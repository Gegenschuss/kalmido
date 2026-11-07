#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.593.0 B (#4893): the BMF per diem tables abroad of 2023 and 2024 (kalmido/office/vma.py) - pure Python, no server.
The expected values are read off the official BMF letters (23.11.2022, IV C 5 - S 2353/19/10010 :004 and 21.11.2023,
IV C 5 - S 2353/19/10010 :005), never derived from the tables under test.
 - the number of lines per year (2023: 224, 2024: 223) and of countries (171 each), the source of each year in VMA_YEARS
 - samples: France Paris / the rest, USA New York City, United Kingdom London / the rest, Austria (no city), China Hong Kong
 - a country the letter does not name (Bhutan, Liberia: named from 2025 only) gets the rate of Luxembourg (hint lu), the
   letter's extension Antigua and Barbuda = Trinidad and Tobago (hint alias)
 - Germany 28 / 14 in both years; a trip of 2024 abroad counts an amount; 2022 keeps the hint "year" without an amount
usage: python3 tests/p2593_b_vma_test.py"""
import importlib.util
import os
import sys
import types

from kt import check, done

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kalmido", "office")
for name in ("kalmido", "kalmido.office"):  # vma.py alone: its two helpers from calc.py (stdlib only) and a stub for countries
    m = types.ModuleType(name)
    m.__path__ = []
    sys.modules[name] = m


def load(mod):
    spec = importlib.util.spec_from_file_location("kalmido.office." + mod, os.path.join(SRC, mod + ".py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["kalmido.office." + mod] = m
    spec.loader.exec_module(m)
    return m


load("calc")
co = types.ModuleType("kalmido.office.countries")
co.fk_country_names = lambda lg: {}
sys.modules["kalmido.office.countries"] = co
vma = load("vma")

# ---------------------------------------------------------------- the tables
for y, rows, countries in ((2023, 224, 171), (2024, 223, 171)):
    tab = vma.VMA_TABLES.get(y) or {}
    check(sum(len(p) for p in tab.values()) == rows and len(tab) == countries, f"{y}: {rows} lines, {countries} countries")
    check(all("" in p for p in tab.values()), f"{y}: every country has its rate for the whole country ('im Übrigen')")
    check(vma.vma_table_year(y) == y and vma.VMA_HOME[y] == (28, 14), f"{y}: own table, Germany 28 / 14")
check("23.11.2022" in vma.VMA_YEARS[2023] and ":004" in vma.VMA_YEARS[2023] and "S. 1654" in vma.VMA_YEARS[2023], "source 2023")
check("21.11.2023" in vma.VMA_YEARS[2024] and ":005" in vma.VMA_YEARS[2024] and "S. 2076" in vma.VMA_YEARS[2024], "source 2024")

PARIS = "Paris sowie die Departments 77, 78, 91 bis 95"
SAMPLES = [  # (year, code, place) -> (full, partial, code used, place used, how), from the letters' tables
    (2023, "FR", PARIS, (58, 39, "FR", PARIS, "")), (2023, "FR", "", (53, 36, "FR", "", "")),
    (2024, "FR", PARIS, (58, 39, "FR", PARIS, "")), (2024, "FR", "Lyon", (53, 36, "FR", "", "")),
    (2023, "US", "New York City", (66, 44, "US", "New York City", "")), (2024, "US", "New York City", (66, 44, "US", "New York City", "")),
    (2023, "US", "", (59, 40, "US", "", "")),
    (2023, "GB", "London", (66, 44, "GB", "London", "")), (2024, "GB", "London", (66, 44, "GB", "London", "")),
    (2024, "GB", "", (52, 35, "GB", "", "")),
    (2023, "AT", "", (40, 27, "AT", "", "")), (2024, "AT", "", (50, 33, "AT", "", "")),
    (2023, "HK", "", (74, 49, "CN", "Hongkong", "")), (2024, "HK", "", (71, 48, "CN", "Hongkong", "")),
    (2023, "PL", "Krakau", (27, 18, "PL", "Krakau", "")),
    (2023, "BT", "", (63, 42, "LU", "", "lu")), (2024, "LR", "", (63, 42, "LU", "", "lu")),
    (2024, "AG", "", (66, 44, "TT", "", "alias")), (2023, "DE", "", (28, 14, "DE", "", "")),
]
for y, code, place, want in SAMPLES:
    got = vma.vma_rate(y, code, place)
    check(got == want, f"{y} {code} {place or '-'}: {want[:2]} (got {got})")

# ---------------------------------------------------------------- a trip
t = vma.vma_trip({"date_from": "2024-03-04", "date_to": "2024-03-06", "country": "FR", "place": PARIS, "overnight": 1})
check(t["amount"] == "136.00" and not [h for h in t["hints"] if h["key"] == "year"] and t["source"] == [vma.VMA_YEARS[2024]],
      f"2024 Paris: 39 + 58 + 39 = 136, no hint 'no table' {t}")
t = vma.vma_trip({"date_from": "2023-12-31", "date_to": "2024-01-01", "country": "AT", "overnight": 1})
check(t["amount"] == "60.00" and len(t["source"]) == 2, f"over the turn of 2023/2024: Austria 27 (2023) + 33 (2024) {t}")
t = vma.vma_trip({"date_from": "2022-06-01", "date_to": "2022-06-03", "country": "FR", "overnight": 1})
check(t["amount"] is None and {"key": "year", "year": 2022} in t["hints"] and vma.vma_table_year(2022) is None,
      f"2022: still no table, the hint 'year' {t}")
sys.exit(done("p2593_b_vma"))
