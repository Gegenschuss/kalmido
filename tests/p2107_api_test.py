#!/usr/bin/env python3
"""2.107.0 API tests (#1962): a chat of its own per job. Invented names only.
 - a job created for a person starts with ONE grey line in that person's chat (kind notice, job_id, job_msg start, the title
   as text, read at once); a job without a person or for another person: none in this chat
 - POST /api/agents/{id}/chat {job_id} (JSON and multipart): the message is stored with the job (job_id, job_parent), the
   agent gets the usual 'chat' event with message.job_id and data.job; a job of another agent, an unknown one or one the
   person cannot see: 400, nothing stored
 - GET ?job=: the start line, my message to the job, the agent's job messages and progress [{text, at}] (the job's
   append_log lines, only for the person it is for); the whole chat keeps messages without job_id
 - a person without an organisation (freelancer fixture) with an own agent: the same
tenant-matrix: agent
freelancer-matrix: agents
usage: p2107_api_test.py <datadir>      (a fresh container; P2107_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

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


if not os.environ.get("P2107_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
Bo, Ca = sess("bob"), sess("carol")


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": name, "display_name": name.title()})
    assert r.ok, r.text
    aid = r.json()["id"]
    A.patch(B + f"/api/admin/agents/{aid}", json={"org_id": ORG})
    return aid, {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"}


CL, CLH = agent("claude")
OT, OTH = agent("otto")
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
for m in (CL, BOB, CAROL):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": m, "role": "edit"}).ok, f"setup: {m} in the list")
W2 = A.post(B + "/api/lists", json={"name": "Otto", "org_id": ORG}).json()["id"]
for m in (OT, BOB):
    check(A.put(B + f"/api/lists/{W2}/members", json={"user_id": m, "role": "edit"}).ok, f"setup: {m} in otto's list")
for lid in (W, W2):
    A.patch(B + f"/api/lists/{lid}", json={"agent_members": True})


def job(hdr, title, who=BOB, base=V, **kw):
    r = requests.post(base + "/agent/jobs", headers=hdr, json={"title": title, **({"user_id": who} if who else {}), "state": "running", **kw})
    assert r.ok, r.text
    return r.json()["id"]


def chat(s, aid=CL, q=""):
    r = s.get(B + f"/api/agents/{aid}/chat" + q)
    return r.json() if r.ok else {"_status": r.status_code}


def events(h=CLH, since=0):
    r = requests.get(V + "/agent/events", headers=h, params={"since": since, "limit": 500})
    assert r.ok, r.text
    return [e for e in r.json()["data"] if e.get("event", e.get("type")) == "chat"]


# ================================================================== the start line
J = job(CLH, "Knox: Release 2.107 (own job chat)", log="Start")
NOP = job(CLH, "No person", who=None)
CJ = job(CLH, "Carla: for carol", CAROL)
msgs = chat(Bo).get("messages", [])
st = [m for m in msgs if m.get("job_id") == J]
check(len(st) == 1 and st[0]["kind"] == "notice" and st[0]["job_msg"] == "start" and st[0]["from"] == "agent"
      and st[0]["body"] == "Knox: Release 2.107 (own job chat)", "a job for bob: one start line in bob's chat " + str(st)[:300])
check(not [m for m in msgs if m.get("job_id") in (NOP, CJ)], "no start line for a job without a person / for carol in bob's chat")
check(not [m for m in chat(Ca).get("messages", []) if m.get("job_id") == J], "carol: no start line of bob's job")
check([m.get("job_id") for m in chat(Ca).get("messages", [])] == [CJ], "carol: the start line of her own job")
unread = [a.get("chat_unread") for a in Bo.get(B + "/api/agents").json().get("agents", []) if a.get("id") == CL]
check(unread in ([0], [None]), "the start line is never unread " + str(unread))
check(str(J) in (chat(Bo).get("jobs") or {}), "the chat answer carries the job of the start line (its card)")

# ================================================================== a message typed in the job's own chat
r = Bo.post(B + f"/api/agents/{CL}/chat", json={"body": "please also update the docs", "job_id": J})
check(r.status_code == 201 and r.json().get("job_id") == J and r.json().get("body") == "please also update the docs",
      "a message with job_id: stored with the job, the text as typed " + r.text[:200])
MB = r.json().get("id")
ev = [e for e in events() if (e.get("data") or {}).get("message", {}).get("id") == MB]
check(len(ev) == 1 and ev[0]["data"]["message"].get("job_id") == J and (ev[0]["data"].get("job") or {}).get("id") == J
      and (ev[0]["data"].get("job") or {}).get("title") == "Knox: Release 2.107 (own job chat)",
      "the agent's chat event: message.job_id + data.job " + str(ev)[:400])
r = Bo.post(B + f"/api/agents/{CL}/chat", data={"body": "a file for the job", "job_id": str(J)},
            files={"file": ("note.txt", b"hello", "text/plain")})
check(r.status_code == 201 and r.json().get("job_id") == J and len(r.json().get("attachments") or []) == 1,
      "job_id as a form field with a file " + r.text[:200])
r = Bo.post(B + f"/api/agents/{CL}/chat", json={"body": "plain message"})
check(r.status_code == 201 and r.json().get("job_id") is None, "without job_id: the whole chat as before " + r.text[:200])
MP = r.json().get("id")
ev = [e for e in events() if (e.get("data") or {}).get("message", {}).get("id") == MP]
check(len(ev) == 1 and "job" not in ev[0]["data"] and ev[0]["data"]["message"].get("job_id") is None, "a plain message's event has no job")
OTJ = job(OTH, "Otto: other agent")
n0 = len(chat(Bo).get("messages", []))
for bad, why in ((OTJ, "a job of another agent"), (999999, "an unknown job"), (CJ, "carol's job (bob cannot see it)"), ("x", "not a number"), (0, "zero")):
    r = Bo.post(B + f"/api/agents/{CL}/chat", json={"body": "to a wrong job", "job_id": bad})
    check(r.status_code == 400, f"{why}: 400 " + str(r.status_code))
check(len(chat(Bo).get("messages", [])) == n0, "the refused messages are not stored")
r = Bo.post(B + f"/api/agents/{CL}/chat", json={"body": "to an unknown job", "job_id": None})
check(r.status_code == 201 and r.json().get("job_id") is None, "job_id null = the whole chat " + r.text[:200])

# ================================================================== the job's own chat: progress lines
check(requests.patch(V + f"/agent/jobs/{J}", headers=CLH, json={"append_log": "Tests are running"}).ok, "the agent adds a progress line")
ra = requests.post(V + f"/agent/chats/{BOB}", headers=CLH, json={"body": "Knox: done", "job_id": J, "job_msg": "result"})
check(ra.status_code == 201, "the agent posts the job's result " + ra.text[:200])
jc = chat(Bo, q=f"?job={J}")
ids = [m["id"] for m in jc.get("messages", [])]
check(MB in ids and ra.json()["id"] in ids and MP not in ids, "?job=: my message to the job and the result, not the plain one " + str(ids))
check(any(m.get("job_msg") == "start" for m in jc.get("messages", [])), "?job=: the start line is the job chat's first row")
pr = jc.get("progress")
check(isinstance(pr, list) and [p["text"] for p in pr] == ["Start", "Tests are running"] and all(p.get("at") for p in pr),
      "?job=: progress = the job's log lines with their time " + str(pr))
check("progress" not in chat(Bo), "the whole chat has no progress field")
check(MP in [m["id"] for m in chat(Bo).get("messages", [])], "messages without job_id stay in the whole chat")
check(Ca.get(B + f"/api/agents/{CL}/chat?job={J}").status_code == 404, "carol: bob's job chat stays 404")
ja = chat(A, q=f"?job={J}")
check(ja.get("progress", []) == [], "alice (admin, may see the job): no progress lines of bob's job " + str(ja)[:200])

# ================================================================== a person without an organisation, own agent
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FU, F = freelancer(B, A, "frida")
ag = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]})
check(ag.status_code in (200, 201), "freelancer: an own agent " + ag.text[:200])
FA = ag.json().get("id")
tk = F.post(B + f"/api/my/agents/{FA}/token")
FH = {"Authorization": "Bearer " + tk.json().get("token", ""), "X-Requested-With": "kalmido"}
FJ = job(FH, "Mira: Release 1.4", who=FU, log="Begin")
fm = chat(F, FA).get("messages", [])
check([m.get("job_msg") for m in fm if m.get("job_id") == FJ] == ["start"], "freelancer: the start line of her job " + str(fm)[:300])
r = F.post(B + f"/api/agents/{FA}/chat", json={"body": "add a test", "job_id": FJ})
check(r.status_code == 201 and r.json().get("job_id") == FJ, "freelancer: a message in the job's chat " + r.text[:200])
ev = [e for e in events(FH) if (e.get("data") or {}).get("message", {}).get("id") == r.json().get("id")]
check(len(ev) == 1 and (ev[0]["data"].get("job") or {}).get("id") == FJ, "freelancer's agent: the event carries the job")
jf = chat(F, FA, f"?job={FJ}")
check([p["text"] for p in jf.get("progress", [])] == ["Begin"] and r.json().get("id") in [m["id"] for m in jf.get("messages", [])],
      "freelancer: the job's chat with message and progress " + str(jf)[:300])
r = F.post(B + f"/api/agents/{FA}/chat", json={"body": "x", "job_id": J})
check(r.status_code == 400, "freelancer: bob's job in her chat: 400 " + str(r.status_code))
check(Bo.post(B + f"/api/agents/{FA}/chat", json={"body": "x", "job_id": FJ}).status_code in (403, 404), "bob cannot write into the freelancer's agent chat")

print(f"p2107_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
