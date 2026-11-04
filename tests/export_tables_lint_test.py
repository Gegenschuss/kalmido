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
rc, out = with_edit(("admin", "exportleft.py"), '"wiki_versions": "history of knowledge pages",', "")
check(rc == 1 and "wiki_versions: not yet in the account export but without a readable name" in out, f"an area without a readable name is a finding: {out[-300:]}")
rc, out = with_edit(("accounts", "settings.py"), '    q = {\n        "lists":', '    q = {\n        "zz_part": ("SELECT * FROM habits", ()),\n        "lists":')
check(rc == 1 and "zz_part" in out, f"a part the import does not know is a finding: {out[-300:]}")
rc, out = with_edit(("admin", "orgexport.py"), '    ("bookmarks.json", "bookmarks", "org_id=?"),\n',
                    '    ("bookmarks.json", "bookmarks", "org_id=?"),\n    ("zz/area.json", "notes", "org_id=?"),\n')
check(rc == 1 and "zz/area.json" in out, f"an area the import does not know is a finding: {out[-300:]}")

# 2.464.0 (#3841): the reasons are keys of the language files, also the ones of the organisation export and without the mark in the manifest
spec = importlib.util.spec_from_file_location("i18nkeys", os.path.join(ROOT, "kalmido", "core", "i18nkeys.py"))
ik = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ik)
keys = ik.reason_keys(ROOT)
# 2.531.0 (#4317): + the readable names of the areas not yet in the account export (UMZ_LATER_NAMES)
check({"not yet in the account export", "credentials", "the trash", "not yet in the export",
       "history of knowledge pages"} <= set(keys) and not any("not_included" in k for k in keys), f"the reasons are read: {sorted(keys)[:5]}")
with open(os.path.join(ROOT, "static", "i18n", "de.json"), encoding="utf-8") as f:
    de = json.load(f)
check(not [k for k in keys if k not in de], f"every reason is translated: {[k for k in keys if k not in de][:5]}")

print(f"export_tables_lint: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
