#!/usr/bin/env python3
"""2.199.0 C (#2742): tables in folders (sheets/shfolder.py, files/fsroots.py). Invented names only.
 - the tables' folders: the first folder makes the root "Tables" of the workspace (GET / POST /api/sheets/folders); a new
   table straight into a folder (folder_id); renaming the table renames its node
 - a folder share (view / edit) gives read / write on the tables in it -- also through a folder above and for tables filed
   later; never the owner's rights (delete, share, move); moving the table out and revoking the share take it away
 - sheet_shares and folder: the higher right counts
 - a table attached to a project the person does not see: the folder never opens it (hidden)
 - deleting a folder: its tables go into the tables' trash and come back with it; a table the deleting person may not delete
   moves one level up (kept)
 - agents: only with a share on exactly them (the organisation's root is open to every person, never to agents); read only
   with view; another organisation never
 - moving the table to another workspace removes its node
 - freelancer-matrix: sheets (a person without an organisation: private folder, her own agent)
 - tenant-matrix: sheet_folder (another organisation: 404 on the folders, never filed across)
usage: p2199_c_sheets_test.py <datadir>      (a fresh container; P2199C_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FEAT = "sheets,collab,comments,files"

if not os.environ.get("P2199C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "carol", "olga"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "olga" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["olga"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ca, Ol = sess("bob"), sess("carol"), sess("olga")
for s in (A, Bo, Ca, Ol):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def agent(name, org=None, owner=None):
    body = {"scopes": ["read", "sheets:read", "sheets:write"], "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


def new(s, title, space="private", **b):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space, **b})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def folder(s, name, space="private", parent=None):
    r = s.post(B + "/api/sheets/folders", json={"name": name, "space": space, **({"parent_id": parent} if parent else {})})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["folder"]["id"]


def place(s, sid, parent):
    return s.post(B + "/api/files/refs", json={"ref_kind": "sheet", "ref_id": sid, "parent_id": parent}).status_code


def fshare(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def can(s, sid):
    """None (no access) | 'read' | 'write' for the web routes."""
    r = s.get(B + f"/api/sheets/{sid}")
    if not r.ok:
        return None
    return "write" if r.json().get("can_write") else "read"


def cell(s, sid, raw="1", base=V, path="/cells"):
    return s.put(base + f"/sheets/{sid}{path}", json={"cells": [{"cell": "A1", "raw": raw}]}).status_code


def wcell(s, sid, raw="1"):
    return s.put(B + f"/api/sheets/{sid}/cells", json={"cells": [{"cell": "A1", "raw": raw}]}).status_code


def idx(s, space="all"):
    r = s.get(B + "/api/sheets", params={"space": space})
    return {x["id"]: x for x in r.json()["sheets"]} if r.ok else {}


def tree(s):
    r = s.get(B + "/api/sheets/folders")
    return r.json() if r.ok else {}


# ================================================================ the root, folders, a new table in a folder, renaming
t = tree(A)
check(t and all(x["root"] is None for x in t["spaces"]) and t["folders"] == [] and {x["space"] for x in t["spaces"]} == {"private", SP},
      f"no root before the first folder {t}")
F1 = folder(A, "Budgets")
F2 = folder(A, "Q1", parent=F1)
t = tree(A)
root = next(x["root"] for x in t["spaces"] if x["space"] == "private")
check(root and [f["id"] for f in t["folders"]] == [F1, F2] and t["folders"][0]["parent_id"] == root, f"the root 'Tables' holds the folders {t}")
check(A.get(B + f"/api/files/nodes/{root}").json().get("name") == "Tables", "the root is called Tables (English)")
check(A.patch(B + f"/api/files/nodes/{root}", json={"name": "My sheets"}).ok and folder(A, "Taxes") and
      next(x["root"] for x in tree(A)["spaces"] if x["space"] == "private") == root, "renaming the root keeps it")
T1 = new(A, "Travel costs")
check(place(A, T1, F1) == 200, "alice files her table into Budgets")
check(idx(A)[T1]["folder_id"] == F1, "the index names its folder")
T2 = new(A, "Q1 plan", folder_id=F2)
check(idx(A)[T2]["folder_id"] == F2, "a new table straight into Q1")
check(A.patch(B + f"/api/sheets/{T1}", json={"title": "Travel 2026"}).ok
      and A.get(B + f"/api/files/refs/sheet/{T1}").json()["node"]["name"] == "Travel 2026", "renaming the table renames its node")

# ================================================================ folder shares: read / write, below, later, out, revoked
check(can(Bo, T1) is None and T1 not in idx(Bo), "not shared yet: bob nothing")
S1 = fshare(A, F1, user_id=uid["bob"], role="view")
check(can(Bo, T1) == "read" and can(Bo, T2) == "read", "a view share of Budgets: bob reads both (Q1 below it too)")
b = idx(Bo)
check(T1 in b and b[T1]["shared_in"] is True and b[T1].get("folder_in") is True and T1 in idx(Bo, "shared"), f"bob's index: shared through the folder {b.get(T1)}")
check(wcell(Bo, T1) == 403, "view: bob does not write")
check(A.patch(B + f"/api/files/shares/{S1}", json={"role": "edit"}).ok and can(Bo, T1) == "write" and wcell(Bo, T1) == 200, "edit: bob writes")
T3 = new(A, "Filed later")
check(can(Bo, T3) is None and place(A, T3, F2) == 200 and can(Bo, T3) == "write", "filed later into Q1: bob writes")
for m, p, body in [("DELETE", "", None), ("POST", "/shares", {"user_id": uid["carol"], "role": "read"}), ("POST", "/move-space", {"to": SP})]:
    r = Bo.request(m, B + f"/api/sheets/{T1}{p}", json=body)
    check(r.status_code in (403, 404), f"a folder never makes bob the owner: {m} {p} -> {r.status_code}")
g = Bo.get(B + f"/api/sheets/{T1}").json()
check(g.get("shared_in") is True and g.get("can_share") is False, "the table tells bob it is not his")
check(place(A, T3, None) == 200 and can(Bo, T3) is None, "taken out of the folder: bob nothing")
check(A.delete(B + f"/api/files/shares/{S1}").ok and can(Bo, T1) is None and can(Bo, T2) is None, "share revoked: bob nothing")

# ================================================================ sheet_shares and folder: the higher right
check(A.post(B + f"/api/sheets/{T1}/shares", json={"user_id": uid["bob"], "role": "read"}).status_code == 201, "setup: T1 shared with bob to read")
S2 = fshare(A, F1, user_id=uid["bob"], role="edit")
check(can(Bo, T1) == "write", "sheet share read + folder edit: write")
check(A.patch(B + f"/api/files/shares/{S2}", json={"role": "view"}).ok and can(Bo, T1) == "read", "both read: read")
A.delete(B + f"/api/files/shares/{S2}")
check(can(Bo, T1) == "read", "the sheet share stays on its own")

# ================================================================ a project's table: the folder share opens it (like a sheet share)
L = A.post(B + "/api/lists", json={"name": "Alice private", "org_id": None}).json()["id"]
T4 = new(A, "Project costs", list_id=L, folder_id=F1)
check(can(Bo, T4) is None, "setup: bob does not see alice's project nor its table")
S3 = fshare(A, F1, user_id=uid["bob"], role="edit")
check(can(Bo, T4) == "write" and T4 in idx(Bo), "the folder share opens the project's table to bob")
check(Bo.patch(B + f"/api/sheets/{T4}", json={"list_id": None}).status_code == 403, "... but never its project (detaching)")
check(can(Bo, T2) == "write", "the other tables of the folder too")

# ================================================================ trash: tables go along, protected ones move up
check(A.delete(B + f"/api/files/nodes/{F2}").ok and A.get(B + f"/api/sheets/{T2}").status_code == 404, "Q1 into the trash: its table too")
check(A.post(B + f"/api/files/nodes/{F2}/restore").ok and can(A, T2) == "write" and can(Bo, T2) == "write", "restored with the folder")
F3 = folder(A, "Bob's corner", parent=F1)
T5 = new(A, "Alice's in bob's corner", folder_id=F3)
r = Bo.delete(B + f"/api/files/nodes/{F3}")
kept = r.json().get("kept") if r.ok else r.text
check(r.ok and len(kept) == 1 and "delete" in kept[0]["reason"].lower(), f"bob deletes the folder: alice's table stays ({r.status_code} {kept})")
check(can(A, T5) == "write" and A.get(B + f"/api/files/refs/sheet/{T5}").json()["node"]["parent_id"] == F1, "... one level up, not in the trash")
A.delete(B + f"/api/files/shares/{S3}")

# ================================================================ the organisation: members through the space, agents only with a share
TA, ta = agent("alphabot", org=ORG)
BB, bb = agent("betabot", org=BETA)
OF = folder(A, "Shared plans", space=SP)
t = tree(Bo)
check(any(x["space"] == SP and x["root"] and x["can_add"] for x in t["spaces"]) and OF not in [f["id"] for f in t["folders"]],
      f"bob (member) may add folders, alice's folder stays hers until shared {t}")
OB = folder(Bo, "Bob's plans", space=SP)
t = tree(Bo)
check([f["role"] for f in t["folders"] if f["id"] == OB] == ["owner"] and OB not in [f["id"] for f in tree(Ca)["folders"]],
      "bob's folder at the top is his (carol does not see it)")
OBT = new(Bo, "Bob's org table", space=SP, list_id=Bo.post(B + "/api/lists", json={"name": "Bob board", "org_id": ORG}).json()["id"], folder_id=OB)
check(can(Ca, OBT) is None, "setup: carol does not see bob's project table")
r = Bo.patch(B + f"/api/files/nodes/{OB}", json={"org_access": "view"})
check(r.ok and can(Ca, OBT) == "read", f"bob opens his folder to every member: carol reads the project's table ({r.status_code})")
OT = new(A, "Org budget", space=SP, folder_id=OF)
check(can(Ca, OT) == "write", "a member writes as before (the space)")
check(ta.get(V + f"/sheets/{OT}").status_code == 404, "the organisation's folders give the agent nothing")
fshare(A, OF, agent_id=TA, role="view")
check(ta.get(V + f"/sheets/{OT}").ok and OT in [x["id"] for x in ta.get(V + "/sheets").json().get("data", [])],
      "a share with the agent: it reads the table (and lists it)")
check(cell(ta, OT) == 403, "view: the agent does not write")
check(bb.get(V + f"/sheets/{OT}").status_code == 404, "the other organisation's agent: never")
check(Ol.get(B + f"/api/sheets/{OT}").status_code == 404 and place(Ol, OT, None) == 404, "olga (other organisation): 404")
# tenant-matrix: sheet_folder
r = Ol.post(B + "/api/sheets/folders", json={"name": "Sneak", "parent_id": OF})
check(r.status_code == 404, f"olga cannot add into Alpha's folder ({r.status_code})")
OLF = folder(Ol, "Beta plans", space=f"org:{BETA}")
check(place(A, OT, OLF) == 404 and place(A, T1, OF) == 409, "never filed across workspaces")
check(not any(f["id"] == OF for f in tree(Ol).get("folders", [])), "olga's tree does not show Alpha's folders")

# ================================================================ moving the table to another workspace removes its node
check(A.post(B + f"/api/sheets/{T5}/move-space", json={"to": SP}).ok and A.get(B + f"/api/files/refs/sheet/{T5}").json().get("node") is None,
      "moved into the organisation: no node left in the private folder")

# ================================================================ a person without an organisation
# freelancer-matrix: sheets
FID, Fl = freelancer(B, A, features=FEATURES + ",sheets")
DA, da = agent("fridabot", owner=FID)
t = tree(Fl)
check([x["space"] for x in t.get("spaces", [])] == ["private"], f"freelancer: only her private tables {t}")
FF = folder(Fl, "Clients")
FT = new(Fl, "Rates", folder_id=FF)
check(idx(Fl)[FT]["folder_id"] == FF, "freelancer: a table in her folder")
check(da.get(V + f"/sheets/{FT}").status_code == 404, "her agent: nothing without a share")
fshare(Fl, FF, agent_id=DA, role="edit")
check(da.get(V + f"/sheets/{FT}").ok and cell(da, FT) == 200, "her agent with an edit share: reads and writes")
check(Fl.delete(B + f"/api/files/nodes/{FF}").ok and Fl.get(B + f"/api/sheets/{FT}").status_code == 404, "her folder into the trash: the table too")
check(Fl.post(B + f"/api/files/nodes/{FF}/restore").ok and Fl.get(B + f"/api/sheets/{FT}").ok, "and back")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
