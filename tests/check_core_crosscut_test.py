#!/usr/bin/env python3
# kalmido-suite: after=p2501_a_nosham nodata
"""2.755.0 (#5267, stage Q0a): tools/check_core_crosscut.py. Static, no container.
 - a fragment with a new tag / comment / link / read mark table of an area: red, with file:line and what it looks like
 - the same table in the allow file: quiet; an allow line whose table is gone, dropped by a fragment or no longer looks like one: red
 - quiet: the core's own tables (obj_*), a share link (token_hash), a plain table, a join table with a column of its own
 - a table a fragment drops (DROP TABLE IF EXISTS) does not count
 - code outside kalmido/core: a new *_react( / need_*_say( / MENTION_RE red, a new *_search( only a hint
 - the repository: no finding
usage: check_core_crosscut_test.py"""
import os
import shutil
import sys
import tempfile

from kt import FAILS, OKS, check

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import check_core_crosscut as cc  # noqa: E402

SCHEMA = ("kalmido/core/schema.py", 'SCHEMA = """\nCREATE TABLE IF NOT EXISTS users (\n  id BIGSERIAL PRIMARY KEY, name TEXT);\n'
          'CREATE TABLE IF NOT EXISTS meetings (\n  id BIGSERIAL PRIMARY KEY,\n  org_id BIGINT REFERENCES orgs(id) ON DELETE CASCADE,\n'
          '  title TEXT NOT NULL DEFAULT \'\', amount NUMERIC(14,2));\n"""\n')


def frag(sql, name="9999_x.py"):
    return (f"kalmido/core/migrations.d/{name}", 'SCHEMA = """\n' + sql + '\n"""\n')


def run(*frags, allow=None):
    return cc.findings(srcs=[SCHEMA, *frags], allow={"tables": allow or {}}, code=False)[0]


check(not run(), f"a plain schema: no finding {run()}")
TAGS = frag("CREATE TABLE IF NOT EXISTS meeting_tags (\n  meeting_id BIGINT REFERENCES meetings(id) ON DELETE CASCADE,\n  name TEXT);")
out = run(TAGS)
check(len(out) == 1 and "table meeting_tags (kalmido/core/migrations.d/9999_x.py:2) looks like tags" in out[0] and "docs/dev/kern.md" in out[0],
      f"a new _tags table of an area is red, with file:line and the way out: {out}")
COMMENT = frag("CREATE TABLE IF NOT EXISTS meeting_talk (\n  id BIGSERIAL PRIMARY KEY,\n  meeting_id BIGINT,\n  body TEXT NOT NULL);")
out = run(COMMENT)
check(len(out) == 1 and "meeting_talk" in out[0] and "a comment" in out[0], f"an *_id + body table looks like a comment: {out}")
JOIN = frag("CREATE TABLE IF NOT EXISTS meeting_tasks (\n  meeting_id BIGINT REFERENCES meetings(id),\n  task_id BIGINT REFERENCES tasks(id),\n"
            "  created_at TIMESTAMPTZ, PRIMARY KEY (meeting_id, task_id));")
out = run(JOIN)
check(len(out) == 1 and "meeting_tasks" in out[0] and "a link" in out[0], f"a bare join of two tables looks like a link: {out}")
READ = frag("CREATE TABLE IF NOT EXISTS meeting_marks (\n  user_id BIGINT, meeting_id BIGINT, seen_at TIMESTAMPTZ);")
check(run(READ) and "a read mark" in run(READ)[0], f"seen_at looks like a read mark: {run(READ)}")
check(not run(TAGS, allow={"meeting_tags": "a reason"}), "the same table in the allow file stays quiet")
QUIET = frag("CREATE TABLE IF NOT EXISTS obj_tags (\n  kind TEXT, obj_id BIGINT, tag TEXT);\n"
             "CREATE TABLE IF NOT EXISTS meeting_share_links (\n  id BIGSERIAL PRIMARY KEY, meeting_id BIGINT, token_hash TEXT);\n"
             "CREATE TABLE IF NOT EXISTS meeting_seats (\n  meeting_id BIGINT REFERENCES meetings(id),\n  user_id BIGINT REFERENCES users(id),\n"
             "  seat TEXT);")
check(not run(QUIET), f"the core's own table, a share link and a join with a column of its own stay quiet: {run(QUIET)}")
DROPPED = frag("DROP TABLE IF EXISTS meeting_tags", "9999_y.py")
DROPPED = (DROPPED[0], 'AFTER = [\n    "DROP TABLE IF EXISTS meeting_tags",\n]\n')
check(not run(TAGS, DROPPED), f"a table a fragment drops does not count: {run(TAGS, DROPPED)}")
out = run(TAGS, DROPPED, allow={"meeting_tags": "a reason"})
check(len(out) == 1 and "meeting_tags is gone" in out[0], f"an allow line of a dropped table is red: {out}")
out = run(allow={"meeting_tags": "a reason", "meetings": "a reason"})
check(len(out) == 2 and all("take the line out" in x for x in out), f"an allow line of a missing / plain table is red: {out}")

# code: a temporary tree with schema.py, one area module and kalmido/core
tmp = tempfile.mkdtemp(prefix="c5267-")
for d in ("kalmido/core/migrations.d", "kalmido/meet", "tools"):
    os.makedirs(os.path.join(tmp, d))
with open(os.path.join(tmp, SCHEMA[0]), "w", encoding="utf-8") as f:
    f.write(SCHEMA[1])
with open(os.path.join(tmp, "kalmido/meet/routes.py"), "w", encoding="utf-8") as f:
    f.write("import re\nMENTION_RE = re.compile('x')\n\n\ndef meeting_react(mid):\n    pass\n\n\ndef need_meeting_say(c, m):\n    pass\n\n\n"
            "def meeting_search(q):\n    pass\n")
with open(os.path.join(tmp, "kalmido/core/reacts.py"), "w", encoding="utf-8") as f:
    f.write("def obj_react(c, kind, oid):\n    pass\n")
bad, hints = cc.findings(tmp, allow={})
check(len(bad) == 3 and any("meeting_react (kalmido/meet/routes.py:5)" in x for x in bad) and any("need_meeting_say" in x for x in bad)
      and any("MENTION_RE (kalmido/meet/routes.py:2)" in x for x in bad), f"code: react / say / mention outside the core is red, in the core not: {bad}")
check(len(hints) == 1 and "meeting_search (kalmido/meet/routes.py:13)" in hints[0], f"code: a search of its own is a hint: {hints}")
bad, hints = cc.findings(tmp, allow={"code": {"kalmido/meet/routes.py:meeting_react": "r", "kalmido/meet/routes.py:need_meeting_say": "r",
                                              "kalmido/meet/routes.py:MENTION_RE": "r", "kalmido/meet/routes.py:gone_react": "r"},
                                     "search_functions": {"kalmido/meet/routes.py:meeting_search": "r"}})
check(len(bad) == 1 and "gone_react is gone" in bad[0] and not hints, f"code: allowed ones are quiet, a gone one is red: {bad} {hints}")
shutil.rmtree(tmp, ignore_errors=True)

# the repository: no finding (paperless_links dropped by #5265 counts no more)
bad, hints = cc.findings()
check(not bad, f"the repository: {bad}")
check("paperless_links" not in cc.load_allow()["tables"], "paperless_links is not an exception (#5265 drops it)")

print(f"check_core_crosscut: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
