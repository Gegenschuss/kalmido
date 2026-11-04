#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.528.0 part B (#4305, A13): a change of a time entry carries what the device saw (_prev). Two sessions of a person
without an organisation (freelancer-matrix: time):
 - the second device changes the note, the first one (still showing the old note) changes it too -> 409 with the current
   entry (key "entry"), the second device's note stays
 - a field changed elsewhere that this change does not touch is no conflict (the note changed, the times are sent)
 - _prev equal to the server's state -> applied; the same new value on both devices -> no conflict
 - times compared as instants (another notation of the same time is no conflict), billable and the task as well
 - without _prev (API v1, old clients): as before, the last write wins
usage: p2528_b_time_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

kt.fresh(prefix="P2528BT")
A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "time_all": True})
FID, F1 = freelancer(B, A)
F2 = login(B, "frida")  # the same person on a second device
L = F1.post(B + "/api/lists", json={"name": "Studio", "kind": "project", "time_tracking": 1}).json()["id"]
T = F1.post(B + "/api/tasks", json={"title": "Logo draft", "list_id": L}).json()["id"]
T2 = F1.post(B + "/api/tasks", json={"title": "Website", "list_id": L}).json()["id"]
r = F1.post(B + "/api/time/entries", json={"task_id": T, "start": "2026-10-05T09:00", "minutes": 60, "note": "Sketches"})
check(r.ok, f"entry created {r.status_code} {r.text[:200]}")
E = r.json()
EID = E["id"]
U = f"/api/time/entries/{EID}"
get = lambda: [x for x in F1.get(B + f"/api/time/entries?task_id={T}").json()["entries"] if x["id"] == EID][0]  # noqa: E731

# the other device changes the note; this one still shows "Sketches"
check(F2.patch(B + U, json={"note": "Sketches and colours", "_prev": {"note": "Sketches"}}).ok, "device 2: note changed")
r = F1.patch(B + U, json={"note": "Sketches, first round", "_prev": {"note": "Sketches"}})
check(r.status_code == 409, f"device 1: changed meanwhile -> 409 ({r.status_code} {r.text[:200]})")
check(r.json().get("entry", {}).get("note") == "Sketches and colours", f"the answer carries the current entry {r.text[:300]}")
check(get()["note"] == "Sketches and colours", "the other device's note stays")

# a field not in this change: no conflict (the times move, the note changed elsewhere is not sent)
cur = get()
r = F1.patch(B + U, json={"start": "2026-10-05T10:00:00", "end": "2026-10-05T11:30:00",
                          "_prev": {"start": cur["start"], "end": cur["end"]}})
check(r.ok, f"times with the right base -> applied {r.status_code} {r.text[:200]}")
x = get()
check(x["seconds"] == 5400 and x["note"] == "Sketches and colours", f"times changed, note kept {x}")

# the times changed elsewhere meanwhile -> 409; another notation of the same instant is no conflict
r = F2.patch(B + U, json={"end": "2026-10-05T12:00:00", "_prev": {"end": x["end"]}})
check(r.ok, f"device 2: end moved {r.status_code} {r.text[:200]}")
r = F1.patch(B + U, json={"end": "2026-10-05T11:45:00", "_prev": {"end": x["end"]}})
check(r.status_code == 409, f"end changed meanwhile -> 409 ({r.status_code})")
check(get()["end"] == r.json().get("entry", {}).get("end"), "the end of device 2 stays")
y = get()
r = F1.patch(B + U, json={"note": "Round 2", "_prev": {"note": y["note"], "start": y["start"].replace("+00:00", "Z")}})
check(r.ok, f"the same instant in another notation is no conflict {r.status_code} {r.text[:200]}")

# the same new value on both devices: no conflict
check(F2.patch(B + U, json={"note": "Final", "_prev": {"note": "Round 2"}}).ok, "device 2: Final")
check(F1.patch(B + U, json={"note": "Final", "_prev": {"note": "Round 2"}}).ok, "device 1: the same value -> no conflict")

# billable and the task
check(F2.patch(B + U, json={"billable": False, "_prev": {"billable": True}}).ok, "device 2: not billable")
r = F1.patch(B + U, json={"billable": True, "note": "x", "_prev": {"billable": True, "note": "Final"}})
check(r.status_code == 409 and get()["billable"] is False and get()["note"] == "Final", f"billable changed meanwhile -> 409, nothing written {r.status_code}")
check(F2.patch(B + U, json={"task_id": T2, "_prev": {"task_id": T}}).ok, "device 2: other task")
r = F1.patch(B + U, json={"task_id": T, "_prev": {"task_id": T}})
check(r.status_code == 409, f"task changed meanwhile -> 409 ({r.status_code})")

# without _prev: as before (the API, old clients)
r = F1.patch(B + U, json={"note": "Last word"})
check(r.ok and r.json().get("note") == "Last word", f"without _prev the change goes through {r.status_code}")
sys.exit(kt.done("p2528_b_time"))
