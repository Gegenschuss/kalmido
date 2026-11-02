#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.370.4 Teil A (#3089): contacts and address books around the trash (review r2272 N4-N6, N8, N9). Own container
(start.sh, mode workspaces); invented accounts only (example.com); the person without an organisation (freelancer fixture,
private address books, own office) does every step.
 - N5: restoring a contact / address book brings back its old birthday task out of the tasks' trash (same id, never a second
   one), also when that task was restored by hand meanwhile
 - N4: a contact out of the trash (app, bulk undelete, CardDAV PUT) counts against the contacts per address book (409); books
   in the trash do not count against the address book limit, their restore does; a new default book only while the old one
   is in the trash, restored it is the default again
 - CardDAV PUT of a card in the trash links the client's contact person again (as the restore in the app)
 - N6: undoing a merge with the target (or its address book) in the trash: 409 with what to do, not 200 / 404
 - N8: the data export leaves out address books in the trash
 - N9: a contact in the trash is no letter recipient (404); a contact in the trash does not block a move (single, bulk) or a
   CardDAV UID change
freelancer-matrix: pim
usage: p2370_4_a_contacts_test.py <datadir>      (P2370A_NOSTART=1: a running server on KALMIDO_TEST_PORT)
"""
import os
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer
from kt import FAILS, OKS, check

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
NOW = "2026-01-01T00:00:00Z"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        c.commit()
        try:
            return r.fetchall()
        except Exception:  # an UPDATE without rows to read
            return []
    finally:
        c.close()


def one(q, args=()):
    r = sql(q, args)
    return r[0][0] if r else None


if os.environ.get("P2370A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FID, Fr = freelancer(B, A)


def book(name):
    r = Fr.post(B + "/api/books", json={"name": name, "org_id": None})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def contact(bid, fn, **kw):
    r = Fr.post(B + "/api/contacts", json={"book_id": bid, "fn": fn, "emails": [{"value": fn.split()[0].lower() + "@example.com"}], **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def deleted(cid):
    return one("SELECT deleted_at FROM contacts WHERE id=?", (cid,)) is not None


BK = book("Frida's contacts")
BL = Fr.post(B + "/api/lists", json={"name": "Birthdays"}).json()["id"]
check(Fr.patch(B + f"/api/books/{BK}", json={"birthdays_list_id": BL}).ok, "setup: the book's birthday list")


def bday_tasks(cid):
    """[(id, deleted_at)] of the birthday tasks of contact cid in the birthday list."""
    return [(r[0], r[1]) for r in sql("SELECT id, deleted_at FROM tasks WHERE list_id=? AND fam LIKE ? ORDER BY id", (BL, f'%"contact:{cid}"%'))]


# ================================================================== N5: birthday tasks after a restore
CB = contact(BK, "Bea Example", bday="1990-03-04")
T0 = bday_tasks(CB)
check(len(T0) == 1 and T0[0][1] is None, f"setup: Bea's birthday task {T0}")
T0 = T0[0][0]
check(Fr.delete(B + f"/api/contacts/{CB}").ok and bday_tasks(CB)[0][1] is not None, "N5: deleted, the birthday task is in the tasks' trash")
check(Fr.post(B + f"/api/contacts/{CB}/restore").ok, "N5: restored")
t = bday_tasks(CB)
check(t == [(T0, None)], f"N5: restore brings the old task back, no second one {t}")
check(one("SELECT task_id FROM contact_occ WHERE contact_id=? AND kind='birthday'", (CB,)) == T0, "N5: ... and links it again")
# the task restored by hand before the contact
Fr.delete(B + f"/api/contacts/{CB}")
check(Fr.post(B + f"/api/tasks/{T0}/restore").ok, "setup: the birthday task restored by hand")
check(Fr.post(B + f"/api/contacts/{CB}/restore").ok, "N5: then the contact restored")
t = bday_tasks(CB)
check(t == [(T0, None)], f"N5: still the one task after a restore by hand {t}")
# the whole address book
check(Fr.delete(B + f"/api/books/{BK}").ok and bday_tasks(CB)[0][1] is not None, "N5: book deleted, the task in the trash")
check(Fr.post(B + f"/api/books/{BK}/restore").ok, "N5: book restored")
t = bday_tasks(CB)
check(t == [(T0, None)], f"N5: book restore brings the old task back, no second one {t}")

# ================================================================== N4: contacts per address book
BK2 = book("Big book")
X = contact(BK2, "Xena Example")
XU, XH = sql("SELECT uid, href FROM contacts WHERE id=?", (X,))[0]
check(Fr.delete(B + f"/api/contacts/{X}").ok and deleted(X), "setup: Xena in the trash")
sql("INSERT INTO contacts(book_id, uid, href, fn, created_at, updated_at) SELECT ?, 'p2370a-'||g, 'p2370a-'||g||'.vcf', 'Filler', ?, ? "
    "FROM generate_series(1, 20000) g", (BK2, NOW, NOW))
r = Fr.post(B + f"/api/contacts/{X}/restore")
check(r.status_code == 409 and deleted(X), f"N4: restore into a full book: 409 {r.status_code} {r.text[:120]}")
r = Fr.post(B + "/api/contacts/bulk", json={"action": "undelete", "ids": [X]})
check(r.status_code == 409 and deleted(X), f"N4: bulk undelete into a full book: 409 {r.status_code}")
PW = Fr.post(B + "/api/me/app-passwords", json={"name": "Phone"}).json()["password"]


def dav(method, path, data=None, **hdr):
    return requests.request(method, B + path, data=data.encode("utf-8") if isinstance(data, str) else data, auth=("frida", PW),
                            headers={k.replace("_", "-"): v for k, v in hdr.items()})


def card(uid, fn):
    return f"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{uid}\r\nFN:{fn}\r\nN:{fn};;;;\r\nEND:VCARD\r\n"


r = dav("PUT", f"/dav/addressbooks/frida/b{BK2}/{XH}", card(XU, "Xena Example"), Content_Type="text/vcard")
check(r.status_code not in (200, 201, 204) and deleted(X), f"N4: CardDAV PUT of the card in the trash into a full book refused {r.status_code}")
sql("DELETE FROM contacts WHERE book_id=? AND uid LIKE 'p2370a-%'", (BK2,))
check(Fr.post(B + f"/api/contacts/{X}/restore").ok and not deleted(X), "N4: with room again the restore works")

# ================================================================== CardDAV PUT restore links the contact person again
Y = contact(BK2, "Yuri Example")
YU, YH = sql("SELECT uid, href FROM contacts WHERE id=?", (Y,))[0]
CLY = one("INSERT INTO clients(name, created_by, created_at, updated_at) VALUES(?,?,?,?) RETURNING id", ("Example Client", FID, NOW, NOW))
KPY = one("INSERT INTO office_client_contacts(client_id, name, contact_id, created_at, updated_at) VALUES(?,?,?,?,?) RETURNING id",
          (CLY, "Yuri Example", Y, NOW, NOW))
check(dav("DELETE", f"/dav/addressbooks/frida/b{BK2}/{YH}").status_code in (200, 204) and deleted(Y)
      and one("SELECT contact_id FROM office_client_contacts WHERE id=?", (KPY,)) is None, "setup: Yuri deleted from the phone")
r = dav("PUT", f"/dav/addressbooks/frida/b{BK2}/{YH}", card(YU, "Yuri Example"), Content_Type="text/vcard")
check(r.status_code == 201 and not deleted(Y), f"CardDAV: the same card again takes it out of the trash {r.status_code}")
check(tuple(sql("SELECT contact_id, trash_contact_id FROM office_client_contacts WHERE id=?", (KPY,))[0]) == (Y, None),
      "CardDAV: ... and the client's contact person is linked again")

# ================================================================== N9: the trash blocks nothing, is no recipient
BK4 = book("Second book")
P = contact(BK, "Paul Example")
Q = contact(BK4, "Quinn Example")
Fr.delete(B + f"/api/contacts/{Q}")
sql("UPDATE contacts SET uid=(SELECT uid FROM contacts WHERE id=?) WHERE id=?", (P, Q))
r = Fr.patch(B + f"/api/contacts/{P}", json={"book_id": BK4})
check(r.ok and one("SELECT book_id FROM contacts WHERE id=?", (P,)) == BK4, f"N9: a twin in the trash does not block the move {r.status_code} {r.text[:120]}")
R = contact(BK, "Rita Example")
S = contact(BK4, "Sam Example")
Fr.delete(B + f"/api/contacts/{S}")
sql("UPDATE contacts SET uid=(SELECT uid FROM contacts WHERE id=?) WHERE id=?", (R, S))
r = Fr.post(B + "/api/contacts/bulk", json={"action": "move", "ids": [R], "book_id": BK4})
check(r.ok and r.json().get("moved") == 1 and not r.json().get("conflicts"), f"N9: ... nor the bulk move {r.text[:160]}")
# CardDAV: a UID change to the UID of a card in the trash
U1 = contact(BK2, "Uma Example")
U1H = one("SELECT href FROM contacts WHERE id=?", (U1,))
U2 = contact(BK2, "Ulf Example")
U2U = one("SELECT uid FROM contacts WHERE id=?", (U2,))
Fr.delete(B + f"/api/contacts/{U2}")
r = dav("PUT", f"/dav/addressbooks/frida/b{BK2}/{U1H}", card(U2U, "Uma Example"), Content_Type="text/vcard")
check(r.status_code == 204 and one("SELECT uid FROM contacts WHERE id=?", (U1,)) == U2U, f"N9: CardDAV UID check only against live cards {r.status_code}")
# letters
LT = "/api/office/letters"
r = Fr.post(B + LT, json={"contact_id": P, "subject": "Invented letter", "body": "Invented text."})
check(r.status_code == 201, f"setup: a letter to a live contact {r.status_code} {r.text[:120]}")
r = Fr.post(B + LT, json={"contact_id": Q, "subject": "Invented letter", "body": "Invented text."})
check(r.status_code == 404, f"N9: a contact in the trash is no recipient: 404 ({r.status_code})")

# ================================================================== N6: merge undo with the target in the trash
TT = contact(BK, "Tom Example")
MM = contact(BK, "Tom Example2")
r = Fr.post(B + "/api/contacts/merge", json={"target": TT, "ids": [MM], "pick": {}})
check(r.ok, f"setup: merged {r.text[:150]}")
RID = r.json().get("run_id")
Fr.delete(B + f"/api/contacts/{TT}")
r = Fr.post(B + f"/api/contacts/merges/{RID}/undo")
check(r.status_code == 409 and "trash" in r.text and not one("SELECT 1 FROM contacts WHERE id=?", (MM,)), f"N6: target in the trash: 409 {r.status_code} {r.text[:150]}")
Fr.post(B + f"/api/contacts/{TT}/restore")
r = Fr.post(B + f"/api/contacts/merges/{RID}/undo")
check(r.ok and (r.json().get("target") or {}).get("id") == TT and Fr.get(B + f"/api/contacts/{MM}").ok, f"N6: restored first, the undo works {r.text[:150]}")
BK3 = book("Merge book")
T3 = contact(BK3, "Tina Example")
M3 = contact(BK3, "Tina Example2")
RID3 = Fr.post(B + "/api/contacts/merge", json={"target": T3, "ids": [M3], "pick": {}}).json().get("run_id")
Fr.delete(B + f"/api/books/{BK3}")
r = Fr.post(B + f"/api/contacts/merges/{RID3}/undo")
check(r.status_code == 409 and "trash" in r.text, f"N6: the book in the trash: 409, not 404 ({r.status_code} {r.text[:150]})")

# ================================================================== N8: the export leaves the trash out
j = Fr.get(B + "/api/export.json").json()
ids = [b["id"] for b in j.get("address_books", [])]
check(BK3 not in ids and BK in ids, f"N8: the data export has no book from the trash {ids}")
check(not any(x.get("book_id") == BK3 for x in j.get("contacts", [])), "N8: ... nor its contacts")

# ================================================================== N4: address book limit + default book
live = one("SELECT COUNT(*) FROM books WHERE owner_id=? AND owner_org_id IS NULL AND deleted_at IS NULL", (FID,))
more = [book(f"Book {i}") for i in range(30 - live)]
check(Fr.post(B + "/api/books", json={"name": "One too many", "org_id": None}).status_code == 409, "setup: 30 books, the next one 409")
check(Fr.delete(B + f"/api/books/{more[-1]}").ok, "setup: one into the trash")
r = Fr.post(B + "/api/books", json={"name": "Instead", "org_id": None})
check(r.status_code == 201, f"N4: a book in the trash does not count against the limit {r.status_code} {r.text[:120]}")
r = Fr.post(B + f"/api/books/{more[-1]}/restore")
check(r.status_code == 409 and one("SELECT deleted_at FROM books WHERE id=?", (more[-1],)), f"N4: its restore with the limit reached: 409 {r.status_code}")

GID, Gr = freelancer(B, A, name="gerd")
r = Gr.post(B + "/api/contacts", json={"fn": "First Example"})
check(r.status_code == 201, f"setup: a contact without a book makes the default book {r.text[:120]}")
D1 = one("SELECT book_id FROM contacts WHERE id=?", (r.json()["id"],))
check(Gr.delete(B + f"/api/books/{D1}").ok, "setup: the default book in the trash")
r = Gr.post(B + "/api/contacts", json={"fn": "Second Example"})
D2 = one("SELECT book_id FROM contacts WHERE id=?", (r.json()["id"],)) if r.ok else None
check(D2 and D2 != D1, "N4: with the default book in the trash a new one is made (the old one's contacts stay in the trash)")
check(Gr.post(B + f"/api/books/{D1}/restore").ok, "setup: the old default book restored")
r = Gr.post(B + "/api/contacts", json={"fn": "Third Example"})
check(r.ok and one("SELECT book_id FROM contacts WHERE id=?", (r.json()["id"],)) == D1
      and one("SELECT COUNT(*) FROM books WHERE owner_id=? AND deleted_at IS NULL", (GID,)) == 2,
      "N4: restored, the old one is the default again, no third book")

print(f"p2370_4_a_contacts: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
