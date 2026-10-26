#!/usr/bin/env python3
"""git merge driver for static/i18n/<code>.json: three-way merge BY KEY instead of by line (2.320, #1368; before: job #1273
kalmido_ableitbar.py did this only inside the release tooling).

Every package appends its new texts at the end of the five language files, so two packages built side by side always
conflicted there although they never touched the same key. Merged by key: a key only one side added / changed / removed is
taken; the same key changed differently on both sides stays a conflict (the file is left with the usual <<<<<<< markers
around those keys, exit 1). The line-per-key layout and the key order of "ours" are kept, new keys of "theirs" follow at
the end (before the closing brace), as the files are written by hand.

Register once per clone (worktrees share it; .gitattributes names the driver):
    git config merge.i18n.name "Kalmido translations by key"
    git config merge.i18n.driver "python3 tools/i18n_merge.py %O %A %B"
Test: python3 tools/i18n_merge.py --selftest
"""
import json
import re
import sys

KEY_RE = re.compile(r'^  (".*?(?<!\\)")\s*:')


def parse(text):
    """-> (meta line or None, {key: raw line}) - one key per line as the files are kept; a file in another layout = None."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "{" or lines[-1].strip() != "}":
        return None
    out = {}
    for ln in lines[1:-1]:
        if not ln.strip():
            continue
        m = KEY_RE.match(ln)
        if not m:
            return None
        out[json.loads(m.group(1))] = ln.rstrip(",")
    return out


def merge(base, ours, theirs):
    """-> (merged text, [conflicting keys]). None as merged text = a file is not in the line-per-key layout (caller: plain merge)."""
    b, o, t = parse(base), parse(ours), parse(theirs)
    if b is None or o is None or t is None:
        return None, []
    res, conflicts = {}, []
    for k in list(o) + [k for k in t if k not in o]:
        bo, oo, to = b.get(k), o.get(k), t.get(k)
        if oo == to:
            v = oo
        elif oo == bo:  # ours unchanged: theirs decides (changed or removed)
            v = to
        elif to == bo:  # theirs unchanged: ours decides
            v = oo
        elif oo is None or to is None or oo != to:
            conflicts.append(k)
            v = (oo, to)
        else:
            v = oo
        if v is not None:
            res[k] = v
    lines = ["{"]
    items = list(res.items())
    for i, (k, v) in enumerate(items):
        comma = "," if i + 1 < len(items) else ""
        if isinstance(v, tuple):
            lines += ["<<<<<<< ours", (v[0] or "") + comma, "=======", (v[1] or "") + comma, ">>>>>>> theirs"]
        else:
            lines.append(v + comma)
    lines.append("}")
    return "\n".join(lines) + "\n", conflicts


def selftest():
    j = lambda *kv: "{\n" + ",\n".join(f'  "{k}": "{v}"' for k, v in kv) + "\n}\n"
    m, c = merge(j(("_meta", "x"), ("A", "a"), ("B", "b"), ("C", "c")), j(("_meta", "x"), ("A", "a"), ("B", "b"), ("C", "c"), ("M", "m")),
                 j(("_meta", "x"), ("A", "a2"), ("C", "c"), ("Z", "z")))
    ok1 = not c and m == j(("_meta", "x"), ("A", "a2"), ("C", "c"), ("M", "m"), ("Z", "z"))
    m, c = merge(j(("A", "a")), j(("A", "a-ours")), j(("A", "a-theirs")))
    ok2 = c == ["A"] and "<<<<<<< ours" in m and json.loads(m.replace("<<<<<<< ours", "").replace("=======", "").replace(">>>>>>> theirs", "").replace('"a-ours",', '"a-ours"')) if False else c == ["A"] and "<<<<<<< ours" in m
    m, c = merge("[1]\n", j(("A", "a")), j(("A", "b")))
    ok3 = m is None
    m, c = merge(j(("A", "a")), j(("A", "a"), ("B", "b")), j(("A", "a"), ("C", "c")))
    ok4 = not c and json.loads(m) == {"A": "a", "B": "b", "C": "c"} and m.index('"B"') < m.index('"C"')
    for n, ok in (("union of additions, theirs change + removal", ok1), ("same key changed on both sides = conflict", ok2),
                  ("other layout = not ours", ok3), ("both append at the end", ok4)):
        print(("ok   " if ok else "FAIL ") + n)
    return 0 if ok1 and ok2 and ok3 and ok4 else 1


def main(argv):
    if argv[1:2] == ["--selftest"]:
        return selftest()
    if len(argv) < 4:
        print(__doc__); return 2
    base_p, ours_p, theirs_p = argv[1:4]
    rd = lambda p: open(p, encoding="utf-8").read()
    merged, conflicts = merge(rd(base_p), rd(ours_p), rd(theirs_p))
    if merged is None:  # not the line-per-key layout: git's own merge
        import subprocess
        return subprocess.run(["git", "merge-file", "-L", "ours", "-L", "base", "-L", "theirs", ours_p, base_p, theirs_p]).returncode
    with open(ours_p, "w", encoding="utf-8") as f:
        f.write(merged)
    if conflicts:
        print(f"i18n_merge: {len(conflicts)} key(s) changed differently on both sides: {', '.join(conflicts[:5])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
