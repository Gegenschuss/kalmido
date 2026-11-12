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
 - fable review: the limit of 50 counts for the other task as well; closing as duplicate marks its notification on the
   other devices handled like the status route
usage: p2576_d_links_api_test.py <datadir>      (P2576DL_NOSTART=1 = the server already runs like that)"""
# freelancer-matrix: tasks
import os
import sys
import time

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
# 2.972.0 (#5272): the task comments are rows of the core's obj_comments (kind 'task', ref_id = the task)
cm = kt.dbx("SELECT body FROM obj_comments WHERE kind='task' AND ref_id=? AND deleted_at IS NULL", (T3,))
# 2.1010.0 (#4033): the comment names the other task's title too (both in the same list)
check([x[0] for x in cm] == [f"Duplicate of #{T1}: Alpha task 1"], f"close as duplicate: the comment points at the other task {cm}")
r = A.post(B + "/api/tasks/batch", json={"ids": [T3], "action": "undo", "data": {"items": {str(T3): j.get("undo")}}})
check(r.ok and A.get(B + f"/api/tasks/{T3}").json()["status"] == 0, f"undo: the task is open again {r.status_code} {r.text[:200]}")
# 2.972.0 (#5272): the task comments are rows of the core's obj_comments (kind 'task', ref_id = the task)
check(n_rows(T1, T3) == 0 and not kt.dbx("SELECT 1 FROM obj_comments WHERE kind='task' AND ref_id=? AND deleted_at IS NULL", (T3,)),
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
LRO = A.post(B + "/api/lists", json={"name": "Read plan", "org_id": ALPHA}).json()["id"]
r = A.put(B + f"/api/lists/{LRO}/members", json={"user_id": RO_ID, "role": "view"})
check(r.ok, f"setup: the read-only agent's own list {r.status_code} {r.text[:160]}")
TR1, TR2 = mk(A, LRO, "Read task 1"), mk(A, LRO, "Read task 2")
A.post(B + f"/api/tasks/{TR1}/relations", json={"other_id": TR2})
check(Ro.post(V + f"/tasks/{TR1}/relations", json={"other_id": TR2, "kind": "duplicate"}).status_code == 403 and n_rows(TR1, TR2) == 1,
      "a read-only token adds no relation (403)")
r = Ro.get(V + f"/tasks/{TR1}/relations")
check(r.ok and [x["id"] for x in r.json()["relations"]] == [TR2], f"a read-only token reads them {r.status_code} {r.text[:160]}")

# ---------------------------------------------------------------- remove
check(A.delete(B + f"/api/tasks/{T1}/relations/{TP}").ok and n_rows(T1, TP) == 0, "remove: gone")
check(A.delete(B + f"/api/tasks/{T1}/relations/{TP}").status_code == 404, "remove twice: 404")

# ---------------------------------------------------------------- fable review N1: the limit counts for the other task too
TX = mk(A, LA, "Busy target")
for i in range(50):
    check(A.post(B + f"/api/tasks/{mk(A, LP, f'Filler {i}')}/relations", json={"other_id": TX}).ok, f"setup: relation {i} on the target")
check(A.post(B + f"/api/tasks/{TX}/relations", json={"other_id": T4}).status_code == 400, "N1: the full task itself takes no more")
LB = Bo.post(B + "/api/lists", json={"name": "Bob own", "org_id": None}).json()["id"]
TB = mk(Bo, LB, "Bob own task")
r = Bo.post(B + f"/api/tasks/{TB}/relations", json={"other_id": TX})
check(r.status_code == 400 and "50" in r.text and n_rows(TB, TX) == 0,
      f"N1: relating one's own task to a full one: 400 with the limit, nothing stored {r.status_code} {r.text[:160]}")

# ---------------------------------------------------------------- fable review N2: close as duplicate closes its notification elsewhere
AID = kt.dbx("SELECT id FROM users WHERE username='alice'")[0][0]
TD = mk(A, LA, "Duplicate with a notification")
kt.dbx("INSERT INTO push_subs(user_id,endpoint,p256dh,auth,label,created_at) VALUES(?,?,?,?,?,?)",
       (AID, "https://push.example.com/p2576dl", "k", "a", "Phone", "2026-01-01T00:00:00+00:00"))
SUBID = kt.dbx("SELECT id FROM push_subs WHERE endpoint=?", ("https://push.example.com/p2576dl",))[0][0]
# 2.628.0 (#4985): sent now, not at 1.0 (1970) -- the watchdog (notify/push.py push_dismiss_tick) deletes every tag sent
# more than DISMISS_KEEP ago at each tick, so a tick between this insert and the check below took the row away (CI: IndexError)
kt.dbx("INSERT INTO push_tags(sub_id,tag,sent_at,handled_at) VALUES(?,?,?,NULL)", (SUBID, f"t-{TD}", time.time()))
r = A.post(B + f"/api/tasks/{TD}/relations", json={"other_id": T1, "kind": "duplicate", "close": True})
check(r.ok and r.json()["task"]["status"] == -1, f"N2: closed as duplicate {r.status_code} {r.text[:160]}")
check(kt.dbx("SELECT handled_at FROM push_tags WHERE sub_id=? AND tag=?", (SUBID, f"t-{TD}"))[0][0] is not None,
      "N2: its notification on the other device is marked handled (as the status route does)")
kt.dbx("DELETE FROM push_subs WHERE id=?", (SUBID,))

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

# ---------------------------------------------------------------- 2.1010.0 (#4033): the duplicate comment names key / title


def dupc(t):
    return [x[0] for x in kt.dbx("SELECT body FROM obj_comments WHERE kind='task' AND ref_id=? AND deleted_at IS NULL ORDER BY id", (t,))]


TP2 = mk(A, LP, "Alice private twin")
check(A.post(B + f"/api/tasks/{TP2}/relations", json={"other_id": T2, "kind": "duplicate", "close": True}).ok, "another list: closed as duplicate")
check(dupc(TP2) == [f"Duplicate of #{T2}"], f"another list: only the number, no title of a task the readers may not see {dupc(TP2)}")
r = A.patch(B + f"/api/lists/{LP}", json={"ticket_key": "ALP"})
check(r.ok, f"setup: the private project gets a ticket key {r.status_code} {r.text[:120]}")
K1, K2 = mk(A, LP, "Login  broken"), mk(A, LP, "Login broken again")
no = kt.dbx("SELECT ticket_no FROM tasks WHERE id=?", (K1,))[0][0]
check(A.post(B + f"/api/tasks/{K2}/relations", json={"other_id": K1, "kind": "duplicate", "close": True}).ok, "keyed: closed as duplicate")
check(dupc(K2) == [f"Duplicate of ALP-{no}: Login broken"], f"keyed: the ticket key and the title {dupc(K2)}")
K3 = mk(A, LP, "See [here](https://example.com) <@1> *now*")
K4 = mk(A, LP, "Twin of the link")
check(A.post(B + f"/api/tasks/{K4}/relations", json={"other_id": K3, "kind": "duplicate", "close": True}).ok, "markdown title: closed")
check(dupc(K4) == [f"Duplicate of ALP-{no + 2}: See \\[here\\]\\(https://example.com\\) < @1> \\*now\\*"],
      f"markdown title: plain text, no link, no mention chip {dupc(K4)}")
# review: a participant who sees the closed task but not the other one never reads its title
check(A.put(B + f"/api/lists/{LA}/members", json={"user_id": uid["bob"], "role": "participant"}).ok, "setup: bob a participant in Alpha plan")
T7, T8 = mk(A, LA, "Secret original"), mk(A, LA, "Visible copy")
check(A.patch(B + f"/api/tasks/{T8}", json={"assignee_id": uid["bob"]}).ok, "setup: bob sees the copy only")
check(A.post(B + f"/api/tasks/{T8}/relations", json={"other_id": T7, "kind": "duplicate", "close": True}).ok, "participant: closed")
check(dupc(T8) == [f"Duplicate of #{T7}"], f"participant: no title of a task a reader may not see {dupc(T8)}")

sys.exit(kt.done("p2576_d_links_api"))
