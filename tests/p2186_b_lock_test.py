#!/usr/bin/env python3
"""2.186.0 API tests, part B (#2600 #2601): the lock of booked receipts and the closing of the logbook, own container
(start.sh). Invented people, firms and figures only (example.com).
tenant-matrix: office
freelancer-matrix: office
 - #2600 a booked receipt never moves into another workspace (dry run names it, the move 409)
 - #2600 removing the VAT rate / the payment day keeps the lock (doc_meta.kept_until); the books count only what is booked now
 - #2600 the lock also covers a receipt of the cash book, of the equipment list and one billed on a finalised invoice
 - #2600 the version clean-up (more than 20 versions) leaves every version of a booked receipt alone
 - #2601 the running month cannot be closed (400), a past one can
 - #2601 a client with drives or travel expenses is archived instead of deleted (single and several at once)
 - #2601 the personal office into an organisation: "every vehicle" becomes each own vehicle, never the organisation's;
   a month the organisation closed already does not stop the move
 - the lock and the running month in the personal office of a person without an organisation (freelancer_fixture)
usage: p2186_b_lock_test.py <datadir>      (P2186B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import subprocess
import sys
import time
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
D, T, V, DR, LB = O + "/docs", O + "/trips", O + "/vehicles", O + "/drives", O + "/logbook"
TODAY = testclock.today()
DAY = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731
PM = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=10).isoformat()  # the 10th of the previous month
PPM = (TODAY.replace(day=1) - timedelta(days=40)).replace(day=10).isoformat()  # the 10th of the month before that
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def in_app(code):
    """Runs python code inside the server container (the app loaded, c = a connection, system context); -> stdout + stderr."""
    body = "\n".join("    " + x for x in code.split("\n"))
    out = subprocess.run(["docker", "exec", CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nc = connect()\n"
                          "with system_ctx(c):\n" + body + "\nc.close()"], capture_output=True, text=True)
    return out.stdout + out.stderr


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


def receipt(s, ws, name, vat=None):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": "119.00", "date": DAY(5)})
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def purge(s, nid):
    assert s.delete(B + f"/api/files/nodes/{nid}").ok
    r = s.delete(B + f"/api/files/nodes/{nid}?purge=1")
    if r.status_code == 409:
        s.post(B + f"/api/files/nodes/{nid}/restore")
    return r


if os.environ.get("P2186B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
A.put(B + O + "/settings", json={"company_fields": {"name": "Beispiel Film GmbH", **COMPANY}})
WSO = f"org:{ORG}"

# ---------------------------------------------------------------- #2600 booked receipts: the move into another workspace
R1 = receipt(A, WSO, "software.pdf", "19")
r = A.post(B + "/api/files/move-space", json={"ids": [R1], "to": "private", "dry": True})
check(r.ok and "booked receipt" in (r.json().get("block") or ""), "#2600: the dry run names the booked receipt " + r.text[:200])
r = A.post(B + "/api/files/move-space", json={"ids": [R1], "to": "private"})
check(r.status_code == 409 and "booked receipt" in r.text and sql("SELECT org_id FROM fs_nodes WHERE id=?", (R1,)) == [(ORG,)],
      "#2600: the move of a booked receipt 409, it stays in the organisation " + r.text[:200])
R_FREE = receipt(A, WSO, "frei.pdf", None)
r = A.post(B + "/api/files/move-space", json={"ids": [R_FREE], "to": "private", "dry": True})
check(r.ok and not r.json().get("block"), "#2600: a receipt without booking can still move " + r.text[:200])

# ---------------------------------------------------------------- #2600 removing the VAT rate / the payment day keeps the lock
r = A.put(B + f"/api/docs/{R1}/receipt", json={"category": "", "vat_pct": None})
check(r.ok and not r.json()["receipt"]["is_receipt"], "#2600: VAT rate and category removed: no receipt in the books any more " + r.text[:200])
ku = sql("SELECT kept_until FROM doc_meta WHERE node_id=?", (R1,))
check(ku and ku[0][0] == f"{int(DAY(5)[:4]) + 8}-12-31", f"#2600: kept_until holds the period {ku}")
r = purge(A, R1)
check(r.status_code == 409 and "Kept by law until" in r.text, "#2600: deleting it for good is still refused " + r.text[:200])
R2 = receipt(A, WSO, "bezahlt.pdf", None)
out = in_app(f"from kalmido.core.config import app as fl\nfrom kalmido.office.books import bk_receipt_set_paid\n"
             f"with fl.test_request_context():\n    bk_receipt_set_paid(c, {ORG}, {R2}, '{DAY(3)}')\n"
             f"    bk_receipt_set_paid(c, {ORG}, {R2}, None)\nc.commit()\nprint('paid done')")
check("paid done" in out, "a payment day set and taken back (like a bank match undone) " + out[-300:])
r = purge(A, R2)
check(r.status_code == 409 and "Kept by law until" in r.text, "#2600: the payment day taken back keeps the lock " + r.text[:200])

# ---------------------------------------------------------------- #2600 cash book, equipment list, billed receipts
ts = testclock.now().isoformat(timespec="seconds")
R_CASH, R_EQ, R_BILL = (receipt(A, WSO, f"{n}.pdf", None) for n in ("kasse", "kamera", "weiter"))
sql("INSERT INTO office_cashbooks(org_id, name, created_at, updated_at) VALUES(?,?,?,?)", (ORG, "Kasse", ts, ts), write=True)
BOOK = sql("SELECT id FROM office_cashbooks WHERE org_id=? ORDER BY id DESC LIMIT 1", (ORG,))[0][0]
sql("INSERT INTO office_cash_entries(org_id, book_id, no, day, dir, amount, node_id, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
    (ORG, BOOK, 1, DAY(4), "out", "11.90", R_CASH, ts, ts), write=True)
r = purge(A, R_CASH)
check(r.status_code == 409 and "Kept by law until" in r.text, "#2600: a receipt of the cash book is kept " + r.text[:200])
sql("INSERT INTO office_equipment(org_id, name, purchase_date, life_months, receipt_node_id, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
    (ORG, "Kamera", "2014-02-01", 36, R_EQ, ts, ts), write=True)
r = purge(A, R_EQ)
check(r.status_code == 409 and f"31 Dec {TODAY.year + 8}" in r.text,
      "#2600: the receipt of an item in use is kept (from this year while it is not archived) " + r.text[:200])
sql("UPDATE office_equipment SET archived=1 WHERE receipt_node_id=?", (R_EQ,), write=True)
# 2.355.0 (#2845): an open receipt not booked yet is kept on its own (from its arrival) -- the document here is no receipt
# any more, so only the equipment item could keep it
sql("DELETE FROM rc_receipts WHERE node_id=?", (R_EQ,), write=True)
check(purge(A, R_EQ).ok, "#2600: an archived item of 2014 (36 months, period over) no longer keeps its receipt")
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Kundenweg 2", "zip": "20095", "city": "Hamburg", "country": "DE"}).json()["id"]
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": DAY(30), "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]})
INV = r.json()["id"]
check(A.post(B + f"{D}/{INV}/finalize").ok, "an invoice finalised")
sql("UPDATE rc_receipts SET billed_doc_id=?, billed_at=? WHERE node_id=?", (INV, DAY(1), R_BILL), write=True)
r = purge(A, R_BILL)
check(r.status_code == 409 and "Kept by law until" in r.text, "#2600: a receipt billed on a finalised invoice is kept " + r.text[:200])

# ---------------------------------------------------------------- #2600 the version clean-up
# 2.239.0 (#2874): an unbooked receipt keeps its versions too now -- the file that loses the oldest is a plain document
r = A.post(B + "/api/docs", data={"ws": WSO}, files={"files": ("versionen.pdf", tiny_pdf("Dokument"), "application/pdf")})
assert r.status_code == 201, r.text
R_V = r.json()["ids"][0]
for nid in (R1, R_V):
    for no in range(100, 122):
        sql("INSERT INTO fs_versions(node_id, no, path, size, mime, sha256, created_by, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (nid, no, f"fs/x-{nid}-{no}", 1, "application/pdf", "", ALICE, ts), write=True)
out = in_app(f"from kalmido.admin.dataretention import orf_prune_versions\nprint('prune', orf_prune_versions(c, {R1}, False)[0], "
             f"orf_prune_versions(c, {R_V}, False)[0])")
check("prune 0 3" in out, "#2600: a booked receipt keeps every version, another file loses the oldest " + out[-300:])
sql(f"DELETE FROM fs_versions WHERE node_id IN ({R1}, {R_V}) AND no>=100", write=True)

# ---------------------------------------------------------------- #2601 the running month, clients with drives
VID = A.post(B + V, json={"name": "Kombi", "kind": "private", "odo_start": "1000"}).json()["id"]
r = A.post(B + LB + "/close", json={"month": TODAY.isoformat()[:7], "vehicle_id": VID})
check(r.status_code == 400 and "Only past months" in r.text, "#2601: the running month cannot be closed (400) " + r.text[:160])
r = A.post(B + LB + "/close", json={"month": PPM[:7], "vehicle_id": VID})
check(r.ok, "#2601: a past month is closed " + r.text[:160])
CL2 = A.post(B + "/api/clients", json={"name": "Kunde Zwei GmbH"}).json()["id"]
CL3 = A.post(B + "/api/clients", json={"name": "Kunde Drei GmbH"}).json()["id"]
CL4 = A.post(B + "/api/clients", json={"name": "Kunde Vier GmbH"}).json()["id"]
r = A.post(B + DR, json={"vehicle_id": VID, "day": DAY(1), "dest": "Kunde", "purpose": "Dreh", "km": 30, "kind": "business", "client_id": CL2})
check(r.status_code == 201 and sql("SELECT client_id FROM office_drives WHERE id=?", (r.json().get("id"),)) == [(CL2,)], "a drive for a client " + r.text[:160])
r = A.delete(B + f"/api/clients/{CL2}")
check(r.ok and r.json().get("archived") is True and "logbook" in r.json().get("message", "") and sql("SELECT archived FROM clients WHERE id=?", (CL2,)) == [(1,)],
      "#2601: a client with drives is archived instead of deleted " + r.text[:200])
r = A.post(B + T, json={"date_from": DAY(20), "dest": "Hamburg - Berlin", "purpose": "job", "client_id": CL3,
                        "items": [{"date": DAY(20), "category": "train", "amount": "80.00"}]})
check(r.status_code == 201, "a trip for a client " + r.text[:160])
r = A.post(B + "/api/clients/bulk", json={"action": "delete", "ids": [CL3, CL4]})
check(r.ok and r.json().get("archived") == 1 and r.json().get("deleted") == 1 and sql("SELECT archived FROM clients WHERE id=?", (CL3,)) == [(1,)]
      # 2.272.0 (#3029): the other one goes to the clients' trash (deleted_at), deleted for good after the trash period
      and not sql("SELECT 1 FROM clients WHERE id=? AND deleted_at IS NULL", (CL4,)), "#2601: several at once: the client with a trip archived, the other deleted " + r.text[:200])

# ---------------------------------------------------------------- #2601 the personal office into an organisation
A.patch(B + "/api/settings", json={"workspace": "private"})
PV = A.post(B + V, json={"name": "Privatwagen", "kind": "private", "odo_start": "500"}).json()["id"]
check(A.post(B + DR, json={"vehicle_id": PV, "day": PPM, "dest": "Studio", "km": 12}).status_code == 201, "a drive in the personal office")
check(A.post(B + LB + "/close", json={"month": PPM[:7]}).ok and A.post(B + LB + "/close", json={"month": PM[:7]}).ok,
      "the personal office closes two months for every vehicle")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
V_ORG = A.post(B + V, json={"name": "Transporter", "kind": "company", "odo_start": "2000"}).json()["id"]
check(A.post(B + LB + "/close", json={"month": PPM[:7]}).ok, "the organisation closes the older month for every vehicle")
A.patch(B + "/api/settings", json={"workspace": "private"})
r = A.get(B + O + f"/move/check?org={ORG}")
check(r.ok and not r.json().get("conflicts"), "#2601: the check names no conflict for a month closed on both sides " + r.text[:300])
r = A.post(B + O + "/move/org", json={"org": ORG, "confirm": True})
check(r.ok, "#2601: the personal office moves although the organisation closed the same month " + r.text[:300])
rows = sorted((v or 0, m) for v, m in sql("SELECT vehicle_id, month FROM office_drive_closed WHERE org_id=?", (ORG,)))
want = sorted([(0, PPM[:7]), (VID, PPM[:7]), (PV, PPM[:7]), (PV, PM[:7])])
check(rows == want, f"#2601: every vehicle of the personal office closed per vehicle, the organisation's own rows unchanged {rows} != {want}")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.post(B + DR, json={"vehicle_id": V_ORG, "day": PM, "dest": "Lager", "km": 4})
check(r.status_code == 201, "#2601: the organisation's own vehicle stays open in the month only the personal office had closed " + r.text[:160])
r = A.post(B + DR, json={"vehicle_id": PV, "day": PM, "dest": "Lager", "km": 4})
check(r.status_code == 409 and "month is closed" in r.text, "#2601: the moved vehicle stays closed in that month " + r.text[:160])

# ---------------------------------------------------------------- the same for a person without an organisation
FID, Fr = freelancer(B, A)
F_R = receipt(Fr, "private", "frei-software.pdf", "7")
r = Fr.put(B + f"/api/docs/{F_R}/receipt", json={"category": "", "vat_pct": None})
check(r.ok and not r.json()["receipt"]["is_receipt"], "freelancer #2600: the VAT rate removed " + r.text[:200])
r = purge(Fr, F_R)
check(r.status_code == 409 and "Kept by law until" in r.text, "freelancer #2600: the lock stays " + r.text[:200])
FV = Fr.post(B + V, json={"name": "Rad", "kind": "private", "odo_start": "0"}).json()["id"]
r = Fr.post(B + LB + "/close", json={"month": TODAY.isoformat()[:7], "vehicle_id": FV})
check(r.status_code == 400 and "Only past months" in r.text, "freelancer #2601: the running month cannot be closed (400) " + r.text[:160])
check(Fr.post(B + LB + "/close", json={"month": PM[:7], "vehicle_id": FV}).ok, "freelancer #2601: a past month is closed")

print(f"p2186_b_lock: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
