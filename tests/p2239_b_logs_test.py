#!/usr/bin/env python3
"""2.239.0 API tests, part B (#2888): the server log without full addresses, names or database values. Own container
(start.sh). Invented names only, addresses @example.com / documentation ranges.
 - a failed sign-in: the line keeps its text, the address is shortened (IPv4 /24, IPv6 /48), the typed name is not there
 - a registration (approval) and a sign-in link: shortened address, the account by number, never its name or e-mail
 - an admin creating an organisation: "created by user #<id>", neither the admin's name nor the organisation's
 - the helpers in a fresh process: login_log_ip (IPv4 / IPv6 / mapped / empty / not an address), KALMIDO_LOG_FULL_IP=1
   keeps the full address, login_log_who
 - a database error (a duplicate e-mail, a rejected value): the 400 handler and the 500 log keep the frames, the SQLSTATE
   and the constraint, but not the value (str(e) has it - the test would see it without the fix)
 - a person without an organisation (freelancer-matrix: account): failed + correct sign-in and a sign-in link as before,
   logged by number
usage: p2239_b_logs_test.py <datadir>      (a fresh container; P2239B_NOSTART=1 = the server already runs)"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, CT, H, check, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(prefix="P2239B")
A = kt.setup()
AID = A.get(B + "/api/state").json()["me"]["id"]


def _streams():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout, r.stderr


def logs():
    """A mark in the server log: the length of its stdout and stderr."""
    o, e = _streams()
    return len(o), len(e)


def since(n):
    """What the server logged after the mark n (both streams)."""
    o, e = _streams()
    return o[n[0]:] + "\n" + e[n[1]:]


def can_login(user, pw="password123"):
    return anon().post(B + "/api/auth/login", json={"username": user, "password": pw}).ok


def wait_line(n, needle):
    """The new log lines with needle (waits until one is there)."""
    return until(lambda: [x for x in since(n).splitlines() if needle in x], 10) or []


def box(code, env=None):
    """Python inside the app container (a fresh process) -> its JSON output."""
    cmd = ["docker", "exec"] + [a for k, v in (env or {}).items() for a in ("-e", f"{k}={v}")] + [CT, "python", "-c", "import app\n" + code]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = [x for x in r.stdout.splitlines() if x.startswith("@@")]
    assert r.returncode == 0 and out, r.stdout[-1500:] + r.stderr[-1500:]
    return json.loads(out[-1][2:])


def anon():
    s = requests.Session()
    s.headers.update(H)
    return s


# ================================================================== a failed sign-in
n0 = logs()
r = anon().post(B + "/api/auth/login", json={"username": "Wrongname2239", "password": "x"}, headers={"X-Forwarded-For": "203.0.113.77"})
check(r.status_code == 401, f"a failed sign-in: 401 {r.status_code}")
ln = wait_line(n0, "login failed for")
check(ln and ln[-1].rstrip().endswith("from 203.0.113.x") and "203.0.113.77" not in since(n0) and "Wrongname2239" not in since(n0)
      and "wrongname2239" not in since(n0), f"#2888: the failed sign-in line has the shortened address, no name {ln[-1:]}")
n0 = logs()
anon().post(B + "/api/auth/login", json={"username": "Wrongname2239", "password": "y"}, headers={"X-Forwarded-For": "2001:db8:1:2::5"})
ln = wait_line(n0, "login failed for")
check(ln and ln[-1].rstrip().endswith("from 2001:db8:1::/48") and "2001:db8:1:2::5" not in since(n0),
      f"#2888: an IPv6 address is cut to its /48 {ln[-1:]}")

# ================================================================== a registration and a sign-in link
check(A.patch(B + "/api/admin/settings", json={"signup_mode": "approval"}).ok, "approval mode")
n0 = logs()
r = anon().post(B + "/api/auth/signup", json={"name": "Ines Probe", "email": "ines2239@example.com", "password": "ines-secret-1"},
                headers={"X-Forwarded-For": "198.51.100.23"})
check(r.ok, f"a registration {r.status_code} {r.text[:150]}")
ln = wait_line(n0, "registration:")
check(ln and "from 198.51.100.x" in ln[-1] and "198.51.100.23" not in since(n0) and "ines2239" not in since(n0),
      f"#2888: the registration line: shortened address, no e-mail {ln[-1:]}")
ines = kt.dbx("SELECT id FROM users WHERE email='ines2239@example.com'")
check(ines and A.post(B + f"/api/users/{ines[0][0]}/approve").ok, "the admin approves the registration")
check(can_login("ines2239", "ines-secret-1"), "the approved person signs in as before")


def link_token(uid):
    r = A.post(B + f"/api/users/{uid}/signin-link", json={})
    assert r.ok, r.text
    return r.json()["link"].rsplit("/", 1)[1]


n0 = logs()
r = anon().post(B + "/api/auth/link", json={"token": link_token(ines[0][0])}, headers={"X-Forwarded-For": "198.51.100.24"})
check(r.ok and r.json().get("ok"), "a sign-in link works " + r.text[:150])
ln = wait_line(n0, "signed in with a sign-in link:")
check(ln and f"user #{ines[0][0]} from 198.51.100.x" in ln[-1] and "ines2239" not in since(n0) and "198.51.100.24" not in since(n0),
      f"#2888: the sign-in link line names the account by number {ln[-1:]}")

# ================================================================== an admin's action
n0 = logs()
r = A.post(B + "/api/admin/orgs", json={"name": "Nordlicht Probe 2239"})
check(r.ok, f"an organisation {r.status_code} {r.text[:150]}")
ln = wait_line(n0, "created by")
check(ln and ln[-1].rstrip().endswith(f"created by user #{AID}") and "alice" not in since(n0) and "Nordlicht Probe 2239" not in since(n0),
      f"#2888: the admin and the organisation by number only {ln[-1:]}")

# ================================================================== the helpers (a fresh process)
CODE = """from kalmido.accounts.login import login_log_ip as f, login_log_who as w
print("@@" + __import__("json").dumps([f("203.0.113.77"), f("2001:db8:1:2::5"), f("::ffff:198.51.100.9"), f(""), f(None),
      f("not an address <x>"), w({"id": 7}), w(7), w(None)]))"""
check(box(CODE) == ["203.0.113.x", "2001:db8:1::/48", "198.51.100.x", "-", "-", "?", "user #7", "user #7", "user #?"],
      f"#2888: login_log_ip shortens by default, login_log_who {box(CODE)}")
full = box(CODE, {"KALMIDO_LOG_FULL_IP": "1"})
check(full[:6] == ["203.0.113.77", "2001:db8:1:2::5", "::ffff:198.51.100.9", "-", "-", "?"], f"#2888: KALMIDO_LOG_FULL_IP=1 keeps the address {full}")
check(box(CODE, {"KALMIDO_LOG_FULL_IP": "0"})[0] == "203.0.113.x", "KALMIDO_LOG_FULL_IP=0: shortened")

# ================================================================== database errors without values
DBE = """import contextlib, io, json, logging
from kalmido.core.config import app as fl
from kalmido.core.db import DataError, IntegrityError, connect, db_error, db_log_err
c = connect()
c.execute("CREATE TEMP TABLE t2239 (mail text CONSTRAINT t2239_mail_key UNIQUE)")
c.execute("INSERT INTO t2239 VALUES ('dup2239@example.com')")
try:
    c.execute("INSERT INTO t2239 VALUES ('DUP2239@example.com'), ('dup2239@example.com')")
