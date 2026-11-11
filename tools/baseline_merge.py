#!/usr/bin/env python3
"""A git merge driver for the lint baselines tools/*_baseline.json (2.928.0, #5597).

Every package that fixes an old finding lowers a count in a baseline, and tools/live_filter_baseline.json also keeps a
"total" over all files: two packages built side by side both changed it, so the train's move-up rebase stopped on a
conflict in that one number (11.11.2026: three packages rebuilt for it). Here a three-way merge of the JSON values
instead of the lines:
  - a value only one side changed is taken from that side (also an added or a removed key, an added or removed list item)
  - a count both sides changed: both lowered = the lower one, both raised = the higher one (the same entry added twice
    is one entry), one lowered and one raised = both changes (ours + theirs - base); 0 = the key goes
  - a dict both sides changed is merged key by key; a list both sides changed as a multiset of its items (an item one
    side removed stays removed, an item one side added is kept, order: ours, then theirs' new ones; a sorted list stays
    sorted, the semgrep entries by file, rule, code as tools/semgrep_baseline.py writes them)
  - "total" next to a "files" dict of counts is the sum of the merged counts
  - a text (or another value) both sides changed differently: no merge, git's line merge decides (conflict markers)
The file is written in the layout of "ours" (indent, key order, separators, trailing newline as found), so a merged
baseline equals what the tool's --update would write.

  python3 tools/baseline_merge.py %O %A %B     the driver (.gitattributes `merge=baseline`), writes the result into %A
  python3 tools/baseline_merge.py --selftest
Register once per clone (worktrees share it): tools/git_setup.sh
Python standard library only.
"""
import json
import subprocess
import sys

CONFLICT = object()  # a value both sides changed differently and no rule merges


