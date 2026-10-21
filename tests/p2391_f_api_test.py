#!/usr/bin/env python3
"""2.39.1 API tests (agent F: #1182 Office & finance -- legacy import), own container in mode workspaces (start.sh).
Invented companies, people and addresses only; the spreadsheet is generated here (same layout as the usual DATA.xlsx:
tables Contacts / Services / Equipment / Staff / Freelancer), the PDFs are tiny invented ones.
 - the address splitter: company, contact (z. Hd. / Attn. / c/o / Herr / Frau), street, P.O. box, postcode, city, country
   (DE 5 digits, AT / CH 4 digits, a country line, D- / A- / CH- prefixes, abroad), reasons for uncertain splits
 - preview: clients with duplicates (against the organisation's clients and within the file), services with categories
   from separator rows, equipment, staff / freelancers counted only; nothing stored by the preview
 - import: corrected fields, deselected rows (skip), merge into an existing client (only empty fields), run id on every row
 - archive: file names -> key data + client proposal, PDF only (magic bytes), size, same PDF twice 409, number used 409,
   files 0600 in a 0700 folder, the PDF comes back unchanged, list with the sums, PATCH only amount / paid / client
 - numbers: a new invoice never takes an archived number; the counter proposal from the archive, set only upwards
 - undo: a run removes what nothing builds on (a client with a quotation stays), merged fields emptied again, archive
   files removed, twice = 409
 - rights: member 403 (reads the archive), the second organisation 404 / empty, a private person 400, an agent 403
usage: p2391_f_api_test.py <datadir>"""
import io
import json
import os
import stat
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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


# ---------------------------------------------------------------- an invented DATA.xlsx (zipfile only)
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


ADDRESSES = [
    "Muster Medien GmbH\nz. Hd. Frau Erika Beispiel\nHafenstraße 12\n20457 Hamburg",                 # 0 clean, DE
    "Nordwind Film KG\nAttn. Max Probe\nLindenallee 3a\nD-50667 Köln\nDeutschland",                  # 1 prefix + country line
    "Alpenblick Werbung GmbH\nMariahilfer Straße 101\nA-1060 Wien\nÖsterreich",                      # 2 AT
    "Seeblick Kommunikation AG\nBahnhofplatz 7\n8001 Zürich\nSchweiz",                                # 3 CH, 4 digits + country
    "Bergtal Studios\nHauptweg 9\n6020 Innsbruck",                                                   # 4 4 digits, no country -> unsure
    "Kanalwerk Agentur\nc/o Coworking Nord\nSpeicherstadt 4\n20457 Hamburg",                          # 5 c/o
    "Leuchtturm Verlag GmbH\nPostfach 10 20 30\n80001 München",                                       # 6 P.O. box
    "Wiesengrund Design\nBerlin",                                                                     # 7 no postcode
    "Muster Medien GmbH\nHafenstraße 12\n20457 Hamburg",                                              # 8 duplicate of 0 in the file
    "Bestandskunde AG\nAm Markt 1\n10115 Berlin",                                                     # 9 duplicate of an existing client
    "Herr Jonas Beispiel\nSternschnuppe Media GmbH\nRingstraße 5\n04109 Leipzig",                     # 10 person above company
    "Harbour Pictures Ltd\nAttn: Jane Sample\n12 Quay Street\nLondon EC1A 1BB\nUnited Kingdom",        # 11 UK
    "Prairie Media Inc.\n500 Main Street\nSpringfield, IL 62701\nUSA",                                # 12 US
    "Einzeiler Studio, Gartenweg 2, 01067 Dresden",                                                   # 13 one line with commas
]
CONTACTS = [["addresses"]] + [[a] for a in ADDRESSES]
SERVICES = [["serviceDE", "serviceEN", "dailyrate", "hourlyrate", "rawfee", "producingfee", "order", "category", "freelancer", "intext"],
            ["---- VIDEO ----", "", "", "", "", "", "", "", "", ""],
            ["Kamera", "Camera", 650, "", 1, 1, 1, "", "Kamera", "intern"],
            ["Schnitt", "Editing", 550, 70, 1, 1, 2, "", "", "intern"],
            ["---- AUDIO ----", "", "", "", "", "", "", "", "", ""],
            ["Tonmischung", "Sound mix", "", 85, 0, 1, 3, "", "", "extern"],
            ["Sprecher", "Voice over", 480, "", 0, 0, 4, "Audio", "", "extern"]]
