#!/usr/bin/env python3
"""2.48.0 API tests, part A (#1207): the file store ("Ablage"). Invented names only, generated file contents.
 - own space: folders, upload, same name = a new version, restore an old version, rename, move, trash + restore, purge
 - shares with a person / group / agent, view vs edit, inheritance through folders, expiry
 - organisation boundary: a node of organisation X only for members of X; org admins are owners; "whole organisation" access
 - agents: nothing without a share (404), their own result folder (write without a share), every access in the history
 - links to a task file: the rights of the original
 - v1: scopes files:read / files:write, list / meta / content / text / create / new version
 - rollback: only new tables
usage: p248_a_api_test.py <datadir>      (a fresh container; P248A_NOSTART=1: the container runs already)"""
import base64
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
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


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
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


def up(s, name, data, parent=None, space=None, replace=None):
    form = {}
    if parent:
        form["parent_id"] = str(parent)
    if space:
        form["space"] = space
    if replace is not None:
        form["replace"] = replace
    return s.post(B + "/api/files/upload", data=form, files={"file": (name, data)})


def folder(s, name, parent=None, space=None):
    b = {"name": name}
    if parent:
        b["parent_id"] = parent
    if space:
        b["space"] = space
    r = s.post(B + "/api/files/folders", json=b)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def ls(s, parent=None, space=None):
    r = s.get(B + "/api/files", params={"parent": parent} if parent else {"space": space or "private"})
    return r


def names(r):
    return sorted(x["name"] for x in r.json().get("items", [])) if r.ok else None


def content(s, nid, v=None):
    return s.get(B + f"/api/files/nodes/{nid}/content", params={"v": v} if v else {})


def tiny_pdf(text):
    """A one-page PDF with a text layer (hand-written, no library)."""
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


if not os.environ.get("P248A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = ids["bob"], ids["carol"], ids["dave"], ids["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok, "setup: carol joins Alpha")
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id NOT IN (?))",
    (ORG, BOB, CAROL, ORG2, DAVE), write=True)
# erin: no organisation; alice shares privately with her
r = A.post(B + "/api/admin/agents", json={"username": "alphabot", "display_name": "Alphabot"})
assert r.status_code == 201, r.text
OAG, OAGT = r.json()["id"], r.json().get("token") or ""
dbx("UPDATE agents SET org_id=?, owner_id=? WHERE user_id=?", (ORG, BOB, OAG), write=True)
dbx("DELETE FROM org_members WHERE user_id=?", (OAG,), write=True)
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG, OAG), write=True)
for s in (A, Bo):
    s.post(B + "/api/auth/logout")
A, Bo, Ca, Da, Er = sess("alice"), sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
r = A.post(B + "/api/admin/agents", json={"username": "alicebot", "display_name": "Alicebot"})
assert r.status_code == 201, r.text
PAG, PAGT = r.json()["id"], r.json().get("token") or ""
dbx("DELETE FROM org_members WHERE user_id=?", (PAG,), write=True)
dbx("UPDATE agents SET org_id=NULL, owner_id=1 WHERE user_id=?", (PAG,), write=True)  # alice's personal agent
r = A.post(B + "/api/admin/groups", json={"name": "Readers"})
assert r.ok, r.text
GID = r.json()["id"]
for u in (1, ERIN, DAVE):  # also connects alice with erin / dave (people one may share with)
    dbx("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,'2026-01-01T00:00:00+00:00')", (GID, u), write=True)
AGS = tok(PAGT)
OAGS = tok(OAGT)

# ---- rollback: only new tables, nullable / defaulted columns
cols = dbx("SELECT table_name, column_name, is_nullable, column_default FROM information_schema.columns WHERE table_name LIKE 'fs\\_%'")
check({r[0] for r in cols} == {"fs_nodes", "fs_versions", "fs_shares", "fs_log"}, f"four new tables ({sorted({r[0] for r in cols})})")
rls = dbx("SELECT relrowsecurity FROM pg_class WHERE relname='fs_nodes'")
check(rls and rls[0][0], "fs_nodes has row-level security")

