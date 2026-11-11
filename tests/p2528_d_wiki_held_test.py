#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.528.0 D API tests (#4306, B26), own container: switching the lock of a knowledge space on no longer deletes its history
and its files in the trash at once.
 - GET /api/wiki/e2e names what a switch would hold (held: versions, files, days, purge_on) for the question in the browser
 - start (also without that question, as an old client / the API) holds them: rows and the stored file stay, marked
 - while the space is locked nobody sees them (no history, a held file is not restored)
 - open again: the people of the space at the switch see the held versions, a member who joined later does not (list, one
   version, restore of a held file); a page restored from the trash leaves a held file to who may see it
 - the run (wkhist.wkx_tick): a held version not yet due stays; due but the space open again stays; due and locked: with the
   deleted after the period, also with the retention switch off (review 2.528); a held file in the trash goes with them
 - a person without an organisation (freelancer-matrix: wiki): the same in the private space
 - (B27) a knowledge folder back out of the file store's trash brings its page back, also when its name was taken meanwhile
   ("Name (2)"); single and bulk restore; organisation and a person without an organisation
usage: p2528_d_wiki_held_test.py <datadir>      (P2528D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import json
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
OLD = "2026-01-01T00:00:00+00:00"  # long before any trash period (the time is put into the database, never waited for)
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        if write:
            c.execute(q, args)
            c.commit()
            return None
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def keys_up(s):
    keys = {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}
    r = s.put(B + "/api/e2e/keys", json=keys)
    assert r.ok, r.text


def page(s, space, path, body=""):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def save(s, pid, text):
    r = s.patch(B + f"/api/wiki/pages/{pid}", json={"body": text})
    assert r.ok, r.text


def upload(s, pid, name="a.png"):
    r = s.post(B + f"/api/wiki/pages/{pid}/files", files={"file": (name, PNG, "image/png")})
    assert r.status_code == 201, r.text
    f = r.json()["files"][0]
    return f["id"], sql("SELECT path FROM wiki_files WHERE id=?", (f["id"],))[0][0]


def stored(rel):
    return os.path.isfile(os.path.join(DATA, "attachments", rel))


def vers(s, pid):
    r = s.get(B + f"/api/wiki/pages/{pid}/versions")
    return r.json().get("versions") if r.ok else None


def nvers(pid):
    return sql("SELECT COUNT(*) FROM obj_versions WHERE kind='wiki' AND ref_id=?", (pid,))[0][0]  # 2.958.0 (#5281): obj_versions


def start(s, space, uid):
    return s.post(B + "/api/wiki/e2e/start", json={"space": space, "keys": [{"user_id": uid, "wrapped": {"v": 1, "iv": b64(12), "ct": b64(48)}}]})


def run(fn, purge):
    """A watchdog run inside the app container, called directly (force), with the retention switch of the trash on / off."""
    mod = {"wkx_tick": "kalmido.wiki.wkhist", "wka_tick": "kalmido.wiki.wikiatt"}[fn]
    code = (f"import json, app\nfrom {mod} import {fn}\nfrom kalmido.core.db import connect\nc = connect()\n"
            f"try:\n    print(json.dumps({fn}(c, force=True)))\nfinally:\n    c.close()")
    out = subprocess.run(["docker", "exec", "-e", f"KALMIDO_PURGE_TRASH={1 if purge else 0}", CT, "python", "-c", code],
                         capture_output=True, text=True)
    check(out.returncode == 0, f"{fn} runs {out.stdout[-200:]} {out.stderr[-600:]}")
    return out.stdout


if os.environ.get("P2528D_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Later")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,wiki", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
keys_up(A)
ORG = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
SP = f"org:{ORG}"

# ---------------------------------------------------------------- setup: a page with history, a file in the trash
P = page(A, SP, "Plan", "first state")
save(Bo, P, "second state by Bob")
save(A, P, "third state by Alice")
NV = nvers(P)
check(NV >= 2 and len(vers(A, P)) == NV, f"setup: the page has a history {NV}")
F1, REL1 = upload(A, P, "one.png")
F2, REL2 = upload(A, P, "two.png")
r = A.post(B + "/api/wiki/trash", json={"ids": [], "files": [F1, F2]})
check(r.ok and r.json().get("files") == [F1, F2], "setup: both files in the trash " + r.text[:200])

# ---------------------------------------------------------------- the question before: what a switch would hold
r = A.get(B + "/api/wiki/e2e", params={"space": SP})
h = r.json().get("held") if r.ok else None
check(r.ok and h and h.get("versions") == NV and h.get("files") == 2 and int(h.get("days") or 0) >= 1 and h.get("purge_on") is False,
      "#4306: GET /api/wiki/e2e names the versions / trash files a switch holds, the period and the switch " + r.text[-300:])

# ---------------------------------------------------------------- switching on (no question asked: an old client / the API)
r = start(A, SP, ALICE)
check(r.ok and r.json().get("mode") == "encrypting" and r.json().get("held") == {"versions": NV, "files": 2},
      f"#4306: the switch starts and names what it held {r.status_code} {r.text[-300:]}")
check(nvers(P) == NV, f"#4306 (B26): the history is still there after switching on {nvers(P)} / {NV}")
fr = sql("SELECT id, deleted_at, wkx_held_at FROM wiki_files WHERE id IN (?, ?) ORDER BY id", (F1, F2))
check(len(fr) == 2 and all(x[1] and x[2] for x in fr) and stored(REL1) and stored(REL2),
      f"#4306 (B26): the files in the trash and their stored bytes are still there, held {fr}")
HELD = sql("SELECT DISTINCT held_at FROM obj_versions WHERE kind='wiki' AND ref_id=?", (P,))  # 2.958.0 (#5281): held_at
check(len(HELD) == 1 and HELD[0][0], f"#4306: every version is held from the switch {HELD}")
holds = json.loads(sql("SELECT wkx_holds FROM wiki_spaces WHERE org_id=?", (ORG,))[0][0])
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
check(sorted(holds.get(HELD[0][0], [])) == sorted([ALICE, BOB]), f"#4306: the people of the space then are named {holds}")
check(sql("SELECT COUNT(*) FROM wiki_words WHERE page_id=?", (P,))[0][0] == 0, "the word index of the space still goes (derived)")

# ---------------------------------------------------------------- locked: nobody sees them
check(A.get(B + f"/api/wiki/pages/{P}/versions").json() == {"versions": [], "e2e": True}, "#4306: locked = no history shown")
r = A.post(B + "/api/wiki/restore", json={"ids": [], "files": [F1]})
check(r.ok and r.json().get("files") == [] and r.json().get("files_skipped") == [F1], "#4306: a held file is not restored while locked " + r.text[:200])

# ---------------------------------------------------------------- the run: not yet due -> stays
run("wkx_tick", True)
check(nvers(P) == NV, "#4306: the run leaves held versions inside the period")

# ---------------------------------------------------------------- open again: only who could read the space then
sql("UPDATE wiki_spaces SET e2e=NULL WHERE org_id=?", (ORG,), write=True)  # as after the way back (pages still plain here)
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com", "role": "member"}).ok  # joins after the switch
check(len(vers(A, P) or []) == NV and len(vers(Bo, P) or []) == NV, "#4306: open again, the people of the space then see the held history")
cv = vers(Ca, P)
check(cv == [], f"#4306: a member who joined later sees no held version {cv}")
vid = vers(A, P)[0]["id"]
check(Ca.get(B + f"/api/wiki/pages/{P}/versions/{vid}").status_code == 404 and A.get(B + f"/api/wiki/pages/{P}/versions/{vid}").ok,
      "#4306: one held version: 404 for the later member, readable for the earlier one")
check(Ca.post(B + f"/api/wiki/pages/{P}/versions/{vid}/restore", json={}).status_code in (403, 404), "#4306: the later member cannot restore a held version")
r = Ca.post(B + "/api/wiki/restore", json={"ids": [], "files": [F1]})
check(r.ok and r.json().get("files_skipped") == [F1], "#4306: the later member cannot restore a held file " + r.text[:200])
r = A.post(B + "/api/wiki/restore", json={"ids": [], "files": [F1]})
check(r.ok and r.json().get("files") == [F1] and sql("SELECT deleted_at, wkx_held_at FROM wiki_files WHERE id=?", (F1,))[0] == (None, None),
      "#4306: an earlier member restores the held file: an ordinary file again " + r.text[:200])
check(A.get(B + f"/api/wiki/files/{F1}").content == PNG, "#4306: the restored file is readable")

# a page in the trash with a held file: back from the trash, the file only for who may see it
Q = page(A, SP, "Sub", "x")
F3, REL3 = upload(A, Q, "three.png")
check(A.delete(B + f"/api/wiki/pages/{Q}").ok, "setup: page with file to the trash")
qdel = sql("SELECT deleted_at FROM wiki_pages WHERE id=?", (Q,))[0][0]
sql("UPDATE wiki_files SET deleted_at=?, wkx_held_at=? WHERE id=?", (qdel, HELD[0][0], F3), write=True)  # trashed with it, held
r = Ca.post(B + "/api/wiki/restore", json={"ids": [Q]})
check(r.ok and r.json().get("ids") == [Q] and sql("SELECT deleted_at FROM wiki_files WHERE id=?", (F3,))[0][0],
      "#4306: the later member brings the page back, the held file stays in the trash " + r.text[:200])
check(A.delete(B + f"/api/wiki/pages/{Q}").ok, "setup: to the trash again")
qdel = sql("SELECT deleted_at FROM wiki_pages WHERE id=?", (Q,))[0][0]
sql("UPDATE wiki_files SET deleted_at=? WHERE id=?", (qdel, F3), write=True)
r = A.post(B + "/api/wiki/restore", json={"ids": [Q]})
check(r.ok and sql("SELECT deleted_at, wkx_held_at FROM wiki_files WHERE id=?", (F3,))[0] == (None, None),
      "#4306: an earlier member brings the page back with its held file " + r.text[:200])

# ---------------------------------------------------------------- the period: due, but open -> stays; due and locked -> goes
sql("UPDATE obj_versions SET held_at=? WHERE kind='wiki' AND ref_id=? AND held_at IS NOT NULL", (OLD, P), write=True)  # 2.958.0 (#5281)
sql("UPDATE wiki_spaces SET wkx_holds=? WHERE org_id=?", (json.dumps({OLD: [ALICE, BOB]}), ORG), write=True)
run("wkx_tick", True)
check(nvers(P) >= NV, "#4306: held versions of a space open again stay after the period")
sql("UPDATE wiki_spaces SET e2e='on' WHERE org_id=?", (ORG,), write=True)
sql("UPDATE wiki_files SET deleted_at=?, wkx_held_at=? WHERE id=?", (OLD, OLD, F2), write=True)
# 2.528.0 (#4306, review Fable 1): with the retention switch off the held rows of a locked space still go after the period
# (before: only counted, readable copies of an encrypted space stayed for good)
run("wkx_tick", False)
check(sql("SELECT COUNT(*) FROM obj_versions WHERE kind='wiki' AND ref_id=? AND held_at IS NOT NULL", (P,))[0][0] == 0,
      "#4306 (B26): after the trash period the run deletes the held versions of the locked space, also with the switch off")
check(not sql("SELECT 1 FROM wiki_files WHERE id=?", (F2,)) and not stored(REL2),
      "#4306 (B26): the held file in the trash goes with them after the period, also with the switch off")
run("wkx_tick", True)
check(json.loads(sql("SELECT wkx_holds FROM wiki_spaces WHERE org_id=?", (ORG,))[0][0]) == {}, "#4306: a hold no row names any more is cleared")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: wiki)
FID, Fr = freelancer(B, A, features="cal,comments,collab,wiki")
keys_up(Fr)
fp = page(Fr, "private", "Diary", "one")
save(Fr, fp, "two")
fsql = "UPDATE obj_versions SET created_at=?, updated_at=? WHERE kind='wiki' AND ref_id=?"  # 2.958.0 (#5281)
sql(fsql, (OLD, OLD, fp), write=True)  # the next save is a version of its own (no merge with the last one)
save(Fr, fp, "three")
FV = nvers(fp)
ff, frel = upload(Fr, fp, "f.png")
assert Fr.post(B + "/api/wiki/trash", json={"ids": [], "files": [ff]}).ok
h = Fr.get(B + "/api/wiki/e2e", params={"space": "private"}).json().get("held")
check(h and h.get("versions") == FV and h.get("files") == 1, f"freelancer: the question names versions and the trash file {h}")
r = start(Fr, "private", FID)
check(r.ok and nvers(fp) == FV and sql("SELECT wkx_held_at FROM wiki_files WHERE id=?", (ff,))[0][0] and stored(frel),
      f"freelancer #4306 (B26): switching on keeps history and trash file {r.status_code} {r.text[-200:]}")
