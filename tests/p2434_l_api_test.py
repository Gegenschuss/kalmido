#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.434.0 (#3619, #3616) API tests of the office's outgoing PDFs. Own container (start.sh, mode workspaces, organisation
encryption on) with the SMTP stub (stub_mail.py). Invented companies, people and files only.
 - #3619: a quotation with the terms line carries the terms pages behind its own wherever its PDF goes out: download /
   preview (draft and finalised), the mail (no second terms file any more, the log still names the state), the approval
   link (/s/q/<token>/pdf); the stored PDF stays as it was finalised (pdf_sha256 unchanged); invoices stay without them;
   terms that pypdf cannot read: the PDF unchanged (no 500), the mail sends them as their own file as before
 - #3616: a ZUGFeRD invoice goes out by mail (and to the DATEV inbox) as the PDF alone - its XML is inside; an XRechnung
   (client with a buyer reference) still gets the XML as its own file; GET .../xml stays
 - a person without an organisation (freelancer-matrix: office): the same in the personal office
usage: p2434_l_api_test.py <datadir>      (P2434L_NOSTART=1: a running server on KALMIDO_TEST_PORT with the SMTP sink)"""
import base64
import email
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "cal,comments,collab,office,clients,docs,time"
O = "/api/office"
D = O + "/docs"
T = O + "/terms"
ENV = ["-e", "KALMIDO_INSTANCE_MODE=workspaces", "-e", "KALMIDO_ORGCRYPT_DELAY=0", "-e", f"KALMIDO_SECRET_KEY={KEY}",
       "-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none", "-e", "KALMIDO_MAIL_FROM=kalmido@example.test"]
COMPANY = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
           "email": "hallo@nordlicht.example", "phone": "+49 40 000000", "tax_number": "12/345/67890", "vat_id": "DE999999999",
           "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank"}


def real_pdf(*marks):
    """A small valid PDF (one page per mark, the mark as uncompressed text) that pypdf can read."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for m in marks:
        body = b"BT /F1 12 Tf 72 720 Td (" + m.encode() + b") Tj ET"
        objs.append(b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream")
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % len(objs))
        kids.append(len(objs))
    objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def fake_pdf(tag):
    """Only the PDF header (the upload checks the header only): pypdf cannot read it."""
    return b"%PDF-1.4\n% invented terms " + tag.encode() + b"\n" + os.urandom(64).hex().encode() + b"\n%%EOF\n"


def pages(data):
    return len(re.findall(rb"/Type\s*/Page(?![a-z])", data))


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def upload(s, lang, data, date, name="AGB Beispiel.pdf"):
    return s.post(B + f"{T}/{lang}", files={"file": (name, data, "application/pdf")}, data={"date": date})


def mails():
    p = os.path.join(DATA, "mail", "out.jsonl")
    return [json.loads(x) for x in open(p, encoding="utf-8").read().splitlines()] if os.path.exists(p) else []


def attachments(m):
    """{file name: bytes} of a sunk mail."""
    msg = email.message_from_string(m["raw"])
    return {p.get_filename(): p.get_payload(decode=True) for p in msg.walk() if p.get_filename()}


def sent(s, did, **kw):
    """Sends document did and returns the attachments of the mails it produced."""
    n0 = len(mails())
    r = s.post(B + f"{D}/{did}/send", json=dict({"to": "kunde@example.com"}, **kw))
    assert r.ok, r.text
    return [attachments(m) for m in mails()[n0:]]


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


if not os.environ.get("P2434L_NOSTART"):
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
r = A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": COMPANY, "payment_days": 14, "datev_email": "belege@datev.example"})
check(r.ok, "setup: office settings " + r.text[:160])
CL = A.post(B + "/api/clients", json={"name": "Beispielkunde AG", "street": "Marktstraße 5", "zip": "50667", "city": "Köln", "country": "DE",
                                       "email": "kunde@example.com"}).json()["id"]
CLX = A.post(B + "/api/clients", json={"name": "Stadtwerke Beispiel", "street": "Amtsweg 1", "zip": "50667", "city": "Köln", "country": "DE",
                                        "email": "rechnung@stadt.example", "buyer_reference": "991-12345-67"}).json()["id"]
