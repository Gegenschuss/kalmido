#!/usr/bin/env python3
"""OIDC login (package A) against a fake provider inside the container (stub_oidc.py): the button on the login screen,
the SSRF guard (an internal issuer only once allow-listed), the authorization redirect (code + PKCE S256, state,
nonce, exact redirect URI, binding cookie), the code exchange (client_secret_basic with URL-encoded credentials,
code_verifier), ID token checks (signature via JWKS, key rotation, alg none / HS256 / wrong key / tampered payload,
iss, aud, azp, exp, nonce), state problems (unknown, other browser, replay, cancelled), userinfo, account linking
(subject, user name, verified e-mail only), "no account", disabled users, auto-create (admin switch), unlink, group
gating + admin group (second container), JWKS caching, secrets never in the log.
Starts its OWN test containers. usage: oidc_test.py <datadir>"""
import base64
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
ISS = "http://127.0.0.1:9990"
SECRET = "s3cret:/x+y"
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def pem(k):
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def start(extra=()):
    env = dict(os.environ, EXTRA=" ".join([f"-e KALMIDO_OIDC_ISSUER={ISS}", "-e KALMIDO_OIDC_CLIENT_ID=kalmido-test",
                                           f"-e KALMIDO_OIDC_CLIENT_SECRET={SECRET}", "-e KALMIDO_OIDC_BUTTON_LABEL=TestID", *extra]))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    od = os.path.join(DATA, "oidc")
    shutil.rmtree(od, ignore_errors=True)
    os.makedirs(os.path.join(od, "signing"))
    open(os.path.join(od, "signing", "k1.pem"), "wb").write(pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
    open(os.path.join(od, "evil.pem"), "wb").write(pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
    json.dump({}, open(os.path.join(od, "codes.json"), "w"))
    shutil.copy(os.path.join(N, "stub_oidc.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_oidc.py"])
    time.sleep(0.8)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        assert s.post(B + "/api/auth/login", json={"username": user, "password": pw}).ok
    return s


def oidc_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "oidc", "log.jsonl"))]
    except FileNotFoundError:
        return []


def begin(s):
    r = s.get(B + "/api/auth/oidc/start", allow_redirects=False)
    loc = r.headers.get("Location", "")
    return r, loc, dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(loc).query))


def give_code(q, claims, mode="ok", userinfo=None, kid=None):
    p = os.path.join(DATA, "oidc", "codes.json")
    codes = json.load(open(p))
    code = secrets.token_urlsafe(16)
    codes[code] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "claims": claims, "mode": mode, "userinfo": userinfo, "kid": kid}
    json.dump(codes, open(p, "w"))
    return code


def oidc_login(claims, mode="ok", userinfo=None, kid=None, s=None):
    """-> (session, callback response). A successful login redirects to '/', a refused one to '/#login-error=<code>'."""
    s = s or sess()
    r, loc, q = begin(s)
    assert r.status_code == 302 and loc.startswith(ISS + "/authorize?"), (r.status_code, loc, r.text[:200])
    code = give_code(q, claims, mode, userinfo, kid)
    r = s.get(B + "/api/auth/oidc/callback", params={"code": code, "state": q["state"]}, allow_redirects=False)
    return s, r


def err_of(r):
    loc = r.headers.get("Location", "")
    return loc.split("login-error=", 1)[1] if "login-error=" in loc else ("ok" if loc == "/" else loc)


# ------------------------------------------------------------------ container 1: provider not allow-listed at first
start()
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
for u, extra in (("frank", {}), ("gina", {"email": "Gina@Example.test"}), ("hank", {"email": "hank@example.test"}), ("ivy", {})):
    assert A.post(B + "/api/users", json={"username": u, **extra}).ok, u
IDS = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}
A.patch(B + f"/api/users/{IDS['ivy']}", json={"disabled": True})

info = requests.get(B + "/api/auth/info").json()
check(info["oidc"] == {"label": "TestID"} and "no_account" in info["login_errors"], f"login screen: button label + error texts: {info.get('oidc')}")
ab = A.get(B + "/api/about").json()["oidc"]
check(ab["configured"] and ab["issuer"] == ISS and ab["client_id"] == "kalmido-test" and ab["secret_set"] and SECRET not in json.dumps(ab)
      and ab["redirect_uri"] == "https://kalmido.example/api/auth/oidc/callback" and ab["username_claim"] == "preferred_username" and not ab["autocreate"],
      f"admin view (read-only, no secret): {ab}")
check(SECRET not in json.dumps(A.get(B + "/api/about").json()), "client secret never sent to the browser")

