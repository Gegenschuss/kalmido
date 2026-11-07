"""2.236.0 C (#2906 #2907): the queue of an agent - the open tasks assigned or delegated to it that it may see, in the order it set
last (agents.queue_order, a JSON list of task ids), the rest by priority (high first), due date, creation. The first
max_parallel (work style, 0 = no limit) are "active", the others "waiting" with their position 1..n. The priority rule of
the work style goes along wherever the agent chooses its next task (GET /api/v1/agent/queue, the event "assigned").

Kalmido does not start or stop the agent's work: the agent reads the queue and keeps to it. 2.392.0 A (#3367): with
max_parallel > 0 the limit is hard for new running jobs (POST /api/v1/agent/jobs: 409 slots_full, agents/api.py); the person sees the same queue
in the agent's settings (GET /api/agents/<aid>/queue, owner of a personal agent / an instance admin for a team agent).

2.624.0 (#4521): every item carries its size (the selection field Size of a software project, its options s / m / l, any
language and name: lists/templates.py PTYPE_FIELD_OPTS) and its points S=1, M=2, L=3; a task without a size counts as M (2).
GET /api/v1/agent/queue?points=N marks the next bundle: the first items in queue order whose points together stay within N
(bundle: true on them, {points, sum, count} in "bundle"); a first item above N alone is the bundle, so the queue never stalls."""
import contextlib
import json
import re
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
WQ_PRIO = {0: "none", 1: "low", 3: "medium", 5: "high", 7: "urgent"}  # the names of api/v1.py PRIO_NAMES
WQ_SIZE_POINTS = {"s": 1, "m": 2, "l": 3}  # 2.624.0 (#4521): the options of the field Size (lists/templates.py PTYPE_FIELD_OPTS)
WQ_SIZE_NONE = 2  # a task without a size counts as M
WQ_POINTS_MAX = 10000


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
    """The open tasks assigned to aid that aid may see (the same filters as GET /api/v1/tasks?assignee=me), default order.
    2.473.0 (#3357): + the tasks delegated to it (delegate=me)."""
    with _wq_as(c, aid):
        return c.execute(f"""SELECT t.id, t.title, t.list_id, t.priority, t.due FROM tasks t
                             WHERE t.list_id IN {vis_sql()} AND t.deleted_at IS NULL AND {tvis(c, aid, 't.')}
                             AND t.status=0 AND (t.assignee_id=? OR t.delegate_agent_id=?)
                             ORDER BY t.priority DESC, t.due IS NULL, t.due, t.id""", (aid, aid, aid, aid)).fetchall()


def _wq_sizes(c, tids):
    """2.624.0 (#4521): task id -> "s" | "m" | "l" from the Size field of the task's current list: a selection field whose
    options hold the ids s, m and l (the first such field by its place, when a list has more). Tasks without a value are missing."""
    if not tids:
        return {}
    out = {}
    for r in c.execute(f"""SELECT v.task_id, v.value, f.options FROM task_field_values v JOIN list_fields f ON f.id=v.field_id
                           JOIN tasks t ON t.id=v.task_id AND t.list_id=f.list_id
                           WHERE v.task_id IN ({",".join("?" * len(tids))}) AND f.type='select' ORDER BY f.sort, f.id""", tids):
        if r["task_id"] in out or r["value"] not in WQ_SIZE_POINTS:
            continue
        try:
            opts = json.loads(r["options"] or "{}").get("options") or []
        except (ValueError, TypeError, AttributeError):
            continue
        if set(WQ_SIZE_POINTS) <= {o.get("id") for o in opts if isinstance(o, dict)}:
            out[r["task_id"]] = r["value"]
    return out


