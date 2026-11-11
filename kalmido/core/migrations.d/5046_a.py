"""2.647.0 (#5046): the way back of the mirror of 4712_a.py -- core -> old member rows. kalmido_kern_mirror mirrors ev_cal_members /
book_members into the shares of the object's reference node (old -> core) only. A share taken back IN the core (the file store's
share dialog DELETE /api/files/shares, core/objects.py obj_node_unshare / obj_member_take / _take, obj_revoke_person) left the old
row standing; every reader that still looked at the old table (reminders, the heir of a deleted account, news, the export of an
organisation and its import) then saw the person as a member again.

kalmido_kern_back on fs_shares: a share of a person / an agent deleted on the node of a calendar (ref_kind 'evcal') or an address
book ('address_book') deletes that person's old row unless another live share of theirs stays on the node (then the row gets that
share's role); a share's role changed in the core gives the old row the same role. It writes the old rows with app.kern_sync = '1',
so kalmido_kern_mirror (which returns at once on that switch) does not mirror them back: no loop. The other way round (the mirror
deleting / updating a share after an old row changed) finds the old row already as the share says (a no-op).
A node removed for good (kalmido_kern_node_gone, review F3 of #4712) first writes its shares back into the rows; the shares then
go by ON DELETE CASCADE after the node row is gone -- the function finds no node any more and leaves those rows alone.
An expired share (expires_at in the past) is no event of the database: the readers of the app read the core's live shares with
the expiry (events/model.py cal_members / ev_member_role, contacts/model.py book_members_of / bk_member_role), never the old rows of
an object with a node. A share's new expiry date changes nothing here (no UPDATE OF expires_at): the readers decide by it.

New function and trigger only: the version before keeps running on it (it would only see fewer stale old rows); the way back is
DROP TRIGGER kalmido_kern_back ON fs_shares (and DROP FUNCTION kalmido_kern_back()). The function reads only columns fs_shares
has had since 2.48 (node_id, user_id, agent_id, role, expires_at).
2.924.0 (#5069, stage 7b): the function and trigger (kalmido_kern_back) went with the old member tables (events/evkern.py ev_kern_drop,
core/migrations.d/5069_b.py); this fragment keeps only its history.
"""
