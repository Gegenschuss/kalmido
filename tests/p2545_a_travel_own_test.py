#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.545.0 A API tests (#4592): members of an organisation enter their own trips in the travel expenses (the group
"Previous access" has the level "own" there, office/rights.py LEGACY_OWN). Own container (kt.fresh). Invented people,
firms and figures only.
freelancer-matrix: office
tenant-matrix: office
 - member A: lists only the own trips (+ the ones the admin entered with A as participant, read only), creates / changes /
   deletes the own ones, adds / changes / deletes their receipts; "in DATEV" is never set by a member
 - member A on somebody else's trip: 404 (read via items, change, delete), the trip A only travelled on: 403 read only
 - member B sees none of A's trips (list, report, per diem, missing count) and changes none of them (404)
 - billing, the purposes' set-up, the CSV / per diem files (special "export") and the import stay the admins' (403)
 - the admin sees and changes every trip; another organisation sees none (404)
 - the undo of a delete: the member who deleted it (200), the other member 403
 - GET /api/office/settings: rights.levels.travel = "own" for a member in "Previous access"
The same for a person without an organisation (freelancer_fixture: the personal office, unchanged everything).
usage: p2545_a_travel_own_test.py <datadir>"""
import base64
import os

import kt
from kt import B, check, sess
import testclock
from freelancer_fixture import freelancer

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY})
FEAT = "cal,comments,collab,office,clients,docs,files,travel"
O = "/api/office"
T = O + "/trips"
TD = testclock.today().isoformat()
Y = TD[:4]
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"}


def sql(q, args=()):
    return kt.dbx(q, args)


def ids_of(s, q=""):
    r = s.get(B + T + q)
    return [t["id"] for t in r.json()["trips"]] if r.ok else None


def trip(s, dest, amount="10.00", **kw):
    b = {"date_from": TD, "date_to": TD, "dest": dest, "country": "DE",
         "items": [{"date": TD, "category": "train", "amount": amount, "currency": "EUR", "datev": 1, "datev_no": "X1"}]}
    b.update(kw)
    return s.post(B + T, json=b)


s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("mia", "Mia Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Mi, Ca = sess("bob"), sess("mia"), sess("carol")
for s in (A, Bo, Mi, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
for u in ("bob", "mia"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Mi, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A, "frida")  # freelancer-matrix: office (the personal office, its own admin)
for s in (A, Fr):
    s.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})

# ---------------------------------------------------------------- the admin's trips
r = trip(A, "Kunde Geheim", "500.00", project="Geheimprojekt")
check(r.status_code == 201, "admin: a trip of the admin " + r.text[:200])
TA = r.json()["id"]
r = trip(A, "Dreh Hafen", "80.00", people=[{"id": ids["bob"]}])
check(r.status_code == 201, "admin: a trip with Bob as participant " + r.text[:200])
TAB = r.json()["id"]
TAB_ITEM = r.json()["items"][0]["id"]

# ---------------------------------------------------------------- the rights the client reads
rt = Bo.get(B + O + "/settings").json().get("rights") or {}
check(rt.get("legacy") is True and (rt.get("levels") or {}).get("travel") == "own" and (rt.get("levels") or {}).get("bank") == "none",
      f"member: previous access with travel 'own' {rt}")

# ---------------------------------------------------------------- member A (Bob): the own trips
r = trip(Bo, "Messe Berlin", "42.50")
check(r.status_code == 201, "member A: a new trip " + r.text[:200])
TB = r.json()["id"]
check(r.json()["items"][0]["datev"] == 0 and r.json()["items"][0]["datev_no"] == "", "member A: never 'in DATEV' " + r.text[:300])
check(sql("SELECT created_by FROM office_trips WHERE id=?", (TB,))[0][0] == ids["bob"], "member A: the trip is Bob's")
r = Bo.get(B + T)
lst = r.json() if r.ok else {}
seen = {t["id"]: t for t in lst.get("trips") or []}
check(r.status_code == 200 and TB in seen and TA not in seen, f"member A: own trips only, not the admin's {list(seen)}")
check(TAB in seen and seen[TAB].get("own_ro") == 1 and seen[TB].get("own_ro") == 0, "member A: travelled on = read only, own = editable")
check("Geheimprojekt" not in (lst.get("projects") or []), f"member A: no project names of other trips {lst.get('projects')}")
check(lst.get("missing") == 1, f"member A: missing counts only the own receipts (the admin ticked theirs) {lst.get('missing')}")
r = Bo.patch(B + f"{T}/{TB}", json={"dest": "Messe Berlin 2"})
check(r.ok and r.json()["dest"] == "Messe Berlin 2", "member A: changes the own trip " + r.text[:200])
r = Bo.post(B + f"{T}/{TB}/items", json={"date": TD, "category": "hotel", "amount": "99.00", "currency": "EUR"})
check(r.status_code == 201, "member A: adds a receipt " + r.text[:200])
IB = r.json().get("item_id")
r = Bo.patch(B + f"{T}/{TB}/items/{IB}", json={"text": "Hotel am Messegelände", "datev": 1})
check(r.ok and [i for i in r.json()["items"] if i["id"] == IB][0]["datev"] == 0, "member A: changes the receipt, DATEV stays off " + r.text[:200])
check(Bo.delete(B + f"{T}/{TB}/items/{IB}").ok, "member A: deletes the own receipt")

# somebody else's trips
check(Bo.patch(B + f"{T}/{TA}", json={"dest": "X"}).status_code == 404, "member A: the admin's trip: change 404")
check(Bo.delete(B + f"{T}/{TA}").status_code == 404, "member A: the admin's trip: delete 404")
check(Bo.post(B + f"{T}/{TA}/items", json={"date": TD, "category": "taxi", "amount": "5"}).status_code == 404, "member A: the admin's trip: no receipt 404")
check(Bo.patch(B + f"{T}/{TAB}", json={"dest": "X"}).status_code == 403, "member A: travelled on, entered by the admin: read only 403")
check(Bo.delete(B + f"{T}/{TAB}/items/{TAB_ITEM}").status_code == 403, "member A: the admin's receipt on that trip: 403")
check(sql("SELECT dest FROM office_trips WHERE id=?", (TA,))[0][0] == "Kunde Geheim", "member A: the admin's trip unchanged")

# reports: only the own figures
r = Bo.get(B + f"{T}/report?by=month")
check(r.ok and r.json()["total"] in ("122.50", "122.5"), f"member A: the report sums the own and travelled trips only {r.text[:200]}")
check(Bo.get(B + f"{T}/report?by=month&format=csv").status_code == 403, "member A: the CSV file needs the special export (403)")
r = Bo.get(B + f"{T}/vma?year={Y}")
check(r.ok, "member A: the own per diem report " + r.text[:200])
check(Bo.get(B + f"{T}/vma.csv?year={Y}").status_code == 403, "member A: the per diem file (export) 403")
# the admins' parts
check(Bo.get(B + f"{T}/bill-docs").status_code == 403, "member A: billing (documents) 403")
check(Bo.post(B + f"{T}/bill", json={"doc_id": 1, "item_ids": [TAB_ITEM]}).status_code == 403, "member A: billing 403")
check(Bo.post(B + f"{T}/unbill", json={"item_ids": [TAB_ITEM]}).status_code == 403, "member A: unbilling 403")
check(Bo.get(B + f"{T}/purposes").ok, "member A: reads the purposes (the trip form)")
check(Bo.post(B + f"{T}/purposes", json={"name": "Messe"}).status_code == 403, "member A: sets up no purpose (403)")
check(Bo.post(B + f"{T}/import", json={"trips": []}).status_code == 403, "member A: no import (403)")
check(Bo.get(B + O + "/trash").status_code == 403, "member A: the office trash stays the admins' (403)")

# ---------------------------------------------------------------- member B (Mia): nothing of A
r = trip(Mi, "Workshop Köln", "7.00")
check(r.status_code == 201, "member B: an own trip " + r.text[:200])
TM = r.json()["id"]
mi = ids_of(Mi)
check(mi == [TM], f"member B: only the own trip, none of A's or the admin's {mi}")
check(Mi.get(B + T).json().get("missing") == 1, "member B: missing counts only the own receipt")
check(Mi.patch(B + f"{T}/{TB}", json={"dest": "X"}).status_code == 404, "member B: A's trip: change 404")
check(Mi.delete(B + f"{T}/{TB}").status_code == 404, "member B: A's trip: delete 404")
it = Bo.get(B + T).json()["trips"]
ib = [t for t in it if t["id"] == TB][0]["items"][0]["id"]
check(Mi.patch(B + f"{T}/{TB}/items/{ib}", json={"text": "X"}).status_code == 404, "member B: A's receipt: change 404")
check(Mi.delete(B + f"{T}/{TB}/items/{ib}").status_code == 404, "member B: A's receipt: delete 404")
r = Mi.get(B + f"{T}/report?by=person")
check(r.ok and r.json()["total"] in ("7.00", "7.0", "7") and all("Bob" not in g["label"] for g in r.json()["rows"]),
      f"member B: the report holds only the own trip {r.text[:300]}")
r = Mi.get(B + f"{T}/vma?year={Y}")
check(r.ok and "Messe" not in r.text and "Hafen" not in r.text, "member B: the per diem report has none of A's trips")

# ---------------------------------------------------------------- the admin: every trip
ad = ids_of(A)
check(ad is not None and {TA, TAB, TB, TM} <= set(ad), f"admin: sees every trip {ad}")
r = A.patch(B + f"{T}/{TB}", json={"note": "geprüft"})
check(r.ok, "admin: changes the member's trip " + r.text[:200])
check(A.get(B + f"{T}/report?by=month&format=csv").status_code == 200, "admin: the CSV file")
check(A.get(B + f"{T}/bill-docs").status_code == 200, "admin: billing documents")

# ---------------------------------------------------------------- another organisation
check(ids_of(Ca) == [], "another organisation: none of Alpha's trips")
check(Ca.patch(B + f"{T}/{TB}", json={"dest": "X"}).status_code == 404, "another organisation: change 404")

# ---------------------------------------------------------------- the undo of deleting
r = Bo.delete(B + f"{T}/{TB}")
tt = r.json().get("trash_id") if r.ok else None
check(r.ok and tt and TB not in (ids_of(Bo) or []), "member A: deletes the own trip " + r.text[:200])
check(Mi.post(B + f"{T}/trash/{tt}/restore").status_code in (403, 404), "member B: cannot undo A's delete")
r = Bo.post(B + f"{T}/trash/{tt}/restore")
check(r.ok and r.json().get("id") == TB and TB in (ids_of(Bo) or []), "member A: the undo brings the own trip back " + r.text[:200])

# ---------------------------------------------------------------- a person without an organisation: everything as before
r = trip(Fr, "Location Scout")
check(r.status_code == 201 and r.json()["items"][0]["datev"] == 1, "freelancer: a trip, DATEV ticked by the owner " + r.text[:200])
TF = r.json()["id"]
check(ids_of(Fr) == [TF], "freelancer: the own trip only (personal office)")
check(Fr.patch(B + f"{T}/{TF}", json={"dest": "Location Scout 2"}).ok, "freelancer: changes it")
check(Fr.get(B + f"{T}/report?by=month&format=csv").status_code == 200, "freelancer: the CSV file")
check(Fr.get(B + f"{T}/bill-docs").status_code == 200, "freelancer: billing documents")
check(Fr.post(B + f"{T}/purposes", json={"name": "Recherche"}).status_code == 201, "freelancer: an own purpose")
check(Fr.patch(B + f"{T}/{TA}", json={"dest": "X"}).status_code == 404, "freelancer: Alpha's trip 404")
check(Fr.delete(B + f"{T}/{TF}").status_code == 409, "freelancer: a trip with a receipt in DATEV stays (kept by law, 409)")
TF2 = Fr.post(B + T, json={"date_from": TD, "date_to": TD, "dest": "Ohne Beleg"}).json()["id"]
check(Fr.delete(B + f"{T}/{TF2}").ok and TF2 not in (ids_of(Fr) or []), "freelancer: deletes a trip")

raise SystemExit(kt.done("p2545_a_travel_own"))
