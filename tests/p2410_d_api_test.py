#!/usr/bin/env python3
"""2.41.0 API tests (agent D).
 - #1365 "Show in My tasks" per person and list: PUT /api/lists/{id}/in-mine {on}, /api/state mine_hidden, per person (a
   member of a shared list notices nothing), 404 for a list one cannot see, 400 for a non-boolean, agents never
 - #1471 time tracking is a switch of each list (lists.time_tracking, default off for every type): new time needs it (409 with
   a clear message), web + REST API read / write it (owner only), a folder default, tracked time stays in the reports when it
   is switched off, the project page's "Tracked" only with it on; migration: lists with time entries get it on once
 - #1205 "Waiting on" suggestions: GET /api/me/wait-suggestions (own history only, newest first, also from completed
   tasks, never another person's text of a shared list), DELETE hides one (the task keeps it), using it again brings it back
usage: p2410_d_api_test.py <datadir>"""
import os
import subprocess
import sys
from datetime import date, timedelta

import requests

import dbx as dbxm  # 2.37.0: the suite has its own dbx() helper

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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["comments", "time"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "collab,time,comments"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
check(r.ok, "a second person " + r.text[:200])
BOB = r.json().get("id")
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123", "email": "carol@example.com"})
CAROL = r.json().get("id")
Bo, Ca = sess("bob"), sess("carol")
for s_ in (Bo, Ca):
    s_.patch(B + "/api/settings", json={"lang": "en", "features": "collab,time,comments"})
st = lambda s: s.get(B + "/api/state").json()  # noqa: E731
lst = lambda s, i: next((x for x in st(s)["lists"] if x["id"] == i), None)  # noqa: E731
D = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731

TEAM = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]
A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": BOB, "role": "edit"})
PRIV = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"title": "Team task", "list_id": TEAM, "assignee_id": BOB}).json()["id"]

# ================= #1365 Show in My tasks
check(st(A).get("mine_hidden") == [] and st(Bo).get("mine_hidden") == [], "#1365: nothing hidden by default")
r = Bo.put(B + f"/api/lists/{TEAM}/in-mine", json={"on": False})
check(r.ok and r.json().get("mine_hidden") == [TEAM] and r.json().get("on") is False, "#1365: a member hides a shared list for himself " + r.text[:200])
check(st(Bo)["mine_hidden"] == [TEAM] and st(A)["mine_hidden"] == [], "#1365: per person (the owner notices nothing)")
check(Bo.put(B + f"/api/lists/{TEAM}/in-mine", json={"on": False}).ok and st(Bo)["mine_hidden"] == [TEAM], "#1365: twice = once")
check(Bo.put(B + f"/api/lists/{PRIV}/in-mine", json={"on": False}).status_code == 404, "#1365: a list one cannot see: 404")
check(Bo.put(B + f"/api/lists/{TEAM}/in-mine", json={"on": "no"}).status_code == 400, "#1365: on must be a boolean")
check(Bo.get(B + f"/api/tasks/{T1}").json().get("assignee_id") == BOB, "#1365: the task itself stays as it is")
check(Bo.put(B + f"/api/lists/{TEAM}/in-mine", json={"on": True}).json().get("mine_hidden") == [], "#1365: shown again")
Bo.put(B + f"/api/lists/{TEAM}/in-mine", json={"on": False})
A.delete(B + f"/api/lists/{TEAM}/members/{BOB}")
check(st(Bo)["mine_hidden"] == [], "#1365: a list one left is not listed any more")
A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": BOB, "role": "edit"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "structure"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag.get("token", "x")}
check(requests.put(B + f"/api/lists/{TEAM}/in-mine", headers={**AGH, **H}, json={"on": False}).status_code in (401, 403, 404),
      "#1365: agents have no My tasks switch")

