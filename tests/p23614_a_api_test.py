#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.361.4 (#2928 #2935): personal agents per workspace, the owner's log and limits (freelancer-matrix: agents)
 - #2928: the server switch user_agents off (the default): without organisations nobody creates a personal agent (403);
   with organisations the private area is the person's own (a person without an organisation creates one, no admin step
   before), an organisation's admins decide for its members (orgs.member_agents, PATCH /api/orgs/<id>, members 403);
   its admins themselves always may; "auto" falls back to the private area; moving into an organisation that does not
   allow it is 400
 - #2928: the owner reads the log of their agent (GET /api/my/agents/<id>/audit, CSV too; others 404), sets its usage
   limits (PATCH /api/my/agents/<id> {limits}) and hears of a reached limit (News "usage")
 - #2935: a personal agent leaves an organisation for the private area only when none of its projects still holds it
usage: p23614_a_api_test.py <datadir>      (KMT_NOSTART=1 / P23614A_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer, login
from kt import B, check, dbx, done, fresh, setup, until

V = B + "/api/v1"
fresh(prefix="P23614A")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]


def agents_of(s):
    return s.get(B + "/api/my/agents").json()


def token(s, aid):
    return {"Authorization": "Bearer " + s.post(B + f"/api/my/agents/{aid}/token").json()["token"]}


# ================================================================== #2928 a server without organisations: the server switch alone
NID, Nora = freelancer(B, A, "nora")
j = agents_of(Nora)
check(j["allowed"] is False and j["server"] is False, f"#2928: no organisations, switch off -> not allowed {j.get('allowed')} {j.get('server')}")
check(Nora.post(B + "/api/my/agents", json={"username": "norabot"}).status_code == 403, "#2928: ... and creating is refused (403)")

# ================================================================== #2928 with an organisation: the private area is the person's own
r = A.post(B + "/api/admin/orgs", json={"name": "Nordwind", "admin_id": ALICE})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com", "orgs": [ORG]})
assert r.ok, r.text
Bo = login(B, "bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, F = freelancer(B, A)  # no admin step before (the old suites switched user_agents on first)
j = agents_of(F)
check(j["allowed"] is True and j["server"] is False, f"#2928: freelancer: allowed in her private area, server switch off {j.get('allowed')} {j.get('server')}")
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot"})
check(r.status_code == 201 and r.json().get("org_id") is None, f"#2928: the freelancer creates her own agent {r.status_code} {r.text[:200]}")
FA = r.json().get("id")

# ---- the members of an organisation: its admins decide
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "org_id": ORG})
check(r.status_code == 400 and dbx("SELECT COUNT(*) FROM users WHERE username='bobbot'") == [(0,)], f"#2928: member: not into the organisation while it does not allow it {r.status_code} {r.text[:160]}")
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot"})
check(r.status_code == 201 and r.json().get("org_id") is None, f"#2928: member: 'auto' -> his private area {r.status_code} {r.text[:160]}")
BA = r.json().get("id")
r = Bo.patch(B + f"/api/my/agents/{BA}", json={"org_id": ORG})
check(r.status_code == 400 and "admins" in r.text, f"#2928: member: moving it into the organisation is refused {r.status_code} {r.text[:160]}")
r = A.post(B + "/api/my/agents", json={"username": "alicebot", "org_id": ORG})
check(r.status_code == 201 and r.json().get("org_id") == ORG, f"#2928: an admin of the organisation always may {r.status_code} {r.text[:160]}")
o = [x for x in Bo.get(B + "/api/orgs").json()["orgs"] if x["id"] == ORG][0]
check(o.get("member_agents") is False, f"#2928: GET /api/orgs: member_agents off by default {o.get('member_agents')}")
check(Bo.patch(B + f"/api/orgs/{ORG}", json={"member_agents": True}).status_code in (403, 404), "#2928: a member cannot switch it")
check(A.patch(B + f"/api/orgs/{ORG}", json={"member_agents": "yes"}).status_code == 400, "#2928: only true / false")
r = A.patch(B + f"/api/orgs/{ORG}", json={"member_agents": True})
check(r.ok and dbx("SELECT member_agents FROM orgs WHERE id=?", (ORG,)) == [(1,)], f"#2928: its admin allows it {r.status_code} {r.text[:160]}")
r = Bo.patch(B + f"/api/my/agents/{BA}", json={"org_id": ORG})
check(r.ok and r.json().get("org_id") == ORG, f"#2928: now the member moves his agent into the organisation {r.status_code} {r.text[:160]}")

