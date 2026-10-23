#!/usr/bin/env python3
"""2.98.0 part D (#2178): amount and due date of a document are guessed only where it fits; pure Python, no server.
 - an income tax notice with income figures: no amount, no due date
 - a notice with an additional payment ("zu zahlen bis"): amount and due date from exactly that line
 - an invoice with a total line: amount + due date; a letter without a total line: nothing
 - the paperless import takes an amount only from a custom field of type monetary
usage: p298_d_api_test.py <datadir>   (KALMIDO_SRC=<dir with kalmido/> to test another tree)"""
import importlib.util
import os
import sys
from datetime import date

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
from kt import FAILS, OKS, check  # 2.206.0 (#2762): shared helpers (tests/kt.py)
TODAY = date(2026, 10, 15)


spec = importlib.util.spec_from_file_location("p298d_extract", os.path.join(SRC, "kalmido", "docs", "extract.py"))
X = importlib.util.module_from_spec(spec)
spec.loader.exec_module(X)

TAX = "Finanzamt Beispielstadt\nEinkommensteuerbescheid 2025\nDatum: 02.10.2026\nZu versteuerndes Einkommen 52.340,00 EUR\nFestgesetzte Steuer 9.120,00 EUR\nSumme der Einkünfte 55.000,00 EUR\n"
r = X.extract(TAX, TODAY, guess=False)
check(r["amount"] is None and r["due"] is None, f"tax notice with income: nothing guessed {r}")
r = X.extract(TAX + "Nachzahlung 1.234,50 EUR zu zahlen bis 03.11.2026\n", TODAY, guess=False)
check(r["amount"] == "1234.50" and r["due"] == "2026-11-03" and r["currency"] == "EUR", f"additional payment {r}")
r = X.extract(TAX + "Nachzahlung\n88,00 EUR\nzu zahlen bis 03.11.2026\n", TODAY, guess=False)
check(r["due"] is None or r["amount"] in (None, "88.00"), f"split lines never invent a wrong amount {r}")

INV = "Muster GmbH\nRechnung Nr. 17\nDatum: 05.10.2026\nPosition A 40,00 EUR\nGesamtbetrag 47,60 EUR\nZahlbar bis 19.10.2026\n"
r = X.extract(INV, TODAY)
check(r["amount"] == "47.60" and r["due"] == "2026-10-19", f"invoice with total {r}")
r = X.extract("Liebe Frau Beispiel,\nanbei der Plan fuer 2027.\nBestellung 12345 vom 01.10.2026\nArtikel 9,99 EUR\nArtikel 19,99 EUR\n", TODAY)
check(r["amount"] is None, f"letter without total line {r}")

# monetary_value lives in a module with heavy imports: take just that function out of the source
import ast
import re
src = open(os.path.join(SRC, "kalmido", "paperless", "ngx.py"), encoding="utf-8").read()
fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "monetary_value")
ns = {"re": re}
exec(compile(ast.Module([fn], []), "ngx_monetary", "exec"), ns)
mv = ns["monetary_value"]
fields = {1: {"type": "string"}, 2: {"type": "monetary"}}
doc = {"custom_fields": [{"field": 1, "value": "EUR9.99"}, {"field": 2, "value": "EUR12.50"}]}
check(mv(doc, fields) == ("12.50", "EUR"), "monetary field is taken")
check(mv({"custom_fields": [{"field": 1, "value": "EUR9.99"}]}, fields) is None, "string field is not an amount")
check(mv({"custom_fields": []}, fields) is None, "no field, no amount")

print(f"p298_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
