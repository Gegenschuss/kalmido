#!/usr/bin/env python3
"""2.143.0 API tests, part B, own container (start.sh, KALMIDO_BACKUP_TICK=1, KALMIDO_OFFSITE_RETRY_S=1).

#2152 the off-site target of the backups (admin/offsite.py) against fake_offsite.py (an S3 store and a WebDAV server inside
the container, the S3 one checks Signature V4, the signed body hash and Content-MD5 with its own code):
 - instance admins only: another person gets 403 on every route (a setting of the server: freelancer area n/a)
 - credentials are never answered (only key_set / secret_set / password_set; the private SFTP key never, the public one yes),
   not in error texts either
 - the target cannot be switched on without "Encrypt backups" + passphrase, nor incomplete (SFTP: before the host key is known)
 - Test connection writes a probe and deletes it; a wrong secret = "auth" with the target's code
 - after a backup the tick uploads it (same bytes), the newest N stay on the target, a foreign file in the folder stays
 - a failing target is tried again (pause from KALMIDO_OFFSITE_RETRY_S) until it works; the error shows in between
 - an unencrypted backup is never uploaded
 - WebDAV: upload + size check via PROPFIND, wrong password = 401; SFTP: key pair, a closed port fails without secrets
   (no real SFTP server here: the command line and the error path only)
#2211 the trash of knowledge pages (wiki/pages.py):
 - GET /api/wiki/trash lists the space's trashed pages with their files; restore before the period works
 - the watchdog run (wiki_trash_tick, called in the container like p2116_a does for tasks) deletes a page older than the
   period for good: row, file row, scan / text marks, the stored file; inside the period everything stays
 - "Delete permanently" (ids) and "Empty trash" (all) remove pages and files at once; a page not in the trash stays
 - another person / organisation: 404 for the space, ids of others skipped (tenant-matrix: wiki); an organisation's
   member empties the organisation's trash; a person without an organisation (freelancer-matrix: wiki) in the own space
usage: p2143_b_api_test.py <datadir>      (a fresh container; P2143B_NOSTART=1 = the server already runs)"""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import requests

import dbx
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
S3KEY, S3SECRET, DAVPASS = "AKFAKETESTKEY01", "s3-secret-for-the-test-9f2c", "dav-password-for-the-test-7b1e"
PASS = "a long backup passphrase"
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def until(fn, n=60, pause=0.5):
    for _ in range(n):
        x = fn()
        if x:
            return x
        time.sleep(pause)
    return fn()


def no_secret(text, what):
    bad = [x for x in (S3KEY, S3SECRET, DAVPASS, PASS, "PRIVATE KEY") if x in text]
    check(not bad, f"{what}: no credential in the answer ({len(bad)} found)")


if not os.environ.get("P2143B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_BACKUP_TICK=1"
               " -e KALMIDO_OFFSITE_RETRY_S=1 -e KALMIDO_OFFSITE_TIMEOUT=10")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
FEAT = "cal,comments,collab,wiki"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
SP = f"org:{ORG}"
OFF = B + "/api/admin/backups/offsite"

# ============================================================== #2152 off-site target
for mode, port, user, secret in (("s3", 8093, S3KEY, S3SECRET), ("webdav", 8094, "kbk", DAVPASS)):
    shutil.copy(os.path.join(N, "fake_offsite.py"), os.path.join(DATA, "fake_offsite.py"))
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_offsite.py", mode, str(port), user, secret])
time.sleep(1.0)
REM = os.path.join(DATA, "fake-remote")


def remote_log(mode):
    try:
        return [json.loads(x) for x in open(os.path.join(REM, mode + ".log")) if x.strip()]
    except OSError:
        return []


# ---- only instance admins
for m, u in (("GET", OFF), ("PATCH", OFF), ("POST", OFF + "/test"), ("POST", OFF + "/upload")):
    r = Bo.request(m, u, json={"type": "s3"} if m == "PATCH" else None)
    check(r.status_code == 403, f"#2152 {m} {u[len(B):]}: a person who is not an instance admin gets 403 ({r.status_code})")
