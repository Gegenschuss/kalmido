#!/usr/bin/env python3
"""2.40.0 API tests (agent K: office & finance -- clients and the legacy import), own container in mode workspaces (start.sh).
Invented companies, people and addresses only; the PDFs are generated here (a one-page text layer, or none = a scan).
 - #1380 contact persons: the old contact field becomes the default at start-up (also for a row an older version wrote),
   the list via PATCH {contacts} (add / change / delete / default; contact = the default's name), validation, the
   organisation boundary (another organisation 404); documents: contact_id (default, another one, none), the attn. line
   follows, a foreign contact 400, the e-invoice carries BT-56 (name, phone, e-mail), finalised = snapshot
 - #1380 import: a duplicate (in the file / an existing client) with another contact person is proposed as "contact",
   the import adds it (counts.contacts), the undo removes it again
 - #1372 countries: ISO 3166-1 alpha-2 only (UK -> GB, EL -> GR, XX 400) for clients and the company; an unknown stored
   value stops the finalising; the XML carries the code
 - #1421 the recipient's address of an archived PDF: page 1 read (not the own sender line), proposals new client /
   contact person / address differs, a scan = no_text; archiving with the ticked proposals creates the client / the
   contact person in the run (the same company again reuses it); the undo takes them back; rights (member, agent)
 - #1335 the archive file exists only after the commit (no .part left)
usage: p2400_k_api_test.py <datadir>"""
import io
import json
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
FAILS, OKS = [], [0]
TEST_IBAN = "DE02120300000000202051"


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
        r = c.execute(sql, args).fetchall() if not write else c.execute(sql, args)
        if write:
            c.commit()
            return None
        return r
    finally:
        c.close()


def text_pdf(lines, tag=""):
    """A one-page PDF whose text layer holds lines (top to bottom; (y, size, text) or text); no lines = like a scan."""
    ops, y = [], 800
    for ln in lines:
        if isinstance(ln, tuple):
            y, size, t = ln
        else:
            size, t = 11, ln
        t = t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"BT /F1 {size} Tf 60 {y} Td ({t}) Tj ET")
        y -= 16
    content = ("\n".join(ops) + f"\n% {tag}").encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out


