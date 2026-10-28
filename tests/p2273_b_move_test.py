#!/usr/bin/env python3
"""2.273.0 B (#3042, #3051) API tests, own container (kt.fresh): moving loses nothing silently.
 - a task moved to another list answers what ended (move_ended: people coming along, assignee, further projects, subtasks
   left in their list); Undo (batch patch_each) or moving it back by hand within a day brings all of it back (move_restored)
 - indenting drops the task's "also in" links; outdenting again brings them back
 - freelancer-matrix: tasks (the person without an organisation: private <-> private)
usage: p2273_b_move_test.py <datadir>"""
import sys

import kt
from kt import B, FAILS, OKS, check, sess  # noqa: F401
from freelancer_fixture import freelancer, org_join

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "collab,comments,family,files,wiki,sheets,office,clients"})
AID = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": AID})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
org_join(B, "alice", ORG)
FID, Fr = freelancer(B, A, "frida")
GID, Gi = freelancer(B, A, "gina")


def task(s, tid):
    j = s.get(B + f"/api/tasks/{tid}").json()
    return j.get("task") or j


def new_list(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org})
    assert r.ok, r.text
    return r.json()["id"]


def new_task(s, lid, title, **b):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **b})
    assert r.ok, r.text
    return r.json()["id"]


# ================================================================== #3042 a task to another list (freelancer, private <-> private)
L1, L2, L3 = new_list(Fr, "Shared"), new_list(Fr, "Mine"), new_list(Fr, "Further")
assert Fr.put(B + f"/api/lists/{L1}/members", json={"email": "gina@example.com", "role": "edit"}).ok
G = new_list(Gi, "Gina's")
assert Gi.put(B + f"/api/lists/{G}/members", json={"email": "frida@example.com", "role": "edit"}).ok
T = new_task(Fr, L1, "Trip")
S = new_task(Fr, L1, "Pack", parent_id=T)
S2 = new_task(Fr, L1, "Tickets", parent_id=T)
r = Fr.patch(B + f"/api/tasks/{S2}", json={"list_id": G})  # a subtask in a list frida may not move out of (gina's)
check(r.ok and task(Fr, S2).get("parent_id") == T, f"setup: subtask in gina's list keeps its parent {r.text[:120]}")
check(Fr.patch(B + f"/api/tasks/{T}", json={"people": [GID], "assignee_id": GID}).ok, "setup: gina comes along and is assigned")

r = Fr.patch(B + f"/api/tasks/{T}", json={"list_id": L2})
me = r.json().get("move_ended") or {}
check(r.ok and me.get("people") == 1 and me.get("assignee") == 1 and me.get("subtasks") == 1,
      f"#3042: the move answers what ended (people, assignee, subtask left behind) {me}")
t = task(Fr, T)
check(t["list_id"] == L2 and not t.get("people") and not t.get("assignee_id"), "#3042: in the unshared list nobody comes along")
check(task(Fr, S2).get("parent_id") is None and task(Fr, S)["list_id"] == L2, "#3042: the subtask in gina's list stays there, detached")

# Undo = the history step (batch patch_each with _prev) -> all of it back
r = Fr.post(B + "/api/tasks/batch", json={"ids": [T], "action": "patch_each",
                                           "data": {"items": {str(T): {"list_id": L1, "_prev": {"list_id": L2}}}}})
t = task(Fr, T)
check(r.ok and t["list_id"] == L1 and t.get("people") == [GID] and t.get("assignee_id") == GID,
      f"#3042: Undo brings back who comes along and the assignee {t.get('people')} {t.get('assignee_id')} {r.text[:120]}")
check(task(Fr, S2).get("parent_id") == T, "#3042: Undo hangs the detached subtask back on")

