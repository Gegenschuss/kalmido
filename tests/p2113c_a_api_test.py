#!/usr/bin/env python3
"""2.113.2 A (#2253) API tests: terms and conditions (AGB) as a PDF per language, sent along with quotations. Own container
in mode workspaces, organisation encryption on, the SMTP sink of stub_mail.py. Invented companies, people and files only.
 - settings: upload per language (PDF only, at most 10 MB, a valid date), replace, remove, restore (the undo step); the
   office's admin writes, members read; another organisation sees none of it (404 for its files); the general settings
   PUT never sets them; the file is stored sealed and content-addressed (an older state stays)
 - freezing: finalising a quotation keeps the state of its language (office_docs.terms); replacing the terms later leaves
   the finalised one, its PDF line and its mail attachment as they were; a draft follows the current state; a copy takes
   none along; terms in the other language only = no line, no attachment
 - sending: a quotation attaches them by default ("AGB-Stand-<date>.pdf"), terms=false leaves them out, an invoice only on
   request; the log entry "send" names the state (lang, date, sha256)
 - approval link: /s/q/<token>/terms serves the state of the link's quotation (noindex, no-referrer), a wrong token and
   a link without terms answer like /pdf (404); the decision record names the state; a contract made from a template
   keeps the terms when finished and offers them on its link
 - a person without an organisation (freelancer-matrix: office): the same in the personal office
usage: p2113c_a_api_test.py <datadir>      (P2113BA_NOSTART=1: a running server on KALMIDO_TEST_PORT with the SMTP sink)"""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients,docs,time"
O = "/api/office"
D = O + "/docs"
T = O + "/terms"
GD = O + "/gen-docs"
ENV = ["-e", "KALMIDO_INSTANCE_MODE=workspaces", "-e", "KALMIDO_ORGCRYPT_DELAY=0", "-e", f"KALMIDO_SECRET_KEY={KEY}",
       "-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none", "-e", "KALMIDO_MAIL_FROM=kalmido@example.test"]


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def anon(path):
    return requests.get(B + path, allow_redirects=False)


def form_key(html):
    m = re.search(r'name="f" value="([0-9a-f]+)"', html)
    return m.group(1) if m else ""


def pdf_text(data):
    out = b""
    # Kalmido ends a stream with "\nendstream": a compressed stream may itself end in a CR byte (1 in 256), "\r?" cut it off (CI red, 2.145.1 #2439)
    for m in re.finditer(rb"stream\r?\n(.*?)\nendstream", data, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out.decode("latin-1")


def in_pdf(data, text):
    return text.encode("cp1252").hex() in pdf_text(data)


def fake_pdf(tag):
    """A small file with the PDF header (the server checks the header only), different per tag."""
    return b"%PDF-1.4\n% invented terms " + tag.encode() + b"\n" + os.urandom(64).hex().encode() + b"\n%%EOF\n"


def upload(s, lang, data, date="", name="AGB Beispiel.pdf", mime="application/pdf"):
    return s.post(B + f"{T}/{lang}", files={"file": (name, data, mime)}, data={"date": date} if date else {})


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
    time.sleep(0.8)


if not os.environ.get("P2113BA_NOSTART"):
    start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Beta")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, BETA)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
r = A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {
    "name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE", "email": "hallo@nordlicht.example",
    "tax_number": "12/345/67890", "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}, "payment_days": 14})
check(r.ok, "setup: office settings " + r.text[:160])
CL = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
                                       "email": "kunde@example.com"}).json()["id"]

