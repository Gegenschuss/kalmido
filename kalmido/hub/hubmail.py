"""2.84.0 A (#1198): e-mail as an input of the hub -- mails filed with a client or a project (filed, assigned, searchable;
no mail client: nothing is synchronised or rendered as HTML). 2.141.0 A (#2141, #2138): the own mailbox of a workspace and
replies / new mails from the filing (direction out) live in hub/mailbox.py.

Addresses (hub_tokens, plus addresses of the mail input of #971): one per client ("the client's e-mail address"), one per
project and one hub inbox per person and workspace (an organisation or the private space). A mail to a client / project
address is filed there (a project's mail also names the project's client). A mail to the hub inbox is matched by its
sender: the client e-mail, the e-mails of the client's contact persons and of the address book contacts linked to them --
only clients of the same workspace that the recipient sees. Is the sender the person themselves (a forwarded mail), the
original sender of the forwarding header counts, else To / Cc -- audit I4: only when the receiving server confirmed the
own domain (hbm_from_verified: the topmost Authentication-Results, DKIM / DMARC / SPF pass for it); a From with the own
address without that proof may be forged and files the mail "Not assigned" with the From as it stands. No hit or
several clients = "Not assigned" (only the recipient sees it and assigns it by hand).

hub_mails keeps the headers and the plain text (subject, sender, recipients and text sealed with the organisation's key
like the other office texts, core/orgcrypt.py FIELDS); the original .eml and the attachments go into the file store
(folder "E-Mails / <client> / <date> <subject>" of the workspace, fs_put: scan, quota, sealing). A virus find leaves the
attachment out, a full quota all of them (a note on the mail). The search uses hashed words (hub_words, the documents'
index key per workspace, docs/store.py), never a plain index.

Visibility (strict): a project's mail = whoever sees the list, a client's mail = whoever sees the client, a mail that is
not assigned = its recipient; always inside the mail's workspace (client / list of another organisation = nobody).
Writing (assign, delete, restore) = the write right on the list / seeing the client / the recipient. Agents and kid
accounts get nothing (no v1 route, no MCP tool in 2.84.0). Deleting sets deleted_at (Undo restores)."""
import email.utils
import hashlib
import json
import os
import re
import secrets

from flask import g, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, system_ctx
from ..core.i18n import lang, tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..core.access import Denied, WRITE_ROLES, acx_of, list_role, need_list
from ..core.orgcrypt import oc_active, oc_dec_fields, oc_enc_fields
from ..accounts.session import me

HBM_BODY_MAX = 200000   # characters of the plain text kept
HBM_FILES = 20          # attachments of one mail at most
HBM_PAGE = 200          # mails in one list answer
HBM_KINDS = ("inbox", "client", "list")
# audit I4: the authserv-id of the receiving mail server (its Authentication-Results); empty = the topmost such header
HBM_AUTHSERV = os.environ.get("KALMIDO_MAIL_AUTHSERV_ID", "").strip().lower()
_AR_RE = re.compile(r"\s*(dkim|spf|dmarc)\s*=\s*([a-z]+)(.*)", re.I | re.S)
_AR_PROP_RE = re.compile(r"([a-z][\w.-]*)\s*=\s*(\"[^\"]*\"|[^\s;()]+)", re.I)
ROOT = "E-Mails"        # the folder at the root of the workspace's file tree
ADDR_RE = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")


from ..core.db import now_iso as _now  # noqa: E402  2.149.0 G (#2517): was an own copy


def hbm_on():
    from ..integrations.mail import MAIL_IN_ON
    return MAIL_IN_ON


def _gate():
    u = g.user
    if u["kid"] or (u["kind"] or "user") == "agent":
        raise Denied(403, tr("Only people can file e-mails"))


def _ws(org_id, owner_id):
    return f"o{int(org_id)}" if org_id else f"u{int(owner_id or 0)}"


def _visible_client(c, uid, cid):
    """The client row when uid sees client cid (team/clients.py client_rows), else None. 2.84.0 review: in a request the
    clients of uid are read once (hbm_can runs per mail row)."""
    from flask import has_request_context
    from ..team.clients import client_rows
    if not has_request_context():
        return next((r for r in client_rows(c, uid) if r["id"] == cid), None)
    seen = g.setdefault("hbm_clients", {})
    if uid not in seen:
        seen[uid] = {r["id"]: r for r in client_rows(c, uid)}
    return seen[uid].get(cid)


def _list_row(c, lid):
    return c.execute("SELECT id, name, org_id, kind, client_id, e2e FROM lists WHERE id=?", (lid,)).fetchone()


