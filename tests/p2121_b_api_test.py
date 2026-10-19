#!/usr/bin/env python3
"""2.121.0 API tests, part B (#2095): the cash book in the office. Invented companies, people and figures only.
tenant-matrix: office
 - the default cash box (made on the first look), opening balance / day, more boxes, archive instead of delete (the
   default box never), an archived box takes no entries
 - entries: numbers per box without gaps, also for parallel bookings; validation (amount, kind, text, VAT rate, future
   day, before the opening day); the text encrypted at rest; the balance never below zero (400, no number used up)
 - change on an open day with the change log (values before); cancellation = a counter entry with a new number pointing at
   the original (both stay, never twice, a cancellation is not cancelled, cancelled entries do not change)
 - day closing: preview, final (409 for entries / changes / cancellations up to it, the opening balance fixed), closes the
   open days before it too, no future day
 - links: a receipt of the office's documents (the receipt shows "in the cash book no. X"), an issued invoice; those of
   another organisation / drafts 404
 - CSV (semicolon, decimal comma, formula injection made harmless, closings, change log) and PDF; the EUeR unchanged
 - rights: a member 403, an agent 403, another organisation 404; a person without organisation (personal office) uses all
   of it, another person and the organisation do not reach it
usage: p2121_b_api_test.py <datadir>      (P2121B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import csv
import io
import os
import subprocess
import sys
import threading

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
CBS, CE = O + "/cashbooks", O + "/cash-entries"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def enc(v):
    return str(v or "").startswith("kenc1:")


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


def receipt(s, ws, name, amount, day, category="Material"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    assert s.put(B + f"/api/docs/{nid}/receipt", json={"category": category, "vat_pct": "19", "keep": True}).ok
    return nid


def invoice(s, client, draft=False):
    r = s.post(B + O + "/docs", json={"kind": "invoice", "client_id": client, "service_from": "2026-03-01", "service_to": "2026-03-02",
                                      "items": [{"title": "Barverkauf", "qty": 1, "rate": 20}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if not draft:
        r = s.post(B + O + f"/docs/{did}/finalize")
        assert r.ok, r.text
    return did


if os.environ.get("P2121B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
A.put(B + O + "/settings", json={"company_fields": {"name": "Muster GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg", "country": "DE"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH"}).json()["id"]
CL2 = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG"}).json()["id"]
Ca.put(B + O + "/settings", json={"company_fields": {"name": "Beispiel AG", "street": "Weg 2", "zip": "10000", "city": "Berlin", "country": "DE"}})
EUER0 = A.get(B + O + "/books/euer?year=2026").json()

# ---------------------------------------------------------------- rights first
for path in (CBS, O + "/cashbook.csv", O + "/cashbook.pdf", CBS + "/links"):
    check(Bo.get(B + path).status_code == 403, f"member: 403 on {path}")
    check(requests.get(B + path, headers=AGH).status_code == 403, f"agent: 403 on {path}")
check(Bo.post(B + CBS, json={"name": "x"}).status_code == 403 and requests.post(B + CBS, headers=AGH, json={"name": "x"}).status_code == 403, "member / agent: no new cash box")

# ---------------------------------------------------------------- the default cash box
j = A.get(B + CBS).json()
check(len(j["books"]) == 1 and j["books"][0]["is_default"] and j["books"][0]["opening"] == "0.00" and j["books"][0]["balance"] == "0.00"
      and j["currency"] == "EUR" and "income/expense" in j["note"], f"the default cash box {j}")
BK = j["books"][0]["id"]
check(len(A.get(B + CBS).json()["books"]) == 1, "the default box is made once")
r = A.patch(B + f"{CBS}/{BK}", json={"opening": "100", "opening_day": "2026-01-01"})
check(r.ok and r.json()["opening"] == "100.00" and r.json()["opening_day"] == "2026-01-01" and r.json()["balance"] == "100.00", "opening balance + day " + r.text[:200])
check(A.patch(B + f"{CBS}/{BK}", json={"opening": "-1"}).status_code == 400 and A.patch(B + f"{CBS}/{BK}", json={"opening_day": "2026-13-01"}).status_code == 400,
      "opening: negative / no date 400")
check(A.patch(B + f"{CBS}/{BK}", json={"archived": 1}).status_code == 400, "the default box cannot be archived")

# ---------------------------------------------------------------- entries
EN = f"{CBS}/{BK}/entries"


def post(s, body, bk=EN):
    return s.post(B + bk, json=body)


r = post(A, {"day": "2026-03-01", "dir": "in", "amount": "50", "text": "Verkauf Theke", "vat_pct": "19", "category": "Erlöse"})
check(r.status_code == 201 and r.json()["no"] == 1 and r.json()["amount"] == "50.00" and r.json()["balance"] == "150.00" and not r.json()["locked"], "entry 1 " + r.text[:200])
E1 = r.json()["id"]
r = post(A, {"day": "2026-03-01", "dir": "out", "amount": "30,50", "text": "Briefmarken", "vat_pct": "0"})
check(r.status_code == 201 and r.json()["no"] == 2 and r.json()["amount"] == "30.50" and r.json()["balance"] == "119.50", "entry 2 (decimal comma) " + r.text[:200])
E2 = r.json()["id"]
for body, what in (({"day": "2026-03-02", "dir": "in", "amount": "0", "text": "x"}, "amount 0"), ({"day": "2026-03-02", "dir": "in", "amount": "-5", "text": "x"}, "negative"),
                   ({"day": "2026-03-02", "dir": "in", "amount": "abc", "text": "x"}, "not a number"), ({"day": "2026-03-02", "dir": "sideways", "amount": "1", "text": "x"}, "kind"),
                   ({"day": "2026-03-02", "dir": "in", "amount": "1", "text": " "}, "no text"), ({"day": "2026-03-02", "dir": "in", "amount": "1", "text": "x", "vat_pct": "16"}, "VAT 16"),
                   ({"day": "2099-01-01", "dir": "in", "amount": "1", "text": "x"}, "future"), ({"day": "2025-12-31", "dir": "in", "amount": "1", "text": "x"}, "before the opening day"),
                   ({"day": "2026-03-02", "dir": "in", "amount": True, "text": "x"}, "amount true")):
    check(post(A, body).status_code == 400, f"entry: {what} 400")
r = post(A, {"day": "2026-03-02", "dir": "out", "amount": "500", "text": "zu viel"})
check(r.status_code == 400 and "below zero" in r.text, "the balance never below zero " + r.text[:200])
check(post(A, {"day": "2026-02-01", "dir": "out", "amount": "110", "text": "vorher"}).status_code == 400, "below zero also when booked before an income (running balance)")
check(enc(sql("SELECT text FROM office_cash_entries WHERE id=?", (E1,))[0][0]), "the text encrypted at rest")

# parallel bookings: numbers without gaps
sessions = [sess("alice") for _ in range(8)]
res = []


def go(s, i):
    res.append(s.post(B + EN, json={"day": "2026-03-05", "dir": "in", "amount": "1.00", "text": f"Parallel {i}"}).status_code)


ts = [threading.Thread(target=go, args=(s, i)) for i, s in enumerate(sessions)]
for t in ts:
    t.start()
for t in ts:
    t.join()
nos = sorted(x[0] for x in sql("SELECT no FROM office_cash_entries WHERE book_id=?", (BK,)))
check(res.count(201) == 8 and nos == list(range(1, 11)), f"parallel: 8 x 201 and numbers 1..10 without gaps {res} {nos}")

# change on an open day + the log
r = A.patch(B + f"{CE}/{E2}", json={"amount": "20", "text": "Porto"})
check(r.ok and r.json()["amount"] == "20.00" and r.json()["text"] == "Porto", "change on an open day " + r.text[:200])
lg = A.get(B + f"{CE}/{E2}/log").json()["log"]
check([x["action"] for x in lg] == ["create", "change"] and lg[1]["prev"] == {"amount": "30.50", "text": "Briefmarken"} and lg[0]["by"] == "Alice Admin",
      f"the log: create + change with the values before {lg}")
check(enc(sql("SELECT prev FROM office_cash_log WHERE entry_id=? ORDER BY id DESC", (E2,))[0][0]), "the log encrypted at rest")
check(A.patch(B + f"{CE}/{E2}", json={"amount": "900"}).status_code == 400, "change: below zero 400")

# cancellation
r = A.post(B + f"{CE}/{E1}/cancel", json={"day": "2026-03-05"})
check(r.status_code == 201 and r.json()["entry"]["no"] == 11 and r.json()["entry"]["dir"] == "out" and r.json()["entry"]["amount"] == "50.00"
      and r.json()["entry"]["storno_of"] == E1 and r.json()["entry"]["storno_of_no"] == 1 and r.json()["original"]["cancelled_by_no"] == 11,
      "cancel: a counter entry no. 11 pointing at no. 1 " + r.text[:300])
S1 = r.json()["entry"]["id"]
check(A.post(B + f"{CE}/{E1}/cancel", json={}).status_code == 409 and A.post(B + f"{CE}/{S1}/cancel", json={}).status_code == 409, "never cancelled twice, a cancellation is not cancelled")
check(A.patch(B + f"{CE}/{E1}", json={"text": "x"}).status_code == 409 and A.patch(B + f"{CE}/{S1}", json={"text": "x"}).status_code == 409, "cancelled / cancellation: no change")
check(sql("SELECT COUNT(*) FROM office_cash_entries WHERE book_id=?", (BK,))[0][0] == 11, "nothing deleted")
lst = A.get(B + EN + "?year=2026").json()
check(lst["balance"] == "88.00" and lst["entries"][0]["no"] == 11 and len(lst["entries"]) == 11, f"list: newest first, balance 100 + 50 - 20 + 8 - 50 = 88 {lst['balance']}")

# ---------------------------------------------------------------- day closing
p = A.get(B + f"{CBS}/{BK}/closing?day=2026-03-02").json()
check(p["from"] == "2026-03-01" and p["opening"] == "100.00" and p["sum_in"] == "50.00" and p["sum_out"] == "20.00" and p["closing"] == "130.00" and p["count"] == 2
      and [d["day"] for d in p["days"]] == ["2026-03-01", "2026-03-02"], f"closing preview {p}")
check(A.get(B + f"{CBS}/{BK}/closing?day=2099-01-01").status_code == 400 and Bo.post(B + f"{CBS}/{BK}/closing", json={"day": "2026-03-02"}).status_code == 403,
      "closing: no future day, a member 403")
r = A.post(B + f"{CBS}/{BK}/closing", json={"day": "2026-03-02"})
check(r.status_code == 201 and [x["day"] for x in r.json()["closings"]] == ["2026-03-01", "2026-03-02"] and r.json()["closings"][1]["closing"] == "130.00", "closed " + r.text[:300])
check(A.post(B + f"{CBS}/{BK}/closing", json={"day": "2026-03-02"}).status_code == 409 and A.post(B + f"{CBS}/{BK}/closing", json={"day": "2026-03-01"}).status_code == 409,
      "a closed day is not closed again")
check(post(A, {"day": "2026-03-01", "dir": "in", "amount": "1", "text": "nachträglich"}).status_code == 409, "no entry on a closed day")
check(post(A, {"day": "2026-02-15", "dir": "in", "amount": "1", "text": "davor"}).status_code == 409, "no entry before the last closing")
check(A.patch(B + f"{CE}/{E2}", json={"text": "geändert"}).status_code == 409 and A.patch(B + f"{CE}/{E2}", json={"day": "2026-03-06"}).status_code == 409, "a closed entry does not change")
check(A.patch(B + f"{CE}/{S1}", json={"day": "2026-03-01"}).status_code == 409, "an open entry is not moved onto a closed day")
check(A.patch(B + f"{CBS}/{BK}", json={"opening": "200"}).status_code == 409, "the opening balance is fixed after a closing")
r = A.post(B + f"{CE}/{E2}/cancel", json={"day": "2026-03-01"})
check(r.status_code == 409, "a cancellation is not booked on a closed day")
r = A.post(B + f"{CE}/{E2}/cancel", json={"day": "2026-03-06"})
check(r.status_code == 201 and r.json()["entry"]["no"] == 12 and r.json()["original"]["locked"] and r.json()["original"]["cancelled_by_no"] == 12,
      "a closed entry is corrected only by cancellation " + r.text[:200])
check(A.get(B + f"{CBS}/{BK}/log").json()["log"][-1]["action"] == "cancel" and any(x["action"] == "close" for x in A.get(B + f"{CBS}/{BK}/log").json()["log"]),
      "the box log has the closing and the cancellations")

# ---------------------------------------------------------------- links: receipt, invoice
WSO = f"org:{ORG}"
R1 = receipt(A, WSO, "material.pdf", "11.90", "2026-03-06")
RX = receipt(Ca, f"org:{ORG2}", "fremd.pdf", "5.00", "2026-03-06")
links = A.get(B + CBS + "/links").json()
check(any(x["node_id"] == R1 for x in links["receipts"]) and not any(x["node_id"] == RX for x in links["receipts"]), f"links: own receipts only {links['receipts']}")
r = post(A, {"day": "2026-03-06", "dir": "out", "amount": "11.90", "text": "Material bar", "vat_pct": "19", "node_id": R1})
check(r.status_code == 201 and r.json()["node"]["id"] == R1 and r.json()["node"]["name"] == "material.pdf", "an entry with its receipt " + r.text[:200])
ER = r.json()
h = A.get(B + f"/api/docs/{R1}/cashbook").json()
check(h["entries"] == [{"id": ER["id"], "no": ER["no"], "day": "2026-03-06", "book": "Cash box"}], f"the receipt shows its cash entry {h}")
check(Ca.get(B + f"/api/docs/{R1}/cashbook").status_code == 404, "another organisation: the receipt hint 404")
hb = Bo.get(B + f"/api/docs/{R1}/cashbook")
check(hb.status_code == 404 or hb.json()["entries"] == [], f"a member without the office admin role sees no cash entry {hb.status_code}")
check(requests.get(B + f"/api/docs/{R1}/cashbook", headers=AGH).status_code == 403, "agent: the receipt hint 403")
check(post(A, {"day": "2026-03-06", "dir": "out", "amount": "1", "text": "x", "node_id": RX}).status_code == 404, "a receipt of another organisation 404")
INV = invoice(A, CL)
DRAFT = invoice(A, CL, draft=True)
check(any(x["id"] == INV for x in A.get(B + CBS + "/links").json()["invoices"]) and not any(x["id"] == DRAFT for x in A.get(B + CBS + "/links").json()["invoices"]),
      "links: issued invoices, no drafts")
r = post(A, {"day": "2026-03-06", "dir": "in", "amount": "23.80", "text": "Rechnung bar bezahlt", "invoice_id": INV})
check(r.status_code == 201 and r.json()["invoice"]["id"] == INV, "an entry with its invoice " + r.text[:200])
check(post(A, {"day": "2026-03-06", "dir": "in", "amount": "1", "text": "x", "invoice_id": DRAFT}).status_code == 404, "a draft invoice 404")
CINV = invoice(Ca, CL2)
check(post(A, {"day": "2026-03-06", "dir": "in", "amount": "1", "text": "x", "invoice_id": CINV}).status_code == 404, "an invoice of another organisation 404")
check(post(A, {"day": "2026-03-06", "dir": "in", "amount": "1", "text": "=HYPERLINK(1)"}).status_code == 201, "a text like a formula")

# ---------------------------------------------------------------- more boxes
r = A.post(B + CBS, json={"name": "Kasse Laden", "opening": "10", "opening_day": "2026-03-01"})
check(r.status_code == 201 and not r.json()["is_default"] and r.json()["balance"] == "10.00", "a second box " + r.text[:200])
BK2 = r.json()["id"]
r = post(A, {"day": "2026-03-03", "dir": "in", "amount": "5", "text": "Laden"}, f"{CBS}/{BK2}/entries")
check(r.status_code == 201 and r.json()["no"] == 1, "the second box numbers from 1")
check(A.patch(B + f"{CBS}/{BK2}", json={"archived": 1}).ok and post(A, {"day": "2026-03-03", "dir": "in", "amount": "5", "text": "x"}, f"{CBS}/{BK2}/entries").status_code == 409,
      "an archived box takes no entries")
check(A.patch(B + f"{CBS}/{BK2}", json={"archived": 0}).ok, "restore the box")
check(A.post(B + CBS, json={"name": ""}).status_code == 400, "a box without name 400")

# ---------------------------------------------------------------- exports, EUeR
r = A.get(B + O + f"/cashbook.csv?book_id={BK}&year=2026")
check(r.ok and "text/csv" in r.headers.get("Content-Type", ""), "CSV")
rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
flat = [c for row in rows for c in row]
hdr = next((row for row in rows if row[:3] == ["No.", "Date", "Text"]), None)
check(hdr is not None and hdr[4:8] == ["Income", "Expense", "VAT", "Balance"], f"CSV header {hdr}")
e1 = next((row for row in rows if row[:1] == ["1"]), [])
check(e1[1:3] == ["2026-03-01", "Verkauf Theke"] and e1[4] == "50,00" and e1[6] == "19 %" and e1[7] == "150,00" and e1[8] == "Cancelled by no. 11", f"CSV row 1 {e1}")
check(any(row[:1] == ["11"] and row[8] == "Cancels no. 1" for row in rows), "CSV: the cancellation names its original")
check("'=HYPERLINK(1)" in flat and "=HYPERLINK(1)" not in flat, "CSV: formula injection made harmless")
check("Day closings" in flat and any(row[:1] == ["2026-03-02"] and row[4:5] == ["130,00"] for row in rows), "CSV: the day closings")
check("Change log" in flat and "Cancelled" in flat, "CSV: the change log")
r = A.get(B + O + f"/cashbook.pdf?book_id={BK}&year=2026")
check(r.ok and r.content[:5] == b"%PDF-" and len(r.content) > 1500, "PDF")
check(A.get(B + O + "/cashbook.csv?from=2026-03-01&to=2026-03-02").ok, "CSV of a period (default box)")
check(A.get(B + O + "/cashbook.csv?from=2026-03-05&to=2026-03-01").status_code == 400, "CSV: from after to 400")
EUER1 = A.get(B + O + "/books/euer?year=2026").json()
check(EUER1["income"] == EUER0["income"], f"the EUeR income does not count the cash book {EUER1['income']}")
check(abs(sum(float(x["gross"]) for x in EUER1["expenses"]) - 11.90) < 0.001, f"the EUeR expenses: only the receipt (11.90), not its cash entry {EUER1['expenses']}")

# ---------------------------------------------------------------- another organisation, agents
for m, pth in (("get", f"{CBS}/{BK}/entries"), ("patch", f"{CBS}/{BK}"), ("post", f"{CBS}/{BK}/entries"), ("patch", f"{CE}/{E2}"), ("post", f"{CE}/{ER['id']}/cancel"),
               ("get", f"{CE}/{E2}/log"), ("get", f"{CBS}/{BK}/closing"), ("post", f"{CBS}/{BK}/closing"), ("get", f"{CBS}/{BK}/log")):
    check(getattr(Ca, m)(B + pth, json={"day": "2026-03-07", "dir": "in", "amount": "1", "text": "x"} if m != "get" else None).status_code == 404, f"another organisation: {m} {pth} 404")
    check(getattr(requests, m)(B + pth, headers=AGH, json={} if m != "get" else None).status_code == 403, f"agent: {m} {pth} 403")
    check(getattr(Bo, m)(B + pth, json={} if m != "get" else None).status_code == 403, f"member: {m} {pth} 403")
cj = Ca.get(B + CBS).json()
check(len(cj["books"]) == 1 and cj["books"][0]["id"] not in (BK, BK2) and cj["books"][0]["balance"] == "0.00", "another organisation: its own default box")
check(sql("SELECT COUNT(*) FROM office_cash_entries WHERE book_id=?", (BK,))[0][0] == 15, "nothing written by the refused calls")

# ---------------------------------------------------------------- personal office (person without organisation)  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
_, Fr2 = freelancer(B, A, "fiona")
fj = Fr.get(B + CBS).json()
check(len(fj["books"]) == 1 and fj["books"][0]["is_default"], f"personal office: the default box {fj}")
PB = fj["books"][0]["id"]
today = fj["today"]
check(Fr.patch(B + f"{CBS}/{PB}", json={"opening": "20"}).ok, "personal office: the opening balance")
r = post(Fr, {"dir": "in", "amount": "15", "text": "Barverkauf Markt", "vat_pct": "7"}, f"{CBS}/{PB}/entries")
check(r.status_code == 201 and r.json()["no"] == 1 and r.json()["day"] == today and r.json()["balance"] == "35.00", "personal office: an entry today " + r.text[:200])
PE = r.json()["id"]
check(enc(sql("SELECT text FROM office_cash_entries WHERE id=?", (PE,))[0][0]), "personal office: encrypted at rest")
FR = receipt(Fr, "private", "quittung.pdf", "4.00", today)
r = post(Fr, {"dir": "out", "amount": "4", "text": "Kaffee Kunde", "node_id": FR}, f"{CBS}/{PB}/entries")
check(r.status_code == 201 and r.json()["node"]["id"] == FR and Fr.get(B + f"/api/docs/{FR}/cashbook").json()["entries"][0]["no"] == 2, "personal office: a receipt link + hint")
check(post(Fr, {"dir": "out", "amount": "1", "text": "x", "node_id": R1}, f"{CBS}/{PB}/entries").status_code == 404, "personal office: no receipt of the organisation")
r = Fr.post(B + f"{CE}/{PE}/cancel", json={})
check(r.status_code == 201 and r.json()["entry"]["no"] == 3, "personal office: cancel")
check(Fr.post(B + f"{CE}/{PE}/cancel", json={}).status_code == 409, "personal office: not twice")
check(Fr.get(B + f"{CBS}/{PB}/closing?day={today}").json()["closing"] == "16.00", "personal office: closing preview 20 + 15 - 4 - 15")
check(Fr.post(B + f"{CBS}/{PB}/closing", json={"day": today}).status_code == 201 and post(Fr, {"dir": "in", "amount": "1", "text": "x"}, f"{CBS}/{PB}/entries").status_code == 409,
      "personal office: day closing, then today is closed")
check(Fr.get(B + O + "/cashbook.csv").ok and Fr.get(B + O + "/cashbook.pdf").content[:5] == b"%PDF-" and Fr.get(B + CBS + "/links").ok, "personal office: CSV + PDF + links")
check(Fr.get(B + f"{CE}/{PE}/log").ok and Fr.get(B + f"{CBS}/{PB}/log").ok and Fr.get(B + f"{CBS}/{PB}/entries").json()["balance"] == "16.00", "personal office: logs + list")
r = Fr.post(B + CBS, json={"name": "Zweite Kasse"})
check(r.status_code == 201 and Fr.patch(B + f"{CBS}/{r.json()['id']}", json={"archived": 1}).ok, "personal office: a second box, archived")
for m, pth in (("get", f"{CBS}/{PB}/entries"), ("patch", f"{CE}/{PE}"), ("post", f"{CE}/{PE}/cancel"), ("get", f"{CE}/{PE}/log"), ("post", f"{CBS}/{PB}/closing")):
    check(getattr(Fr2, m)(B + pth, json={} if m != "get" else None).status_code == 404, f"another person: {m} {pth} 404")
    check(getattr(A, m)(B + pth, json={} if m != "get" else None).status_code == 404, f"the organisation: {m} {pth} 404")
check(Fr2.get(B + f"/api/docs/{FR}/cashbook").status_code == 404 and A.get(B + f"/api/docs/{FR}/cashbook").status_code == 404, "another person / the organisation: no receipt hint")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
