#!/usr/bin/env python3
"""2.467.0 B (#2586): free / busy for agents, GET /api/v1/events/freebusy (MCP freebusy). Invented names only.
 - without the permission calendar: 403 with required_scope; the web route stays closed to a token
 - a team agent: only people shared with it (its projects, who manages it), full members of its workspace; never a title
 - freebusy_share applies: org = the workspace's sources, all = private ones too, off = left out
 - neither a stranger, a shared guest, a person outside the workspace, itself nor an id that does not exist shows in the answer
 - a personal agent: its owner's whole bar, also with off; a freelancer's agent alike (freelancer-matrix: pim)
 - a person's token answers like the web app; the limit counts per account
usage: p2467_b_freebusy_test.py"""
# kalmido-suite: fresh
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, H, check, sess  # noqa: E402

V = B + "/api/v1"
MODS = "cal,comments,collab,events,contacts,files,agents,team"
SCOPES = ["read", "tasks:write", "calendar"]
D, TZ, SECRET = "2026-11-16", "Europe/Berlin", "Geheimtermin"
EFB_RATE = 120  # kalmido/events/freebusy.py
NOBODY = 987654


def ahead(tok):
    return {"Authorization": "Bearer " + tok, **H}


def fb(h, users):
    return requests.get(V + "/events/freebusy", headers=h, params={"day": D, "users": ",".join(str(u) for u in users), "tz": TZ})


def people(h, users):
    r = fb(h, users)
    check(r.status_code == 200, f"freebusy answers 200, not {r.status_code}: {r.text[:200]}")
    check(SECRET not in r.text and "title" not in r.text and "location" not in r.text, "never a title or a place")
    return {p["user_id"]: [(x["start"], x["end"], x["kind"]) for x in p["slots"]] for p in r.json().get("people", [])}


def person(a, name, orgs):
    r = a.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": kt.PASSWORD,
                                       "email": f"{name}@example.com", "orgs": orgs})
    assert r.ok, r.text
    s = sess(name)
    assert s.patch(B + "/api/settings", json={"lang": "en", "features": MODS}).ok
    return r.json()["id"], s


def events_on(aid):
    kt.dbx("INSERT INTO user_settings(user_id,key,value) VALUES(?,'features',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
           (aid, MODS))


def agent(s, path, name, scopes=None, **kw):
    r = s.post(B + path, json={"username": name, "display_name": name.title(), "scopes": scopes or SCOPES, **kw})
    assert r.ok, r.text
    events_on(r.json()["id"])
    return r.json()["id"], ahead(r.json()["token"])


def cal_event(s, org, a, b):
    r = s.post(B + "/api/evcals", json={"name": "Kalender", "org_id": org})
    assert r.status_code in (200, 201), r.text
    r = s.post(B + "/api/events", json={"cal_id": r.json()["id"], "title": SECRET, "location": SECRET, "start": f"{D}T{a}", "end": f"{D}T{b}", "tz": TZ})
    assert r.status_code == 201, r.text


def mklist(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, **({"org_id": org} if org else {})})
    assert r.ok, r.text
    return r.json()["id"]


def share(s, lid, uid):
    r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": uid, "role": "edit"})
    assert r.ok, r.text


kt.fresh()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "anna", "display_name": "Anna Admin", "password": kt.PASSWORD}).ok
A = sess("anna")
assert A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "org_name": "Testorg", "modules": MODS.split(",")}).ok
assert A.patch(B + "/api/settings", json={"lang": "en", "features": MODS}).ok
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 3}).ok
me = A.get(B + "/api/state").json()["me"]
ANNA, ORG = me["id"], me["workspaces"][0]["id"]
BERT, Be = person(A, "bert", [{"id": ORG, "role": "member"}])
CARL, Ca = person(A, "carl", [{"id": ORG, "role": "member"}])
GINA, Gi = person(A, "gina", [{"id": ORG, "role": "guest"}])
FRIDA, Fr = freelancer(B, A, features=MODS)

PRIV, ORGAN = ("08:00", "09:00", "busy"), ("10:00", "11:00", "busy")
cal_event(Be, None, "08:00", "09:00")
cal_event(Be, ORG, "10:00", "11:00")
cal_event(Ca, ORG, "12:00", "13:00")
cal_event(A, None, "14:00", "15:00")
cal_event(Fr, None, "09:00", "09:30")

G, GH = agent(A, "/api/admin/agents", "orgbot", org_id=ORG)
G2, G2H = agent(A, "/api/admin/agents", "lonebot", org_id=ORG)
RO, ROH = agent(A, "/api/admin/agents", "readbot", scopes=["read"], org_id=ORG)
P, PH = agent(A, "/api/my/agents", "annabot", org_id="private")
L = mklist(A, "Projekt", ORG)
for x in (G, BERT, GINA):
    share(A, L, x)
LP = mklist(A, "Privat", "private")
for x in (P, BERT):
    share(A, LP, x)

# ---- the permission calendar
r = fb(ROH, [BERT])
check(r.status_code == 403 and r.json().get("error", {}).get("required_scope") == "calendar", f"without calendar: 403 required_scope {r.text[:200]}")
r = requests.get(B + "/api/events/freebusy", headers=GH, params={"day": D, "users": BERT})
check(r.status_code in (401, 403), f"the web route stays closed to a token ({r.status_code})")

