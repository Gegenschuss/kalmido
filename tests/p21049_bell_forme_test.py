#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1049.0 (#5806): what the bell's "For you" counts besides mentions, assignments and replies (collab/news.py news_to_me).
The person is frida WITHOUT an organisation (tests/freelancer_fixture.py); bob is a colleague on a shared project.
 - (a) an invitation to an event: "For you"
 - (b) a colleague marks a task "urgent" for me: "For you"
 - (c) a person's plain comment on a task I created / that is assigned to me: "For you" (no reply, no mention needed);
   the same comment on a task I only watch stays Activity (not counted)
 - (d) (e) the ready proposal, the Playbook proposal and the stalled job: p230 / p2390_a / p23922_b
usage: p21049_bell_forme_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import B, check, done, fresh, sess, setup  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

fresh()
A = setup("alice", "Alice")
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
FID, Fr = freelancer(B, A)


def bell():
    return Fr.get(B + "/api/state").json()["news"]["unread_me"]


def feed(kind):
    return [x for x in Fr.get(B + "/api/news").json()["items"] if x["kind"] == kind]


def read_all():
    assert Fr.post(B + "/api/news/read", json={"all": True}).ok
    assert bell() == 0, bell()


def task(s, title, lid, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.status_code < 300, r.text
    return r.json()["id"]


FL = Fr.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
assert Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": BOB, "role": "edit"}).ok
BL = Bo.post(B + "/api/lists", json={"name": "Bob's"}).json()["id"]
assert Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": FID, "role": "edit"}).ok
TF = task(Fr, "Created by frida", FL)
TB = task(Bo, "Assigned to frida", FL, assignee_id=FID)
TO = task(Bo, "Bob's own, frida watches", FL)
assert Fr.post(B + f"/api/tasks/{TO}/watchers", json={}).ok
TU = task(Bo, "Bob's task for the bell", BL)
read_all()

# ---- (c) comments of a person
for t, what in ((TF, "created by me"), (TB, "assigned to me")):
    assert Bo.post(B + f"/api/tasks/{t}/comments", json={"body": "plain note on " + what}).ok
    it = [x for x in feed("comment") if x["task_id"] == t and not x["read"]]
    check(len(it) == 1 and it[0]["to_me"], f"(c) bob's plain comment on a task {what} is 'For you' {it}")
check(bell() == 2, f"(c) the bell counts both: {bell()}")
assert Bo.post(B + f"/api/tasks/{TO}/comments", json={"body": "only watched"}).ok
it = [x for x in feed("comment") if x["task_id"] == TO]
check(not any(x["to_me"] for x in it) and bell() == 2, f"(c) a comment on a task I only watch stays Activity {it} {bell()}")
read_all()

# ---- (b) "urgent" for me
r = Bo.put(B + f"/api/tasks/{TU}/bell", json={"level": "urgent", "users": [FID]})
check(r.ok and r.json().get("changed") == 1, f"(b) bob marks his task urgent for frida {r.status_code} {r.text[:200]}")
it = feed("tbl_urgent")
check(len(it) == 1 and it[0]["to_me"] and not it[0]["read"] and it[0]["task_id"] == TU, f"(b) 'For you' {it}")
check(bell() == 1, f"(b) the bell counts it: {bell()}")
read_all()

# ---- (a) an invitation
r = Bo.post(B + "/api/events", json={"title": "Kickoff", "start": "2026-12-03T15:00", "end": "2026-12-03T16:00", "tz": "Europe/Berlin",
                                      "attendees": [{"user_id": FID}]})
check(r.status_code < 300, f"(a) bob invites frida {r.status_code} {r.text[:200]}")
it = feed("evinvite")
check(len(it) == 1 and it[0]["to_me"] and not it[0]["read"] and it[0]["data"].get("title") == "Kickoff", f"(a) 'For you' {it}")
check(bell() == 1, f"(a) the bell counts it: {bell()}")
check(Fr.post(B + "/api/news/read", json={"ids": [it[0]["id"]]}).ok and bell() == 0, "(a) read = out of the number")
sys.exit(done("p21049_bell_forme"))
