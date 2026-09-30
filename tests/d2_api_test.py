#!/usr/bin/env python3
"""Package D2 API tests (fresh DB on the TEST container :3048): the setup presets (modules of new users, instance
switches), the modules "deps" / "fields" (per user, no unblock News / push when off, the API keeps working, /api/v1/me),
GET /api/deps (edges between visible tasks, completed blockers), "Move dependent tasks along" (list setting: owner only,
cascade by the same delta, only conflicting tasks, only when postponed, lists with the setting, edit rights, depth and
size caps, activity line, the reverse PATCHes of the client's undo, the reorder endpoint), then the migration of
existing users (features_rev 8, and 9 = "comments" since 2.0.6) after a restart of the container on the same data."""
import json, os, sqlite3, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone
import requests

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1]
N = os.path.dirname(os.path.abspath(__file__))
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


def db():
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c.row_factory = sqlite3.Row
    return c


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def state(s):
    return s.get(B + "/api/state").json()


def task(s, tid):
    return next((t for t in state(s)["tasks"] if t["id"] == tid), None)


def feats(s):
    return state(s)["settings"]["features"].split(",")


D = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731

# ---- setup presets: the client sends the modules of the chosen card; new users follow them
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
SIMPLE = ["cal"]
r = A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": False, "time_all": False, "modules": SIMPLE})
check(r.ok, f"setup 'Simple list': {r.status_code} {r.text[:200]}")
with db() as c:
    dflt = c.execute("SELECT value FROM settings WHERE key='default_features'").fetchone()[0].split(",")
check(set(dflt) == {"cal", "collab", "time"}, f"Simple list: default modules = calendar (+ the instance-switched collab / time): {dflt}")
check(set(feats(A)) == {"cal", "collab", "time"}, "Simple list: the admin gets them too")
ab = A.get(B + "/api/about").json()
check(ab.get("collab_all") is False and ab.get("time_all") is False, f"Simple list: collaboration + time tracking off for the server: {ab.get('collab_all')} {ab.get('time_all')}")
SOLO = ["cal", "timeline", "matrix", "kanban", "habits", "pomo", "stats", "progress"]
A.post(B + "/api/admin/setup", json={"collab_all": False, "time_all": False, "modules": SOLO})
check("deps" not in feats(A) and "fields" not in feats(A) and "timeline" in feats(A), "Just me: timeline on, dependencies + custom fields off")
TEAM = SOLO + ["deps", "fields", "paperless"]
A.post(B + "/api/admin/setup", json={"collab_all": True, "time_all": True, "modules": TEAM})
check({"deps", "fields", "progress", "timeline", "collab", "time"} <= set(feats(A)), "Projects & team: everything on")
ab = A.get(B + "/api/about").json()
check(ab.get("collab_all") is True and ab.get("time_all") is True, "Projects & team: collaboration + time tracking on for the server")
ids = {}
for u, n in (("bob", "Bob"), ("carol", "Carol")):
    ids[u] = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "ntfy_topic": "t-" + u}).json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
Bb, C = sess("bob"), sess("carol")
check({"deps", "fields"} <= set(feats(Bb)), "a new user follows the chosen default (deps + fields on)")
check(state(Bb)["settings"]["features_rev"] == "9", "new user: features_rev 9 (2.0.6: comments)")

# ---- per-user module switch: the API keeps working, no unblock News / push when "deps" is off
W = A.post(B + "/api/lists", json={"name": "Work", "kind": "project"}).json()["id"]
A.put(B + f"/api/lists/{W}/members", json={"user_id": BOB, "role": "edit"})
mk = lambda s, **kw: s.post(B + "/api/tasks", json={"list_id": W, **kw}).json()["id"]  # noqa: E731
t1, b1 = mk(A, title="Ship", assignee_id=BOB), mk(A, title="Build")
Bb.patch(B + "/api/settings", json={"features": ",".join(f for f in feats(Bb) if f != "deps")})
check("deps" not in feats(Bb), "bob switched dependencies off")
r = Bb.post(B + "/api/deps", json={"task_id": t1, "blocker_id": b1})
check(r.ok and r.json()["task"]["blocked"] == 1, "module off: the API still links tasks (data and API stay)")
check(Bb.get(B + f"/api/tasks/{t1}/deps").ok, "module off: GET deps still works")
time.sleep(3.2)
open(os.path.join(DATA, "ntfy.log"), "w").close()
A.post(B + f"/api/tasks/{b1}/complete")
time.sleep(0.6)
check(not [p for p in pushes() if p["topic"] == "t-bob"], "deps off at the recipient: no unblock push")
with db() as c:
    check(not c.execute("SELECT 1 FROM notifications WHERE kind='unblock' AND task_id=?", (t1,)).fetchone(), "... and no News row")
    check(c.execute("SELECT 1 FROM activity WHERE kind='unblocked' AND task_id=?", (t1,)).fetchone(), "... the activity line stays")
