#!/usr/bin/env python3
"""2.144.0 API tests (part B: agent chat folding, job card, agent colours), own container (start.sh).
 - #2411: every agent has a palette colour in /api/state (colors), stable across calls; PATCH /api/agents/<id>/color changes it
   (a colour outside the palette is refused); the two agents differ
 - #2365 / #2417: a job's end result posted without an earlier say message comes back from the chat with its text intact and
   the kind derived from it (job_msg stays null, the app reads the leading check mark); a long message keeps its full body
usage: p2144_b_api_test.py <datadir>      (a fresh container; P2144B_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

# freelancer-matrix: agents (the colour route is the same for a person without an organisation: owner of the agent)
N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


if not os.environ.get("P2144B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
st = A.get(B + "/api/state").json()
feats = set(filter(None, ((st.get("settings") or {}).get("features") or "").split(",")))
feats.add("agents")
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": ",".join(sorted(feats))})
ME = A.get(B + "/api/state").json()["me"]
ag = {}
for u in ("devbot", "srvbot"):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": u, "display_name": u.title()}).json()
    ag[u] = r
PAL = {"#3e63dd", "#f76b15", "#30a46c", "#a43cb4", "#cf3539", "#12a594", "#e2a336", "#c2307f", "#2aa7dc", "#8d5f3e", "#6e56cf", "#99b13a"}
cols = A.get(B + "/api/state").json().get("colors", {})
c1, c2 = cols.get(str(ag["devbot"]["id"])), cols.get(str(ag["srvbot"]["id"]))
check(c1 in PAL and c2 in PAL, f"both agents have a palette colour {c1} {c2}")
check(c1 != c2, "the two agents differ in colour")
check(A.get(B + "/api/state").json().get("colors", {}).get(str(ag["devbot"]["id"])) == c1, "the colour is stable")
new = next(c for c in sorted(PAL) if c not in (c1, c2))
r = A.patch(B + f"/api/agents/{ag['devbot']['id']}/color", json={"color": new})
check(r.ok, f"agent colour changes {r.status_code}")
check(A.get(B + "/api/state").json().get("colors", {}).get(str(ag["devbot"]["id"])) == new, "the new colour is in the state")
check(A.patch(B + f"/api/agents/{ag['devbot']['id']}/color", json={"color": "#123456"}).status_code == 400, "a colour outside the palette is refused")

# a job's end result without an earlier say message
TOK = ag["devbot"]["token"]
A.patch(B + f"/api/admin/agents/{ag['devbot']['id']}", json={"org_id": ME["workspaces"][0]["id"]})
V = {"Authorization": "Bearer " + TOK, "Content-Type": "application/json"}
WL = A.post(B + "/api/lists", json={"name": "Work", "org_id": ME["workspaces"][0]["id"]}).json()["id"]
A.put(B + f"/api/lists/{WL}/members", json={"user_id": ag["devbot"]["id"], "role": "edit"})
JR = requests.post(B + "/api/v1/agent/jobs", headers=V, json={"title": "Knox: Release 2.144", "user_id": ME["id"], "state": "running"})
J = JR.json().get("id")
check(J, "setup: a job")
long = "✅ Knox: ready\n" + "\n".join(f"- point {i}" for i in range(12))
mid = requests.post(B + f"/api/v1/agent/chats/{ME['id']}", headers=V, json={"body": long, "job_id": J}).json()["id"]
requests.patch(B + f"/api/v1/agent/jobs/{J}", headers=V, json={"state": "done"})
j = A.get(B + f"/api/agents/{ag['devbot']['id']}/chat?limit=30").json()
m = next((x for x in j["messages"] if x["id"] == mid), {})
check(m.get("body") == long, "the long end result comes back whole")
check(m.get("job_id") == J and (m.get("job_msg") in (None, "result")), "the result is tied to its job")
check(str(J) in {str(k) for k in (j.get("jobs") or {})} and j["jobs"][str(J)]["state"] == "done", "the chat answer carries the finished job")

print(f"p2144_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
