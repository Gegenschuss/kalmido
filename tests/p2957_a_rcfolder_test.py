#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.957.0 (#4910) API tests: receipts of the credit cards and of the bank file themselves into month folders. Own container
(start.sh, org encryption on). Every company, card and figure is invented and made here. tenant-matrix: office
freelancer-matrix: office
 - the statement's PDF lands in Receipts / Credit card / <card with holder> / <year> / <YYYY-MM month> (the statement's month),
   without the tag
 - a receipt matched with a position (a later match and the upload at the position) moves there from the inbox and gets the
   tag "Credit card"; the holder's own upload stays the holder's and stays readable for them
 - a document filed by hand stays in its folder (the tag comes anyway); taking the match back moves nothing back
 - the bank: a receipt matched with a booking goes to Receipts / Bank / <account> / <year> / <YYYY-MM month> (the booking's
   day) with the tag "Bank"; unmatch moves nothing back
 - a person without an organisation: the same in the personal office, the names in their language (German)
usage: p2957_a_rcfolder_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
from kt import FAILS, OKS, check, sess, until, B, H, DATA  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
KEY = base64.b64encode(os.urandom(32)).decode()


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def pdf(lines):
    """A PDF with a text layer, one line of text per entry (hand-written, no library)."""
    body_ = "\n".join(f"({x}) Tj T*" for x in lines)
    stream = f"BT /F1 10 Tf 12 TL 40 760 Td\n{body_}\nET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def path(nid):
    """The folder names above node nid, from the top of its space (the documents folder first)."""
    out, p = [], sql("SELECT parent_id FROM fs_nodes WHERE id=?", (nid,))[0][0]
    while p:
        name, p = sql("SELECT name, parent_id FROM fs_nodes WHERE id=?", (p,))[0]
        out.insert(0, name)
    return out


def tags(nid):
    return sorted(r[0] for r in sql("SELECT t.name FROM doc_node_tags nt JOIN doc_tags t ON t.id=nt.tag_id WHERE nt.node_id=?", (nid,)))


def done(nid):
    until(lambda: (sql("SELECT state FROM doc_meta WHERE node_id=?", (nid,)) or [["wait"]])[0][0] in ("done", "failed"), 30)


