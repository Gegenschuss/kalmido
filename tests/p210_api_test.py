#!/usr/bin/env python3
"""2.1.0 API tests.
 - #317 notification settings: the matrix (defaults = the behaviour up to 2.0.8, new events off except "reply", the
   follow-up on), News + push filtered in one place (comment on my task / reply to my comment / comment on a task I
   follow / new task in a shared list / status / reminder), the list bell (all / default / mute: mentions and assignments
   still come through), PATCH /api/settings (partial object and the web app's whole string), GET /api/v1/me
   notifications + PATCH /api/v1/me/notifications, validation, a list I do not see
 - #180 Paperless connections: the legacy one from the environment keeps working; server connections (admin: name + URL,
   no token, who may use it) with each user's own token; personal connections only for their owner (neither another
   user nor an admin sees or uses them, in the UI API, the admin API and the v1 API); tokens never in any answer or page,
   encrypted at rest (AES-GCM, KALMIDO_SECRET_KEY), sent only to their connection (the fake Paperless logs the header);
   the SSRF guard for personal connections (internal only when an admin allowed the host); a new server address drops
   the tokens, taking a user off drops theirs; links remember their connection (others see "a document"); without the
   key: tokens cannot be stored (409), stored ones are unusable, the legacy connection still works
 - #335 waiting on external: set / change / clear (web API + v1 + ?waiting=), validation, the follow-up day fires once
   (push "Follow up", News "followup" to the person it is for, event followup_due to the following agent)
Starts its OWN containers (start.sh) with the fake Paperless (fake_services.py, 127.0.0.1:8082) and the fake push
service (stub_webpush.py, 127.0.0.1:9997) inside.
usage: p210_api_test.py <datadir>"""
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
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
STUB = "http://127.0.0.1:9997"
KEY = base64.b64encode(os.urandom(32)).decode()
FAILS, OKS = [], [0]
SEEN = []  # every response text of this suite: no token may ever be in one


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


class S(requests.Session):
    def request(self, *a, **k):
        r = super().request(*a, **k)
        SEEN.append(r.text)
        return r


def sess(user, pw="password123"):
    s = S()
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
    for f in ("webpush.log",):
        try:
            os.remove(os.path.join(DATA, f))
        except FileNotFoundError:
            pass


def fake_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "fake.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


class Browser:
    def __init__(self, path):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.endpoint = STUB + path
        self.pub = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

    def sub(self, label):
        return {"endpoint": self.endpoint, "keys": {"p256dh": b64u(self.pub), "auth": b64u(self.auth)}, "label": label}

    def notes(self):
        out = []
        for rec in wp_log():
            if rec["path"] == self.endpoint[len(STUB):]:
                p = json.loads(http_ece.decrypt(base64.b64decode(rec["body"]), private_key=self.key, auth_secret=self.auth, version="aes128gcm"))
                if p.get("type") != "dismiss":
                    out.append(p)
        return out


def settle(fn, t=6.0):
    """Waits until fn() stops changing (pushes go out in a thread after the request)."""
    t0, last = time.time(), None
    while time.time() - t0 < t:
        x = fn()
        if x == last and time.time() - t0 > 1.2:
            return x
        last = x
        time.sleep(0.3)
    return fn()


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def _r(self, m, p, **k):
        r = requests.request(m, V + p, headers=self.h, timeout=60, **k)
        SEEN.append(r.text)
        return r

    def get(self, p, **k):
        return self._r("GET", p, **k)

    def put(self, p, **k):
        return self._r("PUT", p, **k)

    def patch(self, p, **k):
        return self._r("PATCH", p, **k)

    def delete(self, p, **k):
        return self._r("DELETE", p, **k)


