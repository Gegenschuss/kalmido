#!/usr/bin/env python3
"""2.200.0 C (#1781): knowledge pages for agents (API v1 /wiki/pages, wiki/wkv1.py). Invented names only.
 - scopes wiki:read / wiki:write: an agent without them gets 403 (required_scope)
 - an agent sees a page only through a share of the page or a folder above it with exactly it (fs_shares.agent_id): the
   organisation's area gives it nothing (list empty, read / write / create 404); view reads, never writes (403, a create in
   a view folder makes nothing); edit writes (conflict guard 409 with the current page, the history), creates in the folder
 - paths start at the shared node; subfolders and pages added later are reached; revoking the share ends it at once
 - a space locked later (wiki_spaces.e2e): nothing, back when open again
 - tenant-matrix: wiki_v1 (the agent of another organisation 404, a person's token of another organisation 404)
 - freelancer-matrix: wiki (a person without an organisation: her token, her own agent on her shared folder, another person's
   agent never)
 - 2.200.0 F (#1781, review): the file store's API needs wiki:read / wiki:write for the knowledge tree and keeps the private
   rule; a share editor's token changes no path; a write-only token gets no text; 403 before the name; listings not logged
usage: p2200_c_wiki_agent_test.py <datadir>      (a fresh container; P2200C_NOSTART=1 = the server already runs)"""
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
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FEAT = "wiki,files,collab,comments"
WS = ["read", "wiki:read", "wiki:write"]

