#!/usr/bin/env python3
"""2.36.2 API tests, part C (#1139): a list says with whom it is shared, by kind.
 - /api/state lists carry shared_people (number of people besides the viewer) and shared_agents (names of the agents)
 - a list shared only with an agent, only with a person, with both, not shared
 - seen from a member: the owner counts, the viewer does not; nobody is counted that the member list does not already show
 - a list stays unchanged in the database (the name keeps its emoji; #1135 is display only)
usage: p2362_c_api_test.py <datadir>"""
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


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
AG = r.json()["id"]

L_AG = A.post(B + "/api/lists", json={"name": "\U0001F916 Agent only"}).json()["id"]
L_P = A.post(B + "/api/lists", json={"name": "\U0001F3E0 Home"}).json()["id"]
L_BOTH = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]
L_NONE = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]
assert A.put(B + f"/api/lists/{L_AG}/members", json={"user_id": AG, "role": "edit"}).ok
assert A.put(B + f"/api/lists/{L_P}/members", json={"user_id": BOB, "role": "edit"}).ok
for uid in (BOB, CAROL, AG):
    r = A.put(B + f"/api/lists/{L_BOTH}/members", json={"user_id": uid, "role": "edit"})
    assert r.ok, r.text


def lists(s):
    return {l["id"]: l for l in s.get(B + "/api/state").json()["lists"]}


la = lists(A)
for lid, people, agents, shared, what in ((L_AG, 0, ["Claude"], True, "only an agent"), (L_P, 1, [], True, "only a person"),
                                          (L_BOTH, 2, ["Claude"], True, "people and an agent"), (L_NONE, 0, [], False, "not shared")):
    l = la[lid]
    check(l.get("shared_people") == people, f"{what}: shared_people {people} ({l.get('shared_people')})")
    check(l.get("shared_agents") == agents, f"{what}: shared_agents {agents} ({l.get('shared_agents')})")
    check(l.get("shared") is shared, f"{what}: shared {shared}")
check(la[L_AG]["name"] == "\U0001F916 Agent only", "the name keeps its emoji in the data")

# seen from Bob (a member): the owner is a person, Bob himself does not count
lb = lists(sess("bob"))
check(lb[L_P]["shared_people"] == 1 and lb[L_P]["shared_agents"] == [], f"member view: the owner counts, not me ({lb[L_P].get('shared_people')})")
check(lb[L_BOTH]["shared_people"] == 2 and lb[L_BOTH]["shared_agents"] == ["Claude"],
      f"member view of the team list: Alice + Carol, the agent ({lb[L_BOTH].get('shared_people')} {lb[L_BOTH].get('shared_agents')})")
check(L_AG not in lb and L_NONE not in lb, "lists not shared with Bob are not in his state")
mem_ids = {m["user_id"] for m in lb[L_BOTH]["members"]}
check(len(mem_ids - {BOB}) + 1 == lb[L_BOTH]["shared_people"] + len(lb[L_BOTH]["shared_agents"]),
      "the counts come only from the members (and the owner) the viewer already sees")

# taking the agent out: the list is shared with people only again
assert A.delete(B + f"/api/lists/{L_BOTH}/members/{AG}").ok
la = lists(A)
check(la[L_BOTH]["shared_agents"] == [] and la[L_BOTH]["shared_people"] == 2, f"agent removed ({la[L_BOTH].get('shared_agents')})")

print(f"p2362_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
