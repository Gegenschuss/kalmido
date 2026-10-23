#!/usr/bin/env python3
"""2.124.0 API tests, part A (#2109 #2115): the new formula functions of tables and the simple chart. Invented names only, the
.xlsx is generated here.
 - SUMMEWENN/SUMIF, ZÄHLENWENN/COUNTIF with criteria (text in any case, wildcards, ">5", "<>x", "<=date", empty), with and
   without a sum range; SVERWEIS/VLOOKUP exact (default) and approximate (WAHR), not found = "na", a column outside = "ref";
   XVERWEIS/XLOOKUP down a column and along a row, with "if not found"; German and English names
 - text: LINKS/LEFT, RECHTS/RIGHT, TEIL/MID, LÄNGE/LEN, VERKETTEN/CONCAT (also a range), GLÄTTEN/TRIM, GROSS/UPPER,
   KLEIN/LOWER, & still works; date: DATUM/DATE (overflowing months / days), JAHR, MONAT, TAG, EDATUM (month end), HEUTE
   computed per request; type errors instead of a 500, an unknown function 400
 - a column called "Tag" stays usable by its name next to the function TAG(); the completion offers the new functions
 - import of an .xlsx with SUMIF / VLOOKUP (3 and 4 arguments) / XLOOKUP / LEFT / UPPER: formulas again, VLOOKUP without its
   4th argument gets WAHR; the export writes them back as Excel formulas (a Kalmido VLOOKUP with 3 arguments gets FALSE)
 - the chart (#2115): no chart = null; save / read / change / remove (PUT /api/sheets/<id>/chart), bad kind / columns 400,
   a reader of the list sees it and gets 403, another organisation 404, the agents' GET has it too
 - a person without an organisation uses functions and the chart in the private space
tenant-matrix: sheet
freelancer-matrix: sheets
usage: p2124_a_api_test.py <datadir>      (a fresh container; P2124A_NOSTART=1 = the server already runs)"""
import io
import json
import time
import os
import subprocess
import sys
import zipfile
from datetime import date

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
import testclock  # noqa: E402  (2.192.0 A, #2512: the group's test time, run_all.sh `now`)

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "sheets,collab,comments"


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


def put(s, sid, cells):
    return s.put(B + f"/api/sheets/{sid}/cells", json={"cells": cells})


def get(s, sid):
    return s.get(B + f"/api/sheets/{sid}").json()


def cell(d, addr):
    return next((x for x in d["cells"] if x["addr"] == addr), None) or {}


if not os.environ.get("P2124A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "frank" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
Bo, Ca, Fr = sess("bob"), sess("carol"), sess("frank")
for s in (A, Bo, Ca, Fr):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})

# ================================================================== #2109 functions
r = A.post(B + "/api/sheets", json={"title": "Fruit", "space": f"org:{ORG}"})
check(r.status_code == 201, "a table " + r.text[:200])
S = r.json()
SID = S["id"]
check(S.get("chart", "missing") is None, "a table without a chart answers chart: null (the view stays as before)")
for _ in range(3):
    A.post(B + f"/api/sheets/{SID}/columns", json={"title": "", "kind": "text"})  # D, E, F
data = [("A1", "Apple"), ("A2", "Pear"), ("A3", "Cherry"), ("A4", "apple"),
        ("B1", "5"), ("B2", "10"), ("B3", "3"), ("B4", "7"),
        ("C1", "open"), ("C2", "done"), ("C3", "open"), ("C4", "open"),
        ("E1", "2026-01-10"), ("E2", "2026-03-01"), ("E3", "2026-01-31")]
r = put(A, SID, [{"cell": a, "raw": v} for a, v in data])
check(r.ok, "the values " + r.text[:200])

