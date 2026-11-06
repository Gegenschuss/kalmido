#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.609.0 (#3373): the ticket model of an organisation, own container (start.sh). Invented names only.
 - (a) fields of an organisation: only its admins add / change / delete them (a member 403, agents and API tokens 403), a
   formula field and a taken key are refused; a project switches a field on (a linked custom field) and off (the field stays,
   unlinked); name and options of a linked field change only through the organisation (409 in the project) and reach every
   linked project (a removed option leaves its values); the API lists the key, GET /api/v1/tasks?fkey_<key>= evaluates over
   projects; deleting the field keeps the projects' fields
 - (b) required fields: creating a task without a value is refused with the field's name (app, API v1), with a value it works;
   a subtask and a task made before stay as they are (completing works), clearing the value is refused; a checkbox / formula
   field cannot be required; the API's list object names required
 - (c) labels of an organisation: its admins manage them, every member gets them in the app state, using one in a project makes
   the linked project tag (colour of the label), renaming the label renames it, the project cannot rename it (409), personal
   tags stay private and unchanged, deleting the label keeps the project tag
 - (d) templates of an organisation: its admin saves one for the organisation, members see and use it (a list template makes
   the project in the organisation) but cannot change or delete it, a member cannot save one for it, back to private = gone
   for the members
 - tenant-matrix: orgschema. The fields, labels and templates of another organisation: never listed, 404 to use / change
 - freelancer-matrix: orgschema. A person without an organisation: own field templates (linked into her lists, the key filter),
   required fields, own templates; no organisation space (404), no organisation labels
usage: p2609_c_schema_api_test.py <datadir>"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
import kt  # noqa: E402
from kt import check, B, H, done, sess  # noqa: E402

V = B + "/api/v1"

kt.fresh()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": kt.PASSWORD}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u == "bob" else [], "username": u, "display_name": u.title(),
                                       "password": kt.PASSWORD, "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["carl"]})
assert r.status_code in (200, 201), r.text
ORG2 = r.json().get("id") or r.json().get("org", {}).get("id")
Bo, Ca = sess("bob"), sess("carl")
FEAT = "collab,comments,fields"
for s in (A, Bo, Ca):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT}).ok
FU, F = freelancer(B, A, "frida")


def st(s):
    return s.get(B + "/api/state").json()


def mklist(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, "kind": "project", **({"org_id": org} if org else {})})
    assert r.ok, r.text
    return r.json()["id"]


def task(s, lid, title, **kw):
    return s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})


def tok(s, scopes=("read", "tasks:write")):
    return {"Authorization": "Bearer " + s.post(B + "/api/me/tokens", json={"name": "t", "scopes": list(scopes)}).json()["token"], **H}


def fld(s, fid):
    return next((f for f in st(s)["fields"] if f["id"] == fid), None)


