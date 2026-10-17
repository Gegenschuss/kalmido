#!/usr/bin/env python3
"""2.67.0 API tests, part B (#1865): the dependency chain moves along. Invented names only.
 - a later due date moves every waiting task by the same days, down the whole chain (A->B->C: gaps kept), branches
   (A->B, A->D), a diamond (D once), a cycle put into the database by hand ends; earlier = nothing moves
 - stay put (and the chain behind them): completed, milestone, no date, no write access -> chain.skipped (a task the
   person cannot see: no id / title); a recurring waiting task moves this occurrence only
 - the TRIGGERING task's list setting counts; on by default in a new project list, off in a plain list; shift_chain false
 - undo = one batch patch_each back (no new chain movement); "Pull the chain in" (dry, gap > 0, gap <= 0, no date)
 - v1 with an agent token: chain in the answer, only shared lists move (a list outside its list limit = skipped, hidden),
   shift_chain false / invalid; offline replay with _prev moves the chain, a queued title change of a moved task is no conflict
usage: p267_b_api_test.py <datadir>      (a fresh container; P267B_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys
from datetime import timedelta

import requests

import dbx
import testclock

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
D = lambda n: (testclock.today() + timedelta(days=n)).isoformat()  # noqa: E731


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


def db():
    c = dbx.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c.row_factory = dbx.Row
    return c


if not os.environ.get("P267B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en"})


def lst(s, name, **kw):
    r = s.post(B + "/api/lists", json={"name": name, **kw})
    assert r.ok, r.text
    return r.json()


def mk(s, lid, title, due=None, start=None, **kw):
    r = s.post(B + "/api/tasks", json={"list_id": lid, "title": title, **({"due": due} if due else {}), **({"start": start} if start else {}), **kw})
    assert r.ok, r.text
    return r.json()["id"]


def dep(s, w, bl):
    r = s.post(B + "/api/deps", json={"task_id": w, "blocker_id": bl})
    assert r.ok, r.text


def row(tid):
    with db() as c:
        return dict(c.execute("SELECT id, title, start, due, status, repeat FROM tasks WHERE id=?", (tid,)).fetchone())


def patch(s, tid, **b):
    r = s.patch(B + f"/api/tasks/{tid}", json=b)
    assert r.ok, r.text
    return r.json()


# ================================================================== the list setting
P = lst(A, "Launch plan", kind="project")
PL = lst(A, "Errands")
check(P["dep_shift"] == 1, f"a new project list: Move dependent tasks along on by default ({P['dep_shift']})")
check(PL["dep_shift"] == 0, "a plain list: off by default")
check(lst(A, "Quiet project", kind="project", dep_shift=False)["dep_shift"] == 0, "an explicit dep_shift false at creation is kept")
for nm, kd in (("Tpl project", "project"), ("Tpl plain", "list")):
    tp = A.post(B + "/api/templates", json={"kind": "list", "data": {"name": nm, "kind": kd}})
    assert tp.ok, tp.text
    ap = A.post(B + f"/api/templates/{tp.json()['id']}/apply", json={"name": nm + " list"})
    assert ap.ok, ap.text
with db() as cx:
    tl = {r_["name"]: r_["dep_shift"] for r_ in cx.execute("SELECT name, dep_shift FROM lists WHERE name LIKE 'Tpl %'")}
check(tl == {"Tpl project list": 1, "Tpl plain list": 0}, f"a list template without the setting: on for a project, off for a plain list: {tl}")
P, PL = P["id"], PL["id"]

# ================================================================== chain A -> B -> C, gaps kept
a = mk(A, P, "Concept", D(1))
b = mk(A, P, "Script", D(4), D(2))
c = mk(A, P, "Shoot", D(9), D(8))
dep(A, b, a)
dep(A, c, b)
r = patch(A, a, due=D(4))
ch = r["chain"]
check(ch["days"] == 3 and [m["id"] for m in ch["moved"]] == [b, c], f"chain: B and C move: {ch}")
check(row(b)["start"] == D(5) and row(b)["due"] == D(7) and row(c)["start"] == D(11) and row(c)["due"] == D(12),
      f"chain: everything +3, gaps and durations kept: {row(b)} {row(c)}")
m0 = ch["moved"][0]
check(m0["old_start"] == D(2) and m0["old_due"] == D(4) and m0["start"] == D(5) and m0["due"] == D(7) and m0["title"] == "Script", f"chain: moved entry {m0}")
check({x["id"] for x in r["shifted"]} == {b, c}, "the older answer field shifted stays for older clients")
with db() as cx:
    check(cx.execute("SELECT COUNT(*) FROM activity WHERE task_id IN (?,?) AND kind='dep_shift'", (b, c)).fetchone()[0] == 2, "each moved task: history line")
r = patch(A, a, due=D(2))
check(r["shifted"] == [] and r["chain"]["moved"] == [] and row(b)["due"] == D(7), "earlier: nothing slides back")
r = patch(A, a, title="Concept v2")
check(r["chain"] == {"moved": [], "skipped": [], "days": 0}, f"no date change: empty chain {r['chain']}")

# ================================================================== branches + diamond + cycle
h = mk(A, P, "Hub", D(1))
x1 = mk(A, P, "Branch one", D(3))
x2 = mk(A, P, "Branch two", D(5), D(4))
dep(A, x1, h)
dep(A, x2, h)
r = patch(A, h, due=D(3))
check(sorted(m["id"] for m in r["chain"]["moved"]) == sorted([x1, x2]) and row(x1)["due"] == D(5) and row(x2)["start"] == D(6),
      f"branches A->B, A->D both move: {r['chain']}")
da = mk(A, P, "Diamond top", D(1))
db_ = mk(A, P, "Diamond left", D(2))
dc = mk(A, P, "Diamond right", D(3))
dd = mk(A, P, "Diamond bottom", D(6), D(5))
for w, bl in ((db_, da), (dc, da), (dd, db_), (dd, dc)):
    dep(A, w, bl)
r = patch(A, da, due=D(3))
check([m["id"] for m in r["chain"]["moved"]].count(dd) == 1 and row(dd)["due"] == D(8) and row(dd)["start"] == D(7),
      f"diamond: the bottom moves once by the delta (not twice): {row(dd)}")
y1 = mk(A, P, "Loop one", D(1))
y2 = mk(A, P, "Loop two", D(2))
dep(A, y2, y1)
with db() as cx:  # a cycle the API refuses, put in by hand
    cx.execute("INSERT INTO task_deps(task_id,blocker_id,created_by,created_at) VALUES(?,?,1,?)", (y1, y2, "2026-01-01T00:00:00.000Z"))
    cx.commit()
r = A.patch(B + f"/api/tasks/{y1}", json={"due": D(4)})
check(r.ok and [m["id"] for m in r.json()["chain"]["moved"]] == [y2] and row(y1)["due"] == D(4) and row(y2)["due"] == D(5),
      f"a cycle in the database ends (each task once): {r.text[:300]}")

# ================================================================== stay put
s1 = mk(A, P, "Start", D(1))
w_done = mk(A, P, "Already done", D(2))
w_ms = mk(A, P, "Gate review", D(3), ms=1)
w_nod = mk(A, P, "Someday")
w_rep = mk(A, P, "Weekly sync", D(2), repeat="FREQ=WEEKLY")
behind_ms = mk(A, P, "After the gate", D(5))
behind_nod = mk(A, P, "After someday", D(6))
for w in (w_done, w_ms, w_nod, w_rep):
    dep(A, w, s1)
dep(A, behind_ms, w_ms)
dep(A, behind_nod, w_nod)
A.post(B + f"/api/tasks/{w_done}/complete")
rep0 = row(w_rep)["repeat"]
r = patch(A, s1, due=D(3))
sk = {x["id"]: x["reason"] for x in r["chain"]["skipped"]}
check(sk == {w_done: "done", w_ms: "milestone", w_nod: "no_date"}, f"stay put with reasons: {r['chain']['skipped']}")
check(row(w_ms)["due"] == D(3) and row(behind_ms)["due"] == D(5) and row(behind_nod)["due"] == D(6) and row(w_done)["due"] == D(2),
      "milestone, no date, completed: they and the chain behind them stay")
check([m["id"] for m in r["chain"]["moved"]] == [w_rep] and row(w_rep)["due"] == D(4) and row(w_rep)["repeat"] == rep0,
      f"a recurring waiting task: this occurrence moves, the rule stays: {row(w_rep)}")

# ================================================================== rights: view only, invisible
BV = lst(Bo, "Bob's crew plan", kind="project")["id"]
Bo.put(B + f"/api/lists/{BV}/members", json={"user_id": 1, "role": "view"})
A.put(B + f"/api/lists/{P}/members", json={"user_id": BOB, "role": "edit"})
BH = lst(Bo, "Bob alone", kind="project")["id"]
s2 = mk(A, P, "Alice books", D(1))
bv = mk(Bo, BV, "Bob rigs", D(3), D(2))
bh = mk(Bo, BH, "Bob private step", D(3), D(2))
behind_bv = mk(A, P, "Alice after Bob", D(5))
dep(Bo, bv, s2)
dep(Bo, bh, s2)
dep(A, behind_bv, bv)
bhd = mk(Bo, BH, "Bob finished step", D(3))
dep(Bo, bhd, s2)
Bo.post(B + f"/api/tasks/{bhd}/complete")
r = patch(A, s2, due=D(2))
sk = r["chain"]["skipped"]
vis = [x for x in sk if not x["hidden"]]
hid = [x for x in sk if x["hidden"]]
check(vis == [{"id": bv, "title": "Bob rigs", "reason": "no_access", "hidden": False}], f"view only: skipped with its title: {sk}")
check(hid == [{"id": None, "title": None, "reason": "no_access", "hidden": True}] * 2 and "Bob private step" not in str(r) and "Bob finished" not in str(r),
      f"invisible: skipped without id / title / state (also a completed one says no_access): {sk}")
check(row(bv)["due"] == D(3) and row(bh)["due"] == D(3) and row(behind_bv)["due"] == D(5), "no write access: they and the chain behind stay")

# ================================================================== the triggering list decides, shift_chain false
Q = lst(A, "Quiet", kind="project", dep_shift=False)["id"]
q1 = mk(A, Q, "Quiet first", D(1))
qw = mk(A, P, "Loud follows", D(2))
dep(A, qw, q1)
r = patch(A, q1, due=D(3))
check(r["chain"]["moved"] == [] and row(qw)["due"] == D(2), "trigger in a list with the setting off: nothing moves (even into a list with it on)")
pw = mk(A, Q, "Quiet follows loud", D(4))
dep(A, pw, a)
r = patch(A, a, due=D(3))
check(pw in [m["id"] for m in r["chain"]["moved"]] and row(pw)["due"] == D(5), "trigger in a list with it on: a waiting task in a list with it off moves")
r = patch(A, a, due=D(6), shift_chain=False)
check(r["chain"]["moved"] == [] and row(b)["due"] == D(8) and row(pw)["due"] == D(5), f"shift_chain false: nothing moves ({row(b)})")
r = A.patch(B + f"/api/tasks/{a}", json={"due": D(6), "shift_chain": False})
check(not r.headers.get("X-Kalmido-Unknown-Fields"), "shift_chain is a known field of the web PATCH")

# ================================================================== undo: one batch back, no new movement
u1 = mk(A, P, "Undo root", D(1))
u2 = mk(A, P, "Undo next", D(3), D(2))
u3 = mk(A, P, "Undo last", D(5), D(4))
dep(A, u2, u1)
dep(A, u3, u2)
r = patch(A, u1, due=D(3))
items = {str(u1): {"due": D(1), "_prev": {"due": D(3)}}}
for m in r["chain"]["moved"]:
    items[str(m["id"])] = {"start": m["old_start"], "due": m["old_due"], "_prev": {"start": m["start"], "due": m["due"]}}
u = A.post(B + "/api/tasks/batch", json={"ids": [int(k) for k in items], "action": "patch_each", "data": {"items": items}})
check(u.ok and row(u1)["due"] == D(1) and row(u2)["due"] == D(3) and row(u2)["start"] == D(2) and row(u3)["due"] == D(5),
      f"undo: one batch puts the whole chain back ({u.status_code})")
items = {str(u1): {"due": D(3), "_prev": {"due": D(1)}}, str(u2): {"start": D(4), "due": D(5), "_prev": {"start": D(2), "due": D(3)}},
         str(u3): {"start": D(6), "due": D(7), "_prev": {"start": D(4), "due": D(5)}}}
u = A.post(B + "/api/tasks/batch", json={"ids": [u1, u2, u3], "action": "patch_each", "data": {"items": items}})
check(u.ok and row(u2)["due"] == D(5) and row(u3)["due"] == D(7), "redo: the same batch forward, the chain is not moved a second time")

# ================================================================== Pull the chain in
p1 = mk(A, P, "Pull root", D(1))
p2 = mk(A, P, "Pull next", D(6), D(5))
p3 = mk(A, P, "Pull last", D(9), D(8))
dep(A, p2, p1)
dep(A, p3, p2)
r = A.post(B + f"/api/tasks/{p1}/chain/pull", json={"dry": True})
j = r.json()
check(r.ok and j["gap"] == 3 and j["dry"] and [m["id"] for m in j["chain"]["moved"]] == [p2, p3] and j["chain"]["days"] == -3 and row(p2)["due"] == D(6),
      f"pull dry: the plan (gap 3), nothing written: {r.text[:300]}")
r = A.post(B + f"/api/tasks/{p1}/chain/pull", json={})
j = r.json()
check(r.ok and row(p2)["start"] == D(2) and row(p2)["due"] == D(3) and row(p3)["start"] == D(5) and row(p3)["due"] == D(6)
      and {m["id"] for m in j["shifted"]} == {p2, p3}, f"pull: the chain moves 3 days earlier, gaps kept: {row(p2)} {row(p3)}")
r = A.post(B + f"/api/tasks/{p1}/chain/pull", json={})
check(r.ok and r.json()["gap"] == 0 and r.json()["shifted"] == [] and row(p2)["start"] == D(2), "pull again: nothing to do (gap 0)")
check(A.post(B + f"/api/tasks/{w_nod}/chain/pull", json={}).status_code == 400, "pull on a task without a date: 400")
check(Bo.post(B + f"/api/tasks/{bh}/chain/pull", json={}).ok and A.post(B + f"/api/tasks/{bh}/chain/pull", json={}).status_code == 404,
      "pull on a task I cannot see: 404")
check(A.post(B + f"/api/tasks/{mk(A, PL, 'Plain', D(1))}/chain/pull", json={}).status_code == 409, "pull in a plain list: 409 (dependencies are for projects)")

# ================================================================== v1 + agent token with a list limit
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "planner", "display_name": "Planner"})
assert r.ok, r.text
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
G = lst(A, "Shared with the agent", kind="project")["id"]
G2 = lst(A, "Also shared, outside the limit", kind="project")["id"]
for lid in (G, G2):
    check(A.put(B + f"/api/lists/{lid}/members", json={"user_id": AG, "role": "edit"}).ok, f"agent edits list {lid}")
g1 = mk(A, G, "Agent root", D(1))
g2 = mk(A, G, "Agent next", D(2))
g3 = mk(A, P, "Not shared with the agent", D(3))
g4 = mk(A, G2, "Outside the limit", D(3))
for w in (g2, g3, g4):
    dep(A, w, g1)
A.patch(B + f"/api/admin/agents/{AG}", json={"list_ids": [G]})
r = requests.patch(V + f"/tasks/{g1}", headers=AGH, json={"due": D(2)})
j = r.json()
check(r.ok and [m["id"] for m in j["chain"]["moved"]] == [g2] and row(g2)["due"] == D(3), f"v1 agent: the shared waiting task moves: {r.text[:300]}")
check(len(j["chain"]["skipped"]) == 2 and all(x["hidden"] and x["id"] is None for x in j["chain"]["skipped"])
      and "Not shared" not in r.text and "Outside the limit" not in r.text and row(g3)["due"] == D(3) and row(g4)["due"] == D(3),
      f"v1 agent: a list not shared and one outside the limit stay, without titles: {j['chain']['skipped']}")
r = requests.patch(V + f"/tasks/{g1}", headers=AGH, json={"due": D(4), "shift_chain": False})
check(r.ok and "chain" not in r.json() and row(g2)["due"] == D(3), "v1: shift_chain false: nothing moves, no chain field")
r = requests.patch(V + f"/tasks/{g1}", headers=AGH, json={"due": D(5), "shift_chain": "no"})
check(r.status_code == 400 and row(g1)["due"] == D(4), f"v1: shift_chain must be a boolean ({r.status_code})")
r = requests.patch(V + f"/tasks/{g1}", headers=AGH, json={"shift_chain": True})
check(r.status_code == 400, "v1: shift_chain alone is nothing to change")
spec = requests.get(V + "/openapi.json", headers=AGH).json()
sch = spec["components"]["schemas"]
check("shift_chain" in sch["TaskUpdate"]["properties"] and "Chain" in sch, "OpenAPI: TaskUpdate.shift_chain + Chain")
check("/tasks/{id}/chain/pull" not in str(spec["paths"].keys()), "the pull button is the app's (no v1 route)")
check(requests.post(B + f"/api/tasks/{g1}/chain/pull", headers=AGH, json={}).status_code in (401, 403, 404), "an agent token cannot use the web pull route")

# ================================================================== offline replay with _prev
o1 = mk(A, P, "Offline root", D(1))
o2 = mk(A, P, "Offline next", D(3))
dep(A, o2, o1)
r = patch(A, o1, due=D(2), _prev={"due": D(1)})
check([m["id"] for m in r["chain"]["moved"]] == [o2] and row(o2)["due"] == D(4), "offline replay (_prev): the server moves the chain")
r = patch(A, o2, title="Offline next (renamed)", _prev={"title": "Offline next"})
check(r["conflicts"] == [] and row(o2)["title"] == "Offline next (renamed)" and row(o2)["due"] == D(4),
      "a queued title change of a moved task: no conflict, its new date stays")
r = patch(A, o2, due=D(10), _prev={"due": D(3)})
check([x["field"] for x in r["conflicts"]] == ["due"] and row(o2)["due"] == D(4), "a queued date change of a moved task: reported as a conflict (moved meanwhile)")

print(f"p267_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
