#!/usr/bin/env python3
"""2.189.0 API tests, part A (#2475): documents in the office's own home currency. Invented companies and numbers only.
 - base pack XX with home GBP: quotation and invoice in GBP without a rate (no tax line in another currency), the
   currency choice offers every code, the e-invoice has no tax currency (BT-6)
 - an invoice in USD takes the office rate (fx_rates), its rates are converted from GBP, the tax in GBP (tax_eur keeps its
   key), rate note and tax line name GBP; the e-invoice carries BT-6 GBP and BT-111 in GBP
 - after a finalised invoice PUT /api/office/settings home_currency is refused (home_locked), office rates still change
 - a DE office stays EUR (home_currency cannot be changed); an invoice in CHF there has its tax line in EUR; USD keeps the
   words of before ("Exchange rate €1: $1.1", "Tax amount equals EUR …")
 - a person without an organisation (freelancer-matrix: office): own XX office with home CHF, quotation in CHF, invoice in
   EUR with the office rate, tax line in CHF, e-invoice BT-6 CHF, home currency locked after finalising
usage: p2189_a_docs_test.py <datadir>"""
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
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def doc(s, kind, client, rate=100, qty=1, extra=None):
    b = {"kind": kind, "lang": "en", "client_id": client, "items": [{"title": "Edit", "qty": qty, "rate": rate}]}  # texts in English
    if kind == "invoice":
        b.update(service_from="2026-03-01", service_to="2026-03-15")
    r = s.post(B + D, json=dict(b, **(extra or {})))
    assert r.status_code == 201, r.text
    return s.get(B + f"{D}/{r.json()['id']}").json()


def xml(s, did):
    r = s.post(B + f"{D}/{did}/finalize")
    check(r.ok, f"finalised {did} " + r.text[:200])
    x = s.get(B + f"{D}/{did}/xml")
    return x.content if x.ok else b""


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})

# ---------------------------------------------------------------- XX office with home GBP
r = A.put(B + O + "/settings", json={"pack": "XX", "home_currency": "GBP", "company": {"name": "Brightside Ltd"},
                                     "company_fields": {"name": "Brightside Ltd", "street": "1 High Street", "zip": "AB1 2CD", "city": "Exampleton",
                                                        "country": "GB", "vat_id": "GB999999973", "iban": "GB33BUKB20201555555555"}})
check(r.ok, "XX office with home GBP saved " + r.text[:200])
j = A.get(B + O + "/settings").json()
check(j["settings"]["home_currency"] == "GBP" and j["settings"]["currency"] == "GBP", f"home GBP, new documents in GBP ({j['settings'].get('home_currency')}, {j['settings'].get('currency')})")
check(j["pack"].get("currency_editable") is True and {"GBP", "CHF", "USD", "EUR"} <= set(j["pack"].get("currencies") or []) and j.get("home_locked") is False,
      f"the pack offers every currency, not locked yet ({j['pack'].get('currencies')}, {j.get('home_locked')})")
CL = A.post(B + "/api/clients", json={"name": "Example Client Ltd", "street": "2 Low Road", "zip": "EF3 4GH", "city": "Sampleford", "country": "GB"}).json()["id"]

q = doc(A, "offer", CL, rate=100, qty=2)
t = q["totals"]
check(q["currency"] == "GBP" and t.get("home") == "GBP" and t.get("fx_rate") is None and float(t["net"]) == 200 and not t.get("fx_note"),
      f"quotation in GBP without a rate ({q['currency']}, {t.get('home')}, {t.get('fx_rate')}, {t.get('net')}, {t.get('fx_note')})")
check("£" in q["gross_text"], f"the sum carries the pound sign ({q['gross_text']})")
iv = doc(A, "invoice", CL, rate=1000)
t = iv["totals"]
check(iv["currency"] == "GBP" and "tax_eur" not in t and t.get("home") == "GBP", f"invoice in GBP: no tax line in another currency ({sorted(t)[:12]})")
x = xml(A, iv["id"])
check(b"<ram:InvoiceCurrencyCode>GBP</ram:InvoiceCurrencyCode>" in x and b"TaxCurrencyCode" not in x, "e-invoice in the home currency GBP: BT-5 GBP, no BT-6 ")

