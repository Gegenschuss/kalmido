#!/usr/bin/env python3
"""2.183.0 B (#2666): a start next to the running server takes no table locks for policies / indexes that are in place.
Against a fresh container (its own start applied everything), core/rls.py apply() and the index filter of init_db run in a
second process inside the container (like a CLI or a helper importing the app):
 - nothing changed -> apply() reports "skipped" and holds no ACCESS EXCLUSIVE relation lock afterwards
 - the policy of a table dropped, FORCE or ENABLE switched off, the expression altered by hand, the function body of
   kalmido_org_count changed -> the next apply() restores it (catalog check), the one after it skips again
 - an older / foreign rls_sig in kalmido_meta (a restored backup) -> applied again
 - a changed rule in the code (POLICY_FORM) and a new table with org_id -> applied again, the new table gets its policy
 - the schema / index scripts of init_db keep no CREATE INDEX for existing indexes; a dropped index stays in and comes back
   with the next start
Importing kalmido starts it (init_db): each docker exec is "a start next to the running server".
usage: p2183_b_rls_skip_test.py <datadir>      (a fresh container)"""
import json
import os
import re
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)
T = "lists"  # an organisation table with the standard rule


def sql(q, args=(), write=False):
    """Superuser connection of the test database (bypasses row-level security)."""
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=20)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def in_ct(code):
    """Python inside the app container, without loading the app (no init_db); the last stdout line is JSON."""
    for _ in range(4):  # a deadlock with the running server is the helper's problem, not the check's
        r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=180)
        if r.returncode == 0 or "deadlock detected" not in r.stdout + r.stderr:
            break
        time.sleep(2)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# importing kalmido starts it (startup.py: init_db) -- "boot" is what that start's apply() did; then one more apply() in the
# same process with {pre} (a changed rule) and the relation locks it holds
APPLY = ("import json\nfrom kalmido.core import rls\nfrom kalmido.core.db import DATABASE_URL\nfrom kalmido.core.pg import connect_direct\n"
         "boot = rls.STATE['policies']\n{pre}\no = connect_direct(DATABASE_URL)\nok = rls.apply(o)\n"
         "n = o.execute(\"SELECT COUNT(*) FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='relation' "
         "AND mode='AccessExclusiveLock'\").fetchone()[0]\no.commit()\no.close()\n"
         "print(json.dumps({{'boot': boot, 'policies': rls.STATE['policies'], 'enforced': ok, 'locks': n}}))")


def apply(pre=""):
    return in_ct(APPLY.format(pre=pre))


def pol(table):
    """(ENABLE, FORCE, the policy's USING expression or None)."""
    r = sql("SELECT c.relrowsecurity, c.relforcerowsecurity, pg_get_expr(p.polqual, p.polrelid) FROM pg_class c "
            "LEFT JOIN pg_policy p ON p.polrelid=c.oid AND p.polname='kalmido_org' "
            "WHERE c.relname=? AND c.relnamespace=current_schema()::regnamespace", (table,))
    return tuple(r[0]) if r else (None, None, None)


# the container's own start applied everything: a second start changes nothing
r = apply()
check(r["boot"] == "skipped" and r["policies"] == "skipped" and r["locks"] == 0 and r["enforced"],
      f"#2666: unchanged -> skipped at the start and after it, no exclusive lock {r}")
good = pol(T)
check(good[0] and good[1] and good[2] and "app.org_ids" in good[2], f"#2666: {T} has its policy {good}")

# the catalog decides along: every way a policy can go missing or stale is repaired at the next start
for what, stmt in (("policy dropped", f"DROP POLICY kalmido_org ON {T}"),
                   ("FORCE off", f"ALTER TABLE {T} NO FORCE ROW LEVEL SECURITY"),
                   ("ENABLE off", f"ALTER TABLE {T} DISABLE ROW LEVEL SECURITY"),
                   ("expression altered", f"ALTER POLICY kalmido_org ON {T} USING (true) WITH CHECK (true)"),
                   ("orgs policy dropped", "DROP POLICY kalmido_org ON orgs")):
    sql(stmt, write=True)
    r = apply()
    check(r["boot"] == "applied" and r["policies"] == "skipped" and r["locks"] == 0, f"#2666: {what} -> applied at the start {r}")
    o = pol("orgs")
    check(pol(T) == good and o[0] and o[1] and o[2], f"#2666: {what} -> restored {pol(T)} {o}")
check(apply()["boot"] == "skipped", "#2666: skipped after the repairs")
# 2.183.0 (review): another policy on the table is never skipped over (applied at every start, with a warning)
sql(f"CREATE POLICY p2183_extra ON {T} USING (true)", write=True)
check(apply()["boot"] == "applied" and apply()["boot"] == "applied", "#2666: another policy -> applied every start")
sql(f"DROP POLICY p2183_extra ON {T}", write=True)
check(apply()["boot"] == "applied" and apply()["boot"] == "skipped", "#2666: the other policy gone -> skipped again")

