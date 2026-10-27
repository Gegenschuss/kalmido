#!/usr/bin/env python3
"""2.120.0 API tests, part B: #2088 the customer portal with quotations, invoices and their payment status. Own container
with the e-mail stub (stub_mail.py), organisations (mode workspaces). Invented companies, people and example.com addresses only.
 - the office setting portal_docs: off by default, only the office's admin switches it (member 403); off = "Send portal link"
   answers 409 and /portal looks as before ("Your reports", no documents section); public links off = no documents either
 - "Send portal link" (POST /api/office/clients/{id}/portal-link): a member of the office sends the sign-in link of the portal
   to the client's e-mail for invoices (else the e-mail); another organisation's client and a client of another person's
   personal office = 404; a client without address 400; at most three links per address and hour (429)
 - the portal after signing in with that link: the documents of exactly that client in exactly that space -- the sent
   quotation (with its open approval link), the sent invoice with the payment state (partly paid, the open amount, due
   date), the paid one; never a draft, a finalised but unsent invoice, a reminder, another client's invoice of the same
   organisation, an invoice of another organisation for a client with the SAME address
 - the PDF /portal/docs/{id}/pdf: the stored file as it was sent (the same bytes as in the app); another client's / space's
   document, a draft, a guessed id and a request without the cookie all get the same 404
 - a person without organisation (personal office): the same for the private clients; the other room's cookie sees nothing
tenant-matrix: portal
tenant-matrix: office
freelancer-matrix: office
freelancer-matrix: link
usage: p2120_b_api_test.py <datadir>      (P2120B_NOSTART=1: a running server on KALMIDO_TEST_PORT with the mail stub, no start.sh)"""
import email
import email.header
import json
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check, sess, until  # 2.206.0 (#2762): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,forms"
O = "/api/office"
D = O + "/docs"
EN = {"Accept-Language": "en"}


MAILENV = ["-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none",
           "-e", "KALMIDO_MAIL_FROM=kalmido@example.test", "-e", "KALMIDO_INSTANCE_MODE=workspaces"]
if os.environ.get("P2120B_NOSTART") != "1":
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)
OUT = os.path.join(DATA, "mail", "out.jsonl")


def dbq(q, a=()):
    c = dbx.connect(os.path.join(DATA, "tasks.db"))
    try:
        return c.execute(q, a).fetchall()
    finally:
        c.close()


