#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.578.0 C (#3462 points 1 + 3): the format of a table's cells and its colour rules (kalmido/sheets/shfmt.py). Invented names
only, the .xlsx files are made by the export here. tenant-matrix: sheet
freelancer-matrix: sheets
 - a cell's format on top of its column's kind: fmt (whole) / fmt_patch (some keys) through PUT …/cells, without raw only the
   format changes; it comes back with the cell (also an empty formatted cell); wrong colours / keys / merges: 400, nothing
   changed; the column keeps its kind; typing into / emptying a formatted cell keeps the format
 - the app's Undo: the former format written back with prev_fmt; prev_fmt that no longer fits: not changed, in conflicts
 - an agent formats in its batch (v1, fmt_patch), the person takes the call back: the format goes, a newer one stays
 - the colour rules: PUT /api/sheets/<id>/rules (validated: op, columns of the sheet, palette, values), in GET; expect_rev
   older = 409 with the current rules; the agents' route needs expect_rev; another person: 404
 - xlsx: the export writes bold / italic / colours / alignment / wrap per cell format, mergeCells and the rules as
   conditionalFormatting (OOXML order: sheetData, mergeCells, conditionalFormatting, dataValidations); the import of that
   file gives the same formats, merges and rules again
 - a copied sheet (POST …/tabs copy_of) keeps formats and rules on its own columns
 - review fixes (Fable 2, G1-G8): formatted empty cells / merged blocks of an imported file count against the table's cap (the
   rest is left out and reported); a format on a missing cell counts as a new cell; overlapping merged blocks are refused /
   end inside a new block / are left out of an import and its export; lists as rule ids / columns: 400; huge row numbers in a
   file are skipped; a changed input skips its entry's format too; a rule whose rows are in the trash is not exported; one
   broken rule of a file drops only itself