# ---- own space: folders, upload, versions
F1 = folder(A, "Reports")
check(names(ls(A)) == ["Reports"], f"the folder is at the top of the own space ({names(ls(A))})")
r = up(A, "plan.txt", b"version one", parent=F1)
check(r.status_code == 201, f"upload ({r.status_code} {r.text[:200]})")
P1 = r.json()["items"][0]["id"]
check(content(A, P1).content == b"version one", "download gives the content back")
r = up(A, "plan.txt", b"version two", parent=F1)
check(r.status_code == 201 and r.json()["items"][0]["id"] == P1, "same name in the same folder: the same file")
d = A.get(B + f"/api/files/nodes/{P1}").json()
check([v["no"] for v in d.get("versions", [])] == [2, 1], f"two versions, newest first ({d.get('versions')})")
check(content(A, P1).content == b"version two" and content(A, P1, 1).content == b"version one", "the old version stays downloadable")
r = A.post(B + f"/api/files/nodes/{P1}/versions/1/restore")
check(r.ok and content(A, P1).content == b"version one" and r.json()["version"] == 3, "restore = a new version 3 with the old content")
r = up(A, "plan.txt", b"keep both", parent=F1, replace="0")
check(r.ok and r.json()["items"][0]["name"] == "plan (2).txt", f"replace=0 keeps both ({r.text[:120]})")
P2 = r.json()["items"][0]["id"]
check(up(A, "empty.txt", b"", parent=F1).status_code == 400, "an empty file is refused")
r = A.patch(B + f"/api/files/nodes/{P2}", json={"name": "notes.txt"})
check(r.ok and r.json()["name"] == "notes.txt", "rename")
F2 = folder(A, "Archive")
r = A.patch(B + f"/api/files/nodes/{P2}", json={"parent_id": F2})
check(r.ok and names(ls(A, F2)) == ["notes.txt"], "move into another folder")
check(A.patch(B + f"/api/files/nodes/{F1}", json={"parent_id": F1}).status_code == 409, "a folder cannot move into itself")
# trash + restore + purge
check(A.delete(B + f"/api/files/nodes/{F2}").ok, "delete moves to the trash")
check(names(ls(A)) == ["Reports"] and content(A, P2).status_code == 404, "trashed: gone from the tree, its files too")
tr = ls(A, space="trash").json()["items"]
check([x["id"] for x in tr] == [F2], f"the trash lists the folder once ({[x['name'] for x in tr]})")
check(A.post(B + f"/api/files/nodes/{F2}/restore").ok and content(A, P2).content == b"keep both", "restore brings the subtree back")
A.delete(B + f"/api/files/nodes/{F2}")
check(A.delete(B + f"/api/files/nodes/{F1}", params={"purge": "1"}).status_code == 409, "purge only from the trash")
check(A.delete(B + f"/api/files/nodes/{F2}", params={"purge": "1"}).ok, "purge")
check(not dbx("SELECT 1 FROM fs_nodes WHERE id IN (?,?)", (F2, P2)), "purged: the rows are gone")
check(not dbx("SELECT 1 FROM fs_versions WHERE node_id=?", (P2,)), "purged: the versions are gone")
FX = folder(A, "Old stuff")
PX = up(A, "old.txt", b"old", parent=FX).json()["items"][0]["id"]
A.delete(B + f"/api/files/nodes/{FX}")
check(A.delete(B + f"/api/files/nodes/{PX}", params={"purge": "1"}).ok, "purge a file inside a deleted folder")
check(not dbx("SELECT 1 FROM fs_nodes WHERE id=?", (PX,)) and dbx("SELECT 1 FROM fs_nodes WHERE id=? AND deleted_at IS NOT NULL", (FX,)),
      "only that file is gone, its folder stays in the trash")

# ---- shares with a person: view / edit, inheritance, expiry
check(Er.get(B + f"/api/files/nodes/{P1}").status_code == 404, "not shared: 404 for another person")
t = A.get(B + f"/api/files/nodes/{F1}/share-targets").json()
check(any(p["id"] == ERIN for p in t["people"]), "erin is a share target of alice's private folder")
check(any(a["id"] == PAG for a in t["agents"]) and not any(a["id"] == OAG for a in t["agents"]),
      "private folder: alice's own agent yes, an organisation's agent no")
