#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.353.0 (#2769): scan inboxes (docs:upload keys of the folder watcher) and every way into the documents (docs_ingest) never
take a locked folder (files/fslock.py) -- invented names only.
 - making a scan inbox for a locked folder: 409 "Locked folders take no scans"
 - an inbox made for a folder that is locked later: the upload 409 with the same message (the watcher shows it and tries
   later), upload-target too; nothing is stored
 - the documents upload with parent_id into a locked folder: 409 (the same guard as the mail address and imports)
 - a person without an organisation (her private space)
usage: p2353_a_scanlock_test.py <datadir>      (a fresh container; P2353S_NOSTART=1 / KMT_NOSTART=1: it runs already)
freelancer-matrix: files"""
import base64
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

V = B + "/api/v1"
MSG = "Locked folders take no scans"
kt.fresh(prefix="P2353S")
A = kt.setup()


def bearer(tok):
    return {"Authorization": "Bearer " + tok}


def wrapped():
    return {"v": 1, "iv": base64.b64encode(os.urandom(12)).decode(), "ct": base64.b64encode(os.urandom(48)).decode()}


def keys():
    u = lambda n: base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")  # noqa: E731
    b = lambda n: base64.b64encode(os.urandom(n)).decode()  # noqa: E731
    return {"pub": {"kty": "EC", "crv": "P-256", "x": u(32), "y": u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b(16), "iv": b(12), "ct": b(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b(16), "iv": b(12), "ct": b(200)}}


FID, Fr = freelancer(B, A)
assert Fr.put(B + "/api/e2e/keys", json=keys()).ok
assert Fr.post(B + "/api/docs", files={"files": ("start.txt", b"Start example", "text/plain")}, data={"ws": "private"}).ok


def folder(name):
    r = Fr.post(B + "/api/files/folders", json={"name": name, "space": "private"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def lock(nid):
    r = Fr.post(B + f"/api/files/lock/{nid}/start", json={"keys": [{"user_id": FID, "wrapped": wrapped()}]})
    assert r.ok, r.text
    assert Fr.post(B + f"/api/files/lock/{nid}/finish", json={}).ok


def up(tok, name="scan.txt"):
    return requests.post(V + "/documents", headers=bearer(tok), files={"file": (name, b"Invoice example 4711", "text/plain")})


# an inbox for a folder that gets locked later
LATER = folder("Scans later locked")
r = Fr.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": "Scanner", "parent_id": LATER})
check(r.status_code == 201, f"an inbox for an open folder {r.text[:200]}")
code = r.json().get("code", "kalmido-scan:1:")[len("kalmido-scan:1:"):]
K = json.loads(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))).get("key", "") if code else ""
r = requests.get(V + "/documents/upload-target", headers=bearer(K))
check(r.ok, f"open folder: the inbox works {r.status_code} {r.text[:120]}")
lock(LATER)
n0 = kt.dbx("SELECT COUNT(*) FROM fs_nodes WHERE parent_id=?", (LATER,))[0][0]
r = up(K, "second.txt")
check(r.status_code == 409 and MSG in r.text, f"locked later: the upload 409 with the message {r.status_code} {r.text[:200]}")
check(kt.dbx("SELECT COUNT(*) FROM fs_nodes WHERE parent_id=?", (LATER,))[0][0] == n0, "nothing stored in the locked folder")
r = requests.get(V + "/documents/upload-target", headers=bearer(K))
check(r.status_code == 409 and MSG in r.text, f"upload-target names the reason {r.status_code} {r.text[:200]}")

# no inbox is made for a locked folder
LOCKED = folder("Locked box")
lock(LOCKED)
r = Fr.post(B + "/api/docs/scan-keys", json={"ws": "private", "name": "Scanner 2", "parent_id": LOCKED})
check(r.status_code == 409 and MSG in r.text, f"making an inbox for a locked folder 409 {r.status_code} {r.text[:200]}")

# the documents upload with a folder (the same guard as the documents mail address and the imports: docs_ingest)
tok = Fr.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "write"]}).json().get("token", "")
r = requests.post(V + "/documents", headers=bearer(tok), files={"file": ("x.txt", b"invented", "text/plain")}, data={"parent_id": str(LOCKED)})
check(r.status_code in (403, 404, 409), f"documents into a locked folder refused {r.status_code} {r.text[:200]}")
check(kt.dbx("SELECT COUNT(*) FROM fs_nodes WHERE parent_id=?", (LOCKED,))[0][0] == 0, "the locked folder stays empty")

# the documents settings offer no locked folder as a place
fs = Fr.get(B + "/api/docs/settings?ws=private").json().get("folders", [])
check(not any(f["id"] in (LOCKED, LATER) for f in fs), "the settings offer no locked folder")
sys.exit(kt.done("p2353_a_scanlock"))
