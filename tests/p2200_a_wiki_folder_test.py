#!/usr/bin/env python3
"""2.200.0 A (#2747): knowledge pages in folders of the file store (wiki/wkfolder.py, files/fsroots.py closed areas).
Invented names only.
 - migration from the paths: a space without nodes gets its root "Knowledge", folders from the path prefixes and one node per
   page (a folder with its own page: page "Alpha" and folder "Alpha" are siblings; a deep path of 12 parts); the page paths
   stay exactly as they were; a second index changes nothing
 - the check after a "rollback change": a path changed in the database / a page without its node -> the node moves / comes back
 - moving / renaming in the tree (the file store's routes) writes wiki_pages.path of the subtree, the [[links]] of the
   other pages and the wiki_shares; a taken name = 409 and nothing changes; POST /api/wiki/move keeps the folder node
 - empty folders (POST /api/wiki/folders, 409 for a taken name); no file / foreign folder into the knowledge tree, no page
   out of it (409)
 - a folder into the trash takes its pages into the knowledge trash, restoring brings them back
 - a locked space (wiki_spaces.e2e): no root, no nodes
 - an organisation: every member sees the folders (index and file store) as before, read-only people read, guests and
   another organisation see nothing (tenant-matrix: wiki)
 - freelancer-matrix: wiki (a person without an organisation: her own private tree, nobody else sees it)
usage: p2200_a_wiki_folder_test.py <datadir>      (a fresh container; P2200A_NOSTART=1 = the server already runs)"""
import io
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEAT = "wiki,files,collab,comments"

if not os.environ.get("P2200A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        if write:
            c.execute(q, args)
            c.commit()
            return None
        return c.execute(q, args).fetchall()
    finally:
        c.close()


s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u, role in (("bob", "member"), ("rita", "readonly"), ("gina", "guest"), ("olga", None)):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}] if role else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["olga"]})
assert r.status_code in (200, 201), r.text
Bo, Ri, Gi, Ol = sess("bob"), sess("rita"), sess("gina"), sess("olga")
for s in (A, Bo, Ri, Gi, Ol):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})


def page(s, path, text="", space=SP):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, (path, r.status_code, r.text)
    return r.json()["id"]


def idx(s, space=SP):
    r = s.get(B + "/api/wiki", params={"space": space})
    return r.json() if r.ok else {"status": r.status_code}


def path_of(pid):
    return sql("SELECT path FROM wiki_pages WHERE id=?", (pid,))[0][0]


