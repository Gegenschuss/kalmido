"""2.51.0 (#1352): agents on the pin board of a project page + the weekly status of a project.

An agent may read the notepads of a project list shared with it and write its OWN notepads there (list_notepads.agent_id;
scope "pinboard", off for new agents, the admin / the person turns it on per agent): create, change and remove only what
it wrote itself; the notepads of people stay theirs (403). People see an agent's notepad marked ("from <agent>, updated
...") and may edit or delete it as usual. One notepad per agent and list is its status block (agent_key 'status', PUT
.../status-pad: upsert, the agent overwrites only its own). GET .../weekly-status hands the agent the finished numbers of
a project (done in the last days, blocked, waiting on external, overdue, who waits on whom) so that it only has to write
the words -- Kalmido never runs a model itself. Weekly: a planned job of the agent (agents/schedules.py) with the recipe
"Weekly status" (docs/AGENTS.md); no timer of its own. Every route checks the list like the web app (need_overview: the
token's list limit, the agent's organisation, health lists never) and the list's write access for writing."""
from datetime import date, timedelta

from flask import g, jsonify

from ..core.config import app
from ..core.pg import insert_id
from ..core.i18n import tr
from ..core.db import bump, db, iso, local_now, now_utc
from ..core.access import Denied, tvis
from ..personal.timetrack import BadInput
from ..api.v1 import v1_args, v1_json, v1_view
from ..agents.core import is_agent
from ..accounts.layouts import WG_PADS_MAX, _wg_pad_text
from ..collab.comments import user_names

APIN_KEYS = ("status",)       # agent_key values: one block per agent + list and key
APIN_DAYS, APIN_DAYS_MAX = 7, 31
APIN_ITEMS = 50               # tasks per group in the weekly status


def apin_dict(r, names=None):
    names = names or {}
    return {"id": r["id"], "list_id": r["list_id"], "title": r["title"], "body": r["body"], "updated_at": r["updated_at"],
            "updated_by": r["updated_by"], "agent_id": r["agent_id"], "agent_key": r["agent_key"] or None,
            "agent_name": names.get(r["agent_id"]) if r["agent_id"] else None,
            "mine": bool(r["agent_id"]) and r["agent_id"] == g.user["id"]}


