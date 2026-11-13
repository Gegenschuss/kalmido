"""2.565.0 (#4719): the shared core, stage 5 -- the team chat's channels and group conversations are the kind 'tchat_room' of
the core (core/objects.py, docs/dev/kern.md).

- The room (a row of tchat_rooms, kind 'channel' | 'group') is registered with listed=False: its reference node only carries
  its members as shares (fs_shares: a person, an agent, a group) -- it lies in no folder and the file store never shows it.
  Direct messages and list conversations are no objects of the core (their rule is the pair / the list).
- Members: every way in (create, add, join, the import) writes the share; every way out (leave, remove, a person's agents
  along, leaving the organisation, a role going down, the retirement) takes it (into obj_revoked: restorable).
  2.924.0 (#5069, stage 7a, one-way): the core alone decides -- the old table tchat_members (2.565.0 to 2.923: the reader
  fallback, kept in step) is neither read nor written. tcx_core_copy, once at a start (flag migr_tcx5069): every channel /
  group with old rows and without a node gets one, every old row without a share gets one; nothing is taken back. Then
  tcx_core_retire at every start while the table exists: the start check counts the rows still without a share -- none:
  DROP TABLE tchat_members (core/kernretire.py, core/migrations.d/5069_a.py); else a clear line in the log, the table stays.
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
  tcx_core_add(c, rid, uid, actor)          uid (a person or an agent) joins room rid: the share of its node
  tcx_core_take(c, rid, uids, actor, reason='unshare')   they leave: shares into obj_revoked
  tcx_core_group_put(c, rid, gid, actor) / tcx_core_group_take(c, rid, gid, actor) -> bool
  tcx_core_groups(c, rids) -> {room id: [group ids]}
  tcx_core_members_sql() -> SQL (room_id, user_id, via): via = the group id (0 = a personal share)
  tcx_core_rooms_sql(uid) -> SQL of the room ids uid is a member of through the core (person, agent, group)
  tcx_core_copy(c) -> {nodes, added}   once at a start (core/db.py init_db, flag migr_tcx5069; 2.924.0, #5069)
  tcx_core_retire(c) -> {} | {left} | {dropped, revoked}   every start while tchat_members exists (after tcx_core_copy)
"""
from ..core import objhooks  # 2.565.0: START (core/db.init_db runs the forward copy)
from ..core.db import iso, now_utc
from ..core.i18n import N_
from ..core.objects import obj_member_put, obj_member_take, obj_register, obj_share_rows_sql
from ..core.kernretire import kern_retire  # 2.924.0 (#5069): the start check and DROP of stage 7
from ..core.pg import system_ctx, table_exists
from ..notify.alerts import aa_now  # 2.924.0 (#5069): the admins learn when the start check keeps the old table
from .teamchan import tcx_can_manage, tcx_members, tcx_room_ok  # loaded before (kalmido/__init__.py ORDER)

TCX_KIND = "tchat_room"
_KINDS = ("channel", "group")


