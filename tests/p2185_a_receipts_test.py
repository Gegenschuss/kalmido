#!/usr/bin/env python3
"""2.185.0 API tests, part A (#2583): possible duplicates marked in the receipts lists of the bookkeeping; an e-invoice read
before (office switched on later, moved into an office) becomes a receipt afterwards. Invented companies and figures only;
every e-invoice is written here as XML text.
freelancer-matrix: office, files  tenant-matrix: office, receipt
 - a person without an organisation (personal office): two e-invoices with the same number -> the newer one carries dup in
   the receipts list (all months) and the list of the month, both still count; "No duplicate" takes the mark away; an older
   document the person does not see marks nothing
 - an e-invoice uploaded without the office module: no receipt and no offer; office switched on: the offer, "Recognise
   again" keeps the offer (2.237.0, #2865), POST /api/docs/<id>/receipt/einvoice makes it (409 the second time, 404 for others,
   400 for no e-invoice), a receipt taken away again stays away after a new run
 - an e-invoice moved from the private space into the documents of an organisation's office is offered there (2.237.0)
usage: p2185_a_receipts_test.py <datadir>   (P2185A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, until  # 2.192.0 (#2514): shared helpers (tests/kt.py)
RL = "/api/office/books/receipts"
ALL = "from=2026-01-01&to=2026-12-31"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def ubl(number, seller, vat_id, item="Papier"):
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
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">7.00</cbc:TaxAmount>
    <cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">100.00</cbc:TaxableAmount><cbc:TaxAmount currencyID="EUR">7.00</cbc:TaxAmount>
      <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>7</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount currencyID="EUR">107.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">107.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="C62">1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>{item}</cbc:Name>
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>7</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">100.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
</ubl:Invoice>
""".encode()


def upload(s, name, data, mime="application/xml"):
    r = s.post(B + "/api/docs", data={"ws": "private"}, files=[("files", (name, data, mime))])
    assert r.ok, r.text
    return r.json()["ids"][0]


def done(s, nid, secs=90):
    return until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")), secs)


def redo(s, nid):
    # the run sets the state to "wait" at once; wait for the new "done"
    r = s.post(B + f"/api/docs/{nid}/redo")
    time.sleep(1)
    return r.ok and done(s, nid) is not None


def rcs(s, nid):
    r = s.get(B + f"/api/docs/{nid}/receipt")
    assert r.ok, r.text
    return r.json()


def take(s, nid):
    return s.post(B + f"/api/docs/{nid}/receipt/einvoice")


def rows(s, q=ALL):
    return s.get(B + RL + "?" + q).json().get("rows") or []


