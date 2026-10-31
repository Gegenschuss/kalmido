#!/usr/bin/env python3
"""A git merge driver for line lists where order does not matter: tests/skip.txt, tests/selfstart.txt (2.358.0, #3394).

git's own `merge=union` keeps the lines of BOTH sides of a conflicting hunk - a line one side deleted came back when the other
side deleted a neighbour (2.358: two parts each took their fixed suites off tests/skip.txt, after the merge all were back).
Here a three-way merge of the line set: a line of the base that one side deleted stays deleted, a new line of either side is
kept (ours in their place, theirs appended), nothing is ever a conflict.

  python3 tools/lines_merge.py %O %A %B     the driver (.gitattributes `merge=lines`), writes the result into %A
  python3 tools/lines_merge.py --selftest
Register once per clone (worktrees share it): tools/git_setup.sh
Python standard library only.
"""
import sys


def merge(base, ours, theirs):
    """The merged text of three versions of a line list."""
    o, b = set(base.splitlines()), set(theirs.splitlines())
    out = [ln for ln in ours.splitlines() if ln not in o or ln in b]  # ours, minus what theirs deleted
    have = set(out)
    for ln in theirs.splitlines():  # + what theirs added
        if ln not in o and ln not in have:
            out.append(ln); have.add(ln)
    return "\n".join(out) + "\n" if out else ""


def selftest():
    base = "# c\na 1\nb 2\nc 3\nd 4\n"
    cases = [
        (base, "# c\nc 3\nd 4\n", "# c\na 1\nb 2\nd 4\n", "# c\nd 4\n"),          # both delete neighbours: all stay deleted
        (base, base + "p1 5\n", base + "p2 6\n", base + "p1 5\np2 6\n"),           # both add: both kept, ours first
        (base, base.replace("b 2", "b 9"), base + "e 5\n", base.replace("b 2", "b 9") + "e 5\n"),  # a changed line + an added one
        (base, base, "", ""),                                                     # theirs empties the list
    ]
    bad = [(i, merge(*c[:3])) for i, c in enumerate(cases) if merge(*c[:3]) != c[3]]
    print("lines_merge selftest:", "ok" if not bad else f"FAILED {bad}")
    return 1 if bad else 0


def main(argv):
    if argv[1:] == ["--selftest"]:
        return selftest()
    if len(argv) != 4:
        print(__doc__.strip())
        return 2
    rd = lambda p: open(p, encoding="utf-8").read()  # noqa: E731
    text = merge(rd(argv[1]), rd(argv[2]), rd(argv[3]))
    with open(argv[2], "w", encoding="utf-8") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
