#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.603.0 (#4927) API tests: the basis of the income statement per year -- "receipts" (as before) or "bank and cash" (strict),
the same data in both. Own container (start.sh, org encryption on). Invented companies, people and figures only.
Data of the year before (Y): R1 119.00 at 19 % paid by bank; R2 59.50 at 19 % without a bank line; a bank line of 30.00 without
a receipt; 500.00 private; 200.00 withdrawn into the cash box (match kind cash), out of it R3 23.80 at 19 % and 10.00 without a
receipt; a meal (gross 150.40) paid by a bank line without a receipt and linked to it; a card statement of 32.50 (cafe 12.50 at
7 % with its receipt, 20.00 open) whose bank total of 33.00 differs. This year: invoice 1 (1190.00) paid through the bank,
invoice 2 (595.00) paid by hand, 50.00 received without an invoice.
 - setting: default receipts, GET / PUT /api/office/books/basis, a later year inherits, 400 on a wrong value
 - receipts: exactly the figures of before (R1 + R2 + R3 + meal + cafe; both invoices; bank lines without receipt count nowhere)
 - bank and cash: R2 open (not counted, open_receipts), bookings without receipt as their own line with the warning, private /
   cash withdrawal / card total no expense, cash book and card positions are the expenses, the meal counts once through its line
   (the line leaves the bookings without receipt), only the bank-paid invoice + the money received without invoice, the card
   difference warned; VAT figures (field 66, field 81) alike
 - a year with a locked month keeps its basis (409); the meal link: one meal per line (409), taken off again
 - a person without an organisation (freelancer-matrix: office): the same in the personal office
