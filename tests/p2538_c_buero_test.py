#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.538.0 C (#4368): reverse charge without the client's country, Monaco, the cash book's dead end. Invented names only.
freelancer-matrix: office
 - reverse charge for a client without a country is not finalised (400 that names the client's country); with the country it is;
   a correction of such an older document stays possible
 - a client in Monaco is an EU case (one VAT territory with France, Art. 7 of Directive 2006/112/EC): reverse charge is finalised
   (was refused as a third country) and counts in field 21, not 45
 - the cash book: without the special pay an entry on an invoice is refused before it is written, with a message that says what
   to do (book it without the invoice); the links list then has no invoices and invoices_allowed false (the dialog hides the
   choice); cancelling an entry that booked a payment says why it is refused; with pay all as before
 - a person without an organisation (own office): the same refusal and Monaco rule, the cash book's invoices allowed
usage: p2538_c_buero_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402
import testclock  # noqa: E402

O, R = "/api/office", "/api/office/rights"
D = O + "/docs"
FEAT = "cal,comments,collab,clients,office,docs,files,contacts"
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051",
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
TD = testclock.today().isoformat()
PERIOD = "m" + TD[5:7]
YEAR = TD[:4]
NV = {"vat_mode": "novat", "vat_note": "reverse"}

kt.fresh(prefix="P2538C")
assert kt.sess(None).post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})


def office(s):
    r = s.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR", "vat_basis": "soll", "payment_days": 14})
    check(r.ok, "setup: office settings " + r.text[:200])


def client(s, name, country, vat_id=""):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Weg 1", "zip": "98000", "city": "Ort", "country": country, "vat_id": vat_id})
    assert r.ok, r.text
    return r.json()["id"]


def draft(s, cl, rate=100, extra=None):
    r = s.post(B + D, json=dict({"kind": "invoice", "client_id": cl, "service_from": TD, "service_to": TD,
                                 "items": [{"title": "Schnitt", "qty": 1, "rate": rate}]}, **(extra or {})))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def dbw(sql, args):
    c = kt._dbx.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def ustva(s):
    return s.get(B + O + f"/books/ustva?year={YEAR}&period={PERIOD}").json()["kz"]


def reverse_rules(s, who):
    """The reverse charge part for s (an organisation's admin or a person without one)."""
    office(s)
    # no country: the tax case would be a guess (counted as section 13b at home before)
    cx = client(s, "Ohneland GmbH", "", "DE888888888")
    rx = draft(s, cx, extra=NV)
    r = s.post(B + f"{D}/{rx}/finalize")
    check(r.status_code == 400 and "client's country (reverse charge)" in r.json().get("error", ""),
          f"{who}: reverse charge without the client's country refused {r.status_code} {r.text[:200]}")
    check(not s.get(B + f"{D}/{rx}").json().get("locked"), f"{who}: the refused draft stays a draft")
    check(s.patch(B + f"/api/clients/{cx}", json={"country": "DE"}).ok, f"{who}: country given")
    r = s.post(B + f"{D}/{rx}/finalize")
    check(r.ok, f"{who}: with the country (DE, section 13b) finalised " + r.text[:200])
    # an older document without a country (finalised before the rule): its correction stays possible
    cy = client(s, "Altkunde GmbH", "DE", "DE777777777")
    ry = draft(s, cy, extra=NV)
    check(s.post(B + f"{D}/{ry}/finalize").ok, f"{who}: (older document) finalised")
    dbw("UPDATE clients SET country='' WHERE id=?", (cy,))
    r = s.post(B + f"{D}/{ry}/credit")
    check(r.status_code == 201, f"{who}: correction draft of the older document " + r.text[:200])
    r = s.post(B + f"{D}/{r.json().get('id')}/finalize")
    check(r.ok, f"{who}: the correction of a document without country is finalised " + r.text[:200])
    # Monaco = France for VAT: an EU case
    cm = client(s, "Exemple SAM", "MC", "FR12345678901")
    k0 = ustva(s)
    rm = draft(s, cm, rate=300, extra=NV)
    r = s.post(B + f"{D}/{rm}/finalize")
    check(r.ok, f"{who}: reverse charge for a client in Monaco finalised (EU, not a third country) " + r.text[:200])
    k = ustva(s)
    d21 = int(k.get("21") or 0) - int(k0.get("21") or 0)
    d45 = int(k.get("45") or 0) - int(k0.get("45") or 0)
    check(d21 == 300 and d45 == 0, f"{who}: Monaco in field 21, not 45 (21 +{d21}, 45 +{d45}) {k}")
    # Switzerland stays a third country (#4081)
    cc = client(s, "Muster AG", "CH", "CHE-123.456.788")
    r = s.post(B + f"{D}/{draft(s, cc, extra=NV)}/finalize")
    check(r.status_code == 400 and "third country" in r.text, f"{who}: Switzerland still a third country " + r.text[:200])


