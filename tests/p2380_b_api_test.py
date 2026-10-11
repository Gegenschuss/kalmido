#!/usr/bin/env python3
"""2.38.0 (#1021 P5) API tests, part B: the stored PDF/A-3 + e-invoice XML of Office & finance, own container in mode
workspaces (start.sh).
 - a draft invoice renders its PDF (with the draft mark) and answers 409 for the XML; finalising stores both files below
   office/<org>/ and shows pdf_sha256 / xml_sha256 in the API; GET .../pdf then returns the stored file (bytes identical,
   SHA matches, also after the company fields and the client change), GET .../xml the stored XML (file name
   invoice-<number>.xml, the own check ein_check finds nothing, the XML embedded in the PDF as factur-x.xml is the same)
 - XRechnung: the PDF carries no embedded file, the XML has the XRechnung profile and the buyer reference; a client
   without a buyer reference -> finalising 400 with the reason, the document stays a draft
 - credit note: type 381 with the cancelled invoice; a reminder has no XML (409); quotations print as PDF/A-3 too
 - tenant matrix (tenant-matrix: office): the second organisation 404, a private person 400, an agent token 403, signed
   out 401; the access log carries "store" with the hashes; a backup zip contains both files
usage: p2380_b_api_test.py <datadir>"""
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
import zipfile

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]



def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()

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


try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)
spec = importlib.util.spec_from_file_location("einvoice", os.path.join(SRC, "kalmido", "office", "einvoice.py"))
ein = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ein)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def xt(xml, path):
    from xml.etree import ElementTree as ET
    x = ET.fromstring(xml).find(path, ein.NS)
    return (x.text or "").strip() if x is not None else None


FEAT = "cal,comments,collab,office,clients"
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Private")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
CAROL = ids["carol"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
OFFICE = os.path.join(DATA, "office")
TEST_IBAN = "DE02120300000000202051"

# ---------------------------------------------------------------- company, clients (invented data)
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht GmbH"}, "lang": "de", "currency": "EUR", "color": "#2f5d8a",
                                     "company_fields": {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                        "country": "DE", "email": "post@beispiel-studio.example", "phone": "+49 40 000000",
                                                        "tax_number": "12/345/67890", "vat_id": "DE123456789", "iban": TEST_IBAN, "bic": "BYLADEM1001",
                                                        "bank_name": "Beispielbank"}})
check(r.ok, "settings + company fields saved " + r.text[:200])
check(r.json()["settings"].get("einvoice_format") == "zugferd", f"the e-invoice format defaults to zugferd: {r.json()['settings'].get('einvoice_format')}")
r = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
                                     "vat_id": "DE987654321", "buyer_reference": "04011000-12345-03", "email_invoice": "rechnung@beispielkunde.example"})
assert r.status_code == 201, r.text
CL = r.json()["id"]
r = A.post(B + "/api/clients", json={"name": "Kleinkunde GbR", "street": "Dorfweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"})
assert r.status_code == 201, r.text
CL2 = r.json()["id"]
ITEMS = [{"title": "Filmherstellung", "qty": 1, "rate": 32840.40}, {"title": "Sprachfassung EN", "qty": 1, "rate": 1215},
         {"title": "Cube-Integration in UI", "qty": 1, "rate": 262.5}, {"title": "Webhosting (3 Monate)", "qty": 1, "rate": 105}]


def new_invoice(client, **kw):
    body = {"kind": "invoice", "project_title": "Interaktiver Film (5 Module + Intro)", "client_id": client, "order_ref": "PO-2026-0001",
            "service_from": "2026-04-01", "service_to": "2026-05-31", "payment_days": 14, "date": "2026-05-08"}
    body.update(kw)
    r = A.post(B + D, json=body)
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = A.put(B + f"{D}/{did}/items", json={"items": ITEMS})
    assert r.ok, r.text
    return did


# ---------------------------------------------------------------- 1. draft: rendered PDF, no XML
INV = new_invoice(CL, einvoice_format="zugferd")  # a client with a buyer reference defaults to xrechnung (F1); this one is ZUGFeRD
r = A.get(B + f"{D}/{INV}/pdf")
check(r.ok and r.headers["Content-Type"].startswith("application/pdf") and r.content.startswith(b"%PDF-1.7") and f'filename="invoice-doc-{INV}.pdf"' in r.headers["Content-Disposition"],
      f"draft invoice: a PDF 1.7 named by the id: {r.headers.get('Content-Disposition')}")
check(b"<pdfaid:part>3</pdfaid:part>" in r.content and b"/EmbeddedFile" not in r.content, "draft: PDF/A-3 without an embedded file")
check(A.get(B + f"{D}/{INV}/xml").status_code == 409, "draft: XML 409")
j = A.get(B + f"{D}/{INV}").json()
check(not j.get("pdf_sha256") and not j.get("xml_sha256") and j["locked"] is False, "draft: no hashes yet")

