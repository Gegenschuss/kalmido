"""Time tracking (module "time") and the unknown-JSON-field check of the REST API."""
import csv
import io
import math
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from flask import g, has_request_context, jsonify, request, Response

from ..core.config import app, PUBLIC_URL, TZ
from ..core.i18n import dec_comma, lang, LANGS, tr
from ..core.db import body, bump, db, err, gsetting, inbox_default, iso, local_now, now_utc, parse_iso, usettings
from ..accounts.session import me, user_public
from ..core.access import (
    _pset_sql, Denied, is_project, list_role, need_feat, need_list, need_project, need_task, need_time, plists,
    PROJ_SQL, pvis, task_visible, time_all, vis_sql,
)
from ..core.state import visible_lists
from ..tasks.validation import DAY_HOURS_DEFAULT
from ..personal.habits import pomo_elapsed


# ---------------------------------------------------------------- time tracking (module "time")
# Time entries per user on a task (or on a whole list). Decisions:
# - Visibility: my own entries always; in a shared list every member sees everyone's entries on the list's
#   tasks (task totals, reports "all members"), read-only: only the author edits or deletes an entry. Entries
#   in lists I cannot see (someone else's private list) are never returned. Logging time needs read access
#   to the task (a view-only member can track own time). time_entries.list_id follows the task (trigger).
# - One running timer per user (unique index). Starting one stops the previous at the new start. Every
#   start / stop carries the device time ("at", clamped to [now - 7 days, now]) and the device's client_id,
#   so an offline start / stop replayed later lands at the right time; a replayed start that is older than
#   the timer running now becomes a finished entry that ends where that timer starts.
# - Focus: a finished focus / stopwatch session on a task becomes an entry (source focus, duration without
#   pauses, at least 1 min) unless it overlaps one of the user's timer entries: the timer wins, nothing is
#   counted twice. Only with the module on and the setting "Count focus sessions" on.
# - Days: an entry belongs to the local day (server time zone) on which it starts; entries crossing
#   midnight are not split. Durations are real elapsed time (UTC), so DST changes are exact. Periods are
#   local days, weeks start on Monday.
# - Rounding (per user, reports / CSV / timesheet only): every entry is rounded UP to N minutes, stored
#   durations stay exact. Amount = rounded hours x hourly rate of the list (set by the list owner).
TIME_BACK_DAYS = 7
TIME_MAX_S = 7 * 86400
TIME_SOURCES = ("timer", "manual", "focus")


class BadInput(Exception):
    pass


# ---- 2.2.1 (#359): unknown JSON fields. The REST API (/api/v1) refuses them: 400 with
# {"error": {"code": "unknown_field", "message", "fields": [...]}}. The web API (/api, the app's own endpoints) keeps
# working: it ignores them as before, but logs a warning and names them in the response header X-Kalmido-Unknown-Fields,
# so a client sending a field under the wrong name notices instead of losing the value silently. The one alias pair: a
# task's description is `content` in the web API and `notes` in /api/v1; both accept the other name too (both names with
# different values at once: 400).
class UnknownFields(BadInput):
    def __init__(self, fields):
        self.fields = sorted(str(k)[:64] for k in fields)[:50]
        super().__init__(tr("Unknown field: {0}", ", ".join(self.fields)[:200]))


def reject_unknown(b, allowed):
    """/api/v1: UnknownFields (-> 400 unknown_field) for keys of b not in allowed."""
    unknown = [k for k in b if k not in allowed]
    if unknown:
        raise UnknownFields(unknown)


def field_alias(b, have, other):
    """b with the alias `other` renamed to `have` (400 when both come with different values)."""
    if not isinstance(b, dict) or other not in b:
        return b
    if have in b and b[have] != b[other]:
        raise BadInput(tr("Send either {0} or {1}, not both", have, other))
    out = {k: v for k, v in b.items() if k != other}
    out[have] = b[other]
    return out


_UNKNOWN_LOGGED, UNKNOWN_LOG_EVERY = {}, 3600  # (what, fields) -> last warning (s); one line per hour and combination


