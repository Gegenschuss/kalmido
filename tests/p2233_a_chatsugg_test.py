#!/usr/bin/env python3
"""2.233.0 A (#2848) API: collected chat suggestions and the chat settings per person and agent, own container (start.sh).
 - an agent's suggestion a newer message ended is "collected": still answerable (chat_choice with collected: true), listed
   in the chat's suggestions (newest first, at most 10); dismiss (choices.dismissed_at, a press then 409, a second dismiss
   409); older than 24 h -> expired (409); the agent's own chat list says collected too
 - chat-prefs GET / PUT per person and agent: defaults, one key at a time, bad values / unknown keys / no object 400, an
   agent not shared with the person 404, another person keeps their own settings; "latest" = the old expiry (409),
   "keep" answers like "collect"
 - approval requests are not touched (open, never in the collection)
 - freelancer-matrix: agents (a person without an organisation and their personal agent: the same)
usage: p2233_a_chatsugg_test.py <datadir>"""
import os
import sys
import threading

import requests

import dbx as dbxm
from freelancer_fixture import freelancer
from kt import B, DATA, check, done, fresh, sess

V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


fresh()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
BOB = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob", "password": "password123",
                                     "email": "bob@example.com"}).json()["id"]
Bo = sess("bob")
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
W = A.post(B + "/api/lists", json={"name": "Chat home", "org_id": ORG}).json()
A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": CL, "role": "edit"})


