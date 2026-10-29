#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.433.0 API tests (#3599): who an office document is sent to first. Own container with the SMTP sink of stub_mail.py,
once in the personal office of a person without an organisation (freelancer fixture; freelancer-matrix: office) and once
in an organisation's office (its admin). Invented companies, people and addresses only.
 - a contact person carries the mark "gets invoices" (saved, read back, kept when a later save leaves the key out)
 - GET /api/office/docs/<id>/recipients: an invoice goes to the e-mail for invoices with the contact persons for
   invoices in copy (none ticked: the default contact person); a quotation to the default contact person with the e-mail
   for invoices in copy; without an e-mail for invoices the client's e-mail; an address only once, empty ones left out
 - sending with several copy addresses (comma separated) reaches every one of them (RCPT, Cc header); a wrong one is 400
usage: p2433_send_rcpts_test.py <datadir>      (P2433S_NOSTART=1: a running server on KALMIDO_TEST_PORT with the SMTP sink)"""
import json
import os
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402
import requests  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
ENV = ["-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none", "-e", "KALMIDO_MAIL_FROM=kalmido@example.test"]
COMPANY = {"name": "Studio Nordlicht", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hallo@nordlicht.example", "tax_number": "12/345/67890", "vat_id": "DE999999999",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def mails():
    p = os.path.join(DATA, "mail", "out.jsonl")
    return [json.loads(x) for x in open(p, encoding="utf-8").read().splitlines()] if os.path.exists(p) else []


def start():
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(ENV)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    for _ in range(50):  # the sink is up once its port answers (never a fixed wait)
        if subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1025), 1)"],
                          capture_output=True).returncode == 0:
            break
        time.sleep(0.2)


if not os.environ.get("P2433S_NOSTART"):
    start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en"})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
A.patch(B + "/api/settings", json={"workspace": f"org:{r.json()['id']}"})
FID, Fr = freelancer(B, A)
ADDR = {"street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"}


def run(S, who, tag):
    def ok(cond, what):
        check(cond, f"{who}: {what}")

    r = S.put(B + O + "/settings", json={"company": {"name": COMPANY["name"]}, "lang": "de", "currency": "EUR", "payment_days": 14,
                                         "company_fields": COMPANY})
    ok(r.ok, "office settings " + r.text[:200])
    ok(S.get(B + O + "/mail-status").json().get("smtp"), "setup: the SMTP sink")
    m = lambda n: f"{n}.{tag}@kunde.example"  # noqa: E731 -- own addresses per run

    def client(**kw):
        r = S.post(B + "/api/clients", json=dict(ADDR, **kw))
        assert r.status_code == 201, r.text
        return r.json()

    def doc(kind, cl):
        b = {"kind": kind, "client_id": cl, "items": [{"title": "Schnitt", "qty": 1, "rate": 100, "unit": "piece"}]}
        if kind == "invoice":
            b.update(service_from="2026-10-01", service_to="2026-10-20")
        r = S.post(B + D, json=b)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def rc(did):
        return S.get(B + f"{D}/{did}/recipients").json()

    c1 = client(name="Beispielkunde AG", email=m("info"), email_invoice=m("rechnung"),
                contacts=[{"name": "Anna Projekt", "email": m("anna"), "is_default": True},
                          {"name": "Bert Buchhaltung", "email": m("bert"), "gets_invoices": True},
                          {"name": "Cora Chefin", "email": m("cora"), "gets_invoices": True},
                          {"name": "Dirk Ohne", "email": "", "gets_invoices": True}])
    ks = {k["name"]: k for k in S.get(B + f"/api/clients/{c1['id']}").json()["contacts"]}
    ok(ks["Bert Buchhaltung"]["gets_invoices"] and ks["Cora Chefin"]["gets_invoices"] and not ks["Anna Projekt"]["gets_invoices"],
       f"the mark 'gets invoices' is saved: {[(k, v['gets_invoices']) for k, v in ks.items()]}")
    # a save without the key keeps the marks (an older client, the client page's own fields)
    r = S.patch(B + f"/api/clients/{c1['id']}", json={"contacts": [{"id": k["id"], "name": k["name"], "email": k["email"], "is_default": k["is_default"]} for k in ks.values()]})
    ok(r.ok, "saved again without the key " + r.text[:120])
    ks = {k["name"]: k for k in S.get(B + f"/api/clients/{c1['id']}").json()["contacts"]}
    ok(ks["Bert Buchhaltung"]["gets_invoices"] and not ks["Anna Projekt"]["gets_invoices"], "the marks stay when the key is missing")

    inv = doc("invoice", c1["id"])
    j = rc(inv)
    ok(j.get("to") == m("rechnung") and j.get("cc") == [m("bert"), m("cora")], f"invoice: to the e-mail for invoices, the contact persons for invoices in copy: {j}")
    off = doc("offer", c1["id"])
    j = rc(off)
    ok(j.get("to") == m("anna") and j.get("cc") == [m("rechnung")], f"quotation: to the default contact person, the e-mail for invoices in copy: {j}")

    c2 = client(name="Zweitkunde GmbH", email=m("info2"), contacts=[{"name": "Dora Default", "email": m("dora"), "is_default": True}])
    j = rc(doc("invoice", c2["id"]))
    ok(j.get("to") == m("info2") and j.get("cc") == [m("dora")], f"no e-mail for invoices, nobody ticked: the client's e-mail, the default contact person in copy: {j}")
    j = rc(doc("offer", c2["id"]))
    ok(j.get("to") == m("dora") and j.get("cc") == [], f"quotation without an e-mail for invoices: no copy: {j}")
    c3 = client(name="Drittkunde KG", email_invoice=m("emil"), contacts=[{"name": "Emil Einer", "email": m("emil"), "is_default": True}])
    j = rc(doc("invoice", c3["id"]))
    ok(j.get("to") == m("emil") and j.get("cc") == [], f"an address only once: {j}")
    c4 = client(name="Leerkunde")
    j = rc(doc("invoice", c4["id"]))
    ok(j.get("to") == "" and j.get("cc") == [], f"empty fields stay empty: {j}")

    # sending with several copy addresses
    r = S.post(B + f"{D}/{inv}/finalize")
    ok(r.ok, "the invoice is finalised " + r.text[:160])
    r = S.post(B + f"{D}/{inv}/send", json={"to": m("rechnung"), "cc": f"{m('bert')}, kein-mail"})
    ok(r.status_code == 400, "a wrong copy address: 400 " + r.text[:120])
    n0 = len(mails())
    r = S.post(B + f"{D}/{inv}/send", json={"to": m("rechnung"), "cc": f"{m('bert')}, {m('cora')}, {m('bert')}"})
    ok(r.ok, "sent with two copy addresses " + r.text[:160])
    got = mails()[n0:]
    ok(len(got) == 1 and sorted(got[0]["to"]) == sorted([m("rechnung"), m("bert"), m("cora")]), f"every address gets the mail once: {[x['to'] for x in got]}")
    ok(got and f"{m('bert')}, {m('cora')}" in got[0]["raw"].replace("\r\n ", " "), "the Cc header names both")


run(Fr, "freelancer", "f")
run(A, "organisation", "o")
print(f"p2433_send_rcpts: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
