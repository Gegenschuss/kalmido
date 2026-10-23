#!/usr/bin/env python3
"""2.114.4 API tests, part A (#2271 #2272 #2273 #2274 #2275 #2276 #2277 #2282 #2284): the layout of the quotation PDF and of
the document PDF. Invented names and amounts only.
 - #2271 footer: the IBAN, "E-Mail x", "Steuernummer x" each stand whole on one line of the text layer
 - #2272 an unspaced phone number prints grouped ("+49 30 123456789"), the stored value stays
 - #2273 / #2282 no "Seite 1 von 1" on a one-page quotation or document; a long quotation numbers every page in the footer
 - #2274 the VAT note names only the rates of the document (19 % alone; 7 % and 19 % when both occur)
 - #2275 the option total reads "Summe netto mit Option Rohdaten" / "Net total with option raw data"
 - #2276 the producing line carries a position number, "1 Tag" / "1 day", the formula stays in the app (render) and not in the PDF
 - #2277 no "Kunde" row in the head (render meta), the name stands in the address field
 - #2284 a document (template) prints the same column footer: bank, IBAN, tax number
 - an organisation's office and a person without an organisation (own personal office) alike
usage: p21144_a_api_test.py <datadir>      (a fresh container; P21144A_NOSTART=1 = the server already runs)"""
import io
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer, login  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
TEST_IBAN = "DE02120300000000202051"
IBAN_PRINT = "IBAN DE02 1203 0000 0000 2020 51"
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def squash(s):
    return re.sub(r"\s+", "", s or "")


def pages(data):
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages]


ONE_PAGE = []


def page_rule(pg, what, fmt="Seite {0} von {1}"):
    """#2273 / #2282: one page -> no page count at all; more -> "x of n" once on every page (the footer)."""
    n = len(pg)
    if n == 1:
        ONE_PAGE.append(what)
        check(not re.search(r"(Seite|Page)\s*1\s*(von|of)\s*1", pg[0]), f"{what}: #2282 no page count on a one-page PDF")
    else:
        check(all(squash(pg[i]).count(squash(fmt.format(i + 1, n))) == 1 for i in range(n)), f"{what}: #2273 'x of {n}' once on every page")


def one_line(pg, want):
    """want stands whole on one line of the text layer (not broken)."""
    return any(want in ln for t in pg for ln in t.splitlines())


if not os.environ.get("P21144A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done"})
FID, F = freelancer(B, A)

COMPANY = {"name": "Musterfilm - Beispiel, Probe & Partner eGbR", "street": "Musterstraße 127", "zip": "10115", "city": "Berlin", "country": "DE",
           "email": "post@musterfilm.example", "phone": "+4930123456789", "tax_number": "12/345/67890", "iban": TEST_IBAN, "bic": "BYLADEM1001",
           "bank_name": "Beispielbank Berlin", "register_court": "Amtsgericht Berlin", "register_no": "GsR 4711",
           "managing_directors": "Erika Beispiel, Max Mustermann & Paula Probe", "md_label": "shareholders"}


def setup(S, who):
    r = S.put(B + O + "/settings", json={"company": {"name": COMPANY["name"]}, "lang": "de", "currency": "EUR", "company_fields": COMPANY,
                                          "prod_quotient": 3, "raw_factor": 0.25, "producing_rate": 600, "producing_on": 1, "raw_on": 1})
    check(r.ok, f"{who}: settings + company fields {r.status_code} {r.text[:200]}")
    st = S.get(B + O + "/settings").json()
    check((st.get("company_fields") or {}).get("phone") == "+4930123456789", f"{who}: #2272 the stored phone stays unspaced {(st.get('company_fields') or {}).get('phone')}")
    r = S.post(B + "/api/clients", json={"name": "Muster Agentur GmbH", "address": "Agenturweg 5\n50667 Köln"})
    check(r.status_code in (200, 201), f"{who}: a client {r.status_code} {r.text[:200]}")
    return r.json().get("id")


def quotation(S, who, cl, lang, items):
    r = S.post(B + D, json={"project_title": f"Imagefilm {who} {lang}", "client_id": cl, "lang": lang, "producing_on": 1})  # 2.113.1 (#2251): producing per quotation (the office setting no longer switches it on)
    check(r.status_code == 201, f"{who} {lang}: a quotation {r.status_code} {r.text[:200]}")
    doc = r.json().get("id")
    r = S.put(B + f"{D}/{doc}/items", json={"items": items})
    check(r.ok, f"{who} {lang}: positions set {r.status_code} {r.text[:200]}")
    return doc


ITEMS = [{"title": "Konzept und Drehbuch", "qty": 3, "unit": "day", "rate": 800, "producing": 1, "raw_fee": 1},
         {"title": "Schnitt", "qty": 1, "unit": "flat", "rate": 500}]