# ---------------------------------------------------------------- settings: upload, rights, checks
j = A.get(B + T).json()
check(j["terms"] == {"de": None, "en": None} and j["admin"] is True and j["max_mb"] == 10, f"no terms yet, the admin may write {j}")
jb = Bo.get(B + T).json()
check(jb["admin"] is False and jb["terms"] == {"de": None, "en": None}, "a member reads (no write right)")
DE1, DE2, EN1 = fake_pdf("de one"), fake_pdf("de two"), fake_pdf("en one")
SHA1, SHA2 = hashlib.sha256(DE1).hexdigest(), hashlib.sha256(DE2).hexdigest()
check(upload(Bo, "de", DE1).status_code == 403, "a member cannot upload (403)")
check(upload(A, "fr", DE1).status_code == 404, "an unknown language: 404")
check(upload(A, "de", b"<html>not a pdf</html>", name="x.pdf").status_code == 400, "not a PDF (header): 400")
check(upload(A, "de", DE1, date="2026-13-40").status_code == 400, "an invalid date: 400")
r = upload(A, "de", b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024))
check(r.status_code == 413, f"more than 10 MB: 413 ({r.status_code})")
r = upload(A, "de", DE1, date="2026-10-01", name='AGB "Studio" 2026.pdf')
check(r.ok and r.json()["terms"]["de"]["date"] == "2026-10-01" and r.json()["terms"]["de"]["sha256"] == SHA1 and r.json()["terms"]["en"] is None,
      f"the admin uploads the German terms {r.status_code} {r.text[:200]}")
check(r.ok and r.json()["terms"]["de"]["name"] == "AGB Studio 2026.pdf" and "file" not in r.json()["terms"]["de"], "the name cleaned, no server file name")
F1 = os.path.join(DATA, "office", str(ORG), f"terms-de-{SHA1[:16]}.pdf")
try:
    raw = open(F1, "rb").read()
    check(not raw.startswith(b"%PDF") and DE1 not in raw, "the file is stored sealed (organisation encryption)")
except PermissionError:
    print("note: the office folder is not readable from the host, sealing not checked")
except FileNotFoundError:
    check(False, f"the terms file is stored content-addressed below the office folder ({F1})")
r = Bo.get(B + f"{T}/de/file")
check(r.ok and r.content == DE1 and "attachment" in r.headers.get("Content-Disposition", "") and r.headers.get("Cache-Control") == "no-store",
      f"a member downloads the file ({r.status_code})")
check(r.ok and "filename*=UTF-8''AGB%20Studio%202026.pdf" in r.headers.get("Content-Disposition", ""), f"the clean name {r.headers.get('Content-Disposition')}")
check("inline" in Bo.get(B + f"{T}/de/file?inline=1").headers.get("Content-Disposition", ""), "?inline=1 shows it")
check(Bo.get(B + f"{T}/en/file").status_code == 404, "no English terms: 404")
check(Ca.get(B + T).json()["terms"] == {"de": None, "en": None} and Ca.get(B + f"{T}/de/file").status_code == 404,
      "another organisation sees none of it (404)")
check(A.put(B + O + "/settings", json={"terms": {}, "color": "#336699"}).ok and A.get(B + T).json()["terms"]["de"]["sha256"] == SHA1,
      "the general settings save never touches the terms")
lg = A.get(B + O + "/log?limit=20").json()["log"]
check(any(x["action"] == "upload" and x["target"] == "terms" and (x.get("detail") or {}).get("sha256") == SHA1 for x in lg), "office log: upload of the terms")

# ---------------------------------------------------------------- quotation: line, freezing
r = A.post(B + D, json={"kind": "offer", "client_id": CL, "project_title": "Imagefilm Herbst", "items": [{"title": "Schnitt", "qty": 2, "rate": 900}]})
assert r.status_code == 201, r.text
Q = r.json()["id"]
j = A.get(B + f"{D}/{Q}/terms").json()
check(j["terms"] and j["terms"]["date"] == "2026-10-01" and j["default"] is True, f"a German quotation draft: the current terms, ticked by default {j}")
rd = A.get(B + f"{D}/{Q}/render").json()
check(rd.get("terms_line") == "Es gelten unsere AGB (Stand 01.10.2026), siehe Anhang.", f"the print model has the line {rd.get('terms_line')!r}")
QE = A.post(B + D, json={"kind": "offer", "client_id": CL, "lang": "en", "items": [{"title": "Edit", "qty": 1, "rate": 100}]}).json()["id"]
check(A.get(B + f"{D}/{QE}/terms").json()["terms"] is None and not A.get(B + f"{D}/{QE}/render").json().get("terms_line"),
      "an English quotation with German terms only: no terms, no line")