# moving back by hand works the same way (and only once: the memo is used up)
r = Fr.patch(B + f"/api/tasks/{T}", json={"list_id": L2})
check(r.ok and (r.json().get("move_ended") or {}).get("people") == 1, "#3042: second move ends the same again")
r = Fr.patch(B + f"/api/tasks/{T}", json={"list_id": L1})
mr = r.json().get("move_restored") or {}
check(r.ok and mr.get("people") == 1 and mr.get("assignee") == 1 and mr.get("subtasks") == 1, f"#3042: moving back by hand restores {mr}")
check(task(Fr, T).get("people") == [GID], "#3042: gina comes along again")
r = Fr.patch(B + f"/api/tasks/{T}", json={"title": "Trip 2"})
check(r.ok and "move_restored" not in r.json() and "move_ended" not in r.json(), "#3042: a plain edit answers no move fields")
# 2.273.0 (#3042, Fable review): a detached subtask is only hung back on where the mover may still write
check(task(Fr, S2).get("parent_id") == T, "setup: the subtask hangs on again")
r = Fr.patch(B + f"/api/tasks/{T}", json={"list_id": L2})
check(r.ok and (r.json().get("move_ended") or {}).get("subtasks") == 1 and task(Fr, S2).get("parent_id") is None, "setup: detached again")
assert Gi.put(B + f"/api/lists/{G}/members", json={"user_id": FID, "role": "view"}).ok  # by id: by e-mail an existing member stays as is
r = Fr.patch(B + f"/api/tasks/{T}", json={"list_id": L1})
check(r.ok and not (r.json().get("move_restored") or {}).get("subtasks") and task(Gi, S2).get("parent_id") is None,
      f"#3042: no write right in gina's list any more = the subtask there stays detached {r.json().get('move_restored')}")
assert Gi.put(B + f"/api/lists/{G}/members", json={"user_id": FID, "role": "edit"}).ok

# a move that ends nothing answers nothing extra
T0 = new_task(Fr, L2, "Plain")
r = Fr.patch(B + f"/api/tasks/{T0}", json={"list_id": L3})
check(r.ok and "move_ended" not in r.json(), "#3042: nothing ended -> no move_ended")

# ================================================================== #3042 indent drops the "also in" links, outdent brings them back
P = new_task(Fr, L1, "Parent")
T2 = new_task(Fr, L1, "Linked")
check(Fr.post(B + f"/api/tasks/{T2}/links", json={"list_id": L3}).ok, "setup: the task is also in Further")
r = Fr.patch(B + f"/api/tasks/{T2}", json={"parent_id": P})
check(r.ok and (r.json().get("move_ended") or {}).get("links") == 1, f"#3042: indent names the further project that ended {r.json().get('move_ended')}")
r = Fr.patch(B + f"/api/tasks/{T2}", json={"parent_id": None})
check(r.ok and (r.json().get("move_restored") or {}).get("links") == 1, "#3042: outdent brings the link back")
check([x["list_id"] for x in task(Fr, T2).get("also") or []] == [L3], f"#3042: the task is in Further again {task(Fr, T2).get('also')}")

# 2.273.0 F1 (#3042): gina links a task of the shared list into her private list; frida indents and outdents it -> the link
# into gina's list (frida may not write there) does not come back through frida
T5, G2 = new_task(Gi, L1, "Gina's linked"), new_list(Gi, "Gina private")
check(Gi.post(B + f"/api/tasks/{T5}/links", json={"list_id": G2}).ok, "setup: gina links it into her own list")
check(Fr.patch(B + f"/api/tasks/{T5}", json={"parent_id": P}).ok, "setup: frida indents it (the link ends)")
r = Fr.patch(B + f"/api/tasks/{T5}", json={"parent_id": None})
check(r.ok and not (r.json().get("move_restored") or {}).get("links") and not kt.dbx("SELECT 1 FROM task_links WHERE task_id=?", (T5,)),
      f"2.273.0 F1 (#3042): no link back into a list the mover may not write in {r.text[:160]}")

