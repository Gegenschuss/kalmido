#!/usr/bin/env python3
"""Package D4 API tests (fresh DB on the TEST container :3048): what the undo / redo history needs from the server.
POST /api/tasks/batch: patch_each reports conflicts per task and field (title, priority, tags, custom field values by
id) and applies the rest in one transaction, complete with expect (date moved elsewhere / already done), reopen with
signed undo payloads (undo completes it again), undo that meets a change, delete with a guard (someone else changed the
task after a time; my own changes do not count), the server time; sections: create at a given place with its old tasks
(only tasks of that list without a section), rename / order / delete with the expected state (_prev), delete answers the
section and its tasks; lists: PATCH with _prev (owner and member fields), reorder with _prev (order, folders); and the
rights: view-only members change nothing, nobody moves tasks of another list into a section."""
import os, sqlite3, sys, time
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


def row(tid):
    with db() as c:
        return dict(c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())


def fval(tid, fid):
    with db() as c:
        r = c.execute("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (tid, fid)).fetchone()
        return r[0] if r else None


def tags(s, tid):
    return next(t for t in s.get(B + "/api/state").json()["tasks"] if t["id"] == tid)["tags"]


D = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
Bb, Cc = sess("bob"), sess("carol")
A.patch(B + "/api/settings", json={"features": "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields"})
L = A.post(B + "/api/lists", json={"name": "Office", "kind": "project"}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Private"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"})
A.put(B + f"/api/lists/{L}/members", json={"user_id": CAROL, "role": "view"})
FLD = A.post(B + f"/api/lists/{L}/fields", json={"name": "Budget", "type": "text"}).json()["id"]
mk = lambda s, **b: s.post(B + "/api/tasks", json=b).json()["id"]  # noqa: E731
batch = lambda s, action, ids, data=None: s.post(B + "/api/tasks/batch", json={"ids": ids, "action": action, "data": data or {}})  # noqa: E731

# ================= patch_each: conflicts per task and field, the rest applied (one transaction)
t1 = mk(A, title="Invoice", list_id=L, priority=1, tags=["a"])
t2 = mk(A, title="Letter", list_id=L)
A.patch(B + f"/api/tasks/{t1}", json={"fields": {str(FLD): "100"}})
Bb.patch(B + f"/api/tasks/{t1}", json={"priority": 5, "fields": {str(FLD): "300"}})  # bob, in between
items = {str(t1): {"title": "Invoice 2", "priority": 3, "tags": ["b"], "fields": {str(FLD): "200"},
                   "_prev": {"title": "Invoice", "priority": 1, "tags": ["a"], "fields": {str(FLD): "100"}}},
         str(t2): {"title": "Letter 2", "_prev": {"title": "Letter"}}}
r = batch(A, "patch_each", [t1, t2], {"items": items})
j = r.json()
check(r.ok and j["count"] == 2 and j.get("now"), f"patch_each answers count + server time {j}")
cf = {(c["id"], c["field"]) for c in j["conflicts"]}
check(cf == {(t1, "priority"), (t1, f"field:{FLD}")}, f"conflicts: priority + custom field of t1 {cf}")
check(next(c for c in j["conflicts"] if c["field"] == "priority")["server"] == 5 and j["conflicts"][0]["title"] == "Invoice", "conflict carries the server value and the title")
r1, r2 = row(t1), row(t2)
check(r1["priority"] == 5 and fval(t1, FLD) == "300", "the values changed elsewhere stay")
check(r1["title"] == "Invoice 2" and tags(A, t1) == ["b"] and r2["title"] == "Letter 2", "the other fields and tasks are applied")
# a value already equal to the target is no conflict (idempotent redo)
r = batch(A, "patch_each", [t2], {"items": {str(t2): {"title": "Letter 2", "_prev": {"title": "Letter"}}}}).json()
check(r["conflicts"] == [], "target value already there: no conflict")
# fields _prev only for fields that are sent
r = batch(A, "patch_each", [t1], {"items": {str(t1): {"fields": {str(FLD): "400"}, "_prev": {"fields": {str(FLD): "300", "999": "x"}}}}}).json()
check(r["conflicts"] == [] and fval(t1, FLD) == "400", "custom field with a matching _prev applied")
# PATCH /api/tasks/<id> reports field conflicts too
r = A.patch(B + f"/api/tasks/{t1}", json={"fields": {str(FLD): "500"}, "_prev": {"fields": {str(FLD): "1"}}}).json()
check([c["field"] for c in r["conflicts"]] == [f"field:{FLD}"] and fval(t1, FLD) == "400", "PATCH: custom field conflict")

