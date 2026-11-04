#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.508.0 (#4301): deleting an account no longer takes what it shares privately with it. A private calendar, address book,
table (with its files) and the knowledge pages somebody may write pass to the longest-standing person with the right to
write, with what the others wrote; shares through a folder count like shares of the object. Nobody to take over: the object
goes and the delete dialog says so. People without an organisation throughout (freelancer-matrix: pim  freelancer-matrix: sheets
freelancer-matrix: wiki); the organisation admin's dialog names nobody. Invented names only, sealed with a server key.
usage: p2508_share_heir_test.py <datadir>"""
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from kt import B, check, dbx, sess  # noqa: E402

kt.fresh({"KALMIDO_ORGCRYPT_DELAY": "0", "KALMIDO_SECRET_KEY": base64.b64encode(os.urandom(32)).decode()})
A = kt.setup()
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en"})
FEAT = "cal,comments,collab,events,files,docs,sheets,wiki,contacts"
PDF = b"%PDF-1.4 a small manual"
DAY = "2030-03-04"


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
c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"))
c.execute("UPDATE book_members SET added_at='2020-01-01T00:00:00Z' WHERE book_id=? AND user_id=?", (B1, CARA))
c.commit()
c.close()
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
check(not dbx("SELECT 1 FROM users WHERE id=?", (ANNA,)), "and the account is gone")

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
