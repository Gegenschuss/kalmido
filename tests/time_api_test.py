#!/usr/bin/env python3
"""Time tracking API tests (fresh DB on the TEST container :3048). Timer lifecycle (cross-device, offline
replays), focus -> entries without double counting, manual CRUD + permissions / IDOR, report totals on a
seeded dataset (week / month boundaries, DST, entries crossing midnight), rounding, amounts, CSV, triggers,
watchdog reminder / auto-stop, export, user delete, module off."""
import csv, io, json, os, sqlite3, sys, time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests

B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
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


def pushes():
    try:
        return [json.loads(l) for l in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        return []


def utc(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def loc(s):  # "2026-09-21 09:00" local -> aware
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


def ver(s):
    return s.get(B + "/api/version").json()["v"]


assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/users/1", json={"ntfy_topic": "t-alice"})
ids = {}
for u, n in (("bob", "Bob"), ("carol", "Carol")):
    ids[u] = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "ntfy_topic": "t-" + u}).json()["id"]
Bb, C = sess("bob"), sess("carol")
Bb.patch(B + "/api/settings", json={"lang": "de"})
st = A.get(B + "/api/state").json()
check(st["timer"] is None and st["time_totals"] == {}, "state: no timer, no totals")
check("time" in st["settings"]["features"].split(",") and st["settings"]["features_rev"] == "10", "new user: module time on, features_rev 10 (2.21.0)")
check(st["settings"]["time_rounding"] == "0" and st["settings"]["time_focus"] == "1", "time settings defaults")
WORK = A.post(B + "/api/lists", json={"name": "Work", "kind": "project"}).json()["id"]
HOME = A.post(B + "/api/lists", json={"name": "Home", "kind": "project"}).json()["id"]
SH = Bb.post(B + "/api/lists", json={"name": "Shared", "kind": "project"}).json()["id"]
Bb.put(B + f"/api/lists/{SH}/members", json={"user_id": 1, "role": "edit"})
VW = Bb.post(B + "/api/lists", json={"name": "Viewonly", "kind": "project"}).json()["id"]
Bb.put(B + f"/api/lists/{VW}/members", json={"user_id": 1, "role": "view"})
PRIV = Bb.post(B + "/api/lists", json={"name": "Bob private", "kind": "project"}).json()["id"]


def mk(s, **kw):
    r = s.post(B + "/api/tasks", json=kw)
    assert r.ok, r.text
    return r.json()["id"]


T1 = mk(A, title="Write report", list_id=WORK)
T2 = mk(A, title="Review", list_id=WORK)
TH = mk(A, title="Garden", list_id=HOME)
TS = mk(Bb, title="Shared job", list_id=SH)
TV = mk(Bb, title="Look only", list_id=VW)
TP = mk(Bb, title="Secret", list_id=PRIV)

# ================= timer lifecycle
v0 = ver(A)
r = A.post(B + "/api/time/start", json={"task_id": T1, "client_id": "c1"}).json()
check(r["timer"]["task_id"] == T1 and r["timer"]["running"] and r["stopped"] is None, "start: timer running on T1")
check(ver(A) > v0, "start bumps the version (other devices reload)")
A2 = sess("alice")  # second device
check(A2.get(B + "/api/state").json()["timer"]["id"] == r["timer"]["id"], "second device sees the running timer")
r2 = A.post(B + "/api/time/start", json={"task_id": T1, "client_id": "c1"}).json()
check(r2["entry"]["id"] == r["entry"]["id"], "same client_id twice (replay): no second entry")
with db() as c:
    c.execute("UPDATE time_entries SET start=? WHERE id=?", (utc(datetime.now(timezone.utc) - timedelta(minutes=10)).replace("Z", "+00:00"), r["entry"]["id"]))
r3 = A2.post(B + "/api/time/start", json={"task_id": T2, "client_id": "c2"}).json()
check(r3["stopped"] and r3["stopped"]["id"] == r["entry"]["id"] and 595 <= r3["stopped"]["seconds"] <= 610, f"start on another device stops the first one ({r3['stopped']})")
check(A.get(B + "/api/state").json()["timer"]["task_id"] == T2, "device 1 now sees the timer on T2")
with db() as c:
    check(c.execute("SELECT COUNT(*) FROM time_entries WHERE user_id=1 AND end IS NULL").fetchone()[0] == 1, "one running timer per user")
    c.execute("UPDATE time_entries SET start=? WHERE id=?", (utc(datetime.now(timezone.utc) - timedelta(minutes=5)).replace("Z", "+00:00"), r3["entry"]["id"]))
