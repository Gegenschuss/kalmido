#!/usr/bin/env python3
"""2.46.6 part B API tests (#1680 #1708), own container (start.sh): what the agent views show about an agent's lists.
- /api/state: a personal agent in a list carries agent_owner (its owner's name) for the list's people; a team agent none
- the switch "Members may see and use the agent" does not open a personal agent to the members (the hint says so):
  it stays out of their agent list and they cannot chat with it
- a person outside the list sees neither the list nor the agent
- the owner moves the personal agent between private and the organisation (PATCH /api/my/agents/<id> org_id)
usage: p2466_b_api_test.py <datadir>"""
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


def state(s):
    return s.get(B + "/api/state").json()


def member(st, lid, uid):
    lst = {x["id"]: x for x in st["lists"]}.get(lid) or {}
    return next((m for m in lst.get("members", []) if m["user_id"] == uid), None)


# ---------------------------------------------------------------- setup
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Org", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en"})
ORG = state(A)["me"]["workspaces"][0]["id"]
check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2}).ok, "policy: personal agents on")

# ---------------------------------------------------------------- #1680: a personal agent in a shared list
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "display_name": "Bob bot"})
check(r.status_code == 201, "bob creates a personal agent " + r.text[:160])
BB = r.json()["id"]
BL = Bo.post(B + "/api/lists", json={"name": "Shoot plan", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": CAROL, "role": "edit"}).ok, "carol joins the list")
r = Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": BB, "role": "edit"})
if r.status_code == 409:  # the agent bridges lists with different people: the owner confirms
    r = Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": BB, "role": "edit", "bridge_ok": True})
check(r.ok, "bob shares the list with his agent " + r.text[:160])
m = member(state(Ca), BL, BB)
check(m and m.get("agent") and m.get("agent_owner") == "Bob", f"carol sees whose personal agent it is: {m}")
m = member(state(Bo), BL, BB)
check(m and m.get("agent_owner") == "Bob", f"bob sees it as his own: {m}")
check(Bo.patch(B + f"/api/lists/{BL}", json={"agent_members": True}).ok, "bob switches 'Members may see and use the agent' on")
check(BB not in [a["id"] for a in state(Ca)["agents"]], "#1680: with the switch on the personal agent stays out of carol's agents")
r = Ca.post(B + f"/api/agents/{BB}/chat", json={"text": "hello"})
check(r.status_code in (403, 404), f"#1680: carol cannot chat with bob's personal agent ({r.status_code})")
check(BB in [a["id"] for a in state(Bo)["agents"]], "bob still has his agent")

# a person outside the list: neither the list nor the agent
sd = state(Da)
check(BL not in [x["id"] for x in sd["lists"]], "dave does not see the list")
check("Shoot plan" not in str(sd["lists"]), "dave gets no list name")
check(BB not in [a["id"] for a in sd["agents"]], "dave does not see the agent")

# ---------------------------------------------------------------- a team agent: no agent_owner
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "teamy", "display_name": "Teamy"})
check(r.ok, "team agent created " + r.text[:160])
TA = r.json()["id"]
TL = A.post(B + "/api/lists", json={"name": "Team list", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{TL}/members", json={"user_id": CAROL, "role": "edit"})
r = A.put(B + f"/api/lists/{TL}/agent", json={"agent_id": TA})
if r.status_code == 409:
    r = A.put(B + f"/api/lists/{TL}/agent", json={"agent_id": TA, "bridge_ok": True})
check(r.ok, "the team agent joins the team list " + r.text[:160])
m = member(state(Ca), TL, TA)
check(m and m.get("agent") and "agent_owner" not in m, f"a team agent has no agent_owner: {m}")
check(TA not in [a["id"] for a in state(Ca)["agents"]], "switch off: carol cannot use the team agent")
A.patch(B + f"/api/lists/{TL}", json={"agent_members": True})
check(TA in [a["id"] for a in state(Ca)["agents"]], "switch on: carol can use the team agent")

# ---------------------------------------------------------------- #1708: the workspace of a personal agent
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot2", "display_name": "Bob bot 2"})
B2 = r.json()["id"]
mine = {a["id"]: a for a in Bo.get(B + "/api/my/agents").json()["agents"]}
check(mine[B2]["org_id"] == ORG, f"a new personal agent starts in the owner's organisation ('auto'): {mine[B2]['org_id']}")
r = Bo.patch(B + f"/api/my/agents/{B2}", json={"org_id": None})
check(r.ok and r.json()["org_id"] is None, "the owner makes it private " + r.text[:160])
r = Bo.patch(B + f"/api/my/agents/{B2}", json={"org_id": ORG})
check(r.ok and r.json()["org_id"] == ORG, "and back into the organisation " + r.text[:160])
r = Ca.patch(B + f"/api/my/agents/{B2}", json={"org_id": None})
check(r.status_code == 404, f"carol cannot move bob's agent ({r.status_code})")

print(f"p2466_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
