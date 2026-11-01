"""2.124.0 C (#2113): one table shared with single people or agents (read | write), on top of the space / list rights.

A share (sheet_shares, one row per table and account) ADDS rights, it never takes any away (sheets/core.py sh_may asks
shs_may first). Who may manage the shares: who may write the table through its space or its list (a share recipient never
re-shares; private tables: the owner is their own admin). Targets: people the person may see (accounts/orgs.py
visible_people; an organisation's table only its members) and the agents of the table's workspace (an organisation's agents;
a private table: private agents without an owner or the person's own) -- the same pool as file store shares.

2.360.2 M (#2561): by e-mail address every share is a row with the sealed address (email_seal) and its keyed hash (email_key),
account or not: GET, the count and the limit treat all alike and the row always reads "invited" (address, never a name), so
nothing tells whether the address has an account; no mail goes out. An account that may hold the share is bound to the row
at once (user_id), otherwise user_id stays NULL until the account of that address signs in (shs_redeem).

The read layer checks every share again (shs_may): a person must still be a member of the table's organisation, an agent
must belong to the table's workspace, never a health / budget list's table, its list limit applies; a revoked share
(revoked_at) counts nothing. A recipient only through a share may not delete / restore the table, attach it to a list, move
it to another workspace, manage its shares or carry rows over (step 2): shs_need_own. Leaving an organisation and moving
the table between workspaces end the shares (org_leave, sheets/shmove.py); a deleted account takes the rows picked by name
along, an address row stays open without access (shs_forget): a row that goes would tell the address had an account.
"""
from flask import g, has_request_context, jsonify

from ..core.config import app, EMAIL_RE
from ..core.access import Denied, acx_org_ok, collab_all, need_feat
from ..core.db import body, bump, db, err, iso_ms, now_utc
from ..core.i18n import N_, tr
from ..core.pg import insert_id, system_ctx
from ..accounts.login import addr_key, seal, unseal
from ..accounts.session import me

SHS_ROLES = ("read", "write")
SHS_MAX = 200
SHS_ONLY_OWN = N_("Only people who may change this table through its workspace can do this")
SHS_SEAL = "sheet-share"  # purpose of email_seal / email_key


def _cache(uid):
    """{sheet id: role} of uid's live shares, once per request (cleared by every change of a share)."""
    if not has_request_context():
        return None
    return g.setdefault("shs_cache", {}).get(uid)


def shs_drop_cache():
    if has_request_context():
        g.pop("shs_cache", None)


def shs_roles_of(c, uid):
    got = _cache(uid)
    if got is None:
        got = {r[0]: r[1] for r in c.execute("SELECT sheet_id, role FROM sheet_shares WHERE user_id=? AND revoked_at IS NULL", (uid,))}
        if has_request_context():
            g.setdefault("shs_cache", {})[uid] = got
    return got


def _agent_row(c, uid):
    return c.execute("SELECT user_id, org_id, owner_id, list_ids FROM agents WHERE user_id=?", (uid,)).fetchone()


def shs_fits(c, uid, r, agent=None):
    """May account uid hold a share of sheet r at all (workspace, list kind, list limit)? agent = its agents row or None."""
    if r["list_id"]:
        l = c.execute("SELECT org_id, life, e2e FROM lists WHERE id=?", (r["list_id"],)).fetchone()
        if agent is not None and l and (l["life"] or "") in ("health", "budget"):
            return False  # a health / budget list stays private: never an agent
        if agent is not None and l and l["e2e"] is not None:
            return False  # 2.124.0 review: a list with a lock never reaches an agent (as sh_may)
    if agent is not None:
        if (agent["org_id"] or None) != (r["org_id"] or None):
            return False  # an agent of another workspace never
        if r["org_id"] is None and agent["owner_id"] not in (None, r["owner_id"]):
            return False  # somebody else's personal agent
        if r["list_id"] and agent["list_ids"]:
            from .vars import _agent_cap
            cap = _agent_cap(c, uid)
            if cap is not None and r["list_id"] not in cap:
                return False
        return True
    if r["org_id"] is None:
        return True
    from ..accounts.orgs import user_orgs
    return r["org_id"] in user_orgs(c, uid) and acx_org_ok(c, uid, r["org_id"])


