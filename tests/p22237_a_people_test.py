#!/usr/bin/env python3
"""2.223.7 A (#2917, #2941): an agent sees only the people of the projects shared with it (and who owns / manages it), not
the whole organisation - and on a server without any organisation not everyone. Invented names only.
freelancer-matrix: agents
Setup like audit I: organisation (Anna admin, Bert, Carl), Frida without an organisation; team agent G (only L1 with Bert
shared), Anna's private agent P (only Lp1), Frida's freelancer agent F (only Lf1).
 - GET /api/v1/groups and /groups/{id}: the agent knows no group of the organisation it is not in (Carl's name never shows)
 - GET /api/v1/absences: Bert (shares L1) in people / items, Carl (shares nothing) not; a person (Anna) still sees Carl
 - a mention <@carl> by the agent becomes '@?', no News for Carl; <@bert> stays
 - event attendees: Carl is an unknown user (400), Bert works (201)
 - PUT /api/v1/lists/{own}/members/{carl}: 404 without a waiting job naming Carl; Bert: 202 approval
 - private agent P and freelancer agent F: their owner and the people of their projects only
 - #2941: a server without organisations: a person sees everyone (household), an agent only its owner / projects
usage: p22237_a_people_test.py <datadir>"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, H, check, sess  # noqa: E402

V = B + "/api/v1"
MODS = ("cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,comments,events,contacts,files,docs,"
        "agents,team,dispo,notes,sheets,office")
SCOPES = ["read", "tasks:write", "comments", "structure", "calendar"]
D = "2026-11-16"


def first(name):
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "anna", "display_name": "Anna Admin", "password": kt.PASSWORD}).ok
    a = sess("anna")
    b = {"lang": "en", "collab_all": True, "modules": MODS.split(",")}
    if name:
        b["org_name"] = name
    r = a.post(B + "/api/admin/setup", json=b)
    assert r.ok, r.text
    a.patch(B + "/api/settings", json={"lang": "en"})
    assert a.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 3}).ok
    return a


def person(a, name, orgs):
    r = a.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": kt.PASSWORD,
                                       "email": f"{name}@example.com", "orgs": orgs})
    assert r.ok, r.text
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "features": MODS})
    return r.json()["id"], s


def ahead(tok):
    return {"Authorization": "Bearer " + tok, **H}


def events_on(aid):
    kt.dbx("INSERT INTO user_settings(user_id,key,value) VALUES(?,'features',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
           (aid, MODS))  # the agent's own module switches: events on


def mklist(s, name, org=None):
    b = {"name": name}
    if org is not None:
        b["org_id"] = org
    r = s.post(B + "/api/lists", json=b)
    assert r.ok, r.text
    return r.json()["id"]


def share(s, lid, uid, role="edit", **kw):
    r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": role, **kw})
    assert r.ok, r.text


def mention(h, lid, who, tag):
    """The agent comments '<@who>' on a new task of lid -> (stored body, News count of who before, after)."""
    t = requests.post(V + "/tasks", headers=h, json={"title": f"mention {tag}", "list_id": lid})
    assert t.ok, t.text
    n0 = kt.dbx("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='mention'", (who,))[0][0]
    r = requests.post(V + f"/tasks/{t.json()['id']}/comments", headers=h, json={"body": f"hello <@{who}> {tag}"})
    assert r.ok, r.text
    body = kt.dbx("SELECT body FROM comments WHERE task_id=? ORDER BY id DESC LIMIT 1", (t.json()["id"],))[0][0]
    return body, n0, kt.dbx("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='mention'", (who,))[0][0]


def attendee(h, uid, tag):
    return requests.post(V + "/events", headers=h, json={"title": f"Meet {tag}", "start": f"{D}T10:00", "end": f"{D}T11:00",
                                                         "attendees": [{"user_id": uid}]})


# ======================================================================== an organisation
kt.fresh(prefix="P22237A")
A = first("Testorg")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ANNA = A.get(B + "/api/state").json()["me"]["id"]
BERT, Be = person(A, "bert", [{"id": ORG, "role": "member"}])
CARL, Ca = person(A, "carl", [{"id": ORG, "role": "member"}])
FRIDA, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": MODS})

r = A.post(B + "/api/admin/agents", json={"username": "orgbot", "display_name": "Org Bot", "org_id": ORG, "scopes": SCOPES})
assert r.ok, r.text
G, GH = r.json()["id"], ahead(r.json()["token"])
r = A.post(B + "/api/my/agents", json={"username": "annabot", "display_name": "Annas Bot", "org_id": "private", "scopes": SCOPES})
assert r.ok, r.text
P, PH = r.json()["id"], ahead(r.json()["token"])
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridas Bot", "scopes": SCOPES})
assert r.ok, r.text
F, FH = r.json()["id"], ahead(r.json()["token"])
for x in (G, P, F):
    events_on(x)

L1 = mklist(A, "Org shared", ORG)
share(A, L1, G)
share(A, L1, BERT)
mklist(Ca, "Carl alone", ORG)
LP1 = mklist(A, "Private shared", "private")
share(A, LP1, P)
LF1 = mklist(Fr, "Frida shared")
share(Fr, LF1, F)
GRP = A.post(B + "/api/admin/groups", json={"name": "Leadership", "members": [BERT, CARL]}).json()["id"]
for s in (Be, Ca):
    r = s.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": D, "end_date": "2026-11-18"})
    check(r.status_code == 201 and r.json().get("status") == "approved", f"setup: vacation ({r.status_code} {r.text[:120]})")

# ---- groups
r = requests.get(V + "/groups", headers=GH)
check(r.ok and not any(x["id"] == GRP for x in r.json()["data"]) and "Carl" not in r.text,
      f"#2917: the team agent does not list a group of the organisation it is not in ({r.text[:200]})")
r = requests.get(V + f"/groups/{GRP}", headers=GH)
check(r.status_code == 404 and "Carl" not in r.text, f"#2917: GET /groups/{{id}} of such a group: 404 ({r.status_code})")
r = requests.get(V + "/groups", headers=PH)
check(r.ok and not any(x["id"] == GRP for x in r.json()["data"]), "#2917: the private agent neither")
g_ = next((x for x in A.get(B + "/api/groups").json()["groups"] if x["id"] == GRP), {})
check({m["user_id"] for m in g_.get("members", [])} == {BERT, CARL}, "#2917: Anna (a person) still sees the group with both")

# ---- absences
q = {"start": "2026-11-01", "end": "2026-11-30"}
r = requests.get(V + "/absences", headers=GH, params=q)
j = r.json() if r.ok else {}
pp = {p["id"] for p in j.get("people", [])}
it = {x["user_id"] for x in j.get("items", [])}
check(r.ok and BERT in pp and BERT in it, f"#2917: the agent sees Bert (shares L1) away ({r.text[:200]})")
check(r.ok and CARL not in pp and CARL not in it and "Carl" not in r.text, f"#2917: never Carl (shares nothing with it) ({r.text[:200]})")
check(ANNA in pp, "#2917: the admin who manages the team agent is visible")
r = A.get(B + "/api/team/absences", params=q)
check(r.ok and any(x["user_id"] == CARL for x in r.json()["items"]), "#2917: Anna (a person) still sees Carl away")
check(requests.get(V + "/absences", headers=PH, params=q).status_code == 404, "the private agent: 404 as before")

# ---- mentions
body, n0, n1 = mention(GH, L1, CARL, "c")
check("@?" in body and "Carl" not in body and f"<@{CARL}>" not in body and n1 == n0, f"#2917: <@carl> by the agent: '@?', no News ({body})")
body, n0, n1 = mention(GH, L1, BERT, "b")
check(f"<@{BERT}>" in body and n1 == n0 + 1, f"#2917: <@bert> stays a mention with News ({body})")
body, _, _ = mention(PH, LP1, BERT, "p")
check("@?" in body and "Bert" not in body, f"#2917: the private agent: Bert (not in Lp1) is '@?' ({body})")
body, n0, n1 = mention(PH, LP1, ANNA, "o")
check(f"<@{ANNA}>" in body, f"#2917: the private agent mentions its owner ({body})")

# ---- event attendees
r = attendee(GH, CARL, "c")
check(r.status_code == 400 and "Carl" not in r.text, f"#2917: Carl as attendee: unknown user 400 ({r.status_code} {r.text[:120]})")
r = attendee(GH, BERT, "b")
check(r.status_code == 201, f"#2917: Bert as attendee: 201 ({r.status_code} {r.text[:120]})")
check(attendee(PH, CARL, "pc").status_code == 400, "#2917: the private agent: Carl unknown")
check(attendee(PH, ANNA, "pa").status_code == 201, "#2917: the private agent invites its owner")

# ---- share requests (approval job titles)
GL = requests.post(V + "/lists", headers=GH, json={"name": "Agent own"}).json()["id"]
jobs = lambda: kt.dbx("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=?", (G,))[0][0]  # noqa: E731
n0 = jobs()
r = requests.put(V + f"/lists/{GL}/members/{CARL}", headers=GH, json={"role": "view"})
check(r.status_code == 404 and jobs() == n0 and "Carl" not in r.text, f"#2917: sharing with Carl: 404, no job naming him ({r.status_code})")
r = requests.put(V + f"/lists/{GL}/members/{BERT}", headers=GH, json={"role": "view"})
check(r.status_code == 202 and "Bert" in r.json().get("job", {}).get("title", ""), f"#2917: Bert still waits for approval ({r.status_code})")

# ---- 2.223.7 review (#2918): the team agent as a participant sees the owner, not every member of the project
L3 = mklist(A, "Participant project", ORG)
share(A, L3, G, "participant", bridge_ok=True)  # 2.30.0 (#919): L1 and L3 have different people
share(A, L3, CARL, "edit", bridge_ok=True)
r = attendee(GH, CARL, "p3")
check(r.status_code == 400 and "Carl" not in r.text, f"#2918: participant without a task: Carl (member of L3) stays unknown ({r.status_code})")
r = requests.get(V + "/absences", headers=GH, params=q)
check(r.ok and CARL not in {p["id"] for p in r.json().get("people", [])}, "#2918: nor in /absences")
t3 = A.post(B + "/api/tasks", json={"title": "for the bot", "list_id": L3}).json()["id"]
assert A.patch(B + f"/api/tasks/{t3}", json={"assignee_id": G}).ok
check(attendee(GH, CARL, "p4").status_code == 201, "#2918: with a task of its own the full members of L3 are visible (like people)")

# ---- the freelancer's agent (freelancer-matrix: agents)
body, _, _ = mention(FH, LF1, FRIDA, "f")
check(f"<@{FRIDA}>" in body, f"freelancer agent mentions its owner ({body})")
body, _, _ = mention(FH, LF1, CARL, "fc")
check("@?" in body and "Carl" not in body, f"freelancer agent: Carl is '@?' ({body})")
check(attendee(FH, FRIDA, "ff").status_code == 201 and attendee(FH, CARL, "fc").status_code == 400, "freelancer agent: owner yes, Carl no")
check(not any(x["id"] == GRP for x in requests.get(V + "/groups", headers=FH).json()["data"]), "freelancer agent: no group of the org")

# ======================================================================== #2941: a server without any organisation
if not kt.nostart("P22237A"):
    kt.fresh()
    A = first(None)
    check(not A.get(B + "/api/state").json()["me"].get("workspaces"), "setup: no organisation")
    ANNA = A.get(B + "/api/state").json()["me"]["id"]
    BERT, Be = person(A, "bert", [])
    CARL, Ca = person(A, "carl", [])
    r = A.post(B + "/api/my/agents", json={"username": "annabot", "display_name": "Annas Bot", "scopes": SCOPES})
    assert r.ok, r.text
    P, PH = r.json()["id"], ahead(r.json()["token"])
    events_on(P)
    LP = mklist(A, "Home shared")
    share(A, LP, P)
    share(A, LP, BERT)
    check(attendee(PH, CARL, "hc").status_code == 400, "#2941: no organisation: the agent does not see everyone (Carl unknown)")
    check(attendee(PH, BERT, "hb").status_code == 201, "#2941: Bert (shares the project) works")
    body, _, _ = mention(PH, LP, CARL, "h")
    check("@?" in body and "Carl" not in body, f"#2941: <@carl> by the agent: '@?' ({body})")
    r = A.post(B + "/api/events", json={"title": "Family", "start": f"{D}T12:00", "end": f"{D}T13:00", "attendees": [{"user_id": CARL}]})
    check(r.ok, f"#2941: a person still sees everyone on a household server ({r.status_code} {r.text[:120]})")
    check(any(u["id"] == CARL for u in A.get(B + "/api/users").json()["users"]), "#2941: Anna lists Carl")

sys.exit(kt.done("p22237_a_people"))
