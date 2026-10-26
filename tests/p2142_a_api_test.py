#!/usr/bin/env python3
"""2.142.0 API tests, part A (#2145, #2146): notification channels (Slack, Matrix, Telegram, Signal) and e-mails for single
events. Own container (start.sh with the webhook stub on 127.0.0.1:8097 and the SMTP sink on 127.0.0.1:1025). Invented names
only, addresses @example.test / @example.com.
 - a person's channels: create (invalid kind / address / token: 400; http:// and private addresses only when allowed), the
   address never comes back (GET shows kind, name, a masked end), sealed in the database; another person: 404; "Send test"
   arrives at the receiver; per channel only the kinds it wants (assignment, mention); off = nothing; the right body per
   service (Slack / Matrix {"text"}, Telegram chat_id + text, Signal number + recipients + message)
 - failures in a row turn a channel off (disabled_reason failures), switching it on again resets the count
 - an organisation's channels: only its admins (a member 403, another organisation 404); new task, completed, assigned and
   comment of a list open to every member arrive; a list shared only with some, a member's private list and another
   organisation's list never; a list with the lock: the neutral word, never the title or the comment; the creator is no admin
   any more -> the channel turns itself off ('admin')
 - a person without an organisation (freelancer-matrix: own): own channels, the events of the own private lists ("lists")
 - e-mails (#2146): an assignment and a mention of a person without a push device -> ONE bundled mail after the delay, with
   links and the hint where to turn it off; a second event waits for the gap; a person with a push device gets none
   ("nopush"), with "always" one; "off" = none; a task out of sight by sending time is left out; invalid values: 400
usage: p2142_a_api_test.py <datadir>      (a fresh container; P2142A_NOSTART=1 = the server already runs)"""
import email as _em
import email.policy
import json
import os
import shutil
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess, until  # noqa: E402  2.192.0 B (#2513)

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
STUB = "http://127.0.0.1:8097"
TG_TOKEN = "123456:ABCdefGHIjklMNOpqrSTUvwxYZ012345"


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def hooks_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "wh.log")) if x.strip()]
    except FileNotFoundError:
        return []


def got(path, pred=None, timeout=12):
    """Bodies (parsed JSON) the stub received on path (and pred(body)), waiting up to timeout seconds for the first."""
    def f():
        out = []
        for r in hooks_log():
            if r["path"] != path:
                continue
            try:
                p = json.loads(r["body"])
            except ValueError:
                continue
            if pred is None or pred(p):
                out.append(p)
        return out
    t0 = time.time()
    while time.time() - t0 < timeout:
        x = f()
        if x:
            return x
        time.sleep(0.3)
    return f()


def queued(u):
    """2.192.0 B (#2513): the waiting rows of the bundled event mail of a person."""
    return dbx("SELECT kind FROM notify_mail_queue WHERE user_id=?", (uid[u],))


def none_after(path, pred=None, wait=4):
    time.sleep(wait)
    return not got(path, pred, timeout=0)


def has(word):
    return lambda p: word in json.dumps(p, ensure_ascii=False)


