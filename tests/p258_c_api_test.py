#!/usr/bin/env python3
"""2.58.0 part C (API): #1761 an agent's list limit (list_ids) in /api/state reaches only the people who manage it (an
instance admin for a team agent, the owner of a personal agent); members who share lists with it never learn about it.
Usage: p258_c_api_test.py DATA_DIR"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
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


def agent_in_state(s, aid):
    return next((a for a in s.get(B + "/api/state").json().get("agents", []) if a["id"] == aid), None)


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "claude", "display_name": "Claude"})
CL = r.json()["id"]
lids = []
for n in ("One", "Two"):
    lid = A.post(B + "/api/lists", json={"name": n, "org_id": ORG}).json()["id"]
    lids.append(lid)
    for p in (BOB, CL):
        assert A.put(B + f"/api/lists/{lid}/members", json={"user_id": p, "role": "edit"}).ok
    assert A.patch(B + f"/api/lists/{lid}", json={"agent_members": True}).ok  # all members reach the agent there

# ---- #1761: no limit = [] for the admin, nothing for a member
a = agent_in_state(A, CL)
check(a is not None and a.get("list_ids") == [], "#1761: the admin sees an empty list limit (all lists) " + str(a and a.get("list_ids")))
b = agent_in_state(Bo, CL)
check(b is not None and "list_ids" not in b, "#1761: a member who shares lists with the agent gets no list_ids " + str(b and sorted(b))[:200])

r = A.patch(B + f"/api/admin/agents/{CL}", json={"list_ids": [lids[0]]})
check(r.ok, "#1761: the admin limits the agent to one list " + r.text[:160])
a = agent_in_state(A, CL)
check(a is not None and a.get("list_ids") == [lids[0]], "#1761: /api/state names the limit for the admin " + str(a and a.get("list_ids")))
b = agent_in_state(Bo, CL)
check(b is not None and "list_ids" not in b, "#1761: ... and still not for the member")

# a personal agent of Bob (made by the admin, owner_id): its owner sees the limit, the admin (not its owner) does not
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "bobhelper", "display_name": "Bobs helper", "owner_id": BOB, "org_id": ORG})
check(r.ok, "#1761: a personal agent for Bob " + r.text[:160])
if r.ok:
    PA = r.json()["id"]
    assert Bo.put(B + f"/api/lists/{lids[1]}/members", json={"user_id": PA, "role": "edit"}).ok or True
    a = agent_in_state(Bo, PA)
    check(a is not None and a.get("list_ids") == [], "#1761: the owner of a personal agent sees its list limit " + str(a)[:200])
    a = agent_in_state(A, PA)
    check(a is None or "list_ids" not in a, "#1761: the admin does not see the limit of someone else's personal agent")

print(f"{OKS[0]} checks passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