def _canon(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _count(b, o, t):
    """A count both sides changed (absent = 0)."""
    if (o - b) * (t - b) > 0:
        return min(o, t) if o < b else max(o, t)
    return max(0, o + t - b)


def _is_count(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _sort_key(items):
    """How a list is kept sorted, or None: the semgrep entries by (file, rule, code), plain values by themselves."""
    if items and all(isinstance(x, dict) and {"file", "rule", "code"} <= set(x) for x in items):
        return lambda x: (x["file"], x["rule"], x["code"])
    if items and all(isinstance(x, str) for x in items) or items and all(_is_count(x) for x in items):
        return lambda x: x
    return None


def _merge_list(b, o, t):
    cb, co, ct = {}, {}, {}
    for lst, cnt in ((b, cb), (o, co), (t, ct)):
        for x in lst:
            cnt[_canon(x)] = cnt.get(_canon(x), 0) + 1
    want = {}
    for k in set(cb) | set(co) | set(ct):
        bb, oo, tt = cb.get(k, 0), co.get(k, 0), ct.get(k, 0)
        want[k] = tt if oo == bb else oo if tt == bb else _count(bb, oo, tt)
    out, left = [], dict(want)
    for x in list(o) + list(t):
        k = _canon(x)
        if left.get(k, 0) > 0:
            out.append(x)
            left[k] -= 1
    key = _sort_key(o)
    if key is not None:
        try:
            if list(o) == sorted(o, key=key):
                out.sort(key=key)
        except TypeError:
            pass
    return out


def _merge_dict(b, o, t):
    b = b if isinstance(b, dict) else {}
    keys = list(o) + [k for k in t if k not in o]
    out = {}
    for k in keys:
        v = merge_value(b.get(k), o.get(k), t.get(k), present=(k in b, k in o, k in t))
        if v is CONFLICT:
            return CONFLICT
        if v is not _GONE:
            out[k] = v
    if list(o) == sorted(o) and len(o) > 1:
        out = dict(sorted(out.items()))
    files = out.get("files")
    if _is_count(out.get("total")) and isinstance(files, dict) and all(_is_count(v) for v in files.values()):
        out["total"] = sum(files.values())
    return out


_GONE = object()


def merge_value(b, o, t, present=(True, True, True)):
    """The merged value of one key; _GONE = the key goes, CONFLICT = no rule merges it."""
    pb, po, pt = present
    vb, vo, vt = (b if pb else _GONE), (o if po else _GONE), (t if pt else _GONE)
    eq = lambda x, y: (x is _GONE and y is _GONE) or (x is not _GONE and y is not _GONE and _canon(x) == _canon(y))  # noqa: E731
    if eq(vo, vt):
        return vo
    if eq(vo, vb):
        return vt
    if eq(vt, vb):
        return vo
    vals = [v for v in (vb, vo, vt) if v is not _GONE]
    if all(_is_count(v) for v in vals) and (vo is not _GONE or vt is not _GONE):
        n = _count(vb if vb is not _GONE else 0, vo if vo is not _GONE else 0, vt if vt is not _GONE else 0)
        return n if n else _GONE
    if vo is not _GONE and vt is not _GONE:
        if isinstance(vo, dict) and isinstance(vt, dict) and (vb is _GONE or isinstance(vb, dict)):
            return _merge_dict(vb if vb is not _GONE else {}, vo, vt)
        if isinstance(vo, list) and isinstance(vt, list) and (vb is _GONE or isinstance(vb, list)):
            return _merge_list(vb if vb is not _GONE else [], vo, vt)
    if vo is _GONE or vt is _GONE:  # one side removed, the other changed: a dict / list keeps the other side's change merged
        kept = vt if vo is _GONE else vo
        if isinstance(kept, dict) and isinstance(vb, dict):
            return _merge_dict(vb, {}, kept) if vo is _GONE else _merge_dict(vb, kept, {})
        if isinstance(kept, list) and isinstance(vb, list):
            return _merge_list(vb, [], kept) if vo is _GONE else _merge_list(vb, kept, [])
    return CONFLICT


LAYOUTS = [  # (json.dump keyword arguments) as the baseline tools write them; the first that reproduces "ours" wins
    dict(indent=1, ensure_ascii=False),
    dict(indent=0, ensure_ascii=False),
    dict(indent=0, sort_keys=True, separators=(",", ":")),
    dict(indent=0, separators=(",", ":"), ensure_ascii=False),
    dict(indent=2, ensure_ascii=False),
    dict(indent=1, sort_keys=True, ensure_ascii=False),
    dict(indent=2, sort_keys=True, ensure_ascii=False),
]


def layout_of(text):
    """(json.dump arguments, trailing newline) that write TEXT back byte for byte; a hand-written file: indent=1 + newline."""
    data = json.loads(text)
    for kw in LAYOUTS:
        out = json.dumps(data, **kw)
        if text == out or text == out + "\n":
            return kw, text.endswith("\n")
    return LAYOUTS[0], True


def merge(base, ours, theirs):
    """The merged text of three versions of a baseline, or None (not JSON / a conflict no rule merges)."""
    try:
        b, o, t = json.loads(base) if base.strip() else {}, json.loads(ours), json.loads(theirs)
    except ValueError:
        return None
    v = merge_value(b, o, t)
    if v is CONFLICT or v is _GONE:
        return None
    kw, nl = layout_of(ours)
    return json.dumps(v, **kw) + ("\n" if nl else "")


def selftest():
    lf = lambda total, **f: json.dumps({"about": "x", "total": total, "files": dict(sorted(f.items()))}, indent=1) + "\n"  # noqa: E731
    sg = lambda *es: json.dumps({"_doc": "d", "entries": [dict(rule="r", file=f, code=c, reason="why", date="d") for f, c in es]},  # noqa: E731
                                indent=1, ensure_ascii=False) + "\n"
    rf = lambda files: json.dumps({"_doc": "d", "files": files}, indent=0, sort_keys=True, separators=(",", ":")) + "\n"  # noqa: E731
    base = lf(10, a=4, b=3, c=3)
    cases = [
        # two packages lower different files: no conflict, total recomputed (the 11.11.2026 conflict)
        ("total", base, lf(9, a=3, b=3, c=3), lf(8, a=4, b=1, c=3), lf(7, a=3, b=1, c=3)),
        # both lower the same file: the lower count; one drops a file, the other lowers another
        ("min", base, lf(8, a=2, b=3, c=3), lf(9, a=3, b=3, c=3), lf(8, a=2, b=3, c=3)),
        ("gone", base, lf(7, a=4, b=3), lf(9, a=4, b=2, c=3), lf(6, a=4, b=2)),
        # a file added on one side (an exception by hand) stays, the other side's lowering too
        ("added", base, lf(12, a=4, b=3, c=3, d=2), lf(9, a=3, b=3, c=3), lf(11, a=3, b=3, c=3, d=2)),
        # semgrep entries: one side removes one, the other adds one - sorted by file, rule, code as the tool writes them
        ("entries", sg(("a.py", "x"), ("b.py", "y")), sg(("b.py", "y")), sg(("a.py", "x"), ("b.py", "y"), ("c.py", "z")),
         sg(("b.py", "y"), ("c.py", "z"))),
        # both add the same entry: once
        ("same add", sg(("a.py", "x")), sg(("a.py", "x"), ("b.py", "y")), sg(("a.py", "x"), ("b.py", "y")), sg(("a.py", "x"), ("b.py", "y"))),
        # innerhtml layout (indent 0, no trailing newline): both lower different keys
        ("innerhtml", '{\n"f|a": 2,\n"f|b": 1\n}', '{\n"f|a": 1,\n"f|b": 1\n}', '{\n"f|a": 2\n}', '{\n"f|a": 1\n}'),
        # ruff layout: hashes per file and rule as a multiset, one side drops one of two equal hashes
        ("ruff", rf({"k.py": {"F401": ["aa", "aa", "bb"]}}), rf({"k.py": {"F401": ["aa", "bb"]}}),
         rf({"k.py": {"F401": ["aa", "aa", "bb"]}, "m.py": {"E1": ["cc"]}}), rf({"k.py": {"F401": ["aa", "bb"]}, "m.py": {"E1": ["cc"]}})),
        # a text both sides changed differently: no rule, git's merge decides
        ("text", lf(10, a=4, b=3, c=3), lf(10, a=4, b=3, c=3).replace('"x"', '"y"'), lf(10, a=4, b=3, c=3).replace('"x"', '"z"'), None),
    ]
    bad = []
    for name, b, o, t, want in cases:
        got = merge(b, o, t)
        if got != want:
            bad.append(f"{name}: got {got!r}, want {want!r}")
    print("baseline_merge selftest:", "ok" if not bad else "FAILED\n  " + "\n  ".join(bad))
    return 1 if bad else 0


def main(argv):
    if argv[1:] == ["--selftest"]:
        return selftest()
    if len(argv) != 4:
        print(__doc__.strip())
        return 2
    rd = lambda p: open(p, encoding="utf-8").read()  # noqa: E731
    text = merge(rd(argv[1]), rd(argv[2]), rd(argv[3]))
    if text is None:  # git's own line merge: a clean result or the usual conflict markers, its exit code
        return subprocess.run(["git", "merge-file", "-q", argv[2], argv[1], argv[3]]).returncode and 1
    with open(argv[2], "w", encoding="utf-8") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
