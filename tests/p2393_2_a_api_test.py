#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.393.2 API tests, part A (#3374 flow figures of a project), own container (start.sh). Invented names only.
freelancer-matrix: lists
 - GET /api/lists/{id}/flow and /api/v1/lists/{id}/flow (?days=30|90): lead time (created -> completed, median and 85th
   percentile, linear between ranks) and cycle time (first entry into a column named "In Arbeit" / "In progress" / "Doing" /
   "WIP" -> completed) over a small fixed history (tasks and history entries written straight into the database), the
   cumulative flow per column and day (no column before the first move, a column that is gone, done, won't do leaves), the
   bug trend per ISO week, the cap at 2000 tasks (capped: true), a list with the lock (metadata only)
 - visibility: a participant counts only their own task, someone outside the list 404, ?days=7 400, an agent token reads it
 - a person without an organisation: their own project
usage: p2393_2_a_api_test.py <datadir>"""
import json
import os
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone

import requests

import kt
from kt import B, check, sess, today
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
V = B + "/api/v1"


def sql(q, args=()):
    c = kt._dbx.connect(os.path.join(kt.DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall() if q.lstrip().upper().startswith("SELECT") else c.execute(q, args)
        c.commit()
        return r
    finally:
        c.close()


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


if not kt.nostart("P2393_2_A"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), kt.DATA], check=True, stdout=subprocess.DEVNULL)
kt.docker_logs_on_first_fail()
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "collab,kanban,comments"})
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": kt.PASSWORD, "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}

T0 = today()


def at(days_ago, hour=10):
    """A stored UTC timestamp `days_ago` days before today at hour:00 UTC (the same local day in Berlin)."""
    return datetime.combine(T0 - timedelta(days=days_ago), time(hour), timezone.utc).isoformat()


def day(days_ago):
    return (T0 - timedelta(days=days_ago)).isoformat()


L = A.post(B + "/api/lists", json={"name": "Flow board", "kind": "project"}).json()["id"]
SEC = {}
for nm in ("Backlog", "In Arbeit", "Review"):
    r = A.post(B + "/api/sections", json={"list_id": L, "name": nm})
    assert r.ok, r.text
    SEC[nm] = r.json()["id"]


def task(title, sec=None, created=0, done=None, status=None, ttype="", moves=(), assignee=None):
    """A task with a fixed history: created / completed `n` days ago, moves = [(days ago, column name)] as history entries."""
    r = A.post(B + "/api/tasks", json={"list_id": L, "title": title, **({"section_id": SEC[sec]} if sec else {})})
    assert r.ok, r.text
    tid = r.json()["id"]
    st = status if status is not None else (2 if done is not None else 0)
    sql("UPDATE tasks SET created_at=?, completed_at=?, status=?, ttype=?, assignee_id=? WHERE id=?",
        (at(created), at(done) if done is not None else None, st, ttype, assignee, tid))
    sql("DELETE FROM activity WHERE task_id=? AND kind IN ('section', 'list')", (tid,))
    for d, nm in moves:
        sql("INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)",
            (tid, ids["alice"], "section", json.dumps({"name": nm}), at(d)))
    return tid


# lead times 5, 2, 39, 1 days; cycle times 3 (In Arbeit -> Review -> done), 2 (in "In Arbeit" since creation), 8
T1 = task("Login form", "Review", created=20, done=15, moves=[(18, "In Arbeit"), (16, "Review")])
T2 = task("Export button", "In Arbeit", created=12, done=10)
T3 = task("Old ticket", "In Arbeit", created=40, done=1, moves=[(9, "In Arbeit")])
T4 = task("Crash on start", "Backlog", created=5, ttype="bug", assignee=ids["bob"])
T5 = task("Typo on the start page", None, created=3, done=2, ttype="bug")
T6 = task("Done long ago", None, created=60, done=50)
T7 = task("Dropped idea", None, created=8, done=4, status=-1)
T8 = task("Renamed column", None, created=25, moves=[(24, "Gone column"), (22, "In Arbeit")])  # open, column today: none
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "participant"})

# ---- the figures (owner)
r = A.get(B + f"/api/lists/{L}/flow")
j = r.json() if r.ok else {}
check(r.ok and j.get("days") == 30 and j.get("start") == day(29) and j.get("end") == day(0), f"#3374: default 30 days up to today {r.status_code} {r.text[:300]}")
check(j.get("capped") is False and j.get("tasks") == 7 and j.get("e2e") is False,
      f"#3374: counted the 7 tasks open or closed in the period (not the one done 50 days ago) ({ {k: j.get(k) for k in ('capped', 'tasks', 'e2e')} })")
lt, ct = j.get("lead_time") or {}, j.get("cycle_time") or {}
check(lt == {"median": 3.5, "p85": 23.7, "n": 4}, f"#3374: lead time median 3.5, 85 % 23.7 of 1 / 2 / 5 / 39 days ({lt})")
check(ct.get("median") == 3.0 and ct.get("p85") == 6.5 and ct.get("n") == 3 and ct.get("columns") == [SEC["In Arbeit"]],
      f"#3374: cycle time from the first entry into 'In Arbeit': 2 / 3 / 8 days -> median 3.0, 85 % 6.5 ({ct})")
cols = (j.get("cfd") or {}).get("columns") or []
keys = [(c["kind"], c["id"]) for c in cols]
check(keys == [("none", None), ("column", SEC["Backlog"]), ("column", SEC["In Arbeit"]), ("column", SEC["Review"]), ("gone", None)],
      f"#3374: the flow's columns: no column first, the board's columns in order, a gone column last ({keys})")
check([c["wip"] for c in cols] == [False, False, True, False, False], f"#3374: 'In Arbeit' counts as in progress ({cols})")
dd = {x["day"]: x for x in (j.get("cfd") or {}).get("days") or []}
check(len(dd) == 30, f"#3374: one point per day ({len(dd)})")


def state(n):
    x = dd.get(day(n)) or {}
    return dict(zip(["none", "backlog", "wip", "review", "gone"], x.get("columns") or [])), x.get("done")


s, dn = state(23)  # T3 no column (before its first move), T8 in the gone column, T1 not created yet
check(s == {"none": 1, "backlog": 0, "wip": 0, "review": 0, "gone": 1} and dn == 0, f"#3374: day -23 ({s}, done {dn})")
s, dn = state(17)  # T1 in "In Arbeit", T3 no column, T8 in "In Arbeit" (its newest move: its column now = none, see below)
check(s.get("wip") == 1 and s.get("none") == 2 and dn == 0, f"#3374: day -17: T1 in progress, T3 + T8 without column ({s}, done {dn})")
s, dn = state(11)  # T2 in "In Arbeit" since its creation, T1 done
check(s.get("wip") == 1 and dn == 1, f"#3374: day -11: T2 in progress, T1 done ({s}, done {dn})")
s, dn = state(4)  # T7 won't do: leaves the diagram; T4 in the backlog
check(s.get("backlog") == 1 and dn == 2 and sum(s.values()) == 3, f"#3374: day -4: won't do is gone, T4 in the backlog ({s}, done {dn})")
s, dn = state(0)
check(dn == 4 and s.get("backlog") == 1 and s.get("none") == 1 and sum(s.values()) == 2, f"#3374: today: 4 done, T4 + T8 open ({s}, done {dn})")

bugs = {w["week"]: w for w in j.get("bugs") or []}
wk = lambda n: "%d-W%02d" % (T0 - timedelta(days=n)).isocalendar()[:2]  # noqa: E731
check(sum(w["created"] for w in bugs.values()) == 2 and sum(w["done"] for w in bugs.values()) == 1, f"#3374: 2 new bugs, 1 completed ({bugs})")
check(bugs.get(wk(2), {}).get("done") == 1 and bugs.get(wk(3), {}).get("created", 0) >= 1 and bugs.get(wk(5), {}).get("created", 0) >= 1,
      f"#3374: the bugs in their ISO weeks ({bugs})")
check(wk(29) in bugs and wk(0) in bugs and list(bugs) == sorted(bugs), f"#3374: every week of the period, oldest first ({list(bugs)})")

# ---- 90 days, bad period, the token API
r = A.get(B + f"/api/lists/{L}/flow?days=90")
check(r.ok and r.json()["days"] == 90 and r.json()["start"] == day(89) and r.json()["tasks"] == 8, f"#3374: 90 days count the one done 50 days ago {r.text[:200]}")
check(r.ok and r.json()["lead_time"]["n"] == 5, f"#3374: 90 days: 5 completed tasks measured {r.text[:200]}")
r = A.get(B + f"/api/lists/{L}/flow?days=7")
check(r.status_code == 400, f"#3374: ?days=7 refused {r.status_code}")
r = A.post(B + "/api/admin/agents", json={"username": "flowbot", "display_name": "Flowbot", "scopes": ["read"]})
check(r.status_code == 201, f"setup: agent {r.text[:200]}")
AGID, AG = r.json().get("id"), tok(r.json().get("token") or "")
r = AG.get(V + f"/lists/{L}/flow")
check(r.status_code == 404, f"#3374: an agent without the list: 404 {r.status_code}")
A.put(B + f"/api/lists/{L}/members", json={"user_id": AGID, "role": "edit"})
r = AG.get(V + f"/lists/{L}/flow?days=30")
check(r.ok and r.json().get("lead_time", {}).get("median") == 3.5, f"#3374: the agent with the list reads the same figures {r.status_code} {r.text[:200]}")
r = AG.get(V + f"/lists/{L}/flow?foo=1")
check(r.status_code == 400, f"#3374: v1: unknown parameter 400 {r.status_code}")
spec = A.get(B + "/api/v1/openapi.json").json()
check("/lists/{id}/flow" in spec.get("paths", {}) and "ListFlow" in spec.get("components", {}).get("schemas", {}), "#3374: OpenAPI: the route and its schema")

# ---- visibility: a participant only their task, someone outside 404
r = Bo.get(B + f"/api/lists/{L}/flow")
check(r.ok and r.json()["tasks"] == 1 and r.json()["lead_time"]["n"] == 0, f"#3374: the participant counts only their task {r.status_code} {r.text[:200]}")
check(r.ok and sum(w["created"] for w in r.json()["bugs"]) == 1, f"#3374: the participant's bug trend: only their bug {r.text[:300]}")
r = Ca.get(B + f"/api/lists/{L}/flow")
check(r.status_code == 404, f"#3374: someone outside the list: 404 {r.status_code}")

# ---- a list with the lock: metadata only
L2 = A.post(B + "/api/lists", json={"name": "Locked board", "kind": "project"}).json()["id"]
S2 = A.post(B + "/api/sections", json={"list_id": L2, "name": "In Arbeit"}).json()["id"]
r = A.post(B + "/api/tasks", json={"list_id": L2, "title": "Secret", "section_id": S2})
sql("UPDATE tasks SET created_at=?, completed_at=?, status=2 WHERE id=?", (at(6), at(3), r.json()["id"]))
sql("UPDATE lists SET e2e=? WHERE id=?", ("{}", L2))
r = A.get(B + f"/api/lists/{L2}/flow")
j = r.json() if r.ok else {}
check(r.ok and j.get("e2e") is True and j["lead_time"]["median"] == 3.0 and j["cycle_time"]["n"] == 0 and j["cycle_time"]["columns"] == []
      and all(c["kind"] == "none" for c in j["cfd"]["columns"]), f"#3374: a locked list: lead time, no columns, no cycle time {r.status_code} {r.text[:300]}")
check("In Arbeit" not in r.text, "#3374: a locked list: no column name in the answer")
sql("UPDATE lists SET e2e=NULL WHERE id=?", (L2,))

# ---- the cap: more than 2000 tasks
L3 = A.post(B + "/api/lists", json={"name": "Big board", "kind": "project"}).json()["id"]
sql("INSERT INTO tasks(list_id, title, created_at, updated_at) SELECT ?, 'Item ' || g, ?, ? FROM generate_series(1, 2003) g", (L3, at(2), at(2)))
r = A.get(B + f"/api/lists/{L3}/flow")
check(r.ok and r.json()["capped"] is True and r.json()["tasks"] == 2000, f"#3374: capped at 2000 tasks {r.status_code} {r.text[:200]}")
check(r.ok and r.json()["cfd"]["days"][-1]["columns"] == [2000], f"#3374: the newest 2000 counted {r.text[-200:]}")

# ---- a person without an organisation
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Own board", "kind": "project"}).json()["id"]
r = Fr.post(B + "/api/tasks", json={"list_id": FL, "title": "Own task"})
sql("UPDATE tasks SET created_at=?, completed_at=?, status=2 WHERE id=?", (at(4), at(1), r.json()["id"]))
r = Fr.get(B + f"/api/lists/{FL}/flow")
check(r.ok and r.json()["lead_time"]["median"] == 3.0, f"#3374: freelancer: own project {r.status_code} {r.text[:200]}")
r = Fr.post(B + "/api/me/tokens", json={"name": "flow", "scopes": ["read"]})
if check(r.status_code == 201 and r.json().get("token"), f"setup: freelancer token {r.status_code} {r.text[:200]}"):
    r = tok(r.json()["token"]).get(V + f"/lists/{FL}/flow?days=90")
    check(r.ok and r.json()["days"] == 90 and r.json()["lead_time"]["n"] == 1, f"#3374: freelancer: v1 {r.status_code} {r.text[:200]}")
r = Fr.get(B + f"/api/lists/{L}/flow")
check(r.status_code == 404, f"#3374: freelancer: another's project 404 {r.status_code}")

sys.exit(kt.done("p2393_2_a_api"))
