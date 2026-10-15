#!/usr/bin/env python3
"""2.47.0 API tests, part A (#1648 fill instead of skip, #1649 masters Freelancer-Rollen / Drehpersonal + their import,
#1645 the raw data / producing columns always read), own container in mode workspaces (start.sh). Invented data only;
the spreadsheet is generated here (zipfile only, like p2391_f).
 - masters: POST / PATCH /api/office/roles (purchase per day / hour) and /api/office/crew (rate, intern / extern, markup);
   a member reads them without purchase prices / markup and cannot write; another organisation gets 404; a crew id is no
   freelancer role; a service points to a role (role_id), not to a crew row or another organisation's role
 - preview: an existing service / device / role / crew row with empty fields = "fill" with the fields it fills, a full one
   = "skip"; blocks Freelancer + Staff as areas roles / crew; the table "Services_2"; #NV = empty; the category order;
   Künstlersozialkasse = unit percent (0.05 -> 5); intext shooting; raw data / producing read with the switches off
 - import: fills only empty fields, never overwrites; roles before services (role_id from the column freelancer)
 - undo: only the area services empties the filled fields again (a field changed since stays), then the whole run
usage: p2470_a_import_api_test.py <datadir>"""
import io
import os
import subprocess
import sys
import zipfile
from xml.sax.saxutils import escape

import requests

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


# ---------------------------------------------------------------- setup: two organisations, an admin, a member
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
O, L = "/api/office", "/api/office/legacy"
# 2.47.0 (#1645): the switches raw_on / producing_on stay OFF here -- the import reads both columns anyway

# ---------------------------------------------------------------- masters: roles + crew, rights
r = A.post(B + O + "/roles", json={"name_de": "Cutter", "cost_hour": "55"})
check(r.status_code == 201 and r.json().get("cost_hour") == 55 and r.json().get("cost_day") is None, "roles: POST with a purchase price per hour " + r.text[:200])
CUT = r.json()["id"]
r = A.patch(B + O + f"/roles/{CUT}", json={"name_en": ""})
check(r.ok and r.json().get("cost_hour") == 55, "roles: a PATCH without the price keeps it " + r.text[:200])
r = A.post(B + O + "/crew", json={"name_de": "Beleuchter", "intext": "extern", "markup_pct": 10})
check(r.status_code == 201 and r.json().get("markup_pct") == 10 and r.json().get("intext") == "extern" and r.json().get("rate_day") is None,
      "crew: POST with intern / extern and a markup " + r.text[:200])
GAF = r.json()["id"]
check(A.post(B + O + "/crew", json={"name_de": "X", "intext": "shooting"}).status_code == 400, "crew: only intern / extern")
check(A.get(B + O + f"/roles/{GAF}").status_code == 404 and A.get(B + O + f"/crew/{CUT}").status_code == 404, "roles / crew: the other master's id = 404")
r = Bo.get(B + O + "/roles")
check(r.ok and [x["name_de"] for x in r.json()["items"]] == ["Cutter"] and not any(k in r.json()["items"][0] for k in ("cost_day", "cost_hour", "costs")),
      "rights: a member reads the roles without purchase prices " + r.text[:200])
r = Bo.get(B + O + f"/crew/{GAF}")
check(r.ok and "markup_pct" not in r.json() and r.json().get("intext") == "extern", "rights: a member reads the crew without the markup " + r.text[:200])
r = Bo.get(B + O + "/export")
check(r.ok and r.json().get("roles") and "cost_hour" not in r.json()["roles"][0] and "markup_pct" not in r.json()["crew"][0],
      "rights: the export of a member carries no purchase prices / markups")
r = A.get(B + O + "/export")
check(r.ok and r.json()["roles"][0].get("cost_hour") == 55 and r.json()["crew"][0].get("markup_pct") == 10, "export: the admin's file carries them")
check(Bo.post(B + O + "/roles", json={"name_de": "X"}).status_code == 403 and Bo.patch(B + O + f"/crew/{GAF}", json={"rate_day": 1}).status_code == 403,
      "rights: a member cannot write roles / crew (403)")
check(Ca.get(B + O + f"/roles/{CUT}").status_code == 404 and Ca.patch(B + O + f"/roles/{CUT}", json={"name_de": "Y"}).status_code == 404
      and Ca.get(B + O + "/roles").json()["items"] == [], "tenant-matrix: office -- another organisation does not see / change the roles (404)")
