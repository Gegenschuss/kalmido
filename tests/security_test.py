#!/usr/bin/env python3
"""Security regression tests (audit 2026-09-28): every finding of the audit + the design caveats.
Starts its OWN test container (start.sh, KALMIDO_TEST_IMAGE) on the test ports with a fake ntfy inbox / fake
Paperless / attacker sink inside the container (fake_services.py). Never touches the live stack.
usage: security_test.py <datadir>"""
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
IMG = os.environ.get("KALMIDO_TEST_IMAGE", "kalmido:test")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")


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


def fake_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "fake.log")) if x.strip()]
    except FileNotFoundError:
        return []


def pushes():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def logs():
    return subprocess.run(["docker", "logs", CT], capture_output=True, text=True).stdout + \
        subprocess.run(["docker", "logs", CT], capture_output=True, text=True).stderr


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def timed(fn):
    t0 = time.time()
    r = fn()
    return r, time.time() - t0


# ------------------------------------------------------------------ container with fakes
subprocess.run(["rm", "-rf", DATA])
os.makedirs(DATA)
subprocess.run(["cp", os.path.join(N, "fake_services.py"), DATA])
PUB = "https://ntfy.example.test"
inbox = [
    {"id": "m-foreign", "message": "foreign host attachment", "attachment": {"name": "loot.txt", "type": "text/plain", "url": "http://127.0.0.1:8084/steal"}},
    {"id": "m-file", "message": "file read attempt", "attachment": {"name": "db.bin", "type": "text/plain", "url": "file:///data/tasks.db"}},
    {"id": "m-lookalike", "message": "lookalike host", "attachment": {"name": "x.txt", "url": "https://ntfy.example.test.evil.example/file/x.txt"}},
    {"id": "m-userinfo", "message": "userinfo trick", "attachment": {"name": "y.txt", "url": "https://ntfy.example.test@127.0.0.1:8084/file/y.txt"}},
    {"id": "m-redirect", "message": "redirect to other host", "attachment": {"name": "r.txt", "url": PUB + "/file/redir"}},
    {"id": "m-good", "message": "legit share", "attachment": {"name": "good.txt", "type": "text/plain", "url": PUB + "/file/abc.txt"}},
    {"id": "m-good-internal", "message": "legit share internal url", "attachment": {"name": "good2.txt", "type": "text/plain", "url": "http://127.0.0.1:8081/file/def.txt"}},
    {"id": "m-link", "message": "link only http://127.0.0.1:8084/should-not-be-fetched"},
]
json.dump(inbox, open(os.path.join(DATA, "inbox.json"), "w"))
env = dict(os.environ, KALMIDO_TEST_IMAGE=IMG, KEEP="1", EXTRA=" ".join([
    "-e NTFY_INBOX_URL=http://127.0.0.1:8081", f"-e NTFY_INBOX_PUBLIC={PUB}", "-e NTFY_INBOX_TOKEN=inbox-secret-token",
    "-e NTFY_INBOX_TOPIC=inbox", "-e PAPERLESS_TOKEN=pl-secret-token", "-e PAPERLESS_API=http://127.0.0.1:8082",
    "-e PAPERLESS_PUBLIC_URL=https://paperless.example.test"]))
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_services.py"])