All as a person without an organisation (frida) with her personal agent; alice (the admin) as the other person.
usage: p2578_c_fmt_test.py <datadir>"""
import io
import os
import re
import sys
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check  # noqa: E402

V = B + "/api/v1"
# 2.578.0 (#3462, review G1 / G2): a small cap of cells per table, so the fixes show with a few hundred cells
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SHEET_CELLS_MAX": "300"}, prefix="P2578C")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,sheets", "tour": "done"})
FID, Fr = freelancer(B, A)


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "sheets:read", "sheets:write"], "username": "fridabot",
                                          "display_name": "Fridabot", "owner_id": FID})
assert r.status_code == 201, r.text
ag = bearer(r.json()["token"])


def get(sid, s=None):
    return (s or Fr).get(B + f"/api/sheets/{sid}").json()


def cell(d, addr):
    return next((x for x in d["cells"] if x["addr"] == addr), None) or {}


def put(sid, cells, s=None):
    return (s or Fr).put(B + f"/api/sheets/{sid}/cells", json={"cells": cells})


# ================================================================== a cell's format
r = Fr.post(B + "/api/sheets", json={"title": "Harvest plan", "space": "private"})
check(r.status_code == 201, "a private table " + r.text[:200])
S = r.json()
SID, C, R = S["id"], [c["id"] for c in S["columns"]], [x["id"] for x in S["rows"]]
check(S.get("rules") == [], "a new table has no colour rules " + str(S.get("rules")))
Fr.patch(B + f"/api/sheets/{SID}/columns/{C[1]}", json={"kind": "number"})
r = put(SID, [{"cell": "A1", "raw": "Apples"}, {"cell": "B1", "raw": "12"}, {"cell": "A2", "raw": "Pears"}, {"cell": "B2", "raw": "4"},
              {"cell": "A3", "raw": "Plums"}, {"cell": "B3", "raw": "30"}])
check(r.ok, "values " + r.text[:200])
r = put(SID, [{"cell": "A1", "fmt": {"bold": True, "fill": "a2", "align": "center"}}])
x = next((c for c in r.json().get("cells", []) if c["addr"] == "A1"), {}) if r.ok else {}
check(r.ok and x.get("fmt") == {"align": "center", "bold": True, "fill": "a2"} and x.get("raw") == "Apples",
      "fmt without raw: only the format changes, it comes back with the cell " + r.text[:300])
d = get(SID)
check(cell(d, "A1").get("fmt", {}).get("bold") is True and cell(d, "A1")["raw"] == "Apples", "GET has the format, the input stays")
check(cell(d, "A2").get("fmt") is None, "an unformatted cell: fmt null")
r = put(SID, [{"cell": "A1", "fmt_patch": {"italic": True, "align": None}}])
check(r.ok and cell(get(SID), "A1").get("fmt") == {"bold": True, "fill": "a2", "italic": True}, "fmt_patch: italic added, align removed")
# an empty cell with a format only
r = put(SID, [{"cell": "C4", "fmt": {"fill": "g3"}}])
check(r.ok and cell(get(SID), "C4").get("fmt") == {"fill": "g3"} and cell(get(SID), "C4").get("raw") == "", "an empty cell keeps a format")
# refused, nothing changed
before = get(SID)
for bad, what in (({"color": "#ff0000"}, "a free colour"), ({"size": 20}, "an unknown key"), ({"merge": [0, 2]}, "a merge of 0 rows"),
                  ({"align": "justify"}, "an unknown alignment"), ({"bold": "yes"}, "bold as text")):
    r = put(SID, [{"cell": "A2", "fmt": bad}])
    check(r.status_code == 400, f"{what}: 400 " + str(r.status_code))
check(cell(get(SID), "A2").get("fmt") is None and get(SID)["rev"] == before["rev"], "refused formats change nothing")
# the column keeps its kind; typing / emptying keeps the format
put(SID, [{"cell": "B1", "fmt": {"bold": True, "color": "a"}}])
check(next(c for c in get(SID)["columns"] if c["id"] == C[1])["kind"] == "number", "the number column stays a number column")
r = put(SID, [{"cell": "B1", "raw": "15", "prev": "12"}])
check(r.ok and cell(get(SID), "B1").get("fmt") == {"bold": True, "color": "a"} and cell(get(SID), "B1")["value"] == 15,
      "a new input keeps the format, the number is a number")
r = put(SID, [{"cell": "B1", "raw": "", "prev": "15"}])
check(r.ok and cell(get(SID), "B1").get("fmt") == {"bold": True, "color": "a"}, "emptying keeps the format (the cell stays)")
put(SID, [{"cell": "B1", "raw": "15"}])

# ================================================================== the app's Undo + prev_fmt
put(SID, [{"cell": "A2", "fmt": {"bold": True}, "prev_fmt": None}])
r = put(SID, [{"cell": "A2", "fmt": None, "prev_fmt": {"bold": True}}])  # Undo: back to none
check(r.ok and cell(get(SID), "A2").get("fmt") is None and not r.json().get("conflicts"), "Undo writes the former format back")
put(SID, [{"cell": "A2", "fmt": {"italic": True}}])  # changed "elsewhere"
r = put(SID, [{"cell": "A2", "fmt": {"bold": True}, "prev_fmt": None}])
cf = r.json().get("conflicts") or []
check(r.ok and cf and cf[0].get("what") == "fmt" and cf[0].get("server") == {"italic": True} and cell(get(SID), "A2").get("fmt") == {"italic": True},
      "prev_fmt that no longer fits: not changed, reported " + r.text[:300])
# the history names the format change
h = Fr.get(B + f"/api/sheets/{SID}/history")
check(h.ok and "Format" in h.text, "the history has the format change " + h.text[:200])

# ================================================================== an agent's call
r = ag.post(V + "/sheets", json={"title": "Bot plan", "space": "private", "rows": [["a", 1], ["b", 2]]})
check(r.status_code == 201, "the agent's table " + r.text[:200])
AS = r.json()
r = ag.put(V + f"/sheets/{AS['id']}/cells", json={"cells": [{"cell": "A1", "fmt_patch": {"bold": True}, "prev": "a"},
                                                            {"cell": "B2", "fmt": {"fill": "a"}, "prev": "2"}]})
check(r.ok and r.json().get("batch"), "an agent formats in its batch " + r.text[:300])
batch = r.json().get("batch")
d = get(AS["id"])
check(cell(d, "A1").get("fmt") == {"bold": True} and cell(d, "B2").get("fmt") == {"fill": "a"}, "the agent's formats are there")
put(AS["id"], [{"cell": "B2", "fmt": {"fill": "g2"}}])  # the person formats B2 again since
r = Fr.post(B + f"/api/sheets/{AS['id']}/batches/{batch}/undo")
d = get(AS["id"])
check(r.ok and cell(d, "A1").get("fmt") is None and cell(d, "B2").get("fmt") == {"fill": "g2"},
      "taking the call back: the agent's format goes, the person's newer one stays " + r.text[:200])
check(cell(d, "A1").get("raw") == "a", "the input stays at the format's Undo")

# ================================================================== colour rules
url = B + f"/api/sheets/{SID}/rules"
rev = get(SID)["rev"]
r = Fr.put(url, json={"rules": [{"cols": [C[1]], "op": "gt", "a": "10", "fill": "a"},
                                 {"cols": [C[0]], "rows": [R[0], R[1]], "op": "contains", "a": "pea", "color": "g1"},
                                 {"cols": [C[2]], "op": "empty", "fill": "g3"}], "expect_rev": rev})
check(r.ok and len(r.json().get("rules") or []) == 3 and r.json()["rev"] > rev, "three rules saved " + r.text[:300])
d = get(SID)
check([x["op"] for x in d.get("rules") or []] == ["gt", "contains", "empty"] and d["rules"][1]["rows"] == [R[0], R[1]]
      and all(x.get("id") for x in d["rules"]), "GET has the rules (ids, rows) " + str(d.get("rules"))[:300])
for bad, what in (({"cols": [C[1]], "op": "bigger", "a": "1", "fill": "a"}, "an unknown op"),
                  ({"cols": [999999], "op": "gt", "a": "1", "fill": "a"}, "a column of no sheet"),
                  ({"cols": [C[1]], "op": "gt", "a": "1", "fill": "#00ff00"}, "a free colour"),
                  ({"cols": [C[1]], "op": "gt", "fill": "a"}, "no value"),
                  ({"cols": [C[1]], "op": "between", "a": "1", "fill": "a"}, "between with one value"),
                  ({"cols": [C[1]], "op": "gt", "a": "1"}, "no colour")):
    r = Fr.put(url, json={"rules": [bad]})
    check(r.status_code == 400, f"rule with {what}: 400 " + str(r.status_code))
r = Fr.put(url, json={"rules": [], "expect_rev": rev})
check(r.status_code == 409 and len(r.json().get("rules") or []) == 3, "an older expect_rev: 409 with the current rules " + r.text[:200])
check(A.put(url, json={"rules": []}).status_code == 404 and A.get(B + f"/api/sheets/{SID}").status_code == 404,
      "another person: 404 (her private table)")
r = ag.put(V + f"/sheets/{AS['id']}/rules", json={"rules": [{"cols": [AS["columns"][1]["id"]], "op": "lt", "a": "2", "color": "a"}]})
check(r.status_code == 400 and "version" in r.text, "the agents' route needs expect_rev " + r.text[:200])
r = ag.put(V + f"/sheets/{AS['id']}/rules", json={"rules": [{"cols": [AS["columns"][1]["id"]], "op": "lt", "a": "2", "color": "a"}],
                                                  "expect_rev": get(AS["id"])["rev"]})
check(r.ok and r.json()["rules"][0]["op"] == "lt", "an agent sets a rule with expect_rev " + r.text[:200])
spec = ag.get(V + "/openapi.json").json()
check("/sheets/{id}/rules" in spec.get("paths", {}) and "fmt" in spec["components"]["schemas"]["SheetCell"]["properties"],
      "the API document has the rules route and fmt")

# ================================================================== xlsx out and in
put(SID, [{"cell": "C2", "raw": "x"}, {"cell": "A5", "raw": "Total"}, {"cell": "A5", "fmt": {"merge": [1, 2], "bold": True, "wrap": True}},
          {"cell": "A3", "fmt": {"italic": True, "color": "a", "align": "right"}}])
r = Fr.get(B + f"/api/sheets/{SID}/export.xlsx")
check(r.ok and r.content[:2] == b"PK", "export .xlsx")
z = zipfile.ZipFile(io.BytesIO(r.content))
st, ws = z.read("xl/styles.xml").decode(), z.read("xl/worksheets/sheet1.xml").decode()
cx = re.findall(r"<xf [^>]*?(?:/>|>.*?</xf>)", re.search(r"<cellXfs[^>]*>(.*?)</cellXfs>", st, re.S).group(1), re.S)
fonts = re.findall(r"<font>.*?</font>", st, re.S)
fills = re.findall(r"<fill>.*?</fill>", st, re.S)


def xf_of(ref):
    m = re.search(rf'<c r="{ref}" s="(\d+)"', ws)
    return cx[int(m.group(1))] if m else ""


def font_of(xf):
    m = re.search(r'fontId="(\d+)"', xf)
    return fonts[int(m.group(1))] if m else ""


a2 = xf_of("A2")  # the data row 1 (row 1 of the file is the header)
check("<b/>" in font_of(a2) and "<i/>" in font_of(a2) and 'applyFill="1"' in a2, "A1 bold + italic + fill in the file " + a2)
m = re.search(r'fillId="(\d+)"', a2)
check(m and "E2F2F4" in fills[int(m.group(1))], "the light accent as its fixed shade")
a4 = xf_of("A4")
check('horizontal="right"' in a4 and "<i/>" in font_of(a4) and "187381" in font_of(a4), "A3 italic, accent text, right " + a4)
check('wrapText="1"' in xf_of("A6"), "A5 wraps")
check('<mergeCell ref="A6:B6"/>' in ws, "mergeCells A6:B6 " + ws[ws.find("<mergeCells"):][:120])
check('operator="greaterThan"' in ws and "<formula>10</formula>" in ws and 'type="containsText"' in ws and 'text="pea"' in ws
      and 'type="containsBlanks"' in ws, "the rules as conditionalFormatting")
check('sqref="A2:A3"' in ws, "a rule on chosen rows only covers those rows")
check(ws.index("</sheetData>") < ws.index("<mergeCells") < ws.index("<conditionalFormatting"), "OOXML order: sheetData, mergeCells, rules")
check(st.index("<numFmts") < st.index("<fonts") < st.index("<fills") < st.index("<borders") < st.index("<cellStyleXfs")
      < st.index("<cellXfs") < st.index("<cellStyles") < st.index("<dxfs"), "styles.xml in OOXML order")
r = Fr.post(B + "/api/sheets/import", data={"space": "private", "title": "Back again"}, files={"file": ("plan.xlsx", r.content)})
check(r.status_code == 201, "the exported file imports " + r.text[:200])
IM = get(r.json()["sheet"]["id"])
check(cell(IM, "A1").get("fmt") == {"bold": True, "fill": "a2", "italic": True} and cell(IM, "A1").get("raw") == "Apples",
      "import: A1's format again " + str(cell(IM, "A1").get("fmt")))
check(cell(IM, "A3").get("fmt") == {"align": "right", "color": "a", "italic": True}, "import: A3 " + str(cell(IM, "A3").get("fmt")))
check((cell(IM, "A5").get("fmt") or {}).get("merge") == [1, 2] and (cell(IM, "A5").get("fmt") or {}).get("wrap") is True,
      "import: the merged block " + str(cell(IM, "A5").get("fmt")))
ops = sorted(x["op"] for x in IM.get("rules") or [])
check(ops == ["contains", "empty", "gt"], "import: the rules " + str(IM.get("rules"))[:300])
gt = next((x for x in IM.get("rules") or [] if x["op"] == "gt"), {})
ct = next((x for x in IM.get("rules") or [] if x["op"] == "contains"), {})
im_cols = [c["id"] for c in IM["columns"]]
check(gt.get("cols") == [im_cols[1]] and gt.get("a") == "10" and gt.get("fill") == "a" and gt.get("rows") is None, "the gt rule " + str(gt))
check(ct.get("rows") == [IM["rows"][0]["id"], IM["rows"][1]["id"]] and ct.get("color") == "g1", "the rule on two rows " + str(ct))

# ================================================================== a copied sheet
r = Fr.post(B + f"/api/sheets/{SID}/tabs", json={"name": "Copy", "copy_of": SID})
check(r.status_code == 201, "a copy of the sheet " + r.text[:200])
CP = get(r.json()["tab"]["id"]) if r.status_code == 201 else {"cells": [], "columns": [], "rules": []}
cp_cols = [c["id"] for c in CP["columns"]]
check(cell(CP, "A1").get("fmt") == {"bold": True, "fill": "a2", "italic": True}, "the copy keeps the formats")
check(len(CP.get("rules") or []) == 3 and all(set(x["cols"]) <= set(cp_cols) for x in CP["rules"]), "the copy's rules point at its own columns")
# a row of a rule goes to the trash: the rules as read are saved again without that rule (no 400 for the whole list)
rr = next((x for x in CP.get("rules") or [] if x.get("rows")), None)
if rr:
    Fr.delete(B + f"/api/sheets/{CP['id']}/rows/{rr['rows'][0]}")
    r = Fr.put(B + f"/api/sheets/{CP['id']}/rules", json={"rules": CP["rules"]})
    check(r.ok and len(r.json().get("rules") or []) == 2, "a rule whose row is gone drops out, the others stay " + r.text[:200])
    r = Fr.put(B + f"/api/sheets/{CP['id']}/rules", json={"rules": [{**rr, "id": "new1"}]})
    check(r.status_code == 400, "a new rule on a row in the trash: 400")


# ================================================================== review fixes (Fable 2: G1-G8)
def rezip(content, fn):
    """The .xlsx with its first sheet's XML changed by fn."""
    zi, out = zipfile.ZipFile(io.BytesIO(content)), io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zi.namelist():
            data = zi.read(n)
            if n == "xl/worksheets/sheet1.xml":
                data = fn(data.decode()).encode()
            zo.writestr(n, data)
    return out.getvalue()


