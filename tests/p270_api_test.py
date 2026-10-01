#!/usr/bin/env python3
"""2.7.0 API, own container (start.sh):
#412 reminders up to a year before the due date (2 weeks, 1 month, 366 days; more: 400) and the deadline flag of a task
(0 / 1 / 2 = on Today from the first reminder; web API + token API deadline / deadline_in_today);
#413 nags: tasks.nag ('' = the list's default, off, 5 / 10 / 15 / 30 / 60 / 1d), lists.nag (owner only), the quiet hours
(quiet_from / quiet_to), the scheduler (a push from the first reminder on / the due time, once per interval: a tick, a
restart or a reminder of the same moment never sends a second; a new date starts over; nothing for completed, deleted,
archived tasks, a muted list bell, the matrix row "nag" off, quiet hours; push buttons Done / Stop reminding / Snooze);
the token API (task nag, list nag via PATCH /api/v1/lists/<id>) + OpenAPI;
#407 hours per day: the admin's instance value time_day_h (default 8), a list's own day_hours (owner, same for every
member), /api/state time_lists {list: {s, b}} with the tracked seconds and the "Budget h" sum; K21: the setup's start
(sample / a project type) still works; #405 S4: purge-done still exists for the Completed view.
usage: p270_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
TZ = ZoneInfo("Europe/Berlin")


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": "password123"})
    assert r.ok, r.text
    return s


def log():
    p = os.path.join(DATA, "ntfy.log")
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()] if os.path.exists(p) else []


def clear():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


def db(sql, args=()):  # the isolated test database (bind-mounted data dir), to age nag_at like time passing
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def age(tid, minutes):
    """Pretend the last nag of task tid was `minutes` ago (keeps its due-date key)."""
    raw = db("SELECT nag_at FROM tasks WHERE id=?", (tid,))[0][0]
    key = raw.partition("|")[0]
    db("UPDATE tasks SET nag_at=? WHERE id=?", (f"{key}|{(datetime.now(TZ) - timedelta(minutes=minutes)).isoformat()}", tid))


def nags(title):
    return [x for x in log() if x["title"] == title]


def wait_for(fn, s=6.0):
    t0 = time.time()
    while time.time() - t0 < s:
        if fn():
            return True
        time.sleep(0.3)
    return fn()


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
requests.post(B + "/api/auth/setup", headers=H, json={"username": "alice", "display_name": "Alice", "password": "password123"})
A = sess("alice")
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
Bo = sess("bob")
for x in (A, Bo):
    x.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "push_channel": "ntfy"})
now = datetime.now(TZ)
today = now.date().isoformat()

# ================================================================== quiet hours (settings)
s = Bo.get(B + "/api/state").json()["settings"]
check(s.get("quiet_from") == "22:00" and s.get("quiet_to") == "07:00", f"quiet hours default 22:00-07:00: {s.get('quiet_from')} {s.get('quiet_to')}")
check(Bo.patch(B + "/api/settings", json={"quiet_from": "23:15"}).ok, "quiet_from stored")
check(Bo.patch(B + "/api/settings", json={"quiet_from": "25:00"}).status_code == 400, "quiet_from invalid 400")
check(Bo.patch(B + "/api/settings", json={"quiet_from": "", "quiet_to": ""}).ok, "quiet hours off ('' + '')")
check(A.patch(B + "/api/settings", json={"quiet_from": "", "quiet_to": ""}).ok, "alice: quiet hours off")

# ================================================================== #412 reminders + deadline
L = Bo.post(B + "/api/lists", json={"name": "Taxes"}).json()["id"]
t = Bo.post(B + "/api/tasks", json={"title": "File return", "list_id": L, "due": (now + timedelta(days=60)).date().isoformat(),
                                     "reminders": "20160,43200", "deadline": 1}).json()
check(t.get("reminders") == "20160,43200" and t.get("deadline") == 1 and t.get("nag") == "", f"2 weeks + 1 month, deadline 1: {t.get('reminders')} {t.get('deadline')}")
check("nag_at" not in t, "nag_at never leaves the server")
T1 = t["id"]
check(Bo.patch(B + f"/api/tasks/{T1}", json={"reminders": [366 * 1440]}).ok, "366 days before: ok")
check(Bo.patch(B + f"/api/tasks/{T1}", json={"reminders": [367 * 1440]}).status_code == 400, "367 days: 400")
check(Bo.patch(B + f"/api/tasks/{T1}", json={"deadline": 2}).ok and Bo.get(B + f"/api/tasks/{T1}").json()["deadline"] == 2, "deadline 2 (on Today from the first reminder)")
check(Bo.patch(B + f"/api/tasks/{T1}", json={"deadline": 3}).status_code == 400, "deadline 3: 400")
check(Bo.patch(B + f"/api/tasks/{T1}", json={"deadline": False}).ok and Bo.get(B + f"/api/tasks/{T1}").json()["deadline"] == 0, "deadline false -> 0")
check(Bo.patch(B + f"/api/tasks/{T1}", json={"deadline": True}).ok and Bo.get(B + f"/api/tasks/{T1}").json()["deadline"] == 1, "deadline true -> 1")
check(Bo.patch(B + f"/api/settings", json={"default_reminder": "20160"}).ok, "default reminder 2 weeks")

# ================================================================== #413 nag values, list default
for v in ("", "off", "5", "10", "15", "30", "60", "1d"):
    check(Bo.patch(B + f"/api/tasks/{T1}", json={"nag": v}).ok, f"task nag {v!r} ok")
for v in ("2", "daily", 5, "7d"):
    check(Bo.patch(B + f"/api/tasks/{T1}", json={"nag": v}).status_code == 400, f"task nag {v!r}: 400")
check(Bo.patch(B + f"/api/lists/{L}", json={"nag": "1d"}).ok and next(x for x in Bo.get(B + "/api/state").json()["lists"] if x["id"] == L)["nag"] == "1d", "list nag 1d (owner)")
check(Bo.patch(B + f"/api/lists/{L}", json={"nag": "3"}).status_code == 400, "list nag invalid 400")
check(Bo.patch(B + f"/api/lists/{L}", json={"nag": "off"}).ok and next(x for x in Bo.get(B + "/api/state").json()["lists"] if x["id"] == L)["nag"] == "", "list nag off -> ''")
Bo.put(B + f"/api/lists/{L}/members", json={"user_id": 1, "role": "edit"})
check(A.patch(B + f"/api/lists/{L}", json={"nag": "5"}).status_code == 403, "list nag: a member gets 403")
check(A.patch(B + f"/api/lists/{L}", json={"day_hours": 6}).status_code == 403, "day_hours: a member gets 403")

# ================================================================== #413 the scheduler
clear()
due_t = (now - timedelta(minutes=2)).strftime("%H:%M")
due_d = (now - timedelta(minutes=2)).date().isoformat()
N1 = Bo.post(B + "/api/tasks", json={"title": "Nag me", "list_id": L, "due": due_d, "due_time": due_t, "nag": "5", "priority": 3}).json()["id"]
check(wait_for(lambda: len(nags("Nag me")) == 1), f"a nag arrives from the due time on (no reminders): {len(nags('Nag me'))}")
time.sleep(2.5)
check(len(nags("Nag me")) == 1, "no second one within the interval (ticks every second)")
n0 = (nags("Nag me") or [{}])[0]
check("Still open" in (n0.get("msg") or "") and f"#t/{N1}" in (n0.get("click") or ""), f"text + link: {n0.get('msg')!r}")
acts = n0.get("actions") or ""
check("Done" in acts and f"#nagoff/{N1}" in acts and f"#snooze/{N1}" in acts and "Stop reminding" in acts, f"buttons Done / Stop reminding / Snooze: {acts!r}")
age(N1, 6)
check(wait_for(lambda: len(nags("Nag me")) == 2), "after the interval: the next one")
time.sleep(1.5)
check(len(nags("Nag me")) == 2, "and only one")
# quiet hours covering now: nothing; they end: it comes
hm = lambda d: d.strftime("%H:%M")
Bo.patch(B + "/api/settings", json={"quiet_from": hm(now - timedelta(hours=1)), "quiet_to": hm(datetime.now(TZ) + timedelta(hours=1))})
age(N1, 6)
time.sleep(2.5)
check(len(nags("Nag me")) == 2, "quiet hours: no nag")
Bo.patch(B + "/api/settings", json={"quiet_from": "", "quiet_to": ""})
check(wait_for(lambda: len(nags("Nag me")) == 3), "quiet hours over: the nag comes")
# the matrix row "nag" off: nothing
Bo.patch(B + "/api/settings", json={"notify": json.dumps({"nag": {"push": 0}})})
st = Bo.get(B + "/api/state").json()
check(st["notify"]["nag"] == {"news": None, "push": False}, f"matrix row nag (push only): {st['notify'].get('nag')}")
age(N1, 6)
time.sleep(2.5)
check(len(nags("Nag me")) == 3, "matrix off: no nag")
Bo.patch(B + "/api/settings", json={"notify": json.dumps({"nag": {"push": 1}})})
check(wait_for(lambda: len(nags("Nag me")) == 4), "matrix on again: the nag comes")
# a muted list bell: nothing
check(Bo.put(B + f"/api/lists/{L}/bell", json={"mode": "mute"}).ok, "bell mute")
age(N1, 6)
time.sleep(2.5)
check(len(nags("Nag me")) == 4, "muted list: no nag")
Bo.put(B + f"/api/lists/{L}/bell", json={"mode": "default"})
check(wait_for(lambda: len(nags("Nag me")) == 5), "bell back: the nag comes")
# Stop reminding (what the push button does): nothing more
check(Bo.patch(B + f"/api/tasks/{N1}", json={"nag": "off"}).ok, "nag off")
age(N1, 6)
time.sleep(2.5)
check(len(nags("Nag me")) == 5, "nag off: nothing")
# the list's default nags its tasks; a task 'off' stays quiet
Bo.patch(B + f"/api/lists/{L}", json={"nag": "10"})
N2 = Bo.post(B + "/api/tasks", json={"title": "List default", "list_id": L, "due": due_d, "due_time": due_t}).json()["id"]
check(wait_for(lambda: len(nags("List default")) == 1), "the list's default nags a task without its own choice")
time.sleep(2)
check(len(nags("Nag me")) == 5, "...but not the task set to off")
# a new date starts over (snooze moves it): the key changes, a nag comes at the new time, not before
fut = (datetime.now(TZ) + timedelta(hours=3))
check(Bo.patch(B + f"/api/tasks/{N2}", json={"due": fut.date().isoformat(), "due_time": hm(fut)}).ok, "moved 3 h later")
age(N2, 30)
time.sleep(2.5)
check(len(nags("List default")) == 1, "a later date: no nag before its time")
# completed / deleted / archived: nothing
N3 = Bo.post(B + "/api/tasks", json={"title": "Done stops", "list_id": L, "due": due_d, "due_time": due_t, "nag": "5"}).json()["id"]
check(wait_for(lambda: len(nags("Done stops")) == 1), "nag of N3")
Bo.post(B + f"/api/tasks/{N3}/complete", json={})
age(N3, 6)
time.sleep(2.5)
check(len(nags("Done stops")) == 1, "completed: no more nags")
N4 = Bo.post(B + "/api/tasks", json={"title": "Deleted stops", "list_id": L, "due": due_d, "due_time": due_t, "nag": "5"}).json()["id"]
check(wait_for(lambda: len(nags("Deleted stops")) == 1), "nag of N4")
Bo.delete(B + f"/api/tasks/{N4}")
age(N4, 6)
time.sleep(2.5)
check(len(nags("Deleted stops")) == 1, "deleted: no more nags")
L2 = Bo.post(B + "/api/lists", json={"name": "Archive me"}).json()["id"]
N5 = Bo.post(B + "/api/tasks", json={"title": "Archived stops", "list_id": L2, "due": due_d, "due_time": due_t, "nag": "5"}).json()["id"]
check(wait_for(lambda: len(nags("Archived stops")) == 1), "nag of N5")
Bo.patch(B + f"/api/lists/{L2}", json={"archived": True})
age(N5, 6)
time.sleep(2.5)
check(len(nags("Archived stops")) == 1, "archived list: no more nags")
# a reminder at the same moment counts as the nag (one push, not two); the next nag an interval after it
N6 = Bo.post(B + "/api/tasks", json={"title": "Reminder first", "list_id": L, "due": due_d, "due_time": hm(datetime.now(TZ) + timedelta(minutes=1)),
                                      "reminders": "2", "nag": "15"}).json()["id"]
check(wait_for(lambda: len(nags("Reminder first")) == 1), "the reminder fires")
time.sleep(2.5)
r6 = nags("Reminder first")
check(len(r6) == 1 and "Still open" not in r6[0]["msg"], f"one push (the reminder), no extra nag: {[x['msg'] for x in r6]}")
check(db("SELECT nag_at FROM tasks WHERE id=?", (N6,))[0][0].count("|") == 1, "the reminder set nag_at")
age(N6, 16)
check(wait_for(lambda: len(nags("Reminder first")) == 2 and "Still open" in nags("Reminder first")[1]["msg"]), "the nag an interval after the reminder")
# a deadline says so in the nag
N7 = Bo.post(B + "/api/tasks", json={"title": "Deadline nag", "list_id": L, "due": due_d, "due_time": due_t, "nag": "1d", "deadline": 1}).json()["id"]
check(wait_for(lambda: len(nags("Deadline nag")) == 1 and nags("Deadline nag")[0]["msg"].startswith("Deadline")), "deadline: the nag starts with Deadline")
age(N7, 60 * 23)
time.sleep(2.5)
check(len(nags("Deadline nag")) == 1, "daily: not after 23 h")
age(N7, 60 * 24 + 1)
check(wait_for(lambda: len(nags("Deadline nag")) == 2), "daily: after 24 h")
# German texts
Bo.patch(B + "/api/settings", json={"lang": "de"})
age(N7, 60 * 24 + 1)
check(wait_for(lambda: len(nags("Deadline nag")) == 3), "German nag")
de = nags("Deadline nag")[-1]
check("fällig" in de["msg"] and "Nachhaken aus" in (de.get("actions") or "") and "Erledigt" in (de.get("actions") or ""), f"German: {de['msg']!r} {de.get('actions')!r}")
Bo.patch(B + "/api/settings", json={"lang": "en"})
for tid in (N2, N6, N7):
    Bo.patch(B + f"/api/tasks/{tid}", json={"nag": "off"})
Bo.patch(B + f"/api/lists/{L}", json={"nag": ""})

# ================================================================== token API + OpenAPI
tok = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()["token"]
V = requests.Session()
V.headers.update({"Authorization": "Bearer " + tok})
vt = V.get(B + f"/api/v1/tasks/{T1}").json()
check(vt.get("deadline") is True and vt.get("deadline_in_today") is False and vt.get("nag") == "1d", f"v1 task: deadline / nag: {vt.get('deadline')} {vt.get('deadline_in_today')} {vt.get('nag')!r}")
r = V.patch(B + f"/api/v1/tasks/{T1}", json={"deadline_in_today": True, "nag": "30"})
check(r.ok and r.json().get("deadline") is True and r.json().get("deadline_in_today") is True and r.json().get("nag") == "30", f"v1 patch deadline_in_today + nag: {r.status_code} {r.text[:200]}")
r = V.patch(B + f"/api/v1/tasks/{T1}", json={"deadline": False})
check(r.ok and r.json().get("deadline") is False and r.json().get("deadline_in_today") is False, "v1 deadline false")
check(V.patch(B + f"/api/v1/tasks/{T1}", json={"nag": "2h"}).status_code == 400, "v1 nag invalid 400")
check(V.patch(B + f"/api/v1/tasks/{T1}", json={"deadline": "yes"}).status_code == 400, "v1 deadline not boolean 400")
r = V.patch(B + f"/api/v1/lists/{L}", json={"nag": "60", "day_hours": 7.5})
check(r.ok and r.json().get("nag") == "60" and r.json().get("day_hours") == 7.5, f"v1 PATCH list nag + day_hours: {r.status_code} {r.text[:200]}")
check(V.patch(B + f"/api/v1/lists/{L}", json={"bogus": 1}).status_code == 400, "v1 PATCH list: unknown field 400")
r = V.post(B + "/api/v1/lists", json={"name": "Via API", "nag": "15"})
check(r.status_code == 201 and r.json().get("nag") == "15", f"v1 create list with nag: {r.status_code}")
spec = requests.get(B + "/api/v1/openapi.json").json()
sch = spec["components"]["schemas"]
check({"deadline", "deadline_in_today", "nag"} <= set(sch["Task"]["properties"]) and {"deadline", "deadline_in_today", "nag"} <= set(sch["TaskInput"]["properties"]), "OpenAPI: task fields")
check("patch" in spec["paths"]["/lists/{id}"] and {"nag", "day_hours"} <= set(sch["ListPatch"]["properties"]) and {"nag", "day_hours"} <= set(sch["List"]["properties"]), "OpenAPI: PATCH /lists/{id}, list fields")
me = V.get(B + "/api/v1/me").json()
check("nag" in json.dumps(me.get("notifications", {})), "v1 /me: the notification row nag")

# ================================================================== #407 hours per day, time sums
st = Bo.get(B + "/api/state").json()
check(st.get("time_day_h") == 8.0, f"time_day_h default 8: {st.get('time_day_h')}")
check(Bo.patch(B + "/api/admin/settings", json={"time_day_h": 6}).status_code == 403, "time_day_h: admins only")
check(A.patch(B + "/api/admin/settings", json={"time_day_h": 30}).status_code == 400, "time_day_h 30: 400")
r = A.patch(B + "/api/admin/settings", json={"time_day_h": "7,5"})
check(r.ok and r.json().get("time_day_h") == 7.5, f"time_day_h 7,5: {r.status_code} {r.text[:120]}")
check(Bo.get(B + "/api/state").json()["time_day_h"] == 7.5, "every user sees it")
P = Bo.post(B + "/api/lists", json={"name": "Client X", "ptype": "agency"}).json()["id"]
check(Bo.patch(B + f"/api/lists/{P}", json={"day_hours": 10}).ok and next(x for x in Bo.get(B + "/api/state").json()["lists"] if x["id"] == P)["day_hours"] == 10, "list day_hours 10")
check(Bo.patch(B + f"/api/lists/{P}", json={"day_hours": 0}).status_code == 400 and Bo.patch(B + f"/api/lists/{P}", json={"day_hours": "x"}).status_code == 400, "day_hours invalid 400")
check(Bo.patch(B + f"/api/lists/{P}", json={"day_hours": ""}).ok and next(x for x in Bo.get(B + "/api/state").json()["lists"] if x["id"] == P)["day_hours"] is None, "day_hours '' -> the server's value")
Bo.patch(B + f"/api/lists/{P}", json={"day_hours": 10})
fields = [f for f in Bo.get(B + "/api/state").json()["fields"] if f["list_id"] == P]
fb = next((f for f in fields if f["name"] == "Budget h"), None)
check(fb and fb["type"] == "number", f"agency project: number field Budget h: {[f['name'] for f in fields]}")
PT1 = Bo.post(B + "/api/tasks", json={"title": "Concept", "list_id": P, "fields": {str(fb["id"]): "12"}}).json()["id"]
PT2 = Bo.post(B + "/api/tasks", json={"title": "Shoot", "list_id": P, "fields": {str(fb["id"]): "8,5"}}).json()["id"]
s0 = (now - timedelta(hours=5)).astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
check(Bo.post(B + "/api/time/entries", json={"task_id": PT1, "start": s0, "minutes": 150}).ok, "entry 2.5 h on a task")
check(Bo.post(B + "/api/time/entries", json={"list_id": P, "start": s0, "minutes": 30}).ok, "entry 0.5 h on the list itself")
tl = Bo.get(B + "/api/state").json().get("time_lists", {}).get(str(P))
check(tl and tl["s"] == 3 * 3600 and tl["b"] == 20.5, f"time_lists: 3 h + budget 20.5: {tl}")
check(Bo.get(B + "/api/state").json().get("time_lists", {}).get(str(L)) is None, "a plain list: no time sum")
# a member sees the same sum (shared, the same hours per day)
Bo.put(B + f"/api/lists/{P}/members", json={"user_id": 1, "role": "edit"})
ta = A.get(B + "/api/state").json()
check(ta["time_lists"].get(str(P), {}).get("s") == 3 * 3600 and next(x for x in ta["lists"] if x["id"] == P)["day_hours"] == 10, "member: same sum, same day length")
# time switched off for the server: no sums
A.patch(B + "/api/admin/settings", json={"time_all": False})
check(Bo.get(B + "/api/state").json().get("time_lists") == {}, "time off: no time_lists")
A.patch(B + "/api/admin/settings", json={"time_all": True})

# ================================================================== #405 S4: Completed view keeps "Delete completed…"
check(Bo.post(B + "/api/tasks/purge-done").ok, "purge-done still answers (Completed view)")

print(f"p270_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
