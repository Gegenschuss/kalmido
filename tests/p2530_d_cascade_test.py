#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.530.0 D (#4316, audit #2425 B2/B4/B9/B10) API tests, own container: deleting for good no longer takes along what the
trash did not show.
 - video sign-offs: a task deleted for good (?hard=1, "Empty trash"), a project deleted for good from the projects' trash --
   their video reviews go into the video trash (deleted_at), with their approval records, and can be restored; a review at a
   task whose project lives on moves to that project
 - GET /api/trash/purge-info names the numbers first: tasks, customer reports (portal_tickets), video reviews, kept by law
 - lists.retain_until (kept by law) holds on every way: ?hard=1 409, "Empty trash" skips and counts them (kept_law), the
   files' trash run keeps their files (attachments_kept)
 - an instance admin's "Empty trash" takes only the own trash; the other owners' trash only with ?all=1 (others = the number)
The case without an organisation (freelancer fixture) runs the video / purge-info / retain steps too.
freelancer-matrix: tasks, videos
usage: p2530_d_cascade_test.py <datadir>"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, DATA, check, dbx, done  # noqa: E402
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

OLD = "2020-01-01T00:00:00+00:00"
NOW = "2026-11-01T10:00:00Z"
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,clients,videos", "tour": "done"})  # 2.623.0 (#4765): + videos, the module Approval (creating needs it)
A_ID = A.get(B + "/api/state").json()["me"]["id"]
FID, Fr = freelancer(B, A)


