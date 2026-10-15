#!/usr/bin/env python3
"""2.45.1 API tests, part B (#1556 devices with a German and an English name), own container in mode workspaces (start.sh).
Invented devices only; the spreadsheet is generated here (zipfile only, like p2391_f).
 - master data: POST / PATCH /api/office/equipment store name_en, the search finds the English name, the export carries it
 - legacy import: columns "Device DE" / "Device EN" (spaces and case do not matter) -> one device with both names; the old
   single column "device" still works; an existing device's English name counts as a duplicate; DE and EN in separate rows are
   joined only with an id column AND a language column, otherwise both rows stay; undo removes the imported devices
usage: p2451_b_api_test.py <datadir>"""
import io
import os
import subprocess
import sys
import zipfile
from xml.sax.saxutils import escape

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
L = "/api/office/legacy"
FAILS, OKS = [], [0]


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


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


# ---------------------------------------------------------------- an invented spreadsheet (zipfile only, as in p2391_f)
def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def make_xlsx(sheets, tables=None):
    """sheets: {name: [[cell, ...], ...]} (str -> shared string, int / float -> number); tables: {sheet: table name}."""
    tables = tables or {}
    strings, sidx = [], {}

    def si(v):
        if v not in sidx:
            sidx[v] = len(strings)
            strings.append(v)
        return sidx[v]
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        names = list(sheets)
        ct = ['<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>',
              '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>']
        wb = ['<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
        rels = ['<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
        tno = 0
        for k, nm in enumerate(names, 1):
            rows = sheets[nm]
            wb.append(f'<sheet name="{escape(nm)}" sheetId="{k}" r:id="rId{k}"/>')
            rels.append(f'<Relationship Id="rId{k}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{k}.xml"/>')
            ct.append(f'<Override PartName="/xl/worksheets/sheet{k}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
            x = ['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
            for r, row in enumerate(rows, 1):
                x.append(f'<row r="{r}">')
                for ci, v in enumerate(row):
                    if v is None or v == "":
                        continue
                    ref = f"{_col(ci)}{r}"
                    if isinstance(v, (int, float)):
                        x.append(f'<c r="{ref}"><v>{v}</v></c>')
                    else:
                        x.append(f'<c r="{ref}" t="s"><v>{si(v)}</v></c>')
                x.append("</row>")
            x.append("</sheetData>")
            if nm in tables:
                tno += 1
                x.append('<tableParts count="1"><tablePart xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rIdT1"/></tableParts>')
                width = max(len(r) for r in rows)
                f.writestr(f"xl/tables/table{tno}.xml", f'<?xml version="1.0" encoding="UTF-8"?><table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                                                        f'id="{tno}" name="{tables[nm]}" displayName="{tables[nm]}" ref="A1:{_col(width - 1)}{len(rows)}"/>')
                f.writestr(f"xl/worksheets/_rels/sheet{k}.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           f'<Relationship Id="rIdT1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" Target="../tables/table{tno}.xml"/></Relationships>')
                ct.append(f'<Override PartName="/xl/tables/table{tno}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>')
            x.append("</worksheet>")
            f.writestr(f"xl/worksheets/sheet{k}.xml", "".join(x))
        wb.append("</sheets></workbook>")
        rels.append(f'<Relationship Id="rIdS" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>')
        ct.append('<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
        f.writestr("[Content_Types].xml", "".join(ct))
        f.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        f.writestr("xl/workbook.xml", "".join(wb))
        f.writestr("xl/_rels/workbook.xml.rels", "".join(rels))
        f.writestr("xl/sharedStrings.xml", '<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + "".join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings) + "</sst>")
    return z.getvalue()


# ---------------------------------------------------------------- setup: one organisation with its admin
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,office,clients", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
E = "/api/office/equipment"

# ---------------------------------------------------------------- master data
r = A.post(B + E, json={"name": "Stativ gross", "name_en": "Large tripod", "category": "Kamera", "daily_rate": 30})
check(r.status_code == 201 and r.json().get("name_en") == "Large tripod", "master data: POST stores name_en " + r.text[:200])
TRI = r.json()["id"]
r = A.patch(B + E + f"/{TRI}", json={"name_en": "Big tripod"})
check(r.ok and r.json().get("name_en") == "Big tripod", "master data: PATCH changes name_en " + r.text[:200])
r = A.post(B + E, json={"name": "Monitor"})
check(r.status_code == 201 and r.json().get("name_en") == "", "master data: without name_en = '' " + r.text[:200])
r = A.get(B + E, params={"q": "big trip"})
check(r.ok and [x["id"] for x in r.json()["items"]] == [TRI], f"master data: the search finds the English name {r.text[:200]}")
r = A.get(B + "/api/office/export")
check(r.ok and any(x.get("name_en") == "Big tripod" for x in r.json().get("equipment", [])), "export: the device file carries name_en")

# ---------------------------------------------------------------- legacy import: two language columns
X1 = make_xlsx({"Equipment": [["Device DE", "Device_EN", "Category", "Daily rate"],
                              ["---- LICHT ----"],
                              ["Lichtkoffer", "Light kit", "", 90],
                              ["Funkstrecke", "Wireless kit", "Ton", 40],
                              ["Stativ klein", "Big tripod", "Kamera", 20],     # its English name = an existing device's
                              ["Akku-Set", "", "Strom", 15]]})
r = A.post(B + L + "/preview", files={"file": ("DATA.xlsx", X1)})
check(r.ok, "preview " + r.text[:200])
EQ = r.json()["equipment"]
check([(x["name"], x["name_en"]) for x in EQ] == [("Lichtkoffer", "Light kit"), ("Funkstrecke", "Wireless kit"), ("Stativ klein", "Big tripod"), ("Akku-Set", "")],
      f"preview: 'Device DE' / 'Device EN' read as both names {[(x['name'], x['name_en']) for x in EQ]}")
check(EQ[0]["category"] == "Licht" and EQ[0]["daily_rate"] == 90, f"preview: separator category + 'Daily rate' column {EQ[0]}")
check([x["action"] for x in EQ] == ["new", "new", "skip", "new"] and EQ[2]["dup"], "preview: an existing device's English name is a duplicate")
check(dbx("SELECT COUNT(*) FROM office_equipment WHERE name='Lichtkoffer'")[0][0] == 0, "preview stores nothing")
r = A.post(B + L + "/import", json={"clients": [], "services": [], "equipment": EQ})
check(r.status_code == 201 and r.json()["counts"]["equipment"] == 3, "import " + r.text[:200])
RUN = r.json()["run_id"]
got = {x["name"]: x["name_en"] for x in A.get(B + E).json()["items"]}
check(got.get("Lichtkoffer") == "Light kit" and got.get("Funkstrecke") == "Wireless kit" and got.get("Akku-Set") == "" and "Stativ klein" not in got,
      f"import: one device per row with both names {got}")
r = A.post(B + L + "/preview", files={"file": ("DATA.xlsx", X1)})
check(r.ok and [x["action"] for x in r.json()["equipment"]] == ["skip"] * 4, "preview again: everything exists already")

# ---------------------------------------------------------------- the old single column, separate language rows
X2 = make_xlsx({"Geräte": [["Gerät", "Kategorie", "Tagessatz"], ["Kamera-Set A", "Kamera", 250]]})
r = A.post(B + L + "/preview", files={"file": ("DATA.xlsx", X2)})
check(r.ok and [(x["name"], x["name_en"]) for x in r.json()["equipment"]] == [("Kamera-Set A", "")], "preview: the old single column still works " + r.text[:200])
X3 = make_xlsx({"Equipment": [["Article no", "Language", "Device"], ["K-1", "DE", "Kran"], ["K-1", "EN", "Crane"], ["D-2", "de", "Dolly"], ["D-2", "en", "Dolly track"]]})
r = A.post(B + L + "/preview", files={"file": ("DATA.xlsx", X3)})
check(r.ok and [(x["name"], x["name_en"]) for x in r.json()["equipment"]] == [("Kran", "Crane"), ("Dolly", "Dolly track")],
      "preview: DE and EN rows with the same article number and a language column = one device " + r.text[:300])
X4 = make_xlsx({"Equipment": [["Device"], ["Kran"], ["Crane"]]})
r = A.post(B + L + "/preview", files={"file": ("DATA.xlsx", X4)})
check(r.ok and [(x["name"], x["name_en"]) for x in r.json()["equipment"]] == [("Kran", ""), ("Crane", "")],
      "preview: without an id and a language column nothing is joined (no guessing) " + r.text[:300])
X5 = make_xlsx({"Equipment": [["Article no", "Language", "Device"], ["T-9", "DE", "Stativ neu"], ["T-9", "EN", "Big tripod"]]})
r = A.post(B + L + "/preview", files={"file": ("DATA.xlsx", X5)})
check(r.ok and [(x["name_en"], x["action"]) for x in r.json()["equipment"]] == [("Big tripod", "skip")],
      "preview: a joined English row whose name exists already makes the device a duplicate (review) " + r.text[:300])

# ---------------------------------------------------------------- undo
r = A.post(B + L + f"/runs/{RUN}/undo")
check(r.ok and r.json()["removed"]["equipment"] == 3, "undo removes the imported devices " + r.text[:200])
names = {x["name"] for x in A.get(B + E).json()["items"]}
check(names == {"Stativ gross", "Monitor"}, f"undo keeps the devices made by hand {names}")

print(f"p2451_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