def imp(content, title):
    return Fr.post(B + "/api/sheets/import", data={"space": "private", "title": title}, files={"file": (title + ".xlsx", content)})


# a table of 40 rows x 10 columns, one filled cell per row (from a CSV)
csv_ = "h1;h2;h3;h4;h5;h6;h7;h8;h9;h10\n" + "".join(f"x{i};;;;;;;;;\n" for i in range(40))
r = Fr.post(B + "/api/sheets/import", data={"space": "private", "title": "Grid"}, files={"file": ("grid.csv", csv_.encode())})
check(r.status_code == 201, "a 40 x 10 table " + r.text[:200])
GID = r.json()["sheet"]["id"]
G = get(GID)
check(len(G["rows"]) == 40 and len(G["columns"]) == 10, "40 rows, 10 columns")
# G2: 360 formats on missing cells (40 stored + 360 > 300): refused like inputs, nothing stored
r = put(GID, [{"cell": f"{L}{n}", "fmt": {"fill": "g3"}} for L in "BCDEFGHIJ" for n in range(1, 41)])
check(r.status_code == 400 and "full" in r.text, "G2: formats on missing cells count against the table's cap " + str(r.status_code) + r.text[:120])
check(len(get(GID)["cells"]) == 40, "G2: no cell made")
# G6: an input changed in the meantime skips the whole entry, its format too
r = put(GID, [{"cell": "A1", "raw": "y", "prev": "not x0", "fmt": {"bold": True}}])
d = get(GID)
check(r.ok and (r.json().get("conflicts") or []) and cell(d, "A1").get("fmt") is None and cell(d, "A1")["raw"] == "x0",
      "G6: prev no longer fits: neither input nor format " + r.text[:200])
