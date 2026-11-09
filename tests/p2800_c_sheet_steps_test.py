#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.800.0 (#5409): undo across devices, stage 5 rest -- a person's other table changes as steps of "Recent steps"
(kalmido/sheets/shustep.py, kinds of the person's batch). Invented names only. Each change is seen in the list (area sheets,
the table named), taken back (the table shows the old state again: GET /api/sheets/<id>), forward again (redo):
 - a row / a column deleted, a column renamed, rows sorted, the chart, a cell's name and frozen value, the rows kept in view,
   a sheet of the bar added / renamed / deleted, the table's own title (the core's copy step of the tracked kind "sheet")
 - a conflict: a column whose title someone else changed since keeps that title (named), its width of the same step goes back
   (the group partial)
 - another account neither sees nor takes the step (404)
tenant-matrix: undo (another account's table step: not listed, 404)
freelancer-matrix: undo (a person without an organisation: her row delete taken back)
usage: p2800_c_sheet_steps_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402

fresh(prefix="P2800C")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
uid["bob"] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
Bo, Ol = sess("bob"), sess("olga")
for s in (A, Bo, Ol):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
BOB = uid["bob"]
FID, Fr = freelancer(B, A)


def last_group(u):
    r = dbx("SELECT id FROM undo_groups WHERE user_id=? ORDER BY id DESC LIMIT 1", (u,))
    return r[0][0] if r else None


def state(gid):
    r = dbx("SELECT state FROM undo_groups WHERE id=?", (gid,))
    return r[0][0] if r else None


def sheet(s, sid):
    r = s.get(B + f"/api/sheets/{sid}")
    assert r.ok, r.text[:300]
    return r.json()


def step(s, u, what, fn):
    """fn() makes the change; -> its group (a new one, listed in the person's Recent steps under the tables)."""
    g0 = last_group(u)
    fn()
    g = last_group(u)
    check(g is not None and g != g0, f"{what}: a step of its own")
    it = [x for x in s.get(B + "/api/undo").json()["items"] if x["id"] == g]
    check(bool(it) and it[0]["area"] == "sheets" and it[0]["undo"] is True, f"{what}: listed in Recent steps (area sheets) {it}")
    return g


def back(s, g, what):
    r = s.post(B + f"/api/undo/to/{g}")
    check(r.ok and g in r.json().get("undone", []) and not r.json().get("stayed"), f"{what}: taken back {r.status_code} {r.text[:300]}")
    return r


def fwd(s, g, what):
    r = s.post(B + f"/api/undo/{g}/redo")
    check(r.ok and r.json().get("redone") and state(g) == "done", f"{what}: forward again {r.status_code} {r.text[:300]}")


def ok(r):
    assert r.ok, r.text[:300]
    return r


r = ok(Bo.post(B + "/api/sheets", json={"title": "Budget plan", "space": SP}))
SID = r.json()["id"]
j = sheet(Bo, SID)
COLS, ROWS = [c["id"] for c in j["columns"]], [x["id"] for x in j["rows"]]
C1, C2, C3 = COLS[:3]
ok(Bo.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"row_id": ROWS[0], "col_id": C1, "raw": "b"}, {"row_id": ROWS[1], "col_id": C1, "raw": "a"},
                                                         {"row_id": ROWS[0], "col_id": C2, "raw": "5"}]}))
CELL = next(x["id"] for x in sheet(Bo, SID)["cells"] if x["row_id"] == ROWS[0] and x["col_id"] == C2)

# ---------------------------------------------------------------- a row deleted
G = step(Bo, BOB, "row deleted", lambda: ok(Bo.delete(B + f"/api/sheets/{SID}/rows/{ROWS[2]}")))
check(ROWS[2] not in [x["id"] for x in sheet(Bo, SID)["rows"]], "the row is gone from the table")
back(Bo, G, "row deleted")
check(ROWS[2] in [x["id"] for x in sheet(Bo, SID)["rows"]], "undo: the table shows the row again")
fwd(Bo, G, "row deleted")
check(ROWS[2] not in [x["id"] for x in sheet(Bo, SID)["rows"]], "redo: the row is gone again")
# another account: neither listed nor taken
check(not any(x["id"] == G for x in Ol.get(B + "/api/undo").json()["items"]) and Ol.post(B + f"/api/undo/to/{G}").status_code == 404
      and ROWS[2] not in [x["id"] for x in sheet(Bo, SID)["rows"]], "another account: not listed, 404, nothing went back")