# ================================================================== #3042 private -> organisation: the links end, back = back
W = new_list(A, "Work", ORG)
P1, P3 = new_list(A, "Alice private"), new_list(A, "Alice further")
T4 = new_task(A, P1, "Report")
check(A.post(B + f"/api/tasks/{T4}/links", json={"list_id": P3}).ok, "setup: alice's task also in a second private list")
r = A.patch(B + f"/api/tasks/{T4}", json={"list_id": W})
check(r.ok and (r.json().get("move_ended") or {}).get("links") == 1, f"#3042: into the organisation the private link ends {r.text[:160]}")
r = A.patch(B + f"/api/tasks/{T4}", json={"list_id": P1})
check(r.ok and (r.json().get("move_restored") or {}).get("links") == 1, f"#3042: back into Private the link is back {r.text[:160]}")

# ================================================================== #3042 a list into the organisation and back (client, links)
r = A.post(B + "/api/clients", json={"name": "Private Example Client", "org_id": None})
PC = r.json().get("id") if r.ok else None
check(PC and A.patch(B + f"/api/lists/{P1}", json={"client_id": PC}).ok, f"setup: alice's private project has a private client {r.text[:120]}")
r = A.patch(B + f"/api/lists/{P1}", json={"org_id": ORG})
me = r.json().get("move_ended") or {}
check(r.ok and me.get("client") == 1 and me.get("links") == 1, f"#3042: into the organisation the list names the client and the link that end {r.text[:200]}")
r = A.patch(B + f"/api/lists/{P1}", json={"org_id": None})
mr = r.json().get("move_restored") or {}
check(r.ok and mr.get("client") == 1 and mr.get("links") == 1, f"#3042: back into Private client and link come back {r.text[:200]}")
check([x["list_id"] for x in task(A, T4).get("also") or []] == [P3], "#3042: the task is in the further list again")

# ================================================================== #3042 office: two parallel copy moves = one copy
import threading  # noqa: E402

cl = A.post(B + "/api/clients", json={"name": "Northwind Example GmbH", "org_id": ORG})
CL = cl.json().get("id") if cl.ok else None
check(CL, "setup: a client of the organisation " + cl.text[:150])
check(A.patch(B + f"/api/lists/{W}", json={"client_id": CL}).ok, "setup: an organisation project uses the client (it is copied, not moved)")
r = A.post(B + "/api/office/move-space", json={"what": "clients", "ids": [CL], "to": "private", "dry": 1})
check(r.ok and (r.json().get("count") or {}).get("copied") == 1, f"setup: the dry run copies the client {r.text[:200]}")
res = []


def go():
    res.append(sess("alice").post(B + "/api/office/move-space", json={"what": "clients", "ids": [CL], "to": "private"}).status_code)


th = [threading.Thread(target=go) for _ in range(2)]
for x in th:
    x.start()
for x in th:
    x.join()
mine = [x for x in A.get(B + "/api/clients").json().get("clients", []) if x.get("name") == "Northwind Example GmbH" and not x.get("org_id")]
check(sorted(res) == [200, 409] and len(mine) == 1, f"#3042: two parallel copy moves -> one copy, the other 409 ({res}, {len(mine)} copies)")
# 2.407.0 (#3396 #3397): a request that reads only after the first one's commit (same rows before and after the lock) is the
# race above made sure: the client a copy move archived is not copied again
r = A.post(B + "/api/office/move-space", json={"what": "clients", "ids": [CL], "to": "private"})
mine = [x for x in A.get(B + "/api/clients").json().get("clients", []) if x.get("name") == "Northwind Example GmbH" and not x.get("org_id")]
check(r.status_code == 409 and len(mine) == 1, f"#3396: a copy move after the first one's commit -> 409, still one copy ({r.status_code}, {len(mine)} copies)")

