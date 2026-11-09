"""2.530.0 A (#4315): the trash of comments and team chat messages (audit #2425 B36, B37, B11).

Deleting a comment or a team chat message was final: its text emptied, its files gone from the disk. Now it goes into a
trash for the trash period (ret_days("trash")): the row keeps looking deleted exactly as before (body '', deleted_at set),
so no read path (app, v1 / MCP, agent events, search, exports, notifications, file downloads) ever sees the kept text; the
text waits in comment_trash_text / tchat_trash_text, the files stay as rows and on disk:
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
unlinked after the commit); files/trashpurge.py no longer has a run of its own for them."""
from ..core.db import iso_ms, now_utc
from ..core.objparts import part_kind  # 2.783.0 (#5368)
from ..core.access import live_sql  # 2.783.0 (#5368)


def cmt_trash(c, cid):
    """Comment cid into the trash: its text kept, its files into the attachment trash (same timestamp). The caller checked
    the rights and commits."""
    r = c.execute(f"SELECT body, mentions FROM comments WHERE id=? AND {live_sql()} FOR UPDATE", (cid,)).fetchone()
    if not r:
        return None
    ts = iso_ms(now_utc())
    c.execute("INSERT INTO comment_trash_text(comment_id, body, mentions) VALUES(?,?,?) ON CONFLICT(comment_id) DO UPDATE "
              "SET body=excluded.body, mentions=excluded.mentions", (cid, r["body"] or "", r["mentions"] or ""))
    c.execute(f"UPDATE attachments SET deleted_at=? WHERE comment_id=? AND {live_sql()}", (ts, cid))
    c.execute("UPDATE comments SET body='', mentions='', deleted_at=? WHERE id=?", (ts, cid))
    return ts


def cmt_restore(c, cid):
    """A comment from the trash back (text, mentions, the files it had at the delete). -> True, or False when there is nothing
    to restore (deleted before 2.530, or the trash run was quicker). The caller checked the rights and commits."""
    r = c.execute("SELECT k.deleted_at, x.body, x.mentions FROM comments k JOIN comment_trash_text x ON x.comment_id=k.id "
                  "WHERE k.id=? AND k.deleted_at IS NOT NULL FOR UPDATE OF k", (cid,)).fetchone()
    if not r:
        return False
    c.execute("UPDATE attachments SET deleted_at=NULL WHERE comment_id=? AND deleted_at=?", (cid, r["deleted_at"]))
    c.execute("UPDATE comments SET body=?, mentions=?, deleted_at=NULL WHERE id=?", (r["body"], r["mentions"], cid))
    c.execute("DELETE FROM comment_trash_text WHERE comment_id=?", (cid,))
    return True


def tcx_trash(c, mid):
    """Team chat message mid into the trash: text (and the ciphertext of an encrypted one) kept, files stay. Caller commits."""
    m = c.execute(f"SELECT body, enc FROM tchat_msgs WHERE id=? AND {live_sql()} FOR UPDATE", (mid,)).fetchone()
    if not m:
        return None
    ts = iso_ms(now_utc())
    c.execute("INSERT INTO tchat_trash_text(message_id, body, enc) VALUES(?,?,?) ON CONFLICT(message_id) DO UPDATE "
              "SET body=excluded.body, enc=excluded.enc", (mid, m["body"] or "", m["enc"]))
    c.execute("UPDATE tchat_msgs SET deleted_at=?, edited_at=?, body='', enc=NULL WHERE id=?", (ts, ts, mid))
    return ts


def tcx_restore(c, mid):
    """A team chat message from the trash back. -> True / False (nothing kept). edited_at moves on: open chats reload it."""
    r = c.execute("SELECT x.body, x.enc FROM tchat_msgs m JOIN tchat_trash_text x ON x.message_id=m.id "
                  "WHERE m.id=? AND m.deleted_at IS NOT NULL FOR UPDATE OF m", (mid,)).fetchone()
    if not r:
        return False
    c.execute("UPDATE tchat_msgs SET body=?, enc=?, deleted_at=NULL, edited_at=? WHERE id=?", (r["body"], r["enc"], iso_ms(now_utc()), mid))
    c.execute("DELETE FROM tchat_trash_text WHERE message_id=?", (mid,))
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
    c.execute("DELETE FROM comment_trash_text WHERE comment_id IN (SELECT k.id FROM comments k JOIN tasks t ON t.id=k.task_id "
              "WHERE t.list_id=?)", (lid,))
    w = "deleted_at IS NOT NULL AND room_id IN (SELECT id FROM tchat_rooms WHERE kind='list' AND list_id=?)"
    paths = tcx_trash_paths(c, w, (lid,))
    c.execute(f"DELETE FROM tchat_files WHERE message_id IN (SELECT id FROM tchat_msgs WHERE {w})", (lid,))
    c.execute(f"DELETE FROM tchat_trash_text WHERE message_id IN (SELECT id FROM tchat_msgs WHERE {w})", (lid,))
    return paths


TCX_MSG_KIND = "tchat_msg"  # 2.783.0 (#5368): the core's retention run of the team chat's tombstones (module docstring)
part_kind(TCX_MSG_KIND, "tchat_msgs", lock="tchat-msg-{id}", agent=False, trash_prune=True,
          prune=" AND NOT EXISTS (SELECT 1 FROM tchat_msgs r WHERE r.thread_of=tchat_msgs.id)", on_prune=tcx_trash_paths)
