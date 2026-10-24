#!/usr/bin/env python3
"""2.269.0 B (#3034): the conflict checks (_prev, expect_updated_at, expect) run under the row's lock, so two saves with the
same base at the same moment never both pass (two offline queues coming online together, agents).
 - task: two parallel PATCH {title, _prev} with the same base -> exactly one changes it, the other reports a conflict
 - wiki page / note: two parallel PATCH with the same expect_updated_at -> exactly one 200, the other 409
 - contact: two parallel PATCH with the same expect -> one 200, one 409
 - section: two parallel PATCH {name, _prev} -> one renames, the other reports a conflict
 - without the check field: as before (both 200, the later one wins)
 - a person without an organisation (freelancer-matrix: tasks): task, page and note the same
usage: p2269_b_locks_test.py <datadir>      (KMT_NOSTART=1 / P2269BL_NOSTART=1: a running server)"""
import sys
import threading

from freelancer_fixture import freelancer, login
from kt import B, check, done, fresh, sess, setup

fresh(prefix="P2269BL")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,collab,contacts,wiki,kanban", "tour": "done"})
ROUNDS = 6


def parallel(*calls):
    bar, out = threading.Barrier(len(calls)), [None] * len(calls)

    def run(i, fn):
        bar.wait()
        out[i] = fn()
    ts = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    return out


def task_rounds(s1, s2, who):
    bad = 0
    for i in range(ROUNDS):
        t = s1.post(B + "/api/tasks", json={"title": f"Base {i}"}).json()
        r1, r2 = parallel(lambda: s1.patch(B + f"/api/tasks/{t['id']}", json={"title": f"Phone {i}", "_prev": {"title": f"Base {i}"}}),
                          lambda: s2.patch(B + f"/api/tasks/{t['id']}", json={"title": f"Desk {i}", "_prev": {"title": f"Base {i}"}}))
        nconf = sum(1 for r in (r1, r2) if r.ok and r.json().get("conflicts"))
        if not (r1.ok and r2.ok and nconf == 1):
            bad += 1
            print("  task round", i, r1.status_code, r2.status_code, r1.text[:150], r2.text[:150])
    check(bad == 0, f"{who}: task: exactly one of two parallel saves with the same _prev gets a conflict ({bad} of {ROUNDS} rounds wrong)")
    t = s1.post(B + "/api/tasks", json={"title": "Plain"}).json()
    r1, r2 = parallel(lambda: s1.patch(B + f"/api/tasks/{t['id']}", json={"title": "Plain 1"}),
                      lambda: s2.patch(B + f"/api/tasks/{t['id']}", json={"title": "Plain 2"}))
    check(r1.ok and r2.ok and not r1.json().get("conflicts") and not r2.json().get("conflicts"), f"{who}: task without _prev: both 200 as before")


def expect_rounds(s1, s2, who, new, url, field, body):
    """new(i) -> the object (with id + updated_at); two parallel PATCH with the same base: one 200, one 409"""
    bad = 0
    for i in range(ROUNDS):
        o = new(i)
        base = o["updated_at"]
        r1, r2 = parallel(lambda: s1.patch(B + url.format(o["id"]), json={**body(i, "phone"), field: base}),
                          lambda: s2.patch(B + url.format(o["id"]), json={**body(i, "desk"), field: base}))
        if sorted((r1.status_code, r2.status_code)) != [200, 409]:
            bad += 1
            print("  round", i, r1.status_code, r2.status_code, r1.text[:150], r2.text[:150])
    check(bad == 0, f"{who}: {url}: two parallel saves with the same base -> one 200, one 409 ({bad} of {ROUNDS} rounds wrong)")
    o = new(99)
    r1, r2 = parallel(lambda: s1.patch(B + url.format(o["id"]), json=body(99, "a")), lambda: s2.patch(B + url.format(o["id"]), json=body(99, "b")))
    check(r1.status_code == 200 and r2.status_code == 200, f"{who}: {url} without {field}: both 200 as before ({r1.status_code}, {r2.status_code})")


def suite(s1, s2, who, contacts=True):
    task_rounds(s1, s2, who)
    expect_rounds(s1, s2, who, lambda i: s1.post(B + "/api/wiki/pages", json={"space": "private", "path": f"Race {who} {i}", "body": "Base"}).json(),
                  "/api/wiki/pages/{}", "expect_updated_at", lambda i, w: {"body": f"Text from the {w} {i}"})
    lid = s1.post(B + "/api/lists", json={"name": f"Notes {who}"}).json()["id"]
    expect_rounds(s1, s2, who, lambda i: s1.post(B + f"/api/lists/{lid}/notes", json={"title": f"N{i}", "body": "Base"}).json(),
                  "/api/notes/{}", "expect_updated_at", lambda i, w: {"body": f"Note from the {w} {i}"})
    if contacts:
        expect_rounds(s1, s2, who, lambda i: s1.post(B + "/api/contacts", json={"fn": f"Contact {i}"}).json(),
                      "/api/contacts/{}", "expect", lambda i, w: {"fn": f"Contact {w} {i}"})
    bad = 0
    for i in range(ROUNDS):
        sid = s1.post(B + "/api/sections", json={"list_id": lid, "name": f"Col {i}"}).json()["id"]
        r1, r2 = parallel(lambda: s1.patch(B + f"/api/sections/{sid}", json={"name": f"Phone {i}", "_prev": {"name": f"Col {i}"}}),
                          lambda: s2.patch(B + f"/api/sections/{sid}", json={"name": f"Desk {i}", "_prev": {"name": f"Col {i}"}}))
        nconf = sum(1 for r in (r1, r2) if r.ok and r.json().get("conflicts"))
        if not (r1.ok and r2.ok and nconf == 1):
            bad += 1
            print("  section round", i, r1.status_code, r2.status_code, r1.text[:150], r2.text[:150])
    check(bad == 0, f"{who}: section: exactly one of two parallel renames with the same _prev gets a conflict ({bad} of {ROUNDS} rounds wrong)")


suite(A, sess("alice"), "admin")
FID, Fr = freelancer(B, A)
suite(Fr, login(B, "frida"), "freelancer")

sys.exit(done("p2269_b_locks"))
