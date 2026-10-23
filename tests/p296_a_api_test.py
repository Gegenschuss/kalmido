#!/usr/bin/env python3
"""2.96.0 API tests, part A (#1941): files, folders and documents to the other workspace (private <-> organisation),
POST /api/files/move-space. Invented names only, generated file contents.
 - private -> organisation and back: a folder with a subfolder and a file, a document with sender / type / tag and a
   Paperless origin: readable in the target, the same content, sealed with the target's key, the labels in the target's
   workspace, the search finds it there; the undo (items back to the old folder under the old name)
 - the dry run changes nothing; a taken name in the target folder -> "Name (2)"; "docs" = the target's documents folder
 - rights: a plain member does not pull someone else's organisation file into the private space (403, the dry run blocks),
   the admin may; another organisation 409; someone else's file 404; an agent's token gets nothing
 - a share with an organisation colleague ends on the way into the private space
 - a person without an organisation (freelancer fixture): 409, there is no other workspace
tenant-matrix: file
freelancer-matrix: files
usage: p296_a_api_test.py <datadir>      (a fresh container; P296A_NOSTART=1: the container runs already)"""
import base64
import os
import struct
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402; 2.148.1 (#2480): an invited member accepts

from kt import FAILS, OKS, check, sess, until, B, H, DATA  # 2.206.0 (#2762): shared helpers (tests/kt.py)
KEY = base64.b64encode(os.urandom(32)).decode()
MAGIC = b"KENC1\n"


def dbx(sql, args=()):
    c = dbxm.connect(DATA)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def space_of(nid):
    """The space id in the header of the current version's stored file (> 0 organisation, < 0 an account), None = plain."""
    rel = one("SELECT v.path FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id AND v.no=n.cur_version WHERE n.id=?", (nid,))
    with open(os.path.join(DATA, "attachments", rel), "rb") as f:
        h = f.read(14)
    return struct.unpack(">q", h[6:14])[0] if h[:6] == MAGIC else None


def folder(s, name, parent=None, space=None):
    b = {"name": name, **({"parent_id": parent} if parent else {}), **({"space": space} if space else {})}
    r = s.post(B + "/api/files/folders", json=b)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(s, name, data, parent=None, space=None):
    form = {"parent_id": str(parent)} if parent else {"space": space or "private"}
    r = s.post(B + "/api/files/upload", data=form, files={"file": (name, data)})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def move(s, body):
    return s.post(B + "/api/files/move-space", json=body)


def node(nid):
    r = dbx("SELECT * FROM fs_nodes WHERE id=?", (nid,))
    return dict(r[0]) if r else None


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


# ---- setup: alice (instance admin), Alpha = bob (admin) + carol, Beta = dave; the server key on (sealed files)
if not os.environ.get("P296A_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_SECRET_KEY=" + KEY + " -e KALMIDO_ORGCRYPT_DELAY=0")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
ORG2 = r.json()["id"]
Bo = sess("bob")
check((Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG)), "setup: carol joins Alpha")
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id NOT IN (?))", (ORG, BOB, CAROL, ORG2, DAVE))
r = A.post(B + "/api/admin/agents", json={"username": "alphabot", "display_name": "Alphabot"})
assert r.status_code == 201, r.text
AGT = r.json().get("token") or ""
dbx("UPDATE agents SET org_id=?, owner_id=? WHERE user_id=?", (ORG, BOB, r.json()["id"]))
Bo.post(B + "/api/auth/logout")
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ---- carol's private things: Projekt / Unter / notiz.txt, a document with sender, type, tag and a Paperless origin
PROJ = folder(Ca, "Projekt")
SUB = folder(Ca, "Unter", parent=PROJ)
NOTE_TXT = b"Gruene Notiz 4711 " + os.urandom(8).hex().encode()
NOTE = upload(Ca, "notiz.txt", NOTE_TXT, parent=SUB)
check(space_of(NOTE) == -CAROL, f"before: the private file is sealed with carol's account key ({space_of(NOTE)})")
PDF = tiny_pdf("Sonnenblume Rechnung 2026")
r = Ca.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("rechnung.pdf", PDF, "application/pdf"))])
check(r.status_code in (200, 201), f"document uploaded ({r.status_code} {r.text[:200]})")
DOC = (r.json().get("ids") or [None])[0]
d = until(lambda: (lambda x: x.json() if x.ok and x.json()["state"] in ("done", "failed") else None)(Ca.get(B + f"/api/docs/{DOC}")), 90)
check(d and d["state"] == "done", f"document recognised ({d and d['state']})")
r = Ca.patch(B + f"/api/docs/{DOC}", json={"sender": "Gaertnerei Beispiel", "type": "Rechnung", "tags": ["Garten"]})
check(r.ok, f"document labels set ({r.status_code})")
dbx("INSERT INTO pl_imported(ws,src,pl_id,org_id,node_id,sha256,asn,dup,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
    (f"u{CAROL}", "abc123", 77, None, DOC, "", None, 0, "2026-10-18T10:00:00Z"))