def start(with_key=True, keep=False):
    extra = ["-e KALMIDO_WEBPUSH_HOSTS=" + STUB, "-e PAPERLESS_TOKEN=pl-legacy-env-token", "-e PAPERLESS_API=http://127.0.0.1:8082",
             "-e PAPERLESS_PUBLIC_URL=https://paperless.example.test"] + (["-e KALMIDO_SECRET_KEY=" + KEY] if with_key else [])
    env = dict(os.environ, EXTRA=" ".join(extra), **({"KEEP": "1"} if keep else {}))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    for f in ("stub_webpush.py", "fake_services.py"):
        subprocess.run(["cp", os.path.join(N, f), DATA])
        subprocess.run(["docker", "exec", "-d", CT, "python", "/data/" + f])
    time.sleep(0.8)


start()
s0 = S()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ids = {"alice": 1}
for u in ("bob", "gert"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ge = sess("bob"), sess("gert")
for x in (A, Bo, Ge):
    x.patch(B + "/api/settings", json={"lang": "en"})

# ================================================================== #317 the matrix
st = Bo.get(B + "/api/state").json()
m = st["notify"]
check(all(m[k]["news"] and m[k]["push"] for k in ("comment", "reply", "follow", "mention", "assign", "unblock")), f"defaults on: {m}")
check(m["newtask"] == {"news": False, "push": False} and m["approval"] == {"news": False, "push": True}, "new events off (approval push as before)")
check(m["complete"] == {"news": False, "push": True} and m["status"] == {"news": True, "push": False} and m["share"] == {"news": True, "push": False},
      "complete / status / share as before")
check(m["reminder"] == {"news": None, "push": True} and m["followup"] == {"news": True, "push": True}, "reminder push only; follow-up on")
# old clients: news_kinds keeps working and drives the News column of the old events (reply / follow follow "comment")
Bo.patch(B + "/api/settings", json={"news_kinds": "mention,assign"})
m = Bo.get(B + "/api/state").json()["notify"]
check(not m["comment"]["news"] and not m["reply"]["news"] and not m["follow"]["news"] and m["mention"]["news"] and m["comment"]["push"], "news_kinds -> matrix")
Bo.patch(B + "/api/settings", json={"news_kinds": "mention,assign,comment,unblock,share,status"})
# partial object: primary rows write news_kinds, the rest notify
r = Bo.patch(B + "/api/settings", json={"notify": {"complete": {"news": True}, "status": {"push": 1}, "newtask": {"news": 1}}})
st = Bo.get(B + "/api/state").json()
check(r.ok and "complete" in st["settings"]["news_kinds"].split(",") and st["notify"]["status"]["push"] and st["notify"]["newtask"]["news"],
      f"partial update: {st['settings']['news_kinds']} {st['settings']['notify']}")
check("complete" not in json.loads(st["settings"]["notify"]), "primary News is not duplicated in notify")
for bad in ({"bogus": {"push": 1}}, {"reminder": {"news": 1}}, {"comment": {"push": 2}}, {"comment": {"sound": 1}}, [1], "{not json"):
    check(Bo.patch(B + "/api/settings", json={"notify": bad}).status_code == 400, f"invalid notify refused: {bad}")
# the web app sends the whole string (undo sends the old one back; '' = defaults)
r = Bo.patch(B + "/api/settings", json={"notify": "", "news_kinds": "mention,assign,comment,unblock,share,status"})
m = Bo.get(B + "/api/state").json()["notify"]
check(r.ok and not m["status"]["push"] and not m["newtask"]["news"] and not m["complete"]["news"], "whole string '' = defaults")
check(Bo.patch(B + "/api/settings", json={"notify": json.dumps({"reply": {"push": 0}})}).ok and not Bo.get(B + "/api/state").json()["notify"]["reply"]["push"],
      "whole string stored")
Bo.patch(B + "/api/settings", json={"notify": ""})

# pushes + News through the matrix
bphone, aphone, gphone = Browser("/push/bob"), Browser("/push/alice"), Browser("/push/gert")
check(Bo.post(B + "/api/push/subs", json=bphone.sub("Phone")).ok and A.post(B + "/api/push/subs", json=aphone.sub("Phone")).ok
      and Ge.post(B + "/api/push/subs", json=gphone.sub("Phone")).ok, "subscribed")
TEAM = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]
for u in ("bob", "gert"):
    assert A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": ids[u], "role": "edit"}).ok


