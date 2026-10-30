#!/usr/bin/env python3
"""2.114.5 API tests (#2300 with #2270): page 1 of the quotation PDF tightened. Invented names and amounts only.
 - the order confirmation (#2270, when on) moves behind the rights appendix / the last printed part; page 1 names the page
   ("Auftragserteilung per Unterschrift auf Seite n"); switched off (setting or per quotation): neither block nor line;
   without appendix and parts it stays below the signature, without a line
 - no "Dieses Angebot ist gültig bis" sentence below the table (the head has "Gültig bis"), no "Kunde" row, no page
   count next to the title
 - one VAT rate -> no VAT column, the note names that rate; mixed rates -> the column stays, both rates named
 - the option as three rows of the totals: "Summe netto", "+ Optional: …", "Summe netto mit Option Rohdaten"; no
   "inklusive Rohdaten", no "… € netto" box
 - footer: "E-Mail: x" with a colon
 - 3 and 8 positions with and without option; 8 positions with the appendix: the totals stay on page 1
 - a finalised quotation keeps its block and line
 - an organisation's office and a person without an organisation (own personal office) alike
usage: p21145_api_test.py <datadir>      (a fresh container; P21145_NOSTART=1 = the server already runs)
P21145_SHOTS=<dir> (shots: 'P21145_SHOTS'): the PDFs and, with pdftoppm, PNGs of page 1 and the last page."""
import io
import os
import re
import shutil
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
SHOTS = os.environ.get("P21145_SHOTS") or ""
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def squash(s):
    return re.sub(r"\s+", "", s or "")


def pages(data):
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages]


def shot(name, data, n):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    pdf_path = os.path.join(SHOTS, name + ".pdf")
    with open(pdf_path, "wb") as fh:
        fh.write(data)
    if shutil.which("pdftoppm"):
        for no in sorted({1, n}):
            subprocess.run(["pdftoppm", "-png", "-r", "70", "-f", str(no), "-l", str(no), "-singlefile", pdf_path,
                            os.path.join(SHOTS, f"{name}-p{no}")], check=False)


if not os.environ.get("P21145_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done"})
FID, F = freelancer(B, A)

COMPANY = {"name": "Musterfilm - Beispiel, Probe & Partner eGbR", "street": "Musterstraße 127", "zip": "10115", "city": "Berlin", "country": "DE",
           "email": "post@musterfilm.example", "phone": "+4930123456789", "tax_number": "12/345/67890", "iban": "DE02120300000000202051",
           "bic": "BYLADEM1001", "bank_name": "Beispielbank Berlin", "register_court": "Amtsgericht Berlin", "register_no": "GsR 4711",
           "managing_directors": "Erika Beispiel, Max Mustermann & Paula Probe", "md_label": "shareholders"}
RIGHTS = {"time": "unbegrenzt", "territory": "weltweit", "media": "intern, web, unpaid media", "note": "Im Übrigen gelten unsere AGB."}
NO_RIGHTS = {"time": "", "territory": "", "media": "", "exceptions": "", "exclusive": 0, "note": ""}
ACC, ACC_SEE, RIGHTS_T = "AUFTRAGSERTEILUNG", "Auftragserteilung per Unterschrift auf Seite {0}", "RECHTEÜBERTRAGUNG"
OPT_ROW, INC_ROW = "+ Optional: Bereitstellung der Rohdaten", "Summe netto mit Option Rohdaten"


def items(n, mixed=False, option=True):
    out = [{"title": "Konzept und Drehbuch", "qty": 2, "unit": "day", "rate": 800, "raw_fee": 1 if option else 0, "detail": "Recherche, Treatment"}]
    out += [{"title": f"Leistung Nr. {i + 2}", "qty": 1, "unit": "flat", "rate": 300 + 10 * i} for i in range(n - 1)]
    if mixed:
        out[-1]["tax"] = "reduced"
    return out


def setup(S, who):
    r = S.put(B + O + "/settings", json={"company": {"name": COMPANY["name"]}, "lang": "de", "currency": "EUR", "company_fields": COMPANY,
                                          "prod_quotient": 3, "raw_factor": 0.25, "producing_rate": 600, "producing_on": 0, "raw_on": 1,
                                          "accept_on": 1})
    check(r.ok, f"{who}: settings {r.status_code} {r.text[:200]}")
    r = S.post(B + "/api/clients", json={"name": "Muster Agentur GmbH", "address": "Agenturweg 5\n50667 Köln"})
    check(r.status_code in (200, 201), f"{who}: a client {r.status_code} {r.text[:200]}")
    return r.json().get("id")


