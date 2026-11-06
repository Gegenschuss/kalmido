#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.575.0 C (#3948): rest of the 2.391 review.
 - L2: GET /api/v1/me/tokens: a project-limited token sees the other tokens' list_ids only within its own limit
 - L3: IDEM_WAIT is 10 s
 - L4: docs/API.md says the rate-limit headers count per process
 - L5: setup.ps1 asks the tool with a timeout, the Codex wrapper cuts comments behind values, TOML strings take an apostrophe
Invented names only."""
import os
import re
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, done  # noqa: E402

ROOT = os.path.dirname(N)


def src(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as fh:
        return fh.read()


kt.fresh(prefix="P2575C")
kt.docker_logs_on_first_fail()
A = kt.setup(lang="en")
_, F = freelancer(B, A, "frida")
V = B + "/api/v1"


def tok(**extra):
    r = F.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "account", "integrations"], **extra})
    assert r.status_code == 201, r.text
    return r.json()


P1 = F.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
P2 = F.post(B + "/api/lists", json={"name": "Site", "kind": "project"}).json()["id"]
P3 = F.post(B + "/api/lists", json={"name": "Docs", "kind": "project"}).json()["id"]
t_lim, t_two, t_all = tok(list_ids=[P1]), tok(list_ids=[P1, P2]), tok()


def listing(t):
    r = requests.get(V + "/me/tokens", headers={"Authorization": "Bearer " + t["token"]}, timeout=60)
    assert r.ok, r.text
    return {x["id"]: x["list_ids"] for x in r.json()["data"]}


got = listing(t_lim)
check(got[t_two["id"]] == [P1], f"L2: a limited token sees only its own projects of another token {got}")
check(P2 not in sum(got.values(), []) and P3 not in sum(got.values(), []), "L2: no project id outside its limit")
check(got[t_lim["id"]] == [P1], "L2: its own limit")
got = listing(t_all)
check(got[t_two["id"]] == [P1, P2] and got[t_lim["id"]] == [P1], f"L2: an unlimited token sees all {got}")

check(re.search(r"^IDEM_WAIT = 10(\.0)?\b", src("kalmido", "core", "idem.py"), re.M), "L3: IDEM_WAIT is 10 s")
check("counter lives in each server process" in src("docs", "API.md"), "L4: API.md names the per-process counter")
ps = src("static", "agent", "setup.ps1")
check("Read-Host (M 'ask_tool')" not in ps and "AddSeconds(120)" in ps, "L5: setup.ps1 asks the tool with a 120 s timeout")
check("(\\s+#.*)?$" in ps and "-replace '\\s+#.*$'" in ps, "L5: the Codex wrapper cuts comments behind values")
check("function TomlS" in ps and "TomlS $_" in ps and "$InnerArg" in ps, "L5: TOML basic strings, quotes escaped for -Command")

sys.exit(done("p2575_c_api"))
