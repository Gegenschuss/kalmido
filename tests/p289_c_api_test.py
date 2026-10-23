#!/usr/bin/env python3
"""2.89.0 API tests, part C (#1916): tables as files and for agents. Invented names only.
 - API v1 (scopes sheets:read / sheets:write): a team agent creates a table in one step (columns with choices + colours, rows,
   formulas, Kalmido variables), every call is one batch a person (or the agent itself) takes back; a sheet the call created
   goes to the trash; cells / rows / columns / vars / rename
 - the boundary (tenant-matrix: sheet_v1): an agent without a shared list sees nothing, an agent of another organisation
   nothing, a person's private or organisation table not attached to a shared list nothing, a variable of a list not shared
   with the agent is "denied" without value and name (and cannot be written by it); a person without an organisation (dave)
   with his own personal agent: what the agent creates is dave's, nobody else sees it
 - export: CSV (header, separator and decimal comma per language, BOM, formula injection guarded), .xlsx (well-formed parts,
   formulas in Excel form, a Kalmido variable as value + note, drop-down list, colours per option, styles); a stranger 404
 - import: the exported .xlsx back = the same values, kinds, choices and colours, formulas again formulas; CSV with decimal
   comma and dates; "=..." in a CSV stays text; broken / entity files 400; another workspace 404; the module off 409
 - the contacts of the REST API carry bday (the birthdays example of the agent docs)
usage: p289_c_api_test.py <datadir>      (a fresh container; P289C_NOSTART=1 = the server already runs)"""
# tenant-matrix: sheet_v1
import io
import os
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def feat_on(s):
    f = s.get(B + "/api/state").json()["settings"]["features"]
    s.patch(B + "/api/settings", json={"features": ",".join(x for x in (f + ",sheets,contacts").split(",") if x)})