j = A.get(OFF).json()
check(j.get("type") == "" and j.get("on") is False and j.get("keep") == 14, f"#2152 the start: no target, off, keep = local daily count {j}")

# ---- S3: set up, credentials only as "set"
r = A.patch(OFF, json={"type": "s3", "s3": {"endpoint": "http://127.0.0.1:8093", "region": "eu-central-1", "bucket": "kbk",
                                             "prefix": "/srv1/", "key": S3KEY, "secret": S3SECRET}})
check(r.ok, f"#2152 S3 target saved {r.status_code} {r.text[:200]}")
j = r.json()
check(j["s3"]["key_set"] and j["s3"]["secret_set"] and j["s3"]["prefix"] == "srv1" and j["s3"]["path_style"] is True,
      f"#2152 S3: key + secret set, the folder cleaned, path style by default {j['s3']}")
no_secret(r.text, "#2152 PATCH S3")
no_secret(A.get(OFF).text, "#2152 GET after S3")
check(A.patch(OFF, json={"s3": {"endpoint": "ftp://example.com"}}).status_code == 400, "#2152 an endpoint must be http(s)")
check(A.patch(OFF, json={"s3": {"endpoint": "https://user:pw@example.com"}}).status_code == 400, "#2152 no credentials in the address")
check(A.patch(OFF, json={"s3": {"prefix": "a/../b"}}).status_code == 400, "#2152 no .. in the folder")
check(A.patch(OFF, json={"keep": 0}).status_code == 400, "#2152 keep at least 1")
db_raw = json.dumps([list(x) for x in dbx.connect(DATA).execute("SELECT key, value FROM settings WHERE key LIKE 'bko_%'").fetchall()])
check(S3SECRET not in db_raw and S3KEY not in db_raw, "#2152 the credentials are sealed in the settings table (not plain)")

# ---- not without encryption
r = A.patch(OFF, json={"on": True})
check(r.status_code == 400 and "encrypt" in r.text.lower(), f"#2152 on without encrypted backups: refused {r.status_code} {r.text[:160]}")
check(A.get(OFF).json()["encrypt_ready"] is False, "#2152 encrypt_ready false")
assert A.patch(B + "/api/admin/backups", json={"encrypt": True, "passphrase": PASS}).ok
check(A.get(OFF).json()["encrypt_ready"] is True, "#2152 encrypt_ready after the passphrase")

# ---- test connection (probe written + deleted, signature checked by the fake)
r = A.post(OFF + "/test")
j = r.json()
check(r.ok and j.get("ok") is True, f"#2152 S3 test works {r.status_code} {r.text[:300]}")
lg = remote_log("s3")
check(any(x["method"] == "PUT" and "kalmido-probe-" in x["path"] and x["status"] == 200 and x["sig"] for x in lg)
      and any(x["method"] == "DELETE" and "kalmido-probe-" in x["path"] for x in lg), f"#2152 S3 probe written with a valid signature and deleted {lg[-4:]}")
check(not glob.glob(os.path.join(REM, "s3", "kbk", "srv1", "kalmido-probe-*")), "#2152 no probe file left on the target")
# a wrong secret: auth with the target's code, never the secret
A.patch(OFF, json={"s3": {"secret": "a-wrong-secret-value"}})
j = A.post(OFF + "/test").json()
check(j.get("ok") is False and j.get("code") == "auth" and "SignatureDoesNotMatch" in j.get("error", ""), f"#2152 wrong secret = auth error {j.get('error')}")
check("a-wrong-secret-value" not in json.dumps(j), "#2152 the wrong secret is not in the answer")
A.patch(OFF, json={"s3": {"secret": S3SECRET}})
check(A.post(OFF + "/test").json().get("ok") is True, "#2152 the right secret again")

