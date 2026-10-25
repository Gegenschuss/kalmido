#!/usr/bin/env python3
"""2.191.0 API tests, part C: fewer database statements with the same answers (#2593 linked task titles, #2516 the
watchdog, #2507 the delta after the poll). Own container (start.sh). Invented people and texts only.
freelancer-matrix: lists, tasks
 - #2593 GET /api/fields/task-refs: the same tasks as before for the owner (all), a participant of two lists (assigned
   + their subtasks + the parent as context, nothing else), someone of another organisation (none) and a person without
   an organisation (only the own); the statements no longer grow with the number of tasks of one list
 - #2516 the watchdog: reminders, nags and event reminders with nothing due cost (almost) no statements (the old path,
   forced, is measured for comparison); a due reminder / nag / event reminder still fires (reminded / nag_at /
   ev_reminded written), a future one does not; a broken reminders value still takes the old path
 - #2507 GET /api/state/delta?lean=1: a change only someone else sees answers lean (no order / timer, fewer statements);
   the own change from another device (order of "My tasks") and a change the person sees answer in full as before;
   without lean=1 the answer is the old one (older clients); the same for a person without an organisation
 - PERF lines (information): the statement counts before / after
usage: p2191_c_perf_test.py <datadir>   (P2191C_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

from kt import FAILS, OKS, check, until, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FEATURES = "cal,collab,comments,events,fields,progress"
TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    return out[-1] if out else "ERR " + r.stderr[-600:]


if not (os.environ.get("P2191C_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ORG = {}
for name in ("Alpha", "Beta"):
    r = A.post(B + "/api/admin/orgs", json={"name": name})
    assert r.status_code in (200, 201), r.text
    ORG[name] = r.json()["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u, o in (("bob", "Alpha"), ("dave", "Alpha"), ("carl", "Beta")):
    r = A.post(B + "/api/users", json={"orgs": [ORG[o]], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Da, Ca = login(B, "bob"), login(B, "dave"), login(B, "carl")
for s in (A, Bo, Da, Ca):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok
FID, Fr = freelancer(B, A)  # freelancer-matrix: lists, tasks (task-refs and the lean delta in the own private space)


def task(s, title, lid, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def refs(s, ids):
    r = s.get(B + "/api/fields/task-refs", params={"ids": ",".join(str(i) for i in ids)})
    return r, ({t["id"] for t in r.json().get("tasks", [])} if r.ok else None)


# ================================================================ #2593: task-refs per list, same result
L1 = A.post(B + "/api/lists", json={"name": "Shoot plan", "org_id": ORG["Alpha"]}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Edit plan", "org_id": ORG["Alpha"]}).json()["id"]
for lid in (L1, L2):
    check(A.put(B + f"/api/lists/{lid}/members", json={"user_id": uid["dave"], "role": "participant"}).ok, f"setup: dave participant of {lid}")
P1 = task(A, "Parent", L1)
C1 = task(A, "Child for dave", L1, parent_id=P1, assignee_id=uid["dave"])
G1 = task(A, "Grandchild", L1, parent_id=C1)
O1 = task(A, "Other in L1", L1)
O1b = task(A, "Other child", L1, parent_id=P1)
D2 = task(A, "Dave in L2", L2, assignee_id=uid["dave"])
O2 = task(A, "Other in L2", L2)
CL = Ca.post(B + "/api/lists", json={"name": "Beta board"}).json()["id"]
CT1 = task(Ca, "Carl's task", CL)
FL = Fr.post(B + "/api/lists", json={"name": "Own work"}).json()["id"]
FT1 = task(Fr, "Frida's task", FL)
ALL = [P1, C1, G1, O1, O1b, D2, O2, CT1, FT1, 99999999]

r, got = refs(A, ALL)
check(got == {P1, C1, G1, O1, O1b, D2, O2}, f"#2593 owner: every task of the own lists, nothing foreign {got}")
r, got = refs(Da, ALL)
check(got == {P1, C1, G1, D2}, f"#2593 participant of two lists: assigned + subtask + parent as context {got}")
r, got = refs(Ca, ALL)
check(got == {CT1}, f"#2593 another organisation: only the own task {got}")
r, got = refs(Fr, ALL)
check(got == {FT1}, f"#2593 without an organisation: only the own task (freelancer-matrix: lists) {got}")
r, got = refs(Da, [O1, O2, CT1])
check(r.ok and got == set(), f"#2593 participant: none of the others {got}")
check(refs(Bo, [])[1] == set(), "#2593 no ids: empty list")
check(Bo.get(B + "/api/fields/task-refs", params={"ids": "1,x"}).status_code == 400, "#2593 a wrong id: 400 as before")
# the statements no longer grow per task of one list (before: list role + two participant queries per task)
MANY = [task(A, f"Bulk {i}", L1, assignee_id=uid["dave"]) for i in range(30)]
n2 = nstmt(refs(Da, MANY[:2])[0])
r, got = refs(Da, MANY)
n30 = nstmt(r)
check(got == set(MANY), "#2593 participant: 30 assigned tasks visible")
check(0 < n30 <= n2 + 2, f"#2593 statements of 30 tasks of one list ~ those of 2 ({n2} -> {n30})")
print(f"PERF #2593 task-refs as participant: 2 tasks {n2} statements, 30 tasks {n30} statements", flush=True)

BL = next(x for x in Bo.get(B + "/api/state").json()["lists"] if x["is_inbox"])["id"]
A.patch(B + f"/api/users/{uid['bob']}", json={"ntfy_topic": "t-bob"})  # the nag / reminder pushes need a channel
assert Bo.patch(B + "/api/settings", json={"quiet_from": "", "quiet_to": ""}).ok  # no nags in the quiet hours (22-07 by default)

# ================================================================ #2507: the lean delta (before the watchdog part: its writes
# to bob's tasks would count as changes bob sees)
def ver(s):
    return s.get(B + "/api/version").json()["v"]


def delta(s, since, lean=True):
    r = s.get(B + "/api/state/delta", params={"since": since, **({"lean": "1"} if lean else {})})
    return r.json(), nstmt(r)


Bo2 = login(B, "bob")  # bob's second device
BT = task(Bo, "Bob's own", BL)
OL = A.post(B + "/api/lists", json={"name": "Shared with bob", "org_id": ORG["Alpha"]}).json()["id"]
check(A.put(B + f"/api/lists/{OL}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob member of a list")
OT = task(A, "Shared task", OL)
v0 = ver(Bo2)
check(Ca.patch(B + f"/api/tasks/{CT1}", json={"title": "Carl's task (2)"}).ok, "carl changes his own task")
j, n_lean = delta(Bo2, v0)
check(j.get("full") is False and j.get("lean") is True and j.get("tasks") == [] and j.get("gone") == [] and "mine_order" not in j,
      f"#2507 a change only another organisation sees: lean {j}")
j2, n_old = delta(Bo2, v0, lean=False)
check(j2.get("full") is False and "lean" not in j2 and "mine_order" in j2 and j2.get("tasks") == [],
      f"#2507 without lean=1 the old answer (older clients) {sorted(j2)}")
check(0 < n_lean < n_old, f"#2507 lean costs fewer statements ({n_old} -> {n_lean})")
print(f"PERF #2507 delta after a change elsewhere: {n_old} -> {n_lean} statements", flush=True)
v1 = ver(Bo2)
check(Bo.put(B + "/api/tasks/mine-order", json={"ids": [BT]}).ok, "bob orders My tasks on his first device")
j, _ = delta(Bo2, v1)
check(j.get("full") is False and not j.get("lean") and str(BT) in {str(k) for k in (j.get("mine_order") or {})},
      f"#2507 the own change from another device: full delta with the order {j.get('mine_order')}")
v2 = ver(Bo2)
check(A.patch(B + f"/api/tasks/{OT}", json={"title": "Shared task (2)"}).ok, "alice changes the shared task")
j, _ = delta(Bo2, v2)
check(j.get("full") is False and not j.get("lean") and [t["id"] for t in j.get("tasks", [])] == [OT] and "mine_order" in j,
      f"#2507 a change bob sees: the task as before {[t['id'] for t in j.get('tasks', [])]}")
v3 = ver(Ca)
check(Bo.patch(B + f"/api/tasks/{BT}", json={"title": "Bob's own (2)"}).ok, "bob changes his task")
j, _ = delta(Ca, v3)
check(j.get("lean") is True and j.get("tasks") == [], f"#2507 carl (other organisation): lean, nothing of bob {j}")
# the person without an organisation
v4 = ver(Fr)
check(Ca.patch(B + f"/api/tasks/{CT1}", json={"title": "Carl's task (3)"}).ok, "carl changes again")
j, _ = delta(Fr, v4)
check(j.get("lean") is True and j.get("tasks") == [], f"#2507 without an organisation: lean after a foreign change (freelancer-matrix: tasks) {j}")
v5 = ver(Fr)
check(Fr.patch(B + f"/api/tasks/{FT1}", json={"title": "Frida's task (2)"}).ok, "frida changes her task")
j, _ = delta(Fr, v5)
check(not j.get("lean") and [t["id"] for t in j.get("tasks", [])] == [FT1] and "mine_order" in j,
      f"#2507 without an organisation: the own change in full {j.get('tasks')}")
r = Fr.get(B + "/api/state/delta", params={"since": "x", "lean": "1"})
check(r.ok and r.json().get("full") is True, "#2507 a wrong since: full as before")
# 2.191.0 F1 (#2507): a write from the background (watchdog: a forgotten timer stopped) ends the lean answer
v6 = ver(Fr)
check(Ca.patch(B + f"/api/tasks/{CT1}", json={"title": "Carl's task (4)"}).ok, "carl changes again")
res = in_app("from kalmido.core.db import connect, bump\nc = connect()\nbump(c)\nc.commit()\nc.close()\nprint('bumped')")
check(res == "bumped", f"#2507 a bump without a request ran {res[:300]}")
j, _ = delta(Fr, v6)
check(not j.get("lean") and (j.get("full") is True or ("timer" in j and "mine_order" in j)),
      f"#2507 after a background write: no lean answer (full reload or the delta with the timer; freelancer-matrix: tasks) {sorted(j)}")
v7 = ver(Fr)
check(Ca.patch(B + f"/api/tasks/{CT1}", json={"title": "Carl's task (5)"}).ok, "carl changes again")
j, _ = delta(Fr, v7)
check(j.get("lean") is True, f"#2507 a foreign change after the background write: lean again {sorted(j)}")

# ================================================================ #2516: the watchdog sections
now = datetime.fromisoformat(in_app("from kalmido.core.db import local_now\nprint(local_now().replace(tzinfo=None).isoformat())"))
far = (now + timedelta(days=3)).date().isoformat()
# not due: reminders, nags, events in three days; the tasks in alice's list assigned to bob (the recipient is not the list
# owner: the old path checked his access per task)
for i in range(20):
    task(A, f"Later {i}", OL, due=far, due_time="10:00", reminders="0,15", assignee_id=uid["bob"])
for i in range(10):
    check(A.patch(B + f"/api/tasks/{task(A, f'Nag later {i}', OL, due=far, due_time='10:00', assignee_id=uid['bob'])}",
                  json={"nag": "5"}).ok, f"setup: nag on task {i}")
CAL = Bo.post(B + "/api/evcals", json={"name": "Work", "color": "#2dd4bf"}).json()
for i in range(10):
    r = Bo.post(B + "/api/events", json={"title": f"Meeting {i}", "cal_id": CAL["id"], "start": f"{far}T09:00", "end": f"{far}T10:00",
                                         "reminders": [15]})
    check(r.ok, f"setup: event {i} {r.text[:120]}")
COUNT = """
from kalmido.core.db import connect, local_now
from kalmido.notify import push as P
from kalmido.events import model as EV
class W:
    def __init__(s, c): s.c, s.n = c, 0
    def execute(s, *a, **k):
        s.n += 1
        return s.c.execute(*a, **k)
    def __getattr__(s, k): return getattr(s.c, k)
