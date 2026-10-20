"""Workload (#463, module "workload"): planned hours per person and week against their capacity, within the organisation."""
from datetime import date, timedelta

from flask import g, jsonify, request

from ..core.db import body, bump, db, err, local_now, usettings, uset
from ..core.config import app
from ..core.i18n import tr
from ..accounts.session import me, user_public
from ..core.access import Denied, need_feat, tvis, vis_sql
from ..personal.timetrack import BadInput


# ---------------------------------------------------------------- 2.23.0 (#463): workload
# Who has how much on their plate, week by week: the open tasks assigned to a person, counted in the week of their
# planned start (day plan), else their due date, else their start (overdue ones in the current week), weighed with their
# estimate (tasks.duration in minutes, the same field the calendar and the day plan use). Tasks without an estimate are
# counted separately ("+ 3 without an estimate"); tasks without a date go to "No date". Capacity: the person's hours per
# week (Settings, capacity_h), else 5 x the instance's hours per day. Only what the person asking may see is counted (their
# lists, a participant's own tasks), and only the people of their organisation (the visibility rules of #752 on top);
# admins choose the organisation (?org=). Agents and kids are never rows. 80 % amber, over 100 % red.
WL_WEEKS_MAX = 12


def capacity_h(c, uid):
    from ..personal.timetrack import time_day_h
    v = usettings(c, uid).get("capacity_h") or ""
    try:
        x = float(v)
        if x > 0:
            return round(x, 2)
    except ValueError:
        pass
    return round(time_day_h(c) * 5, 2)


def wl_people(c, uid, org=None):
    """[(id, row)] of the people of the workload view for uid: the organisation (org, else uid's first), visible to uid."""
    from ..accounts.orgs import user_orgs, visible_people
    u = g.user
    mine = user_orgs(c, uid)
    if org is not None:
        if org not in mine and not u["is_admin"]:
            raise Denied(404)
        orgs = [org]
    else:
        orgs = mine[:1]
    vis = visible_people(c, uid)
    q = "SELECT * FROM users WHERE disabled=0 AND kid=0 AND COALESCE(kind,'user')!='agent'"
    if orgs:
        q += f" AND id IN (SELECT user_id FROM org_members WHERE org_id IN ({','.join(str(int(x)) for x in orgs)}))"
    rows = c.execute(q + " ORDER BY lower(display_name), id").fetchall()
    if (u["kind"] or "user") == "agent":  # 2.86.0 (N34): an agent sees only the people who share a list with it, not the whole organisation
        sh = {r[0] for r in c.execute(f"SELECT owner_id FROM lists WHERE id IN {vis_sql()} UNION "
                                      f"SELECT user_id FROM list_members WHERE list_id IN {vis_sql()}", (uid, uid, uid, uid))}
        rows = [r for r in rows if r["id"] in sh]
    return [r for r in rows if vis is None or r["id"] in vis], (orgs[0] if orgs else None)


