#!/usr/bin/env python3
"""2.3.0 API tests: agent proposals (#260 project from a briefing, #261 break down a task, #262 sort the inbox, #263 tasks
from meeting notes) and their shared infrastructure.
 - who may ask which agent (agents.proposals shared | all | off; instance admins count as sharing; paused agents never):
   GET /api/proposals/agents, /api/state proposers, POST /api/proposals refused for the others (404)
 - the request: a proposal job (kind, state running / requested) + the event job_request with EXACTLY the input the person
   sent; bad kind / missing text / too long / unknown field 400; at most 10 open requests per person (429)
 - the agent's answer POST /api/v1/agent/jobs/{id}/proposal (+ GET /api/v1/agent/jobs/{id}): validation per kind (missing
   field, unknown field -> unknown_field, unknown section, dependency cycle, bad index, > 200 entries, > 256 KB -> 413,
   wrong kind), another agent's job 404, a job without a request 400; the job waits, News "proposal" for the person
 - review: another person's proposal 404 (GET / apply / discard / undo); apply with a selection + edits creates everything AS
   THE PERSON (list owner, created_by, history "created ... from a proposal", assignee pushes / News), dependencies only
   between selected entries, optional sharing with the agent, job done + event job (approve, applied, counts); apply twice 409
 - undo / redo (one step): a clean new project list is removed and created again; a changed task stays (skipped) and the
   rest goes to the trash; subtasks / notes tasks trashed and restored; triage moves / edits reverted and applied again
 - inbox consent (#262): the agent cannot read inbox items (sent or not), the input holds only the selected items and the
   ticked lists, a proposal naming an item or list that was not sent is refused; other people's tasks cannot be sent
 - discard (event reject, a later proposal 409), Approve on a proposal job 409, Stop discards it
 - retention: proposal jobs older than 30 days go with their input (own container, restarted); OpenAPI documents the routes
Starts its OWN containers (start.sh).
usage: p230_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")


def put_member(s, lid, uid, role):
    """2.26.0: shares like PUT /lists/{id}/members; a second agent (one agent per list) joins as in a list from before the
    update, and the list's members may use its agents (the list switch, default off since 2.26.0). Returns a truthy object."""
    r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": role})
    if r.status_code == 409 and "one agent" in r.text.lower():
        c_ = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
        c_.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')",
                   (lid, uid, role, role))
        c_.commit()
        c_.close()
    s.patch(B + f"/api/lists/{lid}", json={"agent_members": True, "agent_peers": True})
    return r.status_code == 409 or r.ok


