#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1045.0 A (#5827): an approved agent step runs from its card, a refusal names its reason, a card only for a real route
 - a card whose step is no route (PUT on a knowledge page that is PATCH, a path that does not exist) is refused at once with
   400 naming the methods the path has; it is never stored (and never shown as "one-way")
 - the 409 approval_required hands over the step (method, path, body, if_match); the card from it, after the Yes, runs with
   POST /api/v1/agent/approvals/<id>/run: exactly the card's step, once; a knowledge page change with a long body is no
   one-way step; a second run answers 409 approval_invalid reason used + used_at (the step ran), not "does not fit"
 - the older way (the same request with X-Kalmido-Approval) names the reason: body (+ the fields), stale (only the state
   field differs), method / path; a run before the Yes: unanswered, after a No: rejected; a card of another agent: 404
 - the target changed between card and run: 409 conflict reason stale, the person's text stays, the card stays unused
 - one case per area through the run: task change (If-Match kept on the card), batch with _prev, comment, knowledge page,
   event, contact, table + cells with prev
 - 2.1045.0 review: a card never runs a card (400 on the card, 409 nested on a run), two runs at once run once (M3), a
   202 (the step waits for a person) leaves the card unused (N2), "used" says "in use right now or has run" (N3)
 - MCP: the 409 keeps the step as step_ref, request_chat_approval step_ref makes the card, run_approved_step runs it
freelancer-matrix: agents (the personal agent belongs to a person without an organisation)
usage: p21045_a_approval_test.py <datadir>      (KMT_NOSTART=1 / P21045A_NOSTART=1: a running server)"""
import importlib.util
import os
import sys

import requests

import kt
from freelancer_fixture import freelancer
from kt import B, check, done, fresh, setup

V = B + "/api/v1"
HDR = "X-Kalmido-Approval"
HERE = os.path.dirname(os.path.abspath(__file__))

os.environ["KALMIDO_AGENT_CONTROL_NEW"] = "approve_all"  # the real default: every change needs a card
fresh(prefix="P21045A")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
OID, OTTO = freelancer(B, A, "otto")
SCOPES = ["read", "tasks:write", "comments", "wiki:read", "wiki:write", "calendar", "contacts", "sheets:read", "sheets:write",
          "structure"]  # 2.1045.0 (#5827, N2): its own project for a step that waits for a person


def err(r):
    try:
        e = r.json()["error"]
        return e if isinstance(e, dict) else {}
    except (ValueError, KeyError, TypeError):
        return {}


def agent(s, name):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": SCOPES})
    check(r.status_code in (200, 201), f"personal agent {name} {r.status_code} {r.text[:150]}")
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}, r.json()["token"]


FA, FH, FTOK = agent(F, "fridabot")
OA, OH, _ = agent(OTTO, "ottobot")
check((F.get(B + f"/api/agents/{FA}/control").json().get("control") or {}).get("level") == "approve_all", "the agent starts with approve_all")
FL = F.post(B + "/api/lists", json={"name": "Frida work"}).json()["id"]
check(F.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "setup: the project is shared with the agent")


def api(method, path, mid=None, h=None, **kw):
    return requests.request(method, V + path, headers={**FH, **({HDR: str(mid)} if mid else {}), **(h or {})}, **kw)


def card(step, h=FH, uid=FID, want=201, **kw):
    r = requests.post(V + f"/agent/chats/{uid}", headers=h, json={"approval": {"title": "May I?", "step": step, **kw}})
    check(r.status_code == want, f"approval card {step.get('method')} {step.get('path')} -> {r.status_code} (want {want}) {r.text[:200]}")
    return r


def answer(mid, choice="yes", s=F, aid=FA):
    r = s.post(B + f"/api/agents/{aid}/chat/{mid}/choice", json={"choice_ids": [choice]})
    check(r.ok, f"answer {choice} {r.status_code} {r.text[:150]}")


def run(mid, h=FH, **kw):
    return requests.post(V + f"/agent/approvals/{mid}/run", headers=h, **kw)


def step_of(r):
    """The step of a 409 approval_required, as the card takes it (method, path, body, if_match)."""
    ap = err(r).get("approval") or {}
    return {k: ap[k] for k in ("method", "path", "body", "if_match") if k in ap}


def approved(r, what):
    """A refused write -> its card (from the 409) answered Yes -> the card's id."""
    check(r.status_code == 409 and err(r).get("code") == "approval_required", f"{what}: refused first {r.status_code} {r.text[:200]}")
    m = card(step_of(r))
    mid = m.json()["id"] if m.ok else 0
    answer(mid)
    return mid


