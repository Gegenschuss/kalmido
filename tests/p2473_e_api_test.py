#!/usr/bin/env python3
"""2.47.3 API tests, part E: the DATEV booking batch (EXTF, #1460) of Office & finance and archiving several lists at once
(#1727). Invented companies, people and numbers only.
 - DATEV settings (admin only, validated): advisor / client number, fiscal year start, ledger length, chart, own accounts,
   tax keys, collective debtor, bank and cash account
 - GET /api/office/datev/extf: admin only (member 403, agent 403, a person without office 403 / 400); without advisor /
   client number 400 with a readable text; a period over two fiscal years 400; ?check=1 -> count + file name
 - the file: Windows-1252, CRLF, header line with 31 fields (EXTF;700;21;"Buchungsstapel";13 ...), 125 column names,
   booking lines with 125 fields; decimal comma, document date DDMM, S/H, Belegfeld 1 = invoice number
 - one line per tax rate (19 % -> 8400, 7 % -> 8300 in SKR03), reverse charge 8337, small business 8195 without tax key,
   a credit note H, payments bank S / cash; debtor from a numeric customer number, else
   the collective debtor; drafts and documents outside the period are not exported
 - SKR04 + ledger length 5: default accounts stretched (44000), debtor 6 digits (100000)
 - a 5-digit customer number is no debtor with ledger length 5 (collective debtor 100000)
 - the whole file equals the fixture fixtures/datev_extf_sample.csv (except the creation time stamp)
 - #1727: POST /api/lists/archive-many {ids}: archives the lists with the right, skips (and names) the others; one undo
usage: p2473_e_api_test.py <datadir>      (P2473E_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FIXTURE = os.path.join(N, "fixtures", "datev_extf_sample.csv")


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


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


FEAT = "cal,comments,collab,office,clients,time"
if os.environ.get("P2473E_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
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
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
X = O + "/datev/extf"

# ---------------------------------------------------------------- settings (invented company)
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel GmbH"}, "lang": "de", "currency": "EUR",
                                     "company_fields": {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg",
                                                        "country": "DE", "tax_number": "12/345/67890", "vat_id": "DE999999999",
                                                        "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
check(r.ok, "company settings " + r.text[:200])
st = A.get(B + O + "/settings").json()["settings"]
check(st.get("datev_extf") == {}, f"datev_extf defaults to an empty dict: {st.get('datev_extf')}")
P = "?from=2026-03-01&to=2026-03-31"
r = A.get(B + X + P + "&check=1")
check(r.status_code == 400 and "advisor number" in r.json().get("error", ""), "without advisor / client number: 400 with a readable text " + r.text[:160])
for bad in ({"advisor_no": "12"}, {"advisor_no": "1000"}, {"client_no": "123456"}, {"fy_start": 13}, {"acct_len": 3}, {"chart": "SKR99"},
            {"accounts": {"standard": "84x0"}}, {"accounts": {"standard": "84000"}}, {"bu": {"standard": "12345"}}, {"bank": "abc"}):
    check(A.put(B + O + "/settings", json={"datev_extf": bad}).status_code == 400, f"datev settings validated: {bad}")
check(A.put(B + O + "/settings", json={"datev_extf": "nope"}).status_code == 400, "datev_extf must be an object")
check(Bo.put(B + O + "/settings", json={"datev_extf": {"advisor_no": "1234567"}}).status_code == 403, "member cannot change the DATEV settings (403)")
r = A.put(B + O + "/settings", json={"datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}})
check(r.ok and r.json()["settings"]["datev_extf"]["advisor_no"] == "1234567" and r.json()["settings"]["datev_extf"]["client_no"] == "12345",
      "DATEV settings stored " + r.text[:200])
r = A.put(B + O + "/settings", json={"payment_days": 21})
check(r.ok and r.json()["settings"]["datev_extf"]["advisor_no"] == "1234567", "another settings save keeps the DATEV settings")

# ---------------------------------------------------------------- documents (dates fixed in the database after finalising)
C1 = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE",
                                      "customer_no": "10042"}).json()["id"]
C2 = A.post(B + "/api/clients", json={"name": "Muster \"Film\" GmbH", "street": "Weg 2", "zip": "10000", "city": "Berlin", "country": "DE",
                                      "customer_no": "K-7"}).json()["id"]
C3 = A.post(B + "/api/clients", json={"name": "Example Ltd", "street": "1 High Street", "zip": "1000", "city": "Wien", "country": "AT",
                                      "vat_id": "ATU99999999"}).json()["id"]


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
    dbx("UPDATE office_docs SET date=? WHERE id=?", (date, did))
    return did, r.json()["number"]


I1, N1 = make("invoice", C1, [{"title": "Schnitt", "qty": 2, "rate": 500}, {"title": "Fachbuch", "qty": 1, "rate": 100, "tax": "reduced"}], "2026-03-05")
I2, N2 = make("invoice", C2, [{"title": "Beratung", "qty": 1, "rate": 1000}], "2026-03-10")
I3, N3 = make("invoice", C3, [{"title": "Animation", "qty": 1, "rate": 2000}], "2026-03-12", {"vat_mode": "novat", "vat_note": "reverse"})
I4, N4 = make("invoice", C1, [{"title": "Kleinauftrag", "qty": 1, "rate": 300}], "2026-03-20", {"vat_mode": "novat", "vat_note": "small"})
CR, NCR = make("credit", None, None, "2026-03-25", src=I2)
I5, N5 = make("invoice", C1, [{"title": "April", "qty": 1, "rate": 50}], "2026-04-02")  # outside the period
DRAFT = A.post(B + D, json={"kind": "invoice", "client_id": C1, "items": [{"title": "Entwurf", "qty": 1, "rate": 999}]}).json()["id"]
dbx("UPDATE office_docs SET date='2026-03-06' WHERE id=?", (DRAFT,))
for did, body in ((I1, {"date": "2026-03-15", "amount": "1000.00", "method": "transfer"}), (I1, {"date": "2026-03-16", "amount": "177.00", "method": "cash"}),
                  (I1, {"date": "2026-04-03", "amount": "5.00", "method": "transfer"})):
    r = A.post(B + f"{D}/{did}/payments", json=body)
    check(r.ok, f"payment recorded {body} " + r.text[:120])

# ---------------------------------------------------------------- access
check(Bo.get(B + X + P).status_code == 403, "member: 403 on the DATEV export")
check(requests.get(B + X + P, headers=AGH).status_code == 403, "agent: 403 on the DATEV export")
check(Ca.get(B + X + P).status_code in (400, 403), "a person without the organisation: no export")
check(A.get(B + X + "?from=2026-03-31&to=2026-03-01").status_code == 400, "end before start: 400")
check(A.get(B + X + "?from=2026-3-1&to=2026-03-31").status_code == 400, "malformed date: 400")
r = A.get(B + X + "?from=2026-12-01&to=2027-01-31&check=1")
check(r.status_code == 400 and "fiscal year" in r.json().get("error", ""), "period over two fiscal years: 400 " + r.text[:160])
r = A.get(B + X + P + "&check=1")
check(r.ok and r.json()["count"] == 8 and r.json()["file"] == "EXTF_Buchungsstapel_20260301_20260331.csv", f"check: 8 bookings + file name: {r.text[:200]}")
r = A.get(B + X)
check(r.ok, "default period (previous month) works " + r.text[:120])

# ---------------------------------------------------------------- the file
r = A.get(B + X + P)
check(r.ok and "attachment" in r.headers.get("Content-Disposition", "") and "EXTF_Buchungsstapel_20260301_20260331.csv" in r.headers.get("Content-Disposition", ""),
      "download with file name")
check("windows-1252" in r.headers.get("Content-Type", "").lower(), "content type names Windows-1252: " + r.headers.get("Content-Type", ""))
raw = r.content
check(b"\r\n" in raw and raw.count(b"\r\n") == raw.count(b"\n"), "CRLF line ends")
txt = raw.decode("cp1252")
check("ö" in txt and "ö".encode("cp1252") in raw and "ö".encode("utf-8") not in raw, "Windows-1252 encoding (umlauts single byte)")
lines = txt.split("\r\n")
check(lines[-1] == "", "file ends with CRLF")
lines = lines[:-1]
head = lines[0].split(";")
check(len(head) == 31, f"header: 31 fields ({len(head)})")
check(head[:5] == ['"EXTF"', "700", "21", '"Buchungsstapel"', "13"], f"header: EXTF 700 / 21 Buchungsstapel / version 13: {head[:5]}")
check(len(head[5]) == 17 and head[5].isdigit(), f"header: created YYYYMMDDHHMMSSFFF: {head[5]}")
check(head[10:16] == ["1234567", "12345", "20260101", "4", "20260301", "20260331"], f"header: advisor, client, fiscal year, ledger length, period: {head[10:16]}")
check(head[18] == "1" and head[21] == '"EUR"' and head[26] == '"03"', f"header: booking type 1, EUR, SKR 03: {head[18]} {head[21]} {head[26]}")
cols = lines[1].split(";")
check(len(cols) == 125 and cols[0] == "Umsatz (ohne Soll/Haben-Kz)" and cols[6] == "Konto" and cols[7] == "Gegenkonto (ohne BU-Schlüssel)" and cols[124] == "Abw. Skontokonto",
      f"column line: 125 names ({len(cols)})")
C = {n: i for i, n in enumerate(cols)}
rows = []
for ln in lines[2:]:
    f = ln.split(";")
    check(len(f) == 125, f"booking line with 125 fields ({len(f)}): {ln[:80]}")
    rows.append(f)
check(len(rows) == 8, f"8 booking lines: {len(rows)}")
g = lambda f, n: f[C[n]]
B1 = [f for f in rows if g(f, "Belegfeld 1") == f'"{N1}"']
check(len(B1) == 4, f"invoice 1: 2 tax rates + 2 payments = 4 lines ({len(B1)})")
inv1 = {g(f, "Gegenkonto (ohne BU-Schlüssel)"): f for f in B1 if g(f, "Konto") == "10042"}
check(set(inv1) == {"8400", "8300"}, f"invoice 1: revenue 19 % -> 8400, 7 % -> 8300 against the debtor of the customer number 10042: {set(inv1)}")
check(g(inv1.get("8400", rows[0]), "Umsatz (ohne Soll/Haben-Kz)") == "1190,00" and g(inv1.get("8300", rows[0]), "Umsatz (ohne Soll/Haben-Kz)") == "107,00",
      "gross per tax rate with decimal comma (1190,00 / 107,00)")
check(all(g(f, "Soll/Haben-Kennzeichen") == '"S"' and g(f, "Belegdatum") == "0503" and g(f, "WKZ Umsatz") == '"EUR"' for f in inv1.values()),
      "invoice: S, document date DDMM, EUR")
check(g(inv1.get("8400", rows[0]), "Leistungsdatum") == "15032026", "date of service DDMMYYYY")
check(g(inv1.get("8400", rows[0]), "Buchungstext").startswith(f'"{N1} Beispielkunde AG'), "booking text = number + client")
pay = [f for f in B1 if g(f, "Gegenkonto (ohne BU-Schlüssel)") == "10042"]
check(sorted((g(f, "Konto"), g(f, "Umsatz (ohne Soll/Haben-Kz)"), g(f, "Soll/Haben-Kennzeichen")) for f in pay) == [("1000", "177,00", '"S"'), ("1200", "1000,00", '"S"')],
      f"payments: bank 1200 and cash 1000 against the debtor, S: {[(g(f, 'Konto'), g(f, 'Umsatz (ohne Soll/Haben-Kz)')) for f in pay]}")
B2 = [f for f in rows if g(f, "Belegfeld 1") == f'"{N2}"']
check(len(B2) == 1 and g(B2[0], "Konto") == "10000" and g(B2[0], "Gegenkonto (ohne BU-Schlüssel)") == "8400",
      "a customer number that is no debtor number -> the collective debtor 10000")
check('""Film""' in g(B2[0], "Buchungstext"), "quotes inside a text field are doubled")
B3 = [f for f in rows if g(f, "Belegfeld 1") == f'"{N3}"']
check(len(B3) == 1 and g(B3[0], "Gegenkonto (ohne BU-Schlüssel)") == "8337" and g(B3[0], "Umsatz (ohne Soll/Haben-Kz)") == "2000,00", "reverse charge -> 8337, net = gross")
B4 = [f for f in rows if g(f, "Belegfeld 1") == f'"{N4}"']
check(len(B4) == 1 and g(B4[0], "Gegenkonto (ohne BU-Schlüssel)") == "8195" and g(B4[0], "BU-Schlüssel") == "", "small business -> 8195 without tax key")
BC = [f for f in rows if g(f, "Belegfeld 1") == f'"{NCR}"']
check(sorted((g(f, "Konto"), g(f, "Soll/Haben-Kennzeichen")) for f in BC) == [("10000", '"H"')],
      f"credit note H on the debtor: {[(g(f, 'Konto'), g(f, 'Soll/Haben-Kennzeichen')) for f in BC]}")
check(not [f for f in rows if g(f, "Belegfeld 1") == f'"{N5}"'] and "999,00" not in txt and "5,00;" not in txt.replace("105,00", ""),
      "documents / payments outside the period and drafts are not exported")
check([g(f, "Belegdatum") for f in rows] == sorted([g(f, "Belegdatum") for f in rows], key=lambda x: x[2:] + x[:2]), "lines sorted by date")

# the fixture: the same file except the creation time stamp (field 6) and the person who exported it (field 9)
norm = lambda t: [";".join(x if i not in (5, 8) else "" for i, x in enumerate(l.split(";"))) if n == 0 else l for n, l in enumerate(t.split("\r\n"))]
if os.environ.get("P2473E_WRITE_FIXTURE") == "1":
    with open(FIXTURE, "wb") as fh:
        fh.write(raw)
with open(FIXTURE, "rb") as fh:
    fx = fh.read().decode("cp1252")
fixed = lambda t: [l.replace(N1, "N1").replace(N2, "N2").replace(N3, "N3").replace(N4, "N4").replace(NCR, "NCR") for l in norm(t)]
fxn = [l.replace("RE-2026-001", "N1").replace("RE-2026-002", "N2").replace("RE-2026-003", "N3").replace("RE-2026-004", "N4").replace("GS-2026-001", "NCR") for l in norm(fx)]
check(fixed(txt) == fxn, "the file equals the fixture fixtures/datev_extf_sample.csv")

# ---------------------------------------------------------------- tax keys, SKR04, ledger length 5
r = A.put(B + O + "/settings", json={"datev_extf": {"chart": "SKR04", "acct_len": 5, "bu": {"standard": "3"}, "bank": "18100"}})
check(r.ok, "SKR04 + ledger length 5 " + r.text[:160])
txt = A.get(B + X + P).content.decode("cp1252")
rows = [l.split(";") for l in txt.split("\r\n")[2:-1]]
check(txt.split("\r\n")[0].split(";")[13] == "5" and txt.split("\r\n")[0].split(";")[26] == '"04"', "header: ledger length 5, SKR 04")
accts = {(g(f, "Konto"), g(f, "Gegenkonto (ohne BU-Schlüssel)"), g(f, "BU-Schlüssel")) for f in rows}
check(any(a[1] == "44000" and a[2] == '"3"' for a in accts) and any(a[1] == "43000" and a[2] == "" for a in accts),
      f"SKR04 defaults stretched to 5 digits (44000 / 43000), tax key 3 on 19 %: {sorted(accts)}")
check(any(a[0] == "100000" for a in accts) and any(a[0] == "18100" for a in accts) and any(a[0] == "16000" for a in accts),
      "6-digit collective debtor 100000, own bank account 18100, cash 16000")
check(A.put(B + O + "/settings", json={"datev_extf": {"fy_start": 7}}).ok, "fiscal year from July")
r = A.get(B + X + "?from=2026-06-01&to=2026-07-31&check=1")
check(r.status_code == 400 and "30.06.2026" in r.json().get("error", ""), "fiscal year July-June: June + July = two fiscal years " + r.text[:160])
txt = A.get(B + X + P).content.decode("cp1252")
check(txt.split("\r\n")[0].split(";")[12] == "20250701", "fiscal year start of March 2026 with July start = 20250701")
log = dbx("SELECT action, target FROM office_doc_log WHERE target='datev'")
check(len(log) >= 1 and log[0]["action"] == "export", "the export is in the office log")

# ---------------------------------------------------------------- #1727: archiving several lists (the client sends one
# PATCH /api/lists/<id> {archived} per marked list and keeps them as one undo step; the rights are the single list's)
LA = A.post(B + "/api/lists", json={"name": "Mark one"}).json()["id"]
LB = A.post(B + "/api/lists", json={"name": "Mark two"}).json()["id"]
LC = Bo.post(B + "/api/lists", json={"name": "Bob shares to view"}).json()["id"]
LD = Bo.post(B + "/api/lists", json={"name": "Bob shares as admin"}).json()["id"]
check(Bo.put(B + f"/api/lists/{LC}/members", json={"user_id": ALICE, "role": "view"}).ok and Bo.put(B + f"/api/lists/{LD}/members", json={"user_id": ALICE, "role": "admin"}).ok,
      "#1727 setup: Bob shares one list to view, one as list admin")
res = {lid: A.patch(B + f"/api/lists/{lid}", json={"archived": 1}).status_code for lid in (LA, LB, LC, LD)}
check(res[LA] == 200 and res[LB] == 200 and res[LD] == 200, f"#1727: own lists and a list admin's list are archived: {res}")
check(res[LC] == 403, f"#1727: a view-only list is refused (skipped and named by the client): {res[LC]}")
arch = lambda s, lid: next((x["archived"] for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)
check(arch(A, LA) and arch(A, LB) and arch(Bo, LD) and not arch(Bo, LC), "#1727: archived exactly the lists with the right")
# the undo step: archived 0 with _prev (a list restored elsewhere meanwhile is reported, not touched)
Bo.patch(B + f"/api/lists/{LD}", json={"archived": 0})
r = {lid: A.patch(B + f"/api/lists/{lid}", json={"archived": 0, "_prev": {"archived": 1}}).json() for lid in (LA, LB, LD)}
check(not arch(A, LA) and not arch(A, LB) and not arch(Bo, LD), "#1727: the undo brings all of them back")
check(not r[LA].get("conflicts") and not r[LB].get("conflicts"), f"#1727: no conflicts on the lists nobody touched: {r[LA].get('conflicts')} {r[LB].get('conflicts')}")
ra = requests.patch(B + f"/api/lists/{LA}", json={"archived": 1}, headers=AGH)
check(ra.status_code in (401, 403, 404), f"#1727: an agent without access cannot archive: {ra.status_code} {ra.text[:120]}")

print(f"p2473_e_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
