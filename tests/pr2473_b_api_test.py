#!/usr/bin/env python3
# kalmido-suite:
"""2.473.0 API tests (#3378: project type Software with the fields Size + Release and the bug inbox), own container (start.sh). Invented data only.
 - the type brings Size (selection S / M / L, pinned) and Release (text, not pinned), also without sections
 - a type change only offers the fields (ptype_missing, with the options), nothing is added
 - bug_inbox: second list "<name> – Bugs" (same folder and workspace, type software, only Release), rule there, answer bug_list_id;
   default off; no effect on another type; not a boolean = 400; in the agent API too; an agent gets 403 and nothing is made
 - the rule: a filled Release moves the task into the build list (first section), the value goes along; the same at creation;
   clearing Release moves nothing; a Release left empty stays; it runs as its creator and pauses when the target is gone from them
 - rules in general: the trigger value "*" is refused on a checkbox field, a selection field takes it
P4: a person without an organisation gets the same (freelancer-matrix: lists)
usage: pr2473_b_api_test.py <datadir>"""
import sys

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

kt.fresh(prefix="PR2473B")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en"})
V = B + "/api/v1"


def state(s):
    return s.get(B + "/api/state").json()


def fields(s, lid):
    return {f["name"]: f for f in state(s)["fields"] if f["list_id"] == lid}


def sections(s, lid):
    return [x for x in state(s)["sections"] if x["list_id"] == lid]


def task(s, tid):
    return s.get(B + f"/api/tasks/{tid}").json()


def rules(s, lid):
    return s.get(B + f"/api/lists/{lid}/rules").json()["rules"]


