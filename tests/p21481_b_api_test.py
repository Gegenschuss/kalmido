#!/usr/bin/env python3
"""2.148.1 API tests, part B: workspace boundary and retention (#2479 #2483 #2484 #2491), own container (start.sh).
Invented names only, addresses @example.com. tenant-matrix: org
 - #2479: an organisation admin does not delete an account with a personal office (409 names the areas); no account whose
   personal office holds finalised documents is deleted, also not by the server admin (409); an account without anything
   private goes as before
 - #2483: data leaves an organisation only through its admin -- list workspace, list copy by a guest, files (move-space),
   tables, contacts (bulk and single), "save as task" from a team channel; an admin's move is logged and the other admins
   get a News entry; receipts the equipment list points to stay in their workspace
 - #2484: a private client with finalised documents of the personal office stays private (409); deleting a client: the
   creator or an admin of its organisation, never while finalised documents refer to it; a document shows the contact
   persons of its client only while the client is in the document's workspace
 - #2491: a closed channel is opened only by its members (an organisation admin may archive it); an organisation's
   address book is not taken over as somebody's own; a server admin's takeover of a disabled account's list is logged and
   told to the person
 - a person without an organisation (freelancer-matrix: contacts): own address books, own lists, own client deletion work
usage: p21481_b_api_test.py <datadir>      (a fresh container; P21481B_NOSTART=1 = the server already runs)"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
TS = "2026-05-04T10:00:00Z"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    r = s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
    assert r.ok, (user, r.text)
    return s


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def news(uid, action):
    out = []
    for (d,) in sql("SELECT data FROM notifications WHERE user_id=? AND kind='orglist'", (uid,)):
        d = json.loads(d) if isinstance(d, str) else (d or {})
        if d.get("action") == action:
            out.append(d)
    return out


def moveouts(kind):
    out = []
    for (d,) in sql("SELECT detail FROM org_list_log WHERE action='moveout'"):
        d = json.loads(d) if isinstance(d, str) else (d or {})
        if d.get("kind") == kind:
            out.append(d)
    return out


def doc(s, client_id, lock=False):
    r = s.post(B + "/api/office/docs", json={"kind": "invoice", "client_id": client_id})
    assert r.status_code in (200, 201), r.text
    did = r.json()["id"]
    if lock:
        sql("UPDATE office_docs SET locked_at=? WHERE id=?", (TS, did), write=True)
    return did


if not os.environ.get("P21481B_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u, role in (("bob", "member"), ("carol", "member"), ("erin", "admin"), ("nora", "member"), ("max", "member"),
                ("hank", "member"), ("gina", "guest")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca, Er, No, Ha, Gi = sess("bob"), sess("carol"), sess("erin"), sess("nora"), sess("hank"), sess("gina")
FID, Fr = freelancer(B, A)

# ================================================================ #2484 clients
for s in (Bo, Er):
    s.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
Ca.patch(B + "/api/settings", json={"workspace": "private"})
CC = Ca.post(B + "/api/clients", json={"name": "Private Client Ltd", "org_id": None}).json()["id"]
check(sql("SELECT org_id FROM clients WHERE id=?", (CC,))[0][0] is None, "setup: carol's client is private")
doc(Ca, CC, lock=True)
r = Ca.patch(B + f"/api/clients/{CC}", json={"org_id": ORG})
check(r.status_code == 409 and r.json().get("error"), "a private client with a finalised document of the personal office stays (409) " + r.text[:200])
check(sql("SELECT org_id FROM clients WHERE id=?", (CC,))[0][0] is None, "the private client is still private")
r = Ca.delete(B + f"/api/clients/{CC}")
check(r.status_code == 409, "a client with a finalised document is not deleted (409) " + r.text[:200])
CC2 = Ca.post(B + "/api/clients", json={"name": "Second Client Ltd", "org_id": None}).json()["id"]
r = Ca.patch(B + f"/api/clients/{CC2}", json={"org_id": ORG})
check(r.ok, "a private client without finalised documents moves as before " + r.text[:200])
# deleting: the creator or an admin of the organisation
CD = Bo.post(B + "/api/clients", json={"name": "Org Client One", "org_id": ORG}).json()["id"]
check(Ca.delete(B + f"/api/clients/{CD}").status_code == 403, "a plain member who did not create the client cannot delete it")
r = Er.delete(B + f"/api/clients/{CD}")
check(r.ok, "an admin of the organisation deletes its client " + r.text[:200])
CK = Bo.post(B + "/api/clients", json={"name": "Org Client Two", "org_id": ORG}).json()["id"]
doc(Bo, CK, lock=True)
check(Er.delete(B + f"/api/clients/{CK}").status_code == 409, "an organisation's client with a finalised document: 409")
check(sql("SELECT COUNT(*) FROM clients WHERE id=?", (CK,))[0][0] == 1, "the client is still there")
# contact persons only in the client's own workspace
CX = Bo.post(B + "/api/clients", json={"name": "Moving Client", "org_id": ORG, "contacts": [{"name": "Petra Example"}]}).json()["id"]
DX = doc(Bo, CX)
check([x["name"] for x in Bo.get(B + f"/api/office/docs/{DX}").json().get("client_contacts", [])] == ["Petra Example"],
      "setup: the draft shows its client's contact person")
r = Bo.patch(B + f"/api/clients/{CX}", json={"org_id": None})
check(r.ok, "the creator moves the client without finalised documents to private " + r.text[:200])
check(Bo.get(B + f"/api/office/docs/{DX}").json().get("client_contacts") == [], "the organisation's draft no longer lists the contact persons")
# freelancer-matrix: contacts -- the own private client
FC = Fr.post(B + "/api/clients", json={"name": "Freelance Client", "org_id": None}).json()["id"]
doc(Fr, FC, lock=True)
check(Fr.delete(B + f"/api/clients/{FC}").status_code == 409, "freelancer: a client with a finalised invoice stays (409)")
FC2 = Fr.post(B + "/api/clients", json={"name": "Old Client", "org_id": None}).json()["id"]
check(Fr.delete(B + f"/api/clients/{FC2}").ok, "freelancer: an own client without documents is deleted")

# ================================================================ #2479 deleting accounts
No.patch(B + "/api/settings", json={"workspace": "private"})
NC = No.post(B + "/api/clients", json={"name": "Nora Client", "org_id": None}).json()["id"]
doc(No, NC)
r = Er.delete(B + f"/api/users/{uid['nora']}")
check(r.status_code == 409 and "personal office" in r.json().get("error", ""), "an organisation admin does not delete an account with a personal office (409, named) " + r.text[:300])
r = Er.get(B + f"/api/users/{uid['nora']}/delete-info")
check(r.ok and not r.json()["can_delete"] and "personal office" in r.json().get("reason", ""), "delete-info: no, the areas named " + r.text[:300])
check(No.get(B + "/api/me").ok, "nora's account is still there")
r = A.delete(B + f"/api/users/{uid['carol']}")
check(r.status_code == 409 and r.json().get("error"), "the server admin does not delete an account whose personal office holds a finalised document (409) " + r.text[:200])
check(Ca.get(B + "/api/me").ok and sql("SELECT COUNT(*) FROM office_docs d JOIN orgs o ON o.id=d.org_id WHERE o.personal_of=?", (uid["carol"],))[0][0] >= 1,
      "carol's account and documents are still there")
r = Er.delete(B + f"/api/users/{uid['max']}")
check(r.ok, "an account without anything private is deleted as before " + r.text[:200])
r = A.delete(B + f"/api/users/{uid['nora']}")
check(r.ok, "the server admin still deletes an account with only drafts in its office " + r.text[:200])
FID2, Fr2 = freelancer(B, A, "fiona")
check(A.delete(B + f"/api/users/{FID2}").ok, "freelancer: an account without an office is deleted as before")
check(A.delete(B + f"/api/users/{FID}").status_code == 409, "freelancer: an account with a finalised invoice is kept (409)")

# ================================================================ #2483 lists
LB = Bo.post(B + "/api/lists", json={"name": "Team plan", "org_id": ORG}).json()["id"]
r = Bo.patch(B + f"/api/lists/{LB}", json={"org_id": None})
check(r.status_code == 403 and "admins" in r.json().get("error", ""), "a plain member cannot move an organisation's list to private (403) " + r.text[:200])
check(sql("SELECT org_id FROM lists WHERE id=?", (LB,))[0][0] == ORG, "the list stays in the organisation")
LE = Er.post(B + "/api/lists", json={"name": "Admin notes", "org_id": ORG}).json()["id"]
r = Er.patch(B + f"/api/lists/{LE}", json={"org_id": None})
check(r.ok and sql("SELECT org_id FROM lists WHERE id=?", (LE,))[0][0] is None, "an organisation admin moves a list out " + r.text[:200])
check(any(x.get("to") == "private" for x in moveouts("list")), "the move is in the organisation's list log")
check(any(x.get("name") == "Admin notes" for x in news(ALICE, "moveout")), "the other admin gets a News entry")
check(not news(uid["erin"], "moveout"), "the admin who moved it gets none")
check(Bo.put(B + f"/api/lists/{LB}/members", json={"user_id": uid["gina"], "role": "edit"}).ok, "setup: the list shared with a guest")
r = Gi.post(B + f"/api/lists/{LB}/duplicate", json={})
check(r.status_code == 403, "a guest's copy would leave the organisation: 403 " + r.text[:200])
r = Bo.post(B + f"/api/lists/{LB}/duplicate", json={})
check(r.ok and sql("SELECT org_id FROM lists WHERE id=?", (r.json().get("list_id"),))[0][0] == ORG, "a member's copy stays in the organisation " + r.text[:200])
FL = Fr.post(B + "/api/lists", json={"name": "Own plan"}).json()["id"]
check(Fr.post(B + f"/api/lists/{FL}/duplicate", json={}).ok, "freelancer: the own list is copied")

# ================================================================ #2483 files
FB = Bo.post(B + "/api/files/folders", json={"name": "Team folder", "space": f"org:{ORG}"}).json()["id"]
r = Bo.post(B + "/api/files/move-space", json={"ids": [FB], "to": "private", "dry": 1})
check(r.ok and r.json().get("block"), "dry run: the plain member's move out is blocked " + r.text[:200])
r = Bo.post(B + "/api/files/move-space", json={"ids": [FB], "to": "private"})
check(r.status_code == 403, "a plain member cannot move an organisation's folder to private (403) " + r.text[:200])
FE = Er.post(B + "/api/files/folders", json={"name": "Admin folder", "space": f"org:{ORG}"}).json()["id"]
r = Er.post(B + "/api/files/move-space", json={"ids": [FE], "to": "private"})
check(r.ok and sql("SELECT org_id FROM fs_nodes WHERE id=?", (FE,))[0][0] is None, "an admin moves a folder out " + r.text[:200])
check(moveouts("file"), "the file move is logged")
r = Er.post(B + "/api/files/upload", data={"space": f"org:{ORG}"}, files=[("file", ("receipt.txt", b"Receipt 12.50 EUR", "text/plain"))])
check(r.status_code == 201, "setup: a receipt file " + r.text[:200])
RN = r.json()["items"][0]["id"] if r.status_code == 201 else 0
sql("INSERT INTO office_equipment(org_id,name,created_at,updated_at,receipt_node_id) VALUES(?,?,?,?,?)", (ORG, "Camera", TS, TS, RN), write=True)
r = Er.post(B + "/api/files/move-space", json={"ids": [RN], "to": "private"})
check(r.status_code == 409, "a receipt of the equipment list stays in its workspace (409) " + r.text[:200])

# ================================================================ #2483 tables
Bo.patch(B + "/api/settings", json={"features": FEATURES + ",sheets"})
r = Bo.post(B + "/api/sheets", json={"title": "Team table", "space": f"org:{ORG}"})
check(r.status_code == 201, "setup: a table " + r.text[:200])
SB = r.json().get("id")
r = Bo.post(B + f"/api/sheets/{SB}/move-space", json={"to": "private"})
check(r.status_code == 403, "its creator (a plain member) cannot move the table out (403) " + r.text[:200])
check(sql("SELECT org_id FROM sheets WHERE id=?", (SB,))[0][0] == ORG, "the table stays")

# ================================================================ #2483 contacts
BO = Bo.post(B + "/api/books", json={"name": "Suppliers", "org_id": ORG}).json()["id"]
BP = Bo.post(B + "/api/books", json={"name": "Mine", "org_id": None}).json()["id"]
K1 = Bo.post(B + "/api/contacts", json={"book_id": BO, "given": "Paul", "family": "Supply"}).json()["id"]
r = Bo.post(B + "/api/contacts/bulk", json={"action": "move", "ids": [K1], "book_id": BP})
check(r.status_code == 403, "a plain member cannot move contacts out of an organisation's address book (403) " + r.text[:200])
r = Bo.patch(B + f"/api/contacts/{K1}", json={"book_id": BP})
check(r.status_code == 403, "nor a single contact (403) " + r.text[:200])
check(sql("SELECT book_id FROM contacts WHERE id=?", (K1,))[0][0] == BO, "the contact stays")
EO = Er.post(B + "/api/books", json={"name": "Admin book", "org_id": ORG}).json()["id"]
EP = Er.post(B + "/api/books", json={"name": "Admin private", "org_id": None}).json()["id"]
K2 = Er.post(B + "/api/contacts", json={"book_id": EO, "given": "Rita", "family": "Example"}).json()["id"]
r = Er.post(B + "/api/contacts/bulk", json={"action": "move", "ids": [K2], "book_id": EP})
check(r.ok and r.json().get("moved") == 1, "an admin moves contacts out " + r.text[:200])
check(moveouts("contacts"), "the contacts move is logged")
F1 = Fr.post(B + "/api/books", json={"name": "Clients", "org_id": None}).json()["id"]
F2 = Fr.post(B + "/api/books", json={"name": "Friends", "org_id": None}).json()["id"]
K3 = Fr.post(B + "/api/contacts", json={"book_id": F1, "given": "Lena", "family": "Example"}).json()["id"]
r = Fr.post(B + "/api/contacts/bulk", json={"action": "move", "ids": [K3], "book_id": F2})
check(r.ok and r.json().get("moved") == 1, "freelancer: contacts move between the own address books " + r.text[:200])

# ================================================================ #2483 save as task, #2491 channels
r = Bo.post(B + "/api/team/channels", json={"name": "Closed room", "org_id": ORG, "open": False})
check(r.status_code == 201, "setup: a closed channel " + r.text[:200])
CH = r.json()["id"]
r = Bo.post(B + f"/api/team/rooms/{CH}/messages", json={"body": "Order the new lenses"})
MID = r.json().get("id")
r = Bo.post(B + "/api/chat-save", json={"kind": "team", "msg_id": MID})
check(r.status_code == 403, "a channel message is not saved into the private basket by a plain member (403) " + r.text[:200])
r = Bo.post(B + "/api/chat-save", json={"kind": "team", "msg_id": MID, "list_id": LB})
check(r.status_code == 201, "into a list of the same organisation it works " + r.text[:200])
r = Er.patch(B + f"/api/team/rooms/{CH}", json={"open": True})
check(r.status_code == 403, "an organisation admin who is no member does not open a closed channel (403) " + r.text[:200])
check(sql("SELECT is_open FROM tchat_rooms WHERE id=?", (CH,))[0][0] == 0, "the channel stays closed")
r = Bo.patch(B + f"/api/team/rooms/{CH}", json={"open": True})
check(r.ok, "its member opens it " + r.text[:200])
check(Bo.patch(B + f"/api/team/rooms/{CH}", json={"open": False}).ok, "and closes it again")
r = Er.patch(B + f"/api/team/rooms/{CH}", json={"archived": True})
check(r.ok, "an organisation admin archives it " + r.text[:200])

# ================================================================ #2491 address books, takeover
AB = A.post(B + "/api/books", json={"name": "Partners", "org_id": ORG}).json()["id"]
r = A.post(B + f"/api/books/{AB}/org", json={"org_role": "view"})
check(r.ok, "setup: an admin hands the address book to the organisation " + r.text[:200])
r = Er.delete(B + f"/api/books/{AB}/org")
check(r.status_code == 403, "another organisation admin does not take the organisation's address book as their own (403) " + r.text[:200])
check(sql("SELECT owner_org_id FROM books WHERE id=?", (AB,))[0][0] == ORG, "the address book stays with the organisation")
r = Er.post(B + f"/api/books/{EO}/org", json={})
check(r.ok and Er.delete(B + f"/api/books/{EO}/org").ok, "the undo of the own hand-over still works")
LH = Ha.post(B + "/api/lists", json={"name": "Hank private", "org_id": None}).json()["id"]
check(A.patch(B + f"/api/users/{uid['hank']}", json={"disabled": True}).ok, "setup: hank disabled")
r = A.post(B + f"/api/lists/{LH}/owner", json={"user_id": uid["bob"]})
check(r.ok, "the server admin takes over a disabled account's list " + r.text[:200])
check(any(x.get("name") == "Hank private" for x in news(uid["hank"], "takeover")), "the person finds the takeover in their News")

print(f"p21481_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
