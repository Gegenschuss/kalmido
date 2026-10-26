#!/usr/bin/env python3
"""2.306.0 D3 (#2875): hardening of files / knowledge and agents / integrations (audit D).
freelancer-matrix: files, wiki, agents (a person without an organisation keeps every function in the own private space)
 - tables: the table list names the folder a table lies in only to who sees that folder (a share of the table alone: none)
 - documents: the search narrows to a folder (?under=) only when the caller sees that folder (else: nothing)
 - knowledge: an organisation's whole trash is emptied only by its admins (a member: 403, may_empty false), the purge is in
   the organisation's history; single pages and the private space as before
 - exports: a locked office file of another version does not break the list of locked files
 - deleting a document for good removes its preview file only after the commit
 - agent jobs: user_id with a task must see the task and reach the agent there; a job's task title only with sight of the task
 - own ntfy server: http:// only for hosts an admin allowed; a shared file's type comes from its content, not the sender
 - Git server: http:// only through the allow list, localhost included; channel list events per request are capped
usage: p2306_d3_files_agents_hardening_test.py <datadir>      (KMT_NOSTART=1 / P2306D3_NOSTART=1: a running server)"""
import os
import subprocess
import sys

import kt
from kt import B, CT, check, done, fresh, sess, setup
from freelancer_fixture import FEATURES, freelancer, org_join

V = B + "/api/v1"
FEAT = FEATURES + ",sheets"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def in_app(code):
    """Python inside the server container (app loaded, c = a connection in the system context) -> stdout + stderr."""
    body = "\n".join("    " + x for x in code.split("\n"))
    out = subprocess.run(["docker", "exec", CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nc = connect()\n"
                          "with system_ctx(c):\n" + body + "\nc.close()"], capture_output=True, text=True)
    return out.stdout + out.stderr


def agent_api(tok):
    import requests
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


fresh({"KALMIDO_CALENDAR_ALLOW_HOSTS": "127.0.0.1"}, prefix="P2306D3")
A = setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL = ids["bob"], ids["carol"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"})
assert org_join(B, "bob", ORG)
SP = f"org:{ORG}"
FID, Fr = freelancer(B, A, "frida", features=FEAT)

# ================================================================ tables: the folder only with sight of it
F = A.post(B + "/api/sheets/folders", json={"space": "private", "name": "Geheim"})
check(F.status_code == 201, f"#2875 setup: a private folder of the tables {F.status_code} {F.text[:200]}")
F = F.json()["folder"]["id"] if F.ok else 0
r = A.post(B + "/api/sheets", json={"title": "Budget D3", "space": "private", "folder_id": F})
check(r.status_code == 201, f"#2875 setup: a table in it {r.status_code} {r.text[:200]}")
SID = r.json()["id"] if r.ok else 0
r = A.post(B + f"/api/sheets/{SID}/shares", json={"user_id": BOB, "role": "read"})
check(r.ok, f"#2875 setup: the table (not the folder) shared {r.status_code} {r.text[:200]}")


def sheet_row(s):
    return next((x for x in s.get(B + "/api/sheets").json().get("sheets", []) if x["id"] == SID), None)


row = sheet_row(Bo)
check(row is not None and row.get("folder_id") is None and row.get("fnode") is None,
      f"#2875 a share of the table alone does not name the owner's folder {row and {k: row.get(k) for k in ('folder_id', 'fnode')}}")
row = sheet_row(A)
check(row is not None and row.get("folder_id") == F and row.get("fnode"), f"#2875 the owner sees the folder of the table {row and row.get('folder_id')}")
FF = Fr.post(B + "/api/sheets/folders", json={"space": "private", "name": "Mine"}).json()["folder"]["id"]
FS = Fr.post(B + "/api/sheets", json={"title": "Frida D3", "space": "private", "folder_id": FF}).json()["id"]
row = next((x for x in Fr.get(B + "/api/sheets").json().get("sheets", []) if x["id"] == FS), None)
check(row is not None and row.get("folder_id") == FF, f"freelancer #2875: the own table names its folder {row and row.get('folder_id')}")

# ================================================================ documents: ?under= only for a folder one sees
r = A.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("vertrag-d3.png", PNG, "image/png")})
check(r.status_code == 201, f"#2875 setup: a private document {r.status_code} {r.text[:200]}")
DOC = r.json()["ids"][0] if r.ok else 0
DFOLD = (kt.dbx("SELECT parent_id FROM fs_nodes WHERE id=?", (DOC,)) or [[None]])[0][0]
check(bool(DFOLD), "#2875 setup: the document lies in a folder of the owner")
r = A.post(B + f"/api/files/nodes/{DOC}/shares", json={"user_id": BOB, "role": "view"})
check(r.ok, f"#2875 setup: the document (not its folder) shared {r.status_code} {r.text[:200]}")


