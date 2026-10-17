#!/usr/bin/env python3
"""2.53.0 API tests, part C: the bell of one task per person -- As the list / Muted / Urgent (#1424).
 - rights: my own bell needs read access to the task; "for others" only the list's owner / admins, only people of the
   list (a stranger 404, an agent 404 as a target, a member 403); an agent's token never reaches the bell routes;
   a member sees only their own bell, an admin also the people of the list
 - effect: Urgent = every change and every comment by someone else is a push at priority 5 (also in a burst, also when
   the person is neither creator nor assignee); Muted = no push about the task (the News item stays)
 - end: "until a date" in the past -> as the list; "until completed": the completion still pushes, later changes not
 - "accept urgency from others" off: someone else's urgency counts as the list (still shown), my own still works
 - history: setting for others and switching off someone else's urgency are lines (counts only, no names);
   undo puts back exactly the rows of one change (own and admin's)
 - "all" = the humans of the list who see the task (no agent); a News item for the people marked by someone else
 - rollback safety: one new table (task_bell), one new user setting (tbl_accept)
usage: p253_c_api_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time
from datetime import timedelta

import dbx as dbxm
import requests
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
T0 = testclock.today()


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


def q(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def clear():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


def to(topic, wait=1.5):
    time.sleep(wait)
    return [p for p in pushes() if p["topic"] == topic]


if not os.environ.get("P253C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"ntfy_topic": "t-alice"})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com",
                                       "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "helper", "display_name": "Helper"})
assert r.status_code in (200, 201), r.text
AG, AGTOK = r.json()["id"], r.json()["token"]
L = A.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: bob edits")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": CAROL, "role": "admin"}).ok, "setup: carol is a list admin")
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the agent is in the list")


def task(s, title, **k):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": L, **k})
    assert r.ok, r.text
    return r.json()["id"]


def bell(s, tid):
    return s.get(B + f"/api/tasks/{tid}/bell")


def put(s, tid, **b):
    return s.put(B + f"/api/tasks/{tid}/bell", json=b)


def comment(s, tid, text):
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": text})
    assert r.ok, r.text


def acts(tid, kind="bell"):
    return [json.loads(x[0]) if isinstance(x[0], str) else x[0] for x in q("SELECT data FROM activity WHERE task_id=? AND kind=? ORDER BY id", (tid, kind))]


T = task(A, "Release notes")

# ================================================================== rights
j = bell(Bo, T).json()
check(j["mine"]["level"] == "list" and j["can_others"] is False and "people" not in j, "member: own bell as the list, no people " + json.dumps(j)[:200])
check(bell(Da, T).status_code == 404 and put(Da, T, level="urgent").status_code == 404, "stranger: 404 for reading and setting")
check(put(Bo, T, level="urgent", users=[CAROL]).status_code == 403, "member: setting for others 403")
ja = bell(Ca, T).json()
check(ja["can_others"] is True and {p["id"] for p in ja["people"]} == {ALICE, BOB}, "list admin: sees the people of the list (no agent, not herself) " + json.dumps(ja)[:300])
check(put(Ca, T, level="urgent", users=[DAVE]).status_code == 404, "admin: a person outside the list 404")
check(put(Ca, T, level="urgent", users=[AG]).status_code == 404, "admin: an agent is never marked urgent (404)")
check(put(Ca, T, level="loud").status_code == 400 and put(Ca, T, level="urgent", until="2020-01-01").status_code == 400
      and put(Ca, T, level="urgent", until="tomorrow").status_code == 400, "bad level / past or broken date 400")
check(put(Ca, T, level="mute", users=[BOB]).status_code == 400, "admin: only urgent / list for others")
agh = {"Authorization": "Bearer " + AGTOK}
ra, rb = requests.get(B + f"/api/tasks/{T}/bell", headers=agh), requests.put(B + f"/api/tasks/{T}/bell", headers={**agh, **H}, json={"level": "urgent", "users": [BOB]})
check(ra.status_code in (401, 403, 404) and rb.status_code in (401, 403, 404), f"agent token: no access to the bell routes ({ra.status_code}, {rb.status_code})")
check(not q("SELECT 1 FROM task_bell"), "nothing stored by the refused calls")

# ================================================================== admin sets urgent for bob
clear()
r = put(Ca, T, level="urgent", users=[BOB])
check(r.ok and r.json()["changed"] == 1 and r.json()["act"], "admin sets urgent for bob " + r.text[:200])
ACT1 = r.json()["act"]
jb = bell(Bo, T).json()["mine"]
check(jb["level"] == "urgent" and jb["by_name"] == "Carol" and jb["active"] and jb["until"] is None, "bob sees: urgent, set by Carol, until completed " + json.dumps(jb))
pb = to("t-bob")
check(any(p["prio"] == "5" and "Carol" in p["msg"] for p in pb), "bob gets a push at priority 5 about the marking " + json.dumps(pb)[:300])
check(any(n["kind"] == "tbl_urgent" and n["task_id"] == T for n in Bo.get(B + "/api/news").json()["items"]), "bob gets a News item")
a = acts(T)
check(len(a) == 1 and a[0].get("level") == "urgent" and a[0].get("n") == 1 and "users" not in a[0] and str(BOB) not in json.dumps(a[0]),
      "history: one line with the count only " + json.dumps(a))
check(bell(Ca, T).json()["people"] and next(p for p in bell(Ca, T).json()["people"] if p["id"] == BOB)["level"] == "urgent", "admin sees bob urgent")
check("people" not in bell(Bo, T).json(), "bob does not see the others")

# every change and every comment by someone else -> priority 5, also in a burst
clear()
A.patch(B + f"/api/tasks/{T}", json={"title": "Release notes v2"})
pb = to("t-bob")
check(len(pb) == 1 and pb[0]["prio"] == "5" and "Urgent" in pb[0]["title"], "a title change pushes to bob at 5 " + json.dumps(pb)[:300])
clear()
comment(A, T, "first")
comment(A, T, "second")
pb = to("t-bob")
check(len(pb) == 2 and all(p["prio"] == "5" for p in pb), "both comments of a burst push at 5 " + json.dumps(pb)[:300])
clear()
comment(Bo, T, "my own")
Bo.patch(B + f"/api/tasks/{T}", json={"priority": 3})
check(not to("t-bob"), "my own changes and comments never push to me")

# ================================================================== mute
T2 = task(Bo, "Bob's task")
clear()
comment(A, T2, "normal")
check(len(to("t-bob")) == 1, "baseline: a comment on bob's task pushes")
check(put(Bo, T2, level="mute").ok and bell(Bo, T2).json()["mine"]["level"] == "mute", "bob mutes his task")
# 2.53.0 (#1424, review): someone's own "Muted" is private -- the admin sees it as "As the list"
check(all(p["level"] == "list" for p in bell(Ca, T2).json().get("people", []) if p["id"] == BOB), "admin does not see bob's mute")
time.sleep(3.2)  # TASKS_PUSH_GAP: the next comment would push again
clear()
comment(A, T2, "muted")
check(not to("t-bob"), "muted: no push")
check(q("SELECT COUNT(*) FROM notifications WHERE user_id=? AND task_id=? AND kind='comment'", (BOB, T2))[0][0] == 2, "muted: the News items stay")
check(not acts(T2), "own mute is no history line")

# ================================================================== until a date
T3 = task(A, "Dated")
check(put(Ca, T3, level="urgent", until=T0.isoformat(), users=[BOB]).ok, "urgent until today")
time.sleep(1)  # the push about the marking itself
clear()
A.patch(B + f"/api/tasks/{T3}", json={"title": "Dated 2"})
check([p["prio"] for p in to("t-bob")] == ["5"], "until today: still urgent")
q("UPDATE task_bell SET until=? WHERE task_id=?", ((T0 - timedelta(days=1)).isoformat(), T3))
clear()
A.patch(B + f"/api/tasks/{T3}", json={"title": "Dated 3"})
check(not to("t-bob"), "until yesterday: as the list again (no push for a non-creator)")
check(bell(Bo, T3).json()["mine"]["active"] is False, "expired urgency shows as not active")

# ================================================================== accept from others off
check(Bo.patch(B + "/api/settings", json={"tbl_accept": "0"}).ok, "bob refuses urgency from others")
clear()
A.patch(B + f"/api/tasks/{T}", json={"title": "Release notes v3"})
check(not to("t-bob"), "refused: someone else's urgency counts as the list")
jb = bell(Bo, T).json()
check(jb["mine"]["level"] == "urgent" and jb["mine"]["active"] is False and jb["accept"] is False, "refused: still shown, not active")
T4 = task(A, "Self urgent")
check(put(Bo, T4, level="urgent").ok, "bob sets his own urgency")
clear()
A.patch(B + f"/api/tasks/{T4}", json={"title": "Self urgent 2"})
check([p["prio"] for p in to("t-bob")] == ["5"], "own urgency works with the switch off")
Bo.patch(B + "/api/settings", json={"tbl_accept": "1"})

# ================================================================== switching off + undo
r = put(Bo, T, level="list")
check(r.ok and bell(Bo, T).json()["mine"]["level"] == "list", "bob switches carol's urgency off")
a = acts(T)
check(len(a) == 2 and a[1].get("self") == 1 and a[1].get("level") == "list", "history: switching off is a line " + json.dumps(a))
check(Bo.post(B + f"/api/tasks/{T}/bell/undo", json={"act": r.json()["act"]}).ok, "bob undoes")
jb = bell(Bo, T).json()["mine"]
check(jb["level"] == "urgent" and jb["by_name"] == "Carol", "undo: urgent set by Carol again " + json.dumps(jb))
check(Ca.post(B + f"/api/tasks/{T}/bell/undo", json={"act": r.json()["act"]}).json()["undone"] == 0, "someone else cannot undo bob's step")
r = put(Ca, T3, level="urgent", users=[BOB])
check(Ca.post(B + f"/api/tasks/{T3}/bell/undo", json={"act": r.json()["act"]}).ok, "admin undoes her marking")
jb = bell(Bo, T3).json()["mine"]
check(jb["level"] == "urgent" and jb["until"] == (T0 - timedelta(days=1)).isoformat(), "admin undo: the previous row is back " + json.dumps(jb))
check(put(Ca, T, level="list", users=[BOB]).json()["changed"] == 1 and bell(Bo, T).json()["mine"]["level"] == "list", "admin takes her urgency back")
put(Bo, T2, level="list")
check(put(Ca, T2, level="list", users=[BOB]).json()["changed"] == 0, "admin 'list' never touches a person's own choice")

# ================================================================== all + completion
T5 = task(Bo, "Everyone")
r = put(Ca, T5, level="urgent", users="all")
check(r.ok and r.json()["changed"] == 3, "all: alice, bob, carol (not the agent) " + r.text[:200])
time.sleep(1)
check({x[0] for x in q("SELECT user_id FROM task_bell WHERE task_id=? AND level='urgent'", (T5,))} == {ALICE, BOB, CAROL}, "all: rows")
clear()
r = Ca.post(B + f"/api/tasks/{T5}/complete", json={})
check(r.ok, "carol completes " + r.text[:200])
pa, pb = to("t-alice"), [p for p in pushes() if p["topic"] == "t-bob"]
check(len(pb) == 1 and pb[0]["prio"] == "5" and len(pa) == 1 and pa[0]["prio"] == "5", "completion: one urgent push each " + json.dumps(pa + pb)[:300])
clear()
Ca.patch(B + f"/api/tasks/{T5}", json={"title": "Everyone (done)"})
check(not to("t-bob") and not [p for p in pushes() if p["topic"] == "t-alice"], "until completed: a later change does not push")

# ================================================================== workspace boundary
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ALICE})
check(r.ok, "setup: an organisation " + r.text[:200])
ORG = r.json().get("id") if r.ok else None
if ORG:
    LB = A.post(B + "/api/lists", json={"name": "Beta work", "org_id": ORG}).json()["id"]
    TB = A.post(B + "/api/tasks", json={"title": "Beta task", "list_id": LB}).json()["id"]
    check(put(A, TB, level="urgent", users=[BOB]).status_code == 404, "boundary: a person outside the organisation (not in its list) 404")
    check(bell(Bo, TB).status_code == 404 and put(Bo, TB, level="urgent").status_code == 404, "boundary: the outsider neither reads nor sets the bell")
    check(put(A, TB, level="urgent").ok and q("SELECT org_id FROM task_bell WHERE task_id=? AND user_id=?", (TB, ALICE))[0][0] == ORG, "the row carries the organisation")
    q("UPDATE task_bell SET org_id=NULL WHERE task_id=?", (TB,))
    check(bell(A, TB).json()["mine"]["level"] == "list", "a row of another workspace (the task moved) is ignored")
    q("UPDATE task_bell SET org_id=? WHERE task_id=?", (ORG, TB))
    q("INSERT INTO task_bell(task_id,user_id,org_id,level,created_at,updated_at) VALUES(?,?,?,?,?,?)", (TB, BOB, ORG, "urgent", "2026-01-01", "2026-01-01"))
    rows = q("SELECT b.task_id, b.user_id FROM task_bell b JOIN users u ON u.id=b.user_id WHERE b.org_id IS NOT NULL AND (u.kind='agent' OR u.kind!='agent' AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=b.org_id AND om.user_id=b.user_id))")
    check([list(x) for x in rows] == [[TB, BOB]], "the nightly boundary check finds the outsider's row " + str(rows))

# ================================================================== rollback safety
cols = {x[0] for x in q("SELECT column_name FROM information_schema.columns WHERE table_name='task_bell'")}
check({"task_id", "user_id", "org_id", "level", "until", "set_by"} <= cols, "task_bell table")

print(f"p253_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
