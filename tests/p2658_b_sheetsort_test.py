#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.658.0 part B API test (#5000): sorting keeps the span of formula ranges. Invented names only.
 - rows/order without moved (a sorting): SUM(A1:A3) stays SUM(A1:A3) and sums what stands there now (row 4 sorted to the top:
   4+1+2 = 7; before 2.658 its corners followed and it became SUM(A2:A4) = 6); a single reference follows its cell
   (=A1*10 shows =A2*10, value 10); a range one row deep (the row's own total SUM(A1:C1)) follows its row
 - sorting back gives every formula as before (the rule is its own Undo)
 - columns/order without moved: the same for columns, also for a range from another sheet of the table
 - the Undo of a move that changed no formula (the whole range moved, its corners followed) sends formulas: [] and is no
   sorting: the range goes back with its rows
 - inserting a row above (sheets.js: a move of the new row, moved = [it]) inside a range widens it like before
All as a person without an organisation (frida).
freelancer-matrix: sheets
usage: p2658_b_sheetsort_test.py <datadir>      (a fresh container; P2658BS_NOSTART=1 = the server already runs)"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402

kt.fresh(prefix="P2658BS")
H = {"X-Requested-With": "kalmido"}
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "sheets,collab,comments", "tour": "done"})
FID, Fr = freelancer(B, A)


def get(sid):
    return Fr.get(B + f"/api/sheets/{sid}").json()


def cell(d, addr):
    return next((x for x in d["cells"] if x["addr"] == addr), None) or {}


def line(d, key):
    return [x["id"] for x in sorted(d[key], key=lambda x: x["pos"])]


def order(sid, kind, ids, prev, **kw):
    return Fr.post(B + f"/api/sheets/{sid}/{kind}/order", json={"ids": ids, "prev": prev, **kw})


def new_sheet(title, cells):
    r = Fr.post(B + "/api/sheets", json={"title": title, "space": "private"})
    check(r.status_code == 201, f"a table {title} " + r.text[:200])
    sid = r.json()["id"]
    for cid in line(get(sid), "columns"):
        Fr.patch(B + f"/api/sheets/{sid}/columns/{cid}", json={"kind": "number"})
    r = Fr.put(B + f"/api/sheets/{sid}/cells", json={"cells": [{"cell": a, "raw": v} for a, v in cells]})
    check(r.ok, f"{title}: the cells " + r.text[:200])
    return sid


def raws(d, addrs):
    return [cell(d, a).get("raw") for a in addrs]


# ---- rows sorted
SID = new_sheet("Sorting", [("A1", "1"), ("A2", "2"), ("A3", "3"), ("A4", "4"), ("B1", "=A1*10"), ("C1", "=SUM(A1:B1)"),
                            ("B6", "=SUM(A1:A3)"), ("C6", "=SUM(A2:A4)")])
d = get(SID)
R = line(d, "rows")
check(cell(d, "B6").get("value") == 6 and cell(d, "C1").get("value") == 11, "start: SUM(A1:A3) = 6, the row total = 11")
srt = [R[3], R[0], R[1], R[2]] + R[4:]  # row 4 (value 4) on top, like a descending sorting would put it
r = order(SID, "rows", srt, R)
check(r.ok and "formulas" not in r.json(), "a sorting (no moved) " + r.text[:200])
d = get(SID)
check(cell(d, "B6").get("raw") == "=SUM(A1:A3)" and cell(d, "B6").get("value") == 7,
      "SUM(A1:A3) keeps its span and sums 4+1+2 = 7 (before 2.658: SUM(A2:A4) = 6) " + str(cell(d, "B6")))
check(cell(d, "C6").get("raw") == "=SUM(A2:A4)" and cell(d, "C6").get("value") == 6, "SUM(A2:A4) keeps its span too = 1+2+3 " + str(cell(d, "C6")))
check(cell(d, "B2").get("raw") == "=A2*10" and cell(d, "B2").get("value") == 10, "a single reference follows its cell " + str(cell(d, "B2")))
check(cell(d, "C2").get("raw") == "=SUM(A2:B2)" and cell(d, "C2").get("value") == 11, "a one-row range (its row's total) follows its row " + str(cell(d, "C2")))
r = order(SID, "rows", R, srt)
d = get(SID)
check(r.ok and raws(d, ("B1", "C1", "B6", "C6")) == ["=A1*10", "=SUM(A1:B1)", "=SUM(A1:A3)", "=SUM(A2:A4)"] and cell(d, "B6").get("value") == 6,
      "sorting back: every formula as before " + str(raws(d, ("B1", "C1", "B6", "C6"))))