def news(s, kind=None):
    j = s.get(B + "/api/news").json()
    return [x for x in j.get("items", []) if kind is None or x["kind"] == kind]


def ncount(s, kind=None):  # consecutive comments on one task are one News row with a count
    return sum(x.get("count", 1) for x in news(s, kind))


def bob_push(fn, t=6.0):
    """Runs fn, returns bob's pushes it caused."""
    clear()
    fn()
    return settle(bphone.notes, t)


BT = Bo.post(B + "/api/tasks", json={"title": "Bobs task", "list_id": TEAM}).json()["id"]
time.sleep(3.2)
n0 = ncount(Bo, "comment")
p = bob_push(lambda: A.post(B + f"/api/tasks/{BT}/comments", json={"body": "on your task"}))
check(len(p) == 1 and "on your task" in p[0]["body"] and ncount(Bo, "comment") == n0 + 1, f"comment on my task: push + News ({len(p)})")
Bo.patch(B + "/api/settings", json={"notify": {"comment": {"push": 0}}})
time.sleep(3.2)
n0 = ncount(Bo, "comment")
p = bob_push(lambda: A.post(B + f"/api/tasks/{BT}/comments", json={"body": "again"}))
check(not p and ncount(Bo, "comment") > n0, f"comment push off: News only ({len(p)})")
Bo.patch(B + "/api/settings", json={"notify": {"comment": {"push": 1}}})
# reply vs follow on alice's task where bob commented
AT = A.post(B + "/api/tasks", json={"title": "Alices task", "list_id": TEAM}).json()["id"]
Bo.post(B + f"/api/tasks/{AT}/comments", json={"body": "my thoughts"})
Bo.patch(B + "/api/settings", json={"notify": {"follow": {"push": 0, "news": 0}}})
time.sleep(3.2)
n0 = ncount(Bo, "comment")
p = bob_push(lambda: Ge.post(B + f"/api/tasks/{AT}/comments", json={"body": "answer to bob"}))
check(len(p) == 1 and "answer to bob" in p[0]["body"] and ncount(Bo, "comment") == n0 + 1, f"reply to my comment (follow off): push + News ({len(p)})")
time.sleep(3.2)
n0 = ncount(Bo, "comment")
p = bob_push(lambda: A.post(B + f"/api/tasks/{AT}/comments", json={"body": "later remark"}))
check(not p and ncount(Bo, "comment") == n0, f"a later comment is 'follow' (off): nothing ({len(p)})")
Bo.patch(B + "/api/settings", json={"notify": {"follow": {"push": 1, "news": 1}}})
# new task in a shared list: off by default, the bell "All" turns it on
time.sleep(3.2)
p = bob_push(lambda: Ge.post(B + "/api/tasks", json={"title": "Gerts new task", "list_id": TEAM}))
check(not p and not news(Bo, "newtask"), "new task: nothing by default")
check(Bo.put(B + f"/api/lists/{TEAM}/bell", json={"mode": "all"}).ok, "bell: all")
check(next(x for x in Bo.get(B + "/api/state").json()["lists"] if x["id"] == TEAM)["bell"] == "all", "state: the list's bell")
check(next(x for x in A.get(B + "/api/state").json()["lists"] if x["id"] == TEAM)["bell"] == "default", "the bell is per user")
p = bob_push(lambda: Ge.post(B + "/api/tasks", json={"title": "Another one", "list_id": TEAM}))
check(len(p) == 1 and "Another one" in p[0]["title"] and news(Bo, "newtask"), f"bell all: new task push + News ({[x.get('title') for x in p]})")
GT = Ge.post(B + "/api/tasks", json={"title": "Gerts private chat", "list_id": TEAM}).json()["id"]
time.sleep(3.2)
p = bob_push(lambda: A.post(B + f"/api/tasks/{GT}/comments", json={"body": "not bobs business"}))
check(len(p) == 1, f"bell all: every comment ({len(p)})")
# mute: only mentions + assignments
check(Bo.put(B + f"/api/lists/{TEAM}/bell", json={"mode": "mute"}).ok, "bell: mute")
time.sleep(3.2)
n0 = ncount(Bo)
p = bob_push(lambda: A.post(B + f"/api/tasks/{BT}/comments", json={"body": "muted comment"}))
check(not p and ncount(Bo) == n0, f"mute: no comment push / News ({len(p)})")
time.sleep(3.2)
p = bob_push(lambda: A.post(B + f"/api/tasks/{BT}/comments", json={"body": f"<@{ids['bob']}> but this one"}))
check(len(p) == 1 and news(Bo, "mention"), "mute: a mention still comes through")
p = bob_push(lambda: A.patch(B + f"/api/tasks/{AT}", json={"assignee_id": ids["bob"]}))
check(len(p) == 1 and news(Bo, "assign"), "mute: an assignment still comes through")
check(Bo.put(B + f"/api/lists/{TEAM}/bell", json={"mode": "default"}).ok, "bell: default")
check(Bo.put(B + f"/api/lists/{TEAM}/bell", json={"mode": "loud"}).status_code == 400, "bell: unknown mode 400")
PRIV = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]
check(Bo.put(B + f"/api/lists/{PRIV}/bell", json={"mode": "mute"}).status_code == 404, "bell: a list I do not see 404")
# status: no push by default, push when switched on
A.patch(B + f"/api/lists/{TEAM}", json={"kind": "project"})
p = bob_push(lambda: A.post(B + f"/api/lists/{TEAM}/status", json={"status": "at_risk", "note": "late"}))
check(not p and news(Bo, "status"), "status: News, no push by default")
Bo.patch(B + "/api/settings", json={"notify": {"status": {"push": 1}}})
p = bob_push(lambda: A.post(B + f"/api/lists/{TEAM}/status", json={"status": "on_track", "note": ""}))
check(len(p) == 1 and "Team" in p[0]["title"] and "On track" in p[0]["body"], f"status push when on: {p}")
# v1
tok = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
bv = Api(tok)
j = bv.get("/me").json()
check(j["notifications"]["events"]["status"]["push"] and j["notifications"]["events"]["reminder"]["news"] is None, "v1 /me: notifications")
r = bv.patch("/me/notifications", json={"events": {"newtask": {"push": True}}, "lists": {str(TEAM): "all"}})
check(r.ok and r.json()["events"]["newtask"]["push"] and r.json()["lists"] == {str(TEAM): "all"}, f"v1 PATCH: {r.text[:200]}")
check(bv.patch("/me/notifications", json={"lists": {str(PRIV): "mute"}}).status_code == 404, "v1: a list I do not see 404")
check(bv.patch("/me/notifications", json={"events": {"nope": {"push": True}}}).status_code == 400, "v1: unknown event 400")
check(bv.patch("/me/notifications", json={"colour": 1}).status_code == 400, "v1: unknown field 400")
bv.patch("/me/notifications", json={"lists": {str(TEAM): "default"}, "events": {"newtask": {"push": False}}})

