#!/usr/bin/env python3
"""Admin alerts via ntfy (1.1.4): settings API (admins only, validation), test alert, every alert kind with its
recipients (enabled admins only, each in their language), no private content (task titles, comments, unknown
login names), cooldown per identical key, hourly cap, daily summary mode, kind toggles, the recent list + clear,
disk space with a fake threshold, the integrity check (a NOT NULL violation planted in the database), and the env
overrides KALMIDO_ADMIN_ALERTS=0 / KALMIDO_ADMIN_TOPIC (with the refused ntfy share inbox and an unreachable Paperless).
Starts its OWN test containers (start.sh, KALMIDO_ADMIN_ALERTS=1, 3 s aggregation window) with the stub ntfy, a fake
push service (stub_webpush.py) and a fake GitHub release API inside.
usage: admin_alerts_test.py <datadir>"""
import base64
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
STUB = "http://127.0.0.1:9997"
TZ = ZoneInfo("Europe/Berlin")
FAILS, OKS = [], [0]
SECRET = "SECRET-TITLE-7f3a"  # must never show up in an admin alert
FAKE_RELEASE = '''import http.server, json
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = json.dumps({"tag_name": "v9.9.9", "html_url": "https://github.com/example/kalmido/releases/tag/v9.9.9"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", 9995), H).serve_forever()
'''


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


def ntfy_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def clear():
    try:
        os.remove(os.path.join(DATA, "ntfy.log"))
    except FileNotFoundError:
        pass


def admin_msgs(topic=None):
    """Admin alerts in the stub log (title 'Kalmido admin: ...' / 'Kalmido Admin: ...' / the test alert)."""
    return [x for x in ntfy_log() if x["title"].lower().startswith(("kalmido admin", "kalmido test alert", "kalmido-testwarnung"))
            and (topic is None or x["topic"] == topic)]


def wait_for(fn, n=1, t=10.0):
    t0 = time.time()
    while time.time() - t0 < t:
        x = fn()
        if len(x) >= n:
            time.sleep(0.4)
            return fn()
        time.sleep(0.2)
    return fn()


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def start(keep=False, extra=(), alerts="1"):
    env = dict(os.environ, KALMIDO_ADMIN_ALERTS=alerts,
               EXTRA=" ".join(["-e KALMIDO_WEBPUSH_HOSTS=" + STUB, "-e KALMIDO_ADMIN_ALERT_WINDOW=3", *extra]))
    if keep:
        env["KEEP"] = "1"
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["cp", os.path.join(N, "stub_webpush.py"), DATA])
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_webpush.py"])
    with open(os.path.join(DATA, "fake_release.py"), "w") as f:
        f.write(FAKE_RELEASE)
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_release.py"])
    time.sleep(0.8)


def alerts(s=None):
    return (s or A).get(B + "/api/admin/alerts").json()


def patch(body, s=None):
    return (s or A).patch(B + "/api/admin/alerts", json=body)


def switch(key, on):
    r = A.patch(B + "/api/admin/settings", json={key: on})
    assert r.ok, r.text


def no_private(msgs, what):
    blob = json.dumps(msgs, ensure_ascii=False)
    check(SECRET not in blob and "hunter2-typo" not in blob and "comment-body-9b" not in blob,
          f"{what}: no task title / comment / unknown login name in admin alerts")


# ------------------------------------------------------------------ container 1: alerts on, update check against a fake API
start(extra=["-e KALMIDO_UPDATE_CHECK=1", "-e KALMIDO_UPDATE_URL=http://127.0.0.1:9995/repos/x/releases/latest"])
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "ntfy_topic": "t-bob"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")

# ---- access control: admins only
check(requests.get(B + "/api/admin/alerts").status_code == 401, "not logged in -> 401")
check(Bo.get(B + "/api/admin/alerts").status_code == 403, "user: GET -> 403")
check(patch({"on": False}, Bo).status_code == 403, "user: PATCH -> 403")
check(Bo.post(B + "/api/admin/alerts/test").status_code == 403, "user: test -> 403")
check(Bo.delete(B + "/api/admin/alerts").status_code == 403, "user: clear -> 403")
check(requests.patch(B + "/api/admin/alerts", json={"on": False}, cookies=A.cookies).status_code == 403, "PATCH without the CSRF header -> 403")