def _apin_list(c, lid, write):
    """The project list lid as the token sees it (404 / 403 / 409 like the web app) -- never a health list."""
    from ..lists.projects import need_overview
    if g.user["kid"]:
        raise Denied(403)
    r = c.execute("SELECT life, archived FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or r["life"] == "health":
        raise Denied(404)
    role = need_overview(c, lid, write=write)
    if write and r["archived"]:
        raise Denied(409, tr("This list is archived"))
    return role


def _apin_pad(c, pid):
    """A notepad the token may change: its list writable for the token's user; an agent only its own notepads."""
    r = c.execute("SELECT * FROM list_notepads WHERE id=?", (pid,)).fetchone()
    if not r:
        raise Denied(404)
    _apin_list(c, r["list_id"], True)
    if is_agent(g.user) and r["agent_id"] != g.user["id"]:
        raise Denied(403, tr("An agent may change only its own notepads"))
    return r


def _apin_out(c, rows):
    names = user_names(c, [r["agent_id"] for r in rows if r["agent_id"]])
    return [apin_dict(r, names) for r in rows]


def _apin_create(c, lid, v, key=""):
    if c.execute("SELECT COUNT(*) FROM list_notepads WHERE list_id=?", (lid,)).fetchone()[0] >= WG_PADS_MAX:
        raise Denied(409, tr("At most {0} notepads", WG_PADS_MAX))
    ts, uid = iso(now_utc()), g.user["id"]
    return insert_id(c, "INSERT INTO list_notepads(list_id,title,body,created_by,created_at,updated_by,updated_at,agent_id,agent_key) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                     (lid, v["title"], v["body"], uid, ts, uid, ts, uid if is_agent(g.user) else None, key))


@app.get("/api/v1/lists/<int:lid>/notepads")
@v1_view
def v1_apin_list(lid):
    """The notepads of a project page (everyone who sees the page; agent_id marks those an agent wrote, mine = yours)."""
    v1_args(())
    c = db()
    _apin_list(c, lid, False)
    return jsonify(data=_apin_out(c, c.execute("SELECT * FROM list_notepads WHERE list_id=? ORDER BY id", (lid,)).fetchall()))


@app.post("/api/v1/lists/<int:lid>/notepads")
@v1_view
def v1_apin_create(lid):
    """{title?, body?}: a new notepad (Markdown) on the project page; written by an agent it stays marked as its own."""
    v1_args(())
    b = v1_json()
    if set(b) - {"title", "body"}:
        raise BadInput(tr("Invalid notepad"))
    v = _wg_pad_text(b, False)
    c = db()
    _apin_list(c, lid, True)
    pid = _apin_create(c, lid, v)
    bump(c)
    c.commit()
    return jsonify(_apin_out(c, [c.execute("SELECT * FROM list_notepads WHERE id=?", (pid,)).fetchone()])[0]), 201


@app.patch("/api/v1/notepads/<int:pid>")
@v1_view
def v1_apin_patch(pid):
    """{title?, body?}: change a notepad -- an agent only its own."""
    v1_args(())
    b = v1_json()
    if set(b) - {"title", "body"}:
        raise BadInput(tr("Invalid notepad"))
    v = _wg_pad_text(b, True)
    c = db()
    _apin_pad(c, pid)
    if v:
        sets = ", ".join(f"{k}=?" for k in v)
        c.execute(f"UPDATE list_notepads SET {sets}, updated_by=?, updated_at=? WHERE id=?", (*v.values(), g.user["id"], iso(now_utc()), pid))
        bump(c)
        c.commit()
    return jsonify(_apin_out(c, [c.execute("SELECT * FROM list_notepads WHERE id=?", (pid,)).fetchone()])[0])


@app.delete("/api/v1/notepads/<int:pid>")
@v1_view
def v1_apin_delete(pid):
    """Remove a notepad -- an agent only its own (its colour goes along, as in the web app)."""
    import json
    v1_args(())
    c = db()
    r = _apin_pad(c, pid)
    c.execute("DELETE FROM list_notepads WHERE id=?", (pid,))
    st = c.execute("SELECT page_style FROM lists WHERE id=?", (r["list_id"],)).fetchone()
    try:
        style = json.loads(st["page_style"] or "{}") if st else {}
    except ValueError:
        style = {}
    if isinstance(style, dict) and style.pop(f"np{pid}", None):
        c.execute("UPDATE lists SET page_style=? WHERE id=?", (json.dumps(style, separators=(",", ":")) if style else "", r["list_id"]))
    bump(c)
    c.commit()
    return jsonify(ok=True, pad=_apin_out(c, [r])[0])


@app.put("/api/v1/lists/<int:lid>/status-pad")
@v1_view
def v1_apin_status(lid):
    """{body, title?}: the agent's status block of this project (one per agent and list): created the first time, then
    overwritten -- only its own, never the notepads of people or other agents. Agents only."""
    from ..agents.core import need_agent
    v1_args(())
    aid = need_agent()
    b = v1_json()
    if set(b) - {"title", "body"} or "body" not in b:
        raise BadInput(tr("Invalid notepad"))
    v = _wg_pad_text({"title": b.get("title") or tr("Status"), "body": b["body"]}, False)
    c = db()
    _apin_list(c, lid, True)
    r = c.execute("SELECT id FROM list_notepads WHERE list_id=? AND agent_id=? AND agent_key='status' ORDER BY id LIMIT 1", (lid, aid)).fetchone()
    code = 200
    if r:
        pid = r["id"]
        c.execute("UPDATE list_notepads SET title=?, body=?, updated_by=?, updated_at=? WHERE id=?", (v["title"], v["body"], aid, iso(now_utc()), pid))
    else:
        pid, code = _apin_create(c, lid, v, "status"), 201
    bump(c)
    c.commit()
    return jsonify(_apin_out(c, [c.execute("SELECT * FROM list_notepads WHERE id=?", (pid,)).fetchone()])[0]), code


# ---------------------------------------------------------------- the weekly status: numbers, the agent writes the words
def apin_weekly(c, lid, uid, days=APIN_DAYS):
    """{list_id, name, from, to, counts, done, overdue, blocked, waiting, waits, people} of project lid as uid sees it
    (only tasks uid may see, tvis). done: completed in the last `days` days (today included)."""
    days = max(1, min(APIN_DAYS_MAX, int(days)))
    today = local_now().date()
    since = today - timedelta(days=days - 1)
    lst = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()
    vis = tvis(c, uid, "t.")
    base = f"FROM tasks t WHERE t.list_id=? AND t.deleted_at IS NULL AND {vis}"
    from ..personal.timetrack import local_bounds
    lo, _ = local_bounds(since, today)
    done = c.execute(f"SELECT t.id, t.title, t.completed_at, t.completed_by, t.assignee_id {base} AND t.status=2 AND t.completed_at>=? "
                     "ORDER BY t.completed_at DESC, t.id", (lid, lo)).fetchall()
    opn = c.execute(f"SELECT t.id, t.title, t.due, t.assignee_id, t.waiting_at, t.wait_note, t.parent_id {base} AND t.status=0 "
                    "ORDER BY t.due NULLS LAST, t.id", (lid,)).fetchall()
    ids = [r["id"] for r in opn]
    blockers = {}
    if ids:
        q = ",".join("?" * len(ids))
        for r in c.execute(f"""SELECT d.task_id, b.id, b.title, b.assignee_id, b.list_id FROM task_deps d JOIN tasks b ON b.id=d.blocker_id
                               WHERE d.task_id IN ({q}) AND b.deleted_at IS NULL AND b.status=0 AND {tvis(c, uid, 'b.')}""", ids):
            blockers.setdefault(r[0], []).append({"id": r[1], "title": r[2], "assignee_id": r[3], "same_list": r[4] == lid})
    ppl = set()
    overdue, blocked, waiting, waits = [], [], [], {}
    for r in opn:
        if r["due"] and r["due"][:10] < today.isoformat():
            overdue.append({"id": r["id"], "title": r["title"], "due": r["due"][:10], "assignee_id": r["assignee_id"],
                            "days_late": (today - date.fromisoformat(r["due"][:10])).days})
            ppl.add(r["assignee_id"])
        if r["id"] in blockers:
            bl = blockers[r["id"]]
            blocked.append({"id": r["id"], "title": r["title"], "assignee_id": r["assignee_id"], "blocked_by": bl})
            ppl.add(r["assignee_id"])
            for x in bl:
                ppl.add(x["assignee_id"])
                if r["assignee_id"] and x["assignee_id"] and r["assignee_id"] != x["assignee_id"]:
                    w = waits.setdefault((r["assignee_id"], x["assignee_id"]), [])
                    if r["id"] not in w:
                        w.append(r["id"])
        if r["waiting_at"]:
            waiting.append({"id": r["id"], "title": r["title"], "since": r["waiting_at"], "on": r["wait_note"] or "",
                            "assignee_id": r["assignee_id"]})
            ppl.add(r["assignee_id"])
    for r in done:
        ppl.add(r["completed_by"])
    names = user_names(c, [p for p in ppl if p])
    cap = lambda v: v[:APIN_ITEMS]  # noqa: E731
    return {"list_id": lid, "name": lst["name"] if lst else "", "from": since.isoformat(), "to": today.isoformat(),
            "counts": {"done": len(done), "open": len(opn), "overdue": len(overdue), "blocked": len(blocked), "waiting": len(waiting)},
            "done": cap([{"id": r["id"], "title": r["title"], "completed_at": r["completed_at"], "by": r["completed_by"]} for r in done]),
            "overdue": cap(overdue), "blocked": cap(blocked), "waiting": cap(waiting),
            "waits": [{"who": a, "on": b, "task_ids": t} for (a, b), t in sorted(waits.items(), key=lambda x: -len(x[1]))][:APIN_ITEMS],
            "people": {str(k): v for k, v in names.items()}}


@app.get("/api/v1/lists/<int:lid>/weekly-status")
@v1_view
def v1_apin_weekly(lid):
    """The numbers of a project's week for the agent's status block (?days=1..31, default 7)."""
    a = v1_args(("days",))
    try:
        days = int(a.get("days") or APIN_DAYS)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "days")) from None
    c = db()
    _apin_list(c, lid, False)
    return jsonify(apin_weekly(c, lid, g.user["id"], days))