# ================================================================== #335 waiting on external
W = Bo.post(B + "/api/tasks", json={"title": "Quote from the carpenter", "list_id": TEAM}).json()["id"]
r = Bo.put(B + f"/api/tasks/{W}/waiting", json={"note": "carpenter Meier", "until": "2031-05-01"})
t = r.json()
check(r.ok and t["waiting_at"] and t["wait_note"] == "carpenter Meier" and t["wait_until"] == "2031-05-01", f"set waiting: {r.text[:200]}")
check(Bo.put(B + f"/api/tasks/{W}/waiting", json={"until": "31.12."}).status_code == 400, "invalid date 400")
check(Bo.put(B + f"/api/tasks/{W}/waiting", json={"who": "x"}).status_code == 400, "unknown field 400")
check(Ge.put(B + f"/api/tasks/{BT}/waiting", json={"note": "x"}).ok, "an editor of the list may set it")
check(Bo.delete(B + f"/api/tasks/{BT}/waiting").json()["waiting_at"] is None, "clear")
j = bv.get("/tasks", params={"waiting": "true"}).json()
check([x["id"] for x in j["data"]] == [W] and j["data"][0]["waiting"]["note"] == "carpenter Meier" and j["data"][0]["waiting"]["until"] == "2031-05-01",
      f"v1 ?waiting=true: {j}")
