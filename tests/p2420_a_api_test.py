#!/usr/bin/env python3
"""2.42.0 API tests, part A (end-to-end encryption in the browser), own container (start.sh). Invented names only.
The server only stores what the browser encrypted; these tests send ciphertext-shaped values (the real WebCrypto round
trips are in p2420_a_ui.js).
 - #828 keys: GET/PUT/DELETE /api/e2e/keys only for the person (agents 403), the shape is checked (no private key part,
   PBKDF2 >= 600 000 rounds), re-wrapping keeps the public key, a different public key = 409
 - #828 note: /api/tasks/{id}/enc-note only for its author; the task carries encrypted_note (+ _mine for the author) in the
   app, the REST API and the agent's view, never the ciphertext; a copy of the task has no note
 - #828 files: /api/tasks/{id}/enc-attachments takes only the KENC format; the file is enc / enc_mine, only its uploader
   downloads it (as a download), no text for anybody, agents get 404 and see it as encrypted
 - #909 DMs: /api/e2e/pub/{id} only for people I may write to; switching a DM on needs both keys; an encrypted DM refuses
   plain text (and a plain room ciphertext); messages carry enc, body stays empty; edit = new ciphertext; the push says only
   "New message from ..."; search and "save as task" never see it; the switch leaves a notice in the conversation
usage: p2420_a_api_test.py <datadir>"""
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

from kt import FAILS, OKS, check, sess, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
LOCAL = os.environ.get("P2420A_NOSTART") == "1"  # against a container started by hand (no push stub)


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def blob(n=48):
    return {"v": 1, "iv": b64(12), "ct": b64(n)}


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def keys():
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}


class Api:
    def __init__(self, token):
        self.h = {"Authorization": "Bearer " + token}

    def __getattr__(self, m):
        return lambda path, **kw: requests.request(m.upper(), B + "/api/v1" + path, headers=self.h, **kw)


if not LOCAL:
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"features": "collab,agents,comments", "lang": "en", "tour": "done"})
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
ids = {"alice": 1}
for u, n in (("bob", "Bob"), ("zed", "Zed")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Z = sess("bob"), sess("zed")
for s in (Bo, Z):
    s.patch(B + "/api/settings", json={"features": "collab,agents,comments", "lang": "en", "tour": "done"})
L = A.post(B + "/api/lists", json={"name": "Office"}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "edit"}).ok
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"}).json()
AG = Api(ag["token"])
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ag["id"], "role": "edit"}).ok
T = A.post(B + "/api/tasks", json={"title": "Contract draft", "list_id": L}).json()["id"]

# ================================================================== keys
# 2.42.0 review: GET also says whether changing / removing the keys asks for the account password
check(A.get(B + "/api/e2e/keys").json() == {"set": False, "password": True}, "keys: none yet")
check(requests.get(B + "/api/e2e/keys", headers=H).status_code in (401, 403), "keys: not without login")
AGH = {"Authorization": "Bearer " + ag["token"]}
check(requests.get(B + "/api/e2e/keys", headers=AGH).status_code in (401, 403, 404), "keys: an agent token gets nothing")
ka = keys()
bad = dict(ka, pub=dict(ka["pub"], d=b64u(32)))
check(A.put(B + "/api/e2e/keys", json=bad).status_code == 400, "keys: a private key part is refused")
bad = dict(ka, bundle_pass=dict(ka["bundle_pass"], iter=1000))
check(A.put(B + "/api/e2e/keys", json=bad).status_code == 400, "keys: too few PBKDF2 rounds are refused")
bad = dict(ka, bundle_rec=ka["bundle_pass"])
check(A.put(B + "/api/e2e/keys", json=bad).status_code == 400, "keys: the recovery bundle must use HKDF")
r = A.put(B + "/api/e2e/keys", json=ka)
check(r.ok and r.json().get("created") is True, "keys: set up " + r.text[:200])
g = A.get(B + "/api/e2e/keys").json()
check(g["set"] and g["pub"]["x"] == ka["pub"]["x"] and g["bundle_pass"]["ct"] == ka["bundle_pass"]["ct"] and "d" not in g["pub"],
      "keys: read back (public key + wrapped bundles)")
