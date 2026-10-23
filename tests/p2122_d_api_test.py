#!/usr/bin/env python3
"""2.122.0 API tests, part D (#2315): VAT only once a year (annual return, no advance returns). Invented companies, people and figures only.
tenant-matrix: office  freelancer-matrix: office
 - tax dates: ustva "year" is stored and returned; one repeating task "Submit the annual VAT return" due at the next 31 July minus
   the lead (FREQ=YEARLY), with the hint to agree the deadline with the tax adviser; the permanent extension does not apply (no new task);
   switching quarter -> year -> none ends the old task each time (done, never deleted); unknown modes 400; a member 403
 - bookkeeping: GET /api/office/books/ustva?period=y = the whole year (1 Jan - 31 Dec), its figures = the sum of the four quarters
   (accrual basis, whole-euro bases), bad periods 400, a member 403
 - a person without organisation (personal office) does both
usage: p2122_d_api_test.py <datadir>      (P2122D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
D = O + "/docs"
BK = O + "/books"
URL = B + O + "/tax-dates"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def task(tid):
    r = dbx("SELECT title,content,due,repeat,status,deleted_at,created_by,assignee_id,list_id FROM tasks WHERE id=?", (tid,))
    return r[0] if r else None


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


def receipt(s, ws, name, amount, day, vat):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    assert s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day}).ok
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Software", "vat_pct": vat, "keep": True})
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


def next_july(lead, today):
    """Independent calculation: the first 31 July whose due day (minus the lead) is today or later."""
    y = today.year
    while date.fromordinal(date(y, 7, 31).toordinal() - lead) < today:
        y += 1
    d = date(y, 7, 31)
    return d, date.fromordinal(d.toordinal() - lead)


if os.environ.get("P2122D_NOSTART") != "1":
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
TODAY = testclock.today()
DL, DUE = next_july(3, TODAY)

# ---------------------------------------------------------------- tax dates: the yearly mode
check(A.get(URL).json()["ustva"] == "none", "default: no VAT return")
check(A.put(URL, json={"ustva": "yearly"}).status_code == 400 and A.put(URL, json={"ustva": "y"}).status_code == 400, "unknown VAT modes: 400")
check(Bo.put(URL, json={"ustva": "year"}).status_code == 403 and A.get(URL).json()["ustva"] == "none", "a member cannot switch (403)")
j = A.put(URL, json={"ustva": "quarter"}).json()
TQ = j["tasks"]["ustva"]
check(TQ and task(TQ)[4] == 0 and "FREQ=MONTHLY;INTERVAL=3" in task(TQ)[3], "quarterly: the quarterly task " + str(task(TQ)))
j = A.put(URL, json={"ustva": "year"}).json()
TY = j["tasks"]["ustva"]
t = task(TY)
check(j["ustva"] == "year" and A.get(URL).json()["ustva"] == "year", "year: stored and returned")
check(t and "annual VAT return" in t[0] and t[3] == "FREQ=YEARLY" and t[2][:10] == DUE.isoformat(), f"year: the yearly task, due {DUE} " + str(t))
check(t and "tax adviser" in t[1] and t[6] == ALICE and t[7] == ALICE, "year: the hint to agree the deadline, alice's task")
check(any(n["kind"] == "ustva" and n["date"] == DL.isoformat() and n["due"] == DUE.isoformat() for n in j["next"]), f"year: the preview names 31 July {j['next']}")
tq = task(TQ)
check(tq[4] == 2 and tq[3] == "" and tq[5] is None, "quarter -> year: the quarterly task is ended (done, not deleted) " + str(tq))
j = A.put(URL, json={"ustva_ext": 1}).json()
check(j["tasks"]["ustva"] == TY and task(TY)[4] == 0 and all(n["date"][5:] == "07-31" for n in j["next"] if n["kind"] == "ustva"),
      "year: the extension changes nothing (same task, still 31 July)")
j = A.put(URL, json={"lead_days": 10}).json()
TY2 = j["tasks"]["ustva"]
check(TY2 != TY and task(TY)[4] == 2 and task(TY2)[2][:10] == next_july(10, TODAY)[1].isoformat(), "year: another lead = a new task, the old one ended")
j = A.put(URL, json={"ustva": "none"}).json()
check(j["tasks"]["ustva"] is None and task(TY2)[4] == 2 and task(TY2)[5] is None, "year -> none: the task ended, not deleted")
check(not any(n["kind"] == "ustva" for n in j["next"]), "none: no VAT date in the preview")
A.put(URL, json={"ustva_ext": 0, "lead_days": 3})

# ---------------------------------------------------------------- bookkeeping: the whole year
A.put(B + O + "/settings", json={"small_business": 0, "vat_basis": "soll", "currency": "EUR",
                                 "company_fields": {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg", "country": "DE",
                                                    "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
C1 = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]
invoice(A, C1, [{"title": "Schnitt", "qty": 2, "rate": 500}], "2025-02-10")
invoice(A, C1, [{"title": "Grafik", "qty": 1, "rate": 500}, {"title": "Fachbuch", "qty": 1, "rate": 200, "tax": "reduced"}], "2025-08-12")
WSO = f"org:{ORG}"
receipt(A, WSO, "lizenz.pdf", "119.00", "2025-05-05", "19")
receipt(A, WSO, "buch.pdf", "107.00", "2025-11-20", "7")
receipt(A, WSO, "naechstes.pdf", "238.00", "2026-01-05", "19")  # another year: never counted
for bad in ("y1", "Y", "year", "q0"):
    check(A.get(B + BK + f"/ustva?year=2025&period={bad}").status_code == 400, f"bad period {bad}: 400")
check(Bo.get(B + BK + "/ustva?year=2025&period=y").status_code == 403, "a member: 403 for the year")
y = A.get(B + BK + "/ustva?year=2025&period=y").json()
check(y.get("period") == "y" and y.get("from") == "2025-01-01" and y.get("to") == "2025-12-31", f"period y: 1 Jan - 31 Dec {y.get('from')} {y.get('to')}")
qs = [A.get(B + BK + f"/ustva?year=2025&period=q{i}").json()["kz"] for i in range(1, 5)]
kz = y.get("kz", {})
check(kz.get("81") == "1500" and kz.get("86") == "200" and kz.get("66") == "26.00", f"year: bases and input tax {kz}")
for f in ("81", "86", "35", "21", "45", "66", "83"):
    check(Decimal(kz.get(f) or "0") == sum(Decimal(q[f]) for q in qs), f"year field {f} = sum of the quarters {kz.get(f)} {[q[f] for q in qs]}")
check(len([i for i in y["items"] if i["kind"] == "receipt"]) == 2, "year: the entries of that year only")
check(A.get(B + BK + "/ustva?year=2025&period=q1").json()["kz"]["81"] == "1000", "quarters unchanged")

# ---------------------------------------------------------------- a person without organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
r = Fr.put(URL, json={"ustva": "year"})
check(r.ok and r.json()["ustva"] == "year", "freelancer: the yearly mode " + r.text[:160])
tf = task(r.json()["tasks"]["ustva"]) if r.ok else None
inbox = dbx("SELECT id FROM lists WHERE is_inbox=1 AND owner_id=?", (FID,))
check(tf and tf[6] == FID and tf[7] == FID and inbox and tf[8] == inbox[0][0] and tf[3] == "FREQ=YEARLY", "freelancer: the yearly task in the own Basket " + str(tf))
r = Fr.get(B + BK + "/ustva?year=2025&period=y")
check(r.ok and r.json()["period"] == "y" and r.json()["to"] == "2025-12-31", "freelancer: the VAT figures of the whole year " + r.text[:160])
r = Fr.put(URL, json={"ustva": "none"})
check(r.ok and r.json()["tasks"]["ustva"] is None and dbx("SELECT status FROM tasks WHERE created_by=? AND title LIKE ?", (FID, "%annual VAT%")) == [(2,)],
      "freelancer: none again ends the yearly task")
check(A.get(URL).json()["ustva"] == "none", "alice's office untouched by the freelancer")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
