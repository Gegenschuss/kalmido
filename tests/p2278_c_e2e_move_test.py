"""2.278.0 C (#3091): browser-encrypted content after an account move. Invented names only, ciphertexts of the right shape
(the browser's cryptography itself is not run here: the server only stores and moves it).
 - the account export carries the own key bundle (e2e_keys), never another person's; the manifest says what the import does
 - import into a person without keys (freelancer, no organisation -- P4): the bundle is taken over, legacy_aad keeps the old
   ids (bundle: the old user id; locked note / encrypted file: old task + old user id) and reaches only the owner
 - saving the locked note again seals it anew: legacy_aad goes
 - import into a person with own keys: those stay unchanged, a warning; the encrypted rows come along (unreadable)
 - a project encrypted in the browser is never taken over: preview count + warning
 - a second move keeps the oldest AAD of a file and both old user ids of the bundle"""
import base64
import io
import json
import os
import sys
import time
import zipfile

import kt
from kt import B, check, dbx
from freelancer_fixture import freelancer

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


def blob():
    return {"v": 1, "iv": b64(12), "ct": b64(48)}


def export_of(s, secs=120):
    r = s.post(B + "/api/account/export")
    assert r.status_code == 202, r.text
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + "/api/account/export").json()
        if j.get("state") != "running":
            break
        time.sleep(0.25)
    assert j.get("state") == "done", j
    r = s.get(B + "/api/account/export/file")
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
    r = s.put(B + f"/api/account/import/{iid}?offset=0", data=data, headers={"Content-Type": "application/octet-stream"})
    assert r.ok, r.text
    return iid, wait(s, iid)


def run(s, iid):
    r = s.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}})
    assert r.status_code == 202, r.text
    return wait(s, iid)


def warns(j):
    return " | ".join(w.get("text", "") for w in (j.get("result") or {}).get("warnings") or [])


def zjson(data, name):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return json.loads(z.read(name))


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SECRET_KEY": KEY})
A = kt.setup()
FRIDA, Fr = freelancer(B, A, "frida")   # the person who moves (no organisation: P4)
GINA, Gi = freelancer(B, A, "gina")     # target without keys
HANK, Ha = freelancer(B, A, "hank")     # target with own keys
IVAN, Iv = freelancer(B, A, "ivan")     # second move
BOB, Bo = freelancer(B, A, "bobby")     # somebody else with keys

# ---------------------------------------------------------------- frida's encrypted content
KF = keys_body()
check(Fr.put(B + "/api/e2e/keys", json=KF).ok, "frida sets up her keys")
check(Bo.put(B + "/api/e2e/keys", json=keys_body()).ok, "bobby sets up his keys")
KH = keys_body()
check(Ha.put(B + "/api/e2e/keys", json=KH).ok, "hank sets up his keys")
check(Fr.get(B + "/api/e2e/keys").json().get("legacy_aad") == [], "no old AAD before a move")
L = Fr.post(B + "/api/lists", json={"name": "Frida Umzugsliste", "org_id": None}).json()["id"]
T = Fr.post(B + "/api/tasks", json={"title": "Geheime Notiz", "list_id": L, "content": "klartext"}).json()["id"]
TF = Fr.post(B + "/api/tasks", json={"title": "Geheime Datei", "list_id": L}).json()["id"]
NOTE = blob()
r = Fr.put(B + f"/api/tasks/{T}/note-lock", json={"body": NOTE})
check(r.ok, "frida locks the note " + r.text[:120])
KENC = b"KENC\x01" + os.urandom(12) + os.urandom(64)
r = Fr.post(B + f"/api/tasks/{TF}/enc-attachments", files=[("file", ("encrypted.kenc", KENC, "application/octet-stream"))])
check(r.ok, "frida attaches an encrypted file " + r.text[:120])
LE = Fr.post(B + "/api/lists", json={"name": "Frida Verschluesselt", "org_id": None}).json()["id"]
Fr.post(B + "/api/tasks", json={"title": "e2e1:chiffrat", "list_id": LE})
dbx("UPDATE lists SET e2e=?, e2e_gen=1, name=? WHERE id=?", ("on", "e2e1:listenchiffrat", LE))  # as the lock leaves it

# ---------------------------------------------------------------- export
EXP = export_of(Fr)
ek = zjson(EXP, "data/e2e_keys.json")
check(len(ek) == 1 and ek[0]["user_id"] == FRIDA and json.loads(ek[0]["bundle_pass"])["ct"] == KF["bundle_pass"]["ct"],
      f"the export carries only frida's own bundle {[x.get('user_id') for x in ek]}")
man = zjson(EXP, "manifest.json")
ce = man.get("client_encrypted") or {}
check(ce.get("keys") is True and ce.get("locked_notes") == 1 and len(ce.get("attachments") or []) == 1, f"manifest: keys + counts {ce}")
check("only with your password readable" not in ce.get("note", "") and "not taken over" in ce.get("note", ""), "manifest note is honest")

