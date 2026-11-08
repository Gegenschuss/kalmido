#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.386.0 (#2328) API tests: the approved entertainment receipts (office/meals.py) in the DATEV booking batch
(office/datevin.py dv_meal_rows). Own container (start.sh, org encryption on). Invented companies, people and figures only.
 - a draft meal is not in the batch; an approved one (food 119.00 at 19 %, drinks 21.40 at 7 %, tip 10.00) gives per VAT
   rate two lines with Belegfeld 1 "M<id>": 70 % of the gross amount on 4650 and 30 % on 4654 (SKR03), both with the input
   tax key of the rate (9 / 8), the tip without a key -- 83.30 + 35.70, 14.98 + 6.42, 7.00 + 3.00 = 150.40 against the
   collective creditor 70000
 - the accounts route names the defaults (4650 / 4654), own accounts in the settings (meal, meal_nd) are used, a wrong value is
   400, SKR04 has 6640 / 6644
 - a receipt of the category "Bewirtung" in the same period stays in the batch, the check names it ("maybe twice")
 - a small business: 70 / 30 of the gross amount (105.28 / 45.12), no key
 - a person without an organisation (freelancer-matrix: office): the same in the personal office, nobody else's meal
usage: p2386_2328_datev_meals_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time
from decimal import Decimal

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
X = O + "/datev/extf"
ACC = O + "/datev/accounts"
P = "?from=2026-03-01&to=2026-03-31"
FEAT = "cal,comments,collab,office,clients,docs,files,travel"

if os.environ.get("P2386M_NOSTART") != "1":
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


def receipt(s, ws, name, amount, day, category="", vat=None):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    assert s.put(B + f"/api/docs/{nid}/receipt", json={"category": category, "vat_pct": vat, "keep": True}).ok
    return nid


def batch(s, q=P):
    r = s.get(B + X + q)
    assert r.ok, r.text
    return [ln.split(";") for ln in r.content.decode("cp1252").split("\r\n")[2:-1]]


def meal_lines(rows, mid):
    """[(amount, konto, gegenkonto, bu)] of the lines of meal mid, sorted."""
    return sorted((x[0], x[6], x[7], x[8].strip('"')) for x in rows if x[10].strip('"') == f"M{mid}")


