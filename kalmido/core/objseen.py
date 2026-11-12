"""2.905.0 (#5284, stage Q8a of the cross-cutting core, analysis #3563): read marks exist once, in the shared core.

One table obj_seen (migrations.d/5284_a.py) holds a person's read mark on an object: (kind, ref_id, user_id, seen_id, seen_at).
seen_id is a high-water mark: everything of the object up to that id counts as seen; it only grows (osn_mark keeps the higher
one). It replaces task_seen (unread comments of a task). Kinds:

    task    tasks.id   seen_id = the highest comment id of the task the person has seen (collab/comments.py, the badge of
                       core/serializers.py, the change feed of tasks/delta.py: a mark changes the task for its reader only)

    tchat   tchat_rooms.id 2.981.0 (#5286, stage Q8b): seen_id = the highest message id of the room's main conversation the
                           person has read (was tchat_reads.last_id; muted is a row of obj_follow, kind 'tchat', mode 'mute')
    tchat_thread  tchat_msgs.id  2.981.0 (#5286): the thread of that first message, seen_id = its highest answer read (was
                           tchat_thread_reads.last_id; taking part is a row of obj_follow, kind 'tchat_thread', mode 'watch')
    rss     rss_items.id   2.981.0 (#5286, stage Q8b): one row per article the person has read (seen_id = the article's id);
                           marking it unread again deletes the row (osn_clear). It replaced rss_reads (the feeds of an
                           organisation) and rss_items.read_at (private feeds): one model for both (life/rss.py)

Tenant boundary: a mark is read and written only for the person it belongs to (the callers pass the signed-in person or the
person acting); the area checks the object before it writes one. No organisation column: the mark holds ids only and says
nothing about the object (a mark left after a right is gone shows nothing). A task deleted for good takes its marks along
(trigger kalmido_osn_gone). Not in the exports: a personal view state, like before (admin/exportleft.py).
"""
from .db import now_utc
from .kernretire import kern_retire_floor

OSN_KINDS = ("task", "rss")  # 2.981.0 (#5286): + rss (the read articles of a feed)
OSN_KINDS += ("tchat", "tchat_thread")  # 2.981.0 (#5286): + a team chat room / thread (was tchat_reads / tchat_thread_reads)
OSN_KINDS += ("due",)  # 2.1037.0 (#5801): "seen for today" of the bell's deadline lines (collab/duebell.py; ref_id 1 today, 2 overdue)


def osn_mark(c, kind, ref_id, uid, seen_id, at=None, only_new=False):
    """uid has seen everything of object ref_id of kind up to seen_id (the higher mark stays). only_new (2.981.0, #5286): only
    when uid has no mark there yet (a thread's new participant starts at a given place, an older mark stays). The caller commits."""
    if kind not in OSN_KINDS:
        raise ValueError(kind)
    c.execute("INSERT INTO obj_seen(kind, ref_id, user_id, seen_id, seen_at) VALUES(?,?,?,?,?) ON CONFLICT(kind, ref_id, user_id) "
              + ("DO NOTHING" if only_new else "DO UPDATE SET seen_id=excluded.seen_id, seen_at=excluded.seen_at "
                 "WHERE excluded.seen_id > obj_seen.seen_id"),
              (kind, int(ref_id), int(uid), int(seen_id or 0), at or now_utc()))


def osn_drop(c, uids, kind, where, args=()):
    """2.981.0 (#5286): the marks of the people uids on the objects of kind whose ref_id matches where (an SQL condition on
    ref_id with its args) go -- a person left a room / an organisation. Returns the rows deleted. The caller commits."""
    if kind not in OSN_KINDS:
        raise ValueError(kind)
    ids = sorted({int(u) for u in ([uids] if isinstance(uids, int) else uids or ()) if u})
    if not ids:
        return 0
    return c.execute(f"DELETE FROM obj_seen WHERE kind=? AND user_id = ANY(CAST(? AS BIGINT[])) AND ({where})",
                     (kind, "{" + ",".join(map(str, ids)) + "}", *args)).rowcount


