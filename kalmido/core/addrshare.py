"""2.1071.0 (#5658, decision of #5643): open shares by e-mail address -- one way of the shared core for projects, folders of
projects and knowledge pages (tables keep theirs in sheet_shares, sheets/shshare.py shs_redeem).

A share typed in as an address binds only an account that proved the address (core/access.py addr_account). Without such an
account (nobody has the address, or someone typed it into their account without proving it) the area writes an open row
here (ads_open) and answers as it always does: the answer never says whether the address has an account. When the account
of that address signs in with the address proved -- or proves it while signed in (integrations/mailproof.py) -- the open
rows are made into shares (ads_redeem): each one is the area's own route again, run as the person who typed it in, with
the rights and checks of that moment (still a manager of the project? the person allowed in that workspace?). A row that
binds, or whose object / sharer is gone or who may no longer share it, goes; a row that does not fit yet (an organisation's
project, the person not a member yet) stays for a later sign-in. Rows older than ADS_DAYS go unredeemed.

The replay runs after the request that signed in / proved the address has finished (teardown_request: its transaction is
committed, the proof is visible), each row in a fresh application context with its own connection, so no state of the
request (g caches, the transaction) mixes with the sharer's. The flag is g.ads_redeem = account id (accounts/session.py
start_session, the proxy sign-in, mailproof).

An area registers its kind (ads_kind): the route (a view function taking the JSON body from g.body, like api/common.py
v1_call), the positional arguments of a row, who may see / remove the open rows (dialog), and whether its object is gone.
The route marks a share bound by address with g.ads_bound = True (ads_bound())."""
import json
from datetime import timedelta

from flask import g, has_request_context, jsonify, request

from .config import app, EMAIL_RE
from .db import db, iso, now_utc
from .errors import BadInput
from .i18n import tr
from .access import Denied
from .ctx import me
from .pg import insert_id, system_ctx
from ..accounts.login import addr_key, seal, unseal

ADS_SEAL = "addr-share"  # purpose of email_seal / email_key
ADS_MAX = 200  # open rows one person may have typed in
ADS_PER_ADDR = 50  # open rows of one address (all sharers): the replay at its sign-in stays short (review #5658 F4)
ADS_REDEEM = 50  # rows replayed per sign-in / proof (the next one takes the rest)
ADS_DAYS = 180  # an open row nobody redeemed goes after this
# the parts of a share's request that are kept for its replay (review #5658 F7: no free-form body)
ADS_KEYS = ("role", "expires_at", "tz", "apply", "page_id", "space", "folder", "images", "expires", "kind")
ADS_KINDS = {}


def ads_kind(kind, view, args, may, gone=None):
    """Register an area's kind: view = its share route; args(row) = the route's positional arguments; may(c, uid, row) =
    uid may see / remove the open row (the share's managers); gone(c, row) = its object is gone (the row goes)."""
    ADS_KINDS[kind] = {"view": view, "args": args, "may": may, "gone": gone}


def ads_bound():
    """The area's route bound a share typed in as an address to an account (read by the replay)."""
    if has_request_context():
        g.ads_bound = True


def ads_replaying():
    """2.1138.0 (#6027): the request is the replay of an open row (_replay), not a share typed in now."""
    return bool(has_request_context() and g.get("ads_replay"))


def ads_clean(em):
    em = str(em or "").strip().lower()[:200]
    return em if EMAIL_RE.fullmatch(em) else ""


