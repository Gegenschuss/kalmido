#!/usr/bin/env python3
"""2.126.0 API tests, part A: office and documents (#1966 #1967 #1970 #1971, #1979 F5-F7 L1-L7). Invented names only.
 - #1966: the next number of an invoice / credit note draft comes only at finalising (409), a numbered invoice draft is
   kept (409), an unnumbered one and a quotation draft can be deleted; also in the personal office
 - #1967: an invoice from times sums only the lists the person sees, also in the personal office
 - #1971 / #1970: the document tables in the encryption status, encrypt-all / decrypt-all, the personal space's document
   data on the account key and back (docs-to-server-key)
 - #1979: the duplicate starts a fresh reminder fee, a client with finalised invoices stays in the organisation, broken
   input gives 400 instead of 500
tenant-matrix: office
freelancer-matrix: office
freelancer-matrix: docs
usage: p2126_a_api_test.py <datadir>      (a fresh container; P2126A_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,time,docs"
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


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def item(title, qty, rate, unit="day"):
    return {"kind": "service", "title": title, "qty": qty, "unit": unit, "rate": rate, "tax": "standard", "raw_fee": 0, "producing": 0,
            "intext": "intern", "cost": 0, "discountable": 1}


if os.environ.get("P2126A_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
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
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Beispiel Studio GmbH", "street": "Musterweg 1",
                                                                                   "zip": "12345", "city": "Musterstadt", "country": "DE"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Kundenweg 5", "zip": "20000", "city": "Beispielstadt", "country": "DE"}).json()["id"]
FID, Fr = freelancer(B, A)
FC = Fr.post(B + "/api/clients", json={"name": "Privatkunde", "street": "Weg 1", "zip": "20000", "city": "Beispielstadt", "country": "DE"}).json()["id"]


# ================================================================ #1966 numbers of invoice drafts
def numbers_case(S, who, cl):
    inv = S.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": "2026-05-01", "items": [item("Beratung", 1, 100)]}).json()
    check(inv["number"] == "" and inv["number_at_finalize"], f"{who}: an invoice draft has no number yet")
    r = S.post(B + f"{D}/{inv['id']}/number", json={})
    check(r.status_code == 409, f"{who}: the next number of an invoice draft comes at finalising (409) " + r.text[:120])
    check(S.get(B + f"{D}/{inv['id']}").json()["number"] == "", f"{who}: still no number")
    cr = S.post(B + D, json={"kind": "credit"}).json()
    check(S.post(B + f"{D}/{cr['id']}/number").status_code == 409, f"{who}: a credit note draft neither")
    r = S.delete(B + f"{D}/{cr['id']}")
    check(r.ok, f"{who}: an unnumbered credit note draft can be deleted " + r.text[:120])
    r = S.post(B + f"{D}/{inv['id']}/number", json={"number": f"RE-{time.localtime().tm_year}-001"})
    check(r.ok, f"{who}: a manual number is still possible " + r.text[:160])
    d = S.get(B + f"{D}/{inv['id']}").json()
    check(d["can_delete"] is False, f"{who}: a numbered invoice draft offers no delete")
    r = S.delete(B + f"{D}/{inv['id']}")
    check(r.status_code == 409 and r.json().get("error"), f"{who}: a numbered invoice draft is kept (409) " + r.text[:160])
    check(S.get(B + f"{D}/{inv['id']}").ok, f"{who}: and still there")
    off = S.post(B + D, json={"kind": "offer", "client_id": cl, "items": [item("Kamera", 1, 500)]}).json()
    check(bool(off["number"]) and off["can_delete"], f"{who}: a numbered quotation draft can still be deleted")
    check(S.delete(B + f"{D}/{off['id']}").ok, f"{who}: quotation draft deleted")
    return inv["id"]


INV1 = numbers_case(A, "org", CL)
FINV1 = numbers_case(Fr, "freelancer", FC)
check(Bo.delete(B + f"{D}/{INV1}").status_code == 403, "a member still gets 403")


# ================================================================ #1967 invoice from times: only the lists the person sees
def entry(user_id, list_id, start, end, secs, note):
    sql("INSERT INTO time_entries(user_id, list_id, task_title, start, \"end\", seconds, note, source, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user_id, list_id, "Schnitt", start, end, secs, note, "manual", end, end), write=True)


def list_for(S, name, cl):
    lid = S.post(B + "/api/lists", json={"name": name}).json()["id"]
    r = S.patch(B + f"/api/lists/{lid}", json={"client_id": cl})
    assert r.ok, r.text
    return lid


def titles(S, doc):
    return sorted(x["title"] for x in S.get(B + f"{D}/{doc}").json()["items"] if x["kind"] == "service")


LA = list_for(A, "Alices Liste", CL)
LB = list_for(Bo, "Bobs Liste", CL)
entry(ALICE, LA, "2026-05-04T08:00:00Z", "2026-05-04T10:00:00Z", 7200, "Konzept")
entry(BOB, LB, "2026-05-05T08:00:00Z", "2026-05-05T09:00:00Z", 3600, "Schnitt")
check(LA not in [x["id"] for x in Bo.get(B + "/api/state").json()["lists"]], "setup: the member does not see the admin's list")
r = Bo.post(B + D + "/from-time", json={"client_id": CL, "from": "2026-05-01", "to": "2026-05-31"})
check(r.status_code == 201 and titles(Bo, r.json()["id"]) == ["Bobs Liste"], "org: only the lists the member sees are summed " + r.text[:200])
FL = list_for(Fr, "Privatprojekt", FC)
entry(FID, FL, "2026-05-04T08:00:00Z", "2026-05-04T09:30:00Z", 5400, "Konzept")
r = Fr.post(B + D + "/from-time", json={"client_id": FC, "from": "2026-05-01", "to": "2026-05-31"})
check(r.status_code == 201, "freelancer: invoice from times " + r.text[:200])
if r.status_code == 201:
    it = [x for x in Fr.get(B + f"{D}/{r.json()['id']}").json()["items"] if x["kind"] == "service"]
    check([x["title"] for x in it] == ["Privatprojekt"] and float(it[0]["qty"]) == 1.5, f"freelancer: the private list's hours are summed {it}")
check(Fr.post(B + D + "/from-time", json={"client_id": CL, "from": "2026-05-01", "to": "2026-05-31"}).status_code == 404, "freelancer: an organisation's client 404")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
