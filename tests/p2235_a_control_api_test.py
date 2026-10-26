#!/usr/bin/env python3
"""2.235.0 A (#2891 #2900 #2901): the control level of an agent, enforced on the server
 - a new agent starts with approve_all ("Alles absegnen"): every write but its own channel answers 409 approval_required
   (step, level); its own channel (status, chat, approval cards) stays open
 - routine: create / plan / comment / tick off pass, other changes 409, deleting 409 (one-way step on every level)
 - free: changes pass, deleting still 409; the goal + own one-way steps reach the agent (GET /api/v1/agent "control")
 - an approval card with step {method, path}: after Yes exactly that request passes ONCE (header X-Kalmido-Approval), never
   another path / method, never before the Yes; a failed request gives the approval back
 - a project exception wins over the agent's level; a personal agent gets at most its owner's own rights in a project
   (edit -> routine; saving more answers 400)
 - each decision without a card is a line in the history; Undo: created -> trash, planned -> old date, ticked off -> open,
   comment -> gone (twice: 409); the agent gets decision_undone; every change of the settings: control_changed
 - #2901 the deadline: a card left unanswered ends by itself (reject / recommend / ask again once), the agent gets
   approval_expired; "recommend" never on a one-way step
 - an agent from before 2.235.0 (control '') works as before (no gate) until its owner picks a level
 - the same as a team agent of an instance admin; another person gets 404 (freelancer-matrix: agents)
usage: p2235_a_control_api_test.py <datadir>      (KMT_NOSTART=1 / P2235A_NOSTART=1: a running server)"""
import os
import sys
from datetime import timedelta, timezone

import requests

import kt
from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup, until
from testclock import now

V = B + "/api/v1"
HDR = "X-Kalmido-Approval"

os.environ["KALMIDO_AGENT_CONTROL_NEW"] = "approve_all"  # the real default (tests/start.sh starts other suites with legacy)
fresh(prefix="P2235A")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
OID, O = freelancer(B, A, "otto")
SCOPES = ["read", "tasks:write", "comments", "delete"]


def ago(hours=2):
    """A time stamp hours ago in the server's format (core/db.py iso)."""
    return (now() - timedelta(hours=hours)).astimezone(timezone.utc).isoformat(timespec="seconds")


def ctl(s, aid, patch=None, code=200):
    r = s.patch(B + f"/api/agents/{aid}/control", json=patch) if patch is not None else s.get(B + f"/api/agents/{aid}/control")
    check(r.status_code == code, f"control {patch} -> {r.status_code} (want {code}) {r.text[:200]}")
    return r.json() if r.ok else None


def events(h, name):
    r = requests.get(V + "/agent/events?since=0&limit=500", headers=h)
    return [e for e in r.json().get("data", []) if e.get("event") == name] if r.ok else []


def code(r):
    try:
        return r.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None


def hist(s, aid):
    return ctl(s, aid)["history"]


