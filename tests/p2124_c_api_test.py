#!/usr/bin/env python3
"""2.124.0 API tests, part C (#2113): one table shared with single people / agents (read | write), own container (start.sh).
Invented names only.
 - a private table shared with a person of the same organisation (read): she reads and exports it, sees it under "shared"
   (shared_in), but never writes (cells, rows, columns, rename, freeze, names, agent undo, step 2), never deletes, attaches,
   moves or re-shares it; the owner's other tables stay hidden (index, open, completion)
 - the role "write": cells / rename go through; delete, attach to a list, the trash, step 2 and managing the shares stay with
   the owner; stop sharing works at once, sharing again (Undo) brings the same share back
 - a table in the trash: the recipient does not see it (nor restores it); restored, the share counts again
 - an organisation's table attached to a list: a member without the list sees the table through the share, not the list
 - agents: an agent of the organisation sees the table in API v1 only with a share (read: no writing), an agent of another
   organisation never (409, 404); stopping the share ends its access
 - strangers: a person of another organisation cannot get a share (409; by e-mail: nothing happens, nothing revealed) and
   gets 404 on every share route (tenant-matrix: sheet_share)
 - moving the table to the organisation ends its shares (the dry run names them); leaving the organisation ends them too
 - a person without an organisation shares a private table by e-mail address and with the own agent (freelancer-matrix: sheets)
usage: p2124_c_api_test.py <datadir>      (a fresh container; P2124C_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "sheets,collab,comments,office"


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


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


if not os.environ.get("P2124C_NOSTART"):
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
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "erin" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["erin"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ca, Er = sess("bob"), sess("carol"), sess("erin")
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
SW = ["read", "sheets:read", "sheets:write"]


def agent(name, org=None, owner=None):
    body = {"scopes": SW, "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


TA, ta = agent("alphabot", org=ORG)
NA, na = agent("idlebot", org=ORG)
BB, bb = agent("betabot", org=BETA)


def share(s, sid, **b):
    return s.post(B + f"/api/sheets/{sid}/shares", json=b)


def shares(s, sid):
    return s.get(B + f"/api/sheets/{sid}/shares")


def ids(s, space="all"):
    r = s.get(B + "/api/sheets", params={"space": space})
    return {x["id"]: x for x in r.json()["sheets"]} if r.ok else {}


def new(s, title, space="private", **b):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space, **b})
    assert r.status_code == 201, r.text
    return r.json()


# ================================================================ a private table shared to read
d = new(Bo, "Plan")
SID = d["id"]
COL, ROW = d["columns"][0]["id"], d["rows"][0]["id"]
CELL = {"row_id": ROW, "col_id": COL}
check(Bo.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{**CELL, "raw": "42"}]}).ok, "setup: a value")
SECRET = new(Bo, "Secret salaries")["id"]
r = shares(Bo, SID)
t = r.json() if r.ok else {}
check(r.ok and any(p["id"] == uid["carol"] for p in t.get("people", [])), "the targets: carol of the same organisation " + r.text[:300])
check(not any(p["id"] == uid["erin"] for p in t.get("people", [])), "the targets: erin of another organisation is not offered")
check(any(a["id"] == TA for a in t.get("agents", [])) is False, "the targets: no organisation agent for a private table")
r = share(Bo, SID, user_id=uid["carol"], role="read")
check(r.status_code == 201 and [x["user_id"] for x in r.json()["shares"]] == [uid["carol"]], "bob shares with carol (read) " + r.text[:300])
SHC = r.json()["id"] if r.ok else 0
g = Ca.get(B + f"/api/sheets/{SID}")
gd = g.json() if g.ok else {}
check(g.ok and gd.get("can_write") is False and gd.get("shared_in") is True and gd.get("can_share") is False,
      "carol reads it, read only, only through the share " + g.text[:300])
check(any(x.get("raw") == "42" for x in gd.get("cells", [])), "carol sees the value")
check(Ca.get(B + f"/api/sheets/{SID}/export.csv").ok, "carol exports it")
check(Ca.get(B + f"/api/sheets/{SID}/vars").ok, "carol gets the completion")
check(Ca.post(B + f"/api/sheets/{SID}/presence", json={"cell_id": None}).ok, "carol's presence")
mine = ids(Ca)
check(SID in mine and mine[SID]["shared_in"] is True and SECRET not in mine, "carol's index: the shared table, not bob's other one")
check(set(ids(Ca, "shared")) == {SID}, "space=shared: exactly the shared table")
check(SID not in ids(Ca, "private"), "carol's private space does not hold bob's table")
check(Ca.get(B + f"/api/sheets/{SECRET}").status_code == 404, "bob's other private table: 404 for carol")
vs = Ca.get(B + f"/api/sheets/{SID}/vars").json().get("vars", [])
check(not any("salar" in (v.get("label") or "").lower() or "salar" in v.get("token", "") for v in vs), "the completion names no other table")
b = ids(Bo)
check(b.get(SID, {}).get("shared") == 1 and b[SID]["shared_in"] is False and b.get(SECRET, {}).get("shared") == 0, "bob's index: shared 1")
check(Bo.get(B + f"/api/sheets/{SID}").json().get("can_share") is True, "bob may manage the shares")
# reading never writes
W = [("PUT", f"/cells", {"cells": [{**CELL, "raw": "1"}]}), ("POST", "/rows", {}), ("POST", "/columns", {"title": "X"}),
     ("PATCH", "", {"title": "Mine now"}), ("DELETE", "", None), ("POST", f"/rows/order", {"ids": [ROW]}),
     ("PATCH", f"/columns/{COL}", {"title": "Y"}), ("DELETE", f"/rows/{ROW}", None), ("DELETE", f"/columns/{COL}", None),
     ("POST", "/to-tasks", {}), ("POST", "/rows-from-list", {}), ("POST", "/move-space", {"to": SP, "dry": 1})]
for m, p, body in W:
    r = Ca.request(m, B + f"/api/sheets/{SID}" + p, json=body)
    check(r.status_code == 403, f"read share: {m} {p or '/'} 403 ({r.status_code})")
cid = next((x["id"] for x in gd.get("cells", []) if x.get("raw") == "42"), 0)
check(Ca.post(B + f"/api/sheets/{SID}/cells/{cid}/freeze", json={"frozen": True}).status_code == 403, "read share: freeze 403")
check(Ca.post(B + f"/api/sheets/{SID}/cells/{cid}/name", json={"name": "x"}).status_code == 403, "read share: name 403")
check(Ca.post(B + f"/api/sheets/{SID}/batches/abc/undo").status_code in (403, 404), "read share: agent undo refused")
check(shares(Ca, SID).status_code == 403 and share(Ca, SID, user_id=uid["alice"], role="read").status_code == 403,
      "a recipient never manages / re-shares")
check(Bo.get(B + f"/api/sheets/{SID}").json()["title"] == "Plan", "nothing changed")

# ================================================================ write
r = Bo.patch(B + f"/api/sheets/{SID}/shares/{SHC}", json={"role": "write"})
check(r.ok and r.json()["shares"][0]["role"] == "write", "bob makes it write " + r.text[:200])
check(Bo.patch(B + f"/api/sheets/{SID}/shares/{SHC}", json={"role": "admin"}).status_code == 400, "an unknown role: 400")
r = Ca.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{**CELL, "raw": "43"}]})
check(r.ok, "write share: carol changes a cell " + r.text[:200])
check(Ca.patch(B + f"/api/sheets/{SID}", json={"title": "Plan 2"}).ok, "write share: rename")
check(Ca.get(B + f"/api/sheets/{SID}").json()["can_write"] is True, "write share: can_write")
L = Ca.post(B + "/api/lists", json={"name": "Carol private", "org_id": None}).json()["id"]
for m, p, body in [("DELETE", "", None), ("PATCH", "", {"list_id": L}), ("POST", "/to-tasks", {}), ("POST", "/move-space", {"to": SP})]:
    r = Ca.request(m, B + f"/api/sheets/{SID}" + p, json=body)
    check(r.status_code == 403, f"write share: {m} {p or '/'} stays with the owner ({r.status_code})")
check(Bo.get(B + f"/api/sheets/{SID}").json()["list_id"] is None, "not attached to carol's list")

# stop sharing works at once; sharing again (Undo) brings the same row back
r = Bo.delete(B + f"/api/sheets/{SID}/shares/{SHC}")
check(r.ok and r.json()["shares"] == [], "bob stops sharing")
check(Ca.get(B + f"/api/sheets/{SID}").status_code == 404 and SID not in ids(Ca), "carol: 404 at once, gone from her index")
check(Ca.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{**CELL, "raw": "1"}]}).status_code == 404, "carol: no writing after the stop")
check(Bo.delete(B + f"/api/sheets/{SID}/shares/{SHC}").status_code == 404, "stopping twice: 404")
r = share(Bo, SID, user_id=uid["carol"], role="write")
check(r.status_code == 201 and r.json().get("id") == SHC, "sharing again revives the same share " + r.text[:200])
check(Ca.get(B + f"/api/sheets/{SID}").ok, "carol reads it again")

# the trash
check(Bo.delete(B + f"/api/sheets/{SID}").ok, "bob deletes the table")
check(Ca.get(B + f"/api/sheets/{SID}").status_code == 404 and SID not in ids(Ca), "in the trash: the recipient does not see it")
check(Ca.post(B + f"/api/sheets/{SID}/restore").status_code == 404, "the recipient cannot restore it (404)")
check(Bo.post(B + f"/api/sheets/{SID}/restore").ok and Ca.get(B + f"/api/sheets/{SID}").ok, "restored: the share counts again")

# ================================================================ strangers (tenant-matrix: sheet_share)
check(share(Bo, SID, user_id=uid["erin"], role="read").status_code == 409, "a person of another organisation: 409")
check(Er.get(B + f"/api/sheets/{SID}").status_code == 404 and SID not in ids(Er, "shared"), "erin got nothing")
for m, p, body in [("GET", "/shares", None), ("POST", "/shares", {"user_id": uid["erin"], "role": "write"}),
                   ("PATCH", f"/shares/{SHC}", {"role": "read"}), ("DELETE", f"/shares/{SHC}", None)]:
    r = Er.request(m, B + f"/api/sheets/{SID}" + p, json=body)
    check(r.status_code == 404, f"stranger: {m} {p} 404 ({r.status_code})")
check(bb.get(V + f"/sheets/{SID}").status_code == 404, "another organisation's agent: 404")
check(share(Bo, SID, user_id=BB, role="read").status_code == 409, "another organisation's agent: 409")
check(share(Bo, SID, user_id=TA, role="read").status_code == 409, "an organisation's agent for a private table: 409")
check(share(Bo, SID, user_id=uid["bob"], role="read").status_code == 409, "the owner himself: 409")
check(share(Bo, SID, user_id="x", role="read").status_code == 400, "user_id not a number: 400")
check(share(Bo, SID, user_id=uid["carol"], role="owner").status_code == 400, "an unknown role: 400")

# ================================================================ an organisation's table, list, agents
OL = Bo.post(B + "/api/lists", json={"name": "Board only", "org_id": ORG}).json()["id"]
d = new(Bo, "Board budget", SP, list_id=OL)
OS = d["id"]
OCOL, OROW = d["columns"][0]["id"], d["rows"][0]["id"]
carol_sees_list = Ca.get(B + "/api/sheets", params={"list_id": OL}).status_code == 200
check(Ca.get(B + f"/api/sheets/{OS}").status_code == (200 if carol_sees_list else 404), "setup: the list decides for carol")
r = share(Bo, OS, user_id=uid["carol"], role="read")
check(r.status_code == 201, "the organisation's table shared with carol " + r.text[:200])
g = Ca.get(B + f"/api/sheets/{OS}")
check(g.ok, "carol reads the list's table through the share")
if not carol_sees_list:
    check(g.ok and g.json().get("list_title") is None, "... but not the list's name")
    check(Ca.get(B + "/api/sheets", params={"list_id": OL}).status_code == 404, "... and not the list's tables")
# agents
check(ta.get(V + f"/sheets/{OS}").status_code == 404 and OS not in [x["id"] for x in ta.get(V + "/sheets").json()["data"]],
      "the organisation's agent without a share sees nothing (as before)")
t = shares(Bo, OS).json()
check(any(a["id"] == TA for a in t.get("agents", [])) and not any(a["id"] == BB for a in t.get("agents", [])),
      "targets: the organisation's agents, not another's")
r = share(Bo, OS, user_id=TA, role="read")
SHA = r.json().get("id") if r.status_code == 201 else 0
check(r.status_code == 201, "shared with the organisation's agent (read) " + r.text[:200])
check(ta.get(V + f"/sheets/{OS}").ok and OS in [x["id"] for x in ta.get(V + "/sheets").json()["data"]], "the agent reads it in API v1")
check(ta.put(V + f"/sheets/{OS}/cells", json={"cells": [{"cell": "A1", "raw": "7"}]}).status_code == 403, "read: the agent cannot write")
check(ta.patch(V + f"/sheets/{OS}", json={"list_id": None}).status_code == 403, "the agent cannot detach it")
check(na.get(V + f"/sheets/{OS}").status_code == 404, "another agent without the share: 404")
Bo.patch(B + f"/api/sheets/{OS}/shares/{SHA}", json={"role": "write"})
r = ta.put(V + f"/sheets/{OS}/cells", json={"cells": [{"cell": "A1", "raw": "7"}]})
check(r.ok, "write: the agent writes (one batch) " + r.text[:200])
Bo.delete(B + f"/api/sheets/{OS}/shares/{SHA}")
check(ta.get(V + f"/sheets/{OS}").status_code == 404, "stopped: the agent's access ends at once")
check(share(Bo, OS, user_id=BB, role="read").status_code == 409, "another organisation's agent: 409")
check(share(Bo, OS, user_id=uid["erin"], role="read").status_code == 409, "an organisation's table: never a person outside it")
r = share(Bo, OS, email="erin@example.com", role="read")
check(r.status_code == 201 and r.json().get("by_email") is True, "by e-mail: the same answer " + r.text[:200])
r2 = share(Bo, OS, email="nobody@example.com", role="read")
check(r2.status_code == 201 and set(r2.json()) == set(r.json()) and r2.json()["shares"] == r.json()["shares"], "an unknown address: the same answer")
check(Er.get(B + f"/api/sheets/{OS}").status_code == 404 and not ids(Er, "shared"), "erin got nothing")

# ================================================================ moving ends the shares
P = new(Bo, "Trip")["id"]
check(share(Bo, P, user_id=uid["carol"], role="read").status_code == 201, "setup: a private table shared with carol")
r = Bo.post(B + f"/api/sheets/{P}/move-space", json={"to": SP, "dry": 1})
check(r.ok and any("share" in n for n in r.json().get("notes", [])), "the dry run names the share " + r.text[:300])
r = Bo.post(B + f"/api/sheets/{P}/move-space", json={"to": SP})
check(r.ok and shares(Bo, P).json()["shares"] == [], "after the move the share has ended " + r.text[:200])
check(ids(Ca).get(P, {}).get("shared_in") is False, "carol now sees it as a member of the organisation, not as a share")

# ================================================================ leaving the organisation ends the shares of its tables
r = A.delete(B + f"/api/orgs/{ORG}/members/{uid['carol']}")
check(r.ok, "carol leaves Alpha " + r.text[:200])
check(Ca.get(B + f"/api/sheets/{OS}").status_code == 404, "her share of the organisation's table ended")
check(not any(x["user_id"] == uid["carol"] for x in shares(Bo, OS).json()["shares"]), "... and is gone from the dialog")
check(Ca.get(B + f"/api/sheets/{SID}").ok, "bob's private table stays shared with her")

# ================================================================ a person without an organisation
# freelancer-matrix: sheets
FID, Fl = freelancer(B, A, features=FEATURES + ",sheets")
GID, Gl = freelancer(B, A, "fiona", features=FEATURES + ",sheets")
DA, da = agent("fridabot", owner=FID)
FS = new(Fl, "Freelance rates")["id"]
check(Fl.get(B + f"/api/sheets/{FS}").json().get("can_share") is True, "freelancer: her own admin, may share")
r = share(Fl, FS, email="fiona@example.com", role="read")
check(r.status_code == 201 and r.json().get("by_email") is True, "freelancer shares by e-mail " + r.text[:200])
check(Gl.get(B + f"/api/sheets/{FS}").ok and FS in ids(Gl, "shared"), "the other freelancer reads it under shared")
check(Gl.put(B + f"/api/sheets/{FS}/cells", json={"cells": [{"cell": "A1", "raw": "1"}]}).status_code == 403, "... read only")
t = shares(Fl, FS).json()
check(any(a["id"] == DA for a in t.get("agents", [])) and not any(a["id"] in (TA, BB) for a in t.get("agents", [])),
      "freelancer: her own agent is a target, no organisation agents")
check(share(Fl, FS, user_id=DA, role="write").status_code == 201, "freelancer shares with her own agent")
check(da.get(V + f"/sheets/{FS}").ok and da.put(V + f"/sheets/{FS}/cells", json={"cells": [{"cell": "A1", "raw": "3"}]}).ok,
      "her agent reads and writes it")
check(share(Fl, FS, user_id=TA, role="read").status_code == 409, "freelancer: an organisation's agent never")
sh = shares(Fl, FS).json()["shares"]
x = next((s for s in sh if s["user_id"] == GID), None)
check(x is not None and Fl.delete(B + f"/api/sheets/{FS}/shares/{x['id']}").ok and Gl.get(B + f"/api/sheets/{FS}").status_code == 404,
      "freelancer stops sharing: at once")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
