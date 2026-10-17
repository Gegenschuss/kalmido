#!/usr/bin/env python3
"""2.60.0 API tests (part A): sprints of project lists (#343).
 - off by default (no sprint fields in /api/state); switching on needs edit rights (viewer 403, outsider 404, plain list 409)
   and starts sprint 1 (from the next start weekday, 2 weeks); /api/state then has sprint_cfg + sprints of the list
 - a task goes only into an open sprint of its own list (400 otherwise), sprint_at is set; moving it to another list clears
   it; the assign route skips other lists' tasks and milestones, _prev reports conflicts; a viewer cannot assign (403)
 - the burndown (count / points, ideal line from the start sum to 0 on the last day), progress
 - closing: the review (done / moved / added, counts, points) with open tasks to the backlog or into the next sprint (the
   earliest planned one starts); planned sprints: create, remove (tasks back to the backlog, recreated with them), start
 - the watchdog closes a sprint past its last day (carry off -> backlog) and starts the next one
 - agents: no access without the list, list_sprints / get_sprint / assign through /api/v1 with access, the events
   sprint_started / sprint_closed; an agent limited to another list sees nothing and hears nothing
tenant-matrix: none
usage: p260_a_api_test.py <datadir>"""
import os
import subprocess
import sys
import time
from datetime import date, timedelta

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def task(tid):
    return dict(dbx("SELECT list_id, sprint_id, sprint_at, status FROM tasks WHERE id=?", (tid,))[0])


def sprints(lid):
    return [dict(r) for r in dbx("SELECT id, num, state, start, end_day, review FROM sprints WHERE list_id=? ORDER BY num", (lid,))]


def lstate(s, lid):
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)


def events(hdr, name):
    j = requests.get(V + "/agent/events", params={"since": 0}, headers=hdr).json()
    return [e for e in (j.get("data") or j.get("events") or []) if e["event"] == name]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
P = A.post(B + "/api/lists", json={"name": "Product", "kind": "project", "org_id": ORG}).json()["id"]
P2 = A.post(B + "/api/lists", json={"name": "Other project", "kind": "project", "org_id": ORG}).json()["id"]
PLAIN = A.post(B + "/api/lists", json={"name": "Plain", "org_id": ORG}).json()["id"]
r = A.put(B + f"/api/lists/{P}/members", json={"user_id": uid["bob"], "role": "edit"})
check(r.ok, "setup: bob edits the project " + r.text[:160])
r = A.put(B + f"/api/lists/{P}/members", json={"user_id": uid["dave"], "role": "view"})
check(r.ok, "setup: dave views the project " + r.text[:160])
T = [A.post(B + "/api/tasks", json={"title": f"Task {i}", "list_id": P}).json()["id"] for i in range(1, 5)]
TX = A.post(B + "/api/tasks", json={"title": "Elsewhere", "list_id": P2}).json()["id"]
MS = A.post(B + "/api/tasks", json={"title": "Release", "list_id": P, "ms": 1}).json()["id"]

