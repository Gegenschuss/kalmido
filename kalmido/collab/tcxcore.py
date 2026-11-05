"""2.565.0 (#4719): the shared core, stage 5 -- the team chat's channels and group conversations are the kind 'tchat_room' of
the core (core/objects.py, docs/dev/kern.md).

- The room (a row of tchat_rooms, kind 'channel' | 'group') is registered with listed=False: its reference node only carries
  its members as shares (fs_shares: a person, an agent, a group) -- it lies in no folder and the file store never shows it.
  Direct messages and list conversations are no objects of the core (their rule is the pair / the list).
- Members: every way in (create, add, join, the import) writes the share AND the old row of tchat_members; every way out
  (leave, remove, a person's agents along, leaving the organisation, a role going down, the retirement) takes both
  (the shares into obj_revoked: restorable). tchat_members stays the reader fallback until stage 7; tcx_core_sync at every
  start copies its rows forward (also what an older version added after a rollback) and takes back the person / agent shares
  whose row an older version removed -- the fallback never opens what the core took away, and the core never what the
  fallback lost.
- A group (lists/groups.py, the admin's groups) as subject: a channel shared with a group has every member of the group as a
  member while they qualify: an enabled person, for an organisation's channel a full member of that organisation (member /
  admin / read-only -- a guest or an accounting member needs a personal invitation, the rule of the open channels). Group
  conversations (kind 'group') take no group.
- The role (obj_role, base_role hook): who reads the room (collab/teamchan.py tcx_room_ok: its members, an open channel every
  full member of its organisation) 'edit', who also manages it (tcx_can_manage) 'manage'; the core's floor before it (another
  organisation, an agent of another workspace, a token limited to lists). A share gives nothing beyond that (cap): the base
  role reads the shares itself with the team chat's rules for who still qualifies.

Interface:
  TCX_KIND = 'tchat_room'
  tcx_core_add(c, rid, uid, actor)          uid (a person or an agent) joins room rid: share + tchat_members row
  tcx_core_take(c, rid, uids, actor, reason='unshare')   they leave: shares into obj_revoked, rows deleted
  tcx_core_group_put(c, rid, gid, actor) / tcx_core_group_take(c, rid, gid, actor) -> bool
  tcx_core_groups(c, rids) -> {room id: [group ids]}
  tcx_core_members_sql() -> SQL (room_id, user_id, via): via = the group id (0 = a personal share)
  tcx_core_rooms_sql(uid) -> SQL of the room ids uid is a member of through the core (person, agent, group)
  tcx_core_sync(c) -> {added, taken, nodes}   every start (core/db.py init_db)
"""
from ..core.db import iso, now_utc
from ..core.i18n import N_
from ..core.objects import _take as obj_take_rows, obj_member_put, obj_member_take, obj_register, obj_share_rows_sql
from ..core.pg import system_ctx
from .teamchan import tcx_can_manage, tcx_members, tcx_room_ok  # loaded before (kalmido/__init__.py ORDER)

TCX_KIND = "tchat_room"
_KINDS = ("channel", "group")


def _space(c, rid):
    """(org_id | None, owner) of a channel / group: the owner of its node is who made it, else the node's owner now, else
    its first person (fs_nodes.owner_id); None for a direct message / list conversation (no object of the core)."""
    r = c.execute("SELECT kind, org_id, created_by FROM tchat_rooms WHERE id=?", (int(rid),)).fetchone()
    if not r or r["kind"] not in _KINDS:
        return None
    owner = r["created_by"]
    if not owner:
        with system_ctx(c):  # who keeps the node of a room whose maker is gone (structure)
            x = c.execute("SELECT owner_id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (TCX_KIND, int(rid))).fetchone() \
                or c.execute("SELECT m.user_id FROM tchat_members m JOIN users u ON u.id=m.user_id WHERE m.room_id=? "
                             "AND COALESCE(u.kind,'')!='agent' ORDER BY m.created_at, m.user_id LIMIT 1", (int(rid),)).fetchone()
        owner = x[0] if x else None
    return (r["org_id"] or None, owner)


def _base(c, uid, rid):
    r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (int(rid),)).fetchone()
    if not r or r["kind"] not in _KINDS:
        return None
    mem = tcx_members(c, r)
    if not tcx_room_ok(c, r, uid, mem):
        return None
    return "manage" if tcx_can_manage(c, r, uid, mem) else "edit"


def _visible(c, uid):
    """The candidates of obj_rows (the kind has a cap hook: obj_role decides each row)."""
    u = int(uid)
    return (f"(SELECT room_id FROM tchat_members WHERE user_id = {u} UNION {tcx_core_rooms_sql(u)} "
            f"UNION SELECT id FROM tchat_rooms WHERE kind = 'channel' AND is_open = 1 AND org_id IN "
            f"(SELECT org_id FROM org_members WHERE user_id = {u}))")


obj_register(TCX_KIND, "tchat_rooms", label=N_("Channel"), fields={}, area="team", routes=False, listed=False,
             space=_space, base_role=_base, visible=_visible, cap=lambda c, uid, rid: None,
             title=lambda c, rid: (c.execute("SELECT name FROM tchat_rooms WHERE id=?", (int(rid),)).fetchone() or [""])[0],
             open_url=lambda rid: f"team/{int(rid)}", scopes=("comments", "comments"))


# ---------------------------------------------------------------- members
def tcx_core_members_sql():
    """(room_id, user_id, via) of the core's shares of every room: a person / an agent (via 0) or the members of a group
    (via = the group id). The team chat's rules (teamchan.tcx_members_of) decide who of them still qualifies."""
    sh = obj_share_rows_sql(TCX_KIND)
    return (f"(SELECT x.ref_id AS room_id, COALESCE(x.user_id, x.agent_id) AS user_id, 0 AS via FROM {sh} x WHERE x.group_id IS NULL "
            f"UNION SELECT x.ref_id AS room_id, gm.user_id, x.group_id AS via FROM {sh} x JOIN group_members gm ON gm.group_id = x.group_id)")


