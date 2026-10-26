"""2.236.0 C (#2906 #2907): the queue of an agent - the open tasks assigned to it that it may see, in the order it set
last (agents.queue_order, a JSON list of task ids), the rest by priority (high first), due date, creation. The first
max_parallel (work style, 0 = no limit) are "active", the others "waiting" with their position 1..n. The priority rule of
the work style goes along wherever the agent chooses its next task (GET /api/v1/agent/queue, the event "assigned").

Kalmido does not start or stop the agent's work: the agent reads the queue and keeps to it; the person sees the same queue
in the agent's settings (GET /api/agents/<aid>/queue, owner of a personal agent / an instance admin for a team agent)."""
import contextlib
import json
from flask import g, has_request_context, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db
from ..core.access import tvis, vis_sql
from ..core.errors import BadInput, UnknownFields
from ..api.common import v1_args, v1_json, v1_view
from ..agents.core import agent_row, lst_brief, need_agent
from ..agents.workstyle import ws_get, ws_need_editor
from ..accounts.session import me

WQ_ORDER_MAX = 500
WQ_PRIO = {0: "none", 1: "low", 3: "medium", 5: "high"}  # the names of api/v1.py PRIO_NAMES


@contextlib.contextmanager
def _wq_as(c, aid):
    """Reads as agent aid for the block (the connection's context hook follows g.user, core/access.py acx_conn_hook): a
    person looking at the agent's queue, or the event of an assignment, sees exactly what the agent sees - never more."""
    prev = g.get("user") if has_request_context() else None
    if not has_request_context() or (prev is not None and prev["id"] == aid):  # a background job: the list filters by aid
        yield c
        return
    g.user = c.execute("SELECT * FROM users WHERE id=?", (aid,)).fetchone()
    try:
        yield c
    finally:
        g.user = prev


def wq_order_of(a):
    """The stored order of agent row a (task ids; [] = none / unreadable)."""
    raw = a["queue_order"] if "queue_order" in a.keys() else ""
    try:
        d = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []
    return [x for x in d if isinstance(x, int) and not isinstance(x, bool)] if isinstance(d, list) else []


def _wq_rows(c, aid):
    """The open tasks assigned to aid that aid may see (the same filters as GET /api/v1/tasks?assignee=me), default order."""
    with _wq_as(c, aid):
        return c.execute(f"""SELECT t.id, t.title, t.list_id, t.priority, t.due FROM tasks t
                             WHERE t.list_id IN {vis_sql()} AND t.deleted_at IS NULL AND {tvis(c, aid, 't.')}
                             AND t.status=0 AND t.assignee_id=?
                             ORDER BY t.priority DESC, t.due IS NULL, t.due, t.id""", (aid, aid, aid)).fetchall()


def wq_build(c, a, ws=None):
    """{max_parallel, priority_rule, items} of agent row a (see the module text)."""
    aid, ws = a["user_id"], ws or ws_get(a)
    rows = _wq_rows(c, aid)
    by_id, order = {r["id"]: r for r in rows}, wq_order_of(a)
    seen, out = set(), []
    for tid in order + [r["id"] for r in rows]:
        if tid in by_id and tid not in seen:
            seen.add(tid)
            out.append(by_id[tid])
    mp, names, items = ws["max_parallel"], {}, []
    for i, r in enumerate(out):
        if r["list_id"] not in names:
            names[r["list_id"]] = lst_brief(c, r["list_id"])["name"]
        active = not mp or i < mp
        items.append({"task_id": r["id"], "title": r["title"], "list_id": r["list_id"], "list_name": names[r["list_id"]],
                      "state": "active" if active else "waiting", "position": None if active else i - mp + 1,
                      "priority": WQ_PRIO.get(r["priority"], "none"), "due": r["due"]})
    return {"max_parallel": mp, "priority_rule": ws["priority_rule"], "items": items}


def wq_event_extra(c, aid, tid):
    """#2906 #2907: what the event "assigned" carries besides the task: its place in the queue and the priority rule."""
    a = agent_row(c, aid)
    if not a:
        return {}
    q = wq_build(c, a)
    it = next((x for x in q["items"] if x["task_id"] == tid), None)
    return {"queue": {"position": it["position"] if it else None, "active": bool(it and it["state"] == "active"),
                      "max_parallel": q["max_parallel"]}, "priority_rule": q["priority_rule"]}


