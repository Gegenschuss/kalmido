#!/usr/bin/env python3
"""2.29.0 API tests ("Folders like lists, calm agents").
 - #1026 search engines stay out: X-Robots-Tag noindex on every answer, /robots.txt "Disallow: /" (was a redirect to the
   sign-in page)
 - #1031 no backlog storm: since=latest starts from now; events older than a day come as one 'missed' summary; more than five
   tasks added to one list by one person in a minute become ONE 'tasks_added' event; bulk-created tasks get no tidy event
   each
 - #1029 the permission mode of an agent (runtime.permission_mode ask | auto | ''): the admin's runtime section, the owner of a
   personal agent, the chat header's switch (PUT /api/agents/<aid>/permission-mode: owner / admin for a team agent, 403
   for others), runtime_changed to the agent, GET /api/v1/agent shows it
 - #1030 / #929 folder settings: defaults (workspace, agent, members may use it, tidy) for the lists in a folder and its
   subfolders, apply to all / only new, a dry run names the lists that cannot follow, a list changed on its own keeps its
   value (folder_own) until "Back to the folder", a new list and a list moved into the folder take them; folder people with
   every role (admin too), a changed role reaches the lists, removing can take the person out of the lists; a list someone
   creates in a folder shared with them is shared with the folder's owner and people
usage: p2290_api_test.py <datadir>"""
import os
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
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


def dbx(sql, args=(), write=False):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def state(s):
    return s.get(B + "/api/state").json()


def lists_of(s):
    return {l["id"]: l for l in state(s)["lists"]}


def members(s, lid):
    return {m["user_id"]: m["role"] for m in lists_of(s)[lid].get("members", [])}


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en"})
ME = state(A)["me"]
ORG = ME["workspaces"][0]["id"]

# ================================================================== #1026 noindex
r = requests.get(B + "/robots.txt", allow_redirects=False)
check(r.status_code == 200 and "Disallow: /" in r.text and r.headers.get("Content-Type", "").startswith("text/plain"), "#1026: /robots.txt says Disallow: / " + str(r.status_code) + r.text[:60])
for path in ("/", "/api/health", "/manifest.json"):
    check("noindex" in requests.get(B + path).headers.get("X-Robots-Tag", ""), f"#1026: X-Robots-Tag noindex on {path}")
check("noindex" in A.get(B + "/api/state").headers.get("X-Robots-Tag", ""), "#1026: ... and on the API")

# ================================================================== #1029 permission mode
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
j = requests.get(V + "/agent", headers=CLH).json()
check(j["runtime"].get("permission_mode") == "", "#1029: the permission mode starts as the host's default " + str(j["runtime"]))
cur0 = requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]
r = A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"permission_mode": "auto"}})
check(r.ok and requests.get(V + "/agent", headers=CLH).json()["runtime"]["permission_mode"] == "auto", "#1029: the admin sets it in the runtime section " + r.text[:80])
ev = requests.get(V + f"/agent/events?since={cur0}", headers=CLH).json()["data"]
check(any(e["event"] == "runtime_changed" and e["data"]["runtime"]["permission_mode"] == "auto" for e in ev), "#1029: runtime_changed tells the agent")
check(A.patch(B + f"/api/admin/agents/{CL}", json={"runtime": {"permission_mode": "yolo"}}).status_code == 400, "#1029: unknown modes are refused")
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()
A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": CL, "role": "edit"})
A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": BOB, "role": "admin"})
A.patch(B + f"/api/lists/{W['id']}", json={"agent_members": True})
A.patch(B + f"/api/lists/{W['id']}", json={"listen_agent_ids": [CL]})  # 2.30.0 (#1034): task_added only where the agent listens in
ag = {a["id"]: a for a in A.get(B + "/api/agents").json()["agents"]}
check(ag[CL]["permission_mode"] == "auto" and ag[CL]["may_set_mode"] is True, "#1029: the chat header knows the mode and that the admin may switch it " + str({k: ag[CL].get(k) for k in ("permission_mode", "may_set_mode")}))
r = A.put(B + f"/api/agents/{CL}/permission-mode", json={"mode": "ask"})
check(r.ok and r.json()["permission_mode"] == "ask", "#1029: the admin switches a team agent in the chat header " + r.text[:80])
bag = {a["id"]: a for a in Bo.get(B + "/api/agents").json()["agents"]}
check(CL in bag and bag[CL]["may_set_mode"] is False and bag[CL]["permission_mode"] == "ask", "#1029: a member sees the mode but may not switch it")
check(Bo.put(B + f"/api/agents/{CL}/permission-mode", json={"mode": "auto"}).status_code == 403, "#1029: ... a member's switch is refused")
check(Ca.put(B + f"/api/agents/{CL}/permission-mode", json={"mode": "auto"}).status_code == 404, "#1029: someone without the agent does not find it")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2})
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "display_name": "Bob's bot"})
check(r.ok, "#1029: a personal agent " + r.text[:80])
BB = r.json()["id"]
r = Bo.patch(B + f"/api/my/agents/{BB}", json={"runtime": {"permission_mode": "auto", "model": "sonnet"}})
check(r.ok, "#1029: the owner sets the runtime of a personal agent " + r.text[:80])
check(Bo.put(B + f"/api/agents/{BB}/permission-mode", json={"mode": "ask"}).ok, "#1029: ... and switches its mode in the chat header")