# ================================================================== off by default, switching on
j = A.get(B + f"/api/lists/{P}/sprints").json()
check(j["settings"]["on"] is False and j["sprints"] == [] and j["active_id"] is None, f"off by default: {j}")
lp = lstate(A, P)
check(lp and "sprints" not in lp and "sprint_cfg" not in lp, "the state has nothing new for a list without sprints")
check(Da.put(B + f"/api/lists/{P}/sprint-settings", json={"on": True}).status_code == 403, "a viewer cannot switch sprints on (403)")
check(Ca.put(B + f"/api/lists/{P}/sprint-settings", json={"on": True}).status_code == 404, "an outsider: 404")
check(Ca.get(B + f"/api/lists/{P}/sprints").status_code == 404, "an outsider cannot read the sprints (404)")
check(A.put(B + f"/api/lists/{PLAIN}/sprint-settings", json={"on": True}).status_code == 409, "a plain list: 409 (projects only)")
check(A.put(B + f"/api/lists/{P}/sprint-settings", json={"on": True, "weeks": 3}).status_code == 400, "weeks 3: 400")
check(A.put(B + f"/api/lists/{P}/sprint-settings", json={"on": "yes"}).status_code == 400, "on must be a boolean: 400")
r = A.put(B + f"/api/lists/{P}/sprint-settings", json={"on": True})
check(r.ok and r.json()["started_id"], "switching on starts sprint 1 " + r.text[:200])
S1 = r.json()["started_id"]
sp = sprints(P)
td = date.today()
first = td + timedelta(days=(0 - td.weekday()) % 7)
check(len(sp) == 1 and sp[0]["num"] == 1 and sp[0]["state"] == "active", f"one active sprint: {sp}")
check(sp[0]["start"] == first.isoformat() and sp[0]["end_day"] == (first + timedelta(days=13)).isoformat(),
      f"default: from the next Monday (or today), 2 weeks: {sp[0]['start']} - {sp[0]['end_day']} (today {td})")
check(r.json()["settings"] == {"on": True, "weeks": 2, "dow": 0, "carry": True}, f"defaults stored: {r.json()['settings']}")
lp = lstate(Bo, P)
check(lp and lp.get("sprint_cfg", {}).get("on") is True and any(s["id"] == S1 and s["state"] == "active" and s["title"] == "Sprint 1" for s in lp.get("sprints", [])),
      f"the state carries the settings and the active sprint: {lp and lp.get('sprints')}")
A.put(B + f"/api/lists/{P}/sprint-settings", json={"on": False})
A.put(B + f"/api/lists/{P}/sprint-settings", json={"on": True})
check(len(sprints(P)) == 1, "off and on again keeps the running sprint (no second one)")

# ================================================================== tasks into sprints
r = A.patch(B + f"/api/tasks/{T[0]}", json={"sprint_id": S1})
check(r.ok and task(T[0])["sprint_id"] == S1 and task(T[0])["sprint_at"], "a task goes into a sprint of its list, sprint_at set " + r.text[:120])
check(A.patch(B + f"/api/tasks/{TX}", json={"sprint_id": S1}).status_code == 400, "a task of another list: 400")
check(task(TX)["sprint_id"] is None, "... and nothing stored")
check(Da.patch(B + f"/api/tasks/{T[1]}", json={"sprint_id": S1}).status_code in (403, 404), "a viewer cannot plan (403)")
r = A.patch(B + f"/api/tasks/{T[0]}", json={"list_id": P2})
check(r.ok and task(T[0])["sprint_id"] is None and task(T[0])["sprint_at"] is None, "moved to another list: the sprint link goes")
A.patch(B + f"/api/tasks/{T[0]}", json={"list_id": P})
c = A.post(B + "/api/tasks", json={"title": "Born in a sprint", "list_id": P, "sprint_id": S1})
check(c.ok and task(c.json()["id"])["sprint_id"] == S1, "created right into a sprint")
TN = c.json()["id"]
check(A.post(B + "/api/tasks", json={"title": "Wrong sprint", "list_id": P2, "sprint_id": S1}).status_code == 400, "created into another list's sprint: 400")

