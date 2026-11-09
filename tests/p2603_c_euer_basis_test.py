#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.603.0 (#4927) API tests: the basis of the income statement per year -- "receipts" (as before) or "bank and cash" (strict),
the same data in both (2.610.0, #4932: the neutral export and the DATEV hints follow). Own container (start.sh, org encryption on). Invented companies, people and figures only.
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
 - 2.755.0 (#5241): the input tax (field 66) where a receipts year meets a strict one: the day of the bank line decides, every
   receipt exactly once over the years (both directions); a receipts year away from the edge keeps the document date
 - 2.764.0 (#5313): the same for the entertainment receipts (their line's day at the edge) and a travel receipt dated in the year
   before its trip (counts in its own year, once)
 - a person without an organisation (freelancer-matrix: office): the same in the personal office
 - 2.743.0 (#4937): the basis changes at the turn of the year (both ways): a receipt with its line in the other year counts once,
   in the neutral and the DATEV export and in the EUeR (also a cash line without paid_at), and is not open
usage: p2603_c_euer_basis_test.py <datadir>"""
import base64
import csv
import io
import os
import subprocess
import sys
import zipfile
from datetime import date

import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import CT, FAILS, OKS, B, H, DATA, check, sess, until  # noqa: E402

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


def bx(s, frm, to):
    """2.610.0 (#4932): the neutral export of [frm, to] -> (check, [(type, gross)] of the CSV, missing.txt of the ZIP)."""
    q = f"{O}/books/export?from={frm}&to={to}"
    chk = s.get(B + q + "&check=1").json()
    txt = s.get(B + q).content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(txt), delimiter=";" if ";" in txt.splitlines()[0] else ","))[1:]
    z = zipfile.ZipFile(io.BytesIO(s.get(B + q + "&zip=1").content))
    miss = "".join(z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".txt"))
    return chk, [(r[0], r[9].replace(",", ".")) for r in rows], miss


def bx_rows(s, frm, to):
    """2.743.0 (#4937): the raw rows of the neutral export CSV of [frm, to] (once() matches type, gross and title)."""
    txt = s.get(B + f"{O}/books/export?from={frm}&to={to}").content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(txt), delimiter=";" if ";" in txt.splitlines()[0] else ","))[1:]


def once(s, who, what, gross, title, years):
    """2.743.0 (#4937): a receipt counts exactly once over the years: the neutral export (its gross) and the DATEV batch (its
    title) of each year -> {year: count}, both the same."""
    nb, nd = {}, {}
    for y in years:
        # by gross AND title: E3 of #5241 has the same gross on the same day as R5
        nb[y] = sum(1 for r in bx_rows(s, f"{y}-01-01", f"{y}-12-31")
                    if r[0] in ("Receipt", "Beleg") and r[9].replace(",", ".") == gross and any(title in x for x in r))
        r = s.get(B + O + f"/datev/extf?from={y}-01-01&to={y}-12-31")
        nd[y] = sum(1 for x in r.content.decode("cp1252").splitlines() if title in x) if r.ok else -1  # booking lines naming it
    check(sum(nb.values()) == 1 and nb == nd, f"{who}: #4937 {what}: once over the years, neutral {nb} DATEV {nd}")
    return nb


def dv_hints(s, frm, to):
    r = s.get(B + O + f"/datev/extf?from={frm}&to={to}&check=1")
    return {h["key"]: h for h in r.json().get("hints", [])} if r.ok else {"_error": r.text[:200]}


