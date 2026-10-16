#!/usr/bin/env python3
"""2.55.0 API tests, part A (#1069, #1068): several saved arrangements per view, an arrangement as a template. Invented names only.
 - #1069 saved arrangements: create (with / without layout), list, rename (unique names), move, overwrite, delete (the row
   comes back for undo), activate (the view's own value becomes the saved one), "Standard" (none active, own value back),
   changes while one is active follow into it, a reset to the standard ends "active"; LYV_MAX 409; unknown view 400;
   someone else's id 404; agents 403; a project page only for people who see it (404 / 403 like the page itself);
   the data export carries view_layouts
 - #1068 templates: only to people the sender sees (another organisation 404, an agent 404), at most 20 recipients, only
   the arrangement travels (the cleaned layout value), a News item "lytpl" with accept / decline, accept = a saved
   arrangement of the recipient (source template, name "<sender>: <name>"), optionally active; decided = gone (404);
   a project page template only to people with access to it, re-checked when taking it over
 - backwards compatible: new tables / a new column only
tenant-matrix: lytpl
usage: p255_a_api_test.py <datadir>      (a fresh container; P255A_NOSTART=1 = the server already runs)"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


if not os.environ.get("P255A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code == 201, r.text
ALPHA = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
check(A.patch(B + f"/api/admin/orgs/{ALPHA}", json={"members": [1, BOB, CAROL], "admins": [1]}).ok, "setup: Alpha members")
A.patch(B + f"/api/admin/orgs/{BETA}", json={"members": [DAVE], "admins": [DAVE]})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "claude", "display_name": "Claude"})
check(r.ok, "an agent " + r.text[:200])
AGH = {"Authorization": "Bearer " + r.json()["token"]} if r.ok else {}
AGENT = r.json().get("id") if r.ok else None
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

FOCUS = json.dumps({"order": ["tasks", "brief"], "hidden": ["inbox"], "opts": {"tasks": {"lw": 4}}})
WIDE = json.dumps({"order": ["brief", "tasks"], "opts": {"brief": {"lh": 3}}})
own = lambda s, k="view_today": s.get(B + "/api/state").json()["settings"].get(k, "")  # noqa: E731
saved = lambda s, k="view_today": s.get(B + "/api/layouts/saved", params={"key": k}).json()["saved"]  # noqa: E731

# ================================================================== #1069 saved arrangements
r = A.post(B + "/api/layouts/saved", json={"key": "view_today", "name": "Focus", "layout": FOCUS})
check(r.ok and r.json()["saved"]["name"] == "Focus" and not r.json()["saved"]["active"], "#1069: save an arrangement " + r.text[:200])
F = r.json()["saved"]["id"]
check(json.loads(r.json()["saved"]["layout"])["hidden"] == ["inbox"], "#1069: the layout is stored cleaned")
r = A.post(B + "/api/layouts/saved", json={"key": "view_today", "name": "Focus", "layout": WIDE})
check(r.ok and r.json()["saved"]["name"] == "Focus (2)", "#1069: names are unique per view " + r.text[:200])
O = r.json()["saved"]["id"]
check(A.patch(B + f"/api/layouts/saved/{O}", json={"name": "Overview"}).json()["saved"]["name"] == "Overview", "#1069: rename")
check(A.patch(B + f"/api/layouts/saved/{O}", json={"name": "  "}).status_code == 400, "#1069: a name is required")
check([x["name"] for x in saved(A)] == ["Focus", "Overview"], "#1069: listed in their order")
check(A.patch(B + f"/api/layouts/saved/{O}", json={"pos": 0}).ok and [x["name"] for x in saved(A)] == ["Overview", "Focus"], "#1069: move to the top")
# without a layout = the current own value
A.patch(B + "/api/settings", json={"view_today": WIDE})
r = A.post(B + "/api/layouts/saved", json={"key": "view_today", "name": "Current"})
check(r.ok and json.loads(r.json()["saved"]["layout"]) == json.loads(WIDE), "#1069: without layout = my current value")
CUR = r.json()["saved"]["id"]

# activate: the own value becomes the saved one
r = A.post(B + f"/api/layouts/saved/{F}/activate")
check(r.ok and r.json()["active"] == F and json.loads(r.json()["value"]) == json.loads(saved(A)[1]["layout"]), "#1069: activate " + r.text[:200])
check(json.loads(own(A)) == json.loads(FOCUS), "#1069: the view's own value is the saved one now (2.53 reads it unchanged)")
check([x["active"] for x in saved(A)] == [False, True, False], "#1069: exactly one is active")
# a change while customizing follows into the active one
CH = json.dumps({"order": ["inbox", "tasks"], "opts": {"tasks": {"lw": 6}}})
A.patch(B + "/api/settings", json={"view_today": CH})
check(json.loads(next(x for x in saved(A) if x["id"] == F)["layout"]) == json.loads(CH), "#1069: the active one follows my changes")
check(json.loads(next(x for x in saved(A) if x["id"] == O)["layout"]) == json.loads(WIDE), "#1069: ... the others stay")
# reset to the standard (no arrangement, only switches) ends "active" and keeps the saved one
A.patch(B + "/api/settings", json={"view_today": json.dumps({"opts": {"tasks": {"x": 1}}})})
check(not any(x["active"] for x in saved(A)) and json.loads(next(x for x in saved(A) if x["id"] == F)["layout"]) == json.loads(CH),
      "#1069: back to the standard: none active, the saved one is kept")
# overwrite an active one: the view follows
A.post(B + f"/api/layouts/saved/{O}/activate")
r = A.patch(B + f"/api/layouts/saved/{O}", json={"layout": FOCUS})
check(r.ok and json.loads(r.json()["value"]) == json.loads(FOCUS) and json.loads(own(A)) == json.loads(FOCUS), "#1069: overwriting the active one sets the view")
# "Standard": none active, own value as sent ('' = the standard), undo sends the old one
r = A.post(B + "/api/layouts/saved/standard", json={"key": "view_today"})
check(r.ok and r.json()["value"] == "" and own(A) == "" and not any(x["active"] for x in saved(A)), "#1069: Standard " + r.text[:200])
r = A.post(B + "/api/layouts/saved/standard", json={"key": "view_today", "value": WIDE})
check(r.ok and json.loads(own(A)) == json.loads(WIDE), "#1069: Standard with a value (undo)")
# delete: the row comes back for undo; posted again it is there again
r = A.delete(B + f"/api/layouts/saved/{CUR}")
check(r.ok and r.json()["deleted"]["name"] == "Current" and r.json()["deleted"]["index"] == 2, "#1069: delete returns the row " + r.text[:200])
d = r.json()["deleted"]
r = A.post(B + "/api/layouts/saved", json={"key": "view_today", "name": d["name"], "layout": d["layout"], "pos": d["index"]})
check(r.ok and [x["name"] for x in saved(A)] == ["Overview", "Focus", "Current"], "#1069: undo of a delete")
# the start page: only its cards
check(A.post(B + "/api/layouts/saved", json={"key": "dashboard", "name": "X", "layout": json.dumps({"order": ["nope"]})}).status_code == 400,
      "#1069: the start page takes only its cards")
check(A.post(B + "/api/layouts/saved", json={"key": "view_nope", "name": "X", "layout": ""}).status_code == 400, "#1069: unknown view 400")
check(A.post(B + "/api/layouts/saved", json={"key": "view_time", "name": "X", "layout": "{" * 3}).status_code == 400, "#1069: broken json 400")
# LYV_MAX
for i in range(12):
    r = A.post(B + "/api/layouts/saved", json={"key": "view_time", "name": f"T{i}", "layout": ""})
check(r.ok, "#1069: twelve per view")
check(A.post(B + "/api/layouts/saved", json={"key": "view_time", "name": "T13", "layout": ""}).status_code == 409, "#1069: the 13th 409")
# someone else's id: 404 everywhere; agents 403
for m, p, b in (("PATCH", f"/api/layouts/saved/{F}", {"name": "x"}), ("DELETE", f"/api/layouts/saved/{F}", None),
                ("POST", f"/api/layouts/saved/{F}/activate", None)):
    check(Bo.request(m, B + p, json=b).status_code == 404, f"#1069: someone else's arrangement {m} 404")
check(saved(Bo) == [], "#1069: bob sees none of alice's")
if AGH:
    for m, p, b in (("GET", "/api/layouts/saved", None), ("POST", "/api/layouts/saved", {"key": "view_today", "name": "A"}),
                    ("POST", "/api/layouts/saved/standard", {"key": "view_today"}), ("POST", "/api/layouts/offers",
                                                                                   {"key": "view_today", "name": "A", "layout": "", "to": [BOB]})):
        r = requests.request(m, B + p, headers={**H, **AGH}, json=b)
        check(r.status_code in (401, 403), f"#1069: an agent cannot {m} {p} ({r.status_code})")

# the project page
P = A.post(B + "/api/lists", json={"name": "Relaunch", "kind": "project", "org_id": ALPHA}).json()["id"]
check(A.put(B + f"/api/lists/{P}/members", json={"user_id": BOB, "role": "view"}).ok, "setup: bob reads the project")
PL = json.dumps({"order": ["ms", "desc"]})
r = Bo.post(B + "/api/layouts/saved", json={"key": f"list:{P}", "name": "Mine", "layout": PL, "activate": True})
check(r.ok and r.json()["saved"]["active"], "#1069: a project page arrangement, active at once " + r.text[:200])
check(json.loads(Bo.get(B + f"/api/lists/{P}/layout").json()["mine"]) == json.loads(PL), "#1069: ... it is bob's own page arrangement now")
PM = r.json()["saved"]["id"]
Bo.put(B + f"/api/lists/{P}/layout", json={"layout": json.dumps({"order": ["desc", "ms"]})})
check(json.loads(saved(Bo, f"list:{P}")[0]["layout"])["order"] == ["desc", "ms"], "#1069: the project page follows too")
Bo.put(B + f"/api/lists/{P}/layout", json={"layout": ""})
check(not saved(Bo, f"list:{P}")[0]["active"], "#1069: back to the project's standard: none active")
r = Da.post(B + "/api/layouts/saved", json={"key": f"list:{P}", "name": "X", "layout": PL})
check(r.status_code in (403, 404), f"#1069: a project page dave cannot see ({r.status_code})")
check(Da.get(B + "/api/layouts/saved", params={"key": f"list:{P}"}).status_code in (403, 404), "#1069: ... nor list its arrangements")

# the data export
ex = A.get(B + "/api/export.json")
check(ex.ok and any(x["name"] == "Focus" for x in ex.json().get("view_layouts", [])), "#1069: the export carries view_layouts")

# ================================================================== #1068 templates
TPL = json.dumps({"order": ["tasks", "events"], "hidden": ["inbox"], "opts": {"tasks": {"lw": 4, "lh": 3}}})
r = A.post(B + "/api/layouts/offers", json={"key": "view_today", "name": "Morning", "layout": TPL, "to": [BOB, CAROL]})
check(r.ok and r.json()["sent"] == 2, "#1068: send to two people " + r.text[:200])
check(A.post(B + "/api/layouts/offers", json={"key": "view_today", "name": "M", "layout": TPL, "to": [DAVE]}).status_code == 404,
      "#1068: another organisation's person 404")
if AGENT:
    check(A.post(B + "/api/layouts/offers", json={"key": "view_today", "name": "M", "layout": TPL, "to": [AGENT]}).status_code == 404,
          "#1068: an agent is no recipient (404)")
check(A.post(B + "/api/layouts/offers", json={"key": "view_today", "name": "M", "layout": TPL, "to": list(range(100, 125))}).status_code == 400,
      "#1068: at most 20 recipients")
check(A.post(B + "/api/layouts/offers", json={"key": "view_today", "name": "M", "layout": TPL, "to": [1]}).status_code == 404, "#1068: not to myself")
check(A.post(B + "/api/layouts/offers", json={"key": "view_today", "name": "", "layout": TPL, "to": [BOB]}).status_code == 400, "#1068: a name")
check(A.post(B + "/api/layouts/offers", json={"key": "view_today", "name": "M", "layout": {"tasks": "x"}, "to": [BOB]}).status_code == 400,
      "#1068: only a valid arrangement travels")
nb = Bo.get(B + "/api/news").json()
it = next((x for x in nb.get("items", []) if x["kind"] == "lytpl"), None)
check(it and it["data"]["name"] == "Morning" and it.get("to_me"), "#1068: bob gets a News item (For you) " + json.dumps(nb)[:300])
OID = it["data"]["offer"] if it else 0
r = Bo.get(B + f"/api/layouts/offers/{OID}")
check(r.ok and r.json()["from"]["name"] == "Alice" and json.loads(r.json()["layout"]) == json.loads(TPL), "#1068: bob reads the template " + r.text[:200])
check(set(r.json()) == {"id", "key", "name", "layout", "created_at", "from"}, "#1068: only the arrangement, nothing else")
check(Ca.get(B + f"/api/layouts/offers/{OID}").status_code == 404, "#1068: carol cannot read bob's template")
check(A.get(B + f"/api/layouts/offers/{OID}").status_code == 404, "#1068: nor the sender (it is bob's now)")
check(Da.post(B + f"/api/layouts/offers/{OID}/accept", json={}).status_code == 404, "#1068: dave cannot take it over")
r = Bo.post(B + f"/api/layouts/offers/{OID}/accept", json={"activate": True})
check(r.ok and r.json()["saved"]["name"] == "Alice: Morning" and r.json()["saved"]["source"] == "template" and r.json()["saved"]["active"],
      "#1068: accept = bob's own saved arrangement, active " + r.text[:200])
check(json.loads(own(Bo)) == json.loads(TPL), "#1068: ... bob's Today shows it")
check(Bo.post(B + f"/api/layouts/offers/{OID}/accept", json={}).status_code == 404, "#1068: decided = gone")
check(not any(x["kind"] == "lytpl" for x in Bo.get(B + "/api/news").json().get("items", [])), "#1068: the News item goes once decided")
it = next((x for x in Ca.get(B + "/api/news").json().get("items", []) if x["kind"] == "lytpl"), None)
check(it is not None, "#1068: carol got hers")
if it:
    check(Ca.post(B + f"/api/layouts/offers/{it['data']['offer']}/decline").ok, "#1068: carol declines")
    check(Ca.get(B + f"/api/layouts/offers/{it['data']['offer']}").status_code == 404 and saved(Ca) == [], "#1068: declined = nothing saved")
# the sender changes nothing at the recipient afterwards
A.delete(B + f"/api/layouts/saved/{F}")
check(any(x["name"] == "Alice: Morning" for x in saved(Bo)), "#1068: bob's copy stays his")
# a project page template: only to people with access, re-checked when taking it over
check(A.post(B + "/api/layouts/offers", json={"key": f"list:{P}", "name": "Page", "layout": PL, "to": [CAROL]}).status_code == 409,
      "#1068: a project page only to people with access (carol has none)")
r = A.post(B + "/api/layouts/offers", json={"key": f"list:{P}", "name": "Page", "layout": PL, "to": [BOB]})
check(r.ok, "#1068: a project page template to bob " + r.text[:200])
it = next((x for x in Bo.get(B + "/api/news").json().get("items", []) if x["kind"] == "lytpl"), None)
A.delete(B + f"/api/lists/{P}/members/{BOB}")
check(it and Bo.post(B + f"/api/layouts/offers/{it['data']['offer']}/accept", json={}).status_code == 404,
      "#1068: bob lost access before taking it over: 404")
# the mute: row "share" of the notification settings without News -> no item (the template still exists)
Ca.patch(B + "/api/settings", json={"notify": {"share": {"news": 0}}})
A.post(B + "/api/layouts/offers", json={"key": "view_today", "name": "Quiet", "layout": TPL, "to": [CAROL]})
check(not any(x["kind"] == "lytpl" for x in Ca.get(B + "/api/news").json().get("items", [])), "#1068: switched off like sharing News")

print(f"p255_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
