#!/usr/bin/env python3
"""2.96.0 API tests, part E (#1941): the separation when data moves between the private space and an organisation, and the
target learning a moved document at once. Invented names only, generated file contents. After a move the old workspace
sees nothing of it any more (no lists, searches, filters, links, shares, agents), the files and their history moved along.
 - files / documents, organisation -> private: a folder with a file (shared with a colleague, opened to an agent) and a
   document with sender / type / tag, recognised text, a receipt project and an agent's suggestion: the colleague and the
   agent get 404 on node, content, preview, text; file list, documents list, both searches and the filters of the old
   workspace no longer show it; no row of it is left with the old workspace (doc_meta, labels, doc_node_tags, file_text,
   rc_*, upload_scan), the word index is new (keyed for the new workspace), every stored version is sealed for the new
   space and no old stored file is left; the history (fs_log) reads in the target
 - files / documents, private -> organisation: a share with someone of another organisation ends (only members of the
   target keep theirs), that other organisation sees nothing, the private searches no longer find it
 - knowledge pages (a folder with a sub-page and links) both ways: list, search, backlinks of the old workspace, wiki_links
   only as the reported text links, the move history (space_moves) only for who sees the page
 - a table bound to a list of the organisation with a carried-over row: detached, the carry-over ended, the old workspace
   neither lists nor opens it
 - a list with a task, a comment and a file (open to everyone in the organisation, a group, an agent): an agent of the
   organisation blocks the move (409); after the move into the private space nobody of the organisation (and the agent)
   sees list, task, comment, file or the link to the file in the organisation's file store; the file is sealed for the
   private space (after the settle pass) and its recognised text belongs to the private workspace; a private list shared
   with someone of another organisation does not go into an organisation (409)
 - learning: the source's models forget a moved document, the target's models know it at once (doc_meta.trained)
tenant-matrix: file
freelancer-matrix: files
usage: p296_e_api_test.py <datadir>      (a fresh container; P296E_NOSTART=1: the container runs already)"""
import base64
import json
import os
import struct
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402; 2.148.1 (#2480): an invited member accepts

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
MAGIC = b"KENC1\n"
FEAT = FEATURES + ",sheets"
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


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


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def head_space(rel):
    """The space id in the header of a stored file (> 0 organisation, < 0 an account), None = plain."""
    with open(os.path.join(DATA, "attachments", rel), "rb") as f:
        h = f.read(14)
    return struct.unpack(">q", h[6:14])[0] if h[:6] == MAGIC else None


def versions(nid):
    return [r[0] for r in dbx("SELECT path FROM fs_versions WHERE node_id=? ORDER BY no", (nid,))]


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


def text_pdf(lines):
    """A one-page PDF with a text layer (hand-written, no library)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 12 Tf 60 740 Td 16 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET").encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def doc_up(s, name, lines, ws="private"):
    r = s.post(B + "/api/docs", data={"ws": ws}, files=[("files", (name, text_pdf(lines), "application/pdf"))])
    assert r.status_code in (200, 201), r.text
    return r.json()["ids"][0]


def done(s, nid, secs=90):
    return until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")), secs)


def settled(kind, ref_id, secs=120):
    return until(lambda: (lambda r: r and r[0][0] in ("found", "none", "skip", "error") and r[0][0])(
        dbx("SELECT state FROM file_text WHERE kind=? AND ref_id=?", (kind, ref_id))), secs)


def fmove(s, body):
    return s.post(B + "/api/files/move-space", json=body)


def gone(r):
    return r.status_code in (403, 404)


def doc_ids(s, **params):
    r = s.get(B + "/api/docs", params={"facets": "0", **params})
    return [d["id"] for d in r.json()["docs"]] if r.ok else []


def fsearch(s, q, space=None):
    r = s.get(B + "/api/files/search", params={"q": q, **({"space": space} if space else {})})
    return [x["id"] for x in r.json()["items"]] if r.ok else []


def top(s, space):
    r = s.get(B + "/api/files", params={"space": space})
    return [x["id"] for x in r.json()["items"]] if r.ok else []


def facet_names(s, ws):
    f = s.get(B + "/api/docs", params={"ws": ws}).json().get("facets") or {}
    return {k: {x["name"] for x in f.get(k) or []} for k in ("senders", "types", "tags")}


def v1(tok, path, **params):
    return requests.get(B + "/api/v1" + path, params=params, headers={"Authorization": "Bearer " + tok, **H})


def lst(s, lid):
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)


def task_ids(s):
    return {t["id"] for t in s.get(B + "/api/state").json()["tasks"]}


# ---- setup: alice (instance admin), Alpha = bob (admin) + carol + erin, Beta = dave; the server key on (sealed files)
if not os.environ.get("P296E_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_SECRET_KEY=" + KEY +
               " -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_FILE_OCR_REHOME_S=1")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
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
SP = f"org:{ORG}"
Bo = sess("bob")
for u in ("carol", "erin"):
    check((Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com"}).ok and org_join(B, u, ORG)), f"setup: {u} joins Alpha")
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?,?)) OR (org_id=? AND user_id NOT IN (?))", (ORG, BOB, CAROL, ERIN, ORG2, DAVE))
r = A.post(B + "/api/admin/agents", json={"username": "alphabot", "display_name": "Alphabot",
                                          "scopes": ["read", "files:read", "attachments:read"]})
assert r.status_code == 201, r.text
AGT, AGID = r.json().get("token") or "", r.json()["id"]
dbx("UPDATE agents SET org_id=?, owner_id=? WHERE user_id=?", (ORG, BOB, AGID))
Bo.post(B + "/api/auth/logout")
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEAT})

# ================================================================ 1. files + document: Alpha -> private (tenant-matrix: file)
WORD_F, WORD_D = "Kirschbaumholz", "Sonnenblumenfeld"
AKTE = folder(Ca, "Akte", space=SP)
FTXT = text_pdf([f"Akte {WORD_F} Notiz", os.urandom(4).hex()])  # a PDF: plain text files are no recognition type
FILE = upload(Ca, "akte.pdf", FTXT, parent=AKTE)
DOC = doc_up(Ca, "rechnung.pdf", ["Gaertnerei Beispiel", f"Rechnung {WORD_D} 2026", "Rosen Tulpen"], SP)
d = done(Ca, DOC)
check(d and d["state"] == "done", f"setup: the document is recognised ({d and d['state']})")
check(Ca.patch(B + f"/api/docs/{DOC}", json={"sender": "Gaertnerei Beispiel", "type": "Pflanzenrechnung", "tags": ["Garten"]}).ok,
      "setup: sender, type, tag of the document")
check(settled("fs", FILE) == "found", "setup: the text of the plain file is recognised")
check(Ca.post(B + f"/api/files/nodes/{AKTE}/shares", json={"user_id": BOB, "role": "view"}).status_code == 201, "setup: the folder shared with bob")
check(Ca.post(B + f"/api/files/nodes/{AKTE}/shares", json={"agent_id": AGID, "role": "view"}).status_code == 201,
      "setup: the folder shared with Alpha's agent")
check(Ca.patch(B + f"/api/files/nodes/{DOC}", json={"org_access": "view"}).ok, "setup: the document opened to Alpha")
check(Ca.post(B + f"/api/files/nodes/{DOC}/shares", json={"agent_id": AGID, "role": "view"}).status_code == 201,
      "setup: the document shared with Alpha's agent")
LA = Ca.post(B + "/api/lists", json={"name": "Gartenprojekt", "org_id": ORG}).json()["id"]
ts = "2026-10-18T10:00:00Z"
dbx("INSERT INTO rc_receipts(node_id, org_id, ws, list_id, category, set_by, set_at) VALUES(?,?,?,?,?,?,?)",
    (DOC, ORG, f"o{ORG}", LA, "Material", CAROL, ts))
dbx("INSERT INTO rc_suggest(node_id, org_id, ws, agent_id, list_id, category, note, state, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
    (DOC, ORG, f"o{ORG}", AGID, LA, "Material", "", "open", ts))
# 2.206.0 (#2735): an organisation's receipt needs the area receipts for an agent too (2.187.1) -> the agent into Project management
r = Bo.put(B + f"/api/office/rights/people/{AGID}", json={"groups": ["tpl:projects"]})
check(r.ok, "setup: Alpha's agent into Project management (area receipts) " + r.text[:200])
# what the old workspace sees before (the checks after the move are only meaningful when these hold)
check(Bo.get(B + f"/api/files/nodes/{FILE}/content").content == FTXT and Bo.get(B + f"/api/docs/{DOC}").ok, "before: bob reads file and document")
check(FILE in fsearch(Bo, WORD_F.lower()) and DOC in doc_ids(Bo, ws="all", q=WORD_D.lower()), "before: bob's searches find them")
check("Gaertnerei Beispiel" in facet_names(Bo, SP)["senders"], "before: Alpha's filters show the sender")
check(AKTE in top(Bo, "shared") or AKTE in top(Bo, SP), "before: bob's file list shows the folder")
check(v1(AGT, f"/files/{AKTE}").ok and v1(AGT, f"/documents/{DOC}").ok and v1(AGT, f"/files/{FILE}/text").ok,
      "before: Alpha's agent reads folder, document, text")
OLD_V = versions(FILE) + versions(DOC)
OLD_TH = one("SELECT thumb FROM doc_meta WHERE node_id=?", (DOC,))
OLD_DW = {r[0] for r in dbx("SELECT h FROM doc_words WHERE node_id=?", (DOC,))}
OLD_FW = {r[0] for r in dbx("SELECT w.h FROM file_words w JOIN file_text f ON f.id=w.ft_id WHERE f.kind='fs' AND f.node_id=?", (FILE,))}
LOG_BEFORE = {(x["action"], x.get("at")) for x in Ca.get(B + f"/api/files/nodes/{AKTE}").json().get("log") or []}
check(all(head_space(p) == ORG for p in OLD_V) and OLD_DW and OLD_FW, "before: sealed for Alpha, word indexes there")

# 2.148.1 (#2483): out of an organisation only through its admin -- carol moves as an admin of Alpha from here on
check(fmove(Ca, {"ids": [AKTE, DOC], "to": "private"}).status_code == 403, "#2483: a member does not move them out of Alpha (403)")
dbx("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=?", (ORG, CAROL))
r = fmove(Ca, {"ids": [AKTE, DOC], "to": "private", "dry": 1})
check(r.ok and r.json().get("block") is None and r.json().get("shares") == 3, f"dry run: 3 shares end, no block ({r.text[:300]})")
r = fmove(Ca, {"ids": [AKTE, DOC], "to": "private", "parent": None})
check(r.ok, f"carol takes her folder and document into her private space ({r.status_code} {r.text[:300]})")
U = f"u{CAROL}"
# -- the colleague
for nid in (AKTE, FILE, DOC):
    check(gone(Bo.get(B + f"/api/files/nodes/{nid}")), f"after: bob gets 404 on node {nid}")
check(gone(Bo.get(B + f"/api/files/nodes/{FILE}/content")) and gone(Bo.get(B + f"/api/files/nodes/{DOC}/content")), "after: bob gets no content")
check(gone(Bo.get(B + f"/api/files/nodes/{FILE}/preview")) and gone(Bo.get(B + f"/api/files/nodes/{DOC}/preview")), "after: bob gets no preview")
for p in ("", "/file", "/thumb"):
    check(gone(Bo.get(B + f"/api/docs/{DOC}{p}")), f"after: bob gets 404 on /api/docs/{DOC}{p}")
check(gone(Bo.get(B + "/api/files", params={"parent": AKTE})), "after: bob cannot list the folder")
check(not {AKTE, FILE, DOC} & set(top(Bo, SP) + top(Bo, "shared")), "after: Alpha's / bob's shared file list no longer shows them")
check(DOC not in doc_ids(Bo, ws=SP) and DOC not in doc_ids(Bo, ws="all"), "after: Alpha's documents list no longer shows it")
check(not {FILE, AKTE, DOC} & set(fsearch(Bo, WORD_F.lower()) + fsearch(Bo, "akte") + fsearch(Bo, WORD_D.lower())),
      "after: bob's file search finds neither the name nor the text")
check(DOC not in doc_ids(Bo, ws="all", q=WORD_D.lower()) and DOC not in doc_ids(Bo, ws=SP, q="gaertnerei"), "after: bob's document search finds nothing")
fn = facet_names(Bo, SP)
check("Gaertnerei Beispiel" not in fn["senders"] and "Pflanzenrechnung" not in fn["types"] and "Garten" not in fn["tags"],
      f"after: Alpha's filters no longer offer sender / type / tag ({fn})")
# -- the agent of Alpha
for p in (f"/files/{AKTE}", f"/files/{FILE}", f"/files/{FILE}/content", f"/files/{FILE}/text", f"/documents/{DOC}"):
    check(gone(v1(AGT, p)), f"after: Alpha's agent gets 404 on {p}")
lid = [x["id"] for x in v1(AGT, "/files").json().get("data") or []]
check(not {AKTE, FILE, DOC} & set(lid), f"after: the agent's file list no longer shows them ({lid})")
check(DOC not in [x["id"] for x in v1(AGT, "/documents").json().get("data") or []], "after: the agent's documents list no longer shows it")
sr = v1(AGT, "/files/search", q=WORD_F.lower())
check(not sr.ok or not {FILE, AKTE} & {x["id"] for x in sr.json().get("data") or []}, "after: the agent's file search finds nothing")
# -- the database: no row of it left with Alpha
check(one("SELECT COUNT(*) FROM fs_nodes WHERE id IN (?,?,?) AND org_id IS NOT NULL", (AKTE, FILE, DOC)) == 0, "db: the nodes are private")
m = dbx("SELECT ws, org_id, sender_id, type_id, trained FROM doc_meta WHERE node_id=?", (DOC,))[0]
check(m[0] == U and m[1] is None, f"db: doc_meta in carol's workspace ({m[0]}, {m[1]})")
check(one("SELECT ws FROM doc_senders WHERE id=?", (m[2],)) == U and one("SELECT ws FROM doc_types WHERE id=?", (m[3],)) == U,
      "db: sender and type are labels of carol's workspace")
tg = dbx("SELECT t.ws FROM doc_node_tags nt JOIN doc_tags t ON t.id=nt.tag_id WHERE nt.node_id=?", (DOC,))
check(tg and all(x[0] == U for x in tg), f"db: the tags are labels of carol's workspace ({tg})")
NEW_DW = {r[0] for r in dbx("SELECT h FROM doc_words WHERE node_id=?", (DOC,))}
check(NEW_DW and not NEW_DW & OLD_DW, "db: the document's word index is new (keyed for carol's workspace, no hash of Alpha's key left)")
ft = dbx("SELECT ws, org_id, state, id FROM file_text WHERE kind='fs' AND node_id=?", (FILE,))
check(ft and ft[0][0] == U and ft[0][1] is None, f"db: file_text of the plain file in carol's workspace ({ft})")
NEW_FW = {r[0] for r in dbx("SELECT h FROM file_words WHERE ft_id=?", (ft[0][3],))} if ft else set()
check(NEW_FW and not NEW_FW & OLD_FW, "db: the file's word index is new")
check(dbx("SELECT ws, org_id, list_id FROM rc_receipts WHERE node_id=?", (DOC,)) == [] or
      [tuple(x) for x in dbx("SELECT ws, org_id, list_id FROM rc_receipts WHERE node_id=?", (DOC,))] == [(U, None, None)],
      "db: the receipt is carol's, without Alpha's project")
check(one("SELECT COUNT(*) FROM rc_suggest WHERE node_id=? AND (agent_id=? OR org_id IS NOT NULL OR ws<>?)", (DOC, AGID, U)) == 0,
      "db: the open suggestion of Alpha's agent is gone")
check(one("SELECT COUNT(*) FROM upload_scan WHERE kind='fs' AND ref_id IN (?,?,?) AND org_id IS NOT NULL", (AKTE, FILE, DOC)) == 0,
      "db: no virus-scan row with Alpha")
check(one("SELECT COUNT(*) FROM fs_shares WHERE node_id IN (?,?,?)", (AKTE, FILE, DOC)) == 0, "db: no share left (bob, the agent)")
NEW_V = versions(FILE) + versions(DOC)
check(NEW_V and all(head_space(p) == -CAROL for p in NEW_V), f"disk: every version sealed for carol's account ({[head_space(p) for p in NEW_V]})")
check(not any(os.path.exists(os.path.join(DATA, "attachments", p)) for p in OLD_V if p not in NEW_V), "disk: no old stored file left")
if OLD_TH:
    check(not os.path.exists(os.path.join(DATA, "attachments", OLD_TH)), "disk: the old preview is gone")
# -- carol (the target) reads everything, with the history
check(Ca.get(B + f"/api/files/nodes/{FILE}/content").content == FTXT, "carol reads the same content")
d = Ca.get(B + f"/api/docs/{DOC}").json()
check(d.get("ws") == U and (d.get("sender") or {}).get("name") == "Gaertnerei Beispiel" and WORD_D.lower() in (d.get("text") or "").lower(),
      "carol reads the document with its sender and text")
check(FILE in fsearch(Ca, WORD_F.lower(), "private") and DOC in doc_ids(Ca, ws="private", q=WORD_D.lower()), "carol's private searches find them")
log = Ca.get(B + f"/api/files/nodes/{AKTE}").json().get("log") or []
check(any(x["action"] == "moved_space" for x in log) and LOG_BEFORE <= {(x["action"], x.get("at")) for x in log},
      f"the folder's history moved along and names the move ({[x['action'] for x in log]})")

# ================================================================ 2. files + document: private -> Alpha (not Beta)
PRIV = folder(Ca, "Privatordner")
PF = upload(Ca, "plan.pdf", text_pdf(["Plan Holunderbluete", os.urandom(4).hex()]), parent=PRIV)
PD = doc_up(Ca, "beleg.pdf", ["Baumarkt Beispiel", "Beleg Holunderbluete Schrauben"])
done(Ca, PD)
Ca.patch(B + f"/api/docs/{PD}", json={"sender": "Baumarkt Beispiel", "tags": ["Werkzeug"]})
check(settled("fs", PF) == "found", "setup: the text of the private file is recognised")
# a share with someone outside Alpha (the app offers only people one may see; the row as an older share left it)
dbx("INSERT INTO fs_shares(node_id, user_id, role, created_by, created_at) VALUES(?,?,?,?,?)", (PRIV, DAVE, "view", CAROL, ts))
check(Ca.post(B + f"/api/files/nodes/{PRIV}/shares", json={"user_id": ERIN, "role": "view"}).status_code == 201, "setup: shared with erin (Alpha)")
check(Da.get(B + f"/api/files/nodes/{PF}/content").ok, "before: dave reads the file")
OLD_V = versions(PF) + versions(PD)
r = fmove(Ca, {"ids": [PRIV, PD], "to": SP, "parent": None})
check(r.ok and r.json().get("shares") == 1, f"private -> Alpha: one share ends (dave) ({r.status_code} {r.text[:300]})")
check(gone(Da.get(B + f"/api/files/nodes/{PRIV}")) and gone(Da.get(B + f"/api/files/nodes/{PF}/content")) and gone(Da.get(B + f"/api/docs/{PD}")),
      "after: dave (another organisation) gets 404")
check(not fsearch(Da, "holunderbluete") and not doc_ids(Da, ws="all", q="holunderbluete"), "after: dave's searches find nothing")
check(Er.get(B + f"/api/files/nodes/{PF}/content").ok, "after: erin (a member of Alpha) keeps her share")
check(one("SELECT COUNT(*) FROM fs_shares WHERE node_id=? AND user_id=?", (PRIV, DAVE)) == 0, "db: dave's share is gone")
check(not doc_ids(Ca, ws="private", q="holunderbluete") and not fsearch(Ca, "holunderbluete", "private"), "the private searches no longer find it")
check(PD in doc_ids(Ca, ws=SP, q="holunderbluete") and PF in fsearch(Ca, "holunderbluete", SP), "Alpha's searches find it")
check(one("SELECT ws FROM doc_meta WHERE node_id=?", (PD,)) == f"o{ORG}" and
      one("SELECT COUNT(*) FROM doc_node_tags nt JOIN doc_tags t ON t.id=nt.tag_id WHERE nt.node_id=? AND t.ws<>?", (PD, f"o{ORG}")) == 0,
      "db: the document and its tags in Alpha's workspace")
check(one("SELECT COUNT(*) FROM file_text WHERE kind='fs' AND node_id=? AND (ws<>? OR org_id IS DISTINCT FROM ?)", (PF, f"o{ORG}", ORG)) == 0,
      "db: the file's text in Alpha's workspace")
NEW_V = versions(PF) + versions(PD)
check(all(head_space(p) == ORG for p in NEW_V) and not any(os.path.exists(os.path.join(DATA, "attachments", p)) for p in OLD_V if p not in NEW_V),
      "disk: sealed for Alpha, no old stored file left")
check("Baumarkt Beispiel" not in facet_names(Ca, "private")["senders"], "the private filters no longer offer the sender")

# ================================================================ 3. knowledge pages, both ways
def wpage(s, path, text="", space="private"):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def wpaths(s, space):
    return {p["path"]: p["id"] for p in s.get(B + "/api/wiki", params={"space": space}).json()["pages"]}


def wsearch(s, q):
    return [p["id"] for p in s.get(B + "/api/wiki/search", params={"q": q}).json()["pages"]]


ANKER = wpage(Bo, "Anker", "Start here: [[Handbuch/Start]]", SP)
W1 = wpage(Ca, "Handbuch/Start", "Zitronenbaum: see [[Handbuch/Start/Unter]] and [[Anker]]", SP)
W2 = wpage(Ca, "Handbuch/Start/Unter", "Zitronenbaum detail, back to [[Handbuch/Start]]", SP)
check(W1 in wsearch(Bo, "zitronenbaum") and any(x["id"] == W1 for x in Bo.get(B + f"/api/wiki/pages/{ANKER}").json()["backlinks"]),
      "before: bob finds the page, Anker shows its backlink")
r = Ca.post(B + "/api/wiki/move-space", json={"folder": "Handbuch", "space": SP, "to": "private", "dest": "", "dry": 1})
check(r.ok and any("2 links point to the other workspace" in n for n in r.json().get("notes", [])),
      f"dry run: names the 2 links over the boundary ({r.text[:300]})")
r = Ca.post(B + "/api/wiki/move-space", json={"folder": "Handbuch", "space": SP, "to": "private", "dest": ""})
check(r.ok, f"carol takes her pages into her private space ({r.text[:200]})")
check(not {"Handbuch/Start", "Handbuch/Start/Unter"} & set(wpaths(Bo, SP)), "after: Alpha's page list no longer shows them")
check(not {W1, W2} & set(wsearch(Bo, "zitronenbaum")), "after: bob's search finds nothing")
check(gone(Bo.get(B + f"/api/wiki/pages/{W1}")) and gone(Bo.get(B + f"/api/wiki/pages/{W2}")),
      "after: bob gets 404 on the pages (and with it on their move history)")
check(not any(x["id"] in (W1, W2) for x in Bo.get(B + f"/api/wiki/pages/{ANKER}").json()["backlinks"]), "after: Anker shows no backlink from them")
moved = {W1, W2}
# links from a moved page: to one that moved along, or the reported text link to Anker
out = {(r[0], r[1]) for r in dbx("SELECT from_id, to_path FROM wiki_links WHERE from_id IN (?,?) AND to_path IS NOT NULL", (W1, W2))}
check(out <= {(W1, "handbuch/start/unter"), (W1, "anker"), (W2, "handbuch/start")}, f"db: links of the moved pages only as before ({out})")
inn = {(r[0], r[1]) for r in dbx("SELECT from_id, to_path FROM wiki_links WHERE to_path IN ('handbuch/start', 'handbuch/start/unter')")}
check({f for f, _ in inn} - moved <= {ANKER}, f"db: only the reported text link from Alpha points at the moved paths ({inn})")
sm = dbx("SELECT from_org, to_org, by_id FROM space_moves WHERE kind='wiki' AND obj_id=? ORDER BY id DESC LIMIT 1", (W1,))
check(sm and list(sm[0]) == [ORG, None, CAROL], f"db: the move is in the page's history ({sm and list(sm[0])})")
g = Ca.get(B + f"/api/wiki/pages/{W1}").json()
check(g.get("moved", {}).get("from") == SP and "Zitronenbaum" in g.get("body", "") and W1 in wsearch(Ca, "zitronenbaum"),
      "carol reads the page, its history and finds it")
check(any(x["id"] == W1 for x in Ca.get(B + f"/api/wiki/pages/{W2}").json()["backlinks"]), "the link between the moved pages works on")
# the way back: private -> Alpha, Beta sees nothing
r = Ca.post(B + "/api/wiki/move-space", json={"pages": [W2], "space": "private", "to": SP, "dest": "Archiv"})
check(r.ok and wpaths(Bo, SP).get("Archiv/Unter") == W2, f"private -> Alpha: bob sees the page ({r.text[:200]})")
check("Handbuch/Start/Unter" not in wpaths(Ca, "private") and gone(Da.get(B + f"/api/wiki/pages/{W2}")) and W2 not in wsearch(Da, "zitronenbaum"),
      "gone from the private space, Beta gets 404")

# ================================================================ 4. a table bound to a list of Alpha
TL = Ca.post(B + "/api/lists", json={"name": "Tabellenliste", "org_id": ORG}).json()["id"]
check(Ca.patch(B + f"/api/lists/{TL}", json={"org_visibility": "org"}).ok, "setup: the list is open to everyone in Alpha")
TT = Ca.post(B + "/api/tasks", json={"title": "Zeile als Aufgabe", "list_id": TL}).json()["id"]
r = Ca.post(B + "/api/sheets", json={"title": "Kostenplan", "space": SP, "list_id": TL})
assert r.status_code == 201, r.text
SID = r.json()["id"]
Ca.put(B + f"/api/sheets/{SID}/cells", json={"cells": [{"cell": "A1", "raw": "Erdbeeren"}, {"cell": "B1", "raw": "12"}]})
ROW = one("SELECT id FROM sheet_rows WHERE sheet_id=? ORDER BY id LIMIT 1", (SID,))
dbx("INSERT INTO sheet_links(sheet_id, row_id, kind, target_id, list_id, batch, created_by, created_at) VALUES(?,?,?,?,?,?,?,?)",
    (SID, ROW, "task", TT, TL, "b1", CAROL, ts))
check(Bo.get(B + f"/api/sheets/{SID}").ok and SID in [x["id"] for x in Bo.get(B + "/api/sheets", params={"space": SP}).json().get("sheets", [])],
      "before: bob opens and lists the table")
r = Ca.post(B + f"/api/sheets/{SID}/move-space", json={"to": "private"})
check(r.ok and r.json()["sheet"]["list_id"] is None, f"carol takes the table into her private space, detached ({r.text[:200]})")
check(gone(Bo.get(B + f"/api/sheets/{SID}")), "after: bob gets 404 on the table")
for q in ({"space": SP}, {"space": "all"}, {"list_id": TL}):
    check(SID not in [x["id"] for x in (Bo.get(B + "/api/sheets", params=q).json() or {}).get("sheets", [])], f"after: bob's table list {q} no longer shows it")
check(one("SELECT COUNT(*) FROM sheet_links WHERE sheet_id=? AND undone_at IS NULL", (SID,)) == 0, "db: the carry-over to Alpha's task ended")
check(list(dbx("SELECT org_id, owner_id, list_id FROM sheets WHERE id=?", (SID,))[0]) == [None, CAROL, None], "db: carol's private table, no list")
check(Ca.get(B + f"/api/sheets/{SID}").json().get("space") == "private", "carol opens it in her private space")

# ================================================================ 5. a list with task, comment and file (existing move: PATCH org_id)
# bob owns the list (and Alpha's agent); carol and erin are colleagues who see it only through "everyone in the organisation"
L = Bo.post(B + "/api/lists", json={"name": "Teamliste Apfel", "org_id": ORG}).json()["id"]
check(Bo.patch(B + f"/api/lists/{L}", json={"org_visibility": "org"}).ok, "setup: open to everyone in Alpha")
T = Bo.post(B + "/api/tasks", json={"title": "Apfelernte planen", "list_id": L}).json()["id"]
check(Bo.post(B + f"/api/tasks/{T}/comments", json={"body": "Kommentar Birnenmus"}).ok, "setup: a comment")
ATXT = text_pdf(["Anhang Quittengelee", os.urandom(4).hex()])
check(Bo.post(B + f"/api/tasks/{T}/attachments", files={"file": ("liste.pdf", ATXT, "application/pdf")}).ok, "setup: a file on the task")
AID = one("SELECT id FROM attachments WHERE task_id=? ORDER BY id DESC LIMIT 1", (T,))
APATH = one("SELECT path FROM attachments WHERE id=?", (AID,))
check(settled("att", AID) == "found", "setup: the file's text is recognised")
check(until(lambda: head_space(APATH) == ORG, 30), f"before: the file is sealed for Alpha ({head_space(APATH)})")
r = Ca.post(B + "/api/files/links", json={"ref_kind": "att", "ref_id": AID, "space": SP})
LINK = r.json().get("id") if r.status_code == 201 else None
check(LINK, f"setup: carol links the file in Alpha's file store ({r.status_code} {r.text[:200]})")
r = Bo.put(B + f"/api/lists/{L}/members", json={"user_id": AGID, "role": "edit", "bridge_ok": True})
check(r.ok, f"setup: Alpha's agent joins the list ({r.status_code} {r.text[:200]})")
check(lst(Ca, L) and T in task_ids(Ca) and Ca.get(B + f"/api/attachments/{AID}").ok, "before: carol sees list, task and file")
check(Ca.get(B + f"/api/files/nodes/{LINK}/content").ok if LINK else False, "before: carol's link opens the file")
check(v1(AGT, f"/lists/{L}").ok and v1(AGT, f"/tasks/{T}").ok, "before: the agent sees list and task")
r = Bo.patch(B + f"/api/lists/{L}", json={"org_id": None})
check(r.status_code == 409 and one("SELECT org_id FROM lists WHERE id=?", (L,)) == ORG, f"an agent of Alpha in the list blocks the move ({r.status_code})")
check(Bo.delete(B + f"/api/lists/{L}/members/{AGID}").ok, "bob takes the agent out")
r = Bo.patch(B + f"/api/lists/{L}", json={"org_id": None})
check(r.ok and one("SELECT org_id FROM lists WHERE id=?", (L,)) is None, f"bob takes the list into his private space ({r.status_code} {r.text[:200]})")
for who, s in (("carol", Ca), ("erin", Er)):
    check(lst(s, L) is None and T not in task_ids(s), f"after: {who}'s state shows neither list nor task")
    check(gone(s.get(B + f"/api/tasks/{T}")) and gone(s.get(B + f"/api/tasks/{T}/timeline")), f"after: {who} gets 404 on the task and its comments")
    check(gone(s.get(B + f"/api/attachments/{AID}")), f"after: {who} gets 404 on the file")
    sr = s.get(B + "/api/tasks", params={"scope": "search", "q": "Apfelernte"})
    check(not sr.ok or T not in [t["id"] for t in sr.json().get("tasks", [])], f"after: {who}'s task search finds nothing")
    check(AID not in [x.get("id") for x in (s.get(B + "/api/files/search", params={"q": "quittengelee"}).json() or {}).get("items", [])],
          f"after: {who}'s file search finds nothing of the file")
check(LINK and Ca.get(B + f"/api/files/nodes/{LINK}/content").status_code != 200, "after: carol's link in Alpha's file store no longer opens the file")
for p in (f"/lists/{L}", f"/tasks/{T}", f"/tasks/{T}/comments", f"/tasks/{T}/attachments"):
    check(gone(v1(AGT, p)), f"after: the agent gets 404 on {p}")
check(L not in [x["id"] for x in v1(AGT, "/lists").json().get("data") or []], "after: the agent's lists no longer show it")
check(one("SELECT COUNT(*) FROM list_members WHERE list_id=?", (L,)) == 0 and
      one("SELECT COUNT(*) FROM group_shares WHERE list_id=?", (L,)) == 0, "db: no member / group share left")
check(until(lambda: head_space(APATH) == -BOB, 60), f"disk: the settle pass sealed the file for bob's account ({head_space(APATH)})")
check(Bo.get(B + f"/api/attachments/{AID}").content == ATXT, "bob reads the file")
tl = Bo.get(B + f"/api/tasks/{T}/timeline").json()
check(any("Birnenmus" in (c.get("body") or "") for c in tl.get("comments", [])), "bob reads the comment")
check(until(lambda: one("SELECT ws FROM file_text WHERE kind='att' AND ref_id=?", (AID,)) == f"u{BOB}", 60) and
      one("SELECT org_id FROM file_text WHERE kind='att' AND ref_id=?", (AID,)) is None,
      f"db: the file's recognised text belongs to bob's workspace (sweep) ({one('SELECT ws FROM file_text WHERE kind=? AND ref_id=?', ('att', AID))})")
# private -> organisation with someone of another organisation in the list: refused (the row as an older share left it)
PL = Bo.post(B + "/api/lists", json={"name": "Mit Dave", "org_id": None}).json()["id"]
dbx("INSERT INTO list_members(list_id, user_id, role, added_at) VALUES(?,?,?,?)", (PL, DAVE, "edit", ts))
r = Bo.patch(B + f"/api/lists/{PL}", json={"org_id": ORG})
check(r.status_code == 409 and one("SELECT org_id FROM lists WHERE id=?", (PL,)) is None, f"dave (Beta) in it: no move into Alpha ({r.status_code})")

# ================================================================ 6. learning: the source forgets, the target knows (#1941, 21:20)
TRAIN = [("vers1.pdf", ["Versicherung Beispiel AG", "Police Haftpflicht Beitrag", "Beitragsrechnung Hausrat"], "Versicherung Beispiel AG", "Beitragsrechnung"),
         ("vers2.pdf", ["Versicherung Beispiel AG", "Police Haftpflicht Beitrag", "Beitragsrechnung 2026 Hausrat"], "Versicherung Beispiel AG", "Beitragsrechnung"),
         ("stadt1.pdf", ["Stadtwerke Musterstadt", "Abschlag Strom Kilowattstunden", "Zaehlerstand Verbrauch"], "Stadtwerke Musterstadt", "Abschlag"),
         ("stadt2.pdf", ["Stadtwerke Musterstadt", "Jahresabrechnung Strom Verbrauch", "Kilowattstunden Zaehlerstand"], "Stadtwerke Musterstadt", "Abschlag")]
PROBE = ["Versicherung Beispiel AG", "Police Haftpflicht Beitrag Hausrat", "Beitragsrechnung"]
tids = []
for name, lines, sender, typ in TRAIN:
    nid = doc_up(Er, name, lines)
    done(Er, nid)
    Er.patch(B + f"/api/docs/{nid}", json={"sender": sender, "type": typ})
    Er.post(B + f"/api/docs/{nid}/review", json={"done": True})
    tids.append(nid)
check(all(one("SELECT trained FROM doc_meta WHERE node_id=?", (n,)) for n in tids), "setup: the four documents are trained in erin's workspace")


GUESSES = []


def guess(s, ws):
    """(sender, type) names the workspace's models set or suggest for a new similar document."""
    # 2.146.0 (#2452): the same bytes again in the same workspace come back as "already there" without a new id ->
    # every probe gets its own last line (the models read the sender / type lines above it)
    GUESSES.append(ws)
    nid = doc_up(s, "probe.pdf", PROBE + [f"Vorgang {len(GUESSES)}"], ws)
    d = done(s, nid) or {}
    sg = d.get("suggest") or {}
    return nid, ((d.get("sender") or {}).get("name") or (sg.get("sender") or {}).get("label"),
                 (d.get("type") or {}).get("name") or (sg.get("type") or {}).get("label"))


P1, g1 = guess(Er, "private")
check(g1[0] == "Versicherung Beispiel AG", f"before: erin's private models know the sender ({g1})")
Er.delete(B + f"/api/files/nodes/{P1}")  # untrained (never confirmed); out of the way
r = fmove(Er, {"ids": tids, "to": SP, "parent": "docs"})
check(r.ok, f"erin moves the four documents into Alpha ({r.status_code} {r.text[:200]})")
check(all(one("SELECT ws FROM doc_meta WHERE node_id=?", (n,)) == f"o{ORG}" and one("SELECT trained FROM doc_meta WHERE node_id=?", (n,))
          for n in tids), "doc_meta.trained is filled again for Alpha's workspace")
P2, g2 = guess(Er, "private")
check(g2[0] != "Versicherung Beispiel AG" and g2[1] != "Beitragsrechnung", f"the private models forgot them ({g2})")
P3, g3 = guess(Er, SP)
check(g3[0] == "Versicherung Beispiel AG", f"Alpha's models learnt the sender at once ({g3})")
check(g3[1] == "Beitragsrechnung", f"... and the type ({g3})")
P4, g4 = guess(Bo, SP)
check(g4[0] == "Versicherung Beispiel AG", f"for every member of Alpha (bob's upload) ({g4})")

# ================================================================ a person without an organisation (freelancer-matrix: files)
FID, Fr = freelancer(B, A)
FN = upload(Fr, "eigen.txt", b"Freiberuflich")
check(fmove(Fr, {"ids": [FN], "to": SP}).status_code == 409, "freelancer: no organisation to move into (409)")
check(gone(Fr.get(B + f"/api/files/nodes/{FILE}")) and not fsearch(Fr, WORD_F.lower()), "freelancer: sees nothing of carol's private file")

print(f"p296_e_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