# ================================================================== #1031 no backlog storm
EV = requests.get(V + "/agent/events?since=latest", headers=CLH).json()
check(EV["data"] == [] and EV["cursor"] >= 1, "#1031: since=latest -> no events, the newest cursor " + str(EV)[:120])
cur = EV["cursor"]
# events older than a day -> one 'missed' summary
for i in range(3):
    Bo.post(B + "/api/tasks", json={"title": f"old {i} @claude", "list_id": W["id"]})
# two days old (older than AGENT_EVENTS_STALE_H) - three days than the 30 days events are kept)
OLD = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 3 * 86400))
dbx("UPDATE agent_events SET created_at=? WHERE agent_id=? AND id>?", (OLD, CL, cur), write=True)
Bo.post(B + "/api/tasks", json={"title": "fresh @claude", "list_id": W["id"]})
j = requests.get(V + f"/agent/events?since={cur}", headers=CLH).json()
evs = j["data"]
check(evs and evs[0]["event"] == "missed" and evs[0]["data"]["count"] >= 3 and evs[0]["data"]["events"], "#1031: old events come as ONE 'missed' summary " + str(evs[:1])[:200])
check(any(e["event"] in ("mention", "task_added") and "fresh" in str(e["data"]) for e in evs[1:]) and not any("old 1" in str(e["data"]) for e in evs[1:]), "#1031: ... the fresh ones one by one after it")
j2 = requests.get(V + f"/agent/events?since={j['cursor']}", headers=CLH).json()
check(not any(e["event"] == "missed" for e in j2["data"]), "#1031: the summary comes once (the cursor moves past it)")
cur = j2["cursor"] if j2["data"] else j["cursor"]
# a bulk: 9 tasks into one list within a minute -> at most 5 single task_added, then one tasks_added
for i in range(9):
    Bo.post(B + "/api/tasks", json={"title": f"bulk {i}", "list_id": W["id"]})
