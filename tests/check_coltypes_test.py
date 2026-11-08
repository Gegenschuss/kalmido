#!/usr/bin/env python3
# kalmido-suite: after=p2501_a_nosham nodata
"""2.755.0 (#5305): tools/check_coltypes.py. Static, no container.
 - a new table / ADD COLUMN step / AFTER ADD COLUMN with a point in time as TEXT, a yes / no as BIGINT 0/1 or JSON as TEXT: red,
   with file:line and the real type; the same with TIMESTAMPTZ / DATE / BOOLEAN / JSONB, a count, a plain text: quiet
 - a column on the baseline: quiet; a baseline line whose column was moved (ALTER COLUMN ... TYPE), dropped or is gone: red
 - a DEFAULT 'a,b' text is no second column; the marker coltype-ok on the line lets one column through
 - the repository: no finding
usage: check_coltypes_test.py"""
import os
import sys

from kt import FAILS, OKS, check

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import check_coltypes as ct  # noqa: E402

SCHEMA = ("kalmido/core/schema.py", 'SCHEMA = """\nCREATE TABLE IF NOT EXISTS meetings (\n  id BIGSERIAL PRIMARY KEY,\n'
          "  types TEXT NOT NULL DEFAULT 'docs,images',\n  created_at TIMESTAMPTZ NOT NULL, day DATE, held_on DATE,\n"
          "  is_open BOOLEAN NOT NULL DEFAULT FALSE, seats BIGINT NOT NULL DEFAULT 0, opts JSONB NOT NULL DEFAULT '{}',\n"
          "  note TEXT NOT NULL DEFAULT '', amount NUMERIC(14,2));\n\"\"\"\n")


def frag(text, name="9999_x.py"):
    return (f"kalmido/core/migrations.d/{name}", text)


def run(*frags, base=None):
    return ct.findings(srcs=[SCHEMA, *frags], base=base or {})


check(not run(), f"real types, a count, a plain text and a DEFAULT 'a,b' text: no finding {run()}")
cols = ct.columns([SCHEMA])
check("meetings.types" in cols and not any("images" in k for k in cols), f"a comma inside a DEFAULT text is no column boundary: {sorted(cols)}")
NEW = frag('SCHEMA = """\nCREATE TABLE IF NOT EXISTS meeting_marks (\n  id BIGSERIAL PRIMARY KEY,\n  seen_at TEXT,\n'
           "  is_done BIGINT NOT NULL DEFAULT 0,\n  pinned INTEGER NOT NULL DEFAULT 0,\n  extra_json TEXT,\n"
           "  filters TEXT NOT NULL DEFAULT '[]', valid_until TEXT);\n\"\"\"\n")
out = run(NEW)
got = {x.split(":")[1].strip().split(" ")[0] for x in out}
check(got == {"meeting_marks.seen_at", "meeting_marks.is_done", "meeting_marks.pinned", "meeting_marks.extra_json", "meeting_marks.filters",
              "meeting_marks.valid_until"}, f"a new table: every column of the old habits is red: {out}")
check(any("meeting_marks.seen_at (kalmido/core/migrations.d/9999_x.py:4): a point in time as TEXT: use TIMESTAMPTZ" in x for x in out)
      and any("is_done" in x and "BOOLEAN" in x for x in out) and any("extra_json" in x and "JSONB" in x for x in out),
      f"the finding names file:line and the real type: {out}")
STEP = frag('MIGRATIONS = [\n    ("meetings", "closed_at", "ALTER TABLE meetings ADD COLUMN closed_at TEXT"),\n'
            '    ("meetings", "has_room", "ALTER TABLE meetings ADD COLUMN has_room BIGINT NOT NULL DEFAULT 0"),\n'
            '    ("meetings", "ends_at", "ALTER TABLE meetings ADD COLUMN ends_at TIMESTAMPTZ"),\n]\n'
            'AFTER = ["ALTER TABLE meetings ADD COLUMN IF NOT EXISTS layout TEXT NOT NULL DEFAULT \'{}\'"]\n')
out = run(STEP)
check(len(out) == 3 and all(k in " ".join(out) for k in ("meetings.closed_at", "meetings.has_room", "meetings.layout")),
      f"MIGRATIONS and AFTER steps: the old habits red, TIMESTAMPTZ quiet: {out}")
check(any("meetings.closed_at (kalmido/core/migrations.d/9999_x.py:2)" in x for x in out), f"a step's finding names its line: {out}")
BASE = {"meetings.closed_at": "time", "meetings.has_room": "bool", "meetings.layout": "json"}
check(not run(STEP, base=BASE), "the same columns on the baseline stay quiet")
out = run(STEP, base=dict(BASE, **{"meetings.closed_at": "bool"}))
check(len(out) == 1 and "meetings.closed_at (" in out[0], f"a baseline line with another rule does not cover the column: {out}")
MOVED = frag('AFTER = ["ALTER TABLE meetings ALTER COLUMN closed_at TYPE TIMESTAMPTZ USING closed_at::timestamptz",\n'
             '         "ALTER TABLE meetings DROP COLUMN IF EXISTS has_room"]\n', "9999_y.py")
out = run(STEP, MOVED, base=BASE)
check(len(out) == 2 and any("meetings.closed_at has a real type by now" in x for x in out) and any("meetings.has_room has a real type by now or is gone" in x for x in out),
      f"a moved and a dropped column: their baseline lines are red: {out}")
GONE = frag('AFTER = ["DROP TABLE IF EXISTS meeting_marks"]\n', "9999_z.py")
check(not run(NEW, GONE), f"a table a fragment drops does not count: {run(NEW, GONE)}")
MARKED = frag('MIGRATIONS = [\n    ("meetings", "label_on", "ALTER TABLE meetings ADD COLUMN label_on TEXT"),  # coltype-ok: the text on a label, no day\n]\n')
check(not run(MARKED), f"the marker coltype-ok lets one column through: {run(MARKED)}")
check(len(run(base={"meetings.gone_at": "time"})) == 1, "a baseline line of a column that never was is red")

# the repository: no finding (paperless_links dropped by #5265 counts no more)
bad = ct.findings()
check(not bad, f"the repository: {bad}")
check(not any(k.startswith("paperless_links.") for k in ct.baseline()), "paperless_links is not on the baseline (#5265 drops it)")

print(f"check_coltypes: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