def workload(c, uid, start=None, weeks=4, org=None):
    today = local_now().date()
    try:
        d0 = date.fromisoformat(start) if start else today
    except ValueError:
        raise BadInput(tr("Invalid date or time")) from None
    d0 = d0 - timedelta(days=d0.weekday())  # Monday
    weeks = max(1, min(WL_WEEKS_MAX, int(weeks)))
    bounds = [(d0 + timedelta(weeks=i), d0 + timedelta(weeks=i, days=6)) for i in range(weeks)]
    people, oid = wl_people(c, uid, org)
    ids = [p["id"] for p in people]
    out = {p["id"]: {**user_public(p), "capacity_h": capacity_h(c, p["id"]), "own": p["id"] == uid,
                     "weeks": [{"minutes": 0, "tasks": 0, "unestimated": 0, "ids": []} for _ in bounds],
                     "nodate": {"minutes": 0, "tasks": 0, "unestimated": 0, "ids": []}} for p in people}
    if ids:
        q = ",".join("?" * len(ids))
        rows = c.execute(f"""SELECT id, assignee_id, due, start, plan_start, duration FROM tasks
                             WHERE status=0 AND deleted_at IS NULL AND ms=0 AND assignee_id IN ({q})
                               AND list_id IN {vis_sql()} AND {tvis(c, uid)}""", (*ids, uid, uid)).fetchall()
        cur_week = today - timedelta(days=today.weekday())
        for t in rows:
            raw = (t["plan_start"] or "")[:10] or t["due"] or t["start"]
            cell = None
            if raw:
                try:
                    d = date.fromisoformat(raw)
                except ValueError:
                    d = None
                if d is not None:
                    if d < cur_week and bounds[0][0] <= cur_week <= bounds[-1][1]:
                        d = cur_week  # overdue: still on the plate this week
                    cell = next((out[t["assignee_id"]]["weeks"][i] for i, (a, b) in enumerate(bounds) if a <= d <= b), None)
                    if cell is None:
                        continue  # outside the range
            if cell is None:
                cell = out[t["assignee_id"]]["nodate"]
            cell["tasks"] += 1
            if t["duration"]:
                cell["minutes"] += int(t["duration"])
            else:
                cell["unestimated"] += 1
            if len(cell["ids"]) < 200:
                cell["ids"].append(t["id"])
    # 2.50.0 (#1195): absent workdays and public holidays of the area lower a week's capacity (0 for a week away)
    from ..hub.absence import abs_capacity_factor, abs_days, abs_holidays, abs_state
    from ..office.model import pb_personal
    aoid = oid or pb_personal(c, uid, create=False)
    gone = abs_days(c, ids, bounds[0][0], bounds[-1][1], aoid) if aoid else {}
    hol = abs_holidays(abs_state(c, aoid), bounds[0][0], bounds[-1][1])
    from ..hub.leave import wt_workdays
    for pid, p in out.items():
        wd = wt_workdays(c, pid)  # 2.125.0 A (#2118): the weekly hours spread over the person's working days
        for w, (a, b) in zip(p["weeks"], bounds):
            f = abs_capacity_factor(gone.get(pid, {}), hol, a, b, wd)
            w["capacity_h"] = round(p["capacity_h"] * f, 2)
            w["absent_days"] = sum(v for k, v in gone.get(pid, {}).items() if a.isoformat() <= k <= b.isoformat() and date.fromisoformat(k).weekday() in wd)
    for p in out.values():
        for w in p["weeks"]:
            cap = w.get("capacity_h", p["capacity_h"])
            w["pct"] = round(w["minutes"] / 60 / cap * 100) if cap else (None if not w["minutes"] else 999)
            w["level"] = "none" if w["pct"] is None else "over" if w["pct"] > 100 else "warn" if w["pct"] >= 80 else "ok"
    from ..accounts.orgs import user_orgs
    orgs = [{"id": r[0], "name": r[1]} for r in c.execute("SELECT id, name FROM orgs WHERE personal_of IS NULL ORDER BY lower(name), id")
            if g.user["is_admin"] or r[0] in user_orgs(c, uid)]
    return {"weeks": [{"start": a.isoformat(), "end": b.isoformat()} for a, b in bounds], "people": [out[i] for i in ids],
            "org_id": oid, "orgs": orgs, "today": today.isoformat()}


@app.get("/api/workload")
def workload_get():
    """?start=YYYY-MM-DD (the week of it) &weeks=1..12 (4) &org=<id> (admins / people in several organisations). Also
    GET /api/v1/workload."""
    c = db()
    if (g.user["kind"] or "user") != "agent":
        need_feat("workload")
    if g.user["kid"]:
        raise Denied(403)
    a = request.args
    try:
        org = int(a["org"]) if a.get("org") else None
        weeks = int(a.get("weeks") or 4)
    except ValueError:
        return err(tr("Invalid data"))
    return jsonify(workload(c, me(), a.get("start"), weeks, org))


@app.put("/api/workload/capacity/<int:uid>")
def workload_capacity(uid):
    """{hours: number | null}: hours per week of a person (oneself, or an admin for anyone; null = the default)."""
    c = db()
    if uid != me() and not g.user["is_admin"]:
        raise Denied(403, tr("Only admins can change the capacity of other people"))
    if not c.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
        raise Denied(404)
    from ..accounts.settings import clean_setting
    v = clean_setting("capacity_h", body().get("hours"))
    uset(c, uid, "capacity_h", v or "")
    bump(c)
    c.commit()
    return jsonify(id=uid, capacity_h=capacity_h(c, uid))
