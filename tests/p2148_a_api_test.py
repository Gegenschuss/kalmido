#!/usr/bin/env python3
"""2.148.0 API tests, part A (#2471, office: locking accounting periods (GoBD) + the export for the tax auditor), own
container (start.sh). Invented companies, people and figures only; all data in the finished month before the current one (M).
 - lock: the current month 400, a wrong confirmation 400, a member 403, ok -> locked [M] (from the earliest month with data),
   a second call locks nothing new; the office log has "period_lock"
 - after the lock every write with a date in M answers 409: a payment in M (new / delete), finalising a draft dated in M,
   moving a draft's date into M, a receipt's amount / date / category, a receipt into the trash, a cash entry in M (new /
   change), a trip in M (new / change / delete / new receipt), matching / unmatching a bank line of M
 - allowed stays: a payment dated today, a credit note dated today, changes in open months (receipt, cash entry, trip, bank)
 - the auditor's export: index.xml parses, every table URL is in the ZIP, every CSV line has the columns of index.xml,
   the invoice number in invoices.csv, decimal comma, dates DD.MM.YYYY; a member 403; another organisation sees nothing of
   Alpha's; a person without organisation (personal office, its own admin) locks and exports in its own office
usage: p2148_a_api_test.py <datadir>      (P2148A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)
freelancer-matrix: office  tenant-matrix: office"""
import csv
import io
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,time,docs,files,travel"
O = "/api/office"
D = O + "/docs"


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


def sql(q, args=()):
    c = dbxm.connect(DATA)
    try:
        return c.execute(q, args).fetchall()
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
    meta = {"date": day} if amount is None else {"amount": amount, "date": day}
    r = s.patch(B + f"/api/docs/{nid}", json=meta)
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": category, "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


