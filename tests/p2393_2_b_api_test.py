#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.393.2 B (#3375): the mail thread of a task, own container (start.sh with the IMAP + SMTP stubs of tests/stub_mail.py).
Invented people and addresses only.
freelancer-matrix: mail
 - a task from the server's mailbox keeps its Message-ID and sender (task_mail 'in' = the reporter)
 - a reply (In-Reply-To) from the reporter becomes a comment of the task: no new task, the quote below "On ... wrote:" and the
   signature cut off, "By e-mail from ..." visible, its file a file of the comment; the same mail again changes nothing
 - a reply from an address that is neither the reporter nor a person who sees the task: a new task as before, with the note
   "Reply to #N, sender not allowed", no comment
 - the signed reply address of the task (+r<id>x<signature>): the reporter's mail to it becomes a comment (also without
   In-Reply-To); another sender to the same address is no comment and no task (the token is bound to the address)
 - a person who sees the task answers by mail from the account's address: a comment in their name
 - the comment field's switch: timeline mail_reporter {address, may}; POST comments mail_reporter true -> the SMTP stub gets
   "Re: <title>" to the reporter with Reply-To = the task's reply address, In-Reply-To / References = the task's Message-IDs,
   its Message-ID stored as 'out'; the reporter's reply to it becomes a comment again
 - refused: a task without a reporter (400), someone who does not see the task, a list with the lock (400, no mail); API v1:
   mail_reporter is a known field (no unknown_field)
 - a person without an organisation: the same in her own basket
