#!/usr/bin/env python3
"""2.0.5 API tests. #310 emptying the trash: instance admins also delete for good what is trashed in shared lists of
other owners where they may edit (here: a list owned by an agent user), everyone else keeps the owner rule; the answer
counts {deleted, kept}, the trash view marks what stays (keep). #311 closing notifications handled on another device:
tag per task (t-<id>) tracked per device, completing / opening (/seen, /api/push/handled) / reading the News item marks it
handled on the OTHER devices (X-Kalmido-Device = this one), a dismiss push {type: 'dismiss', tags} after the debounce, rate
limited (gap, daily cap), never to Apple endpoints (piggybacked on the next real push instead), not counted as delivery.
Starts its OWN container (start.sh) with the fake push service (stub_webpush.py on 127.0.0.1:9997) inside it; endpoints
under /apple count as Apple's push service (KALMIDO_WEBPUSH_APPLE).
usage: p205_api_test.py <datadir>"""
import base64
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date

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


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def wp_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "webpush.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def clear():
    try:
        os.remove(os.path.join(DATA, "webpush.log"))
    except FileNotFoundError:
        pass


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def wait_for(fn, n=1, t=8.0):
    t0 = time.time()
    while time.time() - t0 < t:
        x = fn()
        if len(x) >= n:
            time.sleep(0.3)
            return fn()
        time.sleep(0.2)
    return fn()


class Browser:
    def __init__(self, path):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.endpoint = STUB + path
        self.pub = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

    def sub(self, label):
        return {"endpoint": self.endpoint, "keys": {"p256dh": b64u(self.pub), "auth": b64u(self.auth)}, "label": label}

    def got(self):
        out = []
        for rec in wp_log():
            if rec["path"] == self.endpoint[len(STUB):]:
                raw = base64.b64decode(rec["body"])
                out.append((rec, json.loads(http_ece.decrypt(raw, private_key=self.key, auth_secret=self.auth, version="aes128gcm"))))
        return out

    def dismisses(self):
        return [p for _, p in self.got() if p.get("type") == "dismiss"]

    def notes(self):
        return [p for _, p in self.got() if p.get("type") != "dismiss"]


env = dict(os.environ, EXTRA=" ".join(["-e KALMIDO_WEBPUSH_HOSTS=" + STUB, "-e KALMIDO_WEBPUSH_APPLE=" + STUB + "/apple",
                                       "-e KALMIDO_DISMISS_WAIT=1", "-e KALMIDO_DISMISS_GAP=3"]))
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["cp", os.path.join(N, "stub_webpush.py"), DATA])
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webpush.py"])
time.sleep(0.7)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ids = {"alice": 1}
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carl")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en"})

# ================================================================== #310 trash
DEV = Ca.post(B + "/api/lists", json={"name": "Dev", "kind": "project"}).json()["id"]
VIEW = Ca.post(B + "/api/lists", json={"name": "Read only", "kind": "project"}).json()["id"]
for lid, u, role in ((DEV, "alice", "edit"), (DEV, "bob", "edit"), (VIEW, "alice", "view")):
    assert Ca.put(B + f"/api/lists/{lid}/members", json={"user_id": ids[u], "role": role}).ok
TA = A.post(B + "/api/tasks", json={"title": "Alice in Dev", "list_id": DEV}).json()["id"]
TA1 = A.post(B + "/api/tasks", json={"title": "Sub of it", "list_id": DEV, "parent_id": TA}).json()["id"]
TB = Bo.post(B + "/api/tasks", json={"title": "Bob in Dev", "list_id": DEV}).json()["id"]
TV = Ca.post(B + "/api/tasks", json={"title": "Carl read only", "list_id": VIEW}).json()["id"]
MINE = A.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
TM = A.post(B + "/api/tasks", json={"title": "Alice own", "list_id": MINE}).json()["id"]
BMINE = Bo.post(B + "/api/lists", json={"name": "Bobs"}).json()["id"]
TBO = Bo.post(B + "/api/tasks", json={"title": "Bob own", "list_id": BMINE}).json()["id"]
for s, t in ((A, TA), (Bo, TB), (A, TM), (Ca, TV), (Bo, TBO)):
    check(s.delete(B + f"/api/tasks/{t}").ok, f"to the trash: {t}")
