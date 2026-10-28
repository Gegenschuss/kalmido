#!/usr/bin/env python3
"""2.352.0 F (#2748): the review fixes of the projects folders (lists/lffolder.py, files/web.py). Invented names only.
 - H1 an editor of a list (not its owner / an admin) may not file it into a folder of their own nor share a folder holding it
 - H2 PATCH /api/files/shares/<sid> with only list_role is checked like a share (the folder's owner is no list admin: 403)
 - H3 renaming / moving a projects folder is its owner's (an editor of the folder: 403); a rename that would merge the
   owner's folders of another tree is refused (409), the private folders stay apart
 - M1 a list's node taken out of a folder needs edit on that folder; a move deeper than the file store allows: 409
 - M2 a folder made inside someone else's folder belongs to that folder's owner
 - M6 PUT /api/folders/people with a new role keeps a person's own share of a list (revoking the folder later keeps it)
 - freelancer-matrix: lists (a person without an organisation: her own folders, rename, subfolder owner, depth)
usage: p2352_f_review_test.py <datadir>"""
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
DATA = sys.argv[1]
if not os.environ.get("P2352F_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, capture_output=True, text=True)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, FAILS, OKS, check, dbx, sess  # noqa: E402

assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "collab,files,comments"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl", "dora"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} " + r.text[:200])
    uid[u] = r.json().get("id")
S = {u: sess(u) for u in ("bob", "carl", "dora")}
for s in S.values():
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})


def lists_of(s):
    return {l["id"]: l for l in s.get(B + "/api/state").json()["lists"]}


def mem(lid, who):
    """alice's view of a member: role or None."""
    m = next((x for x in lists_of(A)[lid].get("members", []) if x["user_id"] == uid[who]), None)
    return m["role"] if m else None


def new_list(s, name, folder="", org=ORG):
    r = s.post(B + "/api/lists", json={"name": name, "folder": folder, "org_id": org})
    check(r.ok, f"setup: list {name} " + r.text[:200])
    return r.json()["id"]


def space(s, org=ORG):
    return next(sp for sp in s.get(B + "/api/lists/tree").json()["spaces"] if sp["org_id"] == org)


def lnode(s, lid, org=ORG):
    return next(x["node_id"] for x in space(s, org)["lists"] if x["list_id"] == lid)


def fnode(s, path, org=ORG):
    return next((f for f in space(s, org)["folders"] if f["path"] == path), None)


def mkdir(s, parent, name):
    r = s.post(B + "/api/lists/folders", json={"parent_id": parent, "name": name})
    check(r.status_code == 201, f"setup: folder {name} " + r.text[:200])
    return r.json().get("id")