def shs_may(c, uid, r, write=False):
    """Does a live share give uid the right to read (write: change) sheet r?"""
    role = shs_roles_of(c, uid).get(r["id"])
    if not role or (write and role != "write"):
        return False
    return shs_fits(c, uid, r, _agent_row(c, uid))


def shs_need_own(c, r, code=403):
    """403 (code) unless the current person may write sheet r through its space / list (a share is not enough)."""
    from .core import sh_may
    if not sh_may(c, me(), r, write=True, share=False):
        raise Denied(code, tr(SHS_ONLY_OWN)) if code == 403 else Denied(code)


def shs_shared_ids(c, uid):
    """Ids of the live sheets shared with uid that it may open through the share (not in the trash)."""
    ids = list(shs_roles_of(c, uid))
    if not ids:
        return []
    return [r for r in c.execute(f"SELECT * FROM sheets WHERE deleted_at IS NULL AND id IN ({','.join('?' * len(ids))}) "
                                 f"ORDER BY lower(title), id", ids).fetchall() if shs_may(c, uid, r)]


def shs_index(c, uid, space, rows):
    """sh_index's hook: space "shared" = only the sheets shared with uid; "all" = rows + the shared ones not in them yet."""
    if space == "shared":
        return shs_shared_ids(c, uid)
    if space not in (None, "", "all"):
        return rows
    have = {r["id"] for r in rows}
    return rows + [r for r in shs_shared_ids(c, uid) if r["id"] not in have]


def shs_marks(c, uid, rows, out):
    """sh_brief's hook: shared = number of live shares (for who may manage them), shared_in = uid reads it only through a share."""
    from .core import sh_may
    ids = [r["id"] for r in rows]
    n = {}
    if ids:
        n = {x[0]: x[1] for x in c.execute(f"SELECT sheet_id, COUNT(*) FROM sheet_shares WHERE revoked_at IS NULL AND sheet_id IN "
                                           f"({','.join('?' * len(ids))}) GROUP BY sheet_id", ids)}
    mine = shs_roles_of(c, uid)
    for r, d in zip(rows, out):
        d["shared"] = n.get(r["id"], 0)
        d["shared_in"] = r["id"] in mine and not sh_may(c, uid, r, share=False)
        if d["shared_in"]:
            d["share_role"] = mine[r["id"]]
    return out


def shs_flags(c, r, uid):
    """For GET /api/sheets/<id>: shared_in (only through a share), can_share."""
    from .core import sh_may
    own = sh_may(c, uid, r, share=False)
    return {"shared_in": not own, "can_share": own and sh_may(c, uid, r, write=True, share=False),
            "shared": c.execute("SELECT COUNT(*) FROM sheet_shares WHERE sheet_id=? AND revoked_at IS NULL", (r["id"],)).fetchone()[0]}


def shs_targets(c, r, uid):
    """{people, agents} uid may share sheet r with (never uid itself, never an account outside the table's workspace)."""
    from ..accounts.orgs import visible_people
    vis = visible_people(c, uid)
    org = r["org_id"]
    with system_ctx(c):  # which accounts are agents / members of the table's organisation (ids; vis filters the people)
        ag = {x[0]: x for x in c.execute("SELECT user_id, org_id, owner_id, list_ids FROM agents").fetchall()}
        members = {x[0] for x in c.execute("SELECT user_id FROM org_members WHERE org_id=?", (org,))} if org else None
        users = c.execute("SELECT id, display_name, kind FROM users WHERE disabled=0 ORDER BY display_name").fetchall()
    people, agents = [], []
    for u in users:
        if u["id"] == uid or u["id"] == r["owner_id"]:
            continue
        if u["id"] in ag or (u["kind"] or "") == "agent":
            a = ag.get(u["id"])
            if a is not None and shs_fits(c, u["id"], r, a):
                agents.append({"id": u["id"], "name": u["display_name"]})
            continue
        if not collab_all() or (vis is not None and u["id"] not in vis) or (members is not None and u["id"] not in members):
            continue
        people.append({"id": u["id"], "name": u["display_name"]})
    return {"people": people, "agents": agents}


