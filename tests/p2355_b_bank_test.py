#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.355.0 B (#2843 #2845 #2847) API tests: bank import, cash book payments, retention, own container (start.sh through
kt.fresh, server key + org encryption on). Invented companies, people, accounts and figures only.
tenant-matrix: office  freelancer-matrix: office
 - #2843 amounts of a CSV: thousand separators only in groups of three, else the row is unreadable ("1,234.5" with the
   decimal comma was 1,23; "1.234" with the decimal point was 1,23); half up (1234.565 -> 1234.57); "-50,00" in the
   credit column is -50; DD/MM/YYYY is guessed for a British file (03/04 = 3 April), MM/DD only when a day says so
 - #2843 duplicates: a fixed EndToEndId with the same amount in two months = two bookings (was one); the same day again =
   duplicate; a key stored before 2.355 (without the day) still finds the booking of its own day, not one of another month
 - #2843 a personal office moved into an organisation: the organisation's import finds the moved bookings (no doubles);
   #2845 its locked months go along (the move was refused before)
 - #2843 receipt match: a payment day typed by hand stays (match and unmatch); a receipt with another amount is matched
   and the answer says so (amount_differs)
 - #2843 split: one booking on two invoices (both paid) with a rest of 0.01 shown as match.rest; the parts above the
   booking 400; unmatch takes every part back (both open again); a booking of 100.01 on an invoice of 100.00 (one part)
 - #2843 cash book: cash in for an invoice books a cash payment on it (paid, never reminded); amount / day of that entry
   409; its cancellation takes the payment back (open again)
 - #2847 an import taken back while its booking is matched at the same moment: never a matched booking of an import
   taken back (threads, several rounds)
 - #2845 retention: the asset register counts when an organisation is deleted (odl_retention "assets"); entertainment
   receipts at least 8 years with a lower value of the neutral pack; an open receipt not booked yet cannot be deleted for
   good; #2847 the one-day CSV newest first gives the closing balance of the first row
usage: p2355_b_bank_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import threading
from datetime import timedelta

import kt
from kt import B, CT, DATA, check, sess
from freelancer_fixture import freelancer
import dbx as dbxm
import testclock

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2355B")
import requests  # noqa: E402,F401

A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
FEAT = "cal,comments,collab,office,clients,files,docs"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A, "fiona", features=FEAT)  # freelancer-matrix: office (the personal office, its own admin)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
O = "/api/office"
K = O + "/bank"
D = O + "/docs"
TODAY = testclock.today()
TD = TODAY.isoformat()
DAY = [(TODAY - timedelta(days=n)).isoformat() for n in range(0, 40)]
M0 = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)  # the finished month before
M = M0.isoformat()[:7]
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
REF = [0]


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
    """Python inside the server container (the app loaded, c = a connection, system context) -> stdout + stderr."""
    body = "\n".join("    " + x for x in code.split("\n"))
    out = subprocess.run(["docker", "exec", CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nc = connect()\n"
                          "with system_ctx(c):\n" + body + "\nc.close()"], capture_output=True, text=True)
    return out.stdout + out.stderr


def camt(rows):
    """A CAMT.053 statement: rows (signed amount, day, name, purpose, EndToEndId or None); no AcctSvcrRef."""
    out = []
    for amt, day, name, purpose, e2e in rows:
        REF[0] += 1
        who = "Dbtr" if amt > 0 else "Cdtr"
        refs = f"<Refs><EndToEndId>{e2e}</EndToEndId></Refs>" if e2e else ""
        out.append(f'<Ntry><Amt Ccy="EUR">{abs(amt):.2f}</Amt><CdtDbtInd>{"CRDT" if amt > 0 else "DBIT"}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>'
                   f"<BookgDt><Dt>{day}</Dt></BookgDt><NtryDtls><TxDtls>{refs}<RltdPties><{who}><Pty><Nm>{name}</Nm></Pty></{who}>"
                   f"</RltdPties><RmtInf><Ustrd>{purpose}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>")
    return ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>'
            f'<Id>S{REF[0]}</Id>{"".join(out)}</Stmt></BkToCstmrStmt></Document>')


