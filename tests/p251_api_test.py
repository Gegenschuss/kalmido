#!/usr/bin/env python3
"""2.5.1 API tests.
 - #393 the agents' activity log for Settings > AI colleague > Log: hide_poll=1 leaves out the event polling
   (GET /api/v1/agent/events) and nothing else, the CSV follows it; `today` {requests, denied, polls} on the first page
   (per agent with agent_id, not on later pages); task_title / list_name only where the viewing admin sees the task / list
   (a list the admin is not in: ids only); limit=20 + before= paging; the v1 audit route is unchanged
 - #396 the suggested branch is kalmido-<id> (no title part) in the assigned event and get_task; a pull request on a
   branch named exactly kalmido-<id> links to the task, an old kalmido-<id>-<slug> branch still does (fake GitHub inside
   the test container, fake_git.py)
Starts its OWN container (start.sh).
usage: p251_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()
GH = "http://127.0.0.1:8090"      # fake GitHub Enterprise (API under /api/v3)
TOKEN = "ghp_fake_read_only_token_2b51"
FAILS, OKS = [], [0]
STATE = {}


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


class Api:
    def __init__(self, tok):
        self.h = {"Authorization": "Bearer " + tok}

    def req(self, m, p, **k):
        return requests.request(m, V + p, headers=self.h, timeout=60, **k)

    def get(self, p, **k):
        return self.req("GET", p, **k)

    def post(self, p, **k):
        return self.req("POST", p, **k)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def put_state():
    tmp = os.path.join(DATA, "git.json.tmp")
    with open(tmp, "w") as f:
        json.dump(STATE, f)
    os.replace(tmp, os.path.join(DATA, "git.json"))


def until(fn, t=15.0):
    t0 = time.time()
    while time.time() - t0 < t:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def pr(n, title, ref, sha):
    return {"number": n, "title": title, "body": "", "state": "open", "merged_at": None, "html_url": f"{GH}/acme/app/pull/{n}",
            "user": {"login": "dev"}, "head": {"ref": ref, "sha": sha}, "updated_at": iso(datetime.now(timezone.utc))}


STATE.update({"8090": {"acme/app": {"token": TOKEN, "default_branch": "main", "pulls": [], "commits": {"main": []}}}})
env = dict(os.environ, EXTRA=" ".join(["-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1", "-e KALMIDO_GIT_POLL=2", "-e KALMIDO_GIT_TICK=1",
                                        "-e KALMIDO_SECRET_KEY=" + KEY]))
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
put_state()
subprocess.run(["cp", os.path.join(N, "fake_git.py"), DATA])
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_git.py"])
time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
for x in (A, Bo):
    x.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/agents", json={"username": "claude", "display_name": "Claude"})
assert r.status_code == 201, r.text
AG, ag = r.json()["id"], Api(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"username": "helper", "display_name": "Helper"})
AG2, ag2 = r.json()["id"], Api(r.json()["token"])

# ================================================================== #393 the activity log
TEAM = A.post(B + "/api/lists", json={"name": "Team board"}).json()["id"]
assert A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": AG, "role": "edit"}).ok
T = A.post(B + "/api/tasks", json={"title": "Write the release notes", "list_id": TEAM}).json()["id"]
BL = Bo.post(B + "/api/lists", json={"name": "Bob private"}).json()["id"]
assert Bo.put(B + f"/api/lists/{BL}/members", json={"user_id": AG, "role": "edit"}).ok
TB = Bo.post(B + "/api/tasks", json={"title": "Bob secret task", "list_id": BL}).json()["id"]
check(ag.get(f"/tasks/{T}").ok and ag.get(f"/tasks/{TB}").ok, "agent reads both tasks")
for _ in range(30):
    ag.get("/agent/events", params={"since": 0})
for _ in range(25):
    ag.get("/me")
ag.post("/tasks", json={"title": "From the agent", "list_id": TEAM})
ag2.get("/agent/events", params={"since": 0})
A.patch(B + f"/api/admin/agents/{AG}", json={"enabled": False})
check(ag.get("/lists").status_code == 403, "paused: 403")
A.patch(B + f"/api/admin/agents/{AG}", json={"enabled": True})
time.sleep(0.3)

full = A.get(B + "/api/admin/agents/audit", params={"limit": 500}).json()
allrows = full["data"]
polls = [x for x in allrows if x["method"] == "GET" and x["route"] == "/api/v1/agent/events"]
check(len(polls) == 31 and len(allrows) == 31 + 25 + 2 + 1 + 1, f"all rows incl. polling: {len(allrows)} ({len(polls)} polls)")
j = A.get(B + "/api/admin/agents/audit", params={"hide_poll": "1", "limit": 500}).json()
check(len(j["data"]) == len(allrows) - 31 and not any(x["route"] == "/api/v1/agent/events" for x in j["data"]), f"hide_poll=1: without the polling ({len(j['data'])})")
check(A.get(B + "/api/admin/agents/audit", params={"hide_poll": "0", "limit": 500}).json()["data"].__len__() == len(allrows), "hide_poll=0: everything")
t = full.get("today") or {}
check(t == {"requests": len(allrows), "denied": 1, "polls": 31}, f"today summary: {t}")
t2 = A.get(B + "/api/admin/agents/audit", params={"agent_id": AG2}).json().get("today")
check(t2 == {"requests": 1, "denied": 0, "polls": 1}, f"today per agent: {t2}")
t3 = A.get(B + f"/api/admin/agents/{AG2}/audit").json().get("today")
check(t3 == {"requests": 1, "denied": 0, "polls": 1}, f"today on the per-agent route: {t3}")
p1 = A.get(B + "/api/admin/agents/audit", params={"hide_poll": "1", "limit": 20}).json()
check(len(p1["data"]) == 20 and p1["next_before"], "limit=20 + a cursor")
p2 = A.get(B + "/api/admin/agents/audit", params={"hide_poll": "1", "limit": 50, "before": p1["next_before"]}).json()
check(len(p2["data"]) == len(allrows) - 31 - 20 and "today" not in p2 and not p2["next_before"]
      and max(x["id"] for x in p2["data"]) < min(x["id"] for x in p1["data"]), "the next page: the rest, no summary")
# titles where the admin sees them
mine = next(x for x in allrows if x["task_id"] == T)
check(mine["task_title"] == "Write the release notes", f"task title in a list the admin sees: {mine.get('task_title')}")
bob = next(x for x in allrows if x["task_id"] == TB)
check(bob["task_title"] is None and "Bob secret" not in json.dumps(full), "a task in a list the admin is not in: id only, no title anywhere")
made = next(x for x in allrows if x["method"] == "POST" and x["route"] == "/api/v1/tasks")
check(made["list_id"] == TEAM and made["list_name"] == "Team board", f"list name from the body's list id: {made.get('list_name')}")
check(all("task_title" in x and "list_name" in x for x in allrows), "every row carries both keys")
# CSV follows hide_poll; no titles in the CSV
csv1 = A.get(B + "/api/admin/agents/audit", params={"format": "csv", "hide_poll": "1"}).text
csv2 = A.get(B + "/api/admin/agents/audit", params={"format": "csv"}).text
n1, n2 = len([x for x in csv1.split("\r\n") if x.strip()]), len([x for x in csv2.split("\r\n") if x.strip()])
check(n2 - n1 == 31 and "release notes" not in csv2, f"CSV: hide_poll applies ({n1} / {n2}), ids only")
# admins only; the v1 route as before
check(Bo.get(B + "/api/admin/agents/audit", params={"hide_poll": "1"}).status_code == 403, "members: 403")
r = A.post(B + "/api/me/tokens", json={"name": "audit", "scopes": ["read", "admin-read"]})
check(r.status_code == 201, f"admin-read token: {r.status_code}")
j = requests.get(V + f"/admin/agents/{AG}/audit", headers={"Authorization": "Bearer " + r.json()["token"]}).json()
check(set(j) == {"data", "next_cursor"} and len(j["data"]) == 59 and "task_title" not in j["data"][0], f"v1 audit: unchanged (no summary, no titles, polling included): {len(j.get('data', []))}")
check(requests.get(V + f"/admin/agents/{AG}/audit", params={"hide_poll": "1"}, headers={"Authorization": "Bearer " + r.json()["token"]}).status_code == 400,
      "v1 audit: hide_poll is not a v1 parameter (400)")

# ================================================================== #396 branch kalmido-<id>
P = A.post(B + "/api/lists", json={"name": "App", "kind": "project"}).json()["id"]
assert A.put(B + f"/api/lists/{P}/members", json={"user_id": AG, "role": "edit"}).ok
r = A.post(B + f"/api/lists/{P}/repos", json={"provider": "github", "base_url": GH, "repo": "acme/app", "token": TOKEN})
check(r.status_code == 201, f"repository connected: {r.status_code} {r.text[:200]}")
T1 = A.post(B + "/api/tasks", json={"title": "Export als CSV für Kunden", "list_id": P}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Old style branch", "list_id": P}).json()["id"]
T3 = A.post(B + "/api/tasks", json={"title": "Not this one", "list_id": P}).json()["id"]
cur = ag.get("/agent/events", params={"since": 0}).json().get("cursor", 0)
A.patch(B + f"/api/tasks/{T1}", json={"assignee_id": AG})
ev = until(lambda: [e for e in ag.get("/agent/events", params={"since": cur}).json().get("data", []) if e["event"] == "assigned"], 10)
rp = ev[0]["data"].get("repo") if ev else None
check(rp and rp.get("branch") == f"kalmido-{T1}", f"assigned event: suggested branch kalmido-<id>: {rp and rp.get('branch')}")
j = ag.get(f"/tasks/{T1}").json()
check(j.get("repo", {}).get("branch") == f"kalmido-{T1}", f"get_task: branch {j.get('repo', {}).get('branch')}")
g = STATE["8090"]["acme/app"]
g["pulls"] = [pr(7, "CSV export", f"kalmido-{T1}", "fff777"), pr(8, "Legacy", f"kalmido-{T2}-old-style-branch", "ddd888"),
              pr(9, "Neighbour", f"kalmido-{T3}0", "ccc999")]
put_state()


def code(tid):
    t = next((x for x in A.get(B + "/api/state").json()["tasks"] if x["id"] == tid), None)
    return (t or {}).get("code") or {}


c1 = until(lambda: code(T1).get("prs"), 20)
check(c1 and [p["n"] for p in c1] == [7], f"a pull request on branch kalmido-<id> links: {c1}")
c2 = until(lambda: code(T2).get("prs"), 10)
check(c2 and [p["n"] for p in c2] == [8], f"an old kalmido-<id>-<slug> branch still links: {c2}")
check(not any(p["n"] == 9 for p in code(T3).get("prs", [])), "kalmido-<id>0 is another task, not this one")

subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
print(f"p251_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
