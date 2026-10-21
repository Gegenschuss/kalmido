#!/usr/bin/env python3
"""2.162.0 A (#2603) API tests: test phase - an admin deletes a finalised / sent invoice (invoices.INVOICE_DELETE_TESTPHASE,
#2604: off before the launch). Own container (start.sh), invented companies and people only (@example.com / .example).
 - a finalised, sent invoice with a payment, a matched bank booking, a billed time entry, a credit note and a reminder:
   the admin sees can_delete + delete_confirm + delete_info (sent, credits, reminders, payments, bank, time); a member
   does not (403 on DELETE)
 - DELETE without / with a wrong confirm_number: 409 code confirm_number; with the number: gone with credit note, reminder,
   payments; the bank booking is open again, the time entry free, the stored files gone, the office log says
   "delete" with testphase; afterwards the quotation it came from may be deleted (#2573)
 - cash book: without cash a 409 code cash with the count; cash=1 deletes the open entry, the one on a closed day stays
   (its reference emptied); cash=0 keeps the entries without the reference
 - a reminder listing another invoice too: 409, nothing deleted
 - a person without an organisation (freelancer-matrix: office) deletes an own finalised invoice the same way
 - switch off (a fresh process in the container): idt_applies false = the rule before (numbered invoices stay, 409)
usage: p2162_a_invoice_delete_test.py <datadir>      (a fresh container; P2162A_NOSTART=1 = the server already runs)"""
import base64
import glob
import json
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
FAILS, OKS = [], [0]
TODAY = testclock.today()
T0, Y1, Y5 = TODAY.isoformat(), (TODAY - timedelta(days=1)).isoformat(), (TODAY - timedelta(days=5)).isoformat()


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


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


def office_files(oid, did):
    return glob.glob(os.path.join(DATA, "office", str(int(oid)), f"doc{int(did)}-*"))


CL = setup_office(A)

