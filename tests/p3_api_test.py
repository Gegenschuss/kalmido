#!/usr/bin/env python3
"""Package 3 API tests (fresh DB on the TEST container :3048): dependencies (graph, cycles, visibility / IDOR,
unblock push + News, trash / restore, undo, recurring, batch), project status (permissions, News, history),
progress numbers on seeded data, custom fields (CRUD per type, validation, permissions, values, moves, member
removal, search, activity, export, templates, recurring copies)."""
import json, os, sqlite3, sys, time
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


def db():
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c.row_factory = sqlite3.Row
    return c


def pushes():
    try:
        return [json.loads(l) for l in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        return []


def state(s):
    return s.get(B + "/api/state").json()


def task(s, tid):
    return next((t for t in state(s)["tasks"] if t["id"] == tid), None)


def news(s):
    return s.get(B + "/api/news").json()["items"]


D = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
ids = {}
for u, n in (("bob", "Bob"), ("carol", "Carol"), ("dave", "Dave")):
    ids[u] = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "ntfy_topic": "t-" + u}).json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bb, C, Dv = sess("bob"), sess("carol"), sess("dave")
Bb.patch(B + "/api/settings", json={"lang": "de"})
st = state(A)
check("progress" in st["settings"]["features"].split(",") and st["settings"]["features_rev"] == "9", "new user: progress module on, features_rev 9 (2.0.6)")
check(st["settings"]["hide_blocked_today"] == "0" and st["settings"]["progress_subtasks"] == "0", "new settings defaults")
check(st["fields"] == [], "state: fields []")

W = A.post(B + "/api/lists", json={"name": "Work", "kind": "project"}).json()["id"]
A.put(B + f"/api/lists/{W}/members", json={"user_id": BOB, "role": "edit"})
A.put(B + f"/api/lists/{W}/members", json={"user_id": CAROL, "role": "view"})
P = A.post(B + "/api/lists", json={"name": "Private", "kind": "project"}).json()["id"]
BL = Bb.post(B + "/api/lists", json={"name": "Bob only", "kind": "project"}).json()["id"]


def mk(s, **kw):
    r = s.post(B + "/api/tasks", json=kw)
    assert r.ok, r.text
    return r.json()["id"]


t1 = mk(A, title="Design", list_id=W)
t2 = mk(A, title="Build", list_id=W, assignee_id=BOB)
t3 = mk(A, title="Ship", list_id=W)
tp = mk(A, title="Private prep", list_id=P)
tb = mk(Bb, title="Bob secret", list_id=BL)
dep = lambda s, t, b: s.post(B + "/api/deps", json={"task_id": t, "blocker_id": b})  # noqa: E731

# ================= dependencies: graph rules
r = dep(A, t2, t1)
check(r.ok and r.json()["task"]["blocked"] == 1 and r.json()["task"]["blockers"] == [t1], "add: Build waits on Design")
check(dep(A, t2, t1).ok, "adding the same dependency twice: ok (idempotent)")
with db() as c:
    check(c.execute("SELECT COUNT(*) FROM task_deps").fetchone()[0] == 1, "stored once")
check(dep(A, t3, t2).ok, "Ship waits on Build")
r = dep(A, t1, t3)
check(r.status_code == 400 and "circular" in r.json()["error"], "cycle Design -> Ship -> Build -> Design refused")
r = dep(A, t1, t2)
check(r.status_code == 400, "direct cycle refused")
r = dep(A, t1, t1)
check(r.status_code == 400 and "itself" in r.json()["error"], "self-dependency refused")
check(dep(A, t1, tp).ok, "cross-list: Design (shared) waits on Private prep (private list of alice)")
r = A.post(B + "/api/deps", json={"task_id": "x", "blocker_id": t1})
check(r.status_code == 400, "invalid ids: 400")
# visibility / IDOR
check(dep(A, t1, tb).status_code == 404, "blocker in a list I cannot see: 404")
check(dep(Bb, tb, tp).status_code == 404, "bob: blocker in alice's private list: 404")
check(dep(Dv, t1, t3).status_code == 404, "stranger: 404")
check(dep(C, t3, t1).status_code == 403, "view-only member cannot add (403)")
check(C.delete(B + f"/api/deps/{t2}/{t1}").status_code == 403, "view-only member cannot remove (403)")
check(dep(Bb, tb, t1).ok, "bob: own task waits on a shared task (write on the waiting task, blocker visible)")
bob_tb_dep = True
check(C.get(B + f"/api/tasks/{t2}/deps").ok and Dv.get(B + f"/api/tasks/{t2}/deps").status_code == 404, "deps endpoint: view member ok, stranger 404")
# what bob sees: Design waits on "Private prep" which he cannot see
bt = task(Bb, t1)
check(bt["blocked"] == 1 and bt["blockers"] == [], "bob: Design blocked=1, no visible blocker id")
j = Bb.get(B + f"/api/tasks/{t1}/deps").json()
check(len(j["blocked_by"]) == 1 and j["blocked_by"][0]["hidden"] and j["blocked_by"][0]["title"] is None and j["blocked_by"][0]["id"] is None,
      "bob: hidden blocker without id / title")
