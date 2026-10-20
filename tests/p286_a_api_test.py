#!/usr/bin/env python3
"""2.86.0 API tests, part A: sign-in and accounts (audit hardening). Invented names only.
 - N1 password reset: many requests for one address from many senders do not block the owner's own request
 - N2 the per-name login ceiling (many addresses) does not lock out a known address or a signed-in re-authentication;
   a new address stays refused
 - N3 a child account: POST /share 403, /drop does not take its token, /api/me shows no drop token
 - N4 a sign-in link: an account that became an admin after the link was made is refused (409); the 2FA policy asks to enrol
 - N5 the first local password of a single sign-on account: only right after a fresh sign-in; behind the proxy 403
 - N6 drop / iCal tokens: parked (hashing would make the shown links unrecoverable), nothing to test here
 - N7 POST /share refuses a foreign page (Sec-Fetch-Site cross-site / same-site, a foreign Origin); the log has no shared text
 - N8 an instance admin sees and looks after the kids of their own organisation (and orphans), not another organisation's
 - N9 /api/state kid_ids: only kids the person sees
usage: p286_a_api_test.py <datadir>      (a fresh container; P286A_NOSTART=1 = the server already runs)"""
import hashlib
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
PP = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PROXY_PORT", "3041")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
SMTP = (" -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none"
        " -e KALMIDO_MAIL_FROM=kalmido@example.test")


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123", ip=None):
    s = requests.Session()
    s.headers.update(H)
    if ip:
        s.headers["X-Forwarded-For"] = ip
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def login(user, pw, ip):
    return requests.post(B + "/api/auth/login", json={"username": user, "password": pw}, headers={**H, "X-Forwarded-For": ip})


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


if not os.environ.get("P286A_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + SMTP)  # mail out on (N1); nobody needs the mail itself
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=e)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
for u in ("bob", "carol", "dave", "gina"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
for u in ("olga", "pia"):  # single sign-on accounts without a local password
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "email": f"{u}@example.com"})
    assert r.ok, r.text
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}
dbx("UPDATE users SET password_hash=NULL WHERE id IN (?, ?)", (ids["olga"], ids["pia"]))
for kid, parent in (("kima", "bob"), ("kibe", "dave"), ("kior", "dave")):
    r = A.post(B + "/api/users", json={"username": kid, "display_name": kid.title(), "password": "password123", "kid": True,
                                       "parents": [ids[parent]]})
    assert r.ok, r.text
    ids[kid] = r.json()["id"]
dbx("DELETE FROM kid_parents WHERE kid_id=?", (ids["kior"],))  # an orphan: no organisation, nobody looks after it
ORG = dbx("INSERT INTO orgs(name, icon, domains, created_at) VALUES('Alpha', '', '', '2026-01-01T00:00:00+00:00') RETURNING id")[0][0]
ORG2 = dbx("INSERT INTO orgs(name, icon, domains, created_at) VALUES('Beta', '', '', '2026-01-01T00:00:00+00:00') RETURNING id")[0][0]
for u in ("alice", "bob", "carol", "kima"):
    dbx("INSERT INTO org_members(org_id, user_id, role) VALUES(?, ?, 'member')", (ORG, ids[u]))
for u in ("dave", "kibe"):
    dbx("INSERT INTO org_members(org_id, user_id, role) VALUES(?, ?, 'member')", (ORG2, ids[u]))

# ================================================================== N1 password reset per-address ceiling
for i in range(21):  # PW_LIMITS (3, 10, 20): 21 senders, one request each, all for bob
    requests.post(B + "/api/auth/forgot", headers={**H, "X-Forwarded-For": f"198.51.100.{10 + i}"}, json={"login": "bob@example.com"})
had = dbx("SELECT COUNT(*) FROM user_invites WHERE user_id=? AND kind='reset'", (ids["bob"],))[0][0]
check(had == 1, f"setup: the first request made a reset link ({had})")
dbx("DELETE FROM user_invites WHERE user_id=?", (ids["bob"],))  # past the 5-minute gap
requests.post(B + "/api/auth/forgot", headers={**H, "X-Forwarded-For": "203.0.113.77"}, json={"login": "bob@example.com"})
check(dbx("SELECT COUNT(*) FROM user_invites WHERE user_id=? AND kind='reset'", (ids["bob"],))[0][0] == 1,
      "N1: after many senders the owner's own request still gets a link")

