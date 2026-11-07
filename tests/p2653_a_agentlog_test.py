#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.653.0 A (#5079): the history of an agent's own decisions reads in words, page by page, plus the decisions it writes itself
 - a change of a task that is no plan of its dates is kind task_changed with the task's title and the changed fields (only
   their names), no longer "other" (the dialog showed "Changed PATCH /api/v1/tasks/4501"); unlocking only is a change too
 - a line from before 2.653 (kind other, PATCH /api/v1/tasks/<id>) reads as task_changed
 - POST /api/v1/agent/decisions {title, ref?}: kind decision in the token's OWN history (no id in the path), title trimmed
   and cut to 200, empty / no text 400, unknown fields 400, no Undo, on every control level (approve_all too); a person 403;
   at most 30 a minute (429)
 - GET /api/agents/<id>/control/history?before=&limit=: the whole history page by page ({history, more}); limit 1..200;
   another person / an instance admin for a personal agent of someone else 404; another agent's lines never show
 - a team agent of an organisation (the instance admin) and a person without an organisation with their own agent: the same
 - freelancer-matrix: agents   tenant-matrix: agent
usage: p2653_a_agentlog_test.py <datadir>      (KMT_NOSTART=1 / P2653A_NOSTART=1: a running server)"""
import os
import re

import requests

import kt
from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup

V = B + "/api/v1"
os.environ["KALMIDO_AGENT_CONTROL_NEW"] = "approve_all"  # the real default: the decision line works on every level
fresh(prefix="P2653A")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
OID, O = freelancer(B, A, "otto")
SCOPES = ["read", "tasks:write", "comments"]


def ctl(s, aid, patch=None):
    r = s.patch(B + f"/api/agents/{aid}/control", json=patch) if patch is not None else s.get(B + f"/api/agents/{aid}/control")
    check(r.ok, f"control {patch} -> {r.status_code} {r.text[:200]}")
    return r.json() if r.ok else {}


def hist(s, aid):
    return ctl(s, aid).get("history") or []


def page(s, aid, **q):
    return s.get(B + f"/api/agents/{aid}/control/history", params=q)


def decide(h, **b):
    return requests.post(V + "/agent/decisions", headers=h, json=b)


def run(who, S, AID, H, L):
    def api(method, path, **kw):
        h = dict(H)
        if method == "PATCH" and re.fullmatch(r"/tasks/\d+", path):  # 2.564.0 (#4702): the version it read
            got = requests.get(V + path, headers=H)
            if got.ok:
                h["If-Match"] = got.json()["updated_at"]
        return requests.request(method, V + path, headers=h, **kw)

    # ---- a decision line on approve_all (its own channel: no card needed)
    check(ctl(S, AID).get("control", {}).get("level") == "approve_all", f"{who}: a new agent starts on approve_all")
    r = decide(H, title="  Answered the job card myself -\n tick off 2.599  ", ref="#2599")
    j = r.json() if r.status_code == 201 else {}
    check(r.status_code == 201 and j.get("kind") == "decision" and j.get("title") == "Answered the job card myself - tick off 2.599"
          and j.get("ref") == "#2599", f"{who}: a decision line, trimmed, on approve_all {r.status_code} {r.text[:200]}")
    h = [x for x in hist(S, AID) if x["kind"] == "decision"]
    check(h and h[0]["title"] == "Answered the job card myself - tick off 2.599" and h[0]["ref"] == "#2599" and h[0]["can_undo"] is False,
          f"{who}: the owner sees it in the history, without Undo {h[:1]}")
    r = decide(H, title="x" * 300, ref="y" * 300)
    check(r.status_code == 201 and len(r.json()["title"]) == 200 and len(r.json()["ref"]) == 200, f"{who}: title / ref cut to 200 {r.status_code}")
    for bad in ({"title": ""}, {"title": "   "}, {"title": 5}, {}, {"title": "ok", "ref": 7}, {"title": "ok", "kind": "other"}):
        check(decide(H, **bad).status_code == 400, f"{who}: {bad} -> 400")
    r = S.post(V + "/agent/decisions", json={"title": "a person"})
    check(r.status_code in (401, 403), f"{who}: a person's session cannot write a decision line {r.status_code}")

    # ---- task changes in words (free: changes pass without a card)
    ctl(S, AID, {"level": "free"})
    r = api("POST", "/tasks", json={"title": "Release notes", "list_id": L})
    check(r.status_code == 201, f"{who}: the agent creates a task {r.status_code} {r.text[:150]}")
    T = r.json()["id"]
    check(api("PATCH", f"/tasks/{T}", json={"locked": False}).ok, f"{who}: unlocks its task")
    check(api("PATCH", f"/tasks/{T}", json={"title": "Release notes v2"}).ok, f"{who}: renames its task")
    check(api("PATCH", f"/tasks/{T}", json={"notes": "a note", "priority": "high"}).ok, f"{who}: changes notes + priority")
    h = hist(S, AID)
    ch = [x for x in h if x["kind"] == "task_changed"]
    check(len(ch) == 3, f"{who}: three lines task_changed (unlock, title, notes + priority) {[(x['kind'], x['fields']) for x in h[:5]]}")
    if len(ch) == 3:
        check(ch[2]["fields"] == ["locked"] and ch[2]["title"] == "Release notes", f"{who}: unlocking names the field and the title {ch[2]}")
        check(ch[1]["fields"] == ["title"] and ch[1]["title"] == "Release notes v2", f"{who}: the new title, the field title {ch[1]}")
        check(ch[0]["fields"] == ["notes", "priority"] and ch[0]["title"] == "Release notes v2" and ch[0]["list_name"],
              f"{who}: several fields, the title, the project {ch[0]}")
    check(not [x for x in h if x["kind"] == "other"], f"{who}: no line of kind other for task changes")

    # ---- a line from before 2.653.0 reads in words
    kt.dbx("""INSERT INTO agent_decisions(agent_id,list_id,step,level,kind,method,path,title,via,created_at)
              VALUES(?,?,'change','free','other','PATCH',?,'','self','2026-11-01T10:00:00+00:00')""", (AID, L, f"/api/v1/tasks/{T}"))
    old = [x for x in page(S, AID, limit=200).json()["history"] if x["created_at"].startswith("2026-11-01")]
    check(old and old[0]["kind"] == "task_changed" and old[0]["area"] == "tasks", f"{who}: an old PATCH line reads as task_changed {old[:1]}")

    # ---- the whole history, page by page
    n = len(page(S, AID, limit=200).json()["history"])
    p1 = page(S, AID, limit=2).json()
    check(len(p1["history"]) == 2 and p1["more"] is True, f"{who}: page 1 of 2 lines, more {p1.get('more')}")
    p2 = page(S, AID, limit=200, before=p1["history"][-1]["id"]).json()
    check(len(p2["history"]) == n - 2 and p2["more"] is False and p2["history"][0]["id"] < p1["history"][-1]["id"],
          f"{who}: page 2 holds the rest, older ones {len(p2['history'])} of {n}")
    for q in ({"limit": 0}, {"limit": 201}, {"limit": "x"}, {"before": -1}):
        check(page(S, AID, **q).status_code == 400, f"{who}: history {q} -> 400")


# ================================================================== a team agent of the organisation (the instance admin)
r = A.post(B + "/api/admin/agents", json={"scopes": SCOPES, "username": "teambot", "display_name": "Teambot"})
TA, TAH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
TL = A.post(B + "/api/lists", json={"name": "Team desk"}).json()["id"]
A.put(B + f"/api/lists/{TL}/members", json={"user_id": TA, "role": "edit"})
run("team agent", A, TA, TAH, TL)

# ================================================================== freelancer-matrix: agents (a person without an organisation)
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": SCOPES})
check(r.status_code in (200, 201), f"personal agent {r.status_code} {r.text[:150]}")
FA, FAH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
FL = F.post(B + "/api/lists", json={"name": "Frida desk"}).json()["id"]
check(F.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "the freelancer shares the list with the agent")
run("freelancer", F, FA, FAH, FL)

# ================================================================== tenant-matrix: agent (nobody else reads or writes it)
r = O.post(B + "/api/my/agents", json={"username": "ottobot", "display_name": "Ottobot", "scopes": SCOPES})
OA, OAH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
check(decide(OAH, title="Otto's own decision").status_code == 201, "another person's agent writes its own line")
check(not [x for x in hist(F, FA) if x["title"] == "Otto's own decision"], "... it never shows in Frida's agent's history")
check(not [x for x in page(F, FA, limit=200).json()["history"] if x["title"] == "Otto's own decision"], "... nor in its whole history")
check([x for x in hist(O, OA) if x["title"] == "Otto's own decision"], "... only in Otto's agent's history")
check(O.get(B + f"/api/agents/{FA}/control/history").status_code == 404, "another person: the whole history 404")
check(A.get(B + f"/api/agents/{FA}/control/history").status_code == 404, "an instance admin: a personal agent of someone else 404")
check(F.get(B + f"/api/agents/{TA}/control/history").status_code == 404, "a freelancer: the organisation's team agent 404")
r = requests.post(V + "/agent/decisions", headers={"X-Requested-With": "kalmido"}, json={"title": "no token"})
check(r.status_code in (401, 403), f"no token: no decision line {r.status_code}")
# tenant: POST /api/v1/agent/decisions -- no agent id in the path: each token writes its own history only (checked above)

# ---- the rate limit (30 a minute and agent)
codes = [decide(OAH, title=f"line {i}").status_code for i in range(35)]
check(429 in codes and codes[0] == 201, f"at most 30 decisions a minute -> 429 {codes[-6:]}")

raise SystemExit(done("p2653_a_agentlog"))
