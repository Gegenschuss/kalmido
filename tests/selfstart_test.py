#!/usr/bin/env python3
"""2.180.0 C (#2695): guard of tests/selfstart.txt - the suites that start their OWN fresh container first thing.
run_all.sh's `fresh` starts a container lazily: right before the first suite of the group that really runs. A suite named
in selfstart.txt calls start.sh itself before its first request, so run_all.sh only removes the old container for it
(no second start, ~1 container start saved per group). A suite qualifies when, statically:
 - its file has no KEEP (KEEP=1 = it relies on the container / data before it), and
 - its FIRST start.sh call is a top-level statement: JS `execFileSync('bash', [path.join(__dirname, 'start.sh') …` at
   column 0, optionally behind `if (!process.env.X_NOSTART …)` / `if (process.env.X_NOSTART !== '1')`; Python
   `subprocess.run(["bash", os.path.join(N, "start.sh") …` at column 0 or right under `if not os.environ.get("X_NOSTART"):`
   (X_NOSTART = any variable ending in NOSTART; run_all.sh and the CI set none), and
 - no top-level statement before it talks to the server (JS: nothing awaited / no async IIFE; Python: no requests / login).
A suite that does not start its container anyway fails loudly (no container), never runs on the old one.
No container. usage: selfstart_test.py [--list]   (--list: print every qualifying suite of run_all.sh = the new file)"""
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
RUN = re.compile(r'^\s*(?:now [^;]*;\s*)?(?:fresh;\s*)?run (\S+) (?:node|"\$PY") (\S+)')
JS_START = re.compile(r"""^(?:if \((?:!process\.env\.\w*NOSTART(?: && !process\.env\.\w*NOSTART)*|process\.env\.\w*NOSTART !== '1')\) )?"""
                      r"""execFileSync\('bash', \[path\.join\(__dirname, 'start\.sh'\)""")
PY_START = re.compile(r"""^(?:\w+ = )?subprocess\.run\(\["bash", os\.path\.join\(N, "start\.sh"\)""")
PY_GUARD = re.compile(r"""^if not os\.environ\.get\(["']\w*NOSTART["']\):\s*$""")
JS_TALK = re.compile(r"^\(async|^(?:fetch|boot|login|call|api|v1)\s*\(")  # CommonJS: no top-level await
PY_TALK = re.compile(r"requests\.|urlopen|\bsess\(|\blogin\(|\.(?:get|post|put|patch|delete)\(B")


def suites():
    with open(os.path.join(N, "run_all.sh"), encoding="utf-8") as f:
        for line in f:
            m = RUN.match(line)
            if m:
                yield m.group(1), m.group(2)


def code_lines(path):
    """The lines of the file without the module docstring / leading comment block (they name start.sh in prose)."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    if path.endswith(".py"):
        src = "\n".join(lines)
        m = re.match(r'(#![^\n]*\n)?\s*("""|\'\'\')', src)
        if m:
            end = src.find(m.group(2), m.end())
            skip = src[:end].count("\n") + 1
            return [(i, "" if i < skip else x) for i, x in enumerate(lines)]
    return list(enumerate(lines))


def qualifies(fname):
    """None = qualifies, else the reason it does not."""
    path = os.path.join(N, fname)
    if not os.path.exists(path):
        return "no file"
    lines = code_lines(path)
    js = fname.endswith(".js")
    strip = (lambda x: x.split("//")[0]) if js else (lambda x: x.split("#")[0])
    if any("KEEP" in strip(x) for _, x in lines):
        return "uses KEEP"
    first = next((i for i, x in lines if "start.sh" in strip(x)), None)
    if first is None:
        return "no start.sh call"
    x = lines[first][1]
    if js:
        if not JS_START.match(x):
            return "first start.sh call is not a top-level statement"
        before = [y for _, y in lines[:first] if y and not y[0].isspace() and not y.startswith(("//", "}", ")"))]
        if any(JS_TALK.match(y) for y in before):
            return "talks to the server before start.sh"
    else:
        if not PY_START.match(x.strip()):
            return "first start.sh call is not subprocess.run(start.sh)"
        if x[0].isspace():
            prev = next((y for _, y in reversed(lines[:first]) if y.strip()), "")
            if not PY_GUARD.match(prev) or len(x) - len(x.lstrip()) != 4:
                return "start.sh call is inside a function or condition"
        before = [y for _, y in lines[:first] if y and not y[0].isspace() and not y.startswith(("#", "def ", "class ", "@"))]
        if any(PY_TALK.search(y) for y in before):
            return "talks to the server before start.sh"
    return None


def main():
    all_suites = list(suites())
    if "--list" in sys.argv:
        print("# 2.180.0 C (#2695): suites that start their own fresh container first thing (tests/selfstart_test.py --list)")
        print("# run_all.sh skips the start of `fresh` for them; tests/selfstart_test.py guards every line")
        for name, fname in all_suites:
            if qualifies(fname) is None:
                print(name)
        return 0
    files = dict(all_suites)
    with open(os.path.join(N, "selfstart.txt"), encoding="utf-8") as f:
        listed = [x.strip() for x in f if x.strip() and not x.startswith("#")]
    fails, ok = [], 0
    for name in listed:
        why = "not in run_all.sh" if name not in files else qualifies(files[name])
        if why:
            fails.append(f"{name}: {why}")
            print("FAIL:", name, why)
        else:
            ok += 1
    if len(set(listed)) != len(listed):
        fails.append("names twice")
        print("FAIL: a name is listed twice")
    print(f"selfstart: {ok} ok, {len(fails)} failed ({len(listed)} suites start their own container)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
