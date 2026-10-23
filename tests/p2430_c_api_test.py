#!/usr/bin/env python3
"""2.43.0 API tests, part C, own container (start.sh).
 - #1452 the standard for everyone: the project page (owner / admins: scope standard and promote; an edit member 403),
   the other views (instance admins: PUT /api/layouts/std/<key>; a person 403, an agent 403), reset = my own value goes,
   the review is a view of its own (view_review); widths / heights live in opts (lw, lh) next to half / full, so a 2.42
   layout check (the same clean_layout shape) keeps them; old values (half / full only) still read
 - #1346 notepads on the project page: create / change / delete with write access, a view member reads but cannot write
   (403), a person outside the list sees nothing (404); someone else's save in between = 409 with the current notepad;
   block colours for everyone (palette only), an agent never gets notepads or colours
usage: p2430_c_api_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
P = A.post(B + "/api/lists", json={"name": "Relaunch", "kind": "project"}).json()["id"]
me = lambda s: s.get(B + "/api/me").json()["id"]  # noqa: E731
check(A.put(B + f"/api/lists/{P}/members", json={"user_id": me(Bo), "role": "edit"}).ok, "bob edits the project")
check(A.put(B + f"/api/lists/{P}/members", json={"user_id": me(Ca), "role": "view"}).ok, "carol only reads it")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "claude", "display_name": "Claude"})
AGH = {"Authorization": "Bearer " + r.json()["token"]} if r.ok else {}
check(r.ok, "an agent " + r.text[:200])
if r.ok:
    A.put(B + f"/api/lists/{P}/members", json={"user_id": r.json()["id"], "role": "edit"})
lay = lambda s: s.get(B + f"/api/lists/{P}/layout").json()  # noqa: E731

# ================================================================== #1452 the project page standard
mine = json.dumps({"order": ["ms", "desc"], "half": ["desc"], "opts": {"desc": {"lw": 2, "lh": 1}, "ms": {"lw": 4}}})
r = Bo.put(B + f"/api/lists/{P}/layout", json={"layout": mine})
check(r.ok and r.json()["mine"] and not r.json()["can_std"], "#1452: an edit member keeps an own arrangement, may not set the standard")
check(json.loads(r.json()["mine"])["opts"]["desc"] == {"lw": 2, "lh": 1}, "#1452: width / height stored in opts " + r.text[:200])
for sc in ("standard", "promote"):
    r = Bo.put(B + f"/api/lists/{P}/layout", json={"layout": mine, "scope": sc})
    check(r.status_code == 403, f"#1452: an edit member cannot {sc} the standard ({r.status_code})")
check(lay(A)["std"] == "", "#1452: ... the standard untouched")
r = A.put(B + f"/api/lists/{P}/layout", json={"layout": mine})
r = A.put(B + f"/api/lists/{P}/layout", json={"layout": mine, "scope": "promote"})
check(r.ok and json.loads(r.json()["std"])["order"] == ["ms", "desc"] and r.json()["mine"] == "", "#1452: the owner promotes: standard set, own arrangement gone " + r.text[:200])
check(lay(Ca)["std"] == r.json()["std"] and lay(Ca)["mine"] == "", "#1452: who changed nothing gets the new standard at once")
check(lay(Bo)["mine"] != "", "#1452: ... an own arrangement of someone else stays")
r = Bo.put(B + f"/api/lists/{P}/layout", json={"layout": ""})
check(r.ok and r.json()["mine"] == "", "#1452: reset to the standard = the own arrangement goes")
old = json.dumps({"order": ["desc", "ms"], "half": ["desc"], "full": ["ms"]})
r = A.put(B + f"/api/lists/{P}/layout", json={"layout": old, "scope": "standard"})
check(r.ok and json.loads(r.json()["std"]) == {"order": ["desc", "ms"], "half": ["desc"], "full": ["ms"]}, "#1452: an old value (half / full only) stays valid")
for bad in ({"order": ["desc"], "w": {"desc": 2}}, {"opts": {"desc": {"lw": "x" * 50}}}):
    check(A.put(B + f"/api/lists/{P}/layout", json={"layout": json.dumps(bad)}).status_code == 400, "#1452: an invalid layout 400 " + json.dumps(bad))

# ================================================================== #1452 the other views: instance admins
st = json.dumps({"order": ["news", "today"], "hidden": ["stats"], "opts": {"news": {"lw": 4, "lh": 3}}})
r = A.put(B + "/api/layouts/std/dashboard", json={"layout": st})
check(r.ok and r.json()["layouts"]["dashboard"] and r.json()["can"], "#1452: an instance admin sets the start page standard " + r.text[:200])
r = Bo.put(B + "/api/layouts/std/dashboard", json={"layout": ""})
check(r.status_code == 403, f"#1452: a person cannot ({r.status_code})")
g = Bo.get(B + "/api/layouts/std").json()
check(json.loads(g["layouts"]["dashboard"])["opts"]["news"] == {"lw": 4, "lh": 3} and g["can"] is False, "#1452: everyone reads the standard, can = false")
if AGH:
    r = requests.put(B + "/api/layouts/std/dashboard", headers={**H, **AGH}, json={"layout": ""})
    check(r.status_code in (401, 403), f"#1452: an agent cannot ({r.status_code})")
check(A.put(B + "/api/layouts/std/dashboard", json={"layout": json.dumps({"order": ["nope"]})}).status_code == 400, "#1452: unknown cards 400")
check(A.put(B + "/api/layouts/std/view_nope", json={"layout": ""}).status_code == 400, "#1452: unknown view 400")
r = A.put(B + "/api/layouts/std/view_review", json={"layout": json.dumps({"order": ["journal", "done"]})})
check(r.ok and "journal" in r.json()["layouts"]["view_review"], "#1452: the review has a standard of its own")
r = Bo.patch(B + "/api/settings", json={"view_review": json.dumps({"order": ["next"], "opts": {"next": {"lw": 6}}})})
check(r.ok, "#1452: view_review is a setting of the person " + r.text[:200])
A.patch(B + "/api/settings", json={"dashboard": json.dumps({"order": ["wait"], "opts": {"wait": {"lw": 2}}})})
r = A.put(B + "/api/layouts/std/dashboard", json={"layout": json.dumps({"order": ["wait"], "opts": {"wait": {"lw": 2}}}), "promote": True})
check(r.ok and A.get(B + "/api/state").json()["settings"].get("dashboard", "") == "", "#1452: promote: the admin's own start page goes back to the standard")

# ================================================================== #1346 notepads
r = A.post(B + f"/api/lists/{P}/notepads", json={"title": "Decisions", "body": "- **Go** live in May"})
check(r.ok and r.json()["pads"][0]["title"] == "Decisions", "#1346: the owner adds a notepad " + r.text[:200])
NP = r.json()["id"]
r = Bo.post(B + f"/api/lists/{P}/notepads", json={"title": "Contacts"})
check(r.ok and len(r.json()["pads"]) == 2, "#1346: several notepads per project, an edit member adds one")
NP2 = r.json()["id"]
ov = Ca.get(B + f"/api/lists/{P}/overview").json()["layout"]
check([p["title"] for p in ov["pads"]] == ["Decisions", "Contacts"] and not ov["can_style"], "#1346: a view member reads them, cannot change")
check(Ca.post(B + f"/api/lists/{P}/notepads", json={"title": "x"}).status_code == 403, "#1346: a view member cannot add (403)")
check(Ca.patch(B + f"/api/notepads/{NP}", json={"body": "x"}).status_code == 403, "#1346: ... nor change (403)")
check(Ca.delete(B + f"/api/notepads/{NP}").status_code == 403, "#1346: ... nor delete (403)")
check(Da.get(B + f"/api/lists/{P}/overview").status_code == 404, "#1346: outside the list: no project page")
for m, u in (("post", f"/api/lists/{P}/notepads"), ("patch", f"/api/notepads/{NP}"), ("delete", f"/api/notepads/{NP}")):
    rr = getattr(Da, m)(B + u, json={"title": "x"}) if m != "delete" else Da.delete(B + u)
    check(rr.status_code == 404, f"#1346: outside the list {m} 404 ({rr.status_code})")
base = [p for p in A.get(B + f"/api/lists/{P}/overview").json()["layout"]["pads"] if p["id"] == NP][0]["updated_at"]
r = Bo.patch(B + f"/api/notepads/{NP}", json={"body": "Bob was here", "base": base})
check(r.ok and [p for p in r.json()["pads"] if p["id"] == NP][0]["body"] == "Bob was here", "#1346: an edit member changes a notepad")
r = A.patch(B + f"/api/notepads/{NP}", json={"body": "Alice overwrites", "base": "2000-01-01T00:00:00+00:00"})
check(r.status_code == 409 and r.json()["pad"]["body"] == "Bob was here", "#1346: someone else saved in between: 409 with the current text")
r = A.patch(B + f"/api/notepads/{NP}", json={"body": "Alice overwrites"})
check(r.ok, "#1346: ... saving without base overwrites")
check(A.patch(B + f"/api/notepads/{NP}", json={"body": "x" * 20001}).status_code == 400, "#1346: too long 400")
check(A.patch(B + f"/api/notepads/{NP}", json={"color": "red"}).status_code == 400, "#1346: unknown field 400")
# colours
r = Bo.put(B + f"/api/lists/{P}/page-style", json={"block": "desc", "color": "green"})
check(r.ok and r.json()["style"] == {"desc": "green"}, "#1346: a colour per block for everyone " + r.text[:200])
check(Ca.get(B + f"/api/lists/{P}/overview").json()["layout"]["style"] == {"desc": "green"}, "#1346: everyone sees it")
check(Ca.put(B + f"/api/lists/{P}/page-style", json={"block": "desc", "color": "red"}).status_code == 403, "#1346: a view member cannot colour (403)")
check(A.put(B + f"/api/lists/{P}/page-style", json={"block": "desc", "color": "#ff0000"}).status_code == 400, "#1346: only the palette")
A.put(B + f"/api/lists/{P}/page-style", json={"block": f"np{NP2}", "color": "yellow"})
r = A.delete(B + f"/api/notepads/{NP2}")
check(r.ok and [p["id"] for p in r.json()["pads"]] == [NP] and f"np{NP2}" not in r.json()["style"], "#1346: delete takes its colour along")
r = A.put(B + f"/api/lists/{P}/page-style", json={"block": "desc", "color": ""})
check(r.ok and r.json()["style"] == {}, "#1346: no colour again")
if AGH:
    rr = requests.get(B + f"/api/lists/{P}/overview", headers={**H, **AGH})
    check(rr.status_code != 200 or "pads" not in (rr.json().get("layout") or {}), f"#1346: an agent never gets notepads ({rr.status_code})")
    rr = requests.post(B + f"/api/lists/{P}/notepads", headers={**H, **AGH}, json={"title": "x"})
    check(rr.status_code in (401, 403), f"#1346: an agent cannot add notepads ({rr.status_code})")
    rr = requests.get(B + f"/api/v1/lists/{P}/overview", headers={**H, **AGH})
    check(rr.status_code != 200 or ("pads" not in rr.text and "Alice overwrites" not in rr.text), "#1346: nor in the agent API overview")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
