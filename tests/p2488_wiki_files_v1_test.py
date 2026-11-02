#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.488.0 B (#2209): the files of a knowledge page for agents and tokens (API v1, wiki/wkv1.py). Invented names only.
 - GET /api/v1/wiki/pages/{id}/files lists a page's files (name, size, mime, id, time), GET /api/v1/wiki/files/{id} gives the
   bytes, GET /api/v1/wiki/files/{id}/text the text of a PDF (a picture: kind image)
 - the page's own rule (wkv_need): an agent only through a share of the page / a folder above it (none: 404), a page of
   another organisation 404, a file in the trash 404, a page in the trash 404, a locked space (wiki_spaces.e2e) 404,
   a file the virus scan found infected 403
 - scope wiki:read (a token without it 403 with required_scope), the OpenAPI document names it on all three routes
 - the agent's reads are noted in the history of the page's node (fs_log: meta / download / text)
 - tenant-matrix: wiki_v1 (another organisation's agent and person's token 404)
 - freelancer-matrix: wiki (a person without an organisation: her token, her own agent on her shared folder reads her
   page's files, another person's agent never)
usage: p2488_wiki_files_v1_test.py <datadir>"""
import base64
import sys

import requests

import kt
from kt import B, check, dbx, sess
from freelancer_fixture import FEATURES, freelancer

V = B + "/api/v1"
FEAT = "wiki,files,collab,comments"
WS = ["read", "wiki:read"]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")

kt.fresh()
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
SP = f"org:{ORG}"
r = A.post(B + "/api/users", json={"username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com", "orgs": []})
assert r.ok, r.text
OLGA = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": OLGA})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Ol = sess("olga")
Ol.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})


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
    r = s.post(B + "/api/me/tokens", json={"name": "wikifiles", "scopes": list(scopes)})
    assert r.ok, r.text
    return bearer(r.json()["token"])


def page(s, path, space=SP):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": "text"})
    assert r.status_code == 201, (path, r.status_code, r.text)
    return r.json()["id"]


def upload(s, pid, *files):
    r = s.post(B + f"/api/wiki/pages/{pid}/files", files=[("file", f) for f in files])
    assert r.status_code == 201, r.text
    return [f["id"] for f in r.json()["files"]]


def folders(s, space=SP):
    r = s.get(B + "/api/wiki", params={"space": space})
    return {f["path"]: f["id"] for f in r.json().get("folders", [])} if r.ok else {}


def fshare(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def files(t, pid):
    r = t.get(V + f"/wiki/pages/{pid}/files")
    return {x["id"]: x for x in r.json().get("data", [])} if r.ok else r.status_code


def get(t, fid):
    return t.get(V + f"/wiki/files/{fid}")


def text(t, fid):
    r = t.get(V + f"/wiki/files/{fid}/text")
    return r.json() if r.ok else r.status_code


def node_of(pid):
    r = dbx("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?", (pid,))
    return r[0][0] if r else None


# ================================================================ setup: pages with files, agents
P1 = page(A, "Handbook/Shoot/Checklist")
P2 = page(A, "Secret/Plan")
F1, F2 = upload(A, P1, ("Contract.pdf", PDF, "application/pdf"), ("Sketch.png", PNG, "image/png"))
(F3,) = upload(A, P2, ("Hidden.pdf", PDF, "application/pdf"))
HB = folders(A).get("Handbook")
check(HB, "setup: the knowledge folder Handbook")
TA, ta = agent("alphabot", org=ORG)
TB, tb = agent("betabot", org=BETA)
_, t0 = agent("noscope", org=ORG, scopes=["read"])

# ================================================================ scope wiki:read, OpenAPI
r = t0.get(V + f"/wiki/pages/{P1}/files")
check(r.status_code == 403 and r.json().get("error", {}).get("required_scope") == "wiki:read", f"no wiki:read: list 403 ({r.status_code} {r.text[:120]})")
check(get(t0, F1).status_code == 403 and t0.get(V + f"/wiki/files/{F1}/text").status_code == 403, "no wiki:read: bytes / text 403")
spec = requests.get(V + "/openapi.json").json()["paths"]
for p in ("/wiki/pages/{id}/files", "/wiki/files/{id}", "/wiki/files/{id}/text"):
    check(spec.get(p, {}).get("get", {}).get("x-kalmido-scope") == "wiki:read", f"OpenAPI: {p} needs wiki:read")

# ================================================================ not shared: nothing
check(files(ta, P1) == 404, "no share: the page's files 404")
check(get(ta, F1).status_code == 404 and text(ta, F1) == 404, "no share: a file's bytes / text 404")

# ================================================================ shared: visible
fshare(A, HB, agent_id=TA, role="view")
L = files(ta, P1)
check(isinstance(L, dict) and set(L) == {F1, F2}, f"shared folder: the page's two files {L}")
f1 = L.get(F1, {}) if isinstance(L, dict) else {}
check(f1.get("name") == "Contract.pdf" and f1.get("mime") == "application/pdf" and f1.get("size") == len(PDF)
      and f1.get("page_id") == P1 and f1.get("created_at") and f1.get("url") == f"/api/v1/wiki/files/{F1}" and f1.get("image") is False,
      f"a file's fields {f1}")
check(L.get(F2, {}).get("image") is True if isinstance(L, dict) else False, "a picture: image true")
r = get(ta, F1)
check(r.status_code == 200 and r.content == PDF and r.headers.get("Content-Type", "").startswith("application/pdf"),
      f"the PDF's bytes ({r.status_code} {r.headers.get('Content-Type')})")
r = get(ta, F2)
check(r.status_code == 200 and r.content == PNG and r.headers.get("Content-Type", "").startswith("image/png"), "the picture's bytes")
t = text(ta, F1)
check(isinstance(t, dict) and t.get("kind") == "pdf" and t.get("id") == F1 and t.get("name") == "Contract.pdf", f"the PDF as text {t}")
t = text(ta, F2)
check(isinstance(t, dict) and t.get("kind") == "image", f"a picture as text: kind image {t}")
check(files(ta, P2) == 404 and get(ta, F3).status_code == 404 and text(ta, F3) == 404, "a page outside the shared folder: 404")
check(get(ta, 999999).status_code == 404, "an unknown file: 404")
acts = {x[0] for x in dbx("SELECT action FROM fs_log WHERE node_id=? AND agent=1", (node_of(P1),))}
check({"meta", "download", "text"} <= acts, f"the agent's reads are in the page node's history {acts}")

# ================================================================ another organisation (tenant-matrix: wiki_v1)
check(files(tb, P1) == 404 and get(tb, F1).status_code == 404 and text(tb, F1) == 404, "the other organisation's agent: 404")
ot = token(Ol)
check(files(ot, P1) == 404 and get(ot, F1).status_code == 404, "olga's token (other organisation): 404")
at = token(A)
check(isinstance(files(at, P2), dict) and get(at, F3).content == PDF, "alice's own token: the files of her organisation's page")

# ================================================================ the virus scan's lock: 403
dbx("INSERT INTO upload_scan(kind, ref_id, ver, org_id, state, sig, why, created_at) VALUES('wiki', ?, 0, ?, 'infected', 'Test-Signature', '', "
    "'2026-11-01T00:00:00Z') ON CONFLICT (kind, ref_id, ver) DO UPDATE SET state='infected', sig='Test-Signature'", (F2, ORG))
check(get(ta, F2).status_code == 403 and text(ta, F2) == 403, "a file found infected: 403")
L = files(ta, P1)
check(isinstance(L, dict) and L.get(F2, {}).get("up"), f"the list marks it (up) {L.get(F2) if isinstance(L, dict) else L}")

# ================================================================ trash: the file, the page
check(A.delete(B + f"/api/wiki/files/{F1}").ok, "setup: alice moves the PDF to the trash")
L = files(ta, P1)
check(get(ta, F1).status_code == 404 and isinstance(L, dict) and F1 not in L and F2 in L, "a file in the trash: 404, not listed")
check(A.post(B + "/api/wiki/restore", json={"ids": [], "files": [F1]}).ok and get(ta, F1).status_code == 200, "restored: readable again")
check(A.delete(B + f"/api/wiki/pages/{P1}").ok, "setup: the page to the trash")
check(files(ta, P1) == 404 and get(ta, F1).status_code == 404, "a page in the trash: its files 404")
check(A.post(B + "/api/wiki/restore", json={"ids": [P1]}).ok and get(ta, F1).status_code == 200, "the page restored: readable again")

# ================================================================ locked space: nothing (also not for its people)
dbx("INSERT INTO wiki_spaces(org_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (ORG,))
check(files(ta, P1) == 404 and get(ta, F1).status_code == 404 and text(ta, F1) == 404, "a locked space: the agent gets nothing")
check(files(at, P1) == 404 and get(at, F1).status_code == 404, "a locked space never comes through the API (also not for its people)")
dbx("DELETE FROM wiki_spaces WHERE org_id=?", (ORG,))
check(get(ta, F1).status_code == 200, "open again: the share counts again")

# ================================================================ a person without an organisation
# freelancer-matrix: wiki
FID, Fl = freelancer(B, A, features=FEATURES + ",wiki,files")
DA, da = agent("fridabot", owner=FID)
AA, aa = agent("alicebot", owner=ALICE)
Q1 = page(Fl, "Clients/Acme", space="private")
(G1,) = upload(Fl, Q1, ("Offer.pdf", PDF, "application/pdf"))
ft = token(Fl)
check(set(files(ft, Q1) if isinstance(files(ft, Q1), dict) else ()) == {G1} and get(ft, G1).content == PDF, "her token: her page's file")
check(files(da, Q1) == 404 and get(da, G1).status_code == 404, "her own agent without a share: 404")
fshare(Fl, folders(Fl, "private")["Clients"], agent_id=DA, role="view")
L, t = files(da, Q1), text(da, G1)
check(isinstance(L, dict) and set(L) == {G1} and get(da, G1).content == PDF and isinstance(t, dict) and t.get("kind") == "pdf",
      "her agent with the folder share: list, bytes, text")
check(files(aa, Q1) == 404 and get(aa, G1).status_code == 404 and text(aa, G1) == 404, "another person's agent: never")
check(get(ta, G1).status_code == 404, "an organisation's agent: never")

sys.exit(kt.done("p2488_wiki_files_v1"))
