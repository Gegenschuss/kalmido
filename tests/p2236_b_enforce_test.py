#!/usr/bin/env python3
"""2.236.0 B API tests: the server enforces an agent's work style ("Arbeitsweise und Meldungen"), own container (start.sh).
 - #2909 when the agent may disturb: a new agent pushes only at limits (push "limits": approval requests, permission
   questions, chat messages with limit: true); push "results" = every push as before (chat answers, its comments);
   push "never" = no push at all (the messages still arrive); limit must be a bool
 - #2905 quiet window for messages: pushes are counted, not sent; when the window ends ONE push "<agent>: N messages during
   the quiet hours", the count goes
 - #2911 next_step: one answer button {id next, next: true} after the agent's own choices; dropped with next_step_dropped
   off / repeat / conflict / full (the message stays); 81 characters or not a text -> 400; a press reaches the agent as
   chat_choice
 - #2904 the owner's budget (personal agents of a member and of a person without organisation): one notice at warn_pct
   and one when used up (News + push to the owner, once per period), then 429 + Retry-After + "Budget reached" except the
   exempt routes, budget_state in the work style and for the agent (GET /api/v1/agent), "limit reached" for the owner;
   a higher budget lets calls through; week = Monday 00:00 local time; others get 404 for the work style
freelancer-matrix: agents
usage: p2236_b_enforce_test.py <datadir>      (KMT_NOSTART=1 / P2236B_NOSTART=1: a running server)"""
import json
import os
import sys
from datetime import datetime, timedelta

import requests

import kt
from freelancer_fixture import freelancer
from kt import B, DATA, H, check, done, fresh, sess, until
from testclock import now

V = B + "/api/v1"


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def got(n0, topic, pred, t=10):
    """The pushes to topic after index n0 that match pred (waits for the first one up to t seconds)."""
    return until(lambda: [p for p in pushes()[n0:] if p.get("topic") == topic and pred(p)], t) or []


fresh(prefix="P2236B")
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com",
                                   "ntfy_topic": "t-bob"})
BOB = r.json()["id"]
CAROL = A.post(B + "/api/users", json={"orgs": [1], "username": "carol", "display_name": "Carol", "password": "password123",
                                      "email": "carol@example.com"}).json()["id"]
