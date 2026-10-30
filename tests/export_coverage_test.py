#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.362.0 (#3096) the organisation export guard: every table with an organisation column (org_id) or a list column
(list_id) is either in the organisation export (kalmido/admin/orgexport.py OX_AREAS) or named in OX_LEFT with the reason
why it stays out -- so a new table never goes missing from the export silently. Static like tests/tenant_coverage_test.py:
reads kalmido/core/schema.py (CREATE TABLE + the column migrations) and orgexport.py, no container.
 1. every such table is in OX_AREAS or OX_LEFT
 2. nothing in OX_LEFT is stale (a table that is gone, has no such column any more, or is in OX_AREAS meanwhile)
 3. every reason is a non-empty text
usage: python3 tests/export_coverage_test.py"""
import ast
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402

COLS = ("org_id", "list_id")
SKIP = ("orgs", "lists")  # the organisation and the lists themselves (organisation.json, lists.json)
TYPES = "BIGINT|TEXT|INTEGER|DOUBLE|NUMERIC|BOOLEAN|JSONB|BYTEA|REAL|SMALLINT|DATE|TIMESTAMP"

schema = open(os.path.join(ROOT, "kalmido", "core", "schema.py"), encoding="utf-8").read()
tables = {}
for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", schema, re.S):
    tables.setdefault(m.group(1), set()).update(re.findall(rf"(?:^|,|\()\s*\"?(\w+)\"? (?:{TYPES})", m.group(2)))
for m in re.finditer(r'\("(\w+)", "(\w+)", "ALTER TABLE', schema):
    tables.setdefault(m.group(1), set()).add(m.group(2))
check(len(tables) > 200, f"schema.py read ({len(tables)} tables)")

tree = ast.parse(open(os.path.join(ROOT, "kalmido", "admin", "orgexport.py"), encoding="utf-8").read())
consts = {n.targets[0].id: n.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
areas = {e.elts[1].value for e in consts["OX_AREAS"].elts}
left = {}
for k, v in zip(consts["OX_LEFT"].keys, consts["OX_LEFT"].values):
    left[k.value] = v.value if isinstance(v, ast.Constant) else (ast.literal_eval(consts[v.id]) if isinstance(v, ast.Name) else None)

need = {t for t, cols in tables.items() if any(c in cols for c in COLS) and t not in SKIP}
for t in sorted(need - areas - set(left)):
    check(False, f"{t}: has {'/'.join(c for c in COLS if c in tables[t])} but is neither in OX_AREAS nor in OX_LEFT "
                 "(kalmido/admin/orgexport.py): export it or name why it stays out")
for t in sorted(set(left) - need):
    check(False, f"{t}: stale in OX_LEFT (no such table, or no organisation / list column)")
for t in sorted(set(left) & areas):
    check(False, f"{t}: in OX_AREAS and in OX_LEFT")
for t, why in sorted(left.items()):
    check(isinstance(why, str) and why.strip(), f"{t}: OX_LEFT needs a reason")
check(not (need - areas - set(left)), f"every table with an organisation / list column is accounted for ({len(need)} tables)")

print(f"export_coverage: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
