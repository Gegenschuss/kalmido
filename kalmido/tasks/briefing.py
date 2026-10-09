"""2.34.0 (#264): the morning briefing per person -- what is due today / overdue, what is blocked, what changed since the
last briefing (or since 18:00 yesterday), what has been lying idle. Pure data: the app shows it as the first block of
Today (counts + "New since yesterday" / "Blocked", folded once read that day), an optional push at a chosen time
(setting brief_time, default off) carries only the numbers, and agents read it through the API / MCP (read_briefing)
for a person who may chat with them -- then only from the lists that person shares with the agent. Kalmido itself
writes no prose here; an agent that wants a friendlier text formulates it from these data (planned by the scheduled
jobs, see agents.schedules)."""
import json
from datetime import datetime, timedelta

from flask import g, jsonify, request

from ..core.config import app, PUBLIC_URL, TZ
from ..core.i18n import tr, trn
from ..core.db import db, inbox_default, iso, local_now, now_utc, parse_iso, uset, usettings
from ..core.access import Denied, list_role, tvis, vis_sql
from ..accounts.session import me
from ..tasks.validation import valid_hm
from ..personal.timetrack import BadInput
from ..notify.push import _wd_fail, notify, push_prio
from ..api.v1 import v1_args, v1_view

BRIEF_LIST_MAX = 15        # rows per section (the counts are complete)
BRIEF_SINCE_MAX_DAYS = 7   # "since the last briefing" never reaches further back than this
BRIEF_EVENING = 18         # without a read briefing: changes since this hour of yesterday
# what counts as a change "since yesterday" (activity kinds -> the group shown)
BRIEF_KINDS = {"assign": "assigned", "complete": "status", "reopen": "status", "wont": "status",
               "due": "due", "snooze": "due", "dep_shift": "due"}


def _lname(r):
    return tr("Inbox") if r["is_inbox"] and inbox_default(r["list_name"]) else r["list_name"]


def brief_lists(c, uid, agent_id=None):
    """The (not archived) list ids the briefing of uid draws from: what uid sees; with agent_id only the lists that are
    also shared with that agent (its token's list limit and the agent's own list choice included)."""
    lids = [r[0] for r in c.execute(f"SELECT id FROM lists WHERE archived=0 AND id IN {vis_sql()}", (uid, uid))]
    if agent_id is None:
        return lids
    from ..agents.core import agent_row
    a = agent_row(c, agent_id)
    if a is None:
        return []
    allowed = None
    if "list_ids" in a.keys() and (a["list_ids"] or "").strip():
        allowed = {int(x) for x in a["list_ids"].split(",") if x.strip().isdigit()}
    return [x for x in lids if list_role(c, x, agent_id) and (allowed is None or x in allowed)]


def brief_since(s, now=None):
    """UTC datetime from which changes count: the moment of the last briefing read on an earlier day (stored in brief_read),
    else 18:00 yesterday; never more than BRIEF_SINCE_MAX_DAYS back."""
    now = now or local_now()
    floor = now - timedelta(days=BRIEF_SINCE_MAX_DAYS)
    evening = datetime(now.year, now.month, now.day, BRIEF_EVENING, tzinfo=TZ) - timedelta(days=1)
    st = brief_state(s)
    v = st.get("prev") if st.get("day") == now.date().isoformat() else st.get("at")
    try:
        t = parse_iso(v) if v else None
    except (TypeError, ValueError):
        t = None
    if t is None or t.tzinfo is None or t > now:
        t = evening
    return max(t, floor)


def brief_state(s):
    try:
        st = json.loads(s.get("brief_read") or "{}")
    except ValueError:
        st = {}
    return st if isinstance(st, dict) else {}


def _task_row(r, extra=None):
    d = {"id": r["id"], "title": r["title"], "list_id": r["list_id"], "list_name": _lname(r), "due": r["due"],
         "due_time": r["due_time"], "priority": r["priority"], "assignee_id": r["assignee_id"]}
    if extra:
        d.update(extra)
    return d


