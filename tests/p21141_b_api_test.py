#!/usr/bin/env python3
"""2.114.1 API tests, part B (#2018, office: receipts of the books in the cash flow), own container (start.sh, org
encryption on). Invented companies, people, accounts and figures only. freelancer-matrix: office  tenant-matrix: office
 - a person without organisation (personal office, as found in the device test): invoice 1,190 gross paid through the
   bank, receipt 119 gross (software, 19 %) matched to the money out, tax reserve 30 %: the month shows 1,190 in,
   119 out (kind receipt, the receipt's node), reserve 300, freely available 771; net basis 100; a receipt matched to a
   booking of another amount counts with the booking; a receipt without a match counts on its document date (as the
   statement), a later one is planned; the undo of the match keeps it on its document date; once in the trash it goes;
   every receipt once; the key figures carry the same month
 - an organisation's admin: the matched receipt (amounts encrypted at rest) counts; a member 403; another organisation and
   the personal office never see each other's receipts
usage: p21141_b_api_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time
from datetime import date

import requests
import testclock
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
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


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library; as p290_b_api_test.py)."""
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


if not (os.environ.get("P21141B_NOSTART") or os.environ.get("KMT_NOSTART")):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    assert A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"}).ok
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,office,clients,docs,files"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: office (the personal office, its own admin)
O = "/api/office"
K = O + "/bank"
TODAY = testclock.today().isoformat()
MONTH = TODAY[:7]
NEXT = f"{int(MONTH[:4]) + int(MONTH[5:]) // 12:04d}-{int(MONTH[5:]) % 12 + 1:02d}"
de = lambda iso: f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"
COMPANY = {"street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "vat_id": "DE123456789",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
for s, name in ((A, "Beispiel Film GmbH"), (Ca, "Andere Firma GmbH"), (Fr, "Frida Film")):
    r = s.put(B + O + "/settings", json={"company_fields": {"name": name, **COMPANY}, "tax_reserve_pct": 30})
    assert r.ok, r.text


def invoice(s, rate):
    cl = s.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Weg 2", "zip": "10115", "city": "Berlin", "country": "DE"}).json()["id"]
    r = s.post(B + O + "/docs", json={"kind": "invoice", "client_id": cl, "service_from": TODAY, "items": [{"title": "Schnitt", "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{O}/docs/{did}/finalize")
    assert r.ok, r.text
    return {"id": did, "number": r.json()["number"]}


def receipt(s, name, amount, day, cat="Software", vat="19"):
    ws = s.get(B + O + "/books").json()["upload_ws"]
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name + ".pdf", tiny_pdf(name), "application/pdf")})
    assert r.ok, r.text
    nid = r.json()["ids"][0]
    r1 = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day, "name": name})
    r2 = s.put(B + f"/api/docs/{nid}/receipt", json={"category": cat, "vat_pct": vat})
    assert r1.ok and r2.ok, (r1.text, r2.text)
    return nid


def bank(s, rows):
    """rows [(day, counterpart, purpose, '1.190,00')] -> {purpose: booking}"""
    csv = "Buchungstag;Auftraggeber/Empfänger;Verwendungszweck;Betrag\n" + "".join(f"{de(d)};{c};{p};{a}\n" for d, c, p, a in rows)
    pv = s.post(B + K + "/import/preview", json={"text": csv}).json()
    mp = {k: pv["guess"].get(k) for k in ("date", "amount", "amount_in", "amount_out", "title", "counterpart", "decimal", "date_format")}
    r = s.post(B + K + "/import", json={"text": csv, "filename": "konto.csv", "mapping": mp})
    assert r.status_code == 201, r.text
    return {t["purpose"]: t for t in s.get(B + K + "/tx?state=all").json()["items"]}


def cf(s, basis="gross", months=3):
    r = s.get(B + O + f"/cashflow?from={MONTH}&months={months}&basis={basis}")
    assert r.ok, r.text
    return r.json()


def month(j, mo=MONTH):
    return next(x for x in j["rows"] if x["month"] == mo)


def rcs(j, mo=MONTH):
    return [e for e in j["entries"] if e["kind"] == "receipt" and e["month"] == mo]


# ---------------------------------------------------------------- the personal office (the finding of the device test)
check(Fr.get(B + O + "/settings").json().get("role") == "admin", "personal office: the person is its admin")
PI = invoice(Fr, 1000)
R1 = receipt(Fr, "Software Abo", "119.00", TODAY)
TX = bank(Fr, [(TODAY, "Kunde Eins GmbH", f"Rechnung {PI['number']}", "1.190,00"), (TODAY, "Software Beispiel GmbH", "Abo", "-119,00")])
check(Fr.post(B + f"{K}/tx/{TX['Rechnung ' + PI['number']]['id']}/match", json={"kind": "invoice", "id": PI["id"]}).ok, "personal office: money in -> invoice")
check(Fr.post(B + f"{K}/tx/{TX['Abo']['id']}/match", json={"kind": "receipt", "id": R1}).ok, "personal office: money out -> receipt")
j = cf(Fr)
m = month(j)
rc = rcs(j)
check(float(m["in"]["actual"]) == 1190 and float(m["out"]["actual"]) == 119, f"#2018: 1,190 in, 119 out {m}")
check(len(rc) == 1 and rc[0]["node_id"] == R1 and rc[0]["dir"] == "out" and rc[0]["state"] == "actual" and float(rc[0]["amount"]) == 119
      and rc[0]["date"] == TODAY and "Software Abo" in rc[0]["label"] and rc[0]["category"] == "Software", f"#2018: the receipt entry {rc}")