k2 = dict(keys(), pub=ka["pub"])
# 2.42.0 review: replacing existing keys needs the account password (each refusal counts like a failed login: few of them here)
check(A.put(B + "/api/e2e/keys", json=k2).status_code == 403 and A.put(B + "/api/e2e/keys", json=dict(k2, password="wrong")).status_code == 403
      and A.get(B + "/api/e2e/keys").json()["bundle_pass"]["ct"] == ka["bundle_pass"]["ct"], "keys: re-wrap without / with a wrong password refused")
r = A.put(B + "/api/e2e/keys", json=dict(k2, password="password123"))
check(r.ok and r.json().get("created") is False and A.get(B + "/api/e2e/keys").json()["bundle_pass"]["ct"] == k2["bundle_pass"]["ct"],
      "keys: re-wrapped (new passphrase) with the same public key")
check(A.put(B + "/api/e2e/keys", json=keys()).status_code == 409, "keys: another public key while keys exist = 409")
# repair (the browser found that the stored public key is not the one of its bundle): the bundle's key again, with the password
k3 = dict(k2, pub=keys()["pub"])
r = A.put(B + "/api/e2e/keys", json=dict(k3, repair=True, password="password123"))
check(r.ok and A.get(B + "/api/e2e/keys").json()["pub"]["x"] == k3["pub"]["x"], "keys: repair stores the public key again " + r.text[:150])
r = A.put(B + "/api/e2e/keys", json=dict(k2, repair=True, password="password123"))
check(r.ok and A.get(B + "/api/e2e/keys").json()["pub"]["x"] == ka["pub"]["x"], "keys: and back")
check(Bo.get(B + "/api/e2e/keys").json() == {"set": False, "password": True}, "keys: per person")
r = AG.get("/tasks/%d" % T)
check(r.ok, "agent: sees the task (set-up)")

# ================================================================== #828 note
check(A.get(B + f"/api/tasks/{T}/enc-note").status_code == 404, "note: none yet")
check(Bo.put(B + f"/api/tasks/{T}/enc-note", json={"body": blob()}).status_code == 409, "note: needs own keys")
check(A.put(B + f"/api/tasks/{T}/enc-note", json={"body": "secret text"}).status_code == 400, "note: plain text is refused")
check(A.put(B + f"/api/tasks/{T}/enc-note", json={"body": {"v": 1, "iv": "x", "ct": "y"}}).status_code == 400, "note: a broken ciphertext is refused")
nb = blob(120)
r = A.put(B + f"/api/tasks/{T}/enc-note", json={"body": nb})
check(r.ok, "note: written " + r.text[:200])
r = A.get(B + f"/api/tasks/{T}/enc-note")
check(r.ok and r.json()["body"] == nb, "note: its author reads it back")
check(Bo.get(B + f"/api/tasks/{T}/enc-note").status_code == 404, "note: another member cannot read it")
check(Z.get(B + f"/api/tasks/{T}/enc-note").status_code == 404 and Z.put(B + f"/api/tasks/{T}/enc-note", json={"body": blob()}).status_code == 404,
      "note: someone without the task gets 404")
check(Bo.delete(B + f"/api/tasks/{T}/enc-note").json().get("removed") is False and A.get(B + f"/api/tasks/{T}/enc-note").ok,
      "note: another member cannot delete it")
st = A.get(B + "/api/state").json()
ta = next(t for t in st["tasks"] if t["id"] == T)
check(ta.get("encrypted_note") is True and ta.get("encrypted_note_mine") is True, "note: the author's task says encrypted_note + mine")
tb = next(t for t in Bo.get(B + "/api/state").json()["tasks"] if t["id"] == T)
check(tb.get("encrypted_note") is True and not tb.get("encrypted_note_mine"), "note: the other member only sees that there is one")
check(nb["ct"] not in json.dumps(st) and nb["ct"] not in json.dumps(Bo.get(B + "/api/state").json()), "note: the ciphertext is not in the state")
r = AG.get(f"/tasks/{T}")
check(r.ok and r.json().get("encrypted_note") is True and nb["ct"] not in r.text, "note: the agent's REST view: encrypted_note only " + r.text[:300])
check(requests.get(B + f"/api/tasks/{T}/enc-note", headers=AGH).status_code in (401, 403, 404), "note: an agent cannot load it")
rows = dbx("SELECT body FROM task_enc_notes WHERE task_id=?", (T,))
check(len(rows) == 1 and "secret" not in rows[0][0] and json.loads(rows[0][0])["ct"] == nb["ct"], "note: the database holds only the ciphertext")
check(A.delete(B + f"/api/tasks/{T}/enc-note").json().get("removed") is True and A.get(B + f"/api/tasks/{T}/enc-note").status_code == 404,
      "note: the author deletes it")
