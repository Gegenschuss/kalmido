#!/usr/bin/env python3
"""2.143.0 API tests, part C, own container (start.sh). Invented names and files only.
 - #2154 the share target without the service worker (POST /share): a Word file, a ZIP, an MP3, a contact card (.vcf)
   and a calendar file (.ics) in one go = one new inbox task with all five attached; a path in a file name is cut off,
   control characters become "_"; an HTML file claiming to be a picture is never shown inline (download, sandbox)
 - #2153 sent twice from the offline outbox = stored once: a manual time entry with its client_id, a new note with its
   client_ref (201 the first time, 200 with the same note the second time); another person may use the same ref
 - a person without an organisation (freelancer-matrix: tasks, time, notes): share, a repeated note and a repeated
   time entry the same way
 - 2.143.0 C2 review: the same ref sent several times at once (tab + service worker) = one row and no server error, for
   notes and time entries; a ref of a note in another list never answers that note; the manifest names the upload limit
   per file for the service worker's share target
usage: p2143_c_api_test.py <datadir>"""
import io
import os
import re
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


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
    return s


if os.environ.get("P2143C_NOSTART") != "1":
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
FEAT = "collab,comments,time,contacts,events,files"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
c = dbx.connect(DATA)


def docx():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
    return b.getvalue()


def zipped():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("readme.txt", "invented content")
    return b.getvalue()


MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 400
VCF = b"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Erika Example\r\nEMAIL:erika@example.com\r\nEND:VCARD\r\n"
ICS = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//example//test//EN\r\nBEGIN:VEVENT\r\nUID:p2143c@example.com\r\n"
       b"DTSTART:20261105T100000Z\r\nDTEND:20261105T110000Z\r\nSUMMARY:Invented meeting\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
