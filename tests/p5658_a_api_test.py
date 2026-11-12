#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1071.0 (#5658, decision of #5643): a project, a folder of projects and a knowledge page shared by e-mail address bind only
an account that proved the address (core/access.py addr_account); without one the share stays open (core/addrshare.py,
obj_addr_shares) and is made when the account of that address signs in with the address proved -- as the person who typed it
in, with the rights of that moment. The open share is listed (the address, "invited") and can be taken back. Invented people
and titles only, everyone a person without an organisation.
freelancer-matrix: lists, wiki, sheets
 - the answer stays the one of an unknown address; nothing binds before the proof, not even at a sign-in
 - the Share dialogs: GET /api/addr-shares (project, folder), the knowledge dialog lists the open share as a card (Fable 2.965
   F2: a card for a proved account and none for an unproved one told the difference), DELETE takes it back, others get 404
 - proved + signed in: member of the project, the folder's projects, the page under "Shared with me"; the open rows are gone
 - a project in the trash before the proof: nothing is made, the open row goes
 - Fable 2.983 N2: PATCH of a table's address row bound before the proof counted does not lift that account's role
usage: p5658_a_api_test.py <datadir>      (KMT_NOSTART=1 / P5658A_NOSTART=1: a running server)"""
import sys

from freelancer_fixture import freelancer
from kt import B, check, dbx, done, fresh, sess, setup

fresh(env={"KALMIDO_API_RATE": "5000"}, prefix="P5658A")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FEAT = "sheets,wiki,files,cal,comments,collab"

FID, F = freelancer(B, A, "frida", features=FEAT)
# uma's and vera's accounts were made by the server's admin with the address typed in: nobody proved them yet
UID, U = freelancer(B, A, "uma", features=FEAT)
VID, V = freelancer(B, A, "vera", features=FEAT)


def sees(s, lid):
    return lid in {x["id"] for x in s.get(B + "/api/state").json()["lists"]}


def member(lid, uid):
    return bool(dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)))


def open_rows(kind=None):
    q = "SELECT kind, ref_id, path, created_by FROM obj_addr_shares" + (" WHERE kind=?" if kind else "") + " ORDER BY id"
    return dbx(q, (kind,) if kind else ())


def wiki_shared(s):
    return {x["path"] for x in s.get(B + "/api/wiki/shared").json().get("pages", [])}


def project(name, folder=None):
    r = F.post(B + "/api/lists", json={"name": name, "kind": "project", **({"folder": folder} if folder else {})})
    assert r.ok, r.text
    return r.json()["id"]


check(dbx("SELECT email_proved FROM users WHERE id=?", (UID,))[0][0] == "", "(setup) uma's address is not proved")

# ================================================================ a project by address: open, listed, the same answer
LA = project("Moodboard for Uma")
r = F.put(B + f"/api/lists/{LA}/members", json={"email": "uma@example.com", "role": "view"})
r2 = F.put(B + f"/api/lists/{LA}/members", json={"email": "nobody@example.com", "role": "edit"})
check(r.ok and r2.ok and r.json() == r2.json() == {"ok": True, "by_email": True},
      f"#5658: a project by an unproved address: the answer of an unknown address {r.status_code} {r.text[:160]}")
check(not member(LA, UID) and not sees(U, LA), "#5658: before the proof uma is NOT a member")
check(len(open_rows("list")) == 2, f"#5658: two open shares of the project (uma's and the unknown address) {open_rows('list')}")
j = F.get(B + f"/api/addr-shares?kind=list&ref={LA}").json()
check(sorted(x["email"] for x in j.get("open", [])) == ["nobody@example.com", "uma@example.com"]
      and all(x["state"] == "invited" for x in j["open"]), f"#5658: the Share dialog lists both addresses as invited {j}")
check(U.get(B + f"/api/addr-shares?kind=list&ref={LA}").status_code == 404, "#5658: who does not manage the project sees no open shares")
r = F.put(B + f"/api/lists/{LA}/members", json={"email": "UMA@example.com ", "role": "view"})
check(len(open_rows("list")) == 2, "#5658: the same address again (case, blanks): still one open share for it")

# ================================================================ a folder of projects by address
LF = project("Shoot plan", "Clients")
r = F.put(B + "/api/folders/people", json={"folder": "Clients", "email": "uma@example.com", "role": "edit"})
check(r.ok and r.json() == {"shared": 0, "updated": 0, "by_email": True}, f"#5658: a folder by an unproved address: the address answer {r.text[:160]}")
check(not sees(U, LF), "#5658: before the proof uma does NOT see the folder's project")
j = F.get(B + "/api/addr-shares?kind=list_folder&folder=Clients").json()
check([x["email"] for x in j.get("open", [])] == ["uma@example.com"], f"#5658: the folder's Share dialog lists the open share {j}")
r = F.put(B + "/api/folders/people", json={"folder": "No such folder", "email": "uma@example.com", "role": "edit"})
check(r.ok and len(open_rows("list_folder")) == 1, "#5658: a folder that does not exist keeps no open share")

# ================================================================ a knowledge page by address (Fable 2.965 F2)
r = F.post(B + "/api/wiki/pages", json={"space": "private", "path": "Offer for Uma", "body": "the offer text"})
assert r.status_code == 201, r.text
W1 = r.json()["id"]
r = F.post(B + "/api/wiki/shares", json={"page_id": W1, "kind": "person", "email": "uma@example.com"})
r2 = F.post(B + "/api/wiki/shares", json={"page_id": W1, "kind": "person", "email": "nobody@example.com"})
check(r.ok and r2.ok and r.json() == r2.json() == {"ok": True, "by_email": True},
      f"#5658: a page by address: the answer of an unknown address {r.status_code} {r.text[:160]}")
check("Offer for Uma" not in wiki_shared(U), "#5658: before the proof uma does NOT read the page")
ppl = [s for s in F.get(B + f"/api/wiki/shares?page={W1}").json()["shares"] if s["kind"] == "person"]
check(sorted(s["user"]["name"] for s in ppl) == ["nobody@example.com", "uma@example.com"] and all(s["user"]["by_email"] for s in ppl),
      f"#5658 (F2): the dialog shows a card per address typed in, account or not {ppl}")
NOB = next(s for s in ppl if s["user"]["name"] == "nobody@example.com")
check(F.patch(B + f"/api/wiki/shares/{NOB['id']}", json={"images": True}).ok
      and next(s for s in F.get(B + f"/api/wiki/shares?page={W1}").json()["shares"] if s["id"] == NOB["id"])["images"],
      "#5658: an open page share takes the switch Show pictures")
check(U.delete(B + f"/api/wiki/shares/{NOB['id']}").status_code == 404, "#5658: another person cannot take back frida's open page share")
check(F.post(B + f"/api/wiki/shares/{NOB['id']}/restore").status_code == 404, "#5658: an open share has no restore (it is no link)")
check(F.delete(B + f"/api/wiki/shares/{NOB['id']}").ok and NOB["id"] not in {s["id"] for s in F.get(B + f"/api/wiki/shares?page={W1}").json()["shares"]},
      "#5658: frida takes the open page share back")

# ================================================================ taking an open share of a project back
NOBL = next(x["id"] for x in F.get(B + f"/api/addr-shares?kind=list&ref={LA}").json()["open"] if x["email"] == "nobody@example.com")
check(U.delete(B + f"/api/addr-shares/{NOBL}").status_code == 404, "#5658: who does not manage the project cannot take it back (404)")
check(F.delete(B + f"/api/addr-shares/{NOBL}").ok and [x["email"] for x in F.get(B + f"/api/addr-shares?kind=list&ref={LA}").json()["open"]] == ["uma@example.com"],
      "#5658: frida takes the open share of the unknown address back")

# ================================================================ a project in the trash before the proof: nothing comes of it
LT = project("Old draft")
F.put(B + f"/api/lists/{LT}/members", json={"email": "uma@example.com", "role": "edit"})
check(F.patch(B + f"/api/lists/{LT}", json={"archived": True}).ok and F.delete(B + f"/api/lists/{LT}").ok,
      "(setup) the project is archived and deleted (deleting only from the archive)")

# ================================================================ review F1: a folder renamed before the proof - the open share follows
LS2 = project("Lookbook", "Studio")
F.put(B + "/api/folders/people", json={"folder": "Studio", "email": "uma@example.com", "role": "view"})
check(F.post(B + "/api/folders/rename", json={"old": "Studio", "new": "Studio Two"}).ok, "(setup) the folder is renamed")
j = F.get(B + "/api/addr-shares?kind=list_folder&folder=Studio Two").json()
check([x["email"] for x in j.get("open", [])] == ["uma@example.com"], f"#5658 (F1): the open share follows the renamed folder {j}")

# ================================================================ a sign-in without the proof takes nothing
U = sess("uma")
check(not member(LA, UID) and not sees(U, LF) and "Offer for Uma" not in wiki_shared(U),
      "#5658: a sign-in with the address NOT proved takes nothing")
check(len(open_rows()) == 5, f"#5658: ... the open shares stay {open_rows()}")

# ================================================================ proved + signed in: the shares are made
dbx("UPDATE users SET email_proved='uma@example.com' WHERE id=?", (UID,))  # (a mailed link or a verified OIDC claim)
U = sess("uma")
check(member(LA, UID) and sees(U, LA), "#5658: proved: the next sign-in makes uma a member of the project")
check(dbx("SELECT role FROM list_members WHERE list_id=? AND user_id=?", (LA, UID)) == [("view",)],
      "#5658: ... with the role frida chose")
check(sees(U, LF), "#5658: proved: uma sees the project in the shared folder")
check("Offer for Uma" in wiki_shared(U) and U.get(B + f"/api/wiki/shared/pages/{W1}").status_code == 200,
      "#5658: proved: uma reads the page")
check(not member(LT, UID), "#5658: the project in the trash is not shared")
check(sees(U, LS2) and dbx("SELECT role FROM list_members WHERE list_id=? AND user_id=?", (LS2, UID)) == [("view",)],
      "#5658 (F1): the renamed folder is shared under its new name, with the role chosen")
check(open_rows() == [], f"#5658: every open share of uma's address is gone (made, or its project gone) {open_rows()}")
ppl = [s for s in F.get(B + f"/api/wiki/shares?page={W1}").json()["shares"] if s["kind"] == "person"]
check([s["user"]["name"] for s in ppl] == ["uma@example.com"], f"#5658 (F2): the page's card still shows the address, not the account {ppl}")
check(F.get(B + f"/api/addr-shares?kind=list&ref={LA}").json()["open"] == [], "#5658: the project's dialog has no open share left")
news = [n for n in U.get(B + "/api/news").json().get("items", []) if n.get("kind") in ("share", "wiki_shared")]
check(len(news) >= 2, f"#5658: uma gets the News items of the shares {[(n.get('kind'), n.get('list_id')) for n in news]}")

# ================================================================ review F2 / F3: an organisation's project
r = A.post(B + "/api/orgs", json={"name": "Example Lantern Studio"})
assert r.ok, r.text
OID = r.json()["id"]
r = A.post(B + "/api/lists", json={"name": "Example Studio Wall", "org_id": OID})
assert r.ok, r.text
PO = r.json()["id"]
r = A.post(B + "/api/users", json={"orgs": [{"id": OID, "role": "member"}], "username": "olga", "display_name": "Olga",
                                   "password": "password123", "email": "olga@example.com"})
assert r.ok, r.text
OLGA = r.json()["id"]
r = A.put(B + f"/api/lists/{PO}/members", json={"email": "olga@example.com", "role": "edit"})
check(r.ok and r.json() == {"ok": True, "by_email": True} and not member(PO, OLGA), "#5658: an organisation's project by an unproved address: open")
check(dbx("SELECT org_id FROM obj_addr_shares WHERE kind='list' AND ref_id=?", (PO,)) == [(OID,)], "#5658: the open share carries the organisation")
# F3: uma's address is proved, but she is no member of the organisation: the dialog shows her like an unknown address
r = A.put(B + f"/api/lists/{PO}/members", json={"email": "uma@example.com", "role": "edit"})
r2 = A.put(B + f"/api/lists/{PO}/members", json={"email": "nobody@example.com", "role": "edit"})
check(r.ok and r.json() == r2.json() and not member(PO, UID), "#5658 (F3): proved, but outside the organisation: the answer of an unknown address")
check(sorted(x["email"] for x in A.get(B + f"/api/addr-shares?kind=list&ref={PO}").json()["open"])
      == ["nobody@example.com", "olga@example.com", "uma@example.com"], "#5658 (F3): ... and the dialog lists her like an unknown address")
dbx("UPDATE users SET email_proved='olga@example.com' WHERE id=?", (OLGA,))
sess("olga")
check(member(PO, OLGA), "#5658 (F2): proved: olga becomes a member of the organisation's project at her sign-in")
check(len(dbx("SELECT 1 FROM obj_addr_shares WHERE kind='list' AND ref_id=?", (PO,))) == 2, "#5658: ... her open share is gone, the others stay")

# ================================================================ Fable 2.983 N2: PATCH of an address row bound before the proof counted
dbx("UPDATE users SET email_proved='' WHERE id=?", (VID,))
dbx("UPDATE users SET email_proved='vera@example.com' WHERE id=?", (VID,))  # proved for the share ...
r = F.post(B + "/api/sheets", json={"title": "Rates for Vera", "space": "private"})
assert r.status_code == 201, r.text
TV = r.json()["id"]
check(F.post(B + f"/api/sheets/{TV}/shares", json={"email": "vera@example.com", "role": "read"}).status_code == 201
      and V.get(B + f"/api/sheets/{TV}").status_code == 200, "(setup) the table is shared with vera's proved address")
dbx("UPDATE users SET email_proved='' WHERE id=?", (VID,))  # ... and as if it had been bound before 2.983 (nobody proved it)
row = next(s for s in F.get(B + f"/api/sheets/{TV}/shares").json()["shares"] if s.get("email") == "vera@example.com")
r = F.patch(B + f"/api/sheets/{TV}/shares/{row['id']}", json={"role": "write"})
check(r.ok, f"(setup) PATCH answers {r.status_code} {r.text[:120]}")
check(V.patch(B + f"/api/sheets/{TV}", json={"title": "Changed by Vera"}).status_code in (403, 404)
      and dbx("SELECT user_id FROM sheet_shares WHERE sheet_id=? AND email_key!=''", (TV,)) == [(None,)],
      "#5658 (N2): the role is not lifted for an account whose address nobody proved; the address row is open again")
check(dbx("SELECT title FROM sheets WHERE id=?", (TV,)) == [("Rates for Vera",)], "#5658 (N2): ... and vera changed nothing")

sys.exit(done("p5658_a_api"))
