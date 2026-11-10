#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.892.0 (#5453): which hints of the receipt check count -- pure Python, no app, no server. Invented texts only.
 - a receipt whose text holds no amount, rate or date (a scan without its words) is checked as one without text: no
   "Missing: tax number / invoice number", only "not found" hints
 - "not found in the text" hints are soft (rck_soft): a complete receipt (amount, date, category, VAT rate set by a person)
   has nothing that counts; real gaps (no date, no rate, sums that do not add up) still count
usage: p2892_b_rcheck_test.py   (KALMIDO_SRC=<dir with kalmido/>)"""
import importlib.util
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("p2892b_rcheck", os.path.join(SRC, "kalmido", "docs", "rcheck.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402  shared helpers (tests/kt.py)


def real(fields, text=None):
    return [x["code"] for x in R.rck_check(fields, text) if not R.rck_soft(x["code"])]


# a complete receipt (set by a person: amount, date, VAT rate) whose file has no readable words: nothing counts
done = {"amount": "357.00", "date": "2026-10-28", "vat_pct": "19"}
thin = "Beleg objektivmiete-verleih-nord.pdf"
codes = [x["code"] for x in R.rck_check(done, thin)]
check(not {"taxid", "number"} & set(codes), f"no words: no 'Missing' from a text without figures {codes}")
check(real(done, thin) == [], f"complete receipt, unreadable text: no hint counts {real(done, thin)}")
check(real(done) == [], f"complete receipt without text: no hint counts {real(done)}")
check(all(R.rck_soft(c) for c in codes), f"what is left is soft (not found) {codes}")

# real gaps still count
check("date_read" in real({"amount": "357.00", "vat_pct": "19"}), "no date at all: counts")
check("rate_read" in real({"amount": "357.00", "date": "2026-10-28"}), "no VAT rate at all: counts")
bad = {"supplier": "X", "net": "100.00", "vat": "19.00", "gross": "129.00", "date": "2026-10-28", "vat_pct": "19"}
check("calc_sum" in real(bad), f"sums that do not add up: count {real(bad)}")
meal = {**done, "meal": True}
check("meal" in real(meal), "an entertainment receipt without occasion: counts")

# a text with figures is still checked as before (the rule of 2.299.0)
txt = "Muster Werkstatt GmbH\nRechnungsdatum: 12.10.2026\nNettobetrag 300,00 EUR\nzzgl. 19 % MwSt 57,00 EUR\nGesamtbetrag 357,00 EUR\n"
check("taxid" in [x["code"] for x in R.rck_check({**done, "supplier": "Muster Werkstatt GmbH"}, txt)], "a readable text without tax id: Missing stays")
check(all(R.rck_soft(c) == (c in R.RCK_SOFT) for c in R.RCK_MSG), "rck_soft = RCK_SOFT")
check(all(R.RCK_MSG[c][0] == "hint" for c in R.RCK_SOFT), "soft codes are never warnings")

print(f"p2892_b_rcheck: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
