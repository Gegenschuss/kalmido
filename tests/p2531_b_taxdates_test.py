#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.531.0 (#4498): tax rates of a country pack with a validity (kalmido/office/packs.py, calc.py), pure Python, no server.
 - the pack validator: a tax key is a number (as before) or a list [{valid_from, rate}, ...]: ascending, no day twice, the first
   one from 1970-01-01 (no gap at the start), dates YYYY-MM-DD, rates 0..100, exempt always 0, not empty
 - the shipped packs DE / XX stay valid; DE carries the change of the second half of 2020 (16 / 5 %, else 19 / 7 %)
 - office_pack_for(settings, day): the rates of that day as numbers, the labels' {rate} filled ("16 % MwSt."); the cached
   pack is never changed
usage: python3 tests/p2531_b_taxdates_test.py   (KALMIDO_SRC=<dir with kalmido/> to test another tree)"""
import importlib.util
import json
import os
import sys
import types

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402

SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
OFF = os.path.join(SRC, "kalmido", "office")
pkg = types.ModuleType("kofc")  # packs.py imports .calc lazily: a package of the two files alone
pkg.__path__ = [OFF]
sys.modules["kofc"] = pkg
sys.modules["kofc.catalog"] = None  # no app catalogue: packs._pkc sees an ImportError (only the shipped packs)


def load(name):
    spec = importlib.util.spec_from_file_location("kofc." + name, os.path.join(OFF, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["kofc." + name] = m
    spec.loader.exec_module(m)
    return m


calc = load("calc")
packs = load("packs")
DE = json.load(open(os.path.join(OFF, "packs", "de.json"), encoding="utf-8"))
XX = json.load(open(os.path.join(OFF, "packs", "xx.json"), encoding="utf-8"))
P = packs.pack_tax_problems

# ---------------------------------------------------------------- the validator
check(packs.office_pack_validate(DE) == [], f"DE is valid {packs.office_pack_validate(DE)}")
check(packs.office_pack_validate(XX) == [], f"XX is valid {packs.office_pack_validate(XX)}")
check(P("standard", 19) == [] and P("exempt", 0) == [], "the old form (a number) stays valid")
check(P("standard", "19") and P("standard", 101) and P("exempt", 5), "a text, above 100 and exempt not 0 are refused as before")
ok = [{"valid_from": "1970-01-01", "rate": 20}, {"valid_from": "2030-07-01", "rate": 22}]
check(P("standard", ok) == [], f"a list ascending from 1970-01-01 is valid {P('standard', ok)}")
gap = P("standard", [{"valid_from": "2000-01-01", "rate": 20}])
check(any("gap at the start" in x for x in gap), f"a list starting later than 1970-01-01 is refused (gap) {gap}")
down = P("standard", [{"valid_from": "1970-01-01", "rate": 20}, {"valid_from": "2031-01-01", "rate": 22}, {"valid_from": "2030-01-01", "rate": 21}])
check(any("ascending" in x for x in down), f"a list out of order is refused {down}")
dup = P("standard", [{"valid_from": "1970-01-01", "rate": 20}, {"valid_from": "1970-01-01", "rate": 22}])
check(any("ascending" in x for x in dup), f"the same day twice is refused {dup}")
check(P("standard", []) and P("standard", [{"valid_from": "2030-13-01", "rate": 20}]) and P("standard", [{"valid_from": "1970-01-01", "rate": 120}])
      and P("standard", [{"rate": 20}]) and P("standard", ["x"]), "empty list, a wrong date, a rate above 100, no day, no object: refused")
check(P("exempt", [{"valid_from": "1970-01-01", "rate": 0}]) == [] and P("exempt", [{"valid_from": "1970-01-01", "rate": 1}]),
      "exempt as a list: only 0")
bad = json.loads(json.dumps(DE))
bad["tax"]["reduced"] = [{"valid_from": "2020-07-01", "rate": 5}]
check(any(x.startswith("tax.reduced") for x in packs.office_pack_validate(bad)), "the whole pack check names the key with the gap")

# ---------------------------------------------------------------- DE: the change of 2020
for day, std, red in (("2020-06-30", 19, 7), ("2020-07-01", 16, 5), ("2020-12-31", 16, 5), ("2021-01-01", 19, 7), ("2026-11-04", 19, 7)):
    got = (packs.pack_rate_for(DE, "standard", day), packs.pack_rate_for(DE, "reduced", day), packs.pack_rate_for(DE, "exempt", day))
    check(got == (std, red, 0), f"DE on {day}: {std} / {red} / 0 (got {got})")

# ---------------------------------------------------------------- office_pack_for(settings, day)
packs._cache["DE"] = DE  # the shipped file, without the app's catalogue
p20, p26 = packs.office_pack_for({"pack": "DE"}, "2020-08-01"), packs.office_pack_for({"pack": "DE"}, "2026-11-04")
check(p20["tax"]["standard"] == 16 and p20["tax"]["reduced"] == 5 and p26["tax"]["standard"] == 19 and p26["tax"]["reduced"] == 7,
      f"the pack of a day carries that day's rates as numbers {p20['tax']['standard']} {p26['tax']['standard']}")
check(p20["tax"]["labels"]["de"]["standard"] == "16 % MwSt." and p26["tax"]["labels"]["de"]["standard"] == "19 % MwSt."
      and p26["tax"]["labels"]["en"]["reduced"] == "7 % VAT", f"the labels name the rate of the day {p20['tax']['labels']['de']}")
check(isinstance(DE["tax"]["standard"], list) and "{rate}" in DE["tax"]["labels"]["de"]["standard"], "the cached pack itself stays unchanged")
check(calc.pack_tax(DE, "standard", "2020-09-01") == 16 and calc.pack_tax(DE, "standard", "2019-09-01") == 19,
      "calc.pack_tax reads the list of an unresolved pack by the day")

print(f"p2531_b_taxdates: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
