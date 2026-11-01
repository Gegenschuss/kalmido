#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.480.0 C (#3528) API tests: declining depreciation (degressive AfA) as a choice per device. Invented devices and figures only.
 - a device bought 15.09.2025 for 10,000 net, 10 years: declining = 30 % by the month in the purchase year (1,000), then 30 % of
   the book value (2,700, 1,890 ...), the switch to linear once that gives more (§ 7 Abs. 3 EStG), the years add up to the price
 - the book value today follows the declining plan; auto / linear = the linear plan as before; a low-value asset stays one
 - only for a purchase from 01.07.2025 to 31.12.2027: a purchase in 2024 or 2028 is 400, also when only the date moves out
 - the profit statement (EUeR) takes the year's declining depreciation
 - a member never gets the choice; the person without organisation (personal office) does the same
tenant-matrix: office
freelancer-matrix: office
usage: p2480_c_afa_test.py <datadir>"""
import os
import sys
from decimal import ROUND_HALF_UP, Decimal

import requests
import testclock
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402  tests/kt.py
O = "/api/office"
E = O + "/equipment"
FEAT = "cal,comments,collab,office,clients,docs"


def m2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decl_plan(net, y, m, life):
    """The expected declining plan: rate = min(3 x linear, 30 %); by the month in the purchase year; linear (book / remaining
    months) from the year it gives more; the last months take the rest."""
    net = Decimal(net)
    rate = min(Decimal(36) / life, Decimal("0.30"))
    out, book, used, yr, lin = [], net, 0, y, False
    while book > 0 and used < life:
        mm = min(12 - m + 1 if yr == y else 12, life - used)
        rem = life - used
        if rem <= mm:
            afa = book
        else:
            a_lin, a_dec = m2(book * mm / rem), m2(book * rate * mm / 12)
            lin = lin or a_lin >= a_dec
            afa = a_lin if lin else a_dec
        book -= afa
        out.append({"year": yr, "afa": f"{afa:.2f}", "book": f"{book:.2f}", "mode": "linear" if lin else "declining"})
        used, yr = used + mm, yr + 1
    return out


def row(s, rid):
    return next((x for x in s.get(B + E + "?archived=1").json()["items"] if x["id"] == rid), None)


s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
TODAY = testclock.today()

# ---------------------------------------------------------------- the plan of the example
r = A.post(B + E, json={"name": "Kamera Beispiel", "category": "Kamera", "purchase_date": "2025-09-15", "purchase_net": "10000",
                        "life_months": 120, "afa_method": "declining"})
check(r.status_code == 201, "a device with declining depreciation " + r.text[:200])
CAM = r.json()["id"]
c1 = row(A, CAM)
P = c1["afa_plan"]
check(c1["afa_method"] == "declining" and c1["method"] == "declining" and c1["declining_ok"] is True and c1["declining_pct"] == "30.00",
      f"the choice and the rate come back {c1.get('afa_method')} {c1.get('method')} {c1.get('declining_pct')}")
check(P[:3] == [{"year": 2025, "afa": "1000.00", "book": "9000.00", "mode": "declining"},
                {"year": 2026, "afa": "2700.00", "book": "6300.00", "mode": "declining"},
                {"year": 2027, "afa": "1890.00", "book": "4410.00", "mode": "declining"}],
      f"2025: 30 % x 4/12 = 1,000; 2026: 30 % of 9,000 = 2,700; 2027: 30 % of 6,300 = 1,890 {P[:3]}")
check(P == decl_plan("10000", 2025, 9, 120), f"the whole plan {P}")
sw = next((p for p in P if p["mode"] == "linear"), None)
check(sw is not None and sw["year"] == 2033 and sw["afa"] == "277.95" and P[P.index(sw) - 1]["mode"] == "declining",
      f"switch to linear in 2033 (book 741.19 over 32 months gives more than 30 %) {sw}")
check(P[-1]["year"] == 2035 and P[-1]["book"] == "0.00" and sum(Decimal(p["afa"]) for p in P) == Decimal("10000"),
      f"down to 0 at the end of the useful life, the years add up {P[-1]}")
exp_year = next((p["afa"] for p in P if p["year"] == TODAY.year), "0.00")
check(c1["afa_year"] == exp_year, f"the depreciation of this year {c1['afa_year']} / {exp_year}")
# the book value today: the book value at the start of the year less the year's part by the month
start = Decimal("10000")
for p in P:
    if p["year"] == TODAY.year:
        months = 4 if p["year"] == 2025 else 12
        k = min(TODAY.month - (9 if p["year"] == 2025 else 1) + 1, months)
        exp_book = start - (Decimal(p["afa"]) if k >= months else m2(Decimal(p["afa"]) * k / months))
        break
    start = Decimal(p["book"])
else:
    exp_book = start
check(c1["book_value"] == f"{exp_book:.2f}" and c1["current_value_eff"] == c1["book_value"], f"book value today {c1['book_value']} / {exp_book}")

# ---------------------------------------------------------------- linear again, auto, low-value asset
r = A.patch(B + f"{E}/{CAM}", json={"afa_method": "linear"})
c2 = row(A, CAM)
check(r.ok and c2["method"] == "linear" and c2["afa_plan"][0] == {"year": 2025, "afa": "333.33", "book": "9666.67"},
      f"back to linear: 10,000 x 4/120 {c2['afa_plan'][:1]}")
A.patch(B + f"{E}/{CAM}", json={"afa_method": "declining"})
r = A.post(B + E, json={"name": "Licht Klein", "category": "Licht", "purchase_date": "2025-10-01", "purchase_net": "500"})
LI = r.json()["id"]
check(row(A, LI)["afa_method"] == "auto" and row(A, LI)["method"] == "gwg", "a new device without a choice: auto")
r = A.patch(B + f"{E}/{LI}", json={"afa_method": "declining"})
check(r.ok and row(A, LI)["method"] == "gwg" and row(A, LI)["afa_plan"] == [{"year": 2025, "afa": "500.00", "book": "0.00"}],
      "a low-value asset stays one with declining chosen")
r = A.post(B + E, json={"name": "Laptop Kurz", "category": "Laptop", "purchase_date": "2026-01-10", "purchase_net": "1200", "afa_method": "declining"})
lp = row(A, r.json()["id"])
check(r.status_code == 201 and lp["declining_pct"] == "30.00" and lp["afa_plan"] == [{"year": 2026, "afa": "1200.00", "book": "0.00", "mode": "declining"}],
      f"a useful life of one year: written off in the year {lp.get('afa_plan')}")

# ---------------------------------------------------------------- the window
r = A.post(B + E, json={"name": "Stativ Alt", "category": "Stativ", "purchase_date": "2024-05-02", "purchase_net": "2000", "afa_method": "declining"})
check(r.status_code == 400 and "2025" in r.text, "a purchase in 2024 is refused with a clear message " + r.text[:160])
r = A.post(B + E, json={"name": "Stativ Alt", "category": "Stativ", "purchase_date": "2024-05-02", "purchase_net": "2000"})
OLD = r.json()["id"]
check(row(A, OLD)["declining_ok"] is False and row(A, OLD)["declining_pct"] is None and row(A, OLD)["method"] == "linear", "outside the window: no choice offered")
check(A.patch(B + f"{E}/{OLD}", json={"afa_method": "declining"}).status_code == 400, "and none taken for a purchase in 2024")
check(A.post(B + E, json={"name": "Spaet", "purchase_date": "2028-01-01", "purchase_net": "2000", "afa_method": "declining"}).status_code == 400,
      "a purchase in 2028 is refused")
check(A.post(B + E, json={"name": "Ohne Datum", "purchase_net": "2000", "afa_method": "declining"}).status_code == 400, "no purchase day: refused")
check(A.post(B + E, json={"name": "Grenze", "purchase_date": "2025-07-01", "purchase_net": "2000", "afa_method": "declining"}).status_code == 201
      and A.post(B + E, json={"name": "Grenze 2", "purchase_date": "2027-12-31", "purchase_net": "2000", "afa_method": "declining"}).status_code == 201,
      "01.07.2025 and 31.12.2027 are inside")
check(A.patch(B + f"{E}/{CAM}", json={"purchase_date": "2025-06-30"}).status_code == 400 and row(A, CAM)["purchase_date"] == "2025-09-15",
      "moving the purchase day of a declining device out of the window is refused")
check(A.patch(B + f"{E}/{CAM}", json={"afa_method": "nonsense"}).status_code == 400, "an unknown method is 400")

# ---------------------------------------------------------------- profit statement, member
eu = A.get(B + O + "/books/euer?year=2026").json()
dep = next((x for x in eu.get("expenses", []) if x["label"] == "Depreciation"), None)
exp26 = sum((Decimal(p["afa"]) for x in A.get(B + E + "?archived=1").json()["items"] for p in (x.get("afa_plan") or []) if p["year"] == 2026), Decimal(0))
check(dep and dep["net"] == f"{exp26:.2f}" and exp26 >= Decimal("2700"), f"EUeR 2026 takes the declining 2,700 of the camera {dep} / {exp26}")
bm = next((x for x in Bo.get(B + E).json().get("items", []) if x["id"] == CAM), {})
check("afa_method" not in bm and "afa_plan" not in bm, f"a member never gets the choice {sorted(bm)}")
check(Bo.patch(B + f"{E}/{CAM}", json={"afa_method": "linear"}).status_code in (403, 404) and row(A, CAM)["afa_method"] == "declining",
      "a member cannot change it")

# ---------------------------------------------------------------- the person without organisation
FID, Fr = freelancer(B, A)
r = Fr.post(B + E, json={"name": "Drohne Solo", "category": "Drohne", "purchase_date": "2025-09-15", "purchase_net": "10000",
                         "life_months": 120, "afa_method": "declining"})
check(r.status_code == 201, "personal office: declining " + r.text[:160])
d1 = row(Fr, r.json()["id"])
check(d1["afa_plan"] == P, f"personal office: the same plan {d1.get('afa_plan', [])[:2]}")
check(Fr.post(B + E, json={"name": "Alt", "purchase_date": "2024-01-01", "purchase_net": "2000", "afa_method": "declining"}).status_code == 400,
      "personal office: a purchase in 2024 is refused")
eu = Fr.get(B + O + "/books/euer?year=2026").json()
dep = next((x for x in eu.get("expenses", []) if x["label"] == "Depreciation"), None)
check(dep and dep["net"] == "2700.00", f"personal office: EUeR 2026 = 2,700 {dep}")
check(Fr.get(B + E + "/value").json()["sums"]["afa_year"] == exp_year, "personal office: the insurance list sums the declining year")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
