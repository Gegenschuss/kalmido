#!/usr/bin/env python3
"""2.116.0 API tests, part D (#2066 daily at several times, #2067 focus sessions + habit statistics over API v1), own container.
Invented people only (example.com).
tenant-matrix: own
freelancer-matrix: time
 - a repeat FREQ=DAILY;TIMES=0800,1300,2000: stored sorted, completing moves the due time to the next one of the same day, after
   the last one to the first of the next day, skip does the same, undo takes the time back; more than 12 times, doubles,
   FREQ=WEEKLY with TIMES, hourly and BYHOUR stay refused
 - API v1: GET /focus, /focus/stats, POST /focus/start, /focus/{id}/pause|resume|stop with the token's scope (read / time), 403
   without; another person sees nothing of it (404); every agent (team or personal) is refused with 403; a person without an
   organisation uses it; GET /habits/{id}/stats
usage: p2116_d_api_test.py <datadir>      (P2116D_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

import requests
from freelancer_fixture import freelancer
import testclock  # noqa: E402  (2.192.0 A, #2512: the group's test time, run_all.sh `now`)

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,habits,pomo,time,collab"


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def token(s, scopes):
    r = s.post(B + "/api/me/tokens", json={"name": "script", "scopes": scopes})
    assert r.ok, r.text
    return bearer(r.json()["token"])


if os.environ.get("P2116D_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com"})
assert r.ok, r.text
Ca = sess("carol")
for s in (A, Ca):
    assert s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"}).ok

# ---------------------------------------------------------------- #2066 daily at several times
L = A.post(B + "/api/lists", json={"name": "Medikamente"}).json()["id"]
TODAY = testclock.now().replace(tzinfo=None).date().isoformat()


def new(rep, due=TODAY, tm="08:00", **kw):
    return A.post(B + "/api/tasks", json={"title": "Tablette", "list_id": L, "due": due, "due_time": tm, "repeat": rep, **kw})


def get(tid):
    return A.get(B + f"/api/tasks/{tid}").json()


r = new("FREQ=DAILY;TIMES=2000,0800,1300")
check(r.status_code in (200, 201), f"create with TIMES: {r.status_code} {r.text[:200]}")
T = r.json()["id"]
check(get(T)["repeat"] == "FREQ=DAILY;TIMES=0800,1300,2000", f"times stored sorted: {get(T)['repeat']}")
j = A.post(B + f"/api/tasks/{T}/complete", json={}).json()
check(j["due"] == TODAY and j["due_time"] == "13:00", f"08:00 done -> 13:00 the same day: {j['due']} {j['due_time']}")
j = A.post(B + f"/api/tasks/{T}/complete", json={}).json()
check(j["due"] == TODAY and j["due_time"] == "20:00", f"13:00 done -> 20:00: {j['due']} {j['due_time']}")
tmr = (testclock.now().replace(tzinfo=None).date() + timedelta(days=1)).isoformat()
j = A.post(B + f"/api/tasks/{T}/complete", json={}).json()
check(j["due"] == tmr and j["due_time"] == "08:00", f"20:00 done -> 08:00 tomorrow: {j['due']} {j['due_time']}")
und = j.get("undo")
check(bool(und), "complete returns an undo record")
if und:
    ru = A.post(B + f"/api/tasks/{T}/undo", json=und)
    check(ru.ok and get(T)["due"] == TODAY and get(T)["due_time"] == "20:00", f"undo takes the time back: {ru.text[:200]} {get(T)['due']} {get(T)['due_time']}")
j = A.post(B + f"/api/tasks/{T}/skip", json={}).json()
check(j["due"] == tmr and j["due_time"] == "08:00", f"skip after the last time -> first of tomorrow: {j.get('due')} {j.get('due_time')}")
# interval 2 + weekday filter: next day is a matching one
W = new("FREQ=DAILY;INTERVAL=2;TIMES=0900,1700", tm="17:00").json()["id"]
j = A.post(B + f"/api/tasks/{W}/complete", json={}).json()
d2 = (testclock.now().replace(tzinfo=None).date() + timedelta(days=2)).isoformat()
check(j["due"] == d2 and j["due_time"] == "09:00", f"every 2 days: after the last time two days later: {j['due']} {j['due_time']}")
# COUNT counts the ticks
C = new("FREQ=DAILY;TIMES=0800,1300;COUNT=2").json()["id"]
A.post(B + f"/api/tasks/{C}/complete", json={})
j = A.post(B + f"/api/tasks/{C}/complete", json={}).json()
check(j["status"] == 2 and not j["repeat"], f"COUNT=2 ends after two ticks: {j['status']} {j['repeat']}")
# refused
for rule, why in (("FREQ=DAILY;TIMES=" + ",".join(f"{h:02d}00" for h in range(1, 14)), "13 times"), 
                  ("FREQ=WEEKLY;TIMES=0800", "weekly"), ("FREQ=DAILY;TIMES=2500", "hour 25"), ("FREQ=DAILY;TIMES=0860", "minute 60"),
                  ("FREQ=HOURLY", "hourly"), ("FREQ=DAILY;BYHOUR=8,13", "byhour"), ("FREQ=DAILY;TIMES=", "empty")):
    check(new(rule).status_code == 400, f"refused: {why}")
check(new("FREQ=DAILY;TIMES=" + ",".join(f"{h:02d}00" for h in range(8, 20))).status_code in (200, 201), "12 times are fine")
rd = new("FREQ=DAILY;TIMES=1300,0800,1300")
check(rd.status_code in (200, 201) and rd.json()["repeat"] == "FREQ=DAILY;TIMES=0800,1300", f"doubles are dropped: {rd.text[:200]}")
# ---------------------------------------------------------------- #2067 focus + habit stats over API v1
Pr = token(A, ["read", "time", "tasks:write"])
Pro = token(A, ["read"])
Pc = token(Ca, ["read", "time"])
check(Pr.get(B + "/api/v1/focus").json()["data"] == [], "no sessions yet")
r = Pr.post(B + "/api/v1/focus/start", json={"kind": "focus", "minutes": 25})
check(r.status_code == 201 and r.json()["data"]["running"], f"start: {r.status_code} {r.text[:200]}")
SID = r.json()["data"]["id"]
check(Pro.post(B + "/api/v1/focus/start", json={}).status_code == 403, "start without scope time: 403")
check(Pr.post(B + "/api/v1/focus/start", json={"kind": "nap"}).status_code == 400, "unknown kind: 400")
check(Pr.post(B + "/api/v1/focus/start", json={"minutes": 0}).status_code == 400, "0 minutes: 400")
check(Pr.post(B + "/api/v1/focus/start", json={"colour": "x"}).status_code == 400, "unknown field: 400")
check(Pr.post(B + f"/api/v1/focus/{SID}/pause").json()["data"]["paused"], "pause")
check(not Pr.post(B + f"/api/v1/focus/{SID}/resume").json()["data"]["paused"], "resume")
check(Pc.post(B + f"/api/v1/focus/{SID}/stop").status_code == 404, "another person: stop -> 404")
check(Pc.get(B + "/api/v1/focus").json()["data"] == [], "another person sees none of it")
r = Pr.post(B + f"/api/v1/focus/{SID}/stop")
check(r.ok and not r.json()["data"]["running"], f"stop: {r.text[:200]}")
lst = Pr.get(B + "/api/v1/focus?limit=1").json()
check(len(lst["data"]) == 1 and lst["data"][0]["id"] == SID, "list newest first")
st = Pr.get(B + "/api/v1/focus/stats")
check(st.ok and "today" in st.json() and "recent" in st.json(), f"stats: {st.text[:200]}")
check(Pr.get(B + "/api/v1/focus?bogus=1").status_code == 400, "unknown query parameter: 400")
# a task of a list the person does not see is not named
TK = A.post(B + "/api/tasks", json={"title": "Geheim", "list_id": L}).json()["id"]
Pr.post(B + "/api/v1/focus/start", json={"task_id": TK})
Pr.post(B + f"/api/v1/focus/{Pr.get(B + '/api/v1/focus').json()['data'][0]['id']}/stop")
# 2.116.0 review F7: a task the person cannot see is refused (404) instead of a silent session without a task
rc = Pc.post(B + "/api/v1/focus/start", json={"task_id": TK})
check(rc.status_code == 404, f"focus start on a foreign task: 404 ({rc.status_code})")
carols = Pc.get(B + "/api/v1/focus").json()["data"]
check(not any(x.get("task_title") == "Geheim" for x in carols), f"a foreign task is never named: {carols}")
# agents: team agent, personal agent -> 403 everywhere
for name, kw in (("teambot", {}), ("alicebot", {})):
    body = {"scopes": ["read", "time", "tasks:write"], "username": name, "display_name": name.title()}
    ra = A.post(B + "/api/admin/agents", json=body)
    assert ra.status_code in (200, 201), ra.text
    ag = bearer(ra.json()["token"])
    uid = ra.json()["id"]
    if name == "alicebot":
        A.patch(B + f"/api/admin/agents/{uid}", json={"owner_id": A.get(B + "/api/state").json()["me"]["id"]})
    check(ag.get(B + "/api/v1/focus").status_code == 403, f"{name}: GET /focus 403")
    check(ag.get(B + "/api/v1/focus/stats").status_code == 403, f"{name}: stats 403")
    check(ag.post(B + "/api/v1/focus/start", json={}).status_code == 403, f"{name}: start 403")
    check(ag.post(B + f"/api/v1/focus/{SID}/stop").status_code == 403, f"{name}: stop 403")
# habit statistics
h = Pr.post(B + "/api/v1/habits", json={"name": "Wasser", "goal": 1}).json()
hid = h["id"]
for back in (0, 1, 2):
    day = (testclock.now().replace(tzinfo=None).date() - timedelta(days=back)).isoformat()
    Pr.post(B + f"/api/v1/habits/{hid}/checkin", json={"date": day})
hs = Pr.get(B + f"/api/v1/habits/{hid}/stats").json()
check(hs["current_streak"] == 3 and hs["best_streak"] >= 3 and hs["streak_unit"] == "days" and hs["total_days"] == 3, f"habit stats {hs}")
check(Pro.get(B + f"/api/v1/habits/{hid}/stats").ok, "habit stats with scope read")
check(Pc.get(B + f"/api/v1/habits/{hid}/stats").status_code == 404, "another person's habit: 404")
check(requests.get(B + f"/api/v1/habits/{hid}/stats").status_code == 401, "no token: 401")
# a person without an organisation (freelancer-matrix: time)
FID, Fr = freelancer(B, A)
Ft = token(Fr, ["read", "time"])
r = Ft.post(B + "/api/v1/focus/start", json={"kind": "stopwatch"})
check(r.status_code == 201, f"freelancer: start {r.status_code} {r.text[:200]}")
check(Ft.get(B + "/api/v1/focus/stats").ok and Ft.get(B + "/api/v1/focus").ok, "freelancer: list + stats")
fid = r.json()["data"]["id"]
for act in ("pause", "resume", "stop"):
    check(Ft.post(B + f"/api/v1/focus/{fid}/{act}").ok, f"freelancer: {act}")
fh = Fr.post(B + "/api/habits", json={"name": "Dehnen"}).json()
check(Ft.get(B + f"/api/v1/habits/{fh['id']}/stats").ok, "freelancer: habit stats")

print(f"{OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