if os.environ.get("P2185A_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]

# ---------------------------------------------------------------- 1. possible duplicates in the receipts lists
FID, Fr = freelancer(B, A, "frida")  # freelancer-matrix: office
r = Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Frida Grafik", "vat_id": "DE111222333"}})
check(r.ok, "the personal office: own company " + r.text[:160])
e1 = upload(Fr, "rechnung.xml", ubl("ER-2026-41", "Beispiel Druck GmbH", "DE123456789"))
check(done(Fr, e1) is not None, "first e-invoice read")
e2 = upload(Fr, "rechnung-mail.xml", ubl("ER-2026-41", "Beispiel Druck GmbH", "DE123456789", item="Papier (Kopie)"))
d2 = done(Fr, e2)
check(d2 and (d2.get("duplicate_of") or {}).get("id") == e1, f"the second one is a possible duplicate of the first {d2 and d2.get('duplicate_of')}")
check(take(Fr, e1).ok and take(Fr, e2).ok, "both taken over")  # 2.237.0 (#2865): no receipt by itself any more
check(rcs(Fr, e1)["receipt"]["is_receipt"] and rcs(Fr, e2)["receipt"]["is_receipt"], "both are receipts")
j = Fr.get(B + RL + "?" + ALL).json()
by = {x["node_id"]: x for x in j["rows"]}
check(by.get(e2, {}).get("dup") is True and by.get(e1, {}).get("dup") is False, f"receipts list: dup on the newer one only {[(k, v.get('dup')) for k, v in by.items()]}")
check(j["total"]["count"] == 2 and j["total"]["gross"] == "214.00", f"the possible duplicate still counts (no new decision) {j['total']}")
m = Fr.get(B + "/api/office/books?month=2026-03&year=2026").json()
mb = {x["node_id"]: x for x in m.get("receipts") or []}
check(mb.get(e2, {}).get("dup") is True and mb.get(e1, {}).get("dup") is False, f"the month's list: dup on the newer one {[(k, v.get('dup')) for k, v in mb.items()]}")
r = Fr.post(B + f"/api/docs/{e2}/extracted", json={"do": "nodup"})
check(r.ok, f"No duplicate ({r.status_code})")
check(all(x.get("dup") is False for x in rows(Fr)), "after No duplicate: no mark in the list")
r = Fr.post(B + f"/api/docs/{e2}/extracted", json={"do": "dup"})
check(r.ok and any(x.get("dup") for x in rows(Fr) if x["node_id"] == e2), "its undo: the mark is back")

# ---------------------------------------------------------------- 2. an e-invoice read before the office was on
r = A.post(B + "/api/users", json={"username": "gina", "display_name": "Gina", "password": "password123", "email": "gina@example.com", "orgs": []})
assert r.ok, r.text
G = requests.Session()
G.headers.update(H)
assert G.post(B + "/api/auth/login", json={"username": "gina", "password": "password123"}).ok
G.patch(B + "/api/settings", json={"lang": "en", "features": "docs,files", "tour": "done"})  # freelancer-matrix: files
g1 = upload(G, "rechnung.xml", ubl("ER-2026-51", "Beispiel Licht KG", "DE234567891"))
g2 = upload(G, "rechnung-2.xml", ubl("ER-2026-52", "Beispiel Licht KG", "DE234567891"))
g3 = upload(G, "notiz.txt", b"Nur eine Notiz ohne Rechnung", "text/plain")
for n in (g1, g2, g3):
    check(done(G, n) is not None, f"document {n} read")
x = rcs(G, g1)
check(not x["receipt"]["is_receipt"] and x.get("einvoice_offer") is False, f"no office: no receipt, no offer {x.get('einvoice_offer')}")
check(take(G, g2).status_code == 400, "no office: taking over refused (400)")

# the tenant boundary (still no office): another person's older document marks nothing in Frida's list
dbx("UPDATE doc_meta SET dup_of=?, dup_ok=0 WHERE node_id=?", (g1, e2), write=True)
check(all(x.get("dup") is False for x in rows(Fr)), "an older document of another person marks nothing (tenant-matrix: office)")
check("duplicate_of" not in Fr.get(B + f"/api/docs/{e2}").json(), "nor in the document sheet")

r = G.patch(B + "/api/settings", json={"features": "docs,files,office"})
check(r.ok, "Gina switches the office on")
check(G.get(B + "/api/office/books").ok, "and opens it (the personal office area is made on the first visit)")
x = rcs(G, g1)
check(not x["receipt"]["is_receipt"] and x.get("einvoice_offer") is True, f"office on: the offer {x.get('einvoice_offer')}")
check(rcs(G, g3).get("einvoice_offer") is False, "no offer on a document that is no e-invoice")
check(take(G, g3).status_code == 400, "no e-invoice: 400")

# 2.237.0 (#2865): a new recognition run keeps the offer (no receipt by itself); taken over once
check(redo(G, g1), "g1 recognised again")
x = rcs(G, g1)
check(not x["receipt"]["is_receipt"] and x.get("einvoice_offer") is True, f"recognised again: still the offer {x['receipt']}")
check(take(G, g1).ok, "g1 taken over")
x = rcs(G, g1)
check(x["receipt"]["is_receipt"] and x["receipt"]["vat_pct"] == "7" and x.get("einvoice_offer") is False,
      f"taken over: a receipt with the invoice's VAT rate {x['receipt']}")
check(redo(G, g1), "g1 recognised a third time")
check([y["node_id"] for y in rows(G)].count(g1) == 1, "never two receipts of one document")

# the button (POST /api/docs/<id>/receipt/einvoice)
check(take(Fr, g2).status_code == 404, "another person: 404 (tenant-matrix: receipt)")
check(take(A, g2).status_code == 404, "the admin of the server: 404 on Gina's private document")
r = take(G, g2)
check(r.ok and r.json()["receipt"]["is_receipt"] and r.json()["receipt"]["vat_pct"] == "7" and r.json().get("einvoice_offer") is False,
      f"taken over as receipt ({r.status_code} {r.text[:200]})")
check(take(G, g2).status_code == 409, "a second time: 409, no second receipt")
check(sorted(y["node_id"] for y in rows(G)) == sorted([g1, g2]), f"Gina's receipts list {[y['node_id'] for y in rows(G)]}")

# taken away by hand (the undo): stays away after a new run, the offer comes back
assert G.put(B + f"/api/docs/{g2}/receipt", json={"category": "", "vat_pct": None, "project_id": None}).ok
check(not rcs(G, g2)["receipt"]["is_receipt"], "receipt taken away (undo)")
check(redo(G, g2) and not rcs(G, g2)["receipt"]["is_receipt"], "recognised again: stays no receipt")
check(rcs(G, g2).get("einvoice_offer") is True, "the offer is there again (a person may take it over again)")

# ---------------------------------------------------------------- 3. moved into the documents of an organisation's office
A.patch(B + "/api/settings", json={"lang": "en", "features": "docs,files", "tour": "done"})
a1 = upload(A, "rechnung.xml", ubl("ER-2026-61", "Beispiel Werkzeug AG", "DE345678912"))
check(done(A, a1) is not None and not rcs(A, a1)["receipt"]["is_receipt"], "alice without office: no receipt")
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"features": "docs,files,office", "workspace": f"org:{ORG}"})
r = A.put(B + "/api/office/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "vat_id": "DE999888777"}})
check(r.ok, "Alpha's office set up " + r.text[:160])
r = A.post(B + "/api/files/move-space", json={"ids": [a1], "to": f"org:{ORG}", "parent": "docs"})
check(r.ok, f"moved into Alpha ({r.status_code} {r.text[:200]})")
x = rcs(A, a1)
# 2.237.0 (#2865): moved into the office it is an offer there, a receipt once taken over
check(not x["receipt"]["is_receipt"] and x.get("einvoice_offer") is True, f"moved into the office: the offer there {x['receipt']}")
check(take(A, a1).ok, "taken over in Alpha")
x = rcs(A, a1)
check(x["receipt"]["is_receipt"] and x["receipt"]["vat_pct"] == "7", f"moved into the office: a receipt there {x['receipt']}")
check(a1 in [y["node_id"] for y in rows(A)], "in Alpha's receipts list")
check(take(G, a1).status_code == 404, "another person: 404 on Alpha's document")

print(f"p2185_a_receipts: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