def osn_mark_sel(c, kind, uid, sel, args=(), at=None):
    """2.981.0 (#5286): uid's marks on every object the SQL sel returns (columns: ref_id, seen_id), the higher mark stays.
    Returns the ref_ids that got a new or higher mark. The caller commits (and checked the objects in sel)."""
    if kind not in OSN_KINDS:
        raise ValueError(kind)
    return [r[0] for r in c.execute(
        f"INSERT INTO obj_seen(kind, ref_id, user_id, seen_id, seen_at) SELECT ?, x.ref_id, ?, x.seen_id, CAST(? AS TIMESTAMPTZ) "
        f"FROM ({sel}) x ON CONFLICT(kind, ref_id, user_id) DO UPDATE SET seen_id=excluded.seen_id, seen_at=excluded.seen_at "
        "WHERE excluded.seen_id > obj_seen.seen_id RETURNING ref_id", (kind, int(uid), at or now_utc(), *args)).fetchall()]


def osn_clear(c, kind, uid, sel, args=()):
    """2.981.0 (#5286): uid's marks on the objects the SQL sel returns (one column: the ref_id) go (seen nothing of them).
    Returns the ref_ids cleared. The caller commits."""
    if kind not in OSN_KINDS:
        raise ValueError(kind)
    return [r[0] for r in c.execute(f"DELETE FROM obj_seen WHERE kind=? AND user_id=? AND ref_id IN ({sel}) RETURNING ref_id",
                                    (kind, int(uid), *args)).fetchall()]


def osn_seen_sql(kind, alias):
    """2.981.0 (#5286): SQL of uid's mark time on the object alias.id (one ? = the person; NULL = not seen)."""
    if kind not in OSN_KINDS:
        raise ValueError(kind)
    return f"(SELECT s.seen_at FROM obj_seen s WHERE s.kind='{kind}' AND s.ref_id={alias}.id AND s.user_id=?)"


def osn_get(c, kind, ref_id, uid):
    """uid's own mark on object ref_id of kind (0 = nothing seen yet)."""
    r = c.execute("SELECT seen_id FROM obj_seen WHERE kind=? AND ref_id=? AND user_id=?", (kind, int(ref_id), int(uid))).fetchone()
    return r[0] if r else 0


# ---- the move of task_seen (once; core/db.py init_db calls it before the fragment's AFTER drops the table)
def osn_move(c):
    """2.905.0 (#5284): the rows of task_seen into obj_seen (kind 'task') while that table is there (the first start of 2.905,
    or again after a version before 2.905 ran and made it anew). The higher mark wins. The fragment 5284_a drops task_seen right
    after (one-way). 2.981.0 (#5286): and the read articles (osn_move_rss). Returns the rows moved."""
    n = osn_move_rss(c) + osn_move_tchat(c)
    if not c.execute("SELECT to_regclass('task_seen')").fetchone()[0]:
        return n
    return n + c.execute("""INSERT INTO obj_seen(kind, ref_id, user_id, seen_id, seen_at)
                        SELECT 'task', s.task_id, s.user_id, s.seen_id, now() FROM task_seen s
                        ON CONFLICT(kind, ref_id, user_id) DO UPDATE SET seen_id=excluded.seen_id
                        WHERE excluded.seen_id > obj_seen.seen_id""").rowcount


OSN_ISO = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d{1,6})?(Z|[+-]\d\d:\d\d)$"
OSN_RSS_HOW = ("the read marks of feed articles moved into the shared core (obj_seen kind rss, #5286): rss_reads and rss_items.read_at "
               "were dropped - an older version would show every article unread; go back only with a backup from before")
OSN_OLD_RSS_READS = """INSERT INTO obj_seen(kind, ref_id, user_id, seen_id, seen_at)
    SELECT 'rss', r.item_id, r.user_id, r.item_id, CASE WHEN r.read_at ~ ? THEN r.read_at::timestamptz ELSE CURRENT_TIMESTAMP END
    FROM rss_reads r JOIN rss_items i ON i.id=r.item_id JOIN users u ON u.id=r.user_id
    ON CONFLICT DO NOTHING"""
# a private feed's articles carried the mark of their one reader (the feed's owner)
OSN_OLD_RSS_ITEMS = """INSERT INTO obj_seen(kind, ref_id, user_id, seen_id, seen_at)
    SELECT 'rss', i.id, f.user_id, i.id, CASE WHEN i.read_at ~ ? THEN i.read_at::timestamptz ELSE CURRENT_TIMESTAMP END
    FROM rss_items i JOIN rss_feeds f ON f.id=i.feed_id WHERE i.read_at IS NOT NULL AND f.org_id IS NULL
    ON CONFLICT DO NOTHING"""


