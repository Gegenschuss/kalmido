#!/usr/bin/env python3
"""2.149.0 API tests, part D: downgrade / restore guard (#2509), self-hosting (#2510), environment registry (#2511).
freelancer-matrix: admin
 - unit (pure Python): kalmido/core/env.py reads every switch the same way (1/true/yes/on, 0/false/no/off, any case,
   empty = default, anything else = default), env_int with limits, no variable declared twice; tools/env_check.py passes
   (every read variable declared, docs/ENV.md current)
 - in the container: appver_check for patch / newer minor / the one step back / a newer major
 - the server: a new database is stamped with app_version (no app_version_prev); a database a newer minor ran on refuses
   to start (FATAL in the log), KALMIDO_ALLOW_DOWNGRADE=1 starts it with a warning and keeps the stamp; the one step back
   (app_version_prev = this version) starts without it and changes no stamp; a database of an older version is upgraded
   (prev = the older one); a newer patch of the same minor starts and keeps its stamp
 - TASKS_WATCHDOG: true = on (the watchdog loop runs, was off before 2.149), 0 = off, unset = on
 - restore: an archive whose manifest names a newer minor is refused with code "newer" (upload check), an older one is not
   refused for its version; a person without an organisation (own admin of the private space only) gets 403
 - server key: a new database without a key refuses to start unless KALMIDO_NO_SECRET_KEY=1; a key file created during a
   start next to a database that holds account keys is removed again and the start refused; the old key file starts it
 - data folder without write access: a clear FATAL with the uid instead of a traceback
usage: p2149_d_api_test.py <datadir>   (P2149D_NOSTART=1 / KMT_NOSTART=1: skip the first fresh start)"""
import base64
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
SEC = DATA.rstrip("/") + "-secret2149"  # next to the data dir, never inside it
KEYF = os.path.join(SEC, "kalmido.key")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