def imp(s, rows):
    r = s.post(B + K + "/import", json={"text": camt(rows), "filename": "auszug.xml"})
    assert r.status_code == 201, r.text
    return r.json()


def prev(s, rows):
    r = s.post(B + K + "/import/preview", json={"text": camt(rows), "filename": "auszug.xml"})
    assert r.ok, r.text
    return r.json()


def txs(s):
    return s.get(B + K + "/tx?state=all").json()["items"]


def tx(s, purpose):
    m = [t for t in txs(s) if t["purpose"] == purpose]
    assert len(m) == 1, (purpose, len(m))
    return m[0]


def csv_prev(s, text, mapping):
    r = s.post(B + K + "/import/preview", json={"text": text, "filename": "konto.csv", "mapping": mapping})
    assert r.ok, r.text
    return r.json()


def tiny_pdf(text):
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


def receipt(s, ws, name, amount, day, vat="19"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def invoice(s, client, title, rate):
    r = s.post(B + D, json={"kind": "invoice", "client_id": client, "service_from": DAY[20],
                            "items": [{"title": title, "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    return did


def status(s, did):
    return s.get(B + f"{D}/{did}").json().get("status")


def payments(s, did):
    return s.get(B + f"{D}/{did}/payments").json()["payments"]


# ======================================================================== #2843 the amounts of a CSV (org and personal office)
for who, s in (("org", A), ("freelancer", Fr)):
    p = f"{who}: "
    m = {"date": 0, "amount": 1, "title": 2, "decimal": ",", "date_format": "DD.MM.YYYY"}
    d0 = f"{TD[8:10]}.{TD[5:7]}.{TD[:4]}"
    j = csv_prev(s, "Datum;Betrag;Text\n" + "\n".join(f"{d0};{a};Zeile {i}" for i, a in enumerate(
        ("1.234,56", "1,234.5", "12.30", "-7,5", "1.234.567,80"))), m)
    got = {r["purpose"]: (r["amount"], r["error"]) for r in j["rows"]}
    check(got["Zeile 0"][0] == "1234.56" and got["Zeile 0"][1] is None, p + f"1.234,56 with the decimal comma {got['Zeile 0']}")
    check(got["Zeile 1"][1] and got["Zeile 2"][1], p + f"1,234.5 / 12.30 with the decimal comma are unreadable rows (were 1.23 / 1230) {got}")
    check(got["Zeile 3"][0] == "-7.50" and got["Zeile 4"][0] == "1234567.80", p + f"-7,5 and 1.234.567,80 {got}")
    m["decimal"] = "."
    j = csv_prev(s, "Datum;Betrag;Text\n" + "\n".join(f"{d0};{a};Punkt {i}" for i, a in enumerate(("1.234", "1,234.50", "1234.565", "0.125"))), m)
    got = {r["purpose"]: (r["amount"], r["error"]) for r in j["rows"]}
    check(got["Punkt 0"][1] and got["Punkt 3"][1], p + f"1.234 / 0.125 with the decimal point: a thousand or decimals, unreadable (were 1.23 / 0.13) {got}")
    check(got["Punkt 1"][0] == "1234.50" and got["Punkt 2"][0] == "1234.57", p + f"1,234.50; 1234.565 rounded half up {got}")
    # the credit column keeps its sign, the debit column is always out
    m2 = {"date": 0, "amount_out": 1, "amount_in": 2, "title": 3, "decimal": ",", "date_format": "DD.MM.YYYY"}
    j = csv_prev(s, f"Datum;Soll;Haben;Text\n{d0};;-50,00;Rueckbuchung\n{d0};20,00;;Gebuehr\n{d0};-30,00;;Abbuchung\n{d0};;80,00;Eingang", m2)
    got = {r["purpose"]: r["amount"] for r in j["rows"]}
    check(got == {"Rueckbuchung": "-50.00", "Gebuehr": "-20.00", "Abbuchung": "-30.00", "Eingang": "80.00"},
          p + f"-50,00 in the credit column is -50 (was +50) {got}")
    # British dates
    r = s.post(B + K + "/import/preview", json={"text": "Date,Amount,Description\n03/04/2026,10.00,Tea\n05/06/2026,12.00,Cake\n", "filename": "uk.csv"})
    check(r.ok and r.json()["guess"]["date_format"] == "DD/MM/YYYY", p + f"03/04/2026: day first (DD/MM) {r.text[:300]}")
    r = s.post(B + K + "/import/preview", json={"text": "Date,Amount,Description\n03/25/2026,10.00,Tea\n04/01/2026,12.00,Cake\n", "filename": "us.csv"})
    check(r.ok and r.json()["guess"]["date_format"] == "MM/DD/YYYY", p + f"03/25/2026: month first {r.text[:300]}")
    mu = {"date": 0, "amount": 1, "title": 2, "decimal": ".", "date_format": "DD/MM/YYYY"}
    j = csv_prev(s, "Date,Amount,Description\n03/04/2026,10.00,Tea\n", mu)
    check(j["rows"][0]["day"] == "2026-04-03", p + f"DD/MM/YYYY reads 3 April {j['rows'][0]}")

# ======================================================================== #2843 duplicates with the booking day
for who, s, oid in (("org", A, ORG), ("freelancer", Fr, None)):
    p = f"{who}: "
    e2e = f"VERTRAG-{who.upper()}-7"
    imp(s, [(49.00, DAY[35], "Kunde Abo", f"Abo Januar {who}", e2e)])
    r = s.post(B + K + "/import", json={"text": camt([(49.00, DAY[5], "Kunde Abo", f"Abo Februar {who}", e2e)]), "filename": "auszug.xml"})
    j = r.json()
    check(r.status_code == 201 and j["count"] == 1 and j["dup_count"] == 0,
          p + f"a fixed EndToEndId with the same amount a month later: a new booking (was a duplicate) {r.status_code} {r.text[:200]}")
    j = prev(s, [(49.00, DAY[5], "Kunde Abo", f"Abo Februar anders {who}", e2e)])
    check(j["count"] == 0 and j["dup_count"] == 1, p + f"the same EndToEndId on the same day with another text: duplicate {j}")
    # a key stored before 2.355 (without the day) on the January booking
    t1 = tx(s, f"Abo Januar {who}")
    area = oid or sql("SELECT org_id FROM office_bank_tx WHERE id=?", (t1["id"],))[0][0]
    out = in_app(f"from kalmido.office.bank import bnk_rkey\nprint('KEY', bnk_rkey({area}, 'e|{e2e}|49.00'))")
    old = next((x.split()[1] for x in out.splitlines() if x.startswith("KEY ")), None)
    check(old is not None, p + "the old key made in the app " + out[-300:])
    sql("UPDATE office_bank_tx SET rkeys=? WHERE id=?", (old or "", t1["id"]), write=True)
    j = prev(s, [(49.00, DAY[35], "Kunde Abo", f"Abo Januar anders {who}", e2e)])
    check(j["dup_count"] == 1, p + f"an old key finds the booking of its own day {j}")
    j = prev(s, [(49.00, DAY[1], "Kunde Abo", f"Abo Maerz {who}", e2e)])
    check(j["count"] == 1 and j["dup_count"] == 0, p + f"an old key does not swallow the booking of another month {j}")

# ======================================================================== #2843 #2845 a personal office moves into an organisation
Fr.put(B + O + "/settings", json={"company_fields": {"name": "Fiona Grafik", **COMPANY}})
MOVE_ROWS = [(-12.00, f"{M}-10", "Papier Beispiel", "Papier vor Umzug", "UMZ-1"), (-30.00, f"{M}-12", "Druck Beispiel", "Druck vor Umzug", None)]
imp(Fr, MOVE_ROWS)
r = Fr.post(B + O + "/periods/lock", json={"through": M, "confirm": f"{M[5:7]}/{M[:4]}"})
check(r.ok, f"freelancer: month {M} locked {r.status_code} {r.text[:200]}")
GAM = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": FID}).json()["id"]
Fr.patch(B + "/api/settings", json={"workspace": f"org:{GAM}"})
Fr.put(B + O + "/settings", json={"company_fields": {"name": "Gamma Beispiel GmbH", **COMPANY}})
Fr.patch(B + "/api/settings", json={"workspace": "private"})
r = Fr.get(B + O + f"/move/check?org={GAM}")
notes = " | ".join(r.json().get("notes") or []) if r.ok else r.text
check(r.ok and r.json()["ok"] and "locked up to" in notes, f"#2845: the preview says the locks go along, no conflict {r.text[:300]}")
r = Fr.post(B + O + "/move/org", json={"org": GAM, "confirm": True})
check(r.ok, f"#2845: a locked personal office moves (was 409) {r.status_code} {r.text[:200]}")
check(sql("SELECT MAX(period) FROM office_period_locks WHERE org_id=?", (GAM,))[0][0] == M, "#2845: the organisation is locked up to the same month")
Fr.patch(B + "/api/settings", json={"workspace": f"org:{GAM}"})
j = prev(Fr, MOVE_ROWS)
check(j["count"] == 0 and j["dup_count"] == 2, f"#2843: the same statement in the organisation: both bookings are duplicates (fingerprint and reference) {j}")
j = prev(Fr, [(-12.00, f"{M}-10", "Papier Beispiel", "Papier anderer Text", "UMZ-1")])
check(j["dup_count"] == 1, f"#2843: by the reference of the moved booking too {j}")
Fr.patch(B + "/api/settings", json={"workspace": "private"})

# ======================================================================== #2843 receipt match: day by hand, amount
for who, s, ws in (("org", A, f"org:{ORG}"), ("freelancer", Fr, "private")):
    p = f"{who}: "
    if who == "org":
        s.put(B + O + "/settings", json={"company_fields": {"name": "Alpha Beispiel GmbH", **COMPANY}})
    imp(s, [(-119.00, DAY[3], "Software Beispiel", f"Lizenz {who}", None), (-100.00, DAY[3], "Laden Beispiel", f"Material {who}", None)])
    R1 = receipt(s, ws, f"lizenz-{who}.pdf", "119.00", DAY[6])
    hand = DAY[2]
    sql("UPDATE rc_receipts SET paid_at=? WHERE node_id=?", (hand, R1), write=True)
    t = tx(s, f"Lizenz {who}")
    r = s.post(B + f"{K}/tx/{t['id']}/match", json={"kind": "receipt", "id": R1})
    check(r.ok and r.json().get("amount_differs") is None, p + f"matched, same amount {r.text[:200]}")
    check(sql("SELECT paid_at FROM rc_receipts WHERE node_id=?", (R1,))[0][0] == hand, p + "the payment day typed by hand stays (was the booking's day)")
    check(s.post(B + f"{K}/tx/{t['id']}/unmatch").ok, p + "unmatch")
    check(sql("SELECT paid_at FROM rc_receipts WHERE node_id=?", (R1,))[0][0] == hand, p + "unmatch leaves the day by hand (was emptied)")
    R2 = receipt(s, ws, f"material-{who}.pdf", "119.00", DAY[6])
    t = tx(s, f"Material {who}")
    r = s.post(B + f"{K}/tx/{t['id']}/match", json={"kind": "receipt", "id": R2})
    check(r.ok and r.json().get("amount_differs") == {"receipt": "119.00", "booking": "100.00"}, p + f"another amount: matched and said {r.text[:300]}")
    check(sql("SELECT paid_at FROM rc_receipts WHERE node_id=?", (R2,))[0][0] == DAY[3], p + "without a day by hand the booking's day")
    check(s.post(B + f"{K}/tx/{t['id']}/unmatch").ok and sql("SELECT paid_at FROM rc_receipts WHERE node_id=?", (R2,))[0][0] is None,
          p + "unmatch takes the day it set back")

# ======================================================================== #2843 split + cash book (invoices)
for who, s in (("org", A), ("freelancer", Fr)):
    p = f"{who}: "
    cl = s.post(B + "/api/clients", json={"name": f"Kunde Sammel {who}", "street": "Kundenweg 2", "zip": "20095", "city": "Hamburg", "country": "DE"}).json()["id"]
    I1, I2, I3 = invoice(s, cl, "Schnitt", 100), invoice(s, cl, "Ton", 200), invoice(s, cl, "Farbe", 100)  # 119 / 238 / 119 gross
    imp(s, [(357.01, DAY[2], f"Kunde Sammel {who}", f"Sammel {who}", None), (119.01, DAY[2], f"Kunde Sammel {who}", f"Ueber {who}", None)])
    t = tx(s, f"Sammel {who}")
    r = s.post(B + f"{K}/tx/{t['id']}/match", json={"kind": "invoice", "parts": [{"id": I1, "amount": "119.00"}, {"id": I2, "amount": "238.01"}]})
    check(r.status_code == 409, p + f"a part above the open amount 409 {r.status_code}")
    r = s.post(B + f"{K}/tx/{t['id']}/match", json={"kind": "invoice", "parts": [{"id": I1, "amount": "119.00"}, {"id": I2, "amount": "238.02"}]})
    check(r.status_code == 400, p + f"parts above the booking 400 {r.status_code}")
    check(not payments(s, I1), p + "nothing booked by a refused split")
    r = s.post(B + f"{K}/tx/{t['id']}/match", json={"kind": "invoice", "parts": [{"id": I1, "amount": "119.00"}, {"id": I2, "amount": "238.00"}]})
    check(r.ok and r.json()["match"].get("rest") == "0.01" and [x["id"] for x in r.json()["match"].get("parts") or []] == [I1, I2],
          p + f"split on two invoices, rest 0.01 shown {r.text[:300]}")
    check(status(s, I1) == "paid" and status(s, I2) == "paid", p + "both invoices paid")
    t2 = tx(s, f"Sammel {who}")
    check(t2["match"] and t2["match"].get("rest") == "0.01" and t2["match"]["kind"] == "invoice", p + f"the list shows the rest {t2['match']}")
    r = s.post(B + f"{K}/tx/{t['id']}/unmatch")
    was = r.json().get("was") or {} if r.ok else {}
    check(r.ok and len(was.get("parts") or []) == 2, p + f"unmatch answers the parts for the undo {r.text[:300]}")
    check(status(s, I1) != "paid" and status(s, I2) != "paid", p + "both invoices open again")
    r = s.post(B + f"{K}/tx/{t['id']}/match", json=was)
    check(r.ok and status(s, I1) == "paid", p + "the undo of the unmatch splits again")
    tu = tx(s, f"Ueber {who}")
    r = s.post(B + f"{K}/tx/{tu['id']}/match", json={"kind": "invoice", "id": I3})
    check(r.status_code == 409, p + "119.01 on 119.00 as a plain match: 409 as before")
    r = s.post(B + f"{K}/tx/{tu['id']}/match", json={"kind": "invoice", "parts": [{"id": I3, "amount": "119.00"}]})
    check(r.ok and r.json()["match"].get("rest") == "0.01" and status(s, I3) == "paid", p + f"overpaid by 0.01: paid, rest shown {r.text[:200]}")
    # the cash book
    I4 = invoice(s, cl, "Licht", 50)  # 59.50 gross
    cb = s.post(B + O + "/cashbooks", json={"name": "Hauptkasse", "opening": "100.00", "opening_day": DAY[30]})
    check(cb.status_code in (200, 201), p + f"a cash box {cb.status_code} {cb.text[:200]}")
    CB = cb.json()["id"]
    r = s.post(B + f"{O}/cashbooks/{CB}/entries", json={"day": TD, "dir": "in", "amount": "59.50", "text": "Barzahlung Licht", "vat_pct": "19", "invoice_id": I4})
    check(r.status_code == 201, p + f"cash in for the invoice {r.status_code} {r.text[:200]}")
    E = r.json().get("id")
    pays = payments(s, I4)
    check(status(s, I4) == "paid" and [(x["method"], x["amount"]) for x in pays] == [("cash", "59.50")],
          p + f"the invoice is paid in cash (was open) {status(s, I4)} {pays}")
    r = s.patch(B + f"{O}/cash-entries/{E}", json={"amount": "60.00"})
    check(r.status_code == 409, p + f"the amount of that entry cannot change {r.status_code}")
    check(s.patch(B + f"{O}/cash-entries/{E}", json={"text": "Barzahlung Licht Rechnung"}).ok, p + "its text can")
    r = s.post(B + f"{O}/cash-entries/{E}/cancel", json={})
    check(r.status_code == 201 and status(s, I4) != "paid", p + f"the cancellation takes the payment back {r.status_code} {status(s, I4)}")

# ======================================================================== #2847 take an import back while matching it
for rnd in range(6):
    j = imp(A, [(-5.00 - rnd, DAY[1], "Kiosk Beispiel", f"Wettlauf {rnd}", None)])
    iid, t = j["import"]["id"], tx(A, f"Wettlauf {rnd}")
    res = {}
    go = threading.Barrier(2)

    def undo():
        go.wait()
        res["undo"] = sess("alice").post(B + f"{K}/imports/{iid}/undo").status_code

    def match():
        go.wait()
        res["match"] = sess("alice").post(B + f"{K}/tx/{t['id']}/match", json={"kind": "private"}).status_code

    th = [threading.Thread(target=undo), threading.Thread(target=match)]
    [x.start() for x in th]
    [x.join() for x in th]
    row = sql("SELECT t.deleted_at, t.match_kind, i.undone_at FROM office_bank_tx t JOIN office_bank_imports i ON i.id=t.import_id WHERE t.id=?", (t["id"],))[0]
    check((bool(row[0]) and not row[1]) if row[2] else not row[0],
          f"#2847 round {rnd}: never a matched booking of an import taken back {res} {tuple(row)}")
    if row[1]:
        A.post(B + f"{K}/tx/{t['id']}/unmatch")

# ======================================================================== #2845 retention
ts = testclock.now().isoformat(timespec="seconds")
sql("INSERT INTO office_equipment(org_id, name, purchase_date, life_months, created_at, updated_at) VALUES(?,?,?,?,?,?)",
    (ORG, "Kamera", f"{TODAY.year - 1}-03-01", 36, ts, ts), write=True)
out = in_app(f"from kalmido.accounts.orgretain import odl_retention\nr = odl_retention(c, {ORG})\nprint('RET', r['counts'].get('assets'), r['until'])")
check(f"RET 1 {TODAY.year - 1 + 3 + 10}-12-31" in out, "#2845: the asset register counts, from the year of its last depreciation " + out[-300:])
out = in_app(f"from kalmido.core.config import app as fl\nfrom kalmido.office.meals import bw_years\n"
             f"with fl.test_request_context():\n    print('BW', bw_years(c, {ORG}))")
check("BW 8" in out, "entertainment receipts: 8 years " + out[-300:])
r = A.put(B + O + "/settings", json={"pack": "XX"})
r = A.put(B + O + "/settings", json={"retention_years": 6}) if r.ok else r
out = in_app(f"from kalmido.core.config import app as fl\nfrom kalmido.office.meals import bw_years\n"
             f"with fl.test_request_context():\n    print('BW', bw_years(c, {ORG}))")
check("BW 8" in out, f"#2845: entertainment receipts at least 8 years also with an own lower value ({r.status_code}) " + out[-300:])
for who, s, ws in (("org", A, f"org:{ORG}"), ("freelancer", Fr, "private")):
    nid = receipt(s, ws, f"offen-{who}.pdf", "20.00", DAY[4], None)
    s.put(B + f"/api/docs/{nid}/receipt", json={"category": "", "vat_pct": None, "keep": True})
    assert s.delete(B + f"/api/files/nodes/{nid}").ok
    r = s.delete(B + f"/api/files/nodes/{nid}?purge=1")
    check(r.status_code == 409 and "Kept by law until" in r.text, f"{who} #2845: an open receipt not booked yet is kept from its arrival (was deleted) {r.status_code} {r.text[:200]}")

# ======================================================================== #2847 one-day CSV, newest first: the closing balance
mb = {"date": 0, "amount": 1, "title": 2, "balance": 3, "decimal": ",", "date_format": "DD.MM.YYYY"}
d1 = f"{DAY[1][8:10]}.{DAY[1][5:7]}.{DAY[1][:4]}"
j = csv_prev(A, f"Datum;Betrag;Text;Saldo\n{d1};-10,00;Spaet;490,00\n{d1};-20,00;Mittag;500,00\n{d1};100,00;Frueh;520,00\n", mb)
bals = j.get("balances") or []
check(any(b.get("amount") in ("490.00", "490") for b in bals), f"#2847: one day newest first -> the balance of the first row (was 520) {bals}")

sys.exit(kt.done("p2355_b_bank"))
