#!/usr/bin/env python3
"""2.280.0 A (#3109) API test: a change of someone else no longer makes every client load the whole state. Own container
(start.sh). Invented people and texts only.
freelancer-matrix: tasks, time, wiki, settings
 - /api/version areas: a time entry (app and agent API), a knowledge page, an own setting / habit count in their own area
   ("time", "wiki", "self" per account) and no longer in "other" (= the full state for every client); a setting others
   see (the folder order) stays "other"; the window that wrote gets its own counter in X-Kalmido-Lv
 - GET /api/state/delta: the "full" changes of one list (a section, the order of the sidebar, a member's own folder /
   order) answer full only for whoever sees that list or that person; a change of who sees a list stays full for all;
   the same reorder twice writes no change rows; ?side=1 brings team chat / News / calendars as /api/state has them
 - the brake: GET /api/state?auto=1 twice within seconds of the same account answers {brake: true}; without auto never;
   2.280.0 F (#3109): per sign-in (another device of the same person is not held back)
 - the same for a person without an organisation (frida)
 - PERF lines (information): the statements of the delta vs the whole state after a foreign time entry
usage: p2280_a_api_test.py <datadir>   (KMT_NOSTART=1: the container runs already)"""
import json
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer, login  # noqa: E402
from kt import FAILS, OKS, B, CT, check, dbx, done, fresh, setup, until  # noqa: E402,F401

FEATURES = "cal,collab,comments,events,fields,progress,time,wiki,habits"
TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


fresh()
A = setup()
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha"}).json()["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Bo2, Da = login(B, "bob"), login(B, "bob"), login(B, "dave")
for s in (A, Bo, Da):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok
FID, Fr = freelancer(B, A)  # freelancer-matrix: tasks, time, wiki, settings


def areas(s):
    return s.get(B + "/api/version").json()


def delta(s, since, **kw):
    r = s.get(B + "/api/state/delta", params={"since": since, "lean": "1", **kw})
    return r.json(), nstmt(r)


def task(s, title, lid):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid})
    assert r.ok, r.text
    return r.json()["id"]


def vis(s):
    return {x["id"] for x in s.get(B + "/api/state").json()["lists"]}


