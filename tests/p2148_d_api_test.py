#!/usr/bin/env python3
"""2.148.0 API tests, part D (#2458, office: the DATEV import of master data and booking batches), own container (start.sh,
org encryption on). Invented companies, accounts and figures only (EXTF files written here). freelancer-matrix: office  tenant-matrix: office
 - master data (EXTF category 16, Windows-1252, columns read by name in another order): the check is a preview only
   (new / updated / skipped with reason, nothing written); the import makes clients of the debtors (customer number = the
   account, VAT id from EU-Land + EU-UStID), fills only EMPTY fields of an existing client (same customer number; the
   preview names what differs and it stays), makes suppliers of the creditors (name / address / IBAN encrypted at rest);
   a receipt whose sender matches a supplier (without legal form) is booked on its creditor in the DATEV batch, another
   one on the collective creditor; the run is undone by its own route and by the import page's undo (kind "datev")
 - booking batch (EXTF 21, UTF-8 with BOM): only the opening bookings (9000 / 9008 / 9009 or text "EB") become opening
   balances of their year, other bookings are counted with the hint; a second import replaces the same accounts of the year,
   its undo puts the earlier ones back; an opening booking in a locked month refuses the whole file (409)
 - wrong header / category / version 400, too large 413, too many rows 400; suppliers rename, delete, restore
 - a member without the admin role 403; another organisation sees nothing and gets 404; a person without organisation
   (personal office, its own admin) imports into its private clients and its own suppliers
usage: p2148_d_api_test.py <datadir>"""
import base64
import os
import re
import subprocess
import sys
import time
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
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs,files"
O = "/api/office"
I = O + "/datev/import"


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
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def enc(v):
    return str(v or "").startswith("kenc1:")


def head(cat, name, ver, fy, alen="4"):
    f = ['"EXTF"', "700", str(cat), f'"{name}"', str(ver), "20260101120000000", "", '"RE"', '""', '""', "1234567", "12345", fy, alen]
    return ";".join(f + [""] * (31 - len(f)))


def q(v):
    return '"' + str(v).replace('"', '""') + '"' if v != "" else ""


def extf16(rows, fy="20260101", alen="4", encoding="cp1252"):
    """A master data file: rows = dicts of DATEV column names (the order of COLS16, not DATEV's: read by name)."""
    lines = [head(16, "Debitoren/Kreditoren", 5, fy, alen), ";".join(q(c) for c in COLS16)]
    lines += [";".join(q(r.get(c, "")) for c in COLS16) for r in rows]
    return ("\r\n".join(lines) + "\r\n").encode(encoding)


COLS16 = ("Straße", "Konto", "Name (Adressatentyp Unternehmen)", "Name (Adressatentyp natürl. Person)", "Vorname (Adressatentyp natürl. Person)",
          "Adressatentyp", "Kurzbezeichnung", "EU-Land", "EU-UStID", "Postleitzahl", "Ort", "Land", "E-Mail", "IBAN-Nr. 1")
COLS21 = ("Umsatz (ohne Soll/Haben-Kz)", "Soll/Haben-Kennzeichen", "WKZ Umsatz", "Konto", "Gegenkonto (ohne BU-Schlüssel)", "BU-Schlüssel",
          "Belegdatum", "Belegfeld 1", "Buchungstext")


def extf21(rows, fy, bom=True):
    """A booking batch: rows = (amount, S/H, account, counter account, DDMM, text), UTF-8 with BOM."""
    lines = [head(21, "Buchungsstapel", 13, fy), ";".join(q(c) for c in COLS21)]
    for a, sh, k, g, d, t in rows:
        lines.append(";".join([a, q(sh), q("EUR"), k, g, "", d, q("EB"), q(t)]))
    raw = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    return (b"\xef\xbb\xbf" + raw) if bom else raw


def up(s, path, raw, name="extf.csv"):
    return s.post(B + path, files={"file": (name, raw, "text/csv")})


if not (os.environ.get("P2148D_NOSTART") or os.environ.get("KMT_NOSTART")):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
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
FID, Er = freelancer(B, A, "erin")  # freelancer-matrix: office (the personal office, its own admin)

