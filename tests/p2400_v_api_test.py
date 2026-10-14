#!/usr/bin/env python3
"""2.40.0 API tests (agent V).
 - #1190 the progress bar of projects is off by default: the user setting show_progress (comma list of project ids switched on)
 - #1334 group_order is bounded: route keys and group ids up to 60 characters, 200 groups per view, the newest 40 views
 - #1361 favourites: PUT / DELETE /api/lists/{id}/favorite for the own person (settings.fav_lists), 404 for a list one cannot
   see, another member notices nothing, agents never; fav_only, fav_views validated
 - #1344 My tasks in an own order: PUT /api/tasks/mine-order (state mine_order), tasks.sort unchanged, foreign tasks skipped,
   a newly assigned task loses its place (stands on top), per person, agents never; mine_view own | lists
usage: p2400_v_api_test.py <datadir>"""
import json
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


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
check(r.ok, "a second person " + r.text[:200])
BOB = r.json().get("id")
Bo = sess("bob")
st = lambda s: s.get(B + "/api/state").json()

PRJ = A.post(B + "/api/lists", json={"name": "Launch", "kind": "project"}).json()["id"]
TEAM = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]
A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": BOB, "role": "edit"})
BOBL = Bo.post(B + "/api/lists", json={"name": "Bob private"}).json()["id"]

# ================= #1190 show_progress
s = st(A)["settings"]
check(s.get("show_progress") == "", "#1190: no project switched on by default " + repr(s.get("show_progress")))
check(A.patch(B + "/api/settings", json={"show_progress": f"{PRJ},{PRJ}"}).ok and st(A)["settings"]["show_progress"] == str(PRJ), "#1190: switched on, stored once")
check(A.patch(B + "/api/settings", json={"show_progress": "x,1"}).status_code == 400, "#1190: only ids")
check(st(Bo)["settings"]["show_progress"] == "", "#1190: per person")

# ================= #1334 group_order bounds
go = {f"v{i}": [f"l:{j}" for j in range(250)] + ["x" * 61] for i in range(50)}
go["y" * 61] = ["l:1"]
r = A.patch(B + "/api/settings", json={"group_order": json.dumps(go)})
check(r.ok, "#1334: too much is cut, not refused " + r.text[:200])
g2 = json.loads(st(A)["settings"]["group_order"])
check(len(g2) == 40 and list(g2)[0] == "v10" and list(g2)[-1] == "v49", "#1334: the newest 40 views stay " + str(list(g2)[:2]))
check(max(len(v) for v in g2.values()) == 200 and not any(len(x) > 60 for v in g2.values() for x in v), "#1334: 200 groups, ids up to 60 characters")
check(not any(len(k) > 60 for k in g2), "#1334: route keys up to 60 characters")
check(A.patch(B + "/api/settings", json={"group_order": json.dumps({"assigned": "l:1"})}).status_code == 400, "#1334: a malformed value stays refused")
A.patch(B + "/api/settings", json={"group_order": ""})

# ================= #1361 favourites
r = A.put(B + f"/api/lists/{TEAM}/favorite", json={"on": True})
check(r.ok and r.json().get("favorite") is True and r.json().get("fav_lists") == str(TEAM), "#1361: star set " + r.text[:200])
A.put(B + f"/api/lists/{PRJ}/favorite", json={})
check(st(A)["settings"]["fav_lists"] == f"{TEAM},{PRJ}", "#1361: in the order they were starred, in the state")
check(st(Bo)["settings"]["fav_lists"] == "", "#1361: the other member of the list notices nothing")
check(A.put(B + f"/api/lists/{BOBL}/favorite", json={}).status_code == 404, "#1361: a list one cannot see: 404")
check(A.put(B + "/api/lists/999999/favorite", json={}).status_code == 404, "#1361: no such list: 404")
r = A.delete(B + f"/api/lists/{TEAM}/favorite")
check(r.ok and r.json().get("favorite") is False and st(A)["settings"]["fav_lists"] == str(PRJ), "#1361: DELETE removes the star")
r = A.put(B + f"/api/lists/{PRJ}/favorite", json={"on": False})
check(r.ok and st(A)["settings"]["fav_lists"] == "", "#1361: {on: false} removes it too")
check(Bo.put(B + f"/api/lists/{TEAM}/favorite", json={}).ok and st(Bo)["settings"]["fav_lists"] == str(TEAM) and st(A)["settings"]["fav_lists"] == "",
      "#1361: bob's star is his own")
