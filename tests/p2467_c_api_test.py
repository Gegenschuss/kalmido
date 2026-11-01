#!/usr/bin/env python3
"""2.467.0 API tests, part C (#3456): Anlage EUeR and annual VAT return line by line. Invented companies, people and figures only.
tenant-matrix: office  freelancer-matrix: office
 - the lines depend on the tax year (table per year): the same receipt stands on another line in 2025 and 2026
 - the sums equal bk_euer: Kz 159 = income gross + refund, Kz 199 = expenses gross + VAT paid; the difference to the profit is named
 - a category without a line of its own lands in "other expenses", never on a guessed line
 - VAT paid / refunded: entered per year by the office admin, a member 403, bad values 400, another year untouched
 - annual return: bases / input tax = bk_ustva(y), advance payments 0 in the rhythm "year", the sum of the quarters in "quarter"
 - unknown year: a clear note, no lines; CSV / PDF 400
 - small business: no VAT lines, no annual return; the note on no tax advice always, also in CSV
 - the yearly tax task links the new view (regression: it linked the advance return)
 - a person without organisation does all of it, and the areas stay apart
usage: p2467_c_api_test.py <datadir>      (P2467C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import shutil
import subprocess
import sys
from decimal import Decimal

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
D = O + "/docs"
BK = O + "/books"
TF = BK + "/taxform"
NOTE = "No tax advice; figures without guarantee."


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


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


def receipt(s, ws, name, amount, day, vat, cat="Software"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": cat, "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def invoice(s, client, items, day):
    r = s.post(B + D, json={"kind": "invoice", "client_id": client, "service_from": day, "service_to": day, "items": items})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    dbx("UPDATE office_docs SET date=? WHERE id=?", (day, did), write=True)
    return did


def line(d, kz):
    """The row of a Kennzahl; None when the form shows no such row."""
    return next((r for r in d["rows"] if r["kz"] == str(kz)), None)


def key(d, k):
    return next((r for r in d["rows"] if r["key"] == k), None)


def pay(s, did, day):
    r = s.get(B + f"{D}/{did}").json()
    gross = r.get("totals", {}).get("gross") or r.get("gross")
    p = s.post(B + f"{D}/{did}/payments", json={"amount": str(gross), "date": day})
    assert p.ok, p.text


if os.environ.get("P2467C_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
assert A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"}).ok
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
COMPANY = {"name": "Studio Beispiel GmbH", "street": "Teststrasse 1", "zip": "20000", "city": "Hamburg", "country": "DE", "tax_number": "12/345/67890",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
assert A.put(B + O + "/settings", json={"small_business": 0, "vat_basis": "soll", "currency": "EUR", "company_fields": COMPANY}).ok
C1 = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstrasse 5", "zip": "50000", "city": "Koeln", "country": "DE"}).json()["id"]
I1 = invoice(A, C1, [{"title": "Schnitt", "qty": 2, "rate": 500}], "2025-02-10")
I2 = invoice(A, C1, [{"title": "Grafik", "qty": 1, "rate": 500}], "2026-02-10")
pay(A, I1, "2025-03-01")
pay(A, I2, "2026-03-01")
WSO = f"org:{ORG}"
for yr in (2025, 2026):
    receipt(A, WSO, f"miete{yr}.pdf", "119.00", f"{yr}-05-05", "19", "Miete")
    receipt(A, WSO, f"sonst{yr}.pdf", "119.00", f"{yr}-06-05", "19", "Miete und mehr")  # no exact name: never the rent line

# ---------------------------------------------------------------- Anlage EUeR: lines per year, sums
for yr, rent_line, pre_line, other_line, out_line in ((2025, 39, 57, 60, 75), (2026, 40, 58, 61, 76)):
    r = A.get(B + TF + f"/euer?year={yr}")
    check(r.ok and r.json()["known"], f"{yr}: known " + r.text[:200])
    d = r.json()
    e = A.get(B + BK + f"/euer?year={yr}").json()
    check(line(d, 150) and line(d, 150)["line"] == rent_line and line(d, 150)["amount"] == "100.00", f"{yr}: rent on line {rent_line} net {line(d, 150)}")
    check(line(d, 183) and line(d, 183)["line"] == other_line and line(d, 183)["amount"] == "100.00", f"{yr}: the free category in other expenses {line(d, 183)}")
    check(line(d, 185) and line(d, 185)["line"] == pre_line and line(d, 185)["amount"] == e["expense_total"]["vat"], f"{yr}: input tax {line(d, 185)}")
    check(line(d, 112)["amount"] == e["income_total"]["net"] and line(d, 140)["amount"] == e["income_total"]["vat"], f"{yr}: income net and VAT")
    check(line(d, 159)["amount"] == e["income_total"]["gross"], f"{yr}: Kz 159 = income gross")
    check(line(d, 199)["amount"] == e["expense_total"]["gross"] and line(d, 199)["line"] == out_line, f"{yr}: Kz 199 = expenses gross")
    check(Decimal(d["profit"]) - Decimal(e["profit"]) == Decimal(e["income_total"]["vat"]) - Decimal(e["expense_total"]["vat"]) == Decimal(d["vat_balance"]),
          f"{yr}: the difference to the profit is the VAT balance {d['profit']} {e['profit']} {d['vat_balance']}")
    amounts = sum(Decimal(x["amount"]) for x in d["rows"] if not x["sum"] and x["key"] in ("small", "taxed", "free", "vat_in", "vat_back"))
    check(amounts == Decimal(line(d, 159)["amount"]), f"{yr}: income lines add up to Kz 159")
    check(sum(Decimal(x["amount"]) for x in d["rows"] if not x["sum"] and x["line"] > line(d, 159)["line"]) == Decimal(line(d, 199)["amount"]), f"{yr}: expense lines add up to Kz 199")
    check(NOTE in d["notes"], f"{yr}: the note")
    check(line(d, 186) is not None and line(d, 141) is not None, f"{yr}: VAT paid and refunded shown at 0")

# ---------------------------------------------------------------- VAT paid / refunded
check(Bo.get(B + TF + "/euer?year=2025").status_code == 403 and Bo.get(B + TF + "/ust?year=2025").status_code == 403, "a member cannot read (403)")
check(Bo.put(B + TF + "/vat", json={"year": 2025, "paid": "1"}).status_code == 403, "a member cannot write (403)")
for bad in ("-1", "abc", "NaN", "Infinity", "1000000000"):
    check(A.put(B + TF + "/vat", json={"year": 2025, "paid": bad}).status_code == 400, f"bad amount {bad}: 400")
check(A.put(B + TF + "/vat", json={"year": 1999, "paid": "1"}).status_code == 400, "bad year: 400")
before = A.get(B + BK + "/euer?year=2025").json()
r = A.put(B + TF + "/vat", json={"year": 2025, "paid": "120,50", "refund": "10.00"})
check(r.ok, "VAT paid stored " + r.text[:200])
d = r.json()
check(line(d, 186)["amount"] == "120.50" and line(d, 141)["amount"] == "10.00", "paid and refund on their lines")
check(Decimal(line(d, 159)["amount"]) == Decimal(before["income_total"]["gross"]) + 10, "the refund is income")
check(Decimal(line(d, 199)["amount"]) == Decimal(before["expense_total"]["gross"]) + Decimal("120.50"), "VAT paid is an expense")
check(A.get(B + BK + "/euer?year=2025").json() == before, "the income/expense statement itself stays")
check(line(A.get(B + TF + "/euer?year=2026").json(), 186)["amount"] == "0.00", "another year untouched")

# ---------------------------------------------------------------- annual VAT return
assert A.put(B + O + "/tax-dates", json={"ustva": "year"}).ok
for yr, l19, lpre, lfinal in ((2026, 24, 85, 126),):
    d = A.get(B + TF + f"/ust?year={yr}").json()
    y = A.get(B + BK + f"/ustva?year={yr}&period=y").json()
    check(d["known"] and line(d, 177)["line"] == l19 and line(d, 177)["base"] == y["kz"]["81"] and line(d, 177)["tax"] == y["tax"]["19"], f"{yr}: Kz 177 {line(d, 177)}")
    check(line(d, 320)["line"] == lpre and line(d, 320)["amount"] == y["kz"]["66"], f"{yr}: Kz 320 {line(d, 320)}")
    check(key(d, "adv")["amount"] == "0.00", f"{yr}: rhythm year: no advance payments")
    check(line(d, 820)["line"] == lfinal and line(d, 820)["amount"] == y["kz"]["83"] == line(d, 816)["amount"], f"{yr}: final = VAT less input tax {line(d, 820)}")
    check(d["basis_code"] == "1", f"{yr}: accrual basis = code 1 of Kz 133")
    check(NOTE in d["notes"], f"{yr}: the note")
assert A.put(B + O + "/tax-dates", json={"ustva": "quarter"}).ok
d = A.get(B + TF + "/ust?year=2026").json()
qs = [A.get(B + BK + f"/ustva?year=2026&period=q{i}").json()["kz"]["83"] for i in range(1, 5)]
check(Decimal(key(d, "adv")["amount"]) == sum(Decimal(q) for q in qs), f"quarters: advance payments are their sum {key(d, 'adv')} {qs}")
check(Decimal(line(d, 820)["amount"]) == Decimal(line(d, 816)["amount"]) - Decimal(key(d, "adv")["amount"]), "final = left minus advance payments")
r = A.put(B + O + "/tax-dates", json={"ustva": "year"})
T = r.json()["tasks"]["ustva"]
check(dbx("SELECT url FROM tasks WHERE id=?", (T,))[0][0].endswith("/#office/books/taxforms/ust"), "the yearly task links the annual return")
check("#office/books/taxforms/ust" in dbx("SELECT content FROM tasks WHERE id=?", (T,))[0][0], "the yearly task text links it too")
r = A.put(B + O + "/tax-dates", json={"ustva": "month"})
check(dbx("SELECT url FROM tasks WHERE id=?", (r.json()["tasks"]["ustva"],))[0][0].endswith("/#office/books/ustva"), "the monthly task stays on the advance return")
assert A.put(B + O + "/tax-dates", json={"ustva": "none"}).ok

# ---------------------------------------------------------------- CSV, PDF, unknown year
for kind in ("euer", "ust"):
    r = A.get(B + TF + f"/{kind}.csv?year=2026")
    check(r.ok and NOTE in r.text and "Please check the figures before filing." in r.text, f"{kind}.csv carries the note")
    r = A.get(B + TF + f"/{kind}.pdf?year=2026")
    check(r.ok and r.content[:4] == b"%PDF", f"{kind}.pdf")
    if os.environ.get("P2467C_SHOTS"):  # shots: 'P2467C_SHOTS'
        f = os.path.join(os.environ["P2467C_SHOTS"], f"{kind}.pdf")
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "wb") as o:
            o.write(r.content)
        if shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-png", "-r", "90", f, f[:-4]], check=False)
    for yr in (2024, 2027):
        r = A.get(B + TF + f"/{kind}?year={yr}")
        j = r.json()
        check(r.ok and j["known"] is False and j["rows"] == [] and str(yr) in j["notes"][0] and NOTE in j["notes"], f"{kind} {yr}: a clear note, no lines {r.text[:200]}")
        check(A.get(B + TF + f"/{kind}.csv?year={yr}").status_code == 400 and A.get(B + TF + f"/{kind}.pdf?year={yr}").status_code == 400, f"{kind} {yr}: no file")
    check(Bo.get(B + TF + f"/{kind}.csv?year=2026").status_code == 403, f"{kind}.csv: a member 403")

j = A.get(B + TF + "/ust?year=2025").json()  # no official form at hand: the note, never lines from a copy
check(j["known"] is False and j["rows"] == [] and A.get(B + TF + "/euer?year=2025").json()["known"], "2025: the annual return has no lines yet, the Anlage EUeR has")

# ---------------------------------------------------------------- a person without organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
assert Fr.put(B + O + "/settings", json={"small_business": 0, "vat_basis": "ist", "currency": "EUR", "company_fields": dict(COMPANY, name="Frida Beispiel")}).ok
receipt(Fr, "private", "fmiete.pdf", "238.00", "2026-04-04", "19", "Miete")
r = Fr.get(B + TF + "/euer?year=2026")
check(r.ok and line(r.json(), 150)["amount"] == "200.00" and line(r.json(), 150)["line"] == 40, "freelancer: the Anlage EUeR " + r.text[:200])
r = Fr.get(B + TF + "/ust?year=2026")
check(r.ok and r.json()["basis_code"] == "2" and line(r.json(), 320)["amount"] == "38.00", "freelancer: the annual return " + r.text[:200])
r = Fr.put(B + TF + "/vat", json={"year": 2026, "paid": "5"})
check(r.ok and line(r.json(), 186)["amount"] == "5.00", "freelancer: VAT paid " + r.text[:200])
check(Fr.get(B + TF + "/euer.csv?year=2026").ok and Fr.get(B + TF + "/ust.pdf?year=2026").ok, "freelancer: CSV and PDF")
check(line(A.get(B + TF + "/euer?year=2026").json(), 186)["amount"] == "0.00", "alice's office untouched by the freelancer")
check(line(Fr.get(B + TF + "/euer?year=2025").json(), 150) is None, "freelancer: none of alice's receipts")

# ---------------------------------------------------------------- small business
assert Fr.put(B + O + "/settings", json={"small_business": 1}).ok
d = Fr.get(B + TF + "/euer?year=2026").json()
check(line(d, 185) is None and line(d, 186) is None and line(d, 140) is None and line(d, 141) is None, "small business: no VAT lines")
check(line(d, 150)["amount"] == "238.00" and line(d, 199)["amount"] == "238.00", "small business: expenses gross")
d = Fr.get(B + TF + "/ust?year=2026").json()
check(d["small_business"] and d["known"] and d["rows"] == [] and "no annual VAT return" in d["notes"][0], "small business: the annual return falls away with a note")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
