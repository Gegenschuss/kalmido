#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.670.0 part C (#5127): the agent setup code needs PUBLIC_URL. Own container (start.sh through kt.fresh, restarted once
without PUBLIC_URL at the end). Invented names only.
freelancer-matrix: agents
 - with PUBLIC_URL: a new setup code (a person without an organisation for the own agent, the admin for a team agent)
   names PUBLIC_URL, and redeeming it hands out the token with PUBLIC_URL (never the request's Host header)
 - without PUBLIC_URL (its default http://localhost:3040 would land in the agent's settings): a new code is 503 with a text
   that names PUBLIC_URL, no code and no code row; a code made before the restart is not redeemed either (503, the code
   stays unused, no token) - for the person without organisation and for the team agent
usage: p2670_c_agentsetup_test.py <datadir>      (P2670C_NOSTART=1 / KMT_NOSTART=1: the first container runs already)"""
import sys

import requests

import kt
from kt import B, H, check, dbx, sess
from freelancer_fixture import freelancer

URL = "https://kalmido.example"  # PUBLIC_URL of the test container (tests/start.sh)


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def code(s, path):
    return s.post(B + path + "/setup-code", json={"os": "linux", "folder": "/work/x"})


def redeem(c):
    return requests.post(B + "/api/agent-setup/redeem", headers={**H, "Host": "evil.example"},
                         json={"code": c, "host": "box", "folder": "/work/x", "os": "linux"})


kt.fresh(prefix="P2670C")
A = kt.setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FRI, F = freelancer(B, A, "frida")

r = F.post(B + "/api/my/agents", json={"username": "helper", "display_name": "Helper"})
assert r.ok, r.text
PAID = r.json()["id"]
P = f"/api/my/agents/{PAID}"
r = A.post(B + "/api/admin/agents", json={"username": "teamhelper", "display_name": "Team Helper"})
assert r.ok, r.text
TAID = r.json()["id"]
T = f"/api/admin/agents/{TAID}"

# ---------------------------------------------------------------- with PUBLIC_URL: the code and the token name it
for who, s, path in (("person without organisation", F, P), ("team agent (admin)", A, T)):
    r = code(s, path)
    check(r.status_code == 200 and r.json().get("url") == URL, f"{who}: with PUBLIC_URL the setup code names it {r.status_code} {r.text[:160]}")
    r = redeem(r.json().get("code", ""))
    check(r.ok and r.json().get("url") == URL and "evil.example" not in r.text,
          f"{who}: the token comes with PUBLIC_URL, not the request's Host {r.status_code} {r.text[:160]}")

# codes made before the restart (redeemed only after it)
LEFT = {"person without organisation": code(F, P).json().get("code", ""), "team agent (admin)": code(A, T).json().get("code", "")}
check(all(LEFT.values()), "two codes for after the restart")

if kt.fresh(env={"PUBLIC_URL": ""}, keep=True):
    check(kt.container_env("PUBLIC_URL") == "", "restarted without PUBLIC_URL")
    F = sess("frida")
    A = sess("alice")
    for who, s, path, aid in (("person without organisation", F, P, PAID), ("team agent (admin)", A, T, TAID)):
        n = one("SELECT COUNT(*) FROM agent_setup_codes WHERE agent_id=?", (aid,))
        r = code(s, path)
        check(r.status_code == 503 and "code" not in r.json() and "PUBLIC_URL" in r.json().get("error", "") and "localhost" not in r.text,
              f"#5127: {who}: no PUBLIC_URL: no setup code (503, a text naming PUBLIC_URL) {r.status_code} {r.text[:200]}")
        check(one("SELECT COUNT(*) FROM agent_setup_codes WHERE agent_id=?", (aid,)) == n, f"#5127: {who}: and no code row was made")
        t = one("SELECT COUNT(*) FROM api_tokens WHERE user_id=?", (aid,))
        r = redeem(LEFT[who])
        check(r.status_code == 503 and "token" not in r.json() and "PUBLIC_URL" in r.text,
              f"#5127: {who}: a code made before is not redeemed without PUBLIC_URL (503) {r.status_code} {r.text[:200]}")
        check(one("SELECT COUNT(*) FROM api_tokens WHERE user_id=?", (aid,)) == t, f"#5127: {who}: and no token was made")
        check(one("SELECT COUNT(*) FROM agent_setup_codes WHERE agent_id=? AND used_at IS NOT NULL AND token_id IS NULL", (aid,)) == 0,
              f"#5127: {who}: the code is not used up")
        r = s.get(B + path + "/machines")
        check(r.ok, f"{who}: the computers list still answers {r.status_code}")
else:
    print("P2670C_NOSTART: the restart without PUBLIC_URL is skipped", flush=True)

sys.exit(kt.done("p2670_c_agentsetup"))