# ---- defaults
j = alerts()
check(j["env"] is True and j["on"] is True and j["topic"] == "" and j["prio"] == "4" and j["mode"] == "instant",
      f"defaults: on, own topics, prio 4, instant: {[j.get(k) for k in ('env', 'on', 'topic', 'prio', 'mode')]}")
check(j["kinds"] == ["update", "webpush", "watchdog", "integration", "security", "storage"], f"every kind on by default: {j['kinds']}")
check((j["cooldown_h"], j["max_hour"], j["disk_pct"], j["disk_mb"], j["integ_min"]) == (6, 10, 5, 1024, 15), "default limits")
check([{k: a[k] for k in ("username", "topic", "devices")} for a in j["admins"]] == [{"username": "alice", "topic": "t-alice", "devices": 0}],
      f"recipients: the admins with their topics (2.5.2: + devices): {j['admins']}")

# ---- validation
for bad in ({"topic": "bad topic!"}, {"prio": "7"}, {"kinds": ["update", "nope"]}, {"kinds": "update"}, {"mode": "weekly"},
            {"digest_time": "25:00"}, {"cooldown_h": 999}, {"max_hour": 0}, {"disk_pct": 100}, {"disk_mb": -1},
            {"integ_min": "x"}, {"on": "yes"}, {"cooldown_h": True}):
    check(patch(bad).status_code == 400, f"invalid setting rejected: {bad}")
check(alerts()["kinds"] == j["kinds"] and alerts()["prio"] == "4", "nothing stored after invalid input")
r = patch({"max_hour": 100})  # the suite sends many alerts; the cap is tested on its own below
check(r.ok and r.json()["max_hour"] == 100, "max_hour saved")

# ---- update available (fake GitHub API: v9.9.9), once per new version
clear()
switch("update_check", False)
switch("update_check", True)  # forces a check now
m = wait_for(lambda: [x for x in admin_msgs("t-alice") if "Update available" in x["title"]])
check(len(m) == 1 and "9.9.9 is available" in m[0]["msg"] and m[0]["click"].endswith("/releases/tag/v9.9.9"),
      f"update alert with the release link: {m}")
check(any("Check daily for a new version" in x["msg"] and " off" in x["msg"] for x in admin_msgs("t-alice")),
      "switching the update check is a security alert too")
switch("update_check", False)
switch("update_check", True)
time.sleep(2.5)
check(len([x for x in admin_msgs("t-alice") if "Update available" in x["title"]]) == 1, "no second update alert for the same version")

# ---- test alert
clear()
r = A.post(B + "/api/admin/alerts/test")
check(r.ok and r.json()["ok"] is True, f"test alert: {r.text[:100]}")
m = admin_msgs()
check(len(m) == 1 and m[0]["topic"] == "t-alice" and m[0]["title"] == "Kalmido test alert" and m[0]["prio"] == "4",
      f"test alert: labelled, to the admin's topic, prio 4: {m}")
check("alice" in m[0]["msg"] if m else False, "test alert names who sent it")
check(alerts()["items"][0]["kind"] == "test" and alerts()["items"][0]["delivered"] is True, "test alert listed as delivered")

# ---- instance switches + a new admin (security), recipients = admins only, admin language
clear()
switch("collab_all", False)
m = wait_for(lambda: admin_msgs("t-alice"))
check(len(m) == 1 and m[0]["title"] == "Kalmido admin: Security events" and "alice" in m[0]["msg"]
      and "Collaboration for everyone" in m[0]["msg"] and "off" in m[0]["msg"], f"switch change alert: {m}")
switch("collab_all", True)
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123", "ntfy_topic": "t-carol",
                                    "is_admin": True})