def quotation(S, who, cl, its, rights=True, title="Imagefilm"):
    r = S.post(B + D, json={"project_title": f"{title} {who}", "client_id": cl, "lang": "de", "valid_until": "2026-12-01"})
    check(r.status_code == 201, f"{who}: a quotation {r.status_code} {r.text[:200]}")
    doc = r.json().get("id")
    check(S.put(B + f"{D}/{doc}/items", json={"items": its}).ok, f"{who}: positions set")
    r = S.patch(B + f"{D}/{doc}", json={"rights": RIGHTS if rights else NO_RIGHTS, "closing": "Wir freuen uns auf die Zusammenarbeit.",
                                        "valid_until": "2026-12-01"})
    check(r.ok, f"{who}: rights / closing {r.status_code} {r.text[:200]}")
    return doc


def pdf(S, doc, name=""):
    r = S.get(B + f"{D}/{doc}/pdf")
    check(r.status_code == 200 and r.content.startswith(b"%PDF"), f"the PDF {doc} {r.status_code}")
    pg = pages(r.content)
    if name:
        shot(name, r.content, len(pg))
    return pg


def moved(pg, who, what):
    """the block on the last page behind the rights, page 1 names that page, no block on the main page"""
    n = len(pg)
    last, first = squash(pg[-1]), squash(pg[0])
    check(ACC in last, f"{who} {what}: the order confirmation on the last page")
    check(not any(ACC in squash(t) for t in pg[:-1]), f"{who} {what}: the order confirmation only on the last page")
    check(squash(ACC_SEE.format(n)) in first, f"{who} {what}: page 1 names page {n}")
    if RIGHTS_T in last:
        check(last.find(RIGHTS_T) < last.find(ACC), f"{who} {what}: behind the rights")
    i_ref, i_sign = first.find(squash(ACC_SEE.format(n))), first.find(squash("Mit freundlichen Grüßen"))
    check(0 <= i_ref < i_sign, f"{who} {what}: the line above the greeting ({i_ref} {i_sign})")


