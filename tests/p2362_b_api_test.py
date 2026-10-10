#!/usr/bin/env python3
"""2.36.2 API tests, part B: security alerts of the app (#1133). Own container (start.sh, mode workspaces, admin alerts on,
stub ntfy):
 - a new instance admin is reported (also when the flag is set outside the app's routes); the user route's own alert is not
   doubled; the first admin of a new instance (first-run setup) is not reported
 - a new organisation admin, a new agent (one alert, not a second one for its first token), a new agent token
 - an admin signing in from a new address: the first sign-in after the update only stores it; a new address is reported
   with the address; the same address again is not; the address is stored as a hash only; regular users are not watched
 - every event also writes one "kalmido-security:" JSON line into the server log (also with the alert kind switched off)
 - rebuilding the baseline (the first tick after the update) reports nothing that already exists
 - alerts carry ids, usernames and addresses only (no list names / task titles)
usage: p2362_b_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]
SECRET = "Geheimprojekt Nordlicht 4711"  # a list name: must never show up in an alert


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123", ip=None):
    s = requests.Session()
    s.headers.update(H)
    if user:
        h = {"X-Forwarded-For": ip} if ip else {}
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw}, headers=h)
        assert r.ok, (user, r.text)
    return s


def ntfy_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def clear():
    try:
        os.remove(os.path.join(DATA, "ntfy.log"))
    except FileNotFoundError:
        pass


def msgs(part=""):
    return [x for x in ntfy_log() if x.get("topic") == "t-alice" and part in x.get("msg", "")]


def wait_for(fn, n=1, t=8.0):
    t0 = time.time()
    while time.time() - t0 < t:
        x = fn()
        if len(x) >= n:
            time.sleep(0.4)
            return fn()
        time.sleep(0.2)
    return fn()


def dbx(sql, args=(), write=False):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    out = []
    for line in (r.stdout + r.stderr).splitlines():
        if "kalmido-security: " in line:
            try:
                out.append(json.loads(line.split("kalmido-security: ", 1)[1]))
            except ValueError:
                out.append({"bad": line})
    return out


def log_events(ev, **kw):
    return [x for x in logs() if x.get("event") == ev and all(x.get(k) == v for k, v in kw.items())]


env = dict(os.environ, KALMIDO_ADMIN_ALERTS="1",
           EXTRA="-e KALMIDO_ADMIN_ALERT_WINDOW=3 -e KALMIDO_INSTANCE_MODE=workspaces")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
time.sleep(1.5)  # the first watch tick takes the baseline

s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab", "tour": "done"})
check(A.patch(B + "/api/admin/alerts", json={"max_hour": 100}).ok, "hourly cap raised for the suite")
r = A.post(B + "/api/admin/alerts/test")
check(r.ok, f"test alert works: {r.text[:200]}")
time.sleep(2.5)
check(not msgs("alice is now an instance admin"), "the first admin of a new instance (setup) is not reported")
L = A.post(B + "/api/lists", json={"name": SECRET}).json()


def mk(name, admin=False):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", "is_admin": admin})
    assert r.ok, r.text
    return r.json()["id"]


# ---- new instance admin
clear()
BOB = mk("bob")
time.sleep(2)
check(not msgs("bob"), "a regular new account is not reported")
dbx("UPDATE users SET is_admin=1 WHERE id=?", (BOB,), write=True)  # the flag set outside the app's routes
m = wait_for(lambda: msgs("bob is now an instance admin"))
check(len(m) == 1 and m[0]["title"] == "Kalmido admin: Security events", f"new instance admin reported: {m}")
ev = log_events("new_admin", username="bob")
check(len(ev) == 1 and ev[0]["user_id"] == BOB, f"log line for the new admin: {ev}")
time.sleep(2)
check(len(msgs("bob is now")) == 1, "reported once")
dbx("UPDATE users SET is_admin=0 WHERE id=?", (BOB,), write=True)
time.sleep(2)
dbx("UPDATE users SET is_admin=1 WHERE id=?", (BOB,), write=True)
time.sleep(2.5)
check(len(log_events("new_admin", username="bob")) == 2, "losing and getting the role again is noticed again (log)")
dbx("UPDATE users SET is_admin=0 WHERE id=?", (BOB,), write=True)

clear()
CAROL = mk("carol", admin=True)
m = wait_for(lambda: msgs("carol is now"))
time.sleep(2)
m = msgs("carol is now")
check(len(m) == 1 and "set by alice" in m[0]["msg"], f"the user route's own alert, not doubled by the watch: {m}")
check(log_events("new_admin", username="carol"), "log line for carol")

# ---- new organisation admin
clear()
DAVE = mk("dave")
r = A.post(B + "/api/admin/orgs", json={"name": "Studio Nordlicht GmbH", "admin_id": DAVE})
check(r.status_code in (200, 201), f"organisation created: {r.status_code} {r.text[:200]}")
OID = r.json().get("id") if r.ok else None
m = wait_for(lambda: msgs("dave is now an admin of organisation"))
check(len(m) == 1 and f"#{OID}" in m[0]["msg"], f"new organisation admin reported with the organisation id: {m}")
check(not msgs("alice is now an admin of organisation"), "instance admins (admins of every organisation) are not reported per organisation")
ev = log_events("new_org_admin", username="dave")
check(len(ev) == 1 and ev[0]["org_id"] == OID, f"log line for the organisation admin: {ev}")

# ---- new agent + token
clear()
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "nordbot", "display_name": "Nord bot"})
check(r.status_code == 201, f"agent created: {r.text[:200]}")
AID = r.json()["id"]
m = wait_for(lambda: msgs("nordbot"))
time.sleep(1.5)
m = msgs("nordbot")
check(len(m) == 1 and "A new agent was added: nordbot" in m[0]["msg"], f"one alert for the new agent (not a second one for its first token): {m}")
check(log_events("new_agent", username="nordbot") and log_events("new_agent_token", username="nordbot"), "log lines for agent + first token")
clear()
r = A.post(B + f"/api/admin/agents/{AID}/token", json={})
check(r.ok, "new token for the agent")
TID = dbx("SELECT id FROM api_tokens WHERE user_id=?", (AID,))[0][0]
m = wait_for(lambda: msgs("A new token was created for agent nordbot"))
check(len(m) == 1 and f"token #{TID}" in m[0]["msg"], f"new agent token reported: {m}")
ev = log_events("new_agent_token", token_id=TID)
check(ev and ev[-1]["agent_id"] == AID and ev[-1]["username"] == "nordbot", f"log line for the token: {ev}")
clear()
r = A.post(B + "/api/me/tokens", json={"name": "mine", "scopes": ["read"]})
time.sleep(2)
check(not msgs("token"), "a person's own API token is not an agent token")

# ---- admin sign-in from a new address
clear()
dbx("DELETE FROM admin_login_ips WHERE user_id=1", write=True)  # as right after the update
sess("alice", ip="198.51.100.10")
time.sleep(2)
check(not msgs("signed in from a new address"), "the first sign-in after the update only stores the address")
check(len(dbx("SELECT * FROM admin_login_ips WHERE user_id=1")) == 1, "one address stored")
sess("alice", ip="198.51.100.10")
time.sleep(1.5)
check(not msgs("signed in from a new address"), "the same address again: nothing")
sess("alice", ip="203.0.113.77")
m = wait_for(lambda: msgs("signed in from a new address"))
check(len(m) == 1 and "Admin alice signed in from a new address: 203.0.113.77" in m[0]["msg"], f"new address reported: {m}")
ev = log_events("admin_login_new_ip", username="alice")
check(len(ev) == 1 and ev[0]["ip"] == "203.0.113.77" and ev[0]["via"] == "password", f"log line for the new address: {ev}")
rows = dbx("SELECT ip_hash FROM admin_login_ips WHERE user_id=1")
check(len(rows) == 2 and all(len(x[0]) == 64 and "203.0" not in x[0] and "198.51" not in x[0] for x in rows),
      "addresses are stored as hashes only")
sess("bob", ip="203.0.113.99")
sess("bob", ip="203.0.113.98")
time.sleep(1.5)
check(not msgs("bob signed in"), "regular users are not watched")
check(not dbx("SELECT * FROM admin_login_ips WHERE user_id=?", (BOB,)), "... and nothing is stored for them")
sess("dave", ip="203.0.113.50")
sess("dave", ip="203.0.113.51")
m = wait_for(lambda: msgs("Admin dave signed in"))
check(len(m) == 1, f"organisation admins are watched too: {m}")
for i in range(12):
    dbx("INSERT INTO admin_login_ips(user_id,ip_hash,first_at,last_at) VALUES(1,?,?,?)", (f"{i:064x}", "2020-01-01T00:00:00Z", f"2020-01-01T00:00:{i:02d}Z"), write=True)
sess("alice", ip="203.0.113.200")
check(len(dbx("SELECT * FROM admin_login_ips WHERE user_id=1")) == 10, "the stored addresses are capped per admin (last 10)")

# ---- kind switched off: no alert, still the log line
clear()
kinds = [k["kind"] for k in A.get(B + "/api/admin/alerts").json()["all_kinds"] if k["kind"] != "security"]
check(A.patch(B + "/api/admin/alerts", json={"kinds": kinds}).ok, "security alerts switched off")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "stillbot", "display_name": "Still bot"})
time.sleep(2.5)
check(not msgs("stillbot"), "switched off: no alert")
check(log_events("new_agent", username="stillbot"), "switched off: the log line is still written")
A.patch(B + "/api/admin/alerts", json={"kinds": kinds + ["security"]})

# ---- baseline rebuilt (first tick after the update): nothing existing is reported
clear()
dbx("DELETE FROM sev_known", write=True)
time.sleep(2.5)
check(not [x for x in msgs() if "is now" in x["msg"] or "new agent" in x["msg"] or "new token" in x["msg"]],
      f"rebuilding the baseline reports nothing: {msgs()}")
check(dbx("SELECT COUNT(*) FROM sev_known WHERE ref='*'")[0][0] == 4, "baseline marker per kind")

# ---- no content in alerts
blob = json.dumps(dbx("SELECT message, tmpl FROM admin_alerts"), ensure_ascii=False)
check(SECRET not in blob, "no list names in admin alerts")

subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
print(f"{OKS[0]} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
