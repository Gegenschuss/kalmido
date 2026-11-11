#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.884.0 (#5479): the table steps of "Recent steps" (kalmido/sheets/shustep.py) after the review of #5409. Invented names only.
 - a row / a column / a sheet deleted, taken back and deleted again (redo): its time in the trash is the time of the redo, not
   the one of the first delete (the trash purge would take it at once), and a further undo still brings it back
 - a deleted sheet comes back (undo) only while the table has fewer sheets than the limit, as POST .../tabs/<id>/restore
 - a further sheet's own title (the core's copy step) goes back after someone else hung the table on another project
freelancer-matrix: undo (a person without an organisation: her row deleted again with the time of the redo)
usage: p2884_c_sheet_steps_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402

fresh(prefix="P2884C")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
BOB = r.json().get("id")
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
FID, Fr = freelancer(B, A)
SHB_TABS_MAX = 30  # kalmido/sheets/shbook.py


def ok(r):
    assert r.ok, r.text[:300]
    return r


def last_group(u):
    r = dbx("SELECT id FROM undo_groups WHERE user_id=? ORDER BY id DESC LIMIT 1", (u,))
    return r[0][0] if r else None


def step(u, fn):
    g0 = last_group(u)
    fn()
    g = last_group(u)
    check(g is not None and g != g0, "a step of its own")
    return g


def back(s, g, what):
    r = s.post(B + f"/api/undo/to/{g}")
    check(r.ok and g in r.json().get("undone", []) and not r.json().get("stayed"), f"{what}: taken back {r.status_code} {r.text[:300]}")


def fwd(s, g, what):
    r = s.post(B + f"/api/undo/{g}/redo")
    check(r.ok and r.json().get("redone"), f"{what}: forward again {r.status_code} {r.text[:300]}")


def when(table, xid):
    return dbx(f"SELECT deleted_at FROM {table} WHERE id=?", (xid,))[0][0]


def tabs(s, sid):
    return [t["id"] for t in s.get(B + f"/api/sheets/{sid}/tabs").json()["tabs"]]


def again(s, u, sid, table, xid, path, live, what):
    """Delete, undo, redo: the redo's time in the trash is newer than the first; a further undo still finds it."""
    g = step(u, lambda: ok(s.delete(B + f"/api/sheets/{sid}/{path}/{xid}")))
    t0 = when(table, xid)
    back(s, g, what)
    check(when(table, xid) is None, f"{what}: back in the table")
    fwd(s, g, what)
    t1 = when(table, xid)
    check(t1 is not None and t0 is not None and str(t1) > str(t0), f"{what}: deleted again with the time of the redo {t0} -> {t1}")
    back(s, g, what + " (again)")
    check(xid in live(), f"{what}: a further undo brings it back")


SID = ok(Bo.post(B + "/api/sheets", json={"title": "Budget plan", "space": SP})).json()["id"]
j = Bo.get(B + f"/api/sheets/{SID}").json()
ROWS, COLS = [x["id"] for x in j["rows"]], [c["id"] for c in j["columns"]]
again(Bo, BOB, SID, "sheet_rows", ROWS[1], "rows", lambda: [x["id"] for x in Bo.get(B + f"/api/sheets/{SID}").json()["rows"]], "row")
again(Bo, BOB, SID, "sheet_columns", COLS[1], "columns", lambda: [x["id"] for x in Bo.get(B + f"/api/sheets/{SID}").json()["columns"]], "column")
ok(Bo.post(B + f"/api/sheets/{SID}/tabs", json={"name": "Costs"}))
TID = next(t["id"] for t in Bo.get(B + f"/api/sheets/{SID}/tabs").json()["tabs"] if t["name"] == "Costs")
again(Bo, BOB, SID, "sheets", TID, "tabs", lambda: tabs(Bo, SID), "sheet")

# ---------------------------------------------------------------- a deleted sheet back only below the limit
G = step(BOB, lambda: ok(Bo.delete(B + f"/api/sheets/{SID}/tabs/{TID}")))
k = 0
while len(tabs(Bo, SID)) < SHB_TABS_MAX:  # someone else fills the table (Bob's "back to here" takes only his own steps)
    k += 1
    ok(A.post(B + f"/api/sheets/{SID}/tabs", json={"name": f"Month {k}"}))
r = Bo.post(B + f"/api/undo/to/{G}")
check(r.ok and r.json().get("stayed") and G not in r.json().get("undone", []), f"at the limit: the step stays, named {r.status_code} {r.text[:300]}")
check(len(tabs(Bo, SID)) == SHB_TABS_MAX and TID not in tabs(Bo, SID), f"at the limit: no sheet over it {len(tabs(Bo, SID))}")
LAST = tabs(Bo, SID)[-1]
ok(A.delete(B + f"/api/sheets/{SID}/tabs/{LAST}"))
back(Bo, G, "below the limit")
check(TID in tabs(Bo, SID) and len(tabs(Bo, SID)) == SHB_TABS_MAX, "below the limit: the sheet is back")

# ---------------------------------------------------------------- a further sheet's title back after a change of project
L1 = ok(A.post(B + "/api/lists", json={"name": "Project one", "org_id": ORG})).json()["id"]
L2 = ok(A.post(B + "/api/lists", json={"name": "Project two", "org_id": ORG})).json()["id"]
for L in (L1, L2):
    ok(A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}))
S2 = ok(Bo.post(B + "/api/sheets", json={"title": "Moving plan", "space": SP, "list_id": L1})).json()["id"]
ok(Bo.post(B + f"/api/sheets/{S2}/tabs", json={"name": "North"}))
T2 = next(t["id"] for t in Bo.get(B + f"/api/sheets/{S2}/tabs").json()["tabs"] if t["name"] == "North")
G = step(BOB, lambda: ok(Bo.patch(B + f"/api/sheets/{T2}", json={"title": "South"})))
ok(A.patch(B + f"/api/sheets/{S2}", json={"list_id": L2}))  # someone else hangs the table on another project
check(dbx("SELECT list_id FROM sheets WHERE id=?", (T2,))[0][0] == L2, "the further sheet follows the project")
back(Bo, G, "sheet title after a change of project")
check(any(t["id"] == T2 and t["name"] == "North" for t in Bo.get(B + f"/api/sheets/{S2}/tabs").json()["tabs"]), "undo: the old name of the sheet")
check(dbx("SELECT list_id FROM sheets WHERE id=?", (T2,))[0][0] == L2 and Bo.get(B + f"/api/sheets/{S2}").json()["list_id"] == L2,
      "the table and its sheet stay on the new project")
fwd(Bo, G, "sheet title after a change of project")
check(any(t["id"] == T2 and t["name"] == "South" for t in Bo.get(B + f"/api/sheets/{S2}/tabs").json()["tabs"]), "redo: the new name again")

# ---------------------------------------------------------------- a person without an organisation
FS = ok(Fr.post(B + "/api/sheets", json={"title": "Frida's sheet", "space": "private"})).json()["id"]
FR = [x["id"] for x in Fr.get(B + f"/api/sheets/{FS}").json()["rows"]]
again(Fr, FID, FS, "sheet_rows", FR[0], "rows", lambda: [x["id"] for x in Fr.get(B + f"/api/sheets/{FS}").json()["rows"]], "freelancer: row")

sys.exit(done("p2884_c_sheet_steps"))
