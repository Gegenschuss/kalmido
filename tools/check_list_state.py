#!/usr/bin/env python3
"""2.1029.0 (#5537): a project's state (live / archived / in the trash) is read through its marker, not by hand.

lists.state (kalmido/core/migrations.d/5537_a.py) is 'live', 'archived' or 'trash'; the condition on it is written ONCE:
kalmido/core/access.py list_state_sql(alias, *states) (otr_live(alias) = not in the trash). A new handwritten filter on the
old columns of lists -- archived=0 / archived=1 / deleted_at IS NULL in a line that reads FROM lists (or JOIN lists), or
l.archived / l.deleted_at / lists.archived compared anywhere -- is red. The ones there are today stand per file in
tools/list_state_baseline.json, and that file only shrinks (as tools/check_live_filter.py): more than the baseline = red,
fewer = a notice to lower it (--strict: red), --update lowers the numbers and never raises one or adds a file.

Reading the value (SELECT archived ... for the API, a dict of the row) is no filter and does not count. Stage 2 (one way) moves
the write paths onto the marker and drops the old columns; until then they stay the ones that are written.

Read: kalmido/**/*.py without the schema (kalmido/core/schema.py, kalmido/core/migrations.d/) and the start's one-off fill
(core/db.py names the old columns on purpose there, the lines right after its flag). Line by line, case-insensitive; a filter
in a multi-line statement whose FROM stands on another line is not seen (the qualified form l.archived is).

usage: python3 tools/check_list_state.py [-v] [--strict] [--update] [--root DIR]      exit 1 on a finding
Standard library only.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join("tools", "list_state_baseline.json")
SKIP = ("kalmido/core/schema.py", "kalmido/core/migrations.d/")
# a compare on lists.archived, qualified by the usual aliases of lists (l.deleted_at only in a line that reads lists l:
# the alias l stands for other tables too, e.g. conn_links l)
QUAL = re.compile(r"\b(?:(?:l|lists|lst)\.archived\s*(?:=|<>|!=)|lists\.deleted_at\s+IS\b)", re.I)
QUAL_L = re.compile(r"\bl\.deleted_at\s+IS\b", re.I)
# a line that reads lists (not lists_*) and filters on an unqualified old column AFTER that FROM / JOIN (a table before it
# in the same line, e.g. FROM hub_mails WHERE deleted_at IS NULL ... (SELECT ... FROM lists l), is not lists)
FROM_LISTS = re.compile(r"\b(?:FROM|JOIN)\s+lists\b(?!_)", re.I)
FROM_LISTS_L = re.compile(r"\b(?:FROM|JOIN)\s+lists\s+(?:AS\s+)?l\b", re.I)
BARE = re.compile(r"(?<![.\w])(?:archived\s*(?:=|<>|!=)\s*[01]\b|deleted_at\s+IS\s+(?:NOT\s+)?NULL\b)", re.I)
FILL = "migr_liststate5537"  # the start's one-off fill (core/db.py) names the old columns on purpose
FILL_LINES = 5  # its statement stands within these lines after the flag
HELP = "use list_state_sql() / otr_live() of kalmido/core/access.py"


def count_text(text):
    """Number of handwritten filters on a project's old state columns in a file's text."""
    n, skip = 0, 0
    for line in text.splitlines():
        if FILL in line:
            skip = FILL_LINES
        if skip:
            skip -= 1
            continue
        n += len(QUAL.findall(line))
        m = FROM_LISTS_L.search(line)
        if m:
            n += len(QUAL_L.findall(line, m.start()))
        m = FROM_LISTS.search(line)
        if m:
            n += len(BARE.findall(line, m.end()))
    return n


def counts(root=ROOT):
    """{path relative to root: number of handwritten filters} of the server code (files without one left out)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(root, "kalmido", "**", "*.py"), recursive=True)):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        if rel.startswith(SKIP):
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            n = count_text(f.read())
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
        json.dump({"about": "tools/check_list_state.py (#5537): handwritten filters on lists.archived / deleted_at per file; only shrinks",
                   "total": sum(base.values()), "files": dict(sorted(base.items()))}, f, indent=1, ensure_ascii=False)
        f.write("\n")


def findings(now, base, strict=False):
    """(red, notices) as lines for the counts now against the baseline base."""
    red, note = [], []
    for path, n in sorted(now.items()):
        allowed = base.get(path, 0)
        if n > allowed:
            red.append(f"check_list_state: {path} has {n} handwritten project state filter(s), the baseline {allowed} - {HELP}")
        elif n < allowed:
            note.append(f"check_list_state: {path} has {n} (baseline {allowed}) - lower it: python3 tools/check_list_state.py --update")
    for path in sorted(set(base) - set(now)):
        note.append(f"check_list_state: {path} has none any more (baseline {base[path]}) - python3 tools/check_list_state.py --update")
    if strict:
        red, note = red + note, []
    return red, note


def update(now, base):
    """The baseline lowered to now: never higher than before, never a file it did not hold."""
    return {k: min(v, now[k]) for k, v in base.items() if now.get(k)}


def main(argv):
    root = argv[argv.index("--root") + 1] if "--root" in argv else ROOT
    now, base = counts(root), load(root)
    if "--seed" in argv and not os.path.exists(os.path.join(root, BASELINE)):  # the very first baseline only
        base = now
        save(root, base)
    if "--update" in argv:
        new = update(now, base)
        save(root, new)
        print(f"check_list_state: baseline {sum(base.values())} -> {sum(new.values())} in {len(new)} file(s)")
        base = new
    red, note = findings(now, base, "--strict" in argv)
    for x in note + red:
        print(x)
    if "-v" in argv or red:
        print(f"check_list_state: {sum(now.values())} handwritten filter(s) in {len(now)} file(s), baseline "
              f"{sum(base.values())}, {len(red)} finding(s)")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
