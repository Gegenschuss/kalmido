#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.367.4 (#2972): the office speaks up. Invented companies, people and figures only.
freelancer-matrix: office
 - a payment on an invoice: News for the office's other admins (number, client, no amount), none for the one who booked it
 - an overdue invoice: News once per invoice for the office's people, also with dunning_suggest off; several in one run = one
   item with the count; overdue_notice 0 = nothing; paid and trial invoices never; a person who left the office no longer sees it
 - invoice series: one task per person and day however many series need them; a done task starts a new one
 - the portal link goes out in the language of the client's newest document
 - a person without an organisation: the bell of the own personal office, nothing for the own payment
usage: p23674_a_office_test.py <datadir>"""
import email
import email.policy
import json
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, DATA, check, dbx, done, fresh, sess, setup, until  # noqa: E402

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
O = "/api/office"
D = O + "/docs"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "email": "hallo@beispiel.example",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def in_ct(code):
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def tick(mod="dunning", last="_DUN_LAST", fn="dun_tick"):
    in_ct(f"import app\nfrom kalmido.core.db import connect\nfrom kalmido.office import {mod} as x\nx.{last}['at'] = -1e12\nc = connect()\nx.{fn}(c)\nc.close()")


def series_tick():
    tick("recurring", "_RIN_LAST", "rin_tick")


def news(s, kind):
    return [x for x in s.get(B + "/api/news").json()["items"] if x["kind"] == kind]


def mails(to):
    try:
        rows = [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []
    return [m for m in rows if to in json.dumps(m["to"])]


def client(s, name, **kw):
    r = s.post(B + "/api/clients", json={"name": name, "street": "Marktweg 5", "zip": "50667", "city": "Koeln", "country": "DE", **kw})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def invoice(s, cl, lang="de", overdue=None):
    r = s.post(B + D, json={"kind": "invoice", "lang": lang, "client_id": cl, "project_title": "Schnitt", "service_from": "2026-05-01",
                            "items": [{"title": "Schnitt", "qty": 1, "rate": 500}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    f = s.post(B + f"{D}/{did}/finalize")
    assert f.ok, f.text
    if overdue:
        dbx("UPDATE office_docs SET due_date=? WHERE id=?", ((date.today() - timedelta(days=overdue)).isoformat(), did))
    return did


fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025",
       "KALMIDO_SMTP_TLS": "none", "KALMIDO_MAIL_FROM": "kalmido@example.test"})
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
A = setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"}).json()["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "admin"}).ok
Bo = sess("bob")
for s in (A, Bo):
    assert s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done", "workspace": f"org:{ORG}"}).ok
assert A.put(B + O + "/settings", json={"lang": "de", "dunning_suggest": 0, "company_fields": COMPANY}).ok
CL = client(A, "Muster Medien AG")

# ================================================================== a payment
INV = invoice(A, CL)
num = A.get(B + f"{D}/{INV}").json()["number"]
r = A.post(B + f"{D}/{INV}/payments", json={"amount": "100.00", "date": date.today().isoformat()})
check(r.status_code in (200, 201), f"setup: a part payment {r.status_code} {r.text[:200]}")
n = until(lambda: news(Bo, "docpaid"), 10)
check(len(n) == 1 and n[0]["data"]["number"] == num and n[0]["data"]["client"] == "Muster Medien AG", f"the other admin hears of the payment {n}")
check(not any(k in n[0]["data"] for k in ("amount", "total", "open")) and "100" not in json.dumps(n[0]["data"]).replace(num, ""), f"no amount {n[0]['data']}")
check(n[0]["data"]["click"] == f"#office/invoices/{INV}", "it opens the invoice")
check(not news(A, "docpaid"), "not the person who booked it")

# ================================================================== overdue
I1 = invoice(A, CL, overdue=3)
tick()
n = news(A, "docoverdue")
check(len(n) == 1 and n[0]["data"]["n"] == 1 and n[0]["data"]["client"] == "Muster Medien AG" and n[0]["data"]["click"] == f"#office/invoices/{I1}",
      f"an overdue invoice rings the bell with dunning_suggest off {n}")
check(len(news(Bo, "docoverdue")) == 1, "for every admin of the office")
check(not dbx("SELECT id FROM office_docs WHERE kind='reminder'"), "and suggests no reminder")
tick()
check(len(news(A, "docoverdue")) == 1, "only once per invoice")
I2, I3, I4, I5 = (invoice(A, CL) for _ in range(4))
assert A.post(B + f"{D}/{I4}/payments", json={"amount": "595.00", "date": date.today().isoformat()}).ok
dbx("UPDATE office_docs SET trial=1 WHERE id=?", (I3,))
# the server's own watchdog ticks too (every 10 s in the test container): all four fall due in ONE statement, so any tick sees them together
dbx("UPDATE office_docs SET due_date=? WHERE id IN (?,?,?,?)", ((date.today() - timedelta(days=2)).isoformat(), I2, I3, I4, I5))
tick()
# 2.641.0 (#5012): the watchdog's tick may be the one that tells (or still be committing): wait for the bundle item itself
# instead of taking n[0] (CI v2.632.0 found the old single item in front)
until(lambda: [x for x in news(A, "docoverdue") if x["data"]["click"] == "#office/invoices"], 30)
n = news(A, "docoverdue")
bundle = [x for x in n if x["data"]["click"] == "#office/invoices"]
check(len(n) == 2 and len(bundle) == 1 and bundle[0]["data"]["n"] == 2, f"one item for a run: paid and trial invoices do not count {n}")
assert A.put(B + O + "/settings", json={"overdue_notice": 0}).ok
check('"overdue_notice": 0' in A.get(B + O + "/settings").text.replace('"overdue_notice":0', '"overdue_notice": 0'), "the switch is stored")
invoice(A, CL, overdue=2)
tick()
check(len(news(A, "docoverdue")) == 2, "switched off: nothing")
assert A.put(B + O + "/settings", json={"overdue_notice": 1}).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": BOB, "role": "member"}).ok
check(not news(Bo, "docoverdue"), "no office admin any more: the items are gone")
assert A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": BOB, "role": "admin"}).ok

# 2.641.0 (#5012): two runs at once on the same invoices (the watchdog and another process) tell once. The second run reads
# the invoices, then the first one marks and commits them before the second one writes its marks: only the run whose marks
# went in reports. A day far ahead, so the server's own watchdog (today) never takes these invoices.
J = invoice(A, CL)
RACE = f"""import app, json
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.office import dunning as x, invoices as inv
c1, c2 = connect(), connect()
oid = c1.execute("SELECT org_id FROM office_docs WHERE id={J}").fetchone()[0]
c1.commit()
told, orig, held = [], inv.inv_paid_map, []
x.news_add = lambda c, p, kind, **kw: told.append(kw["data"]["n"])
def pm(c, o, ids):
    if c is c2 and not held:
        held.append(1)
        with system_ctx(c1):
            x.dun_overdue(c1, o, "2099-01-01", [0])
        c1.commit()
    return orig(c, o, ids)