def hbm_can(c, uid, m, write=False):
    """May account uid read (write: assign / delete) hub mail row m? Always inside the mail's workspace."""
    if m["list_id"]:
        l = _list_row(c, m["list_id"])
        if not l or (l["org_id"] or None) != (m["org_id"] or None):
            return False
        role = list_role(c, m["list_id"], uid)
        return role in WRITE_ROLES if write else bool(role)
    if m["client_id"]:
        cl = _visible_client(c, uid, m["client_id"])
        return bool(cl) and (cl["org_id"] or None) == (m["org_id"] or None)
    if m["owner_id"] != uid:
        return False
    return not m["org_id"] or int(m["org_id"]) in acx_of(c, uid).org_ids


def _need_mail(c, mid, write=False, deleted=False):
    m = c.execute("SELECT * FROM hub_mails WHERE id=?", (mid,)).fetchone()
    if not m or (bool(m["deleted_at"]) != deleted) or not hbm_can(c, me(), m):
        raise Denied(404)
    if write and not hbm_can(c, me(), m, write=True):
        raise Denied(403)
    return m


# ---- addresses --------------------------------------------------------------------------------------------------------
def _token_where(kind, uid, org_id, cid, lid):
    if kind == "client":
        return "kind='client' AND client_id=?", (cid,)
    if kind == "list":
        return "kind='list' AND list_id=?", (lid,)
    return "kind='inbox' AND user_id=? AND org_id IS NOT DISTINCT FROM ?", (uid, org_id)


def _target(c, b):
    """(kind, org_id, client_id, list_id) of an address request ({client_id} | {list_id} | {ws: 'private' | 'org:<id>'}),
    with the rights checked: the client seen, the project changeable (and without the lock), the own workspace."""
    uid = me()
    cid, lid, ws = b.get("client_id"), b.get("list_id"), b.get("ws")
    for k, v in (("client_id", cid), ("list_id", lid)):
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            raise Denied(400, tr("Invalid value: {0}", k))
    if cid:
        cl = _visible_client(c, uid, cid)
        if not cl:
            raise Denied(404)
        return "client", cl["org_id"], cid, None
    if lid:
        need_list(c, lid)
        l = _list_row(c, lid)
        if l["kind"] != "project":
            raise Denied(409, tr("Only projects have an e-mail address"))
        if l["e2e"]:
            from ..collab.liste2eguard import le2b_off
            raise Denied(409, le2b_off())
        return "list", l["org_id"], None, lid
    ws = str(ws or "private")
    if ws == "private":
        return "inbox", None, None, None
    m = re.fullmatch(r"org:(\d+)", ws)
    if not m or int(m.group(1)) not in acx_of(c, uid).org_ids:
        raise Denied(404)
    return "inbox", int(m.group(1)), None, None


def _address_of(c, kind, uid, org_id, cid, lid):
    from ..integrations.mail import mail_addr
    w, a = _token_where(kind, uid, org_id, cid, lid)
    r = c.execute(f"SELECT token FROM hub_tokens WHERE {w}", a).fetchone()
    return mail_addr(r[0]) if r else ""


def _args_target():
    a = request.args
    b = {}
    for k in ("client_id", "list_id"):
        if a.get(k):
            try:
                b[k] = int(a.get(k))
            except ValueError:
                raise Denied(400, tr("Invalid value: {0}", k)) from None
    if a.get("ws"):
        b["ws"] = a.get("ws")
    return b


@app.post("/api/hubmail/address")
def hbm_address_new():
    """{client_id | list_id | ws, renew?} -- the e-mail address of a client / project / my hub inbox of a workspace; made
    on the first ask, renew = a new one (the old one stops working)."""
    c = db()
    _gate()
    if not hbm_on():
        return err(tr("E-mail to tasks is not set up on this server"), 409)
    b = body() if isinstance(body(), dict) else {}
    kind, org, cid, lid = _target(c, b)
    uid = me()
    w, a = _token_where(kind, uid, org, cid, lid)
    old = c.execute(f"SELECT token FROM hub_tokens WHERE {w}", a).fetchone()
    if old and not b.get("renew"):
        return jsonify(address=_address_of(c, kind, uid, org, cid, lid), kind=kind)
    tok = secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")
    c.execute(f"DELETE FROM hub_tokens WHERE {w}", a)
    c.execute("INSERT INTO hub_tokens(token,kind,user_id,org_id,client_id,list_id,created_at) VALUES(?,?,?,?,?,?,?)",
              (tok, kind, uid, org, cid, lid, _now()))
    c.commit()
    return jsonify(address=_address_of(c, kind, uid, org, cid, lid), kind=kind, old=bool(old))