r = A.post(B + f"{D}/{Q}/finalize")
check(r.ok, "the quotation is finalised " + r.text[:160])
fz = json.loads(sql("SELECT terms FROM office_docs WHERE id=?", (Q,))[0][0] or "{}")
check(fz.get("sha256") == SHA1 and fz.get("date") == "2026-10-01" and fz.get("lang") == "de", f"finalising froze the state {fz}")
check(r.ok and (r.json().get("terms") or {}).get("sha256") == SHA1 and "file" not in (r.json().get("terms") or {}), "the document answer names the frozen terms")
r = upload(A, "de", DE2, date="2026-10-15", name="AGB neu.pdf")
check(r.ok and r.json()["terms"]["de"]["sha256"] == SHA2, "the admin replaces the German terms")
check(os.path.exists(F1) or not os.access(os.path.dirname(F1), os.R_OK), "the older file stays for what went out with it")
j = A.get(B + f"{D}/{Q}/terms").json()
check(j["terms"]["date"] == "2026-10-01" and j["terms"]["sha256"] == SHA1, f"the finalised quotation keeps its state {j}")
pdf = A.get(B + f"{D}/{Q}/pdf").content
check(pdf[:5] == b"%PDF-" and in_pdf(pdf, "Es gelten unsere AGB (Stand 01.10.2026), siehe Anhang."), "its PDF prints the frozen date")
Q2 = A.post(B + D, json={"kind": "offer", "client_id": CL, "items": [{"title": "Ton", "qty": 1, "rate": 300}]}).json()["id"]
check(A.get(B + f"{D}/{Q2}/render").json().get("terms_line") == "Es gelten unsere AGB (Stand 15.10.2026), siehe Anhang.", "a draft follows the current state")
r = A.post(B + f"{D}/{Q}/duplicate")
QD = r.json()["id"] if r.ok else 0
check(r.ok and sql("SELECT terms FROM office_docs WHERE id=?", (QD,))[0][0] is None, "a copy takes no frozen state along")

# ---------------------------------------------------------------- sending
check(A.get(B + O + "/mail-status").json().get("smtp"), "setup: SMTP sink")
n0 = len(mails())
r = Bo.post(B + f"{D}/{Q}/send", json={"to": "kunde@example.com"})
check(r.ok, "a member sends the quotation " + r.text[:160])
m = mails()[n0:]
check(len(m) == 1 and "AGB-Stand-2026-10-01.pdf" in m[0]["raw"], "the frozen terms go along by default (AGB-Stand-2026-10-01.pdf)")
lg = A.get(B + f"{D}/{Q}/log").json()["log"]
snd = [x for x in lg if x["action"] == "send"]
check(snd and (snd[0].get("detail") or {}).get("terms", {}).get("sha256") == SHA1 and "AGB-Stand-2026-10-01.pdf" in snd[0]["detail"].get("files", []),
      f"the log names the terms state {snd[:1]}")
r = A.post(B + f"{D}/{Q}/send", json={"to": "kunde@example.com", "terms": False})
m = mails()[n0 + 1:]
check(r.ok and len(m) == 1 and "AGB-Stand" not in m[0]["raw"], "terms=false: without the terms")
r = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-10-01", "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]})
INV = r.json()["id"]
r = A.post(B + f"{D}/{INV}/finalize")
check(r.ok, "setup: invoice finalised " + r.text[:200])
check(A.get(B + f"{D}/{INV}/terms").json()["default"] is False, "an invoice: not ticked by default")
n1 = len(mails())
A.post(B + f"{D}/{INV}/send", json={"to": "kunde@example.com", "datev": False})
A.post(B + f"{D}/{INV}/send", json={"to": "kunde@example.com", "datev": False, "terms": True})
m = mails()[n1:]
check(len(m) == 2 and "AGB-Stand" not in m[0]["raw"] and "AGB-Stand-2026-10-15.pdf" in m[1]["raw"], "an invoice: the terms only on request")

