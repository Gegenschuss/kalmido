#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1042.0 API tests (#5815): the discount of a quotation as a fixed amount and per position, once in the personal office
of a person without an organisation (freelancer fixture; freelancer-matrix: office) and once in an organisation's office
(its admin). Invented companies, people and the test IBAN only.
 - the calculator alone (calc.calc_discount_split): an amount is spread over the tax keys by their share, the rest cent to
   the largest base, the parts add up to the amount; an amount over the discountable sum takes the sum (capped)
 - the acceptance case of the task: a quotation with 19 % and 7 %, one position with 10 % of its own and 500 EUR off the
   whole: the position 2000.00 - 200.00 = 1800.00, the 500.00 spread 321.43 / 178.57 over 19 % / 7 %, net 2300.00,
   tax 280.93 + 57.50 = 338.43, gross 2638.43 - to the cent
 - percent and amount exclude each other (an amount sets the percent to 0, a percent clears the amount); an amount over
   the discountable positions is refused (400) and nothing is stored
 - the print model, the PDF and the approval page show the position's discount
 - the invoice from the quotation: the position keeps its 10 %, the 500.00 come as one discount position per rate, the
   sums are the quotation's; finalised, its XML carries the position's discount as a line allowance (BG-27: 10 %, basis
   2000.00, amount 200.00) and the own check (einvoice.ein_check) finds nothing
 - a quotation with a part: the fixed amount is taken off the title page (part lines included), not again in the part
