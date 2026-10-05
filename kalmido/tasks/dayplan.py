"""Day planning ("Plan my day") and the evening review."""
from datetime import date, datetime, timedelta, timezone
from flask import jsonify, request

from ..core.config import app, PUBLIC_URL, TZ
from ..core.i18n import tr
from ..core.db import db, iso, local_now, parse_iso, uset, usettings
from ..accounts.session import me
from ..core.access import tvis, vis_sql
from ..tasks.validation import valid_hm, valid_plan_start
from ..personal.timetrack import BadInput
from ..notify.push import _wd_fail, notify, push_prio
from ..calendars.subscriptions import CAL_ON
from ..api.v1 import PRIO_NAMES, v1_args, v1_view


# ---- 2.10.0 (#440): day planning. "Plan my day" in Today: the built-in planner takes the day's timed events of the
# person's subscribed calendars, their already timed tasks and their working hours (user settings work_start / work_end,
# default 09:00-17:00) and puts their open tasks into the free slots (overdue / due today first, then deadlines, due date,
# priority, short ones first; a task without a duration counts DAYPLAN_DEFAULT_MIN minutes). mode "day" plans today's
# untimed tasks and lists the ones that do not fit as "nofit" (nothing is moved); mode "fill" ("Fill free time") only
# fills the remaining gaps from now on with tasks that are not planned for today yet. The plan is a preview: the web app
# applies it as one undo step. 2.11.0: applying sets ONLY the planned start (tasks.plan_start = "day THH:MM") and the
# duration; due date, due time and deadline are never changed. A task planned for the day counts as busy time
# ("planned" in fixed). With an agent the same structured input
# goes out as a proposal job (kind "dayplan", see docs/AGENTS.md); its answer shows in the same preview and only the person
# applies it. Evening review: done / still open / moved today + a short plan for the next working day, as a card in Today
# and (setting review_time, default off) one push at that time.
DAYPLAN_DEFAULT_MIN = 30
DAYPLAN_STEP = 5             # minutes: slots start on this grid
DAYPLAN_MAX_TASKS = 60       # candidates looked at / sent to an agent
DAYPLAN_MAX_EVENTS = 80


def _hm_min(v, default):
    try:
        h, m = (v or default).split(":")
        return max(0, min(1440, int(h) * 60 + int(m)))
    except (ValueError, AttributeError):
        h, m = default.split(":")
        return int(h) * 60 + int(m)


def _min_hm(m):
    m = max(0, min(1439, int(m)))
    return f"{m // 60:02d}:{m % 60:02d}"


def work_hours(s):
    """(start, end) minutes of the person's working day (settings work_start / work_end; end before start = the default)."""
    a, b = _hm_min(s.get("work_start"), "09:00"), _hm_min(s.get("work_end"), "17:00")
    return (a, b) if b > a else (540, 1020)


