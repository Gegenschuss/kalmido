#!/usr/bin/env python3
"""2.269.0 D (#3046) API tests: nothing twice when a request is sent again (double press, a lost answer, two tabs), own
container (start.sh through kt.fresh, SMTP to the stub of tests/stub_mail.py). Invented companies, people and figures only.
tenant-matrix: office  freelancer-matrix: office
 - payments: the same client_ref twice = one payment (the second answer 200, the invoice unchanged), also two requests at
   the same moment; another ref = a second payment; the ref on another invoice 409; without a ref as before (two payments)
 - new documents: a copy (duplicate), the invoice from a quotation, the credit note, the delivery note and a new
   document with the same client_ref twice = one document (200 the first one); without a ref two
 - the mail: a refused mail (no mail server yet) is 409 and marks nothing (status, sent_at stay); with the server it is
   sent once and marked
 - the cash book: an entry with the same client_ref twice = one entry (one number)
 - imports: fixed costs, trips and the legacy services sent twice = once (skipped counted); a row the preview found and
   the person ticked on purpose (dup_ok / dup) is taken
 - a person without an organisation (personal office) does all of it the same way
usage: p2269_d_idempotency_test.py <datadir>"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import timedelta

import kt
from kt import B, CT, DATA, H, check, sess, today
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
O = "/api/office"
D = O + "/docs"
FEAT = "cal,comments,collab,office,clients,travel"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "email": "hallo@beispiel.example",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
DAY = [(today() - timedelta(days=n)).isoformat() for n in range(0, 40)]

kt.fresh(env={"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
              "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2269D")
import requests  # noqa: E402
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"workspace": "private"})


def mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8")]
    except OSError:
        return []


def setup_office(s, tag):
    r = s.put(B + O + "/settings", json={"company_fields": COMPANY})
    assert r.ok, r.text
    r = s.post(B + "/api/clients", json={"name": f"Kunde {tag} GmbH", "street": "Weg 2", "zip": "10115", "city": "Berlin", "country": "DE",
                                         "email": f"kunde-{tag.lower()}@example.com"})
    assert r.ok, r.text
    return r.json()["id"]


def invoice(s, cl, rate=100):
    r = s.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": DAY[30], "items": [{"title": "Schnitt", "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    r = s.post(B + f"{D}/{did}/finalize")
    assert r.ok, r.text
    return did


def pays(s, did):
    return s.get(B + f"{D}/{did}/payments").json()["payments"]


def count_docs(s, kind):
    return len(s.get(B + f"{D}?kind={kind}").json().get("docs") or [])


for who, s in (("org", A), ("freelancer", Fr)):
    CL = setup_office(s, who.title())
    # ---------------------------------------------------------------- payments
    I1 = invoice(s, CL, 300)
    if who == "org":
        I1_ORG = I1
    r1 = s.post(B + f"{D}/{I1}/payments", json={"date": DAY[1], "amount": "50", "client_ref": f"pay-{who}-1"})
    r2 = s.post(B + f"{D}/{I1}/payments", json={"date": DAY[1], "amount": "50", "client_ref": f"pay-{who}-1"})
    check(r1.status_code == 201 and r2.status_code == 200 and len(pays(s, I1)) == 1,
          f"{who}: the same client_ref twice = one payment {r1.status_code} {r2.status_code} {len(pays(s, I1))}")
    check("client_ref" not in pays(s, I1)[0], f"{who}: the payment's client_ref is not handed out")
    res = []

    def go(ref=f"pay-{who}-par"):
        res.append(s.post(B + f"{D}/{I1}/payments", json={"date": DAY[1], "amount": "20", "client_ref": ref}).status_code)
    th = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in th]
    [t.join() for t in th]
    check(sorted(res) == [200, 200, 200, 201] and len(pays(s, I1)) == 2, f"{who}: four parallel requests with one ref = one payment {res} {len(pays(s, I1))}")
    r = s.post(B + f"{D}/{I1}/payments", json={"date": DAY[1], "amount": "10", "client_ref": f"pay-{who}-2"})
    check(r.status_code == 201 and len(pays(s, I1)) == 3, f"{who}: another ref = another payment")
    I2 = invoice(s, CL, 80)
    r = s.post(B + f"{D}/{I2}/payments", json={"date": DAY[1], "amount": "10", "client_ref": f"pay-{who}-2"})
    check(r.status_code == 409 and not pays(s, I2), f"{who}: a ref of another invoice 409 {r.status_code}")
    s.post(B + f"{D}/{I2}/payments", json={"date": DAY[1], "amount": "10"})
    s.post(B + f"{D}/{I2}/payments", json={"date": DAY[1], "amount": "10"})
    check(len(pays(s, I2)) == 2, f"{who}: without a ref as before (two payments)")
    # a retry after the full payment: no 409 "only open invoices"
    I3 = invoice(s, CL, 50)
    g = s.get(B + f"{D}/{I3}").json()["totals"]["gross"]
    r1 = s.post(B + f"{D}/{I3}/payments", json={"date": DAY[1], "amount": g, "client_ref": f"pay-{who}-full"})
    r2 = s.post(B + f"{D}/{I3}/payments", json={"date": DAY[1], "amount": g, "client_ref": f"pay-{who}-full"})
    check(r1.status_code == 201 and r2.status_code == 200 and r2.json().get("state") == "paid" and len(pays(s, I3)) == 1,
          f"{who}: sent again after the full payment = 200 the paid invoice {r1.status_code} {r2.status_code} {r2.text[:200]}")

    # ---------------------------------------------------------------- new documents
    n0 = count_docs(s, "invoice")
    r1 = s.post(B + f"{D}/{I2}/duplicate", json={"client_ref": f"dup-{who}"})
    r2 = s.post(B + f"{D}/{I2}/duplicate", json={"client_ref": f"dup-{who}"})
    check(r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"] and count_docs(s, "invoice") == n0 + 1,
          f"{who}: duplicate twice with one ref = one copy {r1.status_code} {r2.status_code}")
    r3 = s.post(B + f"{D}/{r1.json()['id']}/duplicate", json={"client_ref": f"dup2-{who}"})
    check(r3.status_code == 201 and r3.json()["id"] != r1.json()["id"], f"{who}: a copy of the copy (the ref is not copied along) {r3.status_code} {r3.text[:200]}")
    s.post(B + f"{D}/{I2}/duplicate")
    s.post(B + f"{D}/{I2}/duplicate")
    check(count_docs(s, "invoice") == n0 + 4, f"{who}: duplicate without a ref = two copies as before")
    r = s.post(B + D, json={"client_id": CL, "project_title": "Imagefilm", "items": [{"title": "Dreh", "qty": 1, "rate": 900}], "client_ref": f"new-{who}"})
    OF = r.json()["id"]
    r2 = s.post(B + D, json={"client_id": CL, "project_title": "Imagefilm", "items": [{"title": "Dreh", "qty": 1, "rate": 900}], "client_ref": f"new-{who}"})
    check(r.status_code == 201 and r2.status_code == 200 and r2.json()["id"] == OF, f"{who}: a new quotation twice with one ref = one {r.status_code} {r2.status_code}")
    n0 = count_docs(s, "invoice")
    r1 = s.post(B + f"{D}/{OF}/invoice", json={"client_ref": f"inv-{who}"})
    r2 = s.post(B + f"{D}/{OF}/invoice", json={"client_ref": f"inv-{who}"})
    check(r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"] and count_docs(s, "invoice") == n0 + 1,
          f"{who}: invoice from the quotation twice = one {r1.status_code} {r2.status_code} {r1.text[:200]}")
    r1 = s.post(B + f"{D}/{OF}/delivery", json={"title": "delivery", "client_ref": f"ls-{who}"})
    r2 = s.post(B + f"{D}/{OF}/delivery", json={"title": "delivery", "client_ref": f"ls-{who}"})
    check(r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"], f"{who}: delivery note twice = one {r1.status_code} {r2.status_code}")
    n0 = count_docs(s, "credit")
    r1 = s.post(B + f"{D}/{I1}/credit", json={"client_ref": f"cr-{who}"})
    r2 = s.post(B + f"{D}/{I1}/credit", json={"client_ref": f"cr-{who}"})
    check(r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"] and count_docs(s, "credit") == n0 + 1,
          f"{who}: credit note twice = one {r1.status_code} {r2.status_code} {r1.text[:200]}")
    res = []

    def dup_par():
        res.append(s.post(B + f"{D}/{I3}/duplicate", json={"client_ref": f"dup-par-{who}"}).json().get("id"))
    th = [threading.Thread(target=dup_par) for _ in range(3)]
    [t.start() for t in th]
    [t.join() for t in th]
    check(len(set(res)) == 1 and res[0], f"{who}: three parallel copies with one ref = one {res}")

    # ---------------------------------------------------------------- imports
    items = [{"label": f"Miete {who}", "amount": "800", "repeat": "monthly", "start": DAY[35][:8] + "01"}]
    r1 = s.post(B + O + "/fixed-costs/import", json={"items": items})
    r2 = s.post(B + O + "/fixed-costs/import", json={"items": items})
    check(r1.status_code == 201 and r1.json()["created"] == 1 and r2.status_code == 201 and r2.json()["created"] == 0 and r2.json()["skipped"] == 1,
          f"{who}: fixed costs imported twice = once {r1.text[:200]} {r2.text[:200]}")
    r3 = s.post(B + O + "/fixed-costs/import", json={"items": [{**items[0], "dup_ok": 1}]})
    check(r3.status_code == 201 and r3.json()["created"] == 1, f"{who}: a found row ticked on purpose (dup_ok) is taken {r3.text[:200]}")
    trips = [{"date_from": DAY[20], "date_to": DAY[20], "dest": "Koeln", "people": [{"name": "Rita Reise"}], "purpose": "job", "project": "Dreh"}]
    r1 = s.post(B + O + "/trips/import", json={"trips": trips})
    r2 = s.post(B + O + "/trips/import", json={"trips": trips})
    check(r1.status_code == 201 and r1.json()["created"] == 1 and r2.status_code == 201 and r2.json()["created"] == 0 and r2.json()["skipped"] == 1,
          f"{who}: trips imported twice = once {r1.text[:200]} {r2.text[:200]}")
    r3 = s.post(B + O + "/trips/import", json={"trips": [{**trips[0], "dup_ok": 1}]})
    check(r3.status_code == 201 and r3.json()["created"] == 1, f"{who}: a found trip ticked on purpose is taken {r3.text[:200]}")
    sv = [{"name_de": f"Kamera {who}", "daily_rate": 500, "action": "new"}]
    r1 = s.post(B + O + "/legacy/import", json={"services": sv})
    r2 = s.post(B + O + "/legacy/import", json={"services": sv})
    check(r1.status_code == 201 and r1.json()["counts"]["services"] == 1 and r2.status_code == 201 and r2.json()["counts"]["services"] == 0
          and r2.json()["counts"]["skipped"] == 1, f"{who}: legacy services imported twice = once {r1.text[:200]} {r2.text[:200]}")
    cl = [{"row": 2, "name": f"Altkunde {who} GmbH", "zip": "20095", "city": "Hamburg", "action": "new"}]
    r1 = s.post(B + O + "/legacy/import", json={"clients": cl})
    r2 = s.post(B + O + "/legacy/import", json={"clients": cl})
    r3 = s.post(B + O + "/legacy/import", json={"clients": [{**cl[0], "dup_ok": 1}]})
    check(r1.json()["counts"]["clients"] == 1 and r2.json()["counts"]["clients"] == 0 and r3.json()["counts"]["clients"] == 1,
          f"{who}: legacy clients twice = once, dup_ok = on purpose {r1.text[:150]} {r2.text[:150]} {r3.text[:150]}")

    # ---------------------------------------------------------------- the cash book
    j = s.get(B + O + "/cashbooks").json()
    CBK = j["books"][0]["id"]
    e = {"day": j["today"], "dir": "in", "amount": "15", "text": "Kiosk", "vat_pct": "7", "client_ref": f"cb-{who}"}
    r1 = s.post(B + O + f"/cashbooks/{CBK}/entries", json=e)
    r2 = s.post(B + O + f"/cashbooks/{CBK}/entries", json=e)
    check(r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"] and r1.json()["no"] == r2.json()["no"]
          and "client_ref" not in r2.json(), f"{who}: a cash book entry twice with one ref = one number {r1.status_code} {r2.status_code} {r1.text[:200]}")
    r3 = s.post(B + O + f"/cashbooks/{CBK}/entries", json={**e, "client_ref": f"cb2-{who}"})
    check(r3.status_code == 201 and r3.json()["no"] == r1.json()["no"] + 1, f"{who}: another ref = the next number {r3.text[:200]}")

    # ---------------------------------------------------------------- the mail after the commit
    I4 = invoice(s, CL, 120)
    if who == "org":
        r = s.post(B + f"{D}/{I4}/send", json={"to": "kunde@example.com"})
        d = s.get(B + f"{D}/{I4}").json()
        check(r.status_code == 409 and d["status"] == "issued" and not d.get("sent_at"),
              f"a refused mail (no mail server): 409 and nothing marked sent {r.status_code} {d.get('status')} {d.get('sent_at')}")
        shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
        subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
        kt.until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1025), 1)"],
                                        capture_output=True).returncode == 0, 15)
    m0 = len(mails())
    r = s.post(B + f"{D}/{I4}/send", json={"to": "kunde@example.com"})
    d = s.get(B + f"{D}/{I4}").json()
    check(r.ok and d["status"] == "sent" and d.get("sent_at") and len(mails()) == m0 + 1 and not r.json().get("datev_error"),
          f"{who}: sent once and marked {r.status_code} {r.text[:200]} {d.get('status')} {len(mails()) - m0}")

# ---------------------------------------------------------------- the other area sees nothing of the refs
r = Fr.post(B + f"{D}/{I1_ORG}/payments", json={"date": DAY[1], "amount": "1", "client_ref": "pay-org-1"})
check(r.status_code in (403, 404), f"the freelancer: an invoice of the organisation 403/404 {r.status_code}")
sys.exit(kt.done("p2269_d_idempotency"))
