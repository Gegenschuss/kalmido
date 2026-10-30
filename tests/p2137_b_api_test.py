#!/usr/bin/env python3
"""2.137.0 part B (#2344): the organisation import takes over the file store, documents, knowledge pages, tables and video
sign-offs of an organisation export. Invented names only.
 - an organisation with a folder tree, a file in two versions shared with a member, a document with sender / type / tag and
   a rule, a knowledge page with a picture and a link to the file, a table with a formula, a person cell and a file cell, a
   video sign-off with a comment on a list -> exported -> imported into another (empty) organisation: the tree, the contents,
   the versions, the share (ticked member only), the document's labels and the word index, the page with its picture and
   the rewritten links, the table's formula (same value), its person and file cells, the sign-off on the new list
 - the source organisation is not touched; undo removes every taken-over row of these areas again
 - a person without any organisation imports the same export into the private space: everything in their own space, readable
   for them, not for the organisation's admin
Starts its OWN container (start.sh) with KALMIDO_SECRET_KEY (P2137B_NOSTART=1 = the server already runs like that).
usage: p2137_b_api_test.py <datadir>"""
# freelancer-matrix: files
# freelancer-matrix: wiki
# freelancer-matrix: sheets
# freelancer-matrix: videos
# freelancer-matrix: own
# tenant-matrix: own
import base64
import hashlib
import json
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm
from freelancer_fixture import FEATURES, freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess, until, su_get  # 2.206.0 (#2762): shared helpers (tests/kt.py)
FEAT = FEATURES + ",sheets,videos"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def EH(email):
    return hashlib.sha256(("kalmido-people|" + email.strip().lower()).encode()).hexdigest()


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def upload(s, data, name="alpha.kalmido-export"):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": name})
    assert r.ok, r.text
    iid, off = r.json()["id"], 0
    while off < len(data):
        part = data[off:off + (1 << 20)]
        r = s.put(B + f"/api/account/import/{iid}?offset={off}", data=part, headers={"Content-Type": "application/octet-stream"})
        assert r.ok, r.text
        off += len(part)
    return iid


def wait(s, iid, secs=240):
    j = {}
    for _ in range(secs * 4):
        j = s.get(B + f"/api/account/import/{iid}").json()
        if j.get("state") not in ("checking", "running", "upload"):
            return j
        time.sleep(0.25)
    return j


def opened(s, data, rk):
    """Upload + recovery key -> (import id, preview)."""
    iid = upload(s, data)
    j = wait(s, iid)
    check(j.get("state") == "key", f"asks for the recovery key {j.get('state')} {j.get('error')}")
    check(s.post(B + f"/api/account/import/{iid}/key", json={"recovery_key": rk}).status_code == 202, "the recovery key is taken")
    j = wait(s, iid)
    check(j.get("state") == "preview", f"opened {j.get('state')} {j.get('error')}")
    return iid, j.get("preview") or {}


def run(s, iid, target, people=None):
    # 2.269.0 (#3046): "again" = the person saw the preview's warning (a second import of one export is 409 without it)
    r = s.post(B + f"/api/account/import/{iid}/run", json={"again": True, "target": target, "people": people or {}})
    check(r.status_code == 202, f"run starts {r.status_code} {r.text[:200]}")
    return wait(s, iid)


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0] if r else None


