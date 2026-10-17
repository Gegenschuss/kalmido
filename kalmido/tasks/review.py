"""2.60.0 C (#1512): the review step of a list -- a reviewer per task, "done only after approval", a linked pull request counts."""
import json

from flask import g, has_request_context, jsonify

from ..core.config import app, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, list_people, list_role, MANAGE_ROLES, need_list, need_task, task_visible
from ..tasks.validation import log_act
from ..tasks.tasks import one_task


# ---------------------------------------------------------------- 2.60.0 C (#1512): review step
# Off until a list switches it on (lists.review_cfg = json {on, reviewer, section, gate}; '' = off; editors of the list
# change it). A task gets a reviewer (tasks.reviewer_id: a person or an agent with access to the list) and a state
# (tasks.review: '' | pending | approved | changes; review_at / review_by = the last change, review_by NULL = a pull request).
#   - moving a task into the review section (the section chosen in the setting, else the one named "Review") asks for a
#     review: the default reviewer when it has none, state pending, News + push to the reviewer (notification row "review",
#     switchable like the others) or the agent event review_requested for an agent
#   - the reviewer (or an owner / admin of the list) approves or sends it back ("changes", optional note): back = the section
#     it came from (tasks.review_sec), the assignee is told. The assignee never approves their own task unless a list admin.
#   - gate on: completing (every way: tick, board, API, MCP, git "fixes #id", bulk, repeats) a task with a reviewer whose
#     review is not approved is refused (409 "Waiting for approval by ..."). Without a reviewer completing stays free.
#     While the gate holds, only the reviewer or a list admin changes / removes the reviewer.
#   - a linked pull request counts as the approval when it is merged (git poll) or approved with a thumbs up in Kalmido by
#     someone who may approve the review.
RVW_STATES = ("", "pending", "approved", "changes")
RVW_ACTIONS = ("reviewer", "request", "approve", "changes", "restore")
RVW_NOTE_MAX = 2000


def rvw_cfg(c, lid):
    """The review setting of list lid ({} = off): {on, reviewer, section, gate}."""
    r = c.execute("SELECT review_cfg FROM lists WHERE id=?", (lid,)).fetchone() if lid else None
    try:
        o = json.loads(r[0]) if r and r[0] else {}
    except ValueError:
        o = {}
    if not isinstance(o, dict) or not o.get("on"):
        return {}
    num = lambda v: v if isinstance(v, int) and not isinstance(v, bool) else None  # noqa: E731
    return {"on": True, "reviewer": num(o.get("reviewer")), "section": num(o.get("section")), "gate": bool(o.get("gate"))}


def rvw_section(c, lid, cfg=None):
    """The review section of list lid: the chosen one, else the section named "Review" (None = none)."""
    cfg = rvw_cfg(c, lid) if cfg is None else cfg
    if not cfg:
        return None
    if cfg.get("section"):
        r = c.execute("SELECT id FROM sections WHERE id=? AND list_id=?", (cfg["section"], lid)).fetchone()
        if r:
            return r[0]
    r = c.execute("SELECT id FROM sections WHERE list_id=? AND LOWER(TRIM(name))=? ORDER BY id LIMIT 1", (lid, "review")).fetchone()
    return r[0] if r else None