def doc_ids(s, **args):
    r = s.get(B + "/api/docs", params={"ws": "all", "facets": "0", **args})
    return [d["id"] for d in r.json().get("docs", [])] if r.ok else None


check(DOC in (doc_ids(Bo) or []), "#2875 the shared document is found by the other person")
check(doc_ids(Bo, under=DFOLD) == [], f"#2875 ?under= a folder the person does not see finds nothing ({doc_ids(Bo, under=DFOLD)})")
check(DOC in (doc_ids(A, under=DFOLD) or []), "#2875 the owner narrows to the own folder")
check(doc_ids(Bo, folder=str(DFOLD)) == [], f"#2875 review: ?folder= a folder the person does not see finds nothing ({doc_ids(Bo, folder=str(DFOLD))})")
check(DOC in (doc_ids(A, folder=str(DFOLD)) or []), "#2875 review: the owner narrows with ?folder= to the own folder")
r = Fr.post(B + "/api/docs", data={"ws": "private"}, files={"files": ("beleg-d3.png", PNG, "image/png")})
FDOC = r.json()["ids"][0] if r.ok else 0
FDF = (kt.dbx("SELECT parent_id FROM fs_nodes WHERE id=?", (FDOC,)) or [[None]])[0][0]
check(FDOC in (doc_ids(Fr, under=FDF) or []), "freelancer #2875: the own folder narrows the search")

