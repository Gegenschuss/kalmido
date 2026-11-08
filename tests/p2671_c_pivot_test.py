#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.671.0 part C API test (#3463 b): the pivot sheet of a table. Invented names only.
 - a pivot sheet (POST /api/sheets/<id>/tabs {pivot}) has no cells; its table is computed from the source sheet on every
   read: sum / count / average per row field, the same numbers as SUMME / MITTELWERT over the same cells, the grand total
 - a column field (one column per value, a total column), a filter, a count of rows (col null), several row fields
 - always up to date: a change in the source shows at the next read (rev and etag of the pivot sheet move)
 - the setting is saved with its version (expect_updated_at: an old one -> 409 with "pivot"), a wrong setting -> 400
 - a pivot sheet takes no write of its own (cells, rows, columns: 409); its kind in the sheet bar (tabs)
 - rights are the table's: a stranger 404 (read, setting), a read share reads it and changes nothing (403)
 - .xlsx of the table writes the pivot's computed values; CSV of the pivot sheet = its table
 - API v1: an agent reads kind / pivot.result of a pivot sheet, its write is refused (409)
freelancer-matrix: sheets
usage: p2671_c_pivot_test.py <datadir>      (a fresh container; P2671C_NOSTART=1 = the server already runs)"""
import io
import os
import re
import sys
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402

V = B + "/api/v1"
kt.fresh(prefix="P2671C")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en"})
uid = {}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": kt.PASSWORD, "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca, Er = sess("bob"), sess("carol"), sess("erin")
for s in (Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"features": "sheets,collab,comments,office", "lang": "en", "tour": "done"})


def get(s, sid, **params):
    r = s.get(B + f"/api/sheets/{sid}", params=params)
    return r.json() if r.ok else {"_status": r.status_code}


def put(s, sid, cell, raw):
    return s.put(B + f"/api/sheets/{sid}/cells", json={"cells": [{"cell": cell, "raw": raw}]})


def at(d, addr):
    return next((c for c in d.get("cells", []) if c["addr"] == addr), {})


def res(s, pid):
    return (get(s, pid).get("pivot") or {}).get("result") or {}


def vals(rows):
    """[[shown texts]] of result rows."""
    return [[x["d"] for x in r] for r in rows or []]


# ================================================================ the source: Client | Month | Amount (currency)
T = Bo.post(B + "/api/sheets", json={"title": "Sales", "space": "private"}).json()["id"]
cols = [c["id"] for c in get(Bo, T)["columns"]]
CA, CB, CC = cols[:3]
for cid, title, kind in ((CA, "Client", "text"), (CB, "Month", "text"), (CC, "Amount", "currency")):
    check(Bo.patch(B + f"/api/sheets/{T}/columns/{cid}", json={"title": title, "kind": kind}).ok, f"column {title}")
DATA = [("Acme", "Jan", "100"), ("Acme", "Feb", "50"), ("Beta", "Jan", "30"), ("Beta", "Jan", ""), ("Gamma", "Feb", "=C1+C2")]
for i, row in enumerate(DATA, 1):
    for L, v in zip("ABC", row):
        if v:
            check(put(Bo, T, f"{L}{i}", v).ok, f"source {L}{i}")
check(at(get(Bo, T), "C5").get("value") == 150, "a formula in the source: =C1+C2 = 150")

# ================================================================ a pivot sheet: rows Client, sum / count / average of Amount
SPEC = {"source": T, "rows": [CA], "values": [{"col": CC, "agg": "sum"}, {"col": CC, "agg": "count"}, {"col": CC, "agg": "avg"}]}
r = Bo.post(B + f"/api/sheets/{T}/tabs", json={"name": "By client", "pivot": SPEC})
check(r.status_code == 201, "a pivot sheet " + r.text[:300])
P = r.json()["tab"]["id"] if r.ok else 0
tabs = {t["id"]: t for t in r.json().get("tabs", [])}
check(tabs.get(P, {}).get("kind") == "pivot" and tabs.get(T, {}).get("kind") == "sheet", "the sheet bar knows the kind " + str(tabs))
d = get(Bo, P)
check(d.get("kind") == "pivot" and d.get("columns") == [] and d.get("cells") == [] and d.get("book_id") == T,
      "a pivot sheet has no cells of its own " + str({k: d.get(k) for k in ("kind", "columns", "book_id")}))
x = res(Bo, P)
check(x.get("header") == ["Client", "Sum of Amount", "Count of Amount", "Average of Amount"], "the header " + str(x.get("header")))
check(vals(x.get("rows")) == [["Acme", "€150.00", "2", "€75.00"], ["Beta", "€30.00", "1", "€30.00"], ["Gamma", "€150.00", "1", "€150.00"]],
      "sum / count / average per client " + str(vals(x.get("rows"))))
check([c["d"] for c in x.get("total") or []] == ["Total", "€330.00", "4", "€82.50"], "the grand total " + str(x.get("total")))
check(x.get("source") == {"id": T, "name": "Sheet 1"} and x.get("error") is None, "its source " + str(x.get("source")))
# the same numbers as the formulas
r = Bo.post(B + f"/api/sheets/{T}/tabs", json={"name": "Check"})
S2 = r.json()["tab"]["id"] if r.ok else 0
check(put(Bo, S2, "A1", "=SUMME('Sheet 1'!C1:C5)").ok and put(Bo, S2, "A2", "=MITTELWERT('Sheet 1'!C1:C5)").ok, "formulas over the source")
d2 = get(Bo, S2)
check(at(d2, "A1").get("value") == x["total"][1]["v"] == 330 and at(d2, "A2").get("value") == x["total"][3]["v"] == 82.5,
      "pivot total = SUMME, average = MITTELWERT " + str((at(d2, "A1").get("value"), at(d2, "A2").get("value"), x["total"])))

# ================================================================ the setting: version, column field, filter, count of rows
pv = get(Bo, P)["pivot"]
ver = pv["updated_at"]
check(bool(ver) and pv["source"] == T and pv["rows"] == [CA], "the setting is read back " + str({k: pv.get(k) for k in ("source", "rows", "updated_at")}))
r = Bo.put(B + f"/api/sheets/{T}/tabs/{P}/pivot", json={"source": T, "rows": [CA], "cols": CB, "values": [{"col": CC, "agg": "sum"}],
                                                        "expect_updated_at": ver})
check(r.ok, "a column field " + r.text[:300])
x = r.json().get("pivot", {}).get("result", {}) if r.ok else {}
check(x.get("header") == ["Client", "Feb", "Jan", "Total"], "one column per month, then the total " + str(x.get("header")))
check(vals(x.get("rows")) == [["Acme", "€50.00", "€100.00", "€150.00"], ["Beta", "", "€30.00", "€30.00"], ["Gamma", "€150.00", "", "€150.00"]],
      "the cells by client and month " + str(vals(x.get("rows"))))
check([c["d"] for c in x.get("total") or []] == ["Total", "€200.00", "€130.00", "€330.00"], "the totals per month " + str(x.get("total")))
r = Bo.put(B + f"/api/sheets/{T}/tabs/{P}/pivot", json={**SPEC, "expect_updated_at": ver})
check(r.status_code == 409 and isinstance(r.json().get("pivot"), dict), "an old version: 409 with the current setting " + r.text[:200])
ver = get(Bo, P)["pivot"]["updated_at"]
r = Bo.put(B + f"/api/sheets/{T}/tabs/{P}/pivot", json={**SPEC, "filter": [{"col": CA, "values": ["Acme", "Gamma"]}], "expect_updated_at": ver})
check(r.ok and [row[0]["d"] for row in r.json()["pivot"]["result"]["rows"]] == ["Acme", "Gamma"]
      and r.json()["pivot"]["result"]["total"][1]["v"] == 300, "a filter: only Acme and Gamma " + r.text[:300])
r = Bo.put(B + f"/api/sheets/{T}/tabs/{P}/pivot", json={"source": T, "rows": [CB], "values": [{"col": None, "agg": "count"}]})
check(r.ok and vals(r.json()["pivot"]["result"]["rows"]) == [["Feb", "2"], ["Jan", "3"]]
      and r.json()["pivot"]["result"]["header"] == ["Month", "Count"], "the number of rows per month " + r.text[:300])
r = Bo.put(B + f"/api/sheets/{T}/tabs/{P}/pivot", json={"source": T, "rows": [CB, CA], "values": [{"col": CC, "agg": "sum"}]})
check(r.ok and vals(r.json()["pivot"]["result"]["rows"]) == [["Feb", "Acme", "€50.00"], ["Feb", "Gamma", "€150.00"], ["Jan", "Acme", "€100.00"], ["Jan", "Beta", "€30.00"]]
      and [c["d"] for c in r.json()["pivot"]["result"]["total"]] == ["Total", "", "€330.00"], "two row fields " + r.text[:400])
# wrong settings
for what, b in (("the pivot itself as source", {"source": P, "values": [{"col": CC, "agg": "sum"}]}),
                ("a column of another sheet", {"source": T, "rows": [get(Bo, S2)["columns"][0]["id"]], "values": [{"col": CC, "agg": "sum"}]}),
                ("an unknown calculation", {"source": T, "values": [{"col": CC, "agg": "median"}]}),
                ("no value", {"source": T, "values": []}),
                ("a sum without a column", {"source": T, "values": [{"col": None, "agg": "sum"}]}),
                ("row and column field at once", {"source": T, "rows": [CA], "cols": CA, "values": [{"col": CC, "agg": "sum"}]})):
    check(Bo.put(B + f"/api/sheets/{T}/tabs/{P}/pivot", json=b).status_code == 400, f"400: {what}")
check(Bo.post(B + f"/api/sheets/{T}/tabs", json={"pivot": {"source": 999999, "values": [{"col": CC, "agg": "sum"}]}}).status_code == 400,
      "a new pivot of a sheet that is not in the table: 400")
# 2.671.0 (#3463, review R2 F1): a sheet of ANOTHER table is never a source - not one of a stranger (Erin's private table, Bob
# cannot read it), not one of Bob's own other tables; both answer exactly as a sheet that does not exist (no hint whether it exists)
ET = Er.post(B + "/api/sheets", json={"title": "Erin's", "space": "private"}).json()["id"]
BT = Bo.post(B + "/api/sheets", json={"title": "Bob's other", "space": "private"}).json()["id"]
none = Bo.put(B + f"/api/sheets/{T}/tabs/{P}/pivot", json={"source": 999999, "values": [{"col": None, "agg": "count"}]})
for what, src in (("a stranger's table", ET), ("an own other table", BT)):
    for how, resp in (("setting", Bo.put(B + f"/api/sheets/{T}/tabs/{P}/pivot", json={"source": src, "values": [{"col": None, "agg": "count"}]})),
                      ("new pivot", Bo.post(B + f"/api/sheets/{T}/tabs", json={"pivot": {"source": src, "values": [{"col": None, "agg": "count"}]}}))):
        check(resp.status_code == 400 and resp.json() == none.json(), f"{what} as source ({how}): 400, the same answer as an unknown sheet " + resp.text[:200])
check(res(Bo, P).get("source", {}).get("id") == T, "the setting stays on the own table's sheet")
check(Bo.put(B + f"/api/sheets/{T}/tabs/{S2}/pivot", json=SPEC).status_code == 409, "an ordinary sheet has no pivot setting: 409")
check(Bo.put(B + f"/api/sheets/{T}/tabs/{P}/pivot", json=SPEC).ok, "back to clients")

# ================================================================ always up to date
d0 = get(Bo, P)
check(put(Bo, T, "C1", "200").ok, "a change in the source")
d1 = get(Bo, P)
check(d1["pivot"]["result"]["rows"][0][1]["v"] == 250 and d1["pivot"]["result"]["total"][1]["v"] == 530,
      "the pivot shows it at the next read " + str(d1["pivot"]["result"]["rows"][0]))
check(d1["rev"] > d0["rev"] and d1.get("etag") != d0.get("etag"), "its rev and etag move (the open view reloads)")
check(Bo.get(B + f"/api/sheets/{P}", params={"etag": d1["etag"]}).json().get("unchanged") is True, "unchanged: the small answer")
check(put(Bo, T, "A6", "Delta").ok and put(Bo, T, "C6", "5").ok and [x[0]["d"] for x in res(Bo, P)["rows"]] == ["Acme", "Beta", "Delta", "Gamma"],
      "a new row in the source: a new group (sorted)")

# ================================================================ no writes of its own
check(put(Bo, P, "A1", "1").status_code == 409, "cells of a pivot sheet: 409")
check(Bo.post(B + f"/api/sheets/{P}/rows", json={"count": 1}).status_code == 409, "rows: 409")
check(Bo.post(B + f"/api/sheets/{P}/columns", json={"title": "x", "kind": "text"}).status_code == 409, "columns: 409")
check(Bo.patch(B + f"/api/sheets/{T}/tabs/{P}", json={"name": "Clients"}).ok, "renamed through the sheet bar")
check(Bo.post(B + f"/api/sheets/{P}/tabs", json={"name": "Another"}).status_code == 201, "a new sheet asked through the pivot sheet")
r = Bo.post(B + f"/api/sheets/{T}/tabs", json={"copy_of": P, "name": "Clients copy"})
check(r.status_code == 201 and get(Bo, r.json()["tab"]["id"]).get("kind") == "pivot", "a copy of a pivot sheet is a pivot sheet")
Q = Bo.post(B + f"/api/sheets/{T}/tabs", json={"name": "All rows", "pivot": {"source": T, "values": [{"col": None, "agg": "count"}]}}).json()["tab"]["id"]
check(res(Bo, Q).get("rows") and res(Bo, Q)["rows"][0][0]["v"] == 6 and res(Bo, Q).get("total") is None,
      "no row field: one row, the count of all rows " + str(res(Bo, Q)))
# the source in the trash -> a hint instead of the table, back -> the table again
R = Bo.post(B + f"/api/sheets/{T}/tabs", json={"name": "Of check", "pivot": {"source": S2, "values": [{"col": None, "agg": "count"}]}}).json()["tab"]["id"]
check(Bo.delete(B + f"/api/sheets/{T}/tabs/{S2}").ok and res(Bo, R).get("error") and res(Bo, R).get("rows") == [], "the source in the trash: a hint " + str(res(Bo, R)))
check(Bo.post(B + f"/api/sheets/{T}/tabs/{S2}/restore").ok and res(Bo, R).get("error") is None, "back: the table again")

# ================================================================ rights
# tenant-matrix: sheet
for what, resp in (("read", Er.get(B + f"/api/sheets/{P}")), ("setting", Er.put(B + f"/api/sheets/{T}/tabs/{P}/pivot", json=SPEC)),
                   ("new pivot", Er.post(B + f"/api/sheets/{T}/tabs", json={"pivot": SPEC})), ("carol, no share", Ca.get(B + f"/api/sheets/{P}")),
                   ("xlsx", Er.get(B + f"/api/sheets/{P}/export.xlsx"))):
    check(resp.status_code == 404, f"a stranger: {what} 404 ({resp.status_code})")
check(Bo.post(B + f"/api/sheets/{T}/shares", json={"user_id": uid["carol"], "role": "read"}).status_code == 201, "shared with carol to read")
check(res(Ca, P).get("total", [{}, {}])[1].get("v") == 535, "a read share reads the pivot " + str(res(Ca, P).get("total")))
check(Ca.put(B + f"/api/sheets/{T}/tabs/{P}/pivot", json=SPEC).status_code == 403
      and Ca.post(B + f"/api/sheets/{T}/tabs", json={"pivot": SPEC}).status_code == 403, "... and changes no setting (403)")

# ================================================================ export
r = Bo.get(B + f"/api/sheets/{T}/export.xlsx")
check(r.ok, "the table as .xlsx")
z = zipfile.ZipFile(io.BytesIO(r.content))
wb = z.read("xl/workbook.xml").decode()
names = re.findall(r'<sheet name="([^"]+)"', wb)
check("Clients" in names, "the pivot sheet is a worksheet " + str(names))
ws = z.read(f"xl/worksheets/sheet{names.index('Clients') + 1}.xml").decode()
check("Sum of Amount" in ws and "<v>535</v>" in ws and "<v>250</v>" in ws and "<f>" not in ws, "its computed values, no formulas " + ws[:600])
r = Bo.get(B + f"/api/sheets/{P}/export.csv")
check(r.ok and "Acme" in r.text and "Sum of Amount" in r.text and "Total" in r.text, "CSV of the pivot sheet: its table " + r.text[:200])

# ================================================================ a person without an organisation + her agent (API v1)
# freelancer-matrix: sheets
FID, Fl = freelancer(B, A, features=FEATURES + ",sheets")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "sheets:read", "sheets:write"], "username": "fridabot", "display_name": "Fridabot",
                                          "org_id": None, "owner_id": FID})
assert r.status_code == 201, r.text
da = requests.Session()
da.headers.update({"Authorization": "Bearer " + r.json()["token"]})
r = da.post(V + "/sheets", json={"title": "Hours", "space": "private", "columns": [{"title": "Who", "kind": "text"}, {"title": "Hours", "kind": "number"}],
                                 "rows": [["Ann", "3"], ["Ben", "2"], ["Ann", "4"]]})
check(r.status_code == 201, "her agent's table " + r.text[:200])
DT = r.json().get("id")
dc = [c["id"] for c in r.json().get("columns", [])]
r = Fl.post(B + f"/api/sheets/{DT}/tabs", json={"name": "Per person", "pivot": {"source": DT, "rows": [dc[0]], "values": [{"col": dc[1], "agg": "sum"}]}})
check(r.status_code == 201, "freelancer: a pivot sheet " + r.text[:200])
FP = r.json()["tab"]["id"] if r.ok else 0
check(vals(res(Fl, FP).get("rows")) == [["Ann", "7"], ["Ben", "2"]], "freelancer: the sums " + str(res(Fl, FP)))
ver = get(Fl, FP)["pivot"]["updated_at"]
check(Fl.put(B + f"/api/sheets/{DT}/tabs/{FP}/pivot", json={"source": DT, "rows": [dc[0]], "values": [{"col": dc[1], "agg": "avg"}], "expect_updated_at": ver}).ok
      and vals(res(Fl, FP).get("rows")) == [["Ann", "3.5"], ["Ben", "2"]], "freelancer: the average")
check(Bo.get(B + f"/api/sheets/{FP}").status_code == 404, "another person never sees it")
d = da.get(V + f"/sheets/{FP}")
check(d.ok and d.json().get("kind") == "pivot" and vals(d.json()["pivot"]["result"]["rows"]) == [["Ann", "3.5"], ["Ben", "2"]],
      "API v1: the agent reads the pivot sheet's table " + d.text[:300])
t = da.get(V + f"/sheets/{DT}/tabs")
check(t.ok and [x.get("kind") for x in t.json()["data"]] == ["sheet", "pivot"], "API v1: the kind in the sheets of the table " + t.text[:300])
rv = d.json().get("rev") if d.ok else 0
check(da.put(V + f"/sheets/{FP}/cells", json={"cells": [{"cell": "A1", "raw": "1"}], "expect_rev": rv}).status_code == 409, "API v1: no cells in a pivot sheet (409)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