check(Fr.get(B + f"/api/wiki/pages/{fp}/versions").json() == {"versions": [], "e2e": True}, "freelancer: locked = no history shown")
sql("UPDATE obj_versions SET held_at=? WHERE kind='wiki' AND ref_id=?", (OLD, fp), write=True)  # 2.958.0 (#5281)
run("wkx_tick", True)
check(nvers(fp) == 0, "freelancer #4306: after the period the held versions of the locked private space go")

# ================================================================ #4306 (B27): a knowledge folder back out of the file store's trash
def node_of(pid):
    r = sql("SELECT id, parent_id FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (pid,))
    return r[0] if r else None


def b27(s, space, who):
    """A page in a folder; the folder into the file store's trash; a new page takes the name; the folder comes back."""
    pid = page(s, space, "Box/Alpha", "alpha text")
    assert s.get(B + "/api/wiki", params={"space": space}).ok  # the tree is made (wkf_sync)
    fb = node_of(pid)[1]
    r = s.delete(B + f"/api/files/nodes/{fb}")
    check(r.ok and sql("SELECT deleted_at FROM wiki_pages WHERE id=?", (pid,))[0][0], f"{who}: the folder into the trash takes its page along " + r.text[:200])
    other = page(s, space, "Box/Alpha", "a new page of the same name")
    r = s.post(B + f"/api/files/nodes/{fb}/restore")
    row = sql("SELECT deleted_at, path FROM wiki_pages WHERE id=?", (pid,))[0]
    check(r.ok and row[0] is None and row[1] == "Box/Alpha (2)" and not (r.json().get("stays") or {}).get("wiki"),
          f"{who} #4306 (B27): the folder's restore brings the page back, its taken name as \"Alpha (2)\" {row} {r.text[-200:]}")
    check(sql("SELECT path, deleted_at FROM wiki_pages WHERE id=?", (other,))[0] == ("Box/Alpha", None), f"{who}: the new page keeps its name")
    pid2 = page(s, space, "Crate/Beta", "beta")
    assert s.get(B + "/api/wiki", params={"space": space}).ok
    fc = node_of(pid2)[1]
    assert s.delete(B + f"/api/files/nodes/{fc}").ok
    r = s.post(B + "/api/files/restore", json={"ids": [fc]})
    check(r.ok and sql("SELECT deleted_at FROM wiki_pages WHERE id=?", (pid2,))[0][0] is None, f"{who} #4306: the bulk restore brings the page back " + r.text[:200])


ORG3 = A.post(B + "/api/admin/orgs", json={"name": "Delta", "admin_id": ALICE}).json()["id"]
b27(A, f"org:{ORG3}", "organisation")
_, Fo = freelancer(B, A, "fiona", features="cal,comments,collab,wiki,files")
b27(Fo, "private", "freelancer")  # freelancer-matrix: wiki

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
