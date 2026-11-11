#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.972.0 (#5285, stage Q9a of the cross-cutting core): following is a row of the core (obj_follow, core/objfollow.py) -- the
watchers and the bell of a task. Own container. Invented names only.
 - the old tables task_watchers and task_bell are gone; the start moves rows of them made again by hand (what a version before
   2.972 leaves after a rollback) into obj_follow and drops them; a time that is no time becomes now
 - watching on / off (a row with mode watch), the bell muted / urgent until a day with its one undo step, an urgency of
   yesterday no longer active, urgency set by the project owner for a member and taken back by undo; watching and a muted bell
   at the same time are two rows
 - a watcher who may not read the task gets nothing (obj_notify's first step), a watcher who may gets the News
 - a watching row follows its task into another workspace, a bell row keeps the one it was set in (ignored there)
 - the account export keeps the parts task_bell / task_watchers with their old columns, the organisation export keeps
   tasks/watchers.json (task_id)
 - a member removed from the project: their watching and bells there end; leaving the organisation (the core's revocation):
   their rows of the organisation end; the task deleted for good takes its rows along
 - a person without an organisation (freelancer fixture) watches and mutes a task of her own list
freelancer-matrix: tasks
usage: p2903_c_follow_test.py <datadir>"""
import json
import os
import subprocess
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
import testclock  # noqa: E402
from kt import B, CT, check, dbx  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

T0 = testclock.today()


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


def rows(tid):
    """[(user, mode)] of the task's rows in obj_follow."""
    return sorted((r[0], r[1]) for r in dbx("SELECT user_id, mode FROM obj_follow WHERE kind='task' AND ref_id=?", (tid,)))


def bell(s, tid):
    return s.get(B + f"/api/tasks/{tid}/bell")


def put(s, tid, **kw):
    return s.put(B + f"/api/tasks/{tid}/bell", json=kw)


def news(s, tid, kind):
    return [x for x in s.get(B + "/api/news").json().get("items", []) if x.get("task_id") == tid and x.get("kind") == kind]


kt.fresh(prefix="P2903C")
r = kt.sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
assert r.ok, r.text
A = kt.sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
for u in ("bob", "gina"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    org_join(B, u, ORG)
r = A.post(B + "/api/users", json={"orgs": [], "username": "dave", "display_name": "Dave", "password": "password123", "email": "dave@example.com"})
assert r.ok, r.text
Bo, Gi, Da = kt.sess("bob"), kt.sess("gina"), kt.sess("dave")
for s in (Bo, Gi, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
BOB, GINA, DAVE = kt.me_id(Bo), kt.me_id(Gi), kt.me_id(Da)

# ================================================================== the old tables are gone, the core's table is there
check(table_there("obj_follow"), "the core's table obj_follow exists")
for t in ("task_watchers", "task_bell"):
    check(not table_there(t), f"the old table {t} is gone")

LID = A.post(B + "/api/lists", json={"name": "Werkstatt", "kind": "project", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{LID}/members", json={"user_id": BOB, "role": "edit"})
A.put(B + f"/api/lists/{LID}/members", json={"user_id": GINA, "role": "view"})
T = A.post(B + "/api/tasks", json={"title": "Regal bauen", "list_id": LID}).json()["id"]
W = B + f"/api/tasks/{T}/watchers"

# ================================================================== watching on / off
r = Bo.post(W, json={})
check(r.ok and r.json()["mine"] and [x["id"] for x in r.json()["watchers"]] == [BOB], f"bob watches the task {r.status_code} {r.text[:200]}")
check(rows(T) == [(BOB, "watch")], f"a row of obj_follow with mode watch {rows(T)}")
org_row = dbx("SELECT org_id FROM obj_follow WHERE kind='task' AND ref_id=? AND user_id=?", (T, BOB))
check(org_row and org_row[0][0] == ORG, f"the watching row carries the task's organisation {org_row}")
check(A.get(B + f"/api/tasks/{T}").json().get("watchers") == [BOB], "the task carries its watchers")
r = Bo.delete(W + f"/{BOB}")
check(r.ok and not r.json()["mine"] and rows(T) == [], f"bob stops watching: the row is gone {rows(T)}")
check(Bo.post(W, json={}).ok and Gi.post(W, json={}).ok, "bob and gina watch")

# ================================================================== the bell
r = put(Bo, T, level="mute")
check(r.ok and r.json()["mine"]["level"] == "mute", f"bob mutes the task {r.status_code} {r.text[:200]}")
check(rows(T) == sorted([(BOB, "watch"), (BOB, "mute"), (GINA, "watch")]), f"watching and the muted bell are two rows {rows(T)}")
day = (T0 + timedelta(days=2)).isoformat()
r = put(Bo, T, level="urgent", until=day)
j = r.json() if r.ok else {}
check(r.ok and j["mine"]["level"] == "urgent" and j["mine"]["until"] == day and j["mine"]["active"] and j.get("act"),
      f"urgent until a day {r.status_code} {r.text[:200]}")
check(dbx("SELECT until::text FROM obj_follow WHERE kind='task' AND ref_id=? AND user_id=? AND mode<>'watch'", (T, BOB))[0][0] == day,
      "the day is stored as a date")
r = Bo.post(B + f"/api/tasks/{T}/bell/undo", json={"act": j.get("act")})
check(r.ok and r.json()["undone"] == 1 and r.json()["mine"]["level"] == "mute", f"undo: back to muted {r.status_code} {r.text[:200]}")
check(put(Bo, T, level="urgent", until=day).ok, "urgent again")
dbx("UPDATE obj_follow SET until=? WHERE kind='task' AND ref_id=? AND user_id=? AND mode<>'watch'", ((T0 - timedelta(days=1)).isoformat(), T, BOB))
check(bell(Bo, T).json()["mine"]["active"] is False, "an urgency of yesterday is no longer active")
r = put(A, T, level="urgent", users=[GINA])
j = r.json() if r.ok else {}
check(r.ok and j.get("changed") == 1, f"the owner marks gina urgent {r.status_code} {r.text[:200]}")
g = dbx("SELECT mode, set_by FROM obj_follow WHERE kind='task' AND ref_id=? AND user_id=? AND mode<>'watch'", (T, GINA))
check(g and (g[0][0], g[0][1]) == ("urgent", ALICE), f"gina's bell row: urgent, set by alice {g}")
check([p for p in A.get(B + f"/api/tasks/{T}/bell").json()["people"] if p["id"] == GINA][0]["level"] == "urgent", "the owner sees it")
r = A.post(B + f"/api/tasks/{T}/bell/undo", json={"act": j.get("act")})
check(r.ok and bell(Gi, T).json()["mine"]["level"] == "list", f"the owner's undo takes it back {r.status_code} {r.text[:200]}")

# ================================================================== who gets something: the right first
dbx("INSERT INTO obj_follow(user_id,kind,ref_id,mode) VALUES(?,'task',?,'watch')", (DAVE, T))  # a row of someone who may not read it
check(bell(Da, T).status_code == 404, "dave does not see the task")
Gi.post(B + "/api/news/read", json={"all": True})
check(A.post(B + f"/api/tasks/{T}/complete", json={}).ok, "alice completes the task")
check(kt.until(lambda: news(Gi, T, "complete"), timeout=10), "gina (watcher, reader) gets the News of the completion")
check(not dbx("SELECT 1 FROM notifications WHERE user_id=? AND task_id=?", (DAVE, T)), "dave (watcher without the right) gets nothing")
A.post(B + f"/api/tasks/{T}/complete", json={"status": 0})

# ================================================================== a task in another workspace
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Eigenes"}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"title": "Umzug", "list_id": LID}).json()["id"]
check(Bo.post(B + f"/api/tasks/{T3}/watchers", json={}).ok and put(Bo, T3, level="mute").ok, "bob watches and mutes a second task")
dbx("UPDATE tasks SET list_id=? WHERE id=?", (FL, T3))  # moved into a private list (the move route has its own checks)
o = dict((r[0], r[1]) for r in dbx("SELECT mode, org_id FROM obj_follow WHERE kind='task' AND ref_id=? AND user_id=?", (T3, BOB)))
check(o.get("watch", 0) is None and o.get("mute") == ORG, f"the watching row follows the task, the bell row keeps its workspace {o}")
dbx("UPDATE tasks SET list_id=? WHERE id=?", (LID, T3))
o = dict((r[0], r[1]) for r in dbx("SELECT mode, org_id FROM obj_follow WHERE kind='task' AND ref_id=? AND user_id=?", (T3, BOB)))
check(o.get("watch") == ORG and o.get("mute") == ORG and bell(Bo, T3).json()["mine"]["level"] == "mute", f"and back {o}")

# ================================================================== exports
out = box(f"""import json
from kalmido.accounts.settings import umz_export_queries
q = umz_export_queries({BOB})
for k in ("task_bell", "task_watchers"):
    sql, a = q[k]
    print("EX" + k + " " + json.dumps(sorted([dict(r) for r in c.execute(sql, a).fetchall()], key=lambda x: x["task_id"]), default=str))""")
ex = {ln.split(" ", 1)[0][2:]: json.loads(ln.split(" ", 1)[1]) for ln in out.splitlines() if ln.startswith("EX")}
tb, tw = ex.get("task_bell") or [], ex.get("task_watchers") or []
check([(x["task_id"], x["level"]) for x in tb] == [(T, "urgent"), (T3, "mute")] and tb[0]["until"] == (T0 - timedelta(days=1)).isoformat(),
      f"the account export: the part task_bell with its old columns {tb}")
check([x["task_id"] for x in tw] == [T, T3] and all(isinstance(x["created_at"], str) for x in tw), f"... and task_watchers {tw}")
out = box(f"""import io, json, zipfile
from kalmido.admin.orgexport import ox_build
b = io.BytesIO()
ox_build(c, {ORG}, b, by={{"id": {ALICE}, "name": "Admin"}})
z = zipfile.ZipFile(b)
print("OXJSON" + json.dumps(json.loads(z.read("tasks/watchers.json")) if "tasks/watchers.json" in z.namelist() else None, default=str))""")
line = next((x for x in out.splitlines() if x.startswith("OXJSON")), None)
ox = json.loads(line[6:]) if line else None
check(ox is not None and sorted((x.get("task_id"), x.get("user_id")) for x in ox) == sorted([(T, BOB), (T, GINA), (T, DAVE), (T3, BOB)])
      and all("ref_id" not in x and "mode" not in x for x in ox), f"the organisation export keeps tasks/watchers.json with task_id {ox}")

# ================================================================== the end of a share
check(A.delete(B + f"/api/lists/{LID}/members/{GINA}").ok, "alice removes gina from the project")
check(not [x for x in rows(T) if x[0] == GINA], f"her watching ends {rows(T)}")
box(f"""from kalmido.core.objhooks import person_revoked
person_revoked(c, {BOB}, {ORG}, "leave")""")
check(not dbx("SELECT 1 FROM obj_follow WHERE user_id=? AND org_id=?", (BOB, ORG)), "the core's revocation (leaving the organisation): bob's rows there end")

# ================================================================== the move of the old tables (a version before 2.972 ran)
T2 = A.post(B + "/api/tasks", json={"title": "Lampe", "list_id": LID}).json()["id"]
dbx("""CREATE TABLE task_watchers (task_id BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
       user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at TEXT NOT NULL, PRIMARY KEY (task_id, user_id))""")
dbx("""CREATE TABLE task_bell (task_id BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
       user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, org_id BIGINT REFERENCES orgs(id) ON DELETE CASCADE,
       level TEXT NOT NULL DEFAULT 'list', until TEXT, set_by BIGINT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
       prev TEXT, act TEXT, act_by BIGINT, PRIMARY KEY (task_id, user_id))""")
dbx("INSERT INTO task_watchers(task_id,user_id,created_at) VALUES(?,?,?)", (T2, ALICE, "2026-11-01T08:30:00+00:00"))
dbx("INSERT INTO task_watchers(task_id,user_id,created_at) VALUES(?,?,?)", (T2, GINA, "not a time"))
dbx("""INSERT INTO task_bell(task_id,user_id,org_id,level,until,set_by,created_at,updated_at,prev,act,act_by)
       VALUES(?,?,?,'urgent','2026-12-31',?,'2026-11-01T08:30:00+00:00','2026-11-02T09:00:00+00:00',?,'a1',?)""",
    (T2, ALICE, ORG, ALICE, json.dumps({"level": "mute", "until": None, "set_by": None}), ALICE))
box("pass")  # the next start of the app
check(not table_there("task_watchers") and not table_there("task_bell"), "the start dropped the old tables made again")
check(rows(T2) == sorted([(ALICE, "watch"), (GINA, "watch"), (ALICE, "urgent")]), f"their rows moved into obj_follow {rows(T2)}")
m = dbx("""SELECT until::text, set_by, prev->>'level', act, act_by, org_id, created_at::text FROM obj_follow
           WHERE kind='task' AND ref_id=? AND user_id=? AND mode='urgent'""", (T2, ALICE))
check(m and tuple(m[0][i] for i in range(6)) == ("2026-12-31", ALICE, "mute", "a1", ALICE, ORG) and m[0][6].startswith("2026-11-01"),
      f"the bell came along with its day, its undo step, its workspace and its time {m}")
w = dbx("SELECT org_id FROM obj_follow WHERE kind='task' AND ref_id=? AND mode='watch'", (T2,))
check(w and all(x[0] == ORG for x in w), f"the watching rows got the task's workspace {w}")
check(A.get(B + f"/api/tasks/{T2}/watchers").json()["mine"], "the app reads the moved row")

# ================================================================== deleted for good: the rows go with the task
dbx("DELETE FROM tasks WHERE id=?", (T2,))
check(rows(T2) == [], "a task deleted for good takes its rows along")

# ================================================================== a person without an organisation
FT = Fr.post(B + "/api/tasks", json={"title": "Angebot schreiben", "list_id": FL}).json()["id"]
r = Fr.post(B + f"/api/tasks/{FT}/watchers", json={})
check(r.ok and r.json()["mine"], f"freelancer: watches her task {r.status_code} {r.text[:200]}")
r = put(Fr, FT, level="mute")
check(r.ok and r.json()["mine"]["level"] == "mute" and bell(Fr, FT).json()["mine"]["level"] == "mute", f"freelancer: mutes it {r.text[:200]}")
f = dbx("SELECT mode, org_id FROM obj_follow WHERE kind='task' AND ref_id=? AND user_id=? ORDER BY mode", (FT, FID))
check([(x[0], x[1]) for x in f] == [("mute", None), ("watch", None)], f"freelancer: two private rows {f}")
check(Fr.delete(B + f"/api/tasks/{FT}/watchers/{FID}").ok and rows(FT) == [(FID, "mute")], "freelancer: stops watching, the bell stays")

sys.exit(kt.done("p2903_c_follow"))