def agent(name, scopes, org=None, owner=None):
    body = {"scopes": scopes, "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


def cells(d):
    return {x["addr"]: x for x in d["cells"]}


if not os.environ.get("P289C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "erin", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u in ("bob", "carol") else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["erin"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ca, Er, Da = sess("bob"), sess("carol"), sess("erin"), sess("dave")
for s in (A, Bo, Er, Da):
    feat_on(s)
Bo.patch(B + "/api/settings", json={"lang": "de"})
W = Bo.post(B + "/api/lists", json={"name": "Garden", "org_id": ORG}).json()["id"]
SEC = Bo.post(B + "/api/lists", json={"name": "Secret plan", "org_id": ORG}).json()["id"]
t1 = Bo.post(B + "/api/tasks", json={"title": "Dig", "list_id": W}).json()["id"]
t2 = Bo.post(B + "/api/tasks", json={"title": "Plant", "list_id": W}).json()["id"]
Bo.post(B + f"/api/tasks/{t2}/complete")
for i in range(3):
    Bo.post(B + "/api/tasks", json={"title": f"Hidden {i}", "list_id": SEC})
SW = ["read", "sheets:read", "sheets:write"]
TA, ta = agent("gardenbot", SW + ["contacts"], org=ORG)
NA, na = agent("idlebot", SW, org=ORG)
BB, bb = agent("betabot", SW, org=BETA)
RO, ro = agent("readbot", ["read", "sheets:read"], org=ORG)
X0, x0 = agent("plainbot", ["read", "tasks:write"], org=ORG)
DA, da = agent("davebot", SW, owner=uid["dave"])
check(Bo.put(B + f"/api/lists/{W}/members", json={"user_id": TA, "role": "edit"}).ok, "setup: the garden list shared with the agent")
W2 = Bo.post(B + "/api/lists", json={"name": "Orchard", "org_id": ORG}).json()["id"]  # one agent per list
check(Bo.put(B + f"/api/lists/{W2}/members", json={"user_id": RO, "role": "view"}).ok, "setup: the read agent reads another list")

# ================================================================== API v1: create in one step, batches
check(x0.get(V + "/sheets").status_code == 403, "without sheets:read: 403")
COLS = [{"title": "Posten"}, {"title": "Stunden", "kind": "number"}, {"title": "Satz", "kind": "currency"},
        {"title": "Betrag", "kind": "currency"},
        {"title": "Status", "kind": "select", "color_mode": "row",
         "options": [{"label": "Offen", "color": "#f5b041"}, {"label": "Fix", "color": "#58d68d"}]},
        {"title": "Offen", "kind": "number"}]
ROWS = [["Kamera", 10, 95, "=B1*C1", "Offen", "=liste.garden.offen"],
        ["Schnitt", "16", "80,5", "=B2*C2", "Fix", "=hier.offen"],
        ["Summe", "", "", "=SUMME(D1:D2)", "", ""]]
r = ta.post(V + "/sheets", json={"title": "Angebot Garten", "space": f"org:{ORG}", "list_id": W, "columns": COLS, "rows": ROWS})
check(r.status_code == 201, "an agent creates a table in one step " + r.text[:300])
S1 = r.json()
SID, BATCH0 = S1["id"], S1.get("batch") or ""
c1 = cells(S1)
check(BATCH0.startswith("a") and S1["list_id"] == W, "the answer carries the batch and the list " + str(BATCH0))
check(c1.get("D1", {}).get("value") == 950 and c1.get("D2", {}).get("value") == 1288 and c1.get("D3", {}).get("value") == 2238,
      "formulas calculated " + str({k: c1.get(k, {}).get("value") for k in ("D1", "D2", "D3")}))
check(c1.get("F1", {}).get("value") == 1 and c1.get("F1", {}).get("origin") == "kalmido", "liste.garden.offen = 1 open task " + str(c1.get("F1")))
check(c1.get("F2", {}).get("value") == 1, "hier.offen = the attached list " + str(c1.get("F2")))
check(c1.get("E1", {}).get("display") == "Offen" and (c1["E1"].get("agent") or {}).get("batch") == BATCH0, "a choice by label, the cell marked with the agent")
check(c1.get("D1", {}).get("raw") == "=B1*C1" and c1.get("F1", {}).get("raw") == "=liste.garden.offen", "formulas shown with names")
check(S1["columns"][4]["color_mode"] == "row" and S1["columns"][4]["options"][0]["color"] == "#f5b041", "choices with colours, colour per row")
r = Bo.get(B + f"/api/sheets/{SID}")
check(r.ok and r.json()["batches"] and r.json()["batches"][0]["agent_id"] == TA, "the person sees the table and the agent's call " + r.text[:200])
check(SID in [x["id"] for x in ta.get(V + "/sheets").json()["data"]], "the agent lists its table")
check(SID in [x["id"] for x in ta.get(V + "/sheets", params={"list_id": W}).json()["data"]], "the agent lists the tables of the shared list")

# cells, undo by the person, undo by the agent
r = ta.put(V + f"/sheets/{SID}/cells", json={"cells": [{"cell": "B1", "raw": "12"}]})
b2 = r.json().get("batch")
check(r.ok and b2 and b2 != BATCH0, "set cells: a new batch " + r.text[:200])
check(any(x["addr"] == "D1" and x["value"] == 1140 for x in r.json()["cells"]), "the depending cell comes along")
r = Bo.post(B + f"/api/sheets/{SID}/batches/{b2}/undo")
check(r.ok, "the person takes the agent's call back " + r.text[:200])
check(cells(Bo.get(B + f"/api/sheets/{SID}").json())["B1"]["value"] == 10, "the former input is back")
r = ta.put(V + f"/sheets/{SID}/cells", json={"cells": [{"cell": "A1", "raw": "Kamera A"}]})
b3 = r.json().get("batch")
check(ta.post(V + f"/sheets/{SID}/batches/{b3}/undo").json().get("undone") == 1, "the agent takes back its own call")
check(cells(ta.get(V + f"/sheets/{SID}").json())["A1"]["value"] == "Kamera", "... the cell is as before")
check(ta.post(V + f"/sheets/{SID}/batches/a0000000000000000/undo").status_code == 404, "an unknown batch: 404")
check(ta.put(V + f"/sheets/{SID}/cells", json={"cells": [{"cell": "B9", "raw": "1"}]}).status_code == 400, "a cell that does not exist: 400")
check(ta.put(V + f"/sheets/{SID}/cells", json={"cells": [{"cell": "B1", "raw": "=SUMME(B1:"}]}).status_code == 400, "a broken formula: 400")
check(ta.put(V + f"/sheets/{SID}/cells", json={"cells": [{"cell": "A1", "raw": "x"}], "extra": 1}).status_code == 400, "an unknown field: 400")
r = ta.post(V + f"/sheets/{SID}/rows", json={"rows": [["Licht", 4, 60, "=B4*C4", "Neu", ""]]})
check(r.status_code == 201 and len(r.json()["row_ids"]) == 1 and r.json()["batch"], "append rows " + r.text[:200])
d = ta.get(V + f"/sheets/{SID}").json()
check(cells(d)["D4"]["value"] == 240 and [o["label"] for o in d["columns"][4]["options"]] == ["Offen", "Fix", "Neu"],
      "the new row is calculated, a new label became a choice")
r = ta.post(V + f"/sheets/{SID}/columns", json={"title": "Notiz", "kind": "text"})
check(r.status_code == 201 and r.json()["col_id"], "add a column " + r.text[:200])
check(ta.patch(V + f"/sheets/{SID}", json={"title": "Angebot Garten 2"}).json()["title"] == "Angebot Garten 2", "rename")
vs = ta.get(V + f"/sheets/{SID}/vars").json()["data"]
toks = {v["token"] for v in vs}
check("liste.garden.offen" in toks and "hier.offen" in toks, "vars: the shared list and hier")
check(not any("secret" in t for t in toks), "vars: never a list not shared with the agent")
S9 = Bo.post(B + "/api/sheets", json={"title": "Orchard", "space": f"org:{ORG}", "list_id": W2}).json()["id"]
check(ro.get(V + f"/sheets/{S9}").ok and ro.put(V + f"/sheets/{S9}/cells", json={"cells": [{"cell": "A1", "raw": "x"}]}).status_code == 403,
      "sheets:read only: reads, writes 403")
check(ro.get(V + f"/sheets/{SID}").status_code == 404, "another agent's list: 404")

# a table the agent created: one undo moves it to the trash
r = ta.post(V + "/sheets", json={"title": "Scratch", "space": f"org:{ORG}"})
S2, b4 = r.json()["id"], r.json()["batch"]
check(r.status_code == 201 and Bo.get(B + f"/api/sheets/{S2}").ok, "an agent's table in its workspace: the members see it")
check(ta.post(V + "/sheets", json={"title": "Mine", "space": "private"}).status_code == 400, "a team agent has no private space: 400")
r = ta.post(V + f"/sheets/{S2}/batches/{b4}/undo")
check(r.ok and ta.get(V + f"/sheets/{S2}").status_code == 404 and Bo.get(B + f"/api/sheets/{S2}").status_code == 404,
      "taking back the creating call: the table is in the trash " + r.text[:200])

# ================================================================== the boundary
r = Bo.post(B + "/api/sheets", json={"title": "Bob org", "space": f"org:{ORG}"})
S4 = r.json()["id"]
S5 = Bo.post(B + "/api/sheets", json={"title": "Bob private", "space": "private"}).json()["id"]
r = Bo.post(B + "/api/sheets", json={"title": "Bob garden", "space": f"org:{ORG}", "list_id": W})
S3 = r.json()["id"]
r = Bo.put(B + f"/api/sheets/{S3}/cells", json={"cells": [{"cell": "A1", "raw": "=liste.secret_plan.aufgaben"}, {"cell": "B1", "raw": "=A1*2"}]})
check(r.ok, "bob uses his hidden list in a formula " + r.text[:200])
cb = cells(Bo.get(B + f"/api/sheets/{S3}").json())
check(cb["A1"]["value"] == 3 and cb["B1"]["value"] == 6, "bob sees the value " + str(cb.get("A1")))
r = ta.get(V + f"/sheets/{S3}")
ct = cells(r.json())
check(r.ok and ct["A1"]["error"] == "denied" and ct["A1"]["value"] is None, "the agent: denied, no value " + str(ct.get("A1")))
check("secret" not in r.text.lower(), "the agent never sees the hidden list's name")
check(ta.put(V + f"/sheets/{S3}/cells", json={"cells": [{"cell": "C1", "raw": "=liste.secret_plan.offen"}]}).status_code == 400,
      "the agent cannot use a list not shared with it")
check(ta.put(V + f"/sheets/{S3}/cells", json={"cells": [{"cell": "C1", "raw": "={l:%d}.offen" % SEC}]}).status_code == 400,
      "... not even by its id")
ids = [x["id"] for x in ta.get(V + "/sheets").json()["data"]]
check(S3 in ids and S4 not in ids and S5 not in ids, "the agent lists only shared and own tables " + str(ids))
for sid_, what in ((S4, "an organisation table not attached"), (S5, "a person's private table")):
    check(ta.get(V + f"/sheets/{sid_}").status_code == 404, f"{what}: 404 for the agent")
    check(ta.put(V + f"/sheets/{sid_}/cells", json={"cells": [{"cell": "A1", "raw": "x"}]}).status_code == 404, f"{what}: no write (404)")
check(na.get(V + "/sheets").json()["data"] == [], "an agent without a shared list sees no table")
for path in (f"/sheets/{SID}", f"/sheets/{SID}/vars"):
    check(na.get(V + path).status_code == 404, f"an agent without a shared list: {path} 404")
    check(bb.get(V + path).status_code == 404, f"an agent of another organisation: {path} 404")
check(na.put(V + f"/sheets/{SID}/cells", json={"cells": [{"cell": "A1", "raw": "x"}]}).status_code == 404, "no share: no write")
check(bb.post(V + f"/sheets/{SID}/rows", json={"rows": 1}).status_code == 404, "another organisation: no rows")
check(bb.post(V + f"/sheets/{SID}/columns", json={"title": "x"}).status_code == 404, "another organisation: no columns")
check(bb.post(V + f"/sheets/{SID}/batches/{BATCH0}/undo").status_code == 404, "another organisation: no undo")
check(bb.post(V + "/sheets", json={"title": "x", "space": f"org:{ORG}"}).status_code == 404, "an agent cannot create in another workspace")
check(bb.post(V + "/sheets", json={"title": "x", "space": f"org:{BETA}", "list_id": W}).status_code == 404, "... nor attach a foreign list")
check(bb.get(V + "/sheets").json()["data"] == [], "an agent of another organisation lists nothing")
for path in (f"/api/sheets/{SID}/export.csv", f"/api/sheets/{SID}/export.xlsx", f"/api/sheets/{S5}/export.csv"):
    check(Er.get(B + path).status_code == 404, f"a stranger: {path} 404")
check(Ca.get(B + f"/api/sheets/{S5}/export.xlsx").status_code == 404, "a colleague: another person's private table 404")

# a person without an organisation and his own agent
# freelancer-matrix: sheets
r = da.post(V + "/sheets", json={"title": "Dave list", "columns": [{"title": "Name"}], "rows": [["Ann"]]})
S6 = r.json().get("id")
check(r.status_code == 201 and r.json()["space"] == "private", "dave's agent creates in dave's private space " + r.text[:200])
check(S6 in [x["id"] for x in Da.get(B + "/api/sheets", params={"space": "private"}).json()["sheets"]], "dave sees his agent's table")
check(A.get(B + f"/api/sheets/{S6}").status_code == 404 and Bo.get(B + f"/api/sheets/{S6}").status_code == 404, "nobody else sees it")
check(ta.get(V + f"/sheets/{S6}").status_code == 404, "another agent does not see it")
S7 = Da.post(B + "/api/sheets", json={"title": "Dave own", "space": "private"}).json()["id"]
check(da.get(V + f"/sheets/{S7}").status_code == 404, "dave's own table is not shared with his agent")
check(da.post(V + "/sheets", json={"title": "x", "space": f"org:{ORG}"}).status_code == 404, "dave's agent: no organisation")
check(Da.post(B + f"/api/sheets/{S6}/batches/{r.json()['batch']}/undo").ok and da.get(V + f"/sheets/{S6}").status_code == 404,
      "dave takes his agent's table back")

# ================================================================== export
r = Bo.get(B + f"/api/sheets/{SID}/export.csv")
check(r.ok and r.content.startswith(b"\xef\xbb\xbf") and "text/csv" in r.headers.get("Content-Type", ""), "CSV with BOM")
lines = r.content.decode("utf-8-sig").split("\r\n")
check(lines[0] == "Posten;Stunden;Satz;Betrag;Status;Offen;Notiz", "CSV header, ';' in German " + lines[0])
check(lines[2].startswith("Schnitt;16;80,5;1288;Fix;1"), "CSV values with the decimal comma " + lines[2])
S8 = Bo.post(B + "/api/sheets", json={"title": "Inject", "space": "private"}).json()["id"]
d8 = Bo.get(B + f"/api/sheets/{S8}").json()
Bo.patch(B + f"/api/sheets/{S8}/columns/{d8['columns'][1]['id']}", json={"kind": "number"})
Bo.put(B + f"/api/sheets/{S8}/cells", json={"cells": [{"cell": "A1", "raw": "+1+1"}, {"cell": "A2", "raw": "@SUM(A1)"}, {"cell": "A3", "raw": "-x"},
                                                      {"cell": "B1", "raw": "-5"}]})
txt = Bo.get(B + f"/api/sheets/{S8}/export.csv").content.decode("utf-8-sig")
check("'+1+1" in txt and "'@SUM(A1)" in txt and "'-x" in txt, "CSV: text a spreadsheet would run gets a ' " + txt[:200])
check(";-5" in txt and "'-5" not in txt, "CSV: a negative number stays a number")
A.patch(B + "/api/settings", json={"lang": "en"})

r = Bo.get(B + f"/api/sheets/{SID}/export.xlsx")
check(r.ok and r.content.startswith(b"PK") and "spreadsheetml" in r.headers.get("Content-Type", ""), "xlsx download")
XL = r.content
z = zipfile.ZipFile(io.BytesIO(XL))
parts = {}
for n in z.namelist():
    if n.endswith((".xml", ".rels", ".vml")):
        try:
            parts[n] = ET.fromstring(z.read(n))
        except ET.ParseError as e:
            check(False, f"xlsx part {n} is well-formed: {e}")
check({"[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml", "xl/worksheets/sheet1.xml", "xl/comments1.xml",
       "xl/drawings/vmlDrawing1.vml"} <= set(parts), "xlsx parts " + str(sorted(parts)))
ws = parts["xl/worksheets/sheet1.xml"]
fx = {c.get("r"): c.find(NS + "f").text for c in ws.iter(NS + "c") if c.find(NS + "f") is not None}
vals = {c.get("r"): (c.find(NS + "v").text if c.find(NS + "v") is not None else None) for c in ws.iter(NS + "c")}
check(fx.get("D2") == "B2*C2" and fx.get("D4") == "SUM(D2:D3)", "formulas in Excel form (header row 1) " + str(fx))
check("F2" not in fx and vals.get("F2") == "1", "a Kalmido variable as its value")
check("liste.garden.offen" in z.read("xl/comments1.xml").decode(), "... with a note naming it")
check(vals.get("D2") == "950", "the formula's value is stored too")
dv = [x for x in ws.iter(NS + "dataValidation")]
check(dv and dv[0].get("type") == "list" and dv[0].find(NS + "formula1").text == '"Offen,Fix,Neu"' and dv[0].get("sqref").startswith("E2:E"),
      "the select column as a drop-down list")
cf = [x for x in ws.iter(NS + "cfRule")]
check(any(x.get("type") == "expression" and x.find(NS + "formula").text == '$E2="Offen"' for x in cf), "colour of the whole row per choice")
st = z.read("xl/styles.xml").decode()
check("<dxf>" in st and "FFF5B041" in st and 'numFmtId="164"' in st, "fills of the choices + the currency format")
order = [x.tag.replace(NS, "") for x in ws]
check(order.index("sheetData") < order.index("conditionalFormatting") < order.index("dataValidations") < order.index("legacyDrawing"),
      "the worksheet's parts in schema order " + str(order))

# ================================================================== import
r = Bo.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("Angebot.xlsx", XL)})
check(r.status_code == 201, "import the exported xlsx " + r.text[:300])
IM = r.json()["sheet"]["id"]
rep = r.json()["report"]
check(r.json()["sheet"]["title"] == "Angebot" and rep["formulas"] >= 4, "title from the file name, formulas taken over " + str(rep))
d = Bo.get(B + f"/api/sheets/{IM}").json()
ci = cells(d)
check([c["title"] for c in d["columns"]] == ["Posten", "Stunden", "Satz", "Betrag", "Status", "Offen", "Notiz"], "titles back")
check([c["kind"] for c in d["columns"]][:6] == ["text", "number", "currency", "currency", "select", "number"],
      "kinds back " + str([c["kind"] for c in d["columns"]]))