r = Bo.post(B + f"/api/lists/{P}/sprints/assign", json={"ids": [T[1], T[2], TX, MS], "sprint_id": S1})
j = r.json()
check(r.ok and sorted(j["moved"]) == sorted([T[1], T[2]]) and sorted(j["skipped"]) == sorted([TX, MS]), f"bulk assign: other lists' tasks and milestones skipped: {j}")
check(j["prev"] == {str(T[1]): None, str(T[2]): None}, f"prev for the undo: {j.get('prev')}")
check(Da.post(B + f"/api/lists/{P}/sprints/assign", json={"ids": [T[3]], "sprint_id": S1}).status_code == 403, "a viewer cannot bulk assign (403)")
check(Ca.post(B + f"/api/lists/{P}/sprints/assign", json={"ids": [T[3]], "sprint_id": S1}).status_code == 404, "an outsider: 404")
check(A.post(B + f"/api/lists/{P2}/sprints/assign", json={"ids": [TX], "sprint_id": S1}).status_code == 400, "a sprint of another list: 400")
r = A.post(B + f"/api/lists/{P}/sprints/assign", json={"ids": [T[1]], "sprint_id": None, "_prev": {str(T[1]): 999}})
check(r.ok and r.json()["conflicts"] and task(T[1])["sprint_id"] == S1, "undo with a stale _prev: conflict, nothing changed")
A.post(B + f"/api/lists/{P}/sprints/assign", json={"ids": [TN], "sprint_id": None})
A.post(B + f"/api/lists/{P}/sprints/assign", json={"ids": [T[0]], "sprint_id": None})

# ================================================================== burndown, progress (sprint started three days ago)
st = td - timedelta(days=3)
dbx("UPDATE sprints SET start=?, end_day=? WHERE id=?", (st.isoformat(), (st + timedelta(days=13)).isoformat(), S1), write=True)
dbx("UPDATE tasks SET points=3 WHERE id=?", (T[1],), write=True)
dbx("UPDATE tasks SET points=5 WHERE id=?", (T[2],), write=True)
check(A.post(B + f"/api/tasks/{T[1]}/complete").ok, "setup: one sprint task done")
j = A.get(B + f"/api/sprints/{S1}").json()
check(j["progress"]["done"] == 1 and j["progress"]["total"] == 2 and j["progress"]["points_done"] == 3 and j["progress"]["points_total"] == 8,
      f"progress (count + points): {j['progress']}")
bd = j["burndown"]
check(len(bd["days"]) == 4 and bd["days"][0]["open"] == 2 and bd["days"][-1]["open"] == 1, f"burndown count: open per day up to today: {bd['days']}")
check(bd["ideal"] == [{"day": st.isoformat(), "open": 2}, {"day": (st + timedelta(days=13)).isoformat(), "open": 0}], f"ideal line: {bd['ideal']}")
bp = A.get(B + f"/api/sprints/{S1}", params={"unit": "points"}).json()["burndown"]
check(bp["unit"] == "points" and bp["days"][0]["open"] == 8 and bp["days"][-1]["open"] == 5 and bp["ideal"][0]["open"] == 8, f"burndown points: {bp}")
check(A.get(B + f"/api/sprints/{S1}", params={"unit": "hours"}).status_code == 400, "unit hours: 400")
check(Ca.get(B + f"/api/sprints/{S1}").status_code == 404, "an outsider cannot read a sprint (404)")
check(Da.get(B + f"/api/sprints/{S1}").ok, "a viewer reads it")
check(MS not in [t["id"] for t in j["tasks"]], "milestones never count")