AGB = real_pdf("AGBSEITE-EINS", "AGBSEITE-ZWEI")
check(upload(A, "de", AGB, "2026-10-01").ok, "setup: German terms (two pages)")

# ---------------------------------------------------------------- #3619 the quotation PDF carries the terms pages
Q = A.post(B + D, json={"kind": "offer", "client_id": CL, "project_title": "Imagefilm", "items": [{"title": "Schnitt", "qty": 2, "rate": 900}]}).json()["id"]
check((A.get(B + f"{D}/{Q}/render").json().get("terms_line") or "").startswith("Es gelten unsere AGB"), "setup: the draft prints the terms line")
p = A.get(B + f"{D}/{Q}/pdf?inline=1")
check(p.ok and p.content[:5] == b"%PDF-" and b"AGBSEITE-EINS" in p.content and b"AGBSEITE-ZWEI" in p.content,
      f"#3619: the draft's preview has the terms pages behind it ({p.status_code})")
own = pages(p.content) - 2
check(own >= 1, f"#3619: own pages + 2 terms pages ({pages(p.content)})")
r = A.post(B + f"{D}/{Q}/finalize")
check(r.ok, "the quotation is finalised " + r.text[:160])
sha = sql("SELECT pdf_sha256 FROM office_docs WHERE id=?", (Q,))[0][0]
p = A.get(B + f"{D}/{Q}/pdf")
check(p.ok and b"AGBSEITE-ZWEI" in p.content and pages(p.content) == own + 2, "#3619: the finalised quotation's download carries the frozen terms")
check(sha and hashlib.sha256(p.content).hexdigest() != sha and sql("SELECT pdf_sha256 FROM office_docs WHERE id=?", (Q,))[0][0] == sha,
      "#3619: joined on output - the stored PDF and its hash stay as finalised")
at = sent(A, Q)
check(len(at) == 1 and len(at[0]) == 1 and not any(n.startswith("AGB-Stand") for n in at[0]), f"#3619: the mail has one file, no extra terms file {list(at[0]) if at else at}")
pdf = next(iter(at[0].values())) if at and at[0] else b""
check(b"AGBSEITE-EINS" in pdf and pages(pdf) == own + 2, "#3619: the mailed PDF ends with the terms pages")
snd = [x for x in A.get(B + f"{D}/{Q}/log").json()["log"] if x["action"] == "send"]
check(snd and ((snd[0].get("detail") or {}).get("terms") or {}).get("date") == "2026-10-01", f"#3619: the log still names the terms state {snd[:1]}")
j = A.get(B + f"{D}/{Q}/terms").json()
check(j.get("in_pdf") is True, "#3619: the send dialog learns the terms are inside the PDF (in_pdf)")
check(A.post(B + f"{D}/{Q}/status", json={"status": "sent"}).ok, "setup: quotation sent")
r = A.post(B + f"{D}/{Q}/signoff", json={})
TOK = r.json()["url"].split("/s/q/")[1] if r.ok else "x"
p = requests.get(B + f"/s/q/{TOK}/pdf")
check(p.status_code == 200 and b"AGBSEITE-ZWEI" in p.content, f"#3619: the approval link's PDF carries the terms ({p.status_code})")
check(requests.get(B + f"/s/q/{TOK}/terms").content == AGB, "#3619: the link's own terms download stays")

# invoices stay as they are
INV = A.post(B + D, json={"kind": "invoice", "client_id": CL, "service_from": "2026-10-01", "items": [{"title": "Schnitt", "qty": 1, "rate": 100}]}).json()["id"]
check(A.post(B + f"{D}/{INV}/finalize").ok, "setup: ZUGFeRD invoice finalised")
check(b"AGBSEITE" not in A.get(B + f"{D}/{INV}/pdf").content, "#3619: an invoice PDF stays without the terms pages")
check(A.get(B + f"{D}/{INV}/terms").json().get("in_pdf") is False, "#3619: an invoice keeps the tick (in_pdf false)")

