#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.369.4 API tests (#2507 the poll's version per organisation / person, #2516 the watchdog's sections with an interval).
Invented people and texts only.
freelancer-matrix: lists, tasks
 - #2507 GET /api/version carries vs, the newest version meant for the person: a change in another organisation's list,
   in a list the person does not see or of another person's own settings moves v but not vs; a change in an own list,
   in a list of the own organisation, in a list shared with the person (also without an organisation), the person's own
   setting and a change for everyone (outside the list scope, a write without a request) moves vs up to v; adding /
   removing the person as a list member moves vs for them; the delta after a skipped change has nothing for the person;
   the poll stays one statement for the signatures
 - #2516 the watchdog: a clean-up section runs at most every KALMIDO_WD_SLOW_S seconds (a second tick within the interval
   skips it, after the interval it runs again; 0 = every tick), reminders / nags / events every tick; the tests' start.sh
   sets 0. A wave of due reminders (assignee with the role "edit", a participant, an assignee without access any more ->
   the creator, a person who comes along) reaches the same people as one by one, and costs few statements per reminder
   (PERF line with the statements per reminder and the most frequent ones)
usage: p2369_4_api_test.py <datadir>"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, sess, dbx  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')
FEATURES = "cal,collab,comments,events,fields,progress"


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    return out[-1] if out else "ERR " + r.stderr[-600:]


