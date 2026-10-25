#!/usr/bin/env python3
"""2.142.0 API tests, part B (#2147): the importers Notion, Google Tasks, ClickUp, Jira, any CSV and Markdown checklists.
Every sample file is made here (invented names, @example.com addresses only), never a real export.
 - Notion: export ZIP with a ZIP inside, database CSV next to its _all.csv (the full one wins), id suffixes removed,
   status / date / date range / tags / priority recognized, other properties + people into the notes, the page of a
   database row: text into the notes, its checkboxes subtasks; pages with checkboxes = lists, pages without = skipped
 - Google Tasks: Takeout ZIP and the Tasks.json alone (same ids: the second import skips everything), lists, subtasks
   (parent), due day never shifted, notes, completed, deleted skipped, links as text
 - ClickUp: lists in folders (hidden folder -> space), Unix-millisecond dates, priorities, [tags], checklists as
   subtasks, estimate -> duration, unknown parent -> main task with a warning, assignees only as text
 - Jira: repeated Labels columns, 15/Jan/25 10:00 AM and ISO dates, parent via issue id, resolution Won't Do =
   cancelled, issue key / sprint / reporter in the notes
 - any CSV: German header with ; , columns mapped (the answer's columns), unknown columns into the notes, slash dates
   day first when a value tells, a priority it does not understand stays in the notes
 - Markdown: front matter, headings = lists / sections, - [ ] / - [x] / * [ ] / 1. [ ] / - [-], indentation =
   subtask, text below = notes, clear dates + #tags + priority symbols; a list without checkboxes = plain bullets
 - every source: preview writes nothing, import, undo; wrong / broken / binary / too large files, ZIP bomb, ZIPs nested
   too deeply; people never become assignees; workspace: org:<id> / private, someone else's organisation 400
 - a person without an organisation (freelancer-matrix: Import): imports into the own private space, undo
 - OpenAPI: the six sources in the enum, columns in ImportReport
usage: p2142_b_api_test.py <datadir>      (P2142B_NOSTART=1 = the server already runs, KALMIDO_IMPORT_MAX_MB=2)"""
import io
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def one(sql, args=()):
    r = dbx(sql, args)
    return r[0][0] if r else None


def imp(s, src, name, data, **opts):
    r = s.post(f"{B}/api/import/{src}", files={"file": (name, data)}, data={k: str(v) for k, v in opts.items()})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"raw": r.text[:300]}


def task(title, uid):
    r = dbx("SELECT * FROM tasks WHERE title=? AND created_by=? ORDER BY id DESC", (title, uid))
    return r[0] if r else None


def tags(tid):
    return sorted(x[0] for x in dbx("SELECT tag FROM task_tags WHERE task_id=?", (tid,)))


def lst(name, uid):
    # 2.272.0 (#3027): an undo leaves the list in the trash -- the live one of that name first
    r = dbx("SELECT * FROM lists WHERE name=? AND owner_id=? ORDER BY deleted_at IS NOT NULL, id DESC", (name, uid))
    return r[0] if r else None


def sec_name(sid):
    return one("SELECT name FROM sections WHERE id=?", (sid,)) if sid else None


def count(uid):  # 2.272.0 (#3027): the undo puts into the trash -- count what is not in it
    return one("SELECT COUNT(*) FROM tasks WHERE created_by=? AND deleted_at IS NULL", (uid,))


def warn_has(j, part):
    return any(part in w["text"] for w in j.get("warnings", []))


def zipped(files, comp=zipfile.ZIP_DEFLATED):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", comp) as z:
        for n, d in files:
            z.writestr(n, d)
    return b.getvalue()


