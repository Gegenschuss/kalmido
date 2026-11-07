#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.627.0 (#4526): the people list GET /api/users of a person who is no instance admin carries per person only the
organisations the caller shares with them (the share dialog needs no more); the instance admin's list stays as it was.
Invented names only.
 - carl is in Alpha and Beta: bob (Alpha) reads only Alpha at carl, dave (admin of Beta) only Beta
 - the instance admin (alice, in Alpha only) reads both at carl, in the list and in the user management (?all=1)
 - freelancer-matrix: team (frida without an organisation, connected with carl through her own list, reads carl without
   any organisation id)
usage: p2627_d_users_test.py <datadir>      (a fresh container; P2627D_NOSTART=1 = the server already runs)"""
import sys

import requests

import dbx as dbxm
import kt
from freelancer_fixture import freelancer
from kt import B, check, sess

kt.fresh(prefix="P2627D", env={"KALMIDO_API_RATE": "100000"})
kt.docker_logs_on_first_fail()

s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}


def person(name, orgs):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com"})
    assert r.ok, r.text
    uid[name] = r.json()["id"]
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    return s


Da = person("dave", [])
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["dave"]})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = person("bob", [{"id": ORG, "role": "member"}])
Ca = person("carl", [{"id": ORG, "role": "member"}, {"id": ORG2, "role": "member"}])
FID, Fr = freelancer(B, A, "frida")
CARL = uid["carl"]
mem = lambda s: {o["id"] for o in s.get(B + "/api/orgs").json().get("orgs", [])}  # noqa: E731
check(mem(Ca) == {ORG, ORG2} and mem(Bo) == {ORG} and ORG2 in mem(Da) and ORG not in mem(Da),
      f"setup: carl in Alpha + Beta, bob in Alpha, dave in Beta ({mem(Ca)} {mem(Bo)} {mem(Da)})")


def row(s, who, q=""):
    r = s.get(B + "/api/users" + q)
    assert r.ok, r.text
    return next((u for u in r.json()["users"] if u["id"] == who), None)


x = row(Bo, CARL)
check(x is not None and x.get("orgs") == [ORG], f"#4526: bob (Alpha) reads only Alpha at carl, not Beta: {x and x.get('orgs')}")
x = row(Da, CARL)
check(x is not None and x.get("orgs") == [ORG2], f"#4526: dave (Beta) reads only Beta at carl: {x and x.get('orgs')}")
x = row(Ca, CARL)
check(x is not None and x.get("orgs") == [ORG, ORG2], f"#4526: carl reads his own organisations: {x and x.get('orgs')}")
x = row(Bo, uid["bob"])
check(x is not None and x.get("orgs") == [ORG], "#4526: bob's own row: Alpha")
check(all(set(u.get("orgs") or []) <= {ORG} for u in Bo.get(B + "/api/users").json()["users"]),
      "#4526: no row of bob's list names an organisation bob is not in")

# the instance admin as before
x = row(A, CARL)
check(x is not None and set(x.get("orgs") or []) == {ORG, ORG2}, f"#4526: the instance admin reads both at carl: {x and x.get('orgs')}")
x = row(A, CARL, "?all=1")
check(x is not None and set(x.get("orgs") or []) == {ORG, ORG2}, "#4526: ... in the user management, too")

# a person without an organisation (freelancer-matrix: team): connected with carl through her own list
r = Fr.post(B + "/api/lists", json={"name": "Garten"})
assert r.ok, r.text
L = r.json()["id"]
c = dbxm.connect(kt.DATA)
try:
    c.execute("INSERT INTO list_members(list_id, user_id, role, added_at) VALUES(?, ?, 'edit', '2026-11-07T08:00:00+00:00')", (L, CARL))
    c.commit()
finally:
    c.close()
x = row(Fr, CARL)
check(x is not None and x.get("orgs") == [], f"#4526: frida (no organisation) sees carl without any organisation id: {x}")
check(all(not u.get("orgs") for u in Fr.get(B + "/api/users").json()["users"]), "#4526: no row of frida's list names an organisation")

sys.exit(kt.done("p2627_d_users"))