# ---------------------------------------------------------------- a column renamed, a column deleted
G = step(Bo, BOB, "column renamed", lambda: ok(Bo.patch(B + f"/api/sheets/{SID}/columns/{C1}", json={"title": "Item", "_prev": {"title": ""}})))
back(Bo, G, "column renamed")
check(next(c for c in sheet(Bo, SID)["columns"] if c["id"] == C1)["title"] == "", "undo: the column has its old title")
fwd(Bo, G, "column renamed")
check(next(c for c in sheet(Bo, SID)["columns"] if c["id"] == C1)["title"] == "Item", "redo: the new title again")
G = step(Bo, BOB, "column deleted", lambda: ok(Bo.delete(B + f"/api/sheets/{SID}/columns/{C3}")))
back(Bo, G, "column deleted")
check(C3 in [c["id"] for c in sheet(Bo, SID)["columns"]], "undo: the column is back in the table")
fwd(Bo, G, "column deleted")
check(C3 not in [c["id"] for c in sheet(Bo, SID)["columns"]], "redo: the column is gone again")

# ---- conflict: the title changed by someone else since stays (named), the width of the same step goes back
G = step(Bo, BOB, "column title + width", lambda: ok(Bo.patch(B + f"/api/sheets/{SID}/columns/{C2}", json={"title": "Amount", "width": 300})))
ok(A.patch(B + f"/api/sheets/{SID}/columns/{C2}", json={"title": "Alice's amount"}))
r = Bo.post(B + f"/api/undo/to/{G}")
st = r.json().get("stayed", []) if r.ok else []
col = next(c for c in sheet(Bo, SID)["columns"] if c["id"] == C2)
check(r.ok and G in r.json().get("partial", []) and st and st[0]["code"] == "conflict" and "Column" in st[0]["reason"],
      f"conflict named, the group partial {r.status_code} {r.text[:300]}")
check(col["title"] == "Alice's amount" and col.get("width") in (None, 0), f"the other title stays, the width went back {col}")

# ---------------------------------------------------------------- rows sorted
live = [x["id"] for x in sheet(Bo, SID)["rows"]]
new = [live[1], live[0]] + live[2:]
G = step(Bo, BOB, "rows sorted", lambda: ok(Bo.post(B + f"/api/sheets/{SID}/rows/order", json={"ids": new, "prev": live})))
back(Bo, G, "rows sorted")
check([x["id"] for x in sheet(Bo, SID)["rows"]] == live, "undo: the rows in their old order")
fwd(Bo, G, "rows sorted")
check([x["id"] for x in sheet(Bo, SID)["rows"]] == new, "redo: the sorted order again")

# ---------------------------------------------------------------- the chart, a cell's name and frozen value, rows kept in view
G = step(Bo, BOB, "chart", lambda: ok(Bo.put(B + f"/api/sheets/{SID}/chart", json={"chart": {"type": "bar", "x": C1, "y": [C2]}})))
back(Bo, G, "chart")
check(sheet(Bo, SID)["chart"] is None, "undo: no chart")
fwd(Bo, G, "chart")
check((sheet(Bo, SID)["chart"] or {}).get("type") == "bar", "redo: the chart again")
G = step(Bo, BOB, "cell name", lambda: ok(Bo.post(B + f"/api/sheets/{SID}/cells/{CELL}/name", json={"name": "total_cost"})))
back(Bo, G, "cell name")
check("total_cost" not in sheet(Bo, SID)["names"], "undo: the name is gone")
fwd(Bo, G, "cell name")
check(sheet(Bo, SID)["names"].get("total_cost") == CELL, "redo: the name again")
G = step(Bo, BOB, "value frozen", lambda: ok(Bo.post(B + f"/api/sheets/{SID}/cells/{CELL}/freeze", json={"frozen": True})))
back(Bo, G, "value frozen")
check(not next(x for x in sheet(Bo, SID)["cells"] if x["id"] == CELL).get("frozen"), "undo: the cell is live again")
fwd(Bo, G, "value frozen")
check(next(x for x in sheet(Bo, SID)["cells"] if x["id"] == CELL).get("frozen"), "redo: frozen again")
G = step(Bo, BOB, "rows kept in view", lambda: ok(Bo.post(B + f"/api/sheets/{SID}/fixed", json={"rows": 1})))
back(Bo, G, "rows kept in view")
check(sheet(Bo, SID)["freeze_rows"] == 0, "undo: no row kept in view")