def mails(to=None):
    try:
        out = [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []
    return [m for m in out if not to or to in json.dumps(m["to"])]


def wait_mail(to, n, secs=15):
    for _ in range(secs * 5):
        if len(mails(to)) >= n:
            return mails(to)
        time.sleep(0.2)
    return mails(to)


def mail_parts(m):
    msg = _em.message_from_string(m["raw"], policy=_em.policy.default)
    text = "".join(x.get_content() for x in msg.walk() if x.get_content_type() == "text/plain" and not x.get_filename())
    return str(msg["Subject"]), text


if not os.environ.get("P2142A_NOSTART"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    env = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") +
               " -e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_CHANNEL_TICK=1 -e KALMIDO_CHANNEL_FAILS=3"
               f" -e KALMIDO_TELEGRAM_API={STUB}/tg -e KALMIDO_EVENT_MAIL_DELAY=3 -e KALMIDO_EVENT_MAIL_GAP=8"
               " -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    for f in ("stub_webhook.py", "stub_mail.py"):
        shutil.copy(os.path.join(N, f), DATA)
        subprocess.run(["docker", "exec", "-d", CT, "python", "/data/" + f])
    time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ST = A.get(B + "/api/state").json()["me"]
ORG = ST["workspaces"][0]["id"]
uid = {"alice": ST["id"]}
for u in ("bob", "carol", "dora", "emil", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "frank" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.test"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
OB = r.json().get("id")
Bo, Ca, Do, Em, Fr = (sess(u) for u in ("bob", "carol", "dora", "emil", "frank"))
for s in (A, Bo, Ca, Do, Em, Fr):
    # 2.142.2: quiet hours off - their default 22:00-07:00 holds channel messages back, so the suite went red after 22:00 (CI)
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES, "quiet_from": "", "quiet_to": ""}).ok


def task(s, lid, title):
    r = s.post(B + "/api/tasks", json={"list_id": lid, "title": title})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# ================================================================ 1. a person's channels
# tenant-matrix: channel
j = Bo.get(B + "/api/me/channels").json()
check(j.get("enabled") is True and j.get("kinds") == ["slack", "matrix", "telegram", "signal"] and j.get("channels") == [],
      f"empty list, the four services: {j}")
check("lists" in j.get("events", []) and "reminder" in j["events"], "a person's events " + str(j.get("events")))
check(j.get("mail") == {"enabled": True, "address": True, "device": False, "assign": "nopush", "mention": "nopush"}, f"mail info {j.get('mail')}")
check(Bo.post(B + "/api/me/channels", json={"kind": "teams", "url": "https://example.com/x"}).status_code == 400, "an unknown service: 400")
check(Bo.post(B + "/api/me/channels", json={"kind": "slack", "url": "http://example.com/x"}).status_code == 400, "http:// not allowed: 400")
check(Bo.post(B + "/api/me/channels", json={"kind": "slack", "url": "https://10.1.2.3/x"}).status_code == 400, "a private address: 400")
check(Bo.post(B + "/api/me/channels", json={"kind": "slack", "url": "https://localhost/x"}).status_code == 400, "localhost: 400")
check(Bo.post(B + "/api/me/channels", json={"kind": "telegram", "token": "nope", "chat_id": "1"}).status_code == 400, "a bad bot token: 400")
check(Bo.post(B + "/api/me/channels", json={"kind": "signal", "url": STUB + "/sig", "number": "0151", "recipient": "+4915100000002"}).status_code == 400,
      "a bad sender number: 400")
check(Bo.post(B + "/api/me/channels", json={"kind": "slack", "url": STUB + "/x", "events": ["bogus"]}).status_code == 400, "an unknown event: 400")
check(Bo.post(B + "/api/me/channels", json={"kind": "slack", "url": STUB + "/x", "events": ["newtask"]}).status_code == 400,
      "an organisation's event on a person's channel: 400")
SECRET_PATH = "/slack/T000/B000/XXXXsecretXXXX1234"
r = Bo.post(B + "/api/me/channels", json={"kind": "slack", "name": "Team Slack", "url": STUB + SECRET_PATH, "events": ["assign", "comment"]})
check(r.status_code == 201, f"a Slack channel: {r.status_code} {r.text[:200]}")
SL = r.json()
check("url" not in SL and "target" not in SL and SL.get("hint", "").endswith("…1234") and "XXXXsecret" not in r.text,
      f"the address never comes back, a masked end only: {SL}")
check(SL.get("events") == ["assign", "comment"] and SL.get("enabled") is True, "events + on " + str(SL))
r = Bo.post(B + "/api/me/channels", json={"kind": "telegram", "token": TG_TOKEN, "chat_id": "-100123456"})
check(r.status_code == 201, f"a Telegram channel (default events): {r.text[:200]}")
TG = r.json()
check(TG.get("events") == ["reminder", "assign", "comment"] and TG.get("hint") == "Telegram …2345", "default events, hint " + str(TG))
r = Bo.post(B + "/api/me/channels", json={"kind": "signal", "url": STUB + "/sig", "number": "+4915100000001", "recipient": "+4915100000002",
                                          "events": ["assign"]})
check(r.status_code == 201, f"a Signal channel: {r.text[:200]}")
SG = r.json()
r = Bo.post(B + "/api/me/channels", json={"kind": "matrix", "url": STUB + "/mx", "events": ["digest"]})
check(r.status_code == 201, f"a Matrix channel (digest only): {r.text[:200]}")
MX = r.json()
g = Bo.get(B + "/api/me/channels")
check(len(g.json()["channels"]) == 4 and "XXXXsecret" not in g.text and TG_TOKEN not in g.text and "+4915100000001" not in g.text,
      "GET: four channels, no address / token / number")
row = dbx("SELECT target FROM notify_channels WHERE id=?", (SL["id"],))
check(row and row[0][0].startswith("v1.") and "XXXXsecret" not in row[0][0], "the address is sealed in the database")
check(Ca.get(B + "/api/me/channels").json()["channels"] == [], "carol does not see bob's channels")
for m, u in (("PATCH", f"/api/me/channels/{SL['id']}"), ("DELETE", f"/api/me/channels/{SL['id']}"), ("POST", f"/api/me/channels/{SL['id']}/test")):
    check(Ca.request(m, B + u, json={"name": "x"}).status_code == 404, f"another person's channel: 404 ({m})")
check(Fr.get(B + f"/api/orgs/{ORG}/channels").status_code == 404, "another organisation's channels: 404")

r = Bo.post(B + f"/api/me/channels/{SL['id']}/test")
check(r.status_code == 200 and r.json().get("ok") is True, f"Send test: ok {r.text[:200]}")
x = got(SECRET_PATH, has("Notifications are arriving."))
check(len(x) == 1 and set(x[0]) == {"text"}, f"the test arrived as Slack text: {x}")
r = Bo.post(B + f"/api/me/channels/{TG['id']}/test")
x = got(f"/tg/bot{TG_TOKEN}/sendMessage", has("Notifications are arriving."))
check(r.json().get("ok") is True and x and x[0].get("chat_id") == "-100123456", f"Telegram: the bot URL, chat_id + text: {x}")

# ---- pushes reach the channels (bob has no device: the channels make him reachable)
SH = A.post(B + "/api/lists", json={"name": "Shared tasks", "org_id": None}).json()["id"]
A.put(B + f"/api/lists/{SH}/members", json={"user_id": uid["bob"], "role": "edit"})
T1 = task(A, SH, "Prepare the offer")
A.patch(B + f"/api/tasks/{T1}", json={"assignee_id": uid["bob"]})
x = got(SECRET_PATH, has("assigned you: Prepare the offer"))
check(len(x) == 1 and "#t/" in x[0]["text"], f"#2145: the assignment arrives in Slack with the link: {x}")
check(got(f"/tg/bot{TG_TOKEN}/sendMessage", has("Prepare the offer")), "#2145: ... and in Telegram (default events)")
x = got("/sig/v2/send", has("Prepare the offer"))
check(x and x[0].get("number") == "+4915100000001" and x[0].get("recipients") == ["+4915100000002"] and "message" in x[0],
      f"#2145: Signal: number, recipients, message {x}")
check(none_after("/mx", has("Prepare the offer"), wait=2), "#2145: the Matrix channel (digest only) gets no assignment")
A.post(B + f"/api/tasks/{T1}/comments", json={"body": f"Please check <@{uid['bob']}>"})
check(got(SECRET_PATH, lambda p: "mentioned you" in p["text"] or "you were mentioned" in p["text"]),
      "#2145: a mention arrives in Slack (at once or in the burst summary)")
check(none_after("/sig/v2/send", lambda p: "mentioned" in p["message"], wait=2), "#2145: Signal (assignments only) gets no mention")
check(Bo.patch(B + f"/api/me/channels/{SL['id']}", json={"enabled": False}).json().get("enabled") is False, "switched off")
T2 = task(A, SH, "Order paper")
A.patch(B + f"/api/tasks/{T2}", json={"assignee_id": uid["bob"]})
check(got("/sig/v2/send", has("Order paper")), "the Signal channel still gets it")
check(none_after(SECRET_PATH, has("Order paper"), wait=2), "#2145: a switched-off channel gets nothing")
r = Bo.patch(B + f"/api/me/channels/{SL['id']}", json={"url": STUB + "/slack/new-address-9876", "enabled": True})
check(r.ok and r.json()["hint"].endswith("…9876"), f"a new address replaces the old one: {r.text[:200]}")
check(Bo.patch(B + f"/api/me/channels/{SL['id']}", json={"events": []}).status_code == 400, "no event: 400")

# ---- failures in a row turn a channel off
r = Bo.post(B + "/api/me/channels", json={"kind": "slack", "name": "Broken", "url": STUB + "/fail", "events": ["assign"]})
BR = r.json()["id"]
for i in range(3):
    r = Bo.post(B + f"/api/me/channels/{BR}/test")
    # 2.306.0 (#2875): the test names only the class of the target's answer (5xx), not its number
    check(r.json().get("ok") is False and "5xx" in r.json().get("error_text", "") and "500" not in r.json().get("error_text", "")
          and r.json().get("status") == "5xx", f"a failing test {i + 1}: {r.text[:200]}")
ch = [c for c in Bo.get(B + "/api/me/channels").json()["channels"] if c["id"] == BR][0]
check(ch["enabled"] is False and ch["disabled_reason"] == "failures" and ch["fails"] == 3, f"#2145: off after 3 failures: {ch}")
ch = Bo.patch(B + f"/api/me/channels/{BR}", json={"enabled": True}).json()
check(ch["enabled"] is True and ch["fails"] == 0 and ch["disabled_reason"] == "", "on again: the count starts anew")
T3 = task(A, SH, "Failing delivery")
A.patch(B + f"/api/tasks/{T3}", json={"assignee_id": uid["bob"]})
got("/fail", has("Failing delivery"))
# 2.192.0 B (#2513): wait until the failure is counted instead of 1.5 s
ch = until(lambda: [c for c in Bo.get(B + "/api/me/channels").json()["channels"] if c["id"] == BR and c["fails"] >= 1], 15)
ch = ch[0] if ch else [c for c in Bo.get(B + "/api/me/channels").json()["channels"] if c["id"] == BR][0]
check(ch["fails"] == 1 and "5xx" in ch["last_error"] and "500" not in ch["last_error"],  # 2.306.0 (#2875 review N13): the class only
      f"#2145: a real push that failed is counted, not retried: {ch}")
check(len(got("/fail", has("Failing delivery"), timeout=0)) == 1, "sent once (no retries)")
check(Bo.delete(B + f"/api/me/channels/{BR}").ok and not dbx("SELECT 1 FROM notify_channels WHERE id=?", (BR,)), "removed")

# ================================================================ 2. an organisation's channels
check(Bo.get(B + f"/api/orgs/{ORG}/channels").status_code == 403, "a member cannot see the organisation's channels")
check(Bo.post(B + f"/api/orgs/{ORG}/channels", json={"kind": "slack", "url": STUB + "/org"}).status_code == 403, "a member cannot add one")
r = A.post(B + f"/api/orgs/{ORG}/channels", json={"kind": "slack", "name": "Alpha team", "url": STUB + "/org-alpha"})
check(r.status_code == 201 and r.json()["events"] == ["newtask", "complete", "assign", "comment"], f"the admin adds one: {r.text[:200]}")
OC = r.json()
check(A.post(B + f"/api/orgs/{ORG}/channels", json={"kind": "slack", "url": STUB + "/x", "events": ["lists"]}).status_code == 400,
      "a person's event on an organisation's channel: 400")
check(OC["id"] not in [c["id"] for c in A.get(B + "/api/me/channels").json()["channels"]], "not among the admin's own channels")
check(Fr.patch(B + f"/api/orgs/{OB}/channels/{OC['id']}", json={"name": "x"}).status_code == 404, "via another organisation: 404")
OL = A.post(B + "/api/lists", json={"name": "Alpha board", "org_id": ORG}).json()["id"]
check(A.patch(B + f"/api/lists/{OL}", json={"org_visibility": "org"}).ok, "setup: everyone in the organisation")
A.put(B + f"/api/lists/{OL}/members", json={"user_id": uid["bob"], "role": "edit"})
TO = task(A, OL, "Plan the launch")
check(got("/org-alpha", has("Alice added: Plan the launch")), "#2145: a new task of an open organisation list")
A.patch(B + f"/api/tasks/{TO}", json={"assignee_id": uid["bob"]})
check(got("/org-alpha", has("Alice assigned Bob: Plan the launch")), "#2145: the assignment")
Bo.post(B + f"/api/tasks/{TO}/comments", json={"body": "Draft is ready"})
check(got("/org-alpha", has("Bob commented on Plan the launch: Draft is ready")), "#2145: the comment with its words")
Bo.post(B + f"/api/tasks/{TO}/complete", json={})
check(got("/org-alpha", has("Bob completed: Plan the launch")), "#2145: completed")
# tenant-matrix: channel -- never what not every member sees
OS = A.post(B + "/api/lists", json={"name": "Alpha leadership", "org_id": ORG}).json()["id"]
task(A, OS, "Salary review")
PB = Bo.post(B + "/api/lists", json={"name": "Bob private", "org_id": None}).json()["id"]
task(Bo, PB, "Bob dentist")
FL = Fr.post(B + "/api/lists", json={"name": "Beta board", "org_id": OB}).json()["id"]
Fr.patch(B + f"/api/lists/{FL}", json={"org_visibility": "org"})
task(Fr, FL, "Beta secret plan")
check(none_after("/org-alpha", lambda p: any(w in p["text"] for w in ("Salary review", "Bob dentist", "Beta secret plan"))),
      "#2145: nothing of a list shared only with some, a private list or another organisation")
# a list with the lock: the neutral word only
TL = task(A, OL, "Locked title words")
got("/org-alpha", has("Locked title words"))
dbx("UPDATE lists SET e2e='on' WHERE id=?", (OL,))
A.post(B + f"/api/tasks/{TL}/complete", json={})
lk = [p["text"] for p in got("/org-alpha", has("Alice completed:"))]
check(lk and "Task" in lk[-1] and "Locked title words" not in lk[-1], f"#2145: a list with the lock: the neutral word, no title: {lk[-1:]}")
dbx("UPDATE lists SET e2e=NULL WHERE id=?", (OL,))
# the creator is no admin any more -> off
A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["carol"], "role": "admin"})
r = Ca.post(B + f"/api/orgs/{ORG}/channels", json={"kind": "matrix", "url": STUB + "/org-carol"})
check(r.status_code == 201, f"carol (admin now) adds one: {r.text[:200]}")
CC = r.json()["id"]
A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["carol"], "role": "member"})
task(A, OL, "After the demotion")
check(got("/org-alpha", has("After the demotion")), "the admin's channel still gets it")
check(none_after("/org-carol", has("After the demotion"), wait=1), "#2145: the former admin's channel gets nothing")
ch = [c for c in A.get(B + f"/api/orgs/{ORG}/channels").json()["channels"] if c["id"] == CC][0]
check(ch["enabled"] is False and ch["disabled_reason"] == "admin", f"#2145: turned off ('admin'): {ch}")
r = A.patch(B + f"/api/orgs/{ORG}/channels/{CC}", json={"enabled": True})
check(r.ok and r.json()["enabled"] is True and dbx("SELECT user_id FROM notify_channels WHERE id=?", (CC,))[0][0] == uid["alice"],
      "the admin who switches it on owns it")