def briefing_data(c, uid, *, agent_id=None, since=None):
    """The briefing of person uid (see the module text). agent_id: only lists shared with that agent. since: a UTC datetime
    overriding the start of "changed". Works with and without a request (the watchdog's push, scheduled jobs)."""
    now = local_now()
    today = now.date().isoformat()
    s = usettings(c, uid)
    since_dt = since or brief_since(s, now)
    since_iso = iso(since_dt)
    lids = brief_lists(c, uid, agent_id)
    st = brief_state(s)
    out = {"date": today, "since": since_iso, "read": st.get("day") == today, "read_at": st.get("at") if st.get("day") == today else None,
           "counts": {"today": 0, "overdue": 0, "blocked": 0, "changed": 0, "stale": 0},
           "today": [], "blocked": [], "changed": [], "stale": []}
    if not lids:
        return out
    ql = ",".join(str(int(x)) for x in lids)
    vis = tvis(c, uid, "t.")
    if agent_id is not None:
        vis = f"{vis} AND {tvis(c, agent_id, 't.')}"
    mine = "((l.owner_id=? AND (t.assignee_id IS NULL OR t.assignee_id=?)) OR t.assignee_id=?)"
    base = f"""FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.status=0 AND t.deleted_at IS NULL AND t.list_id IN ({ql})
               AND t.id NOT IN (SELECT item_id FROM sample_items WHERE kind='task') AND {vis}"""
    cols = "t.id, t.title, t.list_id, t.due, t.due_time, t.priority, t.assignee_id, l.name AS list_name, l.is_inbox"
    # due today / overdue (main tasks, mine: like the daily digest)
    rows = c.execute(f"""SELECT {cols} {base} AND t.parent_id IS NULL AND t.due IS NOT NULL AND substr(t.due,1,10)<=? AND {mine}
                         ORDER BY t.due, t.due_time IS NULL, t.due_time, t.priority DESC, t.id""", (today, uid, uid, uid)).fetchall()
    out["counts"]["today"] = sum(1 for r in rows if r["due"][:10] == today)
    out["counts"]["overdue"] = sum(1 for r in rows if r["due"][:10] < today)
    out["today"] = [_task_row(r, {"overdue": r["due"][:10] < today}) for r in rows[:BRIEF_LIST_MAX]]
    # blocked: mine and waiting on someone outside, or on an open task (dependencies count between project lists)
    rows = c.execute(f"""SELECT {cols}, t.waiting_at, t.wait_note, t.wait_until,
                           (SELECT COUNT(*) FROM task_deps d JOIN tasks b ON b.id=d.blocker_id WHERE d.task_id=t.id AND b.status=0
                              AND b.deleted_at IS NULL AND b.list_id IN (SELECT id FROM lists WHERE kind='project')) AS open_blockers
                         {base} AND {mine} AND (t.waiting_at IS NOT NULL OR EXISTS (SELECT 1 FROM task_deps d JOIN tasks b ON b.id=d.blocker_id
                              WHERE d.task_id=t.id AND b.status=0 AND b.deleted_at IS NULL AND b.list_id IN (SELECT id FROM lists WHERE kind='project')))
                         ORDER BY t.due IS NULL, t.due, t.id""", (uid, uid, uid)).fetchall()
    rows = [r for r in rows if r["waiting_at"] or r["open_blockers"]]
    out["counts"]["blocked"] = len(rows)
    out["blocked"] = [_task_row(r, {"reason": "waiting" if r["waiting_at"] else "blocked", "wait_note": (r["wait_note"] or "") if r["waiting_at"] else "",
                                    "wait_until": r["wait_until"] if r["waiting_at"] else None, "open_blockers": r["open_blockers"]})
                      for r in rows[:BRIEF_LIST_MAX]]
    out["changed"], out["counts"]["changed"] = _changes(c, uid, ql, vis, since_iso)
    # lying idle (#266, module tasks.stale): mine only, so a big shared list does not fill the briefing
    try:
        from ..tasks.stale import stale_tasks
    except ImportError:  # pragma: no cover - the stale module ships with 2.34.0
        stale_tasks = None
    if stale_tasks is not None:
        owners = {r[0]: r[1] for r in c.execute(f"SELECT id, owner_id FROM lists WHERE id IN ({ql})")}
        items = [x for x in stale_tasks(c, uid, lids=lids, limit=200)
                 if x.get("assignee_id") == uid or (not x.get("assignee_id") and owners.get(x["list_id"]) == uid)]
        if agent_id is not None:
            items = [x for x in items if _agent_sees(c, agent_id, x["id"])]
        out["counts"]["stale"] = len(items)
        out["stale"] = [{k: x.get(k) for k in ("id", "title", "list_id", "list_name", "idle_days", "reason", "due", "wait_note")}
                        for x in items[:BRIEF_LIST_MAX]]
    return out


