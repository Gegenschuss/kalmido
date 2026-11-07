#!/usr/bin/env python3
"""junit.py - the JUnit XML report of one suite (2.625 D, #4005). tests/run_all.sh calls it after every suite; the CI uploads the
folder per shard (artifact junit-shard-N, ci.yml) and the flaky detection of the release tooling reads it (which suite, which
case red). Standard library only; the suite's own output (FAIL lines, summary line) stays as it is.

    python3 tests/junit.py <dir> <suite> <rc> <ms> [<steps file>] < output     -> <dir>/<suite>.xml
    python3 tests/junit.py --skipped <dir> <suite> <reason>                    -> a report with one skipped case

The cases: the steps file (tests/kt.py check() writes one line per check, "ok\\t<what>" / "fail\\t<what>", when run_all.sh
sets KALMIDO_JUNIT_STEPS) gives one case per check; without it every "FAIL..." line of the output is a failed case and the
passed checks are one case "<suite>: N checks passed" (the count from the summary line "<name>: N ok, M failed" / "N passed").
A suite with a non-zero exit code and no FAIL line gets one failed case "<suite>" with the end of its output."""
import os
import re
import sys
import time
from xml.sax.saxutils import quoteattr, escape

SUMMARY = re.compile(r"(\d+) (?:ok|passed)\b")
MAX_CASES = 2000  # a suite checking in a loop: the passed ones beyond this are counted, not listed
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean(s: str) -> str:
    return CTRL.sub("?", s)


def cases_of(out: str, rc: int, suite: str, steps: str | None = None) -> list[tuple[str, str | None]]:
    """[(name, failure text or None)] of a suite's run."""
    cases: list[tuple[str, str | None]] = []
    lines = out.split("\n")
    if steps:
        oks = 0
        for ln in steps.split("\n"):
            kind, _, what = ln.partition("\t")
            if kind == "ok":
                if sum(1 for c in cases if c[1] is None) < MAX_CASES:
                    cases.append((what or "check", None))
                else:
                    oks += 1
            elif kind == "fail":
                cases.append((what or "check", what or "failed"))
        if oks:
            cases.append((f"{suite}: {oks} more checks passed", None))
        # a FAIL line the steps do not hold (the suite's own check copy, a crash message) still is a failed case
        known = {" ".join(c[1].split())[:300] for c in cases if c[1] is not None}
        for ln in lines:
            what = re.sub(r"^FAIL(?:ED)?:?\s*", "", ln).strip()
            if ln.startswith("FAIL") and not any(k.startswith(" ".join(what.split())[:300]) for k in known):
                cases.append((what[:300] or suite, ln))
    else:
        for ln in lines:
            if ln.startswith("FAIL"):
                what = re.sub(r"^FAIL(?:ED)?:?\s*", "", ln).strip()
                cases.append((what[:300] or suite, ln))
        n = 0
        for ln in reversed(lines):
            m = SUMMARY.search(ln)
            if m and ("failed" in ln or ln.startswith(suite) or " ok" in ln):
                n = int(m.group(1))
                break
        if n or not cases:
            cases.append((f"{suite}: {n} checks passed" if n else suite, None))
    if rc != 0 and not any(c[1] is not None for c in cases):
        tail = "\n".join(x for x in lines if x.strip())[-3000:]
        cases.append((suite, f"exit {rc}\n{tail}"))
    return cases


def xml_of(suite: str, cases: list[tuple[str, str | None]], seconds: float, skipped: str | None = None) -> str:
    fails = sum(1 for c in cases if c[1] is not None)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuite name={quoteattr(suite)} tests="{len(cases) or 1}" failures="{fails}" errors="0" '
           f'skipped="{1 if skipped is not None else 0}" time="{seconds:.3f}" timestamp="{stamp}">']
    if skipped is not None:
        out.append(f'  <testcase classname={quoteattr(suite)} name={quoteattr(suite)} time="0"><skipped message={quoteattr(_clean(skipped))}/></testcase>')
    for name, fail in cases:
        attrs = f'classname={quoteattr(suite)} name={quoteattr(_clean(name))}'
        if fail is None:
            out.append(f'  <testcase {attrs}/>')
        else:
            first = _clean(fail.split("\n", 1)[0])[:500]
            out.append(f'  <testcase {attrs}><failure message={quoteattr(first)}>{escape(_clean(fail))}</failure></testcase>')
    out.append("</testsuite>")
    return "\n".join(out) + "\n"


def write(d: str, suite: str, text: str) -> None:
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".{suite}.xml.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, os.path.join(d, f"{suite}.xml"))


def main(a: list[str]) -> int:
    if a[:1] == ["--skipped"] and len(a) >= 3:
        write(a[1], a[2], xml_of(a[2], [], 0.0, skipped=a[3] if len(a) > 3 else "skipped"))
        return 0
    if len(a) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    d, suite, rc, ms = a[0], a[1], int(a[2] or 0), int(a[3] or 0)
    steps = None
    if len(a) > 4 and a[4] and os.path.isfile(a[4]):
        with open(a[4], encoding="utf-8", errors="replace") as f:
            steps = f.read().strip("\n") or None
    out = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    write(d, suite, xml_of(suite, cases_of(out, rc, suite, steps), ms / 1000.0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
