#!/usr/bin/env python3
"""2.137.0 part A (#2344): the organisation import takes the clients and the whole office over. Invented names only.
 - an organisation with office data of every main kind (client with contact person, service, settings + logo, quotation
   with positions, finalised invoice with a payment, invoice series, cash book with a closed day, trip with a receipt,
   framework contract with its file) is exported and imported into an empty second organisation of another admin: the
   values, the references, the finalised state and the numbers come along, the files are readable and sealed at rest
   where the app seals them; the source organisation stays unchanged; the undo removes everything again
 - the same export into the source organisation itself: existing document numbers are skipped with a warning, never twice
 - a person without an organisation imports it into the private space: it lands in the personal office
 - that person exports the personal office (only the owner; others 404) and an admin imports it into an organisation:
   the office and the private clients come along, the private lists do not
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2137A_NOSTART=1 = the server already runs like that).
usage: p2137_a_api_test.py <datadir>"""
# freelancer-matrix: office
# tenant-matrix: own
import base64
import os
import struct
import subprocess
import sys
import time
import zlib

import requests

import dbx as dbxm
from freelancer_fixture import FEATURES, freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess, su_get  # 2.206.0 (#2762): shared helpers (tests/kt.py)
O, D = "/api/office", "/api/office/docs"


def logs():
    ct = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
    out = subprocess.run(["docker", "logs", "--tail", "300", ct], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
    keep = [x for x in out.splitlines() if any(k in x for k in ('File "/app', "Error", "rror:", "import of user", "Killed", "Segmentation",
                                                                 "WORKER", "Worker", "signal", "Exception"))]
    for x in keep[-30:]:
        print("FAIL-LOG:", x[:300], flush=True)


sys.excepthook = lambda t, v, tb: (print("FAIL: crashed", t.__name__, str(v)[:200], flush=True), logs(), sys.exit(1))


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def upload(s, data, name="alpha.kalmido-export"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid, secs=180):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def opened(s, data, rk):
    iid = upload(s, data)
    j = wait(s, iid)
    check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {j.get('error')}")
    check(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
    j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    return iid, j.get("preview") or {}


def run(s, iid, target, people=None):
    # 2.269.0 (#3046): "again" = the person saw the preview's warning (a second import of one export is 409 without it)
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": people or {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    return wait(s, iid)


def export(s, oid):
    r = s.post(B + f"/api/orgs/{oid}/export")
    check(r.status_code == 202, f"export started {r.status_code} {r.text[:160]}")
    for _ in range(480):
        if s.get(B + f"/api/orgs/{oid}/export").json().get("state") != "running":
            break
        time.sleep(0.25)
    data = (su_get(s, B + f"/api/orgs/{oid}/export/file") if oid == 0 else s.get(B + f"/api/orgs/{oid}/export/file")).content  # 2.223.2 C (#2871): the own office: step-up
    rk = s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
    check(data[:13] == b"KALMIDO-ORGX\n" and rk, f"export + recovery key of {oid}")
    return data, rk


def png():
    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes((40, 90, 160)) * 8 for _ in range(8))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def warnings(j):
    return " | ".join(x.get("text", "") for x in (j.get("result") or {}).get("warnings", []))


def office_counts(oid):
    return {t: dbx(f"SELECT COUNT(*) AS n FROM {t} WHERE org_id=?", (oid,))[0]["n"] for t in (
        "office_docs", "office_doc_items", "office_payments", "office_inv_series", "office_cashbooks", "office_cash_entries",
        "office_cash_closings", "office_trips", "office_trip_items", "office_contracts", "office_contract_files", "office_services",
        "office_numbers", "office_settings", "office_company")}


if not os.environ.get("P2137A_NOSTART"):
    env = dict(os.environ, EXTRA=f"-e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Buero", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
ids = {}
for u, n in (("carol", "Carol Ziel"), ("dora", "Dora Ziel")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Ca, Do = sess("carol"), sess("dora")
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha Buero", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta Ziel", "admin_id": ids["carol"]})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Gamma Ziel", "admin_id": ids["dora"]})
assert r.status_code == 201, r.text
ORG3 = r.json()["id"]
for s, ws in ((A, ORG), (Ca, ORG2), (Do, ORG3)):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done", "workspace": f"org:{ws}"})

# ---------------------------------------------------------------- the office of the source organisation
CL = A.post(B + "/api/clients", json={"name": "Kunde Beispiel", "email": "kunde@example.com", "org_id": ORG, "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt",
                                     "contacts": [{"name": "Petra Beispiel", "email": "petra@example.com", "is_default": True}]}).json()["id"]
r = A.post(B + f"{O}/services", json={"name_de": "Schnitt", "name_en": "Editing", "daily_rate": 980, "unit": "day", "tax": "standard"})
check(r.status_code == 201, "a service " + r.text[:120])
SV = r.json().get("id")
r = A.put(B + f"{O}/settings", json={"company_fields": {"name": "Alpha Studio GmbH", "street": "Hafenweg 2", "zip": "12345", "city": "Musterstadt", "iban": "DE02120300000000202051",
                                                         "tax_number": "12/345/67890"}, "lang": "en", "currency": "EUR"})
check(r.ok, "office settings " + r.text[:120])
LOGO = png()
check(A.post(B + f"{O}/logo", files={"file": ("logo.png", LOGO, "image/png")}).ok, "logo uploaded")
LOGO_SRC = A.get(B + f"{O}/logo").content
r = A.post(B + D, json={"project_title": "Imagefilm", "client_id": CL})
check(r.status_code == 201, "a quotation " + r.text[:120])
OFF = r.json().get("id")
r = A.put(B + f"{D}/{OFF}/items", json={"items": [{"service_id": SV, "qty": 2}, {"title": "Dreh", "qty": 1, "rate": 900}]})
check(r.ok, "quotation positions " + r.text[:120])
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-05-01", "items": [{"title": "Beratung", "qty": 1, "rate": 300}]})
check(r.status_code == 201, "an invoice " + r.text[:120])
INV = r.json().get("id")
r = A.post(B + f"{D}/{INV}/finalize")
check(r.ok and r.json().get("locked"), "the invoice is finalised " + r.text[:160])
INV_NO = r.json().get("number")
check(A.post(B + f"{D}/{INV}/payments", json={"date": "2026-06-01", "amount": "100.00", "method": "transfer"}).status_code == 201, "a payment")
INV_PDF = A.get(B + f"{D}/{INV}/pdf").content
TPL = A.post(B + D, json={"kind": "invoice", "client_id": CL, "project_title": "Betreuung {month}", "service_from": "2026-01-01",
                          "service_to": "2026-01-31", "items": [{"title": "Betreuung", "qty": 1, "rate": 500}]}).json()["id"]
r = A.post(B + f"{O}/series", json={"template_id": TPL, "every": "monthly", "start": "2027-01-31", "title": "Betreuung Kunde"})
check(r.status_code == 201, "an invoice series " + r.text[:160])
BK = A.get(B + f"{O}/cashbooks").json()["books"][0]["id"]
A.patch(B + f"{O}/cashbooks/{BK}", json={"opening": "100", "opening_day": "2026-01-01"})
r = A.post(B + f"{O}/cashbooks/{BK}/entries", json={"day": "2026-03-01", "dir": "in", "amount": "50", "text": "Verkauf Theke", "vat_pct": "19"})
check(r.status_code == 201, "a cash entry " + r.text[:160])
check(A.post(B + f"{O}/cashbooks/{BK}/closing", json={"day": "2026-03-02"}).status_code == 201, "a cash day closed")
r = A.post(B + f"{O}/trips", json={"date_from": "2025-09-03", "date_to": "2025-09-04", "dest": "Musterstadt - Beispielhausen", "overnight": True,
                                   "people": [{"id": ALICE}], "purpose": "job", "client_id": CL, "km": 12,
                                   "items": [{"date": "2025-09-03", "category": "train", "amount": "129,90", "text": "Bahn"}]})
check(r.status_code == 201, "a trip " + r.text[:160])
C1 = A.post(B + f"{O}/contracts", json={"name": "Rahmenvertrag Beispiel", "client_id": CL}).json()["id"]
CPDF = b"%PDF-1.4\n% vertrag beispiel " + os.urandom(8).hex().encode() + b"\n%%EOF\n"
r = A.post(B + f"{O}/contracts/{C1}/files", files={"file": ("Vertrag.pdf", CPDF, "application/pdf")}, data={"date": "2026-03-01"})
check(r.status_code == 201, "a contract file " + r.text[:160])
SRC_CLOSINGS = len(A.get(B + f"{O}/cashbooks/{BK}/entries?year=2026").json().get("closings") or [])
SRC_BEFORE = office_counts(ORG)
SRC_CLIENTS = dbx("SELECT COUNT(*) AS n FROM clients WHERE org_id=?", (ORG,))[0]["n"]
OX, RK = export(A, ORG)

# ---------------------------------------------------------------- import into the empty organisation of another admin
iid, pv = opened(Ca, OX, RK)
taken = " ".join(x.get("what", "") for x in pv.get("taken_areas") or [])
check("Office" in taken and "Clients" in taken, f"the preview names office and clients as taken over {taken}")
j = run(Ca, iid, ORG2)
check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')} {warnings(j)}")
IMP = (j.get("result") or {}).get("import_id")
cl = [x for x in Ca.get(B + "/api/clients").json().get("clients", []) if x.get("name") == "Kunde Beispiel"]
check(len(cl) == 1 and cl[0].get("org_id") == ORG2, f"the client is in the target organisation {cl}")
CL2 = cl[0]["id"] if cl else 0
check(dbx("SELECT COUNT(*) AS n FROM office_client_contacts WHERE client_id=? AND name='Petra Beispiel'", (CL2,))[0]["n"] == 1, "its contact person")
inv = [x for x in Ca.get(B + D + "?kind=invoice").json().get("docs", []) if x.get("number") == INV_NO]
check(len(inv) == 1, f"the finalised invoice keeps its number {INV_NO}")
INV2 = inv[0]["id"] if inv else 0
d = Ca.get(B + f"{D}/{INV2}").json()
check(d.get("locked") and d.get("client_id") == CL2, f"still finalised, its client mapped {d.get('locked')} {d.get('client_id')}")
pays = Ca.get(B + f"{D}/{INV2}/payments").json().get("payments", [])
check(len(pays) == 1 and abs(float(pays[0].get("amount")) - 100) < 0.01, f"the payment came along {pays}")
check(Ca.get(B + f"{D}/{INV2}/pdf").content == INV_PDF, "the stored PDF of the finalised invoice is the same file")
offs = [x for x in Ca.get(B + D + "?kind=offer").json().get("docs", []) if x.get("project_title") == "Imagefilm"]
check(len(offs) == 1, "the quotation came along")
od = Ca.get(B + f"{D}/{offs[0]['id'] if offs else 0}").json()
sv2 = [x for x in Ca.get(B + f"{O}/services").json().get("items", []) if x.get("name_de") == "Schnitt"]
its = od.get("items") or []
check(len(its) == 2 and sv2 and any(i.get("service_id") == sv2[0]["id"] for i in its), f"positions with the mapped service {its}")
ser = Ca.get(B + f"{O}/series").json().get("items", [])
tpl2 = dbx("SELECT id FROM office_docs WHERE org_id=? AND project_title='Betreuung {month}'", (ORG2,))
check(len(ser) == 1 and tpl2 and ser[0].get("template_id", (ser[0].get("template") or {}).get("id")) == tpl2[0]["id"],
      f"the series points at its imported template {ser}")
bk2 = Ca.get(B + f"{O}/cashbooks").json().get("books", [])
ent = Ca.get(B + f"{O}/cashbooks/{bk2[0]['id'] if bk2 else 0}/entries?year=2026").json()
check(len(ent.get("entries") or []) == 1 and len(ent.get("closings") or []) == SRC_CLOSINGS >= 1, f"cash book entry + closing {ent.get('entries')} {ent.get('closings')}")
r = Ca.post(B + f"{O}/cashbooks/{bk2[0]['id'] if bk2 else 0}/entries", json={"day": "2026-03-01", "dir": "in", "amount": "5", "text": "Nachtrag"})
check(r.status_code == 409, f"the closed day stays closed {r.status_code}")
trips = Ca.get(B + f"{O}/trips?year=2025").json().get("trips", [])
check(len(trips) == 1 and trips[0].get("client_id") == CL2 and len(trips[0].get("items") or []) == 1, f"the trip with its receipt {trips}")
ct2 = dbx("SELECT id, client_id FROM office_contracts WHERE org_id=? AND name='Rahmenvertrag Beispiel'", (ORG2,))
check(ct2 and ct2[0]["client_id"] == CL2, "the framework contract, its client mapped")
cf = Ca.get(B + f"{O}/contracts/{ct2[0]['id'] if ct2 else 0}/files").json().get("items", [])
check(len(cf) == 1 and Ca.get(B + f"{O}/contracts/{ct2[0]['id']}/files/{cf[0]['id']}").content == CPDF, "the contract file reads the same")
fn = dbx("SELECT file FROM office_contract_files WHERE org_id=?", (ORG2,))
p = os.path.join(DATA, "office", str(ORG2), fn[0]["file"]) if fn else ""
if p and os.path.isfile(p):
    with open(p, "rb") as fh:
        raw = fh.read()
    check(not raw.startswith(b"%PDF-") and b"vertrag" not in raw, "the contract file is sealed at rest")
else:
    check(False, f"the contract file is on disk {p}")
check(Ca.get(B + f"{O}/logo").content == LOGO_SRC, "the logo came along")
st = Ca.get(B + f"{O}/settings").json()
check((st.get("company_fields") or {}).get("name") == "Alpha Studio GmbH" and (st.get("company_fields") or {}).get("iban"), "company data incl. bank")
enc = dbx("SELECT iban FROM office_company WHERE org_id=?", (ORG2,))
check(enc and str(enc[0]["iban"]).startswith("kenc1:"), "the bank data is encrypted with the target's key")
n1 = dbx("SELECT kind, period, last FROM office_numbers WHERE org_id=? ORDER BY kind, period", (ORG,))
n2 = dbx("SELECT kind, period, last FROM office_numbers WHERE org_id=? ORDER BY kind, period", (ORG2,))
check([dict(x) for x in n1] == [dict(x) for x in n2] and n1, f"the number ranges came along {n2}")
OT = [r["table_name"] for r in dbx("""SELECT table_name FROM information_schema.columns WHERE table_schema=current_schema()
                                      AND column_name='org_id' AND table_name LIKE 'office_%' ORDER BY table_name""")]
diff = {}
for t in OT:
    if t in ("office_doc_log",):  # the export itself writes log entries
        continue
    n1, n2 = (dbx(f"SELECT COUNT(*) AS n FROM {t} WHERE org_id=?", (o,))[0]["n"] for o in (ORG, ORG2))
    if n1 != n2:
        diff[t] = (n1, n2)
check(not diff, f"every office table has as many rows as in the source {diff}")
check(office_counts(ORG) == SRC_BEFORE and dbx("SELECT COUNT(*) AS n FROM clients WHERE org_id=?", (ORG,))[0]["n"] == SRC_CLIENTS,
      "the source organisation is unchanged")
check(Do.get(B + f"{D}/{INV2}").status_code in (403, 404), "an admin of a third organisation cannot read the imported invoice")
r = Ca.post(B + f"/api/imports/{IMP}/undo")
check(r.ok, f"undo {r.status_code} {r.text[:160]}")
left = {k: v for k, v in office_counts(ORG2).items() if v}
check(not left and not dbx("SELECT 1 FROM clients WHERE org_id=?", (ORG2,)), f"the undo removed the office {left}")
check(not p or not os.path.exists(p), "the undo removed the files")
Ca.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- again into the source: numbers it has are skipped
iid, pv = opened(A, OX, RK)
j = run(A, iid, ORG)
check(j.get("state") == "done", f"import into the source done {j.get('error')}")
w = warnings(j)
check("number already exists" in w, f"the duplicate numbers are named {w}")
check(dbx("SELECT COUNT(*) AS n FROM office_docs WHERE org_id=? AND number=?", (ORG, INV_NO))[0]["n"] == 1, "never two invoices with one number")
check(A.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo").ok, "undo")
check(office_counts(ORG) == SRC_BEFORE, f"the source is as before {office_counts(ORG)} {SRC_BEFORE}")
A.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- a person without organisation: into the personal office
FID, Fr = freelancer(B, A)
# 2.137.1 (#2399): an import that fails (here: recording it is refused by a test trigger) leaves no empty personal office behind
check(not dbx("SELECT 1 FROM orgs WHERE personal_of=?", (FID,)), "freelancer: no personal office before")
dbx(f"CREATE OR REPLACE FUNCTION p2137_fail() RETURNS trigger AS $$ BEGIN IF NEW.user_id = {int(FID)} THEN "
    "RAISE EXCEPTION 'p2137 test'; END IF; RETURN NEW; END $$ LANGUAGE plpgsql")
dbx("CREATE TRIGGER p2137_fail BEFORE INSERT ON imports FOR EACH ROW EXECUTE FUNCTION p2137_fail()")
iid, pv = opened(Fr, OX, RK)
j = run(Fr, iid, "private")
dbx("DROP TRIGGER IF EXISTS p2137_fail ON imports")
dbx("DROP FUNCTION IF EXISTS p2137_fail()")
check(j.get("state") == "failed", f"2.137.1 (#2399): the import failed {j.get('state')}")
check(not dbx("SELECT 1 FROM orgs WHERE personal_of=?", (FID,)), "2.137.1 (#2399): the empty personal office made for it is gone again")
check(not dbx("SELECT 1 FROM office_docs d JOIN orgs o ON o.id=d.org_id WHERE o.personal_of=?", (FID,)), "and nothing of the office stayed")
Fr.delete(B + f"/api/account/import/{iid}")
iid, pv = opened(Fr, OX, RK)
j = run(Fr, iid, "private")
check(j.get("state") == "done", f"freelancer import done {j.get('error')} {warnings(j)}")
PB = dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))
PB = PB[0]["id"] if PB else 0
check(PB and dbx("SELECT COUNT(*) AS n FROM office_docs WHERE org_id=? AND number=?", (PB, INV_NO))[0]["n"] == 1, "the invoice is in the personal office")
fc = dbx("SELECT org_id, created_by FROM clients WHERE name='Kunde Beispiel' AND created_by=?", (FID,))
check(len(fc) == 1 and fc[0]["org_id"] is None, f"the client is a private client of the person {[dict(x) for x in fc]}")
finv = [x for x in Fr.get(B + D + "?kind=invoice").json().get("docs", []) if x.get("number") == INV_NO]
check(len(finv) == 1 and Fr.get(B + f"{D}/{finv[0]['id']}/pdf").content == INV_PDF, "the person reads the invoice and its PDF")
check(Fr.get(B + f"{O}/logo").content == LOGO_SRC, "the logo of the personal office")
check(any(x.get("name") == "Kunde Beispiel" for x in Fr.get(B + "/api/clients").json().get("clients", [])), "the person sees the client")
check(not dbx("SELECT 1 FROM org_members WHERE user_id=?", (FID,)), "still in no organisation")
Fr.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- the personal office exported by its owner
check(A.post(B + f"/api/orgs/{PB}/export").status_code == 404, "somebody else cannot export a personal office (404)")
check(A.post(B + f"/api/orgs/{PB}/encryption/recovery", json={"password": "password123"}).status_code == 404, "nor see its recovery key")
check(Fr.get(B + f"/api/orgs/{ORG}/export").status_code == 404, "the person cannot export a foreign organisation")
tk = Fr.post(B + "/api/me/tokens", json={"name": "Probe", "scopes": ["read", "write"]}).json().get("token", "")
TKH = {"Authorization": "Bearer " + tk, "X-Requested-With": "kalmido"}
check(tk and requests.post(B + f"/api/v1/orgs/{PB}/export", headers=TKH).status_code in (403, 404), "an API token of the owner cannot export it")
check(requests.post(B + f"/api/v1/orgs/{PB}/encryption/recovery", headers=TKH, json={"password": "password123"}).status_code in (403, 404),
      "nor read its recovery key")
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "probe", "display_name": "Probe"}).json()
AGH = {"Authorization": "Bearer " + ag.get("token", ""), "X-Requested-With": "kalmido"}
check(requests.post(B + f"/api/v1/orgs/{PB}/export", headers=AGH).status_code in (403, 404), "an agent cannot export a personal office")
Fr.post(B + "/api/lists", json={"name": "Frida Privatliste"})
# 2.137.0 (#2344, with 2.138.0 #1972): the own personal office is organisation 0; its hidden id is never used from outside
check(Fr.get(B + f"/api/orgs/{PB}/export").status_code == 404, "the owner: the hidden id itself 404 (0 = mine)")
check(requests.post(B + "/api/v1/orgs/0/export", headers=TKH).status_code in (403, 404), "an API token of the owner cannot export it (0)")
check(requests.post(B + "/api/v1/orgs/0/export", headers=AGH).status_code in (403, 404), "an agent cannot export it (0)")
PX, PRK = export(Fr, 0)
iid, pv = opened(Do, PX, PRK)
j = run(Do, iid, ORG3)
check(j.get("state") == "done", f"personal office into an organisation {j.get('error')} {warnings(j)}")
check(dbx("SELECT COUNT(*) AS n FROM office_docs WHERE org_id=? AND number=?", (ORG3, INV_NO))[0]["n"] == 1, "its invoice came along")
check(dbx("SELECT COUNT(*) AS n FROM clients WHERE org_id=? AND name='Kunde Beispiel'", (ORG3,))[0]["n"] == 1, "its private client came along")
check(not dbx("SELECT 1 FROM lists WHERE name='Frida Privatliste' AND owner_id!=?", (FID,)), "no private list came along")
check(Do.get(B + f"{O}/logo").content == LOGO_SRC, "the logo came along")

if FAILS:  # the container log once (was in the suite's own check(), 2.206.0 #2762)
    logs()
print(f"p2137_a: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
