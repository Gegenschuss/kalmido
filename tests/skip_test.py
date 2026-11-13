#!/usr/bin/env python3
"""tests/skip.txt well formed (#1315, CI lint step). Every line: <suite of run_all.sh> <YYYY-MM-DD> #<task> <evidence>.
#4314 (Karte 17345): skip.txt is the QUARANTINE of proven flaky suites (tests/run_all.sh runs them, their red does not count) - the
date (when the line came) no longer ends it and is never red: a line goes with the fix (its task) or when the train has seen the
suite green often enough in a row. A line of a never-quiet suite (tests/quarantine_never.txt: rights, encryption, login,
invoices) is a note: run_all.sh ignores it, the suite counts as always.
Python standard library only."""
import fnmatch
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
        s = m.group(1)
        datetime.date.fromisoformat(m.group(2))  # a real date (ValueError = the line is broken)
        if s not in suites:
            out.append(f"line {no}: {s} is no suite of run_all.sh")
        if s in seen:
            out.append(f"line {no}: {s} twice")
        seen.add(s)
        # #4314: the date (day) ends nothing any more - quarantine; it only says when the line came
    return out


def never_quiet(text, never):
    """#4314: the lines of suites that never go quiet (patterns of tests/quarantine_never.txt) - a note, run_all.sh ignores them."""
    pats = [p.strip() for p in never.splitlines() if p.strip() and not p.strip().startswith("#")]
    return [ln.split()[0] for ln in text.splitlines() if ln.strip() and not ln.startswith("#")
            and any(fnmatch.fnmatchcase(ln.split()[0], p) for p in pats)]


def main():
    sys.path.insert(0, HERE)
    import suites as _suites  # 2.321 (#1368): the suite list (suites.txt + marker files)
    suites = {n for _, n, _ in _suites.rows(HERE)}
    today = datetime.datetime.now(ZoneInfo("Europe/Berlin")).date()
    d = datetime.date(2026, 10, 25)
    t = "# c\napi 2026-11-01 #1 CI v1\nui 2026-10-24 #2 x\nnone 2026-10-26 #3 x\napi 2026-10-30 #4 x\nui 2026-12-01 #5 x\nui 2026-10-30\n"
    want = ["line 4: none is no", "line 5: api twice", "line 6: ui twice", "line 7: not"]  # #4314: no expiry, no 14 days
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
    if never_quiet("a 2026-01-01 #1 x\np_rights_ui 2026-01-01 #2 x\n", "# c\n*rights*\n") != ["p_rights_ui"]:
        print("skip_test: self check of never_quiet failed")
        return 1
    text = open(os.path.join(HERE, "skip.txt")).read()
    out = problems(text, suites, today)
    for x in out:
        print("tests/skip.txt " + x)
    nq_file = os.path.join(HERE, "quarantine_never.txt")
    for x in never_quiet(text, open(nq_file).read() if os.path.exists(nq_file) else ""):
        print(f"note: tests/skip.txt names {x}, a never-quiet suite (tests/quarantine_never.txt) - run_all.sh counts it as always")
    n = sum(1 for ln in text.splitlines() if ln.strip() and not ln.startswith("#"))
    print(f"skip_test: {n} suite(s) in quarantine, {len(out)} problem(s)")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
