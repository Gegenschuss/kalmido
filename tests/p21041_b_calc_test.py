#!/usr/bin/env python3
# kalmido-suite: after=office_calc nodata
"""2.1041.0 (#5814 #5816): the quotation / invoice calculator (kalmido/office/calc.py) with optional / alternative positions and
subtotals per section; pure Python, no server.
 - an optional / alternative position: its line keeps qty, rate and amount and carries opt; it counts in no sum (net, tax,
   discount, producing by quantities and by amount, handling costs / markup, raw data, purchase, the base of a percent position)
 - opt_note only when such a position exists; a document without one has the same keys as before (no opt, no opt_note)
 - subtotals: one line kind subtotal at the end of every section (heading to heading, before the calculation lines), the net of
   its counted positions; none before the first heading, none for a section of optional positions only; the sums the same as
   with the switch off; the invoice calculator counts a discount position in its section; the label in the document's language
usage: python3 tests/p21041_b_calc_test.py   (KALMIDO_SRC=<dir with kalmido/> to test another tree)"""
import importlib.util
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("office_calc_21041", os.path.join(SRC, "kalmido", "office", "calc.py"))
calc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calc)
office_calc, inv_calc = calc.office_calc, calc.inv_calc
from kt import FAILS, OKS, check  # noqa: E402  shared helpers (tests/kt.py)


def it(title, qty, rate, opt="", **kw):
    return {"kind": "service", "title": title, "qty": qty, "rate": rate, "tax": "standard", "unit": "day", "opt": opt, **kw}


DOC = {"lang": "de", "currency": "EUR", "raw_mode": "none", "producing_on": 0}
H1, H2 = {"kind": "heading", "title": "Vorproduktion"}, {"kind": "heading", "title": "Dreh"}

# ---------------------------------------------------------------- #5814
base = [H1, it("Konzept", 2, 1000, cost=100), H2, it("Kamera", 3, 800, cost=300)]
t0 = office_calc(DOC, base)
check(t0["net"] == 4400 and "opt_note" not in t0 and not any("opt" in x for x in t0["lines"]), "#5814: without such a position no new key")
t = office_calc(DOC, base + [it("Drohne", 1, 550, "alternative", cost=200), it("Moodfilm", 1, 400, "optional", raw_fee=1)])
il = {x["title"]: x for x in t["lines"] if x["kind"] == "item"}
check(t["net"] == 4400 and t["items_net"] == 4400 and t["gross"] == t0["gross"] and t["costs"] == t0["costs"],
      f"#5814: net, gross, purchase as without them {t['net']} {t['gross']} {t['costs']}")
check(il["Drohne"]["total"] == 550 and il["Drohne"]["opt"] == "alternative" and il["Moodfilm"]["opt"] == "optional" and il["Drohne"]["pos"] == 3,
      "#5814: the lines keep amount, kind and a number " + str(il["Drohne"]))
check(t["opt_note"] == "Optionale und alternative Positionen sind nicht in der Summe enthalten.", "#5814: the note in German " + str(t.get("opt_note")))
check(office_calc({**DOC, "lang": "en"}, [it("A", 1, 1, "optional")])["opt_note"].startswith("Optional and alternative"), "#5814: ... and in English")
t = office_calc({**DOC, "discount_pct": 10, "raw_mode": "included", "raw_factor": 0.25, "handling_pct": 5, "markup_pct": 10},
                [it("A", 1, 1000, raw_fee=1, in_handling=1, in_markup=1), it("B", 1, 600, "optional", raw_fee=1, in_handling=1, in_markup=1)])
check(t["discount"] == 100 and t["raw_amount"] == 250 and t["handling_total"] == 50 and t["markup_total"] == 100,
      f"#5814: discount, raw data, handling, markup only from the normal one {t['discount']} {t['raw_amount']} {t['handling_total']} {t['markup_total']}")
t = office_calc({**DOC, "producing_on": 1, "prod_quotient": 1, "producing_rate": 100}, [it("A", 2, 10, producing=1), it("B", 4, 10, "optional", producing=1)])
check(t["producing_days"] == 2, "#5814: producing by quantities ignores it " + str(t["producing_days"]))
t = office_calc({**DOC, "producing_on": 1, "producing_mode": "amount", "prod_quotient": 1, "producing_rate": 1000},
                [it("A", 1, 1000, producing=1), it("B", 1, 5000, "alternative", producing=1)])
check(t["producing_days"] == 1, "#5814: producing by amount ignores it " + str(t["producing_days"]))
t = office_calc(DOC, [it("Extern", 1, 1000, intext="extern"), it("Extern opt", 1, 9000, "optional", intext="extern"), {**it("KSK", 1, 5), "unit": "percent"}])
check([x["total"] for x in t["lines"] if x["title"] == "KSK"] == [50], "#5814: a percent position takes no optional base")
check(calc.calc_opt({"opt": "x"}) == "" and calc.calc_opt({"opt": "alternative"}) == "alternative", "#5814: calc_opt knows two kinds")

# ---------------------------------------------------------------- #5816
ITS = [it("Briefing", 1, 300), H1, it("Konzept", 2, 1000), {"kind": "text", "detail": "inkl. zwei Runden"}, it("Mood", 1, 400, "optional"),
       H2, it("Kamera", 3, 800), {"kind": "heading", "title": "Optionen"}, it("Drohne", 1, 550, "alternative")]
off = office_calc({**DOC, "discount_pct": 10}, ITS)
on = office_calc({**DOC, "discount_pct": 10, "subtotals": 1}, ITS)
st = [x for x in on["lines"] if x["kind"] == "subtotal"]
check([(x["sec"], x["title"], x["total"]) for x in st] == [(0, "Vorproduktion", 2000), (1, "Dreh", 2400)],
      "#5816: one per section with counted positions, none before the first heading " + str(st))
check(st[0]["label"] == "Zwischensumme Vorproduktion" and st[0]["total_text"] == "2.000,00 €", "#5816: label and amount " + str(st[0]))
kinds = [x["kind"] for x in on["lines"]]
check(kinds == ["item", "heading", "item", "text", "item", "subtotal", "heading", "item", "subtotal", "heading", "item", "discount"],
      "#5816: at the end of the section, after its text, before the next heading and the discount " + str(kinds))
check(all(on[k] == off[k] for k in ("net", "gross", "tax_lines", "discount", "items_net")), "#5816: the sums the same as with the switch off")
check(not any(x["kind"] == "subtotal" for x in off["lines"]), "#5816: off = no subtotal line")
en = office_calc({**DOC, "lang": "en", "subtotals": True}, ITS)
check([x["label"] for x in en["lines"] if x["kind"] == "subtotal"][0] == "Subtotal Vorproduktion", "#5816: the label in English")
iv = inv_calc({"lang": "de", "subtotals": 1}, [H2, it("Kamera", 3, 800), {"kind": "discount", "title": "Nachlass", "qty": 1, "rate": 100, "tax": "standard"},
                                               H1, it("Schnitt", 2, 700)])
check([(x["title"], x["total"]) for x in iv["lines"] if x["kind"] == "subtotal"] == [("Dreh", 2300), ("Vorproduktion", 1400)] and iv["net"] == "3700.00",
      "#5816: the invoice counts a discount position in its section " + str([x for x in iv["lines"] if x["kind"] == "subtotal"]))
check(not any(x["kind"] == "subtotal" for x in inv_calc({"lang": "de"}, [H2, it("Kamera", 3, 800)])["lines"]), "#5816: an invoice without the switch has none")

print(f"p21041_b_calc_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
