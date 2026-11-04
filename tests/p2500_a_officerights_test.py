#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.500.0 (#4072): the rest of the office rights. Invented names only.
freelancer-matrix: office
 (a) a cash book entry on an invoice books a payment: with cash book edit alone 403, nothing written, the invoice stays open; cash
     without an invoice stays free; quotes edit + the special pay books it; cancelling such an entry takes the payment back: the same right
 (b) bank matching kind card needs cards edit, kind payout receipts edit (it writes the fees' receipt)
 (c) the tax forms as files and the booking archive's original files need the special export; the forms as a page stay readable
 - the office admin and a person without an organisation (personal office): as before
usage: p2500_a_officerights_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402
import testclock  # noqa: E402

O, R = "/api/office", "/api/office/rights"
FEAT = "cal,comments,collab,clients,office,docs,files,contacts"
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051",
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
TD = testclock.today().isoformat()

kt.fresh(prefix="P2500A")
assert kt.sess(None).post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})
check(r.ok, "setup: office settings " + r.text[:200])


def person(name, levels, specials):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": name, "display_name": name.title(),
                                       "password": "password123", "email": f"{name}@example.com"})
    assert r.ok, r.text
    uid = r.json()["id"]
    r = A.post(B + f"{R}/groups", json={"from": "tpl:none", "name": "Group " + name})
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    r = A.patch(B + f"{R}/groups/{gid}", json={"levels": levels, "specials": specials})
    assert r.ok, r.text
    r = A.put(B + f"{R}/people/{uid}", json={"groups": [f"g:{gid}"]})
    assert r.ok, r.text
    s = sess(name)
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT, "workspace": f"org:{ORG}"})
    return s


