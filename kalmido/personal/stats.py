"""Statistics (module "stats")."""
from datetime import datetime, timedelta
from flask import jsonify, request

from ..core.config import app, TZ
from ..core.db import db, iso, local_day as _local_day, local_now, now_utc
from ..accounts.session import me
from ..core.access import PROJ_SQL, time_all
from ..core.state import visible_lists
from ..personal.habits import pomo_elapsed
from ..personal.timetrack import entry_secs


# ---------------------------------------------------------------- statistics (per user)
# Completions count for the person who completed (tasks.completed_by; done copies of recurring tasks
# are the completions of their occurrences), won't-do is not a completion. Tasks in the trash still
# count until the trash is emptied. Window: the last 12 weeks (starting on the viewer's first weekday, incl. the current
# one). Open tasks of archived lists are left out of the overdue trend (1.5.1).
# Overdue trend: at the end of each week (today for the current one), the tasks I am responsible for
# (assigned to me, or unassigned in my own lists) whose due date had passed and that were still open,
# based on today's due dates. On time: completed on or before the due day.
STATS_WEEKS = 12


@app.get("/api/stats")
def stats_api():
    c = db()
    uid = me()
    today = local_now().date()
    # 1.5.1: weeks start on the viewer's first weekday (?ws= 0 Sunday .. 6 Saturday, as JavaScript counts; default Monday)
    ws = request.args.get("ws", "1")
    ws = (int(ws) + 6) % 7 if ws.isdigit() and int(ws) < 7 else 0  # -> Python's weekday(): 0 = Monday
    mon0 = today - timedelta(days=(today.weekday() - ws) % 7) - timedelta(weeks=STATS_WEEKS - 1)
    weeks = [mon0 + timedelta(weeks=i) for i in range(STATS_WEEKS)]
    lo = iso(datetime(mon0.year, mon0.month, mon0.day, tzinfo=TZ))
    vis = {l["id"]: l for l in visible_lists(c, uid)}
    wk = lambda d: (d - mon0).days // 7  # noqa: E731

    days_all, per_day, per_week, by_list = set(), {}, [0] * STATS_WEEKS, {}
    with_due = ontime = 0
    for r in c.execute("""SELECT list_id, due, completed_at FROM tasks WHERE completed_by=? AND status=2
                          AND completed_at IS NOT NULL""", (uid,)):
        d = _local_day(r["completed_at"])
        days_all.add(d)
        if d < mon0 or d > today:
            continue
        per_day[d.isoformat()] = per_day.get(d.isoformat(), 0) + 1
        per_week[wk(d)] += 1
        k = r["list_id"] if r["list_id"] in vis else 0
        by_list[k] = by_list.get(k, 0) + 1
        if r["due"]:
            with_due += 1
            ontime += d.isoformat() <= r["due"]

    # streak: days in a row with at least one completion (today still counts as "running" when empty)
    cur, d = 0, today if today in days_all else today - timedelta(days=1)
    while d in days_all:
        cur, d = cur + 1, d - timedelta(days=1)
    best, run, prev = 0, 0, None
    for d in sorted(days_all):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        best, prev = max(best, run), d

    samples = [w + timedelta(days=6) for w in weeks[:-1]] + [today]
    over = [0] * len(samples)
    for r in c.execute("""SELECT t.due, t.status, t.created_at, t.completed_at, t.deleted_at FROM tasks t JOIN lists l ON l.id=t.list_id
                          WHERE t.due IS NOT NULL AND t.due<? AND l.archived=0 AND (t.assignee_id=? OR (t.assignee_id IS NULL AND l.owner_id=?))
                            AND (t.status=0 OR t.completed_at>=?)""", (today.isoformat(), uid, uid, lo)):
        created, done, deleted = _local_day(r["created_at"]), _local_day(r["completed_at"]), _local_day(r["deleted_at"])
        if r["status"] != 0 and not done:
            continue
        for i, s in enumerate(samples):
            if r["due"] < s.isoformat() and created <= s and (not deleted or deleted > s) \
                    and (r["status"] == 0 or done > s):
                over[i] += 1

    f_day, f_week, f_list = {}, [0.0] * STATS_WEEKS, {}
    for p in c.execute("""SELECT p.*, t.list_id FROM pomos p LEFT JOIN tasks t ON t.id=p.task_id
                          WHERE p.user_id=? AND p.kind IN ('focus','stopwatch') AND p.end IS NOT NULL AND p.start>=?""", (uid, lo)):
        d = _local_day(p["start"])
        if d < mon0 or d > today:
            continue
        m = pomo_elapsed(p) / 60
        f_day[d.isoformat()] = f_day.get(d.isoformat(), 0) + m
        f_week[wk(d)] += m
        k = (p["list_id"] if p["list_id"] in vis else 0) if p["task_id"] else -1
        f_list[k] = f_list.get(k, 0) + m

    # tracked time (module "time"): my entries by the local day they start (running timer up to now)
    t_week, t_list, ref = [0] * STATS_WEEKS, {}, now_utc()
    for e in c.execute(f"SELECT start, end, seconds, list_id FROM time_entries WHERE user_id=? AND start>=? AND (list_id IS NULL OR list_id IN {PROJ_SQL})", (uid, lo)):
        d = _local_day(e["start"])
        if d < mon0 or d > today:
            continue
        sec = entry_secs(e, ref)
        t_week[wk(d)] += sec
        k = e["list_id"] if e["list_id"] in vis else 0
        t_list[k] = t_list.get(k, 0) + sec

    def lst(k):
        l = vis.get(k)
        return {"id": k, "name": l["name"] if l else "", "is_inbox": bool(l and l["is_inbox"]), "color": l["color"] if l else ""}
    return jsonify(
        today=today.isoformat(), weeks=[w.isoformat() for w in weeks],
        done={"per_day": per_day, "per_week": per_week, "total": sum(per_week),
              "today": per_day.get(today.isoformat(), 0), "this_week": per_week[-1],
              "by_list": sorted(({**lst(k), "n": n} for k, n in by_list.items()), key=lambda x: (-x["n"], x["id"] == 0))},
        ontime={"with_due": with_due, "ontime": ontime, "rate": round(100 * ontime / with_due) if with_due else None},
        streak={"current": cur, "best": best},
        overdue=[{"date": s.isoformat(), "n": n} for s, n in zip(samples, over)],
        focus={"per_day": {k: round(v) for k, v in f_day.items()}, "per_week": [round(v) for v in f_week],
               "total": round(sum(f_week)), "this_week": round(f_week[-1]),
               "by_list": sorted(({**lst(k), "minutes": round(v)} for k, v in f_list.items() if round(v)),
                                 key=lambda x: -x["minutes"])},
        time=None if not time_all() else {"per_week": [round(v / 60) for v in t_week], "total": round(sum(t_week) / 60), "this_week": round(t_week[-1] / 60),
              "by_list": sorted(({**lst(k), "minutes": round(v / 60)} for k, v in t_list.items() if round(v / 60)),
                                key=lambda x: -x["minutes"])},
    )
