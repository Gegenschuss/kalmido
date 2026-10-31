#!/usr/bin/env python3
"""tests/skip.txt well formed and not expired (#1315, CI lint step). Every line: <suite of run_all.sh> <YYYY-MM-DD> #<task> <evidence>;
the date at most 14 days ahead (Berlin). A date in the past = red: run_all.sh runs that suite again, fix it and delete the line.
Python standard library only."""
import datetime
import os
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
LINE_RE = re.compile(r"^(\w+) (\d{4}-\d\d-\d\d) #(\d+) \S")


def problems(text, suites, today):
    out, seen = [], set()
    for no, ln in enumerate(text.splitlines(), 1):
        if not ln.strip() or ln.startswith("#"):
            continue
        m = LINE_RE.match(ln)
        if not m:
            out.append(f"line {no}: not '<suite> <YYYY-MM-DD> #<task> <evidence>': {ln}")
            continue
        s, day = m.group(1), datetime.date.fromisoformat(m.group(2))
        if s not in suites:
            out.append(f"line {no}: {s} is no suite of run_all.sh")
        if s in seen:
            out.append(f"line {no}: {s} twice")
        seen.add(s)
        if day < today:
            out.append(f"line {no}: {s} expired on {day} - fix it (task #{m.group(3)}) and delete the line")
        elif (day - today).days > 14:
            out.append(f"line {no}: {s} until {day} - at most 14 days ahead")
    return out


def main():
    sys.path.insert(0, HERE)
    import suites as _suites  # 2.321 (#1368): the suite list (suites.txt + marker files)
    suites = {n for _, n, _ in _suites.rows(HERE)}
    today = datetime.datetime.now(ZoneInfo("Europe/Berlin")).date()
    d = datetime.date(2026, 10, 25)
    t = "# c\napi 2026-11-01 #1 CI v1\nui 2026-10-24 #2 x\nnone 2026-10-26 #3 x\napi 2026-10-30 #4 x\nui 2026-12-01 #5 x\nui 2026-10-30\n"
    want = ["line 3: ui expired", "line 4: none is no", "line 5: api twice", "line 6: ui twice", "line 6: ui until", "line 7: not"]
    got = problems(t, {"api", "ui"}, d)
    bad = [w for w in want if not any(g.startswith(w) for g in got)] + ([] if len(got) == len(want) else [f"{len(got)} problems"])
    if bad:
        print("skip_test: self check failed:", bad, got)
        return 1
    # 2.358.0 (#3281): ONLY with an unknown suite is an error (exit 2), not "ALL SUITES PASSED"; a known one is listed (list mode: no container)
    env = dict(os.environ, KALMIDO_LIST_ONLY="1")
    for only, rc, txt in (("no_such_suite_3281", 2, "unknown suite no_such_suite_3281"), ("backup", 0, "ALL SUITES PASSED")):
        r = subprocess.run(["bash", os.path.join(HERE, "run_all.sh")], env=dict(env, ONLY=only), capture_output=True, text=True, timeout=120)
        if r.returncode != rc or txt not in r.stdout:
            print(f"skip_test: run_all.sh ONLY={only}: exit {r.returncode}, want {rc} and {txt!r}:", r.stdout[-300:], r.stderr[-300:])
            return 1
    out = problems(open(os.path.join(HERE, "skip.txt")).read(), suites, today)
    for x in out:
        print("tests/skip.txt " + x)
    n = sum(1 for ln in open(os.path.join(HERE, "skip.txt")) if ln.strip() and not ln.startswith("#"))
    print(f"skip_test: {n} suite(s) skipped, {len(out)} problem(s)")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