r4 = A.post(B + "/api/time/stop", json={"id": r3["entry"]["id"]}).json()
check(r4["timer"] is None and 295 <= r4["entry"]["seconds"] <= 310 and not r4["entry"]["running"], "stop by id")
check(A.post(B + "/api/time/stop", json={}).json().get("already"), "stop with nothing running: no error")
tot = A.get(B + "/api/state").json()["time_totals"]
check(str(T1) in tot and 595 <= tot[str(T1)][0] <= 610 and tot[str(T1)][0] == tot[str(T1)][1], f"task totals: T1 {tot.get(str(T1))}")
# misclick: start + stop in the same second -> discarded
r = A.post(B + "/api/time/start", json={"task_id": T2}).json()
r = A.post(B + "/api/time/stop", json={"at": r["entry"]["start"]}).json()
check(r.get("discarded") and r["entry"] is None, "start + stop in the same second: discarded")

# ================= offline replays (device time "at" + client_id)
now = datetime.now(timezone.utc).replace(microsecond=0)
A.post(B + "/api/time/start", json={"task_id": T1, "client_id": "off1", "at": utc(now - timedelta(minutes=20))})
r = A.post(B + "/api/time/stop", json={"client_id": "off1", "at": utc(now - timedelta(minutes=8))}).json()
check(r["entry"]["seconds"] == 720 and r["entry"]["start"] == (now - timedelta(minutes=20)).isoformat(), "offline start/stop replayed later: device times kept (12 min)")
# device B starts online now; device A's older offline start arrives later -> ends where B's timer began
rb = A2.post(B + "/api/time/start", json={"task_id": T2, "client_id": "onB"}).json()
ra = A.post(B + "/api/time/start", json={"task_id": T1, "client_id": "offA", "at": utc(now - timedelta(minutes=30))}).json()
check(ra["entry"]["end"] is not None and ra["timer"]["id"] == rb["entry"]["id"], "older offline start: stored as finished entry, B keeps running")
rs = A.post(B + "/api/time/stop", json={"client_id": "offA", "at": utc(now - timedelta(minutes=25))}).json()
check(rs["entry"]["seconds"] == 300 and rs["timer"]["id"] == rb["entry"]["id"], "its replayed stop sets the earlier end (5 min) and leaves B running")
A.post(B + "/api/time/stop", json={"id": rb["entry"]["id"]})
# clamping
r = A.post(B + "/api/time/start", json={"task_id": T1, "client_id": "fut", "at": utc(now + timedelta(hours=3))}).json()
check(abs((datetime.fromisoformat(r["entry"]["start"]) - datetime.now(timezone.utc)).total_seconds()) < 5, "start in the future -> now")
A.post(B + "/api/time/stop", json={"id": r["entry"]["id"], "at": utc(now - timedelta(days=1))})
with db() as c:
    x = c.execute("SELECT seconds FROM time_entries WHERE client_id='fut'").fetchone()
check(x is None, "stop before the start: 0 s -> discarded")
r = A.post(B + "/api/time/start", json={"task_id": T1, "client_id": "old", "at": utc(now - timedelta(days=30))}).json()
check(abs((datetime.fromisoformat(r["entry"]["start"]) - (datetime.now(timezone.utc) - timedelta(days=7))).total_seconds()) < 5, "start 30 days back -> clamped to 7 days")
A.delete(B + f"/api/time/entries/{r['entry']['id']}")
check(A.get(B + "/api/state").json()["timer"] is None, "deleting the running timer discards it")

