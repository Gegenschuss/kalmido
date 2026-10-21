"""2.116.0 D (#2067): focus sessions (pomodoro) and habit statistics over API v1.

Focus sessions are private to a person: only a person's own token reaches them (scope read for reading, time for
start / pause / resume / stop -- a focus session on a task becomes a time entry). An agent token -- team agent or
personal agent -- always gets 403, so no agent sees the focus data of a member of the organisation. The rules are the
app's own (pomo_start / pomo_action / pomo_stats_api run through v1_call), nothing is duplicated."""
from datetime import timedelta

from flask import g, jsonify

from ..core.config import app
from ..core.access import Denied, need_task, tvis, vis_sql
from ..core.db import db, local_now
from ..core.i18n import tr
from ..accounts.session import me
from ..api.v1 import BadInput, UnknownFields, v1_limit
from ..api.common import cursor_dec, cursor_enc, v1_args, v1_call, v1_json, v1_view
from ..tasks.validation import as_int
from .habits import need_habit, pomo_action, pomo_elapsed, pomo_start, pomo_stats_api

V1F_KINDS = ("focus", "short", "long", "stopwatch")


def v1f_person():
    """Focus data belongs to a person: an agent token (team or personal) is refused."""
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("Focus sessions are private to a person"))


def v1f_dict(r, title=None, task_ok=True):
    return {"id": r["id"], "kind": r["kind"], "task_id": r["task_id"] if task_ok else None, "task_title": title if task_ok else None,
            "planned_minutes": r["minutes"], "start": r["start"], "end": r["end"], "paused": bool(r["paused_at"] and not r["end"]),
            "done": bool(r["done"]), "running": r["end"] is None, "elapsed_minutes": round(pomo_elapsed(r) / 60, 1)}


@app.get("/api/v1/focus")
@v1_view
def v1_focus():
    """Newest first: the running session (if any) and the finished ones, cursor = older than the last id."""
    v1f_person()
    a = v1_args(("limit", "cursor"))
    lim, before = v1_limit(a), cursor_dec("fo", a.get("cursor"))
    c = db()
    rows = c.execute(f"""SELECT p.*, t.title, (t.id IS NOT NULL) AS vis FROM pomos p
                         LEFT JOIN tasks t ON t.id=p.task_id AND t.list_id IN {vis_sql()} AND {tvis(c, me(), "t.")}
                         WHERE p.user_id=? AND (?=0 OR p.id<?) ORDER BY p.id DESC LIMIT ?""",
                     (me(), me(), me(), before, before, lim + 1)).fetchall()
    more = len(rows) > lim
    rows = rows[:lim]
    return jsonify(data=[v1f_dict(r, r["title"], bool(r["vis"]) or not r["task_id"]) for r in rows],
                   next_cursor=cursor_enc("fo", rows[-1]["id"]) if more and rows else None)


@app.get("/api/v1/focus/stats")
@v1_view
def v1_focus_stats():
    v1f_person()
    v1_args(())
    return jsonify(v1_call(pomo_stats_api))


@app.post("/api/v1/focus/start")
@v1_view
def v1_focus_start():
    """{kind?: focus|short|long|stopwatch (default focus), minutes?: 1-600 (default: the person's setting), task_id?}.
    A running session ends first (one at a time, as in the app)."""
    v1f_person()
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("kind", "minutes", "task_id"))
    if unknown:
        raise UnknownFields(unknown)
    fwd = {}
    if "kind" in b:
        if b["kind"] not in V1F_KINDS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        fwd["kind"] = b["kind"]
    if b.get("minutes") is not None:
        fwd["minutes"] = as_int(b["minutes"], "minutes", 1, 600)
    if b.get("task_id") is not None:
        fwd["task_id"] = as_int(b["task_id"], "task_id", 1, 2 ** 62)
        need_task(db(), fwd["task_id"], write=False, full=True)  # 2.116.0 review F7: a task the person cannot see = 404, not a silent session
    p = v1_call(pomo_start, body=fwd)
    return jsonify(data=v1f_dict(p) if p else None), 201


def v1f_action(pid, action):
    v1f_person()
    v1_args(())
    j = v1_call(pomo_action, pid, action, body={})
    r = db().execute("SELECT * FROM pomos WHERE id=? AND user_id=?", (pid, me())).fetchone()
    return jsonify(data=v1f_dict(r), today=j.get("today"))


@app.post("/api/v1/focus/<int:pid>/stop")
@v1_view
def v1_focus_stop(pid):
    return v1f_action(pid, "stop")


@app.post("/api/v1/focus/<int:pid>/pause")
@v1_view
def v1_focus_pause(pid):
    return v1f_action(pid, "pause")


@app.post("/api/v1/focus/<int:pid>/resume")
@v1_view
def v1_focus_resume(pid):
    return v1f_action(pid, "resume")


