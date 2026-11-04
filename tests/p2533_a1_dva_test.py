#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.533.0 A1 (#4318, audit #2425): import, export and contacts say what they leave out instead of dropping it silently.
freelancer-matrix: import, office, contacts, wiki
 - F8 list CSV import: rows without a title, cells beyond the header, a cut title / description and a file that is not
   UTF-8 are named with their row number in the answer (warnings[].rows)
 - F14 bank CSV: the skipped rows by number and reason (skipped_rows) in the preview and in the import's answer
 - B41 vCard import: a card WITHOUT a REV does not overwrite a contact changed here since its last import (kept_newer,
   kept_norev, kept_names); an unchanged contact still takes the card's values
 - F18 account export: files the virus scanner locked are counted in the export's state (locked)
 - F15 account export: an attachment added while the export runs never comes as a row without its file (one snapshot)
 - F19 knowledge ZIP import with "replace": the files of a replaced page stay (not reproducible as a loss, checked here)
 - F20 undo of an account import: a mailbox set up since (password saved) stays and is counted in kept_rows
 - B42 delete dialog: the files a person sent in direct messages / groups are counted (purge.chat_files)
 - B44 organisation delete dialog: absences, bookings, equipment, vehicles ... named instead of "other entries"
Everything as a person without an organisation (the freelancer fixture) where the route is a person's one. Invented data.
usage: p2533_a1_dva_test.py <datadir>"""
import io
import json
import os
import struct
import subprocess
import sys
import zipfile
import zlib

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, CT, dbx, done, su_get, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

A = kt.setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
FU, F = freelancer(B, A, "frida")
F.patch(B + "/api/settings", json={"workspace": "private"})
NOW = "2026-11-04T10:00:00.000Z"


def inproc(code):
    """Python inside the app container (the app's own modules); -> the JSON of its last output line."""
    p = subprocess.run(["docker", "exec", "-i", "-w", "/app", CT, "python", "-"], input="import sys\nsys.path.insert(0, '/app')\n" + code,
                       capture_output=True, text=True)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (p.stdout[-300:] + p.stderr[-800:])}


def warn(j, start):
    return next((w for w in j.get("warnings") or [] if w["text"].startswith(start)), None)


# ================================================================== F8: list CSV import
LONG_T, LONG_N = "T" * 2100, "x" * 200050
csv_text = ("Title,Notes\n"
            "Erste Aufgabe,eins\n"            # row 2
            ",nur eine Notiz ohne Titel\n"    # row 3: no title
            "Dritte Aufgabe,drei,Zusatz\n"    # row 4: one cell more than the header
            f"{LONG_T},vier\n"                # row 5: title cut
            f"Fuenfte Aufgabe,{LONG_N}\n")    # row 6: description cut
r = F.post(B + "/api/import/csv", files={"file": ("liste.csv", csv_text.encode())}, data={"dry_run": "1"})
j = r.json() if r.ok else {}
check(r.ok and j["created"]["tasks"] == 4, f"F8: the preview counts the four rows with a title {r.status_code} {r.text[:300]}")
w = warn(j, "Rows without a title")
check(w and w.get("rows") == [3], f"F8: the row without a title is named with its number {w}")
w = warn(j, "Cells without a column header")
check(w and w.get("rows") == [4], f"F8: the cell beyond the header is named with its row {w}")
w = warn(j, "Title longer than 2000")
check(w and w.get("rows") == [5], f"F8: the cut title is named with its row {w}")
w = warn(j, "Description longer than 200000")
check(w and w.get("rows") == [6], f"F8: the cut description is named with its row {w}")
r = F.post(B + "/api/import/csv", files={"file": ("cp.csv", b"Title\nCaf\xe9 f\xfcr 5 \x80\n")}, data={"dry_run": "1"})
check(r.ok and warn(r.json(), "The file is not UTF-8"), f"F8: a Windows-1252 file is named, not read silently {r.text[:300]}")
# review 2.533.0: TickTick's preamble counts: the row number is the file's line (was: counted from the header)
TT_HEAD = '"Folder Name","List Name","Title","Content","taskId"\n'
tt = ('"Date: 2026-10-01"\n\n' + TT_HEAD + '"Ordner","TT Liste","Eins","","t1"\n' + '"Ordner","TT Liste","Zwei","","t2","Zusatz"\n')
r = F.post(B + "/api/import/ticktick", files={"file": ("tt.csv", tt.encode(), "text/csv")}, data={"dry_run": "1"})
w = warn(r.json(), "Cells without a column header") if r.ok else None
check(w and w.get("rows") == [5], f"F8: a TickTick row is named with its line in the file (preamble counted) {w} {r.text[:300]}")
r = F.post(B + "/api/import/csv", files={"file": ("ok.csv", "Title\nGanz normal\n".encode())}, data={"dry_run": "1"})
check(r.ok and not r.json().get("warnings"), f"F8: a clean UTF-8 file gives no warning {r.text[:300]}")

