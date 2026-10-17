#!/usr/bin/env python3
"""2.64.2 API tests, part B (#1817 stage 2: files of a list with the lock, encrypted with the list key), own container (start.sh).
Invented names only. The server never reads a list file: these tests send blobs of the right shape (b"KENC\\x02" | gen u32 | iv |
ciphertext) and file names as list ciphertexts ("e2e1:{v, g, iv, ct}"); the WebCrypto round trip is in p264b_b_ui.js.
 - plain upload ways into a list with the lock: web upload, per-person file of 2.42, API v1 text file, project files -> 409 / 403
 - POST /api/tasks/<id>/list-attachments: only 'on', only a person in the app, magic + current generation + name ciphertext,
   comment files only for the comment's author; a comment with list files in one multipart request (field le2e_name)
 - download: members (also viewers) get the bytes as stored, named encrypted.kenc; strangers 404, API token 404, no text
 - serializers: enc 2 + e2e_gen on task and comment files; API v1 lists them as encrypted with an empty name
 - POST /api/lists/<id>/e2e/files/<aid> in the three states (encrypting: plain -> list file, on: older generation -> current,
   decrypting: list file -> plain file), owner / list admins only (a per-person file: its uploader), nothing to do -> 409
 - le2f_left (encrypting / on / decrypting, the per-person files of the caller only)
 - a task with list files never moves to another list (409 list_e2e_files)
usage: p264b_b_api_test.py <datadir>"""
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

DATA = sys.argv[1]
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall() if not write else c.execute(sql, args)
        if write:
            c.commit()
            return None
        return r
    finally:
        c.close()


def py(code):
    """Python in the app container (the app's own functions, background context)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import os; os.environ['TASKS_WATCHDOG']='0'\nimport app\n" + code],
                         capture_output=True, text=True)
    return out.returncode, out.stdout.strip(), out.stderr.strip()[-600:]


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def ct(gen=1, n=48):
    """A ciphertext of a list with the lock (shape only)."""
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(n)}, separators=(",", ":"))


def blob(gen=1, n=200):
    """A list file (shape only): magic, generation, iv, ciphertext."""
    return b"KENC\x02" + struct.pack(">I", gen) + os.urandom(12) + os.urandom(n)


def keys():
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}


def wrapped():
    return {"v": 1, "iv": b64(12), "ct": b64(48)}


def code(r):
    try:
        return r.json().get("code")
    except ValueError:
        return None


def att(aid):
    r = dbx("SELECT enc, e2e_gen, mime, name, comment_id, path, size, enc_by FROM attachments WHERE id=?", (aid,))
    return dict(zip(("enc", "gen", "mime", "name", "comment_id", "path", "size", "enc_by"), r[0])) if r else None


def left(mode, gen, uid):
    rc, out, er = py("import json\nfrom kalmido.collab.liste2efile import le2f_left\nc=app.connect()\n"
                     f"rows, n = le2f_left(c, {L}, {mode!r}, {gen}, {uid}, 50)\nprint(json.dumps([n, sorted(r['id'] for r in rows)]))")
    if rc:
        print("le2f_left:", er, flush=True)
        return None
    return json.loads(out.splitlines()[-1])


def conv(s, aid, data, name, typ=None):
    d = {"name": name, **({"type": typ} if typ else {})}
    return s.post(B + f"/api/lists/{L}/e2e/files/{aid}", files={"file": ("x", data, "application/octet-stream")}, data=d)


def switch(sess_, plain):
    """Runs part A's todo / bulk for the texts (synthetic ciphertexts on the way in, plain words on the way back)."""
    for _ in range(10):
        todo = sess_.get(B + f"/api/lists/{L}/e2e/todo?limit=200").json()
        out_ = {}
        for kind in ("tasks", "comments", "notes", "sections"):
            rows = []
            for x in todo.get(kind) or []:
                y = {"id": x["id"]}
                for f, v in x.items():
                    if f != "id" and v is not None:
                        y[f] = ("plain " + f) if plain else ct()
                rows.append(y)
            if rows:
                out_[kind] = rows
        if todo.get("fields"):
            out_["fields"] = [{"task_id": x["task_id"], "field_id": x["field_id"], "value": "x" if plain else ct()} for x in todo["fields"]]
        if not out_:
            return
        r = sess_.post(B + f"/api/lists/{L}/e2e/bulk", json=out_)
        check(r.ok, f"bulk {r.status_code} {r.text[:300]}")


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"features": "collab,agents,comments,api", "lang": "en", "tour": "done"})
U = {}
for name in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123"})
    assert r.ok, r.text
    U[name] = r.json()["id"]
