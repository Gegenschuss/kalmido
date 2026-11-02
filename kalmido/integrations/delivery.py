"""2.392.0 D (#3369): the delivery report of a list for a day or since a moment (GET /api/v1/lists/<id>/delivery-report): released,
in main, in progress, stuck, completed. Pure data from the status report (lists/report.py) and the build state of the tasks
(gitbuild.git_build_for) plus a Markdown text of fixed headings; a scheduled job can post it, Kalmido formulates nothing and
pushes nothing. A list without a repository still gets in progress, stuck (blocked tasks, waiting jobs) and completed.

"Released" = a task whose version (its commits, pull requests or version field) has a tag first seen in the period, git_tags
.seen_at being the only date of a tag. "Stuck" = open with a branch that did not move in the period, a waiting job, or blocked."""
from datetime import date, timedelta

from flask import g, jsonify

from ..api.common import v1_args, v1_view
from ..collab.liste2eguard import le2b_list_locked, le2b_net, le2b_off
from ..core.access import Denied, need_list, tvis
from ..core.config import TZ, app
from ..core.db import db, iso, local_now, now_utc, parse_iso
from ..core.errors import BadInput
from ..core.i18n import short_day, tr, trn, LANGS
from ..lists.report import REPORT_DAYS_MAX, project_status
from ..personal.timetrack import local_bounds
from .git import git_conns_of_list
from .gitbuild import gb_key, gb_untrusted, git_build_for

WAIT_MAX = 100  # 2.392.0 D (#3369): agents/waiting.py, its OpenAPI text stands below (api.openapi reads no module of the agents layer)
WAIT_KINDS = ("job", "approval", "gate", "review", "blocked", "irreversible")
WAIT_KINDS += ("parked",)  # 2.392.2 (#3365): my own parked tasks (why = the reason)
GATE_ALL = ("merge_request", "integrate", "deploy")
DELIVERY_MAX = 100  # rows per section (the counts are complete)
DL_SECTIONS = ("released", "in_main", "in_progress", "stuck", "completed")


def dl_period(a):
    """?date=YYYY-MM-DD (a day of the instance) | ?since=ISO | neither: the last 24 hours -> (lo, hi) UTC datetimes as ISO, first day."""
    if a.get("date") and a.get("since"):
        raise BadInput(tr("Invalid value: {0}", "since"))
    now = now_utc()
    if a.get("date"):
        try:
            d = date.fromisoformat(a["date"])
        except ValueError:
            raise BadInput(tr("Invalid date or time")) from None
        return (*local_bounds(d, d), d)
    since = now - timedelta(hours=24)
    if a.get("since"):
        try:
            since = parse_iso(a["since"].replace("Z", "+00:00"))
        except ValueError:
            raise BadInput(tr("Invalid date or time")) from None
        since = since.replace(tzinfo=TZ) if since.tzinfo is None else since
        since = max(since, now - timedelta(days=REPORT_DAYS_MAX))
    return iso(since), iso(now + timedelta(seconds=1)), since.astimezone(TZ).date()  # hi is exclusive, iso() has whole seconds


def _released_tags(c, lid, lo, hi):
    """{version key: tag name} of the tags of the list's repositories first seen in [lo, hi)."""
    ids = [k["id"] for k in git_conns_of_list(c, lid)]
    if not ids:
        return {}
    q = ",".join(str(int(x)) for x in ids)
    rows = c.execute(f"SELECT name FROM git_tags WHERE conn_id IN ({q}) AND seen_at>=? AND seen_at<?", (lo, hi)).fetchall()
    return {gb_key(r["name"]): r["name"] for r in rows if gb_key(r["name"])}


def _tagged(c, lid, names):
    """Ids of tasks of list lid with a commit or pull request of one of the tags names, however long ago they closed."""
    if not names:
        return []
    marks = ",".join("?" for _ in names)
    return [r[0] for r in c.execute(
        f"""SELECT l.task_id FROM git_links l JOIN tasks t ON t.id=l.task_id JOIN git_commits m ON m.conn_id=l.conn_id AND m.sha=l.ref
            WHERE t.list_id=? AND l.kind='commit' AND m.tag IN ({marks})
            UNION SELECT l.task_id FROM git_links l JOIN tasks t ON t.id=l.task_id JOIN git_prs p ON p.conn_id=l.conn_id AND CAST(p.number AS TEXT)=l.ref
            WHERE t.list_id=? AND l.kind='pr' AND p.tag IN ({marks})""", (lid, *names, lid, *names))]


