#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.450.0 B (#3770): amounts and dates of the server follow the same rules as the client, for a person without an
organisation (freelancer-matrix: files).
 - a document's amount: "1.234,56" and "1,234.56" keep their value (the first was refused, "1,500" in English was 1.5), a
   wrong amount is 400 and leaves the stored one, an amount with three decimals is not cut
 - tables: a date column reads the Dutch 15-10-2026 (the server knew dots and ISO only)
 - 2.456.0 (#3819): a money field of a document reads like the amount
Invented documents only (the PDF is made here)."""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check  # noqa: E402,F401

kt.fresh()
A = kt.setup(lang="en")
FID, Fr = freelancer(B, A, "frida")
Fn = freelancer(B, A, "fenna")[1]
Fn.patch(B + "/api/settings", json={"lang": "nl"})

PDF = (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
       b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n")


def doc(s, name):
    r = s.post(B + "/api/docs", data={"ws": "private"}, files={"files": (name, PDF, "application/pdf")})
    check(r.status_code == 201, f"setup: document {name} ({r.status_code} {r.text[:160]})")
    return r.json()["ids"][0]


def amount(s, did):
    return s.get(B + f"/api/docs/{did}").json().get("amount")


DOCS = {}
# ---- a document's amount, English and Dutch (a comma language)
for s, who, cases in ((Fr, "en", (("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("1,500", "1500.00"), ("1234,5", "1234.50"), (19.5, "19.5"), ("119.00", "119.00"))),
                      (Fn, "nl", (("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("12,5", "12.50"), ("1,500", "1.50"), ("1,234", None)))):
    did = DOCS[who] = doc(s, f"beleg-{who}.pdf")
    for raw, want in cases:
        r = s.patch(B + f"/api/docs/{did}", json={"amount": raw})
        if want is None:  # 1,234 in a comma language: three decimals, not cut to 1.23
            check(r.status_code == 400, f"#3770: {who} {raw!r} is no amount {r.status_code}")
        else:
            got = amount(s, did)
            check(r.ok and float(got) == float(want), f"#3770: {who} amount {raw!r} = {want} ({r.status_code} {got!r} {r.text[:120] if not r.ok else ''})")
    r = s.patch(B + f"/api/docs/{did}", json={"amount": "119.00"})
    for bad in ("abc", "1.2.3,4,5", "1,2,3", "12.345"):
        r = s.patch(B + f"/api/docs/{did}", json={"amount": bad})
        check(r.status_code == 400 and float(amount(s, did)) == 119, f"#3770: {who} {bad!r} = 400, the amount stays ({r.status_code} {amount(s, did)!r})")
    check(s.patch(B + f"/api/docs/{did}", json={"amount": ""}).ok and not amount(s, did), f"#3770: {who} an empty amount clears it")

# ---- 2.456.0 (#3819): a money field of a document reads like the amount, by language; too many decimals are refused
for s, who, cases in ((Fr, "en", (("1,500", "1500.00"), ("1,5 €", "1.50 EUR"), ("1.234,50", "1234.50"), ("USD 1,234.56", "1234.56 USD"))),
                      (Fn, "nl", (("1,500", "1.50"), ("1.234,50 €", "1234.50 EUR"), ("1500", "1500.00"), ("1,234", None), ("12.345", None), ("abc", None)))):
    f = s.post(B + "/api/docs/fields", json={"ws": "private", "name": "Kaution", "type": "money"})
    check(f.status_code == 201, f"#3819: {who} a money field {f.status_code} {f.text[:160]}")
    did = DOCS[who]
    key = str(f.json().get("id"))
    for raw, want in cases:
        r = s.patch(B + f"/api/docs/{did}", json={"custom_fields": {key: raw}})
        got = next((x.get("value") for x in s.get(B + f"/api/docs/{did}").json().get("custom_fields") or [] if x.get("name") == "Kaution"), None)
        if want is None:
            check(r.status_code == 400, f"#3819: {who} {raw!r} is refused, never reinterpreted {r.status_code} {got!r}")
        else:
            check(r.ok and got == want, f"#3819: {who} {raw!r} = {want} ({r.status_code} {got!r} {r.text[:120] if not r.ok else ''})")

# ---- tables: the Dutch date
r = Fn.post(B + "/api/sheets", json={"title": "Datums"})
check(r.status_code == 201, f"a table {r.status_code} {r.text[:160]}")
sid = r.json()["id"]
col = Fn.post(B + f"/api/sheets/{sid}/columns", json={"title": "Datum", "kind": "date"}).json()["column"]["letter"]
r = Fn.put(B + f"/api/sheets/{sid}/cells", json={"cells": [{"cell": f"{col}1", "raw": "15-10-2026"}, {"cell": f"{col}2", "raw": "15.10.2026"},
                                                           {"cell": f"{col}3", "raw": "2026-10-15"}, {"cell": f"{col}4", "raw": "31-02-2026"}]})
check(r.ok, f"cells {r.status_code} {r.text[:200]}")
at = {x["addr"]: x for x in Fn.get(B + f"/api/sheets/{sid}").json().get("cells", [])}
vals = [(at.get(f"{col}{i}") or {}).get("value") for i in (1, 2, 3)]
check(vals[0] and vals[0] == vals[1] == vals[2], f"#3770: 15-10-2026 is the same date as 15.10.2026 and the ISO form {vals}")
check((at.get(f"{col}4") or {}).get("value") != vals[0], "#3770: 31-02-2026 is no date")

sys.exit(kt.done("p2450_x_num_api"))
