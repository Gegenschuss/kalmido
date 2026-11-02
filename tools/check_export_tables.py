#!/usr/bin/env python3
"""2.362.4 (#3107): no table with people's data goes missing from an export silently. Static (bare Python 3.12, no app import, the CI
lint step): reads kalmido/core/schema.py (CREATE TABLE + the column migrations) and holds every table with a person, organisation,
list or task column against
 - the account export (accounts/settings.py umz_export_queries, admin/acctexport.py umz_extra_queries / umz_mine_queries / umz_build)
   or admin/exportleft.py UMZ_LEFT_TABLES, with the reason why it stays out
 - the organisation export (admin/orgexport.py OX_AREAS) or OX_LEFT (tables with an organisation or a list column)
 - the retention export (admin/retexport.py RX_TABLES) or exportleft.py RX_LEFT_TABLES (the office tables)
 - the imports: every part of the account export is read (acctimport.py UMZ_READ) or named as staying behind (UMZ_LEFT), every
   area of the organisation export is mapped (UMZ_ORG_MAP), read by an area of admin/oi_*.py or named (UMZ_ORG_SKIP)
Nothing in a list may be stale either: a reason for a table that is gone or exported meanwhile fails too.
usage: python3 tools/check_export_tables.py [-v] [--root DIR]      exit 1 on a finding"""
import ast
import glob
import os
import re
import sys

from check_migrations import schema_src

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TYPES = "BIGINT|TEXT|INTEGER|DOUBLE|NUMERIC|BOOLEAN|JSONB|BYTEA|REAL|SMALLINT|DATE|TIMESTAMP"
PEOPLE = ("user_id", "owner_id", "created_by", "org_id", "list_id", "task_id")
ORG_COLS = ("org_id", "list_id")
# the tables that carry the others (the account's own row, the export's frame): never a finding
FRAME = ("users",)
# the parts umz_build writes itself: {part of the file: table}
BUILD_PARTS = {"people": None, "server_links": "msv_links", "budgets": None}


def read(root, *p):
    with open(os.path.join(root, *p), encoding="utf-8") as f:
        return f.read()


def schema_tables(root):
    src = schema_src(root)  # 2.475.0 (#3478): + migrations.d
    tables = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", src, re.S):
        body = re.sub(r"--[^\n]*", "", m.group(2))  # a comment at a line's end must not hide the column on the next line
        tables.setdefault(m.group(1), set()).update(re.findall(rf"(?:^|,|\()\s*\"?(\w+)\"?\s+(?:{TYPES})", body))
    for m in re.finditer(r'\("(\w+)", "(\w+)", "ALTER TABLE', src):
        tables.setdefault(m.group(1), set()).add(m.group(2))
    return tables


