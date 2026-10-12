#!/usr/bin/env python3
"""2.39.1 API tests, part R: the rest of the office audit (#1210), own container in mode workspaces (start.sh) with the
SMTP sink of stub_mail.py. Invented companies, people and the test IBAN only.
 - N2: a manual invoice number is checked and written under one lock per organisation (two parallel requests for the same
   number: one 200, one 400, never a 500); more than one above the counter (a gap) only with a reason, kept in the log
 - N3: only the organisation's admins record payments and set or leave "paid" by hand (members 403)
 - N5: office_doc_items.org_id is NOT NULL after the start (every position carries its organisation). The way back
   (2.39.0 code on a database with the constraint: documents, positions, copies, invoice from a quotation) was checked by
   hand on the build host; 2.39.0 sets org_id on every insert since 2.36.2.
 - N7: mails with an own text: at most 50 per organisation and day; members past it get 429, the standard text still
   goes, admins count but are not limited; the log marks own texts
 - N8: a restore creates office/ and office/<org>/ with 0700 and the files with 0600; at the start folders of older
   versions (0755) become 0700
usage: p2391_r_api_test.py <datadir>"""
import datetime
import os
import subprocess
import sys
import threading
import time

import dbx as dbxm
import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
TEST_IBAN = "DE02120300000000202051"
MAILENV = ["-e", "KALMIDO_INSTANCE_MODE=workspaces", "-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025",
           "-e", "KALMIDO_SMTP_TLS=none", "-e", "KALMIDO_MAIL_FROM=kalmido@example.test"]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def wait_for(fn, t=10.0):
    end = time.time() + t
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.4)
    return fn()


def start(keep=False):
    if not keep:
        subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
        subprocess.run(["rm", "-rf", DATA])
        os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
        subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    else:
        subprocess.run(["docker", "stop", CT], capture_output=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)


def mode(path):
    r = subprocess.run(["docker", "exec", CT, "stat", "-c", "%a", path], capture_output=True, text=True)
    return r.stdout.strip()