# ================================================================== F14: bank CSV, skipped rows by number
BK = "/api/office/bank"
bank_csv = "Datum;Text;Betrag\n01.10.2026;Miete Oktober;-500,00\nkaputt;Fehlerhafte Zeile;-3,00\n02.10.2026;Honorar;1000,00\n"
MAP = {"date": 0, "title": 1, "amount": 2, "decimal": ",", "date_format": "DD.MM.YYYY"}
r = F.post(B + BK + "/import/preview", json={"text": bank_csv, "filename": "konto.csv", "mapping": MAP})
j = r.json() if r.ok else {}
sk = j.get("skipped_rows") or []
check(r.ok and j.get("skipped") == 1 and len(sk) == 1 and sk[0]["n"] == 2 and "date" in sk[0]["error"],
      f"F14: the preview names the skipped row with number and reason {r.status_code} {r.text[:300]}")
r = F.post(B + BK + "/import", json={"text": bank_csv, "filename": "konto.csv", "mapping": MAP})
j = r.json() if r.status_code == 201 else {}
sk = j.get("skipped_rows") or []
check(r.status_code == 201 and j["count"] == 2 and len(sk) == 1 and sk[0]["n"] == 2 and sk[0]["error"],
      f"F14: the import's answer names the skipped row, not only a count {r.status_code} {r.text[:300]}")


# ================================================================== B41: vCard without REV
def card(uid, fn, email, note=None):
    L = ["BEGIN:VCARD", "VERSION:3.0", f"UID:{uid}", f"FN:{fn}", f"N:{fn.split()[-1]};{fn.split()[0]};;;", f"EMAIL;TYPE=INTERNET:{email}"]
    return "\r\n".join(L + ([f"NOTE:{note}"] if note else []) + ["END:VCARD"]) + "\r\n"


def vimp(s, bid, text):
    r = s.post(B + f"/api/books/{bid}/import", files={"file": ("k.vcf", text.encode(), "text/vcard")})
    return r.json() if r.ok else {"status": r.status_code, "text": r.text[:300]}


BID = F.post(B + "/api/books", json={"name": "Import 4318"}).json()["id"]
j = vimp(F, BID, card("dva-1", "Erika Muster", "erika@example.com", "alte Notiz") + card("dva-2", "Max Muster", "max@example.com"))
check(j.get("created") == 2, f"B41: two contacts imported {j}")
C1 = dbx("SELECT id FROM contacts WHERE uid=?", ("dva-1",))[0][0]
r = F.patch(B + f"/api/contacts/{C1}", json={"note": "neue Notiz hier"})
check(r.ok, "B41: the note changed here " + r.text[:200])
j = vimp(F, BID, card("dva-1", "Erika Muster", "erika.alt@example.com", "alte Notiz") + card("dva-2", "Max Muster", "max.neu@example.com"))
d1, d2 = F.get(B + f"/api/contacts/{C1}").json(), F.get(B + "/api/contacts/" + str(dbx("SELECT id FROM contacts WHERE uid=?", ("dva-2",))[0][0])).json()
check(j.get("kept_newer") == 1 and j.get("kept_norev") == 1 and j.get("kept_names") == ["Erika Muster"],
      f"B41: a card without REV over a contact changed here is counted and named, not written {j}")
check(d1["note"] == "neue Notiz hier" and d1["emails"][0]["value"] == "erika@example.com",
      f"B41: the newer values here stay ({d1['note']!r}, {d1['emails']})")
check(d2["emails"][0]["value"] == "max.neu@example.com", f"B41: an unchanged contact takes the card's values {d2['emails']}")
# review 2.533.0: a contact made here and never edited nor imported from a file keeps its values too
r = F.post(B + "/api/contacts", json={"book_id": BID, "fn": "Hanna Hier"})
check(r.ok, "B41: a contact made here " + r.text[:200])
C3 = r.json()["id"]
u3 = dbx("SELECT uid FROM contacts WHERE id=?", (C3,))[0][0]
j = vimp(F, BID, card(u3, "Hanna Hier", "hanna.alt@example.com", "Notiz der Karte"))
d3 = F.get(B + f"/api/contacts/{C3}").json()
check(j.get("kept_norev") == 1 and not d3.get("note") and not d3.get("emails"),
      f"B41: a card without REV does not overwrite a contact made here (never imported) {j} {d3.get('emails')}")

