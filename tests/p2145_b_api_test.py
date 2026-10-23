#!/usr/bin/env python3
"""2.145.0 API tests, part B (#2424): what an own window (/?mini=1#…) starts from, own container (start.sh). Invented names only.
 - GET /?mini=1 is the app page (no cache, the code's version), miniwin.js runs before main.js (it asks the main window for its
   state while the other scripts still run)
 - the state an own window draws from (GET /api/state, which the main window has open) carries the person, the lists, the tasks and
   the change counter; the single task (GET /api/tasks/<id>, the task window) and the team room (the chat window) answer
 - a person without an organisation (freelancer-matrix: tasks): the same state and the same task fetch
 - another person's task stays closed to the task window (404 / 403), nothing of it is in her state
usage: p2145_b_api_test.py <datadir>"""
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


if os.environ.get("P2145B_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Studio", "lang": "en", "collab_all": True, "modules": ["comments"]})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
FEAT = "collab,comments,team"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})

# ---- the page
r = A.get(B + "/?mini=1")
check(r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""), f"the own window's page: {r.status_code}")
check("no-cache" in r.headers.get("Cache-Control", ""), "the page is not cached (a new version arrives)")
check(re.search(r'<meta name="kalmido-version" content="[^"]+">', r.text) is not None, "the page carries the code's version")
# 2.149.0 (#2505): the served page adds ?v=<content hash>
srcs = re.findall(r'<script src="/static/js/([\w-]+)\.js(?:\?v=\w+)?"(?: defer)?></script>', r.text)  # 2.191.0 B (#2505): defer
check("miniwin" in srcs and "main" in srcs and srcs.index("miniwin") < srcs.index("main"), "miniwin.js runs before main.js")
js = requests.get(B + "/static/js/miniwin.js")
check(js.ok and "kalmido-mini-state" in js.text and "mw_bootLoad" in js.text, "miniwin.js has the start from the main window's state")

# ---- the state a window draws from
L = A.post(B + "/api/lists", json={"name": "Workshop", "org_id": None}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Sand the shelf", "list_id": L}).json()["id"]
st = A.get(B + "/api/state").json()
check(st.get("me", {}).get("id") and isinstance(st.get("lists"), list) and isinstance(st.get("tasks"), list) and "v" in st,
      "the state carries the person, lists, tasks and the change counter")
check(any(t["id"] == T for t in st["tasks"]), "the new task is in the state")
r = A.get(B + f"/api/tasks/{T}")
check(r.ok and r.json().get("title") == "Sand the shelf", f"the task window's task: {r.status_code}")
team = A.get(B + "/api/team")
check(team.ok and isinstance(team.json().get("rooms"), list), f"the chat window's rooms: {team.status_code}")

# ---- another person's task stays closed (the window never gets more than the main window has)
st_b = Bo.get(B + "/api/state").json()
check(not any(t["id"] == T for t in st_b.get("tasks", [])), "bob's state has none of alice's private tasks")
r = Bo.get(B + f"/api/tasks/{T}")
check(r.status_code in (403, 404), f"bob's task window cannot fetch alice's task: {r.status_code}")

# ---- freelancer-matrix: tasks (a person without an organisation)
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Own projects"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Draft the offer", "list_id": FL}).json()["id"]
sf = Fr.get(B + "/api/state").json()
check(sf.get("me", {}).get("id") == FID and any(t["id"] == FT for t in sf.get("tasks", [])), "without an organisation: the same state")
r = Fr.get(B + f"/api/tasks/{FT}")
check(r.ok and r.json().get("title") == "Draft the offer", f"without an organisation: the task window's task: {r.status_code}")
r = Fr.get(B + "/?mini=1")
check(r.status_code == 200, f"without an organisation: the own window's page: {r.status_code}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