def roundtrip(s, uid, src, name, data, what, **opts):
    """Preview (nothing written), import, undo (everything gone). -> the import's answer (state after the import kept for checks
    by the caller: the undo runs at the end via the returned function)."""
    n0, l0 = count(uid), one("SELECT COUNT(*) FROM lists WHERE owner_id=? AND deleted_at IS NULL", (uid,))
    st, pj = imp(s, src, name, data, dry_run=1, **opts)
    check(st == 200 and pj.get("dry_run") is True and pj.get("import_id") is None, f"{what}: preview answers {st} {str(pj)[:300]}")
    check(count(uid) == n0 and one("SELECT COUNT(*) FROM lists WHERE owner_id=? AND deleted_at IS NULL", (uid,)) == l0, f"{what}: preview writes nothing")
    st, j = imp(s, src, name, data, **opts)
    check(st == 200 and j.get("import_id") and j["created"]["tasks"] == pj["created"]["tasks"],
          f"{what}: import as previewed {st} {str(j)[:300]}")

    def undo():
        r = s.post(B + f"/api/imports/{j['import_id']}/undo")
        check(r.ok and r.json()["tasks"] == j["created"]["tasks"] and count(uid) == n0
              and one("SELECT COUNT(*) FROM lists WHERE owner_id=? AND deleted_at IS NULL", (uid,)) == l0, f"{what}: undo removes everything {r.text[:200]}")
    return pj, j, undo


def start():
    if os.environ.get("P2142B_NOSTART") == "1":
        return
    extra = ["-e KALMIDO_INSTANCE_MODE=workspaces", "-e KALMIDO_IMPORT_RATE=1000", "-e KALMIDO_IMPORT_MAX_MB=2"]
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(extra))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ================================================================== setup
start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
r = A.post(B + "/api/users", json={"username": "erika", "display_name": "Erika Muster", "password": "password123",
                                   "email": "erika@example.com", "orgs": [ORG]})
assert r.ok, r.text
ERIKA = r.json()["id"]
Ot = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ERIKA})
OTHER = Ot.json().get("id") if Ot.ok else None
PRIV = {"space": "private"}

# ================================================================== Notion
NID = "0123456789abcdef0123456789abcdef"
DB_HEAD = "Name,Status,Due Date,Tags,Priority,Owner,Budget\n"
DB_ROWS = ('"Dach reparieren",Done,"January 15, 2025","Haus, Außen",High,Erika Muster,300\n'
           '"Zaun streichen",In progress,"February 3, 2025 → February 10, 2025",Außen,Low,,\n'
           '"Keller räumen",Not started,,,Medium,,\n')
inner = zipped([
    (f"Projekte {NID}.csv", DB_HEAD + DB_ROWS),
    (f"Projekte {NID}_all.csv", DB_HEAD + DB_ROWS + '"Archiv sortieren",,"2025-03-01",,,,\n'),
    (f"Projekte {NID}/Dach reparieren fedcba9876543210fedcba9876543210.md",
     "# Dach reparieren\n\nStatus: Done\nDue Date: January 15, 2025\n\nZiegel beim Händler bestellen.\n\n- [ ] Leiter holen\n- [x] Ziegel zählen\n"),
    ("Einkauf 11112222333344445555666677778888.md", "# Einkauf\n\n- [ ] Milch\n- [x] Brot\n    - [ ] Vollkorn\n"),
    ("Notizen 99990000aaaabbbbccccddddeeeeffff.md", "# Notizen\n\nNur Text, keine Aufgaben."),
])
NOTION = zipped([("Export-Part-1.zip", inner)], zipfile.ZIP_STORED)
pj, j, undo_notion = roundtrip(A, ALICE, "notion", "Export.zip", NOTION, "Notion", **PRIV)
check(pj["created"]["tasks"] == 9 and pj["created"]["subtasks"] == 3 and pj["created"]["lists"] == 2, f"Notion: counts {pj['created']}")
check(warn_has(pj, "Pages without a checklist"), "Notion: a page without checkboxes is skipped with a warning")
P = lst("Projekte", ALICE)
check(P is not None and lst("Einkauf", ALICE) is not None and not dbx("SELECT 1 FROM lists WHERE name LIKE ?", (f"%{NID}%",)),
      "Notion: lists named without the id suffix")
check(P is not None and P["org_id"] is None, "Notion: space private -> a private list")
t = task("Dach reparieren", ALICE)
check(t and t["status"] == 2 and t["due"] == "2025-01-15" and t["priority"] == 5 and tags(t["id"]) == ["Außen", "Haus"],
      f"Notion: status, date, priority, tags {dict(t) if t else None}")
