#!/usr/bin/env python3
"""2.200.0 B (#2747): sharing knowledge folders and pages through the file store's shares (wiki/wkfolder.py _share,
wkf_shared; wiki/wkfshare.py; wiki/wkshare.py "Shared with me"). Invented names only.
 - who may share: who writes in the space (a member, not only the folder's owner); a read-only member, a guest: no
 - a guest with a folder share: "Shared with me" lists the pages from the shared folder on (no folder above it), reads the
   page; 'edit': changes the text and the page's own name (its node follows), not its folder, no delete; new page / folder IN
   the shared folder (the space's page: the organisation's, a private owner's); 'view': no new page
 - backlinks, moves and search show a share reader only what they may read (no names of other pages)
 - the earlier wiki_shares (a public link of a folder) stay and are listed for the dialog's section
 - withdrawing the share / moving the page out of the shared folder takes it away at once
 - a space locked later: its old nodes give nothing, a new share is 409, nothing is deleted
 - freelancer-matrix: wiki (a person without an organisation shares her private folder with a person; a new page there is hers)
 - tenant-matrix: wiki (only people of the same workspace get a share)
usage: p2200_b_wiki_share_test.py <datadir>      (a fresh container; P2200B_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEAT = "wiki,files,collab,comments"

if not os.environ.get("P2200B_NOSTART"):
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
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}


def person(name, role, org=ORG):
    r = A.post(B + "/api/users", json={"orgs": [{"id": org, "role": role}] if org else [], "username": name, "display_name": name.title(),
                                       "password": "password123", "email": f"{name}@example.com"})
    assert r.ok, r.text
    uid[name] = r.json()["id"]
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
    return s


Bo, Ri, Gi = person("bob", "member"), person("rita", "readonly"), person("gina", "guest")


def page(s, sp, path, text="text"):
    r = s.post(B + "/api/wiki/pages", json={"space": sp, "path": path, "body": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def node(s, pid):
    return s.get(B + f"/api/wiki/pages/{pid}").json().get("node_id")


def folder_of(s, sp, path):
    j = s.get(B + "/api/wiki", params={"space": sp}).json()
    return next((f["id"] for f in j.get("folders", []) if f["path"] == path), None)


def share(s, nid, who, role="view"):
    return s.post(B + f"/api/files/nodes/{nid}/shares", json={"user_id": who, "role": role})


def mine(s):
    return s.get(B + "/api/wiki/shared").json()


# ================================================================ an organisation
P1 = page(A, SP, "Internal/Customer A/Setup", "see [[Internal/Customer A/Notes]]")
P2 = page(A, SP, "Internal/Customer A/Notes")
SECRET = page(A, SP, "Internal/Secret plan", "links to [[Internal/Customer A/Setup]]")
FA = folder_of(A, SP, "Internal/Customer A")
check(FA is not None, "setup: the folder Internal/Customer A")
# who may share
r = share(Bo, FA, uid["gina"])
check(r.status_code == 201, f"a member who writes in the space shares a knowledge folder (not only its owner) {r.status_code} {r.text[:200]}")
SID = r.json().get("id")
check(share(Ri, FA, uid["gina"]).status_code in (403, 404), "a read-only member cannot share")
check(share(Gi, FA, uid["rita"]).status_code in (403, 404), "a guest cannot share")
check(Bo.get(B + f"/api/files/nodes/{FA}").json().get("shares") is not None, "the dialog of a member lists the shares")
root = A.get(B + "/api/wiki", params={"space": SP}).json().get("root")
check(share(A, root, uid["gina"]).status_code == 409, "the root Knowledge cannot be shared")
# the guest reads
j = mine(Gi)
got = {p["id"]: p for p in j["pages"]}
check(set(got) == {P1, P2}, f"Shared with me: the pages of the shared folder {sorted(got)}")
check(got.get(P1, {}).get("path") == "Customer A/Setup" and "Internal" not in str(j), f"from the shared folder on, no folder above it {got.get(P1)}")
check(got.get(P1, {}).get("role") == "view" and got.get(P1, {}).get("via") == "folder", "role view, through the folder")
check([f["name"] for f in j["folders"]] == ["Customer A"], f"the shared folder is listed {j['folders']}")
r = Gi.get(B + f"/api/wiki/shared/pages/{P1}")
check(r.ok and r.json().get("role") == "view" and "#wsh/" in r.json().get("html", ""), "the guest reads the page, the link to the other shared page works")
r = Gi.get(B + f"/api/wiki/pages/{P1}")
check(r.ok and r.json().get("role") == "view", "the page itself opens with role view")
check(r.ok and r.json().get("backlinks") == [] and r.json().get("moved") is None,
      f"no backlink from a page the guest cannot see {r.json().get('backlinks') if r.ok else r.status_code}")
check(any(b["id"] == SECRET for b in A.get(B + f"/api/wiki/pages/{P1}").json().get("backlinks", [])), "the member still sees the backlink")
check(Gi.get(B + f"/api/wiki/pages/{SECRET}").status_code == 404, "a page outside the shared folder stays hidden")
check(Gi.patch(B + f"/api/wiki/pages/{P1}", json={"body": "changed"}).status_code == 403, "view: no change")
check(Gi.post(B + "/api/wiki/shared/pages", json={"folder_id": FA, "name": "New"}).status_code == 403, "view: no new page")
sr = Gi.get(B + "/api/wiki/search", params={"q": "Secret"})
check(sr.status_code in (200, 404) and SECRET not in [p["id"] for p in (sr.json().get("pages", []) if sr.ok else [])], "search finds no hidden page")
# edit
check(A.patch(B + f"/api/files/shares/{SID}", json={"role": "edit"}).ok, "the share becomes edit")
check(Gi.patch(B + f"/api/wiki/pages/{P1}", json={"body": "changed by gina"}).ok, "edit: the guest changes the text")
r = Gi.patch(B + f"/api/wiki/pages/{P1}", json={"path": "Internal/Customer A/Setup v2"})
check(r.ok, f"edit: the page's own name {r.status_code} {r.text[:200]}")
check(sql("SELECT name FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (P1,))[0][0] == "Setup v2", "its node follows the name")
check(Gi.patch(B + f"/api/wiki/pages/{P1}", json={"path": "Elsewhere/Setup v2"}).status_code == 403, "edit: not into another folder by its path")
check(Gi.delete(B + f"/api/wiki/pages/{P1}").status_code == 403, "edit: no delete")
r = Gi.post(B + "/api/wiki/trash", json={"ids": [P1]})
check(r.ok and r.json().get("skipped") == [P1], "edit: no bulk trash")
r = Gi.post(B + "/api/wiki/shared/pages", json={"folder_id": FA, "name": "Guest page", "body": "hello"})
check(r.status_code == 201, f"edit: a new page in the shared folder {r.status_code} {r.text[:200]}")
GP = r.json().get("id")
row = sql("SELECT org_id, owner_id, path, created_by FROM wiki_pages WHERE id=?", (GP,))[0]
check(tuple(row) == (ORG, None, "Internal/Customer A/Guest page", uid["gina"]), f"the page is the organisation's, the path kept {tuple(row)}")
check(any(p["id"] == GP for p in A.get(B + "/api/wiki", params={"space": SP}).json()["pages"]), "the members see it in the space")
check(Gi.post(B + "/api/wiki/shared/pages", json={"folder_id": FA, "name": "Guest page"}).status_code == 409, "a taken name = 409")
r = Gi.post(B + "/api/wiki/shared/folders", json={"parent_id": FA, "name": "Drafts"})
check(r.status_code == 201, f"edit: a subfolder {r.status_code} {r.text[:200]}")
DR = r.json().get("folder", {}).get("id")
r = Gi.post(B + "/api/wiki/shared/pages", json={"folder_id": DR, "name": "Draft"})
check(r.status_code == 201 and sql("SELECT path FROM wiki_pages WHERE id=?", (r.json().get("id"),))[0][0] == "Internal/Customer A/Drafts/Draft",
      "a page in the subfolder: path with it")
check(Gi.post(B + "/api/wiki/shared/pages", json={"folder_id": folder_of(A, SP, "Internal"), "name": "X"}).status_code == 404,
      "no page in a folder that is not shared")
check({f["name"] for f in mine(Gi)["folders"]} == {"Customer A", "Drafts"}, "the subfolder is listed")
# the earlier shares stay: a public link of the folder, listed for the dialog's section
r = A.post(B + "/api/wiki/shares", json={"space": SP, "folder": "Internal/Customer A", "kind": "link"})
check(r.status_code in (201, 409), f"a public link of the folder (or links off) {r.status_code}")
if r.status_code == 201:
    j = A.get(B + "/api/wiki/shares", params={"space": SP, "folder": "Internal/Customer A"}).json()
    check(any(s["kind"] == "link" for s in j["shares"]), "the public link is listed")
# moving out / withdrawing
check(A.patch(B + f"/api/files/nodes/{node(A, P2)}", json={"parent_id": folder_of(A, SP, "Internal")}).ok, "the page moved out of the folder")
check(Gi.get(B + f"/api/wiki/pages/{P2}").status_code == 404 and P2 not in [p["id"] for p in mine(Gi)["pages"]], "moved out = gone at once")
check(A.delete(B + f"/api/files/shares/{SID}").ok, "the share withdrawn")
check(Gi.get(B + f"/api/wiki/pages/{P1}").status_code == 404 and mine(Gi)["pages"] == [] and mine(Gi)["folders"] == [], "withdrawn = gone at once")
check(Gi.get(B + f"/api/wiki/shared/pages/{P1}").status_code == 404, "withdrawn: the reading dialog too")
# a single page node
r = share(A, node(A, P1), uid["gina"])
check(r.status_code == 201 and [p["id"] for p in mine(Gi)["pages"]] == [P1] and mine(Gi)["pages"][0]["path"] == "Setup v2", "a page shared alone")
# 2.200.0 (#2747, Fable review 3): a page shared alone keeps its name (no oracle on the names of its unseen siblings)
check(A.patch(B + f"/api/files/shares/{r.json().get('id')}", json={"role": "edit"}).ok, "the single page share becomes edit")
check(Gi.patch(B + f"/api/wiki/pages/{P1}", json={"path": "Setup v3"}).status_code == 403, "review: a page shared alone is not renamed")
check(Gi.patch(B + f"/api/wiki/pages/{P1}", json={"body": "text only"}).ok, "review: its text still changes")
A.delete(B + f"/api/files/shares/{r.json().get('id')}")
# tenant-matrix: wiki -- a person of another organisation gets no share
r = A.post(B + "/api/admin/orgs", json={"name": "Beta"})
check(r.ok, f"setup: a second organisation {r.status_code} {r.text[:200]}")
if r.ok:
    OB = r.json().get("id")
    Ot = person("otto", "member", OB)
    check(share(A, FA, uid["otto"]).status_code == 409, "tenant-matrix: wiki -- no share with a person of another organisation")
    check(Ot.get(B + f"/api/wiki/pages/{P1}").status_code == 404, "tenant-matrix: wiki -- the other organisation sees nothing")

# ================================================================ freelancer-matrix: wiki (a person without an organisation)
FID, Fr = freelancer(B, A)
a_, b_ = sorted((FID, uid["bob"]))  # an accepted connection (accounts/discover.py): she may share with him
sql("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?, ?, '2026-01-01T00:00:00Z')", (a_, b_), write=True)
FP = page(Fr, "private", "Clients/Studio/Brief")
FF = folder_of(Fr, "private", "Clients/Studio")
r = share(Fr, FF, uid["bob"], "edit")
check(r.status_code == 201, f"freelancer-matrix: wiki -- she shares her private folder with a person {r.status_code} {r.text[:200]}")
j = mine(Bo)
check([p["id"] for p in j["pages"]] == [FP] and j["pages"][0]["owner_name"], "freelancer-matrix: wiki -- Bob sees it with her name")
r = Bo.post(B + "/api/wiki/shared/pages", json={"folder_id": FF, "name": "Answer"})
check(r.status_code == 201, "freelancer-matrix: wiki -- a new page in her folder")
row = sql("SELECT org_id, owner_id, path FROM wiki_pages WHERE id=?", (r.json().get("id"),))[0]
check(tuple(row) == (None, FID, "Clients/Studio/Answer"), f"freelancer-matrix: wiki -- the page is hers {tuple(row)}")
check(any(p["path"] == "Clients/Studio/Answer" for p in Fr.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]),
      "freelancer-matrix: wiki -- she sees it in her space")
check(Bo.patch(B + f"/api/wiki/pages/{FP}", json={"path": "Clients/Studio/Brief 2"}).ok, "freelancer-matrix: wiki -- Bob renames it")
check(any(p["path"] == "Clients/Studio/Brief 2" for p in Fr.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]),
      "freelancer-matrix: wiki -- the name follows in her space (not in Bob's)")
check(not any(p["path"].startswith("Clients") for p in Bo.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]),
      "freelancer-matrix: wiki -- nothing lands in Bob's own space")
# ================================================================ 2.200.0 F (#2747, review of B)
# B1: the shares of a page (link tokens, paths, people) only for who writes in its space, never for a share's reader / editor
check(Bo.get(B + "/api/wiki/shares", params={"page": FP}).status_code == 404, "review B1: an edit share does not list her page's shares")
check(Gi.get(B + "/api/wiki/shares", params={"page": P1}).status_code == 404, "review B1: the guest does not list the page's shares")
check(Fr.get(B + "/api/wiki/shares", params={"page": FP}).ok, "review B1: the owner lists them")
# B2: an edit share makes no public link / person share on someone else's private page
n0 = sql("SELECT COUNT(*) FROM wiki_shares")[0][0]
check(Bo.post(B + "/api/wiki/shares", json={"page_id": FP, "kind": "link"}).status_code == 404
      and Bo.post(B + "/api/wiki/shares", json={"page_id": FP, "kind": "person", "user_id": uid["rita"]}).status_code == 404
      and sql("SELECT COUNT(*) FROM wiki_shares")[0][0] == n0, "review B2: an edit share creates no link / person share")
# B3: through a share the path starts at the shared folder; the rename takes that path
d = Bo.get(B + f"/api/wiki/pages/{FP}").json()
check(d.get("path") == "Studio/Brief 2" and d.get("shares") == 0, f"review B3: the path from the shared folder down, no share count {d.get('path')}")
r = Bo.patch(B + f"/api/wiki/pages/{FP}", json={"path": "Studio/Brief 3"})
check(r.ok and r.json().get("path") == "Studio/Brief 3" and r.json().get("relinked") == 0, f"review B3: rename by the shown path {r.text[:160]}")
check(sql("SELECT path FROM wiki_pages WHERE id=?", (FP,))[0][0] == "Clients/Studio/Brief 3", "review B3: her full path follows")
vs = Bo.get(B + f"/api/wiki/pages/{FP}/versions").json().get("versions", [])
check(vs and all(not v["path"].startswith("Clients") for v in vs), f"review B3: the versions without the folders above {[v['path'] for v in vs]}")
v1 = Bo.get(B + f"/api/wiki/pages/{FP}/versions/{vs[0]['id']}").json() if vs else {}
check(not v1.get("path", "").startswith("Clients") and "size" in v1 and "created_at" in v1, f"review: one version keeps size / created_at {sorted(v1)}")
# B4: the shared folder itself is not renamed / moved / trashed through the share (its pages would leave it)
check(Bo.delete(B + f"/api/files/nodes/{FF}").status_code == 403, "review B4: an edit share does not trash the shared folder")
check(Bo.patch(B + f"/api/files/nodes/{FF}", json={"name": "Gone"}).status_code == 403, "review B4: nor rename it")
check(Bo.post(B + "/api/files/trash", json={"ids": [FF]}).status_code == 403, "review (Fable 1): nor through the bulk trash")
check(sql("SELECT name, deleted_at FROM fs_nodes WHERE id=?", (FF,))[0] == ("Studio", None), "review B4: the folder stays")
# B5 / B6: private knowledge: people and her own agents, no groups, no agents of others or without an owner
OWN = A.post(B + "/api/admin/agents", json={"username": "fridabot", "display_name": "Fridabot", "owner_id": FID, "scopes": ["read"]})
TEAM = A.post(B + "/api/admin/agents", json={"username": "teambot", "display_name": "Teambot", "org_id": None, "scopes": ["read"]})
A.post(B + "/api/admin/groups", json={"name": "Crew"})
t = Fr.get(B + f"/api/files/nodes/{FF}/share-targets").json()
ids = {x["id"] for x in t.get("agents", [])}
check(OWN.status_code != 201 or OWN.json()["id"] in ids, f"review B5: her own agent is offered {ids}")
check(TEAM.status_code != 201 or TEAM.json()["id"] not in ids, "review B5: an agent without an owner is not offered")
check(t.get("groups") == [], f"review B6: no groups in private knowledge {t.get('groups')}")
if TEAM.status_code == 201:
    r = Fr.post(B + f"/api/files/nodes/{FF}/shares", json={"agent_id": TEAM.json()["id"], "role": "view"})
    check(r.status_code == 409, f"review B5: a share with it is refused ({r.status_code})")
# locked later: the old share gives nothing, a new one is 409, nothing is deleted
sql("INSERT INTO wiki_spaces(owner_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (FID,), write=True)
check(Bo.get(B + f"/api/wiki/pages/{FP}").status_code == 404 and mine(Bo)["pages"] == [], "a space locked later: the old share gives nothing")
check(share(Fr, FF, uid["bob"]).status_code == 409, "a space locked later: a new share = 409")
check(sql("SELECT COUNT(*) FROM fs_shares WHERE node_id=?", (FF,))[0][0] == 1, "a space locked later: the share row stays")

print(f"p2200_b_wiki_share: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