# ---- switch on, back up, the tick uploads
r = A.patch(OFF, json={"on": True, "keep": 2})
check(r.ok and r.json()["on"] is True and r.json()["keep"] == 2, f"#2152 on with keep 2 {r.text[:200]}")


def backup_now():
    before = {x["name"] for x in A.get(B + "/api/admin/backups").json()["items"]}
    time.sleep(1.1)  # names carry the second
    assert A.post(B + "/api/admin/backups").status_code == 202
    new = until(lambda: [x for x in A.get(B + "/api/admin/backups").json()["items"] if x["name"] not in before
                         and not A.get(B + "/api/admin/backups").json()["running"]])
    return new[0]["name"] if new else ""


def s3_file(name):
    return os.path.join(REM, "s3", "kbk", "srv1", name)


os.makedirs(os.path.join(REM, "s3", "kbk", "srv1"), exist_ok=True)
open(s3_file("notes-of-the-admin.txt"), "w").write("not a backup")
names = []
for i in range(3):
    n = backup_now()
    names.append(n)
    ok = until(lambda: A.get(OFF).json().get("last_name") == n, 40)
    check(ok, f"#2152 backup {i + 1} ({n}) uploaded by the tick: {A.get(OFF).json()}")
first = names[0]
check(names[0].endswith(".zip.enc"), f"#2152 the backups are encrypted {names}")
loc = os.path.join(DATA, "backups", names[-1])
if os.path.isfile(loc) and os.path.isfile(s3_file(names[-1])):
    check(hashlib.sha256(open(loc, "rb").read()).hexdigest() == hashlib.sha256(open(s3_file(names[-1]), "rb").read()).hexdigest(),
          "#2152 the uploaded file has the same bytes as the local backup")
else:
    check(False, f"#2152 local and uploaded file exist {os.path.isfile(loc)} {os.path.isfile(s3_file(names[-1]))}")
on_target = sorted(os.path.basename(p) for p in glob.glob(s3_file("kalmido-backup-*")))
check(on_target == sorted(names[1:]), f"#2152 keep 2: the two newest stay, the oldest went {on_target} vs {names}")
check(os.path.isfile(s3_file("notes-of-the-admin.txt")), "#2152 a file of another name in the folder stays")
j = A.get(OFF).json()
check(j["last_size"] == os.path.getsize(loc) and j["last_ok"] and not j["last_error"], f"#2152 the state: last upload, size, no error {j}")

# ---- a failing target: tried again until it works
open(os.path.join(REM, "s3.fail"), "w").write("2")
n = backup_now()
seen_err = until(lambda: A.get(OFF).json().get("last_error"), 30, 0.2)
check(seen_err and "500" in seen_err, f"#2152 the failed upload shows its error {seen_err!r}")
no_secret(json.dumps(A.get(OFF).json()), "#2152 GET with an error")
check(until(lambda: A.get(OFF).json().get("last_name") == n, 60), f"#2152 the next tries upload it {A.get(OFF).json()}")
check(not A.get(OFF).json()["last_error"], "#2152 the error is cleared after the upload")

# ---- an unencrypted backup is never uploaded
assert A.patch(B + "/api/admin/backups", json={"encrypt": False}).ok
n = backup_now()
check(n.endswith(".zip") and not n.endswith(".enc"), f"#2152 a plain backup {n}")
err_txt = until(lambda: A.get(OFF).json().get("last_error"), 30, 0.3)
check(err_txt and "encrypted" in err_txt.lower(), f"#2152 the plain backup is refused with the reason {err_txt!r}")
check(not os.path.exists(s3_file(n)), "#2152 the plain backup is not on the target")
assert A.patch(B + "/api/admin/backups", json={"encrypt": True}).ok

