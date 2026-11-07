#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.624.0 B (#4521) the agent's queue in bundles by points, own container. Invented people only (example.com).
tenant-matrix: agent
freelancer-matrix: agents
 - every item of GET /api/v1/agent/queue carries size (S / M / L from the field Size of a software project, null without)
   and points (S=1, M=2, L=3, none = 2); a renamed Size field still counts, another selection field does not
 - ?points=N: the first items in queue order whose points stay within N are bundle: true, the rest false, bundle {points,
   sum, count}; a first item above N alone is the bundle; the agent's own order decides
 - points not a whole number 1..10000 = 400; without points no bundle fields (as before); the owner's route unchanged
 - a person without an organisation: the own agent's queue with points, the same rules
usage: p2624_b_queue_points_test.py <datadir>      (P2624B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # shared helpers (tests/kt.py)


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


if os.environ.get("P2624B_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
feats = set(((A.get(B + "/api/state").json().get("settings") or {}).get("features") or "").split(",")) - {""}
assert A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": ",".join(sorted(feats | {"agents", "fields"}))}).ok
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]

ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "pbot", "display_name": "Pbot"}).json()
AG, T = ag["id"], bearer(ag["token"])
A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": ORG})


def soft_list(s, name, agent):
    r = s.post(B + "/api/lists", json={"name": name, "ptype": "software", "org_id": ORG} if s is A else {"name": name, "ptype": "software"})
    assert r.ok, r.text
    lid = r.json()["id"]
    assert s.put(B + f"/api/lists/{lid}/members", json={"user_id": agent, "role": "edit"}).ok
    size = next(f for f in s.get(B + "/api/state").json()["fields"] if f["list_id"] == lid and f["type"] == "select")
    return lid, size["id"]


def task(s, lid, title, prio, assignee, fields=None):
    b = {"title": title, "list_id": lid, "priority": prio, "assignee_id": assignee}
    if fields:
        b["fields"] = fields
    r = s.post(B + "/api/tasks", json=b)
    assert r.ok, r.text
    return r.json()["id"]


def queue(s, url, params=None):
    r = s.get(url, params=params)
    check(r.ok, f"GET {url} {params}: {r.status_code} {r.text[:200]}")
    return r.json() if r.ok else {"items": []}


def ids(q):
    return [x["task_id"] for x in q.get("items") or []]


def marks(q):
    return [x.get("bundle") for x in q.get("items") or []]


L, SZ = soft_list(A, "App", AG)
TS = task(A, L, "Small", 7, AG, {str(SZ): "s"})
TM = task(A, L, "Medium", 5, AG, {str(SZ): "m"})
TL = task(A, L, "Large", 3, AG, {str(SZ): "l"})
TN = task(A, L, "No size", 1, AG)
# another selection field of the list is not the size
PICK = A.post(B + f"/api/lists/{L}/fields", json={"name": "Pick", "type": "select", "options": {"options": [{"name": "One"}]}}).json()
PO = PICK["options"]["options"][0]["id"]
check(A.patch(B + f"/api/tasks/{TN}", json={"fields": {str(PICK["id"]): PO}}).ok, "another selection field set on the task without a size")

# ---------------------------------------------------------------- sizes and points, no bundle without points
q = queue(T, V + "/agent/queue")
check(ids(q) == [TS, TM, TL, TN], f"queue order by priority: {ids(q)}")
check([x.get("size") for x in q["items"]] == ["S", "M", "L", None] and [x.get("points") for x in q["items"]] == [1, 2, 3, 2],
      f"size + points per item (none = 2): {[(x.get('size'), x.get('points')) for x in q['items']]}")
check("bundle" not in q and all("bundle" not in x for x in q["items"]), f"without points: no bundle fields {q}")

# ---------------------------------------------------------------- bundles
for n, want, total in ((1, [True, False, False, False], 1), (3, [True, True, False, False], 3), (4, [True, True, False, False], 3),
                       (6, [True, True, True, False], 6), (8, [True, True, True, True], 8), (100, [True] * 4, 8)):
    q = queue(T, V + "/agent/queue", {"points": n})
    check(marks(q) == want and q.get("bundle") == {"points": n, "sum": total, "count": want.count(True)},
          f"points={n}: {marks(q)} {q.get('bundle')}")
# the bundle stops at the first item that does not fit (no skipping ahead): L first, then S
r = T.put(V + "/agent/queue", json={"order": [TL, TS]})
check(r.ok and ids(r.json()) == [TL, TS, TM, TN] and "bundle" not in r.json(), f"own order, PUT answer without bundle {r.status_code} {r.text[:200]}")
q = queue(T, V + "/agent/queue", {"points": 2})
check(marks(q) == [True, False, False, False] and q.get("bundle") == {"points": 2, "sum": 3, "count": 1},
      f"a first item above N alone is the bundle: {marks(q)} {q.get('bundle')}")
q = queue(T, V + "/agent/queue", {"points": 5})
check(marks(q) == [True, True, False, False] and q["bundle"]["sum"] == 4, f"points=5 in the own order: {marks(q)} {q.get('bundle')}")

# a renamed Size field still counts (the options decide, not the name)
check(A.patch(B + f"/api/fields/{SZ}", json={"name": "Effort"}).ok, "rename the field Size")
q = queue(T, V + "/agent/queue")
check([x.get("points") for x in q["items"]] == [3, 1, 2, 2], f"renamed field still counts: {[x.get('points') for x in q['items']]}")

# ---------------------------------------------------------------- bad values
for bad in ("0", "-1", "abc", "1.5", "10001", "", "2,3"):
    r = T.get(V + "/agent/queue", params={"points": bad})
    check(r.status_code == 400, f"points={bad!r}: 400 ({r.status_code})")
check(T.get(V + "/agent/queue", params={"limit": 2}).status_code == 400, "an unknown parameter stays 400")

# ---------------------------------------------------------------- the owner's route: the same items with size + points
q = queue(A, B + f"/api/agents/{AG}/queue")
check(ids(q) == [TL, TS, TM, TN] and [x.get("size") for x in q["items"]] == ["L", "S", "M", None] and "bundle" not in q,
      f"the admin's view carries size + points, no bundle {q}")

# ---------------------------------------------------------------- a person without an organisation, own agent
# freelancer-matrix: agents
FID, F = freelancer(B, A)
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
fa = F.post(B + "/api/my/agents", json={"username": "fbot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]})
check(fa.status_code in (200, 201), f"freelancer: an own agent {fa.status_code} {fa.text[:200]}")
FA = fa.json().get("id")
FT = bearer(F.post(B + f"/api/my/agents/{FA}/token").json().get("token", ""))
FL, FSZ = soft_list(F, "Private app", FA)
F1 = task(F, FL, "Offer", 5, FA, {str(FSZ): "l"})
F2 = task(F, FL, "Invoice", 3, FA, {str(FSZ): "s"})
F3 = task(F, FL, "Mail", 1, FA)
q = queue(FT, V + "/agent/queue", {"points": 4})
check(ids(q) == [F1, F2, F3] and [x.get("points") for x in q["items"]] == [3, 1, 2] and marks(q) == [True, True, False]
      and q.get("bundle") == {"points": 4, "sum": 4, "count": 2}, f"freelancer: the own agent's bundle {q}")
check(FT.get(V + "/agent/queue", params={"points": "x"}).status_code == 400, "freelancer: a bad points value 400")
check(TS not in ids(q) and F1 not in ids(queue(T, V + "/agent/queue", {"points": 100})), "freelancer and organisation queues stay apart")

print(f"p2624_b_queue_points: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
