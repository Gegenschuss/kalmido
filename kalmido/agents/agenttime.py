"""2.51.0 (#1353): an agent checks time tracking and proposes entries from calendar events -- a person confirms.

GET /api/v1/time/check (scope time): implausible entries of a person (a day over ATM_DAY_MAX_H hours, one entry over
ATM_ENTRY_MAX_H hours, overlapping entries, entries on a weekend day without an event or booking) and past events / firm
bookings (shoot days) without any tracked time. GET /api/v1/time/from-events (scopes time + calendar): past events of the
period without a matching entry, as ready rows for a proposal. Whose times: the token's user, or for an agent a person who
may chat with it (agent_shares, like the time gaps); only entries and tasks of lists BOTH see, events only of calendars both
see, bookings only of the agent's own workspace (row-level security). The agent never writes time itself: it sends a
proposal of kind time (POST /api/v1/agent/proposals/time); the person reviews it (times, note editable) and "Apply" creates
the entries as that person, one undo step. Kalmido never runs a model itself."""
import json
from datetime import date, datetime, timedelta, timezone

from flask import g, jsonify, request

from ..core.config import app, TZ
from ..core.pg import insert_id
from ..core.i18n import tr
from ..core.db import bump, db, iso, local_day, local_now, now_utc, parse_iso
from ..core.access import Denied, list_role, need_feat, need_time, task_visible
from ..accounts.session import me
from ..personal.timetrack import BadInput, local_bounds, mt_time_on, time_target
from ..api.v1 import v1_args, v1_err, v1_feature, v1_json, v1_view

ATM_DAY_MAX_H = 12            # tracked hours of one day above this: implausible
ATM_ENTRY_MAX_H = 10          # one entry longer than this: implausible
ATM_DAYS, ATM_DAYS_MAX = 14, 62
ATM_ITEMS = 200               # findings / suggestions per answer
ATM_PROP_MAX = 60             # entries of one time proposal
ATM_NOTE_MAX = 500
ATM_WEEKEND = (5, 6)          # Saturday, Sunday


# ---------------------------------------------------------------- whose times, which period
def atm_person(c, a):
    """(person id, viewer id) of a request: user_id = a person who may chat with the agent (else 404); default the token user."""
    from ..agents.core import agent_shares, is_agent
    uid = me()
    pid = uid
    if a.get("user_id") not in (None, ""):
        try:
            pid = int(a["user_id"])
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "user_id")) from None
        if pid != uid:
            u = c.execute("SELECT kind, disabled FROM users WHERE id=?", (pid,)).fetchone()
            if not is_agent(g.user) or not u or u["kind"] == "agent" or u["disabled"] or not agent_shares(c, uid, pid):
                raise Denied(404)
    elif is_agent(g.user):
        from ..agents.admin import agent_owner
        o = agent_owner(c, uid)  # a personal agent works for its owner
        if o is None:
            raise BadInput(tr("Missing field: {0}", "user_id"))
        u = c.execute("SELECT kind, disabled FROM users WHERE id=?", (o,)).fetchone()
        if not u or u["kind"] == "agent" or u["disabled"]:
            raise Denied(404)
        pid = o
    return pid, uid


def atm_period(a, back=ATM_DAYS):
    """from / to (local days, inclusive) of a request: default the last `back` days up to today."""
    try:
        to = date.fromisoformat(a["to"]) if a.get("to") else local_now().date()
        frm = date.fromisoformat(a["from"]) if a.get("from") else to - timedelta(days=back - 1)
    except ValueError:
        raise BadInput(tr("Invalid date or time")) from None
    if to < frm or (to - frm).days >= ATM_DAYS_MAX:
        raise BadInput(tr("Invalid value: {0}", "to"))
    return frm, to


def _both_lists(c, pid, viewer, lid):
    return bool(lid) and bool(list_role(c, lid, pid)) and (viewer == pid or bool(list_role(c, lid, viewer)))


