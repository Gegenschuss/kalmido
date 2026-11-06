#!/usr/bin/env python3
# kalmido-suite: now=wed10:00
"""2.578.0 API tests, part D (#3462): the everyday formula functions of tables, their .xlsx mapping and the new chart kinds.
Invented names only, the .xlsx is generated here.
 - SUMMEWENNS/SUMIFS, ZÄHLENWENNS/COUNTIFS, MITTELWERTWENN/AVERAGEIF, INDEX, VERGLEICH/MATCH (exact by default, 1 / -1),
   WENNFEHLER/IFERROR (a cycle stays a cycle), UND/AND, ODER/OR, NICHT/NOT, ABS, AUFRUNDEN/ROUNDUP, ABRUNDEN/ROUNDDOWN,
   NETTOARBEITSTAGE/NETWORKDAYS (holidays, backwards), ARBEITSTAG/WORKDAY, WOCHENTAG/WEEKDAY (types 1, 2, 3, 11),
   KALENDERWOCHE/WEEKNUM (ISO by default, type 1), ISOKALENDERWOCHE, TEXT (numbers, %, dates, weekday, leading zeros, text),
   ANZAHL2/COUNTA, JETZT/NOW; errors as kinds; the display in the person's language; the completion offers them
 - import of an .xlsx with SUMIFS / COUNTIFS / MATCH (2 arguments) / WEEKNUM (1 argument) / IFERROR / ISOWEEKNUM / ROUNDUP:
   formulas again, MATCH gets ;1 and WEEKNUM ;1; the export writes them back, a Kalmido VERGLEICH with 2 arguments gets ,0 and
   a KALENDERWOCHE with one ,21
 - charts: pie, donut and stacked bars are stored; a pie / donut takes one column with numbers (else 400); an unknown kind 400
 - the print view as PDF (POST /api/sheets/<id>/print.pdf): portrait / landscape (MediaBox), the header row on every page or
   once, page numbers on / off, a selection of rows and columns, a wide sheet across pages without "fit" and on one with it,
   bad options 400, a stranger 404
 - a person without an organisation uses the new functions and a pie chart in the private workspace
tenant-matrix: sheet
freelancer-matrix: sheets
usage: p2578_d_api_test.py <datadir>      (a fresh container; P2578D_NOSTART=1 = the server already runs)"""
import html
import io
import json
import os
import re
import subprocess
import sys
import zipfile
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEAT = "sheets,collab,comments"


def put(s, sid, cells):
    return s.put(B + f"/api/sheets/{sid}/cells", json={"cells": cells})


def get(s, sid):
    return s.get(B + f"/api/sheets/{sid}").json()


def cell(d, addr):
    return next((x for x in d["cells"] if x["addr"] == addr), None) or {}


def run_set(s, sid, col, cases, label):
    """Writes the formulas of cases [(formula, expected)] into column col (rows 1..n) and checks each value / error kind."""
    r = put(s, sid, [{"cell": f"{col}{i + 1}", "raw": f} for i, (f, _w) in enumerate(cases)])
    check(r.ok, f"{label}: the formulas are taken " + r.text[:300])
    d = get(s, sid)
    for i, (f, want) in enumerate(cases):
        x = cell(d, f"{col}{i + 1}")
        if isinstance(want, tuple) and want[0] == "err":
            check(x.get("error") == want[1] and x.get("value") is None, f"{f}: error {want[1]} " + json.dumps(x)[:200])
        elif isinstance(want, tuple) and want[0] == "re":
            check(isinstance(x.get("value"), str) and re.fullmatch(want[1], x["value"]) and not x.get("error"), f"{f} ~ {want[1]} " + json.dumps(x)[:200])
        elif isinstance(want, float):
            check(isinstance(x.get("value"), (int, float)) and abs(x["value"] - want) < 1e-9 and not x.get("error"), f"{f} = {want!r} " + json.dumps(x)[:200])
        else:
            check(x.get("value") == want and not x.get("error"), f"{f} = {want!r} " + json.dumps(x)[:200])
    return d


