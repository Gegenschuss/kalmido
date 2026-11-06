#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.542.0 API tests, part C: trial documents never go out by e-mail (#4594) and finalised documents are held by the database
(#4598, the trigger kalmido_office_locked of core/migrations.d/4598.py). Own container with the SMTP sink of stub_mail.py,
once in an organisation's office (its admin) and once in the personal office of a person without an organisation
(freelancer fixture; freelancer-matrix: office). Invented companies, people and addresses only.
 - #4594: a finalised real invoice is mailed (200, one mail); a finalised trial invoice is refused with 409 and the reason,
   nothing is mailed, it stays unsent
 - #4598: on a finalised invoice a direct SQL change of its content (title, number, date, totals, the stored PDF's hash,
   the status back to draft) and a DELETE are refused by the database; the free columns (project, cash flow planning,
   updated_at) go through; a DELETE of a finalised trial document goes through; the organisation that goes for good takes
   its finalised documents with it (ON DELETE CASCADE); a deleted project empties list_id (ON DELETE SET NULL)
 - the app's own ways keep working with the trigger: payment (paid), sending, credit note (cancellation), a finalised
   quotation taken back to a draft (unlock) and a finalised never-sent quotation deleted, a trial document deleted
usage: p2542_c_office_test.py <datadir>      (P2542C_NOSTART=1: a running server on KALMIDO_TEST_PORT with the SMTP sink)"""
import json
import os
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402
import requests  # noqa: E402
import testclock  # noqa: E402

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
CLIENT = {"name": "Beispiel Kunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
          "email_invoice": "rechnung@kunde.example", "payment_terms_days": 14}
TODAY = testclock.today().isoformat()  # the Berlin day of the test clock
LOCKED = "is finalised"  # the trigger's message (core/migrations.d/4598.py)


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


def free(sql, args=()):
    """The suites' usual access (dbx: past the trigger)."""
    return dbxm.connect(DATA).execute(sql, args)


def guarded(sql, args=()):
    """A statement as the app's connections run it (no switch kalmido.locked_ok) -> "" or the database's error text."""
    try:
        dbxm.connect(DATA, guarded=True).execute(sql, args)
        return ""
    except dbxm.DbError as e:
        return str(e)


def row(did, cols="*"):
    r = free(f"SELECT {cols} FROM office_docs WHERE id=?", (did,)).fetchone()
    return dict(r) if r else None


if not os.environ.get("P2542C_NOSTART"):
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
ORG = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)