# ================================================================== edits, planned sprints
check(A.patch(B + f"/api/sprints/{S1}", json={"goal": "Ship the login", "name": ""}).json()["goal"] == "Ship the login", "the goal is stored")
check(A.patch(B + f"/api/sprints/{S1}", json={"end": (st - timedelta(days=1)).isoformat()}).status_code == 400, "an end before the start: 400")
check(A.patch(B + f"/api/sprints/{S1}", json={"start": "2026-01-01", "end": "2026-12-31"}).status_code == 400, "longer than 92 days: 400")
check(Da.patch(B + f"/api/sprints/{S1}", json={"goal": "x"}).status_code == 403, "a viewer cannot edit a sprint (403)")
r = A.post(B + f"/api/lists/{P}/sprints", json={"goal": "Later"})
check(r.ok and r.json()["state"] == "planned" and r.json()["start"] == (st + timedelta(days=14)).isoformat(), f"a planned sprint right after: {r.text[:200]}")
SP = r.json()["id"]
A.post(B + f"/api/lists/{P}/sprints/assign", json={"ids": [T[3]], "sprint_id": SP})
r = A.delete(B + f"/api/sprints/{SP}")
check(r.ok and r.json()["tasks"] == [T[3]] and task(T[3])["sprint_id"] is None, "removing a planned sprint: its tasks back to the backlog")
r = A.post(B + f"/api/lists/{P}/sprints", json={"goal": "Later", "start": r.json()["sprint"]["start"], "end": r.json()["sprint"]["end"], "tasks": [T[3]]})
check(r.ok and r.json()["moved"] == [T[3]] and task(T[3])["sprint_id"] == r.json()["id"], "the undo recreates it with its tasks")
SP = r.json()["id"]
check(A.delete(B + f"/api/sprints/{S1}").status_code == 409, "a running sprint cannot be removed (409)")
check(A.post(B + f"/api/sprints/{SP}/start").status_code == 409, "a second running sprint: 409")
check(A.post(B + f"/api/sprints/{SP}/close").status_code == 409, "closing a planned sprint: 409")

