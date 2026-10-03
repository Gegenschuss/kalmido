#!/usr/bin/env python3
"""Importers (package C): Todoist (CSV, backup ZIP, Sync API JSON; German and English date texts, priorities, sections,
subtasks via INDENT, @labels, comments + attachment links, durations, deadlines), Trello (board JSON: sections or lists,
checklists, labels, archived cards, comments, attachment links, members), Asana (CSV: sections, parent tasks, tags,
dates, completion, assignee matching only for members of the target list), Microsoft To Do (German Outlook CSV in
Windows-1252, English Outlook CSV, export-tool CSV with steps, ICS), ICS / VTODO (TZID, RELATED-TO, RRULE, VALARM,
COMPLETED / CANCELLED, CATEGORIES, events skipped). Preview = dry run (nothing written), target lists (new / existing /
foreign / view-only), idempotent re-import, undo (24 h, once, kept tasks and lists), activity lines, limits (file size,
task count, ZIP bomb, deeply nested JSON, invalid encodings, binary files, rate limit), formula cells and HTML kept as
plain text, nothing fetched from URLs in the files, CSRF, the REST API (write scope, read-only token, OpenAPI).
Starts its OWN test containers (start.sh). Fixtures: tests/fixtures/import/.
usage: import_test.py <datadir>"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from datetime import date, timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(N, "fixtures", "import")
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
T = date.today()


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c.row_factory = sqlite3.Row
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def start(env=()):
    subprocess.run(["docker", "rm", "-f", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)  # 2.7.2: the old container must not write while its data goes
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1", EXTRA=" ".join(env)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def fx(name):
    with open(os.path.join(FX, name), "rb") as f:
        return f.read()


def imp(s, src, name, data=None, url=None, **opts):
    """POST an import; returns (status, json)."""
    r = s.post(url or f"{B}/api/import/{src}", files={"file": (name, fx(name) if data is None else data)},
               data={k: str(v) for k, v in opts.items()})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"raw": r.text[:200]}


def task(title, uid=1):
    r = dbx("SELECT * FROM tasks WHERE title=? AND created_by=? ORDER BY id DESC", (title, uid))
    return r[0] if r else None


def tags(tid, uid=1):
    return sorted(x[0] for x in dbx("SELECT tag FROM task_tags WHERE task_id=? AND user_id=?", (tid, uid)))


def count(uid=1):
    return dbx("SELECT COUNT(*) FROM tasks WHERE created_by=?", (uid,))[0][0]


def lst(name, uid=1):
    r = dbx("SELECT * FROM lists WHERE name=? AND owner_id=?", (name, uid))
    return r[0] if r else None


def sec_name(sid):
    r = dbx("SELECT name FROM sections WHERE id=?", (sid,)) if sid else []
    return r[0][0] if r else None


def warn_has(j, part):
    return any(part in w["text"] for w in j.get("warnings", []))


# ================================================================== setup
start(["-e KALMIDO_IMPORT_RATE=1000"])
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
for u, n, mail in (("bob", "Bob Builder", "bob@example.com"), ("carol", "Carol", "carol@example.com")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": mail})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
A.patch(B + "/api/users/1", json={"email": "alice@example.com"})
# a probe server inside the container: logs every request -- no URL from an imported file may ever reach it
subprocess.run(["docker", "exec", "-d", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test"), "python", "-c",
                "import http.server\nclass H(http.server.BaseHTTPRequestHandler):\n def do_GET(s):\n  open('/data/probe.log','a').write(s.path+'\\n'); s.send_response(200); s.end_headers()\n"
                " do_POST = do_HEAD = do_GET\n def log_message(s, *a): pass\nhttp.server.HTTPServer(('127.0.0.1', 9998), H).serve_forever()"])
ALICE, BOB, CAROL = 1, 2, 3

# ================================================================== preview = dry run, nothing written
n0 = count()
st, j = imp(A, "todoist", "Haushalt.csv", dry_run=1)
check(st == 200 and j["dry_run"] is True and j["import_id"] is None, f"preview answers ({st} {str(j)[:200]})")
check(j["created"]["tasks"] == 12 and j["created"]["lists"] == 1 and j["created"]["sections"] == 1 and j["created"]["subtasks"] == 3,
      "preview: exact counts " + str(j.get("created")))
check(count() == n0 and not lst("Haushalt") and not dbx("SELECT 1 FROM imports"), "preview: nothing written (tasks, lists, import records)")
check(len(j["samples"]) == 8 and j["samples"][0]["title"] == "Müll rausbringen", "preview: sample rows")
check(warn_has(j, "Date not understood") and warn_has(j, "Nested deeper than 3") and warn_has(j, "Headings without a checkbox")
      and warn_has(j, "p1 (highest)"), "preview: warnings for what cannot be mapped")
w = [x for x in j["warnings"] if "Date not understood" in x["text"]][0]
check(w["examples"] == ["Kompost umsetzen"] and "irgendwann mal" in w["text"], "warning names the task and the text")

# ================================================================== Todoist CSV (German)
st, j = imp(A, "todoist", "Haushalt.csv")
check(st == 200 and j["import_id"] and j["created"]["tasks"] == 12 and j["undo_until"], f"Todoist CSV imported ({st})")
L = lst("Haushalt")
check(L and L["view"] == "list", "list named after the file")
m = task("Müll rausbringen")
check(m and m["repeat"] == "FREQ=WEEKLY;BYDAY=MO" and m["due"] and date.fromisoformat(m["due"]).weekday() == 0
      and date.fromisoformat(m["due"]) >= T, "jeden Montag -> weekly on Monday, next Monday " + str(m and (m["repeat"], m["due"])))
check(m["content"] == "Gelbe Tonne nicht vergessen" and tags(m["id"]) == ["zuhause"] and m["priority"] == 0, "description, @label -> tag, p4 -> none")
s_ = task("Steuererklärung abgeben")
oct15 = date(T.year if (T - date(T.year, 10, 15)).days <= 60 else T.year + 1, 10, 15).isoformat()
check(s_["due"] == oct15, "15. Okt -> the coming 15 October " + str(s_["due"]))
check(s_["priority"] == 5 and tags(s_["id"]) == ["büro", "wichtig"], "PRIORITY 1 = p1 -> high (scale detected), two labels")
be, ko, tief = task("Belege sammeln"), task("Kontoauszüge"), task("Sehr tief")
check(be["parent_id"] == s_["id"] and ko["parent_id"] == be["id"], "INDENT 2 / 3 -> subtask / sub-subtask")
check(tief["parent_id"] == be["id"], "INDENT 4 -> moved up below the level-2 task (at most 3 levels)")
check("quittung.pdf" in tief["content"] and "https://files.todoist.com/abc/quittung.pdf" in tief["content"] and "Bitte bis Freitag" in tief["content"],
      "note row -> comment in the notes, attachment as a link")
check(not dbx("SELECT 1 FROM attachments"), "attachments are never downloaded")
ra = task("Rasen mähen")
check(ra["due"] == (T + timedelta(days=1)).isoformat() and ra["due_time"] == "10:00" and ra["duration"] == 90 and ra["priority"] == 3
      and sec_name(ra["section_id"]) == "Garten", "morgen um 10 Uhr, 90 minutes, p2 -> medium, section Garten")
check("Anna" in ra["content"] and ra["assignee_id"] is None, "unknown RESPONSIBLE kept as text in the notes")
he = task("Hecke schneiden")
check(he["repeat"] == "FREQ=WEEKLY;INTERVAL=2" and he["priority"] == 1, "alle 2 Wochen -> every 2 weeks, p3 -> low")
ko2 = task("Kompost umsetzen")
check(ko2["due"] is None and "irgendwann mal" in ko2["content"], "not understood date kept in the notes")
check(task("Überschrift ohne Haken") is not None, "* heading imported as a task without the marker")
fm = [t for t in dbx("SELECT * FROM tasks WHERE title LIKE '=HYPERLINK%'")]
check(len(fm) == 1 and fm[0]["title"].startswith('=HYPERLINK("http://evil.example/x";"klick")') and tags(fm[0]["id"]) == ["formel"],
      "formula cell stored as plain text")
x = [t for t in dbx("SELECT * FROM tasks WHERE title LIKE '%onerror%'")]
check(len(x) == 1 and x[0]["title"] == "<img src=x onerror=alert(1)> Script <script>alert(2)</script>", "HTML stored as text (escaped on display)")
z = task("Zahnarzt")
check(z["due"] == "2026-11-01", "DEADLINE (1.11.2026) used as the due date when DATE is empty")
act = dbx("SELECT kind, data, user_id FROM activity WHERE task_id=?", (m["id"],))
check(len(act) == 1 and act[0]["kind"] == "import" and json.loads(act[0]["data"])["source"] == "Todoist" and act[0]["user_id"] == ALICE,
      "activity: one line 'imported from Todoist'")
check(dbx("SELECT tt_id FROM tasks WHERE id=?", (m["id"],))[0][0].startswith("todoist:"), "external id per source")

# idempotent: the same file, then the backup ZIP that contains it again
st, j = imp(A, "todoist", "Haushalt.csv")
check(st == 200 and j["created"]["tasks"] == 0 and j["skipped"] == 12 and j["import_id"] is None, "same file again: all 12 skipped")
st, j = imp(A, "todoist", "todoist-backup.zip", dry_run=1)
check(st == 200 and j["skipped"] == 12 and j["created"]["tasks"] == 7 and [x["name"] for x in j["lists"]] == ["Haushalt", "Work"],
      f"backup ZIP: Haushalt skipped, Work new, '[id]' stripped from names ({j.get('created')}, {j.get('skipped')})")
check([x["existing"] for x in j["lists"]] == [True, False], "report: existing vs new list")
st, j = imp(A, "todoist", "todoist-backup.zip")
wk = {t["title"]: t for t in dbx("SELECT * FROM tasks WHERE list_id=?", (lst("Work")["id"],))}
check(wk["Send report"]["repeat"] == "FREQ=WEEKLY;BYDAY=MO" and wk["Send report"]["due_time"] == "09:00" and wk["Send report"]["priority"] == 5,
      "every monday at 9am")
check(wk["Review PR"]["due"] == "2027-01-15" and wk["Review PR"]["due_time"] == "14:00", "Jan 15 2027 14:00")
check(wk["Plan offsite"]["repeat"] == "FREQ=MONTHLY;INTERVAL=3" and wk["Plan offsite"]["repeat_from"] == "done", "every! 3 months -> from completion")
check(wk["Call bank"]["due"] == (T + timedelta(days=1)).isoformat(), "tomorrow")
check(wk["Standup"]["repeat"] == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "every weekday")
check(wk["Weird"]["due"] is None and "every 3rd friday" in wk["Weird"]["content"], "unsupported recurrence kept in the notes")
check(wk["Japanese date"]["due"] is None and "毎週月曜日" in wk["Japanese date"]["content"], "DATE_LANG ja: text kept in the notes")

# Todoist Sync API JSON
st, j = imp(A, "todoist", "todoist-sync.json")
check(st == 200 and j["created"]["tasks"] == 5, f"Todoist JSON ({st} {str(j)[:150]})")
mi = task("Milch kaufen")
inbox = dbx("SELECT id FROM lists WHERE owner_id=1 AND is_inbox=1")[0][0]
check(mi["list_id"] == inbox and tags(mi["id"]) == ["einkauf", "laden"], "inbox project -> own inbox, labels + @label")
vi = task("Visum beantragen")
check(vi["due"] == "2026-11-03" and vi["due_time"] == "09:30" and vi["priority"] == 5 and vi["duration"] == 45 and sec_name(vi["section_id"]) == "Vorher",
      "JSON: floating due, API priority 4 = high, duration, section")
check("Formular ausgedruckt" in vi["content"] and "https://example.com/antrag.pdf" in vi["content"] and "Bob Builder" in vi["content"],
      "JSON: comments with attachment link; responsible not a list member -> notes")
pf = task("Passfoto")
check(pf["parent_id"] == vi["id"] and pf["status"] == 2 and pf["completed_at"].startswith("2026-09-01"), "JSON: completed subtask")
check(task("Pflanzen gießen")["repeat"] == "FREQ=DAILY;INTERVAL=3", "JSON: recurring due string")
pk = lst("Packliste")
check(pk and pk["folder"] == "Reise" and lst("Reise")["view"] == "kanban", "sub-project -> folder, board view -> kanban")
check(task("Archiviert") is None, "archived project skipped")

# ================================================================== Trello (sections mode, archived skipped)
st, j = imp(A, "trello", "trello-board.json", dry_run=1)
check(st == 200 and j["created"]["tasks"] == 7 and warn_has(j, "Archived cards"), "Trello preview: 7 tasks, archived skipped")
check([w_["count"] for w_ in j["warnings"] if "Archived cards" in w_["text"]] == [2], "archived count in the warning")
st, j = imp(A, "trello", "trello-board.json")
hm = task("Homepage mockup")
L = lst("Website Relaunch")
check(hm and hm["list_id"] == L["id"] and sec_name(hm["section_id"]) == "To Do", "board -> one list, Trello list -> section")
check(hm["due"] == "2026-11-05" and hm["due_time"] == "15:00" and hm["reminders"] == "60" and hm["start"] == "2026-11-01", "card due (UTC -> local), dueReminder, start")
check(tags(hm["id"]) == ["Design", "red"], "labels -> tags (unnamed label: its colour)")
check(hm["assignee_id"] == ALICE, "member matching the importing user (owner of the new list) -> assigned")
check("Hero + **pricing**" in hm["content"] and "mockup.png" in hm["content"] and "Looks good" in hm["content"] and "Alice Example" in hm["content"],
      "description, attachment link, comment with author in the notes")
check(hm["created_at"].startswith("2024-03-12"), "creation time from the Trello id " + hm["created_at"])
cls = {t["title"]: t for t in dbx("SELECT * FROM tasks WHERE parent_id=?", (hm["id"],))}
check(set(cls) == {"Sections", "Review"}, "two checklists -> one subtask each")
items = {t["title"]: t for t in dbx("SELECT * FROM tasks WHERE parent_id=?", (cls["Sections"]["id"],))}
check(items["Hero"]["status"] == 2 and items["Pricing"]["status"] == 0 and items["Pricing"]["due"] == "2026-11-03", "checklist items: complete -> done, item due")
check(task("Legal <b>check</b>") is not None, "HTML in a checklist item stays text")
cw = task("Copywriting")
check(cw["status"] == 2 and sec_name(cw["section_id"]) == "Doing" and cw["assignee_id"] is None and "Zed Unknown" in cw["content"],
      "dueComplete -> done; unknown member -> notes")
check(task("Archived card") is None and task("Card in archived list") is None, "archived skipped")
# the other mode + archived as done: a new board name so it does not collide with the first import's ids -> all skipped
st, j = imp(A, "trello", "trello-board.json", mode="lists", archived="done", dry_run=1)
check(st == 200 and j["created"]["tasks"] == 2 and j["skipped"] == 7, "Trello again: only the 2 archived ones are new")
b2 = json.loads(fx("trello-board.json"))
b2["name"] = "Board Two"
for k in ("lists", "cards", "checklists"):
    for o in b2[k]:
        o["id"] = o["id"] + "b"
        if k == "cards":
            o["idList"] += "b"
        if k == "checklists":
            o["idCard"] += "b"
            for it in o["checkItems"]:
                it["id"] += "b"
st, j = imp(Bo, "trello", "b2.json", data=json.dumps(b2).encode(), mode="lists", archived="done")
check(st == 200 and j["created"]["lists"] == 3 and j["created"]["tasks"] == 9, f"lists mode: one list per Trello list incl. archived ({j.get('created')})")
check(all(x["folder"] == "Board Two" for x in dbx("SELECT folder FROM lists WHERE owner_id=? AND is_inbox=0", (BOB,))), "lists mode: board name = folder")
check(task("Archived card", BOB)["status"] == 2, "archived as done")

# ================================================================== Asana (assignee only for members of the target list)
st, j = imp(A, "asana", "asana-project.csv", dry_run=1)
check(st == 200 and j["created"]["tasks"] == 5 and warn_has(j, "Parent task not found") and warn_has(j, "32/13/2026"), "Asana preview")
mk = A.post(B + "/api/lists", json={"name": "Marketing shared"}).json()
A.put(B + f"/api/lists/{mk['id']}/members", json={"user_id": BOB, "role": "edit"})
st, j = imp(A, "asana", "asana-project.csv", target=mk["id"])
lc = task("Launch campaign")
check(st == 200 and lc["list_id"] == mk["id"] and j["lists"][0]["existing"] is True, "Asana into an existing list")
check(lc["assignee_id"] == BOB and lc["assigned_by"] == ALICE and j["created"]["assigned"] == 2, "assignee (e-mail) is a member -> assigned")
check(lc["due"] == "2026-10-15" and lc["start"] == "2026-10-01" and lc["priority"] == 5 and tags(lc["id"]) == ["marketing", "q4"]
      and sec_name(lc["section_id"]) == "Planning", "dates, priority, tags, section")
check("Budget: 5000" in lc["content"] and "Kick-off" in lc["content"], "custom field -> notes")
wb = task("Write brief")
check(wb["parent_id"] == lc["id"] and wb["status"] == 2 and wb["assignee_id"] == ALICE and wb["section_id"] == lc["section_id"],
      "Parent task by name, completed, assignee = me, section of the parent")
ba = task("Book ads")
check(ba["assignee_id"] is None and "Zed Unknown" in ba["content"] and ba["priority"] == 1 and "1205000000000001" in ba["content"],
      "unknown assignee -> notes, dependency -> notes")
check(task("Orphan subtask")["parent_id"] is None, "unknown parent -> main task")
check(task("Bad date")["due"] is None, "invalid date not stored")
# a list not shared with the assignee: no assignment even though the user exists
st, j = imp(Ca, "asana", "asana-project.csv", completed="skip")
check(st == 200 and j["created"]["tasks"] == 4 and j["created"]["assigned"] == 0 and task("Launch campaign", CAROL)["assignee_id"] is None,
      "new list of carol: bob (not a member) is not assigned; completed skipped")

# ================================================================== Microsoft To Do / Outlook
raw = fx("outlook-aufgaben.csv")
check(b"\xfc" in raw and b"\xc3" not in raw, "fixture really is Windows-1252")
st, j = imp(A, "mstodo", "outlook-aufgaben.csv")
pr = task("Präsentation für Müller")
check(st == 200 and pr and pr["due"] == "2026-10-15" and pr["start"] == "2026-10-01" and pr["priority"] == 5, "Outlook DE (cp1252): umlauts, dates, Hoch")
check(pr["reminders"] == "60" and tags(pr["id"]) == ["Büro", "Kunde"] and "Folien überarbeiten – dringend" in pr["content"],
      "reminder 08:00 on the all-day due date = 60 min before 09:00; categories; notes")
check(task("Blumen gießen")["status"] == 2 and task("Geschenk für Jürgen")["priority"] == 1, "Erledigt -> done, Niedrig -> low")
st, j = imp(A, "mstodo", "outlook-tasks-en.csv")
pi = task("Pay invoice")
check(st == 200 and pi["due"] == "2027-01-15" and pi["reminders"] == "1440" and pi["priority"] == 5, "Outlook EN: m/d/y, reminder 9:00 AM the day before")
st, j = imp(A, "mstodo", "mstodo-export.csv")
eg = task("Eggs")
check(st == 200 and lst("Groceries") and lst("Work") and eg["due"] == "2026-10-02" and eg["due_time"] is None and eg["priority"] == 5,
      "export-tool CSV: List column, midnight = no time, importance high")
st_ = {t["title"]: t for t in dbx("SELECT * FROM tasks WHERE parent_id=?", (eg["id"],))}
check(set(st_) == {"Check fridge", "Buy"} and st_["Check fridge"]["status"] == 2, "steps -> subtasks ([x] = done)")
st, j = imp(A, "mstodo", "tasks.ics", dry_run=1)
check(st == 200 and j["created"]["tasks"] == 9, "Microsoft To Do source also takes ICS")

# ================================================================== ICS / VTODO
st, j = imp(A, "ics", "tasks.ics")
check(st == 200 and j["created"]["tasks"] == 9 and warn_has(j, "Calendar events") and warn_has(j, "Repetition not supported"), "ICS imported")
um = task("Umzug planen")
check(lst("Privat") and lst("Arbeit") and um["list_id"] == lst("Privat")["id"], "one list per VCALENDAR (X-WR-CALNAME)")
check(um["due"] == "2026-11-10" and um["due_time"] == "15:00" and um["start"] == "2026-11-01", "TZID America/New_York -> Europe/Berlin")
check(um["reminders"] == "30,1440", "VALARM relative (END) + absolute -> minutes before due: " + um["reminders"])
check(um["priority"] == 5 and tags(um["id"]) == ["Privat", "Umzug"] and um["url"] == "https://example.com/umzug"
      and "Kartons besorgen\nUmzugswagen buchen" in um["content"], "PRIORITY 1 -> high, CATEGORIES, URL, DESCRIPTION")
ka, na = task("Kartons kaufen"), task("Nachsendeauftrag")
check(ka["parent_id"] == um["id"] and ka["status"] == 2 and ka["completed_at"].startswith("2026-09-15") and ka["priority"] == 3,
      "RELATED-TO;RELTYPE=PARENT, COMPLETED, PRIORITY 5 -> medium")
check(na["parent_id"] == um["id"] and na["due"] == "2026-11-05" and na["due_time"] is None and na["priority"] == 1, "RELATED-TO default PARENT, DATE due, 9 -> low")
check(dbx("SELECT repeat FROM tasks WHERE title='Blumen gießen' AND tt_id LIKE 'ics:%'")[0][0] == "FREQ=WEEKLY;BYDAY=SA", "RRULE weekly kept")
sd = [t for t in dbx("SELECT * FROM tasks WHERE title='Stündlich trinken'")][0]
check(sd["repeat"] == "" and "FREQ=HOURLY" in sd["content"], "HOURLY rule -> notes")
check(task("Abgesagt")["status"] == -1, "CANCELLED -> won't do")
fl = task("Floating time")
check(fl["due_time"] == "18:30" and fl["reminders"] == "1440", "floating time; TRIGGER -P1D")
check(task("Ein Termin") is None, "VEVENT skipped")
check(task("Ohne UID") is not None, "VTODO without UID imported (hash id)")
st, j = imp(A, "ics", "tasks.ics")
check(j["created"]["tasks"] == 0 and j["skipped"] == 9, "ICS again: all skipped (UID)")

# ================================================================== targets and permissions
bl = Bo.post(B + "/api/lists", json={"name": "Bobs"}).json()
st, j = imp(A, "ics", "tasks.ics", target=bl["id"], dry_run=1)
check(st == 404, f"foreign list as target: 404 ({st})")
Bo.put(B + f"/api/lists/{bl['id']}/members", json={"user_id": ALICE, "role": "view"})
st, j = imp(A, "ics", "tasks.ics", target=bl["id"], dry_run=1)
check(st == 403, f"view-only shared list: 403 ({st})")
Bo.put(B + f"/api/lists/{bl['id']}/members", json={"user_id": ALICE, "role": "edit"})
cal2 = fx("tasks.ics").replace(b"UID:", b"UID:x-")
st, j = imp(A, "ics", "t2.ics", data=cal2, target=bl["id"])
check(st == 200 and j["created"]["tasks"] == 8 and j["skipped"] == 1 and all(x["list_id"] == bl["id"] for x in j["lists"]),
      "edit member: import into the shared list (the VTODO without UID has the same content hash -> skipped)")
check(set(x[0] for x in dbx("SELECT name FROM sections WHERE list_id=?", (bl["id"],))) == {"Privat", "Arbeit"},
      "several source lists into one list -> sections")
check(imp(A, "nosuch", "x.csv", data=b"a,b\n1,2\n")[0] == 404, "unknown source: 404")
check(imp(A, "ics", "x.ics", data=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", target="abc")[0] == 400, "invalid target: 400")
check(imp(A, "ics", "x.ics", data=b"x", bogus="1")[0] == 400, "unknown option: 400")
check(imp(A, "trello", "x.json", data=b"{}", mode="kanban")[0] == 400, "invalid option value: 400")
r = requests.post(B + "/api/import/todoist", files={"file": ("a.csv", fx("Work.csv"))}, cookies=A.cookies)
check(r.status_code == 403, f"no CSRF header: refused ({r.status_code})")
check(requests.post(B + "/api/import/todoist", headers=H, files={"file": ("a.csv", fx("Work.csv"))}).status_code == 401, "no login: 401")
check(A.post(B + "/api/import/todoist", data={"dry_run": "1"}).status_code == 400, "no file: 400")

# ================================================================== wrong / malicious files
bad = [("todoist", "x.csv", b"Name,Due\nfoo,bar\n", "not a Todoist CSV"),
       ("trello", "x.json", b'{"name": "x"}', "not a Trello board"),
       ("asana", "x.csv", fx("Work.csv"), "not an Asana CSV"),
       ("mstodo", "x.csv", b"Foo,Bar\n1,2\n", "not an Outlook"),
       ("ics", "x.ics", b"hello", "not an iCalendar file"),
       ("ics", "x.ics", b"BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nDUE:notadate\r\n", "could not be read"),
       ("trello", "x.json", b"{" * 5000 + b"}" * 5000, "nested too deeply"),
       ("trello", "x.json", b"[" * 100000, "nested too deeply"),
       ("trello", "x.json", b'{"lists": [], "cards": [', "could not be read"),
       ("todoist", "x.csv", b"\xff\xfeT\x00\xd8", "encoding"),
       ("todoist", "x.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 4, "not a text file"),
       ("todoist", "x.zip", b"PK\x03\x04garbage", "ZIP file could not be read"),
       ("todoist", "x.csv", b"   \n", "empty")]
for src, name, data, part in bad:
    st, j = imp(A, src, name, data=data, dry_run=1)
    check(st == 400 and part.lower() in str(j.get("error", "")).lower(), f"{src} {name}: {part} ({st} {str(j)[:120]})")
# zip bomb: 60 MB of zeros compress to ~60 KB
zb = io.BytesIO()
with zipfile.ZipFile(zb, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("big.csv", b"TYPE,CONTENT\n" + b"0" * (60 * 1048576))
st, j = imp(A, "todoist", "bomb.zip", data=zb.getvalue(), dry_run=1)
check(st == 400 and "too much data" in j.get("error", ""), f"zip bomb refused ({st} {str(j)[:100]})")
zb = io.BytesIO()
with zipfile.ZipFile(zb, "w") as zf:
    for i in range(400):
        zf.writestr(f"p{i}.csv", b"TYPE,CONTENT\ntask,x\n")
check(imp(A, "todoist", "many.zip", data=zb.getvalue(), dry_run=1)[1].get("error", "").endswith("too many files"), "zip with too many members refused")
zb = io.BytesIO()
with zipfile.ZipFile(zb, "w") as zf:
    zf.writestr("../../etc/evil.csv", b"TYPE,CONTENT\ntask,Traversal\n")
st, j = imp(A, "todoist", "trav.zip", data=zb.getvalue())
check(st == 200 and lst("evil") and not os.path.exists(os.path.join(DATA, "..", "etc", "evil.csv")), "zip member paths never used as paths (read in memory)")
# UTF-16 (Excel "Unicode text") and UTF-8 with BOM
u16 = "TYPE,CONTENT,PRIORITY\ntask,Größe prüfen,4\n".encode("utf-16")
st, j = imp(A, "todoist", "U16.csv", data=u16)
check(st == 200 and task("Größe prüfen") is not None, "UTF-16 with BOM")
st, j = imp(A, "todoist", "U16le.csv", data="TYPE,CONTENT\ntask,Ohne BOM ä\n".encode("utf-16-le"))
check(st == 200 and task("Ohne BOM ä") is not None, "UTF-16 LE without BOM detected")
st, j = imp(A, "todoist", "Bom.csv", data=b"\xef\xbb\xbfTYPE,CONTENT\ntask,Mit BOM\n")
check(st == 200 and task("Mit BOM") is not None, "UTF-8 with BOM")
# control and bidi characters, a huge title and huge notes are cut
st, j = imp(A, "todoist", "Ctl.csv", data=("TYPE,CONTENT,DESCRIPTION\ntask,Evil‮exe.txt\x07 Title " + "x" * 5000 + "," + "n" * 300000 + "\n").encode())
ev = [t for t in dbx("SELECT * FROM tasks WHERE title LIKE 'Evilexe.txt Title%'")]
check(st == 200 and len(ev) == 1 and len(ev[0]["title"]) == 2000 and len(ev[0]["content"]) == 200000, "bidi / control characters removed, title and notes capped")
# nothing inside a file is fetched: every URL field points at the probe server
P = "http://127.0.0.1:9998/probe"
pb = {"name": "Probe board", "lists": [{"id": "pl", "name": "L", "pos": 1}], "cards": [
      {"id": "pc", "name": "Probe card", "idList": "pl", "pos": 1, "desc": P + "/desc", "attachments": [{"name": "a", "url": P + "/att"}]}],
      "prefs": {"backgroundImage": P + "/bg"}, "members": [{"id": "m", "fullName": "M", "avatarUrl": P + "/avatar"}]}
imp(A, "trello", "probe.json", data=json.dumps(pb).encode())
imp(A, "ics", "probe.ics", data=("BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:probe\r\nSUMMARY:Probe\r\nURL:" + P + "/url\r\n"
                               "ATTACH:" + P + "/attach\r\nEND:VTODO\r\nEND:VCALENDAR\r\n").encode())
imp(A, "todoist", "Probe.csv", data=('TYPE,CONTENT\ntask,Probe\nnote,"[[file {""file_name"":""f"",""file_url"":""' + P + '/file""}]]"\n').encode())
import time as _t
_t.sleep(1)
check(task("Probe card") and task("Probe") and not os.path.exists(os.path.join(DATA, "probe.log")), "no URL from a file was fetched")
subprocess.run(["docker", "exec", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test"), "python", "-c",
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9998/control', timeout=5)"], capture_output=True)
check(open(os.path.join(DATA, "probe.log")).read().strip() == "/control" if os.path.exists(os.path.join(DATA, "probe.log")) else False,
      "probe server works (control request logged, nothing else)")
check(requests.get(B + "/api/health").ok, "still healthy")

# ================================================================== undo
before = count()
st, j = imp(A, "todoist", "Undo me.csv", data=b"TYPE,CONTENT,INDENT\nsection,S1\ntask,Undo parent,1\ntask,Undo child,2\n")
iid = j["import_id"]
ul = lst("Undo me")
up = task("Undo parent")
check(st == 200 and iid and count() == before + 2 and ul, "import to undo")
# bob (edit member?) -- not a member: carol cannot undo alice's import
check(Ca.post(B + f"/api/imports/{iid}/undo").status_code == 404, "someone else's import: 404")
# a task added later below an imported task and in the imported list stays
keep = A.post(B + "/api/tasks", json={"title": "Added later", "list_id": ul["id"], "parent_id": up["id"]}).json()
r = A.post(B + f"/api/imports/{iid}/undo")
check(r.ok and r.json()["tasks"] == 2 and r.json()["kept_lists"] == 1 and r.json()["kept_tasks"] == 1, "undo: 2 removed, list kept (has a later task) " + r.text)
check(task("Undo parent") is None and task("Undo child") is None and task("Added later")["parent_id"] is None, "undo: imported tasks gone, later task kept as main task")
check(not dbx("SELECT 1 FROM sections WHERE name='S1'"), "undo: created section removed")
check(A.post(B + f"/api/imports/{iid}/undo").status_code == 409, "undo twice: 409")
st, j = imp(A, "todoist", "Undo me.csv", data=b"TYPE,CONTENT,INDENT\nsection,S1\ntask,Undo parent,1\ntask,Undo child,2\n")
check(j["created"]["tasks"] == 2, "after undo the same file imports again")
iid2 = j["import_id"]
A.delete(B + f"/api/tasks/{keep['id']}")
dbx("UPDATE imports SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?", (iid2,))
check(A.post(B + f"/api/imports/{iid2}/undo").status_code == 409, "undo after 24 hours: 409")
st, j = imp(A, "todoist", "Fresh list.csv", data=b"TYPE,CONTENT\ntask,Fresh one\n")
r = A.post(B + f"/api/imports/{j['import_id']}/undo")
check(r.ok and r.json()["lists"] == 1 and not lst("Fresh list"), "undo removes a list the import created when it is empty")
h = A.get(B + "/api/imports").json()
check(h["max_mb"] == 20 and h["max_tasks"] == 20000 and h["imports"][0]["source"] == "todoist" and h["imports"][0]["undone_at"]
      and not h["imports"][0]["can_undo"], "import history")
check(all(x["source"] for x in Bo.get(B + "/api/imports").json()["imports"]) and
      not any(x["id"] == iid for x in Bo.get(B + "/api/imports").json()["imports"]), "history is per user")

# ================================================================== REST API
tw = A.post(B + "/api/me/tokens", json={"name": "imp", "scopes": ["read", "write"]}).json()["token"]
tr_ = A.post(B + "/api/me/tokens", json={"name": "ro", "scopes": ["read"]}).json()["token"]
hw, hr = {"Authorization": "Bearer " + tw}, {"Authorization": "Bearer " + tr_}
r = requests.post(V + "/import/ics", headers=hw, files={"file": ("api.ics", cal2.replace(b"UID:x-", b"UID:api-"))}, data={"dry_run": "true"})
check(r.ok and r.json()["dry_run"] and r.json()["created"]["tasks"] == 8, "API: dry run " + r.text[:120])
r = requests.post(V + "/import/ics", headers=hw, files={"file": ("api.ics", cal2.replace(b"UID:x-", b"UID:api-"))}, data={"list_name": "Via API"})
check(r.ok and r.json()["created"]["tasks"] == 8 and lst("Via API") is None, "API: import (list_name ignored for several lists)")
act = dbx("SELECT a.data FROM activity a JOIN tasks t ON t.id=a.task_id WHERE t.tt_id='ics:api-parent-1@example.com'")
check(act and json.loads(act[0][0]).get("via") == "api", "API: history says via API")
r2 = requests.post(V + f"/imports/{r.json()['import_id']}/undo", headers=hw)
check(r2.ok and r2.json()["tasks"] == 8, "API: undo")
r = requests.post(V + "/import/ics", headers=hr, files={"file": ("api.ics", cal2)})
check(r.status_code == 403 and r.json()["error"]["code"] == "forbidden", "API: read-only token refused")
r = requests.post(V + "/import/ics", headers=hw, files={"file": ("x.ics", b"nope")})
check(r.status_code == 400 and r.json()["error"]["code"] == "invalid", "API: error format")
r = requests.post(V + "/import/ics?x=1", headers=hw, files={"file": ("x.ics", b"nope")})
check(r.status_code == 400, "API: unknown query parameter")
check(requests.post(V + "/import/ics", files={"file": ("x.ics", b"nope")}).status_code == 401, "API: no token")
spec = requests.get(V + "/openapi.json").json()
op = spec["paths"]["/import/{source}"]["post"]
check(op["x-kalmido-scope"] == "structure" and "multipart/form-data" in op["requestBody"]["content"] and "/imports/{id}/undo" in spec["paths"],
      "OpenAPI documents the import")

# ================================================================== limits (own container: 1 MB, 30 tasks, 3 imports per 10 min)
start(["-e KALMIDO_IMPORT_MAX_MB=1", "-e KALMIDO_IMPORT_MAX_TASKS=30", "-e KALMIDO_IMPORT_RATE=4"])
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
big = b"TYPE,CONTENT\n" + b"task,x\n" * 200000
st, j = imp(A, "todoist", "big.csv", data=big, dry_run=1)
check(st == 413 and "1 MB" in j.get("error", ""), f"file larger than the limit: 413 ({st} {str(j)[:100]})")
many = b"TYPE,CONTENT\n" + b"".join(b"task,t%d\n" % i for i in range(31))
st, j = imp(A, "todoist", "many.csv", data=many, dry_run=1)
check(st == 400 and "Too many tasks: 31" in j.get("error", ""), f"more tasks than the limit ({st} {str(j)[:100]})")
check(count() == 0, "limits: nothing written")
imp(A, "todoist", "a.csv", data=b"TYPE,CONTENT\ntask,a\n", dry_run=1)
imp(A, "todoist", "a.csv", data=b"TYPE,CONTENT\ntask,a\n", dry_run=1)
st, j = imp(A, "todoist", "a.csv", data=b"TYPE,CONTENT\ntask,a\n", dry_run=1)
check(st == 429 and "Too many imports" in j.get("error", ""), f"rate limit per user ({st})")
# German error texts
A.patch(B + "/api/settings", json={"lang": "de"})
start(["-e KALMIDO_IMPORT_RATE=1000"])
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "de"})
st, j = imp(A, "trello", "x.json", data=b"{}", dry_run=1)
check(st == 400 and "kein Trello-Board-Export" in j.get("error", ""), "error in German")
st, j = imp(A, "todoist", "Haushalt.csv", dry_run=1)
check(any("Datum nicht verstanden" in w_["text"] for w_ in j["warnings"]), "warnings in German")
st, j = imp(A, "todoist", "Haushalt.csv")
check("Kommentare (Todoist):" in task("Sehr tief")["content"] and "Anhang" in task("Sehr tief")["content"] or "quittung.pdf" in task("Sehr tief")["content"],
      "notes headings in the user's language")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
