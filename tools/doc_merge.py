#!/usr/bin/env python3
"""A git merge driver for the developer docs every core package extends (docs/dev/kern.md; 2.928.0, #5597).

docs/dev/kern.md got 28 commits in three days: each core package adds its paragraph to "4. Saving" or a stage section at
the end. Two packages built side by side add at the same place, git's line merge sees one hunk changed on both sides and
the train's move-up rebase stops - three packages were rebuilt for that on 11.11.2026, every check green.
Here git's own three-way line merge first (git merge-file); only its conflicting hunks are looked at, one by one:
  - both sides only ADDED lines at the same place (the base of the hunk is empty): ours, then theirs - two new paragraphs
  - one side kept the base of the hunk and added before or after it, the other changed it: the change plus the addition
  - anything else (both rewrote the same lines differently, one deleted what the other changed) stays a conflict with the
    usual markers, exit 1 - a real content question for a person, never guessed
A changed line is never dropped and nothing is ever duplicated by the driver beyond what both sides wrote.

  python3 tools/doc_merge.py %O %A %B     the driver (.gitattributes `merge=docs`), writes the result into %A
  python3 tools/doc_merge.py --selftest
Register once per clone (worktrees share it): tools/git_setup.sh
Python standard library only (+ git on the PATH, as for any merge driver).
"""
import os
import subprocess
import sys
import tempfile

M = 7  # git's conflict marker size


def _resolve(base, ours, theirs):
    """The lines of one conflicting hunk, or None (stays a conflict)."""
    if not base:
        return ours + theirs
    n = len(base)
    # one side left the base as it was and only added after / before it, the other changed it: the change + the addition
    if theirs[:n] == base:
        return ours + theirs[n:]
    if theirs[-n:] == base:
        return theirs[:-n] + ours
    if ours[:n] == base:
        return theirs + ours[n:]
    if ours[-n:] == base:
        return ours[:-n] + theirs
    return None


def merge(base, ours, theirs):
    """-> (merged text, number of conflicts left)."""
    with tempfile.TemporaryDirectory(prefix="docmerge-") as d:
        paths = []
        for name, text in (("ours", ours), ("base", base), ("theirs", theirs)):
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            paths.append(p)
        p = subprocess.run(["git", "merge-file", "-p", "--diff3", "-L", "ours", "-L", "base", "-L", "theirs", *paths],
                           capture_output=True, text=True, encoding="utf-8")
    if p.returncode < 0 or p.returncode > 127:
        raise RuntimeError(p.stderr)
    out, left, lines, i = [], 0, p.stdout.splitlines(keepends=True), 0
    while i < len(lines):
        ln = lines[i]
        if not ln.startswith("<" * M + " "):
            out.append(ln)
            i += 1
            continue
        parts, cur, j = {"o": [], "b": [], "t": []}, "o", i + 1
        while j < len(lines) and not lines[j].startswith(">" * M):
            if lines[j].startswith("|" * M + " "):
                cur = "b"
            elif lines[j].rstrip("\n") == "=" * M:
                cur = "t"
            else:
                parts[cur].append(lines[j])
            j += 1
        got = _resolve(parts["b"], parts["o"], parts["t"])
        if got is None:  # back as git writes it without diff3 (the base part left out)
            left += 1
            out += [ln] + parts["o"] + ["=" * M + "\n"] + parts["t"] + [lines[j] if j < len(lines) else ">" * M + " theirs\n"]
        else:
            if got and not got[-1].endswith("\n") and (j + 1) < len(lines):
                got = got[:-1] + [got[-1] + "\n"]
            out += got
        i = j + 1
    return "".join(out), left


def selftest():
    base = "# Core\n\n## 4. Saving\n\nsave text\nc.commit()\n\n## 5. Routes\n\nroutes\n"
    add = lambda text, after, new: text.replace(after, after + new, 1)  # noqa: E731
    cases = [
        # both add a paragraph after c.commit() (the 11.11.2026 conflict): ours, then theirs
        ("same place", base, add(base, "c.commit()\n", "\nA para\n"), add(base, "c.commit()\n", "\nB para\n"),
         add(base, "c.commit()\n", "\nA para\n\nB para\n"), 0),
        # both append a new stage section at the end
        ("both append", base, base + "\n## Stage A\n\nA\n", base + "\n## Stage B\n\nB\n", base + "\n## Stage A\n\nA\n\n## Stage B\n\nB\n", 0),
        # one side rewrites the line the other side adds behind
        ("change + add", base, base.replace("save text", "save text, new"), add(base, "save text\n", "more\n"),
         base.replace("save text\n", "save text, new\nmore\n"), 0),
        # different sections: git alone
        ("apart", base, base.replace("routes", "routes!"), base.replace("save text", "save!"),
         base.replace("routes", "routes!").replace("save text", "save!"), 0),
        # both rewrite the same line differently: a real conflict, markers stay
        ("conflict", base, base.replace("save text", "save A"), base.replace("save text", "save B"), None, 1),
    ]
    bad = []
    for name, b, o, t, want, nleft in cases:
        got, left = merge(b, o, t)
        if left != nleft or (want is not None and got != want) or (want is None and "<" * M not in got):
            bad.append(f"{name}: {left} conflicts, got {got!r}")
    print("doc_merge selftest:", "ok" if not bad else "FAILED\n  " + "\n  ".join(bad))
    return 1 if bad else 0


def main(argv):
    if argv[1:] == ["--selftest"]:
        return selftest()
    if len(argv) != 4:
        print(__doc__.strip())
        return 2
    rd = lambda p: open(p, encoding="utf-8").read()  # noqa: E731
    text, left = merge(rd(argv[1]), rd(argv[2]), rd(argv[3]))
    with open(argv[2], "w", encoding="utf-8") as f:
        f.write(text)
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
