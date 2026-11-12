#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1028.0 (#5536, stage 2c of the core's trash): tasks go for good through the core -- DELETE /api/tasks/<id>?hard=1,
"Empty trash" (DELETE /api/trash) run core/writes.py obj_purge(checked=True) per task (tasks/lifecycle.py tre_purge inside
tasks/tasktrash.py ttp_manual), so the core's rows of the task (obj_history / obj_undo of the kind task) go with it; before,
the routes' own hard_delete left them behind. Invented names only.
 - ?hard=1 of a task in the trash: the task, its subtask, its attachment file and its core rows are gone
 - ?hard=1 of a live task still works (it goes into the trash first, then for good)
 - "Empty trash": both trashed tasks gone with their core rows, the live one stays
 - a project kept by law: ?hard=1 409 with its date, the task stays (the core's hook decides, no route check any more)
 - nobody else deletes a person's task for good
freelancer-matrix: tasks (a person without an organisation deletes her tasks for good and empties her trash)
usage: p21028_a_task_purge_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, DATA, check, dbx, done, fresh, sess  # noqa: E402

fresh(prefix="P21028A")

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
FID, Fr = freelancer(B, A)


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


def attach(s, tid):
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": ("note.txt", b"invented content", "text/plain")})
    check(r.ok, "setup: an attachment " + r.text[:120])
    p = (dbx("SELECT path FROM attachments WHERE task_id=?", (tid,)) or [[""]])[0][0]
    return os.path.join(DATA, "attachments", p) if p else ""


def core_row(tid):
    """A row of the core's history of the kind task (as an area's write of it would leave)."""
    dbx("INSERT INTO obj_history(kind, ref_id, action, created_at, updated_at) VALUES('task', ?, 'update', "
        "'2026-11-01T10:00:00+00:00', '2026-11-01T10:00:00+00:00')", (tid,))


def core_rows(tid):
    return dbx("SELECT COUNT(*) FROM obj_history WHERE kind='task' AND ref_id=?", (tid,))[0][0] + \
        dbx("SELECT COUNT(*) FROM obj_undo WHERE kind='task' AND ref_id=?", (tid,))[0][0]


def exists(tid):
    return bool(dbx("SELECT 1 FROM tasks WHERE id=?", (tid,)))


# ---------------------------------------------------------------- ?hard=1 of a task in the trash (a person without an organisation)
FL = plist(Fr, "Example Freelance Project")
T1 = task(Fr, FL, "Example parent task")
T1S = task(Fr, FL, "Example subtask", parent_id=T1)
path = attach(Fr, T1)
check(path and os.path.exists(path), "setup: the attachment lies on disk")
trash(Fr, T1)
core_row(T1)
check(core_rows(T1) >= 1, "setup: the task has a row of the core")
check(A.delete(B + f"/api/tasks/{T1}?hard=1").status_code in (403, 404) and exists(T1), "nobody else deletes her task for good")
r = Fr.delete(B + f"/api/tasks/{T1}?hard=1")
check(r.ok, f"freelancer: ?hard=1 of her task in the trash {r.status_code} {r.text[:200]}")
check(not exists(T1) and not exists(T1S), "freelancer: the task and its subtask are gone")
check(core_rows(T1) == 0, "freelancer: the core's rows of the task went with it (obj_purge, not the area's own delete)")
check(not os.path.exists(path), "freelancer: the attachment file is gone after the commit")

# ---------------------------------------------------------------- ?hard=1 of a live task
T2 = task(Fr, FL, "Example live task")
r = Fr.delete(B + f"/api/tasks/{T2}?hard=1")
check(r.ok and not exists(T2), f"freelancer: ?hard=1 of a live task still deletes it for good {r.status_code} {r.text[:200]}")

# ---------------------------------------------------------------- "Empty trash"
T3, T4, T5 = (task(Fr, FL, f"Example trash task {i}") for i in (3, 4, 5))
trash(Fr, T3)
trash(Fr, T4)
core_row(T3)
r = Fr.delete(B + "/api/trash")
check(r.ok and r.json().get("deleted") == 2, f"freelancer: Empty trash names two {r.status_code} {r.text[:200]}")
check(not exists(T3) and not exists(T4) and core_rows(T3) == 0, "freelancer: both trashed tasks gone with their core rows")
check(exists(T5), "freelancer: the live task stays")

# ---------------------------------------------------------------- a project kept by law keeps its task
AL = plist(A, "Example Held Project")
T6 = task(A, AL, "Example held task")
trash(A, T6)
dbx("UPDATE lists SET retain_until='2099-12-31' WHERE id=?", (AL,))
r = A.delete(B + f"/api/tasks/{T6}?hard=1")
check(r.status_code == 409 and "2099-12-31" in r.text and exists(T6), f"kept by law: 409 with its date, the task stays {r.status_code} {r.text[:200]}")
r = A.delete(B + "/api/trash")
check(r.ok and r.json().get("kept_law") == 1 and exists(T6), f"kept by law: Empty trash leaves it and counts it {r.text[:200]}")
dbx("UPDATE lists SET retain_until='2020-12-31' WHERE id=?", (AL,))
check(A.delete(B + f"/api/tasks/{T6}?hard=1").ok and not exists(T6), "after the period: deleted for good")

sys.exit(done("p21028_a_task_purge"))
