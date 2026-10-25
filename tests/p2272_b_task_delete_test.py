#!/usr/bin/env python3
"""2.272.0 B (#3025, #3045) API tests (fresh DB): undo of a series completion and the trash of tasks.
#3025: undo of a recurring task's completion: an untouched done copy goes, a copy someone commented on / attached a
file to goes to the trash (the file stays on disk) and the series still moves back; a signature older than 24 hours or
without its time is refused with a clear message.
#3045: trashing a parent leaves a subtask in another list where the person may not delete there (detached, visible for
that list's people), restoring the parent brings back only the subtasks that went along; purge-done (Delete all
completed) takes only my own completed tasks unless others=true; multi-delete with a stale state (guard) is a conflict,
a whole-second updated_at the client saw is not; multi-restore of a task whose project is in the trash is refused.
The case without an organisation (freelancer fixture) runs the same steps."""
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import dbx as dbxm
import testclock
from freelancer_fixture import FEATURES, freelancer
from kt import check, done, sess, B, DATA


def dbx(q, a=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def row(tid):
    r = dbx("SELECT * FROM tasks WHERE id=?", (tid,))
    return dict(r[0]) if r else None


D = lambda n: (testclock.today() + timedelta(days=n)).isoformat()  # noqa: E731
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
A_ID = A.get(B + "/api/state").json()["me"]["id"]
BOB, Bo = freelancer(B, A, "bob")
FRIDA, Fr = freelancer(B, A, "frida")
mk = lambda s, **b: s.post(B + "/api/tasks", json=b).json()["id"]  # noqa: E731
batch = lambda s, action, ids, data=None: s.post(B + "/api/tasks/batch", json={"ids": ids, "action": action, "data": data or {}})  # noqa: E731
L = A.post(B + "/api/lists", json={"name": "Home"}).json()["id"]
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: bob edits alice's list")
KEY = dbx("SELECT value FROM settings WHERE key='undo_key'")[0][0]


def resign(tid, uid, u):
    msg = json.dumps({"tid": tid, "uid": uid, **{k: v for k, v in u.items() if k != "sig"}}, sort_keys=True, default=str)
    return {**u, "sig": hmac.new(KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()}


def series(s, uid, lid, who):
    """#3025 for one person (alice in a shared list / frida without an organisation)."""
    rc = mk(s, title="Water plants", list_id=lid, due=D(0), repeat="FREQ=WEEKLY")
    j = s.post(B + f"/api/tasks/{rc}/complete", json={"expect_due": D(0)}).json()
    u, cp = j["undo"], j["undo"]["copy_id"]
    check(u.get("sat") and row(cp)["status"] == 2 and row(rc)["due"] == D(7), f"{who}: the completion is signed with its time")
    r = s.post(B + f"/api/tasks/{rc}/undo", json=u)
    check(r.ok and row(rc)["due"] == D(0) and row(cp) is None, f"{who}: undo of an untouched copy: copy gone, series back {r.text[:120]}")
    # a comment + a file on the done copy (bob in the shared list, else the person)
    j = s.post(B + f"/api/tasks/{rc}/complete", json={"expect_due": D(0)}).json()
    u, cp = j["undo"], j["undo"]["copy_id"]
    other = Bo if lid == L else s
    check(other.post(B + f"/api/tasks/{cp}/comments", json={"body": "done, photo attached"}).ok, f"{who}: setup comment on the copy")
    ra = other.post(B + f"/api/tasks/{cp}/attachments", files={"file": ("proof.txt", b"proof\n" * 10, "text/plain")})
    check(ra.ok, f"{who}: setup file on the copy {ra.text[:120]}")
    path = dbx("SELECT path FROM attachments WHERE task_id=?", (cp,))[0][0]
    r = s.post(B + f"/api/tasks/{rc}/undo", json=u)
    cr = row(cp)
    check(r.ok and row(rc)["due"] == D(0) and cr is not None and cr["deleted_at"], f"{who}: #3025 copy with a comment -> trash, series back")
    check(os.path.exists(os.path.join(DATA, "attachments", path)), f"{who}: #3025 the copy's file stays on disk")
    check(dbx("SELECT COUNT(*) FROM comments WHERE task_id=?", (cp,))[0][0] == 1, f"{who}: #3025 the comment stays")
    # 2.272.0 F (#3025, review H2): a copy edited since (description) or with a dependency goes to the trash too
    j = s.post(B + f"/api/tasks/{rc}/complete", json={"expect_due": D(0)}).json()
    u, cp = j["undo"], j["undo"]["copy_id"]
    time.sleep(1.1)  # the edit in a later second than the completion
    check(s.patch(B + f"/api/tasks/{cp}", json={"notes": "what was done"}).ok, f"{who}: setup description on the copy")
    r = s.post(B + f"/api/tasks/{rc}/undo", json=u)
    cr = row(cp)
    check(r.ok and row(rc)["due"] == D(0) and cr is not None and cr["deleted_at"],
          f"{who}: #3025 copy with an edited description -> trash, series back {r.text[:120]}")
    j = s.post(B + f"/api/tasks/{rc}/complete", json={"expect_due": D(0)}).json()
    u, cp = j["undo"], j["undo"]["copy_id"]
    dbx("INSERT INTO task_deps(task_id, blocker_id, created_at) VALUES(?,?,?)", (cp, rc, j["undo"]["at"]))
    r = s.post(B + f"/api/tasks/{rc}/undo", json=u)
    cr = row(cp)
    check(r.ok and cr is not None and cr["deleted_at"], f"{who}: #3025 copy with a dependency -> trash {r.text[:120]}")
    # signature time
    j = s.post(B + f"/api/tasks/{rc}/complete", json={"expect_due": D(0)}).json()
    u = j["undo"]
    old = resign(rc, uid, {**u, "sat": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec="seconds")})
    r = s.post(B + f"/api/tasks/{rc}/undo", json=old)
    check(r.status_code == 409 and "no longer" in r.text and row(rc)["due"] == D(7), f"{who}: #3025 signature older than 24 h refused {r.text[:120]}")
    bare = resign(rc, uid, {k: v for k, v in u.items() if k != "sat"})
    r = s.post(B + f"/api/tasks/{rc}/undo", json=bare)
    check(r.status_code == 409 and "no longer" in r.text, f"{who}: #3025 signature without its time refused")
    r = batch(s, "undo", [rc], {"items": {str(rc): old}}).json()
    check(r["count"] == 0 and r["conflicts"], f"{who}: #3025 batch undo with an old signature: conflict")
    check(s.post(B + f"/api/tasks/{rc}/undo", json=u).ok and row(rc)["due"] == D(0), f"{who}: the fresh signature still works")


series(A, A_ID, L, "alice")
FL = Fr.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
series(Fr, FRIDA, FL, "frida (no organisation)")

# ================= #3045 do_delete: a subtask in another list
LB = Bo.post(B + "/api/lists", json={"name": "Bob's"}).json()["id"]
LE = Bo.post(B + "/api/lists", json={"name": "Bob's shared"}).json()["id"]
check(Bo.put(B + f"/api/lists/{LB}/members", json={"user_id": A_ID, "role": "view"}).ok, "setup: alice views bob's list")
check(Bo.put(B + f"/api/lists/{LE}/members", json={"user_id": A_ID, "role": "edit"}).ok, "setup: alice edits bob's other list")
P = mk(A, title="Move house", list_id=L)
S1 = mk(A, title="Same list sub", list_id=L, parent_id=P)
S2 = mk(A, title="Bob's sub", list_id=L, parent_id=P)
S3 = mk(A, title="Shared sub", list_id=L, parent_id=P)
dbx("UPDATE tasks SET list_id=? WHERE id=?", (LB, S2))
dbx("UPDATE tasks SET list_id=? WHERE id=?", (LE, S3))
check(A.delete(B + f"/api/tasks/{P}").ok, "alice trashes the parent")
r2, r1, r3 = row(S2), row(S1), row(S3)
check(r1["deleted_at"] and r3["deleted_at"], "#3045: subtasks in the same list / a list alice may delete in go along")
check(r2["deleted_at"] is None and r2["parent_id"] is None, "#3045: the subtask in bob's list (alice only views) stays, detached")
check(any(t["id"] == S2 for t in Bo.get(B + "/api/state").json()["tasks"]), "#3045: bob still sees his list's subtask")
check(A.post(B + f"/api/tasks/{P}/restore").ok and row(S1)["deleted_at"] is None and row(S3)["deleted_at"] is None
      and row(S2)["parent_id"] is None, "#3045: restoring the parent brings back the ones that went along")
# 2.272.0 F (#3045, review N10): restoring brings back a subtask in another list only where the person may delete
P2 = mk(Bo, title="Bob's parent", list_id=L)
S4 = mk(Bo, title="Bob's sub in his list", list_id=L, parent_id=P2)
dbx("UPDATE tasks SET list_id=? WHERE id=?", (LB, S4))
check(Bo.delete(B + f"/api/tasks/{P2}").ok and row(S4)["deleted_at"], "setup: bob trashes his parent with his own list's subtask")
check(A.post(B + f"/api/tasks/{P2}/restore").ok and row(P2)["deleted_at"] is None and row(S4)["deleted_at"],
      "#3045: alice restores the parent, bob's subtask in his list (alice only views) stays in the trash")
# without an organisation: the same rule
FP = mk(Fr, title="Frida parent", list_id=FL)
FS = mk(Fr, title="Frida sub", list_id=FL, parent_id=FP)
check(Fr.delete(B + f"/api/tasks/{FP}").ok and row(FS)["deleted_at"], "frida (no organisation): her own subtask goes along")

# ================= #3045 purge-done: only my own by default
mine = mk(A, title="My done", list_id=L)
bobs = mk(Bo, title="Bob's done", list_id=L)
rec = mk(A, title="Series", list_id=L, due=D(0), repeat="FREQ=DAILY")
for t, s in ((mine, A), (bobs, Bo)):
    s.post(B + f"/api/tasks/{t}/complete")
cpy = A.post(B + f"/api/tasks/{rec}/complete", json={"expect_due": D(0)}).json()["undo"]["copy_id"]
j = A.post(B + "/api/tasks/purge-done", json={"dry": True}).json()
check(j["own"] >= 2 and j["others"] == 1 and row(mine)["deleted_at"] is None, f"#3045: dry run counts own / others {j}")
j = A.post(B + "/api/tasks/purge-done").json()
check(row(mine)["deleted_at"] and row(cpy)["deleted_at"] and row(bobs)["deleted_at"] is None and j["kept"] == 1,
      f"#3045: purge-done takes my own (and the done copy), bob's stays {j}")
check(row(rec)["deleted_at"] is None and row(rec)["status"] == 0, "#3045: the open series stays")
j = A.post(B + "/api/tasks/purge-done", json={"others": True}).json()
check(j["count"] == 1 and row(bobs)["deleted_at"], "#3045: others=true (the owner's choice) takes bob's too")
fd = mk(Fr, title="Frida done", list_id=FL)
Fr.post(B + f"/api/tasks/{fd}/complete")
check(Fr.post(B + "/api/tasks/purge-done").json()["count"] >= 1 and row(fd)["deleted_at"], "frida (no organisation): purge-done takes her own")

# ================= #3045 multi-delete with the client's state
tb = mk(A, title="Shared plan", list_id=L)
seen = next(t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == tb)["updated_at"]
time.sleep(1.1)  # bob's change in a later second than the state alice saw
check(Bo.patch(B + f"/api/tasks/{tb}", json={"title": "Shared plan (bob)"}).ok, "setup: bob changes the task")
r = batch(A, "delete", [tb], {"guard": {str(tb): seen}}).json()
check(r["count"] == 0 and r["conflicts"] and r["conflicts"][0]["field"] == "changed" and row(tb)["deleted_at"] is None,
      f"#3045: multi-delete with a stale state: conflict, not trashed {r}")
seen = next(t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == tb)["updated_at"]
r = batch(A, "delete", [tb], {"guard": {str(tb): seen}}).json()
check(r["count"] == 1 and not r["conflicts"] and row(tb)["deleted_at"], f"#3045: with the state that saw bob's change: trashed {r}")
tn = mk(A, title="No guard", list_id=L)
check(batch(A, "delete", [tn]).json()["count"] == 1, "#3045: without a guard (agents, old clients) as before")
ft = mk(Fr, title="Frida multi", list_id=FL)
fs = next(t for t in Fr.get(B + "/api/state").json()["tasks"] if t["id"] == ft)["updated_at"]
check(batch(Fr, "delete", [ft], {"guard": {str(ft): fs}}).json()["count"] == 1, "frida (no organisation): multi-delete with her state")
# 2.272.0 F (#3045, review M7): "Delete completed" sends own_only, the server leaves the other members' ones
m2, b2 = mk(A, title="My done 2", list_id=L), mk(Bo, title="Bob's done 2", list_id=L)
A.post(B + f"/api/tasks/{m2}/complete")
Bo.post(B + f"/api/tasks/{b2}/complete")
r = batch(A, "delete", [m2, b2], {"own_only": True}).json()
check(r["count"] == 1 and r["skipped"] == [b2] and row(m2)["deleted_at"] and row(b2)["deleted_at"] is None,
      f"#3045: batch delete with own_only trashes only my own {r}")
f2 = mk(Fr, title="Frida done 2", list_id=FL)
Fr.post(B + f"/api/tasks/{f2}/complete")
check(batch(Fr, "delete", [f2], {"own_only": True}).json()["count"] == 1, "frida (no organisation): own_only takes her own")

# ================= #3045 multi-restore: a task of a project in the trash comes back only with the project
LX = A.post(B + "/api/lists", json={"name": "Gone soon"}).json()["id"]
tx = mk(A, title="In a gone project", list_id=LX)
A.delete(B + f"/api/tasks/{tx}")
A.patch(B + f"/api/lists/{LX}", json={"archived": 1})
check(A.delete(B + f"/api/lists/{LX}").ok, "setup: the project goes to the trash")
r = batch(A, "restore", [tx]).json()
check(r["count"] == 0 and any("restore the project" in e for e in r["errors"]) and row(tx)["deleted_at"],
      f"#3045: multi-restore refused while the project is in the trash {r}")
r = batch(A, "restore", [tn]).json()
check(r["count"] == 1 and row(tn)["deleted_at"] is None, "multi-restore of a normal task as before")

sys.exit(done("p2272_b_task_delete"))