def delivery_report(c, lid, uid, lo, hi, first):
    """The data of list lid as uid sees it (the caller checked the list), without the Markdown text."""
    st = project_status(c, lid, uid, frm=first, to=local_now().date(), with_time=False, bounds=(lo, hi), cap=100000)
    tags = _released_tags(c, lid, lo, hi)
    linked = _tagged(c, lid, sorted(tags.values()))
    rows = c.execute(f"""SELECT t.id, t.title, t.list_id, t.status, t.due, t.completed_at, t.delivery, t.delivery_note FROM tasks t WHERE t.list_id=? AND t.deleted_at IS NULL
                         AND t.parent_id IS NULL AND t.ms=0 AND {tvis(c, uid, 't.')}
                         AND (t.status=0 OR (t.completed_at>=? AND t.completed_at<?) OR t.id IN ({','.join(str(int(x)) for x in linked) or '0'}))
                         ORDER BY t.id DESC""", (lid, lo, hi)).fetchall()
    build = git_build_for(c, rows)
    agent = g.user["kind"] == "agent"
    jobs = {}  # open task -> its running / waiting jobs ("waiting" wins)
    open_ids = [r["id"] for r in rows if r["status"] == 0]
    if open_ids:
        for j in c.execute(f"SELECT task_id, state FROM agent_jobs WHERE state IN ('running', 'waiting') AND task_id IN ({','.join(map(str, open_ids))})"):
            jobs[j["task_id"]] = "waiting" if j["state"] == "waiting" or jobs.get(j["task_id"]) == "waiting" else "running"
    moved = {x["id"] for x in st["in_progress"]}
    blocked = {x["id"]: x for x in st["blocked"]}

    def row(r, b, **x):
        d = {"id": r["id"], "title": r["title"], "due": r["due"], "build": b["state"] if b else "none", "version": b["version"] if b else None}
        if b and b["branches"] and r["status"] == 0:
            d["branches"] = (gb_untrusted(b) if agent else b)["branches"]
        return {**d, **x}
    out = {k: [] for k in DL_SECTIONS}
    for r in rows:
        b = build.get(r["id"])
        state = b["state"] if b else "none"
        vers = [gb_key(v) for v in ((b or {}).get("version"), ((b or {}).get("package") or {}).get("value")) if v]
        hit = next((tags[v] for v in vers if v in tags), None)
        if hit:
            out["released"].append(row(r, b, tag=hit))
        elif state == "main":
            out["in_main"].append(row(r, b))
        elif state == "released" or r["status"] != 0:
            pass
        elif r["delivery"] == "parked":  # 2.392.2 (#3365): held on purpose, with its reason
            out["stuck"].append(row(r, b, reason="parked", wait_note=r["delivery_note"] or None))
        elif jobs.get(r["id"]) == "waiting":
            out["stuck"].append(row(r, b, reason="job"))
        elif r["id"] in blocked:
            x = blocked[r["id"]]
            out["stuck"].append(row(r, b, reason=x["reason"], wait_note=x["wait_note"]))
        elif state == "branch" and r["id"] not in moved:
            out["stuck"].append(row(r, b, reason="branch"))
        elif r["id"] in moved or r["id"] in jobs or state == "branch" or r["delivery"] == "in_progress":
            out["in_progress"].append(row(r, b))
    out["completed"] = [{"id": x["id"], "title": x["title"], "completed_at": x["completed_at"]} for x in st["done"]]
    counts = {k: len(out[k]) for k in DL_SECTIONS}
    return {"list": {k: st["list"][k] for k in ("id", "name", "project")}, "since": lo, "until": hi, "repository": bool(git_conns_of_list(c, lid)),
            "counts": counts, **{k: out[k][:DELIVERY_MAX] for k in DL_SECTIONS}}


def delivery_markdown(d, lg):
    day = lambda v: short_day((parse_iso(v) - timedelta(seconds=1)).astimezone(TZ).date(), lg, year=True)  # noqa: E731  (until is exclusive)
    L = [f"# {tr('Delivery report: {0}', d['list']['name'], lg=lg)}", "", tr("Period: {0} – {1}", day(d["since"]), day(d["until"]), lg=lg)]
    why = {"job": tr("a job waits", lg=lg), "branch": tr("branch without a merge", lg=lg), "blocked": tr("waiting for another task", lg=lg),
           "parked": tr("parked", lg=lg)}

    def line(x):
        t = x["title"]
        if x.get("version") or x.get("tag"):
            t += f" ({x.get('version') or x['tag']})"
        if x.get("reason") == "parked":  # 2.392.2 (#3365)
            return f"{t} – {why['parked']}" + (f": {x['wait_note']}" if x.get("wait_note") else "")
        if x.get("wait_note"):
            return f"{t} – {tr('waiting on: {0}', x['wait_note'], lg=lg)}"
        return f"{t} – {why[x['reason']]}" if x.get("reason") in why else t
    for k, name in (("released", tr("Released", lg=lg)), ("in_main", tr("In main", lg=lg)), ("in_progress", tr("In progress", lg=lg)),
                    ("stuck", tr("Stuck", lg=lg)), ("completed", tr("Completed", lg=lg))):
        n = d["counts"][k]
        if n:
            L.extend(["", f"## {name} ({n})"])
            L.extend("- " + line(x) for x in d[k])
            if n > len(d[k]):
                L.append("- " + trn("and {0} more", "and {0} more", n - len(d[k]), lg=lg))
    if not any(d["counts"].values()):
        L.extend(["", tr("Nothing to report for this period.", lg=lg)])
    return "\n".join(L) + "\n"


