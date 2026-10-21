#!/usr/bin/env python3
"""2.156.0 API tests, part A: tasks and the mind map with five levels (#1949) and "Add ideas" by an agent (#1201).
Invented names only, addresses @example.com.
 - #1949: /api/state carries max_depth 5; five levels can be created and moved, a sixth is refused (create, move, the batch
   move of several tasks); an import (Todoist CSV) puts deeper levels below level 5 with a warning; the same for a person
   without an organisation
 - #1201: only agents the list is shared with can be asked (GET /api/proposals/agents?kind=ideas); the request needs write
   access and a branch with a free level below; the agent gets the branch's path, the list's name, the free levels, the
   hint and the language -- no notes, no other titles; its answer is validated (children cut where no level is free);
   the person takes single ideas over (a sub-idea brings its idea along, tasks as the person, history "proposal"), drops the
   rest, the job ends and the agent hears it; replacing after a take 409; the generic apply / discard work too; the
   tenant boundary (another person, another organisation's agent, an agent's token on the person routes)
 - a freelancer without an organisation does the same with the own agent in the private space
usage: p2156_a_api_test.py <datadir>   (P2156A_NOSTART=1: against a running instance on KALMIDO_TEST_PORT)
freelancer-matrix: agents, tasks
tenant-matrix: agent"""
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
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab,kanban,timeline"


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


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def task(s, title, lid, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def state(s):
    return {t["id"]: t for t in s.get(B + "/api/state").json()["tasks"]}


def chain(s, lid, n, prefix):
    """n tasks, each the subtask of the one before -> their ids (level 1 .. n)."""
    ids, p = [], None
    for i in range(n):
        ids.append(task(s, f"{prefix} {i + 1}", lid, **({"parent_id": p} if p else {})))
        p = ids[-1]
    return ids


def events(ag, kind):
    j = ag.get(V + "/agent/events", params={"since": 0, "limit": 500}).json()
    return [e for e in j.get("data", j.get("events", [])) if e["event"] == kind]


def job_ev(ag, jid):
    ev = [e for e in events(ag, "job_request") if e["data"]["job"]["id"] == jid]
    return ev[-1]["data"] if ev else {}


def agents_for(s, lid):
    r = s.get(B + "/api/proposals/agents", params={"kind": "ideas", "list_id": lid})
    return [a["id"] for a in r.json().get("agents", [])] if r.ok else r.status_code


def ask(s, **b):
    return s.post(B + "/api/proposals", json={"kind": "ideas", **b})


def answer(ag, jid, body):
    return ag.post(V + f"/agent/jobs/{jid}/proposal", json=body)


def decide(s, jid, **b):
    return s.post(B + f"/api/proposals/{jid}/ideas", json=b)


if not os.environ.get("P2156A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]

# ================================================================ #1949 five levels
st = A.get(B + "/api/state").json()
check(st.get("max_depth") == 5, f"#1949: the state names the levels: {st.get('max_depth')}")
L = A.post(B + "/api/lists", json={"name": "Deep plan"}).json()["id"]
C5 = chain(A, L, 5, "Level")
check(len(C5) == 5 and state(A)[C5[4]]["parent_id"] == C5[3], "#1949: five levels created")
r = A.post(B + "/api/tasks", json={"title": "Level 6", "list_id": L, "parent_id": C5[4]})
check(r.status_code == 400 and "5 levels" in r.json().get("error", ""), f"#1949: a sixth level is refused {r.status_code} {r.text[:120]}")
# moving: a task with two levels below fits under level 3 (-> levels 4, 5), not under level 4
M3 = chain(A, L, 3, "Move")
r = A.patch(B + f"/api/tasks/{M3[1]}", json={"parent_id": C5[2]})
check(r.ok, f"#1949: a task with one level below moves under level 3 (-> 4 and 5) {r.status_code} {r.text[:120]}")
r = A.patch(B + f"/api/tasks/{M3[1]}", json={"parent_id": C5[3]})
check(r.status_code == 400, f"#1949: under level 4 its subtask would be level 6: refused {r.status_code}")
check(state(A)[M3[1]]["parent_id"] == C5[2], "#1949: the refused move changed nothing")
# the batch move of several tasks: the one that would go too deep stays, the other moves
X1, X2 = task(A, "Loose one", L), chain(A, L, 2, "Pair")
r = A.post(B + "/api/tasks/batch", json={"ids": [X1, X2[0]], "action": "patch_each",
                                          "data": {"items": {str(X1): {"parent_id": C5[3], "sort": 0}, str(X2[0]): {"parent_id": C5[3], "sort": 1}}}})
j = r.json()
st = state(A)
check(j.get("count") == 1 and st[X1]["parent_id"] == C5[3] and st[X2[0]]["parent_id"] is None, f"#1949: batch: level 5 ok, too deep stays {j}")
# an import: deeper levels hang below level 5 with a warning
csv = "TYPE,CONTENT,INDENT\n" + "".join(f"task,Nest {i},{i}\n" for i in range(1, 8))
r = A.post(B + "/api/import/todoist", files={"file": ("Nest.csv", csv.encode())}, data={})
j = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
check(r.ok, f"#1949: import ran {r.status_code} {str(j)[:160]}")
st = state(A)
nest = {t["title"]: t for t in st.values() if t["title"].startswith("Nest ")}
check(len(nest) == 7 and nest["Nest 5"]["parent_id"] == nest["Nest 4"]["id"], "#1949: import: five levels kept")
check(nest.get("Nest 6", {}).get("parent_id") == nest["Nest 4"]["id"] and nest.get("Nest 7", {}).get("parent_id") == nest["Nest 4"]["id"],
      "#1949: import: levels 6 and 7 hang below level 4 (on level 5)")
check(any("Nested deeper than 5" in (w.get("text") or "") for w in j.get("warnings", [])), f"#1949: import warns {j.get('warnings')}")

# ================================================================ #1201 Add ideas
r = A.post(B + "/api/admin/agents", json={"username": "ideabot", "display_name": "Idea Bot", "scopes": ["read", "write"]})
assert r.status_code == 201, r.text
AG, AGS = r.json()["id"], tok(r.json()["token"])
r = A.post(B + "/api/admin/agents", json={"username": "otherbot", "display_name": "Other Bot", "scopes": ["read", "write"]})
OAG, OAGS = r.json()["id"], tok(r.json()["token"])
P = A.post(B + "/api/lists", json={"name": "Summer party"}).json()["id"]
SEC = A.post(B + "/api/sections", json={"name": "Planning", "list_id": P}).json()["id"]
T1 = task(A, "Venue", P, section_id=SEC, content="SECRET-NOTE do not share")
T2 = task(A, "Shortlist", P, parent_id=T1)
task(A, "Unrelated sibling title", P)
check(agents_for(A, P) == [], "#1201: no agent shares the list: nobody to ask")
check(ask(A, agent_id=AG, list_id=P, branch=f"t{T1}").status_code == 404, "#1201: not shared: 404")
check(A.put(B + f"/api/lists/{P}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: the list is shared with the agent")
check(agents_for(A, P) == [AG], f"#1201: the agent of the list: {agents_for(A, P)}")
check(ask(A, agent_id=OAG, list_id=P, branch=f"t{T1}").status_code == 404, "#1201: an agent the list is not shared with: 404")
check(ask(A, agent_id=AG, list_id=P, branch="x1").status_code == 400, "#1201: a bad branch 400")
check(ask(A, agent_id=AG, list_id=P, branch=f"t{C5[0]}").status_code == 404, "#1201: a task of another list as branch 404")
check(ask(A, agent_id=AG, list_id=P, branch=f"t{T1}", extra=1).status_code == 400, "#1201: unknown keys 400")
r = ask(A, agent_id=AG, list_id=P, branch=f"t{T2}", hint="Outdoor options")
check(r.status_code == 201, "#1201: the request " + r.text[:200])
J1 = r.json()["id"]
ev = job_ev(AGS, J1)
inp = ev.get("input") or {}
check(ev.get("kind") == "ideas" and set(inp) == {"list", "path", "branch", "levels", "hint", "lang", "target"}, f"#1201: the input keys {sorted(inp)}")
check(inp.get("list") == "Summer party" and inp.get("path") == ["Planning", "Venue", "Shortlist"] and inp.get("levels") == 2
      and inp.get("hint") == "Outdoor options" and inp.get("target") == f"t{T2}", f"#1201: path, list, levels, hint {inp}")
check("SECRET-NOTE" not in str(ev) and "Unrelated sibling" not in str(ev), "#1201: no notes, no other titles go to the agent")
check([j["state"] for j in A.get(B + f"/api/lists/{P}/ideas").json()["jobs"]] == ["requested"], "#1201: the map sees the waiting request")
# the agent's answer
check(answer(AGS, J1, {"items": []}).status_code == 400, "#1201: no items 400")
check(answer(AGS, J1, {"items": [{"title": "x", "due": "2030-01-01"}]}).status_code == 400, "#1201: unknown fields 400")
check(answer(AGS, J1, {"items": [{"title": "t"}] * 51}).status_code == 400, "#1201: more than 50 ideas 400")
r = answer(AGS, J1, {"summary": "Three ideas", "items": [{"title": "Park", "children": [{"title": "Ask the city"}, {"title": "Toilets"}]},
                                                          {"title": "Rooftop"}, {"title": "Garden"}]})
check(r.status_code == 201, "#1201: the proposal " + r.text[:200])
jobs = A.get(B + f"/api/lists/{P}/ideas").json()["jobs"]
check(len(jobs) == 1 and jobs[0]["state"] == "ready" and [x["title"] for x in jobs[0]["items"]] == ["Park", "Rooftop", "Garden"]
      and jobs[0]["agent"]["id"] == AG, f"#1201: the ideas for the map {jobs}")
# tenant boundary
check(Bo.get(B + f"/api/lists/{P}/ideas").status_code == 404, "#1201: another person: the list's ideas 404")
check(decide(Bo, J1, take=["1"]).status_code == 404, "#1201: another person cannot take ideas over (404)")
check(Ca.get(B + f"/api/proposals/agents", params={"kind": "ideas", "list_id": P}).status_code == 404, "#1201: another person: no agents of a foreign list")
check(AGS.get(B + f"/api/lists/{P}/ideas").status_code in (401, 403, 404), "#1201: an agent's token gets no person route")
# 2.156.0 review: an agent limited to other lists (agents.list_ids) is not offered and cannot be asked for this list
OTHER = A.post(B + "/api/lists", json={"name": "Elsewhere"}).json()["id"]
A.put(B + f"/api/lists/{OTHER}/members", json={"user_id": AG, "role": "edit"})  # the limit takes only lists the agent is in
r = A.patch(B + f"/api/admin/agents/{AG}", json={"list_ids": [OTHER], "bridge_ok": True})
check(r.ok, f"#1201 review: the agent limited to another list {r.status_code} {r.text[:160]}")
check(AG not in (agents_for(A, P) or []), "#1201 review: a fenced-out agent is not offered")
check(ask(A, agent_id=AG, list_id=P, branch="r").status_code == 404, "#1201 review: a fenced-out agent cannot be asked (404)")
r = A.patch(B + f"/api/admin/agents/{AG}", json={"list_ids": [], "bridge_ok": True})
check(r.ok, f"#1201 review: the restriction lifted again {r.status_code} {r.text[:160]}")
A.delete(B + f"/api/lists/{OTHER}/members/{AG}")
# take a sub-idea: its idea comes along
check(decide(A, J1, take=["9"]).status_code == 400, "#1201: an unknown key 400")
r = decide(A, J1, take=["0.1"])
j = r.json()
check(r.ok and j.get("state") == "ready" and set(j["taken"]) == {"0", "0.1"} and len(j["tasks"]) == 2, f"#1201: a sub-idea brings its idea {r.text[:200]}")
st = state(A)
park, toil = j["taken"]["0"], j["taken"]["0.1"]
check(st[park]["parent_id"] == T2 and st[toil]["parent_id"] == park and st[park]["title"] == "Park" and st[park]["list_id"] == P,
      "#1201: the tasks are under the branch (level 4 and 5)")
check(st[park]["created_by"] == ALICE, "#1201: created as the person")
check(answer(AGS, J1, {"items": [{"title": "Other"}]}).status_code == 409, "#1201: replacing after a take: 409")
r = decide(A, J1, take=["1"], drop=["0.0", "2"])
j = r.json()
check(r.ok and j["state"] == "applied" and j["open"] == [] and set(j["dropped"]) == {"0.0", "2"}, f"#1201: the rest decided: the job ends {r.text[:200]}")
check(A.get(B + f"/api/lists/{P}/ideas").json()["jobs"] == [], "#1201: nothing open any more")
ans = [e for e in events(AGS, "job") if e["data"]["job"]["id"] == J1]
check(ans and ans[-1]["data"]["action"] == "approve" and ans[-1]["data"]["proposal"].get("created") == 3, f"#1201: the agent hears it {ans[-1]['data'] if ans else None}")
check(decide(A, J1, take=["2"]).status_code == 409, "#1201: a finished proposal: 409")
r = A.post(B + f"/api/proposals/{J1}/undo")
check(r.ok and all(x not in state(A) for x in (park, toil)), f"#1201: the generic undo takes the ideas back {r.text[:160]}")
# a branch on level 4: ideas without sub-ideas; level 5: no request
D4 = chain(A, P, 4, "Deep")
r = ask(A, agent_id=AG, list_id=P, branch=f"t{D4[3]}")
check(r.status_code == 201 and job_ev(AGS, r.json()["id"]).get("input", {}).get("levels") == 1, "#1201: a level-4 branch: one level free")
J2 = r.json()["id"]
check(answer(AGS, J2, {"items": [{"title": "Leaf", "children": [{"title": "Too deep"}]}]}).status_code == 201, "#1201: answer on level 4")
jobs = {j["id"]: j for j in A.get(B + f"/api/lists/{P}/ideas").json()["jobs"]}
check(jobs[J2]["items"] == [{"title": "Leaf", "children": []}], f"#1201: children cut where no level is free {jobs[J2]['items']}")
D5 = task(A, "Deep 5", P, parent_id=D4[3])
check(ask(A, agent_id=AG, list_id=P, branch=f"t{D5}").status_code == 400, "#1201: a level-5 branch takes no ideas (400)")
# the generic apply: selected ones taken, the rest dropped
r = A.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"]})
check(r.ok and r.json().get("created") == 1 and any(t["title"] == "Leaf" and t["parent_id"] == D4[3] for t in state(A).values()),
      f"#1201: the generic apply {r.text[:160]}")
# a section and the list itself as branch; discard
r = ask(A, agent_id=AG, list_id=P, branch=f"s{SEC}")
J3 = r.json()["id"]
check(job_ev(AGS, J3).get("input", {}).get("path") == ["Planning"], "#1201: a section: its name is the path")
answer(AGS, J3, {"items": [{"title": "Budget"}]})
r = decide(A, J3, take=["0"])
check(r.ok and r.json()["state"] == "applied" and state(A)[r.json()["taken"]["0"]]["section_id"] == SEC
      and state(A)[r.json()["taken"]["0"]]["parent_id"] is None, "#1201: an idea of a section is a top task in that section")
r = ask(A, agent_id=AG, list_id=P, branch="r")
J4 = r.json()["id"]
check(job_ev(AGS, J4).get("input", {}).get("path") == [] and job_ev(AGS, J4).get("input", {}).get("levels") == 2, "#1201: the list itself")
check(A.post(B + f"/api/proposals/{J4}/discard").ok and A.get(B + f"/api/lists/{P}/ideas").json()["jobs"] == [], "#1201: cancel a waiting request")
check(answer(AGS, J4, {"items": [{"title": "Late"}]}).status_code == 409, "#1201: an answer after the cancel: 409")
# a viewer cannot ask; the list no longer shared: the agent's answer 403
check(A.put(B + f"/api/lists/{P}/members", json={"user_id": Bo.get(B + "/api/state").json()["me"]["id"], "role": "view"}).ok, "setup: bob views")
check(ask(Bo, agent_id=AG, list_id=P, branch="r").status_code in (403, 404), "#1201: a viewer cannot ask for ideas")
J5 = ask(A, agent_id=AG, list_id=P, branch="r").json()["id"]
A.delete(B + f"/api/lists/{P}/members/{AG}")
if agents_for(A, P) == []:
    check(answer(AGS, J5, {"items": [{"title": "Late"}]}).status_code == 403, "#1201: the list no longer shared: 403")

# ================================================================ a freelancer: five levels + ideas in the private space
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "Portrait shoot"}).json()["id"]
FC = chain(Fr, FL, 5, "Step")
check(Fr.post(B + "/api/tasks", json={"title": "Step 6", "list_id": FL, "parent_id": FC[4]}).status_code == 400, "freelancer: five levels, the sixth refused")
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "write"]})
check(r.status_code == 201, "freelancer: her own agent " + r.text[:200])
FAG, FAGS = r.json()["id"], tok(r.json()["token"])
Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FAG, "role": "edit"})
check(agents_for(Fr, FL) == [FAG], f"freelancer: her agent in her list {agents_for(Fr, FL)}")
check(agents_for(A, FL) == 404, "freelancer: another person sees nothing of her list")
r = ask(Fr, agent_id=FAG, list_id=FL, branch=f"t{FC[0]}")
FJ = r.json().get("id")
check(r.status_code == 201 and answer(FAGS, FJ, {"items": [{"title": "Lighting"}, {"title": "Props"}]}).status_code == 201, "freelancer: request + answer")
r = decide(Fr, FJ, take=["0", "1"])
check(r.ok and r.json()["state"] == "applied" and len(r.json()["tasks"]) == 2, "freelancer: ideas taken over")
check(decide(A, FJ, take=["0"]).status_code == 404, "freelancer: the admin cannot touch her proposal")

print(f"p2156_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