c = connect()
users = {r["id"]: r for r in c.execute("SELECT * FROM users WHERE disabled=0")}
S = P._wd_settings(c, users)
LG = {u: "en" for u in users}
out = {}
for mode in ("new", "old"):
    if mode == "old":  # the path before 2.191.0: every row looked up
        P.wd_rem_maybe = P.wd_nag_maybe = EV.ev_wd_maybe = lambda *a: True
    for name, fn in (("rem", P._wd_reminders), ("nag", P._wd_nags), ("ev", EV._wd_events)):
        w = W(c)
        fn(w, users, S, LG, local_now())
        out[mode + "_" + name] = w.n
c.close()
print(json.dumps(out))
"""
res = in_app(COUNT)
try:
    cnt = json.loads(res)
except ValueError:
    cnt = {}
check(bool(cnt), f"#2516 the sections ran inside the app: {res[:400]}")
if cnt:
    # 2.281.0 B (#3117): the old path reads list roles once per tick too (fewer statements to compare with)
    check(cnt["new_rem"] <= 2 and cnt["old_rem"] >= cnt["new_rem"] + 5, f"#2516 reminders with nothing due: no lookup per task {cnt}")
    check(cnt["new_nag"] <= 2 and cnt["old_nag"] >= cnt["new_nag"] + 10, f"#2516 nags with nothing due: no lookup per task {cnt}")
    check(cnt["new_ev"] <= 4 and cnt["old_ev"] >= cnt["new_ev"] + 10, f"#2516 event reminders with nothing due: no lookup per event {cnt}")
    print(f"PERF #2516 watchdog statements (old -> new): reminders {cnt['old_rem']} -> {cnt['new_rem']}, nags {cnt['old_nag']} -> "
          f"{cnt['new_nag']}, events {cnt['old_ev']} -> {cnt['new_ev']}", flush=True)

# due ones still fire (the running watchdog, every second in the test container)
soon = now + timedelta(minutes=10)
TR = task(Bo, "Call the studio", BL, due=soon.date().isoformat(), due_time=soon.strftime("%H:%M"), reminders="15")
key = f"{soon.date().isoformat()} {soon.strftime('%H:%M')}|15"
check(until(lambda: key in (dbx("SELECT reminded FROM tasks WHERE id=?", (TR,))[0]["reminded"] or ""), 15),
      "#2516 a reminder that is due now fires (reminded written)")
TL = dbx("SELECT id, reminded FROM tasks WHERE title='Later 0'")[0]
check(not json.loads(TL["reminded"] or "[]"), "#2516 a reminder in three days does not fire")
past = now - timedelta(minutes=1)
TN = task(Bo, "Send the cut", BL, due=past.date().isoformat(), due_time=past.strftime("%H:%M"))
check(Bo.patch(B + f"/api/tasks/{TN}", json={"nag": "5"}).ok, "setup: nag every 5 minutes")
check(until(lambda: (dbx("SELECT nag_at FROM tasks WHERE id=?", (TN,))[0]["nag_at"] or "") != "", 15), "#2516 a nag that is due fires (nag_at written)")
st = now + timedelta(minutes=10)
EVS = Bo.post(B + "/api/events", json={"title": "Soon", "cal_id": CAL["id"], "start": st.strftime("%Y-%m-%dT%H:%M"),
                                       "end": (st + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"), "reminders": [15]}).json()
check(until(lambda: dbx("SELECT 1 FROM ev_reminded WHERE event_id=? AND user_id=?", (EVS["id"], uid["bob"])), 15),
      "#2516 an event reminder that is due fires (ev_reminded written)")
EV0 = dbx("SELECT id FROM events WHERE title='Meeting 0'")[0]["id"]
check(not dbx("SELECT 1 FROM ev_reminded WHERE event_id=?", (EV0,)), "#2516 an event reminder in three days does not fire")
time.sleep(2)
check(len(dbx("SELECT k FROM ev_reminded WHERE event_id=? AND user_id=?", (EVS["id"], uid["bob"]))) == 1, "#2516 the event reminder only once")

print(f"\np2191_c_perf: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