# ---- SSRF guard: 127.0.0.1 is internal -> refused until allow-listed
s = sess()
r = s.get(B + "/api/auth/oidc/start", allow_redirects=False)
check(r.status_code == 303 and err_of(r) == "failed", f"internal issuer without the allow-list: refused ({r.status_code} {r.headers.get('Location')})")
check("allowed internal host" in A.get(B + "/api/about").json()["oidc"]["error"], f"admin sees why: {A.get(B + '/api/about').json()['oidc']['error']}")
check(not [x for x in oidc_log() if x["path"] != "/nothing"], "the provider was never contacted")
assert A.patch(B + "/api/admin/settings", json={"cal_allow_hosts": "127.0.0.1:9990"}).ok

# ---- the authorization redirect
s = sess()
r, loc, q = begin(s)
sc = r.headers.get("Set-Cookie", "")
check(r.status_code == 302 and q.get("response_type") == "code" and q.get("client_id") == "kalmido-test" and q.get("scope") == "openid profile email"
      and q.get("redirect_uri") == "https://kalmido.example/api/auth/oidc/callback" and q.get("code_challenge_method") == "S256"
      and len(q.get("state", "")) >= 40 and len(q.get("nonce", "")) >= 40 and len(q.get("code_challenge", "")) == 43, f"authorization request: {q}")
check("kalmido_oidc=" in sc and "HttpOnly" in sc and "Path=/api/auth/oidc" in sc and "SameSite=Lax" in sc, f"binding cookie: {sc}")
code = give_code(q, {"sub": "sub-frank", "preferred_username": "frank"})
r = s.get(B + "/api/auth/oidc/callback", params={"code": code, "state": q["state"]}, allow_redirects=False)
check(r.status_code == 303 and r.headers["Location"] == "/" and "kalmido_session" in r.cookies, f"login ok -> '/', session cookie: {r.headers.get('Location')}")
me = s.get(B + "/api/me").json()
check(me.get("username") == "frank" and me.get("via") == "oidc", f"logged in as the pre-created user frank via OIDC: {me}")
check(dbx("SELECT oidc_subject FROM users WHERE username='frank'")[0][0] == ISS + "|sub-frank", "linked: issuer|sub stored")
tok = [x for x in oidc_log() if x["path"] == "/token"][-1]
cid, csec = base64.b64decode(tok["auth"][6:]).decode().split(":", 1)
check(tok["auth"].startswith("Basic ") and urllib.parse.unquote(csec) == SECRET and cid == "kalmido-test", "client_secret_basic, URL-encoded")
check(b64u(hashlib.sha256(tok["form"]["code_verifier"].encode()).digest()) == q["code_challenge"] and "client_secret" not in tok["form"],
      "PKCE: the verifier matches the challenge")
check(tok["form"]["redirect_uri"] == "https://kalmido.example/api/auth/oidc/callback", "exact redirect_uri at the token endpoint")
check(any(x["path"] == "/userinfo" and x["auth"].startswith("Bearer at-") for x in oidc_log()), "userinfo asked with the access token")
check(s.post(B + "/api/auth/logout").ok and s.get(B + "/api/me").status_code == 401, "logout ends the OIDC session")

# ---- the subject decides from now on (a changed user name claim still logs in frank)
s, r = oidc_login({"sub": "sub-frank", "preferred_username": "someone-else"})
check(err_of(r) == "ok" and s.get(B + "/api/me").json()["username"] == "frank", "linked subject wins over the user name claim")

# ---- no account / disabled / e-mail linking
s, r = oidc_login({"sub": "sub-ghost", "preferred_username": "ghost"})
check(err_of(r) == "no_account" and "kalmido_session" not in r.cookies and not dbx("SELECT 1 FROM users WHERE username='ghost'"), "unknown user -> no_account, nothing created")
s, r = oidc_login({"sub": "sub-gina", "preferred_username": "gina.x", "email": "gina@example.test", "email_verified": True})
check(err_of(r) == "ok" and s.get(B + "/api/me").json()["username"] == "gina", "linked by verified e-mail (case-insensitive)")
s, r = oidc_login({"sub": "sub-hank", "preferred_username": "hank.x", "email": "hank@example.test", "email_verified": False})
check(err_of(r) == "no_account", "unverified e-mail does not link")
s, r = oidc_login({"sub": "sub-hank2", "preferred_username": "hank.y", "email": "hank@example.test"})
check(err_of(r) == "no_account", "missing email_verified does not link")
s, r = oidc_login({"sub": "sub-ivy", "preferred_username": "ivy"})
check(err_of(r) == "disabled" and "kalmido_session" not in r.cookies, "disabled user -> disabled")
s, r = oidc_login({"sub": "sub-other", "preferred_username": "frank"})
check(err_of(r) == "no_account", "a second subject cannot take over an already linked user by name")