# Alpha has a "Projekt" already -> carol's arrives as "Projekt (2)"
TAKEN = folder(Bo, "Projekt", space=f"org:{ORG}")

# ---- the dry run: notes, no block, nothing changed
r = move(Ca, {"ids": [PROJ, DOC], "to": f"org:{ORG}", "parent": None, "dry": 1})
j = r.json() if r.ok else {}
check(r.ok and j.get("block") is None and j.get("notes") and j.get("files") == 2 and j.get("folders") == 2,
      f"dry run: 2 files, 2 folders, no block ({r.status_code} {j})")
check(node(PROJ)["org_id"] is None and node(NOTE)["org_id"] is None and space_of(NOTE) == -CAROL, "the dry run changed nothing")

# ---- private -> Alpha
r = move(Ca, {"ids": [PROJ, DOC], "to": f"org:{ORG}", "parent": None})
check(r.ok, f"moved into Alpha ({r.status_code} {r.text[:300]})")
MOVED = r.json().get("moved") if r.ok else []
check(sorted(x["id"] for x in MOVED) == sorted([PROJ, DOC]) and all(x["org_was"] is None for x in MOVED), f"the answer names the roots ({MOVED})")
check(all(node(x)["org_id"] == ORG for x in (PROJ, SUB, NOTE, DOC)), "the whole branch is in Alpha")
check(node(PROJ)["name"] == "Projekt (2)", f"a taken name -> 'Projekt (2)' ({node(PROJ)['name']})")
check(space_of(NOTE) == ORG and space_of(DOC) == ORG, f"sealed again with Alpha's key ({space_of(NOTE)}, {space_of(DOC)})")
check(Ca.get(B + f"/api/files/nodes/{NOTE}/content").content == NOTE_TXT, "carol reads the same content")
check(Bo.get(B + f"/api/files/nodes/{NOTE}/content").content == NOTE_TXT, "bob (admin of Alpha) reads it")
check(Bo.get(B + f"/api/files/nodes/{DOC}/content").content == PDF, "the document's file is the same")
d = Ca.get(B + f"/api/docs/{DOC}").json()
check(d.get("ws") == f"o{ORG}" and (d.get("sender") or {}).get("name") == "Gaertnerei Beispiel" and (d.get("type") or {}).get("name") == "Rechnung"
      and [t["name"] for t in d.get("tags") or []] == ["Garten"], f"the document's labels in Alpha's workspace ({d.get('ws')}, {d.get('sender')}, {d.get('tags')})")
check(one("SELECT ws FROM doc_senders WHERE id=?", (d["sender"]["id"],)) == f"o{ORG}", "the sender row belongs to Alpha")
hits = [x["id"] for x in Ca.get(B + "/api/docs", params={"ws": f"org:{ORG}", "q": "sonnenblume", "facets": "0"}).json()["docs"]]
check(DOC in hits, f"the search finds it in Alpha ({hits})")
check([x["id"] for x in Ca.get(B + "/api/docs", params={"ws": "private", "q": "sonnenblume", "facets": "0"}).json()["docs"]] == [],
      "and no longer in the private space")
check(one("SELECT node_id FROM pl_imported WHERE ws=? AND pl_id=77", (f"o{ORG}",)) == DOC and
      one("SELECT COUNT(*) FROM pl_imported WHERE ws=? AND pl_id=77 AND node_id IS NULL", (f"u{CAROL}",)) == 1,
      "the Paperless origin goes along, the source keeps it without the node (no second import)")
log = Ca.get(B + f"/api/files/nodes/{PROJ}").json().get("log") or []
check(any(x["action"] == "moved_space" for x in log), f"the history names the move ({[x['action'] for x in log]})")

# ---- the undo: the same route back (old folder, old name)
# 2.148.1 (#2483): out of an organisation only through its admin -- carol (a member) is refused, as an admin she may
undo_items = [{"id": x["id"], "parent": x["parent_was"], "name": x["name_was"]} for x in MOVED]
check(move(Ca, {"items": undo_items, "to": "private"}).status_code == 403, "#2483: a member does not move files out of Alpha (403)")
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (ORG, CAROL))
r = move(Ca, {"items": undo_items, "to": "private"})
check(r.ok, f"undo: back into the private space ({r.status_code} {r.text[:300]})")
check(node(PROJ)["org_id"] is None and node(PROJ)["name"] == "Projekt" and node(NOTE)["org_id"] is None, "undo: the old place and name")
check(space_of(NOTE) == -CAROL and Ca.get(B + f"/api/files/nodes/{NOTE}/content").content == NOTE_TXT, "undo: carol's key, the same content")
check(Bo.get(B + f"/api/files/nodes/{NOTE}").status_code == 404, "undo: bob no longer sees it")
d = Ca.get(B + f"/api/docs/{DOC}").json()
check(d.get("ws") == f"u{CAROL}" and (d.get("sender") or {}).get("name") == "Gaertnerei Beispiel", f"undo: the document in the private workspace ({d.get('ws')})")
check(one("SELECT node_id FROM pl_imported WHERE ws=? AND pl_id=77", (f"u{CAROL}",)) == DOC, "undo: the Paperless origin is back")

