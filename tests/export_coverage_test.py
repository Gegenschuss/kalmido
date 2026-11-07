#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.362.0 (#3096) the organisation export guard: every table with an organisation column (org_id) or a list column
(list_id) is either in the organisation export (kalmido/admin/orgexport.py OX_AREAS) or named in OX_LEFT with the reason
why it stays out -- so a new table never goes missing from the export silently. Static like tests/tenant_coverage_test.py:
reads kalmido/core/schema.py (CREATE TABLE + the column migrations) and orgexport.py, no container.
 1. every such table is in OX_AREAS or OX_LEFT
 2. nothing in OX_LEFT is stale (a table that is gone, has no such column any more, or is in OX_AREAS meanwhile)
 3. every reason is a non-empty text
2.362.2 (#3105) the same for the retention export (kalmido/admin/retexport.py): every office_* table is in RX_TABLES or RX_LEFT_TABLES (kalmido/admin/exportleft.py),
RX_LEFT_TABLES is not stale, every RX_TABLES table is in OX_AREAS (its rows come from there) and every folder has a section in the index
2.455.0 (#3469) the same for the account export: every table with a person column (user_id) and the list tables of the decision of
#3469 are read by the queries of the account export (kalmido/accounts/settings.py, kalmido/admin/acctexport.py) or named in
UMZ_LEFT_TABLES (exportleft.py) with the reason; the list is not stale; every agent is named in UMZ_NOT_INCLUDED (keys never move)
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

# 2.455.0 (#3469): without the comments: a column behind a comment line was not seen (issue_reports.list_id)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from check_migrations import schema_src  # noqa: E402

schema = re.sub(r"--[^\n]*", "", schema_src(ROOT))  # 2.475.0 (#3478): + migrations.d
tables = {}
for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", schema, re.S):
    body = re.sub(r"--[^\n]*", "", m.group(2))  # 2.362.4 (#3107): a comment must not hide the column after it
    tables.setdefault(m.group(1), set()).update(re.findall(rf"(?:^|,|\()\s*\"?(\w+)\"?\s+(?:{TYPES})", body))
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

# 2.362.2 (#3105): the retention export
rtree = ast.parse(open(os.path.join(ROOT, "kalmido", "admin", "retexport.py"), encoding="utf-8").read())
rc = {n.targets[0].id: n.value for n in rtree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
rx = {e.elts[1].value: e.elts[0].value for e in rc["RX_TABLES"].elts}
# 2.619.0 (#3862): one list per export, in exportleft.py (was RX_LEFT / UMZ_LEFT_USERS next to it)
ltree = ast.parse(open(os.path.join(ROOT, "kalmido", "admin", "exportleft.py"), encoding="utf-8").read())
lc = {n.targets[0].id: n.value for n in ltree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
rleft = {k.value: True for k in lc["RX_LEFT_TABLES"].keys}
office = {t for t in tables if t.startswith("office_")}
check(len(rx) == len(rc["RX_TABLES"].elts), "RX_TABLES: no table twice")
for t in sorted(office - set(rx) - set(rleft)):
    check(False, f"{t}: an office table neither in RX_TABLES nor in RX_LEFT_TABLES (kalmido/admin/exportleft.py): keep it or name why it stays out")
for t in sorted(set(rleft) - office):
    check(False, f"{t}: stale in RX_LEFT_TABLES (no such table)")
for t in sorted(set(rleft) & set(rx)):
    check(False, f"{t}: in RX_TABLES and in RX_LEFT_TABLES")
for t in sorted(set(rx) - areas):
    check(False, f"{t}: in RX_TABLES but not in OX_AREAS (the export would leave it out silently)")
sections = {e.elts[0].value for e in rc["RX_SECTIONS"].elts}
for t, arc in sorted(rx.items()):
    check(arc.split("/")[0] in sections, f"{arc}: its folder has no line in RX_SECTIONS (the index would not name it)")
check(not (office - set(rx) - set(rleft)), f"every office table is accounted for in the retention export ({len(office)} tables)")

# 2.455.0 (#3469): the account export
atext = open(os.path.join(ROOT, "kalmido", "admin", "acctexport.py"), encoding="utf-8").read()
atree = ast.parse(atext)
ac = {n.targets[0].id: n.value for n in atree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
uleft = {k.value for k in lc["UMZ_LEFT_TABLES"].keys}  # also org / list / task tables: the lint (tools/check_export_tables.py) holds those columns
qtext = atext + open(os.path.join(ROOT, "kalmido", "accounts", "settings.py"), encoding="utf-8").read()
exported = {t for t in tables if re.search(rf"(?:FROM|JOIN) {t}\b", qtext)}
uneed = {t for t, cols in tables.items() if "user_id" in cols}
for t in ("sprints", "task_links", "list_rules", "portal_tickets"):  # #3469: list tables, no person column
    check(t in exported, f"{t}: not in the account export (decision of #3469)")
for t in sorted(uneed - exported - set(uleft)):
    check(False, f"{t}: has user_id but is neither in the account export nor in UMZ_LEFT_TABLES (kalmido/admin/exportleft.py): export it or name why it stays out")
for t in sorted(uleft - set(tables)):
    check(False, f"{t}: stale in UMZ_LEFT_TABLES (no such table)")  # the lint holds the other columns (tools/check_export_tables.py)
# "exported and left out" is held by tools/check_export_tables.py (its test: export_tables_lint): the regex above also sees a mention in a comment
check(any("agents" in str(getattr(e, "args", [None])[0].value if getattr(e, "args", None) else "") for e in ac["UMZ_NOT_INCLUDED"].elts), "UMZ_NOT_INCLUDED names the agents")
check(not (uneed - exported - set(uleft)), f"every table with a person column is accounted for in the account export ({len(uneed)} tables)")

print(f"export_coverage: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
