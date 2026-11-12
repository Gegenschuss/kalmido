#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.1041.0 (#5812): repricing a quotation (Nachkalkulieren), the pure calculation kalmido/office/repcalc.py over the real
calculator (kalmido/office/calc.py office_calc), no server. Invented figures only.
 - by x %: every chosen unit price x (1 + x / 100), rounded to the cent; a price with 4 places keeps them; headings, texts
   and percentage positions stay; positions not chosen stay
 - target net sum met exactly (rest on the largest position); rounding to 5 €: every scaled price a multiple of 5, the
   deviation reported, with the rest exact again
 - a discount line (10 % on the marked positions) and producing (day rate scaled along) count as the document counts them
 - target GROSS 12.000,00 € with mixed tax rates (19 / 7 / 0 %): gross exactly 12000.00
 - target surplus 30 %: (net - costs) / net = 30,00 %
 - a foreign currency: the target in the document's currency, the stored (home currency) rate scaled
 - unreachable: the target below what the unchosen positions alone make -> reachable false (negative); -100 % as well;
   nothing to scale -> "nothing"
usage: python3 tests/p21041_a_repcalc_test.py"""
import importlib.util
import os
import sys
from decimal import Decimal

from kt import FAILS, OKS, check  # noqa: F401

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SRC, "kalmido", "office", fn))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


calc = _load("calc", "calc.py")
rp = _load("repcalc", "repcalc.py")
D = Decimal


def it(title, qty, rate, tax="standard", cost=0, **kw):
    return {"kind": "service", "title": title, "qty": qty, "rate": rate, "tax": tax, "unit": "day", "cost": cost, **kw}


def ev_of(doc):
    return lambda items, pr: calc.office_calc({**doc, "producing_rate": pr}, items, None)


def solve(doc, items, mode, value, sel=None, **kw):
    sel = set(range(len(items))) if sel is None else sel
    return rp.orp_solve(ev_of(doc), items, sel, doc.get("producing_rate", 600), mode, value, **kw)


DOC = {"lang": "de", "currency": "EUR", "vat_mode": "vat", "raw_mode": "none", "producing_on": 0, "producing_rate": 600}
BASE = [{"kind": "heading", "title": "Konzept"}, it("Storyboard", 3, 980), it("Schnitt", 2, 1080),
        {"kind": "text", "detail": "Hinweis"}, it("Lizenz", 1, 333.33), it("Kleinteil", 10, "0.125", unit="piece"),
        it("KSK", 1, 5, unit="percent", intext="intern")]

# ---- by x %
r = solve(DOC, BASE, "pct", 10)
rates = [x.get("rate") for x in r["items"]]
check(r["reachable"] and rates[1] == D("1078.00") and rates[2] == D("1188.00") and rates[4] == D("366.66"), f"pct: +10 % on the prices, cent rounding {rates}")
check(rates[5] == D("0.1375"), f"pct: a price with 4 places keeps 4 places {rates[5]}")
check(r["items"][0] is BASE[0] and r["items"][3] is BASE[3] and rates[6] == 5, "pct: heading, text and the percentage position stay")
check(r["deviation"] is None and r["factor"] == D("1.1"), f"pct: factor 1.1, no deviation {r['factor']}")
r = solve(DOC, BASE, "pct", -10, sel={1})
rates = [x.get("rate") for x in r["items"]]
check(rates[1] == D("882.00") and rates[2] == 1080, f"pct: only the chosen position changes {rates}")

# ---- target net, exact with the rest
r = solve(DOC, BASE, "net", 10000, rest=True)
t = r["after"]
check(r["reachable"] and D(str(t["net"])) == D("10000"), f"net: target 10.000 met exactly {t['net']} deviation {r['deviation']}")
check(r["deviation"] == 0, f"net: deviation 0 {r['deviation']}")
# rounding to 5 euro: without the rest every scaled price (>= 5) a multiple of 5, the deviation said
r = solve(DOC, BASE, "net", 12000, rnd="five")
big = [x["rate"] for i, x in enumerate(r["items"]) if i in (1, 2, 4)]
check(all(D(v) % 5 == 0 for v in big), f"five: prices are multiples of 5 {big}")
check(r["deviation"] == D(12000) - D(str(r["after"]["net"])) and abs(r["deviation"]) < 30, f"five: deviation = target - reached {r['deviation']}")
r = solve(DOC, BASE, "net", 12000, rnd="five", rest=True)
check(D(str(r["after"]["net"])) == 12000 and r["deviation"] == 0, f"five + rest: exactly 12.000 {r['after']['net']}")

# ---- with a discount line
DD = {**DOC, "discount_pct": 10}
ITD = [it("Regie", 2, 1200), it("Kamera", 3, 900), it("Material", 1, 400, discountable=0)]
r = solve(DD, ITD, "net", 8000, rest=True)
check(D(str(r["after"]["net"])) == 8000 and D(str(r["after"]["discount"])) > 0, f"discount: net after discount exactly 8.000 {r['after']['net']} (discount {r['after']['discount']})")

# ---- with producing (day rate scaled along)
DP = {**DOC, "producing_on": 1, "prod_quotient": 3, "producing_rate": 600}
ITP = [it("Animation", 6, 1000, producing=1), it("Ton", 3, 800, producing=1), it("Beratung", 1, 500)]
before = calc.office_calc(DP, ITP, None)
r = solve(DP, ITP, "net", 20000, rest=True, scale_prod=True)
check(D(str(before["producing_total"])) > 0 and D(str(r["after"]["producing_total"])) > 0, "producing: the producing line counts before and after")
check(D(str(r["after"]["net"])) == 20000, f"producing: net exactly 20.000 {r['after']['net']}")
check(r["prod_rate"] != 600 and r["prod_rate"] == calc.money(D(600) * r["factor"]), f"producing: the day rate x the factor {r['prod_rate']}")
r2 = solve(DP, ITP, "pct", 10, scale_prod=False)
check(r2["prod_rate"] == 600, "producing: without the tick the day rate stays")

# ---- target gross with mixed tax rates
ITG = [it("Film", 4, 1500), it("Buch", 10, 39.9, tax="reduced"), it("Versand", 1, 25, tax="exempt"), it("Fotos", 3, 450)]
r = solve(DOC, ITG, "gross", 12000, rest=True)
g = r["after"]
check(D(str(g["gross"])) == D("12000"), f"gross: 12.000,00 with 19 / 7 / 0 % exactly {g['gross']} (net {g['net']}, deviation {r['deviation']})")
check(sorted(x["pct"] for x in g["tax_lines"]) == [0, 7, 19], f"gross: the three tax rates stay {[x['pct'] for x in g['tax_lines']]}")

# ---- target surplus 30 %
ITM = [it("Regie", 3, 1100, cost=0), it("Kamera extern", 4, 950, cost=700, intext="extern"), it("Schnitt", 2, 880, cost=300)]
r = solve(DOC, ITM, "margin", 30, rest=True)
f = rp.orp_figures(r["after"])
check(r["reachable"] and abs(f["margin_pct"] - 30) < D("0.005"), f"margin: surplus 30 % {f['margin_pct']} (net {f['net']}, costs {f['costs']})")
check(D(str(r["after"]["costs"])) == D(str(r["before"]["costs"])), "margin: external costs unchanged")

# ---- foreign currency: target in USD, the EUR rate scaled
DU = {**DOC, "currency": "USD", "fx_rate": "1.1"}
r = solve(DU, [it("Shoot", 2, 1000), it("Edit", 1, 750)], "net", 5000, rest=True)
check(D(str(r["after"]["net"])) == 5000 and r["after"]["currency"] == "USD", f"fx: net 5.000 USD exactly {r['after']['net']}")
check(r["items"][0]["rate"] < D("2100"), f"fx: the stored rate is the home currency's {r['items'][0]['rate']}")

# ---- unreachable
r = solve(DOC, BASE, "net", 2000, sel={4})
check(not r["reachable"] and r["reason"] == "negative" and r["items"] is BASE, f"unreachable: below the unchosen positions {r.get('reason')}")
r = solve(DOC, BASE, "pct", -100)
check(not r["reachable"] and r["reason"] == "negative", "unreachable: -100 %")
r = solve(DOC, BASE, "net", 5000, sel={0, 3, 6})
check(not r["reachable"] and r["reason"] == "nothing", f"nothing: only heading / text / percentage chosen {r.get('reason')}")
r = solve(DOC, [it("Null", 1, 0)], "net", 100)
check(not r["reachable"], "nothing: a price of 0 cannot be scaled")

# ---- rounding helper, rest position (#5814: a position counting in no sum never takes the rest)
check(rp.orp_round(D("0.5"), "five") == D("0.50") and rp.orp_round(D("12.4"), "euro") == D("12.00") and rp.orp_round(D("7.5"), "five") == D("10.00"),
      "round: a price below the step stays a cent amount, else the step")
check(rp.orp_rest_index([it("a", 1, 5000, opt="optional"), it("b", 1, 100)], {0, 1}) == 1, "rest: never on an optional position")

print(f"p21041_a_repcalc: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
