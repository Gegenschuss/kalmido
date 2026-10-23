#!/usr/bin/env python3
"""2.49.0 part A API tests (#1531 "Forgot your password?"), own container (start.sh) with the SMTP stub (stub_mail.py):
the login page learns whether the link is shown (GET /api/auth/info: forgot), POST /api/auth/forgot answers the same for
known, unknown and excluded addresses (status, body, a similar time), sends the one-time reset link only to a normal
account with a password and an address (never to kids, agents, disabled accounts or accounts without a password), one
link per account in five minutes, the link works once and ends the other sessions, the rate limit per address and sender
answers the same and sends nothing, two-factor sign-in stays required after a reset, without outgoing mail the link is
hidden and nothing is sent. The rate limit lives in the app's memory: a restart (KEEP=1) starts each phase afresh."""
import email as _em
import json
import os
import re
import shutil
import subprocess
import sys
import time
import base64
import hashlib
import hmac
import struct

import requests
import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
from kt import FAILS, OKS, check, sess, until, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
SMTP = (" -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none"
        " -e KALMIDO_MAIL_FROM=kalmido@example.test")


def dbx(q, a=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8")]
    except OSError:
        return []


def link_of(m):
    msg = _em.message_from_string(m["raw"])
    parts = {p.get_content_type(): p for p in msg.walk()}
    txt = parts["text/plain"].get_payload(decode=True).decode() if "text/plain" in parts else ""
    return msg, txt, (re.search(r"(https?://[^\s/]+)/#invite/([A-Za-z0-9_-]{20,100})", txt) or [None, None, None])


def forgot(login, host=None):
    t = time.time()
    r = requests.post(B + "/api/auth/forgot", headers={**H, **({"Host": host} if host else {})}, json={"login": login})
    return r, time.time() - t


def totp(secret):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest()
    o = mac[-1] & 15
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def start(extra, keep=False):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + extra, **({"KEEP": "1"} if keep else {}))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    if "SMTP" in extra:
        shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
        subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
        time.sleep(1)


# ================================================================== phase 1: with outgoing mail
start(SMTP)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ids = {}
for un in ("bob", "tim", "agentx", "dora", "olga"):
    j = {"username": un, "display_name": un.title(), "email": un + "@example.com"}
    if un != "olga":  # olga: an account without a password (single sign-on only)
        j["password"] = "password123"
    r = A.post(B + "/api/users", json=j)
    assert r.ok, r.text
    ids[un] = r.json()["id"]
dbx("UPDATE users SET kid=1 WHERE id=?", (ids["tim"],))
dbx("UPDATE users SET kind='agent' WHERE id=?", (ids["agentx"],))
dbx("UPDATE users SET disabled=1 WHERE id=?", (ids["dora"],))
dbx("UPDATE users SET password_hash=NULL WHERE id=?", (ids["olga"],))
check(dbx("SELECT email FROM users WHERE id=?", (ids["olga"],)) == [("olga@example.com",)], "setup: the addresses are stored")
Bo = sess("bob")
check(requests.get(B + "/api/auth/info").json().get("forgot") is True, "with SMTP the login page shows the link")

m0 = len(mails())
r1, t1 = forgot("nobody@example.com")
r2, t2 = forgot("bob@example.com", host="evil.example")  # a forged Host header must not reach the link
check(r1.status_code == r2.status_code == 200 and r1.json() == r2.json() == {"ok": True}, "the same answer for an unknown and a known address")
# 2.58.0 (#1792): the padding is a fixed total of about 0.9 s now
check(min(t1, t2) >= 0.85 and abs(t1 - t2) < 0.3, f"a similar answer time ({t1:.2f} s / {t2:.2f} s)")
ml = until(lambda: [x for x in mails()[m0:] if "bob@example.com" in x["to"]], 10)
check(len(ml) == 1, "bob gets one mail")
msg, txt, mt = link_of(ml[0]) if ml else (None, "", [None, None, None])
tok = mt[2]
check(tok and mt[1] and "evil.example" not in mt[1] and "127.0.0.1" not in mt[1], "the link comes from PUBLIC_URL, not from the request: " + str(mt[1]))
check("Someone asked for a link" in txt and "hopefully you" in txt, "the mail says it was asked for on the login page (no admin named)")
inv = dbx("SELECT kind, created_by, token_hash FROM user_invites WHERE user_id=?", (ids["bob"],))
check(inv and inv[0][0] == "reset" and inv[0][1] is None and tok and inv[0][2] == hashlib.sha256(tok.encode()).hexdigest() and tok not in json.dumps(inv),
      "a reset link, only its hash stored")
