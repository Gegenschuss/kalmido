"""2.392.0 C (#3370): the mark "irreversible" of a task and the task's decisions.

A person or an agent with write access marks a task as a one-way step (tasks.irreversible, with a reason). Where the list has
lists.irreversible_needs_yes on, the integrate / deploy gates (agents/gates.py) stay shut until an approver said yes to that
task (agents/taskdec.py; tasks.irreversible_yes_by / _at). A new reason or a new mark takes the yes back. Only people take a
mark off, and with the switch on only approvers: an agent cannot open its own gate.

task_decisions: the log of a task (text, by_id, created_at); a new entry can supersede an older one, which stays readable.
The text is written by people and agents of the list; a list with the lock takes none (the server would hold it in plain)."""
import os
from flask import g, has_request_context

from ..core.access import Denied, list_role, MANAGE_ROLES, tvis
from ..core.db import iso, iso_ms, now_utc
from ..core.errors import BadInput
from ..core.i18n import tr
from ..core.pg import insert_id
from ..tasks.validation import log_act

IRR_REASON_MAX, IRR_LIST_MAX = 500, 100  # IRR_LIST_MAX: as the deploy checklist
DEC_TEXT_MAX = 4000
DEPLOY_TAG = (os.environ.get("KALMIDO_DEPLOY_TAG") or "deploy").strip() or "deploy"  # also the gates (agents/gates.py)


def irr_view(r):
    """The mark of a task row for the API: {reason, yes_by, yes_at}, None = not marked."""
    if not r["irreversible"]:
        return None
    return {"reason": r["irreversible_reason"] or "", "yes_by": r["irreversible_yes_by"], "yes_at": r["irreversible_yes_at"]}


def irr_needs_yes(c, lid):
    r = c.execute("SELECT irreversible_needs_yes FROM lists WHERE id=?", (lid,)).fetchone()
    return bool(r and r[0])


def irreversible_open(c, lid, uid=None):
    """Open tasks of list lid marked irreversible without a yes: [{id, title, reason}]. With uid: only the tasks uid may see
    (as deploy_checklist)."""
    if uid and not list_role(c, lid, uid):
        return []
    rows = c.execute(f"""SELECT t.id, t.title, t.irreversible_reason FROM tasks t WHERE t.list_id=? AND t.irreversible=1
                         AND t.irreversible_yes_at IS NULL AND t.deleted_at IS NULL AND t.completed_at IS NULL
                         AND {tvis(c, uid, "t.") if uid else "TRUE"} ORDER BY t.id LIMIT ?""", (lid, IRR_LIST_MAX)).fetchall()
    return [{"id": r["id"], "title": r["title"], "reason": r["irreversible_reason"]} for r in rows]


def gate_irreversible(c, t, kind, uid=None):
    """What blocks a request of this kind on task t ([] where the list's switch is off). An integrate request: its own task,
    open or not (completing it must not open the gate)."""
    if not irr_needs_yes(c, t["list_id"]):
        return []
    if kind == "deploy":
        return irreversible_open(c, t["list_id"], uid)
    r = c.execute("SELECT id, title, irreversible, irreversible_reason, irreversible_yes_at FROM tasks WHERE id=?", (t["id"],)).fetchone()
    return [{"id": r["id"], "title": r["title"], "reason": r["irreversible_reason"]}] if r["irreversible"] and not r["irreversible_yes_at"] else []


def irr_guard(c, tid):
    """2.392.0 (#3370 review): an agent cannot make a one-way step that waits for a person's yes go away (complete it, trash it,
    move it out of the list that asks for the yes): that would open its own gate. People stay free, as before."""
    u = g.get("user") if has_request_context() else None
    try:
        if not u or u["kind"] != "agent":
            return
    except (KeyError, IndexError):  # the poll's nobody
        return
    t = c.execute("SELECT list_id, irreversible, irreversible_yes_at FROM tasks WHERE id=?", (tid,)).fetchone()
    if t and t["irreversible"] and not t["irreversible_yes_at"] and irr_needs_yes(c, t["list_id"]):
        raise Denied(409, tr("This one-way step waits for a person's yes"))


def irr_may_clear(c, t):
    """Taking a mark off opens the gate where the list asks for a yes: never an agent, and there only an approver (the rule
    of is_approver with assignee=False, which lives a layer above)."""
    u = g.user
    if u["kind"] == "agent":
        return False
    if not irr_needs_yes(c, t["list_id"]):
        return True
    return list_role(c, t["list_id"], u["id"]) in MANAGE_ROLES or bool(u["is_admin"])