# ================================================================== a card only for a real route
T = F.post(B + "/api/tasks", json={"title": "Plan the shoot", "list_id": FL}).json()["id"]
w = F.post(B + "/api/wiki/pages", json={"space": "private", "path": "Kit/Overview", "body": "Start"})
check(w.status_code in (200, 201), f"setup: a private knowledge page {w.status_code} {w.text[:200]}")
PID = w.json().get("id")
FOL = {f["path"]: f["id"] for f in F.get(B + "/api/wiki", params={"space": "private"}).json().get("folders", [])}
r = F.post(B + f"/api/files/nodes/{FOL.get('Kit')}/shares", json={"agent_id": FA, "role": "edit"})
check(r.status_code == 201, f"setup: the folder is shared with the agent {r.status_code} {r.text[:200]}")

r = card({"method": "PUT", "path": f"/wiki/pages/{PID}", "body": {"body": "x", "expect_updated_at": "2026-01-01"}}, want=400)
check("PATCH" in err(r).get("message", "") and "does not exist" in err(r).get("message", ""), f"PUT on a page: 400 names PATCH {r.text[:300]}")
r = card({"method": "POST", "path": "/no/such/route"}, want=400)
check("does not exist" in err(r).get("message", ""), f"a path that does not exist: 400 {r.text[:200]}")
check(not kt.dbx("SELECT 1 FROM agent_chat WHERE agent_id=? AND choices->'approval' IS NOT NULL", (FA,)), "no card was stored")

# ================================================================== a knowledge page with a long body, run from the card
cur = api("GET", f"/wiki/pages/{PID}").json()
LONG = "\n".join(f"Line {i} – with a dash, two  spaces and a link [[Kit/Camera]]  " for i in range(120))
r = api("PATCH", f"/wiki/pages/{PID}", json={"body": LONG, "expect_updated_at": cur["updated_at"]})
check(err(r).get("approval", {}).get("method") == "PATCH", f"the 409 names the real method PATCH {err(r).get('approval', {}).get('method')}")
m = card(step_of(r))
WMID = m.json()["id"]
check(not m.json()["choices"]["approval"].get("one_way"), f"a knowledge page change is no one-way step {m.json()['choices']['approval']}")
r = run(WMID)
check(r.status_code == 409 and err(r).get("reason") == "unanswered", f"run before the Yes: 409 unanswered {r.status_code} {r.text[:200]}")
answer(WMID)
r = run(WMID)
check(r.ok and r.json().get("body") == LONG, f"run: the page has exactly the card's body {r.status_code} {r.text[:200]}")
check(F.get(B + f"/api/wiki/pages/{PID}").json().get("body") == LONG, "the person sees the new text")
r = run(WMID)
e = err(r)
check(r.status_code == 409 and e.get("code") == "approval_invalid" and e.get("reason") == "used" and e.get("used_at"),
      f"second run: 409 used with the time it ran {r.status_code} {r.text[:200]}")
check(e.get("used_at", "x")[:16] in e.get("message", ""), f"the message says when the step ran {e.get('message')}")
# 2.1045.0 (#5827, N3): "used" may also be a run going on right now (it can still fail and free the card): never "it ran" for sure
check("in use right now or has run" in e.get("message", ""), f"N3: used says 'in use right now or has run' {e.get('message')}")
r = api("PATCH", f"/wiki/pages/{PID}", WMID, json={"body": LONG, "expect_updated_at": cur["updated_at"]})
check(r.status_code == 409 and err(r).get("reason") == "used", f"the same request sent again with the header: used, not 'does not fit' {r.text[:200]}")
dec = kt.dbx("SELECT via, message_id FROM agent_decisions WHERE agent_id=? AND message_id=?", (FA, WMID))
check(len(dec) == 1 and dec[0][0] == "approval", f"the run is one history line 'approval' {dec}")

# ---- the target changed between card and run: stale, the person's text stays, the card stays unused
cur = api("GET", f"/wiki/pages/{PID}").json()
mid = approved(api("PATCH", f"/wiki/pages/{PID}", json={"body": "Agent text", "expect_updated_at": cur["updated_at"]}), "stale")
pg = F.get(B + f"/api/wiki/pages/{PID}").json()
check(F.patch(B + f"/api/wiki/pages/{PID}", json={"body": "Frida's text", "expect_updated_at": pg["updated_at"]}).ok, "setup: the person saves in between")
r = run(mid)
check(r.status_code == 409 and err(r).get("reason") == "stale" and "expect_updated_at" in err(r).get("fields", []),
      f"run after a change: 409 stale (expect_updated_at) {r.status_code} {r.text[:300]}")
