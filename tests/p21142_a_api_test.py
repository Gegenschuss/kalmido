#!/usr/bin/env python3
"""2.114.2 API tests, part A (#2263): a finalised quotation that never left the house (decision of 2026-10-19).
Own container (start.sh), invented companies and people only (@example.com / .example).
 - the organisation's admin deletes a finalised quotation that is still a draft, was never sent and never answered by the
   client (200); the office log keeps a delete entry with the number (locked: true), so the gap stays traceable
 - the admin takes such a quotation back to a draft (POST .../unlock): editable again, the number stays and is kept when
   it is finalised again; the history has an "unlock" entry with the number
 - sent / accepted / declined / mailed (sent_at or a logged send) / signed by the customer / an invoice made from it: 409
   for both; a finalised invoice and credit note: 409 for both
 - a member: 403 (can_delete / can_unlock false); another organisation: 404 (tenant-matrix: office)
 - references: an open approval link goes with the quotation, a pipeline deal loses its offer_id (no dead link), the
   version chain (version_of) of a deleted first quotation stays readable
 - a person without an organisation (freelancer-matrix: office) does the same in the personal office
 - 2.417.0 C (#2604, #2574): the test phase of 2.144.8 (#2573) is gone - sent / accepted / declined / mailed / signed
   quotations stay again (delete and "undo finalising" 409, no delete_sent); the delete rule equals the unlock rule
usage: p21142_a_api_test.py <datadir>      (a fresh container; P21142A_NOSTART=1 = the server already runs)"""
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
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
TEST_IBAN = "DE02120300000000202051"


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


if not os.environ.get("P21142A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,clients,office"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
BOB = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123",
                                     "email": "bob@example.com"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123",
                                       "email": "carol@example.com", "orgs": []}).json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": CAROL})
assert r.status_code == 201, r.text
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{r.json()['id']}"})
D = "/api/office/docs"
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": TEST_IBAN,
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
CLIENT = {"name": "Example Client AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
          "email_invoice": "billing@client.example", "payment_terms_days": 14}


