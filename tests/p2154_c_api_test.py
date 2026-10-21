#!/usr/bin/env python3
"""2.154.0 C (#2192) API tests: data protection sheets of a client (DPA, privacy information, consent). Own container in mode
workspaces, organisation encryption on, the IMAP + SMTP stubs of stub_mail.py. Invented companies, people and files only.
tenant-matrix: office
 - samples: the three sheets are samples of the document templates (German / English, the note "sample text, no legal
   advice" in brackets, only known variables)
 - a sheet from the sample keeps [placeholders] -> a draft for the editor (edit = true); finishing it in the editor makes
   it a finished sheet; a sheet from an own template without placeholders is finished at once (PDF filed with the client)
 - mail: the proposed mail (recipient from the client, subject, text with [Link]); the privacy information is "handed"
   after sending; a DPA / consent gets the signature link and the code in subject + Reply-To (plus address), status sent;
   the code is sealed at rest; 409 for a draft
 - ways back: signing through the link -> signed (link); upload of a PDF -> signed (upload), a text file 400; a reply mail
   with the code (subject or plus address) and a PDF -> "signed (by mail, please check)", filed in the sheet's office
   area; confirm ends the check; an unknown code / no PDF / a sheet not mailed changes nothing
 - status by hand, archive + restore, the list filter data (brief)
 - rights: a member 403, an agent 403, another organisation 404 (client and sheet); a mail code of another organisation
   files only into that organisation
 - a person without an organisation (freelancer-matrix: office): the same in the personal office
usage: p2154_c_api_test.py <datadir>      (P2154C_NOSTART=1: a running server on KALMIDO_TEST_PORT with the mail stubs)"""
import base64
import email
import email.message
import email.policy
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

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,office,clients,docs"
O = "/api/office"
PS = O + "/privacy-sheets"
TP = O + "/doc-templates"
GD = O + "/gen-docs"
ENV = ["-e", "KALMIDO_INSTANCE_MODE=workspaces", "-e", "KALMIDO_ORGCRYPT_DELAY=0", "-e", f"KALMIDO_SECRET_KEY={KEY}",
       "-e", "KALMIDO_MAIL_ADDRESS=tasks@example.test", "-e", "KALMIDO_IMAP_HOST=127.0.0.1", "-e", "KALMIDO_IMAP_PORT=1143",
       "-e", "KALMIDO_IMAP_SSL=0", "-e", "KALMIDO_IMAP_USER=kalmido", "-e", "KALMIDO_IMAP_PASSWORD=secret", "-e", "KALMIDO_IMAP_INTERVAL=10",
       "-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none", "-e", "KALMIDO_MAIL_FROM=kalmido@example.test"]
VARS = {"client.name", "client.address", "client.contact", "project.title", "offer.number", "offer.date", "offer.total", "company.name",
        "company.address", "today"}
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


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


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def until(fn, secs=40):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def mails():
    p = os.path.join(DATA, "mail", "out.jsonl")
    return [json.loads(x) for x in open(p, encoding="utf-8").read().splitlines()] if os.path.exists(p) else []


def parse(m):
    return email.message_from_string(m["raw"], policy=email.policy.default)


def body_of(msg):
    b = msg.get_body(preferencelist=("plain",))
    return b.get_content() if b else ""


def attachments(msg):
    return [(p.get_filename(), p.get_payload(decode=True)) for p in msg.iter_attachments()]


DROPS = [100]


def drop(subj, to="tasks@example.test", files=(), frm="Kunde <kunde@example.com>"):
    DROPS[0] += 1
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = frm, to, subj, f"<ds{DROPS[0]}@client.test>"
    m.set_content("Anbei unterschrieben zurück.")
    for name, data, mime in files:
        main, _, sub = mime.partition("/")
        m.add_attachment(data, maintype=main, subtype=sub, filename=name)
    open(os.path.join(DATA, "mail", "in", f"{DROPS[0]}.eml"), "wb").write(bytes(m))


def poll():
    A.post(B + "/api/admin/mail/poll")
    n = DROPS[0]
    until(lambda: str(n) in (open(os.path.join(DATA, "mail", "seen")).read().split() if os.path.exists(os.path.join(DATA, "mail", "seen")) else []))
    time.sleep(0.5)


