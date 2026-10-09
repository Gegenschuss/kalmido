#!/usr/bin/env python3
"""2.34.0 API tests (agent B: #266 tasks lying idle, #269 time-tracking helper), own container (start.sh).
 - GET /api/stale (web) and GET /api/v1/stale (agents / tokens): open top-level tasks without a change, comment or time entry
   for the list's threshold (default 7 days), waiting tasks without a follow-up day ahead (reason waiting); not: fresh ones,
   ones with a recent comment / time entry, a follow-up day ahead, due later, milestones, repeating tasks
 - visibility: only lists the person sees; a participant only their tasks; an agent only lists shared with it; a foreign list
   id 404; bad parameters 400
 - lists.stale_days (null = default, 0 = never) and lists.agent_followup: owner / list admins only, never an agent; in the
   v1 list output; the event stale_tasks once a day per agent, only lists with "Agent follows up" on
 - GET /api/time/gaps and GET /api/v1/time/gaps: working days with work on tasks of project lists but no time entry; an agent
   for a person who may chat with it (only lists both see), else 404
 - OpenAPI documents /stale and /time/gaps; the new columns leave the 2.33 tables untouched (new columns only)
usage: p2340_b_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys
import time
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


def dbx(sql, args=(), write=False):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


# the day's event may go out at any hour in the test (default: from 09:00 server time)
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_STALE_HOUR=00:00"))
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL, DAVE = uid["bob"], uid["carol"], uid["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "time"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}

W = A.post(B + "/api/lists", json={"name": "Work", "kind": "project"}).json()["id"]
for who, role in ((CL, "edit"), (BOB, "edit"), (DAVE, "participant")):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": role}).ok, f"setup: {who} in the list as {role}")
PRIV = A.post(B + "/api/lists", json={"name": "Private", "kind": "project"}).json()["id"]
CLIST = Ca.post(B + "/api/lists", json={"name": "Carol's"}).json()["id"]


def task(title, lid=W, **kw):
    return A.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw}).json()["id"]


T_OLD, T_NEW, T_WAIT, T_WAITF = task("Old offer"), task("Fresh task"), task("Waits on Mueller"), task("Waits with a day")
T_FUT, T_CMT, T_TIME, T_DAVE = task("Due later", due=(date.today() + timedelta(days=20)).isoformat()), task("Commented yesterday"), \
    task("Time yesterday"), task("Dave's task", assignee_id=DAVE)
T_REP, T_PRIV, T_DONE = task("Weekly report", due=date.today().isoformat(), repeat="FREQ=WEEKLY"), task("Private old", PRIV), task("Done long ago")
T_SUB = A.post(B + "/api/tasks", json={"title": "Old subtask", "list_id": W, "parent_id": T_OLD}).json()["id"]
T_CAROL = Ca.post(B + "/api/tasks", json={"title": "Carol old", "list_id": CLIST}).json()["id"]
check(A.put(B + f"/api/tasks/{T_WAIT}/waiting", json={"note": "Mr Mueller"}).ok, "setup: waiting without a follow-up day")
check(A.put(B + f"/api/tasks/{T_WAITF}/waiting", json={"note": "the office", "until": (date.today() + timedelta(days=5)).isoformat()}).ok,
      "setup: waiting with a follow-up day ahead")
A.post(B + f"/api/tasks/{T_DONE}/complete")
OLD = ago(10)
dbx(f"UPDATE tasks SET updated_at=?, created_at=? WHERE id IN ({','.join(str(x) for x in (T_OLD, T_WAIT, T_WAITF, T_FUT, T_CMT, T_TIME, T_DAVE, T_REP, T_PRIV, T_DONE, T_SUB, T_CAROL))})",
    (OLD, OLD), write=True)
dbx("UPDATE tasks SET waiting_at=? WHERE id IN (?, ?)", (OLD, T_WAIT, T_WAITF), write=True)
dbx("INSERT INTO comments(task_id, user_id, body, created_at) VALUES(?,?,?,?)", (T_CMT, BOB, "still on it", ago(1)), write=True)
dbx("INSERT INTO time_entries(user_id, task_id, list_id, start, end, seconds, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
    (ALICE, T_TIME, W, ago(1), ago(1), 600, ago(1), ago(1)), write=True)


def stale(s, q=""):
    r = s.get(B + "/api/stale" + q)
    return r.status_code, ({t["id"]: t for t in r.json().get("tasks", [])} if r.ok else r.text)


# ---------------------------------------------------------------- #266 who sees what
code, a = stale(A)
check(code == 200 and set(a) == {T_OLD, T_WAIT, T_DAVE, T_PRIV}, f"#266: alice's tasks lying idle {code} {sorted(a) if code == 200 else a}")
check(code == 200 and a.get(T_WAIT, {}).get("reason") == "waiting" and a[T_WAIT]["wait_note"] == "Mr Mueller"
      and a.get(T_OLD, {}).get("reason") == "no_change" and a[T_OLD]["idle_days"] >= 9 and a[T_OLD]["list_name"] == "Work",
      f"#266: reason, wait note, idle days, list name {a.get(T_WAIT)} {a.get(T_OLD)}")
code, b = stale(Bo)
check(code == 200 and set(b) == {T_OLD, T_WAIT, T_DAVE}, f"#266: bob (member) sees the shared list only {sorted(b) if code == 200 else b}")
code, d = stale(Da)
check(code == 200 and set(d) == {T_DAVE}, f"#266: dave (participant) only his own task {sorted(d) if code == 200 else d}")
code, c = stale(Ca)
check(code == 200 and set(c) == {T_CAROL}, f"#266: carol only her own list {sorted(c) if code == 200 else c}")
check(stale(Ca, f"?list_id={W}")[0] == 404 and stale(A, f"?list_id={W}")[0] == 200, "#266: a foreign list id is 404")
check(stale(A, "?days=0")[0] == 400 and stale(A, "?days=x")[0] == 400 and stale(A, "?list_id=x")[0] == 400, "#266: bad parameters 400")
code, a3 = stale(A, "?days=12")
check(code == 200 and not a3, f"#266: days overrides the threshold (12 > 10 idle days) {a3}")
r = requests.get(V + "/stale", headers=CLH)
ag = {t["id"] for t in r.json().get("tasks", [])} if r.ok else r.text
check(r.ok and ag == {T_OLD, T_WAIT, T_DAVE}, f"#266: the agent only sees lists shared with it {r.status_code} {ag}")
check(requests.get(V + f"/stale?list_id={PRIV}", headers=CLH).status_code == 404, "#266: agent + a list not shared with it -> 404")
check(requests.get(V + "/stale?foo=1", headers=CLH).status_code == 400, "#266: v1 unknown parameter -> 400")
check(requests.get(V + f"/stale?list_id={W}&limit=1", headers=CLH).json().get("count") == 1, "#266: limit")

# ---------------------------------------------------------------- #266 the list settings
check(A.patch(B + f"/api/lists/{W}", json={"stale_days": 30}).ok, "#266: owner sets stale_days 30")
check(T_OLD not in stale(A)[1] and T_PRIV in stale(A)[1], "#266: a list's own threshold (30 days) hides its 10-day-old tasks")
check(T_OLD in stale(A, "?days=5")[1], "#266: days still overrides the list's threshold")
check(A.patch(B + f"/api/lists/{W}", json={"stale_days": 0}).ok and not stale(Bo)[1], "#266: stale_days 0 = never")
check(A.patch(B + f"/api/lists/{W}", json={"stale_days": None}).ok and T_OLD in stale(A)[1], "#266: null = the default again")
check(A.patch(B + f"/api/lists/{W}", json={"stale_days": "x"}).status_code == 400 and A.patch(B + f"/api/lists/{W}", json={"stale_days": 999}).status_code == 400
      and A.patch(B + f"/api/lists/{W}", json={"agent_followup": "yes"}).status_code == 400, "#266: invalid values 400")
check(Bo.patch(B + f"/api/lists/{W}", json={"stale_days": 3}).status_code == 403 and Bo.patch(B + f"/api/lists/{W}", json={"agent_followup": True}).status_code == 403,
      "#266: a member (not admin) cannot change it")
check(requests.patch(V + f"/lists/{W}", headers=CLH, json={"agent_followup": True}).status_code in (403, 404), "#266: never an agent")
lst = requests.get(V + f"/lists/{W}", headers=CLH).json()
check(lst.get("stale_days") is None and lst.get("agent_followup") is False, f"#266: v1 list output {lst.get('stale_days')} {lst.get('agent_followup')}")


def stale_events():
    r = requests.get(V + "/agent/events?since=0&limit=200", headers=CLH)
    return [e for e in r.json().get("data", []) if e["event"] == "stale_tasks"] if r.ok else []


time.sleep(3)
check(not stale_events(), "#266: no event while 'Agent follows up' is off")
check(A.patch(B + f"/api/lists/{W}", json={"agent_followup": True}).ok, "#266: owner switches on 'Agent follows up'")
check(A.get(B + "/api/state").json()["lists"] and any(x["id"] == W and x["agent_followup"] for x in A.get(B + "/api/state").json()["lists"]),
      "#266: the list carries agent_followup in the app state")
ev = []
for _ in range(30):
    ev = stale_events()
    if ev:
        break
    time.sleep(0.5)
d0 = ev[0]["data"] if ev else {}
check(len(ev) == 1 and {t["id"] for t in d0.get("tasks", [])} == {T_OLD, T_WAIT, T_DAVE} and d0.get("count") == 3
      and d0.get("lists") == [{"id": W, "name": "Work"}] and "comment" in d0.get("hint", ""), f"#266: ONE bundled event stale_tasks {d0}")
time.sleep(3)
check(len(stale_events()) == 1, "#266: once a day (no second event)")
check(bool(dbx("SELECT stale_sent FROM agents WHERE user_id=?", (CL,))[0][0]), "#266: the day is noted (agents.stale_sent)")

# ---------------------------------------------------------------- #269 time gaps
r = A.get(B + "/api/time/gaps")
g0 = r.json() if r.ok else {}
check(r.ok and g0.get("days") == [] and g0.get("to") and g0.get("from"), f"#269: no gaps yet {r.status_code} {g0}")
to = date.fromisoformat(g0["to"])
busy = (datetime.now(timezone.utc) - timedelta(days=1)).date()  # the setup's comment / time entry (ago(1)) fall around this day
wd = [to - timedelta(days=i) for i in range(0, 14) if (to - timedelta(days=i)).weekday() < 5 and abs((to - timedelta(days=i) - busy).days) > 1][:4]
we = next(to - timedelta(days=i) for i in range(0, 14) if (to - timedelta(days=i)).weekday() >= 5)
noon = lambda d: f"{d.isoformat()}T11:00:00+00:00"  # noqa: E731
dbx("INSERT INTO comments(task_id, user_id, body, created_at) VALUES(?,?,?,?)", (T_OLD, ALICE, "worked", noon(wd[0])), write=True)
dbx("INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)", (T_NEW, ALICE, "title", "{}", noon(wd[1])), write=True)
dbx("INSERT INTO comments(task_id, user_id, body, created_at) VALUES(?,?,?,?)", (T_PRIV, ALICE, "private work", noon(wd[2])), write=True)
dbx("INSERT INTO comments(task_id, user_id, body, created_at) VALUES(?,?,?,?)", (T_OLD, ALICE, "and tracked", noon(wd[3])), write=True)
dbx("INSERT INTO time_entries(user_id, task_id, list_id, start, end, seconds, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
    (ALICE, T_OLD, W, noon(wd[3]), noon(wd[3]), 1800, noon(wd[3]), noon(wd[3])), write=True)
dbx("INSERT INTO comments(task_id, user_id, body, created_at) VALUES(?,?,?,?)", (T_OLD, ALICE, "weekend", noon(we)), write=True)
g = A.get(B + "/api/time/gaps").json()
days = {x["date"]: x for x in g["days"]}
check(set(days) == {wd[0].isoformat(), wd[1].isoformat(), wd[2].isoformat()}, f"#269: gaps = working days with work but no time {sorted(days)} vs {wd}")
check(days.get(wd[0].isoformat(), {}).get("tasks") == [{"id": T_OLD, "title": "Old offer", "list_id": W}], f"#269: the day's tasks {days.get(wd[0].isoformat())}")
check([x["date"] for x in g["days"]] == sorted(days, reverse=True), "#269: newest day first")
r = requests.get(V + f"/time/gaps?user_id={ALICE}", headers=CLH)
ga = {x["date"] for x in r.json().get("days", [])} if r.ok else r.text
check(r.ok and ga == {wd[0].isoformat(), wd[1].isoformat()} and r.json()["user_id"] == ALICE,
      f"#269: the agent for alice: only lists both see (not the private one) {r.status_code} {ga}")
check(requests.get(V + f"/time/gaps?user_id={BOB}", headers=CLH).status_code == 404, "#269: agent + a member who may not chat with it -> 404")
check(requests.get(V + f"/time/gaps?user_id={CAROL}", headers=CLH).status_code == 404, "#269: agent + a stranger -> 404")
check(requests.get(V + f"/time/gaps?user_id={CL}", headers=CLH).json().get("days") == [], "#269: the agent itself: no gaps")
check(requests.get(V + "/time/gaps?days=x", headers=CLH).status_code == 400 and requests.get(V + "/time/gaps?x=1", headers=CLH).status_code == 400,
      "#269: bad parameters 400")
r = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read"]})
if r.ok and r.json().get("token"):
    check(requests.get(V + f"/time/gaps?user_id={ALICE}", headers={"Authorization": "Bearer " + r.json()["token"]}).status_code == 404,
          "#269: a person's token cannot read someone else's gaps")
gb = Bo.get(B + "/api/time/gaps").json().get("days")
check(all(t["id"] == T_CMT for x in gb for t in x["tasks"]), f"#269: bob's gaps only from his own work (his comment) {gb}")

# ---------------------------------------------------------------- OpenAPI + database
spec = requests.get(V + "/openapi.json").json()
check("/stale" in spec["paths"] and "/time/gaps" in spec["paths"] and "StaleTask" in spec["components"]["schemas"], "OpenAPI: /stale, /time/gaps")
cols = {r[1] for r in dbx("PRAGMA table_info(lists)")} | {"a." + r[1] for r in dbx("PRAGMA table_info(agents)")}
check({"stale_days", "agent_followup", "a.stale_sent"} <= cols, "migration: new columns only")
dbx("INSERT INTO lists(name, owner_id, created_at) VALUES('written like 2.33', ?, ?)", (ALICE, ago(0)), write=True)
check(dbx("SELECT stale_days, agent_followup FROM lists WHERE name='written like 2.33'")[0] == (None, 0), "migration: a row written by 2.33 gets the defaults")

print(f"p2340_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