# carl becomes an agent (a list owned by an agent user, the case of the dev lists)
r = A.patch(B + f"/api/users/{ids['carl']}", json={"kind": "agent"})
check(r.ok, f"carl -> agent: {r.status_code} {r.text[:100]}")
alive = lambda *t: {x[0] for x in dbx(f"SELECT id FROM tasks WHERE id IN ({','.join('?' * len(t))})", t)}

tb = {t["id"]: t for t in Bo.get(B + "/api/tasks?scope=trash").json()["tasks"]}
check(set(tb) == {TA, TA1, TB, TBO}, f"bob's trash: Dev items + his own: {sorted(tb)}")
check(all(tb[t].get("keep") for t in (TA, TA1, TB)) and not tb[TBO].get("keep"), "bob (member, no admin): Dev items marked keep, own not")
r = Bo.delete(B + "/api/trash")
check(r.ok and r.json().get("deleted") == 1 and r.json().get("kept") == 3, f"bob empties: {{deleted: 1, kept: 3}}: {r.text}")
check(alive(TA, TA1, TB) == {TA, TA1, TB} and not alive(TBO), "bob: Dev items still there, his own gone")
ta = {t["id"]: t for t in A.get(B + "/api/tasks?scope=trash").json()["tasks"]}
check(set(ta) == {TA, TA1, TB, TM}, f"alice's trash (no view-only list): {sorted(ta)}")
check(not any(t.get("keep") for t in ta.values()), "alice (admin + edit member): nothing marked keep")
r = A.delete(B + "/api/trash")
check(r.ok and r.json().get("deleted") == 4 and r.json().get("kept") == 0, f"alice empties: {{deleted: 4, kept: 0}}: {r.text}")
check(not alive(TA, TA1, TB, TM), "admin: shared list of the agent emptied too (incl. subtask)")
check(alive(TV) == {TV}, "a list where the admin only views: its trash is untouched")
check(A.get(B + "/api/tasks?scope=trash").json()["tasks"] == [], "alice: trash empty now")
# an admin who is not a member at all: nothing of the list
TB2 = Bo.post(B + "/api/tasks", json={"title": "Bob again", "list_id": DEV}).json()["id"]
Bo.delete(B + f"/api/tasks/{TB2}")
A.delete(B + f"/api/lists/{DEV}/members/{ids['alice']}")
r = A.delete(B + "/api/trash")
check(r.ok and r.json()["deleted"] == 0 and alive(TB2) == {TB2}, "admin without membership: the list's trash stays")
# a subtask in a list the admin may not purge survives (detached) when its parent is deleted for good
P = A.post(B + "/api/tasks", json={"title": "Parent", "list_id": MINE}).json()["id"]
check(A.delete(B + f"/api/tasks/{P}").ok and A.delete(B + "/api/trash").json()["deleted"] >= 1 and not alive(P), "own parent deleted for good")

# ================================================================== #311 dismiss handled notifications
phone, desk, iph = Browser("/push/phone"), Browser("/push/desk"), Browser("/apple/iphone")
SUB = {}
for b, lab in ((phone, "Chrome on Android"), (desk, "Firefox on Linux"), (iph, "Safari on iPhone")):
    r = A.post(B + "/api/push/subs", json=b.sub(lab))
    check(r.ok, f"subscribe {lab}")
    SUB[lab] = r.json()["id"]