# ---- WebDAV
r = A.patch(OFF, json={"type": "webdav", "webdav": {"url": "http://127.0.0.1:8094/dav/bk", "user": "kbk", "password": DAVPASS}})
check(r.ok and r.json()["webdav"]["password_set"] and r.json()["webdav"]["user"] == "kbk", f"#2152 WebDAV saved {r.text[:200]}")
no_secret(r.text, "#2152 PATCH WebDAV")
os.makedirs(os.path.join(REM, "webdav", "dav", "bk"), exist_ok=True)
j = A.post(OFF + "/test").json()
check(j.get("ok") is True, f"#2152 WebDAV test works {j.get('error')}")
newest = backup_now()  # encrypted again: the tick uploads it to the new target
dav_file = os.path.join(REM, "webdav", "dav", "bk", newest)
check(until(lambda: os.path.isfile(dav_file) and A.get(OFF).json().get("last_name") == newest, 40),
      f"#2152 WebDAV: the new backup uploaded {A.get(OFF).json()}")
check(os.path.isfile(dav_file) and os.path.getsize(dav_file) == os.path.getsize(os.path.join(DATA, "backups", newest)), "#2152 WebDAV: same size")
os.remove(dav_file)
r = A.post(OFF + "/upload")
check(r.status_code == 202, f"#2152 upload now 202 {r.status_code}")
check(until(lambda: os.path.isfile(dav_file) and not A.get(OFF).json()["running"], 40), "#2152 upload now sends the newest backup again")
check(any(x["method"] == "PROPFIND" for x in remote_log("webdav")), "#2152 WebDAV: the size is checked with PROPFIND")
A.patch(OFF, json={"webdav": {"password": "wrong-dav-password"}})
j = A.post(OFF + "/test").json()
check(j.get("ok") is False and j.get("code") == "auth" and "401" in j.get("error", ""), f"#2152 WebDAV wrong password = 401 {j}")
check("wrong-dav-password" not in json.dumps(j), "#2152 the wrong password is not in the answer")

# ---- SFTP: key pair, fingerprint required before switching on, a closed port fails cleanly
r = A.patch(OFF, json={"type": "sftp", "on": False, "sftp": {"host": "127.0.0.1", "port": 1, "user": "backup", "path": "bk"}})
j = r.json()
pub = j["sftp"]["public_key"]
check(r.ok and pub.startswith("ssh-ed25519 ") and j["sftp"]["fingerprint"] == "", f"#2152 SFTP: a public key, no fingerprint yet {r.text[:200]}")
no_secret(r.text, "#2152 PATCH SFTP")
check("hostkey" in j["missing"], f"#2152 SFTP: the host key is still missing {j['missing']}")
r = A.patch(OFF, json={"on": True})
check(r.status_code == 400, f"#2152 SFTP cannot be switched on before a test recorded the host key {r.status_code}")
j = A.post(OFF + "/test").json()
check(j.get("ok") is False and j.get("code") in ("conn", "tool", "sftp"), f"#2152 SFTP to a closed port fails with a reason {j.get('code')} {j.get('error')}")
no_secret(json.dumps(j), "#2152 SFTP test answer")
check("kalmido-sftp-" not in json.dumps(j), "#2152 SFTP: no temp path in the error")
r = A.patch(OFF, json={"sftp": {"new_key": True}})
check(r.ok and r.json()["sftp"]["public_key"].startswith("ssh-ed25519 ") and r.json()["sftp"]["public_key"] != pub, "#2152 SFTP: a new key pair")
check(A.patch(OFF, json={"sftp": {"host": "-oProxyCommand=x"}}).status_code == 400, "#2152 SFTP: a host cannot be an option")
check(A.patch(OFF, json={"sftp": {"path": 'a"b'}}).status_code == 400, "#2152 SFTP: no quote in the folder")
check(A.patch(OFF, json={"sftp": {"port": 70000}}).status_code == 400, "#2152 SFTP: port range")
A.patch(OFF, json={"type": ""})

# ============================================================== #2211 trash of knowledge pages
Fid, Fr = freelancer(B, A, features=FEAT)
dbc = dbx.connect(DATA)


