#!/usr/bin/env python3
"""2.6.0 (UX audit 2, package "UX2") API, own container (start.sh):
K08 every agent as people see it (GET /api/state, /api/agents, /api/v1/agents, Settings > Agents: /api/admin/agents) carries
`webhook` (bool) and `contact_age` (seconds since its last event poll or API call with its token, null = never): null for a
new agent, a few seconds after any v1 call, after an event poll too; the old fields (online, poll_age, last_poll_at) stay.
K23 the refused test alert (admin alerts switched off on the server, start.sh: KALMIDO_ADMIN_ALERTS=0) explains it in plain
words, without the variable.
usage: p260_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": "password123"})
    assert r.ok, r.text
    return s


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
requests.post(B + "/api/auth/setup", headers=H, json={"username": "alice", "display_name": "Alice", "password": "password123"})
A = sess("alice")
A.patch(B + "/api/settings", json={"features": "collab,agents", "lang": "en", "tour": "done"})
ag = A.post(B + "/api/admin/agents", json={"username": "claude", "display_name": "Claude"}).json()
AID, TOK = ag["id"], ag["token"]
V = requests.Session()
V.headers.update({"Authorization": "Bearer " + TOK})
L = A.post(B + "/api/lists", json={"name": "Web"}).json()["id"]
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": AID, "role": "edit"}).ok, "list shared with the agent")


def mine(path, key="agents"):
    j = A.get(B + path).json()
    rows = j.get(key) if isinstance(j, dict) else j
    return next((a for a in rows or [] if a["id"] == AID), None)


# ---- K08: never in touch
for path, key in (("/api/state", "agents"), ("/api/agents", "agents"), ("/api/admin/agents", "agents")):
    a = mine(path, key)
    check(a is not None and "contact_age" in a and a["contact_age"] is None, f"{path}: contact_age null for a new agent: {a and a.get('contact_age')}")
    check(a is not None and "online" in a and "poll_age" in a and "last_poll_at" in a, f"{path}: the old fields stay")
check(mine("/api/state")["webhook"] is False, "a polling agent: webhook false")
check(mine("/api/admin/agents")["webhook"] in (None, False), "admin view: no webhook (null)")

# any API call counts as contact
check(V.get(B + "/api/v1/tasks", params={"list_id": L}).ok, "agent: one v1 call")
a = mine("/api/state")
check(a["contact_age"] is not None and 0 <= a["contact_age"] <= 5 and a["poll_age"] is None, f"after a v1 call: contact_age {a['contact_age']}, still never polled")
check(V.get(B + "/api/v1/agent/events").ok, "agent: event poll")
a = mine("/api/agents")
check(a["contact_age"] is not None and a["contact_age"] <= 5 and a["poll_age"] is not None and a["online"] is True, "after a poll: contact + online")

# ---- K23: plain words
r = A.post(B + "/api/admin/alerts/test")
e = r.json().get("error") if r.headers.get("content-type", "").startswith("application/json") else r.text
msg = e.get("message", "") if isinstance(e, dict) else str(e)
check(r.status_code == 409 and "server operator" in msg and "KALMIDO_" not in msg, f"test alert refused in plain words: {r.status_code} {msg}")

print(f"p260_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