def irr_apply(c, tid, v):
    """{reason} marks the task (or changes the reason), None takes the mark off; the caller checked the write right and
    commits. A new mark or a new reason takes a given yes back; the same reason again changes nothing. A list with the lock
    takes the mark without a text."""
    from ..collab.liste2eguard import le2b_off, le2b_task_locked
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    now = iso(now_utc())
    if v is None:
        if not t["irreversible"]:
            return
        if not irr_may_clear(c, t):
            raise Denied(403, tr("Only the project owner, a project admin or an admin can decide"))
        c.execute("""UPDATE tasks SET irreversible=0, irreversible_reason='', irreversible_yes_by=NULL, irreversible_yes_at=NULL,
                     updated_at=? WHERE id=?""", (now, tid))
        log_act(c, tid, "irreversible", {"on": 0})
        return
    if not isinstance(v, dict) or set(v) - {"reason"} or not isinstance(v.get("reason", ""), str):
        raise BadInput(tr("Invalid value: {0}", "irreversible"))
    reason = v.get("reason", "").strip()
    if len(reason) > IRR_REASON_MAX:
        raise BadInput(tr("Invalid value: {0}", "reason"))
    if reason and le2b_task_locked(c, tid):
        raise Denied(409, le2b_off())
    if t["irreversible"] and reason == (t["irreversible_reason"] or ""):
        return
    c.execute("""UPDATE tasks SET irreversible=1, irreversible_reason=?, irreversible_yes_by=NULL, irreversible_yes_at=NULL,
                 updated_at=? WHERE id=?""", (reason, now, tid))
    log_act(c, tid, "irreversible", {"on": 1, "reason": reason})


def irr_yes(c, tid, uid):
    """An approver's yes to the marked task (the caller checked that and commits)."""
    c.execute("UPDATE tasks SET irreversible_yes_by=?, irreversible_yes_at=?, updated_at=? WHERE id=?", (uid, iso(now_utc()), iso(now_utc()), tid))
    log_act(c, tid, "irreversible_yes", {})


def dec_list(c, tid, current=False):
    """The decisions of a task, oldest first (current: without the superseded ones). The caller checked the sight of it."""
    rows = c.execute(f"""SELECT d.*, u.display_name, u.username, u.kind FROM task_decisions d LEFT JOIN users u ON u.id=d.by_id
                         WHERE d.task_id=? {"AND d.superseded_by IS NULL" if current else ""} ORDER BY d.id""", (tid,)).fetchall()
    return [{"id": r["id"], "task_id": r["task_id"], "text": r["text"], "by_id": r["by_id"], "by": r["display_name"] or r["username"] or "",
             "by_agent": r["kind"] == "agent", "created_at": r["created_at"], "superseded_by": r["superseded_by"]} for r in rows]


def dec_add(c, tid, b, uid):
    """{text, supersedes?}: a new decision, the id of the one it replaces. The caller checked the write right and commits."""
    from ..collab.liste2eguard import le2b_off, le2b_task_locked
    text, old = b.get("text"), b.get("supersedes")
    if set(b) - {"text", "supersedes"} or not isinstance(text, str) or not text.strip() or len(text.strip()) > DEC_TEXT_MAX:
        raise BadInput(tr("Invalid value: {0}", "text"))
    if old is not None and (not isinstance(old, int) or isinstance(old, bool)):
        raise BadInput(tr("Invalid value: {0}", "supersedes"))
    if le2b_task_locked(c, tid):
        raise Denied(409, le2b_off())
    if old is not None and not c.execute("SELECT 1 FROM task_decisions WHERE id=? AND task_id=? AND superseded_by IS NULL", (old, tid)).fetchone():
        raise BadInput(tr("Invalid value: {0}", "supersedes"))
    did = insert_id(c, "INSERT INTO task_decisions(task_id,text,by_id,created_at) VALUES(?,?,?,?)", (tid, text.strip(), uid, iso_ms(now_utc())))
    if old is not None:
        c.execute("UPDATE task_decisions SET superseded_by=? WHERE id=?", (did, old))
    c.execute("UPDATE tasks SET updated_at=? WHERE id=?", (iso(now_utc()), tid))
    log_act(c, tid, "decision", {"id": did})
    return next(d for d in dec_list(c, tid) if d["id"] == did)


def dec_spec(paths, schemas, op, ok, errs, ref, pid):
    """2.392.0 C (#3370) additions to the OpenAPI document."""
    schemas["TaskDecision"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "task_id": {"type": "integer"}, "text": {"type": "string"}, "by_id": {"type": ["integer", "null"]},
        "by": {"type": "string"}, "by_agent": {"type": "boolean"}, "created_at": {"type": "string"},
        "superseded_by": {"type": ["integer", "null"], "description": "the later decision that replaces this one (it stays readable)"}}}
    schemas["TaskDecisionPage"] = {"type": "object", "required": ["data", "next_cursor"], "properties": {
        "data": {"type": "array", "items": ref("TaskDecision")}, "next_cursor": {"type": ["string", "null"]}}}
    paths["/tasks/{id}/decisions"] = {
        "get": op("The decisions of a task, oldest first (who sees its comments sees them; also in GET /tasks/{id})", "Tasks",
                  ok(ref("TaskDecisionPage")) | errs("404"), [pid()]),
        "post": op("Record a decision on a task; `supersedes` = the id of the decision it replaces. 409 in a project encrypted in the "
                   "browser (the text would stay in plain)", "Tasks", ok(ref("TaskDecision"), "Created", "201") | errs("400", "403", "404", "409"),
                   [pid()], scope="tasks:write", body={"type": "object", "required": ["text"], "properties": {
                       "text": {"type": "string", "maxLength": DEC_TEXT_MAX}, "supersedes": {"type": "integer"}}})}
