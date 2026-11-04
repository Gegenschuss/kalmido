#!/usr/bin/env python3
"""New tables, columns and indexes go into kalmido/core/migrations.d/, not into schema.py (2.475.0, #3478).

Every package used to add its line at the same spot of schema.py (end of MIGRATIONS, the block behind INDEXES): text conflicts
in every queue, though the order of the steps has not mattered since #1996. A fragment <task id>.py has its own place.

tools/migrations_frozen.json names what schema.py held on the cut-off day (plus the steps of packages then under way). What is
there stays where it is, nothing moves; a step, table or index that is not on that list is an error here. The list never grows.
The fragments are plain data, core/db.py frag_load runs them at the start of every process: only SCHEMA, MIGRATIONS and AFTER,
literal values, no import, no code.

2.509.0 (#4285): and only additive steps, so the version before can still run on the database and a step cannot fail on rows that
only the live database has: a MIGRATIONS step adds exactly its column, nullable or with a DEFAULT; AFTER creates indexes only;
SCHEMA only creates. A UNIQUE index on a table the fragment does not create itself can fail on existing rows: it needs the line
`# unique-ok <index>: <why no two rows can collide>` in the fragment.

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


def fragments(root=ROOT):
    return sorted(glob.glob(os.path.join(root, "kalmido", "core", "migrations.d", "*.py")))


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
    steps, ml = values.get("MIGRATIONS", ([], 0))
    for table, col, ddl in steps:
        why = step_finding(table, col, ddl)
        if why:
            bad.append(f"{n}:{ml}: step {table}.{col}: {why}")
    after, al = values.get("AFTER", ([], 0))
    for x in after:
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
    return bad


if __name__ == "__main__":
    out = findings()
    for x in out:
        print(x)
    if "-v" in sys.argv or out:
        print(f"check_migrations: {len(fragments())} fragment(s), {len(out)} finding(s)")
    sys.exit(1 if out else 0)
