#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.536.0 (#4363): a support session counts as "no session" for the OIDC sign-in. Own container (hosted, a server key, a fake
OIDC provider inside: stub_oidc.py). Invented accounts only; the client is a person without an organisation (tests/freelancer_fixture.py).
 - GET /api/auth/oidc/start from a support session: 403 code support_session (the guard's GET block), no authorization redirect
 - the callback with a support session cookie (a state from another browser, its binding cookie): refused (#login-error=support),
   nothing linked to the client's account, the support session stays the only session (no unmarked one in its place)
 - the person's own session is unchanged: start + callback link the provider identity (hosted: only from the own session)
usage: p2536_c_support_oidc_test.py <datadir>"""
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import urllib.parse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import kt
from kt import B, CT, DATA, check, sess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer, login  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
ISS = "http://127.0.0.1:9990"
KEY = base64.b64encode(os.urandom(32)).decode()

kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_HOSTED": "1", "KALMIDO_OIDC_ISSUER": ISS, "KALMIDO_OIDC_CLIENT_ID": "kalmido-test",
              "KALMIDO_OIDC_CLIENT_SECRET": "s3cret:/x+y", "KALMIDO_OIDC_BUTTON_LABEL": "TestID", "KALMIDO_OIDC_ALLOW_HOSTS": "127.0.0.1:9990"})
od = os.path.join(DATA, "oidc")
shutil.rmtree(od, ignore_errors=True)
os.makedirs(os.path.join(od, "signing"))
open(os.path.join(od, "signing", "k1.pem"), "wb").write(rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
json.dump({}, open(os.path.join(od, "codes.json"), "w"))
shutil.copy(os.path.join(N, "stub_oidc.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_oidc.py"])


def query(loc):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(loc).query))


def give_code(q, claims):
    p = os.path.join(od, "codes.json")
    codes = json.load(open(p))
    code = secrets.token_urlsafe(16)
    codes[code] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "claims": claims, "mode": "ok", "userinfo": None, "kid": None}
    json.dump(codes, open(p, "w"))
    return code


def start(s):
    """-> (status, the authorization query or {})."""
    r = s.get(B + "/api/auth/oidc/start", allow_redirects=False)
    loc = r.headers.get("Location", "")
    return r, (query(loc) if r.status_code == 302 and loc.startswith(ISS + "/authorize?") else {})


assert kt.sess(None).post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})
A = sess("alice")
ok = kt.until(lambda: kt.sess(None).get(B + "/api/auth/oidc/start", allow_redirects=False).status_code == 302, 20)
r = kt.sess(None).get(B + "/api/auth/oidc/start", allow_redirects=False)
assert ok, f"the fake provider answers ({r.status_code} {r.headers.get('Location', '')[:80]} {r.text[:200]})"
FID, _Fr = freelancer(B, A)
Fr = login(B, "frida")
assert Fr.patch(B + "/api/settings", json={"lang": "en", "tour": "done"}).ok
assert Fr.post(B + "/api/support-access", json={"hours": 1}).ok
r = A.post(B + f"/api/users/{FID}/signin-link")
assert r.ok, r.text
X = kt.sess(None)
r = X.post(B + "/api/auth/link", json={"token": r.json()["link"].split("#signin/")[1]})
assert r.ok, r.text
check(kt.dbx("SELECT COUNT(*) FROM sessions WHERE user_id=? AND via='support'", (FID,)) == [(1,)], "the operator's session is a support session")
CLAIMS = {"sub": "sub-frida", "preferred_username": "frida", "email": "frida@example.com"}

# ---- the start: refused for the support session
r, q = start(X)
check(r.status_code == 403 and (r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}).get("code") == "support_session"
      and not q, f"#4363: support session: the OIDC start is refused ({r.status_code} {r.headers.get('Location', '')[:60]})")

# ---- the callback: a state from another browser, carried over with its binding cookie, is refused for the support session
Y = kt.sess(None)
r, q = start(Y)
check(bool(q) and Y.cookies.get("kalmido_oidc"), f"another browser starts the sign-in ({r.status_code})")
X.cookies.set("kalmido_oidc", Y.cookies.get("kalmido_oidc"), path="/api/auth/oidc")
r = X.get(B + "/api/auth/oidc/callback", params={"code": give_code(q, CLAIMS), "state": q.get("state", "")}, allow_redirects=False)
check(r.status_code == 303 and "login-error=support" in r.headers.get("Location", ""), f"#4363: the callback with the support cookie is refused ({r.status_code} {r.headers.get('Location')})")
check(kt.dbx("SELECT oidc_subject FROM users WHERE id=?", (FID,)) == [(None,)], "#4363: nothing linked to the client's account")
check(kt.dbx("SELECT COUNT(*) FROM sessions WHERE user_id=? AND via='oidc'", (FID,)) == [(0,)], "#4363: no OIDC session in the support session's place")
check(kt.dbx("SELECT COUNT(*) FROM sessions WHERE user_id=? AND via='support'", (FID,)) == [(1,)] and X.get(B + "/api/me").ok,
      "#4363: the support session stays as it was")

# ---- the person's own session: unchanged (links the provider identity, a new session via oidc)
r, q = start(Fr)
check(bool(q), f"own session: the OIDC start redirects to the provider ({r.status_code})")
r = Fr.get(B + "/api/auth/oidc/callback", params={"code": give_code(q, CLAIMS), "state": q.get("state", "")}, allow_redirects=False)
check(r.status_code == 303 and r.headers.get("Location") == "/", f"own session: the callback signs in ({r.status_code} {r.headers.get('Location')})")
check(kt.dbx("SELECT oidc_subject FROM users WHERE id=?", (FID,)) == [(f"{ISS}|sub-frida",)], "own session: the provider identity is linked")
check(kt.dbx("SELECT COUNT(*) FROM sessions WHERE user_id=? AND via='oidc'", (FID,)) == [(1,)] and Fr.get(B + "/api/me").ok,
      "own session: a new session via oidc")

sys.exit(kt.done("p2536_c_support_oidc"))
