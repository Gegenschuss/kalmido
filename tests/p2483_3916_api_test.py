#!/usr/bin/env python3
# kalmido-suite:
"""2.483.0 API tests (#3916: default type of new tasks per list), own container (start.sh). Invented data only.
 - the list setting def_ttype ('' | bug | feature | task, owner), a bad value = 400, a member may not set it (403)
 - a task created without a type gets the list's default type (and its note template), an explicit type / '' wins,
   subtasks stay without; with ticket types off the default does nothing
 - the bug inbox of a software project (#3378) starts with the default type Bug; the agent API (v1) follows it
P4: a person without an organisation gets the same (freelancer-matrix: lists)
usage: p2483_3916_api_test.py <datadir>"""
import sys

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

kt.fresh(prefix="P2483A")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en"})
V = B + "/api/v1"


def lst(s, lid):
    return next(x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid)


def new(s, lid, **kw):
    r = s.post(B + "/api/tasks", json={"title": kw.pop("title", "T"), "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()


def case(s, who):
    L = s.post(B + "/api/lists", json={"name": "Tickets", "tickets": True}).json()["id"]
    check(lst(s, L).get("def_ttype") == "", f"{who}: no default type at first {lst(s, L).get('def_ttype')!r}")
    check(new(s, L)["ttype"] == "", f"{who}: without a default a new task has no type")
    r = s.patch(B + f"/api/lists/{L}", json={"def_ttype": "story"})
    check(r.status_code == 400, f"{who}: a bad default type = 400 {r.status_code}")
    r = s.patch(B + f"/api/lists/{L}", json={"def_ttype": "bug"})
    check(r.ok and lst(s, L)["def_ttype"] == "bug", f"{who}: the default type is stored {r.status_code}")
    t = new(s, L)
    check(t["ttype"] == "bug" and "Steps to reproduce" in (t.get("content") or ""), f"{who}: a new task is a bug with the template {t['ttype']!r}")
    check(new(s, L, ttype="feature")["ttype"] == "feature", f"{who}: an explicit type wins")
    check(new(s, L, ttype="")["ttype"] == "", f"{who}: an explicit empty type wins")
    sub = new(s, L, parent_id=t["id"])
    check(sub["ttype"] == "", f"{who}: a subtask gets no default type {sub['ttype']!r}")
    r = s.patch(B + f"/api/lists/{L}", json={"def_ttype": ""})
    check(r.ok and lst(s, L)["def_ttype"] == "" and new(s, L)["ttype"] == "", f"{who}: back to no default type {r.status_code} {r.text[:120]}")
    s.patch(B + f"/api/lists/{L}", json={"def_ttype": "bug"})
    s.patch(B + f"/api/lists/{L}", json={"tickets": False})
    check(new(s, L)["ttype"] == "", f"{who}: ticket types off = no default type")

    # the bug inbox (#3378) starts with Bug
    j = s.post(B + "/api/lists", json={"name": "App", "ptype": "software", "bug_inbox": True}).json()
    BUG = j["bug_list_id"]
    check(lst(s, BUG)["def_ttype"] == "bug" and lst(s, j["id"])["def_ttype"] == "", f"{who}: the bug list has Bug, the build list none")
    check(new(s, BUG, title="Crash")["ttype"] == "bug", f"{who}: a new task in the bug list is a bug")
    return BUG


BUG = case(A, "admin")
FID, Fr = freelancer(B, A)
case(Fr, "freelancer")

# a member with edit rights may not change the owner's setting
r = A.post(B + "/api/users", json={"username": "mia", "password": "password123", "display_name": "Mia"})
assert r.ok, r.text
MID = r.json()["id"]
r = A.put(B + f"/api/lists/{BUG}/members", json={"user_id": MID, "role": "edit"})
check(r.ok, f"share the bug list {r.status_code} {r.text[:120]}")
r = sess("mia").patch(B + f"/api/lists/{BUG}", json={"def_ttype": ""})
check(r.status_code == 403, f"member: the default type is the owner's {r.status_code} {r.text[:160]}")

# the agent API follows the default type
r = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]})
assert r.status_code == 201, r.text
PH = {"Authorization": "Bearer " + r.json()["token"]}
r = sess().post(V + "/tasks", headers=PH, json={"title": "From v1", "list_id": BUG})
check(r.status_code == 201 and r.json().get("type") == "bug", f"v1: a task without a type in the bug list is a bug {r.status_code} {r.text[:160]}")
r = sess().post(V + "/tasks", headers=PH, json={"title": "From v1 feature", "list_id": BUG, "type": "feature"})
check(r.status_code == 201 and r.json().get("type") == "feature", f"v1: an explicit type wins {r.text[:160]}")

sys.exit(kt.done("p2483_3916_api"))
