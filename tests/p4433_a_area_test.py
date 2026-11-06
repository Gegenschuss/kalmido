#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.522.0 (#4433) API tests: the office and the private file store apart; the general input sorts. Invented companies and
figures only; the e-invoice is written here as XML text, the letters as plain text.
freelancer-matrix: files
 - a person without an organisation with her personal office (the freelancer fixture): the general upload (sort=1) of an
   e-invoice lands in the office (area office, "Wrong area" offered, in ?area=office and "New in the office", not in the
   file store's ?area=private), a tax notice and a letter with only a gross amount (the doubt) stay private; nothing becomes
   a receipt by itself
 - "Wrong area": one click back into the private space, the undo puts it into the office again (sorted again: "Wrong area"
   offered again); "Move to office" of a private document; a receipt is never moved (409)
 - bound inputs are never sorted: a scan inbox upload and an upload without sort=1 keep area_sort empty, no "Wrong area"
 - another person: 404 on the document (tenant-matrix: document); an agent token: 403
 - a person without an office: sort=1 changes nothing (no area, the file store unfiltered)
 - a person whose office is an organisation's: the sorted invoice moves into the organisation's documents, the notice stays
   private; "Wrong area" moves it back into the private space, the undo into the organisation again
 - 2.576.0 (#4487): a mail to the person's own document address is the general input too: its e-invoice lands in the office,
   a mail with a tax notice stays private (the IMAP stub of the container, tests/stub_mail.py)
usage: p4433_a_area_test.py <datadir>      (a fresh container with the stub mailbox; P4433A_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import base64
import email.message
import json
import os
import subprocess
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, FAILS, OKS, check, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

V = B + "/api/v1"
# 2.576.0 (#4487): the stub mailbox (IMAP 127.0.0.1:1143 inside the container) for the mail to the own document address
MAILENV = {"KALMIDO_MAIL_ADDRESS": "tasks@example.test", "KALMIDO_IMAP_HOST": "127.0.0.1", "KALMIDO_IMAP_PORT": "1143", "KALMIDO_IMAP_SSL": "0",
           "KALMIDO_IMAP_USER": "kalmido", "KALMIDO_IMAP_PASSWORD": "secret", "KALMIDO_IMAP_INTERVAL": "600"}
if not kt.nostart("P4433A"):
    subprocess.run(["rm", "-rf", kt.DATA])
    os.makedirs(os.path.join(kt.DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(kt.N, "stub_mail.py"), kt.DATA])
    kt.fresh(env=MAILENV, prefix="P4433A", keep=True)
    subprocess.run(["docker", "exec", "-d", kt.CT, "python", "/data/stub_mail.py"])
os.makedirs(os.path.join(kt.DATA, "mail", "in"), exist_ok=True)
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]


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


NOTICE = ("Stadt Beispielhausen\nSteueramt\n\nBescheid über die Hundesteuer 2026\n\nSehr geehrte Frau Beispiel,\n"
          "für das Jahr 2026 wird die Hundesteuer festgesetzt. Dieser Bescheid ergeht nach der Satzung der Stadt.\n").encode()
GROSS_ONLY = ("Verein Beispielsport e.V.\n\nTeilnahme Sommerfest\n\nGesamtbetrag 84,71 EUR\nVielen Dank für die Teilnahme.\n").encode()


def upload(s, name, data, mime, sort=True, ws="private"):
    form = {"ws": ws, **({"sort": "1"} if sort else {})}
    r = s.post(B + "/api/docs", data=form, files=[("files", (name, data, mime))])
    assert r.ok and r.json().get("ids"), r.text
    return r.json()["ids"][0]


def row(nid):
    x = kt.dbx("SELECT area, area_sort, ws FROM doc_meta WHERE node_id=?", (nid,))
    return tuple(x[0]) if x else None


def settled(s, nid, secs=90):
    """The document once recognised and no longer waiting for the sorting -> its JSON (GET /api/docs/<id>)."""
    def one():
        # the sorting first, then the sheet: read the other way round, a sheet fetched while the queue still moved the
        # document (area_sort 'sorting') came back with the old state (org_id None, private) next to the finished row
        if (row(nid) or ("", "pending"))[1] in ("pending", "sorting"):  # review 2.522: + 'sorting' (claimed by the queue)
            return None
        r = s.get(B + f"/api/docs/{nid}")
        if not r.ok or r.json()["state"] not in ("done", "failed"):
            return None
        return r.json() if (row(nid) or ("", "pending"))[1] not in ("pending", "sorting") else None
    return until(one, secs)


def ids(s, **q):
    r = s.get(B + "/api/docs", params={"ws": "all", "facets": "0", "limit": "200", **q})
    assert r.ok, r.text
    return [d["id"] for d in r.json()["docs"]]


def area(s, nid, to, undo=False):
    return s.post(B + f"/api/docs/{nid}/area", json={"to": to, **({"undo": True} if undo else {})})


def scan_key(s, name):
    r = s.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": name})
    assert r.status_code == 201, r.text
    raw = r.json()["code"][len("kalmido-scan:1:"):]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))["key"]


