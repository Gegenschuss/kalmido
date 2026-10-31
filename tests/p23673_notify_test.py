#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.367.3 (#2973, #2971): what external channels report, and integrations that stop are told. Own container (start.sh with the
webhook stub on 127.0.0.1:8097 and the SMTP sink on 127.0.0.1:1025). Invented names, addresses @example.test.
 #2973
 - a person's channel with "lists": their own changes stay out, someone else's arrive; the choice "own" brings them back;
   an inbound webhook acts as its owner but is news to them; an organisation's channel is a team feed and keeps the actor's own
 - completing a repeating task reaches the channels (the original is open again by then)
 - a rule "due date reached" run by the watchdog reaches the channels
 #2971
 - a failed message gets exactly one more try (one failure counted); it arrives when the receiver is back
 - a channel that turns itself off: News + push for its owner, for an organisation's channel its admins; the same for a webhook
 - an inbound webhook that pauses: who set it up and the project's owner, once
 - a mailbox, a git connection, an ntfy inbox at INTEG_FAILS failures in a row: once; the notification switch turns it off
 - a failed backup with the admin alerts off: News + mail to the instance's admins, once for the same error on one day
 freelancer-matrix: channels
usage: p23673_notify_test.py <datadir>      (a fresh container; P23673_NOSTART=1 = the server already runs)"""
import email
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
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
STUB = "http://127.0.0.1:8097"
FAILS_MAX = 2  # KALMIDO_CHANNEL_FAILS below


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args)
        rows = r.fetchall() if r.description else []
        c.commit()
        return rows
    finally:
        c.close()


def posts(path):
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "wh.log")) if x.strip() and json.loads(x)["path"] == path]
    except FileNotFoundError:
        return []


def texts(path):
    return [json.loads(r["body"]).get("text", "") for r in posts(path)]


def mails(to):
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "mail", "out.jsonl"), encoding="utf-8") if x.strip() and to in x]
    except FileNotFoundError:
        return []


def until(f, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        x = f()
        if x:
            return x
        time.sleep(0.2)
    return f()


def arrives(path, word):
    return until(lambda: [t for t in texts(path) if word in t])


def news(s, what=None):
    return [x for x in s.get(B + "/api/news").json()["items"] if x["kind"] == "integfail" and (not what or x["data"]["what"] == what)]


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def channel(s, path, events, name="Mine", org=None):
    r = s.post(B + (f"/api/orgs/{org}/channels" if org else "/api/me/channels"), json={"kind": "slack", "name": name, "url": STUB + path, "events": events})
    assert r.status_code == 201, r.text
    return r.json()["id"]


if not os.environ.get("P23673_NOSTART"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    env = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") +
               " -e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_CHANNEL_TICK=1 -e KALMIDO_CHANNEL_RETRY=1"
               f" -e KALMIDO_CHANNEL_FAILS={FAILS_MAX} -e KALMIDO_WEBHOOK_TICK=1 -e KALMIDO_WEBHOOK_BACKOFF=1 -e KALMIDO_NTFYIN_TICK=1"
               " -e TASKS_WATCHDOG_INTERVAL=1 -e KALMIDO_IMAP_INTERVAL=10"
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
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
assert r.ok, r.text
uid["bob"] = r.json()["id"]
Bo = sess("bob")
FID, Fi = freelancer(B, A, "frida")
for s in (A, Bo, Fi):  # quiet hours off: their default holds channel messages back
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES, "quiet_from": "", "quiet_to": ""}).ok
check(A.patch(B + "/api/users/%d" % uid["alice"], json={"email": "alice@example.test"}).ok, "setup: the admin's address")
check("own" in Fi.get(B + "/api/me/channels").json()["events"], "#2973: the choice 'own' is offered to a person")
check(A.post(B + f"/api/orgs/{ORG}/channels", json={"kind": "slack", "url": STUB + "/x", "events": ["own"]}).status_code == 400, "#2973: not to an organisation")

# ================================================================ #2973: own changes (a person without an organisation)
FL = Fi.post(B + "/api/lists", json={"name": "Studio", "org_id": None}).json()["id"]
check(Fi.post(B + f"/api/lists/{FL}/members", json={"username": "bob", "role": "editor"}).ok, "setup: frida shares her project with bob")
FC = channel(Fi, "/fr", ["lists"])
task(Fi, FL, "Written by me")
task(Bo, FL, "Written by bob")
check(arrives("/fr", "Written by bob"), "#2973: someone else's change arrives")
check(not [t for t in texts("/fr") if "Written by me" in t], "#2973: the own change stays out (the later message of the channel came first)")
r = Fi.patch(B + f"/api/me/channels/{FC}", json={"events": ["lists", "own"]})
check(r.ok and "own" in r.json()["events"], "#2973: 'own' is saved")
task(Fi, FL, "Mine again")
check(arrives("/fr", "Mine again"), "#2973: with the choice the own change arrives")
Fi.patch(B + f"/api/me/channels/{FC}", json={"events": ["lists"]})

# an inbound webhook acts as its owner, and is news to them
r = Fi.post(B + f"/api/lists/{FL}/hooks-in", json={"name": "Form"})
check(r.status_code == 201, f"setup: an inbound webhook {r.text[:200]}")
HK, HT = r.json()["id"], r.json()["token"]
r = requests.post(B + "/api/hooks/in", headers={"X-Kalmido-Hook-Token": HT}, json={"title": "From the form"})
check(r.status_code == 201, f"the hook takes a task {r.text[:200]}")
check(arrives("/fr", "From the form"), "#2973: a task of the own inbound webhook arrives")

# an organisation's channel is a team feed
OL = A.post(B + "/api/lists", json={"name": "Alpha board", "org_id": ORG}).json()["id"]
A.patch(B + f"/api/lists/{OL}", json={"org_visibility": "all"})
channel(A, "/alpha", ["newtask", "complete"], name="Team", org=ORG)
task(A, OL, "Team news by the admin")
check(arrives("/alpha", "Team news by the admin"), "#2973: an organisation's channel keeps the actor's own events")

# ================================================================ #2973: completing a repeating task
RT = task(Fi, FL, "Water the plants", due=time.strftime("%Y-%m-%d"), repeat="FREQ=WEEKLY")
RTO = task(A, OL, "Weekly report", due=time.strftime("%Y-%m-%d"), repeat="FREQ=WEEKLY")
Fi.patch(B + f"/api/me/channels/{FC}", json={"events": ["lists", "own"]})
check(Fi.post(B + f"/api/tasks/{RT}/complete", json={}).ok and A.post(B + f"/api/tasks/{RTO}/complete", json={}).ok, "setup: both completed")
check(arrives("/fr", "completed: Water the plants"), "#2973: a person's channel hears that a repeating task was completed")
check(arrives("/alpha", "completed: Weekly report"), "#2973: an organisation's channel too")
Fi.patch(B + f"/api/me/channels/{FC}", json={"events": ["lists"]})

# ================================================================ #2973: a rule run of the watchdog
r = Fi.post(B + f"/api/lists/{FL}/rules", json={"name": "Hand over at due date", "trigger": {"kind": "due"}, "action": {"kind": "assign", "user_id": uid["bob"]}})
check(r.status_code == 201, f"setup: rule 'due date reached' {r.text[:200]}")
task(Fi, FL, "Handed over by the rule", due=time.strftime("%Y-%m-%d"))
check(arrives("/fr", "Bob: Handed over by the rule"), "#2973: a rule run of the watchdog reaches the channel (and counts as no own change)")
Fi.delete(B + f"/api/lists/{FL}/rules/{r.json()['id']}")

# ================================================================ #2971: one more try
BL = Bo.post(B + "/api/lists", json={"name": "Bob's", "org_id": None}).json()["id"]
BC = channel(Bo, "/fail-bob", ["lists"], name="Bob's Slack")
check(Bo.post(B + f"/api/lists/{BL}/members", json={"username": "alice", "role": "editor"}).ok, "setup: bob shares with alice")
task(A, BL, "First message")
check(until(lambda: len(posts("/fail-bob")) >= 2), "#2971: the failed message is tried once more")
time.sleep(2.5)
check(len(posts("/fail-bob")) == 2, f"#2971: exactly once ({len(posts('/fail-bob'))} tries)")
check(list(dbx("SELECT fails, enabled FROM notify_channels WHERE id=?", (BC,))[0]) == [1, 1], "#2971: one message counts as one failure")
check(not dbx("SELECT 1 FROM notify_channel_queue WHERE channel_id=?", (BC,)), "#2971: nothing waits after the second try")
check(not news(Bo), "#2971: nobody is told while the channel works on")

# ---- the receiver is back before the second try
# (flap = 500 on the first call of a path, 200 afterwards)
FC2 = channel(Bo, "/flap-bob", ["lists"], name="Flappy")
task(A, BL, "Second message")
check(until(lambda: len(posts("/flap-bob")) >= 2), "#2971: the second try went out")
check(until(lambda: list(dbx("SELECT fails FROM notify_channels WHERE id=?", (FC2,))[0])[0] == 0), "#2971: the second try worked: no failure stays")

# ================================================================ #2971: a channel turns itself off
task(A, BL, "Third message")
check(until(lambda: news(Bo, "channel")), "#2971: the channel's owner gets a News item when it turns off")
it = news(Bo, "channel")
check(len(it) == 1 and "Bob's Slack" in it[0]["data"]["text"] and it[0]["data"]["focus"] == "newskinds", f"#2971: it names the channel and where to repair it {it}")
check(it[0]["to_me"] is True, "#2971: it counts as for me (the bell)")
check(not news(A) and not news(Fi), "#2971: nobody else")
OC = channel(A, "/fail-org", ["newtask"], name="Org Slack", org=ORG)
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "admin"}).ok, "setup: bob is an admin of the organisation too")
task(A, OL, "Org one")
task(A, OL, "Org two")
check(until(lambda: news(A, "channel") and news(Bo, "channel")[1:]), "#2971: an organisation's channel: every admin of it hears it")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "member"}).ok, "setup: bob back to member")

# a channel whose creator is no admin any more: the organisation's admins hear it
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "admin"}).ok, "setup: bob an admin again")
channel(Bo, "/ok-bob-org", ["newtask"], name="Bob for Alpha", org=ORG)
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "member"}).ok, "setup: bob no admin any more")
task(A, OL, "After the change")
check(until(lambda: news(A, "channel_admin")), "#2971: the organisation's admins hear that a channel of a former admin turned off")

# ================================================================ #2971: a webhook turns itself off
r = Fi.post(B + "/api/me/webhooks", json={"name": "Dead hook", "url": STUB + "/fail-wh", "events": ["task.created"]})
check(r.status_code == 201, f"setup: a webhook of a person without an organisation {r.text[:200]}")
task(Fi, FL, "For the dead hook")
check(until(lambda: news(Fi, "webhook"), 30), "#2971: the webhook's owner gets a News item when it turns off")
check(news(Fi, "webhook") and "Dead hook" in news(Fi, "webhook")[0]["data"]["text"] and news(Fi, "webhook")[0]["data"]["focus"] == "webhooks", "#2971: it names the webhook")

# ================================================================ #2971: an inbound webhook pauses
r = Bo.post(B + f"/api/lists/{FL}/hooks-in", json={"name": "Bob's form"})
check(r.status_code == 201, f"setup: bob's inbound webhook in frida's project {r.text[:200]}")
HT2 = r.json()["token"]
check(Fi.patch(B + f"/api/lists/{FL}/members/{uid['bob']}", json={"role": "viewer"}).ok, "setup: bob can only read now")
for i in range(2):
    check(requests.post(B + "/api/hooks/in", headers={"X-Kalmido-Hook-Token": HT2}, json={"title": "No way"}).status_code == 403, f"the hook refuses ({i})")
for s, who in ((Bo, "who set it up"), (Fi, "the project's owner")):
    it = news(s, "hookin")
    check(len(it) == 1 and "Bob's form" in it[0]["data"]["text"] and it[0]["data"]["list"] == FL, f"#2971: {who} hears it once {it}")

# ================================================================ #2971: polled connections
now = "2026-10-01T10:00:00Z"
dbx("INSERT INTO hub_mailboxes(ws,owner_id,active,imap_host,imap_user,error,error_at,fails,created_at,updated_at) VALUES(?,?,1,'127.0.0.1','frida@example.test','timeout',?,4,?,?)",
    (f"u{FID}", FID, now, now, now))
ws = dbx("SELECT ws FROM hub_mailboxes WHERE owner_id=?", (FID,))[0][0]
check(until(lambda: news(Fi, "mailbox"), 30), "#2971: a mailbox at 5 failures in a row: its person is told")
it = news(Fi, "mailbox")
check(it and "frida@example.test" in it[0]["data"]["text"] and "2026-10-01" in it[0]["data"]["text"] and it[0]["data"]["ws"] == ws, f"#2971: since when it fails {it}")
check(until(lambda: list(dbx("SELECT fails FROM hub_mailboxes WHERE ws=?", (ws,))[0])[0] >= 6, 30) and len(news(Fi, "mailbox")) == 1, "#2971: the next failure tells nobody again")

dbx("INSERT INTO git_conns(list_id,provider,base_url,owner,repo,fails,polled_at,next_at,created_by,created_at) VALUES(?,'gitea','http://127.0.0.1:9/','acme','tool',4,?,0,?,?)",
    (FL, now, FID, now))
check(until(lambda: news(Fi, "git"), 30), "#2971: a git connection at 5 failures in a row: told once")
it = news(Fi, "git")
check(it and "acme/tool" in it[0]["data"]["text"] and "2026-10-01" in it[0]["data"]["text"] and it[0]["data"]["list"] == FL, f"#2971: the git notice {it}")

check(Bo.patch(B + "/api/settings", json={"notify": {"integration": {"news": False, "push": False}}}).ok, "bob switches the event off")
dbx("INSERT INTO ntfy_inboxes(user_id,enabled,topic,url,fails,last_ok,updated_at) VALUES(?,1,'bob-in','http://127.0.0.1:9',4,?,?)", (uid["bob"], now, now))
check(until(lambda: list(dbx("SELECT fails FROM ntfy_inboxes WHERE user_id=?", (uid["bob"],))[0])[0] >= 5, 30), "setup: the ntfy inbox failed")
check(not news(Bo, "ntfy"), "#2971: the notification switch turns it off")
dbx("INSERT INTO ntfy_inboxes(user_id,enabled,topic,url,fails,last_ok,updated_at) VALUES(?,1,'frida-in','http://127.0.0.1:9',4,?,?)", (FID, now, now))
check(until(lambda: news(Fi, "ntfy"), 30), "#2971: an ntfy inbox at 5 failures in a row: told once")

# ================================================================ #2971: a failed backup, the admin alerts off
BK = os.path.join(DATA, "backups")
os.makedirs(BK, exist_ok=True)
os.chmod(BK, 0o500)
try:
    check(A.post(B + "/api/admin/backups").status_code == 202, "setup: back up now")
    check(until(lambda: news(A, "backup"), 30), "#2971: the instance's admin gets a News item for a failed backup with the alerts off")
    m = until(lambda: mails("alice@example.test"), 15)
    check(len(m) == 1 and "Backup failed" in str(email.message_from_string(m[0]["raw"], policy=email.policy.default)["Subject"]), f"#2971: and a mail {m}")
    check(until(lambda: not A.get(B + "/api/admin/backups").json().get("running")), "setup: the run ended")
    check(A.post(B + "/api/admin/backups").status_code == 202, "setup: back up again")
    check(until(lambda: not A.get(B + "/api/admin/backups").json().get("running") and not dbx("SELECT 1 FROM bg_jobs WHERE kind='backup' AND done_at IS NULL")), "setup: that run ended")
    check(len(news(A, "backup")) == 1 and len(mails("alice@example.test")) == 1, "#2971: the same error again on the same day tells nobody again")
finally:
    os.chmod(BK, 0o700)
check(not news(Bo, "backup") and not news(Fi, "backup"), "#2971: only the instance's admins")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