# a restored backup brings an older kalmido_meta: the stored value does not match -> applied
sql("UPDATE kalmido_meta SET value='0:0' WHERE key='rls_sig'", write=True)
check(apply()["boot"] == "applied", "#2666: an older rls_sig -> applied")
sql("DELETE FROM kalmido_meta WHERE key='rls_sig'", write=True)
check(apply()["boot"] == "applied", "#2666: no rls_sig -> applied")
check(apply()["boot"] == "skipped", "#2666: then skipped")

# a change of the rules in the code -> applied (and the next start with the code's rules applies once more)
check(apply("rls.POLICY_FORM += ' (changed)'")["policies"] == "applied", "#2666: a changed policy form -> applied")
r = apply()
check(r["boot"] == "applied" and r["policies"] == "skipped", f"#2666: back to the code's form -> applied once {r}")
check(apply("rls.OWN_RULES = dict(rls.OWN_RULES, orgs=rls.OWN_RULES['orgs'] + ' OR false')")["policies"] == "applied",
      "#2666: a changed rule -> applied")
check("false" in (pol("orgs")[2] or ""), f"#2666: the changed rule is in the catalog {pol('orgs')}")
check(apply()["boot"] == "applied" and "false" not in (pol("orgs")[2] or ""), f"#2666: the code's rule again {pol('orgs')}")

# a new table with an org_id gets its policy (with the warning); its removal changes the set again
sql("CREATE TABLE p2183b_probe (id BIGSERIAL PRIMARY KEY, org_id BIGINT)", write=True)
try:
    check(apply()["boot"] == "applied", "#2666: a new table -> applied")
    p = pol("p2183b_probe")
    check(p[0] and p[1] and p[2] and "IS NULL" in p[2], f"#2666: the new table has the policy (nullable org_id) {p}")
    check(apply()["boot"] == "skipped", "#2666: the new table -> skipped next time")
finally:
    sql("DROP TABLE IF EXISTS p2183b_probe", write=True)
r1, r2 = apply()["boot"], apply()["boot"]
check((r1, r2) == ("applied", "skipped"), f"#2666: table gone -> applied once, then skipped {r1} {r2}")

# kalmido_org_count: replaced only when its body differs
sql("CREATE OR REPLACE FUNCTION kalmido_org_count() RETURNS bigint LANGUAGE plpgsql STABLE AS $f$BEGIN RETURN 0; END$f$", write=True)
apply()
src = sql("SELECT prosrc FROM pg_proc WHERE proname='kalmido_org_count'")
check(src and "personal_of IS NULL" in src[0][0], f"#2666: kalmido_org_count restored {src}")

# the index scripts of init_db: only missing indexes are left in; a dropped one is in the script and back after a start
IX = ("import json\nfrom kalmido.core.db import DATABASE_URL, ix_have, ix_skip_present, _IX_LINE\nfrom kalmido.core.pg import connect_direct\n"
      "from kalmido.core.schema import SCHEMA, INDEXES\no = connect_direct(DATABASE_URL)\nh = ix_have(o)\no.rollback()\no.close()\n"
      "name = [n for n in _IX_LINE.findall(SCHEMA) if 'tasks' in n][0]\n"
      "idx = [m.group(1) for m in (_IX_LINE.search(s + ';') for s in INDEXES.split(';')) if m and m.group(1).lower() not in h]\n"
      "print(json.dumps({'all': len(_IX_LINE.findall(SCHEMA)), 'left': _IX_LINE.findall(ix_skip_present(SCHEMA, h)), 'idx': idx, "
      "'tables': SCHEMA.count('CREATE TABLE') == ix_skip_present(SCHEMA, h).count('CREATE TABLE'), 'name': name, "
      "'without': _IX_LINE.findall(ix_skip_present(SCHEMA, h - {name}))}))")
r = in_ct(IX)
check(r["all"] > 100 and r["left"] == [] and r["idx"] == [] and r["tables"], f"#2666: no CREATE INDEX for existing indexes {r}")
check(r["without"] == [r["name"]], f"#2666: a missing index stays in the script {r['without']}")
sql(f"DROP INDEX {r['name']}", write=True)
check(apply()["boot"] == "skipped", "#2666: a start after the index went")
check(sql("SELECT 1 FROM pg_class WHERE relname=?", (r["name"],)) == [(1,)], f"#2666: the start created {r['name']} again")
check(in_ct(IX)["left"] == [], "#2666: nothing left after the start")

print(f"p2183_b_rls_skip: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
