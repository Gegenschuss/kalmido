#!/usr/bin/env python3
"""2.64.3 API tests, part A (#1817: the lock per knowledge space, stage 3), own container (start.sh).
Invented names only. The server never sees a space key or a plain text; these tests send ciphertext-shaped values and wrapped keys
of the right shape (the WebCrypto round trip is in the UI suite of part B).
 - GET / start (prepare, rights: organisation admins only, private space only its owner, agents / API tokens 403; a missing key
   409 with the names; members without encryption on the waiting list), a second start 409
 - encrypting: page writes 409 busy, todo / bulk / finish (trash included), only ciphertexts of the current generation
 - 'on': plain writes 409 wiki_e2e, ciphertexts ok, e2e1: in an open space 400, template_id 400, no links on the server, search /
   mentions leave the space out, export / import / move 409, bodies=1, backlinks empty, plain-text sweep after finish
 - joining the organisation -> waiting list, release only by admins + News, a key holder leaving -> rotation pending, a waiting
   person leaving -> none
 - rotate (409 wiki_e2e_gen, a stranger 400) + re-encryption in 'on' (an edit made meanwhile stays), finish once
 - stop (password), decrypting with a name taken twice -> " (2)" + renamed, links rebuilt, keys gone
usage: p264c_a_api_test.py <datadir>"""
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
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)
LOCAL = os.environ.get("P264A_NOSTART") == "1"  # against a container started by hand


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


def ct(gen=1, n=48):
    """A ciphertext of a space with the lock (shape only)."""
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(n)}, separators=(",", ":"))


if not LOCAL:
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"features": "collab,agents,comments,api", "lang": "en", "tour": "done"})
ORG = dbx("SELECT id FROM orgs WHERE personal_of IS NULL ORDER BY id LIMIT 1")[0][0]
SP = f"org:{ORG}"
U = {}
for name in ("bob", "carol", "dave", "erin", "frank"):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123",
                                       **({"orgs": [ORG]} if name != "frank" else {"email": "frank@example.com"})})
    assert r.ok, r.text
    U[name] = r.json()["id"]
BOB, CAROL, DAVE, ERIN, FRANK = (U[k] for k in ("bob", "carol", "dave", "erin", "frank"))
Bo, Ca, Da, Er, Fr = (sess(k) for k in ("bob", "carol", "dave", "erin", "frank"))
for s in (Bo, Ca, Da, Er, Fr):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments"})
dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG, FRANK))  # frank joins later
for s, u in ((A, 1), (Bo, BOB), (Ca, CAROL), (Er, ERIN), (Fr, FRANK)):  # dave has no encryption set up
    assert s.put(B + "/api/e2e/keys", json=keys()).ok
assert A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": CAROL, "role": "admin"}).ok
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], **H}
tok = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "write"]})
TH = {"Authorization": "Bearer " + tok.json()["token"], **H} if tok.ok else None

T = A.post(B + "/api/tasks", json={"title": "Order the props"}).json()["id"]
PG = {}
for key, path, text in (("check", "Processes/Checklist", f"Hello world, see [[Other]] and #{T}"), ("other", "Other", "plain other text"),
                        ("tpl", "Templates/Daily", "---\ntags: [daily]\n---\nDaily notes"), ("trash", "Trash me", "gone soon"),
                        ("empty", "Empty", "")):
    r = A.post(B + "/api/wiki/pages", json={"space": SP, "path": path, "body": text})
    assert r.status_code == 201, r.text
    PG[key] = r.json()["id"]
assert A.delete(B + f"/api/wiki/pages/{PG['trash']}").ok
check(len(dbx("SELECT 1 FROM wiki_links WHERE from_id=?", (PG["check"],))) == 2, "open space: links are kept on the server")
OWN = Bo.post(B + "/api/wiki/pages", json={"space": "private", "path": "Diary", "body": f"my plain diary #{T}"}).json()["id"]


def pages_of(sp=SP, s=A, **kw):
    return {p["id"]: p for p in s.get(B + "/api/wiki", params={"space": sp, **kw}).json()["pages"]}