Bb.patch(B + "/api/settings", json={"features": ",".join(feats(Bb) + ["deps"])})
t2, b2 = mk(A, title="Invoice", assignee_id=BOB), mk(A, title="Hours")
Bb.post(B + "/api/deps", json={"task_id": t2, "blocker_id": b2})
time.sleep(3.2)
open(os.path.join(DATA, "ntfy.log"), "w").close()
A.post(B + f"/api/tasks/{b2}/complete")
time.sleep(0.6)
check(len([p for p in pushes() if p["topic"] == "t-bob"]) == 1, "deps on again: unblock push")
Bb.patch(B + "/api/settings", json={"features": ",".join(f for f in feats(Bb) if f != "fields")})
f1 = A.post(B + f"/api/lists/{W}/fields", json={"name": "Budget", "type": "number"})
check(f1.ok, f"fields: owner creates a field: {f1.status_code}")
fid = f1.json()["id"] if f1.ok else 0
r = Bb.patch(B + f"/api/tasks/{t2}", json={"fields": {str(fid): "12"}})
check(r.ok and r.json()["fields"].get(str(fid)) in ("12", "12.0"), f"module fields off: values still readable / writable via the API: {r.text[:120]}")
# API token: /api/v1/me reports the modules
tok = Bb.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read"]}).json().get("token")
me = requests.get(B + "/api/v1/me", headers={"Authorization": "Bearer " + (tok or "")}).json()
check(me.get("features", {}).get("dependencies") is True and me["features"].get("custom_fields") is False, f"/api/v1/me: dependencies / custom_fields: {me.get('features')}")
Bb.patch(B + "/api/settings", json={"features": ",".join(feats(Bb) + ["fields"])})

# ---- GET /api/deps: every dependency between visible tasks of open waiting tasks, completed blockers listed
P = C.post(B + "/api/lists", json={"name": "Carol private", "kind": "project"}).json()["id"]
hid = C.post(B + "/api/tasks", json={"list_id": P, "title": "Secret"}).json()["id"]
t3, b3, b4 = mk(A, title="Launch"), mk(A, title="Copy"), mk(A, title="Visuals")
A.post(B + "/api/deps", json={"task_id": t3, "blocker_id": b3})
A.post(B + "/api/deps", json={"task_id": t3, "blocker_id": b4})
A.post(B + f"/api/tasks/{b4}/complete")
C.put(B + f"/api/lists/{P}/members", json={"user_id": 1, "role": "view"})  # alice sees Carol's list for the dependency ...
A.post(B + "/api/deps", json={"task_id": t3, "blocker_id": hid})
C.delete(B + f"/api/lists/{P}/members/1")                                   # ... and loses access again
j = A.get(B + "/api/deps").json()
E = {tuple(e) for e in j["edges"]}
check((t3, b3) in E and (t3, b4) in E, f"GET /api/deps: open + completed blockers: {E}")
check((t3, hid) not in E and all(hid not in e for e in E), "GET /api/deps: a blocker I cannot see is left out")
cl = {x["id"]: x for x in j["closed"]}
check(b4 in cl and cl[b4]["status"] == 2 and cl[b4]["title"] == "Visuals" and b3 not in cl, "GET /api/deps: completed blockers as rows (title, status)")
check((t1, b1) not in E or task(A, t1)["status"] == 0, "GET /api/deps: only open waiting tasks")
jb = Bb.get(B + "/api/deps").json()
check((t3, b3) in {tuple(e) for e in jb["edges"]}, "GET /api/deps: a member sees the list's dependencies")
check(C.get(B + "/api/deps").json()["edges"] == [] or all(t3 not in e for e in C.get(B + "/api/deps").json()["edges"]), "GET /api/deps: nothing of lists I cannot see (IDOR)")

