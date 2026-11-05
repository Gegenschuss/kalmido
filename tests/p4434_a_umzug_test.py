#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.547.0 (#4434) API tests: the old receipts of the own documents into the office, once, with a preview and one undo for 30
days (docs/areamove.py). Invented companies and figures only; the e-invoices are written here as XML text.
freelancer-matrix: files
tenant-matrix: document
 - a person without an organisation with her personal office (the freelancer fixture): two e-invoices that lay in her documents
   before #4433 (uploaded without sort=1: never sorted); the preview lists both, the one with the tag "Steuer" preset to
   "stays", and changes nothing; the move of the chosen one sets it into the office; the hint is gone, the undo line there;
   the undo puts it back as it was; a second undo 409; an undo older than 30 days 409 and no longer offered
 - the tenant boundary: another person's id is never moved (409 "Nothing to move"), another person's undo 404, an agent 403;
   a person without an office: nothing listed, POST 409
 - an organisation's office (Alice, its admin): an old receipt in a folder of her own documents, shared with a person outside the
   organisation, and an e-invoice move into the organisation's documents (the share ends); the undo brings both back into
   her own documents, the receipt into its folder under its name, the share again
 - a member of the organisation who is no admin: no hint (why=admin), POST 403
usage: p4434_a_umzug_test.py <datadir>      (a fresh container; P4434A_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, FAILS, OKS, check, dbx, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(prefix="P4434A")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
MV = B + "/api/docs/office-move"


def ubl_inv(number, seller, vat_id):
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
    assert r.ok and r.json().get("ids"), r.text
    nid = r.json()["ids"][0]
    check(until(lambda: s.get(B + f"/api/docs/{nid}").json()["state"] == "done", 90), f"{name} is read")
    return nid


def row(nid):
    x = dbx("SELECT d.area, d.area_sort, d.ws, n.org_id, n.parent_id, n.name FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE d.node_id=?", (nid,))
    return tuple(x[0]) if x else None


def preview(s, **q):
    r = s.get(MV, params=q)
    assert r.ok, r.text
    return r.json()


def picks(j):
    return {x["id"]: x["pick"] for x in j.get("items") or []}


# ==== a person without an organisation, her personal office (freelancer-matrix: files)
FRIDA, Fr = freelancer(B, A)
r = Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Frida Grafik", "vat_id": "DE111222333"}})
check(r.ok, "setup: the personal office " + r.text[:160])
f1 = upload(Fr, "rechnung-papier.xml", ubl_inv("ER-2026-91", "Beispiel Papier GmbH", "DE123456789"))
f2 = upload(Fr, "rechnung-steuer.xml", ubl_inv("ER-2026-92", "Beispiel Kanzlei KG", "DE234567891"))
check(Fr.patch(B + f"/api/docs/{f2}", json={"tags": ["Steuer"]}).ok, "setup: f2 gets the tag Steuer")
check(row(f1)[:2] == ("", "") and row(f2)[:2] == ("", ""), f"setup: both lie unsorted in her documents {row(f1)} {row(f2)}")

j = preview(Fr, count="1")
check(j["n"] == 2 and j["office"] == "own" and not j["hidden"] and j["undo"] is None and "items" not in j, f"the hint: 2 receipts {j}")
before = (row(f1), row(f2))
j = preview(Fr)
check(picks(j) == {f1: "move", f2: "stay"}, f"the preview: f1 move, the tag Steuer stays {picks(j)}")
check(next(x for x in j["items"] if x["id"] == f2)["tax"] is True, "f2 is marked as tax")
check((row(f1), row(f2)) == before, f"#4434: the preview moves nothing {row(f1)} {row(f2)}")

# ---- the tenant boundary
G = freelancer(B, A, "gina")[1]
g1 = upload(G, "rechnung-gina.xml", ubl_inv("ER-2026-93", "Beispiel Licht AG", "DE345678912"))
r = Fr.post(MV, json={"ids": [g1]})
check(r.status_code == 409 and row(g1)[:2] == ("", ""), f"another person's document is never moved {r.status_code} {row(g1)}")
check(Fr.post(MV, json={"ids": "all"}).status_code == 400, "ids must be a list: 400")
r = Fr.post(B + "/api/agents", json={"name": "Umzieher"})
tok = (r.json().get("token") or "") if r.ok else ""
check(bool(tok), "setup: an agent token")
r = requests.post(MV, headers={"Authorization": "Bearer " + tok}, json={"ids": [f1]})
check(r.status_code in (401, 403), f"an agent never moves ({r.status_code})")
check(requests.get(MV, headers={"Authorization": "Bearer " + tok}).status_code in (401, 403), "an agent gets no preview")

# ---- the move, the hint, the undo
r = Fr.post(B + "/api/docs/office-move", json={"ids": [f1, f2]})  # the person may move the tax one as well: it is her click
check(r.ok and r.json()["moved"] == 2 and r.json()["id"], f"the move {r.status_code} {r.text[:200]}")
RUN = r.json()["id"]
check(row(f1)[:2] == ("office", "person") and row(f2)[:2] == ("office", "person"), f"both in the office {row(f1)} {row(f2)}")
r = Fr.get(B + "/api/docs", params={"ws": "all", "facets": "0", "area": "office"})
check(f1 in [d["id"] for d in r.json()["docs"]], "the office lists f1 now")
j = preview(Fr, count="1")
check(j["n"] == 0 and j["hidden"] and j["undo"] and j["undo"]["id"] == RUN and j["undo"]["n"] == 2, f"the hint gone, the undo line there {j}")
check(G.post(MV + f"/{RUN}/undo").status_code == 404, "another person's undo: 404 (tenant-matrix: document)")
r = Fr.post(B + f"/api/docs/office-move/{RUN}/undo")
check(r.ok and r.json()["back"] == 2 and not r.json()["stayed"], f"the undo {r.status_code} {r.text[:200]}")
check((row(f1), row(f2)) == before, f"#4434: both as before {row(f1)} {row(f2)}")
check(Fr.post(MV + f"/{RUN}/undo").status_code == 409, "a second undo: 409")
check(preview(Fr, count="1")["undo"] is None, "no undo line after the undo")

# ---- a receipt recorded since stays in the office at the undo
r = Fr.post(MV, json={"ids": [f1]})
RUN2 = r.json()["id"]
check(Fr.post(B + f"/api/docs/{f1}/receipt/einvoice").ok, "setup: f1 recorded as receipt in the office")
r = Fr.post(MV + f"/{RUN2}/undo")
check(r.ok and r.json()["back"] == 0 and r.json()["stayed"] == [f1] and row(f1)[0] == "office", f"a receipt recorded since stays {r.text[:160]} {row(f1)}")

# ---- the undo for 30 days only
r = Fr.post(MV, json={"ids": [f2]})
RUN3 = r.json()["id"]
dbx("UPDATE doc_office_moves SET created_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="seconds"), RUN3))
check(preview(Fr, count="1")["undo"] is None, "after 30 days no undo line")
r = Fr.post(MV + f"/{RUN3}/undo")
check(r.status_code == 409 and row(f2)[0] == "office", f"after 30 days: 409, it stays in the office {r.status_code} {row(f2)}")

r = Fr.post(B + "/api/docs/office-move/hide")
check(r.ok and preview(Fr, count="1")["hidden"], "the hint closed")

# ==== a person without an office
No = freelancer(B, A, "nora", features="files,docs")[1]
upload(No, "rechnung.xml", ubl_inv("ER-2026-94", "Beispiel Papier GmbH", "DE123456789"))
j = preview(No)
check(j["n"] == 0 and j["office"] is None and j["why"] == "none", f"no office: nothing listed {j}")
check(No.post(MV, json={"ids": [1]}).status_code == 409, "no office: POST 409")

# ==== an organisation's office (Alice, its admin)
A.patch(B + "/api/settings", json={"lang": "en", "features": "docs,files,office", "tour": "done", "workspace": "private"})
r = A.put(B + "/api/office/settings", json={"company_fields": {"name": "Alice Beratung", "vat_id": "DE555666777"}})
check(r.ok, "setup: Alice's personal office first " + r.text[:160])
a1 = upload(A, "beleg-alt.xml", ubl_inv("ER-2026-95", "Beispiel Druck GmbH", "DE456789123"))
check(A.post(B + f"/api/docs/{a1}/receipt/einvoice").ok, "setup: a1 an old receipt of her personal office")
a2 = upload(A, "rechnung-neu.xml", ubl_inv("ER-2026-96", "Beispiel Strom AG", "DE567891234"))
r = A.post(B + "/api/files/folders", json={"name": "Belege alt", "space": "private"})
FOLD = r.json()["id"]
check(A.patch(B + f"/api/files/nodes/{a1}", json={"parent_id": FOLD}).ok, "setup: a1 into the folder Belege alt")
GINA = dbx("SELECT id FROM users WHERE username='gina'")[0][0]
r = A.post(B + f"/api/files/nodes/{a1}/shares", json={"user_id": GINA, "role": "view"})
check(r.status_code in (200, 201), f"setup: a1 shared with Gina (outside the organisation) {r.status_code} {r.text[:160]}")
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.put(B + "/api/office/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "vat_id": "DE999888777"}}).ok, "setup: Alpha's office")
o1, o2 = row(a1), row(a2)
shares = lambda nid: dbx("SELECT user_id, role FROM fs_shares WHERE node_id=?", (nid,))  # noqa: E731
check(o1[3] is None and o1[4] == FOLD and shares(a1) == [(GINA, "view")], f"setup: a1 private in its folder, shared {o1} {shares(a1)}")
j = preview(A)
check(j["office"] == "org" and picks(j).get(a1) == "move" and picks(j).get(a2) == "move", f"the preview of Alpha's office {j}")
check(row(a1) == o1 and shares(a1) == [(GINA, "view")], "the preview moves nothing, the share stays")
r = A.post(MV, json={"ids": [a1, a2]})
check(r.ok and r.json()["moved"] == 2, f"the move into Alpha {r.status_code} {r.text[:200]}")
RA = r.json()["id"]
check(row(a1)[2:4] == (f"o{ORG}", ORG) and row(a2)[2:4] == (f"o{ORG}", ORG), f"both in Alpha's documents {row(a1)} {row(a2)}")
check(shares(a1) == [], "the share with a person outside Alpha ended")
check(G.get(B + f"/api/docs/{a1}").status_code in (403, 404), "Gina no longer sees a1")
r = A.post(MV + f"/{RA}/undo")
check(r.ok and r.json()["back"] == 2, f"the undo out of Alpha {r.status_code} {r.text[:200]}")
check(row(a1)[2:] == o1[2:] and row(a2)[2:] == o2[2:], f"#4434: both back, a1 into its folder under its name {row(a1)} {o1}")
check(shares(a1) == [(GINA, "view")], f"the share is back {shares(a1)}")
check(G.get(B + f"/api/docs/{a1}").ok, "Gina sees a1 again")

# ==== a member who is no admin of the organisation
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bert", "display_name": "Bert",
                                   "password": "password123", "email": "bert@example.com"})
check(r.ok, "setup: bert, a member of Alpha " + r.text[:160])
Be = kt.sess("bert")
Be.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "docs,files,office", "workspace": f"org:{ORG}"})
b1 = upload(Be, "rechnung-bert.xml", ubl_inv("ER-2026-97", "Beispiel Papier GmbH", "DE123456789"))
j = preview(Be)
check(j["n"] == 0 and j["why"] == "admin", f"a member: no hint {j}")
r = Be.post(MV, json={"ids": [b1]})
check(r.status_code == 403 and row(b1)[3] is None, f"a member: 403, nothing moved {r.status_code} {row(b1)}")

print(f"p4434_a_umzug: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
