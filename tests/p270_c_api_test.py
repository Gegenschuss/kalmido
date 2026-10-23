#!/usr/bin/env python3
"""2.70.0 API tests, part C (#1359): contracts in view -- an agent reminds a person of a notice deadline. Invented names only.
 - the event contract_notice (watchdog): for open contracts whose last day to cancel is within their lead (else 30 days), to
   the agent the contract's list is shared with; not to an agent without the share, one limited to other lists
   (agents.list_ids), one of another organisation (agents.org_id), not for a far / completed contract, once per contract and
   deadline (a moved deadline = a new one); the event's data (cost per month, cancel by, end of the term, person, language)
 - POST /api/v1/agent/proposals {kind: notice, task_id, text}: only after a contract_notice (409 otherwise), a contract the
   agent cannot see 404, a task that is no contract 404, validation (text <= 300, unknown fields), a new one replaces the open
   one, the title never shows the cost, POST /api/proposals kind notice 400
 - the person: the card's data, the agent cannot apply / discard, another person 404; apply = a comment as the person, the
   history line, with remind a reminder 3 days before; undo / redo one step; a second apply 409; discard; the agent hears both
 - a freelancer without an organisation (own contract list, own agent) gets it the same way
 - health lists and the journal never reach an agent: a contract in a health list (also with an agent member) sends nothing,
   the agent reads neither the list nor its tasks, no journal in the review, the briefing or over PUT, no scope private
usage: p270_c_api_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time
from datetime import timedelta

import requests

import dbx as dbxm
import testclock

N = os.path.dirname(os.path.abspath(__file__))
from kt import FAILS, OKS, check, sess, until, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
V = B + "/api/v1"


def dbx(q, a=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def tokh(t):
    return {"Authorization": "Bearer " + t}


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
LIFE = "cal,comments,collab,agents,contracts,health,review"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": LIFE})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Free", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"tour": "done", "lang": "de", "features": LIFE})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ALICE}).json()["id"]
T0 = testclock.today()
D = lambda n: (T0 + timedelta(days=n)).isoformat()  # noqa: E731


def agent(name):
    r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": name, "display_name": name.title()})
    assert r.status_code == 201, r.text
    dbx("UPDATE agents SET org_id=NULL WHERE user_id=?", (r.json()["id"],))  # private agents unless a test sets one
    return r.json()["id"], tokh(r.json()["token"])


def contract(s, name, ends, **kw):
    r = s.post(B + "/api/life/contracts", json={"name": name, "ends": ends, "notice": 0, "renew_months": 12, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def events(h, kind="contract_notice"):
    r = requests.get(V + "/agent/events?since=0&limit=500", headers=h)
    return [e for e in r.json().get("data", []) if e["event"] == kind] if r.ok else []


def share(s, lid, uid):
    r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": "edit"})
    check(r.ok, f"setup: share list {lid} with {uid} " + r.text[:200])


def propose(h, tid, text="Your mobile phone contract can be cancelled until the 1st; it costs 19.99 a month.", **kw):
    return requests.post(V + "/agent/proposals", headers=h, json={"kind": "notice", "task_id": tid, "text": text, **kw})


CLA, CLH = agent("claude")      # the contract list is shared with it
ROB, ROH = agent("robo")        # nothing shared
LIM, LIH = agent("limbot")      # shared, but limited to another list
BET, BEH = agent("betabot")     # of another organisation
HEA, HEH = agent("healthbot")   # a member of the health list (forced in)

# ---------------------------------------------------------------- contracts of alice
C_MOB = contract(A, "Mobile phone", D(10), provider="Telco", cost="19,99", per="month", lead_days=14)
CL1 = C_MOB["list_id"]
C_FAR = contract(A, "Far insurance", D(200), cost=300, per="year", lead_days=14)
C_L60 = contract(A, "Electricity", D(50), cost=600, per="year", lead_days=60, list_id=CL1)
C_L0 = contract(A, "Streaming", D(20), cost=9, per="month", lead_days=0, list_id=CL1)       # no own lead: 30 days
C_EDGE = contract(A, "Gym", D(25), cost=30, per="month", lead_days=14, list_id=CL1)          # 25 > 14: not yet
C_DONE = contract(A, "Old phone", D(5), cost=5, per="month", lead_days=14, list_id=CL1)
dbx("UPDATE tasks SET status=2, completed_at=? WHERE id=?", ("2026-01-01T00:00:00Z", C_DONE["id"]))
PLAIN = A.post(B + "/api/tasks", json={"title": "Not a contract", "list_id": CL1, "due": D(3)}).json()["id"]
share(A, CL1, CLA)
CL2 = A.post(B + "/api/lists", json={"name": "Contracts two"}).json()["id"]
OTHER = A.post(B + "/api/lists", json={"name": "Other"}).json()["id"]
C_LIM = contract(A, "Car insurance", D(9), cost=40, per="month", list_id=CL2)
dbx("UPDATE agents SET org_id=? WHERE user_id=?", (ORG, LIM))
# 2.148.1 (#2480): with two organisations and none chosen a new list is private (was: the first one) -> put both into Alpha
dbx("UPDATE lists SET org_id=? WHERE id IN (?,?)", (ORG, CL2, OTHER))
dbx("UPDATE agents SET list_ids=? WHERE user_id=?", (str(OTHER), LIM))  # first the limit, then the shares (the watchdog runs every second)
share(A, CL2, LIM)
share(A, OTHER, LIM)
CL3 = A.post(B + "/api/lists", json={"name": "Alpha contracts"}).json()["id"]
C_ORG = contract(A, "Office lease", D(9), cost=900, per="month", list_id=CL3)
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, CL3))
dbx("UPDATE agents SET org_id=? WHERE user_id=?", (ORG2, BET))
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,?,?)", (CL3, BET, "edit", "edit", 99, "2026-01-01T00:00:00Z"))
# a contract inside the health list (a person may file it there) + an agent forced in as a member
r = A.post(B + "/api/life/health", json={"type": "appointment", "title": "Dentist", "date": D(4)})
check(r.status_code == 201, "setup: a health entry " + r.text[:200])
HL = [l["id"] for l in A.get(B + "/api/state").json()["lists"] if l.get("life") == "health"][0]
C_HEA = contract(A, "Health insurance", D(7), cost=80, per="month", list_id=HL)
check(A.put(B + f"/api/lists/{HL}/members", json={"user_id": HEA, "role": "edit"}).status_code == 409, "sharing the health list with an agent: 409")
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,?,?)", (HL, HEA, "edit", "edit", 99, "2026-01-01T00:00:00Z"))

# ---------------------------------------------------------------- the event contract_notice
ev = until(lambda: len(events(CLH)) >= 3 and events(CLH))
ids = sorted(e["data"]["task_id"] for e in ev)
check(ids == sorted([C_MOB["id"], C_L60["id"], C_L0["id"]]), f"contract_notice for the contracts in reach (own lead, else 30 days) {ids}")
d = next((e["data"] for e in ev if e["data"]["task_id"] == C_MOB["id"]), {})
check(d.get("name") == "Mobile phone" and d.get("provider") == "Telco" and d.get("cost") == 19.99 and d.get("per") == "month"
      and d.get("monthly") == 19.99 and d.get("due") == D(10) and d.get("ends") == D(10) and d.get("renew_months") == 12
      and d.get("list_id") == CL1 and d.get("user") == {"id": ALICE, "name": "Alice"} and d.get("lang") == "en" and d.get("days") == 10
      and "propose_contract_notice" in d.get("hint", ""), "the event's data " + json.dumps(d)[:400])
de = next((e["data"] for e in ev if e["data"]["task_id"] == C_L60["id"]), {})
check(de.get("monthly") == 50.0 and de.get("yearly") == 600.0, "a yearly cost comes per month too")
check(all(e.get("actor") is None for e in ev), "the event comes from Kalmido (no actor)")
time.sleep(3)
check(len(events(CLH)) == 3, "once per contract and deadline (no second event)")
check(not events(ROH), "an agent the list is not shared with gets nothing")
check(not events(LIH), "an agent limited to other lists (agents.list_ids) gets nothing")
check(not events(BEH), "an agent of another organisation (agents.org_id) gets nothing, even as a member")
check(not events(HEH), "nothing from a health list, even with the agent as a member")
check(dbx("SELECT COUNT(*) FROM ctr_notices WHERE task_id=? AND due=? AND agent_id=?", (C_MOB["id"], D(10), CLA))[0][0] == 1,
      "the sent marker (ctr_notices)")
r = A.patch(B + f"/api/tasks/{C_EDGE['id']}", json={"due": D(5)})
check(r.ok, "move the gym deadline into reach")
check(until(lambda: any(e["data"]["task_id"] == C_EDGE["id"] for e in events(CLH))), "a deadline that comes into reach: its event")
A.patch(B + f"/api/tasks/{C_MOB['id']}", json={"due": D(8)})
check(until(lambda: sum(e["data"]["task_id"] == C_MOB["id"] for e in events(CLH)) == 2), "a moved deadline = a new event")

# ---------------------------------------------------------------- the agent proposes
r = propose(CLH, C_MOB["id"])
check(r.status_code == 201 and r.json().get("kind") == "notice", "the agent proposes a sentence " + r.text[:300])
J1 = r.json().get("id")
inp = r.json().get("input") or {}
check(inp.get("user_id") == ALICE and inp.get("due") == D(8) and inp.get("cost") == 19.99, "the job input: the person, the deadline, the cost")
title = r.json().get("title") or ""
check("Mobile phone" in title and "19" not in title, "the title names the contract, never its cost: " + title)
check(propose(CLH, C_FAR["id"]).status_code == 409, "a contract without contract_notice: 409")
check(propose(ROH, C_MOB["id"]).status_code == 404, "an agent that cannot see the contract: 404")
check(propose(LIH, C_LIM["id"]).status_code == 404, "the list-limited agent: 404")
check(propose(BEH, C_ORG["id"]).status_code == 404, "the agent of another organisation: 404")
check(propose(HEH, C_HEA["id"]).status_code == 404 and propose(CLH, C_HEA["id"]).status_code == 404, "a contract in the health list: 404")
check(propose(CLH, PLAIN).status_code == 404, "a task that is no contract: 404")
check(propose(CLH, 999999).status_code == 404, "an unknown task: 404")
check(propose(CLH, C_MOB["id"], text="x" * 301).status_code == 400, "a sentence over 300 characters: 400")
check(propose(CLH, C_MOB["id"], text="  ").status_code == 400, "an empty sentence: 400")
check(propose(CLH, C_MOB["id"], cost=1).status_code == 400, "unknown fields: 400")
check(propose(CLH, "1").status_code == 400, "task_id must be a number: 400")
check(requests.post(V + "/agent/proposals", headers=CLH, data="x" * 300000, timeout=20).status_code in (400, 413), "a huge body: refused")
check(requests.post(V + "/agent/proposals", json={"kind": "notice", "task_id": C_MOB["id"], "text": "x"}).status_code in (401, 403),
      "without a token: refused")
r = A.post(B + "/api/proposals", json={"agent_id": CLA, "kind": "notice", "task_id": C_MOB["id"]})
check(r.status_code == 400, "a person cannot ask for kind notice: 400")
r = propose(CLH, C_MOB["id"], text="Cancel by the deadline to save 239.88 a year, or keep it if you still need it.")
check(r.status_code == 201, "a second sentence")
J2 = r.json()["id"]
st = dict(dbx("SELECT id, prop_state FROM agent_jobs WHERE id IN (?,?)", (J1, J2)))
check(st.get(J1) == "discarded" and st.get(J2) == "ready", f"the new one replaces the open one {st}")
check(any(n.get("kind") == "proposal" for n in A.get(B + "/api/news").json().get("items", [])), "News: proposal ready")

# ---------------------------------------------------------------- the person decides
r = A.get(B + f"/api/proposals/{J2}")
v = r.json() if r.ok else {}
k = v.get("contract") or {}
check(r.ok and v.get("kind") == "notice" and v["proposal"]["text"].startswith("Cancel by") and k.get("due") == D(8)
      and k.get("cost") == 19.99 and k.get("can_remind") is True and k.get("name") == "Mobile phone", "the card's data " + json.dumps(v)[:400])
check(requests.post(B + f"/api/proposals/{J2}/apply", headers={**H, **CLH}, json={"select": ["0"]}).status_code in (401, 403, 404),
      "the agent cannot apply its own proposal")
check(requests.post(B + f"/api/proposals/{J2}/discard", headers={**H, **CLH}).status_code in (401, 403, 404), "… nor discard it")
check(Bo.get(B + f"/api/proposals/{J2}").status_code == 404 and Bo.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"]}).status_code == 404,
      "another person: 404")
rem0 = dbx("SELECT reminders FROM tasks WHERE id=?", (C_MOB["id"],))[0][0]
r = A.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"], "remind": True})
check(r.ok and r.json().get("reminder") is True and r.json().get("comment_id"), "apply with remind " + r.text[:300])
cid = r.json().get("comment_id")
row = dbx("SELECT user_id, body, deleted_at FROM comments WHERE id=?", (cid,))
check(row and row[0][0] == ALICE and row[0][1].startswith("Cancel by") and row[0][2] is None, "a comment as the person")
rem1 = dbx("SELECT reminders FROM tasks WHERE id=?", (C_MOB["id"],))[0][0]
check("4320" in rem1.split(",") and set(rem0.split(",")) < set(rem1.split(",")), f"a reminder 3 days before ({rem0} -> {rem1})")
check(dbx("SELECT COUNT(*) FROM activity WHERE task_id=? AND kind='proposal'", (C_MOB["id"],))[0][0] >= 1, "the history line")
check(A.post(B + f"/api/proposals/{J2}/apply", json={"select": ["0"]}).status_code == 409, "a second apply: 409")
check(until(lambda: any(e["data"].get("action") == "approve" and e["data"]["job"]["id"] == J2 for e in events(CLH, "job")), 10),
      "the agent hears approve")
r = A.post(B + f"/api/proposals/{J2}/undo")
check(r.ok and r.json().get("undone", 0) >= 1, "undo " + r.text[:200])
check(dbx("SELECT deleted_at FROM comments WHERE id=?", (cid,))[0][0] is not None
      and dbx("SELECT reminders FROM tasks WHERE id=?", (C_MOB["id"],))[0][0] == rem0, "undo: the comment and the reminder go")
r = A.post(B + f"/api/proposals/{J2}/redo")
check(r.ok and dbx("SELECT deleted_at, body FROM comments WHERE id=?", (cid,))[0][0] is None
      and "4320" in dbx("SELECT reminders FROM tasks WHERE id=?", (C_MOB["id"],))[0][0], "redo: both come back")
# discard
r = propose(CLH, C_L60["id"], text="Electricity: until the deadline you can switch; it costs 50 a month.")
J3 = r.json().get("id")
check(r.status_code == 201 and A.post(B + f"/api/proposals/{J3}/discard").ok, "discard")
check(A.post(B + f"/api/proposals/{J3}/apply", json={"select": ["0"]}).status_code == 409, "apply after discard: 409")
check(until(lambda: any(e["data"].get("action") == "reject" and e["data"]["job"]["id"] == J3 for e in events(CLH, "job")), 10),
      "the agent hears reject")
check(not dbx("SELECT 1 FROM comments WHERE task_id=?", (C_L60["id"],)), "discard writes nothing")
# a note without remind on a near deadline: no reminder button
r = propose(CLH, C_L0["id"], text="Streaming: 9 a month, cancel by the deadline if you do not watch it.")
J4 = r.json().get("id")
r = A.post(B + f"/api/proposals/{J4}/apply", json={"select": ["0"]})
check(r.ok and r.json().get("reminder") is False and dbx("SELECT reminders FROM tasks WHERE id=?", (C_L0["id"],))[0][0] == C_L0["reminders"],
      "apply without remind: only the note")
check(not any(x in (dbx("SELECT title FROM agent_jobs WHERE id=?", (J4,))[0][0] or "") for x in ("9", "€")), "no amount in the title")

# ---------------------------------------------------------------- freelancer without an organisation
A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2})
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "display_name": "Bob Bot"})
check(r.status_code == 201, "the freelancer's own agent " + r.text[:200])
BB, BBH = r.json()["id"], tokh(r.json()["token"])
C_BOB = contract(Bo, "Handyvertrag", D(6), cost=12, per="month")
share(Bo, C_BOB["list_id"], BB)
ev = until(lambda: events(BBH))
check(ev and ev[0]["data"]["task_id"] == C_BOB["id"] and ev[0]["data"]["lang"] == "de" and ev[0]["data"]["user"]["id"] == BOB,
      "freelancer: the event in the person's language")
r = propose(BBH, C_BOB["id"], text="Dein Handyvertrag kostet 12 im Monat; kuendigen kannst du bis zur Frist.")
check(r.status_code == 201, "freelancer: the proposal " + r.text[:200])
r = Bo.post(B + f"/api/proposals/{r.json().get('id')}/apply", json={"select": ["0"]})
check(r.ok and dbx("SELECT user_id FROM comments WHERE id=?", (r.json().get("comment_id"),))[0][0] == BOB, "freelancer: the note as the person")
check(not any(e["data"]["task_id"] == C_BOB["id"] for e in events(CLH)), "alice's agent hears nothing of bob's contract")

# ---------------------------------------------------------------- health lists and the journal stay closed
check(HL not in [l["id"] for l in requests.get(V + "/lists", headers=HEH).json().get("data", [])], "health list: not in GET /lists")
check(requests.get(V + f"/lists/{HL}", headers=HEH).status_code == 404 and requests.get(V + f"/tasks/{C_HEA['id']}", headers=HEH).status_code == 404,
      "health list: the list and its contract 404 for the member agent")
check(requests.get(V + "/search", headers=HEH, params={"q": "Health insurance"}).json().get("data") == [], "health list: not in the search")
lj = requests.get(V + "/life", headers=HEH)
check(lj.ok and "health" not in lj.json() and "Health insurance" not in lj.text, "GET /life: no health part, no health contract")
check(A.put(B + f"/api/life/journal/{D(0)}", json={"text": "Secret journal line 7781", "mood": 2}).ok, "alice writes her journal")
for h, who in ((CLH, "claude"), (HEH, "healthbot")):
    rv = requests.get(V + "/life/review", headers=h)
    check("journal" not in (rv.json() if rv.ok else {}) and "7781" not in rv.text, f"{who}: no journal in the review")
    rb = requests.get(V + "/briefing", headers=h, params={"user_id": ALICE})
    check("7781" not in rb.text, f"{who}: no journal in the briefing ({rb.status_code})")
    check(requests.put(V + f"/life/journal/{D(0)}", headers=h, json={"text": "x"}).status_code in (403, 404, 409), f"{who}: no journal write")
check(dbx("SELECT text FROM journal WHERE user_id=? AND day=?", (ALICE, D(0)))[0][0] == "Secret journal line 7781", "the journal is untouched")
r = A.patch(B + f"/api/admin/agents/{CLA}", json={"scopes": ["read", "private"]})
check(r.status_code == 400, "an agent never gets the scope private (400)")
sc = {(p, m): o.get("x-kalmido-scope") for p, ms in requests.get(V + "/openapi.json").json()["paths"].items() for m, o in ms.items()}
check(bool(sc.get(("/agent/proposals", "post"))), f"OpenAPI: POST /agent/proposals carries x-kalmido-scope ({sc.get(('/agent/proposals', 'post'))})")
spec = requests.get(V + "/openapi.json").json()["paths"]["/agent/proposals"]["post"]
check("notice" in json.dumps(spec), "OpenAPI: the kind notice is documented")
check("contract_notice" in json.dumps(requests.get(V + "/openapi.json").json()), "OpenAPI: the event contract_notice")
check(requests.get(V + "/agent", headers=CLH).ok and "contract_notice" in requests.get(V + "/agent", headers=CLH).text, "GET /agent lists the event")

print(f"p270_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