check(t and "Ziegel beim Händler bestellen." in t["content"] and "Erika Muster" in t["content"] and "Budget: 300" in t["content"]
      and "Status: Done" not in t["content"] and t["assignee_id"] is None,
      f"Notion: the row page's text + other properties + the person (as text, never an account) in the notes {t['content'] if t else ''}")
lh = task("Leiter holen", ALICE)
check(lh and t and lh["parent_id"] == t["id"] and task("Ziegel zählen", ALICE)["status"] == 2, "Notion: the row page's checkboxes are subtasks")
z = task("Zaun streichen", ALICE)
check(z and z["start"] == "2025-02-03" and z["due"] == "2025-02-10" and z["priority"] == 1 and "Status: In progress" in z["content"],
      f"Notion: a date range = start + due, a status in work stays in the notes {dict(z) if z else None}")
check(task("Archiv sortieren", ALICE) is not None and len(dbx("SELECT 1 FROM tasks WHERE title='Keller räumen' AND created_by=?", (ALICE,))) == 1,
      "Notion: _all.csv wins over the view CSV (no doubles, the hidden row too)")
vk = task("Vollkorn", ALICE)
check(vk and vk["parent_id"] == task("Brot", ALICE)["id"] and task("Brot", ALICE)["status"] == 2, "Notion: a page's checklist with an indented item")
act = dbx("SELECT data FROM activity WHERE task_id=? AND kind='import'", (t["id"],)) if t else []
check(act and json.loads(act[0][0])["source"] == "Notion", "Notion: activity line 'imported from Notion'")
undo_notion()
# a single database CSV and a single Markdown page work too
st, j = imp(A, "notion", f"Projekte {NID}.csv", (DB_HEAD + DB_ROWS).encode(), dry_run=1)
check(st == 200 and j["created"]["tasks"] == 3 and j["lists"][0]["name"] == "Projekte", f"Notion: a single database CSV {st} {str(j)[:200]}")
st, j = imp(A, "notion", "Leer.zip", zipped([("bild.png", b"\x89PNG....")]), dry_run=1)
check(st == 400 and "No Notion database" in j.get("error", ""), f"Notion: a ZIP without database or checklist {st} {j}")
st, j = imp(A, "notion", "Kaputt.zip", b"PK\x03\x04kaputt" * 10, dry_run=1)
check(st == 400 and "ZIP" in j.get("error", ""), f"Notion: a broken ZIP {st} {j}")
deep = zipped([("a.zip", zipped([("b.zip", zipped([("c.csv", "Name\nx\n")]))]))])
st, j = imp(A, "notion", "Tief.zip", deep, dry_run=1)
check(st == 400 and "nested too deeply" in j.get("error", ""), f"Notion: ZIPs nested too deeply {st} {j}")
bomb = zipped([("bomb.csv", "Name\n" + "0" * (5 * 1048576))])
st, j = imp(A, "notion", "Bombe.zip", bomb, dry_run=1)
check(st == 400 and "too much data" in j.get("error", ""), f"Notion: ZIP bomb refused {st} {j}")
bomb2 = zipped([("Export-Part-1.zip", zipped([("x.csv", "Name\n" + "0" * (5 * 1048576))]))], zipfile.ZIP_STORED)
st, j = imp(A, "notion", "Bombe2.zip", bomb2, dry_run=1)
check(st == 400 and "too much data" in j.get("error", ""), f"Notion: ZIP bomb inside a ZIP refused {st} {j}")
many = zipped([(f"Export-Part-{i}.zip", zipped([(f"p{i}.md", "- [ ] x\n")])) for i in range(25)], zipfile.ZIP_STORED)
st, j = imp(A, "notion", "Viele.zip", many, dry_run=1)
check(st == 400 and "too many files" in j.get("error", ""), f"Notion: too many ZIPs inside {st} {j}")