check(F.get(B + f"/api/wiki/pages/{PID}").json().get("body") == "Frida's text", "the person's text stays")
check(not kt.dbx("SELECT 1 FROM agent_chat WHERE id=? AND choices->'approval'->>'used_at' IS NOT NULL", (mid,)), "the card stays unused")

# ================================================================== the older header way names its reason
def task_now():
    return api("GET", f"/tasks/{T}").json()["updated_at"]


u = task_now()
mid = approved(api("PATCH", f"/tasks/{T}", json={"title": "Card title", "expect_updated_at": u}), "header")
r = api("PATCH", f"/tasks/{T}", mid, json={"title": "Other title", "expect_updated_at": u})
check(r.status_code == 409 and err(r).get("reason") == "body" and err(r).get("fields") == ["title"],
      f"another body: 409 body naming the field title {r.text[:300]}")
check("Other title" not in r.text and "Card title" not in r.text, "the reason names fields, never their values")
r = api("PATCH", f"/tasks/{T}", mid, json={"title": "Card title", "expect_updated_at": "2020-01-01T00:00:00Z"})
check(r.status_code == 409 and err(r).get("reason") == "stale", f"only the state field differs: 409 stale {r.text[:300]}")
r2 = api("PATCH", f"/tasks/{T + 99999}", mid, json={"title": "Card title", "expect_updated_at": u})
check(r2.status_code in (404, 409), f"another path: refused {r2.status_code}")
if r2.status_code == 409:
    check(err(r2).get("reason") == "path", f"another path: reason path {r2.text[:300]}")
r = api("PATCH", f"/tasks/{T}", mid, json={"expect_updated_at": u, "title": "Card title"})
check(r.ok and r.json()["title"] == "Card title", f"the older way still works (keys in another order) {r.status_code} {r.text[:200]}")

# ---- no, someone else's card, a body on the run
cur = api("GET", f"/wiki/pages/{PID}").json()
r = api("PATCH", f"/wiki/pages/{PID}", json={"body": "No way", "expect_updated_at": cur["updated_at"]})
mid = card(step_of(r)).json()["id"]
answer(mid, "no")
r = run(mid)
check(r.status_code == 409 and err(r).get("reason") == "rejected", f"after a No: 409 rejected {r.status_code} {r.text[:200]}")
r = run(mid, h=OH)
check(r.status_code == 404, f"another agent's card: 404 {r.status_code}")
r = run(WMID, json={"body": "smuggled"})
check(r.status_code == 400, f"a run takes no body {r.status_code}")
r = F.post(V + f"/agent/approvals/{WMID}/run")
check(r.status_code in (401, 403), f"a person's session cannot run a card {r.status_code}")

# ================================================================== one case per area through the run
# task change with If-Match (the version as a header: kept on the card as if_match)
r = api("PATCH", f"/tasks/{T}", json={"notes": "Agent notes"}, h={"If-Match": task_now()})
check(err(r).get("approval", {}).get("if_match"), f"the 409 keeps the If-Match {err(r).get('approval')}")
mid = approved(r, "task If-Match")
r = run(mid)
check(r.ok and r.json().get("notes") == "Agent notes", f"task change with If-Match through the run {r.status_code} {r.text[:200]}")

# batch_tasks with _prev
BT = [F.post(B + "/api/tasks", json={"title": f"Batch {i}", "list_id": FL}).json()["id"] for i in range(3)]
body = {"ids": BT, "action": "update", "changes": {"title": "Renamed"}, "_prev": {str(i): {"title": f"Batch {n}"} for n, i in enumerate(BT)}}
r = run(approved(api("POST", "/tasks/batch", json=body), "batch"))
check(r.ok and r.json().get("count") == 3, f"batch through the run {r.status_code} {r.text[:200]}")

# comment
r = run(approved(api("POST", f"/tasks/{T}/comments", json={"body": "Looks good"}), "comment"))
check(r.status_code == 201 and r.json().get("body") == "Looks good", f"comment through the run {r.status_code} {r.text[:200]}")

# event
r = run(approved(api("POST", "/events", json={"title": "Shoot day", "start": "2027-03-04T09:00", "end": "2027-03-04T17:00"}), "event"))
check(r.status_code in (200, 201) and r.json().get("title") == "Shoot day", f"event through the run {r.status_code} {r.text[:200]}")