if not os.environ.get("P2137B_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY={KEY} -e KALMIDO_ORGCRYPT_DELAY=0")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Ablage", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
A.patch(B + f"/api/users/{ALICE}", json={"email": "alice@example.com"})
ids = {}
for u, n in (("bob", "Bob Mitglied"), ("dora", "Dora Mitglied")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Do = sess("bob"), sess("dora")
for s in (A, Bo, Do):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Ablage", "admin_id": ALICE}).json()["id"]
GAM = A.post(B + "/api/admin/orgs", json={"name": "Gamma Ziel", "admin_id": ALICE}).json()["id"]
for u in ("bob", "dora"):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
    assert A.put(B + f"/api/orgs/{GAM}/members", json={"email": f"{u}@example.com", "role": "member"}).ok
SP = f"org:{ORG}"
dbx("INSERT INTO settings(key, value) VALUES('wiki_encrypt', '1') ON CONFLICT (key) DO UPDATE SET value='1'")  # page texts sealed at rest

# ---------------------------------------------------------------- the organisation's data
LO = A.post(B + "/api/lists", json={"name": "Alpha Projekt", "org_id": ORG}).json()["id"]
r = A.post(B + "/api/files/folders", json={"name": "Projekte", "space": SP})
check(r.status_code == 201, "a folder " + r.text[:160])
P1 = r.json()["id"]
P2 = A.post(B + "/api/files/folders", json={"name": "Unterordner", "parent_id": P1}).json()["id"]
V1, V2 = b"Plan Fassung eins " + os.urandom(6).hex().encode(), b"Plan Fassung zwei " + os.urandom(6).hex().encode()
r = A.post(B + "/api/files/upload", data={"parent_id": str(P2)}, files={"file": ("plan.txt", V1, "text/plain")})
check(r.status_code == 201, "a file " + r.text[:160])
F1 = r.json()["items"][0]["id"]
check(A.post(B + f"/api/files/nodes/{F1}/versions", files={"file": ("plan.txt", V2, "text/plain")}).ok, "a second version")
check(A.post(B + f"/api/files/nodes/{P1}/shares", json={"user_id": ids["bob"], "role": "view"}).ok, "the folder shared with bob")
check(A.post(B + f"/api/files/nodes/{P1}/shares", json={"user_id": ids["dora"], "role": "edit"}).ok, "the folder shared with dora")
r = A.post(B + "/api/docs", data={"ws": SP}, files=[("files", ("rechnung.txt", b"Rechnung Beispielfirma Kalibrierung 42 EUR", "text/plain"))])
check(r.status_code == 201, "a document " + r.text[:160])
D1 = r.json()["ids"][0]
until(lambda: A.get(B + f"/api/docs/{D1}").json().get("state") in ("done", "failed"), 120)
r = A.patch(B + f"/api/docs/{D1}", json={"sender": "Muster Werkstatt", "type": "Rechnung", "tags": ["Steuer"]})
check(r.ok, "the document's sender, type and tag " + r.text[:160])
r = A.post(B + "/api/docs/rules", json={"ws": SP, "kind": "any", "match": "Kalibrierung", "type": "Rechnung"})
check(r.ok, "a document rule " + r.text[:160])
r = A.post(B + "/api/wiki/pages", json={"space": SP, "path": "Prozesse/Ablauf", "body": "Erster Text"})
check(r.ok, "a knowledge page " + r.text[:160])
WP = r.json().get("id") or (r.json().get("page") or {}).get("id")
r = A.post(B + f"/api/wiki/pages/{WP}/files", files={"file": ("bild.png", PNG, "image/png")})
check(r.ok, "a picture on the page " + r.text[:160])
WF = (r.json().get("files") or [{}])[0].get("id")
BODY = f"Ablauf mit Bild ![bild](/api/wiki/files/{WF}/bild.png) und Plan [[datei:{F1}]]"
r = A.patch(B + f"/api/wiki/pages/{WP}", json={"body": BODY})
check(r.ok, "the page links its picture and the file " + r.text[:160])
r = A.post(B + "/api/sheets", json={"title": "Kalkulation", "space": SP})
check(r.status_code == 201, "a table " + r.text[:160])
SH = r.json()
SID, C0, C1 = SH["id"], SH["columns"][0]["id"], SH["columns"][1]["id"]
R0, R1 = SH["rows"][0]["id"], SH["rows"][1]["id"]
CP = A.post(B + f"/api/sheets/{SID}/columns", json={"title": "Person", "kind": "person"}).json()["column"]["id"]
CF = A.post(B + f"/api/sheets/{SID}/columns", json={"title": "Datei", "kind": "file"}).json()["column"]["id"]
r = A.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"row_id": R0, "col_id": C0, "raw": "5"}, {"row_id": R1, "col_id": C0, "raw": "=A1*2"},
                                                         {"row_id": R0, "col_id": C1, "raw": "Wert"},
                                                         {"row_id": R0, "col_id": CP, "raw": str(ids["bob"])}]})
