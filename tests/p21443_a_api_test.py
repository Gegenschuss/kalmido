#!/usr/bin/env python3
"""2.147.1 API tests, part A (#2523): a task dragged into a chat is put in as "#123" (the client, refs.js); the server keeps
that text as it is and the client draws the reference card from it. Own container (start.sh). Invented names only.
 - team chat (a channel of the organisation) and a thread reply: a message with "#<id>" and an app link is stored and
   comes back with the same text
 - the agent chat: the same message is stored, the agent reads it over the API v1 with the same text
 - a person without an organisation (freelancer-matrix: chat): a direct message and the chat with the own agent keep "#<id>"
usage: p21443_a_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

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


def j(r):
    try:
        return r.json()
    except ValueError:
        return {}


if os.environ.get("P21443A_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
for x in (A, Bo):
    x.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
L = A.post(B + "/api/lists", json={"name": "Shoot", "org_id": ORG}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"title": "Write the brief", "list_id": L}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Book the studio", "list_id": L}).json()["id"]
check(T1 and T2, "setup: two tasks")
# what refs.js puts in for two tasks dragged at once and a list: "#1 #2" and a Markdown link to this app
BODY = f"Please look at #{T1} #{T2} and [Shoot](https://kalmido.example.com/#l/{L})"

# ================================================================== team chat
r = A.post(B + "/api/team/channels", json={"name": "Project", "org_id": ORG, "open": False, "members": [BOB]})
check(r.status_code == 201, "team: a channel " + r.text[:200])
PRJ = j(r).get("id")
r = A.post(B + f"/api/team/rooms/{PRJ}/messages", json={"body": BODY})
check(r.ok, "team: the message with references is stored " + r.text[:200])
M1 = j(r).get("id")
msgs = j(Bo.get(B + f"/api/team/rooms/{PRJ}/messages")).get("messages") or []
m = next((x for x in msgs if x.get("id") == M1), {})
check(m.get("body") == BODY, "team: bob gets the same text back " + repr(m.get("body")))
r = Bo.post(B + f"/api/team/rooms/{PRJ}/messages", json={"body": f"Done, see #{T1}", "thread_of": M1})
check(r.ok, "thread: a reply with a reference " + r.text[:200])
th = j(A.get(B + f"/api/team/rooms/{PRJ}/messages?thread={M1}")).get("messages") or []
check(any(x.get("body") == f"Done, see #{T1}" for x in th), "thread: the reply keeps the text " + repr([x.get("body") for x in th]))

# ================================================================== agent chat
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude", "org_id": ORG})
check(r.ok, "agent: created " + r.text[:200])
CL, CLH = j(r).get("id"), {"Authorization": "Bearer " + j(r).get("token", "")}
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": CL, "role": "edit"}).ok, "agent: the list is shared with it (the chat needs that)")
r = A.post(B + f"/api/agents/{CL}/chat", json={"body": BODY})
check(r.status_code == 201, "agent chat: the message with references is stored " + r.text[:200])
msgs = j(A.get(B + f"/api/agents/{CL}/chat")).get("messages") or []
check(any(x.get("body") == BODY and x.get("from") == "user" for x in msgs), "agent chat: the same text back")
ch = j(requests.get(V + "/agent/chats", headers=CLH)).get("data") or []
check(any(x.get("body") == BODY for x in ch), "agent chat: the agent reads the same text over the API v1 " + repr([x.get("body") for x in ch])[:200])

# ================================================================== a person without an organisation
# freelancer-matrix: chat
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, Fr = freelancer(B, A)
FIO, Fi = freelancer(B, A, "fiona")
DBC = dbx.connect(DATA)  # two freelancers work together through a group of the instance (as in p2139_b)
DBC.execute("INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES(?,?,?,?)", ("Freelance pool", "", "2026-10-21T08:00:00", ALICE))
GID = DBC.execute("SELECT id FROM groups WHERE name=?", ("Freelance pool",)).fetchone()[0]
for x in (FID, FIO):
    DBC.execute("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (GID, x, "2026-10-21T08:00:00"))
FL = j(Fr.post(B + "/api/lists", json={"name": "My shoot"})).get("id")
FT = j(Fr.post(B + "/api/tasks", json={"title": "Call the client", "list_id": FL})).get("id")
check(FL and FT, "freelancer: an own list and task")
r = Fr.post(B + "/api/team/dm", json={"user_id": FIO})
check(r.ok, "freelancer: a direct message with fiona " + r.text[:200])
FDM = j(r).get("id")
r = Fr.post(B + f"/api/team/rooms/{FDM}/messages", json={"body": f"See #{FT}"})
check(r.ok, "freelancer: a message with a reference " + r.text[:200])
msgs = j(Fi.get(B + f"/api/team/rooms/{FDM}/messages")).get("messages") or []
check(any(x.get("body") == f"See #{FT}" for x in msgs), "freelancer: fiona gets the same text")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida bot", "scopes": ["read", "comments"]})
check(r.status_code in (200, 201), "freelancer: an own agent " + r.text[:200])
FA = j(r).get("id")
check(Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "freelancer: the own list shared with the own agent")
r = Fr.post(B + f"/api/agents/{FA}/chat", json={"body": f"Check #{FT}"})
check(r.status_code == 201, "freelancer: agent chat with a reference " + r.text[:200])
msgs = j(Fr.get(B + f"/api/agents/{FA}/chat")).get("messages") or []
check(any(x.get("body") == f"Check #{FT}" for x in msgs), "freelancer: the same text back in the agent chat")

print(f"p21443_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
