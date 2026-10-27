#!/usr/bin/env python3
"""2.138.0 API tests, part E (office), own container (start.sh). Invented data only; the spreadsheet is generated here.
(taken over from the 2.112.0 A-D suites, only the cases of #2242 #2235 #2237 #2238 #2241)
tenant-matrix: office
freelancer-matrix: office
 - #2237: an import takes the file's order also for services that existed before (old small sort values), numbers all of
   them 1..n without gaps, grouped by category; every other field of an existing service stays (only sort is overwritten)
 - #2237: POST /api/office/services/renumber numbers the list's order 1..n; {sorts} sets exact values (the client's undo);
   a member 403, another organisation only reaches its own services (a foreign id = 400)
 - #2241: undo archives the run's services / devices that documents / sets use (name + where), deletes the unused ones;
   the producing service of the calculation rules stays active, unless the rules name another one; the document keeps
   title and rate; restore = PATCH archived 0
 - #2241: POST /api/office/legacy/runs/<id>/tidy archives what an earlier undo left active (only that run's entries,
   nothing deleted); a run not undone = 409, a member 403, another organisation 404
 - #2235: an invoice from a quotation that is not accepted yet works (draft and sent; the question is the client's only)
 - #2242: company data choice "Gesellschafter (GbR)" / "Partners (GbR)": the footer prints "Gesellschafter: ..." (DE) /
   "Partners: ..." (EN); "shareholders" is unchanged
 - a person without an organisation: the same in the personal office
 - #2238 (no server, kalmido/office/pdf.py of the source tree): offers and invoices of every length from 8 to 60 positions:
   the closing (totals, payment, closing text, signature, order confirmation) always on one page together with at least
   one position, a group heading never the last line of a page, nothing below the body bottom; at least one length lands
   tight at the page end (set tighter instead of a page break); a closing longer than a page still breaks, every row printed
usage: p2138_e_api_test.py <datadir>      (P2138E_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh;
       KALMIDO_SRC = the source tree for the PDF part, default ../ next to tests/)"""
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from xml.sax.saxutils import escape

import requests
from freelancer_fixture import freelancer