def ads_open(c, kind, by, em, body, ref_id=None, owner_id=None, path="", org_id=None):
    """An open share of address em, typed in by account by (body = the route's request; only ADS_KEYS are kept). Silent: the
    answer of the route stays the one of every address (no row beyond ADS_MAX / ADS_PER_ADDR, an invalid address, one's own
    address: nothing). True = written."""
    em = ads_clean(em)
    if not em or kind not in ADS_KINDS:
        return False
    if em == str((c.execute("SELECT email FROM users WHERE id=?", (by,)).fetchone() or [""])[0] or "").strip().lower():
        return False  # one's own address
    data = json.dumps({k: (body or {})[k] for k in ADS_KEYS if k in (body or {})}, ensure_ascii=False)
    if len(data) > 4000:
        return False
    key = addr_key(c, ADS_SEAL, em)
    where = "kind=? AND COALESCE(ref_id,0)=? AND COALESCE(owner_id,0)=? AND path=? AND email_key=?"
    args = (kind, int(ref_id or 0), int(owner_id or 0), path or "", key)
    with system_ctx(c):  # counts only; the rows written are the sharer's own (row-level security checks the insert)
        old = c.execute(f"SELECT id FROM obj_addr_shares WHERE {where}", args).fetchone()
        full = not old and (c.execute("SELECT COUNT(*) FROM obj_addr_shares WHERE created_by=?", (by,)).fetchone()[0] >= ADS_MAX
                            or c.execute("SELECT COUNT(*) FROM obj_addr_shares WHERE email_key=?", (key,)).fetchone()[0] >= ADS_PER_ADDR)
    if full:
        return False
    try:
        with c.savepoint():
            if old:
                # 2.1115.0 (#5967): review (M1) - shared again: its time and sharer stay, as a bound share (obj_node_share)
                c.execute("UPDATE obj_addr_shares SET body=CAST(? AS JSONB) WHERE id=?", (data, old["id"]))
            else:
                insert_id(c, "INSERT INTO obj_addr_shares(kind,ref_id,owner_id,org_id,path,body,email_seal,email_key,created_by,created_at) "
                             "VALUES(?,?,?,?,?,CAST(? AS JSONB),?,?,?,?)", (kind, ref_id, owner_id, org_id, path or "", data, seal(c, ADS_SEAL, em), key, by,
                                                            iso(now_utc())))
    except Exception:  # noqa: BLE001  the same address typed in twice at once: one row is enough (review #5658 F9)
        return False
    return True


def _addr(c, x):
    try:
        return unseal(c, ADS_SEAL, x["email_seal"])
    except Exception:  # noqa: BLE001  (sealed under an older server key: the row can still be removed)
        return ""


def ads_dict(c, x):
    try:
        b = json.loads(x["body"] or "{}")
    except ValueError:
        b = {}
    return {"id": int(x["id"]), "email": _addr(c, x), "role": b.get("role"), "expires": b.get("expires") or b.get("expires_at"),
            "created_at": iso(x["created_at"]) if not isinstance(x["created_at"], str) else x["created_at"], "state": "invited"}


def ads_rows(c, kind, ref_id=None, owner_id=None, path=None):
    """The open rows of one object (the dialog: address, role, "invited")."""
    q, a = "SELECT * FROM obj_addr_shares WHERE kind=? AND COALESCE(ref_id,0)=? AND COALESCE(owner_id,0)=?", [kind, int(ref_id or 0), int(owner_id or 0)]
    if path is not None:
        q += " AND path=?"
        a.append(path)
    return c.execute(q + " ORDER BY id LIMIT 500", a).fetchall()


def ads_row(c, aid):
    return c.execute("SELECT * FROM obj_addr_shares WHERE id=?", (int(aid),)).fetchone()


def ads_drop(c, aid):
    c.execute("DELETE FROM obj_addr_shares WHERE id=?", (int(aid),))


def ads_take(c, x, by):
    """2.1115.0 (#5967): an open row taken back in a dialog goes into obj_revoked (src obj_addr_shares, kind / ref_id = its
    object) -- the Undo (ads_back) brings it back under its id, as a share bound to an account comes back (nothing tells the
    two apart). The prune of obj_revoked ends it for good."""
    from .objects import _revoked_add
    _revoked_add(c, "obj_addr_shares", x, "unshare", by, org=x["org_id"], uid=x["owner_id"] or by, kind=x["kind"], ref_id=x["ref_id"])
    ads_drop(c, x["id"])


def ads_taken(c, kind, aid, uid):
    """The obj_revoked row of open row aid (kind) that uid took back (ads_take, the newest), None without one."""
    return c.execute("SELECT * FROM obj_revoked WHERE src='obj_addr_shares' AND kind=? AND user_id=? AND (CAST(row_json AS JSONB)->>'id')=? "
                     "ORDER BY id DESC LIMIT 1", (kind, int(uid), str(int(aid)))).fetchone()


