#!/usr/bin/env python3
"""2.240.0 A (#2883): the admin mail path.
 - KALMIDO_SMTP_* / KALMIDO_IMAP_* of the admin: the TLS context checks certificate + host name (CERT_REQUIRED,
   check_hostname); only KALMIDO_SMTP_INSECURE=1 turns it off (CERT_NONE); a workspace's own server stays checked
 - instance mailbox: a mail taken in whole (or dropped as for nobody / a double, MAIL_DROP) is marked \\Deleted and
   expunged (UID EXPUNGE when the server has UIDPLUS, else EXPUNGE); a mail whose import failed, that an importer refused
   (None / 0) or that was taken in only in part (MailKept: an attachment not stored) stays (only \\Seen); a mail another
   process claimed stays too; KALMIDO_IMAP_KEEP=1 = only \\Seen as before; workspace mailboxes (delete off) only \\Seen
 - error log lines: a refused recipient's address never lands in the log (only the error class)
 - freelancer-matrix: mail (a person without organisation: a mail to her personal address through the IMAP stub becomes a
   task in her basket and is deleted from the mailbox)
Runs the functions inside the test container (fake IMAP objects) plus one real round through tests/stub_mail.py.
usage: p2240_a_mail_test.py <datadir>      (starts its own container)"""
import email.message
import json
import os
import shutil
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import B, CT, DATA, FAILS, OKS, check, dbx, done, sess, setup, until  # noqa: E402,F401
from freelancer_fixture import freelancer  # noqa: E402
MAILENV = (" -e KALMIDO_MAIL_ADDRESS=tasks@example.test -e KALMIDO_IMAP_HOST=127.0.0.1 -e KALMIDO_IMAP_PORT=1143 -e KALMIDO_IMAP_SSL=0"
           " -e KALMIDO_IMAP_USER=kalmido -e KALMIDO_IMAP_PASSWORD=secret -e KALMIDO_IMAP_INTERVAL=600")

r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + MAILENV),
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)


def py(code, env=()):
    args = ["docker", "exec", "-i"]
    for e in env:
        args += ["-e", e]
    r = subprocess.run(args + [CT, "python", "-c", code], capture_output=True, text=True, timeout=300)
    if r.returncode:
        print("PY FAILED:", r.stdout[-2000:], r.stderr[-3000:], flush=True)
    return r


def jlast(r):
    for ln in reversed((r.stdout or "").splitlines()):
        if ln.startswith("{"):
            return json.loads(ln)
    return {}


# ---- 1. TLS context of the admin mail server
TLS = """
import json, ssl, app
from kalmido.integrations import mail as M
a, w = M._admin_tls_ctx(), M._tls_ctx()
print(json.dumps({"mode": int(a.verify_mode), "host": a.check_hostname, "ws_mode": int(w.verify_mode), "ws_host": w.check_hostname,
                  "req": int(ssl.CERT_REQUIRED), "none": int(ssl.CERT_NONE)}))
"""
j = jlast(py(TLS))
check(j.get("mode") == j.get("req") and j.get("host") is True, f"admin mail server: certificate + host name checked {j}")
check(j.get("ws_mode") == j.get("req") and j.get("ws_host") is True, f"workspace mail server: checked {j}")
j = jlast(py(TLS, ["KALMIDO_SMTP_INSECURE=1"]))
check(j.get("mode") == j.get("none") and j.get("host") is False, f"KALMIDO_SMTP_INSECURE=1: admin check off {j}")
check(j.get("ws_mode") == j.get("req") and j.get("ws_host") is True, f"KALMIDO_SMTP_INSECURE=1: workspace server still checked {j}")

# the SMTP session of the admin hands the checked context to STARTTLS and SMTP_SSL
SMTPCTX = """
import json, smtplib, ssl, app
from kalmido.integrations import mail as M
seen = {}
class FakeSMTP:
    def __init__(self, host, port, timeout=None, context=None):
        seen["ssl_ctx"] = None if context is None else int(context.verify_mode)
    def starttls(self, context=None):
        seen["starttls_ctx"] = None if context is None else int(context.verify_mode)
    def login(self, u, p): pass
    def close(self): pass
smtplib.SMTP = smtplib.SMTP_SSL = FakeSMTP
M.SMTP.update(host="mail.example.com", tls="starttls", user="")
M.smtp_open()
M.SMTP.update(tls="ssl")
M.smtp_open()
print(json.dumps(seen))
"""
j = jlast(py(SMTPCTX))
check(j.get("starttls_ctx") == 2 and j.get("ssl_ctx") == 2, f"admin SMTP: starttls and ssl get a context with CERT_REQUIRED {j}")

