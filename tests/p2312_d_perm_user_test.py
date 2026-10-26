#!/usr/bin/env python3
"""2.312.0 D (#3266): who answers a team agent's permission questions is chosen in its settings (runtime.perm_user).
freelancer-matrix: agents
 - GET /api/agents/{id}/perm-users: a team agent offers the active people it reaches in a shared project (no agent, no
   one outside its projects); a personal agent offers its owner only; nobody else gets an answer (404: a member, another
   person's personal agent, the agent itself)
 - saving (PATCH /api/admin/agents/{id} runtime.perm_user) takes only such a person (400 otherwise, also when creating an
   agent); GET /api/v1/agent hands it to the host as perm_user_id while the person still reaches the agent, else null;
   runtime_changed carries it
 - the owner of a personal agent may choose only themself (PATCH /api/my/agents/{id}); a personal agent's host gets null
 - a person without an organisation: the own agent the same way
 - static: mcp/agent_run.py takes perm_user_id before KALMIDO_PERM_USER (both launchers run it); without it the env value
   stays (older servers, old installations)
usage: p2312_d_perm_user_test.py <datadir>      (KMT_NOSTART=1 / P2312D_NOSTART=1: a running server)"""
import importlib.util
import os
import sys
import tempfile
import types

from freelancer_fixture import freelancer
from kt import B, check, done, fresh, sess, setup

N = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.join(N, "..", "mcp")

# ---------------------------------------------------------------- static: the event runner (no server needed)
RUN_ENV = {k: os.environ.get(k) for k in ("KALMIDO_URL", "KALMIDO_TOKEN")}
os.environ.update(KALMIDO_URL="http://127.0.0.1:9", KALMIDO_TOKEN="abk_" + "x" * 30)  # nothing is called: no server needed
spec = importlib.util.spec_from_file_location("agent_run", os.path.join(MCP, "agent_run.py"))
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)
os.environ["KALMIDO_PERM_USER"] = "7"
os.environ.pop("KALMIDO_OWNER_IDS", None)
rn = ar.Runner(["claude"], os.path.join(tempfile.mkdtemp(), "state"))
rn.agent = {"owner_id": None, "perm_user_id": 5}
check(rn.perm_uid() == 5 and rn.perm_operators() == {5}, f"runner: the person chosen in Kalmido comes first {rn.perm_uid()} {rn.perm_operators()}")
rn.agent = {"owner_id": None, "perm_user_id": None}
check(rn.perm_uid() == 7 and rn.perm_operators() == {7}, "runner: no choice -> KALMIDO_PERM_USER as before")
rn.agent = {"owner_id": None}
check(rn.perm_uid() == 7, "runner: an older server without the field -> KALMIDO_PERM_USER")
os.environ.pop("KALMIDO_PERM_USER")
rn.agent = {"owner_id": 3, "perm_user_id": None}
check(rn.perm_uid() == 3 and rn.perm_operators() == {3}, "runner: a personal agent asks its owner")
for k, v in RUN_ENV.items():
    os.environ.pop(k, None) if v is None else os.environ.update({k: v})


def bear(tok):
    return {"Authorization": "Bearer " + tok}


# ---------------------------------------------------------------- server
fresh(prefix="P2312D")
A = setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")

r = A.post(B + "/api/admin/agents", json={"username": "teamhelper", "display_name": "Team Helper"})
assert r.ok, r.text
TEAM, TOK = r.json()["id"], r.json()["token"]
r = A.post(B + "/api/admin/agents", json={"username": "otherhelper", "display_name": "Other Helper"})
assert r.ok, r.text
OTHER = r.json()["id"]
r = A.post(B + "/api/lists", json={"name": "Shared work"})
assert r.ok, r.text
L = r.json()["id"]
for uid, role in ((TEAM, "edit"), (ids["bob"], "admin")):  # one agent per project
    r = A.put(B + f"/api/lists/{L}/members", json={"user_id": uid, "role": role})
    check(r.ok, f"setup: member {uid} {r.text[:160]}")

r = A.get(B + f"/api/agents/{TEAM}/perm-users")
j = r.json() if r.ok else {}
people = {p["id"] for p in j.get("people", [])}
check(r.ok and j.get("team") is True and j.get("current") is None, f"team agent: the choice for the admin {r.text[:200]}")
check(people == {ALICE, ids["bob"]}, f"only the people it reaches, no agent, no one outside its projects: {people}")
check(Bo.get(B + f"/api/agents/{TEAM}/perm-users").status_code == 404, "a member who is no admin: 404")
check(Ca.get(B + f"/api/agents/{TEAM}/perm-users").status_code == 404, "someone outside: 404")
check(sess().get(B + f"/api/agents/{TEAM}/perm-users", headers=bear(TOK)).status_code in (401, 403, 404), "the agent itself: refused")

ag = sess()
ag.headers.update(bear(TOK))
j = ag.get(B + "/api/v1/agent").json()
check(j.get("perm_user_id") is None and j["runtime"].get("perm_user") is None, f"nothing chosen: the host keeps its env value {j.get('perm_user_id')}")

