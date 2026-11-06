#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.574.0 D (#3376, from 2.393.0 D): the small ticket-model items. Invented projects and titles only. freelancer-matrix: tasks
 (1) priority "Urgent" (7) above High: web API 7 (6 = 400), API v1 / rules "urgent", priority_min=high includes it,
     sort by priority puts it first, OpenAPI enum; the same for a person without an organisation
 (2) POST /api/v1/tasks/<id>/duplicate (the web's duplicate): subtasks, type, points, assignee, fields, snippets come along, the
     copy is open, below the original; a read-only token 403, someone without access 404/403 an E2E project 403 list_e2e
 (3) GET /api/orgs/<id>/tasks: an organisation admin reads the tasks of the organisation's shared projects without being a
     member (open / done / all, one project, search); never an unshared, an encrypted, a private or (2.574.0) a health project (404 for those as
     list_id); a member who is no admin 403, an admin of another organisation 404, an agent with admin rights 403; every call
     is a row in the list log (history of "Projects of the organisation"); a person without an organisation: 404
 (4) list switch two_eyes (default off): an integrate / deploy / merge request needs the 👍 of two DIFFERENT approvers --
     the first stays open (state open, suggestion.approvals), the same person again never approves (decide and reaction), the
     second person approves, a 👎 rejects at once, a thumb taken back takes the approval back; off = one 👍 as before; a person
     without an organisation alone in the project never gets past the first 👍 (the app shows a hint)
tenant-matrix: org
usage: p2574_d_api_test.py <datadir>      (KMT_NOSTART=1 / P2574D_NOSTART=1: a running server)"""
import json
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, sess, setup

fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="P2574D")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, F = freelancer(B, A)
V = B + "/api/v1"
AID = A.get(B + "/api/state").json()["me"]["id"]


def token(s, scopes=("read", "tasks:write")):
    r = s.post(B + "/api/me/tokens", json={"name": "p2574d", "scopes": list(scopes)})
    assert r.ok, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


# ---------------------------------------------------------------- (1) Urgent
def prio(who, s):
    T = token(s)
    L = s.post(B + "/api/lists", json={"name": "Prio board", "kind": "project"}).json()["id"]
    r = s.post(B + "/api/tasks", json={"title": "Fire", "list_id": L, "priority": 7})
    check(r.ok and r.json()["priority"] == 7, f"{who}: web API takes priority 7 ({r.status_code} {r.text[:120]})")
    U = r.json()["id"]
    check(s.post(B + "/api/tasks", json={"title": "x", "list_id": L, "priority": 6}).status_code == 400, f"{who}: 6 stays invalid")
    H = requests.post(V + "/tasks", headers=T, json={"list_id": L, "title": "Hot", "priority": "high"}).json()["id"]
    r = requests.post(V + "/tasks", headers=T, json={"list_id": L, "title": "Fire 2", "priority": "urgent"})
    check(r.status_code == 201 and r.json()["priority"] == "urgent", f"{who}: v1 takes 'urgent' ({r.status_code} {r.text[:120]})")
    U2 = r.json()["id"]
    requests.post(V + "/tasks", headers=T, json={"list_id": L, "title": "Calm", "priority": "low"})
    check(requests.get(V + f"/tasks/{U}", headers=T).json()["priority"] == "urgent", f"{who}: v1 names 7 'urgent'")
    got = sorted(t["id"] for t in requests.get(V + "/tasks", headers=T, params={"list_id": L, "priority_min": "high"}).json()["data"])
    check(got == sorted([U, U2, H]), f"{who}: priority_min=high includes urgent {got}")
    got = [t["id"] for t in requests.get(V + "/tasks", headers=T, params={"list_id": L, "priority": "urgent"}).json()["data"]]
    check(sorted(got) == sorted([U, U2]), f"{who}: filter priority=urgent {got}")
    got = [t["priority"] for t in requests.get(V + "/tasks", headers=T, params={"list_id": L, "sort": "-priority"}).json()["data"]]
    check(got[:2] == ["urgent", "urgent"] and got[2] == "high", f"{who}: sort -priority puts urgent first {got}")
    r = s.post(B + f"/api/lists/{L}/rules", json={"name": "Escalate", "trigger": {"kind": "created"},
                                                   "action": {"kind": "priority", "priority": "urgent"}})
    check(r.status_code == 201, f"{who}: a rule may set urgent ({r.status_code} {r.text[:120]})")
    return L


# ---------------------------------------------------------------- (2) duplicate
def dup(who, s, uid, L):
    T = token(s)
    fid = s.post(B + f"/api/lists/{L}/fields", json={"name": "Budget", "type": "number"}).json()["id"]
    r = requests.post(V + "/tasks", headers=T, json={
        "list_id": L, "title": "Release notes", "notes": "Draft", "type": "bug", "points": 5, "assignee_id": uid, "priority": "urgent",
        "fields": {str(fid): 42}, "snippets": [{"lang": "py", "code": "print(1)"}]})
    check(r.status_code == 201, f"{who}: original ({r.status_code} {r.text[:160]})")
    o = r.json()
    for i in (1, 2):
        requests.post(V + "/tasks", headers=T, json={"list_id": L, "parent_id": o["id"], "title": f"Step {i}"})
    r = requests.post(V + f"/tasks/{o['id']}/duplicate", headers=T)
    check(r.status_code == 201, f"{who}: v1 duplicate 201 ({r.status_code} {r.text[:160]})")
    d = r.json()
    check(d["id"] != o["id"] and d["title"] == "Release notes" and d["notes"] == "Draft" and d["status"] == "open", f"{who}: a new open copy")
    check(d["type"] == "bug" and d["points"] == 5 and d["assignee_id"] == uid and d["priority"] == "urgent",
          f"{who}: type, points, assignee, priority {d['type']} {d['points']} {d['assignee_id']} {d['priority']}")
    check(str(d["fields"]) == str(requests.get(V + f"/tasks/{o['id']}", headers=T).json()["fields"]) and "42" in str(d["fields"]),
          f"{who}: fields {d['fields']}")
    sn = requests.get(V + f"/tasks/{d['id']}", headers=T).json().get("snippets") or []
    check([x["code"] for x in sn] == ["print(1)"], f"{who}: snippets {sn}")
    kids = [t["title"] for t in requests.get(V + "/tasks", headers=T, params={"list_id": L, "parent_id": d["id"]}).json()["data"]]
    check(sorted(kids) == ["Step 1", "Step 2"], f"{who}: subtasks come along {kids}")
    check("skipped_files" in d, f"{who}: skipped_files in the answer")
    RO = token(s, ("read",))
    check(requests.post(V + f"/tasks/{o['id']}/duplicate", headers=RO).status_code == 403, f"{who}: a read-only token 403")
    return o["id"]


prio("freelancer", F)
LA = prio("admin", A)
dup("freelancer", F, FID, prio("freelancer2", F))
TA = dup("admin", A, AID, LA)
code = requests.post(V + f"/tasks/{TA}/duplicate", headers=token(F)).status_code
check(code in (403, 404), f"someone without access to the project: {code}")
dbx("UPDATE lists SET e2e='on' WHERE id=?", (LA,))
r = requests.post(V + f"/tasks/{TA}/duplicate", headers=token(A))
check(r.status_code == 403 and "list_e2e" in r.text, f"an E2E project: 403 list_e2e (as every v1 route there) ({r.status_code} {r.text[:120]})")
dbx("UPDATE lists SET e2e=NULL WHERE id=?", (LA,))


# ---------------------------------------------------------------- (3) the admin's read-only task view
def user(u, org=None):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com",
                                       **({"orgs": [{"id": org, "role": "member"}]} if org else {})})
    assert r.ok, r.text
    s = sess(u)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
    return r.json()["id"], s


BOB, Bo = user("bob")
EVE, Ev = user("eve")
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": BOB}).json()["id"]
OTHER = A.post(B + "/api/admin/orgs", json={"name": "Beta Works", "admin_id": EVE}).json()["id"]
CAROL, Ca = user("carol", ORG)
DAVE, Da = user("dave", ORG)


def org_list(name, share=True, org=ORG):
    r = Ca.post(B + "/api/lists", json={"name": name, "kind": "project", "org_id": org})
    assert r.ok, r.text
    lid = r.json()["id"]
    if share:
        assert Ca.put(B + f"/api/lists/{lid}/members", json={"user_id": DAVE, "role": "edit"}).ok
    return lid


LS, LSOLO, LE2E, LPRIV = org_list("Launch plan"), org_list("Solo notes", share=False), org_list("Sealed"), org_list("Private shared", org=None)
check(dbx("SELECT org_id FROM lists WHERE id=?", (LS,))[0][0] == ORG and dbx("SELECT org_id FROM lists WHERE id=?", (LPRIV,))[0][0] is None,
      "setup: one project in the organisation, one private")
mk = lambda lid, t, **o: Ca.post(B + "/api/tasks", json={"title": t, "list_id": lid, **o}).json()["id"]
T1, T2 = mk(LS, "Book the venue", priority=7, assignee_id=DAVE), mk(LS, "Print flyers")
check(Ca.post(B + f"/api/tasks/{T2}/complete", json={}).ok, "setup: one task done")
TS, TE, TP = mk(LSOLO, "Diary"), mk(LE2E, "Sealed task"), mk(LPRIV, "Private task")
dbx("UPDATE lists SET e2e='on' WHERE id=?", (LE2E,))
LHEALTH = org_list("Checkups")  # 2.574.0: a shared health project of the organisation stays with its people
mk(LHEALTH, "Blood test")
dbx("UPDATE lists SET life='health' WHERE id=?", (LHEALTH,))
OT = f"/api/orgs/{ORG}/tasks"
logn = lambda: dbx("SELECT COUNT(*) FROM org_list_log WHERE org_id=? AND action IN ('tasks', 'tasksall')", (ORG,))[0][0]
check(not any(lid in (LS,) for lid in [x["id"] for x in Bo.get(B + "/api/state").json()["lists"]]), "bob is no member of the project")
n0 = logn()
r = Bo.get(B + OT)
j = r.json() if r.ok else {}
ids = [t["id"] for t in j.get("tasks", [])]
check(r.ok and ids == [T1] and j["total"] == 1 and j.get("read_only") is True, f"admin: the open task of the shared project {r.status_code} {ids}")
t1 = (j.get("tasks") or [{}])[0]
check(t1.get("title") == "Book the venue" and t1.get("priority") == 7 and t1.get("assignee_name") == "Dave" and "content" not in t1
      and t1.get("list_name") == "Launch plan", f"admin: the overview fields, no notes {t1}")
check([x["id"] for x in j.get("lists", [])] == [LS], f"admin: only the shared project of the organisation {j.get('lists')}")
check(sorted(t["id"] for t in Bo.get(B + OT, params={"status": "all"}).json()["tasks"]) == sorted([T1, T2]), "status=all: the done one too")
check([t["id"] for t in Bo.get(B + OT, params={"status": "done"}).json()["tasks"]] == [T2], "status=done")
check([t["id"] for t in Bo.get(B + OT, params={"q": "venue", "list_id": LS}).json()["tasks"]] == [T1], "search + one project")
for lid, what in ((LSOLO, "an unshared project"), (LE2E, "an encrypted project"), (LPRIV, "a private project"), (LHEALTH, "a health project")):
    check(Bo.get(B + OT, params={"list_id": lid}).status_code == 404, f"{what}: 404")
seen = str(Bo.get(B + OT, params={"status": "all"}).json())
check(all(x not in seen for x in ("Diary", "Sealed task", "Private task", "Blood test", "Checkups")), "nothing of them in the answer")
check(Bo.get(B + OT, params={"status": "x"}).status_code == 400, "a bad status: 400")
check(logn() == n0 + 5, f"every call is in the list log ({logn() - n0} of 5)")
lg = Bo.get(B + f"/api/orgs/{ORG}/lists").json()["log"]
check(any(x["action"] == "tasks" and x["list_id"] == LS and x["by"] == "Bob" for x in lg) and any(x["action"] == "tasksall" for x in lg),
      "the history of Projects of the organisation shows them")
check(Da.get(B + OT).status_code == 403, "a member who is no admin: 403")
check(Ev.get(B + OT).status_code == 404, "the admin of another organisation: 404")
check(Ca.get(B + f"/api/orgs/{OTHER}/tasks").status_code == 404, "not a member of that organisation: 404")
check(F.get(B + OT).status_code == 404, "a person without an organisation: 404")
tk = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "orghelper", "display_name": "Org Helper", "org_id": ORG})
if tk.ok and tk.json().get("token"):
    Bo.put(B + f"/api/orgs/{ORG}/members", json={"user_id": tk.json()["id"], "role": "admin"})
    ag = requests.Session()
    ag.headers.update({"Authorization": "Bearer " + tk.json()["token"], "X-Requested-With": "kalmido"})
    r = ag.get(B + OT)
    check(r.status_code in (401, 403), f"an agent (admin rights or not): refused ({r.status_code} {r.text[:120]})")  # web routes take no agent token; need_person 403 behind it
else:
    check(False, "setup: an agent " + tk.text[:160])
check(logn() == n0 + 5, "refused calls write no log row")


# ---------------------------------------------------------------- (4) two approvals
TS = "2026-11-02T10:00:00Z"
LG = org_list("Release train")
check(Ca.put(B + f"/api/lists/{LG}/members", json={"user_id": DAVE, "role": "admin"}).ok, "setup: dave is a project admin")
tk = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "gatebot", "display_name": "Gate Bot",
                                         "org_id": ORG})
GB = tk.json()["id"]
check(Ca.put(B + f"/api/lists/{LG}/members", json={"user_id": GB, "role": "edit"}).ok, "setup: the team agent in the project")
TG = mk(LG, "Ship it")


def req(kind="integrate", lid=None, tid=None, by=GB):
    sug = {"kind": kind, "state": "open", **({"source": "feat/x", "target": "main", "evidence": "tests green"} if kind == "integrate" else {}),
           **({"pr_url": "https://example.com/acme/app/pull/7", "number": 7, "repo": "acme/app"} if kind == "merge_request" else {})}
    dbx("INSERT INTO comments(task_id,user_id,body,created_at,suggestion) VALUES(?,?,?,?,?)", (tid or TG, by, "please " + kind, TS, json.dumps(sug)))
    return dbx("SELECT id FROM comments WHERE task_id=? ORDER BY id DESC LIMIT 1", (tid or TG,))[0][0]


sugg = lambda k: json.loads(dbx("SELECT suggestion FROM comments WHERE id=?", (k,))[0][0])
decide = lambda s, k, d="approve": s.post(B + f"/api/comments/{k}/decide", json={"decision": d})
react = lambda s, k, e="up", on=True: s.post(B + f"/api/comments/{k}/reactions", json={"emoji": e, "on": on})
K0 = req()
r = decide(Ca, K0)
check(r.ok and r.json()["state"] == "approved", f"switch off: one approval decides ({r.status_code} {r.text[:120]})")
check(Ca.patch(B + f"/api/lists/{LG}", json={"two_eyes": True}).ok, "the owner switches two_eyes on")
lst = next(x for x in Ca.get(B + "/api/state").json()["lists"] if x["id"] == LG)
check(lst.get("two_eyes") in (1, True), f"the list carries two_eyes {lst.get('two_eyes')}")
check(requests.get(V + f"/lists/{LG}", headers=token(Ca)).json().get("two_eyes") is True, "API v1 shows two_eyes")
K1 = req()
r = decide(Ca, K1)
check(r.ok and r.json()["state"] == "waiting" and sugg(K1)["state"] == "open" and [a["by"] for a in sugg(K1)["approvals"]] == [CAROL],
      f"first approval: waiting, still open ({r.text[:160]})")
r = decide(Ca, K1)
check(r.ok and r.json()["state"] == "waiting" and sugg(K1)["state"] == "open" and len(sugg(K1)["approvals"]) == 1,
      "the same person a second time: still open")
check(decide(Bo, K1).status_code in (403, 404) and sugg(K1)["state"] == "open", "the organisation admin outside the project is no approver (he does not see it)")
r = decide(Da, K1)
check(r.ok and r.json()["state"] == "approved" and sorted(a["by"] for a in sugg(K1)["approvals"]) == sorted([CAROL, DAVE]),
      f"a second, different approver approves ({r.text[:160]})")
K2 = req()
decide(Ca, K2)
r = decide(Da, K2, "reject")
check(r.ok and r.json()["state"] == "rejected", "a reject of the other one rejects at once")
K3 = req()
r = react(Ca, K3)
check(r.ok and r.json().get("gate") == "waiting" and r.json().get("approval") is None and sugg(K3)["state"] == "open", f"👍 by reaction: waiting {r.text[:160]}")
react(Ca, K3, on=False)
check(sugg(K3).get("approvals") == [], "the thumb taken back takes the approval back")
react(Ca, K3)
r = react(Da, K3)
check(r.ok and r.json().get("gate") == "approved" and sugg(K3)["state"] == "approved", f"the second 👍 approves {r.text[:160]}")
K4 = req("merge_request")
r = react(Ca, K4)
check(r.ok and r.json().get("merge") == "waiting" and sugg(K4)["state"] == "open", f"merge request: the first 👍 waits {r.text[:160]}")
r = react(Da, K4)
check(r.ok and r.json().get("merge") == "approved" and sugg(K4)["state"] == "approved", f"merge request: the second 👍 approves {r.text[:160]}")
# a person without an organisation, alone in the project with the own agent: the switch keeps the request open
LF = F.post(B + "/api/lists", json={"name": "Solo release", "kind": "project"}).json()["id"]
r = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot"})
FB = r.json()["id"] if r.ok else None
check(FB and F.put(B + f"/api/lists/{LF}/members", json={"user_id": FB, "role": "edit"}).ok, f"freelancer: the own agent in the project {r.text[:120]}")
TF = F.post(B + "/api/tasks", json={"title": "Solo ship", "list_id": LF}).json()["id"]
check(F.patch(B + f"/api/lists/{LF}", json={"two_eyes": True}).ok, "freelancer: may switch it on")
KF = req(tid=TF, by=FB)
r = decide(F, KF)
check(r.ok and r.json()["state"] == "waiting" and sugg(KF)["state"] == "open", f"freelancer alone: never past the first approval {r.text[:120]}")
check(F.patch(B + f"/api/lists/{LF}", json={"two_eyes": False}).ok and decide(F, KF).json()["state"] == "approved",
      "freelancer: switched off, the next approval decides")

sch = requests.get(V + "/openapi.json").json()
check("urgent" in str(sch["components"]["schemas"]), "OpenAPI: urgent in the priority enum")

sys.exit(done("p2574_d_api"))
