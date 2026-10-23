#!/usr/bin/env python3
"""2.190.0 API tests, part A (#1991 #2496 #2561): sessions and sign-in, own container (start.sh). Invented names only,
addresses @example.com.
 - #1991: every way a session ends takes the push subscriptions made in it along: the own password change from session Y
   (the subscription of session X goes, the one of Y stays), the admin disables the account, the admin sets a password,
   a reset link; the daily clean-up removes subscriptions of sessions that are gone ('' = unknown session stays)
 - #2496: a reset link and the admin setting a password revoke the app passwords; API tokens stay
 - #2496: in-memory sign-in tickets: one address keeps at most PEND_PER_IP, its own oldest give way, others stay
 - #2496: WebAuthn takes a localhost page origin only when PUBLIC_URL itself is localhost (here: kalmido.example)
 - #2496: a sign-in link for another account while someone is signed in asks first (the link stays unused), then signs in
 - #2561: the sign-in log tags a name with an HMAC (the plain SHA-256 is not in the log)
 - a person without an organisation (freelancer-matrix: account): the own password change ends the other session with its
   subscription, a sign-in link asks the same way
usage: p2190_a_sessions_test.py <datadir>      (a fresh container; P2190A_NOSTART=1 = the server already runs)"""
import base64
import hashlib
import os
import re
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
FAILS, OKS = [], [0]


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


def b64u(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


SUBN = [0]


def subscribe(s):
    SUBN[0] += 1
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,
                                                                            serialization.PublicFormat.UncompressedPoint)
    r = s.post(B + "/api/push/subs", json={"endpoint": f"{STUB}/push/a{SUBN[0]}", "keys": {"p256dh": b64u(pub), "auth": b64u(os.urandom(16))},
                                          "label": f"device {SUBN[0]}"})
    assert r.ok, r.text
    return r.json()["id"]


def has_sub(sid):
    return bool(DB.execute("SELECT 1 FROM push_subs WHERE id=?", (sid,)).fetchone())


