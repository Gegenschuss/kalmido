#!/usr/bin/env python3
"""2.39.1 API tests (agent L).
 - #1188 list admins delete shared lists: the owner or a list admin archives and deletes (only from the archive), the
   tasks go to the trash of the OWNER's inbox (restorable), the owner gets a News entry; a member with edit gets 403, a
   server admin is no list admin (403 / 404); the REST API (DELETE /api/v1/lists/{id}) the same
 - #1188 Lists of the organisation: only lists of the organisation that are shared with at least one more person (never
   private lists, also when shared, never lists without members, never inboxes), with owner and folder path; another
   organisation: 404
 - #1188 moving a list into a folder with defaults: GET /api/lists/{id}/folder-preview names what would change; PATCH with
   folder_adopt: true takes the folder's workspace, without it the list keeps its own (marked as differing from the folder)
 - #1214 "Hide completed": the setting show_done_default (validated), the folder default hide_done (stored with the folder
   settings, inherited by subfolders through the effective props)
tenant-matrix: org
usage: p2391_l_api_test.py <datadir>"""
import json
import os
import dbx as dbxm
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def news(s, kind="orglist"):
    return [x for x in s.get(B + "/api/news").json().get("items", []) if x["kind"] == kind]


def restart(extra):
    e = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + extra)
    assert subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True).returncode == 0


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
# 2.46.0 (#1592): no organisation from the start any more: the setup creates the one these tests use (id 1), new people join it
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL, DAVE = uid["bob"], uid["carol"], uid["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for _s in (A, Bo, Ca, Da):  # 2.49.0 (#1535): the old defaults (completed stay visible, new lists get no own entry)
    _s.patch(B + "/api/settings", json={"show_done_default": "1", "show_done_new": "0"})
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
BINBOX = dbx("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (BOB,))[0][0]
CINBOX = dbx("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (CAROL,))[0][0]

# ================================================================== #1188 a list admin deletes a shared list
SH = Bo.post(B + "/api/lists", json={"name": "Fair stand", "org_id": ORG, "folder": "Events"}).json()["id"]
check(Bo.put(B + f"/api/lists/{SH}/members", json={"user_id": CAROL, "role": "admin"}).ok, "setup: carol is a list admin")
check(Bo.put(B + f"/api/lists/{SH}/members", json={"user_id": DAVE, "role": "edit"}).ok, "setup: dave edits")
T1 = Bo.post(B + "/api/tasks", json={"title": "Book the booth", "list_id": SH}).json()["id"]
T2 = Ca.post(B + "/api/tasks", json={"title": "Print flyers", "list_id": SH}).json()["id"]

check(Da.patch(B + f"/api/lists/{SH}", json={"archived": 1}).status_code == 403, "#1188: a member with edit cannot archive")
check(Da.delete(B + f"/api/lists/{SH}").status_code == 403, "#1188: a member with edit cannot delete")
check(A.delete(B + f"/api/lists/{SH}").status_code in (403, 404), "#1188: a server admin outside the list cannot delete it")
check(Ca.delete(B + f"/api/lists/{SH}").status_code == 409, "#1188: the list admin: only from the archive (409)")
r = Ca.patch(B + f"/api/lists/{SH}", json={"archived": 1})
check(r.ok and dbx("SELECT archived, archived_at IS NOT NULL FROM lists WHERE id=?", (SH,))[0] == (1, 1), "#1188: the list admin archives " + r.text[:120])
nb = news(Bo)
check(any((x.get("data") or {}).get("action") == "larchive" and (x.get("data") or {}).get("name") == "Fair stand" for x in nb),
      "#1188: the owner hears about the archive " + json.dumps(nb)[:300])
check(Ca.patch(B + f"/api/lists/{SH}", json={"archived": 1, "kind": "project"}).status_code == 403, "#1188: the list admin still cannot change the type (owner; 2.40.0 #1431: renaming is allowed)")
r = Ca.patch(B + f"/api/lists/{SH}", json={"archived": 0})
check(r.ok and dbx("SELECT archived FROM lists WHERE id=?", (SH,))[0][0] == 0, "#1188: ... and restores")
Ca.patch(B + f"/api/lists/{SH}", json={"archived": 1})
# a server admin who is only an editor of the list: still no delete
check(Bo.put(B + f"/api/lists/{SH}/members", json={"user_id": dbx("SELECT id FROM users WHERE username='alice'")[0][0], "role": "edit"}).ok, "setup: alice edits")
check(A.delete(B + f"/api/lists/{SH}").status_code == 403, "#1188: a server admin with edit in the list: 403 (no delete right for others' lists)")
# 2.102.0 (#1988): into the list trash of the organisation; the tasks stay in the list (in the trash)
r = Ca.delete(B + f"/api/lists/{SH}")
check(r.ok and dbx("SELECT deleted_at IS NOT NULL FROM lists WHERE id=?", (SH,)) == [(1,)], "#1188: the list admin deletes the archived list " + r.text[:120])
rows = dbx("SELECT list_id, deleted_at IS NOT NULL FROM tasks WHERE id IN (?,?) ORDER BY id", (T1, T2))
check(rows == [(SH, 1), (SH, 1)] and not dbx("SELECT 1 FROM tasks WHERE id IN (?,?) AND list_id=?", (T1, T2, BINBOX)),
      "#1988: the tasks stay in the list (in the trash), not in the owner's inbox " + str(rows))
check(not dbx("SELECT 1 FROM tasks WHERE list_id=?", (CINBOX,)), "#1188: nothing in the admin's inbox")
nb = news(Bo)
check(any((x.get("data") or {}).get("action") == "ltrash" and (x.get("data") or {}).get("name") == "Fair stand" for x in nb),
      "#1188: the owner is told about the delete " + json.dumps(nb)[:300])  # 2.102.0 (#1988): ltrash
check(not any((x.get("data") or {}).get("action") in ("ldelete", "ltrash") for x in news(Ca)), "#1188: the admin who deleted gets no News about it")
check(Bo.post(B + f"/api/tasks/{T1}/restore").status_code == 409, "#1988: a single task comes back only with its list")
check(Bo.post(B + f"/api/trash/lists/{SH}/restore").ok and dbx("SELECT deleted_at FROM tasks WHERE id=?", (T1,)) == [(None,)],
      "#1188 / #1988: the owner restores the list with its tasks from the trash")

# the owner deletes his own list: no News to himself, the old way
OWN = Bo.post(B + "/api/lists", json={"name": "Own list", "org_id": ORG}).json()["id"]
Bo.patch(B + f"/api/lists/{OWN}", json={"archived": 1})
check(Bo.delete(B + f"/api/lists/{OWN}").ok, "#1188: the owner deletes as before")

# ---- the REST API: the same rules
tok_c = Ca.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "delete"]}).json()["token"]
tok_d = Da.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "delete"]}).json()["token"]
VC, VD = {"Authorization": "Bearer " + tok_c}, {"Authorization": "Bearer " + tok_d}
L2 = Bo.post(B + "/api/lists", json={"name": "Second", "org_id": ORG}).json()["id"]
Bo.put(B + f"/api/lists/{L2}/members", json={"user_id": CAROL, "role": "admin"})
Bo.put(B + f"/api/lists/{L2}/members", json={"user_id": DAVE, "role": "edit"})
check(requests.patch(V + f"/lists/{L2}", headers=VD, json={"archived": True}).status_code == 403, "#1188 v1: an editor cannot archive")
r = requests.patch(V + f"/lists/{L2}", headers=VC, json={"archived": True})
check(r.ok, "#1188 v1: the list admin archives " + r.text[:120])
check(requests.delete(V + f"/lists/{L2}", headers=VD).status_code == 403, "#1188 v1: an editor cannot delete")
r = requests.delete(V + f"/lists/{L2}", headers=VC)
check(r.status_code == 204 and dbx("SELECT deleted_at IS NOT NULL FROM lists WHERE id=?", (L2,)) == [(1,)], "#1188 v1: the list admin deletes (2.102.0 #1988: into the trash) " + str(r.status_code) + r.text[:120])

