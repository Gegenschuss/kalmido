#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.958.0 A (#5245): stage 7d of the shared core -- folder_people and group_shares are gone, the projects share only through
the shares of their nodes (kalmido/lists/lffolder.py, groups.py, lkretire.py). Invented names only.
 - a folder shared with a person: GET /api/folders/people reads the shares of the folder's nodes; one that ran out is gone at
   once (no watchdog round); taken back: gone
 - a project shared with a group: the core's row on the project's node (fs_shares.group_id, list_own 1, list_role), the same
   answer of GET /api/lists/<id>/groups and GET /api/v1/lists/<id>/groups as before (via "list"), a role change, the end (404 the
   second time), the group's member sees the project and loses it again
 - a folder shared with a group: a share of the folder's nodes, the member gets a folder role (frole) in the projects below,
   the share follows a renamed folder and ends with DELETE
 - the start's one-way step: old rows of group_shares are copied forward (a project's own row, a folder's row), both tables are
   dropped; a folder_people row without a share holds the table back (the start check), without it the table goes
freelancer-matrix: lists (a person without an organisation shares a private folder with a person and lists her)
usage: p2958_a_lists_kern_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, check, dbx, docker_logs_on_first_fail, done, fresh, sess, until  # noqa: E402

fresh(prefix="P2958A")
docker_logs_on_first_fail()
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["comments", "collab"]})
FEAT = "collab,files,comments,fields"
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl", "dora"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} " + r.text[:200])
    uid[u] = r.json().get("id")
S = {u: sess(u) for u in uid}
for s in S.values():
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})


def new_list(s, name, folder=""):
    r = s.post(B + "/api/lists", json={"name": name, "folder": folder, "org_id": ORG})
    assert r.ok, (name, r.status_code, r.text[:300])
    return r.json()["id"]


def sees(s, lid):
    return s.get(B + f"/api/lists/{lid}/overview").ok


def member(lid, who):
    r = dbx("SELECT role, own_role, grole, frole FROM list_members WHERE list_id=? AND user_id=?", (lid, who))
    return tuple(r[0]) if r else None


def fpeople(s, f):
    r = s.get(B + "/api/folders/people", params={"folder": f})
    return {x["user_id"]: x["role"] for x in r.json().get("people", [])} if r.ok else None


def lgroups(lid):
    r = A.get(B + f"/api/lists/{lid}/groups")
    return [(x["group_id"], x["role"], x["via"]) for x in r.json()["groups"]] if r.ok else None


def table(name):
    return bool(dbx("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?", (name,)))


check(not table("folder_people") and not table("group_shares"), "a new database has neither old table")

# ---------------------------------------------------------------- (1) a folder shared with a person
LP = new_list(A, "Harbour map", "Docks")
r = A.put(B + "/api/folders/people", json={"folder": "Docks", "user_id": uid["carl"], "role": "edit"})
check(r.ok and r.json().get("shared") == 1, "alice shares her folder Docks with carl " + r.text[:200])
check(fpeople(A, "Docks") == {uid["carl"]: "edit"}, f"the folder's people come from its nodes' shares: {fpeople(A, 'Docks')}")
check(sees(S["carl"], LP) and member(LP, uid["carl"])[3] == "edit", f"carl sees the project through the folder (frole) {member(LP, uid['carl'])}")
check(A.get(B + "/api/state").ok, "the state loads with a shared folder")
dbx("""UPDATE fs_shares SET expires_at='2000-01-01T00:00:00Z' WHERE user_id=? AND node_id IN (SELECT id FROM fs_nodes WHERE kind='folder'
       AND owner_id=?)""", (uid["carl"], ALICE))
check(fpeople(A, "Docks") == {}, f"a share that ran out is no folder person at once (no watchdog round): {fpeople(A, 'Docks')}")
dbx("UPDATE fs_shares SET expires_at=NULL WHERE user_id=? AND node_id IN (SELECT id FROM fs_nodes WHERE kind='folder' AND owner_id=?)",
    (uid["carl"], ALICE))
check(A.delete(B + "/api/folders/people", json={"folder": "Docks", "user_id": uid["carl"]}).ok and fpeople(A, "Docks") == {},
      "taken back: no folder person")
check(not sees(S["carl"], LP), "carl no longer sees the project")

