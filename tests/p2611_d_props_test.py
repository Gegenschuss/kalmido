#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.611.0 D (#4784): proposals of the team server agent - write rights at apply time, the raw notes of an extract, Waiting for me.
freelancer-matrix: agents (the person without an organisation: her own agent's subtasks proposal in her own project applies as before)
 - (a) a subtasks proposal whose task moved, between the request and the apply, into a project where the one applying only reads:
   403 and no subtask - for the one who asked and for another member with write rights in the old project; with write rights
   there again the same proposal applies
 - (b) an extract of the team agent: the one who asked sees the whole input (the notes); another member with write rights sees
   only the proposed tasks (input: list + members, no text / images); a reader 404
 - (c) Waiting for me: a member with write rights finds the team proposals of someone else, a reader does not
usage: p2611_d_props_test.py <datadir>      (KMT_NOSTART=1 / P2611D_NOSTART=1: a running server)"""
import os
import shutil
import subprocess

import requests

from kt import B, CT, DATA, check, dbx, done, docker_logs_on_first_fail, fresh, sess, until
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
SKEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (the provider key is sealed with it)
KEY_ORG = "sk-test-orgkey-0123456789-dddd"
fresh(env={"KALMIDO_SECRET_KEY": SKEY, "KALMIDO_SRVAGENT_ANTHROPIC_URL": "http://127.0.0.1:8091", "KALMIDO_SRVAGENT_RUN_S": "60",
           "KALMIDO_SRVAGENT_STEPS": "6"}, prefix="P2611D")
docker_logs_on_first_fail()
shutil.copy(os.path.join(N, "fake_anthropic.py"), DATA)
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_anthropic.py"], check=True)
until(lambda: subprocess.run(["docker", "exec", CT, "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8091), 1)"],
                             capture_output=True).returncode == 0, 20)

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok, "personal agents allowed")
uid = {}
for u, rk in (("bob", "admin"), ("carl", "member"), ("dora", "member"), ("rita", "member")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rk}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as {rk} " + r.text[:200])
    uid[u] = r.json().get("id")
S = {u: sess(u) for u in ("bob", "carl", "dora", "rita")}
Bo, Ca, Do, Ri = (S[u] for u in ("bob", "carl", "dora", "rita"))
for s in S.values():
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "comments,collab"})
FID, Fr = freelancer(B, A)

r = Bo.post(B + f"/api/orgs/{ORG}/server-agents", json={"username": "teamki", "display_name": "Team KI"})
check(r.status_code == 201, f"setup: bob creates the team agent {r.status_code} {r.text[:200]}")
TK = r.json().get("id")
check(Bo.put(B + f"/api/agents/{TK}/server", json={"api_key": KEY_ORG}).ok, "setup: its key")
P = Bo.post(B + "/api/lists", json={"name": "Team project", "org_id": ORG}).json()["id"]
P3 = Bo.post(B + "/api/lists", json={"name": "Read-only project", "org_id": ORG}).json()["id"]
for lid, u, role in ((P, "carl", "edit"), (P, "dora", "edit"), (P, "rita", "view"), (P3, "carl", "view"), (P3, "dora", "view")):
    check(Bo.put(B + f"/api/lists/{lid}/members", json={"user_id": uid[u], "role": role}).ok, f"setup: {u} in project {lid} ({role})")
check(Bo.put(B + f"/api/lists/{P}/members", json={"user_id": TK, "role": "edit"}).ok, "setup: the team agent joins the project")
check(Bo.patch(B + f"/api/lists/{P}", json={"agent_members": True}).ok, "setup: bob opens the agent to the members")
r = A.post(B + f"/api/admin/agents/{TK}/token", json={})
check(r.ok, f"setup: a token of the agent for the stand-in proposals {r.status_code}")
TOK = {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"}


def runs():
    return dbx("SELECT id, state FROM agent_runs WHERE agent_id=? ORDER BY id", (TK,))


def ask(s, body, n_before):
    """A proposal request of s to the team agent -> its job id, once the agent's run on it ended."""
    r = s.post(B + "/api/proposals", json={"agent_id": TK, **body})
    check(r.status_code in (200, 201), f"request {body['kind']} {r.status_code} {r.text[:200]}")
    until(lambda: (lambda rr: rr if len(rr) > n_before and all(x[1] != "run" for x in rr) else None)(runs()), 40)
    return r.json().get("job", r.json()).get("id")


def propose(jid, prop, tok=TOK):
    r = requests.post(B + f"/api/v1/agent/jobs/{jid}/proposal", headers=tok, json=prop, timeout=30)
    check(r.ok, f"the agent's proposal for job {jid} {r.status_code} {r.text[:200]}")


def waiting(s, jid):
    return any(x["kind"] == "job" and x["id"] == jid for x in s.get(B + "/api/inbox").json().get("items", []))


def subs(tid):
    return dbx("SELECT COUNT(*) FROM tasks WHERE parent_id=? AND deleted_at IS NULL", (tid,))[0][0]


# ---------------------------------------------------------------- (a) the task moved into a project where they only read
T3 = Bo.post(B + "/api/tasks", json={"title": "Moving owl task", "list_id": P}).json()["id"]
J1 = ask(Ca, {"kind": "subtasks", "task_id": T3}, len(runs()))
propose(J1, {"kind": "subtasks", "items": [{"title": "Owl step one"}]})
check(Do.get(B + f"/api/proposals/{J1}").ok, "dora (write rights in the project) sees carl's subtasks proposal")
check(waiting(Do, J1), "(c) Waiting for me lists it for dora")
check(not waiting(Ri, J1), "(c) ... not for rita (read only)")
check(Bo.patch(B + f"/api/tasks/{T3}", json={"list_id": P3}).ok, "bob moves the task into the read-only project")
for s, who in ((Ca, "carl (who asked)"), (Do, "dora (write rights in the old project)")):
    r = s.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]})
    check(r.status_code == 403, f"{who}: applying is refused (403) {r.status_code} {r.text[:160]}")
