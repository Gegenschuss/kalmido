"""2.192.0 C (#2514): the upgrade test -- the current server starts on the database of an OLDER release with data in it.
freelancer-matrix: office

Every other suite starts from an empty database; this one loads each dump of tests/fixtures/upgrade/<version>.sql.gz
(made by tools/make_upgrade_dump.sh + tests/upgrade_seed.py from that release, invented data; the first: 2.101.0.sql.gz) into the group's database
and starts the current image on it:
- 2.509.0 (#4285): before the start every old table gets a row (fill_old_tables), the dump alone has them in few tables; a step
  that only fails on existing rows fails here too
- the migrations run through: the start succeeds, the log has no traceback / error, every MIGRATIONS step is recorded,
  kalmido_meta.app_version is the current VERSION, and the upgraded schema holds everything a fresh install has (columns
  with type + NULL rule + default, constraints, indexes, row-level security + policies, triggers; extra old columns only reported)
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
import re
import subprocess
import sys

import kt
from kt import B, DATA, check, sess
from upgrade_views import data_checks, schema as schema_base, schema_gaps as gaps_base  # 2.510.0 (#4286): shared with p4286_restore

N = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(N, "fixtures", "upgrade")
ROOT = os.path.dirname(N)
VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()


def schema():
    """upgrade_views.schema + 2.509.0 (#4285): defaults and constraints (by their definition: an old database may name a constraint otherwise)."""
    q, s = kt.dbx, schema_base()
    s["defaults"] = {(r[0], r[1]): r[2] for r in q("SELECT table_name, column_name, column_default FROM information_schema.columns "
                                                    "WHERE table_schema='public' AND column_default IS NOT NULL")}
    s["constraints"] = {(r[0], r[1]) for r in q("SELECT c.conrelid::regclass::text, pg_get_constraintdef(c.oid) FROM pg_constraint c "
                                                "JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public' AND c.conrelid<>0")}
    return s


def schema_gaps(ref, got):
    gaps, extra = gaps_base(ref, got)
    gaps += [f"default of {k[0]}.{k[1]}: {got['defaults'].get(k)} instead of {v}" for k, v in sorted(ref["defaults"].items()) if got["defaults"].get(k) != v]
    gaps += [f"constraint of {t} missing: {d}" for t, d in sorted(ref["constraints"] - got["constraints"])]
    return gaps, extra


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


def fill_old_tables():
    """2.509.0 (#4285): one row in every table of the old database that has none. The dump holds rows in few of them; a step like
    ADD COLUMN ... NOT NULL only fails on a table with rows, so it stayed green here and broke on a live database. Only the columns
    without a default get a value; a few rounds for tables that point at others. The rows hang on an account of their own (the last
    row of the table pointed at, FILL_FIRST below): a key, a login factor or a move for one of the old accounts would change what the
    data checks read. Returns {table: why not} of what stayed empty."""
    q = kt.dbx
    fks = {}
    for t, col, ref, refcol in q("""SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text, fa.attname FROM pg_constraint c
                                    JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
                                    JOIN pg_attribute fa ON fa.attrelid=c.confrelid AND fa.attnum=c.confkey[1]
                                    JOIN pg_namespace n ON n.oid=c.connamespace WHERE c.contype='f' AND n.nspname='public'"""):
        fks[(t, col)] = (ref, refcol)
    # 2.1015.0 (#5777): a column with a CHECK that lists its values (obj_follow.mode since 2.981, obj_notif_cap.kind, obj_tags.scope_kind)
    # takes the first allowed one - the filler text broke the row and the test read it as a failed upgrade. Postgres keeps
    # "col IN ('a', 'b')" as "(col = ANY (ARRAY['a'::text, 'b'::text]))"; every table, none left out.
    allowed = {}
    for t, col, cdef in q("""SELECT c.conrelid::regclass::text, a.attname, pg_get_constraintdef(c.oid) FROM pg_constraint c
                             JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
                             JOIN pg_namespace n ON n.oid=c.connamespace
                             WHERE c.contype='c' AND n.nspname='public' AND array_length(c.conkey, 1)=1"""):
        m = re.search(r"= ANY \(+ARRAY\['((?:[^']|'')*)'", cdef) or re.search(r"\bIN \('((?:[^']|'')*)'", cdef)
        if m:
            allowed[(t, col)] = m.group(1).replace("''", "'")

    def value(t, name, typ):
        """The text of a value for column name, None: it points at an empty table."""
        if (t, name) in allowed:
            return allowed[(t, name)]
        if (t, name) in fks:
            ref, refcol = fks[(t, name)]
            r = q(f'SELECT "{refcol}" FROM "{ref}" ORDER BY "{refcol}" DESC LIMIT 1')
            return str(r[0][0]) if r else None
        if "int" in typ or typ in ("numeric", "double precision", "real"):
            return "0"
        if name.endswith("_at") and "timestamp" not in typ:  # #5916: an old TEXT time column (created_at, added_at ...) held ISO
            return "2026-01-01T00:00:00Z"  # (now_iso) - the filler text broke later moves into TIMESTAMPTZ columns (#5306)
        return {"bytea": "\\x00", "jsonb": "{}", "json": "{}", "boolean": "false", "date": "2026-01-01"}.get(typ, "p2192-fill-" + t if "timestamp" not in typ else "2026-01-01")

    def insert(t, more=()):
        """One row in t, with the columns more on top of the required ones."""
        cols = q("""SELECT column_name, data_type, is_nullable='NO' AND column_default IS NULL AND is_identity='NO' AND is_generated='NEVER'
                    FROM information_schema.columns WHERE table_schema='public' AND table_name=? ORDER BY ordinal_position""", (t,))
        names, vals = [], []
        for name, typ, need in cols:
            if need or name in more:
                v = value(t, name, typ)
                if v is None:
                    return f"{name} points at an empty table"
                names.append(f'"{name}"')
                vals.append("'" + v.replace("'", "''") + "'")
        q(f"INSERT INTO \"{t}\"({','.join(names)}) VALUES({','.join(vals)}) ON CONFLICT DO NOTHING" if names else f'INSERT INTO "{t}" DEFAULT VALUES')
        return None

    for t, more in FILL_FIRST:
        insert(t, more)
    tables = [r[0] for r in q("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1")]
    why = {}
    for _ in range(4):
        why = {}
        for t in tables:
            if q(f'SELECT 1 FROM "{t}" LIMIT 1'):
                continue
            try:
                w = insert(t)
            except Exception as e:  # noqa: BLE001 - a CHECK of the table, wiki_spaces: an organisation or an owner, one of them
                w = str(e)[-200:]
                for col in [c for (x, c) in fks if x == t]:
                    try:
                        w = insert(t, (col,))
                        break
                    except Exception as e2:  # noqa: BLE001
                        w = str(e2)[-200:]
            if w:
                why[t] = w
        if not why:
            break
    return why


OLD_TASKS = "SELECT COUNT(*) FROM tasks WHERE title NOT LIKE 'p2192-fill-%'"
FILL_FIRST = (("users", ()), ("orgs", ()), ("lists", ("owner_id",)), ("tasks", ()))  # the fill's own: every other row points at these


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
    empty = fill_old_tables()  # 2.509.0 (#4285)
    check(not empty, f"{tag}: every old table has a row before the start: {empty}")
    before = kt.dbx(OLD_TASKS)[0][0]
    # 2.1084.0 (#5916): the recorded steps before the start; a dump before 2.102.0 (2.101.0) has no kalmido_migrations yet
    has_migs = int(kt.dbx("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='kalmido_migrations'")[0][0]) > 0
    mig_before = {r[0]: tuple(r[1:]) for r in kt.dbx("SELECT id, applied_at, note FROM kalmido_migrations WHERE id NOT LIKE 'flag:%'")} if has_migs else {}
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
    # 2.1084.0 (#5916): a short jump (the live state of the upgrade probe, 2.1067 -> 2.1075) may bring only new tables (SCHEMA of a
    # fragment) and no MIGRATIONS column step - then core/db.py mig_apply prints nothing and that is right. The log line has to
    # match the steps recorded as applied at this start: N of them = "migrations: N step(s) applied", none = no such line.
    # (core/moneycol.py records its column type changes as "type:table.column" with a log line of their own, not in this count)
    fresh_steps = sum(1 for mid, at, note in kt.dbx("SELECT id, applied_at, note FROM kalmido_migrations WHERE id NOT LIKE 'flag:%' "
                                                    "AND id NOT LIKE 'type:%'")
                      if note in ("applied", "again") and mig_before.get(mid) != tuple((at, note)))
    m = re.search(r"migrations: (\d+) step\(s\) applied", log1)
    check((int(m.group(1)) if m else 0) == fresh_steps,
          f"{tag}: the migrations ran: log says {m.group(0) if m else 'no step applied'}, {fresh_steps} step(s) newly recorded as applied")
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
    # 2.509.0 (#4285): the fill's rows aside (a step turns its old milestone into a task of its own); 2.1154.0 (#6059): the
    # office's inbox tasks of the first ticks aside as well (upgrade_views.OFFICE_INBOX - the dumps hold none)
    after = kt.dbx(OLD_TASKS + " AND COALESCE(url, '') NOT LIKE '%/#office/%'")[0][0]
    check(after == before, f"{tag}: no task lost by the migrations: {before} -> {after}")
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