assert r.ok, r.text
Ca = sess("carol")
Ca.patch(B + "/api/settings", json={"lang": "de"})
m = wait_for(lambda: [x for x in admin_msgs("t-alice") if "carol is now an admin" in x["msg"]])
check(len(m) == 1 and "set by alice" in m[0]["msg"], f"new admin alert: {m}")
check(not admin_msgs("t-bob"), "the regular user bob never gets admin alerts")
clear()
switch("time_all", False)
switch("time_all", True)
m = wait_for(lambda: admin_msgs(), 4)
check(len(admin_msgs("t-alice")) == 2 and len(admin_msgs("t-carol")) == 2 and not admin_msgs("t-bob"),
      f"alerts go to both admins, not to bob: {[(x['topic'], x['msg']) for x in m]}")
de = admin_msgs("t-carol")
check(de and de[0]["title"] == "Kalmido Admin: Sicherheitsereignisse" and "Zeiterfassung für alle" in de[0]["msg"]
      and "aus" in de[0]["msg"], f"carol gets them in German: {de[:1]}")
r = A.patch(B + f"/api/users/{BOB}", json={"is_admin": False, "display_name": "Bob"})
check(r.ok, "editing bob without admin rights: no alert")
time.sleep(1.5)
check(not [x for x in admin_msgs() if "bob is now an admin" in x["msg"]], "no 'new admin' alert for a non-admin edit")

# ---- watchdog errors: a broken reminder row, aggregated per window, ids only, cooldown
clear()
r = A.post(B + "/api/tasks", json={"title": SECRET, "due": (datetime.now(TZ) + timedelta(days=2)).date().isoformat(),
                                   "due_time": "10:00", "reminders": "0"})
assert r.ok, r.text
TID = r.json()["id"]
A.post(B + f"/api/tasks/{TID}/comments", json={"body": "comment-body-9b"})
dbx("UPDATE tasks SET reminders='x' WHERE id=?", (TID,))
m = wait_for(lambda: [x for x in admin_msgs("t-alice") if "Watchdog" in x["title"]], t=12)
check(len(m) == 1 and f"id: {TID}" in m[0]["msg"] and "reminders" in m[0]["msg"] and "ValueError" in m[0]["msg"]
      and "1 entry" in m[0]["msg"], f"watchdog alert: count, part, error class, id: {m}")
de = [x for x in admin_msgs("t-carol") if "Watchdog" in x["title"]]
check(de and "Erinnerungen" in de[0]["msg"] and "übersprungen" in de[0]["msg"], f"watchdog alert in German: {de[:1]}")
time.sleep(5)  # the next window: same row, same error -> cooldown
check(len([x for x in admin_msgs("t-alice") if "Watchdog" in x["title"]]) == 1, "cooldown: the same broken row is reported once")
it = [x for x in alerts()["items"] if x["kind"] == "watchdog"]
check(it and it[0]["repeats"] >= 1, f"the swallowed repeats are counted: {it[:1]}")
dbx("UPDATE tasks SET reminders='' WHERE id=?", (TID,))

# ---- Web Push: a device the push service refuses (410) -> removed + fell back to ntfy
clear()
pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,
                                                                       serialization.PublicFormat.UncompressedPoint)
b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
r = A.post(B + "/api/push/subs", json={"endpoint": STUB + "/push/gone", "keys": {"p256dh": b64u(pub), "auth": b64u(os.urandom(16))},
                                       "label": "Pixel Test"})
check(r.ok, f"subscribe a device on the stub: {r.text[:100]}")
r = A.post(B + "/api/push/test")
check(r.ok, "push over the channel (the device answers 410)")
m = wait_for(lambda: [x for x in admin_msgs("t-alice") if "Web Push" in x["title"]], 2, t=12)
rem = [x for x in m if "removed" in x["msg"]]
fb = [x for x in m if "went to ntfy" in x["msg"]]
check(rem and "alice · Pixel Test (410)" in rem[0]["msg"] and rem[0]["msg"].startswith("1 device"), f"device removed alert: {rem}")
check(fb and "alice" in fb[0]["msg"] and fb[0]["msg"].startswith("1 push"), f"fallback to ntfy alert: {fb}")
check(A.get(B + "/api/push/subs").json()["subs"] == [], "the refused device is gone")