TEAM = A.post(B + "/api/lists", json={"name": "Team", "kind": "project"}).json()["id"]
assert A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": ids["bob"], "role": "edit"}).ok
X, Y, Z, W = (A.post(B + "/api/tasks", json={"title": n, "list_id": TEAM}).json()["id"] for n in ("Task X", "Task Y", "Task Z", "Task W"))
time.sleep(3.5)
clear()
Bo.post(B + f"/api/tasks/{X}/comments", json={"body": "look at X"})
wait_for(lambda: wp_log(), 3)
check(all(len(b.notes()) == 1 and b.notes()[0].get("tag") == f"t-{X}" for b in (phone, desk, iph)), "comment push on all three devices, tag t-<id>")
rows = dbx("SELECT sub_id, tag, handled_at FROM push_tags ORDER BY sub_id")
check(len(rows) == 3 and all(r[1] == f"t-{X}" and r[2] is None for r in rows), f"tracked per device: {rows}")
# a test push (tag test) is not tracked
A.post(B + "/api/push/test", json={"id": SUB["Chrome on Android"]})
time.sleep(0.8)
check(len(dbx("SELECT 1 FROM push_tags")) == 3, "tag 'test' not tracked")
# the sending thread commits last_ok after the last device: wait until all three are stored, then remember them
wait_for(lambda: [1 for r in dbx("SELECT last_ok FROM push_subs") if r[0]], 3)
time.sleep(0.5)
lastok = dict(dbx("SELECT id, last_ok FROM push_subs"))
clear()
# complete X on the desktop: desk closes its own, phone gets a dismiss push, the iPhone none
r = A.post(B + f"/api/tasks/{X}/complete", headers={"X-Kalmido-Device": desk.endpoint})
check(r.ok, "complete X on the desktop")
rows = {r[0]: r for r in dbx("SELECT sub_id, tag, handled_at FROM push_tags")}
check(SUB["Firefox on Linux"] not in rows and rows[SUB["Chrome on Android"]][2] and rows[SUB["Safari on iPhone"]][2], f"origin row dropped, others handled: {rows}")
d = wait_for(phone.dismisses, 1, 8)
check(len(d) == 1 and {k: v for k, v in d[0].items() if k != "badge"} == {"type": "dismiss", "tags": [f"t-{X}"]} and isinstance(d[0].get("badge"), int),
      f"phone: dismiss push (2.19.0: with the app badge) {d}")
rec = [x for x, p in phone.got() if p.get("type") == "dismiss"]
check(rec and rec[0]["headers"].get("urgency") == "normal" and rec[0]["headers"].get("ttl") == "3600" and "topic" not in rec[0]["headers"],
      "dismiss push: Urgency normal, TTL 1 h, no Topic")