# ================================================================== N2 per-name login ceiling
KNOWN = "198.51.100.200"
G = sess("gina", ip=KNOWN)  # gina logged in from here before
with ThreadPoolExecutor(8) as ex:  # 20 addresses x 5 wrong passwords = the ceiling of 100 for the name
    codes = list(ex.map(lambda i: login("gina", "wrong-password", f"192.0.2.{1 + i // 5}").status_code, range(100)))
check(codes.count(401) == 100, f"setup: 100 wrong passwords counted ({sorted(set(codes))})")
r = login("gina", "password123", "203.0.113.5")
check(r.status_code == 429, f"N2: a new address stays refused ({r.status_code})")
r = login("gina", "password123", KNOWN)
check(r.ok, f"N2: the known address still logs in ({r.status_code} {r.text[:120]})")
G.headers["X-Forwarded-For"] = "203.0.113.6"
r = G.patch(B + "/api/me", json={"password": "password456", "current_password": "password123"})
check(r.ok, f"N2: a signed-in re-authentication is not locked out ({r.status_code} {r.text[:120]})")

# ================================================================== N3 child accounts: /share, /drop, /api/me
K = sess("kima")
r = K.post(B + "/share", data={"title": "Kid share", "text": "hello"}, allow_redirects=False)
check(r.status_code == 403, f"N3: a child account cannot POST /share ({r.status_code})")
check(K.get(B + "/api/me").json().get("drop_token_set") is False, "N3: /api/me shows a kid no drop token")
# 2.138.0 (#1907): tokens are stored as SHA-256 hashes; give the kid one directly to see /drop refuses it
ktok = "kid-token-" + "k" * 24
dbx("UPDATE users SET drop_token_hash=? WHERE id=?", (hashlib.sha256(ktok.encode()).hexdigest(), ids["kima"]))
r = requests.post(B + "/drop", headers={"Authorization": "Bearer " + ktok}, data={"text": "Kid drop"})
check(r.status_code >= 400, f"N3: /drop does not take a kid's token ({r.status_code})")
check(not dbx("SELECT 1 FROM tasks WHERE title='Kid drop'"), "N3: no task from the kid's drop")
r = K.post(B + "/api/me/drop-token")
check(r.status_code == 403, f"N3 review: a child account cannot make a new upload token ({r.status_code})")
check(dbx("SELECT drop_token_hash FROM users WHERE id=?", (ids["kima"],))[0][0] == hashlib.sha256(ktok.encode()).hexdigest(), "N3 review: the kid's token stayed unchanged")
Bo = sess("bob")
btok = Bo.post(B + "/api/me/drop-token").json().get("drop_token")  # 2.138.0 (#1907): shown once, when created
r = requests.post(B + "/drop", headers={"Authorization": "Bearer " + btok}, data={"text": "Grown-up drop"})
check(r.ok, f"N3: an ordinary account still drops ({r.status_code})")

# ================================================================== N7 POST /share origin + log
for sfs, want in (("cross-site", 403), ("same-site", 403), ("none", 303), ("same-origin", 303)):
    r = A.post(B + "/share", data={"title": f"Share {sfs}", "text": "x"}, headers={"Sec-Fetch-Site": sfs}, allow_redirects=False)
    check(r.status_code == want, f"N7: Sec-Fetch-Site {sfs} -> {want} ({r.status_code})")
