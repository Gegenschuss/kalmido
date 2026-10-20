#!/usr/bin/env python3
"""2.148.0 API tests, part B (#2470, office: the DATEV ZIP with the receipt images, as for DATEV Unternehmen online), own
container (start.sh). Invented companies, people and figures only; the data lie in the finished month before the current one (M).
 - the outer ZIP holds the EXTF batch and Belege_<from>_<to>.zip; the inner one document.xml (DATEV XML interface,
   Document_v05.0) and the files; every GUID of document.xml stands as BEDI "GUID" in the column Beleglink of its batch
   line (invoice: its number, receipt: B<id>); the invoice's file is its PDF, the receipt's file the uploaded bytes
 - the GUIDs are the same in a second export
 - check=1: counts, a receipt without amount (no_booking), a cash payment without receipt and a bank payment without
   match (no_receipt); nothing written
 - locked=1: 400 without a locked month; with the lock the header and every line say Festschreibung 1 and the period
   ends with the last locked month
 - a member 403; another organisation never gets Alpha's receipts; a person without organisation (personal office, its
   own admin) gets its own receipts
usage: p2148_b_api_test.py <datadir>      (P2148B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)
freelancer-matrix: office  tenant-matrix: office"""
import csv
import io
import os
import subprocess
import sys
import re
import time
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
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,time,docs,files,travel"
O = "/api/office"
D = O + "/docs"
Z = O + "/datev/zip"
XN = "{http://xml.datev.de/bedi/tps/document/v05.0}"


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


def receipt(s, ws, name, amount, day, category="", vat=None):
    """A receipt: a document (upload) with amount + date and its assignment (category, VAT rate)."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    meta = {"date": day} if amount is None else {"amount": amount, "date": day}
    r = s.patch(B + f"/api/docs/{nid}", json=meta)
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": category, "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def bank_tx(oid, day, amount, text):
    """A bank line straight in the database (the import is tested elsewhere)."""
    sql("INSERT INTO office_bank_tx(org_id, day, amount, currency, counterpart, purpose, hash, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (oid, day, amount, "EUR", text, text, "t-" + text, TODAY.isoformat() + "T08:00:00Z"))
    return sql("SELECT id FROM office_bank_tx WHERE org_id=? AND hash=?", (oid, "t-" + text))[0][0]


def link(x):
    """The GUID of a batch line's Beleglink BEDI "GUID" ('' without)."""
    v = (x or {}).get("Beleglink") or ""
    return v[6:-1] if v.startswith('BEDI "') and v.endswith('"') else ""


def datev_zip(s, q):
    """-> (outer names, header fields, column names, lines as dicts, {guid: (file name, bytes)}, response)."""
    r = s.get(B + Z + q)
    assert r.ok, r.text
    outer = zipfile.ZipFile(io.BytesIO(r.content))
    names = outer.namelist()
    ex = [n for n in names if n.startswith("EXTF_")]
    be = [n for n in names if n.startswith("Belege_") and n.endswith(".zip")]
    txt = outer.read(ex[0]).decode("cp1252") if ex else ""
    lines = txt.split("\r\n")
    head = lines[0].split(";") if lines else []
    cols = next(csv.reader([lines[1]], delimiter=";")) if len(lines) > 1 else []
    data = [dict(zip(cols, x)) for x in csv.reader(lines[2:-1], delimiter=";")]
    files = {}
    if be:
        inner = zipfile.ZipFile(io.BytesIO(outer.read(be[0])))
        root = ET.fromstring(inner.read("document.xml"))
        for d in root.iter(XN + "document"):
            ext = d.find(XN + "extension")
            nm = ext.get("name") if ext is not None else ""
            files[d.get("guid")] = (nm, inner.read(nm) if nm in inner.namelist() else None)
    return names, head, cols, data, files, r


