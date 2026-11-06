#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.579.0 API tests, part B (#4184): load_tasks and GET /api/state/delta read only the rows of the tasks they serialize
(task_id = ANY) instead of the whole instance. Own container (start.sh). Invented people and texts only.
freelancer-matrix: tasks, time
 - one changed task: the delta carries the same dependencies (blocked / blockers / blocking), git code (pull request +
   commit), time total, contacts and events for it (and for the task waiting on it) as a full GET /api/state
 - with tt=1 (the app) time_totals holds only the changed tasks and time_ids names them; the totals of other tasks are
   left to the client; without tt=1 every total as before (older clients)
 - a new time entry on the task: the delta's total follows; a task whose last entry is gone: in time_ids, no total
 - rights stay: another organisation's tasks never appear in the delta's maps (fewer rows, never other rows)
 - EXPLAIN (ANALYZE) of the five queries before / after with many foreign rows (dependencies and git links of another
   organisation, a long time history): the rows read go down; both plans of the dependency query (one task and every
   task of the person) are printed
 - the same for a person without an organisation
usage: p2579_b_api_test.py <datadir>   (P2579B_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import json
import os
import sys
from datetime import timedelta

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from kt import B, DATA, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(prefix="P2579B")
kt.docker_logs_on_first_fail()
FEATURES = "collab,comments,deps,events,contacts,time,progress,fields"
A = kt.setup()
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code in (200, 201), r.text
ALPHA = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta"})
BETA = r.json()["id"]
r = A.post(B + "/api/users", json={"orgs": [BETA], "username": "carl", "display_name": "Carl", "password": "password123",
                                   "email": "carl@example.com"})
assert r.ok, r.text
Ca = sess("carl")
for s in (A, Ca):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok
FID, Fr = freelancer(B, A)
NOW = kt.now()


def dbx(sql, args=()):
    return kt.dbx(sql, args)


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"))
    try:
        return c.execute(sql, args).rowcount
    finally:
        c.close()


def psql(sql, args=()):
    dbc, dbn = dbxm._target(os.path.join(DATA, "tasks.db"))
    return dbxm._psql(dbc, dbn, dbxm.fill(sql, args) + ";\n")


def ok(r):
    assert r.ok, r.text
    return r.json()


def task(s, title, lid, **kw):
    return ok(s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw}))["id"]


def ts(minutes_ago, length=30):
    a = NOW - timedelta(minutes=minutes_ago)
    return a.isoformat(timespec="seconds"), (a + timedelta(minutes=length)).isoformat(timespec="seconds")


def entry(s, tid, minutes_ago, length=30):
    a, b = ts(minutes_ago, length)
    return ok(s.post(B + "/api/time/entries", json={"task_id": tid, "start": a, "end": b}))["id"]


def clone(table, rid, n, over):
    """n copies of row rid of table (columns over: SQL expressions with g = 1..n); the copies are no change of a version
    (dl_changes rows written by the trigger are stamped at the next bump, before the delta's since)."""
    cols = [r[0] for r in dbx("SELECT column_name FROM information_schema.columns WHERE table_name=? AND is_generated='NEVER' "
                              "AND column_name<>'id' AND identity_generation IS NULL ORDER BY ordinal_position", (table,))]
    sel = ", ".join(over.get(k, f'"{k}"') for k in cols)
    return dbw(f"INSERT INTO {table} ({', '.join(chr(34) + k + chr(34) for k in cols)}) SELECT {sel} FROM {table}, "
               f"generate_series(1, {int(n)}) g WHERE id={int(rid)}")


