#!/usr/bin/env python3
"""2.115.0 API tests, part B (#2062): active sessions and organisation invitations, own container (start.sh). Invented names
only, addresses @example.com.
 - two logins of one person: the list shows both, exactly one "current", device / browser / system read from the User-Agent,
   never the token hash or the cookie; last activity is not written on every request
 - ending one session: its cookie is 401 at once, its push subscription is gone, the one of the other session stays;
   a foreign / unknown session id 404; "log out everywhere else": only the current one stays; ending the current one = log out
 - the ordinary logout removes the push subscription of its session; agent tokens never reach the routes
 - a person without an organisation (freelancer-matrix: own): the same list, ending the others
 - organisation invitations (tenant-matrix: org): an organisation admin (not admin of the server) invites a new address ->
   account (no password) + member in the chosen role + the mail with the link (also in the answer); accepting sets the
   password and the person is in the organisation; an address with an account: the old answer, no invitation; a plain
   member 403, the admin of another organisation 404, an agent 403; resend (a new link, the old one stops working); withdraw
   deletes only an account this organisation invited that never signed in (404 after it signed in, 404 for another
   organisation); the daily limit (429); the server admin switches it off (403)
usage: p2115_b_api_test.py <datadir>      (a fresh container; P2115B_NOSTART=1 = the server already runs)"""
import base64
import email
import json
import re
import os
import shutil
import subprocess
import sys
import time

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
STUB = "http://127.0.0.1:9997"
from kt import FAILS, OKS, check, sess, until  # 2.192.0 (#2514): shared helpers (tests/kt.py)
UA_FF = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
UA_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
          "Mobile/15E148 Safari/604.1")


def b64u(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def subscribe(s, n):
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,
                                                                            serialization.PublicFormat.UncompressedPoint)
    r = s.post(B + "/api/push/subs", json={"endpoint": f"{STUB}/push/s{n}", "keys": {"p256dh": b64u(pub), "auth": b64u(os.urandom(16))},
                                          "label": f"device {n}"})
    assert r.ok, r.text
    return r.json()["id"]


def mails():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8")]
    except OSError:
        return []


if not os.environ.get("P2115B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_WEBPUSH_HOSTS={STUB} -e KALMIDO_SMTP_HOST=127.0.0.1"
               " -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(1)
DB = dbx.connect(DATA)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice", ua=UA_FF)
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "frank" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
ORG2 = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "admin"}).ok  # bob: admin of Alpha only

# ================================================================ sessions: the list
Bo1, Bo2 = sess("bob", ua=UA_FF), sess("bob", ua=UA_IOS)
sub1, sub2 = subscribe(Bo1, 1), subscribe(Bo2, 2)
r = Bo1.get(B + "/api/me/sessions")
j = r.json() if r.ok else {}
ss = j.get("sessions", [])
check(r.ok and len(ss) == 2 and sum(1 for s in ss if s["current"]) == 1 and ss[0]["current"], "two logins: two sessions, the current one first " + r.text[:300])
hashes = [x["token_hash"] for x in DB.execute("SELECT token_hash FROM sessions WHERE user_id=?", (uid["bob"],)).fetchall()]
check(not any(h in r.text for h in hashes) and Bo1.cookies.get("kalmido_session", "x") not in r.text and "token_hash" not in r.text,
      "no token hash and no cookie value in the answer")
cur = next((s for s in ss if s["current"]), {})
oth = next((s for s in ss if not s["current"]), {})
check(cur.get("browser") == "Firefox" and cur.get("system") == "Linux" and cur.get("device") == "computer", f"User-Agent read: {cur}")
check(oth.get("browser") == "Safari" and oth.get("system") == "iOS" and oth.get("device") == "phone", f"the phone: {oth}")
check(all(s["via"] == "password" and s["created_at"] and s["expires_at"] and s["last_seen_at"] for s in ss), "via, times")
check(len(cur.get("sid", "")) == 16 and cur["sid"] != oth.get("sid"), "a short public id per session")
row = lambda: DB.execute("SELECT last_seen_at, user_agent FROM sessions WHERE user_id=? ORDER BY created_at", (uid["bob"],)).fetchall()  # noqa: E731
before = [x["last_seen_at"] for x in row()]
for _ in range(5):
    Bo1.get(B + "/api/state")
    Bo2.get(B + "/api/me/sessions")