inv.inv_paid_map = pm
with system_ctx(c2):
    x.dun_overdue(c2, oid, "2099-01-01", [0])
c2.commit()
print(json.dumps({{"told": told, "held": len(held)}}))
"""
r = subprocess.run(["docker", "exec", CT, "python3", "-c", RACE], capture_output=True, text=True, timeout=120)
assert r.returncode == 0, r.stdout + r.stderr
race = json.loads(r.stdout.strip().splitlines()[-1])
check(race["held"] == 1 and len(race["told"]) == 1 and race["told"][0] >= 1, f"two runs at once: one report {race}")
check(dbx("SELECT COUNT(*) FROM office_dunning_marks WHERE doc_id=? AND level=0", (J,))[0][0] == 1, "and one mark")

# ================================================================== invoice series
Q = A.post(B + D, json={"client_id": CL, "project_title": "Retainer"}).json()["id"]
A.put(B + f"{D}/{Q}/items", json={"items": [{"kind": "service", "title": "Care", "qty": 1, "unit": "flat", "rate": 500}]})
TPL = A.post(B + f"{D}/{Q}/invoice", json={}).json()["id"]
GONE = A.post(B + "/api/users", json={"username": "gone", "display_name": "Gone", "password": "password123", "orgs": []}).json()["id"]


def series(*titles):
    # 2.641.0 (#5012): made for tomorrow, then due today with the creator gone in ONE statement: the server's own watchdog
    # (every 10 s in the test container) never takes a series while its creator is still Alice (then only she hears of it)
    ids = []
    for title in titles:
        r = A.post(B + O + "/series", json={"template_id": TPL, "every": "monthly", "start": (date.today() + timedelta(days=1)).isoformat(),
                                            "auto_send": False, "title": title})
        check(r.status_code == 201, f"setup: a series {r.text[:200]}")
        ids.append(r.json()["id"])
    today = date.today().isoformat()
    dbx(f"UPDATE office_inv_series SET created_by=?, start=?, next_date=? WHERE id IN ({','.join('?' * len(ids))})", (GONE, today, today, *ids))  # its creator left: every admin hears of it


series("Serie Eins", "Serie Zwei", "Serie Drei")
series_tick()


def stasks(uid):
    return dbx("SELECT title, content, url FROM tasks WHERE created_by=? AND (title LIKE '%series%' OR content LIKE '%Serie %') AND completed_at IS NULL", (uid,))


t = stasks(ALICE)
check(len(t) == 1 and t[0][0] == "3 invoice series need you" and all(x in t[0][1] for x in ("Serie Eins", "Serie Zwei", "Serie Drei")) and t[0][2].endswith("#office/invoices"),
      f"three series, one task {t}")
t = stasks(BOB)
check(len(t) == 1 and t[0][0] == "3 invoice series need you", f"one for each admin, not one per series and admin {t}")
dbx("UPDATE tasks SET completed_at=? WHERE created_by=? AND title LIKE '%series%'", ("2026-01-01T00:00:00Z", ALICE))
series("Serie Vier")
series_tick()
t = stasks(ALICE)
check(len(t) == 1 and "Serie Vier" in t[0][0] and "3 invoice" not in t[0][0] and "/#office/offers/" in t[0][2], f"a done task: a new one with its own title and link {t}")

# 2.641.0 (#5012): two series runs at once tell one person: the second waits for the first one's commit and adds to its task
# (it read the person's open task before the first one wrote it and made a second task). Waits for the real state: the
# second connection blocked on a lock or done.
RACER = A.post(B + "/api/users", json={"username": "racer", "display_name": "Racer", "password": "password123", "orgs": []}).json()["id"]
RACE2 = f"""import app, json, threading, time
from kalmido.core.config import app as flask_app
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.office import recurring as x
c1, c2, c3 = connect(), connect(), connect()
from kalmido.core.access import my_inbox
with system_ctx(c1):
    my_inbox(c1, {RACER})  # the inbox exists before the race