time.sleep(18)  # AGENT_BURST_QUIET_S = 15 + the watchdog tick
evs = requests.get(V + f"/agent/events?since={cur}&limit=200", headers=CLH).json()["data"]
single = [e for e in evs if e["event"] == "task_added"]
bulk = [e for e in evs if e["event"] == "tasks_added"]
check(len(single) <= 5, f"#1031: at most five single task_added in a burst ({len(single)})")
check(len(bulk) == 1 and bulk[0]["data"]["count"] == 9 - len(single) and bulk[0]["data"]["list_id"] == W["id"] and bulk[0]["data"]["how"] == "created", "#1031: ... the rest as ONE tasks_added " + str(bulk)[:200])
check(bulk and bulk[0]["actor"]["id"] == BOB, "#1031: ... with the person who did it")
# a bulk move via the multi-select batch
W2 = A.post(B + "/api/lists", json={"name": "Elsewhere", "org_id": ORG}).json()
A.put(B + f"/api/lists/{W2['id']}/members", json={"user_id": BOB, "role": "edit"})
tids = [Bo.post(B + "/api/tasks", json={"title": f"mv {i}", "list_id": W2["id"]}).json()["id"] for i in range(8)]
time.sleep(1)
cur = requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]
r = Bo.post(B + "/api/tasks/batch", json={"ids": tids, "action": "patch", "data": {"list_id": W["id"]}})
check(r.ok, "#1031: batch move " + r.text[:80])
time.sleep(18)
evs = requests.get(V + f"/agent/events?since={cur}&limit=200", headers=CLH).json()["data"]
check(len([e for e in evs if e["event"] == "task_added"]) <= 5 and any(e["event"] == "tasks_added" and e["data"]["how"] == "moved" for e in evs),
      "#1031: a bulk move: a few single events, then one tasks_added (moved) " + str([e["event"] for e in evs]))
# tidy: bulk-created tasks get no tidy event each
A.patch(B + f"/api/lists/{W['id']}", json={"agent_tidy": "suggest"})
cur = requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]
time.sleep(61)  # a new burst window
for i in range(9):
    Bo.post(B + "/api/tasks", json={"title": f"tidy bulk {i}", "list_id": W["id"]})
time.sleep(3)
evs = requests.get(V + f"/agent/events?since={cur}&limit=200", headers=CLH).json()["data"]
check(len([e for e in evs if e["event"] == "tidy"]) == 9, "#1031: typing in the app keeps every tidy event " + str(len([e for e in evs if e["event"] == "tidy"])))
# ... tasks created in bulk through the API: at most five tidy events
r = Bo.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "write"]})
if r.ok and r.json().get("token"):
    BT = {"Authorization": "Bearer " + r.json()["token"]}
    time.sleep(61)
    cur = requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]
    for i in range(9):
        requests.post(V + "/tasks", headers=BT, json={"title": f"api bulk {i}", "list_id": W["id"]})
    time.sleep(3)
    evs = requests.get(V + f"/agent/events?since={cur}&limit=200", headers=CLH).json()["data"]
    check(len([e for e in evs if e["event"] == "tidy"]) <= 5, "#1031: bulk through the API: at most five tidy events " + str(len([e for e in evs if e["event"] == "tidy"])))
else:
    check(False, "#1031: a personal API token for the bulk test " + r.text[:100])
A.patch(B + f"/api/lists/{W['id']}", json={"agent_tidy": "off"})

