#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.609.0 API tests (#3372: own ticket types per workspace), own container (start.sh). Invented data only.
 - a person's own types (space private): epic / story only as suggestions, switched on by their key; an own type from a name
   (key from the name), at most 20; a task gets an own type only once it exists and is offered (before: 400)
 - the type's note template for a new ticket, a project's own template for it wins (lists.ticket_tpl with an own key)
 - a project picks the types it offers (lists.ttypes): GET /api/lists/<id>/ticket-types, an own type it does not offer = 400,
   a built-in one always (forms, imports); the default type must be a type of the workspace (story unknown = 400)
 - switched off: not offered, tasks keep it; deleting with tasks: 409 with the count, with confirm=1 they get no type and the
   projects forget it (default, pick)
 - an organisation's types: its admin manages them, a member reads (403 on writes), another person sees nothing (404)
 - API v1: a person's token reads and manages, an agent reads only (403), the task filter type=<own key>, OpenAPI documents it
P4: a person without an organisation manages their own (freelancer-matrix: tasks)
usage: p2609_c_ttypes_api_test.py <datadir>"""
import sys

import kt
from kt import B, check, sess
from freelancer_fixture import FEATURES, freelancer, org_join

kt.fresh(prefix="P2609CT")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
V = B + "/api/v1"


def tt(s, space="private"):
    r = s.get(B + "/api/ticket-types", params={"space": space})
    assert r.ok, r.text
    return r.json()


def new(s, lid, **kw):
    return s.post(B + "/api/tasks", json={"title": kw.pop("title", "T"), "list_id": lid, **kw})


def case(s, who):
    """The private space of one person (the admin, the freelancer)."""
    j = tt(s)
    check(j["types"] == [] and j["can_edit"] and sorted(x["key"] for x in j["suggestions"]) == ["epic", "story"],
          f"{who}: no own types at first, epic and story only suggested {j}")
    L = s.post(B + "/api/lists", json={"name": "Tickets " + who, "tickets": True}).json()["id"]
    r = new(s, L, ttype="epic")
    check(r.status_code == 400, f"{who}: epic before it is switched on = 400 {r.status_code} {r.text[:120]}")
    r = s.post(B + "/api/ticket-types", json={"key": "epic"})
    check(r.ok and r.json()["name"] == "Epic" and r.json()["icon"] == "flag" and r.json()["enabled"], f"{who}: epic switched on {r.text[:200]}")
    EPIC = r.json()["id"]
    for nm in ("", "   "):  # 2.1010.0 (#4033): a suggestion's key with an empty name is refused, not stored without a name
        check(s.post(B + "/api/ticket-types", json={"key": "story", "name": nm}).status_code == 400, f"{who}: story with name {nm!r} = 400")
    r = s.post(B + "/api/ticket-types", json={"name": "Incident", "icon": "zap", "color": "#AA3300", "template": "**Impact**\n"})
    check(r.ok and r.json()["key"] == "incident" and r.json()["color"] == "#aa3300", f"{who}: an own type from a name {r.text[:200]}")
    INC = r.json()["id"]
    check(s.post(B + "/api/ticket-types", json={"name": "Incident"}).status_code == 400, f"{who}: the same key twice = 400")
    check(s.post(B + "/api/ticket-types", json={"key": "bug", "name": "Mine"}).status_code == 400, f"{who}: a built-in key = 400")
    check(s.post(B + "/api/ticket-types", json={"name": "x", "icon": "nope"}).status_code == 400, f"{who}: an unknown symbol = 400")
    check(s.patch(B + f"/api/ticket-types/{INC}", json={"key": "other"}).status_code == 400, f"{who}: the key stays")

    # a ticket of an own type, with the type's template; the project's own template for it wins
    r = new(s, L, title="Big thing", ttype="epic")
    check(r.ok and r.json()["ttype"] == "epic" and "Goal" in (r.json().get("content") or ""), f"{who}: an epic with its template {r.text[:200]}")
    E1 = r.json()["id"]
    # 2.609.0 (#3372): a copy keeps the own type where the project offers it (templates.py tpl_ttype; before: the copy had no type)
    r = s.post(B + f"/api/tasks/{E1}/duplicate", json={})
    check(r.ok and r.json()["task"]["ttype"] == "epic", f"{who}: a duplicated epic stays an epic {r.text[:200]}")
    s.delete(B + f"/api/tasks/{r.json()['task']['id']}") if r.ok else None
    r = new(s, L, title="Down", ttype="incident")
    check(r.ok and r.json().get("content") == "**Impact**\n", f"{who}: the own type's template {r.text[:200]}")
    r = s.patch(B + f"/api/lists/{L}", json={"ticket_tpl": {"incident": "**Project impact**\n"}})
    check(r.ok, f"{who}: a project's template of an own type is stored {r.status_code} {r.text[:120]}")
    check(new(s, L, ttype="incident").json().get("content") == "**Project impact**\n", f"{who}: the project's template wins")
    check(s.patch(B + f"/api/lists/{L}", json={"ticket_tpl": {"task": "x"}}).status_code == 400, f"{who}: no template for task")
    T = new(s, L, title="Plain").json()["id"]
    r = s.patch(B + f"/api/tasks/{T}", json={"ttype": "story"})
    check(r.status_code == 400, f"{who}: a type that does not exist = 400 {r.status_code}")
    r = s.patch(B + f"/api/tasks/{T}", json={"ttype": "incident"})
    check(r.ok and r.json()["ttype"] == "incident", f"{who}: changed to an own type {r.text[:160]}")

    # the project picks
    check(s.get(B + f"/api/lists/{L}/ticket-types").json()["keys"] == ["bug", "feature", "task", "epic", "incident"], f"{who}: all offered at first")
    r = s.patch(B + f"/api/lists/{L}", json={"ttypes": ["bug", "epic"], "def_ttype": "epic"})
    check(r.ok, f"{who}: the project's pick and default {r.status_code} {r.text[:160]}")
    check(s.get(B + f"/api/lists/{L}/ticket-types").json()["keys"] == ["bug", "epic"], f"{who}: only the picked ones")
    check(new(s, L, ttype="incident").status_code == 400, f"{who}: an own type the project does not offer = 400")
    check(new(s, L, ttype="feature").ok, f"{who}: a built-in type always (forms, imports)")
    check(new(s, L).json()["ttype"] == "epic", f"{who}: the default type epic")
    check(s.patch(B + f"/api/lists/{L}", json={"def_ttype": "story"}).status_code == 400, f"{who}: an unknown default type = 400")
    check(s.patch(B + f"/api/lists/{L}", json={"ttypes": ["Bad Key"]}).status_code == 400, f"{who}: a bad pick = 400")
    s.patch(B + f"/api/lists/{L}", json={"ttypes": []})
    # 2.1010.0 (#4033): moved into a project without its own type: the task keeps it and the answer says so (move_ttype)
    L2 = s.post(B + "/api/lists", json={"name": "Other " + who, "tickets": True}).json()["id"]
    check(s.patch(B + f"/api/lists/{L2}", json={"ttypes": ["bug"]}).ok, f"{who}: a second project offers bug only")
    r = s.patch(B + f"/api/tasks/{T}", json={"list_id": L2})
    check(r.ok and r.json().get("move_ttype") == "incident" and r.json()["ttype"] == "incident",
          f"{who}: moved, the type stays and the answer names it {r.status_code} {r.text[:160]}")
    r = s.patch(B + f"/api/tasks/{T}", json={"list_id": L})
    check(r.ok and "move_ttype" not in r.json() and r.json()["ttype"] == "incident", f"{who}: back where it is offered: no hint {r.text[:160]}")

    # switched off: not offered, the tasks keep it
    r = s.patch(B + f"/api/ticket-types/{INC}", json={"enabled": False})
    check(r.ok and not r.json()["enabled"], f"{who}: switched off {r.text[:120]}")
    check("incident" not in s.get(B + f"/api/lists/{L}/ticket-types").json()["keys"], f"{who}: a switched off type is not offered")
    check(s.get(B + f"/api/tasks/{T}").json()["ttype"] == "incident", f"{who}: a task keeps a switched off type")

    k = new(s, L, title="Part", parent_id=E1)
    check(k.ok, f"{who}: a subtask of the epic (the app shows its progress) {k.status_code}")

    # delete with tasks: ask first (409 + count), then they have no type
    s.patch(B + f"/api/lists/{L}", json={"ttypes": ["epic", "bug"], "def_ttype": "epic"})
    n = next(x for x in tt(s)["types"] if x["key"] == "epic")["tasks"]
    r = s.delete(B + f"/api/ticket-types/{EPIC}")
    check(r.status_code == 409 and r.json().get("tasks") == n and n >= 2 and r.json().get("code") == "has_tasks",
          f"{who}: delete with tasks asks first {r.status_code} {r.text[:200]} n={n}")
    r = s.delete(B + f"/api/ticket-types/{EPIC}", params={"confirm": "1"})
    check(r.ok and r.json()["tasks"] == n, f"{who}: deleted after the question {r.status_code} {r.text[:160]}")
    check(s.get(B + f"/api/tasks/{E1}").json()["ttype"] == "", f"{who}: its tasks have no type")
    lst = next(x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == L)
    check(lst["def_ttype"] == "" and lst["ttypes"] == '["bug"]', f"{who}: the project forgot it {lst['def_ttype']!r} {lst['ttypes']!r}")
    check(s.delete(B + f"/api/ticket-types/{INC}").status_code == 409, f"{who}: a switched off type with tasks asks too")

    # at most 20
    for i in range(19):
        s.post(B + "/api/ticket-types", json={"name": f"Kind {i}"})
    check(len(tt(s)["types"]) == 20, f"{who}: 20 own types {len(tt(s)['types'])}")
    r = s.post(B + "/api/ticket-types", json={"name": "One too many"})
    check(r.status_code == 400, f"{who}: the 21st = 400 {r.status_code}")
    return L, INC


L_A, INC_A = case(A, "admin")
FID, Fr = freelancer(B, A)
case(Fr, "freelancer")
check(Fr.patch(B + f"/api/ticket-types/{INC_A}", json={"name": "Hijack"}).status_code == 404, "another person's type: 404")
check(not any(x["owner_id"] == ALICE for x in Fr.get(B + "/api/ticket-types").json()["types"] if "owner_id" in x),
      "another person's private types stay unseen")

# ================================================================ an organisation's types
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"})
assert org_join(B, "bob", ORG)
Bo = sess("bob")
SP = f"org:{ORG}"
r = A.post(B + "/api/ticket-types", json={"space": SP, "key": "story"})
check(r.ok and r.json()["org_id"] == ORG and r.json()["name"] == "Story", f"org: the admin switches story on {r.text[:160]}")
ST = r.json()["id"]
j = tt(Bo, SP)
check([x["key"] for x in j["types"]] == ["story"] and not j["can_edit"], f"org: a member reads, cannot change {j}")
check(Bo.post(B + "/api/ticket-types", json={"space": SP, "name": "Mine"}).status_code == 403, "org: a member cannot add")
check(Bo.patch(B + f"/api/ticket-types/{ST}", json={"name": "X"}).status_code == 403, "org: a member cannot change")
# tenant-matrix: orgschema. Another organisation's ticket types: a stranger 404 to read or change
check(Fr.get(B + "/api/ticket-types", params={"space": SP}).status_code == 404, "org: a stranger gets 404")
check(Fr.patch(B + f"/api/ticket-types/{ST}", json={"name": "X"}).status_code == 404, "org: a stranger cannot change (404)")
OL = A.post(B + "/api/lists", json={"name": "Team board", "org_id": ORG, "tickets": True}).json()["id"]
check("story" in A.get(B + f"/api/lists/{OL}/ticket-types").json()["keys"] and "incident" not in A.get(B + f"/api/lists/{OL}/ticket-types").json()["keys"],
      "org: an organisation's project offers the organisation's types, not the admin's private ones")
check(new(A, OL, ttype="incident").status_code == 400 and new(A, OL, ttype="story").ok, "org: a task gets the organisation's types only")
check(new(A, L_A, ttype="story").status_code == 400, "a private project does not offer the organisation's types")

# ================================================================ API v1: a person's token manages, an agent only reads
r = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]})
assert r.status_code == 201, r.text
PH = {"Authorization": "Bearer " + r.json()["token"]}
r = sess().get(V + "/ticket-types", headers=PH)
check(r.ok and any(x["key"] == "incident" for x in r.json()["types"]), f"v1: a person's token reads {r.status_code} {r.text[:160]}")
r = sess().post(V + "/ticket-types", headers=PH, json={"space": SP, "name": "Spike", "icon": "rocket"})
check(r.ok and r.json()["key"] == "spike", f"v1: a person's token creates {r.status_code} {r.text[:160]}")
check(sess().post(V + "/ticket-types", headers=PH, json={"name": "X", "colour": "#000000"}).status_code == 400, "v1: an unknown field = 400")
SPK = r.json()["id"]
r = sess().get(V + f"/lists/{OL}/ticket-types", headers=PH)
check(r.ok and "spike" in r.json()["keys"], f"v1: what a project offers {r.text[:160]}")
r = sess().patch(V + f"/ticket-types/{SPK}", headers=PH, json={"color": "#112233"})
check(r.ok and r.json()["color"] == "#112233", f"v1: a person's token changes {r.status_code} {r.text[:160]}")
r = sess().post(V + "/tasks", headers=PH, json={"title": "From v1", "list_id": OL, "type": "spike"})
check(r.status_code == 201 and r.json().get("type") == "spike", f"v1: a task of an own type {r.status_code} {r.text[:160]}")
r = sess().get(V + "/tasks", headers=PH, params={"type": "spike", "list_id": OL})
check(r.ok and [x["title"] for x in r.json()["data"]] == ["From v1"], f"v1: the filter type=<own key> {r.status_code} {r.text[:200]}")
r = sess().post(V + "/tasks", headers=PH, json={"title": "x", "list_id": OL, "type": "epic"})
check(r.status_code == 400, f"v1: a type the project does not offer = 400 {r.status_code}")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "write"], "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
AG = {"Authorization": "Bearer " + r.json()["token"]}
A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": r.json()["id"], "role": "member"})
r = sess().get(V + "/ticket-types", headers=AG)
check(r.ok, f"v1: an agent reads {r.status_code} {r.text[:160]}")
r = sess().post(V + "/ticket-types", headers=AG, json={"name": "Agent kind"})
check(r.status_code == 403, f"v1: an agent cannot create {r.status_code} {r.text[:160]}")
r = sess().patch(V + f"/ticket-types/{ST}", headers=AG, json={"name": "X"})
check(r.status_code in (403, 404), f"v1: an agent cannot change {r.status_code}")
r = sess().delete(V + f"/ticket-types/{SPK}", headers=PH)
check(r.status_code == 409 and r.json()["error"].get("tasks") == 1 and r.json()["error"]["code"] == "has_tasks", f"v1: delete with a task asks first {r.status_code} {r.text[:160]}")
r = sess().delete(V + f"/ticket-types/{SPK}", headers=PH, params={"confirm": "1"})
check(r.ok and r.json()["tasks"] == 1, f"v1: deleted with confirm {r.status_code} {r.text[:160]}")
spec = sess().get(V + "/openapi.json").json()
check("/ticket-types" in spec["paths"] and "/ticket-types/{id}" in spec["paths"] and "TicketType" in spec["components"]["schemas"],
      "OpenAPI documents the ticket types")
check("enum" not in spec["components"]["schemas"]["Task"]["properties"]["type"], "OpenAPI: a task's type is no closed list any more")

sys.exit(kt.done("p2609_c_ttypes_api"))