# ================================================================== Google Tasks
GT = {"kind": "tasks#taskLists", "items": [
    {"kind": "tasks#taskList", "id": "L1", "title": "Privat", "items": [
        {"kind": "tasks#task", "id": "g1", "title": "Steuer machen", "notes": "Belege sammeln", "status": "needsAction",
         "due": "2025-03-31T00:00:00.000Z", "position": "00000000000000000001",
         "links": [{"type": "email", "description": "Mail", "link": "https://mail.example.com/x"}]},
        {"kind": "tasks#task", "id": "g2", "title": "Formular ausfüllen", "parent": "g1", "status": "completed",
         "completed": "2025-03-01T10:00:00.000Z", "position": "00000000000000000000"},
        {"kind": "tasks#task", "id": "g3", "title": "Schon gelöscht", "deleted": True, "status": "needsAction"}]},
    {"kind": "tasks#taskList", "id": "L2", "title": "Arbeit", "items": [
        {"kind": "tasks#task", "id": "g4", "title": "Bericht schreiben", "status": "needsAction"}]}]}
GTZ = zipped([("Takeout/Tasks/Tasks.json", json.dumps(GT)), ("Takeout/archive_browser.html", "<html></html>")])
pj, j, undo_gt = roundtrip(A, ALICE, "gtasks", "takeout.zip", GTZ, "Google Tasks", **PRIV)
check(pj["created"]["tasks"] == 3 and pj["created"]["lists"] == 2 and pj["created"]["subtasks"] == 1, f"Google Tasks: counts {pj['created']}")
g1, g2 = task("Steuer machen", ALICE), task("Formular ausfüllen", ALICE)
check(g1 and g1["due"] == "2025-03-31" and g1["due_time"] is None and "Belege sammeln" in g1["content"]
      and "https://mail.example.com/x" in g1["content"], f"Google Tasks: due day (not shifted), notes, link as text {dict(g1) if g1 else None}")
check(g2 and g1 and g2["parent_id"] == g1["id"] and g2["status"] == 2 and str(g2["completed_at"]).startswith("2025-03-01"),
      "Google Tasks: subtask via parent, completed with its time")
check(task("Schon gelöscht", ALICE) is None and lst("Arbeit", ALICE) is not None, "Google Tasks: deleted tasks skipped, every list")
st, j2 = imp(A, "gtasks", "Tasks.json", json.dumps(GT).encode(), dry_run=1)
check(st == 200 and j2["created"]["tasks"] == 0 and j2["skipped"] == 3, f"Google Tasks: the JSON alone, the same tasks skipped {st} {str(j2)[:200]}")
undo_gt()
st, j = imp(A, "gtasks", "x.json", b'{"foo": 1}', dry_run=1)
check(st == 400 and "Google Tasks" in j.get("error", ""), f"Google Tasks: another JSON refused {st} {j}")
st, j = imp(A, "gtasks", "x.zip", zipped([("a.txt", "x")]), dry_run=1)
check(st == 400 and "Tasks.json" in j.get("error", ""), f"Google Tasks: a ZIP without JSON {st} {j}")
st, j = imp(A, "gtasks", "deep.json", ("[" * 100 + "]" * 100).encode(), dry_run=1)
check(st == 400 and "nested too deeply" in j.get("error", ""), f"Google Tasks: a deeply nested JSON {st} {j}")

# ================================================================== ClickUp
ms = lambda *a: str(int(datetime(*a, tzinfo=timezone.utc).timestamp() * 1000))  # noqa: E731
CU = ("Task ID,Task Name,Task Content,Status,Date Created,Due Date,Due Date Text,Start Date,Priority,Tags,List Name,Folder Name,Space Name,"
      "Assignees,Parent ID,Checklists,Time Estimated,Story Points\n"
      f'cu1,Website relaunch,Neue Seiten planen,in progress,{ms(2025, 1, 10, 12)},{ms(2025, 1, 22, 12)},,{ms(2025, 1, 20, 12)},high,'
      '"[web, design]",Marketing,hidden,Firma,[Max Mustermann],,,7200000,5\n'
      'cu2,Texte schreiben,,complete,,,,,urgent,,Marketing,hidden,Firma,,cu1,'
      '"{""Vorbereitung"":[{""name"":""Briefing lesen"",""resolved"":true},{""name"":""Gliederung"",""resolved"":false}]}",,\n'
      'cu3,Fotos auswählen,,to do,,,,,,,Marketing,hidden,Firma,,cu404,,,\n')
