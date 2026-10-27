#!/usr/bin/env python3
# kalmido-suite:
"""2.357.0 (#3221, GoBD): the one-time catch-up of the stored files of finalised office documents (kalmido/office/
storefill.py osf_tick, called in the container with force=True as the watchdog does), own container (start.sh). A person
without an organisation (freelancer-matrix: office); invented data and the test IBAN only.
 - an invoice finalised "before the files were stored" (stored files removed, hashes empty): the run renders it once and
   stores PDF + XML with both hashes (log "store"); the download is then the stored file (hash of the bytes = noted hash)
 - a second invoice with its stored file but no noted hash: the run notes the hash of that file (log "store_hash"),
   the file stays byte for byte
 - review M2: a document that cannot be stored (an XRechnung without buyer reference) is skipped with its reason
   (office log "store_skip", the setting's "skipped"), the others go on
 - a draft and a finalised quotation (never stored at finalising) stay as they are; a second run finds nothing and notes "done"; after "done" nothing runs again
The container runs with KALMIDO_OFFICE_STORE_FILL=off (its watchdog ticks every second), the test's own run switches it on.
usage: p2357_l_storefill_test.py <datadir>      (P2357L_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import hashlib
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
import dbx as _dbx  # noqa: E402
from kt import FAILS, OKS, check, dbx, fresh, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
TEST_IBAN = "DE02120300000000202051"

fresh({"KALMIDO_OFFICE_STORE_FILL": "off"}, prefix="P2357L", data=DATA)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en"})
FID, Fr = freelancer(B, A)
r = Fr.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht"}, "lang": "de", "currency": "EUR", "payment_days": 14,
                                      "company_fields": {"name": "Studio Nordlicht", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                         "country": "DE", "email": "hallo@nordlicht.example", "phone": "+49 40 000000",
                                                         "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN, "bic": "BYLADEM1001",
                                                         "bank_name": "Beispielbank"}})
check(r.ok, "freelancer office settings " + r.text[:200])
r = Fr.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"})
assert r.status_code == 201, r.text
CL = r.json()["id"]


def sh(cmd):
    return subprocess.run(["docker", "exec", CT, "sh", "-c", cmd], capture_output=True, timeout=60)


def doc(kind, title):
    r = Fr.post(B + D, json={"kind": kind, "client_id": CL, "project_title": title, "service_from": "2026-10-01", "service_to": "2026-10-20",
                             "items": [{"kind": "service", "title": "Regie", "qty": 1, "unit": "day", "rate": 1000}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def row(did):
    return dbx("SELECT org_id, locked_at, COALESCE(pdf_sha256, '') AS p, COALESCE(xml_sha256, '') AS x FROM office_docs WHERE id=?", (did,), DATA)[0]


def tick():
    """One portion of the catch-up, as the watchdog does it (force: no interval wait). -> documents looked at."""
    code = ("import app\nfrom kalmido.office.storefill import osf_tick\nc = app.connect()\n"
            "try:\n    print(osf_tick(c, force=True))\nfinally:\n    c.close()")
    out = subprocess.run(["docker", "exec", "-e", "KALMIDO_OFFICE_STORE_FILL=on", CT, "python", "-c", code], capture_output=True, text=True)
    check(out.returncode == 0, f"the run works {out.stdout[-200:]} {out.stderr[-600:]}")
    try:
        return int(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return -1


# ---------------------------------------------------------------- documents "from before"
INV = doc("invoice", "Imagefilm")
r = Fr.post(B + f"{D}/{INV}/finalize")
check(r.ok and r.json().get("locked"), "invoice finalised " + r.text[:200])
OFF = doc("invoice", "Relaunch")
r = Fr.post(B + f"{D}/{OFF}/finalize")
check(r.ok and r.json().get("locked"), "second invoice finalised " + r.text[:200])
QU = doc("offer", "Angebot")
r = Fr.post(B + f"{D}/{QU}/finalize")
check(r.ok and r.json().get("locked"), "quotation finalised " + r.text[:200])
BAD = doc("invoice", "Ohne Käuferreferenz")
r = Fr.post(B + f"{D}/{BAD}/finalize")
check(r.ok and r.json().get("locked"), "third invoice finalised " + r.text[:200])
DRAFT = doc("invoice", "Entwurf")
oid = row(INV)["org_id"]
check(row(INV)["p"] and row(INV)["x"] and row(OFF)["p"], f"finalising stored the files with their hashes (as before) {dict(row(INV))} {dict(row(OFF))}")
off_file = sh(f"ls /data/office/{oid}/doc{OFF}-*.pdf").stdout.decode().strip()
off_before = sh(f"sha256sum {off_file}").stdout.split()[:1]
# the first invoice: as before the files were stored (no files, no hashes); the second: a file but no hash noted
DB = _dbx.connect(DATA)
sh(f"rm -f /data/office/{oid}/doc{INV}-*.pdf /data/office/{oid}/doc{INV}-*.xml")
DB.execute("UPDATE office_docs SET pdf_sha256='', xml_sha256='' WHERE id IN (?, ?, ?)", (INV, OFF, BAD))
sh(f"rm -f /data/office/{oid}/doc{BAD}-*.pdf /data/office/{oid}/doc{BAD}-*.xml")
DB.execute("UPDATE office_docs SET einvoice_format='xrechnung' WHERE id=?", (BAD,))  # its new rendering fails: no buyer reference
DB.execute("DELETE FROM settings WHERE key='office_store_fill'")  # the watchdog of the fresh container may have noted "done" already
check(sh(f"ls /data/office/{oid}/doc{INV}-*.pdf").stdout.strip() == b"" and not row(INV)["p"], "the invoice has no stored file and no hash now")

# ---------------------------------------------------------------- the catch-up
n = tick()
check(n == 3, f"the run looked at the three invoices: {n} {dict(row(INV))} {dict(row(OFF))}")
ri, ro = row(INV), row(OFF)
check(len(ri["p"]) == 64 and len(ri["x"]) == 64, f"#3221: the invoice: PDF and XML stored with their hashes {ri}")
check(sh(f"ls /data/office/{oid}/doc{INV}-*.pdf").stdout.strip() != b"" and sh(f"ls /data/office/{oid}/doc{INV}-*.xml").stdout.strip() != b"",
      "#3221: the invoice's files are on disk")
pdf = Fr.get(B + f"{D}/{INV}/pdf")
check(pdf.ok and pdf.content[:5] == b"%PDF-" and hashlib.sha256(pdf.content).hexdigest() == ri["p"], "#3221: the download is the stored file (hash matches)")
xml = Fr.get(B + f"{D}/{INV}/xml")
check(xml.ok and hashlib.sha256(xml.content).hexdigest() == ri["x"], "#3221: the XML is the stored one (hash matches)")
check(len(ro["p"]) == 64 and len(ro["x"]) == 64 and sh(f"sha256sum {off_file}").stdout.split()[:1] == off_before,
      "#3221: the second invoice: hashes noted, its file unchanged")
po = Fr.get(B + f"{D}/{OFF}/pdf")
check(po.ok and hashlib.sha256(po.content).hexdigest() == ro["p"], "#3221: the noted hash is the hash of its stored file")
acts = {(x["doc_id"], x["action"]) for x in dbx("SELECT doc_id, action FROM office_doc_log WHERE org_id=?", (oid,), DATA)}
check((INV, "store") in acts and (OFF, "store_hash") in acts, f"#3221: logged store / store_hash: {sorted(a for a in acts if a[0] in (INV, OFF))}")
check(not row(DRAFT)["locked_at"] and not row(DRAFT)["p"], "a draft stays as it is")
check(row(QU)["locked_at"] and not row(QU)["p"] and sh(f"ls /data/office/{oid}/doc{QU}-*.pdf").stdout.strip() == b"", "a finalised quotation stays unstored")
check(not row(BAD)["p"] and (BAD, "store_skip") in acts, f"M2: the invoice that cannot be stored is skipped and logged: {dict(row(BAD))}")
lg = Fr.get(B + O + "/log?limit=200")
reason = [x.get("detail") or {} for x in (lg.json().get("log") or []) if x.get("doc_id") == BAD and x.get("action") == "store_skip"] if lg.ok else []
check(reason and reason[0].get("catch_up") == 1 and reason[0].get("reason"), f"M2: the skip names its reason in the office log: {reason}")
st_log = [x.get("detail") or {} for x in (lg.json().get("log") or []) if x.get("doc_id") == INV and x.get("action") == "store"] if lg.ok else []
check(any(d.get("catch_up") == 1 for d in st_log), f"N1: the catch-up's store entry is marked catch_up: {st_log}")
check(tick() == 0, "a second run finds nothing")
st = json.loads(dbx("SELECT value FROM settings WHERE key='office_store_fill'", (), DATA)[0][0])
check(st.get("done") == 1 and str(BAD) in (st.get("skipped") or {}), f"the catch-up is noted as done, the skipped document with it: {st}")
DB.execute("UPDATE office_docs SET pdf_sha256='' WHERE id=?", (OFF,))
check(tick() == 0 and not row(OFF)["p"], "after done nothing runs again")

print(f"p2357_l_storefill: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