def _agent_sees(c, aid, tid):
    from ..core.access import task_visible
    return task_visible(c, tid, aid)


def _changes(c, uid, ql, vis, since_iso):
    """Changes by others since since_iso on the tasks that concern uid (assigned to uid, created by uid, commented by uid, or
    without assignee in uid's own lists): newly assigned, comments, status changes, date changes. One row per task, newest
    first: {id, title, list_id, list_name, kinds, by: [{id, name}], at}; plus the number of such tasks."""
    from ..collab.comments import user_names
    concern = f"""(t.assignee_id=? OR t.created_by=? OR (t.assignee_id IS NULL AND l.owner_id=?)
                   OR t.id IN (SELECT task_id FROM comments WHERE user_id=? AND deleted_at IS NULL))"""
    head = f"""FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.deleted_at IS NULL AND t.list_id IN ({ql}) AND {vis}"""
    kinds = ",".join(f"'{k}'" for k in BRIEF_KINDS)
    acts = c.execute(f"""SELECT a.task_id, a.user_id, a.kind, a.data, a.created_at {head.replace('FROM tasks t', 'FROM activity a JOIN tasks t ON t.id=a.task_id')}
                         AND a.created_at>? AND a.kind IN ({kinds}) AND a.user_id IS NOT NULL AND a.user_id!=? AND {concern}""",
                     (since_iso, uid, uid, uid, uid, uid)).fetchall()
    # comments only where uid sees the task fully (a participant's context tasks have no comments for them)
    cvis = tvis(c, uid, "t.", write=True)
    cms = c.execute(f"""SELECT cm.task_id, cm.user_id, cm.created_at {head.replace('FROM tasks t', 'FROM comments cm JOIN tasks t ON t.id=cm.task_id')}
                        AND {cvis} AND cm.created_at>? AND cm.deleted_at IS NULL AND cm.user_id IS NOT NULL AND cm.user_id!=? AND {concern}""",
                    (since_iso, uid, uid, uid, uid, uid)).fetchall()
    news = c.execute(f"""SELECT t.id AS task_id, t.created_by AS user_id, t.created_at {head} AND t.status=0 AND t.assignee_id=?
                         AND t.created_at>? AND t.created_by IS NOT NULL AND t.created_by!=?""", (uid, since_iso, uid)).fetchall()
    per = {}

    def add(tid, who, kind, at):
        x = per.setdefault(tid, {"kinds": [], "by": [], "at": ""})
        if kind not in x["kinds"]:
            x["kinds"].append(kind)
        if who and who not in x["by"]:
            x["by"].append(who)
        x["at"] = max(x["at"], at or "")
    for r in acts:
        k = BRIEF_KINDS[r["kind"]]
        if k == "assigned":
            try:
                to = json.loads(r["data"] or "{}").get("to")
            except ValueError:
                to = None
            if to != uid:
                continue
        add(r["task_id"], r["user_id"], k, r["created_at"])
    for r in cms:
        add(r["task_id"], r["user_id"], "comment", r["created_at"])
    for r in news:
        add(r["task_id"], r["user_id"], "assigned", r["created_at"])
    if not per:
        return [], 0
    ids = sorted(per, key=lambda t: per[t]["at"], reverse=True)
    top = ids[:BRIEF_LIST_MAX]
    q = ",".join(str(int(x)) for x in top)
    info = {r["id"]: r for r in c.execute(f"""SELECT t.id, t.title, t.list_id, t.status, t.due, l.name AS list_name, l.is_inbox
                                              FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id IN ({q})""")}
    names = user_names(c, [u for t in top for u in per[t]["by"]])
    out = []
    for tid in top:
        r = info.get(tid)
        if not r:
            continue
        x = per[tid]
        out.append({"id": tid, "title": r["title"], "list_id": r["list_id"], "list_name": _lname(r), "status": r["status"],
                    "due": r["due"], "kinds": x["kinds"], "by": [{"id": u, "name": names.get(u, "")} for u in x["by"]], "at": x["at"]})
    return out, len(per)


