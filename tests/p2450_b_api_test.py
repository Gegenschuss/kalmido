#!/usr/bin/env python3
"""2.45.0 API tests, part B (#1515 self-hosting), own containers (start.sh with its own settings). Invented names only.
 - one-time setup code: while no account exists the server prints a code into its log; POST /api/auth/setup without it,
   with a wrong one = 403; the right one (blanks, dashes, capitals do not matter) creates the admin; afterwards 409 as
   before, GET /api/auth/info says setup_code false; a restart with an account prints no code
 - KALMIDO_SETUP_CODE=<fixed> takes exactly that code; KALMIDO_SETUP_CODE=off (start.sh's default) needs none
 - wrong codes are rate limited per address (429 after 10, then even the right code waits) -- last, it locks the address
 - server key file KALMIDO_SECRET_FILE: created once (mode 0600, 32 bytes base64), reused on a restart, the variable
   KALMIDO_SECRET_KEY wins, a file inside the data folder is refused; the admin sees secret_key / secret_key_problem
 - a new server backs up daily (bk_on after the first setup, first automatic backup tomorrow)
usage: p2450_b_api_test.py <datadir>"""
import base64
import os
import stat
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402

DATA = os.path.abspath(sys.argv[1])
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
SEC = DATA.rstrip("/") + "-secret"  # next to the data dir, never inside it
KEYF = os.path.join(SEC, "kalmido.key")
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)
USER = {"username": "alice", "display_name": "Alice", "password": "password123"}


def start(code=None, keep=False, extra=()):
    """start.sh with KALMIDO_SETUP_CODE=code (None = start.sh's default off) and extra docker arguments."""
    env = dict(os.environ, EXTRA=" ".join(extra))
    env.pop("KEEP", None)
    if keep:
        env["KEEP"] = "1"
    if code is None:
        env.pop("KALMIDO_SETUP_CODE", None)
    else:
        env["KALMIDO_SETUP_CODE"] = code
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, check=True, stdout=subprocess.DEVNULL)


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def log_code():
    for ln in logs().splitlines():
        if "Setup code:" in ln:
            return ln.split("Setup code:", 1)[1].strip()
    return ""


def setup(code=None, **kw):
    b = dict(USER, **kw)
    if code is not None:
        b["setup_code"] = code
    return requests.post(B + "/api/auth/setup", headers=H, json=b)


def login():
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"})
    assert r.ok, r.text
    return s


def about(s):
    return s.get(B + "/api/state").json()["about"]


def info():
    return requests.get(B + "/api/auth/info").json()


os.makedirs(SEC, exist_ok=True)
os.chmod(SEC, 0o777)  # the container runs as the caller's uid; (777: rootless setups map it elsewhere)
if os.path.exists(KEYF):
    os.remove(KEYF)
FILE_ARGS = ("-e KALMIDO_SECRET_FILE=/secret/kalmido.key", f"-v {SEC}:/secret")

# ---- 1. random code, key file created
start(code="", extra=FILE_ARGS)
code = log_code()
check(len(code.replace("-", "")) == 12, f"the log shows a setup code: {code!r}")
j = info()
check(j["setup"] is True and j["setup_code"] is True, f"auth/info: setup + setup_code {j.get('setup')} {j.get('setup_code')}")
r = setup()
check(r.status_code == 403, f"setup without the code = 403: {r.status_code}")
r = setup("abcd-efgh-jkmn")
check(r.status_code == 403 and "log" in r.json().get("error", ""), f"wrong code = 403 with a hint at the log: {r.status_code} {r.text[:120]}")
check(not dbx.connect(DATA).execute("SELECT 1 FROM users").fetchone(), "no account after wrong codes")
check(logs().count(code) == 1, "the code is in the log once (wrong tries never print it)")
r = setup(" " + code.upper().replace("-", " - ") + " ")
check(r.ok, f"the right code (capitals, blanks) creates the admin: {r.status_code} {r.text[:120]}")
r = setup(code)
check(r.status_code == 409, f"the code again: setup is done (409): {r.status_code}")
j = info()
check(j["setup"] is False and j["setup_code"] is False, "auth/info after the setup: no code asked")
A = login()
check(os.path.isfile(KEYF) and stat.S_IMODE(os.stat(KEYF).st_mode) == 0o600, "key file created with mode 0600")
KEY = open(KEYF).read().strip()
check(len(base64.b64decode(KEY)) == 32, "key file: 32 bytes, base64")
check("A new server key was created" in logs(), "the log says a key was created")
a = about(A)
check(a.get("secret_key") is True and a.get("secret_key_src") == "file" and a.get("secret_key_problem") == "", f"admin: key from the file {a}")
# the key works: organisation encryption can be switched on (needs the server key)
check(A.get(B + "/api/admin/orgcrypt").json().get("enabled") is True, "organisation encryption available with the file key")