time.sleep(2)
check(not desk.got(), "desktop (where it was handled): nothing")
check(not iph.got(), "iPhone: no silent push (Apple)")
check(dict(dbx("SELECT id, last_ok FROM push_subs")) == lastok, "dismiss does not count as a delivered push (last_ok unchanged)")
check(not dbx("SELECT 1 FROM push_tags WHERE sub_id=?", (SUB["Chrome on Android"],)), "phone: row gone after the dismiss")
check(dbx("SELECT tag FROM push_tags WHERE sub_id=? AND handled_at IS NOT NULL", (SUB["Safari on iPhone"],)) == [(f"t-{X}",)], "iPhone: waits for the next push")
# the next real push carries the dismiss tags to the iPhone (and to nobody else)
time.sleep(3.5)
clear()
Bo.post(B + f"/api/tasks/{Y}/comments", json={"body": "and Y"})
wait_for(lambda: wp_log(), 3)
pi = iph.notes()
check(len(pi) == 1 and pi[0].get("tag") == f"t-{Y}" and pi[0].get("dismiss") == [f"t-{X}"], f"iPhone: next push with dismiss [t-X]: {pi}")
check(all("dismiss" not in p for p in phone.notes() + desk.notes()), "others: no dismiss piggyback (nothing pending)")
check(not dbx("SELECT 1 FROM push_tags WHERE sub_id=? AND tag=?", (SUB["Safari on iPhone"], f"t-{X}")), "iPhone: t-X done after the piggyback")
# opening the task (POST /api/push/handled) without a device header: every device, only mine
check(Bo.post(B + "/api/push/handled", json={"tasks": [Y]}).json().get("marked") == 0, "bob marks Y: none of his devices, nothing of alice's")
check(A.post(B + "/api/push/handled", json={"tasks": ["x"]}).status_code == 400, "invalid ids -> 400")
clear()
r = A.post(B + "/api/push/handled", json={"tasks": [Y]})
check(r.ok and r.json().get("marked") == 3, f"alice opens Y (no device header): 3 marked: {r.text}")
d = wait_for(lambda: phone.dismisses() + desk.dismisses(), 2, 8)
check(len(phone.dismisses()) == 1 and len(desk.dismisses()) == 1 and not iph.got(), "dismiss to phone + desk, not the iPhone")
# rate limit: another handled tag right after -> not before the gap (3 s)
time.sleep(3.5)
clear()
Bo.post(B + f"/api/tasks/{Z}/comments", json={"body": "Z"})
wait_for(lambda: wp_log(), 3)
clear()
dbx("UPDATE push_subs SET dismiss_at=? WHERE id=?", (time.time(), SUB["Chrome on Android"]))
A.post(B + "/api/push/handled", json={"tasks": [Z]}, headers={"X-Kalmido-Device": str(SUB["Firefox on Linux"])})
time.sleep(2)
check(not phone.dismisses(), "phone: within the gap no second dismiss")
d = wait_for(phone.dismisses, 1, 6)
check(len(d) == 1 and d[0]["tags"] == [f"t-{Z}"], "phone: dismiss after the gap")
check(not desk.got(), "device header as subscription id: the desktop is the origin, nothing sent there")
# daily cap: none once reached
time.sleep(3.5)
clear()
Bo.post(B + f"/api/tasks/{W}/comments", json={"body": "W"})
wait_for(lambda: wp_log(), 3)
clear()
dbx("UPDATE push_subs SET dismiss_n=30, dismiss_day=?", (date.today().isoformat(),))
A.post(B + "/api/push/handled", json={"tasks": [W]})
time.sleep(5)
check(not phone.dismisses() and not desk.dismisses(), "daily cap reached: no dismiss push")
dbx("UPDATE push_subs SET dismiss_n=0, dismiss_day=''")
dbx("DELETE FROM push_tags")
# News read closes the task's notification elsewhere; a foreign device header counts as none
time.sleep(3.5)
clear()
Bo.patch(B + f"/api/tasks/{W}", json={"assignee_id": ids["alice"]})
wait_for(lambda: wp_log(), 3)
check(all(p.get("tag") == f"t-{W}" for p in phone.notes() + desk.notes() + iph.notes()) and len(phone.notes()) == 1, "assign push tagged t-W")
items = A.get(B + "/api/news").json()["items"]
nid = [i for it in items if it.get("task_id") == W and not it.get("read") for i in it["ids"]]
check(nid, "News item for W")
clear()
r = A.post(B + "/api/news/read", json={"ids": nid}, headers={"X-Kalmido-Device": "https://fcm.googleapis.com/fcm/send/not-mine"})
check(r.ok, "read the News item")
check(len(dbx("SELECT 1 FROM push_tags WHERE tag=? AND handled_at IS NOT NULL", (f"t-{W}",))) == 3, "News read: all three handled (foreign header ignored)")
d = wait_for(lambda: phone.dismisses() + desk.dismisses(), 2, 8)
check(len(d) == 2 and all(x["tags"] == [f"t-{W}"] for x in d), f"dismiss for W after reading the News: {d}")
# nothing tracked -> no dismiss push at all
clear()
V = A.post(B + "/api/tasks", json={"title": "Never pushed", "list_id": TEAM}).json()["id"]
A.post(B + f"/api/tasks/{V}/complete")
time.sleep(3)
check(not wp_log(), "completing a task without notification: no push")
# a gone device (410) on a dismiss push is removed
gone = Browser("/push/gone-x")
gid = A.post(B + "/api/push/subs", json=gone.sub("old")).json()["id"]
dbx("INSERT INTO push_tags(sub_id, tag, sent_at, handled_at) VALUES(?,?,?,?)", (gid, "t-999", time.time(), time.time() - 5))
time.sleep(3)
check(not dbx("SELECT 1 FROM push_subs WHERE id=?", (gid,)), "410 on a dismiss push: subscription removed")
# a subscription removed -> its rows go too (ON DELETE CASCADE)
A.delete(B + f"/api/push/subs/{SUB['Firefox on Linux']}")
dbx("INSERT INTO push_tags(sub_id, tag, sent_at) VALUES(?,?,?)", (SUB["Chrome on Android"], "t-1", time.time()))
A.delete(B + f"/api/push/subs/{SUB['Chrome on Android']}")
check(not dbx("SELECT 1 FROM push_tags WHERE sub_id IN (?,?)", (SUB["Firefox on Linux"], SUB["Chrome on Android"])), "rows of removed devices are gone")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