# ================= #1471 time tracking per list
P = A.post(B + "/api/lists", json={"name": "Client X", "kind": "project"}).json()["id"]
PT = A.post(B + "/api/tasks", json={"title": "Concept", "list_id": P}).json()["id"]
check(lst(A, P)["time_tracking"] == 0 and lst(A, PRIV)["time_tracking"] == 0, "#1471: off by default, also for projects")
r = A.post(B + "/api/time/start", json={"task_id": PT})
check(r.status_code == 409 and "time tracking" in r.json().get("error", ""), "#1471: no timer with the switch off: " + r.text[:160])
check(A.post(B + "/api/time/entries", json={"list_id": P, "start": D(-1) + "T09:00", "minutes": 30}).status_code == 409, "#1471: no entry on the list either")
check(Bo.patch(B + f"/api/lists/{TEAM}", json={"time_tracking": True}).status_code == 403, "#1471: only the owner switches it")
r = A.patch(B + f"/api/lists/{P}", json={"time_tracking": True})
check(r.ok and lst(A, P)["time_tracking"] == 1, "#1471: switched on " + r.text[:160])
check(A.post(B + "/api/time/entries", json={"task_id": PT, "start": D(-1) + "T09:00", "minutes": 90}).ok, "#1471: time on a task now")
PL = A.post(B + "/api/lists", json={"name": "Errands", "time_tracking": True}).json()["id"]  # a plain list with time tracking
PLT = A.post(B + "/api/tasks", json={"title": "Bank", "list_id": PL}).json()["id"]
check(lst(A, PL)["kind"] == "list" and A.post(B + "/api/time/entries", json={"task_id": PLT, "start": D(-1) + "T11:00", "minutes": 30}).ok,
      "#1471: any list type can track time (created with the switch on)")
rep = lambda: A.get(B + "/api/time/report", params={"from": D(-3), "to": D(0)}).json()["total"]["seconds"]  # noqa: E731
s1 = rep()
check(s1 == 120 * 60, f"#1471: the report counts both lists ({s1})")
check((A.get(B + f"/api/lists/{P}/overview").json().get("time") or {}).get("seconds") == 5400, "#1471: project page: Tracked with the switch on")
A.patch(B + f"/api/lists/{P}", json={"time_tracking": False})
check(rep() == s1, "#1471: switched off: the tracked time stays in the report")
check(A.get(B + f"/api/lists/{P}/overview").json().get("time") is None, "#1471: project page: no Tracked with the switch off")
check(any(e["task_id"] == PT for e in A.get(B + "/api/time/entries", params={"from": D(-3), "to": D(0)}).json()["entries"]), "#1471: the entries stay listed")
check(A.post(B + "/api/time/start", json={"task_id": PT}).status_code == 409, "#1471: switched off: no new timer")
# REST API
tok = A.post(B + "/api/me/tokens", json={"name": "k", "scopes": ["read", "write"]}).json()["token"]
VH = {"Authorization": "Bearer " + tok}
lv = requests.get(V + f"/lists/{P}", headers=VH).json()
check(lv.get("time_tracking") is False, "#1471: API v1 list carries time_tracking " + str(lv.get("time_tracking")))
r = requests.patch(V + f"/lists/{P}", headers=VH, json={"time_tracking": True})
check(r.ok and r.json().get("time_tracking") is True, "#1471: API v1 PATCH time_tracking " + r.text[:160])
check(requests.patch(V + f"/lists/{P}", headers=VH, json={"time_tracking": 1}).status_code == 400, "#1471: API v1 wants a boolean")
r = requests.post(V + "/lists", headers=VH, json={"name": "API timed", "time_tracking": True})
check(r.status_code == 201 and r.json().get("time_tracking") is True, "#1471: API v1 create with time_tracking " + r.text[:160])
spec = requests.get(V + "/openapi.json").json()
check("time_tracking" in str(spec), "#1471: OpenAPI documents time_tracking")
# folder default
r = A.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"time_tracking": True}})
check(r.ok, "#1471: folder default time_tracking " + r.text[:200])
FL = A.post(B + "/api/lists", json={"name": "Client Y", "folder": "Clients"}).json()["id"]
check(lst(A, FL)["time_tracking"] == 1, "#1471: a new list in the folder gets it")
FL2 = A.post(B + "/api/lists", json={"name": "Client Z", "folder": "Clients", "time_tracking": False}).json()["id"]
check(lst(A, FL2)["time_tracking"] == 0, "#1471: an explicit value beats the folder")
check(A.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"time_tracking": "yes"}}).status_code == 400, "#1471: folder default must be a switch")
# migration: a list with entries gets the switch on once (a list switched off later keeps it off on the next start)
OLD = A.post(B + "/api/lists", json={"name": "Old project", "kind": "project", "time_tracking": True}).json()["id"]
OT = A.post(B + "/api/tasks", json={"title": "Old work", "list_id": OLD}).json()["id"]
A.post(B + "/api/time/entries", json={"task_id": OT, "start": D(-2) + "T09:00", "minutes": 60})
dbx("UPDATE lists SET time_tracking=0 WHERE id IN (?, ?)", (OLD, PRIV), write=True)
dbx("DELETE FROM settings WHERE key='migr_time241'", write=True)
env = dict(os.environ, KEEP="1")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
check(lst(A, OLD)["time_tracking"] == 1 and lst(A, PRIV)["time_tracking"] == 0, "#1471: migration: a list with time entries gets it on, the rest stays off")
A.patch(B + f"/api/lists/{OLD}", json={"time_tracking": False})
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
check(lst(A, OLD)["time_tracking"] == 0, "#1471: migration runs once (switched off stays off)")