# ---------------------------------------------------------------- approval link
check(A.post(B + f"{D}/{Q}/status", json={"status": "sent"}).ok, "setup: quotation sent")
r = A.post(B + f"{D}/{Q}/signoff", json={})
check(r.ok, "approval link " + r.text[:160])
TOK = r.json()["url"].split("/s/q/")[1]
pg = anon("/s/q/" + TOK)
check(pg.status_code == 200 and f"/s/q/{TOK}/terms" in pg.text and "01.10.2026" in pg.text, "the customer page links the terms with their date")
r = anon(f"/s/q/{TOK}/terms")
check(r.status_code == 200 and r.content == DE1 and "AGB-Stand-2026-10-01.pdf" in r.headers.get("Content-Disposition", ""), f"/terms: the frozen file ({r.status_code})")
check("noindex" in r.headers.get("X-Robots-Tag", "") and r.headers.get("Referrer-Policy") == "no-referrer", "/terms: noindex, no referrer")
bad_t, bad_p = anon("/s/q/" + "x" * 43 + "/terms"), anon("/s/q/" + "x" * 43 + "/pdf")
check(bad_t.status_code == 404 and bad_t.status_code == bad_p.status_code and bad_t.text == bad_p.text, "a wrong token: the same 404 as /pdf")
check(A.post(B + f"{D}/{QE}/status", json={"status": "sent"}).ok, "setup: the English quotation sent")
TOKE = A.post(B + f"{D}/{QE}/signoff", json={}).json()["url"].split("/s/q/")[1]
check(anon(f"/s/q/{TOKE}/terms").status_code == 404 and "/terms" not in anon("/s/q/" + TOKE).text, "a link without terms: no link, 404")
r = requests.post(B + "/s/q/" + TOK, data={"f": form_key(pg.text), "name": "Max Muster", "ok": "1", "do": "accept"}, allow_redirects=False)
check(r.status_code == 303, f"the customer accepts ({r.status_code})")
done = anon("/s/q/" + TOK)
check("01.10.2026" in done.text and f"/s/q/{TOK}/terms" in done.text, "the confirmation names the terms state and keeps the download")
lg = A.get(B + f"{D}/{Q}/log").json()["log"]
acc = [x for x in lg if x["action"] == "signoff_accepted"]
check(acc and (acc[0].get("detail") or {}).get("terms") == {"lang": "de", "date": "2026-10-01", "sha256": SHA1}, f"the decision record names the terms {acc[:1]}")

# 2.113.2 (#2253) review: an open link of a quotation that is not finalised: other terms void it (the record never names unseen terms)
check(A.post(B + f"{D}/{Q2}/status", json={"status": "sent"}).ok, "setup: the unfinalised quotation sent")
TOK2 = A.post(B + f"{D}/{Q2}/signoff", json={}).json()["url"].split("/s/q/")[1]
check(anon(f"/s/q/{TOK2}/terms").content == DE2, "the unfinalised quotation's link serves the current terms")
check(upload(A, "de", DE1, date="2026-10-20", name="AGB A.pdf").ok, "setup: other German terms")
check(anon("/s/q/" + TOK2).status_code == 404 and anon(f"/s/q/{TOK2}/terms").status_code == 404, "other terms void the open link (404)")
check(A.post(B + f"{T}/de/restore", json={"sha256": SHA2, "date": "2026-10-15", "name": "AGB neu.pdf"}).ok, "setup: the terms of 15.10. back")

# ---------------------------------------------------------------- remove, undo (restore)
check(Bo.delete(B + f"{T}/de").status_code == 403, "a member cannot remove (403)")
r = A.delete(B + f"{T}/de")
check(r.ok and r.json()["terms"]["de"] is None and r.json()["removed"]["sha256"] == SHA2, "the admin removes the German terms")
REM = r.json()["removed"]
check(A.get(B + f"{T}/de/file").status_code == 404 and A.get(B + f"{D}/{Q2}/terms").json()["terms"] is None, "removed: no file, a draft has none")
check(A.get(B + f"{D}/{Q}/terms").json()["terms"]["sha256"] == SHA1 and anon(f"/s/q/{TOK}/terms").status_code == 200, "the finalised quotation and its link keep theirs")
check(A.delete(B + f"{T}/de").status_code == 404, "nothing to remove: 404")
check(Ca.post(B + f"{T}/de/restore", json=REM).status_code == 404, "another organisation cannot restore a state of this one (404)")
check(A.post(B + f"{T}/de/restore", json=dict(REM, sha256="0" * 64)).status_code == 404, "an unknown state: 404")
check(A.post(B + f"{T}/en/restore", json=REM).status_code == 404, "a state of the other language: 404")
r = A.post(B + f"{T}/de/restore", json=REM)
check(r.ok and r.json()["terms"]["de"]["sha256"] == SHA2 and r.json()["terms"]["de"]["date"] == "2026-10-15", "the undo puts the state back")
lg = A.get(B + O + "/log?limit=20").json()["log"]
check({"delete", "restore"} <= {x["action"] for x in lg if x["target"] == "terms"}, "office log: remove and restore")