check(float(m.get("reserve") or 0) == 300 and float(m.get("free") or 0) == 771, f"#2018: reserve 300, freely available 1,190 - 119 - 300 = 771 {m}")
rn = rcs(cf(Fr, "net"))
check(len(rn) == 1 and float(rn[0]["amount"]) == 100, f"#2018: net basis = 100 {rn}")
eu = Fr.get(B + O + f"/books/euer?year={TODAY[:4]}").json()
check(float(eu["profit"]) == 900, f"the statement agrees: 1,000 - 100 = 900 {eu.get('profit')}")
kp = Fr.get(B + O + "/kpi").json()
km = next((x for x in kp.get("cashflow") or [] if x["month"] == MONTH), {})
check(float(km.get("out", {}).get("actual") or 0) == 119, f"#2018: the key figures carry the receipt too {km}")

# a booking of another amount than the receipt: the booking's amount counts
R2 = receipt(Fr, "Kamera Miete", "59.50", TODAY, cat="Equipment")
TX = bank(Fr, [(TODAY, "Verleih Beispiel", "Miete Kamera", "-60,00")])
check(Fr.post(B + f"{K}/tx/{TX['Miete Kamera']['id']}/match", json={"kind": "receipt", "id": R2}).ok, "a second receipt matched")
r2 = [e for e in rcs(cf(Fr)) if e["node_id"] == R2]
check(len(r2) == 1 and float(r2[0]["amount"]) == 60, f"#2018: matched with another amount = the booking's 60.00 {r2}")
r2n = [e for e in rcs(cf(Fr, "net")) if e["node_id"] == R2]
check(len(r2n) == 1 and abs(float(r2n[0]["amount"]) - 50.42) < 0.011, f"#2018: its net = 60 / 1.19 {r2n}")
# without a match: on its document date (as the statement); a later one is planned
R3 = receipt(Fr, "Porto", "23.80", TODAY, cat="Postage")
R4 = receipt(Fr, "Hosting", "11.90", NEXT + "-15", cat="Software")
j = cf(Fr)
r3, r4 = [e for e in rcs(j) if e["node_id"] == R3], [e for e in rcs(j, NEXT) if e["node_id"] == R4]
check(len(r3) == 1 and r3[0]["state"] == "actual" and float(r3[0]["amount"]) == 23.8, f"#2018: an unmatched receipt on its document date {r3}")
check(len(r4) == 1 and r4[0]["state"] == "plan", f"#2018: a later receipt is planned {r4}")
check(float(month(j)["out"]["actual"]) == round(119 + 60 + 23.8, 2), f"#2018: the month's money out {month(j)}")
ids = [e["node_id"] for e in j["entries"] if e["kind"] == "receipt"]
check(len(ids) == len(set(ids)) == 4, f"#2018: every receipt once {ids}")
# the undo of the match: the receipt stays on its document date, with its own amount
check(Fr.post(B + f"{K}/tx/{TX['Miete Kamera']['id']}/unmatch").ok, "unmatch the second receipt")
r2 = [e for e in rcs(cf(Fr)) if e["node_id"] == R2]
check(len(r2) == 1 and float(r2[0]["amount"]) == 59.5, f"#2018: after the undo its own amount on its document date {r2}")
# in the trash it goes
check(Fr.delete(B + f"/api/files/nodes/{R3}").ok, "a receipt into the trash")
check(not [e for e in rcs(cf(Fr)) if e["node_id"] == R3], "#2018: a receipt in the trash does not count")

# ---------------------------------------------------------------- an organisation (admin), encrypted at rest
OI = invoice(A, 1000)
RA = receipt(A, "Lizenz Schnitt", "119.00", TODAY)
TA = bank(A, [(TODAY, "Kunde Eins GmbH", f"Rechnung {OI['number']}", "1.190,00"), (TODAY, "Software Beispiel GmbH", "Lizenz", "-119,00")])
check(A.post(B + f"{K}/tx/{TA['Lizenz']['id']}/match", json={"kind": "receipt", "id": RA}).ok, "organisation: money out -> receipt")
check(A.post(B + f"{K}/tx/{TA['Rechnung ' + OI['number']]['id']}/match", json={"kind": "invoice", "id": OI["id"]}).ok, "organisation: money in -> invoice")
j = cf(A)
ra = rcs(j)
check(len(ra) == 1 and ra[0]["node_id"] == RA and float(ra[0]["amount"]) == 119, f"#2018 organisation: the receipt counts (booking decrypted) {ra}")
check(float(month(j).get("free") or 0) == 771, f"#2018 organisation: freely available 771 {month(j)}")
check(not {e["node_id"] for e in j["entries"] if e["kind"] == "receipt"} & {R1, R2, R4}, "organisation: no receipt of the personal office")
check(not {e["node_id"] for e in cf(Fr)["entries"] if e["kind"] == "receipt"} & {RA}, "personal office: no receipt of the organisation")
check(Bo.get(B + O + f"/cashflow?from={MONTH}").status_code == 403, "a member: no cash flow (403)")
check(not [e for e in cf(Ca)["entries"] if e["kind"] == "receipt"], "another organisation sees no receipt")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
