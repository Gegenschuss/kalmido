#!/usr/bin/env python3
"""2.99.0 API tests, part D (#2188): the rest of the fixed recipient fields of office documents. Own container (start.sh),
invented companies and people only.
 - a client's name addition (name_extra): stored, in /api/clients and /api/state; lists show "name - addition" (label);
   a draft's recipient prints it as its own line under the name; the e-invoice buyer name (BT-44) is "name - addition"
 - the e-invoice takes VAT ID (BT-48), e-mail (BT-49: the invoice e-mail, else the client's e-mail) and the buyer
   reference (BT-10) from the client
 - the own company name has up to three lines (more: 400): the PDF letterhead and footer print them one under the other,
   the sender line and the seller name (BT-27) on one line; the company's extra address line (BT-36 = LineTwo)
 - an old free company address (street / postcode / city empty) is read into the fields of the settings answer (nothing
   stored, the free lines stay); saving keeps them; an address that does not split cleanly stays free
 - a finalised invoice keeps its recipient, print model and XML when the client changes; an old snapshot without
   name_extra still renders
 - a person without an organisation (the personal office) works the same
freelancer-matrix: office
usage: p299_d_api_test.py <datadir>      (a fresh container; P299D_NOSTART=1: the container runs already)"""
import io
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
TEST_IBAN = "DE02120300000000202051"
NS = {"rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
      "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"}
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


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def pdf_lines(data):
    """The text lines of a PDF (pdftotext, else pypdf); None when neither is there."""
    try:
        out = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, check=True).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.CalledProcessError):
        try:
            from pypdf import PdfReader
        except ImportError:
            return None
        out = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    return [" ".join(x.split()) for x in out.splitlines() if x.strip()]


def xml_of(s, did):
    r = s.get(B + f"{D}/{did}/xml")
    assert r.ok, r.text[:200]
    return ET.fromstring(r.content)


def xt(root, path):
    e = root.find(path, NS)
    return (e.text or "") if e is not None else None


