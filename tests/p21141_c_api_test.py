#!/usr/bin/env python3
"""2.114.1 API tests, part C (#2258): the transfer of rights of a quotation PDF on its own last page (an appendix).
Invented names and amounts only.
 - a quotation with rights and a printed part (DE): the rights title + rows stand only on the last page, after the part's
   page; the main pages carry the short line "Rechteübertragung siehe Anhang" above the signature and the order
   confirmation, the signature follows the totals / the closing text
 - the same in English ("TRANSFER OF RIGHTS", "Transfer of rights see appendix")
 - without a rights block: no line, no extra page (one page less than with rights)
 - an organisation's office and a person without an organisation (own personal office) alike
usage: p21141_c_api_test.py <datadir>      (a fresh container; P21141C_NOSTART=1 = the server already runs)
P21141C_SHOTS=<dir> (shots: 'P21141C_SHOTS'): the PDFs and, with pdftoppm, PNGs of the signature page and the appendix there."""
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
D = "/api/office/docs"
SHOTS = os.environ.get("P21141C_SHOTS") or ""
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def squash(s):
    return re.sub(r"\s+", "", s or "")


def pages(data):
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages]


def shot(name, data, page_nos):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    pdf_path = os.path.join(SHOTS, name + ".pdf")
    with open(pdf_path, "wb") as fh:
        fh.write(data)
    if shutil.which("pdftoppm"):
        for no in page_nos:
            subprocess.run(["pdftoppm", "-png", "-r", "90", "-f", str(no), "-l", str(no), "-singlefile", pdf_path,
                            os.path.join(SHOTS, f"{name}-p{no}")], check=False)


if not os.environ.get("P21141C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done"})
FID, F = freelancer(B, A)

RIGHTS = {"de": {"time": "unbegrenzt", "territory": "weltweit", "media": "intern, web, unpaid media", "note": "Im Übrigen gelten unsere AGB."},
          "en": {"time": "in perpetuity", "territory": "worldwide", "media": "internal use, web", "note": "Otherwise, our terms apply."}}
TXT = {"de": {"title": "RECHTEÜBERTRAGUNG", "see": "Rechteübertragung siehe Anhang", "sign": "Mit freundlichen Grüßen", "accept": "AUFTRAGSERTEILUNG",
             "acc_see": "Auftragserteilung per Unterschrift auf Seite {0}"},
       "en": {"title": "TRANSFEROFRIGHTS", "see": "Transfer of rights see appendix", "sign": "Kind regards", "accept": "ORDERCONFIRMATION",
             "acc_see": "Order confirmation by signature on page {0}"}}


def scenario(S, who):
    for lang in ("de", "en"):
        t, rt = TXT[lang], RIGHTS[lang]
        r = S.post(B + D, json={"kind": "offer", "lang": lang, "project_title": f"Imagefilm {who} {lang}",
                                "items": [{"title": "Konzept", "qty": 1, "rate": 800}]})
        check(r.status_code == 201, f"{who} {lang}: create quotation {r.status_code} {r.text[:200]}")
        doc = r.json().get("id")
        r = S.patch(B + f"{D}/{doc}", json={"rights": rt, "closing": "Wir freuen uns auf die Zusammenarbeit." if lang == "de" else "We look forward to working with you."})
        check(r.ok, f"{who} {lang}: rights set {r.text[:200]}")
        r = S.post(B + f"{D}/{doc}/parts", json={"title": "Interaktives Modul", "print": 1})
        check(r.status_code == 201, f"{who} {lang}: a printed part {r.text[:200]}")
        pid = (r.json().get("part") or {}).get("id")
        S.put(B + f"{D}/{doc}/parts/{pid}/items", json={"items": [{"title": "Animation", "qty": 2, "rate": 500}]})
        r = S.get(B + f"{D}/{doc}/pdf")
        check(r.status_code == 200 and r.content.startswith(b"%PDF"), f"{who} {lang}: the PDF {r.status_code}")
        pg = pages(r.content)
        n = len(pg)
        check(n >= 3, f"{who} {lang}: main page, part page, rights appendix ({n} pages)")
        check(t["title"] in squash(pg[-1]) and rt["time"] in pg[-1] and rt["territory"] in pg[-1] and rt["note"] in pg[-1],
              f"{who} {lang}: the rights title, rows and note on the last page")
        check(not any(t["title"] in squash(x) or rt["note"] in x for x in pg[:-1]), f"{who} {lang}: the rights only on the last page")
        check(squash("Interaktives Modul").upper() in squash(pg[-2]).upper() and "Animation" in pg[-2], f"{who} {lang}: the part's page comes before the appendix")
        check(not any(squash(t["see"]) in squash(x) for x in pg[-2:]), f"{who} {lang}: the reference line not on the part / appendix pages")
        main = squash("\n".join(pg[:-2]))
        # 2.114.5 (#2300): the order confirmation moved behind the appendix; the main page names its page
        i_see, i_sign, i_ref = main.find(squash(t["see"])), main.find(squash(t["sign"])), main.find(squash(t["acc_see"].format(n)))
        check(0 <= i_see < i_ref < i_sign and t["accept"] not in main, f"{who} {lang}: reference lines, then signature; no order confirmation on the main page ({i_see} {i_ref} {i_sign})")
        check(squash(pg[-1]).find(t["title"]) < squash(pg[-1]).find(t["accept"]), f"{who} {lang}: the order confirmation follows the rights on the last page")
        check(squash(f"Seite {n} von {n}" if lang == "de" else f"Page {n} of {n}") in squash(pg[-1]), f"{who} {lang}: the appendix carries 'page n of n'")
        if who == "org":
            shot(f"kva-{lang}", r.content, [1, n])
        # without rights: no line, no extra page
        r = S.patch(B + f"{D}/{doc}", json={"rights": {"time": "", "territory": "", "media": "", "exceptions": "", "exclusive": 0, "note": ""}})
        check(r.ok, f"{who} {lang}: rights cleared {r.text[:200]}")
        r = S.get(B + f"{D}/{doc}/pdf")
        pg2 = pages(r.content)
        check(len(pg2) == n - 1, f"{who} {lang}: without rights one page less ({len(pg2)} vs {n})")
        check(not any(squash(t["see"]) in squash(x) or t["title"] in squash(x) for x in pg2), f"{who} {lang}: without rights no reference line, no rights title")
        check("Animation" in pg2[-1], f"{who} {lang}: without rights the part's page is the last one")
        # 2.114.5 (#2300): without rights the order confirmation follows the part, page 1 names that page
        check(t["accept"] in squash(pg2[-1]) and squash(t["acc_see"].format(len(pg2))) in squash(pg2[0]), f"{who} {lang}: order confirmation behind the part")


# ---------------------------------------------------------------- an organisation's office
scenario(A, "org")

# ---------------------------------------------------------------- a person without an organisation (personal office)
# freelancer-matrix: office
o = F.get(B + "/api/office/settings").json()
check(o.get("personal") == 1, f"freelancer: the personal office {o.get('personal')}")
scenario(F, "freelancer")

print(f"p21141_c_api: {OKS[0]} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
