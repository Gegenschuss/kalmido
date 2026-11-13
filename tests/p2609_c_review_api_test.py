#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.609.0 (#3372 / #3373): the findings of the review of ticket types and the organisation's schema, each with its
regression check. Own container (hosted, a server key: sealed files and a support session). Invented names only.
 - F1 an organisation's task template goes into a private project / the inbox only through its admin (logged), a member gets
   403; its project template makes the project in the organisation only: a read-only member 403 (was: privately), a support
   session without the organisation's own support access 403 support_session
 - F2 an admin who makes another admin's organisation template private owns it now (with its file copies)
 - F3 a guest gets no organisation labels in the app state and cannot reach them by name (a plain project tag at most)
 - F4 an organisation's templates stay when their maker's account goes (the heir owns them, their files still open);
   they no longer count for their maker's limit
 - F5 the trash lists an organisation's deleted template for its admins (also when another admin made it), not for a member
 - F6 a guest gets no workspace view of the organisation's ticket types (404) and in the plain list only key, name, icon,
   colour of the types its shared project offers; the task counts only for the types' managers
 - F7 a project admin without the full view switches on no field of the schema (404), switching off stays
 - F8 deleting a ticket type changes its tasks' updated_at; the API needs the scope delete for it
 - F9 fkey_<key> over more than 200 projects' fields: 400