TODAY = testclock.today()
P0 = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)  # the 1st of the month before
PREV = P0.isoformat()[:7]
LY = TODAY.year - 1  # the opening balances of last year (its January can be locked: a finished month)
r = A.put(B + O + "/settings", json={"datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}})
assert r.ok, r.text


def clients(s):
    """customer number (else name) -> the client with its billing fields flat."""
    out = {}
    for x in s.get(B + "/api/clients").json()["clients"]:
        x = {**x, **(x.get("billing") or {})}
        out[x.get("customer_no") or x["name"]] = x
    return out


# ---------------------------------------------------------------- master data: preview, import, fill only empty fields
OLD = A.post(B + "/api/clients", json={"name": "Altkunde AG", "city": "Bonn", "customer_no": "10003", "org_id": ORG})
check(OLD.ok, "an existing client with customer number 10003 " + OLD.text[:200])
OLD = OLD.json()["id"]
F16 = extf16([
    {"Konto": "10001", "Name (Adressatentyp Unternehmen)": "Beispiel Handel GmbH", "Straße": "Hauptstraße 1", "Postleitzahl": "50667", "Ort": "Köln",
     "Land": "DE", "EU-Land": "DE", "EU-UStID": "123456789", "E-Mail": "info@example.com"},
    {"Konto": "10002", "Name (Adressatentyp natürl. Person)": "Muster", "Vorname (Adressatentyp natürl. Person)": "Erika", "Ort": "Mainz",
     "E-Mail": "kein-mail"},
    {"Konto": "10003", "Name (Adressatentyp Unternehmen)": "Altkunde AG", "Straße": "Weg 2", "Ort": "Berlin"},
    {"Konto": "70001", "Name (Adressatentyp Unternehmen)": "Muster Bau GmbH", "Straße": "Baustraße 9", "Postleitzahl": "10115", "Ort": "Berlin",
     "IBAN-Nr. 1": "DE02 1203 0000 0000 2020 51"},
    {"Konto": "4400", "Name (Adressatentyp Unternehmen)": "Kein Personenkonto"},
    {"Konto": "10001", "Name (Adressatentyp Unternehmen)": "Doppelt GmbH"},
    {"Konto": "10004"},
])
before = sql("SELECT COUNT(*) FROM clients")[0][0]
r = up(A, I + "/check", F16)
check(r.ok, "check of a master data file " + r.text[:300])
j = r.json()
check(j["category"] == 16 and j["kind"] == "master" and j["counts"]["new"] == 3 and j["counts"]["updated"] == 1 and j["counts"]["skipped"] == 3,
      f"preview counts: 3 new, 1 updated, 3 skipped {j.get('counts')}")
rows = {x["row"]: x for x in j["rows"]}
check(rows[3]["action"] == "new" and rows[3]["kind"] == "debtor" and rows[3]["values"]["vat_id"] == "DE123456789", f"debtor 10001 new, VAT id with country {rows[3]}")
check(rows[4]["values"]["name"] == "Erika Muster" and rows[4]["values"]["email"] == "" and any("E-mail" in n for n in rows[4]["notes"]),
      f"a person: first + last name, an invalid e-mail left out with a note {rows[4]}")
check(rows[5]["action"] == "update" and rows[5]["fill"] == {"street": "Weg 2"} and rows[5]["differ"].get("city", {}).get("now") == "Bonn",
      f"existing client: street filled, the city differs and stays {rows[5]}")
check(rows[6]["kind"] == "creditor" and rows[6]["values"]["iban"] == "DE02120300000000202051", f"creditor 70001 with IBAN {rows[6]}")
check(rows[7]["action"] == "skip" and "neither" in rows[7]["reason"], f"4400 is no personal account {rows[7]}")
check(rows[8]["action"] == "skip" and "twice" in rows[8]["reason"], f"the second 10001 skipped {rows[8]}")
check(rows[9]["action"] == "skip" and "Name missing" in rows[9]["reason"], f"a row without name skipped {rows[9]}")
check(sql("SELECT COUNT(*) FROM clients")[0][0] == before and not sql("SELECT 1 FROM office_suppliers"), "the check writes nothing")

r = up(A, I, F16)
check(r.status_code == 201, "import of the master data " + r.text[:300])
RUN1 = r.json()["run_id"]
cl = clients(A)
check("10001" in cl and cl["10001"]["name"] == "Beispiel Handel GmbH" and cl["10001"].get("vat_id") == "DE123456789" and cl["10001"].get("city") == "Köln",
      f"client 10001 made {cl.get('10001')}")
check("10002" in cl and cl["10002"]["name"] == "Erika Muster", "client 10002 (a person) made")
check(cl["10003"]["id"] == OLD and cl["10003"].get("street") == "Weg 2" and cl["10003"].get("city") == "Bonn", f"10003: street filled, city kept {cl.get('10003')}")
sp = A.get(B + O + "/datev/suppliers").json()["items"]
check(len(sp) == 1 and sp[0]["account_no"] == "70001" and sp[0]["name"] == "Muster Bau GmbH" and sp[0]["iban"] == "DE02120300000000202051", f"one supplier {sp}")
raw = sql("SELECT name, street, iban, account_no FROM office_suppliers WHERE org_id=?", (ORG,))
check(len(raw) == 1 and enc(raw[0][0]) and enc(raw[0][1]) and enc(raw[0][2]) and raw[0][3] == "70001", "supplier name, address, IBAN encrypted at rest")
log = sql("SELECT target FROM office_doc_log WHERE org_id=? AND action='import'", (ORG,))
check([x[0] for x in log] == ["datev_in"], f"the import is in the office log {log}")
r = up(A, I + "/check", F16)
check(r.ok and r.json()["counts"]["new"] == 0 and r.json()["counts"]["updated"] == 0, f"the same file again: nothing new {r.json().get('counts')}")


# ---------------------------------------------------------------- the creditor of a receipt in the DATEV batch
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


def receipt(s, ws, name, amount, day, sender):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Beleg " + name), "application/pdf")})
    assert r.status_code == 201, r.text
    nid = r.json()["ids"][0]
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day, "sender": sender})
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"category": "Material", "vat_pct": "19", "keep": True})
    assert r.ok, r.text
    return nid