F = {  # address: (formula, expected value | ("err", kind))
    "D1": ('=SUMMEWENN(A1:A4;"apple";B1:B4)', 12),
    "D2": ('=SUMIF(B1:B4;">5")', 17),
    "D3": ('=ZÄHLENWENN(C1:C4;"open")', 3),
    "D4": ('=COUNTIF(A1:A4;"?ear")', 1),
    "D5": ('=ZÄHLENWENN(A1:A5;"<>apple")', 3),  # Pear, Cherry and the empty A5
    "D6": ('=COUNTIF(A1:A4;"*r*")', 2),  # Pear, Cherry
    "D7": ('=SVERWEIS("cherry";A1:C4;2;FALSCH)', 3),
    "D8": ('=VLOOKUP("Mango";A1:C4;2;0)', ("err", "na")),
    "D9": ('=SVERWEIS("Pear";A1:C4;5)', ("err", "ref")),
    "D10": ('=XVERWEIS("Pear";A1:A4;C1:C4)', "done"),
    "F1": ('=XLOOKUP("Mango";A1:A4;C1:C4;"none")', "none"),
    "F2": ('=XVERWEIS("Mango";A1:A4;C1:C4)', ("err", "na")),
    "F3": ('=ZÄHLENWENN(E1:E3;"<=2026-02-01")', 2),
    "F4": ('=SUMMEWENN(C1:C4;"open";B1:B4)+ZÄHLENWENN(C1:C4;"=")', 15),
    "F5": ('=SUMMEWENN(5;">1")', ("err", "type")),
    "F6": ('=LÄNGE()', ("err", "syntax")),
}
r = put(A, SID, [{"cell": a, "raw": f} for a, (f, _v) in F.items()])
check(r.ok, "the formulas are taken " + r.text[:300])
d = get(A, SID)
for a, (f, want) in F.items():
    x = cell(d, a)
    if isinstance(want, tuple):
        check(x.get("error") == want[1] and x.get("value") is None, f"{f}: error {want[1]} " + json.dumps(x)[:200])
    else:
        check(x.get("value") == want and not x.get("error"), f"{f} = {want!r} " + json.dumps(x)[:200])
check(cell(d, "D8").get("error_text") == "Not found", "not found reads 'Not found' " + str(cell(d, "D8").get("error_text")))
check(cell(d, "D7").get("raw") == '=SVERWEIS("cherry";A1:C4;2;FALSCH)', "the formula shows as typed")
# a change answers the lookups that read it
r = put(A, SID, [{"cell": "B3", "raw": "4"}])
check(r.ok and any(x["addr"] == "D7" and x["value"] == 4 for x in r.json()["cells"]), "changing B3 answers the SVERWEIS again " + r.text[:300])
check(put(A, SID, [{"cell": "D8", "raw": "=FOO(1)"}]).status_code == 400, "an unknown function: 400")
# 2.124.0 review: wildcards match without backtracking (a long cell and many * answered at once)
t0 = time.time()
r = put(A, SID, [{"cell": "A6", "raw": "a" * 3000}, {"cell": "F7", "raw": '=ZÄHLENWENN(A1:A6;"*a*a*a*a*a*a*b")'},
                 {"cell": "F8", "raw": '=COUNTIF(A1:A6;"*a*a*a*a*a*a")'}])
d = get(A, SID)
check(r.ok and cell(d, "F7").get("value") == 0 and cell(d, "F8").get("value") == 1 and time.time() - t0 < 10,
      "wildcards on a 3000-character cell: fast " + json.dumps(cell(d, "F8"))[:200])

# approximate lookup, text, dates, errors -- a second table
r = A.post(B + "/api/sheets", json={"title": "Misc", "space": f"org:{ORG}"})
T2 = r.json()["id"]
put(A, T2, [{"cell": "A1", "raw": "0"}, {"cell": "A2", "raw": "100"}, {"cell": "A3", "raw": "500"},
            {"cell": "B1", "raw": "low"}, {"cell": "B2", "raw": "mid"}, {"cell": "B3", "raw": "high"}])