check([(o["label"], o["color"]) for o in d["columns"][4]["options"]][:2] == [("Offen", "#f5b041"), ("Fix", "#58d68d")]
      and d["columns"][4]["color_mode"] == "row", "choices + colours + colour per row back")
check(ci["D1"]["raw"] == "=B1*C1" and ci["D1"]["value"] == 950 and ci["D3"]["raw"] == "=SUMME(D1:D2)" and ci["D3"]["value"] == 2238,
      "formulas back as formulas " + str((ci["D1"]["raw"], ci["D3"]["raw"])))
check(ci["F1"]["value"] == 1 and ci["F1"]["origin"] == "own" and ci["E2"]["display"] == "Fix", "a variable's value as a value, choices")
csv_in = "Name;Betrag;Datum\r\nKabel;12,50;18.10.2026\r\nStativ;1.234,00;01.11.2026\r\n=HYPERLINK(\"http://example.com\");3;\r\n".encode()
r = Bo.post(B + "/api/sheets/import", data={"space": "private", "title": "Material"}, files={"file": ("m.csv", csv_in)})
check(r.status_code == 201, "import a CSV " + r.text[:300])
d = Bo.get(B + f"/api/sheets/{r.json()['sheet']['id']}").json()
ci = cells(d)
check([c["kind"] for c in d["columns"]] == ["text", "number", "date"], "CSV kinds " + str([c["kind"] for c in d["columns"]]))
check(ci["B2"]["value"] == 1234 and ci["C1"]["value"] == "2026-10-18", "CSV numbers and dates " + str((ci["B2"]["value"], ci["C1"]["value"])))
check(ci["A3"]["origin"] == "own" and ci["A3"]["raw"].startswith("'="), "'=' in a CSV stays text " + str(ci["A3"]))
bad = io.BytesIO()
with zipfile.ZipFile(bad, "w") as zz:
    zz.writestr("xl/workbook.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><workbook>&a;</workbook>')
check(Bo.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("x.xlsx", bad.getvalue())}).status_code == 400, "entities: 400")
check(Bo.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("x.xlsx", b"PK\x03\x04broken")}).status_code == 400, "a broken xlsx: 400")
check(Bo.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("x.pdf", b"%PDF-1.4")}).status_code == 400, "not a table: 400")
check(Bo.post(B + "/api/sheets/import", data={"space": f"org:{BETA}"}, files={"file": ("m.csv", csv_in)}).status_code == 404, "another workspace: 404")
check(Bo.post(B + "/api/sheets/import", data={"space": "private", "list_id": str(SEC)}, files={"file": ("m.csv", csv_in)}).status_code == 400,
      "a list of another space: 400")