def shs_list(c, sid):
    from ..collab.comments import user_names
    rows = c.execute("SELECT s.*, u.kind FROM sheet_shares s LEFT JOIN users u ON u.id=s.user_id WHERE s.sheet_id=? AND s.revoked_at IS NULL "
                     "ORDER BY s.id", (sid,)).fetchall()
    names = user_names(c, {x["user_id"] for x in rows if x["user_id"] and not x["email_key"]})
    out = []
    for x in rows:
        if x["email_key"]:  # 2.360.2 M (#2561): one form with or without an account behind the address
            em = _addr(c, x)
            out.append({"id": x["id"], "user_id": None, "name": em, "email": em, "role": x["role"], "agent": False,
                        "state": "invited", "created_at": x["created_at"]})
        else:
            out.append({"id": x["id"], "user_id": x["user_id"], "name": names.get(x["user_id"], ""), "role": x["role"],
                        "agent": (x["kind"] or "") == "agent", "state": "active", "created_at": x["created_at"]})
    return out


def _addr(c, x):
    try:
        return unseal(c, SHS_SEAL, x["email_seal"])
    except Exception:  # noqa: BLE001  (sealed under an older server key: the row stays, it can still be removed)
        return ""


def _bind(c, r, shid, tid, by):
    """2.360.2 M (#2561): the account tid takes the address row shid of sheet r when it may hold a share. A live share of
    its own (picked by name) stays alone: the address row just stays open. True when bound."""
    if tid in (by, r["owner_id"]) or not collab_all() or not shs_fits(c, tid, r):
        return False
    other = c.execute("SELECT id, revoked_at FROM sheet_shares WHERE sheet_id=? AND user_id=? AND id!=?", (r["id"], tid, shid)).fetchone()
    if other and other["revoked_at"] is None:
        return False
    if other:
        c.execute("DELETE FROM sheet_shares WHERE id=?", (other["id"],))
    c.execute("UPDATE sheet_shares SET user_id=? WHERE id=?", (tid, shid))
    return True


def shs_redeem(c, u):
    """2.360.2 M (#2561): at sign-in the open address rows of the account's e-mail address become its shares. u = a users row.
    A row that does not fit yet (an organisation's table, not a member) stays open for a later sign-in. Returns how many."""
    em = (u["email"] or "").strip().lower()
    if not em or em != u["email_proved"] or (u["kind"] or "user") == "agent":  # review: a typed-in address takes nobody's tables
        return 0
    n = 0
    with system_ctx(c):  # tables of organisations the person may not be in yet; the checks are in _bind
        for x in c.execute("SELECT id, sheet_id, created_by FROM sheet_shares WHERE email_key=? AND user_id IS NULL AND revoked_at IS NULL",
                           (addr_key(c, SHS_SEAL, em),)).fetchall():
            r = c.execute("SELECT * FROM sheets WHERE id=?", (x["sheet_id"],)).fetchone()
            n += bool(r and _bind(c, r, x["id"], u["id"], x["created_by"]))
    if n:
        shs_drop_cache()
    return n


def _tell_shared(c, aid, r, role):
    """2.465.0 (#2361): the agent learns that table r was shared with it (like file_shared: only a new share). No list_id in the
    event: a share does not make the agent a member of the list, its Playbook stays out; only the data lock is asked here."""
    try:
        from ..agents.core import agent_emit
        from ..core.dlock import dl_list_locked
        if not (r["list_id"] and dl_list_locked(c, aid, r["list_id"])):
            agent_emit(c, aid, "sheet_shared", {"sheet": {"id": r["id"], "title": r["title"]}, "role": role})
    except Exception as e:  # noqa: BLE001  an event must never block the share itself
        print(f"WARNING sheet_shared event for agent {aid}: {e}", flush=True)


def _tell_unshared(c, sid, uids):
    """2.465.0 (#2361): the share of table sid ended: only its id, the agent may not read the table any more."""
    from ..agents.core import agent_emit
    for aid in uids:
        try:
            if aid and _agent_row(c, aid):
                agent_emit(c, aid, "sheet_unshared", {"sheet": {"id": sid}})
        except Exception as e:  # noqa: BLE001  an event must never block ending the share
            print(f"WARNING sheet_unshared event for agent {aid}: {e}", flush=True)


