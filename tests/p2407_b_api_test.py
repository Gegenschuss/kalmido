#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.407.0 B (#3493): the agent chat's usage ring -- costs of API-key agents and the switch (freelancer-matrix: agents)
 - GET /api/agents: "cost" of an agent that reports costs (no plan quota): {period, pct} against its cost limit (the hard
   one, else the soft one; month or day); the amounts {today, month, limit} only for who may read its usage numbers (the
   owner of a personal agent, instance admins: #2928) -- someone who only shares a list with it gets the share, no amounts
 - without a cost limit: no share (pct null), the owner / admin still gets today / this month; a tokens limit is no cost
   limit; no cost reported and no cost limit: cost null; a plan quota and costs: both in the answer
 - the personal setting agent_quota_show (default on, '0' = off) is saved per person (PATCH /api/settings)
 - a person without an organisation with her own agent (private area) gets the same
usage: p2407_b_api_test.py <datadir>      (KMT_NOSTART=1 / P2407B_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer, login
from kt import B, check, done, fresh, setup

V = B + "/api/v1"
fresh(prefix="P2407B")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = login(B, "bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
L = A.post(B + "/api/lists", json={"name": "Shared work"}).json()["id"]
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "admin"}).ok, "setup: bob shares the list (as its admin: agents are open to list admins)")


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": name, "display_name": name.title()})
    assert r.ok, r.text
    aid = r.json()["id"]
    check(A.put(B + f"/api/lists/{L}/members", json={"user_id": aid, "role": "edit", "bridge_ok": True}).ok, f"setup: {name} on the shared list")
    return aid, {"Authorization": "Bearer " + r.json()["token"]}


def cost_of(s, aid):
    a = [x for x in s.get(B + "/api/agents").json().get("agents", []) if x["id"] == aid]
    return a[0].get("cost", "missing") if a else "no agent"


def report(h, usd):
    r = requests.post(V + "/agent/usage", headers=h, json={"model": "test-model", "input_tokens": 10, "output_tokens": 5, "cost_usd": usd})
    assert r.ok, r.text


# ================================================================== a monthly cost limit
API, APIH = agent("apibot")
check(cost_of(A, API) is None, f"#3493: no cost reported, no cost limit: cost null {cost_of(A, API)}")
check(A.patch(B + f"/api/admin/agents/{API}", json={"limits": {"period": "month", "metric": "cost", "hard": 10}}).ok, "setup: a monthly cost limit of $10")
report(APIH, 2.5)
report(APIH, 0.5)
c = cost_of(A, API)
check(isinstance(c, dict) and c.get("period") == "month" and c.get("pct") == 30.0, f"#3493: the share of the monthly cost limit (30 %) {c}")
check(isinstance(c, dict) and c.get("today") == 3.0 and c.get("month") == 3.0 and c.get("limit") == 10.0, f"#3493: the admin reads the amounts {c}")
c = cost_of(Bo, API)
check(isinstance(c, dict) and c.get("pct") == 30.0 and not {"today", "month", "limit"} & set(c), f"#3493: someone sharing a list: only the share, no amounts {c}")

# the soft limit when there is no hard one; a daily limit counts today
check(A.patch(B + f"/api/admin/agents/{API}", json={"limits": {"period": "day", "metric": "cost", "soft": 4}}).ok, "setup: a daily soft cost limit of $4")
c = cost_of(A, API)
check(isinstance(c, dict) and c.get("period") == "day" and c.get("pct") == 75.0 and c.get("limit") == 4.0, f"#3493: the soft daily limit when there is no hard one (75 %) {c}")

# ================================================================== no cost limit / a tokens limit
check(A.patch(B + f"/api/admin/agents/{API}", json={"limits": {"period": "month", "metric": "tokens", "hard": 1000}}).ok, "setup: a tokens limit only")
c = cost_of(A, API)
check(isinstance(c, dict) and c.get("pct") is None and c.get("limit") is None and c.get("month") == 3.0, f"#3493: a tokens limit is no cost limit: no share, the costs stay {c}")
check(A.patch(B + f"/api/admin/agents/{API}", json={"limits": None}).ok, "setup: no limits")
c = cost_of(A, API)
check(isinstance(c, dict) and c.get("pct") is None and c.get("today") == 3.0 and c.get("month") == 3.0, f"#3493: without a limit: no share, the admin reads today / this month {c}")
c = cost_of(Bo, API)
check(isinstance(c, dict) and c.get("pct") is None and not {"today", "month", "limit"} & set(c), f"#3493: ... and someone sharing a list nothing {c}")

# ================================================================== plan quota and costs
PLAN, PLANH = agent("planbot")
check(requests.put(V + "/agent/quota", headers=PLANH, json={"windows": [{"label": "Week", "percent": 41}]}).ok, "setup: a plan quota")
check(cost_of(A, PLAN) is None, "#3493: a plan agent without costs: cost null")
report(PLANH, 1.25)
a = [x for x in A.get(B + "/api/agents").json()["agents"] if x["id"] == PLAN][0]
check((a.get("quota") or {}).get("windows") and (a.get("cost") or {}).get("month") == 1.25, f"#3493: both reported: the quota and the costs {a.get('quota')} {a.get('cost')}")

# ================================================================== the personal switch
st = A.get(B + "/api/state").json()["settings"]
check(st.get("agent_quota_show") == "1", f"#3493: 'Show usage' is on by default {st.get('agent_quota_show')}")
check(A.patch(B + "/api/settings", json={"agent_quota_show": "0"}).ok, "#3493: switched off")
check(A.get(B + "/api/state").json()["settings"].get("agent_quota_show") == "0", "#3493: ... saved")
check(Bo.get(B + "/api/state").json()["settings"].get("agent_quota_show") == "1", "#3493: ... per person (bob's stays on)")
A.patch(B + "/api/settings", json={"agent_quota_show": "1"})

# ================================================================== a person without an organisation, her own agent
r = A.post(B + "/api/admin/orgs", json={"name": "Nordwind", "admin_id": A.get(B + "/api/state").json()["me"]["id"]})
assert r.status_code == 201, r.text  # with an organisation on the server the private area is the freelancer's own (#2928)
FID, F = freelancer(B, A)
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot"})
check(r.status_code == 201, f"setup: the freelancer creates her own agent {r.status_code} {r.text[:160]}")
FA = r.json()["id"]
FL = F.post(B + "/api/lists", json={"name": "Frida work"}).json()["id"]
check(F.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "setup: she shares a list with her agent")
FH = {"Authorization": "Bearer " + F.post(B + f"/api/my/agents/{FA}/token").json()["token"]}
check(F.patch(B + f"/api/my/agents/{FA}", json={"limits": {"period": "month", "metric": "cost", "hard": 20}}).ok, "setup: she sets a monthly cost limit")
report(FH, 5)
c = cost_of(F, FA)
check(isinstance(c, dict) and c.get("pct") == 25.0 and c.get("month") == 5.0 and c.get("limit") == 20.0, f"#3493 P4: the owner without an organisation: share and amounts {c}")
check(F.patch(B + "/api/settings", json={"agent_quota_show": "0"}).ok and F.get(B + "/api/state").json()["settings"].get("agent_quota_show") == "0",
      "#3493 P4: she switches the ring off")

sys.exit(done("p2407_b_api"))