def sheet(s, sid):
    return next((x for x in s.get(B + PS + "?archived=1&brief=1").json()["sheets"] if x["id"] == sid), None)


def form_key(html):
    m = re.search(r'name="f" value="([0-9a-f]+)"', html)
    return m.group(1) if m else ""


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


if not os.environ.get("P2154C_NOSTART"):
    start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
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
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
A.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Beispiel Studio GmbH", "street": "Musterweg 1",
                                                                                   "zip": "12345", "city": "Musterstadt", "country": "DE"}})
Ca.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Beta Werkstatt", "city": "Beispielstadt"}})
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH", "street": "Kundenweg 5", "zip": "20000", "city": "Hamburg", "country": "DE",
                                       "contact": "Erika Beispiel", "email": "kunde@example.com"}).json()["id"]
CL2 = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG", "email": "fremd@example.com"}).json()["id"]
check(A.get(B + O + "/mail-status").json().get("smtp"), "setup: SMTP sink")

# ================================================================== samples
st = A.get(B + TP + "/starters").json()
sm = {x["key"]: x for x in st["starters"]}
check({"privacy_dpa", "privacy_info", "privacy_consent"} <= set(sm), f"#2192: the three sheets are samples {list(sm)}")
for k in ("privacy_dpa", "privacy_info", "privacy_consent"):
    x = sm.get(k) or {"body": "", "name": ""}
    used = set(re.findall(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}", x["body"]))
    check(x["body"].startswith("# ") and "[Mustertext, keine Rechtsberatung" in x["body"] and used and used <= VARS and x.get("legal") == 1,
          f"#2192: {k} German, the note in brackets, known variables only {used - VARS}")
ste = {x["key"]: x for x in A.get(B + TP + "/starters?lang=en").json()["starters"]}
check("[Sample text, no legal advice" in ste["privacy_dpa"]["body"] and "Art. 28(3)(a) GDPR" in ste["privacy_dpa"]["body"], "#2192: the English DPA sample")
check("Art. 28 Abs. 3 lit. a DSGVO" in sm["privacy_dpa"]["body"] and "Art. 77 DSGVO" in sm["privacy_info"]["body"]
      and "Art. 7 Abs. 3 DSGVO" in sm["privacy_consent"]["body"], "#2192: the German samples name their articles")

# ================================================================== list + create
j = A.get(B + PS + f"?client_id={CL}").json()
check(j["sheets"] == [] and [k["key"] for k in j["kinds"]] == ["dpa", "info", "consent"], f"#2192: no sheet yet, three kinds {j.get('kinds')}")
check(j["kinds"][0]["hint"] and "Art. 28" in j["kinds"][0]["hint"] and not j["kinds"][1]["sign"] and j["kinds"][0]["sign"], "#2192: the DPA hint, info needs no signature")
check(j["smtp"] and j["reply_in"], "#2192: mail out + reply mailbox set up")
check(A.post(B + PS, json={"client_id": CL, "kind": "lease"}).status_code == 400, "#2192: an unknown kind 400")
check(A.post(B + PS, json={"kind": "dpa"}).status_code in (400, 404), "#2192: no client 400 / 404")
r = A.post(B + PS, json={"client_id": CL, "kind": "info"})
check(r.status_code == 201 and r.json()["edit"] and r.json()["sheet"]["gen_status"] == "draft" and r.json()["sheet"]["status"] == "open",
      f"#2192: from the sample: a draft for the editor ({r.status_code} {r.text[:200]})")
S_INFO = r.json()["sheet"]
G_INFO = S_INFO["gen_doc_id"]
check(A.get(B + PS + f"/{S_INFO['id']}/mail").status_code == 409, "#2192: no mail for a draft")
check(A.patch(B + f"{GD}/{G_INFO}", json={"body": "# Datenschutzhinweise\n\nVerantwortlich: {{company.name}}\n\nFür {{client.name}}"}).ok, "#2192: the draft edited")
r = A.post(B + f"{GD}/{G_INFO}/final")
check(r.ok and r.json()["status"] == "final" and r.json()["node_id"], f"#2192: the draft finished in the editor ({r.status_code})")
x = sheet(A, S_INFO["id"])
check(x and x["gen_status"] == "final" and x["node_id"] and x["status"] == "open", f"#2192: the sheet follows its document {x}")
check(sql("SELECT sign FROM office_gen_docs WHERE id=?", (G_INFO,))[0][0] == 0, "#2192: the information is not signable")

T_SIGN = A.post(B + TP, json={"kind": "other", "name": "AVV kurz", "lang": "de", "sign": 1,
                              "body": "# AVV\n\nZwischen {{client.name}} und {{company.name}}.\n\n## Gegenstand\nPflege der Kundendaten."}).json()["id"]
r = A.post(B + PS, json={"client_id": CL, "kind": "dpa", "template_id": T_SIGN})
check(r.status_code == 201 and not r.json()["edit"] and r.json()["sheet"]["gen_status"] == "final" and r.json()["sheet"]["node_id"],
      f"#2192: an own template without placeholders: finished at once ({r.status_code} {r.text[:200]})")
S_DPA = r.json()["sheet"]
p = A.get(B + PS + f"/{S_DPA['id']}/pdf")
check(p.ok and p.content.startswith(b"%PDF-") and "no-store" in p.headers.get("Cache-Control", ""), "#2192: the sheet's PDF")
nd = sql("SELECT name, org_id FROM fs_nodes WHERE id=(SELECT parent_id FROM fs_nodes WHERE id=?)", (S_DPA["node_id"],))
check(nd and nd[0][0] == "Kunde Eins GmbH" and nd[0][1] == ORG, f"#2192: the PDF is filed in the client's folder {nd}")
check(A.get(B + PS + f"/{S_DPA['id']}/pdf?signed=1").status_code == 404, "#2192: no signed file yet")

# ================================================================== mail: information = handed over
m = A.get(B + PS + f"/{S_INFO['id']}/mail").json()
check(m["to"] == "kunde@example.com" and "[DS-" not in m["subject"] and not m["reply_in"] and not m["link"] and "[Link]" not in m["text"],
      f"#2192: the information's mail: no code, no link {m}")
n0 = len(mails())
r = A.post(B + PS + f"/{S_INFO['id']}/send", json={"to": "kunde@example.com"})
check(r.ok and r.json()["status"] == "handed" and r.json()["sent_at"], f"#2192: sent = handed over ({r.status_code} {r.text[:200]})")
ms = mails()[n0:]
msg = parse(ms[0]) if ms else None
check(msg is not None and ms[0]["to"] == ["kunde@example.com"] and any(n.endswith(".pdf") and d.startswith(b"%PDF-") for n, d in attachments(msg)),
      "#2192: the mail went out with the PDF")
check(msg is not None and "anbei erhalten Sie unser Dokument" in body_of(msg) and "/s/q/" not in body_of(msg), "#2192: German text, no link")
check(A.post(B + PS + f"/{S_INFO['id']}/send", json={"to": "no address"}).status_code == 400, "#2192: a bad address 400")

# ================================================================== mail: DPA = sent, link + code
m = A.get(B + PS + f"/{S_DPA['id']}/mail").json()
code = (re.search(r"\[DS-([A-Z2-9]{12})\]", m["subject"]) or [None, ""])[1]
check(code and m["reply_in"] and m["link"] and "[Link]" in m["text"], f"#2192: the DPA's mail: code + link {m}")
row = sql("SELECT code, code_hash FROM office_privacy_sheets WHERE id=?", (S_DPA["id"],))[0]
check(row[1] and code not in row[0] and code not in row[1], "#2192: the code is sealed, only its hash is plain")
n0 = len(mails())
r = A.post(B + PS + f"/{S_DPA['id']}/send", json={"to": "kunde@example.com", "subject": "Unser AVV", "text": "Bitte hier unterschreiben: [Link]"})
check(r.ok and r.json()["status"] == "sent", f"#2192: the DPA sent ({r.status_code} {r.text[:200]})")
ms = mails()[n0:]
msg = parse(ms[0]) if ms else None
tok = re.search(r"/s/q/([A-Za-z0-9_-]{20,})", body_of(msg)) if msg else None
check(msg is not None and str(msg["Subject"]).startswith("Unser AVV") and f"[DS-{code}]" in str(msg["Subject"]), f"#2192: own subject keeps the code {msg and msg['Subject']}")
check(msg is not None and str(msg["Reply-To"]) == f"tasks+ds-{code}@example.test", f"#2192: the reply address with the code {msg and msg['Reply-To']}")
check(tok is not None and "[Link]" not in body_of(msg), "#2192: [Link] became the signature link")

# ================================================================== the way back: the customer signs through the link
pg = requests.get(B + "/s/q/" + tok.group(1)) if tok else None
check(pg is not None and pg.ok and "Pflege der Kundendaten" in pg.text, "#2192: the customer page shows the sheet")
r = requests.post(B + "/s/q/" + tok.group(1), data={"f": form_key(pg.text), "name": "Erika Beispiel", "ok": "1", "do": "accept"},
                  allow_redirects=False, headers={"User-Agent": "TestBrowser/1.0"}) if pg is not None else None
check(r is not None and r.status_code == 303, f"#2192: signed through the link ({r.status_code if r is not None else None})")
x = sheet(A, S_DPA["id"])
check(x and x["status"] == "signed" and x["signed_via"] == "link" and not x["review"] and x["signed_node_id"], f"#2192: the sheet is signed (link) {x}")
p = A.get(B + PS + f"/{S_DPA['id']}/pdf?signed=1")
check(p.ok and p.content.startswith(b"%PDF-"), "#2192: the signed PDF of the link")
check(A.post(B + PS + f"/{S_DPA['id']}/send", json={"to": "kunde@example.com"}).status_code == 409, "#2192: a signed DPA is not sent again")

# ================================================================== the way back: a reply mail with the code
T_CONS = A.post(B + TP, json={"kind": "other", "name": "Einwilligung kurz", "lang": "de", "sign": 1,
                              "body": "# Einwilligung\n\n{{client.name}} willigt in den Newsletter ein."}).json()["id"]
S_CONS = A.post(B + PS, json={"client_id": CL, "kind": "consent", "template_id": T_CONS}).json()["sheet"]
drop(f"Re: Einwilligung [DS-{code}]", files=[("unterschrieben.pdf", PDF, "application/pdf")])  # the DPA's code: already signed
poll()
check(sheet(A, S_DPA["id"])["signed_via"] == "link", "#2192: a reply for a sheet already signed changes nothing")
# 2.154.0 E (#2192): ... but it is never silently gone: office log entry + "Reply received (please check)" (review 2)
x = sheet(A, S_DPA["id"])
check(x["status"] == "signed" and x["review"] == 2 and x["status_label"] == "Reply received (please check)", f"#2192 E C1: a reply not filed is shown {x}")
check(sql("SELECT count(*) FROM office_doc_log WHERE org_id=? AND action='privacy_reply'", (ORG,))[0][0] >= 1, "#2192 E C1: the reply is in the office log")
r = A.post(B + PS + f"/{S_DPA['id']}/confirm")
check(r.ok and r.json()["status"] == "signed" and not r.json()["review"] and r.json()["signed_via"] == "link", "#2192 E C1: reply checked, status stays")
m = A.get(B + PS + f"/{S_CONS['id']}/mail").json()
c2 = re.search(r"\[DS-([A-Z2-9]{12})\]", m["subject"]).group(1)
drop(f"Re: Einwilligung [DS-{c2}]", files=[("x.pdf", PDF, "application/pdf")])  # not mailed yet: nothing
poll()
check(sheet(A, S_CONS["id"])["status"] == "open", "#2192: a reply for a sheet never mailed changes nothing")
check(A.post(B + PS + f"/{S_CONS['id']}/send", json={"to": "kunde@example.com"}).ok, "#2192: the consent sent")
drop(f"Re: Einwilligung [DS-{c2}]", files=[("notiz.txt", b"nur Text", "text/plain")])
poll()
check(sheet(A, S_CONS["id"])["status"] == "sent", "#2192: a reply without PDF / picture changes nothing")
check(sheet(A, S_CONS["id"])["review"] == 2, "#2192 E C1: a reply without PDF / picture (e.g. a revocation) marks the sheet")
r = A.post(B + PS + f"/{S_CONS['id']}/confirm")
check(r.ok and r.json()["status"] == "sent" and not r.json()["review"], f"#2192 E C1: confirm also a sheet that is not signed ({r.status_code})")
drop("Re: Einwilligung [DS-ABCDEFGHJKLM]", files=[("x.pdf", PDF, "application/pdf")])
poll()
check(sheet(A, S_CONS["id"])["status"] == "sent", "#2192: an unknown code changes nothing")
drop(f"Re: Einwilligung [DS-{c2.lower()}]", files=[("Einwilligung signiert.pdf", PDF, "application/pdf")])
poll()
x = until(lambda: (sheet(A, S_CONS["id"]) or {}).get("status") == "signed" and sheet(A, S_CONS["id"]))
check(x and x["status"] == "signed" and x["signed_via"] == "mail" and x["review"] and x["signed_node_id"], f"#2192: a reply with the code: signed, please check {x}")
check(x and "please check" in x["status_label"], "#2192: the status says so")
nd = sql("SELECT org_id FROM fs_nodes WHERE id=?", (x["signed_node_id"],)) if x else []
check(nd and nd[0][0] == ORG, "#2192: filed in the sheet's organisation")
p = A.get(B + PS + f"/{S_CONS['id']}/pdf?signed=1")
check(p.ok and p.content == PDF, "#2192: the signed file that came by mail")
check(not sql("SELECT 1 FROM tasks WHERE title LIKE ?", ("%Einwilligung%",)), "#2192: no reply became a task")
check(A.post(B + PS + f"/{S_INFO['id']}/confirm").status_code == 409, "#2192: confirm only a signed sheet")
r = A.post(B + PS + f"/{S_CONS['id']}/confirm")
check(r.ok and r.json()["status"] == "signed" and not r.json()["review"], "#2192: confirmed")

# the plus address alone (the subject changed by the customer) finds the sheet too
S_C2 = A.post(B + PS, json={"client_id": CL, "kind": "consent", "template_id": T_CONS}).json()["sheet"]
A.post(B + PS + f"/{S_C2['id']}/send", json={"to": "kunde@example.com"})
c3 = re.search(r"\[DS-([A-Z2-9]{12})\]", A.get(B + PS + f"/{S_C2['id']}/mail").json()["subject"]).group(1)
# 2.154.0 E (#2192, C3): the sheet as it was sent and a small logo are skipped, the scan (30 KB or more) is filed
SENT = A.get(B + PS + f"/{S_C2['id']}/pdf").content
SCAN = b"\x89PNG\r\n\x1a\n" + b"\x00" * (40 * 1024)
drop("Unterschrift", to=f"tasks+ds-{c3.lower()}@example.test", files=[("original.pdf", SENT, "application/pdf"),
     ("logo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png"), ("scan.png", SCAN, "image/png")])
poll()
x = until(lambda: (sheet(A, S_C2["id"]) or {}).get("review") and sheet(A, S_C2["id"]))
check(x and x["status"] == "signed" and x["signed_via"] == "mail", f"#2192: the plus address with the code (a picture) {x}")
check(SENT.startswith(b"%PDF-") and A.get(B + PS + f"/{S_C2['id']}/pdf?signed=1").content == SCAN, "#2192 E C3: not the sent PDF, not the logo: the scan")
r = A.patch(B + PS + f"/{S_C2['id']}", json={"status": "sent"})
check(r.ok and r.json()["status"] == "sent" and not r.json()["review"], "#2192: not the signed sheet: back to sent")

# ================================================================== the way back: upload
S_D2 = A.post(B + PS, json={"client_id": CL, "kind": "dpa", "template_id": T_SIGN}).json()["sheet"]
check(A.post(B + PS + f"/{S_D2['id']}/signed", files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 400, "#2192: upload: only PDF / pictures")
r = A.post(B + PS + f"/{S_D2['id']}/signed", files={"file": ("AVV unterschrieben.pdf", PDF, "application/pdf")})
check(r.ok and r.json()["status"] == "signed" and r.json()["signed_via"] == "upload" and not r.json()["review"], f"#2192: upload = signed ({r.status_code} {r.text[:200]})")
check(A.get(B + PS + f"/{S_D2['id']}/pdf?signed=1").content == PDF, "#2192: the uploaded file")

# ================================================================== status by hand, archive, filter data
check(A.patch(B + PS + f"/{S_D2['id']}", json={"status": "maybe"}).status_code == 400, "#2192: an unknown status 400")
r = A.patch(B + PS + f"/{S_D2['id']}", json={"status": "declined"})
check(r.ok and r.json()["status"] == "declined", "#2192: declined by hand")
check(A.delete(B + PS + f"/{S_D2['id']}").ok and all(x["id"] != S_D2["id"] for x in A.get(B + PS + "?brief=1").json()["sheets"]), "#2192: archived")
check(A.post(B + PS + f"/{S_D2['id']}/restore").ok and any(x["id"] == S_D2["id"] for x in A.get(B + PS + "?brief=1").json()["sheets"]), "#2192: restored")
al = A.get(B + PS + "?brief=1").json()
check("kinds" not in al and {x["client_id"] for x in al["sheets"]} == {CL} and len(al["sheets"]) == 5, f"#2192: brief = the sheets of the area {len(al['sheets'])}")

# ================================================================== rights + tenant boundary
check(Bo.get(B + PS).status_code == 403 and Bo.post(B + PS, json={"client_id": CL, "kind": "info"}).status_code == 403, "#2192: a member 403")
check(requests.get(B + PS, headers=AGH).status_code == 403 and requests.post(B + PS + f"/{S_DPA['id']}/send", headers=AGH, json={"to": "a@example.com"}).status_code == 403,
      "#2192: an agent 403 (agents never send)")
for meth, path in (("GET", f"{PS}/{S_DPA['id']}/pdf"), ("GET", f"{PS}/{S_DPA['id']}/mail"), ("PATCH", f"{PS}/{S_DPA['id']}"),
                   ("POST", f"{PS}/{S_DPA['id']}/send"), ("POST", f"{PS}/{S_DPA['id']}/confirm"), ("DELETE", f"{PS}/{S_DPA['id']}")):
    check(Ca.request(meth, B + path, json={"status": "open", "to": "x@example.com"}).status_code == 404, f"#2192: another organisation: {meth} {path} 404")
check(Ca.get(B + PS + f"?client_id={CL}").status_code == 404 and A.post(B + PS, json={"client_id": CL2, "kind": "info"}).status_code == 404,
      "#2192: a client of another organisation 404")
TB = Ca.post(B + TP, json={"kind": "other", "name": "AVV Beta", "lang": "de", "sign": 1, "body": "# AVV\n\n{{client.name}}"}).json()["id"]
SB = Ca.post(B + PS, json={"client_id": CL2, "kind": "dpa", "template_id": TB}).json()["sheet"]
Ca.post(B + PS + f"/{SB['id']}/send", json={"to": "fremd@example.com"})
cb = re.search(r"\[DS-([A-Z2-9]{12})\]", Ca.get(B + PS + f"/{SB['id']}/mail").json()["subject"]).group(1)
drop(f"Re: AVV [DS-{cb}]", files=[("b.pdf", PDF, "application/pdf")])
poll()
x = until(lambda: (sheet(Ca, SB["id"]) or {}).get("review") and sheet(Ca, SB["id"]))
nd = sql("SELECT org_id FROM fs_nodes WHERE id=?", (x["signed_node_id"],)) if x else []
check(x and nd and nd[0][0] == BETA, f"#2192: a code of another organisation files only there {nd}")
check(all(y["id"] != SB["id"] for y in A.get(B + PS + "?brief=1").json()["sheets"]), "#2192: Alpha never sees Beta's sheet")

# ================================================================== a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
Fr.put(B + O + "/settings", json={"lang": "de", "currency": "EUR", "company_fields": {"name": "Frida Grafik", "city": "Beispielstadt"}})
FCL = Fr.post(B + "/api/clients", json={"name": "Privatkunde Beispiel", "email": "privat@example.com"}).json()["id"]
j = Fr.get(B + PS + f"?client_id={FCL}")
check(j.ok and j.json()["sheets"] == [], f"freelancer: the list ({j.status_code})")
r = Fr.post(B + PS, json={"client_id": FCL, "kind": "consent"})
check(r.status_code == 201 and r.json()["edit"], "freelancer: a sheet from the sample (draft)")
FT = Fr.post(B + TP, json={"kind": "other", "name": "Info", "lang": "de", "sign": 0, "body": "# Datenschutz\n\n{{company.name}} informiert."}).json()["id"]
r = Fr.post(B + PS, json={"client_id": FCL, "kind": "info", "template_id": FT})
check(r.status_code == 201 and not r.json()["edit"] and r.json()["sheet"]["node_id"], "freelancer: a finished sheet")
FS = r.json()["sheet"]["id"]
check(Fr.get(B + PS + f"/{FS}/mail").ok and Fr.get(B + PS + f"/{FS}/pdf").ok, "freelancer: mail proposal + PDF")
r = Fr.post(B + PS + f"/{FS}/send", json={"to": "privat@example.com"})
check(r.ok and r.json()["status"] == "handed", f"freelancer: sent ({r.status_code} {r.text[:160]})")
FT2 = Fr.post(B + TP, json={"kind": "other", "name": "AVV", "lang": "de", "sign": 1, "body": "# AVV\n\n{{client.name}}"}).json()["id"]
FS2 = Fr.post(B + PS, json={"client_id": FCL, "kind": "dpa", "template_id": FT2}).json()["sheet"]["id"]
check(Fr.post(B + PS + f"/{FS2}/send", json={"to": "privat@example.com"}).ok, "freelancer: the DPA sent")
fc = re.search(r"\[DS-([A-Z2-9]{12})\]", Fr.get(B + PS + f"/{FS2}/mail").json()["subject"]).group(1)
drop(f"Re: AVV [DS-{fc}]", files=[("f.pdf", PDF, "application/pdf")])
poll()
x = until(lambda: (sheet(Fr, FS2) or {}).get("review") and sheet(Fr, FS2))
nd = sql("SELECT org_id, owner_id FROM fs_nodes WHERE id=?", (x["signed_node_id"],)) if x else []
check(x and x["signed_via"] == "mail" and nd and nd[0][0] is None and nd[0][1] == FID, f"freelancer: the reply lands in the own space {nd}")
check(Fr.post(B + PS + f"/{FS2}/confirm").ok, "freelancer: confirm")
# 2.154.0 E (#2192, C4): the information needs no signature -> 409; the upload on a DPA; an archived sheet 409
r = Fr.post(B + PS + f"/{FS}/signed", files={"file": ("i.pdf", PDF, "application/pdf")})
check(r.status_code == 409, f"freelancer: no upload for the information ({r.status_code})")
FS3 = Fr.post(B + PS, json={"client_id": FCL, "kind": "dpa", "template_id": FT2}).json()["sheet"]["id"]
r = Fr.post(B + PS + f"/{FS3}/signed", files={"file": ("i.pdf", PDF, "application/pdf")})
check(r.ok and r.json()["status"] == "signed", "freelancer: upload")
check(Fr.delete(B + PS + f"/{FS3}").ok and Fr.post(B + PS + f"/{FS3}/signed", files={"file": ("i.pdf", PDF, "application/pdf")}).status_code == 409,
      "freelancer: no upload for an archived sheet")
check(Fr.patch(B + PS + f"/{FS}", json={"status": "handed"}).ok and Fr.delete(B + PS + f"/{FS}").ok and Fr.post(B + PS + f"/{FS}/restore").ok,
      "freelancer: status, archive, restore")
check(Fr.get(B + PS + f"/{S_DPA['id']}/pdf").status_code == 404 and Fr.get(B + PS + f"?client_id={CL}").status_code == 404,
      "freelancer: sheets / clients of an organisation 404")

print(f"p2154_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
