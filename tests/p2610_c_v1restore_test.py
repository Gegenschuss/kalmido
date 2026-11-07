#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.610.0 (#4010, audit E2-N7) API v1: agents restore task / comment files and project files from the trash.
 - POST /api/v1/attachments/{id}/restore and POST /api/v1/list-files/{id}/restore: the same rights and scope as deleting
   (attachments:write); the agent of a shared project deletes (v1) and restores -> 200 with the file, readable again; a
   second restore 404; a live file 404
 - an agent of the same organisation the project is not shared with: 404; an agent of another organisation: 404; an agent
   without attachments:write: 403 required_scope; the file stays in the trash
 - OpenAPI names both routes with the scope attachments:write
 - freelancer-matrix: tasks, lists (a person without an organisation: her own agent on her shared private project, another
   person's agent 404)
 - tenant-matrix: attachment (the agent of another organisation: 404 on both routes)
usage: p2610_c_v1restore_test.py <datadir>      (a fresh container)"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, dbx, sess  # noqa: E402

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
SC = ["read", "tasks:write", "attachments:read", "attachments:write"]

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
assert r.ok, r.text
OLGA = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": OLGA})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def agent(name, org=None, owner=None, scopes=SC):
    body = {"scopes": list(scopes), "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


def project(s, name, agents):
    lid = s.post(B + "/api/lists", json={"name": name, "kind": "project"}).json()["id"]
    for ag in agents:
        r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": ag, "role": "edit"})
        assert r.ok, r.text
    tid = s.post(B + "/api/tasks", json={"title": "Cut", "list_id": lid}).json()["id"]
    r = s.post(B + f"/api/tasks/{tid}/attachments", files={"file": ("notes.txt", b"take 3 is the one\n" * 20, "text/plain")})
    assert r.ok, r.text
    aid = dbx("SELECT id FROM attachments WHERE task_id=?", (tid,))[0][0]
    r = s.post(B + f"/api/lists/{lid}/files", files={"file": ("brief.txt", b"the brief\n" * 20, "text/plain")})
    assert r.ok, r.text
    fid = dbx("SELECT id FROM list_files WHERE list_id=?", (lid,))[0][0]
    return lid, tid, aid, fid


def trashed(table, i):
    r = dbx(f"SELECT deleted_at FROM {table} WHERE id=?", (i,))
    return bool(r and r[0][0])


def case(who, own, lid, tid, aid, fid, strangers, noscope=None):
    """own = the agent the project is shared with; strangers = [(label, agent session)] that must get 404."""
    check(own.post(V + f"/attachments/{aid}/restore").status_code == 404, f"{who}: a live file: 404")
    r = own.delete(V + f"/attachments/{aid}")
    check(r.status_code == 204 and trashed("attachments", aid), f"{who}: the agent deletes the task file (trash) {r.status_code}")
    check(own.get(V + f"/attachments/{aid}").status_code == 404, f"{who}: a file in the trash: 404")
    for label, t in strangers:
        r = t.post(V + f"/attachments/{aid}/restore")
        check(r.status_code == 404, f"{who}: {label}: restoring the task file 404 ({r.status_code} {r.text[:120]})")
    if noscope is not None:
        r = noscope.post(V + f"/attachments/{aid}/restore")
        check(r.status_code == 403 and r.json().get("error", {}).get("required_scope") == "attachments:write",
              f"{who}: without attachments:write: 403 ({r.status_code} {r.text[:160]})")
    check(trashed("attachments", aid), f"{who}: the task file stays in the trash after the refused calls")
    r = own.post(V + f"/attachments/{aid}/restore")
    j = r.json() if r.ok else {}
    check(r.status_code == 200 and j.get("id") == aid and j.get("task_id") == tid and j.get("url") == f"/api/v1/attachments/{aid}",
          f"{who}: the agent restores the task file {r.status_code} {r.text[:200]}")
    check(not trashed("attachments", aid) and own.get(V + f"/attachments/{aid}").ok, f"{who}: readable again")
    check(own.post(V + f"/attachments/{aid}/restore").status_code == 404, f"{who}: a second restore: 404")
    # the project file
    r = own.delete(V + f"/lists/{lid}/files/{fid}")
    check(r.status_code == 204 and trashed("list_files", fid), f"{who}: the agent deletes the project file (trash) {r.status_code}")
    for label, t in strangers:
        r = t.post(V + f"/list-files/{fid}/restore")
        check(r.status_code == 404, f"{who}: {label}: restoring the project file 404 ({r.status_code} {r.text[:120]})")
    if noscope is not None:
        check(noscope.post(V + f"/list-files/{fid}/restore").status_code == 403, f"{who}: project file without attachments:write: 403")
    check(trashed("list_files", fid), f"{who}: the project file stays in the trash after the refused calls")
    r = own.post(V + f"/list-files/{fid}/restore")
    j = r.json() if r.ok else {}
    check(r.status_code == 200 and j.get("id") == fid and j.get("list_id") == lid and j.get("name") == "brief.txt"
          and j.get("url") == f"/api/v1/lists/{lid}/files/{fid}", f"{who}: the agent restores the project file {r.status_code} {r.text[:200]}")
    check(not trashed("list_files", fid) and own.get(V + f"/lists/{lid}/files/{fid}").ok, f"{who}: the project file readable again")
    check(own.post(V + f"/list-files/{fid}/restore").status_code == 404, f"{who}: a second restore of the project file: 404")


# ---------------------------------------------------------------- an organisation's project
TA, ta = agent("alphabot", org=ORG, owner=ALICE)
_, tn = agent("idlebot", org=ORG, owner=ALICE)          # same organisation, the project not shared with it
TB, tb = agent("betabot", org=BETA, owner=OLGA)        # tenant-matrix: attachment -- another organisation
_, tr_ = agent("readbot", org=ORG, owner=ALICE, scopes=["read", "tasks:write", "attachments:read"])
L, T, AT, F = project(A, "Film Alpha", [TA])  # one agent per project: readbot is refused by its scope before any share counts
case("org", ta, L, T, AT, F, [("an agent the project is not shared with", tn), ("the agent of another organisation", tb)], noscope=tr_)

spec = A.get(V + "/openapi.json").json()["paths"]
check(spec.get("/attachments/{id}/restore", {}).get("post", {}).get("x-kalmido-scope") == "attachments:write"
      and spec.get("/list-files/{id}/restore", {}).get("post", {}).get("x-kalmido-scope") == "attachments:write",
      "OpenAPI: both restore routes with the scope attachments:write")

# ---------------------------------------------------------------- a person without an organisation  # freelancer-matrix: tasks, lists
FID, Fr = freelancer(B, A, features=FEATURES)
DA, da = agent("fridabot", owner=FID)
FL, FT, FA, FF = project(Fr, "Film Frida", [DA])
case("freelancer", da, FL, FT, FA, FF, [("another person's agent", ta), ("the agent of another organisation", tb)])

print(f"p2610_c_v1restore: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
