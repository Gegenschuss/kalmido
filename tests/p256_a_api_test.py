#!/usr/bin/env python3
"""2.56.0 API tests, part A (#1791, #1793): talking to one job of an agent. Invented names only.
 - #1791 POST /api/agents/jobs/{id}/action {action: message, text}: the same right as stop (the person the job is for,
   an admin who reaches the agent, a list writer of its task; a reader 403, someone who cannot see the job 404), empty
   text 400, too long 400, an ended job 409; the agent gets the 'job' event {action: message, text, job, user}; the job
   row stays as it was (state, action fields); the other actions are unchanged (stop still ends the job)
 - #1793 job names: a job titled "Clara: Release 1.0" carries name "Clara" (part jobs "Clara B"), other titles null;
   GET /api/agents/{id}/chat?job={id}: only that job's messages (job_id), the person's own messages addressed to it
   ("Clara: ...", "Job N: ...", "#N: ...") and the agent's direct answers to those -- from the person's OWN conversation only;
   a job of another agent / one the person cannot see = 404; ?before= pages
usage: p256_a_api_test.py <datadir>      (a fresh container; P256A_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
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


if not os.environ.get("P256A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
BOB, CAROL, DAVE = uid["bob"], uid["carol"], uid["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": name, "display_name": name.title()})
    assert r.ok, r.text
    aid = r.json()["id"]
    A.patch(B + f"/api/admin/agents/{aid}", json={"org_id": ORG})
    return aid, {"Authorization": "Bearer " + r.json()["token"]}


CL, CLH = agent("claude")
OT, OTH = agent("otto")
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": CL, "role": "edit"}).ok, "setup: claude in the list")
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: bob writes in the list")
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": DAVE, "role": "view"}).ok, "setup: dave only reads the list")
A.patch(B + f"/api/lists/{W}", json={"agent_members": True})
W2 = A.post(B + "/api/lists", json={"name": "Otto", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{W2}/members", json={"user_id": OT, "role": "edit"})
T = A.post(B + "/api/tasks", json={"title": "Shared task", "list_id": W}).json()["id"]


def job(title, h=CLH, **kw):
    r = requests.post(V + "/agent/jobs", headers=h, json={"title": title, **kw})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def cursor(h=CLH):
    return requests.get(V + "/agent/events", headers=h, params={"since": 0, "limit": 500}).json()["cursor"]


def job_events(since, h=CLH):
    r = requests.get(V + "/agent/events", headers=h, params={"since": since, "limit": 500})
    assert r.ok, r.text
    return [e for e in r.json()["data"] if e.get("event", e.get("type")) == "job"]


def payload(e):
    return e.get("data") or e.get("payload") or e


def act(s, jid, **b):
    return s.post(B + f"/api/agents/jobs/{jid}/action", json=b)


def row(jid):
    return {x["id"]: x for x in A.get(B + "/api/agents/jobs?state=all").json()["jobs"]}.get(jid) or {}


# ================================================================== #1791 message from the job card
JA = job("Clara: Release 1.0", task_id=T, user_id=1)
before = row(JA)
check(before.get("state") == "running" and before.get("name") == "Clara", "#1793: the job carries its name " + str(before.get("name")))
cur = cursor()
r = act(A, JA, action="message", text="  Please also update the guide.  ")
check(r.status_code == 200 and r.json().get("ok"), "#1791: alice (the job is for her) sends a message " + r.text[:200])
ev = job_events(cur)
check(len(ev) == 1, "#1791: exactly one 'job' event " + str(len(ev)))
p = payload(ev[0]) if ev else {}
check(p.get("action") == "message" and p.get("text") == "Please also update the guide." and (p.get("job") or {}).get("id") == JA
      and (p.get("user") or {}).get("name") == "Alice", "#1791: the event carries action, the trimmed text, job, user " + str(p)[:300])
after = row(JA)
check(after.get("state") == "running" and after.get("action") == before.get("action") and after.get("action_by") == before.get("action_by")
      and after.get("action_at") == before.get("action_at"), "#1791: the job row stays as it was " + str(after)[:200])
cur = cursor()
check(act(A, JA, action="message", text="   ").status_code == 400, "#1791: empty text 400")
check(act(A, JA, action="message").status_code == 400, "#1791: no text 400")
check(act(A, JA, action="message", text=["x"]).status_code == 400, "#1791: text not a string 400")
check(act(A, JA, action="message", text="x" * 4001).status_code == 400, "#1791: too long 400")
check(act(A, JA, action="message", text="x" * 4000).status_code == 200, "#1791: 4000 characters are fine")
check(act(Bo, JA, action="message", text="from bob").status_code == 200, "#1791: bob (writes in the task's list, may stop) may write too")
check(act(Da, JA, action="message", text="from dave").status_code == 403, "#1791: dave (only reads the list) 403 like stop")
check(act(Da, JA, action="stop").status_code == 403, "#1791: ... and dave may not stop either (unchanged)")
check(act(Ca, JA, action="message", text="from carol").status_code == 404, "#1791: carol (no access to the task) 404")
r = requests.post(B + f"/api/agents/jobs/{JA}/action", headers={**CLH, **H}, json={"action": "message", "text": "self"})
check(r.status_code in (401, 403, 404), "#1791: the agent's own token cannot use the person route " + str(r.status_code))
check(len(job_events(cur)) == 2, "#1791: only the two accepted messages reached the agent")
check(act(A, JA, action="poke", text="x").status_code == 400, "#1791: unknown action still 400")
# stop is unchanged and an ended job takes no message
check(act(A, JA, action="stop").status_code == 200 and row(JA).get("state") == "stopped", "#1791: stop still ends the job")
check(act(A, JA, action="message", text="too late").status_code == 409, "#1791: an ended job 409")
JD = job("Ben: Done one", user_id=1)
requests.patch(V + f"/agent/jobs/{JD}", headers=CLH, json={"state": "done"})
check(act(A, JD, action="message", text="x").status_code == 409, "#1791: a done job 409")
JW = job("Plain waiting job", user_id=1)
requests.patch(V + f"/agent/jobs/{JW}", headers=CLH, json={"state": "waiting"})
check(act(A, JW, action="message", text="x").status_code == 200 and row(JW).get("state") == "waiting", "#1791: a waiting job takes a message, stays waiting")
# 2.56.0 review: a paused agent gets nothing -> 409, never "sent"
check(A.patch(B + f"/api/admin/agents/{CL}", json={"enabled": False}).ok, "setup: pause claude")
r = act(A, JW, action="message", text="while paused")
check(r.status_code == 409, "#1791: a paused agent -> 409 " + str(r.status_code))
check(A.patch(B + f"/api/admin/agents/{CL}", json={"enabled": True}).ok, "setup: claude on again")
check(row(JW).get("name") is None, "#1793: a title without a name -> name null")
check(row(job("Clara B: Part A", user_id=1)).get("name") == "Clara B", "#1793: a part job's name")

# ================================================================== #1793 the job's own history
JC = job("Clara: Release 2.0", user_id=1)
JF = job("Frida: Other release", user_id=1)


def say(to, body, h=CLH, **kw):
    r = requests.post(V + f"/agent/chats/{to}", headers=h, json={"body": body, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def post(s, body, aid=CL):
    r = s.post(B + f"/api/agents/{aid}/chat", json={"body": body})
    assert r.ok, r.text
    return r.json()["id"]


m1 = say(1, f"Job #{JC} started", job_id=JC)
m2 = say(1, f"Job #{JF} started", job_id=JF)
m3 = post(A, "Clara: please hurry")
m4 = say(1, "Delivered to Clara.", reply_to=m3)
m5 = post(A, f"Job {JC}: one more")
m6 = post(A, f"#{JC}: and another")
m7 = post(A, "Frida: not for clara")
m8 = post(A, "I like Clara a lot")  # the name only somewhere in the text: not addressed
m9 = say(1, "Something else")
m10 = say(1, f"Clara: done", job_id=JC)
# 2.56.1: bob's job starts before his message (history counts addressed messages from the job's start on; Postgres keeps
# sub-second times, SQLite whole seconds)
JB = job("Clara: Bob's run", task_id=T, user_id=BOB)
mb = post(Bo, "Clara: bob writes to her too")  # bob's own conversation: never in alice's history
r = A.get(B + f"/api/agents/{CL}/chat?job={JC}")
check(r.ok, "#1793: alice reads the job's history " + r.text[:200])
# 2.153.0 (#1962): a job created for a person starts with its start line (a notice) -- the first row of its history
nid = lambda r: [m["id"] for m in r.json().get("messages", []) if m.get("job_msg") != "start"]  # noqa: E731
starts = lambda r: [m["id"] for m in r.json().get("messages", []) if m.get("job_msg") == "start"]  # noqa: E731
check(r.ok and len(starts(r)) == 1 and r.json()["messages"][0]["job_msg"] == "start", "2.153.0: the job's start line opens its history")
got = nid(r) if r.ok else []
check(got == [m1, m3, m4, m5, m6, m10], f"#1793: only the job's messages, oldest first {got} vs {[m1, m3, m4, m5, m6, m10]}")
check(mb not in got and m8 not in got and m7 not in got and m2 not in got and m9 not in got, "#1793: nothing else")
r = A.get(B + f"/api/agents/{CL}/chat?job={JF}")
check(nid(r) == [m2, m7], "#1793: Frida's history")
r = A.get(B + f"/api/agents/{CL}/chat?job={JC}&limit=2")
check([m["id"] for m in r.json()["messages"]] == [m6, m10] and r.json().get("has_more") is True, "#1793: ?limit= gives the newest + has_more")
r = A.get(B + f"/api/agents/{CL}/chat?job={JC}&before={m5}")
check(nid(r) == [m1, m3, m4] and r.json().get("has_more") is False, "#1793: ?before= pages " + str([m["id"] for m in r.json()["messages"]]))
r = A.get(B + f"/api/agents/{CL}/chat?job={JC}&after={m5}")
check([m["id"] for m in r.json()["messages"]] == [m6, m10], "#1793: ?after= only newer ones (the refresh) " + str([m["id"] for m in r.json()["messages"]]))
r = Bo.get(B + f"/api/agents/{CL}/chat?job={JC}")
check(r.status_code == 404, "#1793: bob cannot open a job that is not for him (and not on a task he sees) " + str(r.status_code))
r = Bo.get(B + f"/api/agents/{CL}/chat?job={JB}")
check(r.ok and nid(r) == [mb], "#1793: bob's job history = his own conversation only")
r = A.get(B + f"/api/agents/{CL}/chat?job={JB}")
check(r.ok and mb not in [m["id"] for m in r.json()["messages"]], "#1793: alice (admin) opens bob's job but sees none of bob's messages")
JO = job("Otto: Elsewhere", h=OTH, user_id=1)
check(A.get(B + f"/api/agents/{CL}/chat?job={JO}").status_code == 404, "#1793: a job of another agent 404")
check(A.get(B + f"/api/agents/{CL}/chat?job=999999").status_code == 404, "#1793: an unknown job 404")
check(A.get(B + f"/api/agents/{CL}/chat?job=abc").status_code == 400, "#1793: a broken job id 400")
check(Ca.get(B + f"/api/agents/{CL}/chat?job={JC}").status_code == 404, "#1793: carol (no chat with claude) 404")
r = A.get(B + f"/api/agents/{CL}/chat")
check(r.ok and {m1, m2, m8, m9}.issubset({m["id"] for m in r.json()["messages"]}), "#1793: the main chat is unchanged")

print(f"p256_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
