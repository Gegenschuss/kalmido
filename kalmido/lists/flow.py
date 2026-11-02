"""2.393.2 A (#3374): flow figures of a project, computed on read from the task history (no own storage).

  * lead time: created -> completed (median and 85th percentile in days) of the tasks completed in the period
  * cycle time: first entry into an "in progress" column -> completed (median) of the same tasks
  * cumulative flow: open tasks per column at the end of every day of the period, plus the strand "done" (tasks completed
    within the period, growing); a task counts from its creation (or its last move into this list)
  * bug trend: per ISO week of the period the bugs (ticket type bug) created vs. completed

The column of a task over time comes from its current column and the history entries "section" (activity kind
'section', data {name}, tasks/validation.py log_changes): after a move the task stands in the named column (matched by name
to the list's columns today; a name no column carries any more = "earlier column"), before its first move in the list
it counts as "no column" (the history does not record the column a task was created in). Counted: the top-level tasks of
the list (no subtasks, no milestones) the viewer fully sees (a participant: only theirs), at most FLW_MAX, newest first.
A list with the lock (end-to-end encryption) has no column names on the server: only metadata is used (lead time, bug
trend, open / done), the columns and the cycle time stay empty."""
import json
from datetime import datetime, time, timedelta, timezone

from ..core.access import list_role, pvis
from ..core.db import TZ, local_day, local_now, parse_iso
from ..core.pg import st_ids

FLW_DAYS = (30, 90)
FLW_MAX = 2000  # tasks per query (the newest ones); more = capped: true in the answer
# Until columns carry a status meaning (#3354, section_kind) a column counts as "in progress" by its name. #3354 replaces
# is_wip_section; nothing else here reads these names.
FLW_WIP_NAMES = ("in arbeit", "in progress", "doing", "wip")


def is_wip_section(section):
    """True when the column (a sections row / dict with name) means "work has started"."""
    nm = (section.get("name") if isinstance(section, dict) else section["name"]) or ""
    return nm.strip().casefold() in FLW_WIP_NAMES


def flw_pct(xs, p):
    """The p-th percentile (0..100) of xs, linear between the ranks (like a spreadsheet's PERCENTILE.INC); None when empty."""
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def flw_r1(v):
    return None if v is None else round(v + 1e-9, 1)


