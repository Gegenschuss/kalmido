#!/usr/bin/env python3
"""2.96.0 API tests, part C (#2015): one card per job in the agent chat. Invented names only.
 - POST /api/v1/agent/chats/{uid} takes job_msg (say | question | result | error), only together with job_id (else 400),
   another value 400, an empty one = none; the message carries it back as job_msg (null without), for the person and the agent
 - GET /api/agents/{id}/chat carries jobs: {id: {id, name, title, version, state, parent_id, parent_name, updated_at}} of the
   jobs of the delivered messages (also with ?job= and ?after=), the state follows the job; another person's jobs never show
 - a person without an organisation (freelancer fixture) with an own agent: the same
tenant-matrix: agent
freelancer-matrix: agents
usage: p296_c_api_test.py <datadir>      (a fresh container; P296C_NOSTART=1 = the server already runs)"""
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


if not os.environ.get("P296C_NOSTART"):
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


def job(hdr, title, who=BOB, base=V):
    r = requests.post(base + "/agent/jobs", headers=hdr, json={"title": title, "user_id": who, "state": "running"})
    assert r.ok, r.text
    return r.json()["id"]


def say(body, hdr=CLH, who=BOB, **kw):
    return requests.post(V + f"/agent/chats/{who}", headers=hdr, json={"body": body, **kw})


def chat(s, aid=CL, q=""):
    r = s.get(B + f"/api/agents/{aid}/chat" + q)
    return r.json() if r.ok else {"_status": r.status_code}


LEAD = job(CLH, "Knox: Release 2.96 (job cards)")
PART = job(CLH, "Knox C: part C")
PLAIN = job(CLH, "Nightly audit")
OTJ = job(OTH, "Otto: other agent")
CJ = job(CLH, "Carla: Release 3.1.2a for carol", CAROL)

# ================================================================== job_msg on the agent's chat post
ids = {}
for k in ("say", "question", "result", "error"):
    r = say(f"Knox: {k}", job_id=LEAD, job_msg=k)
    check(r.status_code == 201 and r.json().get("job_msg") == k and r.json().get("job_id") == LEAD, f"job_msg {k} accepted and returned {r.status_code} {r.text[:200]}")
    ids[k] = r.json().get("id")
r = say("Knox: no kind", job_id=LEAD)
check(r.status_code == 201 and r.json().get("job_msg") is None, "without job_msg: null " + r.text[:200])
ids["none"] = r.json().get("id")
r = say("Knox: empty kind", job_id=LEAD, job_msg="")
check(r.status_code == 201 and r.json().get("job_msg") is None, "an empty job_msg = none " + r.text[:200])
r = say("no job", job_msg="result")
check(r.status_code == 400, "job_msg without job_id: 400 " + str(r.status_code))
r = say("Knox: bad", job_id=LEAD, job_msg="done")
check(r.status_code == 400, "job_msg with another value: 400 " + str(r.status_code))
r = say("Knox: bad", job_id=LEAD, job_msg=["result"])
check(r.status_code == 400, "job_msg not a string: 400 " + str(r.status_code))
r = say("Otto's job", job_id=OTJ, job_msg="result")
check(r.status_code == 400, "a job of another agent: 400 (unchanged) " + str(r.status_code))
r = requests.post(V + f"/agent/chats/{BOB}", headers=CLH, data={"body": "Knox: as a form", "job_id": str(LEAD), "job_msg": "result"})
check(r.status_code == 201 and r.json().get("job_msg") == "result", "job_msg in a multipart / form post " + r.text[:200])
r = say("Knox C: part done", job_id=PART, job_parent=LEAD, job_msg="result")
check(r.status_code == 201 and r.json().get("job_msg") == "result" and r.json().get("job_parent") == LEAD, "a part job's result with job_parent + job_msg " + r.text[:200])
mpart = r.json().get("id")
mplain = say("plain answer").json().get("id")
r = requests.get(V + "/agent/chats", headers=CLH, params={"user_id": BOB})
got = {m["id"]: m for m in (r.json().get("data") or [])} if r.ok else {}
check(r.ok and got.get(ids["result"], {}).get("job_msg") == "result" and got.get(mplain, {}).get("job_msg") is None,
      "the agent reads job_msg back in its own chat list " + r.text[:200])

# ================================================================== jobs in the person's chat answer
j = chat(Bo)
msgs = {m["id"]: m for m in j.get("messages", [])}
jobs = j.get("jobs") or {}
check(msgs.get(ids["error"], {}).get("job_msg") == "error" and msgs.get(ids["none"], {}).get("job_msg", "x") is None,
      "the person's chat: job_msg per message (null = unknown)")
