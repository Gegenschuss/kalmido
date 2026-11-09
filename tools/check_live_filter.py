#!/usr/bin/env python3
"""2.773.0 (#5292, review finding F3): the "not in the trash" filter comes from the core, not by hand.

A row in the trash is invisible everywhere but in the trash's own routes; the condition for that is written ONCE:
kalmido/core/access.py live_sql(alias, col) (trash_sql for the opposite). A new handwritten 'deleted_at IS NULL' in the
server code is red. The ones there are today stand per file in tools/live_filter_baseline.json, and that file only shrinks:
a file with MORE than its number is red (use live_sql), a file with fewer is a notice to lower the number (--strict: red),
a baseline line of a file that is gone is a notice too (--strict: red). --update lowers the numbers to what is there now and
takes out the lines of files without any - it never raises a number or adds a file (a new one stays red).

Read: kalmido/**/*.py, without the schema (kalmido/core/schema.py, kalmido/core/migrations.d/): a partial index
"WHERE deleted_at IS NULL" is DDL, no read. Case and the spaces between the words do not count; an alias before it does not
either (t.deleted_at IS NULL counts).

usage: python3 tools/check_live_filter.py [-v] [--strict] [--update] [--root DIR]      exit 1 on a finding
Standard library only.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join("tools", "live_filter_baseline.json")
HAND = re.compile(r"\bdeleted_at\s+IS\s+NULL\b", re.I)
SKIP = ("kalmido/core/schema.py", "kalmido/core/migrations.d/")
HELP = "use live_sql() / trash_sql() of kalmido/core/access.py"


def counts(root=ROOT):
    """{path relative to root: number of handwritten filters} of the server code (files without one left out)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(root, "kalmido", "**", "*.py"), recursive=True)):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        if rel.startswith(SKIP):
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            n = len(HAND.findall(f.read()))
        if n:
            out[rel] = n
    return out


def load(root=ROOT):
    p = os.path.join(root, BASELINE)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return {k: int(v) for k, v in (data.get("files") or {}).items()}


def save(root, base):
    with open(os.path.join(root, BASELINE), "w", encoding="utf-8") as f:
        json.dump({"about": "tools/check_live_filter.py (#5292): handwritten 'deleted_at IS NULL' per file; only shrinks",
                   "total": sum(base.values()), "files": dict(sorted(base.items()))}, f, indent=1, ensure_ascii=False)
        f.write("\n")


def findings(now, base, strict=False):
    """(red, notices) as lines for the counts now against the baseline base."""
    red, note = [], []
    for path, n in sorted(now.items()):
        allowed = base.get(path, 0)
        if n > allowed:
            red.append(f"check_live_filter: {path} has {n} handwritten 'deleted_at IS NULL', the baseline {allowed} - {HELP}")
        elif n < allowed:
            note.append(f"check_live_filter: {path} has {n} (baseline {allowed}) - lower it: python3 tools/check_live_filter.py --update")
    for path in sorted(set(base) - set(now)):
        note.append(f"check_live_filter: {path} has none any more (baseline {base[path]}) - python3 tools/check_live_filter.py --update")
    if strict:
        red, note = red + note, []
    return red, note


def update(now, base):
    """The baseline lowered to now: never higher than before, never a file it did not hold."""
    return {k: min(v, now[k]) for k, v in base.items() if now.get(k)}


def main(argv):
    root = argv[argv.index("--root") + 1] if "--root" in argv else ROOT
    now, base = counts(root), load(root)
    if "--update" in argv:
        new = update(now, base)
        save(root, new)
        print(f"check_live_filter: baseline {sum(base.values())} -> {sum(new.values())} in {len(new)} file(s)")
        base = new
    red, note = findings(now, base, "--strict" in argv)
    for x in note + red:
        print(x)
    if "-v" in argv or red:
        print(f"check_live_filter: {sum(now.values())} handwritten filter(s) in {len(now)} file(s), baseline "
              f"{sum(base.values())}, {len(red)} finding(s)")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