# ================================================================== agents
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "claude", "display_name": "Claude"})
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"], **H}
check(requests.get(V + f"/lists/{P}/sprints", headers=AGH).status_code == 404, "an agent without the list sees no sprints (404)")
check(requests.get(V + f"/sprints/{S1}", headers=AGH).status_code == 404, "... and no sprint (404)")
check(A.put(B + f"/api/lists/{P}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the agent joins the project")
j = requests.get(V + f"/lists/{P}/sprints", headers=AGH).json()
check(j.get("active_id") == S1 and {s["id"] for s in j.get("data", [])} == {S1, SP}, f"list_sprints through the API: {str(j)[:200]}")
check(requests.get(V + f"/lists/{P}/sprints", params={"x": 1}, headers=AGH).status_code == 400, "an unknown parameter: 400")
j = requests.get(V + f"/sprints/{S1}", params={"unit": "points"}, headers=AGH).json()
check(j.get("burndown", {}).get("unit") == "points" and len(j.get("tasks", [])) == 2, "get_sprint with the burndown")
r = requests.post(V + f"/lists/{P}/sprints/assign", json={"ids": [T[0]], "sprint_id": S1}, headers=AGH)
check(r.ok and task(T[0])["sprint_id"] == S1, "the agent puts a task into the sprint " + r.text[:120])
check(requests.post(V + f"/lists/{P}/sprints/assign", json={"ids": [T[0]], "sprint_id": S1, "x": 1}, headers=AGH).status_code == 400, "unknown field: 400")

# ================================================================== closing: review, backlog / next sprint
check(Da.post(B + f"/api/sprints/{S1}/close", json={"target": "backlog"}).status_code == 403, "a viewer cannot close (403)")
check(A.post(B + f"/api/sprints/{S1}/close", json={"target": "later"}).status_code == 400, "target later: 400")
r = A.post(B + f"/api/sprints/{S1}/close", json={"target": "backlog"})
check(r.ok, "closed " + r.text[:200])
rv = r.json()["sprint"]["review"] or {}
check(rv.get("done") == [T[1]] and sorted(rv.get("moved", [])) == sorted([T[0], T[2]]), f"review done / moved: {rv}")
check(sorted(rv.get("added", [])) == sorted([T[0], T[1], T[2]]), f"added after the start (planned in after its first day): {rv.get('added')}")
check(rv.get("count_done") == 1 and rv.get("count_total") == 3 and rv.get("points_done") == 3 and rv.get("points_total") == 8, f"review counts / points: {rv}")
check(rv.get("target") == "backlog" and task(T[2])["sprint_id"] is None and task(T[0])["sprint_id"] is None, "open tasks back to the backlog")
check(task(T[1])["sprint_id"] == S1, "the done task stays in the closed sprint")
nx = r.json()["next"]
check(nx and nx["id"] == SP and nx["state"] == "active", f"the planned sprint starts next: {nx and nx['id']} {nx and nx['state']}")
check(A.patch(B + f"/api/tasks/{T[2]}", json={"sprint_id": S1}).status_code == 400, "a closed sprint takes no tasks (400)")
check(A.patch(B + f"/api/sprints/{S1}", json={"start": td.isoformat()}).status_code == 409, "a closed sprint keeps its dates (409)")
cl = requests.get(V + f"/sprints/{S1}", headers=AGH).json()
check(cl.get("state") == "closed" and cl.get("progress", {}).get("total") == 3 and cl.get("progress", {}).get("done") == 1, f"a closed sprint stays readable: {cl.get('progress')}")
time.sleep(1)
ev = events(AGH, "sprint_closed")
check(any(e["data"]["sprint"]["id"] == S1 and e["data"]["sprint"]["review"]["done"] == [T[1]] and e["data"].get("next_sprint_id") == SP for e in ev),
      f"the agent hears sprint_closed with the review: {str(ev)[:200]}")
check(any(e["data"]["sprint"]["id"] == SP for e in events(AGH, "sprint_started")), "... and sprint_started of the next one")

A.post(B + f"/api/lists/{P}/sprints/assign", json={"ids": [T[2]], "sprint_id": SP})
r = A.post(B + f"/api/sprints/{SP}/close", json={"target": "next"})
nx = r.json()["next"]
check(r.ok and nx and nx["state"] == "active" and task(T[2])["sprint_id"] == nx["id"] and task(T[3])["sprint_id"] == nx["id"],
      f"target next: open tasks go into the new sprint: {r.text[:160]}")
S3 = nx["id"]
check(nx["start"] == (st + timedelta(days=28)).isoformat(), f"the rhythm stays (right after the closed one): {nx['start']}")

# ================================================================== the watchdog: past its last day, carry off
A.put(B + f"/api/lists/{P}/sprint-settings", json={"carry": False})
dbx("UPDATE sprints SET start=?, end_day=? WHERE id=?", ((td - timedelta(days=14)).isoformat(), (td - timedelta(days=1)).isoformat(), S3), write=True)
for _ in range(20):
    time.sleep(0.5)
    if dbx("SELECT state FROM sprints WHERE id=?", (S3,))[0][0] == "closed":
        break
sp = sprints(P)
check(any(s["id"] == S3 and s["state"] == "closed" for s in sp), f"the watchdog closed the sprint past its last day: {sp}")
act = [s for s in sp if s["state"] == "active"]
check(len(act) == 1 and act[0]["start"] == td.isoformat(), f"... and started the next one from today: {act}")
check(task(T[2])["sprint_id"] is None and task(T[3])["sprint_id"] is None, "carry off: open tasks back to the backlog")
check(len([s for s in sprints(P) if s["state"] == "active"]) == 1, "never two running sprints")

# ================================================================== an agent limited to another list
check(A.put(B + f"/api/lists/{P2}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the agent in the other project too")
r = A.patch(B + f"/api/admin/agents/{AG}", json={"list_ids": [P2]})
check(r.ok, "setup: the agent limited to the other project " + r.text[:120])
n0 = len(events(AGH, "sprint_started"))
check(requests.get(V + f"/lists/{P}/sprints", headers=AGH).status_code == 404, "a limited agent sees no sprints of the list (404)")
check(requests.post(V + f"/lists/{P}/sprints/assign", json={"ids": [T[2]], "sprint_id": act[0]["id"]}, headers=AGH).status_code == 404,
      "... and cannot assign (404)")
A.post(B + f"/api/sprints/{act[0]['id']}/close", json={"target": "backlog"})
time.sleep(1)
check(len(events(AGH, "sprint_started")) == n0, "... and hears nothing of it")

print(f"p260_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
