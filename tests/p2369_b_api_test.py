#!/usr/bin/env python3
# kalmido-suite:
"""2.369.0 B (#2731): a start next to the running server replaces no trigger and builds no index that is in place.
Against a fresh container (its own start set everything up), a second process inside the container imports the app (a start,
like tests/p2183_b_rls_skip_test.py) and notes at every COMMIT which strong table locks its transaction held:
 - nothing changed -> no SHARE or stronger lock on any table, every trigger row untouched (xmin)
 - a trigger dropped, its definition changed (events, columns, timing, WHEN, row / statement, arguments, function) or switched
   off -> the start repairs exactly that (and the lock shows that the probe sees locks); then quiet again
 - a function behind a trigger changed -> back from the start, without a table lock
 - an index dropped (each of the former IF NOT EXISTS places) or the column of the INDEXES script -> back from the start
 - tg_norm: the same statement in other spelling is equal, every real difference is not
usage: p2369_b_api_test.py <datadir>      (a fresh container)"""
import json
import os
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check


def sql(q, args=(), write=False):
    """Superuser connection of the test database."""
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
    """Python inside the app container; the last stdout line is JSON."""
    for _ in range(4):  # a deadlock with the running server is the helper's problem, not the check's
        r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=180)
        if r.returncode == 0 or "deadlock detected" not in r.stdout + r.stderr:
            break
        time.sleep(2)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# a start (importing kalmido) with a look at the locks of every transaction right before its COMMIT
START = """import json
import psycopg
from psycopg.rows import tuple_row
seen, commits, orig = set(), [0], psycopg.Connection.commit
Q = ("SELECT relation::regclass::text, mode FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='relation' "
     "AND mode IN ('ShareLock', 'ShareRowExclusiveLock', 'ExclusiveLock', 'AccessExclusiveLock')")
def commit(self):
    commits[0] += 1
    with self.cursor(row_factory=tuple_row) as k:
        seen.update(f"{t} {m}" for t, m in k.execute(Q).fetchall())
    return orig(self)
psycopg.Connection.commit = commit
from kalmido.core import rls
print(json.dumps({'commits': commits[0], 'locks': sorted(seen), 'rls': rls.STATE['policies']}))"""


def start():
    return in_ct(START)


def defs():
    """Every trigger of the app: its definition as Postgres has it and whether it is on."""
    return {f"{t}.{n}": [d, e] for t, n, d, e in sql(
        "SELECT t.tgrelid::regclass::text, t.tgname, pg_get_triggerdef(t.oid), t.tgenabled::text FROM pg_trigger t "
        "WHERE NOT t.tgisinternal")}


def rows():
    return {f"{t}.{n}": x for t, n, x in sql(
        "SELECT tgrelid::regclass::text, tgname, xmin::text FROM pg_trigger WHERE NOT tgisinternal")}


def quiet(what):
    before = rows()
    r = start()
    check(r["commits"] > 0 and r["locks"] == [], f"#2731: {what}: a start takes no strong table lock {r}")
    after = rows()
    check(before == after, f"#2731: {what}: no trigger replaced {[k for k in after if before.get(k) != after[k]]}")


# the container's own start set everything up; the first start here may still settle one-shots
good = defs()
for name in ("list_members.list_e2e_members", "org_members.wiki_e2e_members", "time_entries.time_title_e2e", "tasks.time_task_list",
             "tasks.time_task_title", "tasks.kalmido_dl_tasks", "orgs.kalmido_acx_orgs", "tasks.kalmido_ml_task",
             "tasks.kalmido_fts_task_upd", "tasks.kalmido_sec_at", "tasks.kalmido_ticket_no", "api_tokens.kalmido_revoked_api_tokens",
             "lists.kalmido_purged_lists"):
    check(name in good, f"#2731: trigger {name} is there")
quiet("unchanged")
quiet("unchanged, again")