@app.get("/api/v1/agent/queue")
@v1_view
def v1_agent_queue():
    """The agent's own queue: {max_parallel, priority_rule, items: [{task_id, title, list_id, list_name, state, position,
    priority, due}]}."""
    v1_args(())
    aid = need_agent()
    c = db()
    return jsonify(wq_build(c, agent_row(c, aid)))


@app.put("/api/v1/agent/queue")
@v1_view
def v1_agent_queue_set():
    """{order: [task_id, ...]} -- the agent's own order (only its own open visible tasks; at most 500; unknown ids = 400).
    The tasks not named follow in the default order."""
    v1_args(())
    aid = need_agent()
    b = v1_json()
    unknown = sorted(k for k in b if k != "order")
    if unknown:
        raise UnknownFields(unknown)
    order = b.get("order")
    if (not isinstance(order, list) or len(order) > WQ_ORDER_MAX
            or any(isinstance(x, bool) or not isinstance(x, int) for x in order) or len(set(order)) != len(order)):
        raise BadInput(tr("Invalid value: {0}", "order"))
    c = db()
    mine = {r["id"] for r in _wq_rows(c, aid)}
    if any(x not in mine for x in order):
        raise BadInput(tr("Invalid value: {0}", "order"))
    c.execute("UPDATE agents SET queue_order=? WHERE user_id=?", (json.dumps(order), aid))
    c.commit()
    return jsonify(wq_build(c, agent_row(c, aid)))


@app.get("/api/agents/<int:aid>/queue")
def wq_route_get(aid):
    """The queue of agent aid for the person who may set its work style (404 for everyone else)."""
    c = db()
    a = ws_need_editor(c, aid)
    q = wq_build(c, a)
    # 2.236.0 (#2906, tenant boundary): the agent may see tasks of lists the person cannot (shared with the agent only):
    # those keep their place in the queue but carry no title, list or id
    ids = [x["task_id"] for x in q["items"]]
    mine = {r["id"] for r in c.execute(f"""SELECT t.id FROM tasks t WHERE t.id IN ({",".join("?" * len(ids))})
                                            AND t.list_id IN {vis_sql()} AND {tvis(c, me(), 't.')}""",
                                         (*ids, me(), me()))} if ids else set()
    q["items"] = [x if x["task_id"] in mine else {"state": x["state"], "position": x["position"], "hidden": True,
                                                   "task_id": None, "title": None, "list_id": None, "list_name": None,
                                                   "priority": None, "due": None} for x in q["items"]]
    return jsonify(q)


def wq_spec(paths, schemas, op, ok, errs, ref):
    """OpenAPI of the agent's queue (2.236.0 C, #2906 #2907)."""
    AG = "Agents"
    schemas["AgentQueue"] = {"type": "object", "properties": {
        "max_parallel": {"type": "integer", "description": "From your work style: work on at most this many tasks at once (0 = no limit)"},
        "priority_rule": {"type": "string", "description": "From your work style: the owner's rule for choosing the next task, in their words"},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "task_id": {"type": "integer"}, "title": {"type": "string"}, "list_id": {"type": "integer"}, "list_name": {"type": "string"},
            "state": {"type": "string", "enum": ["active", "waiting"], "description": "the first max_parallel are active, the rest waits"},
            "position": {"type": ["integer", "null"], "description": "1.. for the waiting ones, null for the active ones"},
            "priority": {"type": "string", "enum": list(WQ_PRIO.values())}, "due": {"type": ["string", "null"]}}}}}}
    paths["/agent/queue"] = {
        "get": op("2.236.0 (#2906 #2907): your queue - the open tasks assigned to you that you see, in your order (PUT), the rest by "
                  "priority (high first), due date, creation; the first max_parallel are active, the rest waits. Choose the next task "
                  "from it and keep to priority_rule", AG, ok(ref("AgentQueue")) | errs("403")),
        "put": op("2.236.0 (#2906): set the order of your queue (at most 500 of your own open tasks; unknown / foreign ids = 400); the "
                  "tasks not named follow in the default order", AG, ok(ref("AgentQueue")) | errs("400", "403"), scope="write",
                  body={"type": "object", "required": ["order"], "additionalProperties": False, "properties": {
                      "order": {"type": "array", "maxItems": WQ_ORDER_MAX, "items": {"type": "integer"}}}})}
