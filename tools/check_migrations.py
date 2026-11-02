#!/usr/bin/env python3
"""New tables, columns and indexes go into kalmido/core/migrations.d/, not into schema.py (2.475.0, #3478).

Every package used to add its line at the same spot of schema.py (end of MIGRATIONS, the block behind INDEXES): text conflicts
in every queue, though the order of the steps has not mattered since #1996. A fragment <task id>.py has its own place.

tools/migrations_frozen.json names what schema.py held on the cut-off day (plus the steps of packages then under way). What is
there stays where it is, nothing moves; a step, table or index that is not on that list is an error here. The list never grows.
The fragments are plain data, core/db.py frag_load runs them at the start of every process: only SCHEMA, MIGRATIONS and AFTER,
literal values, no import, no code.

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


def frag_findings(path):
    """What makes a fragment more than plain data."""
    n, bad = os.path.basename(path), []
    if not FRAG_NAME.match(n):
        bad.append(f"{n}: the name is the task id (3478.py, 3478_b.py)")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
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
    return bad


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
