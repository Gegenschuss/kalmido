#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.545.0 C (#4387): the rest of the office audit (2.355). Invented names and figures only.
freelancer-matrix: office
 - section 13b as the recipient: a receipt with the mark "eu" (a service of a business in another EU state) counts its
   amount as the base of field 46, the tax at 19 % in field 47 and the same as input tax in field 67; "other" (e.g. a third
   country) goes to 84 / 85 at the rate chosen (7 % here); a normal receipt stays in 66; 83 is unchanged by section 13b;
   the income statement counts the section 13b amount as net without input tax; a wrong mark answers 400
 - paid reminder fees: marked paid = income "reminder fees (not taxable)" in the income statement (no VAT, Anlage EUeR line
   of Kz 103), money in in the cash flow (kind fee) and the key figures on the day it was marked; waived = gone again
 - a final invoice with a negative rest (-595.00): "to pay back" 595.00, a refund above it 409, a refund of 200.00 is booked
   negative (state partial, cash flow out kind refund, VAT base on cash basis -168), the rest makes it paid; another one is
   cancelled by its credit note (negative itself, was refused)
 - travel receipts with a VAT rate: 107.00 train at 7 % and 119.00 hotel at 19 % count net in the income statement (100 + 7,
   100 + 19) and with 26.00 input tax in field 66 of their month; one without a rate as before; a wrong rate answers 400
 - the same for a person without an organisation (own office)
usage: p2545_c_buero_test.py <datadir>"""
import os
import subprocess
import sys
import time
from decimal import Decimal

import requests

import dbx as dbxm
import testclock
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402

FEAT = "cal,comments,collab,office,clients,docs,travel,time"
O = "/api/office"
D = O + "/docs"
BK = O + "/books"
Y = testclock.today().year
COMPANY = {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg", "country": "DE",
           "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}

subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)


def office(s):
    r = s.put(B + O + "/settings", json={"company": {"name": COMPANY["name"]}, "lang": "en", "currency": "EUR", "company_fields": COMPANY,
                                         "payment_days": 14})
    check(r.ok, "office settings " + r.text[:200])


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


def receipt(s, name, ws, amount, day, vat, rc13b=None):
    """A receipt document in workspace ws with amount / date / VAT rate (and the section 13b mark) set by hand."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf(name), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    for _ in range(120):  # the recognition is done (a real state, not a fixed wait)
        if s.get(B + f"/api/docs/{nid}").json().get("state") in ("done", "failed"):
            break
        time.sleep(0.25)
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "currency": "EUR", "date": day})
    assert r.ok, r.text
    b = {"category": "Software", "vat_pct": vat, "keep": True}
    if rc13b is not None:
        b["rc13b"] = rc13b
    r = s.put(B + f"/api/docs/{nid}/receipt", json=b)
    assert r.ok, r.text
    return nid, r.json()


def ustva(s, period):
    r = s.get(B + BK + f"/ustva?year={Y}&period={period}")
    check(r.ok, "UStVA " + r.text[:200])
    return r.json()


# ---------------------------------------------------------------- section 13b receipts (organisation)
def r13b_office(s, ws, who):
    office(s)
    n1, st = receipt(s, f"{who}-cloud-ie.pdf", ws, "1000.00", f"{Y}-03-10", "0", "eu")
    check(st["receipt"].get("rc13b") == "eu", f"{who}: the receipt keeps the mark eu {st.get('receipt')}")
    receipt(s, f"{who}-print-us.pdf", ws, "500.00", f"{Y}-03-11", "7", "other")
    receipt(s, f"{who}-paper.pdf", ws, "119.00", f"{Y}-03-12", "19")
    r = s.put(B + f"/api/docs/{n1}/receipt", json={"category": "Software", "rc13b": "xx"})
    check(r.status_code == 400, f"{who}: a wrong mark answers 400 {r.status_code}")
    d = ustva(s, "m03")
    kz = d.get("kz", {})
    want = {"46": "1000", "47": "190.00", "84": "500", "85": "35.00", "67": "225.00", "66": "19.00", "83": "-19.00"}
    check(all(kz.get(k) == v for k, v in want.items()), f"{who}: fields 46/47, 84/85, 67, 66, 83 {kz}")
    check(d.get("missing_vat") == 0, f"{who}: section 13b receipts are not 'without VAT rate' {d.get('missing_vat')}")
    eu = s.get(B + O + f"/books/euer?year={Y}").json()
    check(Decimal(eu["expense_total"]["net"]) == Decimal("1600.00") and Decimal(eu["expense_total"]["vat"]) == Decimal("19.00"),
          f"{who}: income statement: section 13b amounts net without input tax {eu.get('expense_total')}")
    r = s.put(B + f"/api/docs/{n1}/receipt", json={"category": "Software", "rc13b": ""})
    check(r.ok and not r.json()["receipt"].get("rc13b"), f"{who}: the mark goes off again " + r.text[:200])
    kz = ustva(s, "m03").get("kz", {})
    check(kz.get("46") == "0" and kz.get("67") == "35.00", f"{who}: without the mark the receipt leaves 46 / 67 {kz}")


