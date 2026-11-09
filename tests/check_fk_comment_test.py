#!/usr/bin/env python3
# kalmido-suite: after=p2501_a_nosham nodata
"""2.755.0 (#5261): tools/check_fk_comment.py, the #2174 rule as a lint step. Static, no container.
 - a fragment with a new *_id column without a key: red; with REFERENCES, with "no FK: <why>" on its line, or a table with
   "no FK" in its comment block: quiet; the same for a MIGRATIONS step
 - a frozen column (tests/p2103_c_fk_legacy.txt) stays quiet; a frozen line whose column has a key by now: red (the list shrinks)
 - the repository itself: no finding
usage: check_fk_comment_test.py"""
import os
import sys

from kt import FAILS, OKS, check

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from check_fk_comment import findings  # noqa: E402


def frag(body, steps=""):
    return 'SCHEMA = """\n' + body + '\n"""\nMIGRATIONS = [\n' + steps + "]\n"


BAD = frag("CREATE TABLE IF NOT EXISTS t1 (\n  id BIGSERIAL PRIMARY KEY,\n  owner_id BIGINT,\n  note TEXT\n);")
out = findings(src=BAD, old=set())
check(len(out) == 1 and out[0].startswith("t1.owner_id:"), f"a new *_id column without a key is red: {out}")
check(not findings(src=BAD, old={"t1.owner_id"}), "the same column on the frozen list stays quiet")
GOOD = frag("CREATE TABLE IF NOT EXISTS t1 (\n  id BIGSERIAL PRIMARY KEY,\n"
            "  owner_id BIGINT REFERENCES users(id) ON DELETE CASCADE,\n  gone_id BIGINT,  -- no FK: the id of a deleted row\n  x TEXT\n);\n"
            "-- no FK: a log of ids that outlive their rows\nCREATE TABLE IF NOT EXISTS t2 (\n  id BIGSERIAL PRIMARY KEY,\n  user_id BIGINT\n);")
check(not findings(src=GOOD, old=set()), f"REFERENCES, a 'no FK' line and a 'no FK' table stay quiet: {findings(src=GOOD, old=set())}")
STEP_BAD = frag("", '    ("t3", "task_id", "ALTER TABLE t3 ADD COLUMN task_id BIGINT"),\n')
check(findings(src=STEP_BAD, old=set()) and findings(src=STEP_BAD, old=set())[0].startswith("t3.task_id:"), "a MIGRATIONS step without a key is red")
STEP_OK = frag("", '    ("t3", "task_id", "ALTER TABLE t3 ADD COLUMN task_id BIGINT REFERENCES tasks(id) ON DELETE SET NULL"),\n'
               '    ("t3", "row_id", "ALTER TABLE t3 ADD COLUMN row_id BIGINT"),  # no FK: any table\'s row\n')
check(not findings(src=STEP_OK, old=set()), "a step with REFERENCES or 'no FK' stays quiet")
# 2.755.0 (#5261): the other ways to write a step
V = frag("", '    ("t4", "a_id", "ALTER TABLE IF EXISTS t4 ADD COLUMN IF NOT EXISTS a_id BIGINT"),\n'
         '    ("t4", "b_id",\n     "ALTER TABLE t4 ADD COLUMN b_id BIGINT"),\n')
V += 'AFTER = ["ALTER TABLE t5 ADD COLUMN d_id BIGINT"]\n'
out = findings(src=V, old=set())
check(sorted(x.split(":")[0] for x in out) == ["t4.a_id", "t4.b_id", "t5.d_id"], f"IF NOT EXISTS, a wrapped tuple and an AFTER list are red: {out}")
V2 = frag("", '    ("t4", "a_id", "ALTER TABLE t4 ADD COLUMN IF NOT EXISTS a_id BIGINT REFERENCES x(id)"),\n'
          '    # no FK: free id\n    ("t4", "b_id", "ALTER TABLE t4 ADD COLUMN b_id BIGINT"),\n')
check(not findings(src=V2, old=set()), f"REFERENCES / a no-FK comment on the line before stay quiet: {findings(src=V2, old=set())}")
out = findings(src=GOOD, old={"t1.owner_id"})
check(len(out) == 1 and "t1.owner_id has a key by now" in out[0], f"a frozen line whose column has a key is red: {out}")
out = findings()
check(not out, f"the repository: {out}")

print(f"check_fk_comment: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
