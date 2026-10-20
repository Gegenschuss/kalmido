#!/usr/bin/env python3
"""2.126.0 API tests, part D (#1987 #1990 #1992): tasks and lists. Own container (start.sh), invented names only.
 - #1987 a recurring task completed twice at the same moment (two sessions, also batch + single): every completion that
   is not "skipped" leaves exactly one completed copy, the date and COUNT move once per copy
 - #1990 POST /api/tasks with the same client_ref twice (also at the same moment, also a subtask) = one task, the same id;
   another person's ref is their own; the completed copy of a recurring task does not take the ref along
 - #1992 A3 a task in the trash: PATCH / complete / skip / reopen 409, a reorder leaves it where it is; restored = editable
 - A4 a subtask under a parent in the trash is refused (create and move)
 - A5 moved to another list: who comes along stays only when they share the target list (subtasks too)
 - A6 view only: duplicate the list / save it as a template 403; an editor may
 - A7 a drag into another list of a task that waits behind the review gate: 409, the list stays
 - A8 a batch with more than 1000 ids: 400; a batch change that fails for one task leaves that task as it was
 - O4 logging out answers Clear-Site-Data "cache"
 - a person without an organisation (the own private space, its own admin): the same -- freelancer-matrix: tasks, lists
usage: p2126_d_api_test.py <datadir>      (P2126D_NOSTART=1: use a running server)"""
import os
import subprocess
import sys
import threading
import uuid
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

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