EQUIPMENT = [["device", "category", "dailyrate"], ["Kamera-Set A", "Kamera", 250], ["Funkstrecke", "Ton", 40], ["Lichtkoffer", "Licht", 90]]
STAFF = [["jobtitleDE", "jobtitleEN", "dailyrate", "intext"], ["Kameraassistenz", "Camera assistant", 350, "extern"], ["Tonmeister", "Sound engineer", 450, "extern"]]
FREEL = [["jobtitle", "dailyrate", "hourlyrate"], ["Kamera", 500, 60]]
XLSX = make_xlsx({"Contacts": CONTACTS, "Services": SERVICES, "Equipment": EQUIPMENT, "Staff": STAFF, "Freelancer": FREEL},
                 tables={"Contacts": "Contacts", "Services": "Services"})


def mini_pdf(tag):
    """A tiny invented PDF (valid enough for a viewer); tag makes it unique."""
    content = f"BT /F1 12 Tf 72 720 Td (Archiv {tag}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out


# ---------------------------------------------------------------- setup: two organisations, a member, a private person, an agent
FEAT = "cal,comments,collab,office,clients,time"
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dave", "Dave Private")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
A.put(B + "/api/office/settings", json={"producing_on": 1, "raw_on": 1})  # 2.40.0 (#1379): the raw data / producing columns need the switches
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
L = "/api/office/legacy"
r = A.post(B + "/api/clients", json={"name": "Bestandskunde AG", "zip": "10115", "city": "Berlin", "org_id": ORG})
assert r.status_code == 201, r.text
EXIST = r.json()["id"]
r = A.post(B + "/api/clients", json={"name": "Nordwind Film KG", "org_id": ORG})  # exists without postcode: the import may fill it
NORD = r.json()["id"]

# ---------------------------------------------------------------- the address splitter (through /split)
def split(t):
    r = A.post(B + L + "/split", json={"address": t})
    assert r.ok, r.text
    return r.json()


a = split(ADDRESSES[0])
check((a["name"], a["contact"], a["street"], a["zip"], a["city"], a["country"]) == ("Muster Medien GmbH", "Frau Erika Beispiel", "Hafenstraße 12", "20457", "Hamburg", "DE")
      and not a["flags"], f"split: clean German address {a}")
a = split(ADDRESSES[1])
check(a["contact"] == "Max Probe" and a["zip"] == "50667" and a["city"] == "Köln" and a["country"] == "DE" and a["street"] == "Lindenallee 3a", f"split: D- prefix, Attn., country line {a}")
a = split(ADDRESSES[2])
check(a["zip"] == "1060" and a["country"] == "AT" and a["street"] == "Mariahilfer Straße 101" and "zip4" not in a["flags"], f"split: Austria {a}")
a = split(ADDRESSES[3])
check(a["zip"] == "8001" and a["city"] == "Zürich" and a["country"] == "CH", f"split: Switzerland {a}")
a = split(ADDRESSES[4])
check(a["zip"] == "6020" and a["country"] == "" and "zip4" in a["flags"] and a["reasons"], f"split: 4 digits without a country = unsure with a reason {a}")
a = split(ADDRESSES[5])
check(a["name"] == "Kanalwerk Agentur" and "c/o Coworking Nord" in a["contact"] and "co" in a["flags"] and a["street"] == "Speicherstadt 4", f"split: c/o {a}")
a = split(ADDRESSES[6])
check(a["street"].startswith("Postfach") and "po_box" in a["flags"] and a["zip"] == "80001", f"split: P.O. box {a}")
a = split(ADDRESSES[7])
check(a["name"] == "Wiesengrund Design" and "no_zip" in a["flags"], f"split: no postcode {a}")
a = split(ADDRESSES[10])
check(a["name"] == "Sternschnuppe Media GmbH" and a["contact"] == "Herr Jonas Beispiel" and a["zip"] == "04109", f"split: person above the company {a}")
a = split(ADDRESSES[11])
check(a["country"] == "GB" and a["zip"] == "EC1A 1BB" and a["city"] == "London" and a["contact"] == "Jane Sample", f"split: UK {a}")
a = split(ADDRESSES[12])
check(a["country"] == "US" and a["zip"] == "62701" and "Springfield" in a["city"], f"split: US {a}")
a = split(ADDRESSES[13])
check(a["name"] == "Einzeiler Studio" and a["street"] == "Gartenweg 2" and a["zip"] == "01067" and a["city"] == "Dresden", f"split: one line with commas {a}")

