#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.631.0 part B API test (#4620): moving rows and columns of a table -- the server part. Invented names only.
 - rows/order with moved: a single reference follows its cell (=A1*10 shows =A3*10 after row 1 went down), the value stays
 - ranges keep their rows: SUM(A1:A3) with row 1 moved below row 5 is SUM(A1:A2) over the two rows left (5, not the 2..5
   the corners alone would span), a row dropped into a range belongs to it, a member dragged to right below the range's
   last row stays in it (SUM(A1:A5) above a total), a block of two rows taken out leaves it; the answer names the changed
   formulas (raw before, now after)
 - the Undo (old order + formulas, without moved) gives back every formula and value exactly
 - a sorting (rows/order without moved) keeps each range's span (2.658.0, #5000: SUM(A1:A3) stays A1:A3)
 - columns/order (new): the same for columns, a range in another sheet of the table ('Sheet 1'!A1:B1) too; prev guards (409)
 - moved / formulas malformed: 400; only reading (a share to read): 403 for both routes; another person's table: refused
All as a person without an organisation (frida), the reader is bob with a read share on alice's table.
freelancer-matrix: sheets
usage: p2631_b_sheet_move_test.py <datadir>      (a fresh container; P2631BS_NOSTART=1 = the server already runs)"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402

kt.fresh(prefix="P2631BS")
H = {"X-Requested-With": "kalmido"}
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "sheets,collab,comments", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": "sheets,collab,comments", "tour": "done"})
FID, Fr = freelancer(B, A)


def get(s, sid):
    return s.get(B + f"/api/sheets/{sid}").json()


def cell(d, addr):
    return next((x for x in d["cells"] if x["addr"] == addr), None) or {}


def rows(d):
    return [x["id"] for x in sorted(d["rows"], key=lambda x: x["pos"])]


def cols(d):
    return [x["id"] for x in sorted(d["columns"], key=lambda x: x["pos"])]


def order(s, sid, kind, ids, prev=None, **kw):
    return s.post(B + f"/api/sheets/{sid}/{kind}/order", json={"ids": ids, **({"prev": prev} if prev is not None else {}), **kw})


def new_sheet(s, title, cells, space="private"):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space})
    check(r.status_code == 201, f"a table {title} " + r.text[:200])
    sid = r.json()["id"]
    for cid in cols(get(s, sid)):
        s.patch(B + f"/api/sheets/{sid}/columns/{cid}", json={"kind": "number"})
    r = s.put(B + f"/api/sheets/{sid}/cells", json={"cells": [{"cell": a, "raw": v} for a, v in cells]})
    check(r.ok, f"{title}: the cells " + r.text[:200])
    return sid


# ---- rows: single references follow, ranges keep their rows
SID = new_sheet(Fr, "Moving", [("A1", "1"), ("A2", "2"), ("A3", "3"), ("A4", "4"), ("A5", "5"),
                               ("B1", "=A1*10"), ("B6", "=SUM(A1:A3)"), ("C6", "=SUM(A2:A4)"), ("C7", "=SUM(A1:A5)")])
d = get(Fr, SID)
R = rows(d)
check(cell(d, "B6").get("value") == 6 and cell(d, "C6").get("value") == 9, "start: SUM(A1:A3) = 6, SUM(A2:A4) = 9 " + str(cell(d, "B6")))
# row 1 below row 5 (the block = row 1): 2 3 4 5 1 6 7 ...
new = R[1:5] + [R[0]] + R[5:]
r = order(Fr, SID, "rows", new, prev=R, moved=[R[0]])
check(r.ok, "rows/order with moved " + r.text[:300])
fx = r.json().get("formulas") if r.ok else None
d = get(Fr, SID)
check(rows(d) == new, "the new order is stored")
check(cell(d, "B5").get("raw") == "=A5*10" and cell(d, "B5").get("value") == 10, "a single reference follows its cell: =A5*10 = 10 " + str(cell(d, "B5")))
check(cell(d, "B6").get("raw") == "=SUM(A1:A2)" and cell(d, "B6").get("value") == 5,
      "SUM(A1:A3) keeps rows 2 and 3 only: =SUM(A1:A2) = 5 (the corners alone would take 2..5 = 14) " + str(cell(d, "B6")))
