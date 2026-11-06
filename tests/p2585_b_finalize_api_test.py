#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.585.0 B (#4288) API tests: finalising invoices under pressure. Own container (start.sh, mode workspaces) with the SMTP
sink (stub_mail.py). Invented companies, people and the test IBAN only. Run for an organisation's office and for a person
without an organisation (freelancer fixture; freelancer-matrix: office).
 - two finalise calls on the same invoice at once (two threads behind a barrier): one 200, one 409, and the invoice carries
   the next number of the series; two different invoices at once: both 200 with the next two numbers (no number twice)
 - a finalising that fails after the number was drawn (XRechnung without the client's buyer reference, 400 at storing)
   uses up no number: the draft stays without one, the next invoice gets the next number - also when both run at once
 - at the end the series of finalised invoices is gap-free (1..n, every number once)
 - the mail attachment is the stored PDF (SHA-256 = pdf_sha256 of the document); a stored PDF changed underneath: the send
   answers 409, no mail goes out and the document is not marked sent
usage: p2585_b_finalize_api_test.py <datadir>      (P2585B_NOSTART=1: a running server on KALMIDO_TEST_PORT with the SMTP sink)"""
import email
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import date

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer, login  # noqa: E402
from kt import CT, FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
D = O + "/docs"
FEAT = "cal,comments,collab,office,clients,docs,time"
ENV = ["-e", "KALMIDO_INSTANCE_MODE=workspaces",
       "-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none", "-e", "KALMIDO_MAIL_FROM=kalmido@example.test"]
COMPANY = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hallo@nordlicht.example", "phone": "+49 40 000000", "tax_number": "12/345/67890", "vat_id": "DE999999999",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}
YEAR = date.today().year


def sh(cmd, data=None):
    return subprocess.run(["docker", "exec", "-i", CT, "sh", "-c", cmd], input=data, capture_output=True, timeout=60)


def start():
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(ENV)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    for _ in range(50):  # the sink is up once its port answers (a real state, not a fixed time)
        if subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1025), 1)"],
                          capture_output=True).returncode == 0:
            break
        time.sleep(0.2)


def mails():
    p = os.path.join(DATA, "mail", "out.jsonl")
    return [json.loads(x) for x in open(p, encoding="utf-8").read().splitlines()] if os.path.exists(p) else []


def attachments(m):
    """{file name: bytes} of a sunk mail."""
    msg = email.message_from_string(m["raw"])
    return {p.get_filename(): p.get_payload(decode=True) for p in msg.walk() if p.get_filename()}


def at_once(*calls):
    """Runs the calls in threads released together by a barrier -> their responses in call order."""
    bar, out = threading.Barrier(len(calls)), [None] * len(calls)

    def run(i, fn):
        bar.wait()
        out[i] = fn()
    ts = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return out


def office(who, S, S2):
    """All checks in the office the sessions S / S2 (the same person, two logins) work in."""
    r = S.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": COMPANY, "company": {"name": COMPANY["name"]},
                                         "payment_days": 14, "datev_auto": 0, "datev_email": ""})
    check(r.ok, f"{who}: setup office settings " + r.text[:160])
    scheme = S.get(B + O + "/settings").json()["settings"].get("invoice_scheme") or ""
    check("{yyyy}" in scheme and "{seq" in scheme, f"{who}: setup the invoice scheme holds the year and the counter ({scheme!r})")
    pat = re.compile("^" + re.escape(scheme).replace(re.escape("{yyyy}"), str(YEAR)).replace(re.escape("{seq:03}"), r"(\d+)")
                     .replace(re.escape("{seq}"), r"(\d+)") + "$")
    r = S.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
                                         "email": "kunde@example.com"})
    assert r.status_code == 201, r.text
    cl = r.json()["id"]

    def seq(n):
        m = pat.match(n or "")
        return int(m.group(1)) if m else None

    def invoice(**kw):
        r = S.post(B + D, json=dict({"kind": "invoice", "client_id": cl, "service_from": f"{YEAR}-01-01", "service_to": f"{YEAR}-01-20",
                                     "einvoice_format": "zugferd", "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]}, **kw))
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def doc(did):
        return S.get(B + f"{D}/{did}").json()

    def finals():
        """The counter values of the office's finalised invoices of this year."""
        return sorted(seq(x.get("number")) for x in S.get(B + D, params={"kind": "invoice"}).json().get("docs", [])
                      if x.get("locked") and seq(x.get("number")) is not None)

    def fin(s, did):
        return lambda: s.post(B + f"{D}/{did}/finalize")

    # ------------------------------------------------------------ the same invoice twice at once: 200 + 409, the next number
    bad = []
    for i in range(5):
        last = max(finals() or [0])
        I = invoice()
        a, b = at_once(fin(S, I), fin(S2, I))
        d = doc(I)
        if sorted((a.status_code, b.status_code)) != [200, 409] or not d.get("locked") or seq(d.get("number")) != last + 1:
            bad.append((i, a.status_code, b.status_code, d.get("number"), last, (a.text if not a.ok else b.text)[:120]))
    check(not bad, f"{who}: #4288 the same invoice finalised twice at once: one 200, one 409, the next number {bad}")

    # ------------------------------------------------------------ two invoices at once: both 200, the next two numbers
    bad = []
    for i in range(3):
        last = max(finals() or [0])
        I, J = invoice(), invoice()
        a, b = at_once(fin(S, I), fin(S2, J))
        got = sorted([seq(doc(I).get("number")) or 0, seq(doc(J).get("number")) or 0])
        if not (a.ok and b.ok) or got != [last + 1, last + 2]:
            bad.append((i, a.status_code, b.status_code, got, last))
    check(not bad, f"{who}: #4288 two invoices finalised at once: both 200 with the next two numbers {bad}")

    # ------------------------------------------------------------ a failed finalising uses up no number
    last = max(finals() or [0])
    X = invoice(einvoice_format="xrechnung")  # the client has no buyer reference: the XML fails at storing, after the number
    r = S.post(B + f"{D}/{X}/finalize")
    d = doc(X)
    check(r.status_code == 400 and "buyer reference" in r.text.lower(), f"{who}: precondition XRechnung without a buyer reference: 400 {r.status_code} {r.text[:160]}")
    check(not d.get("locked") and not d.get("number") and not d.get("pdf_sha256"), f"{who}: #4288 ... the draft stays without a number ({d.get('number')!r})")
    I = invoice()
    r = S.post(B + f"{D}/{I}/finalize")
    check(r.ok and seq(doc(I).get("number")) == last + 1, f"{who}: #4288 ... the next invoice gets the next number {last + 1} ({doc(I).get('number')!r})")
    bad = []
    for i in range(3):  # the failing one and a good one at once: the good one draws the next number, no gap
        last = max(finals() or [0])
        I = invoice()
        a, b = at_once(fin(S, X), fin(S2, I))
        dx, di = doc(X), doc(I)
        if a.status_code != 400 or not b.ok or dx.get("number") or seq(di.get("number")) != last + 1:
            bad.append((i, a.status_code, b.status_code, dx.get("number"), di.get("number"), last))
    check(not bad, f"{who}: #4288 a failing and a good finalising at once: the good one has the next number, the failed one none {bad}")

    # ------------------------------------------------------------ the series is gap-free
    f = finals()
    check(f and f == list(range(1, len(f) + 1)), f"{who}: #4288 the finalised invoices of {YEAR} are numbered 1..{len(f)} without a gap or a twin {f}")

    # ------------------------------------------------------------ the mail carries the stored PDF, a changed file sends nothing
    I = invoice()
    r = S.post(B + f"{D}/{I}/finalize")
    sha = (r.json() if r.ok else {}).get("pdf_sha256") or ""
    check(r.ok and len(sha) == 64, f"{who}: setup finalised with pdf_sha256 {r.status_code} {r.text[:160]}")
    n0 = len(mails())
    r = S.post(B + f"{D}/{I}/send", json={"to": "kunde@example.com"})
    new = mails()[n0:]
    at = attachments(new[0]) if new else {}
    pdfs = [v for k, v in at.items() if k.endswith(".pdf")]
    check(r.ok and len(new) == 1 and len(pdfs) == 1, f"{who}: setup one mail with one PDF {r.status_code} {len(new)} {list(at)}")
    check(pdfs and hashlib.sha256(pdfs[0]).hexdigest() == sha, f"{who}: #4288 the mailed PDF is the stored one (SHA-256 = pdf_sha256)")
    J = invoice()
    r = S.post(B + f"{D}/{J}/finalize")
    check(r.ok, f"{who}: setup a second invoice finalised")
    p = sh(f"ls /data/office/*/doc{J}-*.pdf").stdout.decode().split()
    w = sh(f"cat > {p[0]}", b"%PDF-1.7\n% changed underneath\n%%EOF\n") if len(p) == 1 else None
    check(w is not None and w.returncode == 0, f"{who}: setup the stored PDF changed underneath ({p})")
    n0 = len(mails())
    r = S.post(B + f"{D}/{J}/send", json={"to": "kunde@example.com"})
    check(r.status_code == 409 and "checksum" in r.text, f"{who}: #4288 a changed stored PDF: send 409 {r.status_code} {r.text[:160]}")
    check(len(mails()) == n0, f"{who}: #4288 ... and no mail went out ({len(mails()) - n0})")
    check(doc(J).get("status") != "sent", f"{who}: #4288 ... the invoice is not marked sent ({doc(J).get('status')!r})")


if not os.environ.get("P2585B_NOSTART"):
    start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
office("org", A, sess("alice"))
FID, Fr = freelancer(B, A)
office("freelancer", Fr, login(B, "frida"))

print(f"p2585_b_finalize_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
