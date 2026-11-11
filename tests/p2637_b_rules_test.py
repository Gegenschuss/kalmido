#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.637.0 B (#4768): rules of a list -- the due trigger with a distance, up to five actions, conditions "only when".
Invented names only.
 - due trigger "3 days before": a task due in 3 days gets the rule's comment once (a second tick adds none); a run marker of
   the same due day = nothing again, a marker of an earlier due day (the date was moved) = it runs again
 - due trigger "overdue for 2 days": a task due 2 days ago gets it, one due yesterday does not
 - a chain of 3 actions (priority, tag, comment) runs in order on one trigger; 6 actions, a move into another list that is
   not the last action, bad conditions / distance -> 400
 - conditions: priority / person / tag / column all must hold (one does not hold -> nothing happens), all hold -> it runs
 - a missing right at action 2 (the creator has no write access to the move's target list any more): the whole rule pauses
   (target), action 1 left nothing behind; while the right was there the chain ran (counter-check)
 - an old rule (a row with act / act_val only, as an older version wrote it) runs unchanged and reads as a chain of one
 - agents propose a rule with actions + conditions (the card names them, accepting stores them)
 - a person without an organisation (freelancer-matrix: lists): a chain with a condition in a private list
usage: p2637_b_rules_test.py <datadir>      (KMT_NOSTART=1 / P2637B_NOSTART=1: a running server)"""
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from freelancer_fixture import freelancer
from kt import B, CT, H, check, dbx, done, fresh, sess, until

V = B + "/api/v1"
TODAY = datetime.now(ZoneInfo("Europe/Berlin")).date()  # the test server's time zone (start.sh)
fresh(prefix="P2637B")
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
BOB, CAROL = uid["bob"], uid["carol"]
Ca = sess("carol")


def mklist(s, name, org=ORG):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org})
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


def rule(s, lid, name, trig, code=201, **body):
    r = s.post(B + f"/api/lists/{lid}/rules", json={"name": name, "trigger": trig, **body})
    check(r.status_code == code, f"rule {name}: {code} (got {r.status_code} {r.text[:200]})")
    return r.json().get("id") if r.ok else None


def rule_of(s, lid, rid):
    return next((x for x in s.get(B + f"/api/lists/{lid}/rules").json()["rules"] if x["id"] == rid), None)


def comments(tid, name):
    # 2.972.0 (#5272): the comments' core, the rule's name in extra
    return [x[0] for x in dbx("SELECT body FROM obj_comments WHERE kind='task' AND ref_id=? AND extra->>'rule_name'=? ORDER BY id", (tid, name))]


def day(n):
    return (TODAY + timedelta(days=n)).isoformat()


W = mklist(A, "Work")
W2 = mklist(A, "Archive")
for who, role in ((BOB, "edit"), (CAROL, "admin")):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": role}).ok, f"setup: member {who} {role}")
for who in (CAROL, BOB):  # everyone who sees Work sees Archive too: carol's rule may move tasks there (tasks.py can_move)
    check(A.put(B + f"/api/lists/{W2}/members", json={"user_id": who, "role": "edit"}).ok, f"setup: {who} may write in Archive")
TODO, REVIEW = section(A, W, "To do"), section(A, W, "Review")
OLD = section(A, W2, "Old")
TAG = A.post(B + f"/api/lists/{W}/tags", json={"name": "urgent"}).json()["id"]

# ---------------------------------------------------------------- invalid input
C1 = {"kind": "comment", "text": "x"}
rule(A, W, "six", {"kind": "done"}, 400, actions=[C1] * 6)
rule(A, W, "none", {"kind": "done"}, 400, actions=[])
rule(A, W, "both", {"kind": "done"}, 400, action=C1, actions=[C1])
rule(A, W, "move first", {"kind": "done"}, 400, actions=[{"kind": "move", "list_id": W2}, C1])
rule(A, W, "far", {"kind": "due", "when": "before", "days": 31}, 400, action=C1)
rule(A, W, "when", {"kind": "due", "when": "later", "days": 1}, 400, action=C1)
rule(A, W, "cond prio", {"kind": "done"}, 400, action=C1, conditions={"priority": "huge"})
rule(A, W, "cond tag", {"kind": "done"}, 400, action=C1, conditions={"tag_id": 999999})
rule(A, W, "cond section", {"kind": "done"}, 400, action=C1, conditions={"section_id": OLD})
rule(A, W, "cond key", {"kind": "done"}, 400, action=C1, conditions={"colour": "red"})
check(A.get(B + f"/api/lists/{W}/rules").json()["rules"] == [], "nothing stored from the bad input")

# ---------------------------------------------------------------- a chain of three actions
R_CH = rule(A, W, "Chain", {"kind": "done"}, actions=[{"kind": "priority", "priority": "high"}, {"kind": "tag", "tag_id": TAG},
                                                      {"kind": "comment", "text": "Chain done"}])
rv = rule_of(A, W, R_CH)
check(rv and len(rv["actions"]) == 3 and rv["action"]["kind"] == "priority" and rv["names"]["acts"][1].get("tag_to") == "urgent"
      and rv["conditions"] == {}, f"the rule reads as a chain of three {rv}")
row = dbx("SELECT act, more_acts, conds FROM list_rules WHERE id=?", (R_CH,))[0]
check(row[0] == "priority" and '"tag"' in row[1] and '"comment"' in row[1] and row[2] == "",
      f"stored: the first action in act, the others in more_acts {row}")
t1 = task(A, W, "Ship")
check(A.post(B + f"/api/tasks/{t1}/complete", json={}).ok, "the task is completed")
check(dbx("SELECT priority FROM tasks WHERE id=?", (t1,))[0][0] == 5, "action 1: priority high")
check(dbx("SELECT 1 FROM obj_tag_links WHERE kind='task' AND obj_id=? AND tag_id=?", (t1, TAG)), "action 2: the tag")  # 2.947.0 (#5275): the core's tags (obj_tags / obj_tag_links)
check(comments(t1, "Chain") == ["Chain done"], f"action 3: the comment {comments(t1, 'Chain')}")
check(A.patch(B + f"/api/rules/{R_CH}", json={"active": False}).ok, "the chain is switched off")

# ---------------------------------------------------------------- conditions (all must hold)
R_NO = rule(A, W, "Cond no", {"kind": "done"}, action={"kind": "comment", "text": "no"},
            conditions={"priority": "urgent", "user_id": BOB, "tag_id": TAG, "section_id": REVIEW})
R_YES = rule(A, W, "Cond yes", {"kind": "done"}, action={"kind": "comment", "text": "yes"},
             conditions={"priority": "high", "user_id": BOB, "tag_id": TAG, "section_id": REVIEW})
cv = rule_of(A, W, R_YES)
check(cv["conditions"] == {"priority": "high", "user_id": BOB, "tag_id": TAG, "section_id": REVIEW}
      and cv["names"]["cond"] == {"user": "Bob", "tag": "urgent", "section": "Review"}, f"the conditions with names {cv}")
t2 = task(A, W, "Check", section_id=REVIEW, assignee_id=BOB, priority=5)
check(A.patch(B + f"/api/tasks/{t2}", json={"ltags": ["urgent"]}).ok, "the task gets the tag")
t3 = task(A, W, "Check other column", section_id=TODO, assignee_id=BOB, priority=5)
A.patch(B + f"/api/tasks/{t3}", json={"ltags": ["urgent"]})
for t in (t2, t3):
    A.post(B + f"/api/tasks/{t}/complete", json={})
check(comments(t2, "Cond yes") == ["yes"], "all conditions hold -> the rule runs")
check(comments(t2, "Cond no") == [], "the priority does not hold -> nothing")
check(comments(t3, "Cond yes") == [], "the column does not hold -> nothing")
check(A.patch(B + f"/api/rules/{R_YES}", json={"conditions": None}).ok and rule_of(A, W, R_YES)["conditions"] == {},
      "the conditions can be cleared")
for r_ in (R_NO, R_YES):
    A.patch(B + f"/api/rules/{r_}", json={"active": False})

# ---------------------------------------------------------------- a missing right at action 2 pauses the whole rule
R_MV = rule(Ca, W, "Hand over", {"kind": "done"}, actions=[{"kind": "comment", "text": "Handed over"},
                                                           {"kind": "move", "list_id": W2, "section_id": OLD}])
t4 = task(A, W, "First")
A.post(B + f"/api/tasks/{t4}/complete", json={})
x = dbx("SELECT list_id, section_id FROM tasks WHERE id=?", (t4,))[0]
check(tuple(x) == (W2, OLD) and comments(t4, "Hand over") == ["Handed over"], f"while carol may write in Archive the chain runs {x}")
check(A.put(B + f"/api/lists/{W2}/members", json={"user_id": CAROL, "role": "view"}).ok, "carol may only view Archive now")
t5 = task(A, W, "Second")
A.post(B + f"/api/tasks/{t5}/complete", json={})
r5 = rule_of(A, W, R_MV)
check(r5 and not r5["active"] and r5["paused_reason"] == "target", f"the rule paused: target ({r5 and r5['paused_reason']})")
check(comments(t5, "Hand over") == [] and dbx("SELECT list_id FROM tasks WHERE id=?", (t5,))[0][0] == W,
      "action 1 left nothing behind, the task stays")

# ---------------------------------------------------------------- an old rule (act / act_val only) runs unchanged
OLDR = dbx("""INSERT INTO list_rules(list_id,org_id,name,trig,trig_val,act,act_val,active,paused_reason,created_by,created_at,updated_at)
              VALUES(?,?,'Old style','reopen','','comment','{"text":"Opened again"}',1,'',?,?,?) RETURNING id""",
           (W, ORG, ALICE, "2026-11-01T10:00:00Z", "2026-11-01T10:00:00Z"))[0][0]
ov = rule_of(A, W, OLDR)
check(ov and [a["kind"] for a in ov["actions"]] == ["comment"] and ov["conditions"] == {}, f"an old rule reads as a chain of one {ov}")
A.post(B + f"/api/tasks/{t1}/reopen", json={})
check(comments(t1, "Old style") == ["Opened again"], "the old rule runs unchanged")
r1 = A.post(B + f"/api/lists/{W}/rules", json={"name": "Single", "trigger": {"kind": "done"}, "action": {"kind": "due", "days": 1}})
check(r1.status_code == 201 and tuple(dbx("SELECT more_acts, conds FROM list_rules WHERE id=?", (r1.json()["id"],))[0]) == ("", ""),
      "a single action (the old body) stores no chain and no conditions")
A.patch(B + f"/api/rules/{r1.json()['id']}", json={"active": False})
A.patch(B + f"/api/rules/{OLDR}", json={"active": False})

# ---------------------------------------------------------------- the due trigger with a distance (watchdog)
R_B3 = rule(A, W, "Soon", {"kind": "due", "when": "before", "days": 3}, action={"kind": "comment", "text": "Due in 3 days"})
R_O2 = rule(A, W, "Late", {"kind": "due", "when": "overdue", "days": 2}, action={"kind": "comment", "text": "Overdue 2 days"})
bv = rule_of(A, W, R_B3)
check(bv["trigger"] == {"kind": "due", "when": "before", "days": 3}, f"the trigger reads back {bv['trigger']}")
check(dbx("SELECT trig_val FROM list_rules WHERE id=?", (R_O2,))[0][0] == "o2", "overdue for 2 days stored as o2")
same = task(A, W, "Ran for this due day")      # a marker of the same due day: nothing again
moved = task(A, W, "Date was moved")            # a marker of an earlier due day: runs again
for tid, d in ((same, day(3)), (moved, day(1))):
    dbx("INSERT INTO list_rule_runs(rule_id,task_id,key,at) VALUES(?,?,?,?)", (R_B3, tid, f"due:{d}:b3", "2026-11-01T10:00:00Z"))
t_b3 = task(A, W, "Pay in 3 days", due=day(3))
t_o1 = task(A, W, "Overdue 1 day", due=day(-1))
t_o2 = task(A, W, "Overdue 2 days", due=day(-2))
for tid in (same, moved):
    check(A.patch(B + f"/api/tasks/{tid}", json={"due": day(3)}).ok, f"task {tid} due in 3 days")
check(until(lambda: comments(t_b3, "Soon") and comments(moved, "Soon") and comments(t_o2, "Late"), timeout=90),
      "the watchdog ran the due rules")
check(comments(t_b3, "Soon") == ["Due in 3 days"], "3 days before: one comment")
check(comments(moved, "Soon") == ["Due in 3 days"], "a moved due date runs again")
check(comments(same, "Soon") == [], "the same due day does not run twice")
check(comments(t_o2, "Late") == ["Overdue 2 days"], "overdue for 2 days: the rule runs")
check(comments(t_o1, "Late") == [] and comments(t_o1, "Soon") == [], "overdue for 1 day: no rule")
again = task(A, W, "Next tick", due=day(3))   # a later tick: the earlier tasks get nothing more
check(until(lambda: comments(again, "Soon"), timeout=90), "a later tick runs for the new task")
check(len(comments(t_b3, "Soon")) == 1, "3 days before: still once")
check(dbx("SELECT key FROM list_rule_runs WHERE rule_id=? AND task_id=?", (R_B3, t_b3))[0][0] == f"due:{day(3)}:b3",
      "the marker holds the due day and the distance")

# ---------------------------------------------------------------- agents propose a chain with conditions
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "robo", "display_name": "Robo"})
assert r.ok, r.text
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": ORG})
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: robo in Work")
pp = requests.post(V + f"/lists/{W}/rules/proposals", headers=AGH, json={
    "name": "Agent chain", "summary": "Saves time", "trigger": {"kind": "due", "when": "overdue", "days": 1},
    "actions": [{"kind": "priority", "priority": "urgent"}, {"kind": "comment", "text": "Late"}], "conditions": {"tag_id": TAG}})
check(pp.status_code == 201, f"the agent proposes a chain ({pp.status_code} {pp.text[:200]})")
check(requests.post(V + f"/lists/{W}/rules/proposals", headers=AGH, json={"name": "x", "trigger": {"kind": "done"},
                    "actions": [C1] * 6}).status_code == 400, "a proposal with six actions: 400")
jid = pp.json()["id"]
card = A.get(B + f"/api/proposals/{jid}").json().get("rule_view") or {}
check(len(card.get("actions") or []) == 2 and card.get("conditions") == {"tag_id": TAG} and card["trigger"].get("when") == "overdue",
      f"the card shows the chain and the condition {card}")
ap = A.post(B + f"/api/proposals/{jid}/apply", json={"select": ["0"]})
check(ap.ok and ap.json().get("rule_id"), f"alice accepts ({ap.status_code} {ap.text[:200]})")
ar = rule_of(A, W, ap.json().get("rule_id"))
check(ar and len(ar["actions"]) == 2 and ar["conditions"] == {"tag_id": TAG} and ar["created_by"] == ALICE,
      f"the accepted rule keeps the chain and the condition {ar}")
spec = requests.get(V + "/openapi.json").json()["components"]["schemas"]["ListRule"]["properties"]
check("actions" in spec and "conditions" in spec and spec["trigger"]["properties"]["when"]["enum"] == ["before", "overdue"],
      "OpenAPI names actions, conditions and the distance")

# ---------------------------------------------------------------- a person without an organisation
FID, F = freelancer(B, A)
FL = F.post(B + "/api/lists", json={"name": "Freelance"}).json()["id"]
FS = F.post(B + "/api/sections", json={"list_id": FL, "name": "Doing"}).json()["id"]
fr = F.post(B + f"/api/lists/{FL}/rules", json={"name": "Mine", "trigger": {"kind": "done"}, "conditions": {"priority": "high"},
                                                 "actions": [{"kind": "move", "section_id": FS}, {"kind": "comment", "text": "Filed"}]})
check(fr.status_code == 201, f"freelancer: a chain with a condition ({fr.status_code} {fr.text[:200]})")
fa = F.post(B + "/api/tasks", json={"title": "Gig", "list_id": FL, "priority": 5}).json()["id"]
fb = F.post(B + "/api/tasks", json={"title": "Low gig", "list_id": FL, "priority": 1}).json()["id"]
for t in (fa, fb):
    F.post(B + f"/api/tasks/{t}/complete", json={})
check(dbx("SELECT section_id FROM tasks WHERE id=?", (fa,))[0][0] == FS and comments(fa, "Mine") == ["Filed"],
      "freelancer: the chain runs when the condition holds")
check(dbx("SELECT section_id FROM tasks WHERE id=?", (fb,))[0][0] != FS and comments(fb, "Mine") == [],
      "freelancer: nothing when it does not")
# 2.637.0 (#4768, review): the import keeps "a move into another project only as the last action" (rules.py rul_clean);
# a hand-built file with the move in the middle is left out, the same move as the last action comes along
_imp = r"""import json, app
from kalmido.admin import oi_team as o
class C:
    def execute(self, *a):
        return self
    def fetchone(self):
        return (0,)
class Run:
    warned = []
    def m(self, table, v):
        return {"lists": {"7": 70}, "sections": {}}.get(table, {}).get(str(v)) if v else None
    def warning(self, *a):
        self.warned.append(a[0])
def go(more):
    src = {"name": "R", "trig": "done", "trig_val": "", "act": "comment", "act_val": json.dumps({"text": "x"}),
           "more_acts": json.dumps(more)}
    d = o.rule_ids(C(), Run(), lambda v: None, {}, src, {"list_id": 5})
    return None if d is None else d["target_list_id"]
print(json.dumps([go([{"kind": "move", "list_id": 7}, {"kind": "priority", "priority": "high"}]),
                  go([{"kind": "priority", "priority": "high"}, {"kind": "move", "list_id": 7}])]))
"""
_out = subprocess.run(["docker", "exec", CT, "python", "-c", _imp], capture_output=True, text=True)
check(_out.stdout.strip().splitlines()[-1:] == ["[null, 70]"],
      f"import: a move into another project in the middle of the chain is left out, as the last one it comes along ({_out.stdout[-200:]} {_out.stderr[-300:]})")
sys.exit(done("p2637_b_rules"))
