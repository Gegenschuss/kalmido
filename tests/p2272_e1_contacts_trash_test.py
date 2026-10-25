#!/usr/bin/env python3
"""2.272.0 API tests, part E1 (#3038): contacts, address books and notes go to the trash. Own container (start.sh, mode
workspaces). Invented accounts only (example.com); the person without an organisation (freelancer fixture, private address
book and project) does every step.
 - DELETE /api/contacts/<id> = the trash: gone from the list, the card, CardDAV (sync-collection reports it gone); its
   "stay in touch" note and task link stay; restore brings them back
 - a CardDAV DELETE from the phone = the trash too; the same card sent again takes the row out of the trash
 - bulk delete / undelete / purge (purge only for contacts in the trash), an import of the same UID restores it
 - DELETE /api/books/<id> names its contacts and puts the book into the trash; restore / purge (purge only from the trash)
 - the trash run only counts while the switch is off, with KALMIDO_PURGE_TRASH=1 it deletes contacts and notes for good
 - a note goes to the trash, the list / search / API no longer show it, restore brings back the same note (same id)
freelancer-matrix: pim
usage: p2272_e1_contacts_trash_test.py <datadir>      (P2272E1_NOSTART=1: a running server on KALMIDO_TEST_PORT)
"""
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


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


def box(code, env=()):
    """Runs python code inside the app container (a fresh process: the run state of the watchdog starts empty)."""
    cmd = ["docker", "exec"]
    for e in env:
        cmd += ["-e", e]
    out = subprocess.run(cmd + [CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.commit()\nc.close()"],
                         capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def ago(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_purge(switch):
    return box("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))", ("KALMIDO_PURGE_TRASH=1",) if switch else ())


if os.environ.get("P2272E1_NOSTART") != "1":
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

r = Fr.post(B + "/api/books", json={"name": "Frida's contacts", "org_id": None})
check(r.status_code == 201, f"setup: a private address book {r.status_code} {r.text[:120]}")
BK = r.json()["id"]


def contact(fn, email, **kw):
    r = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": fn, "emails": [{"value": email}], **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def live_ids(**params):
    return [x["id"] for x in Fr.get(B + "/api/contacts", params={"book_id": BK, **params}).json()["items"]]


def deleted_at(cid):
    rows = sql("SELECT deleted_at FROM contacts WHERE id=?", (cid,))
    return rows[0][0] if rows else "gone"


C1 = contact("Anna Example", "anna@example.com", bday="1980-05-12")
C2 = contact("Ben Example", "ben@example.com")
C3 = contact("Cleo Example", "cleo@example.com")
C4 = contact("Dan Example", "dan@example.com")
LID = Fr.post(B + "/api/lists", json={"name": "Calls"}).json()["id"]
TID = Fr.post(B + "/api/tasks", json={"title": "Call Anna", "list_id": LID}).json()["id"]
check(Fr.post(B + f"/api/tasks/{TID}/contacts", json={"contact_id": C1, "kind": "about"}).ok, "setup: Anna linked to a task")
check(Fr.put(B + f"/api/contacts/{C1}/care", json={"every_days": 30, "note": "ask about the trip"}).ok, "setup: stay in touch with Anna")

# CardDAV: the phone's view before
PW = Fr.post(B + "/api/me/app-passwords", json={"name": "Phone"}).json()["password"]
AB = f"/dav/addressbooks/frida/b{BK}/"
SYNC = ('<?xml version="1.0" encoding="utf-8"?><d:sync-collection xmlns:d="DAV:"><d:sync-token>{}</d:sync-token>'
        '<d:sync-level>1</d:sync-level><d:prop><d:getetag/></d:prop></d:sync-collection>')


def dav(method, path, data=None, **hdr):
    return requests.request(method, B + path, data=data.encode("utf-8") if isinstance(data, str) else data, auth=("frida", PW),
                            headers={k.replace("_", "-"): v for k, v in hdr.items()})


def sync(tok=""):
    r = dav("REPORT", AB, SYNC.format(tok), Depth="1")
    root = ET.fromstring(r.text)
    have, gone = [], []
    for x in root.iter("{DAV:}response"):
        st = x.find("{DAV:}status")
        (gone if st is not None and "404" in st.text else have).append(x.find("{DAV:}href").text)
    t = root.find("{DAV:}sync-token")
    return r.status_code, have, gone, (t.text if t is not None else "")


H1 = sql("SELECT href FROM contacts WHERE id=?", (C1,))[0][0]
st, have, _, TOK0 = sync()
check(st == 207 and any(h.endswith(H1) for h in have) and TOK0, f"setup: the phone sees Anna {st} {have}")

# ================================================================== one contact into the trash and back
# 2.272.0 F (#3038, review M8): a client's contact person linked to the contact
CLX = sql("INSERT INTO clients(name, created_by, created_at, updated_at) VALUES(?,?,?,?) RETURNING id", ("Example Client", FID, ago(), ago()))[0][0]
KPX = sql("INSERT INTO office_client_contacts(client_id, name, contact_id, created_at, updated_at) VALUES(?,?,?,?,?) RETURNING id",
          (CLX, "Anna Example", C1, ago(), ago()))[0][0]
r = Fr.delete(B + f"/api/contacts/{C1}")
check(sql("SELECT contact_id FROM office_client_contacts WHERE id=?", (KPX,))[0][0] is None, "delete: the client's contact person lets go of it")
check(r.ok and r.json().get("trashed") is True and r.json().get("trash_days", 0) >= 1, f"delete: into the trash {r.text[:150]}")
check(deleted_at(C1) not in (None, "gone"), "delete: the row stays with deleted_at")
check(Fr.get(B + f"/api/contacts/{C1}").status_code == 404 and C1 not in live_ids(), "delete: gone from the card and the list")
j = Fr.get(B + "/api/contacts", params={"trash": 1}).json()
check([x["id"] for x in j["items"]] == [C1] and j["items"][0].get("deleted_at") and j.get("trash_days", 0) >= 1, f"trash: the deleted contact {j}")
check(sql("SELECT COUNT(*) FROM contact_care WHERE contact_id=?", (C1,))[0][0] == 1
      and sql("SELECT COUNT(*) FROM contact_tasks WHERE contact_id=?", (C1,))[0][0] == 1, "delete: its note and task link stay in the trash")
st, have, gone, TOK1 = sync(TOK0)
check(st == 207 and any(h.endswith(H1) for h in gone) and TOK1 != TOK0, f"CardDAV: the phone hears it is gone {gone}")
check(dav("GET", AB + H1).status_code == 404, "CardDAV: GET of the card in the trash: 404")
r = Fr.post(B + f"/api/contacts/{C1}/restore")
check(r.ok and r.json()["id"] == C1 and deleted_at(C1) is None, f"restore: back {r.status_code} {r.text[:150]}")
check(tuple(sql("SELECT contact_id, trash_contact_id FROM office_client_contacts WHERE id=?", (KPX,))[0]) == (C1, None),
      "restore: the client's contact person is linked to it again (review M8)")
d = Fr.get(B + f"/api/contacts/{C1}").json()
check([t["task_id"] for t in d.get("tasks", [])] == [TID] and (d.get("care") or {}).get("note") == "ask about the trip",
      f"restore: the task link and the stay-in-touch note come back {d.get('tasks')} {d.get('care')}")
st, have, _, _ = sync(TOK1)
check(any(h.endswith(H1) for h in have), "CardDAV: the restored card reaches the phone again")

# ================================================================== a delete from the phone
H2 = sql("SELECT href FROM contacts WHERE id=?", (C2,))[0][0]
CARD = dav("GET", AB + H2).text
r = dav("DELETE", AB + H2)
check(r.status_code == 204 and deleted_at(C2) not in (None, "gone") and C2 not in live_ids(), f"CardDAV DELETE: into the trash {r.status_code}")
r = dav("PUT", AB + H2, CARD.replace("Ben Example", "Ben Again"), Content_Type="text/vcard")
check(r.status_code == 201 and deleted_at(C2) is None and sql("SELECT fn FROM contacts WHERE id=?", (C2,))[0][0] == "Ben Again",
      f"CardDAV: the same card again takes the row out of the trash {r.status_code}")
check(sql("SELECT COUNT(*) FROM contacts WHERE book_id=? AND fn LIKE 'Ben%'", (BK,))[0][0] == 1, "CardDAV: no second row")

# ================================================================== several at once
r = Fr.post(B + "/api/contacts/bulk", json={"action": "delete", "ids": [C3, C4]})
check(r.ok and r.json()["deleted"] == 2 and all(deleted_at(x) not in (None, "gone") for x in (C3, C4)), f"bulk: both into the trash {r.text[:150]}")
r = Fr.post(B + "/api/contacts/bulk", json={"action": "delete", "ids": [C3]})
check(r.status_code == 404, "bulk: a contact in the trash cannot be deleted again (404)")
r = Fr.post(B + "/api/contacts/bulk", json={"action": "undelete", "ids": [C3, C4]})
check(r.ok and r.json()["restored"] == 2 and deleted_at(C3) is None and deleted_at(C4) is None, f"bulk: undelete {r.text[:150]}")
r = Fr.post(B + "/api/contacts/bulk", json={"action": "purge", "ids": [C4]})
check(r.status_code == 404 and deleted_at(C4) is None, "bulk: purge only for contacts in the trash")
Fr.post(B + "/api/contacts/bulk", json={"action": "delete", "ids": [C4]})
r = Fr.post(B + "/api/contacts/bulk", json={"action": "purge", "ids": [C4]})
check(r.ok and r.json()["purged"] == 1 and deleted_at(C4) == "gone", f"bulk: purge deletes for good {r.text[:150]}")

# an import of the same UID takes it out of the trash (as a new one before)
U3 = sql("SELECT uid FROM contacts WHERE id=?", (C3,))[0][0]
Fr.delete(B + f"/api/contacts/{C3}")
vcf = f"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{U3}\r\nFN:Cleo Example\r\nEMAIL:cleo@example.com\r\nEND:VCARD\r\n"
r = Fr.post(B + f"/api/books/{BK}/import", files={"file": ("c.vcf", vcf.encode(), "text/vcard")})
check(r.ok and r.json().get("created") == 1 and deleted_at(C3) is None, f"import: the same UID comes back out of the trash {r.text[:150]}")

# ================================================================== the address book
r = Fr.delete(B + f"/api/books/{BK}")
check(r.ok and r.json().get("contacts") == 3 and r.json().get("trashed") is True, f"book: into the trash, naming its contacts {r.text[:150]}")
check(BK not in [b["id"] for b in Fr.get(B + "/api/books").json()["items"]] and Fr.get(B + f"/api/contacts/{C1}").status_code == 404,
      "book: gone with its contacts")
j = Fr.get(B + "/api/books", params={"trash": 1}).json()
check([(b["id"], b["count"]) for b in j["items"]] == [(BK, 3)], f"book: in the trash with 3 contacts {j}")
check(dav("PROPFIND", AB, Depth="0").status_code == 404, "book: the phone no longer sees it")
check(Fr.post(B + f"/api/books/{BK}/restore").ok and Fr.get(B + f"/api/contacts/{C1}").ok, "book: restore brings it back with its contacts")
check(Fr.post(B + f"/api/books/{BK}/purge").status_code == 409, "book: purge only from the trash")
BK2 = Fr.post(B + "/api/books", json={"name": "Old", "org_id": None}).json()["id"]
Fr.delete(B + f"/api/books/{BK2}")
check(Fr.post(B + f"/api/books/{BK2}/purge").ok and not sql("SELECT 1 FROM books WHERE id=?", (BK2,)), "book: purged for good from the trash")
# 2.272.0 F (#3038, review M5 + N7): a book in the trash is no newsletter source; the run blanks its merge undo data
BK3 = Fr.post(B + "/api/books", json={"name": "Newsletter old", "org_id": None}).json()["id"]
Fr.delete(B + f"/api/books/{BK3}")
nb = box(f"from kalmido.newsletter.sync import nwl_books\nfrom kalmido.core.pg import system_ctx\n"
         f"with system_ctx(c):\n    print('books', [b['id'] for b in nwl_books(c, 'u{FID}')])")
check("books [" in nb and f"{BK3}" not in nb.split("books", 1)[1], f"newsletter: a book in the trash is no source {nb[-300:]}")
MR = sql("INSERT INTO merge_runs(kind, target_id, book_id, snapshot, created_at) VALUES(?,?,?,?,?) RETURNING id",
         ("contact", 0, BK3, '{"x": 1}', ago()))[0][0]
sql("UPDATE books SET deleted_at=? WHERE id=?", (ago(days=400), BK3))
run_purge(True)
check(not sql("SELECT 1 FROM books WHERE id=?", (BK3,)) and sql("SELECT snapshot FROM merge_runs WHERE id=?", (MR,))[0][0] == "{}",
      "run: the book goes for good, its merge undo data with it")
GID, Gr = freelancer(B, A, "gina")
check(Gr.post(B + f"/api/books/{BK}/restore").status_code == 404 and Gr.post(B + f"/api/contacts/{C1}/restore").status_code == 404,
      "another person cannot restore (404)")

# ================================================================== the trash run
Fr.delete(B + f"/api/contacts/{C3}")
sql("UPDATE contacts SET deleted_at=? WHERE id=?", (ago(days=400), C3))
out = run_purge(False)
check(deleted_at(C3) not in (None, "gone") and "'contacts': 1" in out, f"run: switch off = counted, the contact stays {out[-300:]}")
out = run_purge(True)
check(deleted_at(C3) == "gone", f"run: switch on = deleted for good {out[-300:]}")
check(deleted_at(C1) is None, "run: live contacts stay")

# ================================================================== notes
r = Fr.post(B + f"/api/lists/{LID}/notes", json={"title": "Kick-off minutes", "body": "Agreed on the plan"})
check(r.status_code == 201, "notes: setup")
NID = r.json()["id"]
r = Fr.delete(B + f"/api/notes/{NID}")
check(r.ok and r.json().get("trashed") is True and r.json()["note"]["title"] == "Kick-off minutes", f"notes: into the trash {r.text[:150]}")
check(Fr.get(B + f"/api/notes/{NID}").status_code == 404 and not Fr.get(B + f"/api/lists/{LID}/notes").json()["notes"]
      and not Fr.get(B + "/api/notes", params={"q": "Kick-off"}).json()["notes"], "notes: gone from the list, the card and the search")
check(not any(n["id"] == NID for n in Fr.get(B + "/api/state").json().get("notes", [])), "notes: gone from the state")
j = Fr.get(B + f"/api/lists/{LID}/notes", params={"trash": 1}).json()
check([n["id"] for n in j["notes"]] == [NID] and j.get("trash_days", 0) >= 1, f"notes: the list's trash {j}")
check(Gr.post(B + f"/api/notes/{NID}/restore").status_code == 404, "notes: another person cannot restore")
r = Fr.post(B + f"/api/notes/{NID}/restore")
check(r.ok and r.json()["id"] == NID and Fr.get(B + f"/api/notes/{NID}").json()["body"] == "Agreed on the plan", f"notes: restore = the same note {r.text[:150]}")
# 2.272.0 F (#3038, review N3): the offline outbox sending a note again that was deleted since: 404, never "live"
r = Fr.post(B + f"/api/lists/{LID}/notes", json={"title": "Offline note", "client_ref": "p2272e1-ref-1"})
NID2 = r.json()["id"]
Fr.delete(B + f"/api/notes/{NID2}")
r = Fr.post(B + f"/api/lists/{LID}/notes", json={"title": "Offline note", "client_ref": "p2272e1-ref-1"})
check(r.status_code == 404, f"notes: the same client_ref of a note in the trash -> 404 {r.status_code} {r.text[:150]}")
Fr.delete(B + f"/api/notes/{NID}")
sql("UPDATE notes SET deleted_at=? WHERE id=?", (ago(days=400), NID))
out = run_purge(False)
check(sql("SELECT COUNT(*) FROM notes WHERE id=?", (NID,))[0][0] == 1 and "'notes': 1" in out, f"notes run: switch off = counted {out[-300:]}")
run_purge(True)
check(sql("SELECT COUNT(*) FROM notes WHERE id=?", (NID,))[0][0] == 0, "notes run: switch on = deleted for good")

print(f"p2272_e1_contacts_trash: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
