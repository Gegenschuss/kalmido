#!/usr/bin/env python3
"""2.121.0 API tests, part D (lead): receipt categories with an account of the chart SKR03 / SKR04 (#2093). Own container
(start.sh, org encryption on). Invented companies, people and figures only.
tenant-matrix: office
freelancer-matrix: office
 - GET /api/office/books answers accounts {chart, own, categories {name: {account, default, own}}}: the default account per
   category of the DATEV export (keywords), an own account set through the office settings (datev_extf.cat_accounts), the
   chart switch SKR03 -> SKR04 changes the defaults; the EUeR lines of receipt categories carry the account; a member
   without the office admin role 403, another organisation never sees ours; a person without organisation (personal office)
usage: p2121_d_api_test.py <datadir>      (P2121D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
D = O + "/docs"
RB = O + "/receipts"


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t, "X-Requested-With": "kalmido"})
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


def upload(s, name, text, ws):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf(text), "application/pdf")})
    assert r.ok, r.text
    j = r.json()
    nid = (j.get("ids") or [x["id"] for x in j.get("docs") or j.get("items") or []])[0]
    for _ in range(60):  # the recognition must be over, else it may overwrite what the test sets
        if s.get(B + f"/api/docs/{nid}").json().get("state") not in ("wait", "run"):
            break
        time.sleep(0.5)
    return nid


def receipt(s, name, ws, amount, vat, cat, day="2026-03-05"):
    """A document of the documents space with amount, date, category and VAT rate = a receipt of the office."""
    nid = upload(s, name, "Receipt " + name, ws)
    r = s.patch(B + f"/api/docs/{nid}", json={"amount": amount, "date": day, "currency": "EUR"})
    assert r.ok, r.text
    r = s.put(B + f"/api/docs/{nid}/receipt", json={"project_id": None, "category": cat, "vat_pct": vat, "keep": True})
    assert r.ok, r.text
    return nid


if os.environ.get("P2121D_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
WS = f"org:{ORG}"
A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Beispiel Studio GmbH", "street": "Musterweg 1",
                                                                                   "zip": "12345", "city": "Musterstadt", "country": "DE"}})
Ca.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Fremd GmbH", "street": "Weg 2", "zip": "12345", "city": "Stadt", "country": "DE"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH"}).json()["id"]

# ================================================================ #2093 accounts per category
R1 = receipt(A, "Hosting.pdf", WS, "119.00", "19", "Software", "2026-03-05")
R2 = receipt(A, "Papier.pdf", WS, "23.80", "19", "Bürobedarf", "2026-03-06")
R3 = receipt(A, "Sonstiges.pdf", WS, "10.00", "19", "Allerlei", "2026-03-07")
j = A.get(B + O + "/books?year=2026").json()
acc = j.get("accounts") or {}
cats = acc.get("categories") or {}
check(acc.get("chart") == "SKR03" and cats.get("Software", {}).get("account") == "4964" and cats["Software"]["own"] is False,
      f"#2093: default account of Software in SKR03 ({acc})")
check(cats.get("Bürobedarf", {}).get("account") == "4930" and cats.get("Allerlei", {}).get("account") == "4900", f"#2093: office supplies / other ({cats})")
check(j["categories"] == sorted(j["categories"], key=str.lower) and "Software" in j["categories"], "#2093: the category list stays as it was")
r = A.put(B + O + "/settings", json={"datev_extf": {"cat_accounts": {"allerlei": "4980"}}})
check(r.ok, f"#2093: own account through the office settings ({r.text[:160]})")
cats = A.get(B + O + "/books?year=2026").json()["accounts"]["categories"]
check(cats["Allerlei"]["account"] == "4980" and cats["Allerlei"]["own"] is True and cats["Allerlei"]["default"] == "4900", f"#2093: own account wins ({cats['Allerlei']})")
e = A.get(B + O + "/books/euer?year=2026").json()
lines = {x["label"]: x.get("account") for x in e["expenses"]}
check(lines.get("Software") == "4964" and lines.get("Allerlei") == "4980", f"#2093: EUeR lines carry the account ({lines})")
r = A.put(B + O + "/settings", json={"datev_extf": {"chart": "SKR04"}})
acc = A.get(B + O + "/books?year=2026").json()["accounts"]
check(r.ok and acc["chart"] == "SKR04" and acc["categories"]["Software"]["account"] == "6837" and acc["categories"]["Allerlei"]["account"] == "4980",
      f"#2093: SKR04 defaults, the own account stays ({acc})")
r = A.put(B + O + "/settings", json={"datev_extf": {"cat_accounts": {}}})
check(r.ok and A.get(B + O + "/books?year=2026").json()["accounts"]["categories"]["Allerlei"]["account"] == "6300", "#2093: own account removed = default (undo)")
r = A.put(B + O + "/settings", json={"datev_extf": {"cat_accounts": {"software": "12ab"}}})
check(r.status_code == 400, f"#2093: an account is digits only ({r.status_code})")
check(Bo.get(B + O + "/books?year=2026").status_code == 403, "#2093: a member without the office admin role 403")
check(Bo.put(B + O + "/settings", json={"datev_extf": {"cat_accounts": {"software": "4000"}}}).status_code == 403, "#2093: a member cannot set accounts")
oc = Ca.get(B + O + "/books?year=2026").json().get("accounts") or {}
check("Software" not in (oc.get("categories") or {}), "#2093: another organisation never sees our categories")

# ================================================================ person without organisation
FID, Fr = freelancer(B, A)
Fr.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Frida Film", "street": "Weg 3", "zip": "12345", "city": "Stadt", "country": "DE"}})
receipt(Fr, "Abo.pdf", "private", "11.90", "19", "Software", "2026-03-05")
r = Fr.put(B + O + "/settings", json={"datev_extf": {"cat_accounts": {"software": "4806"}}})
cats = Fr.get(B + O + "/books?year=2026").json()["accounts"]["categories"]
check(r.ok and cats["Software"]["account"] == "4806" and cats["Software"]["own"], f"freelancer: own account in the personal office ({cats})")
check(A.get(B + O + "/books?year=2026").json()["accounts"]["categories"]["Software"]["own"] is False, "freelancer: her accounts stay hers")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
