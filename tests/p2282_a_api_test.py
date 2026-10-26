#!/usr/bin/env python3
"""2.282.0 (#3111): sign-ins behind one shared address (office NAT): the address counter delays instead of refusing.
 - 21 wrong logins with 10 names from one address: all 401, never 429
 - afterwards a right password of another name from there: 200, after the delay (KALMIDO_LOGIN_SLOW_S)
 - a name that signed in from this address before: 200 without the delay
 - the pair name + address (5 failures of the same name) still refuses with 429
 - parallel delayed requests of one address above the cap: 429 with Retry-After (no thread exhaustion)
 - the second factor after a right password and a password change of a signed-in person: not 429, not delayed there
 - a person without an organisation signs in from the delayed address too
 - CalDAV/CardDAV: 30+ wrong app passwords of several accounts from one address do not lock another account there
   (207); the pair stays locked after 10
freelancer-matrix: n/a (area auth)
usage: p2282_a_api_test.py <datadir>      (a fresh container)"""
import base64
import hashlib
import hmac
import os
import struct
import subprocess
import sys
import threading
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import check, done  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

SLOW = 2.0  # this suite's delay: long enough to tell "delayed" from "not delayed" by the clock
NAT = "203.0.113.80"


def login(user, pw, ip, s=None):
    t0 = time.monotonic()
    r = (s or requests).post(B + "/api/auth/login", json={"username": user, "password": pw}, headers={**H, "X-Forwarded-For": ip})
    return r, time.monotonic() - t0


def sess_at(user, ip, pw="password123"):
    s = requests.Session()
    s.headers.update({**H, "X-Forwarded-For": ip})
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dav(user, pw, ip):
    return requests.request("PROPFIND", B + "/dav/", auth=(user, pw), headers={"Depth": "0", "X-Forwarded-Proto": "https",
                                                                                "X-Forwarded-For": ip}).status_code


def totp(secret):
    key = base64.b32decode(secret.replace(" ", "") + "=" * (-len(secret.replace(" ", "")) % 8))
    mac = hmac.new(key, struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest()
    o = mac[-1] & 15
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env=dict(os.environ, KALMIDO_LOGIN_SLOW_S=str(SLOW)))
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess_at("alice", "192.0.2.1")
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
for u in ["kim", "u30", "tess", "pat", "dora", "dan", "dex"] + [f"w{i}" for i in range(10)]:
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
FR_ID, FR = freelancer(B, A, "frida")

# kim and tess signed in from the office address before (known there); tess enrols TOTP from there
K = sess_at("kim", NAT)
T = sess_at("tess", NAT)
r = T.post(B + "/api/me/2fa/totp", json={"password": "password123"})
assert r.ok, r.text
SEC = r.json()["secret"]
assert T.post(B + "/api/me/2fa/totp/confirm", json={"code": totp(SEC)}).ok
P = sess_at("pat", NAT)  # signed in before the failures: changes the password afterwards

# ---- 21 wrong logins with 10 names from one address
codes = [login(f"w{i % 10}", "wrong-pass", NAT)[0].status_code for i in range(21)]
check(codes == [401] * 21, f"#3111: 21 wrong logins with 10 names from one address: all 401, never 429 {codes}")

# ---- a right password of another name: delayed, not refused
r, dt = login("u30", "password123", NAT)
check(r.status_code == 200, f"#3111: u30 with the right password from that address signs in ({r.status_code} {r.text[:80]})")
check(dt >= SLOW, f"#3111: ... after the delay ({dt:.2f} s >= {SLOW})")
r, dt = login("w5", "wrong-pass", NAT)  # not u30: its sign-in just made it known there
check(r.status_code == 401 and dt >= SLOW, f"#3111: a wrong password takes the same delay ({r.status_code}, {dt:.2f} s)")
r, dt = login("u30", "password123", NAT)
check(r.status_code == 200 and dt < SLOW * 0.75, f"#3111: u30 is known there after its sign-in: no delay any more ({dt:.2f} s)")
r, dt = login("nobody-here", "wrong-pass", NAT)
check(r.status_code == 401 and dt >= SLOW, f"#3111: an unknown name too ({r.status_code}, {dt:.2f} s)")
r, dt = login("frida", "password123", NAT)
check(r.status_code == 200, f"#3111: a person without an organisation signs in from there ({r.status_code})")