r = Ca.post(B + O + "/roles", json={"name_de": "Fremd", "cost_day": 1})
FREMD = r.json()["id"]
r = A.post(B + O + "/services", json={"name_de": "Schnitt", "name_en": "Edit", "category": "Post", "sort": 5, "daily_rate": 500, "hourly_rate": 60,
                                      "raw_fee": 1, "producing": 1, "role": "Cutter", "role_id": CUT, "intext": "intern"})
check(r.status_code == 201 and r.json().get("role_id") == CUT, "service: role_id = a freelancer role " + r.text[:200])
check(A.post(B + O + "/services", json={"name_de": "S2", "role_id": GAF}).status_code == 400, "service: a crew row is no role (400)")
check(A.post(B + O + "/services", json={"name_de": "S3", "role_id": FREMD}).status_code == 400, "tenant-matrix: office -- another organisation's role (400)")
r = A.post(B + O + "/services", json={"name_de": "KSK-Test", "unit": "percent", "daily_rate": 5, "intext": "shooting"})
check(r.status_code == 201 and r.json()["unit"] == "percent" and r.json()["intext"] == "shooting", "service: unit percent, kind shooting " + r.text[:200])
A.delete(B + O + f"/services/{r.json()['id']}")
A.post(B + O + "/services", json={"name_de": "Sprecher", "name_en": "Voice", "category": "Audio", "sort": 7, "daily_rate": 480, "hourly_rate": 60,
                                  "raw_fee": 1, "producing": 1, "role": "Unbekannt"})  # only role_id empty, and that role exists nowhere
r = A.post(B + O + "/services", json={"name_de": "Kamera", "daily_rate": 700})  # empty fields: the import fills them
KAM = r.json()["id"]
LK = A.post(B + "/api/office/equipment", json={"name": "Lichtkoffer", "daily_rate": 80}).json()["id"]

# ---------------------------------------------------------------- the spreadsheet: _DATA-like tables
SERVICES = [["serviceDE", "serviceEN", "dailyrate", "hourlyrate", "rawfee", "producingfee", "order", "category", "freelancer", "intext"],
            ["---- VIDEO ----"],
            ["Kamera", "Camera", 650, "", 1, 1, 1, "", "Motion Designer", "intern"],
            ["Schnitt", "Editing", 550, 70, 0, 0, "#NV", "#NV", "Cutter", "intern"],
            ["Farbkorrektur", "Grading", 600, "", 1, 0, "", "", "", "intern"],
            ["---- AUDIO ----"],
            ["Tonmischung", "Sound mix", "", 85, 0, 1, 2, "", "", "extern"],
            ["Sprecher", "Voice over", 480, "", 0, 0, 2, "", "Unbekannt", "extern"],
            ["---- OFFICE ----"],
            ["Künstlersozialkasse", "Artists' social insurance", 0.05, "", 0, 0, 3, "", "", "extern"],
            ["---- SHOOTING ----"],
            ["Drehtag Kamera", "Shoot day camera", 650, "", 0, 0, 6, "", "", "shooting"]]
FREEL = [["jobtitle", "dailyrate", "hourlyrate"], ["Motion Designer", 600, 75], ["Cutter", 500, 62], ["3 D Animator", 650, ""]]
STAFF = [["jobtitleDE", "jobtitleEN", "dailyrate", "intext"], ["Beleuchter", "Gaffer", 350, "extern"], ["Kamera", "Camera", 650, "intern"],
         ["Kamera (Premium)", "Camera (premium)", 850, "intern"]]
EQUIP = [["device", "category", "dailyrate"], ["Lichtkoffer", "Licht", 90], ["Funkstrecke", "Ton", 40]]
XLSX = make_xlsx({"_DATA": SERVICES, "staff": STAFF, "freelancer": FREEL, "equipment": EQUIP}, tables={"_DATA": "Services_2"})

r = A.post(B + L + "/preview", files={"file": ("KV.xlsx", XLSX)})
check(r.ok, "preview " + r.text[:300])
P = r.json()
sv = {x["name_de"]: x for x in P.get("services", [])}
check(list(sv) == ["Kamera", "Schnitt", "Farbkorrektur", "Tonmischung", "Sprecher", "Künstlersozialkasse", "Drehtag Kamera"], f"preview: the table Services_2 is read {list(sv)}")
check(sv["Sprecher"]["action"] == "skip" and sv["Sprecher"]["fill"] == {}, f"preview: a role found neither in the file nor in the masters is nothing to fill {sv['Sprecher']}")
k = sv.get("Kamera", {})
check(k.get("action") == "fill" and k.get("fill") == {"name_en": "Camera", "category": "Video", "sort": k.get("sort"), "raw_fee": 1, "producing": 1,
                                                       "role": "Motion Designer", "role_id": "Motion Designer"},
      f"preview: an existing service with empty fields = fill, only the empty ones (daily rate stays) {k.get('fill')}")