# ---------------------------------------------------------------- into gina (no keys)
iid, j = preview(Gi, EXP)
p = j.get("preview") or {}
check(j.get("state") == "preview" and p.get("encrypted", {}).get("keys") == "take", f"preview: the keys are taken {p.get('encrypted')}")
check(p.get("encrypted", {}).get("locked_lists") == 1, "preview: one encrypted project")
check(not any(x["name"].startswith("e2e1:") for x in p.get("lists", [])), "preview: no ciphertext project name")
j = run(Gi, iid)
check(j.get("state") == "done", f"import into gina {j.get('state')} {j.get('error')}")
check("encrypted project was not taken over" in warns(j) and "Encryption keys taken over" in warns(j), "warnings: project skipped, keys taken " + warns(j))
check(not dbx("SELECT 1 FROM lists WHERE owner_id=? AND name LIKE 'e2e1:%'", (GINA,)), "the encrypted project is not taken over")
kg = Gi.get(B + "/api/e2e/keys").json()
check(kg.get("set") and kg["pub"]["x"] == KF["pub"]["x"] and kg["bundle_rec"]["ct"] == KF["bundle_rec"]["ct"], "gina has frida's bundle")
check(kg.get("legacy_aad") == [f"kalmido-e2e:v1:{FRIDA}"], f"bundle: the old user id {kg.get('legacy_aad')}")
GT = one("SELECT id FROM tasks WHERE created_by=? AND title='Geheime Notiz'", (GINA,)) \
    or one("SELECT t.id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE l.owner_id=? AND t.title='Geheime Notiz'", (GINA,))
GTF = one("SELECT t.id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE l.owner_id=? AND t.title='Geheime Datei'", (GINA,))
r = Gi.get(B + f"/api/tasks/{GT}/note-lock")
check(r.ok and r.json().get("legacy_aad") == f"kalmido-locknote:v1:{T}:{FRIDA}" and r.json()["body"]["ct"] == NOTE["ct"],
      f"locked note: old AAD for its author {r.text[:200]}")
la = one("SELECT legacy_aad FROM attachments WHERE task_id=? AND enc=1", (GTF,))
check(la == f"kalmido-file:v1:{TF}:{FRIDA}", f"encrypted file: old AAD {la}")
st = Gi.get(B + "/api/state").json()
att = [a for t in st.get("tasks", []) if t.get("id") == GTF for a in t.get("attachments") or []]
check(att and att[0].get("enc_mine") and att[0].get("legacy_aad") == la, f"the file's old AAD reaches its owner {att}")
check(Gi.put(B + f"/api/tasks/{GT}/note-lock", json={"body": blob()}).ok, "gina saves the note (sealed anew)")
check(one("SELECT legacy_aad FROM task_note_locks WHERE task_id=?", (GT,)) is None, "saved: the old AAD is gone")

# ---------------------------------------------------------------- into hank (own keys)
iid, j = preview(Ha, EXP)
check((j.get("preview") or {}).get("encrypted", {}).get("keys") == "keep", "preview: hank keeps his keys")
j = run(Ha, iid)
check(j.get("state") == "done", f"import into hank {j.get('error')}")
check("already have your own encryption keys" in warns(j), "warning: the export's content stays unreadable " + warns(j))
kh = Ha.get(B + "/api/e2e/keys").json()
check(kh["pub"]["x"] == KH["pub"]["x"] and kh["bundle_pass"]["ct"] == KH["bundle_pass"]["ct"] and kh.get("legacy_aad") == [],
      "hank's own keys are unchanged")
check(one("SELECT COUNT(*) FROM task_note_locks WHERE user_id=?", (HANK,)) == 1, "the locked note comes along (unreadable, may be deleted)")

# ---------------------------------------------------------------- second move: gina -> ivan
EXP2 = export_of(Gi)
iid, j = preview(Iv, EXP2)
j = run(Iv, iid)
check(j.get("state") == "done", f"import into ivan {j.get('error')}")
ki = Iv.get(B + "/api/e2e/keys").json()
check(ki.get("legacy_aad") == [f"kalmido-e2e:v1:{GINA}", f"kalmido-e2e:v1:{FRIDA}"], f"bundle: both old user ids {ki.get('legacy_aad')}")
ITF = one("SELECT t.id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE l.owner_id=? AND t.title='Geheime Datei'", (IVAN,))
check(one("SELECT legacy_aad FROM attachments WHERE task_id=? AND enc=1", (ITF,)) == f"kalmido-file:v1:{TF}:{FRIDA}",
      "the file keeps the AAD it was sealed with (first server)")
IT = one("SELECT t.id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE l.owner_id=? AND t.title='Geheime Notiz'", (IVAN,))
check(one("SELECT legacy_aad FROM task_note_locks WHERE task_id=?", (IT,)) == f"kalmido-locknote:v1:{GT}:{GINA}",
      "the note resealed at gina carries gina's AAD")

# ---------------------------------------------------------------- 2.278.0 review M1: undo + the same import again
r = Iv.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok, f"undo of ivan's import {r.text[:200]}")
check(Iv.get(B + "/api/e2e/keys").json().get("set"), "after the undo ivan still has the bundle (his own pair)")
iid, j = preview(Iv, EXP2)
check((j.get("preview") or {}).get("encrypted", {}).get("keys") == "take", f"preview again: the same pair = take {(j.get('preview') or {}).get('encrypted')}")
j = run(Iv, iid)
check(j.get("state") == "done" and "Encryption keys taken over" in warns(j) and "already have your own" not in warns(j),
      "import again: keys taken, no unreadable warning " + warns(j))
ki = Iv.get(B + "/api/e2e/keys").json()
check(ki.get("legacy_aad") == [f"kalmido-e2e:v1:{GINA}", f"kalmido-e2e:v1:{FRIDA}"], f"bundle again: the old ids once each {ki.get('legacy_aad')}")

sys.exit(kt.done("p2278_c_e2e_move"))
