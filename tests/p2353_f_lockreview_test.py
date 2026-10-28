#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.353.0 F (#2758): the findings of the security review of the locked folders -- invented names and bytes only (the shapes
of tests/p2353_a_lockfolder_test.py: ciphertexts and wrapped keys of the right form, no WebCrypto).
 M2  a locked folder moves only where it could be locked (documents tree, a folder shared with an agent, below an external
     link: 409 fs_locked_place); the documents' folder feature never files into a locked folder (id or name)
 M3  a new table (filed object) never goes into a locked folder (409 fs_locked)
 M4  a locked top folder named like the documents folder is not taken as one (a document goes into a new one)
 M5  the lock row follows a move into another space; a stale row takes the folder's workspace again when it is locked
 M6  a plain scan into a locked folder 409 (a stranger 404)
 M8  the plain names in a file's history go when it is moved into a locked folder
 N1  the folder that decides the recognition is named only to who sees it
 N3  a folder of an agent does not move into a locked folder (the list of locking)
 N4  a stranger learns nothing about a lock (404 before 409): upload, move
 N10 no tags on a node in a locked folder (taking them off stays possible)
usage: p2353_f_lockreview_test.py <datadir>
freelancer-matrix: files  tenant-matrix: file"""
import base64
import json
import os
import struct
import subprocess
import sys
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess, B, H, DATA  # noqa: E402,F401

if not (os.environ.get("P2353F_NOSTART") or os.environ.get("KMT_NOSTART")):
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


def png(w, h, rgb):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Studio Example", "lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
FEAT = "collab,agents,comments,api,files,docs,sheets"
A.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
ORG = dbx("SELECT id FROM orgs WHERE personal_of IS NULL ORDER BY id LIMIT 1")[0][0]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "orgs": [ORG]})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
assert A.put(B + "/api/e2e/keys", json=keys()).ok
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"}).json()
AGID = ag["id"]
ME = 1  # alice, the first account


def folder(s, name, parent=None, space="private"):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": space})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(s, parent, name, data=b"invented plain text"):
    return s.post(B + "/api/files/upload", data={"parent_id": str(parent)}, files={"file": (name, data, "text/plain")})


def lupload(s, parent, gen=1):
    return s.post(B + "/api/files/lock/upload", data={"parent_id": str(parent), "name": ct(gen)},
                  files={"file": ("encrypted.kenc", kenc(gen), "application/octet-stream")})


def lock(s, fid, uid):
    """Lock the EMPTY folder fid (start + finish) -> its generation."""
    r = s.post(B + f"/api/files/lock/{fid}/start", json={"keys": [{"user_id": uid, "wrapped": wrapped()}]})
    assert r.ok, r.text
    r = s.post(B + f"/api/files/lock/{fid}/finish", json={})
    assert r.ok and r.json()["mode"] == "on", r.text
    return r.json()["gen"]


def unlock(s, fid):
    r = s.post(B + f"/api/files/lock/{fid}/stop", json={"password": "password123"})
    assert r.ok, r.text
    r = s.post(B + f"/api/files/lock/{fid}/finish", json={})
    assert r.ok and r.json()["mode"] is None, r.text


# the documents folder of alice (made by the first document)
r = A.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("bill.txt", b"invented bill one", "text/plain")})
check(r.ok, "a first document " + r.text[:200])
DROOT = dbx("SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id IS NULL AND owner_id=? AND lower(name) IN ('dokumente','documents') ORDER BY id LIMIT 1", (ME,))[0][0]
DOC1 = dbx("SELECT id FROM fs_nodes WHERE owner_id=? AND kind='file' AND name='bill.txt'", (ME,))[0][0]

L = folder(A, "Locked box")
lock(A, L, ME)
r = lupload(A, L)
check(r.status_code == 201, "an encrypted file in the locked folder " + r.text[:200])
LF = r.json()["items"][0]["id"] if r.status_code == 201 else 0

# ---------------------------------------------------------------- M2 the locked folder moves only where it could be locked
r = A.patch(B + f"/api/files/nodes/{L}", json={"parent_id": DROOT})
check(r.status_code == 409 and code(r) == "fs_locked_place", f"M2: into the documents folder 409 ({r.status_code} {r.text[:200]})")
AGF = folder(A, "For the agent")
dbx("INSERT INTO fs_shares(node_id, agent_id, role, created_by, created_at) VALUES(?, ?, 'view', 1, '2026-10-26T10:00:00Z')", (AGF, AGID))  # a folder shared with the agent
r = A.patch(B + f"/api/files/nodes/{L}", json={"parent_id": AGF})
check(r.status_code == 409 and code(r) == "fs_locked_place", f"M2: below a share with an agent 409 ({r.status_code})")
EXF = folder(A, "Linked")
check(A.post(B + f"/api/files/nodes/{EXF}/ext-links", json={"expires": "7d"}).ok, "a folder with an external link")
r = A.patch(B + f"/api/files/nodes/{L}", json={"parent_id": EXF})
check(r.status_code == 409 and code(r) == "fs_locked_place", f"M2: below an external link 409 ({r.status_code})")
PLAIN = folder(A, "Plain shelf")
check(A.patch(B + f"/api/files/nodes/{L}", json={"parent_id": PLAIN}).ok, "M2: into a plain folder it moves")
# defence in depth: a locked folder inside the documents tree (made directly) takes no document -- by id nor by name
r = A.patch(B + f"/api/docs/{DOC1}", json={"folder": "Kunde Beispiel"})
KF = dbx("SELECT parent_id FROM fs_nodes WHERE id=?", (DOC1,))[0][0]
check(r.ok and KF != DROOT, "a customer folder in the documents tree " + r.text[:200])
dbx("INSERT INTO fs_locks(node_id, org_id, e2e, e2e_gen) VALUES(?, NULL, 'on', 1)", (KF,))
r = A.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("bill2.txt", b"invented bill two", "text/plain")})
DOC2 = dbx("SELECT id FROM fs_nodes WHERE owner_id=? AND kind='file' AND name='bill2.txt'", (ME,))[0][0]
A.patch(B + f"/api/docs/{DOC2}", json={"folder": KF})
A.patch(B + f"/api/docs/{DOC2}", json={"folder": "Kunde Beispiel"})
check(dbx("SELECT parent_id FROM fs_nodes WHERE id=?", (DOC2,))[0][0] != KF, "M2: the folder feature files nothing into a locked folder (id, name)")
dbx("DELETE FROM fs_locks WHERE node_id=?", (KF,))

# ---------------------------------------------------------------- M3 filed objects
r = A.post(B + "/api/sheets", json={"title": "Plan", "space": "private", "folder_id": L})
check(r.status_code == 409 and code(r) == "fs_locked", f"M3: a new table into the locked folder 409 ({r.status_code} {r.text[:200]})")
check(not dbx("SELECT 1 FROM fs_nodes WHERE parent_id=? AND kind='ref'", (L,)), "M3: no filed object in it")

# ---------------------------------------------------------------- M6 scan, N4 strangers
r = A.post(B + "/api/files/scan", data={"parent_id": str(L), "name": "Scan"}, files=[("page", ("p0.png", png(40, 30, (200, 10, 10)), "image/png"))])
check(r.status_code == 409 and code(r) == "fs_locked", f"M6: a plain scan into the locked folder 409 ({r.status_code})")
r = Bo.post(B + "/api/files/scan", data={"parent_id": str(L), "name": "Scan"}, files=[("page", ("p0.png", png(40, 30, (10, 200, 10)), "image/png"))])
check(r.status_code == 404, f"N4: a stranger's scan 404, not 409 ({r.status_code})")
check(upload(Bo, L, "x.txt").status_code == 404, "N4: a stranger's upload into the locked folder 404")
BOBF = folder(Bo, "Bob's")
BFILE = upload(Bo, BOBF, "bob.txt").json()["items"][0]["id"]
r = Bo.patch(B + f"/api/files/nodes/{BFILE}", json={"parent_id": L})
check(r.status_code == 404, f"N4: a stranger's move into the locked folder 404 ({r.status_code} {r.text[:120]})")

# ---------------------------------------------------------------- N10 tags
r = A.put(B + f"/api/files/nodes/{LF}/tags", json={"tags": ["secret word"]})
check(r.status_code == 409 and code(r) == "fs_locked", f"N10: a tag on a locked file 409 ({r.status_code})")
check(A.put(B + f"/api/files/nodes/{LF}/tags", json={"tags": []}).ok, "N10: taking tags off stays possible")

# ---------------------------------------------------------------- M8, N3 moving in
MF = folder(A, "Loose")
F = upload(A, MF, "draft.txt", b"invented draft").json()["items"][0]["id"]
check(A.patch(B + f"/api/files/nodes/{F}", json={"name": "very secret name.txt"}).ok, "a plain rename (the history keeps the name)")
def logged(nid):
    return " ".join(str(x[0] or "") for x in dbx("SELECT detail FROM fs_log WHERE node_id=?", (nid,)))


check("very secret" in logged(F), "the history holds the plain name")
r = A.post(B + f"/api/files/lock/move/{F}", data={"parent_id": str(L), "name": ct(1)}, files={"file": ("x", kenc(1), "application/octet-stream")})
check(r.ok, "moved into the locked folder " + r.text[:200])
check("very secret" not in logged(F), "M8: the plain name left the history")
AGFOLD = folder(A, "Agent results")
dbx("UPDATE fs_nodes SET agent_id=? WHERE id=?", (AGID, AGFOLD))
r = A.post(B + f"/api/files/lock/move/{AGFOLD}", data={"parent_id": str(L), "name": ct(1)})
check(r.status_code == 409, f"N3: an agent's folder does not move into a locked folder ({r.status_code} {r.text[:160]})")

# ---------------------------------------------------------------- N1 recognition source
P = folder(A, "Recognising parent")
C = folder(A, "Shared child", P)
dbx("UPDATE fs_nodes SET recog='on' WHERE id=?", (P,))
check(A.post(B + f"/api/files/nodes/{C}/shares", json={"user_id": BOB, "role": "view"}).ok, "the child shared with bob")
na = A.get(B + "/api/files", params={"parent": C}).json().get("node", {})
nb = Bo.get(B + "/api/files", params={"parent": C}).json().get("node", {})
check(na.get("recog_from") == "Recognising parent", f"N1: the owner sees where the recognition comes from ({na.get('recog_from')!r})")
check(nb.get("recog_on") is True and not nb.get("recog_from"), f"N1: bob does not learn the name of the folder above ({nb.get('recog_from')!r})")

# ---------------------------------------------------------------- M5 the lock row and the workspace
OF = folder(A, "Team box", space=f"org:{ORG}")
lock(A, OF, ME)
unlock(A, OF)
check(dbx("SELECT org_id FROM fs_locks WHERE node_id=?", (OF,)) == [(ORG,)], "an organisation's folder: its lock row (open) of the organisation")
r = A.post(B + "/api/files/move-space", json={"ids": [OF], "to": "private", "parent": None})
check(r.ok, "moved into the private space " + r.text[:200])
check(dbx("SELECT org_id FROM fs_locks WHERE node_id=?", (OF,)) == [(None,)], "M5: the lock row went along into the private space")
SF = folder(A, "Stale")
dbx("INSERT INTO fs_locks(node_id, org_id, e2e, e2e_gen) VALUES(?, ?, NULL, 3)", (SF, ORG))  # a row of before the fix
g = lock(A, SF, ME)
check(g == 4 and dbx("SELECT org_id FROM fs_locks WHERE node_id=?", (SF,)) == [(None,)], f"M5: locking again takes the folder's workspace, the generation goes on ({g})")

# ---------------------------------------------------------------- M4 (and a person without an organisation)
FID, Fr = freelancer(B, A, "frida")
assert Fr.put(B + "/api/e2e/keys", json=keys()).ok
Fr.patch(B + "/api/settings", json={"features": FEAT})
BOX = folder(Fr, "Box")
lock(Fr, BOX, FID)
check(Fr.patch(B + f"/api/files/nodes/{BOX}", json={"name": "Dokumente"}).ok, "frida names her locked folder like the documents folder")
r = Fr.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("note.txt", b"invented note", "text/plain")})
row = dbx("SELECT parent_id FROM fs_nodes WHERE owner_id=? AND kind='file' AND name='note.txt'", (FID,))
check(r.ok and row and row[0][0] != BOX, f"M4: her document goes into a new documents folder, not into the locked one ({r.status_code} {row})")
r = Fr.patch(B + f"/api/files/nodes/{BOX}", json={"parent_id": row[0][0] if row else 0})
check(r.status_code == 409, "freelancer: her locked folder does not move into the documents folder")

print(f"p2353_f_lockreview: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
