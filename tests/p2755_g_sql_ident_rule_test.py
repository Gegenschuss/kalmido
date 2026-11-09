#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.755.0 (#5296 review): the regexes of .semgrep/sql_ident.yml hit what they should. Static (python re with the same patterns
as semgrep's pattern-regex), no semgrep and no container.
 - FROM / JOIN / INTO / UPDATE / SET / TABLE / TRUNCATE / INDEX x ON {name} without qi( : red
 - the same with {qi(name, ALLOWED)}: quiet; plain text, a non-f-string and a lowercase-free sentence: quiet
usage: p2755_g_sql_ident_rule_test.py"""
import os
import re
import sys

from kt import FAILS, OKS, check

HERE = os.path.dirname(os.path.abspath(__file__))
YML = open(os.path.join(HERE, "..", ".semgrep", "sql_ident.yml"), encoding="utf-8").read()
PATS = [re.compile(m.group(1)) for m in re.finditer(r"^\s*- pattern-regex: (.+)$", YML, re.M)]
check(len(PATS) == 2, f"the rule has a one-line and a triple-quote regex: {len(PATS)}")


def hit(code):
    return any(p.search(code) for p in PATS)


RED = ['c.execute(f"SELECT id FROM {t} WHERE x=?", (1,))',
       "c.execute(f'UPDATE {t} SET a=1')",
       'c.execute(f"DELETE FROM x WHERE 1 AND y IN (SELECT 1 FROM {t})")',
       'c.execute(f"TRUNCATE {t}")',
       'c.execute(f"DROP TABLE {t}")',
       'c.execute(f"CREATE INDEX i_x ON {t} (a)")',
       'c.execute(f"""\n  SELECT 1\n  FROM {t}\n""")',
       'c.execute(rf"INSERT INTO {t}(a) VALUES (?)")']
GREEN = ['c.execute(f"SELECT id FROM {qi(t, TABLES)} WHERE x=?", (1,))',
         'c.execute(f"TRUNCATE {qi(t, TABLES)}")',
         'c.execute(f"CREATE INDEX i_x ON {qi(t, TABLES)} (a)")',
         'c.execute("SELECT id FROM users WHERE x=?", (1,))',
         'msg = f"Moving files from {src} to {dst}"',
         'x = f"hello {name}, welcome"',
         'c.execute(f"""\n  SELECT 1\n  FROM {qi(t, TABLES)}\n""")']
for code in RED:
    check(hit(code), f"red: {code!r}")
for code in GREEN:
    check(not hit(code), f"quiet: {code!r}")

print(f"p2755_g_sql_ident_rule: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