# ---------------------------------------------------------------- #3616 ZUGFeRD = the PDF alone, XRechnung = + XML
at = sent(A, INV, datev=False)
names = list(at[0]) if at else []
check(len(names) == 1 and names[0].endswith(".pdf"), f"#3616: a ZUGFeRD invoice goes out as the PDF alone {names}")
check(b"factur-x.xml" in (at[0][names[0]] if names else b""), "#3616: ... and that PDF carries its factur-x.xml")
x = A.get(B + f"{D}/{INV}/xml")
check(x.ok and x.content.lstrip().startswith(b"<?xml"), "#3616: the XML download in the invoice stays")
at = sent(A, INV, datev=True)
check(len(at) == 2 and all(len(a) == 1 and list(a)[0].endswith(".pdf") for a in at), f"#3616: the DATEV copy follows the same rule {[list(a) for a in at]}")
XR = A.post(B + D, json={"kind": "invoice", "client_id": CLX, "service_from": "2026-10-01", "items": [{"title": "Beratung", "qty": 1, "rate": 200}]}).json()["id"]
r = A.post(B + f"{D}/{XR}/finalize")
check(r.ok, "setup: XRechnung finalised " + r.text[:200])
at = sent(A, XR, datev=False)
names = sorted(at[0]) if at else []
check(len(names) == 2 and names[0].endswith(".pdf") and names[1].endswith(".xml") and b"xrechnung" in at[0][names[1]],
      f"#3616: an XRechnung keeps the XML as its own file next to the PDF {names}")

# ---------------------------------------------------------------- #3619 terms pypdf cannot read: no 500, the old way in the mail
check(upload(A, "de", fake_pdf("kaputt"), "2026-10-20").ok, "setup: terms with only a PDF header")
Q2 = A.post(B + D, json={"kind": "offer", "client_id": CL, "items": [{"title": "Ton", "qty": 1, "rate": 300}]}).json()["id"]
p = A.get(B + f"{D}/{Q2}/pdf")
check(p.status_code == 200 and p.content[:5] == b"%PDF-" and b"invented terms kaputt" not in p.content, f"#3619: unreadable terms - the PDF without them, no 500 ({p.status_code})")
at = sent(A, Q2)
check(len(at) == 1 and any(n.startswith("AGB-Stand-2026-10-20") for n in at[0]), f"#3619: ... and the mail sends them as their own file {list(at[0]) if at else at}")

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: office
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
check(Fr.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": COMPANY, "payment_days": 14}).ok, "freelancer: office settings")
check(upload(Fr, "de", real_pdf("FREI-AGB"), "2026-09-30").ok, "freelancer: own terms")
FCL = Fr.post(B + "/api/clients", json={"name": "Privatkunde GmbH", "street": "Hauptstraße 1", "zip": "10115", "city": "Berlin", "country": "DE",
                                         "email": "kunde@example.com"}).json()["id"]
FQ = Fr.post(B + D, json={"kind": "offer", "client_id": FCL, "items": [{"title": "Kamera", "qty": 1, "rate": 500}]}).json()["id"]
check(Fr.post(B + f"{D}/{FQ}/finalize").ok, "freelancer: quotation finalised")
check(b"FREI-AGB" in Fr.get(B + f"{D}/{FQ}/pdf").content and b"AGBSEITE" not in Fr.get(B + f"{D}/{FQ}/pdf").content,
      "freelancer #3619: the own terms behind the quotation (never the organisation's)")
at = sent(Fr, FQ)
check(len(at) == 1 and len(at[0]) == 1 and b"FREI-AGB" in next(iter(at[0].values())), "freelancer #3619: the mail carries one PDF with the terms")
FI = Fr.post(B + D, json={"kind": "invoice", "client_id": FCL, "service_from": "2026-10-01", "items": [{"title": "Kamera", "qty": 1, "rate": 500}]}).json()["id"]
check(Fr.post(B + f"{D}/{FI}/finalize").ok, "freelancer: invoice finalised")
at = sent(Fr, FI, datev=False)
check(len(at) == 1 and [n[-4:] for n in at[0]] == [".pdf"], f"freelancer #3616: the ZUGFeRD invoice as the PDF alone {[list(a) for a in at]}")
check(A.get(B + f"{D}/{FQ}/pdf").status_code == 404, "freelancer: the organisation cannot read the personal quotation")

print(f"p2434_l_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
