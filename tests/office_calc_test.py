#!/usr/bin/env python3
"""2.36.1 (#1021): the quotation calculator (kalmido/office/calc.py), pure Python, no server.
 - parity with the spreadsheet example KV02: 12 positions -> net 20380.00, raw data 3422.50, net including raw data
   23802.50, 4.5 producing days (14 production days / 3 rounded to half days), internal costs 3750 / margin 16630
 - raw_mode included (framework contract): the raw data line counts, net 23802.50 and "excluding raw data" 20380.00;
   none: no line, no sums; discount 10 % on the marked positions only; USD converts every rate with the exchange rate
 - rounding like the template: half days (ROUND(x/5, 1)*5), money half up to 2 places; comma and point inputs
 - tax: standard / reduced / exempt from the pack, vat_mode novat = no tax lines; headings and text blocks pass through
 - the document's words follow its language (DE / EN), the pack's labels override the built-in ones
usage: python3 tests/office_calc_test.py   (KALMIDO_SRC=<dir with kalmido/> to test another tree)"""
import importlib.util
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("office_calc", os.path.join(SRC, "kalmido", "office", "calc.py"))
calc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calc)
office_calc, half_days, dec, fmt_money = calc.office_calc, calc.half_days, calc.dec, calc.fmt_money
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def it(title, qty, rate, raw=0, prod=0, intext="intern", cost=0, tax="standard", **kw):
    return {"kind": "service", "title": title, "qty": qty, "rate": rate, "tax": tax, "raw_fee": raw, "producing": prod,
            "intext": intext, "cost": cost, "unit": "day", **kw}


# the 12 positions of KV02 (invented customer, the figures of the template)
KV02 = [
    it("Storyboard", 3, 980, detail="(reference frames for the production)"),
    it("Generative media (video)", 4, 960, raw=1, prod=1),
    it("Generative media (audio)", 1, 960, raw=1, prod=1),
    it("Animation 2D / motion design", 4.5, 1080, raw=1, prod=1, intext="extern", cost=600),
    it("Editing", 2, 980, raw=1, prod=1),
    it("Stock footage HD", 10, 75, intext="extern", cost=75, unit="piece"),
    it("Music editing", 0.5, 980, raw=1, prod=0),
    it("Music track incl. licence", 1, 300, prod=1, intext="extern", cost=300),
    it("Sound design", 1, 980, raw=1, prod=1),
    it("Sound editing & mix", 0.5, 580, raw=1, prod=1),
    it("Subtitles, base fee", 1, 210, raw=1),
    it("Subtitles, per minute", 2, 50, raw=1, unit="minute"),
]
PACK = {"code": "DE", "tax": {"standard": 19, "reduced": 7, "exempt": 0}}
DOC = {"lang": "de", "currency": "EUR", "vat_mode": "vat", "raw_mode": "optional", "raw_factor": 0.25, "prod_quotient": 3,
       "producing_rate": 600, "discount_pct": 0}

# ---------------------------------------------------------------- KV02 parity
r = office_calc(DOC, KV02, PACK)
check(r["items_net"] == 17680, f"KV02: positions net 17680, got {r['items_net']}")
check(r["producing_qty"] == 14 and r["producing_days"] == 4.5 and r["producing_total"] == 2700, f"KV02: 14 production days -> 4.5 days x 600 = 2700, got {r['producing_qty']} / {r['producing_days']} / {r['producing_total']}")
check(r["net"] == 20380, f"KV02 parity: net = 20380.00, got {r['net']}")
check(r["raw_base"] == 13690 and r["raw_amount"] == 3422.5, f"KV02: raw data 13690 x 0.25 = 3422.50, got {r['raw_base']} / {r['raw_amount']}")
check(r["net_incl_raw"] == 23802.5 and r["net_excl_raw"] is None, f"KV02 parity: including raw data = 23802.50, got {r['net_incl_raw']}")
check(r["costs"] == 3750 and r["margin"] == 16630, f"KV02: costs 3750 / margin 16630, got {r['costs']} / {r['margin']}")
check(r["tax_lines"] == [{"rate_key": "standard", "pct": 19, "base": 20380, "amount": 3872.2, "label": "MwSt. 19 %"}], f"KV02: one 19 % line on 20380 = 3872.20, got {r['tax_lines']}")
check(r["gross"] == 24252.2, f"KV02: gross 24252.20, got {r['gross']}")
check(r["vat_note"] == "Alle Preise zuzüglich 7 % bzw. 19 % MwSt.", "KV02: the offer's VAT note (DE)")
kinds = [l["kind"] for l in r["lines"]]
check(kinds == ["item"] * 12 + ["producing", "raw"], f"KV02: 12 positions, then Producing and the raw data option: {kinds}")
raw = r["lines"][-1]
check(raw["optional"] and raw["title"] == "Optional: Bereitstellung der Rohdaten" and raw["total"] == 3422.5, f"KV02: the optional raw data line {raw}")
prod = r["lines"][-2]
check(prod["qty"] == 4.5 and prod["qty_text"] == "4,5" and prod["rate"] == 600 and prod["total"] == 2700 and prod["title"] == "Producing", f"KV02: the producing line {prod}")
check(prod["detail"] == "4,5 Tage = 14 Produktionstage / 3, auf halbe Tage gerundet", f"KV02: the producing explanation: {prod['detail']}")
check([l["pos"] for l in r["lines"][:12]] == list(range(1, 13)), "KV02: positions numbered 1..12")
check(r["lines"][3]["total"] == 4860 and r["lines"][3]["qty_text"] == "4,5" and r["lines"][5]["unit_text"] == "Stk.", f"KV02: 4.5 x 1080 = 4860, units in DE: {r['lines'][3]} {r['lines'][5]['unit_text']}")
check(r["fx_rate"] is None and r["fx_note"] == "", "EUR: no exchange rate shown")

