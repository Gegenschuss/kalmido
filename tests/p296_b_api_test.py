#!/usr/bin/env python3
"""2.96.0 API tests, part B (#1941): knowledge pages / folders and tables to the other workspace (private <-> organisation),
own container (start.sh). Invented names only.
 - a folder with two sub-pages and a link: private -> organisation (into a target folder) and back; the link between the two
   follows the new path, the links to a page that stays are named by the dry run; the dry run changes nothing
 - a name taken in the target: 409 with the names (the dry run: block)
 - out of an organisation: a plain member may not move a page somebody else created (403), the organisation's admin may
 - another organisation (not a member): 409; a page of somebody else: 404; an agent: refused (tenant-matrix: wiki)
 - a space with the lock while it is being encrypted: refused with a clear message (dry run: block; the move: 409)
 - a table attached to a private list: private -> organisation ends the attachment (named), the move back (undo) restores it;
   a formula naming a private list is named; plain member 403, another organisation 409, an agent refused (tenant-matrix: sheet)
 - the last move shows on the page / the table (both sides)
 - a person without an organisation (freelancer-matrix: wiki, freelancer-matrix: sheets): there is no other workspace, 409
usage: p296_b_api_test.py <datadir>      (a fresh container; P296B_NOSTART=1 = the server already runs)"""
import base64
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "sheets,wiki,collab,comments"


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


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def b64u(n):
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def e2e_keys():
    return {"pub": {"kty": "EC", "crv": "P-256", "x": b64u(32), "y": b64u(32), "ext": True, "key_ops": []},
            "bundle_pass": {"v": 1, "kdf": "pbkdf2-sha256", "iter": 600000, "salt": b64(16), "iv": b64(12), "ct": b64(200)},
            "bundle_rec": {"v": 1, "kdf": "hkdf-sha256", "salt": b64(16), "iv": b64(12), "ct": b64(200)}}