check([x["last_seen_at"] for x in row()] == before and all(before), "last activity is not written on every request")
check(sorted(x["user_agent"] for x in row()) == sorted([UA_FF, UA_IOS]), "the User-Agent is stored (shortened), no address")
subs = {x["id"]: x["session_hash"] for x in DB.execute("SELECT id, session_hash FROM push_subs WHERE user_id=?", (uid["bob"],)).fetchall()}
check(subs.get(sub1) and subs.get(sub2) and subs[sub1] != subs[sub2] and set(subs.values()) <= set(hashes), "push subscriptions know their session")

# ---- end one
C = sess("carol", ua=UA_FF)
csid = C.get(B + "/api/me/sessions").json()["sessions"][0]["sid"]
check(Bo1.delete(B + f"/api/me/sessions/{csid}").status_code == 404 and C.get(B + "/api/state").ok, "someone else's session id: 404, it lives on")
check(Bo1.delete(B + "/api/me/sessions/0123456789abcdef").status_code == 404, "an unknown id: 404")
check(requests.delete(B + f"/api/me/sessions/{oth['sid']}").status_code in (401, 403), "without a session: no")
r = Bo1.delete(B + f"/api/me/sessions/{oth['sid']}")
check(r.ok and r.json().get("current") is False, "end the other session " + r.text[:200])
check(Bo2.get(B + "/api/state").status_code == 401, "its cookie is 401 at once")
left = [x["id"] for x in DB.execute("SELECT id FROM push_subs WHERE user_id=?", (uid["bob"],)).fetchall()]
check(sub2 not in left and sub1 in left, f"its push subscription went, the other stays: {left}")

# ---- everywhere else
Bo3, Bo4 = sess("bob", ua=UA_FF), sess("bob", ua=UA_FF)
r = Bo1.post(B + "/api/me/sessions/others")
check(r.ok and r.json().get("ended") == 2, "log out everywhere else: 2 ended " + r.text[:200])
check(Bo3.get(B + "/api/state").status_code == 401 and Bo4.get(B + "/api/state").status_code == 401 and Bo1.get(B + "/api/state").ok,
      "only the current session stays")
check(len(Bo1.get(B + "/api/me/sessions").json()["sessions"]) == 1, "the list shows one")
check(C.get(B + "/api/state").ok, "other people's sessions are untouched")
check(Bo1.post(B + "/api/me/sessions/others", headers={"X-Requested-With": ""}).status_code == 403, "CSRF header needed")

# ---- the current one = log out
Bo5 = sess("bob", ua=UA_FF)
s5 = subscribe(Bo5, 5)
me5 = next(s for s in Bo5.get(B + "/api/me/sessions").json()["sessions"] if s["current"])
r = Bo5.delete(B + f"/api/me/sessions/{me5['sid']}")
check(r.ok and r.json().get("current") is True and "kalmido_session=" in r.headers.get("Set-Cookie", ""), "ending the current session clears the cookie")
check(Bo5.get(B + "/api/state").status_code == 401 and not DB.execute("SELECT 1 FROM push_subs WHERE id=?", (s5,)).fetchone(),
      "logged out, its push subscription gone")
Bo6 = sess("bob", ua=UA_FF)
s6 = subscribe(Bo6, 6)
check(Bo6.post(B + "/api/auth/logout").ok and not DB.execute("SELECT 1 FROM push_subs WHERE id=?", (s6,)).fetchone()
      and DB.execute("SELECT 1 FROM push_subs WHERE id=?", (sub1,)).fetchone(), "the logout removes only its own session's subscription")