c1.commit()
pid = c2.execute("SELECT pg_backend_pid()").fetchone()[0]
c2.commit()
def run(c, name):
    with flask_app.test_request_context("/"), system_ctx(c):
        x.rin_bundle(c, {RACER}, name, "Check the race draft", None)
run(c1, "Race series one")
t = threading.Thread(target=lambda: (run(c2, "Race series two"), c2.commit()))
t.start()
end = time.monotonic() + 20
while t.is_alive() and time.monotonic() < end and not c3.execute("SELECT 1 FROM pg_stat_activity WHERE pid=? AND wait_event_type='Lock'", (pid,)).fetchone():
    c3.commit()
    time.sleep(0.05)
c1.commit()
t.join(30)
with system_ctx(c3):
    rows = c3.execute("SELECT title FROM tasks WHERE created_by=? AND completed_at IS NULL AND deleted_at IS NULL", ({RACER},)).fetchall()
print(json.dumps([r[0] for r in rows]))
"""
r = subprocess.run(["docker", "exec", CT, "python3", "-c", RACE2], capture_output=True, text=True, timeout=120)
assert r.returncode == 0, r.stdout + r.stderr
race = json.loads(r.stdout.strip().splitlines()[-1])
check(len(race) == 1 and race[0].startswith("2 "), f"two series runs at once: one task for the person {race}")

# ================================================================== the portal link
CF = client(A, "Client Fr", email="client-fr@example.com")
assert A.put(B + O + "/settings", json={"portal_docs": 1}).ok
A.patch(B + "/api/admin/settings", json={"public_links": True})
invoice(A, CF, lang="fr")
r = A.post(B + f"{O}/clients/{CF}/portal-link", json={})
check(r.ok, f"setup: the portal link {r.status_code} {r.text[:200]}")
m = until(lambda: mails("client-fr@example.com"), 20)
sub = str(email.message_from_string(m[0]["raw"], policy=email.policy.default)["subject"]) if m else ""
check("documents" in sub.lower() and "Your" not in sub and "Dokumente" not in sub, f"French for a client with French documents, the office speaks German: {sub}")
# 2.460.0 (#3767): a language set on the client wins over its newest document
CN = client(A, "Client Nl", email="client-nl@example.com")
assert A.patch(B + f"/api/clients/{CN}", json={"doc_lang": "nl"}).ok
invoice(A, CN, lang="fr")
assert A.post(B + f"{O}/clients/{CN}/portal-link", json={}).ok
m = until(lambda: mails("client-nl@example.com"), 20)
sub = str(email.message_from_string(m[0]["raw"], policy=email.policy.default)["subject"]) if m else ""
check(sub and "Vos" not in sub and "Your" not in sub and "Dokumente" not in sub, f"Dutch for a client set to Dutch with a French document: {sub}")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
assert Fr.put(B + O + "/settings", json={"lang": "de", "dunning_suggest": 0, "company_fields": COMPANY}).ok
FC = client(Fr, "Eigenkunde GmbH")
FI = invoice(Fr, FC, overdue=4)
tick()
n = news(Fr, "docoverdue")
check(len(n) == 1 and n[0]["data"]["client"] == "Eigenkunde GmbH", f"the own personal office rings the bell {n}")
check(not news(A, "docoverdue") or all(x["data"].get("client") != "Eigenkunde GmbH" for x in news(A, "docoverdue")), "nobody else hears of it")
assert Fr.post(B + f"{D}/{FI}/payments", json={"amount": "10.00", "date": date.today().isoformat()}).ok
check(not news(Fr, "docpaid"), "the own booking stays quiet")
sys.exit(done("p23674_a_office"))