r = A.post(B + f"/api/files/nodes/{F1}/shares", json={"user_id": ERIN, "role": "view"})
check(r.status_code == 201, f"share the folder with erin (view) ({r.text[:120]})")
SH = r.json()["id"]
check(content(Er, P1).content == b"version one", "erin reads the file inside (inherited)")
check("Reports" in (names(ls(Er, space="shared")) or []), "the folder is in erin's 'shared with me'")
check(up(Er, "x.txt", b"x", parent=F1).status_code == 403, "view: no upload")
check(Er.delete(B + f"/api/files/nodes/{P1}").status_code == 403, "view: no delete")
check(Er.post(B + f"/api/files/nodes/{F1}/shares", json={"user_id": DAVE, "role": "view"}).status_code == 403, "only the owner shares")
check(A.patch(B + f"/api/files/shares/{SH}", json={"role": "edit"}).ok, "role -> edit")
r = up(Er, "from-erin.txt", b"hello", parent=F1)
check(r.status_code == 201, "edit: erin uploads into the folder")
EF = r.json()["items"][0]["id"]
check(dbx("SELECT owner_id, created_by FROM fs_nodes WHERE id=?", (EF,))[0] == (1, ERIN), "the file belongs to alice's tree, added by erin")
check(A.patch(B + f"/api/files/shares/{SH}", json={"expires_at": "2000-01-01"}).ok, "expiry in the past")
check(content(Er, P1).status_code == 404, "expired share: no access")
check(A.patch(B + f"/api/files/shares/{SH}", json={"expires_at": "2999-01-01"}).ok and content(Er, P1).ok, "expiry in the future: access")
check(A.post(B + f"/api/files/nodes/{F1}/shares", json={"user_id": BOB, "role": "view"}).status_code in (201, 409), "bob: a share target or refused")

# ---- groups
F3 = folder(A, "For the group")
r = A.post(B + f"/api/files/nodes/{F3}/shares", json={"group_id": GID, "role": "view"})
check(r.status_code == 201, f"share with a group ({r.text[:120]})")
check(Da.get(B + "/api/files", params={"parent": F3}).ok, "a group member sees the folder")
check(Ca.get(B + "/api/files", params={"parent": F3}).status_code == 404, "a non-member does not")