def shs_end(c, sid, user_ids=None):
    """Revoke the live shares of sheet sid (only those of user_ids when given). Returns how many ended."""
    q, args = "UPDATE sheet_shares SET revoked_at=? WHERE sheet_id=? AND revoked_at IS NULL", [iso_ms(now_utc()), sid]
    if user_ids is not None:
        if not user_ids:
            return 0
        q += f" AND user_id IN ({','.join('?' * len(user_ids))})"
        args += list(user_ids)
    n = c.execute(q + " RETURNING user_id", args).fetchall()
    shs_drop_cache()
    _tell_unshared(c, sid, [x[0] for x in n])
    return len(n)


def shs_leave(c, oid, uids):
    """org_leave's hook: the shares of organisation oid's tables held by the leaver (and their agents) end."""
    if uids:
        # 2.360.2 M (#2561): an address row stays listed as it was (open again): a row that goes would name the leaver's address
        c.execute(f"UPDATE sheet_shares SET user_id=NULL WHERE org_id=? AND email_key!='' AND user_id IN ({','.join('?' * len(uids))})", [oid, *uids])
        ended = c.execute(f"UPDATE sheet_shares SET revoked_at=? WHERE org_id=? AND revoked_at IS NULL AND user_id IN ({','.join('?' * len(uids))}) "
                          "RETURNING sheet_id, user_id", [iso_ms(now_utc()), oid, *uids]).fetchall()
        shs_drop_cache()
        for x in ended:
            _tell_unshared(c, x[0], [x[1]])


def shs_forget(c, uid):
    """2.453.0 (#3781): before an account is deleted its address rows open again (address kept, no access), like shs_leave;
    the rows picked by name go with the account (foreign key)."""
    c.execute("UPDATE sheet_shares SET user_id=NULL WHERE user_id=? AND email_key!=''", (uid,))
    shs_drop_cache()


def _manage(c, sid):
    """The sheet for a person who may manage its shares (agents: 403 -- session.py refuses them on web routes anyway)."""
    from .core import sh_is_agent, sh_need
    uid = me()
    if sh_is_agent(c, uid):
        raise Denied(403)
    r = sh_need(c, sid)
    from .shbook import shb_whole
    shb_whole(r)  # 2.124.0 E (#2116): shares belong to the whole table (its first sheet)
    shs_need_own(c, r)
    return r, uid


def _answer(c, sid, code=200, **extra):
    bump(c)
    c.commit()
    return jsonify(shares=shs_list(c, sid), **extra), code


@app.get("/api/sheets/<int:sid>/shares")
def sheets_shares_get(sid):
    """{shares, people, agents}: the live shares and who the table can be shared with (people who may manage them)."""
    c = db()
    r, uid = _manage(c, sid)
    return jsonify(shares=shs_list(c, sid), **shs_targets(c, r, uid))


@app.post("/api/sheets/<int:sid>/shares")
def sheets_shares_add(sid):
    """{user_id | email, role: read | write}: share the table (the same account again = its role changes; a revoked share
    comes back). By e-mail address the row is the same whether the address has an account or not (2.360.2 M, #2561)."""
    need_feat("sheets")
    c = db()
    r, uid = _manage(c, sid)
    b = body()
    role = b.get("role") or "read"
    if role not in SHS_ROLES:
        return err(tr("Invalid value: {0}", "role"))
    tid = b.get("user_id")
    if b.get("email") and not tid:
        em = str(b["email"]).strip().lower()[:200]
        if not EMAIL_RE.fullmatch(em):
            return err(tr("Please enter a valid e-mail address"))
        return _by_email(c, r, uid, em, role)
    if isinstance(tid, bool) or not isinstance(tid, int):
        return err(tr("Expected {0}", "user_id | email"))
    t = shs_targets(c, r, uid)
    if not any(p["id"] == tid for p in t["people"] + t["agents"]):
        return err(tr("Only people and agents of the same workspace can get a share"), 409)
    old = c.execute("SELECT id, revoked_at, email_key FROM sheet_shares WHERE sheet_id=? AND user_id=?", (sid, tid)).fetchone()
    if old and old["email_key"]:  # 2.360.2 M (#2561): the address row stays as it is, the person gets a row of their own
        c.execute("UPDATE sheet_shares SET user_id=NULL WHERE id=?", (old["id"],))
        old = None
    ts = iso_ms(now_utc())
    is_new = not old or old["revoked_at"] is not None
    if old:
        c.execute("UPDATE sheet_shares SET role=?, revoked_at=NULL, org_id=?, created_by=?, created_at=CASE WHEN revoked_at IS NULL "
                  "THEN created_at ELSE ? END WHERE id=?", (role, r["org_id"], uid, ts, old["id"]))
        shid = old["id"]
    else:
        if c.execute("SELECT COUNT(*) FROM sheet_shares WHERE sheet_id=? AND revoked_at IS NULL", (sid,)).fetchone()[0] >= SHS_MAX:
            return err(tr("Too many shares"), 409)
        shid = insert_id(c, "INSERT INTO sheet_shares(sheet_id,org_id,user_id,role,created_by,created_at) VALUES(?,?,?,?,?,?)",
                         (sid, r["org_id"], tid, role, uid, ts))
    shs_drop_cache()
    if is_new and any(a["id"] == tid for a in t["agents"]):
        _tell_shared(c, tid, r, role)
    return _answer(c, sid, 201, id=shid)