if not os.environ.get("P2578D_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})

# ================================================================== #3462 point 2: functions
r = A.post(B + "/api/sheets", json={"title": "Orchard", "space": f"org:{ORG}"})
check(r.status_code == 201, "a table " + r.text[:200])
SID = r.json()["id"]
for _ in range(3):
    A.post(B + f"/api/sheets/{SID}/columns", json={"title": "", "kind": "text"})  # D, E, F
A.post(B + f"/api/sheets/{SID}/rows", json={"count": 60})
data = [("A1", "Apple"), ("A2", "Pear"), ("A3", "Cherry"), ("A4", "apple"),
        ("B1", "5"), ("B2", "10"), ("B3", "3"), ("B4", "7"),
        ("D1", "open"), ("D2", "done"), ("D3", "open"), ("D4", "open"),
        ("E1", "10"), ("E2", "20"), ("E3", "30")]
check(put(A, SID, [{"cell": a, "raw": v} for a, v in data]).ok, "the values")
F = [
    ('=SUMMEWENNS(B1:B4;A1:A4;"apple";D1:D4;"open")', 12),
    ('=SUMIFS(B1:B4;B1:B4;">5";D1:D4;"open")', 7),
    ('=ZÄHLENWENNS(A1:A4;"apple";D1:D4;"open")', 2),
    ('=COUNTIFS(D1:D4;"open";B1:B4;"<5")', 1),
    ('=MITTELWERTWENN(D1:D4;"open";B1:B4)', 5),
    ('=AVERAGEIF(B1:B4;">5")', 8.5),
    ('=MITTELWERTWENN(D1:D4;"x";B1:B4)', ("err", "div0")),
    ('=SUMMEWENNS(B1:B3;A1:A4;"apple")', ("err", "type")),
    ('=INDEX(A1:B4;3;2)', 3),
    ('=INDEX(A1:A4;2)', "Pear"),
    ('=INDEX(E1:E3;5)', ("err", "ref")),
    ('=INDEX(A1:B4;0;1)', ("err", "type")),
    ('=VERGLEICH("cherry";A1:A4)', 3),
    ('=MATCH("Mango";A1:A4;0)', ("err", "na")),
    ('=VERGLEICH(25;E1:E3;1)', 2),
    ('=MATCH(15;E1:E3;-1)', 2),
    ('=INDEX(B1:B4;VERGLEICH("Pear";A1:A4;0))', 10),
    ('=WENNFEHLER(1/0;"none")', "none"),
    ('=IFERROR(VLOOKUP("Mango";A1:B4;2;FALSE);0)', 0),
    ('=WENNFEHLER(B1*2;0)', 10),
    ('=UND(B1>1;B2>1)', True),
    ('=OR(B1>100;D1="open")', True),
    ('=NICHT(B1>1)', False),
    ('=AND(TRUE;FALSE)', False),
    ('=UND()', ("err", "syntax")),
    ('=ABS(-4.5)', 4.5),  # (without a ";" a "," separates arguments)
    ('=AUFRUNDEN(2,141;2)', 2.15),
    ('=ROUNDUP(-2,1;0)', -3),
    ('=AUFRUNDEN(1234;-2)', 1300),
    ('=ABRUNDEN(2,199;1)', 2.1),
    ('=ROUNDDOWN(-2,9;0)', -2),
    ('=NETTOARBEITSTAGE(DATUM(2026;11;2);DATUM(2026;11;13))', 10),
    ('=NETWORKDAYS(DATUM(2026;11;2);DATUM(2026;11;13);DATUM(2026;11;4))', 9),
    ('=NETTOARBEITSTAGE(DATUM(2026;11;13);DATUM(2026;11;2))', -10),
    ('=ARBEITSTAG(DATUM(2026;11;6);1)', "2026-11-09"),
    ('=WORKDAY(DATUM(2026;11;2);3;DATUM(2026;11;4))', "2026-11-06"),
    ('=ARBEITSTAG(DATUM(2026;11;9);-1)', "2026-11-06"),
    ('=ARBEITSTAG(DATUM(2026;11;2);20)', "2026-11-30"),
    ('=WOCHENTAG(DATUM(2026;11;8))', 1),
    ('=WEEKDAY(DATUM(2026;11;8);2)', 7),
    ('=WOCHENTAG(DATUM(2026;11;2);3)', 0),
    ('=WOCHENTAG(DATUM(2026;11;2);11)', 1),
    ('=WOCHENTAG(DATUM(2026;11;2);9)', ("err", "type")),
    ('=KALENDERWOCHE(DATUM(2027;1;1))', 53),
    ('=WEEKNUM(DATUM(2027;1;1);1)', 1),
    ('=ISOKALENDERWOCHE(DATUM(2026;11;6))', 45),
    ('=ANZAHL2(A1:A8)', 4),
    ('=COUNTA(A1:B4;"x")', 9),
    ('=JETZT()', ("re", r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")),
]
check(len(F) <= 60, "fits the rows")
d = run_set(A, SID, "C", F, "functions")
check(cell(d, "C1").get("raw") == '=SUMIFS(B1:B4;A1:A4;"apple";D1:D4;"open")', "a German name shows in the person's language (English) "
      + str(cell(d, "C1").get("raw")))
check(cell(d, "C13").get("raw") == '=MATCH("cherry";A1:A4)', "VERGLEICH reads MATCH " + str(cell(d, "C13").get("raw")))
T = [
    ('=TEXT(1234,5;"#,##0.00")', "1,234.50"),
    ('=TEXT(1234,5;"#.##0,00")', "1,234.50"),  # the German pattern, shown with the separators of the person's language
    ('=TEXT(0,256;"0%")', "26%"),
    ('=TEXT(7;"000")', "007"),
    ('=TEXT(-3,5;"0,0")', "-3.5"),
    ('=TEXT(1234567;"#,##0")', "1,234,567"),
    ('=TEXT(5;"0,00 €")', "5.00 €"),
    ('=TEXT(DATUM(2026;11;6);"DD.MM.YYYY")', "06.11.2026"),
    ('=TEXT(DATUM(2026;11;6);"TT.MM.JJ")', "06.11.26"),
    ('=TEXT(DATUM(2026;11;6);"dddd")', "Friday"),
    ('=TEXT(DATUM(2026;11;6);"MMMM YYYY")', "November 2026"),
    ('=TEXT("2026-11-06 14:05";"hh:mm")', "14:05"),
    ('=TEXT("abc";"0,00")', "abc"),
    ('=TEXT(JETZT();"YYYY")', ("re", r"\d{4}")),
    ('=TEXT(5)', ("err", "syntax")),
]
run_set(A, SID, "F", T, "TEXT")
# 2.578.0 (#3462) review F1: a huge number in AUFRUNDEN / ABRUNDEN / TEXT is an error in its cell, the table stays readable
r = A.post(B + "/api/sheets", json={"title": "Huge", "space": f"org:{ORG}"})
HID = r.json()["id"]
A.post(B + f"/api/sheets/{HID}/rows", json={"count": 10})
HUGE = [('=AUFRUNDEN(1E30;0)', ("err", "type")), ('=ABRUNDEN(1E29;2)', ("err", "type")), ('=TEXT(1E30;"0,00")', ("err", "type")),
        ('=TEXT(1E13;"0%")', ("err", "type")), ('=AUFRUNDEN(1E308*10;0)', ("err", "type")), ('=TEXT("NaN";"0,00")', "NaN"),
        ('=AUFRUNDEN(123456789012,1;0)', 123456789013)]
check(put(A, HID, [{"cell": f"A{i + 1}", "raw": f} for i, (f, _w) in enumerate(HUGE)]).ok, "huge numbers: the formulas are taken")
r = A.get(B + f"/api/sheets/{HID}")
check(r.status_code == 200, f"huge numbers: the table stays readable {r.status_code}")
if r.status_code == 200:
    run_set(A, HID, "A", HUGE, "huge numbers")
for path in ("export.xlsx", "export.csv"):
    r = A.get(B + f"/api/sheets/{HID}/{path}")
    check(r.status_code == 200, f"huge numbers: {path} {r.status_code}")
r = A.post(B + f"/api/sheets/{HID}/print.pdf", json={})
check(r.status_code == 200, f"huge numbers: print.pdf {r.status_code}")
# WENNFEHLER does not hide a cycle: the cells of the cycle stay marked
r = put(A, SID, [{"cell": "E10", "raw": "=WENNFEHLER(E11;0)"}, {"cell": "E11", "raw": "=E10+1"}])
d = get(A, SID)
check(cell(d, "E10").get("error") == "cycle" and cell(d, "E11").get("error") == "cycle", "a cycle through WENNFEHLER stays a cycle "
      + json.dumps([cell(d, "E10"), cell(d, "E11")])[:300])
# a change answers the functions that read it
r = put(A, SID, [{"cell": "B4", "raw": "8"}])
check(r.ok and any(x["addr"] == "C1" and x["value"] == 13 for x in r.json()["cells"]), "changing B4 answers SUMMEWENNS again " + r.text[:300])
# the completion offers the new functions with a help
for q, tok in (("sumifs", "SUMIFS"), ("wennf", "IFERROR"), ("networ", "NETWORKDAYS"), ("anzahl2", "COUNTA")):
    v = A.get(B + f"/api/sheets/{SID}/vars", params={"q": q}).json()
    items = v if isinstance(v, list) else v.get("items") or v.get("vars") or []
    check(any(x.get("token") == tok and x.get("kind") == "function" and x.get("help") for x in items), f"completion: {tok} for '{q}' "
          + json.dumps(v)[:300])


# ================================================================== #3462 point 2: import / export
def xlsx(rows):
    """A minimal .xlsx: rows of (value | ("f", formula, cached value))."""
    def col(i):
        s = ""
        i += 1
        while i:
            i, rr = divmod(i - 1, 26)
            s = chr(65 + rr) + s
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
            elif v != "":
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
           ["a", 1, ("f", 'SUMIFS(B2:B4,A2:A4,"a")', 4)],
           ["b", 2, ("f", 'COUNTIFS(A2:A4,"a",B2:B4,">1")', 1)],
           ["a", 3, ("f", "MATCH(2,B2:B4)", 2)],
           ["", "", ("f", "WEEKNUM(DATE(2027,1,1))", 1)],
           ["", "", ("f", 'IFERROR(1/0,"x")', "x")],
           ["", "", ("f", "_xlfn.ISOWEEKNUM(DATE(2027,1,1))", 53)],
           ["", "", ("f", "ROUNDUP(B2/3,1)", 0.4)]])
r = A.post(B + "/api/sheets/import", data={"space": f"org:{ORG}", "title": "Imported"}, files={"file": ("calc.xlsx", XL)})
check(r.status_code == 201, "import an .xlsx with the new functions " + r.text[:300])
IM = r.json()["sheet"]["id"] if r.status_code == 201 else None
rep = (r.json().get("report") or {}) if r.status_code == 201 else {}
check(rep.get("formulas") == 7 and not rep.get("as_value"), "all seven taken over as formulas " + json.dumps(rep))
if IM:
    d = get(A, IM)
    want = {"C1": ('=SUMIFS(B1:B3;A1:A3;"a")', 4), "C2": ('=COUNTIFS(A1:A3;"a";B1:B3;">1")', 1),
            "C3": ("=MATCH(2;B1:B3;1)", 2), "C4": ("=WEEKNUM(DATE(2027;1;1);1)", 1), "C5": ('=IFERROR(1/0;"x")', "x"),
            "C6": ("=ISOWEEKNUM(DATE(2027;1;1))", 53)}
    for a, (raw, val) in want.items():
        x = cell(d, a)
        check(x.get("raw") == raw and x.get("value") == val, f"import {a}: {raw} = {val!r} " + json.dumps(x)[:250])
    x = cell(d, "C7")
    check(x.get("raw") == "=ROUNDUP(B1/3;1)" and abs((x.get("value") or 0) - 0.4) < 1e-9, "import C7: ROUNDUP " + json.dumps(x)[:250])
    A.post(B + f"/api/sheets/{IM}/columns", json={"title": "Check", "kind": "text"})
    check(put(A, IM, [{"cell": "D1", "raw": '=VERGLEICH("b";A1:A3)'}, {"cell": "D2", "raw": "=KALENDERWOCHE(DATUM(2026;11;6))"},
                      {"cell": "D3", "raw": "=NETTOARBEITSTAGE(DATUM(2026;11;2);DATUM(2026;11;6))"},
                      # 2.578.0 (#3462) review F5: TEXT formats go to Excel in its form
                      {"cell": "D4", "raw": '=TEXT(DATUM(2026;11;6);"TT.MM.JJJJ")'}, {"cell": "D5", "raw": '=TEXT(B1;"#.##0,00 €")'},
                      {"cell": "D6", "raw": '=TEXT(B1;"0,0")'}]).ok, "Kalmido-only defaults")
    r = A.get(B + f"/api/sheets/{IM}/export.xlsx")
    check(r.ok, "export .xlsx")
    sx = zipfile.ZipFile(io.BytesIO(r.content)).read("xl/worksheets/sheet1.xml").decode()
    for part in ("SUMIFS(B2:B4,A2:A4,&quot;a&quot;)", "COUNTIFS(A2:A4,&quot;a&quot;,B2:B4,&quot;&gt;1&quot;)", "MATCH(2,B2:B4,1)",
                 "WEEKNUM(DATE(2027,1,1),1)", "IFERROR(1/0,&quot;x&quot;)", "_xlfn.ISOWEEKNUM(DATE(2027,1,1))", "ROUNDUP(B2/3,1)",
                 "MATCH(&quot;b&quot;,A2:A4,0)", "WEEKNUM(DATE(2026,11,6),21)", "NETWORKDAYS(DATE(2026,11,2),DATE(2026,11,6))",
                 'TEXT(DATE(2026,11,6),"dd.MM.yyyy")', 'TEXT(B2,"#,##0.00 €")', 'TEXT(B2,"0.0")'):
        plain = html.unescape(part)
        check(plain in html.unescape(sx), f"export holds {plain} " + sx[sx.find('<f>'):sx.find('<f>') + 200])

# ================================================================== #3462 point 5: chart kinds
COLS = [c["id"] for c in get(A, SID)["columns"]]
url = B + f"/api/sheets/{SID}/chart"
for kind in ("pie", "donut"):
    r = A.put(url, json={"chart": {"type": kind, "x": COLS[0], "y": [COLS[1]]}})
    check(r.ok and r.json()["chart"] == {"type": kind, "x": COLS[0], "y": [COLS[1]]}, f"save a {kind} chart " + r.text[:200])
    check(A.put(url, json={"chart": {"type": kind, "x": COLS[0], "y": [COLS[1], COLS[4]]}}).status_code == 400,
          f"a {kind} chart with two columns: 400")
check(get(A, SID)["chart"]["type"] == "donut", "a refused change leaves the chart")
r = A.put(url, json={"chart": {"type": "stacked", "x": COLS[0], "y": [COLS[1], COLS[4]]}})
check(r.ok and r.json()["chart"]["type"] == "stacked" and r.json()["chart"]["y"] == [COLS[1], COLS[4]], "stacked bars with two columns " + r.text[:200])
check(A.put(url, json={"chart": {"type": "radar", "y": [COLS[1]]}}).status_code == 400, "an unknown kind: 400")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "sheets:read"], "username": "helper", "display_name": "Helper", "org_id": ORG})
if r.ok:
    AG = {"Authorization": "Bearer " + r.json()["token"], **H}
    W = A.post(B + "/api/lists", json={"name": "Shared", "org_id": ORG}).json()["id"]
    A.put(B + f"/api/lists/{W}/members", json={"user_id": r.json()["id"], "role": "view"})
    AS = A.post(B + "/api/sheets", json={"title": "Agent sheet", "space": f"org:{ORG}", "list_id": W}).json()
    A.put(B + f"/api/sheets/{AS['id']}/chart", json={"chart": {"type": "pie", "y": [AS["columns"][1]["id"]]}})
    ra = requests.get(B + f"/api/v1/sheets/{AS['id']}", headers=AG)
    check(ra.ok and (ra.json().get("chart") or {}).get("type") == "pie", "an agent's GET has the pie chart " + ra.text[:200])