# ---- list types: list | checklist | project; project-only features refused elsewhere (409), checklist compat
PL = A.post(B + "/api/lists", json={"name": "Plain"}).json()["id"]
lst = lambda s, i: next(l for l in state(s)["lists"] if l["id"] == i)  # noqa: E731
check(lst(A, PL)["kind"] == "list" and lst(A, W)["kind"] == "project", "new list: type list by default; kind project on request")
pt = A.post(B + "/api/tasks", json={"list_id": PL, "title": "Plain task"}).json()["id"]
r = A.post(B + "/api/time/start", json={"task_id": pt})
check(r.status_code == 409 and "project" in r.json().get("error", ""), f"plain list: timer refused with a clear message: {r.status_code} {r.text[:120]}")
r = A.post(B + "/api/time/entries", json={"list_id": PL, "start": D(-1) + "T09:00", "minutes": 30})
check(r.status_code == 409, f"plain list: time entry refused: {r.status_code}")
r = A.post(B + "/api/deps", json={"task_id": pt, "blocker_id": t3})
check(r.status_code == 409 and "projects" in r.json().get("error", ""), f"dependency needs both lists to be projects: {r.text[:120]}")
r = A.post(B + "/api/deps", json={"task_id": t3, "blocker_id": pt})
check(r.status_code == 409, "... also the other way round")
check(A.post(B + f"/api/lists/{PL}/fields", json={"name": "X", "type": "text"}).status_code == 409, "plain list: no custom fields")
check(A.patch(B + f"/api/tasks/{pt}", json={"fields": {str(fid): "3"}}).status_code == 409, "plain list: no field values")
check(A.post(B + f"/api/lists/{PL}/status", json={"status": "on_track"}).status_code == 409, "plain list: no project status")
check(A.post(B + "/api/tasks", json={"list_id": PL, "title": "x", "fields": {str(fid): "1"}}).status_code == 409, "plain list: no field values on create")
CKL = A.post(B + "/api/lists", json={"name": "Shopping", "checklist": True}).json()["id"]
check(lst(A, CKL)["kind"] == "checklist" and lst(A, CKL)["checklist"] == 1, "compat: checklist=true creates a checklist")
A.patch(B + f"/api/lists/{CKL}", json={"checklist": False})
check(lst(A, CKL)["kind"] == "list" and lst(A, CKL)["checklist"] == 0, "compat: checklist=false -> plain list")
A.patch(B + f"/api/lists/{CKL}", json={"kind": "checklist"})
check(lst(A, CKL)["checklist"] == 1, "kind checklist sets the checklist flag")
A.patch(B + f"/api/lists/{CKL}", json={"kind": "project"})
check(lst(A, CKL)["checklist"] == 0 and lst(A, CKL)["kind"] == "project", "kind project clears it")
check(A.patch(B + f"/api/lists/{CKL}", json={"kind": "board"}).status_code == 400, "unknown kind refused")
check(Bb.patch(B + f"/api/lists/{W}", json={"kind": "list"}).status_code == 403, "only the owner changes the type")
tok2 = A.post(B + "/api/me/tokens", json={"name": "k", "scopes": ["read", "write"]}).json()["token"]
VH = {"Authorization": "Bearer " + tok2}
vl = requests.get(B + "/api/v1/lists", headers=VH).json()["data"]
check(next(x for x in vl if x["id"] == W)["kind"] == "project" and next(x for x in vl if x["id"] == PL)["checklist"] is False, "API v1: lists carry kind + checklist")
r = requests.post(B + "/api/v1/lists", headers=VH, json={"name": "API project", "kind": "project"})
check(r.status_code == 201 and r.json()["kind"] == "project", f"API v1: create with kind: {r.text[:120]}")
r = requests.post(B + "/api/v1/lists", headers=VH, json={"name": "API check", "checklist": True})
check(r.status_code == 201 and r.json()["kind"] == "checklist" and r.json()["checklist"] is True, "API v1: checklist=true still works")
# switching a project back to a list hides its time and dependencies (nothing deleted), and back again
TP = A.post(B + "/api/lists", json={"name": "Client X", "kind": "project"}).json()["id"]
tp1, tp2 = A.post(B + "/api/tasks", json={"list_id": TP, "title": "Brief"}).json()["id"], A.post(B + "/api/tasks", json={"list_id": TP, "title": "Pitch"}).json()["id"]
A.post(B + "/api/time/entries", json={"task_id": tp1, "start": D(-1) + "T09:00", "minutes": 90})
A.post(B + "/api/deps", json={"task_id": tp2, "blocker_id": tp1})
rep_ = lambda: A.get(B + "/api/time/report", params={"from": D(-3), "to": D(0)}).json()["total"]["seconds"]  # noqa: E731
s0 = rep_()
check(s0 >= 5400 and task(A, tp2)["blocked"] == 1, "project: time in the report, the task waits")
A.patch(B + f"/api/lists/{TP}", json={"kind": "list"})
check(rep_() == s0 - 5400 and task(A, tp2)["blocked"] == 0, "back to a list: its time left out of reports, no waiting")
with db() as c:
    check(c.execute("SELECT COUNT(*) FROM time_entries WHERE task_id=?", (tp1,)).fetchone()[0] == 1 and c.execute("SELECT COUNT(*) FROM task_deps WHERE task_id=?", (tp2,)).fetchone()[0] == 1, "... nothing deleted")
