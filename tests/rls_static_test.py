#!/usr/bin/env python3
"""2.37.0 (#1150) row-level security, stage 1 -- the static guard (no container needed, reads kalmido/ like parity_test.py):
 1. #4314: apply() gives the policy to EVERY base table with a column org_id, taken from the database itself (org_tables),
    with no hand-kept list in between -- a new table with an org_id is protected without an entry anywhere (the property
    is checked here in the code, tests/rls_direct_test.py checks it in a fresh database)
 2. orgs and org_members have their own rules
 3. the policy text: "system" passes, the organisation list comes from app.org_ids, an empty setting is NULLIF'd (so an
    unset context means "no organisation", never "everything"); nullable org_id columns keep the private rows
 4. system_ctx is used only with a reason (a comment or docstring on the line or within the 6 lines before)
usage: python3 tests/rls_static_test.py"""
import ast
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from check_migrations import schema_src  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


schema = schema_src(ROOT)  # 2.475.0 (#3478): + migrations.d
sql = "\n".join(re.sub(r"--.*", "", ln) for ln in schema.split("\n"))
tables, i = {}, 0
for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\(", sql):
    depth, j = 1, m.end()
    while depth and j < len(sql):
        depth += {"(": 1, ")": -1}.get(sql[j], 0)
        j += 1
    tables[m.group(1)] = sql[m.end():j - 1]
with_org = {t for t, body in tables.items() if re.search(r"(^|[\s,(])org_id\s+BIGINT", body)}
with_org |= set(re.findall(r'\(\s*"(\w+)"\s*,\s*"org_id"\s*,', schema))  # MIGRATIONS: ("lists", "org_id", "ALTER TABLE ...")
check(len(with_org) >= 15 and {"lists", "agents", "office_docs", "org_members"} <= with_org,
      f"schema parsed: {len(with_org)} tables with org_id")

rls_src = read("kalmido/core/rls.py")
tree = ast.parse(rls_src)
consts = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        try:
            consts[node.targets[0].id] = ast.literal_eval(node.value)
        except ValueError:
            pass
OWN = set(consts.get("OWN_POLICY", ()))
# #4314 (Karte 17345): the table list is derived, not kept by hand -- the property instead of the list
fn = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
check({"apply", "org_tables", "_policy"} <= set(fn), "core/rls.py has apply(), org_tables() and _policy()")
ot_src = ast.get_source_segment(rls_src, fn["org_tables"]) or ""
ot_sql = re.sub(r"\s+", " ", "".join(re.findall(r'"([^"]*)"', ot_src[ot_src.find("c.execute("):])))
check(ot_sql.strip() == ("SELECT c.table_name, c.is_nullable FROM information_schema.columns c JOIN information_schema.tables t "
                         "ON t.table_schema=c.table_schema AND t.table_name=c.table_name "
                         "WHERE c.table_schema=current_schema() AND c.column_name='org_id' AND t.table_type='BASE TABLE'")
      and "return {r[0]: r[1] == \"YES\" for r in c.execute(" in ot_src,  # #4314 (Fable review): exactly this, no filter
      f"org_tables(): every base table of the schema with a column org_id, nothing filtered out: {ot_sql[:240]}")
ap = fn["apply"]
ap_src = ast.get_source_segment(rls_src, ap) or ""
check(re.search(r"^\s*have = org_tables\(c\)\s*(?:#.*)?\n\s*want = \{t: rule\(nullable\) for t, nullable in have\.items\(\) if t not in OWN_POLICY\}\s*$",
                ap_src, re.M) is not None and (lambda u: u[:1] == [" = org_tables(c)"] and set(u[1:]) <= {".items()", ")"})(  # only read: have.items() / set(have)
                    [m.group(1) for m in re.finditer(r"\bhave\b(\s*=\s*org_tables\(c\)|\.items\(\)|\S*)", ap_src)]),
      "apply(): the tables come from org_tables(c), nothing between it and want, have not changed afterwards")
loops = [n for n in ast.walk(ap) if isinstance(n, ast.For) and "have.items()" in (ast.get_source_segment(rls_src, n.iter) or "")]
loop_ok = False
for lp in loops:
    body = ast.get_source_segment(rls_src, lp) or ""
    ifs = [n for n in lp.body if isinstance(n, ast.If)]
    # the loop over every table of have: the only skip is OWN_POLICY (those get their OWN_RULES below), each other one _policy()
    if len(lp.body) == 1 and ifs and (ast.get_source_segment(rls_src, ifs[0].test) or "").replace(" ", "") == "tnotinOWN_POLICY" \
            and not ifs[0].orelse and "_policy(c, t, rule(nullable))" in body:
        loop_ok = True
check(loop_ok, "apply(): every table of org_tables() except OWN_POLICY gets _policy(c, t, rule(nullable)) - no other filter")
check(re.search(r"for t, expr in OWN_RULES\.items\(\):\s*\n\s*_policy\(c, t, expr\)", ap_src) is not None,
      "apply(): orgs / org_members / time_sheets get their own rules")
# the schema still has tables with an org_id (the parser works, the property above is not vacuous)
check("org_members" in with_org, "org_members is a table with an org_id in schema.py")
check(OWN == {"orgs", "org_members"}, "orgs and org_members have their own policies")

# load the module on its own and look at the rules it writes; 2.1079.0 (#5654): without its relative imports (from .pg import
# qi, table_names for _lock_all) -- the rules need none of them, and importing the package would start the app
ns = {}
exec(compile(re.sub(r"(?m)^from \.\w+ import .*$", "", rls_src), "rls.py", "exec"), ns)  # noqa: S102 -- our own source, no imports
for nullable in (True, False):
    r = ns["rule"](nullable)
    check("NULLIF(current_setting('app.role', true), '') = 'system'" in r, f"rule({nullable}): system passes")
    check("org_id = ANY (string_to_array(NULLIF(current_setting('app.org_ids', true), ''), ',')::bigint[])" in r,
          f"rule({nullable}): organisations from app.org_ids, empty = none")
    check(("org_id IS NULL" in r) == nullable, f"rule({nullable}): private rows only where org_id may be NULL")
own = ns["OWN_RULES"]
# 2.125.0 (#2119): + time_sheets (the general rule or the own rows)
check(set(own) == {"orgs", "org_members", "time_sheets"} and own["time_sheets"] == ns["rule"](True) + " OR user_id = NULLIF(current_setting('app.user_id', true), '')::bigint" and "id = ANY" in own["orgs"] and "user_id = NULLIF(current_setting('app.user_id', true), '')::bigint" in own["org_members"],
      "orgs: own organisations; org_members, time_sheets: own rows + rows of the own organisations")
check("FORCE ROW LEVEL SECURITY" in rls_src and "WITH CHECK" in rls_src, "ENABLE + FORCE, the same rule for writing (WITH CHECK)")
check("NOBYPASSRLS" in rls_src and "SET ROLE" in read("kalmido/core/pg.py"),
      "a login role that bypasses row-level security: the app works as the role without bypass")
db = read("kalmido/core/db.py")
check("rls_apply(c)" in db and db.index("rls_apply(c)") < db.index("pool_refresh()"), "init_db applies the policies, then renews the pool")

# system_ctx only with a reason
n = 0
for p in sorted(glob.glob(os.path.join(ROOT, "kalmido", "**", "*.py"), recursive=True)):
    lines = open(p, encoding="utf-8").read().split("\n")
    for k, ln in enumerate(lines):
        if re.search(r"with (pg_system|system_ctx|_pg\.system_ctx)\(", ln):
            n += 1
            why = "#" in ln or any(x.strip().startswith(("#", '"""')) or x.rstrip().endswith('"""') or "  # " in x
                                   for x in lines[max(0, k - 6):k])
            check(why, f"{os.path.relpath(p, ROOT)}:{k + 1}: system_ctx without a comment why")
check(n >= 10, f"system_ctx is in use ({n} places)")

print(f"\nrls_static: {OKS[0]} ok, {len(FAILS)} failed")
raise SystemExit(1 if FAILS else 0)
