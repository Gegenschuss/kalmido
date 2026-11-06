#!/usr/bin/env python3
"""New tables, columns and indexes go into kalmido/core/migrations.d/, not into schema.py (2.475.0, #3478).

Every package used to add its line at the same spot of schema.py (end of MIGRATIONS, the block behind INDEXES): text conflicts
in every queue, though the order of the steps has not mattered since #1996. A fragment <task id>.py has its own place.

tools/migrations_frozen.json names what schema.py held on the cut-off day (plus the steps of packages then under way). What is
there stays where it is, nothing moves; a step, table or index that is not on that list is an error here. The list never grows.
The fragments are plain data, core/db.py frag_load runs them at the start of every process: only SCHEMA, MIGRATIONS and AFTER,
literal values, no import, no code.

2.509.0 (#4285): and only additive steps, so the version before can still run on the database and a step cannot fail on rows that
only the live database has: a MIGRATIONS step adds exactly its column, nullable or with a DEFAULT; AFTER creates indexes, or adds a
column with ADD COLUMN IF NOT EXISTS under the same rules as a step (a table that core/schema.py makes after the steps, #4300);
SCHEMA only creates. A UNIQUE index on a table the fragment does not create itself can fail on existing rows: it needs the line
`# unique-ok <index>: <why no two rows can collide>` in the fragment.

2.574.0 (#3779): one way back out: a table of a feature that was taken out goes with `DROP TABLE IF EXISTS <table>` in AFTER
(runs at every start, a no-op once it is gone). That is a one-way step (its rows are lost, the version before fails on it), so
it needs the line `# drop-ok <table>: <why>` in the fragment, and the table may be created nowhere any more (schema.py or a
fragment), else every start would make it and drop it again. Review F5: `DROP TABLE` without IF EXISTS is a finding of its own (AFTER
runs at every start, the second one would fail); a column of a feature taken out goes the same way with
`ALTER TABLE <table> DROP COLUMN IF EXISTS <column>` in AFTER and the line `# drop-ok <table>.<column>: <why>`, and the column may be
added nowhere any more.

usage: python3 tools/check_migrations.py [-v]     exit code 1 on a finding
"""
import ast
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAG_NAME = re.compile(r"^\d+[a-z0-9_]*\.py$")
FRAG_KEYS = {"SCHEMA", "MIGRATIONS", "AFTER"}
ADD_COLUMN = re.compile(r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+(.+)", re.I | re.S)
CREATE_INDEX = re.compile(r"CREATE\s+(UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+(\w+)\s+ON\s+(?:ONLY\s+)?(\w+)\b", re.I)
CREATE_TABLE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.I)
UNIQUE_OK = re.compile(r"^[ \t]*#[ \t]*unique-ok[ \t]+(\w+)[ \t]*:[ \t]*\S", re.M)
DROP_TABLE = re.compile(r"DROP\s+TABLE\s+(IF\s+EXISTS\s+)?(\w+)", re.I)  # 2.574.0 (#3779); review F5: IF EXISTS checked on its own
DROP_COLUMN = re.compile(r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)\s+DROP\s+COLUMN\s+(IF\s+EXISTS\s+)?(\w+)", re.I)  # review F5
DROP_OK = re.compile(r"^[ \t]*#[ \t]*drop-ok[ \t]+(\w+(?:\.\w+)?)[ \t]*:[ \t]*\S", re.M)


def fragments(root=ROOT):
    return sorted(glob.glob(os.path.join(root, "kalmido", "core", "migrations.d", "*.py")))


