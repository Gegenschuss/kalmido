#!/usr/bin/env python3
"""2.270.0 A (#3019): stale dialogs no longer write old full states back. Own container in mode workspaces. Invented people only.
freelancer-matrix: lists
 - PATCH /api/lists/<id> with _prev: a field another device changed meanwhile stays (conflicts), the others are written;
   also org_id (no move back) and columns; booleans / numbers compare by value (no false conflict); without _prev as before
 - organisation members / admins: members_add / members_remove / admins_add / admins_remove (and the sets with _prev)
   change only those people: who joined or became admin meanwhile stays; the old set format still replaces (compatibility)
 - PATCH /api/users/<id> with _prev orgs: only the difference (an organisation added meanwhile stays)
 - project description: expect_updated_at -> 409 with the current overview (web and token API), the earlier text in
   GET /api/lists/<id>/overview/history; without expect_updated_at as before
 - the same for a person without an organisation (own project, own description)
usage: p2270_a_conflict_test.py <datadir>      (P2270A_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2270A")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,progress,fields,time"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]


def user(name):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com", "orgs": []})
    assert r.ok, r.text
    return r.json()["id"]


BOB, CAROL, DAVE = user("bob"), user("carol"), user("dave")
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ALICE}).json()["id"]


def lst(s, lid):
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)


def org(oid):
    return next(x for x in A.get(B + "/api/admin/orgs").json()["orgs"] if x["id"] == oid)


def list_checks(s, who):
    lid = s.post(B + "/api/lists", json={"name": "Plan"}).json()["id"]
    # device 2 renames; device 1 (opened before) changes the colour and still has the old name in its form
    check(s.patch(B + f"/api/lists/{lid}", json={"name": "Plan B"}).ok, f"{who}: rename on device 2")
    r = s.patch(B + f"/api/lists/{lid}", json={"name": "Plan", "color": "#2e7d32", "_prev": {"name": "Plan", "color": ""}})
    j = r.json()
    check(r.ok and [c["field"] for c in j.get("conflicts", [])] == ["name"], f"{who}: stale name reported as conflict: {r.text}")
    x = lst(s, lid)
    check(x["name"] == "Plan B" and x["color"] == "#2e7d32", f"{who}: name of device 2 kept, colour written: {x['name']} {x['color']}")
    # booleans and numbers by value: no false conflict (stored 0 / 50.0, sent false / "50")
    s.patch(B + f"/api/lists/{lid}", json={"rate": 50})
    r = s.patch(B + f"/api/lists/{lid}", json={"dep_shift": True, "rate": "60", "_prev": {"dep_shift": False, "rate": "50"}})
    x = lst(s, lid)
    check(r.ok and not r.json().get("conflicts") and x["dep_shift"] and float(x["rate"]) == 60, f"{who}: no false conflict: {r.text}")
    # columns (settings JSON): another device chose others meanwhile
    s.patch(B + f"/api/lists/{lid}", json={"columns": ["prio", "due"]})
    r = s.patch(B + f"/api/lists/{lid}", json={"columns": ["id"], "_prev": {"columns": None}})
    check(r.ok and [c["field"] for c in r.json().get("conflicts", [])] == ["columns"] and lst(s, lid)["columns"] == ["prio", "due"],
          f"{who}: stale columns not written: {r.text}")
    # without _prev: as before (old clients)
    r = s.patch(B + f"/api/lists/{lid}", json={"name": "Plan C"})
    check(r.ok and lst(s, lid)["name"] == "Plan C", f"{who}: without _prev the value is written")
    return lid


def desc_checks(s, who, tok=None):
    lid = s.post(B + "/api/lists", json={"name": "Launch", "kind": "project"}).json()["id"]
    ov = B + f"/api/lists/{lid}/overview"
    r = s.patch(ov, json={"description": "one", "expect_updated_at": None})
    check(r.ok and r.json()["description"] == "one" and r.json().get("description_at"), f"{who}: first description: {r.text}")
    d1 = r.json()["description_at"]
    r = s.patch(ov, json={"description": "two", "expect_updated_at": d1})
    check(r.ok and r.json()["description_at"] != d1, f"{who}: saved on top of the state it started from: {r.text}")
    r = s.patch(ov, json={"description": "three", "expect_updated_at": d1})
    check(r.status_code == 409 and r.json().get("current", {}).get("description") == "two", f"{who}: stale save -> 409 + current: {r.status_code} {r.text[:200]}")
    check(s.get(ov).json()["description"] == "two", f"{who}: nothing written by the stale save")
    h = s.get(ov + "/history").json().get("history", [])
    check([x["text"] for x in h][:1] == ["one"], f"{who}: the replaced text is in the history: {h}")
    r = s.patch(ov, json={"description": "four"})
    check(r.ok and r.json()["description"] == "four", f"{who}: without expect_updated_at as before")
    if tok:  # the token API: 409 with the current overview in error.current
        hd = {"Authorization": "Bearer " + tok}
        r = requests.patch(B + f"/api/v1/lists/{lid}/overview", headers=hd, json={"description": "five", "expect_updated_at": d1})
        check(r.status_code == 409 and (r.json().get("error") or {}).get("current", {}).get("description") == "four",
              f"{who}: v1 stale save -> 409 + current: {r.status_code} {r.text[:200]}")
        cur = requests.get(B + f"/api/v1/lists/{lid}/overview", headers=hd).json()
        r = requests.patch(B + f"/api/v1/lists/{lid}/overview", headers=hd, json={"description": "five", "expect_updated_at": cur.get("description_at")})
        check(r.ok and r.json()["description"] == "five", f"{who}: v1 save with the current state: {r.status_code} {r.text[:200]}")


# ---- lists: _prev for every setting, org_id
L1 = list_checks(A, "alice")
A.patch(B + f"/api/lists/{L1}", json={"org_id": ORG})
r = A.patch(B + f"/api/lists/{L1}", json={"org_id": None, "view": "kanban", "_prev": {"org_id": None, "view": "list"}})
check(r.ok and [c["field"] for c in r.json().get("conflicts", [])] == ["org_id"], f"stale org_id reported: {r.text}")
x = lst(A, L1)
check(x["org_id"] == ORG and x["view"] == "kanban", f"the list stays in the organisation, the view is written: {x['org_id']} {x['view']}")

# ---- organisation members / admins as operations
check(A.patch(B + f"/api/admin/orgs/{ORG}", json={"members_add": [BOB]}).ok, "bob joins (e.g. invitation)")
o = org(ORG)  # the admin dialog opened before bob joined would have members [alice]
r = A.patch(B + f"/api/admin/orgs/{ORG}", json={"members_add": [CAROL], "members_remove": [], "admins_add": [], "admins_remove": []})
o = org(ORG)
check(r.ok and {ALICE, BOB, CAROL} <= set(o["members"]), f"members_add keeps who joined meanwhile: {o['members']}")
check(A.patch(B + f"/api/admin/orgs/{ORG}", json={"admins_add": [BOB]}).ok, "bob becomes admin")
r = A.patch(B + f"/api/admin/orgs/{ORG}", json={"members": [ALICE, CAROL, DAVE], "admins": [ALICE],
                                               "_prev": {"members": [ALICE, CAROL], "admins": [ALICE]}})
o = org(ORG)
check(r.ok and {ALICE, BOB, CAROL, DAVE} <= set(o["members"]) and BOB in o["admins"], f"sets with _prev = only the difference: {o}")
r = A.patch(B + f"/api/admin/orgs/{ORG}", json={"members_remove": [DAVE], "admins_remove": [BOB]})
o = org(ORG)
check(r.ok and DAVE not in o["members"] and BOB in o["members"] and BOB not in o["admins"], f"remove ops: {o}")
r = A.patch(B + f"/api/admin/orgs/{ORG}", json={"members": [ALICE, BOB], "admins": [ALICE]})  # 2.270.0 (#3019): old format still replaces
o = org(ORG)
check(r.ok and set(o["members"]) == {ALICE, BOB}, f"old set format still accepted: {o['members']}")
check(A.patch(B + f"/api/admin/orgs/{ORG}", json={"members_add": ["x"]}).status_code == 400, "bad ids -> 400")

# ---- user dialog: organisations with _prev
A.patch(B + f"/api/users/{CAROL}", json={"orgs": [ORG2]})  # meanwhile: carol into Beta (the dialog showed no organisation)
r = A.patch(B + f"/api/users/{CAROL}", json={"orgs": [ORG], "_prev": {"orgs": []}})
u = next(x for x in A.get(B + "/api/users?all=1").json()["users"] if x["id"] == CAROL)
check(r.ok and set(u["orgs"]) == {ORG, ORG2}, f"user orgs with _prev: Beta added meanwhile stays: {u['orgs']}")
r = A.patch(B + f"/api/users/{CAROL}", json={"orgs": [ORG2], "_prev": {"orgs": [ORG, ORG2]}})
u = next(x for x in A.get(B + "/api/users?all=1").json()["users"] if x["id"] == CAROL)
check(r.ok and u["orgs"] == [ORG2], f"user orgs with _prev: removed only Alpha: {u['orgs']}")

# ---- project description
TOK = A.post(B + "/api/me/tokens", json={"name": "t2270", "scopes": ["read", "write"]}).json().get("token")
desc_checks(A, "alice", TOK)

# ---- freelancer-matrix: lists (a person without an organisation: own project list, own description)
FID, Fr = freelancer(B, A)
list_checks(Fr, "frida")
desc_checks(Fr, "frida")

sys.exit(kt.done("p2270_a_conflict"))
