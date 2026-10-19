#!/usr/bin/env python3
"""2.114.0 API tests, part A (#2060): more rule triggers and actions. Invented names only.
 - triggers created, assigned (one person / anybody; only when the person is new, also via an approval request) and field
   (any change / a selection option / checked / unchecked); actions priority, tag (a list tag), field (a fixed value)
 - loop protection depth 0 stays: a value set by a rule never starts a "field changed" rule
 - invalid references 400 (formula field, wrong value type, unknown option, a tag of another list, a person outside the list)
 - only the owner / a list admin creates rules (an edit member 403); a deleted field / list tag pauses the rule
 - agents read and propose the new kinds; OpenAPI lists every enum value
 - a person without an organisation (freelancer) has the new rules in a private list
freelancer-matrix: lists
usage: p2114_a_api_test.py <datadir>      (a fresh container; P2114A_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


if not os.environ.get("P2114A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
OUT, Out = freelancer(B, A, "otto")  # someone outside the lists of alice


def mklist(s, name, org=ORG):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org})
    assert r.ok, r.text
    lid = r.json()["id"]
    if s is A and org:
        s.put(B + f"/api/lists/{lid}/members", json={"user_id": BOB, "role": "edit"})
        s.put(B + f"/api/lists/{lid}/members", json={"user_id": CAROL, "role": "edit"})
    return lid


def field(s, lid, name, ftype, **k):
    r = s.post(B + f"/api/lists/{lid}/fields", json={"name": name, "type": ftype, **k})
    assert r.ok, r.text
    return r.json()


def task(s, lid, title, **k):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **k})
    assert r.ok, r.text
    return r.json()["id"]


def get(s, tid):
    return s.get(B + f"/api/tasks/{tid}").json()


def rule(s, lid, name, trig, act, code=201):
    r = s.post(B + f"/api/lists/{lid}/rules", json={"name": name, "trigger": trig, "action": act})
    check(r.status_code == code, f"rule {name}: {code} (got {r.status_code} {r.text[:200]})")
    return r.json().get("id") if r.ok else None


def rules(s, lid):
    return {r["id"]: r for r in s.get(B + f"/api/lists/{lid}/rules").json()["rules"]}


def comments(s, tid, name):
    return [c for c in s.get(B + f"/api/tasks/{tid}/timeline").json()["comments"] if c.get("rule_name") == name]


def ltags(s, tid):
    return get(s, tid).get("ltags") or []


# ---- created -> priority high (also for a task bob creates; history marks the rule)
L1 = mklist(A, "Inbox work")
check(Bo.post(B + f"/api/lists/{L1}/rules", json={"name": "x", "trigger": {"kind": "created"},
                                                  "action": {"kind": "priority", "priority": "high"}}).status_code == 403,
      "an edit member cannot add a rule with the new kinds (403)")
rule(A, L1, "bad prio", {"kind": "created"}, {"kind": "priority", "priority": "urgent"}, 400)
R1 = rule(A, L1, "Hot", {"kind": "created"}, {"kind": "priority", "priority": "high"})
t1 = task(Bo, L1, "New lead")
check(get(A, t1).get("priority") == 5, f"created -> priority high ({get(A, t1).get('priority')})")
act = [a for a in A.get(B + f"/api/tasks/{t1}/timeline").json()["activity"] if (a["data"].get("rule") or {}).get("id") == R1]
check(act and act[0]["user_id"] == ALICE, "history: the priority change is marked with the rule, run as alice")
t1b = task(A, L1, "Later")
A.patch(B + f"/api/tasks/{t1b}", json={"priority": 1})
A.patch(B + f"/api/tasks/{t1b}", json={"title": "Later still"})
check(get(A, t1b).get("priority") == 1, "a change is not a creation: the rule does not run again")

# ---- assigned (carol -> tag hot; anybody -> comment)
L2 = mklist(A, "Team")
HOT = A.post(B + f"/api/lists/{L2}/tags", json={"name": "hot"}).json()["id"]
OTHERTAG = A.post(B + f"/api/lists/{L1}/tags", json={"name": "elsewhere"}).json()["id"]
rule(A, L2, "stranger", {"kind": "assigned", "user_id": OUT}, {"kind": "comment", "text": "x"}, 400)
rule(A, L2, "foreign tag", {"kind": "created"}, {"kind": "tag", "tag_id": OTHERTAG}, 400)
R2 = rule(A, L2, "Carol", {"kind": "assigned", "user_id": CAROL}, {"kind": "tag", "tag_id": HOT})
R3 = rule(A, L2, "Anyone", {"kind": "assigned"}, {"kind": "comment", "text": "Assigned"})
t2 = task(A, L2, "Plan")
check(not comments(A, t2, "Anyone"), "no assignee: the assigned rule does not run")
A.patch(B + f"/api/tasks/{t2}", json={"assignee_id": BOB})
check(len(comments(A, t2, "Anyone")) == 1 and "hot" not in ltags(A, t2), "assigned to bob: 'anybody' runs, 'carol' does not")
A.patch(B + f"/api/tasks/{t2}", json={"title": "Plan 2"})
check(len(comments(A, t2, "Anyone")) == 1, "the same person again: no new run")
A.patch(B + f"/api/tasks/{t2}", json={"assignee_id": CAROL})
check(len(comments(A, t2, "Anyone")) == 2 and "hot" in ltags(A, t2), f"assigned to carol: tag hot ({ltags(A, t2)})")
t2b = task(A, L2, "Born assigned", assignee_id=CAROL)
check("hot" in ltags(A, t2b), "created with carol as assignee: the person is new -> tag hot")
t2c = task(A, L2, "Needs a yes")
ap = A.post(B + f"/api/tasks/{t2c}/approval", json={"action": "request", "approver_id": CAROL})
check(ap.ok and "hot" in ltags(A, t2c), f"an approval request makes carol the assignee -> tag hot ({ap.status_code} {ltags(A, t2c)})")

# ---- field triggers / field action + loop protection
L3 = mklist(A, "Pipeline")
ST = field(A, L3, "Stage", "select", options={"options": [{"name": "Lead"}, {"name": "Won"}]})
OPT = {o["name"]: o["id"] for o in ST["options"]["options"]}
OK = field(A, L3, "Signed", "checkbox")
HRS = field(A, L3, "Hours", "number")
FX = field(A, L3, "Double", "formula", formula="{Hours} * 2")
rule(A, L3, "formula", {"kind": "field", "field_id": FX["id"]}, {"kind": "priority", "priority": "low"}, 400)
rule(A, L3, "bad option", {"kind": "field", "field_id": ST["id"], "value": "nope"}, {"kind": "priority", "priority": "low"}, 400)
rule(A, L3, "bad number", {"kind": "created"}, {"kind": "field", "field_id": HRS["id"], "value": "abc"}, 400)
rule(A, L3, "set formula", {"kind": "created"}, {"kind": "field", "field_id": FX["id"], "value": "1"}, 400)
R4 = rule(A, L3, "Won", {"kind": "field", "field_id": ST["id"], "value": OPT["Won"]}, {"kind": "priority", "priority": "high"})
R5 = rule(A, L3, "Signed", {"kind": "field", "field_id": OK["id"], "value": "1"}, {"kind": "field", "field_id": HRS["id"], "value": "8"})
R6 = rule(A, L3, "Hours", {"kind": "field", "field_id": HRS["id"]}, {"kind": "comment", "text": "Hours changed"})
R7 = rule(A, L3, "Unsigned", {"kind": "field", "field_id": OK["id"], "value": "0"}, {"kind": "priority", "priority": "low"})
rv = rules(A, L3)
check(rv[R4]["trigger"] == {"kind": "field", "field_id": ST["id"], "value": OPT["Won"]} and rv[R4]["names"].get("value") == "Won",
      f"GET: the field trigger with its option name ({rv[R4]['trigger']}, {rv[R4]['names']})")
check(rv[R7]["trigger"].get("value") == "0" and rv[R5]["action"] == {"kind": "field", "field_id": HRS["id"], "value": "8"},
      f"GET: unchecked = '0', the action keeps its value ({rv[R7]['trigger']}, {rv[R5]['action']})")
t3 = task(A, L3, "Deal")
Bo.patch(B + f"/api/tasks/{t3}", json={"fields": {str(ST["id"]): OPT["Lead"]}})
check(get(A, t3).get("priority") == 0, "Stage = Lead: the 'Won' rule does not run")
Bo.patch(B + f"/api/tasks/{t3}", json={"fields": {str(ST["id"]): OPT["Won"]}})
check(get(A, t3).get("priority") == 5, "Stage = Won -> priority high")
Bo.patch(B + f"/api/tasks/{t3}", json={"fields": {str(OK["id"]): True}})
x = get(A, t3)
check((x.get("fields") or {}).get(str(HRS["id"])) == "8", f"checked -> Hours set to 8 by the rule ({x.get('fields')})")
check(not comments(A, t3, "Hours changed") and not comments(A, t3, "Hours"),
      "depth 0: the value the rule set does not start the 'Hours changed' rule")
Bo.patch(B + f"/api/tasks/{t3}", json={"fields": {str(HRS["id"]): "3"}})
check(len(comments(A, t3, "Hours")) == 1, "a person changes Hours -> the field rule runs once")
Bo.patch(B + f"/api/tasks/{t3}", json={"title": "Deal 2"})
check(len(comments(A, t3, "Hours")) == 1, "another change: the field rule does not run")
Bo.patch(B + f"/api/tasks/{t3}", json={"fields": {str(OK["id"]): None}})
check(get(A, t3).get("priority") == 1, "unchecked -> priority low")
t3b = task(A, L3, "Signed at once", fields={str(OK["id"]): True})
check((get(A, t3b).get("fields") or {}).get(str(HRS["id"])) == "8", "created with the box checked: the field rule runs")

# switching a rule off and on again re-checks the stored trigger / action (round trip of GET -> PATCH)
check(A.patch(B + f"/api/rules/{R5}", json={"active": False}).ok and A.patch(B + f"/api/rules/{R5}", json={"active": True}).ok,
      "a field rule can be switched off and on again")

# ---- deleted field / tag -> paused
check(A.delete(B + f"/api/fields/{HRS['id']}").ok, "the field Hours is deleted")
rv = rules(A, L3)
check(not rv[R5]["active"] and rv[R5]["paused_reason"] == "field" and rv[R6]["paused_reason"] == "field",
      f"rules using the deleted field pause: field ({rv[R5]['paused_reason']}, {rv[R6]['paused_reason']})")
check(A.delete(B + f"/api/list-tags/{HOT}").ok, "the tag hot is deleted")
rv2 = rules(A, L2)
check(rv2[R2]["paused_reason"] == "tag" and rv2[R3]["active"], f"the tag rule pauses: tag ({rv2[R2]['paused_reason']})")

# ---- agents: read + propose the new kinds; OpenAPI
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "robo", "display_name": "Robo"})
assert r.ok, r.text
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": ORG})
A.put(B + f"/api/lists/{L3}/members", json={"user_id": AG, "role": "edit"})
g = requests.get(V + f"/lists/{L3}/rules", headers=AGH)
check(g.ok and {r["trigger"]["kind"] for r in g.json()["data"]} >= {"field"}, f"agent reads field rules ({g.status_code})")
pp = requests.post(V + f"/lists/{L3}/rules/proposals", headers=AGH, json={"name": "Agent stage", "summary": "Saves time",
                   "trigger": {"kind": "created"}, "action": {"kind": "field", "field_id": ST["id"], "value": OPT["Lead"]}})
check(pp.status_code == 201, f"agent proposes a created -> field rule ({pp.status_code} {pp.text[:200]})")
if pp.ok:
    v = A.get(B + f"/api/proposals/{pp.json()['id']}").json()
    check((v.get("rule_view") or {}).get("names", {}).get("value_to") == "Lead", f"the card names the value ({v.get('rule_view')})")
    ac = A.post(B + f"/api/proposals/{pp.json()['id']}/apply", json={"select": ["0"]})
    check(ac.ok, f"alice accepts ({ac.status_code})")
    t4 = task(A, L3, "From the agent's rule")
    check((get(A, t4).get("fields") or {}).get(str(ST["id"])) == OPT["Lead"], "the accepted rule sets Stage = Lead on new tasks")
pa = requests.post(V + f"/lists/{L3}/rules/proposals", headers=AGH, json={"name": "a", "trigger": {"kind": "assigned", "user_id": OUT},
                   "action": {"kind": "priority", "priority": "medium"}})
check(pa.status_code == 400, f"agent: assigned to someone outside the list -> 400 ({pa.status_code})")
sch = requests.get(V + "/openapi.json").json()["components"]["schemas"]["ListRule"]["properties"]
check(set(sch["trigger"]["properties"]["kind"]["enum"]) >= {"created", "assigned", "field"}
      and set(sch["action"]["properties"]["kind"]["enum"]) >= {"priority", "tag", "field"}
      and sch["action"]["properties"]["priority"]["enum"] == ["none", "low", "medium", "high"], "OpenAPI: every new enum value")

# ---- a person without an organisation: private list with the new rules (freelancer-matrix: lists)
FID, Fr = freelancer(B, A, "frida")
FL = Fr.post(B + "/api/lists", json={"name": "Gigs", "org_id": None}).json()["id"]
FB = field(Fr, FL, "Paid", "checkbox")
FT = Fr.post(B + f"/api/lists/{FL}/tags", json={"name": "done-paid"}).json()["id"]
rule(Fr, FL, "Prio", {"kind": "created"}, {"kind": "priority", "priority": "medium"})
rule(Fr, FL, "Paid", {"kind": "field", "field_id": FB["id"], "value": "1"}, {"kind": "tag", "tag_id": FT})
ft = task(Fr, FL, "Logo")
check(get(Fr, ft).get("priority") == 3, "freelancer: created -> priority medium")
Fr.patch(B + f"/api/tasks/{ft}", json={"fields": {str(FB["id"]): True}})
check("done-paid" in ltags(Fr, ft), f"freelancer: checked -> list tag ({ltags(Fr, ft)})")
check(A.get(B + f"/api/lists/{FL}/rules").status_code == 404, "someone else cannot see the freelancer's rules")

print(f"p2114_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
