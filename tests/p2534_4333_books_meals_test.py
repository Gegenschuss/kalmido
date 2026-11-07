#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.534.0 (#4333) API tests: the approved entertainment receipts (office/meals.py) count in the bookkeeping. Own container
(start.sh, org encryption on). Invented companies, people and figures only.
 - a draft counts nowhere; an approved meal (food 119.00 at 19 %, drinks 21.40 at 7 %, tip 10: gross 150.40, input tax
   20.40, net 130.00, 70 % = 91.00, 30 % = 39.00) is the EUeR line "Entertainment (70 % deductible)" with net 91.00 and the
   full input tax, the 30 % and the double-count hint are named in the notes; field 66 of its quarter carries 20.40, the
   other quarter nothing; the neutral export has a 70 % row per VAT rate with the tax and the rate (2.616.0, #4563: the tip
   at 0 %) and one 30 % row without
 - a small business: 70 % of the gross amount (105.28), no input tax, no VAT return figures
 - a person without an organisation (freelancer-matrix: office): the same in the personal office
usage: p2534_4333_books_meals_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"
M = O + "/meals"
FEAT = "cal,comments,collab,office,clients,docs"

if os.environ.get("P2534M_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
for _ in range(100):  # the server is up once setup answers (a real state, not a fixed time)
    try:
        r = s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"})
        break
    except requests.ConnectionError:
        time.sleep(0.2)
assert r.ok, r.text
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR"}).ok, "setup: office settings")


def full(host, **kw):
    b = {"date": "2025-05-14", "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
         "occasion": "Negotiation of the follow-up order for the spring campaign", "host": {"id": host},
         "guests": [{"name": "Gina Gast", "extra": "Example GmbH, buyer"}],
         "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}, {"kind": "drinks", "rate": 7, "gross": "21.40"}], "tip": "10"}
    b.update(kw)
    return b


def line(eu):
    return next((x for x in eu.get("expenses", []) if x["key"] == "m:"), None)


def books(s, who, host):
    """The whole flow in the office s works in (an organisation or the personal office)."""
    r = s.post(B + M, json=full(host))
    check(r.status_code == 201, f"{who}: a draft meal {r.status_code} {r.text[:200]}")
    mid = r.json()["id"]
    eu = s.get(B + O + "/books/euer?year=2025").json()
    check(line(eu) is None and eu.get("meals") is None and eu["expense_total"]["net"] == "0.00", f"{who}: a draft counts nowhere {eu.get('expenses')}")
    check(s.get(B + O + "/books/ustva?year=2025&period=q2").json()["kz"]["66"] == "0.00", f"{who}: a draft has no input tax")
    check(s.post(B + f"{M}/{mid}/approve").ok, f"{who}: approved")
    eu = s.get(B + O + "/books/euer?year=2025").json()
    ln = line(eu)
    check(ln and (ln["net"], ln["vat"], ln["gross"], ln["count"]) == ("91.00", "20.40", "111.40", 1),
          f"{who}: EUeR line 70 % of the net amount + the full input tax {ln}")
    check(ln and "70 %" in ln["label"], f"{who}: the line says 70 % {ln}")
    check(eu["expense_total"]["net"] == "91.00" and eu["profit"] == "-91.00", f"{who}: in the totals and the profit {eu['expense_total']} {eu['profit']}")
    mm = eu.get("meals") or {}
    check((mm.get("count"), mm.get("deductible"), mm.get("not_deductible"), mm.get("vat")) == (1, "91.00", "39.00", "20.40"), f"{who}: the summary {mm}")
    notes = " ".join(mm.get("notes") or [])
    check("39" in notes and "30 %" in notes and "twice" in notes and all(n in eu["notes"] for n in mm.get("notes") or ["-"]),
          f"{who}: the 30 % and the double-count hint in the notes {mm.get('notes')}")
    u = s.get(B + O + "/books/ustva?year=2025&period=q2").json()
    check(u["kz"]["66"] == "20.40" and any(x["kind"] == "meal" and x["vat"] == "20.40" and "Trattoria" in x["title"] for x in u["items"]),
          f"{who}: field 66 carries the full input tax, the meal among the entries {u['kz']['66']}")
    check(s.get(B + O + "/books/ustva?year=2025&period=q1").json()["kz"]["66"] == "0.00", f"{who}: another quarter has none")
    r = s.get(B + O + "/books/export?from=2025-01-01&to=2025-12-31")
    txt = r.content.decode("utf-8-sig") if r.ok else ""
    rows = [x for x in txt.split("\r\n") if "Trattoria" in x]
    ded = [x for x in rows if "70 %" in x]
    nd = [x for x in rows if "30 %" in x]
    # 2.616.0 (#4563): one 70 % row per VAT rate (19 %: 70.00 + 19.00, 7 %: 14.00 + 1.40, the tip at 0 %: 7.00), tax_pct filled;
    # before, one 70 % row (91.00 + 20.40) with an empty rate. The organisation's office writes "," as decimal mark (de).
    cells = [x.split(";") if ";" in x else x.split(",") for x in ded]
    got = sorted(((c_[6], c_[7], c_[8], c_[9]) for c_ in cells), key=lambda x: x[0]) if all(len(c_) >= 12 for c_ in cells) else []
    want = [("0", "-7,00", "", "-7,00"), ("19", "-70,00", "-19,00", "-89,00"), ("7", "-14,00", "-1,40", "-15,40")]
    check(r.ok and len(rows) == 4 and len(ded) == 3 and len(nd) == 1, f"{who}: #4563: the export has three 70 % rows and one 30 % row {rows} {r.status_code}")
    check([tuple(v.replace(".", ",") for v in g) for g in got] == want, f"{who}: #4563: a 70 % row per rate with its tax and rate {got}")
    check(nd and ("-39,00" in nd[0] or "-39.00" in nd[0]), f"{who}: export 30 % row {nd}")
    # a small business: no input tax, 70 % of the gross amount
    check(s.put(B + O + "/settings", json={"small_business": True}).ok, f"{who}: small business on")
    eu = s.get(B + O + "/books/euer?year=2025").json()
    ln = line(eu)
    check(ln and (ln["net"], ln["vat"], ln["gross"]) == ("105.28", "0.00", "105.28") and eu["profit"] == "-105.28",
          f"{who}: small business: 70 % of the gross amount, no input tax {ln} {eu['profit']}")
    check((eu.get("meals") or {}).get("not_deductible") == "45.12", f"{who}: small business: 30 % of the gross amount not deductible {eu.get('meals')}")
    check(s.get(B + O + "/books/ustva?year=2025&period=q2").json().get("small_business") is True, f"{who}: small business: no VAT return figures")
    check(s.put(B + O + "/settings", json={"small_business": False}).ok, f"{who}: small business off again")


books(A, "org", ALICE)

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
books(Fr, "freelancer", FID)
check(line(A.get(B + O + "/books/euer?year=2025").json())["count"] == 1, "the organisation still counts its one meal only")

print(f"p2534_4333_books_meals: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
