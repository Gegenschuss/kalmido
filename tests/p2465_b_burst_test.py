#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.465.0 (#3892): web and worker apart (KALMIDO_ROLE=web + `python app.py worker`): a burst the web process held still
reaches the agent. The web process has no watchdog, so before the fix the summary 'tasks_added' stayed in its memory for
good. The tasks wait in the table agent_burst_held, the worker sends one event and empties it. Invented names only."""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, CT, check, done, until  # noqa: E402

V = B + "/api/v1"
kt.fresh(env={"KALMIDO_ROLE": "web", "KALMIDO_AGENT_BURST_S": 30, "KALMIDO_AGENT_BURST_QUIET_S": 1})
A = kt.setup(lang="en")
ORG = A.post(B + "/api/orgs", json={"name": "Nordlicht"}).json()["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "robo", "display_name": "Robo", "org_id": ORG})
assert r.ok, r.text
AG, AH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{W}/members", json={"user_id": AG, "role": "edit"})
A.patch(B + f"/api/lists/{W}", json={"agent_members": True})
A.patch(B + f"/api/lists/{W}", json={"listen_agent_ids": [AG]})
cur = requests.get(V + "/agent/events?since=latest", headers=AH).json()["cursor"]


def events():
    return requests.get(V + f"/agent/events?since={cur}&limit=200", headers=AH).json()["data"]


ids = [A.post(B + "/api/tasks", json={"title": f"bulk {i}", "list_id": W}).json()["id"] for i in range(9)]
held = kt.dbx("SELECT task_id FROM agent_burst_held WHERE list_id=? ORDER BY id", (W,))
single = [e for e in events() if e["event"] == "task_added"]
check(len(single) == 5 and len(held) == 4, f"#3892: five single events, the rest waits in the table ({len(single)}, {len(held)})")
gone = held[0][0]
check(A.delete(B + f"/api/tasks/{gone}").ok, "#3892: a held task is deleted")
subprocess.Popen(["docker", "exec", "-e", "KALMIDO_ROLE=worker", "-w", "/app", CT, "python", "app.py", "worker"],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
bulk = until(lambda: [e for e in events() if e["event"] == "tasks_added"], 90)
check(bulk and len(bulk) == 1, f"#3892: the worker sends ONE tasks_added for the burst of the web process {bulk}")
d = bulk[0]["data"] if bulk else {}
check(d.get("how") == "created" and d.get("list_id") == W and sorted(d.get("task_ids", [])) == sorted(x[0] for x in held[1:]) and d.get("count") == 3
      and d.get("truncated") is False, f"#3892: ... with the ids that still exist {d}")
check(bulk and bulk[0]["actor"]["name"] == "Alice Admin" and bulk[0]["actor"]["kind"] == "person", "#3892: ... and the person who did it")
check(kt.dbx("SELECT COUNT(*) FROM agent_burst_held")[0][0] == 0, "#3892: the table is empty afterwards")
sys.exit(done("p2465_b_burst"))