if not os.environ.get("P2200C_NOSTART"):
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
for u in ("bob", "olga"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u == "bob" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["olga"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ol = sess("bob"), sess("olga")
for s in (A, Bo, Ol):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def agent(name, org=None, owner=None, scopes=WS):
    body = {"scopes": list(scopes), "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


def token(s, scopes=WS):
    r = s.post(B + "/api/me/tokens", json={"name": "wiki", "scopes": list(scopes)})
    assert r.ok, r.text
    return bearer(r.json()["token"])


def page(s, path, text="", space=SP):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, (path, r.status_code, r.text)
    return r.json()["id"]


def folders(s, space=SP):
    r = s.get(B + "/api/wiki", params={"space": space})
    return {f["path"]: f["id"] for f in r.json().get("folders", [])} if r.ok else {}


def fshare(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def lst(t, **params):
    r = t.get(V + "/wiki/pages", params=params)
    return {x["id"]: x["path"] for x in r.json().get("data", [])} if r.ok else {"status": r.status_code}


def read(t, pid):
    r = t.get(V + f"/wiki/pages/{pid}")
    return r.json() if r.ok else r.status_code


def write(t, pid, **b):
    return t.patch(V + f"/wiki/pages/{pid}", json=b)


def create(t, fid, name, text="x"):
    return t.post(V + "/wiki/pages", json={"folder_id": fid, "name": name, "body": text})


def node_of(pid):
    r = sql("SELECT id, parent_id, name FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (pid,))
    return r[0] if r else None


# ================================================================ setup: pages of the organisation, agents
P1 = page(A, "Handbook/Shoot/Checklist", "- [ ] Batteries")
P2 = page(A, "Handbook/Intro", "Welcome")
P3 = page(A, "Secret/Plan", "do not tell")
F = folders(A)
HB, SH, SE = F.get("Handbook"), F.get("Handbook/Shoot"), F.get("Secret")
check(HB and SH and SE, f"setup: the knowledge folders {F}")
TA, ta = agent("alphabot", org=ORG)
TB, tb = agent("betabot", org=BETA)
_, t0 = agent("noscope", org=ORG, scopes=["read"])

# ================================================================ scopes
r = t0.get(V + "/wiki/pages")
check(r.status_code == 403 and r.json().get("error", {}).get("required_scope") == "wiki:read", f"no wiki:read: 403 ({r.status_code} {r.text[:120]})")
r = t0.patch(V + f"/wiki/pages/{P1}", json={"body": "x"})
check(r.status_code == 403, "no wiki:write: 403")
spec = requests.get(V + "/openapi.json").json()["paths"]
check(spec.get("/wiki/pages", {}).get("get", {}).get("x-kalmido-scope") == "wiki:read"
      and spec.get("/wiki/pages/{id}", {}).get("patch", {}).get("x-kalmido-scope") == "wiki:write", "OpenAPI: the wiki scopes")

# ================================================================ same organisation, no share: nothing
check(lst(ta) == {}, f"no share: the agent lists nothing {lst(ta)}")
check(read(ta, P1) == 404 and write(ta, P1, body="x").status_code == 404, "no share: read / write 404 (no right from the area)")
check(create(ta, HB, "New").status_code == 404, "no share: create in the folder 404")
check(lst(ta, space=SP) == {} and lst(ta, space="shared") == {}, "no share: every space filter empty")

# ================================================================ a view share on a folder
S1 = fshare(A, HB, agent_id=TA, role="view")
L = lst(ta)
check(L == {P1: "Handbook/Shoot/Checklist", P2: "Handbook/Intro"}, f"view share: the folder's pages, paths from the shared folder {L}")
d = read(ta, P1)
check(isinstance(d, dict) and d.get("body") == "- [ ] Batteries" and d.get("role") == "view" and d.get("path") == "Handbook/Shoot/Checklist",
      f"view share: the agent reads the text {d}")
check(read(ta, P3) == 404, "a page outside the shared folder: 404")
check(write(ta, P1, body="hacked").status_code == 403, "view: no write (403)")
n0 = sql("SELECT COUNT(*) FROM wiki_pages WHERE org_id=?", (ORG,))[0][0]
check(create(ta, SH, "Lens").status_code == 403 and sql("SELECT COUNT(*) FROM wiki_pages WHERE org_id=?", (ORG,))[0][0] == n0,
      "view: a create in the folder 403, nothing made")
P4 = page(A, "Handbook/Shoot/Lights", "LED")
check(P4 in lst(ta) and read(ta, P4) != 404, "a page added later in a subfolder is reached")
check(sql("SELECT COUNT(*) FROM fs_log WHERE node_id=? AND agent=1 AND action='text'", (node_of(P1)[0],))[0][0] >= 1,
      "the agent's read is noted in the node's history")

# ================================================================ a page shared alone: only its own name
S2 = fshare(A, node_of(P3)[0], agent_id=TA, role="view")
L = lst(ta)
check(L.get(P3) == "Plan" and read(ta, P3).get("path") == "Plan", f"a page shared alone: path = its name, nothing above {L.get(P3)}")
A.delete(B + f"/api/files/shares/{S2}")
check(read(ta, P3) == 404, "share of the page revoked: 404")

# ================================================================ edit: write with the conflict guard, create
check(A.patch(B + f"/api/files/shares/{S1}", json={"role": "edit"}).ok, "setup: the share to edit")
d = read(ta, P1)
check(d.get("role") == "edit", "edit share: role edit")
r = write(ta, P1, body="- [x] Batteries", expect_updated_at=d["updated_at"])
check(r.status_code == 200 and r.json().get("body") == "- [x] Batteries", f"edit: the agent writes ({r.status_code} {r.text[:200]})")
w = A.get(B + f"/api/wiki/pages/{P1}").json()
check(w.get("body") == "- [x] Batteries" and w.get("updated_by") == TA and w.get("path") == "Handbook/Shoot/Checklist",
      "alice sees the agent's text, the agent as editor, the path unchanged")
hv = A.get(B + f"/api/wiki/pages/{P1}/versions")
check(hv.ok and len(hv.json().get("versions", [])) >= 1, f"the history has the save ({hv.status_code})")
r = write(ta, P1, body="old view", expect_updated_at="2000-01-01T00:00:00.000Z")
check(r.status_code == 409 and r.json().get("error", {}).get("page", {}).get("body") == "- [x] Batteries",
      f"conflict guard: 409 with the current page ({r.status_code})")
check(write(ta, P1, path="Elsewhere/Checklist", body="x").status_code == 400, "an agent does not rename (unknown field path)")
r = create(ta, SH, "Tripod", "three legs")
check(r.status_code == 201 and r.json().get("path") == "Handbook/Shoot/Tripod", f"edit: the agent creates in the subfolder ({r.status_code} {r.text[:200]})")
P5 = r.json().get("id") if r.status_code == 201 else 0
n = node_of(P5)
check(n and n[1] == SH and n[2] == "Tripod", f"its node lies in the folder {n}")
check(sql("SELECT path, created_by FROM wiki_pages WHERE id=?", (P5,))[0] == ("Handbook/Shoot/Tripod", TA), "path kept for older versions, made by the agent")
check(P5 in {p["id"] for p in A.get(B + "/api/wiki", params={"space": SP}).json()["pages"]}, "alice sees the new page")
check(create(ta, SH, "Tripod").status_code == 409, "a taken name: 409")
check(create(ta, SH, "a/b").status_code == 400, "a name with / : 400")
check(create(ta, SE, "Sneak").status_code == 404, "a folder not shared: 404")
check(write(ta, P1, body="y" * 500_001).status_code == 400, "the size limit of the web route")

# ================================================================ a person's token: what the person sees
bt = token(Bo)
L = lst(bt, space=SP)
check({P1, P2, P3, P4, P5} <= set(L) and L.get(P3) == "Secret/Plan", f"bob's token: every page of his organisation, full paths {len(L)}")
check(write(bt, P2, body="hello", path="Handbook/Welcome").status_code == 200 and read(bt, P2).get("path") == "Handbook/Welcome",
      "a person's token may rename (path)")
r = bt.post(V + "/wiki/pages", json={"space": SP, "path": "Notes/Bob", "body": "b"})
check(r.status_code == 201 and r.json().get("path") == "Notes/Bob", f"a person's token creates like the app ({r.status_code} {r.text[:200]})")

# ================================================================ tenant-matrix: wiki_v1
check(lst(tb) == {} and read(tb, P1) == 404 and write(tb, P1, body="x").status_code == 404, "the other organisation's agent: 404")
check(create(tb, SH, "Sneak").status_code == 404, "the other organisation's agent cannot create in Alpha's folder")
ot = token(Ol)
check(P1 not in lst(ot) and read(ot, P1) == 404 and write(ot, P1, body="x").status_code == 404 and create(ot, SH, "x").status_code == 404,
      "olga's token (other organisation): 404")

# ================================================================ locked later: nothing; open again: back
sql("INSERT INTO wiki_spaces(org_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (ORG,), write=True)
check(read(ta, P1) == 404 and lst(ta) == {} and create(ta, SH, "Locked").status_code == 404, "a space locked later: the agent gets nothing")
check(read(bt, P1) == 404, "a locked space never comes through the API (also not for its people)")
sql("DELETE FROM wiki_spaces WHERE org_id=?", (ORG,), write=True)
check(read(ta, P1) != 404, "open again: the share counts again")

# ================================================================ revoking
check(A.delete(B + f"/api/files/shares/{S1}").ok, "setup: the share revoked")
check(lst(ta) == {} and read(ta, P1) == 404 and write(ta, P1, body="x").status_code == 404, "revoked: 404 at once")

# ================================================================ a person without an organisation
# freelancer-matrix: wiki
FID, Fl = freelancer(B, A, features=FEATURES + ",wiki,files")
DA, da = agent("fridabot", owner=FID)
AA, aa = agent("alicebot", owner=uid["alice"])
Q1 = page(Fl, "Clients/Acme/Contacts", "Jane", space="private")
Q2 = page(Fl, "Diary", "private", space="private")
FF = folders(Fl, "private")
CL = FF.get("Clients")
check(CL, f"setup: her folder {FF}")
ft = token(Fl)
L = lst(ft)
check(L.get(Q1) == "Clients/Acme/Contacts" and Q2 in L, f"her token: her pages, full paths {L}")
check(lst(da) == {} and read(da, Q1) == 404, "her own agent: nothing without a share")
fshare(Fl, CL, agent_id=DA, role="edit")
check(lst(da) == {Q1: "Clients/Acme/Contacts"} and read(da, Q1).get("body") == "Jane", "her agent with the folder share reads")
check(write(da, Q1, body="Jane Doe").status_code == 200, "and writes")
r = create(da, CL, "Globex", "new client")
check(r.status_code == 201 and r.json().get("space") == "private", f"and creates in her private folder ({r.status_code} {r.text[:160]})")
Q3 = r.json().get("id") if r.status_code == 201 else 0
check(sql("SELECT owner_id, created_by FROM wiki_pages WHERE id=?", (Q3,))[0] == (FID, DA), "the page stays hers, made by her agent")
check(Q3 in {p["id"] for p in Fl.get(B + "/api/wiki", params={"space": "private"}).json()["pages"]}, "she sees it in her index")
check(read(da, Q2) == 404, "a page outside the shared folder: 404")
check(read(aa, Q1) == 404 and lst(aa) == {} and create(aa, CL, "x").status_code == 404, "another person's agent: never")
check(read(ta, Q1) == 404, "an organisation's agent: never")

# ================================================================ 2.200.0 F (#1781, review): the rules hold on every way in
# 6: a listing is not noted per page (reads / writes / creations are)
nl = sql("SELECT COUNT(*) FROM fs_log WHERE node_id=? AND action='list'", (node_of(Q1)[0],))[0][0]
lst(da)
check(sql("SELECT COUNT(*) FROM fs_log WHERE node_id=? AND action='list'", (node_of(Q1)[0],))[0][0] == nl, "review 6: listing writes no history")
# 1 + 3: the file store's API -- a page's text needs wiki:read, a knowledge folder wiki:read / wiki:write
FO, fo = agent("filesonly", owner=FID, scopes=["read", "files:read", "files:write"])
fshare(Fl, CL, agent_id=FO, role="edit")
names = {x.get("name") for x in fo.get(V + "/files").json().get("data", [])}
check("Clients" not in names and "Contacts" not in names, f"review 1: files:read alone lists no knowledge folder / page {names}")
check(fo.get(V + "/files", params={"parent_id": CL}).status_code == 403, "review 1: a knowledge folder's children need wiki:read")
for suf in ("text", "content"):
    r = fo.get(V + f"/files/{node_of(Q1)[0]}/{suf}")
    check(r.status_code in (403, 404) and "Jane" not in r.text, f"review 1: /files/<page>/{suf} without wiki:read ({r.status_code})")
nf = sql("SELECT COUNT(*) FROM fs_nodes WHERE parent_id=?", (CL,))[0][0]
r = fo.post(V + "/files", json={"parent_id": CL, "name": "Drop", "kind": "folder"})
check(r.status_code == 403 and sql("SELECT COUNT(*) FROM fs_nodes WHERE parent_id=?", (CL,))[0][0] == nf,
      f"review 3: files:write makes no folder in the knowledge tree without wiki:write ({r.status_code})")
r = da.get(V + "/files", params={"parent_id": CL})
check(r.status_code == 403, f"review 1: wiki:read alone opens no file store listing ({r.status_code})")
# 1: another person's agent never gets a private page, not through the file store either
AF, af = agent("alicefiles", owner=uid["alice"], scopes=[*WS, "files:read"])
r = Fl.post(B + f"/api/files/nodes/{CL}/shares", json={"agent_id": AF, "role": "view"})
if r.status_code == 201:
    t = af.get(V + f"/files/{node_of(Q1)[0]}/text")
    kids = af.get(V + "/files", params={"parent_id": CL})
    check(t.status_code == 404 and "Jane" not in t.text, f"review 1: another person's agent: the page's text 404 ({t.status_code})")
    check(kids.status_code != 200 or "Contacts" not in kids.text, "review 1: and no page title in the folder's listing")
    check(read(af, Q1) == 404 and Q1 not in lst(af), "review 1: and nothing through /wiki/pages")
else:
    check(r.status_code in (403, 404, 409), f"review 1: sharing her folder with another person's agent refused ({r.status_code})")
# 2: a person whose edit comes from a share changes the text, never path / relink
R1 = page(A, "Recipes/Soup", "salt", space="private")
fshare(A, folders(A, "private")["Recipes"], user_id=uid["bob"], role="edit")
check(write(bt, R1, path="Recipes/Stew").status_code == 403 and write(bt, R1, relink=False, body="x").status_code == 403,
      "review 2: a share editor's token: path / relink 403")
check(sql("SELECT path, body FROM wiki_pages WHERE id=?", (R1,))[0][0] == "Recipes/Soup", "review 2: nothing renamed")
check(write(bt, R1, body="pepper").status_code == 200, "review 2: the text through the share")
# 4: a token that may only write gets no text back
wo = token(Bo, scopes=["read", "wiki:write"])
r = write(wo, P2, body="written")
check(r.status_code == 200 and "body" not in r.json() and "attrs" not in r.json(), f"review 4: write-only token: no text back {r.text[:160]}")
r = write(wo, P2, body="older", expect_updated_at="2000-01-01T00:00:00.000Z")
check(r.status_code == 409 and "body" not in r.json().get("error", {}).get("page", {}), "review 4: the conflict without the text")
# 7: a folder shared to read: 403 before the name check (no 409 that tells a name exists)
S3 = fshare(A, SE, agent_id=TA, role="view")
check(create(ta, SE, "Plan").status_code == 403 and create(ta, SE, "Nothing").status_code == 403, "review 7: view folder: 403 for any name")
A.delete(B + f"/api/files/shares/{S3}")


print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
