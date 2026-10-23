#!/usr/bin/env python3
"""2.46.1 API tests, part C (#1557 legacy import per area), own container in mode workspaces (start.sh).
Invented clients, services and devices only; the spreadsheet is generated here (zipfile only, as in p2391_f / p2451_b).
 - import: only the areas switched on are written (areas=[...]); an area switched off is not even checked (a later import of
   the same file with only the equipment works without the addresses)
 - undo per area (kinds=[...]): only that area goes, the run remembers it (runs list: areas.<kind>.undone_at), the same area
   twice -> 409, the second area -> the whole run counts as undone; the whole undo after a partial one takes the rest only;
   a client in use stays (also for the whole undo later); kinds are checked (unknown -> 400, an archive run -> 400)
usage: p2461_c_import_api_test.py <datadir>"""
import io
import os
import subprocess
import sys
import zipfile
from xml.sax.saxutils import escape

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
L = "/api/office/legacy"
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


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
if not os.environ.get("KMT_NOSTART"):  # KMT_NOSTART=1: against an app in mode workspaces that already runs (a quick local check)
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


def sheet(tag):
    return make_xlsx({"Contacts": [["Address"], [f"{tag} Studio GmbH\nMusterweg 1\n12345 Musterstadt"], [f"{tag} Film KG\nBeispielstr. 2\n54321 Beispielort"]],
                      "Services": [["serviceDE", "dailyrate"], [f"{tag} Kamera", 500], [f"{tag} Schnitt", 400]],
                      "Equipment": [["Device", "Daily rate"], [f"{tag} Stativ", 20], [f"{tag} Licht", 60], [f"{tag} Ton", 40]]})


def preview(x):
    r = A.post(B + L + "/preview", files={"file": ("DATA.xlsx", x)})
    assert r.ok, r.text
    return r.json()


def names():
    return ({x["name"] for x in A.get(B + "/api/clients").json().get("clients", []) if not x.get("archived")},
            {x["name_de"] for x in A.get(B + "/api/office/services").json().get("items", [])},
            {x["name"] for x in A.get(B + "/api/office/equipment").json().get("items", [])})


def run(rid):
    return next((x for x in A.get(B + L + "/runs").json()["runs"] if x["id"] == rid), {})


# ---------------------------------------------------------------- import only some areas
P1 = preview(sheet("Ax"))
check(len(P1["clients"]) == 2 and len(P1["services"]) == 2 and len(P1["equipment"]) == 3, f"preview of three areas {[len(P1[k]) for k in ('clients', 'services', 'equipment')]}")
r = A.post(B + L + "/import", json={"clients": P1["clients"], "services": P1["services"], "equipment": P1["equipment"], "areas": ["clients", "services"]})
check(r.status_code == 201 and r.json()["counts"]["clients"] == 2 and r.json()["counts"]["services"] == 2 and r.json()["counts"]["equipment"] == 0,
      "#1557: only the areas switched on are written " + r.text[:200])
R1 = r.json()["run_id"]
cl, sv, eq = names()
check({"Ax Studio GmbH", "Ax Film KG"} <= cl and {"Ax Kamera", "Ax Schnitt"} <= sv and not any(n.startswith("Ax") for n in eq), f"#1557: clients + services, no equipment {cl} {sv} {eq}")
check(set(run(R1).get("areas", {})) == {"clients", "services"}, f"#1557: the run lists its areas {run(R1)}")
# the same file again, only the equipment: the addresses are not checked (a broken client row does not stop it)
P1b = preview(sheet("Ax"))
check(all(x["action"] == "skip" for x in P1b["clients"]), "#1557: the addresses are duplicates now")
bad = [{"row": 2, "action": "merge", "merge_id": "x"}]
r = A.post(B + L + "/import", json={"clients": bad, "services": P1b["services"], "equipment": P1b["equipment"], "areas": ["equipment"]})
check(r.status_code == 201 and r.json()["counts"]["equipment"] == 3 and r.json()["counts"]["clients"] == 0, "#1557: a later import with only the equipment " + r.text[:200])
R2 = r.json()["run_id"]
check({"Ax Stativ", "Ax Licht", "Ax Ton"} <= names()[2], "#1557: the devices are there")
r = A.post(B + L + "/import", json={"clients": bad, "areas": ["clients"]})
check(r.status_code == 400, "#1557: the clients area switched on is checked as before")
for ar in (["bogus"], "equipment"):
    r = A.post(B + L + "/import", json={"equipment": P1b["equipment"], "areas": ar})
    check(r.status_code == 400, f"#1557: areas {ar!r} -> 400")
r = A.post(B + L + "/import", json={"clients": [], "services": P1["services"]})
check(r.status_code == 201, "#1557: without areas every area is taken as before (old clients)")
A.post(B + L + f"/runs/{r.json()['run_id']}/undo")
# 2.58.0 (#1557): a run without entries is not fully undone after its first partial undo
r = A.post(B + L + "/import", json={"clients": [], "services": [], "equipment": [], "areas": ["clients", "services"]})
check(r.status_code == 201, "#1557: an import without entries " + r.text[:200])
RE = r.json().get("run_id")
check(A.post(B + L + f"/runs/{RE}/undo", json={"kinds": ["services"]}).ok and not run(RE).get("undone_at"),
      f"#1557: a run without entries stays open after one partial undo {run(RE)}")
