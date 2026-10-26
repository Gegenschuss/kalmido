#!/usr/bin/env python3
"""The suite list of Kalmido's test run (2.321, #1368 - Allison #1304 Änderung 3: no hand-kept list that every package appends to).

A suite is a file tests/<name>_test.py (python) or tests/<name>.js / tests/<name>_test.js (node) with a marker line in its
first 15 lines:

    # kalmido-suite: [fresh] [after=<suite>] [now=<spec>|now=real] [nodata]      (python)
    // kalmido-suite: ...                                                         (node)

  fresh        its own group: a fresh container is started before it (the default, so the bare marker is enough)
  after=X      no own container: it runs in the group of suite X, right after X (and after earlier after=X suites, by name)
  now=wed10:00 the group's test time (tests/run_all.sh `now ...`: an ISO instant, HH:MM, mon..sun HH:MM, or real); only
               meaningful with fresh
  nodata       the suite takes no data folder argument (default: "$KALMIDO_TEST_DATA" is passed)

The suites that existed before the marker stand in tests/suites.txt with the old run_all.sh line syntax
(`[now ...; ]fresh; run <name> <command>` / `       run <name> <command>` = same group as the line before); a new suite
needs NO line anywhere - the marker is enough, it gets its own group at the end (or joins X's group). The order: suites.txt
first, then the discovered groups by name. tests/run_all.sh, tools/shards.py, tests/stages.py and the Mac runner all read
the list through this module, so every tool sees the same groups.

  python3 tests/suites.py --bash          the run lines for tests/run_all.sh (eval'd there)
  python3 tests/suites.py --list          name, group number and file per suite
  python3 tests/suites.py --file SUITE    the test file of a suite
  python3 tests/suites.py --check         exit 1 when a marker is malformed, a name is taken twice or after= names no suite
Python standard library only.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(HERE, "suites.txt")
FRESH_RE = re.compile(r"^(now [^;]*; *)?fresh;")
RUN_RE = re.compile(r"^(now [^;]*; *)?(fresh;)?[ \t]*run ([A-Za-z0-9_]+) (.*)$")
MARK_RE = re.compile(r"^\s*(?:#|//)\s*kalmido-suite:(.*)$")
FILE_RE = re.compile(r"\s([A-Za-z0-9_./-]+\.(?:py|js))\b")
HELPERS = {"boot.js", "ff.js", "testclock.js", "testclock.py", "kt.py", "dbx.py", "stages.py", "suites.py", "skip_test.py",
           "selfstart_test.py"}


class Suite:
    __slots__ = ("name", "file", "cmd", "fresh", "now", "after", "line", "legacy")

    def __init__(self, name, file, cmd, fresh, now=None, after=None, line=None, legacy=False):
        self.name, self.file, self.cmd, self.fresh, self.now, self.after, self.line, self.legacy = name, file, cmd, fresh, now, after, line, legacy

    def bash(self):
        if self.line is not None:
            return self.line
        pre = (f"now {self.now}; " if self.now else "") + ("fresh; " if self.fresh else "       ")
        return f"{pre}run {self.name} {self.cmd}"


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


SHARD_RE = re.compile(r"^shard ([0-9]+)\b")


def legacy(path=LIST):
    """The suites of tests/suites.txt (old run_all.sh line syntax), in file order; `shard N` marker lines pass through as
    entries without a name (run_all.sh and tools/shards.py read them for runs without a shard plan - the Mac full run)."""
    out = []
    for ln in read(path).splitlines():
        if SHARD_RE.match(ln):
            out.append(Suite(None, None, "", False, line=ln, legacy=True))
            continue
        m = RUN_RE.match(ln)
        if not m:
            continue
        f = FILE_RE.search(" " + m.group(4).split("#")[0])
        now = (m.group(1) or "").strip().rstrip(";").strip()
        out.append(Suite(m.group(3), f.group(1) if f else None, m.group(4), bool(m.group(2)), now[4:] if now else None, line=ln, legacy=True))
    return out


def marker(path):
    """The marker of a test file: (dict of options) or None; a malformed marker = {"error": text}."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = [next(f) for _ in range(15)]
    except StopIteration:
        head = read(path).splitlines()[:15]
    except OSError:
        return None
    for ln in head:
        m = MARK_RE.match(ln)
        if not m:
            continue
        o = {"fresh": True, "nodata": False, "now": None, "after": None}
        for tok in m.group(1).split():
            if tok == "fresh":
                o["fresh"] = True
            elif tok == "nodata":
                o["nodata"] = True
            elif tok.startswith("after="):
                o["after"], o["fresh"] = tok[6:], False
            elif tok.startswith("now="):
                o["now"] = tok[4:].replace("mon", "mon ").replace("tue", "tue ").replace("wed", "wed ").replace("thu", "thu ") \
                    .replace("fri", "fri ").replace("sat", "sat ").replace("sun", "sun ").replace("  ", " ").strip()
            else:
                return {"error": f"{os.path.basename(path)}: unknown word {tok!r} in the kalmido-suite marker"}
        return o
    return None


