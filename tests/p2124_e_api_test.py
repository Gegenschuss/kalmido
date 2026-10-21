#!/usr/bin/env python3
"""2.124.0 API tests, part E (#2116): several sheets in one table, own container (start.sh). Invented names only, the
.xlsx files are made here.
 - a table starts with one sheet (as before: tabs = [itself], the index counts 1); a new sheet, renaming (unique names),
   moving in the bar, the trash (the first sheet carries the table: 409) and back
 - the index, the API v1 list: only the table (with its number of sheets), never a further sheet on its own
 - formulas across sheets: Costs!A1, 'Cost data'!A1:A3, SUMMEWENN / SVERWEIS over another sheet, a renamed sheet keeps the
   formula, a change shows on the next read, a deleted sheet = "ref" (back with Undo), sheets reading each other = cycle,
   an unknown sheet = 400
 - rights: who reads the table reads all its sheets and writes none (a read share of part C), a write share writes every
   sheet, shares only on the first sheet (409), the list only there (409); a stranger 404 everywhere (tenant-matrix: sheet)
 - moving the table to the organisation and back takes every sheet along (also when asked through a further sheet)
 - .xlsx with three sheets in, all three out (with the formula into another sheet); CSV stays one sheet
 - agents: their own table gets a sheet through API v1 (one batch; taking it back = the sheet to the trash), another
   organisation's agent 404 (tenant-matrix: sheet_v1)
 - a person without an organisation (freelancer-matrix: sheets)
usage: p2124_e_api_test.py <datadir>      (a fresh container; P2124E_NOSTART=1 = the server already runs)"""
import io
import os
import subprocess
import sys
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "sheets,collab,comments,office"


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


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


if not os.environ.get("P2124E_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "erin" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["erin"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ca, Er = sess("bob"), sess("carol"), sess("erin")
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
SW = ["read", "sheets:read", "sheets:write"]


def agent(name, org=None, owner=None):
    body = {"scopes": SW, "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


TA, ta = agent("alphabot", org=ORG)
BB, bb = agent("betabot", org=BETA)


def new(s, title, space="private", **b):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space, **b})
    assert r.status_code == 201, r.text
    return r.json()


def get(s, sid):
    r = s.get(B + f"/api/sheets/{sid}")
    return r.json() if r.ok else {"_status": r.status_code}


def tabs(s, sid):
    r = s.get(B + f"/api/sheets/{sid}/tabs")
    return [t["id"] for t in r.json()["tabs"]] if r.ok else None


def put(s, sid, cell, raw):
    return s.put(B + f"/api/sheets/{sid}/cells", json={"cells": [{"cell": cell, "raw": raw}]})


def at(d, addr):
    return next((c for c in d.get("cells", []) if c["addr"] == addr), {})


def index(s, space="all"):
    r = s.get(B + "/api/sheets", params={"space": space})
    return {x["id"]: x for x in r.json()["sheets"]} if r.ok else {}


# ================================================================ one sheet: as before
T = new(Bo, "Budget")["id"]
d = get(Bo, T)
check(d.get("book_id") == T and [t["id"] for t in d.get("tabs", [])] == [T] and d.get("book_title") == "Budget",
      "a new table has one sheet " + str({k: d.get(k) for k in ("book_id", "tabs", "book_title")}))
check(index(Bo)[T].get("sheets") == 1, "the index counts one sheet")

# ================================================================ a new sheet, names, order
r = Bo.post(B + f"/api/sheets/{T}/tabs", json={})
check(r.status_code == 201 and len(r.json()["tabs"]) == 2, "a second sheet " + r.text[:300])
S2 = r.json()["tab"]["id"] if r.ok else 0
check([t["name"] for t in r.json().get("tabs", [])] == ["Sheet 1", "Sheet 2"], "the sheets are named Sheet 1, Sheet 2 " + r.text[:200])
check(Bo.patch(B + f"/api/sheets/{T}/tabs/{S2}", json={"name": "Costs"}).ok, "renamed to Costs")
check(Bo.patch(B + f"/api/sheets/{T}/tabs/{S2}", json={"name": "sheet 1"}).status_code == 400, "a name taken (any case): 400")
check(Bo.post(B + f"/api/sheets/{T}/tabs", json={"name": "costs"}).status_code == 400, "a new sheet with a taken name: 400")
d2 = get(Bo, S2)
check(d2.get("book_id") == T and d2.get("tab_name") == "Costs" and d2.get("book_title") == "Budget" and d2.get("can_write") is True,
      "the further sheet knows its table " + str({k: d2.get(k) for k in ("book_id", "tab_name", "book_title")}))