def column_made(src, table, col):
    """Review F5 (#3779): does src still create column table.col (in its CREATE TABLE or by ADD COLUMN)?"""
    if re.search(rf"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?{table}\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?{col}\"?\s", src, re.I):
        return True
    for m in re.finditer(rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{table}\s*\(", src, re.I):
        depth, i, body = 1, m.end(), ""
        while i < len(src) and depth:
            depth += (src[i] == "(") - (src[i] == ")")
            body += src[i] if depth == 1 and src[i] != ")" else ","  # the top level only: REFERENCES x(id) names no column here
            i += 1
        if any(re.match(rf"\s*\"?{col}\"?\s", part + " ") for part in body.split(",")):
            return True
    return False


def schema_src(root=ROOT):
    """schema.py + the fragments, as one text: for every check that reads the schema (rls_static, check_layout, the export lists)."""
    out = []
    for p in [os.path.join(root, "kalmido", "core", "schema.py")] + fragments(root):
        with open(p, encoding="utf-8") as f:
            out.append(f.read())
    return "\n".join(out)


def step_ids(src):
    """The ids of the MIGRATIONS lists in src (same counting as core/db.py mig_ids)."""
    seen, out = {}, []
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "MIGRATIONS":
            for e in node.value.elts:
                k = f"{e.elts[0].value}.{e.elts[1].value}"
                seen[k] = seen.get(k, 0) + 1
                out.append(k if seen[k] == 1 else f"{k}#{seen[k]}")
    return out


def names(src):
    """(tables, indexes) created in src."""
    return (set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", src)),
            set(re.findall(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS (\w+)", src)))


def sql_bare(sql):
    """sql without its comments, texts and function bodies: what is left can be read for commas, semicolons and key words."""
    # one pass: a -- inside a text is no comment, an apostrophe in a comment opens no text
    return re.sub(r"'(?:[^']|'')*'|--[^\n]*|\$\$.*?\$\$", lambda m: {"'": "''", "-": " ", "$": "$$"}[m.group(0)[0]], sql, flags=re.S)


def step_finding(table, col, ddl):
    """Why a MIGRATIONS step is not additive (None: it is): exactly its own column, nullable or with a DEFAULT."""
    m = ADD_COLUMN.fullmatch(sql_bare(ddl).strip().rstrip(";").strip())
    if not m:
        return "only ALTER TABLE <table> ADD COLUMN <column> ... (one statement)"
    if (m.group(1), m.group(2)) != (table, col):
        return f"the statement adds {m.group(1)}.{m.group(2)}, the step says {table}.{col} (it would run at every start)"
    rest, depth, flat = m.group(3), 0, ""
    for ch in rest:  # the column's definition outside brackets: NUMERIC(10,2) has a comma of its own
        depth += (ch == "(") - (ch == ")")
        flat += ch if depth == 0 and ch != ")" else ""
    up = " ".join(flat.upper().split())
    if ";" in rest or "," in flat or re.search(r"\b(DROP|RENAME|ALTER)\b", up):
        return "more than one change in the statement"
    if re.search(r"\b(UNIQUE|PRIMARY KEY)\b", up):
        return "a unique column can fail on existing rows: a UNIQUE index in AFTER with a line # unique-ok"
    if re.search(r"\bGENERATED\b", up):
        return "a generated column rewrites the table"
    if "NOT NULL" in up and not re.search(r"\bDEFAULT\b", up):
        return "NOT NULL without a DEFAULT fails on every table with rows"
    return None


def index_finding(stmt, own, ok):
    """Why an index statement is not allowed (None: it is); own = the tables the fragment creates, ok = the indexes it vouches for."""
    bare = sql_bare(stmt).strip().rstrip(";").strip()
    m = CREATE_INDEX.match(bare)
    if not m or ";" in bare:
        return "only one CREATE [UNIQUE] INDEX IF NOT EXISTS (not CONCURRENTLY: the start runs in one transaction)"
    if m.group(1) and m.group(3) not in own and m.group(2) not in ok:
        return f"UNIQUE on the existing table {m.group(3)} can fail on its rows: needs a line # unique-ok {m.group(2)}: <why>"
    return None


# 2.585.0 (#4841): the start keeps a trigger in place when its statement equals pg_get_triggerdef (core/db.py tg_same, #2731);
# a WHEN written otherwise than Postgres prints it never matches, and every start replaces the trigger under a SHARE ROW EXCLUSIVE
# lock on its table (4712_a: `IN ('evcal', ...)` and `'ref'` without its type)
TRIGGER_WHEN = re.compile(r"CREATE\s+OR\s+REPLACE\s+TRIGGER\s+(\w+)\b.*?\bWHEN\s*\((.*)\)\s*EXECUTE\s+(?:FUNCTION|PROCEDURE)\b", re.I | re.S)


def trigger_when_finding(stmt):
    """Why the WHEN of a CREATE OR REPLACE TRIGGER (comments / texts blanked by sql_bare) never equals what Postgres prints (None: fine)."""
    m = TRIGGER_WHEN.match(stmt)
    if not m:
        return None
    w = m.group(2)
    if re.search(r"\bIN\s*\(", w, re.I):
        return "WHEN with IN (...): Postgres prints = ANY (ARRAY[...]), write it that way (else every start replaces it)"
    if re.search(r"''(?!::)", w):
        return "WHEN with a text without its type: Postgres prints 'x'::text, write it that way (else every start replaces it)"
    return None


def content_findings(n, values, src):
    """2.509.0 (#4285): what a fragment's statements do. values = {name: (literal value, line)}."""
    bad = []
    ok = set(UNIQUE_OK.findall(src))
    schema, sl = values.get("SCHEMA", ("", 0))
    stmts = [x.strip() for x in sql_bare(schema).split(";") if x.strip()]
    own = {CREATE_TABLE.match(x).group(1) for x in stmts if CREATE_TABLE.match(x)}
    for x in stmts:
        if not x.upper().startswith("CREATE"):
            bad.append(f"{n}:{sl}: SCHEMA only creates, not: {x[:60]}")
        elif re.match(r"CREATE\s+TABLE\b", x, re.I) and not re.match(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\b", x, re.I):
            bad.append(f"{n}:{sl}: SCHEMA runs at every start: CREATE TABLE IF NOT EXISTS, not: {x[:60]}")
        elif re.match(r"CREATE\s+(UNIQUE\s+)?INDEX\b", x, re.I):
            why = index_finding(x, own, ok)
            if why:
                bad.append(f"{n}:{sl}: SCHEMA: {why}")
        elif TRIGGER_WHEN.match(x):  # 2.585.0 (#4841)
            why = trigger_when_finding(x)
            if why:
                bad.append(f"{n}:{sl}: SCHEMA: trigger {TRIGGER_WHEN.match(x).group(1)}: {why}")
    steps, ml = values.get("MIGRATIONS", ([], 0))
    for table, col, ddl in steps:
        why = step_finding(table, col, ddl)
        if why:
            bad.append(f"{n}:{ml}: step {table}.{col}: {why}")
    after, al = values.get("AFTER", ([], 0))
    for x in after:
        col = ADD_COLUMN.fullmatch(sql_bare(x).strip().rstrip(";").strip())
        drop = DROP_TABLE.fullmatch(sql_bare(x).strip().rstrip(";").strip())
        dcol = DROP_COLUMN.fullmatch(sql_bare(x).strip().rstrip(";").strip())
        if col:  # a column on a table made after the steps (#4300): AFTER runs at every start, so IF NOT EXISTS
            why = step_finding(col.group(1), col.group(2), x)
            if not why and not re.search(r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\b", x, re.I):
                why = "AFTER runs at every start: ADD COLUMN IF NOT EXISTS"
        elif drop:  # 2.574.0 (#3779): the table of a feature taken out, with a reason
            why = "AFTER runs at every start: DROP TABLE IF EXISTS" if not drop.group(1) else \
                None if drop.group(2) in set(DROP_OK.findall(src)) else \
                f"DROP TABLE is a one-way step (its rows are lost): needs a line # drop-ok {drop.group(2)}: <why>"
        elif dcol:  # review F5: a column of a feature taken out, the same way
            key = f"{dcol.group(1)}.{dcol.group(3)}"
            why = "AFTER runs at every start: DROP COLUMN IF EXISTS" if not dcol.group(2) else \
                None if key in set(DROP_OK.findall(src)) else \
                f"DROP COLUMN is a one-way step (its values are lost): needs a line # drop-ok {key}: <why>"
        else:
            why = index_finding(x, own, ok)
        if why:
            bad.append(f"{n}:{al}: AFTER: {why}: {x[:60]}")
    return bad


def frag_findings(path):
    """What makes a fragment more than plain data."""
    n, bad = os.path.basename(path), []
    if not FRAG_NAME.match(n):
        bad.append(f"{n}: the name is the task id (3478.py, 3478_b.py)")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree, values, shape = ast.parse(src, path), {}, len(bad)
    for i, node in enumerate(tree.body):
        if i == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # the docstring
        name = getattr(node.targets[0], "id", "") if isinstance(node, ast.Assign) and len(node.targets) == 1 else ""
        if name not in FRAG_KEYS:
            bad.append(f"{n}:{node.lineno}: only SCHEMA, MIGRATIONS and AFTER, nothing else")
            continue
        try:
            v = ast.literal_eval(node.value)
        except ValueError:
            bad.append(f"{n}:{node.lineno}: {name} is not a literal value")
            continue
        if name == "SCHEMA" and not isinstance(v, str):
            bad.append(f"{n}:{node.lineno}: SCHEMA is a text")
        elif name == "AFTER" and not (isinstance(v, list) and all(isinstance(s, str) for s in v)):
            bad.append(f"{n}:{node.lineno}: AFTER is a list of statements")
        elif name == "MIGRATIONS" and not (isinstance(v, list) and all(
                isinstance(s, tuple) and len(s) == 3 and all(isinstance(x, str) for x in s) for s in v)):
            bad.append(f"{n}:{node.lineno}: MIGRATIONS is a list of (table, column, statement)")
        values[name] = (v, node.lineno)
    return bad + (content_findings(n, values, src) if len(bad) == shape else [])


def findings(root=ROOT):
    with open(os.path.join(root, "kalmido", "core", "schema.py"), encoding="utf-8") as f:
        src = f.read()
    with open(os.path.join(root, "tools", "migrations_frozen.json"), encoding="utf-8") as f:
        fz = json.load(f)
    tables, indexes = names(src)
    new = [f"step {x}" for x in step_ids(src) if x not in set(fz["steps"])]
    new += [f"table {x}" for x in sorted(tables - set(fz["tables"]))]
    new += [f"index {x}" for x in sorted(indexes - set(fz["indexes"]))]
    bad = [f"schema.py: new {x}: belongs into kalmido/core/migrations.d/<task id>.py (docs/ARCHITECTURE.md, Migrations)" for x in new]
    for p in fragments(root):
        bad += frag_findings(p)
    full = schema_src(root)
    made = names(full)[0]
    for p in fragments(root):  # 2.574.0 (#3779): a dropped table that is still created would come back at every start
        with open(p, encoding="utf-8") as f:
            ok = set(DROP_OK.findall(f.read()))
            for t in sorted(ok & made):
                bad.append(f"{os.path.basename(p)}: drops {t}, but schema.py or a fragment still creates it (every start would make it again)")
            for t in sorted(x for x in ok if "." in x and column_made(full, *x.split(".", 1))):  # review F5
                bad.append(f"{os.path.basename(p)}: drops {t}, but schema.py or a fragment still adds it (every start would make it again)")
    return bad


if __name__ == "__main__":
    out = findings()
    for x in out:
        print(x)
    if "-v" in sys.argv or out:
        print(f"check_migrations: {len(fragments())} fragment(s), {len(out)} finding(s)")
    sys.exit(1 if out else 0)
