"""2.473.0 (#3357): a second responsibility on a task: "delegated to" one agent, and a list of watchers.

tasks.delegate_agent_id: the agent that does the work while the person stays the assignee. Only an agent of the task's list
that is open to the person (check_delegate, on the server, like check_assignee); it gets the event "assigned" / "unassigned"
with delegated: true, the task counts in its queue (agents/workqueue.py) and it sees the task even as a participant.
task_watchers: everybody who may see a task with its comments can watch it (POST /api/tasks/<id>/watchers); adding or removing
others is for the list's owner / admins. Watchers get comments like someone who commented (notification row "follow") and status
changes like a completion (row "complete"): no new kind of push, both are switched off in Settings > Notifications. Who gets it
is decided when it is sent: a watcher who lost the list or the task hears nothing (collab_user, task_visible), and leaving a
list or a move to a list out of their reach ends the row (dlg_gone, wat_moved). In a list with the lock pushes carry no text."""
from flask import g, has_request_context, jsonify

from ..core.config import app, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, now_utc
from ..core.dlock import dl_list_locked
from ..core.pg import st_ids
from ..core.errors import BadInput, UnknownFields
from ..core.access import Denied, list_people, list_role, MANAGE_ROLES, need_collab, need_task, task_visible
from ..api.common import v1_args, v1_json, v1_view
from ..accounts.session import me
from ..collab.comments import burst_gate, collab_user, lang_of, user_names
from ..collab.news import agent_push_ok, bell_all_users, news_add, notif_ok
from ..notify.push import push_prio, push_reachable
from ..notify.taskbell import _people, TBL_KIND_TXT, tbl_level
from ..tasks.validation import log_act


def _ag(*names):
    """Names of agents.core / agents.safety, loaded after this module (one upward import for the whole file)."""
    from ..agents import core, safety
    return [getattr(core, n) if hasattr(core, n) else getattr(safety, n) for n in names]


WAT_MAX = 200  # watchers of one task
WAT_STATUS = ("complete", "wont", "reopen")  # history lines that reach the watchers


def check_delegate(c, lid, aid):
    """None if agent aid may take over tasks of list lid for the current person, else an error message."""
    if aid is None:
        return None
    need_collab()
    agent_ids, agent_row, agent_usable, ids_parse = _ag("agent_ids", "agent_row", "agent_usable", "ids_parse")
    if aid not in agent_ids(c) or aid not in list_people(c, lid):
        return tr("Only an agent of the project can be delegated to")
    if aid != me() and not agent_usable(c, aid, me(), lid):
        return tr("The project owner has not opened this agent to members")
    a = agent_row(c, aid)
    if dl_list_locked(c, aid, lid) or (a["list_ids"] and lid not in ids_parse(a["list_ids"])):
        return tr("Only an agent of the project can be delegated to")  # its own limits leave this list out: it would hear nothing
    return None


def dlg_events(c, tid, old, new):
    """The agent's events of a changed delegation; an agent that is the assignee as well hears of that one only."""
    if old == new:
        return
    agent_assign_event, = _ag("agent_assign_event")
    who = c.execute("SELECT assignee_id FROM tasks WHERE id=?", (tid,)).fetchone()[0]
    if new and new != who:
        agent_assign_event(c, tid, "assigned", new, delegated=True)
    if old and old != who:
        agent_assign_event(c, tid, "unassigned", old, delegated=True)


def wat_moved(c, ids, lid, people):
    """Tasks ids moved into list lid: the delegation and the watching end for whoever does not reach that list."""
    agent_emit, = _ag("agent_emit")
    for r in c.execute("""SELECT id, delegate_agent_id FROM tasks WHERE id = ANY(CAST(? AS BIGINT[])) AND delegate_agent_id IS NOT NULL
                          AND NOT (delegate_agent_id = ANY(CAST(? AS BIGINT[])))""", (st_ids(ids), st_ids(people))).fetchall():
        c.execute("UPDATE tasks SET delegate_agent_id=NULL WHERE id=?", (r["id"],))
        # only the id: the agent is out of the target list (its ids-only "unassigned" names no list, so nothing of it reaches the agent)
        agent_emit(c, r["delegate_agent_id"], "unassigned", {"task": {"id": r["id"]}, "visible": False, "delegated": True}, actor=None)
    for r in c.execute("SELECT task_id, user_id FROM task_watchers WHERE task_id = ANY(CAST(? AS BIGINT[]))", (st_ids(ids),)).fetchall():
        if r["user_id"] not in people and not list_role(c, lid, r["user_id"]):
            c.execute("DELETE FROM task_watchers WHERE task_id=? AND user_id=?", (r["task_id"], r["user_id"]))