ix = index(Bo)
check(T in ix and S2 not in ix and ix[T].get("sheets") == 2, "the index: the table once, with 2 sheets")
check(S2 not in [x["id"] for x in index(Bo, "private").values()], "... also in the private space")
S3 = Bo.post(B + f"/api/sheets/{S2}/tabs", json={"name": "Notes", "after_id": T}).json()["tab"]["id"]  # through a further sheet
check(tabs(Bo, T) == [T, S3, S2], "after_id: the new sheet right after the first " + str(tabs(Bo, T)))
check(Bo.patch(B + f"/api/sheets/{T}/tabs/{S2}", json={"pos": 0}).ok and tabs(Bo, T) == [S2, T, S3], "moved to the front")
check(Bo.patch(B + f"/api/sheets/{T}/tabs/{S2}", json={"pos": 9}).status_code == 400, "a place out of range: 400")
check(Bo.patch(B + f"/api/sheets/{T}", json={"title": "Budget 2027"}).ok and get(Bo, S2).get("book_title") == "Budget 2027",
      "renaming the table shows on every sheet")

# ================================================================ formulas across sheets
check(put(Bo, S2, "A1", "5").ok and put(Bo, S2, "A2", "7").ok and put(Bo, S2, "B1", "x").ok, "values in Costs")
r = put(Bo, T, "A1", "=Costs!A1*2")
check(r.ok, "a formula into Costs " + r.text[:300])
check(at(get(Bo, T), "A1").get("value") == 10, "Costs!A1*2 = 10 " + str(at(get(Bo, T), "A1")))
check(put(Bo, T, "A2", "=SUMME(Costs!A1:A3)").ok and at(get(Bo, T), "A2").get("value") == 12, "SUMME(Costs!A1:A3) = 12")
check(put(Bo, T, "A3", '=SVERWEIS(5;Costs!A1:B3;2;FALSCH)').ok and at(get(Bo, T), "A3").get("value") == "x", "SVERWEIS over another sheet " + str(at(get(Bo, T), "A3")))
check(put(Bo, T, "A4", '=SUMMEWENN(Costs!A1:A3;">6")').ok and at(get(Bo, T), "A4").get("value") == 7, "SUMMEWENN over another sheet")
check(Bo.patch(B + f"/api/sheets/{T}/tabs/{S2}", json={"name": "Cost data"}).ok, "Costs renamed")
d = get(Bo, T)
check(at(d, "A1").get("raw") == "='Cost data'!A1*2" and at(d, "A1").get("value") == 10, "a renamed sheet keeps the formula " + str(at(d, "A1").get("raw")))
check(at(d, "A2").get("raw") == "=SUMME('Cost data'!A1:A3)", "a range is written Name!A1:A3 " + str(at(d, "A2").get("raw")))
check(put(Bo, S2, "A1", "8").ok and at(get(Bo, T), "A1").get("value") == 16, "a change in the other sheet shows")
check(put(Bo, T, "B1", "=Nowhere!A1").status_code == 400, "an unknown sheet: 400")
check(put(Bo, T, "B1", "='Cost data'!Z99").status_code == 400, "a cell that does not exist: 400")
check(put(Bo, T, "B2", "='Sheet 1'!A1+1").ok and at(get(Bo, T), "B2").get("value") == 17, "its own sheet by name")
# sheets reading each other in a circle
check(put(Bo, T, "C1", "='Cost data'!C1").ok and put(Bo, S2, "C1", "='Sheet 1'!C1").ok, "two sheets reading each other")
check(at(get(Bo, T), "C1").get("error") == "cycle" and at(get(Bo, S2), "C1").get("error") == "cycle", "... = Circular reference")
rv = get(Bo, T)["rev"]
put(Bo, S2, "A2", "9")
check(get(Bo, T)["rev"] > rv, "a change in one sheet counts the other sheets' rev up (they reload)")
# the trash
check(Bo.delete(B + f"/api/sheets/{T}/tabs/{T}").status_code == 409, "the first sheet carries the table: 409")
r = Bo.delete(B + f"/api/sheets/{T}/tabs/{S2}")
check(r.ok and S2 not in [t["id"] for t in r.json()["tabs"]], "a sheet to the trash")
check(get(Bo, S2).get("_status") == 404, "... gone")
check(at(get(Bo, T), "A1").get("error") == "ref", "a formula into it: Reference not found")
check(Bo.post(B + f"/api/sheets/{T}/tabs/{S2}/restore").ok and at(get(Bo, T), "A1").get("value") == 16, "Undo: back, the value too")
check(Bo.post(B + f"/api/sheets/{T}/tabs/{S2}/restore").status_code == 404, "restoring a live sheet: 404")
# the whole table in the trash: every sheet is gone with it
check(Bo.delete(B + f"/api/sheets/{T}").ok and get(Bo, S2).get("_status") == 404 and tabs(Bo, S2) is None, "the table in the trash: its sheets too")
check(Bo.post(B + f"/api/sheets/{T}/restore").ok and get(Bo, S2).get("tab_name") == "Cost data", "restored: the sheets are back")