# ---- broken tokens
for mode in ("bad_sig", "wrong_aud", "aud_list_no_azp", "azp_bad", "expired", "no_exp", "wrong_nonce", "wrong_iss", "alg_none", "hs256", "tampered"):
    s, r = oidc_login({"sub": "sub-frank", "preferred_username": "frank"}, mode=mode)
    check(err_of(r) == "failed" and "kalmido_session" not in r.cookies and s.get(B + "/api/me").status_code == 401, f"{mode}: refused")
ab = A.get(B + "/api/about").json()["oidc"]
check("token" in ab["error"], f"admin sees the token problem: {ab['error']}")

# ---- state problems
s = sess()
r, loc, q = begin(s)
code = give_code(q, {"sub": "sub-frank", "preferred_username": "frank"})
r = s.get(B + "/api/auth/oidc/callback", params={"code": code, "state": "not-the-state"}, allow_redirects=False)
check(err_of(r) == "state", "unknown state -> state")
s = sess()
r, loc, q = begin(s)
code = give_code(q, {"sub": "sub-frank", "preferred_username": "frank"})
other = sess()
r = other.get(B + "/api/auth/oidc/callback", params={"code": code, "state": q["state"]}, allow_redirects=False)
check(err_of(r) == "state" and "kalmido_session" not in r.cookies, "callback in another browser (no binding cookie) -> state (login CSRF)")
r = s.get(B + "/api/auth/oidc/callback", params={"code": code, "state": q["state"]}, allow_redirects=False)
check(err_of(r) == "state", "the state is one-time: the first (failed) use consumed it")
s = sess()
r, loc, q = begin(s)
code = give_code(q, {"sub": "sub-frank", "preferred_username": "frank"})
r = s.get(B + "/api/auth/oidc/callback", params={"code": code, "state": q["state"]}, allow_redirects=False)
r2 = s.get(B + "/api/auth/oidc/callback", params={"code": code, "state": q["state"]}, allow_redirects=False)
check(err_of(r) == "ok" and err_of(r2) == "state", "replayed callback refused")
s = sess()
r, loc, q = begin(s)
r = s.get(B + "/api/auth/oidc/callback", params={"error": "access_denied", "state": q["state"]}, allow_redirects=False)
check(err_of(r) == "denied", "cancelled at the provider -> denied")

# ---- JWKS: cached, fetched again for an unknown key id (rotation)
n_jwks = len([x for x in oidc_log() if x["path"] == "/jwks"])
check(n_jwks == 1, f"JWKS fetched once for all logins so far: {n_jwks}")
time.sleep(11)  # an unknown key id fetches the JWKS again at most every 10 s
ek = ec.generate_private_key(ec.SECP256R1())
open(os.path.join(DATA, "oidc", "signing", "k2.pem"), "wb").write(pem(ek))
s, r = oidc_login({"sub": "sub-frank", "preferred_username": "frank"}, kid="k2")
check(err_of(r) == "ok" and len([x for x in oidc_log() if x["path"] == "/jwks"]) == 2, "new key id (ES256): JWKS fetched again, login ok")

# ---- userinfo: extra claims (same sub only)
A.patch(B + "/api/admin/settings", json={"oidc_autocreate": True})
s, r = oidc_login({"sub": "sub-jo", "preferred_username": "jo"}, userinfo={"sub": "sub-jo", "name": "Jo From Userinfo"})
check(err_of(r) == "ok" and s.get(B + "/api/me").json()["display_name"] == "Jo From Userinfo", "auto-create: display name from userinfo")
check(dbx("SELECT is_admin, password_hash FROM users WHERE username='jo'")[0] == (0, None), "created without admin rights and without a password")
s, r = oidc_login({"sub": "sub-kim", "preferred_username": "kim"}, userinfo={"sub": "sub-SOMEONE", "name": "Mallory"})
check(err_of(r) == "ok" and s.get(B + "/api/me").json()["display_name"] == "kim", "userinfo with another sub is ignored")
s, r = oidc_login({"sub": "sub-bad", "preferred_username": "Bad Name!"})
check(err_of(r) == "taken", "invalid user name claim -> taken (nothing created)")
s, r = oidc_login({"sub": "sub-frank-2", "preferred_username": "frank"})
check(err_of(r) == "taken", "auto-create never takes a user name that exists")
A.patch(B + "/api/admin/settings", json={"oidc_autocreate": False})
s, r = oidc_login({"sub": "sub-lu", "preferred_username": "lu"})
check(err_of(r) == "no_account", "auto-create off again -> no_account")

