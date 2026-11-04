#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.528.0 C (#4306 #4305): tables -- no silent data loss. Invented names only. tenant-matrix: sheet
freelancer-matrix: sheets
 (B24) an agent's Undo leaves rows / columns / a table a person typed values into since: only the agent's own cells go back,
       the answer names what stayed (kept); untouched agent rows still go to the trash
 (A12) row order and column settings under the sheet's lock with the state the writer saw: a sorting with prev (the order
       this device saw) after a sorting elsewhere gives 409 with the current order; rows added since do not count, a row of
       prev deleted since does; a column field with _prev that changed elsewhere stays (conflicts); without prev / _prev as before
 (B22) the trash of tables: the tables of a workspace in the trash (restore, for good one by one, empty -- an organisation's
       whole trash only its admins), a table's rows / columns in the trash with a few of their inputs (restore); another
       organisation's / person's trash: 404 or nothing
 (B25) a move between workspaces whose file cannot be copied (sealed) stops as a whole: 409, the table / page stays where it
       was with its file as before, no new stored file; with the file intact the same move goes through
The Undo cases as a person without an organisation (frida) with her own personal agent; a move needs an organisation (alice).
usage: p2528_c_sheets_test.py <datadir>"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check  # noqa: E402

V = B + "/api/v1"
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2528C")
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,wiki,sheets,files", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
FID, Fr = freelancer(B, A)
MAGIC = b"KENC1\n"  # core/orgcrypt.py: a stored file that looks sealed but is cut short cannot be opened


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "sheets:read", "sheets:write"], "username": "fridabot",
                                          "display_name": "Fridabot", "owner_id": FID})
assert r.status_code == 201, r.text
ag = bearer(r.json()["token"])


def sheet(sid, s=None):
    return (s or Fr).get(B + f"/api/sheets/{sid}")


def at(d):
    """{(row_id, col_id): raw} of the live cells with content."""
    return {(x["row_id"], x["col_id"]): x["raw"] for x in d["cells"]}


def undo(sid, batch):
    r = Fr.post(B + f"/api/sheets/{sid}/batches/{batch}/undo")
    check(r.ok, f"undo {batch}: {r.status_code} {r.text[:200]}")
    return r.json() if r.ok else {}


# ================================================================== (B24) the agent's Undo keeps people's input
r = ag.post(V + "/sheets", json={"title": "Guests", "columns": [{"title": "Name"}, {"title": "Note"}], "rows": [["Ann", ""], ["Ben", ""]]})
check(r.status_code == 201, "the agent creates a table " + r.text[:200])
S1, b0 = r.json()["id"], r.json()["batch"]
d = sheet(S1).json()
R1, R2 = d["rows"][0]["id"], d["rows"][1]["id"]
CN, CX = d["columns"][0]["id"], d["columns"][1]["id"]
check(Fr.put(B + f"/api/sheets/{S1}/cells", json={"cells": [{"row_id": R1, "col_id": CX, "raw": "brings cake"}]}).ok, "frida types a note")
k = undo(S1, b0).get("kept") or {}
d = sheet(S1)
check(d.ok and k.get("sheet") is True, "the agent's table stays because frida typed into it " + str(k) + " " + str(d.status_code))
if d.ok:
    d = d.json()
    rows = [x["id"] for x in d["rows"]]
    check(at(d).get((R1, CX)) == "brings cake", "frida's note is still there " + str(at(d)))
    check((R1, CN) not in at(d), "the agent's own cell of that row is taken back " + str(at(d)))
    check(R1 in rows and R2 not in rows, "the agent's row nobody typed into went to the trash " + str(rows))

