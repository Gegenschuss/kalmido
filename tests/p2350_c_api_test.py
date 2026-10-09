#!/usr/bin/env python3
"""2.35.0 API tests (agent C).
 - #1101 organisation admins and the lists of their organisation (GET /api/orgs/{id}/lists, POST .../lists/{id}/archive,
   DELETE .../lists/{id} with the name, POST .../lists/{id}/owner): the overview names lists of the organisation only (never
   private lists, private sharing, inboxes, never task titles), a member gets 403, an agent 403 (also with admin rights),
   archive / restore (also by the owner), delete only from the archive and only with the exact name, the tasks land in the
   owner's trash and can be restored, handing over to a person of the organisation (never an agent / an outsider), News for
   the owner and the members, the history, the account export; mode workspaces: another organisation's admin gets 404 for
   our organisation and its lists, an instance admin who is no organisation admin 404; mode shared: no function (404);
   a backup with the new table org_list_log verifies and restores
 - #186 file links: the task link, a project's key links and a link field take smb:// afp:// nfs:// webdav(s):// file:// and
   \\\\server\\share paths; javascript: / data: / text stay refused (also through the agent API)
tenant-matrix: org
usage: p2350_c_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
import time

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
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def wait_for(fn, t=8.0):
    end = time.time() + t
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.4)
    return fn()


def restart(extra):
    e = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_BACKUP_TICK=1 " + extra)
    assert subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True).returncode == 0


def news(s, kind="orglist"):
    return [x for x in s.get(B + "/api/news").json().get("items", []) if x["kind"] == kind]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_BACKUP_TICK=1"))
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL, DAVE = uid["bob"], uid["carol"], uid["dave"]
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]

# bob's lists: two of the organisation (one shared with carol), one private (shared privately with dave), his inbox
TEAM = Bo.post(B + "/api/lists", json={"name": "Bob Team", "org_id": ORG}).json()["id"]
KEEP = Bo.post(B + "/api/lists", json={"name": "Bob Keep", "org_id": ORG, "kind": "project"}).json()["id"]
PRIV = Bo.post(B + "/api/lists", json={"name": "Bob Private", "org_id": None}).json()["id"]
check(Bo.put(B + f"/api/lists/{TEAM}/members", json={"user_id": CAROL, "role": "edit"}).ok, "setup: carol in bob's team list")
check(Bo.put(B + f"/api/lists/{PRIV}/members", json={"user_id": DAVE, "role": "edit"}).ok, "setup: dave in bob's private list (private sharing)")
T1 = Bo.post(B + "/api/tasks", json={"title": "Secret task one", "list_id": TEAM}).json()["id"]
T2 = Bo.post(B + "/api/tasks", json={"title": "Secret task two", "list_id": TEAM}).json()["id"]
dbx("UPDATE tasks SET status=2 WHERE id=?", (T2,), write=True)
Bo.post(B + "/api/tasks", json={"title": "Private thing", "list_id": PRIV})
BINBOX = dbx("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (BOB,))[0][0]
check(dbx("SELECT org_id FROM lists WHERE id=?", (TEAM,))[0][0] == ORG and dbx("SELECT org_id FROM lists WHERE id=?", (PRIV,))[0][0] is None, "setup: workspaces of the lists")

# ================================================================== #1101 the overview (mode organisation: instance admins = org admins)
r = A.get(B + f"/api/orgs/{ORG}/lists")
check(r.ok, "#1101: the instance admin is the organisation's admin in the mode organisation " + r.text[:120])
j = r.json()
ls = {x["id"]: x for x in j["lists"]}
check(TEAM in ls and KEEP in ls, "#1101: the organisation's lists are listed")
check(PRIV not in ls and BINBOX not in ls and not any(x["name"] == "Bob Private" for x in j["lists"]), "#1101: never a private list or an inbox")
check(ls[TEAM]["owner_id"] == BOB and ls[TEAM]["owner_name"] == "Bob" and ls[TEAM]["open"] == 1 and ls[TEAM]["tasks"] == 2 and ls[TEAM]["members"] == 1
      and ls[TEAM]["changed_at"] and ls[TEAM]["archived"] is False, "#1101: name, owner, numbers, last change " + json.dumps(ls[TEAM]))
check("Secret task" not in r.text and "Private thing" not in r.text, "#1101: no contents (no task titles)")
check({p["id"] for p in j["people"]} >= {BOB, CAROL, DAVE} and all(set(p) == {"id", "name"} for p in j["people"]), "#1101: the people a list can go to")
check(Ca.get(B + f"/api/orgs/{ORG}/lists").status_code == 403, "#1101: a member of the organisation gets 403")
check(Ca.post(B + f"/api/orgs/{ORG}/lists/{TEAM}/archive", json={"archived": True}).status_code == 403, "#1101: a member cannot archive")
check(Ca.delete(B + f"/api/orgs/{ORG}/lists/{TEAM}", json={"confirm": "Bob Team"}).status_code == 403, "#1101: a member cannot delete")
check(Ca.post(B + f"/api/orgs/{ORG}/lists/{TEAM}/owner", json={"user_id": CAROL}).status_code == 403, "#1101: a member cannot hand over")
check(A.get(B + "/api/orgs/9999/lists").status_code == 404, "#1101: an unknown organisation: 404")

# an agent, even with admin rights, never
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"], **H}
dbx("UPDATE users SET is_admin=1 WHERE id=?", (AG,), write=True)
dbx("INSERT OR IGNORE INTO org_members(org_id,user_id,role) VALUES(?,?,'admin')", (ORG, AG), write=True)
for m, u, b in (("GET", f"/api/orgs/{ORG}/lists", None), ("POST", f"/api/orgs/{ORG}/lists/{TEAM}/archive", {"archived": True}),
                ("DELETE", f"/api/orgs/{ORG}/lists/{TEAM}", {"confirm": "Bob Team"})):
    r = requests.request(m, B + u, headers=AGH, json=b)
    check(r.status_code in (401, 403), f"#1101: an agent with admin rights gets no access ({m} {u}): {r.status_code}")
check(dbx("SELECT archived FROM lists WHERE id=?", (TEAM,))[0][0] == 0, "#1101: the agent changed nothing")

# private list, inbox, a list id of nothing: 404 (never 403 with something in it)
for lid in (PRIV, BINBOX, 99999):
    check(A.post(B + f"/api/orgs/{ORG}/lists/{lid}/archive", json={"archived": True}).status_code == 404, f"#1101: archive list {lid} (private / inbox / none): 404")
    check(A.delete(B + f"/api/orgs/{ORG}/lists/{lid}", json={"confirm": "x"}).status_code == 404, f"#1101: delete list {lid}: 404")
    check(A.post(B + f"/api/orgs/{ORG}/lists/{lid}/owner", json={"user_id": CAROL}).status_code == 404, f"#1101: hand over list {lid}: 404")
check(dbx("SELECT archived FROM lists WHERE id=?", (PRIV,))[0][0] == 0, "#1101: the private list is untouched")

# ---- archive, the owner restores, archive again
check(A.delete(B + f"/api/orgs/{ORG}/lists/{TEAM}", json={"confirm": "Bob Team"}).status_code == 409, "#1101: deleting needs the archive first (409)")
check(A.post(B + f"/api/orgs/{ORG}/lists/{TEAM}/archive", json={"archived": "yes"}).status_code == 400, "#1101: archived must be true / false")
r = A.post(B + f"/api/orgs/{ORG}/lists/{TEAM}/archive", json={"archived": True})
check(r.ok and {x["id"]: x for x in r.json()["lists"]}[TEAM]["archived"] is True, "#1101: the admin archives a list of another person")
check(dbx("SELECT archived, archived_at IS NOT NULL FROM lists WHERE id=?", (TEAM,))[0] == (1, 1), "#1101: archived with its time")
nb = news(Bo)
check(nb and nb[0]["data"]["action"] == "archive" and nb[0]["data"]["name"] == "Bob Team" and nb[0]["actor_id"] == 1, "#1101: the owner is told (News) " + json.dumps(nb[:1]))
check(any(x["data"]["action"] == "archive" for x in news(Ca)), "#1101: the members are told")
check(not news(Da), "#1101: nobody outside the list is told")
check(Bo.patch(B + f"/api/lists/{TEAM}", json={"archived": False}).ok and dbx("SELECT archived FROM lists WHERE id=?", (TEAM,))[0][0] == 0, "#1101: the owner restores it from the archive")
check(A.post(B + f"/api/orgs/{ORG}/lists/{TEAM}/archive", json={"archived": True}).ok, "#1101: archived again")
r = A.post(B + f"/api/orgs/{ORG}/lists/{TEAM}/archive", json={"archived": False})
check(r.ok and dbx("SELECT archived, archived_at FROM lists WHERE id=?", (TEAM,))[0] == (0, None), "#1101: the admin restores it")
check(any(x["data"]["action"] == "restore" for x in news(Bo)), "#1101: restore told")
A.post(B + f"/api/orgs/{ORG}/lists/{TEAM}/archive", json={"archived": True})

# ---- delete for good: only with the exact name; tasks to the owner's trash, restorable
check(A.delete(B + f"/api/orgs/{ORG}/lists/{TEAM}", json={}).status_code == 400, "#1101: no name, no delete")
check(A.delete(B + f"/api/orgs/{ORG}/lists/{TEAM}", json={"confirm": "bob team"}).status_code == 400, "#1101: the name must match exactly")
check(dbx("SELECT COUNT(*) FROM lists WHERE id=?", (TEAM,))[0][0] == 1, "#1101: still there after the wrong names")
r = A.delete(B + f"/api/orgs/{ORG}/lists/{TEAM}", json={"confirm": "Bob Team"})
check(r.ok and TEAM not in {x["id"] for x in r.json()["lists"]}, "#1101: the admin deletes it for good " + r.text[:120])
check(dbx("SELECT COUNT(*) FROM lists WHERE id=?", (TEAM,))[0][0] == 0, "#1101: the list is gone")
rows = dbx("SELECT id, list_id, deleted_at IS NOT NULL FROM tasks WHERE id IN (?, ?)", (T1, T2))
check(len(rows) == 2 and all(x[1] == BINBOX and x[2] for x in rows), "#1101: its tasks are in the trash of the OWNER's inbox " + str(rows))
check(Bo.post(B + f"/api/tasks/{T1}/restore").ok and dbx("SELECT deleted_at FROM tasks WHERE id=?", (T1,))[0][0] is None, "#1101: the owner restores a task from the trash")
nb = [x for x in news(Bo) if x["data"]["action"] == "delete"]
check(nb and nb[0]["list_id"] is None and nb[0]["data"]["name"] == "Bob Team", "#1101: the owner is told about the delete (the name in the News)")
check(any(x["data"]["action"] == "delete" for x in news(Ca)), "#1101: the former member is told about the delete")

# ---- hand over
check(A.post(B + f"/api/orgs/{ORG}/lists/{KEEP}/owner", json={"user_id": AG}).status_code in (400, 404), "#1101: never to an agent")
check(A.post(B + f"/api/orgs/{ORG}/lists/{KEEP}/owner", json={"user_id": BOB}).status_code == 400, "#1101: not to the owner himself")
check(A.post(B + f"/api/orgs/{ORG}/lists/{KEEP}/owner", json={"user_id": "3"}).status_code == 400, "#1101: user_id is a number")
r = A.post(B + f"/api/orgs/{ORG}/lists/{KEEP}/owner", json={"user_id": CAROL})
check(r.ok and {x["id"]: x for x in r.json()["lists"]}[KEEP]["owner_id"] == CAROL, "#1101: the admin hands bob's list to carol " + r.text[:120])
check(dbx("SELECT role FROM list_members WHERE list_id=? AND user_id=?", (KEEP, BOB)) == [("admin",)], "#1101: bob stays as a list admin")
check(any(x["kind"] == "owner" for x in Ca.get(B + "/api/news").json()["items"]), "#1101: carol is told she owns it")
check(any(x["data"]["action"] == "owner" and x["data"].get("to") == "Carol" for x in news(Bo)), "#1101: bob is told who has it now")

# ---- the history, the account export
log = A.get(B + f"/api/orgs/{ORG}/lists").json()["log"]
acts = [x["action"] for x in log]
check(acts[:2] == ["owner", "delete"] and "archive" in acts and "restore" in acts and log[0]["by"] == "Alice" and log[0]["to"] == "Carol"
      and log[1]["list_name"] == "Bob Team" and log[1]["owner"] == "Bob", "#1101: the history, newest first " + json.dumps(log[:2]))
ex = A.get(B + "/api/export.json").json()
check(len(ex.get("org_list_actions", [])) == len(log), "#1101: the account export holds my actions as an organisation admin")

# ================================================================== #186 file links
FL = ["smb://nas/Projekte/Kunde A/Angebot.pdf", "file:///Users/me/Documents/plan.pdf", "\\\\nas\\share\\Kunde A\\x.docx",
      "webdavs://cloud.example.com/remote.php/dav/files/a", "afp://mac.local/Share", "https://cloud.example.com/s/abc"]
T3 = Bo.post(B + "/api/tasks", json={"title": "With a file", "list_id": KEEP}).json()["id"]
for u in FL:
    r = Bo.patch(B + f"/api/tasks/{T3}", json={"url": u})
    check(r.ok and dbx("SELECT url FROM tasks WHERE id=?", (T3,))[0][0] == u, f"#186: task link {u} " + r.text[:100])
for u in ("javascript:alert(1)", "data:text/html,<b>x</b>", "smb://", "file://", "nas/share", "smb://nas/a\nb", "vbscript:x"):
    check(Bo.patch(B + f"/api/tasks/{T3}", json={"url": u}).status_code == 400, f"#186: refused: {u!r}")
tok = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "tasks:write"]}).json().get("token")
check(bool(tok), "#186: a token for the API")
if tok:
    BH = {"Authorization": "Bearer " + tok}
    check(requests.patch(V + f"/tasks/{T3}", headers=BH, json={"url": "smb://nas/a.txt"}).ok, "#186: the API takes a file link")
    check(requests.patch(V + f"/tasks/{T3}", headers=BH, json={"url": "javascript:alert(1)"}).status_code == 400, "#186: the API refuses javascript:")
r = Ca.post(B + f"/api/lists/{KEEP}/links", json={"url": "smb://nas/Projekte/Spec.pdf"})
check(r.status_code in (200, 201) and any(x["url"] == "smb://nas/Projekte/Spec.pdf" for x in Ca.get(B + f"/api/lists/{KEEP}/overview").json().get("links", [])),
      "#186: a key link of a project to a network drive " + r.text[:120])
check(Ca.post(B + f"/api/lists/{KEEP}/links", json={"url": "javascript:alert(1)"}).status_code == 400, "#186: a key link stays no javascript:")
r = Ca.post(B + f"/api/lists/{KEEP}/fields", json={"name": "Folder", "type": "url"})
check(r.ok, "#186: a link field " + r.text[:100])
if r.ok:
    FID = r.json()["id"]
    check(Ca.patch(B + f"/api/tasks/{T3}", json={"fields": {str(FID): "\\\\nas\\share\\x"}}).ok, "#186: a link field takes a Windows share path")
    check(Ca.patch(B + f"/api/tasks/{T3}", json={"fields": {str(FID): "data:text/html,x"}}).status_code == 400, "#186: a link field refuses data:")

# ---- a backup with the new table verifies and restores
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, "backup: back up now " + r.text[:100])
items = wait_for(lambda: [x for x in A.get(B + "/api/admin/backups").json().get("items", []) if x["kind"] == "manual"], 30)
name = items[0]["name"] if items else ""
r = A.post(B + f"/api/admin/backups/{name}/verify", json={})
check(r.ok and r.json().get("ok"), "backup: a backup with org_list_log verifies " + r.text[:200])
n0 = dbx("SELECT COUNT(*) FROM org_list_log")[0][0]
dbx("DELETE FROM org_list_log", write=True)
r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "name": name})
check(r.ok and r.json().get("ok"), "backup: restore " + r.text[:200])
check(wait_for(lambda: dbx("SELECT COUNT(*) FROM org_list_log")[0][0] == n0, 10), "backup: the history is back after the restore")

# ================================================================== mode workspaces: the boundary between organisations
restart("-e KALMIDO_INSTANCE_MODE=workspaces")
A, Bo, Ca, Da = sess("alice"), sess("bob"), sess("carol"), sess("dave")
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "icon": "B", "admin_id": DAVE})
check(r.status_code == 201, "workspaces: a second organisation with dave as its admin " + r.text[:120])
BETA = r.json()["id"]
check(A.delete(B + f"/api/orgs/{ORG}/members/{DAVE}").ok, "workspaces: dave leaves the first organisation")
BL = Da.post(B + "/api/lists", json={"name": "Beta plan", "org_id": BETA}).json()["id"]
check(dbx("SELECT org_id FROM lists WHERE id=?", (BL,))[0][0] == BETA, "workspaces: dave's list belongs to Beta")
r = Da.get(B + f"/api/orgs/{BETA}/lists")
check(r.ok and [x["id"] for x in r.json()["lists"]] == [BL], "workspaces: Beta's admin sees Beta's lists only")
check(Da.get(B + f"/api/orgs/{ORG}/lists").status_code == 404, "workspaces: another organisation's admin: 404 for our organisation")
check(Da.post(B + f"/api/orgs/{ORG}/lists/{KEEP}/archive", json={"archived": True}).status_code == 404, "workspaces: ... and for its lists")
check(Da.post(B + f"/api/orgs/{BETA}/lists/{KEEP}/archive", json={"archived": True}).status_code == 404, "workspaces: our list through Beta: 404")
check(Da.delete(B + f"/api/orgs/{BETA}/lists/{KEEP}", json={"confirm": "Bob Keep"}).status_code == 404, "workspaces: deleting our list through Beta: 404")
check(dbx("SELECT archived FROM lists WHERE id=?", (KEEP,))[0][0] == 0, "workspaces: nothing changed across the boundary")
check(A.get(B + f"/api/orgs/{BETA}/lists").status_code == 404, "workspaces: an instance admin who is not in Beta: 404")
check(A.get(B + f"/api/orgs/{ORG}/lists").ok, "workspaces: alice (organisation admin role) still manages her organisation")
check(Bo.get(B + f"/api/orgs/{ORG}/lists").status_code == 403, "workspaces: a plain member: 403")
check(Da.post(B + f"/api/orgs/{BETA}/lists/{BL}/owner", json={"user_id": BOB}).status_code == 404, "workspaces: never to a person outside the organisation")
check(A.post(B + f"/api/orgs/{ORG}/lists/{KEEP}/owner", json={"user_id": DAVE}).status_code == 404, "workspaces: dave (now outside) cannot get our list")

# ================================================================== mode shared: no organisation, no function
restart("-e KALMIDO_INSTANCE_MODE=shared")
A = sess("alice")
check(A.get(B + f"/api/orgs/{ORG}/lists").status_code == 404, "shared: no organisation lists (404)")
check(A.post(B + f"/api/orgs/{ORG}/lists/{KEEP}/archive", json={"archived": True}).status_code == 404, "shared: no archive by an admin (404)")

print(f"p2350_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