# ================================================================ knowledge: emptying an organisation's trash
def wpage(s, sp, path):
    r = s.post(B + "/api/wiki/pages", json={"space": sp, "path": path, "body": "text"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert s.delete(B + f"/api/wiki/pages/{pid}").ok
    return pid


O1, O2 = wpage(A, SP, "D3/One"), wpage(Bo, SP, "D3/Two")
j = Bo.get(B + "/api/wiki/trash", params={"space": SP}).json()
check(j.get("may_empty") is False and {O1, O2} <= {p["id"] for p in j.get("pages", [])}, f"#2875 a member sees the trash, may not empty it {j.get('may_empty')}")
r = Bo.post(B + "/api/wiki/purge", json={"space": SP, "all": True})
check(r.status_code == 403, f"#2875 a member cannot empty the organisation's whole trash ({r.status_code})")
check(kt.dbx("SELECT COUNT(*) FROM wiki_pages WHERE id IN (?,?)", (O1, O2))[0][0] == 2, "#2875 ... nothing was deleted")
# 2.306.0 (#2875 review N12): several pages in one call are emptying by hand: admins only
r = Bo.post(B + "/api/wiki/purge", json={"space": SP, "ids": [O1, O2]})
check(r.status_code == 403 and kt.dbx("SELECT COUNT(*) FROM wiki_pages WHERE id IN (?,?)", (O1, O2))[0][0] == 2,
      f"#2875 a member cannot empty the organisation's trash with a list of ids ({r.status_code})")
r = Bo.post(B + "/api/wiki/purge", json={"space": SP, "ids": [O2]})
check(r.ok and r.json().get("ids") == [O2], f"#2875 a member still deletes a single page for good (as before) {r.text[:200]}")
check(A.get(B + "/api/wiki/trash", params={"space": SP}).json().get("may_empty") is True, "#2875 the organisation's admin may empty it")
r = A.post(B + "/api/wiki/purge", json={"space": SP, "all": True})
check(r.ok and r.json().get("ids") == [O1], f"#2875 the admin empties the organisation's trash {r.text[:200]}")
log = kt.dbx("SELECT action, by_id, detail FROM org_list_log WHERE org_id=? AND action='purge' ORDER BY id", (ORG,))
check(len(log) == 2 and {x[1] for x in log} == {BOB, ALICE} and all("wiki" in str(x[2]) for x in log),
      f"#2875 both purges are in the organisation's history {log}")
FP = wpage(Fr, "private", "D3/Own")
check(Fr.get(B + "/api/wiki/trash", params={"space": "private"}).json().get("may_empty") is True, "freelancer #2875: may empty the own trash")
r = Fr.post(B + "/api/wiki/purge", json={"space": "private", "all": True})
check(r.ok and r.json().get("ids") == [FP], f"freelancer #2875: empties the own trash {r.text[:200]}")

# ================================================================ exports: a locked office file of another version
out = in_app(f"from kalmido.files.scan import sc_locked_all\n"
             f"fid = c.execute(\"INSERT INTO office_contract_files(org_id,contract_id,name,file,created_at) VALUES({ORG},1,'v.pdf','d3-v.pdf','2026-10-25') RETURNING id\").fetchone()[0]\n"
             f"c.execute(\"INSERT INTO upload_scan(kind,ref_id,ver,org_id,state,sig,created_at) VALUES('ocf',?,2,{ORG},'infected','D3-Sig','2026-10-25')\", (fid,))\n"
             f"try:\n    print('locked', sc_locked_all(c, {ORG})['office'].get('d3-v.pdf'))\n"
             f"except Exception as e:\n    print('failed', type(e).__name__)\n"
             f"c.rollback()")
check("locked ('ocf'," in out and "'D3-Sig')" in out, "#2875 a locked office file with another version is listed, no error " + out[-300:])

# ================================================================ a document's preview goes only after the commit
out = in_app(f"import os\nfrom kalmido.core.config import ATT_DIR\nfrom kalmido.files.store import fs_purge\n"
             f"rel = os.path.join('docthumbs', 'd3-test.png')\nos.makedirs(os.path.join(ATT_DIR, 'docthumbs'), exist_ok=True)\n"
             f"open(os.path.join(ATT_DIR, rel), 'wb').write(b'x')\n"
             f"c.execute('UPDATE doc_meta SET thumb=? WHERE node_id=?', (rel, {DOC}))\n"
             f"ids, paths = fs_purge(c, {DOC})\n"
             f"print('kept', os.path.exists(os.path.join(ATT_DIR, rel)), rel in paths)\n"
             f"c.rollback()\nos.remove(os.path.join(ATT_DIR, rel))")
check("kept True True" in out, "#2875 the preview file stays until the caller unlinks it after the commit " + out[-300:])

# ================================================================ agent jobs: the person and the task title
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
AG, ag = r.json()["id"], agent_api(r.json()["token"])
L1 = A.post(B + "/api/lists", json={"name": "Team D3"}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Alice only D3"}).json()["id"]
for lid in (L1, L2):
    A.put(B + f"/api/lists/{lid}/members", json={"user_id": AG, "role": "edit"})
    A.patch(B + f"/api/lists/{lid}", json={"agent_members": True})
check(A.put(B + f"/api/lists/{L1}/members", json={"user_id": BOB, "role": "edit"}).ok, "#2875 setup: Bob in the team list")
T1 = A.post(B + "/api/tasks", json={"title": "Shared job task D3", "list_id": L1}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Hidden job task D3", "list_id": L2}).json()["id"]
r = ag.post(V + "/agent/jobs", json={"title": "Job for a hidden task", "task_id": T2, "user_id": BOB})
check(r.status_code == 400, f"#2875 a job for a person who does not see its task: 400 ({r.status_code} {r.text[:200]})")
r = ag.post(V + "/agent/jobs", json={"title": "Job D3", "task_id": T1, "user_id": BOB})
check(r.status_code == 201, f"#2875 a job for a person of the task's list: 201 ({r.status_code} {r.text[:200]})")
JOB = r.json()["id"] if r.ok else 0
# a person without an organisation: the own personal agent in the own project
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "fhelper", "display_name": "F Helper", "owner_id": FID})
assert r.ok, r.text
FAG, fag = r.json()["id"], agent_api(r.json()["token"])
LF = Fr.post(B + "/api/lists", json={"name": "Frida D3"}).json()["id"]
check(Fr.put(B + f"/api/lists/{LF}/members", json={"user_id": FAG, "role": "edit"}).ok, "freelancer #2875 setup: the own agent in the own project")
TF = Fr.post(B + "/api/tasks", json={"title": "Frida job task D3", "list_id": LF}).json()["id"]
r = fag.post(V + "/agent/jobs", json={"title": "Job Frida D3", "task_id": TF, "user_id": FID})
check(r.status_code == 201, f"freelancer #2875: a job for a person without an organisation ({r.status_code} {r.text[:200]})")
fj = next((x for x in Fr.get(B + "/api/agents/jobs").json().get("jobs", []) if x["task_id"] == TF), None)
check(fj is not None and fj.get("task_title") == "Frida job task D3", f"freelancer #2875: sees the task title of the own job {fj}")
A.delete(B + f"/api/lists/{L1}/members/{BOB}")
cj = next((x for x in Bo.get(B + "/api/agents/jobs").json().get("jobs", []) if x["id"] == JOB), None)
check(cj is not None and cj.get("task_title") is None and cj.get("list_id") is None,
      f"#2875 the job stays visible, its task title only with sight of the task {cj and cj.get('task_title')}")
aj = next((x for x in A.get(B + "/api/agents/jobs").json().get("jobs", []) if x["id"] == JOB), None)
check(aj is not None and aj.get("task_title") == "Shared job task D3", f"#2875 the list's owner (admin) sees the title {aj and aj.get('task_title')}")

# ================================================================ own ntfy server, shared file type, Git server, channel events
TOPIC = "d3-share-topic-0123456789"
r = Ca.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": TOPIC, "url": "http://ntfy.example.com"})
check(r.status_code == 400 and "https://" in r.text, f"#2875 an own ntfy server over http:// is refused ({r.status_code} {r.text[:200]})")
r = Ca.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": TOPIC, "url": "http://127.0.0.1:8099"})
check(r.ok, f"#2875 ... unless an admin allowed the host ({r.status_code} {r.text[:200]})")
r = Fr.put(B + "/api/me/ntfy-inbox", json={"enabled": True, "topic": TOPIC + "f", "url": "https://ntfy.example.com"})
check(r.ok, f"freelancer #2875: an own ntfy server over https:// ({r.status_code} {r.text[:200]})")
out = in_app(f"from kalmido.core.pages import ntfy_inbox_import\n"
             f"m = {{'id': 'd3att1', 'event': 'message', 'message': 'pic', 'attachment': {{'name': 'pic.png', 'type': 'text/html', 'url': 'http://x/f'}}}}\n"
             f"ntfy_inbox_import(c, m, {{'uid': {CAROL}, 'fetch': lambda u: bytes.fromhex('{PNG.hex()}'), 'since': lambda mid: None}})\n"
             f"print('mime', c.execute(\"SELECT a.mime FROM attachments a JOIN tasks t ON t.id=a.task_id WHERE t.tt_id='ntfy:d3att1'\").fetchone()[0])")
check("mime image/png" in out, "#2875 a shared file gets its type from its content, not the sender's word " + out[-300:])
# 2.306.0 Fix-2a (#2875): an inbox saved before with an http:// server (no allow list then) can still be switched off / changed
OLD_HTTP = f"c.execute(\"UPDATE ntfy_inboxes SET url='http://ntfy.example.com', enabled=1 WHERE user_id={CAROL}\")\nc.commit()\nprint('set')"
check("set" in in_app(OLD_HTTP), "#2875 setup: an old http:// inbox")
r = Ca.put(B + "/api/me/ntfy-inbox", json={"token": "tk-d3-old-http"})
check(r.ok, f"#2875 an old http:// inbox keeps running on a token change ({r.status_code} {r.text[:200]})")
r = Ca.put(B + "/api/me/ntfy-inbox", json={"enabled": False})
check(r.ok and not r.json().get("enabled"), f"#2875 an old http:// inbox can always be switched off ({r.status_code} {r.text[:200]})")
r = Ca.put(B + "/api/me/ntfy-inbox", json={"enabled": True})
check(r.status_code == 400 and "https://" in r.text, f"#2875 switching it on again checks the address ({r.status_code} {r.text[:200]})")
in_app(OLD_HTTP)
r = Ca.put(B + "/api/me/ntfy-inbox", json={"url": "http://other.example.com"})
check(r.status_code == 400 and "https://" in r.text, f"#2875 a changed http:// address is checked ({r.status_code} {r.text[:200]})")
r = Fr.put(B + "/api/me/ntfy-inbox", json={"enabled": False})
check(r.ok, f"freelancer #2875: the own inbox switched off ({r.status_code} {r.text[:200]})")
out = in_app("from kalmido.core.config import app as fa\nfrom kalmido.integrations.git import git_norm_base_url\n"
             "with fa.test_request_context():\n"
             "    for u in ('http://localhost:9999', 'http://127.0.0.1:8099', 'https://git.example.com/api'):\n"
             "        try:\n            print('git', u, git_norm_base_url(u))\n"
             "        except Exception as e:\n            print('git', u, 'refused', type(e).__name__)")
check("git http://localhost:9999 refused" in out, "#2875 a Git server on localhost over http:// needs the allow list too " + out[-400:])
check("git http://127.0.0.1:8099 http://127.0.0.1:8099" in out and "git https://git.example.com/api https://git.example.com" in out,
      "#2875 an allowed host and https:// stay as before " + out[-400:])
out = in_app("from flask import g\nfrom kalmido.core.config import app as fa\nfrom kalmido.notify.channels import chn_note, CH_NOTE_MAX\n"
             "with fa.test_request_context():\n"
             "    for i in range(CH_NOTE_MAX + 50):\n        chn_note(c, i + 1, 'created')\n"
             "    chn_note(c, 1, 'comment', 7)\n    chn_note(c, 1, 'created', 9)\n"
             "    print('noted', len(g.chn), CH_NOTE_MAX, g.chn[(1, 'newtask')])")
check("noted 200 200 {'cid': 9}" in out, "#2875 list events per request are capped, a known one still takes its comment " + out[-300:])

sys.exit(done("p2306_d3_files_agents_hardening"))