r = A.post(B + "/share", data={"title": "Share evil", "text": "x"}, headers={"Origin": "https://evil.example"}, allow_redirects=False)
check(r.status_code == 403, f"N7: a foreign Origin without Sec-Fetch-Site -> 403 ({r.status_code})")
r = A.post(B + "/share", data={"title": "Share own", "text": "x"}, headers={"Origin": B}, allow_redirects=False)
check(r.status_code == 303, f"N7: the own Origin -> 303 ({r.status_code})")
r = A.post(B + "/share", data={"title": "Zq7 private shared title", "text": "Zq7 private text"}, allow_redirects=False)
check(r.status_code == 303, f"setup: a plain share works ({r.status_code})")
time.sleep(0.5)
try:
    logs = subprocess.run(["docker", "logs", CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30).stdout
except (OSError, subprocess.SubprocessError):
    logs = ""
if "share POST" in logs:
    check("Zq7 private" not in logs, "N7: the log names no shared title / text")
else:
    print("note: container log not readable, N7 log case skipped", flush=True)

# ================================================================== N4 sign-in link
r = A.post(B + f"/api/users/{ids['bob']}/signin-link")
check(r.ok, f"setup: a sign-in link for bob {r.text[:120]}")
btok_l = r.json()["link"].split("#signin/")[1]
check(A.patch(B + f"/api/users/{ids['bob']}", json={"is_admin": True}).ok, "setup: bob becomes an admin")
r = requests.post(B + "/api/auth/link", headers=H, json={"token": btok_l})
check(r.status_code == 409, f"N4: the link of a now-admin is refused on use ({r.status_code})")
check(A.patch(B + f"/api/users/{ids['bob']}", json={"is_admin": False}).ok, "setup: bob is no admin again")
dbx("INSERT INTO settings(key, value) VALUES('twofa_required', '1') ON CONFLICT(key) DO UPDATE SET value='1'")
try:
    ctok = A.post(B + f"/api/users/{ids['carol']}/signin-link").json()["link"].split("#signin/")[1]
    r = requests.post(B + "/api/auth/link", headers=H, json={"token": ctok})
    check(r.ok and r.json().get("enrol") is True and not r.json().get("ok"),
          f"N4: with the 2FA policy the link asks to enrol first ({r.status_code} {r.text[:120]})")
    ptok = A.post(B + f"/api/users/{ids['pia']}/signin-link").json()["link"].split("#signin/")[1]
    r = requests.post(B + "/api/auth/link", headers=H, json={"token": ptok})
    check(r.ok and r.json().get("ok") is True, f"N4: an account without a password signs in as before ({r.status_code} {r.text[:120]})")
finally:
    dbx("DELETE FROM settings WHERE key='twofa_required'")

# ================================================================== N5 first local password of an SSO account
O = requests.Session()
O.headers.update(H)
otok = A.post(B + f"/api/users/{ids['olga']}/signin-link").json()["link"].split("#signin/")[1]
r = O.post(B + "/api/auth/link", json={"token": otok})
check(r.ok and r.json().get("ok"), f"setup: olga signs in with a link {r.text[:120]}")
dbx("UPDATE sessions SET created_at='2020-01-01T00:00:00+00:00' WHERE user_id=?", (ids["olga"],))
r = O.patch(B + "/api/me", json={"password": "olgapassword1"})
check(r.status_code == 403, f"N5: an older session cannot add a first password ({r.status_code})")
check(dbx("SELECT password_hash FROM users WHERE id=?", (ids["olga"],))[0][0] is None, "N5: no password stored")
dbx("UPDATE sessions SET created_at='2999-01-01T00:00:00+00:00' WHERE user_id=?", (ids["olga"],))
r = O.patch(B + "/api/me", json={"password": "olgapassword1"})
check(r.ok, f"N5: right after a fresh sign-in the first password works ({r.status_code} {r.text[:120]})")
check(dbx("SELECT password_hash FROM users WHERE id=?", (ids["olga"],))[0][0] is not None, "N5: the password is stored")
dbx("UPDATE users SET password_hash=NULL, proxy_login='pia-sso' WHERE id=?", (ids["pia"],))
try:
    r = requests.patch(PP + "/api/me", headers={**H, "Remote-User": "pia-sso"}, json={"password": "piapassword1"})
    check(r.status_code == 403, f"N5: behind the login proxy the first password is the admin's ({r.status_code})")
except requests.ConnectionError:
    print("note: proxy port not reachable, N5 proxy case skipped", flush=True)

# ================================================================== N8 + N9 kids of the own organisation
kids = {k["id"] for k in A.get(B + "/api/family/kids").json()["kids"]}
check(ids["kima"] in kids and ids["kior"] in kids, f"N8: the admin sees the own organisation's kid and the orphan {kids}")
check(ids["kibe"] not in kids, "N8: the admin does not see another organisation's kid")
check(A.post(B + f"/api/family/kids/{ids['kibe']}/stars", json={"delta": 1}).status_code == 404,
      "N8: the admin cannot give stars to another organisation's kid")
check(A.post(B + f"/api/family/kids/{ids['kima']}/stars", json={"delta": 1}).ok, "N8: the own organisation's kid: stars work")
D = sess("dave")
check(ids["kibe"] in {k["id"] for k in D.get(B + "/api/family/kids").json()["kids"]}, "N8: the parent still sees the kid")
kb = set(Bo.get(B + "/api/state").json().get("kid_ids") or [])
check(ids["kima"] in kb and ids["kibe"] not in kb and ids["kior"] not in kb, f"N9: bob's kid_ids only the visible kids {kb}")
ka = set(A.get(B + "/api/state").json().get("kid_ids") or [])
check(ids["kima"] in ka and ids["kior"] in ka and ids["kibe"] not in ka, f"N9: the admin's kid_ids {ka}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
