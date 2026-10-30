#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.444.0 (#3447) API tests: credit card statements in the office, own container (start.sh, org encryption on). Every statement,
company and figure is invented and made here; no real statement in a test. tenant-matrix: office  freelancer-matrix: office
 - the Mastercard reader on an artificial statement: both days, the year of December on a January statement, foreign amount and
   currency, the foreign fee as a position of its own, money back, fees "no receipt needed", balances and the last payment no
   positions, the printed total, the digits
 - not a PDF 400, one statement per card and month 409, a PDF without text: nothing read, the positions typed in
 - a draft counts for nothing; positions that do not add up 409 until accepted; confirmed positions cannot be changed
 - the receipt search over all documents (also unsorted ones): amount, original amount, name, best first; a suggestion is
   never matched by itself; the match sets the payment day, one document on one position, not also on a bank booking, undone
   again; a document in the trash shows as gone
 - private positions add up to what the holder pays back; the bank booking of the total: wrong sum 409, matched it leaves the
   bookings without a receipt, undone it is back
 - rights: the holder sees only their own card, works on it, never the cards themselves or the bank; another organisation 404;
   the reminder goes to the holder and ends by itself; DATEV and the neutral export carry the card
 - a person without an organisation: the same in the personal office
usage: p2444_a_cards_test.py <datadir>"""
import base64
import csv
import io
import os
import subprocess
import sys
import time
import zipfile
from datetime import date, timedelta

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
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
FEAT = "cal,comments,collab,office,clients,docs"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
O = "/api/office"
K = O + "/cards"
A.put(B + O + "/settings", json={"company_fields": {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"},
                                 "datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}})
Y = testclock.today().year - 1  # a closed year: nothing of the test lies in the future
J = f"{Y}-01"
LINES = [f"Kreditkartenabrechnung vom 15.01.{Y}", "Beispielbank Mastercard Business", "Karte 5232 12XX XXXX 4711", "Saldo Vormonat 100,00-",
         "28.12. 29.12. Cafe Beispiel Berlin 12,50-", "02.01. 02.01. Ihre Zahlung 100,00+", "03.01. 04.01. Cloud Beispiel Inc USD 20,00 18,40-",
         "Auslandseinsatzentgelt 1,75% 0,32-", "05.01. 05.01. Gutschrift Beispielhaendler 5,00+", "10.01. 10.01. Jahresentgelt 30,00-", "Neuer Saldo 56,22-"]


def up(s, cid, data, name="stmt.pdf", **form):
    return s.post(B + f"{K}/{cid}/statements", files={"file": (name, data, "application/pdf")}, data=form)


def sheet(s, sid):
    return s.get(B + f"{K}/statements/{sid}").json()


# ---- cards
r = A.post(B + K, json={"holder_id": BOB, "last4": "4711", "account": "DE02120300000000202051"})
check(r.status_code == 201 and r.json()["holder"] == "Bob Member", f"a card of a person of the area {r.text[:200]}")
CARD = r.json()["id"]
r = A.post(B + K, json={"holder_name": "Fremder Name", "last4": "9999"})
check(r.status_code == 201 and r.json()["holder"] == "Fremder Name", "a card with a free name, no account")
CARD2 = r.json()["id"]
check(A.post(B + K, json={"holder_name": "X", "last4": "12"}).status_code == 400, "four digits or 400")
check(A.post(B + K, json={"last4": "1234"}).status_code == 400, "a holder or 400")
check(A.post(B + K, json={"holder_id": CAROL, "last4": "1234"}).status_code == 400, "a person of another area is no holder")
check(sql("SELECT last4 FROM office_cc_cards WHERE id=?", (CARD,))[0][0] != "4711", "the digits are encrypted at rest")

# ---- the reader
check(A.post(B + f"{K}/{CARD}/statements", files={"file": ("x.txt", b"no pdf", "text/plain")}).status_code == 400, "only a PDF")
r = up(A, CARD, pdf(LINES))
check(r.status_code == 201 and r.json()["read"] is True and not r.json()["digits_differ"], f"statement read {r.text[:300]}")
ST = r.json()["statement"]
SID = ST["id"]
check(ST["month"] == J and ST["day"] == f"{Y}-01-15" and ST["total"] == "56.22" and ST["sum"] == "56.22" and ST["state"] == "draft", f"head of the statement {ST}")
S = sheet(A, SID)
L = S["lines"]
check([x["merchant"] for x in L] == ["Cafe Beispiel Berlin", "Cloud Beispiel Inc", "Auslandseinsatzentgelt 1,75%", "Gutschrift Beispielhaendler", "Jahresentgelt"], f"positions, no balance, no payment {[x['merchant'] for x in L]}")
check(L[0]["day"] == f"{Y - 1}-12-28" and L[0]["booked"] == f"{Y - 1}-12-29", f"December of the year before {L[0]}")
check(L[1]["amount"] == "18.40" and L[1]["orig_amount"] == "20.00" and L[1]["orig_currency"] == "USD", f"the euro amount counts, the original stays {L[1]}")
check(L[2]["kind"] == "fee" and L[2]["state"] == "noreceipt" and L[2]["amount"] == "0.32", f"the foreign fee is its own position, needs no receipt {L[2]}")
check(L[3]["kind"] == "credit" and L[3]["amount"] == "-5.00" and L[3]["state"] == "open", f"money back {L[3]}")
check(L[4]["kind"] == "fee" and L[4]["state"] == "noreceipt", "the yearly fee needs no receipt")
check(sql("SELECT merchant FROM office_cc_lines WHERE id=?", (L[0]["id"],))[0][0] != "Cafe Beispiel Berlin", "the merchant is encrypted at rest")
check(sql("SELECT amount FROM office_cc_lines WHERE id=?", (L[0]["id"],))[0][0] != "12.50", "the amount is encrypted at rest")
check(up(A, CARD, pdf(LINES)).status_code == 409, "one statement per card and month")
r = up(A, CARD2, pdf(LINES))
check(r.status_code == 201 and r.json()["digits_differ"] is True, "other digits on the statement are said")
assert A.delete(B + f"{K}/statements/{r.json()['statement']['id']}").ok
r = up(A, CARD2, pdf(["Dieses Blatt hat keine Positionen"]), month=f"{Y}-02")
check(r.status_code == 201 and r.json()["read"] is False and r.json()["statement"]["reader"] == "manual", f"nothing readable: typed in {r.text[:200]}")
MS = r.json()["statement"]["id"]
r = A.post(B + f"{K}/statements/{MS}/lines", json={"day": f"{Y}-02-03", "merchant": "Handeintrag Beispiel", "amount": "10.00"})
check(r.status_code == 201 and r.json()["statement"]["sum"] == "10.00", f"a position typed in {r.text[:200]}")
ML = r.json()["line"]["id"]
check(A.post(B + f"{K}/statements/{MS}/confirm", json={}).status_code == 409, "the positions do not add up to the total (0.00): 409")
assert A.patch(B + f"{K}/statements/{MS}", json={"total": "10.00"}).ok
check(A.post(B + f"{K}/statements/{MS}/confirm", json={}).ok, "typed total fits: confirmed")
check(A.patch(B + f"{K}/lines/{ML}", json={"amount": "11.00"}).status_code == 409, "a confirmed position cannot change")
check(A.post(B + f"{K}/lines/{ML}/match", json={"node_id": 1}).status_code in (404, 409), "a stranger's document")

# ---- nothing counts before the confirmation
check(A.post(B + f"{K}/lines/{L[0]['id']}/match", json={"node_id": 1}).status_code == 409, "a draft takes no receipt")
assert A.post(B + f"{K}/statements/{SID}/confirm", json={}).ok

# ---- the search for the receipt
WSO = f"org:{ORG}"


def doc(s, name, amount, day, currency=None, ws=WSO):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, pdf(["Rechnung"]), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    until(lambda: (sql("SELECT state FROM doc_meta WHERE node_id=?", (nid,)) or [["wait"]])[0][0] in ("done", "failed"), 30)
    b = {"amount": amount, "date": day}
    if currency:
        b["currency"] = currency
    r = s.patch(B + f"/api/docs/{nid}", json=b)
    assert r.ok, r.text
    return nid


CAFE = doc(A, "cafe-beispiel.pdf", "12.50", f"{Y - 1}-12-28")  # unsorted: no receipt yet
CLOUD = doc(A, "cloud-rechnung.pdf", "20.00", f"{Y}-01-03", "USD")
OTHER = doc(A, "anderes.pdf", "99.00", f"{Y}-06-01")
c = A.get(B + f"{K}/lines/{L[0]['id']}/candidates").json()["items"]
check(c and c[0]["id"] == CAFE, f"found over all documents, also unsorted {c}")
check(all(x["id"] != OTHER for x in c), "what does not fit is not offered")
c = A.get(B + f"{K}/lines/{L[1]['id']}/candidates").json()["items"]
check(c and c[0]["id"] == CLOUD, f"found by the original amount {c}")
check(A.get(B + f"{K}/lines/{L[0]['id']}/candidates?q=anderes").json()["items"][0]["id"] == OTHER, "the search finds the rest")
S = sheet(A, SID)
check(S["lines"][0]["suggestion"]["id"] == CAFE and S["lines"][0]["state"] == "open", "a suggestion, nothing matched by itself")
check(not sql("SELECT 1 FROM rc_receipts WHERE node_id=?", (CAFE,)), "the document is untouched before the press")
r = A.post(B + f"{K}/lines/{L[0]['id']}/match", json={"node_id": CAFE})
check(r.ok and r.json()["line"]["state"] == "matched" and r.json()["amount_differs"] is None, f"matched after the press {r.text[:200]}")
check(sql("SELECT paid_at FROM rc_receipts WHERE node_id=?", (CAFE,))[0][0] == f"{Y - 1}-12-28", "the document is a receipt, paid on the position's day")
check(A.post(B + f"{K}/lines/{L[1]['id']}/match", json={"node_id": CAFE}).status_code == 409, "one document on one position")
check(A.post(B + f"{K}/lines/{L[2]['id']}/match", json={"node_id": OTHER}).status_code == 409, "a fee takes no receipt")
check(A.post(B + f"{K}/statements/{SID}/reopen").status_code == 409, "the confirmation stays while receipts hang on it")
check(A.delete(B + f"{K}/statements/{SID}").status_code == 409, "the statement stays while receipts hang on it")
check(A.post(B + f"{K}/lines/{L[0]['id']}/unmatch").ok, "taken back")
check(sql("SELECT paid_at FROM rc_receipts WHERE node_id=?", (CAFE,))[0][0] is None, "the payment day goes with it")
assert A.post(B + f"{K}/lines/{L[0]['id']}/match", json={"node_id": CAFE}).ok
assert A.delete(B + f"/api/files/nodes/{CAFE}").ok
check(sheet(A, SID)["lines"][0]["gone"] is True, "a document in the trash shows as gone")
assert A.post(B + f"/api/files/nodes/{CAFE}/restore").ok

# ---- private, the bank
r = A.patch(B + f"{K}/lines/{L[3]['id']}", json={"state": "noreceipt"})
check(r.ok and r.json()["line"]["state"] == "noreceipt", "no receipt needed by hand")
r = A.patch(B + f"{K}/lines/{L[1]['id']}", json={"state": "private"})
check(r.ok and r.json()["statement"]["private"] == "18.40", f"the private sum the holder pays back {r.text[:300]}")


def camt(entries):
    return ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>S</Id>'
            '<Acct><Id><IBAN>DE02120300000000202051</IBAN></Id><Ccy>EUR</Ccy></Acct>' + "".join(entries) + '</Stmt></BkToCstmrStmt></Document>')


def ntry(amt, day, ref):
    return (f'<Ntry><Amt Ccy="EUR">{amt}</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{day}</Dt></BookgDt><AcctSvcrRef>{ref}</AcctSvcrRef>'
            f'<NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>Beispielbank Kartenservice</Nm></Pty></Cdtr></RltdPties><RmtInf><Ustrd>Buchung {ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>')


assert A.post(B + O + "/bank/import", json={"text": camt([ntry("56.22", f"{Y}-01-20", "C-1"), ntry("56.23", f"{Y}-01-21", "C-2")]), "filename": "k.xml"}).status_code == 201
TX = {t["purpose"]: t["id"] for t in A.get(B + O + "/bank/tx?state=all").json()["items"]}
c = A.get(B + f"{K}/statements/{SID}/bank").json()["items"]
check(c[0]["id"] == TX["Buchung C-1"] and c[0]["fits"] is True, f"the booking of the fitting total first {c}")
check(any(x["kind"] == "card" and x["id"] == SID for x in A.get(B + O + f"/bank/tx/{TX['Buchung C-1']}/candidates").json()["items"]), "the bank's own list offers the statement")
check(A.post(B + O + f"/bank/tx/{TX['Buchung C-2']}/match", json={"kind": "card", "id": SID}).status_code == 409, "the sum is checked")
n0 = A.get(B + O + "/bank/noreceipt/count").json()["out"]
r = A.post(B + O + f"/bank/tx/{TX['Buchung C-1']}/match", json={"kind": "card", "id": SID})
check(r.ok and r.json()["match"]["kind"] == "card" and r.json()["match"]["label"] == f"{J} ·· 4711", f"the booking matched {r.text[:300]}")
check(A.get(B + O + "/bank/noreceipt/count").json()["out"] == n0 - 1, "it left the bookings without a receipt")
check(sheet(A, SID)["statement"]["bank"]["id"] == TX["Buchung C-1"], "the statement knows its booking")
check(A.post(B + O + f"/bank/tx/{TX['Buchung C-2']}/match", json={"kind": "card", "id": SID, "accept_diff": True}).status_code == 409, "one booking per statement")
check(A.post(B + O + f"/bank/tx/{TX['Buchung C-2']}/match", json={"kind": "card", "id": 999999, "accept_diff": True}).status_code == 404, "a statement of nobody 404")
r = A.post(B + O + f"/bank/tx/{TX['Buchung C-1']}/unmatch")
check(r.ok and r.json()["was"] == {"kind": "card", "id": SID}, "undone through the bank's route")
check(A.get(B + O + "/bank/noreceipt/count").json()["out"] == n0, "the booking is back on the list")
assert A.post(B + O + f"/bank/tx/{TX['Buchung C-1']}/match", json={"kind": "card", "id": SID}).ok
BANK_R = doc(A, "bank-receipt.pdf", "1.00", f"{Y}-01-20")
assert A.put(B + f"/api/docs/{BANK_R}/receipt", json={"keep": True}).ok
assert A.post(B + f"{K}/lines/{ML}/match", json={"node_id": BANK_R}).ok
check(A.post(B + O + f"/bank/tx/{TX['Buchung C-2']}/match", json={"kind": "receipt", "id": BANK_R}).status_code == 409, "a receipt paid by card is no bank booking's receipt")

# ---- the holder, the others
it = Bo.get(B + K).json()
check([k["id"] for k in it["items"]] == [CARD] and it["manage"] is False and "people" not in it, f"the holder sees only their own card {it}")
check(Bo.get(B + O + "/settings").json().get("cards") is True, "the menu knows the holder")
check(A.get(B + O + "/settings").json().get("cards") is False, "an admin without a card")
check(Bo.get(B + f"{K}/{CARD2}/statements").status_code == 404, "somebody else's card 404")
check(Bo.get(B + f"{K}/statements/{MS}").status_code == 404, "somebody else's statement 404")
check(Bo.patch(B + f"{K}/lines/{ML}", json={"state": "private"}).status_code == 404, "somebody else's position 404")
check(Bo.get(B + f"{K}/statements/{SID}/file").content[:5] == b"%PDF-", "the holder reads the statement the admin uploaded")
check(Bo.post(B + K, json={"holder_id": BOB, "last4": "1111"}).status_code == 403, "a holder makes no cards")
check(Bo.patch(B + f"{K}/{CARD}", json={"last4": "1111"}).status_code == 403, "nor changes them")
check(Bo.delete(B + f"{K}/{CARD}").status_code == 403, "nor deletes them")
check(Bo.get(B + f"{K}/statements/{SID}/bank").status_code == 403, "nor sees the bank")
check(Bo.get(B + K + "/reminder").status_code == 403, "nor the reminder's settings")
rc = Bo.post(B + f"{K}/lines/{L[0]['id']}/unmatch")
check(rc.ok, f"the holder works on their own position {rc.text[:200]}")
r = Bo.post(B + f"{K}/lines/{L[0]['id']}/upload", files={"file": ("beleg.pdf", pdf(["Beleg des Inhabers"]), "application/pdf")})
check(r.status_code == 201 and r.json()["line"]["state"] == "matched", f"the holder uploads the receipt, matched at once {r.text[:300]}")
nid = r.json()["node_id"]
check(sql("SELECT paid_at FROM rc_receipts WHERE node_id=?", (nid,))[0][0] == f"{Y - 1}-12-28", "a receipt with its payment day")
check(all(x["id"] != CAFE for x in Bo.get(B + f"{K}/lines/{L[4]['id']}/candidates?q=cafe").json()["items"]), "a holder finds only documents they see")
check(Ca.get(B + K).json()["items"] == [], "another organisation sees no card")
for path in (f"{K}/{CARD}/statements", f"{K}/statements/{SID}", f"{K}/statements/{SID}/file", f"{K}/lines/{L[0]['id']}/candidates"):
    check(Ca.get(B + path).status_code == 404, f"another organisation 404: {path}")
check(Ca.patch(B + f"{K}/{CARD}", json={"last4": "1111"}).status_code == 404, "another organisation cannot change the card")
check(Ca.post(B + O + "/bank/tx/1/match", json={"kind": "card", "id": SID}).status_code == 404, "another organisation's statement")

# ---- the reminder
S2 = up(A, CARD, pdf([f"Abrechnung vom 15.03.{Y}", "02.03. 02.03. Laden Beispiel 7,00-", "Neuer Saldo 7,00-"])).json()["statement"]["id"]
assert A.post(B + f"{K}/statements/{S2}/confirm", json={}).ok
r = A.put(B + K + "/reminder", json={"every": "week"})
check(r.ok and r.json()["count"] >= 1, f"the reminder on {r.text[:200]}")
tk = sql("SELECT id, title, status FROM tasks WHERE assignee_id=? AND url LIKE '%#office/cards'", (BOB,))
check(len(tk) == 1 and tk[0][1] == "1 card position without a receipt" and tk[0][2] == 0, f"one task for the holder {tk}")
check(A.put(B + K + "/reminder", json={"every": "bad"}).status_code == 400, "a wrong rhythm 400")
ln = sheet(A, S2)["lines"][0]["id"]
assert Bo.patch(B + f"{K}/lines/{ln}", json={"state": "private"}).ok
assert A.put(B + K + "/reminder", json={"user": ALICE}).ok
check(sql("SELECT status FROM tasks WHERE id=?", (tk[0][0],))[0][0] != 0, "done by itself once nothing is open")
assert A.put(B + K + "/reminder", json={"every": "off"}).ok

# ---- exports
r = A.get(B + O + f"/books/export?from={Y - 1}-12-01&to={Y}-03-31")
rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿")), delimiter=";" if ";" in r.text.splitlines()[0] else ","))
cards = [x for x in rows if "Credit card" in x[0]]
check(len(cards) >= 6, f"the positions and statements in the neutral export ({len(cards)})")
r = A.get(B + O + f"/books/export?from={Y - 1}-12-01&to={Y}-03-31&zip=1")
names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
check(sum(n.startswith("cards/") for n in names) >= 3, f"the statements and receipts in the ZIP {names[:12]}")
r = A.get(B + O + f"/datev/extf?from={Y}-01-01&to={Y}-03-31")
check(r.ok and "1730" in r.text, f"DATEV: the card account {r.status_code}")
check("1800" in r.text, "DATEV: the private account")
r = A.get(B + O + f"/datev/zip?from={Y}-01-01&to={Y}-03-31&check=1").json()
check(r["files"] >= 1, f"DATEV: the statement as receipt image {r}")
r = A.put(B + O + "/settings", json={"datev_extf": {"card": "1732"}})
check(r.ok, "the card account can be set")
check("1732" in A.get(B + O + f"/datev/extf?from={Y}-01-01&to={Y}-03-31").text, "and is used")
check(A.put(B + O + "/settings", json={"datev_extf": {"card": "abc"}}).status_code == 400, "digits only")

# ---- a card out of the list, the undo
check(A.delete(B + f"{K}/{CARD2}").ok and all(k["id"] != CARD2 for k in A.get(B + K).json()["items"]), "a card leaves the list")
check(A.post(B + f"{K}/{CARD2}/restore").ok, "and comes back")

# ---- a person without an organisation (their own admin)
FID, Fr = freelancer(B, A, "frida")
r = Fr.post(B + K, json={"holder_id": FID, "last4": "1234"})
check(r.status_code == 201 and r.json()["holder"] == "Frida", f"a card in the personal office {r.text[:200]}")
FC = r.json()["id"]
check(Fr.post(B + K, json={"holder_id": BOB, "last4": "1234"}).status_code == 400, "only the owner is a person there")
check(Fr.post(B + K, json={"holder_name": "Partnerin", "last4": "2222"}).status_code == 201, "or a free name")
r = up(Fr, FC, pdf(LINES))
check(r.status_code == 201 and r.json()["read"] is True, f"the statement read there {r.text[:200]}")
FS = r.json()["statement"]["id"]
fl = sheet(Fr, FS)["lines"]
assert Fr.post(B + f"{K}/statements/{FS}/confirm", json={}).ok
fd = doc(Fr, "fruehstueck.pdf", "12.50", f"{Y - 1}-12-28", ws="private")
check(Fr.get(B + f"{K}/lines/{fl[0]['id']}/candidates").json()["items"][0]["id"] == fd, "the search in the personal office")
check(Fr.post(B + f"{K}/lines/{fl[0]['id']}/match", json={"node_id": fd}).ok, "the match there")
check(Fr.put(B + K + "/reminder", json={"every": "month"}).ok, "the reminder there")
check(A.get(B + f"{K}/statements/{FS}").status_code == 404, "nobody else sees it")
check(Fr.get(B + O + f"/books/export?from={Y - 1}-12-01&to={Y}-03-31").text.count("Credit card") >= 2, "the export there")
check(Fr.get(B + K + "/reminder").json()["every"] == "month", "reads back")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