# ---------------------------------------------------------------- 2. finalising stores PDF + XML (ZUGFeRD)
r = Bo.post(B + f"{D}/{INV}/finalize")
check(r.ok and r.json()["locked"] is True, "a member finalises " + r.text[:200])
NUM = r.json()["number"]
PSHA, XSHA = r.json().get("pdf_sha256"), r.json().get("xml_sha256")
check(len(PSHA or "") == 64 and len(XSHA or "") == 64 and PSHA != XSHA, f"pdf_sha256 / xml_sha256 in the API: {PSHA} {XSHA}")
PDF_FILE = os.path.join(OFFICE, str(ORG), f"doc{INV}-invoice-{NUM}.pdf")
XML_FILE = os.path.join(OFFICE, str(ORG), f"doc{INV}-invoice-{NUM}.xml")
check(os.path.isfile(PDF_FILE) and os.path.isfile(XML_FILE), f"both files stored below office/{ORG}/: {sorted(os.listdir(os.path.join(OFFICE, str(ORG))))}")
with open(PDF_FILE, "rb") as fh:
    stored_pdf = fh.read()
with open(XML_FILE, "rb") as fh:
    stored_xml = fh.read()
check(sha(stored_pdf) == PSHA and sha(stored_xml) == XSHA, "the stored files have the hashes of the document")
r = A.get(B + f"{D}/{INV}/pdf")
check(r.ok and r.content == stored_pdf and f'filename="invoice-{NUM}.pdf"' in r.headers["Content-Disposition"], "GET pdf = the stored file, named by kind and number")
r = Bo.get(B + f"{D}/{INV}/xml")
check(r.ok and r.content == stored_xml and r.headers["Content-Type"].startswith("application/xml") and f'filename="invoice-{NUM}.xml"' in r.headers["Content-Disposition"]
      and "no-store" in r.headers.get("Cache-Control", ""), f"GET xml = the stored XML for members: {r.status_code} {r.headers.get('Content-Disposition')}")
