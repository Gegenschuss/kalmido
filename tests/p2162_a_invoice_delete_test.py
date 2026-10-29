#!/usr/bin/env python3
"""2.162.0 A (#2603) API tests, turned round by 2.417.0 C (#2604): the test phase deletion of finalised / sent invoices is
gone (invoices.INVOICE_DELETE_TESTPHASE, office/invdelete.py and confirm_number removed) - a finalised or sent invoice stays
(GoBD), the correction is a cancellation / credit note. Own container (start.sh), invented companies and people only.
 - a finalised, sent invoice with a payment and a credit note: no can_delete / delete_confirm / delete_info for the admin,
   not in the list row either; DELETE without / with confirm_number (and cash=1): 409 naming GoBD, the invoice, its payment
   and its credit note stay; the finalised credit note stays too; the quotation it came from stays (an invoice was made)
 - a sent invoice that was never finalised: 409; a member: 403
 - still deletable: an invoice draft without a number (to the office trash), a finalised trial invoice (at any time)
 - an agent token (scope office): DELETE of the finalised invoice does not go through, the invoice stays
 - a person without an organisation (freelancer-matrix: office): the same in the personal office
 - the switch and the module are gone (a fresh process in the container)
usage: p2162_a_invoice_delete_test.py <datadir>      (a fresh container; P2162A_NOSTART=1 = the server already runs)"""
import base64
import os
import subprocess
import sys
import time
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
TODAY = testclock.today()
T0, Y1, Y5 = TODAY.isoformat(), (TODAY - timedelta(days=1)).isoformat(), (TODAY - timedelta(days=5)).isoformat()


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


if not os.environ.get("P2162A_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
FEAT = "cal,comments,collab,clients,office,docs,files,time"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
D, O = "/api/office/docs", "/api/office"
CBS = O + "/cashbooks"
COMPANY = {"name": "Studio Example GmbH", "street": "Hafenweg 1", "zip": "20457", "city": "Hamburg", "country": "de",
           "email": "hello@studio.example", "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051",
           "bic": "BYLADEM1001", "bank_name": "Example Bank"}
CLIENT = {"name": "Example Client AG", "street": "Marktstrasse 5", "zip": "50667", "city": "Koeln", "country": "DE",
          "email_invoice": "billing@client.example", "payment_terms_days": 14}
de = lambda iso: f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"  # noqa: E731


def setup_office(s):
    r = s.put(B + O + "/settings", json={"company_fields": COMPANY, "lang": "en", "currency": "EUR"})
    check(r.ok, "office settings " + r.text[:200])
    r = s.post(B + "/api/clients", json=CLIENT)
    check(r.status_code in (200, 201), "a client " + r.text[:200])
    return r.json().get("id")


def make(s, cl, title, kind="invoice", final=True, rate=900):
    r = s.post(B + D, json={"kind": kind, "project_title": title, "client_id": cl, "service_from": Y5, "service_to": T0})
    check(r.status_code == 201, f"{title}: created " + r.text[:200])
    did = r.json()["id"]
    check(s.put(B + f"{D}/{did}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": rate}]}).ok, f"{title}: positions")
    if final:
        r = s.post(B + f"{D}/{did}/finalize")
        check(r.ok and r.json().get("locked") is True, f"{title}: finalised " + r.text[:300])
    return did


def number(s, did):
    return s.get(B + f"{D}/{did}").json().get("number") or ""


def delete(s, did, num=None, cash=None):
    q = []
    if num is not None:
        q.append("confirm_number=" + requests.utils.quote(num))
    if cash is not None:
        q.append(f"cash={cash}")
    return s.delete(B + f"{D}/{did}" + ("?" + "&".join(q) if q else ""))


CL = setup_office(A)
GOBD = "GoBD"  # the reason names the rule (ODOC_INV_KEPT)