# appended rows: the one with a person's input stays, the other goes
r = ag.post(V + "/sheets", json={"title": "Orders", "columns": [{"title": "Item"}, {"title": "Qty"}], "rows": [["Tea", "1"]]})
S2 = r.json()["id"]  # the agent's own table (a personal agent sees only those and shared ones)
d = sheet(S2).json()
CI, CQ = d["columns"][0]["id"], d["columns"][1]["id"]
r = ag.post(V + f"/sheets/{S2}/rows", json={"rows": [["Cake", "2"], ["Milk", "3"]]})
check(r.status_code == 201, "the agent appends two rows " + r.text[:200])
b1, (R3, R4) = r.json()["batch"], r.json()["row_ids"]
check(Fr.put(B + f"/api/sheets/{S2}/cells", json={"cells": [{"row_id": R3, "col_id": CQ, "raw": "5"}]}).ok, "frida corrects a quantity")
k = undo(S2, b1).get("kept") or {}
d = sheet(S2).json()
rows = [x["id"] for x in d["rows"]]
check(k.get("rows") == [R3] and not k.get("sheet"), "the answer names the row that stayed " + str(k))
check(R3 in rows and R4 not in rows, "the row with frida's input stays, the untouched one is in the trash " + str(rows))
check(at(d).get((R3, CQ)) == "5" and (R3, CI) not in at(d), "frida's value stays, the agent's cell of that row is taken back " + str(at(d)))

# an added column frida typed into stays
r = ag.post(V + f"/sheets/{S2}/columns", json={"title": "Price"})
check(r.status_code == 201, "the agent adds a column " + r.text[:200])
b2, CP = r.json()["batch"], r.json()["col_id"]
check(Fr.put(B + f"/api/sheets/{S2}/cells", json={"cells": [{"row_id": R3, "col_id": CP, "raw": "4.50"}]}).ok, "frida fills a price")
r = ag.post(V + f"/sheets/{S2}/batches/{b2}/undo")
check(r.ok and (r.json().get("kept") or {}).get("cols") == [CP], "the agent's own undo (v1) names the column that stayed " + r.text[:200])
check(CP in [x["id"] for x in sheet(S2).json()["columns"]], "the column with frida's price stays")
# ... and a column nobody typed into still goes
r = ag.post(V + f"/sheets/{S2}/columns", json={"title": "Spare"})
b3, CS = r.json()["batch"], r.json()["col_id"]
r = ag.post(V + f"/sheets/{S2}/batches/{b3}/undo")
check(r.ok and not (r.json().get("kept") or {}).get("cols"), "an untouched column: nothing kept " + r.text[:200])
check(CS not in [x["id"] for x in sheet(S2).json()["columns"]], "... it is in the trash")
# a table the agent created and nobody typed into: still to the trash
r = ag.post(V + "/sheets", json={"title": "Scratch", "rows": [["x"]]})
S3, b4 = r.json()["id"], r.json()["batch"]
k = undo(S3, b4).get("kept")
check(sheet(S3).status_code == 404 and not (k or {}).get("sheet"), "an untouched agent table goes to the trash " + str(k))

