#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.577.0 part B: the office. Invented names only.
 - #3964: a person who lost "Quotes & invoices" (edit) between her change of a client and its undo / redo: the undo puts the
   other fields back but leaves the invoicing fields (VAT ID, customer number, payment terms ...) as they are now, like the
   save (team/clients.py cl_bill_strip) would
 - #4638: under "All workspaces" an office request names its area in the header X-Kalmido-Office-Space (office/model.py
   office_space): only "private" or one of the person's own organisations, only while the setting is "All"; another value =
   400, a chosen workspace outranks the header; a write lands in the named area
 - freelancer-matrix: office (a person without an organisation: "private" works, a foreign organisation is refused)
usage: p2577_b_office_test.py <datadir>"""
import os
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
O, R = "/api/office", "/api/office/rights"
FEAT = "cal,comments,collab,clients,office,docs,files,contacts"
HS = "X-Kalmido-Office-Space"

if not os.environ.get("P2577B_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ME = A.get(B + "/api/state").json()["me"]
ORG = ME["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": "bob", "display_name": "Bob",
                                   "password": "password123", "email": "bob@example.com"})
check(r.ok, "setup: bob as member " + r.text[:200])
BOB = r.json().get("id")
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT, "workspace": f"org:{ORG}"})
check(A.put(B + O + "/settings", json={"company_fields": {"name": "Studio Example GmbH", "country": "de"}, "lang": "en", "currency": "EUR"}).ok,
      "setup: office settings")
BILL = {"city": "Berlin", "country": "DE", "vat_id": "DE123456789", "customer_no": "K-100", "payment_terms_days": 14}
r = A.post(B + "/api/clients", json={"name": "Example Client AG", "org_id": ORG, "note": "First", **BILL})
check(r.status_code == 201, "setup: the organisation's client " + r.text[:200])
CL = r.json().get("id")


def cli():
    r = A.get(B + f"/api/clients/{CL}")
    j = r.json() if r.ok else {}
    return j.get("note"), j.get("billing", {}).get("vat_id"), j.get("billing", {}).get("payment_terms_days")


# ---------------------------------------------------------------- #3964: undo after losing the quotes area
TOK = os.urandom(12).hex()
r = Bo.patch(B + f"/api/clients/{CL}", json={"note": "Second", "vat_id": "DE987654321", "payment_terms_days": 30}, headers={"X-Kalmido-Undo": TOK})
check(r.ok and cli() == ("Second", "DE987654321", 30), f"bob (no group yet) changes note and invoicing fields with an undo session {cli()}")
check(A.put(B + f"{R}/people/{BOB}", json={"groups": ["tpl:staff"]}).ok, "alice puts bob into Staff (no quotes area)")
r = Bo.post(B + O + f"/undo/client/{CL}", json={"sess": TOK, "op": "undo"})
check(r.ok and cli() == ("First", "DE987654321", 30), f"undo: the note goes back, the invoicing fields stay ({r.status_code} {cli()} {r.text[:160]})")
r = Bo.post(B + O + f"/undo/client/{CL}", json={"sess": TOK, "op": "redo"})
check(r.ok and cli() == ("Second", "DE987654321", 30), f"redo: the note again, the invoicing fields untouched ({r.status_code} {cli()})")
check(A.put(B + f"{R}/people/{BOB}", json={"groups": ["tpl:legacy"]}).ok, "alice gives bob his previous access again (tpl:legacy)")
r = Bo.post(B + O + f"/undo/client/{CL}", json={"sess": TOK, "op": "undo"})
check(r.ok and cli() == ("First", "DE123456789", 14), f"with the right back: the undo puts the invoicing fields back too ({r.status_code} {cli()})")

# ---------------------------------------------------------------- #4638: the office's area per request under "All"
r = A.post(B + "/api/admin/orgs", json={"name": "Bravo", "admin_id": ME["id"]})
check(r.ok, "setup: a second organisation " + r.text[:200])
ORG2 = r.json().get("id")
A.patch(B + "/api/settings", json={"workspace": "all"})


def where(s, sp=None):
    r = s.get(B + O + "/settings", headers={HS: sp} if sp is not None else {})
    j = r.json() if r.ok else {}
    return r.status_code, j.get("org_id"), bool(j.get("personal"))


st = where(A)
check(st[0] == 400, f"All, two organisations, no header: as before 400 (choose a workspace) {st}")
check(where(A, f"org:{ORG}")[:2] == (200, ORG), f"header org:{ORG}: its office {where(A, f'org:{ORG}')}")
check(where(A, f"org:{ORG2}")[:2] == (200, ORG2), f"header org:{ORG2}: its office {where(A, f'org:{ORG2}')}")
st = where(A, "private")
check(st[0] == 200 and st[2] and st[1] not in (ORG, ORG2), f"header private: the personal office {st}")
check(where(A, "org:999999")[0] == 400, f"header of a foreign organisation: 400 {where(A, 'org:999999')}")
check(where(A, "all")[0] == 400 and where(A, "org:x")[0] == 400, "header with another value: 400")
check(where(Bo, f"org:{ORG2}")[:2] == (200, ORG), f"bob (workspace chosen) names Bravo, not his: the setting rules {where(Bo, f'org:{ORG2}')}")
Bo.patch(B + "/api/settings", json={"workspace": "all"})
check(where(Bo)[:2] == (200, ORG), f"bob under All with one organisation: as before its office {where(Bo)}")
check(where(Bo, f"org:{ORG2}")[0] == 400, f"bob under All names Bravo (no member): 400, never another office {where(Bo, f'org:{ORG2}')}")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(where(A, f"org:{ORG2}")[:2] == (200, ORG), f"alice with a workspace chosen: the header does nothing {where(A, f'org:{ORG2}')}")
A.patch(B + "/api/settings", json={"workspace": "all"})
r = A.post(B + O + "/services", json={"name_de": "Beratung Bravo"}, headers={HS: f"org:{ORG2}"})
check(r.status_code == 201, f"a write with header org:{ORG2} ({r.status_code} {r.text[:160]})")


def svc(sp):
    r = A.get(B + O + "/services", headers={HS: sp})
    return [x.get("name_de") for x in r.json().get("items", [])] if r.ok else [r.status_code]


check("Beratung Bravo" in svc(f"org:{ORG2}") and "Beratung Bravo" not in svc(f"org:{ORG}") and "Beratung Bravo" not in svc("private"),
      f"the service landed in Bravo only {svc(f'org:{ORG2}')} {svc(f'org:{ORG}')}")

# ---------------------------------------------------------------- freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"workspace": "all"})
st = where(Fr)
check(st[0] == 200 and st[2], f"freelancer: her own office as before {st}")
st = where(Fr, "private")
check(st[0] == 200 and st[2], f"freelancer: header private = her own office {st}")
check(where(Fr, f"org:{ORG}")[0] == 400, f"freelancer: an organisation she is not in: 400 {where(Fr, f'org:{ORG}')}")

print(f"p2577_b_office: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
