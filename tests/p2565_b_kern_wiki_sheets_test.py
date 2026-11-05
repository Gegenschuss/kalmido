#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.565.0 (#4717): the shared core, stage 4 -- shares of tables and of knowledge pages / folders with people and agents are
core shares (fs_shares on the reference node, core/objects.py obj_node_share), the old rows stay their cards. Invented names only.
 - tables: a share through the old route lands on the table's node (a table in no folder: at the top of its tree, the panel
   shows it in no folder), read / write work, the role change follows, revoking ends it at once (obj_revoked), taking the
   table out of a folder keeps the share; a core share taken back in the file store's dialog ends it although the card stays
   (the fallback reopens nothing)
 - knowledge: a person share of a page / a folder lands on the node(s); the folder share covers a page renamed below it and
   stops for a page moved out; #4668: a page restored as "Name (2)" keeps its share; revoke / restore (Undo)
 - the fallback: an old row not moved yet (core_id NULL) is read as before; the one-shot migr_core4717 (and the knowledge
   index) copy it forward, then it works through the core
 - a public link stays a link with the maker's rule of #4698 (maker made read-only: the link ends)
 - tenant-matrix: wiki, sheet_share (a person of no organisation / another workspace: 404, no share; an agent: only what is
   shared with it, never a knowledge person share)
 - freelancer-matrix: sheets, wiki (two people without an organisation: shares by address, her own agent)
usage: p2565_b_kern_wiki_sheets_test.py <datadir>      (a fresh container; P2565B_NOSTART=1 = the server already runs)"""
import sys

import requests

import kt
from freelancer_fixture import freelancer
from kt import B, check, dbx, sess

FEAT = "wiki,files,collab,comments,sheets"
V = B + "/api/v1"
kt.fresh(prefix="P2565B", env={"KALMIDO_API_RATE": "100000"})
kt.docker_logs_on_first_fail()

s0 = requests.Session()
s0.headers.update(kt.H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}


def person(name, role, org=ORG):
    r = A.post(B + "/api/users", json={"orgs": [{"id": org, "role": role}] if org else [], "username": name, "display_name": name.title(),
                                       "password": "password123", "email": f"{name}@example.com"})
    assert r.ok, r.text
    uid[name] = r.json()["id"]
    s = sess(name)
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})
    return s


Bo, Gi = person("bob", "member"), person("gina", "guest")
FID, Fr = freelancer(B, A, "frida")
FIO, Fi = freelancer(B, A, "fiona")
for s in (Fr, Fi):
    s.patch(B + "/api/settings", json={"features": FEAT})
BOB, GINA = uid["bob"], uid["gina"]


def table(s, title, space):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def node_of(kind, rid):
    x = dbx("SELECT id, parent_id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (kind, rid))
    return x[0] if x else (None, None)


def core(kind, rid, who):
    """The core shares (role) of who on the object's own node."""
    return [x[0] for x in dbx("SELECT s.role FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind=? "
                              "AND n.ref_id=? AND (s.user_id=? OR s.agent_id=?)", (kind, rid, who, who))]


# ================================================================ tables: a share through the old route is a core share
T1 = table(Bo, "Rates", SP)
r = Bo.post(B + f"/api/sheets/{T1}/shares", json={"user_id": GINA, "role": "read"})
check(r.status_code == 201, f"bob shares the organisation's table with the guest {r.status_code} {r.text[:160]}")
SH1 = r.json().get("id")
nid, parent = node_of("sheet", T1)
check(nid and parent is None and core("sheet", T1, GINA) == ["view"], f"the share lies on the table's node at the top of its tree {nid} {parent}")
check(dbx("SELECT core_id IS NOT NULL FROM sheet_shares WHERE id=?", (SH1,)) == [(True,)], "the old row is the card of the core share")
check(Gi.get(B + f"/api/sheets/{T1}").status_code == 200, "the guest reads the table")
check(Gi.patch(B + f"/api/sheets/{T1}", json={"title": "Rates x"}).status_code == 403, "read only: no change")
row = next((x for x in Bo.get(B + "/api/sheets?space=all").json().get("sheets", []) if x["id"] == T1), {})
check(row.get("folder_id") is None and row.get("shared") == 1, f"the panel: in no folder, one share {row.get('folder_id')} {row.get('shared')}")
r = Bo.patch(B + f"/api/sheets/{T1}/shares/{SH1}", json={"role": "write"})
check(r.ok and core("sheet", T1, GINA) == ["edit"], f"the role change reaches the core share {r.status_code}")
check(Gi.patch(B + f"/api/sheets/{T1}", json={"title": "Rates 2"}).ok, "write: the guest renames the table")
check([x["role"] for x in Bo.get(B + f"/api/sheets/{T1}/shares").json()["shares"]] == ["write"], "the dialog lists the share")

