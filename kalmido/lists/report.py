"""2.34.0 (#265): the status report of a project (or any list) for a period (default: the last 7 days) -- done, in progress,
blocked, overdue, the next dates and milestones, the tracked hours. Pure data plus a plain Markdown text built from fixed
sentences (no generated prose) that a person copies or shares with a client. Internal things stay out of the text on
purpose: no comments, no descriptions or notes, no names of people or agents, no note of the project status. The app shows
it on the project page ("Status report": preview, period, copy, share); agents read the same data through the API / MCP
(read_project_status) -- only in lists shared with them."""
from datetime import date, timedelta

from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import dec_comma, lang, short_day, tr, trn
from ..core.db import db, inbox_default, local_now, now_utc
from ..core.access import need_list, time_all, tvis
from ..personal.timetrack import BadInput, entry_out, time_on, time_rows, time_rounding, vis_ids
from ..core.db import usettings
from ..api.v1 import v1_args, v1_view

REPORT_LIST_MAX = 30     # rows per section (the counts are complete)
REPORT_DAYS_MAX = 366    # longest period
REPORT_AHEAD_DAYS = 14   # "next dates": due from today until this many days after the period's end


def report_period(a):
    """?from=&to= (local days, inclusive) or ?days=N (the last N days up to today) -> (from, to) as dates; default the last 7."""
    today = local_now().date()
    try:
        to = date.fromisoformat(a["to"]) if a.get("to") else today
        if a.get("from"):
            frm = date.fromisoformat(a["from"])
        else:
            n = int(a.get("days") or 7)
            if not 1 <= n <= REPORT_DAYS_MAX:
                raise ValueError
            frm = to - timedelta(days=n - 1)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid date or time")) from None
    if frm > to:
        frm, to = to, frm
    if (to - frm).days >= REPORT_DAYS_MAX:
        raise BadInput(tr("Invalid date or time"))
    return frm, to


def _bounds(frm, to):
    from ..personal.timetrack import local_bounds
    return local_bounds(frm, to)


def project_status(c, lid, uid, *, frm=None, to=None, with_time=True):
    """The status data of list lid as uid sees it (the caller checked need_list(c, lid, write=False)). frm / to: dates.
    with_time=False: no time block (time: None), see time_allowed."""
    today = local_now().date()
    to = to or today
    frm = frm or (to - timedelta(days=6))
    lo, hi = _bounds(frm, to)
    lst = c.execute("SELECT id, name, is_inbox, kind, status FROM lists WHERE id=?", (lid,)).fetchone()
    vis = tvis(c, uid, "t.")
    base = f"FROM tasks t WHERE t.list_id=? AND t.deleted_at IS NULL AND {vis}"
    cols = "t.id, t.title, t.due, t.due_time, t.status, t.completed_at, t.parent_id, t.ms, t.waiting_at, t.wait_note, t.wait_until"

    def row(r, **x):
        d = {"id": r["id"], "title": r["title"], "due": r["due"], "milestone": bool(r["ms"])}
        d.update(x)
        return d
    done_all = c.execute(f"""SELECT {cols} {base} AND t.status=2 AND t.completed_at>=? AND t.completed_at<?
                             ORDER BY t.completed_at, t.id""", (lid, lo, hi)).fetchall()
    done = [r for r in done_all if not r["parent_id"] and not r["ms"]]
    reached = [r for r in done_all if r["ms"]]
    opened = c.execute(f"""SELECT {cols},
                             (SELECT COUNT(*) FROM task_deps d JOIN tasks b ON b.id=d.blocker_id WHERE d.task_id=t.id AND b.status=0
                                AND b.deleted_at IS NULL AND b.list_id IN (SELECT id FROM lists WHERE kind='project')) AS open_blockers,
                             (EXISTS (SELECT 1 FROM activity a WHERE a.task_id=t.id AND a.kind!='created' AND a.created_at>=? AND a.created_at<?)
                              OR EXISTS (SELECT 1 FROM comments cm WHERE cm.task_id=t.id AND cm.deleted_at IS NULL AND cm.created_at>=? AND cm.created_at<?)
                              OR EXISTS (SELECT 1 FROM time_entries te WHERE te.task_id=t.id AND te.start>=? AND te.start<?)
                              OR EXISTS (SELECT 1 FROM tasks s WHERE s.parent_id=t.id AND s.deleted_at IS NULL AND s.updated_at>=? AND s.updated_at<?)) AS moved
                           {base} AND t.status=0 AND t.parent_id IS NULL ORDER BY t.due IS NULL, t.due, t.sort, t.id""",
                       (lo, hi, lo, hi, lo, hi, lo, hi, lid)).fetchall()
    t0 = today.isoformat()
    blocked = [r for r in opened if not r["ms"] and (r["waiting_at"] or r["open_blockers"])]
    bl_ids = {r["id"] for r in blocked}
    progress = [r for r in opened if not r["ms"] and r["moved"] and r["id"] not in bl_ids]
    overdue = [r for r in opened if not r["ms"] and r["due"] and r["due"][:10] < t0]
    ahead = (max(to, today) + timedelta(days=REPORT_AHEAD_DAYS)).isoformat()
    upcoming = [r for r in opened if r["due"] and t0 <= r["due"][:10] <= ahead]
    ms_next = [r for r in opened if r["ms"] and (not r["due"] or r["due"][:10] >= t0)][:5]
    out = {"list": {"id": lid, "name": tr("Inbox") if lst["is_inbox"] and inbox_default(lst["name"]) else lst["name"],
                    "project": lst["kind"] == "project", "status": lst["status"] or None},
           "from": frm.isoformat(), "to": to.isoformat(), "today": t0,
           "counts": {"done": len(done), "done_subtasks": sum(1 for r in done_all if r["parent_id"] and not r["ms"]),
                      "in_progress": len(progress), "blocked": len(blocked), "overdue": len(overdue), "upcoming": len(upcoming),
                      "open": sum(1 for r in opened if not r["ms"])},
           "done": [row(r, completed_at=r["completed_at"]) for r in done[:REPORT_LIST_MAX]],
           "in_progress": [row(r) for r in progress[:REPORT_LIST_MAX]],
           "blocked": [row(r, reason="waiting" if r["waiting_at"] else "blocked", wait_note=(r["wait_note"] or "") if r["waiting_at"] else "",
                           wait_until=r["wait_until"] if r["waiting_at"] else None) for r in blocked[:REPORT_LIST_MAX]],
           "overdue": [row(r) for r in overdue[:REPORT_LIST_MAX]],
           "upcoming": [row(r, due_time=r["due_time"]) for r in upcoming[:REPORT_LIST_MAX]],
           "milestones": [row(r, done=True, completed_at=r["completed_at"]) for r in reached]
                         + [row(r, done=False) for r in ms_next],
           "time": _time_of(c, lid, uid, frm, to) if with_time and lst["kind"] == "project" and time_all() else None}
    return out