def run(who, S, UID, AID, H, L):
    """The whole round for one agent (personal of a freelancer / a team agent of the instance admin) in its project L."""
    def api(method, path, h=None, **kw):
        return requests.request(method, V + path, headers={**H, **(h or {})}, **kw)

    def card(step, recommend=None, one_way=None, title="May I?"):
        ap = {"title": title, **({"step": step} if step else {})}
        if recommend:
            ap["recommend"] = recommend
        if one_way:
            ap["one_way"] = True
        r = api("POST", f"/agent/chats/{UID}", json={"approval": ap})
        check(r.status_code == 201, f"{who}: approval card {r.status_code} {r.text[:200]}")
        return r.json()["id"]

    def answer(mid, choice="yes"):
        r = S.post(B + f"/api/agents/{AID}/chat/{mid}/choice", json={"choice_ids": [choice]})
        check(r.ok, f"{who}: answer {choice} {r.status_code} {r.text[:150]}")

    # ---- a new agent: approve_all
    st = ctl(S, AID)
    check(st["chosen"] is True and st["control"]["level"] == "approve_all", f"{who}: a new agent starts with approve_all {st.get('control')}")
    me = api("GET", "/agent").json()["control"]
    check(me["level"] == "approve_all" and me["enforced"] is True and [x["id"] for x in me["one_way"]["fixed"]] == ["delete", "costs", "login", "migration"],
          f"{who}: GET /api/v1/agent control {me}")
    r = api("POST", "/tasks", json={"title": "Blocked", "list_id": L})
    e = r.json().get("error", {}) if r.status_code == 409 else {}
    check(r.status_code == 409 and e.get("code") == "approval_required" and e.get("step") == "routine" and e.get("level") == "approve_all"
          and e.get("project_id") == L and HDR in e.get("message", ""), f"{who}: approve_all -> 409 approval_required {r.status_code} {r.text[:300]}")
    check(api("PUT", "/agent/status", json={"status": "working"}).ok, f"{who}: its own channel (status) stays open")
    check(not [t for t in requests.get(V + f"/tasks?list_id={L}", headers=H).json().get("data", []) if t["title"] == "Blocked"],
          f"{who}: the refused task was not created")

    # ---- routine
    st = ctl(S, AID, {"level": "routine"})
    check(st["control"]["level"] == "routine", f"{who}: level routine saved")
    check(until(lambda: events(H, "control_changed"), 5), f"{who}: the agent gets control_changed")
    r = api("POST", "/tasks", json={"title": "Routine task", "list_id": L})
    check(r.status_code == 201, f"{who}: routine: create a task {r.status_code} {r.text[:150]}")
    T = r.json()["id"]
    check(api("PATCH", f"/tasks/{T}", json={"due": "2026-12-01"}).ok, f"{who}: routine: plan (due) passes")
    r = api("PATCH", f"/tasks/{T}", json={"title": "Renamed"})
    check(r.status_code == 409 and r.json()["error"]["step"] == "change", f"{who}: routine: a title change -> 409 change {r.status_code}")
    r = api("POST", f"/tasks/{T}/comments", json={"body": "A note by the agent"})
    check(r.status_code == 201, f"{who}: routine: comment {r.status_code}")
    CM = r.json()["id"]
    T2 = api("POST", "/tasks", json={"title": "Tick me", "list_id": L}).json()["id"]
    check(api("POST", f"/tasks/{T2}/complete").ok, f"{who}: routine: tick off")
    r = api("DELETE", f"/tasks/{T2}")
    check(r.status_code == 409 and r.json()["error"]["step"] == "one_way", f"{who}: routine: delete -> 409 one_way {r.status_code}")
    h = hist(S, AID)
    kinds = [x["kind"] for x in h]
    check({"task_created", "task_planned", "comment", "task_completed"} <= set(kinds), f"{who}: the history has the decisions {kinds}")
    check(all(x["via"] == "self" and x["list_id"] == L for x in h), f"{who}: history lines name the project and 'self'")

    # ---- the approval card: exactly one step, once, only after Yes
    mid = card({"method": "DELETE", "path": f"/api/v1/tasks/{T2}"}, title="Delete the ticked task")
    r = api("DELETE", f"/tasks/{T2}", h={HDR: str(mid)})
    check(r.status_code == 409 and code(r) == "approval_invalid", f"{who}: before the Yes the card does not count {r.status_code}")
    answer(mid)
    r = api("DELETE", f"/tasks/{T}", h={HDR: str(mid)})
    check(r.status_code == 409 and code(r) == "approval_invalid", f"{who}: another path with the card -> 409 {r.status_code}")
    r = api("DELETE", f"/tasks/{T2}", h={HDR: str(mid)})
    check(r.status_code == 204, f"{who}: after Yes the approved step runs {r.status_code} {r.text[:150]}")
    T3 = api("POST", "/tasks", json={"title": "Second", "list_id": L}).json()["id"]
    r = api("DELETE", f"/tasks/{T2}", h={HDR: str(mid)})
    check(r.status_code == 409 and code(r) == "approval_invalid", f"{who}: the same card a second time -> 409 {r.status_code}")
    check(any(x["via"] == "approval" for x in hist(S, AID)), f"{who}: the approved step is in the history")
    # a failed request gives the approval back
    mid = card({"method": "PATCH", "path": f"/tasks/{T3}"})
    answer(mid)
    r = api("PATCH", f"/tasks/{T3}", h={HDR: str(mid)}, json={"priority": "nonsense"})
    check(r.status_code == 400, f"{who}: an invalid request with the card -> 400 {r.status_code}")
    r = api("PATCH", f"/tasks/{T3}", h={HDR: str(mid)}, json={"title": "Approved rename"})
    check(r.status_code == 200 and r.json()["title"] == "Approved rename", f"{who}: the card still works after a failed try {r.status_code}")
    # a rejected card never counts
    mid = card({"method": "PATCH", "path": f"/tasks/{T3}"})
    answer(mid, "no")
    r = api("PATCH", f"/tasks/{T3}", h={HDR: str(mid)}, json={"title": "Nope"})
    check(r.status_code == 409, f"{who}: a No never approves {r.status_code}")

    # ---- free: changes pass, deleting does not
    st = ctl(S, AID, {"level": "free", "goal": "keep the project tidy", "one_way": ["send invoices"], "deadline": "1h", "then": "recommend"})
    check(st["control"]["goal"] == "keep the project tidy" and st["control"]["one_way"] == ["send invoices"], f"{who}: goal + own one-way step saved")
    me = api("GET", "/agent").json()["control"]
    check(me["level"] == "free" and me["goal"] == "keep the project tidy" and me["one_way"]["custom"] == ["send invoices"]
          and me["deadline"] == 3600 and me["then"] == "recommend", f"{who}: the agent reads goal, own steps and deadline {me}")
    check(api("PATCH", f"/tasks/{T3}", json={"title": "Free rename"}).ok, f"{who}: free: a change passes")
    r = api("DELETE", f"/tasks/{T3}")
    check(r.status_code == 409 and r.json()["error"]["step"] == "one_way" and r.json()["error"]["level"] == "free", f"{who}: free: delete still 409")
    # a project exception wins
    ctl(S, AID, {"projects": {str(L): "approve_all"}})
    r = api("PATCH", f"/tasks/{T3}", json={"title": "Not now"})
    check(r.status_code == 409 and r.json()["error"]["level"] == "approve_all", f"{who}: the project's exception wins {r.status_code}")
    ctl(S, AID, {"projects": {str(L): None}})
    check(api("PATCH", f"/tasks/{T3}", json={"title": "Free again"}).ok, f"{who}: exception removed -> free again")
    for bad in ({"level": "yolo"}, {"deadline": "2h"}, {"then": "maybe"}, {"one_way": ["x" * 121]}, {"one_way": ["a"] * 21},
                {"goal": "x" * 501}, {"projects": {"abc": "free"}}, {"no_such": 1}):
        ctl(S, AID, bad, 400)

    # ---- Undo
    by = {x["kind"]: x for x in hist(S, AID) if not x["undone_at"]}
    for kind in ("task_created", "task_planned", "comment", "task_completed"):
        x = by.get(kind)
        check(x and x["can_undo"], f"{who}: {kind} can be undone")
    r = S.post(B + f"/api/agents/{AID}/control/history/{by['task_planned']['id']}/undo")
    check(r.ok, f"{who}: undo the plan {r.status_code} {r.text[:150]}")
    check(requests.get(V + f"/tasks/{T}", headers=H).json()["due"] is None, f"{who}: the due date is back to none")
    r = S.post(B + f"/api/agents/{AID}/control/history/{by['comment']['id']}/undo")
    check(r.ok and not [k for k in requests.get(V + f"/tasks/{T}/comments", headers=H).json().get("data", []) if k["id"] == CM],
          f"{who}: undo the comment {r.status_code}")
    check(S.post(B + f"/api/agents/{AID}/control/history/{by['comment']['id']}/undo").status_code == 409, f"{who}: undo twice -> 409")
    created = [x for x in hist(S, AID) if x["kind"] == "task_created" and x["title"] == "Routine task"]
    r = S.post(B + f"/api/agents/{AID}/control/history/{created[0]['id']}/undo")
    check(r.ok and kt.dbx("SELECT deleted_at FROM tasks WHERE id=?", (T,))[0][0], f"{who}: undo the created task -> trash {r.status_code}")
    check(until(lambda: events(H, "decision_undone"), 5), f"{who}: the agent gets decision_undone")

    # ---- #2901 the deadline (the watchdog of the test container runs every second; the card is made 2 hours old)
    def aged(mid):
        kt.dbx("UPDATE agent_chat SET created_at=? WHERE id=?", (ago(), mid))

    T4 = api("POST", "/tasks", json={"title": "Deadline task", "list_id": L}).json()["id"]
    mid = card({"method": "PATCH", "path": f"/tasks/{T4}"}, recommend="yes")
    aged(mid)
    check(until(lambda: [e for e in events(H, "approval_expired") if e["data"]["message_id"] == mid], 10), f"{who}: recommend -> approval_expired")
    ev = [e for e in events(H, "approval_expired") if e["data"]["message_id"] == mid][0]["data"]
    check(ev["outcome"] == "approved", f"{who}: the recommended Yes is taken {ev}")
    ctl(S, AID, {"projects": {str(L): "approve_all"}})
    check(api("PATCH", f"/tasks/{T4}", h={HDR: str(mid)}, json={"title": "Taken by deadline"}).ok, f"{who}: the recommended Yes approves the step")
    ctl(S, AID, {"projects": {str(L): None}})
    mid = card({"method": "DELETE", "path": f"/tasks/{T4}"}, recommend="yes")
    aged(mid)
    check(until(lambda: [e for e in events(H, "approval_expired") if e["data"]["message_id"] == mid], 10), f"{who}: one-way: approval_expired")
    ev = [e for e in events(H, "approval_expired") if e["data"]["message_id"] == mid][0]["data"]
    check(ev["outcome"] == "rejected", f"{who}: recommend never on a one-way step: rejected {ev}")
    check(api("DELETE", f"/tasks/{T4}", h={HDR: str(mid)}).status_code == 409, f"{who}: the expired one-way card approves nothing")
    ctl(S, AID, {"then": "ask_again"})
    mid = card({"method": "PATCH", "path": f"/tasks/{T4}"}, recommend="yes")
    aged(mid)
    check(until(lambda: [e for e in events(H, "approval_expired") if e["data"]["message_id"] == mid], 10), f"{who}: ask again")
    ev = [e for e in events(H, "approval_expired") if e["data"]["message_id"] == mid][0]["data"]
    check(ev["outcome"] == "asked_again", f"{who}: asked again once {ev}")
    kt.dbx("UPDATE agent_chat SET choices=jsonb_set(choices, '{deadline_asked_at}', to_jsonb(CAST(? AS TEXT))) WHERE id=?",
           (ago(), mid))
    check(until(lambda: len([e for e in events(H, "approval_expired") if e["data"]["message_id"] == mid]) == 2, 10), f"{who}: second expiry")
    ev = [e for e in events(H, "approval_expired") if e["data"]["message_id"] == mid][-1]["data"]
    check(ev["outcome"] == "rejected", f"{who}: after asking again: rejected {ev}")
    check(not kt.dbx("SELECT 1 FROM agent_chat WHERE id=? AND choice IS NULL AND choices->>'withdrawn_at' IS NULL", (mid,)),
          f"{who}: the card is no longer open")
    check(any(x["kind"].startswith("deadline_") for x in hist(S, AID)), f"{who}: the deadline results are in the history")

    # ---- an agent from before 2.235.0: no level stored = as before
    kt.dbx("UPDATE agents SET control='' WHERE user_id=?", (AID,))
    me = api("GET", "/agent").json()["control"]
    check(me["chosen"] is False and me["enforced"] is False and me["level"] is None, f"{who}: legacy agent: no level {me}")
    check(ctl(S, AID)["chosen"] is False, f"{who}: the settings say no level chosen")
    r = api("DELETE", f"/tasks/{T4}")
    check(r.status_code == 204, f"{who}: legacy agent deletes as before {r.status_code} {r.text[:150]}")
    ctl(S, AID, {"level": "routine"})
    check(api("GET", "/agent").json()["control"]["level"] == "routine", f"{who}: picking a level turns the control on")


