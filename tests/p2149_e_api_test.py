#!/usr/bin/env python3
"""2.149.0 API tests, part E (#2512 #2513 #2514): the test clock reaches the server, the shared helpers in tests/kt.py.
freelancer-matrix: tasks
 - kt.py: until() returns the first truthy value at once, gives up after its timeout with the last value (no fixed sleeps)
 - a server without KALMIDO_TEST_NOW runs at the real time: a task completed by a person without an organisation carries the
   real time, the log says nothing about a test clock
 - KALMIDO_TEST_NOW=2026-10-18T23:30:00Z (Saturday 23:30 UTC = Sunday 01:30 in Berlin, the night case of the CI flakes):
   the completion time is that instant (the clock runs on from it: a later completion is later), the statistics count it on
   the Berlin day 2026-10-19, the start-up log warns about the shifted clock, testclock in the suite agrees with the server
 - KALMIDO_TEST_NOW without KALMIDO_TEST=1 is ignored (real time, a warning in the log): a server outside the tests cannot
   be moved in time by one variable
usage: p2149_e_api_test.py <datadir>   (P2149E_NOSTART=1 / KMT_NOSTART=1: the container runs already - only the real-time part)"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
import testclock  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, check, until  # noqa: E402

NIGHT = "2026-10-18T23:30:00Z"
CLOCK_VARS = ("KALMIDO_TEST_NOW", "KALMIDO_TEST_NOW_AT")


def start(now=None, extra=None):
    """A fresh container: at the real time (now=None) or with KALMIDO_TEST_NOW=now (start.sh passes it on)."""
    for k in CLOCK_VARS:
        os.environ.pop(k, None)
    if now:
        os.environ["KALMIDO_TEST_NOW"], os.environ["KALMIDO_TEST_NOW_AT"] = now, str(int(time.time()))
    return kt.fresh(env=extra, prefix="P2149E")


def completed(s, title):
    """Create and complete a task -> its stored completion time (aware datetime)."""
    tid = s.post(B + "/api/tasks", json={"title": title}).json()["id"]
    r = s.post(B + f"/api/tasks/{tid}/complete", json={})
    assert r.ok, r.text
    v = kt.dbx("SELECT completed_at FROM tasks WHERE id=?", (tid,))[0][0]
    d = datetime.fromisoformat(str(v))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def near(a, b, secs=120):
    return abs((a - b).total_seconds()) <= secs


# ---- kt.py
t0 = time.monotonic()
check(until(lambda: 5, 3) == 5 and time.monotonic() - t0 < 1, "kt.until: a truthy value at once")
t0 = time.monotonic()
check(until(lambda: 0, 0.6, 0.1) == 0 and 0.5 <= time.monotonic() - t0 < 3, "kt.until: gives up after the timeout with the last value")
n = [0]
check(until(lambda: n.__setitem__(0, n[0] + 1) or n[0] >= 3, 5, 0.05) is True and n[0] == 3, "kt.until: polls until the state holds")

# ---- the real time (no KALMIDO_TEST_NOW)
started = start()
A = kt.setup()
FID, Fr = freelancer(B, A)  # freelancer-matrix: tasks (the completion time of a private task)
real = completed(Fr, "Real time")
check(near(real, datetime.now(timezone.utc)), f"no test clock: the completion carries the real time ({real})")
if started:
    check("test clock" not in logs(), "no test clock: nothing about it in the log")

if started:
    # ---- the night case: Saturday 23:30 UTC = Sunday 01:30 in Berlin
    start(NIGHT)
    A = kt.setup()
    FID, Fr = freelancer(B, A)
    want = datetime.fromisoformat(NIGHT.replace("Z", "+00:00"))
    c1 = completed(Fr, "Night 1")
    check(near(c1, want), f"KALMIDO_TEST_NOW: the completion time is the test instant ({c1}, wanted {want})")
    check(near(c1, testclock.now()), f"testclock in the suite agrees with the server ({c1} / {testclock.now()})")
    time.sleep(1.2)
    c2 = completed(Fr, "Night 2")
    check(c2 > c1 and c2 - c1 < timedelta(seconds=60), f"the test clock runs on ({c1} -> {c2})")
    st = Fr.get(B + "/api/stats").json()
    per = (st.get("done") or {}).get("per_day") or {}
    check(per.get("2026-10-19") == 2 and "2026-10-18" not in per, f"the statistics count on the Berlin day 2026-10-19 {per}")
    check((st.get("done") or {}).get("today") == 2, f"... and as today {st.get('done', {}).get('today')}")
    check("WARNING test clock" in logs(), "the start-up log warns about the shifted clock")

    # ---- KALMIDO_TEST_NOW without KALMIDO_TEST=1 is ignored (EXTRA comes after start.sh's own -e: the last one counts)
    start(NIGHT, {"KALMIDO_TEST": "0"})
    A = kt.setup()
    FID, Fr = freelancer(B, A)
    c3 = completed(Fr, "Ignored")
    check(near(c3, datetime.now(timezone.utc)), f"without KALMIDO_TEST=1 the variable is ignored: real time ({c3})")
    check("KALMIDO_TEST_NOW is ignored" in logs(), "... and the log says so")
    for k in CLOCK_VARS:
        os.environ.pop(k, None)

sys.exit(kt.done("p2149_e_api"))
