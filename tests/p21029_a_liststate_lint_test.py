#!/usr/bin/env python3
# kalmido-suite: after=p2501_a_nosham nodata
"""2.1029.0 (#5537, stage 1): tools/check_list_state.py and the migration fragment of the projects' state marker. Static, no
container.
 - a handwritten filter on lists.archived / deleted_at is counted: archived=0 / =1 / deleted_at IS NULL after FROM / JOIN lists,
   l.archived / lists.archived compared anywhere, l.deleted_at only in a line that reads lists l
 - not counted: reading the value (SELECT archived), other tables with the alias l (conn_links l), a filter of a table that
   stands before FROM lists in the line, list_state_sql() / otr_live(), the schema, the start's one-off fill (its flag)
 - the same number as the baseline: quiet; fewer / a file gone: a notice (--strict: red); --update only lowers
 - the repository: no finding, the baseline file is there
 - the fragment migrations.d/5537_a.py: additive column with a default, the trigger before INSERT / UPDATE of archived,
   deleted_at, state; tools/check_migrations.py has no finding for it
usage: p21029_a_liststate_lint_test.py"""
import os
import shutil
import subprocess
import sys
import tempfile

from kt import FAILS, OKS, check

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_list_state as ls  # noqa: E402

# ---- what counts
for text, want, what in [
    ('Q = "SELECT id FROM lists WHERE owner_id=? AND archived=0"', 1, "archived=0 after FROM lists"),
    ('Q = "SELECT id FROM lists WHERE archived = 1"', 1, "archived = 1 with spaces"),
    ('Q = "SELECT 1 FROM lists WHERE id=? AND deleted_at IS NULL"', 1, "deleted_at IS NULL after FROM lists"),
    ('Q = "SELECT 1 FROM lists WHERE id=? AND archived=0 AND deleted_at IS NULL"', 2, "both columns"),
    ('Q = "FROM lists l WHERE l.deleted_at IS NULL"', 1, "l.deleted_at in a line that reads lists l"),
    ('Q = "AND t.due IS NOT NULL AND l.archived=0"', 1, "l.archived compared anywhere (multi-line statement)"),
    ('Q = "JOIN lists l ON l.id=t.list_id WHERE l.archived<>0"', 1, "l.archived<>0"),
    ('Q = "SELECT id, name, archived FROM lists WHERE id=?"', 0, "reading the value is no filter"),
    ('Q = "SELECT 1 FROM conn_links l WHERE l.deleted_at IS NULL"', 0, "another table with the alias l"),
    ('Q = "SELECT * FROM hub_mails WHERE deleted_at IS NULL AND list_id IN (SELECT l.id FROM lists l"', 0, "a table before FROM lists"),
    ('Q = f"SELECT id FROM lists WHERE {list_state_sql()} AND id IN {otr_live(\'l\')}"', 0, "the helpers"),
    ('Q = "SELECT id FROM lists_sync WHERE archived=0"', 0, "a table lists_* is not lists"),
    ('Q = "SELECT id FROM habits WHERE archived=0"', 0, "habits.archived is not a project"),
    ('if gsetting(c, "migr_liststate5537") != "1":\n    c.execute("UPDATE lists SET state=state WHERE archived <> 0 OR deleted_at IS NOT NULL")', 0,
     "the start's one-off fill"),
]:
    got = ls.count_text(text)
    check(got == want, f"{what}: {got} (want {want})")


def tree(files, base=None):
    tmp = tempfile.mkdtemp(prefix="p21029a-")
    for rel, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True)
        with open(os.path.join(tmp, rel), "w", encoding="utf-8") as f:
            f.write(text)
    os.makedirs(os.path.join(tmp, "tools"), exist_ok=True)
    if base is not None:
        ls.save(tmp, base)
    return tmp


