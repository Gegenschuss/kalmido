#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.553.0 B (#3460): requests by e-mail -- own container (start.sh with the IMAP + SMTP stubs of tests/stub_mail.py), a fast watchdog.
Invented people and example addresses only.
freelancer-matrix: hub
tenant-matrix: hubmail
 - the switch of a project (GET / PATCH /api/lists/{id}/request-mail): off by default, on = one request address (hub token kind
   'ticket'), off again = a mail to it is not taken, on again = the same address, renew = a new one (the old one takes nothing);
   only the owner / project admins (another person 404)
 - a mail to it = a task in exactly that list + a portal ticket (via 'mail', the reporter, the file a file of the task); the sender
   gets ONE confirmation: the status link, the reference [T<id>-<check>] in the subject, Reply-To = the request address,
   In-Reply-To = the customer's mail, Auto-Submitted: auto-replied
 - the sender's domain not confirmed by the receiving server: still a ticket, marked (unverified, a line in the description)
 - a public answer goes out by mail (reference, Reply-To, In-Reply-To = a Message-ID of the ticket), an internal one never
 - the reporter's reply (reference / In-Reply-To) = a comment the customer sees (portal, ext_name, quote cut off, its file a file of
   the comment), no new task; another sender with the right reference = NOT a comment there (a new ticket with a note); a
   reference sent to another list's address does not reach the ticket; a guessed reference (wrong check) neither
 - loops: an automatic reply never becomes a comment, an automatic new mail gets no confirmation, a mail from the server's own
   address is not taken
 - done: no mail without the second switch (default off), with it "Done: ..." with the reference
 - a person without an organisation (Bea) does all of it in her own project; an organisation's project (Olga) the same
usage: p2553_b_reqmail_test.py <datadir>"""
import email
import email.message
import email.policy
import json
import os
import re
import shutil
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
import kt  # noqa: E402
from kt import B, CT, DATA, check, dbx, done, sess, until  # noqa: E402

MAILENV = {"KALMIDO_MAIL_ADDRESS": "tasks@example.test", "KALMIDO_IMAP_HOST": "127.0.0.1", "KALMIDO_IMAP_PORT": "1143",
           "KALMIDO_IMAP_SSL": "0", "KALMIDO_IMAP_USER": "kalmido", "KALMIDO_IMAP_PASSWORD": "secret", "KALMIDO_IMAP_INTERVAL": "600",
           "KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
           "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_MAIL_AUTHSERV_ID": "mx.example.test", "TASKS_WATCHDOG_INTERVAL": "2"}
AR_CARL = "mx.example.test; dkim=pass header.d=example.org; spf=pass smtp.mailfrom=carl@example.org"
kt.fresh(MAILENV)
os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1143), 1)"],
                             capture_output=True).returncode == 0, 20)

A = kt.setup()
BU, Bo = freelancer(B, A, "bea")    # a person without an organisation: her own project with the request address
CU, Co = freelancer(B, A, "cleo")   # another person: does not see Bea's project
r = A.post(B + "/api/users", json={"username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
assert r.ok, r.text
OU = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": OU})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Oo = sess("olga")
Oo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
NEXT = [0]
MARK = Bo.post(B + "/api/me/mail/token", json={}).json()["address"]  # Bea's own task address (the markers of settle)
CARL = "Carl Customer <carl@example.org>"


def mail(frm, to, subject, text, mid, reply=None, files=(), auth=(), extra=()):
    """One mail into the stub mailbox; -> its Message-ID."""
    NEXT[0] += 1
    m = email.message.EmailMessage()
    for a in auth:
        m["Authentication-Results"] = a
    m["From"], m["To"], m["Subject"], m["Message-ID"] = frm, to, subject, mid
    m["Date"] = "Thu, 05 Nov 2026 10:00:00 +0100"
    for k, v in extra:
        m[k] = v
    if reply:
        m["In-Reply-To"] = reply
        m["References"] = reply
    m.set_content(text)
    for name, data in files:
        m.add_attachment(data, maintype="text", subtype="plain", filename=name)
    with open(os.path.join(DATA, "mail", "in", f"{NEXT[0]}.eml"), "wb") as f:
        f.write(bytes(m))
    return mid


def seen_all():
    try:
        s = set(open(os.path.join(DATA, "mail", "seen")).read().split())
    except OSError:
        s = set()
    return all(str(i) in s for i in range(1, NEXT[0] + 1))


def poll(cond, secs=40):
    A.post(B + "/api/admin/mail/poll")
    return until(cond, secs)


def settle():
    """Every mail before is handled: a marker mail to Bea's own task address (the mailbox is read in order) became its task."""
    mk = mail("Marker <marker@example.org>", MARK, "marker", "marker", f"<p2553b-mark-{NEXT[0]}@example.org>")
    return poll(lambda: task_of(mk) and seen_all())