# 2.273.0 F1 (#3042): a position added in the organisation since a draft moved there goes back with the undo without the
# organisation's service (as on the way there: service / list of the old office end)
check(A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"}).ok, "setup: alice in the organisation's office")
r = A.post(B + "/api/office/services", json={"name_de": "Beratung", "daily_rate": 800})
SV = r.json().get("id") if r.ok else None
A.patch(B + "/api/settings", json={"workspace": "private"})
r = A.post(B + "/api/office/docs", json={"project_title": "Example draft"})
DR = r.json().get("id") if r.ok else None
r = A.post(B + "/api/office/move-space", json={"what": "drafts", "ids": [DR], "to": f"org:{ORG}"})
MD = r.json().get("move_id") if r.ok else None
check(SV and DR and MD, f"setup: a service in the organisation, a private draft moved there {r.text[:160]}")
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
check(A.put(B + f"/api/office/docs/{DR}/items", json={"items": [{"title": "Edit", "qty": 1, "rate": 500}]}).ok, "setup: a position added there")
kt.dbx("UPDATE office_doc_items SET service_id=? WHERE doc_id=?", (SV, DR))
A.patch(B + "/api/settings", json={"workspace": "private"})
r = A.post(B + "/api/office/move-space", json={"undo": MD})
its = kt.dbx("SELECT service_id, list_id FROM office_doc_items WHERE doc_id=?", (DR,))
check(r.ok and len(its) == 1 and its[0][0] is None and its[0][1] is None,
      f"2.273.0 F1 (#3042): the position comes back without the organisation's service {its} {r.text[:160]}")

# ================================================================== #3042 wiki / tables / files (alice: private <-> organisation)
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
org_join(B, "bob", ORG)
sess("bob").patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "wiki,sheets,files,collab"})
A.patch(B + "/api/settings", json={"features": "collab,comments,family,files,wiki,sheets,office,clients"})