FILES = {
    "kalmido/proj/routes.py": 'A = "SELECT id FROM lists WHERE archived=0"\nB = "SELECT 1 FROM lists l WHERE l.deleted_at IS NULL"\n',
    "kalmido/proj/clean.py": 'from ..core.access import list_state_sql\nQ = f"SELECT 1 FROM lists WHERE {list_state_sql()}"\n',
    "kalmido/core/schema.py": 'S = "SELECT id FROM lists WHERE archived=0"\n',
    "kalmido/core/migrations.d/9999_x.py": 'S = "CREATE INDEX y ON lists(id) WHERE deleted_at IS NULL"\n',
}
tmp = tree(FILES, {"kalmido/proj/routes.py": 1})
now = ls.counts(tmp)
check(now == {"kalmido/proj/routes.py": 2}, f"counted: two in routes.py, none in the schema / for the helper {now}")
red, note = ls.findings(now, ls.load(tmp))
check(len(red) == 1 and "kalmido/proj/routes.py has 2" in red[0] and "baseline 1" in red[0] and "list_state_sql" in red[0],
      f"one more than the baseline: red, with the helper named {red}")
check(ls.main(["x", "--root", tmp]) == 1, "the script: exit 1")
red, note = ls.findings(now, {"kalmido/proj/routes.py": 2})
check(not red and not note, f"the same number: quiet {red} {note}")
red, note = ls.findings(now, {"kalmido/proj/routes.py": 3, "kalmido/proj/old.py": 1})
check(not red and len(note) == 2, f"fewer / a file gone: notices {note}")
red, _ = ls.findings(now, {"kalmido/proj/routes.py": 3, "kalmido/proj/old.py": 1}, strict=True)
check(len(red) == 2, f"--strict: the notices are red {red}")
check(ls.findings({"kalmido/new/x.py": 1}, {})[0], "a new file with one: red (not in the baseline = 0)")
shutil.rmtree(tmp, ignore_errors=True)

up = ls.update({"a.py": 1, "b.py": 5, "new.py": 2}, {"a.py": 3, "b.py": 4, "gone.py": 2})
check(up == {"a.py": 1, "b.py": 4}, f"--update: lowered, never raised, no new file, empty ones out {up}")
tmp = tree(FILES)
check(ls.main(["x", "--seed", "--root", tmp]) == 0 and ls.load(tmp) == {"kalmido/proj/routes.py": 2}, "--seed writes the very first baseline")
check(ls.main(["x", "--root", tmp]) == 0, "after --seed: quiet")
with open(os.path.join(tmp, "kalmido/proj/routes.py"), "a", encoding="utf-8") as f:
    f.write('C = "SELECT id FROM lists WHERE archived=1"\n')
check(ls.main(["x", "--seed", "--root", tmp]) == 1, "--seed never raises an existing baseline: a new filter stays red")
shutil.rmtree(tmp, ignore_errors=True)

# ---- the repository
now, base = ls.counts(), ls.load()
red, note = ls.findings(now, base)
check(not red, f"the repository: {red[:5]}")
check(os.path.exists(os.path.join(ROOT, ls.BASELINE)), "the repository has tools/list_state_baseline.json")

# ---- the migration fragment
frag = {}
with open(os.path.join(ROOT, "kalmido", "core", "migrations.d", "5537_a.py"), encoding="utf-8") as f:
    exec(compile(f.read(), "5537_a.py", "exec"), frag)  # nosec: a file of this repository, data only
steps = frag.get("MIGRATIONS", [])
check(steps == [("lists", "state", "ALTER TABLE lists ADD COLUMN IF NOT EXISTS state TEXT NOT NULL DEFAULT 'live'")],
      f"one additive column with a default {steps}")
sch = frag.get("SCHEMA", "")
check("BEFORE INSERT OR UPDATE OF archived, deleted_at, state ON lists FOR EACH ROW" in sch and "GENERATED" not in sch.upper(),
      "the trigger runs before every insert and every update of the three columns (no generated column)")
for want in ("'trash'", "'archived'", "'live'", "NEW.deleted_at IS NOT NULL", "COALESCE(NEW.archived, 0) <> 0"):
    check(want in sch, f"the trigger's rule names {want}")
check(sch.index("'trash'") < sch.index("'archived'"), "the trash comes first: an archived project in the trash is 'trash'")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_migrations.py")], capture_output=True, text=True)
check(r.returncode == 0, f"tools/check_migrations.py: no finding {r.stdout[-300:]}")

print(f"p21029_a_liststate_lint: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
