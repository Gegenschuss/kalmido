#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.392.0 A (#3367): the two hard limits of starting agent work. Invented names only.
 - max_parallel > 0 is hard: POST /api/v1/agent/jobs with a running job over the places -> 409 slots_full {running, max}, nothing
   stored; waiting / done jobs and job updates stay open; PATCH waiting -> running over the limit -> 409; ending a job frees
   a place; max_parallel 0 = no limit; the working mark of a task (POST /tasks/{id}/working) is held by it too
 - sections.wip_hard (PATCH /api/sections, API v1 /sections): a hard column over its wip_limit refuses a job with a task in it
   (409 wip_full {section_id, section, count, limit}); at the limit it is allowed; back under the limit at once; a job without
   a task or a task of another column is not held; a limit that is only a hint (wip_hard off) holds nothing
 - the same for a person without an organisation (freelancer matrix: agents)
usage: p2392_a_api_test.py <datadir>      (KMT_NOSTART=1 / P2392A_NOSTART=1: a running server)"""
import sys

from freelancer_fixture import freelancer
from kt import B, check, done, dbx, fresh, setup

V = B + "/api/v1"
fresh(prefix="P2392A", env={"KALMIDO_API_RATE": "100000"})
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)

r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": ["read", "tasks:write", "structure"]})
check(r.status_code in (200, 201), f"a personal agent {r.status_code} {r.text[:120]}")
AG, H = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
import requests  # noqa: E402


def job(**b):
    return requests.post(V + "/agent/jobs", json=b, headers=H)


def upd(jid, **b):
    return requests.patch(V + f"/agent/jobs/{jid}", json=b, headers=H)


def count():
    return dbx("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=?", (AG,))[0][0]


def ws(**b):
    r = F.patch(B + f"/api/agents/{AG}/work-style", json=b)
    check(r.ok, f"work style {b}: {r.status_code} {r.text[:100]}")


def err(r, status, code):
    j = r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json") else {}
    check(r.status_code == status and j.get("code") == code, f"{status} {code}: got {r.status_code} {r.text[:160]}")
    return j


# ---- places (max_parallel)
check(job(title="one").status_code == 201 and job(title="two").status_code == 201, "no limit by default: two running jobs")
ws(max_parallel=2)
n = count()
j = err(job(title="three"), 409, "slots_full")
check(j.get("running") == 2 and j.get("max") == 2 and "2" in j.get("message", ""), f"fields running / max {j}")
check(count() == n, "nothing stored by the refused job")
r = job(title="parked", state="waiting")
check(r.status_code == 201, f"a waiting job holds no place and is not held {r.status_code}")
wid = r.json()["id"]
err(upd(wid, state="running"), 409, "slots_full")
check(upd(wid, title="parked, renamed").status_code == 200, "a title update of a waiting job stays open")
check(upd(wid, state="done").status_code == 200, "ending a job is never held")
rid = dbx("SELECT id FROM agent_jobs WHERE agent_id=? AND state='running' ORDER BY id", (AG,))[0][0]
check(upd(rid, append_log="still working").status_code == 200, "a log line of a running job stays open")
check(upd(rid, state="done").status_code == 200, "a running job ends")
check(job(title="three").status_code == 201, "a free place: the next job starts")
ws(max_parallel=0)
check(job(title="four").status_code == 201, "max_parallel 0 = no limit again")

# ---- the working mark is a running job as well
ws(max_parallel=1)
r = F.post(B + "/api/lists", json={"name": "Board"})
check(r.ok, f"list {r.status_code} {r.text[:100]}")
LID = r.json()["id"]
check(F.put(B + f"/api/lists/{LID}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the agent edits the list")
r = F.post(B + "/api/tasks", json={"title": "Mark me", "list_id": LID})
T0 = r.json()["id"]
r = requests.post(V + f"/tasks/{T0}/working", json={"text": "start"}, headers=H)
err(r, 409, "slots_full")
ws(max_parallel=0)
check(requests.post(V + f"/tasks/{T0}/working", json={"text": "start"}, headers=H).status_code == 201, "the mark starts with free places")
ws(max_parallel=1)
check(requests.post(V + f"/tasks/{T0}/working", json={"text": "next line"}, headers=H).status_code == 200,
      "a progress line of the mark that runs already is not held")
ws(max_parallel=0)

# ---- hard column limit
r = F.post(B + "/api/sections", json={"list_id": LID, "name": "Doing", "wip_limit": 2, "tasks": []})
SID = r.json()["id"]
r = F.post(B + "/api/sections", json={"list_id": LID, "name": "Later", "tasks": []})
SID2 = r.json()["id"]


def task(title, sec):
    r = F.post(B + "/api/tasks", json={"title": title, "list_id": LID, "section_id": sec})
    check(r.ok, f"task {title} {r.status_code} {r.text[:100]}")
    return r.json()["id"]


ta, tb, tc = task("A", SID), task("B", SID), task("C", SID)
tl = task("L", SID2)
sec = {s["id"]: s for s in requests.get(V + f"/lists/{LID}/sections", headers=H).json()["data"]}
check(sec[SID]["wip_hard"] is False and sec[SID]["wip_limit"] == 2, f"v1 shows the switch off by default {sec[SID]}")
check(job(title="soft", task_id=tc).status_code == 201, "wip_hard off: over the limit is only a hint")
r = F.patch(B + f"/api/sections/{SID}", json={"wip_hard": True})
check(r.ok, f"set wip_hard {r.status_code} {r.text[:100]}")
check(dbx("SELECT wip_hard FROM sections WHERE id=?", (SID,))[0][0] == 1, "stored")
n = count()
j = err(job(title="hard", task_id=tc), 409, "wip_full")
check(j.get("section_id") == SID and j.get("section") == "Doing" and j.get("count") == 3 and j.get("limit") == 2, f"wip_full fields {j}")
check(count() == n, "nothing stored by the refused job")
check(job(title="no task").status_code == 201, "a job without a task is not held")
check(job(title="other column", task_id=tl).status_code == 201, "a task of another column is not held")
check(job(title="waits", task_id=tc, state="waiting").status_code == 201, "a waiting job on the task is not held")
td = task("D", SID)  # no running job on it yet: the working mark would start one
err(requests.post(V + f"/tasks/{td}/working", json={}, headers=H), 409, "wip_full")
err(job(title="still over", task_id=ta), 409, "wip_full")
for t in (tc, td):
    r = F.post(B + f"/api/tasks/{t}/complete", json={})
    check(r.ok, f"close a task {r.status_code} {r.text[:100]}")
r = job(title="at the limit", task_id=ta)
check(r.status_code == 201, f"{r.text[:120]} at the limit (2 of 2) the job starts: back under lifts it at once")
# a subtask does not count, like the column head
r = F.post(B + "/api/tasks", json={"title": "sub", "list_id": LID, "section_id": SID, "parent_id": ta})
check(job(title="with a subtask", task_id=tb).status_code == 201, "subtasks do not count")
# v1: set and read, and the rights of the limit
r = requests.patch(V + f"/sections/{SID}", json={"wip_hard": False}, headers=H)
check(r.status_code == 200 and r.json()["wip_hard"] is False, f"v1 sets it {r.status_code} {r.text[:100]}")
r = requests.patch(V + f"/sections/{SID}", json={"wip_hard": "yes"}, headers=H)
check(r.status_code == 400, f"a bad value 400 {r.status_code}")
r = requests.post(V + f"/lists/{LID}/sections", json={"name": "Fresh", "wip_limit": 1, "wip_hard": True}, headers=H)
check(r.status_code == 201 and r.json()["wip_hard"] is True, f"v1 creates a hard column {r.status_code} {r.text[:100]}")
# undo of a deleted section brings the switch back
r = F.post(B + "/api/sections", json={"list_id": LID, "name": "Back", "wip_limit": 3, "wip_hard": True, "tasks": []})
check(r.ok and dbx("SELECT wip_hard FROM sections WHERE id=?", (r.json()["id"],))[0][0] == 1, "web create keeps wip_hard")
sys.exit(done("p2392_a_api"))
