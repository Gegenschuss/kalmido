"""2.568.0 (#4739): stage 6 of the shared core -- the projects (lists) as a kind of the core (core/objects.py, docs/dev/kern.md).

list_members stays the role table every reader uses (visibility, the delta, notifications, the lock, agents, row-level
security); participants and the task visibility (tvis) stay the area's own. What moves onto the core:
- the kind 'list' (obj_register, routes=False: the projects bring their own routes; fsref=False: the reference kind 'list'
  of files/fsref.py stays the one of lists/lffolder.py, whose folder shares grp_sync materializes into list_members.frole)
  with the project role as its base role: owner / list admin 'manage', editor 'edit', viewer 'view' (participants: none --
  what they see is decided per task)
- every change of a person's / an agent's own share (PUT /api/lists/<id>/members, DELETE .../members/<uid>, PUT .../agent)
  writes the core's share row on the project's node too: fs_shares with list_role = the project role, list_own = 1, the
  expiry, created_by / by_role and the node's log. Taking a share away moves that row into obj_revoked (restorable with
  obj_share_restore, POST /api/lists/<id>/shares/<rid>/restore: the project's own rules of a share apply again, member_set);
  an expired row ends the own role (groups.grp_sync, lffolder.lf_expire_tick). A member from before 2.568 has no row yet: the
  row is written when the share is taken away, so it can be put back the same way.
- leaving an organisation takes these rows with the core (obj_revoke_person 'leave': the shares on the organisation's
  nodes); the organisation role changing re-materializes the groups' roles (A-F10: a guest / accounting person gets no
  project role through a group, lists/groups.py grp_org_limited)
- the history of a project's settings (PATCH /api/lists/<id>: columns, col_sums, kpis, props, ticket_tpl, agent_members) in
  obj_history (lmc_history; GET /api/lists/<id>/history)
- 2.936.0 (#5364): the trash period of a project in the trash (lists/listtrash.py) is the core's retention run
  (obj_trash_tick: trash_prune, trash_keep=otr_keep, obj_on_purge hook otr_core_purge, 50 per run); its trash, restore and
  delete stay the routes of listtrash.py; 2.1002.0 (#5491): their restore / delete for good run through the core
  (obj_restore / obj_purge with trash_can=otr_can, children = the tasks)
The rule "one agent per project" stays the area's (core/access.py list_other_agent, checked by member_set).

Interface:
  lmc_share(c, actor, lid, uid, role, expires_at=None) -> share id | None    the core's row of an own share (caller checked)
  lmc_unshare(c, actor, lid, uid) -> obj_revoked id | None                   it goes (restorable); written first if missing
  lmc_snap(c, lid, keys=LMC_HIST) -> {field: value}                         the settings with a history as they are
  lmc_history(c, uid, lid, before, after)                                    a change of the project's settings
  GET  /api/lists/<id>/shares                          {shares, inherited, revoked} (owner / list admin)
  POST /api/lists/<id>/shares/<revoked_id>/restore     a share taken away comes back (owner / list admin)
  GET  /api/lists/<id>/history                         the settings' history, newest first (who sees the project)
"""
import json

from flask import g, jsonify

from ..accounts.session import me
from ..core.access import _list_role, need_collab, need_list
from ..core.config import app
from ..core.db import bump, db, err, iso, now_utc
from ..core.i18n import N_, tr
from ..core.objects import obj_register, obj_share, obj_share_locks, obj_share_restore, obj_shares, obj_unshare  # #5788: obj_share_locks
from ..core.pg import system_ctx
from ..core.writes import obj_history, obj_history_add
from ..core.writes import obj_on_purge  # 2.936.0 (#5364)
from ..core.writes import undo_skip  # 2.1029.0 (#5537)
from ..api.common import v1_call
from .groups import grp_list_ids, grp_of_user, grp_sync
from .lffolder import lf_own_stale, lf_place
from ..core.objhooks import SETTLE
from .lists import member_set
from .listtrash import otr_can, otr_core_purge, otr_keep  # 2.936.0 (#5364): the kind list's retention hooks; #5491: otr_can

LMC_KIND = "list"
LMC_HIST = ("columns", "col_sums", "kpis", "props", "ticket_tpl", "agent_members")  # the settings with a history
_ROLE = {"owner": "manage", "admin": "manage", "edit": "edit", "view": "view"}  # participants: none (tvis decides per task)