A.patch(B + f"/api/lists/{TP}", json={"kind": "project"})
check(rep_() == s0 and task(A, tp2)["blocked"] == 1, "project again: everything back")

# ---- focus sessions past their planned end are finished on the server (watchdog), at the planned end
ft = A.post(B + "/api/tasks", json={"list_id": TP, "title": "Deep work"}).json()["id"]
A.post(B + "/api/pomo/start", json={"kind": "focus", "minutes": 1, "task_id": ft})
with db() as c:
    pid = c.execute("SELECT id FROM pomos WHERE end IS NULL AND user_id=1").fetchone()[0]
    st0 = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(microsecond=0)
    c.execute("UPDATE pomos SET start=? WHERE id=?", (st0.isoformat(), pid))
    c.commit()
ok_ = False
for _ in range(40):
    time.sleep(0.25)
    with db() as c:
        r2 = c.execute("SELECT * FROM pomos WHERE id=?", (pid,)).fetchone()
    if r2["end"]:
        ok_ = True
        break
check(ok_ and r2["done"] == 1 and r2["end"].startswith((st0 + timedelta(minutes=1)).isoformat()[:19]), f"stale focus session closed at its planned end: {dict(r2) if r2 else None}")
with db() as c:
    check(c.execute("SELECT seconds FROM time_entries WHERE pomo_id=? AND source='focus'", (pid,)).fetchone()[0] == 60, "... and became a time entry (time_focus on, project list)")
check(state(A)["pomo"] is None, "... so nothing looks like it is still running")
A.post(B + "/api/pomo/start", json={"kind": "focus", "minutes": 25})
with db() as c:
    pid2 = c.execute("SELECT id FROM pomos WHERE end IS NULL AND user_id=1").fetchone()[0]
    c.execute("UPDATE pomos SET start=?, notified=1 WHERE id=?", ((datetime.now(timezone.utc) - timedelta(hours=10)).replace(microsecond=0).isoformat(), pid2))
    c.commit()
A.post(B + f"/api/pomo/{pid2}/finish")
with db() as c:
    r3 = c.execute("SELECT start, end FROM pomos WHERE id=?", (pid2,)).fetchone()
check((datetime.fromisoformat(r3["end"]) - datetime.fromisoformat(r3["start"])).total_seconds() <= 25 * 60 + 1, "a late finish ends at the planned end, not hours later")

