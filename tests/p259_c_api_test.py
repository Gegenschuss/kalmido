#!/usr/bin/env python3
"""2.59.0 API tests (part C), own container (start.sh).
 - #1827: the first chat answer with job_id + job_parent stores the leader at the job (agent_jobs.parent_id, job JSON
   parent_id, set once); messages with a job_id carry job_name, job_parent (the message's, else the job's) and
   job_parent_name -- only of jobs the reader may see; a leader of another agent / person stays 400 (as since 2.47.3)
usage: p259_c_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
V = B + "/api/v1"
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def py(code):
    p = subprocess.run(["docker", "exec", "-i", "-w", "/app", CT, "python", "-"], input=code, capture_output=True, text=True)
    return p.stdout.strip(), p.stderr[-600:]


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


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
W2 = A.post(B + "/api/lists", json={"name": "Otto", "org_id": ORG}).json()["id"]  # one agent per list (as p256_a)
for m in (OT, BOB):
    check(A.put(B + f"/api/lists/{W2}/members", json={"user_id": m, "role": "edit"}).ok, f"setup: {m} in otto's list")


def job(hdr, title, who=BOB):
    r = requests.post(V + "/agent/jobs", headers=hdr, json={"title": title, "user_id": who, "state": "running"})
    assert r.ok, r.text
    return r.json()["id"]


def say(body, hdr=CLH, who=BOB, **kw):
    return requests.post(V + f"/agent/chats/{who}", headers=hdr, json={"body": body, **kw})


def chat(s, aid=CL):
    r = s.get(B + f"/api/agents/{aid}/chat")
    return {m["id"]: m for m in r.json().get("messages", [])} if r.ok else {}


LEAD = job(CLH, "Walker: Release 2.59")
PART = job(CLH, "Walker E: part C")
PLAIN = job(CLH, "Nightly audit")
OTJ = job(OTH, "Otto: other agent")
CJ = job(CLH, "Carla: for carol", CAROL)

# ---- the leader is stored at the job, once
r = say(f"Job #{PART}: part starts", job_id=PART, job_parent=LEAD)
check(r.status_code == 201, f"part message posted {r.status_code} {r.text[:200]}")
m1 = r.json()
check(m1.get("job_name") == "Walker E" and m1.get("job_parent") == LEAD and m1.get("job_parent_name") == "Walker",
      f"the answer carries job_name / job_parent / job_parent_name {m1.get('job_name')} {m1.get('job_parent')} {m1.get('job_parent_name')}")
r = requests.get(V + f"/agent/jobs/{PART}", headers=CLH)
check(r.ok and r.json().get("parent_id") == LEAD, f"the job keeps its leader (parent_id) {r.text[:200]}")
r = say(f"Job #{PART}: later, without job_parent", job_id=PART)
check(r.status_code == 201 and r.json().get("job_parent") == LEAD and r.json().get("job_parent_name") == "Walker",
      f"a later message without job_parent: the job's leader {r.text[:200]}")
m2 = r.json()["id"]
r = say(f"Job #{PART}: another leader", job_id=PART, job_parent=PLAIN)
check(r.status_code == 201 and r.json().get("job_parent") == PLAIN and r.json().get("job_parent_name") is None, "a message keeps its own job_parent (a leader without a name: null name)")
r = requests.get(V + f"/agent/jobs/{PART}", headers=CLH)
check(r.ok and r.json().get("parent_id") == LEAD, "once set, the job's leader stays")
r = say(f"Job #{LEAD}: leader", job_id=LEAD)
check(r.status_code == 201 and r.json().get("job_name") == "Walker" and r.json().get("job_parent") is None and r.json().get("job_parent_name") is None, "the leader: its name, no parent")
r = say(f"Job #{PLAIN}: nameless", job_id=PLAIN)
check(r.status_code == 201 and r.json().get("job_name") is None, "a job without a name: job_name null")
r = say("no job")
check(r.status_code == 201 and r.json().get("job_id") is None and r.json().get("job_name") is None, "a message without job: no name")

# ---- foreign leaders stay 400 (as the neighbours: job_id / job_parent since 2.47.3), nothing stored
check(say("x", job_id=PLAIN, job_parent=OTJ).status_code == 400, "a job of another agent as leader: 400")
check(say("x", job_id=PLAIN, job_parent=CJ).status_code == 400, "a job of the same agent for another person as leader: 400")
r = requests.get(V + f"/agent/jobs/{PLAIN}", headers=CLH)
check(r.ok and r.json().get("parent_id") is None, "a refused leader is not stored")

# ---- the person's chat and the agent's chat list carry the names
mb = chat(Bo)
check(mb.get(m1["id"], {}).get("job_name") == "Walker E" and mb[m1["id"]].get("job_parent_name") == "Walker", f"bob's chat: names {mb.get(m1['id'])}")
check(mb.get(m2, {}).get("job_parent") == LEAD, "bob's chat: the job's leader on a message without job_parent")
r = requests.get(V + "/agent/chats", headers=CLH, params={"user_id": BOB})
dm = {m["id"]: m for m in r.json().get("data", [])} if r.ok else {}
check(dm.get(m1["id"], {}).get("job_name") == "Walker E" and dm[m1["id"]].get("job_parent_name") == "Walker", f"the agent's chat list: names {r.status_code} {str(dm.get(m1['id']))[:200]}")
r = A.get(B + "/api/agents/jobs", params={"id": PART})
js = r.json().get("jobs", []) if r.ok else []
check(js and js[0].get("parent_id") == LEAD and js[0].get("name") == "Walker E", f"the app's job list: parent_id + name {str(js)[:200]}")

# ---- a leader the reader may not see: no number, no name (simulated: the leader belongs to carol now)
out, err = py(f"""
import sys
sys.path.insert(0, "/app")
from kalmido.core.db import connect
c = connect()
c.execute("UPDATE agent_jobs SET user_id=? WHERE id=?", ({CAROL}, {LEAD}))
c.commit()
print("ok")
""")
check(out.endswith("ok"), f"setup: leader moved {out} {err}")
mb = chat(Bo)
x = mb.get(m1["id"], {})
check(x.get("job_name") == "Walker E" and x.get("job_parent") is None and x.get("job_parent_name") is None, f"bob may not see the leader: neither its number nor its name {x.get('job_parent')} {x.get('job_parent_name')}")
r = requests.get(V + "/agent/chats", headers=CLH, params={"user_id": BOB})
dm = {m["id"]: m for m in r.json().get("data", [])} if r.ok else {}
check(dm.get(m1["id"], {}).get("job_parent_name") == "Walker", "the agent sees its own leader job")
# the job itself invisible: the message keeps its job_id (as before), but no name
out, err = py(f"""
import sys
sys.path.insert(0, "/app")
from kalmido.core.db import connect
c = connect()
c.execute("UPDATE agent_jobs SET user_id=? WHERE id=?", ({CAROL}, {PART}))
c.commit()
print("ok")
""")
x = chat(Bo).get(m1["id"], {})
check(x.get("job_id") == PART and x.get("job_name") is None and x.get("job_parent") is None, f"a job bob may not see: no name {str(x)[:200]}")
check(not any(m.get("job_name") for m in chat(Ca).values()), "carol's own chat holds none of bob's messages")

print(f"p259_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