# ================= permissions / IDOR
check(A.post(B + "/api/time/start", json={"task_id": TP}).status_code == 404, "timer on someone else's private task: 404")
check(A.post(B + "/api/time/entries", json={"task_id": TP, "start": utc(now - timedelta(hours=2)), "minutes": 10}).status_code == 404, "manual entry on a private task: 404")
check(A.post(B + "/api/time/entries", json={"list_id": PRIV, "start": utc(now - timedelta(hours=2)), "minutes": 10}).status_code == 404, "list entry on a private list: 404")
rv = A.post(B + "/api/time/entries", json={"task_id": TV, "start": utc(now - timedelta(hours=3)), "minutes": 15, "note": "view only"})
check(rv.ok, "view-only member may track own time on the list's task")
bp = Bb.post(B + "/api/time/entries", json={"task_id": TP, "start": utc(now - timedelta(hours=2)), "minutes": 40, "note": "private"}).json()
bs = Bb.post(B + "/api/time/entries", json={"task_id": TS, "start": utc(now - timedelta(hours=4)), "minutes": 30, "note": "bob shared"}).json()
check(bs["seconds"] == 1800 and bs["source"] == "manual", "bob: manual entry by minutes")
ents = A.get(B + f"/api/time/entries?task_id={TS}").json()
check([e["id"] for e in ents["entries"]] == [bs["id"]] and not ents["entries"][0]["mine"] and ents["entries"][0]["user_name"] == "Bob", "alice sees bob's entry on the shared task (read-only)")
check(A.patch(B + f"/api/time/entries/{bs['id']}", json={"note": "hijack"}).status_code == 403, "alice cannot edit bob's entry (403)")
check(A.delete(B + f"/api/time/entries/{bs['id']}").status_code == 403, "alice cannot delete bob's entry (403)")
check(A.patch(B + f"/api/time/entries/{bp['id']}", json={"note": "x"}).status_code == 404, "bob's private entry: 404 for alice")
check(A.get(B + f"/api/time/entries?task_id={TP}").status_code == 404, "entries of a private task: 404")
check(C.get(B + f"/api/time/entries?task_id={TS}").status_code == 404, "carol (no access): 404")
check(C.delete(B + f"/api/time/entries/{bs['id']}").status_code == 404, "carol cannot delete (404, no existence leak)")
rep = A.get(B + "/api/time/report?scope=all").json()
check(all(e["id"] != bp["id"] for e in rep["entries"]) and any(e["id"] == bs["id"] for e in rep["entries"]), "report 'all': bob's shared entry yes, private no")
check(all(e["mine"] for e in A.get(B + "/api/time/report?scope=mine").json()["entries"]), "report 'mine': only own entries")
check(not any(e["id"] == bp["id"] for e in A.get(B + f"/api/time/report?scope=all&user={ids['bob']}").json()["entries"]), "filter by user cannot reach private entries")
check(str(TS) in A.get(B + "/api/state").json()["time_totals"] and str(TP) not in A.get(B + "/api/state").json()["time_totals"], "alice's task totals: shared yes, private no")
check(str(TS) not in C.get(B + "/api/state").json()["time_totals"], "carol: no totals of lists she cannot see")
tt = A.get(B + "/api/state").json()["time_totals"][str(TS)]
check(tt == [1800, 0], f"shared task total: all 1800, mine 0 ({tt})")
check(A.patch(B + f"/api/lists/{SH}", json={"rate": 50}).status_code == 403, "only the owner sets the hourly rate")
check(A.patch(B + f"/api/lists/{WORK}", json={"rate": "abc"}).status_code == 400, "rate must be a number")
A.patch(B + f"/api/lists/{WORK}", json={"rate": "80,5"})
check([l for l in A.get(B + "/api/state").json()["lists"] if l["id"] == WORK][0]["rate"] == 80.5, "rate with decimal comma stored")
# the member leaves the list: her entries stay hers (visible to her), bob still sees them in his list
ra = A.post(B + "/api/time/entries", json={"task_id": TS, "start": utc(now - timedelta(hours=5)), "minutes": 20}).json()
check(any(e["id"] == ra["id"] for e in Bb.get(B + f"/api/time/entries?task_id={TS}").json()["entries"]), "bob sees alice's entry on his shared task")

