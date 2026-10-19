#!/usr/bin/env python3
"""2.122.4 API tests, part B (#2261, #2316, #2317). Invented names and amounts only.
 - #2261: a quotation with exceptions + exclusive: the PDF (de and en) names each of them exactly once
 - #2316: an entertainment-receipt bill raises /api/me/storage "used"
 - #2317: free text starting with TAB / CR / = in the entertainment CSV gets a ' in front
 - an organisation's office and a person without an organisation alike -- freelancer-matrix: office
usage: p21224_b_api_test.py <datadir>      (a fresh container; P21224B_NOSTART=1 = the server already runs)"""
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
D = "/api/office/docs"
M = "/api/office/meals"
FAILS, OKS = [], [0]
PDFB = b"%PDF-1.4\n1 0 obj<<>>endobj\n" + b"%" + b"x" * 6000 + b"\ntrailer<<>>\n%%EOF\n"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def text_of(data):
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)


if not os.environ.get("P21224B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done"})
FID, F = freelancer(B, A)

WORDS = {"de": ("Ausnahmen", "Exklusiv"), "en": ("Exceptions", "Exclusive")}


def scenario(S, who):
    # #2261: exceptions and exclusive once in the quotation PDF
    for lang in ("de", "en"):
        r = S.post(B + D, json={"kind": "offer", "lang": lang, "project_title": f"Imagefilm {who} {lang}",
                                "items": [{"title": "Konzept", "qty": 1, "rate": 800}]})
        check(r.status_code == 201, f"{who} {lang}: create quotation {r.status_code} {r.text[:200]}")
        doc = r.json().get("id")
        rt = {"time": "in perpetuity", "territory": "worldwide", "media": "web", "exceptions": "stock footage", "exclusive": 1}
        check(S.patch(B + f"{D}/{doc}", json={"rights": rt}).ok, f"{who} {lang}: rights set")
        r = S.get(B + f"{D}/{doc}/pdf")
        check(r.status_code == 200 and r.content.startswith(b"%PDF"), f"{who} {lang}: the PDF {r.status_code}")
        txt = text_of(r.content)
        w_ex, w_excl = WORDS[lang]
        check(len(re.findall(w_ex, txt)) == 1, f"{who} {lang}: '{w_ex}' once ({len(re.findall(w_ex, txt))})")
        check(len(re.findall(w_excl, txt)) == 1, f"{who} {lang}: '{w_excl}' once ({len(re.findall(w_excl, txt))})")
        check(len(re.findall("stock footage", txt)) == 1, f"{who} {lang}: the exceptions text once")

    # #2316: the bill of an entertainment receipt counts for the quota
    used0 = S.get(B + "/api/me/storage").json().get("used", 0)
    r = S.post(B + M, json={"date": "2025-05-14", "place_name": "\t=1+1", "place_address": "Beispielweg 1", "occasion": "\r=cmd|' /C calc'!A0",
                            "host": {"name": "Gina Gast", "extra": ""}, "guests": [],
                            "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}], "tip": "0"})
    check(r.status_code == 201, f"{who}: meal created {r.status_code} {r.text[:200]}")
    mid = r.json().get("id")
    r = S.post(B + f"{M}/{mid}/file", files={"file": ("bill.pdf", PDFB, "application/pdf")})
    check(r.status_code == 201, f"{who}: bill attached {r.status_code} {r.text[:200]}")
    used1 = S.get(B + "/api/me/storage").json().get("used", 0)
    check(used1 - used0 >= len(PDFB), f"{who}: storage used rises by the bill ({used0} -> {used1})")

    # #2317: formula guard in the CSV
    r = S.get(B + M + "/report?year=2025&format=csv")
    check(r.status_code == 200, f"{who}: meals csv {r.status_code}")
    body = r.content.decode("utf-8-sig", "replace")
    # the input cleaning may drop the leading TAB / CR; either way no cell may start with a formula character
    cells = [x.strip('"') for line in body.replace("\r", "\n").split("\n") for x in line.split(";")]
    check("'=1+1" in body or "'\t=1+1" in body, f"{who}: the TAB-led place gets a ' in front")
    check("'=cmd" in body or "'\r=cmd" in body, f"{who}: the CR-led occasion gets a ' in front")
    check(not any(x.startswith(("=", "+", "@", "\t")) for x in cells), f"{who}: no cell starts with a formula character")


scenario(A, "org")
# freelancer-matrix: office
check(F.get(B + "/api/office/settings").json().get("personal") == 1, "freelancer: the personal office")
scenario(F, "freelancer")

print(f"p21224_b_api: {OKS[0]} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