# ---- integrations: ntfy pushes failing in a row (user pushes only)
clear()
A.patch(B + f"/api/users/{BOB}", json={"ntfy_topic": "fail-bob"})
for _ in range(5):
    Bo.post(B + "/api/push/test")
m = wait_for(lambda: [x for x in admin_msgs("t-alice") if "Integration" in x["title"]])
check(m and "5 ntfy pushes in a row failed (HTTP 500)" in m[0]["msg"], f"ntfy failure streak alert: {m}")
A.patch(B + f"/api/users/{BOB}", json={"ntfy_topic": "t-bob"})
Bo.post(B + "/api/push/test")  # a working push ends the streak

# ---- security: failed logins (rate limit trip + summary), invalid /drop and calendar tokens
clear()
for _ in range(5):
    requests.post(B + "/api/auth/login", json={"username": "bob", "password": "wrong-password"}, headers=H)
requests.post(B + "/api/auth/login", json={"username": "hunter2-typo", "password": "x"}, headers=H)
for _ in range(5):
    requests.post(B + "/drop", headers={"Authorization": "Bearer nope"}, data={"text": "x"})
    requests.get(B + "/ical/1.wrongtoken.ics")
m = wait_for(lambda: [x for x in admin_msgs("t-alice") if "Security" in x["title"]], 4, t=12)
msgs = [x["msg"] for x in m]
check(any("Login rate limit reached for user bob" in x for x in msgs), f"rate limit trip for bob: {msgs}")
lg = [x for x in msgs if "failed logins" in x]
check(lg and lg[0].startswith("6 failed logins") and "bob ×5" in lg[0] and "?" in lg[0], f"failed logins summed up: {lg}")
check(any(x.startswith("5 uploads (/drop) with an invalid token") for x in msgs), f"/drop burst: {msgs}")
check(any(x.startswith("5 calendar feed requests with an invalid link") for x in msgs), f"calendar token burst: {msgs}")
requests.post(B + "/api/auth/login", json={"username": "carol", "password": "wrong"}, headers=H)
time.sleep(4.5)
check(not [x for x in admin_msgs("t-alice") if "failed login " in x["msg"]], "a single failed login stays below the burst threshold")
# cooldown: the same /drop burst again within 6 h -> not sent, counted
n0 = len(admin_msgs("t-alice"))
for _ in range(5):
    requests.post(B + "/drop", headers={"Authorization": "Bearer nope"}, data={"text": "x"})
time.sleep(4.5)
check(len(admin_msgs("t-alice")) == n0, "cooldown: an identical /drop burst is not sent again")
it = [x for x in alerts()["items"] if "/drop" in x["message"]]
check(it and it[0]["repeats"] == 1, f"... but counted on the listed alert: {it[:1]}")

# ---- storage: disk space with a fake threshold (99 % free needed)
clear()
check(patch({"disk_pct": 99}).ok, "fake disk threshold saved")
m = wait_for(lambda: [x for x in admin_msgs("t-alice") if "Storage" in x["title"]])
check(m and "Low disk space on the data volume" in m[0]["msg"], f"low disk alert: {m}")
st = alerts()["storage"]
check(st.get("total", 0) > 0 and 0 <= st.get("pct", -1) <= 100 and st.get("att_ok") is True, f"storage status for the settings: {st}")
patch({"disk_pct": 5, "disk_mb": 0})

# ---- kind toggles
clear()
check(patch({"kinds": ["update", "webpush", "watchdog", "integration", "storage"]}).ok, "security alerts off")
n0 = len(alerts()["items"])
switch("collab_all", False)
switch("collab_all", True)
time.sleep(2.5)
check(not admin_msgs() and len(alerts()["items"]) == n0, "kind off: nothing sent, nothing listed")
patch({"kinds": ["update", "webpush", "watchdog", "integration", "security", "storage"]})

