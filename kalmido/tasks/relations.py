"""2.576.0 (#3371): saved relations between tasks -- "relates to" and "duplicate of" (decision 28.10.2026; first drafted in
2.393.0 A on the branch that did not land, rebuilt on today's main).

task_relations(task_id, other_id, kind): 'relates' is one row per pair (task_id < other_id) and shows on both tasks; 'duplicate'
is directed: task_id is a duplicate of other_id (the other task shows "has duplicate"). A pair has one relation: a duplicate
replaces a 'relates' of the same pair, a 'relates' next to a duplicate changes nothing. Adding or removing needs write access to
the task it is done from and the other task must be visible to the person (404 otherwise, like dependencies); at most REL_MAX
relations per task. Only relations whose other task the reader sees are shown, on either side (the task object's `relations`,
GET .../relations, API v1, MCP); tasks in the trash drop out while they are there; an agent never sees one to a task its data
lock covers (core/serializers.rel_of).
"Duplicate of" does not close by itself: close=true (the app's "Close as duplicate") marks the task as won't do with a comment
"Duplicate of #X" and answers a signed undo (tasks/lifecycle.py undo_status): the undo opens the task again and removes the
relation and the comment. The computed similar tasks (tasks/related.py) stay a suggestion apart; they say which of them is
saved already (saved = the kind).
"""
from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, iso_ms, now_utc
from ..core.pg import insert_id
from ..core.objcomments import ocm_add  # 2.972.0 (#5272)
from ..core.errors import BadInput, reject_unknown
from ..core.access import Denied, need_task, task_visible
from ..core.serializers import rel_of
from ..api.common import v1_args, v1_json, v1_view
from ..accounts.session import me
from ..collab.liste2e import le2e_task_mode
from ..personal.timetrack import vis_ids
from ..tasks.validation import log_act
from ..tasks.tasks import one_task
from ..tasks.lifecycle import complete_stale, do_complete, need_live, signed
from ..tasks.dependencies import completed_ids, unblock_events

REL_MAX = 50  # relations of one task (both directions)
REL_KINDS = ("relates", "duplicate")


def rel_list(c, tid):
    """The relations of task tid the current person sees, with the other task's title / status / list (detail panel, API)."""
    rows = rel_of(c, {tid}, lambda: vis_ids(c, me()), me()).get(tid, [])
    if not rows:
        return []
    q = ",".join("?" * len(rows))
    info = {r["id"]: r for r in c.execute(f"SELECT id, title, status, list_id FROM tasks WHERE id IN ({q})", [x["id"] for x in rows])}
    return [{**x, "title": info[x["id"]]["title"], "status": info[x["id"]]["status"], "list_id": info[x["id"]]["list_id"]}
            for x in rows if x["id"] in info and task_visible(c, x["id"], me())]


def rel_info(c, tid):
    return {"task_id": tid, "relations": rel_list(c, tid), "max": REL_MAX}


def _ids(b):
    b = b if isinstance(b, dict) else {}
    o = b.get("other_id")
    if isinstance(o, bool) or not isinstance(o, (int, str)):
        raise BadInput(tr("Invalid data"))
    try:
        other = int(o)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid data")) from None
    if not 0 < other < 2 ** 63:
        raise BadInput(tr("Invalid data"))
    kind = b.get("kind") or "relates"
    if kind not in REL_KINDS:
        raise BadInput(tr("Invalid data"))
    if "close" in b and not isinstance(b["close"], bool):
        raise BadInput(tr("Invalid data"))
    return other, kind


def _title(c, tid):
    return (c.execute("SELECT title FROM tasks WHERE id=?", (tid,)).fetchone()[0] or "")[:200]