pj, j, undo_cu = roundtrip(A, ALICE, "clickup", "export.csv", CU.encode(), "ClickUp", **PRIV)
check(pj["created"]["tasks"] == 5 and pj["created"]["subtasks"] == 3, f"ClickUp: counts {pj['created']}")
check(warn_has(pj, "Parent task not found"), "ClickUp: an unknown parent -> main task with a warning")
c1, c2 = task("Website relaunch", ALICE), task("Texte schreiben", ALICE)
check(c1 and c1["due"] == "2025-01-22" and c1["start"] == "2025-01-20" and c1["priority"] == 5 and c1["duration"] == 120
      and tags(c1["id"]) == ["design", "web"], f"ClickUp: dates from milliseconds, priority, estimate, [tags] {dict(c1) if c1 else None}")
check(c1 and "Max Mustermann" in c1["content"] and "Story Points: 5" in c1["content"] and "in progress" in c1["content"]
      and c1["assignee_id"] is None, f"ClickUp: assignee as text, extra column + status in the notes {c1['content'] if c1 else ''}")
check(c2 and c1 and c2["parent_id"] == c1["id"] and c2["status"] == 2, "ClickUp: subtask via Parent ID, complete = done")
bl, gl = task("Briefing lesen", ALICE), task("Gliederung", ALICE)
check(bl and gl and c2 and bl["parent_id"] == c2["id"] and bl["status"] == 2 and gl["status"] == 0, "ClickUp: checklist items = subtasks")
mk = lst("Marketing", ALICE)
check(mk and mk["folder"] == "Firma" and task("Fotos auswählen", ALICE)["parent_id"] is None, "ClickUp: hidden folder -> the space as folder")
undo_cu()
st, j = imp(A, "clickup", "x.csv", b"Name,Due\nx,y\n", dry_run=1)
check(st == 400 and "ClickUp" in j.get("error", ""), f"ClickUp: another CSV refused {st} {j}")

# ================================================================== Jira
JI = ("Summary,Issue key,Issue id,Issue Type,Status,Priority,Resolution,Assignee,Reporter,Created,Due date,Resolved,Labels,Labels,"
      "Description,Parent,Project name,Sprint\n"
      'Login bauen,APP-1,10001,Story,In Progress,Highest,,Erika Muster,Max Muster,15/Jan/25 10:00 AM,31/Jan/25 12:00 AM,,backend,auth,'
      '"Formular und Server",,App,Sprint 1\n'
      'Passwort vergessen,APP-2,10002,Sub-task,Done,Medium,Done,,,16/Jan/25 9:15 AM,2025-02-05,20/Jan/25 4:30 PM,auth,,Link schicken,10001,App,\n'
      "Altes Feature,APP-3,10003,Bug,Closed,Low,Won't Do,,,,,,,,,,App,\n")
pj, j, undo_ji = roundtrip(A, ALICE, "jira", "jira.csv", JI.encode(), "Jira", **PRIV)
check(pj["created"]["tasks"] == 3 and pj["created"]["subtasks"] == 1 and pj["created"]["assigned"] == 0, f"Jira: counts {pj['created']}")
j1, j2, j3 = task("Login bauen", ALICE), task("Passwort vergessen", ALICE), task("Altes Feature", ALICE)
check(j1 and j1["due"] == "2025-01-31" and j1["due_time"] is None and j1["priority"] == 5 and tags(j1["id"]) == ["auth", "backend"],
      f"Jira: due date (12:00 AM = no time), priority, repeated Labels columns {dict(j1) if j1 else None}")
