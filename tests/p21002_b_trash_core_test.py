#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1002.0 (#5491, stage 2b of the core's trash; first built in 2.851.0): projects come back / go for good through the core
(core/writes.py obj_restore / obj_purge with the kind's trash rule trash_can = lists/listtrash.py otr_can and its tasks as
children), a task comes back through the core (tasks/lifecycle.py restore_task -> obj_restore checked=True + the hook rt_back
of obj_on_restore). Invented names only.
 - the registration: the kind list carries its trash rule and its tasks as children, the kind task its restore hook
 - a project: restored through the route (form unchanged), rev / updated_by written, the tasks that went with it back (not
   one trashed before), a restore line in its history; a second restore 404; a live project is not deleted from the trash
   route; delete for good: tasks, attachment file and history gone; a kept project 409; the custodian's early delete of a
   kept project with its name still works (through obj_purge)
 - a task of a project in the trash: 409 until the project is back
 - a task comes back through the core (rev / updated_by, its subtask with it); restoring a live task changes nothing
 - sections keep their own trash (copies of the core) and their way back
 - the retention page leaves out the old slots of the runs that went (tasks / lists)
freelancer-matrix: tasks (a person without an organisation: her task comes back through the core, her project comes back
and goes for good; nobody else reaches it)
usage: p21002_b_trash_core_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, DATA, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

fresh(prefix="P21002B")

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
FID, Fr = freelancer(B, A)
UID_A = dbx("SELECT id FROM users WHERE username='alice'")[0][0]


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    check(r.ok, f"setup: task {title} {r.text[:120]}")
    return r.json().get("id")


def plist(s, name):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": None})
    check(r.ok, f"setup: project {name} {r.text[:120]}")
    return r.json().get("id")


def trash(s, tid):
    check(s.delete(B + f"/api/tasks/{tid}").ok, f"setup: task {tid} into the trash")


def list_to_trash(s, lid):
    s.patch(B + f"/api/lists/{lid}", json={"archived": True})
    check(s.delete(B + f"/api/lists/{lid}").ok, f"setup: project {lid} into the trash")


def attach(s, tid):
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": ("note.txt", b"invented content", "text/plain")})
    check(r.ok, "setup: an attachment " + r.text[:120])
    p = (dbx("SELECT path FROM attachments WHERE task_id=?", (tid,)) or [[""]])[0][0]
    return os.path.join(DATA, "attachments", p) if p else ""


def exists(table, rid):
    return bool(dbx(f"SELECT 1 FROM {table} WHERE id=?", (rid,)))


def gone_at(table, rid):
    return dbx(f"SELECT deleted_at FROM {table} WHERE id=?", (rid,))[0][0]


# ---------------------------------------------------------------- the registration
out = in_app("""from kalmido.core.objects import OBJ
from kalmido.core.writes import OBJ_BACK
r = OBJ["list"]
print("LREG", r["trash_can"] is not None, r["children"])
print("TREG", "task" in OBJ_BACK)""")
check("LREG True (('tasks', 'list_id'),)" in out, f"the kind list carries its trash rule and its tasks as children {out[-300:]}")
check("TREG True" in out, f"the kind task has its restore hook (rt_back) {out[-300:]}")

