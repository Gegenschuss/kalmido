"""2.34.0 (#272): planned agent jobs -- "every Monday at 9: the week plan for the team".

A person who may chat with an agent (agent_shares) plans jobs for that agent for THEMSELVES: title, the order (prompt),
a rhythm (daily / weekdays / weekly on days / monthly on a day, at HH:MM in the person's time zone), optionally a list
the job is about (it must be open to the person for the agent: agent_usable, and inside the agent's list limit), on / off.
The agent's managers (the owner of a personal agent; for a team agent the instance admins) see and manage every plan of
the agent. Kalmido never runs a model itself: when a plan is due the watchdog (every TASKS_WATCHDOG_INTERVAL seconds)
records ONE agent event scheduled_job {schedule_id, title, prompt, list_id, list, by, user, chat_with, due_at, late, manual, manual_by}
and the agent answers in its chat with that person (send_chat user_id = by.id). Once per due time; after an outage at most
the one missed run is sent (late: true), then the plan goes on from now (no catch-up storm). A switched-off agent (kill
switch, disabled) gets nothing -- the run counts as skipped; a paused agent gets the event queued like every other one.
A plan whose person lost the agent, or whose list is no longer shared with it, switches itself off (last_state no_access /
no_list). Limits: SCHED_MAX plans per person and agent; the rhythm is at most daily, "Run now" at most every SCHED_RUN_GAP_S
seconds per plan. Agents read their plans (GET /api/v1/agent/schedules) but cannot create or change them."""
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import g, jsonify

from ..core.config import app, TZ
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc, parse_iso
from ..core.access import Denied, list_role
from ..accounts.session import me
from ..collab.comments import user_names
from ..personal.timetrack import BadInput
from ..api.v1 import v1_args, v1_view
from ..agents.core import agent_active, agent_emit, agent_row, agent_shares, agent_usable, is_agent, lst_brief, need_agent

SCHED_FREQS = ("daily", "weekdays", "weekly", "monthly")
SCHED_MAX = 20                 # plans per person and agent
SCHED_TITLE_MAX = 120
SCHED_PROMPT_MAX = 4000
SCHED_LATE_S = 15 * 60         # a run sent later than this after its due time is marked late
SCHED_RUN_GAP_S = 600          # "Run now": at most once per plan within this many seconds
SCHED_TICK_MAX = 200           # due plans handled per watchdog tick
SCHED_FIELDS = ("title", "prompt", "freq", "days", "time", "tz", "list_id", "enabled")


def sched_zone(name):
    try:
        return ZoneInfo(str(name)) if name else TZ
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return TZ


def sched_days(r):
    return [int(x) for x in str(r["days"] or "").split(",") if x.strip().isdigit()]