def brief_line(d, lg=None):
    """The push text: only numbers ("5 due today, 2 blocked, 3 new since yesterday"); '' when there is nothing to say."""
    n, parts = d["counts"], []
    if n["today"]:
        parts.append(trn("{0} due today", "{0} due today", n["today"], lg=lg))
    if n["overdue"]:
        parts.append(trn("{0} overdue", "{0} overdue", n["overdue"], lg=lg))
    if n["blocked"]:
        parts.append(trn("{0} blocked", "{0} blocked", n["blocked"], lg=lg))
    if n["changed"]:
        parts.append(trn("{0} new since yesterday", "{0} new since yesterday", n["changed"], lg=lg))
    if n["stale"]:
        parts.append(trn("{0} lying idle", "{0} lying idle", n["stale"], lg=lg))
    return ", ".join(parts)


def _need_person():
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(404)


@app.get("/api/briefing")
def briefing_get():
    """The briefing of the signed-in person (the block "Briefing" on Today)."""
    _need_person()
    return jsonify(briefing_data(db(), me()))


@app.post("/api/briefing/read")
def briefing_read():
    """{read?: true|false} -- marks today's briefing read (folds it for the day on every device; the next briefing counts
    changes from now). false: unread again (the start of "changed" stays as it was)."""
    _need_person()
    b = request.get_json(silent=True) or {}
    if not isinstance(b, dict) or set(b) - {"read"} or not isinstance(b.get("read", True), bool):
        raise BadInput(tr("Invalid value: {0}", "read"))
    c, uid = db(), me()
    s = usettings(c, uid)
    now = local_now()
    today, st = now.date().isoformat(), brief_state(s)
    if b.get("read", True):
        if st.get("day") != today:  # the first read today: the start of today's "changed" is kept for re-reading
            st = {"day": today, "at": iso(now_utc()), "prev": iso(brief_since(s, now))}
    elif st.get("day") == today:
        st = {"day": "", "at": st.get("prev") or "", "prev": ""}
    uset(c, uid, "brief_read", json.dumps(st, separators=(",", ":")))
    c.commit()
    return jsonify(briefing_data(c, uid))


@app.get("/api/v1/briefing")
@v1_view
def v1_briefing():
    """2.34.0 (#264): the briefing of a person. A personal token: its own (user_id left out or its own id). An agent:
    user_id = a person who may chat with it (shares a list with it); only the lists that person shares with the agent
    count. Reading it marks nothing read."""
    from ..agents.core import agent_shares, is_agent
    a = v1_args(("user_id", "since"))
    c, uid = db(), me()
    since = None
    if a.get("since"):
        try:
            since = parse_iso(a["since"].replace("Z", "+00:00"))
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "since")) from None
        if since.tzinfo is None:
            since = since.replace(tzinfo=TZ)
        since = max(since, now_utc() - timedelta(days=BRIEF_SINCE_MAX_DAYS))
    raw = a.get("user_id")
    if is_agent(g.user):
        if not raw or not str(raw).isdigit():
            raise BadInput(tr("Invalid value: {0}", "user_id"))
        pid = int(raw)
        u = c.execute("SELECT * FROM users WHERE id=? AND disabled=0", (pid,)).fetchone()
        if not u or is_agent(u) or not agent_shares(c, uid, pid):
            raise Denied(404)
        return jsonify(briefing_data(c, pid, agent_id=uid, since=since))
    if raw and str(raw) != str(uid):
        raise Denied(404)
    return jsonify(briefing_data(c, uid, since=since))