V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def start(keep=False):
    if not keep:
        subprocess.run(["docker", "rm", "-f", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)  # 2.7.2: the old container must not write while its data goes
        subprocess.run(["rm", "-rf", DATA])
        os.makedirs(DATA, exist_ok=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


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
        return requests.request(m, V + p, headers=self.h, timeout=30, **k)

    def get(self, p, **k):
        return self.req("GET", p, **k)

    def post(self, p, **k):
        return self.req("POST", p, **k)


def dbx(q, a=()):
    con = sqlite3.connect(os.path.join(DATA, "tasks.db"))
    try:
        return con.execute(q, a).fetchall()
    finally:
        con.close()


def events(cl, since=0):
    return cl.get("/agent/events", params={"since": since, "limit": 500}).json()["data"]


def last_event(cl, kind):
    ev = [e for e in events(cl) if e["event"] == kind]
    return ev[-1] if ev else None


def new_agent(a, name):
    r = a.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": name, "display_name": name.title()})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"], Api(r.json()["token"])


def ask(s, **b):
    return s.post(B + "/api/proposals", json=b)


def task(s, tid):
    return s.get(B + f"/api/tasks/{tid}").json()


def timeline(s, tid):
    return s.get(B + f"/api/tasks/{tid}/timeline").json()


start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for x in (A, Bo, Ca):
    x.patch(B + "/api/settings", json={"lang": "en"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
AG, cl = new_agent(A, "claude")
AG2, cl2 = new_agent(A, "helper")
TEAM = A.post(B + "/api/lists", json={"name": "Team"}).json()["id"]
PRIV = A.post(B + "/api/lists", json={"name": "Private stuff"}).json()["id"]
for uid in (BOB, AG):
    assert put_member(A, TEAM, uid, "edit")
SEC = A.post(B + "/api/sections", json={"list_id": TEAM, "name": "Doing"}).json()["id"]

# ================================================================== who may ask which agent
ids = lambda s: sorted(a["id"] for a in s.get(B + "/api/proposals/agents").json()["agents"])  # noqa: E731
check(ids(A) == [AG], f"admin: only the agents of her lists (2.28.0 #965: admins are no exception): {ids(A)}")
check(ids(Bo) == [AG], f"bob shares Team with claude only: {ids(Bo)}")
check(ids(Ca) == [], f"carol shares nothing: {ids(Ca)}")
check([a["id"] for a in Bo.get(B + "/api/state").json()["proposers"]] == [AG], "state: proposers")
check(A.patch(B + f"/api/admin/agents/{AG2}", json={"proposals": "all"}).ok, "admin: helper for everyone")
check(A.get(B + "/api/admin/agents").json()["agents"][-1].get("proposals") in ("all", "shared"), "admin list: proposals mode")
check(ids(Ca) == [AG2] and ids(Bo) == [AG, AG2], "mode all: everyone may ask helper")
check(A.patch(B + f"/api/admin/agents/{AG2}", json={"proposals": "nope"}).status_code == 400, "bad mode 400")
check(A.patch(B + f"/api/admin/agents/{AG}", json={"proposals": "off"}).ok and ids(Bo) == [AG2], "mode off: nobody")
check(ask(Bo, agent_id=AG, kind="project", text="x").status_code == 404, "off: request refused (404)")
A.patch(B + f"/api/admin/agents/{AG}", json={"proposals": "shared"})
check(ask(Ca, agent_id=AG, kind="project", text="x").status_code == 404, "carol may not ask claude (no shared list)")
A.patch(B + f"/api/admin/agents/{AG2}", json={"enabled": False})
check(AG2 not in ids(Ca) and ask(Ca, agent_id=AG2, kind="project", text="x").status_code == 404, "paused agent: not offered, refused")
A.patch(B + f"/api/admin/agents/{AG2}", json={"enabled": True, "proposals": "shared"})
check(Bo.get(B + "/api/proposals/agents").ok and ask(Bo, agent_id=BOB, kind="project", text="x").status_code == 404, "a person is no agent")
check(cl.get("/agent/jobs/999999").status_code == 404, "agent: unknown job 404")

# ================================================================== request validation
check(ask(A, agent_id=AG, kind="magic", text="x").status_code == 400, "bad kind 400")
check(ask(A, agent_id=AG, kind="project").status_code == 400, "project without text 400")
check(ask(A, agent_id=AG, kind="project", text="x" * 50001).status_code == 400, "text > 50000 400")
r = ask(A, agent_id=AG, kind="project", text="x", secret_field=1)
check(r.status_code == 400 and "secret_field" in r.text, f"unknown request field named ({r.status_code})")
check(ask(A, agent_id=AG, kind="extract", list_id=PRIV + 999, text="x").status_code == 404, "extract: unknown list 404")

# ================================================================== #260 project from a briefing
BRIEF = "Image film for ACME: shoot in May, edit in June, deliver 2 cuts."
seq0 = max([e["seq"] for e in events(cl)] or [0])
r = ask(A, agent_id=AG, kind="project", text=BRIEF, folder="Clients", file_name="brief.md")
check(r.status_code == 201 and r.json()["kind"] == "project" and r.json()["proposal_state"] == "requested" and r.json()["state"] == "running",
      f"project request: 201 job ({r.status_code} {r.text[:200]})")
J1 = r.json()["id"]
ev = [e for e in events(cl, seq0) if e["event"] == "job_request"]
check(len(ev) == 1 and ev[0]["data"]["input"] == {"text": BRIEF, "file_name": "brief.md", "folder": "Clients"},
      f"job_request carries exactly the input: {ev and ev[0]['data']['input']}")
check(ev and ev[0]["data"]["kind"] == "project" and ev[0]["data"]["job"]["id"] == J1 and ev[0]["data"]["limits"]["max_items"] == 200
      and ev[0]["data"]["requested_by"]["id"] == ALICE and ev[0]["actor"]["id"] == ALICE, "job_request: kind, job, limits, requested_by")
check(not [e for e in events(cl2, 0) if e["event"] == "job_request"], "the other agent gets nothing")
g = cl.get(f"/agent/jobs/{J1}").json()
check(g.get("input", {}).get("text") == BRIEF and g.get("proposal") is None and g.get("kind") == "project", "agent GET job: input")
check(cl2.get(f"/agent/jobs/{J1}").status_code == 404, "wrong agent: GET 404")
jobs = A.get(B + "/api/agents/jobs").json()["jobs"]
check(any(j["id"] == J1 and j["kind"] == "project" for j in jobs), "Agents view lists the proposal job")
check(Bo.get(B + f"/api/proposals/{J1}").status_code == 404, "another person: GET 404")
check(A.get(B + f"/api/proposals/{J1}").json()["state"] == "requested", "person: state requested")
check(A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code == 409, "apply before a proposal: 409")

GOOD = {"kind": "project", "name": "ACME image film", "folder": "Clients", "summary": "Three phases.",
        "sections": ["Pre-production", "Shoot", "Post"],
        "tasks": [{"title": "Write treatment", "section": "Pre-production", "due": "2031-05-01", "priority": "high",
                   "subtasks": [{"title": "Research"}, {"title": "Draft", "notes": "2 pages"}]},
                  {"title": "Shoot day", "section": "shoot", "start": "2031-05-10", "due": "2031-05-11", "depends_on": [0]},
                  {"title": "Edit", "section": "Post", "due": "2031-06-01", "depends_on": [1]},
                  {"title": "Deliver", "notes": "2 cuts", "depends_on": [2, 0]}]}
bad = [({**GOOD, "name": ""}, 400, "missing name"),
       ({**GOOD, "colour": "red"}, 400, "unknown field"),
       ({**GOOD, "tasks": [{"title": "x", "section": "Nope"}]}, 400, "unknown section"),
       ({**GOOD, "tasks": [{"title": "a", "depends_on": [1]}, {"title": "b", "depends_on": [0]}]}, 400, "cycle"),
       ({**GOOD, "tasks": [{"title": "a", "depends_on": [5]}]}, 400, "bad index"),
       ({**GOOD, "tasks": [{"title": "a", "depends_on": [0]}]}, 400, "depends on itself"),
       ({**GOOD, "tasks": [{"title": "t%d" % i} for i in range(201)]}, 400, "> 200 tasks"),
       ({**GOOD, "tasks": [{"title": "t", "subtasks": [{"title": "s"}] * 50}] * 4}, 400, "> 200 with subtasks"),
       ({**GOOD, "tasks": [{"title": "x", "due": "31.05.2031"}]}, 400, "bad date"),
       ({**GOOD, "tasks": [{"title": "x", "priority": "urgent"}]}, 400, "bad priority"),
       ({**GOOD, "kind": "triage"}, 400, "wrong kind"),
       ({**GOOD, "tasks": [{"title": "x" * 301}]}, 400, "title too long"),
       ({**GOOD, "tasks": [{"title": "x", "notes": "n" * 300000}]}, 413, "body > 256 KB")]
for body, code, what in bad:
    r = cl.post(f"/agent/jobs/{J1}/proposal", json=body)
    check(r.status_code == code, f"proposal {what}: {code} ({r.status_code} {r.text[:160]})")
r = cl.post(f"/agent/jobs/{J1}/proposal", json={**GOOD, "colour": "red"})
check(r.json().get("error", {}).get("code") == "unknown_field" and "colour" in r.json()["error"].get("fields", []), "unknown_field names it")
check(requests.post(V + f"/agent/jobs/{J1}/proposal", data="[1]", headers={**cl.h, "Content-Type": "application/json"}).status_code == 400,
      "not an object 400")
check(cl2.post(f"/agent/jobs/{J1}/proposal", json=GOOD).status_code == 404, "wrong agent: submit 404")
PJ = cl.post("/agent/jobs", json={"title": "plain job"}).json()["id"]
check(cl.post(f"/agent/jobs/{PJ}/proposal", json=GOOD).status_code == 400, "a job without a request: 400")
check(A.get(B + f"/api/proposals/{PJ}").status_code == 404, "a plain job is no proposal (404)")
r = cl.post(f"/agent/jobs/{J1}/proposal", json=GOOD)
check(r.status_code == 201 and r.json()["state"] == "waiting" and r.json()["proposal_state"] == "ready", f"valid proposal 201 ({r.text[:200]})")
check(r.json()["proposal"]["tasks"][1]["section"] == "Shoot" and r.json()["proposal"]["tasks"][0]["priority"] == 5, "normalized (section case, priority)")
news = A.get(B + "/api/news").json()["items"]
check(any(n["kind"] == "proposal" and n["data"].get("job") == J1 and n["actor_id"] == AG for n in news), "News: proposal ready")
check(not any(n["kind"] == "proposal" for n in Bo.get(B + "/api/news").json()["items"]), "no News for others")
check(cl.post(f"/agent/jobs/{J1}/proposal", json=GOOD).status_code == 201, "resubmit replaces (until reviewed)")
check(len([n for n in A.get(B + "/api/news").json()["items"] if n["kind"] == "proposal"]) == 1, "resubmit: no second News")
pv = A.get(B + f"/api/proposals/{J1}").json()
check(pv["state"] == "ready" and pv["proposal"]["name"] == "ACME image film" and pv["agent"]["id"] == AG and pv["input"]["text"] == BRIEF,
      "person: GET the proposal")
check(Bo.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code == 404, "another person: apply 404")
check(Bo.post(B + f"/api/proposals/{J1}/discard").status_code == 404, "another person: discard 404")
check(A.post(B + f"/api/agents/jobs/{J1}/action", json={"action": "approve"}).status_code == 409, "Approve on a proposal job: 409")
check(A.post(B + f"/api/proposals/{J1}/apply", json={"select": []}).status_code == 400, "empty selection 400")
check(A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"], "edits": {"0": {"section": "Nope"}}}).status_code == 400, "edit: unknown section 400")
check(A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"], "edits": {"0": {"title": ""}}}).status_code == 400, "edit: empty title 400")
check(not dbx("SELECT 1 FROM lists WHERE name='ACME image film'"), "a refused apply creates nothing")
seq1 = max(e["seq"] for e in events(cl))
# everything but task 2 (Edit) and subtask 0.0; edits on 0 and 3
r = A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0", "0.1", "1", "3"], "name": "ACME film", "folder": "Clients",
                                                    "share_agent": True,
                                                    "edits": {"0": {"title": "Write the treatment", "due": "2031-05-02"},
                                                              "3": {"section": "Post", "due": "2031-06-20"}}})
check(r.status_code == 200 and r.json()["created"] == 4 and r.json()["list_id"], f"apply: 4 entries ({r.status_code} {r.text[:200]})")
PL = r.json()["list_id"]
lst = dbx("SELECT name, owner_id, kind, folder FROM lists WHERE id=?", (PL,))[0]
check(lst == ("ACME film", ALICE, "project", "Clients"), f"list owned by the person, kind project, folder: {lst}")
rows = dbx("SELECT id, title, created_by, parent_id, section_id, due, priority FROM tasks WHERE list_id=? ORDER BY id", (PL,))
check([x[1] for x in rows] == ["Write the treatment", "Draft", "Shoot day", "Deliver"], f"selected + edited titles: {[x[1] for x in rows]}")
check(all(x[2] == ALICE for x in rows), "created_by = the person (never the agent)")
tid = {x[1]: x[0] for x in rows}
check(rows[1][3] == tid["Write the treatment"], "subtask under its task")
secs = dict(dbx("SELECT name, id FROM sections WHERE list_id=?", (PL,)))
check(rows[0][4] == secs["Pre-production"] and rows[3][4] == secs["Post"] and rows[2][4] == secs["Shoot"], "sections (incl. an edit)")
check(rows[0][5] == "2031-05-02" and rows[0][6] == 5 and rows[3][5] == "2031-06-20", "dates / priority (edits win)")
deps = set(dbx("SELECT task_id, blocker_id FROM task_deps WHERE task_id IN (SELECT id FROM tasks WHERE list_id=?)", (PL,)))
check(deps == {(tid["Shoot day"], tid["Write the treatment"]), (tid["Deliver"], tid["Write the treatment"])},
      f"dependencies only between selected entries: {deps}")
check(dbx("SELECT role FROM list_members WHERE list_id=? AND user_id=?", (PL, AG)) == [("edit",)], "shared with the agent (edit)")
act = timeline(A, tid["Deliver"])["activity"]
check(act and act[0]["kind"] == "created" and act[0]["user_id"] == ALICE and act[0]["data"].get("agent") == AG, "history: created by the person from a proposal")
j = dbx("SELECT state, prop_state, action, action_by FROM agent_jobs WHERE id=?", (J1,))[0]
check(j == ("done", "applied", "approve", ALICE), f"job done / applied: {j}")
ev = [e for e in events(cl, seq1) if e["event"] == "job" and e["data"]["job"]["id"] == J1]
check(ev and ev[-1]["data"]["action"] == "approve" and ev[-1]["data"]["proposal"]["state"] == "applied" and ev[-1]["data"]["proposal"]["created"] == 4,
      "agent told: approve / applied / counts")
check(A.post(B + f"/api/proposals/{J1}/apply", json={"select": ["0"]}).status_code == 409, "apply twice 409")
check(cl.post(f"/agent/jobs/{J1}/proposal", json=GOOD).status_code == 409, "submit after apply 409")
check(Bo.post(B + f"/api/proposals/{J1}/undo").status_code == 404, "another person: undo 404")
# undo: a clean new project goes as a whole, redo brings it back
r = A.post(B + f"/api/proposals/{J1}/undo")
check(r.ok and r.json()["undone"] == 4 and not r.json()["skipped"], f"undo: {r.text[:200]}")
check(not dbx("SELECT 1 FROM lists WHERE id=?", (PL,)), "undo: the new project list is gone")
check(A.post(B + f"/api/proposals/{J1}/undo").status_code == 409, "undo twice 409")
r = A.post(B + f"/api/proposals/{J1}/redo")
PL2 = r.json().get("list_id")
check(r.ok and r.json()["redone"] == 4 and PL2, f"redo: created again ({r.text[:200]})")
check(len(dbx("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at IS NULL", (PL2,))) == 4 and
      dbx("SELECT name FROM lists WHERE id=?", (PL2,)) == [("ACME film",)], "redo: same list + entries")
# undo after someone changed a task: that one stays, the rest goes to the trash, the list stays
ch = dbx("SELECT id FROM tasks WHERE list_id=? AND title='Shoot day'", (PL2,))[0][0]
time.sleep(1.1)  # the change must be later than the apply (seconds)
check(A.patch(B + f"/api/tasks/{ch}", json={"title": "Shoot day (moved)", "due": "2031-05-12"}).ok, "change one task")
r = A.post(B + f"/api/proposals/{J1}/undo")
check(r.ok and r.json()["undone"] == 3 and any("Shoot day" in x for x in r.json()["skipped"]), f"undo: changed task skipped ({r.text[:200]})")
check(dbx("SELECT 1 FROM lists WHERE id=?", (PL2,)) and dbx("SELECT deleted_at IS NULL FROM tasks WHERE id=?", (ch,)) == [(1,)],
      "list + the changed task stay")
check(len(dbx("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at IS NOT NULL", (PL2,))) == 3, "the others are in the trash")
r = A.post(B + f"/api/proposals/{J1}/redo")
check(r.ok and r.json()["redone"] == 3 and len(dbx("SELECT 1 FROM tasks WHERE list_id=? AND deleted_at IS NULL", (PL2,))) == 4, "redo restores them")

# ================================================================== #261 break down a task
T = A.post(B + "/api/tasks", json={"title": "Plan the offsite", "content": "Budget 5k, 12 people", "list_id": TEAM}).json()["id"]
A.post(B + "/api/tasks", json={"title": "Existing sub", "parent_id": T})
r = ask(A, agent_id=AG, kind="subtasks", task_id=T, hint="at most 4 steps")
check(r.status_code == 201 and r.json()["task_id"] == T, f"break down: 201 ({r.text[:200]})")
J2 = r.json()["id"]
inp = cl.get(f"/agent/jobs/{J2}").json()["input"]
check(inp == {"task": {"id": T, "title": "Plan the offsite", "notes": "Budget 5k, 12 people", "due": None, "subtasks": ["Existing sub"]},
              "hint": "at most 4 steps"}, f"input: the task + hint: {inp}")
check(ask(Ca, agent_id=AG2, kind="subtasks", task_id=T).status_code in (403, 404), "a task carol cannot see: refused")
check(ask(A, agent_id=AG, kind="subtasks", task_id=T + 999).status_code == 404, "unknown task 404")
SUB = {"items": [{"title": "Venue", "estimate": 60}, {"title": "Invite", "due": "2031-03-01"}, {"title": "Book"}],
       "dependencies": [[2, 0], [1, 2]]}
check(cl.post(f"/agent/jobs/{J2}/proposal", json={**SUB, "dependencies": [[0, 1], [1, 0]]}).status_code == 400, "subtasks: cycle 400")
check(cl.post(f"/agent/jobs/{J2}/proposal", json={**SUB, "dependencies": [[0, 9]]}).status_code == 400, "subtasks: bad index 400")
check(cl.post(f"/agent/jobs/{J2}/proposal", json={"items": [{"title": "x", "estimate": -5}]}).status_code == 400, "subtasks: bad estimate 400")
check(cl.post(f"/agent/jobs/{J2}/proposal", json={"items": []}).status_code == 400, "subtasks: empty 400")
check(cl.post(f"/agent/jobs/{J2}/proposal", json=SUB).status_code == 201, "subtasks: valid 201")
r = A.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0", "1", "2"], "edits": {"1": {"title": "Send invites"}}})
check(r.ok and r.json()["created"] == 3, f"subtasks applied ({r.text[:200]})")
subs = dbx("SELECT id, title, parent_id, created_by, list_id, duration FROM tasks WHERE parent_id=? ORDER BY sort, id", (T,))
check([x[1] for x in subs] == ["Existing sub", "Venue", "Send invites", "Book"] and all(x[3] == ALICE and x[4] == TEAM for x in subs[1:]),
      f"subtasks under the task, as the person: {[x[1] for x in subs]}")
check(subs[1][5] == 60, "estimate -> duration (minutes)")
sid = {x[1]: x[0] for x in subs}
check(set(dbx("SELECT task_id, blocker_id FROM task_deps WHERE task_id IN (?,?,?)", (sid["Venue"], sid["Send invites"], sid["Book"])))
      == {(sid["Book"], sid["Venue"]), (sid["Send invites"], sid["Book"])}, "subtask dependencies")
check(any(a["kind"] == "subtask" for a in timeline(A, T)["activity"]), "the task's history names the new subtasks")
r = A.post(B + f"/api/proposals/{J2}/undo")
check(r.ok and r.json()["undone"] == 3 and len(dbx("SELECT 1 FROM tasks WHERE parent_id=? AND deleted_at IS NULL", (T,))) == 1, "undo: subtasks trashed")
r = A.post(B + f"/api/proposals/{J2}/redo")
check(r.ok and r.json()["redone"] == 3 and len(dbx("SELECT 1 FROM tasks WHERE parent_id=? AND deleted_at IS NULL", (T,))) == 4, "redo: back")

# ================================================================== #262 sort the inbox: consent
I1 = A.post(B + "/api/tasks", json={"title": "call the printer about the flyer"}).json()["id"]
I2 = A.post(B + "/api/tasks", json={"title": "bday gift mum", "content": "something with plants"}).json()["id"]
I3 = A.post(B + "/api/tasks", json={"title": "SECRET-DIAGNOSIS doctor"}).json()["id"]
A.patch(B + f"/api/tasks/{I1}", json={"tags": ["mine"]})
BT = Bo.post(B + "/api/tasks", json={"title": "bob's inbox"}).json()["id"]
check(ask(A, agent_id=AG, kind="triage", task_ids=[I1, BT]).status_code == 400, "someone else's task cannot be sent")
check(ask(A, agent_id=AG, kind="triage", task_ids=[I1], lists=[PRIV + 999]).status_code == 400, "a list I cannot change cannot be offered")
r = ask(A, agent_id=AG, kind="triage", task_ids=[I1, I2], lists=[TEAM])
check(r.status_code == 201, f"triage: 201 ({r.text[:200]})")
J3 = r.json()["id"]
ev = [e for e in events(cl) if e["event"] == "job_request" and e["data"]["job"]["id"] == J3][0]
inp = ev["data"]["input"]
check(sorted(x["task_id"] for x in inp["items"]) == sorted([I1, I2]) and [x["id"] for x in inp["lists"]] == [TEAM], "input: only the chosen items + lists")
check(inp["lists"][0]["sections"] == [{"id": SEC, "name": "Doing"}], "lists carry their sections")
check("SECRET-DIAGNOSIS" not in json.dumps(events(cl)) and "Private stuff" not in json.dumps(ev), "nothing else of the inbox / other lists leaks")
for x in (I1, I2, I3):
    check(cl.get(f"/tasks/{x}").status_code == 404, f"agent cannot read inbox item {x}")
check(cl.post(f"/agent/jobs/{J3}/proposal", json={"items": [{"task_id": I3, "list_id": TEAM}]}).status_code == 400, "an item not sent: 400")
check(cl.post(f"/agent/jobs/{J3}/proposal", json={"items": [{"task_id": I1, "list_id": PRIV}]}).status_code == 400, "a list not offered: 400")
check(cl.post(f"/agent/jobs/{J3}/proposal", json={"items": [{"task_id": I1, "section_id": SEC}]}).status_code == 400, "a section without its list: 400")
check(cl.post(f"/agent/jobs/{J3}/proposal", json={"items": [{"task_id": I1}, {"task_id": I1}]}).status_code == 400, "an item twice: 400")
TRI = {"items": [{"task_id": I1, "list_id": TEAM, "section_id": SEC, "tags": ["print", "#Mine"], "priority": "medium"},
                 {"task_id": I2, "rewrite_title": "Birthday gift for Mum", "due": "2031-04-02", "tags": ["family"]}]}
check(cl.post(f"/agent/jobs/{J3}/proposal", json=TRI).status_code == 201, "triage: valid 201")
r = A.post(B + f"/api/proposals/{J3}/apply", json={"select": ["0", "1"], "edits": {"1": {"due": "2031-04-03"}}})
check(r.ok and r.json()["changed"] == 2, f"triage applied ({r.text[:200]})")
t1, t2 = task(A, I1), task(A, I2)
check(t1["list_id"] == TEAM and t1["section_id"] == SEC and t1["priority"] == 3 and sorted(t1["tags"]) == ["mine", "print"],
      f"I1 moved to Team / Doing, medium, personal tags merged: {t1['list_id']} {t1['section_id']} {t1['tags']}")
check(t2["title"] == "Birthday gift for Mum" and t2["due"] == "2031-04-03" and "family" in t2["tags"], "I2 renamed, dated (edit wins)")
check(any(a["kind"] == "proposal" and a["data"].get("agent") == AG and a["user_id"] == ALICE for a in timeline(A, I1)["activity"]),
      "history: applied a proposal by the agent (as the person)")
check(task(A, I3)["list_id"] == t2["list_id"], "I3 untouched")
r = A.post(B + f"/api/proposals/{J3}/undo")
t1, t2 = task(A, I1), task(A, I2)
check(r.ok and t1["list_id"] == t2["list_id"] and t1["section_id"] is None and t1["tags"] == ["mine"] and t2["title"] == "bday gift mum"
      and t2["due"] is None, f"undo: back in the inbox, old title / tags ({r.text[:200]})")
r = A.post(B + f"/api/proposals/{J3}/redo")
check(r.ok and task(A, I1)["list_id"] == TEAM and task(A, I2)["title"] == "Birthday gift for Mum", "redo: sorted again")
check(task(Bo, I1)["title"] == "call the printer about the flyer", "bob sees the moved item in Team (shared list)")
# "all open inbox items" (max 100): the ones left
r = ask(A, agent_id=AG, kind="triage")
check(r.status_code == 201 and sorted(x["task_id"] for x in cl.get(f"/agent/jobs/{r.json()['id']}").json()["input"]["items"]) == [I2, I3],
      "task_ids omitted = every open main task of my inbox")
A.post(B + f"/api/proposals/{r.json()['id']}/discard")

# ================================================================== #263 tasks from meeting notes
NOTES = "Bob books the studio by Friday. Alice writes the brief. Someone orders pizza."
r = ask(A, agent_id=AG, kind="extract", list_id=TEAM, text=NOTES)
check(r.status_code == 201, f"extract: 201 ({r.text[:200]})")
J4 = r.json()["id"]
inp = cl.get(f"/agent/jobs/{J4}").json()["input"]
check(inp["text"] == NOTES and inp["list"]["id"] == TEAM and inp["list"]["sections"] == ["Doing"], "extract input: notes + list")
check(sorted(m["id"] for m in inp["members"]) == sorted([ALICE, BOB]), f"members = the people (no agents): {inp['members']}")
check(ask(Ca, agent_id=AG2, kind="extract", list_id=TEAM, text="x").status_code in (403, 404), "extract: a list carol cannot change")
check(cl.post(f"/agent/jobs/{J4}/proposal", json={"tasks": [{"title": "x", "assignee_id": CAROL}]}).status_code == 400, "assignee not a member: 400")
EX = {"tasks": [{"title": "Book the studio", "assignee_id": BOB, "due": "2031-02-07", "section": "Doing"},
                {"title": "Write the brief", "assignee_id": ALICE, "section": "Briefs"},
                {"title": "Order pizza"}]}
check(cl.post(f"/agent/jobs/{J4}/proposal", json=EX).status_code == 201, "extract: valid 201")
bnews0 = len(Bo.get(B + "/api/news").json()["items"])
r = A.post(B + f"/api/proposals/{J4}/apply", json={"select": ["0", "1"], "edits": {"1": {"assignee_id": None}}})
check(r.ok and r.json()["created"] == 2, f"extract applied ({r.text[:200]})")
ex = dbx("SELECT title, assignee_id, created_by, section_id FROM tasks WHERE list_id=? AND title IN ('Book the studio','Write the brief','Order pizza')", (TEAM,))
ex = {x[0]: x for x in ex}
check(set(ex) == {"Book the studio", "Write the brief"}, "only the selected")
check(ex["Book the studio"][1] == BOB and ex["Book the studio"][2] == ALICE and ex["Book the studio"][3] == SEC, "assigned to Bob, created by Alice, section")
check(ex["Write the brief"][1] is None and dbx("SELECT name FROM sections WHERE id=?", (ex["Write the brief"][3],)) == [("Briefs",)],
      "edit removed the assignee; a new section was created")
check(len(Bo.get(B + "/api/news").json()["items"]) > bnews0, "Bob gets the assignment News")
r = A.post(B + f"/api/proposals/{J4}/undo")
check(r.ok and r.json()["undone"] == 2 and not dbx("SELECT 1 FROM tasks WHERE title='Book the studio' AND deleted_at IS NULL"), "extract undo")

# ================================================================== discard, stop, limits
r = ask(Bo, agent_id=AG, kind="project", text="bob's plan")
J5 = r.json()["id"]
check(cl.post(f"/agent/jobs/{J5}/proposal", json={"name": "P", "tasks": [{"title": "t"}]}).status_code == 201, "bob's proposal")
seq2 = max(e["seq"] for e in events(cl))
check(A.post(B + f"/api/proposals/{J5}/discard").status_code == 404, "alice cannot discard bob's proposal")
check(Bo.post(B + f"/api/proposals/{J5}/discard").ok, "discard")
j = dbx("SELECT state, prop_state, action FROM agent_jobs WHERE id=?", (J5,))[0]
check(j == ("stopped", "discarded", "reject"), f"discarded: {j}")
ev = [e for e in events(cl, seq2) if e["event"] == "job"]
check(ev and ev[-1]["data"]["action"] == "reject" and ev[-1]["data"]["proposal"]["state"] == "discarded", "agent told: reject / discarded")
check(cl.post(f"/agent/jobs/{J5}/proposal", json={"name": "P", "tasks": [{"title": "t"}]}).status_code == 409, "submit after discard 409")
check(Bo.post(B + f"/api/proposals/{J5}/discard").status_code == 409, "discard twice 409")
r = ask(Bo, agent_id=AG, kind="project", text="stop me")
check(Bo.post(B + f"/api/agents/jobs/{r.json()['id']}/action", json={"action": "stop"}).ok and
      dbx("SELECT prop_state FROM agent_jobs WHERE id=?", (r.json()["id"],)) == [("discarded",)], "Stop discards the proposal")
opened = [ask(Ca, agent_id=AG2, kind="project", text=f"p{i}") for i in range(11)] if A.patch(B + f"/api/admin/agents/{AG2}", json={"proposals": "all"}).ok else []
check([x.status_code for x in opened].count(201) == 10 and opened[-1].status_code == 429, f"at most 10 open requests: {[x.status_code for x in opened]}")

# ================================================================== spec, notification row
spec = requests.get(V + "/openapi.json").json()
check("get" in spec["paths"].get("/agent/jobs/{id}", {}) and "post" in spec["paths"].get("/agent/jobs/{id}/proposal", {}), "spec documents the routes")
check("job_request" in json.dumps(spec["components"]["schemas"]["AgentEvent"]), "spec: event job_request")
m = A.get(B + "/api/state").json()["notify"]
check(m.get("proposal") == {"news": True, "push": True}, f"notification row proposal (News + push on): {m.get('proposal')}")
check(A.patch(B + "/api/settings", json={"notify": {"proposal": {"news": False}}}).ok and
      A.get(B + "/api/state").json()["notify"]["proposal"]["news"] is False, "the row can be switched off")

# ================================================================== retention (30 days) after a restart
old = (date.today() - timedelta(days=31)).isoformat() + "T00:00:00Z"
dbx_w = sqlite3.connect(os.path.join(DATA, "tasks.db"))
dbx_w.execute("UPDATE agent_jobs SET updated_at=? WHERE id IN (?,?)", (old, J2, J5))
dbx_w.commit()
dbx_w.close()
start(keep=True)
for _ in range(20):
    if not dbx("SELECT 1 FROM agent_jobs WHERE id IN (?,?)", (J2, J5)):
        break
    time.sleep(0.5)
check(not dbx("SELECT 1 FROM agent_jobs WHERE id IN (?,?)", (J2, J5)), "proposal jobs older than 30 days are gone (with their input)")
check(dbx("SELECT 1 FROM agent_jobs WHERE id=?", (J1,)) and dbx("SELECT 1 FROM agent_jobs WHERE id=?", (PJ,)), "newer ones + plain jobs stay")
check(dbx("SELECT 1 FROM tasks WHERE parent_id=? AND deleted_at IS NULL", (T,)), "the tasks it created stay (they are the person's)")

print(f"p230_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