def wpage(path, body="Invented text"):
    r = A.post(B + "/api/wiki/pages", json={"space": "private", "path": path, "body": body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


p1, p2 = wpage("Plans/Day one"), wpage("Plans/Old notes")
r = A.post(B + "/api/wiki/shares", json={"page_id": p1, "kind": "person", "user_id": BOB})
check(r.status_code in (200, 201), f"setup: a page shared with bob {r.text[:120]}")
check(A.delete(B + f"/api/wiki/pages/{p2}").ok, "setup: one page of the folder in the trash")
r = A.post(B + "/api/wiki/move-space", json={"space": "private", "folder": "Plans", "to": f"org:{ORG}", "dry": 1})
j = r.json()
check(r.ok and j.get("shares") == 1 and j.get("trash") == 1 and any("share" in n for n in j.get("notes", []))
      and any("trash" in n for n in j.get("notes", [])), f"#3042: the wiki dry run names the share that ends and the page in the trash {j}")

# a locked source (set up in the database: the server only checks the shape) -> expect_updated_at of the dry run
p3 = wpage("Locked page")
kt.dbx("INSERT INTO wiki_spaces(owner_id, e2e, e2e_gen) VALUES(?, 'on', 1) ON CONFLICT DO NOTHING", (AID,))
sp = kt.dbx("SELECT id FROM wiki_spaces WHERE owner_id=?", (AID,))[0][0]
kt.dbx("UPDATE wiki_spaces SET e2e='on', e2e_gen=1 WHERE id=?", (sp,))
kt.dbx("INSERT INTO wiki_keys(space_id, gen, user_id, wrapped, wrapper_pub, created_at) VALUES(?, 1, ?, 'x', 'x', '2026-10-24T10:00:00Z') "
       "ON CONFLICT DO NOTHING", (sp, AID))
r = A.post(B + "/api/wiki/move-space", json={"pages": [p3], "space": "private", "to": f"org:{ORG}", "dry": 1})
pg = (r.json().get("pages") or [{}])[0]
check(r.ok and pg.get("id") == p3 and pg.get("updated_at"), f"#3042: the locked dry run answers updated_at per page {r.text[:200]}")
kt.dbx("UPDATE wiki_pages SET updated_at='2099-01-01T00:00:00.000Z' WHERE id=?", (p3,))  # saved elsewhere meanwhile
mv = {"pages": [{"id": p3, "path": "Locked page", "body": "From the browser", "expect_updated_at": pg.get("updated_at")}],
      "space": "private", "to": f"org:{ORG}", "gens": {"from": 1, "to": 0}}
r = A.post(B + "/api/wiki/move-space", json=mv)
check(r.status_code == 409 and r.json().get("code") == "wiki_changed", f"#3042: a stale expect_updated_at = 409 {r.status_code} {r.text[:160]}")
mv["pages"][0]["expect_updated_at"] = "2099-01-01T00:00:00.000Z"
r = A.post(B + "/api/wiki/move-space", json=mv)
check(r.ok, f"#3042: the current expect_updated_at moves {r.status_code} {r.text[:160]}")

# 2.273.0 F1 (#3042): a page renamed while the move waits for its row lock moves under its new name (not the one read before)
HOLD = """
import sys, time
from kalmido.core import pg as _pg
from kalmido.core.config import DATABASE_URL
pid, new = int(sys.argv[1]), sys.argv[2]
c, w, n = _pg.connect_direct(DATABASE_URL), _pg.connect_direct(DATABASE_URL), 0
with _pg.system_ctx(c):
    c.execute("SELECT id FROM wiki_pages WHERE id=? FOR UPDATE", (pid,))
    print("locked", flush=True)
    for _ in range(1200):  # until the move request waits for the lock (a state, not a fixed time)
        with _pg.system_ctx(w):
            n = w.execute("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' "
                          "AND query ILIKE '%wiki_pages%FOR UPDATE%'").fetchone()[0]
        w.commit()
        if n:
            break
        time.sleep(0.05)
    c.execute("UPDATE wiki_pages SET path=? WHERE id=?", (new, pid))
c.commit()
print("done", n, flush=True)
"""
Bo = sess("bob")
r = Bo.post(B + "/api/wiki/pages", json={"space": "private", "path": "Race/Page one", "body": "Invented text"})
RP = r.json().get("id") if r.status_code == 201 else None
check(RP, f"setup: a private page of bob {r.text[:120]}")
import subprocess  # noqa: E402

hold = subprocess.Popen(["docker", "exec", "-i", kt.CT, "python", "-c", HOLD, str(RP), "Race/Renamed"], stdout=subprocess.PIPE, text=True)
check((hold.stdout.readline() or "").startswith("locked"), "setup: the page row is locked by another transaction")
res = []
th = threading.Thread(target=lambda: res.append(Bo.post(B + "/api/wiki/move-space", json={"space": "private", "folder": "Race", "to": f"org:{ORG}"})))
th.start()
held = hold.communicate(timeout=120)[0]
th.join()
row = kt.dbx("SELECT path, org_id FROM wiki_pages WHERE id=?", (RP,))
check(res and res[0].ok and row and row[0][0] == "Race/Renamed" and row[0][1] == ORG,
      f"2.273.0 F1 (#3042): the move uses the name of the locked row {row} {held!r} {res[0].text[:160] if res else ''}")

# tables: the undo of a move brings the shares back
r = A.post(B + "/api/sheets", json={"title": "Budget", "space": f"org:{ORG}"})
SH = r.json()["id"] if r.status_code == 201 else None
check(SH and A.post(B + f"/api/sheets/{SH}/shares", json={"user_id": BOB, "role": "read"}).status_code in (200, 201), f"setup: table shared with bob {r.text[:120]}")
r = A.post(B + f"/api/sheets/{SH}/move-space", json={"to": "private"})
mid = r.json().get("move_id")
check(r.ok and mid, f"setup: table moved to Private {r.text[:120]}")
r = A.post(B + f"/api/sheets/{SH}/move-space", json={"to": f"org:{ORG}", "undo": mid})
shs = kt.dbx("SELECT COUNT(*) FROM sheet_shares WHERE sheet_id=? AND revoked_at IS NULL", (SH,))[0][0]
check(r.ok and r.json().get("shares_back") == 1 and int(shs) == 1, f"#3042: the undo of the table move brings bob's share back {r.text[:160]} {shs}")

# files: share, opening and the trash below a folder come back with the undo (move back)
r = A.post(B + "/api/files/folders", json={"name": "Shoot", "space": f"org:{ORG}"})
FO = r.json().get("id") if r.status_code == 201 else None
check(FO, f"setup: a folder of the organisation {r.text[:120]}")
r = A.post(B + "/api/files/upload", data={"parent_id": FO}, files={"file": ("old.txt", b"old", "text/plain")})
FI = ((r.json().get("items") or [{}])[0]).get("id") if r.ok else None
check(FI and A.delete(B + f"/api/files/nodes/{FI}").ok, f"setup: a file of the folder in the trash {r.text[:120]}")
check(A.post(B + f"/api/files/nodes/{FO}/shares", json={"user_id": BOB, "role": "view"}).ok, "setup: the folder shared with bob")
r = A.post(B + "/api/admin/groups", json={"name": "Crew"})
GRP = r.json().get("id") if r.ok else None
check(GRP and A.post(B + f"/api/files/nodes/{FO}/shares", json={"group_id": GRP, "role": "view"}).ok, f"setup: and with a group {r.text[:120]}")
r = A.post(B + "/api/files/move-space", json={"ids": [FO], "to": "private", "dry": 1})
check(r.ok and r.json().get("shares") == 2, f"setup: the dry run names the shares {r.text[:160]}")
r = A.post(B + "/api/files/move-space", json={"ids": [FO], "to": "private"})
mv = r.json().get("moved") or [{}]
check(r.ok and not kt.dbx("SELECT 1 FROM fs_shares WHERE node_id=?", (FO,)), f"setup: moved, the share ended {r.text[:160]}")
# 2.273.0 F1 (#3042): the group is deleted meanwhile and bob's share is there again -> the move back neither fails nor doubles it
kt.dbx("DELETE FROM groups WHERE id=?", (GRP,))
kt.dbx("INSERT INTO fs_shares(node_id, user_id, role, created_at) VALUES(?, ?, 'view', '2026-10-24T10:00:00Z')", (FO, BOB))
r = A.post(B + "/api/files/move-space", json={"items": [{"id": FO, "parent": mv[0].get("parent_was"), "name": mv[0].get("name_was")}], "to": f"org:{ORG}"})
check(r.ok and r.json().get("restored", 0) >= 1, f"#3042: the move back restores (2.273.0 F1: without the deleted group) {r.text[:160]}")
check(len(kt.dbx("SELECT 1 FROM fs_shares WHERE node_id=? AND user_id=?", (FO, BOB))) == 1, "#3042: bob's share of the folder is back")
check(kt.dbx("SELECT parent_id FROM fs_nodes WHERE id=?", (FI,))[0][0] == FO, "#3042: the file in the trash lies in its folder again")

# ================================================================== 2.273.0 F1 (#3042) list back into the organisation: readers only if still allowed
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "rita", "display_name": "Rita", "password": "password123", "email": "rita@example.com"})
assert r.ok, r.text
RID = r.json()["id"]
org_join(B, "rita", ORG)
OL = new_list(A, "Opened", ORG)
check(A.patch(B + f"/api/lists/{OL}", json={"org_visibility": "org", "org_edit": 1}).ok, "setup: everyone in the organisation may edit")
TR, TB = new_task(A, OL, "For rita"), new_task(A, OL, "For bob")
check(A.patch(B + f"/api/tasks/{TR}", json={"assignee_id": RID}).ok and A.patch(B + f"/api/tasks/{TB}", json={"assignee_id": BOB}).ok,
      "setup: two readers assigned")