for bad, what in ((ids["carol"], "someone it does not reach"), (OTHER, "another agent"), (TEAM, "the agent itself"),
                  ("x", "not a number"), (True, "a boolean"), (-1, "a negative id")):
    r = A.patch(B + f"/api/admin/agents/{TEAM}", json={"runtime": {"perm_user": bad}})
    check(r.status_code == 400, f"refused: {what} ({r.status_code})")
r = A.post(B + "/api/admin/agents", json={"username": "newhelper", "runtime": {"perm_user": ALICE}})
check(r.status_code == 400, f"a new agent reaches nobody yet: no choice when creating it ({r.status_code})")

cur = ag.get(B + "/api/v1/agent").json()["events_cursor"]
r = A.patch(B + f"/api/admin/agents/{TEAM}", json={"runtime": {"perm_user": ids["bob"]}})
check(r.ok and r.json()["runtime"].get("perm_user") == ids["bob"], f"the admin chooses bob {r.text[:200]}")
j = ag.get(B + "/api/v1/agent").json()
check(j.get("perm_user_id") == ids["bob"] and j["runtime"].get("perm_user") == ids["bob"], f"the host gets bob {j.get('perm_user_id')}")
evs = ag.get(B + "/api/v1/agent/events", params={"since": cur}).json().get("data", [])
rc = [e for e in evs if e.get("event") == "runtime_changed"]
check(rc and rc[-1]["data"]["runtime"].get("perm_user") == ids["bob"], f"runtime_changed carries the choice {[e.get('event') for e in evs]}")
check(A.get(B + f"/api/agents/{TEAM}/perm-users").json().get("current") == ids["bob"], "the choice shows as current")
r = A.patch(B + f"/api/admin/agents/{TEAM}", json={"note": "unchanged choice", "runtime": {"perm_user": ids["bob"], "model": ""}})
check(r.ok, f"saving the dialog again with the same choice {r.status_code}")

# bob leaves the project: the choice stays stored, but the host gets null (KALMIDO_PERM_USER again)
check(A.delete(B + f"/api/lists/{L}/members/{ids['bob']}").ok, "setup: bob leaves the project")
j = ag.get(B + "/api/v1/agent").json()
check(j.get("perm_user_id") is None, f"no longer reached: null for the host {j.get('perm_user_id')}")
check(ids["bob"] not in {p["id"] for p in A.get(B + f"/api/agents/{TEAM}/perm-users").json()["people"]}, "and no longer offered")
r = A.patch(B + f"/api/admin/agents/{TEAM}", json={"runtime": {"perm_user": None}})
check(r.ok and r.json()["runtime"].get("perm_user") is None, "back to: as set up on its computer")

# a personal agent: only its owner
r = Bo.post(B + "/api/my/agents", json={"username": "bobs-helper", "display_name": "Bob Helper"})
assert r.ok, r.text
OWN, OTOK = r.json()["id"], r.json()["token"]
r = Bo.get(B + f"/api/agents/{OWN}/perm-users")
j = r.json() if r.ok else {}
check(r.ok and j.get("team") is False and [p["id"] for p in j.get("people", [])] == [ids["bob"]], f"personal agent: its owner only {r.text[:200]}")
check(A.get(B + f"/api/agents/{OWN}/perm-users").status_code == 404, "another person's personal agent: 404 for an admin too")
check(Bo.patch(B + f"/api/my/agents/{OWN}", json={"runtime": {"perm_user": ALICE}}).status_code == 400, "the owner cannot hand it to someone else")
check(Bo.patch(B + f"/api/my/agents/{OWN}", json={"runtime": {"perm_user": ids["bob"]}}).ok, "the owner may name themself")
check(sess().get(B + "/api/v1/agent", headers=bear(OTOK)).json().get("perm_user_id") is None, "a personal agent's host gets null (its owner answers)")

# freelancer-matrix: agents -- a person without an organisation
FID, F = freelancer(B, A)
r = F.post(B + "/api/my/agents", json={"username": "frida-helper", "display_name": "Frida Helper"})
check(r.ok, f"without an organisation: own agent {r.text[:200]}")
if r.ok:
    FA = r.json()["id"]
    r = F.get(B + f"/api/agents/{FA}/perm-users")
    check(r.ok and [p["id"] for p in r.json().get("people", [])] == [FID], f"without an organisation: they answer themself {r.text[:200]}")
    check(F.patch(B + f"/api/my/agents/{FA}", json={"runtime": {"perm_user": FID}}).ok, "without an organisation: may name themself")
    check(F.patch(B + f"/api/my/agents/{FA}", json={"runtime": {"perm_user": ALICE}}).status_code == 400, "without an organisation: nobody else")
    check(F.get(B + f"/api/agents/{TEAM}/perm-users").status_code == 404, "without an organisation: another team agent stays closed")
sys.exit(done("p2312_d_perm_user"))