# a folder: in and out again, the share stays on the node
r = Bo.post(B + "/api/sheets/folders", json={"space": SP, "name": "Finance"})
check(r.status_code == 201, f"a folder of the tables {r.status_code} {r.text[:120]}")
FOLD = r.json()["folder"]["id"]
check(Bo.post(B + "/api/files/refs", json={"ref_kind": "sheet", "ref_id": T1, "parent_id": FOLD}).ok, "the table into the folder")
check(node_of("sheet", T1) == (nid, FOLD) and core("sheet", T1, GINA) == ["edit"], "the same node in the folder, the share with it")
check(Bo.post(B + "/api/files/refs", json={"ref_kind": "sheet", "ref_id": T1, "parent_id": None}).ok, "the table out of the folder")
check(node_of("sheet", T1) == (nid, None) and core("sheet", T1, GINA) == ["edit"], "out of the folder: the node keeps its share (at the top)")
check(Gi.get(B + f"/api/sheets/{T1}").status_code == 200, "... the guest still reads it")

# revoke: at once, into obj_revoked, the card marked
r = Bo.delete(B + f"/api/sheets/{T1}/shares/{SH1}")
check(r.ok and not core("sheet", T1, GINA), f"revoked: the core share is gone {r.status_code}")
check(Gi.get(B + f"/api/sheets/{T1}").status_code == 404, "... the guest reads nothing at once")
check(dbx("SELECT COUNT(*) FROM obj_revoked WHERE src='fs_shares' AND kind='sheet' AND ref_id=?", (T1,))[0][0] == 1, "... restorable in obj_revoked")
check(dbx("SELECT revoked_at IS NOT NULL FROM sheet_shares WHERE id=?", (SH1,)) == [(True,)], "... the card is marked")

# a core share taken back in the file store's dialog ends the share, the card does not reopen it
r = Bo.post(B + f"/api/sheets/{T1}/shares", json={"user_id": GINA, "role": "read"})
check(r.status_code == 201 and Gi.get(B + f"/api/sheets/{T1}").status_code == 200, "shared again (Undo = the same person again)")
fsid = dbx("SELECT core_id FROM sheet_shares WHERE id=?", (SH1,))[0][0]
check(Bo.delete(B + f"/api/files/shares/{fsid}").ok, "the core share taken back in the file store's dialog")
check(Gi.get(B + f"/api/sheets/{T1}").status_code == 404, "the card alone opens nothing (no fallback for a moved row)")
check(Bo.get(B + f"/api/sheets/{T1}/shares").json()["shares"] == [], "... and is no longer listed")

# tenant-matrix: sheet_share -- a person of no organisation: no share, nothing to read
check(Fr.get(B + f"/api/sheets/{T1}").status_code == 404, "frida (no organisation) does not see the organisation's table")
r = Bo.post(B + f"/api/sheets/{T1}/shares", json={"user_id": FID, "role": "read"})
check(r.status_code in (404, 409), f"... and cannot get a share of it {r.status_code}")

# ================================================================ freelancer-matrix: sheets (by address, her own agent)
P1 = table(Fr, "Own rates", "private")
r = Fr.post(B + f"/api/sheets/{P1}/shares", json={"email": "fiona@example.com", "role": "read"})
check(r.status_code == 201, f"frida shares a private table by address {r.status_code} {r.text[:160]}")
check(core("sheet", P1, FIO) == ["view"] and Fi.get(B + f"/api/sheets/{P1}").status_code == 200, "the address' account holds a core share and reads")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Fridabot", "scopes": ["read", "sheets:read", "sheets:write"]})
check(r.status_code in (200, 201), f"her personal agent {r.status_code} {r.text[:120]}")
FA, FH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
dbx("INSERT INTO user_settings(user_id,key,value) VALUES(?,'features','sheets,wiki,files') ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value", (FA,))
P2 = table(Fr, "Not shared", "private")
check(Fr.post(B + f"/api/sheets/{P1}/shares", json={"user_id": FA, "role": "write"}).status_code == 201, "P1 shared with her agent")
check(core("sheet", P1, FA) == ["edit"], "the agent's share is a core share (agent_id)")
check(requests.get(V + f"/sheets/{P1}", headers=FH, timeout=30).status_code == 200, "the agent reads the table shared with it")
check(requests.get(V + f"/sheets/{P2}", headers=FH, timeout=30).status_code == 404, "... not the one not shared")
check(requests.get(V + f"/sheets/{T1}", headers=FH, timeout=30).status_code == 404, "... nor another workspace's")
r = Bo.post(B + f"/api/sheets/{T1}/shares", json={"user_id": FA, "role": "read"})
check(r.status_code in (404, 409), f"tenant-matrix: sheet_share -- an agent of another workspace gets no share {r.status_code}")

