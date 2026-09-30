#!/usr/bin/env python3
"""Backups + restore (package A): admin-only API + CSRF, settings validation, "Back up now" (zip layout, manifest
checksums, file mode), download (auth, streamed bytes), the daily schedule (runs once per day), retention (daily +
weekly + safety), the "older than 2 days" and "backup failed" admin alerts, encryption (own format: scrypt + AES-GCM
chunks, decrypted here independently; wrong passphrase refused), restore of a listed backup and of an uploaded file
(data, attachments, safety backup, backup settings kept, every other session ended, the admin gets a fresh one,
migrations / schema version), and refused archives: not a zip, no manifest, path traversal / absolute / symlink
members, checksum mismatch, zip bomb, too large, newer schema (manifest and database), foreign trigger, damaged
database -- each without changing anything. Finally KALMIDO_BACKUPS=0.
Starts its OWN test containers (start.sh, KALMIDO_ADMIN_ALERTS=1, KALMIDO_BACKUP_TICK=1, KALMIDO_BACKUP_MAX_MB=5).
usage: backup_test.py <datadir>"""
import base64
import hashlib
import io
import json
import os
import sqlite3
import stat
import struct
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
BK = os.path.join(DATA, "backups")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
BP = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PROXY_PORT", "3041")
H = {"X-Requested-With": "kalmido"}
TZ = ZoneInfo("Europe/Berlin")
FAILS, OKS = [], [0]
MAGIC = b"KALMIDO-BACKUP-ENC\x00"


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


def start(extra=(), backups="1"):
    env = dict(os.environ, KALMIDO_ADMIN_ALERTS="1",
               EXTRA=" ".join(["-e KALMIDO_BACKUP_TICK=1", "-e KALMIDO_BACKUP_MAX_MB=5", "-e KALMIDO_ADMIN_ALERT_WINDOW=3",
                               f"-e KALMIDO_BACKUPS={backups}", *extra]))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def state(s=None):
    return (s or A).get(B + "/api/admin/backups").json()


def wait_idle(n_before=None, t=30):
    t0 = time.time()
    while time.time() - t0 < t:
        j = state()
        if not j["running"] and (n_before is None or len(j["items"]) > n_before or j["last_error"]):
            return j
        time.sleep(0.3)
    return state()


def backup_now():
    n = len(state()["items"])
    r = A.post(B + "/api/admin/backups")
    assert r.status_code == 202, r.text
    return wait_idle(n)


def alerts(key_prefix):
    return [r for r in dbx("SELECT key, message FROM admin_alerts") if r[0].startswith(key_prefix)]


def wait_alert(key_prefix, t=8):
    t0 = time.time()
    while time.time() - t0 < t:
        a = alerts(key_prefix)
        if a:
            return a
        time.sleep(0.3)
    return []


def titles(s):
    return sorted(t["title"] for t in s.get(B + "/api/state").json()["tasks"])