check(Ca.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("m.csv", csv_in)}).status_code == 409, "the module off: 409")

# ================================================================== birthdays: contacts of the REST API carry bday
r = A.post(B + "/api/contacts", json={"given": "Ann", "family": "Example", "bday": "1990-11-02"})
check(r.ok, "a contact with a birthday " + r.text[:200])
tok = A.post(B + "/api/me/tokens", json={"name": "bday", "scopes": ["read", "contacts"]}).json().get("token")
r = bearer(tok or "x").get(V + "/contacts")
check(r.ok and any(x.get("bday") == "1990-11-02" for x in r.json().get("data", [])), "GET /api/v1/contacts has bday " + r.text[:200])

# ================================================================== 2.89.0 (#1916): review 2 - v1 PATCH list_id follows the web rule
r = Bo.post(B + "/api/sheets", json={"title": "Bound by bob", "space": f"org:{ORG}", "list_id": W})
RB = r.json()["id"]
check(ta.get(V + f"/sheets/{RB}").ok, "review 2: the team agent sees bob's table on the shared list")
check(ta.patch(V + f"/sheets/{RB}", json={"list_id": None}).status_code == 403, "review 2: the agent cannot detach a table it did not create")
check(Bo.get(B + f"/api/sheets/{RB}").json()["list_id"] == W, "review 2: ... the table stays attached")
check(ta.patch(V + f"/sheets/{RB}", json={"title": "Renamed by agent"}).ok, "review 2: renaming stays allowed")
r = ta.post(V + "/sheets", json={"title": "Own bound", "space": f"org:{ORG}", "list_id": W})
check(r.status_code == 201 and ta.patch(V + f"/sheets/{r.json()['id']}", json={"list_id": None}).ok,
      "review 2: the agent detaches a table it created itself")

