#!/usr/bin/env python3
"""1.0 tests: version / about, the instance-wide collaboration switch, the update check (fake GitHub API
inside the container) and (2.36.0) no Paperless data in any answer. Starts its OWN test container (start.sh).
usage: v1_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
IMG = os.environ.get("KALMIDO_TEST_IMAGE", "kalmido:test")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
VERSION = open(os.path.join(N, "..", "VERSION"), encoding="utf-8").read().strip()


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
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def release(body, status=200):
    """What the fake GitHub API answers next (read per request by the fake server)."""
    json.dump({"status": status, "body": body}, open(os.path.join(DATA, "release.json"), "w"))


FAKE = r'''
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        with open("/data/release.log", "a") as f:
            f.write(json.dumps({"path": self.path, "ua": self.headers.get("User-Agent")}) + "\n")
        r = json.load(open("/data/release.json"))
        b = r["body"] if isinstance(r["body"], str) else json.dumps(r["body"])
        b = b.encode()
        self.send_response(r["status"]); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
ThreadingHTTPServer(("127.0.0.1", 9998), H).serve_forever()
'''


def fake_calls():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "release.log")) if x.strip()]
    except FileNotFoundError:
        return []


def about(s):
    return s.get(B + "/api/about").json()


def wait_checked(s, after, timeout=8):
    t0 = time.time()
    while time.time() - t0 < timeout:
        a = about(s)
        if a.get("checked_at") and a["checked_at"] != after:
            return a
        time.sleep(0.3)
    return about(s)


# ------------------------------------------------------------------ container: update check on, fake release API
subprocess.run(["docker", "rm", "-f", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True)  # 2.7.2: the old container must not write while its data goes
subprocess.run(["rm", "-rf", DATA])
os.makedirs(DATA, exist_ok=True)
open(os.path.join(DATA, "fake_release.py"), "w").write(FAKE)
release({"tag_name": "v99.0.1", "html_url": "https://github.com/example/kalmido/releases/tag/v99.0.1"})
env = dict(os.environ, KEEP="1", EXTRA=" ".join([
    "-e KALMIDO_UPDATE_CHECK=1", "-e KALMIDO_UPDATE_URL=http://127.0.0.1:9998/repos/x/releases/latest",
    "-e PAPERLESS_TOKEN=pl-test-token", "-e PAPERLESS_API=http://127.0.0.1:9"]))
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_release.py"])
time.sleep(0.8)

s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ids = {"alice": 1}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")

# ------------------------------------------------------------------ version / about / health
h = requests.get(B + "/api/health")
check(h.status_code == 200 and h.json() == {"ok": True}, f"health stays minimal: {h.text}")
check(requests.get(B + "/api/about").status_code == 401, "about needs a login")
check(about(A)["version"] == VERSION, f"about: version from the VERSION file ({VERSION})")
check(A.get(B + "/api/state").json()["about"]["version"] == VERSION, "state carries the version")
ab = about(Bo)
check(set(ab) == {"version"}, f"non-admin: only the version, no update info: {ab}")
check(A.get(B + "/api/state").json()["collab_all"] is True, "collab_all on by default")

# ------------------------------------------------------------------ update check (fake GitHub API)
a0 = about(A)
check(a0["update_env"] is True and a0["update_check"] is True, "update check on (env + setting)")
# the check at start ran before the fake server was up -> force one by switching the setting off / on
check(Bo.patch(B + "/api/admin/settings", json={"update_check": False}).status_code == 403, "non-admin cannot change instance settings")
check(A.patch(B + "/api/admin/settings", json={"update_check": "no"}).status_code == 400, "admin settings: booleans only")
n0 = len(fake_calls())
A.patch(B + "/api/admin/settings", json={"update_check": False})
check(len(fake_calls()) == n0, "switching the check off asks nothing")
A.patch(B + "/api/admin/settings", json={"update_check": True})
a = wait_checked(A, a0.get("checked_at"))
check(a["available"] is True and a["latest"] == "99.0.1" and a["url"].endswith("/v99.0.1"), f"newer release found: {a}")
calls = fake_calls()
check(len(calls) == n0 + 1 and calls[-1]["ua"].startswith("Kalmido/" + VERSION), f"one request with a plain user agent: {calls[-1:]}")
check(about(Bo) == {"version": VERSION}, "non-admin still sees no update info")
# cached: another pass of the loop / a restart within the interval does not ask again (UPDATE_EVERY)
n1 = len(fake_calls())
subprocess.run(["docker", "exec", CT, "python", "-c",
                "import os; os.environ['TASKS_WATCHDOG']='0'; import app; c=app.connect(); app.update_check(c); print('ok')"],
               capture_output=True, text=True)
check(len(fake_calls()) == n1, "cached result: no second request within the check interval (6 h)")
# older / equal release -> nothing available
release({"tag_name": "v0.0.1", "html_url": "https://github.com/example/kalmido/releases/tag/v0.0.1"})
prev = about(A)["checked_at"]
A.patch(B + "/api/admin/settings", json={"update_check": True})
a = wait_checked(A, prev)
# 1.9.0: a release older than the running version is never shown as "latest" (it is the running version then)
check(a["available"] is False and a["latest"] == a["version"] and a["url"] == "", f"older release: no update: {a}")
# hostile answers: odd tag, non-github link, too large, http error -> never shown as update, link dropped
release({"tag_name": "v100.0.0", "html_url": "javascript:alert(1)"})
prev = about(A)["checked_at"]
A.patch(B + "/api/admin/settings", json={"update_check": True})
a = wait_checked(A, prev)
check(a["available"] is True and a["url"] == "", f"non-github link is dropped: {a}")
for body, st, what in (({"tag_name": "latest<script>"}, 200, "bad tag"), ("x" * 300000, 200, "too large"),
                       ({"message": "rate limited"}, 403, "http error"), ({"tag_name": "v200.0.0", "prerelease": True}, 200, "prerelease")):
    release(body, st)
    prev = about(A)["checked_at"]
    A.patch(B + "/api/admin/settings", json={"update_check": True})
    a = wait_checked(A, prev)
    check(a["error"] and a["latest"] == "100.0.0", f"{what}: error recorded, last known release kept: {a}")
release({"message": "Not Found"}, 404)
prev = about(A)["checked_at"]
A.patch(B + "/api/admin/settings", json={"update_check": True})
a = wait_checked(A, prev)
check(a["error"] == "" and a["latest"] == "100.0.0", f"404 (no release yet) is not an error: {a}")
A.patch(B + "/api/admin/settings", json={"update_check": False})
check(about(A)["available"] is False, "setting off: no update shown")
# env off: never asks, setting cannot turn it on
r = subprocess.run(["docker", "run", "--rm", "--network", "none", "-e", "TASKS_DB=/tmp/x.db", "-e", "TASKS_WATCHDOG=0",
                    "-e", "KALMIDO_UPDATE_CHECK=0", "-w", "/app", IMG, "python", "-c",
                    "import app; c=app.connect(); print(app.UPDATE_CHECK_ENV, app.update_enabled(c))"], capture_output=True, text=True)
check(r.stdout.strip().splitlines()[-1:] == ["False False"], f"KALMIDO_UPDATE_CHECK=0 turns it off: {r.stdout} {r.stderr[-300:]}")

# ------------------------------------------------------------------ Paperless rows stay in the database, never in an answer
# 2.36.0 (#1116): the Paperless connection is removed; linked documents stay in paperless_links (the way back) but no task,
# state or export answer carries them any more
lid = A.post(B + "/api/lists", json={"name": "Shared", "kind": "project"}).json()["id"]
A.put(B + f"/api/lists/{lid}/members", json={"user_id": ids["bob"], "role": "edit"})
tid = A.post(B + "/api/tasks", json={"title": "with document", "list_id": lid}).json()["id"]
dbx("INSERT INTO paperless_links(task_id,doc_id,title,correspondent,created,status,added_at) VALUES(?,?,?,?,?,'ok',?)",
    (tid, 4711, "Salary 2026", "Employer", "2026-01-01", "2026-09-01T00:00:00Z"))
ta = A.get(B + f"/api/tasks/{tid}").json()
tb = Bo.get(B + f"/api/tasks/{tid}").json()
check("paperless" not in ta and "paperless" not in tb, "task: no Paperless field")
sb = [t for t in Bo.get(B + "/api/state").json()["tasks"] if t["id"] == tid][0]
check("paperless" not in sb and "Salary 2026" not in Bo.get(B + "/api/state").text, "state: no Paperless data")
blid = Bo.post(B + "/api/lists", json={"name": "Bob own", "kind": "project"}).json()["id"]
btid = Bo.post(B + "/api/tasks", json={"title": "bob doc", "list_id": blid}).json()["id"]
dbx("INSERT INTO paperless_links(task_id,doc_id,title,status,added_at) VALUES(?,?,?,'ok',?)", (btid, 815, "Contract", "2026-09-01T00:00:00Z"))
ex = Bo.get(B + "/api/export.json").json()
check("paperless_links" not in ex and "paperless_connections" not in ex, "export: no Paperless data")
exa = A.get(B + "/api/export.json")
check("Salary 2026" not in exa.text, "export of the owner: no Paperless titles")
check(dbx("SELECT COUNT(*) FROM paperless_links")[0][0] == 2, "the rows stay in the database")
tl = A.post(B + f"/api/tasks/{tid}/comments", json={"body": "see doc"})
check(tl.ok, "comment while collaboration is on")

# ------------------------------------------------------------------ collaboration for everyone: OFF
t_bob = A.post(B + "/api/tasks", json={"title": "assigned to bob", "list_id": lid, "assignee_id": ids["bob"]}).json()["id"]
A.post(B + f"/api/lists/{lid}/status", json={"status": "at_risk", "note": "slow"})
before = {t: dbx(f"SELECT COUNT(*) FROM {t}")[0][0] for t in ("list_members", "comments", "activity", "notifications", "list_status", "tasks")}
news_before = dbx("SELECT COUNT(*) FROM notifications")[0][0]
check(Bo.patch(B + "/api/admin/settings", json={"collab_all": False}).status_code == 403, "non-admin cannot switch collaboration off")
open(os.path.join(DATA, "ntfy.log"), "w").close()
r = A.patch(B + "/api/admin/settings", json={"collab_all": False})
check(r.ok and r.json()["collab_all"] is False, "admin switches collaboration off")
st_a, st_b = A.get(B + "/api/state").json(), Bo.get(B + "/api/state").json()
check(st_a["collab_all"] is False and st_b["collab_all"] is False, "state: collab_all false for everyone")
la = [l for l in st_a["lists"] if l["id"] == lid][0]
check(la["shared"] is False and la["members"] == [], "owner: list no longer shows members")
check(lid not in [l["id"] for l in st_b["lists"]] and tid not in [t["id"] for t in st_b["tasks"]], "member: shared list + tasks hidden")
check(Bo.get(B + f"/api/tasks/{tid}").status_code == 404, "member: task of the shared list unreachable")
check(Bo.patch(B + f"/api/tasks/{tid}", json={"title": "x"}).status_code == 404, "member: cannot change it")
refused = {
    "share": A.put(B + f"/api/lists/{lid}/members", json={"user_id": ids["carol"], "role": "view"}),
    "unshare": A.delete(B + f"/api/lists/{lid}/members/{ids['bob']}"),
    "leave": Bo.delete(B + f"/api/lists/{lid}/members/{ids['bob']}"),
    "status": A.post(B + f"/api/lists/{lid}/status", json={"status": "on_track"}),
    "status history": A.get(B + f"/api/lists/{lid}/status"),
    "assign": A.patch(B + f"/api/tasks/{tid}", json={"assignee_id": ids["bob"]}),
    "assign on create": A.post(B + "/api/tasks", json={"title": "y", "list_id": lid, "assignee_id": ids["alice"]}),
}
for k, r in refused.items():
    check(r.status_code == 403 and "Collaboration is turned off" in r.json().get("error", ""), f"off: {k} refused with 403 ({r.status_code} {r.text[:80]})")
# 2.0.6 (#315): comments stay as personal notes: the timeline without activity / people, a comment without mentions,
# News or pushes; the author rule for editing stays
tl0 = A.get(B + f"/api/tasks/{tid}/timeline")
check(tl0.ok and tl0.json()["activity"] == [] and tl0.json()["people"] == [] and len(tl0.json()["comments"]) == 1, f"off: timeline = comments only ({tl0.status_code})")
r = A.post(B + f"/api/tasks/{tid}/comments", json={"body": "hi <@%d>" % ids["bob"]})
check(r.ok and r.json()["mentions"] == [], f"off: a comment is a note, no mention ({r.status_code} {r.text[:80]})")
check(A.patch(B + f"/api/comments/{r.json()['id']}", json={"body": "note"}).ok and A.delete(B + f"/api/comments/{r.json()['id']}").ok, "off: own note: edit + delete work")
check(A.patch(B + f"/api/tasks/{t_bob}", json={"assignee_id": ids["bob"], "title": "same assignee"}).ok, "off: unchanged assignee still saves")
check(A.patch(B + f"/api/tasks/{t_bob}", json={"title": "renamed"}).ok, "off: normal edits work")
n = Bo.get(B + "/api/news").json()
check(n.get("enabled") is False and n.get("items") == [], f"off: News empty + disabled: {str(n)[:120]}")
check(Bo.get(B + "/api/users").json()["users"] == [{k: v for k, v in Bo.get(B + '/api/me').json().items() if k in ('id', 'username', 'display_name')}]
      or len(Bo.get(B + "/api/users").json()["users"]) == 1, "off: non-admin user directory only has themselves")
A.post(B + f"/api/tasks/{t_bob}/complete")
time.sleep(1.5)
check(dbx("SELECT COUNT(*) FROM notifications")[0][0] == news_before, "off: completing an assigned task writes no News")
check(not [x for x in (open(os.path.join(DATA, "ntfy.log")).read().splitlines() if os.path.exists(os.path.join(DATA, "ntfy.log")) else [])
           if "t-bob" in x], "off: no collaboration push to bob")
after = {t: dbx(f"SELECT COUNT(*) FROM {t}")[0][0] for t in ("list_members", "comments", "list_status")}
check(all(after[k] == before[k] + (1 if k == "comments" else 0) for k in after), f"off: memberships, comments (+ the deleted note), status history untouched: {before} {after}")
# personal lists keep working
check(Bo.post(B + "/api/tasks", json={"title": "solo", "list_id": blid}).ok, "off: own lists work normally")
ical = A.post(B + "/api/ical", json={"action": "create"}).json()
check(ical.get("url"), "off: calendar feed still available")

# ------------------------------------------------------------------ back ON: everything is there again
A.post(B + f"/api/tasks/{t_bob}/reopen")
r = A.patch(B + "/api/admin/settings", json={"collab_all": True})
check(r.ok and r.json()["collab_all"] is True, "admin switches collaboration on again")
st_b = Bo.get(B + "/api/state").json()
check(lid in [l["id"] for l in st_b["lists"]] and tid in [t["id"] for t in st_b["tasks"]], "on: member sees the shared list again")
tl = Bo.get(B + f"/api/tasks/{tid}/timeline").json()
check(len(tl["comments"]) == 1 and tl["comments"][0]["body"] == "see doc", "on: comments are back")
check([t for t in st_b["tasks"] if t["id"] == t_bob][0]["assignee_id"] == ids["bob"], "on: assignment kept")
check(A.get(B + f"/api/lists/{lid}/status").json()["items"][0]["status"] == "at_risk", "on: status history kept")
check(A.post(B + f"/api/tasks/{tid}/comments", json={"body": "back"}).ok, "on: commenting works again")
# persisted: survives a restart
A.patch(B + "/api/admin/settings", json={"collab_all": False})
subprocess.run(["docker", "restart", CT], capture_output=True)
for _ in range(60):
    try:
        if requests.get(B + "/api/health", timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(0.5)
A = sess("alice")
check(A.get(B + "/api/state").json()["collab_all"] is False, "switch persists across a restart")
A.patch(B + "/api/admin/settings", json={"collab_all": True})

# ------------------------------------------------------------------ time tracking for everyone
A = sess("alice")
Bo = sess("bob")
check(A.get(B + "/api/state").json()["time_all"] is True, "time_all on by default")
tt = A.post(B + "/api/tasks", json={"title": "timed work", "list_id": lid}).json()["id"]  # time tracking: project lists only
A.post(B + "/api/time/entries", json={"task_id": tt, "start": "2026-09-01T08:00:00Z", "end": "2026-09-01T09:00:00Z"})
r = A.post(B + "/api/time/start", json={"task_id": tt})
check(r.ok and A.get(B + "/api/state").json()["timer"], f"timer running before: {r.text[:100]}")
Bo.post(B + "/api/time/start", json={"list_id": blid})
entries_before = dbx("SELECT COUNT(*) FROM time_entries")[0][0]
check(Bo.patch(B + "/api/admin/settings", json={"time_all": False}).status_code == 403, "non-admin cannot switch time tracking off")
r = A.patch(B + "/api/admin/settings", json={"time_all": False})
check(r.ok and r.json()["time_all"] is False, "admin switches time tracking off")
check(dbx("SELECT COUNT(*) FROM time_entries WHERE end IS NULL")[0][0] == 0, "off: running timers (both users) stopped at that moment")
check(dbx("SELECT COUNT(*) FROM time_entries")[0][0] == entries_before, "off: entries kept")
st = A.get(B + "/api/state").json()
check(st["time_all"] is False and st["timer"] is None and st["time_totals"] == {}, "off: state without timer / totals")
for what, r in {"start": A.post(B + "/api/time/start", json={"task_id": tt}), "stop": A.post(B + "/api/time/stop", json={}),
                "create": A.post(B + "/api/time/entries", json={"task_id": tt, "start": "2026-09-02T08:00:00Z", "end": "2026-09-02T09:00:00Z"}),
                "list": A.get(B + f"/api/time/entries?task_id={tt}"), "report": A.get(B + "/api/time/report"),
                "csv": A.get(B + "/api/time/export.csv"),
                "update": A.patch(B + f"/api/time/entries/{dbx('SELECT MIN(id) FROM time_entries')[0][0]}", json={"note": "x"}),
                "delete": A.delete(B + f"/api/time/entries/{dbx('SELECT MIN(id) FROM time_entries')[0][0]}")}.items():
    check(r.status_code == 403 and "Time tracking is turned off" in r.text, f"time off: {what} refused ({r.status_code})")
check(A.get(B + "/api/stats").json().get("time") is None, "time off: no tracked time in the statistics")
# focus session on a task does not become a time entry
p = A.post(B + "/api/pomo/start", json={"kind": "stopwatch", "task_id": tt}).json()
pid = (p.get("pomo") or p).get("id")
dbx("UPDATE pomos SET start=? WHERE id=?", ("2026-09-01T10:00:00Z", pid))
A.post(B + f"/api/pomo/{pid}/stop")
check(dbx("SELECT COUNT(*) FROM time_entries")[0][0] == entries_before, "time off: focus session is not tracked")
# the watchdog leaves forgotten timers alone (none may run anyway) -> a stale open entry stays untouched
dbx("INSERT INTO time_entries(user_id,task_id,list_id,start,created_at,updated_at,source) VALUES(?,?,?,?,?,?,'timer')",
    (1, tt, None, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
time.sleep(2.5)
check(dbx("SELECT end FROM time_entries WHERE start='2026-01-01T00:00:00Z'")[0][0] is None, "time off: no auto-stop / timer pushes")
dbx("DELETE FROM time_entries WHERE start='2026-01-01T00:00:00Z'")
r = A.patch(B + "/api/admin/settings", json={"time_all": True})
check(r.ok and A.get(B + "/api/state").json()["time_all"] is True, "time tracking on again")
check(len(A.get(B + f"/api/time/entries?task_id={tt}").json().get("entries", [])) >= 2, "on: entries are back")

# ------------------------------------------------------------------ first-run step 2 API (admin only)
check(Bo.post(B + "/api/admin/setup", json={"modules": []}).status_code == 403, "setup choices: admin only")
check(A.post(B + "/api/admin/setup", json={"modules": "cal"}).status_code == 400, "setup choices: modules must be a list")
check(A.post(B + "/api/admin/setup", json={"modules": [], "lang": "xx"}).status_code == 400, "setup choices: unknown language refused")
r = A.post(B + "/api/admin/setup", json={"modules": ["cal", "kanban"], "collab_all": True, "time_all": False, "lang": "en"})
st = A.get(B + "/api/state").json()
check(r.ok and st["time_all"] is False and st["settings"]["features"] == "cal,kanban,collab,time", f"setup choices applied: {st['settings']['features']}")
nu = A.post(B + "/api/users", json={"username": "dora", "password": "password123"}).json()
check(sess("dora").get(B + "/api/state").json()["settings"]["features"] == "cal,kanban,collab,time,agents", "new users get the default modules (2.22.0 #739: + agents)")
A.post(B + "/api/admin/setup", json={"modules": list("x"), "collab_all": True, "time_all": True})
# "Turn on collaboration now?" also switches the personal switches on
A.patch(B + "/api/settings", json={"features": "cal"})
A.patch(B + "/api/admin/settings", json={"collab_all": False})
A.patch(B + "/api/admin/settings", json={"collab_all": True, "collab_personal_on": True})
check("collab" in A.get(B + "/api/state").json()["settings"]["features"].split(","), "collab_personal_on: personal switch on again")
A.patch(B + "/api/settings", json={"features": "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields"})  # for v1_ui.js

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