# ================================================================== #3462 point 4: the print view as PDF
def pdf_parts(raw):
    """(page count, [MediaBox sizes], the page contents unpacked) of a PDF from shprint (FlateDecode streams)."""
    boxes = re.findall(rb"/Type /Page /Parent \d+ 0 R /MediaBox \[0 0 ([\d.]+) ([\d.]+)\]", raw)
    text = b""
    for m in re.finditer(rb"stream\n(.*?)\nendstream", raw, re.S):
        try:
            text += zlib.decompress(m.group(1)) + b"\n"
        except zlib.error:
            pass
    return len(boxes), [(float(w), float(h)) for w, h in boxes], text


def hx(s):
    return ("<" + s.encode("cp1252").hex() + ">").encode()


r = A.post(B + "/api/sheets", json={"title": "Print me", "space": f"org:{ORG}"})
PS = r.json()
PID = PS["id"]
c1 = A.post(B + f"/api/sheets/{PID}/columns", json={"title": "Customer", "kind": "text"}).json()["column"]
c2 = A.post(B + f"/api/sheets/{PID}/columns", json={"title": "Amount", "kind": "number"}).json()["column"]
A.post(B + f"/api/sheets/{PID}/rows", json={"count": 80})
check(put(A, PID, [{"cell": f"{c1['letter']}{i}", "raw": f"Client {i:03d}"} for i in range(1, 81)]
          + [{"cell": f"{c2['letter']}{i}", "raw": str(i * 10)} for i in range(1, 81)]).ok, "print: 80 rows")