def v1f_habit_stats(c, h):
    """Streaks and shares like the app's habit page (static/js/habits.js habitStats): fixed weekdays or x times a week."""
    t0 = local_now().date()
    logs = {r["day"]: r["count"] for r in c.execute("SELECT day, count FROM habit_logs WHERE habit_id=? AND count>=?", (h["id"], h["goal"]))}
    # from the first log (a habit can be filled in backwards), at most 800 days back
    first = max(min([h["created_at"][:10], *logs]), (t0 - timedelta(days=800)).isoformat())

    def sched(d):
        return bool(h["per_week"]) or str(d.isoweekday()) in h["days"]

    def mon(d):
        return d - timedelta(days=d.weekday())

    def week_done(m):
        return sum(1 for i in range(7) if (m + timedelta(days=i)).isoformat() in logs)

    out = {"habit_id": h["id"], "name": h["name"], "total_days": len(logs), "per_week": h["per_week"]}
    if h["per_week"]:
        m, cur, best, run, hit, n = mon(t0), 0, 0, 0, 0, 0
        if week_done(m) < h["per_week"]:
            m -= timedelta(days=7)
        while cur < 300 and week_done(m) >= h["per_week"]:
            cur, m = cur + 1, m - timedelta(days=7)
        m = mon(t0)
        for g_ in range(300):
            if m.isoformat() < mon(date_of(first)).isoformat():
                break
            if week_done(m) >= h["per_week"]:
                run += 1
                best = max(best, run)
            elif g_:
                run = 0
            m -= timedelta(days=7)
        for w in range(1, 5):
            m = mon(t0) - timedelta(days=7 * w)
            if m.isoformat() < mon(date_of(first)).isoformat():
                break
            n += 1
            hit += week_done(m) >= h["per_week"]
        out.update(current_streak=cur, best_streak=best, streak_unit="weeks", rate_percent=round(100 * hit / n) if n else 0)
        return out
    d, cur = t0, 0
    if t0.isoformat() not in logs:
        d = t0 - timedelta(days=1)
    for _ in range(800):
        if d.isoformat() < first:
            break
        if sched(d):
            if d.isoformat() not in logs:
                break
            cur += 1
        d -= timedelta(days=1)
    best = run = 0
    d = date_of(first)
    while d <= t0:
        if sched(d):
            if d.isoformat() in logs:
                run += 1
                best = max(best, run)
            elif d != t0:
                run = 0
        d += timedelta(days=1)
    s = hit = 0
    for i in range(30):
        d = t0 - timedelta(days=i)
        if d.isoformat() < first:
            break
        if sched(d):
            s += 1
            hit += d.isoformat() in logs
    out.update(current_streak=cur, best_streak=best, streak_unit="days", rate_percent=round(100 * hit / s) if s else 0)
    return out


def date_of(s):
    from datetime import date
    return date.fromisoformat(s)


@app.get("/api/v1/habits/<int:hid>/stats")
@v1_view
def v1_habit_stats(hid):
    v1_args(())
    c = db()
    need_habit(c, hid)
    return jsonify(v1f_habit_stats(c, c.execute("SELECT * FROM habits WHERE id=?", (hid,)).fetchone()))


def v1f_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of the focus routes and the habit statistics (called from api/openapi.py)."""
    F = "Focus"
    schemas["FocusSession"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "kind": {"type": "string", "enum": list(V1F_KINDS)}, "task_id": {"type": ["integer", "null"]},
        "task_title": {"type": ["string", "null"]}, "planned_minutes": {"type": "integer", "description": "0 = stopwatch"},
        "start": {"type": "string"}, "end": {"type": ["string", "null"]}, "paused": {"type": "boolean"}, "done": {"type": "boolean"},
        "running": {"type": "boolean"}, "elapsed_minutes": {"type": "number"}}}
    schemas["HabitStats"] = {"type": "object", "properties": {
        "habit_id": {"type": "integer"}, "name": {"type": "string"}, "total_days": {"type": "integer"}, "per_week": {"type": "integer"},
        "current_streak": {"type": "integer"}, "best_streak": {"type": "integer"}, "streak_unit": {"type": "string", "enum": ["days", "weeks"]},
        "rate_percent": {"type": "integer", "description": "Share of the last 30 scheduled days (last 4 full weeks for x-times-a-week) that hit the goal"}}}
    one = {"type": "object", "properties": {"data": ref("FocusSession")}}
    priv = "Focus sessions are private to a person: only a person's own token reaches them; an agent token always gets 403."
    paths["/focus"] = {"get": op("Focus sessions (pomodoro), newest first, running one included (2.116.0)", F,
                                 ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("FocusSession")},
                                                                       "next_cursor": {"type": ["string", "null"]}}}) | errs("400", "403"),
                                 [q("limit", "Page size", {"type": "integer"}), q("cursor", "From next_cursor")], desc=priv)}
    paths["/focus/stats"] = {"get": op("Focus statistics: today, 7 days, per day, per task, recent sessions (2.116.0)", F,
                                       ok({"type": "object"}) | errs("403"), desc=priv)}
    paths["/focus/start"] = {"post": op("Start a focus session, break or stopwatch (2.116.0)", F, ok(one, "Created", "201") | errs("400", "403"),
                                        body={"type": "object", "additionalProperties": False, "properties": {
                                            "kind": {"type": "string", "enum": list(V1F_KINDS), "default": "focus"},
                                            "minutes": {"type": "integer", "minimum": 1, "maximum": 600, "description": "Default: your setting"},
                                            "task_id": {"type": "integer", "description": "A task you may see; the session becomes a time entry on it"}}},
                                        scope="write", desc=priv + " A running session ends first.")}
    for act, txt in (("stop", "Stop (end) a focus session"), ("pause", "Pause a focus session"), ("resume", "Resume a paused focus session")):
        paths[f"/focus/{{id}}/{act}"] = {"post": op(txt + " (2.116.0)", F, ok({"type": "object", "properties": {
            "data": ref("FocusSession"), "today": {"type": "object"}}}) | errs("403", "404"), [pid("id", "Session id")], scope="write", desc=priv)}
    paths["/habits/{id}/stats"] = {"get": op("Streaks and hit rate of a habit (2.116.0)", "Habits", ok(ref("HabitStats")) | errs("404"),
                                             [pid("id", "Habit id")])}