check(W not in [x["id"] for x in bv.get("/tasks", params={"waiting": "false"}).json()["data"]], "v1 ?waiting=false")
check(bv.get("/tasks", params={"waiting": "maybe"}).status_code == 400, "v1 ?waiting=maybe 400")
r = bv.put(f"/tasks/{BT}/waiting", json={"note": "the office", "until": None})
check(r.ok and r.json()["waiting"]["note"] == "the office" and r.json()["waiting"]["until"] is None, "v1 PUT waiting")
check(bv.delete(f"/tasks/{BT}/waiting").json()["waiting"] is None, "v1 DELETE waiting")
check(bv.put(f"/tasks/{BT}/waiting", json={"note": 5}).status_code == 400, "v1: note must be text")
# the follow-up day: push + News for the person, followup_due for the following agent, once
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
AG, AGTOK = r.json()["id"], r.json()["token"]
assert A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": AG, "role": "edit"}).ok
cl = Api(AGTOK)
cur = cl.get("/agent").json()["cursor"]
F = Bo.post(B + "/api/tasks", json={"title": "Ping the tax office", "list_id": TEAM}).json()["id"]
cl_c = requests.post(V + f"/tasks/{F}/comments", headers={"Authorization": "Bearer " + AGTOK}, json={"body": "I will keep an eye on it"})
check(cl_c.status_code == 201, "the agent comments (follows the task)")
Bo.patch(B + "/api/settings", json={"allday_time": "00:00"})
time.sleep(3.2)
clear()
Bo.put(B + f"/api/tasks/{F}/waiting", json={"note": "tax office", "until": date.today().isoformat()})
p = settle(bphone.notes, 8)
check(len(p) == 1 and p[0]["title"] == "Follow up: Ping the tax office" and "tax office" in p[0]["body"], f"follow-up push: {p}")
fn = news(Bo, "followup")
check(len(fn) == 1 and fn[0]["task_id"] == F, f"follow-up News: {fn}")
evs = []
for _ in range(20):
    evs = [e for e in cl.get("/agent/events", params={"since": cur}).json().get("data", []) if e["event"] == "followup_due"]
    if evs:
        break
    time.sleep(0.4)
check(len(evs) == 1 and evs[0]["data"]["task"]["id"] == F and evs[0]["data"]["waiting"]["note"] == "tax office"
      and evs[0]["data"]["task"]["comments"], f"agent event followup_due: {evs[:1]}")
time.sleep(2.5)
check(len(settle(bphone.notes, 3)) == 1 and len(news(Bo, "followup")) == 1, "fires once per date")
check("followup_due" in cl.get("/agent").json().get("events", []), "the agent's event list names followup_due")
Bo.patch(B + "/api/settings", json={"allday_time": "09:00"})