def _sched_day_ok(freq, days, d):
    if freq == "daily":
        return True
    if freq == "weekdays":
        return d.isoweekday() <= 5
    if freq == "weekly":
        return d.isoweekday() in days
    # monthly: the day of the month; a day the month does not have = its last day (31 -> 30 April, 28 / 29 February)
    want = days[0] if days else 1
    last = ((d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).day
    return d.day == min(want, last)


def sched_next(freq, days, hm, tzname, after):
    """The next due time (UTC datetime) strictly after `after` (aware datetime), or None."""
    z = sched_zone(tzname)
    h, m = (int(x) for x in hm.split(":"))
    d = after.astimezone(z).date()
    for _ in range(400):
        if _sched_day_ok(freq, days, d):
            at = datetime.combine(d, dtime(h, m), tzinfo=z).astimezone(timezone.utc)
            if at > after:
                return at
        d += timedelta(days=1)
    return None


def sched_manager(c, aid, uid):
    """May uid see and manage every plan of agent aid? The owner of a personal agent; for a team agent the instance
    admins who reach it (2.28.0 #965: like the jobs, only through lists open to them -- agent_shares)."""
    a = agent_row(c, aid)
    u = c.execute("SELECT is_admin, kind, disabled FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not a or not u or u["kind"] == "agent" or u["disabled"]:
        return False
    if a["owner_id"]:
        return a["owner_id"] == uid
    return bool(u["is_admin"]) and agent_shares(c, aid, uid)


def sched_list_ok(c, aid, uid, lid):
    """The list a plan is about: 404 when the person cannot see it, BadInput when it is not open to them for this agent."""
    from ..agents.safety import ids_parse
    if not list_role(c, lid, uid):
        raise Denied(404)
    a = agent_row(c, aid)
    if not agent_usable(c, aid, uid, lid) or (a["list_ids"] and lid not in ids_parse(a["list_ids"])):
        raise BadInput(tr("This list is not shared with the agent"))


def sched_in(c, aid, uid, b, cur=None):
    """Checked fields of a new plan (cur None) or a change; BadInput / Denied(404) otherwise."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "body"))
    unknown = sorted(k for k in b if k not in SCHED_FIELDS)
    if unknown:
        raise BadInput(tr("Invalid value: {0}", ", ".join(unknown)))
    f = {}
    for k in ("title", "prompt"):
        if k in b or cur is None:
            v = b.get(k)
            if not isinstance(v, str) or not v.strip():
                raise BadInput(tr("Invalid value: {0}", k))
            v = v.strip()
            if len(v) > (SCHED_TITLE_MAX if k == "title" else SCHED_PROMPT_MAX):
                raise BadInput(tr("Too long: {0} (at most {1} characters)", k, SCHED_TITLE_MAX if k == "title" else SCHED_PROMPT_MAX))
            f[k] = v
    freq = b.get("freq", cur["freq"] if cur else "daily")
    if freq not in SCHED_FREQS:
        raise BadInput(tr("Invalid value: {0}", "freq"))
    days = b.get("days", sched_days(cur) if cur else [])
    if not isinstance(days, list) or any(isinstance(x, bool) or not isinstance(x, int) for x in days):
        raise BadInput(tr("Invalid value: {0}", "days"))
    if freq == "weekly":
        days = sorted(set(days))
        if not days or any(not 1 <= x <= 7 for x in days):
            raise BadInput(tr("Pick at least one weekday"))
    elif freq == "monthly":
        if len(days) != 1 or not 1 <= days[0] <= 31:
            raise BadInput(tr("Invalid value: {0}", "days"))
    else:
        days = []
    f["freq"], f["days"] = freq, ",".join(str(x) for x in days)
    hm = b.get("time", cur["at_time"] if cur else "09:00")
    if not isinstance(hm, str) or len(hm) != 5 or hm[2] != ":" or not (hm[:2].isdigit() and hm[3:].isdigit()) \
            or int(hm[:2]) > 23 or int(hm[3:]) > 59:
        raise BadInput(tr("Invalid value: {0}", "time"))
    f["at_time"] = hm
    tz = b.get("tz", cur["tz"] if cur else TZ.key)
    if not isinstance(tz, str) or len(tz) > 64:
        raise BadInput(tr("Invalid value: {0}", "tz"))
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise BadInput(tr("Invalid value: {0}", "tz")) from None
    f["tz"] = tz
    if "list_id" in b:
        lid = b["list_id"]
        if lid in (None, 0):
            f["list_id"] = None
        elif isinstance(lid, bool) or not isinstance(lid, int):
            raise BadInput(tr("Invalid value: {0}", "list_id"))
        else:
            # a manager changing someone else's plan: the list must work for the plan's person
            sched_list_ok(c, aid, cur["user_id"] if cur else uid, lid)
            f["list_id"] = lid
    if "enabled" in b:
        if not isinstance(b["enabled"], bool):
            raise BadInput(tr("Invalid value: {0}", "enabled"))
        f["enabled"] = int(b["enabled"])
    return f


def sched_dict(c, r, uid=None, names=None):
    names = names or user_names(c, [r["agent_id"], r["user_id"]])
    lname = None
    if r["list_id"] and (uid is None or list_role(c, r["list_id"], uid)):
        lname = lst_brief(c, r["list_id"])["name"]
    return {"id": r["id"], "agent_id": r["agent_id"], "agent_name": names.get(r["agent_id"], ""),
            "user_id": r["user_id"], "by_name": names.get(r["user_id"], ""), "mine": uid is not None and r["user_id"] == uid,
            "title": r["title"], "prompt": r["prompt"], "freq": r["freq"], "days": sched_days(r), "time": r["at_time"], "tz": r["tz"],
            "list_id": r["list_id"], "list_name": lname, "enabled": bool(r["enabled"]),
            "next_at": r["next_at"] if r["enabled"] else None, "last_at": r["last_at"], "last_state": r["last_state"] or None,
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def sched_row(c, sid):
    return c.execute("SELECT * FROM agent_schedules WHERE id=?", (sid,)).fetchone()


def sched_need(c, sid, uid):
    """A plan uid may manage (their own while they still reach the agent, or as the agent's manager); 404 otherwise."""
    r = sched_row(c, sid)
    if not r or is_agent(g.user):
        raise Denied(404)
    if r["user_id"] == uid and agent_shares(c, r["agent_id"], uid):
        return r
    if sched_manager(c, r["agent_id"], uid):
        return r
    raise Denied(404)


def _sched_set_next(c, sid, after=None):
    r = sched_row(c, sid)
    nx = sched_next(r["freq"], sched_days(r), r["at_time"], r["tz"], after or now_utc()) if r["enabled"] else None
    c.execute("UPDATE agent_schedules SET next_at=? WHERE id=?", (iso(nx) if nx else None, sid))


def sched_fire(c, r, now, manual=False, manual_by=None):
    """Sends the scheduled_job event of plan r (the caller commits). Returns the state written to last_state. manual_by: the
    id of a manager who pressed "Run now" on another person's plan (review N2: the event names who triggered it)."""
    aid, uid = r["agent_id"], r["user_id"]
    a = agent_row(c, aid)
    state = None
    u = c.execute("SELECT disabled FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["disabled"] or not agent_shares(c, aid, uid):
        state = "no_access"
    elif r["list_id"]:
        try:
            sched_list_ok(c, aid, uid, r["list_id"])
        except (Denied, BadInput):
            state = "no_list"
    if state:  # the plan cannot work any more: it switches itself off (the person sees why)
        c.execute("UPDATE agent_schedules SET enabled=0, next_at=NULL, last_state=?, updated_at=? WHERE id=?", (state, iso(now), r["id"]))
        return state
    due = r["next_at"] if not manual and r["next_at"] else iso(now)
    late = not manual and (now - parse_iso(due)).total_seconds() > SCHED_LATE_S
    name = user_names(c, [uid]).get(uid, "")
    data = {"schedule_id": r["id"], "title": r["title"], "prompt": r["prompt"], "list_id": r["list_id"],
            "list": lst_brief(c, r["list_id"]) if r["list_id"] else None,
            "by": {"id": uid, "name": name}, "user": {"id": uid, "name": name}, "chat_with": uid,
            "rhythm": {"freq": r["freq"], "days": sched_days(r), "time": r["at_time"], "tz": r["tz"]},
            "due_at": due, "late": late, "manual": manual,
            "manual_by": {"id": manual_by, "name": user_names(c, [manual_by]).get(manual_by, "")} if manual_by else None,
            "hint": "A planned job of this person. Do what the prompt says (only with lists shared with you) and answer in "
                    "your chat with them (send_chat user_id = by.id), starting with the job's title. Nothing goes to anyone else."}
    seq = agent_emit(c, aid, "scheduled_job", data) if agent_active(a) else None
    state = ("late" if late else "sent") if seq else "skipped"
    c.execute("UPDATE agent_schedules SET last_at=?, last_state=?, last_seq=? WHERE id=?", (iso(now), state, seq, r["id"]))
    return state


def sched_tick(c):
    """Watchdog: every due plan once. The next due time is computed from now, so an outage costs at most one late run."""
    now = now_utc()
    rows = c.execute("SELECT * FROM agent_schedules WHERE enabled=1 AND next_at IS NOT NULL AND next_at<=? ORDER BY next_at LIMIT ?",
                     (iso(now), SCHED_TICK_MAX)).fetchall()
    for r in rows:
        try:
            if sched_fire(c, r, now) not in ("no_access", "no_list"):
                _sched_set_next(c, r["id"], now)
            c.commit()
        except Exception as e:  # noqa: BLE001 -- one broken plan must not hold up the others (nor fire every tick)
            c.rollback()
            print("agent schedule", r["id"], "failed:", type(e).__name__, e, flush=True)
            c.execute("UPDATE agent_schedules SET next_at=? WHERE id=?", (iso(now + timedelta(hours=1)), r["id"]))
            c.commit()


# ---- the app (session): plans of the person with one agent, managers see all of the agent
@app.get("/api/agents/<int:aid>/schedules")
def agent_schedules_get(aid):
    c, uid = db(), me()
    mgr = sched_manager(c, aid, uid)
    if not agent_row(c, aid) or is_agent(g.user) or not (agent_shares(c, aid, uid) or mgr):
        raise Denied(404)
    rows = c.execute("SELECT * FROM agent_schedules WHERE agent_id=?" + ("" if mgr else " AND user_id=?") + " ORDER BY user_id!=?, id",
                     (aid, uid) if mgr else (aid, uid, uid)).fetchall()
    names = user_names(c, [aid] + [r["user_id"] for r in rows])
    return jsonify(data=[sched_dict(c, r, uid, names) for r in rows], manager=mgr, max=SCHED_MAX, may_create=agent_shares(c, aid, uid),
                   freqs=list(SCHED_FREQS))


@app.post("/api/agents/<int:aid>/schedules")
def agent_schedule_create(aid):
    """{title, prompt, freq, days?, time, tz?, list_id?, enabled?} -- a plan of mine for this agent."""
    c, uid = db(), me()
    a = agent_row(c, aid)
    if not a or is_agent(g.user) or not agent_shares(c, aid, uid):
        raise Denied(404)
    try:
        f = sched_in(c, aid, uid, body())
    except BadInput as e:
        return err(str(e))
    if c.execute("SELECT COUNT(*) FROM agent_schedules WHERE agent_id=? AND user_id=?", (aid, uid)).fetchone()[0] >= SCHED_MAX:
        return err(tr("At most {0} plans per agent", SCHED_MAX), 409)
    ts = iso(now_utc())
    sid = c.execute("""INSERT INTO agent_schedules(agent_id,user_id,title,prompt,freq,days,at_time,tz,list_id,enabled,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (aid, uid, f["title"], f["prompt"], f["freq"], f["days"], f["at_time"], f["tz"], f.get("list_id"),
                     f.get("enabled", 1), ts, ts)).lastrowid
    _sched_set_next(c, sid)
    c.commit()
    return jsonify(sched_dict(c, sched_row(c, sid), uid)), 201


@app.patch("/api/agent-schedules/<int:sid>")
def agent_schedule_update(sid):
    c, uid = db(), me()
    r = sched_need(c, sid, uid)
    try:
        f = sched_in(c, r["agent_id"], uid, body(), cur=r)
    except BadInput as e:
        return err(str(e))
    if f.get("enabled") and not r["enabled"]:
        f["last_state"] = ""  # switched on again: the old "switched itself off" reason goes
    sets = ", ".join(f"{k}=?" for k in f)
    c.execute(f"UPDATE agent_schedules SET {sets}, updated_at=? WHERE id=?", (*f.values(), iso(now_utc()), sid))
    _sched_set_next(c, sid)
    c.commit()
    return jsonify(sched_dict(c, sched_row(c, sid), uid))


@app.delete("/api/agent-schedules/<int:sid>")
def agent_schedule_delete(sid):
    c, uid = db(), me()
    sched_need(c, sid, uid)
    c.execute("DELETE FROM agent_schedules WHERE id=?", (sid,))
    c.commit()
    return jsonify(ok=True)


@app.post("/api/agent-schedules/<int:sid>/run")
def agent_schedule_run(sid):
    """Run now: the event goes out at once (manual: true); the plan's rhythm stays as it is."""
    c, uid = db(), me()
    r = sched_need(c, sid, uid)
    now = now_utc()
    if r["last_at"] and (now - parse_iso(r["last_at"])).total_seconds() < SCHED_RUN_GAP_S and r["last_state"] in ("sent", "late", "manual"):
        return err(tr("This plan just ran. Try again in a few minutes."), 429)
    if not agent_active(agent_row(c, r["agent_id"])):
        return err(tr("This agent is paused"), 409)
    st = sched_fire(c, r, now, manual=True, manual_by=uid if uid != r["user_id"] else None)
    if st == "sent":
        c.execute("UPDATE agent_schedules SET last_state='manual' WHERE id=?", (sid,))
    c.commit()
    if st in ("no_access", "no_list"):
        return err(tr("This plan cannot run any more: the agent no longer sees its list or you."), 409)
    return jsonify(sched_dict(c, sched_row(c, sid), uid))


# ---- the agent API: an agent reads its plans (it cannot create or change them)
@app.get("/api/v1/agent/schedules")
@v1_view
def v1_agent_schedules():
    v1_args(())
    aid = need_agent()
    c = db()
    rows = c.execute("SELECT * FROM agent_schedules WHERE agent_id=? ORDER BY id", (aid,)).fetchall()
    names = user_names(c, [aid] + [r["user_id"] for r in rows])
    out = []
    for r in rows:
        d = sched_dict(c, r, None, names)
        d.pop("mine", None)
        d["list"] = lst_brief(c, r["list_id"]) if r["list_id"] and list_role(c, r["list_id"], aid) else None
        out.append(d)
    return jsonify(data=out, next_cursor=None)


def sched_spec(paths, schemas, op, ok, errs, ref, pid, nul):
    """OpenAPI: GET /agent/schedules + the Schedule schema (called from openapi_spec)."""
    schemas["Schedule"] = {"type": "object", "description": "2.34.0 (#272): a planned job of a person for the agent", "properties": {
        "id": {"type": "integer"}, "agent_id": {"type": "integer"}, "agent_name": {"type": "string"},
        "user_id": {"type": "integer", "description": "The person who planned it; answer in your chat with them"},
        "by_name": {"type": "string"}, "title": {"type": "string"}, "prompt": {"type": "string", "description": "What to do (the person's words)"},
        "freq": {"type": "string", "enum": list(SCHED_FREQS)},
        "days": {"type": "array", "items": {"type": "integer"}, "description": "weekly: ISO weekdays 1 (Monday) - 7; monthly: [day of month]"},
        "time": {"type": "string", "description": "HH:MM in tz"}, "tz": {"type": "string", "description": "IANA time zone of the person"},
        "list_id": nul("integer"), "list_name": nul("string"), "list": nul("object"), "enabled": {"type": "boolean"},
        "next_at": nul("string", format="date-time"), "last_at": nul("string", format="date-time"),
        "last_state": nul("string", description="sent | late | manual | skipped (you were switched off) | no_access | no_list (switched itself off)"),
        "created_at": {"type": "string", "format": "date-time"}, "updated_at": {"type": "string", "format": "date-time"}}}
    paths["/agent/schedules"] = {"get": op(
        "2.34.0 (#272): your planned jobs (agent tokens only). People who may chat with you plan them in the app; when one is due "
        "you get the event scheduled_job {schedule_id, title, prompt, list_id, list, by, user, chat_with, rhythm, due_at, late, manual, manual_by} "
        "and answer in your chat with that person. You cannot create or change plans.", "Agents",
        ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("Schedule")}, "next_cursor": nul("string")}}) | errs("403"))}