freelancer-matrix: orgschema. A person without an organisation: her template's trash, her ticket types as before
usage: p2609_c_review_api_test.py <datadir>"""
import os
import sys

import requests

import dbx as dbxm
import kt
from kt import B, H, check, dbx, sess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer, login  # noqa: E402

KEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (32 bytes, base64)
PW = kt.PASSWORD
V = B + "/api/v1"
FEAT = "collab,comments,fields"

kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_HOSTED": "1"})
assert kt.sess(None).post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": PW}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
ORG = A.get(B + "/api/orgs").json()["orgs"][0]["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u, role in (("bob", "member"), ("dora", "admin"), ("eve", "admin"), ("rita", "readonly"), ("gina", "guest"), ("cara", "member")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": PW, "email": f"{u}@example.com",
                                       "orgs": [{"id": ORG, "role": role}]})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Do, Ev, Ri, Gi, Cc = (login(B, u) for u in ("bob", "dora", "eve", "rita", "gina", "cara"))
for s in (A, Bo, Do, Ev, Ri, Gi, Cc):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT}).ok
FID, Fr = freelancer(B, A)


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"), timeout=10)
    c.execute(sql, args)
    c.commit()
    c.close()


def st(s):
    return s.get(B + "/api/state").json()


def mklist(s, name, org=None, **kw):
    r = s.post(B + "/api/lists", json={"name": name, "kind": "project", "org_id": org, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def attach(s, tid, name, data):
    assert s.post(B + f"/api/tasks/{tid}/attachments", files={"file": (name, data, "text/plain")}).ok


def files_of(tid):
    return dbx("SELECT id, name FROM attachments WHERE task_id=? AND deleted_at IS NULL ORDER BY id", (tid,))


def tok(s, scopes):
    r = s.post(B + "/api/me/tokens", json={"name": "t", "scopes": list(scopes)})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"], **H}


def tpl(s, **kw):
    r = s.post(B + "/api/templates", json=kw)
    assert r.ok, r.text
    return r.json()["id"]


def trash_tpls(s):
    return [x["id"] for x in s.get(B + "/api/trash/parts").json()["items"] if x["kind"] == "template"]


L1 = mklist(A, "Support desk", ORG, tickets=True)
for u, role in (("bob", "edit"), ("dora", "edit"), ("eve", "edit"), ("gina", "edit")):
    assert A.put(B + f"/api/lists/{L1}/members", json={"user_id": uid[u], "role": role}).ok
LB = mklist(Bo, "Bob's own", None)
LA = mklist(A, "Alice's own", None)
check(next(x for x in st(Bo)["lists"] if x["id"] == LB)["org_id"] is None, "setup: bob has a private project")
T1 = task(A, L1, "Printer jams")

# ================================================================== F1 applying an organisation's template
TT = tpl(A, task_id=T1, name="Jam fix", space=f"org:{ORG}")
r = Bo.post(B + f"/api/templates/{TT}/apply", json={"list_id": LB})
check(r.status_code == 403, f"F1: a member does not put the organisation's template into a private project {r.status_code} {r.text[:120]}")
r = Bo.post(B + f"/api/templates/{TT}/apply", json={})
check(r.status_code == 403, f"F1: nor into the own inbox {r.status_code}")
check(not any(t["title"] == "Printer jams" and t["list_id"] != L1 for t in st(Bo)["tasks"]), "F1: nothing landed outside")
r = Bo.post(B + f"/api/templates/{TT}/apply", json={"list_id": L1})
check(r.ok, f"F1: into a project of the organisation it works {r.text[:120]}")
n0 = dbx("SELECT COUNT(*) FROM org_list_log WHERE org_id=? AND action='moveout' AND detail LIKE ?", (ORG, '%"template"%'))[0][0]
r = A.post(B + f"/api/templates/{TT}/apply", json={"list_id": LA})
check(r.ok, f"F1: the admin takes it into her own project {r.text[:120]}")
n1 = dbx("SELECT COUNT(*) FROM org_list_log WHERE org_id=? AND action='moveout' AND detail LIKE ?", (ORG, '%"template"%'))[0][0]
check(n1 == n0 + 1, f"F1: logged as a move out of the organisation {n0} -> {n1}")
TP = tpl(A, list_id=L1, name="Desk project", space=f"org:{ORG}")
before = len(dbx("SELECT id FROM lists WHERE deleted_at IS NULL"))
r = Ri.post(B + f"/api/templates/{TP}/apply", json={"name": "Rita's desk"})
check(r.status_code == 403, f"F1: a read-only member cannot make the organisation's project (was: privately) {r.status_code} {r.text[:120]}")
check(len(dbx("SELECT id FROM lists WHERE deleted_at IS NULL")) == before, "F1: no project was made")
r = Bo.post(B + f"/api/templates/{TP}/apply", json={"name": "Bob's desk"})
check(r.ok and dbx("SELECT org_id FROM lists WHERE id=?", (r.json().get("list_id"),)) == [(ORG,)], f"F1: a member makes it in the organisation {r.text[:120]}")

# F1 (not checked by the review): a support session and the organisation's fixed org_id
# cara makes the company herself: since 2.593.0 (#3570) an invitation from a company of one's own (POST /api/orgs) to an
# account its maker may not see (cara is in another organisation) stays silent, so she could never accept it
r = Cc.post(B + "/api/orgs", json={"name": "Client Studio"})
assert r.status_code == 201, r.text
CO = r.json()["id"]
CL = mklist(Cc, "Studio board", CO)
CT = tpl(Cc, list_id=CL, name="Studio project", space=f"org:{CO}")
r = Cc.post(B + f"/api/templates/{CT}/apply", json={"name": "Cara's studio"})
check(r.ok and dbx("SELECT org_id FROM lists WHERE id=?", (r.json().get("list_id"),)) == [(CO,)], f"F1: cara's own session makes it {r.text[:120]}")
assert Cc.post(B + "/api/support-access", json={"hours": 1}).ok
r = A.post(B + f"/api/users/{uid['cara']}/signin-link")
assert r.ok, r.text
Y = kt.sess(None)
assert Y.post(B + "/api/auth/link", json={"token": r.json()["link"].split("#signin/")[1]}).ok
n0 = dbx("SELECT COUNT(*) FROM lists WHERE org_id=?", (CO,))[0][0]
r = Y.post(B + f"/api/templates/{CT}/apply", json={"name": "Support's studio"})
check(r.status_code == 403 and r.json().get("code") == "support_session",
      f"F1: a support session makes no project in an organisation without its own support access {r.status_code} {r.text[:120]}")
check(dbx("SELECT COUNT(*) FROM lists WHERE org_id=?", (CO,))[0][0] == n0, "F1: nothing was made there")

# ================================================================== F4 the maker's account goes
TF0 = task(Do, L1, "Escalation")
attach(Do, TF0, "spec.txt", b"the spec\n")
TF = tpl(Do, task_id=TF0, name="Escalation", space=f"org:{ORG}")
r = A.delete(B + f"/api/users/{uid['dora']}")
check(r.ok, f"F4: dora's account deleted {r.status_code} {r.text[:160]}")
# 2.905.0 (#5288): templates.owner_id (was user_id)
check(dbx("SELECT owner_id, org_id FROM templates WHERE id=?", (TF,)) == [(ALICE, ORG)], "F4: the organisation's template stays, with the heir")
check(any(x["id"] == TF for x in Bo.get(B + "/api/templates").json()["templates"]), "F4: the members still see it")
r = Bo.post(B + f"/api/templates/{TF}/apply", json={"list_id": L1})
nt = r.json().get("task", {}).get("id") if r.ok else None
f = files_of(nt) if nt else []
check(f and Bo.get(B + f"/api/attachments/{f[0][0]}").content == b"the spec\n", f"F4: its file opens after the key went {r.text[:120]} {f}")
# the limit: the organisation's templates no longer count for the person who made them
# 2.905.0 (#5288): templates.owner_id (was user_id)
dbw("INSERT INTO templates(owner_id,kind,name,data,created_at,updated_at,org_id) SELECT ?, 'task', 'bulk ' || g, '{\"task\":{\"title\":\"x\"}}', "
    "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', ? FROM generate_series(1, 200) g", (ALICE, ORG))
r = A.post(B + "/api/templates", json={"kind": "task", "data": {"task": {"title": "Mine"}}, "name": "Still mine"})
check(r.ok, f"F4: 200 organisation templates do not block her own {r.status_code} {r.text[:120]}")
r = A.post(B + "/api/templates", json={"kind": "task", "data": {"task": {"title": "One more"}}, "name": "Org 201", "space": f"org:{ORG}"})
check(r.status_code == 400, f"F4: the organisation has its own limit {r.status_code}")
dbw("DELETE FROM templates WHERE org_id=? AND name LIKE 'bulk %'", (ORG,))

# ================================================================== F2 an admin makes another admin's template private
TD0 = task(Ev, L1, "Eve's checklist")
attach(Ev, TD0, "steps.txt", b"step one\n")
TD = tpl(Ev, task_id=TD0, name="Eve's checklist", space=f"org:{ORG}")
check(dbx("SELECT user_id FROM template_files WHERE template_id=?", (TD,)) == [(uid["eve"],)], "setup: the template has eve's file copy")
r = A.patch(B + f"/api/templates/{TD}", json={"space": "private"})
check(r.ok and r.json()["org_id"] is None and r.json()["mine"] is True, f"F2: the admin who makes it private owns it {r.text[:160]}")
# 2.905.0 (#5288): templates.owner_id (was user_id)
check(dbx("SELECT owner_id FROM templates WHERE id=?", (TD,)) == [(ALICE,)], "F2: owner_id = the admin")
check(dbx("SELECT user_id FROM template_files WHERE template_id=?", (TD,)) == [(ALICE,)], "F2: its file copies follow")
check(not any(x["id"] == TD for x in Ev.get(B + "/api/templates").json()["templates"]), "F2: not eve's private template")
r = A.post(B + f"/api/templates/{TD}/apply", json={"list_id": LA})
nt = r.json().get("task", {}).get("id") if r.ok else None
f = files_of(nt) if nt else []
check(f and A.get(B + f"/api/attachments/{f[0][0]}").content == b"step one\n", f"F2: its file still opens {r.text[:120]} {f}")

# ================================================================== F5 the trash of the organisation's templates
TE = tpl(Ev, kind="task", data={"task": {"title": "Eve's"}}, name="Eve's routine", space=f"org:{ORG}")
check(A.delete(B + f"/api/templates/{TE}").ok, "setup: alice deletes eve's organisation template")
check(TE in trash_tpls(A), "F5: the admin who deleted it finds it in the trash")
check(TE in trash_tpls(Ev), "F5: the other admin too")
check(TE not in trash_tpls(Bo), "F5: a member does not")
check(A.post(B + f"/api/templates/{TE}/restore").ok, "F5: restored from there")

# ================================================================== F3 labels and a guest
r = A.post(B + "/api/org-labels", json={"org_id": ORG, "name": "Acme deal", "color": "#f87171"})
assert r.status_code == 201, r.text
OLB = r.json()["id"]
check(any(x["id"] == OLB for x in st(Bo).get("org_labels", [])), "F3: a member gets the label")
check(any(x["id"] == OLB for x in st(Ri).get("org_labels", [])), "F3: a read-only member too (full view)")
check(st(Gi).get("org_labels") == [], f"F3: a guest of a shared project does not {st(Gi).get('org_labels')}")
TG = task(A, L1, "Guest's ticket")
Gi.patch(B + f"/api/tasks/{TG}", json={"ltags": ["Acme deal"]})
lt = next(x for x in st(A)["lists"] if x["id"] == L1)["tags"]
check(not any(x.get("org_tag_id") == OLB for x in lt), f"F3: the guest's tag by that name is no link to the label {lt}")
check(Bo.patch(B + f"/api/tasks/{TG}", json={"ltags": ["Acme deal"]}).ok, "F3: a member uses the label")
lt = next(x for x in st(A)["lists"] if x["id"] == L1)["tags"]
check(any(x.get("org_tag_id") == OLB for x in lt) or any(x["name"] == "Acme deal" for x in lt), f"F3: the member's use works {lt}")

# ================================================================== F6 ticket types and a guest
r = A.post(B + "/api/ticket-types", json={"space": f"org:{ORG}", "name": "Incident", "template": "**Internal runbook**\n"})
assert r.ok, r.text
INC = r.json()["id"]
r = A.post(B + "/api/ticket-types", json={"space": f"org:{ORG}", "name": "Hidden kind", "enabled": False})
assert r.ok, r.text
HID = r.json()["id"]
TI = task(A, L1, "Server down", ttype="incident")
r = Gi.get(B + "/api/ticket-types", params={"space": f"org:{ORG}"})
check(r.status_code == 404, f"F6: a guest has no workspace view of the types {r.status_code}")
ty = Gi.get(B + "/api/ticket-types").json()["types"]
inc = next((x for x in ty if x["key"] == "incident"), None)
check(inc and set(inc) <= {"key", "name", "icon", "color", "enabled", "org_id", "space"} and "template" not in inc,
      f"F6: the guest sees the offered type with key, name, icon, colour only {inc}")
check(not any(x["key"] == "hidden_kind" for x in ty), f"F6: not a switched off one {[x['key'] for x in ty]}")
j = Bo.get(B + "/api/ticket-types", params={"space": f"org:{ORG}"}).json()
check(j["types"] and all("tasks" not in x for x in j["types"]), f"F6: a member reads them without task counts {j['types']}")
j = A.get(B + "/api/ticket-types", params={"space": f"org:{ORG}"}).json()
check(next(x for x in j["types"] if x["id"] == INC).get("tasks") == 1, f"F6: the admin sees the count {j['types']}")
check(any(x["key"] == "incident" and "template" in x for x in Bo.get(B + "/api/ticket-types").json()["types"]), "F6: a member still meets the full type")

# ================================================================== F8 deleting a type: updated_at, the scope delete
dbw("UPDATE tasks SET updated_at='2026-01-01T00:00:00Z' WHERE id=?", (TI,))
r = requests.delete(V + f"/ticket-types/{INC}", headers=tok(A, ("read", "structure")), params={"confirm": "1"})
check(r.status_code == 403, f"F8: the scope structure no longer deletes a type {r.status_code} {r.text[:120]}")
r = requests.delete(V + f"/ticket-types/{INC}", headers=tok(A, ("read", "delete")), params={"confirm": "1"})
check(r.ok and r.json().get("tasks") == 1, f"F8: the scope delete does {r.status_code} {r.text[:120]}")
check(dbx("SELECT ttype, updated_at FROM tasks WHERE id=?", (TI,))[0][1] != "2026-01-01T00:00:00Z", "F8: the task's updated_at changed")
r = requests.get(V + "/tasks", headers=tok(A, ("read",)), params={"updated_since": "2026-06-01T00:00:00Z", "list_id": L1})
check(r.ok and TI in [x["id"] for x in r.json()["data"]], f"F8: updated_since finds the task {r.status_code}")
spec = requests.get(V + "/openapi.json").json()
check(spec["paths"]["/ticket-types/{id}"]["delete"].get("x-kalmido-scope") == "delete", "F8: OpenAPI names the scope delete")
assert A.delete(B + f"/api/ticket-types/{HID}").ok

# ================================================================== F7 a project admin without the full view
OFX = A.post(B + "/api/org-fields", json={"space": f"org:{ORG}", "name": "Internal margin", "type": "text"}).json()["id"]
OFL = A.post(B + "/api/org-fields", json={"space": f"org:{ORG}", "name": "Region", "type": "text"}).json()["id"]
assert A.put(B + f"/api/lists/{L1}/org-fields/{OFL}", json={"on": True}).ok
r = A.put(B + f"/api/lists/{L1}/members", json={"user_id": uid["gina"], "role": "admin"})
check(r.ok, f"setup: a guest of the organisation administers the project {r.status_code} {r.text[:120]}")
check([x["id"] for x in Gi.get(B + f"/api/lists/{L1}/org-fields").json()["fields"]] == [OFL], "setup: the guest admin sees only the linked field")
r = Gi.put(B + f"/api/lists/{L1}/org-fields/{OFX}", json={"on": True})
check(r.status_code == 404, f"F7: she cannot switch on a field of the schema she does not see {r.status_code} {r.text[:120]}")
check(not any(f.get("org_field_id") == OFX for f in st(A)["fields"]), "F7: nothing was linked")
r = Gi.put(B + f"/api/lists/{L1}/org-fields/{OFL}", json={"on": False})
check(r.ok, f"F7: switching off stays {r.status_code} {r.text[:120]}")
check(A.put(B + f"/api/lists/{L1}/org-fields/{OFL}", json={"on": True}).ok, "setup: linked again")
check(Bo.put(B + f"/api/lists/{L1}/org-fields/{OFX}", json={"on": True}).status_code == 403, "F7: a member without project admin: 403 as before")

# ================================================================== F9 fkey_ over too many projects
PA = tok(A, ("read",))
r = requests.get(V + "/tasks", headers=PA, params={"fkey_region": "north"})
check(r.ok, f"setup: fkey_region works {r.status_code} {r.text[:120]}")
dbw("INSERT INTO list_fields(list_id,name,type,options,pinned,sort,created_at,org_field_id) SELECT ?, 'Region ' || g, 'text', '{}', false, 1000 + g, "
    "'2026-01-01T00:00:00Z', ? FROM generate_series(1, 200) g", (L1, OFL))
r = requests.get(V + "/tasks", headers=PA, params={"fkey_region": "north"})
check(r.status_code == 400 and "200" in r.text, f"F9: more than 200 linked fields: 400 {r.status_code} {r.text[:160]}")
dbw("DELETE FROM list_fields WHERE list_id=? AND name LIKE 'Region %'", (L1,))
check(requests.get(V + "/tasks", headers=PA, params={"fkey_region": "north"}).ok, "F9: back under the limit it works")

# ================================================================== freelancer-matrix: orgschema
FL = mklist(Fr, "My work", None)
FT = task(Fr, FL, "Invoice run")
FP = tpl(Fr, task_id=FT, name="Invoice run")
check(Fr.post(B + f"/api/templates/{FP}/apply", json={}).ok, "P4: her own template into her inbox as before")
check(Fr.delete(B + f"/api/templates/{FP}").ok and FP in trash_tpls(Fr), "P4: her deleted template is in her trash")
check(FP not in trash_tpls(A), "P4: not in anybody else's")
check(Fr.post(B + f"/api/templates/{FP}/restore").ok, "P4: restored")
check(Fr.get(B + "/api/ticket-types").ok and Fr.get(B + "/api/ticket-types", params={"space": "private"}).ok, "P4: her ticket types as before")
check(Fr.get(B + "/api/ticket-types", params={"space": f"org:{ORG}"}).status_code == 404, "P4: no organisation's types")

sys.exit(kt.done("p2609_c_review_api"))
