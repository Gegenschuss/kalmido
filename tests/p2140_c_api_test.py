"""2.140.0 API tests, part C: journal history, search, export, mood statistics (#2133); several reminder times per habit (#2135).
Invented names only. One container (start.sh).
#2133: GET /api/life/journal newest first, 30 per page + cursor (next / before), q (case-insensitive, % and _ literal), mood,
  from / to; GET /api/life/journal/stats (30 / 90 / 365, distribution + series, other values 400); GET /api/life/journal/export
  (md / csv, range, spreadsheet formulas defused); each person sees only their own entries; a person without an organisation
  (freelancer-matrix: personal) uses all three.
#2135: habits keep remind_at (the first time) and get remind_times (sorted, unique, at most 6, HH:MM); an old client that sends
  only remind_at still works (both set); API v1 answers both and accepts remind_times.
usage: p2140_c_api_test.py <datadir>      (P2140C_NOSTART=1: a server already runs on KALMIDO_TEST_PORT)"""
import os
import subprocess
import sys
import time
from datetime import date, timedelta

import requests
from freelancer_fixture import freelancer
import testclock  # noqa: E402  (2.192.0 A, #2512: the group's test time, run_all.sh `now`)

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


if os.environ.get("P2140C_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
assert A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"}).ok
Bo = sess("bob")
FEAT = "cal,habits,review,family"
for s in (A, Bo):
    r = s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
    assert r.ok, r.text
TODAY = testclock.today()
day = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731


def put(s, d, text, mood=None):
    return s.put(B + f"/api/life/journal/{d}", json={"text": text, "mood": mood})


def suite(s, who):
    # 40 entries: day n has mood 1 + n % 5, every 7th mentions "Garden_Party 100%"
    for n in range(40):
        r = put(s, day(n), f"Entry {n} " + ("Garden_Party 100% sunny" if n % 7 == 0 else "plain day"), 1 + n % 5)
        check(r.ok, f"{who}: write {n} " + r.text[:120])
    put(s, day(50), "=cmd|' /C calc'!A0 formula", 3)
    r = s.get(B + "/api/life/journal")
    j = r.json()
    check(r.ok and len(j["entries"]) == 30 and j["entries"][0]["day"] == day(0) and j["next"] == j["entries"][-1]["day"], f"{who}: first page {r.status_code} {len(j.get('entries', []))}")
    j2 = s.get(B + "/api/life/journal", params={"before": j["next"]}).json()
    check(len(j2["entries"]) == 11 and j2["next"] is None and j2["entries"][0]["day"] < j["next"], f"{who}: second page {len(j2['entries'])}")
    check(len(s.get(B + "/api/life/journal", params={"limit": 5}).json()["entries"]) == 5, f"{who}: limit")
    check(s.get(B + "/api/life/journal", params={"limit": 500}).status_code == 400, f"{who}: limit too big = 400")
    q = s.get(B + "/api/life/journal", params={"q": "garden_party"}).json()["entries"]
    check(sorted(x["day"] for x in q) == sorted(day(n) for n in (0, 7, 14, 21, 28, 35)), f"{who}: search finds 6 entries, case-insensitive ({len(q)})")
    check(s.get(B + "/api/life/journal", params={"q": "%"}).json()["entries"].__len__() == 6, f"{who}: % is a literal, not a wildcard")
    check(s.get(B + "/api/life/journal", params={"q": "gardenxparty"}).json()["entries"] == [], f"{who}: _ is a literal")
    m = s.get(B + "/api/life/journal", params={"mood": 5, "limit": 100}).json()["entries"]
    check(m and all(x["mood"] == 5 for x in m), f"{who}: mood filter")
    check(s.get(B + "/api/life/journal", params={"mood": 9}).status_code == 400, f"{who}: mood 9 = 400")
    rg = s.get(B + "/api/life/journal", params={"from": day(10), "to": day(5)}).json()["entries"]
    check([x["day"] for x in rg] == [day(n) for n in range(5, 11)], f"{who}: range {[x['day'] for x in rg]}")
    check(s.get(B + "/api/life/journal", params={"from": "nope"}).status_code == 400, f"{who}: bad date = 400")
    # statistics
    st = s.get(B + "/api/life/journal/stats", params={"days": 30}).json()
    check(st["days"] == 30 and st["rated"] == 30 and sum(st["dist"].values()) == 30 and st["period"] == "week" and st["series"], f"{who}: stats 30 {st}")
    check(abs(st["avg"] - 3.0) < 0.01, f"{who}: average {st['avg']}")
    st3 = s.get(B + "/api/life/journal/stats", params={"days": 365}).json()
    check(st3["period"] == "month" and st3["rated"] == 41, f"{who}: stats 365 {st3['rated']}")
    check(s.get(B + "/api/life/journal/stats", params={"days": 7}).status_code == 400, f"{who}: days 7 = 400")
    check(s.get(B + "/api/life/journal/stats").json()["days"] == 30, f"{who}: default 30")
    # export
    r = s.get(B + "/api/life/journal/export", params={"format": "csv"})
    check(r.ok and "text/csv" in r.headers["Content-Type"] and "journal.csv" in r.headers["Content-Disposition"], f"{who}: csv headers")
    lines = r.text.lstrip("﻿").splitlines()
    check(lines[0].startswith("Date,Mood,Text") and len(lines) == 42, f"{who}: csv rows {len(lines)}")
    check(not any(x.split(",", 2)[-1].startswith(("=", "+", "-", "@")) for x in lines[1:]) and "'=cmd" in r.text, f"{who}: formula defused")
    check(lines[1].startswith(day(50)), f"{who}: csv oldest first")
    r = s.get(B + "/api/life/journal/export", params={"from": day(3), "to": day(1)})
    check(r.ok and "journal.md" in r.headers["Content-Disposition"] and r.text.startswith("# Journal") and f"## {day(2)} (" in r.text
          and day(0) not in r.text and day(4) not in r.text, f"{who}: markdown range " + r.text[:100])
    check(s.get(B + "/api/life/journal/export", params={"from": "x"}).status_code == 400, f"{who}: export bad date = 400")


suite(A, "alice")
# privacy: bob sees nothing of alice
check(Bo.get(B + "/api/life/journal").json()["entries"] == [], "bob sees no journal of alice")
check(Bo.get(B + "/api/life/journal/export", params={"format": "csv"}).text.lstrip("﻿").strip().count("\n") == 0, "bob's export is empty")
check(requests.get(B + "/api/life/journal", headers=H).status_code in (401, 403), "signed out: refused")
# freelancer-matrix: personal - a person without an organisation uses all three
FID, Fr = freelancer(B, A, "frida")
suite(Fr, "frida")

# ================================================================ #2135 habits
def habit(s, **b):
    r = s.post(B + "/api/habits", json={"name": "Stretch", **b})
    assert r.ok, r.text
    return r.json()["id"]


def get(s, hid):
    return next(h for h in s.get(B + "/api/state").json()["habits"] if h["id"] == hid)


h1 = habit(A, remind_times=["20:00", "08:00", "13:30", "08:00"])
g = get(A, h1)
check(g["remind_times"] == "08:00,13:30,20:00" and g["remind_at"] == "08:00", f"sorted, unique, first time kept in remind_at: {g['remind_times']} {g['remind_at']}")
h2 = habit(A, remind_at="07:15")  # an older client
g = get(A, h2)
check(g["remind_times"] == "07:15" and g["remind_at"] == "07:15", f"old client: both set {g['remind_times']}")
check(A.patch(B + f"/api/habits/{h2}", json={"remind_times": ["07:15", "21:00"]}).ok and get(A, h2)["remind_times"] == "07:15,21:00", "patch adds a time")
check(A.patch(B + f"/api/habits/{h2}", json={"remind_at": "06:00"}).ok and get(A, h2)["remind_times"] == "06:00", "an old client's patch replaces the list")
check(A.patch(B + f"/api/habits/{h2}", json={"remind_times": []}).ok and get(A, h2)["remind_times"] == "" and get(A, h2)["remind_at"] == "", "empty list = off")
check(A.patch(B + f"/api/habits/{h2}", json={"name": "Stretch 2"}).ok and get(A, h1)["remind_times"] == "08:00,13:30,20:00", "other fields leave the times alone")
seven = [f"{8 + i:02}:00" for i in range(7)]
r = A.patch(B + f"/api/habits/{h1}", json={"remind_times": seven})
check(r.status_code == 400 and get(A, h1)["remind_times"] == "08:00,13:30,20:00", f"seven times = 400, nothing stored ({r.status_code})")
check(A.patch(B + f"/api/habits/{h1}", json={"remind_times": ["25:00"]}).status_code == 400, "invalid time = 400")
check(A.patch(B + f"/api/habits/{h1}", json={"remind_times": "x"}).status_code == 400, "no list = 400")
check(A.patch(B + f"/api/habits/{h1}", json={"remind_times": [f"{8 + i:02}:00" for i in range(6)]}).ok, "six times are fine")
# API v1 (token)
tok = A.post(B + "/api/me/tokens", json={"name": "c-test", "scopes": ["read", "tasks:write"]}).json().get("token")
if tok:
    V = {"Authorization": "Bearer " + tok}
    r = requests.post(B + "/api/v1/habits", headers=V, json={"name": "Read", "remind_times": ["09:00", "21:00"]})
    check(r.status_code == 201 and r.json()["remind_times"] == ["09:00", "21:00"] and r.json()["remind_at"] == "09:00", f"v1 create {r.status_code} {r.text[:200]}")
    hid = r.json()["id"]
    r = requests.patch(B + f"/api/v1/habits/{hid}", headers=V, json={"remind_times": ["10:00"]})
    check(r.ok and r.json()["remind_times"] == ["10:00"], "v1 patch " + r.text[:200])
    r = requests.get(B + "/api/v1/habits", headers=V)
    check(r.ok and all("remind_times" in x for x in r.json()["data"]), "v1 list carries remind_times")
    spec = requests.get(B + "/api/v1/openapi.json").json()
    check("remind_times" in spec["components"]["schemas"]["Habit"]["properties"], "OpenAPI: Habit.remind_times")
else:
    check(False, "no API token for the v1 checks")
# a person without an organisation (freelancer-matrix: time)
fh = habit(Fr, remind_times=["07:00", "19:00"])
check(get(Fr, fh)["remind_times"] == "07:00,19:00", "freelancer: several times")

print(f"p2140_c_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