# ================================================================== the full invoice: payments, bank, time, credit note, reminder
r = A.post(B + D, json={"kind": "offer", "project_title": "Film", "client_id": CL})
Q1 = r.json()["id"]
A.put(B + f"{D}/{Q1}/items", json={"items": [{"title": "Shoot", "qty": 1, "rate": 1000}]})
check(A.post(B + f"{D}/{Q1}/finalize").ok, "the quotation finalised")
r = A.post(B + f"{D}/{Q1}/invoice")
check(r.status_code == 201, "an invoice from the quotation " + r.text[:200])
INV = r.json()["id"]
r = A.post(B + f"{D}/{INV}/finalize")
check(r.ok, "the invoice finalised " + r.text[:200])
NUM = number(A, INV)
check(NUM, f"the invoice has a number {NUM}")
dbx("UPDATE office_docs SET status='sent', sent_at=? WHERE id=?", (T0 + "T09:00:00Z", INV))  # mailed (no mail server in the test)
check(delete(A, Q1).status_code == 409, "before: the invoiced quotation stays (BGA_USED)")
r = A.post(B + f"{D}/{INV}/payments", json={"date": T0, "amount": "100.00"})
check(r.status_code in (200, 201), "a payment " + r.text[:200])
# a bank booking matched on the invoice (books another payment)
csv = "Buchungstag;Auftraggeber/Empfänger;Verwendungszweck;Betrag\n" + f"{de(T0)};Example Client AG;Rechnung {NUM};50,00\n"
pv = A.post(B + O + "/bank/import/preview", json={"text": csv}).json()
mp = {k: (pv.get("guess") or {}).get(k) for k in ("date", "amount", "amount_in", "amount_out", "title", "counterpart", "decimal", "date_format")}
r = A.post(B + O + "/bank/import", json={"text": csv, "filename": "konto.csv", "mapping": mp})
check(r.status_code == 201, "bank import " + r.text[:200])
TX = next((t for t in A.get(B + O + "/bank/tx?state=all").json().get("items", []) if NUM in (t.get("purpose") or "")), {})
check(A.post(B + O + f"/bank/tx/{TX.get('id')}/match", json={"kind": "invoice", "id": INV}).ok, "the booking matched on the invoice")
# a time entry billed on it
dbx("INSERT INTO time_entries(user_id, task_title, start, \"end\", seconds, note, source, created_at, updated_at, billed_doc_id, billed_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (ALICE, "Edit", T0 + "T08:00:00Z", T0 + "T09:00:00Z", 3600, "", "manual", T0 + "T09:00:00Z", T0 + "T09:00:00Z", INV, T0))
TE = dbx("SELECT id FROM time_entries WHERE billed_doc_id=?", (INV,))[0][0]
r = A.post(B + f"{D}/{INV}/credit")
check(r.status_code == 201, "a credit note draft " + r.text[:200])
CR = r.json().get("id")
r = A.post(B + D + "/reminder", json={"doc_ids": [INV], "level": 1})
REM = r.json().get("id") if r.status_code == 201 else None
check(REM, "a reminder over the invoice " + r.text[:200])
files_before = office_files(ORG, INV)

d = A.get(B + f"{D}/{INV}").json()
info = d.get("delete_info") or {}
check(d.get("can_delete") is True and d.get("delete_confirm") is True, f"admin: can_delete + delete_confirm {d.get('can_delete')} {d.get('delete_confirm')} {d.get('delete_block')}")
check(info.get("number") == NUM and info.get("sent") is True, f"delete_info: number + sent {info}")
check(len(info.get("credits") or []) == 1 and len(info.get("reminders") or []) == (1 if REM else 0), f"delete_info: credit note + reminder {info}")
check(info.get("payments", 0) >= 2 and info.get("bank") == 1 and info.get("time") == 1, f"delete_info: payments / bank / time {info}")
row = next((x for x in A.get(B + D + "?kind=invoice").json().get("docs", []) if x["id"] == INV), {})
check(row.get("can_delete") is True and row.get("delete_confirm") is True, f"the list row offers Delete {row.get('can_delete')}")
# a member: never
dm = Bo.get(B + f"{D}/{INV}").json()
check(not dm.get("can_delete") and "delete_info" not in dm, "member: no can_delete, no delete_info")
check(delete(Bo, INV, NUM).status_code == 403, "member: DELETE 403")
# the number is checked by the server too
r = delete(A, INV)
check(r.status_code == 409 and r.json().get("code") == "confirm_number", "no confirm_number: 409 " + r.text[:200])
r = delete(A, INV, NUM + "X")
check(r.status_code == 409 and r.json().get("code") == "confirm_number", "a wrong number: 409 " + r.text[:200])
check(A.get(B + f"{D}/{INV}").ok, "still there after the 409s")
r = delete(A, INV, NUM)
check(r.ok and r.json().get("deleted") == (3 if REM else 2), "deleted with the number " + r.text[:200])
check(A.get(B + f"{D}/{INV}").status_code == 404 and A.get(B + f"{D}/{CR}").status_code == 404, "the invoice and its credit note are gone")
if REM:
    check(A.get(B + f"{D}/{REM}").status_code == 404, "the reminder is gone")
check(not dbx("SELECT 1 FROM office_payments WHERE doc_id=?", (INV,)), "the payments are gone")
t = dbx("SELECT match_kind, match_id, payment_id FROM office_bank_tx WHERE id=?", (TX.get("id"),))
check(t and t[0][0] is None and t[0][1] is None and t[0][2] is None, f"the bank booking is open again {t}")
check(dbx("SELECT billed_doc_id FROM time_entries WHERE id=?", (TE,))[0][0] is None, "the time entry is free again")
check(files_before == [] or office_files(ORG, INV) == [], f"the stored files are gone {office_files(ORG, INV)}")
log = A.get(B + O + "/log?limit=50").json().get("log", [])
lx = [x for x in log if x["action"] == "delete" and x.get("doc_id") == INV]
check(lx and lx[0]["detail"].get("testphase") is True and lx[0]["detail"].get("number") == NUM and lx[0]["detail"].get("kind") == "invoice",
      f"the office log: delete with testphase {lx[:1]}")
check(any(x["action"] == "delete" and x.get("doc_id") == CR and x["detail"].get("with") == NUM for x in log), "the office log: the credit note with it")
# 2.144.8 (#2573): nothing is made from the quotation any more
check(delete(A, Q1).ok, "afterwards the quotation may be deleted")

# ================================================================== cash book: ask first, closed days stay
BK = A.get(B + CBS).json()["books"][0]["id"]
check(A.patch(B + f"{CBS}/{BK}", json={"opening": "100", "opening_day": Y5}).ok, "the cash box opening")
INV2 = make(A, CL, "Cash paid")
NUM2 = number(A, INV2)
r = A.post(B + f"{CBS}/{BK}/entries", json={"day": Y1, "dir": "in", "amount": "20", "text": "Cash part 1", "invoice_id": INV2})
check(r.status_code == 201, "a cash entry (yesterday) " + r.text[:200])
E_CLOSED = r.json().get("id")
check(A.post(B + f"{CBS}/{BK}/closing", json={"day": Y1}).ok, "yesterday closed")
r = A.post(B + f"{CBS}/{BK}/entries", json={"day": T0, "dir": "in", "amount": "30", "text": "Cash part 2", "invoice_id": INV2})
check(r.status_code == 201, "a cash entry (today) " + r.text[:200])
E_OPEN = r.json().get("id")
r = delete(A, INV2, NUM2)
check(r.status_code == 409 and r.json().get("code") == "cash" and r.json().get("cash") == 1 and r.json().get("cash_closed") == 1,
      "cash entries: 409 code cash, one open, one closed " + r.text[:200])
check(A.get(B + f"{D}/{INV2}").ok, "still there after the cash question")
r = delete(A, INV2, NUM2, cash=1)
check(r.ok and r.json().get("cash_deleted") == 1 and r.json().get("cash_kept") == 1, "cash=1: deleted " + r.text[:200])
check(not dbx("SELECT 1 FROM office_cash_entries WHERE id=?", (E_OPEN,)), "the open cash entry is gone")
ce = dbx("SELECT invoice_id FROM office_cash_entries WHERE id=?", (E_CLOSED,))
check(ce and ce[0][0] is None, f"the entry on the closed day stays, without the reference {ce}")
INV3 = make(A, CL, "Cash kept")
r = A.post(B + f"{CBS}/{BK}/entries", json={"day": T0, "dir": "in", "amount": "10", "text": "Cash kept", "invoice_id": INV3})
E_KEEP = r.json().get("id")
r = delete(A, INV3, number(A, INV3), cash=0)
check(r.ok and r.json().get("cash_deleted") == 0, "cash=0: the invoice deleted " + r.text[:200])
ce = dbx("SELECT invoice_id FROM office_cash_entries WHERE id=?", (E_KEEP,))
check(ce and ce[0][0] is None, f"cash=0: the entry stays without the reference {ce}")

# ================================================================== a reminder over two invoices: 409
INV4, INV5 = make(A, CL, "Two A"), make(A, CL, "Two B")
r = A.post(B + D + "/reminder", json={"doc_ids": [INV4, INV5], "level": 1})
if r.status_code == 201:
    r = delete(A, INV4, number(A, INV4))
    check(r.status_code == 409 and "code" not in r.json(), "a reminder listing another invoice too: 409 " + r.text[:200])
    check(A.get(B + f"{D}/{INV4}").ok, "the invoice stays")
    check(A.get(B + f"{D}/{INV4}").json().get("delete_block"), "doc_public names why (delete_block)")
else:
    check(False, "a reminder over two invoices " + r.text[:200])

# ================================================================== freelancer-matrix: office (a person without an organisation)
FID, F = freelancer(B, A)
FCL = setup_office(F)
check(F.get(B + O + "/settings").json().get("role") == "admin", "freelancer: admin of the personal office")
FI = make(F, FCL, "Solo invoice")
FN = number(F, FI)
fd = F.get(B + f"{D}/{FI}").json()
check(fd.get("can_delete") is True and fd.get("delete_confirm") is True, "freelancer: may delete the own finalised invoice")
check(delete(F, FI, "nope").status_code == 409, "freelancer: a wrong number 409")
check(delete(F, FI, FN).ok, "freelancer: deleted with the number")
check(F.get(B + f"{D}/{FI}").status_code == 404, "freelancer: gone")

# ================================================================== switch off = the rule before (a fresh process in the container)
INV6 = make(A, CL, "Switch")
code = ("import json, app\nimport kalmido.office.invoices as inv\nimport kalmido.office.invdelete as m\nimport kalmido.office.docs as d\n"
        "c = app.connect()\ntry:\n    r = c.execute('SELECT * FROM office_docs WHERE id=?', (%d,)).fetchone()\n    on = m.idt_applies(r)\n"
        "    inv.INVOICE_DELETE_TESTPHASE = False\n    off = m.idt_applies(r)\n    print('RULE' + json.dumps([on, off, d.odoc_seq_numbered(r), bool(d.ofx_locked(r))]))\n"
        "finally:\n    c.close()\n") % INV6
p = subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True)
line = next((x for x in p.stdout.splitlines() if x.startswith("RULE")), None)
check(line, "switch off: the check ran " + (p.stdout + p.stderr)[-400:])
res = json.loads(line[4:]) if line else [None] * 4
check(res[0] is True and res[1] is False, f"switch off: the test phase rule no longer applies {res}")
check(res[2] is True and res[3] is True, f"switch off: the old rule keeps it (numbered + finalised = 409) {res}")

print(f"p2162_a_invoice_delete: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