def git_on(lid, tid, n=7, sha="ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12"):
    cid = dbx("INSERT INTO git_conns(list_id, provider, owner, repo, next_at, created_at) VALUES(?, 'github', 'acme', ?, 1e12, ?) "
              "RETURNING id", (lid, f"repo{lid}", NOW.isoformat()))[0][0]
    dbw("INSERT INTO git_prs(conn_id, number, title, state, updated_at) VALUES(?, ?, 'Fix the export', 'open', ?)", (cid, n, NOW.isoformat()))
    dbw("INSERT INTO git_commits(conn_id, sha, message, at) VALUES(?, ?, 'Export: header row', ?)", (cid, sha, NOW.isoformat()))
    dbw("INSERT INTO git_links(task_id, conn_id, kind, ref, created_at) VALUES(?, ?, 'pr', ?, ?)", (tid, cid, str(n), NOW.isoformat()))
    dbw("INSERT INTO git_links(task_id, conn_id, kind, ref, created_at) VALUES(?, ?, 'commit', ?, ?)", (tid, cid, sha, NOW.isoformat()))
    return cid


def delta(s, since, tt=True):
    return ok(s.get(B + "/api/state/delta", params={"since": since, **({"tt": "1"} if tt else {})}))


KEYS = ("blocked", "blockers", "blocking", "code")


def same_as_state(s, who, d, ids):
    st = ok(s.get(B + "/api/state"))
    full = {t["id"]: t for t in st["tasks"]}
    dt = {t["id"]: t for t in d["tasks"]}
    for i in ids:
        check(i in dt and i in full, f"{who}: task {i} in the delta and the state")
        if i in dt and i in full:
            for k in KEYS:
                check(dt[i].get(k) == full[i].get(k), f"{who}: task {i} {k} as in the state {dt[i].get(k)} / {full[i].get(k)}")
        check(d["time_totals"].get(str(i)) == st["time_totals"].get(str(i)), f"{who}: task {i} time total as in the state")
        check(d["tcontacts"].get(str(i)) == st["tcontacts"].get(str(i)), f"{who}: task {i} contacts as in the state")
        check(d["evlinks"].get(str(i)) == st["evlinks"].get(str(i)), f"{who}: task {i} events as in the state")
    return st


