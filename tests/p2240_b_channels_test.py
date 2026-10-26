#!/usr/bin/env python3
"""2.240.0 B (#2867): a person's notification channels (Slack, Matrix, Telegram, Signal) get a push only after the same rules
as the list events. Own container (start.sh with the webhook stub on 127.0.0.1:8097). Invented names, addresses @example.test.
 - nothing of a health, budget or read-later list, nor of an organisation's trip (the push itself still happens in the app)
 - an organisation's list: a neutral line with the link, no title / comment, unless the organisation allows the content
   (PATCH /api/orgs/<id> {chn_content}: its admins only; a member 403)
 - a disabled account: its channels stay quiet; a person's own "lists" channel skips a read-later list
 - a person without an organisation (freelancer-matrix: channels): a private list shared with them -> the full text as before
 - 2.240.0 B2 (#2867): a push without a known reference is neutral; private callers (habits, the summary's numbers, the own
   personal office) keep their text; the summary carries no titles; team chat follows the list / organisation (DMs within one: neutral)
Every "nothing" waits for a later push of the same channel first (the queue is sent in order), never for a fixed time alone.
usage: p2240_b_channels_test.py <datadir>      (a fresh container; P2240B_NOSTART=1 = the server already runs)"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402
import testclock  # noqa: E402  (the group's test time, run_all.sh `now`)

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
STUB = "http://127.0.0.1:8097"


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def texts(path):
    out = []
    try:
        rows = [json.loads(x) for x in open(os.path.join(DATA, "wh.log")) if x.strip()]
    except FileNotFoundError:
        return out
    for r in rows:
        if r["path"] == path:
            try:
                out.append(json.loads(r["body"]).get("text", ""))
            except ValueError:
                pass
    return out


def wait_for(path, word, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        x = [t for t in texts(path) if word in t]
        if x:
            return x
        time.sleep(0.3)
    return []


if not os.environ.get("P2240B_NOSTART"):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    env = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") +
               " -e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_CHANNEL_TICK=1")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    shutil.copy(os.path.join(N, "stub_webhook.py"), DATA)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webhook.py"])
    time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ST = A.get(B + "/api/state").json()["me"]
ORG = ST["workspaces"][0]["id"]
uid = {"alice": ST["id"]}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.test"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
FID, Fi = freelancer(B, A, "frida")
for s in (A, Bo, Ca, Fi):
    # quiet hours off: their default 22:00-07:00 holds channel messages back
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES, "quiet_from": "", "quiet_to": ""}).ok

PATH = {"bob": "/b2240-bob", "carol": "/b2240-carol", "frida": "/b2240-frida"}
for u, s in (("bob", Bo), ("carol", Ca), ("frida", Fi)):
    r = s.post(B + "/api/me/channels", json={"kind": "slack", "name": "Mine", "url": STUB + PATH[u], "events": ["reminder", "assign", "comment", "lists"]})
    assert r.status_code == 201, r.text
# 2.240.0 B2 (#2867): a second channel of carol and frida for the summary and the other pushes (team chat, office, ...)
for s, pth in ((Ca, "/b2240-carol-more"), (Fi, "/b2240-frida-more")):
    r = s.post(B + "/api/me/channels", json={"kind": "slack", "name": "More", "url": STUB + pth, "events": ["digest", "other"]})
    assert r.status_code == 201, r.text


def in_app(code):
    """Runs python inside the server container (the app loaded, c = a connection); -> the last line of stdout (or the error)."""
    for _ in range(4):
        r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                            "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nc = connect()\n" + code + "\nc.close()"],
                           capture_output=True, text=True)
        if "deadlock detected" not in r.stderr:  # init_db next to the running server (see calendars_test.py py_in_app)
            break
        time.sleep(2)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-400:]


def scope(who, **kw):
    """chn_scope of who: 'None' = nothing, '' = the full text, else the name in the neutral line."""
    return in_app(f"from kalmido.notify.channels import chn_scope\nwith system_ctx(c):\n    print(repr(chn_scope(c, {who}, **{kw!r})))")


def push(who, title, msg, **kw):
    """notify() of who (the push path to the channels, as the callers use it)."""
    return in_app(f"from kalmido.notify.push import notify\nprint(notify({who}, {title!r}, {msg!r}, **{kw!r}))")


def task(s, lid, title):
    r = s.post(B + "/api/tasks", json={"list_id": lid, "title": title})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def assign(lid, title, who="bob"):
    t = task(A, lid, title)
    assert A.patch(B + f"/api/tasks/{t}", json={"assignee_id": uid[who]}).ok
    return t


def shared(name, org=None, who=("bob",)):
    lid = A.post(B + "/api/lists", json={"name": name, "org_id": org}).json()["id"]
    if org:
        A.patch(B + f"/api/lists/{lid}", json={"org_visibility": "org"})
    for w in who:
        A.put(B + f"/api/lists/{lid}/members", json={"user_id": uid[w] if w != "frida" else FID, "role": "edit"})
    return lid


# ================================================================ 1. a private list shared with bob: the full text (as before)
PL = shared("Shared errands")
assign(PL, "Buy stamps")
x = wait_for(PATH["bob"], "Buy stamps")
check(x and "#t/" in x[0], f"#2867: a private list: the full text with the link {x}")

# ================================================================ 2. health / budget / read later / an organisation's trip: nothing
for life, org in (("health", None), ("budget", None), ("reading", None), ("travel", ORG)):
    lid = shared(f"List {life}", org)
    dbx("UPDATE lists SET life=? WHERE id=?", (life, lid))
    assign(lid, f"Secret {life} words")
    assign(PL, f"Control after {life}")
    check(wait_for(PATH["bob"], f"Control after {life}"), f"control push after {life} arrived")
    check(not [t for t in texts(PATH["bob"]) if f"Secret {life} words" in t], f"#2867: nothing of a {life} list reaches the channel")

# ================================================================ 3. an organisation's list: neutral unless the organisation allows it
OL = shared("Alpha board", ORG)
TO = assign(OL, "Launch pricing")
x = wait_for(PATH["bob"], "New notification in Alpha")
check(x and "#t/" in x[-1], f"#2867: an organisation's list: a neutral line with the link {x[-1:]}")
check(not [t for t in texts(PATH["bob"]) if "Launch pricing" in t], "#2867: ... and never the title")
Ca.post(B + f"/api/tasks/{TO}/comments", json={"body": f"Margin numbers <@{uid['bob']}>"})
assign(PL, "Control after comment")
check(wait_for(PATH["bob"], "Control after comment"), "control push after the comment arrived")
check(not [t for t in texts(PATH["bob"]) if "Margin numbers" in t], "#2867: nor the words of a comment")
check(Bo.patch(B + f"/api/orgs/{ORG}", json={"chn_content": True}).status_code == 403, "a member cannot allow the content: 403")
check(A.get(B + "/api/orgs").json()["orgs"][0].get("chn_content") is False, "the switch is off by default")
check(A.patch(B + f"/api/orgs/{ORG}", json={"chn_content": True}).ok, "the admin allows the content")
assign(OL, "Launch dates")
check(wait_for(PATH["bob"], "Launch dates"), "#2867: with the switch on: the full text")
A.patch(B + f"/api/orgs/{ORG}", json={"chn_content": False})

# ================================================================ 4. a person's "lists" channel: no read-later list
RL = Bo.post(B + "/api/lists", json={"name": "Bob reading", "org_id": None}).json()["id"]
dbx("UPDATE lists SET life='reading' WHERE id=?", (RL,))
BL = Bo.post(B + "/api/lists", json={"name": "Bob chores", "org_id": None}).json()["id"]
task(Bo, RL, "An article to read")
task(Bo, BL, "Control chores")
check(wait_for(PATH["bob"], "Control chores"), "the own list's event arrives")
check(not [t for t in texts(PATH["bob"]) if "An article to read" in t], "#2867: nothing of a read-later list (lists events)")

# ================================================================ 5. a disabled account: its channels stay quiet
# an organisation's channel set up by an admin whose account is disabled later (still admin in the organisation)
A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "admin"})
r = Bo.post(B + f"/api/orgs/{ORG}/channels", json={"kind": "slack", "name": "Bob for Alpha", "url": STUB + "/b2240-org-bob"})
check(r.status_code == 201, f"setup: bob (admin) adds an organisation channel {r.text[:200]}")
r = A.post(B + f"/api/orgs/{ORG}/channels", json={"kind": "slack", "name": "Alice for Alpha", "url": STUB + "/b2240-org-alice"})
check(r.status_code == 201, f"setup: the control channel of alice {r.text[:200]}")
CL = shared("Errands for both", who=("bob", "carol"))
check(A.patch(B + f"/api/users/{uid['bob']}", json={"disabled": True}).ok, "setup: bob disabled")
assign(CL, "After the goodbye")
assign(CL, "Control for carol", who="carol")
check(wait_for(PATH["carol"], "Control for carol"), "carol's push arrived")
check(not [t for t in texts(PATH["bob"]) if "After the goodbye" in t], "#2867: a disabled account's channel gets nothing")
task(A, OL, "Alpha news after the goodbye")
check(wait_for("/b2240-org-alice", "Alpha news after the goodbye"), "the organisation's control channel got it")
check(not [t for t in texts("/b2240-org-bob") if "Alpha news" in t], "#2867: the organisation channel of a disabled admin gets nothing")
check(not dbx("SELECT 1 FROM notify_channel_queue q JOIN notify_channels n ON n.id=q.channel_id WHERE n.user_id=?", (uid["bob"],)),
      "#2867: nothing waits for it either")

# ================================================================ 6. freelancer-matrix: channels -- a person without an organisation
FH = Fi.post(B + "/api/lists", json={"name": "Frida own", "org_id": None}).json()["id"]
task(Fi, FH, "Frida own task")
check(wait_for(PATH["frida"], "Frida own task"), "#2867: a person without an organisation: the events of the own private list")
# a reminder of the own private list (the push path, chn_push): the full text as before
at = (testclock.now().replace(tzinfo=None) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
r = Fi.post(B + "/api/tasks", json={"list_id": FH, "title": "Frida invoice draft", "remind_at": at})
check(r.status_code in (200, 201), f"setup: a due reminder {r.text[:200]}")
x = wait_for(PATH["frida"], "Frida invoice draft", timeout=60)
check(x and "New notification" not in x[-1] and "#t/" in x[-1], f"#2867: a person without an organisation: the reminder with its full text {x[-1:]}")

# ================================================================ 7. 2.240.0 B2 (#2867): only a known, allowed reference carries the text
CM = "/b2240-carol-more"
x = push(uid["carol"], "Payroll notes", "Salary words without a reference", click=f"{B}/#workload", kind="other")
check(not x.startswith("ERR"), f"setup: the push without a reference {x}")
x = wait_for(CM, "New notification in")
check(x and not [t for t in texts(CM) if "Salary words" in t], f"#2867 B2: a push without a reference: only the neutral line {x[-1:]}")
check(scope(uid["carol"], click="#workload") == repr("Kalmido"), "#2867 B2: chn_scope without a reference names the app")
check(scope(uid["carol"], scope="private") == repr(""), "#2867 B2: a private caller keeps the full text")
# 13. the organisation is named only to its members
check(scope(uid["carol"], scope=f"o:{ORG}") == repr("Alpha"), "#2867 B2: a member: the organisation's name")
check(scope(FID, scope=f"o:{ORG}") == repr("Kalmido"), "#2867 B2 (13): no member: the app's name, not the organisation's")
# 5. a disabled account: nothing, also on the push path that skips collab_user (bob was disabled in 5.)
check(scope(uid["bob"], scope="private") == "None", "#2867 B2 (5): chn_scope of a disabled account: nothing")
check(not push(uid["bob"], "Gone", "Words for a disabled account", click=f"{B}/#today", kind="reminder", scope="private").startswith("ERR")
      and not dbx("SELECT 1 FROM notify_channel_queue q JOIN notify_channels n ON n.id=q.channel_id WHERE n.user_id=?", (uid["bob"],)),
      "#2867 B2 (5): a reminder to a disabled account queues nothing for its channel")
# 12. the organisation channel of the disabled admin is off with its reason (the channel loop marks it)
oc = []
for _ in range(50):
    oc = [ch for ch in A.get(B + f"/api/orgs/{ORG}/channels").json()["channels"] if ch["name"] == "Bob for Alpha"]
    if oc and not oc[0]["enabled"]:
        break
    time.sleep(0.3)
check(oc and oc[0]["enabled"] is False and oc[0]["disabled_reason"] == "disabled", f"#2867 B2 (12): off, reason disabled {oc}")

# ---- the summary: to the channels only its numbers, never the titles (a health task among them)
HL = shared("Care plan", who=("carol",))
dbx("UPDATE lists SET life='health' WHERE id=?", (HL,))
today = testclock.now().date().isoformat()
A.put(B + f"/api/lists/{PL}/members", json={"user_id": uid["carol"], "role": "edit"})
TH = assign(HL, "Pill schedule words", who="carol")
TW = assign(PL, "Window cleaning words", who="carol")
for t in (TH, TW):
    assert A.patch(B + f"/api/tasks/{t}", json={"due": today}).ok
dbx("DELETE FROM user_settings WHERE user_id=? AND key='digest_sent'", (uid["carol"],))
assert Ca.patch(B + "/api/settings", json={"digest_time": "00:00"}).ok
x = wait_for(CM, "tasks today", timeout=90)
check(x, f"#2867 B2: the summary reached the channel {x[-1:]}")
check(not [t for t in texts(CM) if "Pill schedule words" in t or "Window cleaning words" in t],
      "#2867 B2: the summary in the channel carries no task titles (health or not)")
assert Ca.patch(B + "/api/settings", json={"digest_time": ""}).ok

# ---- team chat: an organisation's list without chn_content -> neutral; a private list -> the full text; a DM within the organisation -> neutral
OCL = shared("Alpha chat", ORG, who=("carol",))
PCL = shared("Private chat", who=("carol",))
rooms = {r_.get("list_id"): r_["id"] for r_ in A.get(B + "/api/team").json()["rooms"]}
r = A.post(B + f"/api/team/rooms/{rooms[OCL]}/messages", json={"body": f"Org chat secret words <@{uid['carol']}>"})
check(r.ok, f"setup: a message in the organisation's list chat {r.text[:200]}")
r = A.post(B + f"/api/team/rooms/{rooms[PCL]}/messages", json={"body": f"Private chat plain words <@{uid['carol']}>"})
check(r.ok, f"setup: a message in the private list chat {r.text[:200]}")
check(wait_for(CM, "Private chat plain words"), "#2867 B2: a private list's chat: the full text")
check(not [t for t in texts(CM) if "Org chat secret words" in t], "#2867 B2: an organisation list's chat without chn_content: never the words")
check([t for t in texts(CM) if "New notification in Alpha" in t and f"#team/{rooms[OCL]}" in t], "#2867 B2: ... but the neutral line with the link")
dm = A.post(B + "/api/team/dm", json={"user_id": uid["carol"]})
check(dm.ok, f"setup: a DM alice -> carol {dm.text[:200]}")
A.post(B + f"/api/team/rooms/{dm.json()['id']}/messages", json={"body": "Direct secret words"})
A.post(B + f"/api/team/rooms/{rooms[PCL]}/messages", json={"body": f"Control after the DM <@{uid['carol']}>"})
check(wait_for(CM, "Control after the DM"), "control message after the DM arrived")
check(not [t for t in texts(CM) if "Direct secret words" in t], "#2867 B2: a DM between members of an organisation without chn_content: neutral")

# ---- freelancer-matrix: channels -- the own personal office is private (P4): a customer's decision with the full text
FM = "/b2240-frida-more"
poid = in_app(f"from kalmido.office.model import pb_personal\nwith system_ctx(c):\n    print(pb_personal(c, {FID}))\nc.commit()")
check(poid.isdigit(), f"setup: frida's personal office {poid}")
check(scope(FID, scope=f"o:{poid}") == repr(""), "#2867 B2 (3): the own personal office: the full text")
check(scope(uid["carol"], scope=f"o:{poid}") == repr("Kalmido"), "#2867 B2 (3): another person's personal office: neutral, no name")
push(FID, "Approved by the customer", "Studio client: offer words", click=f"{B}/#office/offers/1", scope=f"o:{poid}")
check(wait_for(FM, "Studio client: offer words"), "#2867 B2 (3): a customer's approval in the personal office arrives in full")
push(FID, "Plain", "Frida words without a reference", click=f"{B}/#workload")
check(wait_for(FM, "New notification in Kalmido") and not [t for t in texts(FM) if "Frida words without" in t],
      "#2867 B2: a person without an organisation: a push without a reference is neutral too")

print(f"p2240_b_channels: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