TIME_E2E = "ON time_entries FOR EACH ROW EXECUTE FUNCTION kalmido_time_title_e2e()"
for what, table, trig, stmt in (
        ("dropped e2e", "list_members", "list_e2e_members", "DROP TRIGGER list_e2e_members ON list_members"),
        ("dropped e2e", "org_members", "wiki_e2e_members", "DROP TRIGGER wiki_e2e_members ON org_members"),
        ("dropped e2e", "time_entries", "time_title_e2e", "DROP TRIGGER time_title_e2e ON time_entries"),
        ("dropped delta", "comments", "kalmido_dl_comments", "DROP TRIGGER kalmido_dl_comments ON comments"),
        ("dropped in SCHEMA", "tasks", "time_task_list", "DROP TRIGGER time_task_list ON tasks"),
        ("event gone", "time_entries", "time_title_e2e", f"CREATE OR REPLACE TRIGGER time_title_e2e BEFORE INSERT {TIME_E2E}"),
        ("column gone", "list_members", "list_e2e_members",
         "CREATE OR REPLACE TRIGGER list_e2e_members BEFORE INSERT OR UPDATE OF role OR DELETE ON list_members FOR EACH ROW "
         "EXECUTE FUNCTION kalmido_list_e2e_members()"),
        ("timing", "org_members", "wiki_e2e_members",
         "CREATE OR REPLACE TRIGGER wiki_e2e_members AFTER INSERT OR UPDATE OF org_id, user_id OR DELETE ON org_members FOR EACH ROW "
         "EXECUTE FUNCTION kalmido_wiki_e2e_members()"),
        ("WHEN", "tasks", "time_task_list",
         "CREATE OR REPLACE TRIGGER time_task_list AFTER UPDATE OF list_id ON tasks FOR EACH ROW "
         "WHEN (NEW.list_id IS NOT DISTINCT FROM OLD.list_id) EXECUTE FUNCTION kalmido_time_task_list()"),
        ("one branch of WHEN", "tasks", "kalmido_fts_task_upd",
         "CREATE OR REPLACE TRIGGER kalmido_fts_task_upd AFTER UPDATE OF title, content ON tasks FOR EACH ROW "
         "WHEN (OLD.title IS DISTINCT FROM NEW.title) EXECUTE FUNCTION kalmido_fts_task()"),
        ("argument", "api_tokens", "kalmido_revoked_api_tokens",
         "CREATE OR REPLACE TRIGGER kalmido_revoked_api_tokens AFTER DELETE ON api_tokens FOR EACH ROW "
         "EXECUTE FUNCTION kalmido_revoked_note('pw_hash')"),
        ("row / statement", "orgs", "kalmido_acx_orgs",
         "CREATE OR REPLACE TRIGGER kalmido_acx_orgs AFTER INSERT OR DELETE OR UPDATE OF personal_of ON orgs FOR EACH ROW "
         "EXECUTE FUNCTION kalmido_acx_bump()"),
        ("another function", "tasks", "kalmido_ml_task",
         "CREATE OR REPLACE TRIGGER kalmido_ml_task AFTER UPDATE OF list_id, parent_id ON tasks FOR EACH ROW "
         "WHEN (NEW.list_id IS DISTINCT FROM OLD.list_id OR NEW.parent_id IS DISTINCT FROM OLD.parent_id) "
         "EXECUTE FUNCTION kalmido_time_task_list()"),
        ("switched off", "list_members", "list_e2e_members", "ALTER TABLE list_members DISABLE TRIGGER list_e2e_members"),
        ("replica only", "org_members", "wiki_e2e_members", "ALTER TABLE org_members ENABLE REPLICA TRIGGER wiki_e2e_members")):
    sql(stmt, write=True)
    check(defs() != good, f"#2731: {what} {trig}: the change is in the catalog")
    r = start()
    check(f"{table} ShareRowExclusiveLock" in r["locks"], f"#2731: {what} {trig}: the start replaced it (the probe sees the lock) {r}")
    now = defs()
    check(now == good, f"#2731: {what} {trig}: restored {[k for k in good if now.get(k) != good[k]]}")
quiet("after the repairs")

