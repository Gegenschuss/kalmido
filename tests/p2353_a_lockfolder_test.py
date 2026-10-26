#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.353.0 A (#2758): locked folders of the file store -- invented names and bytes only. The server never sees a folder key or
a plain name / file of a locked folder; these tests send ciphertexts and wrapped keys of the right shape (the WebCrypto round
trip is in tests/p2353_a_lockfolder_ui.js).
 (a) GET / start: only the owner (an organisation's admin for a member's folder too), agents and API tokens 403, a missing key
     409, nesting / the documents folder refused
 (b) encrypting: plain ways 409, todo / raw / convert (the plain version goes, recognised text goes) / finish
 (c) 'on': every plain way 409 (upload, new folder, rename, new version, API), the encrypted upload / folder / rename /
     version; the listing carries locked + lock_id; server preview 409, server search leaves the files out
 (d) agents and API tokens see nothing (also with a share on the folder above), no agent share, no external link, no file
     request, the ZIP leaves the files out
 (e) moving: a plain move across the border 409, re-encrypted in and out (fslock move), a locked folder into another 409
 (f) keys: people with access wait, the owner hands over, a person without encryption 409, a non-manager sees no people
 (g) versions (restore keeps the ciphertext), trash and back
 (h) unlock (password) -> decrypting -> plain again, keys gone; an aborted start without a password
 (i) a person without an organisation: her private folder locked, encrypted upload, her agent sees nothing
