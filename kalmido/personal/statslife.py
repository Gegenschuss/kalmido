"""2.630.0 (#4617): the statistics blocks of Home & life -- contracts, health and travel (GET /api/stats).
Each block only while its module is on (Settings > Modules), the workspace filter (?space=) holds, and only the person's own
numbers, by the rule of the overdue trend: a task is mine when it is assigned to me, or unassigned in a list I own;
completions count for the person who ticked them off (tasks.completed_by), as in the rest of the statistics. A trip is mine
when I own its project. Health -- names of people included -- is never shown to an agent or an API token without the
scope "private" (health_hidden), an organisation's trips never to an agent / token (org_trips_hidden); health is private
anyway, so an organisation's view has no health block. The completed tasks of these lists keep counting in "Completed" and
"By project" (stats.py)."""
import json
import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from ..core.access import Denied, health_hidden, org_trips_hidden, vis_sql
from ..core.db import local_day, local_now
from ..life.model import contract_end, feat_on, PER_MONTHS

STL_NOTICE_DAYS = 90   # the contracts' "next deadlines to cancel": the next 90 days
STL_NEXT_MAX = 5       # health: the next due appointments shown
STL_MED = "medication"
# The product rule (04.11.2026, #4617): every module of Home & life (LIFE_MODS, kalmido/life/model.py) brings its block
# of the statistics (a key of GET /api/stats + a block of LY.stats, static/js/dashboard.js) -- or stands here with the reason
# why not. tests/p2630_c_stats_blocks_test.py fails for a new module with neither.
STL_NO_BLOCK = {
    "home": "devices and upkeep are reminders without a measure over time; their dates count in Overdue and Completed",
    "care": "staying in touch is a rhythm per contact (the daily push, Home & life), nothing that adds up over weeks",
    "review": "is itself the look back (the day / week in review)",
    "reading": "read-later items are plain tasks: ticked off they count in Completed and By project",
    "budget": "has its own evaluation (the household budget view), private like health",
}


def stl_key(s):
    """The same provider / person however it is written: case and spaces do not matter."""
    return re.sub(r"\s+", " ", s or "").strip().casefold()


def stl_label(names):
    """The spelling shown for a group: the most frequent one (the first seen on a tie)."""
    return Counter(re.sub(r"\s+", " ", n).strip() for n in names).most_common(1)[0][0] if names else ""


def _fam(v):
    try:
        f = json.loads(v or "")
    except ValueError:
        return {}
    return f if isinstance(f, dict) else {}


def _mine_sql(tw):
    """Tasks t of lists l that are mine (assigned to me, or unassigned in my own list), not deleted, not in an archived,
    deleted or locked (e2e) project; tw = the workspace narrowing of stats.py. Four ? = uid: and only lists the request may
    see (vis_sql: the token's list allowlist, an agent's data lock, the organisation boundary - Fable review 2.630)."""
    return f"""FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.deleted_at IS NULL AND l.archived=0 AND l.deleted_at IS NULL
               AND l.e2e IS NULL AND (t.assignee_id=? OR (t.assignee_id IS NULL AND l.owner_id=?)) AND t.list_id IN {vis_sql()}{tw}"""


def stl_contracts(c, uid, today, tw):
    """The running contracts: how many, the cost per month / year, the deadlines to cancel of the next 90 days, by provider."""
    items = []
    for r in c.execute(f"SELECT t.id, t.title, t.due, t.fam {_mine_sql(tw)} AND t.status=0 AND t.fam LIKE ? ORDER BY t.id",
                       (uid, uid, uid, uid, '%"kind":"contract"%')):
        f = _fam(r["fam"])
        if f.get("kind") != "contract":
            continue
        end = contract_end(r["due"], f)
        if end and end < today.isoformat():
            continue  # its term is over (it did not renew): not running any more
        cost = f.get("cost")
        monthly = cost / PER_MONTHS.get(f.get("per") or "month", 1) if isinstance(cost, (int, float)) else None
        items.append({"task_id": r["id"], "name": f.get("name") or r["title"], "provider": f.get("provider") or "", "due": r["due"],
                      "monthly": monthly})
    hi = (today + timedelta(days=STL_NOTICE_DAYS)).isoformat()
    notice = sorted(({"task_id": x["task_id"], "name": x["name"], "provider": x["provider"], "due": x["due"],
                      "days": (date.fromisoformat(x["due"]) - today).days}
                     for x in items if x["due"] and today.isoformat() <= x["due"] <= hi), key=lambda x: (x["due"], x["task_id"]))
    groups = {}
    for x in items:
        groups.setdefault(stl_key(x["provider"]), []).append(x)
    by = [{"name": stl_label([x["provider"] for x in xs]) if k else "", "n": len(xs),
           "monthly": round(sum(x["monthly"] or 0 for x in xs), 2)} for k, xs in groups.items()]
    by.sort(key=lambda x: (-x["monthly"], -x["n"], x["name"] == "", x["name"].casefold()))
    monthly = round(sum(x["monthly"] or 0 for x in items), 2)
    return {"count": len(items), "monthly": monthly, "yearly": round(monthly * 12, 2), "notice": notice, "notice_days": STL_NOTICE_DAYS,
            "by_provider": by}


