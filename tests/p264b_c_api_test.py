#!/usr/bin/env python3
"""2.64.2 API tests, parts C + D (#1817: the lock per list, stage 2), own container (start.sh). Invented names only. The server
never sees a list key; the tests send ciphertext-shaped values.
 - the list channel of a list with the lock: plain text 409, a ciphertext {v, g, iv, ct} of the list key ok (generation <= current),
   a wrong shape 400, an open channel refuses one, editing re-encrypts, mentions named by the browser push, the push has no text
 - agents / API tokens: reading gives no ciphertext and no text (encrypted: true), writing is refused
 - search finds nothing in the channel, a message cannot be saved as a task
 - le2c_left / le2c_bulk through the conversion of switching the lock off (decrypting) and on again (encrypting)
 - pushes of a list with the lock: the neutral word in the language of the recipient, a comment push names the list, not the words
usage: p264b_c_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sess(user=None):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": "password123"})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def ct(gen=1, n=48):
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(n)}, separators=(",", ":"))


def chan(gen=1):
    """A channel ciphertext (shape only)."""
    return {"v": 1, "g": gen, "iv": b64(12), "ct": b64(64)}


def wrapped():
    return {"v": 1, "iv": b64(12), "ct": b64(48)}


def keys():
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}


def code(r):
    try:
        return r.json().get("code")
    except ValueError:
        return None


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def clear():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


def until(fn, t=6.0):
    end = time.time() + t
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return fn()


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"features": "collab,agents,comments,api", "lang": "en", "tour": "done"})
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
U = {}
for name in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", "ntfy_topic": "t-" + name})
    assert r.ok, r.text
    U[name] = r.json()["id"]
BOB, CAROL = U["bob"], U["carol"]
Bo, Ca = sess("bob"), sess("carol")
Bo.patch(B + "/api/settings", json={"lang": "de", "tour": "done", "features": "collab,comments,api"})  # the recipient speaks German
Ca.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments"})
assert A.put(B + "/api/e2e/keys", json=keys()).ok
assert Bo.put(B + "/api/e2e/keys", json=keys()).ok
L = A.post(B + "/api/lists", json={"name": "Garden"}).json()["id"]
LO = A.post(B + "/api/lists", json={"name": "Open"}).json()["id"]
for lid in (L, LO):
    assert A.put(B + f"/api/lists/{lid}/members", json={"user_id": BOB, "role": "edit"}).ok
# a plain message in the channel before the lock (converted when the lock goes on)
rooms = {r["list_id"]: r["id"] for r in A.get(B + "/api/team").json()["rooms"] if r["kind"] == "list"}
RID, RO = rooms[L], rooms[LO]
M0 = A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Before the lock"}).json()["id"]

# switching on: start, todo (texts + the message), bulk, finish
r = A.post(B + f"/api/lists/{L}/e2e/start", json={"keys": [{"user_id": 1, "wrapped": wrapped()}, {"user_id": BOB, "wrapped": wrapped()}]})
assert r.ok, r.text
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(1)})
check(r.status_code == 409, "channel: no message while the list is being encrypted " + r.text[:200])
j = A.get(B + f"/api/lists/{L}/e2e/todo").json()
check([m["id"] for m in j.get("msgs", [])] == [M0] and j["msgs"][0]["body"] == "Before the lock" and j["left"].get("msgs") == 1,
      "todo: the plain channel message is to do " + json.dumps(j)[:300])
check(A.post(B + f"/api/lists/{L}/e2e/finish").status_code == 409, "finish: not while a message is plain")
r = A.post(B + f"/api/lists/{L}/e2e/bulk", json={"msgs": [{"id": M0, "enc": chan(2)}]})
check(r.status_code == 400, "bulk: a message of another generation is refused")
r = A.post(B + f"/api/lists/{L}/e2e/bulk", json={"msgs": [{"id": M0, "enc": chan(1)}]})
check(r.ok, "bulk: the message encrypted " + r.text[:200])
check(dbx("SELECT body, enc FROM tchat_msgs WHERE id=?", (M0,))[0][0] == "" and '"g":1' in dbx("SELECT enc FROM tchat_msgs WHERE id=?", (M0,))[0][0],
      "bulk: the server keeps only the ciphertext")
r = A.post(B + f"/api/lists/{L}/e2e/finish")
check(r.ok, "finish: on " + r.text[:200])

# ================================================================== the channel of a list with the lock
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "plain words"})
check(r.status_code == 409, "channel: plain text refused " + r.text[:200])
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": {"v": 1, "iv": b64(12), "ct": b64(32)}})
check(r.status_code == 400, "channel: a DM-shaped ciphertext (no generation) refused")
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(2)})
check(r.status_code == 400, "channel: a generation the list does not have refused")
clear()
r = A.post(B + f"/api/team/rooms/{RID}/messages", json={"enc": chan(1), "mentions": [BOB, 999]})
check(r.status_code == 201 and r.json()["enc"]["g"] == 1 and r.json()["body"] == "", "channel: a ciphertext of the list key " + r.text[:200])
M1 = r.json().get("id")
p = until(lambda: [x for x in pushes() if x.get("topic") == "t-bob"])
check(p and "Before" not in json.dumps(p) and "Neue Nachricht von Alice" in json.dumps(p, ensure_ascii=False),
      "push: the mentioned member is told who wrote, no text, in his language " + json.dumps(p, ensure_ascii=False)[:300])
r = A.post(B + f"/api/team/rooms/{RO}/messages", json={"enc": chan(1)})
check(r.status_code == 409, "open channel: a ciphertext refused")
j = Bo.get(B + f"/api/team/rooms/{RID}/messages").json()
check(j["room"].get("list_e2e") == "on" and j["room"].get("gen") == 1 and all(m["enc"] and m["enc"].get("g") == 1 for m in j["messages"]),
      "read in the app: the room says the lock, every message a ciphertext with its generation")
check([x for x in Bo.get(B + "/api/team").json()["rooms"] if x["id"] == RID][0].get("list_e2e") == "on", "room list: the lock of the channel")
r = A.patch(B + f"/api/team/messages/{M1}", json={"body": "changed in plain"})
check(r.status_code == 409, "edit: plain text refused")
r = A.patch(B + f"/api/team/messages/{M1}", json={"enc": chan(1)})
check(r.ok and r.json()["edited_at"], "edit: encrypted again")
check(Bo.patch(B + f"/api/team/messages/{M1}", json={"enc": chan(1)}).status_code == 403, "edit: only the sender")

# agents / API tokens
r = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]})
check(r.status_code == 201, "API token " + r.text[:200])
TH = {"Authorization": "Bearer " + r.json()["token"]}
r = requests.get(B + f"/api/v1/team/rooms/{RID}/messages", headers=TH)
d = r.json() if r.ok else {}
check(r.ok and d["data"] and all(m["enc"] is None and m["body"] == "" and m.get("encrypted") is True for m in d["data"]),
      "API: no ciphertext, no text, encrypted: true " + r.text[:300])
r = requests.post(B + f"/api/v1/team/rooms/{RID}/messages", headers=TH, json={"body": "from a script"})
check(r.status_code in (403, 409), "API: writing into the channel refused " + r.text[:200])
r = requests.post(B + f"/api/v1/team/messages/{M1}/reactions", headers=TH, json={"emoji": "up"})
check(r.status_code == 403, "API: no reactions in the channel of a list with the lock")
check(requests.post(B + f"/api/v1/team/rooms/{RO}/messages", headers=TH, json={"body": "open list"}).status_code == 201, "API: an open channel works as before")

# search (also a plain leftover of 2.64.1 in the channel), save as a task
dbx("INSERT INTO tchat_msgs(room_id,user_id,body,created_at) VALUES(?,?,?,?)", (RID, 1, "Leftover words", "2026-10-17T05:00:00.000Z"))
A.post(B + f"/api/team/rooms/{RO}/messages", json={"body": "Leftover words in the open list"})
r = A.get(B + "/api/search/messages", params={"q": "Leftover"})
hits = r.json().get("hits", []) if r.ok else []
check(r.ok and hits and not [h for h in hits if h.get("room_id") == RID], "search: the open channel yes, the locked one never " + r.text[:300])
dbx("DELETE FROM tchat_msgs WHERE room_id=? AND body=?", (RID, "Leftover words"))
r = A.post(B + "/api/chat-save", json={"kind": "team", "msg_id": M1, "list_id": LO})
check(r.status_code in (400, 404, 409), "save as task: refused for an encrypted message " + str(r.status_code))

# ================================================================== the way back converts the channel too
r = A.post(B + f"/api/lists/{L}/e2e/stop", json={"password": "password123"})
check(r.ok, "stop: decrypting " + r.text[:200])
j = A.get(B + f"/api/lists/{L}/e2e/todo").json()
ids = sorted(m["id"] for m in j.get("msgs", []))
check(M0 in ids and M1 in ids and all(m["enc"] and m["enc"]["g"] == 1 for m in j["msgs"]), "todo decrypting: the ciphertexts of the channel")
r = A.post(B + f"/api/lists/{L}/e2e/bulk", json={"msgs": [{"id": i, "body": f"plain {i}"} for i in ids]})
check(r.ok, "bulk decrypting: plain texts " + r.text[:200])
r = A.post(B + f"/api/lists/{L}/e2e/finish")
check(r.ok and dbx("SELECT COUNT(*) FROM tchat_msgs WHERE room_id=? AND enc IS NOT NULL", (RID,))[0][0] == 0, "finish: open, no ciphertext left in the channel")
check(A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "open again"}).status_code == 201, "open again: plain messages")

# ================================================================== pushes of a list with the lock (part D)
L2 = A.post(B + "/api/lists", json={"name": "Roses"}).json()["id"]
assert A.put(B + f"/api/lists/{L2}/members", json={"user_id": BOB, "role": "edit"}).ok
T = A.post(B + "/api/tasks", json={"title": "Cut the roses", "list_id": L2}).json()["id"]  # no assignment push before (burst gate)
assert A.post(B + f"/api/lists/{L2}/e2e/start", json={"keys": [{"user_id": 1, "wrapped": wrapped()}, {"user_id": BOB, "wrapped": wrapped()}]}).ok
j = A.get(B + f"/api/lists/{L2}/e2e/todo").json()
assert A.post(B + f"/api/lists/{L2}/e2e/bulk", json={"tasks": [{"id": x["id"], **{k: ct(1) for k in ("title", "content", "url") if x.get(k)}} for x in j["tasks"]],
                                                     "msgs": [{"id": m["id"], "enc": chan(1)} for m in j.get("msgs", [])]}).ok
assert A.post(B + f"/api/lists/{L2}/e2e/finish").ok, A.get(B + f"/api/lists/{L2}/e2e/todo").text
clear()
r = A.post(B + f"/api/tasks/{T}/comments", json={"body": ct(1), "mentions": [BOB]})
check(r.status_code in (200, 201), "comment: a ciphertext " + r.text[:200])
p = until(lambda: [x for x in pushes() if x.get("topic") == "t-bob"])
s = json.dumps(p, ensure_ascii=False)
check(p and "e2e1:" not in s and "Alice hat dich in Roses erwähnt" in s, "comment push: names the list, not the words, in German " + s[:300])
check(p and "🔒 Aufgabe" in s, "comment push: the neutral title in the recipient's language " + s[:300])

print(f"p264b_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