# contact
r = run(approved(api("POST", "/contacts", json={"given": "Lena", "family": "Lamp", "org": "Light Rental"}), "contact"))
check(r.status_code in (200, 201), f"contact through the run {r.status_code} {r.text[:200]}")

# table + cells with prev
r = run(approved(api("POST", "/sheets", json={"title": "Budget", "rows": [["a", "1"], ["b", "2"]]}), "sheet_create"))
check(r.status_code == 201, f"table through the run {r.status_code} {r.text[:200]}")
SID = r.json().get("id") if r.status_code == 201 else None
if SID:
    r = run(approved(api("PUT", f"/sheets/{SID}/cells", json={"cells": [{"cell": "B1", "raw": "9", "prev": "1"}]}), "cells"))
    check(r.ok and not r.json().get("conflicts"), f"cells with prev through the run {r.status_code} {r.text[:200]}")

# ---- a step the level now allows without a card still uses the card: a card runs once
check(F.patch(B + f"/api/agents/{FA}/control", json={"level": "free"}).ok, "setup: level free")
mid = card({"method": "POST", "path": f"/tasks/{T}/comments", "body": {"body": "Once only"}}).json()["id"]
answer(mid)
r = run(mid)
check(r.status_code == 201, f"free level: the card's step runs {r.status_code} {r.text[:200]}")
r = run(mid)
check(r.status_code == 409 and err(r).get("reason") == "used", f"free level: a second run is refused as used {r.status_code} {r.text[:200]}")
n = [x for x in F.get(B + f"/api/tasks/{T}/comments").json().get("comments", []) if x.get("body") == "Once only"] \
    if F.get(B + f"/api/tasks/{T}/comments").ok else None
check(n is None or len(n) == 1, f"free level: one comment, not two {n}")

# ---- 2.1045.0 (#5827, M3): two runs of one card at the same moment (level free: the gate claims nothing) -> one runs, one is "used"
import threading  # noqa: E402