# G3: overlapping merged blocks
check(put(GID, [{"cell": "A1", "fmt": {"merge": [2, 2]}}]).ok, "G3: block A1:B2")
r = put(GID, [{"cell": "B2", "fmt": {"merge": [2, 2]}}])
check(r.status_code == 400 and cell(get(GID), "B2").get("fmt") is None, "G3: B2:C3 reaches into A1:B2: 400, nothing changed " + str(r.status_code))
r = put(GID, [{"cell": "C1", "fmt": {"merge": [1, 2]}}])
check(r.ok, "G3: a block beside it is fine " + r.text[:120])
check(put(GID, [{"cell": "A4", "fmt": {"merge": [1, 2], "bold": True}}]).ok, "G3: block A4:B4")
r = put(GID, [{"cell": "C1", "fmt": None}, {"cell": "A1", "fmt": {"merge": [4, 4]}}])
d = get(GID)
check(r.ok and cell(d, "A1").get("fmt") == {"merge": [4, 4]} and cell(d, "A4").get("fmt") == {"bold": True},
      "G3: a block lying inside a new one ends (its other format stays) " + str(cell(d, "A4").get("fmt")) + r.text[:120])
# G4: lists as rule ids / columns: 400 instead of 500
for bad, what in (({"id": [1], "cols": [G["columns"][0]["id"]], "op": "empty", "fill": "a"}, "a list as id"),
                  ({"cols": [[5]], "op": "empty", "fill": "a"}, "a list as column"),
                  ({"cols": [G["columns"][0]["id"]], "rows": [{"a": 1}, [2]], "op": "empty", "fill": "a"}, "lists as rows")):
    r = Fr.put(B + f"/api/sheets/{GID}/rules", json={"rules": [bad]})
    ok_ = r.status_code < 500 if what == "a list as id" else r.status_code == 400  # a list as id: a new id is given
    check(ok_, f"G4: {what}: no 500 " + str(r.status_code))