BOB, CAROL, DAVE = U["bob"], U["carol"], U["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments"})
for s in (A, Bo, Ca):
    assert s.put(B + "/api/e2e/keys", json=keys()).ok
L = A.post(B + "/api/lists", json={"name": "Strongbox"}).json()["id"]
LO = A.post(B + "/api/lists", json={"name": "Open list"}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": CAROL, "role": "view"}).ok
assert A.put(B + f"/api/lists/{LO}/members", json={"user_id": BOB, "role": "edit"}).ok
r = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "attachments:read", "attachments:write"]})
check(r.status_code == 201, f"API token {r.text[:200]}")
TOK = {"Authorization": "Bearer " + r.json()["token"]}

# ================================================================== before: plain files, a comment file, a per-person file
T = A.post(B + "/api/tasks", json={"title": "Contracts", "list_id": L}).json()["id"]
r = A.post(B + f"/api/tasks/{T}/attachments", files={"file": ("plan.txt", b"the garden plan", "text/plain")})
check(r.ok, f"plain file before the lock {r.text[:200]}")
P1 = r.json()["attachments"][0]["id"]
r = Bo.post(B + f"/api/tasks/{T}/comments", data={"body": "see the photo"}, files={"file": ("photo.png", b"\x89PNG fake", "image/png")})
check(r.ok, f"comment with a file before the lock {r.status_code} {r.text[:200]}")
CM1 = r.json()["id"]
P2 = dbx("SELECT id FROM attachments WHERE comment_id=?", (CM1,))[0][0]
r = Bo.post(B + f"/api/tasks/{T}/enc-attachments", files={"file": ("blob", b"KENC\x01" + os.urandom(300), "application/octet-stream")})
check(r.ok, f"bob's per-person file (2.42) {r.text[:200]}")
E1 = dbx("SELECT id FROM attachments WHERE task_id=? AND enc=1", (T,))[0][0]

# ================================================================== switch on: 'encrypting'
r = A.post(B + f"/api/lists/{L}/e2e/start", json={"keys": [{"user_id": u, "wrapped": wrapped()} for u in (1, BOB, CAROL)]})
check(r.ok and dbx("SELECT e2e FROM lists WHERE id=?", (L,))[0][0] == "encrypting", f"start {r.status_code} {r.text[:300]}")
r = A.post(B + f"/api/tasks/{T}/attachments", files={"file": ("new.txt", b"new", "text/plain")})
check(r.status_code == 409 and code(r) == "list_e2e", f"encrypting: a plain upload is refused {r.status_code} {r.text[:200]}")
r = A.post(B + f"/api/tasks/{T}/list-attachments", files={"file": ("x", blob(), "application/octet-stream")}, data={"name": ct()})
check(r.status_code == 409 and code(r) == "list_e2e_busy", f"encrypting: no new list file yet {r.status_code} {r.text[:200]}")
lf = left("encrypting", 1, 1)
check(lf == [2, sorted([P1, P2])], f"le2f_left encrypting (alice): the plain files, not bob's per-person file {lf}")
lf = left("encrypting", 1, BOB)
check(lf == [3, sorted([P1, P2, E1])], f"le2f_left encrypting (bob): + his per-person file {lf}")

