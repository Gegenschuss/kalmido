#!/usr/bin/env python3
# kalmido-suite: now=2027-02-15T10:00:00+01:00
"""2.589.0 API tests, part C (#3458): the tax check before filing (traffic light). Invented companies, people and figures only.
tenant-matrix: office  freelancer-matrix: office
 - EUeR income against the advance returns and the annual VAT return: a difference is red and carries its amount
 - a jump to the year before (percent AND euros) is yellow, the line named
 - checked fields: entertainment in a plain receipt category, a device receipt above the GWG limit outside the depreciation
 - bookings without a receipt (an open payment from the account), open money in, receipts without a bank booking
 - formalities: a missing tax number is red, a corporation (GmbH) is red; quotas are never red
 - red blocks nothing (the tax forms answer as before); a member 403, another office's figures never
 - a person without organisation with clean data: every point green
usage: p2589_c_taxcheck_test.py <datadir>      (P2589C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

O = "/api/office"
D = O + "/docs"
TC = "/api/office/books/taxcheck"  # the literal path: tests/tenant_coverage_test.py finds the route here
FEAT = "cal,comments,collab,office,clients,docs"


def dbw(sql, args=()):
    c = kt._dbx.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


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


def receipt(s, ws, name, amount, day, vat, cat):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": cat, "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def invoice(s, client, net, day, paid):
    r = s.post(B + D, json={"kind": "invoice", "client_id": client, "service_from": day, "service_to": day,
                            "items": [{"title": "Schnitt", "qty": 1, "rate": net}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    dbw("UPDATE office_docs SET date=? WHERE id=?", (day, did))
    gross = s.get(B + f"{D}/{did}").json()["totals"]["gross"]
    r = s.post(B + f"{D}/{did}/payments", json={"amount": str(gross), "date": paid})
    assert r.ok, r.text
    return did


def pt(d, key):
    return next((p for p in d["points"] if p["punkt"] == key), None)


def amp(d, key):
    p = pt(d, key)
    return p["ampel"] if p else None


kt.fresh(prefix="P2589C")
kt.docker_logs_on_first_fail()
A = kt.setup()
assert A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"}).ok
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
COMPANY = {"name": "Studio Beispiel", "street": "Teststrasse 1", "zip": "20000", "city": "Hamburg", "country": "DE",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank", "tax_number": "12/345/67890"}
r = A.put(B + O + "/settings", json={"small_business": 0, "vat_basis": "soll", "currency": "EUR", "company_fields": COMPANY})
assert r.ok, r.text
assert A.put(B + O + "/tax-dates", json={"ustva": "quarter"}).ok
C1 = A.post(B + "/api/clients", json={"name": "Beispielkunde", "street": "Marktstrasse 5", "zip": "50000", "city": "Koeln", "country": "DE"}).json()["id"]
# accrual basis: an invoice of December 2025 paid in January 2026 -> in the EUeR 2026 (cash), in the advance returns of 2025
invoice(A, C1, 1000, "2025-12-10", "2026-01-15")
invoice(A, C1, 1000, "2026-03-10", "2026-03-20")
WS = f"org:{ORG}"
receipt(A, WS, "fremd2025.pdf", "1190.00", "2025-05-05", "19", "Fremdleistungen")
receipt(A, WS, "fremd2026.pdf", "11900.00", "2026-05-05", "19", "Fremdleistungen")  # +900 %, +9,000: a jump
receipt(A, WS, "essen.pdf", "119.00", "2026-06-01", "19", "Bewirtung")  # entertainment as a plain receipt: in full
receipt(A, WS, "laptop.pdf", "1785.00", "2026-07-01", "19", "Computer")  # 1,500 net > 800: no depreciation
for tag, day, amount in (("out1", "2026-08-01", "-50.00"), ("in1", "2026-09-01", "300.00")):
    dbw("INSERT INTO office_bank_tx(org_id, day, amount, currency, counterpart, purpose, hash, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (ORG, day, amount, "EUR", "Someone", "x", "p2589c-" + tag, "2026-10-01T10:00:00Z"))

assert A.put(B + O + "/settings", json={"company_fields": {"tax_number": ""}}).ok  # finalising needed it; the check must miss it
# ---------------------------------------------------------------- rights
check(Bo.get(B + TC + "?year=2026").status_code == 403, "a member cannot read the tax check (403)")
r = A.get(B + TC + "?year=2026")
check(r.ok, "the office admin " + r.text[:300])
d = r.json()
print({p["punkt"]: p["ampel"] for p in d["points"]})
check(all(set(p) >= {"punkt", "ampel", "text", "link", "title", "group"} for p in d["points"]), "every point: punkt, ampel, text, link")
check(all(p["ampel"] in ("green", "yellow", "red") for p in d["points"]), "only green / yellow / red")
check(d["counts"]["red"] == sum(p["ampel"] == "red" for p in d["points"]), "the counts")
check("No tax advice; figures without guarantee." in d["notes"], "the note")

# ---------------------------------------------------------------- comparison
p = pt(d, "ustva")
check(p and p["ampel"] == "red" and p["amount"] == "1000.00" and "1,000.00" in p["text"], f"advance returns: red with the amount {p}")
check(p and p["link"] == "#office/books/ustva", "advance returns: the link to the VAT return figures")
p = pt(d, "ust_year")
check(p and p["ampel"] == "red" and p["amount"] == "1000.00", f"annual VAT return: red with the amount {p}")
check(p and p["link"] == "#office/books/taxforms/ust", "annual VAT return: the link")
check(A.get(B + O + "/books/taxform/ust?year=2026").ok and A.get(B + O + "/books/taxform/euer.pdf?year=2026").ok, "red blocks nothing: the forms answer")

# ---------------------------------------------------------------- year before
p = pt(d, "jumps")
check(p and p["ampel"] == "yellow" and any("Fremdleistungen" in x for x in p["details"]), f"a jump to the year before: yellow, named {p}")
check(p and "+900 %" in " ".join(p["details"]), f"the jump in percent {p and p['details']}")

# ---------------------------------------------------------------- quotas: hints only
check(amp(d, "quota") == "yellow", f"quotas above the usual: yellow, never red {pt(d, 'quota')}")

# ---------------------------------------------------------------- checked fields
p = pt(d, "meals")
check(p and p["ampel"] == "yellow" and "essen.pdf" in p["details"] and p["link"] == "#office/meals", f"entertainment in full: yellow {p}")
p = pt(d, "gwg")
check(p and p["ampel"] == "yellow" and "laptop.pdf" in p["details"] and p["link"] == "#office/equipment", f"a device above the GWG limit: yellow {p}")
check(amp(d, "gifts") == "green" and amp(d, "car") == "green" and amp(d, "room") == "green", "gifts, car, study: green without such receipts")
check(amp(d, "reverse") == "green", "no reverse charge: green")

# ---------------------------------------------------------------- receipts
p = pt(d, "no_receipt")
check(p and p["ampel"] == "yellow" and "1 booking" in p["text"] and p["link"] == "#office/bank", f"a payment from the account without a receipt {p}")
check(amp(d, "bank_open") == "yellow", f"open money in: yellow {pt(d, 'bank_open')}")
p = pt(d, "no_booking")
check(p and p["ampel"] == "yellow" and "3 receipts" in p["text"], f"receipts of 2026 without a bank booking {p}")

# ---------------------------------------------------------------- formalities
p = pt(d, "tax_number")
check(p and p["ampel"] == "red" and p["link"] == "setgo:biz-company", f"no tax number: red, the link to the company details {p}")
check(amp(d, "legal_form") == "green", "a sole proprietor: green")
assert A.put(B + O + "/settings", json={"company_fields": dict(COMPANY, name="Studio Beispiel GmbH", tax_number="12345678901")}).ok
d2 = A.get(B + TC + "?year=2026").json()
check(amp(d2, "legal_form") == "red", f"a GmbH: red (balance sheet, no EUeR) {pt(d2, 'legal_form')}")
check(amp(d2, "tax_number") == "green", "a tax number: green")
assert A.put(B + O + "/settings", json={"company_fields": dict(COMPANY, tax_number="12-ab")}).ok  # back to no GmbH
check(amp(A.get(B + TC + "?year=2026").json(), "tax_number") == "yellow", "a tax number of the wrong shape: yellow")
check(A.get(B + TC + "?year=1999").status_code == 400, "a bad year: 400")

# ---------------------------------------------------------------- a person without organisation, clean data: all green
FID, Fr = freelancer(B, A)
r = Fr.put(B + O + "/settings", json={"small_business": 0, "vat_basis": "ist", "currency": "EUR",
                                      "company_fields": dict(COMPANY, name="Frida Beispiel")})
assert r.ok, r.text
assert Fr.put(B + O + "/tax-dates", json={"ustva": "quarter"}).ok
FC = Fr.post(B + "/api/clients", json={"name": "Kundin Beispiel", "street": "Weg 2", "zip": "10000", "city": "Berlin", "country": "DE"}).json()["id"]
for yr in (2025, 2026):
    invoice(Fr, FC, 1000, f"{yr}-03-10", f"{yr}-03-20")
    receipt(Fr, "private", f"soft{yr}.pdf", "119.00", f"{yr}-04-01", "19", "Software")
r = Fr.get(B + TC + "?year=2026")
check(r.ok, "freelancer: the tax check " + r.text[:300])
f = r.json()
bad = {p["punkt"]: (p["ampel"], p["text"]) for p in f["points"] if p["ampel"] != "green"}
check(not bad, f"freelancer, clean data: every point green {bad}")
check({"ustva", "ust_year", "jumps", "quota", "meals", "gifts", "car", "room", "gwg", "reverse", "no_receipt", "no_booking", "tax_number",
       "period", "legal_form", "details"} <= {p["punkt"] for p in f["points"]}, "freelancer: every point is there")
check(f["counts"]["red"] == 0 and f["counts"]["yellow"] == 0, "freelancer: no red, no yellow")
check(pt(f, "ustva")["amount"] is None, "green: no amount")
# alice's office stays apart
check(amp(A.get(B + TC + "?year=2026").json(), "ustva") == "red", "alice's office: still her own figures")

sys.exit(kt.done("p2589_c_taxcheck"))
