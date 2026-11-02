#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.367.4 (#2974): an organisation's events reach its own people. Invented companies, people and figures only.
freelancer-matrix: agents
 - an agent's usage limit: the admins of its organisation (and its owner); the instance admin stays out (only a number), an
   agent of nobody still goes to the instance admins
 - a sign-in of an organisation admin from a new address: News for the person and the organisation's admins, no admin alert
   with the name; an instance admin's stays the admin alert
 - a registration by domain: the instance admin keeps it (only they approve), the organisation's admins hear of it too
 - security alerts: without a time in the key the cooldown holds; two-factor on is summed up, the single person is not told of it
 - an invited account: bell, mail (once a day); the answer goes to whoever invited; a new role is a News item
 - the maintenance notice as a push: works, switchable, not to its author
usage: p23674_b_org_test.py <datadir>"""
import base64
import email as _em
import hashlib
import hmac
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, check, dbx, done, fresh, H, sess, setup, until  # noqa: E402

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")


def in_ct(code):
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def news(s, kind):
    return [x for x in s.get(B + "/api/news").json()["items"] if x["kind"] == kind]


def mails(to):
    try:
        rows = [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []
    return [m for m in rows if to in json.dumps(m["to"])]


def totp(secret):
    key = base64.b32decode(secret.replace(" ", "") + "=" * (-len(secret.replace(" ", "")) % 8))
    mac = hmac.new(key, struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest()
    o = mac[-1] & 15
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def alerts():
    return A.get(B + "/api/admin/alerts").json()["items"]


os.environ["KALMIDO_ADMIN_ALERTS"] = "1"
fresh({"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_SMTP_HOST": "127.0.0.1", "KALMIDO_SMTP_PORT": "1025", "KALMIDO_SMTP_TLS": "none",
       "KALMIDO_MAIL_FROM": "kalmido@example.test", "KALMIDO_ADMIN_ALERT_WINDOW": "3", "KALMIDO_TRUST_PROXY": "1"})
shutil.copy(os.path.join(N, "stub_mail.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
A = setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]


def user(name):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123", "email": f"{name}@example.com", "orgs": []})
    assert r.ok, r.text
    return r.json()["id"]


BOB, CAROL, DAVE, EVE = user("bob"), user("carol"), user("dave"), user("eve")
ORG = A.post(B + "/api/admin/orgs", json={"name": "Nordwind", "admin_id": BOB}).json()["id"]
Bo = sess("bob")
assert Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments,agents"}).ok
Ca, Da, Ev = sess("carol"), sess("dave"), sess("eve")
for s in (Ca, Da, Ev):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments"}).ok
assert A.patch(B + "/api/settings", json={"features": "collab,comments,agents"}).ok

# ================================================================== an invited account
r = Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com", "role": "member"})
check(r.ok, f"setup: bob invites carol {r.status_code} {r.text[:200]}")
check(news(Ca, "orgjoin"), "the bell as before")
m = until(lambda: mails("carol@example.com"), 20)
check(len(m) == 1 and "Nordwind" in json.dumps(m[0]), f"and a mail naming the organisation {str(m)[:300]}")
Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com", "role": "member"})
check(len(until(lambda: mails("carol@example.com"), 3)) == 1, "the same day: no second mail")
assert Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "dave@example.com", "role": "member"}).ok
assert Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "eve@example.com", "role": "member"}).ok
assert Ca.post(B + f"/api/orgs/{ORG}/join").ok and Da.post(B + f"/api/orgs/{ORG}/join").ok and Ev.delete(B + f"/api/orgs/{ORG}/join").ok
n = news(Bo, "orgjoinres")
check(sorted(x["data"]["yes"] for x in n) == [False, True, True] and all(x["data"]["name"] == "Nordwind" for x in n), f"whoever invited hears each answer {n}")

# ================================================================== a new role
r = Bo.put(B + f"/api/orgs/{ORG}/members", json={"user_id": CAROL, "role": "admin"})
check(r.ok, f"setup: carol becomes admin {r.status_code} {r.text[:200]}")
n = news(Ca, "orgrole")
check(len(n) == 1 and n[0]["data"] == {"org_id": ORG, "name": "Nordwind", "role": "admin"}, f"the person hears of the new role {n}")
Bo.put(B + f"/api/orgs/{ORG}/members", json={"user_id": CAROL, "role": "admin"})
check(len(news(Ca, "orgrole")) == 1, "the same role again: nothing")

# ================================================================== an agent's usage limit
r = Bo.patch(B + f"/api/orgs/{ORG}", json={"member_agents": True})
r = A.post(B + "/api/admin/agents", json={"username": "teamrobot", "display_name": "Team Robot", "org_id": ORG})
check(r.status_code in (200, 201), f"setup: an agent {r.status_code} {r.text[:200]}")
AG = r.json().get("id") or r.json().get("agent", {}).get("id")
dbx("UPDATE agents SET org_id=?, owner_id=NULL WHERE user_id=?", (ORG, AG))
t = A.post(B + f"/api/admin/agents/{AG}/token")
check(t.ok, f"setup: its token {t.status_code} {t.text[:200]}")
HA = {**H, "Authorization": "Bearer " + t.json()["token"]}
assert A.patch(B + f"/api/admin/agents/{AG}", json={"limits": {"period": "day", "metric": "tokens", "hard": 100}}).ok


def report():
    r = requests.post(B + "/api/v1/agent/usage", headers=HA, json={"model": "test-model", "input_tokens": 90, "output_tokens": 30})
    check(r.ok or r.status_code == 429, f"setup: the agent reports usage {r.status_code} {r.text[:160]}")


report()
check(until(lambda: news(Bo, "usage"), 10) and news(Ca, "usage"), "the organisation's admins hear of the limit")
check(not news(A, "usage"), "the instance admin who is not in it does not (no name, no figures)")
check(not news(Da, "usage"), "nor a plain member")
c = until(lambda: [x for x in alerts() if "agent limit" in (x.get("message") or "")], 70)
check(c and "Team Robot" not in json.dumps(c), f"the instance admin gets a number {c}")
dbx("UPDATE agents SET org_id=NULL, usage_alerted='' WHERE user_id=?", (AG,))
dbx("DELETE FROM agent_usage WHERE agent_id=?", (AG,))
report()
check(until(lambda: news(A, "usage"), 10), "an agent of nobody still goes to the instance admins")

# ================================================================== a sign-in from a new address
sess("bob", ip="203.0.113.10")
dbx("DELETE FROM notifications WHERE kind='orglogin'")
sess("bob", ip="198.51.100.20")
n = until(lambda: news(Ca, "orglogin"), 10)
check(len(n) == 1 and n[0]["data"]["name"] == "bob" and n[0]["data"]["ip"] == "198.51.100.x", f"the other admin of the organisation hears of it {n}")
check(len(news(Bo, "orglogin")) == 1, "the person too")
check(not news(Da, "orglogin"), "not a plain member")
check(until(lambda: [x for x in alerts() if "organisation admin" in (x.get("message") or "")], 70), "the instance admin: a number")
check(not [x for x in alerts() if "Admin bob signed in" in (x.get("message") or "")], "not the name")
assert sess("alice", ip="203.0.113.11").get(B + "/api/me").ok
sess("alice", ip="198.51.100.21")
check(until(lambda: [x for x in alerts() if "Admin alice signed in" in (x.get("message") or "")], 70), "an instance admin stays the admin alert")

# ================================================================== a registration by domain
assert A.patch(B + f"/api/admin/orgs/{ORG}", json={"domains": "nordwind.example"}).ok  # 2.467.0 (#3898): only a server admin
A.patch(B + "/api/admin/settings", json={"password": "password123", "signup_mode": "approval"})
R = requests.Session()
R.headers.update(H)
r = R.post(B + "/api/auth/signup", json={"name": "Nina", "email": "nina@nordwind.example", "password": "nina-secret-1"})
check(r.ok, f"setup: a registration {r.text[:200]}")
ml = until(lambda: mails("nina@nordwind.example"), 20)
htm = [p for p in _em.message_from_string(ml[0]["raw"]).walk() if p.get_content_type() == "text/html"][0].get_payload(decode=True).decode()
tok = re.search(r"#invite/([A-Za-z0-9_-]{20,100})", htm)[1]
check(requests.post(B + "/api/auth/invite/accept", headers=H, json={"token": tok, "password": "nina-secret-1"}).ok, "setup: confirmed")
NID = dbx("SELECT id FROM users WHERE username='nina'")[0][0]
check(dbx("SELECT org_id FROM org_members WHERE user_id=?", (NID,)) == [(ORG,)], "setup: in the organisation by its domain")
n = news(A, "signup")
check(len(n) == 1 and "org_id" not in n[0]["data"], f"the instance admin keeps it {n}")
n = news(Bo, "signup")
check(len(n) == 1 and n[0]["data"]["org_id"] == ORG and n[0]["data"]["user_id"] == NID, f"the organisation's admin hears of it {n}")
check(not news(Da, "signup"), "not a plain member")
# 2.464.0 (#3882): the organisation's admin decides it too (before: 403, the instance admin only)
def waiting(s):
    o = [x for x in s.get(B + "/api/orgs").json()["orgs"] if x["id"] == ORG]
    return [m["id"] for m in o[0]["members"] if m.get("pending")] if o else []


check(waiting(Bo) == [NID], f"the organisation's admin sees who waits {waiting(Bo)}")
check(not waiting(Da), "a plain member does not")
check(Da.post(B + f"/api/users/{NID}/approve").status_code == 403, "a plain member cannot approve")
assert A.post(B + "/api/admin/orgs", json={"name": "Fremd GmbH", "admin_id": user("xena")}).ok
Xo = sess("xena")
check(Xo.post(B + f"/api/users/{NID}/approve").status_code == 404, "the admin of another organisation gets a 404")
check(Xo.delete(B + f"/api/users/{NID}").status_code == 404, "and cannot decline it")
r = Bo.post(B + f"/api/users/{NID}/approve")
check(r.ok and r.json() == {"ok": True}, f"the organisation's admin approves, the answer has no account details {r.status_code} {r.text[:200]}")
check(dbx("SELECT signup, disabled FROM users WHERE id=?", (NID,)) == [("", 0)], "the account is active")
check(not news(Bo, "signup") and not news(A, "signup"), "decided: the item is gone")
check(Bo.post(B + f"/api/users/{NID}/approve").status_code == 409, "once")
check(until(lambda: mails("nina@nordwind.example")[1:], 20), "the person hears of it")

# ================================================================== security alerts
out = in_ct("""import app
from kalmido.notify import alerts as x
b = {"items": {"bob": 1, "dave": 1, "eve": 1}, "extra": {"uid": {"2": 1, "3": 1, "4": 1}}, "n": 3}
a = x._aa_build(None, "security", "2fa_on", b)
print(a[3], a[5], x.aa_text(a[1], a[3], a[2], "en"))
b = {"items": {"bob": 1}, "extra": {"uid": {"2": 1}}, "n": 1}
a = x._aa_build(None, "security", "2fa_on", b)
print(a[3], a[5])
""").strip().splitlines()
check(out[-2].startswith("3 None 3 people turned on two-factor authentication: bob, dave, eve"), f"three people: one alert with the count, to everyone {out}")
check(out[-1] == "1 2", f"one person: not told of the own step {out}")
out = in_ct("""import app
from kalmido.core.db import connect
from kalmido.notify import alerts as x
c = connect()
x.aa_admin_via = lambda c, uid, s=None: {"ntfy": "", "webpush": 1}
cfg = {"topic": ""}
print([t for _, t, _ in x.aa_recipients(c, cfg)], [t for _, t, _ in x.aa_recipients(c, cfg, %d)])
""" % ALICE).strip().splitlines()[-1]
check(out == f"[{ALICE}] []", f"skip leaves the admin out {out}")
sec = Bo.post(B + "/api/me/2fa/totp", json={"password": "password123"}).json()["secret"]
check(Bo.post(B + "/api/me/2fa/totp/confirm", json={"code": totp(sec)}).ok, "setup: bob turns two-factor on")
check(until(lambda: [x for x in alerts() if "1 person turned on two-factor authentication: bob" in (x.get("message") or "")], 70), "it reaches the list as a summed alert")
dbx("UPDATE admin_alerts SET sent_at='2000-01-01T00:00:00+00:00' WHERE sent_at IS NOT NULL")  # the hourly cap: a capped row counts for no cooldown
for _ in range(2):  # the same reset twice within the cooldown
    dbx("UPDATE users SET totp_secret='x' WHERE id=?", (EVE,))
    check(A.patch(B + f"/api/users/{EVE}", json={"reset_2fa": True}).ok, "setup: a reset")
resets = lambda: [x for x in alerts() if "reset the two-factor" in (x.get("message") or "")]  # noqa: E731
r = until(lambda: (y if len(y := resets()) > 1 or (y and y[0].get("repeats")) else None), 70) or resets()  # the second reset lands a round later under load
check(len(r) == 1 and r[0].get("repeats") == 1, f"one row, the cooldown holds (with a time in the key: two) {r}")

# ================================================================== the notice
r = A.put(B + "/api/admin/announcement", json={"text": "Wartung heute Abend", "minutes": 30, "push": True})
check(r.ok, f"a notice with a push works (it was a 500) {r.status_code} {r.text[:200]}")
r = Da.patch(B + "/api/settings", json={"notify": {"notice": {"push": 0}}})
check(r.ok, f"the row can be switched off {r.status_code} {r.text[:200]}")
out = in_ct("""import app
from kalmido.core.db import connect, usettings
from kalmido.collab.news import notif_ok
c = connect()
print(notif_ok(c, %d, usettings(c, %d), "notice", "push"), notif_ok(c, %d, usettings(c, %d), "notice", "push"), notif_ok(c, %d, usettings(c, %d), "notice", "news"))
""" % (DAVE, DAVE, EVE, EVE, EVE, EVE)).strip().splitlines()[-1]
check(out == "False True False", f"off for dave, on for eve, no News row {out}")
check(A.put(B + "/api/admin/announcement", json={"text": ""}).ok, "setup: cleared")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot"})
check(r.status_code == 201, f"setup: a personal agent {r.status_code} {r.text[:200]}")
FA = r.json()["id"]
HA = {**H, "Authorization": "Bearer " + Fr.post(B + f"/api/my/agents/{FA}/token").json()["token"]}
assert Fr.patch(B + f"/api/my/agents/{FA}", json={"limits": {"period": "day", "metric": "tokens", "hard": 100}}).ok
n0 = len(news(A, "usage"))
report()
check(until(lambda: news(Fr, "usage"), 10) and len(news(A, "usage")) == n0, "a personal agent: its owner, not the operator")
# 2.464.0 (#3882): at the end: a deleted account is one more security alert
r = R.post(B + "/api/auth/signup", json={"name": "Olga", "email": "olga@nordwind.example", "password": "olga-secret-12"})
check(r.ok, f"setup: a second registration {r.text[:200]}")
ml = until(lambda: mails("olga@nordwind.example"), 20)
htm = [p for p in _em.message_from_string(ml[0]["raw"]).walk() if p.get_content_type() == "text/html"][0].get_payload(decode=True).decode()
check(requests.post(B + "/api/auth/invite/accept", headers=H, json={"token": re.search(r"#invite/([A-Za-z0-9_-]{20,100})", htm)[1], "password": "olga-secret-12"}).ok, "setup: confirmed")
OID = dbx("SELECT id FROM users WHERE username='olga'")[0][0]
check(Bo.delete(B + f"/api/users/{OID}").ok and not dbx("SELECT 1 FROM users WHERE id=?", (OID,)), "declining: the organisation's admin deletes the waiting account")
sys.exit(done("p23674_b_org"))