Bo, Ca = sess("bob"), sess("carol")
Bo.patch(B + "/api/settings", json={"lang": "en", "agent_push": "1"})  # pushes for what agents do (comments) wanted
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
W = A.post(B + "/api/lists", json={"name": "Chat home", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{W}/members", json={"user_id": BOB, "role": "edit"}).ok
assert A.put(B + f"/api/lists/{W}/members", json={"user_id": CL, "role": "edit"}).ok
assert A.patch(B + f"/api/lists/{W}", json={"agent_members": True}).ok
T1 = Bo.post(B + "/api/tasks", json={"title": "Plan the launch", "list_id": W}).json()["id"]
T2 = Bo.post(B + "/api/tasks", json={"title": "Write the flyer", "list_id": W}).json()["id"]


def say(uid=BOB, h=None, **b):
    return requests.post(V + f"/agent/chats/{uid}", headers=h or CLH, json=b)


def ws(patch=None, aid=CL, s=A):
    r = s.patch(B + f"/api/agents/{aid}/work-style", json=patch) if patch is not None else s.get(B + f"/api/agents/{aid}/work-style")
    assert r.ok, r.text
    return r.json()


def body_in(text):
    return lambda p: text in (p.get("msg") or "") or text in (p.get("title") or "")


# ================================================================== #2909 push limits (the default of a new agent)
check(ws()["work_style"]["push"] == "limits", "#2909: a new agent pushes only at limits")
n0 = len(pushes())
check(say(body="Plain result one").status_code == 201, "#2909: a plain answer arrives")
check(requests.post(V + f"/tasks/{T1}/comments", headers=CLH, json={"body": "Limits comment"}).status_code == 201, "#2909: the agent comments")
check(say(body="Stopped: the disk is full", limit=True).status_code == 201, "#2909: a message with limit: true")
check(got(n0, "t-bob", body_in("Stopped: the disk is full")), "#2909 limits: the limit message pushes")
check(say(approval={"title": "Deploy the site"}).status_code == 201, "#2909: an approval request")
check(got(n0, "t-bob", lambda p: p.get("title") == "Approval needed: Claude"), "#2909 limits: the approval request pushes")
check(say(body="May I delete the cache?", permission=True).status_code == 201, "#2909: a permission question")
check(got(n0, "t-bob", body_in("May I delete the cache?")), "#2909 limits: the permission question pushes")
seen = [(p.get("title"), p.get("msg")) for p in pushes()[n0:] if p.get("topic") == "t-bob"]
check(not [x for x in seen if "Plain result one" in (x[1] or "") or "Limits comment" in (x[1] or "")],
      "#2909 limits: neither the plain answer nor the comment pushed " + str(seen))
check(say(body="x", limit="yes").status_code == 400, "#2909: limit must be a bool")
msgs = Bo.get(B + f"/api/agents/{CL}/chat").json()["messages"]
check(any(m["body"] == "Plain result one" for m in msgs), "#2909: the message is in the chat all the same")

# ================================================================== #2909 push results (as before 2.236)
ws({"push": "results"})
n0 = len(pushes())
say(body="Result two")
requests.post(V + f"/tasks/{T2}/comments", headers=CLH, json={"body": "Results comment"})
check(got(n0, "t-bob", body_in("Result two")), "#2909 results: the plain answer pushes")
check(got(n0, "t-bob", body_in("Results comment")), "#2909 results: the agent's comment pushes (Bob wants agent pushes)")

# ================================================================== #2909 push never
ws({"push": "never"})
n0 = len(pushes())
# 2.236.0 review (#2909): a second agent comment inside the burst window is neither pushed nor counted for the summary
requests.post(V + f"/tasks/{T2}/comments", headers=CLH, json={"body": "Never burst comment"})
tp = kt.dbx("SELECT pending, events FROM task_push WHERE user_id=? AND task_id=?", (BOB, T2))
check(not tp or (tp[0][0] == 0 and tp[0][1] == 0), "#2909 never: no burst count for the watchdog summary " + str(tp))
check(say(body="Never limit", limit=True).status_code == 201 and say(approval={"title": "Never approval"}).status_code == 201,
      "#2909 never: the messages arrive")
ws({"push": "results"})
say(body="Sentinel after never")
check(got(n0, "t-bob", body_in("Sentinel after never")), "#2909: (sentinel) results push again")
seen = [(p.get("title"), p.get("msg")) for p in pushes()[n0:] if p.get("topic") == "t-bob"]
check(not [x for x in seen if "Never" in (x[1] or "")], "#2909 never: no push, not even a limit or an approval " + str(seen))

# ================================================================== #2905 quiet window: held, then one summary
t = now()
qf, qt = (t - timedelta(hours=1)).strftime("%H:%M"), (t + timedelta(hours=1)).strftime("%H:%M")
j = ws({"quiet_mode": "on", "quiet_from": qf, "quiet_to": qt})
check(j["state"]["quiet"] is True, "#2905: the quiet window is on now " + json.dumps(j["state"]))
n0 = len(pushes())
for x in ("Quiet one", "Quiet two"):
    say(body=x)
say(body="Quiet three", limit=True)
held = kt.dbx("SELECT n FROM agent_push_held WHERE agent_id=? AND user_id=?", (CL, BOB))
# 2.236.0 review (#2905): a limit (approval, permission question, limit: true) passes the quiet window
check(held and held[0][0] == 2, "#2905: two plain pushes counted, not sent " + str(held))
check(got(n0, "t-bob", body_in("Quiet three")), "#2905: the limit message pushes inside the quiet window")
ws({"quiet_mode": "off"})
sm = got(n0, "t-bob", body_in("2 messages during the quiet hours"))
check(len(sm) == 1 and sm[0].get("title") == "Claude", "#2905: ONE summary push when the window ends " + str(sm))
check(not [p for p in pushes()[n0:] if "Quiet one" in (p.get("msg") or "") or "Quiet two" in (p.get("msg") or "")], "#2905: the held messages themselves never pushed")
check(until(lambda: not kt.dbx("SELECT 1 FROM agent_push_held WHERE agent_id=?", (CL,)), 5), "#2905: the count is gone")
say(body="After the quiet window")
check(got(n0, "t-bob", body_in("After the quiet window")), "#2905: afterwards pushes go out again")
check(len([p for p in pushes()[n0:] if "during the quiet hours" in (p.get("msg") or "")]) == 1, "#2905: only one summary")

# ================================================================== #2911 next_step
r = say(body="The tests are green.", next_step="Run the device test")
j = r.json()
nx = [x for x in (j.get("choices") or {}).get("choices", []) if x["id"] == "next"]
check(r.status_code == 201 and len(nx) == 1 and nx[0]["label"] == "Run the device test" and nx[0].get("next") is True and "next_step_dropped" not in j,
      "#2911: next_step becomes one button {id next, next: true} " + r.text[:300])
MID = j["id"]
r = say(body="Which one?", choices=[{"id": "a", "label": "Option A"}, "B"], next_step="Ship it")
check(r.status_code == 201 and [x["id"] for x in r.json()["choices"]["choices"]] == ["a", "B", "next"], "#2911: appended after the own choices " + r.text[:300])
r = say(body="Again", next_step="  run the DEVICE test ")
check(r.status_code == 201 and r.json().get("next_step_dropped") == "repeat" and not r.json().get("choices"), "#2911: the same step again -> dropped (repeat) " + r.text[:200])
r = say(body="Eight", choices=[str(i) for i in range(8)], next_step="Ninth")
check(r.status_code == 201 and r.json().get("next_step_dropped") == "full" and len(r.json()["choices"]["choices"]) == 8, "#2911: 8 choices already -> full")
r = say(approval={"title": "Merge it"}, next_step="Merge")
check(r.status_code == 201 and r.json().get("next_step_dropped") == "conflict", "#2911: with an approval request -> conflict " + r.text[:200])
r = say(body="May I?", choices=["allow", "deny"], next_step="Go on")
check(r.status_code == 201 and r.json().get("next_step_dropped") == "conflict", "#2911 review: an older host's allow / deny question -> conflict " + r.text[:200])
check(say(body="x", choices='"oops"', next_step="Go").status_code == 400, "#2911 review: choices not a list stays 400 with next_step")
check(say(body="x", next_step="y" * 81).status_code == 400 and say(body="x", next_step=5).status_code == 400, "#2911: too long / not a text -> 400")
ws({"next_step": False})
r = say(body="Off now", next_step="A brand new step")
check(r.status_code == 201 and r.json().get("next_step_dropped") == "off" and r.json()["body"] == "Off now", "#2911: next_step off -> dropped, the message stays")
ws({"next_step": True})
r = say(body="Last question", next_step="Write the release notes")
cur = requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]
pr = Bo.post(B + f"/api/agents/{CL}/chat/{r.json()['id']}/choice", json={"choice_ids": ["next"]})
ev = [e for e in requests.get(V + f"/agent/events?since={cur}&limit=50", headers=CLH).json()["data"] if e["event"] == "chat_choice"]
check(pr.ok and ev and ev[-1]["data"]["choice_ids"] == ["next"] and ev[-1]["data"]["labels"] == ["Write the release notes"],
      "#2911: pressing the button reaches the agent as chat_choice " + pr.text[:200] + json.dumps(ev)[:300])

# ================================================================== #2904 the owner's budget (member + person without organisation)
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2}).ok
FID, Fr = freelancer(B, A)
check(A.patch(B + f"/api/users/{FID}", json={"ntfy_topic": "t-frida"}).ok, "setup: the freelancer gets a push topic")


