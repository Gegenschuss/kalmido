#!/usr/bin/env python3
# kalmido-suite:
"""2.370.2 (#3088): the rest of the conflict guard of the office. Own container, SMTP to tests/stub_mail.py once it runs.
Invented companies, people and figures only.
tenant-matrix: office  freelancer-matrix: office
 - comments: the same client_ref twice = one comment, also over the API (200 the second time), one deleted since gives it free
 - an agent's payment suggestion: the same client_ref twice = one suggestion, also once the invoice is paid
 - a refused mail hands the address counter back; a mail sent counts; marking that fails sends no mail (2.501.0, #4296)
 - a save without expect_updated_at names the positions that stayed (kept_ids)
 - a deleted document: the ref makes a new one; restoring the old one from the trash next to it works
 - time entries whose position goes away are open again, with their billed date gone; the rest of the invoice stays bound
 - budget categories: expect_updated_at, 409 with the current state
 - a person without an organisation does all of it the same way
usage: p2370_2_office_test.py <datadir>"""
import os
import shutil
import subprocess
import sys

import requests

import dbx as dbxm
import kt
from kt import B, CT, DATA, H, check, dbx, sess, today
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
O = "/api/office"
D = O + "/docs"
V = B + "/api/v1"
FEAT = "cal,comments,collab,office,clients,travel,budget"
COMPANY = {"name": "Beispiel Film GmbH", "street": "Musterweg 1", "zip": "12345", "city": "Musterstadt", "country": "DE", "email": "hallo@beispiel.example",
           "vat_id": "DE123456789", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
TODAY = today().isoformat()

kt.fresh(env={"KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
              "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P23702")
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
AID = A.get(B + "/api/state").json()["me"]["id"]
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "private"})


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute(q, args)
        c.commit()
    finally:
        c.close()


def invoice(s, cl, title="Schnitt"):
    r = s.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": TODAY, "items": [{"title": title, "qty": 1, "rate": 100}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert s.post(B + f"{D}/{did}/finalize").ok
    return did


def comments_case(s, who):
    lid = s.post(B + "/api/lists", json={"name": f"Kommentare {who}"}).json()["id"]
    tid = s.post(B + "/api/tasks", json={"title": "Aufgabe", "list_id": lid}).json()["id"]
    u = B + f"/api/tasks/{tid}/comments"
    r1 = s.post(u, json={"body": "Erster", "client_ref": f"c-{who}"})
    r2 = s.post(u, json={"body": "Erster", "client_ref": f"c-{who}"})
    check(r1.ok and r2.ok and r1.json()["id"] == r2.json()["id"], f"{who}: sent again = the same comment {r1.text[:120]} {r2.text[:120]}")
    # 2.972.0 (#5272): the task comments are rows of the core's obj_comments (kind 'task', ref_id = the task)
    n = len(dbx("SELECT id FROM obj_comments WHERE kind='task' AND ref_id=?", (tid,)))
    check(n == 1, f"{who}: one comment in the task: {n}")
    check("client_ref" not in r2.json(), f"{who}: the ref stays on the server")
    r = s.post(u, data={"body": "Mit Formular", "client_ref": f"f-{who}"}, headers={"Content-Type": None})
    r2 = s.post(u, data={"body": "Mit Formular", "client_ref": f"f-{who}"}, headers={"Content-Type": None})
    check(r.ok and r2.ok and r.json()["id"] == r2.json()["id"], f"{who}: the form too {r.text[:120]}")
    s.delete(B + f"/api/comments/{r1.json()['id']}")
    r3 = s.post(u, json={"body": "Erster", "client_ref": f"c-{who}"})
    check(r3.ok and r3.json()["id"] != r1.json()["id"], f"{who}: a deleted comment gives its ref free {r3.text[:120]}")
    r4 = s.post(u, json={"body": "Ohne"})
    r5 = s.post(u, json={"body": "Ohne"})
    check(r4.json()["id"] != r5.json()["id"], f"{who}: without a ref two comments")
    return tid


