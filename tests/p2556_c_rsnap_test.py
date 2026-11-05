#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.556.0 C (#4583) API test: the completed copy of a recurring task keeps what its subtasks were (tasks.sub_snapshot,
tasks/lifecycle.rsn_take). Own container. Invented people only (example.com).
freelancer-matrix: tasks (a person without an organisation, the same round)
 - 5 subtasks, 3 done, the task ticked: the copy says 3 of 5 with the titles in their order and their state; it has no
   subtasks of its own; the original's subtasks are all open again and the original carries no snapshot
 - the snapshot stays as it was: renaming / ticking the original's subtasks afterwards does not change it
 - undo: the copy is gone (with its snapshot), the 3 subtasks are done again, the task is back on its day
 - a birthday (FAM_OCC): its gift ideas keep their ticks, the copy has no snapshot
 - a person's API token (REST v1) reads the snapshot on the copy
usage: p2556_c_rsnap_test.py <datadir>"""
import os
import sys
import requests

import kt
import testclock
from kt import B, check

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

kt.docker_logs_on_first_fail()
kt.fresh()
A = kt.setup()
assert A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"}).ok
FID, Fr = freelancer(B, A, "frieda")
TODAY = testclock.today().isoformat()


def copy_of(lid, tid):
    rows = kt.dbx("SELECT id FROM tasks WHERE list_id=? AND id<>? AND parent_id IS NULL AND status=2 AND deleted_at IS NULL ORDER BY id",
                  (lid, tid))
    return [r[0] for r in rows]


def states(ids):
    st = dict(kt.dbx(f"SELECT id, status FROM tasks WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)))
    return [st.get(i) for i in ids]


def round_of(s, who):
    lid = s.post(B + "/api/lists", json={"name": f"Routine {who}"}).json()["id"]
    r = s.post(B + "/api/tasks", json={"title": f"Weekly review {who}", "list_id": lid, "due": TODAY, "repeat": "FREQ=WEEKLY"})
    assert r.ok, r.text
    tid = r.json()["id"]
    subs = []
    for i in range(1, 6):
        r = s.post(B + "/api/tasks", json={"title": f"Step {i} {who}", "list_id": lid, "parent_id": tid})
        assert r.ok, r.text
        subs.append(r.json()["id"])
    for k in subs[:3]:
        assert s.post(B + f"/api/tasks/{k}/complete", json={}).ok
    j = s.post(B + f"/api/tasks/{tid}/complete", json={}).json()
    check(j.get("next_due") and j["next_due"] > TODAY, f"{who}: ticked, the task moves on {j.get('next_due')}")
    cps = copy_of(lid, tid)
    check(len(cps) == 1, f"{who}: one completed copy {cps}")
    cp = cps[0] if cps else 0
    ss = s.get(B + f"/api/tasks/{cp}").json().get("sub_snapshot") or {}
    items = ss.get("items") or []
    check(ss.get("done") == 3 and ss.get("total") == 5, f"{who}: the copy says 3 of 5 {ss}")
    check([i.get("title") for i in items] == [f"Step {i} {who}" for i in range(1, 6)]
          and [i.get("status") for i in items] == [2, 2, 2, 0, 0] and all(i.get("depth") == 1 for i in items),
          f"{who}: the titles in their order with their state {items}")
    check(not kt.dbx("SELECT 1 FROM tasks WHERE parent_id=?", (cp,)), f"{who}: the copy has no subtasks of its own")
    check(states(subs) == [0] * 5, f"{who}: the original's subtasks are all open again {states(subs)}")
    check("sub_snapshot" not in s.get(B + f"/api/tasks/{tid}").json(), f"{who}: the original carries no snapshot")
    # undo: the copy with its snapshot goes, the round comes back
    u = s.post(B + f"/api/tasks/{tid}/undo", json=j.get("undo") or {})
    check(u.ok and u.json().get("due") == TODAY, f"{who}: undo, back on its day {u.status_code} {u.text[:200]}")
    check(not kt.dbx("SELECT 1 FROM tasks WHERE id=?", (cp,)), f"{who}: undo removed the copy (and its snapshot)")
    check(states(subs) == [2, 2, 2, 0, 0], f"{who}: undo, the 3 subtasks are done again {states(subs)}")
    # once more, then the original's subtasks change: the snapshot stays as it was
    j = s.post(B + f"/api/tasks/{tid}/complete", json={}).json()
    cp = (copy_of(lid, tid) or [0])[0]
    assert s.patch(B + f"/api/tasks/{subs[0]}", json={"title": f"Renamed {who}"}).ok
    assert s.post(B + f"/api/tasks/{subs[4]}/complete", json={}).ok
    ss2 = s.get(B + f"/api/tasks/{cp}").json().get("sub_snapshot") or {}
    check(ss2.get("done") == 3 and (ss2.get("items") or [{}])[0].get("title") == f"Step 1 {who}",
          f"{who}: later changes leave the snapshot as it was {ss2}")
    return cp


ACP = round_of(A, "alice")
FCP = round_of(Fr, "frieda")  # freelancer-matrix: tasks

# ---- REST v1 with a person's token: the snapshot is there for agents / scripts, too
tok = Fr.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read"]}).json().get("token")
r = requests.get(B + f"/api/v1/tasks/{FCP}", headers={"Authorization": "Bearer " + (tok or "")}, timeout=30)
check(r.ok and (r.json().get("sub_snapshot") or {}).get("total") == 5, f"v1: the copy's snapshot {r.status_code} {r.text[:200]}")

# ---- a birthday: the gift ideas keep their ticks, no snapshot
lid = A.post(B + "/api/lists", json={"name": "Birthdays"}).json()["id"]
r = A.post(B + "/api/tasks", json={"title": "Erika", "list_id": lid, "due": TODAY, "repeat": "FREQ=YEARLY"})
O = r.json()["id"]
r = A.patch(B + f"/api/tasks/{O}", json={"fam": {"kind": "birthday", "name": "Erika"}})
check(r.ok, f"a birthday {r.status_code} {r.text[:200]}")
g = [A.post(B + "/api/tasks", json={"title": f"Gift {i}", "list_id": lid, "parent_id": O}).json()["id"] for i in (1, 2)]
A.post(B + f"/api/tasks/{g[0]}/complete", json={})
A.post(B + f"/api/tasks/{O}/complete", json={})
oc = (copy_of(lid, O) or [0])[0]
check(oc and "sub_snapshot" not in A.get(B + f"/api/tasks/{oc}").json(), "birthday: the copy has no snapshot")
check(states(g) == [2, 0], f"birthday: the given gift stays ticked {states(g)}")

sys.exit(kt.done("p2556_c_rsnap"))