def usage(h, n):
    return requests.post(V + "/agent/usage", headers=h, json={"model": "test-model", "input_tokens": n, "output_tokens": 0})


for who, S, OWNER, topic in (("member", Bo, BOB, "t-bob"), ("freelancer", Fr, FID, "t-frida")):
    ag = S.post(B + "/api/my/agents", json={"username": f"budget{OWNER}", "display_name": f"Budgy {who}", "scopes": ["read", "tasks:write"]}).json()
    assert "id" in ag, ag
    AID, AH = ag["id"], {"Authorization": "Bearer " + ag["token"]}
    check(ws(aid=AID, s=S)["budget_state"] is None, f"#2904 {who}: no budget = budget_state null")
    j = ws({"budget_period": "day", "budget_metric": "tokens", "budget_limit": 1000, "budget_warn_pct": 50}, aid=AID, s=S)
    check(j["budget_state"] and j["budget_state"]["used"] == 0 and j["budget_state"]["paused"] is False, f"#2904 {who}: budget_state " + json.dumps(j["budget_state"]))
    check(Ca.get(B + f"/api/agents/{AID}/work-style").status_code == 404, f"#2904 {who}: another person 404")
    n0 = len(pushes())
    check(usage(AH, 600).status_code == 201, f"#2904 {who}: usage reported")
    check(got(n0, topic, lambda p: p.get("title") == f"Budgy {who}: 50 % of the budget"), f"#2904 {who}: the notice at 50 % to the owner")
    st = ws(aid=AID, s=S)["budget_state"]
    check(st["warn"] is True and st["paused"] is False and st["pct"] == 60.0, f"#2904 {who}: warn " + json.dumps(st))
    usage(AH, 100)
    news = lambda: [x for x in S.get(B + "/api/news").json()["items"] if x["kind"] == "usage"]  # noqa: E731
    check(len(news()) == 1, f"#2904 {who}: the notice once per period (News) " + json.dumps(news())[:300])
    check(requests.get(V + "/tasks", headers=AH).status_code == 200, f"#2904 {who}: below the budget calls go through")
    usage(AH, 400)
    check(got(n0, topic, lambda p: p.get("title") == f"Budgy {who}: budget reached, paused"), f"#2904 {who}: the push when used up")
    check(len([p for p in pushes()[n0:] if p.get("topic") == topic and "of the budget" in (p.get("title") or "")]) == 1, f"#2904 {who}: the 50 % push once")
    check(len(news()) == 2, f"#2904 {who}: two notices (warn + used up)")
    r = requests.get(V + "/tasks", headers=AH)
    check(r.status_code == 429 and int(r.headers.get("Retry-After", "0")) >= 60 and "Budget reached" in r.text, f"#2904 {who}: 429 + Retry-After " + r.text[:200])
    r = requests.get(V + "/agent", headers=AH)
    check(r.ok and r.json()["work_style"]["budget_state"]["paused"] is True, f"#2904 {who}: the agent reads its budget_state " + r.text[:200])
    check(usage(AH, 1).status_code == 201, f"#2904 {who}: reporting usage still works")
    a = next(x for x in S.get(B + "/api/state").json()["agents"] if x["id"] == AID)
    check(a["limit_reached"] is True, f"#2904 {who}: 'limit reached' for the owner")
    ws({"budget_limit": 5000}, aid=AID, s=S)
    check(requests.get(V + "/tasks", headers=AH).status_code == 200, f"#2904 {who}: a higher budget lets calls through")
    st = ws({"budget_period": "week"}, aid=AID, s=S)["budget_state"]
    end = datetime.fromisoformat(st["resets_at"].replace("Z", "+00:00")).astimezone(now().tzinfo)
    check(st["period"] == "week" and end.weekday() == 0 and end.hour == 0 and end.minute == 0 and 0 < (end - now()).days + 1 <= 7,
          f"#2904 {who}: a week ends Monday 00:00 local time " + st["resets_at"])

sys.exit(done("p2236_b_enforce"))