AG = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement"
FEAT = "cal,comments,collab,office,clients,time"
if os.environ.get("P299D_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com"})
assert r.ok, r.text
CAROL = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Ca = sess("carol")
for s in (A, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{r.json()['id']}"})
O = "/api/office"
D = O + "/docs"

# ---------------------------------------------------------------- the company: a name of up to three lines, the extra line
CNAME = "Studio Polar\nFilm und Ton\nProduktion GmbH"
COMPANY = {"name": CNAME, "street": "Hafenstraße 12", "address_extra": "Speicher 3", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hallo@polar.example", "phone": "+49 40 123456", "tax_number": "12/345/67890", "vat_id": "DE999999999",
           "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank", "managing_directors": "Erika Beispiel"}
r = A.put(B + O + "/settings", json={"company": {"name": CNAME}, "lang": "de", "currency": "EUR", "company_fields": COMPANY, "payment_days": 14})
check(r.ok and r.json()["company_fields"]["name"] == CNAME and r.json()["company_fields"]["address_extra"] == "Speicher 3",
      "the company name keeps its three lines, the extra address line is stored " + r.text[:200])
check(r.ok and r.json()["settings"]["company"]["name"] == CNAME, "the free company name keeps its lines too")
r = A.put(B + O + "/settings", json={"company_fields": {"name": "Eins\nZwei\nDrei\nVier"}})
check(r.status_code == 400, f"four lines: 400 ({r.status_code})")
r = A.put(B + O + "/settings", json={"company_fields": {"name": "  Studio Polar \n\n Film   und Ton\nProduktion GmbH  "}})
check(r.ok and r.json()["company_fields"]["name"] == CNAME, f"empty lines and spaces folded: {r.json().get('company_fields', {}).get('name')!r}")


def client(s, **b):
    r = s.post(B + "/api/clients", json={"org_id": ORG, **b} if s is A else b)
    assert r.status_code == 201, r.text
    return r.json()


def state_cl(s):
    return {c["id"]: c for c in s.get(B + "/api/state").json().get("clients") or []}


# ---------------------------------------------------------------- the client's name addition
K = client(A, name="NORDLICHT", name_extra="Berg, Tal und Partner GbR", street="Unter den Linden 2", zip="10117", city="Berlin",
           country="DE", email="buero@nordlicht.example", vat_id="DE123456789", buyer_reference="991-12345-67")
check(K["name"] == "NORDLICHT" and K["name_extra"] == "Berg, Tal und Partner GbR", f"name_extra stored next to the name: {K.get('name_extra')!r}")
check(K["label"] == "NORDLICHT - Berg, Tal und Partner GbR" and state_cl(A)[K["id"]]["label"] == K["label"],
      f"lists show name - addition on one line: {K['label']!r}")
check(state_cl(A)[K["id"]].get("name_extra") == "Berg, Tal und Partner GbR", "/api/state carries name_extra")
r = A.patch(B + f"/api/clients/{K['id']}", json={"name_extra": "  Berg,   Tal und Partner GbR  "})
check(r.ok and r.json()["name_extra"] == "Berg, Tal und Partner GbR", "PATCH name_extra (spaces folded)")
check(A.patch(B + f"/api/clients/{K['id']}", json={"name_extra": 5}).status_code == 400, "name_extra must be text (400)")
check(A.patch(B + f"/api/clients/{K['id']}", json={"name_extra": "x" * 200}).json().get("name_extra") == "x" * 120, "name_extra is cut at 120")
A.patch(B + f"/api/clients/{K['id']}", json={"name_extra": "Berg, Tal und Partner GbR"})
DN = client(A, name="NORDLICHT", name_extra="Zweigstelle", display_name="Nordlicht Süd", street="Weg 1", zip="80331", city="München")
check(DN["label"] == "Nordlicht Süd", "a display name still wins as the label")

# ---------------------------------------------------------------- a quotation draft: the extra line under the name
r = A.post(B + D, json={"project_title": "Imagefilm", "client_id": K["id"]})
check(r.status_code == 201, "a quotation with the client " + r.text[:160])
OFF = r.json()
check(OFF["recipient"]["lines"] == ["NORDLICHT", "Berg, Tal und Partner GbR", "Unter den Linden 2", "10117 Berlin"] and
      OFF["recipient"].get("name_extra") == "Berg, Tal und Partner GbR", f"the recipient: the addition as its own line: {OFF['recipient']}")
rd = A.get(B + f"{D}/{OFF['id']}/render").json()
check(rd["recipient"]["name"] == "NORDLICHT" and rd["recipient"].get("name_extra") == "Berg, Tal und Partner GbR", "the print model carries it")
p = A.get(B + f"{D}/{OFF['id']}/pdf")
lines = pdf_lines(p.content) if p.ok else None
if lines is None:
    print("p299_d_api: no pdftotext / pypdf - PDF text checks skipped", flush=True)
else:
    txt = "\n".join(lines)
    check("NORDLICHT" in txt and "Berg, Tal und Partner GbR" in txt and txt.find("NORDLICHT") < txt.find("Berg, Tal und Partner GbR"),
          "quotation PDF: the name, then the addition")
    check(not any("NORDLICHT Berg, Tal" in ln or "NORDLICHT - Berg" in ln for ln in lines), "quotation PDF: two lines, not one")
    check(all(x in txt for x in ("Studio Polar", "Film und Ton", "Produktion GmbH")), "quotation PDF: the three company name lines")

# ---------------------------------------------------------------- an invoice: PDF, XML (BT-44/48/49/10, BT-27, BT-36)
r = A.post(B + D, json={"kind": "invoice", "client_id": K["id"], "service_from": "2030-05-01", "service_to": "2030-05-31",
                        "einvoice_format": "xrechnung", "items": [{"title": "Beratung", "qty": 1, "rate": 100}]})
check(r.status_code == 201, "an invoice draft " + r.text[:160])
INV = r.json()
r = A.post(B + f"{D}/{INV['id']}/finalize")
check(r.ok and r.json()["locked"] is True, "finalised " + r.text[:200])
x = xml_of(A, INV["id"])
check(xt(x, AG + "/ram:BuyerTradeParty/ram:Name") == "NORDLICHT - Berg, Tal und Partner GbR",
      f"BT-44: name - addition: {xt(x, AG + '/ram:BuyerTradeParty/ram:Name')!r}")
check(xt(x, AG + "/ram:BuyerTradeParty/ram:SpecifiedTaxRegistration/ram:ID") == "DE123456789", "BT-48: the client's VAT ID")
check(xt(x, AG + "/ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID") == "buero@nordlicht.example",
      "BT-49: without an invoice e-mail the client's e-mail")
check(xt(x, AG + "/ram:BuyerReference") == "991-12345-67", "BT-10: the client's buyer reference (Leitweg-ID)")
check(xt(x, AG + "/ram:SellerTradeParty/ram:Name") == "Studio Polar Film und Ton Produktion GmbH", f"BT-27: the company name on one line: {xt(x, AG + '/ram:SellerTradeParty/ram:Name')!r}")
check(xt(x, AG + "/ram:SellerTradeParty/ram:PostalTradeAddress/ram:LineTwo") == "Speicher 3", "BT-36: the company's extra address line")
rd = A.get(B + f"{D}/{INV['id']}/render").json()
check(rd["recipient"].get("name_extra") == "Berg, Tal und Partner GbR" and rd["recipient"]["lines"][:2] == ["NORDLICHT", "Berg, Tal und Partner GbR"],
      f"the invoice's print model: {rd['recipient'].get('lines')}")
p = A.get(B + f"{D}/{INV['id']}/pdf")
lines = pdf_lines(p.content) if p.ok else None
if lines is not None:
    txt = "\n".join(lines)
    check(txt.find("NORDLICHT") < txt.find("Berg, Tal und Partner GbR") and not any("NORDLICHT - Berg" in ln for ln in lines), "invoice PDF: name and addition, two lines")
    check(any("Studio Polar Film und Ton Produktion GmbH" in ln for ln in lines), "invoice PDF: the sender line has the name on one line")
    check(sum(1 for ln in lines if "Produktion GmbH" in ln and "Studio Polar" not in ln) >= 2,
          "invoice PDF: letterhead and footer set the name lines one under the other")
    check(any("Speicher 3" in ln for ln in lines), "invoice PDF: the company's extra address line")
# an invoice e-mail wins over the e-mail
A.patch(B + f"/api/clients/{K['id']}", json={"email_invoice": "rechnung@nordlicht.example"})
r = A.post(B + D, json={"kind": "invoice", "client_id": K["id"], "service_from": "2030-06-01", "items": [{"title": "Schnitt", "qty": 1, "rate": 50}]})
I2 = r.json()
check(A.post(B + f"{D}/{I2['id']}/finalize").ok, "the second invoice finalised")
check(xt(xml_of(A, I2["id"]), AG + "/ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID") == "rechnung@nordlicht.example",
      "BT-49: the invoice e-mail when there is one")
# the client changes after finalising: the invoice stays
A.patch(B + f"/api/clients/{K['id']}", json={"name_extra": "Neue Gesellschafter GbR", "vat_id": "DE111111111"})
d = A.get(B + f"{D}/{INV['id']}").json()
check(d["recipient"]["lines"][:2] == ["NORDLICHT", "Berg, Tal und Partner GbR"], f"finalised: the recipient is frozen: {d['recipient']['lines']}")
x2 = xml_of(A, INV["id"])
check(xt(x2, AG + "/ram:BuyerTradeParty/ram:Name") == "NORDLICHT - Berg, Tal und Partner GbR" and
      xt(x2, AG + "/ram:BuyerTradeParty/ram:SpecifiedTaxRegistration/ram:ID") == "DE123456789", "finalised: the XML is frozen")
r = A.post(B + D, json={"project_title": "Neu", "client_id": K["id"]})
check("Neue Gesellschafter GbR" in r.json()["recipient"]["lines"], "a draft reads the changed addition")
# an old snapshot without name_extra (as 2.97 froze it) still renders, with the name only
dbx("UPDATE office_docs SET recipient_snapshot=?, recipient=? WHERE id=?",
    (json.dumps({"name": "NORDLICHT", "lines": ["NORDLICHT", "Unter den Linden 2", "10117 Berlin"], "street": "Unter den Linden 2", "zip": "10117",
                 "city": "Berlin", "country": "DE", "vat_id": "DE123456789", "buyer_reference": "991-12345-67", "email_invoice": ""}),
     json.dumps({"name": "NORDLICHT", "lines": ["NORDLICHT", "Unter den Linden 2", "10117 Berlin"]}), INV["id"]))
rd = A.get(B + f"{D}/{INV['id']}/render")
check(rd.ok and rd.json()["recipient"]["name"] == "NORDLICHT" and not rd.json()["recipient"].get("name_extra"), "an old snapshot renders without the addition")
check(xt(xml_of(A, INV["id"]), AG + "/ram:BuyerTradeParty/ram:Name") in ("NORDLICHT", "NORDLICHT - Berg, Tal und Partner GbR"),
      "an old snapshot: the XML has the name (a stored XML stays as it was)")
check(Ca.get(B + f"{D}/{INV['id']}").status_code in (403, 404), "tenant-matrix: office -- another organisation does not read the invoice")
check(K["id"] not in state_cl(Ca), "tenant-matrix: office -- another organisation does not see the client")

# ---------------------------------------------------------------- the old free company address -> the fields
dbx("UPDATE office_company SET street='', address_extra='', zip='', city='' WHERE org_id=?", (ORG,))
A.put(B + O + "/settings", json={"company": {"name": CNAME, "lines": ["Altonaer Straße 5", "22767 Hamburg"]}})
r = A.get(B + O + "/settings").json()
cf = r["company_fields"]
check(cf["street"] == "Altonaer Straße 5" and cf["zip"] == "22767" and cf["city"] == "Hamburg", f"the free address read into the fields: {cf}")
check(r["settings"]["company"]["lines"] == ["Altonaer Straße 5", "22767 Hamburg"], "the free lines stay")
check(dbx("SELECT street FROM office_company WHERE org_id=?", (ORG,))[0][0] == "", "reading stores nothing")
r = A.post(B + D, json={"kind": "invoice", "client_id": K["id"], "service_from": "2030-07-01", "items": [{"title": "Ton", "qty": 1, "rate": 70}]})
check(A.post(B + f"{D}/{r.json()['id']}/finalize").ok, "an invoice with the read company address finalises")
x3 = xml_of(A, r.json()["id"])
check(xt(x3, AG + "/ram:SellerTradeParty/ram:PostalTradeAddress/ram:LineOne") == "Altonaer Straße 5" and
      xt(x3, AG + "/ram:SellerTradeParty/ram:PostalTradeAddress/ram:CityName") == "Hamburg", "the e-invoice seller address from the read fields")
r = A.put(B + O + "/settings", json={"company_fields": {"phone": "+49 40 654321"}})
check(r.ok and dbx("SELECT street, zip, city FROM office_company WHERE org_id=?", (ORG,))[0] == ("Altonaer Straße 5", "22767", "Hamburg"),
      "saving the settings keeps the read fields")
# a free address that does not split cleanly stays free (nothing lost in print)
dbx("UPDATE office_company SET street='', zip='', city='' WHERE org_id=?", (ORG,))
A.put(B + O + "/settings", json={"company": {"lines": ["c/o Agentur Beispiel", "Altonaer Straße 5", "22767 Hamburg"]}})
cf = A.get(B + O + "/settings").json()["company_fields"]
check(cf["street"] == "" and cf["city"] == "", f"an address with an extra line stays in the free lines: {cf['street']!r}")
A.put(B + O + "/settings", json={"company_fields": COMPANY})

# ---------------------------------------------------------------- a person without an organisation (the personal office)
FID, Fr = freelancer(B, A)
r = Fr.put(B + O + "/settings", json={"company_fields": {"name": "Frida Film\nKamera und Schnitt", "street": "Hafenweg 1", "zip": "20457",
                                                           "city": "Hamburg", "country": "DE", "tax_number": "12/345/67890", "iban": TEST_IBAN}})
check(r.ok and r.json()["company_fields"]["name"] == "Frida Film\nKamera und Schnitt", "freelancer: a company name of two lines")
P1 = client(Fr, name="Kunde Eins", name_extra="Abteilung Film", street="Weg 1", zip="20095", city="Hamburg")
check(P1["org_id"] is None and state_cl(Fr)[P1["id"]]["label"] == "Kunde Eins - Abteilung Film", "freelancer: a private client with an addition")
r = Fr.post(B + D, json={"kind": "invoice", "client_id": P1["id"], "service_from": "2030-02-01", "items": [{"title": "Shoot", "qty": 1, "rate": 900}]})
check(r.status_code == 201 and r.json()["recipient"]["lines"] == ["Kunde Eins", "Abteilung Film", "Weg 1", "20095 Hamburg"], f"freelancer: the recipient: {r.text[:200]}")
FI = r.json()["id"]
check(Fr.post(B + f"{D}/{FI}/finalize").ok, "freelancer: finalised")
xf = xml_of(Fr, FI)
check(xt(xf, AG + "/ram:BuyerTradeParty/ram:Name") == "Kunde Eins - Abteilung Film" and xt(xf, AG + "/ram:SellerTradeParty/ram:Name") == "Frida Film Kamera und Schnitt",
      "freelancer: BT-44 with the addition, BT-27 on one line")
check(P1["id"] not in state_cl(A) and K["id"] not in state_cl(Fr), "freelancer: no clients across the boundary")

print(f"p299_d_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
