#!/usr/bin/env python3
"""Web Push (1.1.3): VAPID key, subscriptions, endpoint allow-list (SSRF), RFC 8291 encryption (decrypted here
with http_ece, acting as the browser), VAPID JWT (RFC 8292), channel routing ntfy / webpush / both incl. the
ntfy fallback, priorities -> Urgency / TTL, 404 / 410 / 429 / 403 handling, the push kinds (reminder with
actions, collaboration incl. the instance + personal switches, habit, digest, time tracking, test).
Starts its OWN test container (start.sh) with a fake push service inside it (stub_webpush.py on
127.0.0.1:9997, allowed via KALMIDO_WEBPUSH_HOSTS). Leaves the container running for webpush_ui.js.
usage: webpush_test.py <datadir>"""
import base64
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import http_ece
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
STUB = "http://127.0.0.1:9997"
TZ = ZoneInfo("Europe/Berlin")


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _lines(name):
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, name), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def ntfy_log():
    return _lines("ntfy.log")


def wp_log():
    return _lines("webpush.log")


def clear():
    for f in ("ntfy.log", "webpush.log"):
        try:
            os.remove(os.path.join(DATA, f))
        except FileNotFoundError:
            pass


def wait_for(fn, n=1, t=8.0):
    t0 = time.time()
    while time.time() - t0 < t:
        x = fn()
        if len(x) >= n:
            time.sleep(0.3)
            return fn()
        time.sleep(0.2)
    return fn()


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


class Browser:
    """A browser's push subscription: our own P-256 key + auth secret, endpoint on the stub."""
    def __init__(self, path):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.endpoint = STUB + path
        self.pub = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

    def sub(self, label="Test browser"):
        return {"endpoint": self.endpoint, "keys": {"p256dh": b64u(self.pub), "auth": b64u(self.auth)}, "label": label}

    def decrypt(self, rec):
        raw = base64.b64decode(rec["body"])
        return json.loads(http_ece.decrypt(raw, private_key=self.key, auth_secret=self.auth, version="aes128gcm"))

    def got(self):
        return [x for x in wp_log() if x["path"] == self.endpoint[len(STUB):]]


def start(keep=False, extra=()):
    env = dict(os.environ, EXTRA=" ".join(["-e KALMIDO_WEBPUSH_HOSTS=" + STUB, *extra]))
    if keep:
        env["KEEP"] = "1"
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["cp", os.path.join(N, "stub_webpush.py"), DATA])
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webpush.py"])
    time.sleep(0.7)


# ------------------------------------------------------------------ container + users
start()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ids = {"alice": 1}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
Bo, Ca = sess("bob"), sess("carol")

# ------------------------------------------------------------------ VAPID key
check(requests.get(B + "/api/push/vapid").status_code == 401, "VAPID key only for logged-in users")
v = A.get(B + "/api/push/vapid").json()
check(v["enabled"] is True and len(b64u_dec(v["key"])) == 65 and b64u_dec(v["key"])[0] == 4, "VAPID public key: uncompressed P-256 point")
VKEY = v["key"]
priv = dbx("SELECT value FROM settings WHERE key='vapid_private'")
check(priv and len(b64u_dec(priv[0][0])) == 32, "VAPID private key stored in the settings table")
PRIV = priv[0][0]
st = A.get(B + "/api/state").json()
check(st["webpush"]["key"] == VKEY and st["webpush"]["devices"] == 0, "state: webpush key + device count")
blob = json.dumps(st) + A.get(B + "/api/export.json").text + A.get(B + "/api/push/subs").text + json.dumps(v)
check(PRIV not in blob, "private VAPID key never in an API response")
check(st["settings"]["push_channel"] == "webpush", "new users default to channel webpush")

# ------------------------------------------------------------------ allow-list / validation (SSRF)
good = Browser("/push/alice1")
bad_eps = ["http://127.0.0.1:8080/x", "https://127.0.0.1/x", "https://169.254.169.254/latest/meta-data", "http://169.254.169.254/",
           "https://fcm.googleapis.com.evil.example/fcm/send/x", "https://evil.example@fcm.googleapis.com/fcm/send/x",
           "https://fcm.googleapis.com:8443/fcm/send/x", "http://fcm.googleapis.com/fcm/send/x", "file:///etc/passwd",
           "https://xnotify.windows.com/w/x", "https://notify.windows.com.evil.example/", "https://localhost/x",
           "https://push.services.mozilla.com.attacker.example/x", "gopher://127.0.0.1:9997/x", "http://127.0.0.1:9998/x",
           "https://fcm.googleapis.com./x", "https://fcm.googleapis.com/x#frag", "https://fcm.googleapis.com/\\@evil", "", None, 5,
           "https://fcm.googleapis.com/" + "a" * 1100]