# ================================================================== F18: export state counts locked files
FT = F.post(B + "/api/tasks", json={"title": "Mit Anhang 4318"}).json()["id"]
r = F.post(B + f"/api/tasks/{FT}/attachments", files={"file": ("bericht.txt", b"Anhang mit Text\n" * 20, "text/plain")})
check(r.ok, "F18: an attachment uploaded " + r.text[:200])
FA = dbx("SELECT id FROM attachments WHERE task_id=? ORDER BY id", (FT,))[0][0]
dbx("INSERT INTO upload_scan(kind, ref_id, ver, state, sig, created_at) VALUES('att', ?, 0, 'infected', 'Test-Signatur', ?) "
    "ON CONFLICT (kind, ref_id, ver) DO UPDATE SET state='infected', sig='Test-Signatur'", (FA, NOW))
r = F.post(B + "/api/account/export")
check(r.status_code == 202, "F18: the export started " + r.text[:200])
st = until(lambda: (lambda x: x if x.get("state") != "running" else None)(F.get(B + "/api/account/export").json()), 120) or {}
check(st.get("state") == "done" and st.get("locked") == 1, f"F18: the export's state counts the locked file (the page shows it) {st}")

# ================================================================== F15: one snapshot for files and rows
AT = A.post(B + "/api/tasks", json={"title": "Export waehrend Upload 4318"}).json()["id"]
r = A.post(B + f"/api/tasks/{AT}/attachments", files={"file": ("erst.txt", b"erste Datei\n" * 20, "text/plain")})
check(r.ok, "F15: the first attachment " + r.text[:200])
RACE = """
import json, os
from kalmido.admin import acctexport as X
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
UID, TID, NOW = %d, %d, %r
orig, hit = X._put_file, []
def put(c, zf, out, name, full):
    if not hit:  # a second request adds an attachment while the export is between its file and its row reads
        hit.append(name)
        c2 = connect()
        with system_ctx(c2):
            r = c2.execute("SELECT size, path FROM attachments WHERE task_id=? ORDER BY id LIMIT 1", (TID,)).fetchone()
            c2.execute("INSERT INTO attachments(task_id, name, mime, size, path, created_at) VALUES(?,?,?,?,?,?)",
                       (TID, "dazwischen.txt", "text/plain", r["size"], r["path"], NOW))
        c2.commit()
        c2.close()
    return orig(c, zf, out, name, full)
X._put_file = put
os.makedirs(X._udir(UID), mode=0o700, exist_ok=True)
X.umz_run(UID, "dva4318")
print(json.dumps({"hit": len(hit), "state": X.umz_status(UID).get("state")}))
""" % (ALICE, AT, NOW)
res = inproc(RACE)
check(res.get("hit") == 1 and res.get("state") == "done", f"F15: the export ran with an attachment added meanwhile {res}")
r = su_get(A, B + "/api/account/export/file")
rows = []
if r.ok:
    z = zipfile.ZipFile(io.BytesIO(r.content))
    rows = json.loads(z.read("data/attachments.json")) if "data/attachments.json" in z.namelist() else []
nofile = [x.get("name") for x in rows if not x.get("file")]  # Alice's only attachments: the first one and the one added meanwhile
check(r.ok and rows and not nofile, f"F15: no attachment row without its file in the export ({r.status_code}, {len(rows)} rows, {nofile})")
dbx("DELETE FROM attachments WHERE task_id=? AND name='dazwischen.txt'", (AT,))


# ================================================================== F19: knowledge ZIP "replace" keeps a page's files
def png():
    raw = b"\x00\xff\x00\x00"
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def wzip(members):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as zz:
        for n, d in members:
            zz.writestr(n, d)
    return b.getvalue()


r = F.post(B + "/api/wiki/import", params={"space": "private"},
           files={"file": ("w.zip", wzip([("Doku/Seite 4318.md", "Text mit Bild ![[bild.png]]"), ("Doku/bild.png", png())]), "application/zip")})
WP = (r.json().get("created") or [None])[0] if r.ok else None
nf = lambda: dbx("SELECT COUNT(*) FROM wiki_files WHERE page_id=? AND deleted_at IS NULL", (WP,))[0][0] if WP else -1  # noqa: E731
check(WP and nf() == 1, f"F19: the page came with its picture ({r.status_code} {r.text[:300]}, files {nf()})")
r = F.post(B + "/api/wiki/import", params={"space": "private", "replace": "1"},
           files={"file": ("w.zip", wzip([("Doku/Seite 4318.md", "Neuer Text ohne Bild")]), "application/zip")})
