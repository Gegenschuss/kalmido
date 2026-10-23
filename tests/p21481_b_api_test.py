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
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
TS = "2026-05-04T10:00:00Z"


def usess(user, pw="password123"):
    """kt.sess plus the suite's settings (2.206.0 #2762)."""
    s = sess(user, pw)
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
A = usess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = usess("alice")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u, role in (("bob", "member"), ("carol", "member"), ("erin", "admin"), ("nora", "member"), ("max", "member"),
                ("hank", "member"), ("gina", "guest")):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": role}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca, Er, No, Ha, Gi = usess("bob"), usess("carol"), usess("erin"), usess("nora"), usess("hank"), usess("gina")
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
# bundle C: 2.152.0 (#2168) archives a client in use instead of the 409 of 2.148.1 (#2484); the row and its documents stay
check(r.ok and r.json().get("archived") is True and sql("SELECT archived FROM clients WHERE id=?", (CC,))[0][0] == 1, "a client with a finalised document is not deleted, archived " + r.text[:200])
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
r = Er.delete(B + f"/api/clients/{CK}")
check(r.ok and r.json().get("archived") is True, "an organisation's client with a finalised document: archived (2.152.0) " + r.text[:200])
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
r = Fr.delete(B + f"/api/clients/{FC}")
check(r.ok and r.json().get("archived") is True and sql("SELECT COUNT(*) FROM clients WHERE id=?", (FC,))[0][0] == 1, "freelancer: a client with a finalised invoice stays (archived, 2.152.0) " + r.text[:200])
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
# 2.186.0 (#2599): an account whose personal office keeps finalised documents is no longer refused for a missing export
# step: the office would be retired (rx_state "retire", no waiver). Only the delete-info is checked here: carol and the
# freelancer stay for the rest of the test (the deletion itself: p2186_a_retire)
r = A.get(B + f"/api/users/{uid['carol']}/delete-info")
check(r.ok and (r.json().get("retention") or {}).get("state") == "retire" and (r.json().get("purge") or {}).get("office") == "keep",
      "the server admin: the personal office with a finalised document would be retired, not deleted " + r.text[:200])
check(Ca.get(B + "/api/me").ok and sql("SELECT COUNT(*) FROM office_docs d JOIN orgs o ON o.id=d.org_id WHERE o.personal_of=?", (uid["carol"],))[0][0] >= 1,
      "carol's account and documents are still there")
r = Er.delete(B + f"/api/users/{uid['max']}")
check(r.ok, "an account without anything private is deleted as before " + r.text[:200])
r = A.delete(B + f"/api/users/{uid['nora']}")
check(r.ok, "the server admin still deletes an account with only drafts in its office " + r.text[:200])
FID2, Fr2 = freelancer(B, A, "fiona")
check(A.delete(B + f"/api/users/{FID2}").ok, "freelancer: an account without an office is deleted as before")
r = A.get(B + f"/api/users/{FID}/delete-info")  # 2.186.0 (#2599): retired instead of 409, see above
check(r.ok and (r.json().get("retention") or {}).get("state") == "retire", "freelancer: an account with a finalised invoice would retire its office " + r.text[:200])

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

# ================================================================ review fixes (part H): more ways out of an organisation
LF = Bo.post(B + "/api/lists", json={"name": "Team shopping", "org_id": ORG}).json()["id"]
r = Bo.patch(B + f"/api/lists/{LF}", json={"family": "shopping"})
check(r.status_code == 403 and sql("SELECT org_id FROM lists WHERE id=?", (LF,))[0][0] == ORG,
      "'Used for' does not make a plain member's organisation list private (403) " + r.text[:200])
BPL = Bo.post(B + "/api/lists", json={"name": "Bob own", "org_id": None}).json()["id"]
TB = Bo.post(B + "/api/tasks", json={"title": "Team task", "list_id": LB}).json()["id"]
r = Bo.patch(B + f"/api/tasks/{TB}", json={"list_id": BPL})
check(r.status_code == 403 and sql("SELECT list_id FROM tasks WHERE id=?", (TB,))[0][0] == LB,
      "a plain member does not move a task out of an organisation list (403) " + r.text[:200])
LB2 = Bo.post(B + "/api/lists", json={"name": "Team plan two", "org_id": ORG}).json()["id"]
check(Bo.patch(B + f"/api/tasks/{TB}", json={"list_id": LB2}).ok, "inside the organisation tasks move as before")
r = Bo.post(B + "/api/templates", json={"list_id": LB})
check(r.status_code == 403, "a plain member saves no organisation list as a template (403) " + r.text[:200])
r = Bo.post(B + "/api/templates", json={"task_id": TB})
check(r.status_code == 403, "... nor one of its tasks (403) " + r.text[:200])
LE2 = Er.post(B + "/api/lists", json={"name": "Admin plan", "org_id": ORG}).json()["id"]
r = Er.post(B + "/api/templates", json={"list_id": LE2})
check(r.ok and moveouts("template"), "an organisation admin saves it as a template, logged " + r.text[:200])
EPL = Er.post(B + "/api/lists", json={"name": "Erin own", "org_id": None}).json()["id"]
TE = Er.post(B + "/api/tasks", json={"title": "Admin task", "list_id": LE2}).json()["id"]
check(Er.patch(B + f"/api/tasks/{TE}", json={"list_id": EPL}).ok, "an organisation admin moves a task out")
r = Bo.patch(B + f"/api/books/{BO}", json={"org_id": None})
check(r.status_code == 403 and sql("SELECT org_id FROM books WHERE id=?", (BO,))[0][0] == ORG,
      "a plain member does not move an organisation's address book to private (403) " + r.text[:200])
r = Bo.post(B + "/api/evcals", json={"name": "Team dates", "org_id": ORG})
EC = r.json().get("id") if r.ok else None
r = Bo.patch(B + f"/api/evcals/{EC}", json={"org_id": None})
check(EC and r.status_code == 403, "... nor an organisation's calendar (403) " + r.text[:200])
check(Fr.patch(B + f"/api/books/{F2}", json={"org_id": None}).ok, "freelancer: the own address book stays editable")
# a closed channel: only its members add people
r = Bo.post(B + "/api/team/channels", json={"name": "Closed two", "org_id": ORG, "open": False})
CH2 = r.json().get("id") if r.status_code == 201 else None
r = Er.post(B + f"/api/team/rooms/{CH2}/members", json={"user_id": uid["carol"]})
check(CH2 and r.status_code == 403, "an organisation admin who is no member adds nobody to a closed channel (403) " + r.text[:200])
r = Bo.post(B + f"/api/team/rooms/{CH2}/members", json={"user_id": uid["carol"]})
check(r.ok, "its member adds a colleague " + r.text[:200])
# the boundary check names a receipt finding as a file
r = Er.post(B + "/api/files/upload", data={"space": "private"}, files=[("file", ("bill.txt", b"Bill 3.20 EUR", "text/plain"))])
RP = r.json()["items"][0]["id"] if r.status_code == 201 else 0
sql("INSERT INTO office_equipment(org_id,name,created_at,updated_at,receipt_node_id) VALUES(?,?,?,?,?)", (ORG, "Tripod", TS, TS, RP), write=True)
det = [x for x in ((A.get(B + "/api/admin/orgs").json().get("boundary") or {}).get("details") or []) if x["kind"] == "office_receipt"]
check(RP and any(x["id"] == RP and x["type"] == "file" and x["name"] == "bill.txt" for x in det), "a receipt finding is shown as a file " + str(det[:2]))

print(f"p21481_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
