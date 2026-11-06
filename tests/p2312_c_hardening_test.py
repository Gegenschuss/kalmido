#!/usr/bin/env python3
"""2.312.0 C (#3265): hardening rest of 2.306, own container (start.sh). Invented accounts only (example.com). One case per rule:
 - (the ntfy share inbox: parallel polls, old http:// inboxes - 2.574.0 #3779: the inbox is gone, its route is a 404)
 - the sign-in exception "known address" (the per-name ceiling skipped for an address the account signed in from) holds
   for every process: remembered by one process, used by another with an empty memory; another address stays limited
 - saved number schemes with more than four text building blocks are reported at the start (log line + admin alert),
   nothing is changed; four blocks are fine
freelancer-matrix: ntfy_inbox (2.574.0: the route is gone for them too), core_hardening (the sign-in), office (the personal office's scheme is reported too)
usage: p2312_c_hardening_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time

import kt
from kt import B, CT, check, sess, until

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
ENV = {}


def dbw(q, a=()):
    """A write in the suite's database (committed)."""
    c = kt._dbx.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(q, a)
        c.commit()
    finally:
        c.close()


def py(code, env=None):
    """Runs code in a second process of the container (no loops, role web); the last line of its output = JSON."""
    extra = []
    for k, v in {"TASKS_WATCHDOG": "0", "KALMIDO_ROLE": "web", **(env or {})}.items():
        extra += ["-e", f"{k}={v}"]
    for _try in range(3):  # the import may meet the running server's start-up DDL (deadlock): try again
        r = subprocess.run(["docker", "exec", "-w", "/app", *extra, CT, "python", "-c", "import app\n" + code],
                           capture_output=True, text=True)
        if "DeadlockDetected" not in r.stdout + r.stderr:
            break
        time.sleep(2)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print((r.stdout + r.stderr)[-2000:], flush=True)
        return {}


kt.fresh(env=ENV)
A = kt.sess(None)
assert A.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments", "office"]})
A = sess("alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol"):  # bob first: the lower id, the one a round one after the other would poll first
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com", "orgs": [{"id": ORG, "role": "member"}]})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
FID, Fr = freelancer(B, A)
Bo, Ca = sess("bob"), sess("carol")

# ================================================================ 1./2. the ntfy share inbox (parallel polls, old http:// inboxes)
# 2.574.0 (#3779): the share inbox is gone (decided 30.10.2026), its two cases with it: the route answers 404 for everyone
for who, s_ in (("member", Bo), ("freelancer", Fr)):
    check(s_.get(B + "/api/me/ntfy-inbox").status_code == 404, f"#3779: {who}: no share inbox any more")

# ================================================================ 3. the known sign-in address holds for every process
KN = """
import json
from kalmido.core.config import app as fl
from kalmido.accounts import session as S
out = []
for ip, what in {steps}:
    with fl.test_request_context("/", environ_base={{"REMOTE_ADDR": ip}}):
        out.append(S._rate_reset("{name}") if what == "ok" else S._rate_fail([("uall:{name}", 3)]) if what == "fail"
                   else S._rate_blocked([("uall:{name}", 3)]))
print(json.dumps(out))
"""
HOME, OTHER, ATT = "203.0.113.20", "198.51.100.8", "198.51.100.7"
py(KN.format(name="p2312kn", steps=[(HOME, "ok")]))  # process 1: a successful sign-in from HOME
q = py(KN.format(name="p2312kn", steps=[(ATT, "fail")] * 3 + [(HOME, "blocked"), (OTHER, "blocked")]))  # process 2: an empty memory
check(isinstance(q, list) and q[3:] == [False, True], f"another process skips the per-name ceiling for the known address, not for another one {q}")
q = py(KN.format(name="p2312new", steps=[(ATT, "fail")] * 3 + [(HOME, "blocked")]))
check(isinstance(q, list) and q[3:] == [True], f"without a sign-in from there the ceiling applies {q}")
check(not kt.dbx("SELECT 1 FROM rate_known WHERE u LIKE '%p2312%' OR a LIKE '%p2312%' OR a LIKE '%203.0.113%'")
      and kt.dbx("SELECT COUNT(*) FROM rate_known")[0][0] >= 1, "the shared table stores hashes only")
check(sess("frida").get(B + "/api/me").ok, "freelancer: a normal sign-in works with the shared table")

# ================================================================ 4. number schemes with more than four text blocks: reported at the start
r = Fr.put(B + "/api/office/settings", json={"company_fields": {"name": "Frida Studio"}})
check(r.ok, "freelancer: the personal office " + r.text[:120])
FOFF = [x[0] for x in kt.dbx("SELECT id FROM orgs WHERE personal_of=?", (FID,))]
check(FOFF and kt.dbx("SELECT 1 FROM office_settings WHERE org_id=?", (FOFF[0],)), f"the freelancer's personal office {FOFF}")
dbw("INSERT INTO office_settings(org_id, data, updated_at) VALUES(?, '{}', '2026-10-26T00:00:00Z') ON CONFLICT(org_id) DO NOTHING", (ORG,))
LONG = "{project}-{client}-{initials}-{project}-{client}-{seq:03}"
OK4 = "{project}-{client}-{initials}-{project}-{seq:03}"
for oid, k, v in ((ORG, "invoice_scheme", LONG), (ORG, "offer_scheme", OK4), (FOFF[0], "credit_scheme", LONG)):
    d = json.loads(kt.dbx("SELECT data FROM office_settings WHERE org_id=?", (oid,))[0][0] or "{}")
    d[k] = v
    dbw("UPDATE office_settings SET data=? WHERE org_id=?", (json.dumps(d), oid))
kt.fresh(env={**ENV, "KALMIDO_ADMIN_ALERTS": "1"}, keep=True)  # start.sh switches admin alerts off
al = until(lambda: kt.dbx("SELECT key, kind FROM admin_alerts WHERE key LIKE 'onclong:%'"), timeout=90)  # the alert queue goes out every 30 s
check(al and al[0][1] == "storage", f"an admin alert under storage and health {al}")
key = al[0][0] if al else ""
check(f"{ORG}:invoice_scheme" in key and f"{FOFF[0]}:credit_scheme" in key and "offer_scheme" not in key,
      f"it names the office areas and settings with more than four blocks (four are fine) {key}")
logs = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
check("2 number scheme(s) with more than four text building blocks" in logs.stdout + logs.stderr, "a warning in the log")
d = json.loads(kt.dbx("SELECT data FROM office_settings WHERE org_id=?", (ORG,))[0][0])
check(d.get("invoice_scheme") == LONG, "the scheme itself is not changed")
A = sess("alice")
r = A.get(B + "/api/admin/alerts")
check(r.ok and "more than four text building blocks" in r.text, f"the admin sees it in the alerts list ({r.status_code})")

print(f"p2312_c_hardening: {kt.OKS[0]} ok, {len(kt.FAILS)} failed", flush=True)
sys.exit(1 if kt.FAILS else 0)