def scenario(S, who):
    cl = setup(S, who)
    # ------------------------------------------------ a one-page quotation (DE)
    doc = quotation(S, who, cl, "de", ITEMS)
    rd = S.get(B + f"{D}/{doc}/render").json()
    number = rd.get("number") or ""
    check("Kunde" not in [x[0] for x in rd.get("meta") or []], f"{who}: #2277 no 'Kunde' row in the head {rd.get('meta')}")
    prod = [x for x in rd.get("lines") or [] if x.get("kind") == "producing"]
    check(prod and prod[0].get("pos") == 3 and prod[0].get("unit_text") == "Tag", f"{who}: #2276 producing numbered 3, '1 Tag' {prod[:1]}")
    # 2.113.1 (#2251): the print model (preview, PDF) carries no calculation text; the editor shows it from
    # the document's own totals
    check(prod and not prod[0].get("detail"), f"{who}: #2251 no formula in the print model {prod[:1]}")
    ed = [x for x in (S.get(B + f"{D}/{doc}").json().get("totals") or {}).get("lines") or [] if x.get("kind") == "producing"]
    check(ed and ed[0].get("detail", "").startswith("1 Tag = 3 Produktionstage / 3"), f"{who}: #2276 the app keeps the formula {ed[:1]}")
    check(rd.get("totals", {}).get("vat_note") == "Alle Preise zuzüglich 19 % MwSt.", f"{who}: #2274 only 19 % {rd.get('totals', {}).get('vat_note')}")
    r = S.get(B + f"{D}/{doc}/pdf")
    check(r.status_code == 200 and r.content.startswith(b"%PDF"), f"{who}: the PDF {r.status_code}")
    pg = pages(r.content)
    allt = "\n".join(pg)
    page_rule(pg, who + " quotation")
    check(number and number in pg[0], f"{who}: the number still in the footer / head {number}")
    # 2.114.5 (#2300): "E-Mail:" with a colon
    for want in (IBAN_PRINT, "E-Mail: post@musterfilm.example", "Steuernummer 12/345/67890", "BIC BYLADEM1001", "Tel. +49 30 123456789"):
        check(one_line(pg, want), f"{who}: #2271 #2272 {want!r} whole on one line")
    check("+4930123456789" not in allt, f"{who}: #2272 no unspaced phone in the PDF")
    check("Alle Preise zuzüglich 19 % MwSt." in allt and "7 % bzw." not in allt, f"{who}: #2274 the VAT note names 19 % only")
    check("Summe netto mit Option Rohdaten" in allt and "inklusive Rohdaten" not in allt, f"{who}: #2275 the option total")
    check(re.search(r"\b3\s*Producing", allt) and re.search(r"1\s*Tag\b", allt), f"{who}: #2276 'Producing' with number 3 and '1 Tag'")
    check("Produktionstag" not in allt, f"{who}: #2276 no formula in the PDF")
    check(not re.search(r"Kunde\s*Muster Agentur", allt) and "Muster Agentur GmbH" in allt, f"{who}: #2277 the client only in the address field")
    # ------------------------------------------------ both VAT rates, English
    doc2 = quotation(S, who, cl, "en", ITEMS + [{"title": "Music licence", "qty": 1, "unit": "flat", "rate": 100, "tax": "reduced"}])
    pg2 = pages(S.get(B + f"{D}/{doc2}/pdf").content)
    all2 = "\n".join(pg2)
    check("All prices plus 7 % or 19 % VAT." in all2, f"{who}: #2274 both rates occur -> both named")
    check("Net total with option raw data" in all2 and "including raw data" not in all2, f"{who}: #2275 English option total")
    check(re.search(r"1\s*day\b", all2) and "production day" not in all2, f"{who}: #2276 '1 day', no formula")
    page_rule(pg2, who + " quotation en", "Page {0} of {1}")
    # ------------------------------------------------ a long quotation: page x of y in the footer of every page
    doc3 = quotation(S, who, cl, "de", [{"title": f"Zusatzleistung Nr. {i + 1}", "qty": 1, "unit": "flat", "rate": 100} for i in range(40)])
    pg3 = pages(S.get(B + f"{D}/{doc3}/pdf").content)
    n = len(pg3)
    check(n >= 2 and all(squash(f"Seite {i + 1} von {n}") in squash(t) for i, t in enumerate(pg3)), f"{who}: #2282 every page of {n} numbered")
    check(squash(pg3[0]).count(squash(f"Seite 1 von {n}")) == 1, f"{who}: #2273 'Seite 1 von n' only once on page 1 (the footer)")
    # ------------------------------------------------ a document from a template: the quotation's footer columns
    r = S.post(B + O + "/doc-templates", json={"starter": "contract"})
    check(r.status_code == 201, f"{who}: a template from the sample {r.status_code} {r.text[:200]}")
    r = S.post(B + O + "/gen-docs", json={"template_id": r.json().get("id"), "client_id": cl})
    check(r.status_code == 201, f"{who}: a document {r.status_code} {r.text[:200]}")
    r = S.get(B + O + f"/gen-docs/{r.json().get('id')}/pdf")
    check(r.ok and r.content.startswith(b"%PDF"), f"{who}: the document PDF {r.status_code}")
    pgd = pages(r.content)
    for want in (IBAN_PRINT, "Steuernummer 12/345/67890", "Beispielbank Berlin", "E-Mail: post@musterfilm.example", "Tel. +49 30 123456789"):
        check(one_line(pgd, want), f"{who}: #2284 the document footer has {want!r} on one line")
    page_rule(pgd, who + " document")
    # ------------------------------------------------ without bank data: no empty column, no IBAN word
    bare = {k: "" for k in ("iban", "bic", "bank_name", "tax_number", "register_court", "register_no", "managing_directors")}
    check(S.put(B + O + "/settings", json={"company_fields": bare}).ok, f"{who}: bank and register data removed")
    pgb = pages(S.get(B + f"{D}/{doc}/pdf").content)
    check("IBAN" not in "\n".join(pgb) and "Steuernummer" not in "\n".join(pgb) and one_line(pgb, "E-Mail: post@musterfilm.example"),
          f"{who}: #2284 without bank data the footer keeps address + contact only")


# ---------------------------------------------------------------- an organisation's office
scenario(A, "org")

# ---------------------------------------------------------------- a person without an organisation (personal office)
# freelancer-matrix: office
o = F.get(B + O + "/settings").json()
check(o.get("personal") == 1, f"freelancer: the personal office {o.get('personal')}")
scenario(F, "freelancer")

check(len(ONE_PAGE) >= 2, f"#2282: at least two one-page PDFs checked {ONE_PAGE}")
print(f"p21144_a_api: {OKS[0]} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
