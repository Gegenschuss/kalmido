#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.774.0 (#5251): undo across devices, stage 3 -- the tasks' steps on the server (diff parts, kalmido/tasks/tundo.py).
Invented names only.
 - creating, editing (PATCH), multi-select (batch patch), dragging (reorder), completing (also a recurring task), reopening,
   the trash and restoring each record ONE step group of the person (area tasks, kind task, mode diff, only the changed
   fields), labelled with the task's title or the number of tasks
 - POST /api/undo/to/<id> takes it back through the tasks' own write path: a field someone else changed since stays (named,
   the group partial), the other fields go back; redo brings it forward again; the undo itself records no new step
 - a task of a batch that failed (locked) records nothing
 - sections: rename / limits and the order of a project's sections are steps too
 - another person's group: 404; a viewer-only member's groups are never written (no write)
tenant-matrix: undo (another person's task step: not listed, 404)
freelancer-matrix: undo (a person without an organisation: her task step listed, taken back, redone)
usage: p2774_a_task_undo_test.py <datadir>"""
import json
import os
import sys
from datetime import timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, dbx, done, sess, today  # noqa: E402

kt.fresh(prefix="P2774A")
A = kt.setup()
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "de"})
AL = A.get(B + "/api/state").json()["me"]["id"]
L = A.post(B + "/api/lists", json={"name": "Garden", "kind": "project"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"})
D = lambda n: (today() + timedelta(days=n)).isoformat()  # noqa: E731


def mk(s, **b):
    r = s.post(B + "/api/tasks", json={"list_id": L, **b})
    assert r.ok, r.text[:300]
    return r.json()["id"]


def task(tid):
    r = dbx("SELECT title, priority, status, due, deleted_at, section_id, sort FROM tasks WHERE id=?", (tid,))
    return dict(zip(("title", "priority", "status", "due", "deleted_at", "section_id", "sort"), r[0])) if r else None


def last(u):
    r = dbx("SELECT id, state, parts, area, label_key, label_args FROM undo_groups WHERE user_id=? ORDER BY id DESC LIMIT 1", (u,))
    return dict(zip(("id", "state", "parts", "area", "label_key", "label_args"), r[0])) if r else {}


def ngroups(u):
    return dbx("SELECT COUNT(*) FROM undo_groups WHERE user_id=?", (u,))[0][0]


def parts(gid):
    return [(k, rid, mode, json.loads(snap)) for k, rid, mode, snap in
            dbx("SELECT kind, ref_id, mode, snap FROM obj_undo WHERE group_id=? ORDER BY id", (gid,))]


def undo(s, gid):
    r = s.post(B + f"/api/undo/to/{gid}")
    return r.json() if r.ok else r.status_code


def redo(s, gid):
    r = s.post(B + f"/api/undo/{gid}/redo")
    return r.json() if r.ok else r.status_code


# ---------------------------------------------------------------- create, edit
t1 = mk(A, title="Water the roses", priority=1)
g = last(AL)
check(g.get("area") == "tasks" and g.get("label_key") == "Created: {0}" and g.get("parts") == 1, f"a new task is one step {g}")
check([(k, r, m, d.get("op")) for k, r, m, d in parts(g["id"])] == [("task", t1, "diff", "create")], f"its part {parts(g['id'])}")
GC = g["id"]
r = A.patch(B + f"/api/tasks/{t1}", json={"title": "Water the tulips", "priority": 3})
check(r.ok, f"edited {r.status_code}")
g = last(AL)
p = parts(g["id"])
check(g["label_key"] == "Edited {0}" and json.loads(g["label_args"]) == ["Water the tulips"], f"the edit's label {g}")
check(len(p) == 1 and p[0][3] == {"op": "fields", "b": {"title": "Water the roses", "priority": 1},
                                  "a": {"title": "Water the tulips", "priority": 3}}, f"only the changed fields are kept {p}")
items = A.get(B + "/api/undo").json()["items"]
check(items[0]["id"] == g["id"] and items[0]["label"] == "Edited Water the tulips" and items[0]["kind"] == "task"
      and items[0]["ref_id"] == t1, f"listed with its label, kind and task {items[:1]}")
n = ngroups(AL)
res = undo(A, g["id"])
check(isinstance(res, dict) and res["undone"] == [g["id"]] and not res["stayed"], f"undone {res}")
check(task(t1)["title"] == "Water the roses" and task(t1)["priority"] == 1, f"the values before are back {task(t1)}")
check(ngroups(AL) == n and last(AL)["state"] == "undone", "the undo itself records no new step")
res = redo(A, g["id"])
check(isinstance(res, dict) and res["redone"] == 1, f"redone {res}")
check(task(t1)["title"] == "Water the tulips" and task(t1)["priority"] == 3, f"forward again {task(t1)}")

# ---------------------------------------------------------------- a field changed elsewhere stays, the rest goes back
A.patch(B + f"/api/tasks/{t1}", json={"title": "Water all", "priority": 5})
G = last(AL)["id"]
Bo.patch(B + f"/api/tasks/{t1}", json={"title": "Bob waters"})
res = undo(A, G)
check(res["partial"] == [G] and len(res["stayed"]) == 1 and res["stayed"][0]["code"] == "conflict"
      and "title" in res["stayed"][0]["reason"], f"the title stays, named {res}")
check(task(t1)["title"] == "Bob waters" and task(t1)["priority"] == 3, f"the priority went back, bob's title stayed {task(t1)}")
check(Bo.post(B + f"/api/undo/to/{G}").status_code == 404, "another person's group: 404")
check(all(x["id"] != G for x in Bo.get(B + "/api/undo").json()["items"]), "and not in bob's list")

# ---------------------------------------------------------------- multi-select: one group, one part per task
t2, t3, t4 = mk(A, title="Rake leaves"), mk(A, title="Cut hedge"), mk(A, title="Sow grass")
r = A.post(B + "/api/tasks/batch", json={"ids": [t2, t3, t4], "action": "patch", "data": {"priority": 7}})
check(r.ok and r.json()["count"] == 3, f"batch {r.text[:200]}")
g = last(AL)
check(g["parts"] == 3 and g["label_key"] == "{0} tasks changed" and json.loads(g["label_args"]) == [3], f"one group for the batch {g}")
undo(A, g["id"])
check([task(t)["priority"] for t in (t2, t3, t4)] == [0, 0, 0], f"all three back {[task(t) for t in (t2, t3, t4)]}")
# a task of a batch that fails goes back to its savepoint and records nothing (the step is read at the commit)
r = A.post(B + "/api/tasks/batch", json={"ids": [t3, t4], "action": "patch_each",
                                         "data": {"items": {str(t3): {"priority": 5}, str(t4): {"priority": 5, "title": ""}}}})
g = last(AL)
check(r.ok and r.json()["count"] == 1 and task(t4)["priority"] == 0, f"the failing one kept its values {r.text[:200]}")
check([x[1] for x in parts(g["id"])] == [t3], f"only the changed task is a part {parts(g['id'])}")

# ---------------------------------------------------------------- drag (reorder) into another place
r = A.post(B + "/api/tasks/reorder", json={"items": [{"id": t2, "sort": 99, "priority": 3}]})
g = last(AL)
check(r.ok and parts(g["id"])[0][3]["a"] == {"sort": 99, "priority": 3}, f"a drag is a step {parts(g['id'])}")
undo(A, g["id"])
check(task(t2)["priority"] == 0 and task(t2)["sort"] != 99, f"dragged back {task(t2)}")

# ---------------------------------------------------------------- complete / reopen / recurring
r = A.post(B + f"/api/tasks/{t2}/complete", json={})
g = last(AL)
check(r.ok and g["label_key"] == "Completed {0}" and parts(g["id"])[0][3]["op"] == "complete", f"completing is a step {g}")
undo(A, g["id"])
check(task(t2)["status"] == 0, f"open again {task(t2)}")
redo(A, g["id"])
check(task(t2)["status"] == 2, f"done again {task(t2)}")
r = A.post(B + f"/api/tasks/{t2}/reopen")
g = last(AL)
check(r.ok and g["label_key"] == "Reopened {0}", f"reopening is a step {g}")
undo(A, g["id"])
check(task(t2)["status"] == 2, f"undoing the reopen completes it again {task(t2)}")
tr_ = mk(A, title="Feed the fish", due=D(0), repeat="FREQ=DAILY")
r = A.post(B + f"/api/tasks/{tr_}/complete", json={})
g = last(AL)
check(r.ok and task(tr_)["due"] == D(1), f"the series moved on {task(tr_)}")
ncopies = dbx("SELECT COUNT(*) FROM tasks WHERE title='Feed the fish' AND status=2")[0][0]
res = undo(A, g["id"])
check(task(tr_)["due"] == D(0) and dbx("SELECT COUNT(*) FROM tasks WHERE title='Feed the fish' AND status=2")[0][0] == ncopies - 1,
      f"the date is back and the completed copy gone {task(tr_)} {res}")

# ---------------------------------------------------------------- trash, restore, create taken back
r = A.delete(B + f"/api/tasks/{t3}")
g = last(AL)
check(r.ok and g["label_key"] == "Deleted {0}", f"the trash is a step {g}")
undo(A, g["id"])
check(task(t3)["deleted_at"] is None, f"back from the trash {task(t3)}")
redo(A, g["id"])
check(task(t3)["deleted_at"] is not None, "in the trash again")
A.post(B + f"/api/tasks/{t3}/restore")
check(last(AL)["label_key"] == "Restored {0}", f"restoring is a step {last(AL)}")
t5 = mk(A, title="Plant a tree")
G5 = last(AL)["id"]
undo(A, G5)
check(task(t5)["deleted_at"] is not None, "undoing a new task puts it in the trash")
redo(A, G5)
check(task(t5)["deleted_at"] is None, "redo brings it back")
t6 = mk(A, title="Mow")
G6 = last(AL)["id"]
Bo.patch(B + f"/api/tasks/{t6}", json={"priority": 3})
res = undo(A, G6)
check(task(t6)["deleted_at"] is None and res["stayed"] and res["stayed"][0]["code"] == "conflict",
      f"a new task someone else changed since stays {res}")

# ---------------------------------------------------------------- "bis hierher": several groups in one run
t7 = mk(A, title="Prune")
A.patch(B + f"/api/tasks/{t7}", json={"priority": 1})
G7a = last(AL)["id"]
A.patch(B + f"/api/tasks/{t7}", json={"title": "Prune the apple tree"})
res = undo(A, G7a)
check(len(res["undone"]) == 2 and task(t7)["title"] == "Prune" and task(t7)["priority"] == 0, f"two steps back in one run {res}")

# ---------------------------------------------------------------- sections
S1 = A.post(B + "/api/sections", json={"list_id": L, "name": "Spring"}).json()["id"]
S2 = A.post(B + "/api/sections", json={"list_id": L, "name": "Autumn"}).json()["id"]
A.patch(B + f"/api/sections/{S1}", json={"name": "Early spring", "wip_limit": 3})
g = last(AL)
check(g["label_key"] == "Section renamed to {0}" and parts(g["id"])[0][:3] == ("section", S1, "diff"), f"a section's step {g}")
undo(A, g["id"])
check(dbx("SELECT name, wip_limit FROM sections WHERE id=?", (S1,)) == [("Spring", None)], f"name and limit back {dbx('SELECT name, wip_limit FROM sections WHERE id=?', (S1,))}")
order = lambda: [r[0] for r in dbx("SELECT id FROM sections WHERE list_id=? ORDER BY sort, id", (L,))]  # noqa: E731
before = order()
A.post(B + f"/api/lists/{L}/sections/order", json={"ids": list(reversed(before))})
g = last(AL)
check(g["label_key"] == "Sections reordered" and order() == list(reversed(before)), f"reordering is a step {g}")
undo(A, g["id"])
check(order() == before, f"the order is back {order()}")
check(A.patch(B + f"/api/sections/{S2}", json={"name": ""}).status_code == 400, "an empty name: 400 as before")

# ---------------------------------------------------------------- a person without an organisation
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Studio"}).json()["id"]
ft = Fr.post(B + "/api/tasks", json={"list_id": FL, "title": "Send sketches"}).json()["id"]
Fr.patch(B + f"/api/tasks/{ft}", json={"title": "Send the sketches", "due": D(2)})
g = last(FID)
check(any(x["id"] == g["id"] for x in Fr.get(B + "/api/undo").json()["items"]), "listed for her")
res = undo(Fr, g["id"])
check(res["undone"] == [g["id"]] and task(ft)["title"] == "Send sketches" and task(ft)["due"] is None, f"taken back {res} {task(ft)}")
redo(Fr, g["id"])
check(task(ft)["title"] == "Send the sketches" and task(ft)["due"] == D(2), f"redone {task(ft)}")

sys.exit(done("p2774_a_task_undo"))