purl = B + f"/api/sheets/{PID}/print.pdf"
r = A.post(purl, json={"orient": "portrait", "fit": True, "head": True, "numbers": True})
check(r.ok and r.headers.get("Content-Type", "").startswith("application/pdf") and r.content.startswith(b"%PDF"), "print: a PDF "
      + str(r.status_code) + r.text[:200] if not r.ok else "print: a PDF")
n, boxes, txt = pdf_parts(r.content)
check(n >= 2 and all(b == (595.28, 841.89) for b in boxes), f"print: portrait A4 over {n} pages {boxes[:2]}")
check(txt.count(hx("Customer")) == n, f"print: the header row on each of the {n} pages ({txt.count(hx('Customer'))})")
check(hx(f"Page 1 of {n}") in txt and hx(f"Page {n} of {n}") in txt, "print: page numbers")
check(hx("Print me") in txt and hx("Client 080") in txt and hx("800") in txt, "print: title and the last row")
r = A.post(purl, json={"orient": "landscape", "fit": True, "head": False, "numbers": False})
n2, boxes, txt = pdf_parts(r.content)
check(r.ok and boxes and all(b == (841.89, 595.28) for b in boxes), f"print: landscape {boxes[:1]}")
check(txt.count(hx("Customer")) == 1 and hx("Page 1 of") not in txt and n2 >= 2, f"print: header only once, no page numbers ({n2} pages)")
rows = [x["id"] for x in get(A, PID)["rows"]]
r = A.post(purl, json={"rows": rows[2:4], "cols": [c1["id"]]})
n3, _b, txt = pdf_parts(r.content)
check(r.ok and n3 == 1 and hx("Client 003") in txt and hx("Client 004") in txt and hx("Client 005") not in txt
      and hx("Amount") not in txt, "print: the selection only (two rows, one column)")
