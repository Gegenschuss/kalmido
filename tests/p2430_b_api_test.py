#!/usr/bin/env python3
"""2.43.0 API tests, part B, own container (start.sh):
 - #1330 dependencies by dragging (the client sends the same POST /api/deps as the dependency field): a loop is refused
   with a message that names both tasks (also through a third task), the reverse direction after removing works; rights:
   a viewer of a shared project cannot let a task wait, an editor cannot use a blocker in a project they do not see, a
   task outside projects gets no dependency; DELETE (the undo) removes it again
 - #1003 several tasks at once (one POST /api/tasks/batch patch_each = one undo step): several tasks become subtasks of
   one, in the given order; a task whose own subtasks would go deeper than five levels (2.156.0, #1949) is refused (the others move);
   subtasks out of their parent keep their order, assignee and dates; the undo (patch_each back with _prev) restores the
   parents; a viewer changes nothing, nobody nests under a task of a list they cannot see; moving into another list takes
   the subtasks along
usage: p2430_b_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


if not os.environ.get("P2430_B_NOSTART"):  # (a quick local run against a running server sets it)
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}


def task(s, title, lid, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def state(s):
    return {t["id"]: t for t in s.get(B + "/api/state").json()["tasks"]}


def batch(s, items):
    return s.post(B + "/api/tasks/batch", json={"ids": [int(i) for i in items], "action": "patch_each",
                                                "data": {"items": {str(k): v for k, v in items.items()}}})


# ======================================================================= #1330 dependencies
P = A.post(B + "/api/lists", json={"name": "Launch", "kind": "project"}).json()["id"]
SP = A.post(B + "/api/lists", json={"name": "Shared project", "kind": "project"}).json()["id"]
HID = A.post(B + "/api/lists", json={"name": "Alice only", "kind": "project"}).json()["id"]
PLAIN = A.post(B + "/api/lists", json={"name": "Errands"}).json()["id"]
A.put(B + f"/api/lists/{SP}/members", json={"user_id": ids["bob"], "role": "edit"})
A.put(B + f"/api/lists/{SP}/members", json={"user_id": ids["carol"], "role": "view"})
D1, D2, D3 = task(A, "Design", P), task(A, "Build", P), task(A, "Ship", P)
r = A.post(B + "/api/deps", json={"task_id": D2, "blocker_id": D1})
check(r.ok, f"#1330: Build waits on Design {r.status_code} {r.text[:200]}")
r = A.post(B + "/api/deps", json={"task_id": D1, "blocker_id": D2})
e = r.json().get("error", "")
check(r.status_code == 400 and "circular" in e and "“Design”" in e and "“Build”" in e, f"#1330: a direct loop is refused, both names: {r.status_code} {e}")
A.post(B + "/api/deps", json={"task_id": D3, "blocker_id": D2})
r = A.post(B + "/api/deps", json={"task_id": D1, "blocker_id": D3})
e = r.json().get("error", "")
check(r.status_code == 400 and "“Ship” already waits on “Design”" in e, f"#1330: a loop through a third task names the ends: {e}")
r = A.delete(B + f"/api/deps/{D2}/{D1}")
check(r.ok and not state(A)[D2].get("blockers"), f"#1330: removing (the undo) {r.status_code}")
r = A.post(B + "/api/deps", json={"task_id": D1, "blocker_id": D2})
check(r.ok, f"#1330: once the old link is gone the other direction works {r.status_code} {r.text[:200]}")
check(D2 in (state(A)[D1].get("blockers") or []), "#1330: the state carries the new blocker")
# rights
S1, S2 = task(A, "Shared one", SP), task(A, "Shared two", SP)
H1 = task(A, "Hidden blocker", HID)
r = Ca.post(B + "/api/deps", json={"task_id": S1, "blocker_id": S2})
check(r.status_code in (403, 404), f"#1330: a viewer cannot let a task wait {r.status_code}")
r = Bo.post(B + "/api/deps", json={"task_id": S1, "blocker_id": S2})
check(r.ok, f"#1330: an editor of the shared project can {r.status_code} {r.text[:200]}")
r = Bo.post(B + "/api/deps", json={"task_id": S2, "blocker_id": H1})
check(r.status_code in (403, 404), f"#1330: no blocker from a project the editor does not see {r.status_code}")
r = Bo.post(B + "/api/deps", json={"task_id": H1, "blocker_id": S2})
check(r.status_code in (403, 404), f"#1330: no waiting task in a project the editor does not see {r.status_code}")
E1, E2 = task(A, "Buy milk", PLAIN), task(A, "Buy bread", PLAIN)
r = A.post(B + "/api/deps", json={"task_id": E1, "blocker_id": E2})
check(r.status_code >= 400, f"#1330: dependencies only between project tasks {r.status_code}")
r = Bo.delete(B + f"/api/deps/{S1}/{S2}")
check(r.ok, f"#1330: the editor's undo removes it {r.status_code}")

# ======================================================================= #1003 several tasks at once
W = A.post(B + "/api/lists", json={"name": "Team work"}).json()["id"]
W2 = A.post(B + "/api/lists", json={"name": "Later"}).json()["id"]
A.put(B + f"/api/lists/{W}/members", json={"user_id": ids["bob"], "role": "edit"})
A.put(B + f"/api/lists/{W}/members", json={"user_id": ids["carol"], "role": "view"})
TOP = task(A, "Release notes", W)
X, Y, Z = task(A, "Collect changes", W), task(A, "Write intro", W), task(A, "Proofread", W)
DEEP = task(A, "Screenshots", W)
DK = task(A, "Shot of the list", W, parent_id=DEEP)
# 2.156.0 (#1949): five levels -> Screenshots needs three levels below it to be too deep under MID
DK3 = task(A, "Export", W, parent_id=task(A, "Crop", W, parent_id=DK))
MID = task(A, "Chapter one", W, parent_id=TOP)
# several onto one: X, Y, Z under TOP in this order (after its own subtask)
r = batch(A, {X: {"parent_id": TOP, "sort": 10}, Y: {"parent_id": TOP, "sort": 11}, Z: {"parent_id": TOP, "sort": 12}})
j = r.json()
check(r.ok and j.get("count") == 3 and not j.get("errors"), f"#1003: three tasks become subtasks in one batch {r.status_code} {j}")
st = state(A)
kids = sorted([t for t in st.values() if t.get("parent_id") == TOP], key=lambda t: t["sort"])
check([t["id"] for t in kids] == [MID, X, Y, Z], f"#1003: their order is kept after the own subtask: {[t['title'] for t in kids]}")
# depth: DEEP has three levels below it; under MID (level 2) it would be level 3 with its last one on level 6 -> refused, X2 moves
X2 = task(A, "Index", W)
r = batch(A, {X2: {"parent_id": MID, "sort": 0}, DEEP: {"parent_id": MID, "sort": 1}})
j = r.json()
st = state(A)
check(j.get("count") == 1 and any("levels" in x for x in j.get("errors", [])), f"#1003: the one with own subtasks is refused (5 levels), the rest moves: {j}")
check(st[X2]["parent_id"] == MID and st[DEEP]["parent_id"] is None and st[DK]["parent_id"] == DEEP, "#1003: X2 is on level 3, Screenshots stays with its subtask")
# out of the parent: order, assignee and dates stay
O1 = task(A, "Order flowers", W, parent_id=TOP, assignee_id=ids["bob"], due="2030-05-02")
O2 = task(A, "Book the room", W, parent_id=TOP, due="2030-05-03", due_time="10:00")
O3 = task(A, "Send invites", W, parent_id=TOP, assignee_id=ids["alice"])
st = state(A)
before = {i: dict(st[i]) for i in (O1, O2, O3)}
base = st[TOP]["sort"]
r = batch(A, {O1: {"parent_id": None, "section_id": None, "sort": base + 0.25}, O2: {"parent_id": None, "section_id": None, "sort": base + 0.5},
              O3: {"parent_id": None, "section_id": None, "sort": base + 0.75}})
check(r.ok and r.json().get("count") == 3, f"#1003: three subtasks out of their parent {r.text[:200]}")
st = state(A)
check(all(st[i]["parent_id"] is None for i in (O1, O2, O3)), "#1003: they are standalone")
check(st[O1]["assignee_id"] == ids["bob"] and st[O3]["assignee_id"] == ids["alice"], "#1003: assignees stay")
check(st[O1]["due"] == "2030-05-02" and st[O2]["due"] == "2030-05-03" and st[O2]["due_time"] == "10:00", "#1003: dates stay")
check(st[O1]["sort"] < st[O2]["sort"] < st[O3]["sort"], "#1003: the order stays")
# the undo: patch_each back to the parent with _prev (what the client's history sends)
r = batch(A, {i: {"parent_id": TOP, "sort": before[i]["sort"], "_prev": {"parent_id": None, "sort": st[i]["sort"]}} for i in (O1, O2, O3)})
st = state(A)
check(r.ok and not r.json().get("conflicts") and all(st[i]["parent_id"] == TOP for i in (O1, O2, O3)), f"#1003: one undo puts all three back {r.text[:200]}")
# rights: a viewer changes nothing; an editor cannot nest under a task of a list they cannot see
r = batch(Ca, {O1: {"parent_id": None}, O2: {"parent_id": None}})
check(r.json().get("count") == 0 and all(state(A)[i]["parent_id"] == TOP for i in (O1, O2)), f"#1003: a viewer changes nothing {r.text[:200]}")
PRIV = task(A, "Alice private", HID)
r = batch(Bo, {O1: {"parent_id": PRIV}})
check(r.json().get("count") == 0 and state(A)[O1]["parent_id"] == TOP, f"#1003: no parent from a list the editor does not see {r.text[:200]}")
BT = task(Bo, "Bob's own", W)
r = batch(Bo, {O3: {"parent_id": BT, "sort": 0}, O2: {"parent_id": BT, "sort": 1}})
st = state(A)
check(r.json().get("count") == 2 and st[O3]["parent_id"] == BT and st[O3]["assignee_id"] == ids["alice"], f"#1003: an editor regroups in the shared list, assignee kept {r.text[:200]}")
# to another list (the sidebar drop): standalone there, own subtasks follow
r = batch(A, {DEEP: {"list_id": W2, "section_id": None}, X2: {"list_id": W2, "section_id": None, "parent_id": None}})
st = state(A)
check(r.json().get("count") == 2 and st[DEEP]["list_id"] == W2 and st[DK]["list_id"] == W2 and st[X2]["list_id"] == W2 and st[X2]["parent_id"] is None,
      f"#1003: into another list, subtasks follow {r.text[:200]}")

print(f"p2430_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