check(A.post(B + f"/api/orgs/{ORG}/channels/{CC}/test").json().get("ok") is True, "test of an organisation's channel")
check(A.delete(B + f"/api/orgs/{ORG}/channels/{CC}").ok, "removed")

# ================================================================ 3. a person without an organisation
# freelancer-matrix: own
FID, Fi = freelancer(B, A, "frida")
check(Fi.get(B + "/api/me/channels").json()["channels"] == [], "the freelancer: no channels yet")
check(Fi.get(B + f"/api/orgs/{ORG}/channels").status_code == 404, "the freelancer: no organisation's channels")
r = Fi.post(B + "/api/me/channels", json={"kind": "slack", "name": "Mine", "url": STUB + "/frida", "events": ["lists", "reminder"]})
check(r.status_code == 201, f"the freelancer adds a channel: {r.text[:200]}")
FC = r.json()["id"]
check(Fi.patch(B + f"/api/me/channels/{FC}", json={"name": "My studio"}).json().get("name") == "My studio", "the freelancer renames it")
check(Fi.post(B + f"/api/me/channels/{FC}/test").json().get("ok") is True, "the freelancer's test")
FLI = Fi.post(B + "/api/lists", json={"name": "Studio", "org_id": None}).json()["id"]
FT = task(Fi, FLI, "Invoice the client")
check(got("/frida", has("Frida added: Invoice the client")), "#2145 (P4): the private area's own list events")
Fi.post(B + f"/api/tasks/{FT}/complete", json={})
check(got("/frida", has("Frida completed: Invoice the client")), "#2145 (P4): completed in the own list")
check(Fi.delete(B + f"/api/me/channels/{FC}").ok, "the freelancer removes it")

