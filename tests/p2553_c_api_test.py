#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.553.0 C (#3538) API tests, own container: the board's time limits and the time in a column in API v1 and MCP.
 - v1 sections carry dwell_warn_h / dwell_alert_h (null = none); PATCH /api/v1/sections/{id} and POST /lists/{id}/sections take
   them with the app's checks: 0 / null = none, one of them alone keeps the other, red must stay above yellow, out of range 400
 - rights as with wip_limit: a project shared read-only -> refused, one not shared -> 404, a token without "structure" ->
   403, nothing stored in each case
 - v1 tasks carry section_at (null until the task changes its column, then the stored time) and field_at {field id: ISO}
 - the MCP tool set_dwell_limits sends PATCH /sections/{id} with only the limits given (static, no server); in the toolset
   "tickets" and the scope "structure"
 - freelancer-matrix: the agent of a person without an organisation; the admin's agent the same
usage: p2553_c_api_test.py <datadir>      (KMT_NOSTART=1 / P2553C_NOSTART=1: a running server)"""
import os
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, setup

V = B + "/api/v1"
fresh(prefix="P2553C", env={"KALMIDO_API_RATE": "100000"})
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments,kanban"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)


def agent(s, name, scopes):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": scopes})
    check(r.status_code in (200, 201), f"{name}: agent created {r.status_code} {r.text[:120]}")
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


def lim(sid):
    return tuple(dbx("SELECT dwell_warn_h, dwell_alert_h FROM sections WHERE id=?", (sid,))[0])


def board(s, who, ag, role):
    r = s.post(B + "/api/lists", json={"name": f"Board {who} {role}"})
    check(r.ok, f"{who}: list {r.status_code}")
    lid = r.json()["id"]
    check(s.put(B + f"/api/lists/{lid}/members", json={"user_id": ag, "role": role}).ok, f"{who}: the agent gets {role}")
    return lid


def sec(s, lid, name):
    r = s.post(B + "/api/sections", json={"list_id": lid, "name": name})
    check(r.ok, f"section {name} {r.status_code}")
    return r.json()["id"]


def run(s, who):
    ag, H = agent(s, f"{who}bot", ["read", "tasks:write", "structure"])
    _, HR = agent(s, f"{who}reader", ["read", "tasks:write"])
    L = board(s, who, ag, "edit")
    S1, S2 = sec(s, L, "Doing"), sec(s, L, "Review")
    # ---- read: both limits, null by default
    got = {x["id"]: x for x in requests.get(V + f"/lists/{L}/sections", headers=H).json()["data"]}
    check(got[S1].get("dwell_warn_h", 1) is None and got[S1].get("dwell_alert_h", 1) is None and "dwell_warn_h" in got[S1],
          f"{who}: v1 sections carry the limits, null by default ({got[S1]})")
    # ---- set
    r = requests.patch(V + f"/sections/{S1}", json={"dwell_warn_h": 8, "dwell_alert_h": 48}, headers=H)
    check(r.status_code == 200 and r.json().get("dwell_warn_h") == 8 and r.json().get("dwell_alert_h") == 48 and lim(S1) == (8, 48),
          f"{who}: PATCH sets both ({r.status_code} {r.text[:160]} {lim(S1)})")
    r = requests.patch(V + f"/sections/{S1}", json={"dwell_warn_h": 12}, headers=H)
    check(r.status_code == 200 and lim(S1) == (12, 48), f"{who}: one alone keeps the other ({r.status_code} {lim(S1)})")
    for bad in ({"dwell_alert_h": 12}, {"dwell_warn_h": 9000}, {"dwell_warn_h": -1}, {"dwell_warn_h": "x"}):
        r = requests.patch(V + f"/sections/{S1}", json=bad, headers=H)
        check(r.status_code == 400 and lim(S1) == (12, 48), f"{who}: {bad}: 400, unchanged ({r.status_code} {lim(S1)})")
    r = requests.patch(V + f"/sections/{S1}", json={"dwell_warn_h": 0, "dwell_alert_h": None}, headers=H)
    check(r.status_code == 200 and lim(S1) == (None, None) and r.json().get("dwell_warn_h") is None,
          f"{who}: 0 / null = no limit ({r.status_code} {lim(S1)})")
    r = requests.post(V + f"/lists/{L}/sections", json={"name": "Waiting", "dwell_warn_h": 24, "dwell_alert_h": 72}, headers=H)
    check(r.status_code == 201 and r.json().get("dwell_warn_h") == 24 and lim(r.json()["id"]) == (24, 72),
          f"{who}: POST takes them ({r.status_code} {r.text[:160]})")
    r = requests.post(V + f"/lists/{L}/sections", json={"name": "Bad", "dwell_warn_h": 10, "dwell_alert_h": 3}, headers=H)
    check(r.status_code == 400, f"{who}: POST with red under yellow: 400 ({r.status_code})")
    # ---- rights (like wip_limit)
    RO = board(s, who, ag, "view")
    SR = sec(s, RO, "Read only")
    r = requests.patch(V + f"/sections/{SR}", json={"dwell_warn_h": 5}, headers=H)
    check(r.status_code in (403, 404) and lim(SR) == (None, None), f"{who}: a read-only project: refused ({r.status_code} {lim(SR)})")
    r = s.post(B + "/api/lists", json={"name": f"Private {who}"})
    SP = sec(s, r.json()["id"], "Mine")
    r = requests.patch(V + f"/sections/{SP}", json={"dwell_warn_h": 5}, headers=H)
    check(r.status_code == 404 and lim(SP) == (None, None), f"{who}: a project not shared: 404 ({r.status_code})")
    r = requests.patch(V + f"/sections/{S1}", json={"dwell_warn_h": 5}, headers=HR)
    check(r.status_code == 403 and lim(S1) == (None, None), f"{who}: a token without structure: 403 ({r.status_code})")
    # ---- tasks: section_at and field_at
    r = s.post(B + "/api/tasks", json={"title": f"Card {who}", "list_id": L, "section_id": S1})
    T = r.json()["id"]
    t = requests.get(V + f"/tasks/{T}", headers=H).json()
    check("section_at" in t and t["section_at"] is None and t.get("field_at") == {},
          f"{who}: a new task: section_at null, field_at empty ({t.get('section_at')!r} {t.get('field_at')!r})")
    s.patch(B + f"/api/tasks/{T}", json={"section_id": S2})
    stored = dbx("SELECT section_at FROM tasks WHERE id=?", (T,))[0][0]
    t = requests.get(V + f"/tasks/{T}", headers=H).json()
    check(stored and t.get("section_at") == stored, f"{who}: after a move v1 carries section_at ({t.get('section_at')} = {stored})")
    r = s.post(B + f"/api/lists/{L}/fields", json={"name": "Stage", "type": "text"})
    FLD = str(r.json().get("id"))
    s.patch(B + f"/api/tasks/{T}", json={"fields": {FLD: "build"}})
    sat = dbx("SELECT set_at FROM task_field_values WHERE task_id=? AND field_id=?", (T, int(FLD)))[0][0]
    t = requests.get(V + f"/tasks/{T}", headers=H).json()
    check(sat and t.get("field_at") == {FLD: sat}, f"{who}: v1 carries field_at ({t.get('field_at')} / {sat})")
    rows = requests.get(V + "/tasks", params={"list_id": L}, headers=H).json().get("data") or []
    one = next((x for x in rows if x["id"] == T), {})
    check(one.get("section_at") == stored and one.get("field_at") == {FLD: sat}, f"{who}: the task list carries both ({one.get('field_at')})")


run(F, "frida")  # freelancer-matrix: agents
run(A, "alice")

# ---- MCP tool (static: the call it makes)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcp"))
import kalmido_mcp as m  # noqa: E402

tool = next((t for t in m.TOOLS if t[0] == "set_dwell_limits"), None)
check(tool is not None, "MCP: set_dwell_limits exists")
calls = []


class Api:
    def call(self, method, path, body=None, **k):
        calls.append((method, path, body))
        return {}


tool[3](Api(), {"section_id": 7, "dwell_warn_h": 8})
tool[3](Api(), {"section_id": 7, "dwell_warn_h": None, "dwell_alert_h": 0})
check(calls == [("PATCH", "/sections/7", {"dwell_warn_h": 8}), ("PATCH", "/sections/7", {"dwell_warn_h": None, "dwell_alert_h": 0})],
      f"MCP: PATCH with only the given limits ({calls})")
check(m.TOOL_SCOPE.get("set_dwell_limits") == "structure", "MCP: scope structure like set_wip_limit")
check("set_dwell_limits" in m.TOOLSETS["tickets"].split(), "MCP: in the toolset tickets")
sys.exit(done("p2553_c_api"))