check(cell(d, "C6").get("raw") == "=SUM(A1:A3)" and cell(d, "C6").get("value") == 9, "a range the row was never in stays on its rows " + str(cell(d, "C6")))
check(cell(d, "C7").get("raw") == "=SUM(A1:A5)" and cell(d, "C7").get("value") == 15,
      "a member dragged to right below the range's last row (above the total) stays in it " + str(cell(d, "C7")))
check(isinstance(fx, list) and sorted((f.get("raw"), f.get("now")) for f in fx) == [("=SUM(A1:A3)", "=SUM(A1:A2)"), ("=SUM(A1:A5)", "=SUM(A1:A5)")],
      "the answer names the changed formulas (before / after) " + str(fx))
# the Undo: the old order with the formulas -> exactly as before
r = order(Fr, SID, "rows", R, prev=new, formulas=fx or [])
check(r.ok and "formulas" not in r.json(), "the Undo is accepted " + r.text[:200])
d = get(Fr, SID)
check(rows(d) == R, "Undo: the old order")
check([cell(d, a).get("raw") for a in ("B1", "B6", "C6", "C7")] == ["=A1*10", "=SUM(A1:A3)", "=SUM(A2:A4)", "=SUM(A1:A5)"]
      and cell(d, "B6").get("value") == 6, "Undo: every formula as before " + str([cell(d, a).get("raw") for a in ("B1", "B6", "C6", "C7")]))
# a row dropped into a range belongs to it: row 5 between rows 1 and 2
new2 = [R[0], R[4], R[1], R[2], R[3]] + R[5:]
r = order(Fr, SID, "rows", new2, prev=R, moved=[R[4]])
d = get(Fr, SID)
check(r.ok and cell(d, "B6").get("raw") == "=SUM(A1:A4)" and cell(d, "B6").get("value") == 11,
      "a row dropped into SUM(A1:A3) is in it: =SUM(A1:A4) = 11 " + str(cell(d, "B6")))
order(Fr, SID, "rows", R, prev=new2, formulas=r.json().get("formulas") or [])
# two rows moved together (the block 1-2 below row 4): SUM(A1:A3) keeps row 3 only
new3 = [R[2], R[3], R[0], R[1]] + R[4:]
r = order(Fr, SID, "rows", new3, prev=R, moved=[R[0], R[1]])
d = get(Fr, SID)
check(r.ok and cell(d, "B6").get("value") == 3,
      "a block of two rows out of SUM(A1:A3): only row 3 is left = 3 " + str(cell(d, "B6")))
order(Fr, SID, "rows", R, prev=new3, formulas=r.json().get("formulas") or [])
d = get(Fr, SID)
check(rows(d) == R and cell(d, "B6").get("raw") == "=SUM(A1:A3)", "Undo of the block: as before " + str(cell(d, "B6")))
# 2.658.0 (#5000): a sorting (no moved) keeps each range's span on its positions (was: the corners followed, =SUM(A2:A3) = 4)
srt = [R[1], R[0]] + R[2:]
r = order(Fr, SID, "rows", srt, prev=R)
check(r.ok and "formulas" not in r.json(), "a sorting without moved: no formulas in the answer")
d = get(Fr, SID)
check(cell(d, "B6").get("raw") == "=SUM(A1:A3)" and cell(d, "B6").get("value") == 6, "a sorting keeps the range's span " + str(cell(d, "B6")))
order(Fr, SID, "rows", R, prev=srt)
check(cell(get(Fr, SID), "B6").get("raw") == "=SUM(A1:A3)", "sorting back: the span as before")
# prev guards a move elsewhere since
check(order(Fr, SID, "rows", new, prev=srt, moved=[R[0]]).status_code == 409, "rows/order: a stale prev gives 409")
check(order(Fr, SID, "rows", new, prev=R, moved=[999999]).status_code == 400, "rows/order: moved with an unknown row: 400")
check(order(Fr, SID, "rows", new, prev=R, moved="x").status_code == 400, "rows/order: moved not a list: 400")
check(order(Fr, SID, "rows", R, formulas=[{"sheet_id": SID}]).status_code == 400, "rows/order: malformed formulas: 400")