def stl_health(c, uid, today, mon0, weeks, tw):
    """Per person (fam.who; empty = me): appointments / check-ups / vaccinations done in the last weeks (per week), the next
    due one and how many are overdue; medication apart as "intakes done x of y" (one task per intake and day)."""
    now = local_now()
    hm = now.strftime("%H:%M")
    people = {}

    def person(who):
        p = people.get(stl_key(who))
        if p is None:
            p = people[stl_key(who)] = {"names": [], "per_week": [0] * weeks, "done": 0, "next": None, "overdue": 0,
                                        "med_done": 0, "med_due": 0}
        p["names"].append(who or "")
        return p

    sql = f"""SELECT t.id, t.title, t.due, t.due_time, t.status, t.completed_at, t.completed_by, t.repeat, t.fam {_mine_sql(tw)}
              AND l.life='health' AND t.fam LIKE ? AND (t.status=0 OR (t.status=2 AND t.completed_by=? AND t.completed_at IS NOT NULL)) ORDER BY t.id"""
    nxt = []
    for r in c.execute(sql, (uid, uid, uid, uid, '%"kind":"health"%', uid)):
        f = _fam(r["fam"])
        if f.get("kind") != "health":
            continue
        p, med = person(f.get("who") or ""), f.get("type") == STL_MED
        if r["status"] == 2:
            d = local_day(r["completed_at"]) if not med else (date.fromisoformat(r["due"]) if r["due"] else None)
            if not d or d < mon0 or d > today:
                continue
            if med:  # a done copy of the day's intake
                p["med_done"] += 1
                p["med_due"] += 1
            else:
                p["done"] += 1
                p["per_week"][(d - mon0).days // 7] += 1
            continue
        if not r["due"]:
            continue
        if med:  # the open intake: every day since its date that has passed (today once its time is reached) was due
            d0 = max(date.fromisoformat(r["due"]), mon0)
            p["med_due"] += max(0, (today - d0).days) + (1 if d0 <= today and (r["due_time"] or "00:00") <= hm else 0)
        elif r["due"] < today.isoformat():
            p["overdue"] += 1
        else:
            x = {"task_id": r["id"], "title": r["title"], "type": f.get("type") or "appointment", "due": r["due"], "time": r["due_time"]}
            nxt.append((x, p))
            if p["next"] is None or (x["due"], x["time"] or "") < (p["next"]["due"], p["next"]["time"] or ""):
                p["next"] = x
    out = []
    for k, p in people.items():
        if not (p["done"] or p["next"] or p["overdue"] or p["med_due"]):
            continue
        p["name"] = stl_label([n for n in p["names"] if stl_key(n) == k]) if k else ""
        del p["names"]
        out.append(p)
    out.sort(key=lambda p: (p["name"] != "", p["name"].casefold()))
    nxt.sort(key=lambda xp: (xp[0]["due"], xp[0]["time"] or "", xp[0]["task_id"]))
    per_week = [sum(p["per_week"][i] for p in out) for i in range(weeks)]
    return {"per_week": per_week, "done": sum(per_week), "overdue": sum(p["overdue"] for p in out),
            "med_done": sum(p["med_done"] for p in out), "med_due": sum(p["med_due"] for p in out), "people": out,
            "next": [{**x, "who": p["name"]} for x, p in nxt[:STL_NEXT_MAX]]}


def _span(a, z, lo, hi):
    """Days of the trip a..z (ISO, both included) within lo..hi."""
    a, z = max(date.fromisoformat(a), lo), min(date.fromisoformat(z), hi)
    return (z - a).days + 1 if z >= a else 0


def stl_trip_costs(c, uid, trips):
    """{list id: (amount, currency)} -- the travel expenses made from the trips (kalmido/life/tripcost.py) that uid may
    open there (the admins of the office area; never an agent / API token: ltc_office refuses, then simply none)."""
    if not trips:
        return {}
    from ..life.tripcost import ltc_office
    from ..office.travel import rk_home_cur, rk_trips
    ids = ",".join(str(int(t["id"])) for t in trips)
    org = {t["id"]: t["org_id"] for t in trips}
    out, offices = {}, {}
    for k in c.execute(f"SELECT list_id, org_id, trip_id FROM life_trip_costs WHERE list_id IN ({ids})").fetchall():  # noqa: S608 (ints)
        lo = org[k["list_id"]]
        if lo not in offices:
            from ..office.model import pb_personal
            if lo is None and pb_personal(c, uid, create=False) is None:
                offices[lo] = None  # no personal office yet: a GET makes none (Fable review 2.630)
                continue
            try:
                offices[lo] = ltc_office(c, uid, lo)
            except Denied:
                offices[lo] = None
        oid = offices[lo]
        if oid is None or oid != k["org_id"]:
            continue
        try:
            rt = rk_trips(c, oid, trip_id=k["trip_id"])
        except Denied:
            continue
        if rt:
            out[k["list_id"]] = (Decimal(rt[0]["total"] or "0"), rk_home_cur(c, oid))
    return out


def stl_travel(c, uid, today, sq):
    """My trips (the trip projects I own, archived ones too): trips and travel days of the last 12 months and of this year,
    their travel expenses, the next trip."""
    where = (" AND id IN " + sq if sq else "") + f" AND id IN {vis_sql()}"  # 2.630.0: the request's list scope (token allowlist)
    if org_trips_hidden():
        where += " AND org_id IS NULL"
    trips = []
    for r in c.execute(f"SELECT id, name, org_id, trip FROM lists WHERE life='travel' AND owner_id=? AND deleted_at IS NULL{where} ORDER BY id", (uid, uid, uid)):
        t = _fam(r["trip"])
        try:
            a, z = date.fromisoformat(t["from"]).isoformat(), date.fromisoformat(t.get("to") or t["from"]).isoformat()
        except (KeyError, TypeError, ValueError):
            continue
        trips.append({"id": r["id"], "name": r["name"], "org_id": r["org_id"], "where": t.get("where") or "", "from": a, "to": z})
    lo12, y0, y1 = today - timedelta(days=364), date(today.year, 1, 1), date(today.year, 12, 31)
    costs = stl_trip_costs(c, uid, [t for t in trips if _span(t["from"], t["to"], min(lo12, y0), y1)])

    def win(lo, hi):
        ts = [t for t in trips if _span(t["from"], t["to"], lo, hi)]
        cur = {}
        for t in ts:
            if t["id"] in costs:
                amt, cc = costs[t["id"]]
                cur[cc] = cur.get(cc, Decimal(0)) + amt
        return {"trips": len(ts), "days": sum(_span(t["from"], t["to"], lo, hi) for t in ts),
                "costs": [{"currency": k, "amount": float(v)} for k, v in sorted(cur.items())]}
    up = sorted((t for t in trips if t["to"] >= today.isoformat()), key=lambda t: (t["from"], t["id"]))
    nx = up[0] if up else None
    return {"last12": win(lo12, today), "year": {**win(y0, y1), "year": today.year},
            "next": {"list_id": nx["id"], "name": nx["name"], "where": nx["where"], "from": nx["from"], "to": nx["to"],
                     "days": (date.fromisoformat(nx["from"]) - today).days} if nx else None}


def stl_blocks(c, uid, today, mon0, weeks, sq, org):
    """The keys of Home & life for GET /api/stats: contracts / health / travel, each only while its module is on."""
    tw = f" AND t.list_id IN {sq}" if sq else ""
    out = {}
    if feat_on(c, uid, "contracts"):
        out["contracts"] = stl_contracts(c, uid, today, tw)
    if feat_on(c, uid, "health") and not org and not health_hidden(c, uid):
        out["health"] = stl_health(c, uid, today, mon0, weeks, tw)
    if feat_on(c, uid, "travel"):
        out["travel"] = stl_travel(c, uid, today, sq)
    return out