# ---------------------------------------------------------------- GET, prepare, start
r = A.get(B + "/api/wiki/e2e", params={"space": SP})
d = r.json() if r.ok else {}
check(r.ok and d["mode"] is None and d["space_id"] is None and d["can_manage"] is True and d["left"] == {"pages": 0},
      "GET: open, no row yet, alice manages " + r.text[:200])
mem = {m["user_id"]: m for m in d.get("members", [])}
check(set(mem) == {1, BOB, CAROL, DAVE, ERIN} and ag["id"] not in mem, "GET: members = the people of the organisation, no agent")
check(mem.get(DAVE, {}).get("has_keys") is False and mem.get(BOB, {}).get("pub", {}).get("kty") == "EC", "GET: has_keys + public keys")
check(Bo.get(B + "/api/wiki/e2e", params={"space": SP}).json()["can_manage"] is False, "GET: a member does not manage")
check(requests.get(B + "/api/wiki/e2e", params={"space": SP}, headers=AGH).status_code in (401, 403), "GET: agent refused")
if TH:
    check(requests.get(B + "/api/wiki/e2e", params={"space": SP}, headers=TH).status_code in (401, 403), "GET: API token refused")
check(Fr.get(B + "/api/wiki/e2e", params={"space": SP}).status_code == 404, "GET: a space of another organisation 404")
check(Bo.post(B + "/api/wiki/e2e/start", json={"space": SP, "prepare": True}).status_code == 403, "prepare: a member 403")
r = A.post(B + "/api/wiki/e2e/start", json={"space": SP, "prepare": True})
SID = r.json().get("space_id") if r.ok else None
check(r.ok and isinstance(SID, int) and r.json()["mode"] is None, "prepare: the row of the space, still open " + r.text[:200])
check(A.post(B + "/api/wiki/e2e/start", json={"space": SP, "prepare": True}).json().get("space_id") == SID, "prepare twice: the same row")
W = {u: wrapped() for u in (1, BOB, CAROL, ERIN)}
r = Bo.post(B + "/api/wiki/e2e/start", json={"space": SP, "keys": [{"user_id": u, "wrapped": w} for u, w in W.items()]})
check(r.status_code == 403, "start: a member without the admin role 403")
r = requests.post(B + "/api/wiki/e2e/start", json={"space": SP, "keys": []}, headers=AGH)
check(r.status_code in (401, 403), "start: agent refused")
r = A.post(B + "/api/wiki/e2e/start", json={"space": SP, "keys": [{"user_id": 1, "wrapped": W[1]}]})
check(r.status_code == 409 and code(r) == "wiki_e2e_keys" and "Bob" in r.json()["error"] and set(r.json()["missing"]) == {BOB, CAROL, ERIN},
      "start: a missing key 409 with the names " + r.text[:200])
r = A.post(B + "/api/wiki/e2e/start", json={"space": SP, "keys": [{"user_id": u, "wrapped": w} for u, w in W.items()] + [{"user_id": DAVE, "wrapped": wrapped()}]})
check(r.status_code == 400, "start: a key for a person without encryption 400")
r = A.post(B + "/api/wiki/e2e/start", json={"space": SP, "keys": [{"user_id": u, "wrapped": w} for u, w in W.items()]})
d = r.json() if r.ok else {}
check(r.ok and d["mode"] == "encrypting" and d["gen"] == 1 and d["space_id"] == SID and [p["user_id"] for p in d["pending"]] == [DAVE],
      "start: encrypting, generation 1, dave waits (decision E7) " + r.text[:300])
check(len(d.get("keys", [])) == 1 and d["keys"][0]["gen"] == 1 and d["keys"][0]["wrapped_by"] == 1, "start: my wrapped key only")
check(dbx("SELECT user_id FROM wiki_key_pending WHERE space_id=?", (SID,)) == [(DAVE,)], "start: the waiting list in the table")
check(A.post(B + "/api/wiki/e2e/start", json={"space": SP, "keys": [{"user_id": u, "wrapped": w} for u, w in W.items()]}).status_code == 409,
      "start twice: 409")