# ================================================================== a personal agent of a person without organisation
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": SCOPES})
check(r.status_code in (200, 201), f"personal agent {r.status_code} {r.text[:150]}")
FA, FAH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
FL = F.post(B + "/api/lists", json={"name": "Frida work"}).json()["id"]
check(F.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "the freelancer shares the list with the agent")
check(O.get(B + f"/api/agents/{FA}/control").status_code == 404, "another person: GET 404")
check(O.patch(B + f"/api/agents/{FA}/control", json={"level": "free"}).status_code == 404, "another person: PATCH 404")
check(A.get(B + f"/api/agents/{FA}/control").status_code == 404, "an instance admin: no access to a personal agent of someone else")
run("freelancer", F, FID, FA, FAH, FL)

# the cap: in a list of Otto where Frida may only edit, her agent gets at most routine
OL = O.post(B + "/api/lists", json={"name": "Otto shared"}).json()["id"]
for uid in (FID, FA):
    kt.dbx("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,'edit',?) ON CONFLICT DO NOTHING", (OL, uid, ago(0)))
OT = O.post(B + "/api/tasks", json={"title": "Otto's task", "list_id": OL}).json()["id"]
st = ctl(F, FA)
p = [x for x in st["projects"] if x["id"] == OL]
check(p and p[0]["max_level"] == "routine", f"the cap: edit rights -> at most routine {p}")
check(not [x for x in st["projects"] if x["id"] == FL and x["max_level"] != "free"], "her own list: free")
ctl(F, FA, {"projects": {str(OL): "free"}}, 400)
ctl(F, FA, {"projects": {str(OL): "routine"}})
ctl(F, FA, {"level": "free"})
r = requests.patch(V + f"/tasks/{OT}", headers=FAH, json={"title": "Changed by the agent"})
check(r.status_code == 409 and r.json()["error"]["level"] == "routine", f"free agent, edit owner: capped to routine in that list {r.status_code}")
check(requests.post(V + "/tasks", headers=FAH, json={"title": "Routine in Otto's", "list_id": OL}).status_code == 201, "routine passes there")
check(requests.patch(V + f"/tasks/{OT}", headers=FAH, json={"due": "2026-12-24"}).ok, "planning passes there")

# ================================================================== a team agent of the instance admin
r = A.post(B + "/api/admin/agents", json={"username": "teambot", "display_name": "Team", "scopes": SCOPES})
check(r.status_code in (200, 201), f"team agent {r.status_code}")
TA, TAH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
TL = A.post(B + "/api/lists", json={"name": "Team work"}).json()["id"]
check(A.put(B + f"/api/lists/{TL}/members", json={"user_id": TA, "role": "edit"}).ok, "the admin shares a list with the team agent")
A.patch(B + f"/api/lists/{TL}", json={"agent_members": True})
check(F.get(B + f"/api/agents/{TA}/control").status_code == 404, "a person without admin rights: 404 on a team agent")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
run("team", A, ALICE, TA, TAH, TL)
sys.exit(done("p2235_a_control_api"))