# ==== a person without an organisation, her personal office (freelancer-matrix: files)
FRIDA, Fr = freelancer(B, A)
r = Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Frida Grafik", "vat_id": "DE111222333"}})
check(r.ok, "setup: the personal office " + r.text[:160])

inv = upload(Fr, "rechnung.xml", ubl("ER-2026-81", "Beispiel Papier GmbH", "DE123456789"), "application/xml")
d = settled(Fr, inv)
check(d and d["method"] == "e-invoice", f"the e-invoice is read {d and d['method']}")
check(row(inv)[:2] == ("office", "auto"), f"#4433: the invoice is sorted into the office {row(inv)}")
check(d and (d.get("area") or {}).get("area") == "office" and d["area"].get("wrong") is True and d["area"].get("office") == "own",
      f"the sheet: office, 'Wrong area' offered {d and d.get('area')}")
check(not kt.dbx("SELECT 1 FROM rc_receipts WHERE node_id=?", (inv,)), "#2865: sorted, never booked by itself")
check(inv in ids(Fr, area="office") and inv in ids(Fr, area="office", unbooked="1"), "in the office's list and 'New in the office'")
check(inv not in ids(Fr, area="private"), "the file store (?area=private) shows no office document")
check(inv in ids(Fr), "without the area filter the list is as before")

notice = upload(Fr, "bescheid.txt", NOTICE, "text/plain")
d = settled(Fr, notice)
check(d and row(notice)[:2] == ("private", "auto") and (d.get("area") or {}).get("area") == "private" and d["area"].get("wrong") is True,
      f"#4433: a tax notice stays private {row(notice)} {d and d.get('area')}")
check(notice in ids(Fr, area="private") and notice not in ids(Fr, area="office"), "the notice in the file store, not in the office")

doubt = upload(Fr, "sommerfest.txt", GROSS_ONLY, "text/plain")
check(settled(Fr, doubt) and row(doubt)[:2] == ("private", "auto"), f"#4433: only a gross amount (the doubt): private {row(doubt)}")

# ---- "Wrong area" with its undo, "Move to office"
r = area(Fr, inv, "private")
check(r.ok and r.json()["area"] == "private" and r.json()["area_sort"] == "person", f"'Wrong area': back to private {r.status_code} {r.text[:200]}")
check(row(inv)[:2] == ("private", "person") and inv in ids(Fr, area="private"), f"in the file store now {row(inv)}")
d = Fr.get(B + f"/api/docs/{inv}").json()
check(d["area"]["area"] == "private" and d["area"]["wrong"] is False, f"a person's choice: no 'Wrong area' any more {d['area']}")
r = area(Fr, inv, "office", undo=True)
check(r.ok and row(inv)[:2] == ("office", "auto") and Fr.get(B + f"/api/docs/{inv}").json()["area"]["wrong"] is True,
      f"the undo: in the office again, sorted as before {row(inv)}")
r = area(Fr, notice, "office")
check(r.ok and row(notice)[:2] == ("office", "person") and notice in ids(Fr, area="office"), f"'Move to office' {row(notice)} {r.text[:160]}")
check(area(Fr, notice, "private", undo=True).ok and row(notice)[:2] == ("private", "auto"), f"its undo {row(notice)}")
check(area(Fr, inv, "elsewhere").status_code == 400, "an unknown area: 400")