def case(s, who):
    # the fields of the type
    j = s.post(B + "/api/lists", json={"name": "Plain app", "ptype": "software"}).json()
    f = fields(s, j["id"])
    check(sorted(f) == ["Release", "Size"], f"{who}: software brings Size and Release {sorted(f)}")
    check(f["Size"]["type"] == "select" and f["Size"]["pinned"] == 1 and [o["name"] for o in f["Size"]["options"]["options"]] == ["S", "M", "L"],
          f"{who}: Size = selection S / M / L, pinned {f['Size']}")
    check(f["Release"]["type"] == "text" and f["Release"]["pinned"] == 0, f"{who}: Release = text, not pinned {f['Release']}")
    check("bug_list_id" not in j and len([x for x in state(s)["lists"] if x["name"] == "Plain app – Bugs"]) == 0, f"{who}: no bug inbox by default")

    # a type change only offers them
    o = s.post(B + "/api/lists", json={"name": "Older"}).json()
    r = s.patch(B + f"/api/lists/{o['id']}", json={"ptype": "software"})
    miss = r.json().get("ptype_missing", {}).get("fields", [])
    check(r.ok and [x["name"] for x in miss] == ["Size", "Release"] and len(miss[0]["options"]["options"]) == 3, f"{who}: the type change offers the fields {miss}")
    check(not fields(s, o["id"]), f"{who}: the type change adds no field")

    # bad value, another type
    r = s.post(B + "/api/lists", json={"name": "Bad", "ptype": "software", "bug_inbox": "yes"})
    check(r.status_code == 400, f"{who}: bug_inbox not a boolean = 400 {r.status_code}")
    n = len(state(s)["lists"])
    r = s.post(B + "/api/lists", json={"name": "Agency one", "ptype": "agency", "bug_inbox": True})
    check(r.ok and "bug_list_id" not in r.json() and len(state(s)["lists"]) == n + 1, f"{who}: no effect on another type")

    # the second list + rule
    j = s.post(B + "/api/lists", json={"name": "App", "ptype": "software", "folder": "Dev", "sections": True, "color": "#6d8cff", "bug_inbox": True}).json()
    BUILD, BUG = j["id"], j["bug_list_id"]
    L = {x["id"]: x for x in state(s)["lists"]}
    x = L[BUG]
    check(x["name"] == "App – Bugs" and x["folder"] == "Dev" and x["ptype"] == "software" and x["tickets"] in (1, True) and x["color"] == "#6d8cff"
          and x["org_id"] == L[BUILD]["org_id"], f"{who}: the bug list next to the build list {x['name'], x['folder'], x['ptype'], x['org_id']}")
    check(not sections(s, BUG), f"{who}: the bug list has no sections")
    bf = fields(s, BUG)
    check(list(bf) == ["Release"], f"{who}: the bug list has only Release {list(bf)}")
    rs = rules(s, BUG)
    first = next(x for x in sections(s, BUILD) if x["name"] == "Backlog")
    check(len(rs) == 1 and rs[0]["active"] and rs[0]["trigger"] == {"kind": "field", "field_id": bf["Release"]["id"], "value": "*"}
          and rs[0]["action"]["kind"] == "move" and rs[0]["action"]["list_id"] == BUILD and rs[0]["action"]["section_id"] == first["id"],
          f"{who}: the rule {rs}")
    check(rs[0]["created_by"] == s.get(B + "/api/state").json()["me"]["id"], f"{who}: the rule is the creator's")
    RF, TF = bf["Release"]["id"], fields(s, BUILD)["Release"]["id"]

    # no value: stays; a value: moves, the value along
    t = s.post(B + "/api/tasks", json={"title": "Crash on save", "list_id": BUG}).json()
    check(task(s, t["id"])["list_id"] == BUG, f"{who}: without a release it stays")
    r = s.patch(B + f"/api/tasks/{t['id']}", json={"fields": {str(RF): "2.5"}})
    x = task(s, t["id"])
    check(r.ok and x["list_id"] == BUILD and x["section_id"] == first["id"], f"{who}: Release filled = in the build list, first section {x['list_id'], x['section_id']}")
    check(x["fields"].get(str(TF)) == "2.5", f"{who}: the value goes along into the build list's Release {x['fields']}")

    # filled at creation
    t2 = s.post(B + "/api/tasks", json={"title": "Filled at once", "list_id": BUG, "fields": {str(RF): "2.6"}}).json()
    check(task(s, t2["id"])["list_id"] == BUILD and task(s, t2["id"])["fields"].get(str(TF)) == "2.6", f"{who}: filled when created = moves too")

    # back in the inbox with its old value: clearing it is no reason to move
    r = s.patch(B + f"/api/tasks/{t['id']}", json={"list_id": BUG})
    check(r.ok and task(s, t["id"])["list_id"] == BUG, f"{who}: moved back by hand stays (a move triggers nothing)")
    r = s.patch(B + f"/api/tasks/{t['id']}", json={"fields": {str(RF): None}})
    check(r.ok and task(s, t["id"])["list_id"] == BUG and not task(s, t["id"])["fields"].get(str(RF)), f"{who}: clearing Release moves nothing {task(s, t['id'])['list_id']}")

    # the check when it fires: the target column gone = the rule pauses, the task stays
    r = s.delete(B + f"/api/sections/{first['id']}")
    check(r.ok, f"{who}: section deleted {r.status_code}")
    r = s.patch(B + f"/api/tasks/{t['id']}", json={"fields": {str(RF): "3.0"}})
    rs = rules(s, BUG)
    check(r.ok and task(s, t["id"])["list_id"] == BUG and not rs[0]["active"] and rs[0]["paused_reason"] == "section", f"{who}: target gone: the rule pauses {rs[0]}")


case(A, "alice")
FID, Fr = freelancer(B, A)
case(Fr, "frida (no organisation)")