# ---- 2. instance mailbox: delete after import
FETCH = """
import json, smtplib, sys, io, app
from kalmido.integrations import mail as M
class FakeIMAP:
    capabilities = ("IMAP4REV1",)
    def __init__(self, *a, **k): self.stores, self.expunged, self.xat = [], 0, []
    def select(self, folder): return "OK", [b"6"]
    def xatom(self, *a): self.xat.append(" ".join(a)); return "OK", []
    def uid(self, cmd, *a):
        if cmd == "SEARCH": return "OK", [b"1 2 3 4 5"]
        if cmd == "FETCH":
            if "SIZE" in a[1]: return "OK", [b"1 (UID %s RFC822.SIZE 100)" % a[0]]
            return "OK", [(b"1 (UID %s RFC822 {5}" % a[0], b"mail" + a[0]), b")"]
        if cmd == "STORE": self.stores.append((a[0].decode(), a[2])); return "OK", []
    def expunge(self): self.expunged += 1; return "OK", []
    def login(self, u, p): return "OK", []
    def logout(self): pass
    def read(self, n): return b""
def importer(c, raw, pre=None):
    if c is None:  # the instance poll's prefetch step (2.424.0 B2, #3450): no downloads here
        return None
    if raw == b"mail2": raise smtplib.SMTPRecipientsRefused({"bob.secret@example.com": (550, b"no such user")})
    return {b"mail1": 11, b"mail3": M.MAIL_DROP, b"mail4": None, b"mail5": M.MailKept(15)}[raw]  # 3 for nobody, 4 refused, 5 in part
out = {}
buf, old = io.StringIO(), sys.stdout
sys.stdout = buf
try:
    f = FakeIMAP(); M.mail_fetch(f, "INBOX", importer, delete=True); out["del"] = [f.stores, f.expunged]
    f = FakeIMAP(); M.mail_fetch(f, "INBOX", importer); out["keep"] = [f.stores, f.expunged]
    f = FakeIMAP(); f.capabilities = ("IMAP4REV1", "UIDPLUS"); M.mail_fetch(f, "INBOX", importer, delete=True); out["uidplus"] = [f.xat, f.expunged]
    # the instance poll: deletes by default, KALMIDO_IMAP_KEEP=1 keeps
    made = []
    M.imaplib.IMAP4 = M.imaplib.IMAP4_SSL = lambda *a, **k: made.append(FakeIMAP()) or made[-1]
    M.IMAP.update(host="imap.example.com", ssl=False, user="u")
    M.mail_import = importer
    M.mail_poll_once(); out["poll"] = [made[-1].stores, made[-1].expunged]
finally:
    sys.stdout = old
out["log"] = buf.getvalue()
print(json.dumps(out))
"""
r = py(FETCH)
j = jlast(r)
d = {u: f for u, f in (j.get("del") or [[], 0])[0]}
check("\\Deleted" in d.get("1", "") and "\\Deleted" in d.get("3", ""), f"delete: imported + for nobody -> \\Deleted {d}")
check(d.get("2") == "(\\Seen)", f"delete: the failed one stays (only seen) {d}")
check(d.get("4") == "(\\Seen)" and d.get("5") == "(\\Seen)", f"delete: refused (None) and taken in part (MailKept) stay {d}")
check(j.get("uidplus") == [["UID EXPUNGE 1,3"], 0], f"UIDPLUS: UID EXPUNGE of exactly the deleted ones {j.get('uidplus')}")
check((j.get("del") or [0, 0])[1] == 1, f"delete: expunged once {j.get('del')}")
k = {u: f for u, f in (j.get("keep") or [[], 0])[0]}
check(k and all(f == "(\\Seen)" for f in k.values()) and j["keep"][1] == 0, f"workspace mailbox (delete off): only seen, no expunge {j.get('keep')}")
p = {u: f for u, f in (j.get("poll") or [[], 0])[0]}
check("\\Deleted" in p.get("1", "") and j["poll"][1] == 1, f"instance poll deletes by default {j.get('poll')}")
check("bob.secret" not in j.get("log", "x") and "SMTPRecipientsRefused" in j.get("log", ""), f"log without address: {j.get('log')!r}")
j = jlast(py(FETCH, ["KALMIDO_IMAP_KEEP=1"]))
p = {u: f for u, f in (j.get("poll") or [[], 0])[0]}
check(p and all(f == "(\\Seen)" for f in p.values()) and j["poll"][1] == 0, f"KALMIDO_IMAP_KEEP=1: only seen {j.get('poll')}")

# ---- 3. the other log lines: summary mail, event mail, workspace mailbox loops (error class only)
LOGS = """
import inspect, json, re, app
from kalmido.integrations import mail as M
from kalmido.hub import mailbox as X
from kalmido.notify import channels as C
bad = []
for mod in (M, X, C):
    for ln in inspect.getsource(mod).splitlines():
        if re.search(r'print\\("(mail|mailbox):.*type\\(e\\)\\.__name__, e[,)]', ln):  # the mail / mailbox error lines
            bad.append(ln.strip())
print(json.dumps(bad))
"""
r = py(LOGS)
bad = json.loads((r.stdout or "[1]").strip().splitlines()[-1] or "[1]")
check(bad == [], f"mail log lines print no exception text: {bad}")

# ---- 4. one real round through the IMAP stub: a person without organisation (freelancer-matrix: mail)
A = setup()
FID, Fr = freelancer(B, A)
r = Fr.post(B + "/api/me/mail/token", json={})
addr = r.json().get("address", "") if r.ok else ""
check("+" in addr, f"freelancer: a personal mail address {r.status_code} {addr}")
m = email.message.EmailMessage()
m["From"], m["To"], m["Subject"], m["Message-ID"] = "sender@example.com", addr, "Invoice check", "<p2240a-1@example.test>"
m.set_content("please check")
with open(os.path.join(DATA, "mail", "in", "1.eml"), "wb") as f:
    f.write(bytes(m))
until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1143), 1)"],
                             capture_output=True).returncode == 0, 15)
A.post(B + "/api/admin/mail/poll")
row = until(lambda: dbx("SELECT l.owner_id, l.org_id, l.is_inbox FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.tt_id=?",
                        ("mail:<p2240a-1@example.test>",)), 40)
check(row and row[0][0] == FID and row[0][1] is None and row[0][2], f"freelancer: the mail is a task in her basket {row}")


def stubfile(name):
    try:
        return open(os.path.join(DATA, "mail", name)).read().split()
    except OSError:
        return []


check(until(lambda: "1" in stubfile("deleted") and stubfile("expunged"), 20), f"freelancer: the mail is deleted from the mailbox {stubfile('deleted')}")

sys.exit(done("p2240_a_mail"))