# ================================================================== #1030 / #929 folder settings
L1 = A.post(B + "/api/lists", json={"name": "C1", "folder": "Clients", "org_id": None}).json()
L2 = A.post(B + "/api/lists", json={"name": "C2", "folder": "Clients/Sub", "org_id": None}).json()
L3 = A.post(B + "/api/lists", json={"name": "C3", "folder": "Clients", "org_id": None}).json()
A.put(B + f"/api/lists/{L3['id']}/members", json={"user_id": CAROL, "role": "edit"})  # Carol is a member of the organisation too
r = A.get(B + "/api/folders/props?folder=Clients")
check(r.ok and r.json()["props"] == {} and len(r.json()["lists"]) == 3, "#1030: a folder without settings, its lists (subfolder included) " + r.text[:120])
# dry run: the workspace
r = A.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"org_id": ORG}, "dry_run": True})
check(r.ok and r.json()["dry_run"] and r.json()["changed"] == 3, "#1030: dry run: three lists would move into the organisation " + r.text[:200])
check(A.get(B + "/api/folders/props?folder=Clients").json()["props"] == {} and lists_of(A)[L1["id"]]["org_id"] is None, "#1030: ... and nothing changed")
r = A.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"org_id": ORG, "agent_id": CL, "agent_members": True}})
check(r.ok and r.json()["props"]["org_id"] == ORG, "#1030: the folder's workspace + agent " + r.text[:200])
ls = lists_of(A)
check(all(ls[x["id"]]["org_id"] == ORG for x in (L1, L2, L3)), "#1030: every list of the folder and its subfolder is the organisation's")
# 2.30.0 (#919): C3 (Alice + Carol) and Work (Alice + Bob) through one agent would be a bridge: the folder skips C3, its
# owner confirms it in the list itself
check(any(x["id"] == L3["id"] for x in r.json().get("skipped", r.json().get("lists", []))) or CL not in members(A, L3["id"]), "2.30.0: the folder leaves the bridge list out " + r.text[:300])
check(A.put(B + f"/api/lists/{L3['id']}/agent", json={"agent_id": CL, "bridge_ok": True}).ok, "2.30.0: ... confirmed in the list")
check(all(CL in members(A, x["id"]) for x in (L1, L2, L3)) and all(ls[x["id"]]["agent_members"] for x in (L1, L2)), "#929: the folder's agent joined every list, Members may use it on")
# a new list in the folder
N1 = A.post(B + "/api/lists", json={"name": "N1", "folder": "Clients"}).json()
check(lists_of(A)[N1["id"]]["org_id"] == ORG and CL in members(A, N1["id"]), "#1030: a new list in the folder takes its settings")
# a list on its own keeps its value
r = A.patch(B + f"/api/lists/{L1['id']}", json={"agent_members": False})
check(r.ok and "agent_members" in (lists_of(A)[L1["id"]].get("folder_own") or ""), "#1030: a list changed on its own differs from the folder " + str(lists_of(A)[L1["id"]].get("folder_own")))
r = A.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"agent_members": True, "agent_tidy": "suggest"}, "dry_run": True})
own = [x for x in r.json()["lists"] if x["id"] == L1["id"]]
check(own and "agent_members" in own[0]["own"], "#1030: the dry run names the list that keeps its own value " + str(r.json()["lists"])[:200])
A.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"agent_tidy": "suggest"}})
ls = lists_of(A)
check(ls[L1["id"]]["agent_members"] == 0 and ls[L3["id"]]["agent_tidy"] == "suggest", "#1030: the folder changed, the list kept its own value, the others follow")
r = A.post(B + f"/api/lists/{L1['id']}/folder-reset", json={})
check(r.ok and lists_of(A)[L1["id"]]["agent_members"] == 1 and lists_of(A)[L1["id"]]["folder_own"] in ("[]", ""), "#1030: Back to the folder " + r.text[:100])
check(Bo.post(B + f"/api/lists/{L1['id']}/folder-reset", json={}).status_code in (403, 404), "#1030: only the owner resets a list")
# only new lists
A.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"agent_tidy": "off"}, "apply": "new"})
check(lists_of(A)[L3["id"]]["agent_tidy"] == "suggest", "#1030: apply new: the existing lists stay")
N2 = A.post(B + "/api/lists", json={"name": "N2", "folder": "Clients"}).json()
check(lists_of(A)[N2["id"]]["agent_tidy"] in ("off", None, ""), "#1030: ... a new list takes the new value")
# the subfolder overrides the top folder
A.put(B + "/api/folders/props", json={"folder": "Clients/Sub", "props": {"org_id": 0}})
check(lists_of(A)[L2["id"]]["org_id"] is None or CL in members(A, L2["id"]), "#1030: a subfolder's own workspace (private) -- the organisation's agent keeps it in the organisation (named)")
inf = A.get(B + "/api/folders/props?folder=Clients/Sub").json()
check(inf["props"].get("org_id") == 0 and "agent_id" in inf["inherited"], "#1030: a subfolder knows what it inherits " + str(inf)[:200])
# a list moved into the folder
M = A.post(B + "/api/lists", json={"name": "Mover", "org_id": None}).json()
A.patch(B + f"/api/lists/{M['id']}", json={"folder": "Clients"})
check(lists_of(A)[M["id"]]["org_id"] == ORG and CL in members(A, M["id"]), "#1030: a list moved into the folder takes its settings")
M2 = A.post(B + "/api/lists", json={"name": "Dragged", "org_id": None}).json()
A.post(B + "/api/lists/reorder", json={"ids": [M2["id"]], "folder": {str(M2["id"]): "Clients"}})
check(lists_of(A)[M2["id"]]["org_id"] == ORG, "#1030: ... also dragged in the sidebar")
# validation
check(A.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"color": "red"}}).status_code == 400, "#1030: unknown settings are refused")
check(A.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"org_id": 999}}).status_code == 409, "#1030: a workspace one does not belong to is refused")
check(A.put(B + "/api/folders/props", json={"folder": "", "props": {}}).status_code == 400, "#1030: a folder is needed")