# ================================================================ knowledge: person shares of pages / folders
def page(s, path, text="text", sp="private"):
    r = s.post(B + "/api/wiki/pages", json={"space": sp, "path": path, "body": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def shared(s):
    return {x["id"] for x in s.get(B + "/api/wiki/shared").json().get("pages", [])}


W1 = page(Fr, "Docs/Intro")
W2 = page(Fr, "Docs/Deep/Part")
W3 = page(Fr, "Other")
r = Fr.post(B + "/api/wiki/shares", json={"space": "private", "folder": "Docs", "kind": "person", "email": "fiona@example.com"})
check(r.ok, f"frida shares the folder Docs by address {r.status_code} {r.text[:160]}")
card = dbx("SELECT id, core_id FROM wiki_shares WHERE kind='person' AND owner_id=? AND path='Docs'", (FID,))
fold = dbx("SELECT n.id FROM fs_nodes n JOIN fs_shares s ON s.node_id=n.id WHERE s.id=? AND n.kind='folder' AND n.name='Docs'",
           (card[0][1],)) if card and card[0][1] else []
check(bool(fold), f"the folder share is a core share on the folder's node {card}")
check({W1, W2} <= shared(Fi) and W3 not in shared(Fi), "fiona reads the folder's pages, not the others")
check(Fi.get(B + f"/api/wiki/shared/pages/{W2}").status_code == 200, "... the page two levels down too")
check(Fi.get(B + f"/api/wiki/shared/pages/{W3}").status_code == 404, "... not a page outside the folder")
check(Fr.patch(B + f"/api/wiki/pages/{W1}", json={"path": "Docs/Start"}).ok and W1 in shared(Fi), "a page renamed in the folder stays shared")
check(Fr.patch(B + f"/api/wiki/pages/{W1}", json={"path": "Moved out"}).ok and W1 not in shared(Fi), "a page moved out of the folder is not")
check(Fi.post(B + "/api/wiki/shared/pages", json={"folder_id": fold[0][0] if fold else 0, "name": "Mine"}).status_code == 403,
      "a person share stays read only (no new page)")

# a page share and #4668: restored as "Name (2)" it keeps its share
W4 = page(Fr, "Note", "first note")
r = Fr.post(B + "/api/wiki/shares", json={"page_id": W4, "kind": "person", "email": "fiona@example.com"})
check(r.ok and core("wiki", W4, FIO) == ["view"], f"a page share is a core share on the page's node {r.status_code}")
check(Fr.delete(B + f"/api/wiki/pages/{W4}").ok and W4 not in shared(Fi), "the page in the trash: not shared any more")
W5 = page(Fr, "Note", "another note")
r = Fr.post(B + "/api/wiki/restore", json={"ids": [W4]})
check(r.ok and dbx("SELECT path FROM wiki_pages WHERE id=?", (W4,)) == [("Note (2)",)], f"#4668: restored as 'Note (2)' {r.text[:160]}")
Fr.get(B + "/api/wiki?space=private")  # the index: the tree follows the new name
check(W4 in shared(Fi) and Fi.get(B + f"/api/wiki/shared/pages/{W4}").json().get("body") == "first note",
      "#4668: the restored page keeps its share")
check(W5 not in shared(Fi), "#4668: the new page of the old name is not shared")

# revoke and Undo
sid4 = dbx("SELECT id FROM wiki_shares WHERE kind='person' AND page_id=?", (W4,))[0][0]
check(Fr.delete(B + f"/api/wiki/shares/{sid4}").ok and not core("wiki", W4, FIO), "revoked: the core share is gone")
check(Fi.get(B + f"/api/wiki/shared/pages/{W4}").status_code == 404, "... fiona reads nothing at once")
check(Fr.post(B + f"/api/wiki/shares/{sid4}/restore").ok and core("wiki", W4, FIO) == ["view"], "Undo: the core share is back")
check(Fi.get(B + f"/api/wiki/shared/pages/{W4}").status_code == 200, "... and works")

# tenant-matrix: wiki -- no person share of an organisation's page, never with an agent
OP = page(Bo, "Team/Plan", sp=SP)
r = Bo.post(B + "/api/wiki/shares", json={"page_id": OP, "kind": "person", "user_id": GINA})
check(r.status_code == 409, f"an organisation's page: no person share (a public link instead) {r.status_code}")
r = Fr.post(B + "/api/wiki/shares", json={"page_id": W3, "kind": "person", "user_id": FA})
check(r.status_code == 404 and not core("wiki", W3, FA), f"never a knowledge person share with an agent {r.status_code}")
check(Gi.get(B + f"/api/wiki/shared/pages/{W2}").status_code == 404, "another person reads nothing of frida's folder")

# the public link keeps the maker's rule (#4698 c)
r = Bo.post(B + "/api/wiki/shares", json={"page_id": OP, "kind": "link"})
check(r.status_code == 201 and "/s/w/" in r.json().get("url", ""), f"bob makes a public link {r.text[:120]}")
WL = "/s/w/" + r.json().get("url", "/s/w/x").split("/s/w/", 1)[1]
anon = requests.Session()
check(anon.get(B + WL).status_code == 200, "the link opens")
check(A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "readonly"}).ok, "bob made read-only")
check(anon.get(B + WL).status_code in (404, 410), "the link of a maker made read-only ends")
A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"})

