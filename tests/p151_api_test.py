#!/usr/bin/env python3
"""1.5.1 API tests (fresh DB on the TEST container :3048): "Show completed" per view (user setting show_done_views: a
json map route key -> 0/1, validated, per user, not shared); archived lists hide their tasks outside the list (no
calendar ghosts, no ICS events, no reminders, not in the daily digest, not in the overdue trend of the statistics;
unarchiving brings them back); the statistics weeks start on the viewer's first weekday (?ws=, JavaScript numbering)."""
import json, os, sys, time
from datetime import date, timedelta
import requests

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1]
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what)


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok
    return s


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def clear_pushes():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


def wait_for(fn, timeout=6):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return True
        time.sleep(0.2)
    return False


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
Bb = sess("bob")
A.patch(B + "/api/settings", json={"features": "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields",
                                   "push_channel": "ntfy"})
st = lambda s=A: s.get(B + "/api/state").json()  # noqa: E731

# ---- show_done_views
s = st()["settings"]
check(s.get("show_done_views") == "{}" and "show_completed" not in s, f"defaults: empty map, no global switch (1.8.1): {s.get('show_done_views')}")
r = A.patch(B + "/api/settings", json={"show_completed": "0"})
check(r.ok and "show_completed" not in st()["settings"], "1.8.1: the old global key is ignored, not stored")
r = A.patch(B + "/api/settings", json={"show_done_views": json.dumps({"cal": 0})})
check(r.ok and json.loads(st()["settings"]["show_done_views"]) == {"cal": 0}, "the calendar's own entry is accepted")
r = A.patch(B + "/api/settings", json={"show_done_views": json.dumps({"today": 0, "l:5": 1, "tag:ärger": "1"})})
check(r.ok, f"valid map saved: {r.status_code} {r.text}")
check(json.loads(st()["settings"]["show_done_views"]) == {"today": 0, "l:5": 1, "tag:ärger": 1}, "stored as 0/1 per view key")
r = A.patch(B + "/api/settings", json={"show_done_views": {"f:3": True, "week": 0}})  # a json object works too
check(r.ok and json.loads(st()["settings"]["show_done_views"]) == {"f:3": 1, "week": 0}, "object body accepted (true -> 1)")
before = st()["settings"]["show_done_views"]
for bad in ([1, 2], json.dumps({"today": 2}), json.dumps({"today": "yes"}), json.dumps({"x" * 121: 1}), json.dumps({"": 1}),
            "not json", json.dumps({f"l:{i}": 1 for i in range(501)}), json.dumps(["today"])):
    r = A.patch(B + "/api/settings", json={"show_done_views": bad})
    check(r.status_code == 400, f"invalid refused ({str(bad)[:40]}): {r.status_code}")
check(st()["settings"]["show_done_views"] == before, "an invalid value changes nothing")
check(st(Bb)["settings"]["show_done_views"] == "{}", "per user: bob's map is his own")
r = A.patch(B + "/api/settings", json={"show_done_views": ""})
check(r.ok and st()["settings"]["show_done_views"] == "{}", "empty -> {}")

# ---- archived lists
today = date.today()
T0 = today.isoformat()
L = A.post(B + "/api/lists", json={"name": "Old project"}).json()["id"]
K = A.post(B + "/api/lists", json={"name": "Keep"}).json()["id"]
REP = A.post(B + "/api/tasks", json={"title": "Water plants", "list_id": L, "due": T0, "repeat": "FREQ=DAILY"}).json()["id"]
REP2 = A.post(B + "/api/tasks", json={"title": "Stretch", "list_id": K, "due": T0, "repeat": "FREQ=DAILY"}).json()["id"]
OVER = A.post(B + "/api/tasks", json={"title": "Late one", "list_id": L, "due": (today - timedelta(days=3)).isoformat()}).json()["id"]
rng = {"from": T0, "to": (today + timedelta(days=6)).isoformat()}
occ = lambda: {o["id"] for o in A.get(B + "/api/occurrences", params=rng).json()["items"]}  # noqa: E731
check(occ() == {REP, REP2}, f"ghosts of both recurring tasks: {occ()}")
ical = A.post(B + "/api/ical", json={"action": "create"}).json()["url"]
ics_path = "/ical/" + ical.rsplit("/ical/", 1)[1]
ics = lambda: sess().get(B + ics_path).text  # noqa: E731
check("Water plants" in ics() and "Late one" in ics(), "ICS: tasks of the list while it is active")
stats_over = lambda: A.get(B + "/api/stats").json()["overdue"][-1]["n"]  # noqa: E731
n_over = stats_over()
check(n_over >= 1, f"overdue trend counts the late task: {n_over}")