# ================================================================ rights
# tenant-matrix: sheet
for what, resp in (("read", Er.get(B + f"/api/sheets/{S2}")), ("tabs", Er.get(B + f"/api/sheets/{T}/tabs")),
                   ("add", Er.post(B + f"/api/sheets/{T}/tabs", json={})), ("rename", Er.patch(B + f"/api/sheets/{T}/tabs/{S2}", json={"name": "x"})),
                   ("delete", Er.delete(B + f"/api/sheets/{T}/tabs/{S2}")), ("restore", Er.post(B + f"/api/sheets/{T}/tabs/{S2}/restore")),
                   ("cells", put(Er, S2, "A1", "1")), ("carol, no share", Ca.get(B + f"/api/sheets/{S2}"))):
    check(resp.status_code == 404, f"a stranger / another person: {what} 404 ({resp.status_code})")
r = Bo.post(B + f"/api/sheets/{T}/shares", json={"user_id": uid["carol"], "role": "read"})
check(r.status_code == 201, "shared with carol to read " + r.text[:200])
SH = r.json().get("id")
d = get(Ca, S2)
check(d.get("can_write") is False and d.get("shared_in") is True and at(d, "A1").get("value") == 8, "a read share reads every sheet " + str(d.get("_status")))
check(at(get(Ca, T), "A1").get("value") == 16, "... with the formulas across sheets")
check(put(Ca, S2, "A1", "1").status_code == 403 and Ca.post(B + f"/api/sheets/{T}/tabs", json={}).status_code == 403
      and Ca.patch(B + f"/api/sheets/{T}/tabs/{S2}", json={"name": "Mine"}).status_code == 403, "... writes no sheet, adds / renames none")
check(Bo.post(B + f"/api/sheets/{S2}/shares", json={"user_id": uid["alice"], "role": "read"}).status_code == 409, "shares only on the first sheet: 409")
check(Bo.get(B + f"/api/sheets/{S2}/shares").status_code == 409, "... also the list of shares")
check(Bo.patch(B + f"/api/sheets/{T}/shares/{SH}", json={"role": "write"}).ok, "carol may write now")
check(put(Ca, S2, "A2", "11").ok and Ca.post(B + f"/api/sheets/{T}/tabs", json={"name": "Carol"}).status_code == 201, "a write share writes and adds sheets")
check(Ca.delete(B + f"/api/sheets/{T}").status_code == 403, "... but never deletes the table")
L = Bo.post(B + "/api/lists", json={"name": "Trip", "org_id": None}).json()["id"]
check(Bo.patch(B + f"/api/sheets/{S2}", json={"list_id": L}).status_code == 409, "the list only on the first sheet: 409")
check(Bo.patch(B + f"/api/sheets/{T}", json={"list_id": L}).ok and get(Bo, S2).get("list_id") == L, "attached on the first sheet: every sheet")
check(Bo.patch(B + f"/api/sheets/{T}", json={"list_id": None}).ok and get(Bo, S2).get("list_id") is None, "detached: every sheet")

# ================================================================ moving between workspaces
r = Bo.post(B + f"/api/sheets/{S2}/move-space", json={"to": SP})  # asked through a further sheet
check(r.ok and r.json().get("space") == SP, "moved to the organisation (through a further sheet) " + r.text[:300])
check(get(Bo, S2).get("space") == SP and get(Bo, S3).get("space") == SP, "every sheet moved")
check(get(A, S2).get("can_write") is True, "alice (member) writes the further sheet now")
check(at(get(A, T), "A1").get("value") == 16, "... and the formula across sheets reads for her")
check(Bo.post(B + f"/api/sheets/{T}/move-space", json={"to": "private"}).status_code == 403, "#2483: a member does not take it out (403)")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "admin"}).ok, "setup: bob an admin")  # 2.148.1 (#2483)
r = Bo.post(B + f"/api/sheets/{T}/move-space", json={"to": "private"})
check(r.ok and get(Bo, S2).get("space") == "private" and get(A, S2).get("_status") == 404, "back to private: every sheet " + r.text[:200])