# ================================================================== #1188 Lists of the organisation: the rule of 11.10. 21:39
OSH = Bo.post(B + "/api/lists", json={"name": "Org shared", "org_id": ORG, "folder": "Clients/Muster"}).json()["id"]
Bo.put(B + f"/api/lists/{OSH}/members", json={"user_id": CAROL, "role": "edit"})
O0 = Bo.post(B + "/api/lists", json={"name": "Org alone", "org_id": ORG}).json()["id"]
PSH = Bo.post(B + "/api/lists", json={"name": "Private shared", "org_id": None}).json()["id"]
Bo.put(B + f"/api/lists/{PSH}/members", json={"user_id": DAVE, "role": "edit"})
CSH = Ca.post(B + "/api/lists", json={"name": "Carol team", "org_id": ORG}).json()["id"]
Ca.put(B + f"/api/lists/{CSH}/members", json={"user_id": DAVE, "role": "view"})
r = A.get(B + f"/api/orgs/{ORG}/lists")
check(r.ok, "#1188: the overview " + r.text[:120])
ls = {x["id"]: x for x in r.json()["lists"]}
check(OSH in ls and CSH in ls, "#1188: lists of the organisation shared with someone are listed")
check(O0 not in ls, "#1188: a list of the organisation without members is not")
check(PSH not in ls, "#1188: a private list is never listed, also when shared")
check(BINBOX not in ls and CINBOX not in ls, "#1188: never an inbox")
check(ls.get(OSH, {}).get("folder") == "Clients/Muster" and ls.get(OSH, {}).get("owner_name") == "Bob" and ls.get(CSH, {}).get("owner_name") == "Carol",
      "#1188: owner (to group by) and the folder path " + json.dumps(ls.get(OSH)))
