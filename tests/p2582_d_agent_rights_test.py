#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.582.0 D (#4380, audit #2483 M3 + M4): agents only within what they were given.
freelancer-matrix: agents (the person who set the agent up has no organisation)
 M3 time entries:
 - an agent token without the scope time: GET /api/v1/time/entries -> 403 with required_scope time (before: read was enough);
   its own timer (GET /time/timer) stays readable; the OpenAPI document names it (x-kalmido-agent-scope)
 - with the scope time and scope=all: other people's entries only where the agent is a project admin AND the person who set
   it up is one too (the freelancer's own project: yes; a colleague's project where the freelancer only edits: no)
 - MCP: an agent token without time does not get list_time_entries, a person's read token does
 M4 proposals:
 - "Break down" a task of a health / a budget project -> 400 (as extract), a plain task -> 201 (counter-check)
 - "Plan my day" and "Sort the basket": no task / no target project of a health or budget project in the job's input
usage: p2582_d_agent_rights_test.py <datadir>      (KMT_NOSTART=1 / P2582D_NOSTART=1: a running server)"""
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

from freelancer_fixture import freelancer
from kt import B, check, done, dbx, fresh, setup

N = os.path.dirname(os.path.abspath(__file__))
sp = importlib.util.spec_from_file_location("kalmido_mcp", os.path.join(N, "..", "mcp", "kalmido_mcp.py"))
mcp = importlib.util.module_from_spec(sp)
sp.loader.exec_module(mcp)

V = B + "/api/v1"
fresh(prefix="P2582D", env={"KALMIDO_API_RATE": "100000"})
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
BOB, Bo = freelancer(B, A, "bobby")

r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": ["read", "tasks:write"]})
check(r.status_code in (200, 201), f"a personal agent {r.status_code} {r.text[:120]}")
FA, FH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}

# ---------------------------------------------------------------- M3: the projects, members and entries
P = F.post(B + "/api/lists", json={"name": "Frida's project"}).json()["id"]
Q = Bo.post(B + "/api/lists", json={"name": "Bobby's project"}).json()["id"]
NOW = datetime.now(timezone.utc).replace(microsecond=0)
for lid, uid, role in ((P, BOB, "edit"), (P, FA, "admin"), (Q, FID, "edit"), (Q, FA, "admin")):
    dbx("INSERT INTO list_members(list_id, user_id, role, added_at) VALUES (?, ?, ?, ?)", (lid, uid, role, NOW.isoformat()))
for uid, lid, note in ((FID, P, "ZQXF-P"), (BOB, P, "ZQXBOB-P"), (BOB, Q, "ZQXBOB-Q")):
    s = NOW - timedelta(days=1, hours=2)
    dbx("""INSERT INTO time_entries(user_id, list_id, start, "end", seconds, note, created_at, updated_at)
           VALUES (?, ?, ?, ?, 1800, ?, ?, ?)""", (uid, lid, s.isoformat(), (s + timedelta(minutes=30)).isoformat(), note,
                                                   NOW.isoformat(), NOW.isoformat()))
check(len(dbx("SELECT id FROM time_entries WHERE note LIKE 'ZQX%'")) == 3, "three entries")

r = requests.get(V + "/time/entries?scope=all", headers=FH)
check(r.status_code == 403 and (r.json().get("error") or {}).get("required_scope") == "time",
      f"agent without the scope time: 403 required_scope time {r.status_code} {r.text[:200]}")
r = requests.get(V + "/time/entries", headers=FH)
check(r.status_code == 403 and "ZQX" not in r.text, f"agent without time, scope mine: 403 {r.status_code}")
r = requests.get(V + "/time/timer", headers=FH)
check(r.status_code == 200, f"its own timer stays readable (counter-check) {r.status_code} {r.text[:120]}")
spec = requests.get(V + "/openapi.json", timeout=30).json()
check(spec["paths"]["/time/entries"]["get"].get("x-kalmido-agent-scope") == "time"
      and spec["paths"]["/time/entries"]["get"].get("x-kalmido-scope") == "read", "OpenAPI: read for people, time for agents")

r = F.patch(B + f"/api/my/agents/{FA}", json={"scopes": ["read", "tasks:write", "time"]})
check(r.ok, f"the owner grants the scope time {r.status_code} {r.text[:160]}")
r = requests.get(V + "/time/entries?scope=all", headers=FH)
check(r.status_code == 200, f"with time: 200 {r.status_code} {r.text[:200]}")
notes = {e["note"] for e in r.json().get("data", [])}
check({"ZQXF-P", "ZQXBOB-P"} <= notes, f"its owner's project: everyone's entries (counter-check) {notes}")
check("ZQXBOB-Q" not in notes, f"a project where only the agent is admin, not its owner: no other people's entries {notes}")
r = requests.get(V + f"/time/entries?scope=all&list_id={Q}", headers=FH)
check(r.status_code == 200 and not r.json().get("data"), f"list_id of that project: empty {r.text[:200]}")
check("ZQXBOB-Q" in Bo.get(B + "/api/time/entries?scope=all").text, "Bobby still sees his own entry (counter-check)")


# ---------------------------------------------------------------- M3: MCP tool list (static, the module's own check)
class Me:
    def __init__(self, kind, scopes):
        self.v = {"kind": kind, "token": {"effective_scopes": scopes}}

    def call(self, method, path, **kw):
        return self.v


def allowed(kind, scopes, name):
    mcp._ME.update(at=0.0, v=None)
    return mcp.tool_allowed(Me(kind, scopes), name)


check(not allowed("agent", ["read", "tasks:write"], "list_time_entries"), "MCP: an agent without time has no list_time_entries")
check(allowed("agent", ["read", "time"], "list_time_entries"), "MCP: an agent with time has it")
check(allowed("user", ["read"], "list_time_entries"), "MCP: a person's read token keeps it (counter-check)")
check(allowed("agent", ["read"], "get_timer"), "MCP: get_timer stays read")

# ---------------------------------------------------------------- M4: health / budget never reach an agent through a proposal
HL = F.post(B + "/api/lists", json={"name": "ZQXHEALTH doctors"}).json()["id"]
BL = F.post(B + "/api/lists", json={"name": "ZQXBUDGET money"}).json()["id"]
dbx("UPDATE lists SET life='health' WHERE id=?", (HL,))
dbx("UPDATE lists SET life='budget' WHERE id=?", (BL,))


def task(title, **kw):
    r = F.post(B + "/api/tasks", json={"title": title, **kw})
    check(r.ok, f"task {title}: {r.status_code} {r.text[:120]}")
    return r.json()["id"]


def ask(**b):
    return F.post(B + "/api/proposals", json={"agent_id": FA, **b})


def job_text(jid):
    ev = [e for e in requests.get(V + "/agent/events?since=0&limit=500", headers=FH).json().get("data", [])
          if e["event"] == "job_request" and (e["data"].get("job") or {}).get("id") == jid]
    r = requests.get(V + f"/agent/jobs/{jid}", headers=FH)
    check(r.status_code == 200, f"job {jid}: GET {r.status_code} {r.text[:120]}")
    return json.dumps([x["data"] for x in ev]) + json.dumps(r.json())


T_OK = task("ZQXPLAIN write the offer", list_id=P)
T_H = task("ZQXHEALTH blood test", list_id=HL)
T_B = task("ZQXBUDGET pay the rent", list_id=BL)
check("ZQXHEALTH" in F.get(B + f"/api/tasks/{T_H}").text, "the person sees the health task (counter-check)")

for tid, what in ((T_H, "health"), (T_B, "budget")):
    r = ask(kind="subtasks", task_id=tid)
    check(r.status_code == 400 and "ZQX" not in r.text, f"break down a {what} task: 400 {r.status_code} {r.text[:160]}")
r = ask(kind="subtasks", task_id=T_OK)
check(r.status_code == 201, f"break down a plain task: 201 (counter-check) {r.status_code} {r.text[:160]}")

r = ask(kind="dayplan")
check(r.status_code == 201, f"dayplan: 201 {r.status_code} {r.text[:200]}")
txt = job_text(r.json()["id"])
check("ZQXPLAIN" in txt, f"dayplan: the plain task is there (counter-check) {txt[:300]}")
check("ZQXHEALTH" not in txt and "ZQXBUDGET" not in txt, f"dayplan: no health / budget task {txt[:400]}")
check(f'"task_id": {T_H}' not in txt and f'"task_id": {T_B}' not in txt, "dayplan: nor their ids")

task("ZQXPLAIN call the printer")
r = ask(kind="triage")
check(r.status_code == 201, f"triage: 201 {r.status_code} {r.text[:200]}")
txt = job_text(r.json()["id"])
check("Frida's project" in txt, f"triage: a plain project is a target (counter-check) {txt[:300]}")
check("ZQXHEALTH" not in txt and "ZQXBUDGET" not in txt, f"triage: no health / budget project as a target {txt[:400]}")
sys.exit(done("p2582_d_agent_rights"))
