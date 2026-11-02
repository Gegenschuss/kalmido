#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.392.2 (#3366): a job for several tasks, part jobs and continuations, the server's watchdog, own container (start.sh).
Invented people and texts only.
freelancer-matrix: agents
 - POST /api/v1/agent/jobs task_ids (the first is task_id; each visible, else 404; more than 50 or not a list: 400); every task
   in progress by the job, ending it clears all of them; parent_id / continue_of only the agent's own jobs (400 otherwise);
   the job answers task_ids, parent_id, continue_of, continued_by, parts; PATCH does not take them (400)
 - the person's job list (GET /api/agents/jobs) carries the same chain
 - the watchdog: a running job without progress for stall_min (default 60) minutes -> job_stalled once per case to the agent,
   a News entry (job_watch) and "Waiting for me" (kind watch) for its owner; progress ends the case, a new stall is a new one;
   stall_min 0 = never (the other agent of the same tick is told); a branch of an open task without a merge, no open job,
   the last one ended 3 days ago -> branch_stranded once (the branch untrusted), a merge ends the case
 - work style: stall_min 0 or 15..1440, else 400
 - a person without an organisation: her own list and her personal agents
usage: p23922_b_api_test.py <datadir>"""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
import kt  # noqa: E402
from kt import check, B, dbx, H, done, until  # noqa: E402

V = B + "/api/v1"


def hdr(tok):
    return {"Authorization": "Bearer " + tok, **H}


def agent(s, name, lid, role="edit"):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "tasks:write", "comments", "delete"]})
    assert r.status_code in (200, 201), r.text
    aid = r.json()["id"]
    assert s.put(B + f"/api/lists/{lid}/members", json={"user_id": aid, "role": role}).ok
    return aid, hdr(s.post(B + f"/api/my/agents/{aid}/token").json()["token"])


def task(s, lid, title):
    return s.post(B + "/api/tasks", json={"title": title, "list_id": lid}).json()["id"]


def events(h, event):
    rows = requests.get(V + "/agent/events", headers=h, params={"since": 0, "limit": 500}).json()
    rows = rows.get("data", rows.get("events", [])) if isinstance(rows, dict) else rows
    return [e for e in rows if e.get("event") == event]


def dv(h, tid):
    return requests.get(V + f"/tasks/{tid}", headers=h).json().get("delivery")


def ago(**k):
    return (datetime.now(timezone.utc) - timedelta(**k)).isoformat(timespec="seconds")


def job(h, **b):
    return requests.post(V + "/agent/jobs", headers=h, json={"title": "Work", **b})


kt.fresh()
A = kt.setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 5})
FU, F = freelancer(B, A, "frida")  # a person without an organisation: her own list and agents
XU, X = freelancer(B, A, "xena")  # a stranger
L = F.post(B + "/api/lists", json={"name": "Release", "kind": "project", "ptype": "software"}).json()["id"]
AID, AH = agent(F, "fridabot", L)
BID, BH = agent(F, "fridahelper", L)
T = [task(F, L, f"Task {i}") for i in range(4)]
XT = task(X, X.post(B + "/api/lists", json={"name": "Hers"}).json()["id"], "Not yours")

# ================================================================== several tasks
r = job(AH, task_ids=[T[0], T[1], T[2]])
j = r.json()
J1 = j.get("id")
check(r.status_code == 201 and j.get("task_id") == T[0] and j.get("task_ids") == [T[0], T[1], T[2]], "a job of three tasks " + r.text[:300])
check(all((dv(AH, t) or {}).get("job_id") == J1 for t in T[:3]), "each task is in progress by the job")
check(job(AH, task_ids=[T[3], XT]).status_code == 404, "a task it does not see: 404")
check(job(AH, task_ids=list(range(1, 52))).status_code == 400, "more than 50: 400")
check(job(AH, task_ids="1,2").status_code == 400, "not a list: 400")
r = job(AH, task_id=T[3], task_ids=[T[3], T[1]])
check(r.status_code == 201 and r.json()["task_ids"] == [T[3], T[1]], "task_id and task_ids together, no twice " + r.text[:200])
J0 = r.json()["id"]
requests.patch(V + f"/agent/jobs/{J0}", headers=AH, json={"state": "done"})
check(requests.patch(V + f"/agent/jobs/{J1}", headers=AH, json={"task_ids": [T[3]]}).status_code == 400, "PATCH does not take task_ids")
requests.patch(V + f"/agent/jobs/{J1}", headers=AH, json={"state": "done"})
check(all(dv(AH, t) is None for t in T[:3]), "ending the job clears all of them")

# ================================================================== parent, continuation
JP = job(AH, title="Lead").json()["id"]
r = job(AH, title="Part A", parent_id=JP)
JA = r.json().get("id")
check(r.status_code == 201 and r.json().get("parent_id") == JP, "a part job " + r.text[:200])
r = job(AH, title="Lead, continued", continue_of=JP)
JC = r.json().get("id")
check(r.status_code == 201 and r.json().get("continue_of") == JP, "a continuation " + r.text[:200])
jp = requests.get(V + "/agent/jobs", headers=AH).json()["data"]
lead = next(x for x in jp if x["id"] == JP)
check(lead.get("continued_by") == JC and lead.get("parts") == [JA], f"the lead knows its chain {lead.get('continued_by')} {lead.get('parts')}")
OJ = job(BH, title="Other agent").json()["id"]
check(job(AH, parent_id=OJ).status_code == 400, "parent_id of another agent's job: 400")
check(job(AH, continue_of=OJ).status_code == 400, "continue_of of another agent's job: 400")
check(job(AH, continue_of=999999).status_code == 400, "an unknown job: 400")
mine = F.get(B + "/api/agents/jobs?state=open").json().get("jobs") or []
ml = next((x for x in mine if x["id"] == JP), {})
check(ml.get("continued_by") == JC and ml.get("parts") == [JA], f"the person's job list carries the chain {str(ml)[:200]}")
for x in (JP, JA, JC, OJ):
    requests.patch(V + f"/agent/jobs/{x}", headers=AH if x != OJ else BH, json={"state": "done"})

# ================================================================== work style
check(F.patch(B + f"/api/agents/{AID}/work-style", json={"stall_min": 5}).status_code == 400, "stall_min 5: 400")
check(F.patch(B + f"/api/agents/{AID}/work-style", json={"stall_min": 2000}).status_code == 400, "stall_min 2000: 400")
r = F.get(B + f"/api/agents/{AID}/work-style")
check(r.ok and (r.json().get("work_style") or r.json()).get("stall_min") == 60, "default 60 minutes " + r.text[:200])

# ================================================================== the watchdog: stalled
JS = job(AH, title="Long build", task_id=T[0]).json()["id"]
dbx("UPDATE agent_jobs SET updated_at=? WHERE id=?", (ago(minutes=90), JS))
check(until(lambda: events(AH, "job_stalled"), 30), "job_stalled reaches the agent")
ev = events(AH, "job_stalled")[0]["data"]
check(ev["job"]["id"] == JS and ev.get("minutes", 0) >= 89 and (ev.get("task") or {}).get("id") == T[0], f"... with the job, minutes, task {str(ev)[:300]}")
check(until(lambda: [x for x in F.get(B + "/api/inbox").json()["items"] if x["kind"] == "watch"]), "Waiting for me: the finding")
w = [x for x in F.get(B + "/api/inbox").json()["items"] if x["kind"] == "watch"][0]
check(w["finding"] == "job_stalled" and w["job_id"] == JS and w["task_id"] == T[0], f"... job and task {w}")
nw = dbx("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='job_watch'", (FU,))[0][0]
check(nw == 1, f"one News entry for the owner ({nw})")
check(len(dbx("SELECT 1 FROM job_watch WHERE kind='job_stalled' AND job_id=?", (JS,))) == 1, "one case")
requests.patch(V + f"/agent/jobs/{JS}", headers=AH, json={"append_log": "still compiling"})
check(until(lambda: dbx("SELECT cleared_at FROM job_watch WHERE job_id=?", (JS,))[0][0]), "progress ends the case")
check(not [x for x in F.get(B + "/api/inbox").json()["items"] if x["kind"] == "watch"], "... and it leaves Waiting for me")
dbx("UPDATE agent_jobs SET updated_at=? WHERE id=?", (ago(minutes=120), JS))
check(until(lambda: len(events(AH, "job_stalled")) == 2, 30), "a new stall is a new case")
# stall_min 0: never; the other agent of the same ticks is told
check(F.patch(B + f"/api/agents/{AID}/work-style", json={"stall_min": 0}).ok, "stall_min 0")
JS2 = job(AH, title="Quiet one").json()["id"]
JB = job(BH, title="Helper's").json()["id"]
dbx("UPDATE agent_jobs SET updated_at=? WHERE id IN (?, ?)", (ago(minutes=90), JS2, JB))
check(until(lambda: events(BH, "job_stalled"), 30), "the other agent is told")
check(not [e for e in events(AH, "job_stalled") if e["data"]["job"]["id"] == JS2], "stall_min 0: not told")
check(not events(AH, "branch_stranded"), "no stranded branch yet")
for x, h in ((JS, AH), (JS2, AH), (JB, BH)):
    requests.patch(V + f"/agent/jobs/{x}", headers=h, json={"state": "done"})

# ================================================================== the watchdog: a stranded branch
CID = dbx("""INSERT INTO git_conns(list_id, provider, owner, repo, created_at, next_at) VALUES(?, 'github', 'acme', 'app', ?, 9e12) RETURNING id""",
          (L, ago(days=10)))[0][0]
JT = job(AH, title="Feature", task_id=T[1]).json()["id"]
requests.patch(V + f"/agent/jobs/{JT}", headers=AH, json={"state": "done"})
dbx("INSERT INTO git_branches(conn_id, name, task_id, ahead, sha) VALUES(?, ?, ?, 3, 'abc123')", (CID, f"kalmido-{T[1]}", T[1]))
T1J = (J1, J0, JT)  # every job of task 1 (J1, J0 hold it in task_ids)
dbx("UPDATE agent_jobs SET updated_at=? WHERE id IN (?, ?, ?)", (ago(days=1), *T1J))
JW = job(BH, title="tick probe").json()["id"]
dbx("UPDATE agent_jobs SET updated_at=? WHERE id=?", (ago(minutes=90), JW))
check(until(lambda: [e for e in events(BH, "job_stalled") if e["data"]["job"]["id"] == JW], 30), "a tick ran")
check(not events(AH, "branch_stranded"), "one day: not yet")
requests.patch(V + f"/agent/jobs/{JW}", headers=BH, json={"state": "done"})
dbx("UPDATE agent_jobs SET updated_at=? WHERE id IN (?, ?, ?)", (ago(days=4), *T1J))
check(until(lambda: events(AH, "branch_stranded"), 30), "branch_stranded after 3 days")
e = events(AH, "branch_stranded")[0]["data"]
check(e["branch"]["name"] == f"kalmido-{T[1]}" and e["branch"].get("untrusted") is True and e["job"]["id"] == JT and e.get("days", 0) >= 3,
      f"... the branch untrusted, the last job {str(e)[:300]}")
check(until(lambda: [x for x in F.get(B + "/api/inbox").json()["items"] if x["kind"] == "watch" and x["finding"] == "branch_stranded"]), "Waiting for me: the branch")
dbx("UPDATE git_branches SET ahead=0 WHERE conn_id=?", (CID,))
check(until(lambda: dbx("SELECT cleared_at FROM job_watch WHERE kind='branch_stranded'")[0][0]), "the merge ends the case")
check(len(events(AH, "branch_stranded")) == 1, "told once")
check(not [x for x in X.get(B + "/api/inbox").json()["items"] if x["kind"] == "watch"], "a stranger sees nothing")

sys.exit(done("p23922_b_api"))
