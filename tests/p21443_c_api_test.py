#!/usr/bin/env python3
"""2.144.3 C API tests (#2405, #2420, #2396). freelancer-matrix: news
 - an agent's approval request that waits for me counts in the bell number (unread_me) and is flagged to_me
 - the organisation's card counts people only (2 people + 1 agent -> 2), in the admin list and in "my organisations"
 - the Mac icon (1024 px) is linked in the page head and served as a 1024 x 1024 PNG
 - a person without an organisation: the same approval counts in the bell number
usage: p21443_c_api_test.py <datadir>      (P21443C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
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


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall() if q.lstrip().upper().startswith("SELECT") else c.execute(q, args)
        if write:
            c.commit()
        return r
    finally:
        c.close()


def hdr(token):
    return {"Authorization": "Bearer " + token, "X-Requested-With": "kalmido"}


if os.environ.get("P21443C_NOSTART") != "1":
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "notify": {"approval": {"news": 1}}})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
me = A.get(B + "/api/state").json()["me"]
ORG, ALICE = me["workspaces"][0]["id"], me["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123",
                                   "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "delete", "structure"],
                                          "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
CL, CLH = r.json()["id"], hdr(r.json()["token"])
A.patch(B + f"/api/admin/agents/{CL}", json={"org_id": ORG})
W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
W3 = A.post(B + "/api/lists", json={"name": "Elsewhere", "org_id": ORG}).json()["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "carol", "display_name": "Carol", "password": "password123",
                                   "email": "carol@example.com"})
assert r.ok, r.text
CAROL = r.json()["id"]
for lid, ms in ((W, (CL, BOB)), (W3, (CL, BOB, CAROL))):  # Carol only in the target list: the agent's move there waits
    for m in ms:
        check(A.put(B + f"/api/lists/{lid}/members", json={"user_id": m, "role": "edit"}).ok, f"setup: {m} in {lid}")


def wait_move(task):
    r = requests.patch(V + f"/tasks/{task}", headers=CLH, json={"list_id": W3})
    check(r.status_code == 202, f"the agent's move waits {r.status_code} {r.text[:200]}")
    return (r.json().get("job") or {}).get("id")


def bell(s):
    j = s.get(B + "/api/news").json()
    return j.get("unread_me"), [x for x in j["items"] if x["kind"] == "approval" and not x["read"]]


# ---- #2405: the approval counts
n0, _ = bell(A)
T1 = A.post(B + "/api/tasks", json={"title": "Prepare the offer", "list_id": W}).json()["id"]
J1 = wait_move(T1)
n1, ap = bell(A)
check(n1 == n0 + 1, f"the bell number counts the approval {n0} -> {n1}")
check(len(ap) == 1 and ap[0].get("to_me"), "the approval item is flagged to_me")
check(A.post(B + f"/api/agents/jobs/{J1}/action", json={"action": "reject"}).ok, "rejected")

# ---- #2420: the card counts people only
org = [o for o in A.get(B + "/api/admin/orgs").json()["orgs"] if o["id"] == ORG][0]
ag = sql("SELECT COUNT(*) FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND u.kind='agent'", (ORG,))[0][0]
check(ag >= 1 and org.get("people") == len(org["members"]) - ag, f"admin list: people leaves the agent out {org.get('people')} of {len(org['members'])}, agents {ag}")
mine = [o for o in A.get(B + "/api/orgs").json()["orgs"] if o["id"] == ORG][0]
check(len([m for m in mine["members"] if not m["agent"]]) == org["people"], "my organisations: the same people")

# ---- #2396: the Mac icon
page = requests.get(B + "/").text
check('apple-touch-icon-1024.png' in page and 'sizes="1024x1024"' in page, "the page head links the 1024 px icon")
r = requests.get(B + "/static/apple-touch-icon-1024.png")
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/png"), f"icon served as PNG {r.status_code}")
check(r.content[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(r.content[16:20], "big") == 1024 and int.from_bytes(r.content[20:24], "big") == 1024, "icon is 1024 x 1024")

# ---- a person without an organisation (freelancer-matrix: news)
FU, F = freelancer(B, A)
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments", "delete"]})
check(r.status_code in (200, 201), "freelancer: an own agent " + r.text[:200])
FA = r.json()["id"]
FH = hdr(F.post(B + f"/api/my/agents/{FA}/token").json().get("token", ""))
FL = F.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
check(F.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "freelancer: the agent in the own list")
F.patch(B + "/api/settings", json={"notify": {"approval": {"news": 1}}})
FT = [F.post(B + "/api/tasks", json={"title": f"Shot {i}", "list_id": FL}).json()["id"] for i in range(10)]
f0, _ = bell(F)
r = requests.post(V + "/tasks/batch", headers=FH, json={"ids": FT, "action": "complete"})
check(r.status_code == 202, f"freelancer: the batch waits {r.status_code}")
f1, ap = bell(F)
check(f1 == f0 + 1 and len(ap) == 1, f"freelancer: the bell counts the approval {f0} -> {f1}")

print(f"p21443_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