for ep in bad_eps:
    r = Ca.post(B + "/api/push/subs", json={**good.sub(), "endpoint": ep})
    check(r.status_code == 400, f"endpoint rejected: {str(ep)[:60]!r} -> {r.status_code}")
ok_eps = ["https://fcm.googleapis.com/fcm/send/abc:def", "https://updates.push.services.mozilla.com/wpush/v2/gAAA",
          "https://web.push.apple.com/QAbc", "https://wns2-par02p.notify.windows.com/w/?token=BQYAAA", "https://fcm.googleapis.com:443/wp/x"]
for ep in ok_eps:
    r = Ca.post(B + "/api/push/subs", json={**good.sub(), "endpoint": ep})
    check(r.ok, f"known push service accepted: {ep} -> {r.status_code} {r.text[:80]}")
    if r.ok:  # never let the watchdog push to a real service
        check(Ca.delete(B + f"/api/push/subs/{r.json()['id']}").ok, "remove it again")
check(Ca.get(B + "/api/push/subs").json()["subs"] == [], "carol: no subscriptions left")
for keys, what in (({"p256dh": b64u(b"\x04" + b"\x01" * 64), "auth": b64u(os.urandom(16))}, "point not on the curve"),
                   ({"p256dh": b64u(good.pub[:33]), "auth": b64u(os.urandom(16))}, "compressed / short key"),
                   ({"p256dh": b64u(good.pub), "auth": b64u(os.urandom(8))}, "short auth secret"),
                   ({"p256dh": "not base64!", "auth": b64u(os.urandom(16))}, "garbage key"), ({}, "no keys")):
    r = A.post(B + "/api/push/subs", json={"endpoint": good.endpoint, "keys": keys})
    check(r.status_code == 400, f"invalid keys rejected: {what} -> {r.status_code}")
r = requests.post(B + "/api/push/subs", json=good.sub(), cookies=A.cookies)
check(r.status_code == 403, "subscribe without the CSRF header -> 403")
check(not wp_log(), "no request reached the push stub during validation")

# ------------------------------------------------------------------ subscribe, encrypt, VAPID
clear()
r = A.post(B + "/api/push/subs", json=good.sub("Chrome on Android"))
check(r.ok and r.json()["label"] == "Chrome on Android" and r.json()["host"] == "127.0.0.1", f"subscribe: {r.text[:120]}")
SID = r.json()["id"]
subs = A.get(B + "/api/push/subs").json()
check([x["id"] for x in subs["subs"]] == [SID] and subs["channel"] == "webpush" and subs["ntfy"] is True, "list own subscriptions")
check(Bo.get(B + "/api/push/subs").json()["subs"] == [], "bob does not see alice's devices")
check(Bo.delete(B + f"/api/push/subs/{SID}").status_code == 404, "bob cannot remove alice's device")
check(Bo.post(B + "/api/push/test", json={"id": SID}).status_code == 404, "bob cannot test alice's device")
r = A.post(B + "/api/push/test", json={"id": SID})
check(r.ok and r.json()["ok"] is True, f"test to this device: {r.text}")
got = wait_for(good.got)
check(len(got) == 1, f"stub got one push: {len(got)}")
if got:
    rec = got[0]
    h = rec["headers"]
    check(h.get("content-encoding") == "aes128gcm" and h.get("content-type") == "application/octet-stream", "aes128gcm body")
    check(h.get("ttl") == "600" and h.get("urgency") == "high" and h.get("topic") == "test", f"TTL / Urgency / Topic: {h}")
    body = base64.b64decode(rec["body"])
    check(len(body) <= 4096 and body[20] == 65, "record header: keyid = 65-byte server key, <= 4096 bytes")
    check(b"Kalmido" not in body and b"arriving" not in body, "payload is not readable on the wire")
    p = good.decrypt(rec)
    check(p["title"] == "Kalmido: Test" and p["body"] == "Notifications are arriving." and p["tag"] == "test", f"decrypted payload: {p}")
    check(set(p) <= {"title", "body", "url", "prio", "ts", "tag", "task", "due", "actions"}, f"payload holds only what the notification shows: {sorted(p)}")
    auth = h.get("authorization", "")
    check(auth.startswith("vapid t=") and auth.endswith(", k=" + VKEY), f"Authorization: vapid t=..., k=<public key>: {auth[:40]}")
    jwt = auth[len("vapid t="):].split(",")[0]
    hd, cl, sig = jwt.split(".")
    claims = json.loads(b64u_dec(cl))
    check(json.loads(b64u_dec(hd)) == {"typ": "JWT", "alg": "ES256"}, "JWT header ES256")
    check(claims["aud"] == STUB and 0 < claims["exp"] - time.time() <= 24 * 3600 and claims["sub"], f"JWT claims: {claims}")
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64u_dec(VKEY))
    raw = b64u_dec(sig)
    try:
        pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                   f"{hd}.{cl}".encode(), ec.ECDSA(hashes.SHA256()))
        check(True, "")
    except Exception as e:  # noqa: BLE001
        check(False, f"JWT signature verifies with the VAPID public key: {e}")