except IntegrityError as x:
    ie = x
c.rollback()
try:
    c.execute("SELECT 'abc2239'::int")
except DataError as x:
    de = x
c.rollback()
buf, lb = io.StringIO(), io.StringIO()
h = logging.StreamHandler(lb)
logging.getLogger(fl.name).addHandler(h)
with fl.test_request_context("/api/probe", method="POST"), contextlib.redirect_stdout(buf):
    code = db_error(ie)[1]
    fl.log_exception((type(de), de, de.__traceback__))
print("@@" + json.dumps({"raw": str(ie), "raw_de": str(de), "ie": db_log_err(ie), "de": db_log_err(de), "out": buf.getvalue(),
                         "log": lb.getvalue(), "code": code, "other": db_log_err(ValueError("plain"))}))"""
d = box(DBE)
check("dup2239@example.com" in d["raw"] and "abc2239" in d["raw_de"], "the psycopg texts carry the values (what the fix keeps out)")
check("dup2239" not in d["ie"] and "23505" in d["ie"] and "t2239_mail_key" in d["ie"] and d["ie"].startswith("UniqueViolation:"),
      f"#2888: db_log_err of a duplicate: SQLSTATE + constraint, no value {d['ie']}")
check("abc2239" not in d["de"] and "22P02" in d["de"], f"#2888: db_log_err of a rejected value: no value {d['de']}")
check(d["code"] == 400 and "database error (400) POST /api/probe:" in d["out"] and "Traceback" in d["out"] and "File " in d["out"]
      and "dup2239" not in d["out"].lower() and "DETAIL" not in d["out"] and "t2239_mail_key" in d["out"],
      f"#2888: the 400 handler logs frames, not the duplicate e-mail {d['out'][-400:]}")
check("Exception on /api/probe [POST]" in d["log"] and "File " in d["log"] and "abc2239" not in d["log"] and "22P02" in d["log"],
      f"#2888: an uncaught database error (500) logs without the value {d['log'][-400:]}")
check(d["other"] == "ValueError: plain", "other errors: class and text as before")

# ================================================================== a person without an organisation
# freelancer-matrix: account
FID, Fr = freelancer(B, A)
n0 = logs()
r = anon().post(B + "/api/auth/login", json={"username": "frida", "password": "wrong-2239"}, headers={"X-Forwarded-For": "192.0.2.41"})
check(r.status_code == 401, "freelancer: a wrong password 401")
ln = wait_line(n0, "login failed for")
check(ln and ln[-1].rstrip().endswith("from 192.0.2.x") and "frida" not in since(n0), f"freelancer: the failed sign-in is logged shortened {ln[-1:]}")
check(can_login("frida"), "freelancer: signs in as before")
n0 = logs()
r = anon().post(B + "/api/auth/link", json={"token": link_token(FID)})
check(r.ok and r.json().get("ok"), "freelancer: a sign-in link works " + r.text[:150])
ln = wait_line(n0, "signed in with a sign-in link:")
check(ln and f"user #{FID} " in ln[-1] and "frida" not in since(n0), f"freelancer: the sign-in link line by number {ln[-1:]}")

sys.exit(kt.done("p2239_b_logs"))
