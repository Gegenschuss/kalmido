#!/usr/bin/env python3
"""2.120.0 API tests, part C (#2090): the DATEV booking batch with the input side (receipts and travel expenses).
Invented companies, people and numbers only.
 - settings (datev_extf, additive): in_on, in_counter creditor | bank, creditor, in_other, cat_accounts, travel, bu_in;
   validated (400), a member 403, other settings saves keep them
 - GET /api/office/datev/accounts: admin only (member 403, agent 403, another organisation never sees Alpha's categories)
 - the batch: one line per receipt with an amount (expense account of its category against the collective creditor 70000,
   tax key 9 / 8 for 19 % / 7 %, none for an unknown rate), own category accounts, a receipt without category on the other
   expenses account, a receipt without amount not exported but counted in the check's hints, per travel receipt one line
   on the travel account (no tax key), the per diem of a trip one line on its last day; Belegfeld 1 unique
 - ?in=0 and in_on=0 leave the input side out; the invoices' lines stay as they were
 - Windows-1252, CRLF, 125 fields per line, the sum of the input lines, the fiscal year limit (a receipt of the next fiscal
   year is not in the batch), SKR04 + ledger length 5 (stretched defaults, creditor 6 digits), counter account bank
 - a person without organisation (personal office, small business): its own batch with its receipts, no input tax key,
   the owner's travel accounts; nobody else's receipts in it
usage: p2120_c_api_test.py <datadir>      (P2120C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)
freelancer-matrix: office"""
import os
import re
import subprocess
import sys
from decimal import Decimal

import requests

import dbx as dbxm
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


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


def batch(s, q):
    r = s.get(B + X + q)
    assert r.ok, r.text
    raw = r.content
    txt = raw.decode("cp1252")
    lines = txt.split("\r\n")
    return raw, lines, [l.split(";") for l in lines[2:-1]]


def by_beleg(rows):
    return {x[10].strip('"'): x for x in rows}


def amt(x):
    return Decimal(x[0].replace(",", "."))


FEAT = "cal,comments,collab,office,clients,time,docs,files,travel"
if os.environ.get("P2120C_NOSTART") != "1":
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
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carol"]}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
X = O + "/datev/extf"
ACC = O + "/datev/accounts"
P = "?from=2026-03-01&to=2026-03-31"

