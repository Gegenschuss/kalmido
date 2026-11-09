#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.769.0 API tests (#5352): "Recently edited" over Knowledge, Files and Reading (GET /api/recent), own container (start.sh).
Invented data only.
 - ONE route: items of the three areas, newest first, each with area, workspace, title, who, when; limit (default 20, 1..50)
 - rights as the areas themselves: a member sees the organisation's page and read-later entry (a shared workspace), never the
   private ones of another person nor anything of another organisation; a file only when the file store lists it to the person
   (a share: workspace "shared"); ?space=org:<id> of a foreign organisation 404, a bad value 400
 - ?space= narrows to one workspace (the start page inside a workspace): nothing of another one, nothing shared from outside
 - an area the organisation's admins switch off gives nothing of that organisation; the person's own module switch the same
 - agents and API tokens: 403 (a view of the app)
 - a person without an organisation gets her own items in Private (freelancer-matrix: wiki)
tenant-matrix: recent
usage: p2769_d_recent_api_test.py <datadir>      (KMT_NOSTART=1 / P2769D_NOSTART=1: a running server)"""
import json
import sys

import requests

from freelancer_fixture import FEATURES, freelancer, login
from kt import B, check, done, fresh, setup

H = {"X-Requested-With": "kalmido"}
fresh(prefix="P2769D")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
ALICE = A.get(B + "/api/state").json()["me"]["id"]


def mkorg(name, admin):
    r = A.post(B + "/api/admin/orgs", json={"name": name, "admin_id": admin})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def mkuser(name, orgs):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com", "orgs": orgs})
    assert r.ok, r.text
    s = login(B, name)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})
    return r.json()["id"], s


def page(s, space, path):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": "Text of " + path})
    assert r.ok, r.text
    return r.json()["id"]


def upload(s, space, name):
    r = s.post(B + "/api/files/upload", data={"space": space}, files={"file": (name, b"content " + name.encode(), "text/plain")})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def later(s, space, title):
    r = s.post(B + "/api/reading", json={"url": "https://example.com/" + title.replace(" ", "-"), "title": title, "space": space})
    assert r.ok, r.text
    return r.json()["task_id"]


def recent(s, **params):
    r = s.get(B + "/api/recent", params=params)
    return r.json().get("items", []) if r.ok else None


def keys(items):
    return {(x["area"], x["id"]) for x in items or []}


ORG = mkorg("Nordwind", ALICE)
BOB, Bo = mkuser("bob", [ORG])
DORA, Do = mkuser("dora", [])
ORG2 = mkorg("Suedwind", DORA)
SP, SP2 = f"org:{ORG}", f"org:{ORG2}"

# ---- the content
P_PRIV = page(A, "private", "Personal/Diary")
P_ORG = page(A, SP, "Processes/Shoot day")
P_ORG2 = page(Do, SP2, "Secret plan")
F_PRIV = upload(A, "private", "alice-private.txt")
F_SHARED = upload(A, "private", "alice-for-bob.txt")
check(A.post(B + f"/api/files/nodes/{F_SHARED}/shares", json={"user_id": BOB, "role": "view"}).ok, "setup: alice shares a file with bob")
F_ORG = upload(A, SP, "nordwind-team.txt")
F_ORG2 = upload(Do, SP2, "suedwind.txt")
R_PRIV = later(A, "private", "Alice private read")
R_ORG = later(A, SP, "Team article")
R_ORG2 = later(Do, SP2, "Suedwind article")
P_BOB = page(Bo, SP, "Bob notes")  # the newest

# ================================================================== the owner: everything of her own, newest first
it = recent(A)
k = keys(it)
check({("wiki", P_PRIV), ("wiki", P_ORG), ("files", F_PRIV), ("files", F_ORG), ("reading", R_PRIV), ("reading", R_ORG)} <= k,
      f"#5352: alice sees her pages, files and read-later entries of both workspaces {sorted(k)}")
check(not k & {("wiki", P_ORG2), ("files", F_ORG2), ("reading", R_ORG2)}, "#5352: nothing of another organisation")
ats = [x["at"][:19] + (x["at"][19:23] if x["at"][19:20] == "." else ".000") for x in it]  # pages carry milliseconds
check(ats == sorted(ats, reverse=True), f"#5352: newest first {ats}")
x = next(x for x in it if x["area"] == "wiki" and x["id"] == P_ORG)
check(x["space"] == SP and x["title"] == "Shoot day" and x["place"] == "Processes" and x["by"] == ALICE and x["by_name"] and x["at"],
      f"#5352: a page: workspace, title, folder, who, when {x}")
x = next(x for x in it if x["area"] == "reading" and x["id"] == R_PRIV)
check(x["space"] == "private" and x["title"] == "Alice private read" and x["url"].startswith("https://example.com/"), f"#5352: a read-later entry {x}")
x = next(x for x in it if x["area"] == "files" and x["id"] == F_PRIV)
check(x["space"] == "private" and x["title"] == "alice-private.txt" and x["by"] == ALICE, f"#5352: a file {x}")
check(len(recent(A, limit=2)) == 2, "#5352: limit")
check(it[0]["area"] == "wiki" and it[0]["id"] == P_BOB and it[0]["by"] == BOB, f"#5352: bob's page on top for alice too {it[0]}")

# ================================================================== a member: the organisation's (shared workspace), never alice's private
it = recent(Bo)
k = keys(it)
check(("wiki", P_ORG) in k and ("reading", R_ORG) in k and ("wiki", P_BOB) in k, f"#5352: bob sees the organisation's page and read-later entry {sorted(k)}")
check(not k & {("wiki", P_PRIV), ("files", F_PRIV), ("reading", R_PRIV)}, "#5352: never alice's private page, file or read-later entry")
check(not k & {("wiki", P_ORG2), ("files", F_ORG2), ("reading", R_ORG2)}, "#5352: nothing of another organisation")
x = next((x for x in it if x["area"] == "files" and x["id"] == F_SHARED), None)
check(x and x["space"] == "shared", f"#5352: the file alice shared with him, as shared {x}")
listed = {n["id"] for n in Bo.get(B + "/api/files", params={"space": SP}).json().get("items", [])}
check((("files", F_ORG) in k) == (F_ORG in listed), f"#5352: the organisation's file exactly when the file store lists it to him ({F_ORG in listed})")

# one workspace: nothing of another one, nothing shared from outside
k = keys(recent(Bo, space=SP))
check(("wiki", P_ORG) in k and ("files", F_SHARED) not in k and all(x["space"] == SP for x in recent(Bo, space=SP)), f"#5352: ?space=org: only the organisation {sorted(k)}")
check(not keys(recent(Bo, space="private")) & {("wiki", P_ORG), ("reading", R_ORG)}, "#5352: ?space=private: nothing of the organisation")
check(Bo.get(B + "/api/recent", params={"space": SP2}).status_code == 404, "#5352: a foreign organisation 404")
check(Bo.get(B + "/api/recent", params={"space": "org:x"}).status_code == 400, "#5352: a bad space 400")
for lim in ("0", "51", "x"):
    check(Bo.get(B + "/api/recent", params={"limit": lim}).status_code == 400, f"#5352: limit {lim} 400")
check(Bo.get(B + "/api/recent", params={"areas": "wiki,mail"}).status_code == 400, "#5352: an unknown area 400")
check({x["area"] for x in recent(Bo, areas="wiki")} == {"wiki"}, "#5352: areas narrows")

# the other organisation's admin sees hers, nothing of Nordwind
k = keys(recent(Do))
check({("wiki", P_ORG2), ("files", F_ORG2), ("reading", R_ORG2)} <= k and not k & {("wiki", P_ORG), ("wiki", P_BOB), ("reading", R_ORG), ("files", F_ORG)},
      f"#5352: dora: only Suedwind {sorted(k)}")

# ================================================================== switched off: by the organisation's admins, by the person
check(A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": ["wiki", "reading"]}).ok, "setup: Nordwind switches Knowledge and Reading off")
k = keys(recent(Bo))
check(("wiki", P_ORG) not in k and ("reading", R_ORG) not in k and ("files", F_SHARED) in k, f"#5352: switched off: nothing of these areas of Nordwind {sorted(k)}")
A.patch(B + f"/api/orgs/{ORG}", json={"areas_off": []})
check(("wiki", P_ORG) in keys(recent(Bo)), "#5352: on again: there again")
Bo.patch(B + "/api/settings", json={"features": FEATURES.replace(",wiki", "")})
check(not any(x["area"] == "wiki" for x in recent(Bo)), "#5352: the person's module Knowledge off: no pages")
Bo.patch(B + "/api/settings", json={"features": FEATURES})

# ================================================================== a page deleted is gone
check(A.delete(B + f"/api/wiki/pages/{P_ORG}").ok, "setup: alice deletes the organisation's page")
check(("wiki", P_ORG) not in keys(recent(Bo)), "#5352: a deleted page is gone")

# ================================================================== the start page's block is a known block (settings.py DASH_WIDGETS)
r = Bo.patch(B + "/api/settings", json={"dashboard": json.dumps({"order": ["recent", "today"], "hidden": ["recent"]})})
check(r.ok, f"#5352: the start page's arrangement takes the block 'recent' {r.status_code} {r.text[:160]}")

# ================================================================== agents and API tokens: 403
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
r = A.post(B + "/api/me/tokens", json={"name": "t1", "scopes": ["read", "write", "private"]})
PTH = {"Authorization": "Bearer " + r.json()["token"], **H}
for who, hd in (("agent", AGH), ("API token", PTH)):
    check(requests.get(B + "/api/recent", headers=hd).status_code in (401, 403), f"#5352: {who}: 403")

# ================================================================== a person without an organisation (freelancer-matrix: wiki)
FID, Fl = freelancer(B, A)
FP = page(Fl, "private", "Ideas")
FF = upload(Fl, "private", "frida.txt")
FR = later(Fl, "private", "Frida read")
it = recent(Fl)
check(keys(it) == {("wiki", FP), ("files", FF), ("reading", FR)} and all(x["space"] == "private" for x in it), f"freelancer: her own three, in Private {it}")
check(keys(recent(Fl, space="private")) == keys(it), "freelancer: ?space=private the same")
check(Fl.get(B + "/api/recent", params={"space": SP}).status_code == 404, "freelancer: an organisation 404")

sys.exit(done("p2769_d_recent_api_test"))