def make_xlsx(rows):
    """A minimal .xlsx with one sheet "Contacts" (column "addresses"), strings only."""
    strings = [r[0] for r in rows]
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
        f.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        f.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Contacts" sheetId="1" r:id="rId1"/></sheets></workbook>')
        f.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rIdS" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>')
        f.writestr("xl/worksheets/sheet1.xml", '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                   + "".join(f'<row r="{i}"><c r="A{i}" t="s"><v>{i - 1}</v></c></row>' for i in range(1, len(strings) + 1)) + "</sheetData></worksheet>")
        f.writestr("xl/sharedStrings.xml", '<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + "".join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings) + "</sst>")
    return z.getvalue()


# ---------------------------------------------------------------- setup: two organisations, a member, an agent
FEAT = "cal,comments,collab,office,clients,time"
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
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
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
O, D, L = "/api/office", "/api/office/docs", "/api/office/legacy"
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht GmbH"}, "lang": "de", "currency": "EUR",
                                     "company_fields": {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                        "country": "DE", "email": "hallo@nordlicht.example", "phone": "+49 40 000000", "tax_number": "12/345/67890",
                                                        "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}, "payment_days": 14})
check(r.ok, "office settings with company data " + r.text[:160])

# ---------------------------------------------------------------- #1380 migration: the contact field becomes the default
r = A.post(B + "/api/clients", json={"name": "Muster Medien GmbH", "contact": "Erika Beispiel", "street": "Lindenweg 4", "zip": "50667",
                                     "city": "Köln", "country": "DE", "org_id": ORG})
check(r.status_code == 201 and [k["name"] for k in r.json()["contacts"]] == ["Erika Beispiel"] and r.json()["contacts"][0]["is_default"],
      "a new client with contact: the default contact person " + r.text[:200])
CL = r.json()["id"]
# a client the way 2.39.1 writes it (only the column) and one whose contact an older version renamed
dbx("INSERT INTO clients(org_id, name, contact, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?)",
    (ORG, "Altkunde KG", "Hans Alt", ALICE, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"), write=True)
dbx("UPDATE clients SET contact='Erika Neu' WHERE id=?", (CL,), write=True)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(env, KEEP="1"), capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
cls = {c["name"]: c for c in A.get(B + "/api/clients").json()["clients"]}
check([k["name"] for k in cls["Altkunde KG"]["contacts"]] == ["Hans Alt"] and cls["Altkunde KG"]["contacts"][0]["is_default"],
      f"migration: the old contact field became the default contact person {cls['Altkunde KG'].get('contacts')}")
check([k["name"] for k in cls["Muster Medien GmbH"]["contacts"]] == ["Erika Neu"], "migration: a contact renamed by an older version renames the default")
n1 = dbx("SELECT COUNT(*) FROM office_client_contacts")[0][0]
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(env, KEEP="1"), capture_output=True, text=True)
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
check(dbx("SELECT COUNT(*) FROM office_client_contacts")[0][0] == n1, "migration: idempotent (a second start adds nothing)")

# ---------------------------------------------------------------- #1380 the list
k0 = cls["Muster Medien GmbH"]["contacts"][0]["id"]
r = A.patch(B + f"/api/clients/{CL}", json={"contacts": [{"id": k0, "name": "Erika Neu", "role": "Einkauf"},
                                                         {"name": "Max Probe", "email": "max@example.com", "phone": "+49 221 1234", "is_default": True},
                                                         {"name": "Ida Muster", "role": "Buchhaltung"}]})
ks = r.json().get("contacts") or []
check(r.ok and [k["name"] for k in ks] == ["Max Probe", "Erika Neu", "Ida Muster"] and ks[0]["is_default"] and r.json()["contact"] == "Max Probe",
      f"contacts: added, changed, the default first and contact = its name {ks}")
KMAX, KERI, KIDA = ks[0]["id"], ks[1]["id"], ks[2]["id"]
check(dbx("SELECT contact FROM clients WHERE id=?", (CL,))[0][0] == "Max Probe", "contacts: clients.contact follows the default (2.39.1 reads it)")
r = A.patch(B + f"/api/clients/{CL}", json={"contacts": [{"id": KMAX, "name": "Max Probe", "email": "max@example.com", "phone": "+49 221 1234"},
                                                         {"id": KERI, "name": "Erika Neu", "role": "Einkauf"}]})
check(r.ok and KIDA not in [k["id"] for k in r.json()["contacts"]] and len(r.json()["contacts"]) == 2, "contacts: a missing one is deleted")
check(A.patch(B + f"/api/clients/{CL}", json={"contacts": [{"name": "X", "email": "no-mail"}]}).status_code == 400, "contacts: an invalid e-mail = 400")
check(A.patch(B + f"/api/clients/{CL}", json={"contacts": [{"name": ""}]}).status_code == 400, "contacts: a contact person without a name = 400")
check(A.patch(B + f"/api/clients/{CL}", json={"contacts": [{"id": 999999, "name": "X"}]}).status_code == 400, "contacts: an unknown id = 400")
check(A.patch(B + f"/api/clients/{CL}", json={"contacts": "x"}).status_code == 400, "contacts: not a list = 400")
r = A.post(B + "/api/clients", json={"name": "Nordwind Film KG", "zip": "10115", "city": "Berlin", "country": "DE", "org_id": ORG})
NORD = r.json()["id"]
r = A.patch(B + f"/api/clients/{NORD}", json={"contact": "Jonas Probe"})
check(r.ok and [k["name"] for k in r.json()["contacts"]] == ["Jonas Probe"], "the old field contact adds the default")
r = A.patch(B + f"/api/clients/{NORD}", json={"contact": "Jonas Probe-Beispiel"})
check(r.ok and [k["name"] for k in r.json()["contacts"]] == ["Jonas Probe-Beispiel"], "the old field contact renames the default")
# the organisation boundary
r = Ca.post(B + "/api/clients", json={"name": "Fremdfirma AG", "contact": "Clara Fremd"})
CLB = r.json()["id"]
check(Ca.get(B + f"/api/clients/{CL}").status_code == 404, "tenant-matrix: client -- another organisation does not see the client (404)")
check(Ca.patch(B + f"/api/clients/{CL}", json={"contacts": [{"name": "Eve"}]}).status_code == 404, "tenant-matrix: client -- another organisation cannot change its contacts (404)")
check(A.get(B + f"/api/clients/{CLB}").status_code == 404, "tenant-matrix: client -- the first organisation does not see the other's client")
check(requests.get(B + "/api/v1/clients", headers=AGH).json().get("clients", []) == [] or requests.get(B + "/api/v1/clients", headers=AGH).status_code in (403, 409),
      "an agent token sees no clients (no contact persons)")
check(dbx("SELECT org_id FROM office_client_contacts WHERE client_id=?", (CLB,))[0][0] == ORG2, "a contact person carries the client's organisation (row-level security)")

# ---------------------------------------------------------------- #1380 documents
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-01-05", "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]})
check(r.status_code == 201, "an invoice draft for the client " + r.text[:200])
I1 = r.json()["id"]
d = r.json()
check(d["recipient"]["lines"][:2] == ["Muster Medien GmbH", "Max Probe"] and d.get("contact_id") is None and len(d.get("client_contacts") or []) == 2,
      f"document: the default contact in the attn. line, the choice in client_contacts {d['recipient']} {d.get('contact_id')}")
r = A.patch(B + f"{D}/{I1}", json={"contact_id": KERI})
check(r.ok and r.json()["recipient"]["lines"][:2] == ["Muster Medien GmbH", "Erika Neu"] and r.json()["contact_id"] == KERI, "document: another contact person replaces the attn. line")
r = A.patch(B + f"{D}/{I1}", json={"contact_id": 0})
check(r.ok and "Erika Neu" not in r.json()["recipient"]["lines"], "document: no contact person removes the attn. line")
r = A.patch(B + f"{D}/{I1}", json={"contact_id": KMAX})
check(r.ok and r.json()["recipient"]["lines"][1] == "Max Probe", "document: back to Max")
nk = A.get(B + f"/api/clients/{NORD}").json()["contacts"][0]["id"]
check(A.patch(B + f"{D}/{I1}", json={"contact_id": nk}).status_code == 400, "document: a contact person of another client = 400")
r = A.post(B + f"{D}/{I1}/finalize")
check(r.ok, "finalised " + r.text[:200])
x = A.get(B + f"{D}/{I1}/xml").text
bp = x[x.find("BuyerTradeParty"):x.find("</ram:BuyerTradeParty>")]
check("<ram:DefinedTradeContact>" in bp and "<ram:PersonName>Max Probe</ram:PersonName>" in bp and "+49 221 1234" in bp and "max@example.com" in bp,
      "e-invoice: BT-56 buyer contact with phone and e-mail " + bp[:400])
check(bp.find("DefinedTradeContact") < bp.find("PostalTradeAddress"), "e-invoice: the buyer contact stands before the address (schema order)")
snap = json.loads(dbx("SELECT recipient_snapshot FROM office_docs WHERE id=?", (I1,))[0][0])
check((snap.get("contact") or {}).get("name") == "Max Probe", f"finalised: the contact person is in the snapshot {snap.get('contact')}")
A.patch(B + f"/api/clients/{CL}", json={"contacts": [{"id": KMAX, "name": "Max Umbenannt", "is_default": True}, {"id": KERI, "name": "Erika Neu"}]})
check(A.get(B + f"{D}/{I1}").json()["recipient"]["lines"][1] == "Max Probe", "finalised: the attn. line keeps its snapshot after a rename")
r = A.post(B + D, json={"kind": "offer", "client_id": CL, "contact_id": KERI})
check(r.status_code == 201 and r.json()["recipient"]["lines"][1] == "Erika Neu" and r.json()["contact_id"] == KERI, "quotation: the contact chosen at creation " + r.text[:200])
OF = r.json()["id"]
r = A.post(B + f"{D}/{OF}/invoice")
if r.status_code in (200, 201):
    check(r.json().get("contact_id") == KERI, "an invoice from the quotation keeps the contact person")

# ---------------------------------------------------------------- #1380 import: another contact person = "contact"
XLSX = make_xlsx([["addresses"],
                  ["Kanalwerk Agentur GmbH\nz. Hd. Anna Eins\nSpeicherstadt 4\n20457 Hamburg"],
                  ["Kanalwerk Agentur GmbH\nz. Hd. Bert Zwei\nSpeicherstadt 4\n20457 Hamburg"],
                  ["Kanalwerk Agentur GmbH\nz. Hd. Anna Eins\nSpeicherstadt 4\n20457 Hamburg"],
                  ["Nordwind Film KG\nz. Hd. Lena Drei\nAm Markt 1\n10115 Berlin"],
                  ["Nordwind Film KG\nz. Hd. Jonas Probe-Beispiel\nAm Markt 1\n10115 Berlin"]])
r = A.post(B + L + "/preview", files={"file": ("DATA.xlsx", XLSX, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
check(r.ok, "preview " + r.text[:200])
pv = r.json()["clients"]
acts = [(c["row"], c["action"], (c["dup"] or {}).get("kind")) for c in pv]
check(acts == [(2, "new", None), (3, "contact", "file"), (4, "skip", "file"), (5, "contact", "existing"), (6, "skip", "existing")],
      f"preview: another contact person of a duplicate is proposed as contact person, the same one is skipped {acts}")
rows = [{k: c.get(k) for k in ("row", "name", "contact", "street", "zip", "city", "country", "address", "action")} for c in pv]
rows[1]["contact_row"] = pv[1]["dup"]["row"]
rows[3]["merge_id"] = pv[3]["dup"]["id"]
r = A.post(B + L + "/import", json={"clients": rows})
check(r.status_code == 201 and r.json()["counts"].get("contacts") == 2 and r.json()["counts"]["clients"] == 1, "import: two contact persons added " + r.text[:200])
RUN = r.json()["run_id"]
cls = {c["name"]: c for c in A.get(B + "/api/clients").json()["clients"]}
check([k["name"] for k in cls["Kanalwerk Agentur GmbH"]["contacts"]] == ["Anna Eins", "Bert Zwei"], f"import: the new client with both contact persons {cls['Kanalwerk Agentur GmbH']['contacts']}")
check("Lena Drei" in [k["name"] for k in cls["Nordwind Film KG"]["contacts"]] and cls["Nordwind Film KG"]["contact"] == "Jonas Probe-Beispiel",
      "import: the existing client got the contact person, its default stays")
check(A.post(B + L + "/import", json={"clients": [{"row": 3, "name": "X", "contact": "Y", "action": "contact", "contact_row": 2}]}).status_code == 400,
      "import: a contact person for a row that is not imported = 400")
check(A.post(B + L + "/import", json={"clients": [{"row": 3, "name": "X", "contact": "Y", "action": "contact", "merge_id": CLB}]}).status_code == 400,
      "tenant-matrix: office -- a contact person for another organisation's client = 400")
r = A.post(B + L + f"/runs/{RUN}/undo")
check(r.ok and r.json()["removed"]["contacts"] == 1 and r.json()["removed"]["clients"] == 1, "undo: the new client and the added contact person are removed " + r.text[:200])
cls = {c["name"]: c for c in A.get(B + "/api/clients").json()["clients"]}
check("Kanalwerk Agentur GmbH" not in cls and [k["name"] for k in cls["Nordwind Film KG"]["contacts"]] == ["Jonas Probe-Beispiel"], "undo: the existing client is as before")

# ---------------------------------------------------------------- #1372 countries
r = A.patch(B + f"/api/clients/{NORD}", json={"country": "uk"})
check(r.ok and r.json()["billing"]["country"] == "GB", "country: UK becomes GB")
r = A.patch(B + f"/api/clients/{NORD}", json={"country": "EL"})
check(r.ok and r.json()["billing"]["country"] == "GR", "country: EL becomes GR")
check(A.patch(B + f"/api/clients/{NORD}", json={"country": "XX"}).status_code == 400, "country: XX = 400")
check(A.patch(B + f"/api/clients/{NORD}", json={"country": "Deutschland"}).status_code == 400, "country: a name instead of a code = 400")
r = A.patch(B + f"/api/clients/{NORD}", json={"country": ""})
check(r.ok and r.json()["billing"]["country"] == "", "country: empty (= Germany) is allowed")
check(A.put(B + O + "/settings", json={"company_fields": {"country": "QQ"}}).status_code == 400, "company country: QQ = 400")
r = A.put(B + O + "/settings", json={"company_fields": {"country": "at"}})
check(r.ok, "company country: AT " + r.text[:120])
A.put(B + O + "/settings", json={"company_fields": {"country": "DE"}})
dbx("UPDATE clients SET country='XX' WHERE id=?", (NORD,), write=True)
r = A.post(B + D, json={"kind": "invoice", "client_id": NORD, "service_from": "2026-01-06", "items": [{"title": "Ton", "qty": 1, "rate": 50}]})
I2 = r.json()["id"]
dbx("UPDATE clients SET street='Am Markt 1' WHERE id=?", (NORD,), write=True)
r = A.post(B + f"{D}/{I2}/finalize")
check(r.status_code == 400 and "XX" in r.text, "an unknown stored country stops the finalising (not silently DE) " + r.text[:200])
check(A.patch(B + f"/api/clients/{NORD}", json={"name": "Nordwind Film KG"}).ok, "a client with an old invalid country can still be saved without touching it")
dbx("UPDATE clients SET country='AT' WHERE id=?", (NORD,), write=True)
r = A.post(B + f"{D}/{I2}/finalize")
x = A.get(B + f"{D}/{I2}/xml").text
bp = x[x.find("BuyerTradeParty"):]
check(r.ok and "<ram:CountryID>AT</ram:CountryID>" in bp, "XML: the buyer's country code")

# ---------------------------------------------------------------- #1421 the address of an old PDF
SENDER = (790, 7, "Studio Nordlicht GmbH · Hafenstraße 12 · 20457 Hamburg")
P1 = text_pdf([SENDER, "Leuchtturm Verlag GmbH", "z. Hd. Frau Ida Leser", "Ringstraße 5", "04109 Leipzig", (600, 14, "Rechnung 2023-017"),
               "Datum: 12.03.2023", (60, 8, "Studio Nordlicht GmbH, Hafenstraße 12, 20457 Hamburg, IBAN DE02 1203 0000 0000 2020 51")], "p1")
P2 = text_pdf([SENDER, "Muster Medien GmbH", "z. Hd. Herrn Paul Neu", "Hauptweg 9", "50667 Köln", (600, 14, "Angebot 2023-004")], "p2")
P3 = text_pdf([], "scan")
P4 = text_pdf([SENDER, "Leuchtturm Verlag GmbH", "z. Hd. Frau Ida Leser", "Ringstraße 5", "04109 Leipzig", (600, 14, "Rechnung 2023-018")], "p4")


def addr(sess_, pdf, cid=None):
    return sess_.post(B + L + "/archive/address", files={"file": ("a.pdf", pdf, "application/pdf")}, data={"client_id": cid or ""})


r = addr(A, P1)
j = r.json()
a = j.get("address") or {}
check(r.ok and j["status"] == "ok" and (a.get("name"), a.get("contact"), a.get("street"), a.get("zip"), a.get("city")) ==
      ("Leuchtturm Verlag GmbH", "Frau Ida Leser", "Ringstraße 5", "04109", "Leipzig"), f"PDF: the recipient block, not the own sender line {j}")
check(j.get("new_client") and not j.get("client_id") and not j.get("unsure"), "PDF: unknown company = proposal new client")
j = addr(A, P2).json()
check(j["status"] == "ok" and j["client_id"] == CL and j["add_contact"] == "Herrn Paul Neu" and j["address_differs"],
      f"PDF: known client, another contact person and another address = the two proposals {j}")
check(addr(A, P3).json()["status"] == "no_text", "PDF: a scan without text = hint, no OCR")
check(addr(A, b"GIF89a").status_code == 400, "PDF: only PDF files")
check(addr(Bo, P1).status_code == 403, "rights: a member cannot read addresses of the archive import")
check(requests.post(B + L + "/archive/address", headers=AGH, files={"file": ("a.pdf", P1, "application/pdf")}).status_code in (401, 403), "rights: an agent cannot")
RA = A.post(B + L + "/archive/run").json()["run_id"]
na = {k: a[k] for k in ("name", "contact", "street", "zip", "city", "country")}


def up(pdf, meta, name="a.pdf"):
    return A.post(B + L + "/archive", files={"file": (name, pdf, "application/pdf")}, data={k: ("" if v is None else str(v)) for k, v in meta.items()})


r = up(P1, {"run_id": RA, "kind": "invoice", "number": "ALT-2023-017", "new_client": json.dumps(na)})
check(r.status_code == 201 and r.json()["client_id"], "archive with the ticked proposal: the new client " + r.text[:200])
NEWC = r.json().get("client_id")
r = up(P4, {"run_id": RA, "kind": "invoice", "number": "ALT-2023-018", "new_client": json.dumps(na)})
check(r.status_code == 201 and r.json()["client_id"] == NEWC, "the same company again in the run reuses the new client")
r = up(P2, {"run_id": RA, "kind": "offer", "number": "ALT-2023-004", "client_id": CL, "add_contact": "Herrn Paul Neu"})
check(r.status_code == 201, "archive with the contact person proposal " + r.text[:200])
cls = {c["name"]: c for c in A.get(B + "/api/clients").json()["clients"]}
check([k["name"] for k in cls["Leuchtturm Verlag GmbH"]["contacts"]] == ["Frau Ida Leser"] and cls["Leuchtturm Verlag GmbH"]["contact"] == "Frau Ida Leser",
      "the new client carries the contact person as its default")
check("Herrn Paul Neu" in [k["name"] for k in cls["Muster Medien GmbH"]["contacts"]], "the existing client got the contact person")
check(up(text_pdf(["x"], "t5"), {"run_id": RA, "kind": "invoice", "number": "ALT-X", "add_contact": "Y", "client_id": CLB}).status_code == 400,
      "tenant-matrix: office -- a contact person for another organisation's client from the archive = 400")
# #1335: only the archived files, no .part left behind
od = os.path.join(DATA, "office", str(ORG))
names = os.listdir(od) if os.path.isdir(od) else []
check(not [n for n in names if n.endswith(".part")] and len([n for n in names if n.startswith("archive-")]) == 3, f"#1335: three archive files, no .part {names}")
check(len(dbx("SELECT 1 FROM office_archive WHERE org_id=?", (ORG,))) == 3, "#1335: three rows for the three files")
r = A.post(B + L + f"/runs/{RA}/undo")
check(r.ok and r.json()["removed"]["clients"] == 1 and r.json()["removed"]["contacts"] == 1 and r.json()["removed"]["archive"] == 3,
      "undo of the archive run: the new client, the contact person and the documents " + r.text[:200])
cls = {c["name"]: c for c in A.get(B + "/api/clients").json()["clients"]}
check("Leuchtturm Verlag GmbH" not in cls and "Herrn Paul Neu" not in [k["name"] for k in cls["Muster Medien GmbH"]["contacts"]], "undo: clients as before")

# 2.81.0 (#1463): reading an address shares the /api/pdf-text budget (10 per account in 10 minutes) -> 429
codes = [addr(A, P1).status_code for _ in range(12)]
check(429 in codes and codes.index(429) <= 10 and set(codes[codes.index(429):]) == {429}, f"#1463: the address read is throttled per account {codes}")

print(f"p2400_k_api_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