# ---------------------------------------------------------------- paid reminder fees
def fees(s, who):
    TODAY = testclock.today().isoformat()
    cl = s.post(B + "/api/clients", json={"name": f"{who} Kunde", "street": "Weg 1", "zip": "50667", "city": "Köln", "country": "DE"}).json()["id"]
    r = s.post(B + D, json={"kind": "invoice", "client_id": cl, "project_title": "Schnitt", "service_from": f"{Y}-01-05",
                            "items": [{"title": "Schnitt", "qty": 1, "rate": 500}]})
    assert r.status_code == 201, r.text
    inv = r.json()["id"]
    check(s.post(B + f"{D}/{inv}/finalize").ok, f"{who}: invoice finalised")
    dbxm.q(DATA, "UPDATE office_docs SET due_date=? WHERE id=?", (f"{Y}-01-01", inv))
    r = s.post(B + D + "/reminder", json={"doc_ids": [inv], "level": 2, "fee": 7.5})
    check(r.ok, f"{who}: reminder with fee " + r.text[:200])
    rm = r.json()["id"]
    check(s.post(B + f"{D}/{rm}/finalize").ok, f"{who}: reminder finalised")
    eu = s.get(B + O + f"/books/euer?year={Y}").json()
    check(not [x for x in eu["income"] if x["key"] == "fee"], f"{who}: an open fee is no income {eu.get('income')}")
    check(s.post(B + f"{D}/{rm}/fee", json={"state": "paid"}).ok, f"{who}: fee marked paid")
    day = dbxm.q(DATA, "SELECT reminder_fee_paid_at FROM office_docs WHERE id=?", (rm,))[0][0]
    check(day == TODAY, f"{who}: the paid day is stored {day} {TODAY}")
    eu = s.get(B + O + f"/books/euer?year={Y}").json()
    fee = [x for x in eu["income"] if x["key"] == "fee"]
    check(fee and fee[0]["net"] == "7.50" and fee[0]["vat"] == "0.00" and fee[0]["gross"] == "7.50", f"{who}: income statement: paid fee 7.50 without VAT {fee}")
    tf = s.get(B + BK + f"/taxform/euer?year={Y}").json()
    free = [x for x in tf.get("rows", []) if x.get("kz") == "103"]
    check(not tf.get("known") or (free and free[0]["amount"] == "7.50"), f"{who}: Anlage EUeR: the fee in the line of Kz 103 {free}")
    cf = s.get(B + O + f"/cashflow?from={TODAY[:7]}&months=1").json()
    ent = [e for e in cf.get("entries", []) if e.get("kind") == "fee"]
    check(ent and ent[0]["amount"] == "7.50" and ent[0]["state"] == "actual" and ent[0]["doc_id"] == rm, f"{who}: cash flow: the fee came in {ent}")
    kp = s.get(B + O + "/kpi").json()
    mo = [m for m in kp["revenue"]["months"] if m["month"] == TODAY[:7]]
    check(mo and mo[0]["amount"] == "7.50", f"{who}: key figures: the fee in this month's money received {mo}")
    kz = ustva(s, "y").get("kz", {})
    check(kz.get("81") == "0" and kz.get("48") == "0", f"{who}: the fee is not in the VAT return {kz}")
    check(s.post(B + f"{D}/{rm}/fee", json={"state": "waived"}).ok, f"{who}: fee waived")
    eu = s.get(B + O + f"/books/euer?year={Y}").json()
    check(not [x for x in eu["income"] if x["key"] == "fee"], f"{who}: a waived fee is no income again {eu.get('income')}")


# ---------------------------------------------------------------- final invoice with a negative rest
def neg_final(s, who, rate):
    cl = s.post(B + "/api/clients", json={"name": f"{who} Bau GmbH", "street": "Weg 2", "zip": "20095", "city": "Hamburg", "country": "DE"}).json()["id"]
    r = s.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": f"{Y}-01-05", "items": [{"title": "Abschläge zu hoch", "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    dbxm.q(DATA, "UPDATE office_docs SET inv_type='final' WHERE id=?", (did,))
    check(s.post(B + f"{D}/{did}/finalize").ok, f"{who}: the negative final invoice is finalised")
    return did


