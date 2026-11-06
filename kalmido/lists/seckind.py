"""2.577.0 (#3354): the meaning of a column (sections.kind): '' = none, open, progress, review, done, rejected.
Five fixed meanings, the column's name stays free. Moving a task into a done column completes it, into a rejected column
marks it "won't do", out of them (same project) opens it again. A tick moves the task into the project's first done column
when completed tasks stay in their column (the same for "won't do"), reopening out of a done / rejected column moves it into
the first open column. The moves here write section_id directly and the status changes only happen on a move, so tick and
move never call each other. Only top level tasks move (a subtask follows its parent's section), lists without a meaning
behave as before.
section_kind of a task (API, MCP, webhooks): completed = done, won't do = rejected, else the meaning of its column, the
rest open."""
from flask import g, has_request_context

from ..core.ctx import me
from ..core.errors import BadInput, Denied
from ..core.i18n import tr

SEC_KINDS = ("open", "progress", "review", "done", "rejected")
SK_STATUS = {"done": 2, "rejected": -1}  # the columns that set a task's status
# the derived kind as SQL over the table tasks (GET /api/v1/tasks ?section_kind=, saved filters)
SK_SQL = ("CASE WHEN status=2 THEN 'done' WHEN status=-1 THEN 'rejected' ELSE COALESCE(NULLIF("
          "(SELECT s.kind FROM sections s WHERE s.id=tasks.section_id), ''), 'open') END")


def sk_clean(v, what="kind"):
    """A column's meaning from a client value: None / '' = none."""
    if v in (None, ""):
        return ""
    if v not in SEC_KINDS:
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def sk_derive(status, kind):
    """section_kind of a task: status first, then the meaning of its column."""
    return "done" if status == 2 else "rejected" if status == -1 else kind or "open"


def sk_of(c, sid):
    """The meaning of section sid ('' = none, or no section)."""
    r = c.execute("SELECT kind FROM sections WHERE id=?", (sid,)).fetchone() if sid else None
    return r[0] if r else ""


def sk_task(c, t):
    """section_kind of a tasks row."""
    return sk_derive(t["status"], sk_of(c, t["section_id"]))


def sk_first(c, lid, kind):
    """The first column of list lid with this meaning (None = none)."""
    r = c.execute("SELECT id FROM sections WHERE list_id=? AND kind=? ORDER BY sort, id LIMIT 1", (lid, kind)).fetchone()
    return r[0] if r else None


def sk_keeps(c, lid):
    """Do completed tasks of list lid stay in columns? The server's side of "Keep completed in their section" (client dsxOn);
    only asked for a list with a column of that meaning, so "null = default" means on."""
    from ..family.family import is_shop
    r = c.execute("SELECT checklist, done_in_section FROM lists WHERE id=?", (lid,)).fetchone()
    return bool(r) and not r["checklist"] and not is_shop(c, lid) and (r["done_in_section"] is None or bool(r["done_in_section"]))


def sk_snap(c, tid):
    """The task's section_kind before this request changed it (webhook task.status_changed, see wh_enqueue)."""
    if has_request_context():
        m = g.setdefault("sk_old", {})
        if tid not in m:
            t = c.execute("SELECT status, section_id FROM tasks WHERE id=?", (tid,)).fetchone()
            if t:
                m[tid] = sk_task(c, t)


def _place(c, tid, sid):
    from ..tasks.validation import log_act
    c.execute("UPDATE tasks SET section_id=? WHERE id=?", (sid, tid))
    r = c.execute("SELECT name FROM sections WHERE id=?", (sid,)).fetchone() if sid else None
    log_act(c, tid, "section", {"name": r[0] if r else None})