check(r.ok, "cells with a formula and a person " + r.text[:160])
r = A.post(B + f"/api/sheets/{SID}/files", data={"row_id": str(R0), "col_id": str(CF)}, files={"file": ("anhang.pdf", PDF, "application/pdf")})
check(r.ok, "a file cell " + r.text[:160])
r = A.post(B + "/api/videos", json={"title": "Schnitt eins", "url": "https://vimeo.com/123456789", "list_id": LO})
check(r.ok, "a video sign-off " + r.text[:160])
VID = r.json()["id"]
check(A.post(B + f"/api/videos/{VID}/comments", json={"body": "Bei Sekunde zwoelf heller", "at_sec": 12}).ok, "a comment at a time code")

src_counts = {t: dbx(f"SELECT COUNT(*) AS n FROM {t} WHERE org_id=?", (ORG,))[0]["n"]
              for t in ("fs_nodes", "doc_meta", "wiki_pages", "wiki_files", "sheets", "sheet_files", "video_reviews", "video_comments")}
check(src_counts["fs_nodes"] >= 4 and src_counts["doc_meta"] == 1, f"the source has its data {src_counts}")

# ---------------------------------------------------------------- export
r = A.post(B + f"/api/orgs/{ORG}/export")
check(r.status_code == 202, "organisation export started " + r.text[:120])
for _ in range(480):
    if A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running":
        break
    time.sleep(0.25)
OX = su_get(A, B + f"/api/orgs/{ORG}/export/file").content  # 2.360.0 (#2496): the step-up
RK = A.post(B + f"/api/orgs/{ORG}/encryption/recovery", json={"password": "password123"}).json().get("recovery_key", "")
check(OX[:13] == b"KALMIDO-ORGX\n" and RK, "organisation export + recovery key")

# ---------------------------------------------------------------- into the other organisation (bob ticked, dora not)
iid, pv = opened(A, OX, RK)
taken = {x.get("what") for x in pv.get("taken_areas") or []}
check({"File store", "Documents", "Knowledge pages", "Tables", "Video sign-offs"} <= taken, f"the preview names the areas {taken}")
nt = " ".join(str(x) for x in pv.get("not_taken") or [])
check(not any(w in nt for w in ("File store", "Knowledge pages", "Tables", "Video sign-offs")), f"not named as skipped {nt}")
j = run(A, iid, GAM, people={EH("bob@example.com"): {"share": True}})
check(j.get("state") == "done", f"import done {j.get('state')} {j.get('error')} {(j.get('result') or {}).get('warnings')}")
IMP = (j.get("result") or {}).get("import_id")

n1 = one("SELECT id, parent_id FROM fs_nodes WHERE org_id=? AND name='Projekte' AND kind='folder'", (GAM,))
n2 = one("SELECT id, parent_id FROM fs_nodes WHERE org_id=? AND name='Unterordner'", (GAM,))
nf = one("SELECT id, parent_id, cur_version FROM fs_nodes WHERE org_id=? AND name='plan.txt'", (GAM,))
check(n1 and n1["parent_id"] is None and n2 and n2["parent_id"] == n1["id"] and nf and nf["parent_id"] == n2["id"],
      "the folder tree is rebuilt")