# a small table to export: A1 bold, a rule on two rows, a rule on a whole column
r = Fr.post(B + "/api/sheets", json={"title": "Caps", "space": "private"})
CA = r.json()
CID, CC, CR = CA["id"], [c["id"] for c in CA["columns"]], [x["id"] for x in CA["rows"]]
put(CID, [{"cell": f"{L}{n}", "raw": "x"} for L in "ABC" for n in range(1, 5)] + [{"cell": "A1", "fmt": {"bold": True}}])
r = Fr.put(B + f"/api/sheets/{CID}/rules", json={"rules": [{"cols": [CC[1]], "op": "empty", "fill": "a"},
                                                             {"cols": [CC[0]], "rows": [CR[0], CR[1]], "op": "contains", "a": "x", "color": "g1"}]})
check(r.ok, "Caps: two rules " + r.text[:200])
E1 = Fr.get(B + f"/api/sheets/{CID}/export.xlsx").content
s_bold = re.search(r'<c r="A2" s="(\d+)"', zipfile.ZipFile(io.BytesIO(E1)).read("xl/worksheets/sheet1.xml").decode()).group(1)
# G1: 420 formatted empty cells in a file (a cap of 300 per table): imported up to the cap, the rest reported
many = "".join(f'<row r="{n}">' + "".join(f'<c r="{L}{n}" s="{s_bold}"><v></v></c>' for L in "ABC") + "</row>" for n in range(20, 160))
many += '<row r="160"><c r="A160" t="inlineStr"><is><t>end</t></is></c></row>'  # a value at the end keeps the rows
r = imp(rezip(E1, lambda x: x.replace("</sheetData>", many + "</sheetData>")), "Many")
check(r.status_code == 201, "G1: the file imports " + r.text[:200])
if r.status_code == 201:
    rep_ = r.json()["report"]
    n = len(get(r.json()["sheet"]["id"])["cells"])
    check(n <= 300 and rep_.get("fmt_left_out", 0) >= 100, f"G1: formatted empty cells count against the cap ({n} cells, {rep_})")
    check(any("left out" in m for m in r.json().get("messages") or []), "G1: the message names the left-out formats " + str(r.json().get("messages")))