# ================================================================== #180 Paperless connections
BTOK, PTOK, BTOK2 = "bob-server-token-8f1d", "bob-personal-token-77aa", "bob-server-token-NEW2"
c = A.get(B + "/api/paperless/conns").json()
check(c["key"] and [x["id"] for x in c["conns"]] == [0] and c["conns"][0]["kind"] == "legacy", f"admin: the legacy connection: {c}")
check(Bo.get(B + "/api/paperless/conns").json()["conns"] == [], "bob: none")
check(Bo.get(B + "/api/paperless/search", params={"conn": 0}).status_code == 403, "bob: no legacy access")
check(A.get(B + "/api/paperless/search").ok, "legacy works (no conn = 0)")
r = A.post(B + "/api/admin/paperless", json={"name": "Office", "url": "http://127.0.0.1:8082/api/", "users": [ids["bob"]]})
SRV = r.json()["id"]
check(r.status_code == 201 and r.json()["url"] == "http://127.0.0.1:8082" and r.json()["users"] == [ids["bob"]], f"server connection: {r.text}")
check(A.post(B + "/api/admin/paperless", json={"name": "x", "url": "ftp://x"}).status_code == 400, "bad URL 400")
check(Bo.post(B + "/api/admin/paperless", json={"name": "x", "url": "https://x.example"}).status_code == 403, "not an admin 403")
check(A.post(B + "/api/admin/paperless", json={"name": "x", "url": "https://x.example", "users": [AG]}).status_code == 400, "an agent cannot be granted")
bc = Bo.get(B + "/api/paperless/conns").json()["conns"]
check([(x["id"], x["token_set"], x["usable"]) for x in bc] == [(SRV, False, False)], f"bob sees it, no token yet: {bc}")
check(Bo.get(B + "/api/paperless/search", params={"conn": SRV}).status_code == 403, "no token: 403")
check(Ge.patch(B + f"/api/paperless/conns/{SRV}", json={"token": "x"}).status_code == 404, "gert (not granted) cannot set a token")
r = Bo.patch(B + f"/api/paperless/conns/{SRV}", json={"token": BTOK})
check(r.ok and r.json()["token_set"] and r.json()["usable"], "bob sets his token")
check(Bo.patch(B + f"/api/paperless/conns/{SRV}", json={"name": "Mine now"}).status_code == 400, "a user cannot rename a server connection")
open(os.path.join(DATA, "fake.log"), "w").close()
r = Bo.get(B + "/api/paperless/search", params={"conn": SRV, "q": "tax"})
check(r.ok and r.json()["items"] and r.json()["conn"] == SRV, "bob searches with his token")
auths = {x["auth"] for x in fake_log()}
check(auths == {"Token " + BTOK}, f"only bob's token went out: {auths}")
check(Bo.get(B + f"/api/paperless/thumb/7", params={"conn": SRV}).status_code == 502, "thumbnail type guard still applies")
check(Bo.get(B + f"/api/paperless/thumb/8", params={"conn": SRV}).ok, "thumbnail")
# personal connection: internal address blocked until an admin allows the host
r = Bo.post(B + "/api/paperless/conns", json={"name": "Private", "url": "http://127.0.0.1:8082", "token": PTOK})
PER = r.json()["id"]
check(r.status_code == 201 and r.json()["kind"] == "personal" and r.json()["usable"], f"personal connection: {r.text}")
check(Bo.post(B + "/api/paperless/conns", json={"name": "x", "url": "http://127.0.0.1:8082"}).status_code == 400, "a token is needed")
r = Bo.get(B + "/api/paperless/search", params={"conn": PER})
check(r.status_code == 502 and "internal" in r.json()["error"], f"SSRF guard: {r.text[:200]}")
A.patch(B + "/api/admin/settings", json={"cal_allow_hosts": "127.0.0.1:8082"})
open(os.path.join(DATA, "fake.log"), "w").close()
r = Bo.get(B + "/api/paperless/search", params={"conn": PER})
check(r.ok and {x["auth"] for x in fake_log()} == {"Token " + PTOK}, f"allowed host: bob's personal token only: {r.status_code}")
# nobody else sees or uses it
ac = [x["id"] for x in A.get(B + "/api/paperless/conns").json()["conns"]]
check(PER not in ac and SRV not in ac, f"alice (admin) does not see bob's connections: {ac}")
adm = A.get(B + "/api/admin/paperless").json()
check([x["id"] for x in adm["servers"]] == [SRV] and adm["servers"][0]["tokens"] == 1 and "Private" not in json.dumps(adm), "admin API: server only, no personal")
for s_, who in ((A, "alice"), (Ge, "gert")):
    check(s_.get(B + "/api/paperless/search", params={"conn": PER}).status_code == 403, f"{who} cannot search bob's personal connection")
    check(s_.patch(B + f"/api/paperless/conns/{PER}", json={"token": "hijack"}).status_code == 404, f"{who} cannot set a token on it")
    check(s_.delete(B + f"/api/paperless/conns/{PER}").status_code == 404, f"{who} cannot delete it")
    check(s_.post(B + f"/api/paperless/conns/{PER}/test").status_code == 404, f"{who} cannot test it")