G = [
    ('=SVERWEIS(250;A1:B3;2;WAHR)', "mid"), ('=VLOOKUP(500;A1:B3;2;TRUE)', "high"), ('=SVERWEIS(-1;A1:B3;2;WAHR)', ("err", "na")),
    ('=XLOOKUP(100;A1:A3;B1:B3)', "mid"),
    ('=LINKS("Kalmido";3)', "Kal"), ('=LEFT("Kalmido")', "K"), ('=RECHTS("Kalmido";2)', "do"), ('=RIGHT("Kalmido";0)', ""),
    ('=TEIL("Kalmido";2;3)', "alm"), ('=MID("Kalmido";6;9)', "do"), ('=LÄNGE("Kalmido")', 7), ('=LEN(A2)', 3),
    ('=VERKETTEN(B1;"-";A2)', "low-100"), ('=CONCAT(B1:B3)', "lowmidhigh"), ('=CONCATENATE("a";"b")', "ab"),
    ('=GLÄTTEN("  a   b ")', "a b"), ('=TRIM(" x ")', "x"), ('=GROSS("abc")', "ABC"), ('=UPPER("Ab")', "AB"),
    ('=KLEIN("ÄB")', "äb"), ('=LOWER("Q")', "q"), ('=B1&" "&B2', "low mid"),
    ('=DATUM(2026;2;30)', "2026-03-02"), ('=DATE(2026;13;1)', "2027-01-01"), ('=JAHR(DATUM(2026;5;17))', 2026),
    ('=MONTH("2026-05-17")', 5), ('=TAG(DATUM(2026;5;17))', 17), ('=DAY("17.05.2026")', 17),
    ('=EDATUM(DATUM(2026;1;31);1)', "2026-02-28"), ('=EDATE("2026-03-15";-2)', "2026-01-15"),
    ('=TAGE(HEUTE();DATUM(JAHR(HEUTE());MONAT(HEUTE());TAG(HEUTE())))', 0), ('=TODAY()', testclock.today().isoformat()),
    ('=LINKS("a";-1)', ("err", "type")), ('=TEIL("abc";0;1)', ("err", "type")), ('=JAHR("no date")', ("err", "type")),
    ('=DATUM(99999;1;1)', ("err", "type")), ('=XVERWEIS(1;A1:B3;B1:B3)', ("err", "type")),
]
cells = [{"cell": f"C{i + 1}", "raw": f} for i, (f, _w) in enumerate(G)]
check(len(G) <= 50, "fits")
A.post(B + f"/api/sheets/{T2}/rows", json={"count": 40})
r = put(A, T2, cells)
check(r.ok, "the second set of formulas " + r.text[:300])
d = get(A, T2)
for i, (f, want) in enumerate(G):
    x = cell(d, f"C{i + 1}")
    if isinstance(want, tuple):
        check(x.get("error") == want[1], f"{f}: error {want[1]} " + json.dumps(x)[:200])
    elif f == "=TODAY()":
        # the container's day may differ from the runner's around midnight: a date of the last / next day is fine
        check(x.get("vtype") == "date" and abs((date.fromisoformat(x["value"]) - testclock.today()).days) <= 1, f"{f} is today " + json.dumps(x)[:200])
    else:
        check(x.get("value") == want and not x.get("error"), f"{f} = {want!r} " + json.dumps(x)[:200])
# a column called "Tag" (day) keeps its name in formulas next to the function TAG()
r = A.post(B + f"/api/sheets/{T2}/columns", json={"title": "Tag", "kind": "number"})
check(r.status_code == 201, "a column 'Tag' " + r.text[:200])
TL = r.json()["column"]["letter"]
put(A, T2, [{"cell": f"{TL}1", "raw": "4"}, {"cell": f"{TL}2", "raw": "6"}])
r = put(A, T2, [{"cell": "B5", "raw": "=SUMME(tag)+TAG(DATUM(2026;1;5))"}])
check(r.ok and cell(get(A, T2), "B5").get("value") == 15, "the column 'Tag' by name and TAG() side by side " + r.text[:300])
# the completion offers the new functions with a help
v = A.get(B + f"/api/sheets/{T2}/vars", params={"q": "sver"}).json()
items = v if isinstance(v, list) else v.get("items") or v.get("vars") or []
check(any(x.get("token") == "SVERWEIS" and x.get("kind") == "function" and x.get("help") for x in items), "completion: SVERWEIS with help " + json.dumps(v)[:300])

