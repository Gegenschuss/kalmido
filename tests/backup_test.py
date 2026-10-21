#!/usr/bin/env python3
"""Backups + restore (package A): admin-only API + CSRF, settings validation, "Back up now" (zip layout, manifest
checksums, file mode), download (auth, streamed bytes), the daily schedule (runs once per day), retention (daily +
weekly + safety), the "older than 2 days" and "backup failed" admin alerts, encryption (own format: scrypt + AES-GCM
chunks, decrypted here independently; wrong passphrase refused), restore of a listed backup and of an uploaded file
(data, attachments, safety backup, backup settings kept, every other session ended, the admin gets a fresh one,
migrations / schema version), and refused archives: not a zip, no manifest, path traversal / absolute / symlink
members, checksum mismatch, zip bomb, too large, newer schema (manifest and dump), foreign trigger / view / function,
damaged dump -- each without changing anything. 2.37.0 (#1150, Postgres): the archive holds kalmido.dump (pg_dump -Fc,
format_version 2); a restore brings back the rows of every table of two organisations (counted per table before / after),
attachments and office files; an archive from before 2.37 (tasks.db, format 1) is listed, uploaded and checked, but its
restore is refused with its own code ("legacy"). Finally KALMIDO_BACKUPS=0.
Starts its OWN test containers (start.sh, KALMIDO_ADMIN_ALERTS=1, KALMIDO_BACKUP_TICK=1, KALMIDO_BACKUP_MAX_MB=5).
usage: backup_test.py <datadir>"""
import base64
import hashlib
import io
import json
import os
import dbx as dbxm
import shutil
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
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)  # 2.37.0: Postgres
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


