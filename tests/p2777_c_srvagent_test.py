#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.777.0 C (#5378): a new server agent - the starter pack without red errors, projects before the pack, a team agent visible.
 - a new team agent without a shared project: the planned jobs of the starter pack are made switched off and wait
   (state "waiting", share_wait), a rule is made as before; GET /api/agents/<id>/server/starter says waiting / missing
 - the organisation's admin shares a project with it: the watchdog switches the waiting plans on (enabled, next due time); the
   same item asked again (the agent's window after "Share project") starts them at once
 - projects shared BEFORE the starter pack (the dialog's order): the plans are created and active right away
 - a plan switched off by hand no longer waits (share_wait gone)
 - the tab Agents: a team agent for every member / admin of its organisation also without a shared project ("shared": false,
   "projects": N, nothing of its work); a guest of the organisation, another organisation's admin and a person without an
   organisation never see it
 - the chat of a member without a shared project: allowed, the fixed answer of Kalmido follows at once, no event for the agent,
   no data (its plans 404, its server settings 404), a task / files refused; other organisations 404
 - a person without an organisation: her personal server agent with her own project, the pack created and active, the state
   route (freelancer-matrix: agents)
 - review F1: the text of such a member and Kalmido's answer never reach the agent: its poll (GET /api/v1/agent/chats), the
   message search and delivered stay without them, also after a project is shared later; a repeat with the same client_id is
   the stored message (no second answer)
 - review F2: waiting plans wake only by the person's OWN share (owner / admin of a project the agent is in); someone else
   taking the agent into a project where she is only a member wakes nothing; the state route says own: false
 - review F3: a member without a shared project sees nothing of the agent's host, model, rights mode, usage, costs, contact
tenant-matrix: agent (another organisation's admin: the state route, the chat and the tab never reach the team agent)
usage: p2777_c_srvagent_test.py <datadir>      (KMT_NOSTART=1 / P2777C_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, sess, until

fresh(prefix="P2777C")
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 10}).ok, "personal agents allowed")
uid = {}
for u, rk in (("bob", "admin"), ("carl", "member"), ("gus", "guest")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": rk}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as {rk} " + r.text[:200])
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
uid["olga"] = r.json().get("id")
r = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]})
check(r.ok, "setup: another organisation with olga as its admin " + r.text[:200])
S = {u: sess(u) for u in ("bob", "carl", "gus", "olga")}
Bo, Ca, Gu, Ol = (S[u] for u in ("bob", "carl", "gus", "olga"))
for s in S.values():
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "comments,collab,agents"})
FID, Fr = freelancer(B, A)


def starter(s, aid, items):
    return s.post(B + f"/api/agents/{aid}/server/starter", json={"items": items})


def states(r):
    return {x["item"]: x["state"] for x in (r.json().get("items") or [])} if r.ok else {}


def plans_db(aid):
    return dbx("SELECT srv_flow, enabled, share_wait, next_at IS NOT NULL FROM agent_schedules WHERE agent_id=? ORDER BY srv_flow", (aid,))


def listed(s, aid):
    return next((a for a in s.get(B + "/api/agents").json().get("agents") or [] if a["id"] == aid), None)


# ================================================================ a new team agent without a project: the plans wait
r = Bo.post(B + f"/api/orgs/{ORG}/server-agents", json={"username": "teamki", "display_name": "Team KI"})
check(r.status_code == 201, f"bob (organisation admin) creates a team agent {r.status_code} {r.text[:200]}")
TK = r.json().get("id")
r = starter(Bo, TK, ["briefing", "tidy", "followup", "meetings"])
st = states(r)
check(r.ok and st == {"briefing": "waiting", "tidy": "waiting", "followup": "waiting", "meetings": "created"},
      f"without a shared project: three plans wait, the rule is made, nothing skipped {r.text[:400]}")
# 2.777.0 (#5378): review F2 - the reason says it starts by one of YOUR projects
check(all(x["reason"] and "share one of your projects" in x["reason"] for x in r.json()["items"] if x["state"] == "waiting"),
      "waiting: the calm reason says how it starts")
check(sorted(plans_db(TK)) == [("briefing", 0, 1, False), ("followup", 0, 1, False), ("tidy", 0, 1, False)],
      f"stored switched off and marked as waiting {plans_db(TK)}")
check(states(starter(Bo, TK, ["briefing"])) == {"briefing": "waiting"} and len(plans_db(TK)) == 3, "the same again: still waiting, no second plan")
j = Bo.get(B + f"/api/agents/{TK}/server/starter").json()
check(j.get("shared") is False and j.get("projects") == 0 and j.get("org_id") == ORG and j["items"]["briefing"] == "waiting"
      and j["items"]["meetings"] == "active" and j["items"]["docs"] == "missing" and j["items"]["office"] == "missing",
      f"the state route: waiting / active / missing, not shared, no project {j}")