# a function is replaced by its CREATE OR REPLACE FUNCTION of every start, without a table lock
for fn, ret in (("kalmido_time_title_e2e", "NEW"), ("kalmido_list_e2e_members", "NEW"), ("kalmido_dl_touch", "NULL"),
                ("kalmido_fts_task", "NULL"), ("kalmido_acx_bump", "NULL"), ("kalmido_ml_prune", "NULL")):
    src = sql("SELECT prosrc FROM pg_proc WHERE proname=?", (fn,))[0][0]
    sql(f"CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger LANGUAGE plpgsql AS $fn$BEGIN RETURN {ret}; END$fn$", write=True)
    r = start()
    check(sql("SELECT prosrc FROM pg_proc WHERE proname=?", (fn,))[0][0] == src, f"#2731: {fn}: the start put its body back")
    check(r["locks"] == [], f"#2731: {fn}: without a table lock {r}")

# the former CREATE INDEX IF NOT EXISTS of the start: each comes back when it is gone
fk = sql("SELECT relname FROM pg_class WHERE relname LIKE 'fk2103!_%' ESCAPE '!' AND relkind='i' ORDER BY relname LIMIT 1")[0][0]
for ix in ("tasks_agroup", "tasks_msid", "ix2281_task_fts_vec", "ix2281_cmt_fts_vec", "msg_trgm_comments", "office_doc_items_org", fk):
    check(sql("SELECT 1 FROM pg_class WHERE relname=?", (ix,)) == [(1,)], f"#2731: index {ix} there")
    sql(f"DROP INDEX {ix}", write=True)
    r = start()
    check(sql("SELECT 1 FROM pg_class WHERE relname=?", (ix,)) == [(1,)], f"#2731: the start built {ix} again")
    check(any(x.endswith(" ShareLock") for x in r["locks"]), f"#2731: {ix}: built under its lock {r}")
quiet("after the indexes")

# the one ALTER TABLE .. ADD COLUMN IF NOT EXISTS of the INDEXES script: only when the column is gone
sql("ALTER TABLE org_joins DROP COLUMN pending_lists", write=True)
r = start()
check("org_joins AccessExclusiveLock" in r["locks"], f"#2731: a missing column is added {r}")
check(sql("SELECT 1 FROM information_schema.columns WHERE table_name='org_joins' AND column_name='pending_lists'") == [(1,)],
      "#2731: org_joins.pending_lists is back")
quiet("after the column")

# the comparison itself: other spelling is equal, a real difference never
WANT = ("CREATE OR REPLACE TRIGGER x AFTER INSERT OR UPDATE OF b, a OR DELETE ON t FOR EACH ROW\n"
        "  WHEN (NEW.a IS DISTINCT FROM OLD.a OR NEW.b IS DISTINCT FROM OLD.b) EXECUTE FUNCTION f('Full', 'y');")
SAME = ("CREATE TRIGGER x AFTER INSERT OR DELETE OR UPDATE OF a, b ON public.t FOR EACH ROW "
        "WHEN (new.a IS DISTINCT FROM old.a OR new.b IS DISTINCT FROM old.b) EXECUTE PROCEDURE public.f('Full','y')")
OTHER = [SAME.replace(a, b) for a, b in (
    ("OF a, b", "OF a"), ("OF a, b", "OF a, b, c"), ("AFTER", "BEFORE"), ("INSERT OR ", ""), ("EACH ROW", "EACH STATEMENT"),
    ("'Full'", "'full'"), ("'y'", "'y', 'z'"), ("public.f", "f2"), ("public.f", "other.f"), ("public.t", "other.t"),
    (" OR new.b IS DISTINCT FROM old.b", ""), ("new.a IS", "old.a IS"), ("ON public.t", "ON public.t2"), ("TRIGGER x", "TRIGGER y"))]
NORM = ("import json\nfrom kalmido.core.db import tg_norm\n"
        f"w = {WANT!r}\ns = {SAME!r}\no = {OTHER!r}\n"
        "print(json.dumps({'same': tg_norm(w) == tg_norm(s), 'none': tg_norm('DROP TRIGGER x') is None and tg_norm('') is None, "
        "'hit': [x for x in o if tg_norm(x) == tg_norm(w)], 'n': len({tg_norm(x) for x in o}),"
        "'schema': tg_norm(w.replace(' ON t ', ' ON app.t '), 'app') == tg_norm(w)}))")
r = in_ct(NORM)
check(r["same"] and r["none"] and r["schema"], f"#2731: the same statement in other spelling is equal {r}")
check(r["hit"] == [] and r["n"] == len(OTHER), f"#2731: every real difference counts {r}")

print(f"p2369_b: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
