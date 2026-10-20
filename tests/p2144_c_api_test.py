#!/usr/bin/env python3
"""2.144.0 API tests, part C (#2414): a list grouped by a custom field, sort_mode and group_field over /api/v1. Own container
(start.sh). Invented names only, addresses @example.com.
 - the app's PATCH /api/lists/<id> {group_field}: 'cf:<id>' or the id of a text / select field of this list; '' / null = off;
   a number / date field, a field of another list, garbage = 400; a member (edit) or viewer = 403; /api/state carries it
 - the sections stay untouched while a grouping is on
 - 2.144.0 A2: deleting the grouping field ends the grouping (group_field back to '')
 - PATCH /api/v1/lists/<id> {sort_mode, group_field} with a personal token (scope structure); GET carries both; a wrong
   sort_mode = 400; a read-only token = 403
 - a person without an organisation (freelancer-matrix: lists): groups and sorts the own private list in the app and over
   /api/v1
usage: p2144_c_api_test.py <datadir>      (a fresh container; P2144C_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
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


def token(s, scopes):
    r = s.post(B + "/api/me/tokens", json={"name": "script", "scopes": scopes})
    assert r.ok, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def lst(s, lid):
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), {})


if not os.environ.get("P2144C_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments", "fields"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {"alice": 1}
for u in ("bob", "vic"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Vi = sess("bob"), sess("vic")
for s in (A, Bo, Vi):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "comments,fields"}).ok

# ================================================================ the list and its fields
L = A.post(B + "/api/lists", json={"name": "Releases", "kind": "project", "org_id": ORG}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Other", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["bob"], "role": "edit"}).ok
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["vic"], "role": "view"}).ok
sec = A.post(B + "/api/sections", json={"list_id": L, "name": "Phase one"}).json()["id"]
fsel = A.post(B + f"/api/lists/{L}/fields", json={"name": "Package", "type": "select", "options": {"options": [
    {"id": "p1", "name": "2.10", "color": "blue"}, {"id": "p2", "name": "2.9", "color": "green"}]}}).json()["id"]
ftxt = A.post(B + f"/api/lists/{L}/fields", json={"name": "Client", "type": "text"}).json()["id"]
fnum = A.post(B + f"/api/lists/{L}/fields", json={"name": "Hours", "type": "number"}).json()["id"]
fother = A.post(B + f"/api/lists/{L2}/fields", json={"name": "Elsewhere", "type": "text"}).json()["id"]
check(all(isinstance(x, int) for x in (fsel, ftxt, fnum, fother)), "fields created")
T1 = A.post(B + "/api/tasks", json={"list_id": L, "title": "Build A", "section_id": sec, "fields": {str(fsel): "p1"}}).json()["id"]

check(lst(A, L).get("group_field") == "", "a new list: no grouping")
r = A.patch(B + f"/api/lists/{L}", json={"group_field": f"cf:{fsel}"})
check(r.ok, f"owner groups by a select field {r.status_code} {r.text[:200]}")
check(lst(A, L).get("group_field") == f"cf:{fsel}", "state carries group_field")
check(lst(Bo, L).get("group_field") == f"cf:{fsel}", "the same for every member")
r = A.patch(B + f"/api/lists/{L}", json={"group_field": ftxt})
check(r.ok and lst(A, L).get("group_field") == f"cf:{ftxt}", "the plain id of a text field is taken as cf:<id>")
for bad, what in ((f"cf:{fnum}", "a number field"), (f"cf:{fother}", "a field of another list"), ("package", "garbage"),
                  (True, "a boolean"), ("cf:999999", "an unknown field")):
    check(A.patch(B + f"/api/lists/{L}", json={"group_field": bad}).status_code == 400, f"400 for {what}")
check(lst(A, L).get("group_field") == f"cf:{ftxt}", "a refused value changes nothing")
check(Bo.patch(B + f"/api/lists/{L}", json={"group_field": ""}).status_code == 403, "a member (edit) may not change it")
check(Vi.patch(B + f"/api/lists/{L}", json={"group_field": ""}).status_code == 403, "a viewer may not change it")
secs = [x for x in A.get(B + "/api/state").json()["sections"] if x["list_id"] == L]
check([x["name"] for x in secs] == ["Phase one"], f"the sections stay {secs}")
t = next(x for x in A.get(B + "/api/state").json()["tasks"] if x["id"] == T1)
check(t.get("section_id") == sec, "the task keeps its section")
r = A.patch(B + f"/api/lists/{L}", json={"group_field": None})
check(r.ok and lst(A, L).get("group_field") == "", "null = by sections again")
# 2.144.0 A2 (#2414): a deleted grouping field ends the grouping
fgone = A.post(B + f"/api/lists/{L}/fields", json={"name": "Temporary", "type": "text"}).json()["id"]
assert A.patch(B + f"/api/lists/{L}", json={"group_field": f"cf:{fgone}"}).ok
check(A.delete(B + f"/api/fields/{fgone}").ok and lst(A, L).get("group_field") == "", "A2: deleting the grouping field ends the grouping")

# ================================================================ /api/v1: sort_mode and group_field
TK = token(A, ["read", "structure"])
r = requests.patch(B + f"/api/v1/lists/{L}", headers=TK, json={"sort_mode": "title", "group_field": f"cf:{fsel}"})
check(r.ok, f"v1 PATCH sort_mode + group_field {r.status_code} {r.text[:200]}")
j = r.json() if r.ok else {}
check(j.get("sort_mode") == "title" and j.get("group_field") == f"cf:{fsel}", f"v1 answer carries both {j.get('sort_mode')} {j.get('group_field')}")
j = requests.get(B + f"/api/v1/lists/{L}", headers=TK).json()
check(j.get("sort_mode") == "title" and j.get("group_field") == f"cf:{fsel}", "v1 GET carries both")
check(lst(Bo, L).get("sort_mode") == "title", "the app sees the sort set over the API")
check(requests.patch(B + f"/api/v1/lists/{L}", headers=TK, json={"sort_mode": "sideways"}).status_code == 400, "v1: a wrong sort_mode = 400")
check(requests.patch(B + f"/api/v1/lists/{L}", headers=TK, json={"group_field": f"cf:{fnum}"}).status_code == 400, "v1: a number field = 400")
r = requests.patch(B + f"/api/v1/lists/{L}", headers=TK, json={"sort_mode": "", "group_field": ""})
check(r.ok and r.json().get("sort_mode") == "" and r.json().get("group_field") == "", "v1: both back to the default")
TR = token(A, ["read"])
check(requests.patch(B + f"/api/v1/lists/{L}", headers=TR, json={"group_field": ""}).status_code == 403, "v1: a read-only token = 403")
TB = token(Bo, ["read", "structure"])
check(requests.patch(B + f"/api/v1/lists/{L}", headers=TB, json={"sort_mode": "date"}).status_code == 403, "v1: a member (edit) = 403")
spec = requests.get(B + "/api/v1/openapi.json").json()
props = spec.get("components", {}).get("schemas", {}).get("ListPatch", {}).get("properties", {})
check("sort_mode" in props and "group_field" in props, "OpenAPI ListPatch names sort_mode and group_field")

# ================================================================ a person without an organisation (freelancer-matrix: lists)
FID, Fl = freelancer(B, A)
FL = Fl.post(B + "/api/lists", json={"name": "Own work"}).json()["id"]
ff = Fl.post(B + f"/api/lists/{FL}/fields", json={"name": "Customer", "type": "text"})
check(ff.ok, f"freelancer: field created {ff.status_code}")
ff = ff.json().get("id") if ff.ok else 0
check(Fl.patch(B + f"/api/lists/{FL}", json={"group_field": f"cf:{ff}"}).ok and lst(Fl, FL).get("group_field") == f"cf:{ff}",
      "freelancer: groups the own list in the app")
TF = token(Fl, ["read", "structure"])
r = requests.patch(B + f"/api/v1/lists/{FL}", headers=TF, json={"sort_mode": "prio", "group_field": ""})
check(r.ok and r.json().get("sort_mode") == "prio" and r.json().get("group_field") == "", f"freelancer: v1 sort + grouping {r.status_code}")
check(Fl.patch(B + f"/api/lists/{L}", json={"group_field": ""}).status_code in (403, 404), "freelancer: an organisation's list is refused")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
