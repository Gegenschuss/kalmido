#!/usr/bin/env python3
"""2.97.1 API tests (#2224): the sender line above the address field of a quotation / invoice carries the company name,
"Company · Street · Postcode City", like the document templates. Own container (start.sh), invented companies only.
 - a draft quotation and a draft invoice: the print model's sender_line starts with the company name, then the address
 - a name that is already one of the free company lines is not doubled
 - finalising freezes the line (in the sender snapshot); a later change of the company leaves it alone
 - a document finalised before 2.97.1 (snapshot without the line) keeps the line it was printed with (no name)
 - the quotation's key data carry the client's customer number like the invoice (draft: live; finalised: frozen;
   finalised before 2.97.1: as printed then)
 - the PDF of a draft quotation is written (the shortening to the field width happens there)
 - a person without an organisation (the personal office) works the same
freelancer-matrix: office
usage: p2971_api_test.py <datadir>      (a fresh container; P2971_NOSTART=1: the container runs already)"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
TEST_IBAN = "DE02120300000000202051"
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
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


if os.environ.get("P2971_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,time", "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
O = "/api/office"
D = O + "/docs"
COMPANY = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hallo@nordlicht.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
           "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht GmbH"}, "lang": "de", "currency": "EUR",
                                     "company_fields": COMPANY, "payment_days": 14})
check(r.ok, "setup: office settings " + r.text[:200])
r = A.post(B + "/api/clients", json={"org_id": ORG, "name": "Foo AG", "street": "Unter den Linden 2", "zip": "10117", "city": "Berlin",
                                     "country": "DE", "customer_no": "K-1001"})
assert r.status_code == 201, r.text
CL = r.json()["id"]
LINE = "Studio Nordlicht GmbH · Hafenstraße 12 · 20457 Hamburg"


def sender_line(s, did):
    r = s.get(B + f"{D}/{did}/render")
    assert r.ok, r.text[:200]
    return r.json()["company"]["sender_line"]


# ---------------------------------------------------------------- drafts
r = A.post(B + D, json={"project_title": "Imagefilm", "client_id": CL, "items": [{"title": "Dreh", "qty": 1, "rate": 1000}]})
check(r.status_code == 201, "a quotation draft " + r.text[:160])
OFF = r.json()["id"]
check(sender_line(A, OFF) == LINE, f"quotation draft: the company name leads the sender line: {sender_line(A, OFF)!r}")


def meta(s, did):
    return {k: v for k, v in s.get(B + f"{D}/{did}/render").json()["meta"]}


check(meta(A, OFF).get("Kunden-Nr.") == "K-1001", f"quotation draft: the customer number in the key data: {meta(A, OFF)}")
r = A.get(B + f"{D}/{OFF}/pdf")
check(r.ok and r.content[:5] == b"%PDF-", "quotation draft: the PDF is written " + str(r.status_code))
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2030-05-01", "items": [{"title": "Beratung", "qty": 1, "rate": 100}]})
check(r.status_code == 201, "an invoice draft " + r.text[:160])
INV = r.json()["id"]
check(sender_line(A, INV) == LINE, f"invoice draft: the same sender line: {sender_line(A, INV)!r}")

# ---------------------------------------------------------------- finalising freezes the line
r = A.post(B + f"{D}/{OFF}/finalize")
check(r.ok and r.json()["locked"] is True, "quotation finalised " + r.text[:200])
check(sender_line(A, OFF) == LINE, "finalised quotation: the line with the name")
A.patch(B + f"/api/clients/{CL}", json={"customer_no": "K-2002"})
check(meta(A, OFF).get("Kunden-Nr.") == "K-1001", f"finalised quotation: the customer number frozen: {meta(A, OFF)}")
row = dbx("SELECT sender FROM office_docs WHERE id=?", (OFF,))[0]
snap = json.loads(row[0])
check(snap["company"].get("sender_line") == LINE, f"the line is part of the sender snapshot: {snap['company'].get('sender_line')!r}")
A.put(B + O + "/settings", json={"company_fields": dict(COMPANY, name="Nordlicht Neu GmbH", street="Kai 1")})
check(sender_line(A, OFF) == LINE, f"a later company change leaves the finalised quotation alone: {sender_line(A, OFF)!r}")
check(sender_line(A, INV) == "Nordlicht Neu GmbH · Kai 1 · 20457 Hamburg", f"the draft invoice follows the change: {sender_line(A, INV)!r}")

# ---------------------------------------------------------------- a document finalised before 2.97.1 keeps its line
del snap["company"]["sender_line"]
dbx("UPDATE office_docs SET sender=? WHERE id=?", (json.dumps(snap, ensure_ascii=False), OFF))
check(sender_line(A, OFF) == "Hafenstraße 12 · 20457 Hamburg", f"an older finalised document: printed as before: {sender_line(A, OFF)!r}")
check("Kunden-Nr." not in meta(A, OFF), "an older finalised quotation: no customer number added afterwards")

# ---------------------------------------------------------------- the name already in the free lines: not doubled
r = A.put(B + O + "/settings", json={"company_fields": {"name": "", "street": "", "zip": "", "city": ""}, "company": {"name": "Atelier Süd", "lines": ["Atelier Süd", "Weg 3", "80331 München"]}})
check(r.ok, "free company lines " + r.text[:160])
check(sender_line(A, INV) == "Atelier Süd · Weg 3 · 80331 München", f"the name in the lines is not doubled: {sender_line(A, INV)!r}")

# ---------------------------------------------------------------- a person without an organisation (the personal office)
FID, Fr = freelancer(B, A)
check(Fr.put(B + O + "/settings", json={"company_fields": {"name": "Frida Film", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg",
                                                             "country": "DE", "tax_number": "12/345/67890", "iban": TEST_IBAN}}).ok,
      "freelancer: company fields")
r = Fr.post(B + "/api/clients", json={"name": "Kunde Eins", "street": "Weg 1", "zip": "20095", "city": "Hamburg"})
assert r.status_code == 201, r.text
r = Fr.post(B + D, json={"project_title": "Shoot", "client_id": r.json()["id"], "items": [{"title": "Shoot", "qty": 1, "rate": 900}]})
check(r.status_code == 201, "freelancer: a quotation " + r.text[:160])
check(sender_line(Fr, r.json()["id"]) == "Frida Film · Hafenweg 1 · 20457 Hamburg", "freelancer: the name leads the sender line")
check(A.get(B + f"{D}/{r.json()['id']}/render").status_code in (403, 404), "tenant-matrix: office -- the organisation does not read the freelancer's quotation")

print(f"p2971_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