# ================================================================ the fallback and the forward copy (migration)
TS = "2026-11-05T10:00:00.000+00:00"
T2 = table(Bo, "Old share", SP)
dbx("INSERT INTO sheet_shares(sheet_id,org_id,user_id,role,created_by,created_at) VALUES(?,?,?,'read',?,?)", (T2, ORG, GINA, BOB, TS))
check(Gi.get(B + f"/api/sheets/{T2}").status_code == 200, "fallback: an old table share not moved yet reads as before")
W6 = page(Fr, "Legacy")
dbx("INSERT INTO wiki_shares(org_id,owner_id,path,is_folder,kind,user_id,token,created_by,created_at,page_id,images) "
    "VALUES(NULL,?,'Legacy',0,'person',?,'',?,?,?,0)", (FID, FIO, FID, TS, W6))
check(Fi.get(B + f"/api/wiki/shared/pages/{W6}").status_code == 200, "fallback: an old page share not moved yet reads as before")
dbx("DELETE FROM settings WHERE key='migr_core4717'")
kt.fresh(prefix="P2565B", env={"KALMIDO_API_RATE": "100000"}, keep=True)  # the start runs the one-shot again
Bo, Gi, Fr, Fi = sess("bob"), sess("gina"), sess("frida"), sess("fiona")
check(core("sheet", T2, GINA) == ["view"] and dbx("SELECT core_id IS NOT NULL FROM sheet_shares WHERE sheet_id=?", (T2,)) == [(True,)],
      "migration: the old table share is a core share now, its row the card")
check(core("wiki", W6, FIO) == ["view"], "migration: the old page share is a core share now")
check(Gi.get(B + f"/api/sheets/{T2}").status_code == 200 and Fi.get(B + f"/api/wiki/shared/pages/{W6}").status_code == 200,
      "migrated shares work")
check(dbx("SELECT value FROM settings WHERE key='migr_core4717'") == [("1",)], "the one-shot is done")
fsid = dbx("SELECT core_id FROM sheet_shares WHERE sheet_id=?", (T2,))[0][0]
check(Bo.delete(B + f"/api/files/shares/{fsid}").ok and Gi.get(B + f"/api/sheets/{T2}").status_code == 404,
      "the migrated share taken back in the core: the old row reopens nothing")
w6 = dbx("SELECT id FROM wiki_shares WHERE page_id=?", (W6,))[0][0]
check(Fr.delete(B + f"/api/wiki/shares/{w6}").ok and Fi.get(B + f"/api/wiki/shared/pages/{W6}").status_code == 404,
      "the migrated page share revoked: gone at once")

sys.exit(kt.done("p2565_b_kern_wiki_sheets"))