L = jobs.get(str(LEAD)) or {}
check(L.get("id") == LEAD and L.get("name") == "Knox" and L.get("version") == "2.96" and L.get("state") == "running"
      and L.get("title") == "Knox: Release 2.96 (job cards)" and "updated_at" in L, "jobs: the leader with name, version, state " + str(L))
P = jobs.get(str(PART)) or {}
check(P.get("parent_id") == LEAD and P.get("parent_name") == "Knox" and P.get("name") == "Knox C" and P.get("version") == "",
      "jobs: the part job with its leader, no version in its title " + str(P))
check(str(PLAIN) not in jobs and str(OTJ) not in jobs and str(CJ) not in jobs, "jobs: only jobs of the delivered messages " + str(sorted(jobs)))
check(requests.patch(V + f"/agent/jobs/{LEAD}", headers=CLH, json={"state": "done"}).ok, "the agent ends the leader")
jobs = chat(Bo).get("jobs") or {}
check((jobs.get(str(LEAD)) or {}).get("state") == "done", "jobs: the state follows the job " + str(jobs.get(str(LEAD))))
r = chat(Bo, q=f"?after={mpart - 1}")
check(set(r.get("jobs") or {}) == {str(PART), str(LEAD)}, "?after=: the jobs of the newer messages (the part job + its leader) " + str(sorted(r.get("jobs") or {})))
r = chat(Bo, q=f"?after={mplain}")
check(r.get("messages") == [] and r.get("jobs") == {}, "?after= without new messages: jobs empty " + str(r)[:200])
r = chat(Bo, q=f"?job={PART}")
check(str(PART) in (r.get("jobs") or {}) and mpart in [m["id"] for m in r.get("messages", [])], "?job=: the job history carries its job " + str(r)[:200])

# ================================================================== tenant: another person never sees bob's jobs
cm = say("Carla: done", who=CAROL, job_id=CJ, job_msg="result")
check(cm.status_code == 201, "a job message for carol " + cm.text[:200])
r = say("Knox: to carol", who=CAROL, job_id=LEAD, job_msg="say")
check(r.status_code == 400, "a job of bob cannot be posted into carol's chat (400) " + str(r.status_code))
jc = chat(Ca)
check(set(jc.get("jobs") or {}) == {str(CJ)} and (jc["jobs"][str(CJ)].get("version") == "3.1.2a"), "carol: only her own job (version with a letter) " + str(jc.get("jobs")))
check(not ({ids["result"], mpart} & {m["id"] for m in jc.get("messages", [])}), "carol: none of bob's job messages")
ja = chat(A)
check(not ({str(LEAD), str(PART), str(CJ)} & set(ja.get("jobs") or {})), "alice (admin): her own chat carries none of the others' jobs " + str(ja.get("jobs")))
check(Ca.get(B + f"/api/agents/{CL}/chat?job={LEAD}").status_code == 404, "carol: bob's job history stays 404")

# ================================================================== a person without an organisation, own agent
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})  # the server's switch for personal agents
FU, F = freelancer(B, A, "frida")
ag = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]})
check(ag.status_code in (200, 201), "freelancer: an own agent " + ag.text[:200])
FA = ag.json().get("id")
tk = F.post(B + f"/api/my/agents/{FA}/token")
FH = {"Authorization": "Bearer " + tk.json().get("token", ""), "X-Requested-With": "kalmido"}
FJ = job(FH, "Mira: Release 1.4", who=FU)
r = requests.post(V + f"/agent/chats/{FU}", headers=FH, json={"body": "✅ Mira: done", "job_id": FJ, "job_msg": "result"})
check(r.status_code == 201 and r.json().get("job_msg") == "result", "freelancer's agent: job_msg accepted " + r.text[:200])
r = requests.post(V + f"/agent/chats/{FU}", headers=FH, json={"body": "x", "job_msg": "result"})
check(r.status_code == 400, "freelancer's agent: job_msg without job_id 400 " + str(r.status_code))
jf = chat(F, FA)
FJD = (jf.get("jobs") or {}).get(str(FJ)) or {}
check(FJD.get("state") == "running" and FJD.get("name") == "Mira" and FJD.get("version") == "1.4", "freelancer: jobs in the own chat " + str(jf)[:300])
check(chat(Bo, FA).get("_status") in (403, 404), "bob cannot open the freelancer's agent chat")
r = requests.post(V + f"/agent/chats/{FU}", headers=CLH, json={"body": "x", "job_id": LEAD, "job_msg": "say"})
check(r.status_code in (400, 403, 404), "another agent cannot post into the freelancer's chat " + str(r.status_code))

print(f"p296_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
