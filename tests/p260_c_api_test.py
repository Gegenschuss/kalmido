#!/usr/bin/env python3
"""2.60.0 API tests (part C): #1512 the review step.
 - the list setting (PUT /api/lists/{id}/review, editors; a viewer 403; a reviewer without access 400)
 - a reviewer only with access to the list: a person outside 400, an agent that is no member 400, an agent limited to other
   lists (agents.list_ids) 400, an agent of the list ok
 - moving a task into the review section: default reviewer, state pending, review_sec, News + push to the reviewer
 - "done only after approval": 409 on the web tick, the batch (task stays open), API v1 complete and v1 batch
 - only the reviewer / a list admin decides: the assignee 403 (also as reviewer of their own task), a stranger 404;
   changes = back to the previous section + News for the assignee; approve -> completing works
 - while the gate holds only the reviewer / a list admin changes or removes the reviewer
 - notification row "review" off -> no push (the News item stays)
 - an agent as reviewer: event review_requested, approves through API v1; an agent that is not the reviewer 403
 - git: a merged linked pull request approves the review (review_by null), "fixes #id" completes it in the same poll
 - a repeating task: the next occurrence needs its own approval
usage: p260_c_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timezone

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
GH = "http://127.0.0.1:8090"      # fake GitHub Enterprise (fake_git.py)
TOKEN = "ghp_fake_read_only_token_260c"
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


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=60, **k)


def q(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def pushes(topic, wait=1.5):
    time.sleep(wait)
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip() and json.loads(x)["topic"] == topic]
    except FileNotFoundError:
        return []


def clear():
    open(os.path.join(DATA, "ntfy.log"), "w").close()


STATE = {"8090": {"acme/app": {"token": TOKEN, "default_branch": "main", "pulls": [], "commits": {"main": []}, "status": {}, "checks": {}}}}


def put_state():
    tmp = os.path.join(DATA, "git.json.tmp")
    with open(tmp, "w") as f:
        json.dump(STATE, f)
    os.replace(tmp, os.path.join(DATA, "git.json"))


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def until(fn, t=20.0):
    t0 = time.time()
    while time.time() - t0 < t:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


env = dict(os.environ, EXTRA=" ".join(["-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1", "-e KALMIDO_GIT_POLL=2", "-e KALMIDO_GIT_TICK=1",
                                        "-e KALMIDO_SECRET_KEY=" + KEY]))
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
put_state()
subprocess.run(["cp", os.path.join(N, "fake_git.py"), DATA])
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_git.py"])
time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {}
for u in ("bob", "carol", "dave", "eve"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com",
                                       "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, EVE = ids["bob"], ids["carol"], ids["dave"], ids["eve"]
Bo, Ca, Da, Ev = sess("bob"), sess("carol"), sess("dave"), sess("eve")
for s in (Bo, Ca, Da, Ev):
    s.patch(B + "/api/settings", json={"lang": "en"})


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": name, "display_name": name.title()})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"], Api(r.json()["token"])


RV, rv = agent("reviewbot")      # member of P
OUT, out = agent("outsider")     # no member of P
P = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
OTHER = A.post(B + "/api/lists", json={"name": "Other"}).json()["id"]
for u, role in ((BOB, "edit"), (CAROL, "edit"), (DAVE, "view"), (RV, "edit")):
    r = A.put(B + f"/api/lists/{P}/members", json={"user_id": u, "role": role})
    assert r.ok, (u, role, r.status_code, r.text)
r = A.put(B + f"/api/lists/{OTHER}/members", json={"user_id": RV, "role": "edit"})  # one agent per list: the same one in OTHER
assert r.ok, r.text
assert A.patch(B + f"/api/lists/{P}", json={"agent_members": True}).ok
S1 = A.post(B + "/api/sections", json={"list_id": P, "name": "In progress"}).json()["id"]
S2 = A.post(B + "/api/sections", json={"list_id": P, "name": "Review"}).json()["id"]


def task(title, sec=S1, who=BOB, **k):
    r = Bo.post(B + "/api/tasks", json={"title": title, "list_id": P, "section_id": sec, "assignee_id": who, **k})
    assert r.ok, r.text
    return r.json()["id"]


def one(tid, s=A):
    return s.get(B + f"/api/tasks/{tid}").json()


def rvw(s, tid, **b):
    return s.post(B + f"/api/tasks/{tid}/review", json=b)


def news(s, kind="review"):
    return [x for x in s.get(B + "/api/news").json().get("items", []) if x["kind"] == kind]


# ---------------------------------------------------------------- the list setting
check(Da.put(B + f"/api/lists/{P}/review", json={"on": True}).status_code in (403, 404), "a viewer cannot switch the review step on")
check(Bo.put(B + f"/api/lists/{P}/review", json={"on": True, "reviewer": EVE}).status_code == 400, "a default reviewer without access: 400")
check(Bo.put(B + f"/api/lists/{P}/review", json={"on": True, "section": 999999}).status_code == 400, "a section of another list: 400")
r = Bo.put(B + f"/api/lists/{P}/review", json={"on": True, "reviewer": CAROL, "gate": True})
check(r.ok and json.loads(r.json()["review_cfg"]) == {"on": 1, "reviewer": CAROL, "section": None, "gate": 1}, "an editor switches it on " + r.text[:200])
lst = next(x for x in A.get(B + "/api/state").json()["lists"] if x["id"] == P)
check(json.loads(lst.get("review_cfg") or "{}").get("gate") == 1, "the list carries review_cfg")
check(Ev.put(B + f"/api/lists/{P}/review", json={"on": False}).status_code == 404, "a stranger: 404")

# ---------------------------------------------------------------- who may review
T1 = task("Login form")
check(rvw(Bo, T1, action="reviewer", reviewer_id=EVE).status_code == 400, "a person without access cannot review")
check(rvw(Bo, T1, action="reviewer", reviewer_id=OUT).status_code == 400, "an agent that is not in the list cannot review")
check(A.patch(B + f"/api/admin/agents/{RV}", json={"list_ids": [OTHER]}).ok, "setup: the agent limited to OTHER")
r = rvw(Bo, T1, action="reviewer", reviewer_id=RV)
check(r.status_code == 400 and "no access" in r.text, "an agent limited to other lists cannot review " + r.text[:200])
r = A.patch(B + f"/api/admin/agents/{RV}", json={"list_ids": []})
check(r.ok and not r.json().get("list_ids"), "the limit lifted again " + r.text[:200])
r = rvw(Bo, T1, action="reviewer", reviewer_id=RV)
check(r.ok and r.json().get("reviewer_id") == RV and not r.json().get("review"), "an agent of the list can review")
check(rvw(Bo, T1, action="reviewer", reviewer_id=None).status_code == 403, "with the gate on the assignee cannot remove the reviewer again")
check(rvw(A, T1, action="reviewer", reviewer_id=None).ok and "reviewer_id" not in one(T1), "a list admin removes it (field left out)")

# ---------------------------------------------------------------- into review: default reviewer, pending, News + push
clear()
r = Bo.patch(B + f"/api/tasks/{T1}", json={"section_id": S2})
t = one(T1)
check(r.ok and t.get("reviewer_id") == CAROL and t.get("review") == "pending" and t.get("review_sec") == S1, f"moved into Review: pending for carol {t}")
n = news(Ca)
check(n and n[0]["task_id"] == T1 and (n[0].get("data") or {}).get("state") == "pending", "carol has a News item about the review")
pc = pushes("t-carol")
check(len(pc) == 1 and "review" in pc[0]["title"].lower(), "carol gets a push " + json.dumps(pc)[:300])

# ---------------------------------------------------------------- the gate on every way
r = Bo.post(B + f"/api/tasks/{T1}/complete")
check(r.status_code == 409 and "Waiting for approval by Carol" in r.text, f"web tick: 409 {r.status_code} {r.text[:200]}")
r = Bo.post(B + "/api/tasks/batch", json={"ids": [T1], "action": "complete"})
check(one(T1)["status"] == 0 and any("Waiting for approval" in e for e in (r.json().get("errors") or [])), "batch: left open with the reason " + r.text[:200])
r = rv.req("POST", f"/tasks/{T1}/complete")
check(r.status_code == 409, f"API v1 complete: 409 ({r.status_code})")
rv.req("POST", "/tasks/batch", json={"ids": [T1], "action": "complete"})
check(one(T1)["status"] == 0, "API v1 batch: still open")
TS = Bo.post(B + "/api/tasks", json={"title": "sub", "list_id": P, "parent_id": T1}).json()["id"]
check(Bo.post(B + f"/api/tasks/{TS}/complete").ok, "a subtask without a reviewer completes freely")

# ---------------------------------------------------------------- who decides
check(rvw(Bo, T1, action="approve").status_code == 403, "the assignee cannot approve")
check(rvw(Ev, T1, action="approve").status_code == 404, "a stranger: 404")
check(rvw(Da, T1, action="approve").status_code == 403, "a viewer who is not the reviewer: 403")
check(rv.req("POST", f"/tasks/{T1}/review", json={"action": "approve"}).status_code == 403, "an agent that is not the reviewer: 403")
r = rvw(Ca, T1, action="approve")
check(r.ok and r.json().get("review") == "approved" and r.json().get("review_by") == CAROL, "the reviewer approves " + r.text[:200])
check(Bo.post(B + f"/api/tasks/{T1}/complete").ok and one(T1)["status"] == 2, "approved: completing works")

# changes: back to the previous section, the assignee is told
T2 = task("Export")
Bo.patch(B + f"/api/tasks/{T2}", json={"section_id": S2})
clear()
r = rvw(Ca, T2, action="changes", note="Add a header row")
t = one(T2)
check(r.ok and t.get("review") == "changes" and t.get("section_id") == S1, f"changes: back to In progress {t}")
nb = [x for x in news(Bo) if x["task_id"] == T2]
check(nb and nb[0]["data"].get("state") == "changes" and "header" in nb[0]["data"].get("note", ""), "bob has a News item with the note")
check(len(pushes("t-bob")) == 1, "bob gets a push")
check(Bo.post(B + f"/api/tasks/{T2}/complete").status_code == 409, "changes: still not done")
r = rvw(Bo, T2, action="request")
check(r.ok and r.json().get("review") == "pending" and r.json().get("section_id") == S2, "send for review again: into Review, pending")

# the assignee as reviewer of their own task: only a list admin approves
T3 = task("Own", who=CAROL)
rvw(Bo, T3, action="reviewer", reviewer_id=CAROL)
rvw(Bo, T3, action="request")
r = rvw(Ca, T3, action="approve")
check(r.status_code == 403 and "own task" in r.text, "no self-approval " + r.text[:200])
check(rvw(A, T3, action="approve").ok, "the list owner (admin) approves")

# while the gate holds: only the reviewer / an admin changes the reviewer
T4 = task("Locked")
Bo.patch(B + f"/api/tasks/{T4}", json={"section_id": S2})
check(rvw(Bo, T4, action="reviewer", reviewer_id=RV).status_code == 403, "the assignee cannot swap the reviewer while it waits")
check(rvw(Bo, T4, action="reviewer", reviewer_id=None).status_code == 403, "nor remove it")
check(Bo.patch(B + f"/api/tasks/{T4}", json={"reviewer_id": None, "review": "approved"}).ok and one(T4).get("review") == "pending",
      "PATCH does not touch the review fields")
r = rvw(Bo, T4, action="restore", reviewer_id=CAROL, review="approved")
check(r.status_code == 403, "restore cannot approve for someone else")
check(rvw(A, T4, action="reviewer", reviewer_id=RV).ok, "a list admin can")

# ---------------------------------------------------------------- notification row off -> no push, the News item stays
Ca.patch(B + "/api/settings", json={"notify": {"review": {"push": 0}}})
m = Ca.get(B + "/api/state").json().get("notify") or {}
check((m.get("review") or {}).get("push") is False, "the matrix has the row review " + json.dumps(m.get("review")))
clear()
T5 = task("Quiet")
Bo.patch(B + f"/api/tasks/{T5}", json={"section_id": S2})
check(not pushes("t-carol"), "row off: no push")
check(any(x["task_id"] == T5 for x in news(Ca)), "the News item stays")

# ---------------------------------------------------------------- an agent as reviewer
cur = rv.req("GET", "/agent").json()["cursor"]
T6 = task("Agent review")
rvw(Bo, T6, action="reviewer", reviewer_id=RV)
rvw(Bo, T6, action="request")


def events(since, want, t=10.0):
    t0, got = time.time(), []
    while time.time() - t0 < t:
        j = rv.req("GET", "/agent/events", params={"since": since}).json()
        got = [e for e in j.get("data", []) if e["event"] in want]
        if got:
            return got
        time.sleep(0.3)
    return got


ev = events(cur, {"review_requested"})
d = ev[0]["data"] if ev else {}
check(ev and (d.get("task") or {}).get("id") == T6 and (d.get("review") or {}).get("state") == "pending", f"agent event review_requested {d}")
r = rv.req("POST", f"/tasks/{T6}/review", json={"action": "approve"})
check(r.ok and r.json().get("review") == "approved", "the agent approves as the reviewer " + r.text[:200])
check(rv.req("POST", f"/tasks/{T6}/review", json={"action": "approve", "bogus": 1}).status_code == 400, "unknown field: 400")

# ---------------------------------------------------------------- git: a merged pull request counts
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "github", "base_url": GH, "repo": "acme/app", "token": TOKEN})
check(r.status_code in (200, 201), "connect the repository " + r.text[:200])
time.sleep(5)  # the first poll is the baseline
T7 = task("Merged PR")
T8 = task("Fixes keyword")
for x in (T7, T8):
    Bo.patch(B + f"/api/tasks/{x}", json={"section_id": S2})
now = iso(datetime.now(timezone.utc))
g = STATE["8090"]["acme/app"]
for n_, title, body in ((21, f"Search #{T7}", ""), (22, "Small fix", f"fixes #{T8}")):
    g["pulls"].insert(0, {"number": n_, "title": title, "body": body, "state": "closed", "merged_at": now, "html_url": f"{GH}/acme/app/pull/{n_}",
                          "user": {"login": "dev"}, "head": {"ref": f"feat-{n_}", "sha": f"sha{n_}"}, "updated_at": now})
put_state()
t7 = until(lambda: (lambda t: t if t.get("review") == "approved" else None)(one(T7)))
check(t7 and not t7.get("review_by"), f"a merged PR approves the review, review_by empty: {t7 and {k: t7.get(k) for k in ('review', 'review_by')}}")
t8 = until(lambda: (lambda t: t if t["status"] == 2 else None)(one(T8)))
check(t8 and t8.get("review") == "approved", "fixes #id: approved and completed in the same poll")
tl = A.get(B + f"/api/tasks/{T7}/timeline").json()
acts = [a for a in tl.get("activity", tl.get("items", [])) if a.get("kind") == "review"] if isinstance(tl, dict) else []
check(any("acme/app#21" in json.dumps(a) for a in acts) or not acts, "the history names the pull request")

# ---------------------------------------------------------------- repeats: the next occurrence needs its own approval
T9 = task("Weekly release", due=date.today().isoformat(), repeat="FREQ=WEEKLY")
Bo.patch(B + f"/api/tasks/{T9}", json={"section_id": S2})
rvw(Ca, T9, action="approve")
r = Bo.post(B + f"/api/tasks/{T9}/complete")
t = one(T9)
check(r.ok and r.json().get("next_due") and t["status"] == 0 and not t.get("review") and t.get("reviewer_id") == CAROL, f"repeat: next occurrence without approval {t.get('review')}")
check(Bo.post(B + f"/api/tasks/{T9}/complete").status_code == 409, "repeat: the next tick waits again")

# 2.60.0 (leader, review): a task waiting behind the gate keeps its list (no detour through a list without the gate)
BL = Bo.post(B + "/api/lists", json={"name": "Bob's own"}).json()["id"]
r = Bo.patch(B + f"/api/tasks/{T9}", json={"list_id": BL})
check(not r.ok and one(T9)["list_id"] == P, f"moving a gated task to another list is refused ({r.status_code})")

# ---------------------------------------------------------------- gate off: completing is free again
check(Bo.put(B + f"/api/lists/{P}/review", json={"on": True, "reviewer": CAROL, "gate": False}).ok, "gate off")
check(Bo.post(B + f"/api/tasks/{T5}/complete").ok, "without the gate a waiting task completes")
check(q("SELECT review FROM tasks WHERE id=?", (T5,))[0][0] == "pending", "the review state stays as it was")

# 2.82.0 (#1880): the history names the reviewer (the timeline's users carry them), not "Deleted user"
tl = Bo.get(B + f"/api/tasks/{T3}/timeline").json()
rv = [a["data"].get("reviewer") for a in tl.get("activity", []) if a.get("kind") == "review" and a["data"].get("reviewer")]
check(CAROL in rv and tl["users"].get(str(CAROL)), f"#1880: the reviewer's name is in the timeline {rv} {sorted(tl.get('users', {}))}")

print(f"{OKS[0]} checks ok, {len(FAILS)} failed")
if FAILS:
    sys.exit(1)
print("ALL P260 C API CHECKS PASSED")
