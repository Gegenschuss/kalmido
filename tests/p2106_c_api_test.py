#!/usr/bin/env python3
"""2.106.0 API tests, part C (#2029, #2030): a letter sent by e-mail and its answer linked; text blocks. Own container
(start.sh) with the SMTP sink + IMAP stub (tests/stub_mail.py). Invented names, addresses @example.com only.
 - mail-info: mail server on, the reply address = the person's document address of the office's documents space ('' before)
 - send-mail: a draft goes out to its recipient's e-mail with the PDF attached, Reply-To = the document address, the
   Message-ID kept on the letter, status sent + channel email; a second send 400; no address / a broken one 400
 - the answer (In-Reply-To = that Message-ID) to the document address -> a document linked to the letter (kind reply);
   the same Message-ID arriving in another organisation's or the private documents space -> no link (tenant-matrix: office)
 - text blocks: create, change, delete + restore, samples (de / en, the note); a member 403, another organisation 404,
   an agent token 403
 - a person without an organisation (freelancer-matrix: office): the personal office sends a letter by e-mail, the answer
   to the private document address is linked; own text blocks
usage: p2106_c_api_test.py <datadir>      (a fresh container; P2106C_NOSTART=1 = the server already runs with the mail stubs)"""
import email
import email.message
import email.policy
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "clients,office,docs,files"
O = "/api/office"
L = O + "/letters"
BL = O + "/letter-blocks"
MAILENV = ["-e", "KALMIDO_MAIL_ADDRESS=tasks@example.test", "-e", "KALMIDO_IMAP_HOST=127.0.0.1", "-e", "KALMIDO_IMAP_PORT=1143",
           "-e", "KALMIDO_IMAP_SSL=0", "-e", "KALMIDO_IMAP_USER=kalmido", "-e", "KALMIDO_IMAP_PASSWORD=secret", "-e", "KALMIDO_IMAP_INTERVAL=600",
           "-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none",
           "-e", "KALMIDO_MAIL_FROM=kalmido@example.test", "-e", "KALMIDO_DOCS_SCAN_S=2"]


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