def office(s, who, ws, me):
    """The whole flow in the office s works in (an organisation or the personal office)."""
    check(s.put(B + O + "/settings", json={"lang": "de", "currency": "EUR",
                                           "company_fields": {"name": f"{who} Beispiel GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE",
                                                              "tax_number": "12/345/67890", "iban": "DE02120300000000202051"}}).ok,
          f"{who}: office settings")
    b = s.get(B + f"/api/office/books/basis?year={Y}").json()
    check(b.get("basis") == "receipts" and b.get("years") == {} and b.get("locked") is False, f"{who}: the default is receipts {b}")
    check(s.put(B + "/api/office/books/basis", json={"year": Y, "basis": "nonsense"}).status_code == 400, f"{who}: a wrong basis 400")
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
    p = s.get(B + f"/api/office/meals/{mid}/payment").json()
    check(p["current"] is None and p["candidates"] and p["candidates"][0]["kind"] == "bank" and p["candidates"][0]["id"] == tx["MEAL"],
          f"{who}: the bank line of the same amount is offered first {p}")
    r = s.put(B + f"/api/office/meals/{mid}/payment", json={"kind": "bank", "id": tx["MEAL"]})
    check(r.ok and r.json()["current"]["amount"] == "150.40", f"{who}: an approved meal takes its line {r.text[:200]}")
    r = s.post(B + O + "/meals", json=meal(me, f"{Y}-09-09"))
    mid2 = r.json()["id"]
    check(s.put(B + f"/api/office/meals/{mid2}/payment", json={"kind": "bank", "id": tx["MEAL"]}).status_code == 409, f"{who}: one meal per line")
    check(s.put(B + f"/api/office/meals/{mid2}/payment", json={"kind": "bank", "id": 99999999}).status_code == 404, f"{who}: a line of nobody 404")
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
    # 2.610.0 (#4932): the neutral export by receipts as before (all four receipts, no rows of the bank lines, nothing open)
    check(s.put(B + O + "/settings", json={"datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}}).ok,
          f"{who}: DATEV numbers")
    chk, rows, miss = bx(s, f"{Y}-01-01", f"{Y}-12-31")
    check(chk.get("receipts") == 4 and chk.get("open") == 0 and chk.get("outside") == 0, f"{who}: export receipts: all four receipts {chk}")
    check(not any(t in ("Booking", "Buchung") for t, _ in rows), f"{who}: export receipts: no booking rows {rows}")
    check("open_strict" not in dv_hints(s, f"{Y}-01-01", f"{Y}-12-31"), f"{who}: DATEV receipts: no open-receipt hint")

    # ---- basis bank and cash (from Y on: this year inherits)
    r = s.put(B + "/api/office/books/basis", json={"year": Y, "basis": "bank"})
    check(r.ok and r.json()["basis"] == "bank" and r.json()["years"] == {str(Y): "bank"}, f"{who}: bank and cash from {Y} {r.text[:200]}")
    check(s.get(B + f"/api/office/books/basis?year={TODAY.year}").json()["basis"] == "bank", f"{who}: the next year inherits")
    check(s.get(B + f"/api/office/books/basis?year={Y - 1}").json()["basis"] == "receipts", f"{who}: the year before stays")
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
    # 2.610.0 (#4932): the neutral export follows the basis of the year: R1 (bank), R3 (cash), cafe (card); R2 open and named;
    # the bank line 30.00 and the cash entry 10.00 without receipt as booking rows; the meal once through its line (70 / 30)
    chk, rows, miss = bx(s, f"{Y}-01-01", f"{Y}-12-31")
    check(chk.get("receipts") == 3 and chk.get("open") == 1, f"{who}: export strict: three receipts with their line, R2 open {chk}")
    bk = sorted(g for t, g in rows if t in ("Booking", "Buchung"))
    check(bk == ["-10.00", "-30.00"], f"{who}: export strict: the bank / cash lines without receipt (not the meal's line) {bk} {rows}")
    rec = sorted(g for t, g in rows if t in ("Receipt", "Beleg"))
    check(rec == ["-119.00", "-12.50", "-23.80"], f"{who}: export strict: the receipts with the amounts of their lines {rec}")
    ml = [g for t, g in rows if t in ("Entertainment receipt", "Bewirtungsbeleg")]
    check(len(ml) == 4 and round(sum(float(x) for x in ml), 2) == -150.40, f"{who}: export strict: the meal once (70 / 30 of the bill, one row per VAT rate and the tip, #4563) {ml}")
    check("r2-ohne-bank.pdf" in miss, f"{who}: export strict: missing.txt names the open receipt {miss[:300]}")
    h = dv_hints(s, f"{Y}-01-01", f"{Y}-12-31")
    check(h.get("open_strict", {}).get("count") == 1 and r2 in h["open_strict"].get("ids", []), f"{who}: DATEV strict: the open receipt as a hint {h}")
    chk, rows, miss = bx(s, f"{TODAY.year}-01-01", T0)
    check(chk.get("outside") == 1 and sorted(g for t, g in rows if t in ("Payment", "Zahlung")) == ["1190.00"],
          f"{who}: export strict: only the bank-paid invoice, the payment by hand named {chk} {rows}")
    check([g for t, g in rows if t in ("Booking", "Buchung")] == ["50.00"], f"{who}: export strict: 50.00 received without invoice {rows}")
    check(i2 and "\n- " in miss and str(TODAY.year) in miss, f"{who}: export strict: missing.txt names the payment by hand {miss[:300]}")
    h = dv_hints(s, f"{TODAY.year}-01-01", T0)
    check(h.get("pay_outside", {}).get("count") == 1, f"{who}: DATEV strict: the payment by hand as a hint {h}")
    # taking the meal's line off: the line is a booking without receipt again, the meal does not count
    check(s.put(B + f"/api/office/meals/{mid}/payment", json={"kind": None}).ok, f"{who}: the link taken off")
    eu2 = s.get(B + O + f"/books/euer?year={Y}").json()
    check(line(eu2, "m:") is None and line(eu2, "b:")["net"] == "210.40", f"{who}: strict: no line, no meal; the line counts without receipt {line(eu2, 'b:')}")
    check(s.put(B + f"/api/office/meals/{mid}/payment", json={"kind": "bank", "id": tx["MEAL"]}).ok, f"{who}: linked again")
    # ---- 2.610.0 (#4932 review M1 / M2 / N3)
    # M1: a meal paid by card, its position without a receipt of its own (open): the meal's rows carry the amount, the position not
    lines = [f"Kreditkartenabrechnung vom 15.11.{Y}", "Beispielbank Mastercard Business", "Karte 5232 12XX XXXX 4711", "Saldo Vormonat 0,00",
             "08.11. 08.11. Trattoria Esempio 150,40-", "Neuer Saldo 150,40-"]
    r = s.post(B + f"{K}/{card}/statements", files={"file": ("stmt-nov.pdf", pdf(lines), "application/pdf")})
    check(r.status_code == 201, f"{who}: M1: the November statement read {r.text[:300]}")
    sid2 = r.json()["statement"]["id"]
    cl2 = s.get(B + f"{K}/statements/{sid2}").json()["lines"]
    check([x["amount"] for x in cl2] == ["150.40"], f"{who}: M1: one position {[(x['merchant'], x['amount']) for x in cl2]}")
    check(s.post(B + f"{K}/statements/{sid2}/confirm", json={}).ok, f"{who}: M1: statement confirmed")
    r = s.post(B + O + "/meals", json=meal(me, f"{Y}-11-08"))
    mid3 = r.json()["id"]
    check(s.post(B + O + f"/meals/{mid3}/approve").ok, f"{who}: M1: the second meal approved")
    r = s.put(B + f"/api/office/meals/{mid3}/payment", json={"kind": "card", "id": cl2[0]["id"]})
    check(r.ok and r.json()["current"]["amount"] == "150.40", f"{who}: M1: the meal takes the open card position {r.text[:200]}")
    # M2: R4 of 28.03. paid on 02.04., R5 of 28.12. paid on 01.01. of this year (both years "bank and cash")
    r4 = doc(s, ws, "r4-maerz-april.pdf", "35.70", f"{Y}-03-28", "19")
    r5 = doc(s, ws, "r5-dezember.pdf", "47.60", f"{Y}-12-28", "19")
    r = s.post(B + O + "/bank/import", json={"text": camt([ntry("35.70", f"{Y}-04-02", "RVIER"), ntry("47.60", f"{TODAY.year}-01-01", "RFUENF")]),
                                             "filename": "konto2.xml"})
    check(r.status_code == 201, f"{who}: M2: bank import {r.status_code} {r.text[:200]}")
    tx = {t["purpose"].split()[-1]: t["id"] for t in s.get(B + O + "/bank/tx?state=all").json()["items"]}
    check(m(tx["RVIER"], {"kind": "receipt", "id": r4}).ok and m(tx["RFUENF"], {"kind": "receipt", "id": r5}).ok, f"{who}: M2: R4 / R5 matched")
    # N3: a receipt without an amount and without a line in the strict year (Z0); N2: one without any date (U0)
    for name, patch in (("z0-ohne-betrag.pdf", {"date": f"{Y}-07-01"}), ("u0-ohne-datum.pdf", {"amount": "5.00"})):
        r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, pdf(["Beleg " + name]), "application/pdf")})
        nid = r.json()["ids"][0]
        until(lambda: s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"), 30)
        check(s.patch(B + f"/api/docs/{nid}", json=patch).ok and s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Material", "keep": True}).ok,
              f"{who}: {name} as a receipt")
    chk, rows, miss = bx(s, f"{Y}-01-01", f"{Y}-12-31")
    cards = [g for t, g in rows if t in ("Credit card", "Kreditkarte")]
    check("-150.40" not in cards and "-20.00" in cards, f"{who}: M1: the meal's card position without its amount, the other open one with {cards}")
    ml = [g for t, g in rows if t in ("Entertainment receipt", "Bewirtungsbeleg")]
    check(len(ml) == 8 and round(sum(float(x) for x in ml), 2) == -300.80, f"{who}: M1: both meals once (70 / 30 each, four rows per meal since #4563) {ml}")
    check("z0-ohne-betrag.pdf" in miss and "r2-ohne-bank.pdf" in miss, f"{who}: N3: the receipt without amount and line is named as open {miss[:400]}")
    check("r4-maerz-april.pdf" not in miss, f"{who}: M2: R4 has its line (April) and is not open {miss[:400]}")
    check("open_strict" not in dv_hints(s, f"{Y}-03-01", f"{Y}-03-31"), f"{who}: M2: the March DATEV export names no open receipt (R4 paid in April)")
    chk, rows, miss = bx(s, f"{Y}-03-01", f"{Y}-03-31")
    check(chk.get("open") == 0, f"{who}: M2: the March export: nothing open {chk}")
    chk, rows, miss = bx(s, f"{Y}-12-01", T0)
    check("r5-dezember.pdf" not in miss and "-47.60" in [g for t, g in rows if t in ("Receipt", "Beleg")],
          f"{who}: M2: R5 (December, paid in January) in the export and not open {miss[:400]} {rows}")
    # ---- 2.755.0 (#5241): the input tax at the edge between the bases -- every receipt exactly once over the years.
    # {Y - 1} receipts -> {Y} bank and cash -> {TODAY.year} receipts again (set here, the lock part below sets it once more).
    # E1 of 20.12.{Y-1} paid on 05.01.{Y} (was in both years), E2 of 03.01.{Y} paid on 28.12.{Y-1} (was in none),
    # E3 of 20.12.{Y} paid on 01.01. this year (was in none), E4 of 01.01. this year paid on 29.12.{Y} (was in both);
    # E5 of 28.03.{Y-1} paid on 02.04.: a receipts year away from the edge keeps the document date (March, par. 15 UStG)
    TY = TODAY.year
    check(s.put(B + "/api/office/books/basis", json={"year": TY, "basis": "receipts"}).ok, f"{who}: #5241: this year by receipts")
    e1 = doc(s, ws, "e1-dez-jan.pdf", "23.80", f"{Y - 1}-12-20", "19")
    e2 = doc(s, ws, "e2-jan-vorab.pdf", "35.70", f"{Y}-01-03", "19")
    e3 = doc(s, ws, "e3-dez-jan.pdf", "47.60", f"{Y}-12-20", "19")
    e4 = doc(s, ws, "e4-jan-vorab.pdf", "59.50", f"{TY}-01-01", "19")
    e5 = doc(s, ws, "e5-maerz-april.pdf", "11.90", f"{Y - 1}-03-28", "19")
    r = s.post(B + O + "/bank/import", json={"text": camt([ntry("23.80", f"{Y}-01-05", "EEINS"), ntry("35.70", f"{Y - 1}-12-28", "EZWEI"),
                                                           ntry("47.60", f"{TY}-01-01", "EDREI"), ntry("59.50", f"{Y}-12-29", "EVIER"),
                                                           ntry("11.90", f"{Y - 1}-04-02", "EFUENF")]), "filename": "konto3.xml"})
    check(r.status_code == 201, f"{who}: #5241: bank import {r.status_code} {r.text[:200]}")
    tx = {t["purpose"].split()[-1]: t["id"] for t in s.get(B + O + "/bank/tx?state=all").json()["items"]}
    for ref, nid in (("EEINS", e1), ("EZWEI", e2), ("EDREI", e3), ("EVIER", e4), ("EFUENF", e5)):
        check(m(tx[ref], {"kind": "receipt", "id": nid}).ok, f"{who}: #5241: {ref} matched")

    def vat_ids(year, period):
        u = s.get(B + O + f"/books/ustva?year={year}&period={period}").json()
        return {x["node_id"]: x["date"] for x in u.get("items", []) if x.get("kind") == "receipt"}
    p0, p1, p2 = vat_ids(Y - 1, "y"), vat_ids(Y, "y"), vat_ids(TY, "y")
    check(e1 not in p0 and p1.get(e1) == f"{Y}-01-05", f"{who}: #5241: E1 only in the strict year, on its line's day {p0.get(e1)} {p1.get(e1)}")
    check(p0.get(e2) == f"{Y - 1}-12-28" and e2 not in p1, f"{who}: #5241: E2 in the receipts year of its line {p0.get(e2)} {p1.get(e2)}")
    check(e3 not in p1 and p2.get(e3) == f"{TY}-01-01", f"{who}: #5241: E3 in the receipts year of its line {p1.get(e3)} {p2.get(e3)}")
    check(p1.get(e4) == f"{Y}-12-29" and e4 not in p2, f"{who}: #5241: E4 only in the strict year {p1.get(e4)} {p2.get(e4)}")
    check(p0.get(e5) == f"{Y - 1}-03-28" and e5 in vat_ids(Y - 1, "m03") and e5 not in vat_ids(Y - 1, "m04"),
          f"{who}: #5241: E5 away from the edge by its document date (March) {p0.get(e5)}")
    check(vat_ids(Y - 1, "m12").get(e2) == f"{Y - 1}-12-28" and e1 not in vat_ids(Y - 1, "m12"), f"{who}: #5241: December of {Y - 1}")
    # the income statement of the two receipts years counts the same receipts (E2 + E5 / E3 + R5 of M2): its input tax = field 66
    ev = {y: s.get(B + O + f"/books/euer?year={y}").json()["expense_total"]["vat"] for y in (Y - 1, TY)}
    uv = {y: s.get(B + O + f"/books/ustva?year={y}&period=y").json()["kz"]["66"] for y in (Y - 1, TY)}
    check(ev == uv and ev[Y - 1] == "7.60" and ev[TY] == "15.20", f"{who}: #5241: the EUeR and field 66 agree in the receipts years {ev} {uv}")

    # ---- 2.743.0 (#4937): the basis changes at the turn of the year ({Y - 1} receipts, {Y} bank and cash): every receipt once
    eu0 = s.get(B + O + f"/books/euer?year={Y - 1}").json()["expense_total"]
    ra = doc(s, ws, "ra-dez-jan.pdf", "41.65", f"{Y - 1}-12-20", "19")  # receipt in December, its bank line in January (strict)
    rb = doc(s, ws, "rb-jan-dez.pdf", "29.75", f"{Y}-01-07", "19")  # receipt in January (strict), its bank line in December
    rk = doc(s, ws, "rk-kasse-dez.pdf", "17.85", f"{Y - 1}-12-30", "19")  # the edge case: a cash line sets no paid_at
    r = s.post(B + O + "/bank/import", json={"text": camt([ntry("41.65", f"{Y}-01-05", "RSECHS"), ntry("29.75", f"{Y - 1}-12-22", "RSIEBEN")]),
                                             "filename": "konto4.xml"})
    check(r.status_code == 201, f"{who}: #4937: bank import {r.status_code} {r.text[:200]}")
    tx = {t["purpose"].split()[-1]: t["id"] for t in s.get(B + O + "/bank/tx?state=all").json()["items"]}
    check(m(tx["RSECHS"], {"kind": "receipt", "id": ra}).ok and m(tx["RSIEBEN"], {"kind": "receipt", "id": rb}).ok, f"{who}: #4937: ra / rb matched")
    check(s.post(B + E, json={"day": f"{Y}-01-02", "dir": "in", "amount": "20.00", "text": "Einlage"}).status_code == 201, f"{who}: #4937: cash in for January")
    check(s.post(B + E, json={"day": f"{Y}-01-04", "dir": "out", "amount": "17.85", "vat_pct": "19", "text": "Material", "node_id": rk}).status_code == 201,
          f"{who}: #4937: rk paid from the cash box in January")
    check(once(s, who, "receipt 12 / line 01", "-41.65", "ra-dez-jan", (Y - 1, Y)) == {Y - 1: 0, Y: 1}, f"{who}: #4937: ra in {Y} (its line)")
    check(once(s, who, "receipt 01 / line 12", "-29.75", "rb-jan-dez", (Y - 1, Y)) == {Y - 1: 1, Y: 0}, f"{who}: #4937: rb in {Y - 1} (its line)")
    check(once(s, who, "cash line without paid_at", "-17.85", "rk-kasse-dez", (Y - 1, Y)) == {Y - 1: 0, Y: 1}, f"{who}: #4937: rk in {Y} (its cash line)")
    eu1 = s.get(B + O + f"/books/euer?year={Y - 1}").json()["expense_total"]
    check(round(float(eu1["net"]) - float(eu0["net"]), 2) == 25.0, f"{who}: #4937: the EUeR of {Y - 1} counts rb only (25.00 net), not ra / rk {eu0} {eu1}")
    chk, rows, miss = bx(s, f"{Y}-01-01", f"{Y}-12-31")
    check("rb-jan-dez.pdf" not in miss, f"{who}: #4937: rb (line in a receipts year) is not open in the strict year {miss[:400]}")
    check("open_strict" not in dv_hints(s, f"{Y}-01-01", f"{Y}-01-31"), f"{who}: #4937: the January DATEV export names rb not open")

    # ---- 2.764.0 (#5313): entertainment receipts and travel receipts at the same edges -- each exactly once over the years.
    # MA of 27.12.{Y-1} paid on 04.01.{Y} (was in both years), MB of 28.12.{Y} paid on 03.01. this year (was in none);
    # a trip of 10.01.{Y} with a ticket of 15.12.{Y-1} at 19 % (was in no year: the trip is of {Y})
    r = s.post(B + O + "/bank/import", json={"text": camt([ntry("150.40", f"{Y}-01-04", "MEDGEA"), ntry("150.40", f"{TY}-01-03", "MEDGEB")]),
                                             "filename": "konto5.xml"})
    check(r.status_code == 201, f"{who}: #5313: bank import {r.status_code} {r.text[:200]}")
    tx = {t["purpose"].split()[-1]: t["id"] for t in s.get(B + O + "/bank/tx?state=all").json()["items"]}
    edge = {}
    for name, day, ref in (("MA", f"{Y - 1}-12-27", "MEDGEA"), ("MB", f"{Y}-12-28", "MEDGEB")):
        r = s.post(B + O + "/meals", json=meal(me, day))
        check(r.status_code == 201, f"{who}: #5313: meal {name} {r.text[:200]}")
        edge[name] = r.json()["id"]
        check(s.post(B + O + f"/meals/{edge[name]}/approve").ok, f"{who}: #5313: meal {name} approved")
        r = s.put(B + f"/api/office/meals/{edge[name]}/payment", json={"kind": "bank", "id": tx[ref]})
        check(r.ok, f"{who}: #5313: meal {name} takes its line {r.text[:200]}")
    r = s.post(B + O + "/trips", json={"date_from": f"{Y}-01-10", "date_to": f"{Y}-01-12", "dest": "Hamburg - Berlin", "purpose": "job",
                                       "items": [{"date": f"{Y - 1}-12-15", "category": "train", "amount": "119", "vat_pct": "19"}]})
    check(r.status_code == 201, f"{who}: #5313: a trip with a ticket of the year before {r.text[:200]}")

    def vat_kind(year, kind, key):
        u = s.get(B + O + f"/books/ustva?year={year}&period=y").json()
        return {x[key]: x["date"] for x in u.get("items", []) if x.get("kind") == kind}
    m0, m1, m2 = (vat_kind(y, "meal", "meal_id") for y in (Y - 1, Y, TY))
    check(edge["MA"] not in m0 and m1.get(edge["MA"]) == f"{Y}-01-04", f"{who}: #5313: MA only in the strict year, on its line's day {m0} {m1}")
    check(edge["MB"] not in m1 and m2.get(edge["MB"]) == f"{TY}-01-03", f"{who}: #5313: MB in the receipts year of its line {m1} {m2}")
    q = s.get(B + O + f"/books/ustva?year={TY}&period=m01").json()
    check(any(x.get("meal_id") == edge["MB"] for x in q.get("items", [])), f"{who}: #5313: MB in January of this year (its line's month)")
    t0, t1 = vat_kind(Y - 1, "travel", "trip_id"), vat_kind(Y, "travel", "trip_id")
    tid = r.json()["id"]
    check(t0.get(tid) == f"{Y - 1}-12-15" and tid not in t1, f"{who}: #5313: the ticket counts in its own year, once {t0} {t1}")
    # the income statement and field 66 agree again in the receipts years (+ MB 20.40, the ticket 19.00; rb of #4937 4.75 in {Y - 1})
    ev = {y: s.get(B + O + f"/books/euer?year={y}").json()["expense_total"]["vat"] for y in (Y - 1, TY)}
    uv = {y: s.get(B + O + f"/books/ustva?year={y}&period=y").json()["kz"]["66"] for y in (Y - 1, TY)}
    check(ev == uv and ev[Y - 1] == "31.35" and ev[TY] == "35.60", f"{who}: #5313: the EUeR and field 66 agree with the meals and the ticket {ev} {uv}")
    check(line(s.get(B + O + f"/books/euer?year={Y - 1}").json(), "m:") is None, f"{who}: #5313: the EUeR of {Y - 1} has no meal (MA counts in {Y})")
    mt = line(s.get(B + O + f"/books/euer?year={TY}").json(), "m:")
    check(mt and mt["count"] == 1 and mt["vat"] == "20.40", f"{who}: #5313: the EUeR of this year has MB once {mt}")

    # ---- a locked month keeps the basis of its year
    r = s.post(B + O + "/periods/lock", json={"through": f"{Y}-01", "confirm": f"01/{Y}"})
    check(r.ok, f"{who}: January of {Y} locked {r.text[:200]}")
    r = s.put(B + "/api/office/books/basis", json={"year": Y, "basis": "receipts"})
    check(r.status_code == 409 and str(Y) in r.text, f"{who}: a year with a locked month keeps its basis {r.status_code} {r.text[:200]}")
    check(s.get(B + f"/api/office/books/basis?year={Y}").json()["locked"] is True, f"{who}: the year shows as locked")
    check(s.put(B + "/api/office/books/basis", json={"year": Y, "basis": "bank"}).ok, f"{who}: the same basis again is fine")
    check(s.put(B + "/api/office/books/basis", json={"year": TODAY.year, "basis": "receipts"}).ok, f"{who}: the open year may change")
    ei = s.get(B + O + f"/books/euer?year={TODAY.year}").json()
    check(inc(ei, "vat19")["net"] == "1500.00" and ei.get("basis") == "receipts", f"{who}: this year by receipts again")
    check(s.get(B + O + f"/books/euer?year={Y}").json().get("basis") == "bank", f"{who}: {Y} stays bank and cash")
    # ---- 2.743.0 (#4937): the other way ({Y} bank and cash, {TODAY.year} receipts): R5 (28.12., bank line 01.01.) and r9
    # (01.01., bank line 30.12.) once each; rw (29.12., cash line 01.01., no paid_at) is not open in {Y}
    t1 = TODAY.year
    check(once(s, who, "R5 receipt 12 / line 01", "-47.60", "r5-dezember", (Y, t1)) == {Y: 0, t1: 1}, f"{who}: #4937: R5 in {t1} (its line)")
    r9 = doc(s, ws, "r9-jan-dez.pdf", "11.90", f"{t1}-01-01", "19")
    r = s.post(B + O + "/bank/import", json={"text": camt([ntry("11.90", f"{Y}-12-30", "RNEUN")]), "filename": "konto4.xml"})
    tx = {t["purpose"].split()[-1]: t["id"] for t in s.get(B + O + "/bank/tx?state=all").json()["items"]}
    check(r.status_code == 201 and m(tx["RNEUN"], {"kind": "receipt", "id": r9}).ok, f"{who}: #4937: r9 matched {r.text[:200]}")
    check(once(s, who, "r9 receipt 01 / line 12", "-11.90", "r9-jan-dez", (Y, t1)) == {Y: 1, t1: 0}, f"{who}: #4937: r9 in {Y} (its line)")
    w0 = s.get(B + O + f"/books/euer?year={Y}").json()["warnings"]["open_receipts"]
    e0 = s.get(B + O + f"/books/euer?year={t1}").json()["expense_total"]
    rw = doc(s, ws, "rw-kasse-jan.pdf", "5.95", f"{Y}-12-29", "19")
    check(s.post(B + E, json={"day": f"{t1}-01-01", "dir": "out", "amount": "5.95", "vat_pct": "19", "text": "Material", "node_id": rw}).status_code == 201,
          f"{who}: #4937: rw paid from the cash box on 01.01.")
    w1 = s.get(B + O + f"/books/euer?year={Y}").json()["warnings"]["open_receipts"]
    check(w1 == w0, f"{who}: #4937: rw (cash line in January) is not open in {Y} {w0} -> {w1}")
    e1 = s.get(B + O + f"/books/euer?year={t1}").json()["expense_total"]
    check(round(float(e1["net"]) - float(e0["net"]), 2) == 5.0, f"{who}: #4937: the EUeR of {t1} counts rw once (5.00 net) {e0} {e1}")
    return mid


MID = office(A, "org", f"org:{ORG}", ALICE)

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
office(Fr, "freelancer", "private", FID)
# tenant-matrix: office -- the meal of another office area: 404, never its line
check(Fr.get(B + f"/api/office/meals/{MID}/payment").status_code == 404, "another office's meal: 404")
check(Fr.put(B + f"/api/office/meals/{MID}/payment", json={"kind": None}).status_code == 404, "another office's meal cannot be unlinked: 404")
check(A.get(B + f"/api/office/meals/{MID}/payment").json()["current"]["kind"] == "bank", "the organisation's link stays")
check(A.get(B + f"/api/office/books/basis?year={Y}").json()["years"] == {str(Y): "bank", str(TODAY.year): "receipts"}, "the organisation keeps its own setting")
# 2.610.0 (#4932 review N2): over two years (one strict), a receipt without any date in a folder the person cannot open counts
# once in "hidden" (the freelancer sees none of the organisation's receipts: hidden = all dated ones + the undated ones)
out = subprocess.run(["docker", "exec", CT, "python", "-c",
                      "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\n"
                      "from kalmido.office.books import bk_receipts, bk_receipts_basis\nc = connect()\nwith system_ctx(c):\n"
                      f"    g, u = {{}}, {{}}\n    bk_receipts_basis(c, {ORG}, '{Y}-01-01', '{T0}', uid={FID}, gaps=g)\n"
                      f"    n = len(bk_receipts_basis(c, {ORG}, '{Y}-01-01', '{T0}', uid=0))\n"
                      f"    bk_receipts(c, {ORG}, '9999-01-01', '9999-01-01', uid={FID}, gaps=u)\n"
                      "    print('N2', g.get('hidden', 0), n + u.get('hidden', 0), u.get('hidden', 0))\nc.close()"],
                     capture_output=True, text=True)
n2 = (out.stdout.split("N2 ")[-1].split() + ["", "", ""])[:3] if "N2 " in out.stdout else ["?", "!", "0"]
check(n2[0] == n2[1] and n2[2] not in ("", "0"), f"N2: hidden counts the undated receipt once {n2} {out.stdout[-200:]} {out.stderr[-300:]}")

print(f"p2603_c_euer_basis: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
