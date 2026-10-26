#!/usr/bin/env python3
"""2.306.0 E (#2927): the one-command setup of a team agent names who answers its permission questions.
freelancer-matrix: agents
 - POST /api/agent-setup/redeem answers operator_id = the account id of the person who made the setup code, for a team
   agent (no owner) only; agent.team says which kind it is
 - only the code's maker counts: a second admin's code gives that admin's id, not the first one's
 - a personal agent (own code or an admin's code): no operator_id (its owner answers), team false
 - a team agent of an organisation: a maker outside it (shared list or membership missing) gets no operator_id, a
   member does (review)
 - the agent's name reaches the starter without control characters (sh, ps1 and the answer; review)
 - a maker who is disabled by the time the code is redeemed: no operator_id
 - a person without an organisation sets up their own agent the same way (team false, no operator_id)
 - static: both setup scripts write KALMIDO_PERM_USER from operator_id, keep an earlier KALMIDO_PERM_USER / OWNER_IDS,
   create CLAUDE.md from the template only when there is none, and mark the same steps; agent_run.py puts the usage hook
   into the run settings
usage: p2306_e_team_agent_setup_test.py <datadir>      (KMT_NOSTART=1 / P2306E_NOSTART=1: a running server)"""
import os
import re
import sys

import requests
from freelancer_fixture import freelancer
from kt import B, check, done, fresh, sess, setup

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
H = {"X-Requested-With": "kalmido"}


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- static: setup scripts + launcher (no server needed)
SH, PS = read("static", "agent", "setup.sh"), read("static", "agent", "setup.ps1")
for name, src in (("setup.sh", SH), ("setup.ps1", PS)):
    check("operator_id" in src and "KALMIDO_PERM_USER=" in src, f"{name}: writes KALMIDO_PERM_USER from operator_id")
    check("KALMIDO_(PERM_USER|OWNER_IDS)=" in src or ('"KALMIDO_PERM_USER=", "KALMIDO_OWNER_IDS="' in src),
          f"{name}: keeps an earlier KALMIDO_PERM_USER / KALMIDO_OWNER_IDS")
    check("kalmido-setup-step: claude_md" in src and "CLAUDE.template.md" in src and "kalmido-agent-rules:start" in src,
          f"{name}: CLAUDE.md from the template")
    check(".claude" in src and ("perm_you" in src and "claude_new" in src and "claude_kept" in src), f"{name}: names who answers and where CLAUDE.md is")
check(re.findall(r"kalmido-setup-step:\s*([a-z_]+)", SH) == re.findall(r"kalmido-setup-step:\s*([a-z_]+)", PS), "setup.sh and setup.ps1: the same steps")
check('open(sys.argv[2], "x"' in SH, "setup.sh: CLAUDE.md is created exclusively (never overwritten)")
RUN = read("mcp", "agent_run.py")
check("claude_usage_hook.py" in RUN and '"SubagentStop"' in RUN and '"Stop"' in RUN, "agent_run.py: the usage hook in the run settings")
check("CLAUDE.template.md" in read("mcp", "starter_files.txt") and "claude_usage_hook.py" in read("mcp", "starter_files.txt"),
      "the template and the usage hook are starter files")

# ---------------------------------------------------------------- server
fresh(prefix="P2306E")
A = setup()
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
me_a = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"username": "adm2", "display_name": "Second Admin", "password": "password123",
                                   "email": "adm2@example.com", "is_admin": True})