check(xt(stored_xml, "rsm:ExchangedDocument/ram:ID") == NUM and xt(stored_xml, "rsm:ExchangedDocument/ram:TypeCode") == "380"
      and xt(stored_xml, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID") == "urn:cen.eu:en16931:2017", "XML: number, type 380, profile EN 16931")
MS = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementHeaderMonetarySummation/"
check(xt(stored_xml, MS + "ram:LineTotalAmount") == "34422.90" and xt(stored_xml, MS + "ram:TaxTotalAmount") == "6540.35" and xt(stored_xml, MS + "ram:GrandTotalAmount") == "40963.25",
      f"XML: the parity sums 34422.90 / 6540.35 / 40963.25: {xt(stored_xml, MS + 'ram:LineTotalAmount')} {xt(stored_xml, MS + 'ram:TaxTotalAmount')} {xt(stored_xml, MS + 'ram:GrandTotalAmount')}")
AG = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/"
check(xt(stored_xml, AG + "ram:SellerTradeParty/ram:Name") == "Studio Nordlicht GmbH" and xt(stored_xml, AG + "ram:BuyerTradeParty/ram:PostalTradeAddress/ram:CityName") == "Köln"
      and xt(stored_xml, AG + "ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID") == "PO-2026-0001", "XML: seller, buyer address, order reference from the snapshot")
check(TEST_IBAN in stored_xml.decode() and "20260522" in stored_xml.decode(), "XML: IBAN and the due date (14 days)")
f = ein.ein_check(stored_xml)
check(f == [], f"ein_check finds nothing in the stored XML: {f}")
rd = PdfReader(io.BytesIO(stored_pdf))
att = rd.attachments.get("factur-x.xml")
att = att[0] if isinstance(att, list) else att
check(att == stored_xml and b"<fx:ConformanceLevel>EN 16931</fx:ConformanceLevel>" in stored_pdf and b"/AFRelationship /Alternative" in stored_pdf,
      "ZUGFeRD: the same XML is embedded in the PDF as factur-x.xml")
txt = "\n".join(p.extract_text() or "" for p in rd.pages)
check(NUM in txt and "40.963,25" in txt and "Beispielkunde AG" in txt and "Marktstraße 5" in txt and "Zahlbar bis 22.05.2026" in txt, "the stored PDF prints number, client address, total, payment text")
check("Entwurf" not in txt and "Draft" not in txt, "no draft mark on the finalised PDF")
log = A.get(B + f"{D}/{INV}/log").json()
entries = log.get("log") if isinstance(log, dict) else log
st = [e for e in entries if e.get("action") == "store"]
check(st and (st[0].get("detail") or {}).get("pdf_sha256") == PSHA, f"the access log has 'store' with the hashes: {st[:1]}")

# ---------------------------------------------------------------- 3. later changes never touch the stored files
A.put(B + O + "/settings", json={"company_fields": {"street": "Neuer Weg 1", "iban": "", "bank_name": "Andere Bank"}, "color": "#aa3300"})
A.patch(B + f"/api/clients/{CL}", json={"name": "Umbenannt AG", "street": "Andere Straße 9"})
r = A.get(B + f"{D}/{INV}/pdf")
check(r.ok and r.content == stored_pdf and sha(r.content) == PSHA, "after company + client changes: GET pdf still byte-identical")
r = A.get(B + f"{D}/{INV}/xml")
check(r.ok and r.content == stored_xml, "... and the XML too")
check(A.get(B + f"{D}/{INV}").json().get("pdf_sha256") == PSHA, "the hashes in the document are unchanged")
A.put(B + O + "/settings", json={"company_fields": {"street": "Hafenstraße 12", "iban": TEST_IBAN, "bank_name": "Beispielbank"}})

# ---------------------------------------------------------------- 4. tenant matrix
for path in ("pdf", "xml"):
    check(Ca.get(B + f"{D}/{INV}/{path}").status_code == 404, f"tenant-matrix: office -- {path}: the second organisation 404")
    check(Da.get(B + f"{D}/{INV}/{path}").status_code in (400, 404), f"tenant-matrix: office -- {path}: a private person cannot")
    check(requests.get(B + f"{D}/{INV}/{path}", headers=AGH).status_code == 403, f"tenant-matrix: office -- {path}: agent 403")
    check(requests.get(B + f"{D}/{INV}/{path}", headers=H).status_code == 401, f"tenant-matrix: office -- {path}: signed out 401")
check(Ca.get(B + f"{D}/{INV}/xml").status_code == 404 and not os.path.isdir(os.path.join(OFFICE, str(ORG2))), "nothing of Alpha is stored below Beta's folder")

# ---------------------------------------------------------------- 5. XRechnung: separate XML, buyer reference mandatory
INX = new_invoice(CL, einvoice_format="xrechnung")
check(A.get(B + f"{D}/{INX}").json().get("einvoice_format") == "xrechnung", "the document's format is xrechnung")
r = A.post(B + f"{D}/{INX}/finalize")
check(r.ok, "XRechnung invoice finalised " + r.text[:200])
NUMX = r.json()["number"]
r = A.get(B + f"{D}/{INX}/xml")
check(r.ok and xt(r.content, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID") == "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
      and xt(r.content, AG + "ram:BuyerReference") == "04011000-12345-03"
      and xt(r.content, AG + "ram:SellerTradeParty/ram:DefinedTradeContact/ram:TelephoneUniversalCommunication/ram:CompleteNumber") == "+49 40 000000"
      and xt(r.content, AG + "ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID") == "rechnung@beispielkunde.example", "XRechnung XML: profile, buyer reference, seller contact, buyer e-mail")
check(ein.ein_check(r.content) == [], f"XRechnung ein_check: {ein.ein_check(r.content)}")
p = A.get(B + f"{D}/{INX}/pdf").content
check(p.startswith(b"%PDF-1.7") and b"<pdfaid:part>3</pdfaid:part>" in p and b"/EmbeddedFile" not in p and b"fx:DocumentFileName" not in p, "XRechnung PDF: PDF/A-3 without an embedded file or fx: schema")
check(os.path.isfile(os.path.join(OFFICE, str(ORG), f"doc{INX}-invoice-{NUMX}.xml")), "XRechnung XML stored as its own file")
INN = new_invoice(CL2, einvoice_format="xrechnung")
r = A.post(B + f"{D}/{INN}/finalize")
check(r.status_code == 400 and "buyer reference" in r.json().get("error", "").lower(), f"XRechnung without a buyer reference: finalise 400 with the reason: {r.status_code} {r.text[:160]}")
j = A.get(B + f"{D}/{INN}").json()
check(j["locked"] is False and not j.get("pdf_sha256"), "... the document stays an open draft without hashes")
check(not any(fn.startswith(f"doc{INN}-") for fn in os.listdir(os.path.join(OFFICE, str(ORG)))), "... and nothing was stored")
r = A.patch(B + f"{D}/{INN}", json={"einvoice_format": "zugferd"})
check(r.ok and A.post(B + f"{D}/{INN}/finalize").ok, "as ZUGFeRD the same invoice finalises")

# ---------------------------------------------------------------- 6. credit note, reminder, quotation
r = A.post(B + f"{D}/{INV}/credit")
check(r.status_code == 201, "credit note made " + r.text[:200])
CR = r.json()["id"]
check(A.get(B + f"{D}/{CR}/xml").status_code == 409, "credit note draft: XML 409")
r = A.post(B + f"{D}/{CR}/finalize")
check(r.ok and r.json().get("xml_sha256"), "credit note finalised with an XML hash " + r.text[:120])
x = A.get(B + f"{D}/{CR}/xml")
check(x.ok and xt(x.content, "rsm:ExchangedDocument/ram:TypeCode") == "381"
      and xt(x.content, "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/ram:InvoiceReferencedDocument/ram:IssuerAssignedID") == NUM
      and xt(x.content, MS + "ram:GrandTotalAmount") == "40963.25", "credit note XML: 381, positive total, BT-25 = the invoice")
check(ein.ein_check(x.content) == [], f"credit note ein_check: {ein.ein_check(x.content)}")
check(f'filename="credit-{r.json()["number"]}.xml"' in x.headers["Content-Disposition"], "credit note XML named credit-<number>.xml")
r = A.post(B + D + "/reminder", json={"doc_ids": [INX], "level": 1, "fee": 5, "deadline_days": 10})
check(r.status_code == 201, "reminder made " + r.text[:160])
RM = r.json()["id"]
p = A.get(B + f"{D}/{RM}/pdf")
check(p.ok and NUMX in "\n".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(p.content)).pages), "reminder draft PDF lists the invoice")
check(A.post(B + f"{D}/{RM}/finalize").ok and A.get(B + f"{D}/{RM}/xml").status_code == 409, "a finalised reminder has a stored PDF but no XML (409)")
j = A.get(B + f"{D}/{RM}").json()
check(len(j.get("pdf_sha256") or "") == 64 and not j.get("xml_sha256"), "reminder: pdf hash only")
r = A.post(B + D, json={"project_title": "Imagefilm", "client_id": CL})
QO = r.json()["id"]
A.put(B + f"{D}/{QO}/items", json={"items": ITEMS[:1]})
p = A.get(B + f"{D}/{QO}/pdf").content
check(p.startswith(b"%PDF-1.7") and b"<pdfaid:part>3</pdfaid:part>" in p and b"/FontFile2" in p and A.get(B + f"{D}/{QO}/xml").status_code == 409,
      "a quotation prints as PDF/A-3 with the embedded font, no XML")
r = A.post(B + f"{D}/{QO}/finalize")
check(r.ok and not r.json().get("pdf_sha256") and not any(fn.startswith(f"doc{QO}-") for fn in os.listdir(os.path.join(OFFICE, str(ORG)))),
      "a finalised quotation is not stored (rendered from its snapshot, no hash)")
p = A.get(B + f"{D}/{QO}/pdf")
check(p.ok and p.content.startswith(b"%PDF-1.7") and f'filename="{r.json()["number"]}.pdf"' in p.headers["Content-Disposition"], "... its PDF still comes from the snapshot, named by the number")

# ---------------------------------------------------------------- 7. the backup carries the stored files
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, "backup started " + r.text[:100])
for _ in range(100):
    j = A.get(B + "/api/admin/backups").json()
    if not j["running"] and j["items"]:
        break
    time.sleep(0.3)