check(A.patch(B + f"/api/admin/paperless/{PER}", json={"users": [1]}).status_code == 404, "admin cannot grant a personal connection")
check(A.delete(B + f"/api/admin/paperless/{PER}").status_code == 404, "admin cannot delete a personal connection")
check(Bo.delete(B + f"/api/paperless/conns/{SRV}").status_code == 403, "a user cannot delete a server connection")
check(Bo.post(B + f"/api/paperless/conns/{PER}/test").json()["ok"], "test: ok")
# links remember their connection
r = Bo.post(B + f"/api/tasks/{BT}/paperless", json={"doc_id": 11, "conn": PER})
pl = r.json()["paperless"]
check(r.ok and pl[0]["title"] == "Secret doc 11" and pl[0]["conn"] == PER, f"bob links through his personal connection: {pl}")
ap = next(t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == BT)["paperless"]
check(ap[0]["hidden"] and ap[0]["title"] == "Paperless document" and ap[0]["conn"] is None and ap[0]["doc_id"] is None, f"alice sees only that there is one: {ap}")
check(A.delete(B + f"/api/paperless-links/{ap[0]['id']}").status_code == 403, "alice cannot remove bob's link")
r = A.post(B + f"/api/tasks/{BT}/paperless", json={"doc_id": 3})
check(r.ok and any(x["conn"] == 0 and x["title"] == "Secret doc 3" for x in r.json()["paperless"]), "legacy link (conn 0)")
bp = next(t for t in Bo.get(B + "/api/state").json()["tasks"] if t["id"] == BT)["paperless"]
check(any(x.get("hidden") for x in bp) and any(x["title"] == "Secret doc 11" for x in bp), "bob: his link visible, the legacy one hidden")
ex = A.get(B + "/api/export.json").text
check("Secret doc 11" not in ex, "alice's export: no title of bob's document")
bex = json.loads(Bo.get(B + "/api/export.json").text)
check({x["name"] for x in bex["paperless_connections"]} == {"Office", "Private"} and "token" not in json.dumps(bex["paperless_connections"]).replace("token_set", ""),
      "bob's export: his connections, no tokens")
hist = Bo.get(B + f"/api/tasks/{BT}/timeline").json()
check(any(a["kind"] == "paperless" and a["data"].get("title") == "Secret doc 11" for a in hist.get("activity", [])), "history: bob sees the title")
ah = A.get(B + f"/api/tasks/{BT}/timeline").json()
check(not any(a["data"].get("title") == "Secret doc 11" for a in ah.get("activity", [])), "history: alice does not")
# never a token in any answer or page, never plaintext in the database
for pth in ("/", "/api/state", "/api/me", "/api/admin/paperless", "/api/paperless/conns", "/api/export.json"):
    for s_ in (A, Bo):
        s_.get(B + pth)