# ================= complete with expect, reopen with undo payloads
rc = mk(A, title="Weekly", list_id=L, due=D(0), repeat="FREQ=WEEKLY")
r = batch(A, "complete", [rc], {"expect": {str(rc): D(-1)}}).json()
check(r["count"] == 0 and r["conflicts"][0]["field"] == "due" and row(rc)["due"] == D(0), "complete: date moved elsewhere -> not completed")
r = batch(A, "complete", [rc], {"expect": {str(rc): D(0)}}).json()
check(r["count"] == 1 and row(rc)["due"] == D(7) and str(rc) in r["undo"], "complete with the expected date: advanced, undo payload")
tok = r["undo"]
r = batch(A, "undo", [rc], {"items": tok}).json()
check(r["count"] == 1 and row(rc)["due"] == D(0), "undo completion: back to its date")
r = batch(A, "undo", [rc], {"items": tok}).json()
check(r["count"] == 0 and r["conflicts"][0]["field"] == "status", "the same undo twice: reported as a conflict")
tc = mk(A, title="Done thing", list_id=L)
batch(A, "complete", [tc])
r = batch(A, "complete", [tc], {"expect": {str(tc): None}}).json()
check(r["count"] == 0 and r["conflicts"][0]["field"] == "status", "redo complete of a task done elsewhere: conflict")
r = batch(A, "reopen", [tc]).json()
check(r["count"] == 1 and row(tc)["status"] == 0 and r["undo"][str(tc)]["op"] == "reopen" and r["undo"][str(tc)]["sig"], "batch reopen returns a signed undo payload")
r = batch(A, "undo", [tc], {"items": r["undo"]}).json()
check(r["count"] == 1 and row(tc)["status"] == 2, "undo of the reopen completes it again")
forged = {str(tc): {"op": "reopen", "status": 2, "sig": "x"}}
check(batch(A, "undo", [tc], {"items": forged}).json()["count"] == 0, "forged undo payload refused")

# ================= delete guard: someone else changed it after the given time
tg = mk(A, title="Guarded", list_id=L)
since = batch(A, "restore", [tg]).json()["now"]
time.sleep(0.05)
A.patch(B + f"/api/tasks/{tg}", json={"priority": 3})  # my own change: does not block
r = batch(A, "delete", [tg], {"guard": {str(tg): since}}).json()
check(r["count"] == 1 and row(tg)["deleted_at"], "guard: my own changes do not block")
since = batch(A, "restore", [tg]).json()["now"]
time.sleep(0.05)
Bb.patch(B + f"/api/tasks/{tg}", json={"title": "Guarded!"})
r = batch(A, "delete", [tg], {"guard": {str(tg): since}}).json()
check(r["count"] == 0 and r["conflicts"][0]["field"] == "changed" and row(tg)["deleted_at"] is None, "guard: bob's change after the time blocks the trash")
r = batch(A, "delete", [tg], {"guard": {str(tg): "2000-01-01T00:00:00+00:00"}}).json()
check(r["count"] == 0, "guard from long ago: bob's change counts")
check(batch(A, "delete", [tg], {"guard": {str(tg): "yesterday"}}).status_code == 400, "invalid guard: 400")
check(batch(A, "patch_each", [tg], "nope").status_code == 400 and batch(A, "patch", ["x"]).status_code == 400, "invalid data / ids: 400")

# ================= rights: view-only members change nothing
r = batch(Cc, "patch_each", [t2], {"items": {str(t2): {"title": "carol was here", "_prev": {"title": "Letter 2"}}}}).json()
check(r["count"] == 0 and r["errors"] and row(t2)["title"] == "Letter 2", "view-only: patch_each refused")
check(batch(Cc, "delete", [t2]).json()["count"] == 0 and row(t2)["deleted_at"] is None, "view-only: delete refused")
tp = mk(A, title="Private one", list_id=L2)
r = batch(Bb, "patch_each", [tp], {"items": {str(tp): {"title": "x"}}}).json()
check(r["count"] == 0 and row(tp)["title"] == "Private one", "no access: nothing changed")