def time_allowed(c, uid):
    """2.34.0 review (M1): the tracked hours only for a caller who may read time: time tracking on (server and the person's
    own module switch) and, for a token, the scope "time" -- like GET /time/entries."""
    if not time_on(usettings(c, uid)):
        return False
    return g.get("auth_via") != "token" or "time" in (g.get("scopes") or set())


def _time_of(c, lid, uid, frm, to):
    """The hours tracked on the list in the period, as uid sees them (everyone's entries in a shared project; a participant
    their own and those on their tasks); None when there are none."""
    rows, _, _, _ = time_rows(c, uid, {"from": frm.isoformat(), "to": to.isoformat(), "scope": "all"})
    vis, ref, rm = vis_ids(c, uid), now_utc(), time_rounding(usettings(c, uid))
    tot, rnd, per = 0, 0, {}
    for r in rows:
        if r["list_id"] != lid:
            continue
        e = entry_out(r, uid, vis, ref, rm)
        if e["list_id"] != lid:
            continue
        tot += e["seconds"]
        rnd += e["rounded"]
        k = e["task_id"] or 0
        x = per.setdefault(k, {"id": e["task_id"], "title": e["title"] if e["task_id"] else "", "seconds": 0, "rounded": 0})
        x["seconds"] += e["seconds"]
        x["rounded"] += e["rounded"]
    if not tot:
        return None
    return {"seconds": tot, "rounded": rnd, "rounding": rm,
            "tasks": sorted(per.values(), key=lambda x: (-x["seconds"], x["title"].casefold()))[:REPORT_LIST_MAX]}


def _hours(sec, lg):
    s = f"{sec / 3600:.1f}"
    return s.replace(".", ",") if dec_comma(lg) else s


