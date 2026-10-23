#!/usr/bin/env python3
"""2.48.0 API tests, part C (#1642: lock a task's note with one's own password), own container (start.sh). Invented names
only. The server only stores what the browser encrypted; these tests send ciphertext-shaped values (the WebCrypto round trip
is in p248_c_lock_ui.js).
 - locking needs the person's end-to-end keys and an own list that is not shared (people / groups: 409; an agent on the
   list is fine); someone else's task: 404
 - locked: tasks.content is empty, only the ciphertext is stored; the history keeps no text of the note; the app state, the
   REST API, the agent, the export and the search see an empty note and note_locked, never the ciphertext
 - nothing overwrites a locked note: app PATCH and agent PATCH = 409 with a clear message (other fields still change),
   a calendar app's PUT changes the title but neither overwrites nor unlocks the note
 - only the person who locked it reads / changes / unlocks it; unlocking writes the plain text back
usage: p248_c_lock_api_test.py <datadir>"""
import base64
import json
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

from kt import FAILS, OKS, check, sess, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
LOCAL = os.environ.get("P248C_NOSTART") == "1"  # against a container started by hand
SECRET = "Secret plan alpha-7 for the garden"


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


def blob(n=64):
    return {"v": 1, "iv": b64(12), "ct": b64(n)}


def keys():
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}


class Api:
    def __init__(self, token):
        self.h = {"Authorization": "Bearer " + token}

    def __getattr__(self, m):
        return lambda path, **kw: requests.request(m.upper(), B + "/api/v1" + path, headers=self.h, **kw)


def state_task(s, tid):
    return next((t for t in s.get(B + "/api/state").json()["tasks"] if t["id"] == tid), None)


if not LOCAL:
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"features": "collab,agents,comments", "lang": "en", "tour": "done"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
LP = A.post(B + "/api/lists", json={"name": "Private notes"}).json()["id"]
LS = A.post(B + "/api/lists", json={"name": "Shared work"}).json()["id"]
assert A.put(B + f"/api/lists/{LS}/members", json={"user_id": BOB, "role": "edit"}).ok
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"}).json()
AG = Api(ag["token"])
assert A.put(B + f"/api/lists/{LP}/members", json={"user_id": ag["id"], "role": "edit"}).ok  # an agent on the list: still "not shared"
TP = A.post(B + "/api/tasks", json={"title": "Garden", "list_id": LP, "content": SECRET}).json()["id"]
TS = A.post(B + "/api/tasks", json={"title": "Team plan", "list_id": LS, "content": "shared text"}).json()["id"]
# the history of #1409 keeps the text before "Turn the checklist into subtasks": locking must remove it
dbx("INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)",
    (TP, 1, "md_subtasks", json.dumps({"prev": SECRET}), "2026-10-15T10:00:00.000Z"))

# ================================================================== who may lock
nb = blob(120)
check(A.put(B + f"/api/tasks/{TP}/note-lock", json={"body": nb}).status_code == 409, "lock: needs own end-to-end keys first")
assert A.put(B + "/api/e2e/keys", json=keys()).ok
check(A.put(B + f"/api/tasks/{TP}/note-lock", json={"body": SECRET}).status_code == 400, "lock: plain text is refused")
r = A.put(B + f"/api/tasks/{TS}/note-lock", json={"body": blob()})
check(r.status_code == 409 and "shared" in r.json().get("error", ""), "lock: not in a list shared with people " + r.text[:200])
check(Bo.put(B + f"/api/tasks/{TP}/note-lock", json={"body": blob()}).status_code in (403, 404), "lock: someone else's task: refused")
check(requests.put(B + f"/api/tasks/{TP}/note-lock", headers={"Authorization": "Bearer " + ag["token"], **H}, json={"body": blob()}).status_code in (401, 403, 404),
      "lock: an agent cannot lock")
r = A.put(B + f"/api/tasks/{TP}/note-lock", json={"body": nb})
check(r.ok and r.json().get("locked") is True, "lock: own list, only an agent on it: locked " + r.text[:200])

# ================================================================== what the server keeps
row = dbx("SELECT content FROM tasks WHERE id=?", (TP,))[0]
check(row[0] == "", "locked: tasks.content is empty")
lk = dbx("SELECT user_id, body FROM task_note_locks WHERE task_id=?", (TP,))
check(len(lk) == 1 and lk[0][0] == 1 and json.loads(lk[0][1])["ct"] == nb["ct"], "locked: only the ciphertext is stored")
check(not dbx("SELECT 1 FROM activity WHERE task_id=? AND data::text LIKE ?", (TP, "%alpha-7%")), "locked: the history keeps no text of the note")
check(dbx("SELECT COUNT(*) FROM activity WHERE task_id=? AND kind='note_lock'", (TP,))[0][0] == 1, "locked: the history says it was locked")
st = A.get(B + "/api/state").json()
ta = next(t for t in st["tasks"] if t["id"] == TP)
check(ta["content"] == "" and ta.get("note_locked") is True and ta.get("note_locked_mine") is True and ta["title"] == "Garden",
      "state: empty note, note_locked + mine, the title stays")
check(nb["ct"] not in json.dumps(st) and "alpha-7" not in json.dumps(st), "state: neither ciphertext nor text")
r = A.get(B + f"/api/tasks/{TP}/note-lock")
check(r.ok and r.json()["body"] == nb, "read: the owner loads the ciphertext")
check(Bo.get(B + f"/api/tasks/{TP}/note-lock").status_code in (403, 404), "read: nobody else")