def _space(c, rid):
    """(org_id | None, owner) of a channel / group: the owner of its node is who made it, else the node's owner now, else
    its first person (fs_nodes.owner_id; 2.924.0, #5069: no old member rows read any more); None for a direct message / list
    conversation (no object of the core)."""
    r = c.execute("SELECT kind, org_id, created_by FROM tchat_rooms WHERE id=?", (int(rid),)).fetchone()
    if not r or r["kind"] not in _KINDS:
        return None
    owner = r["created_by"]
    if not owner:
        with system_ctx(c):  # who keeps the node of a room whose maker is gone (structure)
            x = c.execute("SELECT owner_id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (TCX_KIND, int(rid))).fetchone()
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
    return (f"({tcx_core_rooms_sql(u)} "  # 2.924.0 (#5069): the core alone
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
    u = int(uid)  # review F2: through a group only as a full member of the room's organisation (the poll signature counted the rest)
    return (f"SELECT cm.room_id FROM {tcx_core_members_sql()} cm JOIN tchat_rooms rr ON rr.id = cm.room_id WHERE cm.user_id = {u} "
            f"AND (cm.via = 0 OR rr.org_id IS NULL OR EXISTS (SELECT 1 FROM org_members om WHERE om.org_id = rr.org_id "
            f"AND om.user_id = {u} AND om.role IN ('admin','member','readonly')))")


def _key(c, uid):
    r = c.execute("SELECT kind FROM users WHERE id=?", (int(uid),)).fetchone()
    return "agent_id" if r and (r["kind"] or "") == "agent" else "user_id"


def tcx_core_add(c, rid, uid, actor):
    """uid joins channel / group rid (the caller checked tcx_may_add / joining): the core's share (2.924.0, #5069: alone)."""
    obj_member_put(c, actor, TCX_KIND, rid, _key(c, uid), uid, "edit")


def tcx_core_take(c, rid, uids, actor, reason="unshare"):
    """uids leave room rid: their shares go into obj_revoked (restorable). Returns the shares taken."""
    uids = sorted({int(u) for u in uids or ()})
    if not uids:
        return 0
    n = 0
    for key in ("user_id", "agent_id"):
        n += obj_member_take(c, actor, TCX_KIND, rid, key, uids, reason)
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


# ---------------------------------------------------------------- once at a start (2.924.0, #5069: stage 7a)
TCX_OLD = "tchat_members"
TCX_COPY_FLAG = "migr_tcx5069"  # the forward copy ran (once: the writers no longer keep the old rows, a second copy would reopen)


def tcx_core_copy(c):
    """The forward copy, once, inside init_db's transaction (objhooks.START with its flag, like events/evkern.py ev_kern_copy):
    every channel / group with old member rows and without a node gets one (owner: its maker, else its first person, else the
    owner of an agent in it, else an admin of its organisation), every old row without a share gets one (a person's / an
    agent's, role edit, its added_by / created_at). Nothing is taken back: since 2.565.0 every way out took both, and the
    start of 2.565 to 2.923 (tcx_core_sync) took a share whose row was gone. {nodes, added}; {} without the old table."""
    if not table_exists(c, TCX_OLD):
        return {}
    ts = iso(now_utc())
    owner = """COALESCE(r.created_by,
                        (SELECT m.user_id FROM tchat_members m JOIN users u ON u.id=m.user_id WHERE m.room_id=r.id
                         AND COALESCE(u.kind,'')!='agent' ORDER BY m.created_at, m.user_id LIMIT 1),
                        (SELECT a.owner_id FROM tchat_members m JOIN agents a ON a.user_id=m.user_id WHERE m.room_id=r.id
                         AND a.owner_id IS NOT NULL ORDER BY m.created_at, m.user_id LIMIT 1),
                        (SELECT om.user_id FROM org_members om WHERE om.org_id=r.org_id AND om.role='admin' ORDER BY om.user_id LIMIT 1))"""
    nodes = c.execute(f"""INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,ref_kind,ref_id,created_by,created_at,updated_at)
                          SELECT NULL, 'ref', CASE WHEN r.name != '' THEN r.name ELSE 'Team chat' END, {owner},
                                 r.org_id, ?, r.id, r.created_by, ?, ?
                          FROM tchat_rooms r WHERE r.kind IN ('channel','group')
                            AND EXISTS (SELECT 1 FROM tchat_members m WHERE m.room_id=r.id)
                            AND NOT EXISTS (SELECT 1 FROM fs_nodes n WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=r.id)
                            AND {owner} IS NOT NULL
                          ON CONFLICT DO NOTHING""", (TCX_KIND, ts, ts, TCX_KIND)).rowcount
    added = 0
    for key, cond in (("user_id", "COALESCE(u.kind,'')!='agent'"), ("agent_id", "u.kind='agent'")):
        added += c.execute(f"""INSERT INTO fs_shares(node_id,{key},role,created_by,created_at,by_role)
                               SELECT n.id, m.user_id, 'edit', m.added_by, COALESCE(NULLIF(CAST(m.created_at AS text), '')::timestamptz, now()), NULL
                               FROM tchat_members m JOIN users u ON u.id=m.user_id
                               JOIN fs_nodes n ON n.kind='ref' AND n.ref_kind=? AND n.ref_id=m.room_id
                               WHERE {cond} AND NOT EXISTS (SELECT 1 FROM fs_shares s WHERE s.node_id=n.id AND s.{key}=m.user_id)""",
                           (TCX_KIND,)).rowcount
    return {"nodes": nodes, "added": added}

objhooks.START.append((TCX_COPY_FLAG, True, tcx_core_copy))  # 2.924.0 (#5069): once (core/db.init_db sets the flag)


def tcx_core_left(c):
    """The start check: old rows of a channel / group without a share of their person / agent on the room's node (any role,
    also an expired one or a node in the trash: the core has the membership, it decides). Rows of a direct message / list
    conversation never were members of the core (none are written there) and do not count."""
    return c.execute("""SELECT COUNT(*) FROM tchat_members m JOIN tchat_rooms r ON r.id=m.room_id
                        WHERE r.kind IN ('channel','group') AND NOT EXISTS (
                          SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id
                          WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=m.room_id AND COALESCE(s.user_id, s.agent_id)=m.user_id)""",
                     (TCX_KIND,)).fetchone()[0]


def tcx_core_retire(c):
    """Every start while tchat_members exists (core/db.py init_db, after the forward copy): the start check, then DROP TABLE
    tchat_members and its rows in obj_revoked (one-way, core/migrations.d/5069_a.py), or a line in the log and the table stays."""
    return kern_retire(c, (TCX_OLD,), tcx_core_left, "team chat, stage 7a (#5069)", alert=_retire_alert)


TCX_RETIRE_WAITS = N_("Shared core clean-up waits: {0} old member rows of {1} have no share yet, the old table stays. See the server log.")


def _retire_alert(n, tables):
    """The admins' alert of the start check (kind storage; counts and table names only)."""
    aa_now("storage", "kern5069:" + ",".join(tables), TCX_RETIRE_WAITS, (int(n), ", ".join(tables)))

objhooks.START.append(("tcx_core_retire", False, tcx_core_retire))  # 2.924.0 (#5069): every start until the table is gone