# ---- agents: nothing without a share, the own folder, the history
r = AGS.get(B + "/api/v1/files")
check(r.ok, f"v1 list for the agent ({r.status_code} {r.text[:200]})")
top = r.json().get("data", [])
own = [x for x in top if x.get("agent_id") == PAG]
check(len(own) == 1 and own[0]["name"] == "Alicebot", f"the agent's own result folder is created ({[x['name'] for x in top]})")
check(not any(x["id"] == F1 for x in top), "nothing of alice's that is not shared")
check(AGS.get(B + f"/api/v1/files/{P1}").status_code == 404, "an agent without a share: 404")
r = AGS.post(B + "/api/v1/files", json={"name": "report.md", "content": "# Result\n"})
check(r.status_code == 201 and r.json()["parent_id"] == own[0]["id"], f"the agent writes into its own folder ({r.text[:160]})")
AR = r.json()["id"]
check(content(A, AR).content == b"# Result\n", "the owner reads the agent's result")
r = AGS.post(B + "/api/v1/files", json={"name": "fix.sh", "content": "echo hi"})
check(r.status_code == 201 and r.json()["name"] == "fix.sh.txt", "an agent's executable ending gets .txt")
check(AGS.post(B + "/api/v1/files", json={"parent_id": F1, "name": "x.md", "content": "x"}).status_code == 404, "no write into a folder not shared")
r = A.post(B + f"/api/files/nodes/{F1}/shares", json={"agent_id": PAG, "role": "view"})
check(r.status_code == 201, f"share the folder with the agent (view) ({r.text[:120]})")
ev = dbx("SELECT payload FROM agent_events WHERE agent_id=? AND event='file_shared'", (PAG,))
check(len(ev) == 1 and str(F1) in ev[0][0], "the agent gets the event file_shared")
r = AGS.get(B + f"/api/v1/files/{F1}")
check(r.ok and any(x["id"] == P1 for x in r.json().get("children", [])), "the agent lists the shared folder")
r = AGS.get(B + f"/api/v1/files/{P1}/content")
check(r.ok and r.content == b"version one", "the agent downloads a file")
check(AGS.post(B + f"/api/v1/files/{P1}/versions", json={"content": "agent"}).status_code == 403, "view: no new version")
check(AGS.post(B + f"/api/v1/files/{F1}/shares", json={}).status_code in (403, 404, 405), "no sharing through the API")
A.post(B + f"/api/files/nodes/{F1}/shares", json={"agent_id": PAG, "role": "edit"})
r = AGS.post(B + f"/api/v1/files/{P1}/versions", json={"content_base64": base64.b64encode(b"by the agent").decode()})
check(r.status_code == 201 and content(A, P1).content == b"by the agent", f"edit: the agent uploads a new version ({r.text[:120]})")
log = A.get(B + f"/api/files/nodes/{P1}").json().get("log", [])
acts = {x["action"] for x in log if x["agent"]}
check({"download", "version"} <= acts, f"the history has the agent's accesses ({sorted(acts)})")
check(not any(x["action"] == "download" and not x["agent"] for x in log), "people's reads are not logged")
# review: an agent never writes a new version of an executable file; the API path shows only visible folders
SH_ = up(A, "deploy.sh", b"echo ok", parent=F1).json()["items"][0]["id"]
check(AGS.post(B + f"/api/v1/files/{SH_}/versions", json={"content": "rm -rf /"}).status_code == 403, "no new version of a .sh by an agent")
SUB = folder(A, "Deep", parent=F1)
A.post(B + f"/api/files/nodes/{SUB}/shares", json={"user_id": DAVE, "role": "view"})
Dv = sess("dave")
check(Dv.get(B + f"/api/files", params={"parent": SUB}).json().get("crumbs") == [{"id": SUB, "name": "Deep"}], "crumbs: only the shared folder, not the one above")
# expiry with an offset is compared in UTC
A.patch(B + f"/api/files/shares/{SH}", json={"expires_at": "2000-01-01T10:00+05:00"})
check(dbx("SELECT expires_at FROM fs_shares WHERE id=?", (SH,))[0][0] == "2000-01-01T05:00:00+00:00", "expiry stored in UTC")
A.patch(B + f"/api/files/shares/{SH}", json={"expires_at": None})
pdf = tiny_pdf("Quarterly figures")
r = AGS.post(B + "/api/v1/files", json={"parent_id": F1, "name": "q.pdf", "content_base64": base64.b64encode(pdf).decode(), "mime": "application/pdf"})
check(r.status_code == 201, f"the agent stores a PDF ({r.text[:120]})")
if r.ok:
    t = AGS.get(B + f"/api/v1/files/{r.json()['id']}/text").json()
    check("Quarterly figures" in (t.get("text") or ""), f"the text of the PDF ({str(t)[:160]})")
# scopes
dbx("UPDATE api_tokens SET scopes='read' WHERE user_id=?", (PAG,), write=True)
check(AGS.get(B + "/api/v1/files").status_code == 403, "without files:read: 403")
dbx("UPDATE api_tokens SET scopes='read,files:read' WHERE user_id=?", (PAG,), write=True)
check(AGS.get(B + "/api/v1/files").ok and AGS.post(B + "/api/v1/files", json={"name": "y.md", "content": "y"}).status_code == 403,
      "files:read without files:write: reading only")
dbx("UPDATE api_tokens SET scopes='read,tasks:write,comments,files:read,files:write' WHERE user_id=?", (PAG,), write=True)
spec = A.get(B + "/api/v1/openapi.json").json() if A.get(B + "/api/v1/openapi.json").ok else requests.get(B + "/api/v1/openapi.json").json()
check(spec["paths"]["/files"]["post"]["x-kalmido-scope"] == "files:write" and spec["paths"]["/files/{id}/content"]["get"]["x-kalmido-scope"] == "files:read",
      "OpenAPI declares the scopes")

