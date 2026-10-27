#!/usr/bin/env python3
"""2.237.0 C API tests (#2865): an incoming e-invoice is a receipt suggestion, no booked receipt; scan inbox keys run out
and go with a password reset / change. Invented companies and figures only; every e-invoice is written here as XML text.
freelancer-matrix: office, files
 - a person without an organisation (personal office): an XRechnung uploaded by hand and one through a scan inbox (no
   person) -> no receipt, no VAT rate, the offer with the invoice's values in the document's receipt section and in the
   office books (einvoices); deleting it for good works (no retention lock); Take over books it with 19 % (409 the second
   time), it leaves the offers list; an own invoice is never offered
 - the receipt sheet's save (keep) also makes it a receipt (the explicit step of the receipts page)
 - a scan inbox key gets an expiry date one year ahead (listed with expired false); past that date the upload answers 401
 - a password change revokes the person's scan inbox keys (401), an ordinary API token stays; an admin's password reset
   revokes them too
usage: p2237_c_einvoice_test.py <datadir>      (a fresh container; P2237C_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

V = B + "/api/v1"
kt.fresh(prefix="P2237C")
A = kt.setup()


def ubl(number, seller, vat_id):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ubl:Invoice xmlns:ubl="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID>
  <cbc:ID>{number}</cbc:ID><cbc:IssueDate>2026-03-05</cbc:IssueDate><cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
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
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="C62">1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Papier</cbc:Name>
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">100.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
</ubl:Invoice>
""".encode()


def upload(s, name, data):
    r = s.post(B + "/api/docs", data={"ws": "private"}, files=[("files", (name, data, "application/xml"))])
    assert r.ok, r.text
    return r.json()["ids"][0]


def done(s, nid, secs=90):
    return kt.until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")), secs)


def rcs(s, nid):
    r = s.get(B + f"/api/docs/{nid}/receipt")
    assert r.ok, r.text
    return r.json()


def take(s, nid):
    return s.post(B + f"/api/docs/{nid}/receipt/einvoice")


def offers(s):
    return {x["node_id"]: x for x in s.get(B + "/api/office/books?month=2026-03&year=2026").json().get("einvoices") or []}


def booked(nid):
    return kt.dbx("SELECT vat_pct FROM rc_receipts WHERE node_id=?", (nid,))


def bearer(tok):
    return {"Authorization": "Bearer " + tok}


def scan_key(s, name):
    r = s.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": name})
    assert r.status_code == 201, r.text
    raw = r.json()["code"][len("kalmido-scan:1:"):]
    return r.json()["id"], json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))["key"]


def scan_up(tok, name, data):
    return requests.post(V + "/documents", headers=bearer(tok), files={"file": (name, data, "application/xml")})


# ==== a person without an organisation, her personal office (freelancer-matrix: office)
FRIDA, Fr = freelancer(B, A)
r = Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Frida Grafik", "vat_id": "DE111222333"}})
check(r.ok, "setup: the personal office, own company " + r.text[:160])

# ---- uploaded by hand: a suggestion, no booked receipt
n1 = upload(Fr, "rechnung.xml", ubl("ER-2026-71", "Beispiel Papier GmbH", "DE123456789"))
d1 = done(Fr, n1)
check(d1 and d1["method"] == "e-invoice" and d1["amount"] == "119.00", f"the e-invoice is read {d1 and (d1['method'], d1['amount'])}")
x = rcs(Fr, n1)
check(not x["receipt"]["is_receipt"] and x["receipt"]["vat_pct"] is None and x.get("einvoice_offer") is True,
      f"#2865: no receipt, no VAT rate, the offer {x['receipt']} {x.get('einvoice_offer')}")
check(booked(n1) == [], "#2865: no row in rc_receipts")
check((d1.get("extracted") or {}).get("vat_pct") == "19" and (d1.get("extracted") or {}).get("supplier") == "Beispiel Papier GmbH",
      f"the recognised values stay as the suggestion {d1.get('extracted')}")
o = offers(Fr).get(n1) or {}
check(o.get("vat_pct") == "19" and o.get("amount") == "119.00" and o.get("supplier") == "Beispiel Papier GmbH" and o.get("date") == "2026-03-05",
      f"#2865: the office books list it under einvoices {o}")
check(n1 not in [y["node_id"] for y in Fr.get(B + "/api/office/books?month=2026-03&year=2026").json().get("receipts") or []],
      "not among the receipts of the month")

# ---- an own invoice is never offered
n0 = upload(Fr, "eigene.xml", ubl("RE-2026-9", "Frida Grafik", "DE 111 222 333"))
check(done(Fr, n0) is not None and n0 not in offers(Fr) and rcs(Fr, n0).get("einvoice_offer") is False, "own invoice: no offer")

# ---- through a scan inbox (no person behind the upload): a suggestion too, and deletable for good
K1ID, K1 = scan_key(Fr, "Scanner")
r = scan_up(K1, "scan-rechnung.xml", ubl("ER-2026-72", "Beispiel Licht KG", "DE234567891"))
check(r.status_code == 201, f"scan inbox upload {r.status_code} {r.text[:200]}")
n2 = r.json().get("id")
check(done(Fr, n2) is not None and booked(n2) == [] and rcs(Fr, n2).get("einvoice_offer") is True and n2 in offers(Fr),
      "#2865: the scanned e-invoice is a suggestion, no receipt")
assert Fr.delete(B + f"/api/files/nodes/{n2}").ok
r = Fr.delete(B + f"/api/files/nodes/{n2}?purge=1")
# 2.355.0 (#2845): an e-invoice received into the office is kept from its arrival (decision of 23.10.2026), taken over or not
check(r.status_code == 409 and "Kept by law until" in r.text, f"#2845: the unconfirmed e-invoice goes into the trash, not deleted for good {r.status_code} {r.text[:200]}")
check(n2 not in offers(Fr), "gone from the offers (in the trash)")

