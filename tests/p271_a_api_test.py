#!/usr/bin/env python3
"""2.71.0 API tests, part A (#1457): rules of a list ("When ... then ..."). Invented names only.
 - only the owner / a list admin manages rules (an edit member, a viewer 403; someone outside 404); agents never (403 / no
   route), they read (GET /api/v1/lists/{id}/rules, a list not shared with them 404) and propose (kind rule): the person
   accepts (the rule belongs to them) or declines; undo / redo of the accepted proposal
 - triggers: column, completed, opened again, list tag, due date reached (watchdog); actions: assign, due date, comment,
   move (into another list + column)
 - the rule runs with the rights of its creator (a change by someone else -> history "rule", user = the creator); the
   creator loses the admin role -> the rule pauses, nothing happens
 - targets: another workspace / private / without write access / a non-member to assign -> 400; health list -> no rules
 - loop protection depth 0: two rules A -> B and B -> A move a task once; too long texts 400; at most 50 rules per list
 - delete + restore (the client's undo); a person without an organisation (freelancer) has rules in their own list
tenant-matrix: list
usage: p271_a_api_test.py <datadir>      (a fresh container; P271A_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
TODAY = datetime.now(ZoneInfo("Europe/Berlin")).date()  # the test server's time zone (start.sh)


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


if not os.environ.get("P271A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/users", json={"orgs": [], "username": "erin", "display_name": "Erin", "password": "password123", "email": "erin@example.com"})
assert r.ok, r.text
ERIN = r.json()["id"]
BOB, CAROL, DAVE = uid["bob"], uid["carol"], uid["dave"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")


def mklist(s, name, org=ORG):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org})  # None = private
    assert r.ok, r.text
    return r.json()["id"]


def section(s, lid, name):
    r = s.post(B + "/api/sections", json={"list_id": lid, "name": name})
    assert r.ok, r.text
    return r.json()["id"]


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


def acts(s, tid):
    return s.get(B + f"/api/tasks/{tid}/timeline").json()


W = mklist(A, "Work")
PR = mklist(A, "Probe", org=None)
check([x for x in A.get(B + "/api/state").json()["lists"] if x["id"] == PR][0].get("org_id") is None, "setup: a private list")
W2 = mklist(A, "Archive")
P = mklist(A, "Private", org=None)
for who, role in ((BOB, "edit"), (CAROL, "admin"), (DAVE, "view")):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": role}).ok, f"setup: member {who} {role}")
A.put(B + f"/api/lists/{W2}/members", json={"user_id": BOB, "role": "edit"})
TODO, REVIEW, DONE = section(A, W, "To do"), section(A, W, "Review"), section(A, W, "Done")
ARCH = section(A, W2, "Old")
TAG = A.post(B + f"/api/lists/{W}/tags", json={"name": "urgent"}).json()["id"]

# ---- who may manage rules
check(Bo.post(B + f"/api/lists/{W}/rules", json={"name": "x", "trigger": {"kind": "done"}, "action": {"kind": "due", "days": 1}}).status_code == 403,
      "an edit member cannot add a rule (403)")
check(Da.get(B + f"/api/lists/{W}/rules").status_code == 403, "a viewer does not see the rules (403)")
check(Er.get(B + f"/api/lists/{W}/rules").status_code == 404, "someone outside the list: 404")
check(A.get(B + f"/api/lists/{W}/rules").json()["rules"] == [], "no rules yet")

# ---- invalid targets / values
rule(A, W, "other ws", {"kind": "done"}, {"kind": "move", "list_id": P}, 400)
rule(A, W, "bad section", {"kind": "section", "section_id": ARCH}, {"kind": "due", "days": 0}, 400)
rule(A, W, "bad move section", {"kind": "done"}, {"kind": "move", "section_id": ARCH}, 400)
rule(A, W, "stranger", {"kind": "done"}, {"kind": "assign", "user_id": ERIN}, 400)
rule(A, W, "long", {"kind": "done"}, {"kind": "comment", "text": "x" * 2001}, 400)
rule(A, W, "days", {"kind": "done"}, {"kind": "due", "days": 999}, 400)
rule(A, W, "kind", {"kind": "nope"}, {"kind": "due", "days": 1}, 400)
C = mklist(Ca, "Carols")
Ca.put(B + f"/api/lists/{C}/members", json={"user_id": ALICE, "role": "view"})
rule(A, W, "no write", {"kind": "done"}, {"kind": "move", "list_id": C}, 400)
HL = A.post(B + "/api/lists", json={"name": "Health", "life": "health"})
if HL.ok and HL.json().get("life") == "health":
    check(A.post(B + f"/api/lists/{HL.json()['id']}/rules", json={"name": "h", "trigger": {"kind": "done"},
                                                                     "action": {"kind": "due", "days": 1}}).status_code in (403, 404, 409),
          "a health list has no rules")

# ---- trigger column -> assign (a change by bob runs with alice's rights)
R1 = rule(A, W, "Review", {"kind": "section", "section_id": REVIEW}, {"kind": "assign", "user_id": CAROL})
t1 = task(A, W, "Draft", section_id=TODO)
check(Bo.patch(B + f"/api/tasks/{t1}", json={"section_id": REVIEW}).ok, "bob moves the task into Review")
check(get(A, t1).get("assignee_id") == CAROL, "rule column -> assigned to carol")
tl = acts(A, t1)
ra = [a for a in tl["activity"] if a["kind"] == "assign" and (a["data"].get("rule") or {}).get("id") == R1]
check(ra and ra[0]["user_id"] == ALICE and ra[0]["data"]["rule"]["name"] == "Review",
      f"history: the assignment is 'Rule Review', run as alice ({[(a['kind'], a['user_id'], a['data']) for a in tl['activity']]})")
t1b = task(Bo, W, "Born in review", section_id=REVIEW)
check(get(A, t1b).get("assignee_id") == CAROL, "a task created right in the column triggers the rule")

# ---- trigger done -> comment; reopen -> due date
R2 = rule(A, W, "Thanks", {"kind": "done"}, {"kind": "comment", "text": "Please write the invoice"})
R3 = rule(A, W, "Again", {"kind": "reopen"}, {"kind": "due", "days": 2})
t2 = task(A, W, "Deliver")
check(Bo.post(B + f"/api/tasks/{t2}/complete", json={}).ok, "bob completes")
cm = [c for c in acts(A, t2)["comments"] if c.get("rule_name") == "Thanks"]
check(cm and cm[0]["body"] == "Please write the invoice" and cm[0]["user_id"] == ALICE, "rule done -> comment by alice marked 'Thanks'")
ro = Bo.post(B + f"/api/tasks/{t2}/reopen")
check(ro.ok, f"bob opens it again ({ro.status_code} {ro.text[:300]})")
check(get(A, t2).get("due") == (TODAY + timedelta(days=2)).isoformat(), f"rule reopen -> due in 2 days ({get(A, t2).get('due')})")

# ---- trigger list tag -> move into another list + column
R4 = rule(A, W, "Park", {"kind": "ltag", "tag_id": TAG}, {"kind": "move", "list_id": W2, "section_id": ARCH})
t3 = task(A, W, "Old idea")
check(Bo.patch(B + f"/api/tasks/{t3}", json={"ltags": ["urgent"]}).ok, "bob tags it")
x = get(A, t3)
check(x.get("list_id") == W2 and x.get("section_id") == ARCH, f"rule tag -> moved to Archive / Old ({x.get('list_id')}, {x.get('section_id')})")

# ---- loop protection: W column Done -> W2 column Old, W2 column Old -> W column Done
R5 = rule(A, W, "Out", {"kind": "section", "section_id": DONE}, {"kind": "move", "list_id": W2, "section_id": ARCH})
R6 = rule(A, W2, "Back", {"kind": "section", "section_id": ARCH}, {"kind": "move", "list_id": W, "section_id": DONE})
t4 = task(A, W, "Ping")
check(A.patch(B + f"/api/tasks/{t4}", json={"section_id": DONE}).ok, "into Done")
x = get(A, t4)
check(x.get("list_id") == W2 and x.get("section_id") == ARCH, "depth 0: moved once, the rule of the target list did not run")
A.patch(B + f"/api/rules/{R6}", json={"active": False})

# ---- due date reached (watchdog, once per task and day)
R7 = rule(A, W, "Due", {"kind": "due"}, {"kind": "comment", "text": "Due today"})
t5 = task(A, W, "Pay", due=TODAY.isoformat())
for _ in range(20):
    if [c for c in acts(A, t5)["comments"] if c.get("rule_name") == "Due"]:
        break
    time.sleep(1)
n = len([c for c in acts(A, t5)["comments"] if c.get("rule_name") == "Due"])
check(n == 1, f"rule due date reached -> one comment ({n})")
time.sleep(3)
check(len([c for c in acts(A, t5)["comments"] if c.get("rule_name") == "Due"]) == 1, "due date: only once per day")
A.patch(B + f"/api/rules/{R7}", json={"active": False})

# ---- the creator loses the admin role: the rule pauses, nothing happens
R8 = rule(Ca, W, "Carol", {"kind": "section", "section_id": TODO}, {"kind": "assign", "user_id": DAVE})
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": CAROL, "role": "edit"}).ok, "carol is only edit now")
t6 = task(A, W, "Watch")
Bo.patch(B + f"/api/tasks/{t6}", json={"section_id": TODO})
check(get(A, t6).get("assignee_id") is None, "a rule of a creator without the role does nothing")
r8 = [r for r in A.get(B + f"/api/lists/{W}/rules").json()["rules"] if r["id"] == R8][0]
check(not r8["active"] and r8["paused_reason"] == "role", f"the rule paused: role ({r8['paused_reason']})")
check(A.patch(B + f"/api/rules/{R8}", json={"active": True}).ok, "alice switches it on again")
r8 = [r for r in A.get(B + f"/api/lists/{W}/rules").json()["rules"] if r["id"] == R8][0]
check(r8["active"] and r8["created_by"] == ALICE and not r8["paused_reason"], "switched on again it runs with alice's rights")

# ---- delete + restore (undo)
check(A.delete(B + f"/api/rules/{R2}").ok, "delete a rule")
check(R2 not in [r["id"] for r in A.get(B + f"/api/lists/{W}/rules").json()["rules"]], "deleted rule gone")
check(Bo.post(B + f"/api/rules/{R2}/restore").status_code == 403, "bob cannot restore it")
check(A.post(B + f"/api/rules/{R2}/restore").ok, "restore = undo")
check(R2 in [r["id"] for r in A.get(B + f"/api/lists/{W}/rules").json()["rules"]], "restored")
check(Bo.patch(B + f"/api/rules/{R2}", json={"name": "x"}).status_code == 403, "bob cannot change a rule")
check(Er.delete(B + f"/api/rules/{R2}").status_code == 404, "someone outside: 404")

# ---- at most 50 rules per list
L50 = mklist(A, "Many")
for i in range(50):
    A.post(B + f"/api/lists/{L50}/rules", json={"name": f"r{i}", "trigger": {"kind": "done"}, "action": {"kind": "due", "days": 1}})
rule(A, L50, "one too many", {"kind": "done"}, {"kind": "due", "days": 1}, 400)

# ---- agents: read, propose, never create
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "robo", "display_name": "Robo"})
assert r.ok, r.text
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": ORG})
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: robo in Work")
g = requests.get(V + f"/lists/{W}/rules", headers=AGH)
check(g.ok and {R1, R4} <= {x["id"] for x in g.json()["data"]}, f"agent reads the rules ({g.status_code})")
check(requests.get(V + f"/lists/{W2}/rules", headers=AGH).status_code == 404, "agent: a list not shared with it -> 404")
check(requests.post(B + f"/api/lists/{W}/rules", headers=AGH, json={"name": "a", "trigger": {"kind": "done"},
                                                                     "action": {"kind": "due", "days": 1}}).status_code in (401, 403),
      "agent cannot create a rule directly")
pp = requests.post(V + f"/lists/{W}/rules/proposals", headers=AGH, json={"name": "Agent rule", "summary": "Saves time",
                   "trigger": {"kind": "done"}, "action": {"kind": "due", "days": 0}})
check(pp.status_code == 201 and pp.json().get("kind") in (None, "rule"), f"agent proposes a rule ({pp.status_code} {pp.text[:200]})")
bad = requests.post(V + f"/lists/{W}/rules/proposals", headers=AGH, json={"name": "x", "trigger": {"kind": "done"},
                    "action": {"kind": "move", "list_id": W2}})
check(bad.status_code in (400, 404), f"agent cannot propose a move into a list it does not see ({bad.status_code})")
check(requests.post(V + f"/lists/{W}/rules/proposals", headers=AGH, json={"name": "x", "user_id": BOB, "trigger": {"kind": "done"},
                    "action": {"kind": "due", "days": 0}}).status_code == 400, "proposal for an edit member: 400")
jid = pp.json()["id"]
check(Bo.post(B + f"/api/proposals/{jid}/apply", json={"select": ["0"]}).status_code == 404, "bob cannot accept alice's card")
v = A.get(B + f"/api/proposals/{jid}")
check(v.ok and (v.json().get("rule_view") or {}).get("name") == "Agent rule", f"the card shows the rule ({v.status_code})")
ap = A.post(B + f"/api/proposals/{jid}/apply", json={"select": ["0"]})
check(ap.ok and ap.json().get("rule_id"), f"alice accepts ({ap.status_code} {ap.text[:200]})")
RA = ap.json().get("rule_id")
ra = [r for r in A.get(B + f"/api/lists/{W}/rules").json()["rules"] if r["id"] == RA]
check(ra and ra[0]["created_by"] == ALICE, "the accepted rule belongs to alice, not the agent")
check(A.post(B + f"/api/proposals/{jid}/undo").ok and RA not in [r["id"] for r in A.get(B + f"/api/lists/{W}/rules").json()["rules"]],
      "undo removes the accepted rule")
check(A.post(B + f"/api/proposals/{jid}/redo").ok and RA in [r["id"] for r in A.get(B + f"/api/lists/{W}/rules").json()["rules"]],
      "redo brings it back")
p2 = requests.post(V + f"/lists/{W}/rules/proposals", headers=AGH, json={"name": "Second", "trigger": {"kind": "reopen"},
                   "action": {"kind": "comment", "text": "Hi"}})
check(p2.status_code == 201 and A.post(B + f"/api/proposals/{p2.json()['id']}/discard").ok, "alice declines a proposal")
spec = requests.get(V + "/openapi.json").json()["paths"]
check("/lists/{id}/rules" in spec and spec["/lists/{id}/rules/proposals"]["post"]["x-kalmido-scope"] == "structure", "OpenAPI lists the routes")

# ---- a person without an organisation (freelancer): own list = owner
F = mklist(Er, "Freelance", org=None)
FS = section(Er, F, "Doing")
rule(Er, F, "Mine", {"kind": "section", "section_id": FS}, {"kind": "due", "days": 0})
ft = task(Er, F, "Gig")
Er.patch(B + f"/api/tasks/{ft}", json={"section_id": FS})
check(get(Er, ft).get("due") == TODAY.isoformat(), "freelancer: the rule of the own list runs")
check(A.get(B + f"/api/lists/{F}/rules").status_code == 404, "another organisation's person cannot see a private list's rules")

print(f"p271_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