def tcx_core_rooms_sql(uid):
    """SQL of the room ids uid is a member of through the core (a share with them, or with a group they are in)."""
    return f"SELECT room_id FROM {tcx_core_members_sql()} cm WHERE cm.user_id = {int(uid)}"


def _key(c, uid):
    r = c.execute("SELECT kind FROM users WHERE id=?", (int(uid),)).fetchone()
    return "agent_id" if r and (r["kind"] or "") == "agent" else "user_id"


def tcx_core_add(c, rid, uid, actor):
    """uid joins channel / group rid (the caller checked tcx_may_add / joining): the core's share and the fallback row."""
    obj_member_put(c, actor, TCX_KIND, rid, _key(c, uid), uid, "edit")
    c.execute("INSERT INTO tchat_members(room_id,user_id,added_by,created_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
              (rid, uid, actor, iso(now_utc())))


def tcx_core_take(c, rid, uids, actor, reason="unshare"):
    """uids leave room rid: their shares go into obj_revoked (restorable), their fallback rows go. Returns the shares taken."""
    uids = sorted({int(u) for u in uids or ()})
    if not uids:
        return 0
    n = 0
    for key in ("user_id", "agent_id"):
        n += obj_member_take(c, actor, TCX_KIND, rid, key, uids, reason)
    c.execute(f"DELETE FROM tchat_members WHERE room_id=? AND user_id IN ({','.join('?' * len(uids))})", (rid, *uids))
    return n


def tcx_core_group_put(c, rid, gid, actor):
    obj_member_put(c, actor, TCX_KIND, rid, "group_id", gid, "edit")


def tcx_core_group_take(c, rid, gid, actor):
    return obj_member_take(c, actor, TCX_KIND, rid, "group_id", [gid]) > 0


def tcx_core_groups(c, rids):
    """{room id: [group ids shared with it]}."""
    rids = sorted({int(r) for r in rids or ()})
    out = {r: [] for r in rids}
    if not rids:
        return out
    for x in c.execute(f"SELECT ref_id, group_id FROM {obj_share_rows_sql(TCX_KIND)} x WHERE x.group_id IS NOT NULL "
                       "AND x.ref_id = ANY(CAST(? AS BIGINT[])) ORDER BY x.group_id", (rids,)).fetchall():
        out[x[0]].append(x[1])
    return out


# ---------------------------------------------------------------- every start
def tcx_core_sync(c):
    """Keeps the core's shares and tchat_members in step (module docstring), inside init_db's transaction: rows of
    tchat_members without a share get one (the copy forward of 2.565.0, and what an older version added); person / agent
    shares of a room without their row lose it (an older version removed them; into obj_revoked). Group shares stay."""
    ts = iso(now_utc())
    nodes = c.execute("""INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,ref_kind,ref_id,created_by,created_at,updated_at)
                         SELECT NULL, 'ref', CASE WHEN r.name != '' THEN r.name ELSE 'Team chat' END,
                                COALESCE(r.created_by, (SELECT m.user_id FROM tchat_members m JOIN users u ON u.id=m.user_id
                                                        WHERE m.room_id=r.id AND COALESCE(u.kind,'')!='agent'
                                                        ORDER BY m.created_at, m.user_id LIMIT 1)),
                                r.org_id, ?, r.id, r.created_by, ?, ?
                         FROM tchat_rooms r WHERE r.kind IN ('channel','group')
                           AND EXISTS (SELECT 1 FROM tchat_members m WHERE m.room_id=r.id)
                           AND NOT EXISTS (SELECT 1 FROM fs_nodes n WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=r.id)
                           AND COALESCE(r.created_by, (SELECT m.user_id FROM tchat_members m JOIN users u ON u.id=m.user_id
                                                       WHERE m.room_id=r.id AND COALESCE(u.kind,'')!='agent' LIMIT 1)) IS NOT NULL
                         ON CONFLICT DO NOTHING""", (TCX_KIND, ts, ts, TCX_KIND)).rowcount
    added = 0
    for key, cond in (("user_id", "COALESCE(u.kind,'')!='agent'"), ("agent_id", "u.kind='agent'")):
        added += c.execute(f"""INSERT INTO fs_shares(node_id,{key},role,created_by,created_at,by_role)
                               SELECT n.id, m.user_id, 'edit', m.added_by, m.created_at, NULL
                               FROM tchat_members m JOIN users u ON u.id=m.user_id
                               JOIN fs_nodes n ON n.kind='ref' AND n.ref_kind=? AND n.ref_id=m.room_id
                               WHERE {cond} AND NOT EXISTS (SELECT 1 FROM fs_shares s WHERE s.node_id=n.id AND s.{key}=m.user_id)""",
                           (TCX_KIND,)).rowcount
    gone = c.execute("""SELECT s.id FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id
                        WHERE n.kind='ref' AND n.ref_kind=? AND s.group_id IS NULL
                          AND NOT EXISTS (SELECT 1 FROM tchat_members m WHERE m.room_id=n.ref_id AND m.user_id=COALESCE(s.user_id, s.agent_id))""",
                     (TCX_KIND,)).fetchall()
    taken = 0
    if gone:
        ids = [x[0] for x in gone]
        taken = obj_take_rows(c, "fs_shares", f"id IN ({','.join('?' * len(ids))})", tuple(ids), "unshare", None, None, "user_id", kind=TCX_KIND)
    return {"nodes": nodes, "added": added, "taken": taken}