def scenario(S, who):
    cl = setup(S, who)
    # ------------------------------------------------ 3 positions, one rate, option, rights
    q3 = quotation(S, who, cl, items(3))
    pg = pdf(S, q3, f"{who}-3pos-option" if who == "org" else "")
    allt, first = "\n".join(pg), squash(pg[0])
    check(len(pg) == 2, f"{who} 3: main page + appendix ({len(pg)})")
    moved(pg, who, "3 positions")
    check(squash("POS.LEISTUNGMENGEEINZELPREISGESAMT") in first and "PREISMWST." not in first,  # 2.357.0 (#3183): Einzelpreis
          f"{who} 3: one rate -> no VAT column")
    check("Alle Preise zuzüglich 19 % MwSt." in allt and "7 %" not in allt, f"{who} 3: the note names 19 % only")
    check("gültig bis" not in allt and "Gültig bis" in pg[0], f"{who} 3: no 'gültig bis' sentence, the head has the date")
    check(not re.search(r"Kunde\s*Muster Agentur", allt), f"{who} 3: no 'Kunde' row")
    check(squash("Seite 1 von 2") in first and first.count(squash("Seite 1 von 2")) == 1, f"{who} 3: the page count once, in the footer")
    check(squash(OPT_ROW) in first and squash(INC_ROW) in first and "Summe netto" in pg[0], f"{who} 3: net, + option, net with option")  # 2.357.0 (#3183): Summe netto
    check("inklusive Rohdaten" not in allt and not re.search(r"€\s*netto", allt), f"{who} 3: no 'inklusive Rohdaten', no '… € netto' box")
    i_net, i_opt, i_inc = first.find("Summenetto"), first.find(squash(OPT_ROW)), first.find(squash(INC_ROW))  # 2.357.0 (#3183): Summe netto (the first match is the net row, the one with option follows)
    check(0 <= i_net < i_opt < i_inc, f"{who} 3: the three rows in order ({i_net} {i_opt} {i_inc})")
    check(any("E-Mail: post@musterfilm.example" in ln for t in pg for ln in t.splitlines()), f"{who}: 'E-Mail:' with a colon in the footer")
    check(any("+49 30 123456789" in ln for ln in pg[0].splitlines()), f"{who}: the phone stays grouped")
    # ------------------------------------------------ 8 positions, mixed rates, option, rights: the totals stay on page 1
    q8 = quotation(S, who, cl, items(8, mixed=True))
    pg8 = pdf(S, q8, f"{who}-8pos-mixed" if who == "org" else "")
    f8 = squash(pg8[0])
    check(squash("POS.LEISTUNGMENGEEINZELPREISMWST.GESAMT") in f8, f"{who} 8: mixed rates -> the VAT column stays")  # 2.357.0 (#3183): Einzelpreis
    check("Alle Preise zuzüglich 7 % bzw. 19 % MwSt." in "\n".join(pg8), f"{who} 8: both rates named")
    check("Leistung Nr. 8" in pg8[0] and "Summe netto" in pg8[0] and squash(INC_ROW) in f8, f"{who} 8: 8 positions and the totals on page 1")  # 2.357.0 (#3183): Summe netto
    moved(pg8, who, "8 positions")
    # ------------------------------------------------ 8 positions without option: no option rows
    q8n = quotation(S, who, cl, items(8, option=False), title="Ohne Option")
    pg8n = pdf(S, q8n)
    check("Optional" not in "\n".join(pg8n) and INC_ROW not in "\n".join(pg8n), f"{who} 8 without option: no option rows")
    moved(pg8n, who, "8 without option")
    # ------------------------------------------------ switched off per quotation: neither block nor line
    check(S.patch(B + f"{D}/{q3}", json={"accept_on": 0}).ok, f"{who}: order confirmation off for one quotation")
    pgo = pdf(S, q3, f"{who}-3pos-off" if who == "org" else "")
    check(not any(ACC in squash(t).upper() for t in pgo), f"{who} off: no block, no line")
    # 2.424.0 (#3572): look A (#3491, 2.406) drops the reference line when the rights appendix fits on page 1 - then the
    # appendix itself is on page 1; otherwise the line stays
    ref_o, app_o = squash("Rechteübertragung siehe Anhang") in squash(pgo[0]), squash(RIGHTS["territory"]) in squash(pgo[0])  # the appendix text
    check(ref_o != app_o, f"{who} off: the rights line stays, or the appendix is on page 1 ({ref_o} {app_o})")
    check(S.patch(B + f"{D}/{q3}", json={"accept_on": None}).ok, f"{who}: back to like the setting")
    # switched off in the setting
    check(S.put(B + O + "/settings", json={"accept_on": 0}).ok, f"{who}: setting off")
    check(not any(ACC in squash(t).upper() for t in pdf(S, q8)), f"{who} setting off: no block, no line")
    check(S.put(B + O + "/settings", json={"accept_on": 1}).ok, f"{who}: setting on")
    # ------------------------------------------------ without appendix and parts: stays below the signature, no line
    qn = quotation(S, who, cl, items(3), rights=False, title="Ohne Anhang")
    pgn = pdf(S, qn, f"{who}-3pos-norights" if who == "org" else "")
    fn = squash(pgn[0])
    check(len(pgn) == 1 and ACC in fn and fn.find("MitfreundlichenGrüßen") < fn.find(ACC), f"{who} no appendix: one page, block below the signature")
    check(squash(ACC_SEE.format(1)) not in fn and "Auftragserteilung per" not in pgn[0], f"{who} no appendix: no reference line")
    # ------------------------------------------------ finalised: block and line stay after the setting goes off
    r = S.post(B + f"{D}/{q8}/finalize")
    check(r.ok and r.json().get("locked") is True, f"{who}: finalised {r.text[:200]}")
    check(S.put(B + O + "/settings", json={"accept_on": 0}).ok, f"{who}: setting off after finalising")
    moved(pdf(S, q8), who, "finalised")
    check(S.put(B + O + "/settings", json={"accept_on": 1}).ok, f"{who}: setting on again")


# ---------------------------------------------------------------- an organisation's office
scenario(A, "org")

# ---------------------------------------------------------------- a person without an organisation (personal office)
# freelancer-matrix: office
o = F.get(B + O + "/settings").json()
check(o.get("personal") == 1, f"freelancer: the personal office {o.get('personal')}")
scenario(F, "freelancer")

print(f"p21145_api: {OKS[0]} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