items_b = A.get(B + "/api/admin/backups").json()["items"]
NAME = items_b[0]["name"]
with zipfile.ZipFile(os.path.join(DATA, "backups", NAME)) as z:
    names = z.namelist()
    man = json.loads(z.read("manifest.json"))
    check(f"office/{ORG}/doc{INV}-invoice-{NUM}.pdf" in names and f"office/{ORG}/doc{INV}-invoice-{NUM}.xml" in names, f"the stored PDF + XML are members of the backup zip: {[n for n in names if n.startswith('office/')]}")
    check(any(f_[0] == f"office/{ORG}/doc{INV}-invoice-{NUM}.xml" and f_[2] == XSHA for f_ in man["files"]), "... listed in the manifest with the same SHA-256")
    check(z.read(f"office/{ORG}/doc{INV}-invoice-{NUM}.pdf") == stored_pdf, "... the PDF in the zip is the stored file")

# ---------------------------------------------------------------- 8. a stored file that has gone (2.38.0 review)
# the reminder's stored PDF is no longer where its row points (number changed underneath): 409 + store_missing, no new rendering
dbx("UPDATE office_docs SET number=? WHERE id=?", ("MA-GONE-1", RM), write=True)
r = A.get(B + f"{D}/{RM}/pdf")
check(r.status_code == 409 and "missing" in r.json().get("error", ""), "finalised document without its stored file: 409 " + r.text[:120])
check(dbx("SELECT COUNT(*) FROM office_doc_log WHERE doc_id=? AND action='store_missing'", (RM,))[0][0] >= 1, "... logged as store_missing")
check(A.get(B + f"{D}/{QO}/pdf").ok, "... a finalised quotation without a stored file still renders from its snapshot")

print(f"p2380_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
