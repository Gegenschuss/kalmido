#!/usr/bin/env python3
# kalmido-suite:
"""2.410.0 API tests (leader L), own container (kt.fresh).
 - #3437 a budget counts once per branch: the "Budget h" sum of a project (time_lists in /api/state) counts the subtasks'
   budgets of a task that has some, not its own value as well (the example of the task: 140 h -> 86 h); a deeper level
   counts the same way, a task without valued subtasks counts its own value; the own value stays stored; for a person
   without an organisation the same
 - #3440 "Show completed at the bottom" (checklist / done_at_bottom): a list admin sets it too (like done_in_section), a
   member with edit still gets 403
freelancer-matrix: lists
usage: p24100_l_api_test.py <datadir>"""
import sys

import kt
from kt import B, FAILS, OKS, check, sess  # noqa: F401
from freelancer_fixture import freelancer

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["comments"]})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})


def budget_case(S, tag):
    """The project of the task: top level 3 (no subtasks), then four tasks with own values AND valued subtasks."""
    P = S.post(B + "/api/lists", json={"name": f"Budget {tag}", "ptype": "agency", "time_tracking": True}).json()["id"]
    fb = next(f for f in S.get(B + "/api/state").json()["fields"] if f["list_id"] == P and f["name"] == "Budget h")

    def task(title, v, parent=None):
        b = {"title": title, "list_id": P, "fields": {str(fb["id"]): str(v)}}
        if parent:
            b["parent_id"] = parent
        r = S.post(B + "/api/tasks", json=b)
        assert r.ok, r.text
        return r.json()["id"]

    def total():
        return (S.get(B + "/api/state").json().get("time_lists", {}).get(str(P)) or {}).get("b")

    task("Brief", 3)
    for own, subs in ((10, (11, 4)), (10, (11, 4)), (10, (11, 4, 2)), (24, (24, 12))):
        p = task(f"Episode {own}", own)
        for i, x in enumerate(subs):
            task(f"Part {i}", x, p)
    check(total() == 86, f"{tag}: #3437 header budget once per branch (3 + 15 + 15 + 17 + 36 = 86, not 140): {total()}")
    # a deeper level: a subtask with its own valued subtask counts that one only
    top = task("Deep", 5)
    mid = task("Mid", 4, top)
    task("Leaf", 2, mid)
    check(total() == 88, f"{tag}: #3437 three levels: only the leaf (2) counts: {total()}")
    own = next(t for t in S.get(B + "/api/state").json()["tasks"] if t["id"] == top)
    check(str((own.get("fields") or {}).get(str(fb["id"]))) in ("5", "5.0"), f"{tag}: #3437 the own value stays stored: {own.get('fields')}")
    # a parent without valued subtasks counts its own value
    task("Solo", 7)
    check(total() == 95, f"{tag}: #3437 a task with no valued subtasks counts its own value: {total()}")


budget_case(A, "org-less admin")
FID, Fr = freelancer(B, A)
budget_case(Fr, "freelancer")

# ================================================================== #3440 list admins set "Show completed at the bottom"
L = A.post(B + "/api/lists", json={"name": "Shared project"}).json()["id"]
for u, role in (("bob", "admin"), ("carol", "edit")):
    r = A.put(B + f"/api/lists/{L}/members", json={"user_id": ids[u], "role": role})
    if r.status_code == 409:
        r = A.put(B + f"/api/lists/{L}/members", json={"user_id": ids[u], "role": role, "bridge_ok": True})
    check(r.ok, f"setup: {u} {role} " + r.text[:120])
r = Bo.patch(B + f"/api/lists/{L}", json={"checklist": True})
check(r.ok, f"#3440 a list admin turns it on: {r.status_code} {r.text[:120]}")
check(next(x for x in A.get(B + "/api/state").json()["lists"] if x["id"] == L)["checklist"] == 1, "#3440 stored for everyone (owner sees it)")
r = Bo.patch(B + f"/api/lists/{L}", json={"done_at_bottom": False})
check(r.ok and next(x for x in A.get(B + "/api/state").json()["lists"] if x["id"] == L)["checklist"] == 0, f"#3440 the API name done_at_bottom too: {r.status_code}")
r = Ca.patch(B + f"/api/lists/{L}", json={"checklist": True})
check(r.status_code == 403, f"#3440 a member with edit: 403: {r.status_code}")
r = Bo.patch(B + f"/api/lists/{L}", json={"checklist": True, "kind": "project"})
check(r.status_code == 403, f"#3440 the admin may not change the other owner fields along: {r.status_code}")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
