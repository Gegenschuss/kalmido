#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.638.0 B (#4714): a server agent gets a proposed day limit with its first key (agents/srvagent.py srv_put day_limit).
Invented names and keys only (no provider call: storing a key does not ask the provider).
freelancer-matrix: agents (the person without an organisation sets up her own server agent)
 - GET /api/agents/server/defaults and GET .../server: day_limit_default 2000000; limits null while the agent has none
 - PUT with the first key + day_limit: the agent's hard day limit in tokens (what the run worker pauses at); a bad day_limit 400
 - the first key without day_limit (the field emptied): no limit; a replaced key + day_limit: what it had stays
 - an agent with limits (set by its owner before): they stay as they were
 - a team agent of the instance admin: the same with the first key
usage: p2638_b_srvlimit_test.py <datadir>      (KMT_NOSTART=1 / P2638BS_NOSTART=1: a running server)"""
import json
import sys

from kt import B, check, dbx, done, docker_logs_on_first_fail, fresh
from freelancer_fixture import freelancer

SKEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (the provider key is sealed with it)
KEY1, KEY2, KEY3 = "sk-test-limit-0123456789-aaaa", "sk-test-limit-0123456789-bbbb", "sk-test-limit-0123456789-cccc"
fresh(env={"KALMIDO_SECRET_KEY": SKEY}, prefix="P2638BS")
docker_logs_on_first_fail()
import kt  # noqa: E402
A = kt.setup()
check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 5}).ok, "personal agents allowed")
FID, Fr = freelancer(B, A)


def limits(aid):
    x = dbx("SELECT usage_limits FROM agents WHERE user_id=?", (aid,))
    return json.loads(x[0][0]) if x and x[0][0] else None


def agent(name):
    r = Fr.post(B + "/api/my/agents", json={"username": name, "display_name": name.title()})
    check(r.status_code == 201, f"setup: her agent {name} ({r.status_code} {r.text[:160]})")
    return r.json().get("id")


r = Fr.get(B + "/api/agents/server/defaults")
check(r.ok and r.json().get("day_limit_default") == 2000000, f"the new-agent dialog's defaults propose 2 million tokens a day ({r.text[:200]})")
A1 = agent("kki-one")
j = Fr.get(B + f"/api/agents/{A1}/server").json()
check(j.get("limits") is None and j.get("day_limit_default") == 2000000 and j.get("has_key") is False, f"GET: no limits yet, the proposal ({j})")
for bad in ("2000000", 0, -5, True, 10 ** 11, 1.5):
    r = Fr.put(B + f"/api/agents/{A1}/server", json={"api_key": KEY1, "day_limit": bad})
    check(r.status_code == 400 and KEY1 not in r.text, f"day_limit {bad!r}: 400 ({r.status_code})")
check(limits(A1) is None and not dbx("SELECT 1 FROM agent_server WHERE agent_id=? AND key_sealed<>''", (A1,)), "a refused PUT stores nothing")
r = Fr.put(B + f"/api/agents/{A1}/server", json={"api_key": KEY1, "day_limit": 2000000})
j = r.json() if r.ok else {}
check(r.ok and j.get("has_key") and j.get("limits") == {"period": "day", "metric": "tokens", "soft": None, "hard": 2000000},
      f"the first key + day_limit: the hard day limit in tokens ({r.status_code} {r.text[:300]})")
check(limits(A1) == {"period": "day", "metric": "tokens", "soft": None, "hard": 2000000}, f"stored on the agent ({limits(A1)})")
r = Fr.put(B + f"/api/agents/{A1}/server", json={"api_key": KEY2, "day_limit": 500})
check(r.ok and limits(A1)["hard"] == 2000000, f"a replaced key + day_limit: the limit it had stays ({limits(A1)})")

A2 = agent("kki-two")
r = Fr.put(B + f"/api/agents/{A2}/server", json={"api_key": KEY1})
check(r.ok and r.json().get("limits") is None and limits(A2) is None, f"the first key without day_limit (emptied): no limit ({r.text[:200]})")
r = Fr.put(B + f"/api/agents/{A2}/server", json={"api_key": KEY2, "day_limit": 2000000})
check(r.ok and limits(A2) is None, f"an existing key stays without a limit when it is replaced ({limits(A2)})")
check(Fr.get(B + f"/api/agents/{A2}/server").json().get("limits") is None, "GET says: no limits (the dialog shows its hint)")

A3 = agent("kki-three")
check(Fr.patch(B + f"/api/my/agents/{A3}", json={"limits": {"period": "month", "metric": "tokens", "soft": 100}}).ok, "setup: her own limit first")
r = Fr.put(B + f"/api/agents/{A3}/server", json={"api_key": KEY3, "day_limit": 2000000})
check(r.ok and limits(A3) == {"period": "month", "metric": "tokens", "soft": 100, "hard": None}, f"limits set before stay as they were ({limits(A3)})")

T = A.post(B + "/api/admin/agents", json={"username": "teamki", "display_name": "Team KI"}).json().get("id")
r = A.put(B + f"/api/agents/{T}/server", json={"api_key": KEY1, "day_limit": 1500000})
check(r.ok and limits(T) == {"period": "day", "metric": "tokens", "soft": None, "hard": 1500000}, f"a team agent: the same with its first key ({limits(T)})")

sys.exit(done("p2638_b_srvlimit"))