def web_fields(b, known, what):
    """Web API: unknown keys of b are ignored (as always), logged as a warning (at most hourly per endpoint and set of
    names, never values) and named in the response header X-Kalmido-Unknown-Fields. Returns b."""
    if not isinstance(b, dict):
        return b
    unknown = sorted(str(k)[:64] for k in b if k not in known)
    if not unknown:
        return b
    if has_request_context():
        g.unknown_fields = unknown
    key, now = (what, tuple(unknown[:20])), time.time()
    if now - _UNKNOWN_LOGGED.get(key, 0) >= UNKNOWN_LOG_EVERY:
        if len(_UNKNOWN_LOGGED) > 500:
            _UNKNOWN_LOGGED.clear()
        _UNKNOWN_LOGGED[key] = now
        uid = g.user["id"] if has_request_context() and getattr(g, "user", None) else "-"
        print(f"WARNING {what}: unknown field(s) ignored: {', '.join(unknown)[:300]} (user {uid})", flush=True)
    return b


@app.after_request
def unknown_fields_header(resp):
    u = g.get("unknown_fields")
    if u:
        resp.headers["X-Kalmido-Unknown-Fields"] = ", ".join(u)[:500]
    return resp


@app.errorhandler(BadInput)
def bad_input(e):
    return err(str(e), 400)


def parse_when(v):
    """ISO date-time from the client (Z / offset; naive = server time zone) -> aware UTC (whole seconds)."""
    if not v or not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        raise BadInput(tr("Invalid date or time")) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def time_at(v, ref):
    """Device time of a timer start / stop, clamped to [ref - 7 days, ref]."""
    try:
        t = parse_when(v)
    except BadInput:
        t = None
    if not t or t > ref:
        return ref
    return max(t, ref - timedelta(days=TIME_BACK_DAYS))


class VisIds(set):
    """The list ids uid sees (a set, as before 1.10.0) + task_ok(): whether a task of such a list is visible too
    (participant lists: only the participant's tasks; full=True: not only as context)."""

    def __init__(self, c, uid):
        super().__init__(r[0] for r in c.execute(vis_sql()[1:-1], (uid, uid)))
        self.pl = set(plists(c, uid))
        self.pv, self.pw, _ = pvis(c, uid) if self.pl else (set(), set(), set())

    def task_ok(self, tid, lid, full=False):
        return lid in self and (lid not in self.pl or tid in (self.pw if full else self.pv))


def vis_ids(c, uid):
    return VisIds(c, uid)


def evis(c, uid, a="e."):
    """SQL restriction (no ? params) for time entries: a participant sees their own entries and the ones on their
    own tasks, never other people's entries on the rest of a participant list. "1" when uid is a participant nowhere."""
    pl = plists(c, uid)
    if not pl:
        return "1"
    return (f"({a}user_id={int(uid)} OR {a}list_id IS NULL OR {a}list_id NOT IN ({','.join(str(int(x)) for x in pl)}) "
            f"OR {a}task_id IN ({_pset_sql(uid, pl, write=True)}))")


