#!/usr/bin/env python3
"""2.5.2 (UX audit 2, K04): admin alerts never go to the PUBLIC ntfy.sh unless someone chose it.
Container 1: NTFY_URL=https://ntfy.sh with DNS switched off (--dns 127.0.0.9, so nothing can reach the real service; the
test aborts if ntfy.sh resolves), the fake push service inside (stub_webpush.py): a fresh admin on the default channel
Web Push without a device gets nothing (ntfy_public, the admin listed without topic / devices, the test alert 409 with a
readable reason, a real alert only "listed"); the channel ntfy = their own topic (chosen); Web Push with a device = the
alert arrives encrypted on that device and nowhere else; a member sees nothing. Container 2 (start.sh: an own ntfy server):
as before, the admins' own topics get the alerts whatever channel they use.
usage: p252_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time

import http_ece
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
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


def sess(user=None):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": "password123"})
        assert r.ok, (user, r.text)
    return s


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def lines(name):
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, name), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


class Browser:
    def __init__(self, path):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.endpoint = STUB + path
        self.pub = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

    def sub(self, label="Test browser"):
        return {"endpoint": self.endpoint, "keys": {"p256dh": b64u(self.pub), "auth": b64u(self.auth)}, "label": label}

    def got(self):
        out = []
        for x in lines("webpush.log"):
            if x["path"] == self.endpoint[len(STUB):]:
                out.append(json.loads(http_ece.decrypt(base64.b64decode(x["body"]), private_key=self.key,
                                                       auth_secret=self.auth, version="aes128gcm")))
        return out


def start(extra=(), webpush=False):
    env = dict(os.environ, KALMIDO_ADMIN_ALERTS="1",
               EXTRA=" ".join((["-e KALMIDO_WEBPUSH_HOSTS=" + STUB] if webpush else []) + list(extra)))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    if webpush:
        subprocess.run(["cp", os.path.join(N, "stub_webpush.py"), DATA])
        subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webpush.py"])
    time.sleep(0.7)


def wait_for(fn, n=40):
    for _ in range(n):
        x = fn()
        if x:
            return x
        time.sleep(0.25)
    return fn()


# ------------------------------------------------------------------ container 1: NTFY_URL = the public ntfy.sh, no DNS
start(["-e NTFY_URL=https://ntfy.sh", "--dns 127.0.0.9"], webpush=True)
env = subprocess.run(["docker", "exec", CT, "printenv", "NTFY_URL"], capture_output=True, text=True).stdout.strip()
res = subprocess.run(["docker", "exec", CT, "python", "-c", "import socket\ntry:\n socket.getaddrinfo('ntfy.sh', 443); print('RESOLVES')\nexcept OSError: print('blocked')"],
                     capture_output=True, text=True).stdout.strip()
if env != "https://ntfy.sh" or res != "blocked":  # never let a test reach the real public service
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    sys.exit(f"p252_api: unsafe test setup (NTFY_URL={env!r}, ntfy.sh {res}), stopped")
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
assert r.ok, r.text
Bo = sess("bob")
st = A.get(B + "/api/state").json()["settings"]
check(st.get("push_channel") == "webpush", f"a fresh admin is on the default channel Web Push: {st.get('push_channel')}")

j = A.get(B + "/api/admin/alerts").json()
check(j["on"] is True and j["ntfy_public"] is True and j["webpush"] is True, f"alerts on, ntfy.sh recognised as public: {j['on']} {j['ntfy_public']}")
check([{k: a[k] for k in ("username", "topic", "devices", "me")} for a in j["admins"]] == [{"username": "alice", "topic": "", "devices": 0, "me": True}],
      f"no device, no chosen ntfy: the admin is listed without a destination: {j['admins']}")
r = A.post(B + "/api/admin/alerts/test")
check(r.status_code == 409 and "Settings > Notifications" in r.json().get("error", ""), f"test alert: 409 with a readable reason: {r.status_code} {r.text[:160]}")
r = A.patch(B + "/api/admin/settings", json={"collab_all": False})
check(r.ok, "a server switch (makes a security alert)")
items = wait_for(lambda: [x for x in A.get(B + "/api/admin/alerts").json()["items"] if x["kind"] == "security"])
check(items and items[0]["state"] == "listed" and not items[0]["delivered"], f"the alert is only listed: {items[:1]}")
A.patch(B + "/api/admin/settings", json={"collab_all": True})
check(Bo.get(B + "/api/admin/alerts").status_code == 403, "a member cannot read the admin alerts")

# the channel ntfy: chosen, so the admin's own topic gets them (DNS is off: nothing leaves, the attempt just fails)
check(A.patch(B + "/api/settings", json={"push_channel": "ntfy"}).ok, "alice switches to ntfy")
j = A.get(B + "/api/admin/alerts").json()
check(j["admins"][0]["topic"] != "" and j["admins"][0]["devices"] == 0, f"channel ntfy: her own topic is the destination: {j['admins']}")
r = A.post(B + "/api/admin/alerts/test")
check(r.status_code == 200 and r.json()["ok"] is False and r.json()["alerts"]["items"][0]["state"] == "failed",
      f"test alert goes to ntfy (not reachable here): {r.status_code} {r.text[:200]}")

# Web Push with a device: the alert reaches that device, nothing else
check(A.patch(B + "/api/settings", json={"push_channel": "webpush"}).ok, "alice back on Web Push")
dev = Browser("/alice-phone")
check(A.post(B + "/api/push/subs", json=dev.sub("Alice phone")).ok, "alice subscribes a device")
j = A.get(B + "/api/admin/alerts").json()
check(j["admins"][0]["topic"] == "" and j["admins"][0]["devices"] == 1, f"Web Push to 1 device, no ntfy: {j['admins']}")
r = A.post(B + "/api/admin/alerts/test")
check(r.status_code == 200 and r.json()["ok"] is True, f"test alert delivered: {r.status_code} {r.text[:200]}")
got = wait_for(dev.got)
check(len(got) == 1 and got[0]["title"] == "Kalmido test alert" and "admin alerts arrive" in got[0]["body"] and got[0]["url"] == "/#settings",
      f"the device got the test alert: {got}")
r = A.patch(B + "/api/admin/settings", json={"collab_all": False})
items = wait_for(lambda: [x for x in A.get(B + "/api/admin/alerts").json()["items"] if x["kind"] == "security" and x["state"] != "listed"])
check(items and items[0]["state"] == "sent" and items[0]["delivered"], f"a real alert via Web Push: {items[:1]}")
check(wait_for(lambda: len(dev.got()) >= 2) and any("Collaboration" in x["body"] for x in dev.got()), "the alert arrived on the device")
check(lines("ntfy.log") == [], "nothing went to ntfy at all")

# ------------------------------------------------------------------ container 2: an own ntfy server (start.sh default)
start()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
j = A.get(B + "/api/admin/alerts").json()
check(j["ntfy_public"] is False and j["admins"][0]["topic"] == "t-alice", f"own ntfy server: the admin's topic as before: {j['ntfy_public']} {j['admins']}")
r = A.post(B + "/api/admin/alerts/test")
check(r.ok and r.json()["ok"] is True, f"test alert via the own ntfy: {r.text[:200]}")
m = wait_for(lambda: [x for x in lines("ntfy.log") if x.get("topic") == "t-alice"])
check(len(m) == 1 and m[0]["title"] == "Kalmido test alert", f"arrived on t-alice: {m}")

print(f"p252_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
