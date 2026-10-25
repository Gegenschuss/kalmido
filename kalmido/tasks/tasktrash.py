"""2.116.0 A (#2063): the trash period of tasks. The watchdog (at most hourly) deletes for good every task that lies in
the trash longer than ret_days("trash") (KALMIDO_TRASH_DAYS, 30) -- the same way "Empty trash" does (hard_delete:
subtasks, comments, field values, history, index rows go by ON DELETE CASCADE; the attachment files after the commit).

The run is system-wide: tasks in shared lists of other owners go too (the manual "Empty" leaves those to the list owner),
whoever moved them to the trash; organisation tasks are only deleted, never moved. Like every retention run it only
counts while ret_on("trash") is off (the safe default) and reports the numbers with ret_report(..., run="tasks").

Legal retention: office records (invoices, receipts, bookings, agreements, sign-offs, trip items) keep a plain task_id
number or ON DELETE SET NULL (time entries); none of them cascades from a task, and receipts are file-store nodes, not
task attachments. Deleting a task therefore never removes an office record. A file path another row still uses is kept.
2.272.0 A (#3026): tasks of a project kept by law (lists.retain_until in the future, lists.list_keep) stay until its end --
also as subtasks of a due task elsewhere (detached) -- and are counted as tasks_kept.
"""
import time

from ..core.db import bump, now_utc
from ..core.serializers import unlink_files
from ..core.retention import ret_days, ret_on, ret_report, ret_trash_cut, ret_trash_days  # 2.152.0: core/retention.py is here (its fallback went)
from .tasks import hard_delete
from ..core.pg import system_ctx  # 2.149.0 G (#2517): pulled up from functions

TTP_TICK = {"at": 0.0}
TTP_BATCH = 500  # tasks per run; the rest follows in the next hour


def ttp_days():
    """The trash period of tasks in days (the client shows it in the trash)."""
    return ret_trash_days()  # 2.116.0 review F1: 0 (a typo, an empty template) never means "everything now"


def ttp_cut():
    return ret_trash_cut()  # 2.272.0 A (#3026): the one floor of retention.py


# 2.272.0 A (#3026): a task of a list kept by law (lists.retain_until today or later, lists.list_keep) is not due
TTP_KEPT = "EXISTS (SELECT 1 FROM lists l WHERE l.id={0}.list_id AND l.retain_until>=?)"


def ttp_today():
    return now_utc().date().isoformat()


def ttp_purge(c, ids, cut):
    """Deletes these trashed tasks for good. Every row is locked and checked again (still in the trash since before cut?
    restored meanwhile = it stays). Subtasks not due themselves (restored, or trashed later) are detached and keep their
    own period. -> (number deleted, attachment paths to unlink after the commit)."""
    q = ",".join("?" * len(ids))
    today = ttp_today()
    due = [r[0] for r in c.execute(f"SELECT id FROM tasks WHERE id IN ({q}) AND deleted_at IS NOT NULL AND deleted_at<? "
                                   f"AND NOT {TTP_KEPT.format('tasks')} ORDER BY id FOR UPDATE", (*ids, cut, today))]
    if not due:
        return 0, []
    from .validation import descendants
    lists = set()
    for tid in due:
        for k in descendants(c, tid):
            r = c.execute("SELECT id, list_id, parent_id, deleted_at FROM tasks WHERE id=?", (k,)).fetchone()
            if not r:
                continue
            if r["deleted_at"] is None or r["deleted_at"] >= cut or c.execute(  # 2.272.0 A (#3026): or kept by law
                    f"SELECT 1 FROM tasks WHERE id=? AND {TTP_KEPT.format('tasks')}", (r["id"], today)).fetchone():
                c.execute("UPDATE tasks SET parent_id=NULL WHERE id=?", (r["id"],))
            lists.add(r["list_id"])
    lists -= {None}
    lists |= {r[0] for r in c.execute(f"SELECT DISTINCT list_id FROM tasks WHERE id IN ({q})", due)}
    # the subtasks still below are due themselves: lists = all their lists, so hard_delete detaches nothing more
    files = hard_delete(c, due, lists=lists)
    if files:  # a path another attachment / list file still uses stays on disk
        f = ",".join("?" * len(files))
        used = {r[0] for r in c.execute(f"SELECT path FROM attachments WHERE path IN ({f}) UNION SELECT path FROM list_files "
                                        f"WHERE path IN ({f})", (*files, *files))}
        files = [p for p in files if p not in used]
    return len(due), files


def ttp_tick(c, force=False):
    """The watchdog (at most hourly): trashed tasks older than the period -- counted, and deleted when the switch is on.
    Returns the counts (tests call it with force=True)."""
    if not force and time.time() - TTP_TICK["at"] < 3600:
        return {}
    TTP_TICK["at"] = time.time()
    if ret_days("trash") < 1:  # 2.116.0 review F1: a period of 0 switches the run off instead of emptying every trash
        return {}
    purge, cut, counts, files = ret_on("trash"), ttp_cut(), {}, []
    # the trash of every organisation and private space (row-level security); nothing is handed to a person, rows only go
    with system_ctx(c):
        today = ttp_today()
        kept = c.execute(f"SELECT COUNT(*) FROM tasks WHERE deleted_at IS NOT NULL AND deleted_at<? AND {TTP_KEPT.format('tasks')}",
                         (cut, today)).fetchone()[0]
        if purge:
            ids = [r[0] for r in c.execute("SELECT id FROM tasks WHERE deleted_at IS NOT NULL AND deleted_at<? "
                                           f"AND NOT {TTP_KEPT.format('tasks')} ORDER BY deleted_at, id LIMIT ?", (cut, today, TTP_BATCH))]
            n, files = ttp_purge(c, ids, cut) if ids else (0, [])
            counts = {"tasks": n, "attachments": len(files), "tasks_kept": kept}
            if n:
                bump(c)  # clients drop the rows from their trash view (dl_changes of this transaction)
        else:
            counts = {"tasks": c.execute("SELECT COUNT(*) FROM tasks WHERE deleted_at IS NOT NULL AND deleted_at<? "
                                         f"AND NOT {TTP_KEPT.format('tasks')}", (cut, today)).fetchone()[0],
                      "attachments": c.execute("SELECT COUNT(*) FROM attachments a JOIN tasks t ON t.id=a.task_id "
                                               f"WHERE t.deleted_at IS NOT NULL AND t.deleted_at<? AND NOT {TTP_KEPT.format('t')}",
                                               (cut, today)).fetchone()[0], "tasks_kept": kept}
        ret_report(c, "trash", counts, purge, run="tasks")
    c.commit()
    unlink_files(files)  # after the commit: a failed commit keeps the rows and their files
    return counts