check(any(x["id"] == t2 for x in j["blocking"]), "bob: Design blocks Build")
tl = Bb.get(B + f"/api/tasks/{t1}/timeline").json()
da = [a for a in tl["activity"] if a["kind"] == "dep_add"]
check(da and all("Private prep" not in json.dumps(a) for a in da) and any(a["data"].get("hidden") for a in da), "timeline: title of the hidden blocker not sent to bob")
tl = A.get(B + f"/api/tasks/{t1}/timeline").json()
check(any(a["kind"] == "dep_add" and a["data"].get("title") == "Private prep" for a in tl["activity"]), "timeline: alice sees the title")
check(any(a["kind"] == "blocks_add" for a in A.get(B + f"/api/tasks/{t1}/timeline").json()["activity"]), "blocker gets a 'blocks' line")
# alice's view of tb (bob's list): not visible at all
check(A.get(B + f"/api/tasks/{tb}/deps").status_code == 404, "alice: deps of bob's private task: 404")
j = A.get(B + f"/api/tasks/{t1}/deps").json()
check(any(x["hidden"] for x in j["blocking"]) and "Bob secret" not in json.dumps(j), "alice: bob's task waiting on Design shown as hidden")
# remove hidden blockers (lost access): bob removes via /0 -> only the hidden one goes
Bb.post(B + "/api/deps", json={"task_id": t3, "blocker_id": t1})
r = Bb.delete(B + f"/api/deps/{t1}/0")
check(r.ok and task(A, t1)["blocked"] == 0, "bob removes the dependency on the task he cannot see (/0)")
check(Bb.delete(B + f"/api/deps/{t3}/{t1}").ok and Bb.delete(B + f"/api/deps/{t3}/{t1}").status_code == 404, "remove; removing again 404")
tl = A.get(B + f"/api/tasks/{t1}/timeline").json()
check(any(a["kind"] == "dep_rm" for a in tl["activity"]), "activity: dependency removed")
check(dep(A, t1, tp).ok, "re-add Design waits on Private prep")
check(Bb.delete(B + f"/api/deps/{tb}/{t1}").ok, "bob removes his own dependency again")

# ================= trash / restore of a blocker
A.delete(B + f"/api/tasks/{tp}")
check(task(A, t1)["blocked"] == 0, "blocker in the trash: ignored")
check(all(x["id"] != tp for x in A.get(B + f"/api/tasks/{t1}/deps").json()["blocked_by"]), "trashed blocker not listed")
A.post(B + f"/api/tasks/{tp}/restore")
check(task(A, t1)["blocked"] == 1, "restored: blocks again")

# ================= completion + unblock push / News
time.sleep(3.2)  # burst windows of the assign pushes above are over
open(os.path.join(DATA, "ntfy.log"), "w").close()
r = A.post(B + f"/api/tasks/{t3}/complete")
check(task(A, t3) is not None and r.ok and r.json()["status"] == 2, "completing a waiting task is allowed (the client asks first)")
A.post(B + f"/api/tasks/{t3}/reopen")
A.post(B + f"/api/tasks/{tp}/complete")  # Design's last blocker done -> Design unblocked; creator alice = actor -> no notify
time.sleep(0.6)
check(task(A, t1)["blocked"] == 0, "Design unblocked")
check(not [p for p in pushes() if "Design" in p["title"]], "no self-notification (creator completed it)")
check(any(a["kind"] == "unblocked" for a in A.get(B + f"/api/tasks/{t1}/timeline").json()["activity"]), "activity: unblocked line")
# Build (assigned to bob) waits on Design: carol cannot complete (view) -> alice completes Design
check(C.post(B + f"/api/tasks/{t1}/complete").status_code == 403, "view member cannot complete")
res = A.post(B + f"/api/tasks/{t1}/complete").json()
time.sleep(0.6)
ps = [p for p in pushes() if p["topic"] == "t-bob"]
check(len(ps) == 1 and ps[0]["title"] == "Wartet nicht mehr: Build" and "Alice hat Design erledigt" in ps[0]["msg"] and ps[0]["click"].endswith(f"/#t/{t2}"),
      f"push to the assignee bob, German: {ps}")
