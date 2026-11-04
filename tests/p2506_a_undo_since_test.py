#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.506.0 (#4299): the undo of an account import keeps what changed since it, in every table, and uses the trashes.
Invented names only (example.com). A person without an organisation exports, a second one imports (freelancer-matrix: own):
 - habits (a day logged since), filters, templates, time entries, journal days, bookmarks: the changed one stays, the other goes
 - file store: a folder with a file added since stays with that file, its unchanged file goes into the trash and reads back
   after a restore (the bytes stay); a folder nothing happened in goes into the trash as a whole
 - knowledge pages and tables: the changed one stays whole, the other goes into its trash and comes back from there
 - the answer counts both
 - a stored file of a kept row is still on the disk
usage: p2506_a_undo_since_test.py <datadir>"""
import base64
import os
import sys
from datetime import datetime, timedelta, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, until  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else kt.DATA
KEY = base64.b64encode(os.urandom(32)).decode()
BYTES = {n: f"Inhalt {n} ".encode() + os.urandom(6).hex().encode() for n in ("bleibt", "geht", "still", "neu")}
TS = "2026-01-05T10:00:00+00:00"


def one(sql, args=()):
    r = kt.dbx(sql, args)
    return r[0][0] if r else None


def export_of(s):
    r = s.post(B + "/api/account/export")
    assert r.status_code == 202, r.text
    j = until(lambda: (lambda x: x if x.get("state") != "running" else None)(s.get(B + "/api/account/export").json()), 120)
    assert j and j.get("state") == "done", j
    r = kt.su_get(s, B + "/api/account/export/file")
    assert r.ok, r.text[:200]
    return r.content


def state_of(s, iid):
    j = s.get(B + f"/api/account/import/{iid}").json()
    return j if j.get("state") not in ("checking", "running", "upload") else None


def upload(s, data):
    r = s.post(B + "/api/account/import", json={"size": len(data), "name": "kalmido-account.zip"})
    assert r.ok, r.text
    iid = r.json()["id"]
    r = s.put(B + f"/api/account/import/{iid}?offset=0", data=data, headers={"Content-Type": "application/octet-stream"})
    assert r.ok, r.text
    return iid, until(lambda: state_of(s, iid), 180) or {}


def name_of(table, col, val, uid_col, uid):
    return one(f"SELECT id FROM {table} WHERE {col}=? AND {uid_col}=?", (val, uid))


kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P2506")
A = kt.setup()
FEAT = FEATURES + ",sheets"
FID, Fr = freelancer(B, A, features=FEAT)
GID, Gi = freelancer(B, A, "gina", features=FEAT)

# ---------------------------------------------------------------- what the person moving has
for n in ("Laufen", "Lesen"):
    check(Fr.post(B + "/api/habits", json={"name": n}).status_code in (200, 201), f"habit {n}")
    h = name_of("habits", "name", n, "user_id", FID)
    check(Fr.post(B + f"/api/habits/{h}/log", json={"day": "2026-01-02", "count": 1}).ok, f"a logged day of {n}")
for n in ("Filter eins", "Filter zwei"):
    check(Fr.post(B + "/api/filters", json={"name": n, "rules": {"op": "and"}}).status_code in (200, 201), f"filter {n}")
TL = Fr.post(B + "/api/lists", json={"name": "Vorlagenquelle"}).json()["id"]
for n in ("Vorlage eins", "Vorlage zwei"):
    t = Fr.post(B + "/api/tasks", json={"title": f"Aufgabe {n}", "list_id": TL}).json()["id"]
    check(Fr.post(B + "/api/templates", json={"task_id": t, "name": n}).status_code in (200, 201), f"template {n}")
for n in ("Zeit eins", "Zeit zwei"):
    kt.dbx("""INSERT INTO time_entries(user_id, start, "end", seconds, note, source, created_at, updated_at) VALUES(?,?,?,?,?,'manual',?,?)""",
           (FID, TS, "2026-01-05T11:00:00+00:00", 3600, n, TS, TS))
for d in ("2026-01-03", "2026-01-04"):
    kt.dbx("INSERT INTO journal(user_id, day, text, updated_at) VALUES(?, ?, 'Eintrag', ?)", (FID, d, TS))
for u in ("eins", "zwei"):
    check(Fr.post(B + "/api/bookmarks", json={"url": f"https://www.example.com/{u}"}).status_code in (200, 201), f"bookmark {u}")

F1 = Fr.post(B + "/api/files/folders", json={"space": "private", "name": "Mit Neuem"}).json()["id"]
F2 = Fr.post(B + "/api/files/folders", json={"space": "private", "name": "Ohne Neues"}).json()["id"]
check(Fr.post(B + "/api/files/folders", json={"space": "private", "name": "Ziel"}).status_code == 201, "a folder a file moves into later")
OLD = Gi.post(B + "/api/files/upload", data={"space": "private"}, files={"file": ("alt.txt", b"Alte Datei", "text/plain")}).json()["items"][0]["id"]
for parent, n in ((F1, "bleibt"), (F1, "geht"), (F2, "still")):
    r = Fr.post(B + "/api/files/upload", data={"parent_id": str(parent)}, files={"file": (f"{n}.txt", BYTES[n], "text/plain")})
    check(r.status_code == 201, f"file {n} {r.status_code}")
PAGES = {}
for n in ("Seite Bleibt", "Seite Geht"):
    r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": n, "body": "Text"})
    check(r.ok, f"page {n} {r.text[:100]}")
SHEETS = {}
for n in ("Tabelle Bleibt", "Tabelle Geht"):
    r = Fr.post(B + "/api/sheets", json={"title": n, "space": "private"})
    check(r.status_code == 201, f"table {n}")
    sh = r.json()
    r = Fr.put(B + f"/api/sheets/{sh['id']}/cells", json={"cells": [{"row_id": sh["rows"][0]["id"], "col_id": sh["columns"][0]["id"], "raw": "Wert"}]})
    check(r.ok, f"a cell of {n} {r.text[:100]}")

# ---------------------------------------------------------------- the import
iid, j = upload(Gi, export_of(Fr))
check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
r = Gi.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}})
check(r.status_code == 202, f"the run {r.text[:160]}")
j = until(lambda: state_of(Gi, iid), 180) or {}
check(j.get("state") == "done", f"done {j.get('state')} {j.get('error')}")
IMP = (j.get("result") or {}).get("import_id")
check(IMP, "an import to undo")

at = one("SELECT created_at FROM imports WHERE id=?", (IMP,))
since = datetime.fromisoformat(at.replace("Z", "+00:00"))
check(until(lambda: datetime.now(timezone.utc) >= since + timedelta(seconds=1.1) or None, 10), "the clock is past the import")


def gid(table, col, val):
    return name_of(table, col, val, "user_id", GID)


# ---------------------------------------------------------------- the person works on
HB, HG = gid("habits", "name", "Laufen"), gid("habits", "name", "Lesen")
check(Gi.post(B + f"/api/habits/{HB}/log", json={"day": "2026-01-20", "count": 1}).ok, "a day logged since the import")
FB, FG = gid("filters", "name", "Filter eins"), gid("filters", "name", "Filter zwei")
check(Gi.patch(B + f"/api/filters/{FB}", json={"name": "Filter eins neu"}).ok, "a filter changed")
TB, TG = gid("templates", "name", "Vorlage eins"), gid("templates", "name", "Vorlage zwei")
check(Gi.patch(B + f"/api/templates/{TB}", json={"name": "Vorlage eins neu"}).ok, "a template changed")
EB, EG = gid("time_entries", "note", "Zeit eins"), gid("time_entries", "note", "Zeit zwei")
check(Gi.patch(B + f"/api/time/entries/{EB}", json={"note": "Zeit eins neu"}).ok, "a time entry changed")
kt.dbx("UPDATE journal SET text='Weitergeschrieben', updated_at=? WHERE user_id=? AND day='2026-01-03'", (datetime.now(timezone.utc).isoformat(), GID))
BB = one("SELECT id FROM bookmarks WHERE user_id=? AND url ILIKE '%/eins'", (GID,))
BG = one("SELECT id FROM bookmarks WHERE user_id=? AND url ILIKE '%/zwei'", (GID,))
check(Gi.patch(B + f"/api/bookmarks/{BB}", json={"note": "Meine Notiz"}).ok, "a bookmark changed")

GF1, GF2 = (one("SELECT id FROM fs_nodes WHERE name=? AND owner_id=?", (n, GID)) for n in ("Mit Neuem", "Ohne Neues"))
GGEHT = one("SELECT id FROM fs_nodes WHERE name='geht.txt' AND owner_id=?", (GID,))
GSTILL = one("SELECT id FROM fs_nodes WHERE name='still.txt' AND owner_id=?", (GID,))
r = Gi.post(B + "/api/files/upload", data={"parent_id": str(GF1)}, files={"file": ("neu.txt", BYTES["neu"], "text/plain")})
check(r.status_code == 201, "a file laid into an imported folder since")
NEW = r.json()["items"][0]["id"]
GZ = one("SELECT id FROM fs_nodes WHERE name='Ziel' AND owner_id=?", (GID,))
check(Gi.patch(B + f"/api/files/nodes/{OLD}", json={"parent_id": GZ}).ok, "an older file of the person moved into an imported folder")
PB = one("SELECT id FROM wiki_pages WHERE path='Seite Bleibt' AND owner_id=?", (GID,))
PG = one("SELECT id FROM wiki_pages WHERE path='Seite Geht' AND owner_id=?", (GID,))
check(Gi.patch(B + f"/api/wiki/pages/{PB}", json={"body": "Text weitergeschrieben"}).ok, "a page changed")
SB = one("SELECT id FROM sheets WHERE title='Tabelle Bleibt' AND owner_id=?", (GID,))
SG = one("SELECT id FROM sheets WHERE title='Tabelle Geht' AND owner_id=?", (GID,))
sb = Gi.get(B + f"/api/sheets/{SB}").json()
cells_before = one("SELECT COUNT(*) FROM sheet_cells WHERE sheet_id=?", (SB,))
col2 = sb["columns"][-1]["id"]
check(Gi.put(B + f"/api/sheets/{SB}/cells", json={"cells": [{"row_id": sb["rows"][0]["id"], "col_id": col2, "raw": "Geändert"}]}).ok, "a cell changed")

# ---------------------------------------------------------------- the undo
r = Gi.post(B + f"/api/imports/{IMP}/undo", json={})
check(r.ok, f"the undo {r.status_code} {r.text[:200]}")
u = r.json() if r.ok else {}
check(u.get("kept_rows", 0) >= 9, f"the answer counts what stays {u}")
check(u.get("trash_rows", 0) >= 4, f"the answer counts what went into a trash {u}")


def there(table, rid):
    return bool(kt.dbx(f"SELECT 1 FROM {table} WHERE id=?", (rid,)))


check(there("habits", HB) and one("SELECT COUNT(*) FROM habit_logs WHERE habit_id=?", (HB,)) == 2, "the habit with a day logged since stays, with both days")
check(not there("habits", HG), "the untouched habit goes")
check(there("filters", FB) and not there("filters", FG), "the changed filter stays, the other goes")
check(there("templates", TB) and not there("templates", TG), "the changed template stays, the other goes")
check(there("time_entries", EB) and not there("time_entries", EG), "the changed time entry stays, the other goes")
check(kt.dbx("SELECT 1 FROM journal WHERE user_id=? AND day='2026-01-03'", (GID,)) and not kt.dbx("SELECT 1 FROM journal WHERE user_id=? AND day='2026-01-04'", (GID,)),
      "the journal day written on stays, the other goes")
check(there("bookmarks", BB) and not there("bookmarks", BG), "the changed bookmark stays, the other goes")

live = lambda i: not one("SELECT deleted_at FROM fs_nodes WHERE id=?", (i,))  # noqa: E731
check(there("fs_nodes", GF1) and live(GF1) and live(NEW), "the folder with a file added since stays with that file")
check(Gi.get(B + f"/api/files/nodes/{NEW}/content").content == BYTES["neu"], "the new file reads back")
check(there("fs_nodes", GGEHT) and not live(GGEHT), "its unchanged file lies in the trash")
check(there("fs_nodes", GF2) and not live(GF2), "the folder nothing happened in lies in the trash")
check(live(GZ) and live(OLD) and Gi.get(B + f"/api/files/nodes/{OLD}/content").content == b"Alte Datei",
      "review: a file moved into an imported folder keeps that folder, it does not go into the trash with it")
check(Gi.post(B + f"/api/files/nodes/{GGEHT}/restore").ok, "the file comes back from the trash")
check(Gi.get(B + f"/api/files/nodes/{GGEHT}/content").content == BYTES["geht"], "with its bytes")
check(Gi.post(B + f"/api/files/nodes/{GF2}/restore").ok and Gi.get(B + f"/api/files/nodes/{GSTILL}/content").content == BYTES["still"],
      "the folder comes back with its file and its bytes")

check(not one("SELECT deleted_at FROM wiki_pages WHERE id=?", (PB,)), "the changed page stays")
check(one("SELECT deleted_at FROM wiki_pages WHERE id=?", (PG,)), "the other page lies in the knowledge trash")
check(one("SELECT COUNT(*) FROM sheet_cells WHERE sheet_id=?", (SB,)) >= cells_before and not one("SELECT deleted_at FROM sheets WHERE id=?", (SB,)),
      "the changed table stays whole")
check(one("SELECT deleted_at FROM sheets WHERE id=?", (SG,)), "the other table lies in its trash")
check(one("SELECT COUNT(*) FROM sheet_cells WHERE sheet_id=?", (SG,)) > 0, "with its cells")
check(Gi.post(B + f"/api/sheets/{SG}/restore").ok and not one("SELECT deleted_at FROM sheets WHERE id=?", (SG,)), "it comes back")

sys.exit(kt.done("p2506_a"))