# ---- "docs": into the target's documents folder (made when missing), the member stays its owner
r = move(Ca, {"ids": [DOC], "to": f"org:{ORG}", "parent": "docs"})
check(r.ok, f"a document into Alpha's documents folder ({r.status_code} {r.text[:200]})")
p = node(node(DOC)["parent_id"]) if r.ok else {}
check(p and p["parent_id"] is None and p["org_id"] == ORG and node(DOC)["owner_id"] == CAROL, f"in Alpha's documents folder, carol owns it ({p})")
check(Ca.get(B + f"/api/docs/{DOC}").ok, "carol still opens her document")
r = move(Ca, {"ids": [DOC], "to": "private", "parent": "docs"})
check(r.ok and node(DOC)["org_id"] is None, f"and back into her own documents folder ({r.status_code})")

# ---- rights
dbx("UPDATE org_members SET role='member' WHERE org_id=? AND user_id=?", (ORG, CAROL))  # 2.148.1 (#2483): a member again
PLAN = upload(Bo, "plan.txt", b"Plan von Bob", space=f"org:{ORG}")
check(Bo.patch(B + f"/api/files/nodes/{PLAN}", json={"org_access": "edit"}).ok, "setup: bob opens his file to Alpha (edit)")
r = move(Ca, {"ids": [PLAN], "to": "private", "dry": 1})
check(r.ok and r.json().get("block"), f"dry run: a member may not pull bob's file out of Alpha ({r.status_code} {r.text[:200]})")
r = move(Ca, {"ids": [PLAN], "to": "private"})
check(r.status_code == 403 and node(PLAN)["org_id"] == ORG, f"a member pulling someone else's Alpha file into the private space: 403 ({r.status_code})")
r = move(Ca, {"ids": [NOTE], "to": f"org:{ORG2}"})
check(r.status_code == 409, f"into an organisation carol is not in: 409 ({r.status_code})")
r = move(Da, {"ids": [NOTE], "to": f"org:{ORG2}"})
check(r.status_code == 404 and node(NOTE)["org_id"] is None, f"someone else's file: 404 ({r.status_code})")
r = move(Ca, {"ids": [NOTE], "to": "private"})
check(r.status_code == 409, f"the same workspace: 409 ({r.status_code})")
ag = requests.post(B + "/api/files/move-space", json={"ids": [PLAN], "to": "private"}, headers={"Authorization": "Bearer " + AGT, **H})
check(ag.status_code in (401, 403) and node(PLAN)["org_id"] == ORG, f"an agent's token moves nothing ({ag.status_code})")
r = move(Bo, {"ids": [PLAN], "to": "private"})
check(r.ok and node(PLAN)["org_id"] is None and node(PLAN)["owner_id"] == BOB and node(PLAN)["org_access"] == "",
      f"the admin may take it into his private space; the opening to Alpha ends ({r.status_code})")

# ---- a share with an organisation colleague ends on the way into the private space
SH = folder(Ca, "Geteilt", space=f"org:{ORG}")
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (ORG, CAROL))  # 2.148.1 (#2483): only an admin moves it out
r = Ca.post(B + f"/api/files/nodes/{SH}/shares", json={"user_id": BOB, "role": "view"})
check(r.status_code == 201, f"setup: carol shares her Alpha folder with bob ({r.status_code} {r.text[:200]})")
r = move(Ca, {"ids": [SH], "to": "private", "dry": 1})
check(r.ok and r.json().get("shares") == 1, f"dry run: 1 share ends ({r.text[:200]})")
r = move(Ca, {"ids": [SH], "to": "private"})
check(r.ok and one("SELECT COUNT(*) FROM fs_shares WHERE node_id=?", (SH,)) == 0, f"the share with bob ended ({r.status_code})")
check(Bo.get(B + f"/api/files/nodes/{SH}").status_code == 404, "bob no longer sees the folder")

# ---- a person without an organisation: there is no other workspace
FID, Fr = freelancer(B, A)
FN = upload(Fr, "eigen.txt", b"Freiberuflich")
r = move(Fr, {"ids": [FN], "to": f"org:{ORG}"})
check(r.status_code == 409, f"freelancer into an organisation: 409 ({r.status_code})")
r = move(Fr, {"ids": [FN], "to": "private", "dry": 1})
check(r.status_code == 409, f"freelancer: the private space is the only one, 409 ({r.status_code})")

print(f"p296_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