usage: p5815_discount_test.py <datadir>"""
import importlib.util
import os
import sys
from decimal import Decimal

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402
import requests  # noqa: E402

SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
TEST_IBAN = "DE02120300000000202051"
COMPANY = {"name": "Studio Nordlicht", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hallo@nordlicht.example", "phone": "+49 40 000000", "tax_number": "12/345/67890", "vat_id": "DE999999999",
           "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SRC, "kalmido", "office", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- the calculator alone
calc = load("calc")
ein = load("einvoice")
Z = Decimal
sp, capped = calc.calc_discount_split({"standard": Z(100), "reduced": Z(100), "exempt": Z(100)}, amount=Z(100))
check(sum(sp.values()) == Z(100) and sorted(sp.values()) == [Z("33.33"), Z("33.33"), Z("33.34")] and not capped,
      f"calc: 100.00 over three equal bases = 33.33 + 33.33 + 33.34 (the rest cent to one base): {sp}")
sp, capped = calc.calc_discount_split({"standard": Z(1800), "reduced": Z(1000), "exempt": Z(0)}, amount=Z(500))
check(sp == {"standard": Z("321.43"), "reduced": Z("178.57")} and not capped, f"calc: 500.00 by share 1800 / 1000 = 321.43 / 178.57: {sp}")
sp, capped = calc.calc_discount_split({"standard": Z(50), "reduced": Z(0), "exempt": Z(0)}, amount=Z(80))
check(sp == {"standard": Z(50)} and capped, f"calc: 80.00 on a discountable sum of 50.00 takes 50.00 (capped): {sp} {capped}")
sp, capped = calc.calc_discount_split({"standard": Z(1000), "reduced": Z(500), "exempt": Z(0)}, pct=Z(10))
check(sp == {"standard": Z(100), "reduced": Z(50)} and not capped, f"calc: the percent per key as before: {sp}")
t = calc.office_calc({"discount_amount": 0, "discount_pct": 0, "raw_mode": "none", "producing_on": 0},
                     [{"title": "Regie", "qty": 3, "rate": "33.335", "unit": "hour", "discount_pct": 12.5}])
ln = t["lines"][0]
check(ln["list_total"] == 100.01 and ln["line_discount"] == 12.5 and ln["total"] == 87.51 and t["net"] == 87.51,
      f"calc: a position 3 x 33.335 = 100.01 less 12.5 % (12.50) = 87.51: {ln.get('list_total')} {ln.get('line_discount')} {ln.get('total')}")

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en"})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
A.patch(B + "/api/settings", json={"workspace": f"org:{r.json()['id']}"})
FID, Fr = freelancer(B, A)


def run(S, who):
    def ok(cond, what):
        check(cond, f"{who}: {what}")

    r = S.put(B + O + "/settings", json={"company": {"name": COMPANY["name"]}, "lang": "de", "currency": "EUR", "payment_days": 14,
                                         "company_fields": COMPANY})
    ok(r.ok, "office settings " + r.text[:200])
    r = S.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"})
    assert r.status_code == 201, r.text
    CL = r.json()["id"]

    # ---------------------------------------------------------------- the acceptance case
    r = S.post(B + D, json={"client_id": CL, "project_title": "Imagefilm", "raw_mode": "none", "producing_on": 0,
                            "service_from": "2026-10-01", "service_to": "2026-10-20"})
    assert r.status_code == 201, r.text
    OF = r.json()["id"]
    r = S.put(B + f"{D}/{OF}/items", json={"items": [{"title": "Regie", "qty": 2, "rate": 1000, "unit": "day", "discount_pct": 10},
                                                       {"title": "Buchlizenz", "qty": 1, "rate": 1000, "unit": "flat", "tax": "reduced"}]})
    ok(r.ok, "positions with a discount of their own " + r.text[:200])
    its = r.json().get("items") or []
    ok([float(x.get("discount_pct") or 0) for x in its] == [10.0, 0.0], f"the position keeps its 10 %: {[x.get('discount_pct') for x in its]}")
    r = S.patch(B + f"{D}/{OF}", json={"discount_amount": 500})
    ok(r.ok, "500 off the whole quotation " + r.text[:200])
    d = r.json()
    t = d.get("totals") or {}
    item = next((x for x in t.get("lines") or [] if x.get("kind") == "item" and x.get("title") == "Regie"), {})
    ok(item.get("list_total") == 2000 and item.get("line_discount") == 200 and item.get("total") == 1800 and item.get("discount_pct") == 10,
       f"the position: 2000.00 less 10 % = 1800.00: {item.get('list_total')} {item.get('line_discount')} {item.get('total')}")
    disc = next((x for x in t.get("lines") or [] if x.get("kind") == "discount"), {})
    ok(disc.get("total") == -500 and disc.get("by_tax") == {"standard": 321.43, "reduced": 178.57} and disc.get("pct") is None,
       f"one discount line of 500.00, 321.43 at 19 % and 178.57 at 7 %: {disc}")
    tl = {x["rate_key"]: (x["base"], x["amount"]) for x in t.get("tax_lines") or []}
    ok(t.get("net") == 2300 and tl == {"standard": (1478.57, 280.93), "reduced": (821.43, 57.5)} and t.get("tax_total") == 338.43 and t.get("gross") == 2638.43,
       f"net 2300.00, tax 280.93 + 57.50 = 338.43, gross 2638.43: {t.get('net')} {tl} {t.get('tax_total')} {t.get('gross')}")
    ok(float(d.get("discount_amount") or 0) == 500 and not float(d.get("discount_pct") or 0), f"stored: amount 500, percent 0: {d.get('discount_amount')} {d.get('discount_pct')}")

    # ---------------------------------------------------------------- one or the other, never more than the positions
    r = S.patch(B + f"{D}/{OF}", json={"discount_amount": 3000})
    ok(r.status_code == 400 and "2.800,00" in r.text, "3000 over a discountable sum of 2800.00 is refused, naming the sum " + str(r.status_code) + r.text[:200])
    ok(float(S.get(B + f"{D}/{OF}").json().get("discount_amount") or 0) == 500, "refused: the 500 stay")
    r = S.patch(B + f"{D}/{OF}", json={"discount_pct": 5})
    ok(r.ok and r.json().get("discount_amount") is None and float(r.json().get("discount_pct")) == 5 and r.json()["totals"]["discount"] == 140,
       "a percent clears the amount (5 % of 2800.00 = 140.00) " + r.text[:200])
    r = S.patch(B + f"{D}/{OF}", json={"discount_amount": 500})
    ok(r.ok and not float(r.json().get("discount_pct") or 0) and r.json()["totals"]["gross"] == 2638.43, "an amount sets the percent to 0 " + r.text[:200])

    # ---------------------------------------------------------------- print model, PDF, approval page
    rd = S.get(B + f"{D}/{OF}/render").json()
    rl = next((x for x in rd.get("lines") or [] if x.get("kind") == "item" and x.get("title") == "Regie"), {})
    ok(rl.get("discount_pct") == 10 and rl.get("line_discount") == 200, f"the print model carries the position's discount: {rl.get('discount_pct')} {rl.get('line_discount')}")
    p = S.get(B + f"{D}/{OF}/pdf")
    ok(p.ok and p.content.startswith(b"%PDF-"), f"the PDF of the quotation {p.status_code}")

    # ---------------------------------------------------------------- the invoice from the quotation
    r = S.post(B + f"{D}/{OF}/invoice")
    ok(r.status_code == 201, "invoice from the quotation " + r.text[:200])
    iv = r.json()
    svc = [(x["title"], float(x.get("discount_pct") or 0)) for x in iv.get("items") or [] if x["kind"] == "service"]
    ok(svc == [("Regie", 10.0), ("Buchlizenz", 0.0)], f"the invoice keeps the position's 10 %: {svc}")
    dp = sorted((x["tax"], float(x["rate"])) for x in iv.get("items") or [] if x["kind"] == "discount")
    ok(dp == [("reduced", 178.57), ("standard", 321.43)], f"the 500.00 as one discount position per rate: {dp}")
    it = iv.get("totals") or {}
    ok((it.get("net"), it.get("tax"), it.get("gross")) == ("2300.00", "338.43", "2638.43"), f"the invoice = the quotation: {it.get('net')} {it.get('tax')} {it.get('gross')}")
    il = next((x for x in it.get("lines") or [] if x.get("title") == "Regie"), {})
    ok(il.get("allowance") == "200.00" and il.get("list_net") == "2000.00" and il.get("net") == "1800.00", f"the invoice line: 2000.00 - 200.00 = 1800.00: {il.get('list_net')} {il.get('allowance')} {il.get('net')}")
    r = S.post(B + f"{D}/{iv['id']}/finalize")
    ok(r.ok, "the invoice finalised " + r.text[:200])
    x = S.get(B + f"{D}/{iv['id']}/xml")
    ok(x.ok and b"<ram:ActualAmount>200.00</ram:ActualAmount>" in x.content and b"<ram:CalculationPercent>10</ram:CalculationPercent>" in x.content
       and b"<ram:BasisAmount>2000.00</ram:BasisAmount>" in x.content and b"<ram:GrandTotalAmount>2638.43</ram:GrandTotalAmount>" in x.content,
       "the XML: the position's discount as a line allowance (10 %, 2000.00, 200.00), total 2638.43")
    probs = ein.ein_check(x.content) if x.ok else ["no XML"]
    ok(probs == [], f"the own check of the XML finds nothing: {probs}")

    # ---------------------------------------------------------------- a quotation with a part
    r = S.post(B + D, json={"client_id": CL, "project_title": "Kampagne", "raw_mode": "none", "producing_on": 0})
    assert r.status_code == 201, r.text
    OP = r.json()["id"]
    r = S.post(B + f"{D}/{OP}/parts", json={"title": "Modul A"})
    ok(r.status_code == 201, "a part " + r.text[:200])
    pid = (r.json().get("part") or {}).get("id")
    r = S.put(B + f"{D}/{OP}/parts/{pid}/items", json={"items": [{"title": "Animation", "qty": 1, "rate": 1000, "unit": "flat"}]})
    ok(r.ok, "the part's position " + r.text[:200])
    r = S.patch(B + f"{D}/{OP}", json={"discount_amount": 100})
    ok(r.ok, "100 off a quotation with a part " + r.text[:200])
    d = S.get(B + f"{D}/{OP}").json()
    pt = next((x for x in d.get("parts") or [] if x.get("id") == pid), {})
    ok(d["totals"].get("net") == 900 and (pt.get("totals") or {}).get("net") == 1000,
       f"the title page takes 100 off (900), the part keeps 1000: {d['totals'].get('net')} {(pt.get('totals') or {}).get('net')}")
    r = S.patch(B + f"{D}/{OP}", json={"discount_amount": 1500})
    ok(r.status_code == 400, "over the part lines' sum: refused " + str(r.status_code))


run(Fr, "freelancer")
run(A, "organisation")
print(f"p5815_discount: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
