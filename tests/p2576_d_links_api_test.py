#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.576.0 part D (#3371): saved relations between tasks (relates to, duplicate of). Own container (mode workspaces).
Invented names only (example.com).  tenant-matrix: relation
 - relates: one row per pair, both tasks show it (GET .../relations, the task object's relations, API v1); a duplicate
   replaces it; the reverse duplicate and a task with itself are refused; removing it twice = 404
 - "duplicate of" does not close the task; close=true does (won't do + the comment "Duplicate of #X"), and its undo opens
   the task again and takes the relation and the comment back
 - visibility: adding needs write access to the task and sight of the other one (another organisation's / an unshared task
   404, nothing stored); a relation to a task the reader cannot see is never shown (member, another organisation, the
   agent with only its shared list - app, API v1, task object); a task in the trash drops out and comes back
 - a person without an organisation relates her own tasks (freelancer-matrix: tasks), never to someone else's
usage: p2576_d_links_api_test.py <datadir>      (P2576DL_NOSTART=1 = the server already runs like that)"""
# freelancer-matrix: tasks
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, sess  # noqa: E402

V = B + "/api/v1"
FEAT = "deps,comments,collab"

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2576DL")


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def rels(s, tid, v1=False):
    r = s.get((V if v1 else B + "/api") + f"/tasks/{tid}/relations")
    return r.status_code, {x["id"]: x["kind"] for x in (r.json().get("relations") or [])} if r.ok else {}


def task_rels(s, tid, v1=False):
    r = s.get((V if v1 else B + "/api") + f"/tasks/{tid}")
    return {x["id"]: x["kind"] for x in (r.json().get("relations") or [])} if r.ok else None


def n_rows(a, b):
    return kt.dbx("SELECT COUNT(*) FROM task_relations WHERE (task_id=? AND other_id=?) OR (task_id=? AND other_id=?)", (a, b, b, a))[0][0]


def mk(s, lid, title):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALPHA = A.post(B + "/api/admin/orgs", json={"name": "Alpha"}).json()["id"]
uid = {}
for u, orgs in (("bob", [ALPHA]), ("carol", [])):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": kt.PASSWORD, "email": f"{u}@example.com", "orgs": orgs})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["carol"]}).json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})

LA = A.post(B + "/api/lists", json={"name": "Alpha plan", "org_id": ALPHA}).json()["id"]
check(A.put(B + f"/api/lists/{LA}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob in the shared project")
LP = A.post(B + "/api/lists", json={"name": "Alice private", "org_id": None}).json()["id"]
LC = Ca.post(B + "/api/lists", json={"name": "Beta plan", "org_id": BETA}).json()["id"]
T1, T2, T3, T4 = (mk(A, LA, f"Alpha task {i}") for i in range(1, 5))
TP = mk(A, LP, "Alice private task")
TC = mk(Ca, LC, "Beta task")

# ---------------------------------------------------------------- relates
r = A.post(B + f"/api/tasks/{T1}/relations", json={"other_id": T2})
check(r.ok and {x["id"] for x in r.json()["relations"]} == {T2} and r.json()["max"] == 50, f"relates: added {r.status_code} {r.text[:200]}")
check(rels(A, T2) == (200, {T1: "relates"}), f"relates: the other task shows it too {rels(A, T2)}")
check(A.post(B + f"/api/tasks/{T2}/relations", json={"other_id": T1}).ok and n_rows(T1, T2) == 1, "relates: one row per pair, both ways")
check(task_rels(A, T1) == {T2: "relates"} and task_rels(A, T1, v1=False) is not None, f"relates: the task object carries it {task_rels(A, T1)}")
check(A.post(B + f"/api/tasks/{T1}/relations", json={"other_id": T1}).status_code == 400, "a task with itself: 400")
check(A.post(B + f"/api/tasks/{T1}/relations", json={"other_id": T2, "kind": "blocks"}).status_code == 400, "an unknown kind: 400")
check(A.post(B + f"/api/tasks/{T1}/relations", json={"other_id": "x"}).status_code == 400, "no task id: 400")

# ---------------------------------------------------------------- duplicate: no closing by itself, a duplicate replaces relates
r = A.post(B + f"/api/tasks/{T2}/relations", json={"other_id": T1, "kind": "duplicate"})
check(r.ok and "undo" not in r.json() and r.json()["task"]["status"] == 0, f"duplicate: the task stays open {r.status_code} {r.text[:200]}")
check(rels(A, T2)[1] == {T1: "duplicate_of"} and rels(A, T1)[1] == {T2: "has_duplicate"}, f"duplicate: both sides {rels(A, T2)} {rels(A, T1)}")
check(n_rows(T1, T2) == 1, "duplicate: replaced the relates row")
check(A.post(B + f"/api/tasks/{T1}/relations", json={"other_id": T2, "kind": "duplicate"}).status_code == 400, "the reverse duplicate: 400")
A.post(B + f"/api/tasks/{T1}/relations", json={"other_id": T2})
check(rels(A, T1)[1] == {T2: "has_duplicate"}, "relates next to a duplicate changes nothing")

# ---------------------------------------------------------------- close as duplicate + undo
r = A.post(B + f"/api/tasks/{T3}/relations", json={"other_id": T1, "kind": "duplicate", "close": True})
j = r.json() if r.ok else {}
check(r.ok and j.get("undo") and j["task"]["status"] == -1, f"close as duplicate: won't do, with undo {r.status_code} {r.text[:200]}")
cm = kt.dbx("SELECT body FROM comments WHERE task_id=? AND deleted_at IS NULL", (T3,))
check([x[0] for x in cm] == [f"Duplicate of #{T1}"], f"close as duplicate: the comment points at the other task {cm}")
r = A.post(B + "/api/tasks/batch", json={"ids": [T3], "action": "undo", "data": {"items": {str(T3): j.get("undo")}}})
check(r.ok and A.get(B + f"/api/tasks/{T3}").json()["status"] == 0, f"undo: the task is open again {r.status_code} {r.text[:200]}")
check(n_rows(T1, T3) == 0 and not kt.dbx("SELECT 1 FROM comments WHERE task_id=? AND deleted_at IS NULL", (T3,)),
      "undo: the relation and the comment are gone too")
r = A.post(B + f"/api/v1/tasks/{T3}/relations", json={"other_id": T4, "kind": "duplicate", "close": True}, headers={})
check(r.status_code == 401, "API v1 needs a token")

# ---------------------------------------------------------------- visibility: member, other organisation
check(A.post(B + f"/api/tasks/{T1}/relations", json={"other_id": TP}).ok, "alice relates a shared task to her private one")
check(rels(Bo, T1) == (200, {T2: "has_duplicate"}), f"member: the relation to a task she cannot see is not shown {rels(Bo, T1)}")
check(task_rels(Bo, T1) == {T2: "has_duplicate"}, f"member: nor in the task object {task_rels(Bo, T1)}")
st = Bo.get(B + "/api/state").json()
bt1 = next((t for t in st.get("tasks", []) if t["id"] == T1), {})
check(TP not in {x["id"] for x in bt1.get("relations") or []}, "member: nor in the state")
check(Bo.post(B + f"/api/tasks/{T4}/relations", json={"other_id": TP}).status_code == 404 and n_rows(T4, TP) == 0,
      "member: relating to a task she cannot see 404, nothing stored")
check(Bo.post(B + f"/api/tasks/{T4}/relations", json={"other_id": T1}).ok, "member: relating two tasks of the shared project")
check(Ca.get(B + f"/api/tasks/{T1}/relations").status_code == 404, "another organisation: the relations of a task 404")
check(Ca.post(B + f"/api/tasks/{TC}/relations", json={"other_id": T1}).status_code == 404 and n_rows(TC, T1) == 0,
      "another organisation: relating her task to ours 404, nothing stored")
check(Ca.post(B + f"/api/tasks/{T1}/relations", json={"other_id": TC}).status_code == 404 and n_rows(TC, T1) == 0,
      "another organisation: relating our task to hers 404")
check(Ca.delete(B + f"/api/tasks/{T1}/relations/{T2}").status_code == 404 and n_rows(T1, T2) == 1, "another organisation: removing 404")
check(Bo.delete(B + f"/api/tasks/{T1}/relations/{TP}").status_code == 404 and n_rows(T1, TP) == 1,
      "member: removing a relation to a task she cannot see 404")

# a reader of the project only: sees, cannot change
check(A.put(B + f"/api/lists/{LA}/members", json={"user_id": uid["bob"], "role": "view"}).ok, "bob only reads now")
check(rels(Bo, T1)[0] == 200 and Bo.post(B + f"/api/tasks/{T1}/relations", json={"other_id": T3}).status_code in (403, 404),
      "a reader sees the relations but adds none")
A.put(B + f"/api/lists/{LA}/members", json={"user_id": uid["bob"], "role": "edit"})

# trash: drops out while there
check(A.delete(B + f"/api/tasks/{T2}").ok and T2 not in rels(A, T1)[1], "the other task in the trash: the relation drops out")
check(A.post(B + f"/api/tasks/{T2}/relations", json={"other_id": T3}).status_code == 409, "a task in the trash gets no relation (409)")
check(A.post(B + f"/api/tasks/{T2}/restore").ok and rels(A, T1)[1].get(T2) == "has_duplicate", "restored: it is back")

# ---------------------------------------------------------------- agent with only its shared list (API v1)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "planbot", "display_name": "Plan bot", "org_id": ALPHA})
assert r.status_code == 201, r.text
AG, Ag = r.json()["id"], bearer(r.json()["token"])
LAG = A.post(B + "/api/lists", json={"name": "Agent plan", "org_id": ALPHA}).json()["id"]
check(A.put(B + f"/api/lists/{LAG}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the agent's list")
TA1, TA2 = mk(A, LAG, "Agent task 1"), mk(A, LAG, "Agent task 2")
check(A.post(B + f"/api/tasks/{TA1}/relations", json={"other_id": T1}).ok, "alice relates the agent's task to one it does not see")
r = Ag.post(V + f"/tasks/{TA1}/relations", json={"other_id": TA2, "kind": "duplicate"})
check(r.ok and {x["id"]: x["kind"] for x in r.json()["relations"]} == {TA2: "duplicate_of"} and r.json().get("closed") is False,
      f"agent: relates its own tasks, only those it sees come back {r.status_code} {r.text[:200]}")
check(rels(Ag, TA1, v1=True) == (200, {TA2: "duplicate_of"}), f"agent v1: never the task it cannot see {rels(Ag, TA1, v1=True)}")
check(task_rels(Ag, TA1, v1=True) == {TA2: "duplicate_of"}, f"agent v1: nor in the task {task_rels(Ag, TA1, v1=True)}")
check(rels(A, TA1)[1] == {T1: "relates", TA2: "duplicate_of"}, "alice sees both")
check(Ag.post(V + f"/tasks/{TA1}/relations", json={"other_id": T3}).status_code == 404 and n_rows(TA1, T3) == 0,
      "agent: relating to a task outside its list 404, nothing stored")
check(Ag.get(V + f"/tasks/{T1}/relations").status_code == 404, "agent: the relations of a task it cannot see 404")
check(Ag.post(V + f"/tasks/{TA1}/relations", json={"other_id": TA2, "note": "x"}).status_code == 400, "agent: unknown fields 400")
check(Ag.delete(V + f"/tasks/{TA1}/relations/{T1}").status_code == 404 and n_rows(TA1, T1) == 1, "agent: removing one it cannot see 404")
check(Ag.delete(V + f"/tasks/{TA1}/relations/{TA2}").ok and n_rows(TA1, TA2) == 0, "agent: removes its own")
r = Ag.post(V + f"/tasks/{TA2}/relations", json={"other_id": TA1, "kind": "duplicate", "close": True})
check(r.ok and r.json().get("closed") is True and Ag.get(V + f"/tasks/{TA2}").json().get("status") == "wont_do",
      f"agent: close as duplicate {r.status_code} {r.text[:160]} {Ag.get(V + f'/tasks/{TA2}').json().get('status')}")
ro = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "readbot", "display_name": "Read bot", "org_id": ALPHA})
RO_ID, Ro = ro.json()["id"], bearer(ro.json()["token"])
A.put(B + f"/api/lists/{LAG}/members", json={"user_id": RO_ID, "role": "edit"})
check(Ro.post(V + f"/tasks/{TA1}/relations", json={"other_id": TA2}).status_code == 403, "a read-only token adds no relation (403)")
check(Ro.get(V + f"/tasks/{TA1}/relations").ok, "a read-only token reads them")

# ---------------------------------------------------------------- remove
check(A.delete(B + f"/api/tasks/{T1}/relations/{TP}").ok and n_rows(T1, TP) == 0, "remove: gone")
check(A.delete(B + f"/api/tasks/{T1}/relations/{TP}").status_code == 404, "remove twice: 404")

# ---------------------------------------------------------------- a person without an organisation
FID, Fr = freelancer(B, A, features=FEAT)
LF = Fr.post(B + "/api/lists", json={"name": "Own plan"}).json()["id"]
F1, F2 = mk(Fr, LF, "Own task 1"), mk(Fr, LF, "Own task 2")
check(Fr.post(B + f"/api/tasks/{F1}/relations", json={"other_id": F2}).ok and rels(Fr, F2) == (200, {F1: "relates"}),
      "freelancer: relates her own tasks")
check(Fr.post(B + f"/api/tasks/{F1}/relations", json={"other_id": T1}).status_code == 404 and n_rows(F1, T1) == 0,
      "freelancer: never to someone else's task")
check(Fr.get(B + f"/api/tasks/{T1}/relations").status_code == 404, "freelancer: someone else's relations 404")
check(Fr.delete(B + f"/api/tasks/{F1}/relations/{F2}").ok and rels(Fr, F1) == (200, {}), "freelancer: removes it")

sys.exit(kt.done("p2576_d_links_api"))
