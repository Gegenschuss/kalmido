#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.620.0 C API tests (#4586, #4642): regression tests of the office part of package 2.620. Own container (kt.fresh).
Invented people, firms and figures only.
freelancer-matrix: office
 #4586 tasks from a quotation, a task moved to another project (review #3433 M3, L2, L3):
 - the moved task no longer counts in the old project (offer_tasks, the project's budget hours)
 - the next version's preview shows it as "moved" (not ticked, not offered anew); applying with its key ticked writes
   nothing on it (no new task in the old project, its budget value and its link stay)
 - an office member who does not see the project gets offer_tasks 0 (L2), as a viewer of the project the count
 - two quotations (chains) in one project: the budget sums the hours and nets of both (L3)
 #4642 "Travel expenses" from the trip planning for a member without office groups ("Previous access", level "own"):
 - the member makes the travel expenses of an own trip (201, created_by = the member), a second click the same (200), GET
 - the travel expenses the admin made for a shared trip: the member 403 (POST and GET); read-only 403
 - the admin opens the member's (200, the same office trip)
 - a person without an organisation: as before (201 in the personal office)
usage: p2620_c_office_test.py <datadir>"""
import base64
import os
from datetime import timedelta

import kt
from kt import B, check, sess
import testclock
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY})
FEAT = "cal,comments,collab,office,clients,docs,files,fields,time,travel"
O = "/api/office"
D = O + "/docs"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"}
CLIENT = {"name": "Beispiel Kunde AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Musterstadt", "country": "DE"}
D1 = (testclock.today() + timedelta(days=20)).isoformat()
D2 = (testclock.today() + timedelta(days=22)).isoformat()


def sql(q, args=()):
    return kt.dbx(q, args)


def budget_of(tid):
    v = sql("SELECT v.value FROM task_field_values v JOIN list_fields f ON f.id=v.field_id WHERE v.task_id=? AND f.name='Budget h'", (tid,))
    return float(v[0][0]) if v else None


def live_tasks(lid):
    return {t: i for i, t in sql("SELECT id, title FROM tasks WHERE list_id=? AND deleted_at IS NULL ORDER BY id", (lid,))}


s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("mia", "Mia Member"), ("rita", "Rita Readonly")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Mi, Ri = sess("bob"), sess("mia"), sess("rita")
for s in (A, Bo, Mi, Ri):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
SP = f"org:{ORG}"
for u, role in (("bob", "member"), ("mia", "member"), ("rita", "readonly")):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": role}).ok
for s in (A, Bo, Mi, Ri):
    s.patch(B + "/api/settings", json={"workspace": SP})
A.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "de", "currency": "EUR"})

# ================================================================ #4586: a task moved out of the quotation's project
cl = A.post(B + "/api/clients", json=CLIENT).json().get("id")
L = A.post(B + "/api/lists", json={"name": "Imagefilm", "ptype": "agency", "org_id": ORG}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Anderes Projekt", "ptype": "agency", "org_id": ORG}).json()["id"]
items = [{"kind": "service", "title": t, "qty": q, "unit": "hour", "rate": 100} for t, q in (("Konzept", 2), ("Schnitt", 3), ("Grafik", 4))]
r = A.post(B + D, json={"kind": "offer", "lang": "de", "client_id": cl, "items": items})
check(r.status_code == 201, "#4586: the quotation " + r.text[:200])
Q = r.json()["id"]
check(A.post(B + f"{D}/{Q}/project", json={"list_id": L}).ok, "#4586: the project")
pv = A.get(B + f"{D}/{Q}/tasks").json()
r = A.post(B + f"{D}/{Q}/tasks", json={"pick": [x["key"] for x in pv["rows"]]})
check(r.status_code == 201 and r.json().get("created") == 3, "#4586: three tasks " + r.text[:200])
ts = live_tasks(L)
TS = ts.get("Schnitt")
check(A.patch(B + f"/api/tasks/{TS}", json={"list_id": L2}).ok, "#4586: 'Schnitt' moved into another project")
check(sql("SELECT list_id FROM tasks WHERE id=?", (TS,))[0][0] == L2, "#4586: the task is in the other project now")
check(A.get(B + f"{D}/{Q}").json().get("offer_tasks") == 2, f"#4586: the quotation counts only the tasks in its project ({A.get(B + f'{D}/{Q}').json().get('offer_tasks')})")
bud = A.get(B + f"/api/lists/{L}/office-docs").json().get("budget") or {}
check(bud.get("hours") == 6.0, f"#4586: the project's budget without the moved task (2 + 4 h) {bud}")
# the next version: Schnitt 3 -> 5 h
r = A.post(B + f"{D}/{Q}/duplicate")
check(r.status_code == 201, "#4586: a new version " + r.text[:200])
Q2 = r.json()["id"]
d2 = A.get(B + f"{D}/{Q2}").json()
keep = ("id", "kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "ref_part_id")
ni = [{**{k: it.get(k) for k in keep}, **({"qty": 5} if it["title"] == "Schnitt" else {})} for it in d2["items"]]
check(A.put(B + f"{D}/{Q2}/items", json={"items": ni, "parts_known": [p["id"] for p in d2.get("parts") or []]}).ok, "#4586: Schnitt 5 h")
pv2 = A.get(B + f"{D}/{Q2}/tasks").json()
rb = {x["title"]: x for x in pv2["rows"]}
sc = rb.get("Schnitt") or {}
check(sc.get("state") == "moved" and sc.get("pick") is False and sc.get("task_id") == TS and sc.get("moved_to") == "Anderes Projekt",
      f"#4586: the preview shows the moved task, not ticked {sc}")
check(pv2.get("linked") == 2 and not pv2.get("gone"), f"#4586: linked = the tasks in the project, the moved one is not 'gone' {pv2.get('linked')} {pv2.get('gone')}")
link_before = sql("SELECT doc_id, auto_h, set_h, gone FROM task_offer_links WHERE task_id=?", (TS,))
val_before = budget_of(TS)
r = A.post(B + f"{D}/{Q2}/tasks", json={"pick": [x["key"] for x in pv2["rows"]], "hours": {sc.get("key", ""): 7}})
check(r.ok and r.json().get("created") == 0 and r.json().get("updated") == 0, f"#4586: applied, nothing made or written for the moved task {r.text[:200]}")
check(set(live_tasks(L)) == {"Konzept", "Grafik"}, f"#4586: no new 'Schnitt' in the old project {sorted(live_tasks(L))}")
check(sql("SELECT doc_id, auto_h, set_h, gone FROM task_offer_links WHERE task_id=?", (TS,)) == link_before and budget_of(TS) == val_before,
      f"#4586: the moved task's link and budget value untouched {link_before} {val_before} {budget_of(TS)}")
# L2: an office member who does not see the project: no count
check(Bo.get(B + f"{D}/{Q2}").json().get("offer_tasks") == 0, f"#4586 L2: Bob (not in the project) gets no count ({Bo.get(B + f'{D}/{Q2}').json().get('offer_tasks')})")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "view"}).ok, "#4586 L2: Bob a viewer of the project")
check(Bo.get(B + f"{D}/{Q2}").json().get("offer_tasks") == 2, "#4586 L2: as a viewer the count")
pvb = Bo.get(B + f"{D}/{Q2}/tasks").json()
scb = {x["title"]: x for x in pvb.get("rows") or []}.get("Schnitt") or {}
check(scb.get("state") == "moved" and scb.get("task_id") is None and scb.get("moved_to") is None,
      f"#4586: Bob does not see the other project: neither its name nor the task {scb}")
# L3: a second quotation in the same project
r = A.post(B + D, json={"kind": "offer", "lang": "de", "client_id": cl, "items": [{"kind": "service", "title": "Ton", "qty": 5, "unit": "hour", "rate": 100}]})
Q5 = r.json()["id"]
check(A.post(B + f"{D}/{Q5}/project", json={"list_id": L}).ok, "#4586 L3: the second quotation in the project")
k5 = [x["key"] for x in A.get(B + f"{D}/{Q5}/tasks").json()["rows"]]
check(A.post(B + f"{D}/{Q5}/tasks", json={"pick": k5}).status_code == 201, "#4586 L3: its task")
bud = A.get(B + f"/api/lists/{L}/office-docs").json().get("budget") or {}
check(bud.get("hours") == 11.0 and bud.get("doc_id") == Q5 and "1.600,00" in (bud.get("net_text") or ""),
      f"#4586 L3: the budget of both quotations (2 + 4 + 5 h, 1100 + 500 net) {bud}")
bud2 = A.get(B + f"/api/lists/{L2}/office-docs").json().get("budget")
check(bud2 is None, f"#4586: the other project shows no budget of a quotation that is not its own {bud2}")

# ================================================================ #4642: travel expenses from the trip planning, members
r = Bo.post(B + "/api/life/trips", json={"name": "Messe", "from": D1, "to": D2, "where": "Hamburg", "packing": "", "space": SP})
check(r.status_code == 201, "#4642: Bob plans a trip of the organisation " + r.text[:200])
BT = r.json()["list_id"]
r = Bo.post(B + f"/api/life/trips/{BT}/expenses")
check(r.status_code == 201 and r.json().get("created") and r.json().get("office_id") == ORG, f"#4642: a member makes the own travel expenses ({r.status_code}) {r.text[:200]}")
BTID = r.json().get("trip_id")
check(sql("SELECT created_by, org_id FROM office_trips WHERE id=?", (BTID,)) == [(ids["bob"], ORG)], "#4642: the office trip is Bob's")
r = Bo.post(B + f"/api/life/trips/{BT}/expenses")
check(r.status_code == 200 and r.json().get("trip_id") == BTID, "#4642: a second click: the same " + r.text[:200])
check(Bo.get(B + f"/api/life/trips/{BT}/expenses").json().get("trip_id") == BTID, "#4642: GET the linked travel expenses")
check(BTID in [t["id"] for t in Bo.get(B + O + "/trips", params={"year": D1[:4]}).json().get("trips", [])], "#4642: Bob sees it in the office")
# the admin's travel expenses of a trip shared with Bob: not his
r = A.post(B + "/api/life/trips", json={"name": "Dreh", "from": D1, "to": D2, "where": "Köln", "packing": "", "space": SP})
AT = r.json()["list_id"]
check(A.put(B + f"/api/lists/{AT}/members", json={"user_id": ids["bob"], "role": "edit"}).ok, "#4642: the admin's trip shared with Bob")
check(A.put(B + f"/api/lists/{AT}/members", json={"user_id": ids["rita"], "role": "view"}).ok, "#4642: and with read-only Rita")
r = A.post(B + f"/api/life/trips/{AT}/expenses")
check(r.status_code == 201, "#4642: the admin's travel expenses " + r.text[:200])
ATID = r.json().get("trip_id")
r = Bo.post(B + f"/api/life/trips/{AT}/expenses")
check(r.status_code == 403, f"#4642: somebody else's travel expenses: 403 ({r.status_code})")
check(Bo.get(B + f"/api/life/trips/{AT}/expenses").status_code == 403, "#4642: GET somebody else's: 403")
check(sql("SELECT COUNT(*) FROM office_trips WHERE org_id=?", (ORG,))[0][0] == 2, "#4642: no second office trip")
check(Ri.post(B + f"/api/life/trips/{AT}/expenses").status_code == 403, "#4642: read-only 403")
check(Mi.post(B + f"/api/life/trips/{BT}/expenses").status_code == 404, "#4642: a member who does not see the trip 404")
check(A.post(B + f"/api/life/trips/{BT}/expenses").status_code == 404, "#4642: the admin does not see Bob's trip planning (not shared): 404")
check(Bo.put(B + f"/api/lists/{BT}/members", json={"user_id": ALICE, "role": "edit"}).ok, "#4642: Bob shares his trip with the admin")
r = A.post(B + f"/api/life/trips/{BT}/expenses")
check(r.status_code == 200 and r.json().get("trip_id") == BTID, "#4642: the admin opens Bob's " + r.text[:200])
check(ATID != BTID, "#4642: two office trips")

# ================================================================ a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A, "frida")
r = Fr.post(B + "/api/life/trips", json={"name": "Kundenbesuch", "from": D1, "to": D2, "where": "Berlin", "packing": "", "space": "private"})
check(r.status_code == 201, "freelancer: a trip " + r.text[:200])
r = Fr.post(B + f"/api/life/trips/{r.json()['list_id']}/expenses")
pof = sql("SELECT id FROM orgs WHERE personal_of=?", (FID,))
check(r.status_code == 201 and pof and r.json().get("office_id") == pof[0][0], "freelancer: travel expenses in the personal office " + r.text[:200])
Fr.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "de", "currency": "EUR"})
FL = Fr.post(B + "/api/lists", json={"name": "Frida Projekt", "ptype": "agency", "org_id": None}).json()["id"]
FL2 = Fr.post(B + "/api/lists", json={"name": "Frida Zwei", "ptype": "agency", "org_id": None}).json()["id"]
fc = Fr.post(B + "/api/clients", json=CLIENT).json().get("id")
FQ = Fr.post(B + D, json={"kind": "offer", "lang": "de", "client_id": fc, "items": items}).json()["id"]
check(Fr.post(B + f"{D}/{FQ}/project", json={"list_id": FL}).ok, "freelancer: the project")
fk = [x["key"] for x in Fr.get(B + f"{D}/{FQ}/tasks").json()["rows"]]
check(Fr.post(B + f"{D}/{FQ}/tasks", json={"pick": fk}).status_code == 201, "freelancer: tasks from the quotation")
check(Fr.patch(B + f"/api/tasks/{live_tasks(FL)['Schnitt']}", json={"list_id": FL2}).ok, "freelancer: a task moved")
check(Fr.get(B + f"{D}/{FQ}").json().get("offer_tasks") == 2, "freelancer: the count follows the move")
fst = {x["title"]: x["state"] for x in Fr.get(B + f"{D}/{FQ}/tasks").json()["rows"]}
check(fst.get("Schnitt") == "moved", f"freelancer: shown as moved {fst}")

raise SystemExit(kt.done("p2620_c_office"))
