"""2.461 (#3773): public holidays per country -- data only, one JSON per country under kalmido/office/packs/holidays/<code>.json
(next to the office country packs, but on its own: a holiday country needs no tax rates or document words).

A file: {"code": "DE", "name": <key>, "version": 1, "regions": {code: <key>} (optional), "holidays": [...]}; names are translation
keys in English (tools/i18n_check.py reads them through core/i18nkeys.py). A holiday has "name" and one of
  "date": "MM-DD", "easter": days from Easter Sunday, "wednesday_before": "MM-DD" (the last Wednesday before that day);
optionally "regions": [codes] (only there; without it nationwide), "since": first year, "since_region": {code: first year},
"sunday_shift": days to move it when it falls on a Sunday, "every": only in years divisible by this.

What a person or an organisation stores stays one code: a region ("BY") or a country ("AT", "DE" = only the nationwide ones).
Regions of a country never use a code of another country."""
import glob
import json
import os
from datetime import date, timedelta

HOL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "office", "packs", "holidays")
HOL_ORDER = ("DE", "AT", "CH", "FR", "ES", "IT", "NL")  # the picker; others behind them by code


def hol_load():
    """{country code: pack}, in the order of the picker."""
    packs = {}
    for p in sorted(glob.glob(os.path.join(HOL_DIR, "*.json"))):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        packs[d["code"]] = d
    return dict(sorted(packs.items(), key=lambda kv: (HOL_ORDER.index(kv[0]) if kv[0] in HOL_ORDER else len(HOL_ORDER), kv[0])))


HOL_PACKS = hol_load()
HOL_CODES = {}  # stored code -> (country, region or None)
for _cc, _p in HOL_PACKS.items():
    HOL_CODES[_cc] = (_cc, None)
    HOL_CODES.update({_r: (_cc, _r) for _r in _p.get("regions") or {}})


def hol_easter(y):
    """Easter Sunday of year y (Gregorian; the anonymous algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g_ = (b - f + 1) // 3
    h = (19 * a + b - d - g_ + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    return date(y, month, (h + l_ - 7 * m + 114) % 31 + 1)


def _day(h, y):
    if "easter" in h:
        return hol_easter(y) + timedelta(days=h["easter"])
    if "wednesday_before" in h:
        d = date(y, *map(int, h["wednesday_before"].split("-"))) - timedelta(days=1)
        return d - timedelta(days=(d.weekday() - 2) % 7)
    d = date(y, *map(int, h["date"].split("-")))
    return d + timedelta(days=h["sunday_shift"]) if h.get("sunday_shift") and d.weekday() == 6 else d


def hol_year(y, code):
    """{ISO day: name key} of the public holidays of year y for a stored code (unknown or '' = none)."""
    if code not in HOL_CODES:
        return {}
    cc, region = HOL_CODES[code]
    out = {}
    for h in HOL_PACKS[cc]["holidays"]:
        if "regions" in h and region not in h["regions"]:
            continue
        if y < (h.get("since_region") or {}).get(region, h.get("since", 0)) or (h.get("every") and y % h["every"]):
            continue
        out[_day(h, y).isoformat()] = h["name"]
    return out