check(j1 and str(j1["created_at"]).startswith("2025-01-15") and "APP-1" in j1["content"] and "Story" in j1["content"]
      and "Sprint 1" in j1["content"] and "Max Muster" in j1["content"] and "Erika Muster" in j1["content"] and j1["assignee_id"] is None,
      f"Jira: created, key / type / sprint / reporter / assignee (text) in the notes {j1['content'] if j1 else ''}")
check(j2 and j1 and j2["parent_id"] == j1["id"] and j2["status"] == 2 and j2["due"] == "2025-02-05" and j2["priority"] == 3
      and str(j2["completed_at"]).startswith("2025-01-20"), "Jira: sub-task via the parent's issue id, resolved date, ISO due date")
check(j3 and j3["status"] == -1 and j3["priority"] == 1, f"Jira: resolution Won't Do = cancelled {dict(j3) if j3 else None}")
check(lst("App", ALICE) is not None, "Jira: the project = the list")
undo_ji()
st, j = imp(A, "jira", "x.csv", b"Title,Key\nx,y\n", dry_run=1)
check(st == 400 and "Jira" in j.get("error", ""), f"Jira: another CSV refused {st} {j}")

# ================================================================== any CSV
GEN = ("Aufgabe;Fällig;Beschreibung;Projekt;Priorität;Tags;Erledigt;Kosten;Zuständig\n"
       "Rasen mähen;15.04.2025;Vorne und hinten;Garten;hoch;draußen, wochenende;nein;;Erika Muster\n"
       "Hecke schneiden;20/04/2025;;Garten;3;;ja;50 €;\n"
       "Blumen gießen;;;;;;;;\n")
pj, j, undo_csv = roundtrip(A, ALICE, "csv", "Haushalt.csv", GEN.encode("cp1252"), "CSV", **PRIV)
cols = {c["column"]: c["field"] for c in pj.get("columns") or []}
check(cols == {"Aufgabe": "title", "Fällig": "due", "Beschreibung": "notes", "Projekt": "list", "Priorität": "priority", "Tags": "tags",
               "Erledigt": "done", "Kosten": "notes", "Zuständig": "assignee"}, f"CSV: the preview names which column went where {cols}")
check(pj["created"]["tasks"] == 3 and pj["created"]["lists"] == 2 and warn_has(pj, "Priority not understood"), f"CSV: counts + warning {pj['created']}")
r1, r2, r3 = task("Rasen mähen", ALICE), task("Hecke schneiden", ALICE), task("Blumen gießen", ALICE)
check(r1 and r1["due"] == "2025-04-15" and r1["priority"] == 5 and tags(r1["id"]) == ["draußen", "wochenende"] and r1["status"] == 0
      and "Vorne und hinten" in r1["content"] and "Erika Muster" in r1["content"] and r1["assignee_id"] is None,
      f"CSV: German columns, Windows-1252, dotted date, priority word, tags, person as text {dict(r1) if r1 else None}")
check(r2 and r2["due"] == "2025-04-20" and r2["status"] == 2 and "Kosten: 50 €" in r2["content"] and "Priority: 3" in r2["content"],
      f"CSV: slash date day first, done, unknown column + unknown priority in the notes {dict(r2) if r2 else None}")
check(r3 and lst("Haushalt", ALICE) and r3["list_id"] == lst("Haushalt", ALICE)["id"] and lst("Garten", ALICE),
      "CSV: without a list value the file name is the list")
undo_csv()
st, j = imp(A, "csv", "plain.csv", b"Title,Due,Status,Parent,ID\nEins,2025-06-01,done,,1\nZwei,,in progress,1,2\n", dry_run=1)
check(st == 200 and j["created"]["subtasks"] == 1 and j["created"]["done"] == 1 and j["samples"][1]["subtask"] is True,
      f"CSV: English columns, parent via id {st} {str(j)[:300]}")