if not (os.environ.get("P2148B_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
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
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Er = freelancer(B, A, "erin", features=FEAT)  # freelancer-matrix: office (the personal office, its own admin)

TODAY = testclock.today()
TD = TODAY.isoformat()
M0 = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)  # the 1st of the finished month before
M = M0.isoformat()[:7]
ML = f"{M[5:7]}/{M[:4]}"
CUR = TD[:7]


def day(n):
    return f"{M}-{n:02d}"


r = A.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel GmbH"}, "currency": "EUR",
                                     "company_fields": {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg",
                                                        "country": "DE", "tax_number": "12/345/67890", "vat_id": "DE999999999",
                                                        "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
assert r.ok, r.text

ME = (TODAY.replace(day=1) - timedelta(days=1)).isoformat()  # the last day of M
QM = f"?from={M}-01&to={ME}"
DX = {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}
r = A.put(B + O + "/settings", json={"datev_extf": DX})
assert r.ok, r.text

# ---------------------------------------------------------------- data of month M
C1 = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]
r = A.post(B + D, json={"kind": "invoice", "client_id": C1, "items": [{"title": "Schnitt", "qty": 1, "rate": 1000}]})
assert r.status_code == 201, r.text
I1 = r.json()["id"]
r = A.post(B + f"{D}/{I1}/finalize")
assert r.ok, r.text
N1 = r.json()["number"]
sql("UPDATE office_docs SET date=? WHERE id=?", (day(5), I1))
WSO = f"org:{ORG}"
R1 = receipt(A, WSO, "software.pdf", "119.00", day(8), "Software", "19")
R1_BYTES = tiny_pdf("Beleg software.pdf")
R0 = receipt(A, WSO, "ohne-betrag.pdf", None, day(9), "Software", "19")
TXM = bank_tx(ORG, day(12), "-40.00", "Papier Muster")
r = A.post(B + O + "/cashbooks", json={"name": "Hauptkasse", "opening": "500.00", "opening_day": day(1)})
assert r.status_code == 201, r.text
CB = r.json()["id"]
r = A.post(B + f"{O}/cashbooks/{CB}/entries", json={"day": day(15), "dir": "out", "amount": "20.00", "text": "Porto", "vat_pct": "0"})
assert r.status_code == 201, r.text
E1 = r.json()["id"]

# ---------------------------------------------------------------- rights
check(Bo.get(B + Z + QM).status_code == 403 and Bo.get(B + Z + QM + "&check=1").status_code == 403, "a member: no DATEV ZIP (403)")

# ---------------------------------------------------------------- the check
r = A.get(B + Z + QM + "&check=1")
check(r.ok, "check " + r.text[:200])
ch = r.json() if r.ok else {}
check(ch.get("count") == 2 and ch.get("files") == 2 and ch.get("from") == f"{M}-01" and ch.get("to") == ME,
      f"check: two bookings (invoice + receipt), two files {ch}")
check([x["node_id"] for x in ch.get("no_booking", [])] == [R0], f"check: the receipt without amount (no_booking) {ch.get('no_booking')}")
nr = ch.get("no_receipt", [])
check(any(x["kind"] == "bank" and x["id"] == TXM and x["amount"] == "40.00" for x in nr)
      and any(x["kind"] == "cash" and x["id"] == E1 and x["amount"] == "20.00" for x in nr) and len(nr) == 2,
      f"check: the bank payment and the cash payment without receipt (no_receipt) {nr}")
check(not any(x.get("action") == "export" and x.get("target") == "datev" for x in A.get(B + O + "/log?limit=200").json()["log"]),
      "the check writes no export into the log")
check(A.get(B + Z + QM + "&locked=1").status_code == 400 and A.get(B + Z + QM + "&locked=1&check=1").status_code == 400,
      "locked=1 without a locked month: 400")

# ---------------------------------------------------------------- the ZIP
names, head, cols, data, files, r = datev_zip(A, QM)
span = f"{M}01_{ME}".replace("-", "")
check(sorted(names) == sorted([f"EXTF_Buchungsstapel_{span}.csv", f"Belege_{span}.zip"]), f"outer ZIP: the batch and the receipts archive {names}")
check(f'DATEV_{span}.zip' in r.headers.get("Content-Disposition", ""), "file name " + r.headers.get("Content-Disposition", ""))
check("Beleglink" in cols and "Festschreibung" in cols and len(head) > 20 and head[20] == "0", f"header: not locked (Festschreibung 0) {head[:22]}")
by = {x["Belegfeld 1"]: x for x in data if not x.get("Buchungstext", "").startswith("Zahlung")}
GI, GR = link(by.get(N1)), link(by.get(f"B{R1}"))
check(re.fullmatch(r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}", GI or "-") and GI in files, f"the invoice line links its PDF {by.get(N1)}")
check(re.fullmatch(r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}", GR or "-") and GR in files and GR != GI, f"the receipt line links its file {by.get(f'B{R1}')}")
links = {x["Beleglink"] for x in data if x.get("Beleglink")}
check(set(files) == {GI, GR} and all(f'BEDI "{g_}"' in links for g_ in files), f"every GUID of document.xml in the batch {sorted(files)} {links}")
check((files.get(GI, ("", None))[1] or b"").startswith(b"%PDF"), "the invoice's file is a PDF")
check(files.get(GR, ("", None))[1] == R1_BYTES, "the receipt's file = the uploaded bytes")
check(all(nm and "/" not in nm for nm, _ in files.values()), f"file names at the root of the archive {[n for n, _ in files.values()]}")
check(all(x.get("Festschreibung") in ("", "0") for x in data), "lines: not locked")
_, _, _, _, files2, _ = datev_zip(A, QM)
check(set(files2) == set(files), "the GUIDs are stable in a second export")
check(files[GI][0].lower().endswith(".pdf") and files[GR][0].lower().endswith(".pdf"), f"file names keep their extension {[n for n, _ in files.values()]}")
check(any(x.get("action") == "export" and x.get("target") == "datev" for x in A.get(B + O + "/log?limit=200").json()["log"]), "office log: the export")
r0 = A.get(B + Z + QM + "&check=0")
check(r0.ok and r0.headers.get("Content-Type", "").startswith("application/zip"), "check=0 is the download, not the check")
_, _, _, data_in0, files_in0, _ = datev_zip(A, QM + "&in=0")
check(set(files_in0) == {GI} and not any(x["Belegfeld 1"] == f"B{R1}" for x in data_in0), "in=0: only the invoice and its PDF")

# ---------------------------------------------------------------- only locked months
r = A.post(B + O + "/periods/lock", json={"through": M, "confirm": f"{M[5:7]}/{M[:4]}"})
check(r.ok and r.json().get("locked") == [M], "M locked " + r.text[:200])
TD = TODAY.isoformat()
names, head, cols, data, files, r = datev_zip(A, f"?from={M}-01&to={TD}&locked=1")
check(head[20] == "1" and head[14] == f"{M}01".replace("-", "") and head[15] == ME.replace("-", ""),
      f"locked=1: header Festschreibung 1, the period ends with M {head[14:21]}")
check(data and all(x.get("Festschreibung") == "1" for x in data), f"locked=1: every line Festschreibung 1 {[x.get('Festschreibung') for x in data]}")
check(set(files) == {GI, GR}, "locked=1: the same files")
r = A.get(B + Z + f"?from={M}-01&to={TD}&locked=1&check=1")
check(r.ok and r.json().get("to") == ME, "locked=1 check: cut at the end of M " + r.text[:200])
check(A.get(B + Z + f"?from={TD}&to={TD}&locked=1").status_code == 400, "locked=1 for an open period only: 400")

# ---------------------------------------------------------------- another organisation, a person without organisation
check(Ca.put(B + O + "/settings", json={"datev_extf": DX}).ok, "Beta: DATEV numbers")
r = Ca.get(B + Z + QM + "&check=1")
check(r.ok and r.json().get("count") == 0 and r.json().get("files") == 0 and not r.json().get("no_booking") and not r.json().get("no_receipt"),
      "another organisation: nothing of Alpha's in its check " + r.text[:200])
_, _, _, cdata, cfiles, _ = datev_zip(Ca, QM)
check(not cfiles and not cdata, "another organisation: no line, no file of Alpha's")
check(Er.put(B + O + "/settings", json={"datev_extf": DX}).ok, "freelancer: DATEV numbers")
ER = receipt(Er, "private", "objektiv.pdf", "238.00", day(7), "Equipment", "19")
_, _, _, edata, efiles, _ = datev_zip(Er, QM)
GE = link(next((x for x in edata if x["Belegfeld 1"] == f"B{ER}"), None))
check(set(efiles) == {GE} and efiles[GE][1] == tiny_pdf("Beleg objektiv.pdf"), f"freelancer: the own receipt with its file {sorted(efiles)}")
check(any(x["Belegfeld 1"] == f"B{ER}" and x["Beleglink"] == f'BEDI "{GE}"' for x in edata), "freelancer: the own line links it")
check(not ({GI, GR} & set(efiles)), "freelancer: nothing of Alpha's")
_, _, _, _, files3, _ = datev_zip(A, QM)
check(GE not in files3, "the freelancer's receipt never in Alpha's ZIP")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
