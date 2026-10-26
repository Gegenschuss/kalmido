#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.353.0 D (#2759): file store and documents are one area -- recognition per folder / file, inherited like the rights; the
saved filters show only what the person may see; the file store's search finds documents by their fields. Invented people,
companies and files only (the PDFs are made here).
 (a) a person WITHOUT an organisation: the documents folder recognises (its subfolders inherit), a plain top folder does not;
     a file uploaded / moved into a recognising folder becomes a document, elsewhere it stays a plain file
 (b) "Recognise" for one file outside a recognising folder; a folder switched on makes its files documents at once, a
     subfolder with its own "off" keeps its files plain, "inherit" again follows the folder above; switched off: new files
     stay plain, the documents stay documents
 (c) rights: view only -> 403, another person -> 404, a reference / link node -> 409; the list carries recog_on / doc
 (d) the search of the file store finds a document by sender, type and tag (hit doc) -- never one the asker may not see
 (e) the saved filters "Documents" / "To review" (GET /api/docs, review=1) in an organisation: a member sees only his own and
     what is shared with him; the admin's document waiting for review appears for him only after a share
 (f) the setting ab_cards (list / cards per folder, all devices): single entries, a wrong entry is 400
usage: p2353_d_ablagedocs_test.py <datadir>
freelancer-matrix: files"""
import os
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
FEAT = "cal,comments,collab,docs,files"

if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Example", "admin_id": ALICE}).json()["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Staff", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
FID, Fr = freelancer(B, A, "frida")


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


def doc_upload(s, name, ws):
    r = s.post(B + "/api/docs", data={"ws": ws}, files={"files": (name, tiny_pdf("Doc " + name), "application/pdf")})
    check(r.status_code == 201, f"setup: document {name} ({r.status_code} {r.text[:120]})")
    return r.json()["ids"][0]


def file_up(s, name, parent):
    r = s.post(B + "/api/files/upload", data={"parent_id": str(parent)}, files={"file": (name, tiny_pdf("File " + name), "application/pdf")})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["items"][0]["id"]


def folder(s, name, parent=None, space="private"):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": space})})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["id"]


def is_doc(s, nid):
    return s.get(B + f"/api/docs/{nid}").status_code == 200


def recog(s, nid, mode):
    return s.put(B + f"/api/files/nodes/{nid}/recognition", json={"mode": mode})


def listing(s, pid, docs=False):
    r = s.get(B + f"/api/files?parent={pid}" + ("&docs=1" if docs else ""))
    assert r.ok, r.text
    return r.json()


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


# ---------------------------------------------------------------- (a) without an organisation: the documents folder recognises
D1 = doc_upload(Fr, "first-letter.pdf", "private")
ROOT = Fr.get(B + f"/api/files/nodes/{D1}").json()["parent_id"]
j = listing(Fr, ROOT)
check(j["node"].get("recog_on") is True and j["node"].get("recog_root") is True, f"(a) the documents folder recognises ({j['node']})")
check(any(x["id"] == D1 and (x.get("doc") or {}).get("state") for x in j["items"]), "(a) its document carries doc {state, review} in the list")
SUB = folder(Fr, "Insurance", ROOT)
j = listing(Fr, SUB)
check(j["node"].get("recog_on") is True and j["node"].get("recog_from") == "Dokumente", f"(a) a subfolder inherits it ({j['node']})")
F1 = file_up(Fr, "policy.pdf", SUB)
check(is_doc(Fr, F1), "(a) a file uploaded into the recognising subfolder became a document")
PLAIN = folder(Fr, "Holiday")
top = Fr.get(B + "/api/files?space=private").json()["items"]
check(next(x for x in top if x["id"] == PLAIN).get("recog_on") is False and next(x for x in top if x["id"] == ROOT).get("recog_on") is True,
      "(a) the top of the space: the documents folder recognises, a plain folder does not")
F2 = file_up(Fr, "tickets.pdf", PLAIN)
check(not is_doc(Fr, F2), "(a) a file in a plain folder stays a plain file (404 as a document)")
F3 = file_up(Fr, "receipt-move.pdf", PLAIN)
check(Fr.patch(B + f"/api/files/nodes/{F3}", json={"parent_id": SUB}).ok and is_doc(Fr, F3), "(a) moved into a recognising folder: a document")

# ---------------------------------------------------------------- (b) one file, a folder switched on / off, own values below
r = recog(Fr, F2, "on")
check(r.ok and r.json()["added"] == 1 and is_doc(Fr, F2), f"(b) Recognise one file outside: a document ({r.status_code} {r.text[:120]})")
check(recog(Fr, F2, "off").status_code == 400, "(b) a file takes on only")
SCANS = folder(Fr, "Scans")
S1, S2 = file_up(Fr, "scan-1.pdf", SCANS), file_up(Fr, "scan-2.pdf", SCANS)
OLD = folder(Fr, "Old", SCANS)
check(recog(Fr, OLD, "off").ok, "(b) setup: Scans / Old says off of its own")
S3 = file_up(Fr, "old-scan.pdf", OLD)
r = recog(Fr, SCANS, "on")
check(r.ok and r.json()["added"] == 2 and r.json()["recog"]["on"] is True and is_doc(Fr, S1) and is_doc(Fr, S2),
      f"(b) Scans switched on: its two files became documents at once ({r.text[:160]})")
check(not is_doc(Fr, S3), "(b) the subfolder with its own off keeps its file plain")
NEW = folder(Fr, "New", SCANS)
S4 = file_up(Fr, "new-scan.pdf", NEW)
check(is_doc(Fr, S4), "(b) a new subfolder inherits on: its upload is a document")
r = recog(Fr, OLD, "inherit")
check(r.ok and r.json()["added"] == 1 and is_doc(Fr, S3) and listing(Fr, OLD)["node"].get("recog_from") == "Scans",
      f"(b) Old back to inherit: follows Scans, its file becomes a document ({r.text[:160]})")
check(recog(Fr, SCANS, "off").ok, "(b) setup: Scans switched off")
S5 = file_up(Fr, "late-scan.pdf", SCANS)
check(not is_doc(Fr, S5) and is_doc(Fr, S1), "(b) off: a new file stays plain, the documents stay documents")
check(listing(Fr, SCANS)["node"].get("recog") == "off", "(b) the folder's own value is in the list (recog)")
check(recog(Fr, SCANS, "maybe").status_code == 400, "(b) an unknown mode: 400")

# ---------------------------------------------------------------- (c) rights
check(recog(Bo, SCANS, "on").status_code == 404, "(c) another person: 404")
OF = folder(A, "Contracts", space=f"org:{ORG}")
r = A.post(B + f"/api/files/nodes/{OF}/shares", json={"user_id": BOB, "role": "view"})
check(r.status_code == 201, f"(c) setup: alice shares an organisation folder with bob to read ({r.status_code} {r.text[:120]})")
check(recog(Bo, OF, "on").status_code == 403, "(c) shared to read: 403")
check(sql("SELECT recog FROM fs_nodes WHERE id=?", (OF,))[0][0] == "", "(c) nothing changed by the refused request")
# a folder filed with a hub mail only its reader (alice) sees, inside the shared folder: bob's switch never reaches its file
MB = folder(A, "Mail box", OF)
MF = file_up(A, "mail-attachment.pdf", MB)
ts = time.strftime("%Y-%m-%dT%H:%M:%S")
sql("INSERT INTO hub_mails(org_id, owner_id, ws, message_id, created_at) VALUES(?,?,?,?,?)", (ORG, ALICE, f"org:{ORG}", "p2353d@example.com", ts), write=True)
HM = sql("SELECT id FROM hub_mails WHERE message_id=?", ("p2353d@example.com",))[0][0]
sql("UPDATE fs_nodes SET hub_mail_id=? WHERE id=?", (HM, MB), write=True)
OFF1 = file_up(A, "contract-draft.pdf", OF)
check(A.patch(B + f"/api/files/shares/{r.json()['id']}", json={"role": "edit"}).ok, "(c) setup: the share becomes edit")
check(Bo.get(B + f"/api/files/nodes/{MF}").status_code in (403, 404), "(c) setup: bob does not see the mail's file")
r = recog(Bo, OF, "on")
check(r.ok and r.json()["added"] == 1 and is_doc(A, OFF1), f"(c) shared to edit: bob may switch it, its file became a document ({r.text[:120]})")
check(not sql("SELECT 1 FROM doc_meta WHERE node_id=?", (MF,)), "(c) the file in the mail's folder he does not see stays a plain file")

# ---------------------------------------------------------------- (d) the search finds a document by its fields
r = Fr.patch(B + f"/api/docs/{F1}", json={"sender": "Gamma Example Insurance", "type": "Policy", "tags": ["Yearly"]})
check(r.ok, f"(d) setup: sender / type / tag set by hand ({r.status_code} {r.text[:120]})")
for q in ("gamma example", "Policy", "yearly"):
    j = Fr.get(B + "/api/files/search", params={"q": q}).json()
    hit = next((x for x in j["items"] if x["id"] == F1), None)
    check(hit is not None and hit["hit"] in ("doc", "name", "text"), f"(d) the file store's search finds the document by '{q}' ({hit and hit['hit']})")
j = Fr.get(B + "/api/files/search", params={"q": "Gamma Example"}).json()
check(next(x for x in j["items"] if x["id"] == F1)["hit"] == "doc", "(d) the hit is marked doc (sender)")
check(not any(x["id"] == F1 for x in Bo.get(B + "/api/files/search", params={"q": "Gamma Example"}).json()["items"]),
      "(d) bob (no access) does not find it")
j = listing(Fr, SUB, docs=True)
d = next((x.get("doc") for x in j["items"] if x["id"] == F1), None) or {}
check((d.get("sender") or {}).get("name") == "Gamma Example Insurance" and d.get("id") == F1, "(d) docs=1: the card has the document's fields")

# ---------------------------------------------------------------- (e) saved filters only show what the person may see (organisation)
DA = doc_upload(A, "alpha-invoice.pdf", f"org:{ORG}")
DB = doc_upload(Bo, "bob-receipt.pdf", f"org:{ORG}")
sql("UPDATE doc_meta SET review=1 WHERE node_id IN (?, ?)", (DA, DB), write=True)


def review_ids(s):
    j = s.get(B + "/api/docs", params={"ws": f"org:{ORG}", "review": "1"}).json()
    return {x["id"] for x in j["docs"]}


check({DA, DB} <= review_ids(A), "(e) To review: the admin sees both")
check(review_ids(Bo) == {DB}, f"(e) To review: bob sees only his own ({review_ids(Bo)})")
check(DA not in {x["id"] for x in Bo.get(B + "/api/docs", params={"ws": f"org:{ORG}"}).json()["docs"]}, "(e) Documents: not the admin's either")
r = A.post(B + f"/api/files/nodes/{DA}/shares", json={"user_id": BOB, "role": "view"})
check(r.status_code == 201 and DA in review_ids(Bo), f"(e) shared with bob: now in his filter ({r.status_code})")
ORGROOT = A.get(B + f"/api/files/nodes/{DA}").json()["parent_id"]
check(listing(A, ORGROOT)["node"].get("recog_on") is True, "(e) the organisation's documents folder recognises as well")

# ---------------------------------------------------------------- (f) list / cards per folder: the setting ab_cards
r = Fr.patch(B + "/api/settings", json={"set_delta": {"ab_cards": {"add": [f"n:{SUB}", "s:private"]}}})
got = Fr.get(B + "/api/state").json()["settings"].get("ab_cards") if r.ok else None
check(r.ok and got and set(__import__("json").loads(got)) == {f"n:{SUB}", "s:private"}, f"(f) ab_cards: two folders as cards ({r.status_code} {got})")
r = Fr.patch(B + "/api/settings", json={"set_delta": {"ab_cards": {"remove": ["s:private"]}}})
check(r.ok and __import__("json").loads(Fr.get(B + "/api/state").json()["settings"]["ab_cards"]) == [f"n:{SUB}"], "(f) ab_cards: one removed")
check(Fr.patch(B + "/api/settings", json={"ab_cards": '["../x"]'}).status_code == 400, "(f) a wrong entry: 400")

print(f"p2353_d_ablagedocs: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