def run(S, who):
    def ok(cond, what):
        check(cond, f"{who}: {what}")

    r = S.put(B + O + "/settings", json={"company": {"name": COMPANY["name"]}, "lang": "en", "currency": "EUR", "payment_days": 14,
                                         "company_fields": COMPANY})
    ok(r.ok, "office settings " + r.text[:200])
    ok(S.get(B + O + "/mail-status").json().get("smtp"), "setup: the SMTP sink")
    r = S.post(B + "/api/clients", json=CLIENT)
    ok(r.status_code in (200, 201), "a client " + r.text[:200])
    cl = r.json().get("id")

    def doc(kind="invoice", trial=False, final=True, title=None):
        r = S.post(B + D, json={"kind": kind, "client_id": cl, "project_title": title or f"{kind} {who}", "service_from": TODAY,
                                "items": [{"title": "Schnitt", "qty": 1, "rate": 1000}]})
        ok(r.status_code == 201, f"a {kind} " + r.text[:200])
        did = r.json()["id"]
        if trial:
            free("UPDATE office_docs SET trial=1 WHERE id=?", (did,))  # a draft: like part A of 2.144.10 sets it
        if final:
            r = S.post(B + f"{D}/{did}/finalize")
            ok(r.ok and r.json().get("locked") is True, f"{kind} {did} finalised " + r.text[:200])
        return did

    # ---------------------------------------------------------------- #4594: no trial document by e-mail
    real = doc()
    n0 = len(mails())
    r = S.post(B + f"{D}/{real}/send", json={"to": CLIENT["email_invoice"]})
    ok(r.ok, "#4594: a finalised real invoice is mailed " + r.text[:200])
    ok(len(mails()) == n0 + 1, "#4594: one mail for the real invoice")
    tri = doc(trial=True)
    n0 = len(mails())
    r = S.post(B + f"{D}/{tri}/send", json={"to": CLIENT["email_invoice"]})
    ok(r.status_code == 409, f"#4594: a finalised trial invoice is refused (409), got {r.status_code} " + r.text[:200])
    ok("trial document cannot be sent by e-mail" in r.text, "#4594: the reason is named " + r.text[:200])
    ok(len(mails()) == n0, "#4594: nothing mailed for the trial invoice")
    t = row(tri, "status, sent_at")
    ok(t["status"] != "sent" and not t["sent_at"], f"#4594: the trial invoice stays unsent {t}")
    ok(S.get(B + f"{D}/{tri}").json().get("trial") is True, "#4594: the document says trial (the editor's send button is off)")

    # ---------------------------------------------------------------- #4598: the database holds a finalised document
    inv = doc(title="Locked " + who)
    before = row(inv)
    ok(before["locked_at"] and before["pdf_sha256"], "#4598: finalised with its stored PDF's hash")
    for what, sql, args in (("the title", "UPDATE office_docs SET project_title=? WHERE id=?", ("changed", inv)),
                            ("the number", "UPDATE office_docs SET number=? WHERE id=?", ("X-999", inv)),
                            ("the date", "UPDATE office_docs SET date=? WHERE id=?", ("2001-01-01", inv)),
                            ("the totals", "UPDATE office_docs SET totals=? WHERE id=?", ('{"gross": 1}', inv)),
                            ("the frozen recipient", "UPDATE office_docs SET recipient_snapshot=? WHERE id=?", ("{}", inv)),
                            ("the lock itself", "UPDATE office_docs SET locked_at=NULL WHERE id=?", (inv,)),
                            ("the stored PDF's hash", "UPDATE office_docs SET pdf_sha256=? WHERE id=?", ("0" * 64, inv)),
                            ("the status back to draft", "UPDATE office_docs SET status='draft' WHERE id=?", (inv,)),
                            ("a DELETE", "DELETE FROM office_docs WHERE id=?", (inv,))):
        e = guarded(sql, args)
        ok(LOCKED in e, f"#4598: {what} of a finalised invoice is refused by the database: {e[:160]!r}")
    after = row(inv)
    ok(after == before, "#4598: the row is unchanged after the refused statements")
    ok(guarded("UPDATE office_docs SET cashflow='off', updated_at=updated_at WHERE id=?", (inv,)) == "", "#4598: a free column goes through")
    ok(row(inv, "cashflow")["cashflow"] == "off", "#4598: ... and is written")
    free("UPDATE office_docs SET cashflow=? WHERE id=?", (before["cashflow"], inv))
    ok(guarded("UPDATE office_docs SET project_title=project_title WHERE id=?", (inv,)) == "", "#4598: writing the same value is no change")
    draft = doc(final=False)
    ok(guarded("UPDATE office_docs SET project_title='still a draft' WHERE id=?", (draft,)) == "", "#4598: a draft stays free")
    # a project (list) deleted: list_id emptied by the database's reference action
    r = S.post(B + "/api/lists", json={"name": f"Projekt {who}"})
    ok(r.status_code in (200, 201), "a list " + r.text[:200])
    lid = r.json().get("id")
    free("UPDATE office_docs SET list_id=? WHERE id=?", (lid, inv))
    ok(guarded("DELETE FROM lists WHERE id=?", (lid,)) == "", "#4598: a deleted project empties list_id (SET NULL)")
    ok(row(inv, "list_id")["list_id"] is None, "#4598: ... list_id is empty")
    # the app's own ways with the trigger in place
    gross = S.get(B + f"{D}/{inv}").json()["totals"]["gross"]
    r = S.post(B + f"{D}/{inv}/payments", json={"date": before["date"], "amount": gross, "method": "transfer"})
    ok(r.ok, "#4598: a payment on a finalised invoice " + r.text[:200])
    ok(row(inv, "status")["status"] == "paid", "#4598: ... the invoice is paid")
    inv2 = doc()
    r = S.post(B + f"{D}/{inv2}/credit")
    ok(r.status_code == 201, "#4598: a credit note of a finalised invoice " + r.text[:200])
    if r.status_code == 201:
        r = S.post(B + f"{D}/{r.json()['id']}/finalize")
        ok(r.ok, "#4598: the credit note finalised " + r.text[:200])
        ok(row(inv2, "status")["status"] == "cancelled", f"#4598: ... the invoice is cancelled {row(inv2, 'status')}")
    off = doc("offer")
    r = S.post(B + f"{D}/{off}/unlock")
    ok(r.ok and r.json().get("locked") is not True, "#4598: a finalised never-sent quotation goes back to a draft " + r.text[:200])
    ok(not row(off, "locked_at")["locked_at"], "#4598: ... unlocked in the database")
    off2 = doc("offer")
    r = S.delete(B + f"{D}/{off2}")
    ok(r.ok, "#4598: a finalised never-sent quotation is deleted " + r.text[:200])
    ok(row(off2, "id") is None, "#4598: ... gone")
    r = S.delete(B + f"{D}/{tri}")
    ok(r.ok, "#4598: a finalised trial invoice is deleted " + r.text[:200])
    ok(row(tri, "id") is None, "#4598: ... gone")
    tri2 = doc(trial=True)
    ok(guarded("DELETE FROM office_docs WHERE id=?", (tri2,)) == "", "#4598: a DELETE of a finalised trial document goes through")
    r = S.delete(B + f"{D}/{real}")
    ok(r.status_code == 409, f"#4598: the app still refuses to delete a finalised invoice (409), got {r.status_code}")
    return inv


run(A, "organisation")
run(Fr, "freelancer")

# ---------------------------------------------------------------- #4598: an organisation going for good takes its documents along
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ALICE})
check(r.status_code == 201, "a second organisation " + r.text[:200])
BETA = r.json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{BETA}"})
gone = run(A, "organisation Beta")
check(row(gone, "locked_at")["locked_at"], "Beta: a finalised invoice")
e = guarded("DELETE FROM orgs WHERE id=?", (BETA,))
check(LOCKED not in e, f"#4598: the cascade of a deleted organisation is not held by the trigger: {e[:200]!r}")
check(e == "" and row(gone, "id") is None, f"#4598: ... its finalised documents went with it: {e[:200]!r}")

print(f"p2542_c_office: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