A.put(B + f"/api/tasks/{T}/enc-note", json={"body": nb})

# ================================================================== #828 files
plain = b"%PDF-1.4 plain text inside\n"
r = A.post(B + f"/api/tasks/{T}/enc-attachments", files={"file": ("x.pdf", plain, "application/pdf")})
check(r.status_code == 400, "file: an unencrypted file is refused " + r.text[:120])
enc = b"KENC\x01" + os.urandom(400)
r = Bo.post(B + f"/api/tasks/{T}/enc-attachments", files={"file": ("blob", enc, "application/octet-stream")})
check(r.status_code == 409, "file: needs own keys")
r = A.post(B + f"/api/tasks/{T}/enc-attachments", files={"file": ("contract.pdf", enc, "application/pdf")})
check(r.ok, "file: uploaded " + r.text[:200])
att = [a for a in r.json()["attachments"] if a.get("enc")]
check(len(att) == 1 and att[0]["enc_mine"] and att[0]["mime"] == "application/octet-stream" and "contract" not in att[0]["name"],
      f"file: enc + mine, neutral name and type {att}")
AID = att[0]["id"]
r = A.get(B + f"/api/attachments/{AID}")
check(r.ok and r.content == enc and "attachment" in r.headers.get("Content-Disposition", ""), "file: the uploader downloads the blob (as a download)")
check(Bo.get(B + f"/api/attachments/{AID}").status_code == 404, "file: another member cannot download it")
tb = next(t for t in Bo.get(B + "/api/state").json()["tasks"] if t["id"] == T)
check(any(a["id"] == AID and a.get("enc") and not a.get("enc_mine") for a in tb["attachments"]), "file: the other member sees an encrypted file")
check(AG.get(f"/attachments/{AID}").status_code == 404, "file: an agent cannot download it")
check(AG.get(f"/attachments/{AID}/text").status_code == 404 and A.get(B + f"/api/v1/attachments/{AID}/text").status_code in (401, 403, 404),
      "file: no text extraction")
r = AG.get(f"/tasks/{T}/attachments")
check(r.ok and any(x["id"] == AID and x.get("encrypted") for x in r.json()["data"]), "file: the agent's list marks it encrypted")

# ================================================================== #909 DMs
check(Z.get(B + f"/api/e2e/pub/{ids['alice']}").status_code == 404, "pub: not for someone I do not work with")
r = Bo.get(B + f"/api/e2e/pub/{ids['alice']}")
check(r.ok and r.json()["pub"]["x"] == ka["pub"]["x"], "pub: a co-worker gets the public key")
check(A.get(B + f"/api/e2e/pub/{ids['bob']}").json()["pub"] is None, "pub: null while not set up")
DM = A.post(B + "/api/team/dm", json={"user_id": ids["bob"]}).json()["id"]
r = A.post(B + f"/api/team/rooms/{DM}/e2e", json={"on": True})
check(r.status_code == 409 and "Bob" in r.json().get("error", ""), "dm: switching on needs the other one's keys " + r.text[:200])
kb = keys()
assert Bo.put(B + "/api/e2e/keys", json=kb).ok
check(A.post(B + f"/api/team/rooms/{DM}/e2e", json={"on": "yes"}).status_code == 400, "dm: on must be a boolean")
check(A.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "before"}).status_code == 201, "dm: plain before switching")
check(A.post(B + f"/api/team/rooms/{DM}/messages", json={"enc": blob()}).status_code == 409, "dm: a plain room refuses ciphertext")
r = Bo.post(B + f"/api/team/rooms/{DM}/e2e", json={"on": True})
check(r.ok and r.json()["e2e"] is True, "dm: either person switches it on")
j = A.get(B + f"/api/team/rooms/{DM}/messages").json()
check(j["room"]["e2e"] is True and j["messages"][-1]["enc"] == {"sys": "on"} and j["messages"][-1]["user_id"] == ids["bob"],
      "dm: the room says e2e; a notice in the conversation")
check(A.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "plain secret"}).status_code == 409, "dm: plain text refused in an encrypted DM")
check(A.post(B + f"/api/team/rooms/{DM}/messages", json={"enc": {"v": 2, "iv": b64(12), "ct": b64(40)}}).status_code == 400, "dm: unknown version refused")
if not LOCAL:
    open(os.path.join(DATA, "ntfy.log"), "w").close()