def rel_add(c, tid, b):
    """{other_id, kind relates|duplicate, close?}: tid relates to / is a duplicate of other_id. Returns (info, undo or None)."""
    other, kind = _ids(b)
    need_task(c, tid)                    # the task it is done from changes: write access
    need_task(c, other, write=False)     # the other task must be visible (404 otherwise: nothing about it leaks)
    if tid == other:
        raise BadInput(tr("A task cannot be related to itself"))
    need_live(c, tid)
    need_live(c, other)
    a, z = (min(tid, other), max(tid, other)) if kind == "relates" else (tid, other)
    have = {(r["task_id"], r["kind"]): r["id"] for r in c.execute(
        "SELECT id, task_id, kind FROM task_relations WHERE (task_id=? AND other_id=?) OR (task_id=? AND other_id=?)", (tid, other, other, tid))}
    if kind == "duplicate" and (other, "duplicate") in have:
        raise BadInput(tr("The other task is already marked as a duplicate of this one"))
    rid = have.get((a, kind))
    added = False
    if rid is None and not (kind == "relates" and any(k == "duplicate" for _, k in have)):
        for t in (tid, other):  # 2.576.0 (fable review): both tasks, so a task one may only read is not hung with endless ones
            n = c.execute("SELECT COUNT(*) FROM task_relations WHERE task_id=? OR other_id=?", (t, t)).fetchone()[0]
            if n >= REL_MAX:
                raise BadInput(tr("At most {0} relations per task", REL_MAX))
        c.execute("DELETE FROM task_relations WHERE kind='relates' AND task_id=? AND other_id=?", (min(tid, other), max(tid, other)))
        rid = insert_id(c, "INSERT INTO task_relations(task_id,other_id,kind,created_by,created_at) VALUES(?,?,?,?,?) "
                           "ON CONFLICT DO NOTHING", (a, z, kind, me(), iso_ms(now_utc())))
        added = bool(rid)
        if added:
            k = "relates" if kind == "relates" else "duplicate_of"
            log_act(c, tid, "rel_add", {"id": other, "title": _title(c, other), "k": k})
            if task_visible(c, other, me(), write=True):  # a history line in the other task only with write access to it (as dependencies)
                log_act(c, other, "rel_add", {"id": tid, "title": _title(c, tid), "k": "relates" if kind == "relates" else "has_duplicate"})
    undo = None
    t = c.execute("SELECT status, repeat, due FROM tasks WHERE id=?", (tid,)).fetchone()
    if kind == "duplicate" and isinstance(b, dict) and b.get("close") is True and rid and t["status"] == 0 and \
            not (t["repeat"] and complete_stale(c, tid, t["due"])):  # 2.576.0 (fable review): as the status route
        undo = rel_close_dup(c, tid, other, rid if added else None)
    bump(c)
    c.commit()
    return rel_info(c, tid), undo


def rel_close_dup(c, tid, other, rid):
    """Closes tid as won't do, a duplicate of other (a comment says so, outside a list with the lock): the signed undo record.
    rid = the relation this request added (the undo removes it), None when it was there before (it stays).
    2.576.0 (fable review): the same steps as the status route for "won't do" (its notification closed on my other devices;
    no task event, the route sends none for won't do either; a recurring task ticked meanwhile elsewhere is left alone, rel_add)."""
    from ..notify.push import push_handled
    undo = {}
    do_complete(c, tid, -1, undo)
    log_act(c, tid, "wont")
    unblock_events(c, completed_ids(c, tid))
    push_handled(c, me(), [tid])
    cid = None
    if not le2e_task_mode(c, tid):  # a project encrypted in the browser: no plain text from the server
        cid = ocm_add(c, "task", tid, me(), tr("Duplicate of #{0}", other))  # 2.972.0 (#5272): the core's comment
    undo["dup"] = {"other": other, "rel": rid, "cm": cid}
    return signed(tid, undo)


def rel_remove(c, tid, other, kind=None):
    """Removes the relation between tid and other (kind None: any kind). Write access to tid, other visible."""
    need_task(c, tid)
    if not task_visible(c, other, me()):
        raise Denied(404)
    if kind and kind not in REL_KINDS:
        raise BadInput(tr("Invalid data"))
    kinds = (kind,) if kind else REL_KINDS
    q = ",".join("?" * len(kinds))
    gone = c.execute(f"""DELETE FROM task_relations WHERE ((task_id=? AND other_id=?) OR (task_id=? AND other_id=?)) AND kind IN ({q})""",
                     (tid, other, other, tid, *kinds)).rowcount
    if not gone:
        raise Denied(404)
    log_act(c, tid, "rel_rm", {"id": other, "title": _title(c, other)})
    if task_visible(c, other, me(), write=True):
        log_act(c, other, "rel_rm", {"id": tid, "title": _title(c, tid)})
    bump(c)
    c.commit()
    return rel_info(c, tid)


