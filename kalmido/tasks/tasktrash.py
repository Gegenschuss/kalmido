"""2.116.0 A (#2063): the trash period of tasks. The watchdog (at most hourly) deletes for good every task that lies in
the trash longer than ret_days("trash") (KALMIDO_TRASH_DAYS, 30) -- the same way "Empty trash" does (hard_delete:
subtasks, comments, field values, history, index rows go by ON DELETE CASCADE; the attachment files after the commit).

The run is system-wide: tasks in shared lists of other owners go too (the manual "Empty" leaves those to the list owner),
whoever moved them to the trash; organisation tasks are only deleted, never moved. Like every retention run it only
counts while ret_on("trash") is off (the safe default) and reported the numbers with ret_report(..., run="tasks") (see below).

Legal retention: office records (invoices, receipts, bookings, agreements, sign-offs, trip items) keep a plain task_id
number or ON DELETE SET NULL (time entries); none of them cascades from a task, and receipts are file-store nodes, not
task attachments. Deleting a task therefore never removes an office record. A file path another row still uses is kept.
2.272.0 A (#3026): tasks of a project kept by law (lists.retain_until in the future, lists.list_keep) stay until its end --
also as subtasks of a due task elsewhere (detached) -- and are counted as tasks_kept.
2.936.0 (#5364, stage 2a of the core's trash): the run is the core's (core/writes.py obj_trash_tick over the light kind task
of core/objlight.py: trash_prune, trash_keep=ttp_keep, its obj_on_purge hook ttp_core_purge): one retention run for every
trash of the core, its report run "obj_trash" with the numbers task / task_kept / task_locked; ttp_tick went.
2.1028.0 (#5536, stage 2c): a person's delete for good ("Empty trash", DELETE /api/tasks/<id>?hard=1, its background job) goes
the same way: the routes check their rights, then core/writes.py obj_purge(checked=True) per task inside ttp_manual(own) --
the hook deletes any task in the trash (no period), detaches the subtasks outside own (lists the person may empty) and keeps
the tasks of a project kept by law (409 with its date). The old purge of the routes (hard_delete, tre_kept) went.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from ..core.access import Denied, trash_sql  # 2.936.0 (#5364): no handwritten trash filter
from ..core.db import now_utc
from ..core.i18n import tr
from ..core.retention import ret_trash_cut, ret_trash_days  # 2.152.0: core/retention.py is here (its fallback went)
from .tasks import hard_delete
from .validation import descendants  # 2.369.5 (#2517): pulled up from functions

TTP_BATCH = 500  # tasks per run; the rest follows in the next hour (obj_register trash_batch of the kind task)


def ttp_days():
    """The trash period of tasks in days (the client shows it in the trash)."""
    return ret_trash_days()  # 2.116.0 review F1: 0 (a typo, an empty template) never means "everything now"


def ttp_cut():
    return ret_trash_cut()  # 2.272.0 A (#3026): the one floor of retention.py


# 2.272.0 A (#3026): a task of a list kept by law (lists.retain_until today or later, lists.list_keep) is not due
TTP_KEPT = "EXISTS (SELECT 1 FROM lists l WHERE l.id={0}.list_id AND l.retain_until>=?)"


def ttp_today():
    return now_utc().date().isoformat()


def ttp_purge(c, ids, cut, own=None):
    """Deletes these trashed tasks for good. Every row is locked and checked again (still in the trash since before cut?
    restored meanwhile = it stays). Subtasks not due themselves (restored, or trashed later) are detached and keep their
    own period. -> (number deleted, attachment paths to unlink after the commit).
    2.1028.0 (#5536): cut None = a person's delete for good (any time in the trash); own = the lists whose tasks the person
    may delete for good -- a subtask in another list is detached and stays with its list (as hard_delete did)."""
    q = ",".join("?" * len(ids))
    today = ttp_today()
    tq, ta = ("", ()) if cut is None else (" AND deleted_at<?", (cut,))
    due = [r[0] for r in c.execute(f"SELECT id FROM tasks WHERE id IN ({q}) AND {trash_sql()}{tq} "
                                   f"AND NOT {TTP_KEPT.format('tasks')} ORDER BY id FOR UPDATE", (*ids, *ta, today))]
    if not due:
        return 0, []
    lists = set()
    for tid in due:
        for k in descendants(c, tid):
            r = c.execute("SELECT id, list_id, parent_id, deleted_at FROM tasks WHERE id=?", (k,)).fetchone()
            if not r:
                continue
            if r["deleted_at"] is None or (cut is not None and r["deleted_at"] >= cut) or (
                    own is not None and r["list_id"] not in own) or c.execute(  # 2.272.0 A (#3026): or kept by law
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


def ttp_keep(a):
    """2.936.0 (#5364): obj_register trash_keep of the kind task -- the tasks of a project kept by law stay (TTP_KEPT)."""
    return TTP_KEPT.format(a), (ttp_today(),)


_TTP_MANUAL = ContextVar("ttp_manual", default=None)  # 2.1028.0 (#5536): {"own": set} of a person's delete for good


@contextmanager
def ttp_manual(own):
    """2.1028.0 (#5536): the core's purges within are a person's delete for good -- own = the list ids whose tasks they may
    delete for good (tasks/lifecycle.py purge_lists); the hook then takes any task in the trash, not only the ones due."""
    tok = _TTP_MANUAL.set({"own": set(own)})
    try:
        yield
    finally:
        _TTP_MANUAL.reset(tok)


def ttp_kept_until(c, ids):
    """The retain_until dates (newest first) of the projects kept by law among the lists of the tasks ids; [] = none kept
    (the numbers before "Empty trash" and the 409 of a delete for good)."""
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    return [r[0] for r in c.execute(f"SELECT DISTINCT l.retain_until FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id IN ({q}) "
                                    "AND l.retain_until>=? ORDER BY l.retain_until DESC", (*ids, ttp_today()))]


def ttp_core_purge(c, tid):
    """2.936.0 (#5364): the obj_on_purge hook of the kind task -- the core's retention run (core/writes.py obj_trash_prune, system
    context, the id checked again under its lock) deletes the task here the way "Empty trash" does (ttp_purge: subtasks not
    due are detached, attachments); the files go after its commit. Denied(409) = kept (restored or kept by law meanwhile):
    the run counts it as task_locked and the row stays.
    2.1028.0 (#5536): inside ttp_manual a person's delete for good (no period, subtasks outside own detached); a task of a
    project kept by law is Denied 409 with its date (the routes' message, was tre_kept)."""
    m = _TTP_MANUAL.get()
    n, files = ttp_purge(c, [int(tid)], None if m else ttp_cut(), own=m["own"] if m else None)
    if not n:
        kept = ttp_kept_until(c, [int(tid)])
        if kept:
            raise Denied(409, tr("This project keeps receipts by law until {0}: it can be deleted permanently after that.", kept[0]))
        raise Denied(409)
    return files