# ================================================================== agents, API, search, export, calendar
r = AG.get(f"/tasks/{TP}")
check(r.ok and r.json().get("note_locked") is True and r.json().get("notes") == "" and nb["ct"] not in r.text,
      "agent: sees note_locked and an empty note " + r.text[:200])
r = AG.patch(f"/tasks/{TP}", json={"notes": "agent writes over it"})
check(r.status_code == 409 and "locked" in r.text, "agent: PATCH notes on a locked note = 409 with a clear message " + r.text[:200])
r = AG.patch(f"/tasks/{TP}", json={"title": "Garden plan"})
check(r.ok and r.json().get("note_locked") is True, "agent: other fields still change " + r.text[:200])
check(dbx("SELECT content FROM tasks WHERE id=?", (TP,))[0][0] == "", "agent: the note stays empty")
r = A.patch(B + f"/api/tasks/{TP}", json={"content": "typed over"})
check(r.status_code == 409, "app: PATCH content on a locked note = 409")
r = A.patch(B + f"/api/tasks/{TP}", json={"content": "", "priority": 3})
check(r.ok, "app: sending the empty note back unchanged is no change " + r.text[:200])
r = AG.get("/search", params={"q": "alpha-7"})
check(r.ok and TP not in [t.get("id") for t in r.json().get("tasks", r.json().get("results", []))] and "alpha" not in r.text,
      "search: the locked text is not found " + r.text[:200])
ex = A.get(B + "/api/export.json")
check(ex.ok and "alpha-7" not in ex.text and nb["ct"] in ex.text, "export: no text, the locked note as ciphertext")
# CalDAV: a calendar app's PUT changes the title but never the note or the lock
pw = A.post(B + "/api/me/app-passwords", json={"name": "Phone"}).json()["password"]
dv = requests.Session()
dv.auth = ("alice", pw)
pf = dv.request("PROPFIND", B + f"/dav/calendars/alice/{LP}/", headers={"Depth": "1"})
href = next(iter(re.findall(rf"<D:href>([^<]*kalmido-{TP}-[^<]*\.ics)</D:href>", pf.text)), None)
check(pf.status_code == 207 and href, "caldav: the task is in the calendar " + str(pf.status_code))
if href:
    g = dv.get(B + href)
    check(g.ok and "alpha-7" not in g.text and "DESCRIPTION" not in g.text, "caldav: no note in the VTODO")
    ics = re.sub(r"SUMMARY:[^\r\n]*", "SUMMARY:Garden from the phone", g.text.replace("\r\n ", ""))
    ics = ics.replace("END:VTODO", "DESCRIPTION:written on the phone\r\nEND:VTODO")
    r = dv.put(B + href, data=ics.encode(), headers={"Content-Type": "text/calendar; charset=utf-8", "If-Match": g.headers.get("ETag", "*")})
    t = dbx("SELECT title, content FROM tasks WHERE id=?", (TP,))[0]
    check(r.status_code in (200, 201, 204) and t[0] == "Garden from the phone" and t[1] == "" and dbx("SELECT 1 FROM task_note_locks WHERE task_id=?", (TP,)),
          f"caldav: the title changes, the note stays locked and empty ({r.status_code} {t})")
ta = state_task(A, TP)
check(ta and ta.get("note_locked") and ta["content"] == "", "after all that: still locked")

# ================================================================== change, move, unlock
nb2 = blob(140)
r = A.put(B + f"/api/tasks/{TP}/note-lock", json={"body": nb2})
check(r.ok and A.get(B + f"/api/tasks/{TP}/note-lock").json()["body"] == nb2, "change: the owner saves a new ciphertext")
check(dbx("SELECT COUNT(*) FROM activity WHERE task_id=? AND kind='note_lock'", (TP,))[0][0] == 1, "change: no second 'locked' line")
# moving it into a shared list is allowed (the app warns); the note stays unreadable for the others
r = A.patch(B + f"/api/tasks/{TP}", json={"list_id": LS})
tb = state_task(Bo, TP)
check(r.ok and tb and tb.get("note_locked") is True and not tb.get("note_locked_mine") and tb["content"] == "",
      "move: in a shared list the other member sees only that it is locked")
check(Bo.get(B + f"/api/tasks/{TP}/note-lock").status_code == 403 and Bo.delete(B + f"/api/tasks/{TP}/note-lock", json={"content": "x"}).status_code == 403,
      "move: the other member can neither read nor unlock it")
check(Bo.patch(B + f"/api/tasks/{TP}", json={"content": "bob writes"}).status_code == 409, "move: the other member cannot overwrite it")
A.patch(B + f"/api/tasks/{TP}", json={"list_id": LP})
r = A.delete(B + f"/api/tasks/{TP}/note-lock", json={"content": SECRET})
ta = state_task(A, TP)
check(r.ok and ta["content"] == SECRET and not ta.get("note_locked") and not dbx("SELECT 1 FROM task_note_locks WHERE task_id=?", (TP,)),
      "unlock: the text is the task's note again, the lock is gone")
check(dbx("SELECT COUNT(*) FROM activity WHERE task_id=? AND kind='note_unlock'", (TP,))[0][0] == 1, "unlock: the history says so")
r = AG.get(f"/tasks/{TP}")
check(r.ok and r.json().get("notes") == SECRET and "note_locked" not in r.json(), "unlock: agents read the note again")

print(f"p248_c_lock_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