def status_markdown(d, lg=None):
    """The report as plain Markdown in language lg (fixed sentences, the person edits it before sending)."""
    from ..lists.projects import LIST_STATUS_NAMES
    lg = lg or lang()
    day = lambda v: short_day(date.fromisoformat(v[:10]), lg, year=True)  # noqa: E731
    L = [f"# {tr('Status report: {0}', d['list']['name'], lg=lg)}", "",
         tr("Period: {0} – {1}", day(d["from"]), day(d["to"]), lg=lg)]
    if d["list"].get("status") in LIST_STATUS_NAMES:
        L.append(tr("Status: {0}", tr(LIST_STATUS_NAMES[d["list"]["status"]], lg=lg), lg=lg))
    n = d["counts"]

    def sec(title, items, count, fmt):
        if not count:
            return
        L.extend(["", f"## {title} ({count})"])
        L.extend("- " + fmt(x) for x in items)
        if count > len(items):
            L.append("- " + trn("and {0} more", "and {0} more", count - len(items), lg=lg))
    due = lambda x: f" ({tr('due {0}', day(x['due']), lg=lg)})" if x.get("due") else ""  # noqa: E731
    sec(tr("Completed", lg=lg), d["done"], n["done"], lambda x: x["title"])
    sec(tr("In progress", lg=lg), d["in_progress"], n["in_progress"], lambda x: x["title"] + due(x))
    sec(tr("Blocked", lg=lg), d["blocked"], n["blocked"],
        lambda x: x["title"] + (f" – {tr('waiting on: {0}', x['wait_note'], lg=lg)}" if x.get("wait_note") else
                                f" – {tr('waiting for another task', lg=lg)}" if x.get("reason") == "blocked" else ""))
    sec(tr("Overdue", lg=lg), d["overdue"], n["overdue"], lambda x: x["title"] + due(x))
    nxt = sorted([x for x in d["upcoming"]], key=lambda x: x["due"])
    if nxt:
        L.extend(["", f"## {tr('Next dates', lg=lg)}"])
        L.extend(f"- {day(x['due'])}: " + (tr("Milestone: {0}", x["title"], lg=lg) if x["milestone"] else x["title"]) for x in nxt)
        if n["upcoming"] > len(nxt):
            L.append("- " + trn("and {0} more", "and {0} more", n["upcoming"] - len(nxt), lg=lg))
    reached = [x for x in d["milestones"] if x.get("done")]
    if reached:
        L.extend(["", f"## {tr('Milestones reached', lg=lg)}"])
        L.extend(f"- {x['title']}" for x in reached)
    if d.get("time"):
        t = d["time"]
        L.extend(["", f"## {tr('Tracked time', lg=lg)}", tr("Total: {0} h", _hours(t["rounded"], lg), lg=lg)])
    if not (n["done"] or n["in_progress"] or n["blocked"] or n["overdue"] or nxt or reached or d.get("time")):
        L.extend(["", tr("Nothing changed in this period.", lg=lg)])
    return "\n".join(L) + "\n"


def _report(lid, a):
    c = db()
    need_list(c, lid, write=False)
    frm, to = report_period(a)
    d = project_status(c, lid, g.user["id"], frm=frm, to=to, with_time=time_allowed(c, g.user["id"]))
    lg = a.get("lang") if a.get("lang") else None
    from ..core.i18n import LANGS
    if lg and lg != "en" and lg not in LANGS:
        raise BadInput(tr("Invalid value: {0}", "lang"))
    d["markdown"] = status_markdown(d, lg or None)
    return d


@app.get("/api/lists/<int:lid>/status-report")
def list_status_report(lid):
    """2.34.0 (#265): ?from=&to= | ?days=N (default 7), ?lang= -> the data + the Markdown text."""
    return jsonify(_report(lid, request.args))


@app.get("/api/v1/lists/<int:lid>/status-report")
@v1_view
def v1_list_status_report(lid):
    """2.34.0 (#265): the status report of a list the token's user sees (an agent: a list shared with it)."""
    return jsonify(_report(lid, v1_args(("from", "to", "days", "lang"))))


def report_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    """OpenAPI of GET /lists/{id}/status-report (called from api.openapi)."""
    item = {"type": "object", "properties": {
        "id": {"type": "integer"}, "title": {"type": "string"}, "due": nul("string"), "milestone": {"type": "boolean"},
        "completed_at": {"type": "string"}, "reason": {"type": "string", "enum": ["waiting", "blocked"]},
        "wait_note": {"type": "string"}, "wait_until": nul("string"), "done": {"type": "boolean"}}}
    schemas["StatusReportItem"] = item
    arr = {"type": "array", "items": ref("StatusReportItem")}
    schemas["StatusReport"] = {"type": "object", "properties": {
        "list": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "project": {"type": "boolean"},
                                                  "status": nul("string")}},
        "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"}, "today": {"type": "string", "format": "date"},
        "counts": {"type": "object", "properties": {k: {"type": "integer"} for k in
                                                    ("done", "done_subtasks", "in_progress", "blocked", "overdue", "upcoming", "open")}},
        "done": arr, "in_progress": {**arr, "description": "Open main tasks with a change, comment or time entry in the period"},
        "blocked": arr, "overdue": arr, "upcoming": {**arr, "description": "Open tasks and milestones due from today until 14 days after the period"},
        "milestones": {**arr, "description": "Reached in the period (done) and the next open ones"},
        "time": {"type": ["object", "null"], "description": "Tracked hours of a project; null without time entries, when time "
                 "tracking is off for the server or the person, or for a token without the scope time", "properties": {"seconds": {"type": "integer"}, "rounded": {"type": "integer"},
                                                            "rounding": {"type": "integer"}, "tasks": {"type": "array", "items": {"type": "object"}}}},
        "markdown": {"type": "string", "description": "A plain text to copy (fixed sentences; no comments, notes or names)"}}}
    date_s = {"type": "string", "format": "date"}
    paths["/lists/{id}/status-report"] = {"get": op("The status report of a list for a period (default: the last 7 days)", "Lists",
                                                    ok(ref("StatusReport")) | errs("400", "404"),
                                                    [pid("id", "List id"), q("from", "First day", date_s), q("to", "Last day (default today)", date_s),
                                                     q("days", "Instead of from: the last N days up to `to` (1-366, default 7)", {"type": "integer"}),
                                                     q("lang", "Language of the Markdown text (default: the token user's)", {"type": "string"})],
                                                    desc="Pure data plus a Markdown text; nothing is generated beyond fixed sentences.")}