# ================================================================== (A12) row order and columns: two devices
S4 = Fr.post(B + "/api/sheets", json={"title": "Plan", "space": "private"}).json()["id"]
d = sheet(S4).json()
L0 = [x["id"] for x in d["rows"]]
C0 = d["columns"][0]
order = lambda b: Fr.post(B + f"/api/sheets/{S4}/rows/order", json=b)
r = order({"ids": L0[::-1], "prev": L0})
check(r.ok and [x["id"] for x in sheet(S4).json()["rows"]] == L0[::-1], "device 1 sorts with the order it saw " + r.text[:200])
r = order({"ids": L0[1:] + L0[:1], "prev": L0})
check(r.status_code == 409 and r.json().get("rows") == L0[::-1], "device 2 with the old order: 409 and the current order " + r.text[:200])
check([x["id"] for x in sheet(S4).json()["rows"]] == L0[::-1], "... device 1's sorting stays")
L1 = L0[::-1]
r = Fr.post(B + f"/api/sheets/{S4}/rows", json={"count": 1})
check(r.ok, "a row added elsewhere " + r.text[:200])
r = order({"ids": L1[::-1], "prev": L1})
check(r.ok, "a row added since is no conflict " + r.text[:200])
L2 = [x["id"] for x in sheet(S4).json()["rows"]]
Fr.delete(B + f"/api/sheets/{S4}/rows/{L2[0]}")
r = order({"ids": L2[1:], "prev": L2})
check(r.status_code == 409, "a row of the seen order deleted since: 409 " + r.text[:200])
check(order({"ids": L2[2:]}).ok, "without prev (an older client): as before")
check(order({"ids": L2[2:], "prev": "x"}).status_code == 400, "a malformed prev: 400")
col = lambda b: Fr.patch(B + f"/api/sheets/{S4}/columns/{C0['id']}", json=b)
r = col({"title": "Owner", "_prev": {"title": C0["title"]}})
check(r.ok and r.json()["column"]["title"] == "Owner" and not r.json()["conflicts"], "device 1 names the column " + r.text[:200])
r = col({"title": "Lead", "width": 180, "_prev": {"title": C0["title"], "width": C0["width"]}})
cf = r.json().get("conflicts") if r.ok else None
check(r.ok and r.json()["column"]["title"] == "Owner" and r.json()["column"]["width"] == 180, "device 2: the title changed elsewhere stays, its width goes in " + r.text[:200])
check(cf == [{"field": "title", "server": "Owner", "mine": "Lead"}], "... the title is named as a conflict " + str(cf))
r = col({"title": "Owner", "_prev": {"title": C0["title"]}})
check(r.ok and not r.json()["conflicts"], "the same value as the server's: no conflict")
r = col({"pos": 9.5, "_prev": {"pos": C0["pos"] + 1}})
check(r.ok and r.json()["conflicts"] and r.json()["column"]["pos"] == C0["pos"], "a column moved elsewhere: its place stays " + r.text[:200])
check(col({"title": "Plain"}).json()["column"]["title"] == "Plain", "without _prev: as before")

# ================================================================== (B22) the trash of tables
S5 = Fr.post(B + "/api/sheets", json={"title": "Budget", "space": "private"}).json()["id"]
d = sheet(S5).json()
RB, CB = d["rows"][1]["id"], d["columns"][1]["id"]
Fr.put(B + f"/api/sheets/{S5}/cells", json={"cells": [{"row_id": RB, "col_id": d["columns"][0]["id"], "raw": "Rent"},
                                                     {"row_id": d["rows"][0]["id"], "col_id": CB, "raw": "1200"}]})
check(Fr.delete(B + f"/api/sheets/{S5}/rows/{RB}").ok and Fr.delete(B + f"/api/sheets/{S5}/columns/{CB}").ok, "frida deletes a row and a column")
r = Fr.get(B + f"/api/sheets/{S5}/trash")
t = r.json() if r.ok else {}
check([x["id"] for x in t.get("rows", [])] == [RB] and t["rows"][0]["values"] == ["Rent"], "the table's trash shows the row with its input " + r.text[:300])
check([x["id"] for x in t.get("columns", [])] == [CB] and t["columns"][0]["values"] == ["1200"] and t.get("days") == 30 and t.get("can_write") is True,
      "... and the column, the trash period and the right to restore " + str(t.get("columns")))