check(not [x for x in ntfy_log() if x["topic"] == "t-alice"], "device test does not go to ntfy")
row = dbx("SELECT last_ok, fails FROM push_subs WHERE id=?", (SID,))
check(row and row[0][0] and row[0][1] == 0, "last_ok stored")

# ------------------------------------------------------------------ channels + fallback
def test_push(s):
    clear()
    j = s.post(B + "/api/push/test").json()
    time.sleep(0.8)
    return j, good.got(), [x for x in ntfy_log() if x["topic"] == "t-alice"]


j, w, n = test_push(A)
check(j["ok"] and len(w) == 1 and not n, f"channel webpush + device: only Web Push ({len(w)} / {len(n)})")
A.patch(B + "/api/settings", json={"push_channel": "ntfy"})
j, w, n = test_push(A)
check(j["ok"] and not w and len(n) == 1, f"channel ntfy: only ntfy ({len(w)} / {len(n)})")
A.patch(B + "/api/settings", json={"push_channel": "both"})
j, w, n = test_push(A)
check(j["ok"] and len(w) == 1 and len(n) == 1, f"channel both: both ({len(w)} / {len(n)})")
check(A.patch(B + "/api/settings", json={"push_channel": "sms"}).status_code == 400, "invalid channel rejected")
A.patch(B + "/api/settings", json={"push_channel": "webpush"})
# priorities -> Urgency / payload prio
for prio, urg in (("3", "normal"), ("4", "high"), ("5", "high")):
    A.patch(B + "/api/settings", json={"push_priority": prio})
    j, w, n = test_push(A)
    ok = len(w) == 1 and w[0]["headers"].get("urgency") == urg and good.decrypt(w[0])["prio"] == int(prio)
    check(ok, f"priority {prio} -> Urgency {urg} + payload prio")
    check(w and w[0]["headers"].get("ttl") == "86400", "TTL 1 day for normal pushes")
A.patch(B + "/api/settings", json={"push_priority": "4"})