A.put(B + O + "/settings", json={"company": {"name": "Studio Beispiel GmbH"}, "currency": "EUR",
                                 "company_fields": {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg",
                                                    "country": "DE", "tax_number": "12/345/67890", "vat_id": "DE999999999",
                                                    "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
r = A.put(B + O + "/settings", json={"datev_extf": {"advisor_no": "1234567", "client_no": "12345", "fy_start": 1, "acct_len": 4, "chart": "SKR03"}})
check(r.ok, "DATEV numbers stored " + r.text[:160])
st = r.json()["settings"]["datev_extf"]
check(st.get("in_on") == 1 and st.get("in_counter") == "creditor" and st.get("cat_accounts") == {} and st.get("travel") == {},
      f"input side defaults: on, collective creditor, no own accounts {st}")

# ---------------------------------------------------------------- settings validated
for bad in ({"in_counter": "cash"}, {"creditor": "7x000"}, {"creditor": "700000"}, {"in_other": "49000"}, {"cat_accounts": "x"},
            {"cat_accounts": {"Software": "49a4"}}, {"travel": {"fares": "466300"}}, {"bu_in": {"19": "12345"}}):
    check(A.put(B + O + "/settings", json={"datev_extf": bad}).status_code == 400, f"input side settings validated: {bad}")
check(Bo.put(B + O + "/settings", json={"datev_extf": {"in_on": 0}}).status_code == 403, "member cannot change the input side (403)")

# ---------------------------------------------------------------- an invoice (the output side stays as it was)
C1 = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50000", "city": "Köln", "country": "DE"}).json()["id"]
r = A.post(B + D, json={"kind": "invoice", "client_id": C1, "service_from": "2026-03-01", "service_to": "2026-03-15",
                        "items": [{"title": "Schnitt", "qty": 1, "rate": 1000}]})
assert r.status_code == 201, r.text
I1 = r.json()["id"]
r = A.post(B + f"{D}/{I1}/finalize")
assert r.ok, r.text
N1 = r.json()["number"]
dbx("UPDATE office_docs SET date=? WHERE id=?", ("2026-03-05", I1))
_, _, out_only = batch(A, P + "&in=0")
check(len(out_only) == 1 and out_only[0][6] == "10000" and out_only[0][7] == "8400", f"?in=0: only the invoice line {out_only}")

# ---------------------------------------------------------------- receipts of Alpha's documents space
WSO = f"org:{ORG}"
R1 = receipt(A, WSO, "software.pdf", "119.00", "2026-03-02", "Software", "19")
R2 = receipt(A, WSO, "fachbuch.pdf", "107.00", "2026-03-03", "Fachliteratur", "7")
R3 = receipt(A, WSO, "kasse.pdf", "50.00", "2026-03-04", "", None)
R4 = receipt(A, WSO, "druckerei.pdf", "238.00", "2026-03-06", "Druckerei Spezial", "19")
R5 = receipt(A, WSO, "ohne-betrag.pdf", None, "2026-03-07", "Software", "19")
R6 = receipt(A, WSO, "april.pdf", "20.00", "2026-04-01", "Software", "19")  # outside the period
R7 = receipt(A, WSO, "naechstes-jahr.pdf", "30.00", "2027-01-02", "Software", "19")  # next fiscal year
r = A.post(B + "/api/office/trips", json={"date_from": "2026-03-10", "date_to": "2026-03-11", "dest": "Drehort Köln", "overnight": 1, "country": "DE",
                                          "items": [{"date": "2026-03-10", "category": "train", "amount": 89.9},
                                                    {"date": "2026-03-10", "category": "hotel", "amount": 120},
                                                    {"date": "2026-03-11", "category": "parking", "amount": 12}]})
check(r.status_code == 201, "a trip with three travel receipts " + r.text[:160])
TRIP = r.json()
TID = TRIP["id"]
ITEMS = {x["category"]: x["id"] for x in TRIP["items"]}
VMA = TRIP["vma"]["total"]

# ---------------------------------------------------------------- rights on the accounts route and the export
check(Bo.get(B + ACC).status_code == 403 and Bo.get(B + X + P).status_code == 403, "member: 403 on accounts and export")
check(requests.get(B + ACC, headers=AGH).status_code == 403 and requests.get(B + X + P, headers=AGH).status_code == 403, "agent: 403")
rc = Ca.get(B + ACC)
check(rc.ok and not any(x["name"] in ("Software", "Fachliteratur") for x in rc.json()["categories"]), "another organisation: never Alpha's categories")
j = A.get(B + ACC).json()
cats = {x["name"]: x for x in j["categories"]}
check(cats.get("Software", {}).get("default") == "4964" and cats.get("Fachliteratur", {}).get("default") == "4940"
      and cats.get("Druckerei Spezial", {}).get("default") == "4900", f"accounts: defaults found by words, unknown = other expenses {cats}")
check({t["key"]: t["default"] for t in j["travel"]} == {"fares": "4663", "hotel": "4666", "vma": "4664", "other": "4660"},
      f"accounts: the employees' travel accounts of an organisation {j['travel']}")
check(j["creditor"] == "70000" and j["other"] == "4900", f"accounts: creditor and other expenses {j}")

# ---------------------------------------------------------------- the check and the file
r = A.get(B + X + P + "&check=1")
check(r.ok, "check " + r.text[:200])
ch = r.json()
hk = {h["key"]: h for h in ch.get("hints", [])}
check(hk.get("no_amount", {}).get("count") == 1 and "not exported" in hk["no_amount"]["text"], f"hint: one receipt without amount not exported {ch.get('hints')}")
check(hk.get("no_category", {}).get("count") == 1 and "4900" in hk["no_category"]["text"], f"hint: one receipt without category on 4900 {ch.get('hints')}")
check(hk.get("no_vat", {}).get("count") == 1, f"hint: one receipt without VAT rate {ch.get('hints')}")
raw, lines, rows = batch(A, P)
check(ch["count"] == len(rows) == 1 + 4 + 3 + (1 if VMA and Decimal(VMA) else 0), f"the batch: invoice + 4 receipts + 3 travel receipts + per diem ({ch['count']}, {len(rows)}, vma {VMA})")
check(raw.endswith(b"\r\n") and b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), "CRLF only")
check(all(len(x) == 125 for x in rows), "125 fields in every line")
check("Drehort Köln".encode("cp1252") in raw and "Drehort Köln".encode("utf-8") not in raw, "Windows-1252 (the trip's destination)")
bb = by_beleg(rows)
check(len(bb) == len(rows), f"Belegfeld 1 unique {sorted(bb)}")
x = bb.get(f"B{R1}")
check(x and x[0] == "119,00" and x[1] == '"S"' and x[6] == "4964" and x[7] == "70000" and x[8] == '"9"' and x[9] == "0203",
      f"receipt 19 %: 119,00 S software 4964 against 70000, key 9, date 0203 {x and x[:11]}")
x = bb.get(f"B{R2}")
check(x and x[6] == "4940" and x[8] == '"8"', f"receipt 7 %: literature 4940, key 8 {x and x[:11]}")
x = bb.get(f"B{R3}")
check(x and x[6] == "4900" and x[8] == "", f"receipt without category and rate: 4900, no key {x and x[:11]}")
check(f"B{R5}" not in bb and f"B{R6}" not in bb and f"B{R7}" not in bb, "no receipt without amount, of April or of the next year")
x = bb.get(f"R{TID}-{ITEMS['train']}")
check(x and x[0] == "89,90" and x[6] == "4663" and x[7] == "70000" and x[8] == "" and x[9] == "1003", f"train: fares 4663, no key {x and x[:11]}")
x = bb.get(f"R{TID}-{ITEMS['hotel']}")
check(x and x[6] == "4666", f"hotel: 4666 {x and x[:11]}")
x = bb.get(f"R{TID}-{ITEMS['parking']}")
check(x and x[6] == "4663" and x[9] == "1103", f"parking: fares 4663, date 1103 {x and x[:11]}")
if VMA and Decimal(VMA):
    x = bb.get(f"V{TID}")
    check(x and amt(x) == Decimal(VMA) and x[6] == "4664" and x[8] == "" and x[9] == "1103", f"per diem: {VMA} on 4664, last day {x and x[:11]}")
ins = [x for x in rows if re.fullmatch(r"[BRV]\d+(-\d+)?", x[10].strip('"'))]  # the invoice number may start with R as well
check(sum((amt(x) for x in ins), Decimal(0)) == Decimal("119") + Decimal("107") + Decimal("50") + Decimal("238") + Decimal("221.90") + Decimal(VMA or 0),
      "sum of the input side lines")
check(by_beleg(out_only).get(N1) == bb.get(N1), "the invoice line is the same with and without the input side")
check(lines[0].startswith('"EXTF";700;21;"Buchungsstapel";13;'), "header line unchanged")

# ---------------------------------------------------------------- own accounts, switch off, bank, SKR04
r = A.put(B + O + "/settings", json={"datev_extf": {"cat_accounts": {"Software": "4806", "druckerei spezial": "4610"}, "travel": {"hotel": "4676"},
                                                    "bu_in": {"19": "19"}, "creditor": "79999"}})
check(r.ok and r.json()["settings"]["datev_extf"]["cat_accounts"] == {"software": "4806", "druckerei spezial": "4610"}, "own category accounts stored " + r.text[:200])
check(A.put(B + O + "/settings", json={"payment_days": 21}).json()["settings"]["datev_extf"]["creditor"] == "79999", "another settings save keeps them")
bb = by_beleg(batch(A, P)[2])
check(bb[f"B{R1}"][6] == "4806" and bb[f"B{R4}"][6] == "4610" and bb[f"B{R1}"][7] == "79999" and bb[f"B{R1}"][8] == '"19"'
      and bb[f"R{TID}-{ITEMS['hotel']}"][6] == "4676", "own accounts, creditor and tax key used")
check({x["name"]: x["account"] for x in A.get(B + ACC).json()["categories"]}.get("Software") == "4806", "accounts route shows the own account")
A.put(B + O + "/settings", json={"datev_extf": {"in_counter": "bank"}})
check(by_beleg(batch(A, P)[2])[f"B{R1}"][7] == "1200", "counter account bank: 1200")
A.put(B + O + "/settings", json={"datev_extf": {"in_on": 0}})
r = A.get(B + X + P + "&check=1").json()
check(r["count"] == 1 and r["hints"] == [], f"in_on 0: only the invoice, no hints {r}")
A.put(B + O + "/settings", json={"datev_extf": {"in_on": 1, "in_counter": "creditor", "creditor": "", "cat_accounts": {}, "travel": {}, "bu_in": {},
                                                    "chart": "SKR04", "acct_len": 5}})
bb = by_beleg(batch(A, P)[2])
check(bb[f"B{R1}"][6] == "68370" and bb[f"B{R1}"][7] == "700000" and bb[f"B{R3}"][6] == "63000" and bb[f"R{TID}-{ITEMS['train']}"][6] == "66630",
      f"SKR04 + length 5: 68370 / creditor 700000 / 63000 / 66630 {bb[f'B{R1}'][:9]}")
check(A.get(B + X + "?from=2026-12-01&to=2027-01-31&check=1").status_code == 400, "fiscal year limit still holds")
A.put(B + O + "/settings", json={"datev_extf": {"chart": "SKR03", "acct_len": 4}})

# ---------------------------------------------------------------- a person without organisation (personal office, small business)
FID, Fr = freelancer(B, A, "fiona")
r = Fr.put(B + O + "/settings", json={"small_business": 1, "datev_extf": {"advisor_no": "1234567", "client_no": "99"},
                                      "company_fields": {"name": "Fiona Film", "street": "Musterweg 2", "zip": "12345", "city": "Musterstadt", "country": "DE",
                                                         "tax_number": "12/345/67891", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}})
check(r.ok, "freelancer: own DATEV settings " + r.text[:160])
FR = receipt(Fr, "private", "objektiv.pdf", "119.00", "2026-03-04", "Equipment", "19")
r = Fr.post(B + "/api/office/trips", json={"date_from": "2026-03-12", "dest": "Kunde Beispiel", "items": [{"date": "2026-03-12", "category": "taxi", "amount": 25}]})
check(r.status_code == 201, "freelancer: a trip " + r.text[:120])
FT = r.json()
j = Fr.get(B + ACC).json()
check({t["key"]: t["default"] for t in j["travel"]}.get("fares") == "4673" and any(x["name"] == "Equipment" for x in j["categories"]),
      f"freelancer: the owner's travel accounts and own categories {j}")
fb = by_beleg(batch(Fr, P)[2])
x = fb.get(f"B{FR}")
check(x and x[6] == "4985" and x[8] == "", f"freelancer, small business: equipment 4985 without input tax key {x and x[:11]}")
x = fb.get(f"R{FT['id']}-{FT['items'][0]['id']}")
check(x and x[6] == "4673", f"freelancer: taxi on the owner's fares account 4673 {x and x[:11]}")
check(not any(re.fullmatch(r"B\d+", k) and k != f"B{FR}" for k in fb), f"freelancer: only own receipts {sorted(fb)}")
check(f"B{FR}" not in by_beleg(batch(A, P)[2]), "the freelancer's receipt never in Alpha's batch")
check(Ca.get(B + X + P).status_code in (400, 403) or f"B{R1}" not in by_beleg(batch(Ca, P)[2]), "another organisation never gets Alpha's receipts")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