r = A.patch(B + f"/api/lists/{OL}", json={"org_id": None})
check(r.ok and (r.json().get("move_ended") or {}).get("assignees") == 2, f"setup: into Private both readers' assignments end {r.text[:160]}")
kt.dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG, RID))  # rita left the organisation meanwhile
r = A.patch(B + f"/api/lists/{OL}", json={"org_id": ORG})
mr = r.json().get("move_restored") or {}
check(r.ok and mr.get("assignees") == 1 and task(A, TB).get("assignee_id") == BOB and not task(A, TR).get("assignee_id"),
      f"2.273.0 F1 (#3042): back in the organisation only bob is assigned again, not rita who left {mr} {r.text[:120]}")

# ================================================================== 2.273.0 F1 (#3042) the daily clean-up removes old task / list / files move memos
for k, at in (("task", "2026-01-01T00:00:00.000Z"), ("list", "2026-01-01T00:00:00.000Z"), ("files", "2026-01-01T00:00:00.000Z"),
              ("sheet", "2026-01-01T00:00:00.000Z"), ("task", "2099-01-01T00:00:00.000Z")):
    kt.dbx("INSERT INTO space_moves(kind, obj_id, at) VALUES(?, 999999, ?)", (k, at))
out = subprocess.run(["docker", "exec", kt.CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n"
                      "from kalmido.admin.dataretention import lgc_tick\nprint('ran', lgc_tick(c, True))\nc.commit()\nc.close()"],
                     capture_output=True, text=True)