# ================================================================ 4. e-mails for single events (#2146)
check(Do.patch(B + "/api/settings", json={"mail_assign": "sometimes"}).status_code == 400, "#2146: an invalid choice: 400")
check(Do.patch(B + "/api/settings", json={"evmail_at": "1"}).ok and not dbx(
    "SELECT 1 FROM user_settings WHERE user_id=? AND key='evmail_at' AND value='1'", (uid["dora"],)), "server-only state is not written by the person")
ML = A.post(B + "/api/lists", json={"name": "Mail tasks", "org_id": None}).json()["id"]
for u in ("dora", "emil"):
    A.put(B + f"/api/lists/{ML}/members", json={"user_id": uid[u], "role": "edit"})
M1, M2, M3 = task(A, ML, "Book the venue"), task(A, ML, "Write the agenda"), task(A, ML, "Hidden later")
A.patch(B + f"/api/tasks/{M1}", json={"assignee_id": uid["dora"]})
A.post(B + f"/api/tasks/{M2}/comments", json={"body": f"<@{uid['dora']}> can you look?"})
time.sleep(1)
check(not mails("dora@example.test"), "#2146: nothing at once (bundled after the delay)")
m = wait_mail("dora@example.test", 1)
check(len(m) == 1, f"#2146: one mail for both events ({len(m)})")
if m:
    subj, text = mail_parts(m[0])
    check(subj == "Kalmido: 2 new notifications", "subject " + subj)
    check("Alice assigned you: Book the venue" in text and "Alice mentioned you: Write the agenda" in text, "both lines " + text[:300])
    check(f"#t/{M1}" in text and f"#t/{M2}" in text, "links to the tasks")
    check("Settings > Notifications" in text and "#settings/notify" in text, "where to turn it off")
    check("can you look" not in text, "no words of the comment")