# ---- "Move dependent tasks along" (list setting dep_shift)
r = Bb.patch(B + f"/api/lists/{W}", json={"dep_shift": True})
check(r.status_code == 403, f"dep_shift: only the owner sets it (member: {r.status_code})")
r = A.patch(B + f"/api/lists/{W}", json={"dep_shift": True})
check(r.ok and next(l for l in state(A)["lists"] if l["id"] == W)["dep_shift"] == 1, "dep_shift: owner turns it on")
ta = mk(A, title="Design", due=D(2))
tb = mk(A, title="Build it", start=D(3), due=D(5))
tc = mk(A, title="Test late", start=D(9), due=D(10))
td = mk(A, title="Review", due=D(7))
te = mk(A, title="Done already", start=D(3), due=D(4))
tf = mk(A, title="Trashed", start=D(3), due=D(4))
for w, bl in ((tb, ta), (tc, tb), (td, tb), (te, ta), (tf, ta)):
    A.post(B + "/api/deps", json={"task_id": w, "blocker_id": bl})
A.post(B + f"/api/tasks/{te}/complete")
A.delete(B + f"/api/tasks/{tf}")
r = A.patch(B + f"/api/tasks/{ta}", json={"due": D(5)}).json()
sh = {x["id"]: x for x in r.get("shifted", [])}
check(set(sh) == {tb, td}, f"cascade: B (conflict) and D (conflict after B moved) move, C (starts after B) not: {list(sh)}")
check(tb in sh and sh[tb]["start"] == D(6) and sh[tb]["due"] == D(8) and sh[tb]["prev_start"] == D(3) and sh[tb]["prev_due"] == D(5), f"cascade: same delta, duration kept: {sh.get(tb)}")
check(td in sh and sh[td]["due"] == D(10) and sh[td]["start"] is None, f"cascade: second level by the same delta: {sh.get(td)}")
check(task(A, tc)["due"] == D(10) and task(A, tc)["start"] == D(9), "cascade: a task that still starts after its blocker stays")
with db() as c:
    check(c.execute("SELECT due FROM tasks WHERE id=?", (te,)).fetchone()[0] == D(4) and c.execute("SELECT due FROM tasks WHERE id=?", (tf,)).fetchone()[0] == D(4),
          "cascade: completed and trashed tasks stay")
    check(c.execute("SELECT 1 FROM activity WHERE task_id=? AND kind='dep_shift'", (tb,)).fetchone(), "cascade: activity line dep_shift on the moved task")
    check(c.execute("SELECT reminded FROM tasks WHERE id=?", (tb,)).fetchone()[0] == "[]", "cascade: reminder re-armed")
# the client's single undo: reverse PATCH of the root, then of every moved task with _prev
A.patch(B + f"/api/tasks/{ta}", json={"due": D(2), "_prev": {"due": D(5)}})
for x in r["shifted"]:
    A.patch(B + f"/api/tasks/{x['id']}", json={"start": x["prev_start"], "due": x["prev_due"], "_prev": {"start": x["start"], "due": x["due"]}})
