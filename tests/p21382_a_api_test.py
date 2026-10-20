#!/usr/bin/env python3
"""2.138.3 API tests, part A (#2406). Invented people and texts only.
freelancer-matrix: agents
 - an agent's request that waits for approval makes an "approval" News entry (carrying the job number); deciding it
   (yes, no, stop) sets the unread entries of that job to read for every person it was shown to; the bell number drops
 - the same for an approval without a task or list (a personal agent emptying the trash), and for an old entry without a job number (matched by
   task / list + title)
 - a person without an organisation: the same for the own agent
usage: p21382_a_api_test.py <datadir>      (P21382A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
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


def unread(uid, jid):
    """Unread approval News entries of a job (by job number)."""
    return sql("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='approval' AND read_at IS NULL AND data->>'job' = ?",
               (uid, str(jid)))[0][0]


def total(uid, jid):
    return sql("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='approval' AND data->>'job' = ?", (uid, str(jid)))[0][0]


if os.environ.get("P21382A_NOSTART") != "1":
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


# ---- yes
T1 = A.post(B + "/api/tasks", json={"title": "Prepare the offer", "list_id": W}).json()["id"]
J1 = wait_move(T1)
check(unread(ALICE, J1) == 1, f"yes: the approval News entry is unread and carries the job number {total(ALICE, J1)}")
r = A.post(B + f"/api/agents/jobs/{J1}/action", json={"action": "approve"})
check(r.ok and r.json().get("state") == "done", f"yes: approved {r.text[:200]}")
check(total(ALICE, J1) == 1 and unread(ALICE, J1) == 0, "yes: the entry is read after the decision")

# ---- no, decided by another person than the one it was shown to (the entry of both turns read)
T2 = A.post(B + "/api/tasks", json={"title": "Prepare the invoice", "list_id": W}).json()["id"]
J2 = wait_move(T2)
check(unread(ALICE, J2) == 1, "no: unread before")
sql("INSERT INTO notifications(user_id,kind,task_id,actor_id,data,created_at) VALUES(?,?,?,?,CAST(? AS jsonb),?)",
    (BOB, "approval", T2, CL, '{"title": "x", "job": %d}' % J2, "2026-01-01T00:00:00.000Z"), write=True)
check(unread(BOB, J2) == 1, "no: a second recipient has it unread")
r = A.post(B + f"/api/agents/jobs/{J2}/action", json={"action": "reject"})
check(r.ok and r.json().get("state") == "stopped", f"no: rejected {r.text[:200]}")
check(unread(ALICE, J2) == 0 and unread(BOB, J2) == 0, "no: the entries of every recipient are read")

# ---- an old entry without a job number (task + title)
T3 = A.post(B + "/api/tasks", json={"title": "Prepare the report", "list_id": W}).json()["id"]
J3 = wait_move(T3)
sql("UPDATE notifications SET data = data::jsonb - 'job' WHERE user_id=? AND kind='approval' AND task_id=?", (ALICE, T3), write=True)
old = sql("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='approval' AND task_id=? AND read_at IS NULL AND data->>'job' IS NULL",
          (ALICE, T3))[0][0]
check(old == 1, f"legacy: an entry without a job number, unread {old}")
# 2.138.3 (#2406, review): an old entry of another sender with the same title stays (it may be a different open question)
ttl = sql("SELECT data->>'title' FROM notifications WHERE user_id=? AND kind='approval' AND task_id=?", (ALICE, T3))[0][0]
sql("INSERT INTO notifications(user_id,kind,task_id,actor_id,data,created_at) VALUES(?,?,?,?,CAST(? AS jsonb),?)",
    (ALICE, "approval", T3, BOB, json.dumps({"title": ttl}), "2026-01-01T00:00:00.000Z"), write=True)
check(A.post(B + f"/api/agents/jobs/{J3}/action", json={"action": "stop"}).ok, "legacy: stopped")
old = sql("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='approval' AND task_id=? AND read_at IS NULL", (ALICE, T3))[0][0]
check(old == 1, "legacy: the old entry is read by task + title + sender, the other sender's stays")

# ---- a person without an organisation (freelancer-matrix: agents)
FU, F = freelancer(B, A, "frida")
F.patch(B + "/api/settings", json={"notify": {"approval": {"news": 1}}})
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments", "delete"]})
check(r.status_code in (200, 201), "freelancer: an own agent " + r.text[:200])
FA = r.json().get("id")
FH = hdr(F.post(B + f"/api/my/agents/{FA}/token").json().get("token", ""))
FL = F.post(B + "/api/lists", json={"name": "Studio"}).json()["id"]
check(F.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "freelancer: the agent in the own list")
FT = [F.post(B + "/api/tasks", json={"title": f"Shot {i}", "list_id": FL}).json()["id"] for i in range(10)]
r = requests.post(V + "/tasks/batch", headers=FH, json={"ids": FT, "action": "complete"})
check(r.status_code == 202, f"freelancer: the batch waits {r.status_code}")
FJ = (r.json().get("job") or {}).get("id")
check(unread(FU, FJ) == 1, f"freelancer: the News entry is unread {total(FU, FJ)}")
r = F.post(B + f"/api/agents/jobs/{FJ}/action", json={"action": "approve"})
check(r.ok and r.json().get("state") == "done", "freelancer: approved " + r.text[:200])
check(total(FU, FJ) == 1 and unread(FU, FJ) == 0, "freelancer: the entry is read after the decision")

# an approval without a task and without a list (emptying the trash) of a personal agent: shown to its owner
r = requests.delete(V + "/trash", headers=FH)
check(r.status_code == 202, f"freelancer: emptying the trash waits {r.status_code} {r.text[:200]}")
FJ2 = (r.json().get("job") or {}).get("id")
check(unread(FU, FJ2) == 1, "freelancer: the News entry without task and list is unread, with the job number")
check(F.post(B + f"/api/agents/jobs/{FJ2}/action", json={"action": "reject"}).ok, "freelancer: rejected")
check(unread(FU, FJ2) == 0 and total(FU, FJ2) == 1, "freelancer: that entry is read")

print(f"p21382_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
