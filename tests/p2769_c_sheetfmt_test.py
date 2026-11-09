#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.769.0 part C API test (#5351): decimal places and an own currency per table column. Invented names only.
 - a number / currency / percent column takes dec (0-4, null = automatic) and a currency column cur (ISO 4217 of the office
   currencies, null = the table's); the display follows, the value stays full and a formula computes with the full value
 - a wrong dec / cur is refused (400) and changes nothing; a column without them shows as before (automatic, table currency)
 - the column's _prev check (changed elsewhere since) covers dec / cur like the other column fields (conflicts)
 - CSV shows the values in the column's places; .xlsx writes the column's own number format and an import of that file reads
   dec / cur back (round trip); the pivot sum of a column is shown in its format
 - API v1 (an agent of the person): dec / cur on sheet_create's columns and on a new column, a wrong dec -> 400
As a person without an organisation (frida) in her private tables.
freelancer-matrix: sheets
usage: p2769_c_sheetfmt_test.py <datadir>      (a fresh container; P2769C_NOSTART=1 = the server already runs)"""
import csv
import io
import os
import re
import sys
import time
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check  # noqa: E402

V = B + "/api/v1"
kt.fresh(prefix="P2769C")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en"})
FID, Fr = freelancer(B, A)


def get(sid, s=None):
    r = (s or Fr).get(B + f"/api/sheets/{sid}")
    return r.json() if r.ok else {"_status": r.status_code}


def put(sid, cell, raw):
    return Fr.put(B + f"/api/sheets/{sid}/cells", json={"cells": [{"cell": cell, "raw": raw}]})


def at(d, addr):
    return next((c for c in d.get("cells", []) if c["addr"] == addr), {})


def col(d, cid):
    return next((c for c in d.get("columns", []) if c["id"] == cid), {})


def patch(sid, cid, body):
    return Fr.patch(B + f"/api/sheets/{sid}/columns/{cid}", json=body)


# ================================================================ a private table: Hours (number) | Fee (currency) | Rate (percent)
T = Fr.post(B + "/api/sheets", json={"title": "Fees", "space": "private"}).json()["id"]
d = get(T)
CA, CB, CC = [c["id"] for c in d["columns"][:3]]
for cid, title, kind in ((CA, "Hours", "number"), (CB, "Fee", "currency"), (CC, "Rate", "percent")):
    check(patch(T, cid, {"title": title, "kind": kind}).ok, f"column {title}")
for addr, raw in (("A1", "1234.5678"), ("B1", "1234.56"), ("C1", "=0.195"), ("A2", "=A1*2")):
    check(put(T, addr, raw).ok, f"input {addr}")
d = get(T)
check(d.get("currency") == "EUR" and "USD" in (d.get("currencies") or []), "the table's currency and the choice " + str(d.get("currency")))
check(col(d, CA).get("dec") is None and col(d, CB).get("cur") is None, "a column without own format: dec / cur null " + str(col(d, CA)))
check([at(d, a).get("display") for a in ("A1", "B1", "C1")] == ["1,234.5678", "€1,234.56", "19.5%"],
      "automatic: as before " + str([at(d, a).get("display") for a in ("A1", "B1", "C1")]))

# ================================================================ set: 2 places, 0 places in USD, 3 places
r = patch(T, CA, {"dec": 2})
check(r.ok and r.json()["column"]["dec"] == 2, "Hours: 2 decimal places " + r.text[:200])
r = patch(T, CB, {"dec": 0, "cur": "usd"})
check(r.ok and r.json()["column"]["dec"] == 0 and r.json()["column"]["cur"] == "USD", "Fee: 0 places, USD (the code upper case) " + r.text[:200])
check(patch(T, CC, {"dec": 3}).ok, "Rate: 3 places")
d = get(T)
shown = [at(d, a).get("display") for a in ("A1", "B1", "C1", "A2")]
check(shown == ["1,234.57", "$1,235", "19.500%", "2,469.14"], "the display follows the column " + str(shown))
check(at(d, "A1").get("value") == 1234.5678 and at(d, "B1").get("value") == 1234.56, "the stored values stay full " + str(at(d, "A1")))
check(at(d, "A2").get("value") == 2469.1356, "a formula computes with the full value " + str(at(d, "A2").get("value")))

# ================================================================ wrong values: 400, nothing changes
for what, b in (("dec 5", {"dec": 5}), ("dec -1", {"dec": -1}), ("dec as text", {"dec": "2"}), ("dec true", {"dec": True}),
                ("dec 1.5", {"dec": 1.5}), ("an unknown currency", {"cur": "XYZ"}), ("cur a number", {"cur": 5}), ("cur a sign", {"cur": "€"})):
    r = patch(T, CB, b)
    check(r.status_code == 400, f"{what}: 400 " + str(r.status_code))
c2 = col(get(T), CB)
check(c2.get("dec") == 0 and c2.get("cur") == "USD", "after the refused ones the column is as it was " + str(c2))
check(Fr.post(B + f"/api/sheets/{T}/columns", json={"title": "Bad", "kind": "number", "dec": 9}).status_code == 400,
      "a new column with dec 9: 400")

# ================================================================ changed elsewhere: _prev keeps the newer value (conflicts)
r = patch(T, CA, {"dec": 4, "_prev": {"dec": 1}})
check(r.ok and [x["field"] for x in r.json().get("conflicts", [])] == ["dec"] and r.json()["column"]["dec"] == 2,
      "dec changed elsewhere since: it stays, the answer names it " + r.text[:300])
r = patch(T, CA, {"dec": 1, "_prev": {"dec": 2}})
check(r.ok and not r.json().get("conflicts") and r.json()["column"]["dec"] == 1, "with the right _prev it is taken " + r.text[:200])
check(patch(T, CA, {"dec": 2}).ok, "Hours back to 2 places")

# ================================================================ CSV: the values in the column's places
r = Fr.get(B + f"/api/sheets/{T}/export.csv")
rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
check(r.ok and rows[:3] == [["Hours", "Fee", "Rate"], ["1234.57", "1235", "19.5%"], ["2469.14", "", ""]], "CSV " + str(rows[:3]))

# ================================================================ .xlsx: own number formats, the import reads them back
r = Fr.get(B + f"/api/sheets/{T}/export.xlsx")
check(r.ok, "xlsx export " + str(r.status_code))
z = zipfile.ZipFile(io.BytesIO(r.content))
st = z.read("xl/styles.xml").decode()
codes = [x.replace("&quot;", '"') for x in re.findall(r'formatCode="([^"]*)"', st)]
check('"$"#,##0' in codes, "the Fee format in dollars without places " + str(codes))
check("#,##0.00" in codes and "0.000%" in codes and '<numFmts count="4">' in st, "Hours / Rate formats, four in all " + str(codes))
r = Fr.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("Fees.xlsx", r.content)})
check(r.status_code == 201, "the file imported again " + r.text[:200])
IM = r.json()["sheet"]["id"] if r.ok else 0
d2 = get(IM)
got = [(c["title"], c["kind"], c.get("dec"), c.get("cur")) for c in d2.get("columns", [])[:3]]
check(got == [("Hours", "number", 2, None), ("Fee", "currency", 0, "USD"), ("Rate", "percent", 3, None)], "round trip: places and currency " + str(got))
check([at(d2, a).get("display") for a in ("A1", "B1", "C1")] == ["1,234.57", "$1,235", "19.500%"],
      "the imported table shows the same " + str([at(d2, a).get("display") for a in ("A1", "B1", "C1")]))
check(at(d2, "A1").get("value") == 1234.5678, "the imported value is full " + str(at(d2, "A1").get("value")))
# leader review (#5351): an uploaded formatCode is untrusted - a long one with an open quote and many ";" must not stall the
# import (the old lookahead split was quadratic: minutes), and a ";" inside quotes does not end the first section
XL = Fr.get(B + f"/api/sheets/{T}/export.xlsx").content
zi, zo = zipfile.ZipFile(io.BytesIO(XL)), io.BytesIO()
with zipfile.ZipFile(zo, "w", zipfile.ZIP_DEFLATED) as w:
    for it in zi.infolist():
        data = zi.read(it.filename)
        if it.filename == "xl/styles.xml":
            t = data.decode().replace('formatCode="#,##0.00"', 'formatCode="&quot;h;x&quot;#,##0.00"')
            t = t.replace('formatCode="0.000%"', 'formatCode="0.000%;&quot;' + ';' * 300000 + '"')
            data = t.encode()
        w.writestr(it, data)
t0 = time.monotonic()
r = Fr.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("Long.xlsx", zo.getvalue())}, timeout=120)
took = time.monotonic() - t0
print(f"  the import with the long number format took {took:.1f} s")
check(r.status_code == 201 and took < 5, f"an import with a 300 KB number format answers at once ({took:.1f} s) " + r.text[:200])
d4 = get(r.json()["sheet"]["id"]) if r.ok else {}
got4 = [(c["title"], c.get("dec")) for c in d4.get("columns", [])[:3]]
check(got4 == [("Hours", 2), ("Fee", 0), ("Rate", 3)], "a quoted ; and the cut long code keep the places " + str(got4))
# an .xlsx in the table's own currency (EUR, 2 places) stays automatic: no own format on the column
r = Fr.post(B + "/api/sheets", json={"title": "Plain", "space": "private"})
PL = r.json()["id"]
check(patch(PL, r.json()["columns"][0]["id"], {"title": "Amount", "kind": "currency"}).ok and put(PL, "A1", "12.5").ok, "a plain currency table")
r = Fr.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("Plain.xlsx", Fr.get(B + f"/api/sheets/{PL}/export.xlsx").content)})
c0 = (get(r.json()["sheet"]["id"]).get("columns") or [{}])[0] if r.status_code == 201 else {}
check(c0.get("kind") == "currency" and c0.get("dec") is None and c0.get("cur") is None, "the table's currency stays automatic " + str(c0))

# ================================================================ pivot: the sum in the column's format
r = Fr.post(B + f"/api/sheets/{T}/tabs", json={"name": "Sum", "pivot": {"source": T, "rows": [CA], "values": [{"col": CB, "agg": "sum"}]}})
check(r.status_code == 201, "a pivot sheet " + r.text[:200])
P = r.json()["tab"]["id"] if r.ok else 0
res = (get(P).get("pivot") or {}).get("result") or {}
check([x["d"] for x in res.get("total") or []][-1:] == ["$1,235"], "the pivot total in dollars without places " + str(res.get("total")))
check([x["d"] for x in (res.get("rows") or [[]])[0]][:1] == ["1,234.57"], "the row key in the Hours format " + str(res.get("rows")))

# ================================================================ API v1: an agent of frida
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "sheets:read", "sheets:write"], "username": "fridabot",
                                          "display_name": "Fridabot", "owner_id": FID})
check(r.status_code == 201, "frida's agent " + r.text[:200])
ag = requests.Session()
ag.headers.update({"Authorization": "Bearer " + r.json()["token"]})
r = ag.post(V + "/sheets", json={"title": "Costs", "columns": [{"title": "Net", "kind": "currency", "dec": 1, "cur": "GBP"}],
                                 "rows": [["12.345"]]})
check(r.status_code == 201, "sheet_create with dec / cur " + r.text[:300])
AS = r.json().get("id") if r.ok else 0
d3 = ag.get(V + f"/sheets/{AS}").json()
check((d3["columns"][0].get("dec"), d3["columns"][0].get("cur")) == (1, "GBP") and at(d3, "A1").get("display") == "£12.3",
      "the agent reads the column's format and the display " + str((d3["columns"][0], at(d3, "A1").get("display"))))
r = ag.post(V + f"/sheets/{AS}/columns", json={"title": "Tax", "kind": "percent", "dec": 7})
check(r.status_code == 400, "a new column with dec 7: 400 " + str(r.status_code))
r = ag.post(V + f"/sheets/{AS}/columns", json={"title": "Tax", "kind": "percent", "dec": 0})
check(r.status_code == 201, "a new column with dec 0 " + r.text[:200])
check([c.get("dec") for c in ag.get(V + f"/sheets/{AS}").json()["columns"]][-1:] == [0], "its dec is stored")
r = ag.post(V + "/sheets", json={"title": "Bad", "columns": [{"title": "X", "kind": "currency", "cur": "ABC"}]})
check(r.status_code == 400, "sheet_create with an unknown currency: 400 " + str(r.status_code))

sys.exit(kt.done("p2769_c_sheetfmt"))
