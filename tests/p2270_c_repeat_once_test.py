#!/usr/bin/env python3
"""2.270.0 C (#3022): a recurring task advances once per tick, however often the tick is sent. Own container, invented names.
 - batch "complete" with data.expect (the date the device saw, also {due, due_time}) sent twice: the date moves one day, one
   completed copy; the second answer reports the task as a conflict (already ticked) and changes nothing
 - API v1 POST /tasks/<id>/complete with expect_due twice: once, the second answer says skipped; an unknown field 400;
   the OpenAPI describes expect_due and the header Idempotency-Key
 - header Idempotency-Key (offline queue, service worker, agents): the same key twice = one effect, the second answer is the
   first one (Idempotent-Replayed); also POST /api/tasks (one task, the same id) and API v1; a request that failed frees its
   key; another person's same key is their own; without the header everything stays as before
 - a person without an organisation (the own private space): the same -- freelancer-matrix: tasks
usage: p2270_c_repeat_once_test.py <datadir>      (P2270C_NOSTART=1: use a running server)"""
import sys
import uuid
from datetime import timedelta

import requests

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

kt.fresh(prefix="P2270C")
A = kt.setup()
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
TODAY = kt.today()
V = B + "/api/v1"


def task(s, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def one(s, tid):
    return s.get(B + f"/api/tasks/{tid}").json()


def copies(s, title):
    j = s.get(B + "/api/tasks?scope=done&limit=2000").json()
    return [t["title"] for t in (j.get("tasks") if isinstance(j, dict) else j) or []].count(title)


def tok(s):
    r = s.post(B + "/api/me/tokens", json={"name": "t" + uuid.uuid4().hex[:8], "scopes": ["read", "write"]})
    assert r.ok, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def daily(s, lid, title):
    return task(s, title, list_id=lid, due=TODAY.isoformat(), repeat="FREQ=DAILY")


def run(s, who, lid):
    day1 = (TODAY + timedelta(days=1)).isoformat()
    # batch complete twice with the date the device saw
    title = f"Feed the cat {who}"
    T = daily(s, lid, title)
    body = {"ids": [T], "action": "complete", "data": {"expect": {str(T): TODAY.isoformat()}}}
    r1 = s.post(B + "/api/tasks/batch", json=body)
    r2 = s.post(B + "/api/tasks/batch", json=body)
    check(r1.ok and r2.ok, f"{who}: batch twice ok {r1.status_code} {r2.status_code} {r2.text[:200]}")
    check(one(s, T)["due"] == day1 and copies(s, title) == 1, f"{who}: batch sent twice = advanced once ({one(s, T)['due']}, {copies(s, title)} copies)")
    cf = r2.json().get("conflicts") or []
    check(len(cf) == 1 and cf[0]["id"] == T and cf[0]["field"] == "due" and not r2.json().get("errors"),
          f"{who}: the second batch reports 'already ticked' without an error {r2.text[:300]}")
    # the form {due, due_time}
    title = f"Water the fern {who}"
    T = daily(s, lid, title)
    body = {"ids": [T], "action": "complete", "data": {"expect": {str(T): {"due": TODAY.isoformat(), "due_time": None}}}}
    s.post(B + "/api/tasks/batch", json=body)
    s.post(B + "/api/tasks/batch", json=body)
    check(one(s, T)["due"] == day1 and copies(s, title) == 1, f"{who}: expect as {{due, due_time}}: advanced once")
    # without expect the batch works as before (one tick)
    title = f"Empty the bin {who}"
    T = daily(s, lid, title)
    r = s.post(B + "/api/tasks/batch", json={"ids": [T], "action": "complete", "data": {}})
    check(r.ok and r.json().get("count") == 1 and one(s, T)["due"] == day1, f"{who}: batch without expect as before {r.text[:200]}")

    # API v1 with expect_due
    H = tok(s)
    title = f"Check the mail {who}"
    T = daily(s, lid, title)
    r1 = requests.post(V + f"/tasks/{T}/complete", headers=H, json={"expect_due": TODAY.isoformat()})
    r2 = requests.post(V + f"/tasks/{T}/complete", headers=H, json={"expect_due": TODAY.isoformat()})
    check(r1.ok and r1.json().get("next_due") == day1 and not r1.json().get("skipped"), f"{who}: v1 complete advances {r1.text[:200]}")
    check(r2.ok and r2.json().get("skipped") is True and r2.json().get("next_due") is None, f"{who}: v1 repeat with expect_due skipped {r2.text[:200]}")
    check(one(s, T)["due"] == day1 and copies(s, title) == 1, f"{who}: v1 twice = advanced once")
    r = requests.post(V + f"/tasks/{T}/complete", headers=H, json={"expect_date": day1})
    check(r.status_code == 400, f"{who}: v1 complete with an unknown field 400 ({r.status_code})")
    r = requests.post(V + f"/tasks/{T}/complete", headers=H)
    check(r.ok and r.json().get("next_due"), f"{who}: v1 complete without a body as before {r.text[:200]}")

    # Idempotency-Key: API v1
    title = f"Take the vitamins {who}"
    T = daily(s, lid, title)
    k = "agent-" + uuid.uuid4().hex
    r1 = requests.post(V + f"/tasks/{T}/complete", headers={**H, "Idempotency-Key": k})
    r2 = requests.post(V + f"/tasks/{T}/complete", headers={**H, "Idempotency-Key": k})
    check(r1.ok and r2.ok and r2.headers.get("Idempotent-Replayed") == "true" and r2.json() == r1.json(),
          f"{who}: v1 same key twice: the first answer again {r2.status_code} {r2.headers.get('Idempotent-Replayed')}")
    check(one(s, T)["due"] == day1 and copies(s, title) == 1, f"{who}: v1 same key twice = advanced once ({one(s, T)['due']})")
    r3 = requests.post(V + f"/tasks/{T}/complete", headers={**H, "Idempotency-Key": "agent-" + uuid.uuid4().hex})
    check(r3.ok and not r3.headers.get("Idempotent-Replayed") and one(s, T)["due"] == (TODAY + timedelta(days=2)).isoformat(),
          f"{who}: a new key is a new tick")

    # Idempotency-Key: the offline queue (batch without expect, like an old queued entry) and a new task
    title = f"Stretch {who}"
    T = daily(s, lid, title)
    k = uuid.uuid4().hex[:16]
    body = {"ids": [T], "action": "complete", "data": {}}
    r1 = s.post(B + "/api/tasks/batch", json=body, headers={"Idempotency-Key": k})
    r2 = s.post(B + "/api/tasks/batch", json=body, headers={"Idempotency-Key": k})
    check(r1.ok and r2.ok and r2.headers.get("Idempotent-Replayed") == "true", f"{who}: queue replay answered from the store")
    check(one(s, T)["due"] == day1 and copies(s, title) == 1, f"{who}: queue entry sent twice (worker + tab) = advanced once")
    k = uuid.uuid4().hex[:16]
    r1 = s.post(B + "/api/tasks", json={"title": f"Buy stamps {who}", "list_id": lid}, headers={"Idempotency-Key": k})
    r2 = s.post(B + "/api/tasks", json={"title": f"Buy stamps {who}", "list_id": lid}, headers={"Idempotency-Key": k})
    lst = s.get(B + "/api/state").json()["tasks"]
    check(r1.ok and r2.ok and r1.json()["id"] == r2.json()["id"] and [t["title"] for t in lst].count(f"Buy stamps {who}") == 1,
          f"{who}: a new task sent twice with one key = one task, the same id {r1.text[:120]} {r2.text[:120]}")
    # a failed request frees its key
    k = uuid.uuid4().hex[:16]
    r = s.patch(B + "/api/tasks/987654321", json={"title": "x"}, headers={"Idempotency-Key": k})
    check(r.status_code >= 400, f"{who}: change of a task that does not exist fails ({r.status_code})")
    r = s.patch(B + "/api/tasks/987654321", json={"title": "x"}, headers={"Idempotency-Key": k})
    check(r.status_code >= 400 and not r.headers.get("Idempotent-Replayed"), f"{who}: a failure is never stored")
    title = f"Call grandma {who}"
    T = task(s, title, list_id=lid)
    k = uuid.uuid4().hex[:16]
    s.patch(B + "/api/tasks/987654321", json={"title": "x"}, headers={"Idempotency-Key": k})
    r = s.patch(B + f"/api/tasks/{T}", json={"title": title + " today"}, headers={"Idempotency-Key": k})
    check(r.ok and one(s, T)["title"] == title + " today", f"{who}: after a failure the same key works {r.status_code} {r.text[:200]}")
    # a key of another call (other path) does not replay a wrong answer
    r = s.patch(B + f"/api/tasks/{T}", json={"priority": 3}, headers={"Idempotency-Key": uuid.uuid4().hex[:16]})
    check(r.ok and one(s, T)["priority"] == 3, f"{who}: PATCH with a key changes as usual")
    return k


K = run(A, "alice", A.get(B + "/api/state").json()["lists"][0]["id"])
# another person's same key is their own
BL = Bo.post(B + "/api/lists", json={"name": "Garden"}).json()["id"]
T = task(Bo, "Rake leaves", list_id=BL)
r = Bo.patch(B + f"/api/tasks/{T}", json={"priority": 5}, headers={"Idempotency-Key": K})
check(r.ok and not r.headers.get("Idempotent-Replayed") and one(Bo, T)["priority"] == 5, "bob: alice's key is not his")
# a malformed key is ignored (runs as without a key)
r = Bo.patch(B + f"/api/tasks/{T}", json={"priority": 1}, headers={"Idempotency-Key": "bad key with spaces"})
check(r.ok and one(Bo, T)["priority"] == 1, "a malformed key: runs as without one")
# OpenAPI
sp = requests.get(V + "/openapi.json").json()
op = sp["paths"]["/tasks/{id}/complete"]["post"]
check("expect_due" in str(op.get("requestBody")) and "Idempotency-Key" in str(op.get("parameters")) and op["requestBody"]["required"] is False,
      "OpenAPI: expect_due (optional body) and Idempotency-Key")

# ============================================================ a person without an organisation (freelancer-matrix: tasks)
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Studio"}).json()["id"]
run(Fr, "frida", FL)

sys.exit(kt.done("p2270_c_repeat_once"))