def _name(c, uid):
    r = c.execute("SELECT display_name, username FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return (r["display_name"] or r["username"]) if r else "?"


def _is_agent(c, uid):
    r = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return bool(r and r[0] == "agent")


def rvw_reviewer_problem(c, lid, rid, tid=None):
    """None if rid may review tasks of list lid (the same choice as an assignee), else the error text."""
    from ..agents.core import agent_row, agent_usable
    from ..agents.safety import ids_parse
    if not isinstance(rid, int) or isinstance(rid, bool) or rid not in list_people(c, lid) or not list_role(c, lid, rid):
        return tr("The reviewer must be someone with access to this list")
    if _is_agent(c, rid):
        a = agent_row(c, rid)
        lorg = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
        if not a or (a["list_ids"] and lid not in ids_parse(a["list_ids"])) or \
                ("org_id" in a.keys() and a["org_id"] and a["org_id"] != lorg):
            return tr("This agent has no access to this list")
        if me() and rid != me() and not agent_usable(c, rid, me(), lid):
            return tr("The list owner has not opened this agent to members")
    if tid and not task_visible(c, tid, rid, full=True):
        return tr("The reviewer must be someone with access to this list")
    return None


def rvw_may(c, t, uid):
    """May uid approve / send back the review of task row t? The reviewer, or (people only) an owner / admin of the list;
    the assignee not their own task unless they are a list admin."""
    if not uid:
        return False
    admin = not _is_agent(c, uid) and list_role(c, t["list_id"], uid) in MANAGE_ROLES
    if uid == t["assignee_id"] and not admin:
        return False
    return uid == t["reviewer_id"] or admin


def _gate_holds(c, t):
    cfg = rvw_cfg(c, t["list_id"])
    return bool(cfg.get("gate")) and bool(t["reviewer_id"]) and t["review"] != "approved"


def rvw_gate(c, tid):
    """Completing task tid (and its open subtasks) is refused while a review gate holds: the error text, else None."""
    from ..tasks.validation import descendants
    for x in [tid, *descendants(c, tid)]:
        t = c.execute("SELECT * FROM tasks WHERE id=?", (x,)).fetchone()
        if t and (x == tid or t["status"] == 0) and _gate_holds(c, t):
            return tr("Waiting for approval by {0}", _name(c, t["reviewer_id"]))
    return None


def _notify(c, t, rcpt, state, note=""):
    """News + push (row "review") to a person; an agent reviewer gets the event review_requested instead."""
    from ..collab.news import news_add, notif_ok
    from ..collab.comments import burst_gate, collab_user, lang_of
    from ..notify.push import push_prio, push_reachable
    actor = me()
    if not rcpt or rcpt == actor:
        return
    if _is_agent(c, rcpt):
        if state == "pending":
            from ..agents.core import agent_emit, agent_task_data
            agent_emit(c, rcpt, "review_requested", agent_task_data(
                c, t["id"], rcpt, review={"state": "pending", "reviewer_id": rcpt, "list_id": t["list_id"],
                                          "url": f"{PUBLIC_URL}/#t/{t['id']}", "by": actor}))
        return
    s = collab_user(c, rcpt, t["list_id"])
    if not s or not task_visible(c, t["id"], rcpt, full=True):
        return
    news_add(c, rcpt, "review", task_id=t["id"], actor=actor, data={"state": state, **({"note": note[:300]} if note else {})}, s=s)
    if not has_request_context() or not notif_ok(c, rcpt, s, "review", "push", t["list_id"]) or not push_reachable(c, rcpt, s) \
            or not burst_gate(c, rcpt, t["id"], event=True):
        return
    lg = lang_of(s)
    who = _name(c, actor)
    title = tr("{0} asks you to review: {1}", who, t["title"], lg=lg) if state == "pending" \
        else tr("{0} sent back: {1}", who, t["title"], lg=lg)
    g.pushes.append((rcpt, title, note[:200], f"{PUBLIC_URL}/#t/{t['id']}", push_prio(s)))


def _set(c, tid, **kv):
    kv["updated_at"] = iso(now_utc())
    c.execute(f"UPDATE tasks SET {','.join(k + '=?' for k in kv)} WHERE id=?", [*kv.values(), tid])
    return c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()


def rvw_request(c, t, rid=None, note=""):
    """Asks for the review of task row t (reviewer rid, else its own, else the list's default). False = no reviewer."""
    cfg = rvw_cfg(c, t["list_id"])
    rid = rid or t["reviewer_id"] or cfg.get("reviewer")
    if not rid or rvw_reviewer_problem(c, t["list_id"], rid, t["id"]):
        return False
    t = _set(c, t["id"], reviewer_id=rid, review="pending", review_at=iso(now_utc()), review_by=me() or None)
    log_act(c, t["id"], "review", {"state": "pending", "reviewer": rid, **({"note": note} if note else {})})
    _notify(c, t, rid, "pending", note)
    return True


def rvw_on_move(c, tid, cur):
    """apply_update hook: the task (row before the change: cur) went into the review section -> review requested. Moved to
    another list: a reviewer without access there is dropped."""
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t:
        return
    if t["list_id"] != cur["list_id"] and t["reviewer_id"] and rvw_reviewer_problem(c, t["list_id"], t["reviewer_id"], tid):
        t = _set(c, tid, reviewer_id=None, review="", review_sec=None)
    sec = rvw_section(c, t["list_id"])
    if not sec or t["status"] != 0 or t["section_id"] != sec or (cur["section_id"] == sec and cur["list_id"] == t["list_id"]):
        return
    c.execute("UPDATE tasks SET review_sec=? WHERE id=?", (cur["section_id"] if cur["list_id"] == t["list_id"] else None, tid))
    if t["review"] != "pending" or t["reviewer_id"] is None:
        rvw_request(c, c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())


def rvw_after_repeat(c, tid):
    """do_complete hook: a repeating task moved on to its next date -- the next occurrence needs its own approval."""
    c.execute("UPDATE tasks SET review='', review_at=NULL, review_by=NULL WHERE id=? AND review<>''", (tid,))


def rvw_approved_by_pr(c, tid, label, url, uid=None):
    """A linked pull request counts as the approval (merged, or 👍 on the agent's merge request by uid). True = changed."""
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t or t["deleted_at"] or t["status"] != 0 or not t["reviewer_id"] or t["review"] == "approved":
        return False
    if not rvw_cfg(c, t["list_id"]):
        return False
    if uid is not None and not rvw_may(c, t, uid):
        return False
    _set(c, tid, review="approved", review_at=iso(now_utc()), review_by=None)
    log_act(c, tid, "review", {"state": "approved", "pr": str(label)[:200], "url": str(url or "")[:500]}, uid=uid)
    return True


def rvw_apply(c, tid, b):
    """One step of body b on task tid (see above); returns the task dict. Denied / BadInput on errors."""
    from ..personal.timetrack import BadInput
    from ..core.access import need_collab
    need_collab()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    act = b.get("action")
    if act not in RVW_ACTIONS:
        raise BadInput(tr("Invalid value: {0}", "action"))
    note = b.get("note") or ""
    if not isinstance(note, str):
        raise BadInput(tr("Invalid value: {0}", "note"))
    note = note.strip()[:RVW_NOTE_MAX]
    uid = me()
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t or t["deleted_at"] or not task_visible(c, tid, uid):
        raise Denied(404)
    cfg = rvw_cfg(c, t["list_id"])
    if act in ("approve", "changes"):
        need_task(c, tid, write=False, full=True)
        if not rvw_may(c, t, uid):
            raise Denied(403, tr("Only the reviewer or a list admin can decide on this review") if uid != t["assignee_id"]
                         else tr("You cannot approve your own task"))
        if t["status"] != 0:  # 2.60.0 review: only an open task is decided on (a done one cannot be sent back)
            raise BadInput(tr("This task does not wait for a review"))
        if act == "approve" and t["review"] not in ("pending", "changes") or act == "changes" and t["review"] not in ("pending", "approved"):
            raise BadInput(tr("This task does not wait for a review"))
        ts = iso(now_utc())
        if act == "approve":
            _set(c, tid, review="approved", review_at=ts, review_by=uid)
        else:
            sec = rvw_section(c, t["list_id"], cfg)
            back = t["review_sec"] if t["review_sec"] and c.execute(
                "SELECT 1 FROM sections WHERE id=? AND list_id=?", (t["review_sec"], t["list_id"])).fetchone() else None
            kv = {"review": "changes", "review_at": ts, "review_by": uid}
            if sec and t["section_id"] == sec and back:
                kv["section_id"] = back
            _set(c, tid, **kv)
        log_act(c, tid, "review", {"state": "approved" if act == "approve" else "changes", **({"note": note} if note else {})})
        if act == "changes":
            t2 = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
            _notify(c, t2, t2["assignee_id"] or t2["created_by"], "changes", note)
        return one_task(c, tid)
    need_task(c, tid)  # change the task
    locked = _gate_holds(c, t) and not rvw_may(c, t, uid)
    if act == "request":
        if t["status"] != 0:
            raise BadInput(tr("Only open tasks can be reviewed"))
        rid = b.get("reviewer_id")
        if rid is not None:
            e = rvw_reviewer_problem(c, t["list_id"], rid, tid)
            if e:
                raise BadInput(e)
            if locked and rid != t["reviewer_id"]:
                raise Denied(403, tr("Only the reviewer or a list admin can change the reviewer"))
        sec = rvw_section(c, t["list_id"], cfg)
        if sec and t["section_id"] != sec and not t["parent_id"]:  # into the review section ("Send for review")
            t = _set(c, tid, review_sec=t["section_id"], section_id=sec)
        if not rvw_request(c, t, rid, note):
            raise BadInput(tr("Choose a reviewer first"))
        return one_task(c, tid)
    rid = b.get("reviewer_id")
    if rid is not None:
        e = rvw_reviewer_problem(c, t["list_id"], rid, tid)
        if e:
            raise BadInput(e)
    if locked and rid != t["reviewer_id"]:
        raise Denied(403, tr("Only the reviewer or a list admin can change the reviewer"))
    if act == "reviewer":
        if rid == t["reviewer_id"]:
            return one_task(c, tid)
        st = "" if rid is None else ("pending" if t["review"] in ("pending", "changes") else "")
        t2 = _set(c, tid, reviewer_id=rid, review=st, review_at=iso(now_utc()) if st else None, review_by=uid if st else None,
                  **({"review_sec": None} if rid is None else {}))
        log_act(c, tid, "review", {"state": "reviewer", "reviewer": rid})
        if st == "pending":
            _notify(c, t2, rid, "pending", note)
        return one_task(c, tid)
    # restore (undo of a step): reviewer + state as they were; approved / changes only for someone who may decide
    st = b.get("review", "")
    if st not in RVW_STATES or (st and rid is None):
        raise BadInput(tr("Invalid value: {0}", "review"))
    if st in ("approved", "changes") and st != t["review"] and not rvw_may(c, {**dict(t), "reviewer_id": rid}, uid):
        raise Denied(403, tr("Only the reviewer or a list admin can decide on this review"))
    sec = b.get("section_id")
    kv = {"reviewer_id": rid, "review": st}
    if st != t["review"]:
        kv.update(review_at=iso(now_utc()) if st else None, review_by=uid if st else None)
    if isinstance(sec, int) and not isinstance(sec, bool) and c.execute(
            "SELECT 1 FROM sections WHERE id=? AND list_id=?", (sec, t["list_id"])).fetchone():
        kv["section_id"] = sec
    _set(c, tid, **kv)
    log_act(c, tid, "review", {"state": st or "reviewer", "reviewer": rid})
    return one_task(c, tid)


@app.post("/api/tasks/<int:tid>/review")
def task_review(tid):
    """{action: reviewer, reviewer_id (null = none)} | {action: request, reviewer_id?, note?} ("Send for review") |
    {action: approve | changes, note?} (the reviewer / a list admin) | {action: restore, reviewer_id, review, section_id?} (undo).
    Also POST /api/v1/tasks/{id}/review (agents decide only as the reviewer)."""
    c = db()
    out = rvw_apply(c, tid, body())
    bump(c)
    c.commit()
    return jsonify(out)


def rvw_cfg_clean(c, lid, b):
    """The stored json of a review setting body {on, reviewer?, section?, gate?} (BadInput on bad values)."""
    from ..personal.timetrack import BadInput
    if not isinstance(b, dict) or any(k not in ("on", "reviewer", "section", "gate") for k in b):
        raise BadInput(tr("Invalid data"))
    if not b.get("on"):
        return ""
    rv, sec = b.get("reviewer"), b.get("section")
    if rv is not None:
        e = rvw_reviewer_problem(c, lid, rv)
        if e:
            raise BadInput(e)
    if sec is not None and (not isinstance(sec, int) or isinstance(sec, bool)
                            or not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (sec, lid)).fetchone()):
        raise BadInput(tr("Invalid value: {0}", "section"))
    return json.dumps({"on": 1, "reviewer": rv, "section": sec, "gate": 1 if b.get("gate") else 0}, separators=(",", ":"))