@app.delete("/api/hubmail/address")
def hbm_address_del():
    """?client_id= | ?list_id= | ?ws= -- the address stops working."""
    c = db()
    _gate()
    kind, org, cid, lid = _target(c, _args_target())
    w, a = _token_where(kind, me(), org, cid, lid)
    c.execute(f"DELETE FROM hub_tokens WHERE {w}", a)
    c.commit()
    return jsonify(ok=True)


# ---- the rows for the client --------------------------------------------------------------------------------------------
def _open(c, m):
    try:
        return oc_dec_fields(c, m["org_id"], "hub_mails", m) if m["org_id"] else dict(m)
    except Exception:  # noqa: BLE001 -- a key that cannot open the row: show it without its texts
        d = dict(m)
        for k in ("subject", "body", "from_name", "from_addr", "to_addrs"):
            d[k] = ""
        return d


def _files(m):
    try:
        v = json.loads(m["files"] or "[]")
    except ValueError:
        v = []
    return [int(x) for x in v if isinstance(x, int)]


def _names(c, cid, lid):
    cn = c.execute("SELECT name FROM clients WHERE id=?", (cid,)).fetchone() if cid else None
    ln = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone() if lid else None
    return (cn[0] if cn else ""), (ln[0] if ln else "")


def hbm_public(c, m, full=False):
    d = _open(c, m)
    cn, ln = _names(c, m["client_id"], m["list_id"])
    out = {"id": m["id"], "org_id": m["org_id"], "client_id": m["client_id"], "client_name": cn, "list_id": m["list_id"],
           "list_name": ln, "from_addr": d["from_addr"], "from_name": d["from_name"], "subject": d["subject"],
           "sent_at": m["sent_at"], "created_at": m["created_at"], "files": len(_files(m)), "note": m["note"] or "",
           "mine": m["owner_id"] == me(), "deleted": bool(m["deleted_at"])}
    from .mailbox import mbx_state  # 2.141.0 A (#2138): a mail sent from the filing (dir out, to = its recipients; state sending / failed)
    out.update(dir=m["direction"] or "in", state=mbx_state(m), **({"to_list": d["to_addrs"]} if m["direction"] == "out" else {}))
    if full:
        from ..files.store import fs_role
        out["body"] = d["body"]
        out["to"] = d["to_addrs"]
        out["can_write"] = hbm_can(c, me(), m, write=True)
        out["folder_id"] = m["folder_id"] if m["folder_id"] and fs_role(c, m["folder_id"]) else None
        out["attachments"] = []
        out["eml_id"] = m["eml_id"]
        ids = _files(m) + ([m["eml_id"]] if m["eml_id"] else [])
        if ids:
            from ..files.upsafe import up_marks
            rows = c.execute(f"SELECT id, name, size, mime FROM fs_nodes WHERE id IN ({','.join('?' * len(ids))}) AND deleted_at IS NULL",
                             ids).fetchall()
            marks = up_marks(c, "fs", [r["id"] for r in rows]) if rows else {}
            out["attachments"] = [{"id": r["id"], "name": r["name"], "size": r["size"], "mime": r["mime"],
                                   "scan": (marks.get(r["id"]) or {}).get("scan", "")} for r in rows]
    return out


def _search(c, rows, q):
    """The rows whose subject / sender / text hold every word of q (hashed index, prefixes checked against the opened row)."""
    from ..docs import store as DS
    words = DS.index_words(q)[:8]
    if not words or not rows:
        return rows
    by_ws = {}
    for m in rows:
        by_ws.setdefault(m["ws"], []).append(m["id"])
    keep = set()
    for ws, ids in by_ws.items():
        cand, check = set(ids), []
        for w in words:
            h, exact = DS.query_hashes(c, ws, w)
            part = sorted(cand)
            cand = {r[0] for r in c.execute(f"SELECT mail_id FROM hub_words WHERE h=? AND mail_id IN ({','.join('?' * len(part))})",
                                            (h, *part))} if part else set()
            if not exact:
                check.append(w)
        keep |= cand
        if check:
            for m in [x for x in rows if x["id"] in cand]:
                d = _open(c, m)
                have = set(DS.index_words(" ".join(str(d[k] or "") for k in ("subject", "from_name", "from_addr", "body"))))
                if not all(any(x.startswith(w) for x in have) for w in check):
                    keep.discard(m["id"])
    return [m for m in rows if m["id"] in keep]


