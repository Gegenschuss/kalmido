#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.508.0 (#4301): deleting an account no longer takes what it shares privately with it. A private calendar, address book,
table (with its files) and the knowledge pages somebody may write pass to the longest-standing person with the right to
write, with what the others wrote; shares through a folder count like shares of the object. Nobody to take over: the object
goes and the delete dialog says so. 2.537.0 (#4347): shared folders and files of the private file store too (a branch with
its files, versions, recognised text and the contributions of others, sealed again for the heir). People without an
organisation throughout (freelancer-matrix: pim  freelancer-matrix: sheets  freelancer-matrix: wiki  freelancer-matrix: files); the organisation admin's dialog names nobody. Invented names only, sealed with a server key.
usage: p2508_share_heir_test.py <datadir>"""
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from kt import B, check, dbx, sess, until  # noqa: E402

kt.fresh({"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": base64.b64encode(os.urandom(32)).decode()})
A = kt.setup()
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
FEAT = "cal,comments,collab,events,files,docs,sheets,wiki,contacts"
PDF = b"%PDF-1.4 a small manual"
DAY = "2030-03-04"


def write(q, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"))
    c.execute(q, args)
    c.commit()
    c.close()


write("INSERT INTO settings(key, value) VALUES('wiki_encrypt', '1') ON CONFLICT (key) DO UPDATE SET value='1'")  # page texts sealed too


def person(name):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com", "orgs": []})
    assert r.ok, r.text
    s = sess(name)
    assert s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"}).ok
    return r.json()["id"], s


def cal(s, name):
    r = s.post(B + "/api/evcals", json={"name": name, "org_id": None})
    assert r.ok, r.text
    return r.json()["id"]


def book(s, name):
    r = s.post(B + "/api/books", json={"name": name})
    assert r.ok, r.text
    return r.json()["id"]


def sheet(s, title, **kw):
    r = s.post(B + "/api/sheets", json={"title": title, "space": "private", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def page(s, path, text):
    r = s.post(B + "/api/wiki/pages", json={"space": "private", "path": path, "body": text})
    assert r.ok, r.text
    return r.json()["id"]


def fid(r):
    j = r.json()
    return j["id"] if "id" in j else (j.get("folder") or j["node"])["id"]


def owner(table, oid):
    r = dbx(f"SELECT owner_id FROM {table} WHERE id=?", (oid,))
    return r[0][0] if r else None


ANNA, An = person("anna")
ERIK, Er = person("erik")
BERT, Be = person("bert")
CARA, Ca = person("cara")
DORA, Do = person("dora")

# ---------------------------------------------------------------- calendars
BERT_DEFAULT = cal(Be, "Bert's own")
C1 = cal(An, "Family")
for who, role in ((DORA, "view"), (ERIK, "edit"), (BERT, "edit"), (CARA, "edit")):  # dora first but read-only; erik will be disabled
    r = An.put(B + f"/api/evcals/{C1}/members", json={"user_id": who, "role": role})
    check(r.ok, f"share of the calendar with {who} {r.text[:120]}")
r = Ca.post(B + "/api/events", json={"cal_id": C1, "title": "Cara's appointment", "start": f"{DAY}T10:00", "end": f"{DAY}T11:00"})
check(r.ok, "cara enters an appointment " + r.text[:120])
EV = r.json().get("id") or r.json().get("event", {}).get("id")
C2 = cal(An, "Read only circle")
An.put(B + f"/api/evcals/{C2}/members", json={"user_id": DORA, "role": "view"})
C3 = cal(An, "Alone")
assert A.patch(B + f"/api/users/{ERIK}", json={"disabled": True}).ok

# ---------------------------------------------------------------- address books
B1 = book(An, "Friends")
for who, role in ((DORA, "view"), (CARA, "edit"), (BERT, "edit")):
    assert An.put(B + f"/api/books/{B1}/members", json={"user_id": who, "role": role}).ok
# within one second the lower id wins: cara's share is made the older one, so the date is what decides here
write("UPDATE book_members SET added_at='2020-01-01T00:00:00Z' WHERE book_id=? AND user_id=?", (B1, CARA))
r = Be.post(B + "/api/contacts", json={"book_id": B1, "fn": "Olaf Example"})
check(r.ok, "bert enters a contact " + r.text[:120])
CT = r.json().get("id") or r.json().get("contact", {}).get("id")
B2 = book(An, "Read only book")
An.put(B + f"/api/books/{B2}/members", json={"user_id": DORA, "role": "view"})

# a book in a shared folder: the folder's edit share is the right to write, its view share lives on as a share of the book
F = An.post(B + "/api/contacts/folders", json={"name": "Shared books", "space": "private"})
check(F.ok, "a folder of address books " + F.text[:120])
BF = fid(F)
B3 = book(An, "In the folder")
r = An.post(B + "/api/files/refs", json={"ref_kind": "address_book", "ref_id": B3, "parent_id": BF})
check(r.ok, "filed in the folder " + r.text[:120])
assert An.post(B + f"/api/files/nodes/{BF}/shares", json={"user_id": DORA, "role": "view"}).ok
assert An.post(B + f"/api/files/nodes/{BF}/shares", json={"user_id": CARA, "role": "edit"}).ok

# ---------------------------------------------------------------- tables
S1 = sheet(An, "Budget")
COL = An.post(B + f"/api/sheets/{S1}/columns", json={"title": "Doc", "kind": "file"}).json()["column"]["id"]
ROW = An.get(B + f"/api/sheets/{S1}").json()["rows"][0]["id"]
r = An.post(B + f"/api/sheets/{S1}/files", data={"row_id": str(ROW), "col_id": str(COL)}, files={"file": ("manual.pdf", PDF, "application/pdf")})
check(r.ok, "a file in a cell " + r.text[:160])
FILE = r.json().get("id") or r.json().get("file", {}).get("id")
for who, role in ((DORA, "read"), (BERT, "write"), (CARA, "write")):
    assert An.post(B + f"/api/sheets/{S1}/shares", json={"user_id": who, "role": role}).ok
OLD_PATH = dbx("SELECT path FROM sheet_files WHERE id=?", (FILE,))[0][0]
S2 = sheet(An, "Read only table")
An.post(B + f"/api/sheets/{S2}/shares", json={"user_id": DORA, "role": "read"})
SF = An.post(B + "/api/sheets/folders", json={"name": "Shared tables", "space": "private"})
check(SF.ok, "a folder of tables " + SF.text[:120])
SFID = fid(SF)
S3 = sheet(An, "In the folder", folder_id=SFID)
assert An.post(B + f"/api/files/nodes/{SFID}/shares", json={"user_id": DORA, "role": "view"}).ok
assert An.post(B + f"/api/files/nodes/{SFID}/shares", json={"user_id": BERT, "role": "edit"}).ok

# ---------------------------------------------------------------- knowledge pages
BPLAN = page(Be, "Team/Plan", "Bert's own plan")
W = An.post(B + "/api/wiki/folders", json={"space": "private", "name": "Team"})
check(W.status_code == 201, "a knowledge folder " + W.text[:120])
WF = fid(W)
P1 = page(An, "Team/Plan", "Anna's plan, see [[Team/Notes]]")
P2 = page(An, "Team/Notes", "Notes by everybody")
P3 = page(An, "Lone", "Read by dora only")
P4 = page(An, "Mine alone", "Nobody else")
assert An.post(B + f"/api/files/nodes/{WF}/shares", json={"user_id": BERT, "role": "edit"}).ok
assert An.post(B + f"/api/files/nodes/{WF}/shares", json={"user_id": CARA, "role": "view"}).ok
assert An.post(B + "/api/wiki/shares", json={"page_id": P3, "kind": "person", "user_id": DORA}).ok
check(Be.patch(B + f"/api/wiki/pages/{P2}", json={"body": "Notes by everybody, bert too"}).ok, "bert writes through the folder")

# ---------------------------------------------------------------- the delete dialog
d = A.get(B + f"/api/users/{ANNA}/delete-info").json()
sh = d["purge"]["shared"]
check(sh["to"] == {"calendars": 1, "books": 2, "sheets": 2, "wiki": 2}, f"the dialog counts what is handed on: {sh['to']}")
check(sh["gone"] == {"calendars": 1, "books": 1, "sheets": 1, "wiki": 1}, f"and what goes because nobody may write: {sh['gone']}")
check(set(sh["names"]) == {"Bert", "Cara"}, f"and names who takes over: {sh['names']}")

# ---------------------------------------------------------------- a deletion that fails later leaves no copies behind (review)
stored = lambda: sorted(os.listdir(os.path.join(kt.DATA, "attachments", "sheets", str(S1))))  # noqa: E731
BEFORE = stored()
write(f"""CREATE FUNCTION p2508_no() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'no'; END $$ LANGUAGE plpgsql;
          CREATE TRIGGER p2508_no BEFORE DELETE ON users FOR EACH ROW WHEN (OLD.id={ANNA}) EXECUTE FUNCTION p2508_no()""")
r = A.delete(B + f"/api/users/{ANNA}")
check(r.status_code >= 500, f"the deletion fails at its last step ({r.status_code})")
check(owner("ev_cals", C1) == ANNA and owner("sheets", S1) == ANNA, "nothing changed hands")
check(stored() == BEFORE, f"and no sealed copy stays on the disk: {BEFORE} -> {stored()}")
write("DROP TRIGGER p2508_no ON users; DROP FUNCTION p2508_no()")

# an old state of a page nobody can open any more does not stop the deletion (review)
write("""INSERT INTO wiki_versions(page_id, owner_id, path, body, created_at, updated_at)
         VALUES(?, ?, 'Team/Plan', 'kenc1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', '2020-01-01', '2020-01-01')""", (P1, ANNA))

# ---------------------------------------------------------------- the deletion
r = A.delete(B + f"/api/users/{ANNA}")
check(r.ok, "the account goes " + r.text[:200])

check(owner("ev_cals", C1) == BERT, "the shared calendar: the longest-standing active person with edit (not the read-only or disabled one)")
check(not dbx("SELECT 1 FROM ev_cal_members WHERE cal_id=? AND user_id=?", (C1, BERT)), "the new owner has no share of its own")
check(dbx("SELECT role FROM ev_cal_members WHERE cal_id=? AND user_id=?", (C1, CARA))[0][0] == "edit", "cara keeps her share")
check(dbx("SELECT role FROM ev_cal_members WHERE cal_id=? AND user_id=?", (C1, DORA))[0][0] == "view", "dora keeps hers")
r = Ca.get(B + f"/api/events/{EV}")
check(r.ok, "cara's appointment is still there " + r.text[:120])
r = Be.patch(B + f"/api/evcals/{C1}", json={"name": "Family, now bert's"})
check(r.ok, "bert manages it as the owner " + r.text[:120])
check(Ca.patch(B + f"/api/evcals/{C1}", json={"name": "Not hers"}).status_code in (403, 404), "cara does not")
check(dbx("SELECT id FROM ev_cals WHERE owner_id=? ORDER BY sort, id LIMIT 1", (BERT,))[0][0] == BERT_DEFAULT, "bert's first calendar stays the first")
check(owner("ev_cals", C2) is None and owner("ev_cals", C3) is None, "read-only circle and unshared calendar go with the account")

check(owner("books", B1) == CARA, f"the shared book: the longest-standing edit share ({owner('books', B1)})")
check(Be.get(B + f"/api/contacts/{CT}").ok, "bert's contact is still there")
check(owner("books", B2) is None, "a read-only book goes")
check(owner("books", B3) == CARA, f"a book through the folder's edit share ({owner('books', B3)})")
check(dbx("SELECT role FROM book_members WHERE book_id=? AND user_id=?", (B3, DORA))[0][0] == "view", "the folder's read share lives on as a share of the book")
check(not dbx("SELECT 1 FROM fs_nodes WHERE ref_kind='address_book' AND ref_id=?", (B3,)), "the book's node left with the folder")

check(owner("sheets", S1) == BERT and owner("sheet_files", FILE) == BERT, "the shared table and its file: the longest-standing write share")
r = Be.get(B + f"/api/sheets/{S1}")
check(r.ok and r.json().get("can_write"), "bert opens and writes it")
r = Be.get(B + f"/api/sheets/{S1}/files/{FILE}")
check(r.ok and r.content == PDF, f"the file sealed for bert reads as before ({r.status_code})")
check(dbx("SELECT path FROM sheet_files WHERE id=?", (FILE,))[0][0] != OLD_PATH, "into a new stored file")
check(Ca.get(B + f"/api/sheets/{S1}").json().get("can_write"), "cara keeps her write share")
check(not dbx("SELECT 1 FROM sheet_shares WHERE sheet_id=? AND user_id=?", (S1, BERT)), "bert's own share row is gone")
check(owner("sheets", S2) is None, "a read-only table goes")
check(owner("sheets", S3) == BERT, "a table through the folder's edit share")
r = Do.get(B + f"/api/sheets/{S3}")
check(r.ok and not r.json().get("can_write"), "the folder's read share lives on as a share of the table")

check(owner("wiki_pages", P1) == BERT and owner("wiki_pages", P2) == BERT, "the pages somebody may write: to the person with the write share")
paths = {x[0]: x[1] for x in dbx("SELECT id, path FROM wiki_pages WHERE owner_id=?", (BERT,))}
check(paths[P1] == "Team/Plan (2)" and paths[BPLAN] == "Team/Plan" and paths[P2] == "Team/Notes", f"a taken name gets (2): {paths}")
r = Be.get(B + f"/api/wiki/pages/{P2}")
check(r.ok and r.json().get("body") == "Notes by everybody, bert too", "the text sealed for bert reads as before " + r.text[:120])
r = Ca.get(B + f"/api/wiki/shared/pages/{P2}")
check(r.ok and r.json().get("role") == "view", "cara still reads it " + r.text[:120])
check(owner("wiki_pages", P3) is None and owner("wiki_pages", P4) is None, "read-only and unshared pages go")
r = dbx("SELECT body FROM wiki_pages WHERE id=?", (P2,))[0][0]
check(r.startswith("kenc1:"), "the text is sealed for its new owner, not lying open")
check(not dbx("SELECT 1 FROM wiki_versions WHERE page_id=? AND body LIKE 'kenc1:AAAA%'", (P1,)), "the unreadable old state went")
check(not dbx("SELECT 1 FROM users WHERE id=?", (ANNA,)), "and the account is gone")

# ---------------------------------------------------------------- 2.537.0 (#4347): shared branches of the file store
def folder(s, name, parent=None):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": "private"})})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(s, name, data, parent):
    r = s.post(B + "/api/files/upload", data={"parent_id": str(parent)}, files={"file": (name, data)})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["id"]


def text_pdf(line):
    """A one-page PDF with a text layer (hand-written, as in p296_e_api_test.py)."""
    stream = f"BT /F1 12 Tf 60 740 Td ({line}) Tj ET".encode("latin-1")
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
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def node(nid):
    r = dbx("SELECT owner_id, parent_id, name FROM fs_nodes WHERE id=?", (nid,))
    return tuple(r[0]) if r else None


def share_of(nid, u):
    r = dbx("SELECT role FROM fs_shares WHERE node_id=? AND user_id=?", (nid, u))
    return r[0][0] if r else None


def stored(nid):
    return [x[0] for x in dbx("SELECT path FROM fs_versions WHERE node_id=? ORDER BY no", (nid,))]


def settled(nid):
    """The recognition of file nid is over (a running one would make the deletion answer 409)."""
    return until(lambda: not dbx("SELECT 1 FROM file_text WHERE kind='fs' AND node_id=? AND state IN ('wait', 'run')", (nid,))
                 and not dbx("SELECT 1 FROM doc_meta WHERE node_id=? AND state IN ('wait', 'run')", (nid,)), 120)


def recognised(nid, uid):
    """2.537.0 (#4347, review 1): mark file nid as a recognised document with values (doc_meta.extracted), as every recognition
    with a date and an amount does."""
    check(settled(nid), f"the recognition of {nid} is over")
    write("INSERT INTO doc_meta(node_id, ws, state, extracted, doc_date, created_at, updated_at) VALUES(?,?,'done',?,?,?,?) "
          "ON CONFLICT(node_id) DO UPDATE SET state='done', extracted=excluded.extracted, doc_date=excluded.doc_date",
          (nid, f"u{uid}", '{"gross": "11.90", "currency": "EUR"}', "2026-02-01", "2026-02-01T00:00:00Z", "2026-02-01T00:00:00Z"))


def group_share(nid, g):
    r = dbx("SELECT role FROM fs_shares WHERE node_id=? AND group_id=?", (nid, g))
    return r[0][0] if r else None


OLGA, Ol = person("olga")
PIA, Pi = person("pia")
QUIN, Qu = person("quin")
RUTH, Ru = person("ruth")
SAM, Sa = person("sam")
folder(Pi, "Garden plans")  # the heir's own folder of that name: the branch gets " (2)"
GP = folder(Ol, "Garden plans")
DR = folder(Ol, "Drawings", GP)
V1, V2 = text_pdf("Rhubarbfield first layout"), text_pdf("Rhubarbfield second layout")
PLAN = upload(Ol, "plan.pdf", V1, DR)
check(Ol.post(B + f"/api/files/nodes/{PLAN}/versions", files={"file": ("plan.pdf", V2, "application/pdf")}).status_code == 201, "a second version")
for nid, who, role in ((GP, QUIN, "edit"), (GP, PIA, "edit"), (GP, RUTH, "view"), (DR, SAM, "view"), (DR, PIA, "view")):
    check(Ol.post(B + f"/api/files/nodes/{nid}/shares", json={"user_id": who, "role": role}).status_code == 201, f"share {nid} with {who}")
write("UPDATE fs_shares SET created_at='2020-01-01T00:00:00Z' WHERE node_id=? AND user_id=?", (GP, PIA))  # pia's edit share is the older one
QNOTE = b"Quin's notes on the beds"
QF = upload(Qu, "quin.txt", QNOTE, GP)  # a contribution of another person
check(node(QF)[0] == OLGA, "a file added to the shared folder is the folder owner's node")
ft = until(lambda: (lambda r: r and r[0][0] in ("found", "none", "skip", "error") and r[0][0])(
    dbx("SELECT state FROM file_text WHERE kind='fs' AND node_id=?", (PLAN,))), 120)
check(ft == "found", f"the text of the file is recognised ({ft})")
BEFORE = stored(PLAN)
# read only on top, an edit share on a folder inside it: that folder goes on its own, the read share lives on on it
RO = folder(Ol, "Read-only")
ROF = upload(Ol, "ro.txt", b"only read", RO)
INNER = folder(Ol, "Inner", RO)
INF = upload(Ol, "inner.txt", b"inner text", INNER)
check(Ol.post(B + f"/api/files/nodes/{RO}/shares", json={"user_id": RUTH, "role": "view"}).status_code == 201, "read share")
check(Ol.post(B + f"/api/files/nodes/{INNER}/shares", json={"user_id": SAM, "role": "edit"}).status_code == 201, "edit share inside")
LONE = folder(Ol, "Viewed")
check(Ol.post(B + f"/api/files/nodes/{LONE}/shares", json={"user_id": SAM, "role": "view"}).status_code == 201, "a read-only folder")
# review #4347 (1): recognised documents in a branch, and a recognised file shared on its own, are handed on (not left to go)
BILL = upload(Ol, "bill.pdf", text_pdf("Rhubarbfield bill"), DR)
recognised(BILL, OLGA)
LOOSE = folder(Ol, "Loose")
DEED = upload(Ol, "deed.pdf", text_pdf("Rhubarbfield deed"), LOOSE)
recognised(DEED, OLGA)
check(Ol.post(B + f"/api/files/nodes/{DEED}/shares", json={"user_id": SAM, "role": "edit"}).status_code == 201, "a file shared on its own")
# review #4347 (2, 3): a group's share of the folder above stays the group's; an expired row of somebody who keeps a role is replaced
TEAM = A.post(B + "/api/admin/groups", json={"name": "Crew", "members": [QUIN, SAM]}).json()["id"]
PRJ = folder(Ol, "Projects")
PL = folder(Ol, "Plans", PRJ)
PLF = upload(Ol, "plans.txt", b"the plans", PL)
write("INSERT INTO fs_shares(node_id, group_id, role, created_by, created_at) VALUES(?,?,'view',?,?)",  # a group of the instance (the
      (PRJ, TEAM, OLGA, "2026-02-01T00:00:00Z"))  # share dialog offers people without an organisation none)
check(Qu.get(B + f"/api/files/nodes/{PLF}/content").ok, "a group's read share: quin reads the plans")
check(Ol.post(B + f"/api/files/nodes/{PRJ}/shares", json={"user_id": RUTH, "role": "view"}).status_code == 201, "a person's read share")
for who, role in ((PIA, "edit"), (RUTH, "view")):
    check(Ol.post(B + f"/api/files/nodes/{PL}/shares", json={"user_id": who, "role": role}).status_code == 201, f"share of plans with {who}")
write("UPDATE fs_shares SET expires_at='2020-01-01T00:00:00Z' WHERE node_id=? AND user_id=?", (PL, RUTH))  # ruth's own row there ran out
# review #4347 (4): a public link and a file request somebody else set on the branch end with it
write("INSERT INTO fs_ext_links(node_id, created_by, token_hash, token, created_at) VALUES(?,?,?,?,?)",
      (PLAN, QUIN, "p4347-hash", "p4347-token", "2026-02-01T00:00:00Z"))
write("""INSERT INTO fs_upload_requests(node_id, created_by, token, token_hash, title, expires_at, created_at)
         VALUES(?,?,?,?,?,?,?)""", (GP, QUIN, "p4347-req", "p4347-req-hash", "For the beds", "2099-01-01T00:00:00Z", "2026-02-01T00:00:00Z"))
for n in (PLAN, BILL, DEED, PLF, QF):
    check(settled(n), f"nothing is being recognised in {n}")

sh = A.get(B + f"/api/users/{OLGA}/delete-info").json()["purge"]["shared"]
# 2.537.0 (#4347, review): the recognised file on its own and the plans count as handed on, the projects (read only) as gone
check(sh["to"] == {"folders": 4} and sh["gone"] == {"folders": 3}, f"the dialog counts the branches handed on and those that go: {sh}")
check(set(sh["names"]) == {"Pia", "Sam"}, f"and names who takes them over: {sh['names']}")
r = A.delete(B + f"/api/users/{OLGA}")
check(r.ok, "olga's account goes " + r.text[:200])

check(node(GP) == (PIA, None, "Garden plans (2)"), f"the branch: to the oldest edit share, at the top of her tree ({node(GP)})")
check(node(DR)[0] == PIA and node(PLAN)[0] == PIA and node(QF)[0] == PIA, "with everything in it, the contribution of another included")
r = Pi.get(B + f"/api/files/nodes/{PLAN}/content")
check(r.ok and r.content == V2, f"the file sealed for pia reads as before ({r.status_code})")
r = Pi.get(B + f"/api/files/nodes/{PLAN}/content", params={"v": 1})
check(r.ok and r.content == V1, f"its first version too ({r.status_code})")
AFTER = stored(PLAN)
check(len(AFTER) == 2 and not set(AFTER) & set(BEFORE), f"into new stored files: {BEFORE} -> {AFTER}")
check(until(lambda: not [p for p in BEFORE if os.path.exists(os.path.join(kt.DATA, "attachments", p))], 10), "the old ones are removed")
check(dbx("SELECT ws FROM file_text WHERE kind='fs' AND node_id=?", (PLAN,))[0][0] == f"u{PIA}", "the recognised text belongs to pia's workspace")
r = Pi.get(B + "/api/files/search", params={"q": "rhubarbfield"})
check(r.ok and PLAN in [x["id"] for x in r.json()["items"]], "and pia finds the file by its text " + r.text[:160])
r = Qu.get(B + f"/api/files/nodes/{QF}/content")
check(r.ok and r.content == QNOTE, f"quin still reads his file ({r.status_code})")
check(share_of(GP, QUIN) == "edit" and share_of(GP, RUTH) == "view", "the shares of the others stay")
check(share_of(DR, SAM) == "view", "a share inside the branch stays too")
check(share_of(GP, PIA) is None and share_of(DR, PIA) is None, "pia's own share rows are gone")
check(Ru.get(B + f"/api/files/nodes/{PLAN}/content").ok, "ruth reads through the folder as before")
r = Qu.post(B + "/api/files/upload", data={"parent_id": str(GP)}, files={"file": ("more.txt", b"more")})
check(r.status_code == 201, "quin still adds files " + r.text[:120])
check(Ru.post(B + "/api/files/upload", data={"parent_id": str(GP)}, files={"file": ("no.txt", b"no")}).status_code in (403, 404), "ruth does not")

check(node(INNER) == (SAM, None, "Inner"), f"the inner folder with the edit share: to sam ({node(INNER)})")
r = Sa.get(B + f"/api/files/nodes/{INF}/content")
check(r.ok and r.content == b"inner text", "sam reads its file")
check(share_of(INNER, RUTH) == "view", "the read share of the folder above lives on as a share of it")
check(node(RO) is None and node(ROF) is None and node(LONE) is None, "what only others read goes with the account")

# review #4347 (1, 8): the recognised documents went along, their data sealed for the heir
check(node(BILL) == (PIA, DR, "bill.pdf"), f"the recognised document in the branch: pia's ({node(BILL)})")
r = Pi.get(B + f"/api/files/nodes/{BILL}/content")
check(r.ok and r.content.startswith(b"%PDF"), f"pia reads it ({r.status_code})")
m = dbx("SELECT ws, extracted FROM doc_meta WHERE node_id=?", (BILL,))
check(m and m[0][0] == f"u{PIA}" and m[0][1], f"its document data belong to pia's workspace ({m and m[0][0]})")
check(node(DEED) == (SAM, None, "deed.pdf"), f"the recognised file shared on its own: to sam ({node(DEED)})")
check(Sa.get(B + f"/api/files/nodes/{DEED}/content").ok, "sam reads it")
check(node(PRJ) is None, "the projects folder (read only) goes")
# review #4347 (2): the group keeps its role as the group's share, no row per member
check(node(PL) == (PIA, None, "Plans"), f"the plans: to pia ({node(PL)})")
check(group_share(PL, TEAM) == "view", "the group's share of the folder above became the group's share of the branch")
check(share_of(PL, QUIN) is None and share_of(PL, SAM) is None, "no share row per member of the group")
check(Qu.get(B + f"/api/files/nodes/{PLF}/content").ok, "quin reads through the group")
check(A.patch(B + f"/api/admin/groups/{TEAM}", json={"members": [SAM]}).ok, "quin leaves the group")
check(Qu.get(B + f"/api/files/nodes/{PLF}/content").status_code in (403, 404), "and no longer reads it")
# review #4347 (3): ruth's expired row was replaced by a live one
r = dbx("SELECT role, expires_at FROM fs_shares WHERE node_id=? AND user_id=?", (PL, RUTH))
check(r == [("view", None)], f"ruth's expired row is replaced by a live one ({r})")
check(Ru.get(B + f"/api/files/nodes/{PLF}/content").ok, "ruth reads the plans as before")
# review #4347 (4): another person's public link and file request on the branch end
check(not dbx("SELECT 1 FROM fs_ext_links WHERE node_id=?", (PLAN,)), "quin's public link on the file ended")
check(dbx("SELECT revoked_at FROM fs_upload_requests WHERE token_hash='p4347-req-hash'")[0][0], "quin's file request ended")

# ---------------------------------------------------------------- never into a knowledge space with the lock (review)
JANA, Ja = person("jana")
IVO, Iv = person("ivo")
KURT, Ku = person("kurt")
LF1 = fid(Ja.post(B + "/api/wiki/folders", json={"space": "private", "name": "Both"}))
LF2 = fid(Ja.post(B + "/api/wiki/folders", json={"space": "private", "name": "Only ivo"}))
L1 = page(Ja, "Both/One", "For ivo and kurt")
L2 = page(Ja, "Only ivo/Two", "For ivo")
for f, who in ((LF1, IVO), (LF1, KURT), (LF2, IVO)):
    assert Ja.post(B + f"/api/files/nodes/{f}/shares", json={"user_id": who, "role": "edit"}).ok
write("DELETE FROM wiki_spaces WHERE owner_id=?", (IVO,))
write("INSERT INTO wiki_spaces(owner_id, e2e, e2e_gen) VALUES(?, 'on', 1)", (IVO,))
sh = A.get(B + f"/api/users/{JANA}/delete-info").json()["purge"]["shared"]
check(sh["to"] == {"wiki": 1} and sh["gone"] == {"wiki": 1}, f"the dialog counts it so: {sh}")
assert A.delete(B + f"/api/users/{JANA}").ok
check(owner("wiki_pages", L1) == KURT, "the next person with the right takes it")
check(owner("wiki_pages", L2) is None, "nobody else: it goes")

# ---------------------------------------------------------------- an agent never takes over
FA, Fa = person("fina")
GUS, Gu = person("gus")
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok
AG = Fa.post(B + "/api/my/agents", json={"username": "helper", "display_name": "Helper", "scopes": ["read"]})
check(AG.ok, "an agent " + AG.text[:120])
C5 = cal(Fa, "With an agent")
r = Fa.put(B + f"/api/evcals/{C5}/members", json={"user_id": AG.json()["id"], "role": "edit"})
check(r.ok, "shared with the agent " + r.text[:120])
sh = A.get(B + f"/api/users/{FA}/delete-info").json()["purge"]["shared"]
check(not sh["to"] and not sh["gone"], f"an agent's share counts for nothing: {sh}")
assert A.delete(B + f"/api/users/{FA}").ok
check(owner("ev_cals", C5) is None, "and the agent does not take it over")

# ---------------------------------------------------------------- an organisation's admin hears numbers, no names
r = A.post(B + "/api/admin/orgs", json={"name": "Example Studio", "admin_id": GUS})
check(r.ok, "an organisation " + r.text[:120])
ORG = r.json()["id"]
Gu.post(B + f"/api/orgs/{ORG}/join")
r = A.post(B + "/api/users", json={"username": "hans", "display_name": "Hans", "password": "password123", "email": "hans@example.com",
                                   "orgs": [{"id": ORG, "role": "member"}]})
check(r.ok, "a member " + r.text[:120])
HANS, Ha = r.json()["id"], sess("hans")
Ha.post(B + f"/api/orgs/{ORG}/join")
Ha.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
C6 = cal(Ha, "Private of hans")
assert dbx("SELECT org_id FROM ev_cals WHERE id=?", (C6,))[0][0] is None
r = Ha.put(B + f"/api/evcals/{C6}/members", json={"user_id": GUS, "role": "edit"})
check(r.ok, "shared with the admin " + r.text[:120])
d = Gu.get(B + f"/api/users/{HANS}/delete-info")
check(d.ok and d.json().get("can_delete"), "the organisation's admin may delete it " + d.text[:160])
sh = d.json()["purge"]["shared"]
check(sh["to"] == {"calendars": 1} and sh["names"] == [], f"numbers, no names: {sh}")

sys.exit(kt.done("p2508_share_heir"))
