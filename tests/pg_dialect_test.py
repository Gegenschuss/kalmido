"""pg_dialect_test.py -- static guard for 2.37.0 (#1150): no SQLite-only SQL or driver use left in the server code.

Scans the SQL string literals of kalmido/**/*.py (tokenize: only string parts, not comments / names) plus a few driver
patterns in the code. Every hit is a place that works on SQLite but fails or behaves differently on Postgres. A line that is
right on purpose carries the marker `pg-ok` in a comment with the reason.
No container needed:  python3 tests/pg_dialect_test.py
"""
import io
import os
import re
import sys
import tokenize

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kalmido")
if len(sys.argv) > 1:  # e.g. tests/pg_dialect_test.py tests  -> the SQL of the suites themselves (informational)
    ROOT = os.path.abspath(sys.argv[1])
SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE|ORDER BY|GROUP BY|CREATE|ALTER|JOIN|BEGIN|COMMIT|ROLLBACK)\b")
IN_SQL = [  # (name, pattern) inside SQL string literals
    ("INSERT OR IGNORE/REPLACE (use ON CONFLICT)", re.compile(r"\b(INSERT|REPLACE)\s+OR\s+(IGNORE|REPLACE)\b|^\s*REPLACE\s+INTO", re.I)),
    ("x IS ? (use IS NOT DISTINCT FROM ?)", re.compile(r"\bIS\s+(NOT\s+)?\?")),
    ("JSON1 function (use jsonb operators)", re.compile(r"\bjson_(extract|each|valid|array_length|group_array|object|set|insert|remove|type|tree)\s*\(", re.I)),
    ("SQLite date function", re.compile(r"\b(julianday|unixepoch)\s*\(|\b(datetime|date|time)\s*\(\s*'now'|\bstrftime\s*\(\s*'", re.I)),
    ("rowid", re.compile(r"\b(_?rowid_?|oid)\b(?!\s*\()", re.I)),
    ("sqlite_master / PRAGMA", re.compile(r"\bsqlite_(master|schema|sequence)\b|\bPRAGMA\b", re.I)),
    ("COLLATE NOCASE (use lower())", re.compile(r"COLLATE\s+NOCASE", re.I)),
    ("BEGIN IMMEDIATE/EXCLUSIVE (use write_lock)", re.compile(r"\bBEGIN\s+(IMMEDIATE|EXCLUSIVE|DEFERRED)\b", re.I)),
    ("GLOB (use LIKE / ~)", re.compile(r"\bGLOB\b")),
    ("SQLite-only function", re.compile(r"\b(group_concat|ifnull|instr|printf|typeof|total|last_insert_rowid|changes|char)\s*\(", re.I)),
    ("two-argument MAX/MIN (use GREATEST/LEAST)", re.compile(r"\b(MAX|MIN)\(\s*[^()]*?(\([^()]*\)[^()]*?)*,[^()]*\)", re.I)),
    ("case-sensitive LIKE (SQLite LIKE ignores case: use ILIKE)", re.compile(r"(?<![IN])\s(NOT\s+)?LIKE\b(?!\s*\()")),
    ("ON CONFLICT DO UPDATE needs a conflict target", re.compile(r"ON\s+CONFLICT\s+DO\s+UPDATE", re.I)),
    ("LIMIT -1 (use LIMIT ALL)", re.compile(r"LIMIT\s+-1")),
    ("raw COMMIT / ROLLBACK statement (use c.commit() / c.rollback())", re.compile(r"^[rbfu]*[\"']{1,3}\s*(COMMIT|ROLLBACK)\s*;?\s*[\"']{1,3}$", re.I)),
    ("unquoted column end (reserved in Postgres)", re.compile(r"(?<![\w\"'])(?:[a-z]\.)?end\s*(=|IS\b|,\s*\w|\))")),
]
IN_CODE = [  # (name, pattern) in the code itself
    ("cursor.lastrowid (use insert_id)", re.compile(r"\.lastrowid\b")),
    ("sqlite3 driver", re.compile(r"^\s*(import sqlite3|from sqlite3)|\bsqlite3\.")),
    ("isolation_level", re.compile(r"\.isolation_level\b")),
]
# allowed outside the database layer: reading a SQLite file from before 2.37 (the move tool / old backups) -- by file
ALLOW_SQLITE = {"admin/backup.py", "admin/migrate_sqlite.py"}
# 2.37 Teil 1: the in-app backup still copies a SQLite file; it moves to pg_dump / pg_restore in the next step (Job B), which
# removes this exemption
SKIP_UNTIL_JOB_B = {"admin/backup.py"}


def strings(src):
    toks = tokenize.generate_tokens(io.StringIO(src).readline)
    for t in toks:
        if t.type == tokenize.STRING or t.type == getattr(tokenize, "FSTRING_MIDDLE", -1):
            yield t.start[0], t.string


def main():
    hits = []
    for dp, _dn, fns in os.walk(ROOT):
        if "__pycache__" in dp:
            continue
        for fn in sorted(fns):
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dp, fn)
            if fn in ("pg_dialect_test.py", "dbx.py"):
                continue
            rel = os.path.relpath(p, ROOT)
            if rel in SKIP_UNTIL_JOB_B:
                continue
            src = open(p, encoding="utf-8").read()
            lines = src.splitlines()
            ok = lambda ln: "pg-ok" in lines[ln - 1] if 0 < ln <= len(lines) else False
            for ln, s in strings(src):
                if not SQL.search(s) and "CONFLICT" not in s and "LIKE" not in s:
                    continue
                for name, rx in IN_SQL:
                    for m in rx.finditer(s):
                        at = ln + s[:m.start()].count("\n")
                        if not ok(at) and not ok(ln):
                            hits.append((rel, at, name))
            for i, line in enumerate(lines, 1):
                code = line.split("#", 1)[0]
                for name, rx in IN_CODE:
                    if rx.search(code) and "pg-ok" not in line and not (name == "sqlite3 driver" and rel in ALLOW_SQLITE):
                        hits.append((rel, i, name))
    hits = sorted(set(hits))
    for rel, ln, name in hits:
        print(f"FAIL kalmido/{rel}:{ln}: {name}")
    by = {}
    for rel, _ln, _n in hits:
        by[rel.split("/")[0]] = by.get(rel.split("/")[0], 0) + 1
    print("per package:", dict(sorted(by.items())))
    print(f"pg_dialect: {len(hits)} hit(s)" if hits else "pg_dialect: ok, 0 failed")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