# ---- Take over: booked like before, once
r = take(Fr, n1)
check(r.ok and r.json()["receipt"]["is_receipt"] and r.json()["receipt"]["vat_pct"] == "19" and r.json().get("einvoice_offer") is False,
      f"Take over: a receipt with the invoice's 19 % ({r.status_code} {r.text[:200]})")
check(booked(n1) == [("19",)], f"rc_receipts has the rate {booked(n1)}")
check(take(Fr, n1).status_code == 409, "a second time: 409")
check(n1 not in offers(Fr) and n1 in [y["node_id"] for y in Fr.get(B + "/api/office/books?month=2026-03&year=2026").json().get("receipts") or []],
      "it left the offers and is a receipt of the month")
r = Fr.delete(B + f"/api/files/nodes/{n1}")
r = Fr.delete(B + f"/api/files/nodes/{n1}?purge=1")
check(r.status_code == 409, f"the booked receipt is kept like every booked one (409) {r.status_code}")
Fr.post(B + f"/api/files/nodes/{n1}/restore")

# ---- the receipt sheet's save (the explicit step on the receipts page) books it too
n3 = upload(Fr, "rechnung-3.xml", ubl("ER-2026-73", "Beispiel Werkzeug AG", "DE345678912"))
check(done(Fr, n3) is not None and booked(n3) == [], "a third e-invoice: no receipt by itself")
r = Fr.put(B + f"/api/docs/{n3}/receipt", json={"category": "Material", "vat_pct": "19", "project_id": None, "keep": True})
check(r.ok and r.json()["receipt"]["is_receipt"] and booked(n3) == [("19",)] and n3 not in offers(Fr), f"saved in the sheet: a receipt {r.text[:200]}")

# ==== scan inbox keys: one year, then 401
k = next((y for y in Fr.get(B + "/api/docs/scan-keys?ws=private").json().get("keys") or [] if y["id"] == K1ID), {})
exp = k.get("expires_at") or ""
try:
    days = (datetime.fromisoformat(exp.replace("Z", "+00:00")) - datetime.now(timezone.utc)).days
except ValueError:
    days = -1
check(363 <= days <= 366 and k.get("expired") is False, f"#2865: the scan key runs out in a year {exp} {k.get('expired')}")
K2ID, K2 = scan_key(Fr, "Alt")
past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
kt.dbx("UPDATE api_tokens SET expires_at=? WHERE id=?", (past, K2ID))
r = scan_up(K2, "spaet.xml", ubl("ER-2026-74", "Beispiel Licht KG", "DE234567891"))
check(r.status_code == 401, f"#2865: past its date the key answers 401 {r.status_code}")
check(next((y for y in Fr.get(B + "/api/docs/scan-keys?ws=private").json()["keys"] if y["id"] == K2ID), {}).get("expired") is True,
      "listed as expired")
# a key of before 2.237 (no expires_at) runs out a year after its creation; a younger one still works
K4ID, K4 = scan_key(Fr, "Vor 2.237 alt")
K5ID, K5 = scan_key(Fr, "Vor 2.237 jung")
old = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
kt.dbx("UPDATE api_tokens SET expires_at=NULL, created_at=? WHERE id=?", (old, K4ID))
kt.dbx("UPDATE api_tokens SET expires_at=NULL WHERE id=?", (K5ID,))
check(requests.get(V + "/documents/upload-target", headers=bearer(K4)).status_code == 401, "#2865: an old key without expiry, older than a year: 401")
check(requests.get(V + "/documents/upload-target", headers=bearer(K5)).ok, "#2865: an old key without expiry, younger than a year: works")
check(next((y for y in Fr.get(B + "/api/docs/scan-keys?ws=private").json()["keys"] if y["id"] == K4ID), {}).get("expired") is True,
      "the old key is listed as expired")

# ==== a password change revokes the scan keys, an ordinary API token stays
r = Fr.post(B + "/api/me/tokens", json={"name": "Skript", "scopes": ["read"]})
check(r.ok, f"setup: an ordinary token {r.status_code} {r.text[:160]}")
TOK = (r.json().get("token") or "") if r.ok else ""
check(requests.get(V + "/documents/upload-target", headers=bearer(K1)).ok, "the scan key works before")
r = Fr.patch(B + "/api/me", json={"password": "password456", "current_password": kt.PASSWORD})
check(r.ok, f"frida changes her password {r.status_code} {r.text[:160]}")
check(requests.get(V + "/documents/upload-target", headers=bearer(K1)).status_code == 401, "#2865: after the change the scan key is revoked (401)")
check(kt.dbx("SELECT id FROM api_tokens WHERE id IN (?,?)", (K1ID, K2ID)) == [], "both scan keys are gone")
check(not TOK or requests.get(V + "/me", headers=bearer(TOK)).ok, "the ordinary API token stays")
check(Fr.get(B + "/api/docs/scan-keys?ws=private").json().get("keys") == [], "no scan key listed any more")

# ---- an admin's password reset revokes them too
Fr = sess("frida", "password456")
K3ID, K3 = scan_key(Fr, "Neu")
check(requests.get(V + "/documents/upload-target", headers=bearer(K3)).ok, "a new scan key works")
r = A.patch(B + f"/api/users/{FRIDA}", json={"password": "password789"})
check(r.ok, f"the admin resets frida's password {r.status_code} {r.text[:160]}")
check(requests.get(V + "/documents/upload-target", headers=bearer(K3)).status_code == 401, "#2865: after the admin's reset 401")

sys.exit(kt.done("p2237_c_einvoice"))
