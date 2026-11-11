"""2.530.0 A (#4315): the trash of comments and team chat messages (audit #2425 B36, B37, B11).

Deleting a comment or a team chat message was final: its text emptied, its files gone from the disk. Now it goes into a
trash for the trash period (ret_days("trash")): the row keeps looking deleted exactly as before (body '', deleted_at set),
so no read path (app, v1 / MCP, agent events, search, exports, notifications, file downloads) ever sees the kept text; the
text waits in obj_comment_trash (2.972.0, #5272; was comment_trash_text) / tchat_trash_text, the files stay as rows and on disk:
 - comment files: attachments.deleted_at = the comment's deleted_at (the attachment trash keeps them, need_attachment and the
   task's file trash already leave the files of a deleted comment out; restoring the comment brings back exactly these)
 - team chat files: tchat_files unchanged; every reader skips the files of a deleted message (tcx_files_of callers,
   tcx_file_access, tchat_msg_brief, replies, the organisation export)
A restore (author or whoever could delete it, within the period) puts text and files back. The trash run
(files/trashpurge.py) deletes the rows after the period: the attachments go first through atr_tick (same timestamp), the team
chat files leave the disk after the commit (tcx_trash_paths).
2.783.0 (#5368, stage 6 of the trash core): the deleted team chat messages (tombstones) are a side object of the core
(core/objparts.py part_kind TCX_MSG_KIND): the core's run (core/writes.py obj_trash_tick) deletes them after the period with
the thread rule of before (a thread's first message stays while replies point at it) and their files (tcx_trash_paths,
unlinked after the commit); files/trashpurge.py no longer has a run of its own for them.
2.972.0 (#5272): the comments of tasks are rows of the comments' core: their trash (obj_comment_trash, the files with the same
time) is core/objcomments.py ocm_trash / ocm_restore with the task's hooks of collab/comments.py; comment_trash_text is gone.
2.981.0 (#5274, stage Q4c): the team chat's kept text too -- obj_comment_trash, kind 'tchat' (core/objcomments.py
ocm_trash_keep / ocm_trash_take / ocm_trash_forget); tchat_trash_text is gone. The reactions of a deleted message stay in
obj_reactions until the trash run (kalmido_orx_gone deletes them with the row), so a restore brings them back (decided
08.11.2026, question 5)."""
from ..core.db import iso_ms, now_utc
from ..core.objparts import part_kind  # 2.783.0 (#5368)
from ..core.access import live_sql  # 2.783.0 (#5368)
from ..core.objcomments import ocm_trash_drop, ocm_trash_forget, ocm_trash_keep, ocm_trash_take  # 2.972.0 (#5272); 2.981.0 (#5274)
from ..core.objhooks import USER_GONE  # 2.981.0 (#5274)


def tcx_trash(c, mid):
    """Team chat message mid into the trash: text (and the ciphertext of an encrypted one) kept, files stay. Caller commits."""
    m = c.execute(f"SELECT body, enc FROM tchat_msgs WHERE id=? AND {live_sql()} FOR UPDATE", (mid,)).fetchone()
    if not m:
        return None
    ts = iso_ms(now_utc())
    ocm_trash_keep(c, "tchat", mid, m["body"] or "", enc=m["enc"])  # 2.981.0 (#5274): the core's trash, kind 'tchat'
    c.execute("UPDATE tchat_msgs SET deleted_at=?, edited_at=?, body='', enc=NULL WHERE id=?", (ts, ts, mid))
    return ts


def tcx_restore(c, mid):
    """A team chat message from the trash back. -> True / False (nothing kept). edited_at moves on: open chats reload it."""
    if not c.execute("SELECT 1 FROM tchat_msgs WHERE id=? AND deleted_at IS NOT NULL FOR UPDATE", (mid,)).fetchone():
        return False
    r = ocm_trash_take(c, "tchat", mid)  # 2.981.0 (#5274): only the kind 'tchat' (a comment may have the same id)
    if not r:
        return False
    c.execute("UPDATE tchat_msgs SET body=?, enc=?, deleted_at=NULL, edited_at=? WHERE id=?", (r["body"], r["enc"], iso_ms(now_utc()), mid))
    return True


def tcx_trash_paths(c, where, args):
    """The trash run: the files of the deleted messages matching where (on tchat_msgs) -- their scan / text rows go now (no FK),
    the paths for the caller to unlink after the commit (the rows cascade with the message)."""
    rows = c.execute(f"SELECT f.id, f.path FROM tchat_files f WHERE f.message_id IN (SELECT id FROM tchat_msgs WHERE {where})", args).fetchall()
    for i in range(0, len(rows), 500):
        ids = [x["id"] for x in rows[i:i + 500]]
        q = ",".join("?" * len(ids))
        c.execute(f"DELETE FROM upload_scan WHERE kind='tchat' AND ref_id IN ({q})", ids)
        c.execute(f"DELETE FROM file_text WHERE kind='tchat' AND ref_id IN ({q})", ids)
    return [x["path"] for x in rows if x["path"]]


def ctt_purge_list(c, lid):
    """The end of an encryption switch of list lid (collab/liste2e.py, like atr_purge_list): the kept texts of its deleted
    comments and of the deleted messages of its channel were not converted -- they go for good now (a restore would bring back
    a plain text into a locked list, or an old ciphertext). The files of those messages: rows now, -> paths to unlink after
    the commit (the comment files went with atr_purge_list)."""
    ocm_trash_drop(c, "task", [r[0] for r in c.execute("SELECT id FROM tasks WHERE list_id=?", (lid,))])  # 2.972.0 (#5272)
    w = "deleted_at IS NOT NULL AND room_id IN (SELECT id FROM tchat_rooms WHERE kind='list' AND list_id=?)"
    paths = tcx_trash_paths(c, w, (lid,))
    c.execute(f"DELETE FROM tchat_files WHERE message_id IN (SELECT id FROM tchat_msgs WHERE {w})", (lid,))
    ocm_trash_forget(c, "tchat", f"SELECT id FROM tchat_msgs WHERE {w}", (lid,))  # 2.981.0 (#5274)
    return paths


def tcx_purge_user(c, uid):
    """2.981.0 (#5274): an account is deleted (accounts/users.py, core/objhooks.py USER_GONE): the kept texts of its deleted
    team chat messages go (nobody may bring its words back; the rows stay with user_id NULL). Only kind 'tchat'. Caller commits."""
    ocm_trash_forget(c, "tchat", "SELECT id FROM tchat_msgs WHERE user_id=? AND deleted_at IS NOT NULL", (uid,))


USER_GONE.append(tcx_purge_user)


TCX_MSG_KIND = "tchat_msg"  # 2.783.0 (#5368): the core's retention run of the team chat's tombstones (module docstring)
part_kind(TCX_MSG_KIND, "tchat_msgs", lock="tchat-msg-{id}", agent=False, trash_prune=True,
          prune=" AND NOT EXISTS (SELECT 1 FROM tchat_msgs r WHERE r.thread_of=tchat_msgs.id)", on_prune=tcx_trash_paths)
