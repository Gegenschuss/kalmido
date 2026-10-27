#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.235.0 C (#2903): the standing rules of an agent ("from now on always ...") over the agent API and the owner routes
 - the agent saves a rule with its source (POST /api/v1/agent/rules): a chat message of a person to it or a comment it can
   see -> 201; its own chat answer, another agent's chat, a comment in a project it is not in, a gone id -> 404; the same
   text again -> 200 duplicate; bad text / source / an unknown field -> 400; 500 characters, 100 rules per agent (two
   parallel requests at 99 rules: exactly one passes)
 - GET /api/v1/agent "rules" = only the active ones (no paused), GET /api/v1/agent/rules lists all with state + source
 - the owner reads, rewords, pauses, resumes, deletes, adds by hand (GET / POST / PATCH / DELETE /api/agents/<id>/rules);
   each change = the event rules_changed (change + the active rules); the agent's own POST sends none
 - another person 404 (read and write), an instance admin reaches a team agent (not a foreign personal one), a member of
   the team 404; the excerpt / link of a source only for a person who sees it themselves
 - the same as a person without an organisation (freelancer-matrix: agents)
usage: p2235_c_rules_api_test.py <datadir>      (KMT_NOSTART=1 / P2235C_NOSTART=1: a running server)"""
import sys
import threading

import requests

import kt
from freelancer_fixture import freelancer
from kt import B, H, check, done, fresh, sess

V = B + "/api/v1"
fresh(prefix="P2235C")
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Org", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FID, F = freelancer(B, A)
OID, O = freelancer(B, A, "otto")


def own_agent(s, name):
    r = s.post(B + "/api/my/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "comments"]})
    check(r.status_code in (200, 201), f"{name}: a personal agent {r.status_code} {r.text[:120]}")
    j = r.json()
    return j["id"], {"Authorization": "Bearer " + j["token"]}


def add(h, text, kind, sid, **extra):
    return requests.post(V + "/agent/rules", headers=h, json={"text": text, "source": {"kind": kind, "id": sid}, **extra})


def rules(s, aid):
    r = s.get(B + f"/api/agents/{aid}/rules")
    return r.status_code, (r.json().get("rules") if r.ok else None)


def events(h, cur, name="rules_changed"):
    j = requests.get(V + f"/agent/events?since={cur}&limit=100", headers=h).json()
    return [e for e in j.get("data") or [] if e["event"] == name]


def cursor(h):
    return requests.get(V + "/agent/events?since=latest", headers=h).json()["cursor"]


# ================================================================ a person without an organisation and her own agent
# freelancer-matrix: agents
FA, FH = own_agent(F, "fridabot")
OA, OH = own_agent(O, "ottobot")
L = F.post(B + "/api/lists", json={"name": "Studio"}).json()["id"]
check(F.put(B + f"/api/lists/{L}/members", json={"user_id": FA, "role": "edit"}).ok, "the agent in the private project")
T = F.post(B + "/api/tasks", json={"title": "Invoices", "list_id": L}).json()["id"]
L2 = F.post(B + "/api/lists", json={"name": "Private"}).json()["id"]  # not shared with the agent
T2 = F.post(B + "/api/tasks", json={"title": "Diary", "list_id": L2}).json()["id"]

m = F.post(B + f"/api/agents/{FA}/chat", json={"body": "From now on always write invoices in English"})
check(m.status_code in (200, 201), f"a chat message to the agent {m.status_code}")
MID = m.json()["id"]
cur0 = cursor(FH)
r = add(FH, "Always write invoices in English", "chat", MID)
check(r.status_code == 201, f"the agent saves a rule from the chat {r.status_code} {r.text[:200]}")
R1 = r.json()["rule"]
check(R1["state"] == "active" and R1["source"]["kind"] == "chat" and R1["source"]["id"] == MID and R1["source"]["user_id"] == FID
      and "write invoices in English" in R1["source"]["excerpt"], f"state + source + excerpt {R1}")
r = add(FH, "always write invoices in english", "chat", MID)
check(r.status_code == 200 and r.json()["duplicate"] is True and r.json()["rule"]["id"] == R1["id"], f"the same text = that rule {r.status_code}")

# sources the agent may not name
ans = requests.post(V + f"/agent/chats/{FID}", headers=FH, json={"body": "Saved as a standing rule."})
check(ans.ok, f"the agent answers {ans.status_code}")
check(add(FH, "x1", "chat", ans.json()["id"]).status_code == 404, "its own chat answer is no source")
om = O.post(B + f"/api/agents/{OA}/chat", json={"body": "from now on never"}).json()["id"]
check(add(FH, "x2", "chat", om).status_code == 404, "a message of another agent's chat: 404")
c_ok = F.post(B + f"/api/tasks/{T}/comments", json={"body": "In future always attach the PDF"}).json()["id"]
c_no = F.post(B + f"/api/tasks/{T2}/comments", json={"body": "From now on always lock the diary"}).json()["id"]
check(add(FH, "x3", "comment", c_no).status_code == 404, "a comment in a project the agent is not in: 404")
check(add(FH, "x4", "comment", 10 ** 9).status_code == 404, "a gone comment: 404")
r = add(FH, "Always attach the PDF", "comment", c_ok)
check(r.status_code == 201 and r.json()["rule"]["source"]["task_id"] == T, f"a rule from a comment it sees {r.status_code} {r.text[:160]}")
R2 = r.json()["rule"]
for bad in ({"text": "x" * 501, "source": {"kind": "chat", "id": MID}}, {"text": "  ", "source": {"kind": "chat", "id": MID}},
            {"text": "ok"}, {"text": "ok", "source": {"kind": "mail", "id": 1}}, {"text": "ok", "source": {"kind": "chat", "id": "1"}},
            {"text": "ok", "source": {"kind": "chat", "id": MID, "x": 1}}, {"text": "ok", "source": {"kind": "chat", "id": MID}, "state": "paused"}):
    r = requests.post(V + "/agent/rules", headers=FH, json=bad)
    check(r.status_code == 400, f"refused {str(bad)[:60]} -> {r.status_code}")
check(add(FH, "y" * 500, "chat", MID).status_code == 201, "500 characters pass")
check(not events(FH, cur0), "the agent's own POST sends no rules_changed")

# what the agent reads
j = requests.get(V + "/agent", headers=FH).json()
check([x["id"] for x in j["rules"]][:2] == [R1["id"], R2["id"]] and set(j["rules"][0]) == {"id", "text", "created_at", "source"},
      f"GET /api/v1/agent rules = the active ones {j.get('rules')}")

# ---------------------------------------------------------------- the owner
st, rs = rules(F, FA)
check(st == 200 and len(rs) == 3, f"the owner reads the list {st}")
v1 = next(x for x in rs if x["id"] == R1["id"])
check(v1["source"]["visible"] is True and v1["source"]["excerpt"], "her own chat: excerpt + link")
cur = cursor(FH)
r = F.patch(B + f"/api/agents/{FA}/rules/{R1['id']}", json={"state": "paused"})
check(r.ok and r.json()["rule"]["state"] == "paused", f"the owner pauses {r.status_code} {r.text[:120]}")
ev = kt.until(lambda: events(FH, cur), 10)
check(ev and ev[-1]["data"]["change"] == "paused" and R1["id"] not in [x["id"] for x in ev[-1]["data"]["rules"]],
      f"rules_changed paused without the paused rule {ev[-1]['data'] if ev else None}")
j = requests.get(V + "/agent", headers=FH).json()
check(R1["id"] not in [x["id"] for x in j["rules"]], "a paused rule is not in the agent's context")
allr = requests.get(V + "/agent/rules", headers=FH).json()
check(any(x["id"] == R1["id"] and x["state"] == "paused" for x in allr["data"]) and allr["max"] == 100, "GET /agent/rules lists it as paused")
r = F.patch(B + f"/api/agents/{FA}/rules/{R1['id']}", json={"state": "active", "text": "Invoices always in English"})
check(r.ok and r.json()["rule"]["state"] == "active" and r.json()["rule"]["text"] == "Invoices always in English", "resume + reword")
ev = kt.until(lambda: [e for e in events(FH, cur) if e["data"]["change"] == "resumed"], 10)
check(ev and any(x["text"] == "Invoices always in English" for x in ev[-1]["data"]["rules"]), "rules_changed resumed with the new text")
for bad in ({"state": "off"}, {"text": ""}, {"text": "z" * 501}, {"source": 1}):
    check(F.patch(B + f"/api/agents/{FA}/rules/{R1['id']}", json=bad).status_code == 400, f"PATCH refused {str(bad)[:40]}")
r = F.post(B + f"/api/agents/{FA}/rules", json={"text": "Never book on Sundays"})
check(r.status_code == 201 and r.json()["rule"]["source"]["kind"] == "manual", f"a rule by hand {r.status_code}")
MAN = r.json()["rule"]["id"]
cur = cursor(FH)
check(F.delete(B + f"/api/agents/{FA}/rules/{MAN}").ok, "the owner deletes")
check(kt.until(lambda: [e for e in events(FH, cur) if e["data"]["change"] == "deleted"], 10), "rules_changed deleted")
check(F.delete(B + f"/api/agents/{FA}/rules/{MAN}").status_code == 404, "deleted twice: 404")

# ---------------------------------------------------------------- others
check(rules(O, FA)[0] == 404, "another person: GET 404")
check(O.patch(B + f"/api/agents/{FA}/rules/{R1['id']}", json={"state": "paused"}).status_code == 404, "another person: PATCH 404")
check(O.delete(B + f"/api/agents/{FA}/rules/{R1['id']}").status_code == 404, "another person: DELETE 404")
check(O.post(B + f"/api/agents/{FA}/rules", json={"text": "mine"}).status_code == 404, "another person: POST 404")
check(rules(A, FA)[0] == 404, "an instance admin does not reach a foreign personal agent")
check(F.patch(B + f"/api/agents/{OA}/rules/{R1['id']}", json={"state": "paused"}).status_code == 404, "a rule id under another agent: 404")
check(requests.get(B + f"/api/agents/{FA}/rules", headers={**FH, "X-Requested-With": "kalmido"}).status_code in (401, 403, 404),
      "the agent's token does not reach the owner routes")

# ---------------------------------------------------------------- the limit, two parallel requests at 99
n = len(requests.get(V + "/agent/rules", headers=FH).json()["data"])
kt.dbx("INSERT INTO agent_rules(agent_id, body, state, source_kind, created_at, updated_at) "
       "SELECT ?, 'filler ' || g, 'active', '', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00' FROM generate_series(1, ?) g",
       (FA, 99 - n))
res = []
ths = [threading.Thread(target=lambda i=i: res.append(add(FH, f"parallel {i}", "chat", MID).status_code)) for i in range(2)]
[t.start() for t in ths]
[t.join() for t in ths]
check(sorted(res) == [201, 400], f"at 99 rules two parallel requests: exactly one passes {res}")
check(F.post(B + f"/api/agents/{FA}/rules", json={"text": "one more"}).status_code == 400, "the owner too: no 101st")

# ================================================================ a team agent (organisation)
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
BOB = r.json()["id"]
A.post(B + "/api/users", json={"orgs": [ORG], "username": "carol", "display_name": "Carol", "password": "password123", "email": "carol@example.com"})
Bo, Ca = sess("bob"), sess("carol")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "comments"], "username": "teambot", "display_name": "Teambot"})
TA, TH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
W = A.post(B + "/api/lists", json={"name": "Team", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{W}/members", json={"user_id": BOB, "role": "edit"}).ok
assert A.put(B + f"/api/lists/{W}/members", json={"user_id": TA, "role": "edit"}).ok
assert A.patch(B + f"/api/lists/{W}", json={"agent_members": True}).ok
TT = Bo.post(B + "/api/tasks", json={"title": "Release", "list_id": W}).json()["id"]
bc = Bo.post(B + f"/api/tasks/{TT}/comments", json={"body": f"<@{TA}> from now on always link the ticket"}).json()["id"]
r = add(TH, "Always link the ticket", "comment", bc)
check(r.status_code == 201 and r.json()["rule"]["source"]["user_id"] == BOB and "<@" not in r.json()["rule"]["source"]["excerpt"],
      f"team agent: a rule from a member's comment {r.status_code} {r.text[:200]}")
bm = Bo.post(B + f"/api/agents/{TA}/chat", json={"body": "From now on always answer short"})
check(bm.status_code in (200, 201), f"bob chats with the team agent {bm.status_code}")
r = add(TH, "Answer short", "chat", bm.json()["id"])
check(r.status_code == 201, f"team agent: a rule from bob's chat {r.status_code}")
CHR = r.json()["rule"]["id"]
CL = Ca.post(B + "/api/lists", json={"name": "Carol's", "org_id": ORG}).json()["id"]
CT = Ca.post(B + "/api/tasks", json={"title": "Own", "list_id": CL}).json()["id"]
cc = Ca.post(B + f"/api/tasks/{CT}/comments", json={"body": "from now on always ..."}).json()["id"]
check(add(TH, "x5", "comment", cc).status_code == 404, "team agent: a comment of a project it is not in: 404")
st, rs = rules(A, TA)
check(st == 200 and len(rs) == 2, f"the instance admin reads the team agent's rules {st}")
chat_rule = next(x for x in rs if x["id"] == CHR)
check(chat_rule["source"]["visible"] is False and chat_rule["source"]["excerpt"] == "", "bob's chat: no excerpt for the admin")
check(next(x for x in rs if x["id"] != CHR)["source"]["visible"] is True, "the comment in her project: visible for the admin")
check(A.patch(B + f"/api/agents/{TA}/rules/{CHR}", json={"state": "paused"}).ok, "the admin pauses a team agent's rule")
check(rules(Bo, TA)[0] == 404, "a member of the team (no admin): 404")
check(rules(F, TA)[0] == 404, "a person without organisation: 404 on a team agent")
sys.exit(done("p2235_c_rules_api"))