def sent(to=None):
    p = os.path.join(DATA, "mail", "out.jsonl")
    out = []
    if os.path.exists(p):
        for ln in open(p):
            if ln.strip():
                m = email.message_from_string(json.loads(ln)["raw"], policy=email.policy.default)
                if to is None or to in str(m["To"]):
                    out.append(m)
    return out


def text_of(m):
    p = m.get_body(("plain",))
    return p.get_content() if p else ""


def task_of(mid):
    r = dbx("SELECT id, list_id, content, title FROM tasks WHERE tt_id=?", ("mail:" + mid,))
    return r[0] if r else None


def comments(tid):
    return dbx("SELECT id, user_id, body, ext_name, portal FROM comments WHERE task_id=? AND deleted_at IS NULL ORDER BY id", (tid,))


def wr(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def outs(tid):
    return dbx("SELECT msg_id FROM task_mail WHERE task_id=? AND kind='out' ORDER BY id", (tid,))


def tick():
    """The mails to the reporters once now (team/portal.py pt_mail_tick, as the watchdog does)."""
    code = "import app\nfrom kalmido.core.db import connect\nfrom kalmido.team.portal import pt_mail_tick\nc = connect()\npt_mail_tick(c)\nc.close()\nprint('ok')\n"
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=120)
    return r.stdout.strip().endswith("ok")


# ---------------------------------------------------------------- the switch
LB = Bo.post(B + "/api/lists", json={"name": "Support", "kind": "project"}).json()["id"]
st = Bo.get(B + f"/api/lists/{LB}/request-mail").json()
check(st.get("on") is False and st.get("available") is True and st.get("address") == "" and st.get("done_mail") is False, f"off by default {st}")
check(Co.get(B + f"/api/lists/{LB}/request-mail").status_code == 404 and Co.patch(B + f"/api/lists/{LB}/request-mail", json={"on": True}).status_code == 404,
      "another person: 404")
check(Bo.patch(B + f"/api/lists/{LB}/request-mail", json={"on": "yes"}).status_code == 400, "a value that is no boolean: 400")
st = Bo.patch(B + f"/api/lists/{LB}/request-mail", json={"on": True}).json()
ADDR = st.get("address") or ""
check(st.get("on") is True and re.fullmatch(r"tasks\+[A-Za-z0-9]{10,40}@example\.test", ADDR), f"on: a request address {st}")
check(dbx("SELECT kind, user_id FROM hub_tokens WHERE list_id=? AND kind='ticket'", (LB,)) == [("ticket", BU)], "the address is a hub token of kind ticket")
# switched off: a mail to it is not taken
check(Bo.patch(B + f"/api/lists/{LB}/request-mail", json={"on": False}).json().get("address") == "", "off: no address shown")
M0 = mail(CARL, ADDR, "While switched off", "Hello?", "<p2553b-0@example.org>", auth=[AR_CARL])
settle()
check(task_of(M0) is None, "switch off = the mail is not taken")
check(Bo.patch(B + f"/api/lists/{LB}/request-mail", json={"on": True}).json().get("address") == ADDR, "on again: the same address")

