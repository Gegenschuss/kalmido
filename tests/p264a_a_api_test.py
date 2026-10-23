#!/usr/bin/env python3
"""2.64.1 API tests, part A (#1817: the lock per list -- the server core), own container (start.sh). Invented names only. The
server never sees a list key or a plain text of a locked list; these tests send ciphertext-shaped values ("e2e1:" + {v, g, iv,
ct}) and wrapped keys of the right shape (the WebCrypto round trip is in the UI suites of the client parts).
 - GET /api/lists/<id>/e2e: members with their public keys, blockers (agent, public link, participant, locked notes, notepads),
   people and their sessions only (agents / API tokens 403)
 - start: owner / list admins with own keys, a key for everyone set up (409 names the missing), the others on the waiting list
 - todo / bulk / finish: every text of the list incl. the trash and comments of deleted tasks, at most 200 values per call,
   ciphertexts of the current generation only, a cut-off run continues, finish only when nothing is left
 - the write guard: plain text 409 list_e2e, busy 409 list_e2e_busy, ciphertext in an open list 400, moves 409 list_e2e_move
   unless the texts come along, API token 403, waiting notes / note lock refused
 - members: agent / participant 409, a new person / a group lands on the waiting list, leaving drops the keys and marks the
   rotation, key release only by owner / list admins (wrapper_pub set by the server, a News item), owner transfer
 - the way back: only the owner with the password; afterwards no keys, no waiting list, mode open
 - /api/e2e/pub/<uid> for people sharing a list (H4)
usage: p264a_a_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

from kt import FAILS, OKS, check, sess, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
LOCAL = os.environ.get("P264A_NOSTART") == "1"  # against a container started by hand


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
    """A ciphertext of a list with the lock (shape only)."""
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(n)}, separators=(",", ":"))


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


if not LOCAL:
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"features": "collab,agents,comments,api", "lang": "en", "tour": "done"})
U = {}
for name in ("bob", "carol", "dave", "erin", "frank"):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123"})
    assert r.ok, r.text
    U[name] = r.json()["id"]
BOB, CAROL, DAVE, ERIN, FRANK = (U[k] for k in ("bob", "carol", "dave", "erin", "frank"))
Bo, Ca, Da, Er, Fr = (sess(k) for k in ("bob", "carol", "dave", "erin", "frank"))
for s in (Bo, Ca, Da, Er, Fr):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments"})
AK = keys()
assert A.put(B + "/api/e2e/keys", json=AK).ok
for s in (Bo, Er, Fr):
    assert s.put(B + "/api/e2e/keys", json=keys()).ok
L = A.post(B + "/api/lists", json={"name": "Garden plans"}).json()["id"]
LO = A.post(B + "/api/lists", json={"name": "Open list"}).json()["id"]
LP = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": CAROL, "role": "view"}).ok
for lid in (LO,):
    assert A.put(B + f"/api/lists/{lid}/members", json={"user_id": BOB, "role": "edit"}).ok
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], **H}

# the texts of the list before (every kind of text the lock covers)
T1 = A.post(B + "/api/tasks", json={"title": "Plant roses", "list_id": L, "content": "Secret soil mix", "url": "https://example.com/roses"}).json()["id"]
assert A.patch(B + f"/api/tasks/{T1}", json={"snippets": [{"code": "print('roses')", "lang": "python"}]}).ok
T2 = A.post(B + "/api/tasks", json={"title": "Old idea", "list_id": L, "content": "trash text"}).json()["id"]
C2 = A.post(B + f"/api/tasks/{T2}/comments", json={"body": "comment of a task in the trash"}).json()["id"]
assert A.delete(B + f"/api/tasks/{T2}").ok
C1 = A.post(B + f"/api/tasks/{T1}/comments", json={"body": "Roses need sun"}).json()["id"]
N1 = A.post(B + f"/api/lists/{L}/notes", json={"title": "Plan", "body": "The long garden plan"}).json()["id"]
S1 = A.post(B + "/api/sections", json={"list_id": L, "name": "Front yard"}).json()["id"]
FT = A.post(B + f"/api/lists/{L}/fields", json={"name": "Variety", "type": "text"}).json()["id"]
FN = A.post(B + f"/api/lists/{L}/fields", json={"name": "Count", "type": "number"}).json()["id"]
assert A.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FT): "Damask", str(FN): 3}}).ok
TO = A.post(B + "/api/tasks", json={"title": "Open task", "list_id": LO, "content": "open text"}).json()["id"]
TOS = A.post(B + "/api/tasks", json={"title": "Open subtask", "parent_id": TO}).json()["id"]

# ================================================================== reading the lock
r = Bo.get(B + f"/api/lists/{L}/e2e")
j = r.json() if r.ok else {}
mem = {m["user_id"]: m for m in j.get("members", [])}
check(r.ok and j["mode"] is None and j["gen"] == 0 and j["can_manage"] is False, "info: a member reads it, open list, cannot manage " + r.text[:200])
check(mem.get(1, {}).get("role") == "owner" and mem[1]["has_keys"] and mem[1]["pub"]["x"] == AK["pub"]["x"] and mem.get(CAROL, {}).get("has_keys") is False,
      "info: owner + members with their public keys (null without set-up)")
check(j.get("blockers") == [], "info: nothing blocks yet " + json.dumps(j.get("blockers")))
check(A.get(B + f"/api/lists/{L}/e2e").json()["can_manage"] is True, "info: the owner may manage")
check(Fr.get(B + f"/api/lists/{L}/e2e").status_code == 404, "info: not for people outside the list")
check(requests.get(B + f"/api/lists/{L}/e2e", headers=AGH).status_code in (401, 403, 404), "info: not for agents")

# ================================================================== blockers
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": ag["id"], "role": "edit"}).ok
j = A.get(B + f"/api/lists/{L}/e2e").json()
check([b["code"] for b in j["blockers"]] == ["agent"] and [x["user_id"] for x in j["agents"]] == [ag["id"]] and ag["id"] not in [m["user_id"] for m in j["members"]],
      "blocker: an agent in the list (listed apart) " + json.dumps(j["blockers"]))
r = A.post(B + f"/api/lists/{L}/e2e/start", json={"keys": [{"user_id": 1, "wrapped": wrapped()}, {"user_id": BOB, "wrapped": wrapped()}]})
check(r.status_code == 409 and code(r) == "list_e2e_blocked" and r.json()["blockers"][0]["code"] == "agent", "start: refused while an agent is in it")
assert A.delete(B + f"/api/lists/{L}/members/{ag['id']}").ok
pl = A.put(B + f"/api/lists/{L}/public-link", json={"mode": "view"})
if pl.ok:
    check("public_link" in [b["code"] for b in A.get(B + f"/api/lists/{L}/e2e").json()["blockers"]], "blocker: a public link")
    assert A.delete(B + f"/api/lists/{L}/public-link").ok
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": CAROL, "role": "participant"}).ok
check("participant" in [b["code"] for b in A.get(B + f"/api/lists/{L}/e2e").json()["blockers"]], "blocker: the participant role")
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": CAROL, "role": "view"}).ok
dbx("INSERT INTO list_notepads(list_id,title,body,created_at,updated_at) VALUES(?,?,?,?,?)", (L, "Pad", "pad text", "2026-10-17T00:00:00+00:00", "2026-10-17T00:00:00+00:00"))
check("notepad" in [b["code"] for b in A.get(B + f"/api/lists/{L}/e2e").json()["blockers"]], "blocker: a notepad with text")
dbx("DELETE FROM list_notepads WHERE list_id=?", (L,))
TP = A.post(B + "/api/tasks", json={"title": "Diary", "list_id": LP, "content": "x"}).json()["id"]
assert A.put(B + f"/api/tasks/{TP}/note-lock", json={"body": {"v": 1, "iv": b64(12), "ct": b64(64)}}).ok
check("note_lock" in [b["code"] for b in A.get(B + f"/api/lists/{LP}/e2e").json()["blockers"]], "blocker: a note locked with a password")

# ================================================================== switching it on
KS = [{"user_id": 1, "wrapped": wrapped()}, {"user_id": BOB, "wrapped": wrapped()}]
r = Bo.post(B + f"/api/lists/{L}/e2e/start", json={"keys": KS})
check(r.status_code == 403, "start: not by a member with the role edit")
r = A.post(B + f"/api/lists/{L}/e2e/start", json={"keys": KS[:1]})
check(r.status_code == 409 and code(r) == "list_e2e_keys" and r.json()["missing"] == [BOB] and "Bob" in r.json()["error"],
      "start: a key for everyone set up (names the missing) " + r.text[:200])
r = A.post(B + f"/api/lists/{L}/e2e/start", json={"keys": KS + [{"user_id": CAROL, "wrapped": wrapped()}]})
check(r.status_code == 400, "start: no key for someone without set-up")
r = A.post(B + f"/api/lists/{L}/e2e/start", json={"keys": [KS[0], {"user_id": BOB, "wrapped": {"v": 1, "iv": "x", "ct": "y"}}]})
check(r.status_code == 400, "start: a broken wrapped key")
r = A.post(B + f"/api/lists/{L}/e2e/start", json={"keys": KS})
j = r.json() if r.ok else {}
check(r.ok and j["mode"] == "encrypting" and j["gen"] == 1 and [p["user_id"] for p in j["pending"]] == [CAROL] and j["left"]["tasks"] >= 2,
      "start: encrypting, generation 1, the person without set-up waits (E7) " + r.text[:300])
check(j.get("keys") and j["keys"][0]["gen"] == 1 and j["keys"][0]["wrapped_by"] == 1 and j["keys"][0]["wrapper_pub"]["x"] == AK["pub"]["x"],
      "start: my wrapped key with the wrapper's public key")
check(A.post(B + f"/api/lists/{L}/e2e/start", json={"keys": KS}).status_code == 409, "start: not twice")
check(dbx("SELECT COUNT(*) FROM list_keys WHERE list_id=? AND gen=1", (L,))[0][0] == 2, "start: two wrapped keys stored")

# ================================================================== while it is being encrypted
r = Bo.patch(B + f"/api/tasks/{T1}", json={"title": "Bob types"})
check(r.status_code == 409 and code(r) == "list_e2e_busy", "busy: texts wait " + r.text[:200])
check(Bo.patch(B + f"/api/tasks/{T1}", json={"priority": 3}).ok, "busy: other fields still change")
r = Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "a comment now"})
check(r.status_code == 409 and code(r) == "list_e2e_busy", "busy: comments wait")
check(Ca.get(B + f"/api/lists/{L}/e2e/todo").status_code == 403, "todo: not for a viewer")

# todo / bulk in pieces (a cut-off run continues)
r = A.get(B + f"/api/lists/{L}/e2e/todo", params={"limit": 3})
j = r.json()
n = sum(1 for k in ("tasks", "comments", "notes", "sections") for x in j[k] for f, v in x.items() if f != "id" and v is not None) + len(j["fields"])
check(r.ok and 1 <= n <= 3, f"todo: at most limit values ({n})")
r = A.get(B + f"/api/lists/{L}/e2e/todo")
j = r.json()
tids = {x["id"] for x in j["tasks"]}
check(r.ok and {T1, T2} <= tids and {C1, C2} <= {x["id"] for x in j["comments"]} and [x["id"] for x in j["notes"]] == [N1]
      and [x["id"] for x in j["sections"]] == [S1] and [(x["task_id"], x["field_id"]) for x in j["fields"]] == [(T1, FT)],
      "todo: tasks (with the trash), comments (also of deleted tasks), notes, sections, text fields only " + r.text[:300])
t1 = next(x for x in j["tasks"] if x["id"] == T1)
check(t1["title"] == "Plant roses" and t1["url"] == "https://example.com/roses" and "roses" in (t1["snippets"] or ""), "todo: the plain values (snippets as one JSON text)")
r = A.post(B + f"/api/lists/{L}/e2e/bulk", json={"tasks": [{"id": T1, "title": "Plant roses"}]})
check(r.status_code == 400, "bulk: a plain text while encrypting")
r = A.post(B + f"/api/lists/{L}/e2e/bulk", json={"tasks": [{"id": T1, "title": ct(2)}]})
check(r.status_code == 400, "bulk: a ciphertext of another generation")
r = A.post(B + f"/api/lists/{L}/e2e/bulk", json={"tasks": [{"id": TO, "title": ct(1)}]})
check(r.status_code == 400, "bulk: only rows of this list")
r = A.post(B + f"/api/lists/{L}/e2e/bulk", json={"comments": [{"id": C1, "body": ct(1)} for _ in range(201)]})
check(r.status_code == 400, "bulk: at most 200 values per call")
r = A.post(B + f"/api/lists/{L}/e2e/finish")
check(r.status_code == 409 and code(r) == "list_e2e_left" and r.json()["left"]["tasks"] >= 1, "finish: not while texts are left")
CT = {}


def enc_all(todo):
    out = {"tasks": [], "comments": [], "notes": [], "sections": [], "fields": []}
    for k in ("tasks", "comments", "notes", "sections"):
        for x in todo[k]:
            y = {"id": x["id"]}
            for f, v in x.items():
                if f != "id" and v is not None:
                    y[f] = CT.setdefault((k, x["id"], f), ct(1))
            out[k].append(y)
    for x in todo["fields"]:
        out["fields"].append({"task_id": x["task_id"], "field_id": x["field_id"], "value": CT.setdefault(("fields", x["task_id"], x["field_id"]), ct(1))})
    return out


# first only the tasks (the run is "cut off"), then the rest
part = enc_all(j)
r = A.post(B + f"/api/lists/{L}/e2e/bulk", json={"tasks": part["tasks"]})
check(r.ok and r.json()["left"]["tasks"] == 0 and r.json()["left"]["comments"] >= 2, "bulk: tasks done, the rest left " + r.text[:200])
r = A.post(B + f"/api/lists/{L}/e2e/bulk", json={"tasks": part["tasks"][:1]})
check(r.ok, "bulk: repeating a call is harmless")
j2 = A.get(B + f"/api/lists/{L}/e2e/todo").json()
check(not j2["tasks"] and j2["comments"], "todo: continues where it stopped")
r = A.post(B + f"/api/lists/{L}/e2e/bulk", json={k: v for k, v in enc_all(j2).items() if k != "tasks"})
check(r.ok and not any(r.json()["left"].values()), "bulk: nothing left " + r.text[:200])
r = A.post(B + f"/api/lists/{L}/e2e/finish")
check(r.ok and r.json()["mode"] == "on", "finish: the lock is on " + r.text[:200])
row = dbx("SELECT title, content, url, snippets::text FROM tasks WHERE id=?", (T1,))[0]
check(row[0] == CT[("tasks", T1, "title")] and row[1].startswith("e2e1:") and row[2].startswith("e2e1:") and json.loads(row[3]).startswith("e2e1:"),
      "db: title, note, link and snippets are ciphertexts (snippets as a JSON string)")
plain = dbx("""SELECT 'task' FROM tasks WHERE list_id=? AND (title NOT LIKE 'e2e1:%' OR (content<>'' AND content NOT LIKE 'e2e1:%'))
               UNION ALL SELECT 'comment' FROM comments cm JOIN tasks t ON t.id=cm.task_id WHERE t.list_id=? AND cm.body<>'' AND cm.body NOT LIKE 'e2e1:%'
               UNION ALL SELECT 'note' FROM notes WHERE list_id=? AND (title NOT LIKE 'e2e1:%' OR body NOT LIKE 'e2e1:%')
               UNION ALL SELECT 'section' FROM sections WHERE list_id=? AND name NOT LIKE 'e2e1:%'""", (L, L, L, L))
check(not plain, "db: no plain text left in the list (trash included) " + str(plain))
check(dbx("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (T1, FN))[0][0] == "3", "db: a number field stays readable (E2)")

# ================================================================== the state
st = A.get(B + "/api/state").json()
lr = next(x for x in st["lists"] if x["id"] == L)
check(lr["e2e"] == "on" and lr["e2e_gen"] == 1 and lr["e2e_mine"] is True and lr["e2e_pending"] == 1 and lr["e2e_rotate"] == 0,
      "state: e2e, e2e_gen, e2e_mine, e2e_pending, e2e_rotate " + json.dumps({k: lr.get(k) for k in ("e2e", "e2e_gen", "e2e_mine", "e2e_pending")}))
t = next(x for x in st["tasks"] if x["id"] == T1)
check(t["title"].startswith("e2e1:") and isinstance(t.get("snippets"), str) and t["snippets"].startswith("e2e1:"), "state: the app gets the ciphertexts")
lc = next(x for x in Ca.get(B + "/api/state").json()["lists"] if x["id"] == L)
check(lc["e2e_mine"] is False, "state: carol has no key yet")

# ================================================================== the write guard
r = A.patch(B + f"/api/tasks/{T1}", json={"title": "Plain again"})
check(r.status_code == 409 and code(r) == "list_e2e" and "app" in r.json()["error"], "guard: a plain title 409 list_e2e " + r.text[:200])
nt = ct(1, 90)
r = A.patch(B + f"/api/tasks/{T1}", json={"title": nt})
check(r.ok and dbx("SELECT title FROM tasks WHERE id=?", (T1,))[0][0] == nt, "guard: a ciphertext is stored exactly (never cut)")
check(A.patch(B + f"/api/tasks/{T1}", json={"title": ct(2)}).status_code == 409, "guard: a generation that does not exist yet")
check(A.patch(B + f"/api/tasks/{T1}", json={"title": "e2e1:{broken"}).status_code == 400, "guard: a broken ciphertext 400")
big = ct(1, 30000)
r = A.patch(B + f"/api/tasks/{T1}", json={"content": big})
check(r.ok and dbx("SELECT content FROM tasks WHERE id=?", (T1,))[0][0] == big, "guard: long ciphertexts (L3)")
check(A.post(B + "/api/tasks", json={"title": "plain new", "list_id": L}).status_code == 409, "guard: a new task with a plain title")
r = A.post(B + "/api/tasks", json={"title": ct(1), "list_id": L, "url": ct(1), "snippets": ct(1)})
check(r.ok, "guard: a new task with ciphertexts (title, link, snippets) " + r.text[:200])
check(A.patch(B + f"/api/tasks/{TO}", json={"title": ct(1)}).status_code == 400, "guard: no ciphertext in an open list (M8)")
r = Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": "plain comment"})
check(r.status_code == 409 and code(r) == "list_e2e", "comment: plain 409")
r = Bo.post(B + f"/api/tasks/{T1}/comments", json={"body": ct(1), "mentions": [1, FRANK, 999999]})
check(r.ok and r.json()["mentions"] == [1], "comment: ciphertext, mentions only of people of the list " + r.text[:200])
check(A.post(B + f"/api/lists/{L}/notes", json={"title": "plain", "body": "x"}).status_code == 409, "note: plain 409")
check(A.post(B + f"/api/lists/{L}/notes", json={"title": ct(1), "body": ct(1)}).status_code == 201, "note: ciphertexts")
check(A.patch(B + f"/api/sections/{S1}", json={"name": "Back yard"}).status_code == 409, "section: plain 409")
check(A.patch(B + f"/api/sections/{S1}", json={"name": ct(1)}).ok, "section: ciphertext")
check(A.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FT): "Plain variety"}}).status_code in (400, 409), "field: plain text 409")
check(A.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FT): ct(1), str(FN): 5}}).ok, "field: ciphertext + a readable number")
r = A.put(B + f"/api/tasks/{T1}/waiting", json={"note": "the supplier"})
check(r.status_code == 409 and code(r) == "list_e2e_plain", "waiting: a note is not encrypted: refused")
check(A.put(B + f"/api/tasks/{T1}/waiting", json={}).ok, "waiting: without a note fine")
check(A.put(B + f"/api/tasks/{T1}/note-lock", json={"body": {"v": 1, "iv": b64(12), "ct": b64(64)}}).status_code == 409, "note lock: not in a list with the lock")
tok = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "write"]})
if tok.ok:
    TH = {"Authorization": "Bearer " + tok.json()["token"]}
    r = requests.patch(B + f"/api/v1/tasks/{T1}", headers=TH, json={"title": "from a script"})
    check(r.status_code in (403, 409) and dbx("SELECT title FROM tasks WHERE id=?", (T1,))[0][0] == nt, "API token: no text change " + r.text[:200])
    r = requests.patch(B + f"/api/v1/tasks/{T1}", headers=TH, json={"title": ct(1)})
    check(r.status_code in (403, 409), "API token: not even a ciphertext (only the web app)")
    check(requests.get(B + f"/api/v1/lists/{L}/notes", headers=TH).status_code == 403, "API token: notes of the list 403")
    check(requests.get(B + f"/api/lists/{L}/e2e", headers=TH).status_code in (401, 403), "API token: the lock routes 403")
else:
    check(False, "API token could not be made " + tok.text[:200])

# ================================================================== moving (M8)
r = A.patch(B + f"/api/tasks/{TO}", json={"list_id": L})
check(r.status_code == 409 and code(r) == "list_e2e_move" and set(r.json()["need"]["tasks"]) == {TO, TOS},
      "move in: without the texts 409, names what is needed " + r.text[:300])
check(A.post(B + "/api/tasks/reorder", json={"items": [{"id": TO, "list_id": L, "sort": 1}]}).status_code == 409, "move in: dragging (reorder) 409")
r = A.patch(B + f"/api/tasks/{TO}", json={"list_id": L, "title": ct(1), "content": ct(1), "le2e_move": {"tasks": [{"id": TOS, "title": ct(1)}]}})
row = dbx("SELECT list_id, title FROM tasks WHERE id=?", (TOS,))[0]
check(r.ok and row[0] == L and row[1].startswith("e2e1:"), "move in: with the texts of the subtree " + r.text[:200])
r = A.patch(B + f"/api/tasks/{TO}", json={"list_id": LO})
check(r.status_code == 409 and code(r) == "list_e2e_move", "move out: without the texts 409")
r = A.patch(B + f"/api/tasks/{TO}", json={"list_id": LO, "title": "Open task", "content": "open text", "le2e_move": {"tasks": [{"id": TOS, "title": "Open subtask"}]}})
check(r.ok and dbx("SELECT title FROM tasks WHERE id=?", (TOS,))[0][0] == "Open subtask", "move out: plain texts back " + r.text[:200])
# multi-select / undo: one change for many tasks, every task's own texts in le2e_move.tasks
r = A.post(B + "/api/tasks/batch", json={"ids": [TO], "action": "patch", "data": {"list_id": L, "le2e_move": {
    "tasks": [{"id": TO, "title": ct(1), "content": ct(1)}, {"id": TOS, "title": ct(1)}]}}})
row = dbx("SELECT list_id, title, content FROM tasks WHERE id=?", (TO,))[0]
check(r.ok and r.json()["count"] == 1 and row[0] == L and row[1].startswith("e2e1:") and row[2].startswith("e2e1:"),
      "batch move in: own texts from le2e_move " + r.text[:200])
r = A.post(B + "/api/tasks/batch", json={"ids": [TO], "action": "patch_each", "data": {"items": {str(TO): {"list_id": LO, "le2e_move": {
    "tasks": [{"id": TO, "title": "Open task", "content": "open text"}, {"id": TOS, "title": "Open subtask"}]}}}}})
row = dbx("SELECT list_id, title FROM tasks WHERE id=?", (TO,))[0]
check(r.ok and r.json()["count"] == 1 and row[0] == LO and row[1] == "Open task", "undo move out: plain texts back " + r.text[:200])
r = A.post(B + "/api/tasks/batch", json={"ids": [TO], "action": "patch", "data": {"list_id": L}})
check(r.ok and r.json()["count"] == 0 and r.json()["errors"] and dbx("SELECT list_id FROM tasks WHERE id=?", (TO,))[0][0] == LO,
      "batch move in without texts: skipped with an error")
N2 = A.post(B + f"/api/lists/{LO}/notes", json={"title": "Open note", "body": "b"}).json()["id"]
check(A.patch(B + f"/api/notes/{N2}", json={"list_id": L}).status_code == 409, "note move in: without texts 409")
check(A.patch(B + f"/api/notes/{N2}", json={"list_id": L, "title": ct(1), "body": ct(1)}).ok, "note move in: with texts")

# ================================================================== members
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": ag["id"], "role": "edit"})
check(r.status_code == 409 and code(r) == "list_e2e_member", "members: no agent " + r.text[:200])
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": DAVE, "role": "participant"})
check(r.status_code == 409, "members: no participant")
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": DAVE, "role": "edit"})
check(r.ok and r.json().get("e2e_pending") == [DAVE], "members: a new person waits for the key " + r.text[:200])
g = A.post(B + "/api/admin/groups", json={"name": "Gardeners", "members": [ERIN]})
if g.ok:
    gid = g.json()["id"]
    r = A.put(B + f"/api/lists/{L}/groups/{gid}", json={"role": "participant"})
    check(r.status_code == 409, "group: not with the role participant")
    check(A.put(B + f"/api/lists/{L}/groups/{gid}", json={"role": "edit"}).ok, "group: shared")
    check(dbx("SELECT 1 FROM list_key_pending WHERE list_id=? AND user_id=?", (L, ERIN)), "group: the new member waits for the key (M3)")
else:
    check(False, "group could not be made " + g.text[:200])
j = A.get(B + f"/api/lists/{L}/e2e").json()
pend = {p["user_id"]: p for p in j["pending"]}
check({CAROL, DAVE, ERIN} <= set(pend) and pend[ERIN]["has_keys"] and not pend[DAVE]["has_keys"], "waiting list: with has_keys " + json.dumps(j["pending"]))

# a child account takes part only as a participant: it leaves a list with the lock (no 500 from the members trigger)
r = A.patch(B + f"/api/users/{CAROL}", json={"kid": True})
check(r.ok and not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (L, CAROL))
      and dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (LO, BOB)), "kid: leaves the list with the lock " + r.text[:200])

# release (M9)
r = Bo.post(B + f"/api/lists/{L}/e2e/keys", json={"keys": [{"user_id": ERIN, "gen": 1, "wrapped": wrapped()}]})
check(r.status_code == 403, "release: not by a member with the role edit")
r = A.post(B + f"/api/lists/{L}/e2e/keys", json={"keys": [{"user_id": DAVE, "gen": 1, "wrapped": wrapped()}]})
check(r.status_code == 409, "release: not to someone without set-up")
r = A.post(B + f"/api/lists/{L}/e2e/keys", json={"keys": [{"user_id": ERIN, "gen": 2, "wrapped": wrapped()}]})
check(r.status_code == 409, "release: not a generation I do not hold")
r = A.post(B + f"/api/lists/{L}/e2e/keys", json={"keys": [{"user_id": FRANK, "gen": 1, "wrapped": wrapped()}]})
check(r.status_code == 409, "release: not to someone outside the list")
r = A.post(B + f"/api/lists/{L}/e2e/keys", json={"keys": [{"user_id": ERIN, "gen": 1, "wrapped": wrapped()}]})
row = dbx("SELECT wrapped_by, wrapper_pub FROM list_keys WHERE list_id=? AND user_id=? AND gen=1", (L, ERIN))
check(r.ok and row and row[0][0] == 1 and json.loads(row[0][1])["x"] == AK["pub"]["x"], "release: stored with the wrapper's public key from the server")
check(not dbx("SELECT 1 FROM list_key_pending WHERE list_id=? AND user_id=?", (L, ERIN)), "release: off the waiting list")
check(dbx("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='e2e_key' AND list_id=?", (ERIN, L))[0][0] == 1, "release: a News item for the recipient")
nw = Er.get(B + "/api/news").json()
items = nw.get("items", nw.get("news", [])) if isinstance(nw, dict) else nw
ek = [x for x in items if x.get("kind") == "e2e_key"]
check(len(ek) == 1 and ek[0]["list_id"] == L and ek[0]["data"].get("by_name") == "Alice" and ek[0].get("to_me") is True,
      "release: the News item shows in the feed (for me) " + json.dumps(ek)[:200])
ke = Er.get(B + f"/api/lists/{L}/e2e").json()["keys"]
check(len(ke) == 1 and ke[0]["wrapped_by"] == 1, "release: erin loads her wrapped key")

# H4: public keys of people sharing a list
check(Er.get(B + "/api/e2e/pub/1").ok and Er.get(B + "/api/e2e/pub/1").json()["pub"]["x"] == AK["pub"]["x"], "pub: a list mate's public key")
check(Fr.get(B + "/api/e2e/pub/1").status_code == 404, "pub: not for strangers")

# owner transfer: only to someone with the key; their keys stay
check(A.post(B + f"/api/lists/{L}/owner", json={"user_id": DAVE}).status_code == 409, "owner: not to someone without the key")
rot0 = dbx("SELECT e2e_rotate FROM lists WHERE id=?", (L,))[0][0]
r = A.post(B + f"/api/lists/{L}/owner", json={"user_id": BOB})
check(r.ok and dbx("SELECT owner_id FROM lists WHERE id=?", (L,))[0][0] == BOB, "owner: to someone holding the key " + r.text[:200])
check(len(dbx("SELECT 1 FROM list_keys WHERE list_id=? AND gen=1 AND user_id IN (1, ?)", (L, BOB))) == 2
      and dbx("SELECT e2e_rotate FROM lists WHERE id=?", (L,))[0][0] == rot0, "owner: both keep their keys, no new rotation mark")
check(Bo.post(B + f"/api/lists/{L}/owner", json={"user_id": 1}).ok and dbx("SELECT owner_id FROM lists WHERE id=?", (L,))[0][0] == 1, "owner: and back")

# leaving: keys go, the rotation is marked (E8)
dbx("UPDATE lists SET e2e_rotate=0 WHERE id=?", (L,))  # (the kid above left too)
assert A.delete(B + f"/api/lists/{L}/groups/{gid}").ok  # erin came through the group
check(not dbx("SELECT 1 FROM list_keys WHERE list_id=? AND user_id=?", (L, ERIN)) and dbx("SELECT e2e_rotate FROM lists WHERE id=?", (L,))[0][0] == 1,
      "leave: the keys go, rotation pending")
check(A.put(B + f"/api/lists/{L}/public-link", json={"mode": "view"}).status_code == 409, "public link: refused for a list with the lock")

# ================================================================== the way back
check(Bo.post(B + f"/api/lists/{L}/e2e/stop", json={"password": "password123"}).status_code == 403, "stop: only the owner")
check(A.post(B + f"/api/lists/{L}/e2e/stop", json={"password": "wrong"}).status_code == 403, "stop: asks for the password")
r = A.post(B + f"/api/lists/{L}/e2e/stop", json={"password": "password123"})
check(r.ok and r.json()["mode"] == "decrypting", "stop: decrypting " + r.text[:200])
check(A.patch(B + f"/api/tasks/{T1}", json={"title": "x"}).status_code == 409, "decrypting: texts wait")
check(A.post(B + f"/api/lists/{L}/e2e/bulk", json={"tasks": [{"id": T1, "title": ct(1)}]}).status_code == 400, "decrypting: no ciphertext in bulk")
for _ in range(10):
    j = A.get(B + f"/api/lists/{L}/e2e/todo").json()
    if not any(j[k] for k in ("tasks", "comments", "notes", "sections", "fields")):
        break
    out = {"tasks": [], "comments": [], "notes": [], "sections": [], "fields": []}
    for k in ("tasks", "comments", "notes", "sections"):
        for x in j[k]:
            y = {"id": x["id"]}
            for f, v in x.items():
                if f != "id" and v is not None:
                    y[f] = "[]" if f == "snippets" else ("https://example.com/x" if f == "url" else f"plain {k} {f}")
            out[k].append(y)
    out["fields"] = [{"task_id": x["task_id"], "field_id": x["field_id"], "value": "plain value"} for x in j["fields"]]
    r = A.post(B + f"/api/lists/{L}/e2e/bulk", json=out)
    check(r.ok, "decrypting: bulk " + r.text[:200])
r = A.post(B + f"/api/lists/{L}/e2e/finish")
check(r.ok and r.json()["mode"] is None, "finish: open again " + r.text[:200])
check(not dbx("SELECT 1 FROM list_keys WHERE list_id=?", (L,)) and not dbx("SELECT 1 FROM list_key_pending WHERE list_id=?", (L,))
      and dbx("SELECT e2e IS NULL AND e2e_rotate=0 FROM lists WHERE id=?", (L,))[0][0] in (True, 1), "way back: no keys, no waiting list, open")
check(not dbx("SELECT 1 FROM tasks WHERE list_id=? AND (title LIKE 'e2e1:%' OR content LIKE 'e2e1:%')", (L,)), "way back: no ciphertext left")
check(A.patch(B + f"/api/tasks/{T1}", json={"title": "Plant roses again"}).ok, "open again: plain texts")
check(A.patch(B + f"/api/tasks/{T1}", json={"title": ct(1)}).status_code == 400, "open again: no ciphertext")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": ag["id"], "role": "edit"}).ok, "open again: agents may join")

# ================================================================== deleting a list with the lock: the ciphertexts go with it
L2 = A.post(B + "/api/lists", json={"name": "Short lived"}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"title": "temp", "list_id": L2}).json()["id"]
assert A.post(B + f"/api/lists/{L2}/e2e/start", json={"keys": [{"user_id": 1, "wrapped": wrapped()}]}).ok
assert A.post(B + f"/api/lists/{L2}/e2e/bulk", json={"tasks": [{"id": T3, "title": ct(1)}]}).ok
assert A.post(B + f"/api/lists/{L2}/e2e/finish").ok
assert A.patch(B + f"/api/lists/{L2}", json={"archived": True}).ok
r = A.delete(B + f"/api/lists/{L2}")
check(r.ok and not dbx("SELECT 1 FROM tasks WHERE id=?", (T3,)) and not dbx("SELECT 1 FROM list_keys WHERE list_id=?", (L2,)),
      "delete: tasks and keys go with the list (no unreadable ciphertexts in the trash) " + r.text[:200])

# ================================================================== 2.64.1 review round 1 (part E)
LK = A.post(B + "/api/lists", json={"name": "Review lock", "kind": "project"}).json()["id"]
assert A.patch(B + f"/api/lists/{LO}", json={"kind": "project"}).ok  # dependencies across lists need two projects
assert A.put(B + f"/api/lists/{LK}/members", json={"user_id": BOB, "role": "edit"}).ok
TK = A.post(B + "/api/tasks", json={"title": "Review task", "list_id": LK}).json()["id"]
TW = A.post(B + "/api/tasks", json={"title": "Moving waiter", "list_id": LO}).json()["id"]
TD = A.post(B + "/api/tasks", json={"title": "Open waiting", "list_id": LO}).json()["id"]
# 2.64.1 review (M3): lists the server writes texts into cannot be locked
LF = A.post(B + "/api/lists", json={"name": "Groceries"}).json()["id"]
assert A.patch(B + f"/api/lists/{LF}", json={"family": "shopping"}).ok
check("family" in [b["code"] for b in A.get(B + f"/api/lists/{LF}/e2e").json()["blockers"]], "review M3: blocker family")
LL = A.post(B + "/api/lists", json={"name": "House"}).json()["id"]
assert A.patch(B + f"/api/lists/{LL}", json={"life": "home"}).ok
check("life" in [b["code"] for b in A.get(B + f"/api/lists/{LL}/e2e").json()["blockers"]], "review M3: blocker life")
# 2.64.1 review (M2): a list admin cannot lock an owner without encryption out of their own list
LD = Da.post(B + "/api/lists", json={"name": "Dave's list"}).json()["id"]
assert Da.put(B + f"/api/lists/{LD}/members", json={"user_id": 1, "role": "admin"}).ok
j = A.get(B + f"/api/lists/{LD}/e2e").json()
check(j["can_manage"] and "owner_setup" in [b["code"] for b in j["blockers"]], "review M2: blocker owner_setup " + json.dumps(j["blockers"]))
r = A.post(B + f"/api/lists/{LD}/e2e/start", json={"keys": [{"user_id": 1, "wrapped": wrapped()}]})
check(r.status_code == 409 and code(r) == "list_e2e_blocked" and not dbx("SELECT 1 FROM list_keys WHERE list_id=?", (LD,)),
      "review M2: start refused, no keys stored " + r.text[:200])
# 2.64.1 review (M1): a second start does not replace the keys of the first
r = A.post(B + f"/api/lists/{LK}/e2e/start", json={"keys": [{"user_id": 1, "wrapped": wrapped()}, {"user_id": BOB, "wrapped": wrapped()}]})
check(r.ok and r.json()["mode"] == "encrypting", "review M1: first start " + r.text[:200])
w0 = dbx("SELECT user_id, wrapped FROM list_keys WHERE list_id=? ORDER BY user_id", (LK,))
r = A.post(B + f"/api/lists/{LK}/e2e/start", json={"keys": [{"user_id": 1, "wrapped": wrapped()}, {"user_id": BOB, "wrapped": wrapped()}]})
check(r.status_code == 409 and dbx("SELECT user_id, wrapped FROM list_keys WHERE list_id=? ORDER BY user_id", (LK,)) == w0
      and dbx("SELECT e2e_gen FROM lists WHERE id=?", (LK,))[0][0] == 1, "review M1: second start 409, the first keys stay")
assert A.post(B + f"/api/lists/{LK}/e2e/bulk", json=enc_all(A.get(B + f"/api/lists/{LK}/e2e/todo").json())).ok
check(A.post(B + f"/api/lists/{LK}/e2e/finish").ok and A.post(B + f"/api/lists/{LK}/e2e/finish").status_code == 409, "review M1: finish once")
# 2.64.1 review (M3): explicit targets and the purpose of a locked list
r = A.patch(B + f"/api/lists/{LK}", json={"life": "home"})  # (a project is never a family list anyway)
check(r.status_code == 409 and code(r) == "list_e2e_plain", "review M3: a locked list does not become a Home & life list " + r.text[:200])
r = A.post(B + "/api/family/occasions", json={"name": "Grandma", "date": "--05-04", "list_id": LK})
check(r.status_code == 409 and code(r) == "list_e2e_plain", "review M3: no birthday into a locked list " + r.text[:200])
# 2.64.1 review (H1): import with a locked list as target
r = A.post(B + "/api/import/todoist", files={"file": ("p.csv", b"TYPE,CONTENT,PRIORITY\ntask,Imported secret,1\n", "text/csv")}, data={"target": str(LK)})
check(r.status_code == 409 and code(r) == "list_e2e_plain", "review H1: import into a locked list 409 " + r.text[:200])
check(dbx("SELECT COUNT(*) FROM tasks WHERE list_id=?", (LK,))[0][0] == 1, "review H1/M3: nothing written into the locked list")
# 2.64.1 review (L1): an open task waiting on a locked one: no (cut) ciphertext in its history
r = A.post(B + "/api/deps", json={"task_id": TD, "blocker_id": TK})
acts = dbx("SELECT data FROM activity WHERE task_id=?", (TD,))
check(r.ok and acts and "e2e1:" not in json.dumps([str(a[0]) for a in acts]), "review L1: no ciphertext in the history " + r.text[:200])
# 2.64.1 review (L2): the waiting note goes when a task moves into a locked list
dbx("UPDATE tasks SET wait_note='Waiting for the plumber' WHERE id=?", (TW,))
r = A.patch(B + f"/api/tasks/{TW}", json={"list_id": LK, "title": ct(1)})
check(r.ok and dbx("SELECT wait_note FROM tasks WHERE id=?", (TW,))[0][0] == "", "review L2: waiting note gone " + r.text[:200])
# 2.64.1 review (L3): someone else's copy stays unless they set up new keys
wb = dbx("SELECT wrapped FROM list_keys WHERE list_id=? AND user_id=? AND gen=1", (LK, BOB))[0][0]
r = A.post(B + f"/api/lists/{LK}/e2e/keys", json={"keys": [{"user_id": BOB, "gen": 1, "wrapped": wrapped()}]})
check(r.ok and r.json().get("skipped") == [BOB] and r.json().get("released") == []
      and dbx("SELECT wrapped FROM list_keys WHERE list_id=? AND user_id=? AND gen=1", (LK, BOB))[0][0] == wb, "review L3: copy kept, skipped " + r.text[:200])
dbx("UPDATE e2e_keys SET updated_at='2099-01-01T00:00:00+00:00' WHERE user_id=?", (BOB,))
r = A.post(B + f"/api/lists/{LK}/e2e/keys", json={"keys": [{"user_id": BOB, "gen": 1, "wrapped": wrapped()}]})
check(r.ok and r.json().get("released") == [BOB] and dbx("SELECT wrapped FROM list_keys WHERE list_id=? AND user_id=? AND gen=1", (LK, BOB))[0][0] != wb,
      "review L3: replaced after a new set-up " + r.text[:200])
check(A.post(B + f"/api/lists/{LK}/e2e/keys", json={"keys": [{"user_id": 1, "gen": 1, "wrapped": wrapped()}]}).json().get("released") == [1],
      "review L3: my own copy may always be replaced")
# 2.64.1 review: someone on the waiting list (no key) leaves -> no rotation mark (trigger d4ca177)
r = A.put(B + f"/api/lists/{LK}/members", json={"user_id": DAVE, "role": "edit"})
check(r.ok and r.json().get("e2e_pending") == [DAVE], "review: dave waits " + r.text[:200])
assert A.delete(B + f"/api/lists/{LK}/members/{DAVE}").ok
check(dbx("SELECT e2e_rotate FROM lists WHERE id=?", (LK,))[0][0] == 0 and not dbx("SELECT 1 FROM list_key_pending WHERE list_id=? AND user_id=?", (LK, DAVE)),
      "review: a waiting person leaves, rotation stays 0")
# 2.64.1 review (L6): the refusal of a transfer names the list
assert A.put(B + f"/api/lists/{LK}/members", json={"user_id": FRANK, "role": "edit"}).ok
r = A.post(B + f"/api/lists/{LK}/owner", json={"user_id": FRANK})
check(r.status_code == 409 and "Review lock" in r.text, "review L6: the list's name in the refusal " + r.text[:200])

print(f"p264a_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