def _wd_briefing(c, users, S, LG, now):
    """Watchdog: the morning briefing push at the person's brief_time (once a day, only with something to say)."""
    from ..agents.core import agent_ids
    ag = agent_ids(c)
    today = now.date().isoformat()
    for uid in users:
        if uid in ag:
            continue
        try:
            s, lg = S[uid], LG[uid]
            bt = s.get("brief_time") or ""
            if not valid_hm(bt) or s.get("brief_sent") == today or now.strftime("%H:%M") < bt:
                continue
            uset(c, uid, "brief_sent", today)
            c.commit()
            line = brief_line(briefing_data(c, uid), lg)
            if line:
                notify(uid, tr("Your briefing", lg=lg), line, push_prio(s), f"{PUBLIC_URL}/#today", s=s, tag="briefing", ttl=12 * 3600)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "briefing of user", uid, e)


def briefing_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    """OpenAPI of GET /briefing (called from api.openapi)."""
    trow = {"type": "object", "properties": {
        "id": {"type": "integer"}, "title": {"type": "string"}, "list_id": {"type": "integer"}, "list_name": {"type": "string"},
        "due": nul("string"), "due_time": nul("string"), "priority": {"type": "integer"}, "assignee_id": nul("integer"),
        "overdue": {"type": "boolean"}, "reason": {"type": "string", "enum": ["waiting", "blocked"]}, "wait_note": {"type": "string"},
        "wait_until": nul("string", format="date"), "open_blockers": {"type": "integer"}}}
    schemas["BriefingTask"] = trow
    schemas["Briefing"] = {"type": "object", "properties": {
        "date": {"type": "string", "format": "date"},
        "since": {"type": "string", "description": "UTC; changes after this moment count (the person's last briefing read, else 18:00 yesterday)"},
        "read": {"type": "boolean", "description": "The person marked today's briefing read in the app"}, "read_at": nul("string"),
        "counts": {"type": "object", "properties": {k: {"type": "integer"} for k in ("today", "overdue", "blocked", "changed", "stale")}},
        "today": {"type": "array", "items": ref("BriefingTask"), "description": "Due today or overdue (main tasks: assigned to the person, "
                  "or without assignee in their own lists); at most 15, counts are complete"},
        "blocked": {"type": "array", "items": ref("BriefingTask"), "description": "Waiting on someone outside (reason waiting) or on an open task (blocked)"},
        "changed": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "integer"}, "title": {"type": "string"}, "list_id": {"type": "integer"}, "list_name": {"type": "string"},
            "status": {"type": "integer"}, "due": nul("string"), "kinds": {"type": "array", "items": {"type": "string", "enum": ["assigned", "comment", "status", "due"]}},
            "by": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}}},
            "at": {"type": "string"}}}, "description": "Changes by others since `since` on tasks that concern the person, newest first"},
        "stale": {"type": "array", "items": {"type": "object"}, "description": "The person's tasks lying idle (see GET /stale)"}}}
    paths["/briefing"] = {"get": op("The morning briefing of a person: due today, blocked, changed since the last briefing, lying idle", "Day plan",
                                    ok(ref("Briefing")) | errs("400", "404"),
                                    [q("user_id", "Agents: the person (who may chat with the agent; only the lists they share with it count). "
                                                  "Personal tokens: leave out (own briefing)", {"type": "integer"}),
                                     q("since", "Count changes after this moment instead (ISO 8601, at most 7 days back)", {"type": "string"})],
                                    desc="Pure data: no text is generated. Reading it marks nothing read.")}