check(ls.get(OSH, {}).get("members") == 1, "#1188: members count people besides the owner")
check(A.get(B + "/api/orgs/9999/lists").status_code == 404, "#1188: an unknown organisation: 404")

# ================================================================== #1188 moving into a folder with defaults
MV = Bo.post(B + "/api/lists", json={"name": "Mover", "org_id": None, "folder": ""}).json()["id"]
check(Bo.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"org_id": ORG}}).ok, "setup: folder Clients belongs to the organisation")
check(dbx("SELECT org_id FROM lists WHERE id=?", (MV,))[0][0] is None, "setup: the mover is private")
r = Bo.get(B + f"/api/lists/{MV}/folder-preview", params={"folder": "Clients"})
ch = r.json().get("changes", []) if r.ok else []
check(r.ok and any(x["key"] == "org_id" and x["from"] is None and x["to"] == ORG and x.get("to_name") for x in ch), "#1188: the preview names the workspace change " + r.text[:200])
check(Bo.get(B + f"/api/lists/{MV}/folder-preview", params={"folder": "Other"}).json().get("changes") == [], "#1188: a folder without defaults: nothing to confirm")
check(Da.get(B + f"/api/lists/{MV}/folder-preview", params={"folder": "Clients"}).status_code == 404, "#1188: someone else's list: 404")
# without folder_adopt: moved, nothing re-hung silently, marked as differing
r = Bo.patch(B + f"/api/lists/{MV}", json={"folder": "Clients"})
check(r.ok and dbx("SELECT folder, org_id FROM lists WHERE id=?", (MV,))[0] == ("Clients", None), "#1188: moved without folder_adopt: stays private " + r.text[:100])
check("org_id" in json.loads(dbx("SELECT folder_own FROM lists WHERE id=?", (MV,))[0][0] or "[]"), "#1188: ... and differs from the folder")
# back out and in again, now confirmed
Bo.patch(B + f"/api/lists/{MV}", json={"folder": ""})
r = Bo.patch(B + f"/api/lists/{MV}", json={"folder": "Clients", "folder_adopt": True})
check(r.ok and dbx("SELECT org_id FROM lists WHERE id=?", (MV,))[0][0] == ORG, "#1188: with folder_adopt the list takes the folder's workspace")
check("org_id" not in json.loads(dbx("SELECT folder_own FROM lists WHERE id=?", (MV,))[0][0] or "[]"), "#1188: ... and follows the folder")
# the other direction: an organisation list into a private folder
check(Bo.put(B + "/api/folders/props", json={"folder": "Home", "props": {"org_id": 0}}).ok, "setup: folder Home is private")
ch = Bo.get(B + f"/api/lists/{MV}/folder-preview", params={"folder": "Home"}).json()["changes"]
check(any(x["key"] == "org_id" and x["from"] == ORG and x["to"] is None for x in ch), "#1188: organisation -> private is named too " + json.dumps(ch))
# dragging (reorder) the same
Bo.post(B + "/api/lists/reorder", json={"ids": [MV], "folder": {str(MV): "Home"}})
check(dbx("SELECT folder, org_id FROM lists WHERE id=?", (MV,))[0] == ("Home", ORG), "#1188: dragged without folder_adopt: workspace kept")
Bo.post(B + "/api/lists/reorder", json={"ids": [MV], "folder": {str(MV): "Clients"}})
Bo.post(B + "/api/lists/reorder", json={"ids": [MV], "folder": {str(MV): "Home"}, "folder_adopt": [MV]})
check(dbx("SELECT folder, org_id FROM lists WHERE id=?", (MV,))[0] == ("Home", None), "#1188: dragged with folder_adopt: private now")
check(requests.patch(V + f"/lists/{CSH}", headers=VC, json={"folder_adopt": "yes"}).status_code == 400, "#1188 v1: folder_adopt must be a boolean")

