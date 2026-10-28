#!/usr/bin/env python3
# kalmido-suite: fresh nodata
"""2.368.0 C (#2983): one money format on the server, always with the currency of the office or document. Invented figures only.
 - calc.fmt_money / pdf_money (the helper every PDF uses: invoices, asset register, cash book, logbook): de "1.234,50 €",
   en "€1,234.50", USD "1.234,50 $" / "$1,234.50", the German pack format of a German document unchanged
 - parts.f8b_fix_cents: the detail of a rest-cent position names the rate in the office's home currency (was always "€")
 - abschlag.abs_offer_info: net_text / remaining_text of a quotation in the home currency (was always EUR)
   (both in the app container of the group, called directly; the routes around them are the same for a person without an
   organisation - the functions take no organisation)
usage: p2368_c_api_test.py      (KALMIDO_SRC = the source tree, default ../ next to tests/; KALMIDO_TEST_CONTAINER)"""
import importlib.util
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location("p2368c_" + name, os.path.join(SRC, "kalmido", "office", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


calc = load("calc")
pdf = load("pdf")

# ---- the helper: the sign where the language puts it, the currency passed in
for args, want in (((1234.5, "de", "EUR"), "1.234,50 €"), ((1234.5, "en", "EUR"), "€1,234.50"),
                   ((1234.5, "de", "USD"), "1.234,50 $"), ((1234.5, "en", "USD"), "$1,234.50"), ((-5, "en", "GBP"), "-£5.00")):
    check(calc.fmt_money(*args) == want, f"fmt_money{args} = {want!r} ({calc.fmt_money(*args)!r})")
    check(pdf.pdf_money(*args) == want, f"pdf_money{args} = {want!r} ({pdf.pdf_money(*args)!r})")
check(pdf.pdf_money(1234.5, "de", "EUR", {"decimal": ",", "thousands": "."}) == "1.234,50 €", "a German document with the pack's format: as before")


def box(code):
    """Python in the app container -> its last output line."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True)
    check(out.returncode == 0, f"the run works {out.stdout[-200:]} {out.stderr[-800:]}")
    lines = out.stdout.strip().splitlines()
    return lines[-1] if lines else ""


# ---- parts: 3 x 33.33 = 99.99, the part line says 100.00 -> one flat position, its detail keeps "3 × rate"
out = box("""import json
from kalmido.office.parts import f8b_fix_cents
for lang, cur in (("en", "USD"), ("de", "EUR"), ("en", "EUR")):
    rows = [{"kind": "service", "qty": 3, "unit": "day", "rate": "33.33", "tax": "standard", "detail": ""}]
    print(json.dumps(f8b_fix_cents(rows, {"standard": "100.00"}, lang, cur)[0]["detail"], ensure_ascii=False), end="|" if cur != "EUR" or lang != "en" else "\\n")
""")
check(out == '"3 × $33.33"|"3 × 33,33 €"|"3 × €33.33"', "the rest-cent detail in the home currency: " + out)

# ---- abschlag: the quotation's net in the home currency (the rates' one); the database parts replaced by fixed values
out = box("""from decimal import Decimal
import kalmido.office.abschlag as m
import kalmido.office.invoices as inv
inv.inv_items_from_offer = lambda c, oid, offer: []
inv.inv_paid_map = lambda c, oid, ids: {}
m.abs_progress_of = lambda c, oid, offer_id, locked_only=False: []
m._eur_bases = lambda items, pack: {"standard": Decimal("1234.50")}
for home in ("USD", "EUR"):
    m._pack = lambda c, oid, h=home: ({"home_currency": h}, {})
    r = m.abs_offer_info(None, 1, {"id": 1, "lang": "en"})
    print(r["net_text"], r["remaining_text"], end="|" if home == "USD" else "\\n")
""")
check(out == "$1,234.50 $1,234.50|€1,234.50 €1,234.50", "progress payments: net and rest in the home currency: " + out)

print(f"p2368_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
