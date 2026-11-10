#!/usr/bin/env python3
# kalmido-suite: after=p2501_a_nosham nodata
"""2.755.0 (#5267, stage Q0a): tools/check_core_crosscut.py. Static, no container.
 - a fragment with a new tag / comment / link / read mark table of an area: red, with file:line and what it looks like
 - the same table in the allow file: quiet; an allow line whose table is gone, dropped by a fragment or no longer looks like one: red
 - quiet: the core's own tables (obj_*), a share link (token_hash), a plain table, a join table with a column of its own
 - a table a fragment drops (DROP TABLE IF EXISTS) does not count
 - code outside kalmido/core: a new *_react( / need_*_say( / MENTION_RE red, a new *_search( only a hint
 - 2.846.0 (#5522): a _shares table and a table with a user / org / group / agent id plus role or perm* (also added with
   ALTER TABLE) red, a role without such an id quiet; need_* / *_role / *_can outside kalmido/core red, in the core quiet,
   allowed ones quiet, a stale rights line red
 - 2.857.0 (#5523): a filter evaluator / condition dialog of its own outside the core's filter (core/filters.py, fltkern.js,
   fltdlg.js) red, in Python and in static/js; one that only uses the core (calls kflt_*, handed to kflt_where, a catalog's
   cond / old) quiet; a comment naming kflt_ is no use; allowed ones quiet, a stale filter line red
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

# 2.846.0 (#5522): shares and role tables of an area
SHARES = frag("CREATE TABLE IF NOT EXISTS meeting_shares (\n  id BIGSERIAL PRIMARY KEY,\n  meeting_id BIGINT,\n  token_hash TEXT);")
out = run(SHARES)
check(len(out) == 1 and "table meeting_shares (kalmido/core/migrations.d/9999_x.py:2) looks like a share" in out[0]
      and "kern.md section 3" in out[0], f"a new _shares table is red (also with token_hash): {out}")
PEOPLE = frag("CREATE TABLE IF NOT EXISTS meeting_people (\n  meeting_id BIGINT REFERENCES meetings(id),\n"
              "  user_id BIGINT REFERENCES users(id),\n  role TEXT NOT NULL DEFAULT 'view');")
out = run(PEOPLE)
check(len(out) == 1 and "meeting_people" in out[0] and "a share" in out[0], f"user_id + role is a share table, role no exception: {out}")
check(not run(PEOPLE, allow={"meeting_people": "a reason"}), "the same share table in the allow file stays quiet")
PERM = frag("CREATE TABLE IF NOT EXISTS meeting_access (\n  meeting_id BIGINT,\n  holder_id BIGINT REFERENCES groups(id),\n"
            "  perms TEXT);")
out = run(PERM)
check(len(out) == 1 and "meeting_access" in out[0] and "a share" in out[0], f"an id REFERENCES groups + perms is a share table: {out}")
LATER = frag("CREATE TABLE IF NOT EXISTS meeting_seats2 (\n  meeting_id BIGINT,\n  agent_id BIGINT,\n  seat TEXT);\n"
             "ALTER TABLE meeting_seats2 ADD COLUMN IF NOT EXISTS role TEXT;")
out = run(LATER)
check(len(out) == 1 and "meeting_seats2" in out[0] and "a share" in out[0], f"a role added later with ALTER TABLE counts: {out}")
NOROLE = frag("CREATE TABLE IF NOT EXISTS meeting_crew (\n  id BIGSERIAL PRIMARY KEY,\n  meeting_id BIGINT,\n  role TEXT);")
check(not run(NOROLE), f"a role without a user / org / group / agent id (a job title) stays quiet: {run(NOROLE)}")
out = run(allow={"meeting_people": "a reason"})
check(len(out) == 1 and "meeting_people is gone" in out[0], f"an allow line of a missing share table is red: {out}")

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
# 2.846.0 (#5522): rights checks of their own
with open(os.path.join(tmp, "kalmido/meet/rights.py"), "w", encoding="utf-8") as f:
    f.write("def need_meeting(c, mid):\n    pass\n\n\ndef meeting_role(c, uid, m):\n    pass\n\n\ndef meeting_can(c, uid, m):\n"
            "    pass\n\n\ndef _need_x():\n    pass\n")
with open(os.path.join(tmp, "kalmido/core/meetkern.py"), "w", encoding="utf-8") as f:
    f.write("def need_meeting(c, mid):\n    pass\n\n\ndef obj_meeting_role(c):\n    pass\n\n\ndef obj_meeting_can(c):\n    pass\n")
OLD = {"code": {"kalmido/meet/routes.py:meeting_react": "r", "kalmido/meet/routes.py:need_meeting_say": "r",
                "kalmido/meet/routes.py:MENTION_RE": "r"}, "search_functions": {"kalmido/meet/routes.py:meeting_search": "r"}}
bad, hints = cc.findings(tmp, allow=OLD)
check(len(bad) == 3 and any("need_meeting (kalmido/meet/rights.py:1) is a rights check of its own" in x for x in bad)
      and any("meeting_role (kalmido/meet/rights.py:5)" in x for x in bad) and any("meeting_can (kalmido/meet/rights.py:9)" in x for x in bad)
      and not any("kalmido/core/" in x or "need_meeting_say" in x for x in bad),
      f"code: need_* / *_role / *_can outside the core red, in the core quiet, need_*_say only once (code): {bad}")
bad, hints = cc.findings(tmp, allow=dict(OLD, rights={"kalmido/meet/rights.py:need_meeting": "r", "kalmido/meet/rights.py:meeting_role": "r",
                                                      "kalmido/meet/rights.py:meeting_can": "r", "kalmido/meet/rights.py:gone_can": "r"}))
check(len(bad) == 1 and "rights kalmido/meet/rights.py:gone_can is gone" in bad[0], f"code: allowed rights checks quiet, a gone one red: {bad}")
# 2.857.0 (#5523): filters of their own
RIGHTS = {"kalmido/meet/rights.py:need_meeting": "r", "kalmido/meet/rights.py:meeting_role": "r", "kalmido/meet/rights.py:meeting_can": "r"}
os.makedirs(os.path.join(tmp, "static/js"))
FILES = {
    "kalmido/meet/flt.py": "def meeting_filter_sql(rules):\n    return ' AND '.join(x['f'] for x in rules['conds'])\n\n\n"
                           "def _meet_cond_ok(cnd):\n    return None\n\n\n"
                           "def meeting_filter_where(c, rules):\n    return kflt_where(rules, lambda cnd: _meet_cond_ok(cnd))\n",
    "kalmido/core/filters.py": "def kflt_filter_match(item, rules):\n    pass\n",
    "static/js/meet.js": "function mtgFilterMatch(t, r) {  // unlike kflt_match\n  return r.conds.every(c => t[c.f] === c.v);\n}\n"
                         "const mtg_conds = r => kflt_conds(r, MTG_CAT);\n"
                         "function mtg_cfCond(c) {\n  return t => t.n > c.v;\n}\n"
                         "const MTG_CAT = {has: {room: (t, x) => t.room === x}, cond: c => (c.f === 'n' ? mtg_cfCond(c) : undefined)};\n"
                         "async function mtgCondDlg() {\n  return 1;\n}\n"
                         "const mtgSearch = q => q.trim();\n",
    "static/js/fltdlg.js": "function kfltCondRows(host) {\n  return host;\n}\n",
}
for name, text in FILES.items():
    with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
        f.write(text)
bad, hints = cc.findings(tmp, allow=dict(OLD, rights=RIGHTS))
check(len(bad) == 3 and any("meeting_filter_sql (kalmido/meet/flt.py:1) looks like a filter of its own" in x and "kern.md 'Filter'" in x for x in bad)
      and any("mtgFilterMatch (static/js/meet.js:1)" in x for x in bad) and any("mtgCondDlg (static/js/meet.js:9)" in x for x in bad),
      f"filter: an own evaluator in Python, one in the browser (a comment naming kflt_ is no use) and an own condition dialog are red: {bad}")
check(not any(n in x for x in bad for n in ("meeting_filter_where", "_meet_cond_ok", "mtg_conds", "mtg_cfCond", "kflt_filter_match", "kfltCondRows")),
      f"filter: using the core (calls kflt_*, the cnd function handed to kflt_where, a catalog's cond) and the core itself stay quiet: {bad}")
FLT = {"kalmido/meet/flt.py:meeting_filter_sql": "r", "static/js/meet.js:mtgFilterMatch": "r", "static/js/meet.js:mtgCondDlg": "r"}
bad, hints = cc.findings(tmp, allow=dict(OLD, rights=RIGHTS, filter=dict(FLT, **{"static/js/meet.js:mtg_conds": "r"})))
check(len(bad) == 1 and "filter static/js/meet.js:mtg_conds is gone or uses the core's filter now" in bad[0],
      f"filter: allowed ones quiet, a line whose definition uses the core is red: {bad}")
shutil.rmtree(tmp, ignore_errors=True)

# the repository: no finding (paperless_links dropped by #5265 counts no more)
bad, hints = cc.findings()
check(not bad, f"the repository: {bad}")
al = cc.load_allow()
check(all(isinstance(v, str) and len(v) > 20 for v in list(al["rights"].values()) + list(al["tables"].values())),
      "every allow line has a reason of its own (#5522)")
check({"fs_shares", "group_shares", "sheet_shares", "wiki_shares"} <= set(al["tables"]) and "kalmido/accounts/users.py:need_admin" in al["rights"],
      "today's share tables and rights checks stand in the allow file (#5522)")
check(all(isinstance(v, str) and len(v) > 20 for v in al["filter"].values()) and "kalmido/docs/dsearch.py:dsr_filters" in al["filter"],
      "today's filters outside the core stand in the allow file with their reason (#5523)")
check("paperless_links" not in cc.load_allow()["tables"], "paperless_links is not an exception (#5265 drops it)")

print(f"check_core_crosscut: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