s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ids = {"alice": 1}
for u in ("bob", "carol", "mallory"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
Bo, Ca, Ma = sess("bob"), sess("carol"), sess("mallory")

# ------------------------------------------------------------------ HIGH-1: ntfy inbox SSRF / file read / token leak
t0 = time.time()
while time.time() - t0 < 35:
    titles = [t["title"] for t in A.get(B + "/api/state").json()["tasks"]]
    if sum(1 for m in inbox if any(m["message"].split(" http")[0] in x for x in titles)) >= len(inbox):
        break
    time.sleep(1)
st = A.get(B + "/api/state").json()
bytitle = {t["title"]: t for t in st["tasks"]}
check(all(any(m["message"].split(" http")[0] in x for x in bytitle) for m in inbox), "all inbox messages imported as tasks")
fl = fake_log()
check(not [x for x in fl if x["port"] == 8084], "no request ever reached the foreign host (8084): " + str([x["path"] for x in fl if x["port"] == 8084]))
check(all(x["auth"] in (None, "Bearer inbox-secret-token") for x in fl if x["port"] == 8081), "inbox token only sent to the ntfy server")
check(not [x for x in fl if x["port"] != 8081 and x["auth"] and "inbox-secret" in x["auth"]], "inbox token never sent elsewhere")
atts = {t["title"]: [a["name"] for a in t["attachments"]] for t in st["tasks"]}
check(atts.get("foreign host attachment") == [], "foreign attachment not stored")
check(atts.get("file read attempt") == [], "file:// attachment not read")
check(atts.get("lookalike host") == [] and atts.get("userinfo trick") == [], "lookalike / userinfo URLs not fetched")
check(atts.get("redirect to other host") == [], "cross-host redirect not followed")
check(atts.get("legit share") == ["good.txt"], "attachment on the public ntfy base is fetched (public -> internal)")
check(atts.get("legit share internal url") == ["good2.txt"], "attachment on the internal ntfy base is fetched")
good = next(a for a in bytitle["legit share"]["attachments"])
check(A.get(B + f"/api/attachments/{good['id']}").content == b"good file from ntfy", "fetched attachment content")
check([x for x in fl if x["port"] == 8081 and x["path"].startswith("/file/abc.txt") and x["auth"] == "Bearer inbox-secret-token"],
      "public attachment URL rewritten to the internal base, with token")
link_t = next((t for t in st["tasks"] if t["title"].startswith("link only")), None)
check(link_t is not None and (link_t.get("url") or "").startswith("http://127.0.0.1:8084"), "shared link stored in the link field, not fetched")
# task link field is never fetched server-side
A.post(B + "/api/tasks", json={"title": "link field", "url": "http://127.0.0.1:8084/link-field"})
time.sleep(1)
check(not [x for x in fake_log() if x["port"] == 8084], "task link field never fetched")
# safe opener + attachment URL mapping (unit level, inside the container, watchdog off)
unit = r'''
import app, urllib.request, urllib.error
app.NTFY_IN.update(url="http://ntfy-int:80", public="https://ntfy.example.test")
f = app.ntfy_attachment_url
res = [f("https://ntfy.example.test/file/a.txt"), f("http://ntfy-int:80/file/b"), f("https://ntfy.example.test.evil/file/a"),
       f("https://evil@ntfy.example.test/file/a"), f("file:///etc/passwd"), f("https://ntfy.example.test:444/file/a"),
       f("http://ntfy.example.test/file/a"), f("https://ntfy.example.test"), f(None), f("ftp://ntfy.example.test/file/a")]
print(repr(res))
for u in ("file:///etc/passwd", "ftp://example.com/x", "data:text/plain,hi"):
    try:
        app.safe_urlopen(urllib.request.Request(u), timeout=2)
        print("OPENED", u)
    except urllib.error.URLError:
        print("blocked")
app.NTFY_IN.update(url="https://ntfy.sh", topic="inbox"); print("allowed_ntfysh_inbox", app.ntfy_inbox_allowed())
app.NTFY_IN.update(url="https://ntfy.sh", topic="k3j4h5g6f7d8s9a0q1w2"); print("allowed_ntfysh_long", app.ntfy_inbox_allowed())
app.NTFY_IN.update(url="https://ntfy.example.test", topic="inbox"); print("allowed_own", app.ntfy_inbox_allowed())
'''
out = subprocess.run(["docker", "exec", "-e", "TASKS_WATCHDOG=0", "-w", "/app", CT, "python", "-c", unit],
                     capture_output=True, text=True).stdout
lines = out.strip().splitlines()
exp = repr(["http://ntfy-int:80/file/a.txt", "http://ntfy-int:80/file/b", None, None, None, None, None, None, None, None])
check(lines and lines[0] == exp, "ntfy_attachment_url mapping: " + (lines[0] if lines else out))
check(lines[1:4] == ["blocked"] * 3, "safe_urlopen blocks file/ftp/data: " + str(lines[1:4]))
check("allowed_ntfysh_inbox False" in out and "allowed_ntfysh_long True" in out and "allowed_own True" in out, "ntfy.sh + guessable topic refused")
r = subprocess.run(["docker", "run", "--rm", "--network", "none", "-e", "TASKS_DB=/tmp/x.db", "-e", "NTFY_INBOX_URL=https://ntfy.sh",
                    "-e", "NTFY_INBOX_TOKEN=x", "-w", "/app", IMG, "python", "-c", "import app"], capture_output=True, text=True)
check("ntfy inbox NOT started" in r.stdout + r.stderr, "importer refuses ntfy.sh with topic inbox at start")

# ------------------------------------------------------------------ HIGH-2: Paperless gate
check(A.get(B + "/api/state").json()["paperless"]["enabled"] is True, "admin (setup user) has Paperless access")
check(Ma.get(B + "/api/state").json()["paperless"]["enabled"] is False, "non-admin: paperless.enabled false")
check(Ma.get(B + "/api/state").json()["paperless"].get("url") == "", "non-admin: no Paperless URL")
check(Ma.get(B + "/api/paperless/search?q=salary").status_code == 403, "non-admin cannot search Paperless")
check(Ma.get(B + "/api/paperless/thumb/8").status_code == 403, "non-admin cannot fetch thumbnails")
mt = Ma.post(B + "/api/tasks", json={"title": "mallory task"}).json()["id"]
check(Ma.post(B + f"/api/tasks/{mt}/paperless", json={"doc_id": 7}).status_code == 403, "non-admin cannot link a document")
r = Ma.post(B + f"/api/tasks/{mt}/attachments", files={"file": ("m.pdf", b"%PDF-1.4 x", "application/pdf")})
maid = r.json()["attachments"][0]["id"]
check(Ma.post(B + f"/api/attachments/{maid}/to-paperless").status_code == 403, "non-admin cannot upload into Paperless")
check(not [x for x in fake_log() if x["port"] == 8082 and x["method"] == "POST"], "nothing was uploaded to Paperless")
r = A.get(B + "/api/paperless/search?q=salary")
check(r.ok and r.json()["items"][0]["title"] == "Admin salary slip 2026", "admin can search")
r = A.get(B + "/api/paperless/thumb/7")
check(r.status_code == 502 and "text/html" not in r.headers.get("Content-Type", ""), "html thumbnail from upstream is refused")
r = A.get(B + "/api/paperless/thumb/8")
check(r.ok and r.headers["Content-Type"] == "image/png" and r.headers.get("X-Content-Type-Options") == "nosniff"
      and "sandbox" in r.headers.get("Content-Security-Policy", ""), "image thumbnail: fixed type, nosniff, sandbox CSP")
users = {u["username"]: u for u in A.get(B + "/api/users").json()["users"]}
check(users["alice"]["paperless_access"] is True and users["bob"]["paperless_access"] is False, "users list shows paperless_access")
check(Bo.patch(B + f"/api/users/{ids['bob']}", json={"paperless_access": True}).status_code == 403, "non-admin cannot grant itself access")
check(A.patch(B + f"/api/users/{ids['bob']}", json={"paperless_access": True}).ok, "admin grants bob access")
check(Bo.get(B + "/api/paperless/search?q=x").ok and Bo.get(B + "/api/state").json()["paperless"]["enabled"], "bob has access now")
# shared list: alice links a doc, carol (member, no access) sees no title
Sh = A.post(B + "/api/lists", json={"name": "Shared", "kind": "project"}).json()["id"]
A.put(B + f"/api/lists/{Sh}/members", json={"user_id": ids["bob"], "role": "edit"})
A.put(B + f"/api/lists/{Sh}/members", json={"user_id": ids["carol"], "role": "edit"})
ts = A.post(B + "/api/tasks", json={"title": "shared doc task", "list_id": Sh}).json()["id"]
r = A.post(B + f"/api/tasks/{ts}/paperless", json={"doc_id": 9})
check(r.ok and r.json()["paperless"][0]["title"] == "Secret doc 9", "admin links a document")
pc = Ca.get(B + f"/api/tasks/{ts}").json()["paperless"]
check(pc and pc[0]["title"] == "Paperless document" and pc[0].get("hidden") and not pc[0]["correspondent"], "member without access: title hidden")
tl = Ca.get(B + f"/api/tasks/{ts}/timeline").json()
check(not [a for a in tl["activity"] if a["kind"] == "paperless" and "Secret" in json.dumps(a["data"])], "member without access: activity title hidden")
check(Ca.delete(B + f"/api/paperless-links/{pc[0]['id']}").status_code == 403, "member without access cannot unlink")
check(Bo.get(B + f"/api/tasks/{ts}").json()["paperless"][0]["title"] == "Secret doc 9", "member with access sees the title")

# ------------------------------------------------------------------ MEDIUM-1: validation + watchdog robustness
bad = [({"due": "not-a-date"}, "due"), ({"due": "2026-02-30"}, "impossible date"), ({"due": "2026-10-01", "due_time": "25:99"}, "due_time"),
       ({"due": "2026-10-01", "reminders": "abc"}, "reminders text"), ({"due": "2026-10-01", "reminders": "0,1e9"}, "reminders float"),
       ({"due": "2026-10-01", "reminders": "99999999"}, "reminder out of range"), ({"due": "2026-10-01", "start": "yesterday"}, "start"),
       ({"due": "2026-10-01", "due_time": "10:00", "duration": "x"}, "duration"), ({"due": "2026-10-01", "due_time": "10:00", "duration": 10 ** 9}, "duration range"),
       ({"priority": 7}, "priority"), ({"due": "2026-10-01", "repeat": "FREQ=SECONDLY"}, "secondly"),
       ({"due": "2026-10-01", "repeat": "FREQ=MINUTELY"}, "minutely"), ({"due": "2026-10-01", "repeat": "FREQ=HOURLY"}, "hourly"),
       ({"due": "2026-10-01", "repeat": "FREQ=DAILY;BYHOUR=1,2,3"}, "byhour"), ({"due": "2026-10-01", "repeat": "FREQ=DAILY;INTERVAL=0"}, "interval 0"),
       ({"due": "2026-10-01", "repeat": "garbage"}, "garbage rule"), ({"parent_id": "abc"}, "parent id text"), ({"title": ["x"]}, "title list")]
for extra, what in bad:
    r = A.post(B + "/api/tasks", json={"title": "bad " + what, **extra})
    check(r.status_code == 400, f"create rejects bad {what}: {r.status_code}")
r, dt = timed(lambda: A.post(B + "/api/tasks", json={"title": "impossible", "due": "2026-10-01", "repeat": "FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30"}))
check(r.status_code == 400 and dt < 2, f"never-matching rule rejected fast ({dt:.2f}s)")
ok_t = A.post(B + "/api/tasks", json={"title": "valid", "due": "2026-10-01", "due_time": "09:30", "reminders": "0,15", "repeat": "RRULE:FREQ=WEEKLY;BYDAY=MO", "duration": 30})
check(ok_t.ok and ok_t.json()["repeat"] == "FREQ=WEEKLY;BYDAY=MO" and ok_t.json()["reminders"] == "0,15", "valid values accepted (RRULE: prefix normalized)")
vid = ok_t.json()["id"]
for extra, what in bad[:6]:
    check(A.patch(B + f"/api/tasks/{vid}", json=extra).status_code == 400, f"patch rejects bad {what}")
r = A.post(B + "/api/tasks/batch", json={"ids": [vid], "action": "patch", "data": {"due": "nope"}}).json()
check(r["count"] == 0 and r["errors"], "batch patch reports the invalid value")
check(A.get(B + f"/api/tasks/{vid}").json()["due"] == "2026-10-01", "batch: nothing changed")
check(A.post(B + "/api/tasks/reorder", json={"items": [{"id": vid, "sort": 1, "due": "x"}]}).status_code == 400, "reorder rejects a bad date")
check(A.patch(B + "/api/settings", json={"allday_time": "garbage"}).status_code == 400, "settings reject bad allday_time")
check(A.patch(B + "/api/settings", json={"digest_time": "7 Uhr"}).status_code == 400, "settings reject bad digest_time")
check(A.patch(B + "/api/settings", json={"pomo_focus": "abc"}).status_code == 400, "settings reject non-numeric pomo")
check(A.patch(B + "/api/settings", json={"allday_time": "08:30", "digest_time": ""}).ok, "valid settings accepted")
tpl = A.post(B + "/api/templates", json={"kind": "task", "name": "T", "data": {"task": {"title": "tp", "due_offset": 1, "repeat": "FREQ=SECONDLY", "reminders": "0,abc"}}})
if tpl.ok:
    tj = [x for x in A.get(B + "/api/templates").json()["templates"] if x["id"] == tpl.json()["id"]]
    data = tj[0]["data"]["task"] if tj and "data" in tj[0] else None
    check(data is None or (data["repeat"] == "" and data["reminders"] == "0"), "template: sub-daily rule / bad reminder dropped")
else:
    check(tpl.status_code == 400, "template with bad values refused")

# poisoned rows written straight into the DB (bypassing the API, as old data could be) must not stop reminders
now = datetime.now(ZoneInfo("Europe/Berlin"))
today, tm = now.date().isoformat(), (now - timedelta(minutes=10)).strftime("%H:%M")
inbox_m = dbx("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (ids["mallory"],))[0][0]
ts_now = datetime.now().isoformat()
for due, dtm, rem, rep in (("not-a-date", None, "0", ""), (today, None, "abc", ""), (today, "25:99", "0", ""),
                           (today, tm, "0,1.5", ""), ("2026-13-45", "10:00", "0", "FREQ=SECONDLY")):
    dbx("INSERT INTO tasks(list_id,title,due,due_time,reminders,repeat,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
        (inbox_m, "poison", due, dtm, rem, rep, ts_now, ts_now, ids["mallory"]))
dbx("UPDATE user_settings SET value='garbage' WHERE user_id=? AND key='allday_time'", (ids["mallory"],))
dbx("INSERT INTO habits(name,remind_at,created_at,user_id,days,goal) VALUES('poison habit','xx:yy',?,?,'1234567','x')", (ts_now, ids["mallory"]))
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
leg = A.post(B + "/api/tasks", json={"title": "legit reminder after poison", "due": today, "due_time": tm, "reminders": "0"})
check(leg.ok, "legit reminder task created")
t0 = time.time()
while time.time() - t0 < 12 and not [p for p in pushes() if p["title"] == "legit reminder after poison"]:
    time.sleep(0.5)
check([p for p in pushes() if p["title"] == "legit reminder after poison" and p["topic"] == "t-alice"], "reminder fired despite poisoned rows")
lg = logs()
check("watchdog: reminder of task" in lg and "skipped" in lg, "poisoned rows are logged and skipped")
check("watchdog error:" not in lg, "no watchdog-wide error")

# ------------------------------------------------------------------ push priority (user setting, default 4)
check(A.get(B + "/api/state").json()["settings"].get("push_priority") == "4", "push priority defaults to 4")
check([p for p in pushes() if p["title"] == "legit reminder after poison" and p["prio"] == "4"], "reminder push has priority 4")
check(A.patch(B + "/api/settings", json={"push_priority": "9"}).status_code == 400, "invalid push priority refused")
for pr in ("3", "5", "4"):
    A.patch(B + "/api/settings", json={"push_priority": pr})
    n0 = len(pushes())
    A.post(B + "/api/ntfy/test")
    time.sleep(0.5)
    check([p for p in pushes()[n0:] if p["topic"] == "t-alice" and p["prio"] == pr], f"test push uses priority {pr}")
A.patch(B + "/api/settings", json={"push_priority": "3"})
time.sleep(2.5)  # a watchdog tick that already read the old setting finishes first (slow CI runners)
hi = A.post(B + "/api/tasks", json={"title": "high prio reminder", "priority": 5, "due": today, "due_time": tm, "reminders": "0"}).json()["id"]
lo = A.post(B + "/api/tasks", json={"title": "normal prio reminder", "due": today, "due_time": tm, "reminders": "0"}).json()["id"]
A.post(B + "/api/habits", json={"name": "prio habit", "remind_at": "00:00"})
A.patch(B + "/api/settings", json={"digest_time": "00:00"})
t0 = time.time()
want = ("high prio reminder", "normal prio reminder", "Habit: prio habit", "Today")
while time.time() - t0 < 12 and not all(any(p["title"] == w for p in pushes()) for w in want):
    time.sleep(0.5)
pp = {p["title"]: p["prio"] for p in pushes() if p["topic"] == "t-alice"}
check(pp.get("normal prio reminder") == "3", "reminder follows the user setting 3: " + str(pp.get("normal prio reminder")))
check(pp.get("high prio reminder") == "4", "reminder of a high-priority task never below 4: " + str(pp.get("high prio reminder")))
check(pp.get("Habit: prio habit") == "3", "habit push follows the setting: " + str(pp.get("Habit: prio habit")))
check(pp.get("Today") == "3", "digest push follows the setting: " + str(pp.get("Today")))
Ca.patch(B + "/api/settings", json={"push_priority": "5"})
A.patch(B + "/api/users/" + str(ids["carol"]), json={"ntfy_topic": "t-carol"})
asg = A.post(B + "/api/tasks", json={"title": "assign prio", "list_id": Sh, "assignee_id": ids["carol"]})
time.sleep(1)
check([p for p in pushes() if p["topic"] == "t-carol" and p["prio"] == "5"], "collaboration push uses the recipient's priority 5")
A.patch(B + "/api/settings", json={"push_priority": "4", "digest_time": ""})

# ------------------------------------------------------------------ MEDIUM-2: RRULE caps + parent cycles
daily = A.post(B + "/api/tasks", json={"title": "daily", "due": "2026-01-01", "repeat": "FREQ=DAILY"}).json()["id"]
r, dt = timed(lambda: A.get(B + "/api/occurrences?from=2026-01-01&to=2027-01-31"))
items = [x for x in r.json()["items"] if x["id"] == daily]
check(r.ok and len(items) <= 120 and dt < 3, f"occurrences capped per task ({len(items)}) and fast ({dt:.2f}s)")
check(A.get(B + "/api/occurrences?from=2026-01-01&to=2028-01-01").status_code == 400, "range > 400 days refused")
# rules that bypassed validation (old data): expansion stays fast
my_inbox = dbx("SELECT id FROM lists WHERE owner_id=1 AND is_inbox=1")[0][0]
for rule in ("FREQ=SECONDLY", "FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30", "FREQ=DAILY;BYHOUR=0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23;BYMINUTE=0,1,2,3,4,5,6,7,8,9"):
    dbx("INSERT INTO tasks(list_id,title,due,repeat,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,1)",
        (my_inbox, "raw " + rule[:20], "2026-09-01", rule, ts_now, ts_now))
r, dt = timed(lambda: A.get(B + "/api/occurrences?from=2026-09-01&to=2027-09-30"))
check(r.ok and dt < 3, f"occurrences with raw bad rules fast ({dt:.2f}s)")
check(not [x for x in r.json()["items"] if x["id"] in {t[0] for t in dbx("SELECT id FROM tasks WHERE title LIKE 'raw %'")}], "bad raw rules are not expanded")
for (rid,) in dbx("SELECT id FROM tasks WHERE title LIKE 'raw %'"):
    r, dt = timed(lambda: A.post(B + f"/api/tasks/{rid}/complete", json={}))
    check(r.ok and dt < 3, f"complete with a bad raw rule is fast ({dt:.2f}s)")
tok = A.post(B + "/api/ical").json()
feed = tok.get("url") or ""
if feed:
    r, dt = timed(lambda: requests.get(B + "/ical/" + feed.rsplit("/ical/", 1)[1]))
    check(r.ok and dt < 3, f"ICS feed fast ({dt:.2f}s)")
r, dt = timed(lambda: A.get(B + "/api/stats"))
check(r.ok and dt < 3, f"stats fast ({dt:.2f}s)")
# TickTick import with a parent cycle
csvt = '"Folder Name","List Name","Title","Status","taskId","parentId","Order"\n"","Cyc","A","0","a1","b1","1"\n"","Cyc","B","0","b1","a1","2"\n"","Cyc","C","0","c1","c1","3"\n'
r = A.post(B + "/api/import/ticktick", files={"file": ("t.csv", csvt.encode(), "text/csv")})
check(r.ok, "cyclic TickTick import accepted: " + r.text[:100])
rows = dbx("SELECT id, parent_id, title FROM tasks WHERE title IN ('A','B','C') AND created_by=1")
par = {x[0]: x[1] for x in rows}
cyc = any(par.get(par.get(i)) == i for i in par) or any(par[i] == i for i in par)
check(not cyc, "import created no parent cycle: " + str(rows))
# existing cycle in the DB (old data): delete / move / state finish quickly
a1 = A.post(B + "/api/tasks", json={"title": "cycA"}).json()["id"]
b1 = A.post(B + "/api/tasks", json={"title": "cycB", "parent_id": a1}).json()["id"]
check(A.patch(B + f"/api/tasks/{a1}", json={"parent_id": b1}).status_code == 400, "API refuses a parent cycle")
check(A.patch(B + f"/api/tasks/{a1}", json={"parent_id": str(a1)}).status_code == 400, "API refuses self-parent given as string")
dbx("UPDATE tasks SET parent_id=? WHERE id=?", (b1, a1))  # forced cycle
r, dt = timed(lambda: A.get(B + "/api/state"))
check(r.ok and dt < 3, f"state with a cycle is fast ({dt:.2f}s)")
L2 = A.post(B + "/api/lists", json={"name": "other"}).json()["id"]
r, dt = timed(lambda: A.patch(B + f"/api/tasks/{a1}", json={"list_id": L2}))
check(r.ok and dt < 3, f"moving a cyclic task finishes ({dt:.2f}s)")
r, dt = timed(lambda: A.post(B + f"/api/tasks/{a1}/complete", json={}))
check(r.ok and dt < 3, f"completing a cyclic task finishes ({dt:.2f}s)")
r, dt = timed(lambda: A.delete(B + f"/api/tasks/{a1}"))
check(r.ok and dt < 3, f"soft delete of a cyclic task finishes ({dt:.2f}s)")
r, dt = timed(lambda: A.delete(B + f"/api/tasks/{a1}?hard=1"))
check(r.ok and dt < 3, f"hard delete of a cyclic task finishes ({dt:.2f}s)")
check(not dbx("SELECT 1 FROM tasks WHERE id IN (?,?)", (a1, b1)), "cyclic pair deleted")

# ------------------------------------------------------------------ MEDIUM-4: list color / view / folder
L = A.post(B + "/api/lists", json={"name": "colors"}).json()["id"]
for body, what in (({"color": "red;background:url(https://e/x)"}, "css injection color"), ({"color": '"><img src=x onerror=alert(1)>'}, "html color"),
                   ({"color": "#12345"}, "5-digit color"), ({"view": 'kanban"><img src=x>'}, "view"), ({"view": "calendar"}, "unknown view"),
                   ({"folder": ["x"]}, "folder list"), ({"name": ""}, "empty name")):
    check(A.patch(B + f"/api/lists/{L}", json=body).status_code == 400, f"list update rejects {what}")
check(A.post(B + "/api/lists", json={"name": "x", "color": "url(x)"}).status_code == 400, "list create rejects bad color")
check(A.post(B + "/api/lists", json={"name": "x", "view": "evil"}).status_code == 400, "list create rejects bad view")
for col in ("#abc", "#a1b2c3", "#a1b2c3d4", ""):
    check(A.patch(B + f"/api/lists/{L}", json={"color": col}).ok, f"color {col or 'empty'} accepted")
check(A.patch(B + f"/api/lists/{L}", json={"folder": "F" * 500}).ok and len(next(x for x in A.get(B + "/api/state").json()["lists"] if x["id"] == L)["folder"]) == 100,
      "folder truncated to 100 characters")
check(Bo.patch(B + f"/api/lists/{Sh}", json={"view": "x\"><b>"}).status_code == 400, "member view validated")
check(Bo.patch(B + f"/api/lists/{Sh}", json={"view": None}).ok, "member view reset to the owner's")
check(A.post(B + "/api/lists/reorder", json={"ids": [L], "folder": {str(L): {"x": 1}}}).status_code == 400, "reorder folder must be text")
check(A.post(B + "/api/habits", json={"name": "h", "color": "red;x:y"}).status_code == 400, "habit color validated")
hid = A.post(B + "/api/habits", json={"name": "h", "color": "#6d8cff", "remind_at": "08:00"}).json()["id"]
check(A.patch(B + f"/api/habits/{hid}", json={"goal": '"><img>'}).status_code == 400, "habit goal validated")
check(A.patch(B + f"/api/habits/{hid}", json={"remind_at": "25:00"}).status_code == 400, "habit remind_at validated")
check(A.post(B + "/api/folders/rename", json={"old": "F" * 100, "new": "G" * 300}).ok, "folder rename accepted")
check(all(len(x["folder"]) <= 100 for x in A.get(B + "/api/state").json()["lists"]), "renamed folder truncated")

# ------------------------------------------------------------------ LOW-3: headers
for path, sess_ in (("/", None), ("/api/state", A), ("/api/health", None)):
    r = (sess_ or requests).get(B + path)
    csp = r.headers.get("Content-Security-Policy", "")
    check("frame-ancestors 'none'" in csp and r.headers.get("X-Frame-Options") == "DENY" and "camera=()" in r.headers.get("Permissions-Policy", "")
          and r.headers.get("Referrer-Policy") == "same-origin" and r.headers.get("X-Content-Type-Options") == "nosniff", f"security headers on {path}")
r = A.post(B + f"/api/tasks/{vid}/attachments", files={"file": ("p.png", b"\x89PNG\r\n\x1a\nx", "image/png")})
aid = r.json()["attachments"][0]["id"]
check("sandbox" in A.get(B + f"/api/attachments/{aid}").headers.get("Content-Security-Policy", ""), "attachment keeps its sandbox CSP")

# ------------------------------------------------------------------ LOW-2: login timing
def t_login(u):
    t0 = time.perf_counter()
    requests.post(B + "/api/auth/login", json={"username": u, "password": "wrong-password"}, headers=H)
    return time.perf_counter() - t0


unknown = [t_login(f"ghost{i}x") for i in range(6)]
known = [t_login("carol") for _ in range(4)]
mu, mk = statistics.median(unknown), statistics.median(known)
check(0.6 < mu / mk < 1.6, f"login timing unknown vs known user similar ({mu * 1000:.0f} ms vs {mk * 1000:.0f} ms)")

# ------------------------------------------------------------------ design caveats: moves out of shared lists
bi = next(x for x in Bo.get(B + "/api/state").json()["lists"] if x["is_inbox"])["id"]
t_sh = A.post(B + "/api/tasks", json={"title": "alice shared task", "list_id": Sh}).json()["id"]
A.post(B + "/api/tasks", json={"title": "sub of shared", "parent_id": t_sh})
A.post(B + f"/api/tasks/{t_sh}/comments", json={"body": "alice comment"})
r = Bo.patch(B + f"/api/tasks/{t_sh}", json={"list_id": bi})
check(r.status_code == 403 and "owner" in r.json().get("error", ""), "edit member cannot move a shared task into their own list")
check(Bo.post(B + "/api/tasks/reorder", json={"items": [{"id": t_sh, "list_id": bi, "sort": 1}]}).status_code == 403, "nor via reorder")
r = Bo.post(B + "/api/tasks/batch", json={"ids": [t_sh], "action": "patch", "data": {"list_id": bi}}).json()
check(r["count"] == 0 and r["errors"], "nor via batch")
b_sub = Bo.post(B + "/api/tasks", json={"title": "bob parent"}).json()["id"]
check(Bo.patch(B + f"/api/tasks/{t_sh}", json={"parent_id": b_sub}).status_code == 403, "nor by indenting under an own task")
check(A.get(B + f"/api/tasks/{t_sh}").json()["list_id"] == Sh, "task stayed in the shared list")
Sh2 = A.post(B + "/api/lists", json={"name": "Shared 2"}).json()["id"]
A.put(B + f"/api/lists/{Sh2}/members", json={"user_id": ids["bob"], "role": "edit"})
check(Bo.patch(B + f"/api/tasks/{t_sh}", json={"list_id": Sh2}).status_code == 403, "edit member cannot move to a list carol cannot see")
A.put(B + f"/api/lists/{Sh2}/members", json={"user_id": ids["carol"], "role": "view"})
check(Bo.patch(B + f"/api/tasks/{t_sh}", json={"list_id": Sh2}).ok, "edit member may move between lists with the same people")
check(Bo.patch(B + f"/api/tasks/{t_sh}", json={"list_id": Sh}).ok, "and back")
check(A.patch(B + f"/api/tasks/{t_sh}", json={"list_id": L2}).ok, "owner may move out")
A.patch(B + f"/api/tasks/{t_sh}", json={"list_id": Sh})
bo_own = Bo.post(B + "/api/tasks", json={"title": "bob own"}).json()["id"]
check(Bo.patch(B + f"/api/tasks/{bo_own}", json={"list_id": Sh}).ok, "edit member may move an own task INTO the shared list")
# auditor's orphan scenario: a subtask of bob's parent lives in alice's list; bob loses access and moves his parent
t1 = Bo.post(B + "/api/tasks", json={"title": "bob parent 2", "list_id": bi}).json()["id"]
t2 = Bo.post(B + "/api/tasks", json={"title": "will live in Shared", "parent_id": t1}).json()["id"]
check(Bo.post(B + "/api/tasks/reorder", json={"items": [{"id": t2, "list_id": Sh}]}).ok, "bob moves the child into the shared list")
A.patch(B + f"/api/tasks/{t2}", json={"content": "alice confidential notes"})
A.delete(B + f"/api/lists/{Sh}/members/{ids['bob']}")
b2 = Bo.post(B + "/api/lists", json={"name": "bob other"}).json()["id"]
check(Bo.patch(B + f"/api/tasks/{t1}", json={"list_id": b2}).ok, "bob may move his own parent")
x = A.get(B + f"/api/tasks/{t2}")
check(x.ok and x.json()["list_id"] == Sh and x.json()["parent_id"] is None, "the child stayed with alice (detached)")
check(Bo.get(B + f"/api/tasks/{t2}").status_code == 404, "bob cannot read alice's task")
A.put(B + f"/api/lists/{Sh}/members", json={"user_id": ids["bob"], "role": "edit"})

# ------------------------------------------------------------------ design caveats: hard delete owner-only
th = A.post(B + "/api/tasks", json={"title": "hard delete target", "list_id": Sh}).json()["id"]
r = Bo.delete(B + f"/api/tasks/{th}?hard=1")
check(r.status_code == 403, "edit member cannot hard-delete in a shared list")
check(Bo.delete(B + f"/api/tasks/{th}").ok, "edit member can move it to the trash")
check(Bo.delete(B + "/api/trash").ok and dbx("SELECT 1 FROM tasks WHERE id=?", (th,)), "member's 'empty trash' keeps the shared list's tasks")
check(A.delete(B + f"/api/tasks/{th}?hard=1").ok and not dbx("SELECT 1 FROM tasks WHERE id=?", (th,)), "owner can hard-delete")
# bob hard-deletes his own parent whose child is in alice's list: the child survives
p3 = Bo.post(B + "/api/tasks", json={"title": "bob parent 3", "list_id": bi}).json()["id"]
c3 = Bo.post(B + "/api/tasks", json={"title": "child in shared", "parent_id": p3}).json()["id"]
Bo.post(B + "/api/tasks/reorder", json={"items": [{"id": c3, "list_id": Sh}]})
check(Bo.delete(B + f"/api/tasks/{p3}?hard=1").ok, "bob hard-deletes his own parent")
check(dbx("SELECT parent_id FROM tasks WHERE id=?", (c3,)) == [(None,)], "child in alice's list survived (detached)")

# ------------------------------------------------------------------ design caveats: time entry title after losing access
tt = A.post(B + "/api/tasks", json={"title": "Original title", "list_id": Sh}).json()["id"]
now_s = datetime.now().strftime("%Y-%m-%dT%H:%M")
Bo.post(B + "/api/time/entries", json={"task_id": tt, "start": now_s, "minutes": 15})
A.post(B + "/api/time/entries", json={"task_id": tt, "start": now_s, "minutes": 10})
A.delete(B + f"/api/lists/{Sh}/members/{ids['bob']}")
A.patch(B + f"/api/tasks/{tt}", json={"title": "Secret new title"})
bo_titles = [e["title"] for e in Bo.get(B + "/api/time/entries").json().get("entries", [])]
check("Secret new title" not in bo_titles and "Original title" in bo_titles, "former member keeps the old title: " + str(bo_titles))
check(dbx("SELECT task_title FROM time_entries WHERE task_id=? AND user_id=1", (tt,)) == [("Secret new title",)], "owner's entry follows the rename")
check(dbx("SELECT task_title FROM time_entries WHERE task_id=? AND user_id=?", (tt, ids["bob"])) == [("Original title",)], "former member's snapshot not updated")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