assert r.ok, r.text
ADM2 = r.json()["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
r_bob = r.json()["id"]
A2, Bo = sess("adm2"), sess("bob")


def redeem(code):
    return requests.post(B + "/api/agent-setup/redeem", headers=H, json={"code": code, "host": "box", "folder": "/work/x", "os": "linux"})


def code(s, path):
    r = s.post(B + path, json={"os": "linux", "folder": "/work/x"})
    assert r.ok, r.text
    return r.json()["code"]


r = A.post(B + "/api/admin/agents", json={"username": "teamhelper", "display_name": "Team Helper"})
assert r.ok, r.text
TEAM = r.json()["id"]
r = redeem(code(A, f"/api/admin/agents/{TEAM}/setup-code"))
j = r.json()
check(r.ok and j.get("operator_id") == me_a and j["agent"].get("team") is True, f"team agent, admin's code: the admin answers {j}")
check(set(j) >= {"token", "url", "agent", "starter_base"}, "the rest of the answer as before")
r = redeem(code(A2, f"/api/admin/agents/{TEAM}/setup-code"))
check(r.ok and r.json().get("operator_id") == ADM2, f"team agent, second admin's code: only its maker {r.json().get('operator_id')}")

r = Bo.post(B + "/api/my/agents", json={"username": "bobs-helper", "display_name": "Bob Helper"})
assert r.ok, r.text
OWN = r.json()["id"]
r = redeem(code(Bo, f"/api/my/agents/{OWN}/setup-code"))
check(r.ok and r.json().get("operator_id") is None and r.json()["agent"].get("team") is False, f"personal agent, own code: owner answers {r.text[:200]}")
r = redeem(code(A, f"/api/admin/agents/{OWN}/setup-code"))
check(r.ok and r.json().get("operator_id") is None, "personal agent, admin's code: still the owner, not the admin")

# 2.306.0 review (#2927): a team agent of an organisation -- only a maker who reaches the agent answers (shared list or a
# member of the organisation); an instance admin outside it gets no operator_id (the starter then says "nobody set")
r = A.post(B + "/api/admin/orgs", json={"name": "Customer", "admin_id": r_bob})
check(r.ok, f"an organisation the admin is not in {r.text[:200]}")
if r.ok:
    CUST = r.json()["id"]
    in_cust = CUST in [w.get("id") for w in A.get(B + "/api/state").json()["me"].get("workspaces", [])]
    r = A.post(B + "/api/admin/agents", json={"username": "custhelper", "display_name": "Customer Helper", "org_id": CUST})
    assert r.ok, r.text
    CH = r.json()["id"]
    r = redeem(code(A, f"/api/admin/agents/{CH}/setup-code"))
    check(r.ok and not in_cust and r.json().get("operator_id") is None and r.json()["agent"].get("team") is True,
          f"organisation's team agent, code of an admin outside it: nobody {in_cust} {r.text[:200]}")
r = A.post(B + "/api/admin/orgs", json={"name": "Customer Two", "admin_id": me_a})
check(r.ok, f"an organisation the admin is in {r.text[:200]}")
if r.ok:
    r = A.post(B + "/api/admin/agents", json={"username": "custhelper2", "display_name": "Customer Helper Two", "org_id": r.json()["id"]})
    assert r.ok, r.text
    r = redeem(code(A, f"/api/admin/agents/{r.json()['id']}/setup-code"))
    check(r.ok and r.json().get("operator_id") == me_a, f"organisation's team agent, code of a member: the member answers {r.text[:200]}")

# 2.306.0 review (#2927): the name goes into the env file's comment line -- no control characters on the way there
r = A.post(B + "/api/admin/agents", json={"username": "linehelper", "display_name": "Line\nKALMIDO_PERM_USER=1\tx"})
assert r.ok, r.text
LH, stored = r.json()["id"], str(r.json().get("display_name") or "")
check("Line" in stored and not re.search(r"[\x00-\x1f\x7f]", stored), f"the stored agent name is one line {stored!r}")
r = Bo.post(B + "/api/my/agents", json={"username": "bobs-line", "display_name": "Bob\r\nLine"})
check(r.ok and not re.search(r"[\x00-\x1f\x7f]", str(r.json().get("display_name") or r.json().get("name") or "")), f"own agent: one line too {r.text[:200]}")
r = redeem(code(A, f"/api/admin/agents/{LH}/setup-code"))
nm = r.json()["agent"]["name"] if r.ok else ""
check(r.ok and "Line" in nm and not re.search(r"[\x00-\x1f\x7f]", nm), f"setup answer: the agent name without control characters {nm!r}")
check('re.sub(r"[\\x00-\\x1f\\x7f]", " "' in SH and "-replace '[\\x00-\\x1f\\x7f]', ' '" in PS and "$AgName" in PS,
      "setup.sh and setup.ps1: the name in the env file without control characters")

c = code(A2, f"/api/admin/agents/{TEAM}/setup-code")
assert A.patch(B + f"/api/users/{ADM2}", json={"disabled": True}).ok
r = redeem(c)
check(r.ok and r.json().get("operator_id") is None, f"a maker disabled before the redeem: nobody {r.text[:200]}")

# freelancer-matrix: agents -- a person without an organisation
FID, F = freelancer(B, A)
r = F.post(B + "/api/my/agents", json={"username": "frida-helper", "display_name": "Frida Helper"})
check(r.ok, f"without an organisation: own agent {r.text[:200]}")
if r.ok:
    r = redeem(code(F, f"/api/my/agents/{r.json()['id']}/setup-code"))
    check(r.ok and r.json()["token"].startswith("abk_") and r.json().get("operator_id") is None and r.json()["agent"].get("team") is False,
          f"without an organisation: set up the same way {r.text[:200]}")
sys.exit(done("p2306_e_team_agent_setup"))
