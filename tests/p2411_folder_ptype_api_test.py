#!/usr/bin/env python3
# kalmido-suite:
"""2.411.0 API tests (#3516: a new list in a folder takes the folder's project type), own container (start.sh). Invented data only.
 - the folder default "Project type" (PUT /api/folders/props {ptype}): a new list in the folder (and its subfolder) is a project
   of that type with its standard sections, ticket types (software) and the type's modules; an unknown type = 400
 - a type chosen in the request goes first (ptype "agency"); ptype "" = chosen: no type
 - without a folder default: the type the person's projects in the folder share (typed ones all one type and more than the
   untyped ones); mixed types = no type
 - moving an existing list into the folder and "apply to all" change no existing list's type
 - the agent API: POST /api/v1/lists without project_type in a folder = the type its projects there share; project_type null = none
P4: a person without an organisation (tests/freelancer_fixture.py) gets the same (freelancer-matrix: lists)
usage: p2411_folder_ptype_api_test.py <datadir>"""
import sys

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

kt.fresh(prefix="P2411F")
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en"})


def lst(s, lid):
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)


def secs(s, lid):
    return [x["name"] for x in s.get(B + "/api/state").json().get("sections", []) if x["list_id"] == lid]


def new(s, **b):
    r = s.post(B + "/api/lists", json=b)
    assert r.ok, r.text
    return r.json()["id"]


def case(s, who):
    # the folder default
    r = s.put(B + "/api/folders/props", json={"folder": "Kalmido", "props": {"ptype": "nope"}})
    check(r.status_code == 400, f"{who}: an unknown project type = 400 {r.status_code}")
    r = s.put(B + "/api/folders/props", json={"folder": "Kalmido", "props": {"ptype": "software"}, "apply": "new"})
    check(r.ok and r.json()["props"].get("ptype") == "software", f"{who}: the folder default Project type is saved {r.text[:160]}")
    old = new(s, name="Old one")  # outside the folder, moved in later
    lid = new(s, name="Built", folder="Kalmido")
    x = lst(s, lid)
    check(x and x.get("ptype") == "software" and x.get("kind") == "project" and x.get("tickets") in (1, True),
          f"{who}: a new list in the folder is a software project with ticket types {x and (x.get('ptype'), x.get('kind'), x.get('tickets'))}")
    check("Backlog" in secs(s, lid) and "Review" in secs(s, lid), f"{who}: with the type's standard sections {secs(s, lid)}")
    sub = new(s, name="Sub", folder="Kalmido/Web")
    x = lst(s, sub) or {}
    check(x.get("ptype") == "software", f"{who}: a subfolder follows its folder {x.get('folder')!r} {x.get('ptype')!r}")
    ag = new(s, name="Chosen", folder="Kalmido", ptype="agency")
    check((lst(s, ag) or {}).get("ptype") == "agency", f"{who}: a type chosen in the request goes first")
    no = new(s, name="Plain", folder="Kalmido", ptype="")
    check(not (lst(s, no) or {}).get("ptype") and (lst(s, no) or {}).get("kind") != "project", f"{who}: ptype \"\" = chosen: no type")
    # existing lists keep their type: moved in, then "apply to all"
    r = s.patch(B + f"/api/lists/{old}", json={"folder": "Kalmido"})
    check(r.ok and not (lst(s, old) or {}).get("ptype"), f"{who}: a list moved into the folder keeps its (no) type {r.text[:120]}")
    r = s.put(B + "/api/folders/props", json={"folder": "Kalmido", "props": {"ptype": "private"}, "apply": "all"})
    check(r.ok and (lst(s, lid) or {}).get("ptype") == "software" and not (lst(s, old) or {}).get("ptype"),
          f"{who}: apply to all changes no existing list's type {r.text[:160]}")
    check((lst(s, new(s, name="After", folder="Kalmido")) or {}).get("ptype") == "private", f"{who}: the changed default holds for the next new list")
    # without a default: the type the projects share
    for n in ("Apps A", "Apps B"):
        new(s, name=n, folder="Apps", ptype="software")
    new(s, name="Apps notes", folder="Apps")  # made before (no type): 2 typed > 1 untyped (this one already follows the rule)
    check((lst(s, new(s, name="Apps next", folder="Apps")) or {}).get("ptype") == "software", f"{who}: no default: the type the folder's projects share")
    new(s, name="Mix A", folder="Mix", ptype="software")
    new(s, name="Mix B", folder="Mix", ptype="agency")
    check(not (lst(s, new(s, name="Mix next", folder="Mix")) or {}).get("ptype"), f"{who}: mixed types: no type")
    check(not (lst(s, new(s, name="Loose")) or {}).get("ptype"), f"{who}: no folder: no type")


case(A, "alice")
FID, Fr = freelancer(B, A)
case(Fr, "frida (no organisation)")

# the agent API (the agent owns what it creates: its own projects in the folder decide)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
AGH = {"Authorization": "Bearer " + r.json()["token"]}
V = B + "/api/v1"
for n in ("Ops A", "Ops B"):
    r = sess().post(V + "/lists", headers=AGH, json={"name": n, "folder": "Ops", "project_type": "software"})
    check(r.status_code == 201, f"agent: creates a software project {r.status_code} {r.text[:120]}")
r = sess().post(V + "/lists", headers=AGH, json={"name": "Ops next", "folder": "Ops"})
check(r.status_code == 201 and r.json().get("project_type") == "software", f"agent: no project_type in the folder = the shared type {r.text[:160]}")
r = sess().post(V + "/lists", headers=AGH, json={"name": "Ops plain", "folder": "Ops", "project_type": None})
check(r.status_code == 201 and not r.json().get("project_type"), f"agent: project_type null = no type {r.text[:160]}")

sys.exit(kt.done("p2411_folder_ptype_api"))