check(not [p for p in pushes() if p["topic"] in ("t-alice", "t-carol")], "nobody else gets a push")
nb = [x for x in news(Bb) if x["kind"] == "unblock"]
check(len(nb) == 1 and nb[0]["task_id"] == t2 and nb[0]["data"] == {"title": "Design", "hidden": False} and nb[0]["actor_id"] == 1, "News item for bob")
check(not [x for x in news(C) if x["kind"] == "unblock"], "carol: no unblock News")
# undo of the completion takes the News item and the activity line back
u = A.post(B + f"/api/tasks/{t1}/undo", json=res["undo"])
check(u.ok and task(A, t2)["blocked"] == 1, "undo: Build waits again")
check(not [x for x in news(Bb) if x["kind"] == "unblock"], "undo removed bob's News item")
check(not [a for a in A.get(B + f"/api/tasks/{t2}/timeline").json()["activity"] if a["kind"] == "unblocked"], "undo removed the 'unblocked' line")
# unassigned waiting task -> its creator; bob completes the blocker
t4 = mk(A, title="Write docs", list_id=W)
t5 = mk(Bb, title="API ready", list_id=W)
dep(A, t4, t5)
open(os.path.join(DATA, "ntfy.log"), "w").close()
Bb.post(B + f"/api/tasks/{t5}/complete")
time.sleep(0.6)
ps = pushes()
check(len(ps) == 1 and ps[0]["topic"] == "t-alice" and ps[0]["title"] == "Unblocked: Write docs" and "Bob completed API ready" in ps[0]["msg"], f"unassigned -> creator alice (English): {ps}")
# two blockers: only the LAST one unblocks
t6 = mk(A, title="Release", list_id=W, assignee_id=BOB)
b1, b2 = mk(A, title="QA", list_id=W), mk(A, title="Docs review", list_id=W)
dep(A, t6, b1), dep(A, t6, b2)
time.sleep(3.2)
open(os.path.join(DATA, "ntfy.log"), "w").close()
A.post(B + f"/api/tasks/{b1}/complete")
time.sleep(0.4)
check(not pushes() and task(A, t6)["blocked"] == 1, "first of two blockers done: still waiting, no push")
A.post(B + f"/api/tasks/{b2}/complete", json={"status": -1})
time.sleep(0.6)
check(len(pushes()) == 1 and task(A, t6)["blocked"] == 0, "won't do of the last blocker unblocks (+ push)")
# collab off at the recipient: no News, no push
Bb.patch(B + "/api/settings", json={"features": "cal,timeline,matrix,habits,pomo,kanban,paperless,stats,time,progress"})
t7 = mk(A, title="Deploy", list_id=W, assignee_id=BOB)
b3 = mk(A, title="Staging ok", list_id=W)
dep(A, t7, b3)
open(os.path.join(DATA, "ntfy.log"), "w").close()
A.post(B + f"/api/tasks/{b3}/complete")
time.sleep(0.5)
check(not pushes(), "recipient with collaboration off: no push")
with db() as c:
    check(not c.execute("SELECT 1 FROM notifications WHERE kind='unblock' AND task_id=?", (t7,)).fetchone(), "... and no News row")
Bb.patch(B + "/api/settings", json={"features": "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields"})
# burst rule: an unblock right after another event on the same task for bob -> counted, not pushed
t8 = mk(A, title="Invoice", list_id=W)
b4 = mk(A, title="Timesheet", list_id=W)
dep(A, t8, b4)
open(os.path.join(DATA, "ntfy.log"), "w").close()
A.patch(B + f"/api/tasks/{t8}", json={"assignee_id": BOB})  # assign push (burst window opens)
A.post(B + f"/api/tasks/{b4}/complete")
time.sleep(0.6)
ps = [p for p in pushes() if p["topic"] == "t-bob" and p["click"].endswith(f"/#t/{t8}")]
check(len(ps) == 1 and "zugewiesen" in ps[0]["title"], f"burst: assign pushed, unblock only counted: {ps}")
with db() as c:
    r = c.execute("SELECT events FROM task_push WHERE user_id=? AND task_id=?", (BOB, t8)).fetchone()