# the gap: a second event waits
A.patch(B + f"/api/tasks/{M2}", json={"assignee_id": uid["dora"]})
time.sleep(4)
check(len(mails("dora@example.test")) == 1, "#2146: a second mail waits for the gap")
m = wait_mail("dora@example.test", 2, secs=15)
check(len(m) == 2 and "Write the agenda" in mail_parts(m[-1])[1] and mail_parts(m[-1])[0] == "Kalmido: 1 new notification",
      f"#2146: then the second one ({len(m)})")
# a push device: "nopush" sends nothing, "always" does
check(Em.get(B + "/api/me/channels").json()["mail"]["device"] is False, "the topic every account gets is no push device by itself")
check(Em.patch(B + "/api/settings", json={"push_channel": "ntfy"}).ok, "emil uses ntfy")
check(Em.get(B + "/api/me/channels").json()["mail"]["device"] is True, "emil has a push device")
A.patch(B + f"/api/tasks/{M1}", json={"assignee_id": uid["emil"]})
# 2.192.0 B (#2513): a mail only ever comes from the queue: nothing queued = no mail (instead of waiting 6 s for none)
time.sleep(1)
check(not queued("emil") and not mails("emil@example.test"), "#2146: with a push device: no mail (only without a push device)")
check(Em.patch(B + "/api/settings", json={"mail_assign": "always"}).ok, "emil: always")
A.patch(B + f"/api/tasks/{M2}", json={"assignee_id": uid["emil"]})
m = wait_mail("emil@example.test", 1)
check(len(m) == 1 and "Write the agenda" in mail_parts(m[0])[1], f"#2146: always: a mail despite the device ({len(m)})")
# off
check(Do.patch(B + "/api/settings", json={"mail_assign": "off"}).ok, "dora: off")
A.patch(B + f"/api/tasks/{M3}", json={"assignee_id": uid["dora"]})
time.sleep(1)  # 2.192.0 B (#2513): nothing queued = no mail (instead of waiting 10 s for none)
check(not queued("dora") and len(mails("dora@example.test")) == 2, "#2146: off: no mail")
# out of sight by sending time
Do.patch(B + "/api/settings", json={"mail_assign": "nopush"})
A.patch(B + f"/api/tasks/{M3}", json={"assignee_id": None})
time.sleep(1)
A.patch(B + f"/api/tasks/{M3}", json={"assignee_id": uid["dora"]})
A.delete(B + f"/api/lists/{ML}/members/{uid['dora']}")
until(lambda: queued("dora") == [], 40)  # 2.192.0 B (#2513): until the bundled mail was handled (the gap included) instead of 12 s
time.sleep(1)
check(all("Hidden later" not in mail_parts(x)[1] for x in mails("dora@example.test")), "#2146: a task out of sight is left out")

print(f"p2142_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