check(A.post(B + L + f"/runs/{RE}/undo").ok and run(RE).get("undone_at"), "#1557: the whole undo then closes it")

# ---------------------------------------------------------------- undo per area
r = A.post(B + L + f"/runs/{R1}/undo", json={"kinds": ["services"]})
check(r.ok and r.json()["removed"]["services"] == 2 and r.json()["removed"]["clients"] == 0, "#1557: only the services undone " + r.text[:200])
cl, sv, eq = names()
check({"Ax Studio GmbH", "Ax Film KG"} <= cl and not any(n.startswith("Ax") for n in sv), "#1557: the clients stay")
x = run(R1)
check(x.get("areas", {}).get("services", {}).get("undone_at") and not x["areas"]["clients"]["undone_at"] and not x.get("undone_at"),
      f"#1557: the run remembers the area, the run itself stays open {x}")
r = A.post(B + L + f"/runs/{R1}/undo", json={"kinds": ["services"]})
check(r.status_code == 409, "#1557: the same area twice -> 409")
for k in (["bogus"], [], "services"):
    check(A.post(B + L + f"/runs/{R1}/undo", json={"kinds": k}).status_code == 400, f"#1557: kinds {k!r} -> 400")
# a client of the run in use (a list for it) stays
cid = next(c["id"] for c in A.get(B + "/api/clients").json()["clients"] if c["name"] == "Ax Film KG")
LP = A.post(B + "/api/lists", json={"name": "Project Ax"}).json()["id"]
check(A.patch(B + f"/api/lists/{LP}", json={"client_id": cid}).ok, "#1557: a list for one imported client (in use)")
r = A.post(B + L + f"/runs/{R1}/undo", json={"kinds": ["clients"]})
check(r.ok and r.json()["removed"]["clients"] == 1 and r.json()["kept"]["clients"] == 1, "#1557: then the clients (second partial undo) " + r.text[:200])
check("Ax Film KG" in names()[0] and "Ax Studio GmbH" not in names()[0], "#1557: the client in use stays")
x = run(R1)
check(x.get("undone_at") and all(v["undone_at"] for v in x["areas"].values()), f"#1557: every area undone -> the whole run counts as undone {x}")
check(A.post(B + L + f"/runs/{R1}/undo").status_code == 409, "#1557: the whole undo after that -> 409")

# ---------------------------------------------------------------- the whole undo after a partial one
P3 = preview(sheet("Cx"))
r = A.post(B + L + "/import", json={"clients": P3["clients"], "services": P3["services"], "equipment": P3["equipment"]})
check(r.status_code == 201 and r.json()["counts"]["clients"] == 2 and r.json()["counts"]["equipment"] == 3, "#1557: an import of all three areas " + r.text[:200])
R3 = r.json()["run_id"]
r = A.post(B + L + f"/runs/{R3}/undo", json={"kinds": ["equipment"]})
check(r.ok and r.json()["removed"]["equipment"] == 3, "#1557: only the equipment undone " + r.text[:200])
check(not any(n.startswith("Cx") for n in names()[2]) and {"Cx Studio GmbH", "Cx Film KG"} <= names()[0], "#1557: devices gone, clients stay")
A.post(B + "/api/office/equipment", json={"name": "Cx Stativ"})  # made by hand again: the whole undo must not touch it
r = A.post(B + L + f"/runs/{R3}/undo")
j = r.json() if r.ok else {}
check(r.ok and j["removed"]["clients"] == 2 and j["removed"]["services"] == 2 and j["removed"]["equipment"] == 0, "#1557: the whole undo takes the rest " + r.text[:200])
cl, sv, eq = names()
check(not any(n.startswith("Cx") for n in cl | sv) and "Cx Stativ" in eq, f"#1557: the rest is gone, the device made by hand stays {cl} {sv} {eq}")
x = run(R3)
check(x.get("undone_at") and all(v["undone_at"] for v in x["areas"].values()), f"#1557: the run is undone {x}")
check(A.post(B + L + f"/runs/{R3}/undo", json={"kinds": ["clients"]}).status_code == 409, "#1557: a partial undo of an undone run -> 409")
check(A.post(B + L + f"/runs/{R2}/undo").ok and not any(n.startswith("Ax") for n in names()[2]), "#1557: the equipment-only run undoes as a whole")

# ---------------------------------------------------------------- an archive run has no areas
ar = A.post(B + L + "/archive/run").json()["run_id"]
check(A.post(B + L + f"/runs/{ar}/undo", json={"kinds": ["clients"]}).status_code == 400, "#1557: kinds on an archive run -> 400")
check("areas" not in run(ar), "#1557: an archive run lists no areas")
check(A.post(B + L + f"/runs/{ar}/undo").ok, "#1557: the archive run undoes as a whole")

print(f"p2461_c_import_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