@app.put("/api/lists/<int:lid>/review")
def list_review_put(lid):
    """The review step of a list (editors): {on, reviewer?: user id, section?: section id (default: the one named Review),
    gate?: done only after approval}. Answers {review_cfg} (the stored json, '' = off)."""
    from ..personal.timetrack import BadInput
    c = db()
    need_list(c, lid)
    try:
        v = rvw_cfg_clean(c, lid, body())
    except BadInput as e:
        return err(str(e))
    c.execute("UPDATE lists SET review_cfg=? WHERE id=?", (v, lid))
    bump(c)
    c.commit()
    return jsonify(review_cfg=v)


# ---- API v1 (+ MCP review_task / set_list_review)
from ..api.v1 import v1_args, v1_call, v1_json, v1_view  # noqa: E402
from ..personal.timetrack import reject_unknown  # noqa: E402


@app.post("/api/v1/tasks/<int:tid>/review")
@v1_view
def v1_task_review(tid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("action", "reviewer_id", "note", "review", "section_id"))
    return jsonify(v1_call(task_review, tid, body=b))


@app.put("/api/v1/lists/<int:lid>/review")
@v1_view
def v1_list_review(lid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("on", "reviewer", "section", "gate"))
    return jsonify(v1_call(list_review_put, lid, body=b))


