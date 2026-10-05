"""Approvals as a task type (#463): ask someone to approve a task; they approve, ask for changes or reject it."""
from flask import g, jsonify

from ..core.config import app, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import body, bump, db, err, inbox_default, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, list_people, list_role, MANAGE_ROLES, need_collab, need_task, task_visible
from ..tasks.validation import log_act
from ..tasks.tasks import one_task


# ---------------------------------------------------------------- 2.23.0 (#463): approval as a task type
# A task can wait for an approval: "Ask for approval" picks a person of the list (the approver). The task is then
# assigned to them (the usual assignment push) and shows "Approval pending". Only the approver decides:
#   approve  -> approval 'approved', the task is completed
#   changes  -> approval 'changes', the task goes back to whoever asked (assigned to them), with the note
#   reject   -> approval 'rejected', the task is closed as "won't do"
# The person who asked (and the list's owner / admins) can withdraw a pending request ("cancel"); after changes the task
# can be sent for approval again. Every step is in the task's history (with the note), the person who asked gets a News
# item + push about the decision. Agents may ask for an approval and read the state (API), never approve: an approval is
# a person's decision. Webhooks / agents see it as task.updated with the fields approval / approver_id.
APPROVAL_STATES = ("pending", "approved", "changes", "rejected")
APPROVAL_ACTIONS = ("request", "approve", "changes", "reject", "cancel")
APPROVAL_NOTE_MAX = 2000


def _is_agent(uid, c):
    r = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and r[0] == "agent")


def approval_notify(c, t, state, note, rcpt):
    """News + push to the person who asked for the approval (rcpt) about the decision."""
    from ..collab.news import KIND_ROW, news_add, notif_ok
    from ..collab.comments import burst_gate, collab_user, lang_of, user_names
    from ..notify.push import push_prio, push_reachable
    actor = me()
    if not rcpt or rcpt == actor or _is_agent(rcpt, c):
        return
    s = collab_user(c, rcpt, t["list_id"])
    if not s or not task_visible(c, t["id"], rcpt, full=True):
        return
    news_add(c, rcpt, "apdecide", task_id=t["id"], actor=actor, data={"state": state, "note": note[:300]}, s=s)
    if not notif_ok(c, rcpt, s, KIND_ROW["apdecide"], "push", t["list_id"]) or not push_reachable(c, rcpt, s) or \
            not burst_gate(c, rcpt, t["id"], event=True):
        return
    lg = lang_of(s)
    who = user_names(c, [actor]).get(actor, "?")
    title = {"approved": tr("{0} approved: {1}", who, t["title"], lg=lg), "changes": tr("{0} asks for changes: {1}", who, t["title"], lg=lg),
             "rejected": tr("{0} rejected: {1}", who, t["title"], lg=lg)}[state]
    ln = c.execute("SELECT name, is_inbox FROM lists WHERE id=?", (t["list_id"],)).fetchone()
    lname = tr("Inbox", lg=lg) if ln["is_inbox"] and inbox_default(ln["name"]) else ln["name"]
    g.pushes.append((rcpt, title, (note[:200] + " · " if note else "") + lname, f"{PUBLIC_URL}/#t/{t['id']}", push_prio(s)))


