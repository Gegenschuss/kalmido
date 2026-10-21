#!/usr/bin/env python3
"""2.153.0 API tests, part C (#2055): an incoming e-invoice in the documents of an office area becomes a receipt (on the
reader of 2.146, #2451). Invented companies and figures only; every e-invoice is written here as XML text.
freelancer-matrix: office  tenant-matrix: office
 - a person without an organisation (personal office): an XRechnung UBL .xml uploaded -> a receipt with the invoice's VAT
   rate; it shows in the receipts list with the mark e-invoice and its number, the CSV names number and VAT id
 - a UBL credit note: a receipt with a negative amount
 - an invoice whose seller is the own company (same VAT id): no receipt
 - a person without an office: the e-invoice stays a document, no receipt
 - a receipt taken away by hand stays away after "Recognise again"
usage: p2153_c_api_test.py <datadir>   (P2153C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import csv
import io
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
RL = "/api/office/books/receipts"
ALL = "from=2026-01-01&to=2026-12-31"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def ubl(number, seller, vat_id, credit=False):
    root, line, qty = ("CreditNote", "CreditNoteLine", "CreditedQuantity") if credit else ("Invoice", "InvoiceLine", "InvoicedQuantity")
    code = "" if credit else "<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ubl:{root} xmlns:ubl="urn:oasis:names:specification:ubl:schema:xsd:{root}-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID>
  <cbc:ID>{number}</cbc:ID><cbc:IssueDate>2026-03-05</cbc:IssueDate>{code}
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>{seller}</cbc:Name></cac:PartyName>
    <cac:PartyTaxScheme><cbc:CompanyID>{vat_id}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>{seller}</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Kunde Beispiel</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">19.00</cbc:TaxAmount>
    <cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">100.00</cbc:TaxableAmount><cbc:TaxAmount currencyID="EUR">19.00</cbc:TaxAmount>
      <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount currencyID="EUR">119.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">119.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:{line}><cbc:ID>1</cbc:ID><cbc:{qty} unitCode="C62">1</cbc:{qty}>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Papier</cbc:Name>
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">100.00</cbc:PriceAmount></cac:Price></cac:{line}>
</ubl:{root}>
""".encode()


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def upload(s, name, data):
    r = s.post(B + "/api/docs", data={"ws": "private"}, files=[("files", (name, data, "application/xml"))])
    assert r.ok, r.text
    return r.json()["ids"][0]


def done(s, nid, secs=90):
    return until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")), secs)


def rc(s, nid):
    r = s.get(B + f"/api/docs/{nid}/receipt")
    assert r.ok, r.text
    return r.json()["receipt"]


if os.environ.get("P2153C_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})

# ---- a person without an organisation, with the personal office (her own company: VAT id DE111222333)
FID, Fr = freelancer(B, A, "frida")  # freelancer-matrix: office
r = Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Frida Grafik", "vat_id": "DE111222333"}})
check(r.ok, "the personal office: own company " + r.text[:160])
n1 = upload(Fr, "rechnung.xml", ubl("ER-2026-17", "Beispiel Papier GmbH", "DE123456789"))
d1 = done(Fr, n1)
check(d1 and d1["method"] == "e-invoice" and d1["amount"] == "119.00", f"e-invoice read {d1 and (d1['method'], d1['amount'])}")
r1 = rc(Fr, n1)
check(r1["is_receipt"] and r1["vat_pct"] == "19", f"e-invoice in the office's documents: a receipt with 19 % {r1}")
j = Fr.get(B + RL + "?" + ALL).json()
row = next((x for x in j["rows"] if x["node_id"] == n1), None)
check(row and row["einvoice"] is True and row["number"] == "ER-2026-17" and row["amount"] == "119.00" and row["vat"] == "19.00",
      f"receipts list: the e-invoice with its number {row}")
t = Fr.get(B + RL + ".csv?" + ALL).content.decode("utf-8").lstrip("﻿")
rows = list(csv.reader(io.StringIO(t), delimiter=";"))
b = {r_[-1]: dict(zip(rows[0], r_)) for r_ in rows[1:]}.get(str(n1)) or {}
check(b.get("Invoice number") == "ER-2026-17" and b.get("VAT ID") == "DE123456789" and b.get("E-invoice") == "yes",
      f"CSV: number and VAT id of the e-invoice {b}")

# ---- a credit note: a negative receipt
n2 = upload(Fr, "gutschrift.xml", ubl("GS-2026-3", "Beispiel Papier GmbH", "DE123456789", credit=True))
d2 = done(Fr, n2)
check(d2 and d2["amount"] == "-119.00", f"credit note: amount negative {d2 and d2['amount']}")
check(rc(Fr, n2)["is_receipt"], "credit note: a receipt")
j = Fr.get(B + RL + "?" + ALL).json()
check(j["total"]["gross"] == "0.00" and j["total"]["count"] == 2, f"receipts list: invoice and credit note add up to 0 {j['total']}")

# ---- the own invoice (same VAT id as the own company): no receipt
n3 = upload(Fr, "eigene.xml", ubl("RE-2026-1", "Frida Grafik", "DE 111 222 333"))
check(done(Fr, n3) is not None and not rc(Fr, n3)["is_receipt"], "own invoice: no receipt")

# ---- taken away by hand: stays away after a new recognition run
assert Fr.put(B + f"/api/docs/{n1}/receipt", json={"category": "", "vat_pct": None, "project_id": None}).ok
check(not rc(Fr, n1)["is_receipt"], "receipt taken away by hand")
r = Fr.post(B + f"/api/docs/{n1}/redo")
check(r.ok and done(Fr, n1) is not None and not rc(Fr, n1)["is_receipt"], f"recognised again: no new receipt ({r.status_code})")

# ---- a person without the office module: the e-invoice stays a document
r = A.post(B + "/api/users", json={"username": "gina", "display_name": "Gina", "password": "password123", "email": "gina@example.com", "orgs": []})
assert r.ok, r.text
G = requests.Session()
G.headers.update(H)
assert G.post(B + "/api/auth/login", json={"username": "gina", "password": "password123"}).ok
G.patch(B + "/api/settings", json={"lang": "en", "features": "docs,files", "tour": "done"})
n4 = upload(G, "rechnung.xml", ubl("ER-2026-18", "Beispiel Papier GmbH", "DE123456789"))
d4 = done(G, n4)
check(d4 and d4["method"] == "e-invoice" and not rc(G, n4)["is_receipt"], "no office: the e-invoice is no receipt")
check(n1 not in [x["node_id"] for x in (G.get(B + RL + "?" + ALL).json().get("rows") or [])], "another person sees no receipt of Frida")

print(f"p2153_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
