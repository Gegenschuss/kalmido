#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.577.0 (#3356): shared views of a project. Invented projects and titles only.
freelancer-matrix: lists (a person without an organisation, the own project)
 - create / change / delete: editors only (reader 403, stranger 404, never content); read: everyone with read access
 - not in the person's filters; a filter of someone else stays 404; a project left or in the trash: no view any more
 - GET /api/v1/tasks?filter_id=: every rule category, an own filter, a shared view; evaluated with the reader's rights
   (me = the reader, a participant sees only their own tasks, never another project); bad id 400, unknown 404
 - GET / POST /api/v1/lists/<id>/views, scopes; agents only in projects shared with them
 - organisation boundary: a project of another organisation, a project moved to another workspace
 - deleted creator: the view stays; delta sync: full for the project's people only
usage: p2577_a_views_api_test.py <datadir>      (KMT_NOSTART=1 / PR2472C_NOSTART=1: a running server)"""
import requests

import kt
from freelancer_fixture import freelancer, login
from kt import B, check, done, fresh, setup

fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="PR2472C")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
V = B + "/api/v1"
AID = A.get(B + "/api/state").json()["me"]["id"]
FID, F = freelancer(B, A)


def person(name, **kw):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com", **kw})
    assert r.ok, r.text
    s = login(B, name)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    return r.json()["id"], s


def token(s, scopes=("read", "tasks:write", "structure", "delete")):
    r = s.post(B + "/api/me/tokens", json={"name": "views", "scopes": list(scopes)})
    assert r.ok, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def new_list(s, name, **b):
    r = s.post(B + "/api/lists", json={"name": name, **b})
    assert r.ok, r.text
    return r.json()["id"]


def task(s, lid, title, **b):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **b})
    assert r.ok, r.text
    return r.json()["id"]


def share(lid, uid, role):
    r = A.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": role})
    assert r.ok, r.text


def views(s):
    return s.get(B + "/api/state").json()["views"]


EID, E = person("erin")      # editor
RID, R = person("rita")      # reader
PID, P = person("paul")      # participant
XID, X = person("xaver")     # no access
TE, TR, TX = token(E), token(R), token(X)

L = new_list(A, "Product")
L2 = new_list(A, "Other project")
for uid, role in ((EID, "edit"), (RID, "view"), (PID, "participant")):
    share(L, uid, role)
OTHER = task(A, L2, "Other project task", priority=5)
SEC = A.post(B + "/api/sections", json={"list_id": L, "name": "Doing"}).json()["id"]
T1 = task(A, L, "Crash on login", priority=5, assignee_id=PID, section_id=SEC, due="2020-01-02")
T2 = task(A, L, "Tidy the docs", priority=1, assignee_id=RID, ttype="bug")
T3 = task(A, L, "Plan the launch", priority=3, content="crash report attached")

# ================================================================== who may write
r = E.post(B + "/api/filters", json={"name": "Urgent", "list_id": L, "rules": {"prios": [5], "lists": [L2], "sort": "date"}})
check(r.ok, f"an editor creates a shared view: {r.text[:120]}")
VW = r.json()["id"]
check(R.post(B + "/api/filters", json={"name": "No", "list_id": L}).status_code == 403, "a reader cannot create a view")
check(P.post(B + "/api/filters", json={"name": "No", "list_id": L}).status_code == 403, "a participant cannot create a view")
check(X.post(B + "/api/filters", json={"name": "No", "list_id": L}).status_code == 404, "a stranger cannot, and does not learn of the project")
check(E.post(B + "/api/filters", json={"name": "No", "list_id": L, "shared": False}).status_code == 400, "list_id with shared false: 400")
check(E.post(B + "/api/filters", json={"name": "No", "shared": True}).status_code == 400, "shared without a project: 400")
check(E.post(B + "/api/filters", json={"name": "No", "list_id": L, "rules": [1]}).status_code == 400, "rules must be an object")
inbox = next(x["id"] for x in E.get(B + "/api/state").json()["lists"] if x.get("is_inbox"))
check(E.post(B + "/api/filters", json={"name": "No", "list_id": inbox}).status_code == 400, "the inbox has no shared views")
check(R.patch(B + f"/api/filters/{VW}", json={"name": "Mine"}).status_code == 403, "a reader cannot change a view")
check(R.delete(B + f"/api/filters/{VW}").status_code == 403, "a reader cannot delete a view")
check(X.patch(B + f"/api/filters/{VW}", json={"name": "Mine"}).status_code == 404, "a stranger: 404 on change")
check(X.delete(B + f"/api/filters/{VW}").status_code == 404, "a stranger: 404 on delete")
check(A.patch(B + f"/api/filters/{VW}", json={"name": "Urgent now"}).ok, "the owner (not its creator) changes the view")
check(E.patch(B + f"/api/filters/{VW}", json={"rules": {"prios": [5], "lists": [L2], "sort": "date"}}).ok, "the editor changes its rules")
check("lists" not in views(R)[0]["rules"], "a shared view keeps no project in its rules")

# ================================================================== who sees it
for who, s in (("owner", A), ("editor", E), ("reader", R), ("participant", P)):
    v = views(s)
    check([x["id"] for x in v] == [VW], f"{who}: the view is in the state")
    check(VW not in [x["id"] for x in s.get(B + "/api/state").json()["filters"]], f"{who}: not with the person's filters")
check(views(X) == [], "a stranger's state has no view")
mine = R.post(B + "/api/filters", json={"name": "Private of Rita", "rules": {"prios": [1]}}).json()["id"]
check(E.patch(B + f"/api/filters/{mine}", json={"name": "x"}).status_code == 404, "a private filter of someone else: 404")
check(requests.get(V + "/tasks", headers=TE, params={"filter_id": mine}).status_code == 404, "filter_id of someone else's private filter: 404")
check([x["id"] for x in requests.get(V + "/filters", headers=TR).json()["data"]] == [mine], "GET /filters: only the own private ones")
check(requests.get(V + f"/lists/{L}/views", headers=TX).status_code == 404, "GET views: a stranger 404")
d = requests.get(V + f"/lists/{L}/views", headers=TR).json()["data"]
check([(x["id"], x["list_id"], x["shared"]) for x in d] == [(VW, L, True)], "GET views: a reader sees the view")


def ids(hdr, **q):
    r = requests.get(V + "/tasks", headers=hdr, params=q)
    assert r.ok, r.text
    return [t["id"] for t in r.json()["data"]]


# ================================================================== the rules on the server, with the reader's rights
check(ids(TR, filter_id=VW) == [T1], "reader: high priority of this project only, even with another project in the request")
check(ids(TE, filter_id=VW, status="all") == [T1], "the other project's high priority task stays out")
pv = task(A, L, "High priority nobody gave Paul", priority=5)
check(pv in ids(TR, filter_id=VW), "reader sees the new high priority task")
check(ids(token(P), filter_id=VW) == [T1], "a participant sees only their own tasks in the view")
A.delete(B + f"/api/tasks/{pv}")
r = requests.get(V + "/tasks", headers=TX, params={"filter_id": VW})
check(r.status_code == 404, "filter_id of a view of a project not seen: 404, no tasks")
check(requests.get(V + "/tasks", headers=TR, params={"filter_id": "abc"}).status_code == 400, "filter_id not a number: 400")
check(requests.get(V + "/tasks", headers=TR, params={"filter_id": 9999999}).status_code == 404, "unknown filter_id: 404")
pg = requests.get(V + "/tasks", headers=TR, params={"filter_id": E.post(B + "/api/filters", json={"name": "All", "list_id": L, "rules": {"sort": "title"}}).json()["id"], "limit": 1})
check(pg.json()["data"][0]["id"] == T1 and pg.json()["next_cursor"], "a view brings its sort along, and pages")
AV = pg.request.url.split("filter_id=")[1].split("&")[0]
check(ids(TR, filter_id=AV, sort="-priority", limit=1) == [T1], "an explicit sort wins")


def by_rules(rules, hdr=TR):
    r = E.post(B + "/api/filters", json={"name": "Probe", "list_id": L, "rules": rules})
    assert r.ok, r.text
    fid = r.json()["id"]
    try:
        return sorted(ids(hdr, filter_id=fid))
    finally:
        E.delete(B + f"/api/filters/{fid}")


check(by_rules({"who": ["me"]}) == [T2], "who me = the person reading (Rita)")
check(by_rules({"who": ["me"]}, TE) == [], "who me = the person reading (Erin)")
check(by_rules({"who": ["none"]}) == [T3], "who none")
check(by_rules({"who": [str(PID)]}) == [T1], "who id")
check(by_rules({"prios": [1, 3]}) == [T2, T3], "several priorities")
check(by_rules({"types": ["bug"]}) == [T2], "ticket type")
check(by_rules({"secs": [str(SEC)]}) == [T1], "column")
check(by_rules({"secs": ["none"]}) == [T2, T3], "no column")
check(by_rules({"dates": ["overdue"]}) == [T1], "overdue")
check(by_rules({"dates": ["nodate"]}) == [T2, T3], "no date")
check(by_rules({"text": "CRASH"}) == [T1, T3], "text in title or notes, any case")
check(by_rules({"text": "100%_"}) == [], "text is literal")
check(by_rules({"op": "or", "prios": [5], "types": ["bug"]}) == [T1, T2], "op or")
check(by_rules({"prios": [5], "types": ["bug"]}) == [], "op and")
check(by_rules({"who": ["x'; DROP TABLE tasks; --"], "ms": [{"a": 1}], "prios": ["5"]}) == [], "nonsense values match nothing")
check(by_rules({"sprints": ["none"]}) == [T1, T2, T3], "sprint none = backlog")
check(by_rules({"sprints": ["cur"]}) == [], "no active sprint")
fd = lambda name, typ, **o: A.post(B + f"/api/lists/{L}/fields", json={"name": name, "type": typ, **o}).json()  # noqa: E731
F1, F2 = fd("Size", "number")["id"], fd("Ok", "checkbox")["id"]
F3 = fd("Stage", "select", options={"options": [{"name": "A"}, {"name": "B"}]})
OPT = F3["options"]["options"][0]["id"]
TAD = token(A)
assert requests.patch(V + f"/tasks/{T1}", headers=TAD, json={"fields": {str(F1): 7, str(F2): True, str(F3["id"]): OPT}}).ok
assert requests.patch(V + f"/tasks/{T2}", headers=TAD, json={"fields": {str(F1): 2}}).ok
check(by_rules({"cf": {str(F1): {"num": {"op": "gt", "v": "5"}}}}) == [T1], "number field greater")
check(by_rules({"cf": {str(F1): {"num": {"op": "lt", "v": "5,5"}}}}) == [T2], "number field less, decimal comma")
check(by_rules({"cf": {str(F1): {"num": {"op": "empty"}}}}) == [T3], "number field empty")
check(by_rules({"cf": {str(F2): {"chk": ["1"]}}}) == [T1], "checkbox checked")
check(by_rules({"cf": {str(F2): {"chk": ["0"]}}}) == [T2, T3], "checkbox not checked")
check(by_rules({"cf": {str(F3['id']): {"sel": [OPT]}}}) == [T1], "select")
check(by_rules({"cf": {str(F3['id']): {"sel": [""]}}}) == [T2, T3], "select empty")
own = requests.post(V + "/filters", headers=TR, json={"name": "Mine too", "rules": {"lists": [L], "tags": ["nope"]}}).json()
# 2.577.0 (#3354 + #3356): a column meaning in a view: done counts every status like ?section_kind=, a wrong value matches nothing
SD = E.post(B + "/api/sections", json={"list_id": L, "name": "Shipped", "kind": "done"}).json()["id"]
T9 = task(E, L, "shipped work")
check(E.patch(B + f"/api/tasks/{T9}", json={"section_id": SD}).status_code < 300, "moved into the done column")
check(by_rules({"kinds": ["done"]}) == [T9], "a view on the done meaning shows the completed task (default status would hide it)")
check(T9 not in by_rules({"kinds": ["open"]}), "the open meaning leaves it out")
check(by_rules({"kinds": ["nonsense"]}) == [], "an unknown meaning matches nothing, no error")
# 2.577.0 (#3356): the filter dialog stores conditions since 2.521.0 (#4479): {op, conds: [{f, op, v}]}, the same meaning on the server
C = lambda *cs, op="and": {"op": op, "conds": list(cs)}  # noqa: E731
check(by_rules(C({"f": "prio", "op": "in", "v": [5]})) == [T1], "conds: priority is one of")
check(by_rules(C({"f": "prio", "op": "in", "v": []})) == [T1, T2, T3], "conds: a condition without values is off")
check(by_rules(C({"f": "prio", "op": "in", "v": [5]}, {"f": "type", "op": "in", "v": ["bug"]}, {"f": "who", "op": "nin", "v": [str(PID)]}, op="or")) == [T2],
      "conds: is none of holds on top, also with OR")
check(by_rules(C({"f": "who", "op": "empty"})) == [T3], "conds: assignee is empty")
check(by_rules(C({"f": "sec", "op": "nin", "v": [str(SEC)]})) == [T2, T3], "conds: column is none of (tasks without a column count)")
check(by_rules(C({"f": "text", "op": "nhas", "v": "crash"})) == [T2], "conds: text does not contain (title and notes)")
check(by_rules(C({"f": "cf", "name": "stage", "ft": "select", "op": "in", "v": ["a"]})) == [T1], "conds: a field by name and type, an option by name")
check(by_rules(C({"f": "cf", "name": "Stage", "ft": "select", "op": "nin", "v": ["A"]})) == [T2, T3], "conds: field is none of")
check(by_rules(C({"f": "cf", "fid": F1, "op": "gt", "v": 5})) == [T1], "conds: one field, greater than")
check(by_rules(C({"f": "cf", "fid": F1, "op": "empty"})) == [T3], "conds: one field, empty")
check(by_rules(C({"f": "kind", "op": "in", "v": ["done"]})) == [T9], "conds: the column meaning done")
check(by_rules(C({"f": "kind", "op": "nin", "v": ["done", "rejected"]})) == [T1, T2, T3], "conds: the meaning is none of")
check(by_rules(C({"f": "nonsense", "op": "in", "v": [1]}, {"f": "prio", "op": "zz", "v": [5]})) == [T1, T2, T3], "conds: unknown conditions are off")
assert A.patch(B + f"/api/lists/{L}", json={"folder": "Work"}).ok
check(by_rules(C({"f": "folder", "op": "in", "v": ["Work"]})) == [T1, T2, T3], "conds: the folder as the reader sees it (the owner's)")
check(by_rules(C({"f": "folder", "op": "in", "v": ["Wor"]})) == [], "conds: a folder is a whole name")
check(by_rules(C({"f": "folder", "op": "empty"})) == [], "conds: folder is empty")
assert A.patch(B + f"/api/lists/{L}", json={"folder": ""}).ok
check(ids(TR, filter_id=own["id"]) == [] and own["list_id"] is None and own["shared"] is False, "an own private filter works with filter_id")

# ================================================================== the REST routes, scopes, agents
r = requests.post(V + f"/lists/{L}/views", headers=TE, json={"name": "Docs", "rules": {"types": ["bug"], "display": "kanban", "group": "none"}})
check(r.status_code == 201 and r.json()["rules"]["display"] == "kanban" and r.json()["shared"] is True, f"POST views: {r.text[:120]}")
check(requests.post(V + f"/lists/{L}/views", headers=TR, json={"name": "No"}).status_code == 403, "POST views: reader 403")
check(requests.post(V + f"/lists/{L}/views", headers=TX, json={"name": "No"}).status_code == 404, "POST views: stranger 404")
check(requests.post(V + f"/lists/{L}/views", headers=token(E, ("read",)), json={"name": "No"}).status_code == 403, "POST views: needs the scope structure")
check(requests.post(V + f"/lists/{L}/views", headers=TE, json={"name": "No", "zz": 1}).status_code == 400, "POST views: unknown field 400")
check(requests.patch(V + f"/filters/{r.json()['id']}", headers=TR, json={"name": "No"}).status_code == 403, "v1 PATCH: reader 403")
check(requests.delete(V + f"/filters/{r.json()['id']}", headers=TE).status_code == 204, "v1 DELETE: editor")
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "structure"], "username": "scout", "display_name": "Scout"}).json()
TA = {"Authorization": "Bearer " + ag["token"]}
check(requests.get(V + f"/lists/{L}/views", headers=TA).status_code == 404, "an agent without the project: 404")
check(requests.get(V + "/tasks", headers=TA, params={"filter_id": VW}).status_code == 404, "an agent without the project: filter_id 404")
share(L, ag["id"], "view")
check([x["id"] for x in requests.get(V + f"/lists/{L}/views", headers=TA).json()["data"]][0] == VW, "an agent the project is shared with reads the views")
check(ids(TA, filter_id=VW) == [T1], "and applies them")
check(requests.post(V + f"/lists/{L}/views", headers=TA, json={"name": "No"}).status_code == 403, "a reading agent cannot write")

# ================================================================== delta sync: the project's people, nobody else
vE = E.get(B + "/api/state").json()["v"]
vX = X.get(B + "/api/state").json()["v"]
nv = E.post(B + "/api/filters", json={"name": "New one", "list_id": L}).json()["id"]
check(R.get(B + f"/api/state/delta?since={vE}").json().get("full") is True, "a new view: the project's people load the state")
check(X.get(B + f"/api/state/delta?since={vX}").json().get("full") is False, "others keep their delta")
E.delete(B + f"/api/filters/{nv}")

# ================================================================== access ends
L3 = new_list(A, "Short stay")
share(L3, RID, "view")
V3 = A.post(B + "/api/filters", json={"name": "Stay", "list_id": L3}).json()["id"]
check(V3 in [x["id"] for x in views(R)], "a view of the new project")
A.delete(B + f"/api/lists/{L3}/members/{RID}")
check(V3 not in [x["id"] for x in views(R)], "after removal: not in the state")
check(requests.get(V + "/tasks", headers=TR, params={"filter_id": V3}).status_code == 404, "after removal: filter_id 404")
check(R.patch(B + f"/api/filters/{V3}", json={"name": "x"}).status_code == 404, "after removal: no change")
assert A.patch(B + f"/api/lists/{L3}", json={"archived": 1}).ok
r = A.delete(B + f"/api/lists/{L3}")
check(r.ok, f"project into the trash: {r.text[:100]}")
check(V3 not in [x["id"] for x in views(A)], "a project in the trash: no view")
check(requests.get(V + "/tasks", headers=token(A), params={"filter_id": V3}).status_code == 404, "a project in the trash: 404, no error")
check(A.get(B + "/api/state").ok, "the state stays fine")

# ================================================================== the creator goes, the view stays
TMP, S2 = person("tilda")
share(L, TMP, "edit")
VT = S2.post(B + "/api/filters", json={"name": "From Tilda", "list_id": L}).json()["id"]
own2 = S2.post(B + "/api/filters", json={"name": "Private of Tilda"}).json()["id"]
r = A.delete(B + f"/api/users/{TMP}")
check(r.ok, f"the creator's account goes: {r.text[:120]}")
check(VT in [x["id"] for x in views(R)], "the shared view stays with the project")
check(not kt.dbx("SELECT 1 FROM filters WHERE id=?", (own2,)), "their private filter goes")
check(kt.dbx("SELECT user_id FROM filters WHERE id=?", (VT,))[0][0] is None, "no reference to the person stays")
# ================================================================== organisation boundary, a move to another workspace
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": AID}).json()["id"]
GID, G = person("gina", orgs=[])
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": GID}).json()["id"]
L4 = new_list(A, "Alpha project", org_id=ORG)
V4 = A.post(B + "/api/filters", json={"name": "Alpha view", "list_id": L4}).json()["id"]
TG = token(G)
check(requests.get(V + "/tasks", headers=TG, params={"filter_id": V4}).status_code == 404, "another organisation: filter_id 404")
check(requests.get(V + f"/lists/{L4}/views", headers=TG).status_code == 404, "another organisation: views 404")
check(G.patch(B + f"/api/filters/{V4}", json={"name": "x"}).status_code == 404, "another organisation: no change")
check(V4 not in [x["id"] for x in views(G)], "another organisation: nothing in the state")
L5 = new_list(F, "Freelance project")
V5 = F.post(B + "/api/filters", json={"name": "Own view", "list_id": L5, "rules": {"prios": [5]}}).json()["id"]  # freelancer-matrix: lists
TF = token(F)
t5 = task(F, L5, "Invoice client", priority=5)
task(F, L5, "Later", priority=1)
check(ids(TF, filter_id=V5) == [t5], "a person without an organisation: the own project's view")
r = requests.post(V + f"/lists/{L5}/views", headers=TF, json={"name": "Second", "rules": {"text": "later"}})
check(r.status_code == 201, "a person without an organisation: POST views")
check(len(requests.get(V + f"/lists/{L5}/views", headers=TF).json()["data"]) == 2, "a person without an organisation: GET views")
L6 = new_list(A, "Moves along")
V6 = A.post(B + "/api/filters", json={"name": "Moved", "list_id": L6}).json()["id"]
check(A.patch(B + f"/api/lists/{L6}", json={"org_id": ORG}).ok, "the project moves into the organisation")
check(requests.get(V + f"/lists/{L6}/views", headers=token(A)).json()["data"][0]["id"] == V6, "its view goes along")
check(requests.get(V + "/tasks", headers=TG, params={"filter_id": V6}).status_code == 404, "and stays out of reach of the other organisation")

done("p2577_a_views_api")
