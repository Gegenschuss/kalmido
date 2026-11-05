#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.545.0 C (#4387): the rest of the office audit (2.355). Invented names and figures only.
freelancer-matrix: office
 - section 13b as the recipient: a receipt with the mark "eu" (a service of a business in another EU state) counts its
   amount as the base of field 46, the tax at 19 % in field 47 and the same as input tax in field 67; "other" (e.g. a third
   country) goes to 84 / 85 at the rate chosen (7 % here); a normal receipt stays in 66; 83 is unchanged by section 13b;
   the income statement counts the section 13b amount as net without input tax; a wrong mark answers 400
 - the same for a person without an organisation (own office)
usage: p2545_c_buero_test.py <datadir>"""
import os
import subprocess
import sys
import time
from decimal import Decimal

import requests

import testclock
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402

FEAT = "cal,comments,collab,office,clients,docs,travel,time"
O = "/api/office"
D = O + "/docs"
BK = O + "/books"
Y = testclock.today().year
COMPANY = {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg", "country": "DE",
           "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}

subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)


def office(s):
    r = s.put(B + O + "/settings", json={"company": {"name": COMPANY["name"]}, "lang": "en", "currency": "EUR", "company_fields": COMPANY,
                                         "payment_days": 14})
    check(r.ok, "office settings " + r.text[:200])


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def receipt(s, name, ws, amount, day, vat, rc13b=None):
    """A receipt document in workspace ws with amount / date / VAT rate (and the section 13b mark) set by hand."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf(name), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    for _ in range(120):  # the recognition is done (a real state, not a fixed wait)
        if s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"):
            break
        time.sleep(0.25)
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "currency": "EUR", "date": day})
    assert r.ok, r.text
    b = {"category": "Software", "vat_pct": vat, "keep": True}
    if rc13b is not None:
        b["rc13b"] = rc13b
    r = s.put(B + f"/api/docs/{nid}/receipt", json=b)
    assert r.ok, r.text
    return nid, r.json()


def ustva(s, period):
    r = s.get(B + BK + f"/ustva?year={Y}&period={period}")
    check(r.ok, "UStVA " + r.text[:200])
    return r.json()


# ---------------------------------------------------------------- section 13b receipts (organisation)
def r13b_office(s, ws, who):
    office(s)
    n1, st = receipt(s, f"{who}-cloud-ie.pdf", ws, "1000.00", f"{Y}-03-10", "0", "eu")
    check(st["receipt"].get("rc13b") == "eu", f"{who}: the receipt keeps the mark eu {st.get('receipt')}")
    receipt(s, f"{who}-print-us.pdf", ws, "500.00", f"{Y}-03-11", "7", "other")
    receipt(s, f"{who}-paper.pdf", ws, "119.00", f"{Y}-03-12", "19")
    r = s.put(B + f"/api/docs/{n1}/receipt", json={"category": "Software", "rc13b": "xx"})
    check(r.status_code == 400, f"{who}: a wrong mark answers 400 {r.status_code}")
    d = ustva(s, "m03")
    kz = d.get("kz", {})
    want = {"46": "1000", "47": "190.00", "84": "500", "85": "35.00", "67": "225.00", "66": "19.00", "83": "-19.00"}
    check(all(kz.get(k) == v for k, v in want.items()), f"{who}: fields 46/47, 84/85, 67, 66, 83 {kz}")
    check(d.get("missing_vat") == 0, f"{who}: section 13b receipts are not 'without VAT rate' {d.get('missing_vat')}")
    eu = s.get(B + O + f"/books/euer?year={Y}").json()
    check(Decimal(eu["expense_total"]["net"]) == Decimal("1600.00") and Decimal(eu["expense_total"]["vat"]) == Decimal("19.00"),
          f"{who}: income statement: section 13b amounts net without input tax {eu.get('expense_total')}")
    r = s.put(B + f"/api/docs/{n1}/receipt", json={"category": "Software", "rc13b": ""})
    check(r.ok and not r.json()["receipt"].get("rc13b"), f"{who}: the mark goes off again " + r.text[:200])
    kz = ustva(s, "m03").get("kz", {})
    check(kz.get("46") == "0" and kz.get("67") == "35.00", f"{who}: without the mark the receipt leaves 46 / 67 {kz}")


r13b_office(A, f"org:{ORG}", "Alpha")
r13b_office(Fr, "private", "Frida")

print(f"p2545_c_buero: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