# ================================================================== #2935 out of the organisation only without its projects
OL = Bo.post(B + "/api/lists", json={"name": "Nordwind board", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{OL}/members", json={"user_id": BA, "role": "edit"}).ok, "#2935: setup: bob shares an organisation project with his agent")
r = Bo.patch(B + f"/api/my/agents/{BA}", json={"org_id": None})
check(r.status_code == 400 and dbx("SELECT org_id FROM agents WHERE user_id=?", (BA,)) == [(ORG,)], f"#2935: private while still in an organisation project: refused, nothing changes {r.status_code} {r.text[:160]}")
Bo.delete(B + f"/api/lists/{OL}/members/{BA}")
r = Bo.patch(B + f"/api/my/agents/{BA}", json={"org_id": None})
check(r.ok and r.json().get("org_id") is None, f"#2935: out of the project -> private works {r.status_code} {r.text[:160]}")

# ================================================================== #2928 the owner's log and limits (freelancer-matrix: agents)
H = token(F, FA)
check(requests.get(V + "/lists", headers=H).ok, "#2928: setup: the agent calls the API")
j = until(lambda: (lambda x: x if x.get("data") else None)(F.get(B + f"/api/my/agents/{FA}/audit").json()), 20) or {}
check(j.get("data") and all(x["agent_id"] == FA for x in j["data"]) and any(x["route"].startswith("/api/v1/lists") for x in j["data"]),
      f"#2928: the owner reads the log of her agent {str(j)[:200]}")
r = F.get(B + f"/api/my/agents/{FA}/audit?format=csv")
check(r.ok and r.headers.get("Content-Type", "").startswith("text/csv") and "/api/v1/lists" in r.text, f"#2928: ... as CSV {r.status_code}")
check(Bo.get(B + f"/api/my/agents/{FA}/audit").status_code == 404, "#2928: somebody else: 404")
check(requests.get(B + f"/api/my/agents/{FA}/audit", headers=H).status_code in (401, 403, 404), "#2928: not the agent itself")
check(F.patch(B + f"/api/my/agents/{FA}", json={"limits": {"period": "week"}}).status_code == 400, "#2928: invalid limits: 400")
r = F.patch(B + f"/api/my/agents/{FA}", json={"limits": {"period": "day", "metric": "tokens", "hard": 100}})
check(r.ok and (r.json().get("limits") or {}).get("hard") == 100, f"#2928: the owner sets a hard limit {r.status_code} {r.text[:200]}")
r = requests.post(V + "/agent/usage", headers=H, json={"model": "test-model", "input_tokens": 90, "output_tokens": 30})
check(r.ok, f"#2928: setup: the agent reports usage over the limit {r.status_code} {r.text[:160]}")
news = until(lambda: [x for x in F.get(B + "/api/news").json()["items"] if x["kind"] == "usage" and (x.get("data") or {}).get("agent_id") == FA], 20)
check(news and news[0]["data"]["level"] == "hard", f"#2928: the owner hears that the limit is reached {news[:1]}")
r = F.patch(B + f"/api/my/agents/{FA}", json={"limits": None})
check(r.ok and not r.json().get("limits"), f"#2928: and removes it again {r.status_code} {r.text[:160]}")
check(Bo.patch(B + f"/api/my/agents/{FA}", json={"limits": None}).status_code == 404, "#2928: nobody else sets them")
# review 2.361.4: the owner's log names only her agent (never the other agents of the server)
j = F.get(B + f"/api/my/agents/{FA}/audit").json()
check([x["id"] for x in j.get("agents", [])] == [FA], f"#2928: the owner's log lists only her own agent {j.get('agents')}")
# review 2.361.4: the server admin's limits for personal agents stay a ceiling for the owner
A.put(B + "/api/admin/agent-policy", json={"limits": {"period": "month", "metric": "tokens", "hard": 5000}})
check(F.patch(B + f"/api/my/agents/{FA}", json={"limits": None}).status_code == 400, "#2928: with a server limit the owner cannot remove hers")
check(F.patch(B + f"/api/my/agents/{FA}", json={"limits": {"period": "month", "metric": "tokens", "hard": 9000}}).status_code == 400, "#2928: ... nor go above it")
r = F.patch(B + f"/api/my/agents/{FA}", json={"limits": {"period": "month", "metric": "tokens", "hard": 4000}})
check(r.ok and (r.json().get("limits") or {}).get("hard") == 4000, f"#2928: ... but set a lower one {r.status_code} {r.text[:160]}")

sys.exit(done("p23614_a_api"))
