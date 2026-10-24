#!/usr/bin/env python3
"""2.281.0 A (#3112): indexes on the foreign keys and filter columns, "Empty trash" in the background.
 - every foreign key has an index whose leading columns are the key's columns (pg_constraint / pg_index of the test
   instance); the exceptions are listed below with their reason
 - the lookups the database makes when a task / list / person goes (the key check per referencing table, as a generic plan
   with a parameter like the trigger's) use an index, never a Seq Scan (SET enable_seqscan=off: the tables are small here)
 - the filters of the trash (purge, counter), the fixed-time reminders (remind_at), the unread news (4-s poll) and the
   clean-ups (notifications.created_at, ev_reminded.at, sessions.expires_at) use their index
 - "Empty trash" with more than 200 tasks answers at once (queued), the job in bg_jobs ends "done", every task is gone;
   a small trash goes in the request as before (no queued)
 - a person without an organisation (freelancer-matrix: tasks): the big trash of the private space the same way
usage: p2281_b_fkindex_test.py <datadir>      (KMT_NOSTART=1 / P2281B_NOSTART=1: a running server)"""
import json
import os
import sys

import dbx as dbxm
from freelancer_fixture import freelancer
from kt import B, DATA, check, done, fresh, setup, until

# (table, column) or ("*", referenced table) -> why that key has no index of its own
EXEMPT = {
    ("*", "orgs"): "an organisation goes only through the operator's delete run (rare); org_id is a filter of row-level "
                   "security, where it needs an index it leads a composite one",
}

fresh(prefix="P2281B")
A = setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


# ---- every foreign key has an index on its referencing column(s)
FKS = sql("""SELECT cl.relname, rf.relname, con.conkey::int[], array_agg(a.attname ORDER BY k.i)
             FROM pg_constraint con JOIN pg_class cl ON cl.oid=con.conrelid JOIN pg_class rf ON rf.oid=con.confrelid
             JOIN pg_namespace n ON n.oid=cl.relnamespace
             CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(att, i)
             JOIN pg_attribute a ON a.attrelid=con.conrelid AND a.attnum=k.att
             WHERE con.contype='f' AND n.nspname=current_schema()
             GROUP BY cl.relname, rf.relname, con.conkey""")
IXS = {}
for t, keys in sql("""SELECT cl.relname, ix.indkey::int[] FROM pg_index ix JOIN pg_class cl ON cl.oid=ix.indrelid
                      JOIN pg_namespace n ON n.oid=cl.relnamespace WHERE n.nspname=current_schema()"""):
    IXS.setdefault(t, []).append(json.loads(keys))
check(len(FKS) > 300, f"the instance has its foreign keys ({len(FKS)})")
miss, exempt = [], 0
FKS = [(t, ref, json.loads(keys), json.loads(cols)) for t, ref, keys, cols in FKS]  # arrays come as JSON text (dbx.py)
for t, ref, keys, cols in FKS:
    if any(set(ix[:len(keys)]) == set(keys) for ix in IXS.get(t, [])):
        continue
    if (t, cols[0]) in EXEMPT or ("*", ref) in EXEMPT:
        exempt += 1
        continue
    miss.append(f"{t}({', '.join(cols)}) -> {ref}")
check(not miss, f"every foreign key has an index ({len(miss)} without): {', '.join(sorted(miss))}")
print(f"foreign keys: {len(FKS)}, exempt: {exempt}", flush=True)
for (t, c), why in EXEMPT.items():
    check(t == "*" or any(x[0] == t and x[3][0] == c for x in FKS), f"exception {t}.{c} is still a foreign key ({why[:40]})")


def plan(q, args=(), pre=()):
    """EXPLAIN (FORMAT JSON) -> the list of (node type, relation, index) of the plan."""
    dbc, dbn = dbxm._target(DATA)
    script = "".join(p + ";\n" for p in ("SET enable_seqscan = off",) + tuple(pre)) + "EXPLAIN (FORMAT JSON) " + dbxm.fill(q, args) + ";\n"
    js, out = json.loads(dbxm._psql(dbc, dbn, script)), []

    def walk(n):
        out.append((n.get("Node Type"), n.get("Relation Name"), n.get("Index Name")))
        for k in n.get("Plans", []):
            walk(k)
    walk(js[0]["Plan"])
    return out


def no_seq(q, args=(), pre=()):
    p = plan(q, args, pre)
    return not any(n[0] == "Seq Scan" for n in p), p


# ---- the key checks of a delete (generic plan with a parameter, like the trigger's) use an index
KEYS = [("tchat_msgs", "task_id"), ("task_seen", "task_id"), ("user_task_order", "task_id"), ("task_push", "task_id"),
        ("agent_chat", "task_id"), ("pomos", "task_id"), ("sections", "list_id"), ("notifications", "list_id"),
        ("office_docs", "list_id"), ("list_bell", "list_id"), ("tasks", "section_id"), ("wiki_pages", "created_by"),
        ("tchat_msgs", "user_id"), ("notifications", "actor_id"), ("sheet_cells", "updated_by")]