NF = nf["id"] if nf else 0
check(dbx("SELECT COUNT(*) AS n FROM fs_versions WHERE node_id=?", (NF,))[0]["n"] == 2 and nf["cur_version"] == 2, "both versions came along")
check(A.get(B + f"/api/files/nodes/{NF}/content").content == V2, "the current version is readable")
vp = dbx("SELECT path FROM fs_versions WHERE node_id=? ORDER BY no", (NF,))
check(len(vp) == 2 and all(str(NF) in x["path"] for x in vp), "the versions are new stored files")
sh = {x["user_id"] for x in dbx("SELECT user_id FROM fs_shares WHERE node_id=?", (n1["id"] if n1 else 0,))}
check(sh == {ids["bob"]}, f"the share of the ticked member only {sh}")
check(Bo.get(B + f"/api/files/nodes/{NF}/content").content == V2, "bob reads the file through the share")
# documents
dm = one("SELECT n.id, d.ws FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE n.org_id=?", (GAM,))
check(dm and dm["ws"] == f"o{GAM}", f"the document is in the target's workspace {dict(dm) if dm else None}")
ND = dm["id"] if dm else 0
d = A.get(B + f"/api/docs/{ND}").json()
check((d.get("sender") or {}).get("name") == "Muster Werkstatt" and (d.get("type") or {}).get("name") == "Rechnung"
      and [t["name"] for t in d.get("tags") or []] == ["Steuer"], f"sender, type and tag of the document {d.get('sender')} {d.get('type')} {d.get('tags')}")
check("Kalibrierung" in str(d.get("text") or ""), "the recognised text is readable")
r = A.get(B + "/api/docs", params={"ws": f"org:{GAM}", "q": "Kalibrierung"})
check(r.ok and ND in [x.get("id") for x in r.json().get("items") or r.json().get("docs") or []], f"the word index finds it {r.text[:200]}")
check(dbx("SELECT COUNT(*) AS n FROM doc_rules WHERE ws=?", (f"o{GAM}",))[0]["n"] == 1, "the rule came along")
lbl = dbx("SELECT COUNT(*) AS n FROM doc_types WHERE ws=? AND name='Rechnung'", (f"o{GAM}",))[0]["n"]
check(lbl == 1, f"the type exists once in the target {lbl}")
# knowledge pages
pg = one("SELECT id FROM wiki_pages WHERE org_id=? AND path='Prozesse/Ablauf'", (GAM,))
NP = pg["id"] if pg else 0
wf = one("SELECT id FROM wiki_files WHERE page_id=?", (NP,))
NWF = wf["id"] if wf else 0
b = A.get(B + f"/api/wiki/pages/{NP}").json()
body = b.get("body") or (b.get("page") or {}).get("body") or ""
check(f"/api/wiki/files/{NWF}/bild.png" in body and f"[[datei:{NF}]]" in body, f"the page links the new picture and file {body}")
check(A.get(B + f"/api/wiki/files/{NWF}").content == PNG, "the picture is readable")
check(dbx("SELECT body FROM wiki_pages WHERE id=?", (NP,))[0]["body"].startswith("kenc1:"), "the page text is sealed at rest")
nv, sv = (dbx("SELECT COUNT(*) AS n FROM wiki_versions WHERE page_id=?", (x,))[0]["n"] for x in (NP, WP))
check(nv == sv and sv >= 1, f"the page history came along {nv} {sv}")
# tables
ts = one("SELECT id FROM sheets WHERE org_id=? AND title='Kalkulation'", (GAM,))
NS = ts["id"] if ts else 0
g = A.get(B + f"/api/sheets/{NS}").json()
cells = {x["addr"]: x for x in g.get("cells") or []}
check(cells.get("A2", {}).get("raw") == "=A1*2" and str(cells.get("A2", {}).get("value")) in ("10", "10.0"), f"the formula works {cells.get('A2')}")
own = {r_["id"] for r_ in dbx("SELECT id FROM sheet_cells WHERE sheet_id=?", (NS,))}
fr = one("SELECT raw FROM sheet_cells WHERE sheet_id=? AND raw LIKE '={c:%'", (NS,))
check(fr and int(fr["raw"].split(":")[1].split("}")[0]) in own, f"the formula points at the new cell {fr['raw'] if fr else None}")
pc = one("SELECT c.raw FROM sheet_cells c JOIN sheet_columns k ON k.id=c.col_id WHERE c.sheet_id=? AND k.kind='person'", (NS,))
check(pc and pc["raw"] == str(ids["bob"]), "the person cell keeps the ticked member")
fc = one("SELECT c.raw FROM sheet_cells c JOIN sheet_columns k ON k.id=c.col_id WHERE c.sheet_id=? AND k.kind='file'", (NS,))
sf = one("SELECT id FROM sheet_files WHERE sheet_id=?", (NS,))
check(fc and sf and fc["raw"] == f"file:{sf['id']}", f"the file cell points at the new file {fc['raw'] if fc else None}")
check(sf and A.get(B + f"/api/sheets/{NS}/files/{sf['id']}").content == PDF, "the file of the cell is readable")
# video sign-offs
nl = one("SELECT id FROM lists WHERE org_id=? AND name='Alpha Projekt'", (GAM,))
vr = one("SELECT id, list_id FROM video_reviews WHERE org_id=?", (GAM,))
check(vr and nl and vr["list_id"] == nl["id"], "the sign-off hangs on the new list")
vc = dbx("SELECT body, at_sec, version_id FROM video_comments WHERE review_id=?", (vr["id"] if vr else 0,))
check(len(vc) == 1 and vc[0]["at_sec"] == 12 and vc[0]["version_id"], "the comment with its time code and version")
check(A.get(B + f"/api/videos/{vr['id'] if vr else 0}").ok, "the sign-off opens")
# the source is untouched
after = {t: dbx(f"SELECT COUNT(*) AS n FROM {t} WHERE org_id=?", (ORG,))[0]["n"] for t in src_counts}
check(after == src_counts, f"the rows of the source organisation are not touched {after}")
check(A.get(B + f"/api/files/nodes/{F1}/content").content == V2, "the source file is as it was")