def _index(c, mid, ws, d):
    from ..docs import store as DS
    c.execute("DELETE FROM hub_words WHERE mail_id=?", (mid,))
    hs = sorted(DS.word_hashes(c, ws, DS.index_words(" ".join(str(d.get(k) or "") for k in ("subject", "from_name", "from_addr", "body")))))
    for i in range(0, len(hs), 500):
        part = hs[i:i + 500]
        c.execute("INSERT INTO hub_words(mail_id, h) VALUES " + ",".join(["(?,?)"] * len(part)) + " ON CONFLICT DO NOTHING",
                  [x for h in part for x in (mid, h)])


@app.get("/api/hubmail/mails")
def hbm_mails():
    """?client_id= | ?list_id= | ?unassigned=1, q= -- the filed mails I see (newest first) and the address of the client /
    project (empty until someone asks for it)."""
    c = db()
    _gate()
    uid = me()
    a = _args_target()
    if a.get("client_id"):
        cl = _visible_client(c, uid, a["client_id"])
        if not cl:
            raise Denied(404)
        rows = c.execute("SELECT * FROM hub_mails WHERE client_id=? AND deleted_at IS NULL AND org_id IS NOT DISTINCT FROM ? "
                         "ORDER BY COALESCE(sent_at, created_at) DESC, id DESC LIMIT 2000", (cl["id"], cl["org_id"])).fetchall()
        addr, can = _address_of(c, "client", uid, cl["org_id"], cl["id"], None), True
    elif a.get("list_id"):
        role = need_list(c, a["list_id"], write=False)
        l = _list_row(c, a["list_id"])
        rows = c.execute("SELECT * FROM hub_mails WHERE list_id=? AND deleted_at IS NULL AND org_id IS NOT DISTINCT FROM ? "
                         "ORDER BY COALESCE(sent_at, created_at) DESC, id DESC LIMIT 2000", (l["id"], l["org_id"])).fetchall()
        addr, can = _address_of(c, "list", uid, l["org_id"], None, l["id"]), role in WRITE_ROLES and l["kind"] == "project" and not l["e2e"]
    elif request.args.get("unassigned") in ("1", "true"):
        rows = c.execute("SELECT * FROM hub_mails WHERE owner_id=? AND client_id IS NULL AND list_id IS NULL AND deleted_at IS NULL "
                         "ORDER BY COALESCE(sent_at, created_at) DESC, id DESC LIMIT 2000", (uid,)).fetchall()
        addr, can = "", True
    else:
        raise Denied(400, tr("Invalid data"))
    rows = [m for m in rows if hbm_can(c, uid, m)]
    q = (request.args.get("q") or "").strip()
    if q:
        rows = _search(c, rows, q)
    from .mailbox import mbx_can_send  # 2.141.0 A (#2138): "New e-mail" from a client's / project's filing
    org = cl["org_id"] if a.get("client_id") else l["org_id"] if a.get("list_id") else None
    send = bool(can) and not request.args.get("unassigned") and mbx_can_send(c, org or None, uid)
    return jsonify(enabled=hbm_on(), address=addr if hbm_on() else "", can_address=bool(can) and hbm_on(), total=len(rows),
                   mails=[hbm_public(c, m) for m in rows[:HBM_PAGE]], can_send=send)


@app.get("/api/hubmail/inbox")
def hbm_inbox():
    """My hub inbox: per workspace (private + my organisations) its address, and the mails not assigned yet."""
    c = db()
    _gate()
    uid = me()
    spaces = [{"ws": "private", "name": tr("Private|workspace"), "address": _address_of(c, "inbox", uid, None, None, None)}]
    for oid in sorted(acx_of(c, uid).org_ids):
        o = c.execute("SELECT name, personal_of FROM orgs WHERE id=?", (oid,)).fetchone()
        if o and not o["personal_of"]:
            spaces.append({"ws": f"org:{oid}", "name": o["name"], "address": _address_of(c, "inbox", uid, oid, None, None)})
    rows = c.execute("SELECT * FROM hub_mails WHERE owner_id=? AND client_id IS NULL AND list_id IS NULL AND deleted_at IS NULL "
                     "ORDER BY COALESCE(sent_at, created_at) DESC, id DESC LIMIT 2000", (uid,)).fetchall()
    rows = [m for m in rows if hbm_can(c, uid, m)]
    q = (request.args.get("q") or "").strip()
    if q:
        rows = _search(c, rows, q)
    return jsonify(enabled=hbm_on(), spaces=spaces if hbm_on() else [], total=len(rows), mails=[hbm_public(c, m) for m in rows[:HBM_PAGE]])


@app.get("/api/hubmail/mails/<int:mid>")
def hbm_mail_get(mid):
    c = db()
    _gate()
    m = _need_mail(c, mid)
    from .mailview import mh_info  # 2.141.0 B (#2140, #2139): the HTML part (+ its external pictures) and what was made from the mail
    return jsonify({**hbm_public(c, m, full=True), **mh_info(c, m)})


