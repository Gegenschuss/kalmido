#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.552.0 B (#4561, rest of #4318, audit #2425): the last small data loss spots of the office, the fields and the knowledge
base. Own container (start.sh through kt.fresh, mode workspaces). Invented names only (example.com); the person without an
organisation (tests/freelancer_fixture.py) does every step that exists for her.
freelancer-matrix: office, wiki, tasks
 - B21: a deleted credit card position goes into the office trash first (label without the sealed merchant / amount); the
   undo route and the office trash bring it back with its id; another office 404; a confirmed statement takes none back (409)
 - B19: a draft in the office trash whose client was deleted for good since comes back without the client, the answer says so
usage: p2552_b_dataloss_test.py <datadir>      (KMT_NOSTART=1: a running server)"""
import os
import sys
from datetime import date

import dbx as dbxm
import kt
from kt import B, DATA, check, done
from freelancer_fixture import freelancer

O = "/api/office"
K = O + "/cards"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # noqa: BLE001 - an UPDATE without rows to read
            return []
    finally:
        c.close()


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2552B")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, Fr = freelancer(B, A)
D = date.today().isoformat()

# ================================================================== B21 credit card positions: into the office trash first
card = Fr.post(B + K, json={"holder_id": FID, "last4": "4321"})
check(card.ok, f"B21: freelancer card {card.status_code} {card.text[:160]}")
st = Fr.post(B + f"{K}/{card.json()['id']}/statements", files={"file": ("stmt.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")}, data={"month": D[:7]})
check(st.ok, f"B21: a statement {st.status_code} {st.text[:160]}")
SID = st.json()["statement"]["id"]
keep = Fr.post(B + f"{K}/statements/{SID}/lines", json={"day": D, "merchant": "Objektivverleih Beispiel", "amount": "10.00"}).json()["line"]
LID = Fr.post(B + f"{K}/statements/{SID}/lines", json={"day": D, "merchant": "Tippfehler Beispiel", "amount": "2.50"}).json()["line"]["id"]


def del_line():
    r = Fr.delete(B + f"{K}/lines/{LID}")
    check(r.ok, f"B21: the position goes {r.status_code} {r.text[:160]}")
    return r.json().get("trash_id")


TID = del_line()
check(bool(TID), "B21: the answer of the delete names the office trash copy (trash_id)")
row = sql("SELECT kind, label FROM office_trash WHERE id=?", (TID or 0,))
check(row and row[0][0] == "cc_line", f"B21: the copy is in the office trash as kind cc_line: {row}")
check(row and "Tippfehler" not in row[0][1] and "2.50" not in row[0][1], f"B21: the label carries no sealed merchant / amount: {row}")
check(A.post(B + f"{K}/trash/{TID}/restore").status_code == 404, "B21: another office cannot restore the copy (404)")
r = Fr.post(B + f"{K}/trash/{TID}/restore")
check(r.ok and r.json()["line"]["id"] == LID and r.json()["line"]["merchant"] == "Tippfehler Beispiel" and r.json()["line"]["amount"] == "2.50",
      f"B21: the undo brings the position back with its id and values {r.status_code} {r.text[:200]}")
check(not sql("SELECT 1 FROM office_trash WHERE id=?", (TID,)), "B21: the copy left the trash")
lines = Fr.get(B + f"{K}/statements/{SID}").json()["lines"]
check(sorted(x["id"] for x in lines) == sorted([keep["id"], LID]), f"B21: the statement shows both positions again: {[x['id'] for x in lines]}")

TID = del_line()
items = Fr.get(B + O + "/trash").json()["items"]
check(any(x["id"] == TID and x["kind"] == "cc_line" for x in items), "B21: the office trash lists the position")
r = Fr.post(B + O + f"/trash/{TID}/restore")
check(r.ok and r.json().get("kind") == "cc_line" and sql("SELECT 1 FROM office_cc_lines WHERE id=?", (LID,)), f"B21: the office trash restores it {r.status_code} {r.text[:160]}")

TID = del_line()
check(Fr.patch(B + f"{K}/statements/{SID}", json={"total": "10.00"}).ok and Fr.post(B + f"{K}/statements/{SID}/confirm", json={}).ok, "B21: statement confirmed")
r = Fr.post(B + f"{K}/trash/{TID}/restore")
check(r.status_code == 409 and not sql("SELECT 1 FROM office_cc_lines WHERE id=?", (LID,)), f"B21: a confirmed statement takes no position back (409) {r.status_code}")
check(Fr.post(B + O + f"/trash/{TID}/restore").status_code == 409, "B21: the office trash refuses it as well (409)")
check(sql("SELECT 1 FROM office_trash WHERE id=?", (TID,)), "B21: the copy stays in the trash after the refusal")

# ================================================================== B19 a draft whose client is gone for good comes back without it
CID = Fr.post(B + "/api/clients", json={"name": "Weggangskunde GmbH", "email": "weg@example.com"}).json()["id"]
r = Fr.post(B + O + "/docs", json={"project_title": "Fruehling Beispiel", "client_id": CID})
check(r.status_code == 201, f"B19: a draft with a client {r.status_code} {r.text[:160]}")
DID = r.json()["id"]
check(sql("SELECT client_id FROM office_docs WHERE id=?", (DID,))[0][0] == CID, "B19: the draft names the client")
r = Fr.delete(B + O + f"/docs/{DID}")
TID = r.json().get("trash_id") if r.ok else None
check(bool(TID), f"B19: the draft is in the office trash {r.status_code} {r.text[:160]}")
check(Fr.delete(B + f"/api/clients/{CID}").ok, "B19: the client goes to the trash")
r = Fr.delete(B + f"/api/clients/{CID}/purge")
check(r.ok and not sql("SELECT 1 FROM clients WHERE id=?", (CID,)), f"B19: the client is deleted for good {r.status_code} {r.text[:160]}")
r = Fr.post(B + O + f"/trash/{TID}/restore")
j = r.json() if r.ok else {}
check(r.ok and j.get("id") == DID, f"B19: the draft comes back (was 409) {r.status_code} {r.text[:200]}")
check("client_id" in (j.get("gone") or []) and "without a client" in (j.get("note") or ""), f"B19: the answer says it came back without the client: {j}")
row = sql("SELECT client_id, project_title FROM office_docs WHERE id=?", (DID,))
check(row and row[0][0] is None, f"B19: the draft has no client now: {row}")
check(Fr.get(B + O + f"/docs/{DID}").ok, "B19: the draft opens")
check(not sql("SELECT 1 FROM office_trash WHERE id=?", (TID,)), "B19: the copy left the trash")

sys.exit(done("p2552_b_dataloss"))