DAY = P0.replace(day=5).isoformat()
R1 = receipt(A, f"org:{ORG}", "bau.pdf", "119.00", DAY, "Muster Bau")
R2 = receipt(A, f"org:{ORG}", "anderer.pdf", "59.50", DAY, "Ganz Anderer Laden")
end = (P0.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
r = A.get(B + O + f"/datev/extf?from={P0.isoformat()}&to={end.isoformat()}")
check(r.ok, "the DATEV batch " + r.text[:200])
lines = {x.split(";")[10].strip('"'): x.split(";") for x in r.content.decode("cp1252").split("\r\n")[2:-1]}
check(lines.get(f"B{R1}", [""] * 8)[7] == "70001", f"a receipt of the supplier (sender without legal form) on its creditor 70001 {lines.get(f'B{R1}', [])[:10]}")
check(lines.get(f"B{R2}", [""] * 8)[7] == "70000", f"another receipt on the collective creditor 70000 {lines.get(f'B{R2}', [])[:10]}")

# ---------------------------------------------------------------- suppliers: rename, delete, restore
SID = sp[0]["id"]
r = A.put(B + O + f"/datev/suppliers/{SID}", json={"name": "Muster Bau Berlin GmbH"})
check(r.ok and r.json()["name"] == "Muster Bau Berlin GmbH", "rename a supplier " + r.text[:200])
check(A.put(B + O + f"/datev/suppliers/{SID}", json={"name": "  "}).status_code == 400, "an empty name: 400")
check(A.delete(B + O + f"/datev/suppliers/{SID}").ok and A.get(B + O + "/datev/suppliers").json()["items"] == [], "deleted: gone from the list")
check(A.post(B + O + f"/datev/suppliers/{SID}/restore").ok and len(A.get(B + O + "/datev/suppliers").json()["items"]) == 1, "restored")
A.put(B + O + f"/datev/suppliers/{SID}", json={"name": "Muster Bau GmbH"})

# ---------------------------------------------------------------- rights: member, another organisation
check(up(Bo, I + "/check", F16).status_code == 403 and up(Bo, I, F16).status_code == 403, "a member without the admin role: 403 on check / import")
check(Bo.get(B + O + "/datev/suppliers").status_code == 403 and Bo.get(B + O + "/datev/opening").status_code == 403, "a member: 403 on suppliers / opening balances")
check(Ca.get(B + O + "/datev/suppliers").json()["items"] == [], "another organisation sees no supplier")
check(Ca.post(B + I + f"/{RUN1}/undo").status_code == 404, "another organisation: 404 on a foreign run")
check(Ca.put(B + O + f"/datev/suppliers/{SID}", json={"name": "X"}).status_code == 404 and Ca.delete(B + O + f"/datev/suppliers/{SID}").status_code == 404,
      "another organisation: 404 on a foreign supplier")

# ---------------------------------------------------------------- undo (own route) and the import page's undo
runs = A.get(B + O + "/legacy/runs").json()["runs"]
check(any(x["id"] == RUN1 and x["kind"] == "datev" for x in runs), "the run is in the import page's list (kind datev)")
r = A.post(B + I + f"/{RUN1}/undo")
check(r.ok, "undo the master data run " + r.text[:200])
cl = clients(A)
check("10001" not in cl and "10002" not in cl and cl.get("10003", {}).get("street", "x") == "" and cl["10003"].get("city") == "Bonn",
      f"undone: new clients gone, the filled street empty again, the city as before {cl.get('10003')}")
check(A.get(B + O + "/datev/suppliers").json()["items"] == [] and not sql("SELECT 1 FROM office_suppliers WHERE org_id=?", (ORG,)), "the supplier is gone for good")
check(A.post(B + I + f"/{RUN1}/undo").status_code == 409, "a second undo: 409")
r = up(A, I, F16)
RUN2 = r.json()["run_id"]
check(r.status_code == 201 and len(A.get(B + O + "/datev/suppliers").json()["items"]) == 1, "imported again")
r = A.post(B + O + f"/legacy/runs/{RUN2}/undo")
check(r.ok and A.get(B + O + "/datev/suppliers").json()["items"] == [] and "10001" not in clients(A), "the import page's undo takes a DATEV run back too " + r.text[:200])

# ---------------------------------------------------------------- booking batch: only the opening balances
F21 = extf21([("1500,00", "S", "1200", "9000", "0101", "EB Bank"),
              ("25000,00", "S", "9000", "0800", "0101", "Gezeichnetes Kapital"),
              ("300,00", "S", "1000", "1200", "0101", "EB-Wert Kasse"),
              ("1190,00", "S", "10001", "8400", "1502", "Rechnung 1"),
              ("abc", "S", "1600", "9009", "0101", "EB kaputt")], f"{LY}0101")
r = up(A, I + "/check", F21)
check(r.ok, "check of a booking batch " + r.text[:300])
j = r.json()
check(j["category"] == 21 and j["counts"]["opening"] == 3 and j["counts"]["other"] == 1 and j["counts"]["skipped"] == 1, f"3 opening, 1 other, 1 skipped {j.get('counts')}")
check(any("only opening balances" in h for h in j["hints"]), f"the hint: no financial accounting {j['hints']}")
pv = {x["account"]: x for x in j["rows"]}
check(pv["1200"]["side"] == "S" and pv["1200"]["amount"] == "1500.00" and pv["1200"]["year"] == LY, f"1200 debit 1500 in {LY} {pv.get('1200')}")
check(pv["0800"]["side"] == "H" and pv["0800"]["amount"] == "25000.00", f"9000 against 0800: 0800 on the credit side {pv.get('0800')}")
check(pv["1000"]["action"] == "new", "a booking text starting with EB counts")
check("10001" not in pv, "the invoice booking is not in the preview list")
check(not sql("SELECT 1 FROM office_opening_balances"), "the check writes nothing")
r = up(A, I, F21)
check(r.status_code == 201, "import of the booking batch " + r.text[:200])
RB1 = r.json()["run_id"]
ob = A.get(B + O + f"/datev/opening?year={LY}").json()
check(len(ob["items"]) == 3 and ob["debit"] == "1800.00" and ob["credit"] == "25000.00" and LY in ob["years"], f"opening balances {LY} {ob}")
F21b = extf21([("1700,00", "S", "1200", "9000", "0101", "EB Bank neu")], f"{LY}0101", bom=False)
r = up(A, I + "/check", F21b)
check(r.ok and r.json()["counts"]["replaced"] == 1 and r.json()["rows"][0]["action"] == "replace", f"the preview says it replaces 1200 {r.text[:300]}")
r = up(A, I, F21b)
RB2 = r.json()["run_id"]
ob = A.get(B + O + f"/datev/opening?year={LY}").json()
b12 = [x for x in ob["items"] if x["account"] == "1200"]
check(len(ob["items"]) == 3 and len(b12) == 1 and b12[0]["amount"] == "1700.00", f"replaced, not added {ob['items']}")
check(A.post(B + I + f"/{RB2}/undo").ok, "undo the second batch")
b12 = [x for x in A.get(B + O + f"/datev/opening?year={LY}").json()["items"] if x["account"] == "1200"]
check(len(b12) == 1 and b12[0]["amount"] == "1500.00", f"the earlier balance is back {b12}")
check(A.get(B + O + f"/datev/opening?year={LY + 1}").json()["items"] == [], "another year: none")

# ---------------------------------------------------------------- wrong files
def bad(raw, code, what):
    r = up(A, I + "/check", raw)
    check(r.status_code == code, f"{what}: {code} ({r.status_code} {r.text[:160]})")
    return r


bad(b"Konto;Name\r\n10001;X\r\n", 400, "no EXTF header")
r = bad(F16.replace(b'"EXTF";700;16;', b'"EXTF";700;20;', 1), 400, "category 20 (Sachkontenbeschriftungen)")
check("category 16" in r.text, "the reason names the categories that work")
bad(F16.replace(b'"Debitoren/Kreditoren";5;', b'"Debitoren/Kreditoren";99;', 1), 400, "format version 99")
bad(head(21, "Buchungsstapel", 13, f"{LY}0101").encode() + b"\r\n\"Konto\";\"Buchungstext\"\r\n1200;x\r\n", 400, "a batch without amount columns")
bad(F16[:F16.index(b"\r\n") + 2] + b"\r\n".join(b"1;x" for _ in range(20002)) + b"\r\n", 400, "more than 20 000 rows")
r = up(A, I + "/check", b"x" * (10 * 1024 * 1024 + 10))
check(r.status_code in (400, 413), f"larger than 10 MB: refused ({r.status_code})")

# ---------------------------------------------------------------- a locked month refuses the whole file (409)
r = A.post(B + O + "/periods/lock", json={"through": f"{LY}-01", "confirm": f"01/{LY}"})
check(r.ok, "January of last year locked " + r.text[:200])
check(up(A, I + "/check", F21b).status_code == 409, "check: an opening booking in a locked month 409")
r = up(A, I, F21b)
check(r.status_code == 409 and "locked" in r.text, "import: the whole file refused (409) " + r.text[:200])
check(len(A.get(B + O + f"/datev/opening?year={LY}").json()["items"]) == 3, "nothing changed")
check(up(A, I + "/check", F16).ok, "master data have no date: not locked")

# ---------------------------------------------------------------- a person without organisation (personal office)
E16 = extf16([{"Konto": "10010", "Name (Adressatentyp Unternehmen)": "Kundin Beispiel UG", "Ort": "Leipzig"},
              {"Konto": "70010", "Name (Adressatentyp Unternehmen)": "Druckerei Muster", "Ort": "Halle"}], encoding="utf-8")
r = up(Er, I + "/check", E16)
check(r.ok and r.json()["counts"]["new"] == 2, "freelancer: the preview " + r.text[:200])
r = up(Er, I, E16)
check(r.status_code == 201, "freelancer: imported " + r.text[:200])
ec = clients(Er)
check("10010" in ec, "freelancer: its own client 10010")
row = sql("SELECT org_id, created_by FROM clients WHERE customer_no='10010'")
check(len(row) == 1 and row[0][0] is None and row[0][1] == FID, f"a private client (no organisation, created by the person) {row}")
es = Er.get(B + O + "/datev/suppliers").json()["items"]
check([x["account_no"] for x in es] == ["70010"], f"freelancer: its own supplier only {es}")
check([x["account_no"] for x in A.get(B + O + "/datev/suppliers").json()["items"]] == [], "Alpha does not see the freelancer's supplier")
check("10010" not in clients(A), "Alpha does not see the freelancer's client")
r = up(Er, I, extf21([("800,00", "S", "1200", "9000", "0101", "EB Bank")], f"{TODAY.year}0101"))
check(r.status_code == 201 and len(Er.get(B + O + f"/datev/opening?year={TODAY.year}").json()["items"]) == 1, "freelancer: an opening balance")
check(Er.post(B + I + f"/{RB1}/undo").status_code == 404, "freelancer: 404 on Alpha's run")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