check(Fr.post(B + f"/api/sheets/{S5}/rows/{RB}/restore").ok and not Fr.get(B + f"/api/sheets/{S5}/trash").json()["rows"], "the row comes back out of it")
check(A.get(B + f"/api/sheets/{S5}/trash").status_code == 404, "another person: 404 on the table's trash")
check(Fr.delete(B + f"/api/sheets/{S5}").ok, "frida deletes the table")
r = Fr.get(B + "/api/sheets/trash", params={"space": "private"})
t = r.json() if r.ok else {}
x5 = next((x for x in t.get("sheets", []) if x["id"] == S5), None)
check(x5 and x5["title"] == "Budget" and x5["deleted_at"] and x5["can_write"] and t.get("may_empty") is True, "the workspace's trash lists it " + r.text[:300])
check(S5 not in [x["id"] for x in A.get(B + "/api/sheets/trash", params={"space": "private"}).json()["sheets"]], "not in another person's trash")
check(Fr.get(B + "/api/sheets/trash", params={"space": f"org:{ORG}"}).status_code == 404, "an organisation frida is not in: 404")
check(Fr.post(B + f"/api/sheets/{S5}/restore").ok and sheet(S5).ok, "restored from the trash")
Fr.delete(B + f"/api/sheets/{S5}")
r = A.post(B + "/api/sheets/purge", json={"space": "private", "ids": [S5]})
check(r.ok and r.json()["ids"] == [] and r.json()["skipped"] == [S5], "another person cannot delete it for good " + r.text[:200])
r = Fr.post(B + "/api/sheets/purge", json={"space": "private", "ids": [S5]})
check(r.ok and r.json()["ids"] == [S5], "frida deletes it for good " + r.text[:200])
check(Fr.post(B + f"/api/sheets/{S5}/restore").status_code == 404 and S5 not in [x["id"] for x in Fr.get(B + "/api/sheets/trash").json()["sheets"]],
      "... it is gone, also from the trash")
ids6 = [Fr.post(B + "/api/sheets", json={"title": f"Old {i}", "space": "private"}).json()["id"] for i in range(2)]
for i in ids6:
    Fr.delete(B + f"/api/sheets/{i}")
r = Fr.post(B + "/api/sheets/purge", json={"space": "private", "all": True})
check(r.ok and set(ids6) <= set(r.json()["ids"]) and not Fr.get(B + "/api/sheets/trash").json()["sheets"], "emptying the private trash (also the agent table taken back above) " + r.text[:200])
check(Fr.post(B + "/api/sheets/purge", json={"space": "private", "ids": "x"}).status_code == 400, "malformed ids: 400")
# an organisation's trash: a member deletes one table for good, its whole trash only the admins
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": [ORG]})
check(r.ok, "setup: bob in the organisation " + r.text[:200])
Bo = kt.sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,sheets", "tour": "done"})
O1, O2 = [Bo.post(B + "/api/sheets", json={"title": f"Team {i}", "space": f"org:{ORG}"}).json()["id"] for i in range(2)]
for i in (O1, O2):
    Bo.delete(B + f"/api/sheets/{i}")
t = Bo.get(B + "/api/sheets/trash", params={"space": f"org:{ORG}"}).json()
check({O1, O2} <= {x["id"] for x in t["sheets"]} and t["may_empty"] is False, "a member sees the organisation's trash, may not empty it " + str(t)[:200])
check(Bo.post(B + "/api/sheets/purge", json={"space": f"org:{ORG}", "all": True}).status_code == 403, "a member: emptying it 403")
check(Bo.post(B + "/api/sheets/purge", json={"space": f"org:{ORG}", "ids": [O1, O2]}).status_code == 403, "a member: several at once 403")
check(Bo.post(B + "/api/sheets/purge", json={"space": f"org:{ORG}", "ids": [O1]}).json().get("ids") == [O1], "a member: one table for good")
check(Fr.post(B + "/api/sheets/purge", json={"space": f"org:{ORG}", "all": True}).status_code == 404, "a stranger: 404")
r = A.post(B + "/api/sheets/purge", json={"space": f"org:{ORG}", "all": True})
check(r.ok and O2 in r.json()["ids"], "the admin empties the organisation's trash " + r.text[:200])

# ================================================================== (B25) a move stops when a file cannot be copied
def stored(path):
    return os.path.join(kt.DATA, "attachments", path)


def nfiles():
    return sum(len(fs) for _, _, fs in os.walk(os.path.join(kt.DATA, "attachments")))