check(task(A, tb)["start"] == D(3) and task(A, tb)["due"] == D(5) and task(A, td)["due"] == D(7) and task(A, ta)["due"] == D(2), "undo: the whole chain is back")
r = A.patch(B + f"/api/tasks/{ta}", json={"due": D(1)}).json()
check(r.get("shifted") == [] and task(A, tb)["start"] == D(3), "moving a task earlier moves nothing")
r = A.patch(B + f"/api/tasks/{ta}", json={"title": "Design v2"}).json()
check(r.get("shifted") == [], "no date change: nothing moves")
# reorder (drag onto a day in the calendar / list) cascades too
r = A.post(B + "/api/tasks/reorder", json={"items": [{"id": ta, "due": D(4)}]}).json()
check([x["id"] for x in r.get("shifted", [])] == [tb, td] and task(A, tb)["start"] == D(6), f"reorder: dependent tasks moved along: {r}")
# list without the setting: nothing moves
X = A.post(B + "/api/lists", json={"name": "Other", "kind": "project"}).json()["id"]
xa = A.post(B + "/api/tasks", json={"list_id": X, "title": "X1", "due": D(1)}).json()["id"]
xb = A.post(B + "/api/tasks", json={"list_id": X, "title": "X2", "start": D(2), "due": D(3)}).json()["id"]
A.post(B + "/api/deps", json={"task_id": xb, "blocker_id": xa})
r = A.patch(B + f"/api/tasks/{xa}", json={"due": D(6)}).json()
check(r.get("shifted") == [] and task(A, xb)["start"] == D(2), "list without the setting: nothing moves")
# the waiting task's list decides: a task in W waiting on X's task moves
wx = mk(A, title="Follows X", start=D(7), due=D(8))
A.post(B + "/api/deps", json={"task_id": wx, "blocker_id": xa})
r = A.patch(B + f"/api/tasks/{xa}", json={"due": D(9)}).json()
check([x["id"] for x in r["shifted"]] == [wx], f"the waiting task's list setting counts: {r['shifted']}")
# edit rights: a task in a list I may only view is never moved
V = Bb.post(B + "/api/lists", json={"name": "Bob view", "kind": "project"}).json()["id"]
Bb.patch(B + f"/api/lists/{V}", json={"dep_shift": True})
Bb.put(B + f"/api/lists/{V}/members", json={"user_id": 1, "role": "view"})
vt = Bb.post(B + "/api/tasks", json={"list_id": V, "title": "Bob waits", "start": D(1), "due": D(2)}).json()["id"]
A.put(B + f"/api/lists/{W}/members", json={"user_id": BOB, "role": "edit"})
vb = mk(A, title="Alice first", due=D(1))
check(Bb.post(B + "/api/deps", json={"task_id": vt, "blocker_id": vb}).ok, "bob links his task to alice's")
r = A.patch(B + f"/api/tasks/{vb}", json={"due": D(4)}).json()
check(r.get("shifted") == [] and task(Bb, vt)["due"] == D(2), "no edit rights on the waiting task: not moved")
r = Bb.patch(B + f"/api/tasks/{vb}", json={"due": D(6)}).json()
check([x["id"] for x in r["shifted"]] == [vt], "the same move by bob (owner of the waiting task) moves it")
# caps: depth 10, 50 tasks
chain = [mk(A, title="C0", due=D(1))]
for i in range(1, 13):
    chain.append(mk(A, title=f"C{i}", start=D(i), due=D(i)))
    A.post(B + "/api/deps", json={"task_id": chain[i], "blocker_id": chain[i - 1]})
r = A.patch(B + f"/api/tasks/{chain[0]}", json={"due": D(3)}).json()
check(len(r["shifted"]) == 10 and task(A, chain[11])["due"] == D(11), f"cascade depth capped at 10 levels: {len(r['shifted'])}")
root = mk(A, title="Hub", due=D(1))
fan = [mk(A, title=f"F{i}", due=D(1)) for i in range(55)]
with db() as c:  # 55 dependencies at once (the API allows 50 blockers per task, not per blocker)
    c.executemany("INSERT INTO task_deps(task_id,blocker_id,created_by,created_at) VALUES(?,?,1,?)", [(f, root, f"2026-01-01T00:00:{i:02d}.000Z") for i, f in enumerate(fan)])
r = A.patch(B + f"/api/tasks/{root}", json={"due": D(2)}).json()
check(len(r["shifted"]) == 50, f"cascade capped at 50 tasks: {len(r['shifted'])}")
r = A.patch(B + f"/api/lists/{W}", json={"dep_shift": False})
check(r.ok and next(l for l in state(A)["lists"] if l["id"] == W)["dep_shift"] == 0, "dep_shift: off again")

# ---- migration of existing users (features_rev 7 -> 8, then 9 = "comments", 2.0.6) after a restart on the same data
with db() as c:
    c.execute("UPDATE settings SET value='cal,habits,collab,time' WHERE key='default_features'")
    c.execute("DELETE FROM settings WHERE key='migr_feat8'")
    for uid, fs in ((1, "cal,timeline,matrix,collab,time"), (BOB, "cal,habits,collab"), (CAROL, "cal,habits,collab")):
        c.execute("UPDATE user_settings SET value=? WHERE user_id=? AND key='features'", (fs, uid))
        c.execute("UPDATE user_settings SET value='7' WHERE user_id=? AND key='features_rev'", (uid,))
    c.execute("DELETE FROM task_deps WHERE task_id IN (SELECT id FROM tasks WHERE list_id=?) OR blocker_id IN (SELECT id FROM tasks WHERE list_id=?)", (P, P))
    c.execute("INSERT INTO list_fields(list_id,name,type,options,sort,created_at) VALUES(?,?,?,?,?,?)", (P, "Phase", "text", "{}", 0, "2026-01-01T00:00:00Z"))
    c.commit()