# ---- #929 folder people: every role, a changed role reaches the lists, removing
r = A.put(B + "/api/folders/people", json={"folder": "Clients", "user_id": BOB, "role": "admin"})
check(r.ok and r.json()["shared"] >= 3, "#929: share the folder with an admin " + r.text[:100])
check(members(A, L1["id"]).get(BOB) == "admin", "#929: ... Bob is a list admin of its lists")
check(A.put(B + "/api/folders/people", json={"folder": "Clients", "user_id": CL, "role": "admin"}).status_code == 400, "#929: an agent is never a list admin through a folder")
r = A.put(B + "/api/folders/people", json={"folder": "Clients", "user_id": BOB, "role": "view"})
check(r.ok and r.json()["updated"] >= 3 and members(A, L1["id"]).get(BOB) == "view", "#929: a changed folder role reaches the lists " + r.text[:100])
A.put(B + "/api/folders/people", json={"folder": "Clients", "user_id": BOB, "role": "edit"})
# a list Bob creates in the folder shared with him: stays his, shared with Alice (admin) + the folder's people
A.put(B + "/api/folders/people", json={"folder": "Clients", "user_id": CAROL, "role": "participant"})
bl = {l["id"]: l for l in state(Bo)["lists"]}
check(bl[L1["id"]]["m_folder"] if "m_folder" in bl[L1["id"]] else True, "#929: Bob sees the folder")
sh = state(Bo).get("folders_shared_in") or []
check(any(x["folder"] == "Clients" and x["owner_id"] == ME["id"] for x in sh), "#929: the state names the folders shared with Bob " + str(sh))
BL = Bo.post(B + "/api/lists", json={"name": "Bob's", "folder": "Clients"}).json()
m = members(Bo, BL["id"])
check(BL.get("owner_id") == BOB and m.get(ME["id"]) == "admin" and m.get(CAROL) == "participant", "#929: Bob's new list in the shared folder is shared with Alice (admin) and Carol " + str(m))
# removing: only new lists / also from the lists
r = A.delete(B + "/api/folders/people", json={"folder": "Clients", "user_id": CAROL})
check(r.ok and CAROL in members(A, L3["id"]), "#929: stop sharing new lists: the lists stay")
A.put(B + "/api/folders/people", json={"folder": "Clients", "user_id": CAROL, "role": "edit"})
r = A.delete(B + "/api/folders/people", json={"folder": "Clients", "user_id": CAROL, "remove": True})
check(r.ok and r.json()["removed"] >= 3 and CAROL not in members(A, L3["id"]), "#929: also from the lists: Carol leaves them " + r.text[:100])
check(not any(l["id"] == L3["id"] for l in state(Ca)["lists"]), "#929: ... Carol no longer sees them")

print(f"p2290_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
