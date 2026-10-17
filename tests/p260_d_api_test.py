#!/usr/bin/env python3
"""2.60.0 API tests (part D): environments of a project (#1514).
 - environments (Staging, Live) are created / renamed / removed with write access to the list (view 403, a stranger 404, a name
   twice 409, a bad name 400); removing is a soft delete that "restore" takes back
 - a deployment by hand (milestone or version), the milestone's report and /api/state say where it runs since when; only the
   latest deployment of an environment can be taken back
 - the deploy webhook: a secret token per environment, shown once (owner / list admins only, an editor 403), a wrong token or
   another environment's token 403, the version finds the milestone by its title, a version without a milestone is kept,
   rotate kills the old address, off too
 - "complete tasks on arrival" (per environment, off by default): the milestone's open tasks are completed, or not
 - the token API: list_environments / set_deployment for an agent with access, a list it does not see 404; the agent hears
   `deployed` (and not for a list it has no access to)
tenant-matrix: list
usage: p260_d_api_test.py <datadir>"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
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


def local(u):
    """The address as shown (public URL) -> this test server."""
    return B + u[u.index("/api/hooks"):] if "/api/hooks" in u else u


def hook(url, **kw):
    """The deploy script: no session, no header. Waits out the per-environment pause (2 s) first."""
    time.sleep(2.2)
    return requests.post(url, **kw)


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
assert r.status_code == 201, r.text
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


def ag(m, p, **k):
    return requests.request(m, V + p, headers=AGH, timeout=60, **k)


P = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
OTHER = A.post(B + "/api/lists", json={"name": "Hidden app", "kind": "project"}).json()["id"]
check(A.patch(B + f"/api/lists/{P}", json={"ptype": "software"}).ok, "setup: P is a software project")
for u, role in (("bob", "edit"), ("carol", "view")):
    assert A.put(B + f"/api/lists/{P}/members", json={"user_id": uid[u], "role": role}).ok
assert A.put(B + f"/api/lists/{P}/members", json={"user_id": AG, "role": "edit"}).ok
M1 = A.post(B + f"/api/lists/{P}/milestones", json={"name": "Release 2.61.0", "day": "2026-11-01"}).json()["id"]
M2 = A.post(B + f"/api/lists/{P}/milestones", json={"name": "3.0.0", "day": "2026-12-01"}).json()["id"]
MO = A.post(B + f"/api/lists/{OTHER}/milestones", json={"name": "Elsewhere", "day": "2026-11-01"}).json()["id"]
T = [A.post(B + "/api/tasks", json={"title": f"Task {k}", "list_id": P, "milestone_id": M1}).json()["id"] for k in range(3)]
check(A.post(B + f"/api/tasks/{T[2]}/complete", json={}).ok, "setup: one task of the milestone is done")


def st(t):
    return A.get(B + f"/api/tasks/{t}").json()["status"]  # 0 open, 2 done


# ================================================================== rights and names
g = Ca.get(B + f"/api/lists/{P}/envs")
check(g.ok and g.json()["envs"] == [] and g.json()["manage"] is False, "a viewer reads the (empty) environment list, no manage right")
check(g.json()["suggest"] == ["Staging", "Live"], "a software project suggests Staging and Live (never created unasked)")
check(Ca.post(B + f"/api/lists/{P}/envs", json={"name": "Staging"}).status_code == 403, "a viewer cannot add an environment: 403")
check(Da.get(B + f"/api/lists/{P}/envs").status_code == 404, "a stranger cannot read the environments: 404")
check(Da.post(B + f"/api/lists/{P}/envs", json={"name": "Staging"}).status_code == 404, "a stranger cannot add one: 404")
check(Bo.post(B + f"/api/lists/{P}/envs", json={"name": " "}).status_code == 400, "an empty name: 400")
check(Bo.post(B + f"/api/lists/{P}/envs", json={"name": "x" * 41}).status_code == 400, "a name over 40 characters: 400")
r = Bo.post(B + f"/api/lists/{P}/envs", json={"name": "Staging"})
check(r.status_code == 201 and r.json()["name"] == "Staging" and r.json()["auto_close"] is False, "an editor adds Staging (auto close off) " + r.text[:120])
STG = r.json()["id"]
check(Bo.post(B + f"/api/lists/{P}/envs", json={"name": "staging"}).status_code == 409, "the same name twice (any case): 409")
r = Bo.post(B + f"/api/lists/{P}/envs", json={"name": "Live", "auto_close": True})
LIVE = r.json()["id"]
check(r.status_code == 201 and r.json()["auto_close"] is True, "Live with 'complete tasks on arrival'")
check(Bo.patch(B + f"/api/envs/{LIVE}", json={"name": "Production"}).ok and Bo.patch(B + f"/api/envs/{LIVE}", json={"name": "Live"}).ok, "rename and back")
check(Bo.patch(B + f"/api/envs/{LIVE}", json={"name": "Staging"}).status_code == 409, "rename onto another's name: 409")
check(Ca.patch(B + f"/api/envs/{STG}", json={"name": "X"}).status_code == 403, "a viewer cannot rename: 403")
check(Da.patch(B + f"/api/envs/{STG}", json={"name": "X"}).status_code == 404, "a stranger cannot rename: 404")
check(Da.delete(B + f"/api/envs/{STG}").status_code == 404 and Ca.delete(B + f"/api/envs/{STG}").status_code == 403, "delete: stranger 404, viewer 403")
check(Bo.patch(B + f"/api/envs/{STG}", json={"hook": "on"}).status_code == 403, "an editor cannot switch the webhook on (owner / list admins only): 403")
check(Ca.get(B + f"/api/lists/{P}/envs").json()["envs"][0].get("hook") is None, "a viewer never sees the hook flag")

# ================================================================== by hand
check(Da.post(B + f"/api/envs/{STG}/deploy", json={"milestone_id": M1}).status_code == 404, "a stranger cannot put a milestone: 404")
check(Ca.post(B + f"/api/envs/{STG}/deploy", json={"milestone_id": M1}).status_code == 403, "a viewer cannot: 403")
check(Bo.post(B + f"/api/envs/{STG}/deploy", json={"milestone_id": MO}).status_code == 404, "a milestone of another list: 404")
check(Bo.post(B + f"/api/envs/{STG}/deploy", json={}).status_code == 400, "neither milestone nor version: 400")
check(Bo.post(B + f"/api/envs/{STG}/deploy", json={"milestone_id": T[0]}).status_code == 404, "a plain task is no milestone: 404")
r = Bo.post(B + f"/api/envs/{STG}/deploy", json={"milestone_id": M1})
check(r.status_code == 201 and r.json()["version"] == "Release 2.61.0" and r.json()["closed"] == [], "put M1 on Staging: version = title, nothing closed (auto close off) " + r.text[:160])
D1 = r.json()["id"]
check(st(T[0]) == 0 and st(T[1]) == 0, "the milestone's open tasks stay open on Staging")
rep = Ca.get(B + f"/api/tasks/{M1}/milestone").json()
check([e["name"] for e in rep.get("envs", [])] == ["Staging"] and rep["envs"][0]["since"], "the milestone report says where it runs: Staging since ...")
ms = {m["id"]: m for m in A.get(B + "/api/state").json()["lists"][[x["id"] for x in A.get(B + "/api/state").json()["lists"]].index(P)].get("milestones", [])}
check(ms.get(M1, {}).get("envs", [{}])[0].get("name") == "Staging", "/api/state: the milestone carries envs (timeline, task rows)")
cur = Ca.get(B + f"/api/lists/{P}/envs").json()["envs"]
check(cur[0]["current"]["milestone_id"] == M1 and cur[1]["current"] is None, "Staging has its current deployment, Live none")
r = Bo.post(B + f"/api/envs/{STG}/deploy", json={"version": "v3.0.0"})
check(r.status_code == 201 and r.json()["milestone_id"] == M2, "a version 'v3.0.0' finds the milestone '3.0.0' (leading v ignored) " + r.text[:120])
D2 = r.json()["id"]
check(Ca.get(B + f"/api/tasks/{M1}/milestone").json()["envs"] == [], "M1 is not on Staging any more once M2 arrived")
check(Bo.delete(B + f"/api/envs/{STG}/deploys/{D1}").status_code == 409, "only the latest deployment can be taken back: 409")
check(Bo.delete(B + f"/api/envs/{STG}/deploys/{D2}").ok, "the latest one is taken back (Undo)")
check(Ca.get(B + f"/api/tasks/{M1}/milestone").json()["envs"][0]["name"] == "Staging", "... and M1 is on Staging again")

# ================================================================== the deploy webhook
r = A.patch(B + f"/api/envs/{STG}", json={"hook": "on"})
url = local(r.json().get("url", ""))
check(r.ok and f"/api/hooks/deploy/{STG}/" in url and "url" in r.json() and r.json()["hook"] is True, "the owner switches the webhook on: the address comes once " + r.text[:120])
check("url" not in A.get(B + f"/api/lists/{P}/envs").json()["envs"][0] and A.get(B + f"/api/lists/{P}/envs").json()["envs"][0]["hook"] is True, "a later read has the flag, never the address")
check(requests.post(B + f"/api/hooks/deploy/{STG}/wrongtoken", json={"version": "3.0.0"}).status_code == 403, "a wrong token: 403")
check(requests.post(B + f"/api/hooks/deploy/{LIVE}/" + url.rsplit("/", 1)[1], json={"version": "3.0.0"}).status_code == 403, "Staging's token on Live (no webhook there): 403")
r = hook(url, json={"version": "3.0.0"})
check(r.status_code == 201 and r.json()["milestone_id"] == M2, "the right token puts the version on its milestone " + r.text[:120])
check(Ca.get(B + f"/api/tasks/{M2}/milestone").json()["envs"][0]["name"] == "Staging", "... the milestone shows Staging since now")
r = hook(url, json={"version": "9.9.9-rc1"})
check(r.status_code == 201 and r.json()["milestone_id"] is None, "a version without a milestone is kept as text")
check(A.get(B + f"/api/lists/{P}/envs").json()["envs"][0]["current"]["version"] == "9.9.9-rc1" and A.get(B + f"/api/lists/{P}/envs").json()["envs"][0]["current"]["source"] == "hook", "... as the current deployment, source hook")
check(hook(url, json={}).status_code == 400 and hook(url, json={"version": 5}).status_code == 400, "no version / a number: 400")
check(hook(url, data="not json").status_code == 400, "a body that is no JSON: 400")
r1 = requests.post(url, json={"version": "3.0.0"})
check(r1.status_code == 429, "two calls within 2 s: 429 (a script, not a flood)")
r = A.patch(B + f"/api/envs/{STG}", json={"hook": "rotate"})
new = local(r.json().get("url", ""))
check(new and new != url, "rotate gives a new address")
check(hook(url, json={"version": "3.0.0"}).status_code == 403, "the old address is dead: 403")
check(hook(new, json={"version": "3.0.0"}).status_code == 201, "the new one works")
check(A.patch(B + f"/api/envs/{STG}", json={"hook": "off"}).ok and hook(new, json={"version": "3.0.0"}).status_code == 403, "off: the address is dead: 403")

# ================================================================== complete tasks on arrival
before = [st(t) for t in T]
r = A.patch(B + f"/api/envs/{LIVE}", json={"hook": "on"})
lurl = local(r.json()["url"])
r = hook(lurl, json={"version": "Release 2.61.0"})
check(r.status_code == 201 and r.json().get("closed") == 2, "Live (auto close on): the hook reports the closed tasks " + r.text[:120])
after = [st(t) for t in T]
check(before == [0, 0, 2] and after == [2, 2, 2], f"the milestone's two open tasks are completed {before} -> {after}")
check(A.patch(B + f"/api/envs/{LIVE}", json={"auto_close": False}).ok, "auto close off again")
T3 = A.post(B + "/api/tasks", json={"title": "Late task", "list_id": P, "milestone_id": M1}).json()["id"]
r = hook(lurl, json={"version": "Release 2.61.0"})
check(r.status_code == 201 and st(T3) == 0, "with auto close off a later task stays open")
# 2.60.0 (leader, #1514 + #1512): with "done only after approval" a task still waiting for its reviewer stays open on arrival
check(A.put(B + f"/api/lists/{P}/review", json={"on": 1, "gate": 1}).ok, "the review step with its gate on")
T4 = A.post(B + "/api/tasks", json={"title": "Reviewed task", "list_id": P, "milestone_id": M1}).json()["id"]
check(A.post(B + f"/api/tasks/{T4}/review", json={"action": "reviewer", "reviewer_id": uid["carol"]}).ok, "carol reviews the new task")
check(A.patch(B + f"/api/envs/{LIVE}", json={"auto_close": True}).ok, "auto close on")
r = hook(lurl, json={"version": "Release 2.61.0"})
check(r.status_code == 201 and st(T3) == 2 and st(T4) == 0, f"auto close completes the free task, the one waiting for review stays open {st(T3)} {st(T4)} " + r.text[:120])
check(A.patch(B + f"/api/envs/{LIVE}", json={"auto_close": False}).ok and A.put(B + f"/api/lists/{P}/review", json={"on": 0}).ok, "both off again")

# ================================================================== soft delete and restore
check(A.delete(B + f"/api/envs/{LIVE}").ok, "remove Live")
check([e["name"] for e in A.get(B + f"/api/lists/{P}/envs").json()["envs"]] == ["Staging"], "... it is gone from the list")
check(hook(lurl, json={"version": "3.0.0"}).status_code == 403, "... its webhook is dead")
check(A.post(B + f"/api/envs/{LIVE}/restore").ok and [e["name"] for e in A.get(B + f"/api/lists/{P}/envs").json()["envs"]] == ["Staging", "Live"], "restore (Undo) brings it back with its history")
check(A.get(B + f"/api/lists/{P}/envs").json()["envs"][1]["current"]["version"] == "Release 2.61.0", "... with its latest deployment")
check(A.post(B + f"/api/envs/{LIVE}/restore").status_code == 404, "restoring what is not removed: 404")

# ================================================================== the token API and the agent
r = ag("GET", f"/lists/{P}/environments")
check(r.ok and [e["name"] for e in r.json()["data"]] == ["Staging", "Live"], "the agent lists the environments " + r.text[:120])
check(ag("GET", f"/lists/{OTHER}/environments").status_code == 404, "... of a list it does not see: 404")
check(ag("POST", f"/lists/{OTHER}/deployments", json={"environment": "Live", "version": "1"}).status_code == 404, "set_deployment in a list it does not see: 404")
seq = max([e["seq"] for e in ag("GET", "/agent/events", params={"since": 0}).json().get("data", [])] or [0])
r = ag("POST", f"/lists/{P}/deployments", json={"environment": "live", "milestone_id": M2})
check(r.status_code == 201 and r.json()["env"] == "Live" and r.json()["milestone_id"] == M2 and r.json()["source"] == "api", "the agent records M2 on 'live' (by name) " + r.text[:140])
check(ag("POST", f"/lists/{P}/deployments", json={"environment": "Nowhere", "version": "1"}).status_code == 404, "an unknown environment: 404")
check(ag("POST", f"/lists/{P}/deployments", json={"environment": "Live", "version": "1", "surprise": 1}).status_code == 400, "an unknown field: 400")
check(ag("POST", f"/lists/{P}/envs", json={"name": "Nope"}).status_code in (403, 404, 405), "the agent cannot create environments through the API")
check(ag("PATCH", f"/envs/{LIVE}", json={"hook": "on"}).status_code in (403, 404, 405), "... and never the webhook")
Bo.post(B + f"/api/envs/{STG}/deploy", json={"version": "3.0.0"})
evs = [e for e in ag("GET", "/agent/events", params={"since": seq}).json().get("data", []) if e["event"] == "deployed"]
check(len(evs) == 1, f"the agent hears `deployed` for a person's deployment, not for its own call: {len(evs)}")
d = evs[-1]["data"] if evs else {}
check(d.get("list_id") == P and d.get("environment", {}).get("name") == "Staging" and d.get("version") == "3.0.0" and d.get("milestone", {}).get("id") == M2,
      "the event names list, environment, version and milestone " + str(d)[:200])
A.post(B + f"/api/lists/{OTHER}/envs", json={"name": "Live"})
oid = A.get(B + f"/api/lists/{OTHER}/envs").json()["envs"][0]["id"]
seq = max([e["seq"] for e in ag("GET", "/agent/events", params={"since": 0}).json().get("data", [])] or [0])
A.post(B + f"/api/envs/{oid}/deploy", json={"version": "1.0"})
check(not [e for e in ag("GET", "/agent/events", params={"since": seq}).json().get("data", []) if e["event"] == "deployed"], "no `deployed` for a list the agent has no access to")

# ================================================================== My data holds the environments, never a token
ex = A.get(B + "/api/export.json").json()
check(len(ex.get("list_envs", [])) >= 2 and "token_hash" not in str(ex.get("list_envs")), "the export has the environments without the token hash")

print(f"p260_d_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