# ---------------------------------------------------------------- encrypting
r = Bo.patch(B + f"/api/wiki/pages/{PG['other']}", json={"body": "changed while encrypting"})
check(r.status_code == 409 and code(r) == "wiki_e2e_busy", "encrypting: a page write 409 busy " + r.text[:200])
r = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "New while busy"})
check(r.status_code == 409 and code(r) == "wiki_e2e_busy", "encrypting: a new page 409 busy")
check(Bo.get(B + "/api/wiki/e2e/todo", params={"space": SP}).status_code == 403, "todo: not for a member who did not start it")
r = A.get(B + "/api/wiki/e2e/todo", params={"space": SP})
td = r.json() if r.ok else {"pages": []}
ids = {p["id"]: p for p in td["pages"]}
check(r.ok and set(ids) == {PG["check"], PG["other"], PG["tpl"], PG["trash"], PG["empty"]} and td["left"]["pages"] == 5,
      "todo: every page incl. the trash " + r.text[:300])
check(ids.get(PG["empty"], {}).get("body", 1) is None and ids.get(PG["check"], {}).get("body", "").startswith("Hello"), "todo: an empty text is null")
check(A.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": [{"id": PG["other"], "body": "plain"}]}).status_code == 400, "bulk: plain text 400")
check(A.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": [{"id": PG["other"], "body": ct(2)}]}).status_code == 400, "bulk: another generation 400")
check(A.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": [{"id": PG["other"], "path": ""}]}).status_code == 400, "bulk: empty path 400")
check(A.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": [{"id": OWN, "body": ct(1)}]}).status_code == 400, "bulk: a page of another space 400")
check(A.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": [{"id": PG["other"]}] * 201}).status_code == 400, "bulk: at most 200 pages")
r = A.post(B + "/api/wiki/e2e/finish", json={"space": SP})
check(r.status_code == 409 and code(r) == "wiki_e2e_left" and r.json()["left"]["pages"] == 5, "finish: 409 while pages are left")
ENC = {p["id"]: {"id": p["id"], "path": ct(1) if p["path"] else None, "body": ct(1, 96) if p["body"] else None} for p in td["pages"]}
r = A.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": list(ENC.values())})
check(r.ok and r.json()["left"] == {"pages": 0}, "bulk: all pages converted " + r.text[:200])
check(A.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": list(ENC.values())}).ok, "bulk: repeating a call is harmless")
r = A.post(B + "/api/wiki/e2e/finish", json={"space": SP})
check(r.ok and r.json()["mode"] == "on", "finish: on " + r.text[:200])
sp_ids = [x[0] for x in dbx("SELECT id FROM wiki_pages WHERE org_id=?", (ORG,))]
q = ",".join("?" * len(sp_ids))
check(not dbx(f"SELECT 1 FROM wiki_links WHERE from_id IN ({q})", sp_ids), "on: no links of the space on the server")
check(not dbx(f"SELECT 1 FROM wiki_pages WHERE id IN ({q}) AND attrs<>'{{}}'", sp_ids), "on: no frontmatter copy")
leak = []
for word in ("Hello world", "plain other", "Checklist", "Daily notes", "Trash me", "gone soon", "daily"):
    like = f"%{word}%"
    for t, col in (("wiki_pages", "path"), ("wiki_pages", "body"), ("wiki_pages", "attrs"), ("wiki_links", "to_path"),
                   ("notifications", "data"), ("list_activity", "data")):
        if dbx(f"SELECT 1 FROM {t} WHERE {col}::text ILIKE ?" + (" AND org_id IS NOT NULL" if t == "wiki_pages" else ""), (like,)):
            leak.append((word, t, col))
check(not leak, "plain-text sweep after finish: " + str(leak))

# ---------------------------------------------------------------- on: the page routes
r = Bo.patch(B + f"/api/wiki/pages/{PG['other']}", json={"body": "a plain edit"})
check(r.status_code == 409 and code(r) == "wiki_e2e", "on: a plain text 409 wiki_e2e " + r.text[:200])
r = Bo.patch(B + f"/api/wiki/pages/{PG['other']}", json={"path": "Renamed plain"})
check(r.status_code == 409 and code(r) == "wiki_e2e", "on: a plain name 409")
r = Bo.patch(B + f"/api/wiki/pages/{PG['other']}", json={"body": ct(5)})
check(r.status_code == 409 and code(r) == "wiki_e2e", "on: a ciphertext of an unknown generation 409")
X1 = ct(1, 120)
r = Bo.patch(B + f"/api/wiki/pages/{PG['other']}", json={"body": X1, "path": ct(1)})
check(r.ok and r.json()["body"] == X1 and r.json()["attrs"] == {} and r.json()["template"] is False, "on: ciphertexts are stored " + r.text[:200])
r = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": ct(1), "body": ct(1)})
NEWP = r.json().get("id") if r.status_code == 201 else None
check(r.status_code == 201, "on: a new page with ciphertexts " + r.text[:200])
check(Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": "Plain new"}).status_code == 409, "on: a new plain page 409")
r = Bo.post(B + "/api/wiki/pages", json={"space": SP, "path": ct(1), "template_id": PG["tpl"]})
check(r.status_code == 400 and code(r) == "wiki_e2e", "on: template_id 400 (the browser copies the text)")
check(Bo.patch(B + f"/api/wiki/pages/{PG['other']}", json={"body": ct(1, 40) + "x"}).status_code == 409, "on: a broken ciphertext 409")
r = Bo.post(B + "/api/wiki/pages", json={"space": "private", "path": ct(1)})
check(r.status_code == 400 and code(r) == "wiki_e2e_open", "open space: e2e1: 400 " + r.text[:200])
check(Bo.patch(B + f"/api/wiki/pages/{OWN}", json={"body": ct(1)}).status_code == 400, "open space: an e2e1: text 400")
if TH:
    check(requests.patch(B + f"/api/wiki/pages/{PG['other']}", json={"body": ct(1)}, headers=TH).status_code in (401, 403),
          "on: an API token does not write")
check(not dbx("SELECT 1 FROM wiki_links WHERE from_id=?", (NEWP,)), "on: a new page leaves no links")
r = A.post(B + "/api/wiki/move", json={"space": SP, "from": "Processes", "to": "Ops"})
check(r.status_code == 409 and code(r) == "wiki_e2e", "on: move 409")
r = A.get(B + "/api/wiki/export", params={"space": SP})
check(r.status_code == 409 and code(r) == "wiki_e2e", "on: export 409")
r = A.post(B + "/api/wiki/import", params={"space": SP}, files={"file": ("w.zip", b"PK\x05\x06" + b"\0" * 18)})
check(r.status_code == 409 and code(r) == "wiki_e2e", "on: import 409")
srch = Bo.get(B + "/api/wiki/search", params={"q": "e2e1"}).json()["pages"]
check(not srch, "on: search leaves the space out " + str(srch)[:200])
check([p["id"] for p in Bo.get(B + "/api/wiki/search", params={"q": "diary"}).json()["pages"]] == [OWN], "search still finds open spaces")
mn = [p["id"] for p in A.get(B + "/api/wiki/mentions", params={"task": T}).json()["pages"]]
check(PG["check"] not in mn, "on: mentions leave the space out")
r = Bo.get(B + "/api/wiki", params={"space": SP})
e = r.json().get("e2e") or {}
check(e.get("mode") == "on" and e.get("mine") is True and e.get("can_manage") is False and "pending" not in e and e.get("space_id") == SID,
      "index: the e2e block of a member " + str(e))
e = A.get(B + "/api/wiki", params={"space": SP}).json().get("e2e") or {}
check(e.get("pending") == 1 and e.get("can_manage") is True, "index: managers see the number of waiting people")
check(Bo.get(B + "/api/wiki", params={"space": "private"}).json().get("e2e") is None, "index: an open space has e2e null")
pb = pages_of(bodies="1")
check(pb.get(PG["other"], {}).get("body") == X1 and all(p["attrs"] == {} and p["template"] is False for p in pb.values()),
      "index bodies=1: the ciphertexts for the local search")
check("body" not in pages_of(sp="private", s=Bo, bodies="1").get(OWN, {"body": 0}), "index bodies=1: not for an open space")
r = A.get(B + f"/api/wiki/pages/{PG['check']}")
check(r.ok and r.json()["backlinks"] == [], "on: backlinks are found in the browser")
check(Bo.get(B + f"/api/e2e/pub/{ERIN}").ok, "pub: a colleague of a locked space")
check(A.delete(B + f"/api/wiki/pages/{NEWP}").ok and A.post(B + "/api/wiki/restore", json={"ids": [NEWP]}).json()["ids"] == [NEWP],
      "on: trash and restore stay allowed")

# ---------------------------------------------------------------- members: join, release, leave
r = A.put(B + f"/api/orgs/{ORG}/members", json={"email": "frank@example.com", "role": "member"})  # an admin adds by address
assert r.ok and dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (ORG, FRANK)), r.text
check(dbx("SELECT 1 FROM wiki_key_pending WHERE space_id=? AND user_id=?", (SID, FRANK)), "join: frank waits for the key")
d = A.get(B + "/api/wiki/e2e", params={"space": SP}).json()
check({p["user_id"] for p in d["pending"]} == {DAVE, FRANK}, "GET: the waiting list " + str(d["pending"])[:200])
r = Bo.post(B + "/api/wiki/e2e/keys", json={"space": SP, "keys": [{"user_id": FRANK, "gen": 1, "wrapped": wrapped()}]})
check(r.status_code == 403, "keys: only admins release")
r = A.post(B + "/api/wiki/e2e/keys", json={"space": SP, "keys": [{"user_id": DAVE, "gen": 1, "wrapped": wrapped()}]})
check(r.status_code == 409, "keys: not to a person without encryption")
r = A.post(B + "/api/wiki/e2e/keys", json={"space": SP, "keys": [{"user_id": FRANK, "gen": 2, "wrapped": wrapped()}]})
check(r.status_code == 409, "keys: not a generation I do not hold")
r = A.post(B + "/api/wiki/e2e/keys", json={"space": SP, "keys": [{"user_id": FRANK, "gen": 1, "wrapped": wrapped()}]})
check(r.ok and r.json()["released"] == [FRANK], "keys: released " + r.text[:200])
check(not dbx("SELECT 1 FROM wiki_key_pending WHERE space_id=? AND user_id=?", (SID, FRANK)), "keys: frank no longer waits")
kp = dbx("SELECT wrapped_by, wrapper_pub FROM wiki_keys WHERE space_id=? AND user_id=? AND gen=1", (SID, FRANK))
mine_pub = dbx("SELECT pub FROM e2e_keys WHERE user_id=1")[0][0]
check(kp and kp[0][0] == 1 and json.loads(kp[0][1]) == json.loads(mine_pub), "keys: the server sets the wrapper's public key")
nw = dbx("SELECT data FROM notifications WHERE user_id=? AND kind='wiki_e2e_key'", (FRANK,))
check(nw and json.loads(nw[0][0]).get("org_id") == ORG and json.loads(nw[0][0]).get("by") == 1, "keys: frank gets a News entry " + str(nw))
fk = Fr.get(B + "/api/wiki/e2e", params={"space": SP}).json()
check([k["gen"] for k in fk["keys"]] == [1] and fk["can_manage"] is False, "frank sees his wrapped key")
r = Da.delete(B + f"/api/orgs/{ORG}/members/{DAVE}")
check(r.ok and dbx("SELECT e2e_rotate FROM wiki_spaces WHERE id=?", (SID,))[0][0] == 0, "leave: a waiting person -> no rotation " + r.text[:200])
check(not dbx("SELECT 1 FROM wiki_key_pending WHERE space_id=? AND user_id=?", (SID, DAVE)), "leave: the waiting row goes")
r = A.delete(B + f"/api/orgs/{ORG}/members/{ERIN}")
check(r.ok and dbx("SELECT e2e_rotate FROM wiki_spaces WHERE id=?", (SID,))[0][0] == 1, "removal of a key holder -> rotation pending " + r.text[:200])
check(not dbx("SELECT 1 FROM wiki_keys WHERE space_id=? AND user_id=?", (SID, ERIN)), "removal: the keys of the leaver go")
check(Er.get(B + "/api/wiki/e2e", params={"space": SP}).status_code == 404, "the leaver no longer sees the space")
check(A.get(B + "/api/wiki", params={"space": SP}).json()["e2e"]["rotate"] == 1, "index: rotate pending")

# ---------------------------------------------------------------- rotate + re-encryption in 'on'
W2 = [{"user_id": u, "wrapped": wrapped()} for u in (1, BOB, CAROL)]  # frank is not wrapped for: he waits again
check(Bo.post(B + "/api/wiki/e2e/rotate", json={"space": SP, "gen": 2, "keys": W2}).status_code == 403, "rotate: a member 403")
r = A.post(B + "/api/wiki/e2e/rotate", json={"space": SP, "gen": 3, "keys": W2})
check(r.status_code == 409 and code(r) == "wiki_e2e_gen" and r.json()["gen"] == 1, "rotate: wrong generation 409 wiki_e2e_gen")
r = A.post(B + "/api/wiki/e2e/rotate", json={"space": SP, "gen": 2, "keys": W2 + [{"user_id": ERIN, "wrapped": wrapped()}]})
check(r.status_code == 400, "rotate: a stranger in keys 400")
r = A.post(B + "/api/wiki/e2e/rotate", json={"space": SP, "gen": 2, "keys": W2})
d = r.json() if r.ok else {}
check(r.ok and d["gen"] == 2 and d["rotate"] == 0 and d["reenc"] == 2 and [p["user_id"] for p in d["pending"]] == [FRANK],
      "rotate: generation 2, frank waits, re-encryption due " + r.text[:300])
check(d.get("left", {}).get("pages") == 6, "rotate: every page is left for the re-encryption " + str(d.get("left")))
r = Ca.post(B + "/api/wiki/e2e/rotate", json={"space": SP, "gen": 2, "keys": W2})
check(r.status_code == 409 and code(r) == "wiki_e2e_gen", "rotate: the second one at the same moment 409")
X2 = ct(2, 64)
assert Bo.patch(B + f"/api/wiki/pages/{PG['other']}", json={"body": X2}).ok  # an edit made meanwhile (generation 2)
r = Ca.get(B + "/api/wiki/e2e/todo", params={"space": SP})
td = r.json() if r.ok else {"pages": []}
check(r.ok and td["reenc"] == 2 and len(td["pages"]) == 6 and all((p["path"] or "e2e1:").startswith("e2e1:") for p in td["pages"]),
      "todo in 'on': the pages of generation 1 (an admin continues) " + r.text[:200])
oth = [p for p in td["pages"] if p["id"] == PG["other"]]
check(oth and oth[0]["body"] is None and oth[0]["path"], "todo: a value of generation 2 is not listed again")
check(Ca.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": [{"id": PG["check"], "body": ct(1)}]}).status_code == 400, "bulk in 'on': an old generation 400")
r = Ca.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": [{"id": p["id"], "path": ct(2), "body": ct(2) if p["id"] != PG["empty"] else ""} for p in td["pages"]]})
check(r.ok and r.json()["left"] == {"pages": 0}, "bulk in 'on': re-encrypted " + r.text[:200])
check(dbx("SELECT body FROM wiki_pages WHERE id=?", (PG["other"],))[0][0] == X2, "bulk in 'on': the edit made meanwhile stays")
r = Ca.post(B + "/api/wiki/e2e/finish", json={"space": SP})
check(r.ok and dbx("SELECT e2e_reenc FROM wiki_spaces WHERE id=?", (SID,))[0][0] == 0, "finish in 'on': e2e_reenc 0 " + r.text[:200])
check(Ca.post(B + "/api/wiki/e2e/finish", json={"space": SP}).status_code == 409, "finish in 'on': only once")
assert Bo.patch(B + f"/api/wiki/pages/{PG['other']}", json={"body": ct(1)}).ok  # a tab not reloaded writes generation 1
check(dbx("SELECT e2e_reenc FROM wiki_spaces WHERE id=?", (SID,))[0][0] == 2, "an old generation written later makes the re-encryption due again")
r = A.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": [{"id": PG["other"], "body": ct(2)}]})
check(r.ok and A.post(B + "/api/wiki/e2e/finish", json={"space": SP}).ok, "re-encryption again: bulk + finish")

# ---------------------------------------------------------------- stop + decrypting
check(Bo.post(B + "/api/wiki/e2e/stop", json={"space": SP, "password": "password123"}).status_code == 403, "stop: a member 403")
check(A.post(B + "/api/wiki/e2e/stop", json={"space": SP, "password": "wrong"}).status_code in (401, 403), "stop: asks for the password")
r = A.post(B + "/api/wiki/e2e/stop", json={"space": SP, "password": "password123"})
check(r.ok and r.json()["mode"] == "decrypting", "stop: decrypting " + r.text[:200])
r = Bo.patch(B + f"/api/wiki/pages/{PG['other']}", json={"body": ct(2)})
check(r.status_code == 409 and code(r) == "wiki_e2e_busy", "decrypting: page writes 409 busy")
td = A.get(B + "/api/wiki/e2e/todo", params={"space": SP}).json()
check(len(td["pages"]) == 6, "decrypting: todo lists the ciphertexts")
PLAIN = {PG["check"]: ("Same", f"Hello again, see [[Other]] and #{T}"), PG["other"]: ("Same", "other page"),
         PG["tpl"]: ("Templates/Daily", "---\ntags: [daily]\n---\nDaily notes"), PG["trash"]: ("Same", "in the trash"),
         PG["empty"]: ("Empty", None), NEWP: ("New page", "new")}
check(A.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": [{"id": NEWP, "body": ct(2)}]}).status_code == 400, "decrypting: a ciphertext 400")
order = [PG["check"], PG["other"], PG["tpl"], PG["trash"], PG["empty"], NEWP]
r = A.post(B + "/api/wiki/e2e/bulk", json={"space": SP, "pages": [{"id": i, "path": PLAIN[i][0], **({"body": PLAIN[i][1]} if PLAIN[i][1] is not None else {})} for i in order]})
d = r.json() if r.ok else {}
check(r.ok and d["renamed"] == [{"id": PG["other"], "path": "Same (2)"}] and d["left"] == {"pages": 0}, "decrypting: a name taken twice -> (2) " + r.text[:300])
check(dbx("SELECT path FROM wiki_pages WHERE id=?", (PG["trash"],))[0][0] == "Same", "decrypting: a page in the trash keeps its name")
r = A.post(B + "/api/wiki/e2e/finish", json={"space": SP})
check(r.ok and r.json()["mode"] is None, "finish: open again " + r.text[:200])
sp = dbx("SELECT e2e, e2e_rotate, e2e_reenc FROM wiki_spaces WHERE id=?", (SID,))[0]
check(tuple(sp) == (None, 0, 0) and not dbx("SELECT 1 FROM wiki_keys WHERE space_id=?", (SID,))
      and not dbx("SELECT 1 FROM wiki_key_pending WHERE space_id=?", (SID,)), "finish: keys and waiting list gone " + str(sp))
lk = {(x[0], x[1]) for x in dbx("SELECT to_path, to_task FROM wiki_links WHERE from_id=?", (PG["check"],))}
check(lk == {("other", None), (None, T)}, "decrypting: links rebuilt " + str(lk))
check(pages_of()[PG["tpl"]]["attrs"].get("tags") == ["daily"] and pages_of()[PG["tpl"]]["template"] is True, "decrypting: frontmatter + template back")
check(PG["check"] in [p["id"] for p in A.get(B + "/api/wiki/mentions", params={"task": T}).json()["pages"]], "open again: mentions")
check(A.get(B + "/api/wiki/export", params={"space": SP}).ok, "open again: export")

# ---------------------------------------------------------------- private space
r = Bo.post(B + "/api/wiki/e2e/start", json={"space": "private", "keys": [{"user_id": BOB, "wrapped": wrapped()}, {"user_id": 1, "wrapped": wrapped()}]})
check(r.status_code == 400, "private: a key for somebody else 400")
r = Bo.post(B + "/api/wiki/e2e/start", json={"space": "private", "keys": [{"user_id": BOB, "wrapped": wrapped()}]})
d = r.json() if r.ok else {}
check(r.ok and d["mode"] == "encrypting" and d["can_manage"] is True and [m["user_id"] for m in d["members"]] == [BOB],
      "private: only its owner " + r.text[:200])
check(A.get(B + "/api/wiki/e2e", params={"space": "private"}).json()["mode"] is None, "private: alice's own space stays open")
check(Bo.get(B + "/api/wiki/e2e/todo", params={"space": "private"}).json()["left"]["pages"] == 1, "private: todo of bob's page")
check(OWN not in [p["id"] for p in Bo.get(B + "/api/wiki/search", params={"q": "diary"}).json()["pages"]], "private encrypting: search leaves it out")

# ---------------------------------------------------------------- 2.64.3 review 1 M1: no ciphertext-like values in open spaces
import io as _io, zipfile as _zf
EP = Er.post(B + "/api/wiki/pages", json={"space": "private", "path": "Odd", "body": "x"}).json()["id"]
dbx("UPDATE wiki_pages SET body=? WHERE id=?", (ct(1), EP))  # as if written before 2.64.3
r = Er.post(B + "/api/wiki/pages", json={"space": "private", "path": "From odd", "template_id": EP})
check(r.status_code == 400, "M1: a ciphertext template is never copied into an open space " + r.text[:200])
r = Er.post(B + "/api/wiki/move", json={"space": "private", "from": "Odd", "to": "e2e1:x"})
check(r.status_code == 400, "M1: no plain name with the ciphertext prefix (move) " + r.text[:200])
r = Er.post(B + "/api/wiki/pages", json={"space": "private", "path": "e2e1:name", "body": ""})
check(r.status_code == 400, "M1: no plain name with the ciphertext prefix (create)")
buf = _io.BytesIO()
with _zf.ZipFile(buf, "w") as z:
    z.writestr("e2e1:named.md", "a")
    z.writestr("Fine.md", "e2e1:{}")
    z.writestr("Good.md", "good text")
r = Er.post(B + "/api/wiki/import", params={"space": "private"}, files={"file": ("w.zip", buf.getvalue())})
d = r.json() if r.ok else {}
check(r.ok and len(d["created"]) == 1 and len(d["skipped"]) == 2, "M1: import skips ciphertext-like names and texts " + r.text[:200])
r = Er.post(B + "/api/wiki/e2e/start", json={"space": "private", "keys": [{"user_id": ERIN, "wrapped": wrapped()}]})
check(r.status_code == 409 and code(r) == "wiki_e2e_prefix" and r.json().get("pages") == [EP], "M1: switching on refuses such a page " + r.text[:200])
check(Er.patch(B + f"/api/wiki/pages/{EP}", json={"body": "normal again"}).ok, "M1: the page can be changed")
r = Er.post(B + "/api/wiki/e2e/start", json={"space": "private", "keys": [{"user_id": ERIN, "wrapped": wrapped()}]})
check(r.ok and r.json()["mode"] == "encrypting", "M1: then switching on works " + r.text[:200])

print(f"p264c_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