def wat_users(c, tid):
    """Who watches task tid (raw rows: rights are checked when something is sent)."""
    return {r[0] for r in c.execute("SELECT user_id FROM task_watchers WHERE task_id=?", (tid,))}


def wat_note(c, tid, kind, actor):
    """Called by every history line (tasks/validation.py log_act): completed / closed / reopened goes to the watchers, as News
    and as a push of the row "complete". Agents get no event for it (their comments: agent_comment_events)."""
    if kind not in WAT_STATUS or not tid or not c.execute("SELECT 1 FROM task_watchers WHERE task_id=? LIMIT 1", (tid,)).fetchone():
        return
    agent_ids, = _ag("agent_ids")
    from ..collab.liste2e import le2e_mode, le2e_neutral
    t = c.execute("SELECT id, title, list_id, created_by, assigned_by FROM tasks WHERE id=?", (tid,)).fetchone()
    ids = wat_users(c, tid) - agent_ids(c) - {actor, None}
    if kind == "complete":  # they hear of it through task_event
        ids -= {t["created_by"], t["assigned_by"]} | bell_all_users(c, t["list_id"], "complete")
    name = user_names(c, [actor]).get(actor, "?") if actor else None
    lk = le2e_mode(c, t["list_id"])
    for uid in sorted(ids):
        s = collab_user(c, uid, t["list_id"])
        if not s or not task_visible(c, tid, uid, full=True):
            continue
        news_add(c, uid, "complete", task_id=tid, actor=actor if actor is not None else 0, s=s, data=None if kind == "complete" else {"st": kind})
        if tbl_level(c, uid, tid, s, done_ok=kind == "complete"):  # muted: no push; urgent: pushed by tbl_note
            continue
        if not notif_ok(c, uid, s, "complete", "push", t["list_id"]) or not push_reachable(c, uid, s) or \
                not agent_push_ok(c, uid, s, actor) or not burst_gate(c, uid, tid, event=True, kind="complete"):
            continue
        lg = lang_of(s)
        who = name or tr("Someone via the public link", lg=lg)
        g.pushes.append((uid, le2e_neutral(lg) if lk else t["title"], tr(TBL_KIND_TXT[kind], who, lg=lg), f"{PUBLIC_URL}/#t/{tid}", push_prio(s), {"kind": "other"}))


def wat_info(c, tid, role):
    """{watchers: [{id, name}], mine, can_others, people: who an owner / admin can add}."""
    uid, ids = me(), sorted(wat_users(c, tid))
    names = user_names(c, ids)
    out = {"task_id": tid, "watchers": [{"id": u, "name": names.get(u, "?")} for u in ids], "mine": uid in ids,
           "can_others": role in MANAGE_ROLES}
    if role in MANAGE_ROLES:
        ppl = _people(c, tid, c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()[0])
        pn = user_names(c, ppl)
        out["people"] = [{"id": u, "name": pn.get(u, "?")} for u in ppl if u != uid]
    return out


def _wat_target(b):
    b = b if isinstance(b, dict) else {}
    unknown = sorted(k for k in b if k != "user_id")
    if unknown:
        raise UnknownFields(unknown)
    v = b.get("user_id")
    if v is None:
        return me()
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        raise BadInput(tr("Invalid value: {0}", "user_id"))
    return v


def _wat_may_add(c, tid, uid):
    """May the current person (an owner / admin) add uid? Whoever sees the task with its comments; an agent only when it is open to them."""
    agent_ids, agent_usable = _ag("agent_ids", "agent_usable")
    if not task_visible(c, tid, uid, full=True):
        return False
    return uid not in agent_ids(c) or agent_usable(c, uid, me(), c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()[0])