# ---------------------------------------------------------------- the home currency is locked after a booking
r = A.put(B + O + "/settings", json={"home_currency": "EUR"})
check(r.status_code == 400 and "can no longer be changed" in r.text, "home currency locked after a finalised invoice " + r.text[:200])
check(A.get(B + O + "/settings").json().get("home_locked") is True, "settings: home_locked")
r = A.put(B + O + "/settings", json={"fx_rates": {"USD": 1.25}})
check(r.ok and r.json()["settings"]["home_currency"] == "GBP", "office rates still change " + r.text[:160])

# ---------------------------------------------------------------- an invoice in USD in the GBP office
iu = doc(A, "invoice", CL, rate=100, extra={"currency": "USD"})
t = iu["totals"]
check(iu["currency"] == "USD" and float(iu["fx_rate"]) == 1.25, f"USD takes the office rate 1.25 ({iu['currency']}, {iu['fx_rate']})")
check(float(t["lines"][0]["rate"]) == 125 and float(t["net"]) == 125 and float(t["tax"]) == 25, f"rate converted from GBP: 100 x 1.25 ({t['lines'][0].get('rate')}, {t['net']}, {t['tax']})")
check(t.get("tax_eur") == "20.00" and "£20.00" in (t.get("tax_eur_text") or ""), f"tax in the home currency GBP under tax_eur ({t.get('tax_eur')}, {t.get('tax_eur_text')})")
check(t.get("fx_note") == "Exchange rate 1 GBP = 1.25 USD", f"rate note names GBP ({t.get('fx_note')})")
rd = A.get(B + f"{D}/{iu['id']}/render").json()
check(rd["totals"].get("fx_line") == "Tax amount equals GBP 20.00, rate GBP 1 = USD 1.25", f"tax line on the document in GBP ({rd['totals'].get('fx_line')})")
check(["Exchange rate 1 GBP", "Exchange rate 1 GBP = 1.25 USD"] in rd.get("meta", []), f"head row of the rate names GBP ({[m for m in rd.get('meta', []) if 'xchange' in m[0]]})")
x = xml(A, iu["id"])
check(b"<ram:InvoiceCurrencyCode>USD</ram:InvoiceCurrencyCode>" in x and b"<ram:TaxCurrencyCode>GBP</ram:TaxCurrencyCode>" in x
      and b'<ram:TaxTotalAmount currencyID="GBP">20.00</ram:TaxTotalAmount>' in x and b'currencyID="EUR"' not in x, "e-invoice: BT-6 GBP, BT-111 in GBP")
ic = doc(A, "invoice", CL, rate=100, extra={"currency": "CHF", "fx_rate": "1,1"})
check(ic["currency"] == "CHF" and float(ic["fx_rate"]) == 1.1 and float(ic["totals"]["net"]) == 110, f"any code with a rate by hand ({ic['currency']}, {ic['fx_rate']}, {ic['totals'].get('net')})")
check(A.patch(B + f"{D}/{ic['id']}", json={"currency": "XYZ"}).status_code == 400, "unknown currency 400")

# ---------------------------------------------------------------- a DE office stays EUR (a person without an organisation)
FID, Fr = freelancer(B, A, "fred", features=FEAT)  # freelancer-matrix: office (DE office, EUR fixed)
j = Fr.get(B + O + "/settings").json()
check(j["settings"]["home_currency"] == "EUR" and j["pack"].get("currency_editable") is False, f"DE: home EUR, fixed ({j['settings'].get('home_currency')}, {j['pack'].get('currency_editable')})")
r = Fr.put(B + O + "/settings", json={"home_currency": "GBP"})
check(Fr.get(B + O + "/settings").json()["settings"]["home_currency"] == "EUR", "DE: the home currency stays EUR " + r.text[:120])
FC = Fr.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]
fc = doc(Fr, "invoice", FC, rate=100, extra={"currency": "CHF", "fx_rate": "0.95", "lang": "en"})
t = fc["totals"]
check(t.get("home") == "EUR" and float(t["net"]) == 95 and t.get("tax_eur") == "19.00" and t.get("fx_note") == "Exchange rate 1 EUR = 0.95 CHF",
      f"EUR office, invoice in CHF: tax in EUR ({t.get('home')}, {t.get('net')}, {t.get('tax_eur')}, {t.get('fx_note')})")