def make_zip(members, manifest=None, fix=True, schema=None, fv=2):
    """A zip with members {name: bytes}; manifest built from them (fix=True) unless given."""
    # 2.149.0 (#2509): app_version 2.0.0 (was 9.9.9): a backup of a newer minor is refused before the checks below
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
            manifest = {"format": "kalmido-backup", "format_version": fv, "app_version": "2.0.0", "schema_version": schema or 2,
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
# 2.45.0 (#1515): a new server (first setup) backs up daily by default; the first automatic one is tomorrow
check(j["env"] and j["on"] and j["time"] == "03:30" and j["keep_daily"] == 14 and j["keep_weekly"] == 8 and not j["encrypt"]
      and j["items"] == [] and j["confirm_word"] == "RESTORE", f"defaults: on, 03:30, 14 + 8, unencrypted: {j}")
check(dbx("SELECT value FROM settings WHERE key='bk_last_day'")[0][0] == datetime.now(TZ).date().isoformat(),
      "on from the first setup: no automatic backup of the empty server today")
check(A.patch(B + "/api/admin/backups", json={"on": False}).ok and not state()["on"], "switched off (the steps below switch it on)")
for bad in ({"on": "yes"}, {"time": "25:00"}, {"keep_daily": 0}, {"keep_daily": 400}, {"keep_weekly": -1}, {"keep_daily": True},
            {"encrypt": True}, {"passphrase": "short"}, {"encrypt": "1"}):
    check(A.patch(B + "/api/admin/backups", json=bad).status_code == 400, f"invalid setting rejected: {bad}")
check(not state()["encrypt"] and state()["time"] == "03:30", "nothing stored after invalid input")

# 2.37.0 (#1150): rows of two organisations (written straight into the database: the instance mode does not matter
# for the backup) + an office logo file -- a restore must bring back every table's rows of both
ORGS = []
for on in ("Org North", "Org South"):
    oid = dbx("INSERT INTO orgs(name, icon, domains, created_at) VALUES(?, '', '', '2026-01-01T00:00:00+00:00') RETURNING id", (on,))[0][0]
    ORGS.append(oid)
    dbx("INSERT INTO lists(name, owner_id, org_id, created_at) VALUES(?, 1, ?, '2026-01-01T00:00:00+00:00')", (on + " list", oid))
    dbx("INSERT INTO org_members(org_id, user_id, role) VALUES(?, 2, 'member') ON CONFLICT DO NOTHING", (oid,))
OFF = os.path.join(DATA, "office", str(ORGS[0]))
os.makedirs(OFF, exist_ok=True)
open(os.path.join(OFF, "logo.png"), "wb").write(b"\x89PNG\r\n" + b"office logo" * 50)


def table_counts():
    """{table: rows} of every table of the database (one statement)."""
    return {r[0]: int(r[1]) for r in dbx(
        "SELECT relname, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM public.%I', relname), "
        "false, true, '')))[1]::text FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'")}


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
check("kalmido.dump" in names and "tasks.db" not in names and "manifest.json" in names
      and sum(n.startswith("attachments/") for n in names) == 2 and f"office/{ORGS[0]}/logo.png" in names,
      f"zip: kalmido.dump, manifest, 2 attachments, 1 office file: {names}")
with zipfile.ZipFile(p) as z:
    check(z.read("kalmido.dump")[:5] == b"PGDMP", "kalmido.dump is a pg_dump archive (custom format)")
check(man["format"] == "kalmido-backup" and man["format_version"] == 2 and man["schema_version"] == 2 and man["counts"]["tasks"] == 2
      and man["counts"]["lists"] >= 4 and man["attachment_files"] == 3,
      f"manifest: {dict((k, man.get(k)) for k in ('format', 'format_version', 'schema_version', 'counts', 'attachment_files'))}")
check(okhash, "every member matches its SHA-256 and size")
it = j["items"][0]
check(it["counts"]["tasks"] == 2 and it["attachment_files"] == 3 and it["counts"]["users"] == 3 and not it["legacy"],
      f"list shows the contents: {it}")
r = A.post(B + f"/api/admin/backups/{name}/verify", json={})
check(r.ok and r.json()["ok"] and r.json()["counts"]["tasks"] == 2 and r.json()["legacy"] is False, f"verify: {r.text[:200]}")

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
# 2.81.0 (#1627): switching on again starts the clock then -- an old bk_last_ok alone no longer alerts at once
time.sleep(4)
check(not alerts("backup:stale"), "no 'older than 2 days' alert right after switching on again (clock starts at bk_enabled_at)")
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
C0 = table_counts()
j = backup_now()
good = j["items"][0]["name"]
check(j["items"][0]["kind"] == "manual", "fresh backup before the changes")
dbx("DELETE FROM lists WHERE org_id=?", (ORGS[1],))  # 2.37.0: the second organisation goes (rows of several tables)
dbx("DELETE FROM orgs WHERE id=?", (ORGS[1],))
os.remove(os.path.join(OFF, "logo.png"))
open(os.path.join(OFF, "late.png"), "wb").write(b"late office file")
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
# 2.148.1 G (#2482): files the archive does not bring (here late.txt / late.png, made after the backup) are never deleted
# unseen: the folder of before stays once, holding them; this test removes it so the checks below see no leftovers
def _drop_kept(what):
    """2.148.1 G (#2482): a successful restore keeps the folders of before while they hold files the archive does not list;
    the checks of refused archives below are about their own leftovers, so the kept ones of successful restores go here
    (named in the log)."""
    for k in [n for n in os.listdir(DATA) if ".pre-restore-" in n]:
        fs = [os.path.relpath(os.path.join(r, f), os.path.join(DATA, k)) for r, _d, ff in os.walk(os.path.join(DATA, k)) for f in ff]
        print(f"{what}: kept {k} with {len(fs)} file(s): {sorted(fs)[:5]}", flush=True)
        shutil.rmtree(os.path.join(DATA, k), ignore_errors=True)


def _kept(prefix, fname):
    ks = [n for n in os.listdir(DATA) if n.startswith(prefix + ".pre-restore-")]
    has = [k for k in ks if any(f.endswith(fname) for _r, _d, fs in os.walk(os.path.join(DATA, k)) for f in fs)]
    for k in ks:
        shutil.rmtree(os.path.join(DATA, k), ignore_errors=True)
    return ks, has
ks, has = _kept("attachments", "late.txt")
check(len(ks) == 1 and has == ks, f"the attachments of before stay once, with the file made after the backup: {ks}")
check(not any(n.startswith("attachments.") for n in os.listdir(DATA)), f"no leftover attachment folders: {os.listdir(DATA)}")
check(state()["keep_daily"] == 9, "backup settings are kept across a restore")
check(dbx("SELECT value FROM kalmido_meta WHERE key='schema_version'")[0][0] == "2"
      and dbx("SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='totp_secret'"), "schema version + migrations")
# 2.37.0: every table has the rows of the backup again (both organisations); the sessions start over, the restore adds
# its own admin alert
C1 = table_counts()
# 2.42.0 (#1376): dl_changes is the change journal of the delta state (the restore's own writes land there too)
diff = {t: (C0.get(t), C1.get(t)) for t in set(C0) | set(C1) if C0.get(t) != C1.get(t) and t not in ("sessions", "admin_alerts", "dl_changes")}
check(not diff and len(C0) > 50, f"restore: the row count of every table is the backup's ({len(C0)} tables), differences: {diff}")
check([r[0] for r in dbx("SELECT name FROM orgs WHERE id IN (?, ?) ORDER BY id", tuple(ORGS))] == ["Org North", "Org South"]
      and len(dbx("SELECT 1 FROM lists WHERE org_id IN (?, ?)", tuple(ORGS))) == 2, "both organisations and their lists are back")
check(os.path.isfile(os.path.join(OFF, "logo.png")) and not os.path.exists(os.path.join(OFF, "late.png"))
      and open(os.path.join(OFF, "logo.png"), "rb").read().endswith(b"office logo"), "office files: the backup's state")
ks, has = _kept("office", "late.png")
check(len(ks) == 1 and has == ks, f"the office files of before stay once, with late.png: {ks}")
check(not any(n.startswith("office.") for n in os.listdir(DATA)), "no leftover office folders")
rls = dbx("SELECT COUNT(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relrowsecurity AND relforcerowsecurity")[0][0]
check(rls >= 10 and dbx("SELECT COUNT(*) FROM pg_policies WHERE schemaname='public'")[0][0] >= rls,
      f"row-level security is back after the restore ({rls} tables)")
check(dbx("SELECT COUNT(*) FROM pg_extension WHERE extname IN ('unaccent', 'pg_trgm')")[0][0] == 2
      and dbx("SELECT kalmido_fold('Grüße')")[0][0].startswith("grusse"), "extensions + the search function survive pg_restore --clean")
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
_drop_kept("proxy + upload restore")

# ---- refused archives (nothing changes)
ref = titles(A)
src_dump = zipfile.ZipFile(os.path.join(BK, good)).read("kalmido.dump")


def refused(data, code, what):
    r = upload(data)
    if r.ok:
        r = restore(upload=r.json()["upload"])
    ok = r.status_code in (400, 413) and (r.json().get("code") == code if code else True)
    check(ok, f"{what}: refused ({r.status_code} {r.text[:160]})")
    check(titles(A) == ref, f"{what}: nothing changed")
    check(not any(n.startswith(("attachments.", ".restore")) for n in os.listdir(DATA) + os.listdir(BK)), f"{what}: no leftovers")


refused(b"hello world, not a zip", "format", "random bytes")
refused(make_zip({"kalmido.dump": src_dump}, fix=False), "format", "zip without manifest")
refused(make_zip({"kalmido.dump": src_dump, "../../evil.txt": b"x"}), "members", "path traversal member")
refused(make_zip({"kalmido.dump": src_dump, "attachments/1/../../../x": b"x"}), "members", "traversal inside attachments")
refused(make_zip({"kalmido.dump": src_dump, "/etc/passwd": b"x"}), "members", "absolute member")
refused(make_zip({"kalmido.dump": src_dump, "attachments/1/..": b"x"}), "members", "'..' as file name")
refused(make_zip({"kalmido.dump": src_dump, "other.txt": b"x"}), "members", "unexpected member")
link = zipfile.ZipInfo("attachments/1/link")
link.external_attr = (stat.S_IFLNK | 0o777) << 16
refused(make_zip({"kalmido.dump": src_dump, "attachments/1/link": link}), "members", "symlink member")
refused(make_zip({"kalmido.dump": src_dump}, manifest={"format": "kalmido-backup", "format_version": 2, "app_version": "2.0.0", "schema_version": 2,
                                                  "files": [["kalmido.dump", len(src_dump), "0" * 64]]}), "hash", "checksum mismatch")
refused(make_zip({"kalmido.dump": src_dump}, manifest={"format": "kalmido-backup", "format_version": 2, "app_version": "2.0.0", "schema_version": 2,
                                                  "files": [["kalmido.dump", len(src_dump) - 1, hashlib.sha256(src_dump).hexdigest()]]}), None, "size mismatch")
refused(make_zip({"kalmido.dump": src_dump, "attachments/1/zeros.bin": b"\0" * (3 * 1024 * 1024)}), "bomb", "zip bomb (ratio)")  # 2.22.0: 3 MB (the bigger schema + 4 MB passed the 5 MB size limit first)
refused(make_zip({"kalmido.dump": src_dump, "attachments/1/big.bin": os.urandom(6 * 1024 * 1024)}), None, "larger than KALMIDO_BACKUP_MAX_MB")
refused(make_zip({"kalmido.dump": src_dump}, schema=99), "schema", "newer schema (manifest)")


def dump_with(setup, teardown):
    """The kalmido.dump of a backup taken while the database holds something a Kalmido database never has (the backup
    itself is deleted again)."""
    before = {x["name"] for x in state()["items"]}
    for q in setup:
        dbx(q)
    try:
        j = backup_now()
    finally:
        for q in teardown:
            dbx(q)
    new = [x["name"] for x in j["items"] if x["name"] not in before and x["kind"] == "manual"]
    assert len(new) == 1 and not j["last_error"], (new, j["last_error"])
    d = zipfile.ZipFile(os.path.join(BK, new[0])).read("kalmido.dump")
    r = A.post(B + f"/api/admin/backups/{new[0]}/verify", json={})
    print("dump_with verify:", r.status_code, r.text[:160], flush=True)
    os.remove(os.path.join(BK, new[0]))
    return d


refused(make_zip({"kalmido.dump": dump_with(["UPDATE kalmido_meta SET value='99' WHERE key='schema_version'"],
                                            ["UPDATE kalmido_meta SET value='2' WHERE key='schema_version'"])}),
        "schema", "newer schema (the dump's kalmido_meta, manifest says 2)")
refused(make_zip({"kalmido.dump": dump_with(
    ["CREATE FUNCTION evil_fn() RETURNS trigger LANGUAGE plpgsql AS $f$BEGIN DELETE FROM users; RETURN NULL; END$f$",
     "CREATE TRIGGER evil AFTER INSERT ON tasks FOR EACH ROW EXECUTE FUNCTION evil_fn()"],
    ["DROP TRIGGER evil ON tasks", "DROP FUNCTION evil_fn()"])}), "objects", "foreign trigger + function")
refused(make_zip({"kalmido.dump": dump_with(["CREATE VIEW evil_v AS SELECT id FROM users"], ["DROP VIEW evil_v"])}),
        "objects", "foreign view")


# 2.37.0 (review W2-1): a restore takes no code from a dump (filtered table of contents; init_db makes functions, triggers
# and policies from the app's own source). Own-named functions / triggers that do harmful things: the restore either
# refuses the dump or goes through WITHOUT them -- checked in pg_proc / pg_trigger / pg_class afterwards.
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")


def code_state():
    return {"procs": {r[0] for r in dbx("SELECT proname FROM pg_proc WHERE proname LIKE 'kalmido%'")},
            "trgs": {r[0] for r in dbx("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")},
            "rls": {r[0] for r in dbx("SELECT relname FROM pg_class WHERE relkind='r' AND relrowsecurity AND relforcerowsecurity")},
            "pols": len(dbx("SELECT 1 FROM pg_policy"))}


def no_code(setup, teardown, fn, trg, what):
    global A
    before = code_state()
    data = make_zip({"kalmido.dump": dump_with(setup, teardown)})
    check(code_state() == before, f"{what}: the test database is clean again before the restore")
    up = upload(data)
    r = restore(upload=up.json()["upload"]) if up.ok else up
    A = sess("alice")
    if r.ok:  # restored without the code
        after = code_state()
        check(fn not in after["procs"] and (trg is None or trg not in after["trgs"]), f"{what}: restored, its code is not in the database")
        check(after == before, f"{what}: functions, triggers, policies, row security as before ({before} / {after})")
        dbx("UPDATE kalmido_meta SET value=value WHERE key='schema_version'")  # (would fire a trigger on kalmido_meta)
        check(code_state() == before, f"{what}: still the same after a write to kalmido_meta")
    else:
        check(r.status_code == 400 and r.json().get("code") == "objects", f"{what}: refused ({r.status_code} {r.text[:160]})")
    check(titles(A) == ref, f"{what}: data unchanged")


EVIL = "CREATE FUNCTION kalmido_evil() RETURNS trigger LANGUAGE plpgsql AS $f$BEGIN {0}; RETURN NEW; END$f$"
EVIL_TRG = "CREATE TRIGGER kalmido_evil BEFORE UPDATE ON kalmido_meta FOR EACH ROW EXECUTE FUNCTION kalmido_evil()"
UNDO = ["DROP FUNCTION kalmido_evil() CASCADE"]
no_code([EVIL.format("RESET ROLE")], UNDO, "kalmido_evil", None, "own-named function with RESET ROLE")
no_code([EVIL.format("SET app.role = 'system'")], UNDO, "kalmido_evil", None, "own-named function with SET app.role")
no_code([EVIL.format("ALTER TABLE public.lists DISABLE ROW LEVEL SECURITY")], UNDO, "kalmido_evil", None,
        "own-named function with ALTER TABLE ... DISABLE ROW LEVEL SECURITY")
no_code([EVIL.format("ALTER TABLE public.lists DISABLE ROW LEVEL SECURITY"), EVIL_TRG], UNDO, "kalmido_evil", "kalmido_evil",
        "own-named trigger on kalmido_meta")
no_code(["CREATE FUNCTION kalmido_evil() RETURNS void LANGUAGE plpgsql AS $f$BEGIN EXECUTE 'SELECT 1'; END$f$"], UNDO,
        "kalmido_evil", None, "an own-named function with dynamic SQL")
check("lists" in code_state()["rls"], "lists keep FORCE row level security")
# the second floor (the SQL of the filtered list): such statements are refused wherever they would appear
r = subprocess.run(["docker", "exec", CT, "python3", "-c", r"""
import json, sys
from kalmido.admin.backup import bk_check_statement as ok
bad = ["RESET ROLE", "RESET ALL", "RESET SESSION AUTHORIZATION", "SET ROLE kalmido", "SET LOCAL ROLE kalmido",
       "SET session_authorization = 'kalmido'", "SET SESSION AUTHORIZATION kalmido", "SET app.role = 'system'",
       "SET LOCAL app.role = 'system'", "SET role = 'kalmido'", "ALTER TABLE public.lists DISABLE ROW LEVEL SECURITY",
       "ALTER TABLE public.lists NO FORCE ROW LEVEL SECURITY", "ALTER TABLE public.lists ENABLE ROW LEVEL SECURITY",
       "DROP POLICY IF EXISTS kalmido_org ON public.lists", "CREATE POLICY p ON public.lists USING (true)",
       "CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public", "DROP EXTENSION IF EXISTS pg_trgm",
       "CREATE FUNCTION public.kalmido_x() RETURNS void LANGUAGE c AS 'x', 'y'",
       "CREATE FUNCTION public.kalmido_x() RETURNS void LANGUAGE sql AS $$SELECT 1$$",
       "CREATE TRIGGER time_task_list AFTER UPDATE ON public.tasks FOR EACH ROW EXECUTE FUNCTION public.kalmido_time_task_list()",
       "ALTER FUNCTION public.kalmido_fold(text) SET search_path = public", "DO $$BEGIN NULL; END$$",
       "ALTER TABLE ONLY public.tasks ALTER COLUMN title SET DEFAULT set_config('role', 'x', false)",
       "COPY public.tasks (id) FROM PROGRAM 'id'",
       # quoted / Unicode / escape-string call heads in expressions (review W2-1, B1)
       "ALTER TABLE ONLY public.tasks ALTER COLUMN title SET DEFAULT pg_catalog.\"set_config\"('role', 'none', false)",
       "ALTER TABLE ONLY public.tasks ALTER COLUMN title SET DEFAULT U&\"pg\\005fread_file\"('/etc/passwd')",
       "CREATE TABLE public.t (a text DEFAULT pg_catalog.\"set_config\"('a', 'b', false))",
       "ALTER TABLE ONLY public.t ADD CONSTRAINT c CHECK ((pg_catalog.\"set_config\"('a', 'b', false) IS NOT NULL))",
       "CREATE INDEX i ON public.t USING btree (a) WHERE (pg_catalog.\"set_config\"('a', 'b', false) IS NOT NULL)",
       "ALTER TABLE ONLY public.tasks ALTER COLUMN title SET DEFAULT E'\\'' || pg_sleep(1) || '\\''",
       "ALTER TABLE ONLY public.tasks ALTER COLUMN title SET DEFAULT pg_sleep(1)",
       # review W3-2: quotes around the schema
       "ALTER TABLE ONLY public.tasks ALTER COLUMN title SET DEFAULT \"pg_catalog\".pg_sleep(10)::text",
       "ALTER TABLE ONLY public.tasks ALTER COLUMN title SET DEFAULT \"pg_catalog\".lo_from_bytea(0, '\\x00')::text",
       "ALTER TABLE ONLY public.tasks ALTER COLUMN title SET DEFAULT \"pg_catalog\".current_setting('is_superuser')"]
good = ["CREATE TABLE public.t (id bigint NOT NULL, title text DEFAULT ''::text NOT NULL)", "SET row_security = on",
        "ALTER TABLE ONLY public.lists FORCE ROW LEVEL SECURITY", "SELECT pg_catalog.setval('public.tasks_id_seq', 5, true)",
        "CREATE INDEX m ON public.chat USING gin (public.kalmido_fold(body) public.gin_trgm_ops)",
        "CREATE TABLE public.t2 (a character varying(8) DEFAULT ''::character varying, b numeric(14,4) DEFAULT 0 NOT NULL)"]
print(json.dumps({"bad_ok": [s for s in bad if ok(s)], "good_refused": [s for s in good if not ok(s)]}))
"""], capture_output=True, text=True)
try:
    res = json.loads(r.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    res = {"error": (r.stdout + r.stderr)[-400:]}
check(res.get("bad_ok") == [] and res.get("good_refused") == [], f"statement check (second floor): {res}")

# ---- 2.37.0 (review K2-5): pg_restore itself fails (the dump's data breaks a foreign key) -> way back: the data as before,
# the safety backup listed, no folder left over
old_safety = {x["name"] for x in state()["items"] if x["kind"] == "safety"}
fk_dump = dump_with(["ALTER TABLE tasks DISABLE TRIGGER ALL",
                     "INSERT INTO tasks(list_id, title, created_at, updated_at) VALUES(999999, 'orphan task', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
                     "ALTER TABLE tasks ENABLE TRIGGER ALL"],
                    ["DELETE FROM tasks WHERE list_id=999999"])
check(not dbx("SELECT 1 FROM tasks WHERE list_id=999999"), "K2-5: the orphan row is gone again before the restore")
up = upload(make_zip({"kalmido.dump": fk_dump}))
r = restore(upload=up.json()["upload"]) if up.ok else up
A = sess("alice")
check(r.status_code == 400 and r.json().get("code") == "restore", f"K2-5: pg_restore failed -> refused with code restore ({r.status_code} {r.text[:200]})")
check(titles(A) == ref and not dbx("SELECT 1 FROM tasks WHERE list_id=999999"), "K2-5: data as before")
check(code_state()["pols"] > 0 and "lists" in code_state()["rls"], "K2-5: policies and row security back")
check(r.ok is False and r.json().get("safety") in (None, "") and len({x["name"] for x in state()["items"] if x["kind"] == "safety"} - old_safety) == 1,
      "K2-5: the safety backup is listed (the newest of the last 3)")
check(not any("restore" in n for n in os.listdir(DATA) + os.listdir(BK)), f"K2-5: no .restore / .pre-restore folder left: {os.listdir(DATA)}")
check(A.post(B + "/api/tasks", json={"title": "after failed restore", "list_id": L}).ok, "K2-5: the app works after the way back")
ref = titles(A)
dmg = bytearray(src_dump)
for off in range(len(dmg) // 2, len(dmg) // 2 + 4000, 7):
    dmg[off] ^= 0x5A
refused(make_zip({"kalmido.dump": bytes(dmg)}), "integrity", "damaged dump (checksums fixed in the manifest)")
refused(make_zip({"kalmido.dump": src_dump[:len(src_dump) // 2]}), "integrity", "truncated dump")
refused(make_zip({"kalmido.dump": b"PGDMP" + os.urandom(3000)}), None, "garbage after the dump magic")
refused(make_zip({"kalmido.dump": src_dump}, fv=1), "format", "format_version 1 with a dump")
refused(make_zip({"kalmido.dump": src_dump, "tasks.db": b"SQLite format 3\x00"}), "format", "dump and tasks.db together")

# ---- 2.37.0: an archive from before 2.37 (tasks.db, format 1): listed, uploaded and checked, its restore refused
old_zip = make_zip({"tasks.db": b"SQLite format 3\x00" + os.urandom(4000), "attachments/1/a.txt": b"old file"}, fv=1)
up = upload(old_zip)
check(up.ok and up.json()["legacy"] is True and up.json()["schema_version"] == 2, f"old archive: upload accepted, marked legacy: {up.text[:200]}")
r = A.post(B + f"/api/admin/backups/{up.json()['upload']}/verify", json={}) if up.ok else up
check(r.ok and r.json()["ok"] and r.json()["legacy"] is True, f"old archive: verify checks its members: {r.text[:200]}")
r = restore(upload=up.json()["upload"]) if up.ok else up
check(r.status_code == 400 and r.json().get("code") == "legacy" and "2.36" in r.json().get("error", ""),
      f"old archive: restore refused with its own code: {r.text[:240]}")
check(titles(A) == ref and not any(n.startswith(("attachments.", ".restore")) for n in os.listdir(DATA) + os.listdir(BK)),
      "old archive: nothing changed")
r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "upload": up.json()["upload"]},
           headers={"Accept-Language": "de"}) if up.ok else up
check(r.status_code == 400 and "SQLite" in r.json().get("error", ""), f"old archive: the text names the cause: {r.text[:200]}")
old_name = "kalmido-backup-20200101-030000-manual.zip"
open(os.path.join(BK, old_name), "wb").write(old_zip)
r = A.get(B + "/api/admin/backups")
it = [x for x in r.json()["items"] if x["name"] == old_name] if r.ok else []
check(r.ok and it and it[0]["legacy"] is True and not it[0]["unreadable"], f"old archive in the folder: listed as legacy: {it}")
r = restore(name=old_name)
check(r.status_code == 400 and r.json().get("code") == "legacy", "old listed archive: restore refused")
os.remove(os.path.join(BK, old_name))

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
check(raw.startswith(MAGIC) and b"PGDMP" not in raw and b"kept task" not in raw, "encrypted file: magic, no plain text")
h, plain = decrypt(ep, "correct horse battery")
with zipfile.ZipFile(io.BytesIO(plain)) as z:
    check("kalmido.dump" in z.namelist() and z.read("kalmido.dump")[:5] == b"PGDMP" and h["kdf"] == "scrypt"
          and h["meta"].get("format_version") == 2, "independent decryption of the documented format works")
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
check(len(dbx("SELECT 1 FROM lists WHERE org_id IN (?, ?)", tuple(ORGS))) == 2, "encrypted round trip: both organisations' lists")
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
