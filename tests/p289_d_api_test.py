#!/usr/bin/env python3
"""2.89.0 API tests, part D (#1916): tables step 2 -- carrying data over BY BUTTON (kalmido/sheets/step2.py). Invented names only.
 - rows -> tasks: a list of the sheet's organisation (title / due / notes columns, chosen rows), the task's history says it
   came from a table (link, no table name), the row is marked; pressing again skips the rows carried over; undo = the tasks to
   the trash + the marks gone, redo = back
 - the target is checked: a list of another organisation / a private list from an organisation's sheet 404, a list one only
   reads 403, a person who only reads the sheet 403; an agent 403
 - sheet -> quotation draft in the office of the sheet's organisation: description / quantity / unit / unit price columns,
   a client of that office (a client of another office 404), the office history "created from a table", the sheet's mark;
   undo by the office admin deletes the draft, by a member it stays (kept)
 - a person without an organisation (dave, P4): a private sheet -> tasks of a private list and a quotation draft in the
   personal office with a private client; an organisation's list or client refused
 - list -> rows: one row per task with live values (aufgabe.<id>.titel / status / faellig / zeit / zustaendig), new
   columns on an empty sheet (the blank ones step aside), pressing again only fetches the new tasks into the same columns;
   another member who does not see the list gets "No access" without a value; a task in the trash = "Source deleted"
tenant-matrix: sheet
usage: p289_d_api_test.py <datadir>      (a fresh container; P289D_NOSTART=1 = the server already runs)"""
import datetime
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "collab,comments,sheets,office,clients,time"


if not os.environ.get("P289D_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["comments"]})
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["carol"]})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
Da.patch(B + "/api/settings", json={"workspace": "private"})
YDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


def sheet(s, sid):
    r = s.get(B + f"/api/sheets/{sid}")
    return r.json() if r.ok else None


def cell(sh, rid, cid):
    return next((c for c in sh["cells"] if c["row_id"] == rid and c["col_id"] == cid), None)


def new_sheet(s, space, title, cols):
    """A sheet with the given columns [(title, kind)] (the blank start columns turned into them)."""
    r = s.post(B + "/api/sheets", json={"title": title, "space": space})
    assert r.status_code == 201, r.text
    sh = r.json()
    ids = []
    for i, (t, k) in enumerate(cols):
        if i < len(sh["columns"]):
            cid = sh["columns"][i]["id"]
            assert s.patch(B + f"/api/sheets/{sh['id']}/columns/{cid}", json={"title": t, "kind": k}).ok
        else:
            rr = s.post(B + f"/api/sheets/{sh['id']}/columns", json={"title": t, "kind": k})
            assert rr.ok, rr.text
            cid = rr.json().get("id") or rr.json().get("column", {}).get("id")
        ids.append(cid)
    return sheet(s, sh["id"]), ids


def put(s, sh, rows, cols):
    cells = [{"row_id": sh["rows"][i]["id"], "col_id": cols[j], "raw": v} for i, vals in enumerate(rows) for j, v in enumerate(vals) if v != ""]
    r = s.put(B + f"/api/sheets/{sh['id']}/cells", json={"cells": cells})
    assert r.ok, r.text


def acts(s, tid):
    r = s.get(B + f"/api/tasks/{tid}/timeline")
    return r.json().get("activity", []) if r.ok else []


