#!/usr/bin/env python3
"""2.111.0 API tests, part C (#2057): a reminder at a fixed time (tasks.remind_at), own container (start.sh). Invented people
and texts only (example.com).
freelancer-matrix: tasks
 - remind_at "YYYY-MM-DDTHH:MM" (local) on create and change, also without a due date; null / "" clears it; anything else 400
 - the watchdog sends it once (push over the fake ntfy), to the assignee; a reminder missed by more than 6 hours never; the
   notification switch "Reminders" (push off) is respected
 - a recurring task: ticking it moves remind_at by the same number of days as the due date, undo puts it back; skipping
   moves it too
 - REST API v1 (a person's token): read, set, clear, 400; OpenAPI names the field
 - CalDAV: the VTODO carries an absolute VALARM (X-KALMIDO-AT), a round trip keeps remind_at, a new VTODO without a due
   date and an absolute alarm becomes remind_at
 - a person without an organisation: the same in the private space (app + own token + the push)
usage: p2111_c_api_test.py <datadir>      (P2111C_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
FEAT = "cal,comments,collab"


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def until(fn, secs=20):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.4)
    return fn()


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        rows = c.execute(q, args).fetchall() if not write else c.execute(q, args)
        if write:
            c.commit()
            return None
        return rows
    finally:
        c.close()


def ntfy():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8")]
    except OSError:
        return []


def pushes(title, topic=None):
    return [x for x in ntfy() if x.get("title") == title and (topic is None or x.get("topic") == topic)]


def app_log():
    out = subprocess.run(["docker", "logs", "--tail", "400", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True, text=True)
    text = out.stdout + out.stderr
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


def hm(dt):
    return dt.strftime("%Y-%m-%dT%H:%M")


if os.environ.get("P2111C_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Beispiel", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = sess("bob")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
for s, u, uid in ((A, "alice", ALICE), (Bo, "bob", BOB)):
    A.patch(B + f"/api/users/{uid}", json={"ntfy_topic": "t-" + u})
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "push_channel": "ntfy"})
L = A.post(B + "/api/lists", json={"name": "Office"}).json()["id"]
r = A.put(B + f"/api/lists/{L}/members", json={"user_id": BOB, "role": "edit"})
check(r.ok, f"setup: Bob joins the list {r.status_code} {r.text[:200]}")
now = datetime.now()

# ================================================================== set, validate, clear
r = A.post(B + "/api/tasks", json={"title": "Call the printer", "list_id": L, "remind_at": "2030-03-04T09:15"})
T = r.json()
check(r.ok and T.get("remind_at") == "2030-03-04T09:15" and not T.get("due"), f"remind_at without a due date {r.status_code} {r.text[:200]}")
for bad in ("2030-13-04T09:15", "2030-03-04 09:15", "tomorrow", "2030-03-04T24:00", "2030-03-04", 123, True, "2030-03-04T09:15:00"):
    r = A.patch(B + f"/api/tasks/{T['id']}", json={"remind_at": bad})
    check(r.status_code == 400, f"remind_at {bad!r}: 400 ({r.status_code})")
check(sql("SELECT remind_at FROM tasks WHERE id=?", (T["id"],))[0][0] == "2030-03-04T09:15", "a refused value changes nothing")
r = A.patch(B + f"/api/tasks/{T['id']}", json={"remind_at": "2030-03-05T07:00", "due": "2030-03-06"})
check(r.ok and r.json().get("remind_at") == "2030-03-05T07:00" and r.json().get("due") == "2030-03-06", "changed together with a due date")
r = A.patch(B + f"/api/tasks/{T['id']}", json={"due": None})
check(r.ok and r.json().get("remind_at") == "2030-03-05T07:00", "removing the due date keeps the fixed reminder")
r = A.patch(B + f"/api/tasks/{T['id']}", json={"remind_at": ""})
check(r.ok and r.json().get("remind_at") is None, "'' clears it")
A.patch(B + f"/api/tasks/{T['id']}", json={"remind_at": "2030-03-05T07:00"})
r = A.patch(B + f"/api/tasks/{T['id']}", json={"remind_at": None})
check(r.ok and r.json().get("remind_at") is None, "null clears it")
st = A.get(B + "/api/state").json()
check(any(x["id"] == T["id"] and "remind_at" in x for x in st["tasks"]), "the app's state carries remind_at")
check(Bo.patch(B + f"/api/tasks/{T['id']}", json={"remind_at": "2030-03-05T08:00"}).ok, "a member who may edit sets it")

# ================================================================== the watchdog: once, to the assignee
due_at = now - timedelta(minutes=1)
r = A.post(B + "/api/tasks", json={"title": "Send the offer 2111", "list_id": L, "assignee_id": BOB, "remind_at": hm(due_at)})
check(r.ok, f"setup {r.text[:200]}")
W = r.json()["id"]
check(until(lambda: pushes("Send the offer 2111", "t-bob"), 20), f"the fixed reminder reaches Bob (the assignee) {[(x.get('topic'), x.get('title')) for x in ntfy()[-5:]]}")
time.sleep(3)
check(len(pushes("Send the offer 2111")) == 1, f"only once {len(pushes('Send the offer 2111'))}")
p = (pushes("Send the offer 2111") or [{}])[0]
check("Office" in json.dumps(p), f"the message names the list (no due date) {p}")
rem = json.loads(sql("SELECT reminded FROM tasks WHERE id=?", (W,))[0][0] or "[]")
check(f"at|{hm(due_at)}" in rem, f"remembered in reminded {rem}")
# a new time arms it again
A.patch(B + f"/api/tasks/{W}", json={"remind_at": hm(datetime.now() - timedelta(minutes=2))})
check(until(lambda: len(pushes("Send the offer 2111")) == 2, 20), "a changed time fires again")
# missed by more than 6 hours: never
r = A.post(B + "/api/tasks", json={"title": "Old reminder 2111", "list_id": L, "remind_at": hm(now - timedelta(hours=7))})
time.sleep(4)
check(r.ok and not pushes("Old reminder 2111"), "missed by more than 6 h: no push")
# a done task: none
r = A.post(B + "/api/tasks", json={"title": "Done already 2111", "list_id": L, "remind_at": hm(datetime.now() + timedelta(minutes=30))})
D1 = r.json()["id"]
A.post(B + f"/api/tasks/{D1}/complete", json={})
sql("UPDATE tasks SET remind_at=? WHERE id=?", (hm(datetime.now() - timedelta(minutes=1)), D1), write=True)
time.sleep(4)
check(not pushes("Done already 2111"), "a completed task: no push")
# the switch "Reminders" (push off) is respected
r = Bo.patch(B + "/api/settings", json={"notify": {"reminder": {"push": False}}})
check(r.ok, f"setup: Bob switches reminder pushes off {r.text[:200]}")
r = A.post(B + "/api/tasks", json={"title": "Quiet one 2111", "list_id": L, "assignee_id": BOB, "remind_at": hm(datetime.now() - timedelta(minutes=1))})
time.sleep(4)
check(r.ok and not pushes("Quiet one 2111", "t-bob"), "reminders switched off: no push")
Bo.patch(B + "/api/settings", json={"notify": ""})

# ================================================================== recurring: moves along with the due date
today = date.today()
r = A.post(B + "/api/tasks", json={"title": "Water the plants", "list_id": L, "due": today.isoformat(), "repeat": "FREQ=DAILY",
                                   "remind_at": f"{today.isoformat()}T23:50"})
R = r.json()["id"]
j = A.post(B + f"/api/tasks/{R}/complete", json={}).json()
nxt = j.get("next_due")
cur = A.get(B + f"/api/tasks/{R}").json()
check(nxt == (today + timedelta(days=1)).isoformat() and cur.get("remind_at") == f"{nxt}T23:50", f"ticked: remind_at moves to the next day {nxt} {cur.get('remind_at')}")
copy = sql("SELECT remind_at, status FROM tasks WHERE title='Water the plants' AND status=2")
check(copy and copy[0][0] == f"{today.isoformat()}T23:50", "the completed copy keeps the old time (never fires: done)")
u = A.post(B + f"/api/tasks/{R}/undo", json=j.get("undo") or {})
cur = A.get(B + f"/api/tasks/{R}").json()
check(u.ok and cur.get("due") == today.isoformat() and cur.get("remind_at") == f"{today.isoformat()}T23:50", f"undo puts it back {u.status_code} {cur.get('remind_at')}")
r = A.post(B + f"/api/tasks/{R}/skip", json={})
cur = A.get(B + f"/api/tasks/{R}").json()
check(r.ok and cur.get("remind_at") == f"{(today + timedelta(days=1)).isoformat()}T23:50", f"skip moves it too {cur.get('remind_at')}")

# ================================================================== REST API v1 (a person's token)
tok = A.post(B + "/api/me/tokens", json={"name": "script", "scopes": ["read", "write"]}).json().get("token")
pt = bearer(tok)
r = pt.post(B + "/api/v1/tasks", json={"title": "API reminder", "list_id": L, "remind_at": "2031-01-02T08:30"})
check(r.status_code in (200, 201) and r.json().get("remind_at") == "2031-01-02T08:30", f"v1: create with remind_at {r.status_code} {r.text[:200]}")
V = r.json().get("id")
check(pt.get(B + f"/api/v1/tasks/{V}").json().get("remind_at") == "2031-01-02T08:30", "v1: read")
r = pt.patch(B + f"/api/v1/tasks/{V}", json={"remind_at": "bad"})
check(r.status_code == 400, f"v1: 400 for a bad value {r.status_code}")
r = pt.patch(B + f"/api/v1/tasks/{V}", json={"remind_at": None})
check(r.ok and r.json().get("remind_at") is None, f"v1: null clears {r.text[:200]}")
spec = requests.get(B + "/api/v1/openapi.json").json()
check("remind_at" in json.dumps(spec), "OpenAPI names remind_at")

# ================================================================== CalDAV: an absolute alarm
r = A.post(B + "/api/tasks", json={"title": "Dav reminder", "list_id": L, "due": "2031-05-06", "remind_at": "2031-05-05T18:00"})
DV = r.json()["id"]
r = A.post(B + "/api/me/app-passwords", json={"name": "phone"})
Dv = requests.Session()
Dv.auth = ("alice", r.json().get("password", ""))
QRY = ('<?xml version="1.0"?><C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/>'
       '<C:calendar-data/></D:prop><C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VTODO"/></C:comp-filter></C:filter>'
       '</C:calendar-query>')
r = Dv.request("REPORT", B + f"/dav/calendars/alice/{L}/", data=QRY.encode(), headers={"Depth": "1", "Content-Type": "application/xml"})
body = r.text.replace("\r\n ", "")
mine = [b for b in body.split("BEGIN:VTODO")[1:] if "SUMMARY:Dav reminder" in b]
check(r.status_code == 207 and mine and "X-KALMIDO-AT:1" in mine[0] and re.search(r"TRIGGER;VALUE=DATE-TIME:20310505T\d{4}00Z", mine[0]),
      f"CalDAV: the VTODO has the absolute alarm {r.status_code} {(mine or [body[:600]])[0][:600]}")
href = [h for h in re.findall(r"<[a-zA-Z:]*href>([^<]*\.ics)</", r.text) if f"-{DV}-" in h]
if href:
    gr = Dv.get(B + href[0])
    pr = Dv.put(B + href[0], data=gr.text.replace("SUMMARY:Dav reminder", "SUMMARY:Dav reminder 2").encode(),
                headers={"Content-Type": "text/calendar", "If-Match": gr.headers.get("ETag", "*")})
    row = sql("SELECT title, remind_at, reminders FROM tasks WHERE id=?", (DV,))[0]
    check(pr.status_code in (200, 201, 204) and row[0] == "Dav reminder 2" and row[1] == "2031-05-05T18:00" and not row[2],
          f"CalDAV round trip: remind_at stays, no offset made of it {pr.status_code} {tuple(row)}")
else:
    check(False, "CalDAV: the task's href " + r.text[:300])
new = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:new-2111c\r\nSUMMARY:from the phone 2111\r\nBEGIN:VALARM\r\n"
       "ACTION:DISPLAY\r\nDESCRIPTION:x\r\nTRIGGER;VALUE=DATE-TIME:20310707T070000Z\r\nEND:VALARM\r\nEND:VTODO\r\nEND:VCALENDAR\r\n")
pr = Dv.put(B + f"/dav/calendars/alice/{L}/new-2111c.ics", data=new.encode(), headers={"Content-Type": "text/calendar"})
row = sql("SELECT remind_at, due FROM tasks WHERE title='from the phone 2111'")
check(pr.status_code in (201, 204) and row and row[0][0] and row[0][0].startswith("2031-07-0") and not row[0][1],
      f"CalDAV: a new VTODO without a due date and an absolute alarm -> remind_at {pr.status_code} {row}")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A)
A.patch(B + f"/api/users/{FID}", json={"ntfy_topic": "t-frida"})
Fr.patch(B + "/api/settings", json={"push_channel": "ntfy"})
FL = Fr.post(B + "/api/lists", json={"name": "Studio", "org_id": None}).json()["id"]
r = Fr.post(B + "/api/tasks", json={"title": "Invoice the client 2111", "list_id": FL, "remind_at": hm(datetime.now() - timedelta(minutes=1))})
check(r.ok and r.json().get("remind_at"), f"freelancer: remind_at in the private space {r.text[:200]}")
check(until(lambda: pushes("Invoice the client 2111", "t-frida"), 20), "freelancer: the fixed reminder arrives")
ftok = Fr.post(B + "/api/me/tokens", json={"name": "own", "scopes": ["read", "write"]}).json().get("token")
fr = bearer(ftok)
r = fr.post(B + "/api/v1/tasks", json={"title": "Freelancer API 2111", "list_id": FL, "remind_at": "2031-02-03T10:00"})
check(r.status_code in (200, 201) and r.json().get("remind_at") == "2031-02-03T10:00", f"freelancer: v1 with remind_at {r.status_code} {r.text[:200]}")
check(fr.patch(B + f"/api/v1/tasks/{T['id']}", json={"remind_at": "2031-02-03T10:00"}).status_code in (403, 404), "freelancer: not on someone else's task")
check(Fr.patch(B + f"/api/tasks/{T['id']}", json={"remind_at": "2031-02-03T10:00"}).status_code in (403, 404), "freelancer app: not on someone else's task")

if FAILS:
    app_log()
print(f"p2111_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