def page(s, space, path):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": "Text of " + path})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def with_file(s, pid):
    r = s.post(B + f"/api/wiki/pages/{pid}/files", files={"file": ("plan.pdf", PDF, "application/pdf")})
    assert r.status_code == 201, r.text
    f = r.json()["files"][0]
    return f["id"], dbc.execute("SELECT path FROM wiki_files WHERE id=?", (f["id"],)).fetchone()[0]


def stored(rel):
    return os.path.isfile(os.path.join(DATA, "attachments", rel))


def gone(pid):
    return not dbc.execute("SELECT 1 FROM wiki_pages WHERE id=?", (pid,)).fetchall()


def trash_ids(s, space):
    r = s.get(B + "/api/wiki/trash", params={"space": space})
    return [p["id"] for p in r.json().get("pages", [])] if r.ok else None


def tick():
    code = ("import json, app\nfrom kalmido.wiki.pages import wiki_trash_tick\nc = app.connect()\n"
            "try:\n    print(json.dumps(wiki_trash_tick(c, force=True)))\nfinally:\n    c.close()")
    out = subprocess.run(["docker", "exec", CT, "python", "-c", code], capture_output=True, text=True)
    check(out.returncode == 0, f"#2211 the run works {out.stdout[-200:]} {out.stderr[-600:]}")
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


# ---- the period: old pages go for good with their files, young ones stay
old = page(A, "private", "Old/Plan")
old_f, old_path = with_file(A, old)
dbc.execute("INSERT INTO file_text(kind, ref_id, ws, text, created_at, updated_at) SELECT 'wiki', ?, 'test', 'plan text', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z' WHERE NOT EXISTS "
            "(SELECT 1 FROM file_text WHERE kind='wiki' AND ref_id=?)", (old_f, old_f))  # a text mark to be removed with it
young = page(A, "private", "Young/Plan")
young_f, young_path = with_file(A, young)
check(stored(old_path) and stored(young_path), "#2211 setup: the stored files exist")
for p in (old, young):
    check(A.delete(B + f"/api/wiki/pages/{p}").ok, "#2211 to the trash")
tl = A.get(B + "/api/wiki/trash", params={"space": "private"}).json()
row = next((p for p in tl.get("pages", []) if p["id"] == old), {})
check(row.get("files") == 1 and row.get("size") > 0 and tl.get("days") == 30 and row.get("path") == "Old/Plan",
      f"#2211 the trash lists the page with its file and the period {tl}")
n = tick()
check(n.get("pages") == 0 and not gone(old) and stored(old_path), f"#2211 inside the period nothing goes {n}")
dbc.execute("UPDATE wiki_pages SET deleted_at='2000-01-01T00:00:00.000Z' WHERE id=?", (old,))
n = tick()
check(n.get("pages") == 1 and n.get("files") == 1, f"#2211 the run counts one page + one file {n}")
check(gone(old) and not dbc.execute("SELECT 1 FROM wiki_files WHERE id=?", (old_f,)).fetchall(), "#2211 page and file row gone")
check(not dbc.execute("SELECT 1 FROM file_text WHERE kind='wiki' AND ref_id=?", (old_f,)).fetchall()
      and not dbc.execute("SELECT 1 FROM upload_scan WHERE kind='wiki' AND ref_id=?", (old_f,)).fetchall(), "#2211 text / scan marks gone")
check(not stored(old_path), "#2211 the stored file is deleted")
check(not gone(young) and stored(young_path), "#2211 the young page in the trash stays with its file")
# restore before the end of the period
r = A.post(B + "/api/wiki/restore", json={"ids": [young]})
check(r.ok and r.json()["ids"] == [young] and young not in (trash_ids(A, "private") or []), "#2211 restore before the end works")
dbc.execute("UPDATE wiki_pages SET deleted_at=NULL WHERE id=?", (young,))
tick()
check(not gone(young) and stored(young_path), "#2211 a restored page is never purged")