def text_of(node):
    """The text of a (joined) string node; the {...} parts of an f-string count as nothing."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(text_of(v) for v in node.values)
    return ""


def top_from(sql):
    """The tables after each FROM outside parentheses (a subselect in the column list or the WHERE is no source of the rows)."""
    depth, out = 0, []
    for m in re.finditer(r"[()]|\bFROM\s+(\w+)", sql, re.I):
        if m.group(0) == "(":
            depth += 1
        elif m.group(0) == ")":
            depth -= 1
        elif not depth:
            out.append(m.group(1))
    return out


def queries_in(tree, fn):
    """{part: main tables} of the dict(s) of queries in function fn: the FROM of the query and of each UNION ALL."""
    out = {}
    f = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn)
    for d in ast.walk(f):
        if not isinstance(d, ast.Dict):
            continue
        for k, v in zip(d.keys, d.values):
            if isinstance(k, ast.Constant) and isinstance(v, ast.Tuple) and v.elts:
                out[k.value] = top_from(text_of(v.elts[0]))
    return out


def assigned(tree, name):
    return next(n.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name)


def strings(node):
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def reasons(tree, name):
    """{table: reason} of a dict of reasons in a module of plain assignments (names of other reasons resolved)."""
    names = {n.targets[0].id: n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
             and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
    d = assigned(tree, name)
    out = {}
    for k, v in zip(d.keys, d.values):
        out[k.value] = v.value if isinstance(v, ast.Constant) else names.get(getattr(v, "id", ""))
    return out


def check(root):
    tables = schema_tables(root)
    bad = []
    stats = {"tables": len(tables)}
    admin = ("kalmido", "admin")
    # ---- account export
    parts = {}
    parts.update(queries_in(ast.parse(read(root, "kalmido", "accounts", "settings.py")), "umz_export_queries"))
    acct = ast.parse(read(root, *admin, "acctexport.py"))
    for fn in ("umz_extra_queries", "umz_mine_queries"):
        parts.update(queries_in(acct, fn))
    left_tree = ast.parse(read(root, *admin, "exportleft.py"))
    left, rx_left = reasons(left_tree, "UMZ_LEFT_TABLES"), reasons(left_tree, "RX_LEFT_TABLES")
    inc = {t for v in parts.values() for t in v} | {t for t in BUILD_PARTS.values() if t} | set(ast.literal_eval(assigned(left_tree, "UMZ_BUILD_TABLES")))
    need = {t for t, c in tables.items() if any(x in c for x in PEOPLE) and t not in FRAME}
    stats["account"] = len(need)
    for t in sorted(need - inc - set(left)):
        bad.append(f"{t}: has {'/'.join(x for x in PEOPLE if x in tables[t])} but is neither in the account export nor in UMZ_LEFT_TABLES "
                   "(kalmido/admin/exportleft.py): export it or name why it stays out")
    for t in sorted(set(left) - need):
        bad.append(f"{t}: stale in UMZ_LEFT_TABLES (no such table, or no person / organisation / list / task column)")
    for t in sorted(set(left) & inc):
        bad.append(f"{t}: in the account export and in UMZ_LEFT_TABLES")
    # ---- organisation export
    ox = ast.parse(read(root, *admin, "orgexport.py"))
    areas = {e.elts[0].value: e.elts[1].value for e in assigned(ox, "OX_AREAS").elts}
    ox_left = reasons(ox, "OX_LEFT")
    onames = {t for t, c in tables.items() if any(x in c for x in ORG_COLS) and t not in ("orgs", "lists")}
    stats["organisation"] = len(onames)
    for t in sorted(onames - set(areas.values()) - set(ox_left)):
        bad.append(f"{t}: has an organisation / list column but is neither in OX_AREAS nor in OX_LEFT (kalmido/admin/orgexport.py)")
    for t in sorted(set(ox_left) - onames):
        bad.append(f"{t}: stale in OX_LEFT")
    # ---- retention export
    rx = ast.parse(read(root, *admin, "retexport.py"))
    rx_t = {e.elts[1].value for e in assigned(rx, "RX_TABLES").elts}
    office = {t for t in tables if t.startswith("office_")}
    stats["retention"] = len(office)
    for t in sorted(office - rx_t - set(rx_left)):
        bad.append(f"{t}: an office table neither in RX_TABLES (kalmido/admin/retexport.py) nor in RX_LEFT_TABLES (exportleft.py)")
    for t in sorted(set(rx_left) - office):
        bad.append(f"{t}: stale in RX_LEFT_TABLES")
    for t in sorted(set(rx_left) & rx_t):
        bad.append(f"{t}: in RX_TABLES and in RX_LEFT_TABLES")
    for t in sorted(rx_t - set(tables)):
        bad.append(f"{t}: in RX_TABLES but not in the schema")
    # ---- imports
    imp = ast.parse(read(root, *admin, "acctimport.py"))
    known = strings(assigned(imp, "UMZ_READ")) | strings(assigned(imp, "UMZ_LEFT"))
    for p in sorted((set(parts) | set(BUILD_PARTS)) - known):
        bad.append(f"{p}: a part of the account export that acctimport.py neither reads (UMZ_READ) nor names (UMZ_LEFT)")
    omap, skip = strings(assigned(imp, "UMZ_ORG_MAP")), [e.elts[0].value for e in assigned(imp, "UMZ_ORG_SKIP").elts]
    oit = set()
    for f in glob.glob(os.path.join(root, *admin, "oi_*.py")) + [os.path.join(root, *admin, "orgimport.py")]:
        with open(f, encoding="utf-8") as fh:
            oit.update(re.findall(r'OiT\(\s*"([^"]+)"', fh.read()))
    for p in sorted(areas):
        if p not in omap and p not in oit and not any(p.startswith(x) for x in skip):
            bad.append(f"{p}: an area of the organisation export that the import neither maps (UMZ_ORG_MAP, admin/oi_*.py OiT) nor names (UMZ_ORG_SKIP)")
    return bad, stats


def main():
    a = sys.argv[1:]
    root = a[a.index("--root") + 1] if "--root" in a else ROOT
    bad, st = check(root)
    for b in bad:
        print("check_export_tables:", b)
    print(f"check_export_tables: {st['tables']} tables, {st['account']} with people's data, {st['organisation']} with an organisation or list column, "
          f"{st['retention']} office tables, {len(bad)} finding(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