reverse_rules(A, "org")


# ---------------------------------------------------------------- the cash book
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


def status(s, did):
    return s.get(B + f"{D}/{did}").json().get("status")


def invoice(s):
    d = draft(s, client(s, "Barkunde AG", "DE"))
    r = s.post(B + f"{D}/{d}/finalize")
    assert r.ok, r.text
    return d


CASH = person("gus", {"cashbook": "edit"}, [])
CASHPAY = person("pia", {"cashbook": "edit", "offers": "edit"}, ["pay"])
CB = A.post(B + O + "/cashbooks", json={"name": "Hauptkasse", "opening": "500.00", "opening_day": TD}).json()["id"]
ENTRIES = f"{O}/cashbooks/{CB}/entries"
I1 = invoice(A)

ln = CASH.get(B + O + "/cashbooks/links").json()
check(ln.get("invoices_allowed") is False and ln.get("invoices") == [], f"cash book without pay: no invoices to pick, invoices_allowed false {ln}")
ln = CASHPAY.get(B + O + "/cashbooks/links").json()
check(ln.get("invoices_allowed") is True and any(i["id"] == I1 for i in ln.get("invoices") or []), "cash book with pay: the invoices to pick")

count = lambda: kt.dbx("SELECT COUNT(*), COALESCE(MAX(no), 0) FROM office_cash_entries WHERE book_id=?", (CB,))[0]  # noqa: E731
before = count()
body = {"day": TD, "dir": "in", "amount": "119.00", "text": "Barzahlung", "vat_pct": "19", "invoice_id": I1}
r = CASH.post(B + ENTRIES, json=body)
check(r.status_code == 403 and "book the cash without the invoice" in r.json().get("error", ""),
      f"cash book without pay: an entry on an invoice refused with a message that says what to do {r.status_code} {r.text[:200]}")
check(tuple(count()) == tuple(before), f"refused: no entry written, no number used {count()} {before}")
check(not kt.dbx("SELECT 1 FROM office_payments WHERE doc_id=?", (I1,)), "refused: no payment on the invoice")
r = CASH.post(B + ENTRIES, json={**body, "invoice_id": None})
check(r.status_code == 201, "the same cash without the invoice is booked " + r.text[:200])
r = CASHPAY.post(B + ENTRIES, json=body)
check(r.status_code == 201 and status(A, I1) == "paid", f"with pay: the payment is booked {r.status_code} {status(A, I1)}")
E1 = r.json().get("id")
before = count()
r = CASH.post(B + f"{O}/cash-entries/{E1}/cancel", json={"day": TD})
check(r.status_code == 403 and "takes the payment back" in r.json().get("error", ""),
      f"cancelling an entry that booked a payment: refused with the reason {r.status_code} {r.text[:200]}")
check(tuple(count()) == tuple(before) and status(A, I1) == "paid", "refused cancel: no counter entry, the invoice stays paid")
r = CASHPAY.post(B + f"{O}/cash-entries/{E1}/cancel", json={"day": TD})
check(r.status_code == 201 and status(A, I1) != "paid", f"with pay: cancelled, the invoice open again {r.status_code}")

# ---------------------------------------------------------------- a person without an organisation: their own admin
FID, Fr = freelancer(B, A, features=FEAT)
Fr.patch(B + "/api/settings", json={"workspace": "private"})
reverse_rules(Fr, "freelancer")
ln = Fr.get(B + O + "/cashbooks/links").json()
check(ln.get("invoices_allowed") is True, f"freelancer: the cash book's invoices allowed {ln.get('invoices_allowed')}")
FCB = Fr.post(B + O + "/cashbooks", json={"name": "Kasse", "opening": "10.00", "opening_day": TD}).json()["id"]
FI = invoice(Fr)
r = Fr.post(B + f"{O}/cashbooks/{FCB}/entries", json={**body, "invoice_id": FI})
check(r.status_code == 201 and status(Fr, FI) == "paid", "freelancer: a cash entry on an invoice books the payment " + r.text[:160])

print(f"p2538_c_buero: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
