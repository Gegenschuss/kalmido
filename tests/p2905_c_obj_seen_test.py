#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.905.0 (#5284, stage Q8a of the cross-cutting core): the read marks of tasks are rows of the core (obj_seen, core/objseen.py);
task_seen is gone. Own container. Invented names only.
 - obj_seen is there, task_seen is not; a task_seen made again by hand with rows (what a version before 2.905 leaves after a
   rollback) is moved at the next start of the app (the higher mark wins) and dropped
 - a comment read (POST /api/tasks/<id>/seen) is a mark (kind task, the highest comment id, seen_at a point in time); the own
   comment counts as read; the task's unread number in /api/state follows each person's own mark
 - the change feed: a read mark is a change of the task for its reader only (dl_changes row with the reader, the reader's
   delta carries the task, the other member's does not)
 - tenant boundary: who does not see the task cannot set a mark (404), the timeline answers the own mark only
 - a task deleted for good takes its marks along (trigger kalmido_osn_gone)
 - a person without an organisation (freelancer fixture) reads a comment in their own list
freelancer-matrix: tasks
usage: p2905_c_obj_seen_test.py <datadir>"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, dbx  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402


def box(code):
    """Python inside the app container (as the system); "import app" starts the app (init_db: the move, the fragments)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\n"
                          "from kalmido.core.pg import system_ctx\nc = connect()\nwith system_ctx(c):\n"
                          + "".join("    " + ln + "\n" for ln in code.splitlines()) + "c.commit()\nc.close()"],
                         capture_output=True, text=True)
    check(out.returncode == 0, f"the run in the container works {out.stderr[-800:]}")
    return out.stdout.strip()


def table_there(t):
    return bool(dbx("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?", (t,)))


def mark(uid, tid):
    r = dbx("SELECT seen_id FROM obj_seen WHERE kind='task' AND ref_id=? AND user_id=?", (tid, uid))
    return r[0][0] if r else None


def unread(s, tid):
    t = [x for x in s.get(B + "/api/state").json()["tasks"] if x["id"] == tid]
    return t[0].get("unread") if t else None


def comment(s, tid, text):
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": text})
    check(r.ok, f"setup: comment '{text}' {r.status_code} {r.text[:200]}")
    return r.json()["id"]


kt.fresh(prefix="P2905C")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
for u in ("bob", "dora"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    org_join(B, u, ORG)
Bo, Do = kt.sess("bob"), kt.sess("dora")
for s in (Bo, Do):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BOB, DORA = kt.me_id(Bo), kt.me_id(Do)

# ================================================================== the old table is gone, the core's table is there
check(table_there("obj_seen"), "the core's table obj_seen exists")
check(not table_there("task_seen"), "the old table task_seen is gone")
typ = dbx("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='obj_seen' "
          "AND column_name='seen_at'")
check(typ and typ[0][0].startswith("timestamp with time zone"), f"seen_at is a real point in time {typ}")

# ================================================================== a comment read is a mark of the core
LID = A.post(B + "/api/lists", json={"name": "Werkstatt", "kind": "project", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{LID}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: bob is a member")
TID = A.post(B + "/api/tasks", json={"title": "Regal bauen", "list_id": LID}).json()["id"]
C1 = comment(Bo, TID, "Bretter sind bestellt")
check(mark(BOB, TID) == C1, f"bob's own comment counts as read: his mark is it {mark(BOB, TID)} / {C1}")
check(unread(A, TID) == 1 and unread(Bo, TID) == 0, f"alice has one unread comment, bob none ({unread(A, TID)} / {unread(Bo, TID)})")
check(A.get(B + f"/api/tasks/{TID}/timeline").json().get("seen") == 0, "alice's timeline: nothing seen yet")
r = A.post(B + f"/api/tasks/{TID}/seen")
check(r.ok and r.json().get("seen") == C1, f"alice reads the comments {r.status_code} {r.text[:200]}")
check(mark(ALICE, TID) == C1, f"the mark sits in obj_seen (kind task, the highest comment id) {mark(ALICE, TID)}")
at = dbx("SELECT seen_at FROM obj_seen WHERE kind='task' AND ref_id=? AND user_id=?", (TID, ALICE))
check(at and at[0][0] is not None, f"the mark has its point in time {at}")
check(unread(A, TID) == 0, f"alice: no unread comment any more ({unread(A, TID)})")
check(A.get(B + f"/api/tasks/{TID}/timeline").json().get("seen") == C1, "alice's timeline answers her mark")
C2 = comment(A, TID, "Danke, ich hole sie ab")
check(mark(ALICE, TID) == C2 and unread(A, TID) == 0, f"alice's own comment moves her mark ({mark(ALICE, TID)} / {C2})")
check(unread(Bo, TID) == 1, f"bob sees alice's comment as unread ({unread(Bo, TID)})")
check(mark(BOB, TID) == C1, "bob's mark is his own (not alice's)")
check(Bo.get(B + f"/api/tasks/{TID}/timeline").json().get("seen") == C1, "bob's timeline answers bob's mark, not alice's")
# a mark never goes back: reading again with nothing new keeps it (no new write either)
n0 = dbx("SELECT COUNT(*) FROM obj_seen")[0][0]
A.post(B + f"/api/tasks/{TID}/seen")
check(mark(ALICE, TID) == C2 and dbx("SELECT COUNT(*) FROM obj_seen")[0][0] == n0, "reading again keeps the mark")

# ================================================================== the change feed: the reader's alone
C3 = comment(Bo, TID, "Schrauben fehlen noch")
v0 = Bo.get(B + "/api/version").json()["v"]
r = A.post(B + f"/api/tasks/{TID}/seen")
check(r.ok and mark(ALICE, TID) == C3, f"alice reads bob's new comment {mark(ALICE, TID)} / {C3}")
rows = dbx("SELECT user_id FROM dl_changes WHERE task_id=? AND ver IS NULL", (TID,))
check([x[0] for x in rows] == [ALICE], f"the read mark is noted as a change of the task for alice only {rows}")
OWN = A.post(B + "/api/lists", json={"name": "Privat"}).json()["id"]
A.post(B + "/api/tasks", json={"title": "Einkauf", "list_id": OWN})  # a change of alice's that moves the version
da = A.get(B + "/api/state/delta", params={"since": v0, "lean": "1"}).json()
check(da.get("full") is True or TID in [t["id"] for t in da.get("tasks") or []],
      f"alice's delta carries the task (her unread number changed) {str(da)[:300]}")
if da.get("full") is False:
    t = [t for t in da["tasks"] if t["id"] == TID][0]
    check(t.get("unread", 0) == 0, f"... with no unread comment {t.get('unread')}")
db_ = Bo.get(B + "/api/state/delta", params={"since": v0, "lean": "1"}).json()
check(db_.get("full") is False and TID not in [t["id"] for t in db_.get("tasks") or []],
      f"bob's delta does not carry the task for alice's read mark {str(db_)[:300]}")

# ================================================================== tenant boundary
r = Do.post(B + f"/api/tasks/{TID}/seen")
check(r.status_code == 404 and mark(DORA, TID) is None, f"dora does not see the task: no mark ({r.status_code})")

# ================================================================== the move of a task_seen made again (a rollback)
dbx("""CREATE TABLE task_seen (user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
       task_id BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, seen_id BIGINT NOT NULL DEFAULT 0,
       PRIMARY KEY (user_id, task_id))""")
dbx("INSERT INTO task_seen(user_id,task_id,seen_id) VALUES(?,?,?)", (BOB, TID, C3))       # higher than bob's mark: wins
dbx("INSERT INTO task_seen(user_id,task_id,seen_id) VALUES(?,?,?)", (ALICE, TID, C1))     # lower than alice's: hers stays
box("pass")  # the next start of the app
check(not table_there("task_seen"), "the start dropped the old table made again")
check(mark(BOB, TID) == C3, f"bob's higher old mark moved into obj_seen {mark(BOB, TID)} / {C3}")
check(mark(ALICE, TID) == C3, f"alice's higher mark stayed {mark(ALICE, TID)} / {C3}")
check(unread(Bo, TID) == 0, f"bob: no unread comment after the move ({unread(Bo, TID)})")

# ================================================================== a task deleted for good takes its marks
T2 = A.post(B + "/api/tasks", json={"title": "Weg damit", "list_id": LID}).json()["id"]
comment(A, T2, "kurz")
check(mark(ALICE, T2) is not None, "setup: a mark on the second task")
dbx("DELETE FROM tasks WHERE id=?", (T2,))  # what the trash run does at the end
check(not dbx("SELECT 1 FROM obj_seen WHERE kind='task' AND ref_id=?", (T2,)), "the task's marks went with it")
check(mark(ALICE, TID) == C3, "the other task's marks stay")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Eigenes"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Angebot schreiben", "list_id": FL}).json()["id"]
FC = comment(Fr, FT, "Notiz")
check(mark(FID, FT) == FC and unread(Fr, FT) == 0, f"freelancer: her own note counts as read ({mark(FID, FT)})")
dbx("UPDATE obj_comments SET user_id=? WHERE id=?", (ALICE, FC))  # 2.972.0 (#5272): obj_comments - a comment of somebody else in her list (an import, a former member)
dbx("DELETE FROM obj_seen WHERE kind='task' AND ref_id=? AND user_id=?", (FT, FID))
check(unread(Fr, FT) == 1, f"freelancer: the other person's comment is unread ({unread(Fr, FT)})")
r = Fr.post(B + f"/api/tasks/{FT}/seen")
check(r.ok and mark(FID, FT) == FC and unread(Fr, FT) == 0, f"freelancer: read, the mark is in obj_seen {r.status_code}")
check(Bo.post(B + f"/api/tasks/{FT}/seen").status_code == 404 and mark(BOB, FT) is None, "bob cannot mark frida's task")

sys.exit(kt.done("p2905_c_obj_seen"))