# ---- a known name: no delay
r, dt = login("kim", "password123", NAT)
check(r.status_code == 200 and dt < SLOW * 0.75, f"#3111: kim (signed in from there before) without the delay ({r.status_code}, {dt:.2f} s)")
r, dt = login("kim", "password123", "198.51.100.30")
check(r.status_code == 200 and dt < SLOW * 0.75, f"#3111: another address is not delayed at all ({dt:.2f} s)")

# ---- the second factor after the right password (tess is known there) and a password change of a signed-in person
s = requests.Session()
s.headers.update({**H, "X-Forwarded-For": NAT})
r = s.post(B + "/api/auth/login", json={"username": "tess", "password": "password123"})
check(r.ok and r.json().get("twofa"), f"#3111: tess: right password -> the second step ({r.status_code} {r.text[:80]})")
t0 = time.monotonic()
r = s.post(B + "/api/auth/2fa", json={"code": totp(SEC)})
check(r.status_code in (200, 401) and r.status_code != 429, f"#3111: the 2FA step after other names' failures: not 429 ({r.status_code})")
check(time.monotonic() - t0 < SLOW * 0.75, "#3111: ... and not delayed for a known name")
r = P.patch(B + "/api/me", json={"current_password": "password123", "password": "password456"})
check(r.ok, f"#3111: pat changes the password from that address (no 429) ({r.status_code} {r.text[:80]})")

# ---- the pair still refuses
for _ in range(5):
    login("dora", "wrong-pass", NAT)
r, _ = login("dora", "password123", NAT)
check(r.status_code == 429, f"#3111: 5 failures of dora from that address: dora refused there (pair) ({r.status_code})")
r, _ = login("dora", "password123", "198.51.100.31")
check(r.status_code == 200, "#3111: dora signs in from another address")

# ---- parallel delayed requests of one address: at most 2 wait, the rest gets 429 + Retry-After at once
out = []
go = threading.Barrier(5)


def one(i):
    go.wait()
    r, dt = login(f"crowd{i}", "wrong-pass", NAT)
    out.append((r.status_code, dt, r.headers.get("Retry-After")))


th = [threading.Thread(target=one, args=(i,)) for i in range(5)]
for t in th:
    t.start()
for t in th:
    t.join()
busy = [o for o in out if o[0] == 429]
check(len(busy) >= 1 and all(o[2] and o[1] < SLOW for o in busy), f"#3111: 5 parallel delayed requests: the ones above the cap get 429 + Retry-After at once {out}")
check(sum(o[0] == 401 for o in out) >= 1 and sum(o[0] == 401 for o in out) <= 2, f"#3111: ... at most 2 per address are checked {out}")
r, dt = login("dex", "password123", NAT)
check(r.status_code == 200, f"#3111: once they are done the address signs in again ({r.status_code})")

# ---- CalDAV/CardDAV per account + address
PW = {}
for u in ("w0", "w1", "w2", "w3", "dan"):
    PW[u] = sess_at(u, "192.0.2.9").post(B + "/api/me/app-passwords", json={"name": "Phone"}).json()["password"]
DAVIP = "203.0.113.90"
n = sum(dav(u, "wrong-app-password", DAVIP) == 401 for u in ("w0", "w1", "w2", "w3") for _ in range(8))
check(n == 32, f"#3111: 32 wrong app passwords of 4 accounts from one address: all 401 ({n})")
check(dav("dan", PW["dan"], DAVIP) == 207, "#3111: another account still syncs from that address (no address lock)")
for _ in range(2):
    dav("w0", "wrong-app-password", DAVIP)
check(dav("w0", PW["w0"], DAVIP) == 429, "#3111: w0 (10 failures there) stays locked at that address (pair)")
check(dav("w0", PW["w0"], "198.51.100.90") == 207, "#3111: w0 syncs from another address")

subprocess.run(["docker", "rm", "-f", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)
sys.exit(done("p2282_a_api"))