# ---- a team agent: only the people shared with it
got = people(GH, [BERT, CARL, G, RO, GINA, FRIDA, NOBODY])
check(got == {BERT: [ORGAN]}, f"team agent: bert with the workspace's calendar only; not a stranger, itself, an agent, a guest or a person outside ({got})")
check(people(GH, [ANNA]) == {ANNA: []}, "team agent: who manages it counts, her private calendar stays out")
check(fb(GH, [CARL]).json() == fb(GH, [NOBODY]).json(), "a stranger looks like an id that does not exist")
check(people(G2H, [BERT, CARL, FRIDA]) == {}, "an agent with nobody shared: empty, 200")

# ---- freebusy_share of the person asked about
assert Be.patch(B + "/api/settings", json={"freebusy_share": "all"}).ok
check(people(GH, [BERT]) == {BERT: [PRIV, ORGAN]}, "all: bert's private calendar too")
check(people(GH, [CARL, FRIDA]) == {}, "all does not open the people who are not shared")
assert Be.patch(B + "/api/settings", json={"freebusy_share": "off"}).ok
check(people(GH, [BERT]) == {}, "off: left out like a stranger")
assert Be.patch(B + "/api/settings", json={"freebusy_share": "org"}).ok
check(people(GH, [BERT]) == {BERT: [ORGAN]}, "back to org")

# ---- a personal agent: its owner is "oneself"
check(people(PH, [ANNA, CARL]) == {ANNA: [("14:00", "15:00", "busy")]}, "personal agent: the owner's private calendar, not a stranger")
assert A.patch(B + "/api/settings", json={"freebusy_share": "off"}).ok
check(ANNA in people(PH, [ANNA]), "personal agent: off is about colleagues, not about the owner's own agent")
check(people(GH, [ANNA]) == {}, "off holds for the team agent")
assert A.patch(B + "/api/settings", json={"freebusy_share": "org"}).ok
assert Be.patch(B + "/api/settings", json={"freebusy_share": "all"}).ok
check(people(PH, [BERT]) == {}, "an agent without a workspace: a shared person stays out, even with all")
assert Be.patch(B + "/api/settings", json={"freebusy_share": "org"}).ok

# ---- a person without an organisation (P4)
F, FH = agent(Fr, "/api/my/agents", "fridabot")
got = people(FH, [FRIDA, BERT, ANNA])
check(got == {FRIDA: [("09:00", "09:30", "busy")]}, f"the freelancer's agent: only its owner ({got})")
r = Fr.post(B + "/api/me/tokens", json={"name": "fb", "scopes": ["read", "calendar"]})
assert r.ok, r.text
check(people(ahead(r.json()["token"]), [FRIDA, BERT]) == {FRIDA: [("09:00", "09:30", "busy")]}, "the freelancer's token: her own bar")

# ---- a person's token answers like the web app
r = Be.post(B + "/api/me/tokens", json={"name": "fb", "scopes": ["read", "calendar"]})
assert r.ok, r.text
check(people(ahead(r.json()["token"]), [BERT, CARL]) == {BERT: [PRIV, ORGAN], CARL: [("12:00", "13:00", "busy")]}, "a person's token: oneself + colleague")

# ---- review: a token limited to some projects answers only for their people (and oneself, an agent's owner)
LB = mklist(Be, "Nur Bert", ORG)
r = Be.post(B + "/api/me/tokens", json={"name": "fb2", "scopes": ["read", "calendar"], "list_ids": [LB]})
assert r.ok, r.text
TH = ahead(r.json()["token"])
check(set(people(TH, [BERT, CARL])) == {BERT}, "a token limited to a project: not the colleague outside it")
share(Be, LB, CARL)
check(set(people(TH, [BERT, CARL])) == {BERT, CARL}, "a token limited to a project: its people")
LA = mklist(A, "Agentenprojekt", ORG)
A2, A2H = agent(A, "/api/admin/agents", "limitbot", org_id=ORG)
LC = mklist(A, "Anderes Projekt", ORG)
for x in (A2, BERT):
    share(A, LC, x)
share(A, LA, A2)
check(BERT in people(A2H, [BERT]), "an agent without a limit: the people of its projects")
kt.dbx("UPDATE api_tokens SET list_ids=? WHERE user_id=?", (str(LA), A2))
check(BERT not in people(A2H, [BERT]), "an agent limited to a project: not the people of its other projects")

# ---- bad input and the limit per account
check(requests.get(V + "/events/freebusy", headers=GH, params={"day": "x", "users": BERT}).status_code == 400, "a bad day: 400")
check(requests.get(V + "/events/freebusy", headers=GH, params={"day": D, "users": BERT, "x": 1}).status_code == 400, "an unknown parameter: 400")
codes = [fb(GH, [BERT]).status_code for _ in range(EFB_RATE + 2)]
check(429 in codes, f"429 after about {EFB_RATE} answers a minute ({sorted(set(codes))})")
check(fb(G2H, [BERT]).ok, "another agent is not limited by it")

sys.exit(kt.done("p2467_b_freebusy"))