import dbx as dbxm  # 2.144.6 B (#2400 F4): an undo before 2.112 is simulated in the database (a PATCH counts as a restore now)

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients"
O, L, D = "/api/office", "/api/office/legacy", "/api/office/docs"


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def make_xlsx(rows, table="Services"):
    """One sheet + table Services (str -> shared string, int / float -> number)."""
    strings, sidx = [], {}

    def si(v):
        if v not in sidx:
            sidx[v] = len(strings)
            strings.append(v)
        return sidx[v]
    x = ['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    for r, row in enumerate(rows, 1):
        x.append(f'<row r="{r}">')
        for ci, v in enumerate(row):
            if v is None or v == "":
                continue
            ref = f"{_col(ci)}{r}"
            x.append(f'<c r="{ref}"><v>{v}</v></c>' if isinstance(v, (int, float)) else f'<c r="{ref}" t="s"><v>{si(v)}</v></c>')
        x.append("</row>")
    width = max(len(r) for r in rows)
    x.append('</sheetData><tableParts count="1"><tablePart xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rIdT1"/></tableParts></worksheet>')
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
                   '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
        f.writestr("_rels/.rels", f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{pkg}"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        f.writestr("xl/workbook.xml", f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="{rel}">'
                   f'<sheets><sheet name="{table}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        f.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{pkg}"><Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
                   f'<Relationship Id="rIdS" Type="{rel}/sharedStrings" Target="sharedStrings.xml"/></Relationships>')
        f.writestr("xl/worksheets/sheet1.xml", "".join(x))
        f.writestr("xl/worksheets/_rels/sheet1.xml.rels", f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{pkg}"><Relationship Id="rIdT1" Type="{rel}/table" Target="../tables/table1.xml"/></Relationships>')
        f.writestr("xl/tables/table1.xml", f'<?xml version="1.0" encoding="UTF-8"?><table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   f'id="1" name="{table}" displayName="{table}" ref="A1:{_col(width - 1)}{len(rows)}"/>')
        f.writestr("xl/sharedStrings.xml", '<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + "".join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings) + "</sst>")
    return z.getvalue()


HEAD = ["serviceDE", "serviceEN", "dailyrate", "hourlyrate", "order", "category"]
FILE = make_xlsx([HEAD, ["---- VIDEO ----"], ["Kamera", "Camera", 650, "", 1, ""], ["Licht", "Light", 300, "", 1, ""],
                  ["---- GRAFIK ----"], ["Animation 2D", "Animation 2D", 800, "", 2, ""], ["Motion", "Motion", 700, "", 2, ""],
                  ["---- POST ----"], ["Schnitt (Stundensatz)", "Editing (hourly)", "", 90, 3, ""]])


def services(s):
    return s.get(B + O + "/services?archived=1").json()["items"]


def by_name(s, kind="services"):
    return {(x.get("name_de") or x.get("name")): x for x in s.get(B + O + f"/{kind}?archived=1").json()["items"]}


def imp(s, svc=(), eq=()):
    """An import of invented rows (action new) -> run id."""
    rows = [{"row": i + 2, "name_de": n, "sort": 10001 + i, "daily_rate": 100 + i, "action": "new"} for i, n in enumerate(svc)]
    eqs = [{"row": i + 2, "name": n, "daily_rate": 20 + i, "action": "new"} for i, n in enumerate(eq)]
    r = s.post(B + L + "/import", json={"services": rows, "equipment": eqs})
    assert r.status_code == 201, r.text
    return r.json()["run_id"]


def offer(s, title, sids):
    r = s.post(B + O + "/docs", json={"kind": "offer", "project_title": title})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.put(B + O + f"/docs/{did}/items", json={"items": [{"kind": "service", "service_id": sid, "qty": 1} for sid in sids]})
    assert r.ok, r.text
    return did


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def run_of(s, rid):
    return next((x for x in s.get(B + L + "/runs").json()["runs"] if x["id"] == rid), {})


# ---------------------------------------------------------------- setup: two organisations, an admin, a member
if os.environ.get("P2138E_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})

# ---------------------------------------------------------------- #2237: the file's order for existing services
for n, srt, cat, rate in (("Schnitt (Stundensatz)", 1, "Post", None), ("Animation 2D", 2, "Grafik", 900), ("Kamera", 3, "Video", 700), ("Extra", 4, "Video", 50)):
    r = A.post(B + O + "/services", json={"name_de": n, "category": cat, "sort": srt, "daily_rate": rate})
    check(r.status_code == 201, "setup: service " + r.text[:200])
P = A.post(B + L + "/preview", files={"file": ("Leistungen.xlsx", FILE)}).json()
sv = {x["name_de"]: x for x in P.get("services", [])}
check(list(sv) == ["Kamera", "Licht", "Animation 2D", "Motion", "Schnitt (Stundensatz)"], f"preview reads the file {list(sv)}")
r = A.post(B + L + "/import", json={"services": P["services"]})
check(r.status_code == 201, "#2237: import " + r.text[:200])
RUN1 = r.json().get("run_id")
lst = services(A)
check([x["name_de"] for x in lst] == ["Kamera", "Licht", "Extra", "Animation 2D", "Motion", "Schnitt (Stundensatz)"],
      f"#2237: the list follows the file, a service not in the file stays in its category {[x['name_de'] for x in lst]}")
check([x["sort"] for x in lst] == [1, 2, 3, 4, 5, 6], f"#2237: numbered 1..n without gaps {[x['sort'] for x in lst]}")
S = by_name(A)
check(S["Kamera"]["daily_rate"] == 700 and S["Animation 2D"]["daily_rate"] == 900 and S["Kamera"]["name_en"] == "Camera",
      f"#2237: an existing service keeps its set rate, empty fields are filled {S['Kamera']}")

# ---------------------------------------------------------------- #2237: "Renumber"
for i, x in enumerate(lst):
    A.patch(B + O + f"/services/{x['id']}", json={"sort": (i + 1) * 10})
A.patch(B + O + f"/services/{S['Motion']['id']}", json={"sort": 0.5})  # moved to the top by hand
check(Bo.post(B + O + "/services/renumber").status_code == 403, "rights: a member cannot renumber (403)")
r = A.post(B + O + "/services/renumber")
check(r.ok and r.json()["changed"] == 6 and r.json()["before"].get(str(S["Motion"]["id"])) == 0.5, "#2237: renumber " + r.text[:300])
BEFORE = r.json().get("before", {})
lst = services(A)
check([x["name_de"] for x in lst] == ["Motion", "Animation 2D", "Kamera", "Licht", "Extra", "Schnitt (Stundensatz)"] and [x["sort"] for x in lst] == [1, 2, 3, 4, 5, 6],
      f"#2237: renumber keeps the shown order, 1..n {[(x['name_de'], x['sort']) for x in lst]}")
r = A.post(B + O + "/services/renumber")
check(r.ok and r.json()["changed"] == 0, "#2237: renumbering again changes nothing " + r.text[:200])
r = A.post(B + O + "/services/renumber", json={"sorts": BEFORE})
check(r.ok and by_name(A)["Motion"]["sort"] == 0.5 and by_name(A)["Extra"]["sort"] == 30, "#2237: the undo sets the old values back " + r.text[:200])
check(Ca.post(B + O + "/services/renumber", json={"sorts": {str(S["Kamera"]["id"]): 99}}).status_code == 400 and by_name(A)["Kamera"]["sort"] == 10,
      "tenant-matrix: office -- another organisation cannot set the order of a foreign service (400)")
r = Ca.post(B + O + "/services/renumber")
check(r.ok and r.json()["changed"] == 0 and by_name(A)["Motion"]["sort"] == 0.5, "tenant-matrix: office -- another organisation renumbers only its own services")
check(A.post(B + O + "/services/renumber", json={"sorts": {str(S["Kamera"]["id"]): "x"}}).status_code == 400, "renumber: a non-number = 400")
A.post(B + O + "/services/renumber")

# ---------------------------------------------------------------- #2241: undo archives used entries
RUN2 = imp(A, ["Neu A", "Neu B", "Prod X"], ["Gerät A", "Gerät B"])
S, E = by_name(A), by_name(A, "equipment")
DOC = offer(A, "Imagefilm Probe", [S["Neu A"]["id"], S["Prod X"]["id"]])
A.put(B + O + "/settings", json={"producing_service_id": S["Prod X"]["id"]})
r = A.post(B + O + "/sets", json={"name": "Interview-Set", "items": [{"equipment_id": E["Gerät A"]["id"], "qty": 1}]})
check(r.status_code == 201, "setup: a set " + r.text[:200])
check(Bo.post(B + L + f"/runs/{RUN2}/undo").status_code == 403, "rights: a member cannot undo (403)")
r = A.post(B + L + f"/runs/{RUN2}/undo")
check(r.ok, "#2241: undo " + r.text[:300])
arc = {x["name"]: x for x in r.json().get("archived", [])}
check(set(arc) == {"Neu A", "Gerät A"}, f"#2241: the used service and device are archived, named {sorted(arc)}")
check(any("Imagefilm Probe" in u for u in arc.get("Neu A", {}).get("used", [])) and arc.get("Gerät A", {}).get("used") == ["Interview-Set"],
      f"#2241: each with where it is used {arc}")
check(r.json()["removed"]["services"] == 1 and r.json()["removed"]["equipment"] == 1 and r.json()["kept"]["services"] == 1,
      f"#2241: unused ones deleted, the producing service kept {r.json().get('removed')} {r.json().get('kept')}")
S, E = by_name(A), by_name(A, "equipment")
check(S["Neu A"]["archived"] == 1 and E["Gerät A"]["archived"] == 1 and "Neu B" not in S and "Gerät B" not in E, "#2241: archived / deleted in the lists")
check(S["Prod X"]["archived"] == 0, "#2241: the producing service of the calculation rules without a replacement stays active")
d = A.get(B + O + f"/docs/{DOC}").json()
it = {x["title"]: x for x in d.get("items", [])}
check("Neu A" in it and float(it["Neu A"].get("rate") or 0) == 100 and it["Neu A"].get("service_id") == S["Neu A"]["id"], f"#2241: the document still shows the archived service {d.get('items')}")
r = A.patch(B + O + f"/services/{S['Neu A']['id']}", json={"archived": 0})
check(r.ok and by_name(A)["Neu A"]["archived"] == 0, "#2241: restore = archived 0")

# the producing service with another one in the rules: archived
RUN3 = imp(A, ["Prod Y"])
PY = by_name(A)["Prod Y"]["id"]
offer(A, "Werbespot Probe", [PY])
A.put(B + O + "/settings", json={"producing_service_id": by_name(A)["Kamera"]["id"]})
r = A.post(B + L + f"/runs/{RUN3}/undo")
check(r.ok and [x["name"] for x in r.json().get("archived", [])] == ["Prod Y"], "#2241: a producing service with another one in the rules is archived " + r.text[:300])

# ---------------------------------------------------------------- #2241: "Archive leftover entries" for an earlier undo
RUN4 = imp(A, ["Alt A", "Alt B"], ["Alt Gerät"])
S, E = by_name(A), by_name(A, "equipment")
offer(A, "Altkunde Probe", [S["Alt A"]["id"], S["Alt B"]["id"]])
A.post(B + O + "/sets", json={"name": "Alt-Set", "items": [{"equipment_id": E["Alt Gerät"]["id"], "qty": 1}]})
check(A.post(B + L + f"/runs/{RUN4}/tidy").status_code == 409, "#2241: tidy of a run not undone = 409")
r = A.post(B + L + f"/runs/{RUN4}/undo")
check(r.ok and len(r.json().get("archived", [])) == 3, "setup: undo " + r.text[:200])
# as an undo before 2.112 left them: active (2.144.6 B, #2400 F4: in the database; a PATCH archived 0 is a restore by hand)
dbx("UPDATE office_services SET archived=0 WHERE id IN (?, ?)", (S["Alt A"]["id"], S["Alt B"]["id"]))
dbx("UPDATE office_equipment SET archived=0 WHERE id=?", (E["Alt Gerät"]["id"],))
# RUN2: "Prod X" (the rules name another producing service by now); "Neu A" was restored by hand -> no leftover (#2400 F4)
check(run_of(A, RUN4).get("leftover") == 3 and run_of(A, RUN2).get("leftover") == 1, f"#2241: the runs count their leftovers {run_of(A, RUN4)} {run_of(A, RUN2)}")
check(Bo.post(B + L + f"/runs/{RUN4}/tidy").status_code == 403, "rights: a member cannot tidy (403)")
check(Ca.post(B + L + f"/runs/{RUN4}/tidy").status_code == 404, "tenant-matrix: office -- another organisation's run = 404")
r = A.post(B + L + f"/runs/{RUN4}/tidy")
check(r.ok and sorted(x["name"] for x in r.json().get("archived", [])) == ["Alt A", "Alt B", "Alt Gerät"], "#2241: tidy archives the run's leftovers " + r.text[:300])
S = by_name(A)
check(S["Alt A"]["archived"] == 1 and S["Alt B"]["archived"] == 1 and S["Neu A"]["archived"] == 0 and S["Kamera"]["archived"] == 0,
      "#2241: only the entries of this run, nothing else")
check(run_of(A, RUN4).get("leftover") == 0, "#2241: nothing left afterwards (the button goes)")
r = A.post(B + L + f"/runs/{RUN4}/tidy")
check(r.ok and r.json().get("archived") == [], "#2241: a second tidy finds nothing")
check(A.post(B + L + f"/runs/{RUN1}/tidy").status_code == 409, "#2241: the import that was never undone = 409")
acts = A.get(B + O + "/log?limit=50").json().get("log", [])
check(any(x.get("action") == "archive" and x.get("target") == "legacy" for x in acts), "#2241: the tidy is in the office log")

# ---------------------------------------------------------------- #2235: an invoice before the acceptance is no lock
def kva_invoice(S, who):
    r = S.post(B + D, json={"kind": "offer", "lang": "en", "project_title": "Campaign",
                            "items": [{"kind": "service", "title": "Concept", "qty": 1, "unit": "day", "rate": 800, "tax": "standard"}]})
    check(r.status_code == 201, f"{who}: a quotation {r.status_code} {r.text[:200]}")
    did = r.json()["id"]
    r = S.post(B + f"{D}/{did}/invoice", json={})
    check(r.status_code in (200, 201) and r.json().get("kind") == "invoice", f"{who}: #2235 invoice from a draft {r.status_code} {r.text[:200]}")
    r = S.post(B + f"{D}/{did}/status", json={"status": "sent"})
    check(r.ok and r.json().get("status") == "sent", f"{who}: mark as sent {r.text[:200]}")
    # 2.356.0 (#3003): the quotation has an invoice (the draft one above) -> 409 invoice_exists first, never a status lock (#2235)
    r = S.post(B + f"{D}/{did}/invoice", json={})
    check(r.status_code == 409 and r.json().get("code") == "invoice_exists", f"{who}: #3003 a second invoice asks first {r.status_code} {r.text[:200]}")
    r = S.post(B + f"{D}/{did}/invoice", json={"force": True})
    check(r.status_code in (200, 201) and r.json().get("kind") == "invoice", f"{who}: #2235 invoice from a sent quotation {r.status_code}")
    for st in ("accepted", "declined"):
        r = S.post(B + f"{D}/{did}/status", json={"status": st})
        check(r.ok and r.json().get("status") == st, f"{who}: status {st} {r.text[:200]}")


kva_invoice(A, "org")

# ---------------------------------------------------------------- a person without an organisation (personal office)
# freelancer-matrix: office
FID, Fr = freelancer(B, A)
for n, srt in (("Frei Z", 7), ("Frei Y", 3)):
    Fr.post(B + O + "/services", json={"name_de": n, "sort": srt})
r = Fr.post(B + O + "/services/renumber")
check(r.ok and r.json()["changed"] == 2 and [(x["name_de"], x["sort"]) for x in services(Fr)] == [("Frei Y", 1), ("Frei Z", 2)],
      "freelancer: renumber in the personal office " + r.text[:200])
RF = imp(Fr, ["Frei A", "Frei B"])
offer(Fr, "Hochzeitsfilm Probe", [by_name(Fr)["Frei A"]["id"]])
r = Fr.post(B + L + f"/runs/{RF}/undo")
check(r.ok and [x["name"] for x in r.json().get("archived", [])] == ["Frei A"] and r.json()["removed"]["services"] == 1, "freelancer: undo archives the used one " + r.text[:200])
Fr.patch(B + O + f"/services/{by_name(Fr)['Frei A']['id']}", json={"archived": 0})
r = Fr.post(B + L + f"/runs/{RF}/tidy")  # 2.144.6 B (#2400 F4): restored by hand -> tidy leaves it active
check(r.ok and r.json().get("archived") == [] and by_name(Fr)["Frei A"]["archived"] == 0, "freelancer: tidy " + r.text[:200])
check(Fr.post(B + L + f"/runs/{RUN4}/tidy").status_code == 404 and Fr.post(B + O + "/services/renumber", json={"sorts": {str(S["Kamera"]["id"]): 1}}).status_code == 400,
      "freelancer: no way into the organisation's runs / services")

kva_invoice(Fr, "freelancer")

# ---------------------------------------------------------------- #2242: Gesellschafter (GbR) / Partners (GbR), personal office
Fr.put(B + O + "/settings", json={"company_fields": {"managing_directors": "Erika Muster, Max Muster"}})


def footer(lang):
    q = Fr.post(B + D, json={"project_title": "Fuss"}).json()["id"]
    Fr.patch(B + f"{D}/{q}", json={"lang": lang})
    m = json.dumps(Fr.get(B + f"{D}/{q}/render").json(), ensure_ascii=False)
    Fr.delete(B + f"{D}/{q}")
    return m


for key in ("gbr_partners", "shareholders"):
    r = Fr.put(B + O + "/settings", json={"company_fields": {"md_label": key}})
    check(r.ok and r.json()["company_fields"]["md_label"] == key, f"#2242: {key} saved " + r.text[:100])
    de, en = ("Gesellschafter", "Shareholders" if key == "shareholders" else "Partners")
    check(f"{de}: Erika Muster" in footer("de"), f"#2242: {key} prints {de} (DE)")
    check(f"{en}: Erika Muster" in footer("en"), f"#2242: {key} prints {en} (EN)")
r = Fr.put(B + O + "/settings", json={"company_fields": {"md_label": "gbr"}})
check(r.status_code == 400, "#2242: an unknown word is still refused")

# ================================================================ #2238: the closing of the document PDF (no server)
# the text calls of every page are recorded (x, y, size, text) by wrapping the page class of the writer; pypdf opens each PDF.
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
spec = importlib.util.spec_from_file_location("office_pdf_p2138e", os.path.join(SRC, "kalmido", "office", "pdf.py"))
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)

from pypdf import PdfReader  # noqa: E402 (tests/requirements.txt)

# ---------------------------------------------------------------- recorder: every text / line call per page
PAGES = []
_Base = pdf._Page


class RecPage(_Base):
    def __init__(self):
        super().__init__()
        self.rec, self.rules = [], []
        PAGES.append(self)

    def text(self, x, y, s, size, bold=False, color=pdf.C_INK, align="l", spacing=0.0, width=None):
        s = str(s or "")
        if s:
            w = pdf.pdf_text_width(s, size, bold, spacing)
            x0 = (x + (width or 0) - w if width else x - w) if align == "r" else (x + ((width or 0) - w) / 2 if align == "c" else x)
            self.rec.append({"x": x0, "y": y, "w": w, "size": size, "s": s, "bold": bold})
        return super().text(x, y, s, size, bold, color, align, spacing, width)

    def line(self, x1, y1, x2, y2, w=0.5, color=pdf.C_RULE, dash=None):
        self.rules.append((x1, y1, x2, y2, w))
        return super().line(x1, y1, x2, y2, w, color, dash)


pdf._Page = RecPage


def render(model):
    PAGES.clear()
    data = pdf.office_pdf(model)
    r = PdfReader(io.BytesIO(data))
    return data, r, list(PAGES)


def money(v):
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 else "") + s + " €"


def item(pos, title, rate=100, detail=""):
    return {"kind": "item", "pos": pos, "title": title, "detail": detail, "qty": 1, "qty_text": "1", "unit_text": "Tag", "rate": rate,
            "rate_text": money(rate), "tax_pct": 19, "total": rate, "total_text": money(rate)}


def model(n_items=3, parts=None, title="Kostenvoranschlag", kind="offer", heading_every=0, closing=True):
    lines = []
    for i in range(1, n_items + 1):
        if heading_every and i % heading_every == 1:
            lines.append({"kind": "heading", "title": f"Gruppe {i // heading_every + 1}"})
        lines.append(item(i, f"Leistung Nummer {i}"))
    net = 100.0 * n_items
    m = {"kind": kind, "lang": "de", "currency": "EUR", "number": "KVA-2026-077", "date": "2026-10-19", "date_text": "19.10.2026",
         "title": title, "project_title": "Serie Beispielprojekt",
         "company": {"name": "Beispielstudio GmbH", "lines": ["Beispielstudio GmbH", "Musterweg 1", "12345 Musterstadt"],
                     "contact_lines": ["kontakt@example.com"], "color": "#6b4fbb"},
         "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktplatz 2", "54321 Beispielort"]},
         "intro": "Sehr geehrte Damen und Herren,\nwir bieten Ihnen an:",
         "lines": lines,
         "totals": {"rows": [["Summe Netto", money(net)], ["MwSt. 19 %", money(net * 0.19)], ["Gesamt", money(net * 1.19)]], "show_tax_lines": True,
                    "vat_note": "Alle Preise zuzüglich MwSt."},
         "labels": {"offer_no": "Angebot Nr.", "net_total": "Summe Netto", "page_of": "Seite {x} von {y}", "order": "Auftragserteilung"}}
    if closing:
        m["closing"] = "Wir freuen uns auf die Zusammenarbeit und stehen für Rückfragen gerne zur Verfügung."
        m["signature"] = "Mit freundlichen Grüßen"
        m["signature_name"] = "Erika Beispiel"
    if parts:
        m["parts"] = parts
    return m


# ---------------------------------------------------------------- 3. #2238: the closing stays together, no heading alone
def page_of(pages, pred):
    return [k for k, p in enumerate(pages) if any(pred(t) for t in p.rec)]


# 2.138.0 (#2238): the body ends above the footer of this company (its height follows the footer columns since 2.114.5)
BOTTOM = pdf.A4_H - 12 * pdf.MM - pdf.p3f_foot_h(pdf.p3f_fit(pdf.pdf_footer_cols(model()["company"])))


def body(p):
    return [t for t in p.rec if pdf.PDF_NEXT_TOP - 1 <= t["y"] < BOTTOM]


TAIL = (lambda t: t["s"] == "Summe Netto", lambda t: t["s"].startswith("Wir freuen uns"), lambda t: t["s"] == "Erika Beispiel")
tight = []
for kind in ("offer", "invoice"):
    for n in range(8, 61):
        m = model(n_items=n, kind=kind, heading_every=5)
        if kind == "invoice":
            m["payment"] = {"text": "Bitte überweisen Sie den Betrag bis zum 02.11.2026.", "iban": "DE00000000000000000000", "bic": "XXXXDEXXXXX"}
        data, r, pages = render(m)
        tag = f"{kind} {n} positions"
        if not data.startswith(b"%PDF-1.7") or len(r.pages) != len(pages):
            check(False, f"{tag}: the PDF renders")
            continue
        where = [page_of(pages, f) for f in TAIL]
        if kind == "offer":
            where.append(page_of(pages, lambda t: t["s"] == "AUFTRAGSERTEILUNG"))
        else:
            where.append(page_of(pages, lambda t: t["s"].startswith("Bitte überweisen")))
        check(all(len(w) == 1 for w in where) and len({w[0] for w in where}) == 1, f"{tag}: totals, closing text, signature together ({where})")
        sp = where[0][0] if where[0] else 0
        check(any(t["s"].startswith("Leistung Nummer") for t in pages[sp].rec), f"{tag}: the closing page has a position")
        for k, p in enumerate(pages):
            bt = body(p)
            if not bt:
                continue
            low = max(t["y"] for t in bt)
            last = [t["s"] for t in bt if t["y"] > low - 0.5]
            check(not any(x.startswith("GRUPPE ") for x in last), f"{tag}, page {k + 1}: no group heading alone at the page end ({last})")
            check(all(t["y"] + t["size"] <= BOTTOM + 0.5 for t in bt), f"{tag}, page {k + 1}: nothing below the body bottom")
        sig = [t for t in pages[sp].rec if t["s"] == "Erika Beispiel" or t["s"] == "Unterschrift, Stempel Auftraggeber"]  # 2.185.0 C (#2520): PDF_LABELS holds the English keys now
        if sig and BOTTOM - max(t["y"] + t["size"] for t in sig) < 24:
            tight.append(tag)
check(len(tight) >= 1, f"at least one length puts the closing right at the page end ({tight[:4]})")

# a closing longer than one page (40 rights rows: the rights block alone fits a page, the whole closing not) may break
m = model(n_items=10)
m["rights"] = {"title": "Rechteübertragung", "rows": [[f"Recht {i}", "weltweit"] for i in range(1, 41)]}
data, r, pages = render(m)
allt = "\n".join(t["s"] for p in pages for t in p.rec)
check(data.startswith(b"%PDF-1.7") and 2 <= len(pages) <= 6, f"a closing longer than a page breaks ({len(pages)} pages)")
check(all(f"Recht {i}" in allt for i in range(1, 41)) and "Erika Beispiel" in allt, "every rights row and the signature are printed")

print(f"p2138_e_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