# ---- organisation: boundary, admins, whole organisation
OF = folder(Ca, "Team docs", space=f"org:{ORG}")
r = up(Ca, "minutes.txt", b"org minutes", parent=OF)
OFILE = r.json()["items"][0]["id"]
check(Bo.get(B + f"/api/files/nodes/{OFILE}").ok, "the organisation's admin sees a member's folder (owner role)")
check(Da.get(B + f"/api/files/nodes/{OFILE}").status_code == 404 and A.get(B + f"/api/files/nodes/{OFILE}").status_code == 404,
      "another organisation / a non-member: 404")
check(Da.get(B + "/api/files", params={"space": f"org:{ORG}"}).status_code == 404, "listing a foreign organisation: 404")
t = Ca.get(B + f"/api/files/nodes/{OF}/share-targets").json()
check(not any(p["id"] in (DAVE, ERIN) for p in t["people"]), "organisation folder: only its members as share targets")
check(any(a["id"] == OAG for a in t["agents"]) and not any(a["id"] == PAG for a in t["agents"]), "organisation folder: only its agents")
check(Ca.post(B + f"/api/files/nodes/{OF}/shares", json={"user_id": DAVE, "role": "view"}).status_code == 409, "a person of another organisation: 409")
check(Ca.post(B + f"/api/files/nodes/{OF}/shares", json={"agent_id": PAG, "role": "view"}).status_code == 409, "a private agent on an organisation folder: 409")
OAGF = OAGS.get(B + "/api/v1/files")
check(OAGF.ok and not any(x["id"] == OF for x in OAGF.json()["data"]), "the organisation's agent sees nothing unshared")
oown = [x for x in OAGF.json()["data"] if x.get("agent_id") == OAG]
check(len(oown) == 1 and oown[0]["org_id"] == ORG, "the organisation agent's folder lies in the organisation")
check(Bo.get(B + f"/api/files/nodes/{oown[0]['id']}").ok if oown else False, "the organisation's admin sees the agent's folder")
check(Ca.get(B + f"/api/files/nodes/{oown[0]['id']}").status_code == 404 if oown else False, "a plain member does not")
# whole organisation
F_OPEN = folder(Bo, "Handbook", space=f"org:{ORG}")
check(Ca.get(B + "/api/files", params={"parent": F_OPEN}).status_code == 404, "before: the member does not see bob's folder")
check(Bo.patch(B + f"/api/files/nodes/{F_OPEN}", json={"org_access": "view"}).ok, "open to the whole organisation (view)")
check(Ca.get(B + "/api/files", params={"parent": F_OPEN}).ok and "Handbook" in names(ls(Ca, space=f"org:{ORG}")), "after: every member sees it")
check(up(Ca, "x.txt", b"x", parent=F_OPEN).status_code == 403, "whole organisation view: no upload")
check(OAGS.get(B + f"/api/v1/files/{F_OPEN}").status_code == 404, "whole organisation never opens to agents")
check(A.patch(B + f"/api/files/nodes/{F1}", json={"org_access": "view"}).status_code == 409, "a private folder cannot be opened to an organisation")
# no move across workspaces
check(Ca.patch(B + f"/api/files/nodes/{OFILE}", json={"parent_id": None}).ok, "move to the top of the organisation")
MYF = folder(Ca, "Mine")
check(Ca.patch(B + f"/api/files/nodes/{OFILE}", json={"parent_id": MYF}).status_code == 409, "never into another workspace")