check(r and r["events"] == 1, "burst: unblock counted for the summary")
# recurring blocker stays open
t9 = mk(A, title="Monthly close", list_id=W, assignee_id=BOB)
b5 = mk(A, title="Weekly sync", list_id=W, due=D(0), repeat="FREQ=WEEKLY")
dep(A, t9, b5)
A.post(B + f"/api/tasks/{b5}/complete", json={"expect_due": D(0)})
check(task(A, t9)["blocked"] == 1, "recurring blocker: completing an occurrence does not unblock")
# batch complete: unblock once per waiting task
t10 = mk(A, title="Launch", list_id=W, assignee_id=BOB)
b6, b7 = mk(A, title="Copy", list_id=W), mk(A, title="Visuals", list_id=W)
dep(A, t10, b6), dep(A, t10, b7)
time.sleep(3.2)
open(os.path.join(DATA, "ntfy.log"), "w").close()
A.post(B + "/api/tasks/batch", json={"ids": [b6, b7], "action": "complete"})
time.sleep(0.6)
check(len([p for p in pushes() if "Launch" in p["title"]]) == 1 and task(A, t10)["blocked"] == 0, "batch: both blockers done -> one unblock push")
with db() as c:
    check(c.execute("SELECT COUNT(*) FROM activity WHERE task_id=? AND kind='unblocked'", (t10,)).fetchone()[0] == 1, "batch: one 'unblocked' line")
# a completed subtask blocker (completed together with its parent)
t11 = mk(A, title="Publish", list_id=W, assignee_id=BOB)
par = mk(A, title="Prepare", list_id=W)
kid = mk(A, title="Proofread", list_id=W, parent_id=par)
dep(A, t11, kid)
A.post(B + f"/api/tasks/{par}/complete")
check(task(A, t11)["blocked"] == 0 and any(a["kind"] == "unblocked" for a in A.get(B + f"/api/tasks/{t11}/timeline").json()["activity"]),
      "subtask completed with its parent unblocks")
# hard delete of a blocker removes the edge (FK cascade)
t12 = mk(A, title="Tidy", list_id=W)
b8 = mk(A, title="Temp", list_id=W)
dep(A, t12, b8)
A.delete(B + f"/api/tasks/{b8}?hard=1")
with db() as c:
    check(not c.execute("SELECT 1 FROM task_deps WHERE blocker_id=?", (b8,)).fetchone(), "hard delete: dependency gone")
# losing visibility: carol's News item about a blocker she can no longer see
cl = C.post(B + "/api/lists", json={"name": "Carol list", "kind": "project"}).json()["id"]
C.put(B + f"/api/lists/{cl}/members", json={"user_id": 1, "role": "edit"})
tc = mk(C, title="Carol waits", list_id=cl)
tx = mk(A, title="Hidden blocker", list_id=W)
check(dep(C, tc, tx).ok, "carol (view member of Work) may wait on a Work task")
A.delete(B + f"/api/lists/{W}/members/{CAROL}")
check(task(C, tc)["blocked"] == 1 and task(C, tc)["blockers"] == [], "after losing access: blocked count stays, no visible id")
A.post(B + f"/api/tasks/{tx}/complete")
nc = [x for x in news(C) if x["kind"] == "unblock"]
check(len(nc) == 1 and nc[0]["data"] == {"title": None, "hidden": True} and "Hidden blocker" not in json.dumps(nc), "carol's News: blocker title hidden")
check(DEP_ok := A.get(B + f"/api/tasks/{tc}/deps").ok, "alice (member of Carol list) sees the deps")
# limit
many = [mk(A, title=f"b{i}", list_id=P) for i in range(51)]
tl_ = mk(A, title="Many", list_id=P)
codes = [dep(A, tl_, x).status_code for x in many]
check(codes[:50] == [200] * 50 and codes[50] == 400, "at most 50 dependencies per task")

# ================= project status
r = A.post(B + f"/api/lists/{W}/status", json={"status": "at_risk", "note": "  Vendor late  "})
check(r.ok, "owner sets At risk")
lw = next(l for l in state(A)["lists"] if l["id"] == W)
check(lw["status"] == "at_risk" and lw["status_note"] == "Vendor late" and lw["status_by"] == 1 and lw["status_by_name"] == "Alice", "list carries status + note + who")
nb = [x for x in news(Bb) if x["kind"] == "status"]
check(len(nb) == 1 and nb[0]["list_id"] == W and nb[0]["task_id"] is None and nb[0]["data"]["status"] == "at_risk" and nb[0]["excerpt"] == "Vendor late", "News for member bob")
check(not [x for x in news(A) if x["kind"] == "status"], "no News for the actor")
A.put(B + f"/api/lists/{W}/members", json={"user_id": CAROL, "role": "view"})
check(Bb.post(B + f"/api/lists/{W}/status", json={"status": "on_track", "note": "Vendor delivered"}).ok, "edit member sets On track")
check(C.post(B + f"/api/lists/{W}/status", json={"status": "off_track"}).status_code == 403, "view member: 403")
check(Dv.post(B + f"/api/lists/{W}/status", json={"status": "off_track"}).status_code == 404, "stranger: 404")
check(A.post(B + f"/api/lists/{W}/status", json={"status": "great"}).status_code == 400, "unknown status: 400")
inbox = next(l for l in state(A)["lists"] if l["is_inbox"])["id"]
check(A.post(B + f"/api/lists/{inbox}/status", json={"status": "on_track"}).status_code == 400, "inbox: no status")
check(A.post(B + f"/api/lists/{W}/status", json={"status": "on_hold", "note": "x" * 900}).ok and len(next(l for l in state(A)["lists"] if l["id"] == W)["status_note"]) == 500, "note capped at 500")
na = [x for x in news(A) if x["kind"] == "status"]
check(len(na) == 1 and na[0]["actor_id"] == BOB, "alice got bob's update")
check(sorted(x["data"]["status"] for x in news(C) if x["kind"] == "status") == ["on_hold", "on_track"], "carol: only the updates after she was re-added")
h = C.get(B + f"/api/lists/{W}/status").json()["items"]
check([x["status"] for x in h] == ["on_hold", "on_track", "at_risk"] and h[1]["name"] == "Bob", "history newest first (view member may read)")
check(Dv.get(B + f"/api/lists/{W}/status").status_code == 404, "history: stranger 404")
check(A.post(B + f"/api/lists/{W}/status", json={"status": ""}).ok and next(l for l in state(A)["lists"] if l["id"] == W)["status"] == "", "clear status")
check(A.get(B + f"/api/lists/{W}/status").json()["items"][0]["status"] == "", "clearing is in the history")