# ================= sections
S1 = A.post(B + "/api/sections", json={"list_id": L, "name": "Doing"}).json()["id"]
S2 = A.post(B + "/api/sections", json={"list_id": L, "name": "Done"}).json()["id"]
A.patch(B + f"/api/tasks/{t1}", json={"section_id": S1})
A.patch(B + f"/api/tasks/{t2}", json={"section_id": S1})
r = A.delete(B + f"/api/sections/{S1}").json()
check(r["ok"] and r["section"]["name"] == "Doing" and sorted(r["tasks"]) == sorted([t1, t2]), "delete answers the section and its tasks")
check(row(t1)["section_id"] is None, "its tasks stay without a section")
A.patch(B + f"/api/tasks/{t2}", json={"section_id": S2})  # moved elsewhere meanwhile
r = A.post(B + "/api/sections", json={"list_id": L, "name": "Doing", "sort": r["section"]["sort"], "tasks": [t1, t2, tp]}).json()
S1b = r["id"]
check(r["moved"] == [t1] and sorted(r["skipped"]) == sorted([t2, tp]), f"re-created: only its free tasks move back {r['moved']} {r['skipped']}")
check(row(t1)["section_id"] == S1b and row(t2)["section_id"] == S2 and row(tp)["section_id"] is None, "tasks: back / left alone / other list untouched")
with db() as c:
    order = [x[0] for x in c.execute("SELECT id FROM sections WHERE list_id=? ORDER BY sort, id", (L,))]
check(order == [S1b, S2], "at its old place (sort)")
check(A.post(B + "/api/sections", json={"list_id": L, "name": "X", "tasks": "all"}).status_code == 400, "tasks must be a list of ids")
check(A.post(B + "/api/sections", json={"list_id": L, "name": "X", "sort": "nan"}).status_code == 400, "sort must be a number")
check(Cc.post(B + "/api/sections", json={"list_id": L, "name": "Carol"}).status_code == 403, "view-only: no new section")
BL = Bb.post(B + "/api/lists", json={"name": "Bob's"}).json()["id"]
r = Bb.post(B + "/api/sections", json={"list_id": BL, "name": "Grab", "tasks": [tp, t1]}).json()
check(r["moved"] == [] and row(tp)["section_id"] is None and row(t1)["section_id"] == S1b, "nobody pulls tasks of another list into a section")
# rename with the expected name
r = A.patch(B + f"/api/sections/{S1b}", json={"name": "Open", "_prev": {"name": "Doing"}}).json()
check(r["ok"] and r["conflicts"] == [], "rename with the expected name")
Bb.patch(B + f"/api/sections/{S1b}", json={"name": "Bob's name"})
r = A.patch(B + f"/api/sections/{S1b}", json={"name": "Doing", "_prev": {"name": "Open"}}).json()
with db() as c:
    nm = c.execute("SELECT name FROM sections WHERE id=?", (S1b,)).fetchone()[0]
check(r["conflicts"] and nm == "Bob's name", "rename meets a change elsewhere: stays")
check(A.patch(B + f"/api/sections/{S1b}", json={"name": "  "}).status_code == 400, "empty name refused")
# order with the expected order
r = A.post(B + f"/api/lists/{L}/sections/order", json={"ids": [S2, S1b], "_prev": [S1b, S2]}).json()
check(r["ok"] and r["prev"] == [S1b, S2], "order with the expected order")
r = A.post(B + f"/api/lists/{L}/sections/order", json={"ids": [S2, S1b], "_prev": [S1b, S2]}).json()
check(r["ok"] is False and r["conflicts"][0]["field"] == "order", "order changed meanwhile: conflict, nothing changes")
S3 = A.post(B + "/api/sections", json={"list_id": L, "name": "New"}).json()["id"]
r = A.post(B + f"/api/lists/{L}/sections/order", json={"ids": [S1b, S2], "_prev": [S2, S1b]})
check(r.status_code == 200 and r.json()["ok"] is False, "a section added meanwhile: conflict (not 400)")
check(A.post(B + f"/api/lists/{L}/sections/order", json={"ids": [S1b, S2]}).status_code == 400, "without _prev: the old strict check")
# delete with the expected state
r = A.delete(B + f"/api/sections/{S3}", json={"_prev": {"name": "New", "tasks": [t2]}}).json()
check(r["ok"] is False and r["conflicts"], "delete: tasks differ -> conflict")
r = A.delete(B + f"/api/sections/{S3}", json={"_prev": {"name": "Other", "tasks": []}}).json()
check(r["ok"] is False, "delete: name differs -> conflict")
r = A.delete(B + f"/api/sections/{S3}", json={"_prev": {"name": "New", "tasks": []}}).json()
check(r["ok"] is True and r["tasks"] == [], "delete with the expected (empty) state")
check(Cc.delete(B + f"/api/sections/{S2}").status_code == 403, "view-only: no delete")

