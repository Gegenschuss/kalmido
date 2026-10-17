"""2.67.0 B (#1865): the dependency chain moves along ("Move dependent tasks along", list setting dep_shift).

When a task's due date moves LATER by n days, every task waiting on it moves by the same n days (start and due, the
gaps between them stay), and so on down the whole chain: breadth-first with a seen set (each task once per trigger,
so a diamond A->B->D, A->C->D moves D once; a cycle that slipped into the database ends there), at most DCH_MAX tasks.
The setting of the list of the TRIGGERING task decides, and it holds for the whole chain (also for waiting tasks in
other project lists); the person still needs write access to each task that moves.
Stays put and ends that branch (the chain behind it is not followed): completed tasks, milestones, tasks without a
due date, tasks the person cannot change -> `skipped` [{id, title, reason}] (no id / title for a task they cannot see).
Tasks in the trash and in lists that are no projects (dependencies inactive there) are passed silently.
Moving a task earlier never moves the chain back; "Pull the chain in" (POST /api/tasks/<id>/chain/pull) does that on
request. Every move is a normal date change through apply_update (activity line "dep_shift", reminders re-armed,
agent events, webhooks, delta sync); recurring tasks move this occurrence only, like a drag."""
from datetime import date, timedelta
from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, write_lock
from ..accounts.session import me
from ..core.access import need_project, need_task, task_visible

DCH_MAX = 500


def dch_days(old, new):
    """Whole days from old to new (ISO dates; a time part is ignored), 0 when one is missing / invalid."""
    try:
        return (date.fromisoformat(str(new)[:10]) - date.fromisoformat(str(old)[:10])).days if old and new else 0
    except ValueError:
        return 0


def dch_add(d, n):
    return (date.fromisoformat(str(d)[:10]) + timedelta(days=n)).isoformat() if d else None