# ================= progress numbers
PR = A.post(B + "/api/lists", json={"name": "Progress", "kind": "project"}).json()["id"]
m1 = mk(A, title="m1", list_id=PR, due=D(-2))    # open, overdue
m2 = mk(A, title="m2", list_id=PR, due=D(3))     # open, next due
m3 = mk(A, title="m3", list_id=PR, due=D(1))     # done
m4 = mk(A, title="m4", list_id=PR)               # won't do: not counted
m5 = mk(A, title="m5", list_id=PR)               # trash: not counted
m6 = mk(A, title="m6", list_id=PR, due=D(0), repeat="FREQ=DAILY")  # recurring: counts once (open)
s1 = mk(A, title="s1", list_id=PR, parent_id=m1, due=D(-5))
s2 = mk(A, title="s2", list_id=PR, parent_id=m1)
A.post(B + f"/api/tasks/{m3}/complete")
A.post(B + f"/api/tasks/{m4}/complete", json={"status": -1})
A.delete(B + f"/api/tasks/{m5}")
A.post(B + f"/api/tasks/{m6}/complete", json={"expect_due": D(0)})
A.post(B + f"/api/tasks/{m6}/complete", json={"expect_due": D(1)})
A.post(B + f"/api/tasks/{s2}/complete")
pg = next(l for l in state(A)["lists"] if l["id"] == PR)["progress"]
check(pg == {"done": 1, "total": 4, "overdue": 1, "next_due": D(2)}, f"progress main tasks: {pg}")
A.patch(B + "/api/settings", json={"progress_subtasks": "1"})
pg = next(l for l in state(A)["lists"] if l["id"] == PR)["progress"]
check(pg == {"done": 2, "total": 6, "overdue": 2, "next_due": D(2)}, f"progress incl. subtasks: {pg}")
A.patch(B + "/api/settings", json={"progress_subtasks": "0"})
pgb = next(l for l in state(Bb)["lists"] if l["id"] == W)["progress"]
check(pgb["total"] > 0, "member sees the progress of a shared list")

# ================= custom fields: CRUD + validation
F = A.post(B + f"/api/lists/{W}/fields", json={"name": "Stage", "type": "select", "pinned": True,
                                              "options": {"options": [{"name": "Idea", "color": "#94a3b8"}, {"name": "Doing", "color": "bad"}, {"name": " "}]}}).json()
check(F["type"] == "select" and [o["name"] for o in F["options"]["options"]] == ["Idea", "Doing"] and F["options"]["options"][1]["color"] == "" and F["pinned"] == 1,
      "select field: empty option dropped, bad color cleared")