def apin_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of the pin board routes for agents (2.51.0, #1352)."""
    T = "Lists"
    schemas["Notepad"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "list_id": {"type": "integer"}, "title": {"type": "string"}, "body": {"type": "string", "description": "Markdown"},
        "updated_at": {"type": "string", "format": "date-time"}, "updated_by": {"type": "integer"},
        "agent_id": {"type": ["integer", "null"], "description": "The agent that wrote it (null = a person)"},
        "agent_key": {"type": ["string", "null"], "description": "status = the agent's status block"},
        "agent_name": {"type": ["string", "null"]}, "mine": {"type": "boolean", "description": "Written by the token's agent: it may change it"}}}
    schemas["NotepadInput"] = {"type": "object", "additionalProperties": False, "properties": {
        "title": {"type": "string", "maxLength": 200}, "body": {"type": "string", "maxLength": 20000, "description": "Markdown"}}}
    lid = pid("id", "Project list id")
    paths["/lists/{id}/notepads"] = {
        "get": op("2.51.0 (#1352): the notepads of a project page", T, ok({"type": "object", "properties": {
            "data": {"type": "array", "items": ref("Notepad")}}}) | errs("403", "404", "409"), [lid]),
        "post": op("2.51.0 (#1352): add a notepad to a project page (an agent's stays marked as its own)", T,
                   ok(ref("Notepad"), "Created", "201") | errs("400", "403", "404", "409"), [lid], body=ref("NotepadInput"), scope="pinboard",
                   desc="Needs write access to the list. At most 20 notepads per project.")}
    paths["/notepads/{id}"] = {
        "patch": op("2.51.0 (#1352): change a notepad (an agent: only its own)", T, ok(ref("Notepad")) | errs("400", "403", "404", "409"),
                    [pid("id", "Notepad id")], body=ref("NotepadInput"), scope="pinboard"),
        "delete": op("2.51.0 (#1352): remove a notepad (an agent: only its own)", T, ok({"type": "object"}) | errs("403", "404", "409"),
                     [pid("id", "Notepad id")], scope="pinboard")}
    paths["/lists/{id}/status-pad"] = {"put": op(
        "2.51.0 (#1352): write your status block of a project (agents; one per agent and list, overwritten each time)", T,
        ok(ref("Notepad")) | ok(ref("Notepad"), "Created", "201") | errs("400", "403", "404", "409"), [lid],
        body={"type": "object", "required": ["body"], "additionalProperties": False, "properties": {
            "title": {"type": "string", "maxLength": 200, "description": "Default: Status (in your language)"},
            "body": {"type": "string", "maxLength": 20000, "description": "Markdown"}}}, scope="pinboard",
        desc="The recipe Weekly status: GET /lists/{id}/weekly-status, write the words, PUT here. Never overwrites notepads of people.")}
    grp = {"type": "array", "items": {"type": "object"}}
    paths["/lists/{id}/weekly-status"] = {"get": op(
        "2.51.0 (#1352): the numbers of a project's week: done, overdue, blocked, waiting on external, who waits on whom", T,
        ok({"type": "object", "properties": {
            "list_id": {"type": "integer"}, "name": {"type": "string"}, "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"},
            "counts": {"type": "object", "properties": {k: {"type": "integer"} for k in ("done", "open", "overdue", "blocked", "waiting")}},
            "done": grp, "overdue": grp, "blocked": grp, "waiting": grp,
            "waits": {"type": "array", "items": {"type": "object", "properties": {
                "who": {"type": "integer"}, "on": {"type": "integer"}, "task_ids": {"type": "array", "items": {"type": "integer"}}}},
                "description": "who (assignee of a blocked task) waits on (assignee of an open blocker)"},
            "people": {"type": "object", "description": "user id -> name"}}}) | errs("400", "403", "404", "409"),
        [lid, q("days", f"Look back this many days, today included (1-{APIN_DAYS_MAX}, default {APIN_DAYS})", {"type": "integer"})],
        desc=f"Pure data, at most {APIN_ITEMS} tasks per group; only tasks the token's user may see.")}
