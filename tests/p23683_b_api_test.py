#!/usr/bin/env python3
# kalmido-suite: now=wed12:00
"""2.368.3 (#2985) API tests: reminders, summaries and their texts follow the person's time zone, own container (start.sh, the
real watchdog, the fake ntfy). Invented names only; all people are without organisation (their private space).
 - a fixed reminder and a reminder before the due time come at the person's hour, ahead of the server's clock and behind it
 - the digest comes at the person's digest_time, "today" is the person's day, quiet hours hold on the person's clock
 - an all-day event reminds at midnight of the person's clock, the briefing dates by the person's day
 - the time format of the push follows the setting; the browser's zone is kept at the very first login only
usage: p23683_b_api_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, done, sess, until, B, H, DATA  # noqa: E402,F401

TOKYO, NEWYORK, KIRI = ZoneInfo("Asia/Tokyo"), ZoneInfo("America/New_York"), ZoneInfo("Pacific/Kiritimati")

if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})


def ntfy():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8")]
    except OSError:
        return []


def pushes(title, topic=None):
    return [x for x in ntfy() if x.get("title") == title and (topic is None or x.get("topic") == topic)]


def person(name, zone, **more):
    uid, s = freelancer(B, A, name)
    assert A.patch(B + f"/api/users/{uid}", json={"ntfy_topic": "t-" + name}).ok
    assert s.patch(B + "/api/settings", json={"push_channel": "ntfy", "tz": zone, **more}).ok
    return uid, s, s.post(B + "/api/lists", json={"name": "Own " + name, "org_id": None}).json()["id"]


def wall(zone, **delta):
    return (testclock.now() + timedelta(**delta)).astimezone(zone)


def stamp(d):
    return d.strftime("%Y-%m-%dT%H:%M")


TI, T, TL = person("tomo", "Asia/Tokyo")
NI, Y, YL = person("nora", "America/New_York")
KI, K, KL = person("kira", "Pacific/Kiritimati", time_format="12")

# ---- a fixed reminder: 09:00 is 09:00 where the person is
r = T.post(B + "/api/tasks", json={"title": "Fixed Tokyo", "list_id": TL, "remind_at": stamp(wall(TOKYO, minutes=-1))})
check(r.ok, "setup " + r.text[:200])
check(until(lambda: pushes("Fixed Tokyo", "t-tomo"), 30), "ahead of the server: the fixed reminder comes at the person's hour")
r = T.post(B + "/api/tasks", json={"title": "Later Tokyo", "list_id": TL, "remind_at": stamp(wall(TOKYO, minutes=40))})
r = Y.post(B + "/api/tasks", json={"title": "Fixed New York", "list_id": YL, "remind_at": stamp(testclock.now() - timedelta(minutes=1))})
check(r.ok, "setup " + r.text[:200])
Y.post(B + "/api/tasks", json={"title": "Now New York", "list_id": YL, "remind_at": stamp(wall(NEWYORK, minutes=-1))})
check(until(lambda: pushes("Now New York", "t-nora"), 30), "behind the server: comes at the person's hour")
check(not pushes("Fixed New York"), "behind the server: the server's hour is hours early, no push yet")
check(not pushes("Later Tokyo"), "not before the person's hour")

# ---- a reminder before the due time, the text in the person's day and format
d = wall(KIRI, minutes=10)
r = K.post(B + "/api/tasks", json={"title": "Due Kiri", "list_id": KL, "due": d.date().isoformat(), "due_time": d.strftime("%H:%M"), "reminders": "30"})
check(r.ok, "setup " + r.text[:200])
check(until(lambda: pushes("Due Kiri", "t-kira"), 30), "the reminder before the due time, on the person's clock " + r.text[:120])
msg = json.dumps(pushes("Due Kiri"))
h12 = f"{(d.hour % 12) or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"
check("today" in msg, "the person's today, a day ahead of the server " + msg[:300])
check(h12 in msg, f"the time format of the setting ({h12}) " + msg[:300])

# ---- digest
check(T.patch(B + "/api/settings", json={"digest_time": wall(TOKYO, minutes=-5).strftime("%H:%M")}).ok, "setup: digest")
T.post(B + "/api/tasks", json={"title": "For the digest", "list_id": TL, "due": wall(TOKYO).date().isoformat()})
check(until(lambda: pushes("Today", "t-tomo"), 30), "the digest comes at the person's time (hours after the server's clock reads it)")
check(Y.patch(B + "/api/settings", json={"digest_time": wall(NEWYORK, minutes=45).strftime("%H:%M")}).ok, "setup: digest behind the server")
Y.post(B + "/api/tasks", json={"title": "For the digest 2", "list_id": YL, "due": wall(NEWYORK).date().isoformat()})

# ---- quiet hours: a nag waits on the person's clock
q = {"quiet_from": wall(TOKYO, hours=-1).strftime("%H:%M"), "quiet_to": wall(TOKYO, hours=1).strftime("%H:%M")}
check(T.patch(B + "/api/settings", json=q).ok, "setup: quiet hours")
day = wall(TOKYO, days=-1).date().isoformat()
r = T.post(B + "/api/tasks", json={"title": "Nag Tokyo", "list_id": TL, "due": day, "nag": "5"})
check(r.ok, "setup: a nag " + r.text[:200])
x = K.post(B + "/api/tasks", json={"title": "Nag Kiri", "list_id": KL, "due": wall(KIRI, days=-1).date().isoformat(), "nag": "5"})
check(x.ok and until(lambda: pushes("Nag Kiri"), 30), "setup: a nag without quiet hours arrives " + x.text[:200])
check(not pushes("Nag Tokyo"), "quiet hours on the person's clock: no nag")

# ---- an all-day event, the briefing
cal = K.post(B + "/api/evcals", json={"name": "Mine"}).json()["id"]
day = wall(KIRI).date()
r = K.post(B + "/api/events", json={"cal_id": cal, "title": "Day Kiri", "all_day": True, "start": day.isoformat(),
                                    "end": (day + timedelta(days=1)).isoformat(), "reminders": [0]})
check(r.ok, "setup: an all-day event " + r.text[:200])
check(until(lambda: pushes("Day Kiri", "t-kira"), 30), "an all-day event reminds at the person's midnight")
check("today" in json.dumps(pushes("Day Kiri")), "... as today")
b = K.get(B + "/api/briefing").json()
check(b.get("date") == day.isoformat(), f"the briefing dates by the person's day {b.get('date')} {day}")

# ---- the first login keeps the browser's zone, later ones never
A.post(B + "/api/users", json={"username": "lena", "display_name": "Lena", "password": "password123", "email": "lena@example.com", "orgs": []})


def login(name, tz):
    s = requests.Session()
    s.headers.update(H)
    assert s.post(B + "/api/auth/login", json={"username": name, "password": "password123", "tz": tz}).ok
    return s


s1 = login("lena", "no/such_zone")
check(s1.get(B + "/api/state").json()["settings"].get("tz") == "", "an unknown zone is left out")
A.post(B + "/api/users", json={"username": "mira", "display_name": "Mira", "password": "password123", "email": "mira@example.com", "orgs": []})
s2 = login("mira", "Asia/Tokyo")
check(s2.get(B + "/api/state").json()["settings"].get("tz") == "Asia/Tokyo", "the first login keeps the browser's zone")
s3 = login("mira", "America/New_York")
check(s3.get(B + "/api/state").json()["settings"].get("tz") == "Asia/Tokyo", "a later login changes nothing")
sys.exit(done("p23683_b_api"))