def rvw_spec(paths, schemas, op, ok, errs, ref, pid, nul):
    tp = schemas["Task"]["properties"]
    tp["reviewer_id"] = nul("integer", description="2.60.0 (#1512): the reviewer (a person or an agent of the list); only when set")
    tp["review"] = {"type": "string", "enum": list(RVW_STATES[1:]), "description": "2.60.0: review state; only when set"}
    tp["review_at"] = nul("string", description="2.60.0: when the review state changed last")
    tp["review_by"] = nul("integer", description="2.60.0: who changed it last (null with review approved = a linked pull request)")
    tp["review_sec"] = nul("integer", description="2.60.0: the section the task came from into review (Back returns it there)")
    if "List" in schemas:
        schemas["List"].setdefault("properties", {})["review_cfg"] = {
            "type": "string", "description": "2.60.0 (#1512): review step, json {on, reviewer, section, gate}; empty = off"}
    paths["/tasks/{id}/review"] = {"post": op(
        "2.60.0 (#1512): the review step. reviewer (reviewer_id, null = none; a person or an agent with access to the list), request "
        "(Send for review: into the list's review section, state pending, the reviewer is told), approve / changes (only the reviewer "
        "or a list admin; never the assignee on their own task; an agent only as the reviewer; changes returns the task to its "
        "previous section), restore (undo: reviewer_id, review, section_id). With the list's gate on, completing a task whose "
        "review is not approved answers 409.", "Tasks", ok(ref("Task")) | errs("400", "403", "404"), [pid()],
        body={"type": "object", "required": ["action"], "additionalProperties": False, "properties": {
            "action": {"type": "string", "enum": list(RVW_ACTIONS)}, "reviewer_id": nul("integer"),
            "note": {"type": "string", "maxLength": RVW_NOTE_MAX}, "review": {"type": "string", "enum": list(RVW_STATES)},
            "section_id": nul("integer")}}, scope="tasks:write")}
    paths["/lists/{id}/review"] = {"put": op(
        "2.60.0 (#1512): the review step of a list (editors). on, reviewer (default reviewer), section (default: the section named "
        "Review), gate (done only after approval). Off = {on: false}.", "Lists",
        ok({"type": "object", "properties": {"review_cfg": {"type": "string", "description": "The stored json, empty = off"}}})
        | errs("400", "403", "404"), [pid("id", "List id")],
        body={"type": "object", "additionalProperties": False, "required": ["on"], "properties": {
            "on": {"type": "boolean"}, "reviewer": nul("integer"), "section": nul("integer"), "gate": {"type": "boolean"}}},
        scope="structure")}
