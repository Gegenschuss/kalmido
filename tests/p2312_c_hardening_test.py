#!/usr/bin/env python3
"""2.312.0 C (#3265): hardening rest of 2.306, own container (start.sh, a tiny ntfy server inside: stub_ntfyin.py). Invented
accounts only (example.com). One case per rule:
 - the ntfy share inbox polls people at the same time: a person whose server hangs does not hold another person's poll
   (the other one's message arrives while the slow request is still open); the slow one still arrives later
 - an existing inbox on an own server over http:// to a host no admin allowed: the settings answer says so (a hint, it
   keeps running); https:// or an allowed host: no hint; saving it unchanged still works, a new such address is refused
 - the sign-in exception "known address" (the per-name ceiling skipped for an address the account signed in from) holds
   for every process: remembered by one process, used by another with an empty memory; another address stays limited
 - saved number schemes with more than four text building blocks are reported at the start (log line + admin alert),
   nothing is changed; four blocks are fine
freelancer-matrix: ntfy_inbox (the own inbox, the hint), core_hardening (the sign-in), office (the personal office's scheme is reported too)
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
STUB = "http://127.0.0.1:8099"
ENV = {"KALMIDO_CALENDAR_ALLOW_HOSTS": "127.0.0.1:8099", "KALMIDO_NTFYIN_TICK": "1"}


def dbw(q, a=()):
    """A write in the suite's database (committed)."""
    c = kt._dbx.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(q, a)
        c.commit()
    finally:
        c.close()


def stub_start():
    subprocess.run(["cp", os.path.join(N, "stub_ntfyin.py"), kt.DATA])
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_ntfyin.py"])
    until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import urllib.request; urllib.request.urlopen('" + STUB + "/x/json?poll=1')"],
                                 capture_output=True).returncode == 0, timeout=15)


def publish(msgs):
    with open(os.path.join(kt.DATA, "ntfyin_msgs.json"), "w") as f:
        json.dump(msgs, f)


def stub_log():
    p = os.path.join(kt.DATA, "ntfyin.log")
    return [json.loads(x) for x in open(p).read().splitlines() if x.strip()] if os.path.exists(p) else []


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
stub_start()
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

# ================================================================ 1. the ntfy inbox: one slow server holds nobody else
SLOW, FAST = "slow-bobs-share-topic-12345", "carols-share-topic-1234567"
publish([{"topic": SLOW, "id": "s1", "message": "Shared by bob slowly"}, {"topic": FAST, "id": "c1", "message": "Shared by carol"}])
r = Bo.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": SLOW, "url": STUB})
check(r.ok, "bob on (slow server) " + r.text[:120])
check(until(lambda: [x for x in stub_log() if SLOW in x["path"] and not x.get("end")], timeout=20), "bob's slow poll has started")
r = Ca.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": FAST, "url": STUB})
check(r.ok, "carol on " + r.text[:120])
got = until(lambda: kt.dbx("SELECT created_by FROM tasks WHERE title='Shared by carol'"), timeout=30)
check(got and got[0][0] == uid["carol"], f"carol's message arrives {got}")
log = stub_log()
slow_end = min([x["t"] for x in log if SLOW in x["path"] and x.get("end")] or [float("inf")])
fast_at = min([x["t"] for x in log if FAST in x["path"] and not x.get("end")] or [float("inf")])
check(fast_at < slow_end, f"carol is polled while bob's slow request is still open (carol {fast_at}, bob's end {slow_end})")
got = until(lambda: kt.dbx("SELECT created_by FROM tasks WHERE title='Shared by bob slowly'"), timeout=45)
check(got and got[0][0] == uid["bob"], f"bob's message still arrives from the slow server {got}")
n = len([x for x in stub_log() if SLOW in x["path"] and not x.get("end")])
check(n <= len([x for x in stub_log() if SLOW in x["path"] and x.get("end")]) + 1, f"bob is never polled twice at the same time ({n} starts)")
Bo.put(B + "/api/me/ntfy-inbox", json={"enabled": False})
Ca.put(B + "/api/me/ntfy-inbox", json={"enabled": False})

# freelancer-matrix: ntfy_inbox
r = Fr.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "url": STUB})
check(r.ok, "freelancer: inbox on " + r.text[:120])
ft = r.json().get("topic", "")
publish([{"topic": ft, "id": "f1", "message": "Frida shares"}])
got = until(lambda: kt.dbx("SELECT created_by FROM tasks WHERE title='Frida shares'"), timeout=30)
check(got and got[0][0] == FID, "freelancer: the message arrives in the own basket")
Fr.put(B + "/api/me/ntfy-inbox", json={"enabled": False})

# ================================================================ 2. old inboxes over http:// to a host no admin allowed: a hint
dbw("UPDATE ntfy_inboxes SET url='http://ntfy.example.com', enabled=1 WHERE user_id=?", (uid["bob"],))
g = Bo.get(B + "/api/me/ntfy-inbox").json()
check(g.get("insecure") is True and g.get("enabled") is True, f"an http:// server of a host nobody allowed: the hint, still on {g}")
r = Bo.put(B + "/api/me/ntfy-inbox", json={"enabled": True})
check(r.ok and r.json().get("insecure") is True, "saving it unchanged still works (nothing is switched off) " + r.text[:120])
r = Bo.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "url": "http://other.example.com"})
check(r.status_code == 400 and "https://" in r.text, "a new http:// address of such a host: the message of 2.306 " + r.text[:120])
r = Bo.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "url": "https://ntfy.example.com"})
check(r.ok and r.json().get("insecure") is False, "https://: no hint " + r.text[:120])
r = Ca.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "url": STUB})
check(r.ok and r.json().get("insecure") is False, "http:// to a host an admin allowed: no hint " + r.text[:120])
check(Ca.get(B + "/api/me/ntfy-inbox").json().get("insecure") is False and "insecure" in Ca.get(B + "/api/me/ntfy-inbox").json(),
      "the field is in every answer")
for s_ in (Bo, Ca):
    s_.put(B + "/api/me/ntfy-inbox", json={"enabled": False})
dbw("UPDATE ntfy_inboxes SET url='http://ntfy.example.com', enabled=1 WHERE user_id=?", (FID,))
check(Fr.get(B + "/api/me/ntfy-inbox").json().get("insecure") is True, "freelancer (ntfy_inbox): the same hint")
Fr.put(B + "/api/me/ntfy-inbox", json={"enabled": False})

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
