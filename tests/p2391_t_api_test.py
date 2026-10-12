#!/usr/bin/env python3
"""2.39.1 API tests (agent T: lists like a table), own container (start.sh).
 - #1217: custom fields in plain lists (kind list): create, values on create / change, the search finds a text value,
   columns f:<id>; a field of another list stays unknown (400); time tracking and dependencies stay project-only (409)
 - #1327: owner and list admins define fields (web and v1), edit members 403, viewers cannot set values (403)
 - #1293: creating a field or showing it as a column via the API (personal token, agent token, web) switches the module
   "fields" on for the list's OWNER (never for the caller, nothing else changes, never off); modules_on in the answer
   (["fields"] once, [] afterwards; PATCH columns without f: keys: no modules_on), the OpenAPI document says so
usage: p2391_t_api_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
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


def feats(s):
    return [x for x in (s.get(B + "/api/state").json()["settings"].get("features") or "").split(",") if x]


def fields_off(s):
    s.patch(B + "/api/settings", json={"features": ",".join(f for f in feats(s) if f != "fields")})


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["agents", "comments", "time", "deps"]})
A.patch(B + "/api/settings", json={"lang": "en"})
USERS = {}
for n in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": n, "display_name": n.title(), "password": "password123", "email": f"{n}@example.com"})
    assert r.ok, r.text
    USERS[n] = r.json()["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
r = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "write", "structure", "tasks:write"]})
assert r.ok, r.text
TK = {"Authorization": "Bearer " + r.json()["token"]}

# ================================================================== #1217: custom fields in a plain list
fields_off(A)
before = set(feats(A))
L = A.post(B + "/api/lists", json={"name": "Receipts"}).json()["id"]
r = A.post(B + f"/api/lists/{L}/fields", json={"name": "Amount", "type": "number", "options": {"unit": "EUR"}})
check(r.ok and r.json().get("list_id") == L, f"#1217: a plain list gets a custom field: {r.status_code} {r.text[:160]}")
FA = r.json().get("id")
check(r.json().get("modules_on") == ["fields"], f"#1293 web: the owner's module switched on: {r.json().get('modules_on')}")
after = set(feats(A))
check(after == before | {"fields"}, f"#1293: only 'fields' added, nothing else changed: {sorted(before)} -> {sorted(after)}")
r = A.post(B + f"/api/lists/{L}/fields", json={"name": "Note", "type": "text"})
check(r.ok and r.json().get("modules_on") == [], f"#1293: module already on: modules_on []: {r.text[:120]}")
FN = r.json().get("id")
FS = A.post(B + f"/api/lists/{L}/fields", json={"name": "State", "type": "select",
                                              "options": {"options": [{"name": "Open", "color": "#e5484d"}, {"name": "Paid", "color": "#30a46c"}]}}).json()
OPT = {o["name"]: o["id"] for o in FS["options"]["options"]}
r = A.post(B + "/api/tasks", json={"title": "Pharmacy", "list_id": L, "fields": {str(FA): "12.5", str(FN): "zebra-receipt"}})
check(r.ok and r.json()["fields"].get(str(FA)) in ("12.5",) and r.json()["fields"].get(str(FN)) == "zebra-receipt", f"#1217: values on create in a plain list: {r.text[:160]}")
T1 = r.json()["id"]
r = A.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FS["id"]): OPT["Paid"]}})
check(r.ok and r.json()["fields"].get(str(FS["id"])) == OPT["Paid"], f"#1217: a choice value in a plain list: {r.text[:160]}")
r = requests.get(V + "/search", headers=TK, params={"q": "zebra-receipt"})
check(r.ok and [t["id"] for t in r.json()["data"]] == [T1], f"#1217: the search finds the text field value: {r.text[:160]}")
r = requests.get(V + f"/tasks/{T1}", headers=TK)
check(r.ok and r.json().get("fields", {}).get(str(FA)) == "12.5", f"#1217: v1 task carries the values: {r.text[:160]}")
r = A.patch(B + f"/api/lists/{L}", json={"columns": ["due", f"f:{FA}", f"f:{FS['id']}"]})
check(r.ok and r.json().get("modules_on") == [], f"web PATCH field columns, module on already: modules_on []: {r.text[:120]}")
P = A.post(B + "/api/lists", json={"name": "Project", "kind": "project"}).json()["id"]
FP = A.post(B + f"/api/lists/{P}/fields", json={"name": "Budget", "type": "number"}).json()["id"]
check(A.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FP): "3"}}).status_code == 400, "#1217: a field of another list: 400")
check(A.post(B + "/api/time/start", json={"task_id": T1}).status_code == 409, "#1217: time tracking stays project-only (409)")
TP = A.post(B + "/api/tasks", json={"title": "p", "list_id": P}).json()["id"]
check(A.post(B + "/api/deps", json={"task_id": T1, "blocker_id": TP}).status_code == 409, "#1217: dependencies stay project-only (409)")
# a template of the plain list keeps its fields
r = A.post(B + "/api/templates", json={"list_id": L})
check(r.ok and any(f.get("name") == "Amount" for f in (r.json().get("data") or {}).get("fields") or []), f"#1217: a list template keeps the fields of a plain list: {r.text[:200]}")

# ================================================================== #1327: who defines fields, who sets values
for who, role in (("bob", "admin"), ("carol", "edit"), ("dave", "view")):
    check(A.put(B + f"/api/lists/{L}/members", json={"user_id": USERS[who], "role": role}).ok, f"setup: {who} {role}")
r = Bo.post(B + f"/api/lists/{L}/fields", json={"name": "Checked", "type": "checkbox"})
check(r.ok, f"#1327: a list admin defines a field: {r.status_code} {r.text[:120]}")
FC = r.json().get("id")
check(Bo.patch(B + f"/api/fields/{FC}", json={"name": "Refunded"}).ok, "#1327: a list admin renames a field")
check(Ca.post(B + f"/api/lists/{L}/fields", json={"name": "X", "type": "text"}).status_code == 403, "#1327: an edit member cannot define fields (403)")
check(Ca.patch(B + f"/api/fields/{FC}", json={"name": "X"}).status_code == 403, "#1327: an edit member cannot rename (403)")
check(Ca.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FC): "1"}}).ok, "#1327: an edit member sets a value")
check(Da.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FC): None}}).status_code == 403, "#1327: a viewer cannot set values (403)")
check(Da.post(B + f"/api/lists/{L}/fields", json={"name": "X", "type": "text"}).status_code in (403, 404), "#1327: a viewer cannot define fields")
r = Bo.delete(B + f"/api/fields/{FC}")
check(r.ok and r.json().get("values") == 1, f"#1327: a list admin deletes a field with its values: {r.text[:120]}")

# ================================================================== #1293: personal token and agent switch the OWNER's module on
fields_off(A)
fields_off(Bo)
bob_before = set(feats(Bo))
L2 = A.post(B + "/api/lists", json={"name": "AXA"}).json()["id"]
r = requests.post(V + f"/lists/{L2}/fields", headers=TK, json={"name": "Refunded", "type": "checkbox"})
check(r.status_code == 201 and r.json().get("modules_on") == ["fields"], f"#1293 token: field created, modules_on: {r.status_code} {r.text[:160]}")
F2 = r.json().get("id")
check("fields" in feats(A), "#1293 token: the owner's module is on")
fields_off(A)
r = requests.patch(V + f"/lists/{L2}", headers=TK, json={"columns": ["due", f"f:{F2}"]})
check(r.ok and r.json().get("modules_on") == ["fields"] and r.json().get("columns") == ["due", f"f:{F2}"], f"#1293 token: columns with a field switch it on: {r.text[:200]}")
check("fields" in feats(A), "#1293 token: on again after the columns")
r = requests.patch(V + f"/lists/{L2}", headers=TK, json={"columns": ["due"]})
check(r.ok and "modules_on" not in r.json(), f"#1293: columns without fields: no modules_on: {r.text[:200]}")
r = requests.patch(V + f"/lists/{L2}", headers=TK, json={"columns": ["due", f"f:{F2}"]})
check(r.ok and r.json().get("modules_on") == [], f"#1293: already on: modules_on []: {r.text[:200]}")
# an agent (edit member of Alice's list) cannot define fields; Bob (list admin, module off) creates one: Alice's module
# goes on (the owner), Bob's stays off
fields_off(A)
L3 = A.post(B + "/api/lists", json={"name": "Agent setup"}).json()["id"]
check(A.put(B + f"/api/lists/{L3}/members", json={"user_id": CL, "role": "edit"}).ok, "setup: agent as edit member")
check(A.put(B + f"/api/lists/{L3}/members", json={"user_id": USERS["bob"], "role": "admin"}).ok, "setup: bob as list admin")
check(requests.post(V + f"/lists/{L3}/fields", headers=CLH, json={"name": "Stage", "type": "text"}).status_code == 403, "agent as edit member: 403")
r = Bo.post(B + f"/api/lists/{L3}/fields", json={"name": "Stage", "type": "text"})
check(r.ok and r.json().get("modules_on") == ["fields"], f"#1293: a list admin's field switches the owner's module on: {r.text[:160]}")
check("fields" in feats(A) and set(feats(Bo)) == bob_before, "#1293: the owner's module on, the admin's untouched")
# nothing is ever switched off: a list without field columns leaves the module as it is
r = requests.patch(V + f"/lists/{L2}", headers=TK, json={"columns": None})
check(r.ok and "fields" in feats(A), "#1293: columns null switch nothing off")
# the OpenAPI document names it
spec = requests.get(V + "/openapi.json", headers=TK).json()
txt = str(spec)
check("#1293" in txt and "modules_on" in str(spec.get("components", {}).get("schemas", {}).get("Field", {})), "#1293: OpenAPI: Field.modules_on and the columns note")
check("modules_on" in str(spec.get("components", {}).get("schemas", {}).get("List", {})), "#1293: OpenAPI: List.modules_on (PATCH answer)")

print(f"p2391_t_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
time.sleep(0.1)
sys.exit(1 if FAILS else 0)
