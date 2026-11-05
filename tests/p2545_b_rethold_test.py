#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.545.0 B API tests (#4595): the legal retention periods get a buffer (default 1 year, the operator sets it, never below
the law) and an office can switch on "Extend the lock" (a tax audit is open): nothing kept by law is deleted while it is on,
not even after its period. Own container (start.sh). Invented people, firms and figures only (example.com).
freelancer-matrix: office
 - the default: the law + 1 year (GET /api/admin/retention keep_years, the lock of a booked receipt ends 31 Dec <year + 9>)
 - ret_keep_years: an operator value below 0 counts as 0 (exactly the law), 2 = the law + 2, a broken value = the default
 - the switch: only the office admin (a member 403), {"on": bool} only (400), on keeps its first day, the office log has it
 - switch on: a booked receipt whose period is over cannot be deleted for good (409 with the reason), deleting the
   organisation 409; switch off: both go again
 - the same for a person without an organisation (freelancer_fixture: the personal office)
usage: p2545_b_rethold_test.py <datadir>      (P2545B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import subprocess
import sys
import time

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
from kt import FAILS, OKS, check, sess  # noqa: E402
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
RH = O + "/settings/retention-hold"
TODAY = testclock.today()
OLD = "2015-03-01"  # a receipt of 2015: its period (8 + 1 years from the end of the year) ended on 31 Dec 2024


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


def receipt(s, ws, name, day):
    """A booked receipt (VAT rate set) dated day."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    for _ in range(120):  # the recognition may set its own date: it is through first
        if not sql("SELECT 1 FROM doc_meta WHERE node_id=? AND state='run'", (nid,)):
            break
        time.sleep(0.25)
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": "119.00", "date": day})
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "vat_pct": "19", "keep": True})
    assert r.ok, r.text
    return nid


def purge(s, nid):
    """Into the trash, then deleted for good; a refused purge restores it (the next try starts the same way)."""
    assert s.delete(B + f"/api/files/nodes/{nid}").ok
    r = s.delete(B + f"/api/files/nodes/{nid}?purge=1")
    if r.status_code == 409:
        s.post(B + f"/api/files/nodes/{nid}/restore")
    return r


if os.environ.get("P2545B_NOSTART") != "1":
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
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
A.get(B + O + "/settings")
WSO = f"org:{ORG}"

# ---------------------------------------------------------------- the default: the law + 1 year
j = A.get(B + "/api/admin/retention").json()
check(j.get("buffer_years") == 1 and j.get("keep_years") == {"receipt": 9, "book": 11, "logbook": 9, "letter": 7}
      and j.get("legal_years") == {"receipt": 8, "book": 10, "logbook": 8, "letter": 6} and j.get("env_buffer") == "KALMIDO_RETENTION_BUFFER_YEARS",
      f"default: the law + 1 year {j}")
R_NEW = receipt(A, WSO, "neu.pdf", TODAY.isoformat())
r = purge(A, R_NEW)
check(r.status_code == 409 and f"31 Dec {TODAY.year + 9}" in r.text, f"a booked receipt of this year is kept until 31 Dec {TODAY.year + 9} " + r.text[:200])
out = in_app("import os\nfrom kalmido.core.retention import ret_keep_years\n"
             "for v in ('-3', '0', '2', 'abc', '99'):\n"
             "    os.environ['KALMIDO_RETENTION_BUFFER_YEARS'] = v\n"
             "    print('KY', v, ret_keep_years('receipt'), ret_keep_years('book'), ret_keep_years('letter'))")
check("KY -3 8 10 6" in out, "an operator value below the law: exactly the law " + out[-300:])
check("KY 0 8 10 6" in out and "KY 2 10 12 8" in out, "0 = the law, 2 = the law + 2 " + out[-300:])
check("KY abc 9 11 7" in out and "KY 99 38 40 36" in out, "a broken value = the default, at most 30 years more " + out[-300:])

# ---------------------------------------------------------------- the switch: who, what
check(Bo.get(B + RH).status_code == 403 and Bo.put(B + RH, json={"on": True}).status_code == 403, "a member may not see or set the switch")
check(A.put(B + RH, json={"on": "yes"}).status_code == 400 and A.put(B + RH, json={}).status_code == 400, "only {on: bool}")
j = A.get(B + RH).json()
check(j.get("on") is False and j.get("since") is None and j.get("keep_years", {}).get("receipt") == 9, f"off by default {j}")

# ---------------------------------------------------------------- off: a receipt past its period goes
R_OLD1, R_OLD2 = receipt(A, WSO, "alt1.pdf", OLD), receipt(A, WSO, "alt2.pdf", OLD)
check(purge(A, R_OLD1).ok and not sql("SELECT 1 FROM fs_nodes WHERE id=?", (R_OLD1,)), "switch off: a booked receipt of 2015 is deleted for good")

# ---------------------------------------------------------------- on: nothing kept by law goes, also after its period
j = A.put(B + RH, json={"on": True}).json()
check(j.get("on") is True and j.get("since") and j.get("by_name") == "Alice Admin", f"switched on {j}")
since = j.get("since")
check(A.put(B + RH, json={"on": True}).json().get("since") == since, "switching on again keeps the first day")
r = purge(A, R_OLD2)
check(r.status_code == 409 and "Deleting is paused" in r.text and sql("SELECT 1 FROM fs_nodes WHERE id=?", (R_OLD2,)),
      "switch on: the receipt past its period is not deleted for good (409 with the reason) " + r.text[:200])
out = in_app(f"from kalmido.receipts.suggest import olk_fs_locked\nprint('L', olk_fs_locked(c, {R_OLD2}, arrival=True, hold=True), olk_fs_locked(c, {R_OLD2}))")
check("L 9999-12-31 None" in out, "the deleting runs see the switch, the move and the trash do not " + out[-300:])
r = A.delete(B + f"/api/admin/orgs/{ORG}", params={"confirm": "1"})
check(r.status_code == 409 and "Deleting is paused" in r.text and sql("SELECT 1 FROM orgs WHERE id=?", (ORG,)),
      "switch on: the organisation is not deleted " + r.text[:200])
log = A.get(B + O + "/log", params={"limit": 20}).json()
acts = [x.get("action") for x in (log.get("log") or log.get("items") or [])] if isinstance(log, dict) else [x.get("action") for x in log]
check("retention_hold" in acts, f"the office log names the switch {acts}")

# ---------------------------------------------------------------- off again: as before
j = A.put(B + RH, json={"on": False}).json()
check(j.get("on") is False and j.get("since") is None, f"switched off {j}")
check(purge(A, R_OLD2).ok and not sql("SELECT 1 FROM fs_nodes WHERE id=?", (R_OLD2,)), "switch off again: the receipt past its period goes")

# ---------------------------------------------------------------- the same for a person without an organisation
FID, Fr = freelancer(B, A)
Fr.get(B + O + "/settings")
F_OLD1, F_OLD2 = receipt(Fr, "private", "frei-alt1.pdf", OLD), receipt(Fr, "private", "frei-alt2.pdf", OLD)
check(purge(Fr, F_OLD1).ok, "freelancer: switch off, a booked receipt of 2015 goes")
j = Fr.put(B + RH, json={"on": True}).json()
check(j.get("on") is True, f"freelancer: the switch of the own office {j}")
r = purge(Fr, F_OLD2)
check(r.status_code == 409 and "Deleting is paused" in r.text, "freelancer: switch on, the receipt past its period stays " + r.text[:200])
check(Fr.put(B + RH, json={"on": False}).json().get("on") is False and purge(Fr, F_OLD2).ok, "freelancer: switch off, it goes")
check(A.get(B + RH).json().get("on") is False, "the organisation's switch is its own")

print(f"p2545_b_rethold: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