st, j = imp(A, "csv", "bin.csv", b"\x00\x01\x02\x03" * 100, dry_run=1)
check(st == 400 and "not a text file" in j.get("error", ""), f"CSV: a binary file {st} {j}")
st, j = imp(A, "csv", "leer.csv", b"   \n", dry_run=1)
check(st == 400, f"CSV: an empty file {st}")
st, j = imp(A, "csv", "gross.csv", b"Title\n" + b"x" * (2 * 1048576 + 10), dry_run=1)
check(st == 413, f"CSV: a file above the limit 413 {st}")
st, j = imp(A, "csv", "formel.csv", b'Title,Notes\n"=HYPERLINK(""http://127.0.0.1:9998/x"")","<script>alert(1)</script>"\n')
ft = task('=HYPERLINK("http://127.0.0.1:9998/x")', ALICE)
check(st == 200 and ft and "<script>" in ft["content"], "CSV: formulas and HTML stay plain text")
if st == 200:
    A.post(B + f"/api/imports/{j['import_id']}/undo")

# ================================================================== Markdown
MD = ("---\ntitle: Haus\ntags: [x]\n---\n# Haus\nEinleitung ohne Aufgabe.\n## Küche\n"
      "- [ ] Spüle reparieren 📅 2025-05-01 #handwerk ⏫\n  Dichtung kaufen\n  - [x] Werkzeug suchen\n"
      "- [ ] Ofen putzen due: 03.05.2025\n## Bad\n* [ ] Fliesen fugen\n# Garten\n1. [ ] Rasen düngen\n- [-] Teich bauen\n"
      "  - nur ein Punkt ohne Kästchen\n```\n- [ ] kein Task im Code\n```\n")
pj, j, undo_md = roundtrip(A, ALICE, "markdown", "haus.md", MD.encode(), "Markdown", **PRIV)
check(pj["created"]["tasks"] == 6 and pj["created"]["lists"] == 2 and pj["created"]["sections"] == 2 and pj["created"]["subtasks"] == 1,
      f"Markdown: counts {pj['created']}")
m1 = task("Spüle reparieren", ALICE)
check(m1 and m1["due"] == "2025-05-01" and m1["priority"] == 5 and tags(m1["id"]) == ["handwerk"] and "Dichtung kaufen" in m1["content"]
      and sec_name(m1["section_id"]) == "Küche", f"Markdown: date, priority, tag, notes, section {dict(m1) if m1 else None}")
wz = task("Werkzeug suchen", ALICE)
check(wz and m1 and wz["parent_id"] == m1["id"] and wz["status"] == 2, "Markdown: indentation = subtask, [x] = done")
check(task("Ofen putzen", ALICE)["due"] == "2025-05-03" and sec_name(task("Fliesen fugen", ALICE)["section_id"]) == "Bad",
      "Markdown: due: 03.05.2025, * [ ] in the next section")
tb = task("Teich bauen", ALICE)
check(tb and tb["status"] == -1 and "nur ein Punkt" in tb["content"] and task("kein Task im Code", ALICE) is None
      and task("Rasen düngen", ALICE)["list_id"] == lst("Garten", ALICE)["id"], "Markdown: [-] cancelled, bullets below = notes, code blocks ignored")
st, j = imp(A, "markdown", "haus.md", MD.encode(), dry_run=1)
check(st == 200 and j["created"]["tasks"] == 0 and j["skipped"] == 6, "Markdown: importing again skips everything")
undo_md()
st, j = imp(A, "markdown", "Einkauf.md", "- Eins\n- Zwei\n  - Zwei a\n".encode(), dry_run=1)
check(st == 200 and j["created"]["tasks"] == 3 and j["created"]["subtasks"] == 1 and j["lists"][0]["name"] == "Einkauf",
      f"Markdown: a list without checkboxes = plain bullets as tasks {st} {str(j)[:200]}")
st, j = imp(A, "markdown", "text.md", "Nur ein Absatz.\n".encode(), dry_run=1)
check(st == 400 and "No tasks" in j.get("error", ""), f"Markdown: no tasks {st} {j}")