OPT = {o["name"]: o["id"] for o in F["options"]["options"]}
FN = A.post(B + f"/api/lists/{W}/fields", json={"name": "Budget", "type": "number", "options": {"unit": "€"}, "pinned": True}).json()
FT = A.post(B + f"/api/lists/{W}/fields", json={"name": "Client", "type": "text"}).json()
FD = A.post(B + f"/api/lists/{W}/fields", json={"name": "Deadline", "type": "date"}).json()
FC = A.post(B + f"/api/lists/{W}/fields", json={"name": "Approved", "type": "checkbox"}).json()
FP = A.post(B + f"/api/lists/{W}/fields", json={"name": "Reviewer", "type": "person"}).json()
FU = A.post(B + f"/api/lists/{W}/fields", json={"name": "Spec", "type": "url"}).json()
check(all(isinstance(x.get("id"), int) for x in (FN, FT, FD, FC, FP, FU)), "one field of each type")
r = A.post(B + f"/api/lists/{W}/fields", json={"name": "Third pin", "type": "text", "pinned": True})
check(r.status_code == 400, "a third pinned field is refused")
check(A.post(B + f"/api/lists/{W}/fields", json={"name": "X", "type": "formula"}).status_code == 400, "unknown type: 400")
check(A.post(B + f"/api/lists/{W}/fields", json={"name": " ", "type": "text"}).status_code == 400, "empty name: 400")
check(A.post(B + f"/api/lists/{W}/fields", json={"name": "S", "type": "select", "options": {"options": []}}).status_code == 400, "select without options: 400")
check(Bb.post(B + f"/api/lists/{W}/fields", json={"name": "B", "type": "text"}).status_code == 403, "edit member cannot define fields (403)")
check(Dv.post(B + f"/api/lists/{W}/fields", json={"name": "B", "type": "text"}).status_code == 404, "stranger: 404")
check(Bb.patch(B + f"/api/fields/{FT['id']}", json={"name": "Hacked"}).status_code == 403 and Dv.delete(B + f"/api/fields/{FT['id']}").status_code == 404,
      "member cannot change / stranger cannot delete a field")
xs = [A.post(B + f"/api/lists/{P}/fields", json={"name": f"f{i}", "type": "text"}).status_code for i in range(21)]
check(xs[:20] == [200] * 20 and xs[20] == 400, "at most 20 fields per list")
r = A.patch(B + f"/api/fields/{FT['id']}", json={"name": "Customer", "type": "number"}).json()
check(r["name"] == "Customer" and r["type"] == "text", "rename; the type cannot change")
check(state(Bb)["fields"] and {f["id"] for f in state(Bb)["fields"]} >= {F["id"], FN["id"]} and not any(f["list_id"] == P for f in state(Bb)["fields"]),
      "member sees the fields of the shared list, not of alice's private list")

# ================= values
ok = A.patch(B + f"/api/tasks/{t2}", json={"fields": {str(F["id"]): OPT["Doing"], str(FN["id"]): "1.234,5".replace(".", ""), str(FT["id"]): "  Acme  ",
                                                         str(FD["id"]): D(7), str(FC["id"]): True, str(FP["id"]): BOB, str(FU["id"]): "https://example.com/spec"}})
check(ok.ok, "set all seven values: " + ok.text[:200])
fv = task(Bb, t2)["fields"]
check(fv == {str(F["id"]): OPT["Doing"], str(FN["id"]): "1234.5", str(FT["id"]): "Acme", str(FD["id"]): D(7), str(FC["id"]): "1", str(FP["id"]): str(BOB),
             str(FU["id"]): "https://example.com/spec"}, f"stored values (bob sees them): {fv}")
bad = [(FN, "abc"), (FN, "1e20"), (FD, "2026-13-01"), (F, "nope"), (FP, DAVE), (FU, "ftp://x"), (FN, {"a": 1})]
codes = [A.patch(B + f"/api/tasks/{t2}", json={"fields": {str(f["id"]): v}}).status_code for f, v in bad]
check(codes == [400] * len(bad), f"invalid values refused: {codes}")
check(A.patch(B + f"/api/tasks/{t2}", json={"fields": {"99999": "x"}}).status_code == 400, "unknown field id: 400")
check(A.patch(B + f"/api/tasks/{t2}", json={"fields": {str(FN["id"]): "7", str(F["id"]): "nope"}}).status_code == 400 and task(A, t2)["fields"][str(FN["id"])] == "1234.5",
      "one invalid value: nothing stored")
check(A.patch(B + f"/api/tasks/{tp}", json={"fields": {str(F["id"]): OPT["Idea"]}}).status_code == 400, "field of another list: 400")
check(Bb.patch(B + f"/api/tasks/{t2}", json={"fields": {str(FN["id"]): "99"}}).ok and task(A, t2)["fields"][str(FN["id"])] == "99", "edit member sets a value")
check(C.patch(B + f"/api/tasks/{t2}", json={"fields": {str(FN["id"]): "5"}}).status_code == 403, "view member cannot (403)")
check(Dv.patch(B + f"/api/tasks/{t2}", json={"fields": {str(FN["id"]): "5"}}).status_code == 404, "stranger: 404")
check(A.patch(B + f"/api/tasks/{t2}", json={"fields": {str(FC["id"]): False, str(FT["id"]): ""}}).ok and
      str(FC["id"]) not in task(A, t2)["fields"] and str(FT["id"]) not in task(A, t2)["fields"], "unchecking / emptying removes the value")
