#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.633.0 part C, own container (start.sh). Invented names only, addresses @example.com.
#4779 team chat: the channel list (GET /api/team/channels, API v1 /team/channels) goes through the core's floor
(objects.py obj_gate) like need_room: a personal token limited to lists lists no channel (no names, no member ids); the
same person in the app and with a token without a limit still sees the channel.
#4781 list rules, actions done / reopen (freelancer-matrix: lists):
 - "comes into column Done -> mark it as done": the task is done, the history says it was the rule (run as its creator)
 - a recurring task gets its next occurrence (stays open, next due day) and a completed copy, as with the tick
 - a task that waited on it is free (activity "unblocked"); open subtasks do not stop it (they are done with it)
 - loop protection: a task completed by a rule starts no further rule ("is completed -> comment" stays silent; by hand it runs)
 - done already -> nothing (no second completion in the history); open already -> reopen does nothing
 - "comes into column Again -> open it again" reopens a done task
 - only the owner / a list admin creates such a rule (an edit member 403); an unknown value of the action = 400
 - OpenAPI lists done / reopen in the action enum
 - a person without an organisation: the same in a private list
usage: p2633_c_rules_api_test.py <datadir>"""
import os
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
import requests  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, sess  # noqa: E402,F401

V = B + "/api/v1"
FEAT = "cal,comments,collab,deps"

kt.fresh(prefix="P2633C")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})


def token(s, name, lists=None):
    j = {"name": name, "scopes": ["read", "comments"], "expires_days": None}
    if lists is not None:
        j["list_ids"] = lists
    r = s.post(B + "/api/me/tokens", json=j)
    check(r.ok and r.json().get("token"), f"setup: token {name} {r.text[:160]}")
    return {"Authorization": "Bearer " + (r.json().get("token") or "x")} if r.ok else {}


# ================================================================ #4779 the channel list and a token limited to lists
LW = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
r = A.post(B + "/api/team/channels", json={"name": "General", "org_id": ORG, "members": [BOB]})
check(r.status_code in (200, 201), f"#4779 setup: channel {r.text[:160]}")
CH = r.json().get("id")
app_ids = [x["id"] for x in A.get(B + "/api/team/channels").json().get("channels") or []]
check(CH in app_ids, f"#4779: the app lists the channel {app_ids}")
FULL, LIM = token(A, "full"), token(A, "only work", [LW])
r = requests.get(V + "/team/channels", headers=FULL)
check(r.ok and CH in [x["id"] for x in r.json().get("data") or []], f"#4779: a token without a limit lists it {r.status_code} {r.text[:160]}")
r = requests.get(V + "/team/channels", headers=LIM)
check(r.ok and not (r.json().get("data") or []), f"#4779: a token limited to lists lists no channel {r.status_code} {r.text[:200]}")
check("General" not in r.text, "#4779: ... not even the channel's name")
check(requests.get(V + f"/team/rooms/{CH}/messages", headers=LIM).status_code in (403, 404), "#4779: ... and reads none (need_room, unchanged)")
# 2.633.0 (#4779, review): the channel's own routes (need_xroom: rename, open, archive, members) go through the same floor
WS = ["read", "comments", "tasks:write", "structure"]
def wtoken(name, lists=None):
    j = {"name": name, "scopes": WS, "expires_days": None, **({"list_ids": lists} if lists is not None else {})}
    r = A.post(B + "/api/me/tokens", json=j)
    check(r.ok and r.json().get("token"), f"setup: token {name} {r.text[:160]}")
    return {"Authorization": "Bearer " + (r.json().get("token") or "x")}
WLIM, WFULL = wtoken("write only work", [LW]), wtoken("write all")
r = requests.patch(V + f"/team/rooms/{CH}", headers=WLIM, json={"name": "Renamed"})
check(r.status_code in (403, 404) and "General" not in r.text, f"#4779: a token limited to lists renames no channel by its id {r.status_code} {r.text[:160]}")
r = requests.post(V + f"/team/rooms/{CH}/members", headers=WLIM, json={"user_id": BOB})
check(r.status_code in (403, 404) and "General" not in r.text, f"#4779: ... and adds no member {r.status_code} {r.text[:160]}")
names = [x["name"] for x in A.get(B + "/api/team/channels").json().get("channels") or [] if x["id"] == CH]
check(names == ["General"], f"#4779: the channel kept its name {names}")
r = requests.patch(V + f"/team/rooms/{CH}", headers=WFULL, json={"name": "General 2"})
check(r.ok, f"#4779: a token without a limit still renames it (the floor only stops the limit) {r.status_code} {r.text[:160]}")
A.patch(B + f"/api/team/rooms/{CH}", json={"name": "General"})


# ================================================================ #4781 rules done / reopen
def task(s, lid, title, **k):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **k})
    assert r.ok, r.text
    return r.json()["id"]


def get(s, tid):
    return s.get(B + f"/api/tasks/{tid}").json()


def sec(s, lid, name):
    r = s.post(B + "/api/sections", json={"list_id": lid, "name": name})
    assert r.ok, r.text
    return r.json()["id"]


def rule(s, lid, name, trig, act, code=201):
    r = s.post(B + f"/api/lists/{lid}/rules", json={"name": name, "trigger": trig, "action": act})
    check(r.status_code == code, f"rule {name}: {code} (got {r.status_code} {r.text[:200]})")
    return r.json().get("id") if r.ok else None


def acts(s, tid, kind, rid=None):
    """The history lines of kind of task tid (rid: only those of that rule)."""
    out = [a for a in s.get(B + f"/api/tasks/{tid}/timeline").json()["activity"] if a["kind"] == kind]
    return [a for a in out if ((a.get("data") or {}).get("rule") or {}).get("id") == rid] if rid else out


def comments(s, tid, name):
    return [c for c in s.get(B + f"/api/tasks/{tid}/timeline").json()["comments"] if c.get("rule_name") == name]


def flow(s, who, lid, me_id):
    """The whole flow in list lid of session s (an organisation's list or a freelancer's private one)."""
    DONE, AGAIN, TODO = sec(s, lid, "Done"), sec(s, lid, "Again"), sec(s, lid, "To do")
    RD = rule(s, lid, "Finish", {"kind": "section", "section_id": DONE}, {"kind": "done"})
    RO = rule(s, lid, "Back", {"kind": "section", "section_id": AGAIN}, {"kind": "reopen"})
    RC = rule(s, lid, "Said", {"kind": "done"}, {"kind": "comment", "text": "Completed"})
    names = {x["id"]: x for x in s.get(B + f"/api/lists/{lid}/rules").json()["rules"]}
    check(names.get(RD, {}).get("action") == {"kind": "done"} and names.get(RO, {}).get("action") == {"kind": "reopen"},
          f"{who}: the rules read back with their action {[(x['action']) for x in names.values()]}")

    # comes into Done -> done; the history marks the rule, run as its creator; no further rule (no comment)
    t1 = task(s, lid, "Write the report", section_id=TODO)
    s.patch(B + f"/api/tasks/{t1}", json={"section_id": DONE})
    check(get(s, t1)["status"] == 2, f"{who}: column Done -> the rule marked it done {get(s, t1)['status']}")
    a = acts(s, t1, "complete", RD)
    check(a and a[0]["user_id"] == me_id, f"{who}: the history says rule Finish (as its creator) {acts(s, t1, 'complete')}")
    check(not comments(s, t1, "Said"), f"{who}: loop protection: the completion by a rule starts no further rule")

    # done already -> nothing; by hand the follow-up rule does run (it is there and active)
    t2 = task(s, lid, "Call back", section_id=TODO)
    check(s.post(B + f"/api/tasks/{t2}/complete", json={}).ok, f"{who}: ticked by hand")
    check(comments(s, t2, "Said"), f"{who}: by hand the rule 'is completed -> comment' runs (control)")
    s.patch(B + f"/api/tasks/{t2}", json={"section_id": DONE})
    check(len(acts(s, t2, "complete")) == 1 and not acts(s, t2, "complete", RD), f"{who}: done already -> the rule does nothing {acts(s, t2, 'complete')}")

    # reopen: a done task into Again is open again; an open one stays as it is
    s.patch(B + f"/api/tasks/{t2}", json={"section_id": AGAIN})
    check(get(s, t2)["status"] == 0 and acts(s, t2, "reopen", RO), f"{who}: column Again -> the rule opened it again {get(s, t2)['status']}")
    t3 = task(s, lid, "Plan the week", section_id=TODO)
    s.patch(B + f"/api/tasks/{t3}", json={"section_id": AGAIN})
    check(get(s, t3)["status"] == 0 and not acts(s, t3, "reopen"), f"{who}: open already -> reopen does nothing")

    # a recurring task: the next occurrence + a completed copy
    today = testclock.today()
    t4 = task(s, lid, "Water the plants", section_id=TODO, due=today.isoformat(), repeat="FREQ=DAILY")
    s.patch(B + f"/api/tasks/{t4}", json={"section_id": DONE})
    g4 = get(s, t4)
    check(g4["status"] == 0 and (g4.get("due") or "") > today.isoformat(), f"{who}: recurring: open with its next due day {g4.get('status')} {g4.get('due')}")
    a4 = acts(s, t4, "complete", RD)
    check(a4 and (a4[0].get("data") or {}).get("next"), f"{who}: recurring: the history notes the next occurrence {a4}")
    done_copy = [x for x in s.get(B + "/api/state").json()["tasks"] if x["title"] == "Water the plants" and x["status"] == 2]
    check(len(done_copy) == 1, f"{who}: recurring: a completed copy, as with the tick ({len(done_copy)})")

    # dependants free; open subtasks do not stop it
    t5 = task(s, lid, "Collect the receipts", section_id=TODO)
    t6 = task(s, lid, "File the tax return")
    sub = task(s, lid, "Bank statements", parent_id=t5)
    r = s.post(B + "/api/deps", json={"task_id": t6, "blocker_id": t5})
    check(r.ok and get(s, t6).get("blocked"), f"{who}: setup: t6 waits on t5 {r.text[:120]}")
    s.patch(B + f"/api/tasks/{t5}", json={"section_id": DONE})
    check(get(s, t5)["status"] == 2 and get(s, sub)["status"] == 2, f"{who}: open subtasks do not stop it (done with it, as the tick)")
    check(not get(s, t6).get("blocked") and acts(s, t6, "unblocked"), f"{who}: the task waiting on it is free (history: unblocked)")
    return lid, DONE


L = A.post(B + "/api/lists", json={"name": "Office", "org_id": ORG}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"})
flow(A, "org", L, ALICE)

# rights and validation
rule(Bo, L, "Mine", {"kind": "done"}, {"kind": "reopen"}, code=403)
rule(A, L, "Bad", {"kind": "done"}, {"kind": "reopen", "value": 1}, code=400)
# a task bob moves: the rule runs as alice (its creator), the history says so
DONE_L = [x["id"] for x in A.get(B + "/api/state").json()["sections"] if x["list_id"] == L and x["name"] == "Done"][0]
RD_L = [x["id"] for x in A.get(B + f"/api/lists/{L}/rules").json()["rules"] if x["name"] == "Finish"][0]
tb = task(Bo, L, "Bob's draft")
Bo.patch(B + f"/api/tasks/{tb}", json={"section_id": DONE_L})
a = acts(A, tb, "complete", RD_L)
check(get(A, tb)["status"] == 2 and a and a[0]["user_id"] == ALICE, f"a member's move: the rule completes it as its creator {a}")

spec = requests.get(V + "/openapi.json").json()
enum = (((spec.get("components") or {}).get("schemas") or {}).get("ListRule") or {}).get("properties", {}).get("action", {}).get("properties", {}).get("kind", {}).get("enum") or []
check("done" in enum and "reopen" in enum, f"OpenAPI: the action enum has done / reopen {enum}")

# a person without an organisation: a private list
FID, Fr = freelancer(B, A)
LF = Fr.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
flow(Fr, "freelancer", LF, FID)

sys.exit(kt.done("p2633_c_rules_api"))
