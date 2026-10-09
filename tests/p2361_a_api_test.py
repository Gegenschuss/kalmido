#!/usr/bin/env python3
"""2.36.1 API tests, part A (#1127 #956): which calendars show where. Own container (start.sh).
 - the four user settings cal_tasks ("1"|"0"), cal_lists_hidden (json list of list ids), today_cals_hidden and plan_cals_off
   (json lists of calendar keys "e:<own calendar id>" | "s:<subscription id>"): defaults (everything on), stored per user,
   doubles dropped, bad values 400, lists accepted as json text or as a list
 - GET /api/dayplan: the events of subscriptions AND own calendars count as busy; a calendar in plan_cals_off is left out
   (its slot becomes free), an all-day event is listed but never busy; a subscription hidden from the calendar is out too
 - the agent's day plan (POST /api/proposals kind dayplan) gets the same events as the built-in planner
 - "Events today" data: GET /api/calendars/events returns the visible calendars (the Today switch is a client filter on the
   same answer, the setting travels in /api/state); a hidden subscription sends nothing
 - another person's settings are untouched
usage: p2361_a_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def get(self, p, **k):
        return requests.get(V + p, headers=self.h, timeout=30, **k)


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,events,timeline,collab,comments", "work_start": "08:00", "work_end": "12:00"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": "cal,events"})

# ================================================================== the settings
st = A.get(B + "/api/state").json()["settings"]
check(st.get("cal_tasks") == "1" and st.get("cal_lists_hidden") == "[]" and st.get("today_cals_hidden") == "[]" and st.get("plan_cals_off") == "[]",
      f"defaults: tasks on, nothing hidden anywhere ({ {k: st.get(k) for k in ('cal_tasks', 'cal_lists_hidden', 'today_cals_hidden', 'plan_cals_off')} })")
L1 = A.post(B + "/api/lists", json={"name": "Work"}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Home"}).json()["id"]
r = A.patch(B + "/api/settings", json={"cal_tasks": "0", "cal_lists_hidden": [L2, L2, L1], "today_cals_hidden": ["s:7", "e:3", "s:7"], "plan_cals_off": json.dumps(["e:3"])})
check(r.ok, f"settings stored ({r.status_code} {r.text[:120]})")
st = A.get(B + "/api/state").json()["settings"]
check(st["cal_tasks"] == "0" and json.loads(st["cal_lists_hidden"]) == sorted([L1, L2]) and json.loads(st["today_cals_hidden"]) == ["e:3", "s:7"]
      and json.loads(st["plan_cals_off"]) == ["e:3"], f"stored sorted and without doubles (list or json text) ({st['cal_lists_hidden']} {st['today_cals_hidden']} {st['plan_cals_off']})")
check(A.patch(B + "/api/settings", json={"cal_tasks": "true"}).ok and A.get(B + "/api/state").json()["settings"]["cal_tasks"] == "1", "cal_tasks takes true -> 1")
for k, v in (("cal_lists_hidden", ["x"]), ("cal_lists_hidden", "nope"), ("cal_lists_hidden", [0]), ("cal_lists_hidden", [True]), ("today_cals_hidden", ["x:1"]),
             ("today_cals_hidden", ["e:0"]), ("today_cals_hidden", [1]), ("plan_cals_off", "{}"), ("plan_cals_off", ["s:1", 2]), ("cal_tasks", "yes"),
             ("plan_cals_off", ["s:" + "9" * 20])):
    check(A.patch(B + "/api/settings", json={k: v}).status_code == 400, f"bad value 400: {k} = {v!r}")
check(A.patch(B + "/api/settings", json={"cal_lists_hidden": list(range(1, 502))}).status_code == 400, "more than 500 entries 400")
check(A.patch(B + "/api/settings", json={"plan_cals_off": ""}).ok, "'' = an empty list")
check(A.patch(B + "/api/settings", json={"today_cals_hidden": None}).ok, "null = an empty list")
st = A.get(B + "/api/state").json()["settings"]
check(st["today_cals_hidden"] == "[]" and st["plan_cals_off"] == "[]", "emptied")
sb = Bo.get(B + "/api/state").json()["settings"]
check(sb["cal_tasks"] == "1" and sb["cal_lists_hidden"] == "[]", "another person's settings untouched")
check(A.patch(B + "/api/settings", json={"cal_tasks": "1", "cal_lists_hidden": []}).ok, "back to the defaults")

# ================================================================== the day planner: subscriptions + own calendars
D = date.today() + timedelta(days=7)
while D.weekday() != 2:  # a Wednesday in the future: the window is the whole working day
    D += timedelta(days=1)
DS = D.isoformat()
T1 = A.post(B + "/api/tasks", json={"title": "Report", "list_id": L1, "due": DS, "priority": 5, "duration": 60}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Tidy desk", "list_id": L1, "due": DS, "duration": 30}).json()["id"]


def sub(name, color="#2dd4bf", visible=1):
    dbx("INSERT INTO cal_subs(user_id,kind,name,color,visible,url,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (ALICE, "ics", name, color, visible, "x", "ok", "2026-01-01T00:00:00Z"))
    return dbx("SELECT MAX(id) FROM cal_subs")[0][0]


def sub_event(sid, title, h0, h1, day=D, all_day=False):
    if all_day:
        dbx("INSERT INTO cal_events(sub_id,uid,title,all_day,start,end,d0,d1) VALUES(?,?,?,?,?,?,?,?)",
            (sid, title, title, 1, day.isoformat(), (day + timedelta(days=1)).isoformat(), day.isoformat(), day.isoformat()))
        return
    a = datetime(day.year, day.month, day.day, h0, 0).astimezone().astimezone(timezone.utc)
    b = datetime(day.year, day.month, day.day, h1, 0).astimezone().astimezone(timezone.utc)
    dbx("INSERT INTO cal_events(sub_id,uid,title,all_day,start,end,d0,d1) VALUES(?,?,?,?,?,?,?,?)",
        (sid, title, title, 0, a.strftime("%Y-%m-%dT%H:%M:%SZ"), b.strftime("%Y-%m-%dT%H:%M:%SZ"), day.isoformat(), day.isoformat()))


S_WORK = sub("Work feed")
S_FAM = sub("Family feed", "#f87171")
S_OFF = sub("Hidden feed", "#94a3b8", visible=0)
sub_event(S_WORK, "Client call", 10, 11)
sub_event(S_FAM, "School play", 9, 10)
sub_event(S_FAM, "Grandma's birthday", 0, 0, all_day=True)
sub_event(S_OFF, "Secret meeting", 8, 9)
C_OWN = A.post(B + "/api/evcals", json={"name": "Mine", "color": "#60a5fa"}).json()["id"]
r = A.post(B + "/api/events", json={"title": "Dentist", "cal_id": C_OWN, "start": f"{DS}T11:00", "end": f"{DS}T12:00"})
check(r.status_code == 201, f"own event created ({r.status_code} {r.text[:100]})")
A.post(B + "/api/events", json={"title": "Holiday fair", "cal_id": C_OWN, "all_day": True, "start": DS, "end": (D + timedelta(days=1)).isoformat()})


def plan(s=A, **q):
    r = s.get(B + "/api/dayplan", params={"date": DS, **q})
    assert r.ok, r.text
    return r.json()


def busy(p):
    return sorted((e["title"], e["start"], e["end"]) for e in p["events"] if not e["all_day"])


p = plan()
check(busy(p) == [("Client call", "10:00", "11:00"), ("Dentist", "11:00", "12:00"), ("School play", "09:00", "10:00")],
      f"planner: timed events of both subscriptions AND the own calendar are busy, the hidden feed is not ({busy(p)})")
check({e["title"] for e in p["events"] if e["all_day"]} == {"Grandma's birthday", "Holiday fair"}, "planner: all-day events listed")
slots = {x["task_id"]: (x["start"], x["end"]) for x in p["plan"]}
check(slots.get(T1) == ("08:00", "09:00") and T2 not in slots and T2 in {x["task_id"] for x in p["nofit"]},
      f"planner: 08-09 is the only free hour (Report), Tidy desk does not fit ({slots} nofit={[x['task_id'] for x in p['nofit']]})")

# the family feed does not count when planning (#956): 09-10 becomes free (the all-day birthday was never busy)
check(A.patch(B + "/api/settings", json={"plan_cals_off": [f"s:{S_FAM}"]}).ok, "plan_cals_off: the family feed")
p = plan()
check(busy(p) == [("Client call", "10:00", "11:00"), ("Dentist", "11:00", "12:00")] and "Grandma's birthday" not in {e["title"] for e in p["events"]},
      f"planner: the family feed is left out, timed and all-day ({busy(p)})")
slots = {x["task_id"]: (x["start"], x["end"]) for x in p["plan"]}
check(slots.get(T1) == ("08:00", "09:00") and slots.get(T2) == ("09:00", "09:30"), f"planner: Tidy desk now fits at 09:00 ({slots})")
# the own calendar too: 11-12 free
check(A.patch(B + "/api/settings", json={"plan_cals_off": [f"s:{S_FAM}", f"e:{C_OWN}"]}).ok, "plan_cals_off: + the own calendar")
p = plan()
check(busy(p) == [("Client call", "10:00", "11:00")] and "Holiday fair" not in {e["title"] for e in p["events"]}, f"planner: the own calendar is left out ({busy(p)})")
check(p["free_min"] == 180 - 90, f"planner: 3 free hours minus the planned 90 minutes ({p['free_min']})")
# a key of a calendar that does not exist is harmless; a subscription hidden from the calendar is out anyway
check(A.patch(B + "/api/settings", json={"plan_cals_off": ["s:999999", "e:999999"]}).ok, "unknown keys are stored")
p = plan()
check(len(busy(p)) == 3 and "Secret meeting" not in {e["title"] for e in p["events"]}, "planner: everything visible counts again, the hidden feed never")
# "show in my calendar" off (the same field as the settings switch) = out of the planner as well
check(A.patch(B + f"/api/calendars/{S_WORK}", json={"visible": False}).ok, "the work feed hidden from the calendar")
check(A.patch(B + f"/api/evcals/{C_OWN}", json={"hidden": True}).ok, "the own calendar hidden from the calendar")
p = plan()
check(busy(p) == [("School play", "09:00", "10:00")], f"planner: hidden calendars do not count ({busy(p)})")
A.patch(B + f"/api/calendars/{S_WORK}", json={"visible": True})
A.patch(B + f"/api/evcals/{C_OWN}", json={"hidden": False})
check(Bo.get(B + "/api/dayplan", params={"date": DS}).json()["events"] == [], "bob's planner sees none of alice's calendars")

# ================================================================== the agent plans the day: the same events
ag = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"})
AG, agt = ag.json()["id"], ag.json()["token"]
A.patch(B + f"/api/admin/agents/{AG}", json={"proposals": "all"})
ac = Api(agt)
check(A.patch(B + "/api/settings", json={"plan_cals_off": [f"s:{S_FAM}"]}).ok, "plan_cals_off: the family feed (for the agent)")
r = A.post(B + "/api/proposals", json={"agent_id": AG, "kind": "dayplan", "date": DS})
check(r.status_code == 201 and r.json()["kind"] == "dayplan", f"day plan request: 201 ({r.text[:200]})")
J = r.json()["id"]
inp = ac.get(f"/agent/jobs/{J}").json()["input"]
got = sorted((e["title"], e["start"], e["end"]) for e in inp["events"] if not e["all_day"])
check(got == [("Client call", "10:00", "11:00"), ("Dentist", "11:00", "12:00")] and "School play" not in json.dumps(inp["events"]),
      f"agent input: the same events as the built-in planner, the family feed left out ({got})")
check(inp["builtin"]["plan"] and {x["task_id"] for x in inp["builtin"]["plan"]} == {T1, T2}, "agent input: the built-in plan as a hint (both tasks fit)")
A.patch(B + "/api/settings", json={"plan_cals_off": []})

# ================================================================== "Events today" data
T0 = date.today()
sub_event(S_WORK, "Standup today", 9, 10, day=T0)
sub_event(S_OFF, "Hidden today", 9, 10, day=T0)
A.post(B + "/api/events", json={"title": "Lunch today", "cal_id": C_OWN, "start": f"{T0.isoformat()}T12:00", "end": f"{T0.isoformat()}T13:00"})
j = A.get(B + f"/api/calendars/events?from={T0}&to={T0}").json()
titles = {e["title"] for e in j["events"]}
check({"Standup today", "Lunch today"} <= titles and "Hidden today" not in titles, f"events of the day: visible subscriptions + own, nothing of a hidden feed ({titles})")
check(set(map(int, j["subs"])) == {S_WORK, S_FAM} and C_OWN in set(map(int, j["evcals"])), "the answer names the visible subscriptions and the own calendars")
check(A.patch(B + "/api/settings", json={"today_cals_hidden": [f"s:{S_WORK}", f"e:{C_OWN}"]}).ok, "today_cals_hidden stored")
j2 = A.get(B + f"/api/calendars/events?from={T0}&to={T0}").json()
check({e["title"] for e in j2["events"]} == titles, "the Today switch changes nothing on the server (the calendar views keep every event)")
check(json.loads(A.get(B + "/api/state").json()["settings"]["today_cals_hidden"]) == sorted([f"e:{C_OWN}", f"s:{S_WORK}"]), "the Today switch travels with the state")
A.patch(B + "/api/settings", json={"today_cals_hidden": []})
# the account export carries the new settings
r = A.get(B + "/api/export.json")
check(r.ok and "plan_cals_off" in r.text and "today_cals_hidden" in r.text, f"account export carries the new settings ({r.status_code})")

print(f"p2361_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
