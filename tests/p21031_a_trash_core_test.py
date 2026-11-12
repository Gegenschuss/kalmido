#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1031.0 (#5538): small findings of the Fable review of 2.851 in the core's trash, each fixed at its cause.
Invented names only.
 - the trash rule of projects (lists/listtrash.py otr_can) judges the uid it is asked for, also outside a request: the
   owner manages her project in the trash, an agent that owns one never, someone else never
 - obj_purge checks the kind's trash_keep under its lock: a kept project stays (409 of the core) even when the area's
   hook would let it go; early=True (the custodian's early delete) deletes it
 - the retention run with the switch off counts every due object, not at most one batch
 - a full batch makes the next run begin behind its last id: ids that stay locked never hold back the ones behind them
 - a task restored through the core keeps the tasks' format of updated_at (seconds), its dict has no rev / updated_by /
   deleted_by
freelancer-matrix: tasks (a person without an organisation: her project in the trash, her task restored)
usage: p21031_a_trash_core_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import B, check, dbx, done, fresh, sess  # noqa: E402
from obj_probe import agent, in_app  # noqa: E402

fresh(prefix="P21031A")

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEATURES})
FID, Fr = freelancer(B, A)
UID_A = dbx("SELECT id FROM users WHERE username='alice'")[0][0]
OLD = "2020-01-01T00:00:00+00:00"


def plist(s, name):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": None})
    check(r.ok, f"setup: project {name} {r.text[:120]}")
    return r.json().get("id")


def task(s, lid, title):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid})
    check(r.ok, f"setup: task {title} {r.text[:120]}")
    return r.json().get("id")


def list_to_trash(s, lid):
    s.patch(B + f"/api/lists/{lid}", json={"archived": True})
    check(s.delete(B + f"/api/lists/{lid}").ok, f"setup: project {lid} into the trash")


# ---------------------------------------------------------------- otr_can judges the uid it is asked for
L1 = plist(Fr, "Example Own Trash")
list_to_trash(Fr, L1)
AG = agent(Fr, "sorter")
L2 = plist(Fr, "Example Agent Project")
list_to_trash(Fr, L2)
dbx("UPDATE lists SET owner_id=? WHERE id=? RETURNING id", (AG.id, L2))
out = in_app(f"""from kalmido.lists.listtrash import otr_can
r1 = c.execute("SELECT * FROM lists WHERE id=?", ({L1},)).fetchone()
r2 = c.execute("SELECT * FROM lists WHERE id=?", ({L2},)).fetchone()
print("CAN", otr_can(c, {FID}, r1), otr_can(c, {UID_A}, r1), otr_can(c, {AG.id}, r2), otr_can(c, None, r1))""")
check("CAN True False False False" in out,
      f"outside a request: the owner manages her project in the trash, someone else, an owning agent, nobody do not {out[-400:]}")
check(L1 in {x["id"] for x in Fr.get(B + "/api/trash/lists").json().get("lists", [])}, "freelancer: her trash lists it (request)")
check(L1 not in {x["id"] for x in A.get(B + "/api/trash/lists").json().get("lists", [])}, "someone else's trash does not")

# ---------------------------------------------------------------- obj_purge checks trash_keep under its lock
L3 = plist(Fr, "Example Kept Project")
T3 = task(Fr, L3, "Task of the kept project")
list_to_trash(Fr, L3)
dbx("UPDATE lists SET retain_until='2099-12-31' WHERE id=? RETURNING id", (L3,))
out = in_app(f"""from kalmido.core.writes import obj_purge, obj_purge_after
from kalmido.lists.listtrash import _OTR_EARLY
_OTR_EARLY.set(True)  # the area's hook would let it go: the core must keep it all the same
try:
    with obj_purge_after():
        obj_purge(c, {FID}, "list", {L3})
    print("KEEP purged")
except Denied as e:
    print("KEEP", e.code, e.msg)
c.rollback()
with obj_purge_after():
    obj_purge(c, {FID}, "list", {L3}, early=True)
print("EARLY", c.execute("SELECT COUNT(*) FROM lists WHERE id=?", ({L3},)).fetchone()[0])
c.rollback()""")
check("KEEP 409 Receipt within its retention period" in out, f"a kept project stays: 409 of the core under its lock {out[-400:]}")
check("EARLY 0" in out, f"early=True (the custodian's early delete) deletes it {out[-400:]}")
check(dbx("SELECT 1 FROM lists WHERE id=?", (L3,)) and dbx("SELECT 1 FROM tasks WHERE id=?", (T3,)), "setup: rolled back, it is still there")
r = Fr.delete(B + f"/api/trash/lists/{L3}", params={"confirm": "Example Kept Project"})
check(r.ok and not dbx("SELECT 1 FROM lists WHERE id=?", (L3,)), f"the route's early delete with the name still goes {r.status_code} {r.text[:200]}")

# ---------------------------------------------------------------- the run: count all with the switch off, rotate full batches
LS = [plist(Fr, f"Example Old Project {i}") for i in range(3)]
for x in LS:
    list_to_trash(Fr, x)
    dbx("UPDATE lists SET deleted_at=? WHERE id=? RETURNING id", (OLD, x))
dbx("UPDATE lists SET deleted_at=? WHERE id IN (?, ?) RETURNING id", (OLD, L1, L2))
DUE = sorted([*LS, L1, L2])
out = in_app("""from kalmido.core.objects import OBJ
from kalmido.core.writes import OBJ_PURGE, obj_purge_after, obj_trash_prune
OBJ["list"]["trash_batch"] = 2
print("COUNT", obj_trash_prune(c, "list", purge=False))
seen = []
def stuck(c, rid):
    seen.append(rid)
    raise Denied(409)  # kept by its area (as a receipt under the legal retention): it stays, counted as locked
OBJ_PURGE["list"] = stuck
for _ in range(3):
    with obj_purge_after(keep_locked=True):
        obj_trash_prune(c, "list", purge=True)
print("SEEN", sorted(set(seen)), len(seen))
c.rollback()""")
check(f"COUNT {len(DUE)}" in out, f"switch off: every due project is counted ({len(DUE)}), not one batch of 2 {out[-400:]}")
check(f"SEEN {DUE} 6" in out, f"three runs of 2 reach all {len(DUE)} due projects, the locked ones do not hold the rest back {out[-400:]}")

# ---------------------------------------------------------------- a task restored through the core: the tasks' format, its dict
L4 = plist(Fr, "Example Own Tasks")
T4 = task(Fr, L4, "Own task to restore")
check(Fr.delete(B + f"/api/tasks/{T4}").ok, "setup: her task into the trash")
r = Fr.post(B + f"/api/tasks/{T4}/restore")
ua = str(dbx("SELECT updated_at FROM tasks WHERE id=?", (T4,))[0][0] or "")
check(r.ok and ua and "." not in ua, f"freelancer: her task came back, updated_at in seconds as the tasks write it {r.status_code} {ua}")
d = Fr.get(B + f"/api/tasks/{T4}").json()
d = d.get("task", d)
check(d.get("id") == T4 and not ({"rev", "updated_by", "deleted_by"} & set(d)),
      f"the task's dict has no rev / updated_by / deleted_by {sorted(k for k in d if k in ('rev', 'updated_by', 'deleted_by'))}")
st = [t for t in Fr.get(B + "/api/state").json().get("tasks", []) if t.get("id") == T4]
check(st and not ({"rev", "updated_by", "deleted_by"} & set(st[0])), "nor in the state")

sys.exit(done("p21031_a_trash_core"))