Api(tok).get("/me")
leak = [t for t in (BTOK, PTOK, "pl-legacy-env-token", KEY) if any(t in x for x in SEEN)]
check(not leak, f"no token in any answer: {leak}")
raw = open(os.path.join(DATA, "tasks.db"), "rb").read() + b"".join(open(os.path.join(DATA, f), "rb").read() for f in os.listdir(DATA) if f.startswith("tasks.db-"))
check(BTOK.encode() not in raw and PTOK.encode() not in raw and KEY.encode() not in raw, "tokens + key not in the database files")
db = sqlite3.connect(os.path.join(DATA, "tasks.db"))
toks = [r[0] for r in db.execute("SELECT token FROM pl_tokens")]
db.close()
check(len(toks) == 2 and all(t.startswith("v1.") for t in toks), f"sealed at rest: {len(toks)}")
check(not any(KEY in open(os.path.join(dp, f), "rb").read().decode("latin-1") for dp, _, fs in os.walk(DATA) for f in fs), "the key is nowhere in the data dir")
# admin: a new address drops the tokens; taking bob off drops his
A.patch(B + f"/api/admin/paperless/{SRV}", json={"url": "http://127.0.0.1:8082/other"})
bc = {x["id"]: x for x in Bo.get(B + "/api/paperless/conns").json()["conns"]}
check(not bc[SRV]["token_set"], "a new address dropped the token")
A.patch(B + f"/api/admin/paperless/{SRV}", json={"url": "http://127.0.0.1:8082"})
Bo.patch(B + f"/api/paperless/conns/{SRV}", json={"token": BTOK2})
A.patch(B + f"/api/admin/paperless/{SRV}", json={"users": []})
check(SRV not in [x["id"] for x in Bo.get(B + "/api/paperless/conns").json()["conns"]], "access taken away")
db = sqlite3.connect(os.path.join(DATA, "tasks.db"))
check(db.execute("SELECT COUNT(*) FROM pl_tokens WHERE conn_id=?", (SRV,)).fetchone()[0] == 0, "... and his token deleted")
db.close()
A.patch(B + f"/api/admin/paperless/{SRV}", json={"users": [ids["bob"]]})
Bo.patch(B + f"/api/paperless/conns/{SRV}", json={"token": BTOK2})
check(Bo.delete(B + f"/api/paperless/conns/{SRV}/token").ok and not {x["id"]: x for x in Bo.get(B + "/api/paperless/conns").json()["conns"]}[SRV]["token_set"],
      "bob removes his token")
Bo.patch(B + f"/api/paperless/conns/{SRV}", json={"token": BTOK2})

# ---- without the key: nothing can be stored, stored tokens are unusable, the legacy connection keeps working
start(with_key=False, keep=True)
A, Bo = sess("alice"), sess("bob")
c = Bo.get(B + "/api/paperless/conns").json()
check(not c["key"] and all(not x["usable"] and x["token_set"] and not x["token_ok"] for x in c["conns"]), f"no key: tokens unusable: {c}")
r = Bo.post(B + "/api/paperless/conns", json={"name": "New", "url": "https://p.example", "token": "abc"})
check(r.status_code == 409 and "KALMIDO_SECRET_KEY" in r.json()["error"], f"no key: 409 + hint: {r.text[:160]}")
check(Bo.patch(B + f"/api/paperless/conns/{SRV}", json={"token": "abc"}).status_code == 409, "no key: a token cannot be set")
check(A.get(B + "/api/admin/paperless").json()["key"] is False, "admin sees the missing key")
check(A.get(B + "/api/paperless/search").ok, "legacy connection still works without the key")
# the key back: the stored tokens work again
start(with_key=True, keep=True)
Bo = sess("bob")
check(Bo.get(B + "/api/paperless/search", params={"conn": SRV}).ok, "the key back: the stored token works again")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
