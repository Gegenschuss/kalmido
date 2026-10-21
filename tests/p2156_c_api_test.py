#!/usr/bin/env python3
"""2.156.0 API tests, part C (#2071 #2072 #2073), own container (start.sh). Invented names only.
 - #2071: the list view "calendar" is stored like Kanban / Timeline (owner and member), an unknown view is refused
 - #2072: "My tasks" as a board: mine_board (0 | 1) and mine_board_by (due | prio | list) per person, wrong values 400
 - #2073: folded sections (sections_closed: json list of section ids) per person; section templates: saved from a list's
   sections (only who may write the list) or from names, private or for an organisation (members read, its creator and the
   admins change), added to another list = only the missing names (any case), nothing removed; a template of another person
   / organisation: 404 (tenant-matrix: sectpl); agents and API tokens: 403; a list with the lock: 409
 - a person without an organisation (freelancer-matrix: sectpl): views, settings, own templates; no organisation space (404)
usage: p2156_c_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
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


if os.environ.get("P2156C_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "vera", "carl"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "carl" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["carl"]})
assert r.status_code in (200, 201), r.text
ORG2 = r.json().get("id") or r.json().get("org", {}).get("id")
Bo, Ve, Ca = sess("bob"), sess("vera"), sess("carl")
FEAT = "cal,kanban,timeline,collab,comments"
for s in (A, Bo, Ve, Ca):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT}).ok


def st(s):
    return s.get(B + "/api/state").json()


def mklist(s, name, secs=(), org=None):
    j = {"name": name, **({"org_id": org} if org else {})}
    r = s.post(B + "/api/lists", json=j)
    assert r.ok, r.text
    lid = r.json()["id"]
    for n in secs:
        assert s.post(B + "/api/sections", json={"list_id": lid, "name": n}).ok
    return lid


def secnames(s, lid):
    return [x["name"] for x in sorted((x for x in st(s)["sections"] if x["list_id"] == lid), key=lambda x: (x["sort"], x["id"]))]


# ================================================================ #2071: the list view "calendar"
L1 = mklist(A, "Redaktionsplan", ("Idee", "Entwurf", "Fertig"), ORG)
check(A.put(B + f"/api/lists/{L1}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "alice shares the list with bob")
check(A.put(B + f"/api/lists/{L1}/members", json={"user_id": uid["vera"], "role": "view"}).ok, "alice shares the list with vera (view)")
r = A.patch(B + f"/api/lists/{L1}", json={"view": "calendar"})
check(r.ok, f"#2071: the owner sets the view calendar {r.status_code} {r.text[:200]}")
check(next(x for x in st(A)["lists"] if x["id"] == L1).get("view") == "calendar", "#2071: the view is stored")
check(A.patch(B + f"/api/lists/{L1}", json={"view": "agenda"}).status_code == 400, "#2071: an unknown view is refused")
r = Bo.patch(B + f"/api/lists/{L1}", json={"view": "calendar"})
check(r.ok and next(x for x in st(Bo)["lists"] if x["id"] == L1).get("view") == "calendar", f"#2071: a member's own view calendar {r.status_code}")
t = A.post(B + "/api/tasks", json={"title": "Artikel Herbst", "list_id": L1, "due": "2026-11-03"}).json()
check(A.patch(B + f"/api/tasks/{t['id']}", json={"due": "2026-11-05"}).ok, "#2071: moving a task to another day (the drop) is a plain date change")

# ================================================================ #2072: My tasks as a board
j = st(A)["settings"]
check(j.get("mine_board") == "0" and j.get("mine_board_by") == "due", f"#2072: the list by default, columns by due date {j.get('mine_board')} {j.get('mine_board_by')}")
check(A.patch(B + "/api/settings", json={"mine_board": "1", "mine_board_by": "prio"}).ok, "#2072: board by priority")
j = st(A)["settings"]
check(j["mine_board"] == "1" and j["mine_board_by"] == "prio", "#2072: kept for the person (all devices)")
check(st(Bo)["settings"]["mine_board"] == "0", "#2072: per person (bob still sees the list)")
check(A.patch(B + "/api/settings", json={"mine_board_by": "status"}).status_code == 400, "#2072: unknown grouping 400")
check(A.patch(B + "/api/settings", json={"mine_board": "2"}).status_code == 400, "#2072: mine_board 0 | 1")
check(A.patch(B + "/api/settings", json={"mine_board_by": "list"}).ok and st(A)["settings"]["mine_board_by"] == "list", "#2072: board by list")
# 2.156.0 (#2072): mine_view stays own | lists (p2400_v_api_test.py checks "date" is refused)
check(A.patch(B + "/api/settings", json={"mine_view": "board"}).status_code == 400, "#2072: the board is its own setting, not a mine_view value")

# ================================================================ #2073: folded sections
sids = [x["id"] for x in st(A)["sections"] if x["list_id"] == L1]
check(A.patch(B + "/api/settings", json={"sections_closed": f"[{sids[0]}, {sids[2]}, {sids[0]}]"}).ok, "#2073: fold two sections")
check(st(A)["settings"]["sections_closed"] == f"[{sids[0]}, {sids[2]}]", "#2073: stored once each, kept for the person")
check(st(Bo)["settings"]["sections_closed"] == "[]", "#2073: per person (bob's sections stay open)")
for bad in ('["a"]', "[0]", "[true]", '{"x": 1}', "nope", "[" + ",".join(str(i + 1) for i in range(2001)) + "]"):
    check(A.patch(B + "/api/settings", json={"sections_closed": bad}).status_code == 400, f"#2073: bad sections_closed {bad[:20]} 400")

# ================================================================ #2073: section templates (tenant-matrix: sectpl)
r = A.post(B + "/api/section-templates", json={"name": "Redaktion", "list_id": L1, "space": f"org:{ORG}"})
check(r.ok and r.json()["sections"] == ["Idee", "Entwurf", "Fertig"] and r.json()["org_id"] == ORG, f"#2073: saved from the list, for the organisation {r.status_code} {r.text[:200]}")
TO = r.json()["id"]
r = A.post(B + "/api/section-templates", json={"name": "Privat", "sections": ["Heute", " ", "heute", "Später"]})
check(r.ok and r.json()["sections"] == ["Heute", "Später"] and r.json()["space"] == "private", f"#2073: from names, private, doubles / blanks out {r.text[:200]}")
TP = r.json()["id"]
check(A.post(B + "/api/section-templates", json={"name": "Leer", "sections": []}).status_code == 400, "#2073: no sections 400")
check(A.post(B + "/api/section-templates", json={"name": "", "sections": ["X"]}).status_code == 400, "#2073: no name 400")
check(Ve.post(B + "/api/section-templates", json={"name": "Kopie", "list_id": L1}).status_code == 403, "#2073: view only: the list's sections cannot be saved")
ids_b = {x["id"]: x for x in Bo.get(B + "/api/section-templates").json()["templates"]}
check(TO in ids_b and not ids_b[TO]["can_edit"] and TP not in ids_b, "#2073: bob (member) sees the organisation's template, read only; not alice's private one")
check(Bo.patch(B + f"/api/section-templates/{TO}", json={"name": "Neu"}).status_code == 403, "#2073: a member does not change it")
check(Bo.delete(B + f"/api/section-templates/{TO}").status_code == 403, "#2073: a member does not delete it")
check(Bo.patch(B + f"/api/section-templates/{TP}", json={"name": "Neu"}).status_code == 404, "#2073: someone else's private template: 404")
L2 = mklist(Bo, "Bobs Blog", ("entwurf", "Archiv"))
r = Bo.post(B + f"/api/lists/{L2}/sections/from-template", json={"template_id": TO})
check(r.ok and [x["name"] for x in r.json()["added"]] == ["Idee", "Fertig"] and r.json()["skipped"] == ["Entwurf"], f"#2073: only the missing names (any case) {r.text[:300]}")
check(secnames(Bo, L2) == ["entwurf", "Archiv", "Idee", "Fertig"], f"#2073: nothing removed or renamed, the new ones at the end {secnames(Bo, L2)}")
r = Bo.post(B + f"/api/lists/{L2}/sections/from-template", json={"template_id": TO})
check(r.ok and r.json()["added"] == [], "#2073: a second time adds nothing")
check(Bo.post(B + f"/api/lists/{L2}/sections/from-template", json={"template_id": TP}).status_code == 404, "#2073: someone else's private template cannot be used")
check(Ve.post(B + f"/api/lists/{L1}/sections/from-template", json={"template_id": TO}).status_code == 403, "#2073: view only: no sections added")
check(A.patch(B + f"/api/section-templates/{TO}", json={"name": "Redaktion neu", "sections": ["A", "B"]}).json().get("sections") == ["A", "B"], "#2073: the creator changes it")
# another organisation / a person outside: 404
check(TO not in {x["id"] for x in Ca.get(B + "/api/section-templates").json()["templates"]}, "#2073: carl (other organisation) does not see it")
L3 = mklist(Ca, "Carls Liste", (), ORG2)
check(Ca.post(B + f"/api/lists/{L3}/sections/from-template", json={"template_id": TO}).status_code == 404, "#2073: carl cannot use it (404)")
check(Ca.patch(B + f"/api/section-templates/{TO}", json={"name": "x"}).status_code == 404, "#2073: carl cannot change it (404)")
check(Ca.delete(B + f"/api/section-templates/{TO}").status_code == 404, "#2073: carl cannot delete it (404)")
check(Ca.post(B + "/api/section-templates", json={"name": "x", "sections": ["X"], "space": f"org:{ORG}"}).status_code == 404, "#2073: carl cannot save into Alpha (404)")
check(Ca.post(B + f"/api/lists/{L1}/sections/from-template", json={"template_id": TO}).status_code == 404, "#2073: carl cannot add to Alpha's list (404)")
# agents and API tokens: the app only
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
r = A.post(B + "/api/me/tokens", json={"name": "t1", "scopes": ["read", "write", "private"]})
PTH = {"Authorization": "Bearer " + r.json()["token"], **H}
for who, hd in (("agent", AGH), ("API token", PTH)):
    check(requests.get(B + "/api/section-templates", headers=hd).status_code in (401, 403), f"#2073: {who}: no templates")
    check(requests.post(B + f"/api/lists/{L1}/sections/from-template", headers=hd, json={"template_id": TO}).status_code in (401, 403), f"#2073: {who}: no applying")
# the creator / an admin deletes it
check(A.delete(B + f"/api/section-templates/{TO}").ok and TO not in {x["id"] for x in Bo.get(B + "/api/section-templates").json()["templates"]}, "#2073: deleted, gone for the members")

# ================================================================ a person without an organisation (freelancer-matrix: sectpl)
FID, Fr = freelancer(B, A)
LF = mklist(Fr, "Freie Liste", ("Anfrage", "Angebot"))
check(Fr.patch(B + f"/api/lists/{LF}", json={"view": "calendar"}).ok, "freelancer #2071: the calendar view of an own list")
check(Fr.patch(B + "/api/settings", json={"mine_board": "1", "mine_board_by": "due", "sections_closed": "[]"}).ok, "freelancer #2072 #2073: the settings")
r = Fr.post(B + "/api/section-templates", json={"name": "Vertrieb", "list_id": LF})
check(r.ok and r.json()["space"] == "private" and r.json()["can_edit"], f"freelancer #2073: an own template {r.status_code} {r.text[:200]}")
TF = r.json()["id"]
LF2 = mklist(Fr, "Zweite Liste")
r = Fr.post(B + f"/api/lists/{LF2}/sections/from-template", json={"template_id": TF})
check(r.ok and len(r.json()["added"]) == 2, "freelancer #2073: applied to another own list")
check(Fr.post(B + "/api/section-templates", json={"name": "x", "sections": ["X"], "space": f"org:{ORG}"}).status_code == 404, "freelancer: no organisation space (404)")
check({x["id"] for x in Fr.get(B + "/api/section-templates").json()["templates"]} == {TF}, "freelancer: sees only the own template")
check(Fr.patch(B + f"/api/section-templates/{TF}", json={"sections": ["Anfrage"]}).ok and Fr.delete(B + f"/api/section-templates/{TF}").ok, "freelancer: changes and deletes the own template")

print(f"p2156_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