A = kt.setup()
ORG = {}
for name in ("Alpha", "Beta"):
    r = A.post(B + "/api/admin/orgs", json={"name": name})
    assert r.status_code in (200, 201), r.text
    ORG[name] = r.json()["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u, o in (("bob", "Alpha"), ("dave", "Alpha"), ("carl", "Beta")):
    r = A.post(B + "/api/users", json={"orgs": [ORG[o]], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Da, Ca = sess("bob"), sess("dave"), sess("carl")
for s in (A, Bo, Da, Ca):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok
FID, Fr = freelancer(B, A)  # freelancer-matrix: lists, tasks (the own key of a person without an organisation)
P = {"alice": A, "bob": Bo, "dave": Da, "carl": Ca, "frida": Fr}


def task(s, title, lid, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def ver(s):
    j = s.get(B + "/api/version").json()
    return j["v"], j.get("vs")


def moved(what, fn, see, skip):
    """Run the change fn; every person in see must get vs == the new v, every one in skip keeps vs below the old v + 1."""
    before = {k: ver(P[k]) for k in P}
    assert fn() is not False
    after = {k: ver(P[k]) for k in P}
    v = max(x[0] for x in after.values())
    v0 = max(x[0] for x in before.values())
    check(v > v0, f"#2507 {what}: v moved")
    # #5405: since 2.747 (#5249) the writer's step group bumps the writer's own counter ("self") right after the change, so
    # the newest v can be that bump, which only the writer sees: the change's version is the one the readers got, newer
    # than every version before the change and the same for all of them
    # (the writer = the first word of what, its vs may be that newer own bump)
    who = what.split()[0].split("'")[0]
    readers = [k for k in see if k != who]
    vc = max((after[k][1] or 0) for k in readers) if readers else v
    for k in see:
        check((after[k][1] or 0) >= vc if k == who else after[k][1] == vc, f"#2507 {what}: {k} sees it "
              f"(vs {before[k][1]} -> {after[k][1]}, change {vc}, v {v})")
    check(vc > v0, f"#2507 {what}: the change's version is newer than every one before ({vc} > {v0})")
    for k in skip:
        check(after[k][1] == before[k][1] and after[k][1] < v,
              f"#2507 {what}: {k} skips it (vs {before[k][1]} -> {after[k][1]}, v {v})")
    return before, after


def ok(r):
    assert r.ok, r.text
    return True


AL = A.post(B + "/api/lists", json={"name": "Alpha board", "org_id": ORG["Alpha"]}).json()["id"]
check(ok(A.put(B + f"/api/lists/{AL}/members", json={"user_id": uid["bob"], "role": "edit"})), "setup: bob member of the Alpha board")
CL = Ca.post(B + "/api/lists", json={"name": "Beta board"}).json()["id"]
FL = Fr.post(B + "/api/lists", json={"name": "Own work"}).json()["id"]
PL = A.post(B + "/api/lists", json={"name": "Alice private"}).json()["id"]
AT, CT1, FT = task(A, "Alpha task", AL), task(Ca, "Carl's task", CL), task(Fr, "Frida's task", FL)

v0, vs0 = ver(Bo)
check(vs0 is not None and 0 < vs0 <= v0, f"#2507 /api/version carries vs <= v ({vs0}, {v0})")
r = Bo.get(B + "/api/version")
n_poll = nstmt(r)
check(0 < n_poll <= 10, f"#2507 the poll stays a few statements ({n_poll}; audit Q 24.10.2026: 11)")
print(f"PERF #2507 GET /api/version: {n_poll} statements", flush=True)

# another organisation's list: only its people; the org key reaches dave without a membership (same organisation as the list)
moved("carl changes a task of his organisation", lambda: ok(Ca.patch(B + f"/api/tasks/{CT1}", json={"title": "Carl's task 2"})),
      ["carl"], ["bob", "dave", "frida"])
b, _ = moved("alice changes a task of the Alpha board", lambda: ok(A.patch(B + f"/api/tasks/{AT}", json={"title": "Alpha task 2"})),
             ["alice", "bob", "dave"], ["carl", "frida"])
# the delta after a skipped change has nothing for carl (the skip is safe)
v1, vs1 = ver(Ca)
moved("bob comments on the Alpha task", lambda: ok(Bo.post(B + f"/api/tasks/{AT}/comments", json={"body": "Looks good"})),
      ["alice", "bob", "dave"], ["carl", "frida"])
j = Ca.get(B + "/api/state/delta", params={"since": v1, "lean": "1"}).json()
check(j.get("full") is False and j.get("tasks") == [] and j.get("gone") == [], f"#2507 carl's delta over the skipped changes is empty {j}")
# the person without an organisation: own list, then a list shared with her
moved("frida changes her task", lambda: ok(Fr.patch(B + f"/api/tasks/{FT}", json={"title": "Frida's task 2"})),
      ["frida"], ["alice", "bob", "dave", "carl"])
moved("alice changes her private list", lambda: task(A, "Private", PL), ["alice"], ["bob", "dave", "carl", "frida"])
dbx("UPDATE users SET email_proved=lower(COALESCE(email, '')) WHERE email_proved=''")  # 2.1001.0 (#5669): a list / folder shared by address binds only a proved address (a mailed link / OIDC); the accounts here proved theirs
moved("alice shares the private list with frida", lambda: ok(A.put(B + f"/api/lists/{PL}/members", json={"email": "frida@example.com", "role": "edit"})),
      ["alice", "frida"], ["bob", "dave", "carl"])
check(bool(kt.dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (PL, FID))), "setup: frida is a member of alice's private list")
PT = task(A, "Shared private", PL)
moved("alice changes the shared task", lambda: ok(A.patch(B + f"/api/tasks/{PT}", json={"title": "Shared private 2"})),
      ["alice", "frida"], ["bob", "dave", "carl"])
moved("frida changes the shared task", lambda: ok(Fr.patch(B + f"/api/tasks/{PT}", json={"title": "Shared private 3"})),
      ["alice", "frida"], ["bob", "dave", "carl"])
moved("alice removes frida from the list", lambda: ok(A.delete(B + f"/api/lists/{PL}/members/{FID}")),
      ["alice", "frida"], ["bob", "dave", "carl"])
moved("alice changes the private list again", lambda: ok(A.patch(B + f"/api/tasks/{PT}", json={"title": "Shared private 4"})),
      ["alice"], ["bob", "dave", "carl", "frida"])
# a task moved from one list to another: the people of both
moved("alice moves the private task to the Alpha board", lambda: ok(A.patch(B + f"/api/tasks/{PT}", json={"list_id": AL})),
      ["alice", "bob", "dave"], ["carl", "frida"])
# the own settings ("self"): only the writer
moved("bob's own setting", lambda: ok(Bo.patch(B + "/api/settings", json={"work_end": "18:00"})), ["bob"],
      ["alice", "dave", "carl", "frida"])
# a write for everyone: a list's visibility (a "full" change), another area, a write without a request
moved("alice opens the Alpha board to the organisation", lambda: ok(A.patch(B + f"/api/lists/{AL}", json={"org_visibility": "org"})),
      list(P), [])
res = []
moved("a bump without a request (watchdog)",
      lambda: res.append(in_app("from kalmido.core.db import connect, bump\nc = connect()\nbump(c)\nc.commit()\nc.close()\nprint('bumped')")),
      list(P), [])
check(res == ["bumped"], f"#2507 the background bump ran {res}")

# the start sets version:all to the version (a barrier for the keys): after a restart nobody skips a change made before it
moved("carl changes his task again", lambda: ok(Ca.patch(B + f"/api/tasks/{CT1}", json={"title": "Carl's task 3"})),
      ["carl"], ["bob", "dave", "frida"])
v_before = max(ver(P[k])[0] for k in P)
if kt.fresh(keep=True):  # (a running container without a restart: KMT_NOSTART)
    Bo, Ca = sess("bob"), sess("carl")
    v2, vs2 = ver(Bo)
    check(vs2 == v2 >= v_before, f"#2507 after a restart vs = v for everyone ({vs2}, {v2})")
    check(ver(Ca)[1] == v2, "#2507 after a restart vs = v for carl too")

# ================================================================ #2516: the watchdog
IV = """
from kalmido.notify import push as P
ran = []
P.WD_SLOW_S = 600
for name in ("list trash", "reminders"):
    for i in range(2):
        P._wd_section(None, name, lambda c, n=name: ran.append(n))
t = P._WD_LAST["list trash"]
again = P._wd_due("list trash", t + 601)
soon = P._wd_due("list trash", t + 605)
P.WD_SLOW_S = 0
zero = [P._wd_due("list trash") for i in range(2)]
print(json.dumps({"ran": ran, "again": again, "soon": soon, "zero": zero, "slow": sorted(P.WD_SLOW)}))
"""
res = in_app(IV)
try:
    iv = json.loads(res)
except ValueError:
    iv = {}
check(iv.get("ran") == ["list trash", "reminders", "reminders"], f"#2516 a clean-up section once within the interval, reminders every tick {res[:300]}")
check(iv.get("again") is True and iv.get("soon") is False, f"#2516 after the interval it runs again (and not right after) {iv}")
check(iv.get("zero") == [True, True], f"#2516 KALMIDO_WD_SLOW_S=0: every tick {iv}")
check(not {"reminders", "nags", "events", "time", "collab pushes", "fixed reminders", "follow-ups", "admin alerts",
           "list folder shares", "security watch"} & set(iv.get("slow", [])) and "task trash" in iv.get("slow", []),
      f"#2516 the slow ones are clean-ups only {iv.get('slow')}")

# the wave: 60 due reminders in an organisation list
now = datetime.fromisoformat(in_app("from kalmido.core.db import local_now\nprint(local_now().replace(tzinfo=None).isoformat())"))
due = now + timedelta(days=2)  # the running watchdog of the container must not fire them: the wave runs with its own clock
dday, dtime = due.date().isoformat(), due.strftime("%H:%M")
RL = A.post(B + "/api/lists", json={"name": "Reminder wave", "org_id": ORG["Alpha"]}).json()["id"]
check(ok(A.put(B + f"/api/lists/{RL}/members", json={"user_id": uid["bob"], "role": "edit"})), "setup: bob edits the wave list")
check(ok(A.put(B + f"/api/lists/{RL}/members", json={"user_id": uid["dave"], "role": "participant"})), "setup: dave participant")
for u in ("bob", "dave", "alice"):
    A.patch(B + f"/api/users/{uid[u]}", json={"ntfy_topic": f"t-{u}"})
for s in (A, Bo, Da):
    assert s.patch(B + "/api/settings", json={"quiet_from": "", "quiet_to": ""}).ok
r = A.post(B + "/api/users", json={"orgs": [ORG["Alpha"]], "username": "erin", "display_name": "Erin", "password": "password123",
                                   "email": "erin@example.com"})
assert r.ok, r.text
uid["erin"] = r.json()["id"]
check(ok(A.put(B + f"/api/lists/{RL}/members", json={"user_id": uid["erin"], "role": "edit"})), "setup: erin edits the wave list")
EXPECT = {}
for i in range(60):
    who = ("bob", "dave", "erin")[i % 3]
    t = task(A, f"Wave {i}", RL, due=dday, due_time=dtime, reminders="0", assignee_id=uid[who])
    EXPECT[t] = {"erin": "alice"}.get(who, who)  # erin leaves the list: her reminders go to alice (the creator)
check(ok(A.delete(B + f"/api/lists/{RL}/members/{uid['erin']}")), "setup: erin no longer in the wave list")
CA_ = task(A, "Wave with company", RL, due=dday, due_time=dtime, reminders="0", assignee_id=uid["bob"])
r = A.patch(B + f"/api/tasks/{CA_}", json={"people": [uid["dave"]]})
check(r.ok, f"setup: dave comes along {r.text[:200]}")
WAVE = """
from kalmido.core.db import connect, local_now
from kalmido.core import pg as PG
from kalmido.notify import push as P
from collections import Counter
from datetime import timedelta
sent, cnt = [], Counter()
o_notify, o_pgx = P.notify, PG.Conn._pgx
def notify(uid, title, *a, **k):
    sent.append([uid, title])
    return o_notify(uid, title, *a, **k)
def pgx(self, sql, args=None):
    cnt[" ".join(str(sql).split())[:90]] += 1
    return o_pgx(self, sql, args)
P.notify, PG.Conn._pgx = notify, pgx
c = connect()
users = {r["id"]: r for r in c.execute("SELECT * FROM users WHERE disabled=0")}
S = P._wd_settings(c, users)
LG = {u: "en" for u in users}
cnt.clear()
P._wd_reminders(c, users, S, LG, local_now() + timedelta(days=2, minutes=2))
c.close()
KIND = {"people": "FROM task_people", "members": "FROM list_members WHERE list_id", "pvis": "WITH RECURSIVE pa",
        "lists": "deleted_at FROM lists WHE", "datalock": "a.data_lock FROM users"}
kinds = {k: sum(n for q, n in cnt.items() if p in q) for k, p in KIND.items()}
print(json.dumps({"sent": sent, "n": sum(cnt.values()), "top": cnt.most_common(12), "kinds": kinds}))
"""
res = in_app(WAVE)
try:
    wv = json.loads(res)
except ValueError:
    wv = {}
check(bool(wv), f"#2516 the wave ran {res[:400]}")
name = {v: k for k, v in uid.items()}
got = {}
for u, title in wv.get("sent", []):
    got.setdefault(title, set()).add(name.get(u, u))
titles = {t: f"Wave {i}" for i, t in enumerate(EXPECT)}
wrong = {titles[t]: (sorted(got.get(titles[t], [])), w) for t, w in EXPECT.items() if got.get(titles[t]) != {w}}
check(not wrong, f"#2516 every reminder of the wave reached its person (edit member, participant, the creator for erin) {dict(list(wrong.items())[:5])}")
check(got.get("Wave with company") == {"bob", "dave"}, f"#2516 the one who comes along gets it too {got.get('Wave with company')}")
per = wv.get("n", 0) / 61 if wv else 0
print(f"PERF #2516 reminder wave: 61 reminders, {wv.get('n')} statements ({per:.1f} per reminder); most: {wv.get('top')}", flush=True)
check(0 < per < 20, f"#2516 fewer than 20 statements per reminder (audit Q 24.10.2026: ~250) {per:.1f}")
kd = wv.get("kinds", {})
print(f"PERF #2516 recipient lookups of the wave: {kd}", flush=True)
# per list and tick, not per reminder (before 2.369.4: task_people 61, list_members 23, participant sets 42, data lock 44)
check(kd and kd.get("people", 99) <= 1 and kd.get("members", 99) <= 2 and kd.get("pvis", 99) <= 4 and kd.get("lists", 99) <= 2
      and kd.get("datalock", 99) <= 6, f"#2516 roles, who comes along and the participant's tasks once per list and tick {kd}")

sys.exit(kt.done("p2369_4_api"))