def neg_rest(s, who):
    TODAY = testclock.today().isoformat()
    did = neg_final(s, who, -500)
    d = s.get(B + f"{D}/{did}").json()
    check(d.get("overpaid") == "595.00" and d.get("open") == "0.00" and d.get("state") in ("issued", "sent"),
          f"{who}: to pay back 595.00 {d.get('overpaid')} {d.get('open')} {d.get('state')}")
    r = s.post(B + f"{D}/{did}/payments", json={"date": TODAY, "amount": 600})
    check(r.status_code == 409, f"{who}: a refund above the rest is refused {r.status_code}")
    before = ustva(s, "y").get("kz", {}).get("81")
    r = s.post(B + f"{D}/{did}/payments", json={"date": TODAY, "amount": 200})
    check(r.status_code == 201, f"{who}: a refund of 200 is booked " + r.text[:200])
    d = s.get(B + f"{D}/{did}").json()
    amt = dbxm.q(DATA, "SELECT amount FROM office_payments WHERE doc_id=?", (did,))
    check([float(x[0]) for x in amt] == [-200.0] and d.get("overpaid") == "395.00" and d.get("state") == "partial",
          f"{who}: stored as -200, 395 left, partial {amt} {d.get('overpaid')} {d.get('state')}")
    cf = s.get(B + O + f"/cashflow?from={TODAY[:7]}&months=1").json()
    ent = [e for e in cf.get("entries", []) if e.get("kind") == "refund" and e.get("doc_id") == did]
    check(ent and ent[0]["dir"] == "out" and ent[0]["amount"] == "200.00", f"{who}: cash flow: the refund goes out {ent}")
    after = ustva(s, "y").get("kz", {}).get("81")
    check(int(after) - int(before) in (-168, -169), f"{who}: cash basis: the refund lowers field 81 by 168 ({before} -> {after})")
    check(s.post(B + f"{D}/{did}/payments", json={"date": TODAY, "amount": 395}).status_code == 201, f"{who}: the rest refunded")
    d = s.get(B + f"{D}/{did}").json()
    check(d.get("status") == "paid" and d.get("overpaid") == "0.00", f"{who}: paid back in full = paid {d.get('status')} {d.get('overpaid')}")
    d2 = neg_final(s, who, -100)
    r = s.post(B + f"{D}/{d2}/credit")
    check(r.status_code == 201, f"{who}: credit note draft on the negative final invoice " + r.text[:200])
    cr = r.json()["id"]
    r = s.post(B + f"{D}/{cr}/finalize")
    check(r.ok, f"{who}: the (negative) credit note is finalised " + r.text[:200])
    check(s.get(B + f"{D}/{d2}").json().get("status") == "cancelled", f"{who}: the negative final invoice is cancelled by it")


r13b_office(A, f"org:{ORG}", "Alpha")
r13b_office(Fr, "private", "Frida")
fees(A, "Alpha")
fees(Fr, "Frida")
neg_rest(A, "Alpha")
neg_rest(Fr, "Frida")


# ---------------------------------------------------------------- travel receipts with input tax
def travel_vat(s, who):
    day = f"{Y}-04-02"
    r = s.post(B + O + "/trips", json={"date_from": day, "dest": "Hamburg - Berlin", "purpose": "job",
                                       "items": [{"date": day, "category": "train", "amount": "107", "vat_pct": "7"},
                                                 {"date": day, "category": "hotel", "amount": "119", "vat_pct": "19"},
                                                 {"date": day, "category": "taxi", "amount": "20"}]})
    check(r.status_code == 201, f"{who}: a trip with VAT rates " + r.text[:200])
    t = r.json()
    by = {x["category"]: x for x in t.get("items", [])}
    check(by.get("train", {}).get("vat_pct") == "7" and by.get("taxi", {}).get("vat_pct") is None, f"{who}: the rates are kept {list(by.values())[:3]}")
    r = s.patch(B + O + f"/trips/{t['id']}/items/{by['taxi']['id']}", json={"vat_pct": "16"})
    check(r.status_code == 400, f"{who}: a wrong rate answers 400 {r.status_code}")
    eu = s.get(B + O + f"/books/euer?year={Y}").json()
    ex = {x["key"]: x for x in eu["expenses"]}
    check(ex.get("t:train", {}).get("net") == "100.00" and ex.get("t:train", {}).get("vat") == "7.00"
          and ex.get("t:hotel", {}).get("net") == "100.00" and ex.get("t:hotel", {}).get("vat") == "19.00"
          and ex.get("t:taxi", {}).get("net") == "20.00" and ex.get("t:taxi", {}).get("vat") == "0.00",
          f"{who}: income statement: travel receipts net + input tax {[ex.get(k) for k in ('t:train', 't:hotel', 't:taxi')]}")
    d = ustva(s, "m04")
    check(d.get("kz", {}).get("66") == "26.00", f"{who}: field 66 with the travel input tax 7 + 19 {d.get('kz')}")
    check(len([x for x in d.get("items", []) if x.get("kind") == "travel"]) == 2, f"{who}: the two travel receipts are listed {d.get('items')}")


travel_vat(A, "Alpha")
travel_vat(Fr, "Frida")

print(f"p2545_c_buero: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
