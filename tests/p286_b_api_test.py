#!/usr/bin/env python3
"""2.86.0 API tests, part B: rights on tasks, lists and approvals (audit hardening). Invented names only.
 - N10 "Delete all times" + Undo: another person's entry comes back only as the delete returned it (sealed), once;
   a forged or changed entry for someone else is ignored; own entries come back as before
 - N12 an approval: a viewer cannot be the approver (400); an approver who is only a viewer now cannot decide (403)
 - N13 a dependency on a blocker the user only reads: no history line in the blocker (add and remove)
 - N14 a subtask under a parent the user cannot see: 404 (also for a milestone, not "a milestone cannot have subtasks");
   a reader: 403
 - N18 GET /api/v1/lists/{id}/rules: people owner / list admin (like the web), an edit member 403; agents need write access
 - N21 moving a task out of a list open to "Everyone in the organisation" into a list that is not: 403 for a list admin
usage: p286_b_api_test.py <datadir>      (a fresh container; P286B_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


if not os.environ.get("P286B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments", "time"]})
A.patch(B + "/api/settings", json={"lang": "en"})
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s_ in (A, Bo, Ca, Da, Er):
    s_.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,time", "tour": "done"})
ORG = dbx("INSERT INTO orgs(name, icon, domains, created_at) VALUES('Alpha', '', '', '2026-01-01T00:00:00+00:00') RETURNING id")[0][0]
for u in ("alice", "bob", "carol", "dave"):
    dbx("INSERT INTO org_members(org_id, user_id, role) VALUES(?, ?, 'member')", (ORG, ids[u]))


def olist(name, **kw):
    r = A.post(B + "/api/lists", json={"name": name, **kw})
    assert r.ok, r.text
    lid = r.json()["id"]
    dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, lid))
    return lid


def member(lid, who, role):
    r = A.put(B + f"/api/lists/{lid}/members", json={"user_id": ids[who], "role": role})
    check(r.ok, f"setup: {who} {role} in {lid} {r.text[:120]}")


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


# ================================================================== N10 time restore
P = olist("Harbour works", kind="project", time_tracking=True)
member(P, "bob", "edit")
member(P, "dave", "admin")
T = task(A, P, "Survey")
for s_, day in ((A, 1), (A, 2), (Bo, 3)):
    r = s_.post(B + "/api/time/entries", json={"task_id": T, "start": f"2026-09-{day:02d}T08:00:00Z", "end": f"2026-09-{day:02d}T09:00:00Z"})
    assert r.ok, r.text
n0 = len(dbx("SELECT id FROM time_entries WHERE list_id=?", (P,)))
forged = {"user_id": ids["bob"], "task_id": T, "start": "2026-09-10T08:00:00Z", "end": "2026-09-10T18:00:00Z", "seconds": 36000,
          "note": "made up", "source": "manual"}
r = Da.post(B + f"/api/lists/{P}/time/restore", json={"entries": [forged]})
check(r.ok and r.json()["restored"] == 0, f"N10: an admin cannot create an entry for someone else with free values {r.text[:200]}")
check(len(dbx("SELECT id FROM time_entries WHERE list_id=?", (P,))) == n0, "N10: nothing planted")
r = Da.post(B + f"/api/lists/{P}/time/delete-all", json={"confirm": "Harbour works"})
j = r.json()
check(r.ok and j["deleted"] == 3 and all(e.get("sig") for e in j["entries"]), f"N10: the delete returns sealed entries {r.text[:200]}")
bad = [{**e, "seconds": 3600 * 9, "end": "2026-09-01T17:00:00Z"} for e in j["entries"] if e["user_id"] == ids["alice"]][:1]
r = Da.post(B + f"/api/lists/{P}/time/restore", json={"entries": bad})
check(r.ok and r.json()["restored"] == 0, f"N10: a changed entry of someone else is ignored {r.text[:200]}")
r = Da.post(B + f"/api/lists/{P}/time/restore", json={"entries": j["entries"]})
check(r.ok and r.json()["restored"] == 3, f"N10: Undo brings all three back {r.text[:200]}")
check(len(dbx("SELECT id FROM time_entries WHERE list_id=?", (P,))) == n0, "N10: restored")
r = Da.post(B + f"/api/lists/{P}/time/restore", json={"entries": j["entries"]})
check(r.ok and r.json()["restored"] == 0, f"N10: the same entries of others do not come back twice {r.text[:200]}")
own = {"user_id": ids["bob"], "task_id": T, "start": "2026-09-11T08:00:00Z", "end": "2026-09-11T09:00:00Z", "seconds": 3600, "source": "manual"}
r = Bo.post(B + f"/api/lists/{P}/time/restore", json={"entries": [own]})
check(r.ok and r.json()["restored"] == 1, f"N10: own entries come back as before {r.text[:200]}")

# ================================================================== N12 approvals
W = olist("Studio")
member(W, "bob", "edit")
member(W, "carol", "view")
AP = task(A, W, "Poster draft")
r = A.post(B + f"/api/tasks/{AP}/approval", json={"action": "request", "approver_id": ids["carol"]})
check(r.status_code == 400, f"N12: a viewer cannot be the approver ({r.status_code})")
r = A.post(B + f"/api/tasks/{AP}/approval", json={"action": "request", "approver_id": ids["bob"]})
check(r.ok and r.json()["approval"] == "pending", f"N12: an editor can be the approver {r.text[:200]}")
member(W, "bob", "view")
r = Bo.post(B + f"/api/tasks/{AP}/approval", json={"action": "approve"})
check(r.status_code == 403, f"N12: an approver who only reads now cannot decide ({r.status_code})")
check(dbx("SELECT approval, status FROM tasks WHERE id=?", (AP,))[0] == ("pending", 0), "N12: nothing changed")
member(W, "bob", "edit")
r = Bo.post(B + f"/api/tasks/{AP}/approval", json={"action": "approve"})
check(r.ok and r.json()["status"] == 2, f"N12: with write access again the approver decides {r.text[:200]}")

# ================================================================== N13 dependencies
PA = olist("Bridge plan", kind="project")
member(PA, "carol", "view")
TB = task(A, PA, "Foundation")
PC = Ca.post(B + "/api/lists", json={"name": "Carol project", "kind": "project"}).json()["id"]
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, PC))
TC = task(Ca, PC, "Railing")


def kinds(s, tid):
    return [a["kind"] for a in s.get(B + f"/api/tasks/{tid}/timeline").json()["activity"]]


r = Ca.post(B + "/api/deps", json={"task_id": TC, "blocker_id": TB})
check(r.ok, f"N13: a reader may wait on a task she sees {r.text[:200]}")
check("dep_add" in kinds(Ca, TC), "N13: her own task gets the line")
check("blocks_add" not in kinds(A, TB), "N13: no history line in the blocker she only reads")
r = Ca.delete(B + f"/api/deps/{TC}/{TB}")
check(r.ok and "blocks_rm" not in kinds(A, TB), f"N13: removing it writes nothing into the blocker {r.status_code}")
TA2 = task(A, PA, "Pillars")
check(A.post(B + "/api/deps", json={"task_id": TA2, "blocker_id": TB}).ok and "blocks_add" in kinds(A, TB),
      "N13: with write access the blocker still gets its line")

# ================================================================== N14 parent checks after access
MS = task(A, W, "Launch")
dbx("UPDATE tasks SET ms=1 WHERE id=?", (MS,))
r = Er.post(B + "/api/tasks", json={"title": "x", "parent_id": MS})
check(r.status_code == 404, f"N14: someone outside gets 404, not the milestone rule ({r.status_code} {r.text[:120]})")
r = Er.post(B + "/api/tasks", json={"title": "x", "parent_id": TB})
check(r.status_code == 404, f"N14: an invisible normal parent 404 too ({r.status_code})")
own_t = Er.post(B + "/api/tasks", json={"title": "Erin's own"}).json()["id"]
r = Er.patch(B + f"/api/tasks/{own_t}", json={"parent_id": MS})
check(r.status_code == 404, f"N14: PATCH under an invisible milestone 404 ({r.status_code} {r.text[:120]})")
r = Ca.post(B + "/api/tasks", json={"title": "x", "parent_id": MS})
check(r.status_code == 403, f"N14: a reader 403 ({r.status_code})")
r = A.post(B + "/api/tasks", json={"title": "x", "parent_id": MS})
check(r.status_code == 400, f"N14: the owner still gets the milestone rule ({r.status_code})")

# ================================================================== N18 v1 list rules
member(W, "dave", "admin")
toks = {}
for who, s_ in (("alice", A), ("bob", Bo), ("dave", Da), ("carol", Ca)):
    r = s_.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read"]})
    toks[who] = {"Authorization": "Bearer " + r.json()["token"]} if r.ok else None
check(all(toks.values()), "setup: personal tokens")
if all(toks.values()):
    check(requests.get(V + f"/lists/{W}/rules", headers=toks["alice"]).ok, "N18: the owner reads the rules")
    check(requests.get(V + f"/lists/{W}/rules", headers=toks["dave"]).ok, "N18: a list admin reads the rules")
    check(requests.get(V + f"/lists/{W}/rules", headers=toks["bob"]).status_code == 403, "N18: an edit member 403 (like the web)")
    check(requests.get(V + f"/lists/{W}/rules", headers=toks["carol"]).status_code == 403, "N18: a viewer 403")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "structure"], "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
dbx("UPDATE agents SET org_id=? WHERE user_id=?", (ORG, AG))
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG, AG))
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: agent edits the list")
g = requests.get(V + f"/lists/{W}/rules", headers=AGH)
check(g.ok, f"N18: an agent with write access reads the rules ({g.status_code} {g.text[:120]})")
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": AG, "role": "view"}).ok, "setup: agent only reads")
check(requests.get(V + f"/lists/{W}/rules", headers=AGH).status_code == 403, "N18: a reading agent 403")

# ================================================================== N21 move out of an organisation-wide list
OW = olist("Team board")
D2 = olist("Side board")
member(OW, "bob", "admin")
member(D2, "bob", "edit")
r = A.patch(B + f"/api/lists/{OW}", json={"org_visibility": "org"})
check(r.ok, f"setup: the list is open to the organisation {r.text[:120]}")
TM = task(A, OW, "Shared plan")
check(Da.get(B + f"/api/tasks/{TM}/timeline").ok, "setup: dave reads it through the organisation")
r = Bo.patch(B + f"/api/tasks/{TM}", json={"list_id": D2})
check(r.status_code == 403, f"N21: a list admin cannot pull it away from the organisation's readers ({r.status_code})")
check(dbx("SELECT list_id FROM tasks WHERE id=?", (TM,))[0][0] == OW, "N21: the task stays")
check(A.patch(B + f"/api/lists/{D2}", json={"org_visibility": "org"}).ok, "setup: the target is open to the organisation too")
r = Bo.patch(B + f"/api/tasks/{TM}", json={"list_id": D2})
check(r.ok and r.json()["list_id"] == D2, f"N21: into a list the same readers see, the move works {r.status_code} {r.text[:120]}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
