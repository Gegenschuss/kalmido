"""2.905.0 (#5284, stage Q8a of the cross-cutting core, analysis #3563): read marks exist once, in the shared core.

One table obj_seen (migrations.d/5284_a.py) holds a person's read mark on an object: (kind, ref_id, user_id, seen_id, seen_at).
seen_id is a high-water mark: everything of the object up to that id counts as seen; it only grows (osn_mark keeps the higher
one). It replaces task_seen (unread comments of a task). Kinds:

    task    tasks.id   seen_id = the highest comment id of the task the person has seen (collab/comments.py, the badge of
                       core/serializers.py, the change feed of tasks/delta.py: a mark changes the task for its reader only)

Tenant boundary: a mark is read and written only for the person it belongs to (the callers pass the signed-in person or the
person acting); the area checks the object before it writes one. No organisation column: the mark holds ids only and says
nothing about the object (a mark left after a right is gone shows nothing). A task deleted for good takes its marks along
(trigger kalmido_osn_gone). Not in the exports: a personal view state, like before (admin/exportleft.py).
"""
from .db import now_utc

OSN_KINDS = ("task",)


def osn_mark(c, kind, ref_id, uid, seen_id, at=None):
    """uid has seen everything of object ref_id of kind up to seen_id (the higher mark stays). The caller commits."""
    if kind not in OSN_KINDS:
        raise ValueError(kind)
    c.execute("INSERT INTO obj_seen(kind, ref_id, user_id, seen_id, seen_at) VALUES(?,?,?,?,?) "
              "ON CONFLICT(kind, ref_id, user_id) DO UPDATE SET seen_id=excluded.seen_id, seen_at=excluded.seen_at "
              "WHERE excluded.seen_id > obj_seen.seen_id",
              (kind, int(ref_id), int(uid), int(seen_id or 0), at or now_utc()))


def osn_get(c, kind, ref_id, uid):
    """uid's own mark on object ref_id of kind (0 = nothing seen yet)."""
    r = c.execute("SELECT seen_id FROM obj_seen WHERE kind=? AND ref_id=? AND user_id=?", (kind, int(ref_id), int(uid))).fetchone()
    return r[0] if r else 0


# ---- the move of task_seen (once; core/db.py init_db calls it before the fragment's AFTER drops the table)
def osn_move(c):
    """2.905.0 (#5284): the rows of task_seen into obj_seen (kind 'task') while that table is there (the first start of 2.905,
    or again after a version before 2.905 ran and made it anew). The higher mark wins. The fragment 5284_a drops task_seen right
    after (one-way). Returns the rows moved."""
    if not c.execute("SELECT to_regclass('task_seen')").fetchone()[0]:
        return 0
    return c.execute("""INSERT INTO obj_seen(kind, ref_id, user_id, seen_id, seen_at)
                        SELECT 'task', s.task_id, s.user_id, s.seen_id, now() FROM task_seen s
                        ON CONFLICT(kind, ref_id, user_id) DO UPDATE SET seen_id=excluded.seen_id
                        WHERE excluded.seen_id > obj_seen.seen_id""").rowcount