start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo = sess("bob")
FEAT = "cal,comments,collab,office,clients"
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
O = "/api/office"
D = O + "/docs"
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht GmbH"}, "lang": "de", "currency": "EUR",
                                     "company_fields": {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                        "country": "DE", "email": "hallo@nordlicht.example", "tax_number": "12/345/67890",
                                                        "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}, "payment_days": 14})
check(r.ok, "office settings with company data " + r.text[:160])
r = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"})
assert r.status_code == 201, r.text
CL = r.json()["id"]
Y = datetime.date.today().year


def draft(s=A):
    r = s.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": f"{Y}-01-05", "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------- N5: positions always carry their organisation
I1 = draft()
nul = dbx("SELECT is_nullable FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='office_doc_items' AND column_name='org_id'")
check(nul and nul[0][0] == "NO", f"N5: office_doc_items.org_id is NOT NULL {nul}")
check(dbx("SELECT COUNT(*) FROM office_doc_items WHERE org_id IS NULL")[0][0] == 0, "N5: no position without organisation")

# ---------------------------------------------------------------- N2: manual numbers
r = A.post(B + f"{D}/{I1}/number", json={"number": f"RE-{Y}-001"})
check(r.ok and r.json()["number"] == f"RE-{Y}-001", "N2: the next number by hand needs no reason " + r.text[:120])
r = A.post(B + f"{D}/{I1}/finalize")
check(r.ok and r.json()["number"] == f"RE-{Y}-001", "finalised with the manual number " + r.text[:120])
I2 = draft()
r = A.post(B + f"{D}/{I2}/number", json={"number": f"RE-{Y}-005"})
check(r.status_code == 400 and "reason" in r.json().get("error", "") and "3" in r.json().get("error", ""), "N2: a gap of 3 numbers without a reason: 400 " + r.text[:160])
r = A.post(B + f"{D}/{I2}/number", json={"number": f"RE-{Y}-005", "reason": "abc"})
check(r.status_code == 400, "N2: a too short reason: 400")
r = Bo.post(B + f"{D}/{I2}/number", json={"number": f"RE-{Y}-005", "reason": "Nummern 2 bis 4 im Altprogramm vergeben"})
check(r.ok and r.json()["number"] == f"RE-{Y}-005", "N2: with a reason the gap is accepted " + r.text[:120])
lg = dbx("SELECT detail FROM office_doc_log WHERE action='number' AND doc_id=? ORDER BY id DESC LIMIT 1", (I2,))
check(lg and "Altprogramm" in lg[0][0], f"N2: the reason is in the office log {lg}")
# two parallel requests for the same next number: one wins, the other gets a readable 400 (no 500 from the unique index)
I3, I4 = draft(), draft()
res = {}


def put_num(did):
    res[did] = A.post(B + f"{D}/{did}/number", json={"number": f"RE-{Y}-006"}).status_code


ths = [threading.Thread(target=put_num, args=(d,)) for d in (I3, I4)]
for t in ths:
    t.start()
for t in ths:
    t.join()
check(sorted(res.values()) == [200, 400], f"N2: parallel manual numbers: one 200, one 400 {res}")
# the automatic number continues after the manual ones (same lock)
r = A.post(B + f"{D}/{I3 if res[I3] == 400 else I4}/finalize")
check(r.ok and r.json()["number"] == f"RE-{Y}-007", "N2: finalising takes the next number after the manual ones " + r.text[:120])

# ---------------------------------------------------------------- N3: payments and paid by admins only
check(Bo.post(B + f"{D}/{I1}/payments", json={"amount": 50}).status_code == 403, "N3: member records a payment: 403")
check(Bo.post(B + f"{D}/{I1}/status", json={"status": "paid"}).status_code == 403, "N3: member sets paid: 403")
r = A.post(B + f"{D}/{I1}/payments", json={"amount": 50})
check(r.status_code == 201 and r.json()["state"] == "partial", "N3: admin records a part payment " + r.text[:120])
r = Bo.post(B + f"{D}/{I1}/status", json={"status": "sent"})
check(r.ok, "N3: member may still set sent " + r.text[:120])
I5 = draft()
A.post(B + f"{D}/{I5}/finalize")
r = A.post(B + f"{D}/{I5}/status", json={"status": "paid"})
check(r.ok and r.json()["status"] == "paid", "N3: admin sets paid by hand " + r.text[:120])
check(Bo.post(B + f"{D}/{I5}/status", json={"status": "sent"}).status_code == 403, "N3: member takes paid back: 403")
check(Bo.get(B + f"{D}/{I5}/payments").ok, "N3: member still reads the payments")

# ---------------------------------------------------------------- N7: own texts per organisation and day
r = Bo.post(B + f"{D}/{I1}/send", json={"to": "kunde@example.com", "text": "Hallo, anbei die Rechnung. Gruß Bob", "datev": False})
check(r.ok, "N7: member sends with an own text " + r.text[:160])
lg = dbx("SELECT detail FROM office_doc_log WHERE action='send' AND doc_id=? ORDER BY id DESC LIMIT 1", (I1,))
check(lg and '"own_text": 1' in lg[0][0], f"N7: the log marks the own text {lg}")
now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
for _ in range(49):
    dbxm.connect(os.path.join(DATA, "tasks.db")).execute("INSERT INTO office_doc_log(org_id, doc_id, user_id, at, action, target, detail) VALUES(?,?,?,?,?,?,?)",
                                                         (ORG, I1, ALICE, now, "send", "doc", '{"to": "x@example.com", "own_text": 1}'))
r = Bo.post(B + f"{D}/{I1}/send", json={"to": "kunde@example.com", "text": "Noch eine eigene Nachricht", "datev": False})
check(r.status_code == 429 and "50" in r.json().get("error", ""), "N7: the 51st own text of a member: 429 " + r.text[:160])
r = Bo.post(B + f"{D}/{I1}/send", json={"to": "kunde@example.com", "datev": False})
check(r.ok, "N7: the standard text still goes " + r.text[:120])
r = A.post(B + f"{D}/{I1}/send", json={"to": "kunde@example.com", "text": "Eigene Nachricht der Chefin", "datev": False})
check(r.ok, "N7: the admin is not limited " + r.text[:120])
out = os.path.join(DATA, "mail", "out.jsonl")
check(os.path.exists(out) and len(open(out, encoding="utf-8").read().splitlines()) == 3, "N7: three mails went out (not the refused one)")

# ---------------------------------------------------------------- N8: rights of the office folders
check(mode(f"/data/office/{ORG}") == "700", "N8: the organisation folder of the PDFs is 0700 " + mode(f"/data/office/{ORG}"))
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, "backup: back up now " + r.text[:100])
items = wait_for(lambda: [x for x in A.get(B + "/api/admin/backups").json().get("items", []) if x["kind"] == "manual"], 30)
name = items[0]["name"] if items else ""
r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "name": name})
check(r.ok and r.json().get("ok"), "backup: restore " + r.text[:200])
time.sleep(1)
files = subprocess.run(["docker", "exec", CT, "sh", "-c", f"ls /data/office/{ORG}"], capture_output=True, text=True).stdout.split()
pdf = next((f for f in files if f.endswith(".pdf")), "")
check(mode("/data/office") == "700" and mode(f"/data/office/{ORG}") == "700", f"N8: after the restore office/ and office/<org>/ are 0700: {mode('/data/office')} {mode(f'/data/office/{ORG}')}")
check(pdf and mode(f"/data/office/{ORG}/{pdf}") == "600", f"N8: restored files are 0600 ({pdf}: {mode(f'/data/office/{ORG}/{pdf}') if pdf else '-'})")
# folders of older versions: 0755 -> 0700 at the next start
subprocess.run(["docker", "exec", CT, "sh", "-c", f"chmod 755 /data/office /data/office/{ORG}"])
check(mode(f"/data/office/{ORG}") == "755", "N8: an old folder with 0755 (set up)")
start(keep=True)
check(mode("/data/office") == "700" and mode(f"/data/office/{ORG}") == "700", f"N8: after the start the folders are 0700 again: {mode('/data/office')} {mode(f'/data/office/{ORG}')}")
check(requests.get(B + "/api/health").ok, "the app runs after the restart")

print(f"p2391_r_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