# ---------------------------------------------------------------- preview
r = A.post(B + L + "/preview", files={"file": ("DATA.xlsx", XLSX)})
check(r.ok, "preview " + r.text[:200])
P = r.json()
cl = P["clients"]
check(len(cl) == len(ADDRESSES), f"preview: one client per address ({len(cl)})")
check(cl[8]["dup"] and cl[8]["dup"]["kind"] == "file" and cl[8]["action"] == "skip", f"preview: duplicate within the file skipped {cl[8].get('dup')}")
check(cl[9]["dup"] and cl[9]["dup"]["kind"] == "existing" and cl[9]["dup"]["id"] == EXIST and cl[9]["action"] == "skip", f"preview: duplicate of an existing client {cl[9].get('dup')}")
check(cl[1]["dup"] and cl[1]["dup"]["id"] == NORD, "preview: same name, existing client without postcode = duplicate")
check(cl[0]["action"] == "new" and not cl[0]["dup"], "preview: a new client is proposed as new")
sv = P["services"]
check([x["name_de"] for x in sv] == ["Kamera", "Schnitt", "Tonmischung", "Sprecher"], f"preview: separator rows are no services {[x['name_de'] for x in sv]}")
check(sv[0]["category"] == "Video" and sv[2]["category"] == "Audio" and sv[3]["category"] == "Audio", "preview: category from the separator row")
check(sv[0]["daily_rate"] == 650 and sv[2]["unit"] == "hour" and sv[2]["hourly_rate"] == 85 and sv[0]["raw_fee"] == 1 and sv[2]["intext"] == "extern", f"preview: rates, unit, flags {sv[2]}")
check(len(P["equipment"]) == 3 and P["equipment"][0]["daily_rate"] == 250, "preview: equipment")
# 2.47.0 (#1649): staff / freelancers are imported now (areas crew / roles), no longer only counted
check(len(P["crew"]) == 2 and len(P["roles"]) == 1 and P["roles"][0]["cost_day"] == 500, f"preview: staff / freelancers as areas crew / roles {P['crew']} {P['roles']}")
check(dbx("SELECT COUNT(*) FROM clients WHERE org_id=?", (ORG,))[0][0] == 2, "preview stores nothing")
check(A.post(B + L + "/preview", files={"file": ("x.xlsx", b"PK\x03\x04 not a zip")}).status_code == 400, "preview: a broken file = 400")
check(A.post(B + L + "/preview", files={"file": ("x.xlsx", mini_pdf("x"))}).status_code == 400, "preview: a PDF is no spreadsheet = 400")
bomb = io.BytesIO()
with zipfile.ZipFile(bomb, "w") as zf:
    zf.writestr("xl/workbook.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><workbook>&a;</workbook>')
check(A.post(B + L + "/preview", files={"file": ("x.xlsx", bomb.getvalue())}).status_code == 400, "preview: XML with entities refused")

# ---------------------------------------------------------------- rights before the import
check(Bo.post(B + L + "/preview", files={"file": ("DATA.xlsx", XLSX)}).status_code == 403, "rights: an organisation member cannot import (403)")
check(Bo.post(B + L + "/import", json={"clients": []}).status_code == 403, "rights: member import 403")
check(requests.post(B + L + "/preview", headers=AGH, files={"file": ("DATA.xlsx", XLSX)}).status_code == 403, "rights: an agent token 403")
check(requests.get(B + L + "/runs", headers=AGH).status_code == 403, "rights: agent cannot list runs")
# 2.47.3 (#1360): a person without an organisation imports into the own personal office (the preview stores nothing)
r = Da.post(B + L + "/preview", files={"file": ("DATA.xlsx", XLSX)})
check(r.ok and not any((x.get("dup") or {}).get("kind") == "existing" for x in r.json()["clients"]), "rights: a person without an organisation: own office, no duplicates from the organisation")

# ---------------------------------------------------------------- import with corrections
rows = [dict(x) for x in cl]
rows[4]["country"] = "AT"                   # the person fixes the unsure one
rows[7]["action"] = "skip"                  # and deselects one
rows[1]["action"] = "merge"
rows[1]["merge_id"] = NORD
rows[0]["contact"] = "Erika Beispiel"
svc = [dict(x) for x in sv]
svc[3]["action"] = "skip"
r = A.post(B + L + "/import", json={"clients": rows, "services": svc, "equipment": P["equipment"]})
check(r.status_code == 201, "import " + r.text[:300])
RUN = r.json()["run_id"]
cnt = r.json()["counts"]
check(cnt["clients"] == len(ADDRESSES) - 4 and cnt["merged"] == 1 and cnt["services"] == 3 and cnt["equipment"] == 3, f"import counts {cnt}")
got = {x[0]: x for x in dbx("SELECT name, contact, street, zip, city, country, import_run_id, address FROM clients WHERE org_id=?", (ORG,))}
m = got.get("Muster Medien GmbH")
check(m and m[1] == "Erika Beispiel" and m[2] == "Hafenstraße 12" and m[3] == "20457" and m[5] == "DE" and m[6] == RUN and "Hafenstraße" in m[7],
      f"imported client with corrected fields, the run id and the original text {m}")
check(got.get("Bergtal Studios", [None] * 6)[5] == "AT", "a corrected country is stored")
check("Wiesengrund Design" not in got, "a deselected row is not imported")
n = got.get("Nordwind Film KG")
check(n and n[3] == "50667" and n[4] == "Köln" and n[6] is None, f"merge fills only empty fields of the existing client, no run id {n}")
check(sum(1 for k in got if k == "Muster Medien GmbH") == 1, "the duplicate within the file is skipped")
check(dbx("SELECT COUNT(*) FROM office_services WHERE org_id=? AND import_run_id=?", (ORG, RUN))[0][0] == 3, "services carry the run id")
check(dbx("SELECT category FROM office_services WHERE org_id=? AND name_de='Schnitt'", (ORG,))[0][0] == "Video", "service category stored")
check(dbx("SELECT COUNT(*) FROM office_equipment WHERE org_id=? AND import_run_id=?", (ORG, RUN))[0][0] == 3, "equipment carries the run id")
r = A.post(B + L + "/preview", files={"file": ("DATA.xlsx", XLSX)})
check(r.ok and r.json()["clients"][0]["dup"] and r.json()["services"][0]["dup"], "a second preview sees the imported rows as duplicates")
check(A.post(B + L + "/import", json={"clients": [{"name": "", "action": "new"}]}).status_code == 400, "import: a client without a name = 400 (nothing written)")
check(A.post(B + L + "/import", json={"clients": [{"name": "X", "action": "merge", "merge_id": 999999}]}).status_code == 400, "import: merge into a foreign / unknown client = 400")
r = Ca.post(B + "/api/clients", json={"name": "Beta-Kunde", "org_id": ORG2})
CLB = r.json()["id"]
check(A.post(B + L + "/import", json={"clients": [{"name": "X", "action": "merge", "merge_id": CLB}]}).status_code == 400, "tenant-matrix: office -- merge into another organisation's client = 400")

# ---------------------------------------------------------------- archive
OUR = {x[1]: x[0] for x in dbx("SELECT id, name FROM clients WHERE org_id=?", (ORG,))}
NAMES = ["663_MusterMedien_Imagefilm-Hafen__08.05.26_R.pdf", "0815_Nordwind_KV02_2026-03-01_AB.pdf", "664_Bergtal_Messefilm__2026-06-30_R.pdf", "notiz.pdf"]
r = A.post(B + L + "/archive/parse", json={"names": NAMES})
check(r.ok, "archive: parse " + r.text[:200])
it = r.json()["items"]
check(it[0]["kind"] == "invoice" and it[0]["project_no"] == "663" and it[0]["date"] == "2026-05-08" and it[0]["project"] == "Imagefilm-Hafen"
      and it[0]["number"] == "663_MusterMedien_Imagefilm-Hafen__08.05.26_R" and it[0]["client_id"] == OUR["Muster Medien GmbH"], f"archive: invoice file name {it[0]}")
check(it[1]["kind"] == "offer" and it[1]["date"] == "2026-03-01" and it[1]["project_no"] == "0815" and it[1]["client_id"] == NORD, f"archive: quotation file name {it[1]}")
check(it[2]["date"] == "2026-06-30" and it[2]["client_id"] == OUR["Bergtal Studios"], f"archive: ISO date {it[2]}")
check(not it[3]["sure"] and it[3]["number"] == "notiz", "archive: a free name is a proposal only")
check(Bo.post(B + L + "/archive/run").status_code == 403, "rights: member cannot open an archive run")
RA = A.post(B + L + "/archive/run").json()["run_id"]
PDF1 = mini_pdf("663")


def up(sess_, pdf, meta, name="a.pdf"):
    return sess_.post(B + L + "/archive", files={"file": (name, pdf, "application/pdf")}, data={k: ("" if v is None else str(v)) for k, v in meta.items()})


meta0 = {"run_id": RA, "kind": "invoice", "number": it[0]["number"], "project_no": "663", "project": it[0]["project"], "client_id": it[0]["client_id"],
         "date": it[0]["date"], "amount": "40963.25", "paid": 1}
r = up(A, PDF1, meta0, NAMES[0])
check(r.status_code == 201 and r.json()["archive"] and r.json()["amount"] == 40963.25 and r.json()["paid"] == 1, "archive: upload an invoice " + r.text[:200])
A1 = r.json().get("id")
check(up(A, PDF1, dict(meta0, number="other"), NAMES[0]).status_code == 409, "archive: the same PDF twice = 409")
check(up(A, mini_pdf("b"), meta0, "b.pdf").status_code == 409, "archive: a used number = 409")
check(up(A, b"GIF89a not a pdf", dict(meta0, number="x1"), "x.pdf").status_code == 400, "archive: only PDF (magic bytes)")
check(up(A, mini_pdf("c"), dict(meta0, number="x2", amount="abc"), "c.pdf").status_code == 400, "archive: amount validated")
check(up(A, mini_pdf("d"), dict(meta0, number="x3", client_id=CLB), "d.pdf").status_code == 400, "tenant-matrix: office -- archive with another organisation's client = 400")
check(up(A, mini_pdf("e"), dict(meta0, number="x4", run_id=RUN), "e.pdf").status_code == 400, "archive: only into an archive run")
check(up(Bo, mini_pdf("f"), dict(meta0, number="x5"), "f.pdf").status_code == 403, "rights: member cannot upload into the archive")
r = up(A, mini_pdf("kv02"), {"run_id": RA, "kind": "offer", "number": it[1]["number"], "client_id": NORD, "date": it[1]["date"], "amount": "20380", "paid": 0}, NAMES[1])
check(r.status_code == 201, "archive: upload a quotation " + r.text[:200])
r = up(A, mini_pdf("664"), {"run_id": RA, "kind": "invoice", "number": it[2]["number"], "project_no": "664", "client_id": it[2]["client_id"], "date": it[2]["date"], "amount": "1000", "paid": 0}, NAMES[2])
check(r.status_code == 201, "archive: second invoice " + r.text[:200])
A3 = r.json().get("id")
fn = dbx("SELECT file FROM office_archive WHERE id=?", (A1,))[0][0]
p = os.path.join(DATA, "office", str(ORG), fn)
check(os.path.isfile(p) and stat.S_IMODE(os.stat(p).st_mode) == 0o600 and stat.S_IMODE(os.stat(os.path.dirname(p)).st_mode) == 0o700,
      "archive: file 0600 in a 0700 folder")
r = A.get(B + L + f"/archive/{A1}/pdf")
check(r.ok and r.content == PDF1 and r.headers.get("Content-Type", "").startswith("application/pdf"), "archive: the original PDF comes back unchanged")
r = Bo.get(B + L + "/archive")
check(r.ok and len(r.json()["items"]) == 3 and all(x["archive"] for x in r.json()["items"]) and r.json()["sum_paid"] == 40963.25 and r.json()["sum_invoices"] == 41963.25,
      "archive: members read the list with the sums " + r.text[:200])
check(Bo.get(B + L + f"/archive/{A1}/pdf").ok, "archive: members open the PDF")
check(Ca.get(B + L + f"/archive/{A1}/pdf").status_code == 404 and Ca.get(B + L + "/archive").json()["items"] == [], "tenant-matrix: office -- the archive of another organisation = 404 / empty")
check(requests.get(B + L + "/archive", headers=AGH).status_code == 403, "rights: agent cannot read the archive")
r = A.patch(B + L + f"/archive/{A3}", json={"paid": 1, "number": "changed"})
check(r.ok and r.json()["paid"] == 1 and r.json()["number"] == it[2]["number"], "archive: PATCH sets paid, the number stays")
# 2.81.0 (#1834): members may correct an archived document; 2.86.0 audit part 2 (#1968): members only assign the client,
# *Paid* only an office admin
r = Bo.patch(B + L + f"/archive/{A3}", json={"paid": 0})
check(r.status_code == 403 and A.get(B + L + "/archive").json()["items"] and next(x for x in A.get(B + L + "/archive").json()["items"] if x["id"] == A3)["paid"] == 1,
      f"rights: a member does not change Paid of an archived document ({r.status_code})")
check(Ca.patch(B + L + f"/archive/{A3}", json={"paid": 0}).status_code == 404, "tenant-matrix: office -- PATCH another organisation's archive = 404")
# 2.80.0 (#1837): amounts with thousand separators (German and English), currency signs and spaces, upload and PATCH
AMTS = {"2.436,53": 2436.53, "2436,53": 2436.53, "2436.53": 2436.53, "1.500": 1500, "12.000": 12000, "1.500,00": 1500, "2,436.53": 2436.53,
        "€ 2.436,53": 2436.53, "2.436,53 EUR": 2436.53, "2 436,53": 2436.53, "1,5": 1.5}
for t, want in AMTS.items():
    r = A.patch(B + L + f"/archive/{A3}", json={"amount": t})
    check(r.ok and r.json()["amount"] == want, f"archive: PATCH amount {t!r} = {want} " + r.text[:160])
for t in ("abc", "1.2.3", "1,2,3.4", "12,3.4.5"):
    check(A.patch(B + L + f"/archive/{A3}", json={"amount": t}).status_code == 400, f"archive: PATCH amount {t!r} = 400")
check(A.patch(B + L + f"/archive/{A3}", json={"amount": "1000"}).json()["amount"] == 1000, "archive: PATCH amount back to 1000")
RC = A.post(B + L + "/archive/run").json()["run_id"]
r = up(A, mini_pdf("amt1837"), {"run_id": RC, "kind": "invoice", "number": "amt1837", "amount": "2.436,53", "paid": 0}, "amt1837.pdf")
check(r.status_code == 201 and r.json()["amount"] == 2436.53, "archive: upload with amount 2.436,53 " + r.text[:200])
check(A.post(B + L + f"/runs/{RC}/undo").ok, "archive: undo the amount run")
r = A.post(B + L + "/archive/parse", json={"names": [NAMES[0]]})
check(r.json()["items"][0]["taken"], "archive: parse marks a number that is in the archive")

# ---------------------------------------------------------------- numbers: no collision, the counter proposal
st = A.get(B + "/api/office/settings").json()["settings"]
check(A.put(B + "/api/office/settings", json={"invoice_scheme": "{seq}_R"}).ok, "setup: invoice scheme like the old one")
r = A.get(B + L + "/counter")
check(r.ok and r.json()["invoice"]["highest"] == 664 and r.json()["invoice"]["proposal"] == 664 and r.json()["invoice"]["last"] == 0, "counter: proposal from the archive " + r.text[:300])
check(Bo.get(B + L + "/counter").status_code == 403, "rights: member cannot read the counter proposal")
# 2.144.6 B (#2400 F2): raising the invoice counter needs a reason like the number ranges (GoBD)
check(A.post(B + L + "/counter", json={"kind": "invoice", "last": 664}).status_code == 400, "counter: no reason -> 400")
check(A.post(B + L + "/counter", json={"kind": "invoice", "last": 664, "reason": "Continue after the old invoices"}).ok, "counter: set to the proposal")
check(A.post(B + L + "/counter", json={"kind": "invoice", "last": 10}).status_code == 400, "counter: never lowered")
check(dbx("SELECT last FROM office_numbers WHERE org_id=? AND kind='invoice'", (ORG,))[0][0] == 664, "counter stored")
# an archived number that the scheme would make next: the new invoice skips it
r = A.post(B + "/api/office/legacy/archive/run")
RB = r.json()["run_id"]
check(up(A, mini_pdf("665"), {"run_id": RB, "kind": "invoice", "number": "665_R", "amount": "5", "paid": 1}, "665_R.pdf").status_code == 201, "archive: number 665_R")
dbx("UPDATE office_numbers SET last=664 WHERE org_id=? AND kind='invoice'", (ORG,), write=True)
r = A.post(B + "/api/office/docs", json={"kind": "invoice", "client_id": OUR["Muster Medien GmbH"], "project_title": "Neu", "date": "2026-10-12"})
check(r.status_code == 201, "setup: invoice draft " + r.text[:200])
INV = r.json()["id"]
dbx("UPDATE office_docs SET number='' WHERE id=?", (INV,), write=True)
src = open(os.path.join(os.environ.get("KALMIDO_SRC") or os.path.join(N, ".."), "kalmido", "office", "docs.py"), encoding="utf-8").read()
check("fi_number_taken" in src, "docs._assign_number checks the archive numbers")
r = A.post(B + f"/api/office/docs/{INV}/number", json={"number": "665_R"})
check(r.status_code in (400, 409), "a manual invoice number that is in the archive = refused " + r.text[:120])

# ---------------------------------------------------------------- undo
QDOC = A.post(B + "/api/office/docs", json={"kind": "offer", "client_id": OUR["Kanalwerk Agentur"], "project_title": "Neues Angebot"})
check(QDOC.status_code == 201, "setup: a new quotation for an imported client")
check(Bo.post(B + L + f"/runs/{RUN}/undo").status_code == 403, "rights: member cannot undo")
check(Ca.post(B + L + f"/runs/{RUN}/undo").status_code == 404, "tenant-matrix: office -- undo another organisation's run = 404")
r = A.get(B + L + "/runs")
check(r.ok and {x["id"] for x in r.json()["runs"]} >= {RUN, RA, RB} and any(x["id"] == RUN and x["total"] >= 13 for x in r.json()["runs"]), "runs listed with counts")
r = A.post(B + L + f"/runs/{RUN}/undo")
check(r.ok, "undo " + r.text[:200])
rem, kept = r.json()["removed"], r.json()["kept"]
left = {x[0] for x in dbx("SELECT name FROM clients WHERE org_id=?", (ORG,))}
check("Kanalwerk Agentur" in left and "Muster Medien GmbH" in left and "Bergtal Studios" in left, f"undo keeps clients with a quotation / an archived document {sorted(left)}")
check("Alpenblick Werbung GmbH" not in left and "Seeblick Kommunikation AG" not in left, "undo removes the clients nothing builds on")
check(kept["clients"] == 3 and rem["clients"] == cnt["clients"] - 3, f"undo counts {rem} {kept}")
check(dbx("SELECT zip, city FROM clients WHERE id=?", (NORD,))[0] == ("", "") or tuple(dbx("SELECT zip, city FROM clients WHERE id=?", (NORD,))[0]) == ("", ""), "undo empties the merged fields again")
check(dbx("SELECT COUNT(*) FROM office_services WHERE org_id=? AND import_run_id=?", (ORG, RUN))[0][0] == 0, "undo removes unused services")
check(A.post(B + L + f"/runs/{RUN}/undo").status_code == 409, "undo twice = 409")
r = A.post(B + L + f"/runs/{RB}/undo")
check(r.ok and r.json()["removed"]["archive"] == 1, "undo of an archive run removes its documents")
check(not dbx("SELECT 1 FROM office_archive WHERE number='665_R'"), "archive row gone")
check(os.path.isfile(p), "the other run's file stays")
r = A.post(B + L + f"/runs/{RA}/undo")
check(r.ok and r.json()["removed"]["archive"] == 3 and not os.path.isfile(p), "undo of the first archive run removes its files")

# ---------------------------------------------------------------- log + backup coverage
acts = {(x[0], x[1]) for x in dbx("SELECT action, target FROM office_doc_log WHERE org_id=?", (ORG,))}
check(("import", "legacy") in acts and ("undo", "legacy") in acts and ("upload", "archive") in acts, f"office log has the legacy actions {sorted(acts)}")
bk = open(os.path.join(os.environ.get("KALMIDO_SRC") or os.path.join(N, ".."), "kalmido", "admin", "backup.py"), encoding="utf-8").read()
check("office/" in bk and "pg_dump" in bk, "backup: the office folder (archive PDFs) and the whole database are in every backup")

print(f"p2391_f_api_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
