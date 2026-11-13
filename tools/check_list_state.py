#!/usr/bin/env python3
"""2.1029.0 (#5537): a project's state (live / archived / in the trash) is read through its marker, not by hand.

lists.state (kalmido/core/migrations.d/5537_a.py) is 'live', 'archived' or 'trash'; the condition on it is written ONCE:
kalmido/core/access.py list_state_sql(alias, *states) (otr_live(alias) = not in the trash). A new handwritten filter on the
old columns of lists -- archived=0 / archived=1 / deleted_at IS NULL in a line that reads FROM lists (or JOIN lists), or
l.archived / l.deleted_at / lists.archived compared anywhere -- is red (2.1118.0, #5952: the column is BOOLEAN, `NOT archived` / `archived = false` count
the same). The ones there are today stand per file in
tools/list_state_baseline.json, and that file only shrinks (as tools/check_live_filter.py): more than the baseline = red,
fewer = a notice to lower it (--strict: red), --update lowers the numbers and never raises one or adds a file.

Reading the value (SELECT archived ... for the API, a dict of the row) was no filter in stage 1.

2.1061.0 (#5867, stage 3): reads of the old column count too -- archived in a line that reads FROM / JOIN lists (a SELECT
list, an ORDER BY, a COALESCE(archived, 0)), l.archived / lists.archived / lst.archived anywhere: the value is
core/access.py list_archived_sql() (`{list_archived_sql('l')} AS archived` keeps the key) or list_archived(row) / list_out(row)
for a row of SELECT *. The column can then go (a one-way step of its own).

2.1054.0 (#5794, stage 2): the write paths of the archive set the marker through core/access.py list_set_archived(); the
trigger writes the old column archived from it. A new handwritten write of it (UPDATE lists SET ... archived=, in one line)
counts as well.

2.1069.0 (#5416, review 2.781 F5): a handwritten compare on the marker itself counts as well -- lists.state / lst.state
anywhere, l.state in a line that reads lists l, a bare state = / <> / IN after FROM / JOIN lists or in UPDATE lists SET:
list_state_sql() / otr_live() / list_set_archived() write it once, in kalmido/core/access.py (STATE_HOME, not counted there).

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
# 2.1054.0 (#5794): a handwritten write of the old archive column of lists (list_set_archived writes the marker)
WRITE = re.compile(r"\bUPDATE\s+lists\s+SET\b(?!_)[^\"']*?(?<![.\w])archived\s*=", re.I)
# 2.1061.0 (#5867, stage 3): a read of the old column: qualified anywhere (not compared: QUAL counts that), or bare in a line
# that reads lists (not AS archived = the key list_archived_sql() keeps, not archived_at, not a quoted key "archived")
READ_Q = re.compile(r"\b(?:l|lists|lst)\.archived\b(?!\s*(?:=|<>|!=))", re.I)
# 2.1118.0 (#5952): a bare `NOT archived` at the end of a string literal counts too (a quoted key "archived" has the quote before)
READ = re.compile(r"(?<![.\w'\"])(?<!AS )archived\b(?!_)", re.I)
# 2.1069.0 (#5416): a handwritten compare on the state marker lists.state (the helpers of STATE_HOME write it once)
_CMP = r"\s*(?:=|<>|!=|\bIN\b|\bNOT\s+IN\b|\bIS\s+(?:NOT\s+)?DISTINCT\b|\b(?:NOT\s+)?LIKE\b)"  # another alias / a statement over several lines is not seen
STATE_Q = re.compile(r"\b(?:lists|lst)\.state" + _CMP, re.I)
STATE_L = re.compile(r"\bl\.state" + _CMP, re.I)
STATE_B = re.compile(r"(?<![.\w'\"])state" + _CMP, re.I)
UPDATE_LISTS = re.compile(r"\bUPDATE\s+lists\s+SET\b", re.I)
STATE_HOME = "kalmido/core/access.py"
HELP = "use list_state_sql() / otr_live() / list_set_archived() / list_archived_sql() / list_out() of kalmido/core/access.py"


def count_text(text, state=True):
    """Number of handwritten filters on a project's old state columns in a file's text (state: count handwritten compares on
    the marker lists.state too, 2.1069.0 #5416; False for STATE_HOME, the home of the helpers)."""
    n, skip = 0, 0
    for line in text.splitlines():
        if FILL in line:
            skip = FILL_LINES
        if skip:
            skip -= 1
            continue
        n += len(QUAL.findall(line))
        n += len(WRITE.findall(line))
        m = FROM_LISTS_L.search(line)
        if m:
            n += len(QUAL_L.findall(line, m.start()))
        n += len(READ_Q.findall(line))
        m = FROM_LISTS.search(line)
        if m:
            bare = {x.start() for x in BARE.finditer(line, m.end())}
            n += len(bare)
            n += sum(1 for x in READ.finditer(line) if x.start() not in bare)  # 2.1061.0 (#5867): reads, a filter counted once
        if state:  # 2.1069.0 (#5416)
            n += len(STATE_Q.findall(line))
            m = FROM_LISTS_L.search(line)
            if m:
                n += len(STATE_L.findall(line, m.start()))
            m = FROM_LISTS.search(line) or UPDATE_LISTS.search(line)
            if m:
                n += len(STATE_B.findall(line, m.end()))
    return n


def counts(root=ROOT):
    """{path relative to root: number of handwritten filters} of the server code (files without one left out)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(root, "kalmido", "**", "*.py"), recursive=True)):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        if rel.startswith(SKIP):
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            n = count_text(f.read(), state=rel != STATE_HOME)
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