def setup_office(s):
    r = s.put(B + "/api/office/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})
    check(r.ok, "office settings " + r.text[:200])
    r = s.post(B + "/api/clients", json=CLIENT)
    check(r.status_code in (200, 201), "a client " + r.text[:200])
    return r.json().get("id")


def offer(s, cl, title="Image film", final=True):
    r = s.post(B + D, json={"project_title": title, "client_id": cl, "service_from": "2030-02-01", "service_to": "2030-02-28"})
    check(r.status_code == 201, "a quotation " + r.text[:200])
    did = r.json()["id"]
    check(s.put(B + f"{D}/{did}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 900}]}).ok, "positions")
    if final:
        r = s.post(B + f"{D}/{did}/finalize")
        check(r.ok and r.json()["locked"] is True, "finalised " + r.text[:200])
    return did


def log(s, did=None, action=None):
    rows = s.get(B + "/api/office/log?limit=200").json().get("log") or []
    return [x for x in rows if (did is None or x.get("doc_id") == did) and (action is None or x.get("action") == action)]


CL = setup_office(A)

# ================================================================== delete: finalised, never sent (org admin)
# tenant-matrix: office -- the new unlock route and the delete of a finalised quotation across the boundary
Q1 = offer(A, CL)
q = A.get(B + f"{D}/{Q1}").json()
NUM1 = q["number"]
check(q["can_delete"] is True and q["can_unlock"] is True, f"finalised, never sent: the admin may delete / unlock {q.get('can_delete')} {q.get('can_unlock')}")
b = Bo.get(B + f"{D}/{Q1}").json()
check(b["can_delete"] is False and b["can_unlock"] is False, "a member: no delete / unlock")
row = next((x for x in A.get(B + f"{D}?kind=offer").json()["docs"] if x["id"] == Q1), {})
check(row.get("can_delete") is True and row.get("can_unlock") is True, f"the list row says so too {row}")
row = next((x for x in Bo.get(B + f"{D}?kind=offer").json()["docs"] if x["id"] == Q1), {})
check(not row.get("can_delete") and not row.get("can_unlock"), f"the member's list row does not {row}")
check(Bo.delete(B + f"{D}/{Q1}").status_code == 403, "a member: delete 403")
check(Bo.post(B + f"{D}/{Q1}/unlock").status_code == 403, "a member: unlock 403")
check(Ca.delete(B + f"{D}/{Q1}").status_code in (400, 403, 404), "another organisation: delete refused")
check(Ca.post(B + f"{D}/{Q1}/unlock").status_code in (400, 403, 404), "another organisation: unlock refused")
# an open approval link (normally only for sent quotations) goes with it
dbx("INSERT INTO office_signoffs(org_id, kind, doc_id, title, token_hash, token, state, created_at) "
    "VALUES(?, 'offer', ?, 'x', 'p21142a-open', 'x', 'open', '2030-01-01T00:00:00Z')", (ORG, Q1))
r = A.delete(B + f"{D}/{Q1}")
check(r.ok, "the admin deletes the finalised, never sent quotation " + r.text[:200])
check(A.get(B + f"{D}/{Q1}").status_code == 404, "it is gone")
ent = log(A, Q1, "delete")
check(ent and ent[0]["detail"].get("number") == NUM1 and ent[0]["detail"].get("locked") is True, f"office log: delete with the number {ent}")
check(not dbx("SELECT 1 FROM office_signoffs WHERE token_hash='p21142a-open'"), "the open approval link went with it")

# ================================================================== unlock: back to a draft, the number stays
Q2 = offer(A, CL, "Trailer")
NUM2 = A.get(B + f"{D}/{Q2}").json()["number"]
r = A.post(B + f"{D}/{Q2}/unlock")
check(r.ok and r.json()["locked"] is False and r.json()["number"] == NUM2 and r.json()["can_edit"] is True, "unlocked: a draft with its number " + r.text[:200])
check(A.post(B + f"{D}/{Q2}/unlock").ok, "unlock of a draft: the document as it is")
check(A.patch(B + f"{D}/{Q2}", json={"project_title": "Trailer v2"}).ok, "editable again")
ent = log(A, Q2, "unlock")
check(ent and ent[0]["detail"].get("number") == NUM2, f"history: unlock with the number {ent}")
r = A.post(B + f"{D}/{Q2}/finalize")
check(r.ok and r.json()["locked"] is True and r.json()["number"] == NUM2, "finalised again: the same number " + r.text[:200])

# ================================================================== sent / accepted / declined / mailed / signed
# 2.417.0 C (#2604, #2574): delete and unlock 409 again (the test phase rule of 2.144.8 is gone)
def gone_ok(x, what):
    q = A.get(B + f"{D}/{x}").json()
    check(q["can_delete"] is False and q["can_unlock"] is False and "delete_sent" not in q, f"{what}: no delete, no unlock {q.get('can_delete')} {q.get('can_unlock')} {q.get('delete_sent')}")
    row = next((y for y in A.get(B + f"{D}?kind=offer").json()["docs"] if y["id"] == x), {})
    check(not row.get("can_delete") and not row.get("can_unlock") and "delete_sent" not in row, f"{what}: the list row too {row}")
    check(A.post(B + f"{D}/{x}/unlock").status_code == 409, f"{what}: unlock 409")
    r = A.delete(B + f"{D}/{x}")
    check(r.status_code == 409, f"{what}: delete 409 " + r.text[:200])
    check(A.get(B + f"{D}/{x}").ok, f"{what}: still there")


for st in ("sent", "accepted", "declined"):
    x = offer(A, CL, "Status " + st)
    check(A.post(B + f"{D}/{x}/status", json={"status": st}).ok, f"status {st}")
    gone_ok(x, st)
x = offer(A, CL, "Mailed")
dbx("UPDATE office_docs SET sent_at='2030-01-02T00:00:00Z' WHERE id=?", (x,))
gone_ok(x, "sent_at set (mailed, still draft)")
x = offer(A, CL, "Logged send")
dbx("INSERT INTO office_doc_log(org_id, doc_id, at, action, detail) VALUES(?, ?, '2030-01-02T00:00:00Z', 'send', '{}')", (ORG, x))
gone_ok(x, "a logged send")
check(not dbx("SELECT 1 FROM office_doc_log WHERE doc_id=? AND action='delete'", (x,)), "no delete entry in the office log")
x = offer(A, CL, "Signed")
dbx("INSERT INTO office_signoffs(org_id, kind, doc_id, title, token_hash, token, state, created_at) "
    "VALUES(?, 'offer', ?, 'x', 'p21142a-signed', 'x', 'accepted', '2030-01-01T00:00:00Z')", (ORG, x))
gone_ok(x, "signed by the customer")
check(dbx("SELECT 1 FROM office_signoffs WHERE token_hash='p21142a-signed'"), "the signed approval stays")
x = offer(A, CL, "Sent, not finalised", final=False)
check(A.post(B + f"{D}/{x}/status", json={"status": "sent"}).ok, "a sent quotation that was never finalised")
check(A.delete(B + f"{D}/{x}").status_code == 409, "sent, never finalised: delete 409 (2.417.0, #2604)")

# ================================================================== an invoice from it; invoices and credit notes stay strict
QI = offer(A, CL, "Invoiced")
r = A.post(B + f"{D}/{QI}/invoice")
check(r.status_code == 201, "an invoice from the finalised quotation " + r.text[:200])
INV = r.json()["id"]
r = A.delete(B + f"{D}/{QI}")
check(r.status_code == 409 and "invoice" in r.text, "an invoice was made from it: delete 409 " + r.text[:200])
check(A.post(B + f"{D}/{QI}/unlock").status_code == 409, "an invoice was made from it: unlock 409")
check(A.post(B + f"{D}/{QI}/status", json={"status": "accepted"}).ok, "the invoiced quotation accepted")
check(A.get(B + f"{D}/{QI}").json()["can_delete"] is False, "an invoice was made from it: can_delete false")
row = next((y for y in A.get(B + f"{D}?kind=offer").json()["docs"] if y["id"] == QI), {})
check(not row.get("can_delete"), f"an invoice was made from it: the list row too {row}")
r = A.delete(B + f"{D}/{QI}")
check(r.status_code == 409, "accepted + invoiced: delete 409 " + r.text[:200])  # 2.417.0 (#2604): the first reason (accepted) as in 2.114.2
r = A.post(B + f"{D}/{INV}/finalize")
check(r.ok and r.json()["locked"] is True, "the invoice finalised " + r.text[:300])
check(A.get(B + f"{D}/{INV}").json()["can_unlock"] is False, "invoice: can_unlock false")
check(A.delete(B + f"{D}/{INV}").status_code == 409, "a finalised invoice: delete 409")
check(A.post(B + f"{D}/{INV}/unlock").status_code == 409, "a finalised invoice: unlock 409")
r = A.post(B + f"{D}/{INV}/credit")
check(r.status_code == 201, "a credit note " + r.text[:200])
CR = r.json().get("id")
r = A.post(B + f"{D}/{CR}/finalize")
check(r.ok and r.json()["locked"] is True, "the credit note finalised " + r.text[:300])
check(A.delete(B + f"{D}/{CR}").status_code == 409, "a finalised credit note: delete 409")
check(A.post(B + f"{D}/{CR}/unlock").status_code == 409, "a finalised credit note: unlock 409")
check(A.post(B + f"{D}/{INV}/unlock").status_code == 409, "a cancelled invoice: unlock 409")

# ================================================================== references: pipeline deal, version chain
r = A.post(B + "/api/office/deals", json={"title": "Example deal", "client_id": CL})
check(r.status_code == 201, "a deal " + r.text[:200])
DEAL = r.json()["id"]
r = A.post(B + f"/api/office/deals/{DEAL}/offer")
check(r.status_code == 201, "a quotation for the deal " + r.text[:200])
QD = r.json()["doc_id"]
A.put(B + f"{D}/{QD}/items", json={"items": [{"title": "Edit", "qty": 1, "rate": 500}]})
check(A.post(B + f"{D}/{QD}/finalize").ok, "the deal's quotation finalised")
check(A.delete(B + f"{D}/{QD}").ok, "the deal's quotation deleted")
deal = next((x for x in A.get(B + "/api/office/deals").json().get("items", []) if x["id"] == DEAL), {})
check(deal and not deal.get("offer_id"), f"the deal points to no quotation any more {deal}")
check(A.post(B + f"/api/office/deals/{DEAL}/offer").status_code == 201, "the deal can get a new quotation")
QR = offer(A, CL, "Chain")
r = A.post(B + f"{D}/{QR}/duplicate")
check(r.status_code in (200, 201), "the next version " + r.text[:200])
QV = r.json()["id"]
check(A.delete(B + f"{D}/{QR}").ok, "the chain's first quotation deleted")
r = A.get(B + f"{D}/{QV}")
check(r.ok and isinstance(r.json().get("cf_chain"), (dict, list)), "the next version stays readable with its chain " + r.text[:200])
check(A.get(B + f"{D}?kind=offer").ok, "the list still loads")

# ================================================================== a person without an organisation
# freelancer-matrix: office
FID, F = freelancer(B, A)
FCL = setup_office(F)
FQ = offer(F, FCL, "Solo film")
q = F.get(B + f"{D}/{FQ}").json()
check(q["can_delete"] is True and q["can_unlock"] is True, "freelancer: its own admin, may delete / unlock")
FNUM = q["number"]
r = F.post(B + f"{D}/{FQ}/unlock")
check(r.ok and r.json()["locked"] is False and r.json()["number"] == FNUM, "freelancer: unlocked, number kept " + r.text[:200])
check(F.post(B + f"{D}/{FQ}/finalize").json().get("number") == FNUM, "freelancer: finalised again, same number")
check(A.delete(B + f"{D}/{FQ}").status_code in (400, 403, 404), "the organisation's admin cannot delete the freelancer's quotation")
check(F.delete(B + f"{D}/{FQ}").ok, "freelancer: deletes the finalised, never sent quotation")
FS = offer(F, FCL, "Solo sent")
F.post(B + f"{D}/{FS}/status", json={"status": "sent"})
check(F.post(B + f"{D}/{FS}/unlock").status_code == 409, "freelancer: sent, unlock 409")
check(F.delete(B + f"{D}/{FS}").status_code == 409, "freelancer: sent, delete 409 (2.417.0, #2604)")

# ================================================================== 2.417.0 C (#2604, #2574): the rule of 2.114.2 again
# (before: a switch set inside the container; now the running server)
OS, OA, OK = offer(A, CL, "Off sent"), offer(A, CL, "Off signed"), offer(A, CL, "Off never sent")
A.post(B + f"{D}/{OS}/status", json={"status": "sent"})
dbx("INSERT INTO office_signoffs(org_id, kind, doc_id, title, token_hash, token, state, created_at) "
    "VALUES(?, 'offer', ?, 'x', 'p21442a-off', 'x', 'accepted', '2030-01-01T00:00:00Z')", (ORG, OA))
for x, what in ((OS, "sent"), (OA, "signed"), (QI, "invoiced")):
    q = A.get(B + f"{D}/{x}").json()
    check(q["can_delete"] is False and q["can_unlock"] is False, f"{what}: delete rule == undo-finalising rule (2.114.2) {q.get('can_delete')} {q.get('can_unlock')}")
    check(A.delete(B + f"{D}/{x}").status_code == 409, f"{what}: stays (409)")
q = A.get(B + f"{D}/{OK}").json()
check(q["can_delete"] is True and q["can_unlock"] is True, "a never sent one: delete + unlock")
check(A.delete(B + f"{D}/{OK}").ok, "a never sent one may go")

print(f"p21142_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
