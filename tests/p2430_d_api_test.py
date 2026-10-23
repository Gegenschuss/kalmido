#!/usr/bin/env python3
"""2.43.0 API tests, part D: #1434 "Delete all times of this project" (preview, delete, restore), own container (start.sh).
Invented names only. The project is billed in part: an invoice of the client covering a day and carrying the project name.
usage: p2430_d_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

from kt import FAILS, OKS, check, sess, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


if not os.environ.get("P2430_D_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments", "time"]})
A.patch(B + "/api/settings", json={"lang": "en"})
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}
for s_ in (A, Bo, Ca, Da):
    s_.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,office,clients,time", "tour": "done"})
ORG = dbx("INSERT INTO orgs(name, icon, domains, created_at) VALUES('Alpha', '', '', '2026-01-01T00:00:00+00:00') RETURNING id")[0][0]
for u in ("alice", "bob", "dave"):
    dbx("INSERT INTO org_members(org_id, user_id, role) VALUES(?, ?, 'member')", (ORG, ids[u]))

P = A.post(B + "/api/lists", json={"name": "Harbour site", "kind": "project", "time_tracking": True}).json()["id"]
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, P))
A.put(B + f"/api/lists/{P}/members", json={"user_id": ids["bob"], "role": "edit"})
A.put(B + f"/api/lists/{P}/members", json={"user_id": ids["dave"], "role": "admin"})
T = A.post(B + "/api/tasks", json={"title": "Survey", "list_id": P}).json()["id"]


def add(s, day, mins, tid=None):
    body = {"start": f"2026-09-{day:02d}T08:00:00Z", "end": f"2026-09-{day:02d}T{8 + mins // 60:02d}:{mins % 60:02d}:00Z"}
    body.update({"task_id": tid} if tid else {"list_id": P})
    r = s.post(B + "/api/time/entries", json=body)
    assert r.ok, (r.status_code, r.text)
    return r.json()["id"]


for d in (1, 2, 3):
    add(A, d, 60, T)
for d in (4, 5):
    add(Bo, d, 30)
add(A, 20, 120)   # day 20: billed below

# an invoice of the client covering day 20 and carrying the project name -> that entry stays
cid = dbx("INSERT INTO clients(org_id, name, created_at, updated_at) VALUES(?, 'Acme Test', '2026-01-01', '2026-01-01') RETURNING id", (ORG,))[0][0]
dbx("UPDATE lists SET client_id=? WHERE id=?", (cid, P))
did = dbx("INSERT INTO office_docs(org_id, kind, status, client_id, service_from, service_to, created_at, updated_at) "
          "VALUES(?, 'invoice', 'draft', ?, '2026-09-18', '2026-09-22', '2026-09-23', '2026-09-23') RETURNING id", (ORG, cid))[0][0]
dbx("INSERT INTO office_doc_items(doc_id, org_id, title) VALUES(?, ?, 'Harbour site')", (did, ORG))

# preview: admin sees all (5 unbilled), member only own (2), outsider 404, agent n/a
pr = A.get(B + f"/api/lists/{P}/time/delete-all").json()
check(pr["count"] == 5 and pr["billed"] == 1 and pr["seconds"] == 3 * 3600 + 3600 and pr["all"], f"preview admin {pr}")
pr = Bo.get(B + f"/api/lists/{P}/time/delete-all").json()
check(pr["count"] == 2 and pr["seconds"] == 3600 and pr["billed"] == 0 and not pr["all"], f"preview member {pr}")
check(Ca.get(B + f"/api/lists/{P}/time/delete-all").status_code == 404, "outsider: 404")
check(Ca.post(B + f"/api/lists/{P}/time/delete-all", json={"confirm": "Harbour site"}).status_code == 404, "outsider delete: 404")

# confirmation by typing the name
r = Bo.post(B + f"/api/lists/{P}/time/delete-all", json={"confirm": "wrong"})
check(r.status_code == 400, f"wrong name {r.status_code}")
check(len(dbx("SELECT id FROM time_entries WHERE list_id=?", (P,))) == 6, "nothing deleted yet")

# member: only own
r = Bo.post(B + f"/api/lists/{P}/time/delete-all", json={"confirm": "Harbour site"})
j = r.json()
check(r.ok and j["deleted"] == 2 and len(j["entries"]) == 2, f"member deletes own {r.status_code} {r.text[:200]}")
check(len(dbx("SELECT id FROM time_entries WHERE list_id=?", (P,))) == 4, "alice's entries remain")
# restore (undo): own entries back; an entry of somebody else is ignored for a member
r = Bo.post(B + f"/api/lists/{P}/time/restore", json={"entries": j["entries"] + [{**j["entries"][0], "user_id": ids["alice"]}]})
check(r.ok and r.json()["restored"] == 2, f"member restore {r.status_code} {r.text[:200]}")
check(len(dbx("SELECT id FROM time_entries WHERE list_id=?", (P,))) == 6, "restored")

# admin (not owner): all but the billed one
r = Da.post(B + f"/api/lists/{P}/time/delete-all", json={"confirm": "Harbour site"})
j = r.json()
check(r.ok and j["deleted"] == 5 and j["billed"] == 1, f"admin deletes all {r.status_code} {r.text[:200]}")
left = dbx("SELECT user_id, seconds FROM time_entries WHERE list_id=?", (P,))
check(len(left) == 1 and left[0][1] == 7200, f"the billed entry stays {left}")
r = Da.post(B + f"/api/lists/{P}/time/restore", json={"entries": j["entries"]})
check(r.ok and r.json()["restored"] == 5, f"admin restore {r.status_code}")
rows = dbx("SELECT user_id, task_id FROM time_entries WHERE list_id=?", (P,))
check(len(rows) == 6 and sum(1 for x in rows if x[0] == ids["bob"]) == 2 and sum(1 for x in rows if x[1] == T) == 3, f"restored with owners and tasks {rows}")
# review V1: restore never creates entries for people outside the list, nor with end before start
e0 = j["entries"][0]
r = Da.post(B + f"/api/lists/{P}/time/restore", json={"entries": [{**e0, "user_id": ids["carol"]}, {**e0, "start": e0["end"], "end": e0["start"]}]})
check(r.ok and r.json()["restored"] == 0, f"restore: outsider / reversed times ignored {r.status_code} {r.text[:200]}")

# agents: 403
ag = A.post(B + "/api/agents", json={"name": "Helper"})
if ag.ok:
    tok = ag.json().get("token")
    if tok:
        h = {"Authorization": "Bearer " + tok, **H}
        r = requests.get(B + f"/api/lists/{P}/time/delete-all", headers=h)
        check(r.status_code in (401, 403, 404), f"agent preview refused {r.status_code}")
        r = requests.post(B + f"/api/lists/{P}/time/delete-all", headers=h, json={"confirm": "Harbour site"})
        check(r.status_code in (401, 403, 404), f"agent delete refused {r.status_code}")
check(len(dbx("SELECT id FROM time_entries WHERE list_id=?", (P,))) == 6, "agent changed nothing")

print(f"p2430_d_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