# ================================================================== a finalised, sent invoice with a payment and a credit note
r = A.post(B + D, json={"kind": "offer", "project_title": "Film", "client_id": CL})
Q1 = r.json()["id"]
A.put(B + f"{D}/{Q1}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 1000}]})
check(A.post(B + f"{D}/{Q1}/finalize").ok, "the quotation finalised")
r = A.post(B + f"{D}/{Q1}/invoice")
check(r.status_code == 201, "an invoice from the quotation " + r.text[:200])
INV = r.json()["id"]
A.patch(B + f"{D}/{INV}", json={"service_from": Y5, "service_to": T0})
r = A.post(B + f"{D}/{INV}/finalize")
check(r.ok, "the invoice finalised " + r.text[:200])
NUM = number(A, INV)
check(NUM, f"the invoice has a number {NUM}")
dbx("UPDATE office_docs SET status='sent', sent_at=? WHERE id=?", (T0 + "T09:00:00Z", INV))  # mailed (no mail server in the test)
r = A.post(B + f"{D}/{INV}/payments", json={"date": T0, "amount": "100.00"})
check(r.status_code in (200, 201), "a payment " + r.text[:200])
r = A.post(B + f"{D}/{INV}/credit")
check(r.status_code == 201, "a credit note draft " + r.text[:200])
CR = r.json().get("id")

d = A.get(B + f"{D}/{INV}?delete_info=1").json()
check(d.get("can_delete") is False and "delete_confirm" not in d and "delete_info" not in d and "delete_block" not in d,
      f"admin: no can_delete / delete_confirm / delete_info {d.get('can_delete')} {d.get('delete_confirm')} {d.get('delete_info')}")
row = next((x for x in A.get(B + D + "?kind=invoice").json().get("docs", []) if x["id"] == INV), {})
check(not row.get("can_delete") and "delete_confirm" not in row, f"the list row offers no Delete {row.get('can_delete')}")
for q, what in (("", "no number"), (f"?confirm_number={requests.utils.quote(NUM)}", "the number typed"),
                (f"?confirm_number={requests.utils.quote(NUM)}&cash=1", "the number + cash=1")):
    r = A.delete(B + f"{D}/{INV}{q}")
    check(r.status_code == 409 and GOBD in r.text and r.json().get("code") != "confirm_number", f"{what}: 409 (GoBD) " + r.text[:200])
check(A.get(B + f"{D}/{INV}").ok and A.get(B + f"{D}/{CR}").ok, "the invoice and its credit note stay")
check(dbx("SELECT count(*) FROM office_payments WHERE doc_id=?", (INV,))[0][0] == 1, "its payment stays")
check(not [x for x in A.get(B + O + "/log?limit=50").json().get("log", []) if x["action"] == "delete" and x.get("doc_id") == INV],
      "the office log has no delete entry")
r = A.post(B + f"{D}/{CR}/finalize")
check(r.ok and r.json().get("locked") is True, "the credit note finalised " + r.text[:200])
r = A.delete(B + f"{D}/{CR}")
check(r.status_code == 409 and GOBD in r.text, "a finalised credit note: 409 " + r.text[:200])
check(A.delete(B + f"{D}/{Q1}").status_code == 409, "the invoiced quotation stays (BGA_USED)")
check(Bo.delete(B + f"{D}/{INV}?confirm_number={requests.utils.quote(NUM)}").status_code == 403, "member: DELETE 403")

# ================================================================== sent, never finalised
SN = make(A, CL, "Sent draft", final=False)
dbx("UPDATE office_docs SET status='sent', sent_at=? WHERE id=?", (T0 + "T09:00:00Z", SN))
check(A.get(B + f"{D}/{SN}").json().get("can_delete") is False, "a sent invoice draft: no can_delete")
check(A.delete(B + f"{D}/{SN}").status_code == 409 and A.get(B + f"{D}/{SN}").ok, "a sent invoice draft: 409, it stays")

# ================================================================== still deletable: a draft without a number, a trial invoice
DR = make(A, CL, "Plain draft", final=False)
check(number(A, DR) == "" and A.get(B + f"{D}/{DR}").json().get("can_delete") is True, "an invoice draft without a number: can_delete")
r = A.delete(B + f"{D}/{DR}")
check(r.ok and r.json().get("trash_id") and A.get(B + f"{D}/{DR}").status_code == 404, "the draft goes to the office trash " + r.text[:200])
r = A.post(B + D, json={"kind": "invoice", "project_title": "Trial", "client_id": CL, "service_from": Y5, "service_to": T0, "trial": True})
check(r.status_code == 201 and r.json().get("trial") is True, "a trial invoice " + r.text[:200])
TR = r.json()["id"]
A.put(B + f"{D}/{TR}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 100}]})
check(A.post(B + f"{D}/{TR}/finalize").ok, "the trial invoice finalised")
check(A.get(B + f"{D}/{TR}").json().get("can_delete") is True, "a finalised trial invoice: can_delete")
check(A.delete(B + f"{D}/{TR}").ok and A.get(B + f"{D}/{TR}").status_code == 404, "a finalised trial invoice goes at any time")

# ================================================================== an agent token never deletes a finalised invoice
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "officebot", "display_name": "Office Bot", "scopes": ["read", "office"], "org_id": ORG})
check(r.ok and r.json().get("token"), "an office agent " + r.text[:200])
AH = {**H, "Authorization": "Bearer " + (r.json().get("token") or "")}
r = requests.delete(B + f"{D}/{INV}?confirm_number={requests.utils.quote(NUM)}", headers=AH)
check(not r.ok and A.get(B + f"{D}/{INV}").ok, f"agent token: DELETE refused ({r.status_code}), the invoice stays")

# ================================================================== freelancer-matrix: office (a person without an organisation)
FID, F = freelancer(B, A)
FCL = setup_office(F)
check(F.get(B + O + "/settings").json().get("role") == "admin", "freelancer: admin of the personal office")
FI = make(F, FCL, "Solo invoice")
FN = number(F, FI)
check(F.get(B + f"{D}/{FI}").json().get("can_delete") is False, "freelancer: the own finalised invoice has no can_delete")
r = F.delete(B + f"{D}/{FI}?confirm_number={requests.utils.quote(FN)}")
check(r.status_code == 409 and GOBD in r.text and F.get(B + f"{D}/{FI}").ok, "freelancer: 409 with the number, it stays " + r.text[:200])
FD = make(F, FCL, "Solo draft", final=False)
check(F.delete(B + f"{D}/{FD}").ok, "freelancer: an invoice draft without a number goes")

# ================================================================== the switch and the module are gone
code = ("import importlib.util, json, app\nimport kalmido.office.invoices as inv\n"
        "print('RULE' + json.dumps([hasattr(inv, 'INVOICE_DELETE_TESTPHASE'), importlib.util.find_spec('kalmido.office.invdelete') is not None]))\n")
p = subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True)
line = next((x for x in p.stdout.splitlines() if x.startswith("RULE")), None)
check(line, "the check ran " + (p.stdout + p.stderr)[-400:])
check(line == "RULE[false, false]", f"no switch, no invdelete module {line}")

print(f"p2162_a_invoice_delete: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
