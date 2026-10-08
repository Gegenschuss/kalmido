#!/usr/bin/env python3
"""2.27.0 API tests ("Bugs & polish").
 - #968 the version of the code: index.html carries <meta name="kalmido-version">, /api/version answers "app" (the server's
   version), the page and the client's files are revalidated (Cache-Control: no-cache)
 - #972 a new project of a built-in type starts WITHOUT the type's sections unless asked for (web: sections true, API v1:
   project_type + sections true; sections without a project type or not a boolean: 400); fields / tickets still come along
 - #1001 what lands in your own inbox through the share target (/share) is assigned to you
 - #988 a list in its owner's folder sits for every member where the owner put it (folder + place, "mirrored"), whatever the
   member's own copy says; the owners' folder order comes along (folder_orders, only folders the member sees); a list's
   sort is the list's (sort_mode: owner / list admins, validated; members 403)
 - #999 automatic tidy-up waits until a new task is left alone (KALMIDO_TIDY_QUIET_S, the container restarts with 2 s):
   no event while it is fresh or someone edits it (POST /api/tasks/{id}/editing); the agent's tidy is refused (409) while a
   person edits the task, after people changed it since the event, or with an old base_updated_at; the original text stays
usage: p2270_api_test.py <datadir>"""
import os
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


CUR = {}


def events(hdr, key):
    r = requests.get(V + f"/agent/events?since={CUR.get(key, 0)}", headers=hdr)
    assert r.ok, r.text
    j = r.json()
    CUR[key] = j["cursor"]
    return j["data"]


# own container, tidy waits 2 s (the watchdog ticks every second in the test container)
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env={**os.environ, "KALMIDO_TIDY_QUIET_S": "2"})
s0 = requests.Session()
s0.headers.update(H)
s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"})
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
Bo, Ca = sess("bob"), sess("carol")
ver = open(os.path.join(N, "..", "VERSION")).read().strip()

# ================================================================== #968 the code's version
r = A.get(B + "/")
check(f'<meta name="kalmido-version" content="{ver}">' in r.text, f"#968: index.html names the version of its code {ver}")
check("no-cache" in r.headers.get("Cache-Control", ""), "#968: the page is revalidated")
check(A.get(B + "/api/version").json().get("app") == ver, "#968: /api/version answers app")
r = A.get(B + "/static/js/core.js")
check(r.ok and "no-cache" in r.headers.get("Cache-Control", ""), "#968: the client's code is revalidated " + str(r.headers.get("Cache-Control")))

# ================================================================== #972 projects without the standard sections
st = lambda s: s.get(B + "/api/state").json()  # noqa: E731
P1 = A.post(B + "/api/lists", json={"name": "App", "ptype": "software"}).json()
check(P1.get("kind") == "project" and not [x for x in st(A)["sections"] if x["list_id"] == P1["id"]], "#972: a software project starts without sections")
check(next(x for x in st(A)["lists"] if x["id"] == P1["id"])["tickets"] == 1, "#972: the ticket types still come along")
P2 = A.post(B + "/api/lists", json={"name": "Client", "ptype": "agency", "sections": True}).json()
check([x["name"] for x in st(A)["sections"] if x["list_id"] == P2["id"]] == ["Request", "Concept", "Production", "Approval", "Billing"],
      "#972: with sections true the type's sections")
check(len([f for f in st(A)["fields"] if f["list_id"] == P1["id"]]) == 0 and len([f for f in st(A)["fields"] if f["list_id"] == P2["id"]]) == 2,
      "#972: fields of the type as before")
check(A.post(B + "/api/lists", json={"name": "x", "ptype": "private", "sections": "yes"}).status_code == 400, "#972: sections must be a boolean")
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "structure"]}).json()["token"]
VA = {"Authorization": "Bearer " + tok}
r = requests.post(V + "/lists", headers=VA, json={"name": "Via API", "project_type": "private", "sections": True})
check(r.status_code == 201, "#972: v1 project_type + sections " + r.text[:100])
check([x["name"] for x in st(A)["sections"] if x["list_id"] == r.json()["id"]] == ["Ideas", "Planning", "To do"], "#972: v1: the sections")
r = requests.post(V + "/lists", headers=VA, json={"name": "Via API 2", "project_type": "private"})
check(r.status_code == 201 and not [x for x in st(A)["sections"] if x["list_id"] == r.json()["id"]], "#972: v1 without sections: none")
check(requests.post(V + "/lists", headers=VA, json={"name": "x", "sections": True}).status_code == 400, "#972: v1 sections without a project type: 400")