# ================= manual CRUD + validation
bad = [({"task_id": T1, "start": utc(now - timedelta(hours=1)), "end": utc(now - timedelta(hours=2))}, "end before start"),
       ({"task_id": T1, "start": utc(now - timedelta(days=9)), "end": utc(now)}, "longer than 7 days"),
       ({"task_id": T1, "start": utc(now + timedelta(days=2)), "minutes": 30}, "in the future"),
       ({"task_id": T1, "minutes": 30}, "start missing"),
       ({"task_id": T1, "start": "yesterday", "minutes": 30}, "garbage start"),
       ({"start": utc(now - timedelta(hours=1)), "minutes": 30}, "no task / list"),
       ({"task_id": T1, "start": utc(now - timedelta(hours=1))}, "no end / duration"),
       ({"task_id": T1, "start": utc(now - timedelta(hours=1)), "minutes": "x"}, "minutes not a number")]
for b, what in bad:
    check(A.post(B + "/api/time/entries", json=b).status_code == 400, "400: " + what)
m1 = A.post(B + "/api/time/entries", json={"task_id": T1, "start": "2026-09-21T09:00:00", "end": "2026-09-21T10:07:00", "note": "naive local"}).json()
check(m1["start"] == "2026-09-21T07:00:00+00:00" and m1["seconds"] == 4020, "naive time = server time zone")
m2 = A.patch(B + f"/api/time/entries/{m1['id']}", json={"minutes": 90, "note": "edited"}).json()
check(m2["seconds"] == 5400 and m2["end"] == "2026-09-21T08:30:00+00:00" and m2["note"] == "edited", "patch: minutes -> end")
m3 = A.patch(B + f"/api/time/entries/{m1['id']}", json={"start": "2026-09-21T10:00:00+02:00"}).json()
check(m3["start"] == "2026-09-21T08:00:00+00:00" and m3["seconds"] == 5400, "patch: move start keeps the duration")
m4 = A.patch(B + f"/api/time/entries/{m1['id']}", json={"task_id": T2}).json()
check(m4["task_id"] == T2 and m4["title"] == "Review", "patch: move to another task")
check(A.patch(B + f"/api/time/entries/{m1['id']}", json={"task_id": TP}).status_code == 404, "patch: moving onto a private task: 404")
check(A.patch(B + f"/api/time/entries/{m1['id']}", json={"end": "2026-09-21T07:00:00+02:00"}).status_code == 400, "patch: end before start 400")
d = A.delete(B + f"/api/time/entries/{m1['id']}").json()
check(d["ok"] and d["entry"]["seconds"] == 5400, "delete returns the old entry (undo)")
check(A.patch(B + f"/api/time/entries/{m1['id']}", json={"note": "x"}).status_code == 404, "deleted: 404")
# undo restore of a focus entry keeps the duration without pauses
rr = A.post(B + "/api/time/entries", json={"task_id": T2, "start": "2026-09-22T09:00:00+02:00", "end": "2026-09-22T10:00:00+02:00", "seconds": 3000, "source": "focus"}).json()
check(rr["seconds"] == 3000 and rr["source"] == "focus", "restore with seconds < end-start (focus pauses)")
A.delete(B + f"/api/time/entries/{rr['id']}")
# list-level entry (no task)
le = A.post(B + "/api/time/entries", json={"list_id": HOME, "start": "2026-09-22T18:00:00+02:00", "minutes": 45, "note": "general"}).json()
check(le["task_id"] is None and le["list_id"] == HOME and le["title"] == "", "list-level entry")
A.delete(B + f"/api/time/entries/{le['id']}")

# ================= triggers: task moved / renamed / purged
tx = mk(A, title="Temp task", list_id=WORK)
ex = A.post(B + "/api/time/entries", json={"task_id": tx, "start": "2026-09-23T09:00:00+02:00", "minutes": 30}).json()
A.patch(B + f"/api/tasks/{tx}", json={"list_id": HOME, "title": "Temp renamed"})
with db() as c:
    r = c.execute("SELECT list_id, task_title FROM time_entries WHERE id=?", (ex["id"],)).fetchone()
check(r["list_id"] == HOME and r["task_title"] == "Temp renamed", "trigger: entry follows the task's list and title")
A.delete(B + f"/api/tasks/{tx}")
A.delete(B + f"/api/tasks/{tx}?hard=1")
e = [x for x in A.get(B + "/api/time/report?from=2026-09-23&to=2026-09-23").json()["entries"] if x["id"] == ex["id"]]
check(e and e[0]["task_id"] is None and e[0]["title"] == "Temp renamed" and e[0]["list_id"] == HOME, "purged task: entry kept with its title and list")
A.delete(B + f"/api/time/entries/{ex['id']}")