def next_workday(d):
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def dayplan_events(c, uid, day):
    """The day's events of uid's visible calendar subscriptions: [{title, start, end (local minutes), all_day}]."""
    if not CAL_ON:
        return []
    out = []
    ds = day.isoformat()
    for r in c.execute("""SELECT e.title, e.all_day, e.start, e.end FROM cal_events e JOIN cal_subs s ON s.id=e.sub_id
                          WHERE s.user_id=? AND s.visible=1 AND e.d1>=? AND e.d0<=? ORDER BY e.start LIMIT ?""",
                       (uid, ds, ds, DAYPLAN_MAX_EVENTS)):
        if r["all_day"]:
            out.append({"title": r["title"], "all_day": True, "start": None, "end": None})
            continue
        try:
            a = parse_iso(r["start"]).astimezone(TZ)
            b = parse_iso(r["end"]).astimezone(TZ)
        except (ValueError, TypeError):
            continue
        day0 = datetime(day.year, day.month, day.day, tzinfo=TZ)
        sa = max(0, int((a - day0).total_seconds() // 60))
        sb = min(1440, int((b - day0).total_seconds() // 60))
        if sb > sa:
            out.append({"title": r["title"], "all_day": False, "start": _min_hm(sa), "end": _min_hm(sb) if sb < 1440 else "24:00",
                        "s": sa, "e": sb})
    return out


def dayplan_mine_sql(uid):
    """SQL condition (alias t, l = its list) for the tasks that are uid's to do: assigned to them, to one of their groups,
    or nobody's in a list they own."""
    u = int(uid)
    return f"""(t.assignee_id={u} OR t.assignee_group_id IN (SELECT group_id FROM group_members WHERE user_id={u})
               OR (t.assignee_id IS NULL AND t.assignee_group_id IS NULL AND l.owner_id={u}))"""


def dayplan_tasks(c, uid, day):
    """Open tasks of uid in lists they see (not archived, not waiting, not blocked, no sample items)."""
    rows = c.execute(f"""SELECT t.*, l.name AS list_name, l.is_inbox AS list_inbox FROM tasks t JOIN lists l ON l.id=t.list_id
                         WHERE t.status=0 AND t.deleted_at IS NULL AND l.archived=0 AND t.list_id IN {vis_sql()}
                           AND {tvis(c, uid, 't.')} AND {dayplan_mine_sql(uid)} AND t.waiting_at IS NULL
                           AND t.id NOT IN (SELECT item_id FROM sample_items WHERE kind='task')
                           AND NOT EXISTS (SELECT 1 FROM task_deps d JOIN tasks b ON b.id=d.blocker_id
                                           WHERE d.task_id=t.id AND b.status=0 AND b.deleted_at IS NULL)
                         ORDER BY t.id""", (uid, uid)).fetchall()
    return rows


def _dp_task(r, s=None, e=None, reason=""):
    dur = r["duration"] or None
    d = {"task_id": r["id"], "title": r["title"], "list_id": r["list_id"], "list": tr("Inbox") if r["list_inbox"] else r["list_name"],
         "due": r["due"], "due_time": r["due_time"], "priority": PRIO_NAMES.get(r["priority"], "none"),
         "deadline": bool(r["deadline"]), "duration": dur or DAYPLAN_DEFAULT_MIN, "estimated": not dur}
    if s is not None:
        d.update(start=_min_hm(s), end=_min_hm(e) if e < 1440 else "24:00", reason=reason)
    return d


def dayplan_compute(c, uid, day, mode="day", now=None):
    """The built-in plan of uid for `day` (date): see the comment above. Pure: nothing is changed."""
    s = usettings(c, uid)
    now = now or local_now()
    w0, w1 = work_hours(s)
    start = w0
    if day == now.date():
        nm = now.hour * 60 + now.minute
        start = max(w0, -(-nm // DAYPLAN_STEP) * DAYPLAN_STEP)
    elif day < now.date():
        start = w1
    ds = day.isoformat()
    events = dayplan_events(c, uid, day)
    busy = [(e["s"], e["e"]) for e in events if not e["all_day"]]
    rows = dayplan_tasks(c, uid, day)
    fixed, today, later = [], [], []
    for r in rows:
        ps = r["plan_start"] if valid_plan_start(r["plan_start"]) else None
        if (ps and ps[:10] == ds) or (r["due"] == ds and r["due_time"]):
            a = _hm_min(ps[11:] if ps and ps[:10] == ds else r["due_time"], "00:00")
            b = min(1440, a + (r["duration"] or DAYPLAN_DEFAULT_MIN))
            fixed.append(_dp_task(r, a, b, "planned" if ps and ps[:10] == ds else "fixed"))
            busy.append((a, b))
        elif r["parent_id"] and not r["due"]:
            continue  # undated subtasks belong to their parent's work
        elif r["due"] and r["due"] <= ds:
            today.append(r)
        elif (r["due"] and r["due"] <= (day + timedelta(days=7)).isoformat()) or (not r["due"] and (r["priority"] >= 3 or r["pinned"])):
            later.append(r)

    def key(r):
        return (0 if r["deadline"] else 1, r["due"] or "9999", -(r["priority"] or 0), r["duration"] or DAYPLAN_DEFAULT_MIN, r["id"])
    today.sort(key=key)
    later.sort(key=key)
    # free intervals of [start, w1] minus busy
    busy.sort()
    free, cur = [], start
    for a, b in busy:
        if b <= cur:
            continue
        if a > cur:
            free.append([cur, min(a, w1)])
        cur = max(cur, b)
        if cur >= w1:
            break
    if cur < w1:
        free.append([cur, w1])
    free = [f for f in free if f[1] - f[0] >= DAYPLAN_STEP]

    def place(dur):
        for f in free:
            a = -(-f[0] // DAYPLAN_STEP) * DAYPLAN_STEP
            if f[1] - a >= dur:
                f[0] = a + dur
                return a
        return None
    plan, nofit = [], []
    cands = ([] if mode == "fill" else [(r, True) for r in today]) + [(r, False) for r in later]
    for r, is_today in cands[:DAYPLAN_MAX_TASKS]:
        dur = min(r["duration"] or DAYPLAN_DEFAULT_MIN, w1 - w0)
        a = place(dur)
        if a is not None:
            reason = ("overdue" if r["due"] < ds else "today") if is_today else ("deadline" if r["deadline"] else "due" if r["due"] else "priority")
            plan.append(_dp_task(r, a, a + dur, reason))
        elif is_today:  # 2.11.0: only listed ("does not fit today"), its dates stay as they are
            nofit.append(_dp_task(r))
    plan.sort(key=lambda x: x["start"])
    free_min = sum(max(0, f[1] - -(-f[0] // DAYPLAN_STEP) * DAYPLAN_STEP) for f in free)
    return {"date": ds, "mode": mode, "work": {"start": _min_hm(w0), "end": _min_hm(w1) if w1 < 1440 else "24:00"},
            "from": _min_hm(start) if start < 1440 else "24:00", "default_duration": DAYPLAN_DEFAULT_MIN,
            "events": [{k: e[k] for k in ("title", "all_day", "start", "end")} for e in events],
            "fixed": fixed, "plan": plan, "nofit": nofit, "free_min": free_min,
            "open_today": len(today), "candidates": len(today) + len(later)}


def dayplan_day(v):
    if v in (None, ""):
        return local_now().date()
    try:
        d = date.fromisoformat(str(v))
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "date")) from None
    if abs((d - local_now().date()).days) > 366:
        raise BadInput(tr("Invalid value: {0}", "date"))
    return d


def dayplan_mode(v):
    v = v or "day"
    if v not in ("day", "fill"):
        raise BadInput(tr("Invalid value: {0}", "mode"))
    return v


@app.get("/api/dayplan")
def dayplan_get():
    """?date=YYYY-MM-DD&mode=day|fill -> the built-in plan (a preview, nothing changes)."""
    c = db()
    return jsonify(dayplan_compute(c, me(), dayplan_day(request.args.get("date")), dayplan_mode(request.args.get("mode"))))


def _dp_open(r, ds):
    """A task the day plan may still place on day ds (not already timed or planned for it, no undated subtask)."""
    if r["due"] == ds and r["due_time"]:
        return False
    if (r["plan_start"] or "")[:10] == ds:
        return False
    return not (r["parent_id"] and not r["due"])


def dayplan_input(c, uid, day, mode):
    """The job input of a day plan proposal: exactly what the built-in planner looks at (and its plan as a hint)."""
    p = dayplan_compute(c, uid, day, mode)
    ds = day.isoformat()
    rows = [r for r in dayplan_tasks(c, uid, day) if _dp_open(r, ds)][:DAYPLAN_MAX_TASKS]
    tasks = [_dp_task(r) for r in rows]
    for t, r in zip(tasks, rows):
        t["notes"] = (r["content"] or "")[:500]
    return {"date": ds, "mode": mode, "now": local_now().strftime("%Y-%m-%dT%H:%M"), "work": p["work"], "from": p["from"],
            "default_duration": DAYPLAN_DEFAULT_MIN, "events": p["events"], "fixed": p["fixed"], "tasks": tasks,
            "builtin": {"plan": [{"task_id": x["task_id"], "start": x["start"], "duration": x["duration"]} for x in p["plan"]],
                        "nofit": [x["task_id"] for x in p["nofit"]]}}


def dayplan_validate(b, inp):
    """An agent's day plan {summary, items: [{task_id, start, duration?}], nofit: [{task_id, note?}]} -> normalized.
    2.11.0: a plan never moves dates; "defer" (2.10.0) is still accepted and read as nofit (its "to" is ignored)."""
    from ..agents.proposals import _p_int, _p_keys, _p_list, _p_str
    _p_keys(b, "", ("kind", "summary", "items", "nofit", "defer"))
    ids = {t["task_id"] for t in inp.get("tasks", [])}
    out, seen = {"items": []}, set()
    for i, t in enumerate(_p_list(b.get("items"), "items", DAYPLAN_MAX_TASKS)):
        w = f"items[{i}]"
        _p_keys(t, w, ("task_id", "start", "duration", "note"))
        tid = _p_int(t.get("task_id"), w + ".task_id")
        if tid not in ids or tid in seen:
            raise BadInput(tr("Invalid value: {0}", w + ".task_id"))
        seen.add(tid)
        st = t.get("start")
        if not isinstance(st, str) or not valid_hm(st):
            raise BadInput(tr("Invalid value: {0}", w + ".start"))
        dur = t.get("duration")
        dur = None if dur in (None, "") else _p_int(dur, w + ".duration", 5, 720)
        out["items"].append({"task_id": tid, "start": st, "duration": dur, "note": _p_str(t.get("note"), w + ".note", 300)})
    out = {"items": out["items"], "nofit": []}
    for name in ("nofit", "defer"):
        for i, t in enumerate(_p_list(b.get(name), name, DAYPLAN_MAX_TASKS)):
            w = f"{name}[{i}]"
            _p_keys(t, w, ("task_id", "to", "note"))
            tid = _p_int(t.get("task_id"), w + ".task_id")
            if tid not in ids or tid in seen:
                raise BadInput(tr("Invalid value: {0}", w + ".task_id"))
            seen.add(tid)
            out["nofit"].append({"task_id": tid, "note": _p_str(t.get("note"), w + ".note", 300)})
    if not out["items"] and not out["nofit"]:
        raise BadInput(tr("Missing field: {0}", "items"))
    out["items"].sort(key=lambda x: x["start"])
    return out


def dayplan_want(prop, inp, key, e):
    """The task change of one selected entry (key = index into items) of a day plan proposal: the planned start on the
    plan's day and the duration. 2.11.0: never due / due_time / deadline; nofit entries change nothing."""
    items = prop["items"]
    try:
        i = int(key.split(".")[0])
    except ValueError:
        return None, None
    if 0 <= i < len(items):
        it = items[i]
        dur = e.get("duration", it["duration"]) or next((t["duration"] for t in inp.get("tasks", []) if t["task_id"] == it["task_id"]),
                                                        DAYPLAN_DEFAULT_MIN)
        return it["task_id"], {"plan_start": f'{inp["date"]}T{e.get("time", it["start"])}', "duration": dur}
    return None, None


# ---- the evening review
def dayplan_review(c, uid, day):
    """{done, open, moved, tomorrow}: what uid completed on `day`, what is still open (due on or before it), what they moved
    away from it that day, and the built-in plan for the next working day (first entries)."""
    ds = day.isoformat()
    a = datetime(day.year, day.month, day.day, tzinfo=TZ).astimezone(timezone.utc)
    b = a + timedelta(days=1)
    lo, hi = iso(a), iso(b)
    done = [{"task_id": r["id"], "title": r["title"]} for r in c.execute(
        f"""SELECT t.id, t.title FROM tasks t WHERE t.completed_by=? AND t.status=2 AND t.deleted_at IS NULL
            AND t.completed_at>=? AND t.completed_at<? AND t.list_id IN {vis_sql()} ORDER BY t.completed_at LIMIT 50""",
        (uid, lo, hi, uid, uid))]
    rows = dayplan_tasks(c, uid, day)
    still = [{"task_id": r["id"], "title": r["title"], "due": r["due"], "overdue": r["due"] < ds}
             for r in rows if r["due"] and r["due"] <= ds][:50]
    moved = []
    for r in c.execute(f"""SELECT DISTINCT a.task_id, t.title, t.due FROM activity a JOIN tasks t ON t.id=a.task_id
                           WHERE a.user_id=? AND a.kind IN ('due', 'snooze') AND a.created_at>=? AND a.created_at<?
                             AND t.status=0 AND t.deleted_at IS NULL AND t.due>? AND t.list_id IN {vis_sql()} LIMIT 50""",
                       (uid, lo, hi, ds, uid, uid)):
        moved.append({"task_id": r["task_id"], "title": r["title"], "due": r["due"]})
    nd = next_workday(day)
    nxt = dayplan_compute(c, uid, nd, "day", now=datetime(nd.year, nd.month, nd.day, tzinfo=TZ))
    return {"date": ds, "done": done, "open": still, "moved": moved,
            "tomorrow": {"date": nd.isoformat(), "plan": nxt["plan"][:8], "events": len([e for e in nxt["events"] if not e["all_day"]]),
                         "count": len(nxt["plan"])}}


@app.get("/api/dayplan/review")
def dayplan_review_get():
    c = db()
    return jsonify(dayplan_review(c, me(), dayplan_day(request.args.get("date"))))


def dayplan_state(c, uid):
    """For /api/state: the working hours and when the review card / push is due."""
    s = usettings(c, uid)
    w0, w1 = work_hours(s)
    return {"work_start": _min_hm(w0), "work_end": _min_hm(w1) if w1 < 1440 else "24:00", "review_time": s.get("review_time") or "",
            "default_duration": DAYPLAN_DEFAULT_MIN}


def _wd_review(c, users, S, LG, now):
    """Watchdog: the evening review push at the person's review_time (once a day, only when there is something to say)."""
    for uid in users:
        try:
            s, lg = S[uid], LG[uid]
            rt = s.get("review_time") or ""
            today = now.date().isoformat()
            if not valid_hm(rt) or s.get("review_sent") == today or now.strftime("%H:%M") < rt:
                continue
            uset(c, uid, "review_sent", today)
            c.commit()
            r = dayplan_review(c, uid, now.date())
            if not (r["done"] or r["open"] or r["moved"]):
                continue
            parts = [tr("{0} done", len(r["done"]), lg=lg), tr("{0} open", len(r["open"]), lg=lg)]
            if r["moved"]:
                parts.append(tr("{0} moved", len(r["moved"]), lg=lg))
            msg = " · ".join(parts)
            if r["tomorrow"]["plan"]:
                msg += "\n" + tr("Tomorrow: {0}", ", ".join(x["title"] for x in r["tomorrow"]["plan"][:3]), lg=lg)
            notify(uid, tr("Daily review", lg=lg), msg, push_prio(s), f"{PUBLIC_URL}/#today/review", s=s, tag="review", ttl=12 * 3600)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "review of user", uid, e)


@app.get("/api/v1/dayplan")
@v1_view
def v1_dayplan():
    """The built-in day plan of the token's user (a preview; nothing changes)."""
    a = v1_args(("date", "mode"))
    c = db()
    return jsonify(dayplan_compute(c, me(), dayplan_day(a.get("date")), dayplan_mode(a.get("mode"))))


@app.get("/api/v1/dayplan/review")
@v1_view
def v1_dayplan_review():
    a = v1_args(("date",))
    c = db()
    return jsonify(dayplan_review(c, me(), dayplan_day(a.get("date"))))


def dayplan_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    D = "Day plan"
    slot = {"type": "object", "properties": {
        "task_id": {"type": "integer"}, "title": {"type": "string"}, "list_id": {"type": "integer"}, "list": {"type": "string"},
        "due": nul("string", format="date"), "due_time": nul("string"), "priority": {"type": "string"}, "deadline": {"type": "boolean"},
        "duration": {"type": "integer", "description": "Minutes (the task's duration, else the default)"},
        "estimated": {"type": "boolean", "description": "The task has no duration: the default was used"},
        "start": {"type": "string", "description": "HH:MM"}, "end": {"type": "string", "description": "HH:MM"},
        "reason": {"type": "string", "enum": ["fixed", "planned", "overdue", "today", "deadline", "due", "priority"],
                   "description": "fixed = due at a time that day, planned = already planned for that day (plan_start)"}}}
    schemas["DayPlanSlot"] = slot
    schemas["DayPlan"] = {"type": "object", "properties": {
        "date": {"type": "string", "format": "date"}, "mode": {"type": "string", "enum": ["day", "fill"]},
        "work": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}},
        "from": {"type": "string", "description": "First minute that is planned (now on today)"},
        "default_duration": {"type": "integer"},
        "events": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "all_day": {"type": "boolean"},
                                                                               "start": nul("string"), "end": nul("string")}}},
        "fixed": {"type": "array", "items": ref("DayPlanSlot")}, "plan": {"type": "array", "items": ref("DayPlanSlot")},
        "nofit": {"type": "array", "items": ref("DayPlanSlot"), "description": "2.11.0: open tasks of the day that do not fit any more; "
                  "listed only, their dates are not changed"}, "free_min": {"type": "integer"},
        "open_today": {"type": "integer"}, "candidates": {"type": "integer"}}}
    lst = {"type": "array", "items": {"type": "object", "properties": {"task_id": {"type": "integer"}, "title": {"type": "string"},
                                                                       "due": nul("string", format="date")}}}
    schemas["DayReview"] = {"type": "object", "properties": {
        "date": {"type": "string", "format": "date"}, "done": lst, "open": lst, "moved": lst,
        "tomorrow": {"type": "object", "properties": {"date": {"type": "string", "format": "date"}, "count": {"type": "integer"},
                                                      "events": {"type": "integer"}, "plan": {"type": "array", "items": ref("DayPlanSlot")}}}}}
    dq = q("date", "The day (YYYY-MM-DD, default today)", {"type": "string", "format": "date"})
    paths["/dayplan"] = {"get": op("The built-in day plan (preview)", D, ok(ref("DayPlan")) | errs("400"),
                                   [dq, q("mode", "day = plan the day's tasks, fill = only fill free time with other tasks",
                                          {"type": "string", "enum": ["day", "fill"]})],
                                   desc="Free slots between the day's calendar events and timed tasks within the working hours, "
                                        "filled with open tasks (overdue / today first, then deadlines, due date, priority). "
                                        "Nothing changes: apply it with PATCH /tasks/{id} (plan_start = date + 'T' + start, "
                                        "duration). Planning never changes due, due_time or deadline.")}
    paths["/dayplan/review"] = {"get": op("The daily review: done, open, moved today; a plan for the next working day", D,
                                          ok(ref("DayReview")) | errs("400"), [dq])}