# a wide sheet: without "fit" the columns run onto further pages, with "fit" they share one page width
r = A.post(B + "/api/sheets", json={"title": "Wide", "space": f"org:{ORG}"})
WID = r.json()["id"]
for _ in range(9):
    A.post(B + f"/api/sheets/{WID}/columns", json={"title": "", "kind": "text"})
wl = [c["letter"] for c in get(A, WID)["columns"]]
put(A, WID, [{"cell": f"{L}1", "raw": f"Long text in column {L} " * 2} for L in wl])
na = pdf_parts(A.post(B + f"/api/sheets/{WID}/print.pdf", json={"fit": False}).content)[0]
nf = pdf_parts(A.post(B + f"/api/sheets/{WID}/print.pdf", json={"fit": True}).content)[0]
check(na > 1 and nf == 1, f"print: without fit {na} pages across, with fit {nf}")
for bad, what in (({"orient": "upside"}, "an unknown orientation"), ({"rows": []}, "no rows"), ({"rows": [999999999]}, "rows of no sheet"),
                  ({"cols": "A"}, "columns not a list")):
    check(A.post(purl, json=bad).status_code == 400, f"print: {what} = 400")

# ================================================================== a person without an organisation
FID, Fl = freelancer(B, A, "fiona", FEATURES + ",sheets")
r = Fl.post(B + "/api/sheets", json={"title": "My hours", "space": "private"})
check(r.status_code == 201, "freelancer: a private table " + r.text[:200])
FS = r.json()
put(Fl, FS["id"], [{"cell": "A1", "raw": "x"}, {"cell": "A2", "raw": "y"}, {"cell": "B1", "raw": "2"}, {"cell": "B2", "raw": "5"},
                   {"cell": "C1", "raw": '=WENNFEHLER(INDEX(B1:B2;VERGLEICH("y";A1:A2));0)+ZÄHLENWENNS(A1:A2;"x";B1:B2;">1")'},
                   {"cell": "C2", "raw": "=NETTOARBEITSTAGE(DATUM(2026;11;2);DATUM(2026;11;6))"}])