# ================================================================ rows -> tasks (an organisation's sheet)
SH, C = new_sheet(A, f"org:{ORG}", "Shoot plan", [("Item", "text"), ("Qty", "number"), ("Unit", "text"), ("Price", "currency"), ("Due", "date")])
put(A, SH, [["Camera day", "2", "Tag", "650", "20.11.2026"], ["Editing", "6", "Std", "85", ""], ["Travel", "1", "pauschal", "120", ""]], C)
SID = SH["id"]
R = [x["id"] for x in SH["rows"]]
L = A.post(B + "/api/lists", json={"name": "Shoot", "org_id": ORG, "kind": "project", "time_tracking": True}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["bob"], "role": "edit"})
LRO = A.post(B + "/api/lists", json={"name": "Read only", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{LRO}/members", json={"user_id": uid["bob"], "role": "view"})
LPRIV = A.post(B + "/api/lists", json={"name": "Alice private", "org_id": None}).json()["id"]
LBETA = Ca.post(B + "/api/lists", json={"name": "Beta list", "org_id": ORG2}).json()["id"]

r = A.post(B + f"/api/sheets/{SID}/to-tasks", json={"list_id": L, "title_col": C[0], "due_col": C[4], "notes_col": C[2], "rows": [R[0], R[1]]})
check(r.ok, "rows -> tasks " + r.text[:300])
T = r.json() if r.ok else {"tasks": [], "batch": "x"}
check([t["title"] for t in T["tasks"]] == ["Camera day", "Editing"] and T["list_id"] == L, "two tasks in row order " + str(T.get("tasks")))
tasks = {t["row_id"]: t["task_id"] for t in T["tasks"]}
t0 = A.get(B + f"/api/tasks/{tasks.get(R[0])}").json() if tasks else {}
check(t0.get("list_id") == L and t0.get("due") == "2026-11-20" and "Tag" in (t0.get("content") or t0.get("notes") or ""),
      "the task: list, due from the date column, notes from the chosen column " + str({k: t0.get(k) for k in ("list_id", "due", "content")}))
a0 = [a for a in acts(A, tasks.get(R[0], 0)) if a["kind"] == "created"]
check(a0 and a0[0]["data"].get("sheet") == SID and "Shoot plan" not in str(a0[0]["data"]),
      "the history: carried over from a table (its id, not its name) " + str(a0))
lk = A.get(B + f"/api/sheets/{SID}/links").json()
mk = {x["row_id"]: x for x in lk["links"] if x["kind"] == "task"}
check(set(mk) == {R[0], R[1]} and mk[R[0]]["label"] == "Camera day" and mk[R[0]]["target_id"] == tasks[R[0]], "the rows are marked with their task " + str(lk["links"]))
check(any(x["id"] == L and x["writable"] for x in lk["lists"]) and not any(x["id"] in (LPRIV, LBETA) for x in lk["lists"]),
      "the dialog offers the lists of the sheet's space only " + str(lk["lists"]))
r = A.post(B + f"/api/sheets/{SID}/to-tasks", json={"list_id": L, "title_col": C[0], "rows": [R[0], R[1]]})
check(r.status_code == 400, "pressing again on the same rows: nothing new (400) " + str(r.status_code))
r = A.post(B + f"/api/sheets/{SID}/to-tasks", json={"list_id": L, "title_col": C[0]})
check(r.ok and [t["title"] for t in r.json()["tasks"]] == ["Travel"], "all rows: only the row not carried over yet " + r.text[:200])
T3 = r.json() if r.ok else {"batch": "x"}
# undo / redo of the first press
r = A.post(B + f"/api/sheets/{SID}/links/{T['batch']}/undo")
check(r.ok and r.json().get("done") == 2, "undo: both tasks " + r.text[:200])
check(A.get(B + f"/api/tasks/{tasks.get(R[0])}").status_code == 404, "the task is in the trash after the undo")
check(not any(x["row_id"] in (R[0], R[1]) for x in A.get(B + f"/api/sheets/{SID}/links").json()["links"]), "the marks are gone")
r = A.post(B + f"/api/sheets/{SID}/links/{T['batch']}/redo")
check(r.ok and A.get(B + f"/api/tasks/{tasks.get(R[0])}").ok, "redo: the task is back " + r.text[:200])
check(A.post(B + f"/api/sheets/{SID}/links/nosuchbatch/undo").status_code == 404, "an unknown press 404")

# the target and the sheet are checked
for lid, code, what in ((LBETA, 404, "a list of another organisation"), (LPRIV, 404, "a private list from an organisation's sheet"),
                        (999999, 404, "a list that does not exist")):
    r = A.post(B + f"/api/sheets/{SID}/to-tasks", json={"list_id": lid, "title_col": C[0], "rows": [R[2]]})
    check(r.status_code == code, f"{what}: {code} ({r.status_code})")
r = Bo.post(B + f"/api/sheets/{SID}/to-tasks", json={"list_id": LRO, "title_col": C[0], "rows": [R[2]]})
check(r.status_code == 403, "a list bob only reads: 403 " + str(r.status_code))
check(Ca.post(B + f"/api/sheets/{SID}/to-tasks", json={"list_id": LBETA, "title_col": C[0]}).status_code == 404,
      "carol (another organisation) does not reach the sheet: 404")
check(Ca.get(B + f"/api/sheets/{SID}/links").status_code == 404, "nor its marks")
r = A.post(B + f"/api/sheets/{SID}/to-tasks", json={"list_id": L, "title_col": 123456789})
check(r.status_code == 400, "a column of no sheet: 400")
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "helper", "display_name": "Helper"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
r = requests.post(B + f"/api/sheets/{SID}/to-tasks", headers=AGH, json={"list_id": L, "title_col": C[0]})
check(r.status_code in (401, 403, 404), "an agent may not press the button " + str(r.status_code))

# ================================================================ sheet -> quotation draft (Alpha's office)
CL = A.post(B + "/api/clients", json={"name": "Example Client Ltd", "org_id": ORG}).json()["id"]
CLB = Ca.post(B + "/api/clients", json={"name": "Beta Client", "org_id": ORG2}).json()["id"]
check(A.get(B + f"/api/sheets/{SID}/links").json()["office"] is True, "the office is on for the sheet's space")
r = A.post(B + f"/api/sheets/{SID}/to-offer", json={"desc_col": C[0], "qty_col": C[1], "unit_col": C[2], "price_col": C[3], "client_id": CLB})
check(r.status_code == 404, "a client of another office: 404 " + str(r.status_code))
r = A.post(B + f"/api/sheets/{SID}/to-offer", json={"desc_col": C[0], "qty_col": C[1], "unit_col": C[2], "price_col": C[3], "client_id": CL})
check(r.ok, "sheet -> quotation draft " + r.text[:300])
O1 = r.json() if r.ok else {"doc_id": 0, "batch": "x"}
d = A.get(B + f"/api/office/docs/{O1['doc_id']}").json()
items = [(i["title"], float(i["qty"]), i["unit"], float(i["rate"])) for i in d.get("items", [])]
check(items == [("Camera day", 2.0, "day", 650.0), ("Editing", 6.0, "hour", 85.0), ("Travel", 1.0, "flat", 120.0)],
      "the positions: description, quantity, unit (Tag / Std / pauschal), unit price " + str(items))
check(d.get("status") == "draft" and d.get("client_id") == CL and d.get("project_title") == "Shoot plan", "a draft for the client, titled like the sheet "
      + str({k: d.get(k) for k in ("status", "client_id", "project_title")}))
lg = A.get(B + f"/api/office/docs/{O1['doc_id']}/log").json().get("log", [])
check(any(x["action"] == "from_sheet" for x in lg), "the office history: created from a table " + str([x["action"] for x in lg]))
lk = A.get(B + f"/api/sheets/{SID}/links").json()["links"]
check(any(x["kind"] == "offer" and x["target_id"] == O1["doc_id"] and x["label"] for x in lk), "the sheet is marked: carried over into the quotation")
r = A.post(B + f"/api/sheets/{SID}/links/{O1['batch']}/undo")
check(r.ok and r.json()["kept"] == [] and A.get(B + f"/api/office/docs/{O1['doc_id']}").status_code == 404, "undo by the office admin deletes the draft " + r.text[:200])
r = Bo.post(B + f"/api/sheets/{SID}/to-offer", json={"desc_col": C[0], "rows": [R[0]]})
check(r.ok, "bob (member) makes a draft from one row " + r.text[:200])
O2 = r.json() if r.ok else {"doc_id": 0, "batch": "x"}
r = Bo.post(B + f"/api/sheets/{SID}/links/{O2['batch']}/undo")
check(r.ok and r.json()["kept"] == [O2["doc_id"]] and A.get(B + f"/api/office/docs/{O2['doc_id']}").ok, "undo by a member: the draft stays (kept) " + r.text[:200])
# a reader of the sheet: an organisation's sheet attached to a list bob only reads
SHR = A.post(B + "/api/sheets", json={"title": "Attached", "space": f"org:{ORG}", "list_id": LRO}).json()
check(Bo.post(B + f"/api/sheets/{SHR['id']}/to-offer", json={"desc_col": SHR["columns"][0]["id"]}).status_code == 403, "bob only reads that sheet: 403")

# ================================================================ a person without an organisation (dave, P4)
DS, DC = new_sheet(Da, "private", "Gear rental", [("What", "text"), ("Days", "number"), ("Rate", "currency")])
put(Da, DS, [["Lens kit", "3", "40"], ["Lights", "2", "55"]], DC)
DL = Da.post(B + "/api/lists", json={"name": "Dave jobs", "org_id": None}).json()["id"]
r = Da.post(B + f"/api/sheets/{DS['id']}/to-tasks", json={"list_id": DL, "title_col": DC[0]})
check(r.ok and len(r.json()["tasks"]) == 2, "dave: private sheet -> tasks of his private list " + r.text[:200])
check(Da.post(B + f"/api/sheets/{DS['id']}/to-tasks", json={"list_id": L, "title_col": DC[0]}).status_code == 404,
      "dave: a list of Alpha is not reachable (404)")
DCL = Da.post(B + "/api/clients", json={"name": "Private Client", "org_id": None}).json()["id"]
check(Da.get(B + f"/api/sheets/{DS['id']}/links").json()["office"] is True, "dave: the personal office is offered")
r = Da.post(B + f"/api/sheets/{DS['id']}/to-offer", json={"desc_col": DC[0], "qty_col": DC[1], "price_col": DC[2], "client_id": CL})
check(r.status_code == 404, "dave: Alpha's client 404 " + str(r.status_code))
r = Da.post(B + f"/api/sheets/{DS['id']}/to-offer", json={"desc_col": DC[0], "qty_col": DC[1], "price_col": DC[2], "client_id": DCL})
check(r.ok, "dave: a quotation draft in his personal office " + r.text[:200])
DO = r.json() if r.ok else {"doc_id": 0}
dd = Da.get(B + f"/api/office/docs/{DO['doc_id']}")
check(dd.ok and len(dd.json().get("items", [])) == 2 and dd.json().get("client_id") == DCL, "dave reads his draft with both positions")
check(A.get(B + f"/api/office/docs/{DO['doc_id']}").status_code in (403, 404), "alice does not see dave's draft")
check(Da.get(B + f"/api/office/docs/{O2['doc_id']}").status_code in (400, 403, 404), "dave does not see Alpha's draft")

# ================================================================ list -> rows (live task values)
tl = [A.post(B + "/api/tasks", json={"title": t, "list_id": L, **({"due": "2026-12-01"} if t == "Grade" else {})}).json()["id"] for t in ("Grade", "Mix")]
A.patch(B + f"/api/tasks/{tl[1]}", json={"assignee_id": uid["bob"]})
A.post(B + "/api/time/entries", json={"task_id": tl[0], "start": YDAY + "T09:00", "minutes": 90})
LS, _ = new_sheet(A, f"org:{ORG}", "Shoot tasks", [])
blank = [c["id"] for c in LS["columns"]]
r = A.post(B + f"/api/sheets/{LS['id']}/rows-from-list", json={"list_id": L})
check(r.ok and r.json()["added"] >= 5, "list -> rows: one row per task " + r.text[:200])
B1 = r.json() if r.ok else {"batch": "x", "rows": []}
ls = sheet(A, LS["id"])
check([c["title"] for c in ls["columns"]] == ["Title", "Status", "Due", "Time", "Assignee"] and not any(c["id"] in blank for c in ls["columns"]),
      "an empty sheet: five columns, the blank start columns step aside " + str([c["title"] for c in ls["columns"]]))
check(ls["rows"][0]["id"] in B1["rows"], "the new rows come first (above the blank rows)")
cols = {c["title"]: c["id"] for c in ls["columns"]}
row_of = {}
for rid in B1["rows"]:
    x = cell(ls, rid, cols["Title"])
    if x:
        row_of[x["display"]] = rid
g = row_of.get("Grade")
cg = {k: cell(ls, g, cols[k]) for k in cols} if g else {}
check(g and cg["Title"]["raw"] == f"=aufgabe.{tl[0]}.titel" and cg["Title"]["origin"] == "kalmido", "a live Kalmido value: =aufgabe.<id>.titel "
      + str(cg.get("Title")))
check(g and cg["Status"]["display"] == "Open" and cg["Due"]["value"] == "2026-12-01" and float(cg["Time"]["value"]) == 1.5,
      "status, due, booked hours " + str({k: (v or {}).get("value") for k, v in cg.items()}))
m = row_of.get("Mix")
check(m and cell(ls, m, cols["Assignee"])["display"] == "Bob", "the assignee's name")
A.patch(B + f"/api/tasks/{tl[0]}", json={"title": "Grade final"})
check(cell(sheet(A, LS["id"]), g, cols["Title"])["display"] == "Grade final", "a renamed task shows its new title (live)")
# bob sees the sheet (organisation) but not a list that is not shared with him
L3 = A.post(B + "/api/lists", json={"name": "Alice only", "org_id": ORG}).json()["id"]
t3 = A.post(B + "/api/tasks", json={"title": "Secret task", "list_id": L3}).json()["id"]
r = A.post(B + f"/api/sheets/{LS['id']}/rows-from-list", json={"list_id": L3})
check(r.ok and r.json()["added"] == 1, "rows of a second list " + r.text[:200])
B2 = r.json() if r.ok else {"batch": "x"}
check(len(sheet(A, LS["id"])["columns"]) == 5, "a second list uses the same task columns")
bs = sheet(Bo, LS["id"])
secret = [c for c in bs["cells"] if f"{t3}" in (c["raw"] or "")]
check(secret and all(c["error"] == "denied" and c["value"] is None and "Secret" not in str(c["display"]) for c in secret),
      "bob: no access, no value, no title " + str(secret[:1]))
check(bs and not any("Secret" in str(c.get("display")) or "Secret" in str(c.get("raw")) for c in bs["cells"]), "the title shows nowhere for bob")
check(Bo.post(B + f"/api/sheets/{LS['id']}/rows-from-list", json={"list_id": L3}).status_code == 404, "bob cannot fetch rows of that list (404)")
check(A.post(B + f"/api/sheets/{LS['id']}/rows-from-list", json={"list_id": LBETA}).status_code == 404, "a list of another organisation 404")
# fetch new tasks: only the missing ones, into the same columns
ncols = len(sheet(A, LS["id"])["columns"])
A.post(B + "/api/tasks", json={"title": "Deliver", "list_id": L})
r = A.post(B + f"/api/sheets/{LS['id']}/rows-from-list", json={"list_id": L})
check(r.ok and r.json()["added"] == 1, "fetching again: only the new task " + r.text[:200])
B3 = r.json() if r.ok else {"batch": "x"}
ls = sheet(A, LS["id"])
check(len(ls["columns"]) == ncols and any(x["display"] == "Deliver" for x in ls["cells"]), "same columns, the new row is there")
r = A.post(B + f"/api/sheets/{LS['id']}/rows-from-list", json={"list_id": L})
check(r.ok and r.json()["added"] == 0, "nothing new: nothing added")
check(A.post(B + f"/api/sheets/{LS['id']}/links/{B3['batch']}/undo").ok and not any(x["display"] == "Deliver" for x in sheet(A, LS["id"])["cells"]),
      "undo: the fetched row is gone")
A.delete(B + f"/api/tasks/{tl[1]}")
cm = cell(sheet(A, LS["id"]), m, cols["Title"]) if m else None
check(cm and cm["error"] == "deleted" and cm["last_value"] == "Mix", "a task in the trash: Source deleted with the last value " + str(cm))
check(A.post(B + f"/api/sheets/{LS['id']}/links/{B1['batch']}/undo").ok
      and {"Title", "Status", "Due", "Time", "Assignee"} <= {c["title"] for c in sheet(A, LS["id"])["columns"]},
      "undo of the first press while the second list's rows use the columns: they stay")
A.post(B + f"/api/sheets/{LS['id']}/links/{B1['batch']}/redo")
check(A.post(B + f"/api/sheets/{LS['id']}/links/{B2['batch']}/undo").ok, "undo of the second list's rows")
r = A.post(B + f"/api/sheets/{LS['id']}/links/{B1['batch']}/undo")
ls = sheet(A, LS["id"])
check(r.ok and [c["id"] for c in ls["columns"]] == blank, "undo of the first press: the blank columns are back, the task columns gone "
      + str([c["title"] for c in ls["columns"]]))
# a formula typed by hand: aufgabe.<id>.<field> of a task one does not see is refused
r = Bo.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"row_id": R[2], "col_id": C[1], "raw": f"=aufgabe.{t3}.zeit"}]})
check(r.status_code == 400, "bob may not type a variable of a task he does not see " + str(r.status_code))
r = A.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"row_id": R[2], "col_id": C[1], "raw": f"=aufgabe.{tl[0]}.zeit*2"}]})
check(r.ok and any(x.get("value") == 3 for x in r.json()["cells"]), "alice types =aufgabe.<id>.zeit*2 " + r.text[:200])

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