# ---- columns/order: the same for columns, also from another sheet of the table
CS = new_sheet(Fr, "Columns", [("A1", "1"), ("B1", "2"), ("C1", "3"), ("A2", "=SUM(A1:B1)"), ("B2", "=C1")])
r = Fr.post(B + f"/api/sheets/{CS}/tabs", json={"name": "Other"})
check(r.status_code in (200, 201), "a second sheet " + r.text[:200])
OT = (r.json().get("tab") or {}).get("id") if r.ok else None
check(OT, "the second sheet's id " + r.text[:200])
if OT:
    r = Fr.put(B + f"/api/sheets/{OT}/cells", json={"cells": [{"cell": "A1", "raw": "=SUM('Sheet 1'!A1:B1)"}]})
    check(r.ok, "a range into the first sheet " + r.text[:200])
d = get(Fr, CS)
C = cols(d)
newc = [C[1], C[2], C[0]] + C[3:]  # column A to the right of C
r = Fr.post(B + f"/api/sheets/{CS}/columns/order", json={"ids": newc, "prev": C, "moved": [C[0]]})  # the freelancer's call (coverage)
check(r.ok, "columns/order " + r.text[:300])
fxc = r.json().get("formulas") or [] if r.ok else []
d = get(Fr, CS)
check(cols(d) == newc, "the new column order is stored")
check(cell(d, "C2").get("value") == 2, "SUM(A1:B1) keeps column B only = 2 " + str(cell(d, "C2")))
check(cell(d, "A2").get("raw") == "=B1" and cell(d, "A2").get("value") == 3, "=C1 follows its column: =B1 " + str(cell(d, "A2")))
if OT:
    o = get(Fr, OT)
    check(cell(o, "A1").get("value") == 2, "the range from the other sheet keeps its columns too = 2 " + str(cell(o, "A1")))
check(len(fxc) == (2 if OT else 1) and all(f.get("raw") and f.get("now") for f in fxc), "both changed formulas named " + str(fxc))
r = order(Fr, CS, "columns", C, prev=newc, formulas=fxc)
d = get(Fr, CS)
check(r.ok and cols(d) == C and cell(d, "A2").get("raw") == "=SUM(A1:B1)" and cell(d, "A2").get("value") == 3, "columns: the Undo as before " + str(cell(d, "A2")))
if OT:
    o = cell(get(Fr, OT), "A1")
    check("!A1:B1" in (o.get("raw") or "") and o.get("value") == 3, "the other sheet's formula as before " + str(o))
check(order(Fr, CS, "columns", newc, prev=newc, moved=[C[0]]).status_code == 409, "columns/order: a stale prev gives 409")
check(order(Fr, CS, "columns", [C[0], C[0]]).status_code == 400, "columns/order: ids twice: 400")
# another person (alice, not in frida's workspace) cannot move frida's columns: 404, nothing changed
r = A.post(B + f"/api/sheets/{CS}/columns/order", json={"ids": newc, "prev": C, "moved": [C[0]]})
check(r.status_code in (403, 404) and cols(get(Fr, CS)) == C, "another person's table: columns/order refused " + str(r.status_code))

# ---- only reading: no move
AS = new_sheet(A, "Shared to read", [("A1", "1"), ("A2", "2")])
check(A.post(B + f"/api/sheets/{AS}/shares", json={"user_id": BOB, "role": "read"}).status_code == 201, "shared with bob to read")
bd = get(Bo, AS)
check(bd.get("can_write") is False, "bob reads only " + str(bd.get("can_write")))
BR, BC = rows(bd), cols(bd)
check(order(Bo, AS, "rows", BR[::-1], prev=BR, moved=[BR[0]]).status_code == 403, "a reader cannot move rows (403)")
check(order(Bo, AS, "columns", BC[::-1], prev=BC, moved=[BC[0]]).status_code == 403, "a reader cannot move columns (403)")
check(rows(get(A, AS)) == BR, "the order is unchanged")

print(f"p2631_b_sheet_move: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