# ---- unlink
r = A.patch(B + f"/api/users/{IDS['frank']}", json={"oidc_unlink": True})
check(r.ok and r.json()["oidc_linked"] is False and dbx("SELECT oidc_subject FROM users WHERE username='frank'")[0][0] is None, "admin unlinks")
s, r = oidc_login({"sub": "sub-frank-new", "preferred_username": "frank"})
check(err_of(r) == "ok" and dbx("SELECT oidc_subject FROM users WHERE username='frank'")[0][0] == ISS + "|sub-frank-new", "next login links again")

# ---- rate limit on start (60 / 15 min / IP) + secrets not logged
logs = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
blob = logs.stdout + logs.stderr
codes = json.load(open(os.path.join(DATA, "oidc", "codes.json")))
check(SECRET not in blob and not any(c in blob or ("at-" + c) in blob for c in codes) and "eyJ" not in blob, "client secret, codes, tokens never logged")
s = sess()
n429 = 0
for _ in range(70):
    if s.get(B + "/api/auth/oidc/start", allow_redirects=False).status_code == 429:
        n429 += 1
check(n429 > 0, "OIDC start is rate-limited per IP")

# ------------------------------------------------------------------ container 2: groups, admin group, env allow-list
start(["-e KALMIDO_OIDC_ALLOW_HOSTS=127.0.0.1:9990", "-e KALMIDO_OIDC_REQUIRED_GROUP=kalmido", "-e KALMIDO_OIDC_ADMIN_GROUP=kalmido-admins",
       "-e KALMIDO_OIDC_SCOPES=openid,profile,email,groups"])
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
assert A.post(B + "/api/users", json={"username": "max"}).ok
s = sess()
r, loc, q = begin(s)
check(r.status_code == 302 and q["scope"] == "openid profile email groups", f"env allow-list works; scopes from the env: {q.get('scope')}")
s, r = oidc_login({"sub": "sub-max", "preferred_username": "max", "groups": ["other"]})
check(err_of(r) == "group" and "kalmido_session" not in r.cookies, "not in the required group -> group")
s, r = oidc_login({"sub": "sub-max", "preferred_username": "max"}, userinfo={"sub": "sub-max", "groups": ["kalmido"]})
check(err_of(r) == "ok" and s.get(B + "/api/me").json()["is_admin"] is False, "group from userinfo -> in, not admin")
s, r = oidc_login({"sub": "sub-max", "preferred_username": "max", "groups": ["kalmido", "kalmido-admins"]})
check(err_of(r) == "ok" and s.get(B + "/api/me").json()["is_admin"] is True, "admin group -> admin")
s, r = oidc_login({"sub": "sub-max", "preferred_username": "max", "groups": "kalmido"})
check(err_of(r) == "ok" and s.get(B + "/api/me").json()["is_admin"] is False, "left the admin group -> no longer admin (another admin exists)")
# 2.9.0 (#438): admins by verified e-mail domain, stored in the settings next to the environment's admin group
r = A.put(B + "/api/admin/oidc", json={"admin_domains": "corp.test"})
check(r.status_code == 200 and r.json()["admin_domains"] == "corp.test" and "admin_group" in r.json()["env"], "admin domain stored next to the env group")
s, r = oidc_login({"sub": "sub-max", "preferred_username": "max", "groups": ["kalmido"], "email": "max@corp.test", "email_verified": True})
check(err_of(r) == "ok" and s.get(B + "/api/me").json()["is_admin"] is True, "verified e-mail of an admin domain -> admin")
s, r = oidc_login({"sub": "sub-max", "preferred_username": "max", "groups": ["kalmido"], "email": "max@corp.test", "email_verified": False})
check(err_of(r) == "ok" and s.get(B + "/api/me").json()["is_admin"] is False, "unverified e-mail of an admin domain -> no admin")
# 2.9.0: an Entra-style login (user name with @, xms_edov instead of email_verified) creates "eva" when auto-create is on
A.patch(B + "/api/admin/settings", json={"oidc_autocreate": True})
s, r = oidc_login({"sub": "sub-eva", "preferred_username": "Eva@corp.test", "groups": ["kalmido"], "email": "eva@corp.test", "xms_edov": True})
me = s.get(B + "/api/me").json() if err_of(r) == "ok" else {}
check(me.get("username") == "eva" and me.get("is_admin") is True, f"Entra style: account eva from the verified e-mail, admin by domain ({me})")
s, r = oidc_login({"sub": "sub-max2", "preferred_username": "max@else.test", "groups": ["kalmido"], "email": "max@else.test", "email_verified": True})
check(err_of(r) == "taken", "the e-mail local part never links / reuses an existing account (max exists -> taken)")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