def ws(s, v):
    r = s.patch(B + "/api/settings", json={"workspace": v})
    assert r.ok, r.text


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def text_pdf(lines):
    """A one-page PDF with a text layer (hand-written, no library)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 12 Tf 60 740 Td 16 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET").encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def sent_mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl")) if x.strip()]
    except FileNotFoundError:
        return []


EML = [0]


def deliver(to, in_reply_to, subject, refs=None):
    """An incoming mail with a PDF to address to, answering in_reply_to; polled at once."""
    EML[0] += 1
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = "office@example.com", to, subject
    m["Message-ID"] = f"<answer-{EML[0]}@example.com>"
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    if refs:
        m["References"] = refs
    m.set_content("see attachment")
    m.add_attachment(text_pdf([subject, "Datum 06.10.2026"]), maintype="application", subtype="pdf", filename=f"answer{EML[0]}.pdf")
    open(os.path.join(DATA, "mail", "in", f"{EML[0]}.eml"), "wb").write(bytes(m))
    A.post(B + "/api/admin/mail/poll")
    return m["Message-ID"]


def node_of(mid):
    r = until(lambda: dbx("SELECT node_id FROM doc_meta WHERE source='mail' AND ext_id LIKE ?", (f"mail:{mid}:%",)), 40)
    return r[0][0] if r else None


def reply_links(lid):
    return [r[0] for r in dbx("SELECT node_id FROM office_letter_links WHERE letter_id=? AND kind='reply'", (lid,))]


# ---------------------------------------------------------------- setup: alice = admin of Alpha, bob a member, frank = Beta
if not os.environ.get("P2106C_NOSTART"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA],
                       env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u == "bob" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Fr = sess("bob"), sess("frank")
for s in (A, Bo, Fr):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
ws(A, f"org:{ORG}")
ws(Bo, f"org:{ORG}")
ws(Fr, f"org:{BETA}")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AG = requests.Session()
AG.headers.update({"Authorization": "Bearer " + r.json()["token"], **H})

# ---------------------------------------------------------------- mail-info and the reply address
r = A.get(B + L + "/mail-info")
check(r.ok and r.json()["mail_on"] is True and r.json()["reply_address"] == "", f"mail-info before a document address ({r.text[:160]})")
r = A.post(B + "/api/docs/mail", json={"ws": f"org:{ORG}"})
assert r.ok, r.text
ADDR = r.json()["address"]
check(A.get(B + L + "/mail-info").json()["reply_address"] == ADDR, "mail-info: the reply address = Alpha's document address of alice")
check(Bo.get(B + L + "/mail-info").status_code == 403, "a member: mail-info 403")
check(AG.get(B + L + "/mail-info").status_code == 403, "an agent token: mail-info 403")

# ---------------------------------------------------------------- send by e-mail
r = A.post(B + L, json={"rcpt_name": "Amt für Beispiele", "rcpt_address": "Musterweg 1\n12345 Musterstadt", "rcpt_email": "amt@example.com",
                        "subject": "Antrag 7/2026", "body": "Sehr geehrte Damen und Herren,\n\nanbei mein Antrag."})
assert r.status_code == 201, r.text
L1 = r.json()["id"]
r = A.get(B + f"{L}/{L1}/mail-draft")
check(r.ok and r.json()["to"] == "amt@example.com" and r.json()["filename"].endswith(".pdf") and r.json()["reply_address"] == ADDR
      and "Antrag 7/2026" in r.json()["text"], f"mail-draft prefilled ({r.text[:200]})")
check(Fr.get(B + f"{L}/{L1}/mail-draft").status_code == 404, "another organisation: mail-draft 404")
check(Fr.post(B + f"{L}/{L1}/send-mail", json={}).status_code == 404, "another organisation: send-mail 404")
check(Bo.post(B + f"{L}/{L1}/send-mail", json={}).status_code == 403, "a member: send-mail 403")
check(A.post(B + f"{L}/{L1}/send-mail", json={"to": "not-an-address"}).status_code == 400, "a broken address: 400")
n0 = len(sent_mails())
r = A.post(B + f"{L}/{L1}/send-mail", json={"cc": "copy@example.com"})
check(r.ok and r.json()["status"] == "sent" and r.json()["channel"] == "email" and r.json()["sent_at"], f"sent: status + channel ({r.text[:200]})")
MID = (dbx("SELECT msg_id FROM office_letters WHERE id=?", (L1,)) or [[""]])[0][0]
check(MID.startswith("<") and MID.endswith(">"), f"the Message-ID is kept on the letter ({MID})")
out = sent_mails()[n0:]
check(len(out) == 1, f"exactly one mail went out ({len(out)})")
if out:
    m = email.message_from_string(out[-1]["raw"], policy=email.policy.default)
    check(set(out[-1]["to"]) == {"amt@example.com", "copy@example.com"}, f"to + cc ({out[-1]['to']})")
    check(str(m["Message-ID"]) == MID, "the mail's Message-ID = the one on the letter")
    check(str(m["Reply-To"]) == ADDR, f"Reply-To = the document address ({m['Reply-To']})")
    check(str(m["Subject"]) == "Antrag 7/2026", "subject = the letter's subject")
    att = list(m.iter_attachments())
    check(len(att) == 1 and att[0].get_content_type() == "application/pdf" and att[0].get_content().startswith(b"%PDF")
          and att[0].get_filename().endswith(".pdf"), "the letter's PDF is attached")
check(A.post(B + f"{L}/{L1}/send-mail", json={}).status_code == 400, "a second send: 400 (no draft any more)")
check(len(sent_mails()) == n0 + 1, "the refused second send mailed nothing")
r = A.post(B + L, json={"rcpt_name": "Ohne Mail", "subject": "Ohne Adresse"})
L2 = r.json()["id"]
r = A.post(B + f"{L}/{L2}/send-mail", json={})
check(r.status_code == 400 and r.json().get("error"), f"no e-mail address: 400 with a text ({r.text[:120]})")
check(A.get(B + f"{L}/{L2}").json()["status"] == "draft", "the refused letter stays a draft")

# ---------------------------------------------------------------- the answer comes back (tenant-matrix: office)
m1 = deliver(ADDR, MID, "Antwort Antrag 7")
n1 = node_of(m1)
check(bool(n1), "the answer's PDF became a document of Alpha")
check(until(lambda: n1 in reply_links(L1), 10), f"the answer is linked to the letter (reply) ({reply_links(L1)})")
m1b = deliver(ADDR, "<other@example.com>", "Nachtrag", refs=f"<x@example.com> {MID}")
n1b = node_of(m1b)
check(n1b and until(lambda: n1b in reply_links(L1), 10), "References with the Message-ID also links")
m1c = deliver(ADDR, "<unknown@example.com>", "Fremde Sache")
n1c = node_of(m1c)
check(n1c and n1c not in reply_links(L1), "another Message-ID: no link")
r = Fr.post(B + "/api/docs/mail", json={"ws": f"org:{BETA}"})
assert r.ok, r.text
m2 = deliver(r.json()["address"], MID, "Fremde Antwort")
n2 = node_of(m2)
check(n2 and n2 not in reply_links(L1), "the same Message-ID to Beta's document address: no link to Alpha's letter")
check(not dbx("SELECT 1 FROM office_letter_links WHERE node_id=?", (n2,)), "Beta's document: no link at all")
r = A.post(B + "/api/docs/mail", json={"ws": "private"})
assert r.ok, r.text
m3 = deliver(r.json()["address"], MID, "Private Antwort")
n3 = node_of(m3)
check(n3 and not dbx("SELECT 1 FROM office_letter_links WHERE node_id=?", (n3,)), "the same Message-ID to alice's private address: no link")

# ---------------------------------------------------------------- text blocks
r = A.get(B + BL + "/starters?lang=de")
st = r.json().get("starters") or []
check(r.ok and len(st) == 4 and {x["key"] for x in st} == {"cancel", "objection", "reminder", "extension"} and r.json()["note"],
      f"four samples with the note ({r.text[:160]})")
check(any(x["name"] == "Kündigung" for x in st), "German samples")
check(any(x["name"] == "Cancellation" for x in A.get(B + BL + "/starters?lang=en").json()["starters"]), "English samples")
check(A.get(B + BL + "/starters?lang=xx").status_code == 400, "an unknown language: 400")
r = A.post(B + BL, json={"name": "Gruß", "body": "Mit freundlichen Grüßen\nAlice"})
check(r.status_code == 201 and r.json()["body"] == "Mit freundlichen Grüßen\nAlice", f"a block made ({r.text[:120]})")
K1 = r.json()["id"]
check(A.post(B + BL, json={"name": "", "body": "x"}).status_code == 400, "a block without a name: 400")
r = A.post(B + BL, json={"starter": "reminder", "lang": "de"})
check(r.status_code == 201 and r.json()["name"] == "Zahlungserinnerung", "a sample taken over")
K2 = r.json()["id"]
check(A.post(B + BL, json={"starter": "nope"}).status_code == 400, "an unknown sample: 400")
r = A.patch(B + f"{BL}/{K1}", json={"name": "Grußformel"})
check(r.ok and r.json()["name"] == "Grußformel" and r.json()["body"].startswith("Mit freundlichen"), "renamed, the text stays")
names = [x["name"] for x in A.get(B + BL).json()["blocks"]]
check(names == sorted(names, key=str.lower) and {"Grußformel", "Zahlungserinnerung"} <= set(names), f"the list ({names})")
check(A.delete(B + f"{BL}/{K2}").ok and K2 not in [x["id"] for x in A.get(B + BL).json()["blocks"]], "deleted: out of the list")
check(K2 in [x["id"] for x in A.get(B + BL + "?archived=1").json()["blocks"]], "?archived=1 shows it")
check(A.post(B + f"{BL}/{K2}/restore").ok and K2 in [x["id"] for x in A.get(B + BL).json()["blocks"]], "restored (undo)")
check(Bo.get(B + BL).status_code == 403 and Bo.post(B + BL, json={"name": "x"}).status_code == 403, "a member: text blocks 403")
check(AG.get(B + BL).status_code == 403, "an agent token: text blocks 403")
check(Fr.get(B + BL).json()["blocks"] == [], "Beta sees none of Alpha's blocks")
check(Fr.patch(B + f"{BL}/{K1}", json={"name": "x"}).status_code == 404, "Beta: PATCH Alpha's block 404")
check(Fr.delete(B + f"{BL}/{K1}").status_code == 404 and Fr.post(B + f"{BL}/{K1}/restore").status_code == 404, "Beta: delete / restore 404")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
FID, Fi = freelancer(B, A, "fiona")
r = Fi.get(B + L + "/mail-info")
check(r.ok and r.json()["mail_on"] is True, f"freelancer: mail-info ({r.text[:120]})")
r = Fi.post(B + "/api/docs/mail", json={"ws": "private"})
assert r.ok, r.text
FADDR = r.json()["address"]
check(Fi.get(B + L + "/mail-info").json()["reply_address"] == FADDR, "freelancer: the private document address answers")
r = Fi.post(B + L, json={"rcpt_name": "Versicherung", "rcpt_email": "service@example.com", "subject": "Schaden 42"})
FL = r.json()["id"]
n0 = len(sent_mails())
r = Fi.post(B + f"{L}/{FL}/send-mail", json={"text": "Guten Tag,\n\nanbei."})
check(r.ok and r.json()["status"] == "sent", f"freelancer: sent ({r.text[:160]})")
out = sent_mails()[n0:]
FMID = (dbx("SELECT msg_id FROM office_letters WHERE id=?", (FL,)) or [[""]])[0][0]
if out:
    fm = email.message_from_string(out[-1]["raw"], policy=email.policy.default)
    check(str(fm["Reply-To"]) == FADDR and "anbei." in fm.get_body(("plain",)).get_content(), "freelancer: own text, Reply-To private address")
check(A.get(B + f"{L}/{FL}").status_code == 404, "alice (Alpha) cannot open fiona's letter")
fn = node_of(deliver(FADDR, FMID, "Antwort Schaden 42"))
check(fn and until(lambda: fn in reply_links(FL), 10), "freelancer: the answer is linked to the letter of the personal office")
r = Fi.post(B + BL, json={"starter": "cancel", "lang": "en"})
check(r.status_code == 201 and r.json()["name"] == "Cancellation", "freelancer: a sample block")
check([x["id"] for x in Fi.get(B + BL).json()["blocks"]] == [r.json()["id"]], "freelancer: only the own blocks")
check(A.patch(B + f"{BL}/{r.json()['id']}", json={"name": "x"}).status_code == 404, "alice: fiona's block 404")

print(f"p2106_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
