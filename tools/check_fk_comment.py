#!/usr/bin/env python3
"""2.755.0 (#5261): every new *_id column has a foreign key or a "no FK" marker (the schema rule of #2174).

The rule lived in tests/p2103_c_api_test.py only, a suite that needs a container: it was red in the full CI three times (#4647,
#4721, #5101, field_trash.field_id in 2.740.0) before anyone saw it on a build. Now it is a lint step (seconds, no database) and
the suite calls this same logic.

Read: schema.py + the fragments of migrations.d (tools/check_migrations.py schema_src).
  - an *_id BIGINT column of a CREATE TABLE needs REFERENCES, PRIMARY KEY or "no FK" on its line; a table whose comment block
    above it says "no FK" is skipped as a whole
  - an ALTER TABLE ... ADD COLUMN [IF NOT EXISTS] x_id BIGINT ... anywhere (MIGRATIONS tuple, wrapped over lines, AFTER list)
    the same, the marker in the statement, on its line or on the line before
  - the columns of 2.102 without a key stand frozen in tests/p2103_c_fk_legacy.txt: that list only shrinks; a line there whose
    column has a key by now (or is gone) is a finding too, take it out

usage: python3 tools/check_fk_comment.py [-v]      exit 1 on a finding
Standard library only.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from check_migrations import schema_src  # noqa: E402

LEGACY = os.path.join("tests", "p2103_c_fk_legacy.txt")
TABLE = re.compile(r"((?:--[^\n]*\n)*)CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", re.S)
COL = re.compile(r"(\w+_id) BIGINT(?! GENERATED)([^,]*)")
# 2.755.0 (#5261): over the whole text, not per line - IF NOT EXISTS, a wrapped tuple and an AFTER list are seen too
STEP = re.compile(r"""ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?"?(\w+_id)"?\s+BIGINT(?!\s+GENERATED)([^"']*)""", re.I)


def legacy(root=ROOT):
    """The frozen list: table.column of 2.102 that have no key."""
    with open(os.path.join(root, LEGACY), encoding="utf-8") as f:
        return {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}


def unkeyed(src):
    """Every table.column (*_id BIGINT) in src without REFERENCES / PRIMARY KEY / "no FK", in order of appearance."""
    out = []
    sch = "\n".join(re.findall(r'SCHEMA = """(.*?)"""', src, re.S))
    for t in TABLE.finditer(sch):
        if "no FK" in t.group(1):
            continue
        for line in t.group(3).split("\n"):
            for col in COL.findall(line):
                if "REFERENCES" not in col[1] and "PRIMARY KEY" not in col[1] and "no FK" not in line:
                    out.append(f"{t.group(2)}.{col[0]}")
    for m in STEP.finditer(src):
        a = src.rfind("\n", 0, m.start())
        a = src.rfind("\n", 0, a) if a > 0 else a  # the line before, too
        b = src.find("\n", m.end())
        ctx = src[a + 1:b if b >= 0 else len(src)]
        if "REFERENCES" not in m.group(3) and "PRIMARY KEY" not in m.group(3) and "no FK" not in ctx:
            out.append(f"{m.group(1)}.{m.group(2)}")
    return out


def findings(root=ROOT, src=None, old=None):
    """The findings as lines (empty: all fine). src / old: a text and a legacy set of their own (the test's fragments)."""
    src = schema_src(root) if src is None else src
    old = legacy(root) if old is None else old
    now = unkeyed(src)
    bad = [f"{c}: a new *_id column without REFERENCES ... ON DELETE ... or a comment 'no FK: <reason>' on its line (#2174)"
           for c in now if c not in old]
    for c in sorted(old - set(now)):
        bad.append(f"{LEGACY}: {c} has a key by now or is gone - take the line out, the list only shrinks")
    return bad


if __name__ == "__main__":
    out = findings()
    for x in out:
        print(x)
    if "-v" in sys.argv or out:
        print(f"check_fk_comment: {len(legacy())} frozen column(s), {len(out)} finding(s)")
    sys.exit(1 if out else 0)
