#!/usr/bin/env python3
"""2.64.2 API tests, part A (#1817: the lock per list, stage 2 -- key change and re-encryption), own container (start.sh).
Invented names only. The server never sees a list key or a plain text; these tests send ciphertext-shaped values and wrapped keys
of the right shape (the WebCrypto round trip is in p264b_a_ui.js).
 - POST /api/lists/<id>/e2e/rotate: owner / list admins holding the current generation, people only (agent / API token 403),
   gen must be e2e_gen + 1 (409 list_e2e_gen), a stranger in keys 400, everyone not wrapped for on the waiting list, one winner
   when two rotate at the same moment
 - leaving: a person who held a key marks the rotation, a person who only waited does not; leaving the organisation (member
   and owner) marks it too, the heir without a key waits, no 500
 - the re-encryption in 'on': GET reenc / left, todo / bulk / finish only for owner / list admins, only ciphertexts of the current
   generation, an edit made meanwhile is not overwritten, finish sets e2e_reenc 0 (and only once), state carries e2e_reenc
 - release of every generation to a waiting person
usage: p264b_a_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
LOCAL = os.environ.get("P264A_NOSTART") == "1"  # against a container started by hand


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
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"features": "collab,agents,comments,api", "lang": "en", "tour": "done"})
ORG = dbx("SELECT id FROM orgs WHERE personal_of IS NULL ORDER BY id LIMIT 1")[0][0]
U = {}
for name in ("bob", "carol", "dave", "erin", "frank", "gina"):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", "orgs": [ORG]})
    assert r.ok, r.text
    U[name] = r.json()["id"]
BOB, CAROL, DAVE, ERIN, FRANK, GINA = (U[k] for k in ("bob", "carol", "dave", "erin", "frank", "gina"))
Bo, Ca, Da, Er, Fr, Gi = (sess(k) for k in ("bob", "carol", "dave", "erin", "frank", "gina"))
for s in (Bo, Ca, Da, Er, Fr, Gi):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments"})
KEYS = {}
for s, u in ((A, 1), (Bo, BOB), (Ca, CAROL), (Er, ERIN), (Fr, FRANK), (Gi, GINA)):  # dave has no encryption set up
    KEYS[u] = keys()
    assert s.put(B + "/api/e2e/keys", json=KEYS[u]).ok
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], **H}
tok = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "write"]})
TH = {"Authorization": "Bearer " + tok.json()["token"], **H} if tok.ok else None


def enc_all(todo, gen, ctm=None):
    """Every value of a todo answer as a ciphertext of generation gen (ctm: fixed values per (kind, id, field))."""
    out = {"tasks": [], "comments": [], "notes": [], "sections": [], "fields": []}
    for k in ("tasks", "comments", "notes", "sections"):
        for x in todo[k]:
            y = {"id": x["id"]}
            for f, v in x.items():
                if f != "id" and v is not None:
                    y[f] = (ctm or {}).get((k, x["id"], f)) or ct(gen)
            out[k].append(y)
    for x in todo["fields"]:
        out["fields"].append({"task_id": x["task_id"], "field_id": x["field_id"], "value": ct(gen)})
    return out


def lock_on(lid, people):
    """Switches the lock of lid on for people (all with keys) and encrypts every text with generation 1."""
    r = A.post(B + f"/api/lists/{lid}/e2e/start", json={"keys": [{"user_id": u, "wrapped": wrapped()} for u in people]})
    assert r.ok, r.text
    for _ in range(10):
        j = A.get(B + f"/api/lists/{lid}/e2e/todo").json()
        if not any(j["left"].values()):
            break
        assert A.post(B + f"/api/lists/{lid}/e2e/bulk", json=enc_all(j, j["gen"])).ok
    r = A.post(B + f"/api/lists/{lid}/e2e/finish")
    assert r.ok, r.text


def gen_of(v):
    return json.loads(v[5:])["g"] if isinstance(v, str) and v.startswith("e2e1:") else None


# ================================================================== a list with the lock (generation 1)
L = A.post(B + "/api/lists", json={"name": "Garden plans"}).json()["id"]
LO = A.post(B + "/api/lists", json={"name": "Open list"}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"title": "Plant roses", "list_id": L, "content": "Secret soil mix"}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Old idea", "list_id": L}).json()["id"]
C1 = A.post(B + f"/api/tasks/{T1}/comments", json={"body": "Roses need sun"}).json()["id"]
N1 = A.post(B + f"/api/lists/{L}/notes", json={"title": "Plan", "body": "The long garden plan"}).json()["id"]
S1 = A.post(B + "/api/sections", json={"list_id": L, "name": "Front yard"}).json()["id"]
FT = A.post(B + f"/api/lists/{L}/fields", json={"name": "Variety", "type": "text"}).json()["id"]
assert A.patch(B + f"/api/tasks/{T1}", json={"fields": {str(FT): "Damask"}}).ok
assert A.delete(B + f"/api/tasks/{T2}").ok  # the trash is re-encrypted too
for u, role in ((BOB, "admin"), (CAROL, "edit"), (ERIN, "edit")):
    assert A.put(B + f"/api/lists/{L}/members", json={"user_id": u, "role": role}).ok
lock_on(L, [1, BOB, CAROL, ERIN])
j = A.get(B + f"/api/lists/{L}/e2e").json()
check(j["mode"] == "on" and j["gen"] == 1 and j["reenc"] == 0 and j["rotate"] == 0, "info: on, generation 1, nothing to re-encrypt " + json.dumps({k: j.get(k) for k in ("mode", "gen", "reenc", "rotate")}))
check(isinstance(j.get("left"), dict) and not any(j["left"].values()) and "files" in j["left"] and "msgs" in j["left"],
      "info: left in 'on' for a manager (with files and msgs), all done " + json.dumps(j.get("left")))
check("left" not in Ca.get(B + f"/api/lists/{L}/e2e").json(), "info: no left for a member without the admin role")

# a waiting person (no key) leaves: no rotation (2.64a review case)
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": DAVE, "role": "edit"})
check(r.ok and dbx("SELECT 1 FROM list_key_pending WHERE list_id=? AND user_id=?", (L, DAVE)), "dave (no encryption) waits " + r.text[:200])
assert A.delete(B + f"/api/lists/{L}/members/{DAVE}").ok
check(dbx("SELECT e2e_rotate FROM lists WHERE id=?", (L,))[0][0] == 0, "leave: a waiting person without a key marks no rotation")

# ================================================================== rotate: rights and checks
KS2 = [{"user_id": 1, "wrapped": wrapped()}, {"user_id": BOB, "wrapped": wrapped()}, {"user_id": CAROL, "wrapped": wrapped()}]
check(Ca.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 2, "keys": KS2}).status_code == 403, "rotate: not by a member with the role edit")
check(requests.post(B + f"/api/lists/{L}/e2e/rotate", headers=AGH, json={"gen": 2, "keys": KS2}).status_code in (401, 403, 404), "rotate: not by an agent")
if TH:
    check(requests.post(B + f"/api/lists/{L}/e2e/rotate", headers=TH, json={"gen": 2, "keys": KS2}).status_code in (401, 403, 404), "rotate: not with an API token")
check(Fr.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 2, "keys": KS2}).status_code == 404, "rotate: not for strangers")
r = A.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 3, "keys": KS2})
check(r.status_code == 409 and code(r) == "list_e2e_gen", "rotate: a wrong generation 409 list_e2e_gen " + r.text[:200])
r = A.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 1, "keys": KS2})
check(r.status_code == 409 and code(r) == "list_e2e_gen", "rotate: an old generation 409 list_e2e_gen")
check(A.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 2, "keys": KS2 + [{"user_id": FRANK, "wrapped": wrapped()}]}).status_code == 400,
      "rotate: a stranger in keys 400")
check(A.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 2, "keys": KS2[1:]}).status_code == 400, "rotate: without a key for myself 400")
check(A.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 2, "keys": KS2 + KS2[:1]}).status_code == 400, "rotate: a person twice 400")
check(A.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 2, "keys": [KS2[0], {"user_id": BOB, "wrapped": {"v": 1, "iv": "x", "ct": "y"}}]}).status_code == 400,
      "rotate: a broken wrapped key 400")
check(A.post(B + f"/api/lists/{LO}/e2e/rotate", json={"gen": 1, "keys": KS2[:1]}).status_code == 409, "rotate: not in an open list")
check(dbx("SELECT e2e_gen FROM lists WHERE id=?", (L,))[0][0] == 1 and not dbx("SELECT 1 FROM list_keys WHERE list_id=? AND gen=2", (L,)),
      "rotate: nothing written by the refused calls")

# ================================================================== leaving marks the rotation, the browser of an admin rotates
assert A.delete(B + f"/api/lists/{L}/members/{ERIN}").ok
check(dbx("SELECT e2e_rotate FROM lists WHERE id=?", (L,))[0][0] == 1 and not dbx("SELECT 1 FROM list_keys WHERE list_id=? AND user_id=?", (L, ERIN)),
      "leave: erin's keys go, rotation pending")
check(Er.get(B + f"/api/lists/{L}/e2e").status_code == 404, "leave: erin no longer reads the list")
# bob (list admin) rotates; carol is left out (a changed key not confirmed: H4) -> she waits
r = Bo.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 2, "keys": KS2[:2]})
j = r.json() if r.ok else {}
check(r.ok and j["gen"] == 2 and j["rotate"] == 0 and j["reenc"] == 2 and [k["gen"] for k in j["keys"]] == [1, 2], "rotate: by a list admin, generation 2 " + r.text[:300])
kk = {(x[0], x[1]): x[2] for x in dbx("SELECT gen, user_id, wrapped_by FROM list_keys WHERE list_id=?", (L,))}
check(kk.get((2, 1)) == BOB and kk.get((2, BOB)) == BOB and (2, CAROL) not in kk and (1, CAROL) in kk,
      "rotate: new keys wrapped by bob, carol keeps generation 1 only " + str(sorted(kk)))
check([p["user_id"] for p in j.get("pending", [])] == [CAROL], "rotate: carol (not wrapped for) waits " + json.dumps(j.get("pending")))
wp = dbx("SELECT wrapper_pub FROM list_keys WHERE list_id=? AND gen=2 AND user_id=1", (L,))[0][0]
check(json.loads(wp)["x"] == KEYS[BOB]["pub"]["x"], "rotate: wrapper_pub set by the server (bob's public key)")
r = A.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 2, "keys": KS2[:2]})
check(r.status_code == 409 and code(r) == "list_e2e_gen", "rotate: someone else was faster -> 409 list_e2e_gen")
st = {x["id"]: x for x in Ca.get(B + "/api/state").json()["lists"]}
check(st[L]["e2e_gen"] == 2 and st[L]["e2e_reenc"] == 2 and st[L]["e2e_rotate"] == 0 and st[L]["e2e_mine"] is False,
      "state: e2e_gen, e2e_reenc, e2e_rotate, e2e_mine for carol " + json.dumps({k: st[L].get(k) for k in ("e2e_gen", "e2e_reenc", "e2e_rotate", "e2e_mine")}))
# new texts with the new generation, carol cannot write gen 2 she does not hold -- the server checks only the shape
check(Bo.patch(B + f"/api/tasks/{T1}", json={"title": ct(2)}).ok, "write: a ciphertext of the new generation")
BOB_T1 = dbx("SELECT title FROM tasks WHERE id=?", (T1,))[0][0]

# ================================================================== the re-encryption (todo / bulk / finish in 'on')
j = A.get(B + f"/api/lists/{L}/e2e").json()
check(j["reenc"] == 2 and j["left"]["tasks"] >= 2 and j["left"]["comments"] >= 1 and j["left"]["notes"] >= 1 and j["left"]["sections"] >= 1 and j["left"]["fields"] >= 1,
      "info: what is left of generation 1 " + json.dumps(j["left"]))
check(Ca.get(B + f"/api/lists/{L}/e2e/todo").status_code == 403, "todo: not for a member with the role edit")
check(requests.get(B + f"/api/lists/{L}/e2e/todo", headers=AGH).status_code in (401, 403, 404), "todo: not for an agent")
r = A.get(B + f"/api/lists/{L}/e2e/todo")
td = r.json() if r.ok else {}
t1 = next((x for x in td.get("tasks", []) if x["id"] == T1), {})
check(r.ok and td["mode"] == "on" and td["reenc"] == 2 and gen_of(t1.get("content")) == 1 and t1.get("title") is None and T2 in [x["id"] for x in td["tasks"]],
      "todo: the generation 1 ciphertexts (not the title already of generation 2, trash included) " + r.text[:300])
check("files" in td and "msgs" in td, "todo: files and msgs lists")
check(A.post(B + f"/api/lists/{L}/e2e/bulk", json={"tasks": [{"id": T1, "content": ct(1)}]}).status_code == 400, "bulk: no ciphertext of an old generation")
check(A.post(B + f"/api/lists/{L}/e2e/bulk", json={"tasks": [{"id": T1, "content": "plain"}]}).status_code == 400, "bulk: no plain text in 'on'")
check(Ca.post(B + f"/api/lists/{L}/e2e/bulk", json={"tasks": [{"id": T1, "content": ct(2)}]}).status_code == 403, "bulk: not by a member with the role edit")
r = A.post(B + f"/api/lists/{L}/e2e/finish")
check(r.status_code == 409 and code(r) == "list_e2e_left", "finish: not while old ciphertexts are left")
act0 = dbx("SELECT COUNT(*) FROM activity WHERE task_id=?", (T1,))[0][0]
out = enc_all(td, 2)
for x in out["tasks"]:
    if x["id"] == T1:
        x["title"] = ct(2)  # an older todo would carry it: the edit made meanwhile stays
r = A.post(B + f"/api/lists/{L}/e2e/bulk", json=out)
check(r.ok and not any(r.json()["left"].values()), "bulk: everything on generation 2 " + r.text[:300])
check(dbx("SELECT title FROM tasks WHERE id=?", (T1,))[0][0] == BOB_T1, "bulk: a value already of the current generation is not overwritten")
check(dbx("SELECT COUNT(*) FROM activity WHERE task_id=?", (T1,))[0][0] == act0, "bulk: no history entries")
old = dbx("""SELECT x FROM (SELECT title AS x FROM tasks WHERE list_id=? UNION ALL SELECT content FROM tasks WHERE list_id=?
             UNION ALL SELECT cm.body FROM comments cm JOIN tasks t ON t.id=cm.task_id WHERE t.list_id=?
             UNION ALL SELECT title FROM notes WHERE list_id=? UNION ALL SELECT body FROM notes WHERE list_id=?
             UNION ALL SELECT name FROM sections WHERE list_id=?
             UNION ALL SELECT v.value FROM task_field_values v JOIN tasks t ON t.id=v.task_id WHERE t.list_id=?) q WHERE x<>''""", (L,) * 7)
check(old and all(gen_of(x[0]) == 2 for x in old), "db: every text of the list on generation 2 " + str([gen_of(x[0]) for x in old]))
r = A.post(B + f"/api/lists/{L}/e2e/finish")
check(r.ok and r.json()["mode"] == "on" and tuple(dbx("SELECT e2e, e2e_reenc FROM lists WHERE id=?", (L,))[0]) == ("on", 0), "finish: re-encryption done " + r.text[:200])
check(A.post(B + f"/api/lists/{L}/e2e/finish").status_code == 409, "finish: only once")
check(A.get(B + f"/api/lists/{L}/e2e").json()["reenc"] == 0, "info: reenc 0")
# a plain leftover in 'on' (there should be none): the todo hands it out, bulk encrypts it
dbx("UPDATE comments SET body='left plain' WHERE id=?", (C1,))
td = A.get(B + f"/api/lists/{L}/e2e/todo").json()
check([x["body"] for x in td["comments"]] == ["left plain"] and td["left"]["comments"] == 1, "todo: a plain leftover in 'on' " + json.dumps(td["comments"]))
check(A.post(B + f"/api/lists/{L}/e2e/bulk", json={"comments": [{"id": C1, "body": ct(2)}]}).ok and gen_of(dbx("SELECT body FROM comments WHERE id=?", (C1,))[0][0]) == 2,
      "bulk: the leftover encrypted")
# an outdated tab writes a ciphertext of the old generation after the re-encryption: the next run picks it up
assert Bo.patch(B + f"/api/tasks/{T1}", json={"content": ct(1)}).ok
j = A.get(B + f"/api/lists/{L}/e2e").json()
check(j["reenc"] == 0 and j["left"]["tasks"] == 1, "info: a late ciphertext of generation 1 is work again " + json.dumps(j["left"]))
check(A.post(B + f"/api/lists/{L}/e2e/bulk", json={"tasks": [{"id": T1, "content": ct(2)}]}).ok and gen_of(dbx("SELECT content FROM tasks WHERE id=?", (T1,))[0][0]) == 2,
      "bulk: re-encrypted without a running key change")

# ================================================================== release of every generation
r = A.post(B + f"/api/lists/{L}/e2e/keys", json={"keys": [{"user_id": CAROL, "gen": 1, "wrapped": wrapped()}, {"user_id": CAROL, "gen": 2, "wrapped": wrapped()}]})
check(r.ok and r.json()["released"] == [CAROL] and not dbx("SELECT 1 FROM list_key_pending WHERE list_id=? AND user_id=?", (L, CAROL)), "release: carol gets generation 2 " + r.text[:200])
check(sorted(k["gen"] for k in Ca.get(B + f"/api/lists/{L}/e2e").json()["keys"]) == [1, 2], "release: carol holds both generations")
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": GINA, "role": "edit"})
r = A.post(B + f"/api/lists/{L}/e2e/keys", json={"keys": [{"user_id": GINA, "gen": 1, "wrapped": wrapped()}, {"user_id": GINA, "gen": 2, "wrapped": wrapped()}]})
check(r.ok and sorted(k["gen"] for k in Gi.get(B + f"/api/lists/{L}/e2e").json()["keys"]) == [1, 2], "release: a new member after the key change gets every generation " + r.text[:200])

# ================================================================== a manual key change (no one left) and the race
r = A.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 3, "keys": [{"user_id": u, "wrapped": wrapped()} for u in (1, BOB, CAROL, GINA)]})
check(r.ok and r.json()["gen"] == 3 and r.json()["reenc"] == 3 and not r.json()["pending"], "rotate: also without a pending rotation (button) " + r.text[:200])
import threading  # noqa: E402
res = {}


def rot(name, s):
    res[name] = s.post(B + f"/api/lists/{L}/e2e/rotate", json={"gen": 4, "keys": [{"user_id": u, "wrapped": wrapped()} for u in (1, BOB, CAROL, GINA)]})


ths = [threading.Thread(target=rot, args=("a", A)), threading.Thread(target=rot, args=("b", Bo))]
for t in ths:
    t.start()
for t in ths:
    t.join()
codes = sorted(x.status_code for x in res.values())
check(codes == [200, 409] and all(code(x) == "list_e2e_gen" for x in res.values() if x.status_code == 409), f"rotate: two at the same moment, one wins {codes}")
check(dbx("SELECT e2e_gen FROM lists WHERE id=?", (L,))[0][0] == 4 and dbx("SELECT COUNT(*) FROM list_keys WHERE list_id=? AND gen=4", (L,))[0][0] == 4,
      "rotate: generation 4 exactly once")

# ================================================================== leaving the organisation (member and owner)
LG = Bo.post(B + "/api/lists", json={"name": "Team secrets"}).json()["id"]
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, LG))
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, L))
A.post(B + "/api/tasks", json={"title": "x", "list_id": LG})
assert Bo.put(B + f"/api/lists/{LG}/members", json={"user_id": FRANK, "role": "edit"}).ok
r = Bo.post(B + f"/api/lists/{LG}/e2e/start", json={"keys": [{"user_id": u, "wrapped": wrapped()} for u in (BOB, FRANK)]})
assert r.ok, r.text
td = Bo.get(B + f"/api/lists/{LG}/e2e/todo").json()
assert Bo.post(B + f"/api/lists/{LG}/e2e/bulk", json=enc_all(td, td["gen"])).ok
assert Bo.post(B + f"/api/lists/{LG}/e2e/finish").ok
# a member leaves the organisation: L marks the rotation (gina held a key)
r = A.delete(B + f"/api/orgs/{ORG}/members/{GINA}")
check(r.ok and dbx("SELECT e2e_rotate FROM lists WHERE id=?", (L,))[0][0] == 4 and not dbx("SELECT 1 FROM list_keys WHERE list_id=? AND user_id=?", (L, GINA)),
      "org exit of a member: rotation pending, keys gone " + r.text[:200])
# the owner of LG leaves the organisation: the list goes to an organisation admin (alice, no key) who waits, rotation pending
r = Bo.delete(B + f"/api/orgs/{ORG}/members/{BOB}")
check(r.status_code == 200, "org exit of an owner: no 500 " + str(r.status_code) + " " + r.text[:200])
lg = dbx("SELECT owner_id, e2e, e2e_rotate FROM lists WHERE id=?", (LG,))[0]
check(lg[0] == 1 and lg[1] == "on" and lg[2] == 1, "org exit of an owner: heir alice, still locked, rotation pending " + str(lg))
check(dbx("SELECT 1 FROM list_key_pending WHERE list_id=? AND user_id=1", (LG,)) and not dbx("SELECT 1 FROM list_keys WHERE list_id=? AND user_id=?", (LG, BOB)),
      "org exit of an owner: the heir without a key waits, the leaver's keys go")
check(dbx("SELECT e2e_rotate FROM lists WHERE id=?", (L,))[0][0] == 4, "org exit of a list admin: L rotation pending")
r = A.post(B + f"/api/lists/{LG}/e2e/rotate", json={"gen": 2, "keys": [{"user_id": 1, "wrapped": wrapped()}]})
check(r.status_code == 409 and code(r) != "list_e2e_gen", "rotate: not by the heir without a key " + r.text[:200])
# frank (member, key of generation 1) cannot rotate (role edit); after alice makes him admin he can
assert A.put(B + f"/api/lists/{LG}/members", json={"user_id": FRANK, "role": "admin"}).ok
r = Fr.post(B + f"/api/lists/{LG}/e2e/rotate", json={"gen": 2, "keys": [{"user_id": FRANK, "wrapped": wrapped()}, {"user_id": 1, "wrapped": wrapped()}]})
check(r.ok and r.json()["gen"] == 2 and not r.json()["pending"] and tuple(dbx("SELECT e2e_rotate, e2e_reenc FROM lists WHERE id=?", (LG,))[0]) == (0, 2),
      "rotate: a list admin wraps for the heir too (waiting list cleared) " + r.text[:200])

print(f"p264b_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