r = conv(Bo, P1, blob(), ct())
check(r.status_code == 403, f"convert: not for an editor {r.status_code}")
r = conv(Da, P1, blob(), ct())
check(r.status_code == 404, f"convert: a stranger 404 {r.status_code}")
r = requests.post(B + f"/api/lists/{L}/e2e/files/{P1}", headers=TOK, files={"file": ("x", blob(), "application/octet-stream")}, data={"name": ct()})
check(r.status_code == 403, f"convert: not with an API token {r.status_code}")
r = conv(A, P1, b"PLAIN" + os.urandom(100), ct())
check(r.status_code == 400, f"convert: no list file magic -> 400 {r.status_code}")
r = conv(A, P1, blob(2), ct())
check(r.status_code == 400, f"convert: wrong generation -> 400 {r.status_code}")
r = conv(A, P1, blob(), "plan.txt")
check(r.status_code == 400, f"convert: a plain name -> 400 {r.status_code}")
old = att(P1)["path"]
B1 = blob(1, 300)
r = conv(A, P1, B1, ct())
a1 = att(P1)
check(r.ok and r.json().get("enc") == 2 and a1["enc"] == 2 and a1["gen"] == 1 and a1["mime"] == "application/octet-stream"
      and a1["name"].startswith("e2e1:") and a1["path"] != old and a1["size"] == len(B1), f"convert: P1 is a list file {r.text[:200]} {a1}")
check(conv(A, P1, blob(), ct()).status_code == 409, "convert: nothing to do any more -> 409")
r = conv(A, P2, blob(), ct())
a2 = att(P2)
check(r.ok and a2["enc"] == 2 and a2["comment_id"] == CM1, f"convert: the comment file keeps its comment {r.text[:200]} {a2}")
check(conv(A, E1, blob(), ct()).status_code == 409, "convert: bob's per-person file is not alice's to convert")
r = conv(Bo, E1, blob(), ct())
check(r.ok and att(E1)["enc"] == 2 and att(E1)["enc_by"] is None, f"convert: bob converts his own per-person file {r.text[:200]}")
check(left("encrypting", 1, BOB) == [0, []], "le2f_left encrypting: nothing left")
switch(A, False)
r = A.post(B + f"/api/lists/{L}/e2e/finish")
check(r.ok and dbx("SELECT e2e FROM lists WHERE id=?", (L,))[0][0] == "on", f"finish: on {r.status_code} {r.text[:300]}")

# ================================================================== 'on': the plain ways are closed
r = A.post(B + f"/api/tasks/{T}/attachments", files={"file": ("new.txt", b"new", "text/plain")})
check(r.status_code == 409 and code(r) == "list_e2e", f"on: web upload refused {r.status_code} {r.text[:200]}")
r = A.post(B + f"/api/tasks/{T}/enc-attachments", files={"file": ("blob", b"KENC\x01" + os.urandom(300), "application/octet-stream")})
check(r.status_code == 409 and code(r) == "list_e2e", f"on: the per-person file of 2.42 is replaced by list files {r.status_code}")
r = requests.post(V + f"/tasks/{T}/attachments/text", headers=TOK, json={"name": "a.md", "content": "# secret"})
check(r.status_code in (403, 409), f"on: API text file refused {r.status_code} {r.text[:200]}")
r = A.post(B + f"/api/lists/{L}/files", files={"file": ("p.txt", b"project", "text/plain")})
check(r.status_code == 409, f"on: project files refused {r.status_code} {r.text[:200]}")  # (list_e2e once the list is a project)
r = Bo.post(B + f"/api/tasks/{T}/comments", data={"body": ct()}, files={"file": ("p.txt", b"plain text", "text/plain")})
check(r.status_code == 400, f"on: a comment with a plain file is refused {r.status_code} {r.text[:200]}")
check(not dbx("SELECT 1 FROM attachments WHERE task_id=? AND enc=0", (T,)), "on: no plain file was stored")