# ---------------------------------------------------------------- H1: an editor files the list into a folder of their own
L = new_list(A, "Payroll")  # the organisation's projects root comes with its first list
ROOT = space(A)["root"]
check(A.put(B + f"/api/lists/{L}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob edits L")
FB = mkdir(S["bob"], space(S["bob"])["root"], "Bobs")
r = S["bob"].post(B + "/api/lists/tree/move", json={"node_id": lnode(S["bob"], L), "parent_id": FB})
check(r.status_code == 403, f"H1: an editor may not file the list into his folder ({r.status_code} {r.text[:120]})")
# alice (the list's owner, an admin of the organisation) files it there herself; bob then shares his folder
r = A.post(B + "/api/lists/tree/move", json={"node_id": lnode(A, L), "parent_id": FB})
check(r.ok, "setup: alice files L into bob's folder " + r.text[:200])
r = S["bob"].post(B + f"/api/files/nodes/{FB}/shares", json={"user_id": uid["carl"], "role": "edit", "list_role": "admin"})
check(r.status_code == 403 and mem(L, "carl") is None, f"H1: the folder's owner (an editor of L) cannot hand out admin on L ({r.status_code} {mem(L, 'carl')})")
r = S["bob"].post(B + f"/api/files/nodes/{FB}/shares", json={"user_id": uid["carl"], "role": "view"})
check(r.status_code == 403 and mem(L, "carl") is None, f"H1: ... nor share it at all, like sharing L itself ({r.status_code})")

# ---------------------------------------------------------------- H2: PATCH with only list_role
dbx("INSERT INTO fs_shares(node_id,user_id,role,created_by,created_at) VALUES(?,?,?,?,?)",
    (FB, uid["dora"], "view", uid["bob"], "2026-10-26T08:00:00Z"))
SID = dbx("SELECT id FROM fs_shares WHERE node_id=? AND user_id=?", (FB, uid["dora"]))[0][0]
r = S["bob"].patch(B + f"/api/files/shares/{SID}", json={"list_role": "admin"})
row = dbx("SELECT role, list_role FROM fs_shares WHERE id=?", (SID,))[0]
check(r.status_code == 403 and tuple(row) == ("view", None), f"H2: a list role alone is checked too ({r.status_code} {tuple(row)})")
r = A.patch(B + f"/api/files/shares/{SID}", json={"list_role": "edit"})
check(r.ok and mem(L, "dora") == "edit", f"H2: L's owner may set it ({r.status_code} {mem(L, 'dora')})")

# ---------------------------------------------------------------- H3: rename by the owner only, no merge across trees
FK = mkdir(A, ROOT, "Kunden")
LK = new_list(A, "Ledger", "Kunden")
check(A.post(B + f"/api/files/nodes/{FK}/shares", json={"user_id": uid["bob"], "role": "edit"}).status_code == 201, "setup: bob edits the folder")
r = S["bob"].patch(B + f"/api/files/nodes/{FK}", json={"name": "Team"})
check(r.status_code == 403 and lists_of(A)[LK]["folder"] == "Kunden", f"H3: an editor of the folder cannot rename it ({r.status_code})")
r = S["bob"].post(B + "/api/lists/tree/move", json={"node_id": FK, "parent_id": FB})
check(r.status_code in (403, 409) and lists_of(A)[LK]["folder"] == "Kunden", f"H3: ... nor move it ({r.status_code})")
PK = new_list(A, "Private K", "Kunden", org=None)
PT = new_list(A, "Private T", "Team", org=None)
r = A.patch(B + f"/api/files/nodes/{FK}", json={"name": "Team"})
ls = lists_of(A)
check(r.status_code == 409 and ls[PK]["folder"] == "Kunden" and ls[PT]["folder"] == "Team" and ls[LK]["folder"] == "Kunden",
      f"H3: a rename that would merge the private folders: 409, nothing mixed ({r.status_code} {ls[PK]['folder']!r} {ls[LK]['folder']!r})")
pk = fnode(A, "Kunden", None)
check(pk is not None and fnode(A, "Team", None) is not None and pk["id"] != fnode(A, "Team", None)["id"], "H3: the private folders stay two")
r = A.patch(B + f"/api/files/nodes/{FK}", json={"name": "Kunden 2026"})
check(r.ok and lists_of(A)[LK]["folder"] == "Kunden 2026" and lists_of(A)[PK]["folder"] == "Kunden 2026",
      f"H3: the owner renames it (no clash): the path follows in both trees ({r.status_code} {r.text[:120]})")
check(any(x[0] == "rename" for x in dbx("SELECT action FROM fs_log WHERE node_id=?", (FK,))), "the rename is in the history")

# ---------------------------------------------------------------- M2: a subfolder belongs to the folder's owner
r = S["bob"].post(B + "/api/lists/folders", json={"parent_id": FK, "name": "Inner"})
check(r.status_code == 201 and dbx("SELECT owner_id FROM fs_nodes WHERE id=?", (r.json().get("id"),))[0][0] == ALICE,
      f"M2: bob's subfolder in alice's folder is alice's ({r.status_code} {r.text[:120]})")
check(S["bob"].post(B + f"/api/files/nodes/{r.json().get('id')}/shares", json={"user_id": uid["carl"], "role": "edit"}).status_code == 403,
      "M2: ... so bob cannot share it on")

# ---------------------------------------------------------------- M1: out of a folder needs edit there; depth
FS = mkdir(A, ROOT, "Shared out")
LB = new_list(S["bob"], "Bobs plan")
check(S["bob"].put(B + f"/api/lists/{LB}/members", json={"user_id": ALICE, "role": "admin"}).ok, "setup: alice admin of bob's list")
check(A.post(B + "/api/lists/tree/move", json={"node_id": lnode(A, LB), "parent_id": FS}).ok, "setup: alice files it into her folder")
check(A.post(B + f"/api/files/nodes/{FS}/shares", json={"user_id": uid["carl"], "role": "view"}).status_code == 201 and mem(LB, "carl") == "view",
      "setup: carl sees it through alice's folder")
r = S["bob"].post(B + "/api/lists/tree/move", json={"node_id": lnode(S["bob"], LB), "parent_id": space(S["bob"])["root"]})
check(r.status_code == 403 and mem(LB, "carl") == "view", f"M1: bob (no edit on alice's folder) cannot take it out ({r.status_code})")
deep = ROOT
for i in range(25):
    deep = mkdir(A, deep, f"D{i}")
tall = top = mkdir(A, ROOT, "T0")
for i in range(1, 10):
    tall = mkdir(A, tall, f"T{i}")
r = A.post(B + "/api/lists/tree/move", json={"node_id": top, "parent_id": deep})
check(r.status_code == 409, f"M1: a move past the depth of the file store: 409 ({r.status_code} {r.text[:120]})")

# ---------------------------------------------------------------- M6: a new folder role keeps the own share
LM = new_list(A, "Mixed", "Mx")
check(A.put(B + f"/api/lists/{LM}/members", json={"user_id": uid["dora"], "role": "edit"}).ok, "setup: dora directly on LM")
check(A.put(B + "/api/folders/people", json={"folder": "Mx", "user_id": uid["dora"], "role": "view"}).ok, "setup: the folder with dora (view)")
r = A.put(B + "/api/folders/people", json={"folder": "Mx", "user_id": uid["dora"], "role": "admin"})
check(r.ok and mem(LM, "dora") == "admin", f"M6: the new role is set everywhere ({mem(LM, 'dora')})")
r = A.delete(B + "/api/folders/people", json={"folder": "Mx", "user_id": uid["dora"]})
check(r.ok and mem(LM, "dora") == "admin", f"M6: the folder revoked: her own share of LM stays ({mem(LM, 'dora')})")

# ---------------------------------------------------------------- N11: a folder in the trash is no folder key
FX = mkdir(A, ROOT, "Binned")
check(A.get(B + "/api/folders/props", params={"node": FX}).ok, "setup: node= of a live folder")
check(A.delete(B + f"/api/files/nodes/{FX}").ok, "setup: the folder into the trash")
r = A.get(B + "/api/folders/props", params={"node": FX})
check(r.status_code == 404, f"N11: node= of a folder in the trash: 404 ({r.status_code})")

# ---------------------------------------------------------------- N4: into the organisation with people only through folders
r = A.post(B + "/api/users", json={"orgs": [], "username": "eve", "display_name": "Eve", "password": "password123", "email": "eve@example.com"})
uid["eve"] = r.json().get("id")
LP = new_list(A, "Own notes", "Px", org=None)
PX = fnode(A, "Px", None)["id"]  # eve is no one alice may pick: her folder role as grp_sync writes it
dbx("INSERT INTO fs_shares(node_id,user_id,role,list_role,created_by,created_at) VALUES(?,?,?,?,?,?)",
    (PX, uid["eve"], "edit", "edit", ALICE, "2026-10-26T08:00:00Z"))
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,frole,folder,sort,added_at) VALUES(?,?,?,?,?,?,?,?)",
    (LP, uid["eve"], "edit", None, "edit", "", 0, "2026-10-26T08:00:00Z"))