# ---- unit: kalmido/core/env.py (no imports from the app) ---------------------------------------------------------------
spec = importlib.util.spec_from_file_location("p2149d_env", os.path.join(SRC, "kalmido", "core", "env.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
_saved = os.environ.get("P2149D_X")
for raw, dflt, want in (("1", False, True), ("true", False, True), ("YES", False, True), (" On ", False, True),
                        ("0", True, False), ("false", True, False), ("No", True, False), ("OFF", True, False),
                        ("", True, True), ("", False, False), ("maybe", True, True), ("maybe", False, False)):
    os.environ["P2149D_X"] = raw
    check(E.env_bool("P2149D_X", dflt) is want, f"env_bool({raw!r}, default {dflt}) = {want}")
os.environ.pop("P2149D_X", None)
check(E.env_bool("P2149D_X", True) is True and E.env_bool("P2149D_X", False) is False, "env_bool: unset = the default")
os.environ["P2149D_X"] = "7"
check(E.env_int("P2149D_X", 3, lo=1, hi=5) == 5 and E.env_int("P2149D_X", 3) == 7, "env_int: value and upper limit")
os.environ["P2149D_X"] = "x"
check(E.env_int("P2149D_X", 3) == 3, "env_int: not a number = the default")
os.environ.pop("P2149D_X", None)
if _saved is not None:
    os.environ["P2149D_X"] = _saved
names = [v[0] for v in E.VARS]
check(len(names) == len(set(names)), "env registry: no variable declared twice")
for need in ("TASKS_WATCHDOG", "KALMIDO_ALLOW_DOWNGRADE", "KALMIDO_NO_SECRET_KEY", "TASKS_DB", "KALMIDO_UPDATE_URL", "PUBLIC_URL"):
    check(need in names, f"env registry declares {need}")
check(all(v[2] and v[3] for v in E.VARS), "env registry: every variable has a doc sentence and a group")
check(E.env_str("P2149D_UNSET", "dflt") == "dflt" and E.env_default("TASKS_WATCHDOG") == "1", "env_str / env_default")
r = subprocess.run([sys.executable, os.path.join(SRC, "tools", "env_check.py")], capture_output=True, text=True)
check(r.returncode == 0, f"tools/env_check.py passes: {r.stdout[-400:]} {r.stderr[-200:]}")


# ---- the server ---------------------------------------------------------------------------------------------------------
def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall() if not write else None
        if write:
            c.execute(sql, args)
            c.commit()
        return r
    finally:
        c.close()


def meta():
    return {k: v for k, v in dbx("SELECT key, value FROM kalmido_meta WHERE key IN ('app_version','app_version_prev')")}


def set_meta(k, v):
    if v is None:
        dbx("DELETE FROM kalmido_meta WHERE key=?", (k,), write=True)
    else:
        dbx("INSERT INTO kalmido_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v), write=True)


def start(keep=True, extra=(), env=None):
    """start.sh; True when the server answered."""
    e = dict(os.environ, EXTRA=" ".join(extra))
    e.pop("KEEP", None)
    if keep:
        e["KEEP"] = "1"
    e.update(env or {})
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    return r.returncode == 0


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-300:]


def admin():
    return login(B, "alice")


if not (os.environ.get("P2149D_NOSTART") or os.environ.get("KMT_NOSTART")):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    assert start(keep=False), logs()[-2000:]
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = admin()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
VER = A.get(B + "/api/admin/health").json()["version"]
MAJ, MIN, PAT = (int(x) for x in VER.split("."))
NEWER = f"{MAJ}.{MIN + 1}.0"
OLDER = f"{MAJ}.{max(0, MIN - 1)}.3"

# ---- #2509: the stamp of a new database
m = meta()
check(m.get("app_version") == VER and "app_version_prev" not in m, f"new database stamped: app_version {VER}, no prev {m}")

# appver_check in the app
res = in_app("from kalmido.core.db import appver_check as a\n"
             "print(json.dumps([a('2.150.3', None, '2.150.0'), a('2.151.0', None, '2.150.0'), a('2.151.0', '2.150.0', '2.150.0'),"
             " a('2.151.0', '2.150.2', '2.150.0'), a('2.152.0', '2.151.0', '2.150.0'), a('3.0.0', None, '2.150.0'),"
             " a('2.149.0', None, '2.150.0'), a(None, None, '2.150.0'), a('2.151.0', None, '0.0.0')]))")
check(res == json.dumps(["ok", "newer", "back", "back", "newer", "newer", "ok", "ok", "ok"]), f"appver_check: patch / newer / one step back / major: {res}")

# a database a newer minor ran on: refused
set_meta("app_version", NEWER)
set_meta("app_version_prev", None)
ok = start()
lg = logs()
check(not ok and "FATAL: this database last ran Kalmido " + NEWER in lg and "KALMIDO_ALLOW_DOWNGRADE" in lg,
      f"newer minor: start refused with a clear message ({ok}, {lg[-300:]!r})")
# the emergency switch
ok = start(extra=("-e KALMIDO_ALLOW_DOWNGRADE=1",))
check(ok and "WARNING: this database last ran Kalmido " + NEWER in logs(), "KALMIDO_ALLOW_DOWNGRADE=1: starts with a warning")
check(meta().get("app_version") == NEWER, f"the downgrade keeps the newer stamp {meta()}")
# the one step back (the version before the last upgrade)
set_meta("app_version_prev", VER)
ok = start()
check(ok and "as a step back" in logs(), "app_version_prev = this version: the step back starts without the switch")
check(meta() == {"app_version": NEWER, "app_version_prev": VER}, f"the step back changes no stamp {meta()}")
# an upgrade from an older version
set_meta("app_version", OLDER)
set_meta("app_version_prev", None)
check(start(), "older stamp: starts")
check(meta() == {"app_version": VER, "app_version_prev": OLDER}, f"upgrade: app_version {VER}, prev {OLDER}: {meta()}")
# a newer patch of the same minor
PATCH = f"{MAJ}.{MIN}.{PAT + 5}"
set_meta("app_version", PATCH)
check(start() and meta().get("app_version") == PATCH, f"a newer patch of the same minor starts and keeps its stamp {meta()}")
set_meta("app_version", VER)
set_meta("app_version_prev", OLDER)

# ---- #2511: TASKS_WATCHDOG read like every switch
for val, want in (("true", True), ("0", False), (None, True)):
    check(start(extra=(f"-e TASKS_WATCHDOG={val}",) if val is not None else ()), f"TASKS_WATCHDOG={val}: starts")
    loops = admin().get(B + "/api/admin/health").json().get("loops") or {}
    check(("watchdog" in loops) is want, f"TASKS_WATCHDOG={val}: watchdog loop {'on' if want else 'off'} ({sorted(loops)})")
A = admin()


# ---- #2509: restore of a newer backup
def make_zip(app_version):
    dump = b"not a real dump"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("kalmido.dump", dump)
        z.writestr("manifest.json", json.dumps({"format": "kalmido-backup", "format_version": 2, "app_version": app_version,
                                                "schema_version": 2, "created_at": "2026-01-01T00:00:00+00:00", "kind": "manual",
                                                "counts": {}, "files": [["kalmido.dump", len(dump), hashlib.sha256(dump).hexdigest()]]}))
    return buf.getvalue()


def upload(data, s=None):
    return (s or A).post(B + "/api/admin/backups/upload", data=data, headers={"Content-Type": "application/octet-stream"})


r = upload(make_zip(NEWER))
check(r.status_code == 400 and r.json().get("code") == "newer" and NEWER in r.json().get("error", ""),
      f"restore: a backup of a newer minor is refused (newer): {r.status_code} {r.text[:200]}")
r = upload(make_zip(OLDER))
check(r.json().get("code") != "newer", f"restore: an older backup is not refused for its version: {r.status_code} {r.text[:160]}")
r = upload(make_zip(f"{MAJ}.{MIN}.{PAT + 9}"))
check(r.json().get("code") != "newer", f"restore: a newer patch of the same minor is not refused for its version: {r.text[:160]}")
FID, Fr = freelancer(B, A)  # freelancer-matrix: admin (a person without an organisation is no server admin)
check(upload(make_zip(OLDER), Fr).status_code == 403, "a person without an organisation: the server's backups 403")
check(start(extra=("-e KALMIDO_ALLOW_DOWNGRADE=1",)), "start with KALMIDO_ALLOW_DOWNGRADE=1")
r = upload(make_zip(NEWER), admin())
check(r.json().get("code") != "newer", f"KALMIDO_ALLOW_DOWNGRADE=1: the newer backup passes the version check: {r.text[:160]}")

# ---- #2510: server key
ok = start(keep=False, env={"KALMIDO_NO_SECRET_KEY": ""})
lg = logs()
check(not ok and "FATAL: no server key (no key is set)" in lg and "KALMIDO_NO_SECRET_KEY=1" in lg,
      f"a new database without a key: start refused ({ok}, {lg[-300:]!r})")
shutil.rmtree(SEC, ignore_errors=True)
os.makedirs(SEC)
FILE_ARGS = ("-e KALMIDO_SECRET_FILE=/secret/kalmido.key", f"-v {SEC}:/secret")
ok = start(keep=False, extra=FILE_ARGS, env={"KALMIDO_NO_SECRET_KEY": ""})
check(ok and os.path.isfile(KEYF), "a new database with a key file: starts, the key is created")
KEY = open(KEYF).read()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
uid = dbx("SELECT id FROM users WHERE username='alice'")[0][0]
if not dbx("SELECT 1 FROM user_keys WHERE user_id=?", (uid,)):  # a key row as the encryption writes it (contents invented)
    dbx("INSERT INTO user_keys(user_id, wrapped, kek_check, created_at) VALUES(?,?,?,?)",
        (uid, "v1." + base64.urlsafe_b64encode(os.urandom(60)).decode().rstrip("="), "0" * 32, "2026-10-21T10:00:00+00:00"), write=True)
    fake = True
else:
    fake = False
os.remove(KEYF)
ok = start(extra=FILE_ARGS, env={"KALMIDO_NO_SECRET_KEY": ""})
lg = logs()
check(not ok and "a new server key would have been created" in lg, f"lost key file next to sealed data: start refused ({ok}, {lg[-300:]!r})")
check(not os.path.exists(KEYF), "... and the new key file is removed again")
with open(KEYF, "w") as f:
    f.write(KEY)
os.chmod(KEYF, 0o600)
check(start(extra=FILE_ARGS, env={"KALMIDO_NO_SECRET_KEY": ""}), "the old key file back: starts")
if fake:
    dbx("DELETE FROM user_keys WHERE user_id=?", (uid,), write=True)
check(start(extra=FILE_ARGS + ("-e PUBLIC_URL=",)) and "WARNING: PUBLIC_URL is not set" in logs(), "PUBLIC_URL unset: warning in the log")

# ---- #2510: a data folder without write access
if hasattr(os, "geteuid") and os.geteuid() != 0:
    ro = os.path.join(DATA, "ro")
    os.makedirs(ro, exist_ok=True)
    os.chmod(ro, 0o555)
    ok = start(extra=("-e TASKS_DB=/data/ro/tasks.db",))
    lg = logs()
    check(not ok and "FATAL: the data folder /data/ro is not writable" in lg and "Traceback" not in lg,
          f"unwritable data folder: clear FATAL, no traceback ({ok}, {lg[-300:]!r})")
    os.chmod(ro, 0o755)
else:
    print("(running as root: the write-access check is skipped)")
shutil.rmtree(SEC, ignore_errors=True)

print(f"p2149_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