# ================================================================ the tab Agents: every member of its organisation
a = listed(Ca, TK)
check(a and a.get("shared") is False and a.get("projects") == 0 and a.get("status_text") == "" and a.get("status_task") is None,
      f"carl (member, no shared project) sees the team agent with 'no project', nothing of its work {a}")
check(listed(Bo, TK) and listed(Bo, TK).get("shared") is False, "bob (its creator) sees it before sharing a project")
check(any(a["id"] == TK for a in Ca.get(B + "/api/state").json().get("agents") or []), "the state carries it for carl too")
for s, who in ((Gu, "a guest of the organisation"), (Ol, "another organisation's admin"), (Fr, "a person without an organisation")):
    check(listed(s, TK) is None, f"{who} never sees the team agent")
    check(not any(a["id"] == TK for a in s.get(B + "/api/state").json().get("agents") or []), f"{who}: not in the state either")

# ================================================================ the chat without a shared project: the fixed answer, no data
n_ev = dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=?", (TK,))[0][0]
r = Ca.get(B + f"/api/agents/{TK}/chat")
check(r.status_code == 200 and r.json().get("shared") is False and r.json()["agent"].get("status_text") == "", f"carl opens the chat ({r.status_code})")
r = Ca.post(B + f"/api/agents/{TK}/chat", json={"body": "What is due today?"})
check(r.status_code == 201, f"carl writes to it without a project ({r.status_code} {r.text[:200]})")
msgs = Ca.get(B + f"/api/agents/{TK}/chat").json()["messages"]
check(len(msgs) == 2 and msgs[0]["body"] == "What is due today?" and msgs[1]["from"] == "agent"
      and "do not see any project of yours" in msgs[1]["body"] and "Team KI" in msgs[1]["body"],
      f"the answer follows at once: it sees nothing and how to share a project {[m['body'][:60] for m in msgs]}")
