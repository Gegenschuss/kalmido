#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.362.4 (#3107) tools/check_export_tables.py finds what it is there for, on a copy of the sources; no container:
 1. the sources as they are: no finding
 2. a new table with a person column in no export
 3. a reason for a table that is gone (stale)
 4. a new part of the account export the import neither reads nor names
 5. a table exported AND named as left out
 6. a new office table outside the retention export
 7. an area of the organisation export the import neither maps nor names
 8. 2.464.0 (#3841): every reason is a translated key
 9. 2.531.0 (#4317): every table counts (a table without a person column in no list, UMZ_FREE_TABLES stale or holding a person's
    data, an area not yet in the export without its readable name)
10. 2.1093.0 (#5289): the export register of the core: read (obj_export, obj_register export=), a registered table by hand too,
    twice, gone, or a table of the core without an entry is a finding
11. 2.1097.0 (#5949): the register's account queries (acct / acct_more) are parts of the account export and its names count as
    UMZ_LEFT: a part by hand too, a name by hand too, a part the import neither reads nor names, a node clause outside org
usage: python3 tests/export_tables_lint_test.py"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(N, "..")
sys.path.insert(0, N)
from kt import FAILS, OKS, check  # noqa: E402

TOOL = os.path.join(ROOT, "tools", "check_export_tables.py")


def lint(root=ROOT):
    r = subprocess.run([sys.executable, TOOL, "--root", root], capture_output=True, text=True)
    return r.returncode, r.stdout


def with_edit(path, old, new):
    """The tool's output with one source file changed in a copy."""
    with tempfile.TemporaryDirectory() as d:
        k = os.path.join(d, "kalmido")
        for sub in ("core", "accounts", "admin"):
            shutil.copytree(os.path.join(ROOT, "kalmido", sub), os.path.join(k, sub))
        p = os.path.join(k, *path)
        with open(p, encoding="utf-8") as f:
            s = f.read()
        assert old in s, old
        with open(p, "w", encoding="utf-8") as f:
            f.write(s.replace(old, new, 1))
        return lint(d)


rc, out = lint()
check(rc == 0, f"the sources have no finding: {out[-600:]}")
check("0 finding(s)" in out, f"and it says so: {out[-200:]}")

SCHEMA = ("core", "schema.py")
TABLE = "CREATE TABLE IF NOT EXISTS {} (\n  id BIGINT PRIMARY KEY, {} BIGINT);\nCREATE TABLE IF NOT EXISTS filters ("
rc, out = with_edit(SCHEMA, "CREATE TABLE IF NOT EXISTS filters (", TABLE.format("zz_notes", "user_id"))
check(rc == 1 and "zz_notes" in out and "UMZ_LEFT_TABLES" in out, f"a new table with a person column is a finding: {out[-300:]}")
rc, out = with_edit(SCHEMA, "CREATE TABLE IF NOT EXISTS filters (",
                    "CREATE TABLE IF NOT EXISTS zz_comment (  -- a comment\n  id BIGINT PRIMARY KEY, kind TEXT,  -- another\n  user_id BIGINT);\n"
                    "CREATE TABLE IF NOT EXISTS filters (")
check(rc == 1 and "zz_comment" in out, f"a column after a comment is seen: {out[-300:]}")
rc, out = with_edit(("accounts", "settings.py"), '"pomos": ("SELECT * FROM pomos WHERE user_id=?", (uid,)),',
                    '"pomos": ("SELECT (SELECT 1 FROM pomos) AS x, * FROM habits WHERE user_id=?", (uid,)),')
check(rc == 1 and "pomos: has user_id" in out, f"a table only named in a subselect does not count as exported: {out[-300:]}")
# 2.510.0 (#4286): a secret-like column of an exported table
rc, out = with_edit(("admin", "orgexport.py"), '"token", "token_hash", ', "")
check(rc == 1 and ".token_hash: named like a secret" in out, f"a secret-like column that is no longer dropped is a finding: {out[-300:]}")
rc, out = with_edit(SCHEMA, "CREATE TABLE IF NOT EXISTS office_texts (", "CREATE TABLE IF NOT EXISTS office_texts (\n  zz_api_secret TEXT,")
check(rc == 1 and "office_texts.zz_api_secret" in out, f"a new secret-like column in an exported table is a finding: {out[-300:]}")
rc, out = with_edit(SCHEMA, "CREATE TABLE IF NOT EXISTS filters (", TABLE.format("office_zz", "org_id"))
check(rc == 1 and "office_zz" in out and "RX_LEFT_TABLES" in out, f"a new office table is a finding: {out[-300:]}")
rc, out = with_edit(("admin", "exportleft.py"), "UMZ_LEFT_TABLES = {\n", 'UMZ_LEFT_TABLES = {\n    "zz_gone": _SERVER,\n')
check(rc == 1 and "zz_gone: stale" in out, f"a reason for a table that is gone is a finding: {out[-300:]}")
rc, out = with_edit(("admin", "exportleft.py"), "UMZ_LEFT_TABLES = {\n", 'UMZ_LEFT_TABLES = {\n    "tasks": _SERVER,\n')
check(rc == 1 and "tasks: in the account export and in UMZ_LEFT_TABLES" in out, f"exported and left out is a finding: {out[-300:]}")
# 2.531.0 (#4317 F12, audit #2425): every table counts, not only those with a person column
rc, out = with_edit(SCHEMA, "CREATE TABLE IF NOT EXISTS filters (", "CREATE TABLE IF NOT EXISTS zz_pairs (\n  a_id BIGINT, b_id BIGINT);\nCREATE TABLE IF NOT EXISTS filters (")
check(rc == 1 and "zz_pairs: a table but is neither" in out and "UMZ_FREE_TABLES" in out, f"a new table without a person column is a finding: {out[-300:]}")
rc, out = with_edit(("admin", "acctexport.py"), "FROM conn_links l", "FROM users l")
check(rc == 1 and "conn_links: a table but is neither" in out, f"the connections out of the export are a finding: {out[-300:]}")
rc, out = with_edit(("admin", "exportleft.py"), "UMZ_FREE_TABLES = {\n", 'UMZ_FREE_TABLES = {\n    "zz_gone": "x",\n')
check(rc == 1 and "zz_gone: stale in UMZ_FREE_TABLES" in out, f"a table with nobody's data that is gone is a finding: {out[-300:]}")
rc, out = with_edit(("admin", "exportleft.py"), "UMZ_FREE_TABLES = {\n", 'UMZ_FREE_TABLES = {\n    "habits": "x",\n')
check(rc == 1 and "habits: in UMZ_FREE_TABLES but it holds" in out, f"a table with a person's data named as nobody's is a finding: {out[-300:]}")
# 2.958.0 (#5281): the versions of the knowledge pages are rows of obj_versions
# 2.1093.0 (#5289): obj_versions says it in the export register now (acct_later): an old table's name is taken out
rc, out = with_edit(("admin", "exportleft.py"), '"wiki_spaces": "spaces of knowledge pages",', "")
check(rc == 1 and "wiki_spaces: not yet in the account export but without a readable name" in out, f"an area without a readable name is a finding: {out[-300:]}")
rc, out = with_edit(("accounts", "settings.py"), '    q = {\n        "lists":', '    q = {\n        "zz_part": ("SELECT * FROM habits", ()),\n        "lists":')
check(rc == 1 and "zz_part" in out, f"a part the import does not know is a finding: {out[-300:]}")
rc, out = with_edit(("admin", "orgexport.py"), '    ("bookmarks.json", "bookmarks", "org_id=?"),\n',
                    '    ("bookmarks.json", "bookmarks", "org_id=?"),\n    ("zz/area.json", "notes", "org_id=?"),\n')
check(rc == 1 and "zz/area.json" in out, f"an area the import does not know is a finding: {out[-300:]}")

# 2.1093.0 (#5289, stage Q11): the export register of the core (kalmido/core/objexport.py)
OEXP = ("core", "objexport.py")
check("16 in the export register" in lint()[1], f"the register is read: {lint()[1][-200:]}")
rc, out = with_edit(("admin", "exportleft.py"), "UMZ_LEFT_TABLES = {\n", 'UMZ_LEFT_TABLES = {\n    "obj_seen": _VIEW,\n')
check(rc == 1 and "obj_seen: in the export register" in out and "UMZ_LEFT_TABLES" in out, f"a registered table by hand too (account) is a finding: {out[-300:]}")
rc, out = with_edit(("admin", "orgexport.py"), '    ("bookmarks.json", "bookmarks", "org_id=?"),\n',
                    '    ("bookmarks.json", "bookmarks", "org_id=?"),\n    ("zz/links.json", "obj_links", "org_id=?"),\n')
check(rc == 1 and "obj_links: in the export register" in out and "OX_AREAS" in out, f"a registered table by hand too (organisation) is a finding: {out[-300:]}")
rc, out = with_edit(("admin", "retexport.py"), "RX_TABLES = (\n", 'RX_TABLES = (\n    ("zz/v.csv", "obj_versions"),\n')
check(rc == 1 and "obj_versions: in the export register" in out and "RX_TABLES" in out, f"a registered table by hand too (retention) is a finding: {out[-300:]}")
rc, out = with_edit(("admin", "acctimport.py"), 'UMZ_READ_OWN = frozenset((\n', 'UMZ_READ_OWN = frozenset((\n    "comments",\n')
check(rc == 1 and "comments: a part in the export register and by hand in UMZ_READ_OWN" in out, f"a registered part by hand too is a finding: {out[-300:]}")
# 2.1097.0 (#5949): obj_notif_cap carries account queries now, the cases use obj_seen's one-line entry
ANCH = 'obj_export("obj_seen", acct_left=_VIEW)'
rc, out = with_edit(OEXP, ANCH, ANCH + '\nobj_export("obj_seen", acct_left=_VIEW)')
check(rc == 1 and "obj_seen: registered twice" in out, f"a table registered twice is a finding: {out[-300:]}")
rc, out = with_edit(OEXP, ANCH, "pass")
check(rc == 1 and "obj_seen: a table of the core without an entry in the export register" in out, f"a core table without an entry is a finding: {out[-300:]}")
rc, out = with_edit(OEXP, ANCH, ANCH + '\nobj_export("obj_zz_gone")')
check(rc == 1 and "obj_zz_gone: stale in the export register" in out, f"a registered table that is gone is a finding: {out[-300:]}")
# a kind's own table through obj_register(..., export={...}): read like obj_export; without it the table is a finding
rc, out = with_edit(SCHEMA, "CREATE TABLE IF NOT EXISTS filters (", TABLE.format("zz_kind", "org_id"))
check(rc == 1 and "zz_kind" in out, f"setup: a new kind's table in no list is a finding: {out[-300:]}")
KIND = ('\nobj_register("zzk", "zz_kind", label="x", fields={}, export={"org_left": "derived or working data, rebuilt on the target", '
        '"acct_left": "derived or working data, rebuilt on the target"})\n')
with tempfile.TemporaryDirectory() as d:
    k = os.path.join(d, "kalmido")
    for sub in ("core", "accounts", "admin"):
        shutil.copytree(os.path.join(ROOT, "kalmido", sub), os.path.join(k, sub))
    for path, old, new in ((SCHEMA, "CREATE TABLE IF NOT EXISTS filters (", TABLE.format("zz_kind", "org_id")), (OEXP, ANCH, ANCH + KIND)):
        p = os.path.join(k, *path)
        with open(p, encoding="utf-8") as f:
            s = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(s.replace(old, new, 1))
    rc, out = lint(d)
check(rc == 0 and "17 in the export register" in out, f"obj_register export= is read: the kind's table is placed {out[-300:]}")

# 2.1097.0 (#5949): the register's account queries and names (acct / acct_more), its node clauses
rc, out = with_edit(("accounts", "settings.py"), '        "pomos": ("SELECT * FROM pomos WHERE user_id=?", (uid,)),\n',
                    '        "pomos": ("SELECT * FROM pomos WHERE user_id=?", (uid,)),\n        "comments": ("SELECT * FROM tasks WHERE id=?", (uid,)),\n')
check(rc == 1 and "comments: a part of the account export in the export register (obj_comments) and by hand" in out,
      f"a register part by hand in a query function too is a finding: {out[-300:]}")
rc, out = with_edit(("admin", "acctimport.py"), '    (N_("Channel messages"), ("channel_messages",)),\n',
                    '    (N_("Channel messages"), ("channel_messages",)), (N_("Reactions"), ("reactions",)),\n')
check(rc == 1 and "reactions: named in the export register (obj_reactions) and by hand in UMZ_LEFT_OWN" in out,
      f"a register name by hand in UMZ_LEFT_OWN too is a finding: {out[-300:]}")
rc, out = with_edit(OEXP, ANCH, 'obj_export("obj_seen", acct_left=_VIEW, acct_more=(("zz_part", "SELECT * FROM obj_seen WHERE user_id=?"),))')
check(rc == 1 and "zz_part: a part of the account export that acctimport.py neither reads" in out,
      f"a register part the import neither reads nor names is a finding: {out[-300:]}")
rc, out = with_edit(OEXP, ANCH, 'obj_export("obj_seen", acct_left=_VIEW, acct_more=(("zz_part", "SELECT * FROM obj_seen WHERE user_id=?", "Reactions"),))')
check("zz_part" not in out, f"a register part with its name in the import's preview is known: {out[-300:]}")
rc, out = with_edit(OEXP, ANCH, 'obj_export("obj_seen", acct_left=_VIEW, nodes=(("zz/n.json", "ref_id IN ({NODES})"),))')
check(rc == 1 and "obj_seen: the node clause of zz/n.json names no archive of its org entries" in out, f"a node clause outside org is a finding: {out[-300:]}")

# 2.464.0 (#3841): the reasons are keys of the language files, also the ones of the organisation export and without the mark in the manifest
spec = importlib.util.spec_from_file_location("i18nkeys", os.path.join(ROOT, "kalmido", "core", "i18nkeys.py"))
ik = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ik)
keys = ik.reason_keys(ROOT)
# 2.531.0 (#4317): + the readable names of the areas not yet in the account export (UMZ_LATER_NAMES)
# 2.1073.0 (#5865): "the trash" (office_trash) went with its table; "invitations" stands for the not_included ones
check({"not yet in the account export", "credentials", "invitations", "not yet in the export",
       "history of knowledge pages"} <= set(keys) and not any("not_included" in k for k in keys), f"the reasons are read: {sorted(keys)[:5]}")
with open(os.path.join(ROOT, "static", "i18n", "de.json"), encoding="utf-8") as f:
    de = json.load(f)
check(not [k for k in keys if k not in de], f"every reason is translated: {[k for k in keys if k not in de][:5]}")

print(f"export_tables_lint: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