def _by_email(c, r, uid, em, role):
    """2.360.2 M (#2561): one row per table and address, the limit counts it like any share; by address also someone
    outside one's contacts (a client), as list invitations do. The answer and the list are the same for every address."""
    sid, key, ts = r["id"], addr_key(c, SHS_SEAL, em), iso_ms(now_utc())
    old = c.execute("SELECT id, user_id FROM sheet_shares WHERE sheet_id=? AND email_key=?", (sid, key)).fetchone()
    if old:
        c.execute("UPDATE sheet_shares SET role=?, revoked_at=NULL, org_id=?, created_by=?, created_at=CASE WHEN revoked_at IS NULL "
                  "THEN created_at ELSE ? END WHERE id=?", (role, r["org_id"], uid, ts, old["id"]))
        shid = old["id"]
    else:
        if c.execute("SELECT COUNT(*) FROM sheet_shares WHERE sheet_id=? AND revoked_at IS NULL", (sid,)).fetchone()[0] >= SHS_MAX:
            return err(tr("Too many shares"), 409)
        shid = insert_id(c, "INSERT INTO sheet_shares(sheet_id,org_id,user_id,role,created_by,created_at,email_seal,email_key) "
                            "VALUES(?,?,NULL,?,?,?,?,?)", (sid, r["org_id"], role, uid, ts, seal(c, SHS_SEAL, em), key))
    x = c.execute("SELECT id FROM users WHERE lower(email)=? AND disabled=0 AND COALESCE(kind,'user')!='agent'", (em,)).fetchone()
    if x and not (old and old["user_id"]):
        _bind(c, r, shid, x[0], uid)
    shs_drop_cache()
    return _answer(c, sid, 201, by_email=True)


def _need_share(c, sid, shid):
    x = c.execute("SELECT * FROM sheet_shares WHERE id=? AND sheet_id=? AND revoked_at IS NULL", (shid, sid)).fetchone()
    if not x:
        raise Denied(404)
    return x


@app.patch("/api/sheets/<int:sid>/shares/<int:shid>")
def sheets_shares_patch(sid, shid):
    """{role: read | write}"""
    need_feat("sheets")
    c = db()
    _manage(c, sid)
    _need_share(c, sid, shid)
    role = body().get("role")
    if role not in SHS_ROLES:
        return err(tr("Invalid value: {0}", "role"))
    c.execute("UPDATE sheet_shares SET role=? WHERE id=?", (role, shid))
    shs_drop_cache()
    return _answer(c, sid)


@app.delete("/api/sheets/<int:sid>/shares/<int:shid>")
def sheets_shares_delete(sid, shid):
    """Stop sharing (at once; Undo = POST the same account again)."""
    need_feat("sheets")
    c = db()
    _manage(c, sid)
    x = _need_share(c, sid, shid)
    if x["email_key"]:  # 2.360.2 M (#2561): the address is not kept (Undo = POST the address again)
        c.execute("DELETE FROM sheet_shares WHERE id=?", (shid,))
    else:
        c.execute("UPDATE sheet_shares SET revoked_at=? WHERE id=?", (iso_ms(now_utc()), shid))
        _tell_unshared(c, sid, [x["user_id"]])
    shs_drop_cache()
    return _answer(c, sid)
