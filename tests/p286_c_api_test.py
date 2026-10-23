#!/usr/bin/env python3
"""2.86.0 API tests, part C: hardening of the office / clients area from the audit (part 1, low findings), own container in
mode workspaces with the SMTP sink of stub_mail.py. Invented companies, people and the test IBAN only.
 - N11: a client is moved into another workspace only by its creator or an admin of its organisation (a member of both
   organisations: 403); the lists of the old workspace lose it; a list takes only a client of its own workspace (409)
 - N15: office members get no bank lines, no bank fields and no DATEV export data (settings and master data export);
   the admin sees them as before
 - N16: an invoice from time tracking sums only the lists the person making it sees
 - N17: the PDF of a decided quotation: until the link's expiry (without one 30 days after the decision), only while the
   quotation is unchanged; the decided page links it then
 - N26: DATEV EXTF text fields starting with = + - @ get a leading apostrophe (Belegfeld 1 keeps its character set)
 - N27: document mails have a day budget per person (150), organisation (300) and receiving address (20): 429 beyond it
usage: p286_c_api_test.py <datadir>      (P286C_NOSTART=1: a running server on KALMIDO_TEST_PORT; N27 then needs its SMTP)"""
import datetime
import os
import re
import subprocess
import sys
import time

import requests
from freelancer_fixture import org_join  # 2.148.1 (#2480): an invited member accepts

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import testclock  # noqa: E402  (2.192.0 A, #2512: the group's test time, run_all.sh `now`)

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
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


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def anon(path):
    return requests.get(B + path, allow_redirects=False)


def form_key(html):
    m = re.search(r'name="f" value="([0-9a-f]+)"', html)
    return m.group(1) if m else ""


def start():
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)


if not os.environ.get("P286C_NOSTART"):
    start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