# ================================================================== 2.89.0 (#1916): review 5 - an xlsx import counts its cells while reading
_big = io.BytesIO()
with zipfile.ZipFile(io.BytesIO(XL)) as zin, zipfile.ZipFile(_big, "w", zipfile.ZIP_DEFLATED) as zout:
    for n in zin.namelist():
        if n == "xl/worksheets/sheet1.xml":
            rows_x = "".join(f'<row r="{r}">' + "".join(f'<c r="{chr(64 + k // 26) if k >= 26 else ""}{chr(65 + k % 26)}{r}"><v>{k}</v></c>'
                                                         for k in range(200)) + "</row>" for r in range(1, 262))
            zout.writestr(n, '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                             f"<sheetData>{rows_x}</sheetData></worksheet>")
        else:
            zout.writestr(n, zin.read(n))
r = A.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("big.xlsx", _big.getvalue())})
check(r.status_code == 400 and "cells" in r.text.lower(), "review 5: 52 200 filled cells: 400 with a clear message " + str(r.status_code) + r.text[:150])

# ================================================================== 2.89.0 (#1916): review 6 - control characters do not break the xlsx
S9 = Bo.post(B + "/api/sheets", json={"title": "Ctl", "space": "private"}).json()["id"]
Bo.put(B + f"/api/sheets/{S9}/cells", json={"cells": [{"cell": "A1", "raw": "a\x01b\x1fc"}, {"cell": "A2", "raw": '="x\x02"&A1'}]})
r = Bo.get(B + f"/api/sheets/{S9}/export.xlsx")
ok6 = r.ok
if ok6:
    z9 = zipfile.ZipFile(io.BytesIO(r.content))
    for n in z9.namelist():
        if n.endswith((".xml", ".rels", ".vml")):
            try:
                ET.fromstring(z9.read(n))
            except ET.ParseError as e:
                ok6 = False
                check(False, f"review 6: xlsx part {n} is well-formed: {e}")
check(ok6, "review 6: a cell with \\x01: the export is well-formed XML " + str(r.status_code))

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
