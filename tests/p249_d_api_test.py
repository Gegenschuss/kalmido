#!/usr/bin/env python3
"""2.49.0 API tests, part D: completed hidden in new lists / accounts (#1535) and forwarded mails shortened (#971); own container with the
e-mail stubs (stub_mail.py). Invented names and example.com addresses only.
 - a new account starts with show_done_default 0; new lists get an own entry in show_done_views (hide) while show_done_new is on
   (default), none with it off; a folder default (hide_done) goes first; existing lists are untouched
 - mail_trim_fwd off (default): a forwarded mail is imported as before; on: header line + message, signature cut, the original as .eml
   (unless mail_trim_eml is 0)
usage: p249_d_api_test.py <datadir>"""
import email.message
import email.utils
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402

from kt import FAILS, OKS, check, sess, until, B, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")


MAILENV = ["-e", "KALMIDO_MAIL_ADDRESS=tasks@example.test", "-e", "KALMIDO_IMAP_HOST=127.0.0.1", "-e", "KALMIDO_IMAP_PORT=1143",
           "-e", "KALMIDO_IMAP_SSL=0", "-e", "KALMIDO_IMAP_USER=kalmido", "-e", "KALMIDO_IMAP_PASSWORD=secret", "-e", "KALMIDO_IMAP_INTERVAL=10",
           "-e", "KALMIDO_SMTP_HOST=127.0.0.1", "-e", "KALMIDO_SMTP_PORT=1025", "-e", "KALMIDO_SMTP_TLS=none", "-e", "KALMIDO_MAIL_FROM=kalmido@example.test"]

subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
subprocess.run(["rm", "-rf", DATA])
os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)),
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
time.sleep(0.8)


def dbq(q, a=()):
    c = dbx.connect(os.path.join(DATA, "tasks.db"))
    try:
        return c.execute(q, a).fetchall()
    finally:
        c.close()


def sets(s):
    return s.get(B + "/api/state").json()["settings"]


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ================================================================== #1535
check(sets(A).get("show_done_default") == "0" and sets(A).get("show_done_new") == "1", f"a new account hides completed, new lists too {sets(A).get('show_done_default')}")
assert A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"}).ok
Bo = sess("bob")
check(sets(Bo).get("show_done_default") == "0", "an account made by an admin: the same")
L1 = A.post(B + "/api/lists", json={"name": "First"}).json()["id"]
views = lambda s: json.loads(sets(s).get("show_done_views") or "{}")  # noqa: E731
check(views(A).get(f"l:{L1}") == 0, f"a new list has its own entry (hide) {views(A)}")
check(A.patch(B + "/api/settings", json={"show_done_new": "maybe"}).status_code == 400, "show_done_new: only 0 / 1")
check(A.patch(B + "/api/settings", json={"show_done_new": "0"}).ok, "show_done_new off")
L2 = A.post(B + "/api/lists", json={"name": "Second"}).json()["id"]
check(f"l:{L2}" not in views(A) and views(A).get(f"l:{L1}") == 0, "off: no entry for the new list, the earlier entry stays")
A.patch(B + "/api/settings", json={"show_done_new": "1"})
check(A.put(B + "/api/folders/props", json={"folder": "Jobs", "props": {"hide_done": False}}).ok, "folder default: show completed")
L3 = A.post(B + "/api/lists", json={"name": "Third", "folder": "Jobs"}).json()["id"]
check(f"l:{L3}" not in views(A), "a folder default goes first: no own entry")
L4 = A.post(B + "/api/lists", json={"name": "Fourth", "folder": "Other"}).json()["id"]
check(views(A).get(f"l:{L4}") == 0, "a folder without a default: the entry")
check(f"l:{L1}" in views(A) and len(views(A)) == 2, "existing lists untouched: only the two entries " + str(views(A)))
check(f"l:{L1}" not in views(Bo), "another person's views are separate")

# ================================================================== #971
A.patch(B + "/api/settings", json={"mail_from_me": "0"})
check(not sets(A).get("mail_trim_fwd") or sets(A).get("mail_trim_fwd") == "0", "mail_trim_fwd is off by default")
check(A.patch(B + "/api/settings", json={"mail_trim_fwd": "x"}).status_code == 400, "mail_trim_fwd: only 0 / 1")
addr = A.post(B + "/api/me/mail/token", json={}).json()["address"]
j = A.get(B + "/api/me/mail").json()
check(j.get("trim_fwd") is False and j.get("trim_eml") is True, f"/api/me/mail: off, original kept {j}")
FWD = """Please file this.

---------- Forwarded message ---------
From: Jane Doe <jane@example.com>
Date: Mon, Oct 5, 2026 at 9:12 AM
Subject: Dentist on Friday
To: <me@example.com>

Your appointment is on Friday at 10:00.

> older quote

Best regards
Jane Doe
Example Dental
"""


def drop(n, subj, text, mid):
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "Jane <jane@example.com>", addr, subj, mid
    m.set_content(text)
    open(os.path.join(DATA, "mail", "in", f"{n}.eml"), "wb").write(bytes(m))


def task_by(title):
    r = dbq("SELECT id, content FROM tasks WHERE title=?", (title,))
    return r[0] if r else None


drop(1, "Fwd: Plain dentist", FWD, "<a1@client.test>")
A.post(B + "/api/admin/mail/poll")
t1 = until(lambda: task_by("Plain dentist"), 40)
check(t1 and "Best regards" in t1[1] and "Forwarded message" in t1[1], "off: the forwarded mail is imported as before")
check(t1 and dbq("SELECT COUNT(*) FROM attachments WHERE task_id=?", (t1[0],))[0][0] == 0, "off: no .eml attached")
A.patch(B + "/api/settings", json={"mail_trim_fwd": "1"})
drop(2, "Fwd: Short dentist", FWD, "<a2@client.test>")
A.post(B + "/api/admin/mail/poll")
t2 = until(lambda: task_by("Short dentist"), 40)
check(t2 and t2[1].startswith("Please file this.\n\nFrom Jane Doe, Mon, Oct 5, 2026 at 9:12 AM\n\nYour appointment is on Friday at 10:00."), f"on: header line + message {t2}")
check(t2 and "Best regards" not in t2[1] and "older quote" not in t2[1] and "Forwarded message" not in t2[1], "on: signature, quote and marker are gone")
at = dbq("SELECT name FROM attachments WHERE task_id=?", (t2[0],)) if t2 else []
check(len(at) == 1 and at[0][0].endswith(".eml"), f"on: the original is attached as .eml {at}")
A.patch(B + "/api/settings", json={"mail_trim_eml": "0"})
drop(3, "Fwd: No eml", FWD, "<a3@client.test>")
A.post(B + "/api/admin/mail/poll")
t3 = until(lambda: task_by("No eml"), 40)
check(t3 and "Best regards" not in t3[1] and dbq("SELECT COUNT(*) FROM attachments WHERE task_id=?", (t3[0],))[0][0] == 0, "on, .eml off: shortened, nothing attached")
drop(4, "A normal mail", "Hello, no forwarding here.\n\nBest regards\nJane", "<a4@client.test>")
A.post(B + "/api/admin/mail/poll")
t4 = until(lambda: task_by("A normal mail"), 40)
check(t4 and "Best regards" in t4[1], "on: a mail that is no forward is left alone")

print(f"p249_d_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