check(sv.get("Schnitt", {}).get("action") == "skip" and sv["Schnitt"].get("fill") == {} and sv["Schnitt"].get("dup"), "preview: a full existing service = skip, nothing to fill")
check(sv["Schnitt"]["category"] == "Video" and sv["Farbkorrektur"]["category"] == "Video", "preview: #NV = empty, the category of the separator row")
check(sv["Kamera"]["raw_fee"] == 1 and sv["Tonmischung"]["producing"] == 1, "preview (#1645): raw data / producing read with the switches off")
srt = [sv[n]["sort"] for n in ("Kamera", "Schnitt", "Farbkorrektur", "Tonmischung", "Künstlersozialkasse", "Drehtag Kamera")]
check(srt == sorted(srt) and int(sv["Schnitt"]["sort"]) // 10000 == 1 and int(sv["Tonmischung"]["sort"]) // 10000 == 2,
      f"preview: sort = category order, then the file's rows {srt}")
ks = sv["Künstlersozialkasse"]
check(ks["unit"] == "percent" and ks["daily_rate"] == 5 and ks["hourly_rate"] is None and ks.get("percent"), f"preview: Künstlersozialkasse = 5 percent {ks}")
check(sv["Drehtag Kamera"]["intext"] == "shooting" and sv["Kamera"]["intext"] == "intern" and sv["Tonmischung"]["intext"] == "extern", "preview: intern / extern / shooting")
ro = {x["name_de"]: x for x in P.get("roles", [])}
check(list(ro) == ["Motion Designer", "Cutter", "3 D Animator"] and ro["Motion Designer"]["action"] == "new" and ro["Motion Designer"]["cost_day"] == 600
      and ro["Motion Designer"]["cost_hour"] == 75, f"preview: the block Freelancer = area roles {P.get('roles')}")
check(ro.get("Cutter", {}).get("action") == "fill" and ro["Cutter"].get("fill") == {"cost_day": 500}, f"preview: an existing role: only the empty price {ro.get('Cutter')}")
cr = {x["name_de"]: x for x in P.get("crew", [])}
check(list(cr) == ["Beleuchter", "Kamera", "Kamera (Premium)"] and cr["Kamera (Premium)"]["action"] == "new" and cr["Kamera"]["intext"] == "intern",
      f"preview: the block Staff = area crew, a variant is a role of its own {P.get('crew')}")
check(cr.get("Beleuchter", {}).get("fill") == {"name_en": "Gaffer", "rate_day": 350}, f"preview: an existing crew row: the empty fields {cr.get('Beleuchter')}")
eq = {x["name"]: x for x in P.get("equipment", [])}
check(eq.get("Lichtkoffer", {}).get("action") == "fill" and eq["Lichtkoffer"].get("fill") == {"category": "Licht"}, f"preview: device: only the empty category {eq.get('Lichtkoffer')}")
check(Bo.post(B + L + "/preview", files={"file": ("KV.xlsx", XLSX)}).status_code == 403, "rights: a member cannot preview (403)")
check(Bo.post(B + L + "/import", json={"roles": P["roles"]}).status_code == 403, "rights: a member cannot import roles (403)")

# ---------------------------------------------------------------- import
body = {k: P[k] for k in ("roles", "crew", "services", "equipment")}
body["services"] = [dict(x, fill={"daily_rate": 1}) for x in body["services"]]  # the client's fill list is not trusted
r = A.post(B + L + "/import", json=body)
check(r.status_code == 201, "import " + r.text[:300])
RUN = r.json().get("run_id")
cnt = r.json().get("counts", {})
check((cnt.get("roles"), cnt.get("roles_filled"), cnt.get("crew"), cnt.get("crew_filled"), cnt.get("services"), cnt.get("services_filled"),
       cnt.get("equipment"), cnt.get("equipment_filled")) == (2, 1, 2, 1, 4, 1, 1, 1), f"import counts {cnt}")