def wat_add(c, tid, uid):
    """The task's list role of the current person after adding uid (itself: anyone who sees the task; others: owner / admins)."""
    need_collab()
    role = need_task(c, tid, write=False, full=True)
    if c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()[0]:
        raise Denied(409, tr("The task is in the trash"))
    if uid != me():
        if role not in MANAGE_ROLES:
            raise Denied(403)
        if not _wat_may_add(c, tid, uid):  # not in this list / does not see the task: one answer for all
            raise Denied(404, tr("unknown person"))
    if uid in wat_users(c, tid):
        return role
    if len(wat_users(c, tid)) >= WAT_MAX:
        raise BadInput(tr("Too many watchers"))
    c.execute("INSERT INTO task_watchers(task_id,user_id,created_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (tid, uid, iso(now_utc())))
    log_act(c, tid, "watch", {"on": 1, **({"to": uid} if uid != me() else {})})
    bump(c)
    c.commit()
    return role


def wat_remove(c, tid, uid):
    """The role after taking uid off the task (oneself always, others: owner / admins)."""
    need_collab()
    role = need_task(c, tid, write=False, full=True)
    if uid != me() and role not in MANAGE_ROLES:
        raise Denied(403)
    if c.execute("DELETE FROM task_watchers WHERE task_id=? AND user_id=?", (tid, uid)).rowcount:
        log_act(c, tid, "watch", {"on": 0, **({"to": uid} if uid != me() else {})})
        bump(c)
        c.commit()
    return role


@app.get("/api/tasks/<int:tid>/watchers")
def wat_get(tid):
    c = db()
    return jsonify(wat_info(c, tid, need_task(c, tid, write=False, full=True)))


@app.post("/api/tasks/<int:tid>/watchers")
def wat_post(tid):
    """{user_id?}: me without it; somebody else: the list's owner / admins."""
    c = db()
    return jsonify(wat_info(c, tid, wat_add(c, tid, _wat_target(body()))))


@app.delete("/api/tasks/<int:tid>/watchers/<int:uid>")
def wat_delete(tid, uid):
    c = db()
    return jsonify(wat_info(c, tid, wat_remove(c, tid, uid)))


@app.get("/api/v1/tasks/<int:tid>/watchers")
@v1_view
def v1_wat_get(tid):
    """{task_id, watchers: [{id, name}], mine, can_others, people}."""
    v1_args(())
    c = db()
    return jsonify(wat_info(c, tid, need_task(c, tid, write=False, full=True)))


@app.post("/api/v1/tasks/<int:tid>/watchers")
@v1_view
def v1_wat_add(tid):
    """{user_id?}: you without it; somebody else: the project's owner / admins."""
    v1_args(())
    c = db()
    return jsonify(wat_info(c, tid, wat_add(c, tid, _wat_target(v1_json()))))


@app.delete("/api/v1/tasks/<int:tid>/watchers/<int:uid>")
@v1_view
def v1_wat_delete(tid, uid):
    v1_args(())
    c = db()
    return jsonify(wat_info(c, tid, wat_remove(c, tid, uid)))


def wat_spec(paths, schemas, op, ok, errs, ref, pid):
    """OpenAPI of the watchers of a task."""
    T = "Tasks"
    person = {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}}
    schemas["TaskWatchers"] = {"type": "object", "properties": {
        "task_id": {"type": "integer"}, "watchers": {"type": "array", "items": person}, "mine": {"type": "boolean", "description": "You watch the task"},
        "can_others": {"type": "boolean", "description": "You may add and remove others (owner / admins of the project)"},
        "people": {"type": "array", "items": person, "description": "Only with can_others: who you can add"}}}
    uid = {"name": "user_id", "in": "path", "required": True, "schema": {"type": "integer"}, "description": "Who stops watching"}
    paths["/tasks/{id}/watchers"] = {
        "get": op("2.473.0: who watches the task", T, ok(ref("TaskWatchers")) | errs("404"), [pid()]),
        "post": op("2.473.0: watch the task (yourself; somebody else: owner / admins of the project)", T, ok(ref("TaskWatchers")) | errs("400", "403", "404", "409"),
                   [pid()], scope="write", body={"type": "object", "additionalProperties": False, "properties": {"user_id": {"type": "integer"}}},
                   desc="Watchers get the task's comments and status changes; whoever can no longer see the task hears nothing.")}
    paths["/tasks/{id}/watchers/{user_id}"] = {
        "delete": op("2.473.0: stop watching (yourself; somebody else: owner / admins of the project)", T, ok(ref("TaskWatchers")) | errs("403", "404"),
                     [pid(), uid], scope="write")}