# ---------------------------------------------------------------- a project comes back through the core
L5 = plist(A, "Example Restore Project")
T5 = task(A, L5, "Task of the restored project")
T5X = task(A, L5, "Task trashed before")
trash(A, T5X)
list_to_trash(A, L5)
rev0 = dbx("SELECT rev FROM lists WHERE id=?", (L5,))[0][0]
check(L5 in {x["id"] for x in A.get(B + "/api/trash/lists").json().get("lists", [])}, "the project lies in the trash")
r = A.post(B + f"/api/trash/lists/{L5}/restore")
check(r.ok and r.json() == {"ok": True, "id": L5}, f"the restore route keeps its form {r.status_code} {r.text[:200]}")
row = dbx("SELECT deleted_at, deleted_by, rev, updated_by FROM lists WHERE id=?", (L5,))[0]
check(row[0] is None and row[1] is None and row[2] == rev0 + 1 and row[3] == UID_A, f"the core restored it (rev, updated_by) {row}")
check(gone_at("tasks", T5) is None, "its task came back with it")
check(gone_at("tasks", T5X) is not None, "the task trashed before stays in the trash")
check(dbx("SELECT 1 FROM obj_history WHERE kind='list' AND ref_id=? AND action='restore'", (L5,)), "the restore is in the project's history")
check(L5 in {x["id"] for x in A.get(B + "/api/state").json().get("lists", [])}, "the project is back in the lists (archived)")
check(A.post(B + f"/api/trash/lists/{L5}/restore").status_code == 404, "a second restore: 404 (not in the trash)")
check(A.delete(B + f"/api/trash/lists/{L5}").status_code == 404, "a live project is not deleted for good from the trash route")

# ---------------------------------------------------------------- delete for good through obj_purge
F5 = attach(A, T5)
list_to_trash(A, L5)
r = A.delete(B + f"/api/trash/lists/{L5}")
check(r.ok and r.json() == {"ok": True}, f"the delete route keeps its form {r.status_code} {r.text[:200]}")
check(not exists("lists", L5) and not exists("tasks", T5) and not exists("tasks", T5X), "the project went with its tasks")
check(F5 and not os.path.exists(F5), "its attachment file is gone from disk (after the commit)")
check(not dbx("SELECT 1 FROM obj_history WHERE kind='list' AND ref_id=?", (L5,)), "its history went with it")
check(A.post(B + f"/api/trash/lists/{L5}/restore").status_code == 404, "gone for good: 404")

# ---------------------------------------------------------------- kept by law: no restore; the custodian's early delete stays
L6 = plist(A, "Example Held Project")
T6 = task(A, L6, "Task of the held project")
list_to_trash(A, L6)
dbx("UPDATE lists SET retain_until='2099-12-31' WHERE id=? RETURNING id", (L6,))
r = A.post(B + f"/api/trash/lists/{L6}/restore")
check(r.status_code == 409 and gone_at("lists", L6) is not None, f"a kept project is not restored {r.status_code}")
r = A.delete(B + f"/api/trash/lists/{L6}")
check(r.status_code == 409 and exists("lists", L6), f"a kept project without its name is not deleted {r.status_code}")
r = A.delete(B + f"/api/trash/lists/{L6}", params={"confirm": "Example Held Project"})
check(r.ok and not exists("lists", L6) and not exists("tasks", T6),
      f"the custodian's early delete with the name goes through the core all the same {r.status_code} {r.text[:200]}")

# ---------------------------------------------------------------- a task of a project in the trash waits for its project
L7 = plist(A, "Example Closed Project")
T7 = task(A, L7, "Task of the closed project")
list_to_trash(A, L7)
r = A.post(B + f"/api/tasks/{T7}/restore")
check(r.status_code == 409 and gone_at("tasks", T7) is not None, f"the task of a project in the trash waits for its project {r.status_code}")

# ---------------------------------------------------------------- a task comes back through the core
L8 = plist(A, "Example Task Restore")
T8 = task(A, L8, "Parent to restore")
T8S = task(A, L8, "Its subtask", parent_id=T8)
trash(A, T8)
check(gone_at("tasks", T8S) is not None, "setup: the subtask went with its parent")
rev8 = dbx("SELECT rev FROM tasks WHERE id=?", (T8,))[0][0]
r = A.post(B + f"/api/tasks/{T8}/restore")
row = dbx("SELECT deleted_at, rev, updated_by FROM tasks WHERE id=?", (T8,))[0]
check(r.ok and r.json() == {"ok": True} and row[0] is None and row[1] == rev8 + 1 and row[2] == UID_A,
      f"the task came back through the core (rev, updated_by) {r.status_code} {r.text[:120]} {row}")