check(mem(LP, "eve") == "edit", f"setup: eve (no organisation) through alice's private folder ({mem(LP, 'eve')})")
r = A.patch(B + f"/api/lists/{LP}", json={"org_id": ORG})
check(r.ok and mem(LP, "eve") is None, f"N4: the list goes into the organisation, eve's folder role ends there ({r.status_code} {r.text[:120]})")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: lists)
FID, Fr = freelancer(B, A)
PL = Fr.post(B + "/api/lists", json={"name": "Own job", "folder": "Jobs"}).json()["id"]
froot = space(Fr, None)["root"]
fj = fnode(Fr, "Jobs", None)
r = Fr.patch(B + f"/api/files/nodes/{fj['id']}", json={"name": "Work"})
check(r.ok and lists_of(Fr)[PL]["folder"] == "Work", "freelancer: she renames her own folder " + r.text[:120])
r = Fr.post(B + "/api/lists/folders", json={"parent_id": fj["id"], "name": "Inner"})
check(r.status_code == 201 and dbx("SELECT owner_id FROM fs_nodes WHERE id=?", (r.json()["id"],))[0][0] == FID, "freelancer: her subfolder is hers")
d = froot
for i in range(30):  # F29: 31 levels with the root, the deepest a new folder gets
    d = mkdir(Fr, d, f"F{i}")
r = Fr.post(B + "/api/lists/tree/move", json={"node_id": fj["id"], "parent_id": d})
check(r.status_code == 409, f"freelancer: too deep: 409 ({r.status_code})")
check(Fr.post(B + "/api/lists/tree/move", json={"node_id": lnode(Fr, PL, None), "parent_id": froot}).ok
      and lists_of(Fr)[PL]["folder"] == "", "freelancer: she takes her list out of her folder")

print(f"p2352_f_review: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
