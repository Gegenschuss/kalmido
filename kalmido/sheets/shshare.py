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

2.565.0 (#4717, the shared core stage 4): the right itself is a core share -- a row of fs_shares (person: user_id, agent:
agent_id; read = view, write = edit) on the table's reference node (core/objects.py obj_node_share; a table in no folder gets
its node at the top of its workspace's tree, shs_node, as core objects do). A row of sheet_shares is the share's card (the
dialog's id, an address typed in) and names its core share (core_id); it gives nothing itself any more. Reading: the core
share only (2.647.0, #5047: the fallback to the old row with core_id NULL is gone, shs_roles_of). Ending a share
takes the core share back (obj_node_unshare: obj_revoked) and marks / removes the card, so the old row reopens nothing.

2.937.0 (#5244, the shared core stage 7c, one way): the shares with people and agents ARE the core shares of the table's node
-- listed, added, changed and ended there (the dialog's id of such a share is its fs_shares id), a move's undo puts the ones it
took back again (shs_restore). sheet_shares keeps only the addresses typed in (email_seal / email_key): open, or bound to the
account of that address (user_id) whose right is its core share on the node (no card, no core_id). The old rows of people go
at the start after a last forward copy and the start check (shs_retire, core/kernretire.py kern_retire_rows).
"""
from flask import g, has_request_context, jsonify

from ..core import objhooks  # 2.565.0: START (core/db.init_db runs the forward copy)
from ..files.fsref import fs_ref_node, fs_unshare_hooks  # 2.623.0 (#4778)
from ..core.config import app, EMAIL_RE
from ..core.access import Denied, acx_of, acx_org_ok, collab_all, need_feat, trash_sql
from ..core.access import addr_account  # 2.983.0 (#5643)
from ..core.dlock import dl_list_locked  # 2.560.0 B (#4699)
from ..core.db import body, bump, db, err, iso_ms, now_utc
from ..core.i18n import N_, tr
from ..core.pg import insert_id, system_ctx, table_columns
from ..core.kernretire import kern_retire_due, kern_retire_rows  # 2.937.0 (#5244; F1: kern_retire_due)
from ..accounts.login import addr_key, seal, unseal
from ..accounts.session import me
from ..accounts.orgs import user_orgs, visible_people  # 2.369.5 (#2517): pulled up from functions
from .core import sh_may, sh_is_agent, sh_need  # 2.369.5 (#2517): pulled up from functions
from ..collab.comments import user_names  # 2.369.5 (#2517): pulled up from functions
from .vars import _agent_cap  # 2.369.5 (#2517): pulled up from functions

SHS_ROLES = ("read", "write")
SHS_MAX = 200
SHS_ONLY_OWN = N_("Only people who may change this table through its workspace can do this")
SHS_SEAL = "sheet-share"  # purpose of email_seal / email_key
SHS_CORE = {"read": "view", "write": "edit"}  # 2.565.0 (#4717): the dialog's role -> the core share's
SHS_CARD = {"view": "read", "edit": "write"}
SHS_KIND = "sheet"  # the reference kind of a table's node (files/fsref.py FSR, sheets/shfolder.py SHF_KIND)
# 2.937.0 (#5244, stage 7c): a row of sheet_shares is an address typed in (email_key) -- open (user_id NULL) or bound to the
# account of that address (user_id) whose right is its core share on the table's node; revoked_at = ended by a move (its undo)
SHS_ADDR = "{a}email_key!='' AND {a}revoked_at IS NULL"


def _cache(uid):
    """{sheet id: role} of uid's live shares, once per request (cleared by every change of a share)."""
    if not has_request_context():
        return None
    return g.setdefault("shs_cache", {}).get(uid)


def shs_drop_cache():
    if has_request_context():
        g.pop("shs_cache", None)


def shs_core_q(c, cols, where, args=(), trash=True, join=""):
    """2.937.0 (#5244): SELECT cols FROM the live core shares of every table's node AS x (core/objects.py obj_share_rows_sql
    with the reference kind 'sheet'; trash: also nodes in the trash) [join] WHERE where -- the cursor. The one place the
    subquery goes into SQL text: cols / where / join are fixed text of the callers, values go as ? parameters."""
    from ..core.objects import obj_share_rows_sql  # the core loads after the areas (ORDER)
    sub = obj_share_rows_sql(SHS_KIND, trash=trash)
    return c.execute(f"SELECT {cols} FROM {sub} x {join} WHERE {where}", args)


def _core_roles(c, uid):
    """2.565.0 (#4717): {sheet id: read | write} of uid's live core shares -- the shares of the tables' own reference nodes
    (person, agent; 2.937.0 #5244: a group uid is in as well, people only, like the file store's _shares_role), the node in
    the table's workspace (fsref _same_space), not in the trash."""
    if acx_of(c, uid).role == "agent":
        who, args = "x.agent_id=? OR x.user_id=?", (uid, uid)
    elif collab_all():
        who, args = "x.user_id=? OR x.group_id IN (SELECT group_id FROM group_members WHERE user_id=?)", (uid, uid)
    else:
        who, args = "x.user_id=?", (uid,)
    rows = shs_core_q(c, "x.ref_id, x.role", f"({who}) AND COALESCE(t.org_id,0)=COALESCE(x.node_org,0) AND (t.org_id IS NOT NULL "
                      "OR x.node_owner=t.owner_id)", args, trash=False, join="JOIN sheets t ON t.id=x.ref_id").fetchall()
    out = {}
    for sid, role in rows:
        role = SHS_CARD.get(role)
        if role and out.get(sid) != "write":
            out[sid] = role
    return out


def shs_roles_of(c, uid):
    got = _cache(uid)
    if got is None:
        # 2.565.0 (#4717): the core share is the right; 2.937.0 (#5244): nothing else (sheet_shares holds addresses only)
        got = _core_roles(c, uid)
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
        if r["list_id"] and dl_list_locked(c, uid, r["list_id"]):
            return False  # 2.560.0 B (#4699): a table of a list the agent's data lock leaves out (also not offered as a target)
        if r["list_id"] and agent["list_ids"]:
            cap = _agent_cap(c, uid)
            if cap is not None and r["list_id"] not in cap:
                return False
        return True
    if r["org_id"] is None:
        return True
    return r["org_id"] in user_orgs(c, uid) and acx_org_ok(c, uid, r["org_id"])


def shs_may(c, uid, r, write=False):
    """Does a live share give uid the right to read (write: change) sheet r?"""
    role = shs_roles_of(c, uid).get(r["id"])
    if not role or (write and role != "write"):
        return False
    return shs_fits(c, uid, r, _agent_row(c, uid))


def shs_need_own(c, r, code=403):
    """403 (code) unless the current person may write sheet r through its space / list (a share is not enough)."""
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


def shs_count(c, ids):
    """2.937.0 (#5244): {sheet id: number of live shares} -- the people / agents of its node (a bound address counts through
    its core share) + the addresses not bound yet."""
    ids = [int(x) for x in ids]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    n = {x[0]: x[1] for x in shs_core_q(c, "x.ref_id, COUNT(*)", f"x.group_id IS NULL AND x.ref_id IN ({q}) GROUP BY x.ref_id", ids)}
    for sid, k in c.execute(f"SELECT sheet_id, COUNT(*) FROM sheet_shares WHERE {SHS_ADDR.format(a='')} AND user_id IS NULL AND "
                            f"sheet_id IN ({q}) GROUP BY sheet_id", ids):
        n[sid] = n.get(sid, 0) + k
    return n


def shs_marks(c, uid, rows, out):
    """sh_brief's hook: shared = number of live shares (for who may manage them), shared_in = uid reads it only through a share."""
    n = shs_count(c, [r["id"] for r in rows])
    mine = shs_roles_of(c, uid)
    for r, d in zip(rows, out):
        d["shared"] = n.get(r["id"], 0)
        d["shared_in"] = r["id"] in mine and not sh_may(c, uid, r, share=False)
        if d["shared_in"]:
            d["share_role"] = mine[r["id"]]
    return out


def shs_flags(c, r, uid):
    """For GET /api/sheets/<id>: shared_in (only through a share), can_share."""
    own = sh_may(c, uid, r, share=False)
    return {"shared_in": not own, "can_share": own and sh_may(c, uid, r, write=True, share=False),
            "shared": shs_count(c, [r["id"]]).get(r["id"], 0)}


def shs_targets(c, r, uid):
    """{people, agents} uid may share sheet r with (never uid itself, never an account outside the table's workspace)."""
    vis = visible_people(c, uid)
    org = r["org_id"]
    with system_ctx(c):  # which accounts are agents / members of the table's organisation (ids; vis filters the people)
        ag = {x[0]: x for x in c.execute("SELECT user_id, org_id, owner_id, list_ids FROM agents").fetchall()}
        members = {x[0] for x in c.execute("SELECT user_id FROM org_members WHERE org_id=?", (org,))} if org else None
        users = c.execute("SELECT id, display_name, kind FROM users WHERE NOT disabled ORDER BY display_name").fetchall()
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


def _shares_of(c, sid):
    """2.937.0 (#5244): the live core shares of table sid's node with a person or an agent: [{share_id, who, agent, role, created_at}]."""
    return [{"share_id": x["share_id"], "who": x["user_id"] or x["agent_id"], "agent": bool(x["agent_id"]), "role": x["role"],
             "created_at": x["created_at"]}
            for x in shs_core_q(c, "x.*", "x.ref_id=? AND x.group_id IS NULL ORDER BY x.share_id", (sid,)).fetchall()]


def _addr_rows(c, sid):
    return c.execute(f"SELECT * FROM sheet_shares WHERE sheet_id=? AND {SHS_ADDR.format(a='')} ORDER BY id", (sid,)).fetchall()


def shs_list(c, sid):
    """The dialog's rows. 2.937.0 (#5244): a person / agent is the core share of the table's node (id = its fs_shares id); an
    address typed in is its row of sheet_shares (id = minus its id, so the two never meet in one list) and always reads
    "invited" -- bound to an account, its role is the core share's, and that share is not listed by name (2.360.2 M, #2561:
    nothing tells whether the address has an account). A bound address whose core share is gone (taken back elsewhere, run
    out) is no share any more and not listed."""
    core = _shares_of(c, sid)
    have = {x["who"]: x for x in core}
    addr = _addr_rows(c, sid)
    bound = {x["user_id"] for x in addr if x["user_id"]}
    out = []
    for x in addr:
        s = have.get(x["user_id"]) if x["user_id"] else None
        if x["user_id"] and s is None:
            continue
        em = _addr(c, x)
        out.append({"id": -x["id"], "user_id": None, "name": em, "email": em, "role": SHS_CARD.get(s["role"], "read") if s else x["role"],
                    "agent": False, "state": "invited", "created_at": x["created_at"]})
    names = user_names(c, {x["who"] for x in core if x["who"] not in bound})
    for s in core:
        if s["who"] in bound:
            continue
        out.append({"id": s["share_id"], "user_id": s["who"], "name": names.get(s["who"], ""), "role": SHS_CARD.get(s["role"], "read"),
                    "agent": s["agent"], "state": "active", "created_at": s["created_at"]})
    out.sort(key=lambda d: (str(d["created_at"] or ""), abs(d["id"])))
    return out


def _addr(c, x):
    try:
        return unseal(c, SHS_SEAL, x["email_seal"])
    except Exception:  # noqa: BLE001  (sealed under an older server key: the row stays, it can still be removed)
        return ""


def shs_core_of(c, sid, who):
    """The core share row of account who on table sid's node, or None."""
    n = fs_ref_node(c, SHS_KIND, sid)
    if n is None:
        return None
    return c.execute("SELECT * FROM fs_shares WHERE node_id=? AND (user_id=? OR agent_id=?)", (n["id"], int(who), int(who))).fetchone()


def _bind(c, r, aid, tid, by):
    """2.360.2 M (#2561): the account tid takes the address row aid of sheet r when it may hold a share. A share of its own
    (picked by name, or another address) stays alone: the address row just stays open. True when bound. 2.937.0 (#5244):
    the right is tid's core share on the table's node."""
    if tid in (by, r["owner_id"]) or not collab_all() or not shs_fits(c, tid, r):
        return False
    if shs_core_of(c, r["id"], tid) is not None:
        return False
    x = c.execute("SELECT role FROM sheet_shares WHERE id=?", (aid,)).fetchone()
    c.execute("UPDATE sheet_shares SET user_id=? WHERE id=?", (tid, aid))
    shs_put(c, by, r, tid, x["role"] if x else "read")
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
            if r is None or r["deleted_at"] or r["book_id"]:
                continue  # 2.937.0 (#5244): a table in the trash waits (its node gets no new share there)
            try:
                with c.savepoint():
                    n += bool(_bind(c, r, x["id"], u["id"], x["created_by"]))
            except Denied:  # too many shares on the node: the row stays open for a later sign-in
                pass
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


# ---------------------------------------------------------------- 2.565.0 (#4717): the core share of a table
def shs_node(c, uid, r):
    """The reference node of table r (its first sheet) that carries its core shares; a table in no folder gets one at the top
    of its workspace's tree (core/objects.py obj_node: private = the table's owner's tree; an organisation's: owned by uid
    when uid is a member, else by one of its admins, files/fsroots.py). The tables' panel shows such a table in no folder
    (shf_marks: no folder above the node)."""
    from ..files.store import _free_name, _now, fs_log_add, safe_fs_name
    n = fs_ref_node(c, SHS_KIND, r["id"])
    if n is not None:
        return n
    org = r["org_id"] or None
    if org:
        with system_ctx(c):  # is uid a person of the organisation (structure)?
            mem = uid and c.execute("SELECT 1 FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.user_id=? "
                                    "AND COALESCE(u.kind,'')!='agent'", (org, uid)).fetchone()
        if mem:
            owner = uid
        else:
            from ..files.fsroots import _org_owner
            owner = _org_owner(c, org, uid or 0)
    else:
        owner = r["owner_id"]
    nm = safe_fs_name(r["title"] or "") or tr("Table")
    ts = _now()
    nid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,ref_kind,ref_id,created_by,created_at,updated_at)
                          VALUES(NULL,'ref',?,?,?,'sheet',?,?,?,?)""", (_free_name(c, None, owner, org, nm), owner, org, r["id"], uid or owner, ts, ts))
    fs_log_add(c, nid, "create")
    return c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()


def shs_put(c, uid, r, who, role, expires_at=None):
    """2.937.0 (#5244): account who (a person or an agent) gets / keeps its core share of table r with role read | write
    (core/objects.py obj_node_share on the table's node; the same account again changes the role). The caller checked who may
    share and with whom. Returns the share id; Denied(409) when the node is full."""
    from ..core.objects import obj_node_share
    key = "agent_id" if _agent_row(c, who) is not None else "user_id"
    fid = obj_node_share(c, uid, shs_node(c, uid, r), key, int(who), SHS_CORE.get(role, "view"), expires_at, r["org_id"] or None, event=False)
    shs_drop_cache()
    return fid


def shs_take(c, uid, sid, s, reason="unshare", org=None):
    """2.937.0 (#5244): core share s (a row of fs_shares on table sid's node) goes into obj_revoked (core/objects.py
    obj_node_unshare: restorable, shs_restore) -- also an address bound to that account (2.360.2 M, #2561: the address is
    not kept). Returns the obj_revoked id."""
    from ..core.objects import obj_node_unshare
    n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (s["node_id"],)).fetchone()
    out = obj_node_unshare(c, uid, n, s["id"], kind=SHS_KIND, ref_id=sid, org=org, reason=reason) if n is not None else None
    who = s["user_id"] or s["agent_id"]
    if who:
        c.execute("DELETE FROM sheet_shares WHERE sheet_id=? AND user_id=? AND email_key!=''", (sid, who))
    shs_drop_cache()
    return out


def shs_restore(c, uid, r, revoked_id):
    """2.937.0 (#5244): a core share of table r taken back (shs_take, shs_end: a row of obj_revoked with kind 'sheet') comes
    back on the table's node when its account may still hold it (shs_fits) and has none there -- the tables' way of
    core/objects.py obj_share_restore (a table is no core kind; the caller checked who may). Returns the share id or None."""
    import json
    x = c.execute("SELECT * FROM obj_revoked WHERE id=? AND src='fs_shares' AND kind=? AND ref_id=?",
                  (int(revoked_id), SHS_KIND, r["id"])).fetchone()
    if x is None:
        return None
    s = json.loads(x["row_json"])
    who = s.get("user_id") or s.get("agent_id")
    c.execute("DELETE FROM obj_revoked WHERE id=?", (x["id"],))
    if not who or shs_core_of(c, r["id"], who) is not None or not shs_fits(c, who, r, _agent_row(c, who)):
        return None
    if s.get("agent_id") and not _agent_row(c, who):
        return None
    try:
        with c.savepoint():
            return shs_put(c, uid, r, who, SHS_CARD.get(s.get("role"), "read"), s.get("expires_at"))
    except Denied:  # no room on the node: it stays taken back
        return None


def shs_fs_unshare(c, uid, n, s, reason="unshare"):  # 2.649.0 (#5051): reason (the boundary repair passes "boundary")
    """2.623.0 (#4778): the file store's dialog takes share row s of a table's node n back (files/web.py files_share_delete,
    files/fsref.py fs_unshare_hooks; the caller checked who may): the row goes into obj_revoked like in the table's own dialog,
    an address bound to that account goes (as in sheets_shares_delete), an agent hears of it."""
    if n["kind"] != "ref" or n["ref_kind"] != SHS_KIND:
        return False
    t = c.execute("SELECT org_id FROM sheets WHERE id=?", (n["ref_id"],)).fetchone()
    shs_take(c, uid, n["ref_id"], s, reason, org=(t["org_id"] if t else n["org_id"]) or None)
    if s["agent_id"]:
        _tell_unshared(c, n["ref_id"], [s["agent_id"]])
    return True


def shs_end(c, sid, reason="move"):
    """Every share of sheet sid ends (a move to another workspace): the core shares of its node go into obj_revoked, the
    addresses typed in are marked ended (revoked_at; the move's undo opens them again). Returns (address row ids, obj_revoked
    ids). 2.937.0 (#5244): the core shares are the shares."""
    t = c.execute("SELECT org_id FROM sheets WHERE id=?", (sid,)).fetchone()
    org = (t["org_id"] if t else None) or None
    n = fs_ref_node(c, SHS_KIND, sid)
    rows = c.execute("SELECT * FROM fs_shares WHERE node_id=? AND (user_id IS NOT NULL OR agent_id IS NOT NULL)", (n["id"],)).fetchall() if n else []
    addr = [x[0] for x in c.execute("UPDATE sheet_shares SET revoked_at=? WHERE sheet_id=? AND revoked_at IS NULL RETURNING id",
                                    (iso_ms(now_utc()), sid)).fetchall()]
    from ..core.objects import obj_node_unshare
    revoked = []
    for s in rows:
        rid = obj_node_unshare(c, None, n, s["id"], kind=SHS_KIND, ref_id=sid, org=org, reason=reason)
        if rid:
            revoked.append(rid)
    shs_drop_cache()
    _tell_unshared(c, sid, [s["agent_id"] for s in rows if s["agent_id"]])
    return addr, revoked


def shs_leave(c, oid, uids):
    """org_leave's hook: the shares of organisation oid's tables held by the leaver (and their agents) end. 2.360.2 M (#2561):
    an address row stays listed as it was (open again): a row that goes would name the leaver's address."""
    if not uids:
        return
    from ..core.objects import obj_node_unshare
    q = ",".join("?" * len(uids))
    rows = c.execute(f"""SELECT s.*, n.ref_id FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id JOIN sheets t ON t.id=n.ref_id
                         WHERE n.kind='ref' AND n.ref_kind='sheet' AND t.org_id=? AND (s.user_id IN ({q}) OR s.agent_id IN ({q}))""",
                     [oid, *uids, *uids]).fetchall()
    c.execute(f"UPDATE sheet_shares SET user_id=NULL WHERE org_id=? AND email_key!='' AND user_id IN ({q})", [oid, *uids])
    with system_ctx(c):  # the node lies in the organisation's tree the leaver is leaving
        for s in rows:
            n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (s["node_id"],)).fetchone()
            obj_node_unshare(c, None, n, s["id"], kind=SHS_KIND, ref_id=s["ref_id"], org=oid, reason="leave")
    shs_drop_cache()
    for s in rows:
        if s["agent_id"]:
            _tell_unshared(c, s["ref_id"], [s["agent_id"]])


def shs_forget(c, uid):
    """2.453.0 (#3781): before an account is deleted its address rows open again (address kept, no access), like shs_leave;
    its core shares go with the account (foreign key of fs_shares)."""
    c.execute("UPDATE sheet_shares SET user_id=NULL WHERE user_id=? AND email_key!=''", (uid,))
    shs_drop_cache()


def _manage(c, sid):
    """The sheet for a person who may manage its shares (agents: 403 -- session.py refuses them on web routes anyway)."""
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


def _full(c, sid):
    if shs_count(c, [sid]).get(sid, 0) >= SHS_MAX:
        raise Denied(409, tr("Too many shares"))


@app.get("/api/sheets/<int:sid>/shares")
def sheets_shares_get(sid):
    """{shares, people, agents}: the live shares and who the table can be shared with (people who may manage them)."""
    c = db()
    r, uid = _manage(c, sid)
    return jsonify(shares=shs_list(c, sid), **shs_targets(c, r, uid))


@app.post("/api/sheets/<int:sid>/shares")
def sheets_shares_add(sid):
    """{user_id | email, role: read | write}: share the table (the same account again = its role changes). By e-mail address
    the row is the same whether the address has an account or not (2.360.2 M, #2561). 2.937.0 (#5244): id = the core share's."""
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
    # 2.360.2 M (#2561): an address bound to the person stays as it is, open again; the person gets the share by name
    c.execute("UPDATE sheet_shares SET user_id=NULL WHERE sheet_id=? AND user_id=? AND email_key!=''", (sid, tid))
    is_new = shs_core_of(c, sid, tid) is None
    if is_new:
        _full(c, sid)
    fid = shs_put(c, uid, r, tid, role)
    if is_new and any(a["id"] == tid for a in t["agents"]):
        _tell_shared(c, tid, r, role)
    return _answer(c, sid, 201, id=fid)


def _by_email(c, r, uid, em, role):
    """2.360.2 M (#2561): one row per table and address, the limit counts it like any share; by address also someone
    outside one's contacts (a client), as list invitations do. The answer and the list are the same for every address."""
    sid, key, ts = r["id"], addr_key(c, SHS_SEAL, em), iso_ms(now_utc())
    old = c.execute("SELECT id, user_id, revoked_at FROM sheet_shares WHERE sheet_id=? AND email_key=?", (sid, key)).fetchone()
    if old:
        if old["revoked_at"] is not None:
            _full(c, sid)
        c.execute("UPDATE sheet_shares SET role=?, revoked_at=NULL, org_id=?, created_by=?, created_at=CASE WHEN revoked_at IS NULL "
                  "THEN created_at ELSE ? END WHERE id=?", (role, r["org_id"], uid, ts, old["id"]))
        aid = old["id"]
    else:
        _full(c, sid)
        aid = insert_id(c, "INSERT INTO sheet_shares(sheet_id,org_id,user_id,role,created_by,created_at,email_seal,email_key) "
                           "VALUES(?,?,NULL,?,?,?,?,?)", (sid, r["org_id"], role, uid, ts, seal(c, SHS_SEAL, em), key))
    bound = old["user_id"] if old else None
    x = addr_account(c, em)  # 2.983.0 (#5643): only a proved address; else the row stays open until shs_redeem at sign-in
    if bound and x == bound and shs_fits(c, bound, r):
        shs_put(c, uid, r, bound, role)  # the bound row comes back / changes role: its core share follows
    else:
        if bound:  # 2.937.0 (#5244): its account may no longer hold it: open again
            c.execute("UPDATE sheet_shares SET user_id=NULL WHERE id=?", (aid,))
            s = shs_core_of(c, sid, bound) if x != bound else None
            if s is not None:  # 2.983.0 (#5643, Fable F1): bound before the proof counted, or the address changed since:
                from ..core.objects import obj_node_unshare  # the core share it held through this address ends too
                n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (s["node_id"],)).fetchone()
                obj_node_unshare(c, uid, n, s["id"], kind=SHS_KIND, ref_id=sid, org=r["org_id"], reason="unshare")
        if x:
            _bind(c, r, aid, x, uid)
    shs_drop_cache()
    return _answer(c, sid, 201, by_email=True)


def _need_share(c, sid, shid):
    """2.937.0 (#5244): ("addr", the sheet_shares row) for a negative id (an address), ("core", the fs_shares row) for a
    person's / agent's core share of the table's node; 404 otherwise."""
    if shid < 0:
        x = c.execute(f"SELECT * FROM sheet_shares WHERE id=? AND sheet_id=? AND {SHS_ADDR.format(a='')}", (-shid, sid)).fetchone()
        if x and (not x["user_id"] or shs_core_of(c, sid, x["user_id"]) is not None):
            return "addr", x
        raise Denied(404)
    n = fs_ref_node(c, SHS_KIND, sid)
    s = c.execute("SELECT * FROM fs_shares WHERE id=? AND node_id=? AND (user_id IS NOT NULL OR agent_id IS NOT NULL)",
                  (shid, n["id"] if n else 0)).fetchone()
    if not s:
        raise Denied(404)
    return "core", s


@app.patch("/api/sheets/<int:sid>/shares/<int(signed=True):shid>")
def sheets_shares_patch(sid, shid):
    """{role: read | write}"""
    need_feat("sheets")
    c = db()
    r, uid = _manage(c, sid)
    kind, x = _need_share(c, sid, shid)
    role = body().get("role")
    if role not in SHS_ROLES:
        return err(tr("Invalid value: {0}", "role"))
    if kind == "addr":
        c.execute("UPDATE sheet_shares SET role=? WHERE id=?", (role, x["id"]))
        if x["user_id"] and addr_account(c, _addr(c, x)) == x["user_id"] and shs_fits(c, x["user_id"], r):
            shs_put(c, uid, r, x["user_id"], role, shs_core_of(c, sid, x["user_id"])["expires_at"])
        elif x["user_id"]:  # 2.1071.0 (#5658, Fable 2.983 N2): bound before the proof counted (or the address changed since): no role
            # change for that account -- the row opens again (shs_redeem binds it at a sign-in with the address proved) and the
            # core share it held through this address ends, as _by_email does
            c.execute("UPDATE sheet_shares SET user_id=NULL WHERE id=?", (x["id"],))
            s = shs_core_of(c, sid, x["user_id"])
            if s is not None:
                from ..core.objects import obj_node_unshare
                n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (s["node_id"],)).fetchone()
                obj_node_unshare(c, uid, n, s["id"], kind=SHS_KIND, ref_id=sid, org=r["org_id"], reason="unshare")
    else:
        shs_put(c, uid, r, x["user_id"] or x["agent_id"], role, x["expires_at"])  # an end date from the file store stays
    shs_drop_cache()
    return _answer(c, sid)


@app.delete("/api/sheets/<int:sid>/shares/<int(signed=True):shid>")
def sheets_shares_delete(sid, shid):
    """Stop sharing (at once; Undo = POST the same account / address again)."""
    need_feat("sheets")
    c = db()
    r, uid = _manage(c, sid)
    kind, x = _need_share(c, sid, shid)
    if kind == "addr":
        s = shs_core_of(c, sid, x["user_id"]) if x["user_id"] else None
        if s is not None:
            shs_take(c, uid, sid, s, org=r["org_id"] or None)  # the core share goes (obj_revoked) and the address with it
        c.execute("DELETE FROM sheet_shares WHERE id=?", (x["id"],))  # 2.360.2 M (#2561): the address is not kept
    else:
        shs_take(c, uid, sid, x, org=r["org_id"] or None)
        if x["agent_id"]:
            _tell_unshared(c, sid, [x["agent_id"]])
    shs_drop_cache()
    return _answer(c, sid)


fs_unshare_hooks.append(shs_fs_unshare)  # 2.623.0 (#4778)


def _shs_last_copy(c, sheet_id=None, by=None):
    """The forward copy of the old person rows (core/db.py init_db once: migr_core4717, migr_core5047 up to 2.936; 2.937.0
    #5244: the last one runs in shs_retire before the start check): every live row bound to an account without a core share
    gets one. Only while the column core_id is there (a database before stage 7c)."""
    if "core_id" not in table_columns(c, "sheet_shares"):
        return 0
    q = ("SELECT s.id, s.sheet_id, s.user_id, s.role, s.created_by FROM sheet_shares s JOIN sheets t ON t.id=s.sheet_id WHERE "
         "s.revoked_at IS NULL AND s.core_id IS NULL AND s.user_id IS NOT NULL AND t.book_id IS NULL AND (t.deleted_at IS NULL OR "
         "EXISTS (SELECT 1 FROM fs_nodes n WHERE n.kind='ref' AND n.ref_kind='sheet' AND n.ref_id=t.id))")
    n = 0
    with system_ctx(c):  # every workspace's tables (a start-up step)
        for x in c.execute(q + (" AND s.sheet_id=?" if sheet_id else "") + " ORDER BY s.id", (sheet_id,) if sheet_id else ()).fetchall():
            r = c.execute("SELECT * FROM sheets WHERE id=?", (x["sheet_id"],)).fetchone()
            old = shs_core_of(c, r["id"], x["user_id"])
            try:
                with c.savepoint():
                    # 2.647.0 (#5047, review): a core share the account holds already stays as it is (role, expiry)
                    fid = old["id"] if old is not None else shs_put(c, by or x["created_by"], r, x["user_id"], x["role"])
                    c.execute("UPDATE sheet_shares SET core_id=? WHERE id=?", (fid, x["id"]))
                    n += 1
            except Denied:  # too many shares on the node: the start check names it
                print(f"WARNING sheet share card {x['id']} found no room on its table's node (#5244)", flush=True)
    return n


# ---------------------------------------------------------------- 2.937.0 (#5244): stage 7c, the old rows of people go (one way)
SHS_RETIRE_LABEL = "tables, stage 7c (#5244)"
_SHS_LEFT = ("SELECT COUNT(*) FROM sheet_shares s JOIN sheets t ON t.id=s.sheet_id WHERE s.revoked_at IS NULL AND s.user_id IS NOT NULL "
             "AND s.core_id IS NULL AND t.book_id IS NULL AND (t.deleted_at IS NULL OR EXISTS (SELECT 1 FROM fs_nodes n WHERE n.kind='ref' "
             "AND n.ref_kind='sheet' AND n.ref_id=t.id)) AND NOT EXISTS (SELECT 1 FROM fs_shares f JOIN fs_nodes n ON n.id=f.node_id "
             "WHERE n.kind='ref' AND n.ref_kind='sheet' AND n.ref_id=s.sheet_id AND (f.user_id=s.user_id OR f.agent_id=s.user_id))")
# Fable review of 2.937 F6: a table in the trash without its node lost its node's shares with the node; up to 2.936 its
# restore copied the bound address forward again (shs_core_move). Its bound address opens again instead (user_id NULL, no
# right): the next sign-in with the address proved takes it once the table is back (shs_redeem waits while it is in the
# trash). Only the rest -- a table with its node or out of the trash -- is deleted below.
_SHS_NODE = "EXISTS (SELECT 1 FROM fs_nodes n WHERE n.kind='ref' AND n.ref_kind='sheet' AND n.ref_id=s.sheet_id)"
_SHS_REOPEN = ("UPDATE sheet_shares s SET user_id=NULL FROM sheets t WHERE t.id=s.sheet_id AND " + trash_sql("t") + " AND s.email_key!='' "
               "AND s.user_id IS NOT NULL AND s.revoked_at IS NULL AND NOT " + _SHS_NODE)
_SHS_DEAD = ("DELETE FROM sheet_shares s WHERE s.email_key!='' AND s.user_id IS NOT NULL AND s.revoked_at IS NULL AND NOT EXISTS "
             "(SELECT 1 FROM fs_shares f JOIN fs_nodes n ON n.id=f.node_id WHERE n.kind='ref' AND n.ref_kind='sheet' AND "
             "n.ref_id=s.sheet_id AND (f.user_id=s.user_id OR f.agent_id=s.user_id))")
# Fable review of 2.937 F8: one rule for check and cast -- Postgres reads exactly the times the pattern lets through (Python's
# fromisoformat took forms the cast refuses, e.g. a week date, and the cast then stopped every start). A time it cannot read:
# created_at the start's time; revoked_at stays ended (the start's time) -- an ended address never opens again by a bad time.
SHS_ISO = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d{1,6})?(Z|[+-]\d\d:\d\d)?$"
SHS_RETYPE = (
    f"ALTER TABLE sheet_shares ALTER COLUMN created_at TYPE TIMESTAMPTZ USING (CASE WHEN CAST(created_at AS TEXT) ~ '{SHS_ISO}' "
    "THEN CAST(CAST(created_at AS TEXT) AS TIMESTAMPTZ) ELSE CURRENT_TIMESTAMP END)",
    f"ALTER TABLE sheet_shares ALTER COLUMN revoked_at TYPE TIMESTAMPTZ USING (CASE WHEN CAST(revoked_at AS TEXT) ~ '{SHS_ISO}' "
    "THEN CAST(CAST(revoked_at AS TEXT) AS TIMESTAMPTZ) WHEN revoked_at IS NULL OR CAST(revoked_at AS TEXT)='' THEN NULL "
    "ELSE CURRENT_TIMESTAMP END)")


def shs_left(c):
    """The start check: live old rows bound to an account (a table not in the trash, or in it with its node) whose account
    holds no core share on the table's node -- the last forward copy could not give them one (a full node)."""
    return c.execute(_SHS_LEFT).fetchone()[0]


def shs_prune(c):
    """After the check: the rows of people go (their shares are the core shares), so does an address bound to an account
    whose core share is gone (no share any more, listed by nobody: open again it would reopen what was taken back).
    Returns the rows deleted."""
    n = c.execute("DELETE FROM sheet_shares WHERE email_key=''").rowcount
    c.execute(_SHS_REOPEN)  # Fable F6: first, so the delete below does not take them
    n += c.execute(_SHS_DEAD).rowcount
    return n  # the times: SHS_RETYPE reads them (Fable F8)


def shs_retire(c):
    """Every start while sheet_shares.core_id exists (core/db.py init_db): the last forward copy (an older version may have
    written rows after a rollback), the start check, then the rows of people and the column core_id go, created_at /
    revoked_at become TIMESTAMPTZ (#5305) and the back limit rises (core/kernretire.py kern_retire_rows,
    core/migrations.d/5244_a.py) -- or a line in the log, an admin alert, and everything stays."""
    if not kern_retire_due(c, "sheet_shares", ("core_id",), "created_at"):  # Fable F1: done = TIMESTAMPTZ, not "no core_id"
        return {}
    copied = _shs_last_copy(c)
    out = kern_retire_rows(c, "sheet_shares", ("core_id",), shs_left, SHS_RETIRE_LABEL, prune=shs_prune, alter=SHS_RETYPE,
                           alert=_shs_alert)
    return dict(out, copied=copied) if copied else out


def _shs_alert(n, tables):
    from ..collab.tcxcore import _retire_alert  # the admins' alert of stage 7 (kind storage, counts and table names only)
    _retire_alert(n, tables)


objhooks.START.append(("kern5244_sheets", False, shs_retire))  # 2.937.0 (#5244): every start until core_id is gone