FILES = [("file", ("Offer.docx", docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
         ("file", ("photos.zip", zipped(), "application/zip")),
         ("file", ("voice memo.mp3", MP3, "audio/mpeg")),
         ("file", ("../../erika\x01.vcf", VCF, "text/x-vcard")),
         ("file", ("meeting.ics", ICS, "text/calendar"))]


def share(s, files, **form):
    r = s.post(B + "/share", files=files, data=form, allow_redirects=False)
    m = re.search(r"#t/(\d+)", r.headers.get("Location", ""))
    check(r.status_code == 303 and m and "refused" not in r.headers.get("Location", ""),
          f"share: a new task {r.status_code} {r.headers.get('Location')} {r.text[:200]}")
    return int(m.group(1)) if m else 0


def atts(tid):
    return c.execute("SELECT id, name, mime FROM attachments WHERE task_id=? ORDER BY id", (tid,)).fetchall()


# ---------------------------------------------------------------- #2154 every file type
T = share(A, FILES, title="Shared from the phone")
rows = atts(T)
names = [x["name"] for x in rows]
check(len(rows) == 5, f"all five files attached {names}")
check({"Offer.docx", "photos.zip", "voice memo.mp3", "meeting.ics"} <= set(names), f"the names stay {names}")
check("erika_.vcf" in names and not any("/" in n or ".." in n for n in names), f"no path, no control characters {names}")
t = A.get(B + f"/api/tasks/{T}").json()
check(t.get("title") == "Shared from the phone", f"the task's title {t.get('title')}")
inbox = [x for x in A.get(B + "/api/state").json()["lists"] if x.get("is_inbox")]
check(inbox and t.get("list_id") == inbox[0]["id"], "the task is in the inbox")
for x in rows:
    r = A.get(B + f"/api/attachments/{x['id']}")
    check(r.ok and r.content[:2] in (b"PK", b"ID", b"BE"), f"{x['name']}: the bytes come back {r.status_code}")
    check("attachment" in r.headers.get("Content-Disposition", ""), f"{x['name']}: a download, not shown inline")

# an active file claiming to be a picture: never inline
T2 = share(A, [("file", ("cat.png", b"<html><script>void 0</script></html>", "image/png"))])
x = atts(T2)[0]
r = A.get(B + f"/api/attachments/{x['id']}")
check(r.ok and not r.headers.get("Content-Type", "").startswith(("text/html", "image/")), f"html bytes are no picture {r.headers.get('Content-Type')} ({x['mime']})")
check(r.headers.get("X-Content-Type-Options") == "nosniff", "nosniff")
check("sandbox" in r.headers.get("Content-Security-Policy", ""), "a sandbox around it")

# a foreign page may not use the share form
r = A.post(B + "/share", files=FILES[:1], headers={"Sec-Fetch-Site": "cross-site"}, allow_redirects=False)
check(r.status_code == 403, f"no share from another site {r.status_code}")

# ---------------------------------------------------------------- #2153 sent twice = stored once
PRIV = A.post(B + "/api/lists", json={"name": "Notes here", "org_id": None}).json()["id"]
check(A.patch(B + f"/api/lists/{PRIV}", json={"time_tracking": True}).ok, "setup: time tracking in the list")
body = {"list_id": PRIV, "start": "2026-10-19T08:00:00Z", "end": "2026-10-19T09:30:00Z", "note": "Offline entry", "client_id": "p2143c-te-1"}
r1, r2 = A.post(B + "/api/time/entries", json=body), A.post(B + "/api/time/entries", json=body)
check(r1.ok and r2.ok and r1.json().get("id") == r2.json().get("id"), f"time entry: the repeat answers the same entry {r1.text[:150]} {r2.text[:150]}")
n = c.execute("SELECT COUNT(*) AS n FROM time_entries WHERE client_id='p2143c-te-1'").fetchone()["n"]
check(n == 1, f"time entry stored once ({n})")
r3 = A.post(B + "/api/time/entries", json={**body, "client_id": None, "note": "Without id"})
check(r3.ok and r3.json().get("id") != r1.json().get("id"), "without a client id: a new entry as before")

nb = {"title": "Written on the train", "body": "Offline words", "client_ref": "p2143c-note-1"}
r1, r2 = A.post(B + f"/api/lists/{PRIV}/notes", json=nb), A.post(B + f"/api/lists/{PRIV}/notes", json=nb)
check(r1.status_code == 201 and r2.status_code == 200 and r1.json().get("id") == r2.json().get("id"),
      f"note: the repeat answers the same note {r1.status_code} {r2.status_code}")
check(r2.json().get("body") == "Offline words" and "client_ref" not in r2.json(), "note: the full note, no device id in the answer")
n = c.execute("SELECT COUNT(*) AS n FROM notes WHERE list_id=?", (PRIV,)).fetchone()["n"]
check(n == 1, f"note stored once ({n})")
BL = Bo.post(B + "/api/lists", json={"name": "Bob's notes", "org_id": None}).json()["id"]
r = Bo.post(B + f"/api/lists/{BL}/notes", json=nb)
check(r.status_code == 201 and r.json().get("id") != r1.json().get("id"), "another person with the same ref: an own note")
r = Bo.post(B + f"/api/lists/{PRIV}/notes", json={**nb, "client_ref": "p2143c-note-2"})
check(r.status_code in (403, 404), f"no note in a list that is not shared with me {r.status_code}")
nid = r1.json()["id"]
r = A.patch(B + f"/api/notes/{nid}", json={"body": "Changed offline", "expect_updated_at": r1.json()["updated_at"]})
check(r.ok and r.json().get("body") == "Changed offline", "an offline change of it goes through")
r = A.patch(B + f"/api/notes/{nid}", json={"body": "Stale base", "expect_updated_at": r1.json()["updated_at"]})
check(r.status_code == 409 and r.json().get("note", {}).get("body") == "Changed offline", f"a stale base = 409 with the server's note {r.status_code}")

# ---------------------------------------------------------------- 2.143.0 C2 (#2153): the same ref at once
def burst(s, url, js, n=6):
    s2 = [sess("alice") for _ in range(n)] if s is A else [s] * n
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(lambda x: x.post(url, json=js), s2))


rs = burst(A, B + f"/api/lists/{PRIV}/notes", {"title": "At once", "body": "Twice", "client_ref": "p2143c2-burst"})
check(all(r.status_code in (200, 201) for r in rs) and len({r.json().get("id") for r in rs}) == 1,
      f"note sent at once: all answers name one note {[r.status_code for r in rs]}")
n = c.execute("SELECT COUNT(*) AS n FROM notes WHERE client_ref='p2143c2-burst'").fetchone()["n"]
check(n == 1, f"note sent at once: stored once ({n})")
rs = burst(A, B + "/api/time/entries", {**body, "client_id": "p2143c2-burst", "note": "At once"})
check(all(r.ok for r in rs) and len({r.json().get("id") for r in rs}) == 1, f"time entry sent at once: one entry {[r.status_code for r in rs]}")
n = c.execute("SELECT COUNT(*) AS n FROM time_entries WHERE client_id='p2143c2-burst'").fetchone()["n"]
check(n == 1, f"time entry sent at once: stored once ({n})")
# a ref of a note in another list: never that note
OTH = A.post(B + "/api/lists", json={"name": "Other notes", "org_id": None}).json()["id"]
r = A.post(B + f"/api/lists/{OTH}/notes", json=nb)
check(r.status_code < 500 and r.json().get("id") != nid, f"the ref of a note in another list does not answer it {r.status_code} {r.text[:120]}")
# the share target's limit per file
m = A.get(B + "/manifest.json").json()
check(isinstance(m.get("kalmido_max_file_mb"), int) and m["kalmido_max_file_mb"] > 0, f"the manifest names the upload limit {m.get('kalmido_max_file_mb')}")

# ---------------------------------------------------------------- a person without an organisation
# freelancer-matrix: tasks, time, notes
FID, Fr = freelancer(B, A)
FT = share(Fr, FILES[2:4])
check(len(atts(FT)) == 2, "freelancer: share with an MP3 and a contact card")
check(Fr.get(B + f"/api/tasks/{FT}").ok and A.get(B + f"/api/tasks/{FT}").status_code in (403, 404), "freelancer: the task is private")
FL = Fr.post(B + "/api/lists", json={"name": "My notes", "org_id": None}).json()["id"]
check(Fr.patch(B + f"/api/lists/{FL}", json={"time_tracking": True}).ok, "freelancer setup: time tracking in the list")
fb = {**nb, "client_ref": "p2143c-fr-1"}
r1, r2 = Fr.post(B + f"/api/lists/{FL}/notes", json=fb), Fr.post(B + f"/api/lists/{FL}/notes", json=fb)
check(r1.status_code == 201 and r2.status_code == 200 and r1.json().get("id") == r2.json().get("id"), "freelancer: a note sent twice = one")
tb = {**body, "list_id": FL, "client_id": "p2143c-fr-te"}
r1, r2 = Fr.post(B + "/api/time/entries", json=tb), Fr.post(B + "/api/time/entries", json=tb)
check(r1.ok and r2.ok and r1.json().get("id") == r2.json().get("id"), f"freelancer: a time entry sent twice = one {r1.text[:120]}")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