# ---------------------------------------------------------------- (2) a project shared with a group
G = A.post(B + "/api/admin/groups", json={"name": "Crane crew", "members": [uid["dora"]]}).json()["id"]
LG = new_list(A, "Crane rota")
check(not sees(S["dora"], LG), "setup: dora does not see the project")
check(A.put(B + f"/api/lists/{LG}/groups/{G}", json={"role": "edit"}).ok, "alice shares the project with the group")
row = dbx("""SELECT s.role, s.list_role, s.list_own FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id
             WHERE n.kind='ref' AND n.ref_kind='list' AND n.ref_id=? AND s.group_id=?""", (LG, G))
check([tuple(x) for x in row] == [("edit", "edit", 1)], f"the core's row on the project's node: {row}")
check(lgroups(LG) == [(G, "edit", "list")], f"GET groups: the same answer as before {lgroups(LG)}")
check(sees(S["dora"], LG) and member(LG, uid["dora"])[2] == "edit", f"dora sees it through the group (grole) {member(LG, uid['dora'])}")
tok = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read"]})
check(tok.status_code == 201, "setup: alice's personal token " + tok.text[:120])
TH = {"Authorization": "Bearer " + (tok.json().get("token") or "")}
r = requests.get(B + f"/api/v1/lists/{LG}/groups", headers=TH)
check(r.ok and [(x["group_id"], x["role"], x["via"]) for x in r.json()["data"]] == [(G, "edit", "list")],
      f"API v1 (and the MCP tool list_groups behind it): the same rows {r.status_code} {r.text[:200]}")
check(A.put(B + f"/api/lists/{LG}/groups/{G}", json={"role": "view"}).ok and lgroups(LG) == [(G, "view", "list")]
      and member(LG, uid["dora"])[0] == "view", f"a role change: one row, the new role {lgroups(LG)} {member(LG, uid['dora'])}")
check(len(dbx("SELECT 1 FROM fs_shares WHERE group_id=?", (G,))) == 1, "still one share row of the group")
check(A.delete(B + f"/api/lists/{LG}/groups/{G}").ok and lgroups(LG) == [], "the group share ends")
check(A.delete(B + f"/api/lists/{LG}/groups/{G}").status_code == 404, "a second time: 404")
check(not sees(S["dora"], LG), "dora no longer sees the project")

# ---------------------------------------------------------------- (3) a folder shared with a group
LF = new_list(A, "Quay log", "Quay")
check(A.put(B + f"/api/folders/groups/{G}", json={"folder": "Quay", "role": "view"}).ok, "alice shares her folder Quay with the group")
r = A.get(B + "/api/folders/groups", params={"folder": "Quay"})
check(r.ok and [(x["group_id"], x["role"]) for x in r.json()["groups"]] == [(G, "view")], "GET folder groups " + r.text[:200])
check(lgroups(LF) == [(G, "view", "Quay")], f"the project names the folder's group share (via the folder) {lgroups(LF)}")
m = member(LF, uid["dora"])
check(sees(S["dora"], LF) and m and m[3] == "view" and m[2] is None, f"dora: a folder role (frole), no grole {m}")
check(A.post(B + "/api/folders/rename", json={"old": "Quay", "new": "Pier"}).ok, "alice renames the folder")
r = A.get(B + "/api/folders/groups", params={"folder": "Pier"})
check(r.ok and [x["group_id"] for x in r.json()["groups"]] == [G] and sees(S["dora"], LF), "the group share follows the folder " + r.text[:200])
check(A.delete(B + f"/api/folders/groups/{G}", params={"folder": "Pier"}).ok and not sees(S["dora"], LF), "the folder's group share ends")
check(A.delete(B + f"/api/folders/groups/{G}", params={"folder": "Pier"}).status_code == 404, "a second time: 404")

# ---------------------------------------------------------------- (3b) Fable review F9 / F4 / F8
# F9: a folder node made later at the same path (the first project there in another workspace) takes the folder's group shares
LB = new_list(A, "Bay plan", "Bay")
check(A.put(B + f"/api/folders/groups/{G}", json={"folder": "Bay", "role": "edit"}).ok, "alice shares her folder Bay with the group")
r = A.post(B + "/api/lists", json={"name": "Bay notes", "folder": "Bay", "org_id": None})
check(r.ok, "setup: alice's private project in Bay (her own tree) " + r.text[:200])
LBP = r.json()["id"]
bay = dbx("SELECT id FROM fs_nodes WHERE kind='folder' AND name='Bay' AND owner_id=? AND deleted_at IS NULL", (ALICE,))
check(len(bay) == 2, f"setup: Bay is a folder node in two trees {bay}")
gb = dbx("""SELECT s.node_id, s.list_role FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='folder' AND n.name='Bay'
            AND n.owner_id=? AND s.group_id=? AND COALESCE(s.list_own, 0)=0 ORDER BY s.node_id""", (ALICE, G))
