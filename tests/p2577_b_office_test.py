#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.577.0 part B: the office. Invented names only.
 - #3964: a person who lost "Quotes & invoices" (edit) between her change of a client and its undo / redo: the undo puts the
   other fields back but leaves the invoicing fields (VAT ID, customer number, payment terms ...) as they are now, like the
   save (team/clients.py cl_bill_strip) would
usage: p2577_b_office_test.py <datadir>"""
import os
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
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
check(A.put(B + f"{R}/people/{BOB}", json={"groups": []}).ok, "alice takes bob out of the groups again")
r = Bo.post(B + O + f"/undo/client/{CL}", json={"sess": TOK, "op": "undo"})
check(r.ok and cli() == ("First", "DE123456789", 14), f"with the right back: the undo puts the invoicing fields back too ({r.status_code} {cli()})")

print(f"p2577_b_office: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
