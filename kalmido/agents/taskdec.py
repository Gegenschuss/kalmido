"""2.392.0 C (#3370): the yes to a task marked irreversible and the routes of a task's decisions (tasks/oneway.py).

The person's route only, for an approver, never an agent: POST /api/tasks/<id>/irreversible-yes. The mark itself: PUT / DELETE
/api/tasks/<id>/irreversible in the app, the field irreversible of PATCH /api/v1/tasks/<id> for the API, MCP and agents.
Decisions: as the comments of the task to read; to write, the right to change it. Agents with access hear `decision_added`."""
from flask import g, jsonify

from ..accounts.session import me
from ..api.common import v1_args, v1_call, v1_json, v1_view
from ..api.v1 import _v1_live
from ..core.access import need_collab, need_task, task_visible
from ..core.config import app
from ..core.db import body, bump, db, err
from ..core.i18n import tr
from ..tasks.lifecycle import need_live
from ..core.errors import BadInput
from ..tasks.oneway import dec_add, dec_list, irr_apply, irr_view, irr_yes
from .core import agent_emit, agent_task_data, is_agent, is_approver, list_agents


def _irr_done(c, tid):
    bump(c)
    c.commit()
    return jsonify(irreversible=irr_view(c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()))


@app.put("/api/tasks/<int:tid>/irreversible")
def irr_put(tid):
    """{reason?}: marks the task as a one-way step (or changes the reason)."""
    c = db()
    need_task(c, tid)
    need_live(c, tid)
    try:
        irr_apply(c, tid, body())
    except BadInput as e:
        return err(str(e))
    return _irr_done(c, tid)


@app.delete("/api/tasks/<int:tid>/irreversible")
def irr_delete(tid):
    c = db()
    need_task(c, tid)
    need_live(c, tid)
    irr_apply(c, tid, None)
    return _irr_done(c, tid)


@app.post("/api/tasks/<int:tid>/irreversible-yes")
def irr_yes_route(tid):
    """An approver's explicit yes, per task and logged. Like a gate's decision: never an agent, not the assignee alone."""
    need_collab()
    c = db()
    need_task(c, tid, write=False, full=True)
    need_live(c, tid)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if is_agent(g.user) or not is_approver(c, t, me(), assignee=False):
        return err(tr("Only the project owner, a project admin or an admin can decide"), 403)
    if not t["irreversible"]:
        return err(tr("This task is not marked as irreversible"), 409)
    if not t["irreversible_yes_at"]:
        irr_yes(c, tid, me())
    return _irr_done(c, tid)


def dec_event(c, tid, d):
    """Agents that see the task with its comments hear the decision; another agent's text is no instruction."""
    lid = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()[0]
    out = {**d, "origin": "agent", "untrusted": True} if d["by_agent"] else d
    for aid in list_agents(c, lid):
        if task_visible(c, tid, aid, full=True):
            agent_emit(c, aid, "decision_added", agent_task_data(c, tid, aid, full=True, decision=out))


@app.get("/api/tasks/<int:tid>/decisions")
def dec_get(tid):
    c = db()
    need_task(c, tid, write=False, full=True)
    return jsonify(decisions=dec_list(c, tid))


@app.post("/api/tasks/<int:tid>/decisions")
def dec_post(tid):
    """{text, supersedes?}"""
    c = db()
    need_task(c, tid, full=True)
    need_live(c, tid)
    try:
        d = dec_add(c, tid, body(), me())
    except BadInput as e:
        return err(str(e))
    dec_event(c, tid, d)
    bump(c)
    c.commit()
    return jsonify(d), 201


@app.get("/api/v1/tasks/<int:tid>/decisions")
@v1_view
def v1_dec_get(tid):
    v1_args(())
    c = db()
    _v1_live(c, tid, write=False, full=True)
    return jsonify(data=dec_list(c, tid), next_cursor=None)


@app.post("/api/v1/tasks/<int:tid>/decisions")
@v1_view
def v1_dec_post(tid):
    """{text, supersedes?} -> the decision."""
    v1_args(())
    return jsonify(v1_call(dec_post, tid, body=v1_json())), 201
