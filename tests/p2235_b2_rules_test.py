#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.235.0 B2 (#2903 #2902): review findings 3-5 on standing rules and the data lock - a person without an organisation, her
personal agent (freelancer-matrix: agents)
 - a comment as the source of a rule only from a person who may address the agent in that project: the owner 201; another
   member of the project (a personal agent hears its owner only), another agent, a customer through the approval link 404
 - the excerpt in GET /api/v1/agent/rules only while the source exists and the agent sees it: a task locked later (tag) ->
   empty for the agent (the owner still sees it); a deleted comment / chat message -> empty everywhere, also in the database;
   the settings view then names no source person (user_id null)
 - team_message names a task (message.task_id) only when the agent may see it
usage: p2235_b2_rules_test.py <datadir>      (KMT_NOSTART=1 / P2235B2R_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, setup, until

V = B + "/api/v1"
fresh(prefix="P2235B2R")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
OID, O = freelancer(B, A, "otto")


def own_agent(s, name):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "comments"]})
    check(r.status_code in (200, 201), f"{name}: a personal agent {r.status_code} {r.text[:120]}")
    return r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}


def add(h, text, kind, sid):
    return requests.post(V + "/agent/rules", headers=h, json={"text": text, "source": {"kind": kind, "id": sid}})


def comment(s, tid, text):
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": text})
    check(r.ok, f"comment on {tid}: {r.status_code} {r.text[:120]}")
    return r.json()["id"]


def agent_rule(h, rid):
    return next(x for x in requests.get(V + "/agent/rules", headers=h).json()["data"] if x["id"] == rid)


def owner_rule(s, aid, rid):
    return next(x for x in s.get(B + f"/api/agents/{aid}/rules").json()["rules"] if x["id"] == rid)


FA, FH = own_agent(F, "fridabot")
OA, OH = own_agent(O, "ottobot")
L = F.post(B + "/api/lists", json={"name": "Studio"}).json()["id"]
for uid in (FA, OID):
    r = F.put(B + f"/api/lists/{L}/members", json={"user_id": uid, "role": "edit"})
    check(r.ok, f"member {uid} in the project {r.status_code} {r.text[:120]}")
T = F.post(B + "/api/tasks", json={"title": "Invoices", "list_id": L}).json()["id"]

# ---------------------------------------------------------------- finding 3: who a comment source may come from
c_own = comment(F, T, "From now on always attach the PDF")
r = add(FH, "Always attach the PDF", "comment", c_own)
check(r.status_code == 201, f"the owner's comment: 201 (counter-check) {r.status_code} {r.text[:160]}")
R_OWN = r.json()["rule"]["id"]
c_otto = comment(O, T, "From now on never send invoices")
check(add(FH, "Never send invoices", "comment", c_otto).status_code == 404, "a member the personal agent does not hear: 404")
c_ag = dbx("INSERT INTO comments(task_id, user_id, body, mentions, created_at) VALUES(?,?,?,'',?) RETURNING id",
           (T, OA, "From now on always pay at once", "2026-10-26T10:00:00.000Z"))[0][0]
check(add(FH, "Always pay at once", "comment", c_ag).status_code == 404, "a comment of another agent: 404")
c_ext = dbx("INSERT INTO comments(task_id, user_id, body, mentions, created_at, ext_name) VALUES(?,NULL,?,'',?,?) RETURNING id",
            (T, "From now on invoices without VAT", "2026-10-26T10:01:00.000Z", "A customer"))[0][0]
check(add(FH, "Invoices without VAT", "comment", c_ext).status_code == 404, "a customer through the approval link: 404")