def race(mid):
    out, go = [], threading.Barrier(2)

    def one():
        go.wait()
        out.append(run(mid))
    ts = [threading.Thread(target=one) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(150)
    return sorted(x.status_code for x in out), [err(x).get("reason") for x in out if x.status_code == 409]


for i in range(4):
    body = f"Race {i}"
    mid = card({"method": "POST", "path": f"/tasks/{T}/comments", "body": {"body": body}}).json()["id"]
    answer(mid)
    codes, why = race(mid)
    check(codes == [201, 409] and why == ["used"], f"M3: two runs at once -> one 201, one 409 used ({i}) {codes} {why}")
    cs = api("GET", f"/tasks/{T}/comments").json().get("data", [])
    check(len([x for x in cs if x.get("body") == body]) == 1, f"M3: the step ran once ({i})")
    check(not kt.dbx("SELECT 1 FROM agent_chat WHERE id=? AND choices->'approval'->>'run_at' IS NOT NULL", (mid,)), f"M3: the hold is gone after the run ({i})")

# ---- 2.1045.0 (#5827, M3): a failed run frees its hold, the card runs again
mid = card({"method": "POST", "path": f"/tasks/{T}/comments", "body": {"body": "After a failure"}}).json()["id"]
answer(mid)
kt.dbx("UPDATE agent_chat SET choices=jsonb_set(choices, '{approval,step,body}', CAST(? AS JSONB)) WHERE id=?", ('{"body": ""}', mid))
r = run(mid)
check(r.status_code >= 400, f"M3: an empty comment fails {r.status_code} {r.text[:200]}")
check(not kt.dbx("SELECT 1 FROM agent_chat WHERE id=? AND (choices->'approval'->>'used_at' IS NOT NULL OR choices->'approval'->>'run_at' IS NOT NULL)", (mid,)),
      "M3: a failed run leaves no hold and does not use the card")

# ---- 2.1045.0 (#5827, N2): a 202 (the step waits for a person: an agent moves its own project into a folder) does not use the card
r = api("POST", "/lists", json={"name": "Bot shelf"})
check(r.status_code == 201, f"N2 setup: the agent makes its own project {r.status_code} {r.text[:200]}")
BL = r.json().get("id")
# the person who says Yes writes in the project (the level's cap, ctl_claim approver_rights); the agent sharing it would itself wait (202)
kt.dbx("INSERT INTO list_members(list_id,user_id,role,sort,added_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
       (BL, FID, "edit", 0, "2026-11-12T00:00:00Z"))


def n2_case(what):
    mid = card({"method": "PATCH", "path": f"/lists/{BL}", "body": {"folder": "Archive " + what}}).json()["id"]
    answer(mid)
    r = run(mid)
    check(r.status_code == 202, f"N2 ({what}): the step waits for a person, 202 {r.status_code} {r.text[:200]}")
    check(not kt.dbx("SELECT 1 FROM agent_chat WHERE id=? AND (choices->'approval'->>'used_at' IS NOT NULL OR choices->'approval'->>'run_at' IS NOT NULL)", (mid,)),
          f"N2 ({what}): the 202 leaves the card unused")
    r = run(mid)
    check(r.status_code == 202, f"N2 ({what}): the card still runs (the same waiting request) {r.status_code} {r.text[:200]}")


n2_case("free")  # the gate let it pass without the card: the run itself must not mark it used
check(F.patch(B + f"/api/agents/{FA}/control", json={"level": "approve_all"}).ok, "setup: back to approve_all")
n2_case("approve_all")  # the gate claimed the card (ctl_claim): ctl_after gives it back on 202

# ---- 2.1045.0 (#5827, M1): a card whose step runs a card is refused; a run inside a run never runs (no loop)
r = card({"method": "POST", "path": f"/agent/approvals/{WMID}/run"}, want=400)
check(not kt.dbx("SELECT 1 FROM agent_chat WHERE agent_id=? AND right(choices->'approval'->'step'->>'path', 4)=?", (FA, "/run")),
      f"M1: a card running a card is refused and not stored {r.text[:200]}")
mid = card({"method": "POST", "path": f"/tasks/{T}/comments", "body": {"body": "Never"}}).json()["id"]
answer(mid)
kt.dbx("""UPDATE agent_chat SET choices=jsonb_set(choices, '{approval,step}', CAST(? AS JSONB)) WHERE id=?""",
       ('{"method": "POST", "path": "/api/v1/agent/approvals/%d/run"}' % mid, mid))  # stored past the card check (an older card)
r = run(mid)
check(r.status_code == 409 and err(r).get("reason") == "nested", f"M1: a run inside a run is refused as nested {r.status_code} {r.text[:200]}")
check(not kt.dbx("SELECT 1 FROM agent_chat WHERE id=? AND (choices->'approval'->>'used_at' IS NOT NULL OR choices->'approval'->>'run_at' IS NOT NULL)", (mid,)),
      "M1: the refused run leaves the card unused and free")

# ================================================================== MCP: step_ref and run_approved_step
spec = importlib.util.spec_from_file_location("kalmido_mcp_p21045", os.path.join(HERE, "..", "mcp", "kalmido_mcp.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
mc = M.Kalmido(B, FTOK)
cur = api("GET", f"/wiki/pages/{PID}").json()
try:
    mc.call("PATCH", f"/wiki/pages/{PID}", body={"body": "Through MCP", "expect_updated_at": cur["updated_at"]})
    check(False, "MCP: the write is refused first")
except M.ApiError as e:
    check(e.status == 409 and "step_ref=1" in e.message and "run_approved_step" in e.message, f"MCP: the refusal names step_ref {e.message[:300]}")
try:
    M.t_request_chat_approval(mc, {"user_id": FID, "title": "May I?", "step_ref": 7})
    check(False, "MCP: an unknown step_ref is refused")
except M.ApiError as e:
    check(e.status == 400, "MCP: an unknown step_ref: 400")
c = M.t_request_chat_approval(mc, {"user_id": FID, "title": "Change the overview", "step_ref": 1})
st = c["choices"]["approval"]["step"]
check(st["method"] == "PATCH" and st["body"]["body"] == "Through MCP", f"MCP: the card carries the step of the 409 {st}")
answer(c["id"])
out = M.t_run_approved_step(mc, {"message_id": c["id"]})
check(out.get("body") == "Through MCP", f"MCP: run_approved_step wrote the page {str(out)[:200]}")
try:
    M.t_run_approved_step(mc, {"message_id": c["id"]})
    check(False, "MCP: a second run is refused")
except M.ApiError as e:
    check(e.status == 409 and "reason: used" in e.message, f"MCP: the second run says used {e.message[:300]}")
check("run_approved_step" in M.TOOL_MAP and M.TOOL_SCOPE.get("run_approved_step") == "agent", "MCP: the tool exists with scope agent")

sys.exit(done("p21045_a_approval"))
