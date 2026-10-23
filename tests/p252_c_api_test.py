#!/usr/bin/env python3
"""2.52.0 API tests, part C (#1438): address books an organisation owns. Invented names only.
 - hand-over: only the owner of a person's book in an organisation's workspace who is an admin of it (a member: 403, a
   private book / a mirrored one: 409), nothing moves by itself (a new book stays personal)
 - roles: org admins manage (role owner), members read / change / see nothing as org_role says (view | edit | none), a
   share adds to that; another organisation and a person without one see nothing (404), also through search
 - role change member -> admin -> member of the manager: the rights follow the organisation role, not owner_id
 - the manager leaves the organisation / the manager's account is deleted: the book stays with its contacts, its birthday
   list (occ_list_id) and the links to tasks; another admin manages it; the leaver no longer sees it
 - workspace: an organisation's book cannot leave its workspace (409)
 - agents: an agent of the organisation sees the book only when it is shared with it (as before)
 - CardDAV: PROPFIND lists the organisation's book for a member; PUT only with edit
 - way back: an admin makes it personal again (their own; members keep only shares), then hands it over again (undo)
tenant-matrix: book
usage: p252_c_api_test.py <datadir>      (a fresh container)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,collab,comments,events,contacts,family"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def book(s, bid):
    return next((b for b in s.get(B + "/api/books").json()["items"] if b["id"] == bid), None)


VCARD = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{u}\r\nFN:{n}\r\nN:{n};;;;\r\nEND:VCARD\r\n"


def dav(user, pw, m, path, body=None, **h):
    return requests.request(m, B + path, auth=(user, pw), data=body.encode() if body else None, headers=h, allow_redirects=False)


if not os.environ.get("P252_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code == 201, r.text
ALPHA = r.json()["id"]
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = (ids[k] for k in ("bob", "carol", "dave", "erin"))
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": DAVE})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
check(A.patch(B + f"/api/admin/orgs/{ALPHA}", json={"members": [1, BOB, CAROL, ERIN], "admins": [1]}).ok, "setup: Alpha members")
A.patch(B + f"/api/admin/orgs/{BETA}", json={"members": [DAVE], "admins": [DAVE]})
S = {u: sess(u) for u in ("alice", "bob", "carol", "dave", "erin")}
A = S["alice"]
for s in S.values():
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": "all"})

# ---- bob's book in Alpha's workspace, a contact, a list for the birthdays, a task linked to the contact
r = S["bob"].post(B + "/api/books", json={"name": "Suppliers", "org_id": ALPHA})
check(r.status_code == 201, f"bob creates a book in Alpha ({r.status_code} {r.text[:200]})")
BK = r.json()["id"]
check(r.json()["org_owned"] is False and r.json()["can_org"] is False, "a new book is personal; bob (member) may not hand it over")
r = S["bob"].post(B + "/api/contacts", json={"book_id": BK, "given": "Petra", "family": "Supply", "bday": "1980-05-12"})
check(r.status_code == 201, f"bob adds a contact ({r.status_code} {r.text[:200]})")
CT = r.json()["id"]
r = S["bob"].post(B + "/api/lists", json={"name": "Birthdays Alpha", "org_id": ALPHA})
check(r.ok, f"bob creates an Alpha list ({r.status_code} {r.text[:200]})")
LB = r.json()["id"]
check(S["bob"].patch(B + f"/api/books/{BK}", json={"birthdays_list_id": LB}).ok, "bob: birthdays into the Alpha list")
r = S["bob"].post(B + "/api/tasks", json={"title": "Order paper", "list_id": LB})
TK = r.json()["id"]
check(S["bob"].post(B + f"/api/tasks/{TK}/contacts", json={"contact_id": CT, "kind": "about"}).ok, "bob links the contact to a task")

# ---- hand-over: members no, admins yes
r = S["bob"].post(B + f"/api/books/{BK}/org", json={})
check(r.status_code == 403, f"bob (member) cannot hand it over ({r.status_code})")
check(S["carol"].post(B + f"/api/books/{BK}/org", json={}).status_code == 404, "carol (not shared) does not even see it")
check(book(S["carol"], BK) is None, "carol: not in her books before the hand-over")
r = A.put(B + f"/api/orgs/{ALPHA}/members", json={"user_id": BOB, "role": "admin"})
check(r.ok, f"alice makes bob an admin of Alpha ({r.status_code} {r.text[:200]})")
check(book(S["bob"], BK)["can_org"] is True, "bob (admin, owner) may hand it over now")
r = S["bob"].post(B + f"/api/books/{BK}/org", json={"org_role": "maybe"})
check(r.status_code == 400, "a wrong org_role: 400")
r = S["bob"].post(B + f"/api/books/{BK}/org", json={"org_role": "view"})
check(r.ok and r.json()["org_owned"] and r.json()["org_role"] == "view" and r.json()["role"] == "owner", f"bob hands it over ({r.status_code} {r.text[:200]})")
check(S["bob"].post(B + f"/api/books/{BK}/org", json={}).status_code == 409, "a second hand-over: 409")
check(tuple(dbx("SELECT owner_org_id, owner_id FROM books WHERE id=?", (BK,))[0]) == (ALPHA, BOB), "db: owner_org_id = Alpha, manager bob")
# a private book and a book of a member: no hand-over
r = A.post(B + "/api/books", json={"name": "Private", "org_id": None})
PB = r.json()["id"]
check(A.post(B + f"/api/books/{PB}/org", json={}).status_code == 409, "a private book cannot be handed over")
r = S["erin"].post(B + "/api/books", json={"name": "Erin own", "org_id": ALPHA})
EB = r.json()["id"]
check(A.post(B + f"/api/books/{EB}/org", json={}).status_code == 404, "an admin cannot take a member's book (not shared)")
check(S["erin"].post(B + f"/api/books/{EB}/org", json={}).status_code == 403, "erin (member) cannot hand over her own book")

# ---- roles: view / edit / none; other organisation and private people see nothing
b = book(S["carol"], BK)
check(b and b["role"] == "view" and b["org_owned"], f"carol (member) reads the organisation's book: {b and b['role']}")
check(A.get(B + f"/api/contacts/{CT}").ok and book(A, BK)["role"] == "owner", "alice (admin) manages it")
check(S["carol"].get(B + f"/api/contacts/{CT}").ok, "carol reads its contact")
check(S["carol"].post(B + "/api/contacts", json={"book_id": BK, "given": "Nope"}).status_code == 403, "view: carol cannot add a contact")
check(S["carol"].patch(B + f"/api/books/{BK}/org", json={"org_role": "edit"}).status_code == 403, "carol cannot change the role")
check(S["carol"].patch(B + f"/api/books/{BK}", json={"name": "X"}).status_code == 403, "carol cannot rename it")
check(S["dave"].get(B + f"/api/contacts/{CT}").status_code == 404 and book(S["dave"], BK) is None, "dave (Beta) sees nothing")
check(S["dave"].get(B + "/api/contacts?q=Petra").json().get("items", []) == [], "dave: search finds nothing")
check(S["carol"].get(B + "/api/contacts?q=Petra").json()["items"][0]["id"] == CT, "carol: search finds the contact")
r = A.patch(B + f"/api/books/{BK}/org", json={"org_role": "edit"})
check(r.ok and r.json()["org_role"] == "edit", "alice: members may edit")
r = S["carol"].post(B + "/api/contacts", json={"book_id": BK, "given": "Carla", "family": "Carrier"})
check(r.status_code == 201, f"edit: carol adds a contact ({r.status_code})")
CT2 = r.json()["id"]
check(A.patch(B + f"/api/books/{BK}/org", json={"org_role": "none"}).ok, "alice: members see nothing")
check(book(S["carol"], BK) is None and S["carol"].get(B + f"/api/contacts/{CT}").status_code == 404, "none: carol does not see it")
check(A.put(B + f"/api/books/{BK}/members", json={"user_id": CAROL, "role": "view"}).ok, "alice shares it with carol (view)")
check(book(S["carol"], BK)["role"] == "view", "none + share view: carol reads")
check(A.patch(B + f"/api/books/{BK}/org", json={"org_role": "edit"}).ok, "back to edit")
check(book(S["carol"], BK)["role"] == "edit", "edit + share view: the better one (edit)")
check(A.put(B + f"/api/books/{BK}/members", json={"user_id": DAVE, "role": "view"}).status_code in (404, 409), "a Beta person cannot be shared with")

# ---- role change of the manager: member -> admin (above) -> member -> admin
check(A.put(B + f"/api/orgs/{ALPHA}/members", json={"user_id": BOB, "role": "member"}).ok, "bob is a member again")
b = book(S["bob"], BK)
check(b and b["role"] == "edit", f"bob (manager, member) only has the members' role: {b and b['role']}")
check(S["bob"].patch(B + f"/api/books/{BK}/org", json={"org_role": "view"}).status_code == 403, "bob cannot manage it any more")
check(S["bob"].delete(B + f"/api/books/{BK}").status_code == 403, "bob cannot delete it")
check(A.put(B + f"/api/orgs/{ALPHA}/members", json={"user_id": BOB, "role": "admin"}).ok, "bob is an admin again")
check(book(S["bob"], BK)["role"] == "owner", "bob manages it again")

# ---- workspace: an organisation's book stays in its organisation
check(A.patch(B + f"/api/books/{BK}", json={"org_id": None}).status_code == 409, "an organisation's book cannot become private (409)")
check(A.patch(B + f"/api/books/{BK}", json={"org_id": ALPHA, "name": "Suppliers"}).ok, "the same workspace: fine")

# ---- an agent of Alpha: only through a share (as before)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "contacts"], "username": "alphabot", "display_name": "Alpha bot"})
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": ALPHA})
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ALPHA, AG), write=True)
r = requests.get(V + "/address-books", headers=AGH)
check(r.ok and BK not in [x["id"] for x in r.json().get("data", [])], f"the agent does not see the organisation's book unshared ({r.status_code})")
check(requests.get(V + f"/contacts/{CT}", headers=AGH).status_code == 404, "the agent: its contact 404")
check(A.put(B + f"/api/books/{BK}/members", json={"user_id": AG, "role": "view"}).ok, "alice shares it with the agent")
r = requests.get(V + "/address-books", headers=AGH)
check(r.ok and BK in [x["id"] for x in r.json().get("data", [])], "shared: the agent sees it")
check(requests.post(V + f"/contacts", headers=AGH, json={"book_id": BK, "given": "Bot"}).status_code == 403, "the agent (view) cannot write")
check(requests.post(B + f"/api/books/{BK}/org", headers=AGH, json={}).status_code in (403, 404), "the agent cannot use the hand-over")

# ---- CardDAV: the organisation's book for a member; writing only with edit
r = S["carol"].post(B + "/api/me/app-passwords", json={"name": "Phone"})
CPW = r.json()["password"]
A.delete(B + f"/api/books/{BK}/members/{CAROL}")
r = dav("carol", CPW, "PROPFIND", "/dav/addressbooks/carol/", "<?xml version=\"1.0\"?><propfind xmlns=\"DAV:\"><prop><resourcetype/></prop></propfind>", Depth="1")
check(r.status_code == 207 and f"/dav/addressbooks/carol/b{BK}/" in r.text, f"CardDAV: carol's home lists the organisation's book ({r.status_code})")
r = dav("carol", CPW, "PUT", f"/dav/addressbooks/carol/b{BK}/dav-1.vcf", VCARD.format(u="dav-1", n="Dav One"), **{"Content-Type": "text/vcard"})
check(r.status_code in (201, 204), f"CardDAV: edit -> PUT works ({r.status_code})")
check(A.patch(B + f"/api/books/{BK}/org", json={"org_role": "view"}).ok, "view again")
r = dav("carol", CPW, "PUT", f"/dav/addressbooks/carol/b{BK}/dav-2.vcf", VCARD.format(u="dav-2", n="Dav Two"), **{"Content-Type": "text/vcard"})
check(r.status_code == 403, f"CardDAV: view -> PUT 403 ({r.status_code})")
r = S["dave"].post(B + "/api/me/app-passwords", json={"name": "Phone"})
r = dav("dave", r.json()["password"], "PROPFIND", "/dav/addressbooks/dave/", "<?xml version=\"1.0\"?><propfind xmlns=\"DAV:\"><prop><resourcetype/></prop></propfind>", Depth="1")
check(f"b{BK}/" not in r.text, "CardDAV: dave (Beta) does not get it")
check(A.patch(B + f"/api/books/{BK}/org", json={"org_role": "edit"}).ok, "edit again")

# ---- the manager leaves Alpha: the book stays (contacts, birthday list, links), alice manages it
n_ct = dbx("SELECT COUNT(*) FROM contacts WHERE book_id=?", (BK,))[0][0]
n_occ = dbx("SELECT COUNT(*) FROM contact_occ WHERE contact_id=?", (CT,))[0][0]
r = S["bob"].delete(B + f"/api/orgs/{ALPHA}/members/{BOB}")
check(r.ok, f"bob leaves Alpha ({r.status_code} {r.text[:200]})")
row = dbx("SELECT owner_id, owner_org_id, org_id, occ_list_id FROM books WHERE id=?", (BK,))
check(row and tuple(row[0]) == (1, ALPHA, ALPHA, LB), f"after leaving: the book stays, alice manages it ({row and tuple(row[0])})")
check(dbx("SELECT COUNT(*) FROM contacts WHERE book_id=?", (BK,))[0][0] == n_ct, "after leaving: every contact stays")
check(dbx("SELECT COUNT(*) FROM contact_tasks WHERE contact_id=? AND task_id=?", (CT, TK))[0][0] == 1, "after leaving: the link to the task stays")
check(book(S["bob"], BK) is None and S["bob"].get(B + f"/api/contacts/{CT}").status_code == 404, "bob does not see it any more")
check(book(S["carol"], BK)["role"] == "edit", "carol keeps her role")
check(dbx("SELECT COUNT(*) FROM contact_occ WHERE contact_id=?", (CT,))[0][0] == n_occ, "after leaving: the birthday task stays")

# ---- the manager's account is deleted: the book stays, another admin manages it
check(A.put(B + f"/api/orgs/{ALPHA}/members", json={"user_id": ERIN, "role": "admin"}).ok, "erin is an admin of Alpha")
check(S["erin"].patch(B + f"/api/books/{BK}", json={"birthdays_list_id": LB}).status_code in (200, 404), "erin chooses the birthday list")
dbx("UPDATE books SET owner_id=? WHERE id=?", (ERIN, BK), write=True)  # erin manages it now (whatever the list rights said)
r = A.delete(B + f"/api/users/{ERIN}")
check(r.ok, f"alice deletes erin's account ({r.status_code} {r.text[:200]})")
row = dbx("SELECT owner_id, owner_org_id, occ_list_id FROM books WHERE id=?", (BK,))
check(row and tuple(row[0]) == (1, ALPHA, LB), f"after deleting the manager: the book stays with alice ({row and tuple(row[0])})")
check(dbx("SELECT COUNT(*) FROM contacts WHERE book_id=?", (BK,))[0][0] == n_ct, "after deleting: every contact stays")
check(dbx("SELECT COUNT(*) FROM books WHERE id=?", (EB,))[0][0] == 0, "erin's own book went with her (as before)")

# ---- way back: personal again (alice's own), then handed over again (the undo of the app)
r = A.delete(B + f"/api/books/{BK}/org")
check(r.ok and not r.json()["org_owned"] and r.json()["role"] == "owner", f"alice makes it personal ({r.status_code})")
check(tuple(dbx("SELECT owner_id, owner_org_id, org_id FROM books WHERE id=?", (BK,))[0]) == (1, None, ALPHA), "db: alice's own, still in Alpha")
check(book(S["carol"], BK) is None, "personal: carol (no share) does not see it")
check(A.delete(B + f"/api/books/{BK}/org").status_code == 409, "personal twice: 409")
r = A.post(B + f"/api/books/{BK}/org", json={})
check(r.ok and r.json()["org_owned"] and r.json()["org_role"] == "edit", "undo: handed over again, the members' role it had (edit)")
check(book(S["carol"], BK)["role"] == "edit", "carol edits again")

# ---- boundary: an organisation's book outside its organisation is nobody's; the nightly check counts it
dbx("UPDATE books SET org_id=? WHERE id=?", (BETA, BK), write=True)
check(book(S["carol"], BK) is None and book(S["dave"], BK) is None and book(A, BK) is None, "org_id != owner_org_id: nobody sees it")
r = A.get(B + "/api/admin/orgs")
dbx("UPDATE books SET org_id=? WHERE id=?", (ALPHA, BK), write=True)
check(book(S["carol"], BK) is not None, "repaired: carol sees it again")

print(f"\np252_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