@app.get("/api/hubmail/mails/<int:mid>/files/<int:nid>")
def hbm_mail_file(mid, nid):
    """An attachment of a mail I see (its rights are the mail's: the file came with it), ?dl=1 = download."""
    c = db()
    _gate()
    m = _need_mail(c, mid)
    if nid not in _files(m) and nid != m["eml_id"]:
        raise Denied(404)
    n = c.execute("SELECT * FROM fs_nodes WHERE id=? AND deleted_at IS NULL AND kind='file'", (nid,)).fetchone()
    if not n or (n["org_id"] or None) != (m["org_id"] or None):
        raise Denied(404)
    from ..files.web import _send
    return _send(c, dict(n))


@app.get("/api/hubmail/targets")
def hbm_targets():
    """?mail= -- the clients and projects of the mail's workspace I may file it with."""
    c = db()
    _gate()
    uid = me()
    try:
        m = _need_mail(c, int(request.args.get("mail") or 0), write=True)
    except ValueError:
        raise Denied(400, tr("Invalid value: {0}", "mail")) from None
    from ..team.clients import client_rows
    org = m["org_id"] or None
    cls = [{"id": r["id"], "name": r["name"]} for r in client_rows(c, uid, archived=False) if (r["org_id"] or None) == org]
    lids = [r[0] for r in c.execute("SELECT id FROM lists WHERE kind='project' AND archived=0 AND COALESCE(e2e,'')='' "
                                    "AND org_id IS NOT DISTINCT FROM ? ORDER BY lower(name), id", (org,))]
    pr = []
    for lid in lids:
        if list_role(c, lid, uid) in WRITE_ROLES:
            l = _list_row(c, lid)
            pr.append({"id": lid, "name": l["name"], "client_id": l["client_id"]})
    return jsonify(clients=cls, projects=pr)


def _move_folder(c, uid, m, cid, lid):
    """The mail's folder moves along below "E-Mails / <new client / project>" when uid may change it (else it stays)."""
    from ..files.store import ROLE_RANK, _free_name, fs_folder, fs_role
    if not m["folder_id"] or ROLE_RANK[fs_role(c, m["folder_id"], uid)] < ROLE_RANK["edit"]:
        return
    n = c.execute("SELECT * FROM fs_nodes WHERE id=? AND deleted_at IS NULL", (m["folder_id"],)).fetchone()
    if not n:
        return
    cn, ln = _names(c, cid, lid)
    try:
        with c.savepoint():
            parent = fs_folder(c, uid, m["org_id"], [ROOT, cn or ln or tr("Not assigned", lg=lang(c, uid))])
            if parent != n["parent_id"]:
                c.execute("UPDATE fs_nodes SET parent_id=?, name=?, updated_at=? WHERE id=?",
                          (parent, _free_name(c, parent, n["owner_id"], n["org_id"], n["name"], skip=n["id"]), _now(), n["id"]))
    except (Denied, ValueError) as e:
        print("hubmail: folder stays", type(e).__name__, flush=True)


@app.post("/api/hubmail/mails/<int:mid>/assign")
def hbm_mail_assign(mid):
    """{client_id?, list_id?} -- file the mail with a client / project of its workspace (both empty = back to "Not
    assigned", its recipient only). A project brings its client along. Returns the mail and prev (for Undo)."""
    c = db()
    _gate()
    uid = me()
    m = _need_mail(c, mid, write=True)
    b = body() if isinstance(body(), dict) else {}
    cid, lid = b.get("client_id"), b.get("list_id")
    for k, v in (("client_id", cid), ("list_id", lid)):
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            return err(tr("Invalid value: {0}", k))
    org = m["org_id"] or None
    if lid:
        if list_role(c, lid, uid) not in WRITE_ROLES:
            raise Denied(404)
        l = _list_row(c, lid)
        if (l["org_id"] or None) != org:
            return err(tr("The project belongs to another workspace"), 409)
        if l["kind"] != "project" or l["e2e"]:
            return err(tr("Only projects take e-mails"), 409)
        cid = None
        if l["client_id"]:
            cl = _visible_client(c, uid, l["client_id"])
            cid = cl["id"] if cl and (cl["org_id"] or None) == org else None
    elif cid:
        cl = _visible_client(c, uid, cid)
        if not cl:
            raise Denied(404)
        if (cl["org_id"] or None) != org:
            return err(tr("The client belongs to another workspace"), 409)
    elif m["owner_id"] != uid:
        raise Denied(403, tr("Only the recipient can take an e-mail back to Not assigned"))
    prev = {"client_id": m["client_id"], "list_id": m["list_id"]}
    c.execute("UPDATE hub_mails SET client_id=?, list_id=? WHERE id=?", (cid or None, lid or None, mid))
    _move_folder(c, uid, m, cid, lid)
    bump(c)
    c.commit()
    return jsonify(mail=hbm_public(c, c.execute("SELECT * FROM hub_mails WHERE id=?", (mid,)).fetchone()), prev=prev)


