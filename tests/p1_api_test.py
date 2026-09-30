#!/usr/bin/env python3
"""Package 1 API tests: ICS feed, undo, completed_by, templates, statistics, manifest shortcuts.
Runs against the TEST container (:3048 built-in login, :3041 proxy port), fresh DB in DATA."""
import json, os, re, sqlite3, sys, time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests
import icalendar
import recurring_ical_events

B, BP = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048"), "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PROXY_PORT", "3041")
DATA = sys.argv[1]
H = {"X-Requested-With": "kalmido"}
TZ = ZoneInfo("Europe/Berlin")
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what)


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok
    return s


def db():
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    c.row_factory = sqlite3.Row
    return c


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
# 1.9.0: "completed by others" News are off by default; the undo checks below need them
A.patch(B + "/api/settings", json={"news_kinds": "mention,assign,comment,unblock,share,status,complete"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
BOB = r.json()["id"]
Bb = sess("bob")
A.patch(B + "/api/users/1", json={"proxy_login": "alice-sso"})
st = A.get(B + "/api/state").json()
INBOX_A = [l for l in st["lists"] if l["is_inbox"]][0]["id"]
WORK = A.post(B + "/api/lists", json={"name": "Work"}).json()["id"]
SH = Bb.post(B + "/api/lists", json={"name": "Shared"}).json()["id"]
Bb.put(B + f"/api/lists/{SH}/members", json={"user_id": 1, "role": "edit"})
PRIV = Bb.post(B + "/api/lists", json={"name": "Bob private"}).json()["id"]
today = datetime.now(TZ).date()
D = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731


def mk(s, **kw):
    r = s.post(B + "/api/tasks", json=kw)
    assert r.ok, r.text
    return r.json()


# ===================================================================== manifest
m = requests.get(B + "/manifest.json").json()
sc = m.get("shortcuts") or []
check([x["url"] for x in sc] == ["/?action=new", "/?action=capture", "/#today", "/#news", "/#search"], "manifest: 5 shortcuts with the start URLs (2.4.0: Quick add)")
check(all(len(x["icons"]) == 2 and x["icons"][0]["sizes"] == "96x96" for x in sc), "manifest: shortcut icons 96 + 192")
for x in sc:
    for i in x["icons"]:
        rr = requests.get(B + i["src"])
        check(rr.ok and rr.headers["Content-Type"] == "image/png" and rr.content[:4] == b"\x89PNG", "shortcut icon served: " + i["src"])
        z = int(i["sizes"].split("x")[0])
        check(int.from_bytes(rr.content[16:20], "big") == z, "icon size matches " + i["src"])
A.patch(B + "/api/settings", json={"lang": "de"})
md = A.get(B + "/manifest.json").json()
check(md["shortcuts"][0]["name"] == "Neue Aufgabe" and md["lang"] == "de", "manifest shortcuts in German for a German session: " + md["shortcuts"][0]["name"])
A.patch(B + "/api/settings", json={"lang": "en"})

# ===================================================================== completed_by + undo
t1 = mk(A, title="Plain", list_id=WORK)
k1 = mk(A, title="Kid", parent_id=t1["id"])
j = A.post(B + f"/api/tasks/{t1['id']}/complete").json()
check(j["status"] == 2 and j["undo"]["op"] == "complete" and j["undo"]["copy_id"] is None, "complete returns an undo payload")
c = db()
check(c.execute("SELECT completed_by FROM tasks WHERE id=?", (t1["id"],)).fetchone()[0] == 1, "completed_by = alice")
check(c.execute("SELECT status, completed_by FROM tasks WHERE id=?", (k1["id"],)).fetchone()[:] == (2, 1), "subtask completed with the parent, completed_by")
u = A.post(B + f"/api/tasks/{t1['id']}/undo", json=j["undo"])
check(u.ok and u.json()["status"] == 0, "undo complete -> open")
c = db()
check(c.execute("SELECT status, completed_at, completed_by FROM tasks WHERE id=?", (k1["id"],)).fetchone()[:] == (0, None, None), "undo reopens the subtask completed with it")
u2 = A.post(B + f"/api/tasks/{t1['id']}/undo", json=j["undo"])
check(u2.status_code == 409, "second undo -> 409 (changed in the meantime)")
# reopen + undo
j = A.post(B + f"/api/tasks/{t1['id']}/complete").json()
at = j["completed_at"]
time.sleep(1.1)
rj = A.post(B + f"/api/tasks/{t1['id']}/reopen").json()
check(rj["status"] == 0 and rj["undo"]["op"] == "reopen" and rj["undo"]["completed_at"] == at, "reopen returns undo with the old completion time")
uj = A.post(B + f"/api/tasks/{t1['id']}/undo", json=rj["undo"]).json()
check(uj["status"] == 2 and uj["completed_at"] == at and uj["completed_by"] == 1, "undo reopen restores the old completion (time + person)")
# forged completer -> me
A.post(B + f"/api/tasks/{t1['id']}/reopen")
r_ = A.post(B + f"/api/tasks/{t1['id']}/undo", json={**rj["undo"], "completed_by": 999})
check(r_.status_code == 409, "tampered undo payload (signature) refused")
r_ = A.post(B + f"/api/tasks/{t1['id']}/undo", json={"op": "reopen", "status": 2, "completed_at": at, "completed_by": 1})
check(r_.status_code == 409, "unsigned undo payload refused")
# recurring
rt = mk(A, title="Weekly", list_id=WORK, due=D(0), repeat="FREQ=WEEKLY;COUNT=5", reminders="0")
rk = mk(A, title="Sub", parent_id=rt["id"])
A.post(B + f"/api/tasks/{rk['id']}/complete")  # a done subtask gets reset by the advance
j = A.post(B + f"/api/tasks/{rt['id']}/complete", json={"expect_due": D(0)}).json()
cp = j["undo"]["copy_id"]
check(j["due"] == D(7) and j["repeat"] == "FREQ=WEEKLY;COUNT=4" and cp, "recurring advanced, copy made")
c = db()
check(c.execute("SELECT status, completed_by FROM tasks WHERE id=?", (cp,)).fetchone()[:] == (2, 1), "done copy: completed_by alice")
check(c.execute("SELECT status FROM tasks WHERE id=?", (rk["id"],)).fetchone()[0] == 0, "subtask reset by the advance")
uj = A.post(B + f"/api/tasks/{rt['id']}/undo", json=j["undo"]).json()
c = db()
check(uj["due"] == D(0) and uj["repeat"] == "FREQ=WEEKLY;COUNT=5" and uj["status"] == 0, "undo recurring: due + COUNT back")
check(c.execute("SELECT 1 FROM tasks WHERE id=?", (cp,)).fetchone() is None, "undo recurring: done copy removed")
check(c.execute("SELECT status FROM tasks WHERE id=?", (rk["id"],)).fetchone()[0] == 2, "undo recurring: subtask done again")
# undo with a copy id of another task -> refused
other = mk(A, title="Weekly", list_id=WORK)  # same title, same second: still not the copy
A.post(B + f"/api/tasks/{other['id']}/complete")
bad = dict(j["undo"], copy_id=other["id"])
check(A.post(B + f"/api/tasks/{rt['id']}/undo", json=bad).status_code == 409, "replayed undo (copy id reused by a new task) refused")
check(db().execute("SELECT 1 FROM tasks WHERE id=?", (other["id"],)).fetchone() is not None, "foreign task not deleted")
# last occurrence ends the repetition; undo restores it
lt = mk(A, title="Last", list_id=WORK, due=D(0), repeat="FREQ=DAILY;COUNT=1")
j = A.post(B + f"/api/tasks/{lt['id']}/complete").json()
check(j["status"] == 2 and j["repeat"] == "", "last occurrence done for good")
uj = A.post(B + f"/api/tasks/{lt['id']}/undo", json=j["undo"]).json()
check(uj["status"] == 0 and uj["repeat"] == "FREQ=DAILY;COUNT=1", "undo restores the ended repetition")
# view-only member cannot undo
vl = A.post(B + "/api/lists", json={"name": "View"}).json()["id"]
A.put(B + f"/api/lists/{vl}/members", json={"user_id": BOB, "role": "view"})
vt = mk(A, title="VT", list_id=vl)
j = A.post(B + f"/api/tasks/{vt['id']}/complete").json()
check(Bb.post(B + f"/api/tasks/{vt['id']}/undo", json=j["undo"]).status_code == 403, "view-only member: undo 403")
A.put(B + f"/api/lists/{vl}/members", json={"user_id": BOB, "role": "edit"})
check(Bb.post(B + f"/api/tasks/{vt['id']}/undo", json=j["undo"]).status_code == 409, "another user cannot replay my undo payload")
check(sess("bob").post(B + f"/api/tasks/{t1['id']}/undo", json={"op": "reopen", "status": 2}).status_code == 404, "stranger: undo 404")
# shared list completion by bob -> completed_by bob, News item removed on undo
sh1 = mk(A, title="Shared one", list_id=SH)
j = Bb.post(B + f"/api/tasks/{sh1['id']}/complete").json()
c = db()
check(c.execute("SELECT completed_by FROM tasks WHERE id=?", (sh1["id"],)).fetchone()[0] == BOB, "shared list: completed_by = bob")
check(c.execute("SELECT COUNT(*) FROM notifications WHERE task_id=? AND kind='complete'", (sh1["id"],)).fetchone()[0] == 1, "complete News item for alice")
Bb.post(B + f"/api/tasks/{sh1['id']}/undo", json=j["undo"])
check(db().execute("SELECT COUNT(*) FROM notifications WHERE task_id=? AND kind='complete'", (sh1["id"],)).fetchone()[0] == 0, "undo removes the complete News item")
# batch complete / undo / delete / restore / patch_each
b1, b2, b3 = (mk(A, title=f"B{i}", list_id=WORK, due=D(i)) for i in range(3))
ids = [b1["id"], b2["id"], b3["id"]]
j = A.post(B + "/api/tasks/batch", json={"ids": ids, "action": "complete"}).json()
check(j["count"] == 3 and set(j["undo"]) == {str(i) for i in ids}, "batch complete returns undo per task")
j2 = A.post(B + "/api/tasks/batch", json={"ids": ids, "action": "undo", "data": {"items": j["undo"]}}).json()
check(j2["count"] == 3 and not j2["errors"], "batch undo")
check(all(db().execute("SELECT status FROM tasks WHERE id=?", (i,)).fetchone()[0] == 0 for i in ids), "batch undo: all open")
A.post(B + "/api/tasks/batch", json={"ids": ids, "action": "delete"})
check(all(db().execute("SELECT deleted_at FROM tasks WHERE id=?", (i,)).fetchone()[0] for i in ids), "batch delete")
j = A.post(B + "/api/tasks/batch", json={"ids": ids, "action": "restore"}).json()
check(j["count"] == 3 and all(db().execute("SELECT deleted_at FROM tasks WHERE id=?", (i,)).fetchone()[0] is None for i in ids), "batch restore")
A.post(B + "/api/tasks/batch", json={"ids": ids, "action": "patch", "data": {"due": D(5), "priority": 5}})
items = {str(b1["id"]): {"due": D(0), "priority": 0, "_prev": {"due": D(5), "priority": 5}},
         str(b2["id"]): {"due": D(1), "priority": 0, "_prev": {"due": D(5), "priority": 5}}}
j = A.post(B + "/api/tasks/batch", json={"ids": ids[:2], "action": "patch_each", "data": {"items": items}}).json()
c = db()
check(j["count"] == 2 and c.execute("SELECT due, priority FROM tasks WHERE id=?", (b1["id"],)).fetchone()[:] == (D(0), 0)
      and c.execute("SELECT due FROM tasks WHERE id=?", (b2["id"],)).fetchone()[0] == D(1), "batch patch_each restores per task")
check(c.execute("SELECT due FROM tasks WHERE id=?", (b3["id"],)).fetchone()[0] == D(5), "batch patch_each leaves others")

# ===================================================================== templates
p = mk(A, title="Trip prep", list_id=WORK, due=D(3), due_time="10:00", priority=3, tags=["travel"], content="Pack, check",
       reminders="15", repeat="", url="https://example.org/x")
c1 = mk(A, title="Passport", parent_id=p["id"], due=D(1))
c11 = mk(A, title="Photos", parent_id=c1["id"])
tj = A.post(B + "/api/templates", json={"task_id": p["id"]}).json()
check(tj["kind"] == "task" and tj["name"] == "Trip prep" and tj["count"] == 3, "template from task: name, 3 nodes")
n = tj["data"]["task"]
check(n["due_offset"] == 3 and n["due_time"] == "10:00" and n["tags"] == ["travel"] and n["children"][0]["due_offset"] == 1
      and n["children"][0]["children"][0]["title"] == "Photos", "template node: offsets, time, tags, nesting")
check(Bb.get(B + "/api/templates").json()["templates"] == [], "templates are private (bob sees none)")
check(Bb.post(B + f"/api/templates/{tj['id']}/apply", json={}).status_code == 404, "bob cannot use alice's template")
check(Bb.post(B + "/api/templates", json={"task_id": p["id"]}).status_code == 404, "bob cannot template alice's task")
ap = A.post(B + f"/api/templates/{tj['id']}/apply", json={"list_id": INBOX_A}).json()["task"]
check(ap["title"] == "Trip prep" and ap["due"] == D(3) and ap["due_time"] == "10:00" and ap["list_id"] == INBOX_A
      and ap["tags"] == ["travel"] and ap["reminders"] == "15" and ap["url"] == "https://example.org/x", "apply task template")
kids = db().execute("SELECT id, title, due FROM tasks WHERE parent_id=?", (ap["id"],)).fetchall()
check(len(kids) == 1 and kids[0]["due"] == D(1) and db().execute("SELECT COUNT(*) FROM tasks WHERE parent_id=?", (kids[0]["id"],)).fetchone()[0] == 1,
      "apply: subtasks with relative dates")
check(A.post(B + f"/api/templates/{tj['id']}/apply", json={"list_id": PRIV}).status_code == 404, "apply into an invisible list -> 404")
# edit template data + rename
nd = json.loads(json.dumps(tj["data"]))
nd["task"]["due_offset"] = 10
nd["task"]["children"].append({"title": "Tickets", "due_offset": 2})
e = A.patch(B + f"/api/templates/{tj['id']}", json={"name": "Trip", "data": nd}).json()
check(e["name"] == "Trip" and e["count"] == 4 and e["data"]["task"]["due_offset"] == 10, "template edit + rename")
check(A.patch(B + f"/api/templates/{tj['id']}", json={"data": {"task": {"title": ""}}}).status_code == 400, "template edit validates (empty title)")
check(A.patch(B + f"/api/templates/{tj['id']}", json={"name": " "}).status_code == 400, "rename to empty refused")
deep = {"task": {"title": "a", "children": [{"title": "b", "children": [{"title": "c", "children": [{"title": "d"}]}]}]}}
dj = A.post(B + "/api/templates", json={"kind": "task", "data": deep, "name": "deep"}).json()
check(dj["count"] == 3, "template depth capped at 3 levels")
check(A.post(B + "/api/templates", json={"kind": "task", "data": {"task": {"title": "x", "url": "javascript:alert(1)", "due_time": "25:00", "priority": 4}}}).json()["data"]["task"]
      == {**A.post(B + "/api/templates", json={"kind": "task", "data": {"task": {"title": "x"}}}).json()["data"]["task"]}, "template sanitizes url / time / priority")
# list template
secid = A.post(B + "/api/sections", json={"list_id": WORK, "name": "Later"}).json()
secid = secid.get("id") or [s for s in A.get(B + "/api/state").json()["sections"] if s["list_id"] == WORK][0]["id"]
mk(A, title="In section", list_id=WORK, section_id=secid, due=D(2))
lj = A.post(B + "/api/templates", json={"list_id": WORK, "name": "Work kit"}).json()
check(lj["kind"] == "list" and lj["data"]["sections"] == ["Later"] and any(x["section"] == 0 for x in lj["data"]["tasks"]), "list template with sections")
opn = db().execute("SELECT COUNT(*) FROM tasks WHERE list_id=? AND parent_id IS NULL AND status=0 AND deleted_at IS NULL", (WORK,)).fetchone()[0]
check(len(lj["data"]["tasks"]) == opn, f"list template: all open top-level tasks ({opn})")
nl = A.post(B + f"/api/templates/{lj['id']}/apply", json={"name": "Work 2"}).json()["list_id"]
st2 = A.get(B + "/api/state").json()
check(any(l["id"] == nl and l["name"] == "Work 2" and l["role"] == "owner" for l in st2["lists"]), "apply list template: new own list")
check([s["name"] for s in st2["sections"] if s["list_id"] == nl] == ["Later"], "new list has the sections")
insec = [t for t in st2["tasks"] if t["list_id"] == nl and t["title"] == "In section"]
check(insec and insec[0]["due"] == D(2) and insec[0]["section_id"] == [s["id"] for s in st2["sections"] if s["list_id"] == nl][0], "task in section with relative date")
check(len([x for x in st2["templates"] if x["kind"] == "list"]) == 1 and "data" not in st2["templates"][0], "state carries the light template list")
check(A.delete(B + f"/api/templates/{lj['id']}").ok and not any(x["id"] == lj["id"] for x in A.get(B + "/api/templates").json()["templates"]), "template delete")
check(Bb.delete(B + f"/api/templates/{tj['id']}").status_code == 404, "bob cannot delete alice's template")
check("templates" in A.get(B + "/api/export.json").json(), "export contains templates")

# ===================================================================== ICS
check(A.get(B + "/api/ical").json()["url"] is None, "no feed link until created")
url = A.post(B + "/api/ical", json={"action": "create"}).json()["url"]
check(url and url.startswith("https://kalmido.example/ical/1.") and url.endswith(".ics"), "feed link created: " + str(url))
check(A.post(B + "/api/ical", json={"action": "create"}).json()["url"] == url, "create keeps an existing link")
path = url.split("kalmido.example", 1)[1]
tricky = mk(A, title="Comma, semi; back\\slash 🎉 " + "x" * 80, list_id=WORK, due=D(1), due_time="15:30", content="line1\nline2; a,b",
            reminders="0,15", priority=5)
allday = mk(A, title="Allday", list_id=WORK, due=D(2), reminders="0")
rng = mk(A, title="Range", list_id=WORK, due=D(6), start=D(4))
rec = mk(A, title="Rec daily", list_id=WORK, due=D(0), due_time="08:00", repeat="FREQ=DAILY;UNTIL=" + D(4).replace("-", ""))
recw = mk(A, title="Rec weekly", list_id=WORK, due=D(0), repeat="FREQ=WEEKLY;COUNT=3")
recd = mk(A, title="Rec done-based", list_id=WORK, due=D(1), repeat="FREQ=DAILY", repeat_from="done")
wd = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][(today.weekday() + 1) % 7]  # tomorrow's weekday
offp = mk(A, title="Off pattern", list_id=WORK, due=D(0), repeat=f"FREQ=WEEKLY;BYDAY={wd};COUNT=3")
shared_t = mk(Bb, title="In shared list", list_id=SH, due=D(1))
assigned_t = mk(Bb, title="Assigned to alice", list_id=SH, due=D(1), assignee_id=1)
bobpriv = mk(Bb, title="BOB SECRET", list_id=PRIV, due=D(1))
nodate = mk(A, title="No date", list_id=WORK)
donet = mk(A, title="Done dated", list_id=WORK, due=D(1))
A.post(B + f"/api/tasks/{donet['id']}/complete")
r = requests.get(B + path)
check(r.status_code == 200 and r.headers["Content-Type"] == "text/calendar; charset=utf-8", "feed 200 text/calendar utf-8")
raw = r.content
check(all(len(x) <= 75 for x in raw.split(b"\r\n")), "every line <= 75 octets")
check(raw.endswith(b"\r\n") and b"\n" not in raw.replace(b"\r\n", b""), "CRLF line endings only")
unf = raw.decode("utf-8").replace("\r\n ", "")
check("BOB SECRET" not in unf, "no private task of another user")
cal = icalendar.Calendar.from_ical(raw)
ev = {str(e["SUMMARY"]): e for e in cal.walk("VEVENT")}
check(str(cal["X-WR-CALNAME"]) == "Kalmido · Alice", "calendar name")
check("In shared list" in ev and "Assigned to alice" in ev, "shared list tasks + assigned in the feed")
check("No date" not in ev and "Done dated" not in ev, "undated and completed tasks not in the feed")
tk = [e for s, e in ev.items() if s.startswith("Comma")][0]
check(str(tk["SUMMARY"]).startswith("Comma, semi; back\\slash 🎉 xxx"), "escaping round-trips (comma, semicolon, backslash, emoji)")
check("line1\nline2; a,b" in str(tk["DESCRIPTION"]) and "List: Work" in str(tk["DESCRIPTION"]) and f"/#t/{tricky['id']}" in str(tk["DESCRIPTION"]), "description: notes, list, deep link")
check(str(tk["URL"]) == f"https://kalmido.example/#t/{tricky['id']}", "URL = deep link")
dt0 = tk.decoded("DTSTART")
check(dt0 == datetime.combine(today + timedelta(days=1), datetime.min.time()).replace(hour=15, minute=30, tzinfo=dt0.tzinfo)
      and str(dt0.tzinfo) in ("Europe/Berlin", "CET", "CEST") and tk.decoded("DTEND") - dt0 == timedelta(minutes=30), "timed: local 15:30, 30 min")
check(tk["UID"] == f"task-{tricky['id']}@kalmido.example" and int(tk["PRIORITY"]) == 1, "stable UID + priority")
al = [a for a in tk.walk("VALARM")]
check(sorted(a.decoded("TRIGGER") for a in al) == [timedelta(minutes=-15), timedelta(0)], "VALARM triggers 0 / -15 min")
a2 = ev["Allday"]
check(a2.decoded("DTSTART") == today + timedelta(days=2) and a2.decoded("DTEND") == today + timedelta(days=3), "all-day event")
check([a.decoded("TRIGGER") for a in a2.walk("VALARM")] == [timedelta(hours=9)], "all-day reminder at 09:00")
check(ev["Range"].decoded("DTSTART") == today + timedelta(days=4) and ev["Range"].decoded("DTEND") == today + timedelta(days=7), "date range")
check("RRULE" not in ev["Rec done-based"], "repeat-from-completion: single event")
occ = recurring_ical_events.of(cal).between(today, today + timedelta(days=30))
dd = lambda s: sorted(str(o["DTSTART"].dt)[:10] for o in occ if str(o["SUMMARY"]) == s)  # noqa: E731
check(dd("Rec daily") == [D(i) for i in range(5)], "daily UNTIL expands to 5 occurrences: " + str(dd("Rec daily")))
check(dd("Rec weekly") == [D(0), D(7), D(14)], "weekly COUNT=3: " + str(dd("Rec weekly")))
exp = [D(0), D(1), D(8)]
check(dd("Off pattern") == exp, f"off-pattern occurrence split off: {dd('Off pattern')} == {exp}")
check(any(str(e["UID"]).endswith(f"{offp['id']}-series@kalmido.example") for e in cal.walk("VEVENT")), "series UID for the split")
check("BEGIN:VTIMEZONE" in unf and "TZID:Europe/Berlin" in unf and "BEGIN:DAYLIGHT" in unf, "VTIMEZONE with DST")
check(re.search(r"RRULE:FREQ=DAILY;UNTIL=\d{8}T\d{6}Z", unf), "timed UNTIL in UTC")
# scope mine
A.patch(B + "/api/settings", json={"ical_scope": "mine", "ical_alarms": "0"})
cal2 = icalendar.Calendar.from_ical(requests.get(B + path).content)
s2 = {str(e["SUMMARY"]) for e in cal2.walk("VEVENT")}
check("In shared list" not in s2 and "Assigned to alice" in s2 and "Allday" in s2, "scope mine: own + assigned only")
check(not list(cal2.walk("VALARM")), "alarms off")
A.patch(B + "/api/settings", json={"ical_scope": "all", "ical_alarms": "1"})
# language
A.patch(B + "/api/settings", json={"lang": "de"})
cal3 = icalendar.Calendar.from_ical(requests.get(B + path).content)
check("Liste: Work" in str([e for e in cal3.walk("VEVENT") if str(e["SUMMARY"]) == "Allday"][0]["DESCRIPTION"]), "description in the user's language")
A.patch(B + "/api/settings", json={"lang": "en"})
# auth: token only, no proxy header / session
check(A.get(B + "/ical/1.wrong.ics").status_code == 404, "wrong token -> 404 (even with a session)")
r = requests.get(BP + "/ical/1.wrong.ics", headers={"Remote-User": "alice-sso"})
check(r.status_code == 404 and b"BEGIN" not in r.content, "proxy header ignored on /ical/")
check(requests.get(BP + "/api/me", headers={"Remote-User": "alice-sso"}).json().get("username") == "alice", "(sanity) proxy header works elsewhere")
check(requests.get(B + "/ical/abc.ics").status_code == 404 and requests.get(B + "/ical/.ics").status_code == 404, "malformed tokens -> 404")
bob_url = Bb.post(B + "/api/ical", json={"action": "create"}).json()["url"]
bob_tok = bob_url.rsplit("/", 1)[1][:-4].split(".", 1)[1]
check(requests.get(B + f"/ical/1.{bob_tok}.ics").status_code == 404, "bob's secret with alice's id -> 404")
check("BOB SECRET" in requests.get(B + bob_url.split("kalmido.example", 1)[1]).text, "bob's own feed works")
new = A.post(B + "/api/ical", json={"action": "rotate"}).json()["url"]
check(new != url and requests.get(B + path).status_code == 404 and requests.get(B + new.split("kalmido.example", 1)[1]).ok, "rotate: old URL dead, new works")
A.post(B + "/api/ical", json={"action": "off"})
check(requests.get(B + new.split("kalmido.example", 1)[1]).status_code == 404 and A.get(B + "/api/ical").json()["url"] is None, "off: feed gone")
A.patch(B + "/api/users/" + str(BOB), json={"disabled": True})
check(requests.get(B + bob_url.split("kalmido.example", 1)[1]).status_code == 404, "disabled user's feed -> 404")
A.patch(B + "/api/users/" + str(BOB), json={"disabled": False})

# ===================================================================== statistics (seeded)
now = datetime.now(TZ)


def at(n, h=12):
    d = today + timedelta(days=n)
    return datetime(d.year, d.month, d.day, h, 0, tzinfo=TZ).astimezone(timezone.utc).isoformat(timespec="seconds")


c = db()
c.execute("UPDATE tasks SET deleted_at=? WHERE deleted_at IS NULL", (at(-400),))  # hide everything from above (trashed long ago)
c.execute("UPDATE tasks SET completed_by=NULL, status=0, completed_at=NULL")  # ...and no completions
c.execute("DELETE FROM pomos")
FOCUS_TASK = c.execute("INSERT INTO tasks(list_id,title,created_at,updated_at,created_by) VALUES(?,?,?,?,1)", (WORK, "ft", at(-50), at(-50))).lastrowid


def ins(lid, title, due=None, status=0, done=None, by=None, created=-60, deleted=None, assignee=None):
    return c.execute("""INSERT INTO tasks(list_id,title,due,status,completed_at,completed_by,created_at,updated_at,deleted_at,created_by,assignee_id)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (lid, title, due, status, at(done) if done is not None else None, by,
                                                            at(created), at(created), at(deleted) if deleted is not None else None, 1, assignee)).lastrowid


# completions of alice (id 1)
ins(WORK, "c0a", due=D(0), status=2, done=0, by=1)
ins(WORK, "c0b", due=D(-1), status=2, done=0, by=1)
ins(SH, "c1", due=D(1), status=2, done=-1, by=1)
ins(WORK, "c3", status=2, done=-3, by=1)
ins(WORK, "c20", due=D(-25), status=2, done=-20, by=1, created=-40)
ins(WORK, "c100", status=2, done=-100, by=1)
ins(PRIV, "cother", status=2, done=-2, by=1)
ins(WORK, "ctrash", status=2, done=-5, by=1, deleted=-1)
ins(SH, "cbob", status=2, done=0, by=BOB)
ins(WORK, "wont", status=-1, done=0, by=1)
# overdue candidates
ins(WORK, "o1", due=D(-10), created=-30)
ins(SH, "o3", due=D(-2), created=-5, assignee=1)
ins(SH, "o4 bob's", due=D(-3), created=-5)
ins(WORK, "odel", due=D(-15), created=-40, deleted=-5)
ins(WORK, "oassigned bob", due=D(-3), created=-5, assignee=BOB)


def pomo(n, minutes, kind="focus", task=None, uid=1):
    s = datetime.combine(today + timedelta(days=n), datetime.min.time()).replace(hour=0, minute=5, tzinfo=TZ)
    c.execute("INSERT INTO pomos(task_id,kind,minutes,start,end,done,user_id) VALUES(?,?,?,?,?,1,?)",
              (task, kind, minutes, s.astimezone(timezone.utc).isoformat(timespec="seconds"),
               (s + timedelta(minutes=minutes)).astimezone(timezone.utc).isoformat(timespec="seconds"), uid))


pomo(0, 25, task=FOCUS_TASK)
pomo(-3, 50, kind="stopwatch")
pomo(-90, 30)
pomo(0, 45, uid=BOB)
c.commit()
c.close()
S_ = A.get(B + "/api/stats").json()
mon0 = today - timedelta(days=today.weekday()) - timedelta(weeks=11)
wk = lambda n: ((today + timedelta(days=n)) - mon0).days // 7  # noqa: E731
exp_week = [0] * 12
for n in (0, 0, -1, -3, -20, -2, -5):
    exp_week[wk(n)] += 1
check(S_["done"]["per_week"] == exp_week, f"done per week {S_['done']['per_week']} == {exp_week}")
check(S_["done"]["total"] == 7 and S_["done"]["today"] == 2 and S_["done"]["per_day"].get(D(-1)) == 1, "done totals (7 in window, 2 today)")
bl = {x["id"]: x["n"] for x in S_["done"]["by_list"]}
check(bl == {WORK: 5, SH: 1, 0: 1}, f"by list incl. 'other' for an invisible list: {bl}")
check(all(x["name"] == "" for x in S_["done"]["by_list"] if x["id"] == 0), "invisible list name not leaked")
check(S_["ontime"] == {"with_due": 4, "ontime": 2, "rate": 50}, f"on-time: {S_['ontime']}")
check(S_["streak"] == {"current": 4, "best": 4}, f"streak {S_['streak']}")
samples = [mon0 + timedelta(weeks=i, days=6) for i in range(11)] + [today]


def exp_over(s):
    n = 0
    for due, created, done, deleted in ((D(-10), -30, None, None), (D(-2), -5, None, None), (D(-25), -40, -20, None), (D(-15), -40, None, -5)):
        cr, dn, dl = today + timedelta(days=created), (today + timedelta(days=done) if done is not None else None), (today + timedelta(days=deleted) if deleted is not None else None)
        if due < s.isoformat() and cr <= s and (not dl or dl > s) and (dn is None or dn > s):
            n += 1
    return n


eo = [exp_over(s) for s in samples]
check([x["n"] for x in S_["overdue"]] == eo and S_["overdue"][-1]["n"] == 2, f"overdue trend {[x['n'] for x in S_['overdue']]} == {eo}")
fw = [0] * 12
fw[wk(0)] += 25
fw[wk(-3)] += 50
check(S_["focus"]["per_week"] == fw and S_["focus"]["total"] == 75, f"focus per week {S_['focus']['per_week']} == {fw}")
fl = {x["id"]: x["minutes"] for x in S_["focus"]["by_list"]}
check(fl == {WORK: 25, -1: 50}, f"focus by list {fl}")
check(sess("bob").get(B + "/api/stats").json()["done"]["total"] == 1, "bob's stats: only his own completion")
# migration of completed_by on a legacy-shaped row: covered by the copy-of-live test (counts)

# ===================================================================== rate limit (last: blocks this IP for the window)
codes = [requests.get(B + f"/ical/1.bad{i}.ics").status_code for i in range(40)]
check(404 in codes and codes[-1] == 429, f"rate limit after repeated bad tokens: {codes[-3:]}")
print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