# ---- agent tokens are no sessions
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
check(requests.get(B + "/api/me/sessions", headers=AGH).status_code in (401, 403), "an agent token: no session list")
check(requests.get(B + "/api/v1/me", headers=AGH).ok, "the agent token still works")

# ---- freelancer-matrix: own -- a person without an organisation: the same
FID, Fr1 = freelancer(B, A)
Fr2 = sess("frida", ua=UA_FF)
r = Fr1.get(B + "/api/me/sessions")
check(r.ok and len(r.json()["sessions"]) == 2, "freelancer: the own sessions " + r.text[:200])
r = Fr1.post(B + "/api/me/sessions/others")
check(r.ok and r.json()["ended"] == 1 and Fr2.get(B + "/api/state").status_code == 401 and Fr1.get(B + "/api/state").ok, "freelancer: everywhere else")
me_f = Fr1.get(B + "/api/me/sessions").json()["sessions"][0]
check(Fr1.delete(B + f"/api/me/sessions/{me_f['sid']}").ok and Fr1.get(B + "/api/state").status_code == 401, "freelancer: log out this one")

# ================================================================ organisation invitations (tenant-matrix: org)
Bo = sess("bob", ua=UA_FF)
Fk = sess("frank", ua=UA_FF)
r = Bo.get(B + f"/api/orgs/{ORG}/invites")
check(r.ok and r.json() == {"invites": [], "enabled": True}, "an organisation admin: no open invitations yet " + r.text[:200])
check(C.get(B + f"/api/orgs/{ORG}/invites").status_code == 403, "a plain member: 403")
check(C.post(B + f"/api/orgs/{ORG}/invites", json={"email": "x1@example.com"}).status_code == 403, "a plain member cannot invite")
check(Fk.post(B + f"/api/orgs/{ORG}/invites", json={"email": "x2@example.com"}).status_code == 404, "the admin of another organisation: 404")
check(requests.post(B + f"/api/orgs/{ORG}/invites", headers=AGH, json={"email": "x3@example.com"}).status_code in (401, 403), "an agent token: no")
check(Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "not-an-address"}).status_code == 400, "a wrong address: 400")
check(Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "x4@example.com", "role": "owner"}).status_code == 400, "a wrong role: 400")
check(not DB.execute("SELECT 1 FROM users WHERE email LIKE 'x_@example.com'").fetchone(), "no account for refused requests")

r = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "Nina.New@example.com", "role": "admin"})
j = r.json() if r.ok else {}
inv = j.get("invitation") or {}
# 2.115.0 review (M2): once mailed, the link is only in the mail, not in the admin's answer. 2.148.1 (#2480): the answer of an
# organisation admin is the same for every address (no "invited", no "user_id", no invitation details)
check(r.ok and set(j) == {"ok", "by_email", "invites"} and "#invite/" not in r.text,
      "a new address: account + invitation, mailed, the same answer as for any address " + r.text[:300])


def uid_of(mail):
    row = DB.execute("SELECT id FROM users WHERE lower(email)=lower(?)", (mail,)).fetchone()
    return row[0] if row else None


NU = uid_of("Nina.New@example.com")
u = DB.execute("SELECT username, password_hash, email, disabled FROM users WHERE id=?", (NU,)).fetchone()
check(u and u["username"] == "nina.new" and not u["password_hash"] and u["email"] == "Nina.New@example.com" and not u["disabled"],
      f"the account: user name from the address, no password: {dict(u) if u else None}")