if not os.environ.get("P296B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
for u in ("bob", "carol", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "frank" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ca, Fr = sess("bob"), sess("carol"), sess("frank")
for s in (A, Bo, Ca, Fr):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}


def mv(s, **b):
    return s.post(B + "/api/wiki/move-space", json=b)


def page(s, path, text="", space="private"):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def paths(s, space):
    return {p["path"]: p["id"] for p in s.get(B + "/api/wiki", params={"space": space}).json()["pages"]}


# ================================================================ knowledge pages (tenant-matrix: wiki)
ONE = page(Bo, "Plan/One", "See [[Plan/Two]] and [[Other]]")
TWO = page(Bo, "Plan/Two", "two")
OTHER = page(Bo, "Other", "back to [[Plan/One]]")

# the dry run: notes, nothing changes
r = mv(Bo, folder="Plan", space="private", to=SP, dest="", dry=1)
d = r.json() if r.ok else {}
check(r.ok and d.get("block") is None and d.get("count") == 2, "dry run of the folder: 2 pages, no block " + r.text[:300])
check(any("2 links point to the other workspace" in n for n in d.get("notes", [])), "dry run names the 2 links to / from Other " + str(d.get("notes")))
check("Plan/One" in paths(Bo, "private") and not paths(A, SP), "the dry run changed nothing")

# a name taken in the target
TAKEN = page(A, "Plan/Two", "", SP)
r = mv(Bo, folder="Plan", space="private", to=SP, dest="", dry=1)
check(r.ok and r.json().get("block") and "Plan/Two" in r.json().get("taken", []), "dry run: the taken name blocks " + r.text[:300])
r = mv(Bo, folder="Plan", space="private", to=SP, dest="")
check(r.status_code == 409 and "Plan/Two" in r.json().get("taken", []), "the move: 409 with the taken name " + r.text[:300])
check("Plan/One" in paths(Bo, "private"), "after the 409 nothing moved")

# into a folder of the organisation
r = mv(Bo, folder="Plan", space="private", to=SP, dest="Moved")
d = r.json() if r.ok else {}
check(r.ok and d.get("space") == SP and sorted(m["to"] for m in d.get("moved", [])) == ["Moved/Plan/One", "Moved/Plan/Two"],
      "private -> organisation into Moved/ " + r.text[:300])
op = paths(A, SP)
check(op.get("Moved/Plan/One") == ONE and op.get("Moved/Plan/Two") == TWO, "a member of the organisation sees the pages " + str(op))
check("Plan/One" not in paths(Bo, "private") and "Other" in paths(Bo, "private"), "gone from the private space, Other stays")
g = A.get(B + f"/api/wiki/pages/{ONE}").json()
check(g["body"] == "See [[Moved/Plan/Two]] and [[Other]]", "the link between the moved pages follows, the other stays as text: " + g["body"])
# 2.97.0 (#2051): alice reads it -- bob's private space shows without key or person, her organisation by name
check(g.get("moved") and g["moved"]["from"] is None and g["moved"]["from_name"] == "private space" and g["moved"]["to"] == SP
      and g["moved"]["to_name"] == "Alpha" and g["moved"]["by_name"] == "Bob", "the page shows its last move " + str(g.get("moved")))
check(Ca.get(B + f"/api/wiki/pages/{ONE}").ok, "another member reads it")
check(Fr.get(B + f"/api/wiki/pages/{ONE}").status_code == 404, "another organisation: 404")

# back (bob created the pages: he may move them out of the organisation)
r = mv(Bo, folder="Moved/Plan", space=SP, to="private", dest="")
check(r.ok and sorted(m["to"] for m in r.json().get("moved", [])) == ["Plan/One", "Plan/Two"], "organisation -> private back " + r.text[:300])
check(Bo.get(B + f"/api/wiki/pages/{ONE}").json()["body"] == "See [[Plan/Two]] and [[Other]]", "the link follows back")
check(A.get(B + f"/api/wiki/pages/{ONE}").status_code == 404, "the organisation does not see the private page any more")

# out of the organisation: a page somebody else created
DOC = page(A, "Team/Doc", "team text", SP)
r = mv(Bo, pages=[DOC], space=SP, to="private", dest="")
check(r.status_code == 403, "a plain member may not take a page alice created out of the organisation " + r.text[:200])
r = mv(Bo, pages=[DOC], space=SP, to="private", dest="", dry=1)
check(r.status_code == 403, "... also not in the dry run")
check(paths(A, SP).get("Team/Doc") == DOC, "the page stays in the organisation")
r = mv(A, pages=[DOC], space=SP, to="private", dest="Mine")
check(r.ok and paths(A, "private").get("Mine/Doc") == DOC, "the organisation's admin may (into her private folder) " + r.text[:200])
r = mv(A, pages=[DOC], space="private", to=SP, dest="Team")
check(r.ok and paths(A, SP).get("Team/Doc") == DOC, "and back")

# another organisation, somebody else's page, the same space, an agent
check(mv(Bo, pages=[OTHER], space="private", to=f"org:{BETA}").status_code == 409, "an organisation bob is not in: 409")
check(mv(Fr, pages=[OTHER], space="private", to=f"org:{BETA}").status_code == 404, "somebody else's private page: 404")
check(mv(Bo, pages=[OTHER], space="private", to="private").status_code == 409, "the same space: 409")
check(mv(Bo, pages="x", space="private", to=SP).status_code == 400, "pages not a list: 400")
r = requests.post(B + "/api/wiki/move-space", json={"pages": [OTHER], "space": "private", "to": SP}, headers=AGH)
check(r.status_code in (401, 403), "an agent: refused " + str(r.status_code))
check(paths(Bo, "private").get("Other") == OTHER, "after all refusals Other is still bob's")

# a space with the lock: refused with a clear message
# 2.97.0 (#2050): spaces with the lock move now (re-encrypted in the browser, p297_d_api); while the switch runs: busy
SEC = page(Ca, "Secret", "")
assert Ca.put(B + "/api/e2e/keys", json=e2e_keys()).ok
r = Ca.post(B + "/api/wiki/e2e/start", json={"space": "private", "keys": [{"user_id": uid["carol"], "wrapped": {"v": 1, "iv": b64(12), "ct": b64(48)}}]})
check(r.ok, "carol locks her private space " + r.text[:200])
r = mv(Ca, pages=[SEC], space="private", to=SP, dry=1)
check(r.ok and "being encrypted" in (r.json().get("block") or ""), "the lock: the dry run blocks with a clear message " + r.text[:200])
r = mv(Ca, pages=[SEC], space="private", to=SP)
check(r.status_code == 409 and "being encrypted" in r.json().get("error", ""), "the lock: the move 409 " + r.text[:200])
check(not paths(A, SP).get("Secret"), "nothing of the locked space reached the organisation")


# ================================================================ tables (tenant-matrix: sheet)
def smv(s, sid, **b):
    return s.post(B + f"/api/sheets/{sid}/move-space", json=b)


L = Bo.post(B + "/api/lists", json={"name": "Bob Plan", "org_id": None}).json()["id"]
r = Bo.post(B + "/api/sheets", json={"title": "Budget", "space": "private", "list_id": L})
assert r.status_code == 201, r.text
SID = r.json()["id"]
r = Bo.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"cell": "A1", "raw": "=liste.bob_plan.aufgaben"}, {"cell": "A2", "raw": "5"}]})
check(r.ok, "a formula naming the private list " + r.text[:200])
r = smv(Bo, SID, to=SP, dry=1)
d = r.json() if r.ok else {}
notes = " | ".join(d.get("notes", []))
check(r.ok and d.get("block") is None and "no longer attached" in notes, "dry run: the list attachment ends " + r.text[:300])
check("1 formula" in notes, "dry run: the formula naming the private list " + notes)
check(Bo.get(B + f"/api/sheets/{SID}").json()["space"] == "private", "the dry run changed nothing")
r = smv(Bo, SID, to=SP)
d = r.json() if r.ok else {}
check(r.ok and d.get("space") == SP and d["sheet"]["list_id"] is None and d.get("move_id"), "private -> organisation, detached " + r.text[:300])
g = A.get(B + f"/api/sheets/{SID}")
check(g.ok and g.json()["space"] == SP, "a member of the organisation reads the table")
# 2.97.0 (#2051): alice did not move it -- bob's private space shows without its key or person
check(g.ok and (g.json().get("moved") or {}).get("from") is None and g.json()["moved"].get("from_name") == "private space",
      "the table shows its last move " + str(g.json().get("moved") if g.ok else ""))