check(A.patch(B + f"/api/lists/{L}", json={"archived": 1}).ok, "archive the list")
check(occ() == {REP2}, f"archived: no ghosts for its recurring task: {occ()}")
check("Water plants" not in ics() and "Late one" not in ics() and "Stretch" in ics(), "archived: its tasks leave the ICS feed")
check(stats_over() == n_over - 1, f"archived: overdue trend without its task: {stats_over()} vs {n_over}")
s = st()
check(any(t["id"] == REP for t in s["tasks"]), "the tasks still come with the state (the archived list shows them)")

# reminders + digest: nothing for tasks of an archived list
time.sleep(3.5)
clear_pushes()
now = time.strftime("%H:%M")
A.post(B + "/api/tasks", json={"title": "ARCH-REM", "list_id": L, "due": T0, "due_time": now, "reminders": "0"})
A.post(B + "/api/tasks", json={"title": "KEEP-REM", "list_id": K, "due": T0, "due_time": now, "reminders": "0"})
wait_for(lambda: any("KEEP-REM" in (p.get("title", "") + p.get("msg", "")) for p in pushes()))
time.sleep(1.5)
txt = [p.get("title", "") + " " + p.get("msg", "") for p in pushes()]
check(any("KEEP-REM" in x for x in txt), f"reminder of an active list arrives: {txt}")
check(not any("ARCH-REM" in x for x in txt), f"no reminder for a task of an archived list: {txt}")
time.sleep(3.5)
clear_pushes()
A.patch(B + "/api/settings", json={"digest_time": "00:00"})
wait_for(lambda: any(p.get("title") == "Today" for p in pushes()), timeout=8)
dg = [p for p in pushes() if p.get("title") == "Today"]
check(len(dg) == 1 and "Stretch" in dg[0]["msg"], f"digest sent with the active list's task: {dg}")
check(dg and "Water plants" not in dg[0]["msg"] and "Late one" not in dg[0]["msg"] and "ARCH-REM" not in dg[0]["msg"], f"digest leaves out the archived list: {dg}")

check(A.patch(B + f"/api/lists/{L}", json={"archived": 0}).ok, "unarchive")
check(occ() == {REP, REP2}, "unarchived: ghosts back")
check("Water plants" in ics(), "unarchived: ICS back")
check(stats_over() == n_over, "unarchived: overdue trend back")

# ---- statistics: week start
for ws, wd in ((None, 0), ("1", 0), ("0", 6), ("6", 5), ("9", 0), ("x", 0)):
    j = A.get(B + "/api/stats", params={"ws": ws} if ws is not None else {}).json()
    w0 = date.fromisoformat(j["weeks"][0])
    last = date.fromisoformat(j["weeks"][-1])
    check(w0.weekday() == wd and len(j["weeks"]) == 12 and last <= today < last + timedelta(days=7) and len(j["done"]["per_week"]) == 12,
          f"ws={ws}: weeks start on weekday {wd} and the last one holds today: {j['weeks'][0]}..{j['weeks'][-1]}")
A.post(B + f"/api/tasks/{REP2}/complete", json={})
j0, j1 = A.get(B + "/api/stats", params={"ws": "0"}).json(), A.get(B + "/api/stats", params={"ws": "1"}).json()
check(j0["done"]["this_week"] == 1 and j1["done"]["this_week"] == 1, "a completion today is in this week for both week starts")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
