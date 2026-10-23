#!/usr/bin/env python3
"""2.90.0 API tests, part A (#1921): bookkeeping light in the office. Invented companies, people and figures only.
tenant-matrix: office
 - receipts: the VAT rate of a receipt (PUT /api/docs/<id>/receipt vat_pct "19" | "7" | "0" | null; other values 400; GET
   returns it; agents 403); the assignment row stays while only a VAT rate is set
 - income/expense statement (EUeR) of a year: income = payments (cash principle) split by the tax lines (19 / 7 / tax-free
   incl. reverse charge), expenses = receipts by category (without one: Other) + travel receipts; the profit, receipts
   without VAT rate, the tax reserve of the year; paid_at moves a receipt into its payment year
 - VAT return figures (UStVA) of a month / quarter: fields 81, 86, 21, 45, 66, 83 on cash basis ("ist") and accrual basis
   ("soll": finalised documents by date, the credit note negative); a refund (83 negative); small business -> no return
 - CSV (semicolon, decimal comma, formula injection made harmless) and PDF (content type) of the EUeR, one log entry each
 - the tax reserve in the cash flow (reserve + freely available per month; no rows at 0 %)
 - rights: an organisation member 403, an agent 403, another organisation / another person sees nothing and reaches no
   receipt of it (404); a person without organisation (personal office) uses it fully
usage: p290_a_api_test.py <datadir>      (P290A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import csv
import io
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
D = O + "/docs"
BK = O + "/books"


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


def receipt(s, ws, name, amount, day, category="", vat=None):
    """A receipt: a document (upload) with amount + date and its assignment (category, VAT rate)."""
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day})
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": category, "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def F(v):
    return float(v)


if os.environ.get("P290A_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other"), ("dora", "Dora Frei"), ("erik", "Erik Frei")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Do, Er = sess("bob"), sess("carol"), sess("dora"), sess("erik")
for s in (A, Bo, Ca, Do, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
A.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel GmbH"}, "currency": "EUR",
                                 "company_fields": {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg", "country": "DE",
                                                    "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
                                                    "bank_name": "Beispielbank"}})

# ---------------------------------------------------------------- rights first (empty office)
for path in (BK, BK + "/euer?year=2026", BK + "/ustva?year=2026&period=q1", BK + "/euer.csv?year=2026", BK + "/euer.pdf?year=2026"):
    check(Bo.get(B + path).status_code == 403, f"member: 403 on {path}")
    check(requests.get(B + path, headers=AGH).status_code == 403, f"agent: 403 on {path}")
check(A.get(B + BK + "/euer?year=19x").status_code == 400 and A.get(B + BK + "/ustva?year=2026&period=q5").status_code == 400
      and A.get(B + BK + "/ustva?year=2026&period=m13").status_code == 400, "bad year / period: 400")
for bad in ({"tax_reserve_pct": 61}, {"tax_reserve_pct": -1}, {"tax_reserve_pct": "x"}, {"vat_basis": "both"}):
    check(A.put(B + O + "/settings", json=bad).status_code == 400, f"settings validated: {bad}")
check(Bo.put(B + O + "/settings", json={"tax_reserve_pct": 10}).status_code == 403, "member cannot set the tax reserve (403)")
st = A.get(B + O + "/settings").json()["settings"]
check(st.get("tax_reserve_pct") == 0 and st.get("vat_basis") == "ist", f"defaults: no reserve, cash basis {st.get('tax_reserve_pct')} {st.get('vat_basis')}")

# ---------------------------------------------------------------- documents of Alpha (dates fixed in the database after finalising)
C1 = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]
C3 = A.post(B + "/api/clients", json={"name": "Example Ltd", "street": "1 High Street", "zip": "1000", "city": "Wien", "country": "AT", "vat_id": "ATU99999999"}).json()["id"]


def make(kind, client, items, date, extra=None, src=None):
    if src:
        r = A.post(B + f"{D}/{src}/credit")
        assert r.status_code == 201, r.text
        did = r.json()["id"]
    else:
        r = A.post(B + D, json=dict({"kind": kind, "client_id": client, "service_from": "2026-03-01", "service_to": "2026-03-15", "items": items}, **(extra or {})))
        assert r.status_code == 201, r.text
        did = r.json()["id"]
    r = A.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    dbx("UPDATE office_docs SET date=? WHERE id=?", (date, did), write=True)
    return did


def pay(did, day, amount):
    r = A.post(B + f"{D}/{did}/payments", json={"date": day, "amount": amount, "method": "transfer"})
    check(r.status_code == 201, f"payment {did} {day} {amount} " + r.text[:160])


I1 = make("invoice", C1, [{"title": "Schnitt", "qty": 2, "rate": 500}, {"title": "Fachbuch", "qty": 1, "rate": 100, "tax": "reduced"}], "2026-03-05")
I2 = make("invoice", C1, [{"title": "Beratung", "qty": 1, "rate": 1000}], "2026-03-10")
I3 = make("invoice", C3, [{"title": "Animation", "qty": 1, "rate": 2000}], "2026-03-12", {"vat_mode": "novat", "vat_note": "reverse"})
I4 = make("invoice", C3, [{"title": "Grafik", "qty": 1, "rate": 500}], "2026-03-13", {"vat_mode": "novat", "vat_note": "abroad"})
CR = make("credit", None, None, "2026-03-25", src=I2)
I5 = make("invoice", C1, [{"title": "Nachtrag", "qty": 1, "rate": 50}], "2026-03-28")
pay(I1, "2026-03-15", "1000.00")
pay(I1, "2026-03-16", "297.00")
pay(I3, "2026-03-20", "2000.00")
pay(I4, "2026-03-21", "500.00")
pay(I5, "2026-04-03", "59.50")
r = A.post(B + "/api/office/trips", json={"date_from": "2026-03-05", "dest": "Kundentermin", "items": [{"date": "2026-03-05", "category": "taxi", "amount": 30}]})
check(r.status_code == 201, "a travel receipt " + r.text[:120])

# receipts of Alpha's documents space
WSO = f"org:{ORG}"
R1 = receipt(A, WSO, "software.pdf", "119.00", "2026-02-10", "Software", "19")
R2 = receipt(A, WSO, "buch.pdf", "107.00", "2026-03-02", "Books", 7)
R3 = receipt(A, WSO, "kasse.pdf", "50.00", "2026-03-03", "", None)
j = A.get(B + f"/api/docs/{R2}/receipt").json()
check(j["receipt"]["vat_pct"] == "7" and j["receipt"]["category"] == "Books" and j["receipt"]["paid_at"] is None, f"receipt: GET returns the VAT rate {j['receipt']}")
check(A.put(B + f"/api/docs/{R2}/receipt", json={"category": "Books", "vat_pct": "16"}).status_code == 400
      and A.put(B + f"/api/docs/{R2}/receipt", json={"category": "Books", "vat_pct": True}).status_code == 400, "receipt: other VAT rates 400")
r = A.put(B + f"/api/docs/{R2}/receipt", json={"category": "Books"})
check(r.ok and r.json()["receipt"]["vat_pct"] == "7", "receipt: a body without vat_pct keeps the rate")
R4 = receipt(A, WSO, "nur-satz.pdf", "10.00", "2025-05-01", "", "0")
r = A.put(B + f"/api/docs/{R4}/receipt", json={"category": ""})
check(r.ok and r.json()["receipt"]["is_receipt"] and dbx("SELECT vat_pct FROM rc_receipts WHERE node_id=?", (R4,)) == [("0",)], "receipt: the row stays with only a VAT rate")
r = A.put(B + f"/api/docs/{R3}/receipt", json={"category": ""})
check(r.ok and not r.json()["receipt"]["is_receipt"], "receipt: all empty without keep = no receipt any more")
A.put(B + f"/api/docs/{R3}/receipt", json={"category": "", "keep": True})
check(A.get(B + f"/api/docs/{R3}/receipt").json()["receipt"]["is_receipt"], "receipt: keep = a receipt without category and rate")
check(requests.put(B + f"/api/docs/{R2}/receipt", headers=AGH, json={"vat_pct": "19"}).status_code in (401, 403, 404), "agent: cannot set the VAT rate")
check(Ca.put(B + f"/api/docs/{R2}/receipt", json={"vat_pct": "19"}).status_code == 404 and Ca.get(B + f"/api/docs/{R2}/receipt").status_code == 404,
      "another organisation reaches no receipt of Alpha (404)")
R5 = receipt(A, WSO, "injektion.pdf", "10.00", "2025-05-02", "=cmd|calc", "19")

# ---------------------------------------------------------------- the EUeR
e = A.get(B + BK + "/euer?year=2026").json()
inc = {x["key"]: x for x in e["income"]}
check(set(inc) == {"vat19", "vat7", "exempt"}, f"EUeR: income groups 19 / 7 / tax-free {list(inc)}")
check(F(inc["vat19"]["net"]) == 1050 and F(inc["vat19"]["vat"]) == 199.5 and F(inc["vat19"]["gross"]) == 1249.5, f"EUeR: 19 % = I1 part + I5 {inc['vat19']}")
check(F(inc["vat7"]["net"]) == 100 and F(inc["vat7"]["vat"]) == 7, f"EUeR: 7 % {inc['vat7']}")
check(F(inc["exempt"]["net"]) == 2500 and F(inc["exempt"]["vat"]) == 0, f"EUeR: reverse charge + abroad tax-free {inc['exempt']}")
check(F(e["income_total"]["net"]) == 3650 and F(e["income_total"]["gross"]) == 3856.5, f"EUeR: income total {e['income_total']}")
exp = {x["label"]: x for x in e["expenses"]}
check(F(exp["Software"]["net"]) == 100 and F(exp["Software"]["vat"]) == 19 and exp["Software"]["count"] == 1, f"EUeR: receipt 19 % {exp.get('Software')}")
check(F(exp["Books"]["net"]) == 100 and F(exp["Books"]["vat"]) == 7, f"EUeR: receipt 7 % {exp.get('Books')}")
check(F(exp["Other"]["net"]) == 50 and F(exp["Other"]["vat"]) == 0, f"EUeR: a receipt without category and rate: Other, no input tax {exp.get('Other')}")
tr_ = [x for x in e["expenses"] if x["key"].startswith("t:")]
check(len(tr_) == 1 and F(tr_[0]["gross"]) == 30 and F(tr_[0]["vat"]) == 0, f"EUeR: the travel receipt {tr_}")
check(F(e["expense_total"]["net"]) == 280 and F(e["expense_total"]["vat"]) == 26, f"EUeR: expense total {e['expense_total']}")
check(F(e["profit"]) == 3370 and e["missing_vat"] == 1 and e["currency"] == "EUR", f"EUeR: profit and one receipt without VAT rate {e['profit']} {e['missing_vat']}")
check(e["tax_reserve_pct"] == 0 and F(e["tax_reserve"]) == 0 and "No tax advice" in e["notes"][0], "EUeR: no reserve, the note")
e25 = A.get(B + BK + "/euer?year=2025").json()
check(e25["income"] == [] and len(e25["expenses"]) == 2, f"EUeR 2025: only the two receipts of that year {e25['expenses']}")
info = A.get(B + BK + "?year=2026&month=2026-03").json()
check(info["upload_ws"] == WSO and {x["node_id"] for x in info["receipts"]} == {R2, R3} and [x["node_id"] for x in info["missing"]] == [R3]
      and "Software" in info["categories"], f"info: upload space, receipts of the month, without rate {info}")

# ---------------------------------------------------------------- VAT return figures
u = A.get(B + BK + "/ustva?year=2026&period=q1").json()
k = u.get("kz", {})
check(u["basis"] == "ist" and k.get("81") == "1000" and k.get("86") == "100" and k.get("21") == "2000" and k.get("45") == "500", f"UStVA ist Q1: bases {k}")
check(u["tax"] == {"19": "190.00", "7": "7.00"} and k.get("66") == "26.00" and k.get("83") == "171.00", f"UStVA ist Q1: taxes, input tax, advance payment {u['tax']} {k}")
check(u["missing_vat"] == 1 and any(i["kind"] == "receipt" and i["node_id"] == R1 for i in u["items"]) and any(i.get("doc_id") == I1 for i in u["items"]),
      "UStVA: the entries behind it (receipts + invoices)")
m2 = A.get(B + BK + "/ustva?year=2026&period=m02").json()["kz"]
check(m2["81"] == "0" and m2["66"] == "19.00" and m2["83"] == "-19.00", f"UStVA February: only input tax = a refund {m2}")
m4 = A.get(B + BK + "/ustva?year=2026&period=m04").json()["kz"]
check(m4["81"] == "50" and m4["83"] == "9.50", f"UStVA ist April: the late payment of I5 {m4}")
r = A.put(B + O + "/settings", json={"vat_basis": "soll"})
check(r.ok and r.json()["settings"]["vat_basis"] == "soll", "accrual basis set")
k = A.get(B + BK + "/ustva?year=2026&period=q1").json()["kz"]
check(k["81"] == "1050" and k["86"] == "100" and k["21"] == "2000" and k["45"] == "500" and k["83"] == "180.50",
      f"UStVA soll Q1: invoices by date, the credit note cancels I2, I5 counts in March {k}")
check(A.get(B + BK + "/ustva?year=2026&period=m04").json()["kz"]["81"] == "0", "UStVA soll April: nothing (paid there, invoiced in March)")
A.put(B + O + "/settings", json={"vat_basis": "ist"})

# ---------------------------------------------------------------- paid_at (set by the bank reconciliation) moves a receipt in the EUeR
dbx("UPDATE rc_receipts SET paid_at='2025-12-30' WHERE node_id=?", (R1,), write=True)
e = A.get(B + BK + "/euer?year=2026").json()
check(not any(x["label"] == "Software" for x in e["expenses"]), "paid_at: the receipt paid in 2025 leaves the EUeR 2026")
check(any(x["label"] == "Software" for x in A.get(B + BK + "/euer?year=2025").json()["expenses"]), "paid_at: and lands in 2025")
check(A.get(B + BK + "/ustva?year=2026&period=q1").json()["kz"]["66"] == "26.00", "paid_at: the input tax stays by the document date")
dbx("UPDATE rc_receipts SET paid_at=NULL WHERE node_id=?", (R1,), write=True)
e = A.get(B + BK + "/euer?year=2026").json()
check(any(x["label"] == "Software" for x in e["expenses"]), f"paid_at removed: back in 2026 {dbx('SELECT paid_at FROM rc_receipts WHERE node_id=?', (R1,))} {e['expenses']}")

# ---------------------------------------------------------------- CSV + PDF
log0 = dbx("SELECT COUNT(*) FROM office_doc_log WHERE org_id=? AND action='export' AND target='books'", (ORG,))[0][0]
r = A.get(B + BK + "/euer.csv?year=2025")
check(r.ok and r.headers.get("Content-Type", "").startswith("text/csv") and "euer-2025.csv" in r.headers.get("Content-Disposition", ""), "CSV: download " + r.headers.get("Content-Type", ""))
rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
check(rows[0] == ["Group", "Net", "VAT", "Gross"], f"CSV: header {rows[0]}")
check(any(x[0] == "'=cmd|calc" for x in rows) and not any(x[0].startswith("=") for x in rows), f"CSV: formula injection made harmless {rows}")
check(any(x[0] == "Profit" for x in rows) and any("," in c for x in rows for c in x[1:]), "CSV: profit row, decimal comma")
r = A.get(B + BK + "/euer.pdf?year=2026")
check(r.ok and r.headers.get("Content-Type") == "application/pdf" and r.content[:5] == b"%PDF-", "PDF: content type + PDF bytes " + r.headers.get("Content-Type", ""))
log1 = dbx("SELECT COUNT(*) FROM office_doc_log WHERE org_id=? AND action='export' AND target='books'", (ORG,))[0][0]
check(log1 == log0 + 2, f"one log entry per export {log0} -> {log1}")

# ---------------------------------------------------------------- tax reserve: EUeR + cash flow
cf0 = A.get(B + O + "/cashflow?from=2026-03&months=2").json()
check(all("reserve" not in x and "free" not in x for x in cf0["rows"]), "cash flow at 0 %: no reserve rows")
r = A.put(B + O + "/settings", json={"tax_reserve_pct": "30"})
check(r.ok and r.json()["settings"]["tax_reserve_pct"] == 30, "tax reserve 30 % " + r.text[:160])
e = A.get(B + BK + "/euer?year=2026").json()
check(F(e["tax_reserve"]) == 1011 and e["tax_reserve_pct"] == 30, f"EUeR: reserve of the year = 30 % of the profit {e['tax_reserve']} {e['profit']} {e['income_total']} {e['expenses']}")
cf = A.get(B + O + "/cashflow?from=2026-03&months=2").json()["rows"]
check(F(cf[0]["reserve"]) == 1080 and F(cf[0]["free"]) == F(cf[0]["balance"]) - 1080, f"cash flow March: 30 % of 3600 net received; free = balance - reserve {cf[0]}")
check(F(cf[1]["reserve"]) == 15 and abs(F(cf[1]["free"]) - (F(cf[0]["balance"]) + F(cf[1]["balance"]) - 1095)) < 0.005, f"cash flow April: cumulative {cf[1]}")
A.put(B + O + "/settings", json={"tax_reserve_pct": 0})

# ---------------------------------------------------------------- other people see nothing of it
ec = Ca.get(B + BK + "/euer?year=2026").json()
check(ec["income"] == [] and ec["expenses"] == [] and Ca.get(B + BK + "?year=2026&month=2026-03").json()["receipts"] == [], "another organisation: its own empty books")
ee = Er.get(B + BK + "/euer?year=2026").json()
check(ee["income"] == [] and ee["expenses"] == [], "another person (personal office): empty books")

# ---------------------------------------------------------------- a person without organisation: the personal office, small business
check(Do.get(B + O + "/settings").json().get("role") == "admin", "personal office: Dora is its admin")
Do.put(B + O + "/settings", json={"small_business": 1, "company_fields": {"name": "Dora Film", "street": "Musterweg 2", "zip": "12345", "city": "Musterstadt", "country": "DE",
                                                                          "tax_number": "12/345/67891", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
CP = Do.post(B + "/api/clients", json={"name": "Privatkunde Eins", "street": "Weg 1", "zip": "10000", "city": "Berlin", "country": "DE"}).json()["id"]
r = Do.post(B + D, json={"kind": "invoice", "client_id": CP, "service_from": "2026-03-01", "service_to": "2026-03-10", "items": [{"title": "Kamera", "qty": 1, "rate": 300}]})
assert r.status_code == 201, r.text
PI = r.json()["id"]
check(Do.post(B + f"{D}/{PI}/finalize").ok, "personal office: a small business invoice finalised")
check(Do.post(B + f"{D}/{PI}/payments", json={"date": "2026-03-12", "amount": 300}).status_code == 201, "personal office: paid")
PR = receipt(Do, "private", "objektiv.pdf", "119.00", "2026-03-04", "Equipment", "19")
info = Do.get(B + BK + "?year=2026&month=2026-03").json()
check(info["upload_ws"] == "private" and [x["node_id"] for x in info["receipts"]] == [PR] and info["small_business"], f"personal office: its receipts {info}")
e = Do.get(B + BK + "/euer?year=2026").json()
check([x["key"] for x in e["income"]] == ["small"] and F(e["profit"]) == 181 and e["missing_vat"] == 0,
      f"personal office, small business: profit = 300 - 119 gross (no input tax) {e['income']} {e['profit']}")
u = Do.get(B + BK + "/ustva?year=2026&period=q1").json()
check(u.get("small_business") is True and "kz" not in u, f"small business: no VAT return {u}")
check(Er.get(B + f"/api/docs/{PR}/receipt").status_code == 404 and A.get(B + f"/api/docs/{PR}/receipt").status_code == 404, "the personal receipt: others 404")
check(not any(x["node_id"] == PR for x in A.get(B + BK + "?year=2026&month=2026-03").json()["receipts"]), "the personal receipt never in an organisation's books")
r = Do.get(B + BK + "/euer.pdf?year=2026")
check(r.ok and r.content[:5] == b"%PDF-", "personal office: PDF")
check(requests.get(B + BK + "/euer?year=2026", headers=AGH).status_code == 403, "agent: 403 (also with data)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
