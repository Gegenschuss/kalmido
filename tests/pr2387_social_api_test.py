#!/usr/bin/env python3
# kalmido-suite:
"""2.387.0 API tests (#1957: the project type "Social media plan"), own container (start.sh). Invented data only.
 - the type: kind project, view calendar, the field Channel (several values: Instagram ... Newsletter, Other), the modules
   calendar / Kanban / custom fields switched on for the creator; tickets, repository, dependencies and points hidden
 - with the standard sections: Idea, Draft, For approval, Approved, Scheduled, Published (in the creator's language) and the
   review step on that section with "done only after approval", no default reviewer; without them no review step
 - the client as reviewer (a member with the role View): moving a post into For approval asks them, completing is refused
   until they approve, after the approval it completes; Channel takes several values
 - API v1 POST /lists {project_type: social, sections: true} makes the same; an unknown type stays 400
 - a type change to social only offers the field (with its options), adds nothing
P4: a person without an organisation gets the same, in German (freelancer-matrix: lists)
usage: pr2387_social_api_test.py <datadir>"""
import json
import sys

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

kt.fresh(prefix="PR2387")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en"})
V = B + "/api/v1"
SECS = {"en": ["Idea", "Draft", "For approval", "Approved", "Scheduled", "Published"],
        "de": ["Idee", "Entwurf", "Zur Freigabe", "Freigegeben", "Geplant", "Veröffentlicht"]}
CH = {"en": ("Channel", "Other"), "de": ("Kanal", "Sonstiges")}
NETS = ["Instagram", "LinkedIn", "Facebook", "TikTok", "YouTube", "Newsletter"]


def state(s):
    return s.get(B + "/api/state").json()


def lrow(s, lid):
    return next(x for x in state(s)["lists"] if x["id"] == lid)


def fields(s, lid):
    return {f["name"]: f for f in state(s)["fields"] if f["list_id"] == lid}


def sections(s, lid):
    return sorted((x for x in state(s)["sections"] if x["list_id"] == lid), key=lambda x: (x["sort"], x["id"]))


def task(s, tid):
    return s.get(B + f"/api/tasks/{tid}").json()


def cfg(s, lid):
    v = lrow(s, lid).get("review_cfg") or ""
    return json.loads(v) if v else {}


n = 0