def flw_ts(v):
    """A stored UTC timestamp as an aware datetime; None for an empty / unreadable one."""
    if not v:
        return None
    try:
        d = parse_iso(v)
    except (ValueError, TypeError, OverflowError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def flw_day_end(d):
    """The end of local day d (the moment the cumulative flow takes its state) as an aware datetime."""
    return datetime.combine(d + timedelta(days=1), time(0), tzinfo=TZ)


def flw_week(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def flw_tasks(c, lid, uid, since):
    """(rows, capped): the counted tasks of list lid -- open ones and those closed since `since` (UTC ISO text)."""
    rows = c.execute("""SELECT id, section_id, status, created_at, completed_at, ttype FROM tasks
                        WHERE list_id=? AND deleted_at IS NULL AND parent_id IS NULL AND ms=0
                          AND (status=0 OR completed_at >= ?) ORDER BY id DESC LIMIT ?""", (lid, since, FLW_MAX + 1)).fetchall()
    capped = len(rows) > FLW_MAX
    rows = [dict(r) for r in rows[:FLW_MAX]]
    if uid and list_role(c, lid, uid) == "participant":
        wr = pvis(c, uid, lid)[1]  # only what they fully see (no context parents)
        rows = [r for r in rows if r["id"] in wr]
    return rows, capped


def flw_history(c, ids):
    """{task id: [(at, kind, name)]} oldest first: the moves between columns ('section') and into this list ('list')."""
    out = {}
    if not ids:
        return out
    for r in c.execute("""SELECT task_id, kind, data, created_at FROM activity WHERE task_id = ANY(CAST(? AS BIGINT[]))
                          AND kind IN ('section', 'list') ORDER BY task_id, created_at, id""", (st_ids(sorted(ids)),)):
        d = r["data"]
        if isinstance(d, str):
            try:
                d = json.loads(d or "{}")
            except ValueError:
                d = {}
        at = flw_ts(r["created_at"])
        if at:
            out.setdefault(r["task_id"], []).append((at, r["kind"], (d or {}).get("name") if isinstance(d, dict) else None))
    return out


def flw_timeline(t, hist, by_name, e2e):
    """(since, [(from, column key)]) of task t: since = when it came into the list; the column keys (section id, None = no
    column, "gone" = a column that does not exist any more) from that moment on, oldest first."""
    since = flw_ts(t["created_at"])
    ev = hist.get(t["id"], [])
    for at, kind, _ in ev:
        if kind == "list" and (since is None or at > since):
            since = at  # the last move into this list (a task that is here now came here last)
    moves = [(at, nm) for at, kind, nm in ev if kind == "section" and (since is None or at >= since)]
    if e2e:
        return since, [(since, None)]
    if not moves:
        return since, [(since, t["section_id"])]
    seg = [(since, None)]  # before its first move: the history does not know the column it was created in
    for i, (at, nm) in enumerate(moves):
        if i == len(moves) - 1:
            key = t["section_id"]  # the newest move: the column it stands in now (also after a rename)
        elif nm is None:
            key = None
        else:
            key = by_name.get(nm.strip().casefold(), "gone")
        seg.append((at, key))
    return since, seg


def flw_compute(c, lid, uid, days=30):
    """The flow figures of list lid for the viewer uid over the last `days` days (today included). The caller checked that
    uid sees the list."""
    days = days if days in FLW_DAYS else FLW_DAYS[0]
    today = local_now().date()
    start = today - timedelta(days=days - 1)
    since = datetime.combine(start - timedelta(days=1), time(0)).isoformat()  # a day early: stored times are UTC
    lr = c.execute("SELECT e2e FROM lists WHERE id=?", (lid,)).fetchone()
    e2e = bool(lr and lr["e2e"])
    secs = [dict(r) for r in c.execute("SELECT id, name, sort FROM sections WHERE list_id=? ORDER BY sort, id", (lid,)).fetchall()]
    by_name = {}
    if not e2e:
        for s in secs:
            by_name.setdefault((s["name"] or "").strip().casefold(), s["id"])
    wip = set() if e2e else {s["id"] for s in secs if is_wip_section(s)}
    rows, capped = flw_tasks(c, lid, uid, since)
    hist = flw_history(c, [r["id"] for r in rows])
    lead, cyc = [], []
    ends = [flw_day_end(start + timedelta(days=i)) for i in range(days)]
    cnt = [dict() for _ in range(days)]
    done_n = [0] * days
    weeks = {}
    d = start
    while d <= today:
        weeks.setdefault(flw_week(d), {"week": flw_week(d), "created": 0, "done": 0})
        d += timedelta(days=1)
    for t in rows:
        created, closed = flw_ts(t["created_at"]), flw_ts(t["completed_at"]) if t["status"] != 0 else None
        cday = local_day(t["completed_at"]) if closed else None
        since_t, seg = flw_timeline(t, hist, by_name, e2e)
        if t["status"] == 2 and closed and cday and start <= cday <= today:
            if created and closed >= created:
                lead.append((closed - created).total_seconds() / 86400)
            first = next((at for at, key in seg if key in wip), None)
            if first and closed >= first:
                cyc.append((closed - first).total_seconds() / 86400)
        if (t["ttype"] or "") == "bug":
            cd = local_day(t["created_at"])
            if cd and start <= cd <= today:
                weeks[flw_week(cd)]["created"] += 1
            if t["status"] == 2 and cday and start <= cday <= today:
                weeks[flw_week(cday)]["done"] += 1
        if since_t is None:
            continue
        for i, e in enumerate(ends):
            if since_t >= e:
                continue
            if closed and closed < e:
                if t["status"] == 2 and cday and cday >= start:
                    done_n[i] += 1
                continue  # closed before this day ended (won't do: leaves the diagram)
            key = None
            for at, k in seg:
                if at is None or at < e:
                    key = k
                else:
                    break
            cnt[i][key] = cnt[i].get(key, 0) + 1
    used = set().union(*[set(x) for x in cnt]) if cnt else set()
    cols = [{"key": s["id"], "id": s["id"], "name": s["name"], "wip": s["id"] in wip} for s in secs if s["id"] in used]
    if "gone" in used:
        cols.append({"key": "gone", "id": None, "name": None, "wip": False})
    if None in used:
        cols.insert(0, {"key": None, "id": None, "name": None, "wip": False})
    cfd = [{"day": (start + timedelta(days=i)).isoformat(), "done": done_n[i],
            "columns": [cnt[i].get(k["key"], 0) for k in cols]} for i in range(days)]
    return {"days": days, "start": start.isoformat(), "end": today.isoformat(), "capped": capped, "tasks": len(rows), "e2e": e2e,
            "lead_time": {"median": flw_r1(flw_pct(lead, 50)), "p85": flw_r1(flw_pct(lead, 85)), "n": len(lead)},
            "cycle_time": {"median": flw_r1(flw_pct(cyc, 50)), "p85": flw_r1(flw_pct(cyc, 85)), "n": len(cyc),
                           "columns": [s["id"] for s in secs if s["id"] in wip]},
            "cfd": {"columns": [{"id": k["id"], "name": k["name"], "kind": "gone" if k["key"] == "gone" else "none" if k["key"] is None
                                 else "column", "wip": k["wip"]} for k in cols], "days": cfd},
            "bugs": sorted(weeks.values(), key=lambda w: w["week"])}


def flw_days_arg(v):
    """?days= -> 30 / 90; None for anything else."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n in FLW_DAYS else None