check(gone_at("tasks", T8S) is None, "its subtask came back with it (rt_back)")
check(T8 in [t["id"] for t in A.get(B + "/api/state").json().get("tasks", [])], "the task is in the list again")
check(dbx("SELECT 1 FROM activity WHERE task_id=? AND kind='restore'", (T8,)), "the log line of the tasks' area (rt_back)")
r = A.post(B + f"/api/tasks/{T8}/restore")
check(r.ok and dbx("SELECT rev FROM tasks WHERE id=?", (T8,))[0][0] == rev8 + 1, f"restoring a live task changes nothing {r.status_code}")

# ---------------------------------------------------------------- sections keep their own trash (copies of the core)
LS = plist(A, "Example Sections")
r = A.post(B + "/api/sections", json={"list_id": LS, "name": "Example Section"})
check(r.ok, "setup: a section " + r.text[:120])
SID = r.json().get("id")
TS = task(A, LS, "Task in the section", section_id=SID)
check(A.delete(B + f"/api/sections/{SID}").ok, "setup: the section deleted")
r = A.post(B + f"/api/sections/{SID}/restore")
check(r.ok and r.json().get("id") == SID and TS in (r.json().get("moved") or []), f"the section comes back with its task {r.text[:200]}")

# ---------------------------------------------------------------- the retention page: no old slots of the runs that went
dbx("INSERT INTO settings(key, value) VALUES('ret_last_trash.tasks', '{\"at\": \"2026-01-01T00:00:00+00:00\", \"purged\": false, "
    "\"counts\": {\"tasks\": 1}}') ON CONFLICT(key) DO UPDATE SET value=excluded.value RETURNING key")
dbx("INSERT INTO settings(key, value) VALUES('ret_last_trash.obj_trash', '{\"at\": \"2026-01-02T00:00:00+00:00\", \"purged\": false, "
    "\"counts\": {\"task\": 0}}') ON CONFLICT(key) DO NOTHING RETURNING key")
runs = ((A.get(B + "/api/admin/retention").json().get("kinds") or {}).get("trash") or {}).get("runs") or {}
check("obj_trash" in runs and "tasks" not in runs and "lists" not in runs, f"the retention page shows the core's run only {sorted(runs)}")

# ---------------------------------------------------------------- freelancer: her task and her project
FL4 = plist(Fr, "Example Own Tasks")
FT4 = task(Fr, FL4, "Own task to restore")
trash(Fr, FT4)
check(A.post(B + f"/api/tasks/{FT4}/restore").status_code in (403, 404), "freelancer: nobody else restores her task")
r = Fr.post(B + f"/api/tasks/{FT4}/restore")
check(r.ok and gone_at("tasks", FT4) is None and dbx("SELECT updated_by FROM tasks WHERE id=?", (FT4,))[0][0] == FID,
      f"freelancer: her task comes back through the core {r.status_code}")
FL5 = plist(Fr, "Example Own Restore")
FT5 = task(Fr, FL5, "Own task of the restored project")
list_to_trash(Fr, FL5)
check(FL5 in {x["id"] for x in Fr.get(B + "/api/trash/lists").json().get("lists", [])}, "freelancer: her project lies in her trash")
check(A.post(B + f"/api/trash/lists/{FL5}/restore").status_code == 404, "freelancer: nobody else restores it")
r = Fr.post(B + f"/api/trash/lists/{FL5}/restore")
check(r.ok and gone_at("tasks", FT5) is None, f"freelancer: her project comes back {r.status_code}")
check(FL5 in {x["id"] for x in Fr.get(B + "/api/state").json().get("lists", [])}, "freelancer: back in her lists")
list_to_trash(Fr, FL5)
check(A.delete(B + f"/api/trash/lists/{FL5}").status_code == 404, "freelancer: nobody else deletes it")
check(Fr.delete(B + f"/api/trash/lists/{FL5}").ok and not exists("lists", FL5) and not exists("tasks", FT5),
      "freelancer: she deletes it for good")

sys.exit(done("p21002_b_trash_core"))