def _base(c, uid, lid):
    return _ROLE.get(_list_role(c, int(lid), uid))


def _visible(c, uid):
    u = int(uid)
    return f"(SELECT id FROM lists WHERE owner_id = {u} UNION SELECT list_id FROM list_members WHERE user_id = {u})"


def _title(c, lid):
    r = c.execute("SELECT name FROM lists WHERE id=?", (int(lid),)).fetchone()
    return r[0] if r else ""


def _is_agent(c, uid):
    return c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent'", (int(uid),)).fetchone() is not None


def _node(c, lid):
    """The project's reference node (placed where its path says, lffolder.lf_place); None for the basket."""
    nid = lf_place(c, int(lid))
    with system_ctx(c):
        return c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone() if nid else None


def _own_row(c, lid, uid):
    with system_ctx(c):  # the node lies in the owner's tree, also when a list admin asks
        n = c.execute("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (LMC_KIND, int(lid))).fetchone()
        if not n:
            return None
        return c.execute("SELECT * FROM fs_shares WHERE node_id=? AND list_own=1 AND (user_id=? OR agent_id=?) ORDER BY id LIMIT 1",
                         (n[0], int(uid), int(uid))).fetchone()


def lmc_share_locks(c, pairs):
    """2.1032.0 (#5788, review): lmc_share_lock for many (project, person) pairs, their buckets in ascending order (each once;
    core/objects.obj_share_locks): a writer of several member rows takes them all before the first row."""
    lids = sorted({int(lid) for lid, _u in pairs})
    if not lids:
        return
    with system_ctx(c):  # read only (no lf_place: a lock writes nothing); a project without its node yet has no share to cross
        nodes = {r[0]: r[1] for r in c.execute("SELECT ref_id, id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id = ANY(CAST(? AS BIGINT[]))",
                                               (LMC_KIND, lids)).fetchall()}
    obj_share_locks(c, [(nodes[int(lid)], int(uid)) for lid, uid in pairs if int(lid) in nodes])


def lmc_share_lock(c, lid, uid):
    """2.1032.0 (#5788, review F3 of 2.1017): the bucket lock (core/objects.obj_share_lock) of uid's share of project lid,
    taken by member_set BEFORE it writes the list_members row: lffolder.lf_folder_share holds the buckets of its folders
    and then writes list_members (grp_sync); member_set wrote the row first and asked for the bucket in lmc_share -- the
    two orders could deadlock. Now both take a bucket before the row -- and so does every other writer of a member row
    whose core row follows (lmc_share / lmc_mirror after the row: lists.py, orgvis.py, family.py, ownership.py,
    agents/proposals.py), else member_set and that writer would cross on the same bucket. The basket (no node): nothing."""
    lmc_share_locks(c, [(lid, uid)])


_KEEP = object()


def lmc_share(c, actor, lid, uid, role, expires_at=_KEEP):
    """The core's share row of uid's own role in project lid (member_set checked the right, the target and the project's
    rules). role = the project role; the row's view / edit follows lffolder._base (2.352.0 F review H1: only an admin's row
    gives 'edit' on the node, i.e. filing / moving / sharing a folder holding it). expires_at left out: the row's expiry
    stays. -> share id | None (the basket)."""
    if _node(c, lid) is None:
        return None
    key = "agent_id" if _is_agent(c, uid) else "user_id"
    if expires_at is _KEEP:
        old = _own_row(c, lid, uid)
        expires_at = old["expires_at"] if old is not None else None
    with system_ctx(c):  # the node may lie in a folder the actor does not see (another person's path)
        return obj_share(c, actor, LMC_KIND, int(lid), key, int(uid), "edit" if role == "admin" else "view", expires_at,
                         extra={"list_role": role, "list_own": 1}, checked=True)


def _own_role(c, lid, uid):
    """uid's own role in project lid (list_members.own_role; a member from before 2.352 / a row no group / folder gave: role)."""
    m = c.execute("SELECT own_role, role, grole, frole FROM list_members WHERE list_id=? AND user_id=?", (int(lid), int(uid))).fetchone()
    return (m["own_role"] or (m["role"] if m["grole"] is None and m["frole"] is None else None)) if m else None


def lmc_mirror(c, actor, lid, uid):
    """2.654.0 (#5050): the core's row of uid's own role in project lid follows list_members after a way that wrote the member row
    itself (joining an organisation-wide project, the old owner of a transfer, an agent's share of a proposal, an account becoming
    an agent, a child made a participant): lmc_share with the role the row holds now; no own role: nothing. The caller checked the
    right. -> share id | None."""
    role = _own_role(c, lid, uid)
    return lmc_share(c, actor, lid, uid, role) if role else None


def lmc_unshare(c, actor, lid, uid):
    """uid's own share of project lid goes (into obj_revoked, restorable); a member from before 2.568.0 gets the row from
    list_members first. The caller removed / lowered the list_members row (member_remove). -> obj_revoked id | None."""
    s = _own_row(c, lid, uid)
    if s is None:
        role = _own_role(c, lid, uid)
        if not role or lmc_share(c, actor, lid, uid, role) is None:
            return None
        s = _own_row(c, lid, uid)
        if s is None:
            return None
    with system_ctx(c):  # the node may lie in a folder the actor does not see (another person's path); member_remove checked the right
        return obj_unshare(c, actor, LMC_KIND, int(lid), s["id"], checked=True)


def lmc_rejoin_actor(c, lid, uid):
    """2.568.0 (#4739, review F7): who shared project lid with uid before uid left the organisation (created_by of the row the
    core took, obj_revoked) -- None (the system) when no such row is left."""
    for (j,) in c.execute("SELECT row_json FROM obj_revoked WHERE src='fs_shares' AND kind=? AND ref_id=? AND user_id=? ORDER BY id DESC",
                          (LMC_KIND, int(lid), int(uid))).fetchall():
        s = json.loads(j)
        if s.get("list_own") and s.get("created_by") and int(s["created_by"]) != int(uid):
            return int(s["created_by"])
    return None


def _on_restore(c, uid, lid, share):
    """obj_share_restore put uid's (the target's) own member row back (list_own, a person / an agent: core/objects.py, review
    F2): the project's own rules of a share decide (member_set: the workspace, one agent per project, the lock, a child ...);
    a refusal answers its error, nothing is committed. Review F3: an expiry that ran out meanwhile is dropped (the share comes
    back without one; the route's answer says so with expiry_removed)."""
    target = share.get("user_id") or share.get("agent_id")
    role = share.get("list_role") if share.get("list_role") in ("admin", "edit", "participant", "view") else "view"
    exp = share.get("expires_at")
    if exp and str(exp) <= iso(now_utc()):
        exp, g.lmc_expiry_removed = None, True
        c.execute("UPDATE fs_shares SET expires_at=NULL WHERE id=?", (int(share["id"]),))  # before member_set reads the row
    g.lmc_restore = int(target)  # member_set: the target need not be one the manager may look up (shared by e-mail before)
    try:
        v1_call(member_set, int(lid), body={"user_id": int(target), "role": role, "expires_at": exp})
    finally:
        g.pop("lmc_restore", None)


def _on_revoke(c, uid, org, reason, role=None):
    """obj_revoke_person: the organisation role of uid changed -> the roles through groups anew in the organisation's
    projects (A-F10: a guest / accounting person loses them, a member gets them back). Leaving / retiring / deleting: the
    rows of list_members go in accounts/orgs.py org_leave (with its memo for coming back) and with the account."""
    if reason != "role" or not uid or not org:
        return {}
    ids = set()
    for gid in grp_of_user(c, int(uid)):
        ids |= grp_list_ids(c, gid=gid)
    ids |= {r[0] for r in c.execute("SELECT list_id FROM list_members WHERE user_id=? AND (grole IS NOT NULL OR frole IS NOT NULL)", (int(uid),))}
    if ids:
        q = ",".join(str(int(x)) for x in sorted(ids))
        ids = [r[0] for r in c.execute(f"SELECT id FROM lists WHERE org_id=? AND id IN ({q})", (int(org),))]
    if ids:
        grp_sync(c, ids)
    return {"list_members": len(ids)}


_COLS = {"columns": "col_cfg", "col_sums": "tb_sums", "kpis": "fx_kpis", "props": "props", "ticket_tpl": "ticket_tpl",
         "agent_members": "agent_members"}  # the field of the API -> its column of lists


def lmc_snap(c, lid, keys=LMC_HIST):
    """{field: value} of project lid's settings with a history (JSON text read as its value)."""
    r = c.execute(f"SELECT {', '.join(_COLS[k] for k in keys)} FROM lists WHERE id=?", (int(lid),)).fetchone()
    if r is None:
        return {}
    out = {}
    for k, v in zip(keys, r):
        if isinstance(v, str) and v[:1] in ("{", "["):
            try:
                v = json.loads(v)
            except ValueError:
                pass
        out[k] = v
    return out


def lmc_history(c, uid, lid, before, after):
    """A change of project lid's settings (LMC_HIST) in the core's history: before / after of the fields that changed; one
    person's changes within ten minutes merge, an agent's are marked (core/writes.py obj_history_add)."""
    b = {k: before.get(k) for k in LMC_HIST if k in after and before.get(k) != after.get(k)}
    if b:
        obj_history_add(c, uid, LMC_KIND, int(lid), b, {k: after[k] for k in b})


# 2.1029.0 (#5537): the state marker follows archived / deleted_at (trigger kalmido_list_state, migrations.d/5537_a.py) -- no
# undo copy holds it, so taking a step back writes the old columns and the trigger sets the marker from them
undo_skip("lists", "state")
obj_register(LMC_KIND, "lists", label=N_("Project"), fields={}, open_url=lambda lid: f"list/{int(lid)}", title=_title,
             base_role=_base, visible=_visible, area="tasks", routes=False, fsref=False, share_cols=("list_role", "list_own"),
             on_restore=_on_restore, on_revoke=_on_revoke, list_col="id",
             # 2.936.0 (#5364): the projects' trash period runs in the core's retention run (lists/listtrash.py); 50 per run:
             # a project goes with all its tasks and files (2.817.0 review F4)
             trash_prune=True, trash_keep=otr_keep, trash_batch=50,
             # 2.1002.0 (#5491): restore / delete for good through the core (obj_restore / obj_purge): the trash rule of
             # projects (otr_can) and their tasks, which go into the trash with the project's time (listtrash.py otr_trash)
             trash_can=otr_can, children=(("tasks", "list_id"),))
obj_on_purge(LMC_KIND, otr_core_purge)  # 2.936.0 (#5364)


@app.get("/api/lists/<int:lid>/shares")
def lmc_shares_route(lid):
    """The project's shares of the core: its own (members, the file store's shares on its node), the folders' above, the
    ones taken away (restorable). Owner / list admin."""
    need_collab()
    c = db()
    need_list(c, lid, write=False, manage=True)
    return jsonify(obj_shares(c, me(), LMC_KIND, lid))


@app.post("/api/lists/<int:lid>/shares/<int:revoked_id>/restore")
def lmc_share_restore_route(lid, revoked_id):
    """A share taken away comes back (the undo of removing a member, of leaving an organisation within 30 days) under the
    project's rules of a share. Owner / list admin."""
    need_collab()
    c = db()
    need_list(c, lid, write=False, manage=True)
    sid = obj_share_restore(c, me(), LMC_KIND, lid, revoked_id)
    bump(c)
    c.commit()
    gone = bool(g.pop("lmc_expiry_removed", False))  # review F3: an expired share came back without its expiry
    return jsonify(id=sid, expiry_removed=gone, **obj_shares(c, me(), LMC_KIND, lid))


@app.get("/api/lists/<int:lid>/history")
def lmc_history_route(lid):
    """The history of the project's settings (columns, sums, key figures, properties, ticket template, agent members)."""
    c = db()
    need_list(c, lid, write=False)
    if _list_role(c, int(lid), me()) == "participant":  # review F5: they see the project (need_list), not its settings' history
        return err(tr("Participants do not see the project's settings history"), 403)
    return jsonify(history=obj_history(c, me(), LMC_KIND, lid))


def _settle(c, kind, rid):
    if kind == LMC_KIND:
        lf_own_stale(c, int(rid))


SETTLE.append(_settle)  # core/objhooks.obj_settle (accounts/orgs.py ol_private calls it without importing the lists)