def box(code):
    """Python inside the app container (a fresh process)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code
                          + "\nc.commit()\nc.close()"], capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def apppw(uid, name):
    DB.execute("INSERT INTO app_passwords(user_id,name,pw_hash,created_at) VALUES(?,?,?,?)", (uid, name, "x", "2026-01-01T00:00:00+00:00"))


def apppws(uid):
    return DB.execute("SELECT COUNT(*) FROM app_passwords WHERE user_id=?", (uid,)).fetchone()[0]


def link_token(admin, uid):
    r = admin.post(B + f"/api/users/{uid}/signin-link", json={})
    assert r.ok, r.text
    return r.json()["link"].rsplit("/", 1)[1]


if not os.environ.get("P2190A_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_WEBPUSH_HOSTS={STUB}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(1)
DB = dbx.connect(DATA)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]

# ================================================================== #1991: the own password change from session Y
Bx, By = sess("bob"), sess("bob")
sx, sy = subscribe(Bx), subscribe(By)
r = By.patch(B + "/api/me", json={"password": "password456", "current_password": "password123"})
check(r.ok, "own password change " + r.text[:200])
check(Bx.get(B + "/api/state").status_code == 401 and By.get(B + "/api/state").ok, "the other session ends, this one stays")
check(not has_sub(sx) and has_sub(sy), "#1991: the subscription of the ended session goes, the own one stays")

# ================================================================== #1991: the admin disables the account
Cx = sess("carol")
sc = subscribe(Cx)
r = A.patch(B + f"/api/users/{uid['carol']}", json={"disabled": True})
check(r.ok and Cx.get(B + "/api/state").status_code == 401 and not has_sub(sc), "#1991: disabled: sessions and subscriptions gone " + r.text[:200])
A.patch(B + f"/api/users/{uid['carol']}", json={"disabled": False})

# ================================================================== #1991 + #2496: the admin sets a password
Dx = sess("dave")
sd = subscribe(Dx)
apppw(uid["dave"], "phone")
r = A.patch(B + f"/api/users/{uid['dave']}", json={"password": "password789"})
check(r.ok and Dx.get(B + "/api/state").status_code == 401 and not has_sub(sd), "#1991: admin password: sessions and subscriptions gone " + r.text[:200])
check(apppws(uid["dave"]) == 0, "#2496: admin password: the app passwords are revoked (behaviour change)")
Cx = sess("carol")
apppw(uid["carol"], "calendar")
r = A.patch(B + f"/api/users/{uid['carol']}", json={"display_name": "Carol C"})
check(r.ok and apppws(uid["carol"]) == 1 and Cx.get(B + "/api/state").ok, "other changes by the admin keep sessions and app passwords")

# ================================================================== #1991 + #2496: a reset link
sc = subscribe(Cx)
TOK = "r2190a" + "x" * 30
DB.execute("DELETE FROM user_invites WHERE user_id=?", (uid["carol"],))
DB.execute("INSERT INTO user_invites(user_id,token_hash,kind,created_at,expires_at) VALUES(?,?,?,?,?)",
           (uid["carol"], hashlib.sha256(TOK.encode()).hexdigest(), "reset", "2026-01-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00"))
R = requests.Session()
R.headers.update(H)
r = R.post(B + "/api/auth/invite/accept", json={"token": TOK, "password": "password321"})
check(r.ok and r.json().get("ok"), "reset link accepted " + r.text[:200])
check(Cx.get(B + "/api/state").status_code == 401 and not has_sub(sc), "#1991: reset link: the old sessions and their subscriptions go")
check(apppws(uid["carol"]) == 0, "#2496: reset link: the app passwords are revoked (behaviour change)")
check(R.get(B + "/api/state").ok, "the reset link signs in")

# ================================================================== #1991: the daily clean-up
E1 = sess("erin")
se = subscribe(E1)
DB.execute("INSERT INTO push_subs(user_id,endpoint,p256dh,auth,session_hash,created_at) VALUES(?,?,?,?,?,?)",
           (uid["erin"], f"{STUB}/push/orphan", "x", "x", "0" * 64, "2026-01-01T00:00:00+00:00"))
DB.execute("INSERT INTO push_subs(user_id,endpoint,p256dh,auth,session_hash,created_at) VALUES(?,?,?,?,?,?)",
           (uid["erin"], f"{STUB}/push/old", "x", "x", "", "2026-01-01T00:00:00+00:00"))
out = box("from kalmido.admin.dataretention import lgc_tick\nprint('ran', lgc_tick(c, True))")
left = {x["endpoint"] for x in DB.execute("SELECT endpoint FROM push_subs WHERE user_id=?", (uid["erin"],)).fetchall()}
check("ran" in out and f"{STUB}/push/orphan" not in left and f"{STUB}/push/old" in left and has_sub(se),
      f"#1991: clean-up: a subscription of a gone session goes, '' and live ones stay {left} {out[-300:]}")

# ================================================================== #2496: tickets per address
out = box("from kalmido.core.config import app as fa\nfrom kalmido.accounts import login as L\n"
          "with fa.test_request_context('/', environ_base={'REMOTE_ADDR': '198.51.100.7'}):\n"
          "    for _ in range(L.PEND_PER_IP + 10):\n        L.pend_new('pk', None, chal='x')\n"
          "with fa.test_request_context('/', environ_base={'REMOTE_ADDR': '198.51.100.8'}):\n    L.pend_new('pk', None, chal='y')\n"
          "ips = [v.get('_ip') for v in L._PEND.values()]\nprint('per-ip', ips.count('198.51.100.7'), ips.count('198.51.100.8'), L.PEND_PER_IP)\n"
          "d = {'a': {'exp': 1, '_ip': 'x'}, 'b': {'exp': 2, '_ip': 'x'}, 'c': {'exp': 0, '_ip': 'y'}}\nL.pend_ip_cap(d, 'x', 2)\n"
          "print('cap', sorted(d))")
m = re.search(r"per-ip (\d+) (\d+) (\d+)", out)
check(m and m.group(1) == m.group(3) and m.group(2) == "1", "#2496: one address keeps at most PEND_PER_IP tickets, another one is untouched " + out[-300:])
check("cap ['b', 'c']" in out, "#2496: the address's own oldest gives way " + out[-200:])

# ================================================================== #2496: WebAuthn origin
Bo = By
for origin in ("http://localhost:9", "http://evil.localhost"):
    r = Bo.post(B + "/api/me/passkeys/options", json={"password": "password456"}, headers={"Origin": origin})
    rp = ((r.json() if r.ok else {}).get("rp") or {}).get("id")
    check(r.status_code == 403 or rp == "kalmido.example", f"#2496: {origin} is no passkey origin with PUBLIC_URL kalmido.example: {r.status_code} {rp}")

# ================================================================== #2496: a sign-in link with someone signed in
tok = link_token(A, uid["erin"])
Cz = sess("carol", "password321")
r = Cz.post(B + "/api/auth/link", json={"token": tok})
j = r.json() if r.ok else {}
check(j.get("switch") is True and j.get("name") == "Erin" and not j.get("ok"), "#2496: another account signed in: the page asks first " + r.text[:200])
check(not DB.execute("SELECT used_at FROM user_invites WHERE user_id=?", (uid["erin"],)).fetchone()["used_at"] and Cz.get(B + "/api/state").ok,
      "#2496: asking leaves the link unused and the session as it was")
r = Cz.post(B + "/api/auth/link", json={"token": tok, "switch": True})
check(r.ok and r.json().get("ok") and Cz.get(B + "/api/state").json()["me"]["id"] == uid["erin"], "#2496: confirmed: signed in as the link's account " + r.text[:200])
tok = link_token(A, uid["erin"])
r = Cz.post(B + "/api/auth/link", json={"token": tok})
check(r.ok and r.json().get("ok"), "the same account: no question " + r.text[:200])
tok = link_token(A, uid["erin"])
N0 = requests.Session()
N0.headers.update(H)
r = N0.post(B + "/api/auth/link", json={"token": tok})
check(r.ok and r.json().get("ok"), "nobody signed in: no question " + r.text[:200])

# ================================================================== #2561: the sign-in log
nb = len(subprocess.run(["docker", "logs", CT], capture_output=True, text=True).stdout)
s0.post(B + "/api/auth/login", json={"username": "Nobody2190", "password": "x"})
time.sleep(0.5)
lg = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
tail = (lg.stdout + lg.stderr)[max(0, nb - 2000):]
line = [x for x in tail.splitlines() if "login failed for" in x]
check(line and re.search(r"login failed for user#[0-9a-f]{8} ", line[-1]) and hashlib.sha256(b"nobody2190").hexdigest()[:8] not in tail
      and "Nobody2190" not in tail, f"#2561: the name tag is keyed {line[-1:]}")

# ================================================================== a person without an organisation
# freelancer-matrix: account
FID, F1 = freelancer(B, A)
F2 = sess("frida")
f1, f2 = subscribe(F1), subscribe(F2)
apppw(FID, "laptop")
r = F2.patch(B + "/api/me", json={"password": "password654", "current_password": "password123"})
check(r.ok and F1.get(B + "/api/state").status_code == 401 and F2.get(B + "/api/state").ok, "freelancer: own password change ends the other session")
check(not has_sub(f1) and has_sub(f2), "freelancer: the other session's subscription goes, the own one stays")
check(apppws(FID) == 1, "freelancer: the own password change keeps the app passwords (only reset / admin revoke)")
tok = link_token(A, uid["bob"])
r = F2.post(B + "/api/auth/link", json={"token": tok})
check(r.ok and r.json().get("switch") is True, "freelancer: a sign-in link of another account asks first " + r.text[:200])

print(f"\np2190_a_sessions: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