m = DB.execute("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (ORG, NU)).fetchone()
check(m and m["role"] == "admin", "member of the organisation in the chosen role")
check(not DB.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (ORG2, NU)).fetchone(), "not in the other organisation")
ml = until(lambda: [x for x in mails() if any(a.lower() == "nina.new@example.com" for a in x["to"])], 10)  # "to" is a list
msg = email.message_from_string(ml[0]["raw"]) if ml else None
txt = "".join(p.get_payload(decode=True).decode() for p in msg.walk() if p.get_content_type() == "text/plain") if msg else ""
LINK_RE = re.compile(r"https://kalmido\.example/#invite/[A-Za-z0-9_-]+")
mlink = LINK_RE.search(txt)
check(mlink, f"the invitation mail with the link ({len(ml)} mail(s))")
inv["link"] = mlink.group(0) if mlink else ""
r = Bo.get(B + f"/api/orgs/{ORG}/invites")
iv = r.json()["invites"] if r.ok else []
check(len(iv) == 1 and iv[0]["user_id"] == NU and iv[0]["role"] == "admin" and iv[0]["state"] == "invited", f"the open invitation is listed: {iv}")
check(Fk.get(B + f"/api/orgs/{ORG}/invites").status_code == 404, "another organisation's admin does not see it")
r = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "nina.new@example.com", "role": "admin"})
check(r.ok and set(r.json()) == {"ok", "by_email", "invites"}, "the address again (it has an account now): the same answer " + r.text[:200])  # 2.148.1 (#2480)
r = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "carol@example.com"})
check(r.ok and set(r.json()) == {"ok", "by_email", "invites"} and "invitation" not in r.text, "an address with an account: the same answer, no invitation link")  # 2.148.1 (#2480)
check(DB.execute("SELECT COUNT(*) FROM users WHERE lower(email)='carol@example.com'").fetchone()[0] == 1, "no second account")

# ---- resend: a new link, the old one stops working
old_tok = inv["link"].split("#invite/")[1]
check(Fk.post(B + f"/api/orgs/{ORG}/invites/{NU}/resend").status_code == 404 and C.post(B + f"/api/orgs/{ORG}/invites/{NU}/resend").status_code == 403,
      "resend: other organisation 404, member 403")
n_mails = len(mails())
r = Bo.post(B + f"/api/orgs/{ORG}/invites/{NU}/resend")
check(r.ok and "#invite/" not in r.text, "resend: mailed, no link in the answer")
ml2 = until(lambda: mails()[n_mails:] if len(mails()) > n_mails else [], 10)
txt2 = "".join(p.get_payload(decode=True).decode() for p in email.message_from_string(ml2[-1]["raw"]).walk()
               if p.get_content_type() == "text/plain") if ml2 else ""
m2 = LINK_RE.search(txt2)
new_link = m2.group(0) if m2 else ""
check(r.ok and new_link and new_link != inv["link"], "resend: a new link")
check(s0.post(B + "/api/auth/invite/check", json={"token": old_tok}).status_code == 404, "the old link stops working")

# ---- accept: password, signed in, in the organisation
N1 = requests.Session()
N1.headers.update(H)
r = N1.post(B + "/api/auth/invite/accept", json={"token": new_link.split("#invite/")[1], "password": "password123"})
check(r.ok and r.json().get("ok"), "accepting sets the password and signs in " + r.text[:200])
st = N1.get(B + "/api/state").json() if r.ok else {}
check(any(w.get("id") == ORG for w in (st.get("me") or {}).get("workspaces", [])), "the new person is in the organisation")
check(Bo.delete(B + f"/api/orgs/{ORG}/invites/{NU}").status_code == 404, "withdraw after the first sign-in: 404 (the account stays)")
check(Bo.get(B + f"/api/orgs/{ORG}/invites").json()["invites"] == [], "no longer an open invitation")