# G3: overlapping blocks in a file: the first one wins, the export has no overlap
mc = '<mergeCells count="2"><mergeCell ref="A2:B3"/><mergeCell ref="B3:C4"/></mergeCells>'
r = imp(rezip(E1, lambda x: x.replace("</sheetData>", "</sheetData>" + mc)), "Overlap")
check(r.status_code == 201, "G3: the file with overlapping blocks imports " + r.text[:200])
if r.status_code == 201:
    OV = get(r.json()["sheet"]["id"])
    ms = sorted((x["addr"], (x.get("fmt") or {}).get("merge")) for x in OV["cells"] if (x.get("fmt") or {}).get("merge"))
    check(ms == [("A1", [2, 2])], "G3: only the first block of the file " + str(ms))
    ws2 = zipfile.ZipFile(io.BytesIO(Fr.get(B + f"/api/sheets/{OV['id']}/export.xlsx").content)).read("xl/worksheets/sheet1.xml").decode()
    check(re.findall(r'<mergeCell ref="([^"]+)"', ws2) == ["A2:B3"], "G3: the export has one block " + ws2[ws2.find("<mergeCells"):][:160])
# G5: huge row numbers in a merge / a rule's range are skipped, the file still imports
huge = "1" * 5000
bad = (f'</sheetData><mergeCells count="1"><mergeCell ref="A2:B{huge}"/></mergeCells>'
       f'<conditionalFormatting sqref="C2:C{huge}"><cfRule type="containsBlanks" dxfId="0" priority="9"><formula>LEN(TRIM(C2))=0</formula></cfRule></conditionalFormatting>')