def agent_case(s, who, hd, tid, cl):
    r = requests.post(V + f"/tasks/{tid}/comments", headers=hd, json={"body": "Vom Agenten", "client_ref": f"ac-{who}"})
    r2 = requests.post(V + f"/tasks/{tid}/comments", headers=hd, json={"body": "Vom Agenten", "client_ref": f"ac-{who}"})
    check(r.status_code == 201 and r2.status_code == 200 and r.json()["id"] == r2.json()["id"], f"{who}: API comment 201, sent again 200 {r.status_code} {r2.status_code} {r.text[:160]}")
    r = requests.post(V + f"/tasks/{tid}/comments", headers=hd, json={"body": "x", "client_ref": 5})
    check(r.status_code == 400, f"{who}: a client_ref that is no text 400 {r.status_code}")
    # the agent's draft + a person's finalising: the invoice is shared with the agent
    r = requests.post(V + "/office/offers", headers=hd, json={"client_id": cl, "title": "Film", "items": [{"text": "Kamera", "qty": 1, "unit": "day", "price": 100}]})
    assert r.status_code == 201, r.text
    q = r.json()["doc"]["id"]
    assert s.post(B + f"{D}/{q}/finalize").ok
    assert s.post(B + f"{D}/{q}/status", json={"status": "sent"}).ok
    assert s.post(B + f"{D}/{q}/status", json={"status": "accepted"}).ok
    r = requests.post(V + f"/office/offers/{q}/invoice", headers=hd, json={})
    assert r.status_code == 201, r.text
    inv = r.json()["doc"]["id"]
    s.patch(B + f"{D}/{inv}", json={"service_from": TODAY, "service_to": TODAY})
    assert s.post(B + f"{D}/{inv}/finalize").ok
    body = {"invoice_id": inv, "amount": "10.00", "date": TODAY, "client_ref": f"pp-{who}"}
    u = V + "/office/payment-suggestions"
    r1 = requests.post(u, headers=hd, json=body)
    r2 = requests.post(u, headers=hd, json=body)
    check(r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"], f"{who}: suggestion 201, sent again 200, the same one {r1.status_code} {r2.status_code} {r1.text[:160]}")
    check("client_ref" not in r2.json(), f"{who}: the ref stays on the server")
    n = dbx("SELECT COUNT(*) FROM office_pay_props WHERE doc_id=?", (inv,))[0][0]
    check(n == 1, f"{who}: one suggestion {n}")
    gross = s.get(B + f"{D}/{inv}").json()["totals"]["gross"]
    assert s.post(B + f"{D}/{inv}/payments", json={"date": TODAY, "amount": str(gross)}).ok
    r3 = requests.post(u, headers=hd, json=body)
    check(r3.status_code == 200 and r3.json()["id"] == r1.json()["id"], f"{who}: sent again after the invoice was paid = still the first answer {r3.status_code}")
    r4 = requests.post(u, headers=hd, json={**body, "client_ref": f"pp2-{who}"})
    check(r4.status_code == 409, f"{who}: another ref on a paid invoice 409 {r4.status_code}")

    # kept positions, over the API
    r = requests.post(V + "/office/offers", headers=hd, json={"client_id": cl, "title": "Film 2", "items": [{"text": "Licht", "qty": 1, "unit": "day", "price": 50}]})
    q2 = r.json()["doc"]["id"]
    uv = lambda: requests.get(V + f"/office/docs/{q2}", headers=hd).json()["updated_at"]  # 2.564.0 (#4702): an agent sends the version it read
    r = requests.patch(V + f"/office/offers/{q2}", headers=hd, json={"items": [{"text": "Ton", "qty": 1, "unit": "day", "price": 50}], "expect_updated_at": uv()})
    check(r.ok and r.json().get("kept_ids") == [], f"{who}: the agent's save names what stayed (nothing here) {r.status_code} {r.text[:160]}")
    r = requests.patch(V + f"/office/offers/{q2}", headers=hd, json={"title": "Film 3", "expect_updated_at": uv()})
    check(r.ok and "kept_ids" not in r.json(), f"{who}: a save without positions works and names nothing {r.status_code} {r.text[:160]}")


def time_case(s, who, uid, cl):
    ids = {}
    for name in ("Projekt A", "Projekt B"):
        lid = s.post(B + "/api/lists", json={"name": f"{name} {who}", "kind": "project"}).json()["id"]
        r = s.patch(B + f"/api/lists/{lid}", json={"client_id": cl, "time_tracking": True})
        assert r.ok, r.text
        ids[name] = lid
        sql("INSERT INTO time_entries(user_id, list_id, task_title, start, \"end\", seconds, note, source, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (uid, lid, "Schnitt", "2026-05-04T08:00:00Z", "2026-05-04T10:00:00Z", 7200, "", "manual", "2026-05-04T10:00:00Z", "2026-05-04T10:00:00Z"))
    r = s.post(B + D + "/from-time", json={"client_id": cl, "from": "2026-05-01", "to": "2026-05-31"})
    assert r.status_code == 201, r.text
    d = r.json()
    did = d["id"]
    items = d["items"]
    check(len(items) == 2, f"{who}: one position per project {len(items)}")
    stored = {r[0]: r[1] for r in dbx("SELECT list_id, billed_item_id FROM time_entries WHERE billed_doc_id=?", (did,))}
    check(all(stored.values()) and len(stored) == 2, f"{who}: the entries know their position {stored}")
    # without a version: the billed position stays and is named
    keep = [i for i in items if i["list_id"] == ids["Projekt B"]]
    r = s.put(B + f"{D}/{did}/items", json={"items": keep})
    gone_id = next(i["id"] for i in items if i["list_id"] == ids["Projekt A"])
    check(r.ok and r.json().get("kept_ids") == [gone_id], f"{who}: a save without a version keeps the billed position and names it {r.text[:200]}")
    d = s.get(B + f"{D}/{did}").json()
    # with a version: gone, its entries open again, the others stay bound
    r = s.put(B + f"{D}/{did}/items", json={"items": [i for i in d["items"] if i["id"] != gone_id], "expect_updated_at": d["updated_at"]})
    check(r.ok and r.json().get("kept_ids") == [], f"{who}: a save with a version takes it away {r.text[:200]}")
    a = dbx("SELECT billed_doc_id, billed_at, billed_item_id FROM time_entries WHERE list_id=?", (ids["Projekt A"],))[0]
    b = dbx("SELECT billed_doc_id FROM time_entries WHERE list_id=?", (ids["Projekt B"],))[0]
    check(tuple(a) == (None, None, None), f"{who}: the entry of the position gone is open again {tuple(a)}")
    check(b[0] == did, f"{who}: the other entry stays on the invoice {tuple(b)}")


def ref_case(s, who, cl):
    r1 = s.post(B + "/api/office/docs/from-time", json={"client_id": cl, "from": "2020-01-01", "to": "2020-01-31", "client_ref": f"ft-{who}"})
    assert r1.status_code == 201, r1.text
    did = r1.json()["id"]
    r = s.delete(B + f"{D}/{did}")
    assert r.ok, r.text
    trash = r.json().get("trash_id")
    r2 = s.post(B + "/api/office/docs/from-time", json={"client_id": cl, "from": "2020-01-01", "to": "2020-01-31", "client_ref": f"ft-{who}"})
    check(r2.status_code == 201 and r2.json()["id"] != did, f"{who}: the ref of a deleted document makes a new one {r2.status_code} {r2.text[:160]}")
    r = s.post(B + f"{O}/trash/{trash}/restore")
    check(r.ok, f"{who}: the old one comes back from the trash next to it {r.status_code} {r.text[:160]}")
    r3 = s.post(B + "/api/office/docs/from-time", json={"client_id": cl, "from": "2020-01-01", "to": "2020-01-31", "client_ref": f"ft-{who}"})
    check(r3.status_code == 200 and r3.json()["id"] == r2.json()["id"], f"{who}: the ref stays with the new one {r3.status_code}")


def budget_case(s, who):
    r = s.post(B + "/api/budget/lists", json={"name": f"Haushalt {who}"})
    assert r.ok, r.text
    lid = r.json()["list_id"]
    r = s.post(B + f"/api/budget/{lid}/cats", json={"name": "Miete", "kind": "out"})
    assert r.ok, r.text
    cat = r.json()
    check(cat.get("updated_at"), f"{who}: a category has a version {cat}")
    r = s.patch(B + f"/api/budget/cats/{cat['id']}", json={"name": "Wohnen", "expect_updated_at": cat["updated_at"]})
    check(r.ok and r.json()["updated_at"], f"{who}: saved with the right version {r.text[:160]}")
    r2 = s.patch(B + f"/api/budget/cats/{cat['id']}", json={"name": "Alt", "expect_updated_at": "2020-01-01T00:00:00"})
    check(r2.status_code == 409 and r2.json().get("category", {}).get("name") == "Wohnen", f"{who}: an old version 409 with the current state {r2.status_code} {r2.text[:160]}")
    r3 = s.patch(B + f"/api/budget/cats/{cat['id']}", json={"name": "Ohne Version"})
    check(r3.ok, f"{who}: without a version as before")


def mail_case(s, who, cl):
    addr = f"kunde-{who}@example.com"
    inv = invoice(s, cl)
    r = s.post(B + f"{D}/{inv}/send", json={"to": addr})
    d = s.get(B + f"{D}/{inv}").json()
    check(r.status_code == 409 and d["status"] == "issued" and not d.get("sent_at"), f"{who}: a refused mail: 409, nothing marked {r.status_code} {d.get('status')}")
    rows = dbx("SELECT k, n FROM mail_counts WHERE k LIKE ?", (f"%:{addr}",))
    check(len(rows) == 1 and rows[0][1] == 0, f"{who}: the refused mail gave the address counter back {[tuple(x) for x in rows]}")
    n = dbx("SELECT COUNT(*) FROM office_doc_log WHERE doc_id=? AND action='send'", (inv,))[0][0]
    check(n == 0, f"{who}: no send line in the log {n}")
    return inv, addr


def sent_to(addr):
    try:
        return [x for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if addr in x]
    except FileNotFoundError:
        return []


def marked_before_mail(s, who, cl):
    """2.501.0 (#4296, was a look at the order of the source lines): a mail out is always marked. Whatever fails in marking - forced
    here with a database trigger, once on the status and once on the log line - fails while nothing has gone out; a second try
    with the fault gone sends exactly one mail, which also shows that the stub would have seen it."""
    for tag, table, when in (("status", "office_docs", "NEW.sent_at IS NOT NULL AND OLD.sent_at IS NULL"), ("log", "office_doc_log", "NEW.action = 'send'")):
        addr, inv, kind = f"mark-{tag}-{who}@example.com", invoice(s, cl), "UPDATE" if table == "office_docs" else "INSERT"
        dbx("CREATE FUNCTION p4296_fail() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'marking fails'; END $$ LANGUAGE plpgsql")
        dbx(f"CREATE TRIGGER p4296 BEFORE {kind} ON {table} FOR EACH ROW WHEN ({when}) EXECUTE FUNCTION p4296_fail()")
        try:
            r = s.post(B + f"{D}/{inv}/send", json={"to": addr})
        finally:
            dbx(f"DROP TRIGGER p4296 ON {table}")
            dbx("DROP FUNCTION p4296_fail()")
        d = s.get(B + f"{D}/{inv}").json()
        check(not r.ok and not sent_to(addr) and d["status"] == "issued", f"{who}: marking fails ({tag}): no mail, nothing marked {r.status_code} {d.get('status')} {len(sent_to(addr))}")
        r = s.post(B + f"{D}/{inv}/send", json={"to": addr})
        d = s.get(B + f"{D}/{inv}").json()
        check(r.ok and len(sent_to(addr)) == 1 and d["status"] == "sent", f"{who}: fault gone ({tag}): one mail, marked {r.status_code} {d.get('status')} {len(sent_to(addr))}")


def after_stub(s, who, inv, addr):
    r = s.post(B + f"{D}/{inv}/send", json={"to": addr})
    d = s.get(B + f"{D}/{inv}").json()
    check(r.ok and d["status"] == "sent" and d.get("sent_at"), f"{who}: with a server the mail goes out and is marked {r.status_code} {d.get('status')}")
    rows = dbx("SELECT n FROM mail_counts WHERE k LIKE ?", (f"%:{addr}",))
    check(rows and rows[0][0] == 1, f"{who}: a mail sent counts once {[tuple(x) for x in rows]}")


pending = []
for who, s, uid in (("org", A, AID), ("frei", Fr, FID)):
    assert s.put(B + O + "/settings", json={"company_fields": COMPANY, "agents_read": 1}).ok
    cl = s.post(B + "/api/clients", json={"name": f"Kunde {who} GmbH", "street": "Weg 2", "zip": "10115", "city": "Berlin", "country": "DE", "email": f"k-{who}@example.com"}).json()["id"]
    r = s.post(B + "/api/my/agents", json={"username": f"bot{who}", "display_name": f"Bot {who}", "scopes": ["read", "write", "office"], **({"org_id": ORG} if who == "org" else {})})
    assert r.status_code in (200, 201), r.text
    ag, hd = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
    assert s.patch(B + f"{O}/agents/{ag}", json={"office_drafts": True}).ok
    if who == "org":  # 2.223.2 B (#2862): an organisation's agent needs an office group for payment suggestions
        assert s.put(B + f"{O}/rights/people/{ag}", json={"groups": ["tpl:projects", "tpl:bookkeeping"]}).ok
    tid = comments_case(s, who)
    lid = dbx("SELECT list_id FROM tasks WHERE id=?", (tid,))[0][0]
    assert s.put(B + f"/api/lists/{lid}/members", json={"user_id": ag, "role": "edit"}).ok
    agent_case(s, who, hd, tid, cl)
    time_case(s, who, uid, cl)
    ref_case(s, who, cl)
    budget_case(s, who)
    pending.append((s, who, cl, *mail_case(s, who, cl)))

shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
kt.until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1025), 1)"],
                                capture_output=True).returncode == 0, 15)
for s, who, cl, inv, addr in pending:
    after_stub(s, who, inv, addr)
    marked_before_mail(s, who, cl)

sys.exit(kt.done("p2370_2_office"))
