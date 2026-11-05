#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.558.0 part C (#4591) API test: warranty end and maintenance of office equipment, as with a private device (own container,
workspaces). Invented names only. freelancer-matrix: office
 - a device with warranty end + a maintenance: one task due on the warranty day (deadline, reminder 30 days before) and one
   repeating task (every N months from the next date) in the inbox of the admin who saved, nobody assigned; GET names both tasks
 - a save through the master data way (expect_updated_at) moves the tasks along (same task ids: new date, interval, name);
   a stale version 409 and nothing changes
 - a maintenance taken out / the warranty date emptied: its task is done (never deleted); archived: every task done
 - a member never gets the warranty or maintenance fields
 - deleted into the office trash: the tasks are done; restored: new open tasks
 - a person without an organisation: the same in the personal office (tasks in the own inbox)
 - 2.558.0 D (#4591, review F1): a done maintenance task keeps its moved date through a save, the archive and the trash
usage: p2558_c_eqcare_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta

import requests

from freelancer_fixture import freelancer
from kt import B, H, DATA, check, dbx, done, sess

N = os.path.dirname(os.path.abspath(__file__))
O = "/api/office"
D1 = (date.today() + timedelta(days=400)).isoformat()
D2 = (date.today() + timedelta(days=500)).isoformat()
M1 = (date.today() + timedelta(days=60)).isoformat()

if not os.environ.get("KMT_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo = sess("bob")
FEAT = "cal,comments,collab,office,clients,docs"
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
Bo.post(B + f"/api/orgs/{ORG}/join")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
FID, Fr = freelancer(B, A)


def task(tid):
    r = dbx("SELECT t.id, t.list_id, t.title, t.due, t.repeat, t.reminders, t.deadline, t.status, t.deleted_at, t.assignee_id, t.fam, "
            "l.is_inbox, l.owner_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,))
    return dict(r[0]) if r else None


def case(s, who, uid, member=None):
    r = s.post(B + O + "/equipment", json={"name": f"Kamera {who}", "warranty_until": D1,
                                           "maint": [{"kind": "inspection", "every_months": 12, "next": M1}]})
    check(r.status_code == 201, f"{who}: device with warranty and maintenance {r.status_code} {r.text[:300]}")
    eid = r.json()["id"]
    g = s.get(B + O + f"/equipment/{eid}").json()
    wt, mt = (g.get("warranty_task") or {}).get("id"), ((g.get("maint") or [{}])[0].get("task") or {}).get("id")
    check(g.get("warranty_until") == D1 and wt and mt and g["maint"][0].get("id"), f"{who}: GET names both tasks {str(g)[:400]}")
    w, m = task(wt), task(mt)
    check(w and w["due"] == D1 and w["deadline"] == 2 and "Kamera" in w["title"] and str(30 * 1440) in w["reminders"] and not w["repeat"]
          and w["is_inbox"] == 1 and w["owner_id"] == uid and w["assignee_id"] is None and w["status"] == 0,
          f"{who}: warranty task due on the day, in the own inbox, nobody assigned {w}")
    check(m and m["due"] == M1 and m["repeat"] == "FREQ=YEARLY" and "Inspection" in m["title"] and m["is_inbox"] == 1 and m["owner_id"] == uid,
          f"{who}: maintenance = repeating task {m}")
    check(json.loads(w["fam"]).get("office_equipment") == eid, f"{who}: the task is marked for the device")
    # a save with the version: the tasks follow (same ids)
    r = s.patch(B + O + f"/equipment/{eid}", json={"name": f"Kamera {who} B", "warranty_until": D2, "expect_updated_at": g["updated_at"],
                                                   "maint": [{"id": g["maint"][0]["id"], "kind": "calibration", "every_months": 6, "next": M1}]})
    check(r.ok, f"{who}: saved {r.status_code} {r.text[:200]}")
    w, m = task(wt), task(mt)
    check(w["due"] == D2 and "Kamera" in w["title"] and " B" in w["title"], f"{who}: warranty task moved along {w}")
    check(m["repeat"] == "FREQ=MONTHLY;INTERVAL=6" and "Calibration" in m["title"] and m["status"] == 0, f"{who}: maintenance task follows {m}")
    g2 = s.get(B + O + f"/equipment/{eid}").json()
    check(g2["warranty_task"]["id"] == wt and g2["maint"][0]["task"]["id"] == mt, f"{who}: still the same tasks")
    r = s.patch(B + O + f"/equipment/{eid}", json={"warranty_until": D1, "expect_updated_at": g["updated_at"]})
    check(r.status_code == 409 and task(wt)["due"] == D2, f"{who}: a stale version 409, nothing changed {r.status_code}")
    if member:
        j = member.get(B + O + f"/equipment/{eid}").json()
        check(j.get("id") == eid and not ({"warranty_until", "maint", "warranty_task_id", "warranty_task"} & set(j)),
              f"{who}: a member gets none of the fields {sorted(j)}")
    # a second maintenance, then the first taken out and the warranty emptied
    r = s.patch(B + O + f"/equipment/{eid}", json={"warranty_until": "", "expect_updated_at": g2["updated_at"],
                                                   "maint": [{"kind": "service", "label": "Sensor reinigen", "every_months": 3, "next": M1}]})
    g3 = s.get(B + O + f"/equipment/{eid}").json()
    t2 = ((g3.get("maint") or [{}])[0].get("task") or {}).get("id")
    check(r.ok and task(wt)["status"] != 0 and task(mt)["status"] != 0 and task(wt)["deleted_at"] is None,
          f"{who}: warranty emptied + maintenance taken out: their tasks done, not deleted {r.text[:200]}")
    check(t2 and t2 != mt and task(t2)["title"].startswith("Sensor reinigen") and task(t2)["repeat"] == "FREQ=MONTHLY;INTERVAL=3"
          and g3["maint"][0]["id"] != g2["maint"][0]["id"], f"{who}: the new maintenance has its own task {g3.get('maint')}")
    # archived: done; out of the archive again: open again
    s.patch(B + O + f"/equipment/{eid}", json={"archived": 1})
    check(task(t2)["status"] != 0, f"{who}: archived, the tasks are done")
    s.patch(B + O + f"/equipment/{eid}", json={"archived": 0})
    g4 = s.get(B + O + f"/equipment/{eid}").json()
    t3 = g4["maint"][0]["task"]["id"]
    check(task(t3)["status"] == 0 and task(t3)["repeat"], f"{who}: out of the archive: an open task again")
    # deleted into the trash, restored
    r = s.delete(B + O + f"/equipment/{eid}")
    tid = r.json().get("trash_id")
    check(r.ok and tid and task(t3)["status"] != 0, f"{who}: deleted, its task done {r.text[:200]}")
    r = s.post(B + O + f"/trash/{tid}/restore")
    g5 = s.get(B + O + f"/equipment/{eid}").json()
    t4 = ((g5.get("maint") or [{}])[0].get("task") or {}).get("id")
    check(r.ok and t4 and task(t4)["status"] == 0, f"{who}: restored, an open task again {r.text[:200]} {g5.get('maint')}")
    # a device without dates makes no task
    n0 = dbx("SELECT COUNT(*) FROM tasks")[0][0]
    check(s.post(B + O + "/equipment", json={"name": f"Stativ {who}"}).status_code == 201 and dbx("SELECT COUNT(*) FROM tasks")[0][0] == n0,
          f"{who}: a device without dates makes no task")
    r = s.post(B + O + "/equipment", json={"name": "X", "maint": [{"kind": "polish", "every_months": 12}]})
    check(r.status_code == 400, f"{who}: an unknown kind 400 {r.status_code}")




def moved_on(s, who):
    """2.558.0 D (#4591, review F1): a maintenance task done moves on in the same row; a save without the maintenance, the
    archive and the office trash never set it back to the old date, and a task made again is never overdue."""
    r = s.post(B + O + "/equipment", json={"name": f"Drucker {who}", "maint": [{"kind": "service", "every_months": 3, "next": M1}]})
    eid = r.json()["id"]
    mt = s.get(B + O + f"/equipment/{eid}").json()["maint"][0]["task"]["id"]
    r = s.post(B + f"/api/tasks/{mt}/complete")
    d1 = task(mt)["due"]
    check(r.ok and task(mt)["status"] == 0 and d1 > M1, f"{who}: done, the repeating task moved on {r.status_code} {d1}")
    r = s.patch(B + O + f"/equipment/{eid}", json={"name": f"Drucker {who} 2"})
    check(r.ok and task(mt)["due"] == d1 and "2" in task(mt)["title"], f"{who}: a save without the maintenance keeps the date {task(mt)}")
    g = s.get(B + O + f"/equipment/{eid}").json()
    check(g["maint"][0]["next"] == d1, f"{who}: the stored next follows the task {g['maint']}")
    s.patch(B + O + f"/equipment/{eid}", json={"archived": 1})
    s.patch(B + O + f"/equipment/{eid}", json={"archived": 0})
    t2 = s.get(B + O + f"/equipment/{eid}").json()["maint"][0]["task"]["id"]
    check(t2 != mt and task(t2)["status"] == 0 and task(t2)["due"] == d1, f"{who}: out of the archive at the moved date {task(t2)}")
    s.post(B + f"/api/tasks/{t2}/complete")
    d2 = task(t2)["due"]
    tid = s.delete(B + O + f"/equipment/{eid}").json().get("trash_id")
    s.post(B + O + f"/trash/{tid}/restore")
    t3 = s.get(B + O + f"/equipment/{eid}").json()["maint"][0]["task"]["id"]
    check(d2 > d1 and task(t3)["status"] == 0 and task(t3)["due"] == d2, f"{who}: restored from the trash at the moved date {d2} {task(t3)}")
    # an overdue maintenance comes back at today, not in the past
    past = (date.today() - timedelta(days=20)).isoformat()
    eid = s.post(B + O + "/equipment", json={"name": f"Waage {who}", "maint": [{"kind": "calibration", "every_months": 12, "next": past}]}).json()["id"]
    s.patch(B + O + f"/equipment/{eid}", json={"archived": 1})
    s.patch(B + O + f"/equipment/{eid}", json={"archived": 0})
    t4 = s.get(B + O + f"/equipment/{eid}").json()["maint"][0]["task"]["id"]
    check(task(t4)["status"] == 0 and task(t4)["due"] >= date.today().isoformat(), f"{who}: revived, never overdue {task(t4)}")


case(A, "alice", ALICE, member=Bo)
case(Fr, "frida", FID)
moved_on(A, "alice")
moved_on(Fr, "frida")
sys.exit(done("p2558_c_eqcare"))