def _entries(c, pid, viewer, frm, to):
    """The person's finished entries in [frm, to] that the viewer may see (lists both see; list-less ones only for the person)."""
    lo, hi = local_bounds(frm, to)
    rows = c.execute("""SELECT e.id, e.task_id, e.list_id, e.task_title, e.start, e."end", e.seconds, e.note FROM time_entries e
                        WHERE e.user_id=? AND e.start>=? AND e.start<? AND e."end" IS NOT NULL ORDER BY e.start, e.id""",
                     (pid, lo, hi)).fetchall()
    out, cache = [], {}
    for r in rows:
        lid = r["list_id"]
        if lid is None:
            if viewer != pid:
                continue
        else:
            if lid not in cache:
                cache[lid] = _both_lists(c, pid, viewer, lid)
            if not cache[lid]:
                continue
            if viewer != pid and r["task_id"] and not task_visible(c, r["task_id"], viewer):
                continue  # a participant list: only the tasks the viewer may see
        s, e = parse_iso(r["start"]), parse_iso(r["end"])
        out.append({"id": r["id"], "task_id": r["task_id"], "list_id": lid, "title": r["task_title"] or "", "note": r["note"] or "",
                    "start": r["start"], "end": r["end"], "seconds": r["seconds"], "s": s, "e": e, "day": local_day(r["start"])})
    return out