def approval_apply(c, tid, b):
    """The step of body b on task tid (see above); returns the task dict. Denied / BadInput on errors."""
    from ..personal.timetrack import BadInput
    from ..collab.comments import task_event, assignment_events
    from ..tasks.lifecycle import do_complete
    from ..tasks.dependencies import completed_ids, unblock_events
    need_collab()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    act = b.get("action")
    if act not in APPROVAL_ACTIONS:
        raise BadInput(tr("Invalid value: {0}", "action"))
    note = b.get("note") or ""
    if not isinstance(note, str):
        raise BadInput(tr("Invalid value: {0}", "note"))
    note = note.strip()[:APPROVAL_NOTE_MAX]
    uid = me()
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t or t["deleted_at"]:
        raise Denied(404)
    if act == "request":
        need_task(c, tid)  # change the task
        if t["status"] != 0:
            raise BadInput(tr("Only open tasks can wait for an approval"))
        ap = b.get("approver_id")
        if not isinstance(ap, int) or isinstance(ap, bool) or ap not in list_people(c, t["list_id"]) or _is_agent(ap, c):
            raise BadInput(tr("The approver must be a person of this list"))
        if ap == uid:
            raise BadInput(tr("Ask someone else for the approval"))
        if not task_visible(c, tid, ap, full=True):
            raise BadInput(tr("The approver must be a person of this list"))
        old = t["assignee_id"]
        ts = iso(now_utc())
        c.execute("""UPDATE tasks SET approval='pending', approver_id=?, assignee_id=?, assignee_group_id=NULL, assigned_by=?,
                     reminded='[]', updated_at=? WHERE id=?""", (ap, ap, uid, ts, tid))
        log_act(c, tid, "apstate", {"state": "pending", "approver": ap, **({"note": note} if note else {})})
        if old != ap:
            assignment_events(c, tid, old, ap)
        return one_task(c, tid)
    if act == "cancel":
        role = list_role(c, t["list_id"])
        if not t["approval"] or not (t["assigned_by"] == uid or t["created_by"] == uid or role in MANAGE_ROLES):
            raise Denied(403, tr("Only the person who asked or a list admin can withdraw the request"))
        c.execute("UPDATE tasks SET approval='', approver_id=NULL, updated_at=? WHERE id=?", (iso(now_utc()), tid))
        log_act(c, tid, "apstate", {"state": "cancelled"})
        return one_task(c, tid)
    # a decision
    if t["approval"] != "pending":
        raise BadInput(tr("This task does not wait for an approval"))
    if t["approver_id"] != uid:
        raise Denied(403, tr("Only {0} can decide on this approval", _name(c, t["approver_id"])))
    need_task(c, tid, write=False, full=True)
    asker = t["assigned_by"] if t["assigned_by"] and t["assigned_by"] != uid else t["created_by"]
    state = {"approve": "approved", "changes": "changes", "reject": "rejected"}[act]
    ts = iso(now_utc())
    c.execute("UPDATE tasks SET approval=?, updated_at=? WHERE id=?", (state, ts, tid))
    log_act(c, tid, "apstate", {"state": state, **({"note": note} if note else {})})
    if state == "approved":
        do_complete(c, tid, 2)
        log_act(c, tid, "complete")
        task_event(c, tid, "complete")
        unblock_events(c, completed_ids(c, tid))
    elif state == "rejected":
        do_complete(c, tid, -1)
        log_act(c, tid, "wont")
        unblock_events(c, completed_ids(c, tid))
    elif asker and asker in list_people(c, t["list_id"]) and not _is_agent(asker, c):
        c.execute("UPDATE tasks SET assignee_id=?, assigned_by=? WHERE id=?", (asker, uid, tid))
        assignment_events(c, tid, t["assignee_id"], asker)
    approval_notify(c, c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone(), state, note, asker)
    return one_task(c, tid)


def _name(c, uid):
    r = c.execute("SELECT display_name, username FROM users WHERE id=?", (uid,)).fetchone()
    return (r["display_name"] or r["username"]) if r else "?"


@app.post("/api/tasks/<int:tid>/approval")
def task_approval(tid):
    """{action: request, approver_id, note?} | {action: approve | changes | reject, note?} | {action: cancel}. Also
    POST /api/v1/tasks/{id}/approval (agents: request / cancel only)."""
    from ..agents.core import is_agent
    c = db()
    b = body()
    if is_agent(g.user) and b.get("action") in ("approve", "changes", "reject"):
        return err(tr("An approval is a person's decision: agents cannot approve"), 403)
    out = approval_apply(c, tid, b)
    bump(c)
    c.commit()
    return jsonify(out)
