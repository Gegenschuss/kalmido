#!/usr/bin/env python3
"""2.442.0 (#1762): one-command setup of an agent: the token made along with the new agent goes when the code is redeemed.
freelancer-matrix: agents
 - a person without an organisation: after the redeem the agent has exactly one computer (the named one), the old token no
   longer works
 - a team agent the same way
 - the token made with the agent stays when it was already used (a computer set up by hand), a token made by hand stays too
usage: p2442_a_token_test.py <datadir>"""
import sys

import requests
from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup

H = {"X-Requested-With": "kalmido"}
fresh(prefix="P2442A")
A = setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
_, F = freelancer(B, A)


def code(s, path):
    r = s.post(B + path + "/setup-code", json={"os": "linux", "folder": "/work/x"})
    assert r.ok, r.text
    return r.json()["code"]


def redeem(c, host="box"):
    r = requests.post(B + "/api/agent-setup/redeem", headers=H, json={"code": c, "host": host, "folder": "/work/x", "os": "linux"})
    assert r.ok, r.text
    return r.json()["token"]


def works(tok):
    return requests.get(B + "/api/v1/me", headers={"Authorization": "Bearer " + tok}).status_code == 200


def machines(s, path):
    return s.get(B + path + "/machines").json()["machines"]


r = F.post(B + "/api/my/agents", json={"username": "helper", "display_name": "Helper"})
assert r.ok, r.text
P, first = f"/api/my/agents/{r.json()['id']}", r.json()["token"]
tok = redeem(code(F, P))
m = machines(F, P)
check([x["host"] for x in m] == ["box"], f"personal agent: only the named computer is left {m}")
check(not works(first) and works(tok), "personal agent: the token made with it is revoked, the new one works")
tok2 = redeem(code(F, P), "box2")
check(sorted(x["host"] for x in machines(F, P)) == ["box", "box2"] and works(tok), "a second computer leaves the first one alone")

r = A.post(B + "/api/admin/agents", json={"username": "teamhelper", "display_name": "Team Helper"})
assert r.ok, r.text
T, first = f"/api/admin/agents/{r.json()['id']}", r.json()["token"]
redeem(code(A, T))
check([x["host"] for x in machines(A, T)] == ["box"] and not works(first), "team agent: the same")

r = F.post(B + "/api/my/agents", json={"username": "byhand", "display_name": "By hand"})
assert r.ok, r.text
P, first = f"/api/my/agents/{r.json()['id']}", r.json()["token"]
check(works(first), "a token in use")
redeem(code(F, P))
check(works(first) and len(machines(F, P)) == 2, "a token made with the agent and already used stays")
sys.exit(done("p2442_a_token"))