def case(s, who, lg, client):
    global n
    n += 1
    ch, other = CH[lg]
    # without the standard sections: type, view, field, modules; no review step
    j = s.post(B + "/api/lists", json={"name": f"Posts {n}", "ptype": "social"})
    check(j.ok, f"{who}: a social media plan is made {j.status_code} {j.text[:160]}")
    lid = j.json()["id"]
    x = lrow(s, lid)
    check(x["ptype"] == "social" and x["kind"] == "project" and x["view"] == "calendar", f"{who}: type social, a project, calendar view {x['ptype'], x['kind'], x['view']}")
    f = fields(s, lid)
    check(list(f) == [ch], f"{who}: the type brings only {ch} {list(f)}")
    fc = f[ch]
    names = [o["name"] for o in fc["options"]["options"]]
    check(fc["type"] == "multiselect" and fc["pinned"] == 1 and names == [*NETS, other], f"{who}: {ch} = several values of the networks + {other} {fc['type'], names}")
    check(not sections(s, lid) and not cfg(s, lid), f"{who}: without the standard sections no sections, no review step")
    feats = (state(s)["settings"].get("features") or "").split(",")
    check(all(m in feats for m in ("cal", "kanban", "fields")), f"{who}: calendar, Kanban and custom fields are on {feats}")

    # with them: the six sections and the review step on For approval
    lid = s.post(B + "/api/lists", json={"name": f"Client posts {n}", "ptype": "social", "sections": True}).json()["id"]
    secs = sections(s, lid)
    check([x["name"] for x in secs] == SECS[lg], f"{who}: the standard sections {[x['name'] for x in secs]}")
    S = {x["name"]: x["id"] for x in secs}
    rv = cfg(s, lid)
    check(rv.get("on") and rv.get("section") == S[SECS[lg][2]] and rv.get("gate") and rv.get("reviewer") is None,
          f"{who}: review step on {SECS[lg][2]}, done only after approval, no default reviewer {rv}")

    # the client as reviewer (role View)
    check(s.put(B + f"/api/lists/{lid}/members", json={"user_id": client[0], "role": "view"}).ok, f"{who}: the client joins with View")
    r = s.put(B + f"/api/lists/{lid}/review", json={"on": True, "reviewer": client[0], "section": S[SECS[lg][2]], "gate": True})
    check(r.ok, f"{who}: the client is the default reviewer {r.status_code} {r.text[:160]}")
    fid = str(fields(s, lid)[ch]["id"])
    t = s.post(B + "/api/tasks", json={"title": "Launch post", "list_id": lid, "section_id": S[SECS[lg][1]], "due": "2030-05-04",
                                        "notes": "Our new product is here.", "fields": {fid: ["instagram", "linkedin"]}}).json()
    x = task(s, t["id"])
    check(sorted((x["fields"].get(fid) or "").split(",")) == ["instagram", "linkedin"] and x["due"] == "2030-05-04", f"{who}: a post with two channels and its day {x['fields'], x['due']}")
    r = s.patch(B + f"/api/tasks/{t['id']}", json={"section_id": S[SECS[lg][2]]})
    x = task(s, t["id"])
    check(r.ok and x["review"] == "pending" and x["reviewer_id"] == client[0], f"{who}: into {SECS[lg][2]} = the client is asked {x['review'], x['reviewer_id']}")
    r = s.post(B + f"/api/tasks/{t['id']}/complete")
    check(r.status_code == 409 and task(s, t["id"])["status"] == 0, f"{who}: not done before the approval {r.status_code}")
    r = client[1].post(B + f"/api/tasks/{t['id']}/review", json={"action": "approve"})
    check(r.ok and task(s, t["id"])["review"] == "approved", f"{who}: the client approves {r.status_code} {r.text[:160]}")
    r = s.patch(B + f"/api/tasks/{t['id']}", json={"section_id": S[SECS[lg][5]]})
    r2 = s.post(B + f"/api/tasks/{t['id']}/complete")
    x = task(s, t["id"])
    check(r.ok and r2.ok and x["status"] != 0 and x["section_id"] == S[SECS[lg][5]], f"{who}: published by hand and done {r.status_code} {r2.status_code} {x['status']}")

    # a type change only offers the field
    o = s.post(B + "/api/lists", json={"name": f"Older {n}"}).json()
    r = s.patch(B + f"/api/lists/{o['id']}", json={"ptype": "social"})
    miss = r.json().get("ptype_missing", {})
    check(r.ok and [x["name"] for x in miss.get("fields", [])] == [ch] and len(miss["fields"][0]["options"]["options"]) == 7
          and miss.get("sections") == SECS[lg], f"{who}: the type change offers field + sections {miss}")
    check(not fields(s, o["id"]) and not sections(s, o["id"]), f"{who}: the type change adds nothing")


BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Client", "password": "password123", "email": "bob@example.com"}).json()["id"]
Bo = sess("bob")
case(A, "alice", "en", (BOB, Bo))
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"lang": "de"})
case(Fr, "frida (no organisation)", "de", (BOB, Bo))

# API v1
r = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "structure"]})
assert r.status_code == 201, r.text
PH = {"Authorization": "Bearer " + r.json()["token"]}
r = sess().post(V + "/lists", headers=PH, json={"name": "Token posts", "project_type": "social", "sections": True})
check(r.status_code == 201, f"v1: project_type social {r.status_code} {r.text[:160]}")
if r.status_code == 201:
    lid = r.json()["id"]
    x = sess().get(V + f"/lists/{lid}", headers=PH).json()
    check(x.get("project_type") == "social" and [s["name"] for s in sections(A, lid)] == SECS["en"] and cfg(A, lid).get("gate"),
          f"v1: the same project {x.get('project_type')}")
r = sess().post(V + "/lists", headers=PH, json={"name": "Bad", "project_type": "socials"})
check(r.status_code == 400, f"v1: an unknown type = 400 {r.status_code}")

sys.exit(kt.done("pr2387_social_api"))
