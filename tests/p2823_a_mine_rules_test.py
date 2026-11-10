#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.823.0 (#4773) API tests, own container (kt.fresh): the person's own rules of "My tasks" (/api/mine-rules,
kalmido/tasks/minerules.py).
 - the first opening of the sections makes the first rule "due today or overdue -> Now" (default, switched off / deleted
   like any other, a deleted one never comes back by itself; an older account gets it at its next run, hand wins)
 - apply: due today / overdue into Now at the top; the task, its project and the project's order stay untouched
 - hand wins: a task moved by hand afterwards stays (once per rule, task and occasion); a moved due date is a new occasion
 - "3 days before -> Soon at the end", newly assigned, the priority becomes high (lowered and raised again = again),
   from project Y with the condition "priority high", gets the project tag Z; the topmost rule that holds wins
 - a task the person does not see (somebody else's) or that "My tasks" did not send: untouched
 - delete a section: its rules wait; the Undo of the deletion points them at the restored one
 - validation, the limit of 20, the version (409), the order, agents have none (403), a person of an organisation the same
freelancer-matrix: tasks (frida has no organisation: every route as her)
usage: p2823_a_mine_rules_test.py <datadir>"""
import sys
from datetime import date, timedelta

import requests

import kt
from kt import B, check
from freelancer_fixture import freelancer, login

kt.fresh()
A = kt.setup()
FID, Fr = freelancer(B, A, "frida")
BID, Bo = freelancer(B, A, "bob")
Fr2 = login(B, "frida")  # frida's second device
H = {"X-Requested-With": "kalmido"}
D0 = date.today()
TODAY, IN3, IN9 = D0.isoformat(), (D0 + timedelta(days=3)).isoformat(), (D0 + timedelta(days=9)).isoformat()


def st(s=Fr):
    return s.get(B + "/api/state").json()


def secs(s=Fr):
    return st(s)["mine_sections"]


def by_kind(lst, k):
    return next((x for x in lst if x["kind"] == k), None)


def rules(s=Fr):
    return s.get(B + "/api/mine-rules").json()["rules"]


def apply(ids, s=Fr):
    r = s.post(B + "/api/mine-rules/apply", json={"ids": ids, "today": TODAY})
    check(r.ok, f"apply {r.status_code} {r.text[:200]}")
    return r.json()


def sec_of(tid, s=Fr):
    return secs(s)["tasks"].get(str(tid))


def order(s=Fr):
    o = st(s)["mine_order"]
    return [int(k) for k, _ in sorted(o.items(), key=lambda x: x[1])]


def task(tid, s=Fr):
    return next(t for t in st(s)["tasks"] if t["id"] == tid)


# ================================================================== 1. the first rule comes with the sections
check(secs()["rules"] == 0 and rules() == [], "no rules before the sections")
L = Fr.post(B + "/api/mine-sections/init", json={}).json()["mine_sections"]["list"]
REC, NOW, SOON, LATER = (by_kind(L, k)["id"] for k in ("recent", "now", "soon", "later"))
R = rules()
check(len(R) == 1 and R[0]["default"] and R[0]["trigger"] == {"kind": "due", "when": "now"} and R[0]["section_id"] == NOW
      and R[0]["place"] == "top" and R[0]["active"], f"the first rule: due today or overdue -> Now at the top {R}")
check(secs()["rules"] == 1, "state: mine_sections.rules = 1 (the app sends apply)")
DEF = R[0]["id"]

# ================================================================== 2. due today / overdue into Now; the task stays as it is
HOME = Fr.post(B + "/api/lists", json={"name": "Home"}).json()["id"]
WORK = Fr.post(B + "/api/lists", json={"name": "Work"}).json()["id"]


def mk(title, lid=HOME, **kw):
    return Fr.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw}).json()["id"]


T_OVER, T_TODAY, T_IN3, T_PLAIN = mk("Overdue", due="2020-01-02"), mk("Today", due=TODAY), mk("In three days", due=IN3), mk("Plain")
T_FAR = mk("Far away", due=IN9)
T_W1, T_W2 = mk("Work high", WORK, priority=5), mk("Work low", WORK)
ALL = [T_OVER, T_TODAY, T_IN3, T_PLAIN, T_FAR, T_W1, T_W2]
before = {t["id"]: (t["sort"], t.get("section_id"), t.get("due"), t.get("priority"), t["list_id"]) for t in st()["tasks"] if t["id"] in ALL}
check(Fr.put(B + "/api/tasks/mine-order", json={"ids": [T_PLAIN, T_FAR]}).ok, "setup: Plain and Far have a place (no section)")
j = apply(ALL)
check(j.get("moved") == 2 and sec_of(T_OVER) == NOW and sec_of(T_TODAY) == NOW, f"(1) overdue and due today into Now {j.get('moved')} {secs()['tasks']}")
check(sec_of(T_IN3) is None and sec_of(T_PLAIN) is None, "the others stay where they were")
check(j.get("mine_order") and j.get("mine_sections"), "the answer brings the new own order and sections")
after = {t["id"]: (t["sort"], t.get("section_id"), t.get("due"), t.get("priority"), t["list_id"]) for t in st()["tasks"] if t["id"] in ALL}
check(after == before, "the tasks, their projects and the projects' order unchanged")
check(apply(ALL).get("moved") == 0, "a second run moves nothing (once per occasion)")

# ================================================================== 3. hand wins; a moved due date is a new occasion
o = order()
check(Fr.put(B + "/api/tasks/mine-order", json={"ids": o, "secs": {str(T_OVER): SOON}}).ok and sec_of(T_OVER) == SOON, "setup: Overdue into Soon by hand")
check(apply(ALL).get("moved") == 0 and sec_of(T_OVER) == SOON, "(2) moved by hand afterwards: it stays in Soon")
check(Fr.patch(B + f"/api/tasks/{T_OVER}", json={"due": TODAY}).ok, "setup: Overdue gets a new due date (today)")
check(apply(ALL).get("moved") == 1 and sec_of(T_OVER) == NOW, "a moved due date is a new occasion: back in Now")

# ================================================================== 4. 3 days before -> Soon at the end
r = Fr.post(B + "/api/mine-rules", json={"trigger": {"kind": "due", "when": "before", "days": 3}, "section_id": SOON, "place": "bottom"})
check(r.ok and r.json().get("id") and len(r.json()["rules"]) == 2, f"a rule: 3 days before -> Soon {r.status_code} {r.text[:200]}")
R3 = r.json()["id"]
check(Fr.put(B + "/api/tasks/mine-order", json={"ids": order(), "secs": {str(T_PLAIN): SOON}}).ok, "setup: Plain in Soon by hand")
check(apply(ALL).get("moved") == 1 and sec_of(T_IN3) == SOON and sec_of(T_FAR) is None, "(3) due in 3 days: into Soon, due in 9 days: not")
o = order()
check(o.index(T_IN3) > o.index(T_PLAIN), f"at the end of Soon {o}")

# ================================================================== 5. a task the person does not see / that was not sent: untouched
BL = Bo.post(B + "/api/lists", json={"name": "Bob's"}).json()["id"]
T_BOB = Bo.post(B + "/api/tasks", json={"title": "Bob's overdue", "list_id": BL, "due": "2020-01-01"}).json()["id"]
T_NOT = mk("Not sent", due="2020-01-01")
check(apply(ALL + [T_BOB]).get("moved") == 0, "(4) somebody else's task: nothing")
check(str(T_BOB) not in st()["mine_order"] and not kt.dbx("SELECT 1 FROM user_task_order WHERE task_id=?", (T_BOB,)), "no row for a task frida cannot see")
check(sec_of(T_NOT) is None and str(T_NOT) not in st()["mine_order"], "a task \"My tasks\" did not send: untouched")
check(not kt.dbx("SELECT 1 FROM user_mine_rule_runs WHERE task_id=?", (T_BOB,)), "and no marker for it")

# ================================================================== 6. priority becomes high: lowered and raised again = again
ERR = Fr.post(B + "/api/mine-sections", json={"name": "Errands"}).json()["id"]
r = Fr.post(B + "/api/mine-rules", json={"name": "High", "trigger": {"kind": "prio"}, "section_id": LATER})
RP = r.json().get("id")
check(r.ok and apply(ALL).get("moved") == 1 and sec_of(T_W1) == LATER, "priority high: Work high into Someday")
check(Fr.patch(B + f"/api/tasks/{T_PLAIN}", json={"priority": 5}).ok and apply(ALL).get("moved") == 1 and sec_of(T_PLAIN) == LATER,
      "Plain becomes high: into Someday (from a section put by hand: a new occasion)")
check(Fr.put(B + "/api/tasks/mine-order", json={"ids": order(), "secs": {str(T_PLAIN): ERR}}).ok and apply(ALL).get("moved") == 0
      and sec_of(T_PLAIN) == ERR, "moved by hand: stays")
Fr.patch(B + f"/api/tasks/{T_PLAIN}", json={"priority": 0})
check(apply(ALL).get("moved") == 0 and sec_of(T_PLAIN) == ERR, "lowered: nothing moves")
Fr.patch(B + f"/api/tasks/{T_PLAIN}", json={"priority": 5})
check(apply(ALL).get("moved") == 1 and sec_of(T_PLAIN) == LATER, "raised again: a new occasion, into Someday")

# ================================================================== 7. the topmost rule wins; from project Y only if high; a project tag
r = Fr.post(B + "/api/mine-rules", json={"trigger": {"kind": "list", "list_id": WORK}, "section_id": ERR, "conditions": {"priority": "high"}})
RL = r.json().get("id")
check(r.ok and apply(ALL).get("moved") == 1 and sec_of(T_W1) == ERR and sec_of(T_W2) is None,
      "a new rule looks at the tasks there are: Work high into Errands (an occasion of its own), Work low not (only if high)")
check(Fr.put(B + "/api/mine-rules/order", json={"ids": [RL, DEF, R3, RP]}).ok and [x["id"] for x in rules()][:1] == [RL], "the project rule on top")
check(Fr.patch(B + f"/api/mine-rules/{RL}", json={"conditions": {"priority": "high"}, "place": "bottom"}).ok, "changed: the rule starts anew")
check(apply(ALL).get("moved") == 1 and sec_of(T_W1) == ERR and sec_of(T_W2) is None, "(5) from Work only if high: Work high into Errands, Work low not")
T_W3 = mk("Work new high", WORK, priority=5)
ALL.append(T_W3)
check(apply(ALL).get("moved") == 1 and sec_of(T_W3) == ERR, "a new high task of Work: the topmost rule (Errands), not Someday")
TAG = Fr.post(B + f"/api/lists/{WORK}/tags", json={"name": "call"}).json()["id"]
r = Fr.post(B + "/api/mine-rules", json={"trigger": {"kind": "ltag", "tag_id": TAG}, "section_id": SOON, "place": "top"})
check(r.ok and r.json()["rules"][-1]["trigger"] == {"kind": "ltag", "tag_id": TAG, "list_id": WORK}, f"a tag rule {r.text[:200]}")
RT = r.json()["id"]
check(apply(ALL).get("moved") == 0, "no task has the tag yet")
check(Fr.patch(B + f"/api/tasks/{T_W2}", json={"ltags": ["call"]}).ok and apply(ALL).get("moved") == 1 and sec_of(T_W2) == SOON
      and order().index(T_W2) < order().index(T_IN3), "(6) gets the tag: into Soon at the top")

# ================================================================== 8. switched off, deleted, Undo; the first rule never comes back
check(Fr.patch(B + f"/api/mine-rules/{DEF}", json={"active": False}).ok and secs()["rules"] == 4, "the first rule switched off: 4 active")
T_NEW_OVER = mk("New overdue", due="2020-02-02")
ALL.append(T_NEW_OVER)
check(apply(ALL).get("moved") == 0 and sec_of(T_NEW_OVER) is None, "switched off: an overdue task stays where it is")
v = next(x for x in rules() if x["id"] == DEF)["updated_at"]
check(Fr.delete(B + f"/api/mine-rules/{DEF}", json={"expect_updated_at": v}).ok and DEF not in [x["id"] for x in rules()], "deleted")
apply(ALL)
check(not any(x["default"] for x in rules()), "a deleted first rule never comes back by itself")
check(Fr.post(B + f"/api/mine-rules/{DEF}/restore", json={}).ok and DEF in [x["id"] for x in rules()], "Undo: it is back")
Fr.patch(B + f"/api/mine-rules/{DEF}", json={"active": True})
check(apply(ALL).get("moved") == 1 and sec_of(T_NEW_OVER) == NOW, "on again: the overdue task into Now")

# ================================================================== 9. a section deleted: its rules wait; Undo points them at it again
r = Fr.delete(B + f"/api/mine-sections/{SOON}")
rs = r.json()["restore"]
check(r.ok and rs.get("id") == SOON, "Soon deleted, the restore data name its id")
check(all(x["waiting"] for x in rules() if x["id"] in (R3, RT)) and secs()["rules"] == 5, "its rules wait")
T_IN3B = mk("Also in three days", due=IN3)
ALL.append(T_IN3B)
check(apply(ALL).get("moved") == 0 and sec_of(T_IN3B) is None, "a waiting rule moves nothing")
r = Fr.post(B + "/api/mine-sections", json={"name": rs["name"], "restore": rs})
NEWSOON = r.json()["id"]
check(all(x["section_id"] == NEWSOON and not x["waiting"] for x in rules() if x["id"] in (R3, RT)), "Undo: the rules point at the restored Soon")
check(apply(ALL).get("moved") == 1 and sec_of(T_IN3B) == NEWSOON, "and move again")

# ================================================================== 10. newly assigned to me
r = Fr.post(B + "/api/mine-rules", json={"trigger": {"kind": "new"}, "section_id": LATER, "place": "bottom"})
RN = r.json().get("id")
Fr.put(B + "/api/mine-rules/order", json={"ids": [RN]})
T_FRESH = mk("Fresh")
ALL.append(T_FRESH)
check(T_FRESH not in order() and apply(ALL).get("moved") >= 1 and sec_of(T_FRESH) == LATER, "(7) newly assigned (no place yet): into Someday")
check(apply(ALL).get("moved") == 0, "once placed it is no longer new")

# ================================================================== 11. validation, other people's things, version, limit
bad = [{"trigger": {"kind": "x"}, "section_id": ERR}, {"trigger": {"kind": "due", "when": "before", "days": 0}, "section_id": ERR},
       {"trigger": {"kind": "due", "when": "before", "days": 31}, "section_id": ERR}, {"trigger": {"kind": "prio"}, "section_id": REC},
       {"trigger": {"kind": "list", "list_id": BL}, "section_id": ERR}, {"trigger": {"kind": "prio"}, "section_id": 99999999},
       {"trigger": {"kind": "prio"}, "section_id": ERR, "place": "middle"}, {"trigger": {"kind": "prio"}, "section_id": ERR, "conditions": {"priority": "x"}},
       {"trigger": {"kind": "prio"}, "section_id": ERR, "conditions": {"list_id": BL}}, {"trigger": {"kind": "prio"}}]
codes = [Fr.post(B + "/api/mine-rules", json=b).status_code for b in bad]
check(all(c == 400 for c in codes), f"invalid rules: 400 (Recently assigned, bob's project, unknown section ...) {codes}")
BNOW = by_kind(Bo.post(B + "/api/mine-sections/init", json={}).json()["mine_sections"]["list"], "now")["id"]
check(Fr.post(B + "/api/mine-rules", json={"trigger": {"kind": "prio"}, "section_id": BNOW}).status_code == 400, "bob's section: 400")
check(Bo.patch(B + f"/api/mine-rules/{RP}", json={"active": False}).status_code == 404 and Bo.delete(B + f"/api/mine-rules/{RP}").status_code == 404,
      "somebody else's rule: 404")
check(RP not in [x["id"] for x in rules(Bo)] and len(rules(Bo)) == 1, "bob sees only his own first rule")
seen = next(x for x in Fr2.get(B + "/api/mine-rules").json()["rules"] if x["id"] == RP)
check(Fr.patch(B + f"/api/mine-rules/{RP}", json={"name": "Urgent things", "expect_updated_at": seen["updated_at"]}).ok, "device A renames")
r = Fr2.patch(B + f"/api/mine-rules/{RP}", json={"name": "Old", "expect_updated_at": seen["updated_at"]})
check(r.status_code == 409 and r.json().get("rule", {}).get("name") == "Urgent things", f"device B with the old version: 409 {r.status_code} {r.text[:200]}")
n = len(rules())
for i in range(20 - n):
    Fr.post(B + "/api/mine-rules", json={"trigger": {"kind": "prio"}, "section_id": ERR, "active": False})
check(len(rules()) == 20 and Fr.post(B + "/api/mine-rules", json={"trigger": {"kind": "prio"}, "section_id": ERR}).status_code == 400, "at most 20 rules")
check(Fr.post(B + "/api/mine-rules/apply", json={"ids": "x"}).status_code == 400, "apply: ids must be a list")

# ================================================================== 12. an older account: the first rule at the next run, hand wins
GID, Gi = freelancer(B, A, "gina")
GL = Gi.post(B + "/api/mine-sections/init", json={}).json()["mine_sections"]["list"]
GNOW, GSOON = by_kind(GL, "now")["id"], by_kind(GL, "soon")["id"]
kt.dbx("DELETE FROM user_mine_rules WHERE user_id=?", (GID,))  # as before 2.823: sections, no rules
GH = Gi.post(B + "/api/lists", json={"name": "G"}).json()["id"]
G1 = Gi.post(B + "/api/tasks", json={"title": "Put by hand", "list_id": GH, "due": "2020-01-01"}).json()["id"]
G2 = Gi.post(B + "/api/tasks", json={"title": "Not by hand", "list_id": GH, "due": "2020-01-01"}).json()["id"]
check(Gi.put(B + "/api/tasks/mine-order", json={"ids": [G1, G2], "secs": {str(G1): GSOON}}).ok, "setup: gina put an overdue task into Soon by hand")
check(secs(Gi)["rules"] == 1, "state: the first rule is still to be made (the app sends apply)")
j = apply([G1, G2], Gi)
check(len(rules(Gi)) == 1 and rules(Gi)[0]["default"], "made at the first run")
check(sec_of(G1, Gi) == GSOON and sec_of(G2, Gi) == GNOW, f"hand wins: the task put by hand stays in Soon, the other into Now {secs(Gi)['tasks']}")

# ================================================================== 13. agents have none
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "structure"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag.get("token", "x"), **H}
codes = [requests.get(B + "/api/mine-rules", headers=AGH).status_code,
         requests.post(B + "/api/mine-rules", headers=AGH, json={"trigger": {"kind": "prio"}, "section_id": ERR}).status_code,
         requests.patch(B + f"/api/mine-rules/{RP}", headers=AGH, json={"active": False}).status_code,
         requests.delete(B + f"/api/mine-rules/{RP}", headers=AGH).status_code,
         requests.post(B + f"/api/mine-rules/{RP}/restore", headers=AGH, json={}).status_code,
         requests.put(B + "/api/mine-rules/order", headers=AGH, json={"ids": []}).status_code,
         requests.post(B + "/api/mine-rules/apply", headers=AGH, json={"ids": ALL}).status_code]
check(all(c in (401, 403) for c in codes), f"agents neither read nor write the own rules {codes}")
check(next(x for x in rules() if x["id"] == RP)["active"], "the agent changed nothing")

# ================================================================== 14. a person of an organisation the same way (alice)
AL = A.post(B + "/api/mine-sections/init", json={}).json()["mine_sections"]["list"]
AH = A.post(B + "/api/lists", json={"name": "Alice's"}).json()["id"]
TA = A.post(B + "/api/tasks", json={"title": "Alice overdue", "list_id": AH, "due": "2020-01-01"}).json()["id"]
check(len(rules(A)) == 1 and apply([TA], A).get("moved") == 1 and sec_of(TA, A) == by_kind(AL, "now")["id"], "alice (organisation): the same first rule")

sys.exit(kt.done("p2823_a_mine_rules"))
