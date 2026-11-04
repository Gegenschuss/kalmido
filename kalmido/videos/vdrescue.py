"""2.530.0 D (#4316, audit #2425 B2/B18): video sign-offs survive the hard delete of their task, project or client.
video_reviews.task_id / list_id / client_id are ON DELETE CASCADE: a task, list or client deleted for good (the trash runs,
"Empty trash", ?hard=1, a project or client deleted for good) took its reviews along -- with the customer's comments,
versions and approval records -- although video sign-offs have their own trash (deleted_at, videos/review.py
vdr_trash_prune after the trash period). Before such a delete the callers hand the doomed ids here: every review there goes
into its own trash (deleted_at, an older stamp stays) and lets go of the doomed place, so the cascade finds nothing. A
review at a task whose project lives on moves to that project (like videos/review.py vdr_move_space); otherwise it keeps
no place and hangs at its workspace (vdr_may: the owner of a private one, the organisation's people for an organisation's
one). Its public link stays off while it is in the trash (vdr_sig_row); a restore brings it back where it hangs now.
Kept small on purpose (no Flask, no review.py import): tasks/tasks.py hard_delete imports it."""
from ..core.db import iso, now_utc
from ..core.pg import st_ids, system_ctx


def vdr_rescue(c, task_ids=(), list_ids=(), client_ids=()):
    """Moves the reviews at these doomed tasks / lists / clients into the video trash before their hard delete (see the
    module docstring). System context: a review another person owns goes by the cascade too, so it is rescued as well
    (no content is read or handed out). The caller commits. -> number of reviews rescued."""
    tids, lids, cids = st_ids(task_ids or ()), st_ids(list_ids or ()), st_ids(client_ids or ())
    if not (task_ids or list_ids or client_ids):
        return 0
    ts, n = iso(now_utc()), 0
    doomed_l = set(int(x) for x in (list_ids or ()))
    with system_ctx(c):
        rows = c.execute("SELECT v.id, v.task_id, v.list_id, v.client_id, t.list_id AS tl, tl.deleted_at AS tld FROM video_reviews v "
                         "LEFT JOIN tasks t ON t.id=v.task_id LEFT JOIN lists tl ON tl.id=t.list_id "
                         "WHERE v.task_id = ANY(CAST(? AS BIGINT[])) OR v.list_id = ANY(CAST(? AS BIGINT[])) "
                         "OR v.client_id = ANY(CAST(? AS BIGINT[])) ORDER BY v.id FOR UPDATE OF v", (tids, lids, cids)).fetchall()
        doomed_t = set(int(x) for x in (task_ids or ()))
        doomed_c = set(int(x) for x in (client_ids or ()))
        for r in rows:
            tid, lid, cid = r["task_id"], r["list_id"], r["client_id"]
            if tid in doomed_t:
                tid = None
                # a review at a task moves to the task's project when that project lives on (not doomed, not in its trash)
                if lid is None and r["tl"] and r["tl"] not in doomed_l and not r["tld"]:
                    lid = r["tl"]
            if lid in doomed_l:
                lid = None
            if cid in doomed_c:
                cid = None
            c.execute("UPDATE video_reviews SET task_id=?, list_id=?, client_id=?, deleted_at=COALESCE(deleted_at, ?), updated_at=? WHERE id=?",
                      (tid, lid, cid, ts, ts, r["id"]))
            n += 1
    return n


def vdr_doomed_count(c, task_ids=(), list_ids=(), client_ids=()):
    """How many live (not trashed) reviews hang at these tasks / lists / clients: the number the delete dialogs name ("go to
    the video trash"). System context, numbers only."""
    if not (task_ids or list_ids or client_ids):
        return 0
    with system_ctx(c):
        return c.execute("SELECT COUNT(*) FROM video_reviews WHERE deleted_at IS NULL AND (task_id = ANY(CAST(? AS BIGINT[])) "
                         "OR list_id = ANY(CAST(? AS BIGINT[])) OR client_id = ANY(CAST(? AS BIGINT[])))",
                         (st_ids(task_ids or ()), st_ids(list_ids or ()), st_ids(client_ids or ()))).fetchone()[0]