SM = A.post(B + "/api/sheets", json={"title": "Contracts", "space": "private"}).json()["id"]
CF = A.post(B + f"/api/sheets/{SM}/columns", json={"title": "Doc", "kind": "file"}).json()["column"]["id"]
RM = sheet(SM, A).json()["rows"][0]["id"]
r = A.post(B + f"/api/sheets/{SM}/files", data={"row_id": str(RM), "col_id": str(CF)}, files={"file": ("lease.pdf", b"%PDF-1.4 lease", "application/pdf")})
check(r.status_code == 201, "a file into the table " + r.text[:200])
FM = r.json()["file"]["id"]
path0 = kt.dbx("SELECT path FROM sheet_files WHERE id=?", (FM,))[0][0]
with open(stored(path0), "rb") as f:
    good = f.read()
with open(stored(path0), "wb") as f:
    f.write(MAGIC + b"\0" * 8 + b"cut")
n0 = nfiles()
r = A.post(B + f"/api/sheets/{SM}/move-space", json={"to": f"org:{ORG}"})
check(r.status_code == 409 and "nothing was moved" in r.text, "a file that cannot be copied stops the move (409) " + r.text[:200])
d = sheet(SM, A).json()
row = kt.dbx("SELECT path, org_id FROM sheet_files WHERE id=?", (FM,))[0]
check(d["space"] == "private" and row[0] == path0 and row[1] is None, "the table and its file stay private as they were " + str((d["space"], row)))
check(nfiles() == n0, "no new stored file is left behind " + str((n0, nfiles())))
with open(stored(path0), "wb") as f:
    f.write(good)
r = A.post(B + f"/api/sheets/{SM}/move-space", json={"to": f"org:{ORG}"})
check(r.ok and sheet(SM, A).json()["space"] == f"org:{ORG}", "with the file intact the move goes through " + r.text[:200])
r = A.get(B + f"/api/sheets/{SM}/files/{FM}")
check(r.ok and r.content == b"%PDF-1.4 lease", "... and the file opens in the new workspace")

# the same for a knowledge page (wiki/wikiatt.py wka_move_files)
r = A.post(B + "/api/wiki/pages", json={"space": "private", "path": "Lease notes", "body": "See the file."})
check(r.status_code == 201, "a knowledge page " + r.text[:200])
PG = r.json()["id"]
r = A.post(B + f"/api/wiki/pages/{PG}/files", files={"file": ("lease.pdf", b"%PDF-1.4 page", "application/pdf")})
check(r.status_code == 201, "a file on the page " + r.text[:200])
WF = r.json()["files"][0]["id"]
wpath = kt.dbx("SELECT path FROM wiki_files WHERE id=?", (WF,))[0][0]
with open(stored(wpath), "rb") as f:
    good = f.read()
with open(stored(wpath), "wb") as f:
    f.write(MAGIC + b"\0" * 8 + b"cut")
n0 = nfiles()
r = A.post(B + "/api/wiki/move-space", json={"space": "private", "to": f"org:{ORG}", "pages": [PG]})
check(r.status_code == 409 and "nothing was moved" in r.text, "knowledge: a file that cannot be copied stops the move " + r.text[:200])
row = kt.dbx("SELECT p.org_id, f.path, f.org_id FROM wiki_pages p JOIN wiki_files f ON f.page_id=p.id WHERE f.id=?", (WF,))[0]
check(row[0] is None and row[1] == wpath and row[2] is None and nfiles() == n0, "knowledge: page and file stay private as they were " + str(row))
with open(stored(wpath), "wb") as f:
    f.write(good)
r = A.post(B + "/api/wiki/move-space", json={"space": "private", "to": f"org:{ORG}", "pages": [PG]})
check(r.ok and kt.dbx("SELECT org_id FROM wiki_pages WHERE id=?", (PG,))[0][0] == ORG, "knowledge: with the file intact the move goes through " + r.text[:200])

sys.exit(kt.done("p2528_c_sheets"))