check(Fr.get(B + f"/api/sheets/{SID}").status_code == 404, "another organisation: 404")
check(smv(Ca, SID, to="private").status_code == 403, "a plain member may not take bob's table out of the organisation")
check(smv(Bo, SID, to=f"org:{BETA}").status_code == 409, "an organisation bob is not in: 409")
check(smv(Bo, SID, to=SP).status_code == 409, "the same space: 409")
r = requests.post(B + f"/api/sheets/{SID}/move-space", json={"to": "private"}, headers=AGH)
check(r.status_code in (401, 403, 404), "an agent: refused " + str(r.status_code))
# the move back (undo) brings the attachment back
r = smv(Bo, SID, to="private", undo=d.get("move_id"))
check(r.ok and r.json()["sheet"]["space"] == "private" and r.json()["sheet"]["list_id"] == L, "undo: back with the list attached " + r.text[:300])
check(A.get(B + f"/api/sheets/{SID}").status_code == 404, "the organisation does not see it any more")
# an undo id of somebody else's move does nothing extra
r = smv(Bo, SID, to=SP)
mid = r.json().get("move_id")
check(smv(Ca, SID, to="private", undo=mid).status_code == 403, "carol cannot take it back with bob's move id")
r = smv(Bo, SID, to="private", undo="x")
check(r.status_code == 400, "undo not a number: 400")
check(smv(Bo, SID, to="private", undo=mid).ok, "bob takes it back")
# the organisation's admin may move a member's organisation table out
r = Bo.post(B + "/api/sheets", json={"title": "Team table", "space": SP})
TS = r.json()["id"]
check(smv(A, TS, to="private").ok and A.get(B + f"/api/sheets/{TS}").json()["space"] == "private", "the admin moves it out")
check(Bo.get(B + f"/api/sheets/{TS}").status_code == 404, "... then it is hers alone")

# ================================================================ a person without an organisation
# freelancer-matrix: wiki
# freelancer-matrix: sheets
FID, Fl = freelancer(B, A, features=FEATURES + ",sheets")
FP = page(Fl, "Notes/Idea", "an idea")
check(mv(Fl, pages=[FP], space="private", to=SP).status_code == 409, "freelancer: no organisation to move a page to (409)")
check(mv(Fl, folder="Notes", space="private", to="private").status_code == 409, "freelancer: the private space is the only one (409)")
r = mv(Fl, pages=[FP], space="private", to=SP, dry=1)
check(r.status_code == 409, "freelancer: also the dry run 409")
FS = Fl.post(B + "/api/sheets", json={"title": "Mine", "space": "private"}).json()["id"]
check(smv(Fl, FS, to=SP).status_code == 409, "freelancer: no organisation to move a table to (409)")
check(smv(Fl, FS, to="private", dry=1).status_code == 409, "freelancer: the same space 409")
check(Fl.get(B + f"/api/wiki/pages/{FP}").ok and Fl.get(B + f"/api/sheets/{FS}").json()["space"] == "private", "freelancer: everything stays")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