# fallback transitions: device gone (410) -> this push + later ones go to ntfy
A.delete(B + f"/api/push/subs/{SID}")
j, w, n = test_push(A)
check(not w and len(n) == 1, f"no device subscribed -> ntfy fallback ({len(w)} / {len(n)})")
check(A.get(B + "/api/state").json()["settings"]["push_channel"] == "webpush", "channel stays webpush during the fallback")
gone = Browser("/push/gone-a")
A.post(B + "/api/push/subs", json=gone.sub())
j, w, n = test_push(A)
check(len(gone.got()) == 1 and len(n) == 1, "device answers 410 -> the same push falls back to ntfy")
check(not dbx("SELECT 1 FROM push_subs WHERE endpoint=?", (gone.endpoint,)), "410 -> subscription removed")
nf = Browser("/push/nf-a")
A.post(B + "/api/push/subs", json=nf.sub())
test_push(A)
check(not dbx("SELECT 1 FROM push_subs WHERE endpoint=?", (nf.endpoint,)), "404 -> subscription removed")
j, w, n = test_push(A)
check(len(n) == 1, "after expiry: back to ntfy")
r = A.post(B + "/api/push/subs", json=good.sub("Chrome on Android"))
SID = r.json()["id"]
j, w, n = test_push(A)
check(len(w) == 1 and not n, "device added again -> Web Push only")
# two devices, one gone: no ntfy (one accepted)
two = Browser("/push/gone-b")
A.post(B + "/api/push/subs", json=two.sub())
j, w, n = test_push(A)
check(len(w) == 1 and len(two.got()) == 1 and not n, "one of two devices gone: no ntfy fallback")
# 429: back off, no second request until Retry-After
rate = Browser("/push/rate-a")
A.post(B + "/api/push/subs", json=rate.sub())
test_push(A)
bu = dbx("SELECT backoff_until FROM push_subs WHERE endpoint=?", (rate.endpoint,))
check(bu and bu[0][0] > time.time() + 100, "429 -> backoff_until = now + Retry-After")
test_push(A)
check(len(rate.got()) == 0, "during the backoff no request to that endpoint")  # (clear() wiped the first one)
A.post(B + "/api/push/unsubscribe", json={"endpoint": rate.endpoint})
check(not dbx("SELECT 1 FROM push_subs WHERE endpoint=?", (rate.endpoint,)), "unsubscribe by endpoint")
# 403 five times -> removed
bad = Browser("/push/bad-a")
A.post(B + "/api/push/subs", json=bad.sub())
for _ in range(5):
    test_push(A)
check(not dbx("SELECT 1 FROM push_subs WHERE endpoint=?", (bad.endpoint,)), "403 five times in a row -> removed")
# 413 logged, subscription kept
big = Browser("/push/big-a")
A.post(B + "/api/push/subs", json=big.sub())
test_push(A)
check(dbx("SELECT 1 FROM push_subs WHERE endpoint=?", (big.endpoint,)), "413 -> kept (logged)")
A.post(B + "/api/push/unsubscribe", json={"endpoint": big.endpoint})

# same browser, other account: the subscription moves (a device gets the pushes of who subscribed last)
shared = Browser("/push/shared")
A.post(B + "/api/push/subs", json=shared.sub())
r = Bo.post(B + "/api/push/subs", json=shared.sub("Firefox on Linux"))
check(r.ok and dbx("SELECT user_id FROM push_subs WHERE endpoint=?", (shared.endpoint,))[0][0] == ids["bob"], "same endpoint -> moved to bob")
check(shared.endpoint not in [x["endpoint"] for x in A.get(B + "/api/push/subs").json()["subs"]], "gone from alice's list")
# pushsubscriptionchange: replaces keeps the label; sync never re-adds a removed device
renew = Browser("/push/renewed")
r = Bo.post(B + "/api/push/subs", json={**renew.sub(""), "replaces": shared.endpoint})
check(r.ok and r.json()["label"] == "Firefox on Linux" and not dbx("SELECT 1 FROM push_subs WHERE endpoint=?", (shared.endpoint,)),
      "replaces: old row replaced, label kept")
Bo.post(B + "/api/push/unsubscribe", json={"endpoint": renew.endpoint})
r = Bo.post(B + "/api/push/subs", json={**renew.sub(""), "sync": True})
check(r.ok and r.json().get("known") is False and not dbx("SELECT 1 FROM push_subs WHERE endpoint=?", (renew.endpoint,)),
      "sync of a removed device: not re-added")
# at most 20 devices
for i in range(20):
    Ca.post(B + "/api/push/subs", json=Browser(f"/push/many-{i}").sub())
r = Ca.post(B + "/api/push/subs", json=Browser("/push/many-x").sub())
check(r.status_code == 400 and len(Ca.get(B + "/api/push/subs").json()["subs"]) == 20, "at most 20 devices per user")
for x in Ca.get(B + "/api/push/subs").json()["subs"]:
    Ca.delete(B + f"/api/push/subs/{x['id']}")
for x in A.get(B + "/api/push/subs").json()["subs"]:
    if x["id"] != SID:
        A.delete(B + f"/api/push/subs/{x['id']}")
check([x["id"] for x in A.get(B + "/api/push/subs").json()["subs"]] == [SID], "alice: one device left")

