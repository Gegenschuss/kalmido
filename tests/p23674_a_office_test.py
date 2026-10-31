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
I2, I3 = invoice(A, CL, overdue=2), invoice(A, CL, overdue=2)
I4 = invoice(A, CL, overdue=2)
assert A.post(B + f"{D}/{I4}/payments", json={"amount": "595.00", "date": date.today().isoformat()}).ok
dbx("UPDATE office_docs SET trial=1 WHERE id=?", (I3,))
I5 = invoice(A, CL, overdue=2)
tick()
n = news(A, "docoverdue")
check(len(n) == 2 and n[0]["data"]["n"] == 2 and n[0]["data"]["click"] == "#office/invoices", f"one item for a run: paid and trial invoices do not count {n}")
assert A.put(B + O + "/settings", json={"overdue_notice": 0}).ok
check('"overdue_notice": 0' in A.get(B + O + "/settings").text.replace('"overdue_notice":0', '"overdue_notice": 0'), "the switch is stored")
invoice(A, CL, overdue=2)
tick()
check(len(news(A, "docoverdue")) == 2, "switched off: nothing")
assert A.put(B + O + "/settings", json={"overdue_notice": 1}).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": BOB, "role": "member"}).ok
check(not news(Bo, "docoverdue"), "no office admin any more: the items are gone")
assert A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": BOB, "role": "admin"}).ok

# ================================================================== invoice series
Q = A.post(B + D, json={"client_id": CL, "project_title": "Retainer"}).json()["id"]
A.put(B + f"{D}/{Q}/items", json={"items": [{"kind": "service", "title": "Care", "qty": 1, "unit": "flat", "rate": 500}]})
TPL = A.post(B + f"{D}/{Q}/invoice", json={}).json()["id"]
GONE = A.post(B + "/api/users", json={"username": "gone", "display_name": "Gone", "password": "password123", "orgs": []}).json()["id"]


def series(title):
    r = A.post(B + O + "/series", json={"template_id": TPL, "every": "monthly", "start": date.today().isoformat(), "auto_send": False, "title": title})
    check(r.status_code == 201, f"setup: a series {r.text[:200]}")
    dbx("UPDATE office_inv_series SET created_by=? WHERE id=?", (GONE, r.json()["id"]))  # its creator left: every admin hears of it


series("Serie Eins")
series("Serie Zwei")
series("Serie Drei")
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
done("p23674_a_office")