for i, (t, c) in enumerate(KEYS):
    ok, p = no_seq(f"EXECUTE p2281k{i}(1)", pre=("SET plan_cache_mode = force_generic_plan",
                                               f"PREPARE p2281k{i}(bigint) AS SELECT 1 FROM ONLY {t} x WHERE {c} = $1 FOR KEY SHARE OF x"))
    check(ok, f"the key check {t}.{c} uses an index: {p}")
ok, p = no_seq("DELETE FROM tchat_msgs WHERE task_id=?", (1,))
check(ok, f"deleting the chat of a task uses an index (was a Seq Scan over tchat_msgs): {p}")

# ---- the filter columns
CUT = "2999-01-01T00:00"
for what, q, args in (
        ("the trash purge", "SELECT id FROM tasks WHERE deleted_at IS NOT NULL AND deleted_at<?", (CUT,)),
        ("the trash counter", "SELECT COUNT(*) FROM tasks WHERE deleted_at IS NOT NULL", ()),
        ("the fixed-time reminders", "SELECT id FROM tasks WHERE remind_at IS NOT NULL AND remind_at<=? AND remind_at>=?", (CUT, "2000-01-01")),
        ("the news clean-up", "DELETE FROM notifications WHERE created_at<?", (CUT,)),
        ("the event reminder clean-up", "DELETE FROM ev_reminded WHERE at<?", (CUT,)),
        ("the session clean-up", "DELETE FROM sessions WHERE expires_at<?", (CUT,))):
    ok, p = no_seq(q, args)
    check(ok, f"{what} uses an index: {p}")
p = plan("SELECT COUNT(*), COALESCE(MAX(id),0) FROM notifications WHERE user_id=? AND read_at IS NULL", (1,))
check(any(n[2] == "ix2281_notifications_unread" for n in p), f"the unread news (4-s poll) use the partial index: {p}")
names = {r[0] for r in sql("SELECT indexname FROM pg_indexes WHERE indexname LIKE 'ix2281\\_%'")}
check(len(names) >= 180, f"the 2.281 indexes exist ({len(names)})")


# ---- "Empty trash": big = background job, small = in the request
def fill(s, n, label, child=False):
    ids = []
    for i in range(n):
        r = s.post(B + "/api/tasks", json={"title": f"{label} {i}"})
        if r.ok:
            ids.append(r.json()["id"])
    if child:  # a subtask in the trash too (it goes with its parent; the job finds it gone)
        r = s.post(B + "/api/tasks", json={"title": f"{label} child", "parent_id": ids[0]})
        if r.ok:
            ids.append(r.json()["id"])
    q = ",".join("?" * len(ids))
    sql(f"UPDATE tasks SET deleted_at=? WHERE id IN ({q})", ("2026-01-01T00:00:00", *ids), write=True)
    return ids


def left(ids):
    q = ",".join("?" * len(ids))
    return sql(f"SELECT COUNT(*) FROM tasks WHERE id IN ({q})", ids)[0][0]


def job_state(uid):
    r = sql("SELECT state FROM bg_jobs WHERE kind='trash:empty' AND user_id=? ORDER BY id DESC LIMIT 1", (uid,))
    return r[0][0] if r and r[0][0] in ("done", "failed") else None


def big_trash(s, uid, who):
    ids = fill(s, 300, "Old", child=True)
    check(len(ids) == 301, f"{who}: 300 tasks and a subtask in the trash ({len(ids)})")
    r = s.delete(B + "/api/trash")
    j = r.json() if r.ok else {}
    check(r.ok and j.get("queued") is True and j.get("deleted") == 301 and j.get("kept") == 0,
          f"{who}: 301 tasks -> the answer at once, queued {r.status_code} {r.text[:200]}")
    st = until(lambda: job_state(uid), timeout=120)
    check(st == "done", f"{who}: the background job ends done ({st})")
    check(left(ids) == 0, f"{who}: every task of the trash is gone ({left(ids)} left)")
    r = s.get(B + "/api/tasks?scope=trash&limit=50")
    check(r.ok and r.json().get("tasks") == [], f"{who}: the trash view is empty {r.text[:120]}")


ME = A.get(B + "/api/state").json()["me"]["id"]
small = fill(A, 5, "Small")
r = A.delete(B + "/api/trash")
j = r.json() if r.ok else {}
check(r.ok and "queued" not in j and j.get("deleted") == 5, f"a small trash goes in the request as before {r.text[:200]}")
check(left(small) == 0, "the small trash is gone at once")
check(job_state(ME) is None, "no background job for a small trash")
big_trash(A, ME, "admin")

FID, Fr = freelancer(B, A)
big_trash(Fr, FID, "freelancer")

sys.exit(done("p2281_b_fkindex"))
