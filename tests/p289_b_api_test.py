#!/usr/bin/env python3
"""2.89.0 API tests, part B (#1916): the routes the tables view (static/js/sheets.js) relies on. Invented names only.
 - a person without an organisation (dave, P4) creates a private table: 3 columns A-C, 10 rows, may write; the overview
   (space=all) lists it for him only, the others get 404 on it
 - columns: a selection column with options (ids o1.., colours of the app palette) and "colour for the whole row"; a colour
   that is no hex colour is refused (400); width and title stay; delete + restore (the UI's undo)
 - cells: a number, a formula shown with addresses (=A1*2), the selection cell answers option id + label as value / display;
   sorting rows (rows/order) keeps the formula pointing at its cell (shown with the new address)
 - a cell name: set, used by the suggestions (vars), a second cell with the same name 400, removed again
 - freeze / live again, presence of another member in an organisation's table, renaming, the trash + restore
 - a table attached to a list: listed with ?list_id=, a reader of the list reads but may not write
usage: p289_b_api_test.py <datadir>      (a fresh container; P289B_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "collab,comments,sheets"


if not os.environ.get("P289B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "dave" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT})


def sheet(s, sid):
    r = s.get(B + f"/api/sheets/{sid}")
    return r.json() if r.ok else None


def cell(sh, addr):
    return next((c for c in sh["cells"] if c["addr"] == addr), None)


# ---- a private table of a person without an organisation (P4)
# freelancer-matrix: sheets
r = Da.post(B + "/api/sheets", json={"title": "Equipment", "space": "private"})
check(r.ok, "dave (no organisation) creates a private table " + r.text[:200])
S = r.json()
SID = S["id"]
check([c["letter"] for c in S["columns"]] == ["A", "B", "C"] and len(S["rows"]) == 10 and S["can_write"] and S["space"] == "private",
      "a new table: 3 columns A-C, 10 rows, writable, private " + str({k: S.get(k) for k in ("space", "can_write")}))
check(any(x["id"] == SID for x in Da.get(B + "/api/sheets?space=all").json()["sheets"]), "the overview lists it for dave")
check(not any(x["id"] == SID for x in A.get(B + "/api/sheets?space=all").json()["sheets"]), "not in alice's overview")
check(A.get(B + f"/api/sheets/{SID}").status_code == 404 and Bo.get(B + f"/api/sheets/{SID}").status_code == 404, "others: 404")
check(Bo.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"row_id": S["rows"][0]["id"], "col_id": S["columns"][0]["id"], "raw": "1"}]}).status_code == 404,
      "others cannot write into it (404)")

# ---- columns: a selection with colours for the whole row
CA_, CB_, CC_ = (c["id"] for c in S["columns"])
R = [x["id"] for x in S["rows"]]
r = Da.patch(B + f"/api/sheets/{SID}/columns/{CC_}", json={"title": "Status", "kind": "select", "color_mode": "row", "width": 200,
                                                            "options": [{"id": "o1", "label": "Open", "color": "#f5b041"}, {"id": "o2", "label": "Packed", "color": "#4ade80"}]})
check(r.ok, "the column becomes a selection with two coloured options " + r.text[:200])
col = next(c for c in sheet(Da, SID)["columns"] if c["id"] == CC_)
check(col["kind"] == "select" and col["color_mode"] == "row" and [o["color"] for o in col["options"]] == ["#f5b041", "#4ade80"] and col["title"] == "Status"
      and int(col["width"]) == 200, "options, row colour, title and width are stored " + str(col))
r = Da.patch(B + f"/api/sheets/{SID}/columns/{CC_}", json={"options": [{"id": "o1", "label": "Open", "color": "red;background:url(x)"}]})
check(r.status_code == 400, f"a colour that is no hex colour: 400 ({r.status_code})")
check(next(c for c in sheet(Da, SID)["columns"] if c["id"] == CC_)["options"][0]["color"] == "#f5b041", "the refused colour changed nothing")

# ---- cells
r = Da.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"row_id": R[0], "col_id": CA_, "raw": "21"}, {"row_id": R[1], "col_id": CA_, "raw": "4"},
                                                           {"row_id": R[0], "col_id": CB_, "raw": "=A1*2"}, {"row_id": R[0], "col_id": CC_, "raw": "o2"}]})
check(r.ok and "rev" in r.json(), "cells saved, the answer carries rev " + r.text[:200])
sh = sheet(Da, SID)
b1, c1 = cell(sh, "B1"), cell(sh, "C1")
check(b1 and b1["value"] == 42 and b1["raw"] == "=A1*2" and b1["origin"] == "formula" and b1["error"] is None, "a formula: value 42, shown =A1*2, origin formula " + str(b1))
check(cell(sh, "A1")["origin"] == "own" and cell(sh, "A1")["id"] in b1["refs"], "the number is own, the formula reads it (refs)")
check(c1 and c1.get("option") == "o2" and c1["value"] == "Packed" and c1["display"] == "Packed", "the selection cell: option id, label as value and display " + str(c1))
# sorting: A2 (4) first; the formula follows its cell (now A2)
r = Da.post(B + f"/api/sheets/{SID}/rows/order", json={"ids": [R[1], R[0]] + R[2:]})
check(r.ok, "rows sorted " + r.text[:200])
sh = sheet(Da, SID)
b = next(c for c in sh["cells"] if c["row_id"] == R[0] and c["col_id"] == CB_)
check(b["addr"] == "B2" and b["raw"] == "=A2*2" and b["value"] == 42, "after sorting the formula shows the new address " + str({k: b[k] for k in ("addr", "raw", "value")}))
Da.post(B + f"/api/sheets/{SID}/rows/order", json={"ids": R})
# a cell name
a1 = cell(sheet(Da, SID), "A1")
r = Da.post(B + f"/api/sheets/{SID}/cells/{a1['id']}/name", json={"name": "day_rate"})
check(r.ok and sheet(Da, SID)["names"].get("day_rate") == a1["id"], "a cell gets a name " + r.text[:200])
v = Da.get(B + f"/api/sheets/{SID}/vars?q=day").json()["vars"]
check(any(x["token"] == "day_rate" and x["kind"] == "cell" for x in v), "the suggestions offer the name " + str(v[:3]))
a2 = cell(sheet(Da, SID), "A2")
check(Da.post(B + f"/api/sheets/{SID}/cells/{a2['id']}/name", json={"name": "day_rate"}).status_code == 400, "the same name twice: 400")
check(Da.post(B + f"/api/sheets/{SID}/cells/{a1['id']}/name", json={"name": ""}).ok and "day_rate" not in sheet(Da, SID)["names"], "the name removed again")
# freeze / live again
r = Da.post(B + f"/api/sheets/{SID}/cells/{b1['id']}/freeze", json={"frozen": True})
check(r.ok and cell(sheet(Da, SID), "B1")["frozen"] in (1, True), "freeze a formula " + r.text[:200])
Da.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"row_id": R[0], "col_id": CA_, "raw": "50"}]})
check(cell(sheet(Da, SID), "B1")["value"] == 42, "a frozen value stays when its source changes")
check(Da.post(B + f"/api/sheets/{SID}/cells/{b1['id']}/freeze", json={"frozen": False}).ok and cell(sheet(Da, SID), "B1")["value"] == 100, "live again: 100")
# emptying a cell
Da.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"row_id": R[1], "col_id": CA_, "raw": ""}]})
check(cell(sheet(Da, SID), "A2") is None or (cell(sheet(Da, SID), "A2")["raw"] or "") == "", "an empty raw empties the cell")
# a column deleted and restored (the UI's undo)
check(Da.delete(B + f"/api/sheets/{SID}/columns/{CA_}").ok, "column A deleted")
sh = sheet(Da, SID)
check(CA_ not in [c["id"] for c in sh["columns"]] and (cell(sh, "A1") is None or cell(sh, "A1")["col_id"] != CA_), "a deleted column is not in GET")
bb = next(c for c in sh["cells"] if c["row_id"] == R[0] and c["col_id"] == CB_)
check(bb["error"] == "ref", "the formula on it shows the ref error " + str(bb.get("error")))
check(Da.post(B + f"/api/sheets/{SID}/columns/{CA_}/restore").ok and cell(sheet(Da, SID), "B1")["value"] == 100, "restored: the formula works again")
# rows: added after a row, deleted, restored
before = {x["id"] for x in sheet(Da, SID)["rows"]}
check(Da.post(B + f"/api/sheets/{SID}/rows", json={"after_row_id": R[0], "count": 2}).ok, "two rows added")
new = [x["id"] for x in sheet(Da, SID)["rows"] if x["id"] not in before]
check(len(new) == 2 and [x["id"] for x in sheet(Da, SID)["rows"]][1:3] == new, "the new rows sit right after row 1 " + str(new))
check(Da.delete(B + f"/api/sheets/{SID}/rows/{new[0]}").ok and new[0] not in [x["id"] for x in sheet(Da, SID)["rows"]], "a row deleted")
check(Da.post(B + f"/api/sheets/{SID}/rows/{new[0]}/restore").ok and new[0] in [x["id"] for x in sheet(Da, SID)["rows"]], "and restored")
# rename, trash, restore
check(Da.patch(B + f"/api/sheets/{SID}", json={"title": "Kit list"}).ok and sheet(Da, SID)["title"] == "Kit list", "renamed")
check(Da.delete(B + f"/api/sheets/{SID}").ok and not any(x["id"] == SID for x in Da.get(B + "/api/sheets?space=all").json()["sheets"]), "to the trash: gone from the overview")
check(Da.post(B + f"/api/sheets/{SID}/restore").ok and sheet(Da, SID) is not None, "restored from the trash")

# ---- an organisation's table: presence of another member
r = A.post(B + "/api/sheets", json={"title": "Quote", "space": f"org:{ORG}"})
check(r.ok, "alice creates a table of the organisation " + r.text[:200])
OS = r.json()
Bo.put(B + f"/api/sheets/{OS['id']}/cells", json={"cells": [{"row_id": OS["rows"][0]["id"], "col_id": OS["columns"][0]["id"], "raw": "8"}]})
oc = cell(sheet(A, OS["id"]), "A1")
check(oc and oc["value"] == 8 and oc["updated_by_name"] == "Bob", "a member writes into it, the cell says who " + str(oc and oc.get("updated_by_name")))
check(Bo.post(B + f"/api/sheets/{OS['id']}/presence", json={"cell_id": oc["id"]}).ok, "bob reports he edits A1")
pr = sheet(A, OS["id"])["presence"]
check(any(p["user_id"] == uid["bob"] and p["cell_id"] == oc["id"] and p["name"] for p in pr), "alice sees bob editing A1 " + str(pr))
check(Da.get(B + f"/api/sheets/{OS['id']}").status_code == 404 and Da.post(B + f"/api/sheets/{OS['id']}/presence", json={"cell_id": None}).status_code == 404,
      "a person outside the organisation: 404, also for presence")

# ---- attached to a list: a reader of the list reads, may not write
L = A.post(B + "/api/lists", json={"name": "Shoot Berlin", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["bob"], "role": "view"})
r = A.post(B + "/api/sheets", json={"title": "Budget", "space": f"org:{ORG}", "list_id": L})
check(r.ok and r.json()["list_id"] == L, "a table attached to a list " + r.text[:200])
LS_ = r.json()
check([x["id"] for x in A.get(B + f"/api/sheets?list_id={L}").json()["sheets"]] == [LS_["id"]], "listed with ?list_id=")
bs = sheet(Bo, LS_["id"])
check(bs is not None and bs["can_write"] is False, "a reader of the list reads it, can_write false")
check(Bo.put(B + f"/api/sheets/{LS_['id']}/cells", json={"cells": [{"row_id": LS_["rows"][0]["id"], "col_id": LS_["columns"][0]["id"], "raw": "1"}]}).status_code == 403,
      "a reader may not write (403)")
check(Ca.get(B + f"/api/sheets/{LS_['id']}").status_code in (403, 404), "an org member who does not see the list: no access")
check(Da.post(B + "/api/sheets", json={"title": "x", "space": f"org:{ORG}"}).status_code in (403, 404), "dave may not create in a foreign organisation")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