check(len(gb) == 2 and {x[1] for x in gb} == {"edit"}, f"F9: the new Bay node carries the group's share too (as the old row (owner, folder) did) {gb}")
check(lgroups(LBP) == [(G, "edit", "Bay")], f"F9: the private project names the folder's group share {lgroups(LBP)}")
# ---------------------------------------------------------------- (4) a person without an organisation
FID, Fr = freelancer(B, A)
r = Fr.post(B + "/api/lists", json={"name": "Sketches", "folder": "Studio"})
check(r.ok, "setup: frida's private project " + r.text[:200])
r = Fr.put(B + "/api/folders/people", json={"folder": "Studio", "email": "bob@example.com", "role": "view"})
check(r.ok, "frida shares her folder by e-mail " + r.text[:200])
check(fpeople(Fr, "Studio") == {uid["bob"]: "view"}, f"frida's folder lists bob {fpeople(Fr, 'Studio')}")

# ---------------------------------------------------------------- (5) the start's one-way step on an older database
LM = new_list(A, "Old board")
LO = new_list(A, "Old shelf", "Old")
dbx("""CREATE TABLE group_shares (id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, group_id BIGINT NOT NULL REFERENCES groups(id)
       ON DELETE CASCADE, list_id BIGINT REFERENCES lists(id) ON DELETE CASCADE, owner_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
       folder TEXT, role TEXT NOT NULL DEFAULT 'edit', added_by BIGINT, added_at TEXT NOT NULL)""")
dbx("""CREATE TABLE folder_people (owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, folder TEXT NOT NULL,
       user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL DEFAULT 'edit', created_at TEXT NOT NULL,
       PRIMARY KEY (owner_id, folder, user_id))""")
dbx("INSERT INTO group_shares(group_id,list_id,role,added_by,added_at) VALUES(?,?,?,?,?)", (G, LM, "admin", ALICE, "2026-10-01T08:00:00Z"))
dbx("INSERT INTO group_shares(group_id,owner_id,folder,role,added_by,added_at) VALUES(?,?,?,?,?,?)",
    (G, ALICE, "Old", "edit", ALICE, "2026-10-01T08:00:00Z"))
dbx("INSERT INTO folder_people(owner_id,folder,user_id,role,created_at) VALUES(?,?,?,?,?)", (ALICE, "Old", uid["carl"], "view", "2026-10-01T08:00:00Z"))
dbx("DELETE FROM settings WHERE key='migr_grp5245'")  # an older database: the copy has not run yet


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def _health():
    try:
        return requests.get(B + "/api/health", timeout=3).ok
    except requests.RequestException:
        return False


def restart():
    """The next start of the server (core/db.py init_db runs lists/lkretire.py lk_grp_copy once, then lk_retire)."""
    subprocess.run(["docker", "restart", CT], capture_output=True)
    check(until(_health, timeout=90), "the server is up again after the restart")


restart()
A = sess("alice")
check(not table("group_shares") and table("folder_people"),
      "first start: group_shares copied forward and dropped, folder_people held back by the start check (a row without a share)")
check("projects, stage 7d (#5245): folder_people: 1 old row(s) of folder_people have no share in the shared core" in logs(),
      "the log names the row left")
check(lgroups(LM) == [(G, "admin", "list")] and lgroups(LO) == [(G, "edit", "Old")], f"the copies answer as before {lgroups(LM)} {lgroups(LO)}")
check(member(LM, uid["dora"])[2] == "admin" and member(LO, uid["dora"])[3] == "edit",
      f"dora: the project's group role (grole), the folder's as a folder role (frole) {member(LM, uid['dora'])} {member(LO, uid['dora'])}")
check(sees(sess("dora"), LM) and sees(sess("dora"), LO), "dora sees both projects")
dbx("DELETE FROM folder_people")
restart()
check(not table("folder_people") and not table("group_shares"), "without the row the next start drops folder_people")
bf = dbx("SELECT value FROM kalmido_meta WHERE key='back_floor'")
check(bf and bf[0][0], f"the back limit was raised (an older image would rebuild the tables empty) {bf}")
check(lgroups(LM) == [(G, "admin", "list")], "the group share stays after the drop")

sys.exit(done("p2958_a_lists_kern"))
