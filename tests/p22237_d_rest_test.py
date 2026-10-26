#!/usr/bin/env python3
"""2.223.7 D (#2941) small visibility leftovers of agents: what the agent may see NOW (not what it saw when it created
something). Invented names only.
 - job_dict: a job of an agent whose share of the task's project was withdrawn stays visible, without task title / list id
 - agent schedules: the list name of a plan is gone after the share was withdrawn
 - the same for a freelancer's own agent (freelancer-matrix: agents)
 - 2.223.7 review (#2941): a participant agent's deploy request: the checklist stored after the approver decides (blocked /
   approve anyway) names only the deploy tasks the agent sees, not the other open ones of the project
usage: p22237_d_rest_test.py <datadir>   (P22237D_NOSTART=1: against a running instance on KALMIDO_TEST_PORT)"""
import os
import subprocess
import sys
import time

import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,files,docs,agents,deps"


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


if not os.environ.get("P22237D_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})


def case(owner, label):
    """owner: a logged-in person with an own agent; the agent loses the share of the project it worked in."""
    r = owner.post(B + "/api/my/agents", json={"username": f"bot_{label}", "display_name": f"Bot {label}", "scopes": ["read", "write"]})
    assert r.status_code == 201, r.text
    aid, ag = r.json()["id"], tok(r.json()["token"])
    lid = owner.post(B + "/api/lists", json={"name": f"Projekt {label}"}).json()["id"]
    assert owner.put(B + f"/api/lists/{lid}/members", json={"user_id": aid, "role": "edit"}).ok
    t = owner.post(B + "/api/tasks", json={"list_id": lid, "title": f"Aufgabe {label} Zebrafink"}).json()["id"]
    # a job on the task
    r = ag.post(V + "/agent/jobs", json={"title": "Pruefen", "task_id": t})
    check(r.status_code == 201, f"{label}: job created: {r.status_code} {r.text[:120]}")
    jid = r.json()["id"]
    j = [x for x in ag.get(V + "/agent/jobs").json()["data"] if x["id"] == jid][0]
    check(j["task_title"] == f"Aufgabe {label} Zebrafink" and j["list_id"] == lid, f"{label}: job shows task + list while shared")
    # a plan of the owner for the agent, bound to the list
    r = owner.post(B + f"/api/agents/{aid}/schedules", json={"title": "Plan", "prompt": "do", "freq": "daily", "time": "08:00", "list_id": lid})
    check(r.status_code == 201, f"{label}: plan created: {r.status_code} {r.text[:120]}")
    sc = ag.get(V + "/agent/schedules").json()["data"]
    check(sc and sc[0]["list_name"] == f"Projekt {label}", f"{label}: plan shows the list name while shared")
    # the share is withdrawn
    assert owner.delete(B + f"/api/lists/{lid}/members/{aid}").ok
    j = [x for x in ag.get(V + "/agent/jobs").json()["data"] if x["id"] == jid][0]
    check(j["task_title"] is None and j["list_id"] is None and j["title"] == "Pruefen",
          f"{label}: job stays, without the title / list of the task the agent lost ({j['task_title']!r}, {j['list_id']!r})")
    sc = ag.get(V + "/agent/schedules").json()["data"]
    check(sc and sc[0]["list_name"] is None and sc[0]["list"] is None, f"{label}: plan without the list name after the share is gone ({sc[0]['list_name']!r})")


case(A, "org")
case(Fr, "frei")  # freelancer-matrix: agents


def gate(owner, label):
    """A participant agent asks to deploy; the owner decides. The stored checklist never names a task the agent can't see."""
    r = owner.post(B + "/api/my/agents", json={"username": f"gate_{label}", "display_name": f"Gate {label}",
                                                  "scopes": ["read", "tasks:write", "comments", "structure"]})
    assert r.status_code == 201, r.text
    aid, ag = r.json()["id"], tok(r.json()["token"])
    lid = owner.post(B + "/api/lists", json={"name": f"Gate {label}"}).json()["id"]
    assert owner.put(B + f"/api/lists/{lid}/members", json={"user_id": aid, "role": "participant"}).ok
    t = owner.post(B + "/api/tasks", json={"list_id": lid, "title": f"Release {label}"}).json()["id"]
    mine = owner.post(B + "/api/tasks", json={"list_id": lid, "title": f"Eigener Schritt {label}", "ltags": ["deploy"]}).json()["id"]
    other = owner.post(B + "/api/tasks", json={"list_id": lid, "title": f"Geheim Pelikan {label}", "ltags": ["deploy"]}).json()["id"]
    for x in (t, mine):
        assert owner.patch(B + f"/api/tasks/{x}", json={"assignee_id": aid}).ok
    r = ag.post(V + f"/tasks/{t}/comments", json={"body": "Ready", "suggestion": {
        "kind": "integrate", "source": "feat/x", "target": "main", "summary": "s", "evidence": "green"}})
    check(r.ok, f"{label}: integrate request ({r.status_code} {r.text[:120]})")
    ic = r.json()["id"]
    check(owner.post(B + f"/api/comments/{ic}/decide", json={"decision": "approve"}).ok, f"{label}: integration approved")
    r = ag.post(V + f"/tasks/{t}/comments", json={"body": "Deploy?", "suggestion": {
        "kind": "deploy", "summary": "s", "evidence": "ok", "integrations": [ic]}})
    check(r.ok and [x["id"] for x in r.json()["suggestion"]["checklist"]] == [mine] and "Pelikan" not in r.text,
          f"{label}: the agent's checklist: only its own deploy task ({r.text[:200]})")
    dc = r.json()["id"]

    def stored():
        x = ag.get(V + f"/tasks/{t}/comments")
        return x.text, next((k["suggestion"] for k in x.json()["data"] if k["id"] == dc), None) or {}

    r = owner.post(B + f"/api/comments/{dc}/decide", json={"decision": "approve"})
    txt, sug = stored()
    check(r.ok and r.json()["state"] == "blocked", f"{label}: still blocked by both open deploy tasks ({r.text[:160]})")
    check([x["id"] for x in sug.get("checklist", [])] == [mine] and "Pelikan" not in txt,
          f"{label}: after the decision the agent reads only its own deploy task ({txt[:200]})")
    r = owner.post(B + f"/api/comments/{dc}/decide", json={"decision": "approve", "skip_checklist": True})
    txt, sug = stored()
    check(r.ok and sug.get("state") == "approved" and [x["id"] for x in sug.get("skipped", [])] == [mine] and "Pelikan" not in txt,
          f"{label}: approve anyway: skipped names only the agent's task ({txt[:200]})")
    assert other


gate(A, "org")
gate(Fr, "frei")  # freelancer-matrix: agents
print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
