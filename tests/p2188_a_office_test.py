#!/usr/bin/env python3
"""2.188.0 API tests, part A (#2498, office follow-ups of 2.148): auditor ZIP with the DTD, kept receipt GUIDs, a move
without doubles, the lock check of a folder in one query. Own container (start.sh) with KALMIDO_SECRET_KEY (the
organisation export needs it). Invented companies, people and figures only; dated data in the finished month before (M).
 - the auditor's export: gdpdu-01-03-2019.dtd next to index.xml (the official text, checked by its SHA-256), the DOCTYPE
   of index.xml names it; also in the personal office of a person without organisation
 - DATEV ZIP: ?check=1 stores nothing; the first export stores the GUIDs (the start value = the uuid5 formula of 2.148, so
   an update links as before), a second export links the same
 - organisation export -> import into an empty organisation: the stored GUIDs come along (the invoice and the receipt
   file of the target link as in the source), the opening balances and the procedure documentation once; a second import
   of the same export adds neither again (a differing balance keeps the target's, with a warning)
 - a person without organisation (personal office, its own admin) exports DATEV, then moves the personal office into an
   organisation: the invoice keeps its GUID there; an opening balance the organisation has already is not added twice, a
   differing one stays in the personal office, the organisation's own procedure documentation stays the only one (the
   preview names all three)
 - lock check of a tree: a folder with many receipts, one of them (in a sub folder) in the locked month -> 409 with the
   month, nothing in the trash; a folder with only open receipts goes into the trash
usage: p2188_a_office_test.py <datadir>      (P2188A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)
freelancer-matrix: office  tenant-matrix: office"""
import base64
import csv
import hashlib
import io
import os
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess, su_get  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,time,docs,files,travel"
O = "/api/office"
D = O + "/docs"
Z = O + "/datev/zip"
XN = "{http://xml.datev.de/bedi/tps/document/v05.0}"
KEY = base64.b64encode(os.urandom(32)).decode()
DTD = "gdpdu-01-03-2019.dtd"
DTD_SHA = "4439a9ecdd019e82a1ac0b2ccfb64021e3b5a465e9be4cfebc31bb4d3771d7dd"
DZ_NS = uuid.UUID("6f0a4c2e-1d8b-4f7e-9a3c-5b2d8e7f1a90")  # office/datevzip.py DZ_NS


def sql(q, args=()):
    c = dbxm.connect(DATA)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def receipt(s, ws, name, amount, day, category="Software", vat="19"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day})
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": category, "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def link(x):
    v = (x or {}).get("Beleglink") or ""
    return v[6:-1] if v.startswith('BEDI "') and v.endswith('"') else ""


def datev_zip(s, q):
    """-> (lines as dicts, {guid: file name})."""
    r = s.get(B + Z + q)
    assert r.ok, r.text
    outer = zipfile.ZipFile(io.BytesIO(r.content))
    ex = [n for n in outer.namelist() if n.startswith("EXTF_")]
    be = [n for n in outer.namelist() if n.startswith("Belege_")]
    lines = outer.read(ex[0]).decode("cp1252").split("\r\n") if ex else []
    cols = next(csv.reader([lines[1]], delimiter=";")) if len(lines) > 1 else []
    data = [dict(zip(cols, x)) for x in csv.reader(lines[2:-1], delimiter=";")]
    files = {}
    if be:
        inner = zipfile.ZipFile(io.BytesIO(outer.read(be[0])))
        for d in ET.fromstring(inner.read("document.xml")).iter(XN + "document"):
            ext = d.find(XN + "extension")
            files[d.get("guid")] = ext.get("name") if ext is not None else ""
    return data, files


def formula(oid, kind, ident):
    return str(uuid.uuid5(DZ_NS, f"{int(oid)}/{kind}/{int(ident)}")).upper()


def ws(s, v):
    r = s.patch(B + "/api/settings", json={"workspace": v})
    assert r.ok, r.text


