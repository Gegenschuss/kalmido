#!/usr/bin/env python3
# kalmido-suite: fresh
"""#4300 (2.507.0): locked folders of the file store survive an account and an organisation move, or say that they do not.
Invented names only, ciphertexts of the right shape (the browser's cryptography itself runs in p2507_a_lockmove_ui.js).
 - freelancer-matrix: files -- a person without an organisation locks a folder: the account export carries the lock and only
   the own copy of the folder key, the manifest counts it
 - into a person without keys: the preview says it comes along, the lock is there with the OLD ids its ciphertexts are bound to,
   the cipher names and KENC bytes are unchanged and readable through the lock routes; handing the key on clears those ids
 - into a person with other keys: preview and result name the folder, no node with a cipher name exists (no silent junk)
 - an older archive without lock rows: the same, by the cipher nodes
 - a second move keeps the first server's ids; undo removes the folder and its lock
 - an organisation export carries the exporting person's own copy only, a copy another person wrapped has no wrapper on the
   target; an exporter without a copy: named as staying out"""
# freelancer-matrix: files
import base64
import hashlib
import io
import json
import os
import sys
import time
import zipfile

import kt
from kt import B, check, dbx
from freelancer_fixture import FEATURES, freelancer

KEY = base64.b64encode(os.urandom(32)).decode()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def keys_body():
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32)},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(120)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(120)}}


def wrapped():
    return {"v": 1, "iv": b64(12), "ct": b64(48)}


def ct(gen=1):
    return "e2e1:" + json.dumps({"v": 1, "g": gen, "iv": b64(12), "ct": b64(90)}, separators=(",", ":"))


def kenc(gen=1):
    return b"KENC\x02" + gen.to_bytes(4, "big") + os.urandom(12) + os.urandom(64)


def folder(s, name, parent=None, space="private"):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": space})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def lock(s, nid, *uids):
    """A folder locked the way the browser does it, with one encrypted file. -> the file's id, cipher name, bytes."""
    r = s.post(B + f"/api/files/lock/{nid}/start", json={"keys": [{"user_id": u, "wrapped": wrapped()} for u in uids]})
    assert r.ok, r.text
    r = s.post(B + f"/api/files/lock/{nid}/finish", json={})
    assert r.ok, r.text
    n, blob = ct(), kenc()
    r = s.post(B + "/api/files/lock/upload", data={"parent_id": str(nid), "name": n}, files={"file": ("encrypted.kenc", blob, "application/octet-stream")})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"], n, blob


def export_of(s, secs=120):
    assert s.post(B + "/api/account/export").status_code == 202
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + "/api/account/export").json()
        if j.get("state") != "running":
            break
        time.sleep(0.25)
    assert j.get("state") == "done", j
    r = kt.su_get(s, B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    return r.content


def wait(s, iid, secs=180):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def preview(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "konto.zip"})
    assert r.ok, r.text
    iid = r.json()["id"]
    assert s.put(B + f"/api/account/import/{iid}?offset=0", data=data, headers={"Content-Type": "application/octet-stream"}).ok
    return iid, wait(s, iid)


def run(s, iid, target="private"):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": target, "people": {}, "again": True})
    assert r.status_code == 202, r.text
    return wait(s, iid)


def warns(j):
    return " | ".join(str(w.get("text", "")) for w in (j.get("result") or {}).get("warnings") or [])


def zjson(data, name):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return json.loads(z.read(name))


