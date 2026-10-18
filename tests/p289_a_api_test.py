#!/usr/bin/env python3
"""2.89.0 API tests, part A (#1916): tables ("Excel in simple") -- the server core, formulas, Kalmido variables. Invented names only.
 - the module switch: changes need "sheets" on (409), reading stays
 - spaces like knowledge pages: an organisation's table for every member, a private one for its owner only, a table attached to
   a list follows the list (a reader reads, cannot write; a member of the organisation who does not see the list gets 404);
   another organisation / person / an agent on the session routes gets nothing (tenant-matrix: sheet)
 - formulas: + - * /, %, SUMME over a range and over a column name, WENN, RUNDEN, a date plus days, TAGE, a cell's name
   (rename / remove: the formula follows), sorting keeps the values, a cycle, division by zero, a syntax error (400)
 - Kalmido variables evaluated per viewer: projekt / kunde / hier; renaming the project changes the shown name; someone who
   does not see the project gets "denied" without its name or value; a source of another space cannot be chosen; a deleted
   project shows "deleted" with the last value only for whoever saw it; freezing keeps a copy
 - select column (option ids, labels as values), currency display, column / row / table trash + restore, presence, completion
 - a person without an organisation ("dave") does everything in the private space
usage: p289_a_api_test.py <datadir>      (a fresh container; P289A_NOSTART=1 = the server already runs)"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "sheets,time,clients,collab,comments,progress"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


if not os.environ.get("P289A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "erin", "dave", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u in ("bob", "carol", "erin") else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ca, Er, Da, Fr = sess("bob"), sess("carol"), sess("erin"), sess("dave"), sess("frank")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}

# ---- the module switch: off = no changes (reading stays)
A.patch(B + "/api/settings", json={"features": "time,clients,collab,comments"})
r = A.post(B + "/api/sheets", json={"title": "Off", "space": f"org:{ORG}"})
check(r.status_code == 409, "module off: creating a table 409 " + r.text[:200])
for s in (A, Bo, Ca, Er, Da, Fr):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en"})


def put(s, sid, cells):
    return s.put(B + f"/api/sheets/{sid}/cells", json={"cells": cells})


def cell(d, addr):
    return next((x for x in d["cells"] if x["addr"] == addr), None)


def get(s, sid):
    return s.get(B + f"/api/sheets/{sid}").json()


def setv(s, sid, addr, raw):
    r = put(s, sid, [{"cell": addr, "raw": raw}])
    return r


# ---- an organisation's table
r = A.post(B + "/api/sheets", json={"title": "Budget", "space": f"org:{ORG}"})
check(r.status_code == 201, "create in the organisation " + r.text[:200])
S = r.json()
SID = S["id"]
check(len(S["columns"]) == 3 and len(S["rows"]) == 10 and [c["letter"] for c in S["columns"]] == ["A", "B", "C"], "3 columns A-C, 10 rows")
check(S["can_write"] is True and S["space"] == f"org:{ORG}" and isinstance(S["rev"], int), "can_write, space, rev")
COL = [c["id"] for c in S["columns"]]
ROW = [x["id"] for x in S["rows"]]
r = A.post(B + f"/api/sheets/{SID}/columns", json={"title": "", "kind": "text"})
check(r.status_code == 201 and r.json()["column"]["letter"] == "D", "a fourth column D " + r.text[:200])
COL.append(r.json()["column"]["id"])
r = put(A, SID, [{"row_id": ROW[0], "col_id": COL[0], "raw": "10"}, {"row_id": ROW[1], "col_id": COL[0], "raw": "20"},
                 {"row_id": ROW[2], "col_id": COL[0], "raw": "=SUMME(A1:A2)"}])
check(r.ok and r.json()["rev"] > S["rev"], "cells saved, rev moves " + r.text[:300])
c3 = next((x for x in r.json()["cells"] if x["addr"] == "A3"), {}) if r.ok else {}
check(c3.get("value") == 30 and c3.get("origin") == "formula" and c3.get("raw") == "=SUMME(A1:A2)", "SUMME over a range = 30 " + json.dumps(c3)[:300])
check(sorted(c3.get("refs") or []) == sorted(x["id"] for x in get(A, SID)["cells"] if x["addr"] in ("A1", "A2")), "refs = the cells read")
# a change answers the dependants
r = setv(A, SID, "A1", "15")
check(r.ok and any(x["addr"] == "A3" and x["value"] == 35 for x in r.json()["cells"]), "changing A1 answers A3 again (35) " + r.text[:300])
setv(A, SID, "A1", "10")
# the other members of the organisation read and write; another organisation / a private person / an agent: nothing
check(Bo.get(B + f"/api/sheets/{SID}").status_code == 200, "bob (same organisation) reads")
check(setv(Bo, SID, "B1", "=A1*19%").ok, "bob writes")
check(cell(get(A, SID), "B1")["value"] == 1.9, "19 % of 10 = 1.9")
for who, s in (("frank (other organisation)", Fr), ("dave (no organisation)", Da)):
    check(s.get(B + f"/api/sheets/{SID}").status_code == 404, f"{who}: GET 404")
    check(setv(s, SID, "B2", "1").status_code == 404, f"{who}: cells 404")
    check(s.patch(B + f"/api/sheets/{SID}", json={"title": "x"}).status_code == 404, f"{who}: PATCH 404")
    check(s.delete(B + f"/api/sheets/{SID}").status_code == 404, f"{who}: DELETE 404")
    check(s.post(B + f"/api/sheets/{SID}/columns", json={"title": "x", "kind": "text"}).status_code == 404, f"{who}: column 404")
    check(s.post(B + f"/api/sheets/{SID}/rows", json={}).status_code == 404, f"{who}: row 404")
    check(s.get(B + f"/api/sheets/{SID}/vars").status_code == 404, f"{who}: completion 404")
    check(s.post(B + f"/api/sheets/{SID}/presence", json={"cell_id": None}).status_code == 404, f"{who}: presence 404")
    check(all(x["id"] != SID for x in s.get(B + "/api/sheets?space=all").json()["sheets"]), f"{who}: not in the index")
check(Fr.post(B + "/api/sheets", json={"title": "x", "space": f"org:{ORG}"}).status_code == 404, "frank cannot create in Alpha")
check(requests.get(B + f"/api/sheets/{SID}", headers=AGH).status_code in (401, 403, 404), "an agent token on the session route: refused")

# ---- formulas
setv(A, SID, "C1", "=WENN(A1>5;\"big\";\"small\")")
setv(A, SID, "C2", "=RUNDEN(10/3;2)")
setv(A, SID, "C4", "=1/0")
d = get(A, SID)
check(cell(d, "C1")["value"] == "big", "WENN")
check(cell(d, "C2")["value"] == 3.33, "RUNDEN(10/3;2) = 3.33")
check(cell(d, "C4")["error"] == "div0" and cell(d, "C4")["value"] is None and cell(d, "C4")["error_text"], "division by zero")
r = setv(A, SID, "C5", "=1+")
check(r.status_code == 400 and r.json().get("error"), "a syntax error: 400 with a text " + r.text[:200])
r = setv(A, SID, "C5", "=nosuchname*2")
check(r.status_code == 400, "an unknown name: 400")
# a column name: every cell of the column but the formula's own
r = A.patch(B + f"/api/sheets/{SID}/columns/{COL[0]}", json={"title": "Amount", "kind": "number"})
check(r.ok and r.json()["column"]["title"] == "Amount", "column renamed")
setv(A, SID, "C6", "=SUMME(amount)")
check(cell(get(A, SID), "C6")["value"] == 60, "SUMME(amount) = A1 + A2 + A3 = 60")
setv(A, SID, "A4", "=SUMME(amount)")
check(cell(get(A, SID), "A4")["error"] is None and cell(get(A, SID), "A4")["value"] == 60 + 0, "a column formula inside its own column leaves itself out")
# a name for a cell
c1 = cell(get(A, SID), "A1")
r = A.post(B + f"/api/sheets/{SID}/cells/{c1['id']}/name", json={"name": "rate"})
check(r.ok, "cell name " + r.text[:200])
check(A.post(B + f"/api/sheets/{SID}/cells/{cell(get(A, SID), 'A2')['id']}/name", json={"name": "rate"}).status_code == 400, "a name twice: 400")
check(A.post(B + f"/api/sheets/{SID}/cells/{c1['id']}/name", json={"name": "B7"}).status_code == 400, "a name like an address: 400")
setv(A, SID, "D1", "=rate*2")
d = get(A, SID)
check(cell(d, "D1")["value"] == 20 and cell(d, "D1")["raw"] == "=rate*2" and d["names"].get("rate") == c1["id"], "a formula with a cell name")
A.post(B + f"/api/sheets/{SID}/cells/{c1['id']}/name", json={"name": "dayrate"})
check(cell(get(A, SID), "D1")["raw"] == "=dayrate*2", "renaming the name changes the shown formula")
A.post(B + f"/api/sheets/{SID}/cells/{c1['id']}/name", json={"name": ""})
check(cell(get(A, SID), "D1")["raw"] == "=A1*2" and cell(get(A, SID), "D1")["value"] == 20, "without the name: the address")
# sorting keeps the values (ids, not addresses)
d = get(A, SID)
rows = [x["id"] for x in d["rows"]]
D1 = cell(d, "D1")["id"]
check(A.post(B + f"/api/sheets/{SID}/rows/order", json={"ids": list(reversed(rows))}).ok, "rows sorted")
dc = next(x for x in get(A, SID)["cells"] if x["id"] == D1)
check(dc["value"] == 20 and dc["raw"] == "=A10*2" and dc["addr"] == "D10", "after sorting the formula shows the new address, same value " + dc["raw"])
A.post(B + f"/api/sheets/{SID}/rows/order", json={"ids": rows})
# a cycle
setv(A, SID, "D2", "=D3+1")
setv(A, SID, "D3", "=D2+1")
d = get(A, SID)
check(cell(d, "D2")["error"] == "cycle" and cell(d, "D3")["error"] == "cycle", "a cycle: both cells")
# dates
r = A.post(B + f"/api/sheets/{SID}/columns", json={"title": "When", "kind": "date"})
check(r.status_code == 201 and r.json()["column"]["letter"] == "E", "a date column E")
DATE_COL = r.json()["column"]["id"]
put(A, SID, [{"row_id": ROW[0], "col_id": DATE_COL, "raw": "01.10.2026"}, {"row_id": ROW[1], "col_id": DATE_COL, "raw": "=E1+10"},
             {"row_id": ROW[2], "col_id": DATE_COL, "raw": "=TAGE(E2;E1)"}])
d = get(A, SID)
e = {x["addr"]: x for x in d["cells"] if x["col_id"] == DATE_COL}
check(e.get("E1", {}).get("value") == "2026-10-01" and e.get("E2", {}).get("value") == "2026-10-11", "a date plus 10 days " + json.dumps(e)[:300])
check(e.get("E3", {}).get("value") == 10, "TAGE = 10")

# ---- select and currency columns
r = A.post(B + f"/api/sheets/{SID}/columns", json={"title": "Status", "kind": "select"})
SEL = r.json()["column"]["id"]
r = A.patch(B + f"/api/sheets/{SID}/columns/{SEL}", json={"options": [{"label": "Open", "color": "#f5b041"}, {"label": "Agreed", "color": "#2e86de"}]})
opts = r.json()["column"]["options"]
check(r.ok and [o["label"] for o in opts] == ["Open", "Agreed"] and all(o["id"] for o in opts), "options get ids")
check(A.patch(B + f"/api/sheets/{SID}/columns/{SEL}", json={"options": [{"label": "x", "color": "red"}]}).status_code == 400, "a colour not #rrggbb: 400")
put(A, SID, [{"row_id": ROW[0], "col_id": SEL, "raw": opts[1]["id"]}, {"row_id": ROW[1], "col_id": SEL, "raw": "Open"}])
d = get(A, SID)
sc = [x for x in d["cells"] if x["col_id"] == SEL]
check(any(x["option"] == opts[1]["id"] and x["value"] == "Agreed" for x in sc), "an option id shows its label")
check(any(x["option"] == opts[0]["id"] and x["display"] == "Open" for x in sc), "a label becomes the option's id")
sel_addr = next(x["addr"] for x in sc if x["option"] == opts[1]["id"])
setv(A, SID, "C7", f'=WENN({sel_addr}="Agreed";1;0)')
check(cell(get(A, SID), "C7")["value"] == 1, "WENN on a select cell's label")
r = A.patch(B + f"/api/sheets/{SID}/columns/{SEL}", json={"kind": "text"})
check(r.ok and any(x["raw"] == "Agreed" and x["option"] is None for x in get(A, SID)["cells"] if x["col_id"] == SEL), "select -> text: the labels come back as text")
check(cell(get(A, SID), "C7")["value"] == 1, "... the formula still counts")
r = A.post(B + f"/api/sheets/{SID}/columns", json={"title": "Price", "kind": "currency"})
CUR = r.json()["column"]["id"]
check(r.json()["column"]["letter"] == "G", "currency column G")
put(A, SID, [{"row_id": ROW[0], "col_id": CUR, "raw": "1234,5"}])
pc = next(x for x in get(A, SID)["cells"] if x["col_id"] == CUR)
check(pc["value"] == 1234.5 and "1,234.50" in pc["display"] and "€" in pc["display"], "currency: value + display " + pc["display"])

# ---- column / row trash + restore
r = A.delete(B + f"/api/sheets/{SID}/columns/{CUR}")
check(r.ok, "column to the trash")
setv(A, SID, "C8", "=1")
check(all(x["col_id"] != CUR for x in get(A, SID)["cells"]) and all(c["id"] != CUR for c in get(A, SID)["columns"]), "a trashed column is not in GET")
check(A.post(B + f"/api/sheets/{SID}/columns/{CUR}/restore").ok and any(c["id"] == CUR for c in get(A, SID)["columns"]), "column restored")
setv(A, SID, "B5", "=A2*2")
check(A.delete(B + f"/api/sheets/{SID}/rows/{ROW[1]}").ok, "row to the trash")
b5 = next((x for x in get(A, SID)["cells"] if x["raw"].endswith("*2") and x["col_id"] == COL[1]), None)
check(b5 and b5["error"] == "ref", "a formula pointing at a trashed row: ref " + json.dumps(b5)[:200])
check(A.post(B + f"/api/sheets/{SID}/rows/{ROW[1]}/restore").ok, "row restored")
check(cell(get(A, SID), "B5")["value"] == 40, "after restoring: the value again")

# ---- Kalmido variables (column H)
check(A.post(B + f"/api/sheets/{SID}/columns", json={"title": "Vars", "kind": "number"}).json()["column"]["letter"] == "H", "column H")
P = A.post(B + "/api/lists", json={"name": "Shoot Berlin", "org_id": ORG, "kind": "project", "time_tracking": True}).json()["id"]
for t in ("Script", "Casting", "Edit"):
    tid = A.post(B + "/api/tasks", json={"title": t, "list_id": P}).json()["id"]
A.post(B + f"/api/tasks/{tid}/complete", json={})
r = A.post(B + "/api/time/entries", json={"list_id": P, "start": "2026-10-01T09:00:00Z", "minutes": 90})
check(r.ok, "setup: 90 minutes on the project " + r.text[:200])
CL = A.post(B + "/api/clients", json={"name": "Acme Films", "org_id": ORG, "rate": 80, "budget_h": 10}).json()["id"]
setv(A, SID, "H1", "=projekt.shoot_berlin.zeit_gesamt")
setv(A, SID, "H2", "=projekt.shoot_berlin.offen")
setv(A, SID, "H3", "=projekt.shoot_berlin.aufgaben-projekt.shoot_berlin.erledigt")
r = setv(A, SID, "H4", "=kunde.acme_films.satz*2")
check(r.ok, "a client variable " + r.text[:200])
d = get(A, SID)
f1 = cell(d, "H1")
check(f1["value"] == 1.5 and f1["origin"] == "kalmido" and f1["raw"] == "=projekt.shoot_berlin.zeit_gesamt", "project hours = 1.5 " + json.dumps(f1)[:300])
check(f1["sources"] and f1["sources"][0]["type"] == "p" and f1["sources"][0]["id"] == P and f1["sources"][0]["label"] == "Shoot Berlin", "sources of the cell")
check(cell(d, "H2")["value"] == 2 and cell(d, "H3")["value"] == 2, "open 2, tasks - done = 2")
check(cell(d, "H4")["value"] == 160, "client rate * 2 = 160")
check(any(s["type"] == "p" and s["id"] == P for s in d["sources"]), "the sheet's source overview")
# renaming the project: the formula shows the new name, same value
A.patch(B + f"/api/lists/{P}", json={"name": "Shoot Hamburg"})
d = get(A, SID)
check(cell(d, "H1")["raw"] == "=projekt.shoot_hamburg.zeit_gesamt" and cell(d, "H1")["value"] == 1.5, "project renamed: new name in the formula")
# bob does not see the project: "denied", no name, no value
db_ = Bo.get(B + f"/api/sheets/{SID}")
bf = cell(db_.json(), "H1")
check(bf["error"] == "denied" and bf["value"] is None and bf["display"] and "1.5" not in bf["display"], "bob: denied without value " + json.dumps(bf)[:300])
check("hamburg" not in db_.text.lower() and "Shoot" not in db_.text, "bob: the project's name appears nowhere in the answer")
check(bf["sources"] and bf["sources"][0]["label"] is None and bf["sources"][0]["denied"] is True, "bob: the source without label")
check(cell(db_.json(), "H4")["error"] is None and cell(db_.json(), "H4")["value"] == 160, "bob sees the client (same organisation)")
r = setv(Bo, SID, "H5", "=projekt.shoot_hamburg.offen")
check(r.status_code == 400, "bob cannot choose a project he does not see")
r = setv(Bo, SID, "H1", bf["raw"] + "+0")
check(r.ok, "bob may edit a formula that keeps a source chosen before " + r.text[:200])
check(cell(get(A, SID), "H1")["value"] == 1.5, "... and it still counts for alice")
check(all("hamburg" not in v["token"] for v in Bo.get(B + f"/api/sheets/{SID}/vars?q=shoot").json()["vars"]), "bob's completion has no project he does not see")
vs = A.get(B + f"/api/sheets/{SID}/vars?q=shoot").json()["vars"]
check(any(v["token"] == "projekt.shoot_hamburg.zeit_gesamt" and v["kind"] == "project" for v in vs), "alice's completion offers the project")
check(any(v["kind"] == "function" for v in A.get(B + f"/api/sheets/{SID}/vars").json()["vars"]), "completion offers the functions")
# a private project cannot go into the organisation's table
PP = A.post(B + "/api/lists", json={"name": "Own Stuff", "kind": "project", "org_id": None}).json()["id"]
check(setv(A, SID, "H6", "=projekt.own_stuff.offen").status_code == 400, "a private project in an organisation's table: 400")
check(setv(A, SID, "H6", "={p:%d}.offen" % PP).status_code == 400, "... also as a bare id")
# freezing keeps a copy
f1id = cell(get(A, SID), "H1")["id"]
r = A.post(B + f"/api/sheets/{SID}/cells/{f1id}/freeze", json={"frozen": True})
check(r.ok and r.json()["cell"]["origin"] == "frozen" and r.json()["cell"]["value"] == 1.5, "frozen " + r.text[:300])
A.post(B + "/api/time/entries", json={"list_id": P, "start": "2026-10-02T09:00:00Z", "minutes": 30})
check(cell(get(A, SID), "H1")["value"] == 1.5 and cell(get(A, SID), "H2")["value"] == 2, "a frozen cell keeps its value")
check(cell(get(A, SID), "H3")["value"] == 2, "the others still count")
A.post(B + f"/api/sheets/{SID}/cells/{f1id}/freeze", json={"frozen": False})
check(cell(get(A, SID), "H1")["value"] == 2, "thawed: calculated again (2 hours)")
# the project deleted: "deleted" + the last value for whoever saw it
A.patch(B + f"/api/lists/{P}", json={"archived": True})
r = A.delete(B + f"/api/lists/{P}")
check(r.ok, "project deleted " + r.text[:200])
d = get(A, SID)
check(cell(d, "H1")["error"] == "deleted" and cell(d, "H1")["last_value"] == "2", "alice: deleted + her last value " + json.dumps(cell(d, "H1"))[:300])
bf = cell(get(Bo, SID), "H1")
check(bf["error"] == "deleted" and bf["last_value"] is None, "bob: deleted, no last value (he never saw it)")

# ---- a table attached to a list follows the list
W = A.post(B + "/api/lists", json={"name": "Garden", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{W}/members", json={"user_id": uid["bob"], "role": "edit"})
A.put(B + f"/api/lists/{W}/members", json={"user_id": uid["carol"], "role": "view"})
for t in ("Dig", "Plant"):
    A.post(B + "/api/tasks", json={"title": t, "list_id": W})
r = A.post(B + "/api/sheets", json={"title": "Garden sheet", "space": f"org:{ORG}", "list_id": W})
check(r.status_code == 201 and r.json()["list_id"] == W and r.json()["list_title"] == "Garden", "attached to a list " + r.text[:200])
LS = r.json()["id"]
check(setv(A, LS, "A1", "=hier.aufgaben").ok and cell(get(A, LS), "A1")["value"] == 2, "hier.aufgaben = 2")
check(setv(Bo, LS, "A2", "5").ok, "a member who edits the list writes")
check(Ca.get(B + f"/api/sheets/{LS}").status_code == 200 and get(Ca, LS)["can_write"] is False, "a reader of the list reads, can_write false")
check(setv(Ca, LS, "A3", "1").status_code == 403, "a reader of the list cannot write: 403")
check(Er.get(B + f"/api/sheets/{LS}").status_code == 404, "a member of the organisation who does not see the list: 404")
check(any(x["id"] == LS for x in Bo.get(B + f"/api/sheets?list_id={W}").json()["sheets"]), "the list's tables")
check(Er.get(B + f"/api/sheets?list_id={W}").status_code == 404, "the list's tables: 404 without the list")
check(setv(A, SID, "C9", "=hier.offen").status_code == 400, "hier in a table without a list: 400")
FL = Fr.post(B + "/api/lists", json={"name": "Beta plans", "org_id": BETA}).json()["id"]
check(A.post(B + "/api/sheets", json={"title": "x", "space": f"org:{ORG}", "list_id": FL}).status_code == 404, "attaching another organisation's list: 404")
PRIV = A.post(B + "/api/lists", json={"name": "Private list", "org_id": None}).json()["id"]
check(A.post(B + "/api/sheets", json={"title": "x", "space": f"org:{ORG}", "list_id": PRIV}).status_code == 400, "a private list on an organisation's table: 400")
check(Bo.patch(B + f"/api/sheets/{LS}", json={"list_id": None}).status_code == 403, "a member who edits may not detach (that opens it to the space)")
check(Bo.patch(B + f"/api/sheets/{LS}", json={"title": "Garden plan"}).ok, "... but rename it")

# ---- a private table: its owner only
r = A.post(B + "/api/sheets", json={"title": "Mine", "space": "private"})
MS = r.json()["id"]
check(r.status_code == 201 and r.json()["space"] == "private", "a private table")
check(Bo.get(B + f"/api/sheets/{MS}").status_code == 404 and setv(Bo, MS, "A1", "1").status_code == 404, "another person: 404")
check(all(x["id"] != MS for x in Bo.get(B + "/api/sheets?space=all").json()["sheets"]), "not in another person's index")
check(any(x["id"] == MS for x in A.get(B + "/api/sheets?space=private").json()["sheets"]), "in the owner's private index")
check(setv(A, MS, "A1", "=projekt.own_stuff.offen").ok, "a private project in a private table")
check(Fr.get(B + f"/api/sheets?space=org:{ORG}").status_code == 404, "the index of another organisation's space: 404")

# ---- presence
c = cell(get(A, SID), "A2")
check(Bo.post(B + f"/api/sheets/{SID}/presence", json={"cell_id": c["id"]}).ok, "bob is in a cell")
pr = get(A, SID)["presence"]
check(any(p["user_id"] == uid["bob"] and p["cell_id"] == c["id"] and p["name"] == "Bob" for p in pr), "alice sees bob's cell")
check(all(p["user_id"] != uid["bob"] for p in get(Bo, SID)["presence"]), "bob does not see himself")
check(Bo.post(B + f"/api/sheets/{SID}/presence", json={"cell_id": 999999999}).status_code == 400, "presence in a foreign cell: 400")
check(A.post(B + f"/api/sheets/{SID}/batches/nope/undo").status_code == 404, "undo of an unknown batch: 404")

# ---- trash + restore of the table
check(Bo.delete(B + f"/api/sheets/{SID}").ok, "a member moves the table to the trash")
check(A.get(B + f"/api/sheets/{SID}").status_code == 404, "trashed: 404")
check(Fr.post(B + f"/api/sheets/{SID}/restore").status_code == 404, "another organisation cannot restore")
check(A.post(B + f"/api/sheets/{SID}/restore").ok and A.get(B + f"/api/sheets/{SID}").status_code == 200, "restored")
check(A.patch(B + f"/api/sheets/{SID}", json={"title": "Budget 2027"}).json()["title"] == "Budget 2027", "renamed")

# ---- a person without an organisation: everything in the private space
r = Da.post(B + "/api/sheets", json={"title": "Freelance", "space": "private"})
check(r.status_code == 201, "dave creates a private table " + r.text[:200])
DS = r.json()["id"]
DP = Da.post(B + "/api/lists", json={"name": "Client Job", "kind": "project"}).json()["id"]
Da.post(B + "/api/tasks", json={"title": "Pitch", "list_id": DP})
check(setv(Da, DS, "A1", "8").ok and setv(Da, DS, "A2", "=A1*95").ok, "dave calculates")
check(setv(Da, DS, "A3", "=projekt.client_job.offen").ok and cell(get(Da, DS), "A3")["value"] == 1, "dave's project variable")
check(Da.post(B + "/api/sheets", json={"title": "x", "space": f"org:{ORG}"}).status_code == 404, "dave: no organisation space")
check(A.get(B + f"/api/sheets/{DS}").status_code == 404, "the admin does not read dave's private table")
check(Da.post(B + f"/api/sheets/{DS}/columns", json={"title": "Note", "kind": "text"}).status_code == 201, "dave adds a column")

# ---- 2.89.0 (#1916, leader): the account export carries a person's private tables, never an organisation's
import io, json as _json, time as _time, zipfile  # noqa: E402
Da.post(B + "/api/account/export")
st = {}
for _ in range(240):
    st = Da.get(B + "/api/account/export").json()
    if st.get("state") != "running":
        break
    _time.sleep(0.25)
zf = zipfile.ZipFile(io.BytesIO(Da.get(B + "/api/account/export/file").content)) if st.get("state") == "done" else None
def _rows(name):
    if not zf or f"data/{name}.json" not in zf.namelist():
        return None
    d = _json.loads(zf.read(f"data/{name}.json"))
    return d.get("rows", d) if isinstance(d, dict) else d
xs, xc = _rows("sheets"), _rows("sheet_cells")
check(isinstance(xs, list) and {x.get("id") for x in xs} == {DS} and isinstance(xc, list) and len(xc) >= 3,
      f"account export: dave's private table with its cells ({st.get('state')}, {xs if xs is None else len(xs)})")

# ---- 2.89.0 (#1916): review 1 - "&" chains cannot blow text up (each doubling cell would double the text)
RS = A.post(B + "/api/sheets", json={"title": "Review texts", "space": "private"}).json()["id"]
A.post(B + f"/api/sheets/{RS}/rows", json={"count": 14})
_t0 = _time.time()
r = put(A, RS, [{"cell": "A1", "raw": "x" * 10000}] + [{"cell": f"A{i}", "raw": f"=A{i - 1}&A{i - 1}"} for i in range(2, 23)])
check(r.ok, "review 1: the doubling chain is saved " + r.text[:200])
_t0 = _time.time()
d = A.get(B + f"/api/sheets/{RS}")
check(d.ok and _time.time() - _t0 < 10, f"review 1: GET answers quickly ({_time.time() - _t0:.1f} s)")
a2, a22 = cell(d.json(), "A2") or {}, cell(d.json(), "A22") or {}
check(a2.get("error") == "type" and a2.get("value") is None and "10000" in (a2.get("error_text") or "").replace(".", "").replace(",", ""),
      "review 1: the cell over the limit shows 'text too long' " + json.dumps(a2)[:200])
check(a22.get("error") == "type" and a22.get("value") is None, "review 1: ... and the cells built on it an error " + json.dumps(a22)[:200])
check(len(d.text) < 2_000_000, f"review 1: the answer stays small ({len(d.text)} bytes)")
check(setv(A, RS, "B1", "=1+1").ok, "review 1: saving afterwards works")

# ---- 2.89.0 (#1916): review 3 - a range over the whole sheet visits the cells that exist, not every position
_csv = (";".join(f"c{i}" for i in range(1, 201)) + "\r\n" + ";".join(str(i) for i in range(1, 201)) + "\r\n").encode()
r = A.post(B + "/api/sheets/import", data={"space": "private", "title": "Review range"}, files={"file": ("wide.csv", _csv)})
check(r.status_code == 201, "review 3: a table with 200 columns " + r.text[:200])
RR = r.json()["sheet"]["id"]
check(A.post(B + f"/api/sheets/{RR}/rows", json={"count": 4999}).ok, "review 3: ... and 5000 rows")
_t0 = _time.time()
r = put(A, RR, [{"cell": f"B{i}", "raw": "=SUMME(A1:GR5000)"} for i in range(2, 42)] + [{"cell": "A3", "raw": "=SUMME(A1:GR1)"}])
check(r.ok and _time.time() - _t0 < 15, f"review 3: 40 formulas over A1:GR5000 saved quickly ({_time.time() - _t0:.1f} s) " + r.text[:200])
_t0 = _time.time()
d = A.get(B + f"/api/sheets/{RR}")
check(d.ok and _time.time() - _t0 < 10, f"review 3: GET answers quickly ({_time.time() - _t0:.1f} s)")
check((cell(d.json(), "A3") or {}).get("value") == 20100, "review 3: the sum of a range is still right " + json.dumps(cell(d.json(), "A3"))[:200])

# ---- 2.89.0 (#1916): review 4 - deep nesting is a formula error (400), never a 500
RN = A.post(B + "/api/sheets", json={"title": "Review nesting", "space": "private"}).json()["id"]
for raw, what in (("=" + "(" * 300 + "1" + ")" * 300, "300 brackets"), ("=" + "-" * 2000 + "1", "2000 minus signs"),
                  ("=" + "+".join(["1"] * 400), "400 terms in a chain"), ("=" + "SUMME(" * 100 + "1" + ")" * 100, "100 functions")):
    r = setv(A, RN, "A1", raw)
    check(r.status_code == 400 and "error" in r.json(), f"review 4: {what}: 400 " + str(r.status_code) + " " + r.text[:120])
r = setv(A, RN, "A2", "=" + "(" * 40 + "2" + ")" * 40 + "+" + "+".join(["1"] * 100))
check(r.ok and (cell(get(A, RN), "A2") or {}).get("value") == 102, "review 4: 40 brackets and 100 terms still work " + r.text[:200])
_csv = ("Formel\r\n=" + "(" * 300 + "1" + ")" * 300 + "\r\n").encode()
r = A.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("deep.csv", _csv)})
check(r.status_code in (201, 400), "review 4: importing a deep formula: no 500 " + str(r.status_code))

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
