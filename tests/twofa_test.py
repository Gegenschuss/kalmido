#!/usr/bin/env python3
"""Two-factor authentication for the built-in login (package A): TOTP enrolment (password needed, QR code made on the
server, secret stored encrypted), login with a code (ticket cookie, no session before the second step, replayed codes
refused), recovery codes (hashed at rest, one-time), disable (password + code), rate limits (wrong codes count like
wrong passwords, ticket dies after 5 tries), no user enumeration, session fixation, the admin policy "Require 2FA"
(enrolment at the next login, proxy logins unaffected, last factor protected, admin reset); passkeys (WebAuthn) with a
software authenticator written here (ES256, attestation "none", CBOR by hand): registration (origin / challenge /
RP ID checked), second factor, passwordless login (user verification + user handle required), sign counter (a cloned
authenticator is refused), rename / remove, the admin switch; proxy-only accounts cannot enrol.
Runs against a fresh test container (start.sh). usage: twofa_test.py <datadir>"""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import struct
import subprocess
import sys
import time
import urllib.parse

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
BP = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PROXY_PORT", "3041")
H = {"X-Requested-With": "kalmido"}
ORIGIN, RP = "https://kalmido.example", "kalmido.example"  # PUBLIC_URL of the test container
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok and r.json().get("ok"), (user, r.text)
    return s