# ================= #1205 Waiting on suggestions
WT = [A.post(B + "/api/tasks", json={"title": f"W{i}", "list_id": TEAM}).json()["id"] for i in range(4)]
for tid, note in zip(WT, ("Offer from the carpenter", "Tax office", "Delivery", "offer from the carpenter")):
    check(A.put(B + f"/api/tasks/{tid}/waiting", json={"note": note}).ok, "#1205: waiting " + note)
A.patch(B + f"/api/tasks/{WT[1]}", json={"status": 2})  # completed: its text stays a suggestion
A.delete(B + f"/api/tasks/{WT[2]}/waiting")  # no longer waiting: the text stays a suggestion
Bo.put(B + f"/api/tasks/{T1}/waiting", json={"note": "Bob's supplier"})  # another person in the shared list
g = A.get(B + "/api/me/wait-suggestions").json().get("items", [])
notes = [x["note"] for x in g]
check(notes[:3] == ["offer from the carpenter", "Delivery", "Tax office"], f"#1205: newest first, once per text (any case): {notes}")
check("Bob's supplier" not in notes, "#1205: never another person's text from a shared list")
check([x["note"] for x in Bo.get(B + "/api/me/wait-suggestions").json()["items"]] == ["Bob's supplier"], "#1205: Bob sees only his own")
check(Ca.get(B + "/api/me/wait-suggestions").json()["items"] == [], "#1205: a third person: nothing")
r = A.delete(B + "/api/me/wait-suggestions", json={"note": "Tax office"})
check(r.ok and "Tax office" not in [x["note"] for x in r.json()["items"]], "#1205: x hides a suggestion")
check(A.get(B + f"/api/tasks/{WT[1]}").json().get("wait_note") == "Tax office", "#1205: the task keeps its text")
check(A.delete(B + "/api/me/wait-suggestions", json={"note": " "}).status_code == 400, "#1205: an empty text: 400")
check("Tax office" not in [x["note"] for x in A.get(B + "/api/me/wait-suggestions").json()["items"]], "#1205: hidden stays hidden")
A.put(B + f"/api/tasks/{WT[0]}/waiting", json={"note": "TAX OFFICE"})
check(A.get(B + "/api/me/wait-suggestions").json()["items"][0]["note"] == "TAX OFFICE", "#1205: used again: a suggestion again")
check(requests.get(B + "/api/me/wait-suggestions").status_code == 401, "#1205: no login: 401")

print(f"p2410_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