def discovered(tests_dir=HERE, known=()):
    """[Suite] of the marker files (not in `known`), by name; plus [errors]."""
    out, errs, known = [], [], set(known)
    for fn in sorted(os.listdir(tests_dir)):
        if not fn.endswith((".py", ".js")) or fn in HELPERS or fn.startswith(("fake_", "stub_")):
            continue
        o = marker(os.path.join(tests_dir, fn))
        if o is None:
            continue
        if "error" in o:
            errs.append(o["error"]); continue
        name = re.sub(r"_test$", "", fn.rsplit(".", 1)[0])
        if name in known:
            errs.append(f"{fn}: suite name {name} is taken (tests/suites.txt or another file)"); continue
        known.add(name)
        runner = '"$PY"' if fn.endswith(".py") else "node"
        cmd = f"{runner} {fn}" + ("" if o["nodata"] else ' "$KALMIDO_TEST_DATA"')
        out.append(Suite(name, fn, cmd, o["fresh"], o["now"], o["after"]))
    return out, errs


def all_suites(tests_dir=HERE, list_path=None):
    """Every suite in run order: suites.txt, then the discovered own groups by name; after=X suites sit behind X. -> ([Suite], [errors])."""
    base = legacy(list_path or os.path.join(tests_dir, "suites.txt"))
    disc, errs = discovered(tests_dir, [s.name for s in base])
    order = base + [s for s in disc if not s.after]
    for s in sorted((s for s in disc if s.after), key=lambda s: s.name):
        i = next((i for i, x in enumerate(order) if x.name == s.after), None)
        if i is None:
            errs.append(f"{s.file}: after={s.after} names no suite"); continue
        while i + 1 < len(order) and not order[i + 1].fresh and order[i + 1].after == s.after and order[i + 1].name < s.name:
            i += 1
        order.insert(i + 1, s)
    return order, errs


def groups(tests_dir=HERE, list_path=None):
    """[(first suite, [suites], marker shard)] - the shape tools/shards.py uses (`shard N` lines of suites.txt; 0 = none)."""
    out, cur = [], 1
    for s in all_suites(tests_dir, list_path)[0]:
        if s.name is None:
            cur = int(SHARD_RE.match(s.line).group(1)); continue
        if s.fresh or not out:
            out.append([s.name, [], cur])
        out[-1][1].append(s.name)
    return [tuple(g) for g in out]


def rows(tests_dir=HERE, list_path=None):
    """[(group index from 1, suite, test file or None)] - the shape tests/stages.py uses."""
    out, g = [], 0
    for s in all_suites(tests_dir, list_path)[0]:
        if s.name is None:
            continue
        if s.fresh or g == 0:
            g += 1
        out.append((g, s.name, s.file))
    return out


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    suites, errs = all_suites()
    if "--check" in a or not a:
        names = [s.name for s in suites if s.name]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            errs.append(f"suite names twice: {', '.join(dup)}")
        for e in errs:
            print("suites.py: " + e, file=sys.stderr)
        if not a:
            print(f"{sum(1 for s in suites if s.name)} suites, {len(groups())} groups, {sum(1 for s in suites if not s.legacy)} by marker")
        return 1 if errs else 0
    if "--bash" in a:
        print("\n".join(s.bash() for s in suites))
        return 0
    if "--list" in a:
        for g, n, f in rows():
            print(f"{n} {g} {f or '-'}")
        return 0
    if "--file" in a:
        want = a[a.index("--file") + 1]
        f = next((s.file for s in suites if s.name == want), None)
        print(f or "")
        return 0 if f else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