# ================================================================== #1001 the share target: yours
r = A.post(B + "/share", data={"title": "Shared link", "text": "https://example.com/a"}, allow_redirects=False)
check(r.status_code in (302, 303), "#1001: share target " + str(r.status_code))
me = st(A)["me"]["id"]
t = next((x for x in st(A)["tasks"] if x["title"] == "Shared link"), None)
check(t and t.get("assignee_id") == me, "#1001: a shared item in my inbox is assigned to me " + str(t and t.get("assignee_id")))

# ================================================================== #988 mirrored arrangement
A.patch(B + "/api/settings", json={"folders": '["Zeta", "Alpha", "Private"]'})
L1 = A.post(B + "/api/lists", json={"name": "One", "folder": "Alpha"}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Two", "folder": "Alpha"}).json()["id"]
L3 = A.post(B + "/api/lists", json={"name": "Three", "folder": "Zeta"}).json()["id"]
A.post(B + "/api/lists", json={"name": "Hidden", "folder": "Private"})
for lid in (L1, L2, L3):
    check(A.put(B + f"/api/lists/{lid}/members", json={"user_id": BOB, "role": "edit"}).ok, f"share {lid} with bob")
# bob files them his own way (as before 2.27): another folder and order
Bo.post(B + "/api/lists/reorder", json={"ids": [L3, L2, L1], "folder": {str(L1): "Mine", str(L2): "", str(L3): "Mine"}})
A.post(B + "/api/lists/reorder", json={"ids": [L2, L1, L3]})
bl = {x["id"]: x for x in st(Bo)["lists"]}
check(bl[L1]["folder"] == "Alpha" and bl[L2]["folder"] == "Alpha" and bl[L3]["folder"] == "Zeta" and bl[L1].get("mirrored"),
      "#988: bob sees the lists in the owner's folders " + str([(bl[x]["folder"]) for x in (L1, L2, L3)]))
check(bl[L2]["sort"] < bl[L1]["sort"], "#988: ... in the owner's order")
A.post(B + "/api/lists/reorder", json={"ids": [L1, L2, L3]})
bl = {x["id"]: x for x in st(Bo)["lists"]}
check(bl[L1]["sort"] < bl[L2]["sort"], "#988: the owner moves, bob sees it at once")
fo = st(Bo).get("folder_orders", {})
check(fo.get(str(me)) == ["Zeta", "Alpha"], "#988: bob gets the owner's folder order, only the folders he sees " + str(fo))
check(st(A).get("folder_orders") == {}, "#988: the owner has nothing mirrored")
# a member's own list stays his
B1 = Bo.post(B + "/api/lists", json={"name": "Bob's", "folder": "Mine"}).json()["id"]
check(next(x for x in st(Bo)["lists"] if x["id"] == B1)["folder"] == "Mine", "#988: bob's own list keeps his folder")
# a loose shared list (no folder at the owner): the member's own place
L4 = A.post(B + "/api/lists", json={"name": "Loose"}).json()["id"]
A.put(B + f"/api/lists/{L4}/members", json={"user_id": BOB, "role": "edit"})
Bo.post(B + "/api/lists/reorder", json={"ids": [L4], "folder": {str(L4): "Mine"}})
x = next(x for x in st(Bo)["lists"] if x["id"] == L4)
check(x["folder"] == "Mine" and not x.get("mirrored"), "#988: a list without a folder at its owner stays where the member put it")
# the list's sort for everyone
check(A.patch(B + f"/api/lists/{L1}", json={"sort_mode": "title"}).ok, "#988: the owner sets the list's sort")
check(next(x for x in st(Bo)["lists"] if x["id"] == L1)["sort_mode"] == "title", "#988: bob gets it")
check(Bo.patch(B + f"/api/lists/{L1}", json={"sort_mode": "date"}).status_code == 403, "#988: a member cannot change it")
check(A.patch(B + f"/api/lists/{L1}", json={"sort_mode": "sideways"}).status_code == 400, "#988: unknown sort 400")
check(A.patch(B + f"/api/lists/{L1}", json={"sort_mode": "cf:12"}).ok and A.patch(B + f"/api/lists/{L1}", json={"sort_mode": ""}).ok, "#988: a field sort, back to the default")
A.put(B + f"/api/lists/{L2}/members", json={"user_id": BOB, "role": "admin"})
check(Bo.patch(B + f"/api/lists/{L2}", json={"sort_mode": "date"}).ok, "#988: a list admin may")

# ================================================================== #999 tidy-up waits for quiet
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
T = A.post(B + "/api/lists", json={"name": "Tidy"}).json()["id"]
A.put(B + f"/api/lists/{T}/members", json={"user_id": CL, "role": "edit"})
check(A.patch(B + f"/api/lists/{T}", json={"agent_tidy": "auto"}).ok, "tidy auto")
events(CLH, "cl")
t1 = A.post(B + "/api/tasks", json={"title": "call composer about the temp music license for the trailer next week", "list_id": T, "content": "my notes"}).json()["id"]
t2 = A.post(B + "/api/tasks", json={"title": "second entry typed right now", "list_id": T}).json()["id"]
check(A.post(B + f"/api/tasks/{t2}/editing").json().get("ok"), "#999: the editing signal")
check(not [e for e in events(CLH, "cl") if e["event"] == "tidy"], "#999: no tidy event while the task is fresh")
got = []
for _ in range(20):
    time.sleep(0.5)
    got += [e for e in events(CLH, "cl") if e["event"] == "tidy"]
    if got:
        break
time.sleep(1.5)
got += [e for e in events(CLH, "cl") if e["event"] == "tidy"]
check([e["data"]["task"]["id"] for e in got] == [t1], "#999: the tidy event once it is quiet, not for the task being edited " + str([e["data"]["task"]["id"] for e in got]))
check(got and got[0]["actor"] and got[0]["actor"]["id"] == me and got[0]["actor"]["kind"] == "person", "#999: actor = the person who created it")
# a person changed it after the event: refused
A.patch(B + f"/api/tasks/{t1}", json={"content": "my notes, longer now"})
r = requests.post(V + f"/tasks/{t1}/tidy", headers=CLH, json={"title": "Call composer"})
check(r.status_code == 409, "#999: changed since the event: 409 " + str(r.status_code))
check(next(x for x in st(A)["tasks"] if x["id"] == t1)["content"] == "my notes, longer now", "#999: the person's text untouched")
# while someone edits: refused
t3 = A.post(B + "/api/tasks", json={"title": "third one", "list_id": T}).json()["id"]
time.sleep(3)
cur = requests.get(V + f"/tasks/{t3}", headers=CLH).json()
r = requests.post(V + f"/tasks/{t3}/tidy", headers=CLH, json={"title": "Third", "base_updated_at": "2000-01-01T00:00:00+00:00"})
check(r.status_code == 409, "#999: an old base_updated_at: 409")
A.post(B + f"/api/tasks/{t3}/editing")
r = requests.post(V + f"/tasks/{t3}/tidy", headers=CLH, json={"title": "Third"})
check(r.status_code == 409, "#999: while a person edits: 409")
# quiet + unchanged: applied, the original kept
t4 = A.post(B + "/api/tasks", json={"title": "fourth entry with a long title", "list_id": T, "content": "keep me"}).json()["id"]
time.sleep(3)
upd = requests.get(V + f"/tasks/{t4}", headers=CLH).json().get("updated_at")
r = requests.post(V + f"/tasks/{t4}/tidy", headers=CLH, json={"title": "Fourth", "base_updated_at": upd})
check(r.ok, "#999: quiet and unchanged: applied " + r.text[:120])
x = next(x for x in st(A)["tasks"] if x["id"] == t4)
check(x["title"] == "Fourth" and "keep me" in x["content"] and "fourth entry with a long title" in x["content"], "#999: the original text stays")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