# ================================================================== 'on': list files
r = Bo.post(B + f"/api/tasks/{T}/list-attachments", files={"file": ("x", blob(2), "application/octet-stream")}, data={"name": ct()})
check(r.status_code == 400, f"upload: a generation that is not the current one -> 400 {r.status_code}")
r = Bo.post(B + f"/api/tasks/{T}/list-attachments", files={"file": ("x", blob(), "application/octet-stream")}, data={"name": ct(2)})
check(r.status_code == 400, f"upload: the name of another generation -> 400 {r.status_code}")
r = Bo.post(B + f"/api/tasks/{T}/list-attachments", files={"file": ("x", blob(), "application/octet-stream")})
check(r.status_code == 400, f"upload: the name is missing -> 400 {r.status_code}")
r = Ca.post(B + f"/api/tasks/{T}/list-attachments", files={"file": ("x", blob(), "application/octet-stream")}, data={"name": ct()})
check(r.status_code == 403, f"upload: a viewer cannot add task files {r.status_code}")
r = Da.post(B + f"/api/tasks/{T}/list-attachments", files={"file": ("x", blob(), "application/octet-stream")}, data={"name": ct()})
check(r.status_code == 404, f"upload: a stranger 404 {r.status_code}")
r = requests.post(B + f"/api/tasks/{T}/list-attachments", headers=TOK, files={"file": ("x", blob(), "application/octet-stream")}, data={"name": ct()})
check(r.status_code == 403, f"upload: not with an API token {r.status_code}")
BL = blob(1, 1000)
NAME = ct()
r = Bo.post(B + f"/api/tasks/{T}/list-attachments", files={"file": ("x", BL, "application/octet-stream")}, data={"name": NAME})
F1 = None
if r.ok:
    fs = [a for a in r.json().get("attachments", []) if a.get("name") == NAME]
    F1 = fs[0]["id"] if fs else None
    check(fs and fs[0].get("enc") == 2 and fs[0].get("e2e_gen") == 1 and fs[0].get("size") == len(BL), f"upload: the task shows enc 2 + e2e_gen {fs}")
check(r.ok and F1, f"upload: bob adds a list file {r.status_code} {r.text[:200]}")
# a comment with list files in one request (body cipher, field le2e_name per file)
r = Bo.post(B + f"/api/tasks/{T}/comments", data={"body": ct(), "le2e_name": ct()}, files={"file": ("encrypted.kenc", blob(), "application/octet-stream")})
check(r.ok and r.json()["attachments"] and r.json()["attachments"][0].get("enc") == 2, f"comment with a list file {r.status_code} {r.text[:200]}")
CM2 = r.json().get("id") if r.ok else None
r = Ca.post(B + f"/api/tasks/{T}/list-attachments", files={"file": ("x", blob(), "application/octet-stream")}, data={"name": ct(), "comment_id": CM2})
check(r.status_code == 403, f"comment file: not on someone else's comment {r.status_code}")
r = Bo.post(B + f"/api/tasks/{T}/list-attachments", files={"file": ("x", blob(), "application/octet-stream")}, data={"name": ct(), "comment_id": CM2})
check(r.ok and len(dbx("SELECT id FROM attachments WHERE comment_id=? AND enc=2", (CM2,))) == 2, f"comment file: the author adds one {r.status_code} {r.text[:200]}")
cms = Ca.get(B + f"/api/tasks/{T}/timeline").json().get("comments", [])
c2 = [c for c in cms if isinstance(c, dict) and c.get("id") == CM2]
check(c2 and all(a.get("enc") == 2 and a.get("e2e_gen") == 1 for a in c2[0]["attachments"]), f"comment files carry enc 2 + e2e_gen {c2[:1]}")

# download
r = Ca.get(B + f"/api/attachments/{F1}")
check(r.ok and r.content == BL and "encrypted.kenc" in r.headers.get("Content-Disposition", ""), f"download: a viewer gets the bytes as stored {r.status_code}")
check(Da.get(B + f"/api/attachments/{F1}").status_code == 404, "download: a stranger 404")
check(requests.get(B + f"/api/attachments/{F1}", headers=TOK).status_code in (401, 403, 404), "download: API token refused (app route)")
check(requests.get(V + f"/attachments/{F1}", headers=TOK).status_code == 404, "download: API v1 404")
check(requests.get(V + f"/attachments/{F1}/text", headers=TOK).status_code == 404, "text extract: 404")
r = requests.get(V + f"/tasks/{T}/attachments", headers=TOK)
if r.ok:
    e = [x for x in r.json()["data"] if x["id"] == F1]
    check(e and e[0].get("encrypted") is True and not e[0].get("name"), f"API v1: listed as encrypted, no name {e}")
else:
    check(r.status_code in (403, 404), f"API v1 list of files {r.status_code}")
check(A.get(B + f"/api/attachments/{P1}").content == B1, "download: the converted file")

# a rotation (part A) leaves older files to convert
dbx("UPDATE lists SET e2e_gen=2 WHERE id=?", (L,), write=True)
lf = left("on", 2, 1)
check(lf and lf[0] == len(dbx("SELECT a.id FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND a.enc=2", (L,))),
      f"le2f_left on: every list file of generation 1 {lf}")
