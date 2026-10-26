#!/usr/bin/env python3
"""2.250.0 A (#2992) API test: the web search (GET /api/search) also finds the office -- clients (name, contact person)
and quotations / invoices (number, client, project title) -- in the key "office", visible exactly like the office lists.
Own container (start.sh). Invented people, companies and figures only.
 (a) the org admin finds the quotation by its number, the client by name and contact person, the invoice by the client
 (b) a member without a group ("Previous access", quotes & invoices allowed) finds the same; a member in the group
     "Staff" (no quotes & invoices) gets no office hits
 (c) the admin of another organisation finds nothing of Alpha; the Alpha admin in the workspace "Private" neither
 (d) the office module off: no office hits (the task hits stay)
 (e) a freelancer without an organisation finds the own client and quotation, nothing of Alpha
 (f) the agents' API (GET /api/v1/search?fulltext=1) has no office hits; a key of the recipient JSON is no hit
 (g) a search of a person who never opened the office makes no personal office (a read writes nothing)
usage: p2250_a_officesearch_test.py <datadir>      (KMT_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)
freelancer-matrix: office  tenant-matrix: office"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, dbx, sess  # noqa: E402
FEAT = "cal,comments,collab,office,clients,time,docs,files"
O = "/api/office"


def office(s, q):
    r = s.get(B + "/api/search", params={"q": q})
    check(r.status_code == 200, f"search {q}: {r.status_code} {r.text[:160]}")
    return r.json().get("office", []) if r.ok else []


def has(hits, kind, iid):
    return any(h.get("kind") == kind and h.get("id") == iid for h in hits)


if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ids, S = {}, {}
for u, n in (("bob", "Bob Member"), ("sam", "Sam Staff"), ("carl", "Carl Beta")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
    S[u] = sess(u)
for u in ("bob", "sam"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ids["carl"]}).json()["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
for u, s in S.items():
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{BETA if u == 'carl' else ORG}"})
Bo, Sa, Ca = S["bob"], S["sam"], S["carl"]

# ---------------------------------------------------------------- Alpha's office (the admin)
C1 = A.post(B + "/api/clients", json={"name": "Weingut Sonnenhang", "contact": "Petra Probe", "org_id": ORG, "country": "DE"}).json()["id"]
r = A.post(B + O + "/docs", json={"kind": "offer", "client_id": C1, "project_title": "Hoffest Lese",
                                  "items": [{"title": "Konzept", "qty": 1, "rate": 800}]})
assert r.status_code == 201, r.text
OFF, NUM = r.json()["id"], r.json().get("number") or ""
check(len(NUM) >= 3, f"setup: the quotation has a number at once {NUM!r}")
r = A.post(B + O + "/docs", json={"kind": "invoice", "client_id": C1, "items": [{"title": "Schnitt", "qty": 1, "rate": 1000}]})
assert r.status_code == 201, r.text
INV = r.json()["id"]
# Beta's own client of the same name part (the other organisation's admin)
CB = Ca.post(B + "/api/clients", json={"name": "Weingut Talblick", "org_id": BETA}).json().get("id")
check(bool(CB), "setup: a client of Beta")

# ---------------------------------------------------------------- (a) the admin
h = office(A, NUM)
check(has(h, "offer", OFF), f"(a) admin: the quotation by its number {NUM} {h}")
hit = next((x for x in h if x.get("id") == OFF), {})
check(hit.get("go") == f"office/offers/{OFF}" and "Weingut Sonnenhang" in (hit.get("sub") or ""), f"(a) the hit opens the document, sub names the client {hit}")
h = office(A, "Sonnenhang")
check(has(h, "client", C1) and has(h, "offer", OFF) and has(h, "invoice", INV), f"(a) admin: client + its quotation + invoice by the client {h}")
check(next((x for x in h if x.get("kind") == "client"), {}).get("go") == f"client/{C1}", "(a) the client hit opens the client page")
check(not any(x.get("id") == CB and x.get("kind") == "client" for x in h), "(a) admin: no client of Beta")
check(has(office(A, "petra probe"), "client", C1), "(a) admin: the client by the contact person (any case)")
check(has(office(A, "Hoffest"), "offer", OFF), "(a) admin: the quotation by the project title")
check(len(office(A, "Weingut")) <= 10, "(a) a short list (at most 5 per kind)")

# ---------------------------------------------------------------- (b) members
check(has(office(Bo, NUM), "offer", OFF) and has(office(Bo, "Sonnenhang"), "client", C1), "(b) a member with previous access: quotation + client")
r = A.put(B + f"{O}/rights/people/{ids['sam']}", json={"groups": ["tpl:staff"]})
check(r.ok, "(b) setup: sam -> staff " + r.text[:160])
check(Sa.get(B + O + "/docs").status_code == 403, "(b) staff: the quotation list itself 403")
check(office(Sa, NUM) == [] and office(Sa, "Sonnenhang") == [], "(b) staff: no office hits")

# ---------------------------------------------------------------- (c) another organisation / the private workspace
check(office(Ca, NUM) == [] and not has(office(Ca, "Weingut"), "client", C1), "(c) Beta's admin: nothing of Alpha")
check(has(office(Ca, "Talblick"), "client", CB), "(c) Beta's admin finds the own client")
A.patch(B + "/api/settings", json={"workspace": "private"})
check(office(A, NUM) == [] and office(A, "Sonnenhang") == [], "(c) the Alpha admin in the workspace Private: nothing of Alpha")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})

# ---------------------------------------------------------------- (d) the office module off
Bo.patch(B + "/api/settings", json={"features": "cal,comments,collab,clients,time"})
r = Bo.get(B + "/api/search", params={"q": "Sonnenhang"})
check(r.ok and "office" not in r.json() and "hits" in r.json(), f"(d) office off: no key office, the task hits stay {r.text[:160]}")
Bo.patch(B + "/api/settings", json={"features": FEAT})

# ---------------------------------------------------------------- (e) a freelancer without an organisation
FID, Fr = freelancer(B, A)
CF = Fr.post(B + "/api/clients", json={"name": "Weingut Eigenhof", "contact": "Frieda Feld"}).json().get("id")
r = Fr.post(B + O + "/docs", json={"kind": "offer", "client_id": CF, "project_title": "Hofladen Film", "items": [{"title": "Dreh", "qty": 1, "rate": 500}]})
check(r.status_code == 201, "(e) setup: the freelancer's quotation " + r.text[:160])
FOFF = r.json().get("id") if r.ok else None
h = office(Fr, "Weingut")
check(has(h, "client", CF) and has(h, "offer", FOFF), f"freelancer-matrix: office -- the own client + quotation {h}")
hn = office(Fr, NUM)  # the own office counts from 1 too: the same number may be the freelancer's own quotation
check(not has(h, "client", C1) and not has(h, "offer", OFF) and not has(hn, "offer", OFF) and all(x.get("id") == FOFF for x in hn),
      f"tenant-matrix: office -- the freelancer finds nothing of Alpha {hn}")
check(not has(office(A, "Eigenhof"), "client", CF), "tenant-matrix: office -- Alpha's admin does not find the freelancer's client")

# ---------------------------------------------------------------- (f) the agents' API, the recipient JSON
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "claude", "display_name": "Claude"})
check(r.ok, "(f) setup: an agent " + r.text[:160])
if r.ok:
    AH = {"Authorization": "Bearer " + r.json()["token"]}
    A.patch(B + f"/api/admin/agents/{r.json()['id']}", json={"org_id": ORG})
    r = requests.get(B + "/api/v1/search", params={"q": "Sonnenhang", "fulltext": "1"}, headers=AH)
    check(r.status_code in (200, 403) and (r.status_code == 403 or "office" not in r.json()), f"(f) agents' API: no office hits {r.status_code} {r.text[:160]}")
    r = requests.get(B + "/api/search", params={"q": "Sonnenhang"}, headers=AH)
    check(r.status_code != 200 or "office" not in r.json(), f"(f) an agent token on the web search: no office hits {r.status_code}")
check(not has(office(A, "name"), "offer", OFF), "(f) a key of the recipient JSON (\"name\") is no hit")

# ---------------------------------------------------------------- (g) a read makes no personal office (review 2.250.0)
GID, Gr = freelancer(B, A, name="greta", features=FEAT)
check(office(Gr, "Weingut") == [], "(g) no office yet: no office hits")
check(dbx("SELECT count(*) FROM orgs WHERE personal_of=?", (GID,))[0][0] == 0, "(g) the search made no personal office")

print(f"\np2250_a_officesearch: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