A.patch(B + f"/api/tasks/{t2}", json={"fields": {str(FT["id"]): "Acme"}})
# activity: one line per field, repeated edits of the same field merge
A.patch(B + f"/api/tasks/{t3}", json={"fields": {str(FN["id"]): "1"}})
A.patch(B + f"/api/tasks/{t3}", json={"fields": {str(FN["id"]): "2"}})
A.patch(B + f"/api/tasks/{t3}", json={"fields": {str(F["id"]): OPT["Idea"]}})
acts = [a for a in A.get(B + f"/api/tasks/{t3}/timeline").json()["activity"] if a["kind"] == "field"]
check(len(acts) == 2 and acts[0]["data"]["v"] == "2" and acts[0]["data"]["unit"] == "€" and acts[1]["data"]["v"] == "Idea", f"activity merged per field: {[a['data'] for a in acts]}")
acts = [a for a in A.get(B + f"/api/tasks/{t2}/timeline").json()["activity"] if a["kind"] == "field" and a["data"]["name"] == "Reviewer"]
check(acts and acts[-1]["data"]["v"] == "Bob", "person value logged with the name")
# create with fields, and the validation there
tn = A.post(B + "/api/tasks", json={"title": "With fields", "list_id": W, "fields": {str(FN["id"]): "3", str(F["id"]): OPT["Idea"]}}).json()
check(tn["fields"] == {str(FN["id"]): "3", str(F["id"]): OPT["Idea"]}, "create with fields")
n0 = len(state(A)["tasks"])
check(A.post(B + "/api/tasks", json={"title": "Bad", "list_id": W, "fields": {str(FN["id"]): "x"}}).status_code == 400 and len(state(A)["tasks"]) == n0, "create with a bad value: 400, no task")
# select options: removing one clears its values
A.patch(B + f"/api/tasks/{t1}", json={"fields": {str(F["id"]): OPT["Idea"]}})
r = A.patch(B + f"/api/fields/{F['id']}", json={"options": {"options": [{"id": OPT["Doing"], "name": "In progress", "color": "#6d8cff"}]}}).json()
check([o["id"] for o in r["options"]["options"]] == [OPT["Doing"]] and r["options"]["options"][0]["name"] == "In progress", "rename option keeps its id")
check(str(F["id"]) not in task(A, t1)["fields"] and task(A, t2)["fields"][str(F["id"])] == OPT["Doing"], "removed option cleared, kept option stays")
# pinned toggling
check(A.patch(B + f"/api/fields/{FT['id']}", json={"pinned": True}).status_code == 400, "pin a third: 400")
check(A.patch(B + f"/api/fields/{FN['id']}", json={"pinned": False}).ok and A.patch(B + f"/api/fields/{FT['id']}", json={"pinned": True}).ok, "unpin one, pin another")
# move to another list hides the values, moving back brings them back
A.patch(B + f"/api/tasks/{t2}", json={"list_id": P})
check(task(A, t2)["fields"] == {}, "moved to another list: values hidden")
A.patch(B + f"/api/tasks/{t2}", json={"list_id": W})
check(task(A, t2)["fields"].get(str(FN["id"])) == "99", "moved back: values back")
# member removal clears person values of that member
A.patch(B + f"/api/tasks/{t3}", json={"fields": {str(FP["id"]): BOB}})
A.delete(B + f"/api/lists/{W}/members/{BOB}")
check(str(FP["id"]) not in task(A, t3)["fields"], "removed member: person value cleared")
A.put(B + f"/api/lists/{W}/members", json={"user_id": BOB, "role": "edit"})
# search: text + select option names
hits = {t["id"] for t in A.get(B + "/api/tasks?scope=search&q=acme").json()["tasks"]}
check(t2 in hits, "search finds the text value")
hits = {t["id"] for t in A.get(B + "/api/tasks?scope=search&q=progress").json()["tasks"]}
check(t2 in hits and t1 not in hits, "search finds the select option name")
check(not Dv.get(B + "/api/tasks?scope=search&q=acme").json()["tasks"], "search: stranger finds nothing")
# recurring completion copies the values to the done copy
rc = mk(A, title="Weekly report", list_id=W, due=D(0), repeat="FREQ=WEEKLY", fields={str(FN["id"]): "10"})
A.post(B + f"/api/tasks/{rc}/complete", json={"expect_due": D(0)})
with db() as c:
    cp = c.execute("SELECT id FROM tasks WHERE title='Weekly report' AND status=2").fetchone()
    check(cp and c.execute("SELECT value FROM task_field_values WHERE task_id=?", (cp["id"],)).fetchone()[0] == "10", "done copy keeps the values")