# ---- delete permanently (one) and empty trash (all); a page not in the trash stays
a1, a2, a3 = page(A, "private", "Trash/One"), page(A, "private", "Trash/Two"), page(A, "private", "Keep/Me")
_, a1_path = with_file(A, a1)
BOB = Bo.get(B + "/api/state").json()["me"]["id"]
sh = A.post(B + "/api/wiki/shares", json={"page_id": a2, "kind": "person", "user_id": BOB})
check(sh.ok, f"#2211 setup: a share of the page {sh.status_code} {sh.text[:200]}")
SHARE = (sh.json().get("share") or sh.json()).get("id") if sh.ok else 0
A.post(B + "/api/wiki/trash", json={"ids": [a1, a2]})
r = A.post(B + "/api/wiki/purge", json={"space": "private", "ids": [a1, a3]})
check(r.ok and r.json()["ids"] == [a1] and r.json()["skipped"] == [a3], f"#2211 delete permanently: the trashed page, not the live one {r.text}")
check(gone(a1) and not stored(a1_path) and not gone(a3), "#2211 its file is deleted at once, the live page stays")
r = A.post(B + "/api/wiki/purge", json={"space": "private", "all": True})
check(r.ok and r.json()["ids"] == [a2] and gone(a2) and trash_ids(A, "private") == [], f"#2211 empty trash {r.text}")
check(A.post(B + "/api/wiki/purge", json={"space": "private", "ids": "x"}).status_code == 400, "#2211 ids must be a list")
check(bool(SHARE) and dbc.execute("SELECT revoked_at FROM wiki_shares WHERE id=?", (SHARE,)).fetchone()[0],
      "#2211 the share of the purged page ended (a later page of that name is not shared by it)")

# ---- other people / organisations (tenant-matrix: wiki)
o1 = page(A, SP, "Org/Old")
_, o1_path = with_file(A, o1)
A.delete(B + f"/api/wiki/pages/{o1}")
c_p = page(Ca, "private", "Carol/Own")
Ca.delete(B + f"/api/wiki/pages/{c_p}")
check(Ca.get(B + "/api/wiki/trash", params={"space": SP}).status_code == 404, "#2211 a non-member: the organisation's trash 404")
check(Ca.post(B + "/api/wiki/purge", json={"space": SP, "all": True}).status_code == 404, "#2211 a non-member cannot empty it")
r = Ca.post(B + "/api/wiki/purge", json={"space": "private", "ids": [o1]})
check(r.ok and r.json()["ids"] == [] and not gone(o1), f"#2211 an id of another space is skipped {r.text}")
check(o1 not in (trash_ids(Ca, "private") or []) and c_p not in (trash_ids(A, "private") or []), "#2211 the private trash shows only the own pages")
check(trash_ids(Bo, SP) == [o1], "#2211 a member sees the organisation's trash")
r = Bo.post(B + "/api/wiki/purge", json={"space": SP, "ids": [o1]})
check(r.ok and r.json()["ids"] == [o1] and gone(o1) and not stored(o1_path), f"#2211 a member deletes an organisation page for good {r.text}")
check(not gone(c_p), "#2211 Carol's page untouched")

# ---- a person without an organisation (freelancer-matrix: wiki)
f1 = page(Fr, "private", "Frida/Notes")
_, f1_path = with_file(Fr, f1)
Fr.delete(B + f"/api/wiki/pages/{f1}")
check(trash_ids(Fr, "private") == [f1], "#2211 freelancer: the own trash")
r = Fr.post(B + "/api/wiki/purge", json={"space": "private", "all": True})
check(r.ok and r.json()["ids"] == [f1] and gone(f1) and not stored(f1_path), f"#2211 freelancer: empty trash {r.text}")
check(Fr.get(B + "/api/wiki/trash", params={"space": SP}).status_code == 404, "#2211 freelancer: no organisation trash")

print(f"p2143_b api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