if not os.environ.get("KMT_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo = sess("bob")
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
FEAT = "cal,comments,collab,office,clients,docs"
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
OF = "/api/office"
K = OF + "/cards"
A.put(B + OF + "/settings", json={"company_fields": {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"}})
Y = testclock.today().year - 1  # a closed year: nothing of the test lies in the future
LINES = [f"Kreditkartenabrechnung vom 15.01.{Y}", "Beispielbank Mastercard Business", "Karte 5232 12XX XXXX 4711", "Saldo Vormonat 100,00-",
         "28.12. 29.12. Cafe Beispiel Berlin 12,50-", "02.01. 02.01. Ihre Zahlung 100,00+", "03.01. 04.01. Cloud Beispiel Inc USD 20,00 18,40-",
         "05.01. 05.01. Gutschrift Beispielhaendler 5,00+", "08.01. 08.01. Laden Beispiel 7,00-", "Neuer Saldo 32,90-"]
IBAN = "DE02120300000000202051"


def up(s, cid, data):
    return s.post(B + f"{K}/{cid}/statements", files={"file": ("stmt.pdf", data, "application/pdf")})


def doc(s, name, amount, day, ws):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, pdf(["Rechnung " + name]), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    done(nid)
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day})
    assert r.ok, r.text
    return nid


def camt(entries):
    return ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>S</Id>'
            f'<Acct><Id><IBAN>{IBAN}</IBAN></Id><Ccy>EUR</Ccy></Acct>' + "".join(entries) + '</Stmt></BkToCstmrStmt></Document>')


def ntry(amt, day, ref):
    return (f'<Ntry><Amt Ccy="EUR">{amt}</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{day}</Dt></BookgDt><AcctSvcrRef>{ref}</AcctSvcrRef>'
            f'<NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>Beispiel Lieferant</Nm></Pty></Cdtr></RltdPties><RmtInf><Ustrd>Buchung {ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>')


def flow(s, uid, holder, ws, words):
    """The whole way in one office: words = (receipts, credit card, bank, January, February) in the office owner's language."""
    rc, cc, bank, jan, feb = words
    r = s.post(B + K, json={"holder_id": uid, "last4": "4711"})
    assert r.status_code == 201, r.text
    card = r.json()["id"]
    r = up(s, card, pdf(LINES))
    check(r.status_code == 201, f"{ws}: statement read {r.text[:200]}")
    sid = r.json()["statement"]["id"]
    month = [rc, cc, f"Mastercard ·· 4711 ({holder})", str(Y), f"{Y}-01 {jan}"]
    st = sql("SELECT node_id FROM office_cc_statements WHERE id=?", (sid,))[0][0]
    p = path(st)
    check(p[1:] == month and len(p) == 6, f"{ws}: the statement's PDF in the card's month folder (the statement's month) {p}")
    check(cc not in tags(st), f"{ws}: the statement's PDF is no receipt: no tag {tags(st)}")
    root = p[0]
    assert s.post(B + f"{K}/statements/{sid}/confirm", json={}).ok
    ls = s.get(B + f"{K}/statements/{sid}").json()["lines"]
    # a later match of a document in the inbox (the documents folder itself)
    cafe = doc(s, "cafe-beispiel.pdf", "12.50", f"{Y - 1}-12-28", ws)
    check(path(cafe) == [root], f"{ws}: the document starts in the inbox {path(cafe)}")
    r = s.post(B + f"{K}/lines/{ls[0]['id']}/match", json={"node_id": cafe})
    check(r.ok and r.json()["line"]["state"] == "matched", f"{ws}: matched {r.text[:200]}")
    check(path(cafe)[1:] == month, f"{ws}: the receipt moved into the month of the statement, not of its own day {path(cafe)}")
    check(cc in tags(cafe), f"{ws}: the receipt carries the tag {tags(cafe)}")
    # taking the match back moves nothing back
    assert s.post(B + f"{K}/lines/{ls[0]['id']}/unmatch").ok
    check(path(cafe)[1:] == month, f"{ws}: unmatch leaves the receipt in its folder {path(cafe)}")
    # a document filed by hand stays where it is
    rid = sql("SELECT parent_id FROM fs_nodes WHERE id=?", (cafe,))[0][0]
    while sql("SELECT parent_id FROM fs_nodes WHERE id=?", (rid,))[0][0]:
        rid = sql("SELECT parent_id FROM fs_nodes WHERE id=?", (rid,))[0][0]
    r = s.post(B + "/api/files/folders", json={"name": "Abgelegt von Hand", "parent_id": rid})
    assert r.ok, r.text
    hand = r.json()["id"]
    cloud = doc(s, "cloud-rechnung.pdf", "18.40", f"{Y}-01-03", ws)
    r = s.patch(B + f"/api/files/nodes/{cloud}", json={"parent_id": hand})
    assert r.ok, r.text
    assert s.post(B + f"{K}/lines/{ls[1]['id']}/match", json={"node_id": cloud}).ok
    check(path(cloud) == [root, "Abgelegt von Hand"], f"{ws}: filed by hand: stays {path(cloud)}")
    check(cc in tags(cloud), f"{ws}: the tag comes anyway {tags(cloud)}")
    # the bank: the booking's day decides the month
    r = s.post(B + OF + "/settings/bank-accounts", json={"label": "Geschaeftskonto Beispiel", "iban": IBAN, "default": True})
    check(r.status_code == 201, f"{ws}: a bank account {r.text[:200]}")
    r = s.post(B + OF + "/bank/import", json={"text": camt([ntry("30.00", f"{Y}-02-03", "R-1")]), "filename": "k.xml"})
    check(r.status_code == 201, f"{ws}: bank import {r.text[:200]}")
    tx = [t["id"] for t in s.get(B + OF + "/bank/tx?state=all").json()["items"] if t["purpose"] == "Buchung R-1"][0]
    bdoc = doc(s, "lieferant.pdf", "30.00", f"{Y}-02-01", ws)
    assert s.put(B + f"/api/docs/{bdoc}/receipt", json={"keep": True}).ok
    r = s.post(B + OF + f"/bank/tx/{tx}/match", json={"kind": "receipt", "id": bdoc})
    check(r.ok and r.json()["match"]["kind"] == "receipt", f"{ws}: the booking matched {r.text[:200]}")
    bpath = path(bdoc)
    check(bpath[1:] == [rc, bank, "Geschaeftskonto Beispiel", str(Y), f"{Y}-02 {feb}"], f"{ws}: the receipt in the account's month folder (the booking's day) {bpath}")
    check(bank in tags(bdoc), f"{ws}: the tag Bank {tags(bdoc)}")
    assert s.post(B + OF + f"/bank/tx/{tx}/unmatch").ok
    check(path(bdoc) == bpath, f"{ws}: unmatch at the bank moves nothing back {path(bdoc)}")
    return card, sid, ls, month


# ---- an organisation: the admin's language is English
CARD, SID, LS, MONTH = flow(A, BOB, "Bob Member", f"org:{ORG}", ("Receipts", "Credit card", "Bank", "January", "February"))
# the holder uploads the receipt at the position: moved, still theirs, still readable for them
r = Bo.post(B + f"{K}/lines/{LS[3]['id']}/upload", files={"file": ("beleg.pdf", pdf(["Beleg des Inhabers"]), "application/pdf")})
check(r.status_code == 201 and r.json()["line"]["state"] == "matched", f"the holder uploads the receipt {r.text[:300]}")
NID = r.json()["node_id"]
check(path(NID)[1:] == MONTH, f"the holder's upload in the card's month folder {path(NID)}")
check(sql("SELECT owner_id FROM fs_nodes WHERE id=?", (NID,))[0][0] == BOB, "the receipt stays the holder's")
check(Bo.get(B + f"/api/docs/{NID}").ok, "and the holder still opens it")
done(NID)
check(path(NID)[1:] == MONTH and "Credit card" in tags(NID), f"after the recognition: same folder, tag still there {path(NID)} {tags(NID)}")
check(Bo.get(B + f"/api/files/nodes/{sql('SELECT parent_id FROM fs_nodes WHERE id=?', (NID,))[0][0]}").status_code in (403, 404),
      "the month folder itself is not handed to the member (no share, no organisation access)")

# ---- review F1: a folder of the path opened wider than the documents folder takes no receipt (no silent widening)
RCV = sql("SELECT parent_id FROM fs_nodes WHERE id=?", (sql("SELECT parent_id FROM fs_nodes WHERE id=?", (sql("SELECT parent_id FROM fs_nodes WHERE id=?", (sql("SELECT parent_id FROM fs_nodes WHERE id=?", (sql("SELECT parent_id FROM fs_nodes WHERE id=?", (NID,))[0][0],))[0][0],))[0][0],))[0][0],))[0][0]
check(sql("SELECT name FROM fs_nodes WHERE id=?", (RCV,))[0][0] == "Receipts", "the Receipts folder found")
r = A.patch(B + f"/api/files/nodes/{RCV}", json={"org_access": "view"})
check(r.ok, f"the admin opens Receipts to the organisation {r.text[:200]}")
WIDE = doc(A, "gutschrift.pdf", "5.00", f"{Y}-01-05", f"org:{ORG}")
WP = path(WIDE)
assert A.post(B + f"{K}/lines/{LS[2]['id']}/match", json={"node_id": WIDE}).ok
check(path(WIDE) == WP and "Credit card" in tags(WIDE), f"opened path: the receipt stays in the inbox, the tag comes {path(WIDE)} {tags(WIDE)}")
assert A.patch(B + f"/api/files/nodes/{RCV}", json={"org_access": ""}).ok

# ---- a person without an organisation, German
FID, Fr = freelancer(B, A, "frida")
assert Fr.patch(B + "/api/settings", json={"lang": "de"}).ok
Fr.put(B + OF + "/settings", json={"company_fields": {"name": "Frida Beispiel", "street": "Musterweg 2", "zip": "12345", "city": "Musterstadt", "country": "DE"}})
flow(Fr, FID, "Frida", "private", ("Belege", "Kreditkarte", "Bank", "Januar", "Februar"))

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
