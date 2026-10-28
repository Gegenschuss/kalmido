#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.354.0 D (#2837, #2838) API tests: credit notes and refunds of the office, in an organisation and in the personal office
of a person without an organisation (freelancer-matrix: office), own container (start.sh through kt.fresh, org encryption on).
Invented companies, people, accounts and figures only.
 - #2837 a refund is a payment on a finalised credit note: the audit example (RE 939.80 = 520 at 19 % after a discount line
   + 300 at 7 %) paid, cancelled in full, refunded -> VAT year on payments (Ist) KZ 81 / 86 = 0 and income 0; the invoice
   and the credit note answer refund_open (939.80 before, 0.00 after); more than refund_open is 409, a credit note of an
   unpaid invoice has nothing to refund (409); the bank reconciliation offers a credit note for money paid out and books
   the refund on it (undo takes it back)
 - #2838 a credit note keeps currency, exchange rate, client, VAT mode / note of its invoice (409 on a change, the same
   value is fine); no credit note without an invoice (POST /docs kind credit and a copy of a credit note: 409); the credit
   notes of an invoice never exceed it per VAT rate (409 although the total fits); a credit note takes the VAT rates frozen
   with its invoice (tax_snapshot), not the country pack of today
usage: p2354_d_credit_test.py <datadir>      (P2354D_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import base64
import json
import os
import sys

import kt
from kt import B, DATA, check
from freelancer_fixture import freelancer
import dbx as dbxm
import testclock

KEY = base64.b64encode(os.urandom(32)).decode()
kt.fresh(env={"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": KEY}, prefix="P2354D")

O = "/api/office"
D = O + "/docs"
K = O + "/bank"
TODAY = testclock.today().isoformat()
YEAR = TODAY[:4]
REF = [0]


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,files,docs", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
COMPANY = {"street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE", "email": "hallo@studio.example",
           "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def camt(rows):
    """A CAMT.053 statement made here: rows (signed amount, day, name, purpose)."""
    out = []
    for amt, day, name, purpose in rows:
        REF[0] += 1
        who = "Dbtr" if amt > 0 else "Cdtr"
        out.append(f'<Ntry><Amt Ccy="EUR">{abs(amt):.2f}</Amt><CdtDbtInd>{"CRDT" if amt > 0 else "DBIT"}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>'
                   f"<BookgDt><Dt>{day}</Dt></BookgDt><AcctSvcrRef>P2354D-{REF[0]:05d}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties>"
                   f"<{who}><Pty><Nm>{name}</Nm></Pty></{who}></RltdPties><RmtInf><Ustrd>{purpose}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>")
    return ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>'
            f'<Id>S{REF[0]}</Id>{"".join(out)}</Stmt></BkToCstmrStmt></Document>')


def case(who, S):
    r = S.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "vat_basis": "ist", "company_fields": {"name": f"Studio {who}", **COMPANY}})
    check(r.ok, f"{who}: office settings " + r.text[:160])

    def client(name):
        r = S.post(B + "/api/clients", json={"name": name, "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def invoice(cl, items, **kw):
        r = S.post(B + D, json=dict({"kind": "invoice", "client_id": cl, "service_from": TODAY, "service_to": TODAY, "items": items}, **kw))
        assert r.status_code == 201, r.text
        did = r.json()["id"]
        r = S.post(B + f"{D}/{did}/finalize")
        check(r.ok, f"{who}: invoice finalised " + r.text[:200])
        return r.json()

    def doc(did):
        return S.get(B + f"{D}/{did}").json()

    def credit(iid):
        r = S.post(B + f"{D}/{iid}/credit")
        check(r.status_code == 201, f"{who}: credit note draft from the invoice " + r.text[:160])
        return r.json()

    def ust():
        r = S.get(B + O + f"/books/ustva?year={YEAR}&period=y")
        check(r.ok, f"{who}: VAT year " + r.text[:160])
        return r.json()

    C1, C2 = client("Beispielkunde AG"), client("Musterbau GmbH")

    # ================================================================ #2837 the audit example: paid, cancelled, refunded
    inv = invoice(C1, [{"title": "Konzept", "qty": 1, "rate": 570}, {"kind": "discount", "title": "Rabatt", "qty": 1, "unit": "flat", "rate": 50, "tax": "standard"},
                       {"title": "Buch", "qty": 1, "rate": 300, "tax": "reduced"}])
    check(inv["totals"]["gross"] == "939.80", f"{who}: RE 939.80 (520 at 19 % after a discount of 50, 300 at 7 %): {inv['totals'].get('gross')}")
    IID = inv["id"]
    r = S.post(B + f"{D}/{IID}/payments", json={"date": TODAY, "amount": "939.80", "method": "transfer"})
    check(r.status_code == 201 and r.json()["state"] == "paid", f"{who}: invoice paid " + r.text[:160])
    u = ust()
    check(u["kz"]["81"] == "520" and u["kz"]["86"] == "300", f"{who}: paid -> KZ 81 520 / KZ 86 300 {u.get('kz')}")
    cr = credit(IID)
    r = S.post(B + f"{D}/{cr['id']}/finalize")
    check(r.ok and r.json()["totals"]["gross"] == "939.80", f"{who}: full credit note finalised " + r.text[:160])
    CID = cr["id"]
    d = doc(IID)
    check(d["status"] == "cancelled" and d.get("refund_open") == "939.80", f"{who}: invoice cancelled, refund open 939.80 ({d['status']}, {d.get('refund_open')})")
    c = doc(CID)
    check(c.get("refund_open") == "939.80" and c.get("payments") == [], f"{who}: the credit note: refund open 939.80, no refund yet {c.get('refund_open')}")
    r = S.post(B + f"{D}/{CID}/payments", json={"date": TODAY, "amount": "1000.00", "method": "transfer"})
    check(r.status_code == 409, f"{who}: a refund above what was paid: 409 " + r.text[:160])
    r = S.post(B + f"{D}/{CID}/payments", json={"date": TODAY, "amount": "939.80", "method": "transfer"})
    check(r.status_code == 201, f"{who}: refund on the credit note: 201 (was 409, #2837) " + r.text[:160])
    c = doc(CID)
    check(c.get("refund_open") == "0.00" and len(c.get("payments") or []) == 1 and c["state"] == "paid", f"{who}: refunded in full {c.get('refund_open')} {c.get('state')}")
    check(doc(IID).get("refund_open") == "0.00", f"{who}: the invoice: nothing open to refund any more")
    r = S.post(B + f"{D}/{CID}/payments", json={"date": TODAY, "amount": "0.01", "method": "transfer"})
    check(r.status_code == 409, f"{who}: a second refund: 409 " + r.text[:120])
    u = ust()
    check(u["kz"]["81"] == "0" and u["kz"]["86"] == "0" and u["tax"]["19"] == "0.00" and u["tax"]["7"] == "0.00",
          f"{who}: Ist VAT after payment + full credit note + refund: KZ 81 / 86 = 0 (was 520 / 300) {u.get('kz')} {u.get('tax')}")
    e = S.get(B + O + f"/books/euer?year={YEAR}").json()
    check(e["income_total"]["gross"] == "0.00", f"{who}: income statement 0 after the refund {e.get('income_total')}")

    # a credit note of an unpaid invoice: nothing to refund
    inv2 = invoice(C1, [{"title": "Regie", "qty": 1, "rate": 100}])
    cr2 = credit(inv2["id"])
    check(S.post(B + f"{D}/{cr2['id']}/finalize").ok, f"{who}: credit note of an unpaid invoice finalised")
    check(doc(cr2["id"]).get("refund_open") == "0.00", f"{who}: unpaid invoice -> refund open 0.00")
    r = S.post(B + f"{D}/{cr2['id']}/payments", json={"date": TODAY, "amount": "1.00", "method": "transfer"})
    check(r.status_code == 409, f"{who}: no refund of money never received: 409 " + r.text[:120])

    # the bank reconciliation: money paid out matched with a credit note = its refund
    inv3 = invoice(C2, [{"title": "Schnitt", "qty": 1, "rate": 500}])
    check(S.post(B + f"{D}/{inv3['id']}/payments", json={"date": TODAY, "amount": "595.00", "method": "transfer"}).status_code == 201, f"{who}: invoice 3 paid")
    cr3 = credit(inv3["id"])
    check(S.post(B + f"{D}/{cr3['id']}/finalize").ok, f"{who}: credit note 3 finalised")
    r = S.post(B + K + "/import", json={"text": camt([(-595.00, TODAY, "Musterbau GmbH", "Erstattung Gutschrift")]), "filename": "auszug.xml"})
    check(r.status_code == 201, f"{who}: bank statement imported " + r.text[:160])
    t = [x for x in S.get(B + K + "/tx?state=all").json()["items"] if x["purpose"] == "Erstattung Gutschrift"][0]
    cands = S.get(B + K + f"/tx/{t['id']}/candidates").json()["items"]
    hit = [x for x in cands if x["kind"] == "invoice" and x["id"] == cr3["id"]]
    check(hit and hit[0].get("refund") and hit[0]["amount"] == "-595.00", f"{who}: money paid out offers the credit note {cands}")
    r = S.post(B + K + f"/tx/{t['id']}/match", json={"kind": "invoice", "id": cr3["id"]})
    check(r.ok, f"{who}: the booking matched with the credit note " + r.text[:160])
    c = doc(cr3["id"])
    check(c.get("refund_open") == "0.00" and [p["amount"] for p in c.get("payments") or []] == ["595.00"], f"{who}: the refund booked from the bank {c.get('payments')}")
    r = S.post(B + K + f"/tx/{t['id']}/unmatch")
    check(r.ok and doc(cr3["id"]).get("refund_open") == "595.00", f"{who}: undo the match: the refund is open again " + r.text[:120])
    t2 = [x for x in S.get(B + K + "/tx?state=all").json()["items"] if x["purpose"] == "Erstattung Gutschrift"][0]
    r = S.post(B + K + f"/tx/{t2['id']}/match", json={"kind": "invoice", "id": inv3["id"]})
    check(r.status_code == 409, f"{who}: money paid out still cannot pay an invoice (409) " + r.text[:120])

    # ================================================================ #2838 bound to the invoice
    inv4 = invoice(C1, [{"title": "Konzept", "qty": 1, "rate": 1000}, {"title": "Buch", "qty": 1, "rate": 100, "tax": "reduced"}])
    check(inv4["totals"]["gross"] == "1297.00", f"{who}: invoice 4 1297.00 {inv4['totals'].get('gross')}")
    cr4 = credit(inv4["id"])
    X = cr4["id"]
    for k, v in (("currency", "USD"), ("fx_rate", 0.5), ("client_id", C2), ("vat_mode", "novat"), ("vat_note", "reverse")):
        r = S.patch(B + f"{D}/{X}", json={k: v})
        check(r.status_code == 409, f"{who}: credit note {k} -> {v}: 409 (#2838) " + r.text[:160])
    d = doc(X)
    check(d["currency"] == "EUR" and d["client_id"] == C1 and d["vat_mode"] == "vat", f"{who}: the credit note kept the invoice's head {d['currency']} {d['client_id']}")
    r = S.patch(B + f"{D}/{X}", json={"currency": "EUR", "client_id": C1, "project_title": "Storno"})
    check(r.ok and r.json()["project_title"] == "Storno", f"{who}: the same values and other fields stay changeable " + r.text[:160])
    # per VAT rate: 200 at 7 % (214.00) fits the total (1297.00) but not the 7 % part (107.00)
    S.put(B + f"{D}/{X}/items", json={"items": [{"title": "Buch", "qty": 2, "rate": 100, "tax": "reduced"}]})
    r = S.post(B + f"{D}/{X}/finalize")
    check(r.status_code == 409, f"{who}: credit note above the invoice's 7 % part: 409 (#2838) " + r.text[:160])
    check(doc(inv4["id"])["status"] != "cancelled" and not doc(X)["locked"], f"{who}: nothing finalised, the invoice unchanged")
    S.put(B + f"{D}/{X}/items", json={"items": [{"title": "Buch", "qty": 1, "rate": 100, "tax": "reduced"}]})
    r = S.post(B + f"{D}/{X}/finalize")
    check(r.ok, f"{who}: credit note of the 7 % part: finalised " + r.text[:160])
    cr5 = credit(inv4["id"])
    S.put(B + f"{D}/{cr5['id']}/items", json={"items": [{"title": "Buch", "qty": 1, "rate": 1, "tax": "reduced"}]})
    check(S.post(B + f"{D}/{cr5['id']}/finalize").status_code == 409, f"{who}: a second credit note at 7 % above the rest: 409")
    S.delete(B + f"{D}/{cr5['id']}")

    # no credit note without an invoice
    r = S.post(B + D, json={"kind": "credit", "client_id": C1, "items": [{"title": "Frei", "qty": 1, "rate": 999}]})
    check(r.status_code == 409, f"{who}: POST /docs kind credit: 409 (#2838) " + r.text[:160])
    r = S.post(B + f"{D}/{CID}/duplicate")
    check(r.status_code == 409, f"{who}: copy of a credit note: 409 (#2838) " + r.text[:160])
    check(S.get(B + f"{D}/{CID}").ok, f"{who}: existing credit notes stay readable")

    # the VAT rates frozen with the invoice: its snapshot says 16 % (finalised under another rate), the pack of today 19 %
    inv6 = invoice(C1, [{"title": "Konzept", "qty": 1, "rate": 100}])
    row = sql("SELECT tax_snapshot FROM office_docs WHERE id=?", (inv6["id"],))[0][0]
    snap = json.loads(row)
    snap["tax"] = dict(snap.get("tax") or {}, standard=16)
    sql("UPDATE office_docs SET tax_snapshot=? WHERE id=?", (json.dumps(snap), inv6["id"]), write=True)
    cr6 = credit(inv6["id"])
    pcts = [str(x.get("pct")) for x in doc(cr6["id"])["totals"].get("tax_lines") or []]
    check(pcts and all(p.split(".")[0] == "16" for p in pcts), f"{who}: the credit note takes the invoice's frozen 16 % (not today's 19 %) {pcts}")
    S.delete(B + f"{D}/{cr6['id']}")


case("org", A)
case("freelancer", Fr)
sys.exit(kt.done("p2354_d_credit"))