def mails(to):
    """The plain texts of the mails the stub got for address to."""
    out = []
    try:
        lines = open(OUT, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return out
    for ln in lines:
        j = json.loads(ln)
        if not any(to in x for x in j["to"]):
            continue
        m = email.message_from_string(j["raw"])
        txt = ""
        for part in m.walk():
            if part.get_content_type() == "text/plain":
                txt += part.get_payload(decode=True).decode("utf-8", "replace")
        out.append(txt)
    return out


def sign_in(to, n_before):
    """The portal session of the newest sign-in link mailed to address to (after n_before mails)."""
    got = until(lambda: len(mails(to)) > n_before and mails(to), 20) or []
    m = re.search(r"/portal/login/([A-Za-z0-9_-]{30,64})", got[-1] if got else "")
    s = requests.Session()
    s.headers.update(EN)
    if not m:
        return s
    pg = s.get(B + f"/portal/login/{m.group(1)}")  # 2.120.0 (#2088): the button page names documents (documents are on here)
    check(pg.ok and "Show my documents" in pg.text and "Show my reports" not in pg.text, f"#2088: the sign-in button page names documents ({to})")
    r = s.post(B + f"/portal/login/{m.group(1)}", allow_redirects=False)
    check(r.status_code == 303 and "kalmido_portal=" in r.headers.get("Set-Cookie", ""), f"#2088: the mailed link signs in ({to})")
    return s


COMPANY = {"street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE", "email": "hallo@studio.example",
           "tax_number": "12/345/67890", "vat_id": "DE999999999", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def office(s, name):
    r = s.put(B + O + "/settings", json={"company": {"name": name}, "lang": "de", "company_fields": {"name": name, **COMPANY}})
    assert r.ok, r.text


def client(s, name, mail, inv=""):
    r = s.post(B + "/api/clients", json={"name": name, "email": mail, "email_invoice": inv, "street": "Marktstraße 5", "zip": "50667",
                                         "city": "Köln", "country": "DE"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def invoice(s, cl, rate=100, final=True, sent=True):
    r = s.post(B + D, json={"kind": "invoice", "client_id": cl, "service_from": "2026-05-01", "items": [{"title": "Beratung", "qty": 1, "rate": rate}]})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    if final:
        r = s.post(B + f"{D}/{did}/finalize")
        assert r.ok, r.text
    if sent:
        r = s.post(B + f"{D}/{did}/status", json={"status": "sent"})
        assert r.ok, r.text
    return did, s.get(B + f"{D}/{did}").json()


# ---------------------------------------------------------------- setup: Alpha (alice admin, bob member), Beta (carol admin)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments", "clients"]})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    assert A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"}).ok
Bo, Ca = sess("bob"), sess("carol")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Bo.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{ORG2}"})
office(A, "Studio Nordlicht GmbH")
office(Ca, "Beta Werkstatt GmbH")

X = client(A, "Kunde Xaver GmbH", "kontakt@xaver.example.com", "rechnung@xaver.example.com")
Y = client(A, "Kunde Ypsilon AG", "kontakt@ypsilon.example.com")
NOMAIL = client(A, "Kunde ohne Mail", "")
Z = client(Ca, "Xaver bei Beta", "rechnung@xaver.example.com")

# documents of client X (Alpha): a sent quotation with an approval link, a sent invoice (part paid), a paid one, a draft,
# a finalised but unsent one; client Y: a sent invoice; Beta's client Z (same address as X): a sent invoice
r = A.post(B + D, json={"client_id": X, "project_title": "Imagefilm Hafen", "items": [{"title": "Dreh", "qty": 1, "rate": 900}]})
assert r.status_code == 201, r.text
OFF = r.json()["id"]
assert A.post(B + f"{D}/{OFF}/status", json={"status": "sent"}).ok
SIG = A.post(B + f"{D}/{OFF}/signoff", json={}).json()
OFFNUM = A.get(B + f"{D}/{OFF}").json()["number"]
INV1, inv1 = invoice(A, X, 1000)
assert A.post(B + f"{D}/{INV1}/payments", json={"date": "2026-06-01", "amount": "100.00", "method": "transfer"}).ok
INV2, inv2 = invoice(A, X, 200)
assert A.post(B + f"{D}/{INV2}/payments", json={"date": "2026-06-01", "amount": inv2["totals"]["gross"], "method": "transfer"}).ok
DRAFT, _ = invoice(A, X, 300, final=False, sent=False)
ISSUED, issued = invoice(A, X, 400, sent=False)
INVY, invy = invoice(A, Y, 500)
INVZ, invz = invoice(Ca, Z, 600)
check(inv1["number"] and invy["number"] and invz["number"], "setup: numbered invoices")

# ---------------------------------------------------------------- the setting
st = A.get(B + O + "/settings").json()["settings"]
check(st.get("portal_docs") == 0, f"#2088: documents in the portal are off by default ({st.get('portal_docs')})")
check(A.post(B + O + f"/clients/{X}/portal-link", json={}).status_code == 409, "#2088: switched off = no portal link (409)")
check(Bo.put(B + O + "/settings", json={"portal_docs": 1}).status_code == 403, "#2088: a member cannot switch it (403)")
check(A.put(B + O + "/settings", json={"portal_docs": 1}).ok and A.get(B + O + "/settings").json()["settings"].get("portal_docs") == 1,
      "#2088: the office's admin switches it on")
check(Ca.put(B + O + "/settings", json={"portal_docs": 1}).ok, "setup: Beta switches it on too")

# ---------------------------------------------------------------- "Send portal link"
n0 = len(mails("rechnung@xaver.example.com"))
r = Bo.post(B + O + f"/clients/{X}/portal-link", json={})
check(r.ok and r.json().get("to") == "rechnung@xaver.example.com", f"#2088: a member sends the link to the e-mail for invoices {r.status_code} {r.text[:200]}")
check(Ca.post(B + O + f"/clients/{X}/portal-link", json={}).status_code == 404, "#2088: another organisation's client = 404")
check(A.post(B + O + f"/clients/{NOMAIL}/portal-link", json={}).status_code == 400, "#2088: a client without address = 400")
check(A.post(B + O + "/clients/999999/portal-link", json={}).status_code == 404, "#2088: an unknown client = 404")
log = dbq("SELECT action, target FROM office_doc_log WHERE org_id=? AND action='portal_link'", (ORG,))
check(len(log) == 1 and log[0][1] == "client", f"#2088: the office log notes the link {log}")

# ---------------------------------------------------------------- the portal of client X in Alpha
PX = sign_in("rechnung@xaver.example.com", n0)
pg = PX.get(B + "/portal").text
check("Customer portal" in pg and "Documents" in pg, "#2088: the portal shows the documents section")
check(OFFNUM and OFFNUM in pg and inv1["number"] in pg and inv2["number"] in pg, "#2088: the sent quotation and the sent invoices are listed")
check(issued["number"] not in pg and invy["number"] not in pg, "#2088: neither an unsent invoice nor another client's")
check(f"/portal/docs/{DRAFT}/" not in pg and f"/portal/docs/{ISSUED}/" not in pg and f"/portal/docs/{INVY}/" not in pg and f"/portal/docs/{INVZ}/" not in pg,
      "#2088: no link to a draft, unsent, other client's or other space's document")
check("Partly paid" in pg and "Paid" in pg, "#2088: the payment states")
sq = re.search(r"/s/q/[A-Za-z0-9_-]{20,}", SIG.get("url") or "")
check("Review and approve" in pg and bool(sq) and sq.group(0) in pg, f"#2088: the open quotation links its approval page {SIG.get('url')}")
check("<script" not in pg.lower(), "#2088: no scripts on the portal page")

# PDFs
a = A.get(B + f"{D}/{INV1}/pdf")
p = PX.get(B + f"/portal/docs/{INV1}/pdf")
check(p.status_code == 200 and p.content[:5] == b"%PDF-" and p.content == a.content, "#2088: the invoice PDF is the stored one (same bytes as in the app)")
check(p.headers.get("Cache-Control", "").startswith("no-store") and "noindex" in p.headers.get("X-Robots-Tag", ""), "#2088: PDF headers (no-store, noindex)")
check(PX.get(B + f"/portal/docs/{OFF}/pdf").status_code == 200, "#2088: the quotation's PDF")
for did, what in ((DRAFT, "a draft"), (ISSUED, "an unsent invoice"), (INVY, "another client's invoice"), (INVZ, "another organisation's invoice"),
                  (999999, "an unknown id")):
    check(PX.get(B + f"/portal/docs/{did}/pdf").status_code == 404, f"#2088: {what} = 404")
check(requests.get(B + f"/portal/docs/{INV1}/pdf").status_code == 404, "#2088: without the cookie = 404")

# ---------------------------------------------------------------- the same address in Beta sees only Beta's
n1 = len(mails("rechnung@xaver.example.com"))
check(Ca.post(B + O + f"/clients/{Z}/portal-link", json={}).ok, "#2088: Beta sends its client the link")
PZ = sign_in("rechnung@xaver.example.com", n1)
pz = PZ.get(B + "/portal").text
check(invz["number"] in pz and f"/portal/docs/{INVZ}/" in pz and f"/portal/docs/{INV1}/" not in pz and f"/portal/docs/{OFF}/" not in pz,
      "#2088: Beta's portal shows Beta's invoice only")
check(PZ.get(B + f"/portal/docs/{INV1}/pdf").status_code == 404 and PZ.get(B + f"/portal/docs/{INVZ}/pdf").status_code == 200,
      "#2088: Beta's cookie cannot fetch Alpha's PDF")

# ---------------------------------------------------------------- rate limit: three links per address and hour
for _ in range(3):
    last = A.post(B + O + f"/clients/{Y}/portal-link", json={})
check(last.ok and A.post(B + O + f"/clients/{Y}/portal-link", json={}).status_code == 429, "#2088: the fourth link within an hour = 429")

# ---------------------------------------------------------------- switched off = the portal as before
check(A.put(B + O + "/settings", json={"portal_docs": 0}).ok, "#2088: switched off again")
pg = PX.get(B + "/portal").text
check("Your reports" in pg and "Customer portal" not in pg and f"/portal/docs/{INV1}/" not in pg, "#2088: off = the portal as before")
check(PX.get(B + f"/portal/docs/{INV1}/pdf").status_code == 404, "#2088: off = the PDF 404")
check(A.put(B + O + "/settings", json={"portal_docs": 1}).ok, "on again")
A.patch(B + "/api/admin/settings", json={"public_links": False})
off = PX.get(B + f"/portal/docs/{INV1}/pdf").status_code
A.patch(B + "/api/admin/settings", json={"password": "password123", "public_links": True})
check(off == 404, f"#2088: public links off = no documents ({off})")

# ---------------------------------------------------------------- a person without organisation (personal office)
# freelancer-matrix: office (POST /api/office/clients/{}/portal-link) and link (GET /portal/docs/{}/pdf)
FID, Fr = freelancer(B, A)
office(Fr, "Frida Frei Design")
check(Fr.put(B + O + "/settings", json={"portal_docs": 1}).ok, "freelancer: switches the documents on in the personal office")
FC = client(Fr, "Privatkunde Quer", "quer@example.com")
FINV, finv = invoice(Fr, FC, 700)
n2 = len(mails("quer@example.com"))
check(Fr.post(B + O + f"/clients/{FC}/portal-link", json={}).ok, "freelancer: sends the portal link")
check(Fr.post(B + O + f"/clients/{X}/portal-link", json={}).status_code == 404 and A.post(B + O + f"/clients/{FC}/portal-link", json={}).status_code == 404,
      "freelancer: no link to an organisation's client, the organisation none to the private client (404)")
row = dbq("SELECT org_id, owner_id FROM portal_logins ORDER BY id DESC LIMIT 1")
check(row and row[0][0] is None and row[0][1] == FID, f"freelancer: the sign-in belongs to the private space {row}")
PF = sign_in("quer@example.com", n2)
pf = PF.get(B + "/portal").text
check(finv["number"] in pf and f"/portal/docs/{FINV}/" in pf and f"/portal/docs/{INV1}/" not in pf, "freelancer: the private client's portal shows its invoice")
check(PF.get(B + f"/portal/docs/{FINV}/pdf").status_code == 200 and PF.get(B + f"/portal/docs/{INV1}/pdf").status_code == 404,
      "freelancer: its PDF, never an organisation's")
check(PX.get(B + f"/portal/docs/{FINV}/pdf").status_code == 404, "freelancer: Alpha's customer cannot fetch the private PDF")

print(f"p2120_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