OSN_TCHAT_HOW = ("the read marks of the team chat moved into the shared core (obj_seen / obj_follow kind tchat and tchat_thread, #5286): "
                 "tchat_reads and tchat_thread_reads were dropped - an older version would show every message unread; go back only "
                 "with a backup from before")
OSN_OLD_TCHAT = [
    # the room's read mark (a mark of 0 is no mark) and its mute
    """INSERT INTO obj_seen(kind, ref_id, user_id, seen_id, seen_at)
       SELECT 'tchat', d.room_id, d.user_id, d.last_id, CURRENT_TIMESTAMP FROM tchat_reads d
       JOIN tchat_rooms r ON r.id=d.room_id JOIN users u ON u.id=d.user_id WHERE d.last_id > 0
       ON CONFLICT(kind, ref_id, user_id) DO UPDATE SET seen_id=excluded.seen_id WHERE excluded.seen_id > obj_seen.seen_id""",
    """INSERT INTO obj_follow(user_id, kind, ref_id, mode)
       SELECT d.user_id, 'tchat', d.room_id, 'mute' FROM tchat_reads d JOIN tchat_rooms r ON r.id=d.room_id
       JOIN users u ON u.id=d.user_id WHERE d.muted <> 0 ON CONFLICT DO NOTHING""",
    # a thread's read mark and taking part
    """INSERT INTO obj_seen(kind, ref_id, user_id, seen_id, seen_at)
       SELECT 'tchat_thread', t.root_id, t.user_id, t.last_id, CURRENT_TIMESTAMP FROM tchat_thread_reads t
       JOIN tchat_msgs m ON m.id=t.root_id JOIN users u ON u.id=t.user_id WHERE t.last_id > 0
       ON CONFLICT(kind, ref_id, user_id) DO UPDATE SET seen_id=excluded.seen_id WHERE excluded.seen_id > obj_seen.seen_id""",
    """INSERT INTO obj_follow(user_id, kind, ref_id, mode)
       SELECT t.user_id, 'tchat_thread', t.root_id, 'watch' FROM tchat_thread_reads t JOIN tchat_msgs m ON m.id=t.root_id
       JOIN users u ON u.id=t.user_id WHERE t.follow <> 0 ON CONFLICT DO NOTHING""",
]


def osn_move_tchat(c):
    """2.981.0 (#5286): the team chat's read marks into obj_seen and its mute / taking part into obj_follow, while tchat_reads /
    tchat_thread_reads are there (the first start of 2.981, or after an older version ran). The higher mark wins; a mark of 0
    is no row. The fragment 5286_a drops both tables right after (one-way). Returns the rows moved."""
    n, old = 0, False
    for t, qs in (("tchat_reads", OSN_OLD_TCHAT[:2]), ("tchat_thread_reads", OSN_OLD_TCHAT[2:])):
        if c.execute("SELECT to_regclass(?)", (t,)).fetchone()[0]:
            old = True
            for q in qs:
                n += c.execute(q).rowcount
    if old:  # the back limit = the minor of the image that moves (core/kernretire.py), not the package label
        kern_retire_floor(c, how=OSN_TCHAT_HOW)
    return n


def osn_move_rss(c):
    """2.981.0 (#5286): the read marks of articles into obj_seen (kind 'rss'): the rows of rss_reads (an organisation's feeds)
    and rss_items.read_at (private feeds), while they are there (the first start of 2.981, or after an older version ran).
    An old time that is not in the app's ISO form becomes the time of the move. The fragment 5286_a drops rss_reads and the
    column right after (one-way). Returns the rows moved."""
    n, old = 0, False
    if c.execute("SELECT to_regclass('rss_reads')").fetchone()[0]:
        n += c.execute(OSN_OLD_RSS_READS, (OSN_ISO,)).rowcount
        old = True
    if c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='rss_items' "
                 "AND column_name='read_at'").fetchone():
        n += c.execute(OSN_OLD_RSS_ITEMS, (OSN_ISO,)).rowcount
        old = True
    if old:  # the back limit = the minor of the image that moves (core/kernretire.py), not the package label
        kern_retire_floor(c, how=OSN_RSS_HOW)
    return n