# ================================================================== #1214 hide completed: the global default, the folder default
check(Bo.patch(B + "/api/settings", json={"show_done_default": "0"}).ok, "#1214: show_done_default 0 (hide)")
check(Bo.get(B + "/api/state").json().get("settings", {}).get("show_done_default") == "0", "#1214: it is in the state")
check(Bo.patch(B + "/api/settings", json={"show_done_default": "maybe"}).status_code == 400, "#1214: only 0 / 1")
check(Bo.patch(B + "/api/settings", json={"show_done_default": "1"}).ok, "#1214: back to show")
r = Bo.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"hide_done": True}})
check(r.ok and r.json()["props"].get("hide_done") is True, "#1214: the folder default hide_done " + r.text[:200])
check(dbx("SELECT org_id FROM lists WHERE id=?", (OSH,))[0][0] == ORG, "#1214: setting hide_done changes no workspace")
r = Bo.get(B + "/api/folders/props", params={"folder": "Clients/Muster"})
check(r.ok and r.json()["inherited"].get("hide_done", {}).get("value") is True, "#1214: a subfolder inherits it " + r.text[:200])
st = Bo.get(B + "/api/state").json()
fp = st.get("folder_props") or st.get("me", {}).get("folder_props") or {}
check(fp.get("Clients", {}).get("hide_done") is True, "#1214: the client knows the folder default " + json.dumps(fp)[:200])
check(Bo.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"hide_done": "x"}}).status_code == 400, "#1214: hide_done is a boolean")
check(Bo.get(B + f"/api/lists/{MV}/folder-preview", params={"folder": "Clients"}).json()["changes"] == [
    x for x in Bo.get(B + f"/api/lists/{MV}/folder-preview", params={"folder": "Clients"}).json()["changes"] if x["key"] != "hide_done"],
    "#1214: hide_done needs no confirmation when moving")
check(Bo.put(B + "/api/folders/props", json={"folder": "Clients", "props": {"hide_done": None}}).ok
      and "hide_done" not in Bo.get(B + "/api/folders/props", params={"folder": "Clients"}).json()["props"], "#1214: null removes the default")

print(f"{OKS[0]} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