usage: p2393_2_b_api_test.py <datadir>"""
import email
import email.message
import email.policy
import json
import os
import shutil
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
import kt  # noqa: E402
from kt import B, CT, DATA, H, check, dbx, done, until  # noqa: E402

MAILENV = {"KALMIDO_MAIL_ADDRESS": "tasks@example.test", "KALMIDO_IMAP_HOST": "127.0.0.1", "KALMIDO_IMAP_PORT": "1143",
           "KALMIDO_IMAP_SSL": "0", "KALMIDO_IMAP_USER": "kalmido", "KALMIDO_IMAP_PASSWORD": "secret", "KALMIDO_IMAP_INTERVAL": "600",
           "KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
           "KALMIDO_MAIL_FROM": "kalmido@example.test"}
kt.fresh(MAILENV)
os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"], check=True)
until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 1143), 1)"],
                             capture_output=True).returncode == 0, 20)

A = kt.setup()
BU, Bo = freelancer(B, A, "bea")    # receives the mails (her personal address), works on the tasks
CU, Ca = freelancer(B, A, "cleo")   # an account that does not see Bea's tasks
EU, Er = freelancer(B, A, "edda")   # a person without an organisation with her own basket (matrix row)
NEXT = [0]


def wr(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def addr_of(s):
    r = s.post(B + "/api/me/mail/token", json={})
    assert r.ok, r.text
    return r.json()["address"]


def mail(frm, to, subject, text, mid, reply=None, files=()):
    """One mail into the stub mailbox, then a poll; -> its Message-ID."""
    NEXT[0] += 1
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = frm, to, subject, mid
    m["Date"] = "Mon, 02 Nov 2026 10:00:00 +0100"
    if reply:
        m["In-Reply-To"] = reply
        m["References"] = reply
    m.set_content(text)
    for name, data in files:
        m.add_attachment(data, maintype="text", subtype="plain", filename=name)
    with open(os.path.join(DATA, "mail", "in", f"{NEXT[0]}.eml"), "wb") as f:
        f.write(bytes(m))
    return mid


def poll(cond, secs=40):
    A.post(B + "/api/admin/mail/poll")
    return until(cond, secs)


def seen_all():
    try:
        s = set(open(os.path.join(DATA, "mail", "seen")).read().split())
    except OSError:
        s = set()
    return all(str(i) in s for i in range(1, NEXT[0] + 1))


def comments(tid):
    return dbx("SELECT id, user_id, body, ext_name FROM comments WHERE task_id=? AND deleted_at IS NULL ORDER BY id", (tid,))


def task_of(mid):
    r = dbx("SELECT id, content, list_id FROM tasks WHERE tt_id=?", ("mail:" + mid,))
    return r[0] if r else None


def sent():
    p = os.path.join(DATA, "mail", "out.jsonl")
    out = []
    if os.path.exists(p):
        for ln in open(p):
            if ln.strip():
                out.append(email.message_from_string(json.loads(ln)["raw"], policy=email.policy.default))
    return out


def reply_addr(tid, who):
    code = ("import app\nfrom kalmido.core.db import connect\nfrom kalmido.integrations.taskmail import tmr_reply_to\n"
            f"c = connect()\nprint(tmr_reply_to(c, {int(tid)}, {who!r}))\nc.close()\n")
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=120)
    return (r.stdout.strip().splitlines() or [""])[-1]


BA = addr_of(Bo)
REP = "Rita Reporter <rita@example.com>"

# ---- 1. a task from the mailbox keeps Message-ID + sender
M1 = mail(REP, BA, "Printer is broken", "The printer in room 2 prints nothing.", "<p23932b-1@example.org>")
t1 = poll(lambda: task_of(M1))
check(bool(t1), f"the mail is a task {t1}")
T1 = t1[0] if t1 else 0
r = dbx("SELECT msg_id, sender, kind FROM task_mail WHERE task_id=?", (T1,))
check(r == [(M1, "rita@example.com", "in")], f"task_mail keeps Message-ID + sender {r}")

# ---- 2. the reporter's reply by In-Reply-To -> a comment (quote and signature cut off, the file a file of the comment)
M2 = mail(REP, BA, "Re: Printer is broken", "Thanks, it works again.\n\nOn Mon, 2 Nov 2026 Bea wrote:\n> Did you restart it?\n",
          "<p23932b-2@example.org>", reply=M1, files=[("log.txt", b"paper jam cleared")])
cm = poll(lambda: comments(T1))
check(len(cm) == 1 and not task_of(M2), f"the reply is a comment, no new task {cm} {task_of(M2)}")
body = cm[0][2] if cm else ""
check(body.startswith("Thanks, it works again.") and "Did you restart" not in body and "wrote:" not in body, f"quote cut off: {body!r}")
check("By e-mail from rita@example.com" in body and cm[0][1] is None and (cm[0][3] or "") == "Rita Reporter", f"the sender is shown {cm}")
att = dbx("SELECT name, comment_id FROM attachments WHERE task_id=? AND deleted_at IS NULL", (T1,))
check(att == [("log.txt", cm[0][0])] if cm else False, f"the file is a file of the comment {att}")
M2b = mail(REP, BA, "Re: Printer is broken", "Thanks again", "<p23932b-2@example.org>", reply=M1)  # the same Message-ID again
poll(seen_all)
check(len(comments(T1)) == 1, f"the same mail again: no second comment {comments(T1)}")

# ---- 3. a sender who is not allowed: a new task with the note, no comment
M3 = mail("Cleo <cleo@example.com>", BA, "Re: Printer is broken", "I want to read along.", "<p23932b-3@example.org>", reply=M1)
t3 = poll(lambda: task_of(M3))
check(bool(t3) and f"Reply to #{T1}, sender not allowed" in (t3[1] or ""), f"not allowed: a new task with the note {t3}")
check(len(comments(T1)) == 1, f"not allowed: no comment {comments(T1)}")

# ---- 4. the signed reply address: the reporter's mail is a comment, another sender none (and no task: no address the import takes)
RA = reply_addr(T1, "rita@example.com")
check(RA.startswith("tasks+r") and f"r{T1}x" in RA and RA.endswith("@example.test"), f"reply address {RA!r}")
M4 = mail(REP, RA, "Printer", "One more thing: the toner is low.", "<p23932b-4@example.org>")
poll(lambda: len(comments(T1)) == 2)
check(len(comments(T1)) == 2 and "toner is low" in comments(T1)[-1][2], f"the reply address: a comment {comments(T1)}")
M5 = mail("Cleo <cleo@example.com>", RA, "Printer", "Forged reply", "<p23932b-5@example.org>")
poll(seen_all)
check(len(comments(T1)) == 2 and not task_of(M5), f"another sender to the reply address: nothing {comments(T1)} {task_of(M5)}")
bad = RA.replace(RA.split("x", 1)[1][:4], "0000")
M5b = mail(REP, bad, "Printer", "Bad signature", "<p23932b-5b@example.org>")
poll(seen_all)
check(len(comments(T1)) == 2, f"a wrong signature counts as no address {comments(T1)}")

# ---- 5. a person who sees the task answers by mail from her account's address: a comment in her name
M6 = mail("Bea <bea@example.com>", BA, "Re: Printer is broken", "I ordered new toner.\n-- \nBea, office", "<p23932b-6@example.org>", reply=M1)
poll(lambda: len(comments(T1)) == 3)
cm = comments(T1)
check(len(cm) == 3 and cm[-1][1] == BU and "Bea, office" not in cm[-1][2], f"a member's mail: her comment, signature cut off {cm[-1:]}")

# ---- 6. the switch: answer to the reporter
tl = Bo.get(B + f"/api/tasks/{T1}/timeline").json()
check(tl.get("mail_reporter") == {"address": "rita@example.com", "may": True, "e2e": False}, f"timeline mail_reporter {tl.get('mail_reporter')}")
n0 = len(sent())
r = Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "We replaced the toner.", "mail_reporter": True})
check(r.ok and r.json().get("mail_reporter") == "sent", f"comment with mail_reporter {r.status_code} {r.text[:200]}")
out = until(lambda: sent()[n0:], 20) or []
m = out[-1] if out else {}
check(bool(out) and m["To"] == "rita@example.com" and m["Subject"] == "Re: Printer is broken", f"the mail to the reporter {[(x['To'], x['Subject']) for x in out]}")
check(bool(out) and f"r{T1}x" in str(m["Reply-To"]) and str(m["Reply-To"]) == RA, f"Reply-To = the task's reply address {m.get('Reply-To') if out else None}")
check(bool(out) and str(m["In-Reply-To"]) and str(m["In-Reply-To"]) in str(m["References"]) and M1 in str(m["References"]), f"In-Reply-To / References {m.get('In-Reply-To') if out else None}")
check(bool(out) and "We replaced the toner." in m.get_body(("plain",)).get_content(), "the text of the comment goes out")
OUT = str(m["Message-ID"]) if out else ""
check(bool(OUT) and dbx("SELECT kind, sender FROM task_mail WHERE task_id=? AND msg_id=?", (T1, OUT)) == [("out", "rita@example.com")], f"its Message-ID stored as out {OUT}")
M7 = mail(REP, BA, "Re: Printer is broken", "Great, thank you!", "<p23932b-7@example.org>", reply=OUT)
poll(lambda: len(comments(T1)) == 5)
check(len(comments(T1)) == 5 and "Great, thank you!" in comments(T1)[-1][2], f"the reply to our mail is a comment again {comments(T1)[-1:]}")

# ---- 7. refused
Lb = Bo.post(B + "/api/lists", json={"name": "Desk"}).json()["id"]
Tn = Bo.post(B + "/api/tasks", json={"title": "No mail", "list_id": Lb}).json()["id"]
r = Bo.post(B + f"/api/tasks/{Tn}/comments", json={"body": "x", "mail_reporter": True})
check(r.status_code == 400, f"no reporter: 400 {r.status_code}")
check(Bo.get(B + f"/api/tasks/{Tn}/timeline").json().get("mail_reporter") is None, "no reporter: timeline mail_reporter null")
r = Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "x", "mail_reporter": "maybe"})
check(r.status_code == 400, f"mail_reporter not a boolean: 400 {r.status_code}")
r = Ca.post(B + f"/api/tasks/{T1}/comments", json={"body": "x", "mail_reporter": True})
check(r.status_code in (403, 404), f"someone who does not see the task: {r.status_code}")
tok = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "comments"]})
check(tok.status_code == 201, f"a personal API token {tok.status_code} {tok.text[:200]}")
r = requests.post(B + f"/api/v1/tasks/{Tn}/comments", headers={"Authorization": "Bearer " + tok.json().get("token", ""), **H},
                  json={"body": "x", "mail_reporter": True})
check(r.status_code == 400 and "unknown_field" not in r.text, f"API v1: mail_reporter known, no reporter 400 {r.status_code} {r.text[:200]}")
L1 = t1[2] if t1 else 0
n0 = len(sent())
wr("UPDATE lists SET e2e='on' WHERE id=?", (L1,))  # the basket with the lock (state only: the check reads it)
r = Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "x", "mail_reporter": True})
check(r.status_code == 400 and "end-to-end" in r.text, f"a list with the lock: 400 {r.status_code} {r.text[:200]}")
check(Bo.get(B + f"/api/tasks/{T1}/timeline").json().get("mail_reporter", {}).get("may") is False, "a list with the lock: the switch is off")
M8 = mail(REP, BA, "Re: Printer is broken", "Locked?", "<p23932b-8@example.org>", reply=M1)
poll(seen_all)
check(len(comments(T1)) == 5, f"a list with the lock takes no mail comment {len(comments(T1))}")
check(len(sent()) == n0, "a list with the lock: no mail")
wr("UPDATE lists SET e2e=NULL WHERE id=?", (L1,))

# ---- 8. a person without an organisation: her own basket
EA = addr_of(Er)
M9 = mail("Otto <otto@example.com>", EA, "Garden fence", "The fence needs paint.", "<p23932b-9@example.org>")
t9 = poll(lambda: task_of(M9))
check(bool(t9), f"freelancer: a task in her basket {t9}")
T9 = t9[0] if t9 else 0
M10 = mail("Otto <otto@example.com>", EA, "Re: Garden fence", "White, please.\n\nAm 02.11.2026 schrieb Edda:\n> Which colour?", "<p23932b-10@example.org>", reply=M9)
poll(lambda: comments(T9))
cm = comments(T9)
check(len(cm) == 1 and cm[0][2].startswith("White, please.") and "Which colour" not in cm[0][2], f"freelancer: the reply is a comment {cm}")
r = Er.post(B + f"/api/tasks/{T9}/comments", json={"body": "White it is.", "mail_reporter": True})
check(r.ok and r.json().get("mail_reporter") == "sent", f"freelancer: answer to the reporter {r.status_code} {r.text[:200]}")
check(until(lambda: any(x["To"] == "otto@example.com" for x in sent()), 20), "freelancer: the mail goes out")

sys.exit(done("p2393_2_b_api"))
