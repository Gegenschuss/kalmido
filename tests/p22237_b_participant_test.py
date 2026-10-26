#!/usr/bin/env python3
"""2.223.7 B (#2918 #2919): what a participant of a project sees, and agent proposals only to shared projects.
Invented people only (example.com).
freelancer-matrix: agents
 - #2918 a participant (a person and an organisation's agent) gets no notepads (web: none in the page layout, change 404;
   API: 404), no milestones (overview empty, API 404, none in /api/state), no members and no status history in the overview,
   no project files (overview / API list empty, the file itself 404, not found by the file search); the files of their own
   task stay, the file of a task of someone else does not show; a member still sees everything
 - #2919 POST /api/v1/agent/proposals: a project not shared with the agent answers 404 (also with a broken body: no
   oracle) and creates no job, so no project name reaches the agent; a shared project takes the proposal (201); a budget
   and a read-later project answer 404 even when shared -- for the organisation's agent, a personal agent and the agent of a
   person without an organisation (freelancer)
usage: p22237_b_participant_test.py <datadir>      (KMT_NOSTART=1 / P22237B_NOSTART=1: a running server)"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, login, org_join  # noqa: E402
from kt import B, DATA, check, done, fresh, setup  # noqa: E402

V = B + "/api/v1"


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def dbr(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def hdr(token):
    return {"Authorization": "Bearer " + token, "X-Requested-With": "kalmido"}


def mklist(s, name, org="keep", kind="project"):
    b = {"name": name, "kind": kind}
    if org != "keep":
        b["org_id"] = org
    r = s.post(B + "/api/lists", json=b)
    assert r.ok, r.text
    return r.json()["id"]


def task(s, lid, title, assignee=None):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid})
    assert r.ok, r.text
    tid = r.json()["id"]
    if assignee:
        r = s.patch(B + f"/api/tasks/{tid}", json={"assignee_id": assignee})
        assert r.ok, r.text
    return tid


def member(s, lid, uid, role):
    r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": role})
    if not r.ok:  # a kind of list that refuses an agent in the web app: the row as data (the server must still refuse)
        dbw("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,?,'2026-10-25T00:00:00Z') ON CONFLICT DO NOTHING",
            (lid, uid, role))
    return r.ok


fresh(prefix="P22237B")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 3})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": 1}).json()["id"]
U = {}
for u in ("bert", "carl"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123",
                                      "email": f"{u}@example.com", "orgs": [{"id": ORG, "role": "member"}]})
    assert r.ok, r.text
    U[u] = r.json()["id"]
    check(org_join(B, u, ORG), f"setup: {u} in the organisation")
Bt, Ca = login(B, "bert"), login(B, "carl")
for s in (Bt, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
SC = ["read", "tasks:write", "comments", "attachments:read"]
r = A.post(B + "/api/admin/agents", json={"username": "orgbot", "display_name": "Org Bot", "org_id": ORG, "scopes": SC})
assert r.ok, r.text
G, GH = r.json()["id"], hdr(r.json()["token"])
r = A.post(B + "/api/my/agents", json={"username": "annabot", "display_name": "Anna Bot", "org_id": "private", "scopes": SC})
assert r.ok, r.text
P, PH = r.json()["id"], hdr(r.json()["token"])
FID, Fr = freelancer(B, A)
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": SC})
assert r.ok, r.text
F, FH = r.json()["id"], hdr(r.json()["token"])

# ================================================================ #2918 a participant of a project
L1 = mklist(A, "Org project", ORG)
for uid, role in ((U["bert"], "edit"), (U["carl"], "participant"), (G, "participant")):
    check(member(A, L1, uid, role), f"setup: {uid} as {role} in the project")
TC = task(A, L1, "For Carl", U["carl"])
TG = task(A, L1, "For the bot", G)
TB = task(A, L1, "For Bert SECRETTASK", U["bert"])
r = A.post(B + f"/api/lists/{L1}/notepads", json={"title": "Internal", "body": "Salaries SECRETPAD"})
check(r.ok, "setup: a notepad " + r.text[:120])
PAD = dbr("SELECT id FROM list_notepads WHERE list_id=? ORDER BY id DESC LIMIT 1", (L1,))[0][0]
r = A.post(B + f"/api/lists/{L1}/milestones", json={"name": "Launch SECRETMS", "day": "2026-12-01"})
check(r.ok, "setup: a milestone " + r.text[:120])
r = A.post(B + f"/api/lists/{L1}/files", files={"file": ("secretplan.txt", b"plan", "text/plain")})
check(r.ok, "setup: a project file " + r.text[:120])
PF = dbr("SELECT id FROM list_files WHERE list_id=? ORDER BY id DESC LIMIT 1", (L1,))[0][0]
for tid, name in ((TC, "carlfile.txt"), (TG, "botfile.txt"), (TB, "bertfile.txt")):
    r = A.post(B + f"/api/tasks/{tid}/attachments", files={"file": (name, b"x", "text/plain")})
    check(r.ok, f"setup: attachment {name} " + r.text[:120])
r = A.post(B + f"/api/lists/{L1}/status", json={"status": "at_risk", "note": "Budget SECRETNOTE"})
check(r.ok, "setup: a status with a note " + r.text[:120])


def ov_ok(j, who, own):
    check(j.get("role") == "participant", f"{who}: the overview says participant ({j.get('role')})")
    check(j.get("milestones") == [] and j.get("files") == [] and j.get("members") == [], f"{who}: no milestones / project files / members "
          f"({len(j.get('milestones') or [])} {len(j.get('files') or [])} {len(j.get('members') or [])})")
    st = j.get("status") or {}
    check(st.get("history") == [] and st.get("current") == "at_risk", f"{who}: the current status, no history of who set it ({st})")
    names = sorted(f["name"] for f in j.get("task_files") or [])
    check(names == [own], f"{who}: only the file of their own task ({names})")
    check("SECRET" not in str({k: v for k, v in j.items() if k != "status"}), f"{who}: no secret word in the overview")


# ---- a person as participant (web routes)
r = Ca.get(B + f"/api/lists/{L1}/overview")
check(r.ok, f"carl: the overview opens ({r.status_code})")
if r.ok:
    ov_ok(r.json(), "carl", "carlfile.txt")
    check((r.json().get("layout") or {}).get("pads") == [], "carl: no notepads in the page layout")
r = Ca.get(B + f"/api/lists/{L1}/layout")
check(r.ok and r.json().get("pads") == [], f"carl: the layout route has no notepads ({r.status_code})")
check(Ca.patch(B + f"/api/notepads/{PAD}", json={"title": "x"}).status_code == 404, "carl: changing the notepad: 404")
check(Ca.post(B + f"/api/lists/{L1}/notepads", json={"title": "x"}).status_code == 404, "carl: a new notepad: 404")
check(Ca.get(B + f"/api/list-files/{PF}").status_code == 404, "carl: the project file itself: 404")
r = Ca.get(B + "/api/files/search", params={"q": "secretplan"})
check(r.ok and not r.json().get("list_files"), f"carl: the file search does not find the project file ({r.status_code} {r.text[:120]})")
st = Ca.get(B + "/api/state").json()
l1 = next((x for x in st.get("lists", []) if x["id"] == L1), {})
check(l1 and not l1.get("milestones"), f"carl: no milestones of the project in /api/state ({l1.get('milestones')})")
# ---- the member keeps everything
r = Bt.get(B + f"/api/lists/{L1}/overview")
j = r.json() if r.ok else {}
check(len(j.get("milestones") or []) == 1 and len(j.get("files") or []) == 1 and len(j.get("members") or []) >= 3
      and len(j.get("task_files") or []) == 3 and (j.get("layout") or {}).get("pads"), f"bert (member): the full overview ({r.status_code})")
check(Bt.get(B + f"/api/list-files/{PF}").status_code != 404, "bert: the project file opens")
r = Bt.get(B + "/api/files/search", params={"q": "secretplan"})
check(r.ok and len(r.json().get("list_files") or []) == 1, "bert: the file search finds it")
# ---- the organisation's agent as participant (token API)
r = requests.get(V + f"/lists/{L1}/overview", headers=GH)
check(r.ok, f"agent: the overview opens ({r.status_code} {r.text[:120]})")
if r.ok:
    ov_ok(r.json(), "agent", "botfile.txt")
r = requests.get(V + f"/lists/{L1}/notepads", headers=GH)
check(r.status_code == 404 and "SECRET" not in r.text, f"agent: the notepads 404 ({r.status_code})")
check(requests.get(V + f"/lists/{L1}/weekly-status", headers=GH).status_code == 404, "agent: the weekly status 404")
check(requests.get(V + f"/lists/{L1}/milestones", headers=GH).status_code == 404, "agent: the milestones 404")
r = requests.get(V + f"/lists/{L1}/files", headers=GH)
check(r.ok and r.json().get("data") == [], f"agent: the project file list is empty ({r.status_code} {r.text[:120]})")
r = requests.get(V + f"/lists/{L1}/files/{PF}", headers=GH)
check(r.status_code == 404, f"agent: the project file itself 404 ({r.status_code})")
check(requests.get(V + f"/lists/{L1}/links", headers=GH).ok, "agent: the key links stay (not decided otherwise)")
# ---- an agent as member still reads the notepads
L1b = mklist(A, "Org project 2", ORG)
member(A, L1b, G, "edit")
A.post(B + f"/api/lists/{L1b}/notepads", json={"title": "Open", "body": "for the team"})
r = requests.get(V + f"/lists/{L1b}/notepads", headers=GH)
check(r.ok and len(r.json().get("data") or []) == 1, f"agent as member: the notepad reads ({r.status_code})")

# ================================================================ #2919 proposals only to shared projects
BODY = {"title": "Idea", "reason": "Seen elsewhere", "tasks": [{"title": "Do it"}]}


def prop(h, lid, body=BODY):
    return requests.post(V + "/agent/proposals", headers=h, json={**body, "list_id": lid})


def jobs_of(aid):
    return dbr("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND kind='extract'", (aid,))[0][0]


L2 = mklist(A, "Org SECRETORG", ORG)
LP1 = mklist(A, "Private shared", None)
LP2 = mklist(A, "Private SECRETPRIV", None)
member(A, LP1, P, "edit")
LF1 = mklist(Fr, "Frida shared")
LF2 = mklist(Fr, "Frida SECRETFRIDA")
member(Fr, LF1, F, "edit")
LBU = mklist(A, "Budget", ORG, kind="list")
dbw("UPDATE lists SET life='budget' WHERE id=?", (LBU,))
member(A, LBU, G, "edit")
LRD = mklist(A, "Read later", None, kind="list")
dbw("UPDATE lists SET life='reading' WHERE id=?", (LRD,))
member(A, LRD, P, "edit")
for who, h, aid, shared, secret in (("org agent", GH, G, L1b, L2), ("personal agent", PH, P, LP1, LP2), ("freelancer agent", FH, F, LF1, LF2)):
    n0 = jobs_of(aid)
    r = prop(h, secret)
    check(r.status_code == 404 and "SECRET" not in r.text, f"{who}: a project not shared with it: 404 ({r.status_code} {r.text[:120]})")
    r = prop(h, secret, {"title": "", "tasks": "x"})
    check(r.status_code == 404, f"{who}: a broken body to it: 404 as well, no oracle ({r.status_code})")
    r2 = prop(h, 999999, {"title": "", "tasks": "x"})
    check(r2.status_code == 404 and r2.json() == r.json(), f"{who}: same answer as a missing project")
    check(jobs_of(aid) == n0, f"{who}: no job was created")
    r = prop(h, shared)
    check(r.status_code == 201, f"{who}: a shared project takes the proposal ({r.status_code} {r.text[:150]})")
    if r.status_code == 201:
        jr = requests.get(V + f"/agent/jobs/{r.json()['id']}", headers=h)
        check("SECRET" not in jr.text, f"{who}: the job names no secret project")
    check(prop(h, shared, {"title": "", "tasks": "x"}).status_code == 400, f"{who}: a shared project validates the body (400)")
r = prop(GH, LBU)
check(r.status_code == 404, f"org agent: a budget shared with it: 404 ({r.status_code} {r.text[:120]})")
r = prop(PH, LRD)
check(r.status_code == 404, f"personal agent: a read-later project shared with it: 404 ({r.status_code} {r.text[:120]})")
check(prop(PH, L1).status_code == 404, "personal agent: an organisation's project of its owner, not shared: 404")
check(prop(FH, L1).status_code == 404, "freelancer agent: someone else's project: 404")

sys.exit(done("p22237_b_participant"))