def scenario(s, who, org):
    L = ok(s.post(B + "/api/lists", json={"name": "Release plan", "kind": "project", "time_tracking": True,
                                          **({"org_id": org} if org else {})}))["id"]
    T = task(s, "Write the export", L)
    X = task(s, "Agree the format", L)
    W = task(s, "Ship the export", L)
    O = task(s, "Older work", L)
    check(s.post(B + "/api/deps", json={"task_id": T, "blocker_id": X}).ok, f"{who}: T waits on X")
    check(s.post(B + "/api/deps", json={"task_id": W, "blocker_id": T}).ok, f"{who}: W waits on T")
    entry(s, T, 300)
    entry(s, O, 400, 90)
    book = ok(s.post(B + "/api/books", json={"name": "Clients"}))["id"]
    ct = ok(s.post(B + "/api/contacts", json={"book_id": book, "fn": "Dana Example"}))["id"]
    check(s.post(B + f"/api/tasks/{T}/contacts", json={"contact_id": ct}).ok, f"{who}: contact linked to T")
    check(s.post(B + f"/api/tasks/{O}/contacts", json={"contact_id": ct}).ok, f"{who}: contact linked to O")
    cal = ok(s.post(B + "/api/evcals", json={"name": "Work"}))["id"]
    day = (NOW + timedelta(days=2)).date().isoformat()
    check(s.post(B + "/api/events", json={"title": "Export review", "cal_id": cal, "start": f"{day}T10:00", "task_id": T}).ok,
          f"{who}: event prepares T")
    check(s.post(B + "/api/events", json={"title": "Older meeting", "cal_id": cal, "start": f"{day}T12:00", "task_id": O}).ok,
          f"{who}: event prepares O")
    git_on(L, T)
    git_on(L, O, n=8, sha="cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34")
    s.patch(B + f"/api/tasks/{X}", json={"title": "Agree the format (v2)"})  # stamps the rows written by SQL above
    v0 = ok(s.get(B + "/api/state"))["v"]
    check(s.patch(B + f"/api/tasks/{T}", json={"title": "Write the CSV export"}).ok, f"{who}: T changed")
    d = delta(s, v0)
    check(d.get("full") is False, f"{who}: a delta, not full {d.get('full')}")
    st = same_as_state(s, who, d, [T, W])
    dt = {t["id"]: t for t in d["tasks"]}
    check(dt.get(T, {}).get("blocked") == 1 and dt.get(W, {}).get("blocked") == 1 and dt.get(T, {}).get("blocking") == 1,
          f"{who}: the dependencies are there at all")
    check(len((dt.get(T, {}).get("code") or {}).get("prs", [])) == 1 and len((dt.get(T, {}).get("code") or {}).get("commits", [])) == 1,
          f"{who}: T's pull request and commit")
    check(str(T) in d["time_totals"] and str(T) in d["tcontacts"] and str(T) in d["evlinks"], f"{who}: T's time, contact, event")
    # narrow: only the changed tasks (T, the tasks of its dependencies), with their ids; O is left to the client
    check(T in d.get("time_ids", []) and O not in d.get("time_ids", []), f"{who}: time_ids names T, not O {d.get('time_ids')}")
    check(str(O) not in d["time_totals"] and str(O) in st["time_totals"], f"{who}: O's total not in the delta (the client keeps it)")
    check(str(O) not in d["tcontacts"] and str(O) not in d["evlinks"], f"{who}: O's contacts / events not in the delta")
    d0 = delta(s, v0, tt=False)  # an older client: every total, as before
    check("time_ids" not in d0 and d0["time_totals"] == st["time_totals"], f"{who}: without tt=1 every total as before")
    # a new entry on T: its total follows; T's entries all gone: T in time_ids, no total
    v1 = ok(s.get(B + "/api/state"))["v"]
    entry(s, T, 120, 15)
    d = delta(s, v1)
    st = ok(s.get(B + "/api/state"))
    check(T in d.get("time_ids", []) and d["time_totals"].get(str(T)) == st["time_totals"][str(T)]
          and st["time_totals"][str(T)][0] == 45 * 60, f"{who}: the new entry is in T's total {d['time_totals'].get(str(T))}")
    v2 = st["v"]
    for (eid,) in dbx("SELECT id FROM time_entries WHERE task_id=?", (T,)):
        check(s.delete(B + f"/api/time/entries/{eid}").ok, f"{who}: entry {eid} deleted")
    d = delta(s, v2)
    check(T in d.get("time_ids", []) and str(T) not in d["time_totals"], f"{who}: no entries left: T in time_ids, no total")
    return L, T, W, O


L1, T1, W1, O1 = scenario(A, "alice", ALPHA)
LF, TF, WF, OF = scenario(Fr, "frida (no organisation)", None)

# ================================================================ many foreign rows (another organisation)
CL = ok(Ca.post(B + "/api/lists", json={"name": "Beta backlog", "kind": "project", "time_tracking": True, "org_id": BETA}))["id"]
CT = [task(Ca, f"Beta task {i}", CL) for i in range(80)]
dbw("INSERT INTO task_deps(task_id, blocker_id, created_at) SELECT a.id, b.id, ? FROM tasks a, tasks b "
    "WHERE a.list_id=? AND b.list_id=? AND a.id<>b.id", (NOW.isoformat(), CL, CL))  # 6.320 dependencies
CCONN = git_on(CL, CT[0], n=1, sha="ef56ab12cd34ef56ab12cd34ef56ab12cd34ef56")
dbw("INSERT INTO git_commits(conn_id, sha, message, at) SELECT ?, md5(g::text), 'Beta commit', ? FROM generate_series(1, 80) g",
    (CCONN, NOW.isoformat()))
dbw("INSERT INTO git_links(task_id, conn_id, kind, ref, created_at) SELECT t.id, ?, 'commit', md5(g::text), ? FROM tasks t, "
    "generate_series(1, 80) g WHERE t.list_id=?", (CCONN, NOW.isoformat(), CL))  # 6.400 git links