# ---- a receipt is never moved; recorded, it leaves "New in the office"
r = Fr.post(B + f"/api/docs/{inv}/receipt/einvoice")
check(r.ok and r.json()["receipt"]["is_receipt"], f"a person takes it over as receipt {r.status_code} {r.text[:160]}")
check(inv in ids(Fr, area="office") and inv not in ids(Fr, area="office", unbooked="1"), "a receipt: in the office, no longer new")
check(area(Fr, inv, "private").status_code == 409, "a receipt is not moved (409)")
check(Fr.get(B + f"/api/docs/{inv}").json()["area"]["wrong"] is False, "no 'Wrong area' at a receipt")

# ---- bound inputs: never sorted
plain = upload(Fr, "rechnung-2.xml", ubl("ER-2026-82", "Beispiel Licht KG", "DE234567891"), "application/xml", sort=False)
d = settled(Fr, plain)
check(d and row(plain)[:2] == ("", "") and d["area"]["area"] == "private" and d["area"]["wrong"] is False,
      f"an upload without sort=1 (an API client): not sorted {row(plain)} {d and d.get('area')}")
KEY = scan_key(Fr, "Scanner")
r = requests.post(V + "/documents", headers={"Authorization": "Bearer " + KEY},
                  files={"file": ("scan-rechnung.xml", ubl("ER-2026-83", "Beispiel Werkzeug AG", "DE345678912"), "application/xml")})
check(r.status_code == 201, f"scan inbox upload {r.status_code} {r.text[:160]}")
scan = r.json().get("id")
check(settled(Fr, scan) and row(scan)[1] == "", f"#4433: a bound scan inbox lands as sent, never sorted {row(scan)}")

# ---- 2.576.0 (#4487): a mail to her own document address is the general input: sorted like the upload
r = Fr.post(B + "/api/docs/mail", json={"ws": "private"})
check(r.ok and r.json().get("address"), "her document address " + r.text[:160])
MAILNO = [0]


def mail_in(addr, text, att=None):
    """One mail to addr through the stub mailbox (att = (name, bytes, maintype, subtype); none = the mail itself becomes the
    document, docs/ingest.py) -> the new document's node id (None: none came)."""
    MAILNO[0] += 1
    mid = f"<p4433-mail-{MAILNO[0]}@example.com>"
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "post@example.com", addr, "Fwd: Post", mid
    m.set_content(text)
    if att:
        m.add_attachment(att[1], maintype=att[2], subtype=att[3], filename=att[0])
    open(os.path.join(kt.DATA, "mail", "in", f"{MAILNO[0]}.eml"), "wb").write(bytes(m))

    def got():
        A.post(B + "/api/admin/mail/poll")
        x = kt.dbx("SELECT node_id FROM doc_meta WHERE source='mail' AND ext_id LIKE ?", (f"mail:{mid}:%",))
        return x[0][0] if x else None
    return until(got, 40)


if r.ok and r.json().get("address"):
    ADDR = r.json()["address"]
    m1 = mail_in(ADDR, "siehe Anhang", ("mail-rechnung.xml", ubl("ER-2026-91", "Beispiel Post GmbH", "DE456789123"), "application", "xml"))
    d = m1 and settled(Fr, m1)
    check(d and row(m1)[:2] == ("office", "auto") and m1 in ids(Fr, area="office") and m1 not in ids(Fr, area="private"),
          f"#4487: the e-invoice of a mail to her own address is sorted into the office {m1 and row(m1)}")
    m2 = mail_in(ADDR, NOTICE.decode().replace("2026", "2027"))  # a text without a file: the mail itself is the document
    check(m2 and settled(Fr, m2) and row(m2)[:2] == ("private", "auto") and m2 in ids(Fr, area="private"),
          f"#4487: a tax notice by mail stays private {m2 and row(m2)}")