# ---------------------------------------------------------------- undo
# 2.137.1 (#2399): the document settings came along (their documents folder mapped) and the undo removes them again
gc = one("SELECT data FROM doc_cfg WHERE ws=?", (f"o{GAM}",))
groot = json.loads(gc["data"]).get("root_id") if gc else None
check(gc and groot and one("SELECT 1 FROM fs_nodes WHERE id=? AND org_id=?", (groot, GAM)),
      f"the document settings came along with the new documents folder {gc}")
r = A.post(B + f"/api/imports/{IMP}/undo")
check(r.ok, "undo " + r.text[:160])
check(not dbx("SELECT 1 FROM doc_cfg WHERE ws=?", (f"o{GAM}",)), "2.137.1 (#2399): undo removes the document settings it made")
check(dbx("SELECT 1 FROM doc_cfg WHERE ws=?", (f"o{ORG}",)), "the source's document settings stay")
# 2.352.0 A (#2748): a list is a node of the file store (below the area root "Projects"); the undo puts the lists into the
# trash (2.272.0 C, restorable), their nodes stay with them
LFN = "(ref_kind='list' OR id IN (SELECT node_id FROM fs_area_roots WHERE area='lists' AND node_id IS NOT NULL))"
left = {t: dbx(f"SELECT COUNT(*) AS n FROM {t} WHERE org_id=?" + (f" AND NOT {LFN}" if t == "fs_nodes" else ""), (GAM,))[0]["n"]
        for t in ("fs_nodes", "doc_meta", "doc_senders", "doc_types", "doc_tags", "doc_rules", "wiki_pages", "wiki_files", "wiki_versions", "sheets",
                  "sheet_files", "video_reviews", "video_versions", "video_comments")}
check(not any(left.values()), f"undo removes every taken-over row {left} "
      f"{[dict(r) for r in dbx('SELECT id, kind, name, parent_id, ref_kind, deleted_at FROM fs_nodes WHERE org_id=?', (GAM,))] if left.get('fs_nodes') else ''}")
check(not dbx("SELECT 1 FROM fs_versions WHERE node_id=?", (NF,)), "and the versions")
A.delete(B + f"/api/account/import/{iid}")