# ---- withdraw: only this organisation's never used account
r = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "otto@example.com"})
OU = uid_of("otto@example.com") if r.ok else None  # 2.148.1 (#2480): the answer carries no user id
r = Fk.post(B + f"/api/orgs/{ORG2}/invites", json={"email": "petra@example.com"})
PU = uid_of("petra@example.com") if r.ok else None
check(OU and PU, "two more invitations (two organisations)")
check(Bo.delete(B + f"/api/orgs/{ORG}/invites/{PU}").status_code == 404 and DB.execute("SELECT 1 FROM users WHERE id=?", (PU,)).fetchone(),
      "withdrawing another organisation's invitation: 404, the account stays")
check(C.delete(B + f"/api/orgs/{ORG}/invites/{OU}").status_code == 403, "a plain member cannot withdraw")
r = Bo.delete(B + f"/api/orgs/{ORG}/invites/{OU}")
check(r.ok and r.json().get("email") == "otto@example.com" and r.json().get("role") == "member", "withdraw: the address + role for the undo")
check(not DB.execute("SELECT 1 FROM users WHERE id=?", (OU,)).fetchone(), "the never used account is deleted")
check(DB.execute("SELECT 1 FROM users WHERE id=?", (uid["frank"],)).fetchone() and DB.execute("SELECT 1 FROM users WHERE id=?", (NU,)).fetchone(),
      "nobody else is deleted")
r = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "otto@example.com"})
check(r.ok and uid_of("otto@example.com"), "the undo: the same address invited again")  # 2.148.1 (#2480)
r = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "rita@example.com"})
RU = uid_of("rita@example.com") if r.ok else None
check(RU and Bo.delete(B + f"/api/orgs/{ORG}/members/{RU}").ok, "an invited person removed from the organisation")
check(Bo.delete(B + f"/api/orgs/{ORG}/invites/{RU}").status_code == 404 and DB.execute("SELECT 1 FROM users WHERE id=?", (RU,)).fetchone()
      and not any(v["user_id"] == RU for v in Bo.get(B + f"/api/orgs/{ORG}/invites").json()["invites"]),
      "no longer a member: no withdraw (the account stays), not listed")

# ---- the daily limit
n_today = DB.execute("SELECT COUNT(*) FROM org_invites WHERE created_by=?", (uid["bob"],)).fetchone()[0]
NOW = DB.execute("SELECT max(created_at) FROM org_invites").fetchone()[0]  # the server's clock (it may be shifted in tests)
for i in range(20 - n_today):
    DB.execute("INSERT INTO users(username,display_name,created_at) VALUES(?,?,?)", (f"fill{i}", "Fill", "2026-01-01T00:00:00+00:00"))
    fu = DB.execute("SELECT id FROM users WHERE username=?", (f"fill{i}",)).fetchone()[0]
    DB.execute("INSERT INTO org_invites(user_id,org_id,role,created_by,created_at) VALUES(?,?,?,?,?)",
               (fu, ORG, "member", uid["bob"], NOW))
r = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "limit@example.com"})
check(r.status_code == 429 and not DB.execute("SELECT 1 FROM users WHERE email='limit@example.com'").fetchone(), "20 a day: then 429 " + r.text[:200])
check(Fk.post(B + f"/api/orgs/{ORG2}/invites", json={"email": "limit2@example.com"}).ok, "the limit is per inviting person")

# ---- the server admin switches it off
r = A.patch(B + "/api/admin/settings", json={"org_invites": False})
check(r.ok and r.json().get("org_invites") is False, "switch off " + r.text[:200])
check(Fk.post(B + f"/api/orgs/{ORG2}/invites", json={"email": "off@example.com"}).status_code == 403, "off: 403")
check(Fk.get(B + f"/api/orgs/{ORG2}/invites").json() == {"invites": [], "enabled": False}, "off: the client hides it")
check(Fk.put(B + f"/api/orgs/{ORG2}/members", json={"email": "bob@example.com"}).ok, "off: adding an existing account still works")
check(A.patch(B + "/api/admin/settings", json={"org_invites": "yes"}).status_code == 400, "a wrong value: 400")
A.patch(B + "/api/admin/settings", json={"org_invites": True})

print(f"\np2115_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