# ================================================================ .xlsx: three sheets in, all out


def xlsx(sheets):
    """sheets: [(name, [[value | "=formula", ...], ...])] -> the bytes of a small .xlsx (inline strings)."""
    def col(i):
        return chr(65 + i)
    wb_sheets, rels, ct, files = [], [], [], {}
    for k, (name, rows) in enumerate(sheets, 1):
        cells = []
        for ri, row in enumerate(rows, 1):
            cs = []
            for ci, v in enumerate(row):
                ref = f"{col(ci)}{ri}"
                if isinstance(v, str) and v.startswith("="):
                    cs.append(f'<c r="{ref}"><f>{v[1:]}</f><v>0</v></c>')
                elif isinstance(v, (int, float)):
                    cs.append(f'<c r="{ref}"><v>{v}</v></c>')
                else:
                    cs.append(f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>')
            cells.append(f'<row r="{ri}">{"".join(cs)}</row>')
        files[f"xl/worksheets/sheet{k}.xml"] = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
                                                f'spreadsheetml/2006/main"><sheetData>{"".join(cells)}</sheetData></worksheet>')
        wb_sheets.append(f'<sheet name="{name}" sheetId="{k}" r:id="rId{k}"/>')
        rels.append(f'<Relationship Id="rId{k}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                    f'Target="worksheets/sheet{k}.xml"/>')
        ct.append(f'<Override PartName="/xl/worksheets/sheet{k}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
    files["xl/workbook.xml"] = ('<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                                f'<sheets>{"".join(wb_sheets)}</sheets></workbook>')
    files["xl/_rels/workbook.xml.rels"] = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                                           f'package/2006/relationships">{"".join(rels)}</Relationships>')
    files["[Content_Types].xml"] = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                                    '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" '
                                    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                                    f'{"".join(ct)}</Types>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


XL = xlsx([("Summary", [["Item", "Total"], ["Gear", "=Prices!B2*Amounts!B2"], ["Crew", "='Prices'!B3*2"]]),
           ("Prices", [["Item", "Price"], ["Gear", 40], ["Crew", 300]]),
           ("Amounts", [["Item", "Amount"], ["Gear", 3]])])
r = Bo.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("Shoot.xlsx", XL)})
check(r.status_code == 201 and r.json()["report"].get("sheets") == 3, "an .xlsx with three sheets " + r.text[:400])
IM = r.json()["sheet"]["id"] if r.ok else 0
check(any("3 sheets" in m for m in r.json().get("messages", [])), "the answer names the sheets " + str(r.json().get("messages")))
d = get(Bo, IM)
check([t["name"] for t in d.get("tabs", [])] == ["Summary", "Prices", "Amounts"], "three sheets with their names " + str(d.get("tabs")))
check(at(d, "B1").get("value") == 120 and at(d, "B1").get("raw") == "=Prices!B1*Amounts!B1", "a formula into other sheets taken over " + str(at(d, "B1")))
check(at(d, "B2").get("value") == 600, "'Prices'!B3*2 taken over " + str(at(d, "B2")))
check(index(Bo)[IM].get("sheets") == 3, "the index: one table, 3 sheets")
r = Bo.get(B + f"/api/sheets/{IM}/export.xlsx")
z = zipfile.ZipFile(io.BytesIO(r.content)) if r.ok else None
wb = z.read("xl/workbook.xml").decode() if z else ""
check(z is not None and all(f'name="{n}"' in wb for n in ("Summary", "Prices", "Amounts"))
      and {"xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml", "xl/worksheets/sheet3.xml"} <= set(z.namelist()), "the export holds all three sheets")
ws1 = z.read("xl/worksheets/sheet1.xml").decode() if z else ""
check("<f>'Prices'!B2*'Amounts'!B2</f>" in ws1, "... with the formula into the other sheets " + ws1[:600])
r2 = Bo.post(B + "/api/sheets/import", data={"space": "private"}, files={"file": ("again.xlsx", r.content)})
check(r2.status_code == 201 and r2.json()["report"].get("sheets") == 3, "the export reads back in: 3 sheets " + r2.text[:300])
d = get(Bo, r2.json()["sheet"]["id"]) if r2.ok else {}
check(at(d, "B1").get("value") == 120, "... with the formula across sheets " + str(at(d, "B1")))
ex = Bo.get(B + f"/api/sheets/{d.get('tabs', [{}, {}])[1].get('id')}/export.xlsx") if d else None
check(ex is not None and ex.ok and zipfile.ZipFile(io.BytesIO(ex.content)).read("xl/workbook.xml").decode().count("<sheet ") == 3,
      "the export of a further sheet writes the whole table")