# ---- the tenant boundary
G = freelancer(B, A, "gina")[1]
check(area(G, notice, "office").status_code == 404, "another person: 404 (tenant-matrix: document)")
check(area(A, notice, "office").status_code == 404, "the server's admin: 404 on Frida's private document")
r = Fr.post(B + "/api/agents", json={"name": "Sortierer"})
tok = (r.json().get("token") or "") if r.ok else ""
if tok:
    r = requests.post(V.replace("/api/v1", "") + f"/api/docs/{notice}/area", headers={"Authorization": "Bearer " + tok}, json={"to": "office"})
    check(r.status_code in (401, 403, 404), f"an agent token never moves a document ({r.status_code})")

# ==== a person without an office: nothing sorted
NORA, No = freelancer(B, A, "nora", features="files,docs")
n1 = upload(No, "rechnung.xml", ubl("ER-2026-84", "Beispiel Papier GmbH", "DE123456789"), "application/xml")
d = settled(No, n1)
check(d and row(n1)[:2] == ("", "") and d.get("area") is None, f"#4433: without an office nothing is sorted {row(n1)} {d and d.get('area')}")
check(n1 in ids(No, area="private") and n1 in ids(No, area="office"), "without an office the area filter changes nothing")
check(area(No, n1, "office").status_code == 409, "'Move to office' without an office: 409")

# ==== a person whose office is an organisation's
A.patch(B + "/api/settings", json={"lang": "en", "features": "docs,files,office", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.put(B + "/api/office/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "vat_id": "DE999888777"}})
check(r.ok, "setup: Alpha's office " + r.text[:160])
a1 = upload(A, "rechnung.xml", ubl("ER-2026-85", "Beispiel Papier GmbH", "DE123456789"), "application/xml")
d = settled(A, a1)
check(d and d["org_id"] == ORG and row(a1) == ("office", "auto", f"o{ORG}"), f"#4433: the invoice moved into Alpha's documents {d and d['org_id']} {row(a1)}")
check(d and d["area"]["office"] == "org" and d["area"]["wrong"] is True, f"the sheet of the organisation's office {d and d.get('area')}")
check(a1 in ids(A, area="office", unbooked="1") and a1 not in ids(A, area="private"), "Alpha's office lists it, the file store not")
a2 = upload(A, "bescheid.txt", NOTICE, "text/plain")
d = settled(A, a2)
check(d and d["org_id"] is None and row(a2)[:2] == ("private", "auto"), f"the notice stays private {d and d['org_id']} {row(a2)}")
r = area(A, a1, "private")
check(r.ok and r.json()["org_id"] is None and row(a1)[:2] == ("private", "person"), f"'Wrong area': back into the private space {r.status_code} {r.text[:200]}")
r = area(A, a1, "office", undo=True)
check(r.ok and r.json()["org_id"] == ORG and row(a1) == ("office", "auto", f"o{ORG}"), f"the undo: into Alpha again {r.text[:200]} {row(a1)}")
check(area(G, a1, "private").status_code == 404, "another person: 404 on Alpha's document")
# 2.522.0 review (1, 2): a member who is no admin could not take a file out of the organisation again (org_out_ok), so the
# server does not move a member's invoice into the organisation: it stays private, "Move to office" is the person's click
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bert", "display_name": "Bert",
                                   "password": "password123", "email": "bert@example.com"})
check(r.ok, "setup: bert, a member of Alpha " + r.text[:160])
Be = kt.sess("bert")
Be.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "docs,files,office", "workspace": f"org:{ORG}"})
b1 = upload(Be, "rechnung-bert.xml", ubl("ER-2026-86", "Beispiel Papier GmbH", "DE123456789"), "application/xml")
d = settled(Be, b1)
check(d and d["org_id"] is None and row(b1)[:2] == ("private", ""), f"a member's invoice is not moved into the organisation {d and d['org_id']} {row(b1)}")
check(d and (d.get("area") or {}).get("wrong") is False and (d.get("area") or {}).get("can_move") is True, f"no 'Wrong area', 'Move to office' offered {d and d.get('area')}")
r = area(Be, b1, "office")
check(r.ok and r.json()["org_id"] == ORG, f"'Move to office' by the member: into Alpha {r.status_code} {r.text[:200]}")

print(f"p4433_a_area: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