left = sorted((r[0], r[1][:4]) for r in kt.dbx("SELECT kind, at FROM space_moves WHERE obj_id=999999"))
check(left == [("sheet", "2026"), ("task", "2099")],
      f"2.273.0 F1 (#3042): old task / list / files memos are gone, others stay {left} {out.stdout[-200:]}{out.stderr[-300:]}")

# ================================================================== #3051 sprints and sections under their lock (freelancer)
SP_L = Fr.post(B + "/api/lists", json={"name": "Product", "kind": "project"}).json()["id"]
check(Fr.put(B + f"/api/lists/{SP_L}/sprint-settings", json={"on": True}).ok, "setup: sprints on (freelancer)")
codes = []
for _ in range(4):
    r = Fr.post(B + f"/api/lists/{SP_L}/sprints", json={"goal": "Later"})
    sid = r.json().get("id") or (r.json().get("sprint") or {}).get("id")
    out = {}

    def patch_goal(sid=sid, out=out):
        out["patch"] = sess("frida").patch(B + f"/api/sprints/{sid}", json={"goal": "Changed"}).status_code

    def delete(sid=sid, out=out):
        out["delete"] = sess("frida").delete(B + f"/api/sprints/{sid}").status_code
    th = [threading.Thread(target=patch_goal), threading.Thread(target=delete)]
    for x in th:
        x.start()
    for x in th:
        x.join()
    codes.append(out)
check(sid and all(o.get("delete") == 200 and o.get("patch") in (200, 404) for o in codes),
      f"#3051: a sprint changed while it is removed: 200 or 404, never an error {codes}")

secs = [Fr.post(B + "/api/sections", json={"list_id": L2, "name": n}).json()["id"] for n in ("A", "B", "C")]
res = []


def order(ids):
    res.append((ids, sess("frida").post(B + f"/api/lists/{L2}/sections/order", json={"ids": ids, "_prev": secs}).json()))


th = [threading.Thread(target=order, args=([secs[2], secs[0], secs[1]],)), threading.Thread(target=order, args=([secs[1], secs[2], secs[0]],))]
for x in th:
    x.start()
for x in th:
    x.join()
won = [ids for ids, j in res if j.get("ok")]
now = [x["id"] for x in sorted((x for x in Fr.get(B + "/api/state").json()["sections"] if x["list_id"] == L2), key=lambda x: (x["sort"], x["id"]))]
check(len(won) == 1 and now == won[0], f"#3051: two drags of the sections at once: one wins, the other is told {res} {now}")

sys.exit(kt.done("p2273_b_move"))