with db() as c:  # list types from before 1.2: every list a plain list again, checklist flag set on one
    c.execute("UPDATE lists SET kind='list', checklist=0")
    c.execute("UPDATE lists SET checklist=1 WHERE id=?", (CKL,))
    c.execute("INSERT INTO time_entries(user_id,task_id,list_id,task_title,start,end,seconds,source,created_at,updated_at) "
              "VALUES(1,?,?,'misclick','2026-09-01T08:00:00Z','2026-09-01T08:01:00Z',60,'timer','x','x')", (pt, PL))
    c.execute("DELETE FROM settings WHERE key='migr_kind'")
    c.commit()
subprocess.run(["docker", "stop", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)
check(r.returncode == 0, "container restarted on the same data " + r.stderr[-300:])
with db() as c:
    u = {r2["user_id"]: r2["value"] for r2 in c.execute("SELECT user_id, value FROM user_settings WHERE key='features'")}
    rev = {r2["user_id"]: r2["value"] for r2 in c.execute("SELECT user_id, value FROM user_settings WHERE key='features_rev'")}
    dflt = c.execute("SELECT value FROM settings WHERE key='default_features'").fetchone()[0]
check(u[1] == "cal,timeline,matrix,collab,time,deps,fields,comments", f"migration: timeline user gets deps + fields, nothing else changes: {u[1]}")
check(u[BOB] == "cal,habits,collab,deps,fields,comments", f"migration: member of a list with dependencies + a custom field gets both: {u[BOB]}")
check(u[CAROL] == "cal,habits,collab,fields,comments", f"migration: user with a custom field gets fields; deps = instance default (off): {u[CAROL]}")
check(all(v == "9" for v in rev.values()), f"migration: features_rev 9 for everyone (8 + comments): {rev}")
check(dflt == "cal,habits,collab,time", f"migration: setup default without timeline / progress stays as chosen: {dflt}")
with db() as c:
    kinds = {r2["id"]: r2["kind"] for r2 in c.execute("SELECT id, kind FROM lists")}
check(kinds[W] == "project" and kinds[TP] == "project" and kinds[P] == "project", f"migration: lists with dependencies / time / fields became projects: {kinds}")
check(kinds[CKL] == "checklist" and kinds[PL] == "list" and kinds[X] == "project", "migration: checklist stays a checklist, a list with only a 1-minute timer (under 5 min) stays a list")
with db() as c:
    c.execute("UPDATE settings SET value='cal,timeline,progress,collab,time' WHERE key='default_features'")
    c.execute("DELETE FROM settings WHERE key='migr_feat8'")
    c.execute("UPDATE user_settings SET value='cal' WHERE user_id=? AND key='features'", (CAROL,))
    c.execute("UPDATE user_settings SET value='7' WHERE user_id=? AND key='features_rev'", (CAROL,))
    # user 1 (rev 9) switches comments off: the migrations must not bring them back
    c.execute("UPDATE user_settings SET value='cal,timeline,matrix,collab,time,deps,fields' WHERE user_id=1 AND key='features'")
    c.execute("DELETE FROM list_fields WHERE list_id=?", (P,))
    c.commit()
subprocess.run(["docker", "stop", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)
with db() as c:
    dflt = c.execute("SELECT value FROM settings WHERE key='default_features'").fetchone()[0]
    uc = c.execute("SELECT value FROM user_settings WHERE key='features' AND user_id=?", (CAROL,)).fetchone()[0]
    u1 = c.execute("SELECT value FROM user_settings WHERE key='features' AND user_id=1").fetchone()[0]
check(dflt == "cal,timeline,progress,collab,time,deps,fields", f"migration: an old setup default with the timeline gets deps + fields: {dflt}")
check(uc == "cal,deps,fields,comments", f"migration: no data, no timeline -> the (migrated) instance default: {uc}")
check(u1 == "cal,timeline,matrix,collab,time,deps,fields", f"migration runs once (rev 9 users untouched, comments stay off): {u1}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
