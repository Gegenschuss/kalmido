#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.475.0 (#3478): migrations as fragments in kalmido/core/migrations.d. Own container, a real start routine (init_db) on a
fragment folder made here, the app itself has none yet; invented names only.
 - a start creates a fragment's table, column, index and AFTER and records the step; a second start changes nothing
 - a database without the column (an old one) gets it, "again" when the step was recorded; a second step of one column is table.col#2
 - frag_load: name order, only .py, no folder = nothing
 - tools/check_migrations.py: schema.py as it is passes, a new step / table / index there is a finding, a fragment with code too;
   the checks that read the schema see the fragments (schema_src)
 - 2.509.0 (#4285): and it reads the statements: only additive steps, indexes in AFTER, UNIQUE on an existing table with a reason
   (2.574.0 #3779: and a DROP TABLE IF EXISTS in AFTER with a line # drop-ok <table>: <why>, of a table created nowhere any more;
   review F5: DROP COLUMN IF EXISTS the same way with # drop-ok <table>.<column>, IF EXISTS missing is a finding of its own);
   a step that fails in the middle of a start leaves nothing behind and the next start goes through; two starts at once both
   go through and do the step once
No routes, no person (freelancer-matrix: n/a).
usage: p2475_a_api_test.py <datadir>"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_migrations as cm  # noqa: E402
from kt import FAILS, OKS, check  # noqa: E402

CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")

STEP = '''SCHEMA = """
CREATE TABLE IF NOT EXISTS p2475_probe (id BIGINT PRIMARY KEY, org_id BIGINT);
CREATE INDEX IF NOT EXISTS p2475_probe_org ON p2475_probe(org_id);
"""
MIGRATIONS = [("p2475_probe", "note", "ALTER TABLE p2475_probe ADD COLUMN note TEXT NOT NULL DEFAULT ''")]
AFTER = ["INSERT INTO p2475_probe(id, org_id) VALUES(1, 7) ON CONFLICT DO NOTHING"]
'''
# 2.509.0 (#4285): what the lint lets through (STEP above has an INSERT in AFTER on purpose: the start routine runs what it is given)
LINTED = STEP.replace('["INSERT INTO p2475_probe(id, org_id) VALUES(1, 7) ON CONFLICT DO NOTHING"]', '["CREATE INDEX IF NOT EXISTS p2475_probe_note ON p2475_probe(note)"]')
SECOND = 'MIGRATIONS = [("p2475_probe", "note", "ALTER TABLE p2475_probe ADD COLUMN note TEXT")]\n'
RUN = """
import json, os, tempfile
import app  # noqa: F401
import kalmido.core.db as d
t = tempfile.mkdtemp()
for n, s in json.loads(%r).items():
    open(os.path.join(t, n), "w").write(s)
d.FRAG_SCHEMA, d.FRAG_MIGRATIONS, d.FRAG_AFTER = d.frag_load(t)
for q in json.loads(%r):
    c = d.connect_direct(d.DATABASE_URL); c.execute(q); c.commit(); c.close()
d.init_db(guard=False)
c = d.connect_direct(d.DATABASE_URL)
print(json.dumps({
    "rows": c.execute("SELECT count(*) FROM p2475_probe").fetchone()[0],
    "mig": sorted(list(r) for r in c.execute("SELECT id, note, applied_at FROM kalmido_migrations WHERE id LIKE 'p2475%%'").fetchall()),
    "ix": c.execute("SELECT count(*) FROM pg_indexes WHERE indexname='p2475_probe_org'").fetchone()[0]}))
"""


def start(frags, first=()):
    """init_db in the app container on these fragments, after the statements first; the state of the probe table as JSON."""
    code = RUN % (json.dumps(frags), json.dumps(list(first)))
    for _ in range(4):  # a deadlock with the running server's own work is not the check's matter
        r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=180)
        if r.returncode == 0 or "deadlock detected" not in r.stdout + r.stderr:
            break
        time.sleep(2)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


a = start({"3478.py": STEP})
check(a["rows"] == 1 and a["ix"] == 1, f"#3478: the start made the fragment's table, index and AFTER {a}")
check([x[:2] for x in a["mig"]] == [["p2475_probe.note", "applied"]], f"#3478: the step is recorded {a}")
b = start({"3478.py": STEP})
check(b == a, f"#3478: a second start changes nothing {b}")
o = start({"3478.py": STEP}, ["ALTER TABLE p2475_probe DROP COLUMN note"])
check([x[:2] for x in o["mig"]] == [["p2475_probe.note", "again"]], f"#3478: a database without the column gets it {o}")
two = start({"3478.py": STEP, "3479.py": SECOND})
check([x[:2] for x in two["mig"]] == [["p2475_probe.note", "again"], ["p2475_probe.note#2", "present"]],
      f"#3478: a second step of the same column in a fragment {two}")

# 2.509.0 (#4285): a step fails in the middle of a start: nothing stays behind, the next start with the step mended goes through
GOOD = 'MIGRATIONS = [("p2475_probe", "half", "ALTER TABLE p2475_probe ADD COLUMN half TEXT")]\n'
BROKEN = 'MIGRATIONS = [("p2475_probe", "half2", "ALTER TABLE p2475_probe ADD COLUMN half2 NOSUCHTYPE")]\n'
PEEK = "SELECT count(*) FROM information_schema.columns WHERE table_name='p2475_probe' AND column_name='half'"
LOOK = """
import app  # noqa: F401
import kalmido.core.db as d
c = d.connect_direct(d.DATABASE_URL)
print(c.execute(%r).fetchone()[0], c.execute("SELECT count(*) FROM kalmido_migrations WHERE id='p2475_probe.half'").fetchone()[0])
"""


def starts(frags, n=1):
    """n starts at the same moment, each in its own process: (exit code, output) of each."""
    code = RUN % (json.dumps(frags), json.dumps([]))
    ps = [subprocess.Popen(["docker", "exec", CT, "python3", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for _ in range(n)]
    return [(p.wait(timeout=180), p.stdout.read()) for p in ps]


def look():
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", LOOK % PEEK], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.split()[-2:]


[(rc, out)] = starts({"3478.py": STEP, "3483.py": GOOD, "3484.py": BROKEN})
check(rc != 0 and "NOSUCHTYPE" in out.upper(), f"#4285: the broken step stops the start {rc} {out[-200:]}")
check(look() == ["0", "0"], f"#4285: nothing of the steps before it stayed: {look()}")
both = starts({"3478.py": STEP, "3483.py": GOOD}, 2)
check([x[0] for x in both] == [0, 0], f"#4285: two starts at once both go through {[(x[0], x[1][-300:]) for x in both if x[0]]}")
check(look() == ["1", "1"], f"#4285: the step is done and recorded once {look()}")
notes = [json.loads(x[1].strip().splitlines()[-1])["mig"] for x in both if x[0] == 0]
check(all(["p2475_probe.half", "applied"] in [m[:2] for m in n] for n in notes), f"#4285: recorded as applied, not again {notes}")

tmp = tempfile.mkdtemp()
try:
    shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(tmp, "tools"), ignore=shutil.ignore_patterns("demo", "__pycache__"))
    core = os.path.join(tmp, "kalmido", "core")
    os.makedirs(os.path.join(core, "migrations.d"))
    shutil.copy(os.path.join(ROOT, "kalmido", "core", "schema.py"), core)
    check(cm.findings(ROOT) == [], f"#3478: schema.py as it is passes {cm.findings(ROOT)[:5]}")
    check(cm.findings(tmp) == [], "#3478: the copy passes")
    orig = open(os.path.join(core, "schema.py"), encoding="utf-8").read()

    def edited(a, b):
        with open(os.path.join(core, "schema.py"), "w", encoding="utf-8") as f:
            f.write(orig.replace(a, b, 1))
        return cm.findings(tmp)

    bad = edited('MIGRATIONS = [\n', 'MIGRATIONS = [\n    ("lists", "p2475_new", "ALTER TABLE lists ADD COLUMN p2475_new TEXT"),\n')
    check(len(bad) == 1 and "step lists.p2475_new" in bad[0] and "migrations.d" in bad[0], f"#3478: a new step in schema.py {bad}")
    bad = edited('INDEXES = """\n', 'INDEXES = """\nCREATE TABLE IF NOT EXISTS p2475_t (id BIGINT);\nCREATE INDEX IF NOT EXISTS p2475_i ON p2475_t(id);\n')
    check(any("table p2475_t" in x for x in bad) and any("index p2475_i" in x for x in bad), f"#3478: a new table and index in schema.py {bad}")
    edited("", "")

    def frag(name, text):
        p = os.path.join(core, "migrations.d", name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        out = cm.findings(tmp)
        return out, p

    bad, p = frag("3478.py", LINTED)
    check(bad == [], f"#3478: a fragment of data passes {bad}")
    check("p2475_probe" in cm.schema_src(tmp) and "p2475_probe.note" in cm.step_ids(cm.schema_src(tmp)),
          "#3478: the schema readers (rls_static, check_layout, the export lists) see the fragment")
    os.remove(p)
    for text, what in (("import os\n", "an import"), ("SCHEMA = open('x').read()\n", "code in a value"), ("OTHER = 1\n", "another name"),
                       ('MIGRATIONS = [("a", "b")]\n', "a short step"), ('AFTER = "UPDATE x"\n', "AFTER as a text")):
        bad, p = frag("3480.py", text)
        check(len(bad) == 1, f"#3478: {what} is a finding {bad}")
        os.remove(p)
    bad, p = frag("name.py", "")
    check(len(bad) == 1 and "task id" in bad[0], f"#3478: the file name {bad}")
    os.remove(p)

    # 2.509.0 (#4285): the statements
    def step(ddl, table="events", col="x"):
        return f"MIGRATIONS = [({table!r}, {col!r}, {ddl!r})]\n"
    for text in (step("ALTER TABLE events ADD COLUMN IF NOT EXISTS x TEXT"), step("ALTER TABLE events ADD COLUMN x TEXT NOT NULL DEFAULT ''"),
                 step("ALTER TABLE events ADD COLUMN x NUMERIC(10,2) DEFAULT 0"), step("ALTER TABLE events ADD COLUMN x TEXT DEFAULT 'DROP, a;b'"),
                 step("ALTER TABLE events ADD COLUMN x BIGINT REFERENCES users(id) ON DELETE SET NULL"),
                 'AFTER = ["CREATE INDEX IF NOT EXISTS i1 ON events(x) WHERE x IS NOT NULL"]\n',
                 'AFTER = ["ALTER TABLE events ADD COLUMN IF NOT EXISTS x BIGINT"]\n',
                 'SCHEMA = """-- the person\'s own rows\nCREATE TABLE IF NOT EXISTS n2 (id BIGINT, t TEXT DEFAULT \'--\');\nCREATE UNIQUE INDEX IF NOT EXISTS u4 ON n2(id);"""\n',
                 '# unique-ok u1: the column is new and NULL in every row\nAFTER = ["CREATE UNIQUE INDEX IF NOT EXISTS u1 ON events(x)"]\n',
                 'SCHEMA = """CREATE TABLE IF NOT EXISTS n1 (id BIGINT); CREATE UNIQUE INDEX IF NOT EXISTS u2 ON n1(id);"""\nAFTER = ["CREATE UNIQUE INDEX IF NOT EXISTS u3 ON n1(id)"]\n',
                 # 2.574.0 (#3779): the table of a feature taken out, with a reason, created nowhere any more
                 '# drop-ok old_t: the feature was taken out\nAFTER = ["DROP TABLE IF EXISTS old_t"]\n',
                 # review F5 (#3779): a column of a feature taken out, the same way
                 '# drop-ok events.old_c: the feature was taken out\nAFTER = ["ALTER TABLE events DROP COLUMN IF EXISTS old_c"]\n'):
        bad, p = frag("3481.py", text)
        check(bad == [], f"#4285: additive passes: {text.strip()[:90]} {bad}")
        os.remove(p)
    for text, what in ((step("ALTER TABLE events ADD COLUMN x TEXT NOT NULL"), "NOT NULL without a DEFAULT"),
                       (step("ALTER TABLE events DROP COLUMN x"), "DROP COLUMN"),
                       (step("ALTER TABLE events ALTER COLUMN x SET NOT NULL"), "ALTER COLUMN"),
                       (step("ALTER TABLE events ADD COLUMN x TEXT, DROP COLUMN y"), "a second change in the statement"),
                       (step("ALTER TABLE events ADD COLUMN x TEXT DEFAULT ''; DELETE FROM events"), "a second statement"),
                       (step("UPDATE events SET x=1"), "an UPDATE as a step"),
                       (step("ALTER TABLE events ADD COLUMN y TEXT"), "another column than the step says"),
                       (step("ALTER TABLE events ADD COLUMN x TEXT UNIQUE"), "a unique column"),
                       (step("ALTER TABLE events ADD COLUMN x BIGINT GENERATED BY DEFAULT AS IDENTITY"), "a generated column"),
                       ('AFTER = ["UPDATE events SET x=1"]\n', "an UPDATE in AFTER"),
                       ('AFTER = ["ALTER TABLE events ADD COLUMN x BIGINT"]\n', "a column in AFTER without IF NOT EXISTS"),
                       ('AFTER = ["ALTER TABLE events ADD COLUMN IF NOT EXISTS x TEXT NOT NULL"]\n', "NOT NULL without a DEFAULT in AFTER"),
                       ('AFTER = ["ALTER TABLE events DROP COLUMN x"]\n', "a DROP in AFTER"),
                       ('AFTER = ["CREATE INDEX CONCURRENTLY IF NOT EXISTS i ON events(x)"]\n', "CONCURRENTLY"),
                       ('AFTER = ["CREATE INDEX IF NOT EXISTS i ON events(x); DROP TABLE events"]\n', "a statement behind the index"),
                       ('AFTER = ["CREATE UNIQUE INDEX IF NOT EXISTS u ON events(x)"]\n', "UNIQUE on an existing table without a reason"),
                       ('# unique-ok u:\nAFTER = ["CREATE UNIQUE INDEX IF NOT EXISTS u ON events(x)"]\n', "a reason without words"),
                       ('# unique-ok other: x\nAFTER = ["CREATE UNIQUE INDEX IF NOT EXISTS u ON events(x)"]\n', "the reason of another index"),
                       ('SCHEMA = """CREATE UNIQUE INDEX IF NOT EXISTS u ON events(x);"""\n', "UNIQUE on an existing table in SCHEMA"),
                       ('SCHEMA = """DROP TABLE events;"""\n', "a DROP in SCHEMA"),
                       ('SCHEMA = """CREATE TABLE IF NOT EXISTS n3 (id BIGINT); -- don\'t\nDROP TABLE events; -- x\'\n"""\n', "a DROP behind a comment with an apostrophe"),
                       ('SCHEMA = """CREATE TABLE n4 (id BIGINT);"""\n', "CREATE TABLE without IF NOT EXISTS (runs at every start)"),
                       # 2.574.0 (#3779): a DROP TABLE without its reason, of a table schema.py still creates, without IF EXISTS
                       ('AFTER = ["DROP TABLE IF EXISTS old_t"]\n', "a DROP TABLE without a # drop-ok line"),
                       ('# drop-ok events: gone\nAFTER = ["DROP TABLE IF EXISTS events"]\n', "a dropped table schema.py still creates"),
                       ('# drop-ok old_t: gone\nAFTER = ["DROP TABLE old_t"]\n', "DROP TABLE without IF EXISTS"),
                       # review F5 (#3779): DROP COLUMN only with IF EXISTS, its reason, of a column added nowhere any more
                       ('AFTER = ["ALTER TABLE events DROP COLUMN IF EXISTS old_c"]\n', "a DROP COLUMN without a # drop-ok line"),
                       ('# drop-ok old_c: gone\nAFTER = ["ALTER TABLE events DROP COLUMN IF EXISTS old_c"]\n', "the reason without the table"),
                       ('# drop-ok events.old_c: gone\nAFTER = ["ALTER TABLE events DROP COLUMN old_c"]\n', "DROP COLUMN without IF EXISTS"),
                       ('# drop-ok events.location: gone\nAFTER = ["ALTER TABLE events DROP COLUMN IF EXISTS location"]\n',
                        "a dropped column schema.py still creates"),
                       ('# drop-ok events.imp_at: gone\nAFTER = ["ALTER TABLE events DROP COLUMN IF EXISTS imp_at"]\n',
                        "a dropped column a step still adds")):
        bad, p = frag("3482.py", text)
        check(len(bad) == 1, f"#4285: {what} is a finding {bad}")
        if "without IF EXISTS" in what:  # review F5: the finding says what is missing
            check(bool(bad) and "IF EXISTS" in bad[0] and "INDEX" not in bad[0], f"#3779: {what} names IF EXISTS {bad}")
        os.remove(p)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"p2475_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
