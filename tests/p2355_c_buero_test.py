#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.355.0 C: VAT figures, cash discount and e-invoice categories of the office (#2840, #2841, #2844). Invented names only.
freelancer-matrix: office
 - #2840 a cash discount taken lowers the accrual VAT base per rate (field 81 980, not 1000) in the period of its payment,
   the DATEV batch books it debtor against 8736 (H); a discount period longer than the payment terms stops finalising
 - #2841 a payment reversal is dated on the payment's day (December payment taken back later: the year's VAT stays right),
   an older reversal line dated on the correction day counts on the payment's day in the books and the key figures
 - #2844 VAT note eu_goods: the client in another EU state with its VAT id (else 400), category K + deliver-to country in the
   XML, field 41; export: a client outside the EU, category G, field 43; reverse charge at home = field 60 / DATEV 8337,
   to the EU = field 21 / DATEV 8336; a foreign currency without a rate is not finalised
 - the same for a person without an organisation (own office): eu_goods + field 41, the discount period check
usage: p2355_c_buero_test.py <datadir>"""
import os
import subprocess
import sys

import requests

import dbx as dbxm
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


FEAT = "cal,comments,collab,office,clients,time"
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
O = "/api/office"
D = O + "/docs"
BK = O + "/books"
COMPANY = {"name": "Studio Beispiel GmbH", "street": "Teststraße 1", "zip": "20000", "city": "Hamburg", "country": "DE",
           "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def office(s):
    r = s.put(B + O + "/settings", json={"company": {"name": COMPANY["name"]}, "lang": "en", "currency": "EUR", "company_fields": COMPANY,
                                         "payment_days": 14, "datev_extf": {"advisor_no": "1234567", "client_no": "12345", "chart": "SKR03"}})
    check(r.ok, "office settings " + r.text[:200])


def client(s, name, country, vat_id=""):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Weg 1", "zip": "1000", "city": "Ort", "country": country, "vat_id": vat_id})
    assert r.ok, r.text
    return r.json()["id"]


def draft(s, cl, rate=1000, extra=None):
    r = s.post(B + D, json=dict({"kind": "invoice", "client_id": cl, "service_from": "2026-03-01", "service_to": "2026-03-02",
                                 "items": [{"title": "Leistung", "qty": 1, "rate": rate}]}, **(extra or {})))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def final(s, did, date=None):
    r = s.post(B + f"{D}/{did}/finalize")
    check(r.ok, f"finalised {did} " + r.text[:200])
    if date:
        dbx("UPDATE office_docs SET date=? WHERE id=?", (date, did), write=True)
    return r


def ustva(s, period, year=2026):
    return s.get(B + BK + f"/ustva?year={year}&period={period}").json()


def extf(s, frm, to):
    r = s.get(B + O + f"/datev/extf?from={frm}&to={to}")
    check(r.ok, "DATEV batch " + r.text[:200])
    rows = r.content.decode("cp1252").split("\r\n")
    cols = rows[1].split(";")
    return [dict(zip(cols, x.split(";"))) for x in rows[2:] if x]


g = lambda row, k: row.get('"' + k + '"', row.get(k, "")).strip('"')  # noqa: E731

office(A)
C_DE = client(A, "Beispielkunde AG", "DE")
C_AT = client(A, "Example GmbH", "AT", "ATU99999999")
C_FR = client(A, "Exemple SARL", "FR")
C_US = client(A, "Example Inc", "US")
C_DV = client(A, "Baufirma Beispiel GmbH", "DE", "DE888888888")  # reverse charge at home (section 13b): the e-invoice wants BT-48

# ---------------------------------------------------------------- #2840 cash discount
r = A.put(B + O + "/settings", json={"vat_basis": "soll"})
check(r.ok and r.json()["settings"]["vat_basis"] == "soll", "accrual basis")
SK = draft(A, C_DE, extra={"skonto_pct": 2, "skonto_days": 10, "payment_days": 14})
final(A, SK, "2026-03-02")
r = A.post(B + f"{D}/{SK}/payments", json={"date": "2026-03-05", "amount": "1166.20", "method": "transfer"})
check(r.ok and A.get(B + f"{D}/{SK}").json()["status"] == "paid", "#2840: paid in time less 2 % = paid " + r.text[:200])
u = ustva(A, "m03")
check(u["kz"]["81"] == "980" and u["tax"]["19"] == "186.20", f"#2840: soll March, the base less the discount (980, not 1000) {u['kz']} {u['tax']}")
check(any(i.get("source") == "skonto" and i["doc_id"] == SK and i["gross"] == "-23.80" for i in u["items"]), "#2840: the discount is listed behind the figures")
check(ustva(A, "m04")["kz"]["81"] == "0", "#2840: nothing in April")
rows = extf(A, "2026-03-01", "2026-03-31")
sk = [x for x in rows if g(x, "Gegenkonto (ohne BU-Schlüssel)") == "8736"]
check(len(sk) == 1 and g(sk[0], "Umsatz (ohne Soll/Haben-Kz)") == "23,80" and g(sk[0], "Soll/Haben-Kennzeichen") == "H" and g(sk[0], "Konto") == "10000",
      f"#2840: DATEV books the discount on 8736 against the debtor {sk}")
A.put(B + O + "/settings", json={"vat_basis": "ist"})
check(ustva(A, "m03")["kz"]["81"] == "980", "#2840: cash basis unchanged (the payment itself)")
LONG = draft(A, C_DE, extra={"skonto_pct": 2, "skonto_days": 30, "payment_days": 14})
r = A.post(B + f"{D}/{LONG}/finalize")
check(r.status_code == 400 and "cash discount period" in r.text and "14" in r.text, "#2840: 30 days discount with 14 days to pay is refused " + r.text[:200])
check(A.patch(B + f"{D}/{LONG}", json={"skonto_days": 14}).ok and A.post(B + f"{D}/{LONG}/finalize").ok, "#2840: equal to the payment terms is fine")

# ---------------------------------------------------------------- #2841 reversal on the payment's day
ST = draft(A, C_DE, rate=500)
final(A, ST, "2025-12-20")
r = A.post(B + f"{D}/{ST}/payments", json={"date": "2025-12-28", "amount": "595.00"})
check(r.ok, "#2841: December payment " + r.text[:200])
P1 = A.get(B + f"{D}/{ST}/payments").json()["payments"][0]["id"]
check(ustva(A, "m12", 2025)["kz"]["81"] == "500", "#2841: the December payment counts in December")
r = A.delete(B + f"{D}/{ST}/payments/{P1}", json={"note": "wrong invoice"})
ps = A.get(B + f"{D}/{ST}/payments").json()["payments"]
rev = [p for p in ps if p.get("reverses_id") == P1]
check(r.ok and len(rev) == 1 and rev[0]["date"] == "2025-12-28", f"#2841: the reversal carries the payment's day {ps}")
check(ustva(A, "m12", 2025)["kz"]["81"] == "0" and ustva(A, "y")["kz"]["81"] == "980", "#2841: December 0 again, nothing moves into 2026")
# an older reversal line (2.152 - 2.354) dated on the correction day counts on the payment's day too
dbx("UPDATE office_payments SET date='2026-01-05' WHERE id=?", (rev[0]["id"],), write=True)
check(ustva(A, "m12", 2025)["kz"]["81"] == "0" and ustva(A, "m01")["kz"]["81"] == "0", "#2841: an old reversal line counts on the payment's day")
k25 = A.get(B + O + "/kpi?year=2025").json()["revenue"]
k26 = A.get(B + O + "/kpi?year=2026").json()["revenue"]
check(k25["months"][11]["amount"] == "0.00" and k26["months"][0]["amount"] == "0.00", f"#2841: key figures alike {k25['months'][11]} {k26['months'][0]}")

# ---------------------------------------------------------------- #2844 goods to the EU (K), export (G), reverse charge at home
A.put(B + O + "/settings", json={"vat_basis": "soll"})
NV = {"vat_mode": "novat"}
E1 = draft(A, C_FR, extra=dict(NV, vat_note="eu_goods"))
r = A.post(B + f"{D}/{E1}/finalize")
check(r.status_code == 400 and "client's VAT ID" in r.text, "#2844: goods to the EU without the client's VAT id refused " + r.text[:200])
E2 = draft(A, C_DE, extra=dict(NV, vat_note="eu_goods"))
r = A.post(B + f"{D}/{E2}/finalize")
check(r.status_code == 400 and "another EU country" in r.text, "#2844: goods to the EU for a client at home refused " + r.text[:200])
E3 = draft(A, C_AT, rate=700, extra=dict(NV, vat_note="eu_goods"))
final(A, E3, "2026-05-04")
x = A.get(B + f"{D}/{E3}/xml")
check(x.ok and b"<ram:CategoryCode>K</ram:CategoryCode>" in x.content and b"VATEX-EU-IC" in x.content and b"<ram:ShipToTradeParty>" in x.content
      and b"<ram:CountryID>AT</ram:CountryID>" in x.content and b"ATU99999999" in x.content and b"DE999999999" in x.content,
      "#2844: XML category K, exemption code, deliver-to country AT, both VAT ids " + x.text[:200])
E4 = draft(A, C_DE, rate=300, extra=dict(NV, vat_note="export"))
r = A.post(B + f"{D}/{E4}/finalize")
check(r.status_code == 400 and "outside the EU" in r.text, "#2844: export for a client at home refused " + r.text[:200])
E5 = draft(A, C_US, rate=300, extra=dict(NV, vat_note="export"))
final(A, E5, "2026-05-05")
x = A.get(B + f"{D}/{E5}/xml")
check(x.ok and b"<ram:CategoryCode>G</ram:CategoryCode>" in x.content and b"VATEX-EU-G" in x.content, "#2844: export = category G")
R1 = draft(A, C_DV, rate=400, extra=dict(NV, vat_note="reverse"))
final(A, R1, "2026-05-06")
R2 = draft(A, C_AT, rate=600, extra=dict(NV, vat_note="reverse"))
final(A, R2, "2026-05-07")
k = ustva(A, "m05")["kz"]
check(k["41"] == "700" and k["43"] == "300" and k["60"] == "400" and k["21"] == "600" and k["81"] == "0" and k["83"] == "0.00",
      f"#2844: fields 41 / 43 / 60 / 21 {k}")
rows = extf(A, "2026-05-01", "2026-05-31")
acc = {g(x, "Belegfeld 1"): g(x, "Gegenkonto (ohne BU-Schlüssel)") for x in rows if g(x, "Konto") == "10000"}
nums = {did: A.get(B + f"{D}/{did}").json()["number"] for did in (E3, E5, R1, R2)}
check(acc.get(nums[E3]) == "8125" and acc.get(nums[E5]) == "8120" and acc.get(nums[R1]) == "8337" and acc.get(nums[R2]) == "8336",
      f"#2844: DATEV accounts 8125 / 8120 / 8337 (13b at home) / 8336 (EU services) {acc} {nums}")
A.put(B + O + "/settings", json={"vat_basis": "ist"})
# a foreign currency without a rate: rate 1 = none
FX = draft(A, C_DE, extra={"currency": "GBP"})
check(float(A.get(B + f"{D}/{FX}").json()["fx_rate"] or 0) == 1, "GBP without an office rate starts at 1")
r = A.post(B + f"{D}/{FX}/finalize")
check(r.status_code == 400 and "exchange rate of GBP" in r.text, "#2844: foreign currency without a rate is not finalised " + r.text[:200])
check(A.patch(B + f"{D}/{FX}", json={"fx_rate": "0.85"}).ok and A.post(B + f"{D}/{FX}/finalize").ok, "#2844: with a rate it is")

# ---------------------------------------------------------------- the same without an organisation (own office)
FID, Fr = freelancer(B, A)  # freelancer-matrix: office
Fr.patch(B + "/api/settings", json={"features": FEAT})
office(Fr)
F_AT = client(Fr, "Example GmbH", "AT", "ATU99999999")
F1 = draft(Fr, F_AT, rate=250, extra=dict(NV, vat_note="eu_goods"))
final(Fr, F1, "2026-06-03")
Fr.put(B + O + "/settings", json={"vat_basis": "soll"})
check(ustva(Fr, "m06")["kz"]["41"] == "250", "freelancer: goods to the EU in field 41")
F2 = draft(Fr, F_AT, extra={"skonto_pct": 3, "skonto_days": 20, "payment_days": 10})
r = Fr.post(B + f"{D}/{F2}/finalize")
check(r.status_code == 400 and "cash discount period" in r.text, "freelancer: the discount period check " + r.text[:200])
check(Fr.get(B + f"{D}/{E3}").status_code in (403, 404), "freelancer: no document of the organisation")

print(f"p2355_c_buero: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