usage: p2353_a_lockfolder_test.py <datadir>
freelancer-matrix: files  tenant-matrix: file"""
import base64
import json
import os
import struct
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess, B, H, DATA  # noqa: E402,F401

if not (os.environ.get("P2353A_NOSTART") or os.environ.get("KMT_NOSTART")):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)


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


def ct(gen=1, n=48):
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(n)}, separators=(",", ":"))


def kenc(gen=1, n=200):
    return b"KENC\x02" + struct.pack(">I", gen) + os.urandom(12) + os.urandom(n)


def code(r):
    try:
        return r.json().get("code")
    except ValueError:
        return None


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Studio Example", "lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
FEAT = "collab,agents,comments,api,files,docs"
A.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
ORG = dbx("SELECT id FROM orgs WHERE personal_of IS NULL ORDER BY id LIMIT 1")[0][0]
U = {}
for name in ("bob", "dave"):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", "orgs": [ORG]})
    assert r.ok, r.text
    U[name] = r.json()["id"]
BOB, DAVE = U["bob"], U["dave"]
Bo, Da = sess("bob"), sess("dave")
for s in (Bo, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
for s in (A, Bo):  # dave has no encryption set up
    assert s.put(B + "/api/e2e/keys", json=keys()).ok
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"}).json()
AGID, AGH = ag["id"], {"Authorization": "Bearer " + ag["token"], **H}
tok = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "write"]})
TH = {"Authorization": "Bearer " + tok.json()["token"], **H} if tok.ok else None
check(TH is not None, "an API token of alice " + tok.text[:200])


def folder(s, name, parent=None, space="private"):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": space})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(s, parent, name, data=b"invented plain text"):
    return s.post(B + "/api/files/upload", data={"parent_id": str(parent)}, files={"file": (name, data, "text/plain")})


def lupload(s, parent, gen=1, name=None, blob=None):
    return s.post(B + "/api/files/lock/upload", data={"parent_id": str(parent), "name": name or ct(gen)},
                  files={"file": ("encrypted.kenc", blob or kenc(gen), "application/octet-stream")})


def items(s, parent):
    r = s.get(B + "/api/files", params={"parent": parent})
    return {x["id"]: x for x in r.json().get("items", [])} if r.ok else {}


TOP = folder(A, "Top")
SAFE = folder(A, "Safe", TOP)
SUB = folder(A, "Sub", SAFE)
r = upload(A, SAFE, "notes.txt", b"invented secret plain words")
assert r.status_code == 201, r.text
F1 = r.json()["items"][0]["id"]
OUT = folder(A, "Out", TOP)
F2 = upload(A, OUT, "loose.txt", b"loose plain").json()["items"][0]["id"]

# ---------------------------------------------------------------- (a) GET / start
r = A.get(B + f"/api/files/lock/{SAFE}")
d = r.json() if r.ok else {}
check(r.ok and d["mode"] is None and d["can_manage"] is True and d.get("block") is None, "GET: open, alice manages " + r.text[:200])
check(requests.get(B + f"/api/files/lock/{SAFE}", headers=AGH).status_code in (401, 403, 404), "GET: agent refused")
check(requests.get(B + f"/api/files/lock/{SAFE}", headers=TH).status_code in (401, 403), "GET: API token refused")
check(Bo.get(B + f"/api/files/lock/{SAFE}").status_code == 404, "GET: a stranger 404")
r = A.post(B + f"/api/files/lock/{SAFE}/start", json={"keys": []})
check(r.status_code == 409 and code(r) == "fs_lock_keys", "start: my own key missing 409 " + r.text[:200])
check(requests.post(B + f"/api/files/lock/{SAFE}/start", json={"keys": []}, headers=TH).status_code in (401, 403), "start: API token refused")
r = A.post(B + f"/api/files/lock/{SAFE}/start", json={"keys": [{"user_id": 1, "wrapped": wrapped()}]})
check(r.ok and r.json()["mode"] == "encrypting" and r.json()["gen"] == 1 and r.json()["left"] == 2, "start: encrypting, 2 nodes left " + r.text[:300])
check(A.post(B + f"/api/files/lock/{SAFE}/start", json={"keys": [{"user_id": 1, "wrapped": wrapped()}]}).status_code == 409, "start twice 409")
check(A.get(B + f"/api/files/lock/{SUB}").json().get("node_id") == SAFE, "GET of a node inside: the lock of SAFE")
r = A.get(B + f"/api/files/lock/{TOP}")
check(r.ok and r.json().get("block"), "nesting: a folder holding a locked one cannot be locked " + r.text[:200])

# ---------------------------------------------------------------- (b) encrypting
check(upload(A, SAFE, "more.txt").status_code == 409, "encrypting: a plain upload 409")
r = lupload(A, SAFE)
check(r.status_code == 409 and code(r) == "fs_locked_busy", "encrypting: the encrypted upload waits (busy) " + r.text[:200])
t = A.get(B + f"/api/files/lock/{SAFE}/todo").json()
check({x["id"] for x in t.get("items", [])} == {F1, SUB} and t["mode"] == "encrypting", "todo: the file and the subfolder")
check(Bo.get(B + f"/api/files/lock/{SAFE}/todo").status_code == 404, "todo: a stranger 404")
r = A.get(B + f"/api/files/lock/{SAFE}/raw/{F1}")
check(r.ok and r.content == b"invented secret plain words" and r.headers.get("Content-Type", "").startswith("application/octet-stream"),
      "raw: the plain bytes for the browser, always a download type")
dbx("INSERT INTO file_text(kind, ref_id, node_id, state, created_at, updated_at, ws) VALUES('fs', ?, ?, 'found', '2026-10-26', '2026-10-26', 'u1') "
    "ON CONFLICT DO NOTHING", (F1, F1))
r = A.post(B + f"/api/files/lock/{SAFE}/convert/{F1}", data={"name": "plain name"}, files={"file": ("x", kenc(1), "application/octet-stream")})
check(r.status_code == 400, "convert: a plain name refused while encrypting")
r = A.post(B + f"/api/files/lock/{SAFE}/convert/{F1}", data={"name": ct(1)}, files={"file": ("x", b"plain bytes, no KENC head", "text/plain")})
check(r.status_code == 400, "convert: plain bytes refused while encrypting")
r = A.post(B + f"/api/files/lock/{SAFE}/convert/{F1}", data={"name": ct(1)}, files={"file": ("x", kenc(1), "application/octet-stream")})
check(r.ok and r.json()["left"] == 1, "convert: the file " + r.text[:200])
row = dbx("SELECT name, mime, e2e_gen FROM fs_nodes WHERE id=?", (F1,))[0]
check(row[0].startswith("e2e1:") and row[1] == "application/octet-stream" and row[2] == 1, "convert: cipher name, octet-stream, generation 1")
check(len(dbx("SELECT 1 FROM fs_versions WHERE node_id=?", (F1,))) == 1, "convert: the plain version went, only the ciphertext stays")
check(not dbx("SELECT 1 FROM file_text WHERE kind='fs' AND ref_id=?", (F1,)), "convert: the recognised text of the plain file went")
check(A.post(B + f"/api/files/lock/{SAFE}/finish", json={}).status_code == 409, "finish: not everything converted 409")
check(A.post(B + f"/api/files/lock/{SAFE}/convert/{SUB}", data={"name": ct(1)}).ok, "convert: the subfolder's name")
r = A.post(B + f"/api/files/lock/{SAFE}/finish", json={})
check(r.ok and r.json()["mode"] == "on", "finish: on " + r.text[:200])

# ---------------------------------------------------------------- (c) 'on'
r = upload(A, SAFE, "plain.txt")
check(r.status_code == 409 and code(r) == "fs_locked", "on: a plain upload 409 fs_locked " + r.text[:200])
r = A.post(B + "/api/files/folders", json={"name": "Plain", "parent_id": SAFE})
check(r.status_code == 409 and code(r) == "fs_locked", "on: a plain new folder 409")
check(A.patch(B + f"/api/files/nodes/{F1}", json={"name": "plain.txt"}).status_code == 409, "on: a plain rename inside 409")
check(A.patch(B + f"/api/files/nodes/{SAFE}", json={"name": "Safe box"}).ok, "on: the locked folder's own name stays plain (rename ok)")
check(A.post(B + f"/api/files/nodes/{F1}/versions", files={"file": ("n.txt", b"plain", "text/plain")}).status_code == 409, "on: a plain new version 409")
n0 = dbx("SELECT COUNT(*) FROM fs_nodes WHERE parent_id=?", (SAFE,))[0][0]
r = requests.post(B + "/api/v1/files", headers=TH, data={"parent_id": str(SAFE)}, files={"file": ("api.txt", b"plain", "text/plain")})
check(r.status_code != 201 and dbx("SELECT COUNT(*) FROM fs_nodes WHERE parent_id=?", (SAFE,))[0][0] == n0, f"on: the REST API cannot add a file {r.status_code}")
check(lupload(A, SAFE, name="plain name").status_code == 400, "encrypted upload: a plain name 400")
check(lupload(A, SAFE, blob=kenc(2)).status_code == 400, "encrypted upload: another generation 400")
r = lupload(A, SUB)
check(r.status_code == 201, "encrypted upload into the subfolder " + r.text[:200])
F3 = r.json()["items"][0]["id"] if r.status_code == 201 else 0
x = r.json()["items"][0] if r.status_code == 201 else {}
check(x.get("locked") is True and x.get("lock_id") == SAFE and x.get("mime") == "application/octet-stream", "upload answer: locked + lock_id")
check(not dbx("SELECT 1 FROM file_text WHERE kind='fs' AND ref_id=?", (F3,)) and not dbx("SELECT 1 FROM upload_scan WHERE kind='fs' AND ref_id=?", (F3,)),
      "upload: no text recognition / scan queued for a ciphertext")
it = items(A, SAFE)
check(it.get(F1, {}).get("locked") is True and it.get(SUB, {}).get("lock_id") == SAFE, "listing: every node inside carries locked + lock_id")
check(items(A, TOP).get(SAFE, {}).get("lock_id") == SAFE, "listing: the locked folder itself carries locked")
r = A.post(B + "/api/files/lock/folder", json={"parent_id": SAFE, "name": ct(1)})
check(r.status_code == 201 and r.json().get("locked") is True, "encrypted new folder")
check(A.post(B + "/api/files/lock/folder", json={"parent_id": SAFE, "name": "Plain"}).status_code == 400, "encrypted new folder: a plain name 400")
check(A.post(B + f"/api/files/lock/rename/{F1}", json={"name": ct(1)}).ok, "encrypted rename")
check(A.post(B + f"/api/files/lock/rename/{F1}", json={"name": "plain"}).status_code == 400, "encrypted rename: a plain name 400")
check(A.get(B + f"/api/files/nodes/{F1}/preview").status_code == 409, "server preview of a locked file 409")
hits = A.get(B + "/api/files/search", params={"q": "e2e1"}).json().get("items", [])
check(not [h for h in hits if h["id"] in (F1, F3, SUB)], "server search leaves the ciphertexts out")
r = A.get(B + f"/api/files/lock/{SAFE}/raw/{F1}")
check(r.ok and r.content[:5] == b"KENC\x02", "raw: the ciphertext for the browser")
check(A.get(B + f"/api/files/nodes/{F1}/content").content[:5] == b"KENC\x02", "content: the stored ciphertext only")

# ---------------------------------------------------------------- (d) agents, API tokens, external people
r = A.post(B + f"/api/files/nodes/{SAFE}/shares", json={"agent_id": AGID, "role": "view"})
check(r.status_code == 409 and code(r) == "fs_locked_agent", "share with an agent 409 " + r.text[:200])
check(A.get(B + f"/api/files/nodes/{SAFE}/share-targets").json().get("agents") == [], "share targets of a locked folder: no agents")
dbx("INSERT INTO fs_shares(node_id, agent_id, role, created_by, created_at) VALUES(?, ?, 'edit', 1, '2026-10-26T10:00:00Z')", (TOP, AGID))
lst = requests.get(B + "/api/v1/files", params={"parent_id": TOP}, headers=AGH)
check(lst.ok and OUT in {x["id"] for x in lst.json().get("data", [])} and SAFE not in {x["id"] for x in lst.json().get("data", [])},
      "agent: the shared folder above lists everything but the locked folder " + lst.text[:200])
check(requests.get(B + f"/api/v1/files/{F1}", headers=AGH).status_code == 404, "agent: a file inside 404")
check(requests.get(B + f"/api/v1/files/{F1}/content", headers=AGH).status_code == 404, "agent: its content 404")
check(requests.get(B + f"/api/v1/files/{SAFE}", headers=AGH).status_code == 404, "agent: the locked folder 404")
check(requests.get(B + f"/api/v1/files/{F1}", headers=TH).status_code == 404, "API token: a file inside 404")
lst = requests.get(B + "/api/v1/files", params={"parent_id": TOP}, headers=TH)
check(lst.ok and OUT in {x["id"] for x in lst.json().get("data", [])} and SAFE not in {x["id"] for x in lst.json().get("data", [])},
      "API token: the listing leaves the locked folder out")
r = A.post(B + f"/api/files/nodes/{F1}/ext-links", json={"expires": "7d"})
check(r.status_code == 409, "external link inside a locked folder 409")
r = A.post(B + f"/api/files/nodes/{SAFE}/requests", json={"title": "Send me", "days": 7})
check(r.status_code in (409, 403), "file request into a locked folder refused " + r.text[:120])
z = A.get(B + "/api/files/zip", params={"ids": str(TOP), "check": "1"}).json()
check(z.get("files") == 1, "ZIP of the folder above: the locked files stay out " + json.dumps(z))

# ---------------------------------------------------------------- (e) moving
r = A.patch(B + f"/api/files/nodes/{F2}", json={"parent_id": SAFE})
check(r.status_code == 409 and code(r) == "fs_locked_move", "a plain move into the locked folder 409 " + r.text[:200])
check(A.patch(B + f"/api/files/nodes/{F1}", json={"parent_id": OUT}).status_code == 409, "a plain move out of it 409")
check(A.patch(B + f"/api/files/nodes/{F1}", json={"parent_id": SUB}).ok, "a move inside the same locked folder is fine")
r = A.post(B + f"/api/files/lock/move/{F2}", data={"parent_id": str(SAFE), "name": ct(1)}, files={"file": ("x", kenc(1), "application/octet-stream")})
check(r.ok, "re-encrypted into the locked folder " + r.text[:200])
check(dbx("SELECT parent_id, e2e_gen FROM fs_nodes WHERE id=?", (F2,))[0] == (SAFE, 1) and len(dbx("SELECT 1 FROM fs_versions WHERE node_id=?", (F2,))) == 1,
      "moved in: generation 1, only the ciphertext version")
r = A.post(B + f"/api/files/lock/move/{F2}", data={"parent_id": str(OUT), "name": "loose again.txt", "type": "text/plain"},
           files={"file": ("x", b"loose plain again", "application/octet-stream")})
check(r.ok and dbx("SELECT parent_id, e2e_gen, name FROM fs_nodes WHERE id=?", (F2,))[0] == (OUT, 0, "loose again.txt"), "decrypted out again " + r.text[:200])
check(A.get(B + f"/api/files/nodes/{F2}/content").content == b"loose plain again", "moved out: readable again")
SAFE2 = folder(A, "Second")
check(A.patch(B + f"/api/files/nodes/{SAFE}", json={"parent_id": SAFE2}).ok, "the locked folder itself moves into an open folder")

# ---------------------------------------------------------------- (f) keys and sharing
assert A.post(B + f"/api/files/nodes/{SAFE}/shares", json={"user_id": BOB, "role": "view"}).ok
assert A.post(B + f"/api/files/nodes/{SAFE}/shares", json={"user_id": DAVE, "role": "view"}).ok
d = A.get(B + f"/api/files/lock/{SAFE}").json()
pend = {p["user_id"]: p for p in d.get("pending", [])}
check(set(pend) == {BOB, DAVE} and pend[BOB]["has_keys"] and not pend[DAVE]["has_keys"] and AGID not in pend, "people with access wait for the key, no agent")
b = Bo.get(B + f"/api/files/lock/{SAFE}").json()
check(b.get("can_manage") is False and b.get("keys") == [] and b.get("members") == [], "bob: no key yet, sees no people")
check(Bo.post(B + f"/api/files/lock/{SAFE}/keys", json={"keys": [{"user_id": BOB, "gen": 1, "wrapped": wrapped()}]}).status_code == 403, "keys: a viewer cannot hand them out")
r = A.post(B + f"/api/files/lock/{SAFE}/keys", json={"keys": [{"user_id": DAVE, "gen": 1, "wrapped": wrapped()}]})
check(r.status_code == 409, "keys: a person without encryption 409")
r = A.post(B + f"/api/files/lock/{SAFE}/keys", json={"keys": [{"user_id": AGID, "gen": 1, "wrapped": wrapped()}]})
check(r.status_code == 409, "keys: an agent 409")
r = A.post(B + f"/api/files/lock/{SAFE}/keys", json={"keys": [{"user_id": BOB, "gen": 1, "wrapped": wrapped()}]})
check(r.ok and r.json()["released"] == [BOB], "keys: bob gets his copy")
b = Bo.get(B + f"/api/files/lock/{SAFE}").json()
check([k["gen"] for k in b.get("keys", [])] == [1], "bob holds generation 1")
check(Bo.get(B + f"/api/files/lock/{SAFE}/raw/{F1}").content[:5] == b"KENC\x02", "bob reads the ciphertext (viewer)")
check(lupload(Bo, SAFE).status_code == 403, "bob (view) cannot upload")

# ---------------------------------------------------------------- (g) versions, trash
V0 = dbx("SELECT MAX(no) FROM fs_versions WHERE node_id=?", (F1,))[0][0]  # the conversion's version (the plain one before went)
r = A.post(B + f"/api/files/lock/version/{F1}", files={"file": ("x", kenc(1), "application/octet-stream")})
check(r.status_code == 201 and r.json()["version"] == V0 + 1, "encrypted new version " + r.text[:120])
r = A.post(B + f"/api/files/nodes/{F1}/versions/{V0}/restore")
check(r.ok and dbx("SELECT MAX(no) FROM fs_versions WHERE node_id=?", (F1,))[0][0] == V0 + 2, "restore the older version: a new one " + r.text[:120])
check(A.post(B + f"/api/files/nodes/{F1}/versions/1/restore").status_code == 404, "the plain version 1 is gone for good")
check(A.get(B + f"/api/files/lock/{SAFE}/raw/{F1}").content[:5] == b"KENC\x02", "the restored version is the ciphertext")
check(A.delete(B + f"/api/files/nodes/{F3}").ok and A.post(B + f"/api/files/nodes/{F3}/restore").ok, "trash and back")

# ---------------------------------------------------------------- (h) unlock, aborted start
check(A.post(B + f"/api/files/lock/{SAFE}/stop", json={"password": "wrong-password"}).status_code in (400, 401, 403), "stop: a wrong password refused")
check(Bo.post(B + f"/api/files/lock/{SAFE}/stop", json={"password": "password123"}).status_code == 403, "stop: a viewer 403")
r = A.post(B + f"/api/files/lock/{SAFE}/stop", json={"password": "password123"})
check(r.ok and r.json()["mode"] == "decrypting", "stop: decrypting " + r.text[:200])
for _ in range(5):
    t = A.get(B + f"/api/files/lock/{SAFE}/todo").json()
    if not t.get("items"):
        break
    for x in t["items"]:
        fl = {"file": ("x", b"plain again %d" % x["id"], "application/octet-stream")} if x["kind"] == "file" else None
        A.post(B + f"/api/files/lock/{SAFE}/convert/{x['id']}", data={"name": f"Plain {x['id']}.txt", "type": "text/plain"}, files=fl)
r = A.post(B + f"/api/files/lock/{SAFE}/finish", json={})
check(r.ok and r.json()["mode"] is None, "finish: open again " + r.text[:200])
check(not dbx("SELECT 1 FROM fs_lock_keys WHERE node_id=?", (SAFE,)) and not dbx("SELECT 1 FROM fs_nodes WHERE e2e_gen>0"), "open: keys gone, no ciphertext left")
check(A.get(B + f"/api/files/nodes/{F1}/content").content == b"plain again %d" % F1, "open: the file is plain again")
r = A.post(B + f"/api/files/lock/{SAFE}/start", json={"keys": [{"user_id": 1, "wrapped": wrapped()}, {"user_id": BOB, "wrapped": wrapped()}]})
check(r.ok and r.json()["gen"] == 2, "start again: generation 2")
r = A.post(B + f"/api/files/lock/{SAFE}/stop", json={"abort": True})
check(r.ok and r.json()["mode"] == "decrypting", "abort of a start without a password")
check(A.post(B + f"/api/files/lock/{SAFE}/finish", json={}).ok and A.get(B + f"/api/files/lock/{SAFE}").json()["mode"] is None, "aborted start: open, nothing half")

# documents folder and an organisation's folder
r = A.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("bill.txt", b"invented bill", "text/plain")})
root = dbx("SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id IS NULL AND owner_id=1 AND lower(name) IN ('dokumente', 'documents') ORDER BY id LIMIT 1")
if root:
    check(A.get(B + f"/api/files/lock/{root[0][0]}").json().get("block"), "the documents folder cannot be locked")
OF = folder(Bo, "Team box", space=f"org:{ORG}")
check(Bo.get(B + f"/api/files/lock/{OF}").json().get("can_manage") is True and A.get(B + f"/api/files/lock/{OF}").json().get("can_manage") is True,
      "organisation: the folder's owner and the admins manage")
check(Da.get(B + f"/api/files/lock/{OF}").status_code == 404, "organisation: a member without access 404")

# ---------------------------------------------------------------- (i) a person without an organisation
FID, Fr = freelancer(B, A, "frida")
assert Fr.put(B + "/api/e2e/keys", json=keys()).ok
FB = folder(Fr, "Private box")
r = Fr.post(B + f"/api/files/lock/{FB}/start", json={"keys": [{"user_id": FID, "wrapped": wrapped()}]})
check(r.ok and r.json()["mode"] == "encrypting", "freelancer: lock her own folder " + r.text[:200])
check(Fr.post(B + f"/api/files/lock/{FB}/finish", json={}).ok, "freelancer: an empty folder finishes at once")
r = lupload(Fr, FB)
check(r.status_code == 201 and r.json()["items"][0]["locked"] is True, "freelancer: encrypted upload " + r.text[:200])
check(upload(Fr, FB, "plain.txt").status_code == 409, "freelancer: a plain upload 409")
check(A.get(B + f"/api/files/lock/{FB}").status_code == 404, "freelancer: the instance admin does not see her folder")

print(f"p2353_a_lockfolder: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