def say(body, uid=ALICE, hd=CLH, **kw):
    r = requests.post(V + f"/agent/chats/{uid}", headers=hd, json={"body": body, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def ask(body, uid=ALICE, hd=CLH):
    return say(body, uid, hd, choices=[{"id": "yes", "label": "Yes, " + body}, {"id": "no", "label": "No"}])


def press(mid, s=A, aid=CL, ids=("yes",)):
    return s.post(B + f"/api/agents/{aid}/chat/{mid}/choice", json={"choice_ids": list(ids)})


def chat(s=A, aid=CL):
    return s.get(B + f"/api/agents/{aid}/chat").json()


def st(mid, s=A, aid=CL):
    return {m["id"]: m for m in chat(s, aid)["messages"]}[mid]["choice_state"]


def prefs(s=A, aid=CL, **kw):
    return s.put(B + f"/api/agents/{aid}/chat-prefs", json=kw) if kw else s.get(B + f"/api/agents/{aid}/chat-prefs")


def cursor():
    return requests.get(V + "/agent/events?since=latest", headers=CLH).json()["cursor"]


# ================================================================== the settings
r = prefs()
# 2.331.0 (#3309): the default for suggestions is keep (was collect); the server answers keep like collect
check(r.ok and r.json()["prefs"] == {"sugg": "keep", "jobs": "full", "pin": "on", "notices": "full"}, "defaults " + r.text[:200])
check(chat()["chat_prefs"]["sugg"] == "keep", "the chat carries chat_prefs")
r = prefs(jobs="line")
check(r.ok and r.json()["prefs"]["jobs"] == "line" and r.json()["prefs"]["sugg"] == "keep", "one key changes, the others stay " + r.text[:200])
check(prefs().json()["prefs"]["jobs"] == "line", "... stored on the server (every device)")
check(prefs(sugg="maybe").status_code == 400, "a bad value -> 400")
check(prefs(colour="red").status_code == 400, "an unknown key -> 400")
check(A.put(B + f"/api/agents/{CL}/chat-prefs", json=["latest"]).status_code == 400, "no object -> 400")
check(prefs(Bo).status_code == 404 and prefs(Bo, sugg="latest").status_code == 404, "an agent not shared with the person -> 404")
A.put(B + f"/api/lists/{W['id']}/members", json={"user_id": BOB, "role": "admin"})  # a list admin may address the agent
check(prefs(Bo).ok and prefs(Bo).json()["prefs"]["jobs"] == "full", "another person has their own settings (defaults)")
check(prefs(pin="off", notices="line").ok and prefs().json()["prefs"] == {"sugg": "keep", "jobs": "line", "pin": "off", "notices": "line"},
      "several keys at once")
# autosave: three fields saved at the same moment (three devices / quick taps) all stay -- merged in the database
SS = [sess("alice") for _ in range(3)]
res = []
ths = [threading.Thread(target=lambda s=s, kv=kv: res.append(prefs(s, **kv).status_code))
       for s, kv in zip(SS, ({"jobs": "full"}, {"pin": "on"}, {"notices": "full"}))]
for t in ths:
    t.start()
for t in ths:
    t.join()
check(res == [200] * 3 and prefs().json()["prefs"] == {"sugg": "keep", "jobs": "full", "pin": "on", "notices": "full"},
      "three parallel saves: none lost " + str((res, prefs().json()["prefs"])))

# ================================================================== collected suggestions
m1 = ask("plan 2.30")
check(m1["choice_state"] == "open", "a new suggestion is open")
say("Status: the build runs.")
check(st(m1["id"]) == "collected", "a newer message of the agent: collected (was expired) " + str(st(m1["id"])))
j = chat()
check([x["id"] for x in j["suggestions"]] == [m1["id"]] and j["suggestions"][0]["choice_state"] == "collected", "the chat lists the collected suggestions")
v1 = {m["id"]: m["choice_state"] for m in requests.get(V + "/agent/chats?since=0", headers=CLH).json()["data"]}
check(v1.get(m1["id"]) == "collected", "the agent's chat list says collected " + str(v1.get(m1["id"])))
cur = cursor()
r = press(m1["id"])
check(r.ok and r.json()["choice_state"] == "answered", "a press on a collected suggestion is accepted " + r.text[:200])
ev = [e for e in requests.get(V + f"/agent/events?since={cur}&limit=50", headers=CLH).json()["data"] if e["event"] == "chat_choice"]
check(len(ev) == 1 and ev[0]["data"]["message_id"] == m1["id"] and ev[0]["data"].get("collected") is True and ev[0]["data"]["labels"] == ["Yes, plan 2.30"],
      "the agent gets chat_choice with collected: true " + str(ev)[:300])
check(chat()["suggestions"] == [], "used: it leaves the collection")
check(press(m1["id"], ids=["no"]).status_code == 409, "answered once")

# my own message ends it too; dismiss
m3 = ask("ship it")
A.post(B + f"/api/agents/{CL}/chat", json={"body": "one moment"})
check(st(m3["id"]) == "collected", "my own message: collected")
r = A.post(B + f"/api/agents/{CL}/chat/{m3['id']}/dismiss", json={})
check(r.ok and r.json()["choice_state"] == "expired" and r.json()["choices"].get("dismissed_at"), "dismiss -> expired, dismissed_at stored " + r.text[:200])
check(press(m3["id"]).status_code == 409 and "no longer current" in press(m3["id"]).text, "a dismissed one: 409 no longer current")
check(A.post(B + f"/api/agents/{CL}/chat/{m3['id']}/dismiss", json={}).status_code == 409, "dismissing twice -> 409")
check(m3["id"] not in [x["id"] for x in chat()["suggestions"]], "dismissed: out of the collection")
m3b = ask("open one")
check(A.post(B + f"/api/agents/{CL}/chat/{m3b['id']}/dismiss", json={}).status_code == 409, "an open (newest) suggestion cannot be dismissed")
check(Bo.post(B + f"/api/agents/{CL}/chat/{m3b['id']}/dismiss", json={}).status_code == 404, "another person's message -> 404")

# older than 24 h
m4 = ask("old one")
say("next")
check(st(m4["id"]) == "collected", "set-up: collected")
dbw("UPDATE agent_chat SET created_at=? WHERE id=?", ("2020-01-01T00:00:00.000+00:00", m4["id"]))
check(st(m4["id"]) == "expired" and press(m4["id"]).status_code == 409, "older than 24 h: expired, a press 409")

# at most 10 (the newest)
qs = [ask(f"q{i}") for i in range(12)]
say("end")
j = chat()
ids = [x["id"] for x in j["suggestions"]]
check(ids == [q["id"] for q in qs[::-1][:10]], "at most 10, the newest first " + str((ids, [q["id"] for q in qs])))
check(st(qs[0]["id"]) == "expired" and press(qs[0]["id"]).status_code == 409, "the 11th oldest: expired, 409")
check(st(qs[2]["id"]) == "collected", "the 10th: collected")

# approval requests stay as they are
ap = say("", approval={"title": "Delete the old branch"})
say("more")
j = chat()
check({m["id"]: m for m in j["messages"]}[ap["id"]]["choice_state"] == "open" and ap["id"] not in [x["id"] for x in j["suggestions"]],
      "an approval request stays open and is never collected")

# the setting decides on the server
check(prefs(sugg="latest").ok, "sugg latest")
check(st(qs[11]["id"]) == "expired" and chat()["suggestions"] == [] and press(qs[11]["id"]).status_code == 409, "only the newest: expired, 409 as before")
check(prefs(sugg="keep").ok and st(qs[11]["id"]) == "collected", "keep all at the message: answerable again")
check(press(qs[11]["id"]).ok, "... a press is accepted")
check(prefs(sugg="collect").ok and prefs().json()["prefs"]["sugg"] == "collect" and prefs(Bo).json()["prefs"]["sugg"] == "keep",
      "2.331.0 (#3309): a stored choice stays (collect), the default of another person is keep")

# ================================================================== freelancer-matrix: agents
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FU, F = freelancer(B, A, "frida")
ag = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]})
check(ag.status_code in (200, 201), "freelancer: an own agent " + ag.text[:200])
FA = ag.json().get("id")
FH = {"Authorization": "Bearer " + F.post(B + f"/api/my/agents/{FA}/token").json().get("token", ""), "X-Requested-With": "kalmido"}
check(prefs(F, FA).ok and prefs(F, FA).json()["prefs"]["sugg"] == "keep", "freelancer: the settings of the own agent")
check(prefs(F, FA, notices="line").ok and prefs(F, FA).json()["prefs"]["notices"] == "line", "freelancer: changes them")
check(prefs(A, FA).status_code == 404, "freelancer: the admin does not see them (404)")
f1 = ask("tidy up", FU, FH)
say("done with the inbox", FU, FH)
check(st(f1["id"], F, FA) == "collected" and [x["id"] for x in chat(F, FA)["suggestions"]] == [f1["id"]], "freelancer: collected")
check(press(f1["id"], F, FA).ok, "freelancer: a press on it is accepted")
f2 = ask("archive", FU, FH)
say("x", FU, FH)
check(F.post(B + f"/api/agents/{FA}/chat/{f2['id']}/dismiss", json={}).ok and press(f2["id"], F, FA).status_code == 409, "freelancer: dismiss")

# ================================================================== the reference host (mcp/agent_run.py) names the older question
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("agent_run", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcp", "agent_run.py"))
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)
p = ar.build_prompt([{"event": "chat_choice", "data": {"user": {"id": 7}, "message_id": 5, "labels": ["Plan 2.30"], "collected": True,
                                                      "message": {"id": 5, "body": "Shall I plan 2.30 now?\nDetails"}}}], 7)
check("Plan 2.30" in p and "earlier suggestion" in p and "Shall I plan 2.30 now?" in p, "agent_run: a collected press names its question " + p[-300:])
p = ar.build_prompt([{"event": "chat_choice", "data": {"user": {"id": 7}, "message_id": 5, "labels": ["Plan 2.30"]}}], 7)
check("earlier suggestion" not in p, "agent_run: a normal press stays as before")

sys.exit(done("p2233_a_chatsugg"))