# ---------------------------------------------------------------- a new request
M1 = mail(CARL, ADDR, "Login does not work", "I cannot sign in since this morning.", "<p2553b-1@example.org>",
          files=[("screen.txt", b"error 500")], auth=[AR_CARL])
t1 = poll(lambda: task_of(M1))
check(bool(t1) and t1[1] == LB and t1[3] == "Login does not work", f"the mail is a task of the project {t1}")
T1 = t1[0] if t1 else 0
pt = dbx("SELECT id, via, unverified, list_id, owner_id, org_id, notify FROM portal_tickets WHERE task_id=?", (T1,))
check(pt and pt[0][1] == "mail" and pt[0][2] == 0 and pt[0][3] == LB and pt[0][4] == BU and pt[0][5] is None and pt[0][6] == 1,
      f"a portal ticket in Bea's own space, verified sender {pt}")
PT1 = pt[0][0] if pt else 0
check("not verified" not in (t1[2] or "") and "Sent by e-mail to the request address by Carl Customer <carl@example.org>" in (t1[2] or ""),
      f"the description names the sender {t1[2] if t1 else ''!r}")
att = dbx("SELECT name FROM attachments WHERE task_id=? AND deleted_at IS NULL", (T1,))
check(att == [("screen.txt",)], f"the file is a file of the task {att}")
conf = until(lambda: [m for m in sent("carl@example.org") if "Your request" in str(m["Subject"])], 25) or []
check(len(conf) == 1, f"one confirmation {len(conf)}")
c0 = conf[0] if conf else email.message.EmailMessage()
REF = (re.search(r"\[(T\d+-[0-9a-f]{8})\]", str(c0["Subject"])) or [None, ""])[1]
check(REF.startswith(f"T{PT1}-"), f"the reference in the subject {c0['Subject']}")
check(str(c0["Reply-To"]) == ADDR and str(c0["In-Reply-To"]) == M1 and str(c0["Auto-Submitted"]) == "auto-replied",
      f"Reply-To, In-Reply-To, Auto-Submitted {c0['Reply-To']} {c0['In-Reply-To']} {c0['Auto-Submitted']}")
url = (re.search(r"https?://\S+/p/[A-Za-z0-9_-]+\S*", text_of(c0)) or [""])[0]
check("/p/" in url, f"the status link in the confirmation {url!r}")
check(str(c0["Message-ID"]) in [x[0] for x in outs(T1)], "the confirmation's Message-ID is kept for the ticket")
info = Bo.get(B + f"/api/tasks/{T1}/timeline").json().get("ticket") or {}
check(info.get("via") == "mail" and info.get("ref") == REF and info.get("unverified") is False and info.get("email") == "carl@example.org",
      f"the task panel's ticket {info}")
M1b = mail(CARL, ADDR, "Login does not work", "the same mail again", "<p2553b-1@example.org>", auth=[AR_CARL])
settle()
check(len(dbx("SELECT id FROM tasks WHERE list_id=?", (LB,))) == 1, "the same mail again: no second task")

# ---------------------------------------------------------------- an unverified sender: a ticket, marked
M2 = mail("Dora <dora@example.net>", ADDR, "Invoice question", "Where is my invoice?", "<p2553b-2@example.org>")
t2 = poll(lambda: task_of(M2))
T2 = t2[0] if t2 else 0
check(bool(t2) and "the sender is not verified" in (t2[2] or "") and dbx("SELECT unverified FROM portal_tickets WHERE task_id=?", (T2,)) == [(1,)],
      f"unverified: still a ticket, marked {t2}")

