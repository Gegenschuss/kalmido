#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.577.0 D (#4708): the low findings of audit #2822, one block per finding. Own container (mode workspaces).
Invented names only (example.com).
freelancer-matrix: pim
 - (1) contacts deleted for good (bulk purge) only by the book's owner/admin: a person with 'edit' through a share may
   put contacts into the trash and take them out, but not delete them for good (403); the owner can
usage: p2577_d_audit_test.py <datadir>"""
import os
import sys

import kt
from kt import B, check
from freelancer_fixture import freelancer, login

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2577D")

A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": kt.PASSWORD, "email": "bob@example.com"})
check(r.ok, f"setup: bob {r.status_code} {r.text[:120]}")
BOB = r.json()["id"]
Bo = login(B, "bob")
from freelancer_fixture import FEATURES
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
FID, Fr = freelancer(B, A)


def gone(cid):
    rows = kt.dbx("SELECT deleted_at FROM contacts WHERE id=?", (cid,))
    return not rows


# ================================================================== (1) purge only for the owner
r = Fr.post(B + "/api/books", json={"name": "Frida's contacts", "org_id": None})
check(r.status_code == 201, f"(1) setup: Frida's private book {r.status_code} {r.text[:120]}")
BK = r.json()["id"]
CIDS = []
for n in ("Anna Example", "Ben Example"):
    r = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": n, "emails": [{"value": n.split()[0].lower() + "@example.com"}]})
    check(r.status_code == 201, f"(1) setup: contact {n}")
    CIDS.append(r.json()["id"] if r.ok else 0)
r = Fr.put(B + f"/api/books/{BK}/members", json={"user_id": BOB, "role": "edit"})
check(r.ok, f"(1) setup: Frida shares the book with Bob (edit) {r.status_code} {r.text[:120]}")
r = Bo.post(B + "/api/contacts/bulk", json={"action": "delete", "ids": CIDS})
check(r.ok, f"(1) Bob (edit) puts both into the trash {r.status_code} {r.text[:120]}")
r = Bo.post(B + "/api/contacts/bulk", json={"action": "purge", "ids": CIDS})
check(r.status_code == 403 and not any(gone(x) for x in CIDS), f"(1) Bob (edit) cannot delete them for good: 403 {r.status_code}")
r = Bo.post(B + "/api/contacts/bulk", json={"action": "undelete", "ids": [CIDS[1]]})
check(r.ok, f"(1) Bob (edit) still takes one out of the trash {r.status_code}")
r = Fr.post(B + "/api/contacts/bulk", json={"action": "purge", "ids": [CIDS[0]]})
check(r.ok and gone(CIDS[0]), f"(1) the owner (person without an organisation) deletes for good {r.status_code} {r.text[:120]}")

# @@NEXT@@

sys.exit(kt.done("p2577_d_audit"))
