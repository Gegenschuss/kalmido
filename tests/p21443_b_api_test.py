#!/usr/bin/env python3
"""2.147.1 API tests, part B (#2054, first built for 2.109): payment reminders suggested for overdue invoices + the GiroCode (EPC QR) on invoices and
reminders. Own container (start.sh, mode workspaces). Invented companies, people and figures only.
tenant-matrix: office  freelancer-matrix: office
 - GiroCode: the EPC text of a draft invoice against a fixed example string (BCD / 002 / 1 / SCT / BIC / name / IBAN /
   EUR amount / remittance = number), the number after finalising, a reminder = open amounts + fee; no code for USD, a
   credit note, without IBAN or with the setting off; a document finalised with the setting off keeps no code after it is
   switched on again (frozen); the PDF carries the code (its label) only with EUR + IBAN
 - suggestions (the watchdog): an invoice overdue for more than the grace days gets ONE reminder draft (level 1) and a
   task for the admin; within the grace days, paid or cancelled ones none; two invoices of one client = one draft; never
   twice (also after the draft is deleted on the same level); after a finalised reminder's deadline the next level
 - the list: GET /api/office/docs answers dunning.suggested and marks the suggested drafts
 - settings: dunning_suggest off = none, grace days 0..90, members 403; the boundary: another organisation's invoices are
   never in a draft of this one; a person without an organisation gets the same in the own personal office
usage: p21443_b_api_test.py <datadir>"""
import os
import re
import subprocess
import sys
import time
import zlib
from datetime import timedelta

import requests

