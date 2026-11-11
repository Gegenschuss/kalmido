"""2.924.0 (#5069, stage 7a of the shared core, one-way, decided 07.11.2026): the team chat's old member table tchat_members goes.
The members of a channel / group conversation are the shares of the room's reference node (fs_shares: a person, an agent, a
group; collab/tcxcore.py), the core alone decides (obj_share_rows_sql / obj_role). schema.py no longer creates the table.

The DROP is no statement of this file: a fragment's AFTER runs in core/db.py init_db before the areas' start hooks
(objhooks.START), so the forward copy would come too late on the first start, and a fragment cannot hold the start check.
At a start (init_db's one transaction): collab/tcxcore.py tcx_core_copy once (flag migr_tcx5069: a room with old rows and
without a node gets one, every old row without a share gets one, nothing is taken back), then tcx_core_retire at every start
while the table exists (core/kernretire.py kern_retire, lock kalmido-kern5069): the start check counts the old rows of a
channel / group without a share of their person / agent on the room's node -- not 0: the table stays, a line in the log names
the number ("team chat, stage 7a (#5069): N old row(s) ..."), nothing is dropped; 0: DROP TABLE tchat_members and its rows in
obj_revoked (src 'tchat_members', taken back from the old table: nothing restores them any more).

Counting beforehand (read-only, the same rule as the start check):
  SELECT COUNT(*) FROM tchat_members m JOIN tchat_rooms r ON r.id=m.room_id WHERE r.kind IN ('channel','group') AND NOT EXISTS
    (SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind='tchat_room'
     AND n.ref_id=m.room_id AND COALESCE(s.user_id, s.agent_id)=m.user_id);
(before the first start of 2.924 the forward copy has not run yet: rows of rooms without a node count here, the copy gives them one)

What has no way back: the rows of tchat_members (since 2.565.0 every way in and out wrote the share too, the forward copy covers
the rest) and its obj_revoked rows. A version before 2.924 fails on the missing table (its readers: the room list, the search,
the export); the way back is a newer version only."""
# drop-ok tchat_members: stage 7a of the shared core (#5069, decided 07.11.2026), the members are core shares; collab/tcxcore.py tcx_core_retire drops it after the start check