check(A.patch(B + "/api/settings", json={"fav_only": "1", "fav_views": "today,assigned,today"}).ok, "#1361: fav_only, fav_views")
s = st(A)["settings"]
check(s["fav_only"] == "1" and s["fav_views"] == "today,assigned", "#1361: stored (without doubles) " + s["fav_views"])
check(A.patch(B + "/api/settings", json={"fav_views": "To day"}).status_code == 400, "#1361: fav_views: only view keys")
check(A.patch(B + "/api/settings", json={"fav_only": "2"}).status_code == 400, "#1361: fav_only is a switch")
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "structure"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag.get("token", "x")}
A.put(B + f"/api/lists/{TEAM}/members", json={"user_id": ag.get("id"), "role": "edit"})
check(requests.put(B + f"/api/lists/{TEAM}/favorite", headers={**AGH, **H}, json={}).status_code in (401, 403, 404), "#1361: an agent has no favourites")
lv1 = requests.get(B + "/api/v1/lists", headers=AGH).json()
check("fav" not in json.dumps(lv1), "#1361: the agent API shows no stars")

# ================= #1344 My tasks in an own order
mk = lambda s, title, lid, **kw: s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw}).json()["id"]
me = st(A)["me"]["id"]
T1, T2, T3 = mk(A, "One", TEAM, assignee_id=me), mk(A, "Two", TEAM, assignee_id=me), mk(A, "Three", PRJ, assignee_id=me)
BT = mk(Bo, "Bob only", BOBL)
check(st(A)["settings"].get("mine_view") == "own" and st(A).get("mine_order") == {}, "#1344: own order by default, nothing placed yet")
sort0 = {t["id"]: t["sort"] for t in st(A)["tasks"]}
r = A.put(B + "/api/tasks/mine-order", json={"ids": [T3, BT, T1, 999999, T2]})
check(r.ok and r.json().get("count") == 3, "#1344: stored, foreign / unknown ids skipped " + r.text[:200])
mo = st(A)["mine_order"]
check(mo == {str(T3): 0, str(T1): 1, str(T2): 2}, "#1344: mine_order in the state " + json.dumps(mo))
check({t["id"]: t["sort"] for t in st(A)["tasks"]} == sort0, "#1344: tasks.sort unchanged")
check(st(Bo).get("mine_order") == {}, "#1344: per person")
check(A.put(B + "/api/tasks/mine-order", json={"ids": "x"}).status_code == 400 and A.put(B + "/api/tasks/mine-order", json={"ids": [1, "2"]}).status_code == 400,
      "#1344: only a list of ids")
r = A.patch(B + f"/api/tasks/{T2}", json={"assignee_id": BOB})
r = A.patch(B + f"/api/tasks/{T2}", json={"assignee_id": me})
check(r.ok and str(T2) not in st(A)["mine_order"], "#1344: newly assigned = no place yet (on top)")
check(requests.put(B + "/api/tasks/mine-order", headers={**AGH, **H}, json={"ids": [T1]}).status_code in (401, 403, 404), "#1344: an agent has no own order")
check(A.patch(B + "/api/settings", json={"mine_view": "lists"}).ok and st(A)["settings"]["mine_view"] == "lists", "#1344: grouped by list")
check(A.patch(B + "/api/settings", json={"mine_view": "date"}).status_code == 400, "#1344: mine_view own | lists")
check(A.put(B + "/api/tasks/mine-order", json={"ids": []}).ok and st(A)["mine_order"] == {}, "#1344: an empty order resets it")

print(f"{OKS[0]} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