csv = Bo.get(B + f"/api/sheets/{IM}/export.csv")
check(csv.ok and "Gear" in csv.text and "Price" not in csv.text, "CSV: one sheet (the one asked for)")

# ================================================================ agents (API v1)
# tenant-matrix: sheet_v1
r = ta.post(V + "/sheets", json={"title": "Bot plan", "space": SP})
check(r.status_code == 201, "the agent's own table " + r.text[:200])
AT = r.json()["id"] if r.ok else 0
r = ta.post(V + f"/sheets/{AT}/tabs", json={"name": "Data", "columns": [{"title": "N", "kind": "number"}], "rows": [[1], [2]]})
check(r.status_code == 201 and r.json().get("batch") and r.json().get("book_id") == AT, "the agent adds a sheet (one batch) " + r.text[:300])
AS, BAT = (r.json()["id"], r.json()["batch"]) if r.ok else (0, "")
r = ta.get(V + f"/sheets/{AT}/tabs")
check(r.ok and [t["id"] for t in r.json()["data"]] == [AT, AS], "the agent lists the sheets " + r.text[:200])
check(ta.put(V + f"/sheets/{AT}/cells", json={"cells": [{"cell": "A1", "raw": "=SUMME(Data!A1:A2)"}]}).ok, "a formula into its sheet")
check(at(ta.get(V + f"/sheets/{AT}").json(), "A1").get("value") == 3, "... = 3")
check(AT in [x["id"] for x in ta.get(V + "/sheets").json()["data"]] and AS not in [x["id"] for x in ta.get(V + "/sheets").json()["data"]],
      "API v1 list: the table, not its further sheet")
check(bb.get(V + f"/sheets/{AT}/tabs").status_code == 404 and bb.post(V + f"/sheets/{AT}/tabs", json={}).status_code == 404
      and bb.get(V + f"/sheets/{AS}").status_code == 404, "another organisation's agent: 404")
check(ta.get(V + f"/sheets/{T}/tabs").status_code == 404, "a private table of a person: 404 for the agent")
check(ta.post(V + f"/sheets/{AS}/batches/{BAT}/undo").ok and ta.get(V + f"/sheets/{AS}").status_code == 404, "taking the call back: the sheet to the trash")
check(ta.post(V + f"/sheets/{AT}/tabs", json={"bogus": 1}).status_code == 400, "unknown fields: 400")

# ================================================================ a person without an organisation
# freelancer-matrix: sheets
FID, Fl = freelancer(B, A, features=FEATURES + ",sheets")
FT = new(Fl, "Rates")["id"]
r = Fl.post(B + f"/api/sheets/{FT}/tabs", json={"name": "Clients"})
check(r.status_code == 201, "freelancer: a further sheet " + r.text[:200])
FS = r.json()["tab"]["id"] if r.ok else 0
check(put(Fl, FS, "A1", "90").ok and put(Fl, FT, "A1", "=Clients!A1/2").ok and at(get(Fl, FT), "A1").get("value") == 45, "freelancer: a formula across sheets")
check(Fl.get(B + f"/api/sheets/{FT}/tabs").ok and Fl.patch(B + f"/api/sheets/{FT}/tabs/{FS}", json={"name": "Customers", "pos": 0}).ok, "freelancer: rename, move")
check(Fl.delete(B + f"/api/sheets/{FT}/tabs/{FS}").ok and Fl.post(B + f"/api/sheets/{FT}/tabs/{FS}/restore").ok, "freelancer: the trash and back")
check(Bo.get(B + f"/api/sheets/{FS}").status_code == 404, "another person never sees it")
DA, da = agent("fridabot", owner=FID)  # her personal agent (API v1)
r = da.post(V + "/sheets", json={"title": "Bot rates", "space": "private"})
DT = r.json()["id"] if r.status_code == 201 else 0
r = da.post(V + f"/sheets/{DT}/tabs", json={"name": "More"})
check(r.status_code == 201 and da.get(V + f"/sheets/{DT}/tabs").ok, "freelancer's agent: a further sheet in API v1 " + r.text[:200])
check(Fl.get(B + f"/api/sheets/{r.json().get('id')}").ok if r.ok else False, "... she sees it in the app")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