def ads_taken_row(rv):
    """The open row kept in obj_revoked row rv (a dict like a row of obj_addr_shares)."""
    x = rv["row_json"]
    return json.loads(x) if isinstance(x, str) else dict(x or {})


def ads_back(c, rv):
    """The Undo of ads_take: the row back under its id (its address, request and age as they were). False = it cannot come
    back (the same address is open there again, its sharer is gone, ADS_MAX / ADS_PER_ADDR reached): obj_revoked keeps it."""
    x = ads_taken_row(rv)
    with system_ctx(c):  # 2.1115.0 (#5967): review (N2) - the limits of ads_open hold for the Undo too (counts only)
        full = (c.execute("SELECT COUNT(*) FROM obj_addr_shares WHERE created_by=?", (x["created_by"],)).fetchone()[0] >= ADS_MAX
                or c.execute("SELECT COUNT(*) FROM obj_addr_shares WHERE email_key=?", (x["email_key"],)).fetchone()[0] >= ADS_PER_ADDR)
    if full:
        return False
    try:
        with c.savepoint():
            back = c.execute("INSERT INTO obj_addr_shares(id,kind,ref_id,owner_id,org_id,path,body,email_seal,email_key,created_by,created_at) "
                             "VALUES(?,?,?,?,?,?,CAST(? AS JSONB),?,?,?,?) ON CONFLICT DO NOTHING RETURNING id",
                             (int(x["id"]), x["kind"], x.get("ref_id"), x.get("owner_id"), x.get("org_id"), x.get("path") or "",
                              x["body"] if isinstance(x.get("body"), str) else json.dumps(x.get("body") or {}), x["email_seal"],
                              x["email_key"], x["created_by"], x["created_at"])).fetchone()
    except Exception:  # noqa: BLE001  its sharer / object owner is gone (a foreign key): nothing to bring back
        return False
    if back is None:
        return False
    c.execute("DELETE FROM obj_revoked WHERE id=?", (rv["id"],))
    return True


def ads_repath(c, kind, owner_id, old, new):
    """A folder renamed / moved: its open rows follow (the path below it too)."""
    for x in c.execute("SELECT id, path FROM obj_addr_shares WHERE kind=? AND owner_id=?", (kind, owner_id)).fetchall():
        p = x["path"] or ""
        a, b = (p, old) if kind == "list_folder" else (p.lower(), old.lower())  # project folders compare exactly (review F6)
        if a == b or a.startswith(b + "/"):
            try:
                with c.savepoint():
                    c.execute("UPDATE obj_addr_shares SET path=? WHERE id=?", (new + p[len(old):], x["id"]))
            except Exception:  # noqa: BLE001  merged into a folder that has the same address open already: one row stays
                ads_drop(c, x["id"])


def ads_need(c, aid):
    x = ads_row(c, aid)
    k = ADS_KINDS.get(x["kind"]) if x else None
    if not k or (x["created_by"] != me() and not k["may"](c, me(), x)):  # review F8: who typed it in may always remove it
        raise Denied(404)
    return x


@app.get("/api/addr-shares")
def ads_list_route():
    """?kind=list&ref=<project id> | ?kind=list_folder&folder=<path>: the open shares by address of a project / one of my folders
    of projects (who may manage its shares): [{id, email, role, state: invited}]."""
    c = db()
    kind = request.args.get("kind") or ""
    if kind == "list":
        try:
            ref = int(request.args.get("ref") or 0)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "ref"))
        rows = ads_rows(c, kind, ref_id=ref)
        k = ADS_KINDS[kind]
        if not k["may"](c, me(), {"kind": kind, "ref_id": ref, "owner_id": None, "created_by": None, "path": ""}):
            raise Denied(404)
    elif kind == "list_folder":
        from ..lists.lists import clean_folder  # domain, after this module in ORDER
        rows = ads_rows(c, kind, owner_id=me(), path=clean_folder(str(request.args.get("folder") or ""), strict=False))
    else:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    return jsonify(open=[ads_dict(c, x) for x in rows])


@app.delete("/api/addr-shares/<int:aid>")
def ads_delete_route(aid):
    """Remove an open share by address (it is not kept: typed in again = a new row)."""
    c = db()
    ads_drop(c, ads_need(c, aid)["id"])
    c.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- redeeming