def node_of(pid):
    r = sql("SELECT id, parent_id, name FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (pid,))
    return r[0] if r else None


def folder_path(nid):
    parts = []
    while nid:
        r = sql("SELECT parent_id, name FROM fs_nodes WHERE id=?", (nid,))[0]
        if r[0] is None:
            break
        parts.append(r[1])
        nid = r[0]
    return "/".join(reversed(parts))


def wiki_nodes():
    return sql("SELECT COUNT(*) FROM fs_nodes WHERE org_id=?", (ORG,))[0][0]


# ================================================================ migration from the paths
P1 = page(A, "Processes/Shoot day/Checklist", "see [[Alpha]] and [[Alpha/Beta]]")
P2 = page(A, "Alpha", "the folder's own page")
P3 = page(A, "Alpha/Beta")
DEEP = "/".join(f"L{i}" for i in range(1, 12)) + "/Bottom"
P4 = page(A, DEEP)
P5 = page(A, "Loose")
# as before 2.200: no node, no root (every node of the organisation's knowledge tree goes)
sql("DELETE FROM fs_nodes WHERE org_id=? AND kind='ref' AND ref_kind='wiki'", (ORG,), write=True)
sql("DELETE FROM fs_nodes WHERE id IN (SELECT node_id FROM fs_area_roots WHERE area='wiki' AND org_id=?)", (ORG,), write=True)
sql("DELETE FROM fs_area_roots WHERE area='wiki' AND org_id=?", (ORG,), write=True)
check(wiki_nodes() == 0, "setup: no knowledge nodes")
j = idx(A)
ROOT = j.get("root")
check(bool(ROOT) and sql("SELECT name, org_access FROM fs_nodes WHERE id=?", (ROOT,))[0] == ("Knowledge", "edit"),
      f"migration: the root 'Knowledge' opened to the organisation {ROOT}")
pg = {p["id"]: p for p in j.get("pages", [])}
check(all(pg.get(p, {}).get("node_id") for p in (P1, P2, P3, P4, P5)), "migration: every page has its node")
check(folder_path(node_of(P1)[1]) == "Processes/Shoot day" and node_of(P1)[2] == "Checklist", "migration: folders from the path")
check(node_of(P2)[1] == ROOT and node_of(P2)[2] == "Alpha", "folder with its own page: the page 'Alpha' lies at the top")
fa = node_of(P3)[1]
check(sql("SELECT parent_id, name, kind FROM fs_nodes WHERE id=?", (fa,))[0] == (ROOT, "Alpha", "folder"),
      "folder with its own page: the folder 'Alpha' is its sibling")
check(folder_path(node_of(P4)[1]) == DEEP.rsplit("/", 1)[0], "a path of 12 parts")
check([path_of(p) for p in (P1, P2, P3, P4, P5)] == ["Processes/Shoot day/Checklist", "Alpha", "Alpha/Beta", DEEP, "Loose"],
      "migration renames no page")
names = {f["path"] for f in j.get("folders", [])}
check({"Processes", "Processes/Shoot day", "Alpha"} <= names and pg[P1]["folder_id"] == node_of(P1)[1], "the index lists the folders")
before = wiki_nodes()
idx(A)
check(wiki_nodes() == before, "a second index changes nothing")

# ================================================================ after a rollback: paths changed / pages without a node
sql("UPDATE wiki_pages SET path='Elsewhere/Loose', updated_at='2026-12-01T00:00:00.000Z' WHERE id=?", (P5,), write=True)  # as a 2.199 rename
sql("DELETE FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (P3,), write=True)
sql("INSERT INTO wiki_pages(org_id, path, body, created_at, updated_at) VALUES(?, 'Older/New', '', '2026-01-01', '2026-01-01')",
    (ORG,), write=True)
P6 = (sql("SELECT id FROM wiki_pages WHERE org_id=? AND path='Older/New'", (ORG,)) or [[None]])[0][0]
idx(A)
check(folder_path(node_of(P5)[1]) == "Elsewhere", "rollback: a changed path moves the node")
check(node_of(P3) is not None and node_of(P3)[1] == fa, "rollback: a page without a node gets it back (into its folder)")
if P6:
    check(node_of(P6) is not None and folder_path(node_of(P6)[1]) == "Older", "rollback: a page made under 2.199 joins the tree")

# ================================================================ moving / renaming in the tree
FP = node_of(P1)[1]  # "Processes/Shoot day"
r = A.post(B + f"/api/files/nodes/{node_of(P2)[0]}/order", json={"parent_id": FP})
check(r.ok and path_of(P2) == "Processes/Shoot day/Alpha", f"drag a page into a folder: its path {r.status_code} {path_of(P2)}")
body1 = A.get(B + f"/api/wiki/pages/{P1}").json().get("body", "")
check("[[Processes/Shoot day/Alpha]]" in body1, f"the links of other pages follow: {body1!r}")
# the folder "Alpha" (with Beta) into Processes, renamed
r = A.patch(B + f"/api/files/nodes/{fa}", json={"name": "Greek"})
check(r.ok and path_of(P3) == "Greek/Beta", f"renaming a folder renames the pages below it {r.status_code} {path_of(P3)}")
check("[[Greek/Beta]]" in A.get(B + f"/api/wiki/pages/{P1}").json().get("body", ""), "links into a renamed folder follow")
r = A.post(B + f"/api/files/nodes/{fa}/order", json={"parent_id": node_of(P5)[1]})
check(r.ok and path_of(P3) == "Elsewhere/Greek/Beta", f"moving a folder by dragging {path_of(P3)}")
# a taken name: 409, nothing changes
PX = page(A, "Elsewhere/Checklist")
r = A.post(B + f"/api/files/nodes/{node_of(P1)[0]}/order", json={"parent_id": node_of(P5)[1]})
check(r.status_code == 409 and path_of(P1) == "Processes/Shoot day/Checklist" and folder_path(node_of(P1)[1]) == "Processes/Shoot day",
      f"a taken name: 409, nothing moved {r.status_code}")
# sorting among siblings keeps the paths
r = A.post(B + f"/api/files/nodes/{node_of(PX)[0]}/order", json={"before": node_of(P5)[0]})
check(r.ok and path_of(PX) == "Elsewhere/Checklist", "sorting by hand keeps the path")
# the old way: a name with "/" and POST /api/wiki/move
r = A.patch(B + f"/api/wiki/pages/{PX}", json={"path": "Processes/Checklist 2"})
check(r.ok and folder_path(node_of(PX)[1]) == "Processes", "a new name with '/' moves the node")
fproc = sql("SELECT id FROM fs_nodes WHERE parent_id=? AND name='Processes' AND kind='folder'", (ROOT,))[0][0]
r = A.post(B + "/api/wiki/move", json={"space": SP, "from": "Processes", "to": "Workflows"})
check(r.ok and sql("SELECT name FROM fs_nodes WHERE id=?", (fproc,))[0][0] == "Workflows" and path_of(P1) == "Workflows/Shoot day/Checklist",
      "POST /api/wiki/move: the folder node keeps its id and gets the new name")
check(node_of(P1)[1] == FP, "the pages stay in their folders")

# ================================================================ empty folders, the area's border
r = A.post(B + "/api/wiki/folders", json={"space": SP, "name": "Empty"})
check(r.status_code == 201, f"an empty folder {r.status_code} {r.text[:200]}")
FE = r.json()["folder"]["id"] if r.status_code == 201 else None
check(any(f["id"] == FE and f["parent_id"] is None for f in idx(A).get("folders", [])), "the empty folder is in the index")
check(A.post(B + "/api/wiki/folders", json={"space": SP, "name": "empty"}).status_code == 409, "a taken folder name: 409")
r = A.post(B + "/api/wiki/folders", json={"space": SP, "name": "Sub", "parent_id": FE})
check(r.status_code == 201 and r.json()["folder"]["path"] == "Empty/Sub", "a folder in a folder")
r = A.post(B + "/api/files/upload", data={"parent_id": str(FE)}, files={"file": ("note.txt", io.BytesIO(b"x"), "text/plain")})
check(r.status_code == 409, f"no file into a knowledge folder: {r.status_code}")
r = A.post(B + "/api/files/folders", json={"space": SP, "name": "Plain"})
FPLAIN = r.json().get("id") if r.ok else None
check(A.patch(B + f"/api/files/nodes/{FPLAIN}", json={"parent_id": FE}).status_code == 409, "no foreign folder into the tree")
check(A.patch(B + f"/api/files/nodes/{FE}", json={"parent_id": FPLAIN}).status_code == 409, "no knowledge folder out of the tree")
check(A.patch(B + f"/api/files/nodes/{node_of(P5)[0]}", json={"parent_id": None}).status_code == 409, "no page out of the tree")
r = A.post(B + "/api/files/folders", json={"parent_id": FE, "name": "Via#store"})
check(r.status_code == 201 and r.json().get("name") == "Viastore", f"a folder made in the file store gets a page-path name {r.text[:120]}")
check(A.post(B + "/api/files/folders", json={"parent_id": FE, "name": "viastore"}).status_code == 409, "the file store's route: a taken folder name 409, no ' (2)'")
check(A.post(B + "/api/files/refs", json={"ref_kind": "wiki", "ref_id": P5, "parent_id": FE}).status_code == 409, "a page is not filed through /api/files/refs")
r = A.post(B + f"/api/files/nodes/{FE}/ext-links", json={})
check(r.status_code in (403, 409), f"no public file store link on a knowledge folder {r.status_code}")
# a page "Loose2" and a folder of the same name side by side (exact names)
PL = page(A, "Loose2")
r = A.post(B + "/api/wiki/folders", json={"space": SP, "name": "Loose2"})
check(r.status_code == 201 and r.json()["folder"]["name"] == "Loose2", "a folder beside a page of the same name keeps the name")
sql("INSERT INTO fs_nodes(parent_id, kind, name, owner_id, org_id, created_at, updated_at) VALUES(?, 'file', 'old.txt', ?, ?, '2026-01-01', '2026-01-01')",
    (FE, uid["alice"], ORG), write=True)  # a file an older version put into the tree
OLDF = sql("SELECT id FROM fs_nodes WHERE parent_id=? AND name='old.txt'", (FE,))[0][0]
check(A.patch(B + f"/api/files/nodes/{OLDF}", json={"parent_id": FPLAIN}).ok, "a foreign file may leave the knowledge tree")

# ================================================================ the trash
FG = node_of(P3)[1]
r = A.delete(B + f"/api/files/nodes/{FG}")
check(r.ok and sql("SELECT deleted_at IS NOT NULL FROM wiki_pages WHERE id=?", (P3,))[0][0], "a folder into the trash: its page into the knowledge trash")
check(P3 not in {p["id"] for p in idx(A).get("pages", [])}, "the trashed page is not in the index")
A.delete(B + f"/api/wiki/pages/{P5}")
lst = A.get(B + "/api/files", params={"parent": node_of(P5)[1]}).json().get("items", [])
check(node_of(P5)[0] not in {x["id"] for x in lst}, "a page in the knowledge trash is not listed in the file store")
A.post(B + "/api/wiki/restore", json={"ids": [P5]})
r = A.post(B + f"/api/files/nodes/{FG}/restore")
check(r.ok and not sql("SELECT deleted_at FROM wiki_pages WHERE id=?", (P3,))[0][0] and path_of(P3) == "Elsewhere/Greek/Beta",
      "restoring the folder brings the page back")

# ================================================================ the organisation's people
jb = idx(Bo)
check(FE in {f["id"] for f in jb.get("folders", [])} and len(jb.get("pages", [])) == len(idx(A).get("pages", [])), "a member sees every folder and page")
items = Bo.get(B + "/api/files", params={"parent": ROOT})
check(items.ok and FE in {x["id"] for x in items.json().get("items", [])}, "a member lists the knowledge folders in the file store")
check(Bo.post(B + "/api/wiki/folders", json={"space": SP, "name": "By Bob"}).status_code == 201, "a member makes a folder")
jr = idx(Ri)
check(FE in {f["id"] for f in jr.get("folders", [])}, "read-only: sees the folders")
check(Ri.post(B + "/api/wiki/folders", json={"space": SP, "name": "By Rita"}).status_code == 403, "read-only: no folder")
check(Ri.post(B + f"/api/files/nodes/{node_of(P5)[0]}/order", json={"parent_id": FE}).status_code in (403, 404), "read-only: moves nothing")
check(idx(Gi).get("status") == 404 and Gi.get(B + "/api/files", params={"parent": ROOT}).status_code == 404, "a guest sees no part of it")
check(Gi.get(B + f"/api/wiki/pages/{P1}").status_code == 404, "a guest reads no page")
# tenant-matrix: wiki
check(Ol.get(B + "/api/files", params={"parent": ROOT}).status_code == 404 and Ol.post(B + "/api/wiki/folders",
      json={"space": SP, "name": "X"}).status_code == 404, "another organisation: 404")
check(Bo.post(B + "/api/wiki/folders", json={"space": "private", "name": "His", "parent_id": FE}).status_code == 404,
      "another person cannot name a folder of this tree")

# ================================================================ a private space: shares follow, locked spaces get no nodes
Q1 = page(A, "Mine/Note", space="private")
Q2 = page(A, "Mine/Other", "[[Mine/Note]]", space="private")
r = A.post(B + "/api/wiki/shares", json={"page_id": Q1, "kind": "person", "user_id": uid["bob"]})
r2 = A.post(B + "/api/wiki/shares", json={"space": "private", "folder": "Mine", "kind": "person", "user_id": uid["bob"]})
check(r.status_code in (200, 201) and r2.status_code in (200, 201), f"setup: private shares {r.status_code} {r2.status_code}")
jp = idx(A, "private")
fmine = node_of(Q1)[1]
r = A.patch(B + f"/api/files/nodes/{fmine}", json={"name": "Ours"})
check(r.ok and path_of(Q1) == "Ours/Note" and path_of(Q2) == "Ours/Other", "private: renaming the folder")
sh = {x[0] for x in sql("SELECT path FROM wiki_shares WHERE owner_id=?", (uid["alice"],))}
check(sh == {"Ours/Note", "Ours"}, f"the wiki_shares follow {sh}")
check(Bo.get(B + "/api/files", params={"parent": jp.get("root")}).status_code == 404, "nobody else sees a private tree")
# a locked space (simulated: the lock row + a ciphertext path)
sql("INSERT INTO wiki_spaces(owner_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (uid["olga"],), write=True)
sql("INSERT INTO wiki_pages(owner_id, path, body, created_at, updated_at) VALUES(?, 'e2e1:AAAA', 'e2e1:BBBB', '2026-01-01', '2026-01-01')",
    (uid["olga"],), write=True)
jo = idx(Ol, "private")
check(jo.get("root") is None and jo.get("folders") == [], f"a locked space: no tree {jo.get('root')}")
check(sql("SELECT COUNT(*) FROM fs_nodes WHERE owner_id=? AND org_id IS NULL", (uid["olga"],))[0][0] == 0, "a locked space: no nodes")
check(Ol.post(B + "/api/wiki/folders", json={"space": "private", "name": "X"}).status_code == 409, "a locked space: no folder")

# ================================================================ moving pages to the other workspace
r = A.post(B + "/api/wiki/move-space", json={"space": "private", "to": SP, "pages": [Q2]})
check(r.ok and node_of(Q2) is not None and sql("SELECT org_id FROM fs_nodes WHERE id=?", (node_of(Q2)[0],))[0][0] == ORG,
      f"a page moved into the organisation: its node lies in the organisation's tree {r.status_code}")

# ================================================================ freelancer-matrix: wiki
FID, Fr = freelancer(B, A)
F1 = page(Fr, "Clients/Acme", space="private")
jf = idx(Fr, "private")
check(bool(jf.get("root")) and any(f["path"] == "Clients" for f in jf.get("folders", [])), "freelancer: her own tree")
r = Fr.post(B + "/api/wiki/folders", json={"space": "private", "name": "Ideas"})
check(r.status_code == 201, f"freelancer: an empty folder {r.status_code}")
FF = r.json()["folder"]["id"] if r.status_code == 201 else 0
r = Fr.post(B + f"/api/files/nodes/{node_of(F1)[0]}/order", json={"parent_id": FF})
check(r.ok and path_of(F1) == "Ideas/Acme", "freelancer: dragging a page")
check(A.get(B + "/api/files", params={"parent": jf.get("root")}).status_code == 404 and A.get(B + f"/api/wiki/pages/{F1}").status_code == 404,
      "freelancer: nobody else sees her tree")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