if not os.environ.get("P2126D_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
IDS = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    IDS[u] = r.json()["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "cal,comments,collab,review"})


def task(s, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def one(s, tid):
    return s.get(B + f"/api/tasks/{tid}").json()


def done_titles(s):
    j = s.get(B + "/api/tasks?scope=done&limit=2000").json()
    return [t["title"] for t in (j.get("tasks") if isinstance(j, dict) else j) or []]


def trash_row(s, tid):
    j = s.get(B + "/api/tasks?scope=trash&limit=2000").json()
    return next((t for t in (j.get("tasks") if isinstance(j, dict) else j) or [] if t["id"] == tid), None)


def at_once(*calls):
    """Runs the calls in threads released together; their responses in call order."""
    bar, out = threading.Barrier(len(calls)), [None] * len(calls)

    def go(i, fn):
        bar.wait()
        out[i] = fn()
    ths = [threading.Thread(target=go, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    return out


def recurring_race(s1, s2, lid, who, rounds=4, batch=False):
    """#1987: a daily task with COUNT=20 completed by two sessions at once, several rounds."""
    title = f"Water the plants {who} {batch}"
    today = testclock.today()
    R = task(s1, title, list_id=lid, due=today.isoformat(), repeat="FREQ=DAILY;COUNT=20")
    advanced = 0
    for i in range(rounds):
        second = (lambda: s2.post(B + "/api/tasks/batch", json={"ids": [R], "action": "complete"})) if batch else \
            (lambda: s2.post(B + f"/api/tasks/{R}/complete", json={}))
        r1, r2 = at_once(lambda: s1.post(B + f"/api/tasks/{R}/complete", json={}), second)
        check(r1.ok and r2.ok, f"{who}: round {i}: both answers ok {r1.status_code} {r2.status_code} {r2.text[:200]}")
        n = int(not r1.json().get("skipped"))
        n += (r2.json().get("count", 0) if batch else int(not r2.json().get("skipped")))
        check(n in (1, 2), f"{who}: round {i}: at least one completion counts ({n})")
        advanced += n
    copies = done_titles(s1).count(title)
    t = one(s1, R)
    check(copies == advanced, f"{who}: one completed copy per completion that counted ({copies} copies, {advanced} completions)")
    check(t["due"] == (today + timedelta(days=advanced)).isoformat(), f"{who}: the date moved once per completion {t['due']} ({advanced})")
    check(f"COUNT={20 - advanced}" in t["repeat"], f"{who}: COUNT one down per completion {t['repeat']} ({advanced})")
    # a tick after that (not at the same moment) advances as always
    r = s1.post(B + f"/api/tasks/{R}/complete", json={})
    check(r.ok and not r.json().get("skipped") and r.json().get("next_due"), f"{who}: a later tick advances again {r.text[:200]}")
    # with the date the device saw (expect_due): an old one is skipped
    r = s2.post(B + f"/api/tasks/{R}/complete", json={"expect_due": today.isoformat()})
    check(r.ok and r.json().get("skipped"), f"{who}: a tick for a date that is gone is skipped {r.text[:200]}")


def client_ref(s, lid, who):
    """#1990: the same create sent again is the same task."""
    ref = "r" + uuid.uuid4().hex[:12]
    r1 = s.post(B + "/api/tasks", json={"title": f"Call the plumber {who}", "list_id": lid, "client_ref": ref})
    r2 = s.post(B + "/api/tasks", json={"title": f"Call the plumber {who}", "list_id": lid, "client_ref": ref})
    check(r1.ok and r2.ok and r1.json()["id"] == r2.json()["id"], f"{who}: the same client_ref = the same task {r1.text[:120]} {r2.text[:120]}")
    check("client_ref" not in r1.json(), f"{who}: the ref is not part of the task's answer")
    tid = r1.json()["id"]
    state = s.get(B + "/api/state").json()["tasks"]
    check(sum(1 for t in state if t["title"] == f"Call the plumber {who}") == 1, f"{who}: one task in the state")
    k1 = s.post(B + "/api/tasks", json={"title": "Ask for a quote", "parent_id": tid, "client_ref": ref + "k"})
    k2 = s.post(B + "/api/tasks", json={"title": "Ask for a quote", "parent_id": tid, "client_ref": ref + "k"})
    check(k1.ok and k2.ok and k1.json()["id"] == k2.json()["id"] and k1.json()["parent_id"] == tid, f"{who}: a subtask sent twice = one subtask")
    ref2 = "r" + uuid.uuid4().hex[:12]
    a, b = at_once(*[lambda: s.post(B + "/api/tasks", json={"title": f"Order paint {who}", "list_id": lid, "client_ref": ref2})] * 2)
    check(a.ok and b.ok and a.json()["id"] == b.json()["id"], f"{who}: sent twice at the same moment = one task {a.status_code} {b.status_code} {b.text[:200]}")
    # a recurring task with a ref: its completed copy does not take the ref (the next send finds the open task)
    ref3 = "r" + uuid.uuid4().hex[:12]
    R = s.post(B + "/api/tasks", json={"title": f"Feed the cat {who}", "list_id": lid, "due": testclock.today().isoformat(),
                                       "repeat": "FREQ=DAILY", "client_ref": ref3}).json()["id"]
    check(s.post(B + f"/api/tasks/{R}/complete", json={}).ok, f"{who}: the recurring task completes")
    r = s.post(B + "/api/tasks", json={"title": f"Feed the cat {who}", "list_id": lid, "client_ref": ref3})
    check(r.ok and r.json()["id"] == R and r.json()["status"] == 0, f"{who}: the ref stays with the open task {r.text[:200]}")
    return ref


def trash(s, lid, who):
    """#1992 A3 / A4: a task in the trash stays as it is; nothing is hung under it."""
    T = task(s, f"Old note {who}", list_id=lid, due=testclock.today().isoformat(), repeat="FREQ=WEEKLY")
    L2 = s.post(B + "/api/lists", json={"name": f"Elsewhere {who}"}).json()["id"]
    check(s.delete(B + f"/api/tasks/{T}").ok, f"{who}: into the trash")
    check(s.patch(B + f"/api/tasks/{T}", json={"title": "Changed"}).status_code == 409, f"{who}: A3 PATCH in the trash 409")
    check(s.post(B + f"/api/tasks/{T}/complete", json={}).status_code == 409, f"{who}: A3 complete in the trash 409")
    check(s.post(B + f"/api/tasks/{T}/skip", json={}).status_code == 409, f"{who}: A3 skip in the trash 409")
    check(s.post(B + f"/api/tasks/{T}/reopen", json={}).status_code == 409, f"{who}: A3 reopen in the trash 409")
    r = s.post(B + "/api/tasks/reorder", json={"items": [{"id": T, "list_id": L2, "sort": 1}]})
    row = trash_row(s, T)
    check(r.ok and row and row["list_id"] == lid and row["title"] == f"Old note {who}", f"{who}: A3 a reorder leaves it {r.status_code} {row and row['list_id']}")
    check(done_titles(s).count(f"Old note {who}") == 0, f"{who}: A3 no completed copy")
    r = s.post(B + "/api/tasks", json={"title": "Child", "parent_id": T})
    check(r.status_code == 400 and "trash" in r.text, f"{who}: A4 no new subtask under a parent in the trash {r.status_code} {r.text[:200]}")
    K = task(s, f"Loose end {who}", list_id=lid)
    r = s.patch(B + f"/api/tasks/{K}", json={"parent_id": T})
    check(r.status_code == 400 and not one(s, K).get("parent_id"), f"{who}: A4 not moved under a parent in the trash {r.status_code}")
    check(s.post(B + f"/api/tasks/{T}/restore").ok, f"{who}: restored")
    r = s.patch(B + f"/api/tasks/{T}", json={"title": f"Old note {who} again"})
    check(r.ok and r.json()["title"] == f"Old note {who} again", f"{who}: A3 restored = editable again {r.status_code}")
    check(s.patch(B + f"/api/tasks/{K}", json={"parent_id": T}).ok, f"{who}: A4 a live parent takes the subtask")


def batch(s, lid, who):
    """#1992 A8: a limit, and no half change of one task."""
    r = s.post(B + "/api/tasks/batch", json={"ids": list(range(1, 1102)), "action": "patch", "data": {"priority": 1}})
    check(r.status_code == 400, f"{who}: A8 more than 1000 ids 400 ({r.status_code})")
    r = s.post(B + "/api/tasks/reorder", json={"items": [{"id": i, "sort": i} for i in range(1, 1102)]})
    check(r.status_code == 400, f"{who}: A8 a reorder of more than 1000 tasks 400 ({r.status_code})")
    X, Y = task(s, f"Sort the mail {who}", list_id=lid), task(s, f"File the receipts {who}", list_id=lid)
    r = s.post(B + "/api/tasks/batch", json={"ids": [X, Y], "action": "patch", "data": {"title": "Changed", "people": [IDS["dave"]]}})
    check(r.ok and r.json().get("errors") and r.json().get("count") == 0, f"{who}: A8 the error is reported {r.text[:200]}")
    check(one(s, X)["title"] == f"Sort the mail {who}" and one(s, Y)["title"] == f"File the receipts {who}",
          f"{who}: A8 a task the change failed for keeps its title")
    r = s.post(B + "/api/tasks/batch", json={"ids": [X, Y], "action": "patch", "data": {"priority": 5}})
    check(r.ok and r.json().get("count") == 2 and one(s, X)["priority"] == 5, f"{who}: a valid batch still changes all {r.text[:200]}")


# ============================================================ the organisation's people
P = A.post(B + "/api/lists", json={"name": "Chores"}).json()["id"]
A.put(B + f"/api/lists/{P}/members", json={"user_id": IDS["bob"], "role": "edit"})
A.put(B + f"/api/lists/{P}/members", json={"user_id": IDS["carol"], "role": "view"})
A2 = sess("alice")
recurring_race(A, A2, P, "alice")
recurring_race(A, Bo, P, "alice+bob", rounds=3, batch=True)
ref = client_ref(A, P, "alice")
r = Bo.post(B + "/api/tasks", json={"title": "Call the plumber bob", "client_ref": ref})
check(r.ok and r.json()["id"] != A.post(B + "/api/tasks", json={"title": "Call the plumber alice", "client_ref": ref}).json()["id"],
      "#1990: another person's same ref is a task of their own")
trash(A, P, "alice")
batch(A, P, "alice")

# A5: who comes along stays only when they share the target list
P3 = A.post(B + "/api/lists", json={"name": "Alice alone"}).json()["id"]
T = task(A, "Picnic", list_id=P, people=[IDS["bob"]])
K = task(A, "Bring the blanket", parent_id=T)
check(A.patch(B + f"/api/tasks/{K}", json={"people": [IDS["bob"]]}).ok, "A5 setup: bob comes along to the subtask")
check(one(A, T).get("people") == [IDS["bob"]], "A5 setup: bob comes along")
r = A.patch(B + f"/api/tasks/{T}", json={"list_id": P3})
check(r.ok and not one(A, T).get("people") and not one(A, K).get("people"), f"A5 moved: bob no longer comes along {one(A, T).get('people')} {one(A, K).get('people')}")
check(Bo.get(B + f"/api/tasks/{T}").status_code == 404, "A5 bob does not see the moved task")
T2 = task(A, "Barbecue", list_id=P, people=[IDS["bob"]])
P4 = A.post(B + "/api/lists", json={"name": "Weekend"}).json()["id"]
A.put(B + f"/api/lists/{P4}/members", json={"user_id": IDS["bob"], "role": "edit"})
A.put(B + f"/api/lists/{P4}/members", json={"user_id": IDS["carol"], "role": "view"})  # everyone of P sees it: an editor may move there
check(A.post(B + "/api/tasks/reorder", json={"items": [{"id": T2, "list_id": P4, "sort": 1}]}).ok, "A5 dragged into a list bob shares")
check(one(A, T2).get("people") == [IDS["bob"]], "A5 bob shares the target list: he still comes along")

# A6: view only
r = Ca.post(B + f"/api/lists/{P}/duplicate", json={})
check(r.status_code == 403, f"A6 view only: no duplicate ({r.status_code})")
r = Ca.post(B + "/api/templates", json={"list_id": P, "name": "Copy of chores"})
check(r.status_code == 403, f"A6 view only: no list template ({r.status_code})")
r = Bo.post(B + f"/api/lists/{P}/duplicate", json={})
check(r.ok and r.json().get("list_id"), f"A6 an editor duplicates {r.status_code} {r.text[:200]}")
r = Bo.post(B + "/api/templates", json={"list_id": P, "name": "Chores template"})
check(r.ok, f"A6 an editor saves a template {r.status_code} {r.text[:200]}")
check(Da.post(B + f"/api/lists/{P}/duplicate", json={}).status_code == 404, "A6 a stranger 404")

# A7: the review gate holds on a drag too
check(A.put(B + f"/api/lists/{P}/review", json={"on": True, "reviewer": IDS["alice"], "gate": True}).ok, "A7 setup: the gate on")
G = task(Bo, "Publish the newsletter", list_id=P)
r = Bo.post(B + f"/api/tasks/{G}/review", json={"action": "reviewer", "reviewer_id": IDS["alice"]})
check(r.ok and one(A, G).get("reviewer_id") == IDS["alice"], f"A7 setup: alice reviews {r.text[:200]}")
r = Bo.post(B + "/api/tasks/reorder", json={"items": [{"id": G, "list_id": P4, "sort": 1}]})  # bob edits both lists
check(r.status_code == 409 and one(A, G)["list_id"] == P, f"A7 a drag out of the list waits for the approval ({r.status_code} {r.text[:200]})")
check(Bo.patch(B + f"/api/tasks/{G}", json={"list_id": P4}).status_code >= 400, "A7 like a PATCH")
T3 = task(Bo, "Print the posters", list_id=P)
r = Bo.post(B + "/api/tasks/reorder", json={"items": [{"id": T3, "list_id": P4, "sort": 1}]})
check(r.ok and one(A, T3)["list_id"] == P4, f"A7 a task without a review moves as before {r.status_code} {r.text[:200]}")
r = Bo.post(B + "/api/tasks/reorder", json={"items": [{"id": G, "sort": 5}]})
check(r.ok, f"A7 sorting inside the list stays free {r.status_code}")
r = A.post(B + "/api/tasks/reorder", json={"items": [{"id": G, "list_id": P3, "sort": 1}]})
check(r.ok and one(A, G)["list_id"] == P3, f"A7 the reviewer may move it {r.status_code} {r.text[:200]}")
A.put(B + f"/api/lists/{P}/review", json={"on": False})

# O4: logging out clears the browser's copies
L = sess("dave")
r = L.post(B + "/api/auth/logout")
check(r.ok and r.headers.get("Clear-Site-Data") == '"cache"', f"O4 logout: Clear-Site-Data {r.headers.get('Clear-Site-Data')}")

# ============================================================ a person without an organisation (freelancer-matrix: tasks, lists)
FID, Fr = freelancer(B, A)
Fr2 = sess("frida")
FL = Fr.post(B + "/api/lists", json={"name": "Studio"}).json()["id"]
recurring_race(Fr, Fr2, FL, "frida", rounds=3)
client_ref(Fr, FL, "frida")
trash(Fr, FL, "frida")
batch(Fr, FL, "frida")
r = Fr.post(B + f"/api/lists/{FL}/duplicate", json={})
check(r.ok, f"frida duplicates her own list {r.status_code} {r.text[:200]}")
check(Bo.post(B + f"/api/lists/{FL}/duplicate", json={}).status_code == 404, "frida's list: someone else 404")

print(f"p2126_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
