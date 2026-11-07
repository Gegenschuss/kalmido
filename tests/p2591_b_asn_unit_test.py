#!/usr/bin/env python3
# kalmido-suite: after=p248_b_unit nodata
"""2.591.0 B (#4863): the archive number from codes, pure Python, no server.
 - extract.find_asn: prefix in codes and texts (codes first), then a code of digits only ("00143" -> 143), never digits from
   the text; 0, ten digits, digits with other characters and an empty prefix setting
 - ocr.qr_pages with a stubbed renderer / reader: every page up to the cap (a sticker on page 3 is found), the finer second
   pass only when no page had a code and only over the first QR_DPI_PAGES pages, want() stops early
usage: python3 tests/p2591_b_asn_unit_test.py   (KALMIDO_SRC=<dir with kalmido/> to test another tree)"""
import importlib.util
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location("p2591b_" + name, os.path.join(SRC, "kalmido", "docs", name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


X = load("extract")
O = load("ocr")
fa = X.find_asn

# ---- find_asn
check(fa("ASN", [], codes=["00143"]) == 143, "#4863: a code of digits only is the archive number")
check(fa("ASN", [], codes=[" 7 "]) == 7 and fa("ASN", [], codes=["123456789"]) == 123456789, "one to nine digits, spaces around")
check(fa("ASN", [], codes=["0000000143"]) == 143, "leading zeros do not count as digits")
check(fa("ASN", [], codes=["1234567890"]) is None, "#4863: ten digits: no archive number")
check(fa("ASN", [], codes=["0", "000"]) is None, "zero: no archive number")
check(fa("ASN", [], codes=["143a", "14-3", "+143", "1.43"]) is None, "digits with anything else: no archive number")
check(fa("ASN", ["00143"]) is None and fa("ASN", ["Kundennummer 00143"], codes=[]) is None, "#4863: digits in the text never count")
check(fa("ASN", ["Brief"], codes=["00143", "ASN00042"]) == 42, "#4863: a code with the prefix wins over one of digits only")
check(fa("ASN", ["ASN 9 im Text"], codes=["00143"]) == 9, "the prefix in the text wins over a code of digits only")
check(fa("ASN", ["ASN 9"], codes=["ASN00042"]) == 42, "a code with the prefix before the text")
check(fa("ASN", [], codes=["https://example.com/x", "00143"]) == 143, "a later code of digits only after another code")
check(fa(" ", [], codes=["00143"]) == 143 and fa(" ", ["ASN 5"]) is None, "an empty prefix setting: only digit codes")
check(fa("ASN", [], codes=[None, ""]) is None, "empty codes")
# the older call (texts only, codes first in the same list) still works for prefixed numbers (docs/split.py, thumbfill.py moved to codes=)
check(fa("ASN", ["ASN00042"]) == 42 and fa("K-", ["K-0099"]) == 99, "the old form without codes")


# ---- qr_pages: page by page, a finer second pass
def run(n, codes_at, want=None):
    """codes_at: {(page, dpi): [texts]}; -> (codes, [(page, dpi) rendered])."""
    seen = []

    def page(i, dpi):
        seen.append((i, dpi))
        return (i, dpi)

    return O.qr_pages(n, page, lambda img: list(codes_at.get(img, [])), want), seen


out, seen = run(3, {(3, 200): ["ASN00007"]})
check(out == ["ASN00007"] and seen == [(1, 200), (2, 200), (3, 200)], f"#4863: a sticker on page 3 is read {out} {seen}")
out, seen = run(1, {(1, 300): ["00143"]})
check(out == ["00143"] and seen == [(1, 200), (1, 300)], f"#4863: no code at 200 dpi -> once more at 300 {out} {seen}")
out, seen = run(2, {(1, 200): ["https://example.com/pay"], (2, 300): ["00143"]})
check(out == ["https://example.com/pay"] and all(d == 200 for _, d in seen), f"a code found: no second pass {seen}")
out, seen = run(40, {})
check(out == [] and len([s for s in seen if s[1] == 200]) == 40 and len([s for s in seen if s[1] == 300]) == O.QR_DPI_PAGES,
      f"nothing anywhere: every page once, the first {O.QR_DPI_PAGES} finer {len(seen)}")
out, seen = run(1000, {})
check(len([s for s in seen if s[1] == 200]) == O.QR_PAGES, f"at most QR_PAGES pages ({O.QR_PAGES})")
out, seen = run(5, {(1, 200): ["https://example.com/pay"], (2, 200): ["00143"], (4, 200): ["ASN00009"]},
                want=lambda cs: fa("ASN", (), codes=cs) is not None)
check(out == ["https://example.com/pay", "00143"] and seen[-1] == (2, 200), f"want() stops at the first number {out} {seen}")
out, seen = run(2, {(1, 200): ["x"] * 30})
check(len(out) == 20, "at most 20 texts")


def broken(i, dpi):
    return None if i == 1 else (i, dpi)


check(O.qr_pages(2, broken, lambda img: ["00143"] if img == (2, 200) else []) == ["00143"], "a page that cannot be rendered is skipped")
check(O.qr_codes(b"x", "text") == [], "no codes of a text file")
# 2.591.0 (#4863, review): a wall-clock budget - a long scan without a code stops reading instead of holding the queue
T = [0.0]


def slow(i, dpi):
    T[0] += 10
    return (i, dpi)


out = O.qr_pages(50, slow, lambda img: ["00143"] if img == (40, 200) else [], budget=35, clock=lambda: T[0])
check(out == [] and T[0] <= 50, f"the budget stops the reading before page 40 ({T[0]})")
check("zbar_symbol_get_type(sym) == 64" in O.QR_WORKER, "digits only count from a QR code, not from a product / parcel bar code")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