# ---------------------------------------------------------------- the sheets of the bar
G = step(Bo, BOB, "sheet added", lambda: ok(Bo.post(B + f"/api/sheets/{SID}/tabs", json={"name": "Costs"})))
TID = next(t["id"] for t in Bo.get(B + f"/api/sheets/{SID}/tabs").json()["tabs"] if t["name"] == "Costs")
back(Bo, G, "sheet added")
check(TID not in [t["id"] for t in Bo.get(B + f"/api/sheets/{SID}/tabs").json()["tabs"]], "undo: the new sheet is gone from the bar")
fwd(Bo, G, "sheet added")
check(TID in [t["id"] for t in Bo.get(B + f"/api/sheets/{SID}/tabs").json()["tabs"]], "redo: the sheet is back in the bar")
G = step(Bo, BOB, "sheet renamed", lambda: ok(Bo.patch(B + f"/api/sheets/{SID}/tabs/{TID}", json={"name": "Expenses"})))
back(Bo, G, "sheet renamed")
check(any(t["id"] == TID and t["name"] == "Costs" for t in Bo.get(B + f"/api/sheets/{SID}/tabs").json()["tabs"]), "undo: the old name of the sheet")
G = step(Bo, BOB, "sheet deleted", lambda: ok(Bo.delete(B + f"/api/sheets/{SID}/tabs/{TID}")))
back(Bo, G, "sheet deleted")
check(TID in [t["id"] for t in Bo.get(B + f"/api/sheets/{SID}/tabs").json()["tabs"]], "undo: the deleted sheet is back")

# ---------------------------------------------------------------- the table's own title (the core's copy step)
G = step(Bo, BOB, "table renamed", lambda: ok(Bo.patch(B + f"/api/sheets/{SID}", json={"title": "Budget 2027"})))
it = next(x for x in Bo.get(B + "/api/undo").json()["items"] if x["id"] == G)
check(it["kind"] == "sheet" and it["ref_id"] == SID, f"the step names the table {it}")
ok(A.put(B + f"/api/sheets/{SID}/chart", json={"chart": None}))  # someone else changed the table since: not its title
back(Bo, G, "table renamed")
j = sheet(Bo, SID)
check(j["title"] == "Budget plan" and j["chart"] is None, f"undo: the old title, the chart as it is now {j['title']!r} {j['chart']}")
fwd(Bo, G, "table renamed")
check(sheet(Bo, SID)["title"] == "Budget 2027", "redo: the new title again")

# ---------------------------------------------------------------- a person without an organisation
r = ok(Fr.post(B + "/api/sheets", json={"title": "Frida's sheet", "space": "private"}))
FS = r.json()["id"]
FR = [x["id"] for x in sheet(Fr, FS)["rows"]]
G = step(Fr, FID, "freelancer: row deleted", lambda: ok(Fr.delete(B + f"/api/sheets/{FS}/rows/{FR[0]}")))
check(Ol.post(B + f"/api/undo/to/{G}").status_code == 404, "someone else: 404 on her step")
back(Fr, G, "freelancer: row deleted")
check(FR[0] in [x["id"] for x in sheet(Fr, FS)["rows"]], "freelancer: her row is back")

sys.exit(done("p2800_c_sheet_steps"))