def dch_switch(c, tid):
    """The list setting of the triggering task: on in a project list with dep_shift = 1."""
    r = c.execute("SELECT l.kind, l.dep_shift FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    return bool(r) and r["kind"] == "project" and bool(r["dep_shift"])


def dch_skip(c, uid, w, reason):
    if task_visible(c, w["id"], uid):
        return {"id": w["id"], "title": w["title"], "reason": reason, "hidden": False}
    # never an id / title / state of a task they cannot see (done or a milestone would tell something about it)
    return {"id": None, "title": None, "reason": "no_access", "hidden": True}


def dch_plan(c, uid, roots, delta, seen, room=DCH_MAX):
    """[(row, new_start, new_due)] for everything behind roots moved by delta days + the skipped rows. Nothing is written."""
    plan, skipped, todo = [], [], list(roots)
    while todo:
        bid = todo.pop(0)
        for w in c.execute("""SELECT t.id, t.title, t.start, t.due, t.status, t.ms, t.deleted_at, t.list_id, l.kind
                              FROM task_deps d JOIN tasks t ON t.id=d.task_id JOIN lists l ON l.id=t.list_id
                              WHERE d.blocker_id=? ORDER BY t.id""", (bid,)).fetchall():
            if w["id"] in seen:
                continue
            seen.add(w["id"])
            if w["deleted_at"] or w["kind"] != "project":
                continue
            reason = "done" if w["status"] != 0 else "milestone" if w["ms"] else "no_date" if not w["due"] else \
                None if task_visible(c, w["id"], uid, write=True) else "no_access"
            if not reason and len(plan) >= room:  # the cap: one note, the rest stays where it is
                skipped.append({"id": None, "title": None, "reason": "limit", "hidden": True})
                return plan, skipped
            if reason:
                skipped.append(dch_skip(c, uid, w, reason))
                continue
            try:
                nd, ns = dch_add(w["due"], delta), dch_add(w["start"], delta)
            except (ValueError, OverflowError):
                skipped.append(dch_skip(c, uid, w, "error"))
                continue
            plan.append((w, ns, nd))
            todo.append(w["id"])
    return plan, skipped


def dch_apply(c, plan, moved, skipped):
    from ..tasks.lifecycle import apply_update
    for w, ns, nd in plan:
        if apply_update(c, w["id"], {"due": nd, "start": ns, "_act": "dep_shift"}):
            skipped.append({"id": w["id"], "title": w["title"], "reason": "error", "hidden": False})
            continue
        moved.append({"id": w["id"], "title": w["title"], "start": ns, "due": nd, "prev_start": w["start"], "prev_due": w["due"]})


def dch_shift(c, uid, tid, old_due, new_due, seen=None, moved=None, skipped=None):
    """Called after tid's due date changed (PATCH, drag onto a day, roadmap shift). Moves the chain when it moved later
    and tid's list has the setting on. Returns moved [{id, title, start, due, prev_start, prev_due}] (the answer's
    `shifted`); skipped is filled in. seen / moved / skipped: shared by the calls of one request (roadmap)."""
    moved = [] if moved is None else moved
    skipped = [] if skipped is None else skipped
    delta = dch_days(old_due, new_due)
    if delta <= 0 or not dch_switch(c, tid):
        return moved
    write_lock(c, "depchain")  # 2.67.0 (#1865, review): two moves at once must not both shift the same waiting tasks
    seen = {tid} if seen is None else seen
    seen.add(tid)
    plan, sk = dch_plan(c, uid, [tid], delta, seen, DCH_MAX - len(moved))
    skipped += sk
    dch_apply(c, plan, moved, skipped)
    return moved


def dch_chain(moved, skipped, days):
    """The `chain` field of an answer."""
    return {"moved": [{"id": m["id"], "title": m["title"], "start": m["start"], "due": m["due"], "old_start": m["prev_start"],
                       "old_due": m["prev_due"]} for m in moved], "skipped": skipped, "days": days if moved or skipped else 0}


@app.post("/api/tasks/<int:tid>/chain/pull")
def dch_pull(tid):
    """{dry?}: "Pull the chain in". gap = the smallest buffer between tid's due date and the start (else due) of the tasks
    waiting on it directly that could move: min(start_or_due(w)) - (due(tid) + 1 day). gap > 0: the whole chain behind
    tid moves gap days earlier (gaps between them stay, the same stay-put rules as above); gap <= 0: nothing to do.
    dry = only the plan. The answer: {chain, shifted, gap} (shifted: like PATCH, for one undo step)."""
    c = db()
    uid = me()
    need_task(c, tid, write=False)
    t = c.execute("SELECT list_id, due, status, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
    need_project(c, t["list_id"], "deps")
    if t["deleted_at"]:
        return err(tr("The task is in the trash"), 409)
    if not t["due"]:
        return err(tr("This task has no date"))
    dry = bool(body().get("dry"))
    if not dry:
        write_lock(c, "depchain")
    first = []
    for w in c.execute("""SELECT t.id, t.start, t.due FROM task_deps d JOIN tasks t ON t.id=d.task_id JOIN lists l ON l.id=t.list_id
                          WHERE d.blocker_id=? AND t.status=0 AND t.deleted_at IS NULL AND t.due IS NOT NULL
                          AND (t.ms IS NULL OR t.ms=0) AND l.kind='project' ORDER BY t.id""", (tid,)).fetchall():
        if task_visible(c, w["id"], uid, write=True):
            first.append(dch_days(dch_add(t["due"], 1), w["start"] or w["due"]))
    gap = min(first) if first else 0
    moved, skipped = [], []
    if gap > 0:
        plan, skipped = dch_plan(c, uid, [tid], -gap, {tid})
        if dry:
            moved = [{"id": w["id"], "title": w["title"], "start": ns, "due": nd, "prev_start": w["start"], "prev_due": w["due"]}
                     for w, ns, nd in plan]
        else:
            dch_apply(c, plan, moved, skipped)
            if moved:
                bump(c)
                c.commit()
    return jsonify(ok=True, gap=max(gap, 0), dry=dry, chain=dch_chain(moved, skipped, -gap if gap > 0 else 0),
                   shifted=[] if dry else moved)