def totp(secret, step=None):
    key = base64.b32decode(secret.replace(" ", "") + "=" * (-len(secret.replace(" ", "")) % 8))
    st = int(time.time() // 30) if step is None else step
    mac = hmac.new(key, struct.pack(">Q", st), hashlib.sha1).digest()
    o = mac[-1] & 15
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def now_step():
    return int(time.time() // 30)


# ---- minimal CBOR encoder (maps, ints, byte / text strings) for the software authenticator
def _head(major, n):
    if n < 24:
        return bytes([major << 5 | n])
    for ai, fmt in ((24, ">B"), (25, ">H"), (26, ">I"), (27, ">Q")):
        if n < 1 << (8 * struct.calcsize(fmt)):
            return bytes([major << 5 | ai]) + struct.pack(fmt, n)


def cbor(v):
    if isinstance(v, bool):
        return b"\xf5" if v else b"\xf4"
    if isinstance(v, int):
        return _head(0, v) if v >= 0 else _head(1, -1 - v)
    if isinstance(v, bytes):
        return _head(2, len(v)) + v
    if isinstance(v, str):
        e = v.encode()
        return _head(3, len(e)) + e
    if isinstance(v, dict):
        return _head(5, len(v)) + b"".join(cbor(k) + cbor(x) for k, x in v.items())
    raise TypeError(v)


class Authenticator:
    """A software passkey (ES256). count = the signature counter it reports."""
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(32)
        self.count = 0
        self.handle = None

    def cose(self):
        n = self.key.public_key().public_numbers()
        return cbor({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def register(self, opts, origin=ORIGIN, rp=RP, flags=0x45, chal=None):
        self.handle = opts["user"]["id"]
        cd = json.dumps({"type": "webauthn.create", "challenge": chal or opts["challenge"], "origin": origin, "crossOrigin": False}).encode()
        auth = hashlib.sha256(rp.encode()).digest() + bytes([flags]) + struct.pack(">I", 0) + b"\0" * 16 \
            + struct.pack(">H", len(self.cred_id)) + self.cred_id + self.cose()
        att = cbor({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key", "authenticatorAttachment": "platform",
                "response": {"clientDataJSON": b64u(cd), "attestationObject": b64u(att), "transports": ["internal", "hybrid", "bogus"]},
                "clientExtensionResults": {"credProps": {"rk": True}}}

    def assert_(self, opts, origin=ORIGIN, rp=RP, uv=True, handle=True, count=None, key=None):
        self.count = self.count + 1 if count is None else count
        cd = json.dumps({"type": "webauthn.get", "challenge": opts["challenge"], "origin": origin, "crossOrigin": False}).encode()
        auth = hashlib.sha256(rp.encode()).digest() + bytes([0x05 if uv else 0x01]) + struct.pack(">I", self.count)
        sig = (key or self.key).sign(auth + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(cd), "authenticatorData": b64u(auth), "signature": b64u(sig),
                             "userHandle": (self.handle if handle is True else handle) if handle else None},
                "clientExtensionResults": {}}


def login(user, pw="password123", s=None):
    s = s or requests.Session()
    s.headers.update(H)
    return s, s.post(B + "/api/auth/login", json={"username": user, "password": pw})


def enrol_totp(s, pw="password123"):
    r = s.post(B + "/api/me/2fa/totp", json={"password": pw})
    assert r.ok, r.text
    j = r.json()
    sec = j["secret"].replace(" ", "")
    r = s.post(B + "/api/me/2fa/totp/confirm", json={"code": totp(sec)})
    assert r.ok, r.text
    return sec, r.json()


# ------------------------------------------------------------------ setup
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
for u in ("bob", "dave", "erin", "fred", "gwen"):
    assert A.post(B + "/api/users", json={"username": u, "password": "password123"}).ok
assert A.post(B + "/api/users", json={"username": "carol", "proxy_login": "carol-sso"}).ok
IDS = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}
Bo = sess("bob")
C = requests.Session()
C.headers.update({**H, "Remote-User": "carol-sso"})

# ---- state + proxy-only accounts
j = Bo.get(B + "/api/me/2fa").json()
check(j["available"] and not j["totp"] and j["passkeys"] == [] and j["recovery_left"] == 0 and j["rp_id"] == RP, f"initial state: {j}")
j = C.get(BP + "/api/me/2fa").json()
check(j["available"] is False and j["via"] == "proxy", f"proxy-only account: not available: {j}")
check(C.post(BP + "/api/me/2fa/totp", json={"password": ""}).status_code == 409, "proxy-only account cannot enrol TOTP")
check(C.post(BP + "/api/me/passkeys/options", json={"password": ""}).status_code == 409, "proxy-only account cannot add a passkey")

# ---- TOTP enrolment
check(Bo.post(B + "/api/me/2fa/totp", json={}).status_code == 403, "enrolment without the password -> 403")
check(Bo.post(B + "/api/me/2fa/totp", json={"password": "wrong-password"}).status_code == 403, "enrolment with a wrong password -> 403")
check(requests.post(B + "/api/me/2fa/totp", json={"password": "password123"}, cookies=Bo.cookies).status_code == 403, "without the CSRF header -> 403")
r = Bo.post(B + "/api/me/2fa/totp", json={"password": "password123"})
t = r.json()
sec = t["secret"].replace(" ", "")
check(r.ok and len(sec) == 32 and t["qr"].startswith("data:image/svg+xml") and t["uri"].startswith("otpauth://totp/Kalmido:bob?secret=" + sec)
      and "issuer=Kalmido" in t["uri"], f"enrolment: secret, otpauth URI, QR as SVG data URI: {t['uri']}")
check("<svg" in base64.b64decode(t["qr"].split(",", 1)[1]).decode() if ";base64," in t["qr"] else "svg" in urllib.parse.unquote(t["qr"]),
      "QR code is an SVG made on the server")
check(not Bo.get(B + "/api/me/2fa").json()["totp"], "not active before the first code")
check(Bo.post(B + "/api/me/2fa/totp/confirm", json={"code": "000000" if totp(sec) != "000000" else "111111"}).status_code == 400, "wrong first code -> 400")
st0 = now_step()
r = Bo.post(B + "/api/me/2fa/totp/confirm", json={"code": totp(sec, st0)})
codes = r.json().get("recovery_codes") or []
check(r.ok and r.json()["totp"] and len(codes) == 10 and len(set(codes)) == 10 and r.json()["recovery_left"] == 10,
      f"TOTP on + 10 recovery codes: {r.text[:200]}")
row = dbx("SELECT totp_secret FROM users WHERE username='bob'")[0][0]
check(row.startswith("v1.") and sec not in row, "TOTP secret stored encrypted")
hashes_ = [x[0] for x in dbx("SELECT code_hash FROM recovery_codes WHERE user_id=?", (IDS["bob"],))]
check(len(hashes_) == 10 and all(len(h) == 64 for h in hashes_) and not any(c.replace("-", "") in json.dumps(hashes_) for c in codes),
      "recovery codes stored as SHA-256 only")
check(Bo.post(B + "/api/me/2fa/totp", json={"password": "password123"}).status_code == 409, "second enrolment -> 409")
check(A.get(B + "/api/users").json()["users"][IDS["bob"] - 1]["twofa"] == ["totp", "recovery"], "admin list shows 2FA")

# ---- login with the code
s, r = login("bob")
check(r.ok and r.json() == {"ok": False, "twofa": True, "methods": ["totp", "recovery"]} and "kalmido_session" not in r.cookies
      and "kalmido_2fa" in r.cookies, f"password ok -> second step, no session yet: {r.text}")
check("HttpOnly" in r.headers.get("Set-Cookie", "") and "SameSite=Strict" in r.headers.get("Set-Cookie", "") and "Path=/api/auth" in r.headers.get("Set-Cookie", ""),
      f"ticket cookie: HttpOnly, SameSite=Strict, path /api/auth: {r.headers.get('Set-Cookie')}")
check(s.get(B + "/api/state").status_code == 401, "the ticket is not a session")
check(s.post(B + "/api/auth/2fa", json={"code": totp(sec, st0)}).status_code == 401, "the code used at the enrolment cannot be replayed")
r = s.post(B + "/api/auth/2fa", json={"code": totp(sec, now_step() + 1)})
check(r.ok and r.json()["ok"] and "kalmido_session" in r.cookies, f"login with the next code: {r.text[:120]}")
check(s.get(B + "/api/me").json()["via"] == "2fa", "session marked as a two-factor login")
used = now_step() + 1
s2, _ = login("bob")
check(s2.post(B + "/api/auth/2fa", json={"code": totp(sec, used)}).status_code == 401, "a used code is refused in the next login too (replay)")
check(requests.post(B + "/api/auth/2fa", json={"code": totp(sec)}, headers=H).status_code == 401, "second step without a ticket -> 401")

# ---- recovery code
r = s2.post(B + "/api/auth/2fa", json={"recovery": codes[0].upper().replace("-", " ")})
check(r.ok and r.json()["recovery_left"] == 9, f"login with a recovery code (case / separator ignored): {r.text[:120]}")
s3, _ = login("bob")
check(s3.post(B + "/api/auth/2fa", json={"recovery": codes[0]}).status_code == 401, "a recovery code works only once")
check(s3.post(B + "/api/auth/2fa", json={"recovery": codes[1]}).ok, "another recovery code works")

# ---- no user enumeration: wrong password looks the same with or without 2FA / unknown user
a = login("bob", "wrong-password")[1]
b_ = login("nobody-here", "wrong-password")[1]
c_ = login("gwen", "wrong-password")[1]
check(a.status_code == b_.status_code == c_.status_code == 401 and a.json() == b_.json() == c_.json(), "wrong password: same answer for 2FA / no 2FA / unknown")

# ---- rate limits: the ticket dies after 5 wrong codes, and they count against the user name
s4, _ = login("bob")
for i in range(5):
    rr = s4.post(B + "/api/auth/2fa", json={"code": "12345" + str(i) if totp(sec) != "12345" + str(i) else "999999"})
rr = s4.post(B + "/api/auth/2fa", json={"code": totp(sec, now_step() + 1)})
check(rr.status_code in (401, 429) and rr.status_code != 200, f"ticket gone after 5 wrong codes ({rr.status_code})")
check(login("bob")[1].status_code == 429, "5 wrong codes lock the user name like 5 wrong passwords (429)")

# ---- session fixation: a login never keeps the token the browser brought
s5 = requests.Session()
s5.headers.update(H)
s5.cookies.set("kalmido_session", "attacker-chosen-token")
r = s5.post(B + "/api/auth/login", json={"username": "gwen", "password": "password123"})
tok1 = r.cookies.get("kalmido_session")
check(r.ok and tok1 and tok1 != "attacker-chosen-token", "login issues a new token")
s5.cookies.clear()
s5.cookies.set("kalmido_session", tok1)
r = s5.post(B + "/api/auth/login", json={"username": "gwen", "password": "password123"})
tok2 = r.cookies.get("kalmido_session")
check(tok2 != tok1 and requests.get(B + "/api/me", cookies={"kalmido_session": tok1}).status_code == 401, "a new login ends the previous session of this browser")

# ---- disable TOTP (dave: own user, so bob's lock does not interfere)
D = sess("dave")
D2 = sess("dave")  # another device of dave
dsec, dj = enrol_totp(D)
check(D2.get(B + "/api/state").status_code == 401 and D.get(B + "/api/state").ok, "turning on the first factor ends the other sessions, keeps this one")
dcodes = dj["recovery_codes"]
check(D.post(B + "/api/me/2fa/totp/disable", json={"password": "password123"}).status_code == 400, "disable without a code -> 400")
check(D.post(B + "/api/me/2fa/totp/disable", json={"password": "nope-nope", "code": totp(dsec)}).status_code == 403, "disable with a wrong password -> 403")
r = D.post(B + "/api/me/2fa/totp/disable", json={"password": "password123", "code": dcodes[0]})
check(r.ok and not r.json()["totp"] and r.json()["recovery_left"] == 0, "disabled with password + recovery code; codes gone")
check(login("dave")[1].json().get("ok") is True, "login without a second step again")

# ---- passkeys: registration. Restart first (same data): the failure counters above are in memory and 20 failures
# per IP within 15 minutes would block this client from here on.
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True, env=dict(os.environ, KEEP="1"))
assert r.returncode == 0, r.stdout + r.stderr
E = sess("erin")
k = Authenticator()
check(E.post(B + "/api/me/passkeys/options", json={"password": "bad-password"}).status_code == 403, "passkey options need the password")
o = E.post(B + "/api/me/passkeys/options", json={"password": "password123"}).json()
check(o["rp"]["id"] == RP and o["rp"]["name"] == "Kalmido" and o["user"]["name"] == "erin" and len(b64u_dec(o["user"]["id"])) == 32
      and o["attestation"] == "none" and o["authenticatorSelection"]["residentKey"] == "preferred", f"registration options: {o['rp']}, {o['user']}")
check(E.post(B + "/api/me/passkeys", json={"credential": k.register(o, origin="https://evil.example")}).status_code == 400, "wrong origin refused")
o = E.post(B + "/api/me/passkeys/options", json={"password": "password123"}).json()
check(E.post(B + "/api/me/passkeys", json={"credential": k.register(o, chal=b64u(os.urandom(32)))}).status_code == 400, "wrong challenge refused")
o = E.post(B + "/api/me/passkeys/options", json={"password": "password123"}).json()
check(E.post(B + "/api/me/passkeys", json={"credential": k.register(o, rp="evil.example")}).status_code == 400, "wrong RP ID hash refused")
o = E.post(B + "/api/me/passkeys/options", json={"password": "password123"}).json()
r = E.post(B + "/api/me/passkeys", json={"credential": k.register(o), "name": "Laptop <b>"})
j = r.json()
check(r.ok and len(j["passkeys"]) == 1 and j["passkeys"][0]["name"] == "Laptop <b>" and j["passkeys"][0]["discoverable"] == 1
      and len(j.get("recovery_codes") or []) == 10, f"passkey registered (+ recovery codes): {r.text[:200]}")
row = dbx("SELECT transports, rp_id, sign_count FROM webauthn_creds")[0]
check(row == ("internal,hybrid", RP, 0), f"stored: known transports only, RP ID, counter: {row}")
check(E.post(B + "/api/me/passkeys", json={"credential": k.register(o)}).status_code == 409, "challenge is one-time")
o = E.post(B + "/api/me/passkeys/options", json={"password": "password123"}).json()
check([c["id"] for c in o["excludeCredentials"]] == [b64u(k.cred_id)], "registered passkeys are excluded from a new registration")
check(E.post(B + "/api/me/passkeys", json={"credential": k.register(o)}).status_code == 400, "the same passkey twice -> 400")

# ---- passkey as second factor
s, r = login("erin")
check(r.json().get("twofa") and r.json()["methods"] == ["passkey", "recovery"], f"second step offers the passkey: {r.text}")
o = s.post(B + "/api/auth/2fa/passkey/options").json()
check([c["id"] for c in o["allowCredentials"]] == [b64u(k.cred_id)] and o["rpId"] == RP, "assertion options list erin's passkey")
other = Authenticator()
other.handle = k.handle
other.cred_id = k.cred_id
check(s.post(B + "/api/auth/2fa/passkey", json={"credential": other.assert_(o)}).status_code == 401, "signature of another key refused")
o = s.post(B + "/api/auth/2fa/passkey/options").json()
check(s.post(B + "/api/auth/2fa/passkey", json={"credential": k.assert_(o, origin="https://evil.example")}).status_code == 401, "wrong origin refused")
o = s.post(B + "/api/auth/2fa/passkey/options").json()
r = s.post(B + "/api/auth/2fa/passkey", json={"credential": k.assert_(o, uv=False)})
check(r.ok and r.json()["ok"] and s.get(B + "/api/state").ok, "login with the passkey as second factor (user presence is enough)")
check(dbx("SELECT sign_count FROM webauthn_creds")[0][0] == k.count, "sign counter stored")
s, _ = login("erin")
o = s.post(B + "/api/auth/2fa/passkey/options").json()
check(s.post(B + "/api/auth/2fa/passkey", json={"credential": k.assert_(o, count=k.count)}).status_code == 401, "same counter again (cloned authenticator) refused")
# a passkey of another user cannot be the second factor of erin
F = sess("fred")
kf = Authenticator()
o = F.post(B + "/api/me/passkeys/options", json={"password": "password123"}).json()
assert F.post(B + "/api/me/passkeys", json={"credential": kf.register(o)}).ok
s, _ = login("erin")
o = s.post(B + "/api/auth/2fa/passkey/options").json()
check(s.post(B + "/api/auth/2fa/passkey", json={"credential": kf.assert_(o)}).status_code == 401, "another user's passkey is not erin's second factor")

# ---- passwordless login
s = requests.Session()
s.headers.update(H)
o = s.post(B + "/api/auth/passkey/options", json={}).json()
check(o["userVerification"] == "required" and o.get("allowCredentials") in ([], None), f"passwordless options: UV required, no allow-list: {o}")
check(s.post(B + "/api/auth/passkey", json={"credential": k.assert_(o, uv=False)}).status_code == 401, "passwordless without user verification refused")
o = s.post(B + "/api/auth/passkey/options", json={}).json()
check(s.post(B + "/api/auth/passkey", json={"credential": k.assert_(o, handle=kf.handle)}).status_code == 401, "wrong user handle refused")
o = s.post(B + "/api/auth/passkey/options", json={}).json()
check(s.post(B + "/api/auth/passkey", json={"credential": k.assert_(o, handle=False)}).status_code == 401, "missing user handle refused")
o = s.post(B + "/api/auth/passkey/options", json={}).json()
r = s.post(B + "/api/auth/passkey", json={"credential": k.assert_(o)})
check(r.ok and s.get(B + "/api/me").json()["username"] == "erin" and s.get(B + "/api/me").json()["via"] == "passkey", f"passwordless login: {r.text[:100]}")
check(requests.post(B + "/api/auth/passkey", json={"credential": k.assert_(o)}, headers=H).status_code == 401, "assertion without the ticket cookie refused")
assert A.patch(B + "/api/admin/settings", json={"passkey_login": False}).ok
s = requests.Session()
s.headers.update(H)
check(s.post(B + "/api/auth/passkey/options", json={}).status_code == 403, "passwordless login off -> 403")
check(requests.get(B + "/api/auth/info").json()["passkey_login"] is False, "login screen hides the passkey button")
assert A.patch(B + "/api/admin/settings", json={"passkey_login": True}).ok
check(Bo.patch(B + "/api/admin/settings", json={"passkey_login": False}).status_code in (401, 403), "users cannot change the switch")

# ---- rename / remove
pid = E.get(B + "/api/me/2fa").json()["passkeys"][0]["id"]
check(F.patch(B + f"/api/me/passkeys/{pid}", json={"name": "mine now"}).status_code == 404, "another user's passkey cannot be renamed")
check(E.patch(B + f"/api/me/passkeys/{pid}", json={"name": "Phone"}).json()["passkeys"][0]["name"] == "Phone", "rename")
check(F.delete(B + f"/api/me/passkeys/{pid}", json={"password": "password123"}).status_code == 404, "another user's passkey cannot be removed")
check(E.delete(B + f"/api/me/passkeys/{pid}", json={}).status_code == 403, "removing needs the password")
r = E.delete(B + f"/api/me/passkeys/{pid}", json={"password": "password123"})
check(r.ok and r.json()["passkeys"] == [] and r.json()["recovery_left"] == 0, "removed; recovery codes gone with the last factor")

# ---- admin policy: require 2FA
check(Bo.patch(B + "/api/admin/settings", json={"twofa_required": True}).status_code in (401, 403), "user cannot turn the policy on")
r = A.patch(B + "/api/admin/settings", json={"twofa_required": True})
check(r.ok and r.json()["twofa_required"] is True, "policy on")
s, r = login("gwen")
check(r.json() == {"ok": False, "enrol": True, "methods": ["totp", "passkey"]} and "kalmido_session" not in r.cookies, f"no 2FA yet -> enrolment: {r.text}")
check(s.get(B + "/api/state").status_code == 401, "no session before the enrolment")
t = s.post(B + "/api/auth/enrol/totp").json()
gsec = t["secret"].replace(" ", "")
check(t["qr"].startswith("data:image/svg+xml"), "enrolment via the ticket: QR code")
check(s.post(B + "/api/auth/enrol/totp/confirm", json={"code": "000000" if totp(gsec) != "000000" else "111111"}).status_code == 401, "wrong code at the enrolment")
r = s.post(B + "/api/auth/enrol/totp/confirm", json={"code": totp(gsec)})
check(r.ok and len(r.json().get("recovery_codes") or []) == 10 and s.get(B + "/api/state").ok, "enrolled -> session + recovery codes")
check(requests.post(B + "/api/auth/enrol/totp", headers=H).status_code == 401, "enrolment endpoints need the ticket")
# enrolment with a passkey
kd = Authenticator()
s, r = login("dave")
check(r.json().get("enrol"), "dave (2FA turned off before) must enrol")
o = s.post(B + "/api/auth/enrol/passkey/options").json()
r = s.post(B + "/api/auth/enrol/passkey", json={"credential": kd.register(o), "name": "Key"})
check(r.ok and s.get(B + "/api/state").ok and len(r.json()["recovery_codes"]) == 10, "enrolment with a passkey")
# the last factor is protected while the policy is on
sess_g, r = login("gwen")
r = sess_g.post(B + "/api/auth/2fa", json={"code": totp(gsec, now_step() + 1)})
check(r.ok, "gwen logs in with her code")
r = sess_g.post(B + "/api/me/2fa/recovery", json={"password": "password123"})
gcodes = r.json()["recovery_codes"]
r = sess_g.post(B + "/api/me/2fa/totp/disable", json={"password": "password123", "code": gcodes[0]})
check(r.status_code == 409, f"policy on: the last factor cannot be removed ({r.status_code})")
# proxy logins are not affected
check(C.get(BP + "/api/me").ok and C.get(BP + "/api/state").ok, "proxy login unaffected by the policy")
# admin reset
r = A.patch(B + f"/api/users/{IDS['gwen']}", json={"reset_2fa": True})
check(r.ok and r.json()["twofa"] == [], "admin reset clears TOTP, passkeys, recovery codes")
check(sess_g.get(B + "/api/state").status_code == 401, "admin reset ends the user's sessions")
check(login("gwen")[1].json().get("enrol"), "after the reset (policy on): enrol again")
assert A.patch(B + "/api/admin/settings", json={"twofa_required": False}).ok
check(login("gwen")[1].json().get("ok") is True, "policy off: password alone again")

# ---- secrets never logged
logs = subprocess.run(["docker", "logs", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True, text=True)
blob = logs.stdout + logs.stderr
check(sec not in blob and gsec not in blob and not any(c in blob for c in codes + gcodes) and "password123" not in blob,
      "TOTP secrets, recovery codes and passwords never logged")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