check(r.ok and WP in (r.json().get("updated") or []) and nf() == 1,
      f"F19: replacing the page keeps its file (no loss, the finding is not reproducible) {r.text[:300]} files {nf()}")

# ================================================================== F20: account import undo keeps a mailbox set up since
UNDO = """
import json
from kalmido.admin.acctexport import umz_user_conn
from kalmido.admin.acctimport import umz_undo
from kalmido.core.db import connect, insert_id
from kalmido.core.pg import system_ctx
UID, NOW = %d, %r
c = connect()
out = {}
for k, secret, error in (("kept", "sealed-secret", ""), ("gone", "", "password")):
    with system_ctx(c):
        mid = insert_id(c, "INSERT INTO hub_mailboxes(ws, owner_id, secret, error, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                        ("u%%d-4318-%%s" %% (UID, k), UID, secret, error, UID, NOW, NOW))
        iid = insert_id(c, "INSERT INTO imports(user_id, source, file_name, created, report, created_at) VALUES(?,?,?,?,?,?)",
                        (UID, "kalmido", "dva.zip", json.dumps({"hub_mailboxes": [mid]}), "{}", NOW))
    c.commit()
    umz_user_conn(c, UID)
    row = c.execute("SELECT * FROM imports WHERE id=?", (iid,)).fetchone()
    res = umz_undo(c, UID, row)
    with system_ctx(c):
        left = c.execute("SELECT COUNT(*) FROM hub_mailboxes WHERE id=?", (mid,)).fetchone()[0]
        c.execute("DELETE FROM hub_mailboxes WHERE id=?", (mid,))
    c.commit()
    out[k] = {"kept_rows": res["kept_rows"], "left": left}
print(json.dumps(out))
""" % (FU, NOW)
res = inproc(UNDO)
check(res.get("kept", {}).get("left") == 1 and res["kept"]["kept_rows"] >= 1,
      f"F20: a mailbox with a saved password stays and is counted (kept_rows) {res}")
check(res.get("gone", {}).get("left") == 0 and res["gone"]["kept_rows"] == 0, f"F20: an untouched one still goes, not counted {res}")

# ================================================================== B42: delete dialog counts the chat files
room = dbx("INSERT INTO tchat_rooms(kind, a, b, created_at, last_at) VALUES('dm', ?, ?, ?, ?) RETURNING id", (FU, ALICE, NOW, NOW))[0][0]
msg = dbx("INSERT INTO tchat_msgs(room_id, user_id, body, created_at) VALUES(?, ?, 'Datei anbei', ?) RETURNING id", (room, FU, NOW))[0][0]
dbx("INSERT INTO tchat_files(message_id, room_id, user_id, name, mime, size, path, created_at) VALUES(?,?,?,?,?,?,?,?)",
    (msg, room, FU, "plan.pdf", "application/pdf", 10, "tchat/none-4318.pdf", NOW))
r = A.get(B + f"/api/users/{FU}/delete-info")
p = r.json().get("purge", {}) if r.ok else {}
check(r.ok and p.get("chat_files") == 1 and p.get("dms") == 1,
      f"B42: the delete dialog gets the number of the person's chat files (they go for good) {r.status_code} {p}")
dbx("DELETE FROM tchat_rooms WHERE id=?", (room,))

# ================================================================== B44: organisation delete dialog names more areas
MORE = """
import json
from kalmido.accounts.orgretain import ODL_MORE, odl_more_text
from kalmido.core.db import connect
from kalmido.core.merges import mg_fk_refs
from kalmido.core.pg import system_ctx
c = connect()
with system_ctx(c):
    cascade = {t for t, col, d in mg_fk_refs(c, "orgs") if d == "c"}
new = ["hub_absences", "hub_bookings", "office_equipment", "office_fixed_costs", "office_doc_templates", "office_texts",
       "office_vehicles", "office_meals", "life_trip_costs"]
named = {t for _k, _w, t in ODL_MORE}
print(json.dumps({"missing": [t for t in new if t not in named], "not_cascade": [t for t in new if t not in cascade],
                  "text": odl_more_text({"vehicles": 2, "absences": 1, "other": 3})}))
"""
res = inproc(MORE)
check(res.get("missing") == [] and res.get("not_cascade") == [], f"B44: the areas are named and really go with the organisation {res}")
check(res.get("text") == "1 absence, 2 vehicles, 3 other entries", f"B44: the dialog text names them {res}")

sys.exit(done("p2533_a1_dva"))