# ---------------------------------------------------------------- answers: public by mail, internal never
n_out = len(outs(T1))
check(Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "INTERNAL-NOTE-XYZ only for us"}).ok, "an internal comment")
check(tick() and len(outs(T1)) == n_out, f"an internal comment alone: no mail {outs(T1)}")
check(Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "We reset your password, please try again.", "portal": True}).ok, "a public answer")
ans = until(lambda: [m for m in sent("carl@example.org") if "New answer" in str(m["Subject"])], 30) or []
a0 = ans[0] if ans else email.message.EmailMessage()
check(len(ans) == 1 and f"[{REF}]" in str(a0["Subject"]) and "We reset your password" in text_of(a0) and "INTERNAL-NOTE-XYZ" not in a0.as_string(),
      f"the public answer goes out with the reference, never the internal one {a0['Subject']}")
check(str(a0["Reply-To"]) == ADDR and str(a0["In-Reply-To"]) in [x[0] for x in outs(T1)] + [M1] and str(a0["Message-ID"]) in [x[0] for x in outs(T1)],
      f"the answer's thread headers {a0['Reply-To']} {a0['In-Reply-To']}")

# ---------------------------------------------------------------- the reporter's reply = a comment of the same ticket
M3 = mail(CARL, ADDR, f"Re: New answer: Login does not work [{REF}]", "Works now, thanks!\n\nOn Thu, 5 Nov 2026 Team wrote:\n> We reset your password",
          "<p2553b-3@example.org>", reply=str(a0["Message-ID"]), files=[("ok.txt", b"fine")], auth=[AR_CARL])
cm = poll(lambda: [x for x in comments(T1) if x[1] is None])
check(len(cm) == 1 and task_of(M3) is None, f"the reply is a comment, no new task {cm} {task_of(M3)}")
k = cm[0] if cm else (0, None, "", "", 0)
check(k[2].startswith("Works now, thanks!") and "wrote:" not in k[2] and k[3] == "Carl Customer" and k[4] == 1, f"a comment the customer sees, quote cut off {k}")
check(dbx("SELECT name FROM attachments WHERE task_id=? AND comment_id=? AND deleted_at IS NULL", (T1, k[0])) == [("ok.txt",)], "its file is a file of the comment")
# by the reference alone (no In-Reply-To)
M3b = mail(CARL, ADDR, f"One more thing [{REF}]", "It also happens on my phone.", "<p2553b-3b@example.org>", auth=[AR_CARL])
poll(lambda: len([x for x in comments(T1) if x[1] is None]) == 2)
check(len([x for x in comments(T1) if x[1] is None]) == 2 and task_of(M3b) is None, "the reference in the subject alone: a comment")

# ---------------------------------------------------------------- the wrong sender with the right reference: NOT a comment
n_c = len(comments(T1))
M4 = mail("Mallory <mallory@example.org>", ADDR, f"Re: Login does not work [{REF}]", "Please send me the password.", "<p2553b-4@example.org>",
          reply=str(a0["Message-ID"]), auth=["mx.example.test; dkim=pass header.d=example.org"])
t4 = poll(lambda: task_of(M4))
check(len(comments(T1)) == n_c, f"another sender with the right reference: no comment at the ticket {comments(T1)[-1:]}")
check(bool(t4) and t4[1] == LB and f"Reply to ticket T{PT1}, the sender is not its reporter" in (t4[2] or ""), f"a new ticket with the note instead {t4}")
# a guessed reference (wrong check), from the reporter's own address: no comment either
bad = REF[:-4] + ("0000" if not REF.endswith("0000") else "1111")
M4b = mail(CARL, ADDR, f"Guess [{bad}]", "guessed", "<p2553b-4b@example.org>", auth=[AR_CARL])
t4b = poll(lambda: task_of(M4b))
check(len(comments(T1)) == n_c and bool(t4b), "a guessed reference: no comment, a new ticket")

