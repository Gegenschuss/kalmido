#!/usr/bin/env python3
"""2.192.0 C (#2514): new Python suites use the shared helpers of tests/kt.py instead of their own copies.

A tests/*.py file that defines its own top-level check() / sess() / until() is an error, unless it stands in
tools/kt_legacy.txt (the suites from before kt.py, frozen on 23.10.2026). Moving a suite to kt.py = delete its line there;
the list only shrinks. Runs inside tools/check_layout.py (CI lint) and on its own:

usage: python3 tools/check_kt.py            exit code 1 on a new suite with its own helpers (a stale list line only warns)
       python3 tools/check_kt.py --update   add today's offenders to the list (only once for suites of releases built in
                                            parallel before this guard was merged)
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY = os.path.join(ROOT, "tools", "kt_legacy.txt")
OWN = re.compile(r"^(?:async\s+)?def\s+(check|sess|until)\s*\(|^(check|sess|until)\s*=\s*lambda\b", re.M)


def offenders():
    """{file name: sorted helper names} of the tests/*.py files with their own top-level helpers (kt.py itself aside)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "tests", "*.py"))):
        n = os.path.basename(p)
        if n == "kt.py":
            continue
        with open(p, encoding="utf-8") as f:
            names = {a or b for a, b in OWN.findall(f.read())}
        if names:
            out[n] = sorted(names)
    return out


def legacy():
    if not os.path.exists(LEGACY):
        return set()
    with open(LEGACY, encoding="utf-8") as f:
        return {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}


def errors():
    off, old = offenders(), legacy()
    errs = [f"ERROR: tests/{n}: defines its own {', '.join(h + '()' for h in hs)} -- import them from kt (tests/kt.py)"
            for n, hs in off.items() if n not in old]
    warns = [f"WARNING: tools/kt_legacy.txt: {n} is gone or uses kt now -- delete its line" for n in sorted(old - set(off))]
    return errs, warns


def main():
    if "--update" in sys.argv:
        names = sorted(legacy() | set(offenders()))
        with open(LEGACY + ".new", "w", encoding="utf-8") as f:
            f.write("# Python suites with their own check()/sess()/until() from before tests/kt.py (tools/check_kt.py).\n"
                    "# Frozen 2.192.0 (#2514): delete a line when its suite moves to kt.py, never add new suites here.\n")
            f.write("".join(n + "\n" for n in names))
        os.replace(LEGACY + ".new", LEGACY)
        print(f"check_kt: {len(names)} legacy suites")
        return 0
    errs, warns = errors()
    for e in errs + warns:
        print(e)
    print(f"check_kt: {len(offenders())} suites with own helpers, {len(legacy())} on the legacy list, {len(errs)} error(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
