#!/usr/bin/env python3
"""2.189.0 API tests, leader part (#2475): the office's own home currency. Invented companies, people and numbers only.
 - DE: the home currency is EUR and fixed (another one 400), the currency of new documents may be any of the list (an
   unknown code 400), its office rate goes to fx_rates; the pack info lists the currencies, no choice, never locked
 - XX without bookings: the home currency GBP is chosen, the currency of new documents moves along, the office rates
   start empty; a rate for USD (per pound) is kept; members 403 (tenant-matrix: office)
 - after a finalised invoice the home currency is locked (home_locked, a change 400 with the reason, the pack switch to DE
   that would make it EUR as well); other settings still save
 - a person without an organisation (freelancer-matrix: office): own office, base pack, home currency CHF, locked after
   the first finalised invoice
usage: p2189_l_settings_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,comments,office,clients"
O, D = "/api/office", "/api/office/docs"
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


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})

# ---------------------------------------------------------------- DE: EUR, fixed
r = A.put(B + O + "/settings", json={"pack": "DE", "company": {"name": "Studio Beispiel GmbH"},
                                     "company_fields": {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg",
                                                        "country": "DE", "vat_id": "DE999999999", "iban": "DE02120300000000202051"}})
check(r.ok, "setup DE " + r.text[:200])
j = A.get(B + O + "/settings").json()
check(j["settings"]["home_currency"] == "EUR" and j["settings"]["currency"] == "EUR", f"DE: home currency EUR ({j['settings'].get('home_currency')})")
check(j["pack"]["currency_editable"] is False and "GBP" in j["pack"]["currencies"] and j["home_locked"] is False, "DE: no choice, list of currencies " + str(j["pack"])[:120])
r = A.put(B + O + "/settings", json={"home_currency": "GBP"})
check(r.ok and r.json()["settings"]["home_currency"] == "EUR", "DE: the home currency stays EUR " + r.text[:160])
check(A.put(B + O + "/settings", json={"currency": "XYZ"}).status_code == 400, "an unknown currency 400")
check(A.put(B + O + "/settings", json={"fx_rates": {"XYZ": 2}}).status_code == 400, "a rate of an unknown currency 400")
r = A.put(B + O + "/settings", json={"currency": "CHF", "fx_rates": {"CHF": "0,94"}})
check(r.ok and r.json()["settings"]["currency"] == "CHF" and r.json()["settings"]["fx_rates"] == {"CHF": 0.94} and r.json()["settings"]["home_currency"] == "EUR",
      "DE: documents in CHF with the office rate " + r.text[:200])
check(A.put(B + O + "/settings", json={"currency": "EUR"}).ok, "DE: back to EUR documents")
check(Bo.put(B + O + "/settings", json={"home_currency": "GBP"}).status_code == 403, "member 403")

# ---------------------------------------------------------------- XX: chosen while nothing is booked
r = A.put(B + O + "/settings", json={"pack": "XX"})
check(r.ok and r.json()["settings"]["home_currency"] == "EUR" and r.json()["pack"]["currency_editable"] is True, "XX: from EUR, choice offered " + r.text[:200])
r = A.put(B + O + "/settings", json={"home_currency": "GBP"})
st = r.json().get("settings") or {}
check(r.ok and st.get("home_currency") == "GBP" and st.get("currency") == "GBP" and st.get("fx_rates") == {} and r.json().get("home_locked") is False,
      "XX: home currency GBP, documents follow, rates reset " + r.text[:200])
r = A.put(B + O + "/settings", json={"fx_rates": {"USD": 1.27, "GBP": 1}})
check(r.ok and r.json()["settings"]["fx_rates"] == {"USD": 1.27}, "XX: a USD rate per pound kept, none for the home currency " + r.text[:160])
CL = A.post(B + "/api/clients", json={"name": "Example Ltd", "street": "High Street 1", "zip": "SW1A 1AA", "city": "London", "country": "GB"}).json()["id"]
A.put(B + O + "/settings", json={"company_fields": {"country": "GB"}})
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-03-01", "service_to": "2026-03-15",
                        "items": [{"title": "Edit", "qty": 1, "rate": 1000}]})
check(r.status_code == 201, "XX: invoice " + r.text[:200])
I1 = r.json().get("id")
check(A.get(B + f"{D}/{I1}").json().get("currency") == "GBP", "XX: a new document is in GBP")
check(A.get(B + O + "/settings").json()["home_locked"] is False, "a draft locks nothing")
r = A.post(B + f"{D}/{I1}/finalize")
check(r.ok, "XX: finalised " + r.text[:200])

# ---------------------------------------------------------------- locked after the first booking
j = A.get(B + O + "/settings").json()
check(j["home_locked"] is True, "locked after the finalised invoice")
r = A.put(B + O + "/settings", json={"home_currency": "EUR"})
check(r.status_code == 400 and "bookings" in r.text, "a change of the home currency 400 with the reason " + r.text[:200])
check(A.put(B + O + "/settings", json={"pack": "DE"}).status_code == 400, "the switch to DE (home EUR) is refused as well")
check(A.get(B + O + "/settings").json()["settings"]["home_currency"] == "GBP", "the home currency stays GBP")
r = A.put(B + O + "/settings", json={"payment_days": 30, "home_currency": "GBP"})
check(r.ok and r.json()["settings"]["payment_days"] == 30, "other settings still save (the same home currency given along) " + r.text[:160])

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
r = Fr.put(B + O + "/settings", json={"pack": "XX", "company": {"name": "Frida Design"},
                                      "company_fields": {"name": "Frida Design", "street": "Bahnhofstrasse 1", "zip": "8000", "city": "Zürich",
                                                         "country": "CH", "vat_id": "CHE-999.999.999", "iban": "CH9300762011623852957"}})
check(r.ok, "P4: base pack in the personal office " + r.text[:200])
r = Fr.put(B + O + "/settings", json={"home_currency": "CHF"})
check(r.ok and r.json()["settings"]["home_currency"] == "CHF" and r.json()["settings"]["currency"] == "CHF", "P4: home currency CHF " + r.text[:200])
FC = Fr.post(B + "/api/clients", json={"name": "Kunde AG", "street": "Weg 2", "zip": "3000", "city": "Bern", "country": "CH"}).json()["id"]
r = Fr.post(B + D, json={"kind": "invoice", "client_id": FC, "service_from": "2026-03-01", "service_to": "2026-03-15",
                         "items": [{"title": "Design", "qty": 1, "rate": 500}]})
check(r.status_code == 201, "P4: invoice " + r.text[:200])
check(Fr.post(B + f"{D}/{r.json().get('id')}/finalize").ok, "P4: finalised")
j = Fr.get(B + O + "/settings").json()
check(j["home_locked"] is True and Fr.put(B + O + "/settings", json={"home_currency": "EUR"}).status_code == 400, "P4: locked after the first invoice")
check(A.get(B + O + "/settings").json()["settings"]["home_currency"] == "GBP", "the organisation's office is untouched")

print(f"p2189_l_settings: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
