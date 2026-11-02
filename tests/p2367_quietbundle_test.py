#!/usr/bin/env python3
"""2.367 API tests (own container with the two push switches on, test clock Wednesday 10:00):
 - #2966 the quiet hours hold every push except priority 5, the push test and what the person set themselves (digest, focus
   timer); one summary when they end, the bell keeps its entry; quiet hours, digest and the all-day time on the person's clock
 - #2967 from the third push of one actor inside the gap one summary ("assigned you 6 tasks", opens the list), an @mention
   always comes; chat: one push per room and gap, then "3 new messages", none when they were read; all-day reminders of one
   tick as one message, a reminder with a time of day alone
freelancer-matrix: n/a (no new route; the rules are per person, the people here are as good as without an organisation)
usage: p2367_quietbundle_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from zoneinfo import ZoneInfo

import requests

from kt import B, CT, DATA, H, check, done, fresh, sess, until
from testclock import now, today

ON = os.environ.get("P2367_SWITCH", "1")  # P2367_SWITCH=0: the behaviour before the fix, the suite must go red
fresh(env={"KALMIDO_QUIET_PUSH": ON, "KALMIDO_PUSH_BUNDLE": ON}, prefix="P2367")
GAP = 3.2
FAR = "Pacific/Auckland"


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def bob(n0=0):
    return [p for p in pushes()[n0:] if p.get("topic") == "t-bob"]


def with_(n0, text, t=12):
    return until(lambda: [p for p in bob(n0) if text in (p.get("msg") or "")], t) or []


def in_ct(py):
    r = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\n" + py], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]


s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
BOB = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com",
                                     "ntfy_topic": "t-bob"}).json()["id"]
Bo = sess("bob")
OFF = {"quiet_from": "", "quiet_to": ""}
assert Bo.patch(B + "/api/settings", json={"lang": "en", **OFF}).ok
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
L = A.post(B + "/api/lists", json={"name": "Launch", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok


def task(title, **k):
    return A.post(B + "/api/tasks", json={"title": title, "list_id": L, **k}).json()["id"]


# ================================================================== #2967 one actor, many tasks
ids = [task(f"Mass {i}") for i in range(6)]
n0 = len(pushes())
assert A.post(B + "/api/tasks/batch", json={"ids": ids, "action": "patch", "data": {"assignee_id": BOB}}).ok
sm = with_(n0, "assigned you 6 tasks")
check(len(sm) == 1 and sm[0].get("title") == "Alice", f"#2967: one summary with the whole count {sm}")
check(f"#l/{L}" in (sm[0].get("click") or "") if sm else False, f"#2967: the summary opens the list {sm}")
check(len(bob(n0)) == 3, f"#2967: two single pushes + the summary, not six {[p.get('title') for p in bob(n0)]}")
time.sleep(GAP)
n0 = len(pushes())
T = task("Mentions", assignee_id=BOB)
for i in range(3):
    assert A.post(B + f"/api/tasks/{task('M%d' % i, assignee_id=BOB)}/comments", json={"body": "note"}).ok
assert A.post(B + f"/api/tasks/{T}/comments", json={"body": f"<@{BOB}> look here"}).ok
check(with_(n0, "mentioned"), f"#2967: an @mention is never held by the person gate {[p.get('msg') for p in bob(n0)]}")
time.sleep(GAP + 2)

# ================================================================== #2967 chat
DM = A.post(B + "/api/team/dm", json={"user_id": BOB}).json()["id"]
n0 = len(pushes())
for i in range(4):
    assert A.post(B + f"/api/team/rooms/{DM}/messages", json={"body": f"chat {i}"}).ok
sm = with_(n0, "3 new messages")
check(len(sm) == 1 and sm[0].get("title") == "Alice", f"#2967: the chat summary {[(p.get('title'), p.get('msg')) for p in bob(n0)]}")
check(len(bob(n0)) == 2, f"#2967: one push + one summary, not four {[p.get('msg') for p in bob(n0)]}")
time.sleep(GAP + 1)
n0 = len(pushes())
m = None
for i in range(3):
    m = A.post(B + f"/api/team/rooms/{DM}/messages", json={"body": f"read {i}"}).json()
assert Bo.post(B + f"/api/team/rooms/{DM}/read", json={"last_id": m["id"]}).ok
time.sleep(GAP + 2)
check(len(bob(n0)) == 1, f"#2967: no summary for what was read meanwhile {[p.get('msg') for p in bob(n0)]}")

# ================================================================== #2966 quiet hours for all pushes
t = now()
win = {"quiet_from": (t - timedelta(hours=1)).strftime("%H:%M"), "quiet_to": (t + timedelta(hours=1)).strftime("%H:%M")}
assert Bo.patch(B + "/api/settings", json=win).ok
Q = task("Night task")
n0 = len(pushes())
assert A.post(B + "/api/tasks/batch", json={"ids": [Q], "action": "patch", "data": {"assignee_id": BOB}}).ok
check(until(lambda: "Night task" in json.dumps(Bo.get(B + "/api/news").json()), 5), "#2966: the bell keeps the entry")
assert A.post(B + f"/api/tasks/{Q}/comments", json={"body": "at night"}).ok
time.sleep(2)
check(not bob(n0), f"#2966: an assignment and a comment push nothing in the quiet hours {bob(n0)}")
in_ct(f"from kalmido.notify.push import notify\nnotify({BOB}, 'Urgent', 'prio five', '5')\nnotify({BOB}, 'Focus done', 'timer', '4', quiet=False)\nnotify({BOB}, 'Held', 'plain', '4')")
check(with_(n0, "prio five") and with_(n0, "timer"), f"#2966: priority 5 and a focus timer pass {bob(n0)}")
check(not with_(n0, "plain", 1), "#2966: a plain push is held")
assert Bo.patch(B + "/api/settings", json=OFF).ok
sm = with_(n0, "notifications during the quiet hours")
check(len(sm) == 1, f"#2966: one summary when they end {[p.get('msg') for p in bob(n0)]}")
time.sleep(2.5)
check(len(with_(n0, "during the quiet hours", 1)) == 1, "#2966: the summary comes once")

# ================================================================== #2966 the person's clock
far = t.astimezone(ZoneInfo(FAR))
fwin = {"quiet_from": (far - timedelta(hours=1)).strftime("%H:%M"), "quiet_to": (far + timedelta(hours=1)).strftime("%H:%M")}
assert Bo.patch(B + "/api/settings", json=fwin).ok
time.sleep(GAP)
n0 = len(pushes())
in_ct(f"from kalmido.notify.push import notify\nnotify({BOB}, 'Zone', 'server clock', '4')")
check(with_(n0, "server clock"), "#2966: without a zone the hours are the server's (not in them now)")
assert Bo.patch(B + "/api/settings", json={"tz": FAR}).ok
n0 = len(pushes())
in_ct(f"from kalmido.notify.push import notify\nnotify({BOB}, 'Zone', 'far clock', '4')")
check(not with_(n0, "far clock", 2), "#2966: with the zone the same hours hold it")
assert Bo.patch(B + "/api/settings", json=OFF).ok
with_(n0, "during the quiet hours")

# digest at a time that has passed only on the person's clock (and inside the quiet hours: their own choice)
D = task("Digest item", assignee_id=BOB, due=today().isoformat())
assert Bo.patch(B + "/api/settings", json={"tz": "", "digest_time": "23:59", **fwin}).ok
n0 = len(pushes())
time.sleep(2.5)
check(not with_(n0, "Digest item", 0.5), "#2966: the digest time has not come on the server's clock")
assert Bo.patch(B + "/api/settings", json={"tz": FAR, "digest_time": (far - timedelta(minutes=30)).strftime("%H:%M")}).ok
check(with_(n0, "Digest item"), "#2966: the digest goes at the person's time, also inside their quiet hours")
assert Bo.patch(B + "/api/settings", json={"digest_time": "", "tz": "", **OFF}).ok

# ================================================================== #2967 + #2966 all-day reminders
al = (far - timedelta(minutes=5)).strftime("%H:%M")
assert Bo.patch(B + "/api/settings", json={"allday_time": al}).ok
assert Bo.patch(B + "/api/settings", json={"tz": ""}).ok
RS = [task(f"Allday {i}", assignee_id=BOB, due=today().isoformat(), reminders="0") for i in range(3)]
TT = task("Timed one", assignee_id=BOB, due=today().isoformat(), due_time=(t - timedelta(minutes=2)).strftime("%H:%M"), reminders="0")
time.sleep(GAP)
n0 = len(pushes())
assert Bo.patch(B + "/api/settings", json={"tz": FAR}).ok
sm = with_(n0, "3 tasks today")
check(len(sm) == 1 and all(f"Allday {i}" in sm[0]["msg"] for i in range(3)), f"#2967: three all-day reminders are one message, #2966 at the person's all-day time {[p.get('msg') for p in bob(n0)]}")
check(not [p for p in bob(n0) if (p.get("title") or "").startswith("Allday")], "#2967: no single pushes beside it")
check(until(lambda: [p for p in pushes() if p.get("title") == "Timed one"], 8), "#2967: a reminder with a time of day stays its own push")

sys.exit(done("p2367_quietbundle"))