check(subs(T3) == 0, "no subtask in the read-only project")
check(dbx("SELECT prop_state FROM agent_jobs WHERE id=?", (J1,)) == [("ready",)], "the proposal stays ready")
check(Bo.put(B + f"/api/lists/{P3}/members", json={"user_id": uid["carl"], "role": "edit"}).ok, "bob gives carl write rights there")
r = Ca.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]})
check(r.ok and r.json().get("created") == 1 and subs(T3) == 1, f"now carl applies it {r.status_code} {r.text[:160]}")

# ---------------------------------------------------------------- (b) the raw notes of an extract stay with who asked
J2 = ask(Ca, {"kind": "extract", "list_id": P, "text": "CARL-PRIVATE-NOTE the meeting: order chairs, call the printer"}, len(runs()))
propose(J2, {"kind": "extract", "tasks": [{"title": "Order chairs", "assignee_id": uid["dora"]}]})
r = Ca.get(B + f"/api/proposals/{J2}")
check(r.ok and "CARL-PRIVATE-NOTE" in r.json()["input"].get("text", ""), f"carl (who asked) sees his notes {r.status_code}")
r = Do.get(B + f"/api/proposals/{J2}")
v = r.json() if r.ok else {}
check(r.ok and v["proposal"]["tasks"][0]["title"] == "Order chairs", f"dora (write rights) sees the proposed tasks {r.status_code}")
check("CARL-PRIVATE-NOTE" not in r.text and "text" not in v.get("input", {}) and "images" not in v.get("input", {}),
      f"... but not carl's notes nor images {sorted(v.get('input', {}))}")
check(v.get("input", {}).get("list", {}).get("id") == P and any(m["id"] == uid["dora"] for m in v.get("input", {}).get("members", [])),
      "... the card still has the list and its members (assignee choice)")
check(Ri.get(B + f"/api/proposals/{J2}").status_code == 404, "rita (read only): 404")
check(waiting(Do, J2) and not waiting(Ri, J2), "(c) Waiting for me: dora yes, rita no")
r = Do.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"]})
check(r.ok and r.json().get("created") == 1, f"dora applies the extract {r.status_code} {r.text[:160]}")
check(dbx("SELECT COUNT(*) FROM tasks WHERE list_id=? AND title='Order chairs' AND deleted_at IS NULL", (P,)) == [(1,)], "the task is there")

# ---------------------------------------------------------------- review 2.611: the notes of a subtasks request follow the task
P4 = Bo.post(B + "/api/lists", json={"name": "Project without dora", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{P4}/members", json={"user_id": uid["carl"], "role": "edit"}).ok, "setup: carl in the project without dora")
T4 = Ca.post(B + "/api/tasks", json={"title": "Noted owl task", "list_id": P, "content": "CARL-TASK-NOTE keep it short"}).json()["id"]
J3 = ask(Ca, {"kind": "subtasks", "task_id": T4}, len(runs()))
propose(J3, {"kind": "subtasks", "items": [{"title": "Noted step"}]})
r = Do.get(B + f"/api/proposals/{J3}")
check(r.ok and "CARL-TASK-NOTE" in r.text, f"dora sees the notes of the task while she sees the task {r.status_code}")
r = Bo.patch(B + f"/api/tasks/{T4}", json={"list_id": P4})
check(r.ok, f"bob moves the task into a project dora is not in {r.status_code} {r.text[:160]}")
r = Do.get(B + f"/api/proposals/{J3}")
check("CARL-TASK-NOTE" not in r.text, f"... then dora no longer gets its notes from the request {r.status_code}")
r = Ca.get(B + f"/api/proposals/{J3}")
check(r.ok and "CARL-TASK-NOTE" in r.text, f"... carl (who asked) still does {r.status_code}")

# ---------------------------------------------------------------- freelancer: her own agent in her own project
FAG = Fr.post(B + "/api/my/agents", json={"username": "frida-bot", "display_name": "Frida Bot"}).json()["id"]
FL = Fr.post(B + "/api/lists", json={"name": "Frida's project"}).json()["id"]
check(Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FAG, "role": "edit"}).ok, "setup: frida shares her project with her agent")
TF = Fr.post(B + "/api/tasks", json={"title": "Frida's task", "list_id": FL}).json()["id"]
r = Fr.post(B + "/api/proposals", json={"agent_id": FAG, "kind": "subtasks", "task_id": TF})
check(r.status_code in (200, 201), f"frida asks her agent for subtasks {r.status_code} {r.text[:200]}")
FJ = r.json().get("job", r.json()).get("id")
r = Fr.post(B + f"/api/my/agents/{FAG}/token", json={})
check(r.ok, f"a token of frida's agent {r.status_code}")
propose(FJ, {"kind": "subtasks", "items": [{"title": "Frida's step"}]}, {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"})
r = Fr.post(B + f"/api/proposals/{FJ}/apply", json={"select": ["0"]})
check(r.ok and r.json().get("created") == 1 and subs(TF) == 1, f"frida applies it in her own project {r.status_code} {r.text[:160]}")

raise SystemExit(done("p2611_d_props"))