# ---- 2. backups on for the new server
bk = A.get(B + "/api/admin/backups").json()
today = datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
check(bk["on"] is True and bk["items"] == [], f"a new server backs up daily: {bk['on']}")
check(dbx.connect(DATA).execute("SELECT value FROM settings WHERE key='bk_last_day'").fetchone()[0] == today,
      "first automatic backup tomorrow (not of the empty server)")

# ---- 3. restart: the same key, no setup code (an account exists)
start(code="", keep=True, extra=FILE_ARGS)
check(open(KEYF).read().strip() == KEY, "restart: the key file is reused unchanged")
check("A new server key was created" not in logs() and not log_code(), "restart: no new key, no setup code in the log")
A = login()
check(about(A).get("secret_key_src") == "file", "restart: key from the file")
# an admin who switched backups off keeps that (the default only applies to a new server)
A.patch(B + "/api/admin/backups", json={"on": False})
start(keep=True, extra=FILE_ARGS)
A = login()
check(A.get(B + "/api/admin/backups").json()["on"] is False, "backups switched off stay off after a restart")

# ---- 4. the variable wins over the file
ENVKEY = base64.b64encode(bytes(range(32))).decode()
start(keep=True, extra=FILE_ARGS + (f"-e KALMIDO_SECRET_KEY={ENVKEY}",))
A = login()
check(about(A).get("secret_key_src") == "env", "KALMIDO_SECRET_KEY wins over the file")
check(open(KEYF).read().strip() == KEY, "the file stays untouched")

# ---- 5. no key: the admin is warned
start(keep=True)
A = login()
a = about(A)
check(a.get("secret_key") is False and a.get("secret_key_problem") == "unset", f"no key: secret_key false, problem unset {a.get('secret_key_problem')}")
check("WARNING: no server key" in logs(), "no key: warning in the log")

# ---- 6. a key file inside the data folder is refused (a backup would carry it)
start(keep=True, extra=("-e KALMIDO_SECRET_FILE=/data/kalmido.key",))
A = login()
check(about(A).get("secret_key_problem") == "file_in_data", "key file inside /data: refused")
check(not os.path.exists(os.path.join(DATA, "kalmido.key")), "... and not created")
# an invalid key file
open(os.path.join(SEC, "bad.key"), "w").write("not a key\n")
start(keep=True, extra=("-e KALMIDO_SECRET_FILE=/secret/bad.key", f"-v {SEC}:/secret"))
A = login()
check(about(A).get("secret_key_problem") == "invalid", "invalid key file: problem invalid")

# ---- 7. fixed code for automation; off needs none
start(code="Fixed-Setup-Code-42")
check(not log_code(), "fixed code: not printed")
check(setup("wrong").status_code == 403, "fixed code: a wrong one = 403")
check(setup("fixed-setup-code-42").ok, "fixed code: the configured one works")
start()
check(info()["setup_code"] is False, "KALMIDO_SETUP_CODE=off: no code asked")
check(setup().ok, "KALMIDO_SETUP_CODE=off: setup without a code (the other suites)")

# ---- 8. rate limit (last: it locks this address for the login window)
start(code="")
code = log_code()
codes = [setup("wrong-%02d" % i).status_code for i in range(11)]
check(codes[0] == 403 and codes[9] == 403 and codes[10] == 429, f"wrong codes are rate limited: {codes}")
check(setup(code).status_code == 429, "while locked even the right code waits")
check(not dbx.connect(DATA).execute("SELECT 1 FROM users").fetchone(), "still no account")

print(f"p2450_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