check(dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=?", (TK,))[0][0] == n_ev, "no event for the agent (no run, no costs, no data)")
check(Ca.post(B + f"/api/agents/{TK}/chat", json={"body": "x", "task_id": 1}).status_code == 400, "with a task: refused")
# 2.777.0 (#5378): review F1 - the agent's own poll never carries carl's text nor Kalmido's answer to him
r = A.post(B + f"/api/admin/agents/{TK}/token", json={})
check(r.ok, f"setup: a token of the team agent {r.status_code}")
TKH = {"Authorization": "Bearer " + r.json()["token"], "X-Requested-With": "kalmido"}
V = B + "/api/v1"
rows = requests.get(V + "/agent/chats?since=0", headers=TKH, timeout=30).json().get("data")
check(rows is not None and not [m for m in rows if (m.get("user") or {}).get("id") == uid["carl"]],
      f"review F1: the agent's poll lists none of carl's rows {[(m.get('from'), (m.get('body') or '')[:30]) for m in rows or []]}")
rows = requests.get(V + f"/agent/chats?since=0&user_id={uid['carl']}", headers=TKH, timeout=30).json().get("data")
check(rows == [], f"review F1: nor with ?user_id=carl {rows}")
check(dbx("SELECT COUNT(*) FROM agent_chat WHERE agent_id=? AND user_id=? AND delivered_at IS NOT NULL", (TK, uid["carl"]))[0][0] == 0,
      "review F1: carl's message is never marked delivered")
r = requests.get(V + "/search?scope=messages&q=today&art=a", headers=TKH, timeout=30)
check(r.ok and not [h for h in r.json().get("data") or [] if h.get("user_id") == uid["carl"]], f"review F1: the agent's message search finds nothing of carl {r.text[:200]}")
n_c = len(Ca.get(B + f"/api/agents/{TK}/chat").json()["messages"])
r1 = Ca.post(B + f"/api/agents/{TK}/chat", json={"body": "Once only", "client_id": "p2777c-cid-1"})
r2 = Ca.post(B + f"/api/agents/{TK}/chat", json={"body": "Once only", "client_id": "p2777c-cid-1"})
check(r1.status_code == 201 and r2.status_code == 200 and r1.json().get("id") == r2.json().get("id")
      and len(Ca.get(B + f"/api/agents/{TK}/chat").json()["messages"]) == n_c + 2,
      f"review F1: the same client_id again is the stored message, no second answer {r1.status_code} {r2.status_code}")
check(all(m["kind"] == "message" for m in Ca.get(B + f"/api/agents/{TK}/chat").json()["messages"]), "for carl they are normal messages")
# review F3: the agent polls and says what it does - carl sees none of it
requests.get(V + "/agent/events?wait=0", headers=TKH, timeout=30)
requests.put(V + "/agent/status", headers=TKH, json={"status": "working", "text": "On the books"}, timeout=30)
check(dbx("SELECT last_poll_at IS NOT NULL, status FROM agents WHERE user_id=?", (TK,)) == [(True, "working")], "setup: the agent polled and works")
F3_EMPTY = {"status": "idle", "status_text": "", "host": None, "runtime_model": "", "permission_mode": "", "quota": None, "cost": None,
            "limit_reached": False, "last_poll_at": None, "poll_age": None, "contact_age": None}
a = listed(Ca, TK)
check(a and all(a.get(k) == v for k, v in F3_EMPTY.items()), f"review F3: the tab Agents shows carl nothing of its host, model, usage, contact {a}")
ag = Ca.get(B + f"/api/agents/{TK}/chat").json().get("agent") or {}
check(all(ag.get(k) == v for k, v in F3_EMPTY.items()) and "online" in ag, f"review F3: nor its chat header {ag}")
for path in (f"/api/agents/{TK}/schedules", f"/api/agents/{TK}/server", f"/api/agents/{TK}/server/starter"):
    check(Ca.get(B + path).status_code == 404, f"carl gets no data of it: {path} 404")
for s, who in ((Gu, "a guest"), (Ol, "another organisation's admin"), (Fr, "a person without an organisation")):
    check(s.get(B + f"/api/agents/{TK}/chat").status_code == 404, f"{who}: its chat 404")
    check(s.post(B + f"/api/agents/{TK}/chat", json={"body": "hi"}).status_code == 404, f"{who}: writing 404")
    check(s.get(B + f"/api/agents/{TK}/server/starter").status_code == 404, f"{who}: the state route 404")

# ================================================================ bob shares a project: the waiting plans start at once
P = Bo.post(B + "/api/lists", json={"name": "Team project", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{P}/members", json={"user_id": TK, "role": "edit"}).ok, "bob shares his project with the team agent")
ACTIVE3 = [("briefing", 1, 0, True), ("followup", 1, 0, True), ("tidy", 1, 0, True)]
check(until(lambda: sorted(plans_db(TK)) == ACTIVE3, 75), f"the watchdog switches the waiting plans on with their next due time {plans_db(TK)}")
j = Bo.get(B + f"/api/agents/{TK}/server/starter").json()
check(j.get("shared") is True and j.get("projects") == 1 and j["items"]["briefing"] == "active", f"the state: shared, 1 project, active {j}")
a = listed(Ca, TK)
check(a and a.get("projects") == 1 and a.get("shared") is False, f"carl: '1 project', still not shared with him {a}")
check(a and a.get("status") == "idle" and a.get("last_poll_at") is None, "review F3: carl still sees nothing of its work")
a = listed(Bo, TK)
check(a and a.get("status") == "working" and a.get("last_poll_at"), "review F3: bob, who shares a project with it, sees it working")
r = Ca.post(B + f"/api/agents/{TK}/chat", json={"body": "And now?"})
check(r.status_code == 201 and "do not see any project" in Ca.get(B + f"/api/agents/{TK}/chat").json()["messages"][-1]["body"],
      "carl still gets the fixed answer: the project is not opened to him")
rows = requests.get(V + "/agent/chats?since=0", headers=TKH, timeout=30).json().get("data") or []
check(not [m for m in rows if (m.get("user") or {}).get("id") == uid["carl"]], "review F1: with a project shared now, carl's earlier rows still never reach the agent")
# a plan switched off by hand no longer waits
sid = next(p["id"] for p in Bo.get(B + f"/api/agents/{TK}/schedules").json()["data"] if p["title"] == "Follow up")
check(Bo.patch(B + f"/api/agent-schedules/{sid}", json={"enabled": False}).ok, "bob switches the follow-up off")
check(dbx("SELECT enabled, share_wait FROM agent_schedules WHERE id=?", (sid,)) == [(0, 0)], "switched off by hand: no waiting mark")

# ================================================================ asked again after sharing: the waiting plans start at once
r = Bo.post(B + f"/api/orgs/{ORG}/server-agents", json={"username": "teamki3", "display_name": "Team KI Three"})
TK3 = r.json().get("id")
check(states(starter(Bo, TK3, ["briefing", "tidy", "followup"])) == {"briefing": "waiting", "tidy": "waiting", "followup": "waiting"}, "setup: three waiting plans")
P3 = Bo.post(B + "/api/lists", json={"name": "Third project", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{P3}/members", json={"user_id": TK3, "role": "edit"}).ok, "the project is shared")
r = starter(Bo, TK3, ["briefing"])
check(states(r) == {"briefing": "exists"} and sorted(plans_db(TK3)) == ACTIVE3,
      f"the item asked again: every waiting plan of the agent starts at once {r.text[:200]} {plans_db(TK3)}")

# ================================================================ review F2: only the person's OWN share wakes her plans
r = Bo.post(B + f"/api/orgs/{ORG}/server-agents", json={"username": "teamki4", "display_name": "Team KI Four"})
TK4 = r.json().get("id")
check(states(starter(Bo, TK4, ["briefing", "tidy"])) == {"briefing": "waiting", "tidy": "waiting"}, "setup: bob's two plans wait")
check(states(starter(A, TK4, ["briefing"])) == {"briefing": "waiting"}, "setup: alice's plan waits")


def plans_of(aid, u):
    return sorted(dbx("SELECT srv_flow, enabled, share_wait FROM agent_schedules WHERE agent_id=? AND user_id=?", (aid, u)))


ALICE = A.get(B + "/api/state").json()["me"]["id"]
PA = A.post(B + "/api/lists", json={"name": "Alice project", "org_id": ORG}).json()["id"]
check(A.patch(B + f"/api/lists/{PA}", json={"agent_members": True}).ok, "alice opens her project's agents to its members")
check(A.put(B + f"/api/lists/{PA}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "bob is only a member of it")
check(A.put(B + f"/api/lists/{PA}/members", json={"user_id": TK4, "role": "edit"}).ok, "alice takes the agent into her project")
j = Bo.get(B + f"/api/agents/{TK4}/server/starter").json()
check(j.get("shared") is True and j.get("own") is False and j["items"]["briefing"] == "waiting",
      f"bob reaches the agent through alice's project, but has shared nothing himself {j}")
check(until(lambda: plans_of(TK4, ALICE) == [("briefing", 1, 0)], 75), f"alice's own share: the watchdog starts her plan {plans_of(TK4, ALICE)}")
check(plans_of(TK4, uid["bob"]) == [("briefing", 0, 1), ("tidy", 0, 1)],
      f"review F2: the same watchdog turn leaves bob's plans waiting (only a member of alice's project) {plans_of(TK4, uid['bob'])}")
PB = Bo.post(B + "/api/lists", json={"name": "Bob project", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{PB}/members", json={"user_id": TK4, "role": "edit"}).ok, "bob shares his own project with the agent")
check(until(lambda: plans_of(TK4, uid["bob"]) == [("briefing", 1, 0), ("tidy", 1, 0)], 75),
      f"bob's own share: his plans start {plans_of(TK4, uid['bob'])}")
check(Bo.get(B + f"/api/agents/{TK4}/server/starter").json().get("own") is True, "the state route: own")

# ================================================================ the dialog's order: a project first, then the pack
r = Bo.post(B + f"/api/orgs/{ORG}/server-agents", json={"username": "teamki2", "display_name": "Team KI Two"})
TK2 = r.json().get("id")
P2 = Bo.post(B + "/api/lists", json={"name": "Second project", "org_id": ORG}).json()["id"]
check(Bo.put(B + f"/api/lists/{P2}/members", json={"user_id": TK2, "role": "edit"}).ok, "the project is shared first")
r = starter(Bo, TK2, ["briefing", "tidy"])
check(states(r) == {"briefing": "created", "tidy": "created"} and sorted(plans_db(TK2)) == [("briefing", 1, 0, True), ("tidy", 1, 0, True)],
      f"then the pack: created and active at once {r.text[:300]} {plans_db(TK2)}")

# ================================================================ a person without an organisation (freelancer-matrix: agents)
r = Fr.post(B + "/api/my/agents", json={"username": "frida-ki", "display_name": "Frida KI", "provider": "kalmido-server", "org_id": None})
check(r.status_code in (200, 201), f"frida: her personal server agent {r.status_code} {r.text[:200]}")
FA = r.json().get("id")
FL = Fr.post(B + "/api/lists", json={"name": "Frida project"}).json()["id"]
check(Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FA, "role": "edit"}).ok, "frida shares her own project with it")
r = starter(Fr, FA, ["briefing", "followup", "meetings"])
check(states(r) == {"briefing": "created", "followup": "created", "meetings": "created"}, f"frida: the pack is created {r.text[:300]}")
j = Fr.get(B + f"/api/agents/{FA}/server/starter").json()
check(j.get("shared") is True and j.get("projects") == 1 and j.get("org_id") is None and j["items"]["briefing"] == "active"
      and j["items"]["tidy"] == "missing", f"frida: the state route {j}")
a = listed(Fr, FA)
check(a and "projects" not in a and "shared" not in a, f"her personal agent: no team fields {a}")
check(listed(Bo, FA) is None and listed(Ca, FA) is None, "her personal agent: nobody else sees it")
check(Ca.get(B + f"/api/agents/{FA}/server/starter").status_code == 404, "the state route of her agent: 404 for others")

sys.exit(done("p2777_c_srvagent"))
