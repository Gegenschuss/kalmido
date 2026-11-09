#!/usr/bin/env python3
# kalmido-suite: after=p2501_a_nosham nodata
"""2.773.0 (#5292): tools/check_live_filter.py. Static, no container.
 - a new handwritten 'deleted_at IS NULL' (any case, any spaces, with an alias) in the server code is red, with the file
 - the same number as the baseline: quiet; fewer, or a file without any left: a notice (--strict: red)
 - the schema (schema.py, migrations.d: partial indexes) does not count, live_sql() does not count
 - --update lowers the numbers and takes out empty files, it never raises one or adds a file (the baseline only shrinks)
 - the repository: no finding, and no file of it above its baseline
usage: p2773_b_livefilter_test.py"""
import os
import shutil
import sys
import tempfile

from kt import FAILS, OKS, check

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import check_live_filter as lf  # noqa: E402


def tree(files, base=None):
    tmp = tempfile.mkdtemp(prefix="p2773b-")
    for rel, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True)
        with open(os.path.join(tmp, rel), "w", encoding="utf-8") as f:
            f.write(text)
    os.makedirs(os.path.join(tmp, "tools"), exist_ok=True)
    if base is not None:
        lf.save(tmp, base)
    return tmp


FILES = {
    "kalmido/meet/routes.py": 'A = "SELECT * FROM meetings WHERE deleted_at IS NULL"\nB = "SELECT * FROM m t WHERE t.deleted_at  is   null"\n',
    "kalmido/meet/clean.py": 'from ..core.access import live_sql\nQ = f"SELECT 1 FROM m WHERE {live_sql()}"\n',
    "kalmido/core/schema.py": 'S = "CREATE INDEX x ON m(id) WHERE deleted_at IS NULL"\n',
    "kalmido/core/migrations.d/9999_x.py": 'S = "CREATE INDEX y ON m(id) WHERE deleted_at IS NULL"\n',
}
tmp = tree(FILES, {"kalmido/meet/routes.py": 1})
now = lf.counts(tmp)
check(now == {"kalmido/meet/routes.py": 2}, f"counted: two in routes.py (case, spaces, alias), none in the schema / for live_sql {now}")
red, note = lf.findings(now, lf.load(tmp))
check(len(red) == 1 and "kalmido/meet/routes.py has 2" in red[0] and "baseline 1" in red[0] and "live_sql" in red[0], f"one more than the baseline: red {red}")
check(lf.main(["x", "--root", tmp]) == 1, "the script: exit 1")
red, note = lf.findings(now, {"kalmido/meet/routes.py": 2})
check(not red and not note, f"the same number: quiet {red} {note}")
red, note = lf.findings(now, {"kalmido/meet/routes.py": 3, "kalmido/meet/old.py": 1})
check(not red and len(note) == 2 and any("lower it" in x for x in note) and any("old.py has none" in x for x in note), f"fewer / a file gone: notices {note}")
red, _ = lf.findings(now, {"kalmido/meet/routes.py": 3, "kalmido/meet/old.py": 1}, strict=True)
check(len(red) == 2, f"--strict: the notices are red {red}")
check(lf.findings({"kalmido/new/x.py": 1}, {})[0], "a new file with one: red (not in the baseline = 0)")
shutil.rmtree(tmp, ignore_errors=True)

# ---- --update only shrinks
up = lf.update({"a.py": 1, "b.py": 5, "new.py": 2}, {"a.py": 3, "b.py": 4, "gone.py": 2})
check(up == {"a.py": 1, "b.py": 4}, f"--update: lowered, never raised, no new file, empty ones out {up}")
tmp = tree(FILES, {"kalmido/meet/routes.py": 5, "kalmido/meet/old.py": 1})
check(lf.main(["x", "--update", "--root", tmp]) == 0 and lf.load(tmp) == {"kalmido/meet/routes.py": 2}, f"the script --update writes it {lf.load(tmp)}")
shutil.rmtree(tmp, ignore_errors=True)

# ---- the repository
now, base = lf.counts(), lf.load()
red, note = lf.findings(now, base)
check(not red, f"the repository: {red[:5]}")
check(base and sum(base.values()) >= sum(now.values()), f"the repository's baseline holds every file ({sum(base.values())} / {sum(now.values())})")
check(lf.HAND.search("x.deleted_at IS NULL") and not lf.HAND.search("deleted_at IS NOT NULL") and not lf.HAND.search("undeleted_at IS NULL"),
      "the pattern: IS NOT NULL and longer names do not count")

print(f"p2773_b_livefilter: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