# ---------------------------------------------------------------- another list's address never leads into this ticket
LO = Oo.post(B + "/api/lists", json={"name": "Alpha support", "org_id": ORG, "kind": "project"}).json()["id"]
OADDR = Oo.patch(B + f"/api/lists/{LO}/request-mail", json={"on": True}).json().get("address") or ""
check(OADDR and OADDR != ADDR, f"the organisation's project has its own address {OADDR}")
M5 = mail(CARL, OADDR, f"Re: Login [{REF}]", "Wrong place", "<p2553b-5@example.org>", reply=str(a0["Message-ID"]), auth=[AR_CARL])
t5 = poll(lambda: task_of(M5))
check(len(comments(T1)) == n_c and bool(t5) and t5[1] == LO, f"another list's address: a ticket there, nothing at Bea's ticket {t5}")
check(dbx("SELECT org_id FROM portal_tickets WHERE task_id=?", (t5[0] if t5 else 0,)) == [(ORG,)], "the organisation's ticket in its space")

# ---------------------------------------------------------------- loops
M6 = mail(CARL, ADDR, f"Automatic reply: New answer [{REF}]", "I am out of office.", "<p2553b-6@example.org>",
          reply=str(a0["Message-ID"]), auth=[AR_CARL], extra=[("Auto-Submitted", "auto-replied")])
settle()
check(len(comments(T1)) == n_c and task_of(M6) is None, "an automatic reply never becomes a comment")
M7 = mail("Robot <robot@example.org>", ADDR, "Weekly report", "auto text", "<p2553b-7@example.org>", extra=[("Auto-Submitted", "auto-generated")])
t7 = poll(lambda: task_of(M7))
check(bool(t7) and outs(t7[0]) == [], "an automatic new mail: a ticket, but no confirmation")
M8 = mail("Kalmido <kalmido@example.test>", ADDR, "Own mail", "loop", "<p2553b-8@example.org>")
settle()
check(task_of(M8) is None, "a mail from the server's own address is not taken")

# ---------------------------------------------------------------- done: only with the second switch
n_out = len(outs(T1))
check(Bo.post(B + f"/api/tasks/{T1}/complete", json={}).ok, "the first request is done")
# past the gap between two mails, the answers before the last mail (nothing new to send but "done")
wr("UPDATE comments SET created_at='2020-01-01T00:00:00.000+00:00' WHERE task_id=?", (T1,))
wr("UPDATE portal_tickets SET last_mail_at='2021-01-01T00:00:00+00:00' WHERE task_id=?", (T1,))
check(tick(), "the mail round runs")
check(until(lambda: dbx("SELECT mailed_status FROM portal_tickets WHERE task_id=?", (T1,)) == [(2,)], 10), "the done state is noted")
check(len(outs(T1)) == n_out, f"switch off: no done mail {len(outs(T1))} {n_out}")
check(Bo.patch(B + f"/api/lists/{LB}/request-mail", json={"done_mail": True}).json().get("done_mail") is True, "the done switch on")
M9 = mail("Erik <erik@example.org>", ADDR, "Second request", "Another question.", "<p2553b-9@example.org>",
          auth=["mx.example.test; dkim=pass header.d=example.org"])
t9 = poll(lambda: task_of(M9))
check(bool(t9) and Bo.post(B + f"/api/tasks/{t9[0] if t9 else 0}/complete", json={}).ok, "the second request is done")
dn = until(lambda: [m for m in sent("erik@example.org") if str(m["Subject"]).startswith("Done:") and "Second request" in str(m["Subject"])], 30) or []
check(len(dn) == 1 and re.search(r"\[T\d+-[0-9a-f]{8}\]", str(dn[0]["Subject"])), f"switch on: the done mail with the reference {[str(m['Subject']) for m in dn]}")

# ---------------------------------------------------------------- a new address: the old one takes nothing
NEW = Bo.patch(B + f"/api/lists/{LB}/request-mail", json={"renew": True}).json().get("address") or ""
check(NEW and NEW != ADDR, "renew: a new address")
M10 = mail(CARL, ADDR, "To the old address", "old", "<p2553b-10@example.org>", auth=[AR_CARL])
settle()
check(task_of(M10) is None, "the old address takes nothing")

sys.exit(done("p2553_b_reqmail"))