# ---- the app ----------------------------------------------------------------------------------------------------------------
@app.get("/api/tasks/<int:tid>/relations")
def rel_get(tid):
    c = db()
    need_task(c, tid, write=False, full=True)
    return jsonify(rel_info(c, tid))


@app.post("/api/tasks/<int:tid>/relations")
def rel_post(tid):
    """{other_id, kind?, close?} -> {task_id, relations, max, task, undo?}."""
    c = db()
    info, undo = rel_add(c, tid, body())
    return jsonify({**info, "task": one_task(c, tid), **({"undo": undo} if undo else {})})


@app.delete("/api/tasks/<int:tid>/relations/<int:other>")
def rel_delete(tid, other):
    c = db()
    info = rel_remove(c, tid, other)
    return jsonify({**info, "task": one_task(c, tid)})


# ---- API v1 -----------------------------------------------------------------------------------------------------------------
@app.get("/api/v1/tasks/<int:tid>/relations")
@v1_view
def v1_rel_get(tid):
    """{task_id, relations: [{id, kind, title, status, list_id}], max}: only relations whose other task you see."""
    v1_args(())
    c = db()
    need_task(c, tid, write=False, full=True)
    return jsonify(rel_info(c, tid))


@app.post("/api/v1/tasks/<int:tid>/relations")
@v1_view
def v1_rel_add(tid):
    """{other_id, kind: relates | duplicate, close?}: duplicate = this task is a duplicate of other_id; close = also mark it won't do."""
    v1_args(())
    c = db()
    b = v1_json()
    reject_unknown(b, ("other_id", "kind", "close"))
    info, undo = rel_add(c, tid, b)
    return jsonify({**info, "closed": bool(undo)})


@app.delete("/api/v1/tasks/<int:tid>/relations/<int:other>")
@v1_view
def v1_rel_delete(tid, other):
    v1_args(())
    c = db()
    return jsonify(rel_remove(c, tid, other))


def rel_spec(paths, schemas, op, ok, errs, ref, pid):
    """OpenAPI of the saved relations of a task."""
    T = "Tasks"
    schemas["TaskRelation"] = {"type": "object", "properties": {
        "id": {"type": "integer", "description": "The other task"},
        "kind": {"type": "string", "enum": ["relates", "duplicate_of", "has_duplicate"],
                 "description": "relates: related both ways; duplicate_of: this task is a duplicate of the other; has_duplicate: the other is a duplicate of this one"},
        "title": {"type": "string"}, "status": {"type": "integer"}, "list_id": {"type": "integer"}}}
    schemas["TaskRelations"] = {"type": "object", "properties": {
        "task_id": {"type": "integer"}, "relations": {"type": "array", "items": ref("TaskRelation"),
                                                      "description": "Only relations whose other task you may see"},
        "max": {"type": "integer", "description": "At most this many relations per task"},
        "closed": {"type": "boolean", "description": "POST only: the task was closed as a duplicate (close: true)"}}}
    other = {"name": "other_id", "in": "path", "required": True, "schema": {"type": "integer"}, "description": "The other task"}
    paths["/tasks/{id}/relations"] = {
        "get": op("2.576.0: saved relations of the task (relates to, duplicate of)", T, ok(ref("TaskRelations")) | errs("404"), [pid()]),
        "post": op("2.576.0: relate the task to another one or mark it as a duplicate", T,
                   ok(ref("TaskRelations")) | errs("400", "403", "404", "409"),
                   [pid()], scope="write", body={"type": "object", "additionalProperties": False, "required": ["other_id"], "properties": {
                       "other_id": {"type": "integer", "description": "A task you may see"},
                       "kind": {"type": "string", "enum": ["relates", "duplicate"], "description": "duplicate: this task is a duplicate of other_id (default relates)"},
                       "close": {"type": "boolean", "description": "duplicate only: also mark this task won't do with a comment pointing at other_id"}}},
                   desc="Needs write access to this task; the other task must be visible to you (404 otherwise). At most 50 relations "
                        "per task. A duplicate replaces a 'relates' of the same pair. Computed similar tasks: GET /tasks/{id}/related.")}
    paths["/tasks/{id}/relations/{other_id}"] = {
        "delete": op("2.576.0: remove the relation to another task", T, ok(ref("TaskRelations")) | errs("403", "404"), [pid(), other], scope="write")}