# ================= lists: settings and order with _prev
r = A.patch(B + f"/api/lists/{L2}", json={"name": "Home", "color": "#f87171", "_prev": {"name": "Private", "color": ""}}).json()
with db() as c:
    l2 = dict(c.execute("SELECT * FROM lists WHERE id=?", (L2,)).fetchone())
check(r["ok"] and r["conflicts"] == [] and l2["name"] == "Home" and l2["color"] == "#f87171", "list PATCH with the expected values")
with db() as c:
    c.execute("UPDATE lists SET color='#6d8cff' WHERE id=?", (L2,))
r = A.patch(B + f"/api/lists/{L2}", json={"name": "Private", "color": "", "_prev": {"name": "Home", "color": "#f87171"}}).json()
with db() as c:
    l2 = dict(c.execute("SELECT * FROM lists WHERE id=?", (L2,)).fetchone())
check([c["field"] for c in r["conflicts"]] == ["color"] and l2["color"] == "#6d8cff" and l2["name"] == "Private", "changed colour stays, the name is undone")
r = A.patch(B + f"/api/lists/{L}", json={"kind": "list", "rate": 50, "_prev": {"kind": "project", "rate": None}}).json()
with db() as c:
    l1 = dict(c.execute("SELECT * FROM lists WHERE id=?", (L,)).fetchone())
check(r["conflicts"] == [] and l1["kind"] == "list" and l1["rate"] == 50, "type + hourly rate")
A.patch(B + f"/api/lists/{L}", json={"kind": "project"})
r = Bb.patch(B + f"/api/lists/{L}", json={"folder": "Work", "_prev": {"folder": ""}}).json()
check(r["conflicts"] == [], "member: own folder with _prev")
r = Bb.patch(B + f"/api/lists/{L}", json={"folder": "", "_prev": {"folder": "Elsewhere"}}).json()
with db() as c:
    mf = c.execute("SELECT folder FROM list_members WHERE list_id=? AND user_id=?", (L, BOB)).fetchone()[0]
check([c["field"] for c in r["conflicts"]] == ["folder"] and mf == "Work", "member: folder changed meanwhile stays")
check(Bb.patch(B + f"/api/lists/{L}", json={"name": "x", "_prev": {"name": "Office"}}).status_code == 403, "member: owner fields still refused")
st = A.get(B + "/api/state").json()
cur = [x["id"] for x in sorted((x for x in st["lists"] if not x["is_inbox"]), key=lambda x: (x["sort"] or 0, x["id"]))]
new = list(reversed(cur))
r = A.post(B + "/api/lists/reorder", json={"ids": new, "folder": {str(L2): "Private"}, "_prev": {"ids": cur, "folder": {str(L2): ""}}}).json()
st = A.get(B + "/api/state").json()
now = [x["id"] for x in sorted((x for x in st["lists"] if not x["is_inbox"]), key=lambda x: (x["sort"] or 0, x["id"]))]
check(r["conflicts"] == [] and now == new and next(x for x in st["lists"] if x["id"] == L2)["folder"] == "Private", "reorder + folder with _prev")
r = A.post(B + "/api/lists/reorder", json={"ids": cur, "folder": {str(L2): ""}, "_prev": {"ids": cur, "folder": {str(L2): "Other"}}}).json()
st = A.get(B + "/api/state").json()
now2 = [x["id"] for x in sorted((x for x in st["lists"] if not x["is_inbox"]), key=lambda x: (x["sort"] or 0, x["id"]))]
check({c["field"] for c in r["conflicts"]} == {"order", "folder"} and now2 == new and next(x for x in st["lists"] if x["id"] == L2)["folder"] == "Private",
      "reorder: order and folder changed meanwhile -> both stay")
check(A.post(B + "/api/lists/reorder", json={"ids": cur, "_prev": {"ids": ["x"]}}).status_code == 400, "reorder: bad _prev ids -> 400")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