# ================================================================== #2109 import / export
def xlsx(rows):
    """A minimal .xlsx: rows of (value | ("f", formula, cached value))."""
    def col(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s
    xml = []
    for ri, row in enumerate(rows, 1):
        cs = []
        for ci, v in enumerate(row):
            ref = f"{col(ci)}{ri}"
            if isinstance(v, tuple):
                f = v[1].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
                if isinstance(v[2], str):
                    cs.append(f'<c r="{ref}" t="str"><f>{f}</f><v>{v[2]}</v></c>')
                else:
                    cs.append(f'<c r="{ref}"><f>{f}</f><v>{v[2]}</v></c>')
            elif isinstance(v, (int, float)):
                cs.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                cs.append(f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>')
        xml.append(f'<row r="{ri}">{"".join(cs)}</row>')
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{main}" xmlns:r="{rel}"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{main}"><sheetData>{"".join(xml)}</sheetData></worksheet>')
    return b.getvalue()


XL = xlsx([["Name", "Amount", "Result"],
           ["a", 1, ("f", 'SUMIF(A2:A4,"a",B2:B4)', 4)],
           ["b", 2, ("f", 'VLOOKUP("b",A2:B4,2,FALSE)', 2)],
           ["a", 3, ("f", "VLOOKUP(2,B2:B4,1)", 2)],
           ["", "", ("f", '_xlfn.XLOOKUP("b",A2:A4,B2:B4,"-")', 2)],
           ["", "", ("f", "LEFT(A2,1)&UPPER(A3)&COUNTIF(A2:A4,\"a\")", "aB2")]])
r = A.post(B + "/api/sheets/import", data={"space": f"org:{ORG}", "title": "Imported"}, files={"file": ("calc.xlsx", XL)})
check(r.status_code == 201, "import an .xlsx with SUMIF / VLOOKUP / XLOOKUP " + r.text[:300])
IM = r.json()["sheet"]["id"] if r.status_code == 201 else None
rep = r.json().get("report") or {} if r.status_code == 201 else {}
check(rep.get("formulas") == 5 and not rep.get("as_value"), "all five taken over as formulas " + json.dumps(rep))
if IM:
    d = get(A, IM)
    want = {"C1": ("=SUMMEWENN(A1:A3;\"a\";B1:B3)", 4), "C2": ("=SVERWEIS(\"b\";A1:B3;2;FALSCH)", 2),
            "C3": ("=SVERWEIS(2;B1:B3;1;WAHR)", 2), "C4": ("=XVERWEIS(\"b\";A1:A3;B1:B3;\"-\")", 2),
            "C5": ("=LINKS(A1;1)&GROSS(A2)&ZÄHLENWENN(A1:A3;\"a\")", "aB2")}
    for a, (raw, val) in want.items():
        x = cell(d, a)
        check(x.get("raw") == raw and x.get("value") == val, f"import {a}: {raw} = {val!r} " + json.dumps(x)[:250])
    A.post(B + f"/api/sheets/{IM}/columns", json={"title": "Check", "kind": "text"})
    check(put(A, IM, [{"cell": "D1", "raw": '=SVERWEIS("a";A1:B3;2)'}]).ok, "a VLOOKUP with three arguments")
    r = A.get(B + f"/api/sheets/{IM}/export.xlsx")
    check(r.ok, "export .xlsx")
    sx = zipfile.ZipFile(io.BytesIO(r.content)).read("xl/worksheets/sheet1.xml").decode()
    for part in ("SUMIF(A2:A4,&quot;a&quot;,B2:B4)", "VLOOKUP(&quot;b&quot;,A2:B4,2,FALSE)", "VLOOKUP(2,B2:B4,1,TRUE)",
                 "_xlfn.XLOOKUP(", "LEFT(A2,1)&amp;UPPER(A3)&amp;COUNTIF(", "VLOOKUP(&quot;a&quot;,A2:B4,2,FALSE)"):
        check(part in sx or part.replace("&quot;", '"') in sx, f"export holds {part} " + sx[sx.find('<f>'):sx.find('<f>') + 200])

# ================================================================== #2115 the chart
COLS = [c["id"] for c in get(A, SID)["columns"]]  # A..F
url = B + f"/api/sheets/{SID}/chart"
r = A.put(url, json={"chart": {"type": "bar", "x": COLS[0], "y": [COLS[1]]}})
check(r.ok and r.json()["chart"] == {"type": "bar", "x": COLS[0], "y": [COLS[1]]}, "save a bar chart " + r.text[:200])
check(get(A, SID)["chart"] == {"type": "bar", "x": COLS[0], "y": [COLS[1]]}, "GET answers it")
check(get(Bo, SID)["chart"]["type"] == "bar", "a member of the organisation sees it")
r = Bo.put(url, json={"chart": {"type": "line", "x": None, "y": [COLS[1], COLS[3], COLS[1]]}})
check(r.ok and r.json()["chart"] == {"type": "line", "x": None, "y": [COLS[1], COLS[3]]}, "a member who writes changes it (doubles dropped) " + r.text[:200])
for bad, what in (({"type": "pie", "y": [COLS[1]]}, "a kind it does not know"), ({"type": "bar", "y": []}, "no column"),
                  ({"type": "bar", "y": [COLS[1] + 99999]}, "a column that does not exist"),
                  ({"type": "bar", "y": COLS + [COLS[0]]}, "more than six columns"),
                  ({"type": "bar", "x": "A", "y": [COLS[1]]}, "x not an id"), ("bar", "not an object")):
    check(A.put(url, json={"chart": bad}).status_code == 400, f"chart: {what} = 400")
other = A.post(B + "/api/sheets", json={"title": "Other", "space": f"org:{ORG}"}).json()
check(A.put(url, json={"chart": {"type": "bar", "y": [other["columns"][0]["id"]]}}).status_code == 400, "a column of another table: 400")
check(get(A, SID)["chart"]["type"] == "line", "a refused change leaves the chart")
check(Fr.get(B + f"/api/sheets/{SID}").status_code == 404 and Fr.put(url, json={"chart": None}).status_code == 404, "another organisation: 404")
# a reader of a list sees the chart of the table attached to it, but cannot change it
W = A.post(B + "/api/lists", json={"name": "Orchard", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{W}/members", json={"user_id": uid["carol"], "role": "view"})
LS = A.post(B + "/api/sheets", json={"title": "Orchard sheet", "space": f"org:{ORG}", "list_id": W}).json()
lurl = B + f"/api/sheets/{LS['id']}/chart"
check(A.put(lurl, json={"chart": {"type": "bar", "y": [LS["columns"][1]["id"]]}}).ok, "the owner sets a chart on the list's table")
check(get(Ca, LS["id"]).get("chart", {}).get("type") == "bar", "the reader sees the chart")
check(Ca.put(lurl, json={"chart": None}).status_code == 403, "the reader cannot change it: 403")
check(Bo.get(B + f"/api/sheets/{LS['id']}").status_code == 404 and Bo.put(lurl, json={"chart": None}).status_code == 404,
      "a member who does not see the list: 404")
# the module switched off: no change (409)
Bo.patch(B + "/api/settings", json={"features": "collab,comments"})
check(Bo.put(url, json={"chart": None}).status_code == 409, "the module off: 409")
Bo.patch(B + "/api/settings", json={"features": FEAT})
# rev moves, null removes
rev = get(A, SID)["rev"]
r = A.put(url, json={"chart": None})
check(r.ok and r.json()["chart"] is None and r.json()["rev"] > rev and get(A, SID)["chart"] is None, "null removes it, rev moves")
# agents read it with the table
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "sheets:read"], "username": "helper", "display_name": "Helper", "org_id": ORG})
if r.ok:
    AG = {"Authorization": "Bearer " + r.json()["token"], **H}
    A.put(url, json={"chart": {"type": "bar", "y": [COLS[1]]}})
    W2 = A.post(B + "/api/lists", json={"name": "Shared", "org_id": ORG}).json()["id"]
    A.put(B + f"/api/lists/{W2}/members", json={"user_id": r.json()["id"], "role": "view"})
    AS = A.post(B + "/api/sheets", json={"title": "Agent sheet", "space": f"org:{ORG}", "list_id": W2}).json()
    A.put(B + f"/api/sheets/{AS['id']}/chart", json={"chart": {"type": "line", "y": [AS["columns"][1]["id"]]}})
    ra = requests.get(B + f"/api/v1/sheets/{AS['id']}", headers=AG)
    check(ra.ok and (ra.json().get("chart") or {}).get("type") == "line", "an agent's GET has the chart " + ra.text[:200])
    check(requests.put(B + f"/api/sheets/{AS['id']}/chart", headers=AG, json={"chart": None}).status_code in (401, 403, 404),
          "an agent token on the session route: refused")

# ================================================================== a person without an organisation
FID, Fl = freelancer(B, A, "fiona", FEATURES + ",sheets")
r = Fl.post(B + "/api/sheets", json={"title": "My numbers", "space": "private"})
check(r.status_code == 201, "freelancer: a private table " + r.text[:200])
FS = r.json()
put(Fl, FS["id"], [{"cell": "A1", "raw": "x"}, {"cell": "A2", "raw": "y"}, {"cell": "B1", "raw": "2"}, {"cell": "B2", "raw": "5"},
                   {"cell": "C1", "raw": '=SVERWEIS("y";A1:B2;2)+SUMMEWENN(A1:A2;"x";B1:B2)'}])
check(cell(get(Fl, FS["id"]), "C1").get("value") == 7, "freelancer: SVERWEIS + SUMMEWENN")
r = Fl.put(B + f"/api/sheets/{FS['id']}/chart", json={"chart": {"type": "bar", "x": FS["columns"][0]["id"], "y": [FS["columns"][1]["id"]]}})
check(r.ok and get(Fl, FS["id"])["chart"]["type"] == "bar", "freelancer: the chart of the own table " + r.text[:200])
check(A.put(B + f"/api/sheets/{FS['id']}/chart", json={"chart": None}).status_code == 404, "someone else: the freelancer's table 404")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