def ads_mark(uid):
    """Redeem the open shares of uid's proved address once the request has finished."""
    if has_request_context() and uid:
        g.ads_redeem = int(uid)


@app.teardown_request
def ads_teardown(exc):
    uid = g.pop("ads_redeem", None)
    if not uid or exc is not None:
        return
    try:
        ads_redeem(uid)
    except Exception as e:  # noqa: BLE001  never breaks the answer; the next sign-in tries again
        print("open address shares: redeem failed", type(e).__name__, flush=True)


def _rows_of(uid):
    """(address, [open rows]) of account uid with its address proved; prunes the rows past ADS_DAYS."""
    with app.app_context():
        c = db()
        with system_ctx(c):  # rows of other people's projects / spaces: the replay checks everything as the sharer
            u = c.execute("SELECT id, email, email_proved, kind, disabled FROM users WHERE id=?", (uid,)).fetchone()
            em = (u["email"] or "").strip().lower() if u else ""
            if not u or not em or em != (u["email_proved"] or "") or u["disabled"] or (u["kind"] or "user") == "agent":
                return em, []
            c.execute("DELETE FROM obj_addr_shares WHERE created_at<?", (iso(now_utc() - timedelta(days=ADS_DAYS)),))
            rows = [dict(x) for x in c.execute(f"SELECT * FROM obj_addr_shares WHERE email_key=? ORDER BY id LIMIT {ADS_REDEEM}",
                                               (addr_key(c, ADS_SEAL, em),)).fetchall()]
        c.commit()
        return em, rows


def ads_redeem(uid):
    """The open shares of uid's proved address become shares (each as its sharer's route). Returns how many bound."""
    if not ADS_KINDS:
        return 0
    if has_request_context() and g.get("db") is not None:
        g.pop("db").close()  # the request is over: what it did not commit is gone anyway (close rolls back), no lock of it
        # may block the replay, and its pooled connection goes back before the replay takes one (review F4)
    em, rows = _rows_of(uid)
    n = 0
    for x in rows:
        n += _replay(uid, em, x)
    return n


def _replay(uid, em, x):
    from ..collab.comments import send_pushes  # domain, after this module in ORDER
    k = ADS_KINDS.get(x["kind"])
    if k is None:
        return 0
    with app.app_context(), app.test_request_context("/api/addr-shares/redeem", method="PUT"):
        c = db()
        g.pushes, g.auth_via, g.ads_bound, g.ads_replay = [], None, False, True  # ads_replay: 2.1138.0 (#6027)
        with system_ctx(c):  # review F2: no person in this context yet ("anon" would not see an organisation's project)
            by = c.execute("SELECT * FROM users WHERE id=? AND NOT disabled", (x["created_by"],)).fetchone()
            drop = by is None or by["id"] == uid or bool(k["gone"] and k["gone"](c, x))
        bound = False
        if not drop:
            g.user = by  # the sharer's own step: their rights, their workspace, their name in the News item
            try:
                b = json.loads(x["body"] or "{}")
            except ValueError:
                b = {}
            g.body = {**b, "email": em}
            code = 200
            try:
                r = k["view"](*k["args"](x))
                if isinstance(r, tuple):
                    code = r[1] if len(r) > 1 and isinstance(r[1], int) else 400
            except Denied as e:
                code = getattr(e, "code", 403) or 403
            except BadInput:
                code = 400
            except Exception as e:  # noqa: BLE001  one row never stops the others; it stays for the next sign-in
                code = 500
                print("open address share: replay failed", x["kind"], x["id"], type(e).__name__, flush=True)
            finally:
                g.body = None
            c.rollback()  # a route that failed half-way left its writes open: gone (a route that answered committed)
            bound = bool(g.get("ads_bound"))
            drop = bound or code in (400, 404)  # bound, or the sharer may not share it any more / it is gone
        if drop:
            with system_ctx(c):
                ads_drop(c, x["id"])
            c.commit()
        if bound:
            send_pushes(g.pop("pushes", None))
            print("open address share redeemed", x["kind"], x["id"], flush=True)
        return int(bound)
