#!/usr/bin/env python3
"""2.149.0 API tests, part C: database load (#2507 the 4-second poll, #2508 the access context across requests, #2515 indexes,
#2516 the watchdog). Invented people and texts only.
freelancer-matrix: tasks  tenant-matrix: list, org, agent, session
 - #2508 the access context is reused across requests, but every change of a membership counts at once: a member removed
   from the organisation by its admin cannot open the organisation's task with the very next request (and can again right
   after being added back); the same for a membership row written straight into the database (the triggers, no app code);
   an agent moved out of the workspace cannot read the task with the next request, a paused agent is refused at once; a
   signed-out session is refused at once (the session is never cached)
 - #2508 the delta: a participant gets a delta (not full) when only other lists changed, full when their participant list
   changed; an empty delta carries no counts, a delta with a change does
 - #2507 /api/version keeps its fields and their formats; n (news) and t (team chat) move with a new notification / a new
   direct message / a read mark, sp and a are there; /api/state team: unread + direct messages from one room list (same
   numbers as /api/team); a @mention in a list channel
 - #2515 the indexes exist (tasks_done, tasks_due, events_range, the trigram ones, tasks_open stays); the main search finds
   title, notes, link and code snippet matches, also part of a word ("rechn" finds "Rechnung"), two letters, nothing foreign
 - a person without an organisation: state, version, delta and search work the same (own private list)
 - #2508 the cache is used: a membership removed with the triggers off stays cached until the TTL (10 s), then counts
 - PERF line (information): the time of a poll
usage: p2149_c_api_test.py <datadir>   (P2149C_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FEATURES = "cal,collab,comments,events,files,fields,progress"
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def sess(u):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": u, "password": "password123"})
    assert r.ok, (u, r.text)
    return s


def until(fn, secs=20):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.3)
    return fn()


if not (os.environ.get("P2149C_NOSTART") or os.environ.get("KMT_NOSTART")):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Da = sess("bob"), sess("dave")
for s in (A, Bo, Da):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok
FID, Fr = freelancer(B, A)  # freelancer-matrix: tasks (the own private list, state / version / delta / search)


def lids(s):
    return {x["id"] for x in s.get(B + "/api/state").json().get("lists", [])}


# ================================================================ #2508: the access context across requests
OL = A.post(B + "/api/lists", json={"name": "Alpha board", "org_id": ORG}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Plan the shoot", "list_id": OL}).json()["id"]
check(A.put(B + f"/api/lists/{OL}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob member of the organisation's list")
for _ in range(3):  # warm: bob's context is cached now
    Bo.get(B + "/api/version")
check(OL in lids(Bo) and Bo.get(B + f"/api/tasks/{T}").ok, "bob (member) sees the organisation's list and task")

r = A.delete(B + f"/api/orgs/{ORG}/members/{uid['bob']}")
check(r.ok, f"alice removes bob from the organisation {r.status_code} {r.text[:200]}")
r = Bo.get(B + f"/api/tasks/{T}")
check(r.status_code in (403, 404), f"#2508: removed from the organisation -> the very next request cannot open its task ({r.status_code})")
check(OL not in lids(Bo), "#2508: ... and the list is gone from his state")
r = A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"})  # alice no longer sees him: by address
check(r.ok, f"alice adds bob again {r.status_code} {r.text[:200]}")
A.put(B + f"/api/lists/{OL}/members", json={"user_id": uid["bob"], "role": "edit"})
check(Bo.get(B + f"/api/tasks/{T}").ok, "#2508: added again -> the next request sees the task again")

# a membership written straight into the database (no app code, no acx_drop): the triggers renew the generation
g0 = dbx("SELECT value FROM kalmido_meta WHERE key='acx_gen'")
for _ in range(3):
    Bo.get(B + "/api/version")
dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG, uid["bob"]), write=True)
g1 = dbx("SELECT value FROM kalmido_meta WHERE key='acx_gen'")
check(g1 and g1 != g0, f"#2508: a membership change renews the generation {g0} -> {g1}")
r = Bo.get(B + f"/api/tasks/{T}")
check(r.status_code in (403, 404), f"#2508: a membership row deleted in the database counts with the next request ({r.status_code})")
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member')", (ORG, uid["bob"]), write=True)
check(Bo.get(B + f"/api/tasks/{T}").ok, "#2508: the row back -> the next request sees the task")
# a change of something else (a list) leaves the generation as it is
g2 = dbx("SELECT value FROM kalmido_meta WHERE key='acx_gen'")
A.patch(B + f"/api/tasks/{T}", json={"title": "Plan the shoot (2)"})
check(dbx("SELECT value FROM kalmido_meta WHERE key='acx_gen'") == g2, "#2508: a task change does not renew the generation")

# an agent: moved out of the workspace / paused
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "helper", "display_name": "Helper",
                                           "org_id": ORG}).json()
AID, AGH = ag.get("id"), {"Authorization": "Bearer " + ag.get("token", "x"), **H}
A.put(B + f"/api/lists/{OL}/members", json={"user_id": AID, "role": "edit"})
for _ in range(3):
    requests.get(B + f"/api/v1/tasks/{T}", headers=AGH)
r = requests.get(B + f"/api/v1/tasks/{T}", headers=AGH)
check(r.ok, f"the agent in the workspace reads the shared task {r.status_code} {r.text[:200]}")
r = A.patch(B + f"/api/admin/agents/{AID}", json={"org_id": None})
check(r.ok, f"the agent leaves the workspace {r.status_code} {r.text[:200]}")
r = requests.get(B + f"/api/v1/tasks/{T}", headers=AGH)
check(r.status_code in (403, 404), f"#2508: the agent out of the workspace -> the next request cannot read the task ({r.status_code})")
A.patch(B + f"/api/admin/agents/{AID}", json={"org_id": ORG})
A.put(B + f"/api/lists/{OL}/members", json={"user_id": AID, "role": "edit"})
check(requests.get(B + f"/api/v1/tasks/{T}", headers=AGH).ok, "the agent back in the workspace reads the task again")
A.patch(B + f"/api/admin/agents/{AID}", json={"enabled": False})
r = requests.get(B + f"/api/v1/tasks/{T}", headers=AGH)
check(r.status_code in (401, 403), f"#2508: a paused agent is refused with the next request ({r.status_code})")

# a session that ended
S2 = sess("dave")
check(S2.get(B + "/api/version").ok, "dave's second session works")
S2.post(B + "/api/auth/logout")
r = S2.get(B + "/api/version")
check(r.status_code == 401, f"#2508: signed out -> the next request 401 (the session is never cached) ({r.status_code})")

# ================================================================ #2508: the delta for participants, counts only on change
L1 = A.post(B + "/api/lists", json={"name": "Dave participates"}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Dave edits"}).json()["id"]
check(A.put(B + f"/api/lists/{L1}/members", json={"user_id": uid["dave"], "role": "participant"}).ok, "setup: dave participant of L1")
check(A.put(B + f"/api/lists/{L2}/members", json={"user_id": uid["dave"], "role": "edit"}).ok, "setup: dave member of L2")
r = A.post(B + "/api/tasks", json={"title": "For dave", "list_id": L1, "assignee_id": uid["dave"]})
assert r.ok, r.text
TA = r.json()["id"]
TB = A.post(B + "/api/tasks", json={"title": "Not for dave", "list_id": L1}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Shared work", "list_id": L2}).json()["id"]


def delta(s, v):
    return s.get(B + f"/api/state/delta?since={v}").json()


vd = Da.get(B + "/api/state").json()["v"]
d = delta(Da, vd)
check(d.get("full") is False and d.get("tasks") == [] and "counts" not in d, f"#2508: nothing changed -> an empty delta without counts {d}")
A.patch(B + f"/api/tasks/{T2}", json={"title": "Shared work (2)"})
d = delta(Da, vd)
check(d.get("full") is False and [t["id"] for t in d.get("tasks", [])] == [T2] and "done" in d.get("counts", {}),
      f"#2508: a participant elsewhere gets a delta for a change in another list, with counts {str(d)[:300]}")
vd2 = Da.get(B + "/api/state").json()["v"]
A.patch(B + f"/api/tasks/{TB}", json={"title": "Not for dave (2)"})
d = delta(Da, vd2)
check(d.get("full") is True, f"#2508: a change in the participant list -> full {str(d)[:200]}")
st = Da.get(B + "/api/state").json()
ids = {t["id"] for t in st.get("tasks", [])}
check(TA in ids and TB not in ids, "the participant still sees only their own task in the full state")

# ================================================================ #2507: /api/version
v1 = Bo.get(B + "/api/version").json()
check(set(v1) >= {"v", "app", "n", "c", "t", "ty", "sp", "a"} and isinstance(v1["v"], int) and isinstance(v1["a"], dict)
      and "tasks" in v1["a"] and isinstance(v1["n"], str) and isinstance(v1["c"], str) and isinstance(v1["t"], str)
      and isinstance(v1["sp"], int) and isinstance(v1["ty"], list), f"#2507: the fields and their types stay {v1}")
check(v1["n"].count(".") == 1 and v1["c"].count(".") == 2, f"#2507: the formats of n / c stay {v1['n']} {v1['c']}")
check(Bo.get(B + "/api/version").json() == v1, "#2507: nothing changed -> the same answer")
# news: alice assigns bob a task -> his notification
A.post(B + "/api/tasks", json={"title": "Call the venue", "list_id": OL, "assignee_id": uid["bob"]})
v2 = until(lambda: (lambda j: j if j["n"] != v1["n"] else None)(Bo.get(B + "/api/version").json()), 10)
check(v2 and v2["n"] != v1["n"] and v2["v"] > v1["v"] and v2["a"].get("tasks", 0) >= v1["a"].get("tasks", 0),
      f"#2507: a new notification moves n, a task change v {v1['n']} -> {v2 and v2['n']}")
# team chat: a direct message from alice moves bob's t; his state counts it (unread + direct messages)
v2 = Bo.get(B + "/api/version").json()
r = A.post(B + "/api/team/dm", json={"user_id": uid["bob"]})
check(r.ok, f"alice opens a direct conversation with bob {r.status_code} {r.text[:200]}")
RID = r.json().get("id") if r.ok else 0
A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Hello Bob"})
A.post(B + f"/api/team/rooms/{RID}/messages", json={"body": "Are you there?"})
v3 = Bo.get(B + "/api/version").json()
check(v3["t"] != v2["t"], f"#2507: a new direct message moves t {v2['t']} -> {v3['t']}")
team = Bo.get(B + "/api/state").json().get("team", {})
tov = Bo.get(B + "/api/team").json()
check(team.get("enabled") is True and team.get("unread") == 2 and team.get("dm_unread") == 2 and tov.get("unread") == 2,
      f"#2507: /api/state team counts the two direct messages once (= /api/team) {team} {tov.get('unread')}")
dm = [x for x in tov.get("rooms", []) if x["id"] == RID]
check(dm and dm[0]["unread"] == 2 and dm[0]["last"] and dm[0]["last"]["text"] == "Are you there?" and dm[0]["mention"] is False,
      f"#2507: the room: unread, the newest message, no mention {dm[:1]}")
Bo.post(B + f"/api/team/rooms/{RID}/read", json={})
v4 = Bo.get(B + "/api/version").json()
team = Bo.get(B + "/api/state").json().get("team", {})
check(v4["t"] != v3["t"] and team.get("unread") == 0 and team.get("dm_unread") == 0, f"#2507: read -> t moves, nothing unread {team}")
# a @mention in the list channel (bob is a member of the organisation's list)
rooms = A.get(B + "/api/team").json().get("rooms", [])
ch = [x for x in rooms if x.get("list_id") == OL]
if ch:
    A.post(B + f"/api/team/rooms/{ch[0]['id']}/messages", json={"body": f"<@{uid['bob']}> please check the board"})
    br = [x for x in Bo.get(B + "/api/team").json().get("rooms", []) if x["id"] == ch[0]["id"]]
    check(br and br[0]["unread"] >= 1 and br[0]["mention"] is True, f"#2507: a mention in the list channel {br[:1]}")
    team = Bo.get(B + "/api/state").json().get("team", {})
    check(team.get("unread", 0) >= 1 and team.get("dm_unread") == 0, f"#2507: the channel counts as unread, not as a direct message {team}")
else:
    check(False, f"the organisation list's channel exists {rooms}")

# ================================================================ #2515: indexes + the main search
idx = {r[0] for r in dbx("SELECT indexname FROM pg_indexes WHERE tablename IN ('tasks', 'events')")}
want = {"tasks_done", "tasks_due", "events_range", "tasks_trgm_title", "tasks_trgm_content", "tasks_trgm_url", "tasks_snippets", "tasks_open"}
check(want <= idx, f"#2515: the indexes exist (tasks_open stays) {sorted(want - idx)}")
SL = A.post(B + "/api/lists", json={"name": "Search here"}).json()["id"]
S1 = A.post(B + "/api/tasks", json={"title": "Rechnung Oktober", "list_id": SL}).json()["id"]
S2t = A.post(B + "/api/tasks", json={"title": "Paket", "content": "Notiz zur Lieferung am Dienstag", "list_id": SL}).json()["id"]
S3 = A.post(B + "/api/tasks", json={"title": "Website", "url": "https://example.com/abc-xyz", "list_id": SL}).json()["id"]
S4 = A.post(B + "/api/tasks", json={"title": "Snippet", "list_id": SL}).json()["id"]
dbx("""UPDATE tasks SET snippets='[{"path": "src/zauber.py", "code": "def hokus(): pass"}]'::jsonb WHERE id=?""", (S4,), write=True)
FT = Fr.post(B + "/api/tasks", json={"title": "Rechnung Frida"}).json()["id"]


def search(s, q):
    r = s.get(B + "/api/tasks", params={"scope": "search", "q": q})
    return {t["id"] for t in r.json().get("tasks", [])} if r.ok else {"error", r.status_code}


check(search(A, "rechn") == {S1}, f"#2515: part of a word in the title ({search(A, 'rechn')})")
check(search(A, "LIEFERUNG") == {S2t}, "#2515: a word of the notes, any case")
check(search(A, "abc-xyz") == {S3}, "#2515: the link")
check(search(A, "hokus") == {S4} and search(A, "zauber") == {S4}, "#2515: code snippet text and path")
check(S1 in search(A, "re") and S2t in search(A, "ie"), "#2515: two letters still match (title and notes)")
check(search(A, "100%") == set() and search(A, "a_b") == set(), "#2515: % and _ are literal")
check(search(Fr, "rechn") == {FT} and FT not in search(A, "rechn"), "#2515: each person finds only their own (freelancer included)")

# ================================================================ a person without an organisation
vf = Fr.get(B + "/api/version")
check(vf.ok and set(vf.json()) >= {"v", "n", "c", "t", "sp", "a"}, f"freelancer: /api/version {vf.status_code}")
stf = Fr.get(B + "/api/state").json()
v0f = stf["v"]
Fr.patch(B + f"/api/tasks/{FT}", json={"title": "Rechnung Frida (2)"})
df = delta(Fr, v0f)
check(df.get("full") is False and [t["id"] for t in df.get("tasks", [])] == [FT], f"freelancer: her delta {str(df)[:200]}")
for _ in range(3):
    check(Fr.get(B + f"/api/tasks/{FT}").ok, "freelancer: her task with the cached context")
check(Fr.get(B + f"/api/tasks/{T}").status_code in (403, 404), "freelancer: the organisation's task stays closed")

# ================================================================ #2508: the cache is really used (and ends with its TTL)
# a membership removed with the triggers switched off (session_replication_role = replica): nothing renews the generation, so
# the context cached by the last request lives on until KALMIDO_ACX_TTL (10 s) -- proof that requests reuse it, and that the
# TTL bounds even a change the triggers never saw (the app's own writes always renew it, see above)
check(Bo.get(B + f"/api/tasks/{T}").ok, "bob sees the task (context cached now)")
dbx("SET session_replication_role = replica; DELETE FROM org_members WHERE org_id=%d AND user_id=%d" % (ORG, uid["bob"]), write=True)
r = Bo.get(B + f"/api/tasks/{T}")
check(r.ok, f"#2508: without the triggers the cached context lives on (the cache is used) ({r.status_code})")
time.sleep(11)
r = Bo.get(B + f"/api/tasks/{T}")
check(r.status_code in (403, 404), f"#2508: after the TTL the context is read again ({r.status_code})")
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member')", (ORG, uid["bob"]), write=True)
check(Bo.get(B + f"/api/tasks/{T}").ok, "#2508: the row back (with the triggers) -> at once")

# ================================================================ PERF (information): the poll
t0 = time.time()
for _ in range(20):
    Bo.get(B + "/api/version")
print(f"PERF p2149_c: /api/version {(time.time() - t0) * 1000 / 20:.1f} ms each (20 polls)", flush=True)

print(f"p2149_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