def sql(q, a=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # noqa: BLE001 - an UPDATE without rows
            return []
    finally:
        c.close()


def box(code, on=False):
    """Python in the app container (a watchdog run called directly); on = KALMIDO_PURGE_TRASH=1. -> its output."""
    e = ["-e", "KALMIDO_PURGE_TRASH=1"] if on else []
    out = subprocess.run(["docker", "exec", *e, CT, "python", "-c", "import app\nc = app.connect()\n" + code + "\nc.close()"],
                         capture_output=True, text=True)
    return out.stdout + out.stderr


def review(s, **place):
    r = s.post(B + "/api/videos", json={"title": "Cut", "url": "https://vimeo.com/123456789", **place})
    assert r.ok, r.text
    vid = r.json()["id"]
    so = s.post(B + f"/api/videos/{vid}/signoff", json={})
    assert so.ok, so.text
    return vid


def vrow(vid):
    r = dbx("SELECT task_id, list_id, client_id, deleted_at FROM video_reviews WHERE id=?", (vid,))
    return r[0] if r else None


def signoffs(vid):
    return dbx("SELECT COUNT(*) FROM office_signoffs WHERE video_id=?", (vid,))[0][0]


def video_case(s, who):
    lid = s.post(B + "/api/lists", json={"name": f"Film {who}", "kind": "project"}).json()["id"]
    # ?hard=1: the review at the task moves to the task's project, into the video trash, with its approval record
    t1 = s.post(B + "/api/tasks", json={"title": "Cut one", "list_id": lid}).json()["id"]
    v1 = review(s, task_id=t1)
    sql("INSERT INTO portal_tickets(task_id, list_id, owner_id, name, email, token, token_hash, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (t1, lid, None, "Example Person", "person@example.com", f"tok{who}{t1}", f"hash{who}{t1}", NOW))
    check(s.delete(B + f"/api/tasks/{t1}").ok, f"{who}: task into the trash")
    pi = s.get(B + f"/api/trash/purge-info?task={t1}").json()
    check(pi.get("tasks") == 1 and pi.get("videos") == 1 and pi.get("tickets") == 1 and pi.get("kept_law") == 0,
          f"{who}: purge-info names the task, its video review and its customer report {pi}")
    check(s.delete(B + f"/api/tasks/{t1}?hard=1").ok, f"{who}: deleted for good")
    r = vrow(v1)
    check(r is not None and r[0] is None and r[1] == lid and r[3], f"{who}: the review lies in the video trash at the project {r}")
    check(signoffs(v1) == 1, f"{who}: its approval record stays")
    check(s.post(B + f"/api/videos/{v1}/restore").ok and v1 in [x["id"] for x in s.get(B + f"/api/videos?list_id={lid}").json()["reviews"]],
          f"{who}: restored, it shows at the project")
    # "Empty trash": the same
    t2 = s.post(B + "/api/tasks", json={"title": "Cut two", "list_id": lid}).json()["id"]
    t2s = s.post(B + "/api/tasks", json={"title": "Sub of it", "list_id": lid, "parent_id": t2}).json()["id"]
    v2 = review(s, task_id=t2s)
    check(s.delete(B + f"/api/tasks/{t2}").ok, f"{who}: task with subtask into the trash")
    pi = s.get(B + "/api/trash/purge-info").json()
    check(pi.get("tasks") == 2 and pi.get("videos") == 1, f"{who}: purge-info of 'Empty' counts the subtask's video review {pi}")
    r = s.delete(B + "/api/trash")
    check(r.ok and r.json().get("deleted") == 2, f"{who}: emptied {r.text[:200]}")
    r = vrow(v2)
    check(r is not None and r[0] is None and r[1] == lid and r[3] and signoffs(v2) == 1, f"{who}: the subtask's review is in the video trash {r}")
    # a project deleted for good: its reviews (at the project and at its tasks) go to the video trash without a place
    l3 = s.post(B + "/api/lists", json={"name": f"Old film {who}", "kind": "project"}).json()["id"]
    t3 = s.post(B + "/api/tasks", json={"title": "Cut three", "list_id": l3}).json()["id"]
    v3, v4 = review(s, list_id=l3), review(s, task_id=t3)
    s.patch(B + f"/api/lists/{l3}", json={"archived": True})
    check(s.delete(B + f"/api/lists/{l3}").ok, f"{who}: project into the projects' trash")
    pi = s.get(B + f"/api/trash/purge-info?list={l3}").json()
    check(pi.get("tasks") == 1 and pi.get("videos") == 2, f"{who}: purge-info of the project {pi}")
    check(s.delete(B + f"/api/trash/lists/{l3}").ok, f"{who}: project deleted for good")
    for v in (v3, v4):
        r = vrow(v)
        check(r is not None and r[0] is None and r[1] is None and r[3] and signoffs(v) == 1, f"{who}: review {v} kept in the video trash {r}")
    check(s.post(B + f"/api/videos/{v3}/restore").ok, f"{who}: a review without a place can still be restored by its owner")
    # kept by law: ?hard=1 refuses, "Empty" skips and counts, the file run keeps the file
    l5 = s.post(B + "/api/lists", json={"name": f"Kept {who}", "kind": "project"}).json()["id"]
    t5 = s.post(B + "/api/tasks", json={"title": "Receipt work", "list_id": l5}).json()["id"]
    r = s.post(B + f"/api/tasks/{t5}/attachments", files={"file": ("notes.txt", b"kept note\n" * 20, "text/plain")})
    check(r.ok, f"{who}: setup file {r.text[:120]}")
    aid = dbx("SELECT id FROM attachments WHERE task_id=?", (t5,))[0][0]
    check(s.delete(B + f"/api/attachments/{aid}").ok and s.delete(B + f"/api/tasks/{t5}").ok, f"{who}: file and task into the trash")
    sql("UPDATE lists SET retain_until='2099-12-31' WHERE id=?", (l5,))
    sql("UPDATE attachments SET deleted_at=? WHERE id=?", (OLD, aid))
    r = s.delete(B + f"/api/tasks/{t5}?hard=1")
    check(r.status_code == 409 and dbx("SELECT 1 FROM tasks WHERE id=?", (t5,)), f"{who}: ?hard=1 of a kept project: 409, the task stays {r.status_code}")
    pi = s.get(B + "/api/trash/purge-info").json()
    check(pi.get("tasks") == 0 and pi.get("kept_law") == 1, f"{who}: purge-info counts it as kept by law {pi}")
    r = s.delete(B + "/api/trash")
    check(r.ok and r.json().get("deleted") == 0 and r.json().get("kept_law") == 1 and dbx("SELECT 1 FROM tasks WHERE id=?", (t5,)),
          f"{who}: 'Empty' keeps it and counts it {r.text[:200]}")
    out = box("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))", on=True)
    check(dbx("SELECT 1 FROM attachments WHERE id=?", (aid,)) and "'attachments_kept': " in out and "Traceback" not in out,
          f"{who}: the files' run keeps the file of a kept project {out[-400:]}")
    sql("UPDATE lists SET retain_until='2020-12-31' WHERE id=?", (l5,))
    out = box("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))", on=True)
    check(not dbx("SELECT 1 FROM attachments WHERE id=?", (aid,)), f"{who}: after the end of the period the file goes {out[-300:]}")
    check(s.delete(B + "/api/trash").json().get("deleted") == 1, f"{who}: after the end of the period 'Empty' deletes the task")


video_case(A, "alice")
video_case(Fr, "frida")

# ================================================================== B4: an instance admin empties the own trash only
BOB, Bo = freelancer(B, A, "bob")
LB = Bo.post(B + "/api/lists", json={"name": "Bobs shared", "kind": "project"}).json()["id"]
check(Bo.put(B + f"/api/lists/{LB}/members", json={"user_id": A_ID, "role": "edit"}).ok, "setup: alice edits bob's project")
TB = Bo.post(B + "/api/tasks", json={"title": "Bob's draft", "list_id": LB}).json()["id"]
VB = review(Bo, task_id=TB)
check(Bo.delete(B + f"/api/tasks/{TB}").ok, "setup: bob trashes his task")
TA = A.post(B + "/api/tasks", json={"title": "Alice own", "list_id": A.post(B + "/api/lists", json={"name": "Alice"}).json()["id"]}).json()["id"]
check(A.delete(B + f"/api/tasks/{TA}").ok, "setup: alice trashes her own task")
pg = A.get(B + "/api/tasks?scope=trash").json()
check(pg.get("deletable") == 1 and pg.get("others") == 1, f"admin's trash page: deletable 1 (own), others 1 {pg.get('deletable')} {pg.get('others')}")
pi = A.get(B + "/api/trash/purge-info").json()
check(pi.get("tasks") == 1 and pi.get("others") == 1, f"admin: purge-info own 1, others 1 {pi}")
check(A.get(B + "/api/trash/purge-info?all=1").json().get("tasks") == 2, "admin: purge-info with all=1 names both")
r = A.delete(B + "/api/trash")
check(r.ok and r.json().get("deleted") == 1 and r.json().get("others") == 1, f"admin: 'Empty' deletes only her own {r.text[:200]}")
check(dbx("SELECT 1 FROM tasks WHERE id=?", (TB,)) and not dbx("SELECT 1 FROM tasks WHERE id=?", (TA,)), "admin: bob's trashed task stays")
check(Bo.get(B + "/api/trash/purge-info").json().get("others") == 0, "a person without admin rights: others is always 0")
r = A.delete(B + "/api/trash?all=1")
check(r.ok and r.json().get("deleted") == 1 and not dbx("SELECT 1 FROM tasks WHERE id=?", (TB,)), f"admin with all=1: the other owner's trash too {r.text[:200]}")
r = vrow(VB)
check(r is not None and r[3] and signoffs(VB) == 1, f"admin with all=1: bob's video review lies in the video trash {r}")
check(Bo.post(B + f"/api/videos/{VB}/restore").ok, "bob restores his video review")
check(Bo.get(B + "/api/trash/purge-info?task=999999999").status_code == 404, "purge-info of an unknown task: 404")
sys.exit(done("p2530_d_cascade"))