L1 = mklist(A, "Support", ORG)
L2 = mklist(A, "Sales", ORG)
for lid in (L1, L2):
    check(A.put(B + f"/api/lists/{lid}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob edits the projects")
LC = mklist(Ca, "Beta work", ORG2)
check(next(x for x in st(A)["me"]["workspaces"] if x["id"] == ORG)["role"] == "admin", "setup: alice administers Alpha")

# ================================================================== (a) fields of the organisation
SEL = {"options": [{"id": "acme", "name": "Acme"}, {"id": "glob", "name": "Globex"}, {"id": "init", "name": "Initech"}]}
r = Bo.post(B + "/api/org-fields", json={"space": f"org:{ORG}", "name": "Client", "type": "select", "options": SEL})
check(r.status_code == 403, f"(a) a member does not add fields of the organisation {r.status_code}")
r = A.post(B + "/api/org-fields", json={"space": f"org:{ORG}", "name": "Client", "type": "select", "options": SEL})
check(r.ok and r.json()["key"] == "client" and r.json()["org_id"] == ORG, f"(a) the admin adds one, key from the name {r.text[:200]}")
OF = r.json()["id"]
r = A.post(B + "/api/org-fields", json={"space": f"org:{ORG}", "name": "Client", "type": "text"})
check(r.status_code == 400 and "client" in r.text, f"(a) a taken key is refused {r.status_code}")
r = A.post(B + "/api/org-fields", json={"space": f"org:{ORG}", "name": "Sum", "type": "formula", "formula": "1+1"})
check(r.status_code == 400, f"(a) a formula field is not shared {r.status_code}")
r = A.post(B + "/api/org-fields", json={"space": f"org:{ORG}", "name": "Hours", "type": "number", "key": "Bad Key"})
check(r.status_code == 400, f"(a) a key with spaces is refused {r.status_code}")
r = Bo.get(B + "/api/org-fields")
check(r.ok and [f["id"] for f in r.json()["fields"]] == [OF] and r.json()["fields"][0]["can_edit"] is False, f"(a) a member reads them {r.text[:200]}")
r = requests.get(B + "/api/org-fields", headers=tok(A))
check(r.status_code in (401, 403), f"(a) an API token does not manage them {r.status_code}")

r = A.get(B + f"/api/lists/{L1}/org-fields")
check(r.ok and r.json()["fields"][0]["field_id"] is None, f"(a) the project lists it, switched off {r.text[:200]}")
r = Bo.put(B + f"/api/lists/{L1}/org-fields/{OF}", json={"on": True})
check(r.status_code == 403, f"(a) a member who does not manage the project cannot switch it on {r.status_code}")
r = A.put(B + f"/api/lists/{L1}/org-fields/{OF}", json={"on": True})
F1 = r.json().get("field_id")
check(r.ok and F1, f"(a) switched on: a linked field {r.text[:200]}")
F2 = A.put(B + f"/api/lists/{L2}/org-fields/{OF}", json={"on": True}).json().get("field_id")
check(F2 and F2 != F1, "(a) the second project gets its own linked field")
check((fld(A, F1) or {}).get("org_field_id") == OF, "(a) the app state names the link")
check(A.put(B + f"/api/lists/{L1}/org-fields/{OF}", json={"on": True}).json().get("field_id") == F1, "(a) switching on twice: the same field")
T1 = task(A, L1, "Printer jams", fields={str(F1): "init"}).json()["id"]
T2 = task(A, L2, "Offer for Acme", fields={str(F2): "acme"}).json()["id"]
T3 = task(A, L2, "Offer for Initech", fields={str(F2): "init"}).json()["id"]
r = A.patch(B + f"/api/fields/{F1}", json={"name": "Customer"})
check(r.status_code == 409, f"(a) the project cannot rename a linked field {r.status_code}")
r = A.patch(B + f"/api/fields/{F1}", json={"pinned": True})
check(r.ok and r.json()["pinned"] == 1, f"(a) pinned stays the project's {r.text[:200]}")
r = A.patch(B + f"/api/org-fields/{OF}", json={"name": "Customer", "options": {"options": SEL["options"][:2]}})
check(r.ok and r.json()["lists"] == 2, f"(a) the admin changes the field {r.text[:200]}")
check(fld(A, F1)["name"] == "Customer" and fld(A, F2)["name"] == "Customer", "(a) the change reaches both projects")
check(len(fld(A, F2)["options"]["options"]) == 2, "(a) the options too")
tk = {t["id"]: t for t in st(A)["tasks"]}
check(not tk[T1]["fields"].get(str(F1)) and not tk[T3]["fields"].get(str(F2)) and tk[T2]["fields"].get(str(F2)) == "acme",
      f"(a) a removed option leaves its values in every project {tk[T1]['fields']} {tk[T3]['fields']} {tk[T2]['fields']}")
check(Bo.patch(B + f"/api/org-fields/{OF}", json={"name": "X"}).status_code == 403, "(a) a member cannot change it")
PA = tok(A)
r = requests.get(V + f"/lists/{L1}", headers=PA)
fl = next((f for f in r.json().get("fields", []) if f["id"] == F1), {})
check(r.ok and fl.get("key") == "client" and fl.get("required") is False, f"(a) the API names the key {r.text[:300]}")
r = requests.get(V + "/tasks", headers=PA, params={"fkey_client": "Acme"})
check(r.ok and [t["id"] for t in r.json()["data"]] == [T2], f"(a) fkey_client evaluates over projects {r.text[:300]}")
task(A, L1, "Acme call", fields={str(F1): "acme"})
r = requests.get(V + "/tasks", headers=PA, params={"fkey_client": "acme"})
check(r.ok and len(r.json()["data"]) == 2 and {t["list_id"] for t in r.json()["data"]} == {L1, L2}, f"(a) both projects {r.text[:300]}")
r = requests.get(V + "/tasks", headers=PA, params={"fkey_nothing": "x"})
check(r.ok and r.json()["data"] == [], f"(a) an unknown key: no task {r.text[:200]}")
r = A.put(B + f"/api/lists/{L2}/org-fields/{OF}", json={"on": False})
check(r.ok and fld(A, F2) and fld(A, F2)["org_field_id"] is None, f"(a) switched off: the field stays, unlinked {r.text[:200]}")

# tenant-matrix: orgschema. Another organisation's fields
r = Ca.get(B + "/api/org-fields")
check(r.ok and r.json()["fields"] == [], f"(a) another organisation's admin lists none {r.text[:200]}")
check(Ca.put(B + f"/api/lists/{LC}/org-fields/{OF}", json={"on": True}).status_code == 404, "(a) a field of Alpha into a project of Beta: 404")
check(Ca.patch(B + f"/api/org-fields/{OF}", json={"name": "Mine"}).status_code == 404, "(a) changing Alpha's field from Beta: 404")
check(Ca.delete(B + f"/api/org-fields/{OF}").status_code == 404, "(a) deleting it from Beta: 404")
check(Ca.post(B + "/api/org-fields", json={"space": f"org:{ORG}", "name": "Spy", "type": "text"}).status_code == 404, "(a) into Alpha from Beta: 404")

# ================================================================== (b) required fields
OLD = task(A, L1, "Made before").json()["id"]
r = A.patch(B + f"/api/fields/{F1}", json={"required": True})
check(r.ok and r.json()["required"] is True, f"(b) the project makes the field required {r.text[:200]}")
r = task(A, L1, "No customer")
check(r.status_code == 400 and "Customer" in r.text, f"(b) a new task without it is refused, naming the field {r.status_code} {r.text[:200]}")
check(not any(t["title"] == "No customer" for t in st(A)["tasks"]), "(b) nothing was stored")
r = task(A, L1, "With customer", fields={str(F1): "glob"})
check(r.ok, f"(b) with a value it is created {r.text[:200]}")
r = requests.post(V + "/tasks", headers=PA, json={"title": "API without", "list_id": L1})
check(r.status_code == 400 and "Customer" in r.text, f"(b) API v1 (and MCP through it): 400 naming the field {r.status_code} {r.text[:200]}")
r = requests.post(V + "/tasks", headers=PA, json={"title": "API with", "list_id": L1, "fields": {str(F1): "acme"}})
check(r.status_code in (200, 201), f"(b) API v1 with the value {r.status_code} {r.text[:200]}")
r = requests.get(V + f"/lists/{L1}", headers=PA)
check(next(f for f in r.json()["fields"] if f["id"] == F1)["required"] is True, "(b) the list object names required for agents")
check(task(A, L1, "Sub step", parent_id=OLD).ok, "(b) a subtask needs no value")
check(A.patch(B + f"/api/tasks/{OLD}", json={"title": "Made before, renamed"}).ok, "(b) a task made before is changed as before")
check(A.patch(B + f"/api/tasks/{OLD}", json={"status": 2}).ok, "(b) completing needs no value")
r = A.patch(B + f"/api/tasks/{T1}", json={"fields": {str(F1): None}})
check(r.status_code == 400 and "Customer" in r.text, f"(b) clearing a required value is refused {r.status_code}")
CB = A.post(B + f"/api/lists/{L1}/fields", json={"name": "Checked", "type": "checkbox"}).json()["id"]
check(A.patch(B + f"/api/fields/{CB}", json={"required": True}).status_code == 400, "(b) a checkbox cannot be required")
check(A.post(B + f"/api/lists/{L1}/fields", json={"name": "Sum", "type": "formula", "formula": "1", "required": True}).status_code == 400,
      "(b) a formula cannot be required")
check(A.patch(B + f"/api/fields/{F1}", json={"required": False}).ok and task(A, L1, "Free again").ok, "(b) switched off: free again")

# ================================================================== (c) labels of the organisation
r = Bo.post(B + "/api/org-labels", json={"org_id": ORG, "name": "Urgent"})
check(r.status_code == 403, f"(c) a member does not add labels {r.status_code}")
r = A.post(B + "/api/org-labels", json={"org_id": ORG, "name": "Urgent", "color": "#f87171"})
check(r.status_code == 201, f"(c) the admin adds one {r.status_code} {r.text[:200]}")
LB = r.json()["id"]
check(A.post(B + "/api/org-labels", json={"org_id": ORG, "name": "urgent"}).status_code == 409, "(c) the same name twice: 409")
check(any(x["id"] == LB for x in st(Bo).get("org_labels", [])), "(c) a member gets it in the app state")
check(st(Ca).get("org_labels") == [], "(c) another organisation's admin does not")
r = Bo.patch(B + f"/api/tasks/{T1}", json={"ltags": ["Urgent"], "tags": ["mine"]})
check(r.ok, f"(c) a member puts the label on a task {r.text[:200]}")
lt = next(x for x in st(Bo)["lists"] if x["id"] == L1)["tags"]
check(any(x["name"] == "Urgent" and x["org_tag_id"] == LB and x["color"] == "#f87171" for x in lt), f"(c) a linked project tag in its colour {lt}")
tb = next(t for t in st(Bo)["tasks"] if t["id"] == T1)
check(tb["ltags"] == ["Urgent"] and tb["tags"] == ["mine"], f"(c) the label and the personal tag apart {tb['ltags']} {tb['tags']}")
check(next(t for t in st(A)["tasks"] if t["id"] == T1)["tags"] == [], "(c) the personal tag stays private")
LT = next(x["id"] for x in lt if x["name"] == "Urgent")
check(Bo.patch(B + f"/api/list-tags/{LT}", json={"name": "Later"}).status_code == 409, "(c) the project cannot rename the label")
r = A.patch(B + f"/api/org-labels/{LB}", json={"name": "Hot", "color": "#c084fc"})
check(r.ok, f"(c) the admin renames it {r.text[:200]}")
lt = next(x for x in st(Bo)["lists"] if x["id"] == L1)["tags"]
check(any(x["id"] == LT and x["name"] == "Hot" and x["color"] == "#c084fc" for x in lt), f"(c) renamed in the project {lt}")
check(next(t for t in st(Bo)["tasks"] if t["id"] == T1)["ltags"] == ["Hot"], "(c) and on the task")
# tenant-matrix: orgschema. Another organisation's labels
check(Ca.patch(B + f"/api/org-labels/{LB}", json={"name": "Mine"}).status_code == 404, "(c) changing Alpha's label from Beta: 404")
check(Ca.post(B + "/api/org-labels", json={"org_id": ORG, "name": "Spy"}).status_code == 404, "(c) a label into Alpha from Beta: 404")
TC = task(Ca, LC, "Beta task").json()["id"]
check(Ca.patch(B + f"/api/tasks/{TC}", json={"ltags": ["Hot"]}).ok, "setup: a tag of the same name in Beta")
lc = next(x for x in st(Ca)["lists"] if x["id"] == LC)["tags"]
check(all(x["org_tag_id"] is None for x in lc), f"(c) it is no label of Alpha in Beta's project {lc}")
r = A.delete(B + f"/api/org-labels/{LB}")
check(r.ok and r.json()["unlinked"] == 1, f"(c) deleted {r.text[:200]}")
lt = next(x for x in st(Bo)["lists"] if x["id"] == L1)["tags"]
check(any(x["id"] == LT and x["org_tag_id"] is None for x in lt), "(c) the project keeps it as its own tag")

# ================================================================== (d) templates of the organisation
r = Bo.post(B + "/api/templates", json={"task_id": T2, "space": f"org:{ORG}"})
check(r.status_code == 403, f"(d) a member does not save one for the organisation {r.status_code}")
r = A.post(B + "/api/templates", json={"task_id": T2, "name": "Offer", "space": f"org:{ORG}"})
check(r.ok and r.json()["org_id"] == ORG, f"(d) the admin saves one for the organisation {r.text[:200]}")
TP = r.json()["id"]
r = Bo.get(B + "/api/templates")
tp = next((x for x in r.json()["templates"] if x["id"] == TP), None)
check(tp and tp["can_edit"] is False and tp["mine"] is False, f"(d) a member sees it, read only {tp}")
check(any(x["id"] == TP for x in st(Bo)["templates"]), "(d) and finds it under From template (app state)")
r = Bo.post(B + f"/api/templates/{TP}/apply", json={"list_id": L1})
check(r.ok and r.json()["task"]["title"] == "Offer for Acme", f"(d) a member uses it {r.text[:200]}")
check(Bo.patch(B + f"/api/templates/{TP}", json={"name": "Mine"}).status_code == 403, "(d) a member cannot change it")
check(Bo.delete(B + f"/api/templates/{TP}").status_code == 403, "(d) nor delete it")
# 2.609.0 (#3373): the template trash (2.567.0, #4707): the admin deletes the organisation's template, a member can neither see nor
# bring it back, the admin restores it for the organisation
r = A.delete(B + f"/api/templates/{TP}")
check(r.ok and r.json().get("trash"), f"(d) the admin deletes it into the trash {r.text[:200]}")
check(not any(x["id"] == TP for x in Bo.get(B + "/api/templates").json()["templates"]), "(d) deleted: gone for the members")
check(Bo.post(B + f"/api/templates/{TP}/restore").status_code == 404, "(d) a member cannot restore it (404)")
r = A.post(B + f"/api/templates/{TP}/restore")
check(r.ok and r.json().get("org_id") == ORG, f"(d) the admin restores it for the organisation {r.text[:200]}")
check(any(x["id"] == TP for x in Bo.get(B + "/api/templates").json()["templates"]), "(d) restored: the members see it again")
# tenant-matrix: orgschema. Another organisation's templates
check(not any(x["id"] == TP for x in Ca.get(B + "/api/templates").json()["templates"]), "(d) another organisation does not see it")
check(Ca.post(B + f"/api/templates/{TP}/apply", json={"list_id": LC}).status_code == 404, "(d) nor use it (404)")
check(Ca.patch(B + f"/api/templates/{TP}", json={"name": "x"}).status_code == 404, "(d) nor change it (404)")
r = A.post(B + "/api/templates", json={"list_id": L2, "name": "Sales project", "space": f"org:{ORG}"})
check(r.ok and r.json()["org_id"] == ORG, f"(d) a project template for the organisation {r.text[:200]}")
r = Bo.post(B + f"/api/templates/{r.json()['id']}/apply", json={"name": "Sales 2"})
nl = r.json().get("list_id")
check(r.ok and next((x for x in st(Bo)["lists"] if x["id"] == nl), {}).get("org_id") == ORG, f"(d) its project is made in the organisation {r.text[:200]}")
r = A.patch(B + f"/api/templates/{TP}", json={"space": "private"})
check(r.ok and r.json()["org_id"] is None, f"(d) the admin takes it back {r.text[:200]}")
check(Bo.post(B + f"/api/templates/{TP}/apply", json={"list_id": L1}).status_code == 404, "(d) gone for the members")

# ================================================================== freelancer-matrix: orgschema. No organisation
FL = mklist(F, "My clients")
FL2 = mklist(F, "My offers")
check(F.post(B + "/api/org-fields", json={"space": f"org:{ORG}", "name": "X", "type": "text"}).status_code == 404, "P4: no organisation space (404)")
r = F.post(B + "/api/org-fields", json={"name": "Rate", "type": "number"})
check(r.ok and r.json()["space"] == "private" and r.json()["can_edit"], f"P4: an own field template {r.text[:200]}")
FOF = r.json()["id"]
check(A.patch(B + f"/api/org-fields/{FOF}", json={"name": "x"}).status_code == 404, "P4: someone else's own field: 404")
fa = F.put(B + f"/api/lists/{FL}/org-fields/{FOF}", json={"on": True}).json().get("field_id")
fb = F.put(B + f"/api/lists/{FL2}/org-fields/{FOF}", json={"on": True}).json().get("field_id")
check(fa and fb, "P4: linked into both own projects")
check(A.put(B + f"/api/lists/{L1}/org-fields/{FOF}", json={"on": True}).status_code == 404, "P4: not into another person's project")
check(F.patch(B + f"/api/org-fields/{FOF}", json={"name": "Day rate"}).ok and fld(F, fb)["name"] == "Day rate", "P4: the change reaches her projects")
check(F.patch(B + f"/api/fields/{fa}", json={"required": True}).ok, "P4: required")
check(task(F, FL, "No rate").status_code == 400, "P4: a task without the required value is refused")
ft = task(F, FL, "Rate set", fields={str(fa): "800"})
check(ft.ok, f"P4: with the value {ft.text[:200]}")
PF = tok(F)
r = requests.get(V + "/tasks", headers=PF, params={"fkey_rate": "800"})
check(r.ok and [t["id"] for t in r.json()["data"]] == [ft.json()["id"]], f"P4: the key filter {r.text[:200]}")
r = requests.post(V + "/tasks", headers=PF, json={"title": "API no rate", "list_id": FL})
check(r.status_code == 400 and "Day rate" in r.text, f"P4: API v1 400 naming the field {r.status_code}")
check(F.get(B + "/api/org-labels").json()["labels"] == [] and st(F).get("org_labels") == [], "P4: no organisation labels")
check(F.post(B + "/api/org-labels", json={"org_id": ORG, "name": "x"}).status_code == 404, "P4: no label into an organisation")
r = F.post(B + "/api/templates", json={"task_id": ft.json()["id"], "name": "Rate task"})
check(r.ok and r.json()["org_id"] is None and r.json()["can_edit"], f"P4: own templates as before {r.text[:200]}")
check(F.post(B + "/api/templates", json={"task_id": ft.json()["id"], "space": f"org:{ORG}"}).status_code == 404, "P4: no organisation template")
check(F.delete(B + f"/api/org-fields/{FOF}").ok and fld(F, fa) and fld(F, fa)["org_field_id"] is None, "P4: deleting keeps her fields")

# ---- 2.609.0 (#3373): a viewer who is not entitled to the schema sees only the fields linked in the project
OFX = A.post(B + "/api/org-fields", json={"space": f"org:{ORG}", "name": "Internal margin", "type": "text"}).json()["id"]
OFL = A.post(B + "/api/org-fields", json={"space": f"org:{ORG}", "name": "Region", "type": "text"}).json()["id"]
assert A.put(B + f"/api/lists/{L1}/org-fields/{OFL}", json={"on": True}).ok
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "guest"}], "username": "gina", "display_name": "Gina",
                                   "password": kt.PASSWORD, "email": "gina@example.com"})