# ================================================================== workspace (Org / private)
st, j = imp(A, "markdown", "Org.md", b"- [ ] Org-Aufgabe\n", space=f"org:{ORG}")
OL = lst("Org", ALICE)
check(st == 200 and OL and OL["org_id"] == ORG, f"workspace: space org:<id> puts the new list there {st} {dict(OL) if OL else None}")
if OTHER:
    st, j2 = imp(A, "markdown", "Fremd.md", b"- [ ] x\n", space=f"org:{OTHER}")
    check(st == 400 and lst("Fremd", ALICE) is None, f"workspace: an organisation the person is not in -> 400 {st}")
if st == 200 and j.get("import_id"):
    A.post(B + f"/api/imports/{j['import_id']}/undo")

# ================================================================== a person without an organisation
# freelancer-matrix: Import
FID, Fr = freelancer(B, A)
for src, name, data in (("markdown", "frei.md", b"- [ ] Frei 1\n  - [ ] Frei 1a\n"), ("csv", "frei.csv", b"Title,Due\nFrei 2,2025-07-01\n"),
                        ("gtasks", "Tasks.json", json.dumps({"kind": "tasks#tasks", "items": [{"kind": "tasks#task", "id": "f1", "title": "Frei 3", "status": "needsAction"}]}).encode()),
                        ("jira", "f.csv", b"Summary,Issue key\nFrei 4,F-1\n"), ("clickup", "f.csv", b"Task Name,Task ID\nFrei 5,fx1\n"),
                        ("notion", "Frei.md", b"# Frei\n- [ ] Frei 6\n")):
    st, j = imp(Fr, src, name, data, dry_run=1)
    check(st == 200 and j["created"]["tasks"] >= 1, f"freelancer: preview {src} {st} {str(j)[:200]}")
    st, j = imp(Fr, src, name, data)
    nl = j.get("lists", [{}])[0].get("list_id") if st == 200 else None
    check(st == 200 and nl and one("SELECT org_id FROM lists WHERE id=?", (nl,)) is None and one("SELECT owner_id FROM lists WHERE id=?", (nl,)) == FID,
          f"freelancer: {src} into the own private space {st} {str(j)[:200]}")
    if st == 200:
        r = Fr.post(B + f"/api/imports/{j['import_id']}/undo")
        check(r.ok and r.json()["tasks"] == j["created"]["tasks"], f"freelancer: undo {src}")
st, j = imp(Fr, "markdown", "x.md", b"- [ ] x\n", space=f"org:{ORG}")
check(st == 400, f"freelancer: someone else's organisation as workspace 400 {st}")
check(Fr.get(B + "/api/imports").ok, "freelancer: the import list")

# ================================================================== API + OpenAPI
tok = A.post(B + "/api/me/tokens", json={"name": "imp", "scopes": ["read", "write"]})
if tok.ok and tok.json().get("token"):
    TH = {"Authorization": "Bearer " + tok.json()["token"]}
    r = requests.post(V + "/import/markdown", headers=TH, files={"file": ("api.md", b"- [ ] API-Aufgabe\n")}, data={"dry_run": "true"})
    check(r.ok and r.json()["created"]["tasks"] == 1, f"API: v1 import markdown {r.status_code} {r.text[:200]}")
    r = requests.post(V + "/import/csv", headers=TH, files={"file": ("api.csv", b"Name;Datum\nX;2025-01-01\n")}, data={"dry_run": "true"})
    check(r.ok and r.json().get("columns") == [{"column": "Name", "field": "title"}, {"column": "Datum", "field": "due"}],
          f"API: v1 csv answers the columns {r.status_code} {r.text[:200]}")
else:
    print("note: no token route answer", tok.status_code, tok.text[:200], flush=True)
spec = requests.get(V + "/openapi.json").json()
en = spec["paths"]["/import/{source}"]["post"]["parameters"][0]["schema"]["enum"]
check(all(x in en for x in ("notion", "gtasks", "clickup", "jira", "csv", "markdown")) and "todoist" in en, f"OpenAPI: the new sources {en}")
check("columns" in json.dumps(spec["components"]["schemas"]["ImportReport"]), "OpenAPI: columns in ImportReport")
st, j = imp(A, "evernote", "x.enex", b"<x/>", dry_run=1)
check(st == 404, f"an unknown source 404 {st}")

print(f"p2142_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
