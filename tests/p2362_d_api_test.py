#!/usr/bin/env python3
"""2.36.2 API tests, part D: "Keep completed in their section" (#1136) and quick add for another person / "Assigned by
me" (#1138); own container (start.sh).
 - lists.done_in_section: a new column (NULL = the default), sent with every list in /api/state; PATCH /api/lists/<id>
   takes 1 / 0 / null (owner and list admins, the same for every member), refuses other values (400) and other members
   (403); foreign lists 404
 - the column is additive: a list row written without it (an older version) reads as NULL
 - a task created for another person in a list both use: assignee + assigned_by set, it is in the other person's view;
   assigning someone who is not in the list is refused (400) -- the app shows a hint instead
 - "Assigned by me" (the client's filter on the tasks of /api/state): the open tasks I created or assigned that belong to
   someone else; a task in a list I left is no longer sent at all, completed ones and my own are not part of it
usage: p2362_d_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
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


def dbx(sql, args=(), write=False):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]


def share(S, lid, uid, role="edit"):
    r = S.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": role})
    if r.status_code == 409:
        r = S.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": role, "bridge_ok": True})
    check(r.ok, f"setup: {uid} in list {lid} " + r.text[:120])


def lst(S, lid):
    return next((l for l in S.get(B + "/api/state").json()["lists"] if l["id"] == lid), None)


# ================================================================== #1136 done_in_section
check(any(r[1] == "done_in_section" for r in dbx("PRAGMA table_info(lists)")), "schema: lists.done_in_section exists")
P = A.post(B + "/api/lists", json={"name": "Website", "kind": "project"}).json()["id"]
L = A.post(B + "/api/lists", json={"name": "Errands"}).json()["id"]
SH = A.post(B + "/api/lists", json={"name": "Groceries", "family": "shopping"}).json()["id"]
share(A, P, BOB, "edit")
share(A, P, CAROL, "admin")
check("done_in_section" in lst(A, P) and lst(A, P)["done_in_section"] is None, "state: new lists carry done_in_section = null (the default)")
check(lst(A, L)["done_in_section"] is None and lst(A, SH)["done_in_section"] is None, "state: plain and shopping lists start with null too")
r = A.patch(B + f"/api/lists/{L}", json={"done_in_section": 1})
check(r.ok and lst(A, L)["done_in_section"] == 1, "owner turns it on " + r.text[:80])
r = A.patch(B + f"/api/lists/{L}", json={"done_in_section": 0})
check(r.ok and lst(A, L)["done_in_section"] == 0, "owner turns it off (explicit 0)")
r = A.patch(B + f"/api/lists/{L}", json={"done_in_section": None})
check(r.ok and lst(A, L)["done_in_section"] is None, "null = back to the default")
r = A.patch(B + f"/api/lists/{L}", json={"done_in_section": True})
check(r.ok and lst(A, L)["done_in_section"] == 1, "true is taken as 1")
for bad in ("x", 2, 0.5, [1]):
    r = A.patch(B + f"/api/lists/{L}", json={"done_in_section": bad})
    check(r.status_code == 400, f"invalid value {bad!r} -> 400 {r.status_code}")
check(lst(A, L)["done_in_section"] == 1, "an invalid value changes nothing")
r = Bo.patch(B + f"/api/lists/{P}", json={"done_in_section": 0})
check(r.status_code == 403, "a member (edit) may not change it " + str(r.status_code))
r = Ca.patch(B + f"/api/lists/{P}", json={"done_in_section": 0})
check(r.ok, "a list admin may change it " + r.text[:80])
check(lst(Bo, P)["done_in_section"] == 0 and lst(A, P)["done_in_section"] == 0, "the same value for every member")
r = Da.patch(B + f"/api/lists/{P}", json={"done_in_section": 1})
check(r.status_code == 404, "a foreign list -> 404 " + str(r.status_code))
check(lst(A, P)["done_in_section"] == 0, "... and nothing changed")
r = A.patch(B + f"/api/lists/{P}", json={"done_in_section": 1, "name": "Website 2"})
check(r.ok and lst(A, P)["done_in_section"] == 1 and lst(A, P)["name"] == "Website 2", "together with other list fields")
# a list written without the column (as an older version does) reads as the default
dbx("INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id) VALUES('Old style','','',99,'list','2026-01-01T00:00:00Z',?)", (ALICE,), write=True)
old = next((l for l in A.get(B + "/api/state").json()["lists"] if l["name"] == "Old style"), None)
check(old is not None and old["done_in_section"] is None, "a row without the column reads as null")
# completed tasks of the list are still sent (the client puts them into their sections)
SEC = A.post(B + "/api/sections", json={"list_id": P, "name": "Design"}).json().get("id")
t1 = A.post(B + "/api/tasks", json={"title": "Logo draft", "list_id": P, "section_id": SEC}).json()["id"]
A.post(B + f"/api/tasks/{t1}/complete")
mine = {t["id"]: t for t in A.get(B + "/api/state").json()["tasks"]}
check(t1 in mine and mine[t1]["status"] != 0 and mine[t1]["section_id"] == SEC, "a completed task keeps its section in the state " + str(mine.get(t1, {}).get("status")))

# ================================================================== #1138 quick add for another person
W = Ca.post(B + "/api/lists", json={"name": "Team board"}).json()["id"]  # carol's list with alice + bob
share(Ca, W, ALICE, "edit")
share(Ca, W, BOB, "edit")
r = A.post(B + "/api/tasks", json={"title": "Send the offer", "list_id": W, "assignee_id": BOB})
check(r.ok, "create for bob in a list both use " + r.text[:80])
T1 = r.json()["id"]
row = dbx("SELECT assignee_id, assigned_by, created_by FROM tasks WHERE id=?", (T1,))[0]
check(row == (BOB, ALICE, ALICE), "assignee bob, assigned_by + created_by alice " + str(row))
check(any(t["id"] == T1 and t["assignee_id"] == BOB for t in Bo.get(B + "/api/state").json()["tasks"]), "bob sees the task (his view)")
r = A.post(B + "/api/tasks", json={"title": "Not his list", "list_id": L, "assignee_id": BOB})
check(r.status_code == 400, "assigning someone who is not in the list is refused " + str(r.status_code))
r = A.post(B + "/api/tasks", json={"title": "Dave is nowhere", "list_id": W, "assignee_id": DAVE})
check(r.status_code == 400, "... also in a shared list without him " + str(r.status_code))

# ================================================================== #1138 "Assigned by me"
def byme(S, uid):
    """The client's filter (views.js dsxByMe) on what the server sends."""
    return {t["id"] for t in S.get(B + "/api/state").json()["tasks"]
            if t["status"] == 0 and t["assignee_id"] and t["assignee_id"] != uid and uid in (t["assigned_by"], t["created_by"])}


