#!/usr/bin/env python3
"""2.755.0 (#5305): new columns with real types - a point in time is TIMESTAMPTZ (or DATE), yes / no is BOOLEAN, JSON is JSONB.

Since the move to Postgres (2.37.0, #1150) the schema kept the SQLite habits: timestamps as ISO text, booleans as BIGINT 0/1,
JSON as text (core/schema.py, the comment at its top). The old columns move one by one, each with the core stage that touches
them anyway; a new column must not add to them. Read (static, no database): schema.py + the fragments of migrations.d - every
CREATE TABLE column, every ADD COLUMN (MIGRATIONS and AFTER); an ALTER COLUMN ... TYPE changes the type, a dropped table or
column (DROP TABLE / DROP COLUMN in a fragment) is gone.

  time   a column named *_at, *_on or *_until of type TEXT, BIGINT / INTEGER or TIMESTAMP (no zone) -> TIMESTAMPTZ (DATE for a day)
  bool   is_* / has_* of type BIGINT / INTEGER / SMALLINT, or a flag name (enabled, archived, pinned, ... *_enabled, *_ok)
         of such a type with DEFAULT 0 / 1 or CHECK (... IN (0, 1))                            -> BOOLEAN
  json   a TEXT column named *_json or with DEFAULT '{}' / '[]'                                 -> JSONB

What is there today stands in tools/coltypes_baseline.txt ("table.column rule"). A stage that moves an old column takes its line
out; a line whose column has a real type by now, or is gone, is a note (#4314; --strict: a finding). A column the rule reads
wrongly (a text that only ends in _at) gets the marker "coltype-ok: <why>" on its line.

usage: python3 tools/check_coltypes.py [-v] [--list]      exit 1 on a finding (--list: every column the rules catch, as baseline lines)
Standard library only.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from check_migrations import fragments  # noqa: E402

BASELINE = os.path.join("tools", "coltypes_baseline.txt")
INTS = {"BIGINT", "INTEGER", "INT", "SMALLINT", "INT8", "INT4", "INT2"}
FLAG_WORDS = {"enabled", "disabled", "active", "archived", "hidden", "pinned", "muted", "locked", "starred", "favorite", "visible",
              "verified", "confirmed", "approved", "blocked", "done", "closed", "deleted", "private", "public", "read", "seen",
              "paid", "billable", "default", "primary", "flag", "draft", "sent", "silent", "shared", "internal", "official"}
CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\(", re.I)
ADD = re.compile(r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(\w+)\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?\s+"
                 r"([^\"\n;]*)", re.I)
RETYPE = re.compile(r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(\w+)\s+ALTER\s+COLUMN\s+\"?(\w+)\"?\s+(?:SET\s+DATA\s+)?TYPE\s+"
                    r"(\w+)", re.I)
DROP_TABLE = re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)", re.I)
DROP_COL = re.compile(r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)\s+DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?\"?(\w+)", re.I)
OK = "coltype-ok"
WHY = {"time": "a point in time as TEXT / a number / TIMESTAMP without zone: use TIMESTAMPTZ (DATE for a day)",
       "bool": "yes / no as a number 0/1: use BOOLEAN",
       "json": "JSON as TEXT: use JSONB"}


def sources(root=ROOT):
    """[(path relative to root, text)] of schema.py and the fragments."""
    out = []
    for p in [os.path.join(root, "kalmido", "core", "schema.py")] + fragments(root):
        with open(p, encoding="utf-8") as f:
            out.append((os.path.relpath(p, root), f.read()))
    return out


def sql_mask(src):
    """src with the same length and lines: an SQL comment blanked, a comma / bracket inside a '...' text made harmless (a DEFAULT
    'docs,images' is no second column). The marker coltype-ok is read from the text itself."""
    src = re.sub(r"--[^\n]*", lambda m: " " * len(m.group(0)), src)
    return re.sub(r"'(?:[^'\n]|'')*'", lambda m: m.group(0).replace(",", ";").replace("(", "<").replace(")", ">"), src)


def _line(src, pos):
    a, b = src.rfind("\n", 0, pos) + 1, src.find("\n", pos)
    return src[a:b if b >= 0 else len(src)]


def columns(srcs):
    """{"table.column": (definition, file, line number, ok marker)} - the last word on a column wins (ALTER ... TYPE)."""
    cols, gone_t, gone_c = {}, set(), set()
    for path, raw in srcs:
        src = sql_mask(raw)
        for m in CREATE.finditer(src):
            depth, i, part, start = 1, m.end(), "", m.end()
            while i < len(src) and depth:
                ch = src[i]
                depth += (ch == "(") - (ch == ")")
                if depth == 1 and ch == "," or depth == 0:
                    w = part.split()
                    if w and w[0].upper() not in ("PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT", "EXCLUDE"):
                        pos = start + len(part) - len(part.lstrip())
                        key = f"{m.group(1)}.{w[0].strip(chr(34))}"
                        cols.setdefault(key, (" ".join(w[1:]), path, src.count("\n", 0, pos) + 1, OK in _line(raw, pos)))
                    part, start = "", i + 1
                else:
                    part += ch
                i += 1
        for m in ADD.finditer(src):
            key = f"{m.group(1)}.{m.group(2)}"
            if key not in cols:
                cols[key] = (m.group(3).strip(), path, src.count("\n", 0, m.start()) + 1, OK in _line(raw, m.start()))
        if "migrations.d" in path:
            gone_t |= set(DROP_TABLE.findall(src))
            gone_c |= {f"{t}.{c}" for t, c in DROP_COL.findall(src)}
    for path, src in srcs:
        for m in RETYPE.finditer(src):
            key = f"{m.group(1)}.{m.group(2)}"
            if key in cols:
                d = cols[key]
                cols[key] = (m.group(3) + " " + " ".join(d[0].split()[1:]), d[1], d[2], d[3])
    return {k: v for k, v in cols.items() if k.split(".")[0] not in gone_t and k not in gone_c}


def rule(col, definition):
    """'time' | 'bool' | 'json' when the column breaks a rule, else None."""
    w = definition.split()
    typ = re.sub(r"\(.*", "", w[0]).upper() if w else ""
    up = " ".join(definition.upper().split())
    naive_ts = typ == "TIMESTAMP" and not re.match(r"TIMESTAMP\s+WITH\s+TIME\s+ZONE", up)  # TIMESTAMPTZ is another word
    if (typ == "TEXT" or typ in INTS or naive_ts) and re.search(r"_(at|on|until)$", col):  # 2.755.0 (#5261 review): not only TEXT
        return "time"
    if typ in INTS:
        if re.match(r"(is|has)_", col):
            return "bool"
        flag = col in FLAG_WORDS or re.search(r"_(enabled|disabled|ok|flag)$", col)
        if flag and (re.search(r"\bDEFAULT\s+[01]\b", up) or re.search(r"\bIN\s*\(\s*0\s*,\s*1\s*\)", up)):
            return "bool"
    if typ == "TEXT" and (col.endswith("_json") or re.search(r"DEFAULT\s+'(\{\}|\[\])'", up)):
        return "json"
    return None


def caught(srcs):
    """{"table.column": (rule, file, line)} of every column a rule catches (without the ones marked coltype-ok)."""
    out = {}
    for key, (d, path, line, ok) in columns(srcs).items():
        r = rule(key.split(".", 1)[1], d)
        if r and not ok:
            out[key] = (r, path, line)
    return out


def baseline(root=ROOT):
    """{"table.column": rule} of the baseline file."""
    out = {}
    with open(os.path.join(root, BASELINE), encoding="utf-8") as f:
        for ln in f:
            w = ln.split("#")[0].split()
            if len(w) >= 2:
                out[w[0]] = w[1]
    return out


def findings(root=ROOT, srcs=None, base=None, strict=False):
    """The findings as lines (empty: all fine). srcs / base: texts and a baseline of their own (the test's fragments).
    #4314 (Karte 17345): a baseline line whose column has a real type by now or is gone is a note (stale()), not red -- unless
    strict (--strict, a check of the list itself): fixing a column never needs a second edit in the baseline."""
    srcs = sources(root) if srcs is None else srcs
    base = baseline(root) if base is None else base
    now = caught(srcs)
    bad = [f"check_coltypes: {k} ({p}:{ln}): {WHY[r]} (or '{OK}: <why>' on its line when the rule reads it wrongly)"
           for k, (r, p, ln) in sorted(now.items()) if base.get(k) != r]
    if strict:
        bad += stale(root, srcs, base)
    return bad


def stale(root=ROOT, srcs=None, base=None):
    """#4314: the baseline lines whose column has a real type by now or is gone (a note: the line can go)."""
    srcs = sources(root) if srcs is None else srcs
    base = baseline(root) if base is None else base
    now = caught(srcs)
    return [f"{BASELINE}: {k} has a real type by now or is gone - the line can go" for k in sorted(set(base) - set(now))]


if __name__ == "__main__":
    if "--list" in sys.argv:
        for k, (r, _p, _ln) in sorted(caught(sources()).items()):
            print(f"{k} {r}")
        sys.exit(0)
    out = findings(strict="--strict" in sys.argv)
    for x in out:
        print(x)
    if "--strict" not in sys.argv:
        for x in stale():
            print("note:", x)
    if "-v" in sys.argv or out:
        print(f"check_coltypes: {len(baseline())} old column(s) in the baseline, {len(out)} finding(s)")
    sys.exit(1 if out else 0)