# ---------------------------------------------------------------- finding 4: the excerpt follows its source
T2 = F.post(B + "/api/tasks", json={"title": "Travel costs", "list_id": L}).json()["id"]
c_t2 = comment(F, T2, "From now on always ZQXEXC round up travel costs")
r = add(FH, "Always round up travel costs", "comment", c_t2)
check(r.status_code == 201 and "ZQXEXC" in r.json()["rule"]["source"]["excerpt"], f"a rule from a comment, with excerpt {r.text[:160]}")
R_T2 = r.json()["rule"]["id"]
check(F.patch(B + f"/api/tasks/{T2}", json={"tags": ["privat"]}).ok, "the task gets the tag privat")
check(F.patch(B + f"/api/agents/{FA}/data-lock", json={"tags": ["privat"]}).status_code == 200, "lock: tag privat")
check(agent_rule(FH, R_T2)["source"]["excerpt"] == "", "the task is locked now: no excerpt for the agent")
check("ZQXEXC" in owner_rule(F, FA, R_T2)["source"]["excerpt"], "the owner still sees the excerpt")
check("ZQXEXC" not in requests.get(V + "/agent/rules", headers=FH).text, "nowhere in the agent's rules")

check(F.delete(B + f"/api/comments/{c_own}").ok, "the owner deletes the source comment")
check(agent_rule(FH, R_OWN)["source"]["excerpt"] == "", "deleted comment: no excerpt for the agent")
o = owner_rule(F, FA, R_OWN)["source"]
check(o["excerpt"] == "" and o["visible"] is False and o["user_id"] is None, f"deleted comment: nor in the settings (no person) {o}")
check(dbx("SELECT source_excerpt FROM agent_rules WHERE id=?", (R_OWN,))[0][0] == "", "the stored copy is gone too")

m = F.post(B + f"/api/agents/{FA}/chat", json={"body": "From now on always ZQXCHAT answer in German"})
check(m.status_code in (200, 201), f"a chat message {m.status_code}")
MID = m.json()["id"]
r = add(FH, "Always answer in German", "chat", MID)
check(r.status_code == 201 and "ZQXCHAT" in r.json()["rule"]["source"]["excerpt"], f"a rule from the chat {r.text[:160]}")
R_CH = r.json()["rule"]["id"]
check(owner_rule(F, FA, R_CH)["source"]["user_id"] == FID, "the settings name the person while the message exists (counter-check)")
check(F.delete(B + f"/api/agents/{FA}/chat/{MID}").ok, "the owner deletes the chat message")
check(agent_rule(FH, R_CH)["source"]["excerpt"] == "", "deleted chat message: no excerpt for the agent")
o = owner_rule(F, FA, R_CH)["source"]
check(o["excerpt"] == "" and o["visible"] is False and o["user_id"] is None, f"deleted chat message: nor in the settings {o}")
check(dbx("SELECT source_excerpt FROM agent_rules WHERE id=?", (R_CH,))[0][0] == "", "the stored copy of the chat is gone")
check(agent_rule(FH, R_CH)["text"] == "Always answer in German", "the rule itself stays")

# ---------------------------------------------------------------- finding 5: team_message and a locked task
rooms = F.get(B + "/api/team").json().get("rooms", [])
room = next((x for x in rooms if x["kind"] == "list" and x["list_id"] == L), None)
check(room is not None, f"the project's channel {rooms}")
T_OK = F.post(B + "/api/tasks", json={"title": "Plain", "list_id": L}).json()["id"]
for tid, word in ((T_OK, "ZQXOK"), (T2, "ZQXLOCKED")):
    r = F.post(B + f"/api/team/rooms/{room['id']}/messages", json={"body": f"<@{FA}> {word} look", "task_id": tid})
    check(r.ok, f"a channel message naming task {tid}: {r.status_code} {r.text[:120]}")


def tm(word):
    ev = requests.get(V + "/agent/events?since=0&limit=500", headers=FH).json().get("data", [])
    return next((e["data"]["message"] for e in ev if e["event"] == "team_message" and word in e["data"]["message"]["text"]), None)


check(until(lambda: tm("ZQXOK") and tm("ZQXLOCKED")), "both team_message events arrive")
check(tm("ZQXOK")["task_id"] == T_OK, "a visible task: its id (counter-check)")
check(tm("ZQXLOCKED")["task_id"] is None, f"a locked task: no task id {tm('ZQXLOCKED')}")
sys.exit(done("p2235_b2_rules"))
