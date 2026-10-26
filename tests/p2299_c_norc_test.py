#!/usr/bin/env python3
"""2.299.0 C (#3192) API tests: bank bookings without a receipt, own container (start.sh, org encryption on). Invented companies,
people, accounts and figures only; every statement / receipt is made here. tenant-matrix: office  freelancer-matrix: office
 - match kind noreceipt ("needs no receipt"): set and undone like private / ignored, 409 twice, in the bank list as matched
 - GET /api/office/bank/noreceipt: money out without a receipt (open only: not private / ignored / noreceipt / matched),
   dir=in = money in without an invoice, filter month and account (two CAMT statements with their own IBAN), day / amount /
   counterpart / IBAN per row (what a later mailbox fetch needs), a locked month marked (match there 409), the open receipts
   for dragging, upload_ws; the upload path of the client (POST /api/docs, PUT receipt keep, match receipt) takes a row away
 - GET /api/office/bank/noreceipt/count: {out, in}
 - the reminder: off by default; on = one task at once in the inbox of the person (count in the title, link #office/bank/norc),
   a member / a person of another office as responsible 400; two runs at the same time make ONE task (threads in the app
   container); the watchdog completes the task once the list is empty; off ends an open task (done, never deleted)
 - rights: a member 403, another organisation 404 on a foreign booking, an agent 403; a person without organisation (personal
   office) uses all of it for themself
usage: p2299_c_norc_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time
from datetime import timedelta

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
from kt import FAILS, OKS, check, sess, until, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
from freelancer_fixture import freelancer
KEY = base64.b64encode(os.urandom(32)).decode()
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def in_app(code):
    """Python inside the app container (the reminder's run called directly)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\n" + code], capture_output=True, text=True)
    return out.stdout + out.stderr


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


if not os.environ.get("KMT_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,office,clients,docs"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
O = "/api/office"
K = O + "/bank"
NR = K + "/noreceipt"
TODAY = testclock.today()
d = lambda n: (TODAY - timedelta(days=n)).isoformat()
OLD = (TODAY.replace(day=1) - timedelta(days=40)).isoformat()  # a day two months back: its month gets locked
IBAN1, IBAN2 = "DE02120300000000202051", "DE89370400440532013000"
for s, name in ((A, "Beispiel Film GmbH"), (Ca, "Andere Firma GmbH")):
    s.put(B + O + "/settings", json={"company_fields": {"name": name, "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE"}})


def ntry(amt, ind, day, ref, name, iban=""):
    party = "Cdtr" if ind == "DBIT" else "Dbtr"
    acct = f"<{party}Acct><Id><IBAN>{iban}</IBAN></Id></{party}Acct>" if iban else ""
    return (f'<Ntry><Amt Ccy="EUR">{amt}</Amt><CdtDbtInd>{ind}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{day}</Dt></BookgDt>'
            f'<AcctSvcrRef>{ref}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><{party}><Pty><Nm>{name}</Nm></Pty></{party}>{acct}</RltdPties>'
            f'<RmtInf><Ustrd>Buchung {ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>')


def camt(acct, close_day, entries):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>STMT-{acct[-4:]}</Id>
<Acct><Id><IBAN>{acct}</IBAN></Id><Ccy>EUR</Ccy></Acct><Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">1000.00</Amt>
<CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{close_day}</Dt></Dt></Bal>{"".join(entries)}</Stmt></BkToCstmrStmt></Document>"""


def imp(s, text, name):
    r = s.post(B + K + "/import", json={"text": text, "filename": name})
    assert r.status_code == 201, r.text
    return r.json()


imp(A, camt(IBAN1, d(1), [ntry("119.00", "DBIT", d(5), "A-1", "Software Beispiel GmbH", "DE44500105175407324931"),
                          ntry("4.50", "DBIT", d(3), "A-2", "Bäckerei Beispiel"),
                          ntry("9.90", "DBIT", d(2), "A-3", "Beispielbank Entgelt"),
                          ntry("1190.00", "CRDT", d(4), "A-4", "Kunde Eins GmbH", "DE75512108001245126199"),
                          ntry("35.00", "DBIT", OLD, "A-5", "Altes Abo Beispiel")]), "konto1.xml")
imp(A, camt(IBAN2, d(1), [ntry("60.00", "DBIT", d(6), "B-1", "Druckerei Beispiel")]), "konto2.xml")
TX = {t["purpose"]: t for t in A.get(B + K + "/tx?state=all").json()["items"]}
t_soft, t_back, t_fee, t_in, t_old, t_druck = (TX[f"Buchung {x}"] for x in ("A-1", "A-2", "A-3", "A-4", "A-5", "B-1"))
check(len(TX) == 6, f"six bookings imported {sorted(TX)}")

# ---------------------------------------------------------------- the list
j = A.get(B + NR).json()
ids = [t["id"] for t in j["items"]]
check(set(ids) == {t_soft["id"], t_back["id"], t_fee["id"], t_old["id"], t_druck["id"]}, f"out: the five payments, no income {j['items']}")
check(j["counts"] == {"out": 5, "in": 1}, f"counts {j['counts']}")
row = next(t for t in j["items"] if t["id"] == t_soft["id"])
check(row["day"] == d(5) and row["amount"] == "-119.00" and row["counterpart"] == "Software Beispiel GmbH" and row["iban"] == "DE44500105175407324931"
      and row["account"] == IBAN1 and row["locked"] is False, f"a row: day, amount, counterpart, IBAN, account {row}")
check(sorted(j["accounts"]) == sorted([IBAN1, IBAN2]), f"two accounts offered {j['accounts']}")
check(j["upload_ws"] == f"org:{ORG}" and "noreceipt" in j["kinds"], f"upload_ws + kinds {j['upload_ws']} {j['kinds']}")
j = A.get(B + NR + f"?account={IBAN2}").json()
check([t["id"] for t in j["items"]] == [t_druck["id"]], f"account filter {j['items']}")
j = A.get(B + NR + f"?month={OLD[:7]}").json()
check([t["id"] for t in j["items"]] == [t_old["id"]] and OLD[:7] in j["months"], f"month filter {j['items']} {j['months']}")
j = A.get(B + NR + "?dir=in").json()
check([t["id"] for t in j["items"]] == [t_in["id"]] and j["receipts"] == [], f"dir=in: income without an invoice {j['items']}")
for q in ("dir=x", "month=2026-13", "month=x"):
    check(A.get(B + NR + "?" + q).status_code == 400, f"bad {q}: 400")
check(A.get(B + NR + "/count").json() == {"out": 5, "in": 1}, "count")

# ---------------------------------------------------------------- noreceipt
r = A.post(B + f"{K}/tx/{t_fee['id']}/match", json={"kind": "noreceipt"})
check(r.ok and r.json()["match"]["kind"] == "noreceipt", "noreceipt: bank fee marked " + r.text[:200])
check(A.post(B + f"{K}/tx/{t_fee['id']}/match", json={"kind": "noreceipt"}).status_code == 409, "noreceipt: twice 409")
check(t_fee["id"] not in [t["id"] for t in A.get(B + NR).json()["items"]], "noreceipt: off the list")
check(any(t["id"] == t_fee["id"] for t in A.get(B + K + "/tx?state=matched").json()["items"]), "noreceipt: matched in the bank list")
r = A.post(B + f"{K}/tx/{t_fee['id']}/unmatch")
check(r.ok and r.json()["was"] == {"kind": "noreceipt", "id": None}, "noreceipt: undone " + r.text[:200])
check(t_fee["id"] in [t["id"] for t in A.get(B + NR).json()["items"]], "noreceipt: back on the list after the undo")
A.post(B + f"{K}/tx/{t_back['id']}/match", json={"kind": "private"})
check(t_back["id"] not in [t["id"] for t in A.get(B + NR).json()["items"]], "private: off the list")

# ---------------------------------------------------------------- upload a receipt for a row (the client's path)
up = A.post(B + "/api/docs", files={"files": ("druck.pdf", tiny_pdf("Rechnung Druckerei Beispiel 60,00 EUR"), "application/pdf")}, data={"ws": f"org:{ORG}"})
nid = (up.json().get("ids") or [None])[0]
check(up.ok and nid, "upload: a document " + up.text[:200])
check(A.put(B + f"/api/docs/{nid}/receipt", json={"keep": True}).ok, "upload: it becomes a receipt")
r = A.post(B + f"{K}/tx/{t_druck['id']}/match", json={"kind": "receipt", "id": nid})
check(r.ok and r.json()["match"]["kind"] == "receipt", "upload: matched with the booking " + r.text[:200])
check(t_druck["id"] not in [t["id"] for t in A.get(B + NR).json()["items"]], "upload: the row is gone")
check(sql("SELECT paid_at FROM rc_receipts WHERE node_id=?", (nid,))[0][0] == d(6), "upload: the receipt has the booking's day as payment day")

# ---------------------------------------------------------------- a locked month
ML = f"{OLD[5:7]}/{OLD[:4]}"
r = A.post(B + O + "/periods/lock", json={"through": OLD[:7], "confirm": ML})
check(r.ok, "lock the old month " + r.text[:200])
row = next((t for t in A.get(B + NR).json()["items"] if t["id"] == t_old["id"]), {})
check(row.get("locked") is True, f"locked month: marked {row}")
check(A.post(B + f"{K}/tx/{t_old['id']}/match", json={"kind": "noreceipt"}).status_code == 409, "locked month: noreceipt 409")

# ---------------------------------------------------------------- rights
check(Bo.get(B + NR).status_code == 403 and Bo.get(B + NR + "/count").status_code == 403 and Bo.get(B + NR + "/reminder").status_code == 403
      and Bo.put(B + NR + "/reminder", json={"every": "week"}).status_code == 403, "a member 403")
check(Ca.post(B + f"{K}/tx/{t_soft['id']}/match", json={"kind": "noreceipt"}).status_code == 404, "another organisation: a foreign booking 404")
check(Ca.get(B + NR).json()["items"] == [] and Ca.get(B + NR + "/count").json() == {"out": 0, "in": 0}, "another organisation sees none of ours")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "norcbot", "display_name": "Norc Bot"})
AG = {**H, "Authorization": "Bearer " + r.json()["token"]}
check(all(x.status_code in (401, 403) for x in (requests.get(B + NR, headers=AG), requests.get(B + NR + "/count", headers=AG),
                                                 requests.put(B + NR + "/reminder", headers=AG, json={"every": "week"}))), "an agent 403")

# ---------------------------------------------------------------- the reminder
TITLE = lambda n: f"{n} booking without a receipt" if n == 1 else f"{n} bookings without a receipt"


def rtasks(uid=ALICE):
    return sql("SELECT id, title, status, deleted_at, url, due FROM tasks WHERE created_by=? AND title LIKE ? ORDER BY id", (uid, "% without a receipt"))


j = A.get(B + NR + "/reminder").json()
check(j["every"] == "off" and j["task"] is None and [p["id"] for p in j["people"]] == [ALICE], f"reminder: off by default, people = the admins {j}")
check(A.put(B + NR + "/reminder", json={"every": "daily"}).status_code == 400, "reminder: every daily 400")
check(A.put(B + NR + "/reminder", json={"every": "week", "user": BOB}).status_code == 400, "reminder: a member as responsible 400")
check(A.put(B + NR + "/reminder", json={"every": "week", "user": CAROL}).status_code == 400, "reminder: a person of another office 400")
r = A.put(B + NR + "/reminder", json={"every": "week"})
j = r.json()
check(r.ok and j["every"] == "week" and j["user"] == ALICE and j["task"], "reminder: on, a task at once " + r.text[:200])
n_open = A.get(B + NR + "/count").json()["out"]
rt = rtasks()
check(len(rt) == 1 and rt[0][1] == TITLE(n_open) and rt[0][2] == 0 and "#office/bank/norc" in (rt[0][4] or "") and (rt[0][5] or "")[:10] == TODAY.isoformat(),
      f"reminder: one task, count in the title, link, due today {rt}")
time.sleep(0.2)
check(len(rtasks()) == 1 and A.put(B + NR + "/reminder", json={"every": "week"}).ok and len(rtasks()) == 1, "reminder: saving again keeps the one task")

# two runs at the same time (a day after the next date, the task done by hand): ONE new task
check(A.patch(B + f"/api/tasks/{rt[0][0]}", json={"status": 2}).ok, "the person completes the task")
FUT = (TODAY + timedelta(days=30)).isoformat()
out = in_app(f"""import threading
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.office.banknorc import bnr_area
bar, errs = threading.Barrier(2), []
def run():
    c = connect()
    try:
        bar.wait()
        with system_ctx(c):
            bnr_area(c, {ORG}, {FUT!r})
    except Exception as e:
        errs.append(repr(e))
    finally:
        c.close()
ts = [threading.Thread(target=run) for _ in range(2)]
[t.start() for t in ts]
[t.join() for t in ts]
print('errs', errs)""")
check("errs []" in out, "two parallel runs without an error " + out[-600:])
rt = [x for x in rtasks() if x[2] == 0 and x[3] is None]
check(len(rt) == 1, f"two parallel runs: exactly one new task {rtasks()}")

# the watchdog: the list empties -> the task is done by itself
for t in A.get(B + NR).json()["items"]:
    if not t["locked"]:
        A.post(B + f"{K}/tx/{t['id']}/match", json={"kind": "noreceipt"})
left = A.get(B + NR + "/count").json()["out"]
if left:
    check(until(lambda: (sql("SELECT title FROM tasks WHERE id=?", (rt[0][0],)) or [[""]])[0][0] == TITLE(left), 40), "watchdog: the title follows the count")
else:
    check(until(lambda: sql("SELECT status FROM tasks WHERE id=?", (rt[0][0],))[0][0] == 2, 40), "watchdog: the task is done once the list is empty")
r = A.put(B + NR + "/reminder", json={"every": "off"})
check(r.ok and r.json()["task"] is None and all(x[2] == 2 and x[3] is None for x in rtasks()), f"off: the open task done, never deleted {rtasks()}")
A.put(B + O + "/settings", json={"bank_norc": {"every": "week", "user": ALICE}})
check(A.get(B + NR + "/reminder").json()["every"] == "off", "the general settings route ignores bank_norc")

# ---------------------------------------------------------------- a person without organisation (personal office)
# freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.put(B + O + "/settings", json={"company_fields": {"name": "Frida Film", "street": "Weg 3", "zip": "10115", "city": "Berlin", "country": "DE"}})
imp(Fr, camt("DE12500105170648489890", d(1), [ntry("23.80", "DBIT", d(2), "F-1", "Software Beispiel GmbH"), ntry("2.00", "DBIT", d(1), "F-2", "Beispielbank Entgelt")]), "f.xml")
j = Fr.get(B + NR).json()
check(len(j["items"]) == 2 and j["upload_ws"] == "private" and j["accounts"] == [], f"freelancer: own list, private documents space {j}")
fee = next(t for t in j["items"] if t["counterpart"] == "Beispielbank Entgelt")
check(Fr.post(B + f"{K}/tx/{fee['id']}/match", json={"kind": "noreceipt"}).ok and Fr.get(B + NR + "/count").json()["out"] == 1, "freelancer: noreceipt")
r = Fr.put(B + NR + "/reminder", json={"every": "month"})
check(r.ok and r.json()["user"] == FID and [p["id"] for p in r.json()["people"]] == [FID], "freelancer: the reminder goes to themself " + r.text[:200])
check(Fr.put(B + NR + "/reminder", json={"user": ALICE}).status_code == 400, "freelancer: nobody else as responsible")
check(len(rtasks(FID)) == 1, "freelancer: one task in the own inbox")
check(A.get(B + NR).json()["counts"]["out"] == left, "freelancer's bookings never reach the organisation")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
