#!/usr/bin/env python3
"""2.46.0 part D API tests (#1563): the boundary check of Administration > Organisation names what it found -- kind, object,
person / agent -- for the instance admin only; "Clean up" (POST /api/admin/orgs/boundary/repair) takes out the memberships
of people and leaves agents alone.
usage: p2460_d_api_test.py <datadir>      (a fresh container)"""
import os
import dbx as dbxm
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
TS = "2026-10-01T00:00:00+00:00"


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
# 2.46.0 (#1592): no organisation from the start any more: create the one these tests use (id 1), new people join it
assert A.post(B + "/api/admin/orgs", json={"name": "Kalmido"}).ok
ids = {}
for u in ("bob", "eve"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, EVE = ids["bob"], ids["eve"]
Bo = sess("bob")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "alicebot", "display_name": "Alice bot", "owner_id": 1})
PA = r.json()["id"]
check(A.patch(B + f"/api/admin/agents/{PA}", json={"org_id": None}).ok, "setup: a private personal agent")
LID = A.post(B + "/api/lists", json={"name": "Team plans"}).json()["id"]
dbx("UPDATE lists SET org_id=?, name='Team plans' WHERE id=?", (ORG, LID), write=True)
# eve is not in the organisation; her membership of its list and the private agent's are findings
dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG, EVE), write=True)
for u in (EVE, PA):
    dbx("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,'edit',?) ON CONFLICT DO NOTHING", (LID, u, TS), write=True)

bd = A.get(B + "/api/admin/orgs").json()["boundary"]
det = bd.get("details") or []
person = [x for x in det if x["user_id"] == EVE]
agent = [x for x in det if x["user_id"] == PA]
check(bd["violations"] == len(det) and len(det) >= 2, "#1563: one detail per finding " + str(bd))
check(person and person[0]["type"] == "list" and person[0]["name"] == "Team plans" and person[0]["user"] == "Eve" and not person[0]["agent"] and person[0]["fixable"],
      "#1563: a person: kind list, the list's name, the person's name, fixable " + str(person))
check(agent and agent[0]["type"] == "list" and agent[0]["agent"] and agent[0]["user"] == "Alice bot" and not agent[0]["fixable"],
      "#1563: an agent: named and not fixable " + str(agent))
check(Bo.get(B + "/api/admin/orgs").status_code == 403, "#1563: the details are for the instance admin only (the list refuses others)")
check(Bo.post(B + "/api/admin/orgs/boundary/repair", json={}).status_code == 403, "#1563: Clean up is for the instance admin only")
check(requests.post(B + "/api/admin/orgs/boundary/repair", json={}, headers=H).status_code in (401, 403), "#1563: Clean up needs a login")

r = A.post(B + "/api/admin/orgs/boundary/repair", json={})
check(r.ok and r.json()["removed"] == 1, "#1563: Clean up removes the person's membership " + r.text[:200])
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (LID, EVE)), "#1563: eve is out of the list")
check(dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (LID, PA)), "#1563: the agent stays (moved by hand)")
bd = r.json()["boundary"]
check(bd["violations"] == 1 and [x["user_id"] for x in bd["details"]] == [PA] and not bd["details"][0]["fixable"], "#1563: only the agent is left " + str(bd))
r = A.post(B + "/api/admin/orgs/boundary/repair", json={})
check(r.ok and r.json()["removed"] == 0, "#1563: a second run removes nothing")

print(f"p2460_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
