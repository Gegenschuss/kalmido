#!/usr/bin/env python3
"""2.270.0 D API tests (#3028: the agent API writes with a conflict check), own container (start.sh).
Invented people and figures only.
 - PATCH /api/v1/tasks/<id>: expect_updated_at / If-Match older than the task = 409 {error, current}, nothing changes;
   without it the old behaviour (last write wins); _prev {field: value read} keeps a field changed meanwhile (conflicts)
 - the history keeps the description before a change (activity content data.prev), also when an agent overwrote it
 - POST /api/v1/tasks with client_ref: the same ref again = the same task (200), never a second one
 - PATCH /api/v1/notes/<id>: a stale expect_updated_at guards pinned / tags too (409)
 - web batch "patch" with data.prev and reorder with _prev: a field changed elsewhere stays, reported in conflicts
 - an agent's quotation draft change keeps purchase price and price of a position (by id, or by its service without id);
   expect_updated_at of the draft
 - a person without an organisation (freelancer-matrix: tasks, office): own agent, own tasks, own office draft
usage: p2270_d_agent_conflict_test.py <datadir>   (P2270_D_NOSTART=1: against a running instance on KALMIDO_TEST_PORT)"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402  (tests/kt.py)


if not os.environ.get("P2270_D_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
Bo = sess("bob")
ids = {u["username"]: u["id"] for u in A.get(B + "/api/users").json()["users"]}
L = A.post(B + "/api/lists", json={"name": "Shared work"}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": ids["bob"], "role": "edit"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "claude", "display_name": "Claude"}).json()
AGID, AGH = ag.get("id"), {"Authorization": "Bearer " + ag.get("token", "x"), **H}
A.put(B + f"/api/lists/{L}/members", json={"user_id": AGID, "role": "edit"})


def agent(m, path, h=None, **kw):
    return requests.request(m, V + path, headers={**AGH, **(h or {})}, **kw)


# ================================================================== v1 PATCH: expect_updated_at / If-Match
T = A.post(B + "/api/tasks", json={"title": "Plan the shoot", "list_id": L, "content": "Start"}).json()["id"]
seen = agent("GET", f"/tasks/{T}").json()
time.sleep(1.1)
check(Bo.patch(B + f"/api/tasks/{T}", json={"content": "Bob's text"}).ok, "setup: a person changes the description")
r = agent("PATCH", f"/tasks/{T}", json={"notes": "Agent text", "expect_updated_at": seen["updated_at"]})
check(r.status_code == 409 and (r.json().get("current") or {}).get("notes") == "Bob's text" and r.json().get("error"),
      f"#3028: a stale expect_updated_at = 409 with the current task {r.status_code} {r.text[:200]}")
check(A.get(B + f"/api/tasks/{T}").json()["content"] == "Bob's text", "#3028: … and nothing changed")
r = agent("PATCH", f"/tasks/{T}", h={"If-Match": '"' + seen["updated_at"] + '"'}, json={"notes": "Agent text"})
check(r.status_code == 409, f"#3028: If-Match with the old updated_at = 409 too {r.status_code}")
check(agent("PATCH", f"/tasks/{T}", json={"notes": "x", "expect_updated_at": 5}).status_code == 400, "#3028: expect_updated_at must be text")
cur = agent("GET", f"/tasks/{T}").json()
r = agent("PATCH", f"/tasks/{T}", json={"notes": "Agent text", "expect_updated_at": cur["updated_at"]})
check(r.ok and r.json()["notes"] == "Agent text", f"#3028: the current updated_at writes {r.status_code} {r.text[:200]}")

# ================================================================== the history keeps the text before
acts = A.get(B + f"/api/tasks/{T}/timeline").json().get("activity", [])
mine = [a for a in acts if a["kind"] == "content" and a["user_id"] == AGID]
check(len(mine) == 1 and mine[0]["data"].get("prev") == "Bob's text", f"#3028: the agent's change keeps the person's text {mine}")
bob = [a for a in acts if a["kind"] == "content" and a["user_id"] == ids["bob"]]
check(bob and bob[0]["data"].get("prev") == "Start", f"#3028: the person's change keeps the text before too {bob}")
time.sleep(1.1)
check(agent("PATCH", f"/tasks/{T}", json={"notes": "Agent text 2"}).ok, "#3028: without expect: the old behaviour (last write wins)")
acts = A.get(B + f"/api/tasks/{T}/timeline").json().get("activity", [])
mine = [a for a in acts if a["kind"] == "content" and a["user_id"] == AGID]
check(len(mine) == 1 and mine[0]["data"].get("prev") == "Bob's text", f"#3028: a merged entry keeps the text before the first edit {mine}")

# ================================================================== v1 PATCH: _prev per field
seen = agent("GET", f"/tasks/{T}").json()
time.sleep(1.1)
Bo.patch(B + f"/api/tasks/{T}", json={"content": "Bob again"})
r = agent("PATCH", f"/tasks/{T}", json={"notes": "Agent 3", "priority": "high", "_prev": {"notes": seen["notes"], "priority": seen["priority"]}})
j = r.json() if r.ok else {}
check(r.ok and j.get("notes") == "Bob again" and j.get("priority") == "high", f"#3028: _prev: the changed field stays, the rest writes {r.status_code} {r.text[:200]}")
check([c["field"] for c in j.get("conflicts") or []] == ["notes"] and j["conflicts"][0]["server"] == "Bob again",
      f"#3028: _prev: conflicts with the API's field name {j.get('conflicts')}")
check(agent("PATCH", f"/tasks/{T}", json={"title": "x", "_prev": {"nonsense": 1}}).status_code == 400, "#3028: _prev with an unknown field: 400")

# ================================================================== v1 create: client_ref
r1 = agent("POST", "/tasks", json={"title": "Book the studio", "list_id": L, "client_ref": "run-7-a"})
r2 = agent("POST", "/tasks", json={"title": "Book the studio", "list_id": L, "client_ref": "run-7-a"})
check(r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"],
      f"#3028: the same client_ref again = the same task {r1.status_code} {r2.status_code}")
n = [t for t in A.get(B + "/api/state").json()["tasks"] if t["title"] == "Book the studio"]
check(len(n) == 1, f"#3028: one task, not two ({len(n)})")
check(agent("POST", "/tasks", json={"title": "y", "list_id": L, "client_ref": 7}).status_code == 400, "#3028: client_ref must be text")
r3 = agent("POST", "/tasks", json={"title": "Book the studio", "list_id": L})
check(r3.status_code == 201 and r3.json()["id"] != r1.json()["id"], "#3028: without client_ref: a new task as before")

# ================================================================== v1 notes: pinned / tags guarded
NID = A.post(B + f"/api/lists/{L}/notes", json={"title": "Call sheet", "body": "Day 1"}).json()["id"]
nseen = agent("GET", f"/notes/{NID}").json()
time.sleep(1.1)
check(Bo.patch(B + f"/api/notes/{NID}", json={"pinned": True}).ok, "setup: a person pins the note")
r = agent("PATCH", f"/notes/{NID}", json={"pinned": False, "expect_updated_at": nseen["updated_at"]})
check(r.status_code == 409 and A.get(B + f"/api/notes/{NID}").json()["pinned"] is True, f"#3028: a stale pin change = 409 {r.status_code}")
r = agent("PATCH", f"/notes/{NID}", json={"tags": ["late"], "expect_updated_at": nseen["updated_at"]})
check(r.status_code == 409, f"#3028: a stale tags change = 409 {r.status_code}")

# ================================================================== web batch patch + reorder with _prev
T1 = A.post(B + "/api/tasks", json={"title": "Pack lights", "list_id": L, "due": "2027-03-01"}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Pack lenses", "list_id": L, "due": "2027-03-01"}).json()["id"]
Bo.patch(B + f"/api/tasks/{T1}", json={"due": "2027-03-05"})
r = A.post(B + "/api/tasks/batch", json={"ids": [T1, T2], "action": "patch", "data": {"due": "2027-03-10",
                                                                                      "prev": {str(T1): {"due": "2027-03-01"}, str(T2): {"due": "2027-03-01"}}}})
j = r.json()
check(r.ok and [(c["id"], c["field"]) for c in j.get("conflicts") or []] == [(T1, "due")], f"#3028: batch patch reports the changed task {j}")
check(A.get(B + f"/api/tasks/{T1}").json()["due"] == "2027-03-05" and A.get(B + f"/api/tasks/{T2}").json()["due"] == "2027-03-10",
      "#3028: batch patch: the changed task keeps its date, the other moves")
r = A.post(B + "/api/tasks/batch", json={"ids": [T1], "action": "patch", "data": {"due": "2027-03-11"}})
check(r.ok and A.get(B + f"/api/tasks/{T1}").json()["due"] == "2027-03-11", "#3028: batch patch without prev: as before")
Bo.patch(B + f"/api/tasks/{T2}", json={"priority": 3})
r = A.post(B + "/api/tasks/reorder", json={"items": [{"id": T2, "sort": 5, "priority": 5, "_prev": {"priority": 0}}]})
j = r.json()
t2 = A.get(B + f"/api/tasks/{T2}").json()
check(r.ok and [c["field"] for c in j.get("conflicts") or []] == ["priority"] and t2["priority"] == 3 and t2["sort"] == 5,
      f"#3028: reorder keeps a priority changed elsewhere, the position moves {j} {t2.get('priority')} {t2.get('sort')}")
r = A.post(B + "/api/tasks/reorder", json={"items": [{"id": T2, "sort": 6, "priority": 5, "_prev": {"priority": 3}}]})
check(r.ok and not r.json().get("conflicts") and A.get(B + f"/api/tasks/{T2}").json()["priority"] == 5, "#3028: reorder with the current _prev writes")

# ================================================================== freelancer: tasks + office draft positions
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, Fr = freelancer(B, A)
O = "/api/office"
Fr.get(B + O + "/settings")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "tasks:write", "office"]})
check(r.status_code == 201, "setup: the freelancer's own agent " + r.text[:200])
FAG, FH = r.json().get("id"), {**H, "Authorization": "Bearer " + r.json().get("token", "x")}
FL = Fr.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FAG, "role": "edit"})
r1 = requests.post(V + "/tasks", headers=FH, json={"title": "Invoice paper", "list_id": FL, "client_ref": "f-1", "locked": False})
r2 = requests.post(V + "/tasks", headers=FH, json={"title": "Invoice paper", "list_id": FL, "client_ref": "f-1", "locked": False})
check(r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"], f"#3028: freelancer: client_ref {r1.status_code} {r2.status_code}")
FT = r1.json().get("id")
fseen = requests.get(V + f"/tasks/{FT}", headers=FH).json()
time.sleep(1.1)
check(Fr.patch(B + f"/api/tasks/{FT}", json={"content": "Frida's own words"}).ok, "setup: the freelancer changes the task")
r = requests.patch(V + f"/tasks/{FT}", headers=FH, json={"notes": "Agent", "expect_updated_at": fseen["updated_at"]})
check(r.status_code == 409, f"#3028: freelancer: a stale agent write = 409 {r.status_code}")

check(Fr.patch(B + f"{O}/agents/{FAG}", json={"office_drafts": True}).ok, "setup: the freelancer switches her agent on")
check(Fr.put(B + O + "/settings", json={"agents_read": 1}).ok, "setup: the privacy switch of the personal office")
SV = Fr.post(B + O + "/services", json={"name_de": "Kamera", "name_en": "Camera", "daily_rate": 500}).json()["id"]
CLP = Fr.post(B + "/api/clients", json={"name": "Beispiel GmbH"}).json()["id"]
r = requests.post(V + "/office/offers", headers=FH, json={"client_id": CLP, "title": "Portrait", "items": [
    {"service_id": SV, "qty": 2}, {"text": "Travel", "qty": 1, "unit": "flat", "price": 120}]})
check(r.status_code == 201, "setup: the agent's draft " + r.text[:200])
DID = r.json()["doc"]["id"]
u0 = r.json()["doc"]["updated_at"]
doc = Fr.get(B + f"{O}/docs/{DID}").json()
its = doc.get("doc", doc)["items"]
its[0].update(rate=550, cost=300)  # the person's own price and the purchase price (agents never see / set it)
time.sleep(1.1)
r = Fr.put(B + f"{O}/docs/{DID}/items", json={"items": its})
check(r.ok, "setup: the person sets price and purchase " + r.text[:200])
P1, P2 = [i["id"] for i in r.json()["items"]]  # a person's save stores the positions anew (new ids)
r = requests.patch(V + f"/office/offers/{DID}", headers=FH, json={"title": "Portrait 2", "expect_updated_at": u0})
check(r.status_code == 409 and (r.json().get("current") or {}).get("id") == DID, f"#3028: a stale draft change = 409 with the draft {r.status_code} {r.text[:200]}")
u1 = requests.get(V + f"/office/docs/{DID}", headers=FH).json()["updated_at"]
r = requests.patch(V + f"/office/offers/{DID}", headers=FH, json={"expect_updated_at": u1, "items": [
    {"id": P1, "service_id": SV, "qty": 3}, {"id": P2, "text": "Travel", "qty": 1, "unit": "flat"}]})
check(r.ok, f"#3028: the agent changes positions by id {r.status_code} {r.text[:200]}")


def items_now():
    d = Fr.get(B + f"{O}/docs/{DID}").json()
    return d.get("doc", d)["items"]


x = items_now()
check(len(x) == 2 and float(x[0]["qty"]) == 3 and float(x[0]["rate"]) == 550 and float(x[0].get("cost") or 0) == 300,
      f"#3028: purchase price and the person's price stay {[(i.get('qty'), i.get('rate'), i.get('cost')) for i in x]}")
check(float(x[1]["rate"]) == 120, f"#3028: a free position keeps its price when the agent sends none {x[1].get('rate')}")
r = requests.patch(V + f"/office/offers/{DID}", headers=FH, json={"items": [{"service_id": SV, "qty": 4}]})
x = items_now()
check(r.ok and len(x) == 1 and float(x[0].get("cost") or 0) == 300 and float(x[0]["rate"]) == 550,
      f"#3028: without id the same service keeps purchase and price {[(i.get('qty'), i.get('rate'), i.get('cost')) for i in x]}")
Fr.put(B + f"{O}/docs/{DID}/items", json={"items": x})  # saved again by the person: the agent's ids are gone
r = requests.patch(V + f"/office/offers/{DID}", headers=FH, json={"items": [{"id": P1, "service_id": SV, "qty": 5}]})
x = items_now()
check(r.ok and float(x[0]["qty"]) == 5 and float(x[0].get("cost") or 0) == 300, f"#3028: an id gone since = found by its service {r.status_code} {x}")
r = requests.patch(V + f"/office/offers/{DID}", headers=FH, json={"items": [{"id": "x", "service_id": SV, "qty": 1}]})
check(r.status_code == 400, f"#3028: a position id must be a number {r.status_code}")

print(f"p2270_d_agent_conflict: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