T2 = A.post(B + "/api/tasks", json={"title": "Check the texts", "list_id": P, "assignee_id": CAROL}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"title": "My own", "list_id": P, "assignee_id": ALICE}).json()["id"]
T4 = A.post(B + "/api/tasks", json={"title": "Done already", "list_id": P, "assignee_id": BOB}).json()["id"]
A.post(B + f"/api/tasks/{T4}/complete")
T5 = Bo.post(B + "/api/tasks", json={"title": "Bob for carol", "list_id": W, "assignee_id": CAROL}).json()["id"]
T6 = Ca.post(B + "/api/tasks", json={"title": "Carol made, alice assigns", "list_id": W}).json()["id"]
check(A.patch(B + f"/api/tasks/{T6}", json={"assignee_id": BOB}).ok, "alice assigns carol's task to bob")
got = byme(A, ALICE)
check({T1, T2, T6} <= got, "assigned by me: created-for and assigned-by tasks " + str(sorted(got)))
check(T3 not in got and T4 not in got and T5 not in got, "assigned by me: not my own, not completed, not someone else's assignment")
check(byme(Bo, BOB) == {T5}, "bob's view: only what he assigned " + str(sorted(byme(Bo, BOB))))
# alice leaves carol's list: those tasks are no longer sent to her (the view cannot show them)
r = Ca.delete(B + f"/api/lists/{W}/members/{ALICE}")
check(r.ok, "carol removes alice from her list " + r.text[:80])
got = byme(A, ALICE)
check(T1 not in got and T6 not in got and T2 in got, "after leaving: the tasks of that list are gone " + str(sorted(got)))
st = A.get(B + "/api/state").json()
check(not any(t["id"] in (T1, T6) for t in st["tasks"]), "the state holds no task of the left list")
check(A.get(B + f"/api/tasks/{T1}/timeline").status_code == 404, "the task itself is 404 for her now")

print(f"p2362_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