# ---------------------------------------------------------------- a contract from a template keeps the terms on its link
TC = A.post(B + O + "/doc-templates", json={"starter": "contract"}).json()["id"]
G = A.post(B + GD, json={"template_id": TC, "client_id": CL}).json()["id"]
check(A.post(B + f"{GD}/{G}/final").ok, "setup: the contract is finished")
gz = json.loads(sql("SELECT terms FROM office_gen_docs WHERE id=?", (G,))[0][0] or "{}")
check(gz.get("sha256") == SHA2 and gz.get("lang") == "de", f"finishing a contract froze the terms {gz}")
r = A.post(B + f"{GD}/{G}/signoff", json={})
GT = r.json()["url"].split("/s/q/")[1] if r.ok else ""
check(r.ok and f"/s/q/{GT}/terms" in anon("/s/q/" + GT).text, "the contract's link offers the terms")
r = anon(f"/s/q/{GT}/terms")
check(r.status_code == 200 and r.content == DE2, "the contract's link serves its frozen terms")
TN = A.post(B + O + "/doc-templates", json={"starter": "nda"}).json()["id"]
GN = A.post(B + GD, json={"template_id": TN, "client_id": CL}).json()["id"]
A.post(B + f"{GD}/{GN}/final")
check(sql("SELECT terms FROM office_gen_docs WHERE id=?", (GN,))[0][0] is None, "a non-disclosure agreement carries no terms")

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
check(Fr.get(B + T).json()["terms"] == {"de": None, "en": None} and Fr.get(B + T).json()["admin"] is True, "freelancer: own empty terms, own admin")
r = upload(Fr, "en", EN1, date="2026-09-30", name="Terms.pdf")
check(r.ok and r.json()["terms"]["en"]["date"] == "2026-09-30", f"freelancer: uploads English terms {r.status_code} {r.text[:160]}")
check(Fr.get(B + f"{T}/en/file").content == EN1 and A.get(B + f"{T}/en/file").status_code == 404, "freelancer: the file is theirs only")
FCL = Fr.post(B + "/api/clients", json={"name": "Private Client Ltd", "street": "1 High Street", "zip": "10115", "city": "Berlin", "country": "DE"}).json()["id"]
r = Fr.post(B + D, json={"kind": "offer", "client_id": FCL, "lang": "en", "items": [{"title": "Edit", "qty": 1, "rate": 500}]})
FQ = r.json()["id"] if r.status_code == 201 else 0
check(r.status_code == 201 and Fr.get(B + f"{D}/{FQ}/terms").json()["terms"]["date"] == "2026-09-30", "freelancer: the quotation has the terms")
check(Fr.get(B + f"{D}/{FQ}/render").json().get("terms_line") == "Our terms and conditions (as of 30.09.2026) apply, see attachment."
      or Fr.get(B + f"{D}/{FQ}/render").json().get("terms_line", "").startswith("Our terms and conditions (as of "), "freelancer: the English line")
check(Fr.post(B + f"{D}/{FQ}/finalize").ok, "freelancer: finalises")
n2 = len(mails())
r = Fr.post(B + f"{D}/{FQ}/send", json={"to": "client@example.com"})
check(r.ok and "Terms-2026-09-30.pdf" in (mails()[n2:] or [{"raw": ""}])[0]["raw"], "freelancer: the mail carries Terms-2026-09-30.pdf")
r = Fr.delete(B + f"{T}/en")
check(r.ok and Fr.post(B + f"{T}/en/restore", json=r.json()["removed"]).ok and Fr.get(B + T).json()["terms"]["en"], "freelancer: remove + undo")
check(Fr.get(B + f"{D}/{Q}/terms").status_code == 404, "freelancer: a document of an organisation is 404")

print(f"p2113c_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