def full(host, **kw):
    b = {"date": "2026-03-14", "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
         "occasion": "Negotiation of the follow-up order for the spring campaign", "host": {"id": host},
         "guests": [{"name": "Gina Gast", "extra": "Example GmbH, buyer"}],
         "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}, {"kind": "drinks", "rate": 7, "gross": "21.40"}], "tip": "10"}
    b.update(kw)
    return b


WANT = sorted([("83,30", "4650", "70000", "9"), ("35,70", "4654", "70000", "9"), ("14,98", "4650", "70000", "8"),
               ("6,42", "4654", "70000", "8"), ("7,00", "4650", "70000", ""), ("3,00", "4654", "70000", "")])


def flow(s, who, host, ws, company):
    """The whole flow in the office s works in (an organisation or the personal office)."""
    r = s.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1,
                                                                                          "acct_len": 4, "chart": "SKR03"},
                                         "company_fields": {"name": company, "street": "Teststraße 1", "zip": "20000", "city": "Hamburg", "country": "DE",
                                                            "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
                                                            "bank_name": "Beispielbank"}})
    check(r.ok, f"{who}: DATEV settings {r.text[:160]}")
    j = s.get(B + ACC).json()
    check((j.get("meal"), j.get("meal_nd")) == ("4650", "4654"), f"{who}: accounts route names the meal defaults {j.get('meal')} {j.get('meal_nd')}")
    r = s.post(B + M, json=full(host))
    check(r.status_code == 201, f"{who}: a draft meal {r.status_code} {r.text[:200]}")
    mid = r.json()["id"]
    check(meal_lines(batch(s), mid) == [], f"{who}: a draft is not in the batch")
    check(s.post(B + f"{M}/{mid}/approve").ok, f"{who}: approved")
    rows = batch(s)
    got = meal_lines(rows, mid)
    check(got == WANT, f"{who}: 70 / 30 per VAT rate with its key, the tip without {got}")
    check(sum(Decimal(x[0].replace(",", ".")) for x in got) == Decimal("150.40"), f"{who}: the lines add up to the bill incl. tip")
    check(all("Trattoria" in x[13] for x in rows if x[10].strip('"') == f"M{mid}"), f"{who}: booking text names the place")
    check(meal_lines(batch(s, P + "&in=0"), mid) == [], f"{who}: ?in=0 leaves the meals out")
    check(meal_lines(batch(s, "?from=2026-04-01&to=2026-04-30"), mid) == [], f"{who}: another period has none")
    # the check: no hint without a receipt of the category entertainment, "maybe twice" with one (it stays in the batch)
    hk = {h["key"] for h in s.get(B + X + P + "&check=1").json().get("hints", [])}
    check("meal_twice" not in hk, f"{who}: no 'maybe twice' hint without such a receipt {hk}")
    rc = receipt(s, ws, "restaurant.pdf", "59.50", "2026-03-14", "Bewirtung", "19")
    ch = s.get(B + X + P + "&check=1").json()
    h = next((x for x in ch.get("hints", []) if x["key"] == "meal_twice"), {})
    check(h.get("count") == 1 and "twice" in h.get("text", ""), f"{who}: hint 'maybe twice' {ch.get('hints')}")
    check(any(x[10].strip('"') == f"B{rc}" for x in batch(s)), f"{who}: the receipt stays in the batch")
    # own accounts, validated
    check(s.put(B + O + "/settings", json={"datev_extf": {"meal": "abc"}}).status_code == 400, f"{who}: a wrong account is 400")
    r = s.put(B + O + "/settings", json={"datev_extf": {"meal": "4651", "meal_nd": "4655"}})
    check(r.ok and (r.json()["settings"]["datev_extf"].get("meal"), r.json()["settings"]["datev_extf"].get("meal_nd")) == ("4651", "4655"),
          f"{who}: own meal accounts stored {r.text[:200]}")
    got = meal_lines(batch(s), mid)
    check({x[1] for x in got} == {"4651", "4655"}, f"{who}: own accounts used {got}")
    check(s.put(B + O + "/settings", json={"payment_days": 21}).json()["settings"]["datev_extf"].get("meal") == "4651", f"{who}: another save keeps them")
    s.put(B + O + "/settings", json={"datev_extf": {"meal": "", "meal_nd": ""}})
    # SKR04
    s.put(B + O + "/settings", json={"datev_extf": {"chart": "SKR04"}})
    j = s.get(B + ACC).json()
    check((j.get("meal"), j.get("meal_nd")) == ("6640", "6644"), f"{who}: SKR04 defaults {j.get('meal')} {j.get('meal_nd')}")
    check({x[1] for x in meal_lines(batch(s), mid)} == {"6640", "6644"}, f"{who}: SKR04 lines")
    s.put(B + O + "/settings", json={"datev_extf": {"chart": "SKR03"}})
    # a small business: 70 / 30 of the gross amount, no key
    check(s.put(B + O + "/settings", json={"small_business": True}).ok, f"{who}: small business on")
    got = meal_lines(batch(s), mid)
    check(got == sorted([("105,28", "4650", "70000", ""), ("45,12", "4654", "70000", "")]), f"{who}: small business: 70 / 30 of the gross, no key {got}")
    check(s.put(B + O + "/settings", json={"small_business": False}).ok, f"{who}: small business off again")
    return mid


MA = flow(A, "org", ALICE, f"org:{ORG}", "Studio Beispiel GmbH")

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
MF = flow(Fr, "freelancer", FID, "private", "Fiona Film")
check(meal_lines(batch(A), MF) == [] and meal_lines(batch(Fr), MA) == [], "nobody gets the other office's meal")

print(f"p2386_2328_datev_meals: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