assert r.ok, r.text
check(A.put(B + f"/api/lists/{L1}/members", json={"user_id": r.json()["id"], "role": "view"}).ok, "setup: a guest of the organisation views Support")
Gi = sess("gina")
Gi.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
ids = [x["id"] for x in Gi.get(B + f"/api/lists/{L1}/org-fields").json().get("fields", [])]
check(OFL in ids and OFX not in ids, f"(a) a guest sees only the linked fields, not the schema: {ids}")
ids = [x["id"] for x in Bo.get(B + f"/api/lists/{L1}/org-fields").json().get("fields", [])]
check(OFL in ids and OFX in ids, f"(a) a member with full access sees the schema: {ids}")
FS = F.post(B + "/api/org-fields", json={"name": "Client discount", "type": "text"}).json()["id"]
FV = F.post(B + "/api/org-fields", json={"name": "Venue", "type": "text"}).json()["id"]
assert F.put(B + f"/api/lists/{FL}/org-fields/{FV}", json={"on": True}).ok
r = A.post(B + "/api/users", json={"orgs": [], "username": "hank", "display_name": "Hank", "password": kt.PASSWORD, "email": "hank@example.com"})
assert r.ok, r.text
F.put(B + f"/api/lists/{FL}/members", json={"email": "hank@example.com", "role": "view"})  # by address: no common directory
Hk = sess("hank")
check(Hk.get(B + f"/api/lists/{FL}/org-fields").ok, "setup: P4 shares a project to view")
Hk.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
ids = [x["id"] for x in Hk.get(B + f"/api/lists/{FL}/org-fields").json().get("fields", [])]
check(FV in ids and FS not in ids, f"P4: a viewer of her project sees only its linked fields, not her templates: {ids}")
ids = [x["id"] for x in F.get(B + f"/api/lists/{FL}/org-fields").json().get("fields", [])]
check(FV in ids and FS in ids, f"P4: she sees all her templates: {ids}")

# ---- 2.609.0 (#3373): required fields bind the app and API v1 / MCP only, never an inner flow that creates a task itself
check(fld(F, fa)["required"], "setup: the field is still required")
check(task(F, FL, "Still no rate").status_code == 400, "the app still refuses a new task without it")
r = F.post(B + f"/api/lists/{FL}/milestones", json={"name": "Phase 1 done", "day": "2026-12-01"})
check(r.ok, f"an inner flow (a milestone of the overview) creates its task anyway: {r.status_code} {r.text[:200]}")

sys.exit(done("p2609_c_schema_api"))