usage: p2603_c_euer_basis_test.py <datadir>"""
import base64
import os
import subprocess
import sys
from datetime import date

import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, B, H, DATA, check, sess, until  # noqa: E402

KEY = base64.b64encode(os.urandom(32)).decode()
O = "/api/office"
K = O + "/cards"
FEAT = "cal,comments,collab,office,clients,docs"
TODAY = testclock.today()
Y = TODAY.year - 1
T0 = TODAY.isoformat()


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


if not os.environ.get("P2603C_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)


def _up():
    try:
        return s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"})
    except requests.ConnectionError:
        return None


r = until(_up, 30)  # the server is up once setup answers (a real state, not a fixed time)
assert r is not None and r.ok, r and r.text
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})


def camt(entries):
    return ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>S</Id>'
            '<Acct><Id><IBAN>DE02120300000000202051</IBAN></Id><Ccy>EUR</Ccy></Acct>' + "".join(entries) + '</Stmt></BkToCstmrStmt></Document>')


def ntry(amt, day, ref, cd="DBIT"):
    who = "Dbtr" if cd == "CRDT" else "Cdtr"
    return (f'<Ntry><Amt Ccy="EUR">{amt}</Amt><CdtDbtInd>{cd}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{day}</Dt></BookgDt><AcctSvcrRef>{ref}</AcctSvcrRef>'
            f'<NtryDtls><TxDtls><RltdPties><{who}><Pty><Nm>Partner {ref}</Nm></Pty></{who}></RltdPties><RmtInf><Ustrd>Buchung {ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>')


def doc(s, ws, name, amount, day, vat=None):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, pdf(["Rechnung " + name]), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 30)
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    if vat is not None:
        r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Material", "vat_pct": vat, "keep": True})
        assert r.ok, r.text
    return nid


def invoice(s, cl, rate):
    r = s.post(B + O + "/docs", json={"kind": "invoice", "client_id": cl, "project_title": f"Job {rate}", "service_from": T0,
                                       "items": [{"title": "Schnitt", "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + O + f"/docs/{did}/finalize")
    assert r.ok, r.text
    return did, s.get(B + O + f"/docs/{did}").json()["totals"]["gross"]


def meal(host, day):
    return {"date": day, "place_name": "Trattoria Esempio", "place_address": "Beispielweg 1\n12345 Musterstadt",
            "occasion": "Negotiation of the follow-up order for the spring campaign", "host": {"id": host},
            "guests": [{"name": "Gina Gast", "extra": "Example GmbH, buyer"}],
            "amounts": [{"kind": "food", "rate": 19, "gross": "119.00"}, {"kind": "drinks", "rate": 7, "gross": "21.40"}], "tip": "10"}


def line(eu, key):
    return next((x for x in eu.get("expenses", []) if x["key"] == key), None)


def inc(eu, key):
    return next((x for x in eu.get("income", []) if x["key"] == key), None)


def office(s, who, ws, me):
    """The whole flow in the office s works in (an organisation or the personal office)."""
    check(s.put(B + O + "/settings", json={"lang": "de", "currency": "EUR",
                                           "company_fields": {"name": f"{who} Beispiel GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
                                                              "tax_number": "12/345/67890", "iban": "DE02120300000000202051"}}).ok,
          f"{who}: office settings")
    b = s.get(B + O + f"/books/basis?year={Y}").json()
    check(b.get("basis") == "receipts" and b.get("years") == {} and b.get("locked") is False, f"{who}: the default is receipts {b}")
    check(s.put(B + O + "/books/basis", json={"year": Y, "basis": "nonsense"}).status_code == 400, f"{who}: a wrong basis 400")
    # ---- the data
    r1 = doc(s, ws, "r1-material.pdf", "119.00", f"{Y}-03-10", "19")
    r2 = doc(s, ws, "r2-ohne-bank.pdf", "59.50", f"{Y}-04-01", "19")
    r3 = doc(s, ws, "r3-kasse.pdf", "23.80", f"{Y}-06-02", "19")
    cafe = doc(s, ws, "cafe-beispiel.pdf", "12.50", f"{Y}-10-02", "7")
    cl = s.post(B + "/api/clients", json={"name": f"{who} Kunde GmbH", "street": "Kundenweg 2", "zip": "54321", "city": "Kundenstadt", "country": "DE"}).json()["id"]
    i1, g1 = invoice(s, cl, 1000)
    i2, g2 = invoice(s, cl, 500)
    check(str(g1) in ("1190.0", "1190.00", "1190") and str(g2) in ("595.0", "595.00", "595"), f"{who}: the invoices {g1} {g2}")
    xml = camt([ntry("119.00", f"{Y}-03-12", "R1"), ntry("30.00", f"{Y}-05-05", "NOREC"), ntry("500.00", f"{Y}-05-20", "PRIV"),
                ntry("200.00", f"{Y}-06-01", "CASH"), ntry("150.40", f"{Y}-09-10", "MEAL"), ntry("33.00", f"{Y}-10-20", "CARD"),
                ntry("1190.00", T0, "INV1", "CRDT"), ntry("50.00", T0, "IN50", "CRDT")])
    r = s.post(B + O + "/bank/import", json={"text": xml, "filename": "konto.xml"})
    check(r.status_code == 201, f"{who}: bank import {r.status_code} {r.text[:200]}")
    tx = {t["purpose"].split()[-1]: t["id"] for t in s.get(B + O + "/bank/tx?state=all").json()["items"]}
    m = lambda tid, b: s.post(B + O + f"/bank/tx/{tid}/match", json=b)  # noqa: E731
    check(m(tx["R1"], {"kind": "receipt", "id": r1}).ok, f"{who}: R1 matched with its bank line")
    check(m(tx["PRIV"], {"kind": "private"}).ok, f"{who}: private withdrawal")
    r = m(tx["CASH"], {"kind": "cash"})
    check(r.ok and r.json().get("match", {}).get("kind") == "cash", f"{who}: the cash withdrawal is a cash box transfer {r.text[:200]}")
    check(m(tx["INV1"], {"kind": "invoice", "id": i1}).ok, f"{who}: invoice 1 paid through the bank")
    check(s.post(B + O + f"/docs/{i2}/payments", json={"date": T0, "amount": g2, "method": "transfer"}).ok, f"{who}: invoice 2 paid by hand")
    # the cash book: a box of its own from the first of Y
    r = s.post(B + O + "/cashbooks", json={"name": "Handkasse", "opening": "0.00", "opening_day": f"{Y}-01-01"})
    check(r.status_code == 201, f"{who}: a cash box {r.text[:200]}")
    bid = r.json()["id"]
    E = O + f"/cashbooks/{bid}/entries"
    check(s.post(B + E, json={"day": f"{Y}-06-01", "dir": "in", "amount": "200.00", "text": "Barentnahme"}).status_code == 201, f"{who}: cash in from the bank")
    check(s.post(B + E, json={"day": f"{Y}-06-02", "dir": "out", "amount": "23.80", "vat_pct": "19", "text": "Material", "node_id": r3}).status_code == 201,
          f"{who}: cash out with its receipt")
    check(s.post(B + E, json={"day": f"{Y}-06-03", "dir": "out", "amount": "10.00", "text": "Parkschein"}).status_code == 201, f"{who}: cash out without a receipt")
    # the meal, linked to its bank line
    r = s.post(B + O + "/meals", json=meal(me, f"{Y}-09-08"))
    check(r.status_code == 201, f"{who}: a meal {r.text[:200]}")
    mid = r.json()["id"]
    check(s.post(B + O + f"/meals/{mid}/approve").ok, f"{who}: meal approved")
    p = s.get(B + O + f"/meals/{mid}/payment").json()
    check(p["current"] is None and p["candidates"] and p["candidates"][0]["kind"] == "bank" and p["candidates"][0]["id"] == tx["MEAL"],
          f"{who}: the bank line of the same amount is offered first {p}")
    r = s.put(B + O + f"/meals/{mid}/payment", json={"kind": "bank", "id": tx["MEAL"]})
    check(r.ok and r.json()["current"]["amount"] == "150.40", f"{who}: an approved meal takes its line {r.text[:200]}")
    r = s.post(B + O + "/meals", json=meal(me, f"{Y}-09-09"))
    mid2 = r.json()["id"]
    check(s.put(B + O + f"/meals/{mid2}/payment", json={"kind": "bank", "id": tx["MEAL"]}).status_code == 409, f"{who}: one meal per line")
    check(s.put(B + O + f"/meals/{mid2}/payment", json={"kind": "bank", "id": 99999999}).status_code == 404, f"{who}: a line of nobody 404")
    check(s.delete(B + O + f"/meals/{mid2}").ok, f"{who}: the draft goes")
    # the card: a statement of October, the cafe with its receipt, 20.00 open, the bank total 33.00 differs
    r = s.post(B + K, json={"holder_id": me, "last4": "4711", "account": "DE02120300000000202051"})
    check(r.status_code == 201, f"{who}: a card {r.text[:200]}")
    card = r.json()["id"]
    lines = [f"Kreditkartenabrechnung vom 15.10.{Y}", "Beispielbank Mastercard Business", "Karte 5232 12XX XXXX 4711", "Saldo Vormonat 0,00",
             "02.10. 02.10. Cafe Beispiel Berlin 12,50-", "05.10. 05.10. Buchhandlung Beispiel 20,00-", "Neuer Saldo 32,50-"]
    r = s.post(B + f"{K}/{card}/statements", files={"file": ("stmt.pdf", pdf(lines), "application/pdf")})
    check(r.status_code == 201, f"{who}: statement read {r.text[:300]}")
    sid = r.json()["statement"]["id"]
    cl_ = s.get(B + f"{K}/statements/{sid}").json()["lines"]
    check([x["amount"] for x in cl_] == ["12.50", "20.00"], f"{who}: two positions {[(x['merchant'], x['amount']) for x in cl_]}")
    check(s.post(B + f"{K}/statements/{sid}/confirm", json={}).ok, f"{who}: statement confirmed")
    check(s.post(B + f"{K}/lines/{cl_[0]['id']}/match", json={"node_id": cafe}).ok, f"{who}: the cafe position takes its receipt")
    check(m(tx["CARD"], {"kind": "card", "id": sid, "accept_diff": True}).ok, f"{who}: the bank total of the card, the difference accepted")

    # ---- basis receipts: the figures of before
    eu = s.get(B + O + f"/books/euer?year={Y}").json()
    check(eu.get("basis") == "receipts" and eu.get("warnings") is None, f"{who}: receipts: the basis named, no warnings {eu.get('basis')}")
    check(eu["expense_total"]["net"] == "272.68" and eu["expense_total"]["vat"] == "53.52",
          f"{who}: receipts: R1 + R2 + R3 + meal 70 % + cafe {eu['expense_total']} {eu['expenses']}")
    check(line(eu, "b:") is None and line(eu, "n:") is None and line(eu, "m:")["net"] == "91.00", f"{who}: receipts: no booking line, the meal of its own")
    check(any("twice" in n for n in eu["notes"]), f"{who}: receipts: the double-count hint of the meals {eu['notes']}")
    u = s.get(B + O + f"/books/ustva?year={Y}&period=y").json()
    check(u["kz"]["66"] == "53.52" and u.get("euer_basis") == "receipts", f"{who}: receipts: field 66 {u['kz']['66']}")
    ei = s.get(B + O + f"/books/euer?year={TODAY.year}").json()
    check(inc(ei, "vat19") and inc(ei, "vat19")["net"] == "1500.00" and inc(ei, "bank") is None, f"{who}: receipts: both invoices count {ei['income']}")

    # ---- basis bank and cash (from Y on: this year inherits)
    r = s.put(B + O + "/books/basis", json={"year": Y, "basis": "bank"})
    check(r.ok and r.json()["basis"] == "bank" and r.json()["years"] == {str(Y): "bank"}, f"{who}: bank and cash from {Y} {r.text[:200]}")
    check(s.get(B + O + f"/books/basis?year={TODAY.year}").json()["basis"] == "bank", f"{who}: the next year inherits")
    check(s.get(B + O + f"/books/basis?year={Y - 1}").json()["basis"] == "receipts", f"{who}: the year before stays")
    eu = s.get(B + O + f"/books/euer?year={Y}").json()
    w = eu.get("warnings") or {}
    check(eu.get("basis") == "bank", f"{who}: strict: the basis named {eu.get('basis')}")
    check(eu["expense_total"]["net"] == "282.68" and eu["expense_total"]["vat"] == "44.02",
          f"{who}: strict: R1 + R3 (cash) + meal + cafe (card) + 60.00 without receipt, R2 open {eu['expense_total']} {eu['expenses']}")
    b = line(eu, "b:")
    check(b and (b["net"], b["vat"], b["count"]) == ("60.00", "0.00", 3), f"{who}: strict: bank 30 + cash 10 + card 20 without receipt, no input tax {b}")
    check(w.get("missing_count") == 3 and {x["amount"] for x in w.get("missing_receipt", [])} == {"30.00", "10.00", "20.00"},
          f"{who}: strict: the warning 'receipt missing' names them (not the meal's line) {w.get('missing_receipt')}")
    check(w.get("open_receipts") == 1, f"{who}: strict: R2 is open and does not count {w.get('open_receipts')}")
    check(len(w.get("card_diff") or []) == 1 and w["card_diff"][0]["booking"] == "33.00" and w["card_diff"][0]["statement"] == "32.50",
          f"{who}: strict: the card total differs {w.get('card_diff')}")
    mm = line(eu, "m:")
    check(mm and (mm["net"], mm["vat"], mm["count"]) == ("91.00", "20.40", 1), f"{who}: strict: the meal counts once through its line {mm}")
    check(any("never as an expense of their own" in n for n in eu["notes"]), f"{who}: strict: the meal note {eu['notes']}")
    check(any("bank and cash (strict)" in n for n in eu["notes"]), f"{who}: strict: the basis note")
    u = s.get(B + O + f"/books/ustva?year={Y}&period=y").json()
    check(u["kz"]["66"] == "44.02" and u.get("euer_basis") == "bank", f"{who}: strict: field 66 without R2 {u['kz']['66']}")
    ei = s.get(B + O + f"/books/euer?year={TODAY.year}").json()
    wi = ei.get("warnings") or {}
    check(inc(ei, "vat19") and inc(ei, "vat19")["net"] == "1000.00" and inc(ei, "bank") and inc(ei, "bank")["net"] == "50.00",
          f"{who}: strict: only the bank-paid invoice + 50.00 without invoice {ei['income']}")
    check(wi.get("payments_outside") == 1 and len(wi.get("income_open") or []) == 1, f"{who}: strict: the warnings of the income {wi}")
    ui = s.get(B + O + f"/books/ustva?year={TODAY.year}&period=y").json()
    check(ui["kz"]["81"] == "1000", f"{who}: strict: field 81 only of the bank payment (cash basis) {ui['kz']['81']}")
    # the cash flow follows (the bank line without receipt is money out)
    cf = s.get(B + O + f"/cashflow?from={Y}-05&months=1").json()
    check(any(e["kind"] == "norc" and e["amount"] == "30.00" for e in cf.get("entries", [])), f"{who}: strict: the cash flow has the booking without receipt")
    # taking the meal's line off: the line is a booking without receipt again, the meal does not count
    check(s.put(B + O + f"/meals/{mid}/payment", json={"kind": None}).ok, f"{who}: the link taken off")
    eu2 = s.get(B + O + f"/books/euer?year={Y}").json()
    check(line(eu2, "m:") is None and line(eu2, "b:")["net"] == "210.40", f"{who}: strict: no line, no meal; the line counts without receipt {line(eu2, 'b:')}")
    check(s.put(B + O + f"/meals/{mid}/payment", json={"kind": "bank", "id": tx["MEAL"]}).ok, f"{who}: linked again")
    # ---- a locked month keeps the basis of its year
    r = s.post(B + O + "/periods/lock", json={"through": f"{Y}-01", "confirm": f"01/{Y}"})
    check(r.ok, f"{who}: January of {Y} locked {r.text[:200]}")
    r = s.put(B + O + "/books/basis", json={"year": Y, "basis": "receipts"})
    check(r.status_code == 409 and str(Y) in r.text, f"{who}: a year with a locked month keeps its basis {r.status_code} {r.text[:200]}")
    check(s.get(B + O + f"/books/basis?year={Y}").json()["locked"] is True, f"{who}: the year shows as locked")
    check(s.put(B + O + "/books/basis", json={"year": Y, "basis": "bank"}).ok, f"{who}: the same basis again is fine")
    check(s.put(B + O + "/books/basis", json={"year": TODAY.year, "basis": "receipts"}).ok, f"{who}: the open year may change")
    ei = s.get(B + O + f"/books/euer?year={TODAY.year}").json()
    check(inc(ei, "vat19")["net"] == "1500.00" and ei.get("basis") == "receipts", f"{who}: this year by receipts again")
    check(s.get(B + O + f"/books/euer?year={Y}").json().get("basis") == "bank", f"{who}: {Y} stays bank and cash")
    return mid


MID = office(A, "org", f"org:{ORG}", ALICE)

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
office(Fr, "freelancer", "private", FID)
# tenant-matrix: office -- the meal of another office area: 404, never its line
check(Fr.get(B + O + f"/meals/{MID}/payment").status_code == 404, "another office's meal: 404")
check(Fr.put(B + O + f"/meals/{MID}/payment", json={"kind": None}).status_code == 404, "another office's meal cannot be unlinked: 404")
check(A.get(B + O + f"/meals/{MID}/payment").json()["current"]["kind"] == "bank", "the organisation's link stays")
check(A.get(B + O + f"/books/basis?year={Y}").json()["years"] == {str(Y): "bank", str(TODAY.year): "receipts"}, "the organisation keeps its own setting")

print(f"p2603_c_euer_basis: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
