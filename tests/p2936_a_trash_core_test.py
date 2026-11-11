#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.936.0 (#5364, stage 2a of the core's trash; first built in 2.817.0 / 2.851.0): tasks and projects (lists) lie in their
areas' trash as before, but their trash period is the ONE retention run of the core (core/writes.py obj_trash_tick / obj_trash_prune with
obj_register trash_keep and the hooks obj_on_purge: kind task -> tasks/tasktrash.py ttp_core_purge, kind list ->
lists/listtrash.py otr_core_purge). Invented names only.
 - the registration: both kinds with trash_prune and their hooks; the light kind task still has no write path of the core
   (obj_trash 404); the old runs (ttp_tick, otr_prune) are gone
 - switch off: the tick counts (task / task_kept / list / list_kept), nothing goes
 - switch on: an old task goes with its subtask and its attachment file on disk, a young one stays, a task of a project kept
   by law stays; an old project goes with its tasks, a young one stays, a kept one waits
 - the ids way checks again under the lock: a live task and a young one in the trash are never deleted for good
 - the routes keep their form: the young task / project come back through POST /api/tasks/<id>/restore and
   POST /api/trash/lists/<id>/restore, GET /api/trash/lists answers as before
freelancer-matrix: tasks (a person without an organisation: her old task and old project go after the period, a young one
comes back)
 - a subtask that went with its parent in the same run counts as deleted (the run's number is what went)
 - a hook that fails is an error the watchdog hears of (<kind>_err, the run raises after its commit), not a quiet lock,
   and it holds back no other kind (one savepoint per kind)
usage: p2936_a_trash_core_test.py <datadir>"""
import json
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, DATA, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import in_app  # noqa: E402

fresh(prefix="P2936A")
OLD = "2020-01-02T03:04:05+00:00"

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


def list_to_trash(s, lid):
    s.patch(B + f"/api/lists/{lid}", json={"archived": True})
    check(s.delete(B + f"/api/lists/{lid}").ok, f"setup: project {lid} into the trash")


def age_task(tid):
    dbx("UPDATE tasks SET deleted_at=? WHERE (id=? OR parent_id=?) AND deleted_at IS NOT NULL RETURNING id", (OLD, tid, tid))


def age_list(lid):
    dbx("UPDATE lists SET deleted_at=? WHERE id=? RETURNING id", (OLD, lid))
    dbx("UPDATE tasks SET deleted_at=? WHERE list_id=? AND deleted_at IS NOT NULL RETURNING id", (OLD, lid))


def attach(s, tid):
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": ("note.txt", b"invented content", "text/plain")})
    check(r.ok, "setup: an attachment " + r.text[:120])
    p = (dbx("SELECT path FROM attachments WHERE task_id=?", (tid,)) or [[""]])[0][0]
    return os.path.join(DATA, "attachments", p) if p else ""


def exists(table, rid):
    return bool(dbx(f"SELECT 1 FROM {table} WHERE id=?", (rid,)))


def kind_run(purge, kinds=("list", "task")):
    """The core's retention run of these kinds (as obj_trash_tick does it, the switch given) -> {kind: n}."""
    out = in_app(f"""from kalmido.core.writes import obj_purge_after, obj_trash_prune
from kalmido.core.serializers import unlink_files
got = {{}}
with obj_purge_after(keep_locked=True) as box:
    for k in {list(kinds)!r}:
        got[k] = obj_trash_prune(c, k, purge={bool(purge)!r})
c.commit()
unlink_files(box["after"])
import json
print("RUN", json.dumps(got))""")
    line = next((x for x in out.splitlines() if x.startswith("RUN ")), "")
    check(line, f"the run works {out[-600:]}")
    return json.loads(line[4:]) if line else {}


# ---------------------------------------------------------------- the registration
out = in_app("""from kalmido.core.objects import OBJ
from kalmido.core.writes import OBJ_PURGE, obj_trash
import kalmido.tasks.tasktrash as tt, kalmido.lists.listtrash as lt
for k in ("task", "list"):
    r = OBJ[k]
    print("REG", k, r["trash_prune"], k in OBJ_PURGE, r["trash_keep"] is not None)
print("OLD", hasattr(tt, "ttp_tick"), hasattr(lt, "otr_prune"))
try:
    obj_trash(c, 1, "task", 1)
    print("TRASHED")
except Denied as e:
    print("DENIED", e.code)""")
check("REG task True True True" in out and "REG list True True True" in out, f"both kinds hand their trash period to the core {out[-400:]}")
check("OLD False False" in out, f"the areas' own runs are gone {out[-300:]}")
check("DENIED 404" in out and "TRASHED" not in out, f"the light kind task still has no write path of the core {out[-300:]}")

# ---------------------------------------------------------------- tasks
LA = plist(A, "Example Workshop")
T_OLD = task(A, LA, "Old task")
T_SUB = task(A, LA, "Its subtask", parent_id=T_OLD)
F_OLD = attach(A, T_OLD)
T_YOUNG = task(A, LA, "Young task")
T_LIVE = task(A, LA, "Live task")
LK = plist(A, "Example Archive")  # a project kept by law with an old task in the trash
T_KEPT = task(A, LK, "Kept task")
trash(A, T_OLD)
trash(A, T_YOUNG)
trash(A, T_KEPT)
age_task(T_OLD)
age_task(T_KEPT)
dbx("UPDATE lists SET retain_until='2099-12-31' WHERE id=? RETURNING id", (LK,))
check(dbx("SELECT deleted_at FROM tasks WHERE id=?", (T_SUB,))[0][0] == OLD, "setup: the subtask went with its parent")

# ---------------------------------------------------------------- projects
L_OLD = plist(A, "Example Old Project")
T_LO = task(A, L_OLD, "Task of the old project")
L_YOUNG = plist(A, "Example Young Project")
L_KEPT = plist(A, "Example Kept Project")
for lid in (L_OLD, L_YOUNG, L_KEPT):
    list_to_trash(A, lid)
age_list(L_OLD)
age_list(L_KEPT)
dbx("UPDATE lists SET retain_until='2099-12-31' WHERE id=? RETURNING id", (L_KEPT,))

# ---------------------------------------------------------------- switch off: the tick counts, nothing goes
out = in_app("""from kalmido.core.writes import obj_trash_tick
n = obj_trash_tick(c, force=True)
print("TICK", sorted((k, v) for k, v in n.items() if k in ("task", "task_kept", "list", "list_kept")))""")
# due tasks: T_OLD + T_SUB + the old project's task; kept: T_KEPT; projects: L_OLD due, L_KEPT kept
check("TICK [('list', 1), ('list_kept', 1), ('task', 3), ('task_kept', 1)]" in out, f"switch off: counted, kept apart {out[-500:]}")
check(all(exists("tasks", t) for t in (T_OLD, T_SUB, T_YOUNG, T_KEPT, T_LO)) and exists("lists", L_OLD) and F_OLD and os.path.isfile(F_OLD),
      "switch off: nothing deleted")
last = dbx("SELECT value FROM settings WHERE key='ret_last_trash.obj_trash'")
check(last and '"task": 3' in last[0][0] and '"purged": false' in last[0][0], f"reported for the retention page {last}")

# ---------------------------------------------------------------- the ids way checks again under the lock
out = in_app(f"""from kalmido.core.writes import obj_trash_prune
print("IDS", obj_trash_prune(c, "task", purge=True, ids=[{T_LIVE}, {T_YOUNG}, {T_KEPT}]))
c.commit()""")
check("IDS 0" in out and exists("tasks", T_LIVE) and exists("tasks", T_YOUNG) and exists("tasks", T_KEPT),
      f"ids way: a live, a young and a kept task stay {out[-300:]}")

# ---------------------------------------------------------------- switch on
n = kind_run(True)
check(n.get("list") == 1, f"switch on: the old project goes {n}")
check(not exists("lists", L_OLD) and not exists("tasks", T_LO), "the old project went with its task")
check(exists("lists", L_YOUNG) and exists("lists", L_KEPT), "the young project and the kept one stay in the trash")
check(not exists("tasks", T_OLD) and not exists("tasks", T_SUB), f"the old task went with its subtask {n}")
check(n.get("task") == 2, f"the subtask that went with its parent counts as deleted (T_OLD + T_SUB) {n}")
check(F_OLD and not os.path.exists(F_OLD), "its attachment file is gone from disk (after the commit)")
check(exists("tasks", T_YOUNG) and exists("tasks", T_KEPT) and exists("tasks", T_LIVE), "young, kept and live tasks stay")
n = kind_run(True)
check(n == {"list": 0, "task": 0}, f"a second run finds nothing {n}")

# ---------------------------------------------------------------- the routes keep their form
j = A.get(B + "/api/trash/lists").json()
ids = {x["id"] for x in j.get("lists", [])}
check({L_YOUNG, L_KEPT} <= ids and L_OLD not in ids and j.get("days") == 30, f"the projects' trash as before {sorted(ids)} {j.get('days')}")
r = A.post(B + f"/api/trash/lists/{L_YOUNG}/restore")
check(r.ok and r.json().get("id") == L_YOUNG and dbx("SELECT deleted_at FROM lists WHERE id=?", (L_YOUNG,))[0][0] is None,
      f"the young project comes back {r.status_code} {r.text[:200]}")
r = A.post(B + f"/api/tasks/{T_YOUNG}/restore")
check(r.ok and dbx("SELECT deleted_at FROM tasks WHERE id=?", (T_YOUNG,))[0][0] is None, f"the young task comes back {r.status_code}")
check(T_YOUNG not in [t["id"] for t in A.get(B + "/api/tasks?scope=trash").json().get("tasks", [])], "the restored task left the trash view")

# ---------------------------------------------------------------- freelancer: the same period for a private space
FL = plist(Fr, "Example Own Work")
FT_OLD = task(Fr, FL, "Own old task")
FT_YOUNG = task(Fr, FL, "Own young task")
trash(Fr, FT_OLD)
trash(Fr, FT_YOUNG)
age_task(FT_OLD)
FL_OLD = plist(Fr, "Example Own Old Project")
task(Fr, FL_OLD, "Own task of the old project")
list_to_trash(Fr, FL_OLD)
age_list(FL_OLD)
n = kind_run(True)
check(n.get("task", 0) >= 1 and n.get("list") == 1 and not exists("tasks", FT_OLD) and not exists("lists", FL_OLD),
      f"freelancer: the old task and the old project go {n}")
j = Fr.get(B + "/api/tasks?scope=trash").json()
check([t["id"] for t in j.get("tasks", [])] == [FT_YOUNG] and j.get("days") == 30, f"freelancer: the young one stays in the trash {j.get('days')}")
check(Fr.post(B + f"/api/tasks/{FT_YOUNG}/restore").ok and dbx("SELECT deleted_at FROM tasks WHERE id=?", (FT_YOUNG,))[0][0] is None,
      "freelancer: the young task comes back")


# ---------------------------------------------------------------- a failing hook is an error the watchdog hears of (raised
# after the commit, <kind>_err), not a quiet lock -- and it holds back no other kind
LE = plist(A, "Example Error Project")
list_to_trash(A, LE)
age_list(LE)
LT = plist(A, "Example Error Tasks")
TE = task(A, LT, "Task whose hook fails")
trash(A, TE)
age_task(TE)
out = in_app("""import os, json
os.environ["KALMIDO_PURGE_TRASH"] = "1"
from kalmido.core import writes
def boom(c, rid):
    raise ValueError("example failure")
writes.OBJ_PURGE["task"] = boom
try:
    writes.obj_trash_tick(c, force=True)
    print("NORAISE")
except RuntimeError as e:
    print("RAISED", str(e))
last = c.execute("SELECT value FROM settings WHERE key='ret_last_trash.obj_trash'").fetchone()
print("LAST", last[0] if last else "")""")
check("RAISED core trash run: task " in out and "NORAISE" not in out, f"the run raises for the watchdog after its commit {out[-400:]}")
check('"task_err": 1' in out and '"task_locked"' not in out, f"counted as an error, not as locked {out[-400:]}")
check(exists("tasks", TE) and not exists("lists", LE), "the failing task stays, the project of the other kind went all the same")

sys.exit(done("p2936_a_trash_core"))
