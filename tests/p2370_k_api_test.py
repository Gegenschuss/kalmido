#!/usr/bin/env python3
"""2.37.0 API tests (part 2, agent K: #1150 review points of the database layer), own container (start.sh).
 - task search takes the text literally: a backslash, % and _ are no pattern characters ("C:\\Users\\x" is found, "%" alone
   does not find every task, "0%_rabatt" nothing); web search and REST API. 2.997.0 (#5720): words of the shared index obj_search
   (#5278): "50%_rabatt" = the words 50* and rabatt*
 - a value the database refuses (a number out of range) is a 400 with a short message, not a crash, in the web API and in
   the REST API (its own error format); the next request on the same server works normally
usage: p2370_k_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok

ids = {}
for title in ("C:\\Users\\x", "50%_rabatt", "500 rabatt", "Users x", "plain"):
    r = A.post(B + "/api/tasks", json={"title": title})
    check(r.ok, "setup: task " + title + " " + r.text[:100])
    ids[title] = r.json().get("id")


def web(q):
    r = A.get(B + "/api/tasks", params={"scope": "search", "q": q})
    return sorted(t["id"] for t in r.json().get("tasks", [])) if r.ok else r.status_code


# ---- W-5: the search text is literal
BS = "C:\\Users\\x"
got = web(BS)
check(got == [ids[BS]], f"a backslash is text: {BS!r} found ({got})")
# 2.997.0 (#5720): since 2.981.0 (#5278, stage Q6a) the search goes through the shared word index
# obj_search: every word of letters / digits is the start of a word, \\ % _ separate words and are never pattern characters
check(web("\\U") == sorted([ids[BS], ids["Users x"]]), "a lone backslash sequence is text too: the word U at a word start")
got = web("50%_rabatt")
check(got == sorted([ids["50%_rabatt"], ids["500 rabatt"]]), f"'50%_rabatt' = the words 50* and rabatt* ({got})")
got = web("0%_rabatt")
check(got == [], f"'%' is no wildcard: '0%_rabatt' finds nothing (no word starts with 0) ({got})")
for q in ("%", "_"):
    got = web(q)
    check(got == [], f"{q!r} alone does not find every task ({got})")
check(web("rabatt") == sorted([ids["50%_rabatt"], ids["500 rabatt"]]), "a plain word still finds every task containing it")

tok = A.post(B + "/api/me/tokens", json={"name": "k", "scopes": ["read", "write"]}).json().get("token")
check(bool(tok), "setup: API token")
TH = {"Authorization": "Bearer " + (tok or "")}
r = requests.get(B + "/api/v1/search", params={"q": "50%_rabatt"}, headers=TH)
check(r.ok and sorted(t["id"] for t in r.json().get("data", [])) == sorted([ids["50%_rabatt"], ids["500 rabatt"]]),
      f"REST search: the same words ({r.text[:200]})")  # 2.997.0 (#5720): word index (#5278), as the web search
r = requests.get(B + "/api/v1/search", params={"q": "%"}, headers=TH)
check(r.ok and not r.json().get("data"), f"REST search: '%' alone finds nothing ({r.text[:200]})")
r = requests.get(B + "/api/v1/search", params={"q": "C:\\Users"}, headers=TH)
check(r.ok and sorted(t["id"] for t in r.json().get("data", [])) == [ids["C:\\Users\\x"]], f"REST search: backslash ({r.text[:200]})")

# ---- W-6: a value the database refuses -> 400, not 500
huge = 99999999999999999999  # beyond BIGINT
r = A.post(B + "/api/tasks", json={"title": "x", "list_id": huge})
check(r.status_code == 400 and isinstance(r.json().get("error"), str) and r.json()["error"], f"web API: 400 with a message ({r.status_code} {r.text[:200]})")
r = requests.post(B + "/api/v1/tasks", json={"title": "x", "list_id": huge}, headers=TH)
err = (r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}).get("error")
check(r.status_code == 400 and isinstance(err, dict) and err.get("code") == "invalid" and err.get("message"),
      f"REST API: 400 in its own error format ({r.status_code} {r.text[:200]})")
for _ in range(5):  # the connections went back to the pool healthy
    r = A.get(B + "/api/state")
    check(r.ok, f"next request works ({r.status_code})")
r = A.post(B + "/api/tasks", json={"title": "after the error"})
check(r.ok and r.json().get("id"), "a write after the error works")

print(f"p2370_k_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