def invoice(s, org=None):
    b = {"name": "Example Client AG", "email": "buyer@example.com", "street": "Marktstrasse 5", "zip": "50667", "city": "Koeln", "country": "DE"}
    cl = s.post(B + "/api/clients", json={**b, **({"org_id": org} if org else {})}).json()["id"]
    d = s.post(B + O + "/docs", json={"kind": "invoice", "client_id": cl, "service_from": TD, "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]}).json()["id"]
    r = s.post(B + f"{O}/docs/{d}/finalize")
    assert r.ok, r.text
    return d


def status(s, did):
    return s.get(B + f"{O}/docs/{did}").json().get("status")


def dbw(sql, args):
    c = kt._dbx.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def tx(org, tag, amount="100.00"):
    dbw("INSERT INTO office_bank_tx(org_id, day, amount, currency, counterpart, purpose, hash, created_at) VALUES(?,?,?,?,?,?,?,?)",
           (org, TD, amount, "EUR", "Someone", "x", tag, "2026-05-02T10:00:00Z"))
    return kt.dbx("SELECT id FROM office_bank_tx WHERE org_id=? AND hash=?", (org, tag))[0][0]


CASH = person("gus", {"cashbook": "edit"}, [])
CASHPAY = person("pia", {"cashbook": "edit", "offers": "edit"}, ["pay"])
BANK = person("ben", {"bank": "edit"}, ["pay"])
BANKALL = person("bea", {"bank": "edit", "cards": "edit", "receipts": "edit"}, ["pay"])
READER = person("rob", {"books": "view"}, [])
EXPORT = person("eva", {"books": "view"}, ["export"])

# ---------------------------------------------------------------- (a) the cash book
CB = A.post(B + O + "/cashbooks", json={"name": "Hauptkasse", "opening": "500.00", "opening_day": TD}).json()["id"]
ENTRIES = f"{O}/cashbooks/{CB}/entries"
I1 = invoice(A, ORG)
before = kt.dbx("SELECT COUNT(*) FROM office_cash_entries WHERE book_id=?", (CB,))[0][0]
body = {"day": TD, "dir": "in", "amount": "119.00", "text": "Barzahlung", "vat_pct": "19", "invoice_id": I1}
r = CASH.post(B + ENTRIES, json=body)
check(r.status_code == 403, f"(a) cash book edit alone: an entry on an invoice 403, {r.status_code} {r.text[:160]}")
check(kt.dbx("SELECT COUNT(*) FROM office_cash_entries WHERE book_id=?", (CB,))[0][0] == before, "(a) refused: no entry written")
check(not kt.dbx("SELECT 1 FROM office_payments WHERE doc_id=?", (I1,)), "(a) refused: no payment on the invoice")
r = CASH.post(B + ENTRIES, json={"day": TD, "dir": "out", "amount": "5.00", "text": "Porto", "vat_pct": "0"})
check(r.status_code == 201, "(a) cash without an invoice stays free " + r.text[:160])
EP = r.json().get("id")
# 2.533.0 (#4337): choosing the invoice while editing books the payment too, so it needs the same right
r = CASH.patch(B + f"{O}/cash-entries/{EP}", json={"dir": "in", "invoice_id": I1})
row = kt.dbx("SELECT dir, invoice_id FROM office_cash_entries WHERE id=?", (EP,))[0]
check(r.status_code == 403 and tuple(row) == ("out", None) and status(A, I1) != "paid",
      f"(a) #4337 cash book edit alone: editing an entry onto an invoice 403, nothing changed {r.status_code} {tuple(row)} {r.text[:160]}")
r = CASHPAY.post(B + ENTRIES, json=body)
check(r.status_code == 201 and status(A, I1) == "paid", f"(a) quotes edit + pay: books the payment {r.status_code} {status(A, I1)}")
E1 = r.json().get("id")
r = CASH.post(B + f"{O}/cash-entries/{E1}/cancel", json={"day": TD})
check(r.status_code == 403 and status(A, I1) == "paid", f"(a) cancelling takes the payment back: cash book edit alone 403 {r.status_code}")
r = CASHPAY.post(B + f"{O}/cash-entries/{E1}/cancel", json={"day": TD})
check(r.status_code == 201 and status(A, I1) != "paid", f"(a) with pay: cancelled, the invoice open again {r.status_code}")
I2 = invoice(A, ORG)
r = A.post(B + ENTRIES, json={**body, "invoice_id": I2})
check(r.status_code == 201 and status(A, I2) == "paid", "(a) the office admin as before " + r.text[:160])

# ---------------------------------------------------------------- (b) bank matching
T1, T2 = tx(ORG, "p2500-1"), tx(ORG, "p2500-2")
r = BANK.post(B + f"{O}/bank/tx/{T1}/match", json={"kind": "card", "id": 999999})
check(r.status_code == 403, f"(b) no cards area: kind card 403, {r.status_code} {r.text[:160]}")
r = BANK.post(B + f"{O}/bank/tx/{T1}/match", json={"kind": "payout"})
check(r.status_code == 403, f"(b) no receipts area: kind payout 403, {r.status_code} {r.text[:160]}")
check(not kt.dbx("SELECT match_kind FROM office_bank_tx WHERE id=?", (T1,))[0][0], "(b) refused: the booking stays unmatched")
r = BANK.post(B + f"{O}/bank/tx/{T1}/match", json={"kind": "ignored"})
check(r.ok, "(b) a kind without a second area stays free " + r.text[:160])
r = BANKALL.post(B + f"{O}/bank/tx/{T2}/match", json={"kind": "card", "id": 999999})
check(r.status_code == 404, f"(b) cards edit: past the right (no such statement) {r.status_code} {r.text[:160]}")
r = BANKALL.post(B + f"{O}/bank/tx/{T2}/match", json={"kind": "payout"})
check(r.ok, "(b) receipts edit: payout matched " + r.text[:160])

# ---------------------------------------------------------------- (c) the files
A.post(B + f"{O}/bank/tx/{T2}/unmatch")
FILES = [f"{O}/books/taxform/{k}.{x}?year={TD[:4]}" for k in ("euer", "ust") for x in ("csv", "pdf")]
for u in FILES:
    r = READER.get(B + u)
    check(r.status_code == 403, f"(c) no export: {u} 403, {r.status_code}")
    r = EXPORT.get(B + u)
    check(r.ok, f"(c) with export: {u} {r.status_code} {r.text[:120]}")
    check(A.get(B + u).ok, f"(c) the office admin: {u}")
for k in ("euer", "ust"):
    r = READER.get(B + f"{O}/books/taxform/{k}?year={TD[:4]}")
    check(r.ok, f"(c) the form {k} as a page stays readable {r.status_code}")
r = READER.get(B + f"{O}/books/archive/files/999999")
check(r.status_code == 403, f"(c) no export: an archive's original file 403, {r.status_code}")
r = EXPORT.get(B + f"{O}/books/archive/files/999999")
check(r.status_code == 404, f"(c) with export: past the right (no such file) {r.status_code}")

# ---------------------------------------------------------------- a person without an organisation: their own admin
FID, Fr = freelancer(B, A, features=FEAT)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
r = Fr.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})
check(r.ok, "freelancer: office settings " + r.text[:200])
PB = kt.dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))[0][0]
FCB = Fr.post(B + O + "/cashbooks", json={"name": "Kasse", "opening": "10.00", "opening_day": TD}).json()["id"]
FI = invoice(Fr)
r = Fr.post(B + f"{O}/cashbooks/{FCB}/entries", json={**body, "invoice_id": FI})
check(r.status_code == 201 and status(Fr, FI) == "paid", "freelancer: a cash entry on an invoice books the payment " + r.text[:160])
r = Fr.post(B + f"{O}/cash-entries/{r.json().get('id')}/cancel", json={"day": TD})
check(r.status_code == 201, "freelancer: and cancels it " + r.text[:160])
FT1, FT2 = tx(PB, "p2500-f1"), tx(PB, "p2500-f2")
check(Fr.post(B + f"{O}/bank/tx/{FT1}/match", json={"kind": "card", "id": 999999}).status_code == 404, "freelancer: kind card past the right (no such statement)")
check(Fr.post(B + f"{O}/bank/tx/{FT2}/match", json={"kind": "payout"}).ok, "freelancer: kind payout")
for u in FILES:
    check(Fr.get(B + u).ok, f"freelancer: {u}")
check(Fr.get(B + f"{O}/books/archive/files/999999").status_code == 404, "freelancer: archive file past the right")

print(f"p2500_a: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
