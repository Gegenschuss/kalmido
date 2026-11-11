#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.953 (#3348): the rest of the locked folders (2.353.0, #2758) -- invented names and bytes only (the shapes of
tests/p2353_f_lockreview_test.py: ciphertexts and wrapped keys of the right form, no WebCrypto).
 key change   a person who loses access (share taken back) makes the folder ask for a new key (rotate); the new generation goes
              to who keeps it, the copies of who lost access go; the files are encrypted again in 'on' (todo / convert / finish),
              the earlier versions stay; a deleted account that held a key marks the folder; a person without an organisation
              changes the key of her folder by hand
 move         a folder whose content lies in the trash only crosses the border, the trash stays on its side; the check before a
              move with content names what blocks (an external link inside); the targets of "Move to..." below a locked folder
              carry their lock and the name parts
 tags         the lock dialog learns how many nodes carry tags; locking (and moving in) removes them
 N5  who reaches a part only learns nothing about the subtree (left, by, at, block, rotate)
 N6  a deleted file request does not come back into a folder locked since
 N7  no version restore while a folder is being unlocked (never an octet-stream version of a file already decrypted)
 N11 locking waits for a plain write below the folder that runs at the same moment (advisory lock, seen in pg_locks)
 N13 no share with an agent on a folder above a locked folder
 N14 a move into a locked folder refused at the end (another workspace) leaves no stored file behind
 2.970 (#5653) the low findings of the review: N-b a tag change / version restore waits for a folder above that starts to lock;
              N-c locking a folder waits for a plain write below the folder ABOVE it (no nested locks of two starts); N-e a move
              takes its locks in the order of their ids; N-g a file encrypted again with a new key does not replace a version
              saved meanwhile
usage: p2953_lockrest_test.py <datadir>
freelancer-matrix: files  tenant-matrix: file"""
import base64
import json
import os
import struct
import subprocess
import sys
import threading

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess, B, H, DATA  # noqa: E402,F401

if not (os.environ.get("P2953_NOSTART") or os.environ.get("KMT_NOSTART")):
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
FEAT = "collab,agents,comments,api,files,docs,sheets"
A.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
ORG = dbx("SELECT id FROM orgs WHERE personal_of IS NULL ORDER BY id LIMIT 1")[0][0]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "orgs": [ORG]})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
assert A.put(B + "/api/e2e/keys", json=keys()).ok
assert Bo.put(B + "/api/e2e/keys", json=keys()).ok
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"}).json()
AGID = ag["id"]
ME = 1  # alice, the first account


def folder(s, name, parent=None, space="private"):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": space})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(s, parent, name, data=b"invented plain text"):
    r = s.post(B + "/api/files/upload", data={"parent_id": str(parent)}, files={"file": (name, data, "text/plain")})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def lupload(s, parent, gen=1):
    r = s.post(B + "/api/files/lock/upload", data={"parent_id": str(parent), "name": ct(gen)},
               files={"file": ("encrypted.kenc", kenc(gen), "application/octet-stream")})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def start(s, fid, uids):
    r = s.post(B + f"/api/files/lock/{fid}/start", json={"keys": [{"user_id": u, "wrapped": wrapped()} for u in uids]})
    assert r.ok, r.text
    return r.json()["gen"]


def convert_all(s, fid, plain=False):
    """The browser's switch with invented bytes: every node of the todo in the target format."""
    for _ in range(10):
        t = s.get(B + f"/api/files/lock/{fid}/todo").json()
        if not t["items"]:
            return t
        for it in t["items"]:
            files = None
            if plain:
                data = {"name": f"plain-{it['id']}.txt", "type": "text/plain"}
                if it["kind"] == "file":
                    files = {"file": ("file", b"invented plain words", "application/octet-stream")}
            else:
                data = {"name": ct(t["gen"])}
                if it["kind"] == "file":
                    data["version"] = str(it["version"])  # 2.970.0 (#5653): required for the encryption with a new key
                    files = {"file": ("encrypted.kenc", kenc(t["gen"]), "application/octet-stream")}
            r = s.post(B + f"/api/files/lock/{fid}/convert/{it['id']}", data=data, files=files)
            assert r.ok, r.text
    raise AssertionError("the switch did not end")


def lock(s, fid, uids):
    """Lock folder fid (start, its content converted, finish) -> its generation."""
    g = start(s, fid, uids)
    convert_all(s, fid)
    r = s.post(B + f"/api/files/lock/{fid}/finish", json={})
    assert r.ok and r.json()["mode"] == "on", r.text
    return g


def files_on_disk(nid):
    d = os.path.join(DATA, "attachments", "files", str(nid))
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


# ---------------------------------------------------------------- the key change after someone lost access (+ N5)
R = folder(A, "Shared box")
r = A.post(B + f"/api/files/nodes/{R}/shares", json={"user_id": BOB, "role": "view"})
check(r.ok, "the folder shared with bob " + r.text[:200])
SID = dbx("SELECT id FROM fs_shares WHERE node_id=? AND user_id=?", (R, BOB))[0][0]
g1 = lock(A, R, [ME, BOB])
RF = lupload(A, R, g1)
check(A.post(B + f"/api/files/lock/version/{RF}", files={"file": ("encrypted.kenc", kenc(g1), "application/octet-stream")}).status_code == 201,
      "a second version of the encrypted file")
ia = A.get(B + f"/api/files/lock/{R}").json()
check(ia["rotate"] == 0 and ia["reenc"] == 0, f"nobody lost access: no key change ({ia.get('rotate')}, {ia.get('reenc')})")
ib = Bo.get(B + f"/api/files/lock/{R}").json()
check(ia["by"] == ME and ia["at"], "the owner learns who locked the folder when")
check(ib["by"] is None and ib["at"] is None and ib["left"] == 0 and "block" not in ib and ib["rotate"] == 0 and not ib["members"],
      f"N5: bob (no manager) learns nothing about the subtree ({ {k: ib.get(k) for k in ('by', 'at', 'left', 'block', 'rotate')} })")
check(A.delete(B + f"/api/files/shares/{SID}").ok, "the share of bob taken back")
check(Bo.get(B + f"/api/files/lock/{R}").status_code == 404, "bob does not reach the folder any more")
ia = A.get(B + f"/api/files/lock/{R}").json()
check(ia["rotate"] == g1, f"the folder asks for a new key ({ia['rotate']})")
r = A.post(B + f"/api/files/lock/{R}/rotate", json={"gen": g1 + 2, "keys": [{"user_id": ME, "wrapped": wrapped()}]})
check(r.status_code == 409 and code(r) == "fs_lock_gen", f"a generation that is not the next one: 409 fs_lock_gen ({r.status_code})")
r = A.post(B + f"/api/files/lock/{R}/rotate", json={"gen": g1 + 1, "keys": [{"user_id": ME, "wrapped": wrapped()}, {"user_id": BOB, "wrapped": wrapped()}]})
check(r.status_code == 400, f"no new key for who lost access: 400 ({r.status_code})")
r = Bo.post(B + f"/api/files/lock/{R}/rotate", json={"gen": g1 + 1, "keys": [{"user_id": BOB, "wrapped": wrapped()}]})
check(r.status_code in (403, 404), f"bob cannot change the key ({r.status_code})")
r = A.post(B + f"/api/files/lock/{R}/rotate", json={"gen": g1 + 1, "keys": [{"user_id": ME, "wrapped": wrapped()}]})
check(r.ok, "the key changed " + r.text[:200])
j = r.json() if r.ok else {}
g2 = g1 + 1
check(j.get("gen") == g2 and j.get("reenc") == g2 and j.get("rotate") == 0 and j.get("left") == 1,
      f"the new generation, its encryption running, one file to do ({ {k: j.get(k) for k in ('gen', 'reenc', 'rotate', 'left')} })")
check(dbx("SELECT COUNT(*) FROM fs_lock_keys WHERE node_id=? AND user_id=?", (R, BOB))[0][0] == 0, "the copies of bob are gone (every generation)")
check(sorted(x[0] for x in dbx("SELECT gen FROM fs_lock_keys WHERE node_id=? AND user_id=?", (R, ME))) == [g1, g2],
      "alice keeps the old generation (older versions) and has the new one")
r = A.post(B + f"/api/files/lock/{R}/rotate", json={"gen": g2 + 1, "keys": [{"user_id": ME, "wrapped": wrapped()}]})
check(r.ok, "a key change by hand works too " + r.text[:120])
g3 = g2 + 1
vers = [x[0] for x in dbx("SELECT no FROM fs_versions WHERE node_id=? ORDER BY no", (RF,))]
t = convert_all(A, R)
check(t["mode"] == "on" and t["left"] == 0, "the files are encrypted with the new key in 'on'")
vers2 = [x[0] for x in dbx("SELECT no FROM fs_versions WHERE node_id=? ORDER BY no", (RF,))]
check(vers2[:-1] == vers[:-1] and vers2[-1] > vers[-1], f"the earlier versions stay, the current one is replaced ({vers} -> {vers2})")
row = dbx("SELECT e2e_gen, name FROM fs_nodes WHERE id=?", (RF,))[0]
check(row[0] == g3 and json.loads(row[1][5:])["g"] == g3, "the file and its name are of the new generation")
r = A.post(B + f"/api/files/lock/{R}/finish", json={})
check(r.ok and r.json().get("reenc") == 0 and r.json().get("mode") == "on", "finish: the encryption with the new key is done " + r.text[:160])
check(lupload(A, R, g3) > 0, "new files come with the new generation")

# Fable review M2: a share inside the locked folder that expired counts as gone (no key, the folder asks for a new one)
R2 = folder(A, "Inner share box")
R2S = folder(A, "Shared inside", R2)
check(A.post(B + f"/api/files/nodes/{R2S}/shares", json={"user_id": BOB, "role": "view", "expires_at": "2099-01-01"}).ok, "a share with an end date inside")
g21 = lock(A, R2, [ME, BOB])
check(BOB in {m["user_id"] for m in A.get(B + f"/api/files/lock/{R2}").json()["members"]}, "bob counts while his share runs")
dbx("UPDATE fs_shares SET expires_at='2020-01-01T00:00:00+00:00' WHERE node_id=? AND user_id=?", (R2S, BOB))
i2 = A.get(B + f"/api/files/lock/{R2}").json()
check(BOB not in {m["user_id"] for m in i2["members"]} and i2["rotate"] == g21, f"M2: the expired share counts as gone, the folder asks for a new key ({i2['rotate']})")

# an account that held a key is deleted: the folder asks for a new key (no row would tell afterwards)
r = A.post(B + "/api/users", json={"username": "carl", "display_name": "Carl", "password": "password123", "orgs": [ORG]})
CARL = r.json()["id"]
dbx("INSERT INTO fs_lock_keys(node_id,gen,user_id,wrapped,wrapper_pub,created_at) VALUES(?,?,?,?,?,?)",
    (R, g3, CARL, json.dumps(wrapped()), json.dumps(keys()["pub"]), "2026-11-11T10:00:00Z"))
r = A.delete(B + f"/api/users/{CARL}")
check(r.ok, "carl's account deleted " + r.text[:160])
check(dbx("SELECT e2e_rotate FROM fs_locks WHERE node_id=?", (R,))[0][0] == g3, "the deleted key holder marks the folder for a new key")
check(A.get(B + f"/api/files/lock/{R}").json()["rotate"] == g3, "the owner is asked for it")

# ---------------------------------------------------------------- tags removed with the lock
TG = folder(A, "Tagged")
TF = upload(A, TG, "tagged.txt")
check(A.put(B + f"/api/files/nodes/{TF}/tags", json={"tags": ["invented tag"]}).ok, "a tag on a plain file")
check(A.get(B + f"/api/files/lock/{TG}").json().get("tagged") == 1, "the lock dialog learns of one tagged node")
lock(A, TG, [ME])
check(not dbx("SELECT 1 FROM doc_node_tags WHERE node_id=?", (TF,)), "locking removed the tag")
MT = upload(A, folder(A, "Loose"), "moving.txt")
A.put(B + f"/api/files/nodes/{MT}/tags", json={"tags": ["another tag"]})
r = A.post(B + f"/api/files/lock/move/{MT}", data={"parent_id": str(TG), "name": ct(1)}, files={"file": ("x", kenc(1), "application/octet-stream")})
check(r.ok and not dbx("SELECT 1 FROM doc_node_tags WHERE node_id=?", (MT,)), "moving into a locked folder removes the tags " + r.text[:120])

# ---------------------------------------------------------------- folders with content across the border
L = folder(A, "Locked box")
gl = lock(A, L, [ME])
M = folder(A, "Outer")
S = folder(A, "Inner", M)
SF = upload(A, S, "old.txt")
check(A.delete(B + f"/api/files/nodes/{SF}").ok, "the only file of Inner into the trash")
r = Bo.get(B + f"/api/files/lock/movecheck/{M}", params={"to": L})
check(r.status_code == 404, f"another person learns nothing about alice's folder ({r.status_code})")
r = A.get(B + f"/api/files/lock/movecheck/{M}", params={"to": L}).json()
check(r.get("block") is None and r.get("count") == 1, f"the check before the move: nothing blocks, one node below outside the trash ({r})")
r = A.post(B + f"/api/files/lock/move/{S}", data={"parent_id": str(L), "name": ct(gl)})
check(r.ok, "a folder holding only trash crosses the border " + r.text[:160])
check(dbx("SELECT parent_id FROM fs_nodes WHERE id=?", (SF,))[0][0] == M, "its trash stays on its side, below the old parent")
check(dbx("SELECT parent_id, e2e_gen FROM fs_nodes WHERE id=?", (S,))[0] == (L, gl), "the folder lies in the locked folder, its name a cipher")
X = folder(A, "With a link")
XS = folder(A, "Linked inside", X)
check(A.post(B + f"/api/files/nodes/{XS}/ext-links", json={"expires": "7d"}).ok, "an external link inside")
r = A.get(B + f"/api/files/lock/movecheck/{X}", params={"to": L}).json()
check(bool(r.get("block")), f"the check names what blocks before the first step ({r})")
r = A.get(B + f"/api/files/lock/movecheck/{L}", params={"to": M}).json()
check(bool(r.get("block")), f"a locked folder itself never crosses with its content (nesting) ({r})")
fs = {f["id"]: f for f in A.get(B + "/api/files/folders", params={"ablage": "1"}).json()["folders"]}
check(fs.get(S, {}).get("lock_id") == L and fs[S].get("parts", [None])[0] == "Locked box" and fs[S]["parts"][-1].startswith("e2e1:"),
      f"a target below the locked folder carries its lock and the name parts ({fs.get(S)})")
check(not fs.get(M, {}).get("lock_id"), "an open target carries none")

# ---------------------------------------------------------------- N6 file requests
Q = folder(A, "Requests")
r = A.post(B + f"/api/files/nodes/{Q}/requests", json={"title": "Your documents", "days": 14})
if r.status_code == 409 and "Public links" in r.text:
    print("p2953: public links are off on this server, N6 skipped", flush=True)
else:
    check(r.status_code == 201, "a file request " + r.text[:160])
    RQ = r.json()["id"]
    check(A.delete(B + f"/api/files/requests/{RQ}").ok, "the request removed")
    lock(A, Q, [ME])
    r = A.post(B + f"/api/files/requests/{RQ}/restore")
    check(r.status_code == 409 and code(r) == "fs_locked_link", f"N6: no file request back into a locked folder ({r.status_code})")

# ---------------------------------------------------------------- N7 restoring a version while the folder is unlocked
V = folder(A, "Versions")
VF = upload(A, V, "notes.txt")
lock(A, V, [ME])
check(A.post(B + f"/api/files/lock/{V}/stop", json={"password": "password123"}).ok, "unlock started (decrypting)")
convert_all(A, V, plain=True)
cur = dbx("SELECT cur_version FROM fs_nodes WHERE id=?", (VF,))[0][0]
r = A.post(B + f"/api/files/nodes/{VF}/versions/{cur}/restore", json={})
check(r.status_code == 409 and code(r) == "fs_locked_busy", f"N7: no version restored while the folder is being unlocked ({r.status_code} {r.text[:120]})")
mimes = [x[0] for x in dbx("SELECT mime FROM fs_versions WHERE node_id=?", (VF,))]
check("application/octet-stream" not in mimes, f"N7: the decrypted file got no version of type octet-stream ({mimes})")
check(A.post(B + f"/api/files/lock/{V}/finish", json={}).ok, "unlocked")
r = A.post(B + f"/api/files/nodes/{VF}/versions/{cur}/restore", json={})
check(r.ok and dbx("SELECT mime FROM fs_versions WHERE node_id=? ORDER BY no DESC LIMIT 1", (VF,))[0][0] == "text/plain",
      "afterwards the version is restored as the plain file it is " + r.text[:120])

# ---------------------------------------------------------------- N13 agent above a locked folder
UP = folder(A, "Above", space=f"org:{ORG}")  # the agent is a share target of the organisation
IN = folder(A, "Locked below", UP)
lock(A, IN, [ME])
r = A.post(B + f"/api/files/nodes/{UP}/shares", json={"agent_id": AGID, "role": "view"})
check(r.status_code == 409 and code(r) == "fs_locked_agent", f"N13: no agent share above a locked folder ({r.status_code} {r.text[:120]})")

# ---------------------------------------------------------------- N14 a refused move leaves no file behind
OL = folder(A, "Team locked", space=f"org:{ORG}")
gol = lock(A, OL, [ME])
PF = upload(A, folder(A, "Mine"), "mine.txt")
before = files_on_disk(PF)
r = A.post(B + f"/api/files/lock/move/{PF}", data={"parent_id": str(OL), "name": ct(gol)}, files={"file": ("x", kenc(gol), "application/octet-stream")})
check(r.status_code == 409, f"into a locked folder of another workspace: 409 ({r.status_code} {r.text[:120]})")
check(files_on_disk(PF) == before and before, f"N14: no stored file left behind ({before} -> {files_on_disk(PF)})")

# ---------------------------------------------------------------- N11 locking waits for a plain write running below
W = folder(A, "Racing")
DBC, DBN = dbxm._target(os.path.join(DATA, "tasks.db"))
# a plain upload below W, not committed yet: one psql session that keeps the shared lock until it is told to let go
hold = subprocess.Popen(["docker", "exec", "-i", DBC, "psql", "-U", "kalmido", "-d", DBN, "-X", "-q", "-A", "-t"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
hold.stdin.write(f"SELECT pg_advisory_lock_shared(21022, {W});\nSELECT 'held';\n")  # 2.970.0 (#5653, review N-f): fsl_hold's own key space
hold.stdin.flush()
got = [hold.stdout.readline().strip() for _ in range(2)]  # the lock call prints an empty line, then the marker
check("held" in got, f"the plain write holds its lock ({got})")
res = {}
th = threading.Thread(target=lambda: res.setdefault("r", A.post(B + f"/api/files/lock/{W}/start", json={"keys": [{"user_id": ME, "wrapped": wrapped()}]})))
th.start()
waiting = False
for _ in range(200):  # the start's request waits for the lock: seen in pg_locks (a real state, no fixed time)
    if dbx("SELECT COUNT(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted")[0][0] > 0:
        waiting = True
        break
    th.join(0.05)
check(waiting and "r" not in res, "N11: locking waits while a plain write below the folder runs")
hold.stdin.write(f"SELECT pg_advisory_unlock_shared(21022, {W});\n\\q\n")
hold.stdin.flush()
hold.wait(30)
th.join(30)
check(res.get("r") is not None and res["r"].ok, "N11: then it locks")

# ---------------------------------------------------------------- 2.970 (#5653): the low findings of the review
def held_run(lock_sql, unlock_sql, call):
    """call() runs in a thread while one psql session holds an advisory lock (lock_sql) -> (waited, granted, response):
    waited = the request waits for it (seen in pg_locks, a real state), granted = the advisory locks the request's own session
    held meanwhile (fsl_hold's key space, 21022), response once the lock is let go."""
    hs = subprocess.Popen(["docker", "exec", "-i", DBC, "psql", "-U", "kalmido", "-d", DBN, "-X", "-q", "-A", "-t"],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    hs.stdin.write(f"SELECT pg_backend_pid();\n{lock_sql};\nSELECT 'held';\n")
    hs.stdin.flush()
    lines = []
    while "held" not in lines and len(lines) < 10:
        lines.append(hs.stdout.readline().strip())
    pid = int(next(x for x in lines if x.isdigit()))
    out, waited, granted = {}, False, None
    th = threading.Thread(target=lambda: out.setdefault("r", call()))
    th.start()
    for _ in range(200):
        w = dbx("SELECT pid FROM pg_locks WHERE locktype='advisory' AND NOT granted AND pid<>?", (pid,))
        if w:
            waited = "r" not in out
            granted = dbx("SELECT COUNT(*) FROM pg_locks WHERE locktype='advisory' AND granted AND classid=21022 AND pid=?", (w[0][0],))[0][0]
            break
        th.join(0.05)
    hs.stdin.write(f"{unlock_sql};\n\\q\n")
    hs.stdin.flush()
    hs.wait(30)
    th.join(30)
    return waited, granted, out.get("r")


# N-c: a start on a folder waits for a plain write below the folder above it (that write could be in it); then it locks
NP = folder(A, "Nest parent")
NC = folder(A, "Nest child", NP)
waited, _g, r = held_run(f"SELECT pg_advisory_lock_shared(21022, {NP})", f"SELECT pg_advisory_unlock_shared(21022, {NP})",
                         lambda: A.post(B + f"/api/files/lock/{NC}/start", json={"keys": [{"user_id": ME, "wrapped": wrapped()}]}))
check(waited, "N-c: locking a folder waits for a write running below the folder above it")
check(r is not None and r.ok, "N-c: then it locks " + (r.text[:120] if r is not None else ""))
r = A.post(B + f"/api/files/lock/{NP}/start", json={"keys": [{"user_id": ME, "wrapped": wrapped()}]})
check(r.status_code == 409, f"N-c: the folder above cannot be locked as well ({r.status_code})")
A.post(B + f"/api/files/lock/{NC}/stop", json={"abort": True})

# N-b: a tag on a plain file waits while a folder above starts to lock (it would be a plain word in a locked tree)
TB = folder(A, "Tag race")
TBF = upload(A, TB, "race.txt")
waited, _g, r = held_run(f"SELECT pg_advisory_lock(21022, {TB})", f"SELECT pg_advisory_unlock(21022, {TB})",
                         lambda: A.put(B + f"/api/files/nodes/{TBF}/tags", json={"tags": ["invented race"]}))
check(waited, "N-b: a tag change waits while a folder above starts to lock")
check(r is not None and r.ok, "N-b: then it is saved (the folder did not lock) " + (r.text[:120] if r is not None else ""))
cur = dbx("SELECT cur_version FROM fs_nodes WHERE id=?", (TBF,))[0][0]
waited, _g, r = held_run(f"SELECT pg_advisory_lock(21022, {TB})", f"SELECT pg_advisory_unlock(21022, {TB})",
                         lambda: A.post(B + f"/api/files/nodes/{TBF}/versions/{cur}/restore", json={}))
check(waited and r is not None and r.ok, "N-b: a version restore waits too, then it is done")

# N-e: a move into a locked folder takes its locks in the order of their ids -- held at the smallest (the top folder), it holds
# none of the others while it waits (the chain from the bottom would hold the source folder first)
ET = folder(A, "Order top")
ES = folder(A, "Order source", ET)
EL = folder(A, "Order locked")
gel = lock(A, EL, [ME])
EF = upload(A, ES, "order.txt")
waited, granted, r = held_run(f"SELECT pg_advisory_lock(21022, {ET})", f"SELECT pg_advisory_unlock(21022, {ET})",
                              lambda: A.post(B + f"/api/files/lock/move/{EF}", data={"parent_id": str(EL), "name": ct(gel)},
                                             files={"file": ("x", kenc(gel), "application/octet-stream")}))
check(waited and granted == 0, f"N-e: the move waits at the smallest id first, holding nothing else ({waited}, {granted})")
check(r is not None and r.ok, "N-e: then it moves " + (r.text[:120] if r is not None else ""))

# N-g: encrypting a file again with a new key does not replace a version saved meanwhile
GR = folder(A, "Rekey race")
gg = lock(A, GR, [ME])
GF = lupload(A, GR, gg)
r = A.post(B + f"/api/files/lock/{GR}/rotate", json={"gen": gg + 1, "keys": [{"user_id": ME, "wrapped": wrapped()}]})
check(r.ok, "a new key for the race " + r.text[:120])
t = A.get(B + f"/api/files/lock/{GR}/todo").json()
seen = next(it["version"] for it in t["items"] if it["id"] == GF)
r = A.post(B + f"/api/files/lock/version/{GF}", files={"file": ("encrypted.kenc", kenc(gg + 1), "application/octet-stream")})
check(r.status_code == 201, "a new version (of the new key) saved while the browser encrypts the file again " + r.text[:120])
newest = r.json().get("version") if r.status_code == 201 else None
r = A.post(B + f"/api/files/lock/{GR}/convert/{GF}", data={"name": ct(gg + 1)}, files={"file": ("encrypted.kenc", kenc(gg + 1), "application/octet-stream")})
check(r.status_code == 409 and not code(r), f"N-g: without the version it was made from: 409 (an old browser loads again) ({r.status_code})")
r = A.post(B + f"/api/files/lock/{GR}/convert/{GF}", data={"name": ct(gg + 1), "version": str(seen)},
           files={"file": ("encrypted.kenc", kenc(gg + 1), "application/octet-stream")})
check(r.status_code == 409 and not code(r), f"N-g: the old version encrypted again is refused, 409 without a code ({r.status_code} {r.text[:120]})")
check(dbx("SELECT cur_version FROM fs_nodes WHERE id=?", (GF,))[0][0] == newest, "N-g: the version saved meanwhile stays the current one")
t = convert_all(A, GR)
check(t["left"] == 0 and dbx("SELECT e2e_gen FROM fs_nodes WHERE id=?", (GF,))[0][0] == gg + 1, "N-g: the next round encrypts the newest version")

# ---------------------------------------------------------------- a person without an organisation
FID, Fr = freelancer(B, A, "frida")
assert Fr.put(B + "/api/e2e/keys", json=keys()).ok
Fr.patch(B + "/api/settings", json={"features": FEAT})
BOX = folder(Fr, "Box")
gb = lock(Fr, BOX, [FID])
FF = lupload(Fr, BOX, gb)
r = Fr.post(B + f"/api/files/lock/{BOX}/rotate", json={"gen": gb + 1, "keys": [{"user_id": FID, "wrapped": wrapped()}]})
check(r.ok and r.json().get("reenc") == gb + 1, "frida changes the key of her folder " + r.text[:160])
convert_all(Fr, BOX)
check(Fr.post(B + f"/api/files/lock/{BOX}/finish", json={}).ok and dbx("SELECT e2e_gen FROM fs_nodes WHERE id=?", (FF,))[0][0] == gb + 1,
      "frida: her file is encrypted with the new key")
r = Fr.get(B + f"/api/files/lock/movecheck/{folder(Fr, 'Plain')}", params={"to": BOX})
check(r.ok and r.json().get("block") is None, "frida: the check before moving a folder in")

print(f"p2953_lockrest: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