ids = {}
for u, n in (("bob", "Bob Member"), ("carol", "Carol Beta"), ("erin", "Erin Member")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, ERIN = ids["bob"], ids["carol"], ids["erin"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Er = sess("bob"), sess("carol"), sess("erin")
FEAT = "cal,comments,collab,office,clients,time"
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
for who in ("bob", "erin"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{who}@example.com", "role": "member"}).ok
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
check((Ca.put(B + f"/api/orgs/{BETA}/members", json={"email": "bob@example.com", "role": "member"}).ok and org_join(B, "bob", BETA)), "setup: bob is also in Beta")
for s in (A, Bo, Er):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": f"org:{BETA}"})
O = "/api/office"
D = O + "/docs"

# ---------------------------------------------------------------- N11: clients stay in their workspace
r = A.post(B + "/api/clients", json={"name": "Alpha Kunde", "org_id": ORG})
assert r.status_code == 201, r.text
CLA = r.json()["id"]
r = Bo.patch(B + f"/api/clients/{CLA}", json={"org_id": BETA})
check(r.status_code == 403, f"N11: a member of both organisations cannot move someone else's client ({r.status_code})")
check(dbx("SELECT org_id FROM clients WHERE id=?", (CLA,))[0][0] == ORG, "N11: the client stayed in Alpha")
check(Bo.patch(B + f"/api/clients/{CLA}", json={"org_id": ORG, "note": "x"}).ok, "N11: the unchanged workspace in a normal save is fine")
check(A.patch(B + f"/api/clients/{CLA}", json={"org_id": BETA}).status_code == 400, "N11: never into an organisation one is not in (400)")
LA = Bo.post(B + "/api/lists", json={"name": "Alpha Projekt", "org_id": ORG}).json()["id"]
LB = Bo.post(B + "/api/lists", json={"name": "Beta Projekt", "org_id": BETA}).json()["id"]
check(dbx("SELECT org_id FROM lists WHERE id=?", (LB,))[0][0] == BETA, "setup: bob's list in Beta")
r = Bo.patch(B + f"/api/lists/{LB}", json={"client_id": CLA})
check(r.status_code == 409, f"N11: a client of Alpha on a list of Beta: 409 ({r.status_code} {r.text[:120]})")
check(dbx("SELECT client_id FROM lists WHERE id=?", (LB,))[0][0] is None, "N11: the Beta list has no client")
check(Bo.patch(B + f"/api/lists/{LA}", json={"client_id": CLA}).ok, "N11: a client on a list of its own workspace")
r = Bo.post(B + "/api/clients", json={"name": "Bobs Kunde", "org_id": ORG})
CLB = r.json()["id"]
check(Bo.patch(B + f"/api/lists/{LA}", json={"client_id": CLB}).ok, "setup: bob's client on the Alpha list")
r = Bo.patch(B + f"/api/clients/{CLB}", json={"org_id": BETA})
check(r.ok and r.json().get("org_id") == BETA, f"N11: the creator moves the client ({r.status_code} {r.text[:120]})")
check(dbx("SELECT client_id FROM lists WHERE id=?", (LA,))[0][0] is None, "N11: the Alpha list lost the moved client")
check(Bo.patch(B + f"/api/lists/{LB}", json={"client_id": CLB}).ok, "N11: the moved client fits the Beta list")
r = A.post(B + "/api/clients", json={"name": "Erins Kunde", "org_id": ORG})
CLE = r.json()["id"]
dbx("UPDATE clients SET created_by=? WHERE id=?", (ERIN, CLE))
check(A.patch(B + f"/api/clients/{CLE}", json={"org_id": ORG, "note": "admin"}).ok, "N11: the org admin still edits a client")
# 2.86.0 (N11, second way): a list moved into another workspace leaves a client of the old one behind
LM = Bo.post(B + "/api/lists", json={"name": "Wander Projekt", "org_id": ORG}).json()["id"]
# 2.148.1 (#2483): a list leaves an organisation only through its admin -- bob moves it as an admin of both
dbx("UPDATE org_members SET role='admin' WHERE user_id=? AND org_id IN (?,?)", (BOB, ORG, BETA))
check(Bo.patch(B + f"/api/lists/{LM}", json={"client_id": CLA}).ok, "setup: Alpha client on the Alpha list")
r = Bo.patch(B + f"/api/lists/{LM}", json={"org_id": BETA})
check(r.ok, f"N11: the owner moves the list into Beta ({r.status_code} {r.text[:120]})")
check(tuple(dbx("SELECT org_id, client_id FROM lists WHERE id=?", (LM,))[0]) == (BETA, None), "N11: the moved list lost the Alpha client")
check(Bo.patch(B + f"/api/lists/{LM}", json={"client_id": CLB}).ok, "setup: Beta client on the moved list")
check(Bo.patch(B + f"/api/lists/{LM}", json={"org_id": BETA, "name": "Wander Projekt 2"}).ok, "N11: an unchanged workspace in a save")
check(dbx("SELECT client_id FROM lists WHERE id=?", (LM,))[0][0] == CLB, "N11: a fitting client stays")
r = Bo.patch(B + f"/api/lists/{LM}", json={"org_id": None})
check(r.ok and dbx("SELECT client_id FROM lists WHERE id=?", (LM,))[0][0] is None, f"N11: private, the Beta client goes too ({r.status_code})")
dbx("UPDATE org_members SET role='member' WHERE user_id=? AND org_id IN (?,?)", (BOB, ORG, BETA))  # 2.148.1 (#2483): a member again

# ---------------------------------------------------------------- office settings with bank data (admin)
r = A.put(B + O + "/settings", json={"company": {"name": "Studio Nordlicht GmbH", "bank_lines": ["Beispielbank", "IBAN DE02 1203 0000 0000 2020 51"]},
                                     "lang": "de", "currency": "EUR",
                                     "company_fields": {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg",
                                                        "country": "DE", "email": "hallo@nordlicht.example", "tax_number": "12/345/67890",
                                                        "iban": TEST_IBAN, "bic": "BYLADEM1001", "bank_name": "Beispielbank"}, "payment_days": 14,
                                     "datev_extf": {"advisor_no": "12345", "client_no": "678"}})
check(r.ok, "setup: office settings " + r.text[:160])

# ---------------------------------------------------------------- N15: members see no bank / DATEV data
ja = A.get(B + O + "/settings").json()
check(ja["company_fields"]["iban"] == TEST_IBAN and ja["settings"]["company"]["bank_lines"] and ja["settings"]["datev_extf"].get("advisor_no") == "12345",
      "N15: the admin sees bank fields, bank lines and the DATEV data")
jb = Bo.get(B + O + "/settings").json()
check(jb.get("role") == "member", f"setup: bob is a member of the office ({jb.get('role')})")
check(jb["company_fields"]["iban"] == "" and jb["company_fields"]["bic"] == "" and jb["company_fields"]["bank_name"] == "",
      f"N15: a member gets no bank fields {jb['company_fields']}")
check(jb["company_fields"]["name"] == "Studio Nordlicht GmbH" and jb["settings"]["company"]["name"] == "Studio Nordlicht GmbH",
      "N15: the member still sees the company name")
check(jb["settings"]["company"]["bank_lines"] == [] and jb["settings"]["datev_extf"] == {}, "N15: a member gets no bank lines and no DATEV data")
ex = Bo.get(B + O + "/export").json()
check(ex["settings"]["company"]["bank_lines"] == [] and ex["settings"]["datev_extf"] == {}, "N15: the member's master data export likewise")
check(A.get(B + O + "/export").json()["settings"]["datev_extf"].get("client_no") == "678", "N15: the admin's export keeps the DATEV data")
check(A.get(B + O + "/settings").json()["company_fields"]["iban"] == TEST_IBAN, "N15: the admin's values are untouched")

# ---------------------------------------------------------------- N16: invoice from time = only visible lists
r = A.post(B + "/api/clients", json={"name": "Zeitkunde AG", "org_id": ORG, "rate": 80, "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE"})
CLT = r.json()["id"]
LT1 = A.post(B + "/api/lists", json={"name": "Geheimprojekt Alice", "org_id": ORG}).json()["id"]
LT2 = Er.post(B + "/api/lists", json={"name": "Projekt Erin", "org_id": ORG}).json()["id"]
dbx("UPDATE lists SET client_id=? WHERE id IN (?, ?)", (CLT, LT1, LT2))
for who, lid, secs in ((ALICE, LT1, 7200), (ERIN, LT2, 3600)):
    dbx("INSERT INTO time_entries(user_id, list_id, start, \"end\", seconds, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        (who, lid, "2026-05-04T08:00:00", "2026-05-04T10:00:00", secs, "2026-05-04T10:00:00", "2026-05-04T10:00:00"))
r = Er.post(B + f"{D}/from-time", json={"client_id": CLT, "from": "2026-05-01", "to": "2026-05-31"})
check(r.status_code == 201, "N16: erin makes an invoice from time " + r.text[:160])
its = r.json().get("items") or [] if r.ok else []
check([x["title"] for x in its] == ["Projekt Erin"] and float(its[0]["qty"]) == 1, f"N16: only erin's visible list {[(x['title'], x['qty']) for x in its]}")
r = A.post(B + f"{D}/from-time", json={"client_id": CLT, "from": "2026-05-01", "to": "2026-05-31"})
its = r.json().get("items") or [] if r.ok else []
check("Geheimprojekt Alice" in [x["title"] for x in its], f"N16: alice's invoice has her list {[x['title'] for x in its]}")

# ---------------------------------------------------------------- N17: the PDF of a decided quotation
r = A.post(B + D, json={"project_title": "Imagefilm Herbst", "recipient": {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG"]}})
assert r.status_code == 201, r.text
Q = r.json()["id"]
A.put(B + f"{D}/{Q}/items", json={"items": [{"title": "Schnitt", "qty": 2, "rate": 900}]})
check(A.post(B + f"{D}/{Q}/status", json={"status": "sent"}).ok, "setup: quotation sent")
S1 = A.post(B + f"{D}/{Q}/signoff", json={}).json()
TOK = S1["url"].split("/s/q/")[1]
pg = anon("/s/q/" + TOK)
check(anon(f"/s/q/{TOK}/pdf").status_code == 200, "N17: open link: the PDF")
r = requests.post(B + "/s/q/" + TOK, data={"f": form_key(pg.text), "name": "Max Muster", "ok": "1", "do": "accept"}, allow_redirects=False)
check(r.status_code == 303, f"setup: accepted ({r.status_code})")
pdf = anon(f"/s/q/{TOK}/pdf")
check(pdf.status_code == 200 and pdf.content[:4] == b"%PDF", f"N17: right after the decision the customer still gets the PDF ({pdf.status_code})")
check(f"/s/q/{TOK}/pdf" in anon("/s/q/" + TOK).text, "N17: the decided page links the PDF")
old = (testclock.now().astimezone(datetime.timezone.utc) - datetime.timedelta(days=31)).isoformat(timespec="seconds")
dbx("UPDATE office_signoffs SET signed_at=? WHERE id=?", (old, S1["id"]))
check(anon(f"/s/q/{TOK}/pdf").status_code == 404, "N17: 30 days after the decision (no expiry): 404")
pg = anon("/s/q/" + TOK)
check(pg.status_code == 200 and "/pdf" not in pg.text, "N17: the decided page stays, without the PDF link")
fut = (testclock.now().astimezone(datetime.timezone.utc) + datetime.timedelta(days=5)).isoformat(timespec="seconds")
dbx("UPDATE office_signoffs SET expires_at=? WHERE id=?", (fut, S1["id"]))
check(anon(f"/s/q/{TOK}/pdf").status_code == 200, "N17: with an expiry ahead the PDF is there until then")
past = (testclock.now().astimezone(datetime.timezone.utc) - datetime.timedelta(minutes=5)).isoformat(timespec="seconds")
dbx("UPDATE office_signoffs SET expires_at=?, signed_at=? WHERE id=?", (past, testclock.now().astimezone(datetime.timezone.utc).isoformat(timespec="seconds"), S1["id"]))
check(anon(f"/s/q/{TOK}/pdf").status_code == 404, "N17: after the expiry: 404 (also for a fresh decision)")
dbx("UPDATE office_signoffs SET expires_at=? WHERE id=?", (fut, S1["id"]))
dbx("UPDATE office_docs SET project_title=? WHERE id=?", ("Changed after the decision", Q))
check(anon(f"/s/q/{TOK}/pdf").status_code == 404, "N17: the quotation changed after the decision: 404")

# ---------------------------------------------------------------- N26: DATEV formula guard
dbx("UPDATE users SET display_name=? WHERE id=?", ("=cmd|' /C calc'!A0", ALICE))
today = testclock.today()
fy0 = today.replace(day=1).isoformat()
r = A.get(B + O + f"/datev/extf?from={fy0}&to={today.isoformat()}")
check(r.ok, f"N26: DATEV export {r.status_code} {r.text[:120]}")
if r.ok:
    head = r.content.decode("cp1252").split("\r\n")[0].split(";")
    check(head[8].startswith("\"'=cmd"), f"N26: the creator field starts with an apostrophe {head[8]!r}")
    check(len(head[8]) <= 27, f"N26: still at most 25 characters inside the quotes {head[8]!r}")
dbx("UPDATE users SET display_name=? WHERE id=?", ("Alice Admin", ALICE))

# ---------------------------------------------------------------- N27: day budget of document mails
ms = A.get(B + O + "/mail-status").json()
if not ms.get("smtp"):
    print("N27: no SMTP on this server, skipped")
else:
    r = A.post(B + D, json={"kind": "invoice", "client_id": CLT, "service_from": f"{today.year}-01-05", "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]})
    assert r.status_code == 201, r.text
    I1 = r.json()["id"]
    r = A.post(B + f"{D}/{I1}/finalize")
    check(r.ok, "setup: invoice finalised " + r.text[:160])
    r = Bo.post(B + f"{D}/{I1}/send", json={"to": "kunde@example.com", "datev": False})
    check(r.ok, "N27: a member sends a document " + r.text[:160])
    now = testclock.now().astimezone(datetime.timezone.utc).isoformat(timespec="seconds")
    dbx("INSERT INTO office_doc_log(org_id, doc_id, user_id, at, action, target, detail) SELECT ?, ?, ?, ?, 'send', 'doc', '{}' FROM generate_series(1, 149)",
        (ORG, I1, BOB, now))
    r = Bo.post(B + f"{D}/{I1}/send", json={"to": "kunde2@example.com", "datev": False})
    check(r.status_code == 429 and "150" in r.json().get("error", ""), f"N27: the person's 151st document mail of the day: 429 {r.status_code} {r.text[:160]}")
    r = A.post(B + f"{D}/{I1}/send", json={"to": "kunde2@example.com", "datev": False})
    check(r.ok, "N27: another person of the organisation still sends " + r.text[:160])
    dbx("INSERT INTO office_doc_log(org_id, doc_id, user_id, at, action, target, detail) SELECT ?, ?, NULL, ?, 'send', 'doc', '{}' FROM generate_series(1, 150)",
        (ORG, I1, now))
    r = A.post(B + f"{D}/{I1}/send", json={"to": "kunde3@example.com", "datev": False})
    check(r.status_code == 429 and "300" in r.json().get("error", ""), f"N27: the organisation's 301st document mail: 429 {r.status_code} {r.text[:160]}")
    dbx("DELETE FROM office_doc_log WHERE action='send' AND org_id=?", (ORG,))
    dbx("UPDATE mail_counts SET n=20 WHERE k=?", (f"o:{ORG}:kunde@example.com",))
    r = A.post(B + f"{D}/{I1}/send", json={"to": "KUNDE@example.com", "datev": False})
    check(r.status_code == 429 and "20" in r.json().get("error", ""), f"N27: one address gets at most 20 a day (case-blind): 429 {r.status_code} {r.text[:160]}")
    r = A.post(B + f"{D}/{I1}/send", json={"to": "kunde4@example.com", "cc": "kunde@example.com", "datev": False})
    check(r.status_code == 429, f"N27: the cc counts too ({r.status_code})")
    check(A.post(B + f"{D}/{I1}/send", json={"to": "kunde4@example.com", "datev": False}).ok, "N27: another address still goes")
    out = os.path.join(DATA, "mail", "out.jsonl")
    n = len(open(out, encoding="utf-8").read().splitlines()) if os.path.exists(out) else -1
    check(n == 3, f"N27: three mails went out, none of the refused ones ({n})")

print(f"p286_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
