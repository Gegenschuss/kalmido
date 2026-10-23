#!/usr/bin/env python3
"""2.190.0 API tests, part D (#2496 #2561): hardening of office, files, integrations and calendars, own container (start.sh).
Invented people, firms and figures only (example.com).
tenant-matrix: office
freelancer-matrix: office
 - #2561 the index hub_mails(org_id); an organisation export leaves out the filed mails the exporting admin cannot open
 - #2496 DATEV Belegfeld 1 without a leading sign; the travel expense CSV is not cached
 - #2496 an invoice with a negative total is not finalised; credit notes alone covering an invoice cancel it (not "paid")
 - #2496 the cash book's opening balance is fixed with the first entry (also in the personal office of a freelancer)
 - #2496 office agents keep their list restriction (documents of another project are not found)
 - #2496 a member's document in the organisation's documents folder keeps its name next to an admin's of the same name;
   a TIFF loses its GPS directory
 - #2561 a contract file found infected later is locked for download
 - #2561 an inbound webhook body without a length is capped (413)
 - #2496 a mailbox without encryption only to a local server; the event feed drops imported organiser / attendees / alarms;
   public pages never show a login name
usage: p2190_d_hardening_test.py <datadir>      (P2190D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import struct
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
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs,files,events"
O = "/api/office"
D, CBS = O + "/docs", O + "/cashbooks"
TODAY = testclock.today()
DAY = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


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


def gps_tiff():
    """A tiny little-endian TIFF: IFD0 (width, height, GPS pointer) at 8, the GPS IFD at 50 (latitude ref N + latitude as
    three rationals at 80)."""
    e = lambda tag, typ, cnt, val: struct.pack("<HHI", tag, typ, cnt) + val  # noqa: E731
    ifd0 = struct.pack("<H", 3) + e(256, 3, 1, struct.pack("<HH", 1, 0)) + e(257, 3, 1, struct.pack("<HH", 1, 0)) \
        + e(0x8825, 4, 1, struct.pack("<I", 50)) + struct.pack("<I", 0)
    gps = struct.pack("<H", 2) + e(1, 2, 2, b"N\x00\x00\x00") + e(2, 5, 3, struct.pack("<I", 80)) + struct.pack("<I", 0)
    rat = struct.pack("<6I", 52, 1, 31, 1, 7, 1)
    data = b"II*\x00" + struct.pack("<I", 8) + ifd0 + gps + rat
    assert len(data) == 104 and data[50:52] == b"\x02\x00"
    return data


if os.environ.get("P2190D_NOSTART") != "1":
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
BOB = r.json()["id"]
r = A.post(B + "/api/users", json={"username": "nodisp", "password": "password123", "email": "nodisp@example.com"})
NODISP = r.json().get("id")
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
A.put(B + O + "/settings", json={"company_fields": {"name": "Beispiel Film GmbH", **COMPANY}})
WSO = f"org:{ORG}"
ts = testclock.now().isoformat(timespec="seconds")

# ---------------------------------------------------------------- #2561 index, organisation export of filed mails
check(sql("SELECT 1 FROM pg_indexes WHERE indexname='hub_mails_org'") == [(1,)], "#2561: the index hub_mails(org_id) exists")
for owner, mid in ((ALICE, "own@example.com"), (BOB, "other@example.com")):
    sql("INSERT INTO hub_mails(org_id, owner_id, ws, message_id, created_at) VALUES(?,?,?,?,?)", (ORG, owner, WSO, mid, ts), write=True)
M_OWN, M_BOB = (sql("SELECT id FROM hub_mails WHERE message_id=?", (m,))[0][0] for m in ("own@example.com", "other@example.com"))
out = in_app(f"from kalmido.admin.orgexport import ox_hidden_mails\nprint('hidden', sorted(ox_hidden_mails(c, {ORG}, {ALICE})), "
             f"sorted(ox_hidden_mails(c, {ORG}, None)))")
check(f"hidden [{M_BOB}] []" in out, "#2561: the admin's export leaves out another member's inbox mail (as in the app) " + out[-300:])

# ---------------------------------------------------------------- #2496 DATEV Belegfeld 1, travel CSV
out = in_app("from kalmido.office.datev import dx_beleg\nprint('beleg', repr(dx_beleg('+A1*2')), repr(dx_beleg('-1+1')), "
             "repr(dx_beleg('RE-2026-001')), repr(dx_beleg(None)))")
check("beleg 'A1*2' '1+1' 'RE-2026-001' ''" in out, "#2496: Belegfeld 1 without a leading + / - " + out[-300:])
r = A.get(B + O + "/trips/report", params={"format": "csv"})
check(r.ok and "no-store" in r.headers.get("Cache-Control", ""), f"#2496: the travel CSV is not cached ({r.status_code} {r.headers.get('Cache-Control')})")

# ---------------------------------------------------------------- #2496 negative totals, credit notes alone
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Kundenweg 2", "zip": "20095", "city": "Hamburg", "country": "DE"}).json()["id"]
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": DAY(30), "items": [{"title": "Rabatt", "qty": 1, "rate": -100}]})
NEG = r.json()["id"]
r = A.post(B + f"{D}/{NEG}/finalize")
check(r.status_code == 400 and "negative" in r.text and A.get(B + f"{D}/{NEG}").json()["locked"] is False,
      "#2496: an invoice with a negative total is not finalised " + r.text[:200])
A.delete(B + f"{D}/{NEG}")
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": DAY(30), "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]})
INV = r.json()["id"]
check(A.post(B + f"{D}/{INV}/finalize").ok, "an invoice of 119.00 finalised")
for i in (1, 2):
    CR = A.post(B + f"{D}/{INV}/credit").json()["id"]
    A.put(B + f"{D}/{CR}/items", json={"items": [{"title": "Schnitt (Teil)", "qty": 1, "rate": 50}]})
    check(A.post(B + f"{D}/{CR}/finalize").ok, f"partial credit note {i} (59.50) finalised")
inv = A.get(B + f"{D}/{INV}").json()
check(inv["status"] == "cancelled" and not sql("SELECT paid_at FROM office_docs WHERE id=?", (INV,))[0][0],
      f"#2496: two credit notes covering the invoice cancel it, never 'paid' ({inv['status']})")

# ---------------------------------------------------------------- #2496 cash book: the opening balance and the first entry
BK = A.get(B + CBS).json()["books"][0]["id"]
check(A.patch(B + f"{CBS}/{BK}", json={"opening": "100", "opening_day": DAY(30)}).ok, "the opening balance before any entry")
r = A.post(B + f"{CBS}/{BK}/entries", json={"day": DAY(2), "dir": "in", "amount": "10", "text": "Verkauf"})
check(r.status_code == 201, "a first cash entry " + r.text[:200])
r = A.patch(B + f"{CBS}/{BK}", json={"opening": "200"})
check(r.status_code == 409 and "first entry" in r.text, "#2496: the opening balance is fixed with the first entry " + r.text[:200])
check(A.patch(B + f"{CBS}/{BK}", json={"name": "Kasse Laden"}).ok, "... the name still changes")

# ---------------------------------------------------------------- #2496 office agents: the list restriction
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "office"], "username": "buero-agent", "display_name": "Buero Agent"})
check(r.status_code in (200, 201), "an agent " + r.text[:200])
AG = sql("SELECT u.id FROM users u WHERE u.username='buero-agent'")[0][0]
sql("UPDATE agents SET list_ids='5,7' WHERE user_id=?", (AG,), write=True)
out = in_app(f"from kalmido.office.agentdocs import ofa_doc_in_lists\n"
             f"print('lists', ofa_doc_in_lists(c, {AG}, {{'list_id': 5}}), ofa_doc_in_lists(c, {AG}, {{'list_id': 6}}), ofa_doc_in_lists(c, {AG}, {{'list_id': None}}))")
sql("UPDATE agents SET list_ids='' WHERE user_id=?", (AG,), write=True)
out += in_app(f"from kalmido.office.agentdocs import ofa_doc_in_lists\nprint('free', ofa_doc_in_lists(c, {AG}, {{'list_id': 6}}))")
check("lists True False True" in out and "free True" in out, "#2496: an agent with a list restriction sees office documents of its projects only " + out[-300:])

# ---------------------------------------------------------------- #2496 names in the organisation's documents folder, TIFF GPS
r = A.post(B + "/api/docs", data={"ws": WSO}, files={"files": ("vertrag.pdf", tiny_pdf("Vertrag A"), "application/pdf")})
check(r.status_code == 201, "the admin files a document " + r.text[:200])
r = Bo.post(B + "/api/docs", data={"ws": WSO}, files={"files": ("vertrag.pdf", tiny_pdf("Vertrag B"), "application/pdf")})
check(r.status_code == 201, "the member files a document of the same name " + r.text[:200])
if r.status_code == 201:
    nm = sql("SELECT name FROM fs_nodes WHERE id=?", (r.json()["ids"][0],))[0][0]
    check(nm == "vertrag.pdf", f"#2496: the member's document keeps its name (no hint at the admin's): {nm}")
tif = base64.b64encode(gps_tiff()).decode()
out = in_app(f"import base64\nfrom kalmido.files.photometa import pm_strip, pm_kind\nd = base64.b64decode('{tif}')\n"
             "o, meta = pm_strip(c, d, 'image/tiff')\nprint('tiff', pm_kind(d), base64.b64encode(o).decode())")
got = base64.b64decode(out.split("tiff tiff ", 1)[1].split()[0]) if "tiff tiff " in out else b""
check(len(got) == 104 and got[:50] == gps_tiff()[:50] and got[50:52] == b"\x00\x00" and got[80:104] == b"\x00" * 24 and b"N\x00" not in got[50:80],
      "#2496: the TIFF keeps its image directory, the GPS directory is empty and its values are gone " + out[-200:])

# ---------------------------------------------------------------- #2561 a contract file found infected later
C1 = A.post(B + O + "/contracts", json={"name": "Rahmenvertrag Kunde Eins", "client_id": CL}).json()["id"]
r = A.post(B + f"{O}/contracts/{C1}/files", files={"file": ("vertrag.pdf", tiny_pdf("Rahmenvertrag"), "application/pdf")})
check(r.status_code == 201, "a contract file " + r.text[:200])
FCF = r.json()["id"]
check(A.get(B + f"{O}/contracts/{C1}/files/{FCF}").ok, "the contract file downloads")
sql("INSERT INTO upload_scan(kind, ref_id, ver, org_id, state, sig, created_at) VALUES('ocf',?,0,?,'infected','Test-Signatur',?)", (FCF, ORG, ts), write=True)
r = A.get(B + f"{O}/contracts/{C1}/files/{FCF}")
check(r.status_code == 403 and "Test-Signatur" in r.text, "#2561: a contract file found infected later is locked " + r.text[:200])
out = in_app(f"from kalmido.files.scan import _sc_file\nf = _sc_file(c, 'ocf', {FCF}, 0)\nprint('scanfile', f[0], f[1].endswith('.pdf'), f[2] > 0)")
check("scanfile vertrag.pdf True True" in out, "#2561: the later scan finds the stored contract file " + out[-300:])
# 2.190.0 R (#2496): a contract copied into another space keeps the mark of its files
out = in_app(f"from kalmido.files.scan import sc_copy_mark, sc_locked\nsc_copy_mark(c, 'ocf', {FCF}, 987654321, {ORG})\n"
             "print('copied', sc_locked(c, 'ocf', 987654321))\nc.rollback()")
check("copied Test-Signatur" in out, "#2496: the copy of a file keeps its scan mark " + out[-300:])
# 2.190.0 R (#2496): a number drawn since never makes "undo all" fail (the fingerprint skips it for documents only)
out = in_app("from kalmido.office.undo import oun_fp\n"
             "a = oun_fp({'office_docs': [{'id': 1, 'number': '', 'title': 'x'}]})\n"
             "b = oun_fp({'office_docs': [{'id': 1, 'number': 'RE-2026-0001', 'title': 'x'}]})\n"
             "d = oun_fp({'office_docs': [{'id': 1, 'number': '', 'title': 'y'}]})\n"
             "print('fp', a == b, a == d)")
check("fp True False" in out, "#2496: undo fingerprint ignores a drawn document number, not other changes " + out[-300:])

# ---------------------------------------------------------------- #2561 inbound webhook without a length
LID = A.post(B + "/api/lists", json={"name": "Eingang"}).json()["id"]
HK = A.post(B + f"/api/lists/{LID}/hooks-in", json={"name": "Probe"}).json()
URL = B + "/api/hooks/in/" + HK["url"].split("/api/hooks/in/")[1]
r = requests.post(URL, data=(b"x" * 8192 for _ in range(16)), headers={"Content-Type": "text/plain"})
check(r.status_code == 413, f"#2561: a chunked body over the cap: 413 ({r.status_code})")
r = requests.post(URL, json={"title": "Kleine Probe"})
check(r.status_code == 201, "a small body still makes a task " + r.text[:200])

# ---------------------------------------------------------------- #2496 mailbox without encryption, event feed, public names
BOX = {"ws": "private", "imap_host": "imap.example.com", "imap_port": 143, "imap_ssl": False, "imap_user": "x", "imap_password": "secret"}
r = A.put(B + "/api/hubmail/mailbox", json=BOX)
check(r.status_code == 400 and "local network" in r.text, "#2496: IMAP without encryption to an outside server: 400 " + r.text[:200])
r = A.put(B + "/api/hubmail/mailbox", json={**BOX, "imap_ssl": True, "smtp_host": "smtp.example.com", "smtp_tls": "none", "from_addr": "a@example.com"})
check(r.status_code == 400 and "local network" in r.text, "#2496: SMTP without encryption to an outside server: 400 " + r.text[:200])
out = in_app("from kalmido.events.evfeed import evf_extra\nprint('extra', repr(evf_extra('ORGANIZER;CN=X:mailto:x@example.com\\nCATEGORIES:A\\n"
             "BEGIN:VALARM\\nTRIGGER:-PT5M\\nEND:VALARM\\nATTENDEE;CN=Y:mailto:y@example.com\\n  folded\\nX-KEEP:1')))")
check("extra 'CATEGORIES:A\\nX-KEEP:1'" in out, "#2496: the event feed drops imported organiser, attendees and alarms " + out[-300:])
out = in_app(f"from kalmido.calendars.apptbook import apb_owner_name\nprint('owner', repr(apb_owner_name(c, {NODISP})), repr(apb_owner_name(c, {ALICE})))")
check("owner '' 'Alice Admin'" in out, "#2496: public pages show the display name, never the login name " + out[-300:])

# ---------------------------------------------------------------- the personal office of a person without an organisation
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office, its own admin)
FB = Fr.get(B + CBS).json()["books"][0]["id"]
check(Fr.patch(B + f"{CBS}/{FB}", json={"opening": "20", "opening_day": DAY(30)}).ok, "freelancer: the opening balance before any entry")
check(Fr.post(B + f"{CBS}/{FB}/entries", json={"day": DAY(2), "dir": "in", "amount": "15", "text": "Barverkauf"}).status_code == 201,
      "freelancer: a first cash entry")
r = Fr.patch(B + f"{CBS}/{FB}", json={"opening": "30"})
check(r.status_code == 409, "freelancer #2496: the opening balance is fixed with the first entry " + r.text[:200])
Fr.put(B + O + "/settings", json={"company_fields": {"name": "Frida Film", **COMPANY}})
FCL = Fr.post(B + "/api/clients", json={"name": "Kundin Zwei", "street": "Weg 3", "zip": "10115", "city": "Berlin", "country": "DE"}).json()["id"]
r = Fr.post(B + D, json={"kind": "invoice", "client_id": FCL, "service_from": DAY(30), "items": [{"title": "Rabatt", "qty": 1, "rate": -10}]})
r = Fr.post(B + f"{D}/{r.json()['id']}/finalize")
check(r.status_code == 400 and "negative" in r.text, "freelancer #2496: no invoice with a negative total " + r.text[:200])

print(f"p2190_d_hardening: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