rd = Fr.get(B + f"{D}/{fc['id']}/render").json()
check(rd["totals"].get("fx_line") == "Tax amount equals EUR 19.00, rate EUR 1 = CHF 0.95", f"CHF tax line ({rd['totals'].get('fx_line')})")
fu = doc(Fr, "invoice", FC, rate=100, extra={"currency": "USD", "fx_rate": "1.1", "lang": "en"})
t = fu["totals"]
check(t.get("fx_note") == "Exchange rate €1: $1.1" and t.get("tax_eur") == "19.00", f"USD in a EUR office: the words of before ({t.get('fx_note')}, {t.get('tax_eur')})")
rd = Fr.get(B + f"{D}/{fu['id']}/render").json()
check(rd["totals"].get("fx_line") == "Tax amount equals EUR 19.00, rate EUR 1 = USD 1.1", f"USD tax line as before ({rd['totals'].get('fx_line')})")
check(any(m[1] == "Exchange rate €1: $1.1" and "€" in m[0] for m in rd.get("meta", [])), f"USD head row as before ({[m for m in rd.get('meta', []) if 'xchange' in m[0]]})")
fe = doc(Fr, "invoice", FC, rate=100)
check(fe["currency"] == "EUR" and float(fe["fx_rate"]) == 1.09 and "tax_eur" not in fe["totals"], f"EUR invoice in a EUR office as before ({fe['currency']}, {fe['fx_rate']})")

# ---------------------------------------------------------------- P4: own XX office with home CHF
EID, Er = freelancer(B, A, "erin", features=FEAT)  # freelancer-matrix: office (XX office, home CHF)
r = Er.put(B + O + "/settings", json={"pack": "XX", "home_currency": "CHF", "company": {"name": "Erin Design"},
                                      "company_fields": {"name": "Erin Design", "street": "Gasse 1", "zip": "8000", "city": "Beispielstadt",
                                                         "country": "CH", "vat_id": "CHE999999999", "iban": "CH9300762011623852957"}})
check(r.ok and r.json()["settings"]["home_currency"] == "CHF", "P4: own office with home CHF " + r.text[:200])
r = Er.put(B + O + "/settings", json={"fx_rates": {"EUR": 1.05}})
check(r.ok and r.json()["settings"].get("fx_rates") == {"EUR": 1.05}, f"P4: office rate EUR saved ({r.json()['settings'].get('fx_rates') if r.ok else ''})")
EC = Er.post(B + "/api/clients", json={"name": "Client SA", "street": "Avenue 2", "zip": "1050", "city": "Bruxelles", "country": "BE"}).json()["id"]
eq = doc(Er, "offer", EC, rate=100)
check(eq["currency"] == "CHF" and eq["totals"].get("home") == "CHF" and "CHF" in eq["gross_text"], f"P4: quotation in CHF ({eq['currency']}, {eq['gross_text']})")
ee = doc(Er, "invoice", EC, rate=100, extra={"currency": "EUR"})
t = ee["totals"]
check(float(ee["fx_rate"]) == 1.05 and float(t["net"]) == 105 and t.get("tax_eur") == "20.00", f"P4: invoice in EUR with the office rate, tax in CHF ({ee['fx_rate']}, {t.get('net')}, {t.get('tax_eur')})")
rd = Er.get(B + f"{D}/{ee['id']}/render").json()
check(rd["totals"].get("fx_line") == "Tax amount equals CHF 20.00, rate CHF 1 = EUR 1.05", f"P4: tax line in CHF ({rd['totals'].get('fx_line')})")
x = xml(Er, ee["id"])
check(b"<ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>" in x and b"<ram:TaxCurrencyCode>CHF</ram:TaxCurrencyCode>" in x
      and b'<ram:TaxTotalAmount currencyID="CHF">20.00</ram:TaxTotalAmount>' in x, "P4: e-invoice BT-6 CHF, BT-111 in CHF")
r = Er.put(B + O + "/settings", json={"home_currency": "GBP"})
check(r.status_code == 400 and "can no longer be changed" in r.text, "P4: home currency locked after finalising " + r.text[:160])

print(f"p2189_a_docs: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
