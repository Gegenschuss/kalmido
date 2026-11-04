"""2.192.0 C (#2514): the upgrade test -- the current server starts on the database of an OLDER release with data in it.
freelancer-matrix: office

Every other suite starts from an empty database; this one loads each dump of tests/fixtures/upgrade/<version>.sql.gz
(made by tools/make_upgrade_dump.sh + tests/upgrade_seed.py from that release, invented data; the first: 2.101.0.sql.gz) into the group's database
and starts the current image on it:
- the migrations run through: the start succeeds, the log has no traceback / error, every MIGRATIONS step is recorded,
  kalmido_meta.app_version is the current VERSION, and the upgraded schema holds everything a fresh install has (columns
  with type + NULL rule, indexes, row-level security + policies, triggers; extra old columns only reported)
- the data is complete through the API: the old accounts sign in with their passwords; per person the same lists and tasks
  (due date + time, repeat rule, subtasks, done state, attachment names) as the old release showed (<version>.json),
  comments, clients, office documents (number, net, gross), time entries, the personal agent
- a write works (a new task + comment in the org project, frida edits her own task)
- the boundary holds: frida (no organisation) sees no org task / office document, bob not alice's private list
- a second start is idempotent: no migration step runs again, schema and data stay the same
Replaces the group's database (own group with `fresh` in run_all.sh). P2192C_NOSTART / KMT_NOSTART: not supported (the
suite restarts the container itself)."""
import glob
import gzip
import json
import os
import subprocess
import sys

import kt
from kt import B, DATA, check, sess
from upgrade_views import data_checks, schema, schema_gaps  # 2.510.0 (#4286): shared with p4286_restore

N = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(N, "fixtures", "upgrade")
ROOT = os.path.dirname(N)
VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()