def sk_after_status(c, t, status, undo=None, copy_id=None):
    """do_complete / reopen: t (the row before) changed its status by a tick, not by a move. copy_id: a recurring task, its
    completed copy is what moves; the original stays open in its column. undo (dict): "sec" [before, after] for sk_undo."""
    if t["parent_id"]:
        return
    was = sk_of(c, t["section_id"])
    if status == 0:
        sid = sk_first(c, t["list_id"], "open") if was in SK_STATUS else None
    else:
        want = next((k for k, v in SK_STATUS.items() if v == status), "")
        sid = sk_first(c, t["list_id"], want) if want and want != was else None
        if sid and not sk_keeps(c, t["list_id"]):
            sid = None
    if not sid:
        return
    _place(c, copy_id or t["id"], sid)
    if undo is not None and not copy_id:
        undo["sec"] = [t["section_id"], sid]


def sk_undo(c, t, u):
    """undo_status: the column a tick moved the task out of, while it is still where the tick put it."""
    s = u.get("sec")
    if not isinstance(s, list) or len(s) != 2 or t["section_id"] != s[1]:
        return
    if s[0] is None or c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (s[0], t["list_id"])).fetchone():
        c.execute("UPDATE tasks SET section_id=? WHERE id=?", (s[0], t["id"]))


def sk_gate(c, tid, sid):
    """A move into a done column ends at the review gate like a tick."""
    if sk_of(c, sid) == "done":
        from ..tasks.review import rvw_gate
        e = rvw_gate(c, tid)
        if e:
            raise Denied(409, e)


def sk_finish(c, tid, st):
    """A task gets status st (2 / -1) by a move: the steps of a tick. -> what do_complete left to undo, next date."""
    from ..collab.comments import task_event
    from ..notify.push import push_handled
    from ..tasks.dependencies import completed_ids, unblock_events
    from ..tasks.lifecycle import do_complete
    from ..tasks.validation import log_act
    undo = {}
    nxt = do_complete(c, tid, st, undo)
    log_act(c, tid, "wont" if st == -1 else "complete", {"next": nxt} if nxt else None)
    if st == 2:
        task_event(c, tid, "complete")
    unblock_events(c, completed_ids(c, tid))
    if me():
        push_handled(c, me(), [tid])
    return undo, nxt


def sk_on_move(c, tid, cur, rb=None):
    """apply_update / reorder hook: the task (row before the change: cur) changed its section or list. rb: the caller's
    rul_snap, kept current so that its rul_fire does not start the rules of this completion a second time (do_complete did)."""
    from ..tasks.lifecycle import do_reopen, signed
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t or t["deleted_at"] or t["parent_id"]:
        return
    same = t["list_id"] == cur["list_id"]
    if same and t["section_id"] == cur["section_id"]:
        return
    st = SK_STATUS.get(sk_of(c, t["section_id"]))
    if st is None:
        if same and t["status"] != 0 and sk_of(c, cur["section_id"]) in SK_STATUS:
            do_reopen(c, tid)
        return
    if t["status"] == st:
        return
    undo, nxt = sk_finish(c, tid, st)
    if nxt:  # a recurring task: its completed copy stays in the column, the next occurrence goes back
        c.execute("UPDATE tasks SET section_id=? WHERE id=?", (cur["section_id"] if same else sk_first(c, t["list_id"], "open"), tid))
        if has_request_context():  # the app has nothing else to undo: the task is where it was
            g.sk_moved = {**(g.get("sk_moved") or {}), tid: {"undo": signed(tid, undo), "next_due": nxt}}
    if rb:
        rb["status"] = c.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0]


def sk_answer(ids):
    """The answer's part for tasks a move completed as recurring tasks ({} = none)."""
    m = (g.get("sk_moved") or {}) if has_request_context() else {}
    out = {str(i): m[i] for i in ids if i in m}
    return {"section_moved": out} if out else {}


def sk_filter(ks, where, args):
    """GET /api/v1/tasks ?section_kind= (ks: its values)."""
    if not ks or any(k not in SEC_KINDS for k in ks):
        raise BadInput(tr("Invalid value: {0}", "section_kind"))
    where.append(f"{SK_SQL} IN ({','.join('?' * len(ks))})")
    args += ks