@app.get("/api/v1/lists/<int:lid>/delivery-report")
@v1_view
def v1_delivery_report(lid):
    """?date=YYYY-MM-DD | ?since=ISO | neither (the last 24 hours), ?lang= -> the data + the Markdown text. A list with the lock: 409."""
    a = v1_args(("date", "since", "lang"))
    c = db()
    need_list(c, lid, write=False)
    if le2b_list_locked(c, lid):
        e = Denied(409, le2b_off())
        e.v1_name = "list_e2e"
        raise e
    lg = a.get("lang") or None
    if lg and lg != "en" and lg not in LANGS:
        raise BadInput(tr("Invalid value: {0}", "lang"))
    d = delivery_report(c, lid, g.user["id"], *dl_period(a))
    d["markdown"] = le2b_net(delivery_markdown(d, lg))
    return jsonify(d)


def delivery_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    """OpenAPI of GET /lists/{id}/delivery-report and GET /me/waiting (called from api.openapi)."""
    s, i = {"type": "string"}, {"type": "integer"}
    schemas["WaitingItem"] = {"type": "object", "properties": {
        "kind": {"type": "string", "enum": list(WAIT_KINDS)}, "id": {**i, "description": "Job, chat message, comment or task id, by kind"},
        "title": s, "at": nul("string"), "task_id": nul("integer"), "task_title": nul("string"), "list_id": nul("integer"), "list_name": nul("string"),
        "agent_id": i, "agent_name": s, "proposal": {"type": "boolean", "description": "job: a proposal of this person that is ready"},
        "source": {"type": "string", "enum": ["chat", "comment"], "description": "approval: where the card stands"},
        "gate": {"type": "string", "enum": list(GATE_ALL)}, "branch": nul("string"), "target": nul("string"),
        "reason": {"type": "string", "enum": ["waiting", "blocked"]}, "open_blockers": i, "why": {**s, "description": "irreversible: the reason of the mark; parked: the reason of parking (2.392.2)"}}}
    schemas["Waiting"] = {"type": "object", "properties": {
        "total": i, "counts": {"type": "object", "properties": {k: i for k in WAIT_KINDS}, "description": f"At most {WAIT_MAX} per kind"},
        "items": {"type": "array", "items": ref("WaitingItem")}}}
    paths["/me/waiting"] = {"get": op("What waits for a person: jobs, approvals, merge and deploy requests, reviews, blocked tasks, one-way steps without a yes", "Day plan",
                                      ok(ref("Waiting")) | errs("400", "404"),
                                      [q("user_id", "An agent: the person (required). A personal token: left out or its own id", {"type": "integer"})],
                                      desc="Pure data, only what the person sees and can settle; an agent gets only what is shared with it.")}
    item = {"type": "object", "properties": {
        "id": i, "title": s, "due": nul("string"), "build": {"type": "string", "enum": ["none", "branch", "main", "released"]}, "version": nul("string"),
        "tag": {**s, "description": "released: the tag of the period"}, "completed_at": s,
        "reason": {"type": "string", "enum": ["branch", "job", "waiting", "blocked", "parked"], "description": "stuck: why (parked: 2.392.2)"}, "wait_note": s,
        "branches": {"type": "array", "items": {"type": "object"}, "description": "Branches ahead of main; for agents marked untrusted"}}}
    schemas["DeliveryItem"] = item
    arr = {"type": "array", "items": ref("DeliveryItem")}
    schemas["DeliveryReport"] = {"type": "object", "properties": {
        "list": {"type": "object", "properties": {"id": i, "name": s, "project": {"type": "boolean"}}}, "since": s, "until": s,
        "repository": {"type": "boolean", "description": "False: no build states, the report still works"},
        "counts": {"type": "object", "properties": {k: i for k in DL_SECTIONS}}, **{k: arr for k in DL_SECTIONS},
        "markdown": {**s, "description": "A plain text with fixed headings; nothing is generated"}}}
    paths["/lists/{id}/delivery-report"] = {"get": op("The delivery report of a list: released, in main, in progress, stuck, completed", "Lists",
                                                      ok(ref("DeliveryReport")) | errs("400", "404", "409"),
                                                      [pid("id", "List id"), q("date", "A day in the time zone of the instance", {"type": "string", "format": "date"}),
                                                       q("since", "Instead of date: from this moment (default: the last 24 hours)", {"type": "string", "format": "date-time"}),
                                                       q("lang", "Language of the Markdown text (default: the token user's)", s)],
                                                      desc="Pure data plus a Markdown text. A scheduled job can post it; Kalmido pushes nothing itself. A list with the lock answers 409.")}