ce = entry(Ca, CT[1], 500)
clone("time_entries", ce, 6000, {"task_id": f"(SELECT id FROM tasks WHERE list_id={int(CL)} ORDER BY id OFFSET (g % 80) LIMIT 1)"})
# alice's own long history: time entries, events and contact links of other tasks of hers
ae = dbx("SELECT id FROM time_entries WHERE task_id=? LIMIT 1", (O1,))[0][0]
clone("time_entries", ae, 4000, {})
aev = dbx("SELECT id FROM events WHERE task_id=? LIMIT 1", (O1,))[0][0]
clone("events", aev, 3000, {"uid": "md5(random()::text || g::text)"})
OLD = [task(A, f"Archive {i}", L1) for i in range(40)]
ac = dbx("SELECT contact_id FROM contact_tasks WHERE task_id=?", (O1,))[0][0]
dbw("INSERT INTO contact_tasks(contact_id, task_id, kind, added_at) SELECT ?, id, 'about', ? FROM tasks WHERE id = ANY(CAST(? AS BIGINT[]))",
    (ac, NOW.isoformat(), "{" + ",".join(map(str, OLD)) + "}"))
clone("contacts", ac, 120, {"uid": "md5(random()::text || g::text)", "href": "md5(random()::text || g::text) || '.vcf'",
                            "fn": "'Archive contact ' || g"})
dbw("INSERT INTO contact_tasks(contact_id, task_id, kind, added_at) SELECT k.id, t.id, 'about', ? FROM contacts k, tasks t "
    "WHERE k.fn LIKE 'Archive contact %' AND t.id = ANY(CAST(? AS BIGINT[]))", (NOW.isoformat(), "{" + ",".join(map(str, OLD)) + "}"))  # 4.800 links
psql("ANALYZE")
A.patch(B + f"/api/tasks/{O1}", json={"title": "Older work (stamp)"})  # stamps the SQL rows above (before the delta's since)

# rights: alice's delta never carries Beta's tasks
v = ok(A.get(B + "/api/state"))["v"]
A.patch(B + f"/api/tasks/{T1}", json={"title": "Write the CSV export (2)"})
d = delta(A, v)
beta = {str(i) for i in CT}
check(d.get("full") is False and not beta & set(d["time_totals"]) and not {t["id"] for t in d["tasks"]} & set(CT),
      "rights: no task / total of another organisation in the delta")
same_as_state(A, "alice (many foreign rows)", d, [T1, W1])