d = get(Fl, FS["id"])
check(cell(d, "C1").get("value") == 6 and cell(d, "C2").get("value") == 5, "freelancer: VERGLEICH, INDEX, WENNFEHLER, ZÄHLENWENNS, NETTOARBEITSTAGE "
      + json.dumps([cell(d, "C1"), cell(d, "C2")])[:300])
r = Fl.put(B + f"/api/sheets/{FS['id']}/chart", json={"chart": {"type": "pie", "x": FS["columns"][0]["id"], "y": [FS["columns"][1]["id"]]}})
check(r.ok and get(Fl, FS["id"])["chart"]["type"] == "pie", "freelancer: a pie chart of the own table " + r.text[:200])
check(A.put(B + f"/api/sheets/{FS['id']}/chart", json={"chart": None}).status_code == 404, "someone else: the freelancer's table 404")
r = Fl.post(B + f"/api/sheets/{FS['id']}/print.pdf", json={"orient": "landscape"})
check(r.ok and r.content.startswith(b"%PDF"), "freelancer: the print view of the own table " + (r.text[:200] if not r.ok else ""))
check(Fl.post(purl, json={}).status_code == 404 and A.post(B + f"/api/sheets/{FS['id']}/print.pdf", json={}).status_code == 404,
      "print: a stranger gets 404 both ways (organisation table / private table)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