# ================= templates carry the fields (+ values, dates relative)
A.patch(B + f"/api/tasks/{t3}", json={"fields": {str(FD["id"]): D(4), str(FP["id"]): BOB, str(FN["id"]): "5"}})
tpl = A.post(B + "/api/templates", json={"list_id": W, "name": "Project tpl"}).json()
fd = tpl["data"]["fields"]
check([f["name"] for f in fd][:3] == ["Stage", "Budget", "Customer"] and fd[0]["options"]["options"][0]["name"] == "In progress", "list template: field definitions")
node = next(n for n in tpl["data"]["tasks"] if n["title"] == "Ship")
idx = {f["name"]: str(i) for i, f in enumerate(fd)}
check(node["fv"].get(idx["Deadline"]) == 4 and node["fv"].get(idx["Budget"]) == "5" and idx["Reviewer"] not in node["fv"], f"node values: date as offset, no person: {node.get('fv')}")
nl = A.post(B + f"/api/templates/{tpl['id']}/apply", json={"name": "From tpl"}).json()["list_id"]
st2 = state(A)
nf = {f["name"]: f for f in st2["fields"] if f["list_id"] == nl}
check(set(nf) == {f["name"] for f in fd} and nf["Stage"]["pinned"] == 1, "applied: fields created in the new list")
ship = next(t for t in st2["tasks"] if t["list_id"] == nl and t["title"] == "Ship")
check(ship["fields"].get(str(nf["Deadline"]["id"])) == D(4) and ship["fields"].get(str(nf["Budget"]["id"])) == "5", f"applied: values (date relative): {ship['fields']}")
build = next(t for t in st2["tasks"] if t["list_id"] == nl and t["title"] == "Build")
check(build["fields"].get(str(nf["Stage"]["id"])) == OPT["Doing"], "select value maps to the copied option")
# edited template keeps the fields
r = A.patch(B + f"/api/templates/{tpl['id']}", json={"data": {**tpl["data"], "fields": fd + [{"name": "Bad", "type": "nope"}]}})
check(r.status_code == 400, "template with an invalid field definition: 400")
check(A.patch(B + f"/api/templates/{tpl['id']}", json={"data": tpl["data"]}).json()["data"]["fields"] == fd, "template round trip keeps the fields")

# ================= delete a field: values go
nv = 0
with db() as c:
    nv = c.execute("SELECT COUNT(*) FROM task_field_values WHERE field_id=?", (FN["id"],)).fetchone()[0]
r = A.delete(B + f"/api/fields/{FN['id']}")
check(r.ok and r.json()["values"] == nv and nv > 0, f"delete field: {r.json()} values")
with db() as c:
    check(not c.execute("SELECT 1 FROM task_field_values WHERE field_id=?", (FN["id"],)).fetchone(), "values deleted")
check(A.delete(B + f"/api/fields/{FN['id']}").status_code == 404, "deleted field: 404")

# ================= export
ex = A.get(B + "/api/export.json").json()
check(ex["list_fields"] and ex["task_field_values"] and ex["task_deps"] and ex["list_status"], "export: fields, values, dependencies, status history")
check(all(f["list_id"] in {l["id"] for l in ex["lists"]} for f in ex["list_fields"]), "export: only fields of my lists")
exb = Bb.get(B + "/api/export.json").json()
check(not any(f["list_id"] == W for f in exb["list_fields"]), "bob's export: not alice's fields")

# ================= user delete: person values
A.put(B + f"/api/lists/{W}/members", json={"user_id": DAVE, "role": "edit"})
A.patch(B + f"/api/tasks/{t3}", json={"fields": {str(FP["id"]): DAVE}})
check(task(A, t3)["fields"].get(str(FP["id"])) == str(DAVE), "person = dave")
Dv.delete(B + "/api/lists/%d/members/%d" % (W, DAVE))  # dave leaves
check(str(FP["id"]) not in task(A, t3)["fields"], "leaving the list clears the person value too")

# ================= list delete removes its fields; version bump on field changes
v0 = A.get(B + "/api/version").json()["v"]
A.post(B + f"/api/lists/{PR}/fields", json={"name": "Tmp", "type": "text"})
check(A.get(B + "/api/version").json()["v"] > v0, "field changes bump the version")
A.patch(B + f"/api/lists/{PR}", json={"archived": 1})  # 1.5: deleting for good only from the archive
A.delete(B + f"/api/lists/{PR}")
with db() as c:
    check(not c.execute("SELECT 1 FROM list_fields WHERE list_id=?", (PR,)).fetchone(), "deleted list: fields gone")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