# the rule runs as its creator: Bob only has the bug list, the task still reaches the build list he cannot see
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"}).json()["id"]
j = A.post(B + "/api/lists", json={"name": "Shared", "ptype": "software", "bug_inbox": True}).json()
check(A.put(B + f"/api/lists/{j['bug_list_id']}/members", json={"user_id": BOB, "role": "edit"}).ok, "Bob joins the bug list")
Bo = sess("bob")
RF = fields(A, j["bug_list_id"])["Release"]["id"]
t = Bo.post(B + "/api/tasks", json={"title": "Found by Bob", "list_id": j["bug_list_id"]}).json()
r = Bo.patch(B + f"/api/tasks/{t['id']}", json={"fields": {str(RF): "9"}})
check(r.ok and task(A, t["id"])["list_id"] == j["id"], f"as the creator: into a list Bob has no access to {r.status_code} {task(A, t['id']).get('list_id')}")
check(Bo.get(B + f"/api/tasks/{t['id']}").status_code in (403, 404), "... and Bob does not see it there (the project's limit holds)")
check(not rules(A, j["bug_list_id"])[0]["paused_reason"], "... the rule stays active")

# the same "*" in a rule set up by hand: selection yes, checkbox no
L = A.post(B + "/api/lists", json={"name": "Rule fields"}).json()["id"]
SEL = A.post(B + f"/api/lists/{L}/fields", json={"name": "Pick", "type": "select", "options": {"options": [{"name": "One"}]}}).json()
CHK = A.post(B + f"/api/lists/{L}/fields", json={"name": "Box", "type": "checkbox"}).json()
r = A.post(B + f"/api/lists/{L}/rules", json={"name": "Sel", "trigger": {"kind": "field", "field_id": SEL["id"], "value": "*"}, "action": {"kind": "priority", "priority": "high"}})
check(r.status_code == 201 and r.json()["trigger"]["value"] == "*" and not r.json()["names"].get("value"), f"a selection field takes \"*\" {r.text[:200]}")
r = A.post(B + f"/api/lists/{L}/rules", json={"name": "Chk", "trigger": {"kind": "field", "field_id": CHK["id"], "value": "*"}, "action": {"kind": "priority", "priority": "high"}})
check(r.status_code == 400, f"a checkbox field refuses \"*\" {r.status_code}")

# the agent API: a person's token limited to selected lists keeps both new lists; an agent is refused, nothing is made
r = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"], "list_ids": [L]})
assert r.status_code == 201, r.text
PH = {"Authorization": "Bearer " + r.json()["token"]}
r = sess().post(V + "/lists", headers=PH, json={"name": "Token app", "project_type": "software", "bug_inbox": True})
check(r.status_code == 201 and r.json().get("bug_list_id"), f"v1: bug_inbox makes both, bug_list_id in the answer {r.status_code} {r.text[:160]}")
if r.status_code == 201:
    TB = r.json()["bug_list_id"]
    x = sess().get(V + f"/lists/{TB}", headers=PH)
    check(x.ok and x.json()["name"] == "Token app – Bugs", f"v1: the limited token keeps the second list {x.status_code}")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
AGH = {"Authorization": "Bearer " + r.json()["token"]}
r = sess().post(V + "/lists", headers=AGH, json={"name": "Agent app", "project_type": "software", "bug_inbox": True})
check(r.status_code == 403, f"agent: bug_inbox = 403 {r.status_code} {r.text[:120]}")
r = sess().get(V + "/lists", headers=AGH)
check(not [x for x in r.json().get("items", r.json() if isinstance(r.json(), list) else []) if x["name"].startswith("Agent app")], "agent: nothing was made")
r = sess().post(V + "/lists", headers=AGH, json={"name": "Agent plain", "project_type": "software", "bug_inbox": "x"})
check(r.status_code == 400, f"v1: not a boolean = 400 {r.status_code}")
r = sess().post(V + "/lists", headers=AGH, json={"name": "Agent other", "project_type": "agency", "bug_inbox": True})
check(r.status_code == 201 and "bug_list_id" not in r.json(), f"agent: no effect on another type {r.text[:160]}")

sys.exit(kt.done("pr2473_b_api"))