# ---- the Undo of a move that changed no formula is no sorting
US = new_sheet("Undo", [("A1", "1"), ("A2", "2"), ("A3", "3"), ("A4", "4"), ("C6", "=SUM(A1:A2)")])
U = line(get(US), "rows")
mv = U[2:4] + U[:2] + U[4:]  # rows 1-2 (the whole of SUM(A1:A2)) below row 4
r = order(US, "rows", mv, U, moved=U[:2])
d = get(US)
check(r.ok and r.json().get("formulas") == [] and cell(d, "C6").get("raw") == "=SUM(A3:A4)" and cell(d, "C6").get("value") == 3,
      "a range moved as a whole follows its rows, no formula named " + str(cell(d, "C6")) + " " + r.text[:200])
r = order(US, "rows", U, mv, formulas=[])
d = get(US)
check(r.ok and line(d, "rows") == U and cell(d, "C6").get("raw") == "=SUM(A1:A2)" and cell(d, "C6").get("value") == 3,
      "its Undo (formulas: []) brings the range back with its rows, not kept on 3-4 like a sorting " + str(cell(d, "C6")))

# ---- a row inserted above row 2 (a move of the new row, as the grid sends it) widens SUM(A1:A3)
r = Fr.post(B + f"/api/sheets/{SID}/rows", json={})
check(r.ok, "a new row " + r.text[:200])
L = line(get(SID), "rows")
nid = [x for x in L if x not in R]
check(len(nid) == 1, "one new row " + str(nid))
ins = [R[0]] + nid + [x for x in L if x != R[0] and x not in nid]
r = order(SID, "rows", ins, L, moved=nid)
d = get(SID)
check(r.ok and cell(d, "B7").get("raw") == "=SUM(A1:A4)" and cell(d, "B7").get("value") == 6, "the inserted row is inside the range " + str(cell(d, "B7")))

# ---- columns sorted, with a range from another sheet of the table
CS = new_sheet("Columns", [("A1", "1"), ("B1", "2"), ("C1", "3"), ("A3", "=SUM(A1:B1)"), ("B3", "=C1")])
r = Fr.post(B + f"/api/sheets/{CS}/tabs", json={"name": "Other"})
OT = (r.json().get("tab") or {}).get("id") if r.ok else None
check(OT, "a second sheet " + r.text[:200])
if OT:
    check(Fr.put(B + f"/api/sheets/{OT}/cells", json={"cells": [{"cell": "A1", "raw": "=SUM('Sheet 1'!A1:B1)"}]}).ok, "a range into the first sheet")
C = line(get(CS), "columns")
newc = [C[2], C[0], C[1]] + C[3:]  # column C first
r = order(CS, "columns", newc, C)
check(r.ok, "columns sorted " + r.text[:200])
d = get(CS)
a3 = next((x for x in d["cells"] if x["addr"].endswith("3") and (x.get("raw") or "").startswith("=SUM")), {})
check(a3.get("raw") == "=SUM(A1:B1)" and a3.get("value") == 4, "SUM(A1:B1) keeps its columns' span: 3+1 = 4 " + str(a3))
b3 = next((x for x in d["cells"] if x.get("raw") == "=A1"), {})
check(b3.get("value") == 3, "=C1 follows its column: =A1 = 3 " + str(b3))
if OT:
    o = cell(get(OT), "A1")
    check("!A1:B1" in (o.get("raw") or "") and o.get("value") == 4, "the range from the other sheet keeps its span = 4 " + str(o))
r = order(CS, "columns", C, newc)
d = get(CS)
check(r.ok and line(d, "columns") == C and cell(d, "A3").get("raw") == "=SUM(A1:B1)" and cell(d, "A3").get("value") == 3, "columns sorted back " + str(cell(d, "A3")))

print(f"p2658_b_sheetsort: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
