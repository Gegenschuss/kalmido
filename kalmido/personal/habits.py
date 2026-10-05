"""Habits and focus sessions (pomodoro), private per user."""
from datetime import timedelta
from flask import jsonify

from ..core.config import app, TZ
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc, parse_iso, usettings
from ..accounts.session import me
from ..core.access import Denied, need_feat, need_task, tvis, vis_sql
from ..core.serializers import running_pomo
from ..lists.lists import clean_color, clean_list_value
from ..tasks.validation import as_int, valid_hm


# ---------------------------------------------------------------- habits (private per user)

HABIT_FIELDS = ("name", "color", "goal", "days", "remind_at", "sort", "archived", "per_week")


def clean_habit_value(k, v):
    """One habit column from the client, validated (BadInput)."""
    from ..personal.timetrack import BadInput
    if k == "name":
        if not isinstance(v, str) or not v.strip():
            raise BadInput(tr("Name missing"))
        return v.strip()[:200]
    if k == "color":
        return clean_color(v)
    if k == "goal":
        return as_int(v or 1, tr("Goal"), 1, 1000)
    if k == "per_week":
        return as_int(v or 0, tr("Goal"), 0, 7)
    if k == "days":
        v = "".join(dict.fromkeys(x for x in str(v or "") if x in "1234567"))
        return v or "1234567"
    if k == "remind_at":
        if v in (None, ""):
            return ""
        if not valid_hm(v):
            raise BadInput(tr("Invalid value: {0}", tr("Time")))
        return v
    if k == "sort":
        return clean_list_value("sort", v)
    if k == "archived":
        return 1 if v else 0
    return v


def need_habit(c, hid):
    if not c.execute("SELECT 1 FROM habits WHERE id=? AND user_id=?", (hid, me())).fetchone():
        raise Denied(404)


@app.post("/api/habits")
def habit_create():
    need_feat("habits")
    b = body()
    name = (b.get("name") or "").strip()
    if not name:
        return err(tr("Name missing"))
    c = db()
    srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM habits WHERE user_id=?", (me(),)).fetchone()[0]
    v = {k: clean_habit_value(k, b.get(k, d)) for k, d in (("color", ""), ("goal", 1), ("days", "1234567"),
                                                            ("remind_at", ""), ("per_week", 0))}
    cur = c.execute("INSERT INTO habits(name,color,goal,days,remind_at,sort,per_week,created_at,user_id) VALUES(?,?,?,?,?,?,?,?,?)",
                    (name[:200], v["color"], v["goal"], v["days"], v["remind_at"], srt, v["per_week"], iso(now_utc()), me()))
    bump(c)
    c.commit()
    return jsonify(id=cur.lastrowid)