def bank_tx(oid, day, amount, text):
    """A bank line straight in the database (the import is tested elsewhere)."""
    sql("INSERT INTO office_bank_tx(org_id, day, amount, currency, counterpart, purpose, hash, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (oid, day, amount, "EUR", text, text, "t-" + text, TODAY.isoformat() + "T08:00:00Z"))
    return sql("SELECT id FROM office_bank_tx WHERE org_id=? AND hash=?", (oid, "t-" + text))[0][0]


def unzip(r):
    return zipfile.ZipFile(io.BytesIO(r.content))


def tables(z):
    """index.xml -> {url: [column names]} (primary keys first, as written)."""
    root = ET.fromstring(z.read("index.xml"))
    out = {}
    for t in root.iter("Table"):
        cols = [c.findtext("Name") for c in t.find("VariableLength") if c.tag in ("VariablePrimaryKey", "VariableColumn")]
        out[t.findtext("URL")] = cols
    return out


def rows(z, url):
    return list(csv.reader(io.StringIO(z.read(url).decode("utf-8"), newline=""), delimiter=";", quotechar='"'))


if not (os.environ.get("P2148A_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
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
FID, Er = freelancer(B, A, "erin", features=FEAT)  # freelancer-matrix: office (the personal office, its own admin)

TODAY = testclock.today()
TD = TODAY.isoformat()
M0 = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)  # the 1st of the finished month before
M = M0.isoformat()[:7]
ML = f"{M[5:7]}/{M[:4]}"
CUR = TD[:7]


def day(n):
    return f"{M}-{n:02d}"


r = A.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel GmbH"}, "currency": "EUR",
                                     "company_fields": {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg",
                                                        "country": "DE", "tax_number": "12/345/67890", "vat_id": "DE999999999",
                                                        "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
assert r.ok, r.text

# ---------------------------------------------------------------- data of month M (and of today) before the lock
A.post(B + "/api/clients", json={"name": "=Formel Beispiel", "city": "Köln", "country": "DE"})
C1 = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]


def draft(title, rate=1000):
    r = A.post(B + D, json={"kind": "invoice", "client_id": C1, "service_from": day(1), "service_to": day(3),
                            "items": [{"title": title, "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


I1 = draft("Schnitt")
r = A.post(B + f"{D}/{I1}/finalize")
assert r.ok, r.text
N1 = r.json()["number"]
sql("UPDATE office_docs SET date=? WHERE id=?", (day(5), I1))
r = A.post(B + f"{D}/{I1}/payments", json={"date": day(10), "amount": "100.00", "method": "transfer"})
assert r.status_code == 201, r.text
P1 = [p["id"] for p in A.get(B + f"{D}/{I1}/payments").json()["payments"] if p.get("date") == day(10)][0]
D2 = draft("Ton")
r = A.patch(B + f"{D}/{D2}", json={"date": day(20)})
assert r.ok, r.text
D3 = draft("Farbe")
WSO = f"org:{ORG}"
R1 = receipt(A, WSO, "software.pdf", "119.00", day(8), "Software", "19")
R2 = receipt(A, WSO, "heute.pdf", "50.00", TD, "Software", "19")
TXM = bank_tx(ORG, day(12), "-40.00", "Papier Muster")
TXM2 = bank_tx(ORG, day(13), "-25.00", "Privat Muster")
TXO = bank_tx(ORG, TD, "-15.00", "Heute Muster")
r = A.post(B + f"{O}/bank/tx/{TXM2}/match", json={"kind": "private"})
assert r.ok, r.text
r = A.post(B + O + "/cashbooks", json={"name": "Hauptkasse", "opening": "500.00", "opening_day": day(1)})
assert r.status_code == 201, r.text
CB = r.json()["id"]
r = A.post(B + f"{O}/cashbooks/{CB}/entries", json={"day": day(15), "dir": "out", "amount": "20.00", "text": "Porto", "vat_pct": "0"})
assert r.status_code == 201, r.text
E1 = (r.json().get("entry") or r.json())["id"]
r = A.post(B + O + "/trips", json={"date_from": day(10), "date_to": day(11), "dest": "Drehort Beispiel", "overnight": 1, "country": "DE",
                                   "items": [{"date": day(10), "category": "train", "amount": 49.9}]})
assert r.status_code == 201, r.text
T1 = r.json()["id"]
T1I = r.json()["items"][0]["id"]

# ---------------------------------------------------------------- the lock
P = O + "/periods"
j = A.get(B + P).json()
check(j.get("through") is None and j.get("first") == M and j.get("current") == CUR, f"before: nothing locked, first month M {j}")
r = A.get(B + P + f"?check={M}")
check(r.ok and any(h["kind"] == "drafts" for h in r.json().get("hints", [])) and any(h["kind"] == "bank" for h in r.json()["hints"]),
      "check: hints on the draft dated in M and the unmatched bank line " + r.text[:300])
check(A.post(B + P + "/lock", json={"through": CUR, "confirm": f"{CUR[5:7]}/{CUR[:4]}"}).status_code == 400, "the current month cannot be locked (400)")
check(A.post(B + P + "/lock", json={"through": M, "confirm": M}).status_code == 400, "a wrong confirmation 400")
check(A.post(B + P + "/lock", json={"through": M}).status_code == 400, "no confirmation 400")
check(A.post(B + P + "/lock", json={"through": "2026-13", "confirm": "13/2026"}).status_code == 400, "an invalid month 400")
check(Bo.post(B + P + "/lock", json={"through": M, "confirm": ML}).status_code == 403, "a member cannot lock (403)")
check(Bo.get(B + P + f"?check={M}").status_code == 403, "a member gets no check (403)")
r = A.post(B + P + "/lock", json={"through": M, "confirm": ML})
check(r.ok and r.json().get("locked") == [M] and r.json().get("through") == M, "locked [M] " + r.text[:200])
r = A.post(B + P + "/lock", json={"through": M, "confirm": ML})
check(r.ok and r.json().get("locked") == [], "a second lock of the same month locks nothing new " + r.text[:200])
j = Bo.get(B + P).json()
check(j.get("through") == M and [x["period"] for x in j["months"]] == [M] and j["months"][0]["by"] == "Alice Admin",
      f"a member sees the locked month with who locked it {j}")
lg = A.get(B + O + "/log?limit=200").json()["log"]
pl = [x for x in lg if x.get("action") == "period_lock"]
check(len(pl) == 1 and pl[0]["detail"].get("from") == M and pl[0]["detail"].get("to") == M, f"office log (GoBD protocol): period_lock {pl}")
check(Ca.get(B + P).json().get("through") is None, "another organisation: nothing locked there")


def refused(r, what):
    check(r.status_code == 409 and ML in r.text, f"{what}: 409 ({r.status_code} {r.text[:160]})")


# ---------------------------------------------------------------- 409 in the locked month
refused(A.post(B + f"{D}/{I1}/payments", json={"date": day(15), "amount": "10.00", "method": "transfer"}), "a payment dated in M")
refused(A.delete(B + f"{D}/{I1}/payments/{P1}"), "deleting a payment of M")
refused(A.post(B + f"{D}/{D2}/finalize"), "finalising a draft dated in M")
check(sql("SELECT locked_at FROM office_docs WHERE id=?", (D2,))[0][0] is None, "the draft stays a draft")
refused(A.patch(B + f"{D}/{D3}", json={"date": day(21)}), "moving a draft's date into M")
refused(A.patch(B + f"/api/docs/{R1}", json={"amount": "120.00"}), "a receipt's amount in M")
refused(A.patch(B + f"/api/docs/{R1}", json={"date": TD}), "a receipt's date out of M")
refused(A.patch(B + f"/api/docs/{R2}", json={"date": day(9)}), "a receipt's date into M")
refused(A.put(B + f"/api/docs/{R1}/receipt", json={"category": "Fachliteratur", "keep": True}), "a receipt's category in M")
refused(A.delete(B + f"/api/files/nodes/{R1}"), "a receipt of M into the trash")
check(sql("SELECT deleted_at FROM fs_nodes WHERE id=?", (R1,))[0][0] is None, "the receipt is not in the trash")
refused(A.post(B + f"{O}/cashbooks/{CB}/entries", json={"day": day(16), "dir": "out", "amount": "5.00", "text": "Briefmarken", "vat_pct": "0"}),
        "a cash entry in M")
refused(A.patch(B + f"{O}/cash-entries/{E1}", json={"text": "Porto und Papier"}), "changing a cash entry of M")
refused(A.post(B + O + "/trips", json={"date_from": day(3), "date_to": day(3), "dest": "Kunde Beispiel", "country": "DE"}), "a new trip in M")
refused(A.patch(B + f"{O}/trips/{T1}", json={"dest": "Anderer Ort"}), "changing a trip of M")
refused(A.post(B + f"{O}/trips/{T1}/items", json={"date": day(11), "category": "taxi", "amount": 12}), "a new receipt on a trip of M")
refused(A.delete(B + f"{O}/trips/{T1}/items/{T1I}"), "deleting a trip receipt of M")
refused(A.delete(B + f"{O}/trips/{T1}"), "deleting a trip of M")
check(sql("SELECT COUNT(*) FROM office_trips WHERE id=?", (T1,))[0][0] == 1, "the trip is still there")
refused(A.post(B + f"{O}/bank/tx/{TXM}/match", json={"kind": "private"}), "matching a bank line of M")
refused(A.post(B + f"{O}/bank/tx/{TXM2}/unmatch"), "unmatching a bank line of M")

# ---------------------------------------------------------------- allowed: today and open months
r = A.post(B + f"{D}/{I1}/payments", json={"date": TD, "amount": "10.00", "method": "transfer"})
check(r.status_code == 201, "a payment dated today " + r.text[:160])
r = A.post(B + f"{D}/{I1}/credit")
check(r.status_code == 201, "a credit note draft " + r.text[:160])
CR = r.json().get("id")
r = A.post(B + f"{D}/{CR}/finalize")
check(r.ok and r.json().get("number"), "a credit note dated today is finalised " + r.text[:200])
check(A.patch(B + f"{D}/{D3}", json={"date": TD}).ok, "a draft dated today can change")
check(A.patch(B + f"/api/docs/{R2}", json={"amount": "55.00"}).ok, "a receipt of today: amount changes")
r = A.post(B + f"{O}/cashbooks/{CB}/entries", json={"day": TD, "dir": "out", "amount": "5.00", "text": "Briefmarken", "vat_pct": "0"})
check(r.status_code == 201, "a cash entry today " + r.text[:160])
r = A.post(B + O + "/trips", json={"date_from": TD, "date_to": TD, "dest": "Kunde Beispiel", "country": "DE"})
check(r.status_code == 201, "a trip today " + r.text[:160])
check(A.post(B + f"{O}/bank/tx/{TXO}/match", json={"kind": "private"}).ok, "matching a bank line of today")

# ---------------------------------------------------------------- the export for the tax auditor
X = O + "/gobd/export"
Q = f"?from={M}-01&to={TD}"
check(Bo.get(B + X + Q).status_code == 403, "a member: no export (403)")
r = A.get(B + X + Q + "&check=1")
check(r.ok and r.json().get("counts", {}).get("invoices.csv") == 2, "check: counts (invoice + credit note) " + r.text[:300])
check(A.get(B + X + f"?from={TD}&to={M}-01").status_code == 400, "the end before the start 400")
check(A.get(B + X + "?from=2000-01-01&to=2020-01-01").status_code == 400, "more than eleven years 400")
r = A.get(B + X + Q)
check(r.ok and r.headers.get("Content-Type", "").startswith("application/zip") and "GoBD_Export_" in r.headers.get("Content-Disposition", ""),
      "the ZIP " + str(r.status_code))
z = unzip(r)
tb = tables(z)
names = set(z.namelist())
check("index.xml" in names and len(tb) >= 8 and all(u in names for u in tb), f"index.xml parses, every table URL in the ZIP {sorted(tb)} {sorted(names)}")
bad = [(u, i, len(x), len(tb[u])) for u in tb for i, x in enumerate(rows(z, u)) if len(x) != len(tb[u])]
check(not bad, f"every CSV line has the columns of index.xml {bad[:5]}")
check(b"<DecimalSymbol>,</DecimalSymbol>" in z.read("index.xml") and b"DD.MM.YYYY" in z.read("index.xml"), "index.xml: decimal comma, date format")
inv = {x[tb["invoices.csv"].index("Nummer")]: dict(zip(tb["invoices.csv"], x)) for x in rows(z, "invoices.csv")}
i1 = inv.get(N1, {})
check(i1.get("Brutto") == "1190,00" and i1.get("Netto") == "1000,00" and i1.get("Datum") == f"05.{M[5:7]}.{M[:4]}",
      f"invoices.csv: the invoice with decimal comma and DD.MM.YYYY {i1}")
check(len(inv) == 2, f"invoices.csv: invoice + credit note, no drafts {sorted(inv)}")
pay = [dict(zip(tb["payments.csv"], x)) for x in rows(z, "payments.csv")]
check(any(p["Rechnungsnummer"] == N1 and p["Betrag"] == "100,00" and p["Datum"] == f"10.{M[5:7]}.{M[:4]}" for p in pay), f"payments.csv {pay}")
cb = [dict(zip(tb["cashbook.csv"], x)) for x in rows(z, "cashbook.csv")]
check(any(e["Datum"] == f"15.{M[5:7]}.{M[:4]}" and e["Richtung"] == "out" and e["Betrag"] == "20,00" and e["Text"] == "Porto" for e in cb),
      f"cashbook.csv: direction and amount in their columns {cb}")
rc = [dict(zip(tb["receipts.csv"], x)) for x in rows(z, "receipts.csv")]
check(any(x["Beleg_ID"] == str(R1) and x["Brutto"] == "119,00" and x["Belegdatum"] == f"08.{M[5:7]}.{M[:4]}" for x in rc), f"receipts.csv {rc}")
check(any(x[tb["clients.csv"].index("Name")] == "Beispielkunde AG" for x in rows(z, "clients.csv")), "clients.csv: the client")
fm = [x[tb["clients.csv"].index("Name")] for x in rows(z, "clients.csv") if "Formel Beispiel" in "".join(x)]
check(len(fm) == 1 and not fm[0].startswith(("=", "+", "-", "@")), f"clients.csv: a formula-like name is defused {fm}")
check(any(x[tb["log.csv"].index("Aktion")] == "period_lock" for x in rows(z, "log.csv")), "log.csv: the lock")
check(len(rows(z, "bookings.csv")) >= 2, "bookings.csv: the DATEV lines")
z2 = unzip(Ca.get(B + X + Q))
check(not any(N1 in "".join(x) for x in rows(z2, "invoices.csv")) and not any("Beispielkunde" in "".join(x) for x in rows(z2, "clients.csv"))
      and not rows(z2, "cashbook.csv") and not rows(z2, "receipts.csv"), "another organisation: nothing of Alpha's in its export")
lg = A.get(B + O + "/log?limit=200").json()["log"]
check(any(x.get("action") == "export" and x.get("target") == "gobd" for x in lg), "office log: the export")

# ---------------------------------------------------------------- a person without organisation (personal office)
r = Er.post(B + O + "/trips", json={"date_from": day(4), "date_to": day(4), "dest": "Kunde Beispiel", "country": "DE",
                                    "items": [{"date": day(4), "category": "taxi", "amount": 18}]})
check(r.status_code == 201, "freelancer: a trip in M " + r.text[:160])
ET1 = r.json()["id"]
check(Er.get(B + P).json().get("through") is None, "freelancer: nothing locked (Alpha's lock is not hers)")
r = Er.post(B + P + "/lock", json={"through": M, "confirm": ML})
check(r.ok and r.json().get("locked") == [M], "freelancer: locks M in the own office " + r.text[:200])
refused(Er.patch(B + f"{O}/trips/{ET1}", json={"dest": "Anderer Ort"}), "freelancer: changing a trip of M")
check(Er.post(B + O + "/trips", json={"date_from": TD, "date_to": TD, "dest": "Kunde Beispiel", "country": "DE"}).status_code == 201,
      "freelancer: a trip today")
check(Er.post(B + "/api/clients", json={"name": "Privatkunde Beispiel", "city": "Musterstadt", "country": "DE"}).status_code in (200, 201),
      "freelancer: a client of the own")
r = Er.get(B + X + Q)
check(r.ok, "freelancer: the export " + str(r.status_code))
if r.ok:
    ze = unzip(r)
    te = tables(ze)
    check(not any(N1 in "".join(x) for x in rows(ze, "invoices.csv")) and not rows(ze, "cashbook.csv")
          and not any("Beispielkunde" in "".join(x) for x in rows(ze, "clients.csv")), "freelancer: nothing of Alpha's in the own export")
    check(any(x[te["log.csv"].index("Aktion")] == "period_lock" for x in rows(ze, "log.csv")), "freelancer: the own lock in log.csv")
    check(any(x[te["clients.csv"].index("Name")] == "Privatkunde Beispiel" for x in rows(ze, "clients.csv")), "freelancer: the own client in clients.csv")
check(A.get(B + P).json().get("through") == M and len(A.get(B + P).json()["months"]) == 1, "Alpha's locks unchanged")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