# ------------------------------------------------------------------ push kinds
now = datetime.now(TZ)
# reminder: Web Push with Done / Snooze, task id, repeat -> due for expect_due
clear()
due_t = (now + timedelta(minutes=2)).strftime("%H:%M")
if due_t < now.strftime("%H:%M"):  # around midnight: use an all-day task due yesterday-ish is flaky; skip
    due_t = None
T1 = A.post(B + "/api/tasks", json={"title": "Pay rent", "due": now.date().isoformat(), "due_time": due_t,
                                     "reminders": "5", "repeat": "FREQ=WEEKLY"}).json()["id"]
w = wait_for(good.got, 1, 8)
p = good.decrypt(w[0]) if w else {}
check(p.get("title") == "Pay rent" and p.get("task") == T1 and p.get("url") == f"/#t/{T1}", f"reminder via Web Push: {p}")
check([a["action"] for a in p.get("actions", [])] == ["done", "snooze"] and p["actions"][0]["url"] == f"/#done/{T1}"
      and p["actions"][1]["url"] == f"/#snooze/{T1}" and p["actions"][0]["title"] == "Done", f"reminder actions: {p.get('actions')}")
check(p.get("due") == now.date().isoformat() and p.get("tag") == f"t-{T1}", "repeating task: due for expect_due, tag per task")
check(w and w[0]["headers"].get("topic") == f"t-{T1}", "Topic header = tag")
check(not [x for x in ntfy_log() if x["topic"] == "t-alice"], "reminder not on ntfy (Web Push accepted)")
# the same reminder for a ntfy user keeps the ntfy form
A.patch(B + "/api/settings", json={"push_channel": "ntfy"})
clear()
T2 = A.post(B + "/api/tasks", json={"title": "Call mum", "due": now.date().isoformat(), "due_time": due_t, "reminders": "5"}).json()["id"]
n = wait_for(lambda: [x for x in ntfy_log() if x["topic"] == "t-alice"], 1, 8)
check(len(n) == 1 and n[0]["title"] == "Call mum" and n[0]["click"].endswith(f"/#t/{T2}") and not good.got(), f"reminder via ntfy: {n}")
A.patch(B + "/api/settings", json={"push_channel": "webpush"})

# collaboration: bob comments on a shared task -> alice (Web Push); switches respected
L = A.post(B + "/api/lists", json={"name": "Shared", "kind": "project"}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "edit"}).ok
ST = A.post(B + "/api/tasks", json={"title": "Shared task", "list_id": L}).json()["id"]
time.sleep(3.5)
clear()
Bo.post(B + f"/api/tasks/{ST}/comments", json={"body": "hello alice"})
w = wait_for(good.got, 1, 6)
p = good.decrypt(w[0]) if w else {}
check(p.get("title") == "Shared task" and p.get("body") == "Bob commented: hello alice" and p.get("url") == f"/#t/{ST}", f"comment via Web Push: {p}")
check(not [x for x in ntfy_log() if x["topic"] == "t-alice"], "comment not on ntfy")
# bob on ntfy: alice assigns -> bob gets ntfy
time.sleep(3.5)
clear()
Bo.patch(B + "/api/settings", json={"push_channel": "ntfy"})
A.patch(B + f"/api/tasks/{ST}", json={"assignee_id": ids["bob"]})
n = wait_for(lambda: [x for x in ntfy_log() if x["topic"] == "t-bob"], 1, 6)
check(len(n) == 1 and "assigned you" in n[0]["title"], f"assign push to bob via ntfy: {n}")
# personal collab switch off -> nothing for alice
feats = A.get(B + "/api/state").json()["settings"]["features"]
A.patch(B + "/api/settings", json={"features": ",".join(f for f in feats.split(",") if f != "collab")})
time.sleep(3.5)
clear()
Bo.post(B + f"/api/tasks/{ST}/comments", json={"body": "are you there"})
time.sleep(2.5)
check(not good.got() and not [x for x in ntfy_log() if x["topic"] == "t-alice"], "collab off (personal): no push on any channel")
A.patch(B + "/api/settings", json={"features": feats})
# instance collab switch off -> nothing
A.patch(B + "/api/admin/settings", json={"collab_all": False})
time.sleep(3.5)
clear()
Bo.post(B + f"/api/tasks/{ST}/comments", json={"body": "still there?"})
time.sleep(2.5)
check(not good.got() and not [x for x in ntfy_log() if x["topic"] == "t-alice"], "collab off (instance): no push on any channel")
A.patch(B + "/api/admin/settings", json={"collab_all": True})