def wq_points_arg(raw):
    """2.624.0 (#4521): the parameter points of GET /api/v1/agent/queue: None when absent, else a whole number 1..10000 (400)."""
    if raw is None:
        return None
    if not re.fullmatch(r"[1-9][0-9]{0,4}", raw.strip()) or int(raw) > WQ_POINTS_MAX:
        raise BadInput(tr("Invalid value: {0}", "points") + f" (1-{WQ_POINTS_MAX})")
    return int(raw)


def wq_bundle(q, points):
    """2.624.0 (#4521): marks the next bundle of queue q in place (see the module text)."""
    total = n = 0
    for it in q["items"]:
        if n and total + it["points"] > points:
            break
        total, n = total + it["points"], n + 1
    for i, it in enumerate(q["items"]):
        it["bundle"] = i < n
    q["bundle"] = {"points": points, "sum": total, "count": n}
    return q


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
    sizes = _wq_sizes(c, [r["id"] for r in out])
    for i, r in enumerate(out):
        if r["list_id"] not in names:
            names[r["list_id"]] = lst_brief(c, r["list_id"])["name"]
        active = not mp or i < mp
        items.append({"task_id": r["id"], "title": r["title"], "list_id": r["list_id"], "list_name": names[r["list_id"]],
                      "state": "active" if active else "waiting", "position": None if active else i - mp + 1,
                      "priority": WQ_PRIO.get(r["priority"], "none"), "due": r["due"],
                      "size": sizes[r["id"]].upper() if r["id"] in sizes else None,
                      "points": WQ_SIZE_POINTS.get(sizes.get(r["id"]), WQ_SIZE_NONE)})
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
    priority, due, size, points}]}; 2.624.0 (#4521): ?points=N + bundle {points, sum, count} and bundle: true / false per item."""
    pts = wq_points_arg(v1_args(("points",)).get("points"))
    aid = need_agent()
    c = db()
    q = wq_build(c, agent_row(c, aid))
    return jsonify(wq_bundle(q, pts) if pts else q)


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
                                                   "priority": None, "due": None, "size": None, "points": None} for x in q["items"]]
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
            "priority": {"type": "string", "enum": list(WQ_PRIO.values())}, "due": {"type": ["string", "null"]},
            "size": {"type": ["string", "null"], "enum": ["S", "M", "L", None], "description": "2.624.0 (#4521): the field Size of a software project, null = none"},
            "points": {"type": "integer", "description": "2.624.0 (#4521): S=1, M=2, L=3; without a size 2"},
            "bundle": {"type": "boolean", "description": "2.624.0 (#4521): only with ?points=N: part of the next bundle"}}}},
        "bundle": {"type": "object", "description": "2.624.0 (#4521): only with ?points=N: the next bundle", "properties": {
            "points": {"type": "integer", "description": "N as asked"}, "sum": {"type": "integer", "description": "the points of the bundle"},
            "count": {"type": "integer", "description": "the first count items form the bundle"}}}}}
    paths["/agent/queue"] = {
        "get": op("2.236.0 (#2906 #2907): your queue - the open tasks assigned to you that you see, in your order (PUT), the rest by "
                  "priority (high first), due date, creation; the first max_parallel are active, the rest waits. Choose the next task "
                  "from it and keep to priority_rule. 2.624.0 (#4521): points=N marks the next bundle - the first items whose points "
                  "(size S=1, M=2, L=3, none = 2) stay within N; a first item above N alone", AG, ok(ref("AgentQueue")) | errs("400", "403"),
                  params=[{"name": "points", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 1, "maximum": WQ_POINTS_MAX},
                           "description": "mark the next bundle of at most N points"}]),
        "put": op("2.236.0 (#2906): set the order of your queue (at most 500 of your own open tasks; unknown / foreign ids = 400); the "
                  "tasks not named follow in the default order", AG, ok(ref("AgentQueue")) | errs("400", "403"), scope="write",
                  body={"type": "object", "required": ["order"], "additionalProperties": False, "properties": {
                      "order": {"type": "array", "maxItems": WQ_ORDER_MAX, "items": {"type": "integer"}}}})}
