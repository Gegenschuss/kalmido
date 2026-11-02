#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.475.0 (#3478): migrations as fragments in kalmido/core/migrations.d. Own container, a real start routine (init_db) on a
fragment folder made here, the app itself has none yet; invented names only.
 - a start creates a fragment's table, column, index and AFTER and records the step; a second start changes nothing
 - a database without the column (an old one) gets it, "again" when the step was recorded; a second step of one column is table.col#2
 - frag_load: name order, only .py, no folder = nothing
 - tools/check_migrations.py: schema.py as it is passes, a new step / table / index there is a finding, a fragment with code too;
   the checks that read the schema see the fragments (schema_src)
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

    bad, p = frag("3478.py", STEP)
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
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"p2475_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