R = {x["name_de"]: x for x in A.get(B + O + "/roles").json()["items"]}
check(R.get("Motion Designer", {}).get("cost_day") == 600 and R["Motion Designer"].get("cost_hour") == 75, "import: a new role with its purchase prices")
check(R.get("Cutter", {}).get("cost_day") == 500 and R["Cutter"].get("cost_hour") == 55, "import: an existing role: the empty price filled, the set one kept")
S = {x["name_de"]: x for x in A.get(B + O + "/services").json()["items"]}
k = S.get("Kamera", {})
check(k.get("name_en") == "Camera" and k.get("category") == "Video" and k.get("raw_fee") == 1 and k.get("producing") == 1 and k.get("daily_rate") == 700
      and k.get("role") == "Motion Designer" and k.get("role_id") == R["Motion Designer"]["id"] and k.get("sort", 0) > 0,
      f"import: only the empty fields of the service filled, the set daily rate kept, the role resolved {k}")
s5 = S.get("Schnitt", {})
check((s5.get("name_en"), s5.get("category"), s5.get("daily_rate"), s5.get("raw_fee"), s5.get("sort"), s5.get("role_id")) == ("Edit", "Post", 500, 1, 5, CUT),
      f"import: a full service is unchanged {s5}")
check(S.get("Künstlersozialkasse", {}).get("unit") == "percent" and S["Künstlersozialkasse"].get("daily_rate") == 5, "import: Künstlersozialkasse as percent")
check(S.get("Drehtag Kamera", {}).get("intext") == "shooting", "import: a shooting service")
C = {x["name_de"]: x for x in A.get(B + O + "/crew").json()["items"]}
check(C.get("Beleuchter", {}).get("name_en") == "Gaffer" and C["Beleuchter"].get("rate_day") == 350 and C["Beleuchter"].get("markup_pct") == 10,
      f"import: crew filled, the markup kept {C.get('Beleuchter')}")
check(C.get("Kamera (Premium)", {}).get("rate_day") == 850 and C["Kamera (Premium)"].get("intext") == "intern", "import: a new crew row")
E = {x["name"]: x for x in A.get(B + "/api/office/equipment").json()["items"]}
check(E.get("Lichtkoffer", {}).get("category") == "Licht" and E["Lichtkoffer"].get("daily_rate") == 80, "import: device filled, its rate kept")
runs = A.get(B + L + "/runs").json()["runs"]
ar = runs[0].get("areas", {}) if runs else {}
check({k: v["count"] for k, v in ar.items()} == {"roles": 3, "crew": 3, "services": 5, "equipment": 2}, f"runs: the areas with new + filled rows {ar}")
r = A.post(B + L + "/preview", files={"file": ("KV.xlsx", XLSX)})
check(r.ok and r.json()["services"][0]["action"] == "skip" and all(x["action"] == "skip" for x in r.json()["roles"] + r.json()["crew"]),
      "preview again: nothing left to fill = skip")

# ---------------------------------------------------------------- undo: the area services, then the rest
A.patch(B + O + f"/services/{KAM}", json={"category": "Film"})  # changed after the import: stays
r = A.post(B + L + f"/runs/{RUN}/undo", json={"kinds": ["services"]})
check(r.ok and r.json()["removed"]["services"] == 4 and r.json()["removed"]["filled"] == 1, "undo services " + r.text[:300])
k = A.get(B + O + f"/services/{KAM}").json()
check((k.get("name_en"), k.get("category"), k.get("raw_fee"), k.get("producing"), k.get("role"), k.get("role_id"), k.get("sort"), k.get("daily_rate"))
      == ("", "Film", 0, 0, "", None, 0, 700), f"undo services: the filled fields empty again, a field changed since stays {k}")
check("Motion Designer" in {x["name_de"] for x in A.get(B + O + "/roles").json()["items"]}, "undo services: the roles stay")
r = A.post(B + L + f"/runs/{RUN}/undo")
check(r.ok and r.json()["removed"]["roles"] == 2 and r.json()["removed"]["crew"] == 2, "undo the rest " + r.text[:300])
R = {x["name_de"]: x for x in A.get(B + O + "/roles").json()["items"]}
check(set(R) == {"Cutter"} and R["Cutter"]["cost_day"] is None and R["Cutter"]["cost_hour"] == 55, f"undo: the new roles gone, the filled price empty again {R}")
C = {x["name_de"]: x for x in A.get(B + O + "/crew").json()["items"]}
check(set(C) == {"Beleuchter"} and C["Beleuchter"]["name_en"] == "" and C["Beleuchter"]["rate_day"] is None and C["Beleuchter"]["markup_pct"] == 10,
      f"undo: crew back {C}")
check(A.get(B + "/api/office/equipment").json()["items"][0].get("category") == "" and len(A.get(B + "/api/office/equipment").json()["items"]) == 1,
      "undo: the device's category empty again, the new one gone")
check(A.post(B + L + f"/runs/{RUN}/undo").status_code == 409, "undo twice = 409")

print(f"p2470_a_import_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