# ---- hourly cap
clear()
check(patch({"max_hour": 1}).ok, "max 1 alert per hour")
switch("collab_all", False)
switch("collab_all", True)
time.sleep(2.5)
it = alerts()["items"]
check(not admin_msgs() and it[0]["state"] == "capped" and it[0]["delivered"] is False, f"over the hourly cap: listed, not sent: {it[:1]}")
r = A.post(B + "/api/admin/alerts/test")
check(r.json()["ok"] is True and len(admin_msgs()) == 2, "the test alert ignores the cap (both admins)")
patch({"max_hour": 100})

# ---- daily summary mode
clear()
now = datetime.now(TZ)
later = "23:59" if now.hour < 23 else None
if later:
    check(patch({"mode": "digest", "digest_time": later}).ok, "summary mode, later today")
    switch("collab_all", False)
    switch("collab_all", True)
    time.sleep(2.5)
    it = alerts()["items"]
    check(not admin_msgs() and [x["state"] for x in it[:2]] == ["queued", "queued"], f"summary mode: queued, not sent: {[x['state'] for x in it[:3]]}")
    check(patch({"digest_time": "00:00"}).ok, "summary time in the past -> sent on the next tick")
    m = wait_for(lambda: admin_msgs("t-alice"))
    check(len(m) == 1 and m[0]["title"] == "Kalmido admin: daily summary" and m[0]["msg"].startswith("2 alerts since the last summary")
          and "Collaboration for everyone" in m[0]["msg"], f"one summary with both alerts: {m}")
    de = admin_msgs("t-carol")
    check(de and de[0]["title"] == "Kalmido Admin: tägliche Zusammenfassung", f"summary in German for carol: {de[:1]}")
    check([x["state"] for x in alerts()["items"][:2]] == ["summarized", "summarized"], "rows marked as summarized")
    time.sleep(1.5)
    check(len(admin_msgs("t-alice")) == 1, "only one summary a day")
else:
    print("(summary mode test skipped: runs after 23:00)")
patch({"mode": "instant"})

# ---- turning alerts off: the last alert goes out, then nothing
clear()
check(patch({"on": False}).ok, "alerts off")
m = admin_msgs("t-alice")
check(len(m) == 1 and "Admin alerts" in m[0]["msg"] and "off" in m[0]["msg"], f"switching off is still reported: {m}")
switch("collab_all", False)
switch("collab_all", True)
time.sleep(2)
check(len(admin_msgs()) == 2, "off: no more alerts (only the off notice to both admins)")
check(A.post(B + "/api/admin/alerts/test").json()["ok"] is True, "the test alert works while switched off")
patch({"on": True})
wait_for(lambda: [x for x in admin_msgs("t-alice") if "Admin alerts" in x["msg"] and " on" in x["msg"]])

# ---- shared admin topic + priority
clear()
r = patch({"topic": "admins-shared", "prio": "5"})
check(r.ok and r.json()["topic"] == "admins-shared", "shared admin topic saved")
m = wait_for(lambda: [x for x in admin_msgs("admins-shared") if "changed the admin alert topic" in x["msg"]])
check(m and "alice" in m[0]["msg"] and m[0]["prio"] == "5", f"topic change reported, prio 5: {m}")
check(not admin_msgs("t-alice") and not admin_msgs("t-carol"), "shared topic: not to the own topics")
patch({"topic": "", "prio": "4"})

# ---- privacy over everything listed
no_private([x for x in alerts()["items"]], "recent list")

# ---- recent list + clear
it = alerts()["items"]
check(0 < len(it) <= 50 and all({"kind", "label", "message", "created_at", "sent_at", "delivered", "state", "repeats"} <= set(x) for x in it),
      f"recent list: at most 50 rows with the fields: {len(it)}")
check(it == sorted(it, key=lambda x: -x["id"]), "newest first")
r = Ca.get(B + "/api/admin/alerts").json()["items"]
check(r and r[0]["label"] in ("Sicherheitsereignisse", "Testwarnung", "Speicher und Zustand", "Integrationsprobleme"), f"list in the viewer's language: {r[:1]}")
check(A.delete(B + "/api/admin/alerts").json()["items"] == [], "clear")
check(dbx("SELECT COUNT(*) FROM admin_alerts")[0][0] == 0, "cleared in the database")