def _events(c, pid, viewer, frm, to):
    """Past, not cancelled occurrences of events in calendars the person sees and (for an agent) the agent sees too."""
    from ..events.model import ev_range, my_cal_ids
    if not c.execute("SELECT 1 FROM ev_cals LIMIT 1").fetchone():
        return []
    mine = set(my_cal_ids(c, viewer)) if viewer != pid else None
    now = now_utc()
    out = []
    for o in ev_range(c, pid, frm, to):
        if o["status"] == "cancelled" or o["cal"] is None or (mine is not None and o["cal"] not in mine):
            continue
        if o["all_day"]:
            d0, d1 = date.fromisoformat(o["start"]), date.fromisoformat(o["end"]) - timedelta(days=1)
            s = datetime(d0.year, d0.month, d0.day, tzinfo=TZ).astimezone(timezone.utc)
            e = datetime(d1.year, d1.month, d1.day, tzinfo=TZ).astimezone(timezone.utc) + timedelta(days=1)
        else:
            s = datetime.fromisoformat(o["start"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(o["end"].replace("Z", "+00:00"))
        if e > now or s.astimezone(TZ).date() < frm or s.astimezone(TZ).date() > to:
            continue
        out.append({**o, "s": s, "e": e})
    return out


def _bookings(c, pid, frm, to):
    """The person's firm bookings (disposition) in the period -- only those the token's context reaches (its workspace)."""
    rows = c.execute("""SELECT id, title, start, "end", list_id FROM hub_bookings WHERE resource_kind='user' AND resource_id=?
                        AND status='firm' AND deleted_at IS NULL AND start<=? AND "end">=? ORDER BY start, id""",
                     (pid, to.isoformat() + "T99", frm.isoformat())).fetchall()
    today = local_now().date()
    out = []
    for r in rows:
        d0, d1 = date.fromisoformat(r["start"][:10]), date.fromisoformat(r["end"][:10])
        d = max(d0, frm)
        while d <= min(d1, to, today - timedelta(days=1)):
            out.append({"id": r["id"], "title": r["title"], "date": d, "list_id": r["list_id"]})
            d += timedelta(days=1)
    return out


def _covered(entries, s, e):
    return any(x["s"] < e and x["e"] > s for x in entries)


def _hm(dt):
    return dt.astimezone(TZ).strftime("%H:%M")


# ---------------------------------------------------------------- the check
def atm_check(c, pid, viewer, frm, to, events=True):
    """{user_id, from, to, limits, issues: [...], events_checked} -- see the module docstring."""
    ents = _entries(c, pid, viewer, frm, to)
    issues = []
    per_day = {}
    for x in ents:
        per_day.setdefault(x["day"], []).append(x)
        h = x["seconds"] / 3600
        if h > ATM_ENTRY_MAX_H:
            issues.append({"kind": "entry_long", "date": x["day"].isoformat(), "hours": round(h, 2), "entry_ids": [x["id"]],
                           "title": x["title"]})
    for d, xs in sorted(per_day.items()):
        h = sum(x["seconds"] for x in xs) / 3600
        if h > ATM_DAY_MAX_H:
            issues.append({"kind": "day_long", "date": d.isoformat(), "hours": round(h, 2), "entry_ids": [x["id"] for x in xs]})
        xs = sorted(xs, key=lambda x: x["s"])
        for i, a in enumerate(xs):
            for b in xs[i + 1:]:
                if b["s"] >= a["e"]:
                    break
                issues.append({"kind": "overlap", "date": d.isoformat(), "entry_ids": [a["id"], b["id"]],
                               "title": f"{a['title']} / {b['title']}"})
    evs = _events(c, pid, viewer, frm, to) if events else []
    bks = _bookings(c, pid, frm, to)
    busy_days = {e["s"].astimezone(TZ).date() for e in evs} | {b["date"] for b in bks}
    for d, xs in sorted(per_day.items()):
        if d.weekday() in ATM_WEEKEND and d not in busy_days:
            issues.append({"kind": "weekend", "date": d.isoformat(), "hours": round(sum(x["seconds"] for x in xs) / 3600, 2),
                           "entry_ids": [x["id"] for x in xs]})
    for e in evs:
        if not _covered(ents, e["s"], e["e"]):
            issues.append({"kind": "event_no_time", "date": e["s"].astimezone(TZ).date().isoformat(), "event_id": e["eid"],
                           "title": e["title"], "all_day": e["all_day"], "task_id": e["task_id"]})
    for b in bks:
        if b["date"] not in per_day:
            issues.append({"kind": "booking_no_time", "date": b["date"].isoformat(), "booking_id": b["id"], "title": b["title"],
                           "list_id": b["list_id"]})
    issues.sort(key=lambda x: (x["date"], x["kind"]))
    return {"user_id": pid, "from": frm.isoformat(), "to": to.isoformat(), "events_checked": bool(events),
            "limits": {"day_max_hours": ATM_DAY_MAX_H, "entry_max_hours": ATM_ENTRY_MAX_H, "weekend_days": [6, 7]},
            "issues": issues[:ATM_ITEMS], "more": len(issues) > ATM_ITEMS}


def atm_from_events(c, pid, viewer, frm, to):
    """Past events without a matching entry -> rows ready for a time proposal (task / list where the person tracks time)."""
    ents = _entries(c, pid, viewer, frm, to)
    out = []
    for e in _events(c, pid, viewer, frm, to):
        if _covered(ents, e["s"], e["e"]):
            continue
        tid, lid = e["task_id"], None
        if tid:
            t = c.execute("SELECT list_id FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone()
            lid = t["list_id"] if t else None
            if not lid or not mt_time_on(c, lid) or not task_visible(c, tid, pid) or (viewer != pid and not task_visible(c, tid, viewer)):
                tid, lid = None, None
        d = e["s"].astimezone(TZ).date().isoformat()
        out.append({"event_id": e["eid"], "date": d, "title": e["title"], "location": e["location"], "all_day": e["all_day"],
                    "start": None if e["all_day"] else _hm(e["s"]), "end": None if e["all_day"] else _hm(e["e"]),
                    "task_id": tid, "list_id": lid})
        if len(out) >= ATM_ITEMS:
            break
    return {"user_id": pid, "from": frm.isoformat(), "to": to.isoformat(), "events": out}


@app.get("/api/v1/time/check")
@v1_view
def v1_atm_check():
    """Implausible entries and shoot days / events without time of the token user or the person the agent works for."""
    need_time()
    v1_feature("time")
    a = v1_args(("from", "to", "user_id"))
    c = db()
    pid, viewer = atm_person(c, a)
    frm, to = atm_period(a)
    ev = g.get("auth_via") != "token" or "calendar" in (g.get("scopes") or set())  # events only with the calendar scope
    return jsonify(atm_check(c, pid, viewer, frm, to, events=ev))


@app.get("/api/v1/time/from-events")
@v1_view
def v1_atm_from_events():
    """Past events of the period without a matching time entry (needs time + calendar)."""
    from ..api.scopes import need_scope
    need_time()
    v1_feature("time")
    need_scope("calendar")
    a = v1_args(("from", "to", "user_id"))
    c = db()
    pid, viewer = atm_person(c, a)
    frm, to = atm_period(a, 7)
    return jsonify(atm_from_events(c, pid, viewer, frm, to))


# ---------------------------------------------------------------- the proposal (kind time)
def _hm_ok(v):
    if not isinstance(v, str) or len(v) != 5 or v[2] != ":" or not (v[:2] + v[3:]).isdigit():
        return False
    return int(v[:2]) < 24 and int(v[3:]) < 60


def atm_when(d, s, e):
    """local day + HH:MM start / end -> (UTC start, UTC end); BadInput when invalid or in the future."""
    try:
        day = date.fromisoformat(d)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "date")) from None
    if not _hm_ok(s) or not _hm_ok(e):
        raise BadInput(tr("Invalid date or time"))
    a = datetime(day.year, day.month, day.day, int(s[:2]), int(s[3:]), tzinfo=TZ).astimezone(timezone.utc)
    b = datetime(day.year, day.month, day.day, int(e[:2]), int(e[3:]), tzinfo=TZ).astimezone(timezone.utc)
    if b <= a:
        raise BadInput(tr("The end is before the start"))
    if b > now_utc():
        raise BadInput(tr("Entries cannot lie in the future"))
    return a, b


def _atm_item(c, pid, viewer, x, w):
    from ..agents.proposals import _p_int, _p_keys, _p_str
    _p_keys(x, w, ("date", "start", "end", "task_id", "list_id", "note", "event_id"))
    atm_when(x.get("date"), x.get("start"), x.get("end"))
    tid = None if x.get("task_id") in (None, "", 0) else _p_int(x["task_id"], w + ".task_id")
    lid = None if x.get("list_id") in (None, "", 0) else _p_int(x["list_id"], w + ".list_id")
    title = ""
    if tid:
        t = c.execute("SELECT list_id, title, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
        if not t or t["deleted_at"] or not task_visible(c, tid, pid) or not task_visible(c, tid, viewer):
            raise BadInput(tr("Invalid value: {0}", w + ".task_id"))
        lid, title = t["list_id"], t["title"]
    elif lid:
        if not _both_lists(c, pid, viewer, lid):
            raise BadInput(tr("Invalid value: {0}", w + ".list_id"))
        title = (c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone() or {"name": ""})["name"]
    else:
        raise BadInput(tr("Task or list missing"))
    if not mt_time_on(c, lid):
        raise BadInput(tr("Switch on time tracking in the list settings to track time"))
    eid = None if x.get("event_id") in (None, "", 0) else _p_int(x["event_id"], w + ".event_id")
    return {"date": x["date"], "start": x["start"], "end": x["end"], "task_id": tid, "list_id": lid, "title": title,
            "note": _p_str(x.get("note"), w + ".note", ATM_NOTE_MAX), "event_id": eid}


def atm_prop_validate(kind, b, inp):
    """An agent's proposal of kind time (here) or shoot (hub/agentdispo.py) -> the normalized proposal. Checks with the
    database: the person of the job (inp.user_id) and the agent must both see every task / list."""
    from ..agents.proposals import _p_keys, _p_list
    if kind == "shoot":
        from ..hub.agentdispo import adz_validate
        return adz_validate(b, inp)
    _p_keys(b, "", ("kind", "summary", "items"))
    c = db()
    pid, viewer = int(inp.get("user_id") or 0), me()
    raw = _p_list(b.get("items"), "items", ATM_PROP_MAX)
    if not raw:
        raise BadInput(tr("Missing field: {0}", "items"))
    return {"items": [_atm_item(c, pid, viewer, x, f"items[{i}]") for i, x in enumerate(raw)]}


def atm_prop_run(c, j, sel, ed, rec):
    """Apply (as the person): the selected entries, with the edited times / note. rec["made"] = the new entry ids."""
    from ..agents.proposals import _p_keys, _p_str
    if j["kind"] == "shoot":
        from ..hub.agentdispo import adz_run
        return adz_run(c, j, sel, ed, rec)
    need_time()
    need_feat("time")
    prop = json.loads(j["proposal"])
    rec.update(made=[], copies=[])
    ts = iso(now_utc())
    for k in sel:
        if not k.isdigit() or int(k) >= len(prop["items"]):
            continue
        x = dict(prop["items"][int(k)])
        e = ed.get(k) or {}
        _p_keys(e, f"edits.{k}", ("start", "end", "note"))
        for f in ("start", "end"):
            if f in e:
                x[f] = e[f]
        if "note" in e:
            x["note"] = _p_str(e["note"], "note", ATM_NOTE_MAX)
        a, b = atm_when(x["date"], x["start"], x["end"])
        tid, lid, title = time_target(c, {"task_id": x["task_id"]} if x["task_id"] else {"list_id": x["list_id"]})
        row = (me(), tid, lid, title, iso(a), iso(b), int((b - a).total_seconds()), x["note"], "manual", ts, ts)
        rec["made"].append(insert_id(c, """INSERT INTO time_entries(user_id,task_id,list_id,task_title,start,"end",seconds,note,source,
                                          created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""", row))
        rec["copies"].append(list(row))
    if not rec["made"]:
        raise BadInput(tr("Select at least one entry"))
    return rec


def atm_prop_undo(c, j, rec, back=True):
    """Undo (back) removes the entries the proposal made that nobody changed since; redo creates them again."""
    if j["kind"] == "shoot":
        from ..hub.agentdispo import adz_undo
        return adz_undo(c, rec, back)
    n, skipped = 0, []
    if back:
        keep = []
        for eid, row in zip(rec.get("made") or [], rec.get("copies") or []):
            r = c.execute("SELECT updated_at, user_id FROM time_entries WHERE id=?", (eid,)).fetchone()
            if r and r["user_id"] == me() and r["updated_at"] <= rec["at"]:
                c.execute("DELETE FROM time_entries WHERE id=?", (eid,))
                n += 1
                keep.append(row)
            elif r:
                skipped.append(row[3] or "?")
        rec["removed"] = keep
    else:
        made, ts = [], iso(now_utc())
        for row in rec.get("removed") or []:
            made.append(insert_id(c, """INSERT INTO time_entries(user_id,task_id,list_id,task_title,start,"end",seconds,note,source,
                                       created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (*row[:9], ts, ts)))
            n += 1
        rec["made"], rec["copies"], rec["at"] = made, rec.get("removed") or [], ts
    return n, skipped[:8]


def atm_prop_create(c, aid, pid, kind, title, inp, prop, list_id=None):
    """A ready proposal job of the agent for person pid (News + push "Proposal ready" per their settings)."""
    from ..agents.core import JOB_TITLE_MAX, job_dict
    from ..agents.proposals import prop_ready_notify, PROP_OPEN_MAX
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND user_id=? AND kind=? AND prop_state='ready'",
                 (aid, pid, kind)).fetchone()[0] >= PROP_OPEN_MAX:
        return None
    ts = iso(now_utc())
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id,proposal)
                       VALUES(?,NULL,?,?,'waiting','',?,?,?,?,'ready',?,?)""",
                    (aid, pid, title[:JOB_TITLE_MAX], ts, ts, kind, json.dumps(inp, ensure_ascii=False), list_id,
                     json.dumps(prop, ensure_ascii=False)))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    prop_ready_notify(c, j)
    bump(c)
    c.commit()
    return {**job_dict(c, j), "proposal": prop}


@app.post("/api/v1/agent/proposals/time")
@v1_view
def v1_atm_proposal():
    """{user_id?, title?, summary?, items: [{date, start, end, task_id | list_id, note?, event_id?}]} -- the agent proposes
    time entries to a person (who may chat with it; a personal agent: its owner). Nothing is tracked until they apply it."""
    from ..agents.core import need_agent
    from ..agents.proposals import _p_str, PROP_MAX_BYTES, PROP_OPEN_MAX, PROP_TITLE_MAX, prop_validate
    from ..api.scopes import need_scope
    v1_args(())
    aid = need_agent()
    need_time()
    need_scope("time")
    if len(request.data or b"") > PROP_MAX_BYTES:
        return v1_err(413, tr("The proposal is too large (at most {0} KB)", PROP_MAX_BYTES // 1024))
    b = v1_json()
    c = db()
    pid, _ = atm_person(c, {"user_id": b.get("user_id")})
    if pid == aid:
        raise BadInput(tr("Missing field: {0}", "user_id"))
    title = _p_str(b.get("title"), "title", PROP_TITLE_MAX) or tr("Time entries from the calendar")
    inp = {"user_id": pid}
    p = prop_validate("time", {k: v for k, v in b.items() if k not in ("user_id", "title")}, inp)
    out = atm_prop_create(c, aid, pid, "time", title, inp, p)
    if out is None:
        return v1_err(429, tr("You have {0} open proposals for this person: wait until they decided on them", PROP_OPEN_MAX))
    return jsonify(out), 201


def atm_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of the time check routes for agents (2.51.0, #1353)."""
    T = "Time tracking"
    per = [q("from", "First day (YYYY-MM-DD; default: 13 days before to)", {"type": "string", "format": "date"}),
           q("to", "Last day (default today; at most 62 days)", {"type": "string", "format": "date"}),
           q("user_id", "An agent: the person it works for (someone who may chat with it); default: the token's user, a personal agent: its owner",
             {"type": "integer"})]
    paths["/time/check"] = {"get": op(
        "2.51.0 (#1353): implausible time entries and shoot days / events without time", T,
        ok({"type": "object", "properties": {
            "user_id": {"type": "integer"}, "from": {"type": "string"}, "to": {"type": "string"},
            "events_checked": {"type": "boolean", "description": "false: the token lacks the calendar scope, events were not looked at"},
            "limits": {"type": "object"}, "more": {"type": "boolean"},
            "issues": {"type": "array", "items": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["day_long", "entry_long", "overlap", "weekend", "event_no_time", "booking_no_time"]},
                "date": {"type": "string", "format": "date"}, "hours": {"type": "number"},
                "entry_ids": {"type": "array", "items": {"type": "integer"}}, "event_id": {"type": "integer"},
                "booking_id": {"type": "integer"}, "title": {"type": "string"}}}}}}) | errs("400", "403", "404"),
        per, scope="time",
        desc=f"day_long: more than {ATM_DAY_MAX_H} h on one day; entry_long: one entry over {ATM_ENTRY_MAX_H} h; overlap: two entries at "
             "the same time; weekend: entries on Saturday / Sunday without an event or booking; event_no_time: a past event without "
             "any entry at its time; booking_no_time: a firm booking (disposition) of the person without time that day. Only what the "
             "agent and the person both see. Pure data: point it out, propose entries with POST /agent/proposals/time.")}
    paths["/time/from-events"] = {"get": op(
        "2.51.0 (#1353): past events without a matching time entry (rows for a time proposal)", T,
        ok({"type": "object", "properties": {"user_id": {"type": "integer"}, "from": {"type": "string"}, "to": {"type": "string"},
                                             "events": {"type": "array", "items": {"type": "object"}}}}) | errs("400", "403", "404"),
        per, scope="time", desc="Needs the scopes time and calendar. Default period: the last 7 days. start / end = local HH:MM "
                                "(null for all-day events: ask or propose working hours); task_id / list_id where the person tracks time.")}
    paths["/agent/proposals/time"] = {"post": op(
        "2.51.0 (#1353): propose time entries to a person (they review and apply; you never track time yourself)", "Agents",
        ok({"type": "object"}, "Created", "201") | errs("400", "403", "404", "413", "429"),
        body={"type": "object", "required": ["items"], "properties": {
            "user_id": {"type": "integer"}, "title": {"type": "string"}, "summary": {"type": "string", "description": "Markdown, why"},
            "items": {"type": "array", "maxItems": ATM_PROP_MAX, "items": {"type": "object", "required": ["date", "start", "end"], "properties": {
                "date": {"type": "string", "format": "date"}, "start": {"type": "string", "description": "HH:MM local"},
                "end": {"type": "string", "description": "HH:MM local, after start"}, "task_id": {"type": "integer"},
                "list_id": {"type": "integer", "description": "Instead of task_id: an entry on the list"},
                "note": {"type": "string"}, "event_id": {"type": "integer", "description": "The event it comes from"}}}}}},
        scope="time", desc="Agents only. A ready proposal (kind time) for the person: News + push per their settings. Every task / list "
                           "must be visible to you and the person and track time; entries never lie in the future. The answer comes as "
                           "the event job (approve / reject).")}