@app.patch("/api/habits/<int:hid>")
def habit_update(hid):
    b = body()
    c = db()
    need_habit(c, hid)
    vals = {k: clean_habit_value(k, b[k]) for k in HABIT_FIELDS if k in b}  # BadInput: 400, nothing stored
    for k, v in vals.items():
        c.execute(f"UPDATE habits SET {k}=? WHERE id=?", (v, hid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.delete("/api/habits/<int:hid>")
def habit_delete(hid):
    c = db()
    need_habit(c, hid)
    c.execute("DELETE FROM habits WHERE id=?", (hid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/habits/<int:hid>/log")
def habit_log(hid):
    need_feat("habits")
    b = body()
    day = b.get("day") or local_now().date().isoformat()
    c = db()
    need_habit(c, hid)
    old = c.execute("SELECT count, note FROM habit_logs WHERE habit_id=? AND day=?", (hid, day)).fetchone()
    cnt = max(0, int(b["count"])) if "count" in b else (old["count"] if old else 0)
    note = (b.get("note") or "").strip()[:500] if "note" in b else (old["note"] if old else "")
    if cnt or note:  # a note keeps the day even when it is not ticked
        c.execute("INSERT INTO habit_logs(habit_id,day,count,note) VALUES(?,?,?,?) "
                  "ON CONFLICT(habit_id,day) DO UPDATE SET count=excluded.count, note=excluded.note",
                  (hid, day, cnt, note))
    else:
        c.execute("DELETE FROM habit_logs WHERE habit_id=? AND day=?", (hid, day))
    bump(c)
    c.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- pomodoro (private per user)

def pomo_elapsed(p, ref=None):
    ref = ref or now_utc()
    end = parse_iso(p["end"]) if p["end"] else (parse_iso(p["paused_at"]) if p["paused_at"] else ref)
    return max(0, (end - parse_iso(p["start"])).total_seconds() - p["paused_s"])


def pomo_planned_end(p):
    """A timed session (focus / break) that is not paused: when it is due to end (start + minutes + pauses)."""
    if p["minutes"] <= 0 or p["paused_at"] or p["end"]:
        return None
    return parse_iso(p["start"]) + timedelta(seconds=p["minutes"] * 60 + (p["paused_s"] or 0))


def pomo_close(c, p, at, done):
    """Ends a session at `at` (focus on a task -> time entry, see focus_to_entry)."""
    from ..personal.timetrack import focus_to_entry
    n = c.execute("UPDATE pomos SET end=?, done=?, notified=1 WHERE id=? AND end IS NULL", (iso(at), done, p["id"])).rowcount
    if n:
        focus_to_entry(c, p["id"])
    return n


def pomo_stats(c, days=1, uid=None):
    since = local_now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    rows = c.execute("SELECT * FROM pomos WHERE kind IN ('focus','stopwatch') AND end IS NOT NULL AND start>=? AND user_id=?",
                     (iso(since), uid or me())).fetchall()
    return dict(count=sum(1 for r in rows if r["done"] and r["kind"] == "focus"),
                minutes=round(sum(pomo_elapsed(r) for r in rows) / 60))


@app.post("/api/pomo/start")
def pomo_start():
    from ..personal.timetrack import focus_to_entry
    need_feat("pomo")
    b = body()
    c = db()
    s = usettings(c, me())
    kind = b.get("kind", "focus")
    mins = 0 if kind == "stopwatch" else int(b.get("minutes") or s["pomo_" + ("focus" if kind == "focus" else "short")])
    ts = iso(now_utc())
    for p in c.execute("SELECT * FROM pomos WHERE end IS NULL AND user_id=?", (me(),)).fetchall():  # one at a time
        c.execute("UPDATE pomos SET end=? WHERE id=?", (ts, p["id"]))
        focus_to_entry(c, p["id"])
    task = b.get("task_id")
    try:
        if task:
            need_task(c, int(task), write=False, full=True)
    except (Denied, TypeError, ValueError):
        task = None
    c.execute("INSERT INTO pomos(task_id,kind,minutes,start,user_id) VALUES(?,?,?,?,?)",
              (task, kind, mins, ts, me()))
    bump(c)
    c.commit()
    return jsonify(running_pomo(c))


@app.post("/api/pomo/<int:pid>/<action>")
def pomo_action(pid, action):
    from ..personal.timetrack import focus_to_entry
    c = db()
    p = c.execute("SELECT * FROM pomos WHERE id=? AND user_id=?", (pid, me())).fetchone()
    if not p:
        return err(tr("unknown"), 404)
    ts = now_utc()
    if action == "pause" and not p["paused_at"] and not p["end"]:
        c.execute("UPDATE pomos SET paused_at=? WHERE id=?", (iso(ts), pid))
    elif action == "resume" and p["paused_at"]:
        add = int((ts - parse_iso(p["paused_at"])).total_seconds())
        c.execute("UPDATE pomos SET paused_at=NULL, paused_s=paused_s+? WHERE id=?", (add, pid))
    elif action in ("stop", "finish") and not p["end"]:
        done = 1 if action == "finish" or pomo_elapsed(p) >= p["minutes"] * 60 - 5 else 0
        planned = pomo_planned_end(p)
        at = min(ts, planned) if planned else ts  # 1.2: a late finish ends at the planned end, not hours later
        c.execute("UPDATE pomos SET end=?, done=?, paused_at=NULL, paused_s=paused_s+? WHERE id=?",
                  (iso(at), done,
                   int((ts - parse_iso(p["paused_at"])).total_seconds()) if p["paused_at"] else 0, pid))
        focus_to_entry(c, pid)
    bump(c)
    c.commit()
    return jsonify(pomo=running_pomo(c), today=pomo_stats(c, 1))


@app.get("/api/pomo/stats")
def pomo_stats_api():
    c = db()
    since = local_now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29)
    rows = c.execute(f"""SELECT p.*, t.title FROM pomos p
                         LEFT JOIN tasks t ON t.id=p.task_id AND t.list_id IN {vis_sql()} AND {tvis(c, me(), "t.")}
                         WHERE p.user_id=? AND p.kind IN ('focus','stopwatch') AND p.end IS NOT NULL AND p.start>=?
                         ORDER BY p.start DESC""", (me(), me(), me(), iso(since))).fetchall()
    per_day, per_task = {}, {}
    for r in rows:
        d = parse_iso(r["start"]).astimezone(TZ).date().isoformat()
        m = pomo_elapsed(r) / 60
        per_day[d] = per_day.get(d, 0) + m
        k = r["title"] or tr("No task")
        per_task[k] = per_task.get(k, 0) + m
    recent = [dict(id=r["id"], title=r["title"], start=r["start"], minutes=round(pomo_elapsed(r) / 60),
                   done=r["done"]) for r in rows[:30]]
    return jsonify(today=pomo_stats(c, 1), week=pomo_stats(c, 7),
                   per_day={k: round(v) for k, v in per_day.items()},
                   per_task=sorted(([k, round(v)] for k, v in per_task.items()), key=lambda x: -x[1])[:10],
                   recent=recent)