import dbx as dbxm
import testclock
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
O = "/api/office"
D = O + "/docs"
FEAT = "cal,comments,collab,office,clients"
IBAN = "DE02120300000000202051"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "email": "hallo@beispiel.example",
           "vat_id": "DE123456789", "iban": IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(q, a=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


if not os.environ.get("P21443B_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
TODAY = testclock.today()
ago = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731
# Beta starts with the suggestions off (the switch); Alpha keeps the defaults (on, 7 days)
assert A.put(B + O + "/settings", json={"lang": "de", "company_fields": COMPANY}).ok
assert Ca.put(B + O + "/settings", json={"lang": "de", "dunning_suggest": 0, "company_fields": dict(COMPANY, name="Andere Firma AG")}).ok


def client(s, name):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def invoice(s, cl, rate=500, **kw):
    r = s.post(B + D, json={"kind": "invoice", "lang": "de", "client_id": cl, "project_title": "Schnitt", "service_from": "2026-05-01",
                            "items": [{"title": "Schnitt", "qty": 1, "rate": rate}], **kw})
    assert r.status_code == 201, r.text
    return r.json()


def fin(s, did, due_ago=None):
    r = s.post(B + f"{D}/{did}/finalize")
    check(r.ok, f"finalise {did} " + r.text[:200])
    if due_ago is not None:
        dbx("UPDATE office_docs SET due_date=? WHERE id=?", (ago(due_ago), did))
    return r.json() if r.ok else {}


def render(s, did):
    return s.get(B + f"{D}/{did}/render").json()


def gc(s, did):
    return ((render(s, did).get("payment") or {}).get("girocode")) or None


def pdf_has_code(s, did):
    """True when the PDF draws the GiroCode label (the content streams, inflated)."""
    raw = s.get(B + f"{D}/{did}/pdf").content
    want = b"GiroCode".hex().encode()
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        try:
            data = zlib.decompress(m.group(1))
        except zlib.error:
            data = m.group(1)
        if want in data.lower() or b"GiroCode" in data:
            return True
    return False


def reminders(s, inv_id=None, drafts=None):
    rows = [x for x in dbx("SELECT id, ref_doc_ids, reminder_level, locked_at, org_id FROM office_docs WHERE kind='reminder' ORDER BY id")]
    out = []
    for rid, refs, lvl, locked, oid in rows:
        ids = [int(i) for i in re.findall(r"\d+", refs or "")]
        if inv_id is not None and inv_id not in ids:
            continue
        if drafts is not None and bool(locked) == drafts:
            continue
        out.append({"id": rid, "ids": ids, "level": lvl, "locked": bool(locked), "org_id": oid})
    return out


CL1 = client(A, "Kunde Eins GmbH")
CL2 = client(A, "Kunde Zwei GmbH")

# ================================================================== GiroCode
I0 = invoice(A, CL1)
# 2.109.0 (#2054, review): unused trailing elements are left out (a draft has no number yet)
want = "\n".join(("BCD", "002", "1", "SCT", "BYLADEM1001", "Beispiel Film GmbH", IBAN, "EUR595.00"))
check(gc(A, I0["id"]) == want, f"girocode: the EPC text of a draft (fixed example) {gc(A, I0['id'])!r}")
check(pdf_has_code(A, I0["id"]), "girocode: the draft PDF carries the code")
F0 = fin(A, I0["id"])
code = gc(A, I0["id"]) or ""
check(code.split("\n")[7:] == ["EUR595.00", "", "", F0.get("number")] and F0.get("number"), f"girocode: the number as remittance after finalising {code!r}")
check(pdf_has_code(A, I0["id"]), "girocode: the stored PDF of the finalised invoice carries the code")
U = invoice(A, CL1, currency="USD")
check(gc(A, U["id"]) is None and not pdf_has_code(A, U["id"]), "girocode: no code for USD")
cr = A.post(B + f"{D}/{I0['id']}/credit")
check(cr.status_code == 201 and gc(A, cr.json()["id"]) is None, "girocode: no code on a credit note")
r = A.post(B + D + "/reminder", json={"doc_ids": [I0["id"]], "level": 1, "fee": 5})
check(r.status_code == 201 and (gc(A, r.json()["id"]) or "").split("\n")[7] == "EUR600.00", f"girocode: a reminder = open amount + fee {gc(A, r.json()['id']) if r.ok else r.text[:200]!r}")
A.delete(B + f"{D}/{r.json()['id']}")
check(A.put(B + O + "/settings", json={"girocode": 0}).ok, "girocode: switched off")
I_OFF = invoice(A, CL1)
check(gc(A, I_OFF["id"]) is None and not pdf_has_code(A, I_OFF["id"]), "girocode: off = no code on a draft")
fin(A, I_OFF["id"])
check(A.put(B + O + "/settings", json={"girocode": 1}).ok and A.get(B + O + "/settings").json()["settings"].get("girocode") == 1, "girocode: on again")
check(gc(A, I_OFF["id"]) is None and not pdf_has_code(A, I_OFF["id"]), "girocode: a document finalised without the code keeps it so (GoBD)")
check(gc(A, I0["id"]) == code, "girocode: the finalised invoice keeps its code")
check(Bo.put(B + O + "/settings", json={"girocode": 0, "dunning_suggest": 0}).status_code == 403, "settings: a member may not switch them")
check(A.put(B + O + "/settings", json={"dunning_grace_days": 91}).status_code == 400 and A.put(B + O + "/settings", json={"dunning_grace_days": -1}).status_code == 400,
      "settings: grace days 0..90")
s_ = A.get(B + O + "/settings").json()["settings"]
check(s_.get("dunning_suggest") == 1 and s_.get("dunning_grace_days") == 7, f"settings: defaults on + 7 days {s_.get('dunning_suggest')} {s_.get('dunning_grace_days')}")
check(A.delete(B + f"{D}/{U['id']}").ok and (not cr.ok or A.delete(B + f"{D}/{cr.json()['id']}").ok), "setup: the USD draft and the credit draft deleted")
dbx("UPDATE office_docs SET due_date=? WHERE id IN (?, ?)", (ago(-30), I0["id"], I_OFF["id"]))  # not overdue: out of the way below

# ================================================================== suggestions (the watchdog)
I1 = invoice(A, CL1)
fin(A, I1["id"], due_ago=10)                                   # overdue > 7 days -> level 1
I2 = invoice(A, CL1)
fin(A, I2["id"], due_ago=3)                                    # within the grace days
I3 = invoice(A, CL1)
fin(A, I3["id"], due_ago=20)
check(A.post(B + f"{D}/{I3['id']}/payments", json={"amount": 595}).ok, "setup: I3 paid")
I4 = invoice(A, CL1)
fin(A, I4["id"], due_ago=20)
c4 = A.post(B + f"{D}/{I4['id']}/credit").json()
fin(A, c4["id"])                                               # I4 cancelled by a full credit note
I5, I6 = invoice(A, CL2), invoice(A, CL2, rate=300)
fin(A, I5["id"], due_ago=15)
fin(A, I6["id"], due_ago=12)
# Beta (suggestions off) with an overdue invoice; Alpha must never name it
CLB = client(Ca, "Kunde Beta AG")
IB = invoice(Ca, CLB)
fin(Ca, IB["id"], due_ago=30)

got = until(lambda: reminders(A, I1["id"]), 60)
check(len(got) == 1 and got[0]["level"] == 1 and not got[0]["locked"] and got[0]["ids"] == [I1["id"]], f"suggest: one level-1 draft for the overdue invoice {got}")
g56 = until(lambda: reminders(A, I5["id"]), 30)
check(len(g56) == 1 and sorted(g56[0]["ids"]) == sorted([I5["id"], I6["id"]]), f"suggest: one draft per client covering both invoices {g56}")
check(not reminders(A, I2["id"]), "suggest: none within the grace days")
check(not reminders(A, I3["id"]) and not reminders(A, I4["id"]), "suggest: none for paid / cancelled invoices")
check(not reminders(Ca, IB["id"]), "suggest: switched off in Beta = none")
check(all(x["org_id"] == ORG for x in reminders(A) if I1["id"] in x["ids"] or I5["id"] in x["ids"]), "suggest: the drafts belong to the invoices' organisation")
tk = until(lambda: dbx("SELECT title, url, content FROM tasks WHERE assignee_id=? AND title LIKE ?", (ALICE, "%reminders suggested%")), 20)
check(bool(tk) and "#office/offers/" in (tk[0][1] or "") and "595" not in (tk[0][2] or "") and "595" not in tk[0][0], f"suggest: a task for the admin with the link, no amount {tk}")
L = A.get(B + D + "?kind=invoice").json()
check((L.get("dunning") or {}).get("suggested") == 2, f"list: the invoice list names 2 suggested drafts {L.get('dunning')}")
LR = {x["id"]: x for x in A.get(B + D + "?kind=reminder").json()["docs"]}
check(LR.get(got[0]["id"], {}).get("suggested") == 1 if got else False, "list: the suggested draft is marked")
check((Bo.get(B + D + "?kind=invoice").json().get("dunning") or {}).get("suggested") == 2, "list: a member sees the hint too")
check((Ca.get(B + D + "?kind=invoice").json().get("dunning") or {}).get("suggested") == 0, "list: another organisation counts none of them")

# never twice, also after deleting the draft
time.sleep(25)  # two more watchdog runs
check(len(reminders(A, I1["id"])) == 1 and len(reminders(A, I5["id"])) == 1, "suggest: never twice")
check(A.delete(B + f"{D}/{got[0]['id']}").ok if got else False, "the suggested draft deleted by hand")
time.sleep(25)
check(not reminders(A, I1["id"]), "suggest: a deleted draft is not suggested again on the same level")

# the next level: the level-1 reminder of I5 + I6 finalised and its deadline passed
if g56:
    fin(A, g56[0]["id"])
    dbx("UPDATE office_docs SET date=?, reminder_deadline_days=10 WHERE id=?", (ago(20), g56[0]["id"]))
    g2 = until(lambda: [x for x in reminders(A, I5["id"]) if x["level"] == 2], 60)
    check(len(g2) == 1 and sorted(g2[0]["ids"]) == sorted([I5["id"], I6["id"]]) and not g2[0]["locked"], f"suggest: the next level after the deadline {g2}")

# Beta switched on: its own invoice in its own draft
check(Ca.put(B + O + "/settings", json={"dunning_suggest": 1, "dunning_grace_days": 0}).ok, "Beta: suggestions on (0 days)")
gb = until(lambda: reminders(Ca, IB["id"]), 60)
check(len(gb) == 1 and gb[0]["org_id"] == ORG2 and gb[0]["ids"] == [IB["id"]], f"boundary: Beta's draft has only Beta's invoice {gb}")
check(not [x for x in reminders(A) if IB["id"] in x["ids"] and x["org_id"] != ORG2] and not [x for x in reminders(A) if x["org_id"] == ORG2 and set(x["ids"]) - {IB["id"]}],
      "boundary: Beta's invoice in no Alpha reminder, no Alpha invoice in a Beta reminder")
check(gb[0]["id"] not in {x["id"] for x in A.get(B + D + "?kind=reminder").json()["docs"]} if gb else False, "boundary: Alpha does not see Beta's draft")

# ================================================================== a person without an organisation (personal office)
FID, Fr = freelancer(B, A, "dave")
r = Fr.put(B + O + "/settings", json={"lang": "de", "company_fields": dict(COMPANY, name="Dave Schnitt")})
check(r.ok, "freelancer: own office settings " + r.text[:200])
CLF = client(Fr, "Kunde Frei")
IFN = invoice(Fr, CLF)
check((gc(Fr, IFN["id"]) or "").split("\n")[5:8] == ["Dave Schnitt", IBAN, "EUR595.00"], f"freelancer: the GiroCode in the own office {gc(Fr, IFN['id'])!r}")
fin(Fr, IFN["id"], due_ago=9)
gf = until(lambda: reminders(Fr, IFN["id"]), 60)
check(len(gf) == 1 and gf[0]["level"] == 1 and gf[0]["org_id"] not in (ORG, ORG2), f"freelancer: a suggested draft in the personal office {gf}")
check((Fr.get(B + D + "?kind=invoice").json().get("dunning") or {}).get("suggested") == 1, "freelancer: the hint in the own list")
check(bool(until(lambda: dbx("SELECT 1 FROM tasks WHERE assignee_id=? AND title LIKE ?", (FID, "%reminders suggested%")), 20)), "freelancer: the task in the own inbox")
check(gf[0]["id"] not in {x["id"] for x in A.get(B + D + "?kind=reminder").json()["docs"]} if gf else False, "freelancer: the organisation's admin sees nothing of it")
check(A.get(B + f"{D}/{gf[0]['id']}").status_code == 404 if gf else False, "freelancer: the draft is 404 for others")
check(Fr.put(B + O + "/settings", json={"dunning_suggest": 0}).ok, "freelancer: may switch the own suggestions off")

check(dbx("SELECT COUNT(*) FROM office_dunning_marks GROUP BY doc_id, level HAVING COUNT(*) > 1") == [], "never two marks for one invoice + level")
print(f"p21443_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