# ---------------------------------------------------------------- EN words
e = office_calc({**DOC, "lang": "en"}, KV02, PACK)
check(e["net"] == 20380 and e["lines"][-1]["title"] == "Optional: Delivery of raw data" and e["lines"][-2]["qty_text"] == "4.5" and e["vat_note"] == "All prices plus 7 % or 19 % VAT.", f"EN: same figures, English words: {e['lines'][-1]['title']} / {e['vat_note']}")
check(e["lines"][-2]["detail"] == "4.5 days = 14 production days / 3, rounded to half days", f"EN producing explanation: {e['lines'][-2]['detail']}")
p2 = {**PACK, "labels": {"en": {"raw_optional": "Optional: raw data hand-over"}}}
check(office_calc({**DOC, "lang": "en"}, KV02, p2)["lines"][-1]["title"] == "Optional: raw data hand-over", "the pack's labels override the built-in words")

# ---------------------------------------------------------------- raw_mode included / none
i = office_calc({**DOC, "raw_mode": "included"}, KV02, PACK)
check(i["net"] == 23802.5 and i["net_excl_raw"] == 20380 and i["net_incl_raw"] is None, f"included: net 23802.50, excluding raw data 20380, got {i['net']} / {i['net_excl_raw']}")
check(i["lines"][-1]["kind"] == "raw" and not i["lines"][-1]["optional"] and i["lines"][-1]["title"] == "Bereitstellung der Rohdaten" and i["lines"][-1]["qty"] == 1, f"included: the raw data line counts {i['lines'][-1]}")
check(i["tax_lines"][0]["base"] == 23802.5 and i["gross"] == 28324.98, f"included: tax on 23802.50 (4522.48), gross 28324.98, got {i['tax_lines']} {i['gross']}")
n = office_calc({**DOC, "raw_mode": "none"}, KV02, PACK)
check(n["net"] == 20380 and n["raw_amount"] == 0 and n["net_incl_raw"] is None and n["net_excl_raw"] is None and "raw" not in [l["kind"] for l in n["lines"]], "none: no raw data line, no extra sums")
z = office_calc(DOC, [it("Consulting", 2, 100)], PACK)
check(z["raw_amount"] == 0 and "raw" not in [l["kind"] for l in z["lines"]] and z["net_incl_raw"] is None and "producing" not in [l["kind"] for l in z["lines"]], "no raw / producing positions: no automatic lines at all")

# ---------------------------------------------------------------- discount
d = office_calc({**DOC, "discount_pct": 10}, [it("A", 2, 100), it("B", 1, 50, discountable=0), {"kind": "heading", "title": "Audio"}, it("C", 1, 30, tax="reduced")], PACK)
check(d["discount"] == 23 and d["net"] == 280 - 23, f"discount 10 % on A (200) + C (30) = 23, net 257, got {d['discount']} / {d['net']}")
dl = [l for l in d["lines"] if l["kind"] == "discount"][0]
check(dl["total"] == -23 and dl["pct"] == 10 and dl["title"] == "Rabatt", f"the discount line {dl}")
check(d["tax_lines"] == [{"rate_key": "standard", "pct": 19, "base": 230, "amount": 43.7, "label": "MwSt. 19 %"}, {"rate_key": "reduced", "pct": 7, "base": 27, "amount": 1.89, "label": "MwSt. 7 %"}], f"discount reduces each tax base: {d['tax_lines']}")
check(d["gross"] == 257 + 43.7 + 1.89, f"gross {d['gross']}")
check([l["kind"] for l in d["lines"]] == ["item", "item", "heading", "item", "discount"], f"headings pass through in order: {[l['kind'] for l in d['lines']]}")
check(office_calc({**DOC, "discount_pct": 0}, KV02, PACK)["discount"] == 0 and "discount" not in [l["kind"] for l in r["lines"]], "0 %: no discount line")

