#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.407.0 A (#3513) API tests, own container (kt.fresh): "agent is working" at a task.
 - POST /api/v1/tasks/<id>/working starts it (201) and adds progress lines (200, same job); the task carries working
   {agent_id, agent, name, text, at, ttl} in /api/state for the people who see it; a host's own "11:04 " in front is
   dropped, secrets are replaced; PATCH only while working (404 otherwise), without text it only refreshes
 - the delta (GET /api/state/delta) carries the task with the mark: other windows take it without the whole state
 - DELETE ends it (the mark is gone, the job done / failed); without an update for 15 minutes the mark fades (read time)
 - rights: only agents (a person's token 403), only with write access to the task's list (read only: 403, not shared: 404),
   a person of another organisation never sees the mark; job_id picks one of several running jobs on one task
 - a plain running job with task_id (POST /agent/jobs) shows the same way; a proposal / approval job never
 - freelancer-matrix: agents (the own agent of a person without an organisation marks her task, she sees it)
usage: p2407_a_api_test.py <datadir>"""
import sys
from datetime import datetime, timedelta, timezone

import requests

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

V = B + "/api/v1"
kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
BOB = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123",
                                     "email": "bob@example.com"}).json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en"})
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123",
                                       "email": "carol@example.com"}).json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
check(r.ok, "setup: organisation Beta for carol " + r.text[:120])
kt.dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG, CAROL))
Ca = sess("carol")
Ca.patch(B + "/api/settings", json={"lang": "en"})
FID, Fr = freelancer(B, A, "frida")


def agent(name, scopes=("read", "tasks:write", "comments"), org=ORG, **extra):
    r = A.post(B + "/api/admin/agents", json={"scopes": list(scopes), "username": name, "display_name": name.title(), **extra})
    assert r.ok, r.text
    aid = r.json()["id"]
    if org:
        A.patch(B + f"/api/admin/agents/{aid}", json={"org_id": org})
        kt.dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (org, aid))
    h = requests.Session()
    h.headers.update({"Authorization": "Bearer " + r.json()["token"]})
    return aid, h


CL, cl = agent("claude")
OT, ot = agent("otto")      # only reads the list
NO, no = agent("nora")      # not in the list at all
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": CL, "role": "edit"}).ok, "setup: claude edits the list")
WR = A.post(B + "/api/lists", json={"name": "Read only", "org_id": ORG}).json()["id"]  # one agent per list: otto only views this one
check(A.put(B + f"/api/lists/{WR}/members", json={"user_id": OT, "role": "view"}).ok, "setup: otto only views the list")
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: bob in the list")
T = A.post(B + "/api/tasks", json={"title": "Board columns", "list_id": W}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Second task", "list_id": W}).json()["id"]
TR = A.post(B + "/api/tasks", json={"title": "Read only task", "list_id": WR}).json()["id"]


def state_task(s, tid):
    return next((t for t in s.get(B + "/api/state").json().get("tasks", []) if t["id"] == tid), None)


def wk(s, tid):
    t = state_task(s, tid)
    return t and t.get("working")


def NOW():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path(tid=T):
    return V + f"/tasks/{tid}/working"


# ================================================================== start, lines, what people see
v0 = A.get(B + "/api/state").json().get("v")
r = cl.post(path(), json={"text": "Column added"})
j = r.json() if r.ok else {}
check(r.status_code == 201 and (j.get("working") or {}).get("text") == "Column added",
      f"#3513: POST starts working on the task (201, the line) {r.status_code} {r.text[:200]}")
JOB = (j.get("job") or {}).get("id")
check(JOB and j["job"]["state"] == "running" and j["job"]["task_id"] == T, f"#3513: it is the agent's running job of the task {j.get('job')}")
w = wk(A, T)
check(w and w.get("agent") == "Claude" and w.get("text") == "Column added" and w.get("agent_id") == CL and w.get("ttl") == 900 and w.get("at"),
      f"#3513: the task carries working {{agent, text, at, ttl}} in the state {w}")
check((wk(Bo, T) or {}).get("text") == "Column added", "#3513: every person who sees the task sees the mark (bob)")
check(not wk(A, T2), "#3513: only that task, not its neighbour")
d = A.get(B + f"/api/state/delta?since={v0}").json()
dt = next((t for t in d.get("tasks") or [] if t["id"] == T), None)
check(d.get("full") is False and dt and (dt.get("working") or {}).get("text") == "Column added",
      f"#3513: the delta carries the task with the mark (other windows: no whole state) full={d.get('full')} {dt and dt.get('working')}")
r = cl.post(path(), json={"text": "11:04 Cards moved"})
check(r.status_code == 200 and r.json()["job"]["id"] == JOB, f"#3513: a further POST adds a line to the same job (200) {r.status_code} {r.text[:200]}")
check((wk(A, T) or {}).get("text") == "Cards moved", f"#3513: the newest line shows, a host's own time in front dropped {wk(A, T)}")
check("Column added" in (r.json()["job"]["log"] or ""), "#3513: the earlier lines stay in the job's log")
SECRET = "ghp_fake_token_for_tests_3513"
cl.post(path(), json={"text": f"Pushed with {SECRET}"})
check(SECRET not in str(wk(A, T)), f"#3513: a recognisable secret never reaches the task {wk(A, T)}")
cl.post(path(), json={"text": "x" * 450})
t = (wk(A, T) or {}).get("text") or ""
check(len(t) <= 200 and t.endswith("…"), f"#3513: a long line is cut for the rows ({len(t)})")
at0 = (wk(A, T) or {}).get("at")
kt.dbx("UPDATE agent_jobs SET updated_at=? WHERE id=?", ("2026-01-01T00:00:00+00:00", JOB))
r = cl.patch(path(), json={})
check(r.ok and (wk(A, T) or {}).get("at", "") > "2026-01-01", f"#3513: PATCH without text only refreshes the time {r.status_code} {r.text[:160]}")
check((wk(A, T) or {}).get("text") == t, "#3513: ... and keeps the line")
check(at0 and (wk(A, T) or {}).get("at", "") >= at0, "#3513: ... to now")
check(cl.get(path()).json().get("working", {}).get("agent_id") == CL, "#3513: GET answers what people see")
check(cl.post(path(), json={"text": "a", "colour": "red"}).status_code == 400, "#3513: an unknown field is refused (400)")
check(cl.post(path(), json={"text": 5}).status_code == 400, "#3513: text must be text (400)")
check(cl.delete(path() + "?state=lost").status_code == 400, "#3513: DELETE with an unknown state: 400")

# ================================================================== rights and the workspace boundary
check(ot.get(path(TR)).status_code == 200, "#3513: an agent that only reads the list sees the task (GET)")
check(ot.post(path(TR), json={"text": "I only read"}).status_code == 403, "#3513: ... but cannot mark it: 403")
check(not wk(A, TR), "#3513: ... nothing shows")
check(no.post(path(), json={"text": "Not mine"}).status_code == 404, "#3513: an agent the list is not shared with: 404")
check(no.get(path()).status_code == 404, "#3513: ... GET too")
check(A.post(path(), json={"text": "a person"}).status_code in (401, 403), "#3513: a person's session is no agent")
tok = A.post(B + "/api/me/tokens", json={"name": "mine", "scopes": ["read", "tasks:write"]})
if tok.ok and tok.json().get("token"):
    check(requests.post(path(), json={"text": "x"}, headers={"Authorization": "Bearer " + tok.json()["token"]}).status_code == 403,
          "#3513: a person's token cannot mark a task")
rd = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "reader", "display_name": "Reader"})
if rd.ok:
    RD = rd.json()["id"]
    A.put(B + f"/api/lists/{W}/members", json={"user_id": RD, "role": "edit"})
    check(requests.post(path(), json={"text": "x"}, headers={"Authorization": "Bearer " + rd.json()["token"]}).status_code == 403,
          "#3513: a token without tasks:write: 403")
check(state_task(Ca, T) is None and not any(x.get("working") for x in Ca.get(B + "/api/state").json().get("tasks", [])),
      "#3513: a person of another organisation never sees the task or the mark")
check(Ca.get(B + f"/api/tasks/{T}").status_code in (403, 404), "#3513: ... not even by its id")

# ================================================================== end, fade, job_id, plain jobs
r = cl.delete(path())
check(r.ok and r.json().get("ended") == 1 and r.json().get("working") is None, f"#3513: DELETE ends it {r.status_code} {r.text[:160]}")
check(not wk(A, T), "#3513: the mark is gone from the task")
check(kt.dbx("SELECT state FROM agent_jobs WHERE id=?", (JOB,))[0][0] == "done", "#3513: the job is done")
check(cl.patch(path(), json={"text": "late"}).status_code == 404, "#3513: PATCH when not working: 404 (starts nothing)")
check(not wk(A, T), "#3513: ... and shows nothing")
check(cl.delete(path()).json().get("ended") == 0, "#3513: a second DELETE is harmless (ended 0)")
r = cl.post(path(), json={"text": "Again"})
J2 = r.json()["job"]["id"] if r.status_code == 201 else None
check(J2 and J2 != JOB, "#3513: a new start after the end is a new job (201)")
old = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat(timespec="seconds")
kt.dbx("UPDATE agent_jobs SET updated_at=? WHERE id=?", (old, J2))
check(not wk(A, T), "#3513: 16 minutes without an update: the mark has faded")
g = cl.get(path()).json()
check(g.get("working") is None and (g.get("job") or {}).get("id") == J2, f"#3513: ... the job still runs (GET: working null, job) {g}")
cl.patch(path(), json={"text": "Back"})
check((wk(A, T) or {}).get("text") == "Back", "#3513: a new line brings the mark back")
check(cl.delete(path() + "?state=failed").ok and kt.dbx("SELECT state FROM agent_jobs WHERE id=?", (J2,))[0][0] == "failed",
      "#3513: DELETE ?state=failed ends the job as failed")
# two jobs of one agent on one task (a host with part jobs): job_id picks one
ja = cl.post(V + "/agent/jobs", json={"title": "Part A", "task_id": T}).json()["id"]
jb = cl.post(V + "/agent/jobs", json={"title": "Part B", "task_id": T}).json()["id"]
check((wk(A, T) or {}).get("agent_id") == CL, "#3513: a plain running job with task_id shows the same way")
kt.dbx("UPDATE agent_jobs SET updated_at=? WHERE id IN (?, ?)", ((datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(timespec="seconds"), ja, jb))
r = cl.patch(path(), json={"text": "line of A", "job_id": ja})
check(r.ok and r.json()["job"]["id"] == ja, f"#3513: job_id picks that job {r.status_code} {r.text[:160]}")
logs = {x[0]: x[1] for x in kt.dbx("SELECT id, log FROM agent_jobs WHERE id IN (?, ?)", (ja, jb))}
check("line of A" in (logs.get(ja) or "") and "line of A" not in (logs.get(jb) or ""), f"#3513: ... the other job is untouched {logs}")
check(cl.patch(path(T2), json={"text": "x", "job_id": ja}).status_code == 404, "#3513: a job of another task: 404")
check((wk(A, T) or {}).get("text") == "line of A", "#3513: the newest update of the task shows")
cl.patch(V + f"/agent/jobs/{ja}", json={"state": "done"})
cl.patch(V + f"/agent/jobs/{jb}", json={"state": "done"})
check(not wk(A, T), "#3513: ended plain jobs show nothing")
kt.dbx("INSERT INTO agent_jobs(agent_id,task_id,title,state,log,created_at,updated_at,kind,prop_state) VALUES(?,?,?,?,?,?,?,?,?)",
       (CL, T, "Proposal", "running", "thinking", NOW(), NOW(), "subtasks", "ready"))
check(not wk(A, T), "#3513: a proposal job never shows as working")

# ================================================================== freelancer-matrix: agents
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "fhelper", "display_name": "F Helper", "owner_id": FID})
assert r.ok, r.text
FAG = r.json()["id"]
fag = requests.Session()
fag.headers.update({"Authorization": "Bearer " + r.json()["token"]})
LF = Fr.post(B + "/api/lists", json={"name": "Frida A"}).json()["id"]
check(Fr.put(B + f"/api/lists/{LF}/members", json={"user_id": FAG, "role": "edit"}).ok, "freelancer #3513 setup: the own agent in the own project")
TF = Fr.post(B + "/api/tasks", json={"title": "Frida task", "list_id": LF}).json()["id"]
r = fag.post(path(TF), json={"text": "Invoice drafted", "name": "Holston"})
check(r.status_code == 201, f"freelancer #3513: the own agent marks her task ({r.status_code} {r.text[:200]})")
w = wk(Fr, TF)
check(w and w.get("name") == "Holston" and w.get("text") == "Invoice drafted", f"freelancer #3513: she sees name and line {w}")
check(not wk(Bo, TF) and state_task(Bo, TF) is None, "freelancer #3513: nobody else sees her task or the mark")
check(cl.post(path(TF), json={"text": "x"}).status_code == 404, "freelancer #3513: an agent of the organisation does not reach her task")
check(fag.delete(path(TF)).ok and not wk(Fr, TF), "freelancer #3513: ending it removes the mark")

sys.exit(kt.done("p2407_a"))
