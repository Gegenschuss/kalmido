#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.593.0 A API tests (#4891): the office lists send the years with data (years = {min, max} or None) for their year
pickers, independent of ?year= and with the rights of the list. Own container (kt.fresh). Invented people and figures.
freelancer-matrix: office
 - travel (GET /api/office/trips): no trip -> None; trips 2019 and this year -> 2019 .. this year, the same with ?year=2019;
   a trip over New Year counts up to its last day; a member with the level "own" (Previous access) gets only the years of
   the own trips and of the trips travelled on, never the admin's 2019
 - meals (GET /api/office/meals): None, then the meal's year; a trashed meal does not count
 - logbook (GET /api/office/vehicles): None, then the years of the drives of all vehicles
 - cash book (GET /api/office/cashbooks/<id>/entries): None, then the entry's year with ?year= of another year
 - books (GET /api/office/books, the tax forms): None, then this year after an issued invoice
The same for a person without an organisation (freelancer_fixture: the personal office).
usage: p2593_a_years_test.py <datadir>"""
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
T, M = O + "/trips", O + "/meals"
TD = testclock.today().isoformat()
Y = int(TD[:4])
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
           "email": "hallo@beispiel.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051",
           "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def years(s, path):
    r = s.get(B + path)
    check(r.ok, f"GET {path} {r.status_code} {r.text[:200]}")
    return r.json().get("years", "missing") if r.ok else "error"


def span(a, b):
    return {"min": a, "max": b}


s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A, "frida")  # freelancer-matrix: office (the personal office, its own admin)
for s in (A, Fr):
    r = s.put(B + O + "/settings", json={"company": {"name": COMPANY["name"]}, "company_fields": COMPANY, "lang": "en", "currency": "EUR"})
    assert r.ok, r.text

for who, s in (("org admin", A), ("freelancer", Fr)):
    me = ALICE if s is A else FID
    # ---------------------------------------------------------------- travel
    check(years(s, T) is None, f"{who}: travel without a trip: years None")
    for d0, d1, dest in (("2019-05-06", "2019-05-07", "Alt"), (TD, TD, "Neu")):
        r = s.post(B + T, json={"date_from": d0, "date_to": d1, "dest": dest, "country": "DE", "people": [{"id": me}]})
        check(r.status_code == 201, f"{who}: a trip {d0} {r.text[:200]}")
    check(years(s, T) == span(2019, Y), f"{who}: travel 2019 .. this year {years(s, T)}")
    check(years(s, T + "?year=2019") == span(2019, Y), f"{who}: travel: the same with ?year=2019 (independent of the filter)")
    r = s.post(B + T, json={"date_from": f"{Y}-12-30", "date_to": f"{Y + 1}-01-02", "dest": "Silvester", "country": "DE", "people": [{"id": me}]})
    check(r.status_code == 201, f"{who}: a trip over New Year {r.text[:200]}")
    check(years(s, T) == span(2019, Y + 1), f"{who}: the trip over New Year reaches next year {years(s, T)}")

    # ---------------------------------------------------------------- meals
    check(years(s, M) is None, f"{who}: meals without a meal: years None")
    r = s.post(B + M, json={"date": "2021-05-14", "place_name": "Trattoria Esempio", "occasion": "Follow-up order",
                            "host": {"id": me}, "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}]})
    check(r.status_code == 201, f"{who}: a meal 2021 {r.text[:200]}")
    m1 = r.json().get("id")
    r = s.post(B + M, json={"date": "2017-03-01", "place_name": "Bistro Beispiel", "occasion": "Planning",
                            "host": {"id": me}, "amounts": [{"kind": "food", "rate": 19, "gross": "50.00"}]})
    check(r.status_code == 201, f"{who}: a meal 2017 {r.text[:200]}")
    m2 = r.json().get("id")
    check(years(s, M) == span(2017, 2021), f"{who}: meals 2017 .. 2021 {years(s, M)}")
    check(s.delete(B + f"{M}/{m2}").ok, f"{who}: the draft of 2017 into the trash")
    check(years(s, M) == span(2021, 2021), f"{who}: a trashed meal does not count {years(s, M)}")
    check(m1, f"{who}: the meal of 2021 stays")

    # ---------------------------------------------------------------- logbook
    check(years(s, O + "/vehicles") is None, f"{who}: logbook without a drive: years None")
    v1 = s.post(B + O + "/vehicles", json={"name": "Kombi", "kind": "private", "odo_start": "1000"}).json()["id"]
    v2 = s.post(B + O + "/vehicles", json={"name": "Transporter", "kind": "private", "odo_start": "500"}).json()["id"]
    for vid, day in ((v1, "2020-02-03"), (v2, "2022-08-09")):
        r = s.post(B + O + "/drives", json={"vehicle_id": vid, "day": day, "dest": "Kunde", "purpose": "Dreh", "km": 30, "kind": "business"})
        check(r.status_code == 201, f"{who}: a drive {day} {r.text[:200]}")
    check(years(s, O + "/vehicles") == span(2020, 2022), f"{who}: logbook 2020 .. 2022 over all vehicles {years(s, O + '/vehicles')}")

    # ---------------------------------------------------------------- cash book
    bk = s.get(B + O + "/cashbooks").json()["books"][0]["id"]
    check(years(s, f"{O}/cashbooks/{bk}/entries") is None, f"{who}: cash book without an entry: years None")
    s.patch(B + f"{O}/cashbooks/{bk}", json={"opening": "100", "opening_day": "2023-01-01"})
    r = s.post(B + f"{O}/cashbooks/{bk}/entries", json={"day": "2023-06-01", "dir": "in", "amount": "50", "text": "Verkauf", "vat_pct": "19"})
    check(r.status_code == 201, f"{who}: a cash entry 2023 {r.text[:200]}")
    check(years(s, f"{O}/cashbooks/{bk}/entries?year={Y}") == span(2023, 2023), f"{who}: cash book 2023 with ?year= of this year")

    # ---------------------------------------------------------------- books
    check(years(s, O + "/books") is None, f"{who}: books without receipts / invoices: years None")
    cl = s.post(B + "/api/clients", json={"name": "Beispiel Kunde GmbH", "email": "kunde@beispiel.example", "street": "Marktstraße 5",
                                          "zip": "50667", "city": "Köln", "country": "DE"}).json()["id"]
    r = s.post(B + O + "/docs", json={"kind": "invoice", "client_id": cl, "service_from": TD, "items": [{"title": "Beratung", "qty": 1, "rate": 100}]})
    check(r.status_code == 201, f"{who}: an invoice {r.text[:200]}")
    r = s.post(B + O + f"/docs/{r.json()['id']}/finalize")
    check(r.ok, f"{who}: the invoice issued {r.status_code} {r.text[:200]}")
    check(years(s, O + "/books") == span(Y, Y), f"{who}: books: this year after the invoice {years(s, O + '/books')}")
    for k in ("euer", "ust"):
        r = s.get(B + O + f"/books/taxform/{k}?year={Y - 1}")
        check(not r.ok or r.json().get("years") == span(Y, Y), f"{who}: tax form {k}: the books' years {r.status_code} {r.text[:120]}")

# ---------------------------------------------------------------- travel, level "own": member Bob
check(years(Bo, T) is None, f"member: no own trip: years None (the admin's 2019 stays hidden) {years(Bo, T)}")
r = Bo.post(B + T, json={"date_from": "2022-04-04", "date_to": "2022-04-04", "dest": "Messe", "country": "DE"})
check(r.status_code == 201, "member: an own trip 2022 " + r.text[:200])
check(years(Bo, T) == span(2022, 2022), f"member: only the own trip's year {years(Bo, T)}")
r = A.post(B + T, json={"date_from": "2024-09-09", "date_to": "2024-09-09", "dest": "Dreh", "country": "DE", "people": [{"id": BOB}]})
check(r.status_code == 201, "admin: a trip with Bob as participant " + r.text[:200])
check(years(Bo, T) == span(2022, 2024), f"member: + the trip travelled on {years(Bo, T)}")
check(years(A, T) == span(2019, Y + 1), f"admin: every trip of the office {years(A, T)}")

raise SystemExit(kt.done("p2593_a_years"))