def rnd_up(sec, minutes):
    if minutes <= 0 or sec <= 0:
        return sec
    step = minutes * 60
    return -(-sec // step) * step


def time_rounding(s):
    try:
        return max(0, min(60, int(s.get("time_rounding") or 0)))
    except (TypeError, ValueError):
        return 0


def entry_secs(r, ref):
    return max(0, int((ref - parse_iso(r["start"])).total_seconds())) if r["end"] is None else r["seconds"]


def time_on(s):
    return time_all() and "time" in (s.get("features") or "").split(",")


TIME_Q = """SELECT e.*, t.title AS t_title, u.display_name AS u_name, u.username AS u_login
            FROM time_entries e LEFT JOIN tasks t ON t.id=e.task_id LEFT JOIN users u ON u.id=e.user_id"""


def entry_out(r, uid, vis, ref, rm):
    sec, seen = entry_secs(r, ref), r["list_id"] in vis
    if seen and r["task_id"] and isinstance(vis, VisIds):  # 1.10.0: a task a participant no longer sees
        seen = vis.task_ok(r["task_id"], r["list_id"], full=True)
    title = r["t_title"] if seen and r["t_title"] is not None else r["task_title"]
    return {"id": r["id"], "user_id": r["user_id"], "user_name": r["u_name"] or r["u_login"] or "",
            "task_id": r["task_id"] if seen else None, "list_id": r["list_id"] if seen else None,
            "title": title or "", "start": r["start"], "end": r["end"], "seconds": sec, "rounded": rnd_up(sec, rm),
            "note": r["note"], "source": r["source"], "running": r["end"] is None, "mine": r["user_id"] == uid,
            "auto_stopped": bool(r["auto_stopped"]), "client_id": r["client_id"] if r["user_id"] == uid else None}


def one_entry(c, eid):
    uid = me()
    r = c.execute(TIME_Q + " WHERE e.id=?", (eid,)).fetchone()
    return entry_out(r, uid, vis_ids(c, uid), now_utc(), time_rounding(usettings(c, uid))) if r else None


def need_entry(c, eid):
    """My own entry (to change it). Someone else's visible entry: 403, anything else: 404."""
    uid = me()
    r = c.execute("SELECT * FROM time_entries WHERE id=?", (eid,)).fetchone()
    if not r or (r["user_id"] != uid and not (r["list_id"] in (v := vis_ids(c, uid)) and
                                              (not r["task_id"] or v.task_ok(r["task_id"], r["list_id"], full=True))
                                              and (r["task_id"] or r["list_id"] not in v.pl))):
        raise Denied(404)
    if r["user_id"] != uid:
        return err(tr("Only the person who tracked it can change this entry"), 403)
    return r


def time_target(c, b):
    """task_id or list_id of an entry from the request -> (task_id, list_id, title); read access needed."""
    tid = b.get("task_id")
    if tid not in (None, "", 0):
        try:
            tid = int(tid)
        except (TypeError, ValueError):
            raise Denied(404) from None
        need_task(c, tid, write=False, full=True)
        t = c.execute("SELECT list_id, title FROM tasks WHERE id=?", (tid,)).fetchone()
        need_project(c, t["list_id"], "time")
        return tid, t["list_id"], t["title"]
    try:
        lid = int(b.get("list_id"))
    except (TypeError, ValueError):
        raise BadInput(tr("Task or list missing")) from None
    need_list(c, lid, write=False)
    need_project(c, lid, "time")
    return None, lid, ""


def time_running(c, uid):
    r = c.execute(TIME_Q + " WHERE e.user_id=? AND e.end IS NULL", (uid,)).fetchone()
    if not r:
        return None
    return entry_out(r, uid, vis_ids(c, uid), now_utc(), 0)


def time_totals(c, uid):
    """{task_id: [seconds of everyone I can see, my seconds]} of finished entries (the client adds my running timer)."""
    out = {}
    for r in c.execute(f"""SELECT task_id, SUM(seconds) AS s, SUM(CASE WHEN user_id=? THEN seconds ELSE 0 END) AS m
                           FROM time_entries WHERE task_id IS NOT NULL AND end IS NOT NULL AND list_id IN {PROJ_SQL}
                             AND (user_id=? OR list_id IN {vis_sql()}) AND {evis(c, uid, "")} GROUP BY task_id""", (uid, uid, uid, uid)):
        if r["s"]:
            out[r["task_id"]] = [r["s"], r["m"]]
    return out


def clean_day_hours(v):
    """2.7.0 (#407): hours per day / shift: None for '' / None (= the instance's value), False if invalid."""
    if v in (None, ""):
        return None
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return False
    return round(x, 2) if math.isfinite(x) and 1 <= x <= 24 else False


def time_day_h(c):
    """2.7.0 (#407): the instance's hours per day / shift (Administration > Server; default 8)."""
    v = clean_day_hours(gsetting(c, "time_day_h"))
    return v or DAY_HOURS_DEFAULT


BUDGET_FIELD_NAMES = ("budget h", "budget (h)", "budget hours", "budget std", "budget (std)", "budget-stunden", "budgetstunden")


def time_list_totals(c, uid):
    """2.7.0 (#407): {list_id: {"s": seconds of everyone I can see, "b": budget hours or None}} of my project lists with
    time: the finished entries (with or without a task; the client adds my running timer) and the sum of a number field
    called "Budget h" (the agency project type's field, any language) over the list's tasks."""
    out = {}
    for r in c.execute(f"""SELECT list_id, SUM(seconds) AS s FROM time_entries WHERE end IS NOT NULL AND list_id IN {PROJ_SQL}
                           AND (user_id=? OR list_id IN {vis_sql()}) AND {evis(c, uid, "")} GROUP BY list_id""", (uid, uid, uid)):
        if r["s"]:
            out[r["list_id"]] = {"s": r["s"], "b": None}
    names = set(BUDGET_FIELD_NAMES) | {tr("Budget h", lg=x).lower() for x in LANGS}
    part = set(plists(c, uid))  # a participant sees only some tasks: no budget sum there
    for r in c.execute(f"""SELECT f.list_id, f.id, f.name FROM list_fields f WHERE f.type='number' AND f.list_id IN {vis_sql()}
                           AND f.list_id IN {PROJ_SQL}""", (uid, uid)).fetchall():
        if (r["name"] or "").strip().lower() not in names or r["list_id"] in part:
            continue
        tot = 0.0
        for (v,) in c.execute("""SELECT v.value FROM task_field_values v JOIN tasks t ON t.id=v.task_id
                                 WHERE v.field_id=? AND t.deleted_at IS NULL""", (r["id"],)):
            try:
                x = float(str(v).replace(",", "."))
            except (TypeError, ValueError):
                continue
            if math.isfinite(x) and x > 0:
                tot += x
        if tot > 0:
            o = out.setdefault(r["list_id"], {"s": 0, "b": None})
            o["b"] = round((o["b"] or 0) + tot, 2)
    return out


def stop_timer(c, r, at, ts):
    end = max(parse_iso(r["start"]), at)
    sec = int((end - parse_iso(r["start"])).total_seconds())
    c.execute("UPDATE time_entries SET end=?, seconds=?, updated_at=? WHERE id=?", (iso(end), sec, ts, r["id"]))
    return sec


@app.post("/api/time/start")
def time_start():
    """{task_id | list_id, note?, at?, client_id?} -- starts my timer; a running one stops at the new start."""
    need_time()
    need_feat("time")
    b = body()
    c = db()
    uid, ref = me(), now_utc().replace(microsecond=0)
    ts = iso(ref)
    cid = str(b.get("client_id") or "")[:64] or None
    if cid:  # replayed (outbox) or sent twice: the first one counts
        r = c.execute("SELECT id FROM time_entries WHERE user_id=? AND client_id=?", (uid, cid)).fetchone()
        if r:
            return jsonify(entry=one_entry(c, r["id"]), stopped=None, timer=time_running(c, uid))
    tid, lid, title = time_target(c, b)
    at = time_at(b.get("at"), ref)
    note = str(b.get("note") or "").strip()[:500]
    stopped, end = None, None
    run = c.execute("SELECT * FROM time_entries WHERE user_id=? AND end IS NULL", (uid,)).fetchone()
    if run:
        if parse_iso(run["start"]) <= at:
            stopped = {"id": run["id"], "seconds": stop_timer(c, run, at, ts), "task_id": run["task_id"]}
        else:  # an older start arrives late (offline): it ends where the running timer began
            end = parse_iso(run["start"])
    eid = c.execute("""INSERT INTO time_entries(user_id,task_id,list_id,task_title,start,end,seconds,note,source,client_id,
                       created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'timer',?,?,?)""",
                    (uid, tid, lid, title, iso(at), iso(end) if end else None,
                     int((end - at).total_seconds()) if end else 0, note, cid, ts, ts)).lastrowid
    bump(c)
    c.commit()
    return jsonify(entry=one_entry(c, eid), stopped=stopped, timer=time_running(c, uid))


@app.post("/api/time/stop")
def time_stop():
    """{id? | client_id?, at?} -- stops that timer entry (else the running one). A replayed stop of an entry
    that another start already ended keeps the earlier end."""
    need_time()
    b = body()
    c = db()
    uid, ref = me(), now_utc().replace(microsecond=0)
    at = time_at(b.get("at"), ref)
    if b.get("id"):
        r = c.execute("SELECT * FROM time_entries WHERE id=? AND user_id=?", (int(b["id"]), uid)).fetchone()
    elif b.get("client_id"):
        r = c.execute("SELECT * FROM time_entries WHERE client_id=? AND user_id=?", (str(b["client_id"])[:64], uid)).fetchone()
    else:
        r = c.execute("SELECT * FROM time_entries WHERE user_id=? AND end IS NULL", (uid,)).fetchone()
        if not r:
            return jsonify(entry=None, timer=None, already=True)
    if not r:
        return err(tr("unknown"), 404)
    sec = None
    if r["end"] is None or (r["source"] == "timer" and at < parse_iso(r["end"])):
        sec = stop_timer(c, r, at, iso(ref))
    if sec == 0:  # started and stopped within the same second (misclick): nothing to keep
        c.execute("DELETE FROM time_entries WHERE id=?", (r["id"],))
    bump(c)
    c.commit()
    return jsonify(entry=one_entry(c, r["id"]), timer=time_running(c, uid), discarded=sec == 0)


def entry_times(b, start, end, sec):
    """start / end / minutes (or seconds) of a manual entry or an edit -> (start, end, seconds)."""
    if "start" in b:
        start = parse_when(b.get("start"))
    if not start:
        raise BadInput(tr("Start missing"))
    if b.get("minutes") not in (None, ""):
        try:
            sec = int(round(float(str(b["minutes"]).replace(",", ".")) * 60))
        except ValueError:
            raise BadInput(tr("Duration: number of minutes expected")) from None
        end = start + timedelta(seconds=sec)
    elif "end" in b and b.get("end"):
        end = parse_when(b.get("end"))
        full = int((end - start).total_seconds())
        try:  # focus entry (restored by undo): its duration without pauses
            sec = min(full, int(b["seconds"])) if b.get("seconds") not in (None, "") else full
        except (TypeError, ValueError):
            sec = full
    elif "start" in b and end is not None:  # moved start, same duration
        end = start + timedelta(seconds=sec)
    if end is None:
        raise BadInput(tr("End or duration missing"))
    if end < start or sec <= 0:
        raise BadInput(tr("The end is before the start"))
    if sec > TIME_MAX_S:
        raise BadInput(tr("At most 7 days per entry"))
    if end > now_utc() + timedelta(days=1):
        raise BadInput(tr("Entries cannot lie in the future"))
    return start, end, sec


@app.post("/api/time/entries")
def time_create():
    """Manual entry: {task_id | list_id, start, end | minutes, note}."""
    need_time()
    need_feat("time")
    b = body()
    c = db()
    uid, ts = me(), iso(now_utc())
    tid, lid, title = time_target(c, b)
    start, end, sec = entry_times(b, None, None, 0)
    src = b.get("source") if b.get("source") in TIME_SOURCES else "manual"
    eid = c.execute("""INSERT INTO time_entries(user_id,task_id,list_id,task_title,start,end,seconds,note,source,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (uid, tid, lid, title, iso(start), iso(end), sec, str(b.get("note") or "").strip()[:500], src, ts, ts)).lastrowid
    bump(c)
    c.commit()
    return jsonify(one_entry(c, eid))


@app.patch("/api/time/entries/<int:eid>")
def time_update(eid):
    """My entry: {start?, end?, minutes?, note?, task_id? | list_id?}. A running timer: start / note / task only."""
    need_time()
    b = body()
    c = db()
    r = need_entry(c, eid)
    if not isinstance(r, sqlite3.Row):
        return r
    sets, args = [], []
    if "note" in b:
        sets.append("note=?")
        args.append(str(b.get("note") or "").strip()[:500])
    if "task_id" in b or "list_id" in b:
        tid, lid, title = time_target(c, b)
        sets += ["task_id=?", "list_id=?", "task_title=?"]
        args += [tid, lid, title]
    if r["end"] is None:  # running
        if "start" in b:
            st = parse_when(b.get("start"))
            if not st or st > now_utc():
                raise BadInput(tr("Invalid date or time"))
            sets.append("start=?")
            args.append(iso(st))
    elif any(k in b for k in ("start", "end", "minutes")):
        start, end, sec = entry_times(b, parse_iso(r["start"]), parse_iso(r["end"]), r["seconds"])
        sets += ["start=?", "end=?", "seconds=?"]
        args += [iso(start), iso(end), sec]
    if sets:
        c.execute(f"UPDATE time_entries SET {', '.join(sets)}, updated_at=? WHERE id=?", (*args, iso(now_utc()), eid))
        bump(c)
        c.commit()
    return jsonify(one_entry(c, eid))


@app.delete("/api/time/entries/<int:eid>")
def time_delete(eid):
    need_time()
    c = db()
    r = need_entry(c, eid)
    if not isinstance(r, sqlite3.Row):
        return r
    old = one_entry(c, eid)
    c.execute("DELETE FROM time_entries WHERE id=?", (eid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, entry=old)


def focus_to_entry(c, pid):
    """A finished focus / stopwatch session on a task -> time entry (see the decisions above)."""
    p = c.execute("SELECT * FROM pomos WHERE id=?", (pid,)).fetchone()
    if not p or p["end"] is None or p["kind"] not in ("focus", "stopwatch") or not p["task_id"] or not p["user_id"]:
        return None
    uid = p["user_id"]
    s = usettings(c, uid)
    if s.get("time_focus") != "1" or not time_on(s):
        return None
    sec = int(pomo_elapsed(p))
    if sec < 60 or c.execute("SELECT 1 FROM time_entries WHERE pomo_id=?", (pid,)).fetchone():
        return None
    t = c.execute("SELECT list_id, title FROM tasks WHERE id=?", (p["task_id"],)).fetchone()
    if not t or not list_role(c, t["list_id"], uid) or not is_project(c, t["list_id"]):
        return None
    if c.execute("SELECT 1 FROM time_entries WHERE user_id=? AND source='timer' AND start<? AND (end IS NULL OR end>?)",
                 (uid, p["end"], p["start"])).fetchone():
        return None  # a timer ran at the same time: it already counts this time
    ts = iso(now_utc())
    return c.execute("""INSERT INTO time_entries(user_id,task_id,list_id,task_title,start,end,seconds,source,pomo_id,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,'focus',?,?,?)""",
                     (uid, p["task_id"], t["list_id"], t["title"], p["start"], p["end"], sec, pid, ts, ts)).lastrowid


def local_bounds(d1, d2):
    """Local days d1..d2 (inclusive) -> UTC ISO [lo, hi)."""
    d3 = d2 + timedelta(days=1)
    return (iso(datetime(d1.year, d1.month, d1.day, tzinfo=TZ)), iso(datetime(d3.year, d3.month, d3.day, tzinfo=TZ)))


def time_rows(c, uid, a):
    """Visible entries for the entry list / report. a: from, to (local dates, inclusive), scope (mine | all),
    user, task_id, lists (csv of list ids; 0 = no list / a list I cannot see)."""
    # list types: only entries of project lists (and list-less ones); a list turned back into a plain list hides its time
    where, args = [f"(e.user_id=? OR e.list_id IN {vis_sql()})", f"(e.list_id IS NULL OR e.list_id IN {PROJ_SQL})",
                   evis(c, uid)], [uid, uid, uid]
    try:
        f = date.fromisoformat(a["from"]) if a.get("from") else None
        t = date.fromisoformat(a["to"]) if a.get("to") else None
    except ValueError:
        raise BadInput(tr("Invalid date or time")) from None
    if f and t and t < f:
        f, t = t, f
    if f:
        where.append("e.start>=?")
        args.append(local_bounds(f, f)[0])
    if t:
        where.append("e.start<?")
        args.append(local_bounds(t, t)[1])
    if a.get("scope", "mine") == "mine":
        where.append("e.user_id=?")
        args.append(uid)
    for k, col in (("user", "e.user_id"), ("task_id", "e.task_id")):
        if a.get(k):
            try:
                args.append(int(a[k]))
            except ValueError:
                raise BadInput(tr("unknown")) from None
            where.append(f"{col}=?")
    rows = c.execute(TIME_Q + f" WHERE {' AND '.join(where)} ORDER BY e.start, e.id", args).fetchall()
    wanted = None
    if a.get("lists"):
        try:
            wanted = {int(x) for x in str(a["lists"]).split(",") if x.strip()}
        except ValueError:
            raise BadInput(tr("unknown")) from None
    return rows, f, t, wanted


@app.get("/api/time/entries")
def time_list():
    """?task_id= (entries of one task I can see) or the report filters; newest first."""
    need_time()
    c = db()
    uid = me()
    a = dict(request.args)
    if a.get("task_id"):
        try:
            need_task(c, int(a["task_id"]), write=False, full=True)
        except ValueError:
            raise Denied(404) from None
        a.setdefault("scope", "all")
    rows, _, _, wanted = time_rows(c, uid, a)
    vis, ref, rm = vis_ids(c, uid), now_utc(), time_rounding(usettings(c, uid))
    out = [entry_out(r, uid, vis, ref, rm) for r in rows]
    if wanted is not None:
        out = [e for e in out if (e["list_id"] or 0) in wanted]
    out.reverse()
    return jsonify(entries=out[:int(request.args.get("limit", 2000))], seconds=sum(e["seconds"] for e in out),
                   mine=sum(e["seconds"] for e in out if e["mine"]))


def time_report(c, uid, a):
    s = usettings(c, uid)
    rm, ref, vis = time_rounding(s), now_utc(), vis_ids(c, uid)
    lists = {l["id"]: l for l in visible_lists(c, uid)}
    crates = {r[0]: r[1] for r in c.execute("SELECT id, rate FROM clients WHERE rate IS NOT NULL")}  # 2.23.0 (#463)
    rows, f, t, wanted = time_rows(c, uid, a)
    L, D, U, entries = {}, {}, {}, []
    tot = {"seconds": 0, "rounded": 0, "amount": 0.0, "count": 0}

    def add(d, e, amt):
        d["seconds"] += e["seconds"]
        d["rounded"] += e["rounded"]
        d["amount"] = d.get("amount", 0.0) + amt
    for r in rows:
        e = entry_out(r, uid, vis, ref, rm)
        lid = e["list_id"] if e["list_id"] in lists else 0
        if wanted is not None and lid not in wanted:
            continue
        l = lists.get(lid)
        rate = l["rate"] if l and l.get("rate") else (crates.get(l.get("client_id")) if l else None) or None  # else the client's rate
        amt = e["rounded"] / 3600 * rate if rate else 0.0
        e["amount"] = round(amt, 2) if rate else None
        e["day"] = parse_iso(e["start"]).astimezone(TZ).date().isoformat()
        entries.append(e)
        add(tot, e, amt)
        tot["count"] += 1
        grp = L.setdefault(lid, {"id": lid, "name": l["name"] if l else "", "is_inbox": bool(l and l["is_inbox"]),
                               "color": l["color"] if l else "", "rate": rate, "seconds": 0, "rounded": 0, "amount": 0.0,
                               "tasks": {}, "users": {}})
        add(grp, e, amt)
        k = e["task_id"] or "x:" + e["title"]
        tk = grp["tasks"].setdefault(k, {"id": e["task_id"], "title": e["title"], "seconds": 0, "rounded": 0,
                                       "amount": 0.0, "users": {}})
        add(tk, e, amt)
        tk["users"][e["user_name"]] = tk["users"].get(e["user_name"], 0) + e["rounded"]
        grp["users"][e["user_name"]] = grp["users"].get(e["user_name"], 0) + e["rounded"]
        dd = D.setdefault(e["day"], {"date": e["day"], "seconds": 0, "rounded": 0})
        add(dd, e, 0)
        uu = U.setdefault(e["user_id"], {"id": e["user_id"], "name": e["user_name"], "seconds": 0, "rounded": 0})
        add(uu, e, 0)
    out_lists = []
    for grp in sorted(L.values(), key=lambda x: (-x["seconds"], x["id"] == 0, x["name"].casefold())):
        grp["tasks"] = sorted(grp["tasks"].values(), key=lambda x: (-x["seconds"], x["title"].casefold()))
        for x in [grp, *grp["tasks"]]:
            x["amount"] = round(x["amount"], 2)
            x["users"] = sorted(x["users"].items(), key=lambda kv: -kv[1])
        out_lists.append(grp)
    tot["amount"] = round(tot["amount"], 2)
    for d in D.values():
        d.pop("amount", None)
    for u in U.values():
        u.pop("amount", None)
    today = local_now().date()
    lo, hi = local_bounds(today, today)
    mine_today = sum(entry_secs(r, ref) for r in c.execute(
        f"SELECT start, end, seconds FROM time_entries WHERE user_id=? AND start>=? AND start<? AND (list_id IS NULL OR list_id IN {PROJ_SQL})",
        (uid, lo, hi)))
    return {"from": f.isoformat() if f else None, "to": t.isoformat() if t else None, "scope": a.get("scope", "mine"),
            "rounding": rm, "currency": s.get("time_currency") or "", "total": tot, "lists": out_lists,
            "days": sorted(D.values(), key=lambda x: x["date"]), "users": sorted(U.values(), key=lambda x: -x["seconds"]),
            "entries": entries, "now": iso(ref), "today": {"seconds": mine_today, "target_h": _num(s.get("time_target"))},
            "me": user_public(g.user)}


def _num(v):
    try:
        return max(0.0, float(str(v or 0).replace(",", ".")))
    except ValueError:
        return 0.0


@app.get("/api/time/report")
def time_report_api():
    need_time()
    c = db()
    return jsonify(time_report(c, me(), dict(request.args)))


def _csv_cell(v):
    v = str(v or "")
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


@app.get("/api/time/export.csv")
def time_csv():
    """Same filters as the report, one row per entry. German: ';' and decimal comma (Excel)."""
    need_time()
    c = db()
    uid = me()
    rep = time_report(c, uid, dict(request.args))
    lg = lang()
    de = dec_comma(lg)  # 2.11.0: every decimal-comma language
    num = (lambda x: f"{x:.2f}".replace(".", ",")) if de else (lambda x: f"{x:.2f}")
    names = {l["id"]: l["name"] for l in rep["lists"]}
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";" if de else ",", lineterminator="\r\n")
    w.writerow([tr("List"), tr("Task"), tr("User"), tr("Start|time"), tr("End|time"), tr("Duration (h)"),
                tr("Duration (h:mm)"), tr("Rounded (h)"), tr("Amount ({0})", rep["currency"]), tr("Note")])
    for e in rep["entries"]:
        lid = e["list_id"] if e["list_id"] in names else 0
        ln = names.get(lid, "")
        lst = next((x for x in rep["lists"] if x["id"] == lid), None)
        ln = tr("Inbox") if lst and lst["is_inbox"] and inbox_default(ln) else (ln or tr("No list"))
        s0 = parse_iso(e["start"]).astimezone(TZ)
        en = parse_iso(e["end"]).astimezone(TZ) if e["end"] else None
        sec, rs = e["seconds"], e["rounded"]
        w.writerow([_csv_cell(ln), _csv_cell(e["title"] or tr("No task")), _csv_cell(e["user_name"]),
                    s0.strftime("%Y-%m-%d %H:%M"), en.strftime("%Y-%m-%d %H:%M") if en else tr("running"),
                    num(sec / 3600), f"{sec // 3600}:{sec % 3600 // 60:02d}", num(rs / 3600),
                    num(e["amount"]) if e["amount"] is not None else "", _csv_cell(e["note"])])
    name = f"{tr('timesheet|file')}-{rep['from'] or 'all'}-{rep['to'] or local_now().date().isoformat()}.csv"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def time_watchdog(c, users, S, LG):
    """Forgotten timers: a push after time_remind_h, auto-stop after time_autostop_h (end = start + N h)."""
    from ..notify.push import _wd_fail
    if not time_all():
        return
    ref = now_utc()
    for r in c.execute("SELECT e.*, t.title AS t_title FROM time_entries e LEFT JOIN tasks t ON t.id=e.task_id "
                       "WHERE e.end IS NULL").fetchall():
        try:
            _time_watch_one(c, r, users, S, LG, ref)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "time entry", r["id"], e)


def _time_watch_one(c, r, users, S, LG, ref):
    from ..notify.push import notify, push_prio
    uid = r["user_id"]
    if uid not in users:
        return
    s, lg = S[uid], LG[uid]
    rem_h, stop_h = _num(s.get("time_remind_h")), _num(s.get("time_autostop_h"))
    start = parse_iso(r["start"])
    hrs = (ref - start).total_seconds() / 3600
    seen = r["list_id"] is not None and list_role(c, r["list_id"], uid) and \
        (not r["task_id"] or task_visible(c, r["task_id"], uid, full=True))
    label = (r["t_title"] if seen else None) or r["task_title"] or tr("No task", lg=lg)
    fnum = (lambda x: f"{x:.1f}".rstrip("0").rstrip(".").replace(".", "," if dec_comma(lg) else "."))
    if stop_h > 0 and hrs >= stop_h:
        end = start + timedelta(hours=stop_h)
        n = c.execute("UPDATE time_entries SET end=?, seconds=?, auto_stopped=1, updated_at=? WHERE id=? AND end IS NULL",
                      (iso(end), int(stop_h * 3600), iso(ref), r["id"])).rowcount
        bump(c)
        c.commit()
        if n:
            notify(uid, tr("Timer stopped automatically", lg=lg),
                   tr("{0} ran {1} h and was stopped at {2}. Correct the end time if needed.", label, fnum(stop_h),
                      end.astimezone(TZ).strftime("%H:%M"), lg=lg), push_prio(s, 4), f"{PUBLIC_URL}/#time", s=s)
    elif rem_h > 0 and hrs >= rem_h and not r["reminded"]:
        c.execute("UPDATE time_entries SET reminded=1 WHERE id=?", (r["id"],))
        c.commit()
        notify(uid, tr("Timer still running", lg=lg), tr("{0} has been running for {1} h. Still on it?", label, fnum(hrs), lg=lg),
               push_prio(s), f"{PUBLIC_URL}/#time", s=s)