@app.delete("/api/hubmail/mails/<int:mid>")
def hbm_mail_del(mid):
    """The mail goes (deleted_at; Undo = POST .../restore). Its folder in the file store stays."""
    c = db()
    _gate()
    _need_mail(c, mid, write=True)
    c.execute("UPDATE hub_mails SET deleted_at=?, deleted_by=? WHERE id=?", (_now(), me(), mid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/hubmail/mails/<int:mid>/restore")
def hbm_mail_restore(mid):
    c = db()
    _gate()
    _need_mail(c, mid, write=True, deleted=True)
    c.execute("UPDATE hub_mails SET deleted_at=NULL, deleted_by=NULL WHERE id=?", (mid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


# ---- the mail input ---------------------------------------------------------------------------------------------------
def _addrs(msg, *hdrs):
    out = []
    for h in hdrs:
        for _n, a in email.utils.getaddresses([str(x) for x in msg.get_all(h, [])]):
            a = a.strip().lower()
            if a and a not in out:
                out.append(a)
    return out


def hbm_match(c, uid, org, addrs):
    """The id of the ONE client of workspace org (None = private) that uid sees and that has one of addrs (client e-mail,
    contact persons, linked address book contacts); None when there is no or more than one."""
    from ..team.clients import client_rows
    addrs = {a.lower() for a in addrs if a}
    if not addrs:
        return None
    cls = [r for r in client_rows(c, uid, archived=True) if (r["org_id"] or None) == (org or None)]
    if not cls:
        return None
    hit = set()
    for r in cls:
        if addrs & {x.lower() for x in ADDR_RE.findall(r["email"] or "")}:
            hit.add(r["id"])
    ids = [r["id"] for r in cls]
    q = ",".join("?" * len(ids))
    links = []
    for r in c.execute(f"SELECT client_id, email, contact_id FROM office_client_contacts WHERE client_id IN ({q})", ids):
        if (r["email"] or "").strip().lower() in addrs:
            hit.add(r["client_id"])
        if r["contact_id"]:
            links.append((r["client_id"], r["contact_id"]))
    if links:
        q2 = ",".join("?" * len(links))
        em = {r["id"]: r["emails"] for r in c.execute(f"SELECT id, emails FROM contacts WHERE id IN ({q2})", [x[1] for x in links])}
        for cid, ctid in links:
            try:
                vals = {str((e or {}).get("value") or "").strip().lower() for e in json.loads(em.get(ctid) or "[]") if isinstance(e, dict)}
            except ValueError:
                vals = set()
            if vals & addrs:
                hit.add(cid)
    return hit.pop() if len(hit) == 1 else None


def hbm_mail_import(c, msg, raw):
    """A mail to a hub address (hub_tokens): filed with its client / project / the recipient's "Not assigned". None = not
    a hub address (the task import goes on); else the mail id, 0 = taken in but not filed (unknown recipient, gone rights,
    a double)."""
    from ..integrations.mail import MAIL_TOKEN_RE, mail_text
    hdrs = " ".join(str(msg.get_all(h, [])) for h in ("To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To"))
    toks = MAIL_TOKEN_RE.findall(hdrs)
    if not toks:
        return None
    with system_ctx(c):  # hub mail: resolving a secret address token (like a public link), the rights are checked below
        r = next((x for x in (c.execute("SELECT * FROM hub_tokens WHERE token=?", (t,)).fetchone() for t in toks) if x), None)
        if not r:
            return None
        out = _import(c, r, msg, raw, mail_text)
    c.commit()
    return out


def hbm_from_verified(msg, addr):
    """Audit I4: did the receiving mail server confirm the domain of addr for this mail? Only the Authentication-Results
    it added itself count -- the one with KALMIDO_MAIL_AUTHSERV_ID, else the topmost (a sender's own headers sit below
    it): dkim=pass with header.d (or header.i), dmarc=pass with header.from or spf=pass with smtp.mailfrom of that domain.
    No such header (a server that adds none) = not confirmed."""
    dom = (addr or "").rpartition("@")[2].strip().lower()
    if not dom:
        return False
    for h in msg.get_all("Authentication-Results") or []:
        h = re.sub(r"\([^()]*\)", " ", re.sub(r"\s+", " ", str(h)))  # comments may carry ";"
        sid = (h.split(";", 1)[0].split() or [""])[0].lower()
        if HBM_AUTHSERV and sid != HBM_AUTHSERV:
            continue
        for part in h.split(";")[1:]:
            m = _AR_RE.match(part)
            if not m or m.group(2).lower() != "pass":
                continue
            props = {k.lower(): v.strip('"').lower() for k, v in _AR_PROP_RE.findall(m.group(3))}
            key = {"dkim": ("header.d", "header.i"), "dmarc": ("header.from",), "spf": ("smtp.mailfrom",)}[m.group(1).lower()]
            if any(props.get(k, "").rpartition("@")[2] == dom for k in key):
                return True
        return False  # only the receiving server's header counts
    return False


def _holder_ok(c, kind, uid, org, cid, lid):
    """May account uid receive for an address of kind (client / list / inbox)? -> (org_id, client_id) or None: the account
    active and a person, the client seen / the project changeable and without the lock, a member of the workspace."""
    u = c.execute("SELECT disabled, kind, kid FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["disabled"] or u["kid"] or (u["kind"] or "user") == "agent":
        return None
    if kind == "client":
        cl = _visible_client(c, uid, cid)
        if not cl:
            return None  # no longer sees the client
        org = cl["org_id"]
    elif kind == "list":
        l = _list_row(c, lid)
        if not l or l["e2e"] or list_role(c, lid, uid) not in WRITE_ROLES:
            return None  # gone, locked or no longer changeable
        org = l["org_id"]
        cl = _visible_client(c, uid, l["client_id"]) if l["client_id"] else None
        cid = cl["id"] if cl and (cl["org_id"] or None) == (org or None) else None
    if org and int(org) not in acx_of(c, uid).org_ids:
        return None  # no longer a member
    return org, cid


def hbm_heir(c, r, not_uid=None):
    """2.84.0 review: another person who may receive for the shared address r (a client's / project's) when the one who made
    it may not any more (left, locked, lost the right, deleted) -- the project's owner and its members with a write role, or the
    members of the client's organisation who see it (a private client has none). None = nobody."""
    if r["kind"] == "list":
        cand = [x[0] for x in c.execute("SELECT owner_id FROM lists WHERE id=? UNION SELECT user_id FROM list_members WHERE list_id=?",
                                        (r["list_id"], r["list_id"]))]
    elif r["kind"] == "client":
        o = c.execute("SELECT org_id FROM clients WHERE id=?", (r["client_id"],)).fetchone()
        cand = [x[0] for x in c.execute("SELECT user_id FROM org_members WHERE org_id=? AND role IN ('admin','member') ORDER BY user_id",
                                        (o["org_id"],))] if o and o["org_id"] else []  # 2.143.0 A (#2151, review): writing roles only
    else:
        return None
    for uid in sorted({x for x in cand if x and x != r["user_id"] and x != not_uid}):
        if _holder_ok(c, r["kind"], uid, r["org_id"], r["client_id"], r["list_id"]):
            return uid
    return None


def hbm_user_purge(c, uid):
    """Account uid goes (accounts/users.py): its client / project addresses pass to another person who may receive, so mails to
    them are not lost; the rest goes with the account (foreign key)."""
    for r in c.execute("SELECT * FROM hub_tokens WHERE user_id=? AND kind IN ('client', 'list')", (uid,)).fetchall():
        h = hbm_heir(c, r, not_uid=uid)
        if h:
            c.execute("UPDATE hub_tokens SET user_id=? WHERE token=?", (h, r["token"]))


def _import(c, r, msg, raw, mail_text):
    from ..files.store import fs_folder, fs_put
    from ..tasks.attachments import unexec_name
    from ..files.upsafe import UploadRefused
    from ..admin.hosting import QuotaExceeded
    uid, cid, lid = r["user_id"], r["client_id"], r["list_id"]
    ok = _holder_ok(c, r["kind"], uid, r["org_id"], cid, lid)
    if not ok and r["kind"] != "inbox":
        h = hbm_heir(c, r)  # 2.84.0 review: the shared address passes on instead of losing the mails for everybody
        if h:
            c.execute("UPDATE hub_tokens SET user_id=? WHERE token=?", (h, r["token"]))
            uid, ok = h, _holder_ok(c, r["kind"], h, r["org_id"], cid, lid)
    if not ok:
        return 0
    org, cid = ok
    u = c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    ws = _ws(org, uid)
    msgid = str(msg.get("Message-ID", "")).strip()[:300] or ("sha:" + hashlib.sha256(raw).hexdigest())
    if c.execute("SELECT 1 FROM hub_mails WHERE ws=? AND message_id=?", (ws, msgid)).fetchone():
        return 0
    from_name, from_addr = email.utils.parseaddr(str(msg.get("From", "")))
    from_addr = from_addr.strip().lower()
    to = _addrs(msg, "To", "Cc")
    subj = re.sub(r"\s+", " ", str(msg.get("Subject", ""))).strip()[:500]
    text, files = mail_text(msg, HBM_BODY_MAX)
    own = (u["email"] or "").strip().lower()
    mine = bool(own) and from_addr == own
    fwd = mine and hbm_from_verified(msg, own)  # audit I4: a From with the own address can be forged
    if fwd:  # a mail the person forwarded / copied in: the original sender counts, the "Fwd:" goes
        from ..integrations.mailtrim import md_forward_from
        name0, addr0 = md_forward_from(text)
        if addr0:
            from_name, from_addr = name0 or from_name, addr0
        subj = re.sub(r"^\s*((fwd?|wg|tr|fw|doorst)\s*:\s*)+", "", subj, flags=re.I).strip() or subj
    if r["kind"] == "inbox":
        from ..integrations.mail import mail_addr
        own_addrs = {own, mail_addr(r["token"]).lower()}
        if mine and not fwd:
            cand = []  # audit I4: unproven -> "Not assigned", the person assigns it by hand
        elif fwd and from_addr == own:
            cand = [a for a in to if a not in own_addrs]  # a copy of a sent mail: the recipients
        else:
            cand = [from_addr]
        cid = hbm_match(c, uid, org, cand)
    sent = None
    try:
        dt = email.utils.parsedate_to_datetime(str(msg.get("Date", "")))
        sent = iso(dt) if dt and dt.tzinfo else None
    except (TypeError, ValueError, IndexError):
        sent = None
    ts = _now()
    plain = {"from_addr": from_addr[:300], "from_name": (from_name or "").strip()[:300], "to_addrs": ", ".join(to)[:2000],
             "subject": subj, "body": text}
    enc = oc_enc_fields(c, org, "hub_mails", plain)
    mid = insert_id(c, """INSERT INTO hub_mails(org_id,owner_id,client_id,list_id,ws,message_id,from_addr,from_name,to_addrs,subject,
                          sent_at,body,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (org, uid, cid, lid, ws, msgid, enc["from_addr"], enc["from_name"], enc["to_addrs"], enc["subject"],
                     sent, enc["body"], ts))
    lg = lang(c, uid)
    cn, ln = _names(c, cid, lid)
    day = (sent or ts)[:10]
    notes, node_ids, folder, eml_id = [], [], None, None
    sealed = bool(org) and oc_active(c)
    try:
        with c.savepoint():
            # 2.84.0: file store names are not sealed -- with the organisation encryption on, no subject in the names
            label = tr("E-mail", lg=lg) + f" {mid}" if sealed else (subj or tr("E-mail", lg=lg))
            folder = fs_folder(c, uid, org, [ROOT, cn or ln or tr("Not assigned", lg=lg), f"{day} {label}"[:120]])
    except (Denied, ValueError) as e:
        print("hubmail: no folder", type(e).__name__, flush=True)
        notes.append(tr("The original mail and its attachments could not be filed", lg=lg))  # 2.84.0 review
    if folder:
        eml = ("mail" if sealed else re.sub(r"[\\/:*?\"<>|]+", "-", subj)[:60].strip() or "mail") + ".eml"
        for name, mime, data in [(eml, "message/rfc822", raw)] + files[:HBM_FILES]:
            if data is not raw:
                name = unexec_name(name)  # 2.84.0 review: an executable ending from outside gets ".txt" (as agents' files)
            try:
                with c.savepoint():
                    nid = fs_put(c, uid, folder, name, data, mime, org)
                if data is raw:
                    eml_id = nid
                else:
                    node_ids.append(nid)
            except UploadRefused:
                notes.append(tr("{0}: left out, the virus scanner found something", name, lg=lg))
            except QuotaExceeded:
                notes.append(tr("The storage is full: the attachments were not filed", lg=lg))
                break
            except (Denied, ValueError) as e:
                notes.append(f"{name}: {e}"[:300] if str(e) else name)
    c.execute("UPDATE hub_mails SET folder_id=?, files=?, eml_id=?, note=? WHERE id=?",
              (folder, json.dumps([x for x in node_ids if x != eml_id]), eml_id, "\n".join(notes)[:2000], mid))
    _index(c, mid, ws, plain)
    return mid
