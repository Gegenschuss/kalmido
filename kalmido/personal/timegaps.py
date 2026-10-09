"""2.34.0 (#269): time-tracking helper. "Maybe forgotten": working days of the last two weeks on which a person worked on tasks
(completed, commented, changed) in project lists but tracked no time there. Pure data for the time view and the agent API
(GET /api/v1/time/gaps, MCP get_time_gaps); the timesheet text is built by the client from the report."""
from datetime import timedelta

from flask import g, jsonify, request

from ..core.config import app
from ..core.db import db, local_day, local_now
from ..core.i18n import tr
from ..core.access import Denied, PROJ_SQL, need_time, tvis, vis_sql
from ..accounts.session import me
from ..api.v1 import v1_args, v1_feature, v1_view
from ..personal.timetrack import BadInput, local_bounds

GAP_DAYS, GAP_DAYS_MAX = 14, 31   # look back this many days (today not included: the day is not over yet)
GAP_TASKS = 5                      # task examples per day
GAP_WORKDAYS = (0, 1, 2, 3, 4)     # Monday to Friday (assumption: there is no per-person working days setting yet)


def time_gaps(c, uid, viewer=None, days=GAP_DAYS):
    """{from, to, days: [{date, count, tasks: [{id, title, list_id}]}]} for person uid, newest day first. viewer (an agent
    acting for uid): only tasks and entries in lists BOTH see; without viewer: what uid sees, plus uid's list-less entries."""
    viewer = viewer or uid
    days = max(1, min(GAP_DAYS_MAX, int(days)))
    end = local_now().date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    lo, hi = local_bounds(start, end)
    both = f"t.list_id IN {vis_sql()} AND t.list_id IN {vis_sql()} AND t.list_id IN {PROJ_SQL} AND {tvis(c, uid, 't.')} AND {tvis(c, viewer, 't.')}"
    vargs = [uid, uid, viewer, viewer]
    rows = c.execute(f"""
        SELECT x.tid, x.ts, t.title, t.list_id FROM (
            SELECT task_id AS tid, created_at AS ts FROM activity WHERE user_id=? AND created_at>=? AND created_at<?
            UNION ALL SELECT task_id, created_at FROM comments WHERE user_id=? AND deleted_at IS NULL AND created_at>=? AND created_at<?
            UNION ALL SELECT id, completed_at FROM tasks WHERE completed_by=? AND completed_at>=? AND completed_at<?) x
        JOIN tasks t ON t.id=x.tid WHERE t.deleted_at IS NULL AND {both}""",
                     [uid, lo, hi, uid, lo, hi, uid, lo, hi] + vargs).fetchall()
    worked = {}
    for r in rows:
        d = local_day(r["ts"])
        if d is None or d.weekday() not in GAP_WORKDAYS:
            continue
        worked.setdefault(d, {}).setdefault(r["tid"], {"id": r["tid"], "title": r["title"], "list_id": r["list_id"]})
    if not worked:
        return {"from": start.isoformat(), "to": end.isoformat(), "days": []}
    own = " OR e.list_id IS NULL" if viewer == uid else ""
    tracked = {local_day(r[0]) for r in c.execute(
        f"""SELECT e.start FROM time_entries e WHERE e.user_id=? AND e.start>=? AND e.start<?
            AND ((e.list_id IN {vis_sql()} AND e.list_id IN {vis_sql()}){own})""",
        [uid, lo, hi, uid, uid, viewer, viewer])}
    out = []
    for d in sorted(worked, reverse=True):
        if d in tracked:
            continue
        ts = sorted(worked[d].values(), key=lambda x: x["id"])
        out.append({"date": d.isoformat(), "count": len(ts), "tasks": ts[:GAP_TASKS]})
    return {"from": start.isoformat(), "to": end.isoformat(), "days": out}


def _gap_args(a):
    try:
        return int(a.get("days") or GAP_DAYS)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "days")) from None


@app.get("/api/time/gaps")
def time_gaps_get():
    """The time view's hint "Maybe forgotten" for the signed-in person."""
    need_time()
    return jsonify(time_gaps(db(), me(), days=_gap_args(request.args)))


@app.get("/api/v1/time/gaps")
@v1_view
def v1_time_gaps():
    """The token user's own gaps; an agent may ask for user_id = a person who may chat with it (only lists both see)."""
    from ..agents.core import agent_shares, is_agent
    need_time()
    v1_feature("time")
    a = v1_args(("days", "user_id"))
    c, uid = db(), me()
    pid = uid
    if a.get("user_id"):
        try:
            pid = int(a["user_id"])
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "user_id")) from None
        if pid != uid:
            u = c.execute("SELECT kind, disabled FROM users WHERE id=?", (pid,)).fetchone()
            if not is_agent(g.user) or not u or u["kind"] == "agent" or u["disabled"] or not agent_shares(c, uid, pid):
                raise Denied(404)
    return jsonify({"user_id": pid, **time_gaps(c, pid, viewer=uid, days=_gap_args(a))})


def timegaps_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    """OpenAPI of GET /api/v1/time/gaps (2.34.0, #269)."""
    schemas["TimeGaps"] = {"type": "object", "properties": {
        "user_id": {"type": "integer"}, "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"},
        "days": {"type": "array", "items": {"type": "object", "properties": {
            "date": {"type": "string", "format": "date"}, "count": {"type": "integer", "description": "Tasks worked on that day"},
            "tasks": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "integer"}, "title": {"type": "string"}, "list_id": {"type": "integer"}}},
                      "description": f"At most {GAP_TASKS} examples"}}}}}}
    paths["/time/gaps"] = {"get": op(
        "Working days without tracked time although the person worked on tasks (maybe forgotten)", "Time tracking",
        ok(ref("TimeGaps")) | errs("400", "403", "404"),
        [q("days", f"Look back this many days before today (1-{GAP_DAYS_MAX}, default {GAP_DAYS})", {"type": "integer", "minimum": 1, "maximum": GAP_DAYS_MAX}),
         q("user_id", "An agent: the person it works for (someone who may chat with it); default: the token's user", {"type": "integer"})],
        desc="2.34.0 (#269). Monday to Friday of the last days (not today) on which the person completed, commented or changed tasks "
             "of project lists but has no time entry there. For an agent only lists that the agent and the person both see count "
             "(tasks and entries). Pure data: suggest entries to the person, never add time for them without asking.")}