def company(s, name):
    r = s.put(B + O + "/settings", json={"company": {"name": name}, "currency": "EUR", "datev_extf": DX,
                                         "company_fields": {"name": name, "street": "Teststraße 1", "zip": "20000", "city": "Hamburg",
                                                            "country": "DE", "tax_number": "12/345/67890", "vat_id": "DE999999999",
                                                            "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
    assert r.ok, r.text


def finalized(s, client, title):
    r = s.post(B + D, json={"kind": "invoice", "client_id": client, "service_from": day(1), "service_to": day(3),
                            "items": [{"title": title, "qty": 1, "rate": 500}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    sql("UPDATE office_docs SET date=? WHERE id=?", (day(5), did))
    return did, r.json()["number"]


def balances(oid):
    return sorted((int(r[0]), r[1], f"{float(r[2]):.2f}", r[3]) for r in
                  sql("SELECT year, account, amount, side FROM office_opening_balances WHERE org_id=?", (oid,)))


def add_balance(oid, account, amount):
    sql("INSERT INTO office_opening_balances(org_id, year, account, label, amount, side, created_at) VALUES(?,?,?,?,?,?,?)",
        (oid, Y, account, "Eröffnung " + account, amount, "S", TD + "T08:00:00Z"))


def n_procdocs(oid):
    return sql("SELECT COUNT(*) FROM office_procdocs WHERE org_id=?", (oid,))[0][0]


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


def org_import(s, data, rk, target):
    iid = upload(s, data)
    j = wait(s, iid)
    if j.get("state") == "key":
        s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk})
        j = wait(s, iid)
    check(j.get("state") == "preview", f"import opened {j.get('state')} {j.get('error')}")
    # 2.269.0 (#3046): "again" = the person saw the preview's warning (a second import of one export is 409 without it)
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": {}})
    check(r.status_code == 202, f"import runs {r.status_code} {r.text[:200]}")
    j = wait(s, iid)
    check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')}")
    s.delete(B + f"/api/account/import/{iid}")
    return " | ".join(x.get("text", "") for x in (j.get("result") or {}).get("warnings", []))


def org_export(s, oid):
    r = s.post(B + f"/api/orgs/{oid}/export")
    check(r.status_code == 202, f"export started {r.status_code} {r.text[:160]}")
    for _ in range(480):
        if s.get(B + f"/api/orgs/{oid}/export").json().get("state") != "running":
            break
        time.sleep(0.25)
    data = su_get(s, B + f"/api/orgs/{oid}/export/file").content  # 2.360.0 (#2496): the step-up
    rk = s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
    check(data[:13] == b"KALMIDO-ORGX\n" and rk, f"organisation export + recovery key of {oid}")
    return data, rk


if not os.environ.get("P2188A_NOSTART"):
    env = dict(os.environ, EXTRA=f"-e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Ziel", "password": "password123", "email": "carol@example.com"})
assert r.ok, r.text
CAROL = r.json()["id"]
Ca = sess("carol")
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{o}"})
EID, Er = freelancer(B, A, "erin", features=FEAT)  # freelancer-matrix: office (moves the personal office)
FID, Fr = freelancer(B, A, "fred", features=FEAT)  # freelancer-matrix: office (auditor ZIP, locks)

TODAY = testclock.today()
TD = TODAY.isoformat()
M0 = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)
M = M0.isoformat()[:7]
ML = f"{M[5:7]}/{M[:4]}"
Y = int(M[:4])
ME = (TODAY.replace(day=1) - timedelta(days=1)).isoformat()
QM = f"?from={M}-01&to={ME}"
DX = {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}


def day(n):
    return f"{M}-{n:02d}"


company(A, "Studio Beispiel GmbH")
C1 = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]
I1, N1 = finalized(A, C1, "Schnitt")
R1 = receipt(A, f"org:{ORG}", "software.pdf", "119.00", day(8))

# ---------------------------------------------------------------- 1. the auditor's ZIP carries the DTD
GX = O + "/gobd/export"
r = A.get(B + GX + QM)
check(r.ok, f"auditor export {r.status_code} {r.text[:160]}")
z = zipfile.ZipFile(io.BytesIO(r.content))
check(DTD in z.namelist() and "index.xml" in z.namelist(), f"the DTD lies next to index.xml {z.namelist()}")
check(hashlib.sha256(z.read(DTD)).hexdigest() == DTD_SHA, "the DTD is the official text, unchanged")
check(f'<!DOCTYPE DataSet SYSTEM "{DTD}">'.encode() in z.read("index.xml") and b"2004.dtd" not in z.read("index.xml"),
      "index.xml names the DTD in the ZIP")
company(Fr, "Fred Beispiel")
r = Fr.get(B + GX + QM)
fz = zipfile.ZipFile(io.BytesIO(r.content)) if r.ok else None
check(fz is not None and hashlib.sha256(fz.read(DTD)).hexdigest() == DTD_SHA, f"freelancer: the DTD in the own auditor ZIP {r.status_code}")

# ---------------------------------------------------------------- 2. the GUIDs are stored on the first export
r = A.get(B + Z + QM + "&check=1")
check(r.ok and not sql("SELECT 1 FROM office_datev_guids WHERE org_id=?", (ORG,)), "the check stores no GUID")
data, files = datev_zip(A, QM)
by = {x["Belegfeld 1"]: x for x in data if not x.get("Buchungstext", "").startswith("Zahlung")}
GI, GR = link(by.get(N1)), link(by.get(f"B{R1}"))
check(GI == formula(ORG, "doc", I1) and GR == formula(ORG, "receipt", R1), f"the first export links as 2.148 did {GI} {GR}")
st = {(x[0], x[1]): x[2] for x in sql("SELECT doc_id, node_id, guid FROM office_datev_guids WHERE org_id=?", (ORG,))}
check(st == {(I1, None): GI, (None, R1): GR}, f"both GUIDs stored {st}")
data2, files2 = datev_zip(A, QM)
check({link(x) for x in data2 if link(x)} == {GI, GR} and set(files2) == {GI, GR}, "a second export links the same")

# ---------------------------------------------------------------- 3. opening balances + procedure documentation of Alpha
add_balance(ORG, "1200", "100.00")
add_balance(ORG, "1400", "50.00")
r = A.put(B + O + "/procdoc", json={"own": {}})
check(r.ok and n_procdocs(ORG) == 1, f"Alpha: one version of the procedure documentation {r.status_code} {r.text[:160]}")

# ---------------------------------------------------------------- organisation export -> import into Beta, twice
OX, RK = org_export(A, ORG)
w1 = org_import(Ca, OX, RK, ORG2)
g2 = {x[0] for x in sql("SELECT guid FROM office_datev_guids WHERE org_id=?", (ORG2,))}
check(g2 == {GI, GR}, f"Beta: the GUIDs came along {g2} {w1}")
nd = sql("SELECT node_id FROM office_datev_guids WHERE org_id=? AND node_id IS NOT NULL", (ORG2,))
check(len(nd) == 1 and nd[0][0] != R1 and sql("SELECT 1 FROM fs_nodes WHERE id=? AND org_id=?", (nd[0][0], ORG2)),
      "Beta: the GUID of the receipt names Beta's copy of the file")
company(Ca, "Beta Ziel GmbH")
cdata, cfiles = datev_zip(Ca, QM)
check({link(x) for x in cdata if link(x)} == {GI, GR}, f"Beta: the invoice and the receipt link as in Alpha {[link(x) for x in cdata]}")
check(balances(ORG2) == balances(ORG) and n_procdocs(ORG2) == 1, f"Beta: balances + documentation once {balances(ORG2)}")
sql("UPDATE office_opening_balances SET amount=70 WHERE org_id=? AND account='1400'", (ORG2,))
w2 = org_import(Ca, OX, RK, ORG2)
check(balances(ORG2) == [(Y, "1200", "100.00", "S"), (Y, "1400", "70.00", "S")], f"second import: no balance twice, Beta's kept {balances(ORG2)}")
check("opening balance differs" in w2 and f"{Y} 1400" in w2, f"second import: the differing balance is named {w2}")
check(n_procdocs(ORG2) == 1 and "procedure documentation" not in w2, f"second import: the same documentation not again {n_procdocs(ORG2)} {w2}")
check({x[0] for x in sql("SELECT guid FROM office_datev_guids WHERE org_id=? AND doc_id IS NOT NULL", (ORG2,))} == {GI},
      "second import: the invoice (number taken) adds no GUID")

# ---------------------------------------------------------------- the personal office of a person without organisation moves
ws(Er, "private")
company(Er, "Erin Beispiel")
CE = Er.post(B + "/api/clients", json={"name": "Privatkunde Beispiel", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"}).json()["id"]
IE, NE = finalized(Er, CE, "Ton")
PB = sql("SELECT id FROM orgs WHERE personal_of=?", (EID,))[0][0]
edata, _ef = datev_zip(Er, QM)
GE = link(next((x for x in edata if x["Belegfeld 1"] == NE), None))
check(GE == formula(PB, "doc", IE), f"freelancer: the first export links as before {GE}")
check([x[0] for x in sql("SELECT guid FROM office_datev_guids WHERE org_id=? AND doc_id=?", (PB, IE))] == [GE],
      "freelancer: the GUID is stored in the personal office")
add_balance(PB, "1200", "100.00")
add_balance(PB, "1400", "50.00")
check(Er.put(B + O + "/procdoc", json={"own": {}}).ok and n_procdocs(PB) == 1, "freelancer: own procedure documentation")
GAM = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": EID}).json()["id"]
ws(Er, f"org:{GAM}")
company(Er, "Gamma Beispiel GmbH")
check(Er.put(B + O + "/procdoc", json={"own": {}}).ok and n_procdocs(GAM) == 1, "Gamma: its own procedure documentation")
add_balance(GAM, "1200", "100.00")
add_balance(GAM, "1400", "70.00")
ws(Er, "private")
r = Er.get(B + O + f"/move/check?org={GAM}")
notes = " | ".join(r.json().get("notes") or []) if r.ok else r.text
check(r.ok and "in the organisation already" in notes and "differs from the organisation" in notes
      and "own procedure documentation" in notes, f"the preview names what stays {notes}")
r = Er.post(B + O + "/move/org", json={"org": GAM, "confirm": True})
check(r.ok, f"the move {r.status_code} {r.text[:200]}")
check(balances(GAM) == [(Y, "1200", "100.00", "S"), (Y, "1400", "70.00", "S")], f"Gamma: no balance twice, its own kept {balances(GAM)}")
check(balances(PB) == [(Y, "1200", "100.00", "S"), (Y, "1400", "50.00", "S")],
      f"what the organisation has already (same or differing) stays in the personal office {balances(PB)}")
check(n_procdocs(GAM) == 1 and n_procdocs(PB) == 1, f"Gamma keeps its own documentation only {n_procdocs(GAM)} {n_procdocs(PB)}")
check([tuple(x) for x in sql("SELECT org_id, guid FROM office_datev_guids WHERE doc_id=?", (IE,))] == [(GAM, GE)],
      "the stored GUID moved along")
gdata, _gf = datev_zip(Er, QM)
check(link(next((x for x in gdata if x["Belegfeld 1"] == NE), None)) == GE, "after the move the invoice links the same GUID")
check(GE != formula(GAM, "doc", IE), "(without the stored GUID the link would have changed)")

# ---------------------------------------------------------------- 4. the lock check of a folder tree in one query
ws(Fr, "private")


def folder(name, parent=None):
    r = Fr.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": "private"})})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


F1 = folder("Belege Monat")
F1S = folder("Unterordner", F1)
F2 = folder("Belege offen")
many = [receipt(Fr, "private", f"heute-{i}.pdf", "10.00", TD) for i in range(24)]
old = receipt(Fr, "private", "alt.pdf", "20.00", day(8))
open2 = [receipt(Fr, "private", f"offen-{i}.pdf", "5.00", TD) for i in range(3)]
q = ",".join("?" * len(many))
sql(f"UPDATE fs_nodes SET parent_id=? WHERE id IN ({q})", (F1, *many))
sql("UPDATE fs_nodes SET parent_id=? WHERE id=?", (F1S, old))
sql(f"UPDATE fs_nodes SET parent_id=? WHERE id IN ({','.join('?' * len(open2))})", (F2, *open2))
r = Fr.post(B + O + "/periods/lock", json={"through": M, "confirm": ML})
check(r.ok, f"freelancer: lock {M} {r.status_code} {r.text[:160]}")
r = Fr.delete(B + f"/api/files/nodes/{F1}")
check(r.status_code == 409 and ML in r.text, f"a folder with one receipt of the locked month (in a sub folder): 409 ({r.status_code} {r.text[:160]})")
check(sql("SELECT deleted_at FROM fs_nodes WHERE id=?", (F1,))[0][0] is None, "the folder is not in the trash")
r = Fr.delete(B + f"/api/files/nodes/{F2}")
check(r.ok and sql("SELECT deleted_at FROM fs_nodes WHERE id=?", (F2,))[0][0] is not None,
      f"a folder with open receipts only goes into the trash {r.status_code} {r.text[:160]}")
r = Fr.delete(B + f"/api/files/nodes/{many[0]}")
check(r.ok, f"an open receipt of the folder goes alone {r.status_code}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