# ---- links to a task file: the original's rights
lists = A.get(B + "/api/state").json().get("lists", [])
inbox = next((l["id"] for l in lists if l.get("is_inbox")), None)
r = A.post(B + "/api/tasks", json={"title": "With a file", "list_id": inbox})
TID = r.json()["id"]
r = A.post(B + f"/api/tasks/{TID}/attachments", files={"file": ("contract.txt", b"original text")})
AID = [a for a in r.json().get("attachments", []) if a["name"] == "contract.txt"][0]["id"] if r.ok else None
r = A.post(B + "/api/files/links", json={"ref_kind": "att", "ref_id": AID, "parent_id": F1})
check(r.status_code == 201 and r.json()["kind"] == "link", f"a link to a task file ({r.text[:160]})")
LK = r.json()["id"]
check(content(A, LK).content == b"original text", "the link opens the original")
check(content(Er, LK).status_code == 404, "erin (edit on the folder) but not on the task: the link stays closed")
check(Er.post(B + "/api/files/links", json={"ref_kind": "att", "ref_id": AID}).status_code == 404, "no link to a file one cannot see")
check(not dbx("SELECT 1 FROM fs_versions WHERE node_id=?", (LK,)), "a link stores no copy")
lst = Er.get(B + "/api/files", params={"parent": F1}).json()["items"]
lk = [x for x in lst if x["id"] == LK]
check(lk and lk[0].get("no_access") and lk[0]["name"] != "contract.txt" and lk[0].get("ref_id") is None, "a link erin may not open shows nothing of its original")
# trashed: details only for who may restore
A.delete(B + f"/api/files/nodes/{LK}")
check(Er.get(B + f"/api/files/nodes/{LK}").status_code == 404 and A.get(B + f"/api/files/nodes/{LK}").ok, "a trashed node: details only for the owner")
A.post(B + f"/api/files/nodes/{LK}/restore")

# ---- quota counts the file store
q = dbx("SELECT COALESCE(SUM(size),0) FROM fs_versions WHERE created_by=1")[0][0]
check(q > 0, "versions are counted per uploader")

# ---- deleting a person: their branch of an organisation's tree goes to an admin, their own tree goes (files unlinked)
up(Ca, "private.txt", b"carol's own", parent=MYF)
own_paths = [r[0] for r in dbx("SELECT v.path FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id WHERE n.owner_id=? AND n.org_id IS NULL", (CAROL,))]
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,1,'admin') ON CONFLICT DO NOTHING", (ORG,), write=True)  # the instance admin may delete her
r = A.delete(B + f"/api/users/{CAROL}")
check(r.ok, f"carol is deleted ({r.status_code} {r.text[:120]})")
if r.ok:
    check(dbx("SELECT owner_id FROM fs_nodes WHERE id=?", (OF,)) in ([(1,)], [(BOB,)]), "her organisation folder stays, now owned by an admin of the organisation")
    check(Bo.get(B + f"/api/files/nodes/{OFILE}").ok, "its files stay readable for the organisation")
    check(not dbx("SELECT 1 FROM fs_nodes WHERE id=?", (MYF,)), "her own tree is gone")
    check(own_paths and not any(os.path.exists(os.path.join(DATA, "attachments", p)) for p in own_paths), "and its stored files are unlinked")
# ---- an organisation with files is not deleted (the trash does not count)
r = A.delete(B + f"/api/admin/orgs/{ORG}")
check(r.status_code == 409, f"an organisation with a file store: 409 ({r.status_code})")

# ---- the backup archive has the file store's files (attachments/files/<node>/<file>)
import time  # noqa: E402
import zipfile  # noqa: E402
n0 = len(A.get(B + "/api/admin/backups").json().get("items", []))
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, f"backup started ({r.status_code})")
for _ in range(100):
    j = A.get(B + "/api/admin/backups").json()
    if not j.get("running") and (len(j.get("items", [])) > n0 or j.get("last_error")):
        break
    time.sleep(0.3)
bdir = os.path.join(DATA, "backups")
zips = sorted(f for f in os.listdir(bdir) if f.endswith(".zip")) if os.path.isdir(bdir) else []
if zips:
    names = zipfile.ZipFile(os.path.join(bdir, zips[-1])).namelist()
    vp = dbx("SELECT path FROM fs_versions WHERE node_id=? ORDER BY no", (P1,))
    check(vp and all("attachments/" + x[0] in names for x in vp), f"the backup has every version of a file ({[x[0] for x in vp]})")
else:
    check(False, f"a backup archive in {bdir}: {j.get('last_error')}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