# habit reminder (tag per habit) + digest (tag digest, TTL 12 h)
clear()
hm = now.strftime("%H:%M")
HB = A.post(B + "/api/habits", json={"name": "Stretch", "remind_at": hm, "days": "1234567"}).json()["id"]
w = wait_for(good.got, 1, 6)
p = good.decrypt(w[0]) if w else {}
check(p.get("title") == "Habit: Stretch" and p.get("tag") == f"habit-{HB}" and p.get("url") == "/#habits", f"habit via Web Push: {p}")
clear()
A.patch(B + "/api/settings", json={"digest_time": hm})
w = wait_for(good.got, 1, 6)
p = good.decrypt(w[0]) if w else {}
check(p.get("title") == "Today" and p.get("tag") == "digest" and w[0]["headers"].get("ttl") == str(12 * 3600), f"digest via Web Push: {p}")
A.patch(B + "/api/settings", json={"digest_time": ""})

# time tracking: timer running longer than time_remind_h -> Web Push; instance switch off -> nothing
clear()
A.patch(B + "/api/settings", json={"time_remind_h": "1", "time_autostop_h": "0"})
A.patch(B + "/api/lists/" + str(next(x["id"] for x in A.get(B + "/api/state").json()["lists"] if x["is_inbox"])), json={"kind": "project"})  # time tracking: project lists
A.post(B + "/api/time/start", json={"task_id": T2, "at": (datetime.now(TZ) - timedelta(hours=2)).isoformat()})
w = wait_for(good.got, 1, 6)
p = good.decrypt(w[0]) if w else {}
check(p.get("title") == "Timer still running" and p.get("url") == "/#time", f"time reminder via Web Push: {p}")
A.post(B + "/api/time/stop", json={})
A.patch(B + "/api/admin/settings", json={"time_all": False})
dbx("UPDATE time_entries SET reminded=0")
clear()
dbx("INSERT INTO time_entries(user_id,task_id,start,created_at,updated_at) VALUES(?,?,?,?,?)",
    (1, T2, (datetime.now(TZ) - timedelta(hours=3)).isoformat(), datetime.now(TZ).isoformat(), datetime.now(TZ).isoformat()))
time.sleep(2.5)
check(not good.got() and not [x for x in ntfy_log() if x["topic"] == "t-alice"], "time tracking off (instance): no timer push")
A.patch(B + "/api/admin/settings", json={"time_all": True})
dbx("DELETE FROM time_entries WHERE end IS NULL")

# ------------------------------------------------------------------ persistence + migration (restart)
dbx("DELETE FROM user_settings WHERE key='push_channel' AND user_id=?", (ids["carol"],))  # like a user from 1.1
Bo.patch(B + "/api/settings", json={"push_channel": "ntfy"})
start(keep=True)
A = sess("alice")
check(A.get(B + "/api/push/vapid").json()["key"] == VKEY, "VAPID key survives a restart")
check(sess("carol").get(B + "/api/state").json()["settings"]["push_channel"] == "webpush", "existing user (no setting yet) -> webpush after the update")
check(sess("bob").get(B + "/api/state").json()["settings"]["push_channel"] == "ntfy", "an explicit ntfy choice is kept")
check([x["id"] for x in A.get(B + "/api/push/subs").json()["subs"]] == [SID], "subscriptions survive a restart")

# ------------------------------------------------------------------ Web Push switched off (KALMIDO_WEBPUSH=0)
start(keep=True, extra=["-e KALMIDO_WEBPUSH=0"])
A = sess("alice")
clear()
check(A.get(B + "/api/push/vapid").json() == {"enabled": False, "key": ""}, "KALMIDO_WEBPUSH=0: no key handed out")
check(A.post(B + "/api/push/subs", json=Browser("/push/off").sub()).status_code == 404, "KALMIDO_WEBPUSH=0: no new subscriptions")
j, w, n = test_push(A)
check(not w and len(n) == 1, "KALMIDO_WEBPUSH=0: everything via ntfy")
start(keep=True)  # back on for webpush_ui.js

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
