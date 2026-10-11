#!/usr/bin/env python3
"""2.37.0 (#1150) row-level security, stage 1 -- the static guard (no container needed, reads kalmido/ like parity_test.py):
 1. every table with a column org_id in kalmido/core/schema.py (CREATE TABLE or a MIGRATIONS entry) is in core/rls.py TABLES,
    or has its own policy (orgs, org_members); nothing in TABLES is stale
 2. orgs and org_members have their own rules
 3. the policy text: "system" passes, the organisation list comes from app.org_ids, an empty setting is NULLIF'd (so an
    unset context means "no organisation", never "everything"); nullable org_id columns keep the private rows
 4. system_ctx is used only with a reason (a comment or docstring on the line or within the 6 lines before)
A new table with an org_id fails here until it is added to TABLES (the start-up adds the policy anyway, with a warning).
usage: python3 tests/rls_static_test.py"""
import ast
import glob
import os
import re

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


schema = read("kalmido/core/schema.py")
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
TABLES, OWN = set(consts.get("TABLES", ())), set(consts.get("OWN_POLICY", ()))
for t in sorted(with_org - OWN):
    check(t in TABLES, f"table {t} has an org_id: add it to core/rls.py TABLES (row-level security)")
for t in sorted(TABLES):
    check(t in with_org, f"core/rls.py TABLES: {t} has no org_id in schema.py (stale entry)")
check(OWN == {"orgs", "org_members"}, "orgs and org_members have their own policies")

# the module has no imports at module level: load it on its own and look at the rules it writes
ns = {}
exec(compile(rls_src, "rls.py", "exec"), ns)  # noqa: S102 -- our own source, no imports
for nullable in (True, False):
    r = ns["rule"](nullable)
    check("NULLIF(current_setting('app.role', true), '') = 'system'" in r, f"rule({nullable}): system passes")
    check("org_id = ANY (string_to_array(NULLIF(current_setting('app.org_ids', true), ''), ',')::bigint[])" in r,
          f"rule({nullable}): organisations from app.org_ids, empty = none")
    check(("org_id IS NULL" in r) == nullable, f"rule({nullable}): private rows only where org_id may be NULL")
own = ns["OWN_RULES"]
check(set(own) == {"orgs", "org_members"} and "id = ANY" in own["orgs"] and "user_id = NULLIF(current_setting('app.user_id', true), '')::bigint" in own["org_members"],
      "orgs: own organisations; org_members: own rows + rows of the own organisations")
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