for who in ("BOB", "tim@example.com", "agentx@example.com", "dora@example.com", "olga@example.com"):
    r, _ = forgot(who)
    check(r.status_code == 200 and r.json() == {"ok": True}, "the same answer for " + who)
time.sleep(1.5)
check(len(mails()) - m0 == 1, "no second mail within five minutes, none for a kid, an agent, a disabled account, an account without a password")
check(not dbx("SELECT 1 FROM user_invites WHERE user_id IN (?,?,?,?)", (ids["tim"], ids["agentx"], ids["dora"], ids["olga"])), "no link for them either")
check(requests.post(B + "/api/auth/forgot", headers=H, json={"login": ""}).status_code == 400, "an empty field: 400")

# the link: once, ends the other sessions, signs in (no two-factor)
P = sess()
check(P.post(B + "/api/auth/invite/check", json={"token": tok}).json().get("kind") == "reset", "the link opens the page Set a new password")
r = P.post(B + "/api/auth/invite/accept", json={"token": tok, "password": "bob-new-pass-1"})
check(r.ok and r.json().get("ok") and P.get(B + "/api/me").json().get("username") == "bob", "new password set, signed in")
check(Bo.get(B + "/api/me").status_code == 401, "the old session ended")
check(sess().post(B + "/api/auth/invite/accept", json={"token": tok, "password": "bob-other-pass"}).status_code == 404, "the link works once")
check(sess().post(B + "/api/auth/login", json={"username": "bob", "password": "bob-new-pass-1"}).ok, "login with the new password")

# the rate limit per address + sender: the 4th request within 15 minutes sends nothing, the answer stays the same
m1 = len(mails())
dbx("UPDATE user_invites SET created_at='2000-01-01T00:00:00+00:00' WHERE user_id=?", (ids["bob"],))
r, _ = forgot("bob@example.com")  # the 2nd for this address
check(r.json() == {"ok": True} and until(lambda: len(mails()) > m1, 10), "after five minutes a new link is possible")
dbx("UPDATE user_invites SET created_at='2000-01-01T00:00:00+00:00' WHERE user_id=?", (ids["bob"],))
forgot("bob@example.com")  # the 3rd
until(lambda: len(mails()) > m1 + 1, 10)
dbx("UPDATE user_invites SET created_at='2000-01-01T00:00:00+00:00' WHERE user_id=?", (ids["bob"],))
m2 = len(mails())
r, _ = forgot("bob@example.com")  # the 4th: blocked
time.sleep(1.5)
check(r.status_code == 200 and r.json() == {"ok": True} and len(mails()) == m2, "the rate limit: the same answer, no mail")

# ================================================================== phase 2: two-factor stays required after a reset
start(SMTP, keep=True)
Bo = sess("bob", "bob-new-pass-1")
r = Bo.post(B + "/api/me/2fa/totp", json={"password": "bob-new-pass-1"})
sec = r.json()["secret"].replace(" ", "") if r.ok else ""
check(r.ok and Bo.post(B + "/api/me/2fa/totp/confirm", json={"code": totp(sec)}).ok, "bob turns on two-factor sign-in")
dbx("UPDATE user_invites SET created_at='2000-01-01T00:00:00+00:00' WHERE user_id=?", (ids["bob"],))
m3 = len(mails())
forgot("bob@example.com")
ml = until(lambda: [x for x in mails()[m3:] if "bob@example.com" in x["to"]], 10)
tok = link_of(ml[0])[2][2] if ml else None
P = sess()
r = P.post(B + "/api/auth/invite/accept", json={"token": tok, "password": "bob-third-pass"})
check(r.ok and r.json().get("twofa") and not r.json().get("ok") and "totp" in r.json().get("methods", []), "after the reset the second step follows " + r.text[:120])
check(P.get(B + "/api/me").status_code == 401, "no session before the second step")
check(Bo.get(B + "/api/me").status_code == 401, "the old session ended")
st = int(time.time() // 30)  # a fresh TOTP step (the enrolment used the current one)
while int(time.time() // 30) == st:
    time.sleep(0.5)
r = P.post(B + "/api/auth/2fa", json={"code": totp(sec)})
check(r.ok and P.get(B + "/api/me").json().get("username") == "bob", "with the code: signed in")

# ================================================================== phase 3: without outgoing mail
start("", keep=True)
check(requests.get(B + "/api/auth/info").json().get("forgot") is False, "without SMTP the link is hidden")
m4 = len(mails())
r, _ = forgot("bob@example.com")
time.sleep(1)
check(r.status_code == 200 and r.json() == {"ok": True} and len(mails()) == m4, "without SMTP: the same answer, nothing sent")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