mb = blob(64)
r = A.post(B + f"/api/team/rooms/{DM}/messages", json={"enc": mb, "body": ""})
check(r.status_code == 201 and r.json()["body"] == "" and r.json()["enc"] == mb, "dm: an encrypted message " + r.text[:200])
MID = r.json()["id"]
j = Bo.get(B + f"/api/team/rooms/{DM}/messages").json()
check(any(m["id"] == MID and m["enc"] == mb and m["body"] == "" for m in j["messages"]), "dm: the other one gets the ciphertext")
rooms = Bo.get(B + "/api/team").json()["rooms"]
rr = next(x for x in rooms if x["id"] == DM)
check(rr["e2e"] is True and rr["last"]["enc"] == "msg" and rr["last"]["text"] == "", "dm: the conversation list shows no text, says encrypted")
if not LOCAL:
    time.sleep(1.5)
    ps = [p for p in pushes() if p.get("topic") == "t-bob"]
    check(ps and all("New message from Alice" in (p.get("msg") or p.get("message") or "") for p in ps) and not any(mb["ct"] in json.dumps(p) for p in ps),
          f"dm: the push only says who wrote {ps}")
r = Bo.post(B + f"/api/team/rooms/{DM}/messages", json={"enc": blob(), "reply_to": MID})
check(r.status_code == 201 and r.json()["reply"]["enc"] is True and r.json()["reply"]["text"] == "", "dm: a reply quote is marked encrypted")
r = A.patch(B + f"/api/team/messages/{MID}", json={"body": "edited plain"})
check(r.status_code in (400, 409), "dm: editing with plain text is refused")
nb2 = blob(70)
r = A.patch(B + f"/api/team/messages/{MID}", json={"enc": nb2})
check(r.ok and r.json()["enc"] == nb2 and r.json()["edited_at"], "dm: edit = new ciphertext")
check(A.post(B + "/api/chat-save", json={"kind": "team", "msg_id": MID}).status_code == 404, "dm: an encrypted message cannot be saved as a task")
r = A.get(B + "/api/search/messages", params={"q": "plain"})
check(r.ok and not any(h.get("id") == MID for h in r.json()["hits"]), "dm: search never finds encrypted messages " + r.text[:200])
rows = dbx("SELECT body, enc FROM tchat_msgs WHERE id=?", (MID,))
check(rows[0][0] == "" and json.loads(rows[0][1])["ct"] == nb2["ct"], "dm: the database holds only the ciphertext")
check(A.post(B + f"/api/team/messages/{MID}/reactions", json={"emoji": "up"}).status_code == 400
      and Bo.post(B + f"/api/team/messages/{MID}/reactions", json={"emoji": "up"}).ok, "dm: reactions as before")
L2 = [x for x in A.get(B + "/api/team").json()["rooms"] if x["kind"] == "list"]
if L2:
    check(A.post(B + f"/api/team/rooms/{L2[0]['id']}/e2e", json={"on": True}).status_code == 400, "dm: a list channel cannot be encrypted")
r = A.post(B + f"/api/team/rooms/{DM}/e2e", json={"on": False})
check(r.ok and A.get(B + f"/api/team/rooms/{DM}/messages").json()["messages"][-1]["enc"] == {"sys": "off"}, "dm: switched off with a notice")
check(A.post(B + f"/api/team/rooms/{DM}/messages", json={"body": "plain again"}).status_code == 201, "dm: plain again after switching off")

# ================================================================== removing the keys
Bo.post(B + f"/api/team/rooms/{DM}/e2e", json={"on": True})
check(A.delete(B + "/api/e2e/keys").status_code == 403 and A.get(B + "/api/e2e/keys").json()["set"], "remove: not without the password (2.42.0 review)")
r = A.delete(B + "/api/e2e/keys", json={"password": "password123"})
check(r.ok and r.json()["removed"] is True and A.get(B + "/api/e2e/keys").json() == {"set": False, "password": True}, "remove: keys gone")
check(A.get(B + f"/api/tasks/{T}/enc-note").status_code == 404, "remove: my notes go with them")
check(A.get(B + f"/api/team/rooms/{DM}/messages").json()["room"]["e2e"] is False, "remove: my encrypted DMs are switched off")
check(A.put(B + "/api/e2e/keys", json=keys()).ok, "remove: new keys can be set up afterwards")

print(f"p2420_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