# ================= focus sessions -> entries, no double counting
def pomo(s, kind, task, minutes_ago, pause_s=0, action="stop"):
    p = s.post(B + "/api/pomo/start", json={"kind": kind, "task_id": task, "minutes": 0 if kind == "stopwatch" else 25}).json()
    with db() as c:
        c.execute("UPDATE pomos SET start=?, paused_s=? WHERE id=?",
                  ((datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds"), pause_s, p["id"]))
    s.post(B + f"/api/pomo/{p['id']}/{action}")
    with db() as c:
        return c.execute("SELECT * FROM time_entries WHERE pomo_id=?", (p["id"],)).fetchone()


e = pomo(Bb, "stopwatch", TS, 30, pause_s=300)
check(e and e["source"] == "focus" and 1495 <= e["seconds"] <= 1505, "stopwatch on a task -> focus entry, pauses subtracted (25 min)")
e = pomo(Bb, "focus", TS, 25, action="finish")
check(e and e["source"] == "focus" and 1495 <= e["seconds"] <= 1505, "finished focus session -> entry")
check(pomo(Bb, "focus", None, 25, action="finish") is None, "focus without task: no entry")
with db() as c:
    x = c.execute("SELECT COUNT(*) FROM time_entries WHERE source='focus' AND user_id=%d" % ids["bob"] + "").fetchone()[0]
p = Bb.post(B + "/api/pomo/start", json={"kind": "stopwatch", "task_id": TS, "minutes": 0}).json()
check(pomo(Bb, "focus", TS, 0.5, action="finish") is None, "session under 1 min: no entry")
with db() as c:
    check(c.execute("SELECT COUNT(*) FROM time_entries WHERE source='focus' AND user_id=%d" % ids["bob"] + "").fetchone()[0] == x, "pomo started while another ran: the ended short one adds nothing")
# timer running at the same time -> focus session not recorded
tr_ = Bb.post(B + "/api/time/start", json={"task_id": TS}).json()
with db() as c:
    c.execute("UPDATE time_entries SET start=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat(timespec="seconds"), tr_["entry"]["id"]))
check(pomo(Bb, "stopwatch", TS, 20) is None, "focus while a timer runs: not recorded (timer wins)")
Bb.post(B + "/api/time/stop", json={})
# session overlapping a finished timer entry
with db() as c:
    lastt = c.execute("SELECT start, end FROM time_entries WHERE user_id=%d" % ids["bob"] + " AND source='timer' ORDER BY id DESC LIMIT 1").fetchone()
check(pomo(Bb, "stopwatch", TS, 45) is None, "focus overlapping a finished timer entry: not recorded")
Bb.patch(B + "/api/settings", json={"time_focus": "0"})
check(pomo(Bb, "stopwatch", TS, 10) is None, "setting 'count focus sessions' off: no entry")
Bb.patch(B + "/api/settings", json={"time_focus": "1", "features": "cal,habits,pomo,stats"})
check(pomo(Bb, "stopwatch", TS, 10) is None, "module off: no automatic entries")
check(Bb.get(B + "/api/time/report").ok and len(Bb.get(B + "/api/time/report").json()["entries"]) > 0, "module off: data kept, API still answers")
Bb.patch(B + "/api/settings", json={"features": "cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time"})
# focus on someone else's private task is impossible (pomo drops the task)
check(pomo(C, "stopwatch", TP, 10) is None, "focus on a private task of another user: no entry")

# ================= report totals on a seeded dataset (carol, fresh)
CL = C.post(B + "/api/lists", json={"name": "Client A", "kind": "project"}).json()["id"]
CL2 = C.post(B + "/api/lists", json={"name": "Client B", "kind": "project"}).json()["id"]
C.patch(B + f"/api/lists/{CL}", json={"rate": 100})
ca = mk(C, title="Design", list_id=CL)
cb = mk(C, title="Build", list_id=CL)
cc = mk(C, title="Support", list_id=CL2)
seed = [  # (task, start, end) with explicit offsets
    (ca, "2026-09-14T09:00:00+02:00", "2026-09-14T09:07:00+02:00"),   # Mon, 7 min -> 15
    (ca, "2026-09-15T10:00:00+02:00", "2026-09-15T11:01:00+02:00"),   # 61 min -> 75
    (cb, "2026-09-16T14:00:00+02:00", "2026-09-16T15:00:00+02:00"),   # 60 -> 60
    (cc, "2026-09-20T23:30:00+02:00", "2026-09-21T00:30:00+02:00"),   # Sun -> Mon across midnight: counts Sunday (week 38)
    (cc, "2026-09-21T00:00:00+02:00", "2026-09-21T00:10:00+02:00"),   # Monday 00:00 belongs to week 39
    (ca, "2026-08-31T23:00:00+02:00", "2026-09-01T01:00:00+02:00"),   # month boundary: August
    (cb, "2026-03-29T01:30:00+01:00", "2026-03-29T03:30:00+02:00"),   # DST start: 1 h real
    (cb, "2025-10-26T01:30:00+02:00", "2025-10-26T03:30:00+01:00"),   # DST end: 3 h real
    (cb, "2026-03-30T00:15:00+02:00", "2026-03-30T00:45:00+02:00"),   # Monday after DST week
]
for t, s0, e0 in seed:
    r = C.post(B + "/api/time/entries", json={"task_id": t, "start": s0, "end": e0})
    assert r.ok, r.text
C.patch(B + "/api/settings", json={"time_rounding": "15"})
w38 = C.get(B + "/api/time/report?from=2026-09-14&to=2026-09-20").json()
check(w38["total"]["seconds"] == (7 + 61 + 60 + 60) * 60, f"week 38 raw total {w38['total']['seconds']}")
check(w38["total"]["rounded"] == (15 + 75 + 60 + 60) * 60, f"week 38 rounded total {w38['total']['rounded']}")
check(w38["total"]["count"] == 4, "week 38: 4 entries (midnight entry counted on Sunday)")
days = {d["date"]: d["seconds"] for d in w38["days"]}
check(days == {"2026-09-14": 420, "2026-09-15": 3660, "2026-09-16": 3600, "2026-09-20": 3600}, f"per day {days}")
la = [l for l in w38["lists"] if l["id"] == CL][0]
check(la["rounded"] == (15 + 75 + 60) * 60 and la["amount"] == 250.0 and la["rate"] == 100, f"list A rounded 2.5 h x 100 = 250 ({la['amount']})")
check([t["title"] for t in la["tasks"]] == ["Design", "Build"] and la["tasks"][0]["rounded"] == 90 * 60 and la["tasks"][0]["amount"] == 150.0, "tasks sorted by time, per-task amount")
check(w38["total"]["amount"] == 250.0, "grand amount (list B has no rate)")
check(w38["users"] == [{"id": ids["carol"], "name": "Carol", "seconds": 188 * 60, "rounded": 210 * 60}], "per user")
w39 = C.get(B + "/api/time/report?from=2026-09-21&to=2026-09-27").json()
check(w39["total"]["seconds"] == 600 and w39["total"]["count"] == 1, "week 39: only the Monday 00:00 entry")
aug = C.get(B + "/api/time/report?from=2026-08-01&to=2026-08-31").json()
sep = C.get(B + "/api/time/report?from=2026-09-01&to=2026-09-30").json()
check(aug["total"]["seconds"] == 7200 and aug["days"][0]["date"] == "2026-08-31", "entry across the month end counts in August")
check(sep["total"]["count"] == 5, "September: 5 entries")
dst = C.get(B + "/api/time/report?from=2026-03-23&to=2026-03-29").json()
check(dst["total"]["seconds"] == 3600 and dst["total"]["count"] == 1, "DST start week: 1 h real, Monday after excluded")
dst2 = C.get(B + "/api/time/report?from=2025-10-26&to=2025-10-26").json()
check(dst2["total"]["seconds"] == 3 * 3600, "DST end day: 3 h real")
check(C.get(B + "/api/time/report?from=2026-09-20&to=2026-09-14").json()["total"]["count"] == 4, "reversed range is swapped")
f1 = C.get(B + f"/api/time/report?from=2026-09-14&to=2026-09-20&lists={CL2}").json()
check(f1["total"]["seconds"] == 3600 and [l["id"] for l in f1["lists"]] == [CL2], "list filter")
check(C.get(B + "/api/time/report?from=2026-09-14&to=2026-09-20&lists=0").json()["total"]["count"] == 0, "list filter 'no list': none")
C.patch(B + "/api/settings", json={"time_rounding": "0"})
check(C.get(B + "/api/time/report?from=2026-09-14&to=2026-09-20").json()["total"]["rounded"] == 188 * 60, "rounding off: rounded = raw")
C.patch(B + "/api/settings", json={"time_rounding": "15"})
st_all = C.get(B + "/api/stats").json()
st_c = st_all["time"]
# the stats window depends on today: expectations from the server's own window (weeks[0] .. today, the day an entry
# starts on in Berlin time), so the check holds on any day (it failed on the Monday after the seeded week before)
mon0, t_day = date.fromisoformat(st_all["weeks"][0]), date.fromisoformat(st_all["today"])
exp_week, exp_list = [0] * len(st_c["per_week"]), {}
for t, s0, e0 in seed:
    d0 = datetime.fromisoformat(s0).astimezone(TZ).date()
    if mon0 <= d0 <= t_day:
        sec = (datetime.fromisoformat(e0) - datetime.fromisoformat(s0)).total_seconds()
        exp_week[(d0 - mon0).days // 7] += sec
        name = "Client B" if t == cc else "Client A"
        exp_list[name] = exp_list.get(name, 0) + sec
check(st_c["total"] == round(sum(exp_week) / 60) and st_c["per_week"] == [round(v / 60) for v in exp_week]
      and st_c["this_week"] == round(exp_week[-1] / 60), f"stats: tracked minutes {st_c['total']} {st_c['per_week'][-3:]} (expected {round(sum(exp_week) / 60)})")
check([x["name"] for x in st_c["by_list"]] == [k for k, v in sorted(exp_list.items(), key=lambda kv: -kv[1]) if round(v / 60)], "stats: by list")

# ================= CSV
C.post(B + "/api/time/entries", json={"task_id": ca, "start": "2026-09-17T09:00:00+02:00", "minutes": 30, "note": 'Say "hi"; then=\nnext line'})
C.post(B + "/api/time/entries", json={"task_id": ca, "start": "2026-09-17T11:00:00+02:00", "minutes": 5, "note": "=HYPERLINK(\"x\")"})
r = C.get(B + "/api/time/export.csv?from=2026-09-14&to=2026-09-20")
check(r.headers["content-type"].startswith("text/csv") and "charset=utf-8" in r.headers["content-type"], "CSV content type utf-8")
check(r.content.startswith(b"\xef\xbb\xbf"), "CSV starts with a UTF-8 BOM")
check('filename="timesheet-2026-09-14-2026-09-20.csv"' in r.headers.get("content-disposition", ""), "CSV file name " + r.headers.get("content-disposition", ""))
rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
check(rows[0] == ["List", "Task", "User", "Start", "End", "Duration (h)", "Duration (h:mm)", "Rounded (h)", "Amount (€)", "Note"], f"CSV header {rows[0]}")
check(len(rows) == 1 + 6, f"CSV rows {len(rows)}")
check(rows[1] == ["Client A", "Design", "Carol", "2026-09-14 09:00", "2026-09-14 09:07", "0.12", "0:07", "0.25", "25.00", ""], f"CSV row 1 {rows[1]}")
note_row = [x for x in rows if x[3] == "2026-09-17 09:00"][0]
check(note_row[9] == 'Say "hi"; then=\nnext line', "CSV: quotes, separator and newline escaped")
check([x for x in rows if x[3] == "2026-09-17 11:00"][0][9].startswith("'="), "CSV: formula injection neutralised")
check([x for x in rows if x[1] == "Support"][0][8] == "", "CSV: no amount without a rate")
C.patch(B + "/api/settings", json={"lang": "de"})
r = C.get(B + "/api/time/export.csv?from=2026-09-14&to=2026-09-20")
rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
check(rows[0][:3] == ["Liste", "Aufgabe", "Person"] and rows[0][8] == "Betrag (€)", f"German CSV header {rows[0]}")
check(rows[1][5:9] == ["0,12", "0:07", "0,25", "25,00"], f"German CSV: decimal comma {rows[1][5:9]}")
check('filename="stundennachweis-2026-09-14-2026-09-20.csv"' in r.headers["content-disposition"], "German file name")
C.patch(B + "/api/settings", json={"lang": "en"})

# ================= export JSON, user delete
ex = C.get(B + "/api/export.json").json()
check(len(ex["time_entries"]) == 11 and all(e["user_id"] == ids["carol"] for e in ex["time_entries"]), f"JSON export: own time entries ({len(ex['time_entries'])})")
check(any(l.get("rate") == 100 for l in ex["lists"]), "JSON export: list rate")
dave = A.post(B + "/api/users", json={"username": "dave", "display_name": "Dave", "password": "password123"}).json()["id"]
D = sess("dave")
Dl = [l for l in D.get(B + "/api/state").json()["lists"] if l["is_inbox"]][0]["id"]
D.post(B + "/api/time/entries", json={"list_id": Dl, "start": utc(now - timedelta(hours=1)), "minutes": 5})
A.delete(B + f"/api/users/{dave}")
with db() as c:
    check(c.execute("SELECT COUNT(*) FROM time_entries WHERE user_id=?", (dave,)).fetchone()[0] == 0, "user delete removes their time entries")

# ================= watchdog: reminder + auto-stop (watchdog interval 1 s in the test container)
open(os.path.join(DATA, "ntfy.log"), "w").close()
A.patch(B + "/api/settings", json={"time_remind_h": "0.0005", "time_autostop_h": "0"})
A.post(B + "/api/time/start", json={"task_id": T1})
time.sleep(4)
ps = [p for p in pushes() if p["topic"] == "t-alice"]
check(len(ps) == 1 and ps[0]["title"] == "Timer still running" and "Write report" in ps[0]["msg"] and ps[0]["click"].endswith("/#time"), f"reminder push {ps}")
time.sleep(2)
check(len([p for p in pushes() if p["topic"] == "t-alice"]) == 1, "reminder only once")
A.patch(B + "/api/settings", json={"time_autostop_h": "0.001"})  # 3.6 s
time.sleep(3)
st = A.get(B + "/api/state").json()
ents = A.get(B + f"/api/time/entries?task_id={T1}").json()["entries"]
auto = [e for e in ents if e["auto_stopped"]]
check(st["timer"] is None and auto and auto[0]["seconds"] == 3, f"auto-stop: end = start + 3.6 s ({auto[:1]})")
ps = [p for p in pushes() if p["topic"] == "t-alice"]
check(len(ps) == 2 and ps[1]["title"] == "Timer stopped automatically", "auto-stop push")
Bb.patch(B + "/api/settings", json={"time_remind_h": "0.0005"})
Bb.post(B + "/api/time/start", json={"task_id": TS})
time.sleep(4)
pb = [p for p in pushes() if p["topic"] == "t-bob"]
check(pb and pb[0]["title"] == "Timer läuft noch" and "Noch dran?" in pb[0]["msg"], f"reminder in the recipient's language {pb}")
Bb.post(B + "/api/time/stop", json={})
A.patch(B + "/api/settings", json={"time_remind_h": "4", "time_autostop_h": "12"})

# ================= errors are translated (bob: German)
r = Bb.post(B + "/api/time/entries", json={"task_id": TS, "start": utc(now - timedelta(hours=1))})
check(r.status_code == 400 and r.json()["error"] == "Ende oder Dauer fehlt", "German error message")
check(Bb.patch(B + f"/api/time/entries/{ra['id']}", json={"note": "x"}).json()["error"] == "Nur wer den Eintrag erfasst hat, kann ihn ändern", "German 403 text")
check(A.post(B + "/api/time/entries", json={"task_id": T1, "start": "2026-13-45T25:00", "minutes": 5}).json()["error"] == "Invalid date or time", "invalid date message")
# CSRF header required
check(requests.post(B + "/api/time/start", json={"task_id": T1}, cookies=A.cookies).status_code == 403, "CSRF header required")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