# ---------------------------------------------------------------- a person without an organisation imports it privately
FID, Fr = freelancer(B, A)
Fr.patch(B + "/api/settings", json={"features": FEAT})
iid, pv = opened(Fr, OX, RK)
check(not dbx("SELECT 1 FROM doc_cfg WHERE ws=?", (f"u{FID}",)), "freelancer: no document settings before the import")
j = run(Fr, iid, "private")
check(j.get("state") == "done", f"freelancer: import done {j.get('error')}")
fn = one("SELECT id, org_id FROM fs_nodes WHERE owner_id=? AND name='plan.txt'", (FID,))
check(fn and fn["org_id"] is None, "freelancer: the file is in the private file store")
FN = fn["id"] if fn else 0
check(Fr.get(B + f"/api/files/nodes/{FN}/content").content == V2, "freelancer: the file is readable")
check(A.get(B + f"/api/files/nodes/{FN}/content").status_code in (403, 404), "alice cannot read the freelancer's file")
check(not dbx("SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.owner_id=?", (FID,)), "freelancer: shared with nobody")
fd = one("SELECT d.node_id, d.ws FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE n.owner_id=?", (FID,))
check(fd and fd["ws"] == f"u{FID}", "freelancer: the document is in the private workspace")
d = Fr.get(B + f"/api/docs/{fd['node_id'] if fd else 0}").json()
check((d.get("sender") or {}).get("name") == "Muster Werkstatt" and "Kalibrierung" in str(d.get("text") or ""), "freelancer: the document opens")
fp = one("SELECT id, org_id, owner_id FROM wiki_pages WHERE owner_id=? AND path='Prozesse/Ablauf'", (FID,))
check(fp and fp["org_id"] is None, "freelancer: the page is private")
b = Fr.get(B + f"/api/wiki/pages/{fp['id'] if fp else 0}").json()
check("Ablauf mit Bild" in str(b.get("body") or (b.get("page") or {}).get("body") or ""), "freelancer: the page text opens")
fs_ = one("SELECT id, org_id FROM sheets WHERE owner_id=? AND title='Kalkulation'", (FID,))
check(fs_ and fs_["org_id"] is None, "freelancer: the table is private")
g = Fr.get(B + f"/api/sheets/{fs_['id'] if fs_ else 0}").json()
cells = {x["addr"]: x for x in g.get("cells") or []}
check(str(cells.get("A2", {}).get("value")) in ("10", "10.0"), "freelancer: the formula works")
pc = one("SELECT c.raw FROM sheet_cells c JOIN sheet_columns k ON k.id=c.col_id WHERE c.sheet_id=? AND k.kind='person'", (fs_["id"] if fs_ else 0,))
check(pc is None or pc["raw"] == "", "freelancer: a person not ticked is left out of the person cell")
fv = one("SELECT id, org_id, owner_id FROM video_reviews WHERE owner_id=?", (FID,))
check(fv and fv["org_id"] is None, "freelancer: the sign-off is private")
check(not dbx("SELECT 1 FROM org_members WHERE user_id=?", (FID,)), "freelancer: still in no organisation")
r = Fr.post(B + f"/api/imports/{(j.get('result') or {}).get('import_id')}/undo")
check(r.ok and not dbx(f"SELECT 1 FROM fs_nodes WHERE owner_id=? AND NOT {LFN}", (FID,)) and not dbx("SELECT 1 FROM sheets WHERE owner_id=?", (FID,)),
      "freelancer: undo removes it again")
check(not dbx("SELECT 1 FROM doc_cfg WHERE ws=?", (f"u{FID}",)), "2.137.1 (#2399): freelancer: undo removes the private document settings")

if FAILS:  # the container log once (was in the suite's own check(), 2.206.0 #2762)
    ct = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
    print(subprocess.run(["docker", "logs", "--tail", "80", ct], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True).stdout[-8000:], flush=True)
print(f"p2137_b: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