# ---- integrity check: a NOT NULL violation planted while the container is stopped -> reported after the start
subprocess.run(["docker", "stop", "-t", "3", CT], capture_output=True)
c = sqlite3.connect(os.path.join(DATA, "tasks.db"))
c.execute("CREATE TABLE zz_probe(x)")
c.execute("INSERT INTO zz_probe VALUES(NULL)")
c.commit()
c.execute("PRAGMA writable_schema=ON")
c.execute("UPDATE sqlite_master SET sql='CREATE TABLE zz_probe(x NOT NULL)' WHERE name='zz_probe'")
c.commit()
c.close()
clear()
start(keep=True)
m = wait_for(lambda: [x for x in admin_msgs("t-alice") if "integrity" in x["msg"]], t=12)
check(m and "quick_check" in m[0]["msg"] and "NULL value in zz_probe.x" in m[0]["msg"], f"integrity check alert: {m}")
check(alerts()["quick_check"].get("ok") is False, "settings show the failed check")
no_private(ntfy_log(), "whole run")
check(not [x for x in ntfy_log() if x["topic"] == "t-bob" and x["title"].lower().startswith("kalmido admin")], "bob never got an admin alert")
subprocess.run(["docker", "stop", "-t", "3", CT], capture_output=True)
c = sqlite3.connect(os.path.join(DATA, "tasks.db"))
c.execute("PRAGMA writable_schema=ON")
c.execute("UPDATE sqlite_master SET sql='CREATE TABLE zz_probe(x)' WHERE name='zz_probe'")
c.commit()
c.close()
c = sqlite3.connect(os.path.join(DATA, "tasks.db"))
c.execute("DROP TABLE zz_probe")
c.commit()
check(c.execute("PRAGMA quick_check").fetchall() == [("ok",)], "test database repaired again")
c.close()

# ------------------------------------------------------------------ container 2: KALMIDO_ADMIN_ALERTS=0
clear()
start(keep=True, alerts="0")
A = sess("alice")
j = alerts()
check(j["env"] is False, "env off shown to the settings")
check(A.post(B + "/api/admin/alerts/test").status_code == 409, "test refused while turned off by env")
switch("collab_all", False)
switch("collab_all", True)
time.sleep(2)
check(not admin_msgs(), "env off: no alerts at all")

# ------------------------------------------------------------------ container 3: KALMIDO_ADMIN_TOPIC, refused inbox, Paperless down
clear()
start(keep=True, extra=["-e KALMIDO_ADMIN_TOPIC=env-admins", "-e NTFY_INBOX_TOKEN=tk", "-e NTFY_INBOX_URL=https://ntfy.sh",
                        "-e NTFY_INBOX_TOPIC=inbox", "-e PAPERLESS_TOKEN=pl", "-e PAPERLESS_API=http://127.0.0.1:9"])
A = sess("alice")
j = alerts()
check(j["topic_env"] is True and j["topic"] == "env-admins", f"env topic shown (fixed): {j['topic']}")
m = wait_for(lambda: admin_msgs("env-admins"))
check(m and "share inbox was not started" in m[0]["msg"], f"refused share inbox reported to the env topic: {m}")
check(not admin_msgs("t-alice") and not admin_msgs("t-carol"), "env topic: nothing to the own topics")
r = A.post(B + "/api/admin/alerts/test")
check(r.ok and r.json()["ok"] and admin_msgs("env-admins")[-1]["title"] == "Kalmido test alert", "test alert to the env topic (first admin's language)")
check(patch({"integ_min": 1}).ok, "Paperless: 1 minute")
m = wait_for(lambda: [x for x in admin_msgs("env-admins") if "Paperless" in x["msg"]], t=80)
check(m and "Paperless has been failing for 1 min" in m[0]["msg"] and "URLError" in m[0]["msg"], f"Paperless outage reported: {m}")
no_private(ntfy_log(), "env run")

print(f"admin alerts: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