def logs():
    r = subprocess.run(["docker", "logs", kt.CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def bad_lines(text):
    return [ln for ln in text.splitlines() if "Traceback" in ln or " ERROR" in ln or ln.startswith("ERROR")]


def load(dump):
    """The container stops, the group's database is replaced by the dump (start.sh KEEP=1 then keeps it)."""
    subprocess.run(["docker", "rm", "-f", kt.CT], capture_output=True)
    with open(os.path.join(DATA, ".kalmido-db"), encoding="utf-8") as f:
        dbc, dbn = f.read().split()
    psql = ["docker", "exec", "-i", dbc, "psql", "-U", "kalmido", "-v", "ON_ERROR_STOP=1", "-q"]
    r = subprocess.run(psql + ["-d", "kalmido", "-c", f"DROP DATABASE IF EXISTS {dbn} WITH (FORCE)", "-c", f"CREATE DATABASE {dbn}"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    with gzip.open(dump, "rb") as f:
        r = subprocess.run(psql + ["-d", dbn], input=f.read(), capture_output=True)
    assert r.returncode == 0, r.stderr.decode()[-2000:]


DUMPS = sorted(glob.glob(os.path.join(FIX, "*.sql.gz")))
check(DUMPS, "at least one dump in tests/fixtures/upgrade")
kt.fresh()  # the current server on an empty database: the reference schema of a fresh install
REF = schema()
check(len(REF["cols"]) > 500 and REF["policies"], "reference schema of a fresh install read")
for dump in DUMPS:
    with open(dump[:-len(".sql.gz")] + ".json", encoding="utf-8") as f:
        E = json.load(f)
    tag = "from " + E["version"]
    load(dump)
    before = kt.dbx("SELECT COUNT(*) FROM tasks")[0][0]
    try:
        os.environ["START_WAIT_S"] = "150"  # #3506: every migration since the dump runs at this first start
        kt.fresh(keep=True)
        started = True
    except AssertionError as e:
        started = False
        print(str(e)[-3000:])
        try:  # #3506: what the hanging start waits for (its statements, their lock waits)
            for r in kt.dbx("SELECT pid, state, wait_event_type, wait_event, now() - xact_start AS age, left(query, 400) AS q FROM pg_stat_activity "
                            "WHERE datname = current_database() AND pid <> pg_backend_pid()"):
                print("   pg:", tuple(r))
            for r in kt.dbx("SELECT l.pid, l.locktype, l.mode, l.granted, c.relname FROM pg_locks l LEFT JOIN pg_class c ON c.oid = l.relation "
                            "WHERE NOT l.granted"):
                print("   waiting lock:", tuple(r))
        except Exception as x:  # noqa: BLE001 - only a diagnosis
            print("   pg_stat_activity:", x)
    check(started, f"{tag}: the current server starts on the old database")
    if not started:
        continue
    log1 = logs()
    check(not bad_lines(log1), f"{tag}: start log without traceback / error: {bad_lines(log1)[:5]}")
    check("step(s) applied" in log1, f"{tag}: the migrations ran ('migrations: N step(s) applied' in the log)")
    meta = dict(kt.dbx("SELECT key, value FROM kalmido_meta"))
    check(meta.get("app_version") == VERSION, f"{tag}: kalmido_meta.app_version = {VERSION} ({meta.get('app_version')})")
    migs = dict(kt.dbx("SELECT note, COUNT(*) FROM kalmido_migrations WHERE id NOT LIKE 'flag:%' GROUP BY note"))
    ref_migs = kt.dbx("SELECT COUNT(*) FROM kalmido_migrations WHERE id NOT LIKE 'flag:%'")[0][0]
    check(migs.get("applied", 0) > 0 and "again" not in migs, f"{tag}: steps recorded as applied / present, none again: {migs}")
    gaps, extra = schema_gaps(REF, schema())
    check(not gaps, f"{tag}: the upgraded schema holds everything of a fresh install ({len(gaps)} gaps)")
    for g in gaps[:40]:
        print("   gap:", g)
    if extra:
        print(f"   info: {len(extra)} column(s) only in the upgraded database: {', '.join(extra[:30])}")
    check(kt.dbx("SELECT COUNT(*) FROM tasks")[0][0] == before, f"{tag}: no task lost by the migrations")
    users = data_checks(E, tag)
    A, Fr = users["alice"], users["frida"]
    ids = E["ids"]
    # a write works
    r = A.post(B + "/api/tasks", json={"list_id": ids["team"], "title": "Nach dem Update angelegt", "due": "2026-06-01"})
    check(r.ok, f"{tag}: a new task in the old org project: {r.status_code} {r.text[:200]}")
    nt = r.json().get("id") if r.ok else None
    check(nt and A.post(B + f"/api/tasks/{nt}/comments", json={"body": "geht"}).ok, f"{tag}: a comment on it")
    check(nt and any(t["id"] == nt for t in users["bob"].get(B + "/api/state").json()["tasks"]), f"{tag}: bob sees the new org task")
    check(Fr.patch(B + f"/api/tasks/{ids['frida_task']}", json={"title": "Website-Texte (neu)"}).ok, f"{tag}: frida edits her task")
    check(not any(t["id"] == nt for t in Fr.get(B + "/api/state").json()["tasks"]), f"{tag}: frida does not see the new org task")
    # the second start: nothing runs again
    snap = schema()
    kt.fresh(keep=True)
    log2 = logs()
    check(not bad_lines(log2), f"{tag}: second start without traceback / error: {bad_lines(log2)[:5]}")
    check("step(s) applied" not in log2, f"{tag}: second start applies no migration step")
    check(kt.dbx("SELECT COUNT(*) FROM kalmido_migrations WHERE id NOT LIKE 'flag:%'")[0][0] == ref_migs, f"{tag}: no new migration rows")
    check(schema() == snap, f"{tag}: schema unchanged by the second start")
    A2 = sess("alice", E["password"])
    titles = {t["title"] for t in A2.get(B + "/api/state").json()["tasks"]}
    check("Nach dem Update angelegt" in titles and "Imagefilm schneiden" in titles, f"{tag}: old and new tasks after the second start")
    check(any(t["title"] == "Website-Texte (neu)" for t in sess("frida", E["password"]).get(B + "/api/state").json()["tasks"]),
          f"{tag}: frida's change kept")

sys.exit(kt.done("p2192_c_upgrade"))