r = imp(rezip(E1, lambda x: x.replace("</sheetData>", bad, 1)), "Huge")
check(r.status_code == 201, "G5: a file with huge row numbers imports " + str(r.status_code) + r.text[:160])
# G8: one broken rule of a file (its text over 200 characters) drops only itself
long_ = "z" * 250
br = (f'<conditionalFormatting sqref="B2:B3"><cfRule type="containsText" dxfId="0" priority="9" operator="containsText" text="{long_}">'
      f'<formula>NOT(ISERROR(SEARCH("{long_}",B2)))</formula></cfRule></conditionalFormatting>')
r = imp(rezip(E1, lambda x: x.replace("<conditionalFormatting", br + "<conditionalFormatting", 1)), "Rules")
check(r.status_code == 201, "G8: the file imports " + r.text[:200])
if r.status_code == 201:
    ops = sorted(x["op"] for x in get(r.json()["sheet"]["id"]).get("rules") or [])
    check(ops == ["contains", "empty"] and r.json()["report"].get("rules_left_out") == 1,
          "G8: the two good rules stay, the broken one is counted " + str(ops) + str(r.json()["report"]))
# G7: a rule whose rows went to the trash is not in the export (the client colours nothing either)
Fr.delete(B + f"/api/sheets/{CID}/rows/{CR[0]}")
ws3 = zipfile.ZipFile(io.BytesIO(Fr.get(B + f"/api/sheets/{CID}/export.xlsx").content)).read("xl/worksheets/sheet1.xml").decode()
check('type="containsBlanks"' in ws3 and 'type="containsText"' not in ws3, "G7: the rule on trashed rows is left out of the file " + ws3[ws3.find("<conditionalFormatting"):][:200])

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