# ================================================================ EXPLAIN before / after
PROJ = "(SELECT id FROM lists WHERE is_inbox=0)"
uid = ok(A.get(B + "/api/state"))["me"]["id"]
cals = ",".join(str(r[0]) for r in dbx("SELECT id FROM ev_cals WHERE owner_id=?", (uid,))) or "0"
books = ",".join(str(r[0]) for r in dbx("SELECT id FROM books WHERE owner_id=?", (uid,))) or "0"
ONE = "{" + str(T1) + "}"
ALL = "{" + ",".join(str(r[0]) for r in dbx("SELECT id FROM tasks WHERE list_id=?", (L1,))) + "}"
Q = {
    "task_deps (blocked)": (
        f"SELECT d.task_id, d.blocker_id, b.list_id FROM task_deps d JOIN tasks b ON b.id=d.blocker_id JOIN tasks w ON w.id=d.task_id "
        f"WHERE b.status=0 AND b.deleted_at IS NULL AND b.list_id IN {PROJ} AND w.list_id IN {PROJ}", " AND d.task_id = ANY(CAST(? AS BIGINT[]))", "task_deps"),
    "task_deps (blocking)": (
        f"SELECT d.blocker_id, COUNT(*) AS n FROM task_deps d JOIN tasks t ON t.id=d.task_id JOIN tasks b ON b.id=d.blocker_id "
        f"WHERE t.status=0 AND t.deleted_at IS NULL AND t.list_id IN {PROJ} AND b.list_id IN {PROJ}", " AND d.blocker_id = ANY(CAST(? AS BIGINT[]))",
        "task_deps", " GROUP BY d.blocker_id"),
    "git_links (commits)": (
        "SELECT l.task_id, m.sha FROM git_links l JOIN git_conns k ON k.id=l.conn_id JOIN git_commits m ON m.conn_id=l.conn_id "
        "AND m.sha=l.ref WHERE l.kind='commit'", " AND l.task_id = ANY(CAST(? AS BIGINT[]))", "git_links"),
    "time_entries": (
        "SELECT task_id, SUM(seconds) FROM time_entries WHERE task_id IS NOT NULL AND \"end\" IS NOT NULL",
        " AND task_id = ANY(CAST(? AS BIGINT[]))", "time_entries", " GROUP BY task_id"),
    "contact_tasks": (
        f"SELECT l.task_id, l.contact_id FROM contact_tasks l JOIN contacts k ON k.id=l.contact_id WHERE k.book_id IN ({books}) "
        "AND k.deleted_at IS NULL", " AND l.task_id = ANY(CAST(? AS BIGINT[]))", "contact_tasks"),
    "events": (
        f"SELECT id, task_id FROM events WHERE cal_id IN ({cals}) AND task_id IS NOT NULL AND deleted_at IS NULL",
        " AND task_id = ANY(CAST(? AS BIGINT[]))", "events"),
}


def plan(sql, args=()):
    out = psql("EXPLAIN (ANALYZE, FORMAT JSON) " + sql, args)
    return json.loads(out)[0]


def rows_read(node, table):
    n = 0
    if node.get("Relation Name") == table:
        loops = node.get("Actual Loops", 1) or 1
        n += (node.get("Actual Rows", 0) + node.get("Rows Removed by Filter", 0) + node.get("Rows Removed by Index Recheck", 0)) * loops
    for k in node.get("Plans", []):
        n += rows_read(k, table)
    return n


def text_plan(sql, args=()):
    return psql("EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF, SUMMARY ON) " + sql, args)


for name, q in Q.items():
    base, narrow, table = q[0], q[1], q[2]
    tail = q[3] if len(q) > 3 else ""
    before = plan(base + tail)
    after = plan(base + narrow + tail, (ONE,))
    rb, ra = rows_read(before["Plan"], table), rows_read(after["Plan"], table)
    print(f"PERF #4184 {name}: rows of {table} read {rb} -> {ra} (one task), "
          f"{before.get('Execution Time')} -> {after.get('Execution Time')} ms", flush=True)
    check(ra < rb, f"EXPLAIN {name}: fewer rows read for one task ({rb} -> {ra})")
    if name.startswith("task_deps"):  # the comment named a slower plan with the array: both plans in the output
        print(f"--- EXPLAIN {name} before:\n" + text_plan(base + tail), flush=True)
        print(f"--- EXPLAIN {name} after, one task:\n" + text_plan(base + narrow + tail, (ONE,)), flush=True)
        big = plan(base + narrow + tail, (ALL,))
        print(f"--- EXPLAIN {name} after, every task of the list ({ALL.count(',') + 1}):\n" + text_plan(base + narrow + tail, (ALL,)), flush=True)
        check(big.get("Execution Time", 0) <= max(4 * before.get("Execution Time", 0), 50),
              f"EXPLAIN {name}: the array with every task is no slower plan ({before.get('Execution Time')} -> {big.get('Execution Time')} ms)")

# the delta with many foreign rows still answers the same for T1 (above); the statement count does not grow
r1 = A.get(B + "/api/state/delta", params={"since": v, "tt": "1"})
check(r1.ok and "time_ids" in r1.json(), "delta with many foreign rows answers")

sys.exit(kt.done("p2579_b_api"))
