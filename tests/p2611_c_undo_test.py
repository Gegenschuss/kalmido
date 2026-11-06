#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.611.0 Teil C (#4866): the preview of an account import's undo (GET /api/imports/<id>/undo-plan) counts exactly like the
undo itself. Invented names only (example.com). A person without an organisation exports, a second one imports
(freelancer-matrix: own; the account import is private):
 - content of every area: tasks in a project, habits, filters, time entries (one billed since the import), journal days (one
   written on since), bookmarks, a saved arrangement, a focus session, a list rule, two calendars (one with an event added
   since), two address books (one with a contact added since), files in a folder, a knowledge page, a table, a client
 - the preview changes nothing (asked twice, the same answer, the same rows)
 - the preview's numbers == the undo's answer: what goes for good by area, tasks and other rows into a trash, what stays
   (tasks, rows, projects, calendars, address books)
 - and == what really went: per area the rows gone from the database, the tasks now in the trash; the billed time entry and
   the calendar / address book changed since stay; calendars, focus sessions and arrangements are named for good; the rule of a
   project of this run stays with its project (only one on a list of an earlier import goes, umz_part)
usage: p2611_c_undo_test.py <datadir>"""
import base64
import json
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
TS = "2026-01-05T10:00:00+00:00"
LAYOUT = json.dumps({"order": ["tasks", "brief"], "hidden": ["inbox"], "opts": {"tasks": {"lw": 4}}})


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


kt.fresh(env={"KALMIDO_SECRET_KEY": KEY}, prefix="P2611C")
A = kt.setup()
FID, Fr = freelancer(B, A, features=FEATURES)
GID, Gi = freelancer(B, A, "gina", features=FEATURES)

# ---------------------------------------------------------------- what the person moving has
LP = Fr.post(B + "/api/lists", json={"name": "Umzugsprojekt"}).json()["id"]
for n in ("Aufgabe bleibt", "Aufgabe geht"):
    check(Fr.post(B + "/api/tasks", json={"title": n, "list_id": LP}).ok, f"task {n}")
r = Fr.post(B + f"/api/lists/{LP}/rules", json={"name": "Wichtig", "trigger": {"kind": "created"}, "action": {"kind": "priority", "priority": "high"}})
check(r.ok, f"a list rule {r.status_code} {r.text[:160]}")
LQ = Fr.post(B + "/api/lists", json={"name": "Stilles Projekt"}).json()["id"]
check(Fr.post(B + "/api/tasks", json={"title": "Stille Aufgabe", "list_id": LQ}).ok, "a task in a project nothing happens in")
for n in ("Laufen", "Lesen"):
    check(Fr.post(B + "/api/habits", json={"name": n}).status_code in (200, 201), f"habit {n}")
check(Fr.post(B + "/api/filters", json={"name": "Umzugsfilter", "rules": {"op": "and"}}).status_code in (200, 201), "a filter")
for n in ("Zeit abgerechnet", "Zeit offen"):
    kt.dbx("""INSERT INTO time_entries(user_id, start, "end", seconds, note, source, created_at, updated_at) VALUES(?,?,?,?,?,'manual',?,?)""",
           (FID, TS, "2026-01-05T11:00:00+00:00", 3600, n, TS, TS))
for d in ("2026-01-03", "2026-01-04"):
    kt.dbx("INSERT INTO journal(user_id, day, text, updated_at) VALUES(?, ?, 'Eintrag', ?)", (FID, d, TS))
check(Fr.post(B + "/api/bookmarks", json={"url": "https://www.example.com/umzug"}).status_code in (200, 201), "a bookmark")
check(Fr.post(B + "/api/layouts/saved", json={"key": "view_today", "name": "Fokus", "layout": LAYOUT}).ok, "a saved arrangement")
kt.dbx("""INSERT INTO pomos(user_id, kind, minutes, start, "end", done, notified) VALUES(?, 'focus', 25, ?, ?, 1, 1)""",
       (FID, TS, "2026-01-05T10:25:00+00:00"))
for n in ("Kalender still", "Kalender belebt"):
    r = Fr.post(B + "/api/evcals", json={"name": n, "org_id": None})
    check(r.ok, f"calendar {n} {r.text[:120]}")
for n in ("Buch still", "Buch belebt"):
    r = Fr.post(B + "/api/books", json={"name": n, "org_id": None})
    check(r.ok, f"address book {n} {r.text[:120]}")
F1 = Fr.post(B + "/api/files/folders", json={"space": "private", "name": "Umzugsordner"}).json()["id"]
r = Fr.post(B + "/api/files/upload", data={"parent_id": str(F1)}, files={"file": ("notiz.txt", b"Inhalt " + os.urandom(4).hex().encode(), "text/plain")})
check(r.status_code == 201, f"a file {r.status_code}")
check(Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": "Umzugsseite", "body": "Text"}).ok, "a knowledge page")
check(Fr.post(B + "/api/sheets", json={"title": "Umzugstabelle", "space": "private"}).status_code == 201, "a table")
r = Fr.post(B + "/api/clients", json={"name": "Beispiel Kunde", "email": "kunde@example.com"})
check(r.ok, f"a client {r.status_code} {r.text[:120]}")

# ---------------------------------------------------------------- the import
iid, j = upload(Gi, export_of(Fr))
check(j.get("state") == "preview", f"preview {j.get('state')} {j.get('error')}")
r = Gi.post(B + f"/api/account/import/{iid}/run", json={"target": "private", "people": {}})
check(r.status_code == 202, f"the run {r.text[:160]}")
j = until(lambda: state_of(Gi, iid), 180) or {}
check(j.get("state") == "done", f"done {j.get('state')} {j.get('error')}")
IMP = (j.get("result") or {}).get("import_id")
check(IMP, "an import to undo")
since = datetime.fromisoformat(one("SELECT created_at FROM imports WHERE id=?", (IMP,)).replace("Z", "+00:00"))
check(until(lambda: datetime.now(timezone.utc) >= since + timedelta(seconds=1.1) or None, 10), "the clock is past the import")
CR = json.loads(one("SELECT created FROM imports WHERE id=?", (IMP,)) or "{}")
for k in ("ev_cals", "books", "time_entries", "journal", "more"):
    check(CR.get(k), f"setup: the import recorded {k} {sorted(CR)}")

# ---------------------------------------------------------------- the person works on
TB = one("SELECT id FROM tasks WHERE title='Aufgabe bleibt' AND created_by=?", (GID,))
check(Gi.patch(B + f"/api/tasks/{TB}", json={"title": "Aufgabe bleibt, weitergeschrieben"}).ok, "a task changed since")
EBILL = one("SELECT id FROM time_entries WHERE note='Zeit abgerechnet' AND user_id=?", (GID,))
EOPEN = one("SELECT id FROM time_entries WHERE note='Zeit offen' AND user_id=?", (GID,))
kt.dbx("UPDATE time_entries SET billed_doc_id=987654, billed_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), EBILL))  # no FK
kt.dbx("UPDATE journal SET text='Weitergeschrieben', updated_at=? WHERE user_id=? AND day='2026-01-03'", (datetime.now(timezone.utc).isoformat(), GID))
CB = one("SELECT id FROM ev_cals WHERE name='Kalender belebt' AND owner_id=?", (GID,))
CS = one("SELECT id FROM ev_cals WHERE name='Kalender still' AND owner_id=?", (GID,))
D = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
r = Gi.post(B + "/api/events", json={"cal_id": CB, "title": "Neuer Termin", "start": f"{D}T10:00", "end": f"{D}T11:00", "tz": "Europe/Berlin"})
check(r.ok, f"an event added since {r.status_code} {r.text[:160]}")
BB = one("SELECT id FROM books WHERE name='Buch belebt' AND owner_id=?", (GID,))
r = Gi.post(B + "/api/contacts", json={"book_id": BB, "fn": "Erika Beispiel", "emails": [{"value": "erika@example.com"}]})
check(r.ok, f"a contact added since {r.status_code} {r.text[:160]}")

# what the database holds of the person, per area of the dialog (the undo's labels)
AREAS = {"Habits": "SELECT COUNT(*) FROM habits WHERE user_id=?",
         "Filters": "SELECT COUNT(*) FROM filters WHERE user_id=?",
         "Time entries": "SELECT COUNT(*) FROM time_entries WHERE user_id=?",
         "Journal": "SELECT COUNT(*) FROM journal WHERE user_id=?",
         "Bookmarks": "SELECT COUNT(*) FROM bookmarks WHERE user_id=?",
         "Saved arrangements": "SELECT COUNT(*) FROM view_layouts WHERE user_id=?",
         "Focus sessions": "SELECT COUNT(*) FROM pomos WHERE user_id=?",
         "Calendars": "SELECT COUNT(*) FROM ev_cals WHERE owner_id=?",
         "Rules": "SELECT COUNT(*) FROM list_rules WHERE list_id IN (SELECT id FROM lists WHERE owner_id=?)"}
TRASH = {"tasks": "SELECT COUNT(*) FROM tasks WHERE created_by=? AND deleted_at IS NOT NULL",
         "rows": "SELECT (SELECT COUNT(*) FROM fs_nodes WHERE owner_id=? AND deleted_at IS NOT NULL AND (parent_id IS NULL OR parent_id NOT IN "
                 "(SELECT id FROM fs_nodes WHERE deleted_at IS NOT NULL)))"}


def counts():
    out = {k: one(q, (GID,)) for k, q in AREAS.items()}
    out.update({"trash " + k: one(q, (GID,)) for k, q in TRASH.items()})
    out["live tasks"] = one("SELECT COUNT(*) FROM tasks WHERE created_by=? AND deleted_at IS NULL", (GID,))
    out["books in the trash"] = one("SELECT COUNT(*) FROM books WHERE owner_id=? AND deleted_at IS NOT NULL", (GID,))
    return out


# ---------------------------------------------------------------- the preview
before = counts()
r = Gi.get(B + f"/api/imports/{IMP}/undo-plan")
check(r.ok, f"the preview {r.status_code} {r.text[:200]}")
P = r.json() if r.ok else {}
r = Gi.get(B + f"/api/imports/{IMP}/undo-plan")
check(r.ok and r.json() == P, f"asked twice, the same preview {r.text[:300]}")
check(counts() == before and not one("SELECT undone_at FROM imports WHERE id=?", (IMP,)), f"the preview changes nothing {counts()} {before}")
fg = {x["what"]: x["count"] for x in P.get("for_good") or []}
for k in ("Calendars", "Focus sessions", "Saved arrangements", "Time entries", "Journal", "Habits"):
    check(fg.get(k, 0) >= 1, f"#4866: the preview names {k} for good {P.get('for_good')}")
check(P.get("kept_tasks", 0) >= 1 and P.get("kept_cals") == 1 and P.get("kept_books") == 1 and P.get("kept_rows", 0) >= 2,
      f"#4866: the preview counts what stays (the changed task, calendar, address book, journal day, billed time) {P}")
check(P.get("trash_tasks", 0) >= 1 and P.get("trash_rows", 0) >= 3, f"#4866: the preview counts the trash {P}")

# ---------------------------------------------------------------- the undo
r = Gi.post(B + f"/api/imports/{IMP}/undo", json={})
check(r.ok, f"the undo {r.status_code} {r.text[:200]}")
U = r.json() if r.ok else {}
after = counts()
for pk, uk in (("for_good", "for_good"), ("trash_tasks", "tasks"), ("trash_rows", "trash_rows"), ("kept_tasks", "kept_tasks"),
               ("kept_rows", "kept_rows"), ("lists", "lists"), ("kept_lists", "kept_lists"), ("kept_cals", "kept_cals"),
               ("kept_books", "kept_books")):
    check(P.get(pk) == U.get(uk), f"#4866: preview {pk} == undo {uk}: {P.get(pk)} / {U.get(uk)}")
for k in AREAS:
    check(before[k] - after[k] == fg.get(k, 0), f"#4866: {k}: the preview said {fg.get(k, 0)} for good, {before[k] - after[k]} went")
check(after["trash tasks"] - before["trash tasks"] == P.get("trash_tasks"),
      f"#4866: the tasks in the trash {after['trash tasks'] - before['trash tasks']} == preview {P.get('trash_tasks')}")
check(after["trash rows"] - before["trash rows"] <= P.get("trash_rows", -1), f"#4866: the file trash {after} {P}")
check(one("SELECT 1 FROM time_entries WHERE id=?", (EBILL,)) and not one("SELECT 1 FROM time_entries WHERE id=?", (EOPEN,)),
      "#4866: the billed time entry stays, the open one went")
check(one("SELECT 1 FROM ev_cals WHERE id=?", (CB,)) and not one("SELECT 1 FROM ev_cals WHERE id=?", (CS,)),
      "#4866: the calendar with a new event stays, the still one went")
check(not one("SELECT deleted_at FROM books WHERE id=?", (BB,)) and after["books in the trash"] - before["books in the trash"] == 1,
      "#4866: the address book with a new contact stays, the still one is in the trash")
check(not one("SELECT deleted_at FROM tasks WHERE id=?", (TB,)), "#4866: the changed task stays")
check(after["Rules"] == before["Rules"] == 1 and "Rules" not in fg, "#4866: the rule stays with its project (it stays, a task changed)")

sys.exit(kt.done("p2611_c"))
