#!/usr/bin/env python3
"""2.296.0 A (#3164, #3176, #3178): the shared footer in letters, documents from templates and entertainment receipts, the
receipt's page breaks and the 250 EUR limit, each PDF through the layout check (tests/pdfcheck.py). Own container (start.sh).
Invented data only.
freelancer-matrix: office
 - #3164 a letter of a GmbH prints the same footer columns as a quotation: register court, managing director, IBAN, tax number
   (was one line with name, address and contact); a long letter: every page with the footer, layout clean
 - #3164 a document from a template: the body ends above the real footer, layout clean on every page
 - #3176 a receipt with 40 guests and a long note: several pages, nothing below the footer rule, every guest printed, the footer
   with "Created with Kalmido" and the page count on every page, a signature line ("Place, date, signature")
 - #3176 a bill of exactly 250.00 EUR: no hint to make the bill out to the company; 250.01 EUR: the hint ("Above 250 €")
 - a person without organisation (personal office): letter and receipt with the own footer, layout clean
usage: p2296_a_footer_test.py <datadir>      (P2296A_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import base64
import io
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import pdfcheck  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, done, fresh, sess, setup  # noqa: E402
from pypdf import PdfReader  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
fresh({"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2296A")
O = "/api/office"
M = O + "/meals"
IBAN = "IBAN DE89 3704 0044 0532 0130 00"
GMBH = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
        "email": "hallo@studio-nordlicht.example", "phone": "+494012345678", "register_court": "Amtsgericht Hamburg", "register_no": "HRB 123456",
        "managing_directors": "Jana Muster", "bank_name": "Hamburger Beispielbank", "iban": "DE89370400440532013000", "bic": "COBADEFFXXX",
        "tax_number": "12/345/67890", "vat_id": "DE123456789"}

A = setup("alice", "Alice Admin", lang="en")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,docs,files", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office
for s, name in ((A, "Studio Nordlicht GmbH"), (Fr, "Frida Film GmbH")):
    r = s.put(B + O + "/settings", json={"lang": "de", "company_fields": dict(GMBH, name=name)})
    check(r.ok, f"company data saved for {name} {r.text[:200]}")


def flat(fl):
    return " ".join(fl)


def clean(who, data, **kw):
    pr = pdfcheck.problems(data, **kw)
    check(not pr, f"{who}: layout clean {pr[:4]}")


# ---------------------------------------------------------------- 1. #3164 letters
def letter(s, subject, paragraphs=1):
    r = s.post(B + O + "/letters", json={"rcpt_name": "Amt für Beispiele", "rcpt_address": "Musterweg 1\n12345 Musterstadt",
                                         "rcpt_email": "amt@example.com", "subject": subject,
                                         "body": "\n\n".join(("Sehr geehrte Damen und Herren, dies ist ein Absatz mit etwas Text. " * 6) for _ in range(paragraphs))})
    check(r.status_code == 201, f"letter created {r.status_code} {r.text[:200]}")
    r = s.get(B + O + f"/letters/{r.json().get('id')}/pdf")
    check(r.ok and r.content.startswith(b"%PDF"), f"letter PDF {r.status_code}")
    return r.content


for who, s, name in (("org", A, "Studio Nordlicht GmbH"), ("freelancer", Fr, "Frida Film GmbH")):
    d = letter(s, "Antrag 7/2026")
    feet = pdfcheck.footer_lines(d)
    f0 = flat(feet[0])
    for want in (name, "Amtsgericht", "HRB 123456", "Jana Muster", IBAN, "12/345/67890", "hallo@studio-nordlicht.example"):  # a register line may wrap
        check(want in f0, f"#3164 {who}: the letter footer has {want!r} {feet[0]}")
    check(any(IBAN in ln for ln in feet[0]), f"#3164 {who}: the IBAN whole on one line")
    clean(f"#3164 {who} letter", d)
d = letter(A, "Langer Brief", paragraphs=14)
n = len(PdfReader(io.BytesIO(d)).pages)
feet = pdfcheck.footer_lines(d)
check(n >= 2 and all(IBAN in flat(f) and "Amtsgericht Hamburg" in flat(f) for f in feet), f"#3164: a long letter ({n} pages) has the footer on every page")
clean("#3164 long letter", d)

# ---------------------------------------------------------------- 2. #3164 a document from a template
cl = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "address": "Marktplatz 2\n54321 Beispielort"}).json().get("id")
r = A.post(B + O + "/doc-templates", json={"starter": "contract"})
check(r.status_code == 201, f"a template from the sample {r.status_code} {r.text[:200]}")
r = A.post(B + O + "/gen-docs", json={"template_id": r.json().get("id"), "client_id": cl})
check(r.status_code == 201, f"a document {r.status_code} {r.text[:200]}")
r = A.get(B + O + f"/gen-docs/{r.json().get('id')}/pdf")
check(r.ok and r.content.startswith(b"%PDF"), f"the document PDF {r.status_code}")
clean("#3164 template document", r.content)
for i, p in enumerate(pdfcheck.layout(r.content), 1):
    body = [t for t in p["texts"] if t["size"] > 7.2]
    check(p["foot"] is not None and body and max(t["y"] + t["size"] for t in body) <= p["foot"] + 0.6,
          f"#3164: document page {i}: the body ends above the footer rule")
    check(any(IBAN in ln for ln in pdfcheck.footer_lines(r.content)[i - 1]), f"#3164: document page {i}: the footer with the IBAN")


# ---------------------------------------------------------------- 3. #3176 entertainment receipts
def meal(s, host, **kw):
    b = {"date": "2026-10-14", "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
         "occasion": "Negotiation of the follow-up order for the spring campaign", "host": {"id": host},
         "guests": [{"name": "Gina Gast", "extra": "Example GmbH, buyer"}], "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}], "tip": "0"}
    b.update(kw)
    r = s.post(B + M, json={})
    check(r.status_code == 201, f"meal created {r.status_code} {r.text[:200]}")
    mid = r.json().get("id")
    r = s.patch(B + f"{M}/{mid}", json=b)
    check(r.ok, f"meal saved {r.text[:200]}")
    r = s.get(B + f"{M}/{mid}/pdf")
    check(r.ok and r.content.startswith(b"%PDF"), f"meal PDF {r.status_code}")
    return r.content


def text(d):
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(d)).pages)


guests = [{"name": f"Gast Nummer {i}", "extra": "Beispielkunde AG"} for i in range(1, 41)]
note = "\n".join(f"Note line {i}: agreement on locations, schedule, budget and approvals with everybody involved." for i in range(1, 19))
d = meal(A, ALICE, guests=guests, note=note)
lay = pdfcheck.layout(d)
check(len(lay) >= 2, f"#3176: 40 guests and a long note take several pages ({len(lay)})")
clean("#3176 long receipt", d)
t = text(d)
check(all(re.search(rf"Gast Nummer {i}\b", t) for i in range(1, 41)), "#3176: every guest printed")
check("Note line 18" in t and "Place, date, signature" in t, "#3176: the whole note and the signature line")
feet = pdfcheck.footer_lines(d)
check(all("Created with Kalmido" in flat(f) and f"Page {i} of {len(lay)}" in flat(f) and IBAN in flat(f) for i, f in enumerate(feet, 1)),
      f"#3176: the footer with 'Created with Kalmido', the page count and the company columns on every page {feet[-1]}")
for i, p in enumerate(lay, 1):
    check(p["foot"] is not None and all(t["y"] < p["foot"] or t["size"] <= 7.2 for t in p["texts"]), f"#3176: page {i}: nothing of the body below the footer rule")

HINT = "Above 250"
d250 = meal(A, ALICE, amounts=[{"kind": "food", "rate": 19, "gross": "250.00"}], tip="10")
d251 = meal(A, ALICE, amounts=[{"kind": "food", "rate": 19, "gross": "250.01"}])
check(HINT not in text(d250), "#3176: a bill of exactly 250.00 EUR: no hint (small-amount invoice)")
check(HINT in text(d251), "#3176: a bill of 250.01 EUR: the hint to make the bill out to the company")
clean("#3176 receipt 250", d250)
FR = Fr.get(B + "/api/state").json()["me"]["id"]
df = meal(Fr, FR)
check("Frida Film GmbH" in flat(pdfcheck.footer_lines(df)[0]), "#3176 freelancer: the receipt footer with the own company")
clean("#3176 freelancer receipt", df)

sys.exit(done("p2296_a_footer"))