r = conv(A, F1, blob(1), ct(1))
check(r.status_code == 400, f"convert on: still generation 1 -> 400 {r.status_code}")
r = conv(A, F1, blob(2), ct(2))
check(r.ok and att(F1)["gen"] == 2, f"convert on: generation 2 {r.text[:200]}")
check(conv(A, F1, blob(2), ct(2)).status_code == 409, "convert on: current generation -> nothing to do")
check(F1 not in (left("on", 2, 1) or [0, []])[1], "le2f_left on: the converted file is done")
for (aid,) in dbx("SELECT a.id FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND a.enc=2 AND a.e2e_gen<2", (L,)):
    check(conv(A, aid, blob(2), ct(2)).ok, f"convert on: {aid}")
check(left("on", 2, 1) == [0, []], "le2f_left on: nothing left")

# moves: a task with list files stays in its list
r = A.patch(B + f"/api/tasks/{T}", json={"list_id": LO, "title": "Contracts"})
check(r.status_code == 409 and code(r) == "list_e2e_files", f"move: a task with list files stays {r.status_code} {r.text[:200]}")
check(dbx("SELECT list_id FROM tasks WHERE id=?", (T,))[0][0] == L, "move: nothing changed")

# ================================================================== the way back: 'decrypting'
dbx("UPDATE lists SET e2e_gen=1 WHERE id=?", (L,), write=True)  # the keys of this test are generation 1 (the files stay generation 2)
r = A.post(B + f"/api/lists/{L}/e2e/stop", json={"password": "password123"})
check(r.ok and dbx("SELECT e2e FROM lists WHERE id=?", (L,))[0][0] == "decrypting", f"stop {r.status_code} {r.text[:200]}")
n_enc = len(dbx("SELECT a.id FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND a.enc=2", (L,)))
lf = left("decrypting", 1, 1)
check(lf and lf[0] == n_enc, f"le2f_left decrypting: every list file {lf} {n_enc}")
r = conv(A, F1, blob(2), "contract.pdf", "application/pdf")
check(r.status_code == 400, f"decrypting: no list file any more -> 400 {r.status_code}")
r = conv(A, F1, b"%PDF-1.4 plain", ct(2), "application/pdf")
check(r.status_code == 400, f"decrypting: no ciphertext as a name -> 400 {r.status_code}")
r = conv(A, F1, b"%PDF-1.4 the contract", "contract.pdf", "application/pdf")
a3 = att(F1)
check(r.ok and a3["enc"] == 0 and a3["name"] == "contract.pdf" and a3["mime"] == "application/pdf" and a3["gen"] == 0,
      f"decrypting: a plain file again {r.text[:200]} {a3}")
check(A.get(B + f"/api/attachments/{F1}?dl=1").content == b"%PDF-1.4 the contract", "decrypting: download in plain")
r = conv(A, P2, b"\x89PNG\r\n\x1a\n fake", "photo.png", "bad type<>")  # vorint: the full PNG signature (2.61.0 takes the type from the content)
check(r.ok and att(P2)["mime"] == "image/png", f"decrypting: a bad type falls back to the name's type {att(P2)}")
for (aid,) in dbx("SELECT a.id FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.list_id=? AND a.enc=2", (L,)):
    check(conv(A, aid, b"plain bytes", f"file-{aid}.txt", "text/plain").ok, f"decrypting: {aid}")
check(left("decrypting", 1, 1) == [0, []], "le2f_left decrypting: nothing left")
switch(A, True)
r = A.post(B + f"/api/lists/{L}/e2e/finish")
check(r.ok and dbx("SELECT e2e FROM lists WHERE id=?", (L,))[0][0] is None, f"finish: open again {r.status_code} {r.text[:300]}")
r = A.post(B + f"/api/tasks/{T}/attachments", files={"file": ("again.txt", b"again", "text/plain")})
check(r.ok, f"open again: plain uploads work {r.status_code}")
r = A.post(B + f"/api/tasks/{T}/list-attachments", files={"file": ("x", blob(), "application/octet-stream")}, data={"name": ct()})
check(r.status_code == 409, f"open list: no list files {r.status_code}")

print(f"p264b_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