LB = Bo.post(B + "/api/lists", json={"name": "Bob's own plan"}).json()["id"]
LB2 = Bo.post(B + "/api/lists", json={"name": "Bob's second plan"}).json()["id"]
LA = A.post(B + "/api/lists", json={"name": "Shared plan", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{LA}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob member of alice's list")
check(Bo.patch(B + f"/api/lists/{LB}", json={"time_tracking": 1}).ok, "setup: time tracking on in bob's list")
TB = task(Bo, "Bob's task", LB)
FL = Fr.post(B + "/api/lists", json={"name": "Frida's work"}).json()["id"]
FT = task(Fr, "Frida's task", FL)
check(LB not in vis(Da) and LB not in vis(Fr), "setup: dave and frida do not see bob's list")

# ================================================================ areas of /api/version
v0, a0 = areas(Da)["v"], areas(Da)["a"]
r = Bo.post(B + "/api/time/entries", json={"task_id": TB, "start": "2026-01-05T09:00", "minutes": 30})
check(r.ok, f"bob books time {r.text[:200]}")
j = areas(Da)
check(j["v"] > v0 and j["a"].get("time", 0) > a0.get("time", 0) and j["a"]["other"] == a0["other"],
      f"#3109 a time entry moves 'time', not 'other' (was the full state for every client) {a0} -> {j['a']}")
d, n_delta = delta(Da, v0)
check(d.get("full") is False and d.get("lean") is True and d.get("tasks") == [], f"#3109 dave: a lean delta after bob's time entry {d}")
df, _ = delta(Fr, v0)
check(df.get("full") is False and df.get("tasks") == [], f"#3109 frida (no organisation): no full state either {df}")
rs = Da.get(B + "/api/state")
print(f"PERF #3109 after a foreign time entry: delta {n_delta} statements / {len(d and str(d))} B, "
      f"the whole state {nstmt(rs)} statements / {len(rs.content)} B", flush=True)
check(0 < n_delta < nstmt(rs), f"#3109 the delta costs fewer statements than the state ({n_delta} < {nstmt(rs)})")
# 2.280.0 F (#3109): a time entry without a task (on the list) moves the list's time sum of its owner: the owner's delta
# is no longer lean without it (was: nothing noted -> lean -> the sum in the header stayed old); others keep a lean delta
check(A.patch(B + f"/api/lists/{LA}", json={"time_tracking": 1}).ok, "setup: time tracking on in alice's list")
vA, vF = areas(A)["v"], areas(Fr)["v"]
r = Bo.post(B + "/api/time/entries", json={"list_id": LA, "start": "2026-01-05T11:00", "minutes": 45})
check(r.ok, f"bob books time on alice's list (no task) {r.text[:200]}")
d, _ = delta(A, vA)
check(d.get("full") is True or (d.get("time_lists") or {}).get(str(LA), {}).get("s", 0) >= 2700,
      f"#3109 F alice (owner): the list's time sum follows (full or time_lists) {str(d)[:200]}")
check(A.get(B + "/api/state").json()["time_lists"].get(str(LA), {}).get("s", 0) >= 2700, "the whole state has the sum")
df, _ = delta(Fr, vF)
check(df.get("full") is False and df.get("lean") is True, f"#3109 F frida (no organisation, does not see the list): still lean {str(df)[:200]}")
# the agent API: a time entry by token is "time" too
tok = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"], "expires_days": 30}).json()["token"]
a1 = areas(Da)["a"]
r = requests.post(B + "/api/v1/time/entries", headers={"Authorization": "Bearer " + tok},
                  json={"task_id": TB, "start": "2026-01-06T09:00", "minutes": 15})
check(r.status_code == 201, f"agent API: a time entry {r.status_code} {r.text[:200]}")
a2 = areas(Da)["a"]
check(a2["time"] > a1["time"] and a2["other"] == a1["other"], f"#3109 agent API time entry: 'time', not 'other' {a1} -> {a2}")

# a knowledge page
a1 = areas(Da)["a"]
r = Bo.post(B + "/api/wiki/pages", json={"space": "private", "path": "Invented note", "body": "Invented text"})
check(r.ok, f"bob writes a knowledge page {r.status_code} {r.text[:200]}")
a2 = areas(Da)["a"]
check(a2.get("wiki", 0) > a1.get("wiki", 0) and a2["other"] == a1["other"], f"#3109 a knowledge page: 'wiki', not 'other' {a1} -> {a2}")
a1 = areas(Fr)["a"]
check(Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Frida's note", "body": "x"}).ok, "frida writes a page")
check(areas(Fr)["a"]["other"] == a1["other"], "#3109 frida's page: not 'other' (freelancer-matrix: wiki)")

# an own setting: counted for the account (others see nothing move, the writing window gets its counter)
d0, b0, f0 = areas(Da), areas(Bo2), areas(Fr)
r = Bo.patch(B + "/api/settings", json={"allday_time": "08:00"})
check(r.ok and re.fullmatch(r"self:\d+", r.headers.get("X-Kalmido-Lv", "")), f"#3109 the own setting answers X-Kalmido-Lv {r.headers.get('X-Kalmido-Lv')}")
own = int(r.headers.get("X-Kalmido-Lv", "self:0")[5:])
d1, b1, f1 = areas(Da), areas(Bo2), areas(Fr)
check(d1["v"] > d0["v"] and d1["a"] == d0["a"], f"#3109 dave: v moves, no area (was 'other') {d0['a']} -> {d1['a']}")
check(f1["a"] == f0["a"], f"#3109 frida: no area moves on bob's setting (freelancer-matrix: settings) {f0['a']} -> {f1['a']}")
check(b1["a"]["self"] == own and b1["a"]["self"] > b0["a"]["self"] and b1["a"]["other"] == b0["a"]["other"],
      f"#3109 bob's other device: his 'self' moved to the counter of the answer {b0['a']} -> {b1['a']} ({own})")
d, _ = delta(Da, d0["v"])
check(d.get("full") is False and d.get("lean") is True, f"#3109 dave: a lean delta after bob's setting {d}")
a1 = areas(Da)["a"]
check(Bo.patch(B + "/api/settings", json={"folders": '["Invented folder"]'}).ok, "bob orders his folders")
check(areas(Da)["a"]["other"] > a1["other"], "#3109 the folder order (others see it at mirrored lists) stays 'other'")
f0 = areas(Fr)
r = Fr.patch(B + "/api/settings", json={"allday_time": "10:00"})
check(r.ok and areas(Fr)["a"]["self"] > f0["a"]["self"] and areas(Fr)["a"]["other"] == f0["a"]["other"],
      "#3109 frida's own setting: her 'self' (freelancer-matrix: settings)")
# 2.280.0 F (#3109): a setting the server evaluates for the state (the lists' progress, notifications, day plan, language):
# no own counter for the writing window (it reloads like another device of the person); still "self", not "other"
for k, v in (("progress_subtasks", "1"), ("review_time", "18:30"), ("lang", "en")):
    b0, d0 = areas(Bo2)["a"], areas(Da)["a"]
    r = Bo.patch(B + "/api/settings", json={k: v})
    b1 = areas(Bo2)["a"]
    check(r.ok and "X-Kalmido-Lv" not in r.headers and b1["self"] > b0["self"] and b1["other"] == b0["other"] and areas(Da)["a"] == d0,
          f"#3109 F {k}: no X-Kalmido-Lv (the writing window reloads), 'self' moved {r.headers.get('X-Kalmido-Lv')} {b0} -> {b1}")
r = Fr.patch(B + "/api/settings", json={"progress_subtasks": "1"})
check(r.ok and "X-Kalmido-Lv" not in r.headers, "#3109 F frida's progress setting: no own counter either (freelancer-matrix: settings)")
# 2.280.0 F (#3109): an admin's standard layout for everyone is "other" (everyone's clients), not the admin's "self"
a0 = areas(Da)["a"]
r = A.put(B + "/api/layouts/std/dashboard", json={"layout": json.dumps({"order": ["news", "today"]})})
a1 = areas(Da)["a"]
check(r.ok and "X-Kalmido-Lv" not in r.headers and a1["other"] > a0["other"], f"#3109 F the standard layout for everyone: 'other' {r.status_code} {a0} -> {a1}")
h0 = areas(Da)["a"]
check(Bo.post(B + "/api/habits", json={"name": "Invented habit"}).ok, "bob adds a habit")
check(areas(Da)["a"] == h0, "#3109 a habit: no area of dave moves")

# ================================================================ "full" per list
v1 = areas(Da)["v"]
check(Bo.post(B + "/api/sections", json={"list_id": LB, "name": "Week 1"}).ok, "bob adds a section to his own list")
d, _ = delta(Da, v1)
check(d.get("full") is False, f"#3109 a section of a list dave does not see: no full state for dave (was full for all) {d}")
check(delta(Fr, v1)[0].get("full") is False, "#3109 ... nor for frida (freelancer-matrix: tasks)")
check(delta(Bo2, v1)[0].get("full") is True, "#3109 bob's other device: full (he sees the list)")
v2 = areas(Da)["v"]
check(A.post(B + "/api/sections", json={"list_id": LA, "name": "Shared week"}).ok, "alice adds a section to the shared list")
check(delta(Bo2, v2)[0].get("full") is True, "#3109 a section of the shared list: full for its member bob")
check(delta(Da, v2)[0].get("full") is (LA in vis(Da)), "#3109 ... and for dave exactly when he sees the list")
check(delta(Fr, v2)[0].get("full") is False, "#3109 ... never for frida")

# the sidebar order: only the rows that move, only for whoever sees the order
v3 = areas(Da)["v"]
ids = [LB2, LB, LA]
check(Bo.post(B + "/api/lists/reorder", json={"ids": ids}).ok, "bob reorders his sidebar")
check(delta(Da, v3)[0].get("full") is False, "#3109 bob's order: no full state for dave (was: one UPDATE per list = full for all)")
check(delta(A, v3)[0].get("full") is False, "#3109 bob's own order of alice's list (his member row): no full state for alice")
check(delta(Fr, v3)[0].get("full") is False, "#3109 ... nor for frida")
check(delta(Bo2, v3)[0].get("full") is True, "#3109 bob's other device: full (his order)")
v4 = areas(Da)["v"]
n0 = dbx("SELECT COUNT(*) FROM dl_changes WHERE ver > ? OR ver IS NULL", (v4,))[0][0]
check(Bo.post(B + "/api/lists/reorder", json={"ids": ids}).ok, "the same order again")
n1 = dbx("SELECT COUNT(*) FROM dl_changes WHERE ver > ? OR ver IS NULL", (v4,))[0][0]
check(n1 == n0, f"#3109 the same order writes no change rows ({n0} -> {n1})")
check(delta(Bo2, v4)[0].get("full") is False, "#3109 ... and is no full state even for bob's other device")
order = [x["id"] for x in sorted((x for x in Bo2.get(B + "/api/state").json()["lists"] if x["id"] in ids),
                                 key=lambda x: (x["sort"] or 0, x["id"]))]
check(order == ids, f"#3109 the order is stored as before {order}")

# who sees a list changed: full as before
v5 = areas(Da)["v"]
check(A.delete(B + f"/api/lists/{LA}/members/{uid['bob']}").ok, "alice takes bob off her list")
check(delta(Bo2, v5)[0].get("full") is True, "#3109 bob taken off a list: full for bob")
check(delta(Fr, v5)[0].get("full") is False, "#3109 ... not for frida")
v6 = areas(Da)["v"]
check(Bo.patch(B + f"/api/lists/{LB}", json={"name": "Bob's plan (renamed)"}).ok, "bob renames his list")
check(delta(Da, v6)[0].get("full") is False and delta(Bo2, v6)[0].get("full") is True,
      "#3109 a renamed list: full only for whoever sees it")

# ?side=1: the sidebar's parts as /api/state has them
v7 = areas(Da)["v"]
d, _ = delta(Da, v7, side="1")
st = Da.get(B + "/api/state").json()
check(all(k in d for k in ("team", "news", "evcals", "evsig")), f"#3109 side=1 brings the sidebar's parts {sorted(d)}")
check(d.get("team") == st["team"] and d.get("news") == st["news"] and d.get("evcals") == st["evcals"] and d.get("evsig") == st["evsig"],
      "#3109 side=1: the same values as /api/state")
d, _ = delta(Fr, areas(Fr)["v"], side="1")
check(d.get("full") is False and d.get("news") == Fr.get(B + "/api/state").json()["news"], "#3109 side=1 for frida (freelancer-matrix: tasks)")
d, _ = delta(Da, v7)
check("team" not in d, "#3109 without side=1 the answer stays as before")

# ================================================================ the brake
r1 = Da.get(B + "/api/state", params={"auto": "1"})
r2 = Da.get(B + "/api/state", params={"auto": "1"})
check(r1.ok and "tasks" in r1.json(), "#3109 the first automatic reload: the whole state")
check(r2.ok and r2.json().get("brake") is True and "tasks" not in r2.json(), f"#3109 the second within seconds: braked {str(r2.json())[:120]}")
check("tasks" in Da.get(B + "/api/state").json(), "#3109 a reload after an own action (no auto) is never braked")
check("tasks" in Fr.get(B + "/api/state", params={"auto": "1"}).json(), "#3109 the brake is per account (freelancer-matrix: tasks)")
Da2 = login(B, "dave")  # 2.280.0 F (#3109): the same person on another device (own sign-in)
check("tasks" in Da2.get(B + "/api/state", params={"auto": "1"}).json(), "#3109 F the brake is per sign-in: another device of the same person loads")
check(Da2.get(B + "/api/state", params={"auto": "1"}).json().get("brake") is True, "#3109 F ... and is braked itself on a repeat")

sys.exit(done("p2280_a_api"))
