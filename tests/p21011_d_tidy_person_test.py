#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1011.0 D (#5685): the tidy event comes again only after a PERSON's change (kalmido/agents/core.py tidy_tick,
tidy_person_after). Before, every change of a task after its tidy event went out re-armed it - also the dispatcher's
fields and the tidy agent's own changes - so the same task came back every few minutes as "tidy by <whoever made it>".
 - the agent changes the task after the event (notes, a field - one agent per project, so the tidy agent is also the one
   that sets fields and comments, as the dispatcher does): no new tidy event (checked once a
   person's change of another task, made later, has brought that task's new event: the watchdog has looked at both)
 - the tidy agent's tidy is not refused (409) for an agent's change; a person's change still refuses it
 - a person changes it: a new tidy event once it is quiet again, with that person as actor (not the one who made the task)
usage: p21011_d_tidy_person_test.py <datadir>"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import B, check, done, fresh, me_id, sess, setup, until  # noqa: E402

V = B + "/api/v1"
os.environ["KALMIDO_TIDY_QUIET_S"] = "2"  # tests/start.sh hands it to the container (the watchdog ticks every second)
fresh()
A = setup("alice", "Alice")
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
check(r.ok, "bob " + r.text[:100])
BOB = r.json()["id"]
Bo = sess("bob")
me = me_id(A)


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": name,
                                               "display_name": name.title()})
    assert r.ok, r.text
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


CL, CLH = agent("tidier")  # one agent per project: it tidies, and it is also the one that changes tasks (the dispatcher)
T = A.post(B + "/api/lists", json={"name": "Tidy"}).json()["id"]
for u in (BOB, CL):  # the person first; the agent joins a project of alice and bob (bridge_ok: approved by alice)
    r = A.put(B + f"/api/lists/{T}/members", json={"user_id": u, "role": "edit", "bridge_ok": True})
    check(r.ok, f"member {u}: {r.status_code} {r.text[:200]}")
check(A.patch(B + f"/api/lists/{T}", json={"agent_tidy": "auto", "tidy_agent_id": CL}).ok, "tidy auto, tidier tidies")
CUR = {"c": 0}


def events():
    r = requests.get(V + f"/agent/events?since={CUR['c']}", headers=CLH)
    assert r.ok, r.text
    CUR["c"] = r.json()["cursor"]
    return [e for e in r.json()["data"] if e["event"] == "tidy"]


SEEN = []


def tidy_of(tid):
    """The tidy events of task tid seen so far (waits until one more came, or the time is over)."""
    SEEN.extend(events())
    return [e for e in SEEN if e["data"]["task"]["id"] == tid]


events()
ta = A.post(B + "/api/tasks", json={"title": "first entry, its notes changed by the agent later", "list_id": T}).json()["id"]
tb = A.post(B + "/api/tasks", json={"title": "second entry, its priority changed by the agent later", "list_id": T}).json()["id"]
tc = A.post(B + "/api/tasks", json={"title": "third entry changed by bob later", "list_id": T}).json()["id"]
check(until(lambda: all(tidy_of(t) for t in (ta, tb, tc)), timeout=30), "the first tidy event of all three tasks")
first = {t: len(tidy_of(t)) for t in (ta, tb, tc)}
check(first == {ta: 1, tb: 1, tc: 1} and all(e["actor"]["id"] == me for e in SEEN), f"once each, alice as actor {first}")

# agents change two of them after the event (with the version they read, conflict check of the core)


def v1_patch(hdr, tid, body):
    g = requests.get(V + f"/tasks/{tid}", headers=hdr)
    if not g.ok:
        return g
    return requests.patch(V + f"/tasks/{tid}", headers=hdr, json={**body, "expect_updated_at": g.json().get("updated_at")})


r = v1_patch(CLH, ta, {"content": "the agent's note"})
check(r.ok, f"the agent changes the notes of task A {r.status_code} {r.text[:200]}")
r = v1_patch(CLH, tb, {"priority": "high"})
check(r.ok, f"the agent changes the priority of task B {r.status_code} {r.text[:200]}")
# a person changes the third one: its new event shows that the watchdog has looked at all three since
check(Bo.patch(B + f"/api/tasks/{tc}", json={"content": "bob's notes"}).ok, "bob changes task C")
check(until(lambda: len(tidy_of(tc)) >= 2, timeout=30), "#5685: a person's change: a new tidy event of task C")
new_c = tidy_of(tc)[-1]
check(new_c["actor"] and new_c["actor"]["id"] == BOB and new_c["actor"]["kind"] == "person",
      f"#5685: the new event names the person who changed it (bob), not who made it: {new_c.get('actor')}")
# A and B were changed before C with the same quiet time: a wrong new event of theirs would have come with C's at the latest
check(len(tidy_of(ta)) == 1 and len(tidy_of(tb)) == 1,
      f"#5685: the agent's own changes send no new tidy event ({len(tidy_of(ta))}, {len(tidy_of(tb))})")

# the agent's tidy: not refused for an agent's change, still refused for a person's
r = requests.post(V + f"/tasks/{ta}/tidy", headers=CLH, json={"title": "First entry"})
check(r.ok, f"#5685: an agent's change does not block the tidy ({r.status_code} {r.text[:120]})")
check(Bo.patch(B + f"/api/tasks/{tb}", json={"content": "bob too"}).ok, "bob changes task B")
r = requests.post(V + f"/tasks/{tb}/tidy", headers=CLH, json={"title": "Second entry"})
check(r.status_code == 409, f"a person's change after the event: 409 as before ({r.status_code})")
x = next(t for t in A.get(B + "/api/state").json()["tasks"] if t["id"] == tb)
check(x["content"] == "bob too", "the person's text untouched")

sys.exit(done("p21011_d_tidy_person"))