def without(data, *names):
    """The export as an older version wrote it: without these parts, the checksums made to fit."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        files = {n: z.read(n) for n in z.namelist() if n not in (*names, "manifest.json", "checksum.sha256")}
        man = json.loads(z.read("manifest.json"))
    man["files"] = [{"path": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in files.items()]
    mb = json.dumps(man).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
        z.writestr("manifest.json", mb)
        z.writestr("checksum.sha256", "\n".join(f"{hashlib.sha256(b).hexdigest()}  {n}" for n, b in [("manifest.json", mb), *files.items()]) + "\n")
    return out.getvalue()


def cipher_nodes(uid):
    return one("SELECT COUNT(*) FROM fs_nodes WHERE owner_id=? AND (name LIKE 'e2e1:%' OR e2e_gen>0)", (uid,))


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SECRET_KEY": KEY, "KALMIDO_ORGCRYPT_DELAY": "0"})
A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
FRIDA, Fr = freelancer(B, A, "frida")   # moves; no organisation (P4)
GINA, Gi = freelancer(B, A, "gina")     # target without keys
HANK, Ha = freelancer(B, A, "hank")     # target with own keys
IVAN, Iv = freelancer(B, A, "ivan")     # second move
JO, Jo = freelancer(B, A, "jona")       # older archive
BOB, Bo = freelancer(B, A, "bobby")     # somebody else holding a copy

KF = keys_body()
check(Fr.put(B + "/api/e2e/keys", json=KF).ok, "frida sets up her keys")
check(Ha.put(B + "/api/e2e/keys", json=keys_body()).ok, "hank sets up his keys")
check(Bo.put(B + "/api/e2e/keys", json=keys_body()).ok, "bobby sets up his keys")
TOP = folder(Fr, "Akten")
SAFE = folder(Fr, "Vertraege", TOP)
F1, N1, BLOB = lock(Fr, SAFE, FRIDA)
r = Fr.post(B + f"/api/files/nodes/{SAFE}/shares", json={"user_id": BOB, "role": "view"})
check(r.ok, "the locked folder is shared with bobby " + r.text[:160])
r = Fr.post(B + f"/api/files/lock/{SAFE}/keys", json={"keys": [{"user_id": BOB, "gen": 1, "wrapped": wrapped()}]})
check(r.ok, "bobby gets a copy of the key " + r.text[:160])

# ---------------------------------------------------------------- the export
EXP = export_of(Fr)
locks = zjson(EXP, "data/private_locks.json")
lkeys = zjson(EXP, "data/private_lock_keys.json")
check(len(locks) == 1 and locks[0]["node_id"] == SAFE and locks[0]["e2e"] == "on" and locks[0]["aad_folder"] == SAFE, f"the lock in the export {locks}")
check(len(lkeys) == 1 and lkeys[0]["aad_r"] == FRIDA and lkeys[0]["aad_w"] == FRIDA and KF["pub"]["x"] in lkeys[0]["recipient_pub"],
      f"only frida's own copy of the key, for her key pair {[(k['aad_r'], k['aad_w']) for k in lkeys]}")
check("private_lock_keys" in json.dumps(zjson(EXP, "manifest.json").get("client_encrypted")) and zjson(EXP, "manifest.json")["client_encrypted"]["locked_folders"] == 1,
      "the manifest counts and explains the locked folder")

# ---------------------------------------------------------------- into a person without keys
iid, j = preview(Gi, EXP)
enc = (j.get("preview") or {}).get("encrypted") or {}
check(enc.get("keys") == "take" and enc.get("locked_folders") == 1 and enc.get("locked_folders_lost") == 0, f"preview: the folder comes along {enc}")
j = run(Gi, iid)
check(j.get("state") == "done", f"import into gina {j.get('state')} {j.get('error')}")
check("Locked folders taken over" in warns(j) and "stays out" not in warns(j), "result: it says the folder came along " + warns(j))
G_SAFE = one("SELECT id FROM fs_nodes WHERE owner_id=? AND name='Vertraege' AND deleted_at IS NULL", (GINA,))
check(G_SAFE and G_SAFE != SAFE, "gina has the folder under a new id")
row = dbx("SELECT e2e, e2e_gen, e2e_by, aad_folder, org_id FROM fs_locks WHERE node_id=?", (G_SAFE,))
check(row and tuple(row[0]) == ("on", 1, GINA, SAFE, None), f"the lock is there, bound to the old folder id {row}")
kr = dbx("SELECT user_id, gen, wrapped_by, aad_r, aad_w, wrapped FROM fs_lock_keys WHERE node_id=?", (G_SAFE,))
check(len(kr) == 1 and tuple(kr[0][:5]) == (GINA, 1, GINA, FRIDA, FRIDA) and json.loads(kr[0][5])["ct"] == json.loads(lkeys[0]["wrapped"])["ct"],
      f"gina's copy: the wrap as it was, with the old ids {[tuple(x[:5]) for x in kr]}")
info = Gi.get(B + f"/api/files/lock/{G_SAFE}").json()
check(info.get("mode") == "on" and info.get("aad_id") == SAFE and info.get("can_manage"), f"the browser learns the old folder id {info.get('aad_id')}")
check(info["keys"][0].get("aad_r") == FRIDA and info["keys"][0].get("aad_w") == FRIDA, "the browser learns the old ids of its copy")
kids = Gi.get(B + "/api/files", params={"parent": G_SAFE}).json().get("items") or []
check(len(kids) == 1 and kids[0]["name"] == N1, "the cipher name came over unchanged")
G_F1 = kids[0]["id"]
r = Gi.get(B + f"/api/files/lock/{G_SAFE}/raw/{G_F1}")
check(r.ok and r.content == BLOB, "the KENC bytes came over unchanged and open through the lock route")
check(one("SELECT e2e_gen FROM fs_nodes WHERE id=?", (G_F1,)) == 1, "the node stays a ciphertext of its generation")
check(not dbx("SELECT 1 FROM fs_shares WHERE node_id=?", (G_SAFE,)), "no share from the old server")
r = Gi.post(B + "/api/files/lock/upload", data={"parent_id": str(G_SAFE), "name": ct()}, files={"file": ("encrypted.kenc", kenc(), "application/octet-stream")})
check(r.status_code == 201, "gina works in the folder " + r.text[:160])
r = Gi.post(B + f"/api/files/lock/{G_SAFE}/keys", json={"keys": [{"user_id": GINA, "gen": 1, "wrapped": wrapped()}]})
check(r.ok and tuple(dbx("SELECT aad_r, aad_w FROM fs_lock_keys WHERE node_id=? AND user_id=?", (G_SAFE, GINA))[0]) == (None, None),
      "a copy wrapped here has the ids of here")
check(one("SELECT aad_folder FROM fs_locks WHERE node_id=?", (G_SAFE,)) == SAFE, "the folder stays bound to its first id")

# ---------------------------------------------------------------- into a person with other keys
iid, j = preview(Ha, EXP)
enc = (j.get("preview") or {}).get("encrypted") or {}
check(enc.get("keys") == "keep" and enc.get("locked_folders") == 0 and enc.get("locked_folders_lost") == 1 and enc.get("locked_folders_lost_names") == ["Vertraege"],
      f"preview: the folder is named as staying out {enc}")
j = run(Ha, iid)
check(j.get("state") == "done" and "stays out" in warns(j) and "Vertraege" in warns(j), "result: the folder is named " + warns(j))
check(cipher_nodes(HANK) == 0, "no node with a cipher name at hank")
check(one("SELECT COUNT(*) FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id WHERE n.owner_id=? AND n.mime='application/octet-stream'", (HANK,)) == 0, "no ciphertext file at hank")
check("Not taken over because the entry" not in warns(j), "the left-out versions are no second warning " + warns(j))
check(not dbx("SELECT 1 FROM fs_locks l JOIN fs_nodes n ON n.id=l.node_id WHERE n.owner_id=?", (HANK,)), "no lock at hank")

# ---------------------------------------------------------------- an older archive: cipher nodes, no lock rows, no keys
OLD = without(EXP, "data/private_locks.json", "data/private_lock_keys.json", "data/e2e_keys.json")
iid, j = preview(Jo, OLD)
enc = (j.get("preview") or {}).get("encrypted") or {}
check(j.get("state") == "preview" and enc.get("locked_folders_lost") == 1 and enc.get("locked_folders_lost_names") == ["Vertraege"], f"older archive: preview names the folder {j.get('error')} {enc}")
j = run(Jo, iid)
check(j.get("state") == "done" and "stays out" in warns(j), "older archive: the result names it " + warns(j))
check(cipher_nodes(JO) == 0, "older archive: no node with a cipher name")

# ---------------------------------------------------------------- a crafted archive (review of #4300)
def edited(data, edit):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts = {n[5:-5]: json.loads(z.read(n)) for n in z.namelist() if n.startswith("data/") and n.endswith(".json")}
        files = {n: z.read(n) for n in z.namelist() if n not in ("manifest.json", "checksum.sha256")}
        man = json.loads(z.read("manifest.json"))
    edit(parts)
    files.update({f"data/{k}.json": json.dumps(v).encode() for k, v in parts.items()})
    man["files"] = [{"path": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in files.items()]
    mb = json.dumps(man).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
        z.writestr("manifest.json", mb)
        z.writestr("checksum.sha256", "\n".join(f"{hashlib.sha256(b).hexdigest()}  {n}" for n, b in [("manifest.json", mb), *files.items()]) + "\n")
    return out.getvalue()


def craft(p):
    inner = {"id": 990001, "parent_id": SAFE, "kind": "folder", "name": ct(), "e2e_gen": 1, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}
    p["private_files"].append(inner)
    p["private_locks"].append({**p["private_locks"][0], "node_id": 990001, "aad_folder": 990001})
    k = p["private_lock_keys"][0]
    p["private_lock_keys"] += [{**k, "node_id": 990001}, {**k, "gen": 7}]  # a lock below the lock, a generation that does not exist


KK, Kk = freelancer(B, A, "kira")
iid, j = preview(Kk, edited(EXP, craft))
j = run(Kk, iid)
check(j.get("state") == "done", f"crafted archive: imported {j.get('error')}")
K_SAFE = one("SELECT id FROM fs_nodes WHERE owner_id=? AND name='Vertraege' AND deleted_at IS NULL", (KK,))
check(one("SELECT COUNT(*) FROM fs_locks l JOIN fs_nodes n ON n.id=l.node_id WHERE n.owner_id=?", (KK,)) == 1, "crafted archive: one lock per chain, the outer one")
check([r[0] for r in dbx("SELECT gen FROM fs_lock_keys WHERE node_id=?", (K_SAFE,))] == [1], "crafted archive: only the lock's generation")

# ---------------------------------------------------------------- second move, undo
EXP2 = export_of(Gi)
iid, j = preview(Iv, EXP2)
j = run(Iv, iid)
check(j.get("state") == "done", f"import into ivan {j.get('error')}")
I_SAFE = one("SELECT id FROM fs_nodes WHERE owner_id=? AND name='Vertraege' AND deleted_at IS NULL", (IVAN,))
check(one("SELECT aad_folder FROM fs_locks WHERE node_id=?", (I_SAFE,)) == SAFE, "second move: still bound to the first server's folder id")
check(tuple(dbx("SELECT aad_r, aad_w, wrapped_by FROM fs_lock_keys WHERE node_id=?", (I_SAFE,))[0]) == (GINA, GINA, IVAN), "second move: the copy gina wrapped")
r = Iv.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok, "undo " + r.text[:160])
check(not dbx("SELECT 1 FROM fs_locks WHERE node_id=?", (I_SAFE,)) and not dbx("SELECT 1 FROM fs_lock_keys WHERE node_id=?", (I_SAFE,)), "undo: lock and key are gone with the folder")

# ---------------------------------------------------------------- organisation export
r = A.post(B + "/api/users", json={"username": "lena", "display_name": "Lena Lock", "password": "password123", "email": "lena@example.com"})
assert r.ok, r.text
LENA = r.json()["id"]
Le = kt.sess("lena")
for s in (A, Le):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Quelle", "admin_id": ALICE}).json()["id"]
GAM = A.post(B + "/api/admin/orgs", json={"name": "Gamma Ziel", "admin_id": ALICE}).json()["id"]
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "lena@example.com", "role": "member"}).ok, "lena is a member")
check(A.put(B + "/api/e2e/keys", json=keys_body()).ok and Le.put(B + "/api/e2e/keys", json=keys_body()).ok, "alice and lena set up their keys")
O_SAFE = folder(Le, "Personalakten", space=f"org:{ORG}")
O_F, O_N, O_B = lock(Le, O_SAFE, LENA, ALICE)
check(one("SELECT wrapped_by FROM fs_lock_keys WHERE node_id=? AND user_id=?", (O_SAFE, ALICE)) == LENA, "lena wrapped the admin's copy")
NOKEY = folder(Le, "Ohne Schluessel", space=f"org:{ORG}")
lock(Le, NOKEY, LENA, ALICE)
dbx("DELETE FROM fs_lock_keys WHERE node_id=? AND user_id=?", (NOKEY, ALICE))


def org_export(s, oid):
    check(s.post(B + f"/api/orgs/{oid}/export").status_code == 202, "organisation export started")
    st = {}
    for _ in range(480):
        st = s.get(B + f"/api/orgs/{oid}/export").json()
        if st.get("state") != "running":
            break
        time.sleep(0.25)
    check(st.get("state") == "done", f"organisation export done {st}")
    ox = kt.su_get(s, B + f"/api/orgs/{oid}/export/file", "password123").content
    return ox, s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")


OX, RK = org_export(A, ORG)
r = A.post(B + "/api/account/import", json={"size": len(OX), "name": "org.kalmido-export"})
iid = r.json()["id"]
assert A.put(B + f"/api/account/import/{iid}?offset=0", data=OX, headers={"Content-Type": "application/octet-stream"}).ok
j = wait(A, iid)
check(j.get("state") == "key", f"asks for the recovery key {j.get('state')}")
check(A.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": RK}).status_code == 202, "the recovery key is taken")
j = wait(A, iid)
enc = (j.get("preview") or {}).get("encrypted") or {}
check(enc.get("locked_folders") == 1 and enc.get("locked_folders_lost") == 1 and enc.get("locked_folders_lost_names") == ["Ohne Schluessel"], f"org preview: one opens, one is named {enc}")
j = run(A, iid, target=GAM)
check(j.get("state") == "done", f"org import {j.get('state')} {j.get('error')}")
check("Ohne Schluessel" in warns(j), "org result: the folder without a key is named " + warns(j))
T_SAFE = one("SELECT id FROM fs_nodes WHERE org_id=? AND name='Personalakten' AND deleted_at IS NULL", (GAM,))
row = dbx("SELECT e2e, org_id, aad_folder, e2e_by FROM fs_locks WHERE node_id=?", (T_SAFE,))
check(row and tuple(row[0]) == ("on", GAM, O_SAFE, ALICE), f"org: the lock in the target organisation, bound to the old id {row}")
kr = dbx("SELECT user_id, wrapped_by, aad_r, aad_w FROM fs_lock_keys WHERE node_id=?", (T_SAFE,))
check(len(kr) == 1 and tuple(kr[0]) == (ALICE, None, ALICE, LENA), f"org: only the exporter's copy, another person's wrap has no wrapper here {kr}")
info = A.get(B + f"/api/files/lock/{T_SAFE}").json()
check(info["keys"][0].get("wrapped_by") is None and info["keys"][0].get("aad_w") == LENA and info["keys"][0].get("wrapper_pub"), "org: the browser reads the old wrapper's key and id")
kids = A.get(B + "/api/files", params={"parent": T_SAFE}).json().get("items") or []
check(len(kids) == 1 and kids[0]["name"] == O_N, "org: the cipher name came over unchanged")
r = A.get(B + f"/api/files/lock/{T_SAFE}/raw/{kids[0]['id'] if kids else 0}")
check(r.ok and r.content == O_B, "org: the KENC bytes came over unchanged")
check(not dbx("SELECT 1 FROM fs_nodes WHERE org_id=? AND name LIKE 'e2e1:%' AND parent_id NOT IN (SELECT node_id FROM fs_locks)", (GAM,)), "org: no ciphertext outside a lock")
check(not dbx("SELECT 1 FROM fs_lock_keys WHERE node_id=? AND user_id=?", (T_SAFE, LENA)), "org: lena's own copy did not move")

sys.exit(kt.done("p2507_a_lockmove"))
