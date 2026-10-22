"""2.85.0 (#1863): the test clock gives the Berlin calendar day (Python and Node), also around midnight and the DST change."""
import os
import subprocess
import sys
from datetime import timezone

import testclock

HERE = os.path.dirname(os.path.abspath(__file__))
ok, F = 0, []
CASES = [("2026-10-17T22:30:00Z", "2026-10-18", "2026-10-19"), ("2026-10-17T21:59:00Z", "2026-10-17", "2026-10-18"),
         ("2026-12-31T23:30:00Z", "2027-01-01", "2027-01-02"), ("2026-12-31T22:59:00Z", "2026-12-31", "2027-01-01"),
         ("2026-10-24T22:30:00Z", "2026-10-25", "2026-10-26")]
for inst, today, tomorrow in CASES:
    os.environ["KALMIDO_TEST_NOW"] = inst
    py = testclock.today().isoformat()
    js = subprocess.run(["node", "-e", "const c = require('./testclock'); console.log(c.today(), c.day(1))"], cwd=HERE, capture_output=True, text=True, env=os.environ).stdout.split()
    for what, got, want in (("py today", py, today), ("js today", js[0] if js else "", today), ("js tomorrow", js[1] if len(js) > 1 else "", tomorrow)):
        if got == want:
            ok += 1
        else:
            F.append(f"{inst} {what}: {got} != {want}")
            print("FAIL:", F[-1])
os.environ["KALMIDO_TEST_NOW"] = "2026-10-17T22:30:00Z"  # Saturday evening UTC = Sunday 18 Oct in Berlin (CEST): the week started Monday 12 Oct
w = subprocess.run(["node", "-e", "console.log(require('./testclock').weekStart())"], cwd=HERE, capture_output=True, text=True, env=os.environ).stdout.strip()
if w == "2026-10-12":
    ok += 1
else:
    F.append(f"weekStart {w}")
    print("FAIL:", F[-1])
# 2.180.0 B (#2693): dayStart / day_start = 00:00 Berlin of the test day (CET, CEST and the 25-hour day of the October change)
for inst, want in (("2026-10-31T23:30:00Z", "2026-10-31T23:00:00.000Z"), ("2026-07-01T00:30:00+02:00", "2026-06-30T22:00:00.000Z"),
                   ("2026-10-25T22:30:00Z", "2026-10-24T22:00:00.000Z")):
    os.environ["KALMIDO_TEST_NOW"] = inst
    js = subprocess.run(["node", "-e", "console.log(require('./testclock').dayStart().toISOString())"], cwd=HERE, capture_output=True, text=True, env=os.environ).stdout.strip()
    py = testclock.day_start().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for what, got in (("js dayStart", js), ("py day_start", py)):
        if got == want:
            ok += 1
        else:
            F.append(f"{inst} {what}: {got} != {want}")
            print("FAIL:", F[-1])
print(f"testclock: {ok} ok, {len(F)} failed")
sys.exit(1 if F else 0)