def make_zip(members, manifest=None, fix=True, schema=None):
    """A zip with members {name: bytes}; manifest built from them (fix=True) unless given."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        files = []
        for n, data in members.items():
            if isinstance(data, zipfile.ZipInfo):
                continue
            z.writestr(n, data)
            files.append([n, len(data), hashlib.sha256(data).hexdigest()])
        for n, data in members.items():
            if isinstance(data, zipfile.ZipInfo):
                z.writestr(data, b"target")
        if manifest is None and fix:
            manifest = {"format": "kalmido-backup", "format_version": 1, "app_version": "9.9.9", "schema_version": schema or 2,
                        "created_at": "2026-01-01T00:00:00+00:00", "kind": "manual", "counts": {}, "files": files}
        if manifest is not None:
            z.writestr("manifest.json", json.dumps(manifest))
    return buf.getvalue()


def upload(data, s=None):
    return (s or A).post(B + "/api/admin/backups/upload", data=data, headers={"Content-Type": "application/octet-stream"})


def restore(s=None, base=None, **b):
    return (s or A).post((base or B) + "/api/admin/backups/restore", json={"confirm": "RESTORE", **b})


def decrypt(path, pw):
    """Independent implementation of the documented format (README: backups)."""
    with open(path, "rb") as f:
        assert f.read(len(MAGIC)) == MAGIC
        n = struct.unpack(">I", f.read(4))[0]
        raw = f.read(n)
        h = json.loads(raw)
        key = Scrypt(salt=base64.urlsafe_b64decode(h["salt"] + "=" * (-len(h["salt"]) % 4)), length=32, n=h["n"], r=h["r"], p=h["p"]).derive(pw.encode())
        aes, hh, out, i = AESGCM(key), hashlib.sha256(MAGIC + raw).digest(), b"", 0
        while True:
            ln = struct.unpack(">I", f.read(4))[0]
            ct = f.read(ln)
            rest = f.peek(1) if hasattr(f, "peek") else b""
            last = 1 if not rest else 0
            out += aes.decrypt(struct.pack(">IQ", 0, i), ct, hh + struct.pack(">QB", i, last))
            if last:
                return h, out
            i += 1


# ------------------------------------------------------------------ container 1
start()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
assert A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).ok
assert A.post(B + "/api/users", json={"username": "px", "display_name": "Proxy admin", "proxy_login": "px-sso", "is_admin": True}).ok
Bo = sess("bob")
PX = requests.Session()
PX.headers.update({**H, "Remote-User": "px-sso"})
L = A.post(B + "/api/lists", json={"name": "Home"}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"title": "kept task", "list_id": L}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "deleted after backup", "list_id": L}).json()["id"]
r = A.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("note.txt", b"attachment one\n" * 20, "text/plain")})
assert r.ok, r.text
ATT1 = r.json()["attachments"][0]
r = A.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("pic.png", b"\x89PNG\r\n" + os.urandom(90000), "image/png")})
assert r.ok, r.text

# ---- access control
check(requests.get(B + "/api/admin/backups").status_code == 401, "not logged in -> 401")
check(Bo.get(B + "/api/admin/backups").status_code == 403, "user: GET -> 403")
check(Bo.post(B + "/api/admin/backups").status_code == 403, "user: back up now -> 403")
check(Bo.patch(B + "/api/admin/backups", json={"on": True}).status_code == 403, "user: settings -> 403")
check(Bo.post(B + "/api/admin/backups/restore", json={"name": "x", "confirm": "RESTORE"}).status_code == 403, "user: restore -> 403")
check(upload(b"PK", Bo).status_code == 403, "user: upload -> 403")
check(requests.post(B + "/api/admin/backups", cookies=A.cookies).status_code == 403, "back up now without the CSRF header -> 403")
check(requests.post(B + "/api/admin/backups/restore", json={"name": "x", "confirm": "RESTORE"}, cookies=A.cookies).status_code == 403,
      "restore without the CSRF header -> 403")

# ---- defaults + validation
j = state()
check(j["env"] and not j["on"] and j["time"] == "03:30" and j["keep_daily"] == 14 and j["keep_weekly"] == 8 and not j["encrypt"]
      and j["items"] == [] and j["confirm_word"] == "RESTORE", f"defaults: off, 03:30, 14 + 8, unencrypted: {j}")
for bad in ({"on": "yes"}, {"time": "25:00"}, {"keep_daily": 0}, {"keep_daily": 400}, {"keep_weekly": -1}, {"keep_daily": True},
            {"encrypt": True}, {"passphrase": "short"}, {"encrypt": "1"}):
    check(A.patch(B + "/api/admin/backups", json=bad).status_code == 400, f"invalid setting rejected: {bad}")
check(not state()["encrypt"] and state()["time"] == "03:30", "nothing stored after invalid input")

# ---- back up now: layout, manifest, checksums, file mode
j = backup_now()
check(len(j["items"]) == 1 and j["items"][0]["kind"] == "manual" and not j["items"][0]["encrypted"] and j["last_ok"] and not j["last_error"],
      f"manual backup listed: {j['items']}")
name = j["items"][0]["name"]
p = os.path.join(BK, name)
check(os.path.isfile(p) and stat.S_IMODE(os.stat(p).st_mode) == 0o600, "archive exists, mode 0600")
with zipfile.ZipFile(p) as z:
    names = z.namelist()
    man = json.loads(z.read("manifest.json"))
    okhash = all(hashlib.sha256(z.read(f[0])).hexdigest() == f[2] and len(z.read(f[0])) == f[1] for f in man["files"])
check("tasks.db" in names and "manifest.json" in names and sum(n.startswith("attachments/") for n in names) == 2,
      f"zip: tasks.db, manifest, 2 attachments: {names}")
check(man["format"] == "kalmido-backup" and man["schema_version"] == 2 and man["counts"]["tasks"] == 2 and man["attachment_files"] == 2,
      f"manifest: {dict((k, man[k]) for k in ('format', 'schema_version', 'counts', 'attachment_files'))}")
check(okhash, "every member matches its SHA-256 and size")
it = j["items"][0]
check(it["counts"]["tasks"] == 2 and it["attachment_files"] == 2 and it["counts"]["users"] == 3, f"list shows the contents: {it}")
r = A.post(B + f"/api/admin/backups/{name}/verify", json={})
check(r.ok and r.json()["ok"] and r.json()["counts"]["tasks"] == 2, f"verify: {r.text[:200]}")

# ---- download: admins only, the exact bytes
r = A.get(B + f"/api/admin/backups/{name}/download")
check(r.ok and r.content == open(p, "rb").read() and "attachment" in r.headers.get("Content-Disposition", "")
      and r.headers.get("Cache-Control") == "no-store", "download: exact bytes, attachment, no-store")
check(Bo.get(B + f"/api/admin/backups/{name}/download").status_code == 403, "download as user -> 403")
check(requests.get(B + f"/api/admin/backups/{name}/download").status_code in (401, 303), "download without login refused")
for bad in ("../tasks.db", "..%2Ftasks.db", "kalmido-backup-x.zip", "tasks.db", "%2e%2e%2ftasks.db"):
    rr = A.get(B + f"/api/admin/backups/{bad}/download")
    check(rr.status_code == 404 and b"SQLite" not in rr.content, f"download of {bad!r} refused")

# ---- stale alert (no backup for 2 days) + schedule
old = (datetime.now(TZ) - timedelta(days=3)).astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")
dbx("UPDATE settings SET value=? WHERE key='bk_last_ok'", (old,))
r = A.patch(B + "/api/admin/backups", json={"on": True, "time": "00:00"})
check(r.ok and r.json()["on"], "switched on")
check(bool(wait_alert("backup:stale")), "alert: last successful backup older than 2 days")
check(bool(wait_alert("switch:bk_on:1")), "switching backups on is a security alert")
today = datetime.now(TZ).date().isoformat()
check(dbx("SELECT value FROM settings WHERE key='bk_last_day'")[0][0] == today, "time already passed today: first automatic backup tomorrow")
n0 = len(state()["items"])
dbx("UPDATE settings SET value='' WHERE key='bk_last_day'")  # as if the day had just begun
j = wait_idle(n0, 20)
autos = [x for x in j["items"] if x["kind"] == "auto"]
check(len(autos) == 1 and dbx("SELECT value FROM settings WHERE key='bk_last_day'")[0][0] == today, f"scheduled backup ran once: {autos}")
time.sleep(3)
check(len([x for x in state()["items"] if x["kind"] == "auto"]) == 1, "not twice on the same day")

# ---- failure alert: the backup folder is read-only
os.chmod(BK, 0o500)
try:
    j = backup_now()
finally:
    os.chmod(BK, 0o700)
check(j["last_error"] and "could not be written" in j["last_error"], f"failure recorded: {j['last_error']}")
check(bool(wait_alert("backup:io")), "alert: backup failed")
j = backup_now()
check(not j["last_error"], "the next backup clears the error")

# ---- retention: 14 daily + 8 weekly -> here 5 daily + 3 weekly, safety: the last 3
src = open(os.path.join(BK, state()["items"][0]["name"]), "rb").read()
now = datetime.now(TZ)
fake = []
for d in range(1, 60):
    for hh in ((3, 30), (15, 0)) if d % 7 == 0 else ((3, 30),):
        t = (now - timedelta(days=d)).replace(hour=hh[0], minute=hh[1], second=0)
        fake.append(f"kalmido-backup-{t.strftime('%Y%m%d-%H%M%S')}-auto.zip")
for d in range(1, 6):
    t = (now - timedelta(days=d)).replace(hour=12, minute=0, second=0)
    fake.append(f"kalmido-backup-{t.strftime('%Y%m%d-%H%M%S')}-safety.zip")
for n in fake:
    with open(os.path.join(BK, n), "wb") as f:
        f.write(src)
open(os.path.join(BK, "notes.txt"), "w").write("not a backup")
check(A.patch(B + "/api/admin/backups", json={"keep_daily": 5, "keep_weekly": 3}).ok, "retention saved")
before = {x["name"] for x in state()["items"]} | set(fake)
j = backup_now()
left = {x["name"] for x in j["items"]}
allnames = before | left


def expected(names, daily, weekly):
    at = {n: datetime.strptime(n[15:30], "%Y%m%d-%H%M%S") for n in names}
    normal = sorted((n for n in names if not n.endswith("-safety.zip")), key=lambda n: (at[n], n), reverse=True)
    keep, days, weeks = set(), [], []
    for n in normal:
        d, w = at[n].date(), tuple(at[n].isocalendar())[:2]
        if d not in days:
            days.append(d)
            if len(days) <= daily:
                keep.add(n)
        if w not in weeks:
            weeks.append(w)
            if len(weeks) <= weekly:
                keep.add(n)
    keep |= set(sorted((n for n in names if n.endswith("-safety.zip")), key=lambda n: at[n], reverse=True)[:3])
    keep |= {n for n in normal if datetime.now(TZ).replace(tzinfo=None) - at[n] < timedelta(hours=24)}
    return keep


exp = expected(allnames, 5, 3)
check(left == exp, f"retention: kept everything of the last 24 h + newest per day (5 days) + per week (3 weeks) + 3 safety: extra {sorted(left - exp)} missing {sorted(exp - left)}")
check(len([n for n in left if n.endswith("-safety.zip")]) == 3 and len([n for n in left if n in fake and "-auto" in n]) <= 8,
      f"older ones thinned out, 3 safety backups: {sorted(left)}")
check(os.path.exists(os.path.join(BK, "notes.txt")), "unrelated files are never deleted")
os.remove(os.path.join(BK, "notes.txt"))
A.patch(B + "/api/admin/backups", json={"keep_daily": 14, "keep_weekly": 8})

# ---- restore a listed backup
j = backup_now()
good = j["items"][0]["name"]
check(j["items"][0]["kind"] == "manual", "fresh backup before the changes")
A.delete(B + f"/api/tasks/{T2}")
A.post(B + "/api/tasks", json={"title": "created after backup", "list_id": L})
A.post(B + f"/api/tasks/{T1}/attachments", files={"file": ("late.txt", b"late file", "text/plain")})
A.patch(B + "/api/admin/backups", json={"keep_daily": 9})  # a backup setting changed after the backup: must survive
before = titles(A)
check("created after backup" in before and "deleted after backup" not in before, "changed state before the restore")
check(restore(name=good, confirm="restore").status_code == 400, "wrong confirmation word -> 400")
r = A.post(B + "/api/admin/backups/restore", json={"name": good})
check(r.status_code == 400, "no confirmation word -> 400")
check(restore(name="../tasks.db").status_code == 404, "restore of a path -> 404")
PX.get(BP + "/api/me")
old_cookie = A.cookies.get("kalmido_session")
bob_cookie = Bo.cookies.get("kalmido_session")
r = restore(name=good)
check(r.ok and r.json()["ok"] and r.json()["safety"].endswith("-safety.zip") and not r.json()["relogin"], f"restored: {r.text[:200]}")
new_cookie = r.cookies.get("kalmido_session")
check(bool(new_cookie) and new_cookie != old_cookie, "the restoring admin gets a fresh session cookie")
check(requests.get(B + "/api/me", cookies={"kalmido_session": old_cookie}).status_code == 401, "the old session of the admin ended")
check(Bo.get(B + "/api/state").status_code == 401 and requests.get(B + "/api/me", cookies={"kalmido_session": bob_cookie}).status_code == 401,
      "every other session ended")
check(PX.get(BP + "/api/me").json().get("username") == "px", "proxy login keeps working after the restore")
after = titles(A)
check("deleted after backup" in after and "created after backup" not in after and "kept task" in after, f"data is the backup's: {after}")
att = A.get(B + f"/api/tasks/{T1}").json()["attachments"]
check(sorted(a["name"] for a in att) == ["note.txt", "pic.png"], f"attachments of the backup: {[a['name'] for a in att]}")
check(A.get(B + f"/api/attachments/{ATT1['id']}").content == b"attachment one\n" * 20, "attachment file content restored")
check(not any(n.startswith("attachments.") for n in os.listdir(DATA)), f"no leftover attachment folders: {os.listdir(DATA)}")
check(state()["keep_daily"] == 9, "backup settings are kept across a restore")
check(dbx("PRAGMA user_version")[0][0] == 2 and "totp_secret" in [r[1] for r in dbx("PRAGMA table_info(users)")], "schema version + migrations")
check(any(x["kind"] == "safety" and x["name"] == r.json()["safety"] for x in state()["items"]), "safety backup listed")
check(bool(wait_alert("restore:")), "restore is a security alert")
Bo = sess("bob")
check(Bo.get(B + "/api/state").ok, "bob can log in again")
# the safety backup brings the pre-restore state back
r = restore(name=r.json()["safety"])
A.cookies.set("kalmido_session", r.cookies.get("kalmido_session"))
check(r.ok and "created after backup" in titles(A), "restoring the safety backup brings the changes back")

# ---- restore by a proxy-header admin: no cookie needed, relogin false
r = restore(PX, BP, name=good)
check(r.ok and not r.json()["relogin"] and "kalmido_session" not in r.cookies, f"proxy admin restores: {r.text[:120]}")
check(PX.get(BP + "/api/me").ok, "proxy admin still logged in")
A = sess("alice")

# ---- upload + restore an uploaded archive
r = A.get(B + f"/api/admin/backups/{good}/download")
up = upload(r.content)
check(up.ok and up.json()["upload"].startswith("upload-") and up.json()["counts"]["tasks"] == 2 and not up.json()["encrypted"],
      f"upload accepted with a summary: {up.text[:200]}")
A.post(B + "/api/tasks", json={"title": "before upload restore", "list_id": L})
r = restore(upload=up.json()["upload"])
A = sess("alice")
check(r.ok and "before upload restore" not in titles(A), "restored from the uploaded file")
check(not os.listdir(os.path.join(BK, ".uploads")), "the uploaded file is removed afterwards")
check(restore(upload="upload-../../tasks.db").status_code == 404, "upload id with a path -> 404")

# ---- refused archives (nothing changes)
ref = titles(A)
src_db = zipfile.ZipFile(os.path.join(BK, good)).read("tasks.db")


def refused(data, code, what):
    r = upload(data)
    if r.ok:
        r = restore(upload=r.json()["upload"])
    ok = r.status_code in (400, 413) and (r.json().get("code") == code if code else True)
    check(ok, f"{what}: refused ({r.status_code} {r.text[:160]})")
    check(titles(A) == ref, f"{what}: nothing changed")
    check(not any(n.startswith(("attachments.", ".restore")) for n in os.listdir(DATA) + os.listdir(BK)), f"{what}: no leftovers")


refused(b"hello world, not a zip", "format", "random bytes")
refused(make_zip({"tasks.db": src_db}, fix=False), "format", "zip without manifest")
refused(make_zip({"tasks.db": src_db, "../../evil.txt": b"x"}), "members", "path traversal member")
refused(make_zip({"tasks.db": src_db, "attachments/1/../../../x": b"x"}), "members", "traversal inside attachments")
refused(make_zip({"tasks.db": src_db, "/etc/passwd": b"x"}), "members", "absolute member")
refused(make_zip({"tasks.db": src_db, "attachments/1/..": b"x"}), "members", "'..' as file name")
refused(make_zip({"tasks.db": src_db, "other.txt": b"x"}), "members", "unexpected member")
link = zipfile.ZipInfo("attachments/1/link")
link.external_attr = (stat.S_IFLNK | 0o777) << 16
refused(make_zip({"tasks.db": src_db, "attachments/1/link": link}), "members", "symlink member")
refused(make_zip({"tasks.db": src_db}, manifest={"format": "kalmido-backup", "format_version": 1, "app_version": "9.9.9", "schema_version": 2,
                                                  "files": [["tasks.db", len(src_db), "0" * 64]]}), "hash", "checksum mismatch")
refused(make_zip({"tasks.db": src_db}, manifest={"format": "kalmido-backup", "format_version": 1, "app_version": "9.9.9", "schema_version": 2,
                                                  "files": [["tasks.db", len(src_db) - 1, hashlib.sha256(src_db).hexdigest()]]}), None, "size mismatch")
refused(make_zip({"tasks.db": src_db, "attachments/1/zeros.bin": b"\0" * (4 * 1024 * 1024)}), "bomb", "zip bomb (ratio)")
refused(make_zip({"tasks.db": src_db, "attachments/1/big.bin": os.urandom(6 * 1024 * 1024)}), None, "larger than KALMIDO_BACKUP_MAX_MB")
refused(make_zip({"tasks.db": src_db}, schema=99), "schema", "newer schema (manifest)")
tmpdb = os.path.join(DATA, "t.db")
open(tmpdb, "wb").write(src_db)
c = sqlite3.connect(tmpdb)
c.execute("PRAGMA user_version=99")
c.commit()
c.close()
refused(make_zip({"tasks.db": open(tmpdb, "rb").read()}), "schema", "newer schema (database)")
open(tmpdb, "wb").write(src_db)
c = sqlite3.connect(tmpdb)
c.execute("CREATE TRIGGER evil AFTER INSERT ON tasks BEGIN DELETE FROM users; END")
c.commit()
c.close()
refused(make_zip({"tasks.db": open(tmpdb, "rb").read()}), "objects", "foreign trigger")
dmg = bytearray(src_db)
for off in range(4096 * 2, min(len(dmg), 4096 * 6), 7):
    dmg[off] ^= 0x5A
refused(make_zip({"tasks.db": bytes(dmg)}), None, "damaged database")
os.remove(tmpdb)

# ---- encryption
r = A.patch(B + "/api/admin/backups", json={"encrypt": True, "passphrase": "correct horse battery"})
check(r.ok and r.json()["encrypt"] and r.json()["passphrase_set"], "encryption on")
check("correct horse" not in json.dumps(r.json()) and "correct horse" not in json.dumps(dbx("SELECT value FROM settings WHERE key='bk_pass'")),
      "passphrase never returned, stored sealed")
j = backup_now()
check(not j["last_error"], f"encrypted backup written: {j['last_error']}")
enc = [x for x in j["items"] if x["encrypted"]][0]
check(enc["encrypted"] and enc["name"].endswith(".zip.enc") and enc["counts"]["tasks"] >= 2, f"encrypted backup listed with its summary: {enc}")
ep = os.path.join(BK, enc["name"])
raw = open(ep, "rb").read()
check(raw.startswith(MAGIC) and src_db[:16] not in raw and b"kept task" not in raw, "encrypted file: magic, no plain text")
h, plain = decrypt(ep, "correct horse battery")
with zipfile.ZipFile(io.BytesIO(plain)) as z:
    check("tasks.db" in z.namelist() and h["kdf"] == "scrypt", "independent decryption of the documented format works")
r = A.post(B + f"/api/admin/backups/{enc['name']}/verify", json={"passphrase": "wrong passphrase!"})
check(r.status_code == 400 and r.json()["code"] == "passphrase", "verify with a wrong passphrase refused")
check(A.post(B + f"/api/admin/backups/{enc['name']}/verify", json={}).ok, "verify with the saved passphrase")
A.post(B + "/api/tasks", json={"title": "after encrypted backup", "list_id": L})
r = restore(name=enc["name"], passphrase="wrong passphrase!")
check(r.status_code == 400 and r.json()["code"] == "passphrase" and "after encrypted backup" in titles(A), "restore with a wrong passphrase: refused, nothing changed")
trunc = raw[:-40]
up = upload(trunc)
r = restore(upload=up.json()["upload"], passphrase="correct horse battery") if up.ok else up
check(r.status_code == 400, "truncated encrypted file refused")
A.patch(B + "/api/admin/backups", json={"passphrase": "another passphrase 2"})
r = restore(name=enc["name"], passphrase="correct horse battery")
A = sess("alice")
check(r.ok and "after encrypted backup" not in titles(A), "restore of the encrypted backup with its passphrase")
r = A.patch(B + "/api/admin/backups", json={"encrypt": False})
check(r.ok and not r.json()["encrypt"], "encryption off again")

# ---- delete
j = state()
n = j["items"][-1]["name"]
r = A.delete(B + f"/api/admin/backups/{n}")
check(r.ok and n not in [x["name"] for x in r.json()["items"]] and not os.path.exists(os.path.join(BK, n)), "delete a backup")
check(Bo.delete(B + f"/api/admin/backups/{j['items'][0]['name']}").status_code in (401, 403), "user cannot delete")

logs = subprocess.run(["docker", "logs", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True, text=True)
check("correct horse" not in logs.stdout + logs.stderr and "another passphrase" not in logs.stdout + logs.stderr, "passphrases never logged")

# ------------------------------------------------------------------ container 2: KALMIDO_BACKUPS=0
start(backups="0")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
check(A.get(B + "/api/admin/backups").status_code == 404, "KALMIDO_BACKUPS=0: API off")
check(A.get(B + "/api/about").json().get("backups_env") is False, "KALMIDO_BACKUPS=0: about says so")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