# ---------------------------------------------------------------- USD
u = office_calc({**DOC, "currency": "USD", "fx_rate": 1.09}, KV02, PACK)
check(u["currency"] == "USD" and u["fx_rate"] == 1.09 and u["fx_note"] == "Wechselkurs 1 €: 1,09 $", f"USD: rate shown {u['fx_note']}")
check(u["lines"][0]["rate"] == 1068.2 and u["lines"][0]["total"] == 3204.6, f"USD: 980 x 1.09 = 1068.20 per day, 3 days 3204.60, got {u['lines'][0]}")
check(u["lines"][-2]["rate"] == 654 and u["lines"][-2]["qty"] == 4.5 and u["lines"][-2]["total"] == 2943, f"USD: producing 600 x 1.09 = 654 x 4.5 = 2943, got {u['lines'][-2]}")
check(u["net"] == 22214.2, f"USD net 22214.20, got {u['net']}")
check(office_calc({**DOC, "lang": "en", "currency": "USD", "fx_rate": 1.09}, KV02, PACK)["fx_note"] == "Exchange rate €1: $1.09", "USD EN note")
check(office_calc({**DOC, "currency": "USD", "fx_rate": "1,2"}, [it("A", 1, 100)], PACK)["lines"][0]["rate"] == 120, "the exchange rate accepts a comma")

# ---------------------------------------------------------------- tax: reduced / exempt / novat
t = office_calc(DOC, [it("Licence", 1, 100, tax="reduced"), it("Abroad", 1, 50, tax="exempt"), it("Day", 1, 200)], PACK)
check([(x["rate_key"], x["base"], x["amount"]) for x in t["tax_lines"]] == [("standard", 200, 38), ("reduced", 100, 7), ("exempt", 50, 0)], f"tax lines by key: {t['tax_lines']}")
check(t["net"] == 350 and t["gross"] == 395 and t["tax_total"] == 45, f"net 350, gross 395, got {t['net']} / {t['gross']}")
check(t["lines"][0]["tax_pct"] == 7 and t["lines"][1]["tax_pct"] == 0 and t["lines"][2]["tax_pct"] == 19, "each position carries its percentage")
nv = office_calc({**DOC, "vat_mode": "novat"}, KV02, PACK)
check(nv["net"] == 20380 and nv["gross"] == 20380 and nv["tax_lines"] == [] and nv["lines"][0]["tax_pct"] == 0 and nv["vat_note"] == "Nicht im Inland steuerbar / Reverse-Charge-Verfahren.", f"novat: no tax, note {nv['vat_note']}")
check(office_calc(DOC, [it("A", 1, 100)], {"tax": {"standard": {"pct": 20}}})["tax_lines"][0]["pct"] == 20, "a pack with tax: {standard: {pct}} works too")
check(office_calc(DOC, [it("A", 1, 100)], None)["tax_lines"][0]["pct"] == 19, "no pack: DE defaults")

# ---------------------------------------------------------------- rounding and inputs
check([str(half_days(x)) for x in ("4.6667", "4.75", "4.74", "0.2", "0.25", "0", "3", "2.5")] == ["4.5", "5", "4.5", "0", "0.5", "0", "3", "2.5"], f"half days: {[str(half_days(x)) for x in ('4.6667', '4.75', '4.74', '0.2', '0.25', '0', '3', '2.5')]}")
q = office_calc({**DOC, "prod_quotient": "2,5"}, [it("A", "1,5", "1.234,56", prod=1)], PACK)
check(q["lines"][0]["qty"] == 1.5 and q["lines"][0]["rate"] == 1234.56 and q["lines"][0]["total"] == 1851.84 and q["producing_days"] == 0.5, f"comma inputs: 1,5 x 1.234,56 = 1851.84 (1851.84), 1.5 / 2.5 = 0.6 -> 0.5 days, got {q['lines'][0]} {q['producing_days']}")
h = office_calc(DOC, [it("A", 3, 33.333)], PACK)
check(h["lines"][0]["total"] == 99.99 and h["lines"][0]["rate"] == 33.33, f"rates rounded to 2 places before multiplying (3 x 33.33 = 99.99, like the template): {h['lines'][0]}")
check(office_calc(DOC, [it("A", 1, 10.005)], PACK)["net"] == 10.01, "half up, not banker's rounding")
check(str(dec("1,234.56")) == "1234.56" and str(dec("1.234,56")) == "1234.56" and str(dec("4,5")) == "4.5" and str(dec("abc")) == "0" and str(dec(None)) == "0", "dec() reads both notations")
check(fmt_money(1234.5, "de") == "1.234,50 €" and fmt_money(1234.5, "en") == "€1,234.50" and fmt_money(-23, "de", "USD") == "-23,00 $" and fmt_money(1234567.891, "en", "USD") == "$1,234,567.89", "money formats per language")
tb = office_calc(DOC, [{"kind": "text", "detail": "A free text block"}, it("A", 1, 10)], PACK)
check(tb["lines"][0] == {"kind": "text", "text": "A free text block"} and tb["lines"][1]["pos"] == 1, "text blocks pass through and do not count as positions")
check(office_calc({}, [], None)["net"] == 0 and office_calc({}, [], None)["lines"] == [], "empty document")

print(f"office_calc_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
