#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.755.0 part D (#5296): table / column names in SQL text only through qi() (kalmido/core/pg.py), against a fresh container
(the code runs inside it, like a CLI next to the server). Scratch tables p2755_* only, no people's data.
 - qi(): a name from the allowlist comes back double-quoted; a name not in it, an upper-case / quoted / injected name, a
   non-string is a ValueError; a string as the allowlist is a TypeError (a substring test is no allowlist)
 - qi() with table_names(c) / table_columns(c, t): a real query through the driver's ? translation works with quoted names
 - core/merges.mg_repoint: moves the rows, drops the one that would collide on the primary key; an unknown table or column is
   refused before any SQL (ValueError), nothing moved
 - core/writes._write_back: writes a snapshot back (main row + many rows); a snapshot key that is no column is left out, a
   table that is not in the schema is refused
 - accounts/orgs.obj_org_set: a table outside its allowlist (ev_cals / books) is refused before any SQL
usage: p2755_d_qi_test.py <datadir>"""
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import CT, check, dbx, done  # noqa: E402


def in_app(code):
    """Runs python code inside the server container (the app loaded, c = a connection, system context); -> the JSON it prints
    last (or the whole output on an error)."""
    body = "\n".join("    " + x for x in code.strip().split("\n"))
    out = subprocess.run(["docker", "exec", CT, "python", "-c",
                          "import json\nimport app\nfrom kalmido.core.db import connect\n"
                          "from kalmido.core.pg import system_ctx, qi, table_names, table_columns\nc = connect()\n"
                          "with system_ctx(c):\n" + body + "\nc.close()"],
                         capture_output=True, text=True)
    lines = [x for x in out.stdout.strip().split("\n") if x.startswith("{")]
    try:
        return json.loads(lines[-1])
    except (IndexError, ValueError):
        return {"_out": (out.stdout + out.stderr)[-1500:]}


def refused(expr):
    """Code that evaluates expr and records the exception's class name (or "none")."""
    return f"try:\n    {expr}\n    r = 'none'\nexcept Exception as e:\n    r = type(e).__name__"


# --- 1. qi() itself
r = in_app("""
out = {"ok": qi("users", {"users", "lists"}), "list": qi("lists", ["users", "lists"]), "dict": qi("id", {"id": 1})}
for k, expr in {"absent": "qi('tasks', {'users'})", "upper": "qi('Users', {'Users'})", "quote": "qi('a\\"b', {'a\\"b'})",
                "inject": "qi('users; DROP TABLE users', {'users; DROP TABLE users'})", "space": "qi('a b', {'a b'})",
                "empty": "qi('', {''})", "none": "qi(None, {None})", "num": "qi(1, {1})", "long": "qi('a' * 64, {'a' * 64})",
                "strallow": "qi('user', 'users')", "dash": "qi('a-b', {'a-b'})"}.items():
    try:
        eval(expr)
        out[k] = "none"
    except Exception as e:
        out[k] = type(e).__name__
print(json.dumps(out))
""")
check(r.get("ok") == '"users"' and r.get("list") == '"lists"' and r.get("dict") == '"id"', f"qi quotes an allowed name: {r}")
for k in ("absent", "upper", "quote", "inject", "space", "empty", "none", "num", "long", "dash"):
    check(r.get(k) == "ValueError", f"qi refuses {k} with a ValueError: {r.get(k)} {r.get('_out', '')}")
check(r.get("strallow") == "TypeError", f"qi refuses a string as the allowlist (substring test): {r.get('strallow')}")

# --- 2. a real query with quoted names (the driver's ? translation keeps quoted identifiers)
r = in_app("""
tabs = table_names(c)
n = c.execute(f"SELECT COUNT(*) FROM {qi('users', tabs)} WHERE {qi('id', table_columns(c, 'users'))} > ?", (0,)).fetchone()[0]
print(json.dumps({"n": n, "has_users": "users" in tabs, "no_view_typo": "userz" not in tabs}))
""")
check(r.get("has_users") and r.get("no_view_typo") and isinstance(r.get("n"), int), f"a query with qi() names runs: {r}")

# --- scratch tables (the app works as kalmido_app: rights on them like obj_probe.py)
for sql in ("DROP TABLE IF EXISTS p2755_ref, p2755_pk, p2755_w, p2755_wm",
            "CREATE TABLE p2755_ref (id BIGINT PRIMARY KEY, target BIGINT, note TEXT)",
            "CREATE TABLE p2755_pk (target BIGINT, tag TEXT, PRIMARY KEY (target, tag))",
            "CREATE TABLE p2755_w (id BIGINT PRIMARY KEY, title TEXT, body TEXT)",
            "CREATE TABLE p2755_wm (w_id BIGINT, pos INT, txt TEXT)",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON p2755_ref, p2755_pk, p2755_w, p2755_wm TO kalmido_app",
            "INSERT INTO p2755_ref (id, target, note) VALUES (1, 10, 'a'), (2, 11, 'b'), (3, 12, 'c')",
            "INSERT INTO p2755_pk (target, tag) VALUES (10, 'x'), (11, 'x'), (11, 'y'), (20, 'x')",
            "INSERT INTO p2755_w (id, title, body) VALUES (1, 'now', 'now body')",
            "INSERT INTO p2755_wm (w_id, pos, txt) VALUES (1, 1, 'now 1')"):
    dbx(sql)

# --- 3. mg_repoint
r = in_app("""
from kalmido.core.merges import mg_repoint
a = mg_repoint(c, "p2755_ref", "target", [10, 11], 99)
b = mg_repoint(c, "p2755_pk", "target", [10, 11], 20)
out = {"a_moved": len(a["moved"]), "b_moved": len(b["moved"]), "b_dropped": len(b["dropped"])}
for k, args in {"tab": ("p2755_nope", "target"), "col": ("p2755_ref", "nope"), "inj": ("p2755_ref", "target=0; --")}.items():
    try:
        mg_repoint(c, args[0], args[1], [12], 98)
        out[k] = "none"
    except Exception as e:
        out[k] = type(e).__name__
c.commit()
print(json.dumps(out))
""")
check(r.get("a_moved") == 2, f"mg_repoint moves the rows: {r}")
check(r.get("b_moved") == 1 and r.get("b_dropped") == 2, f"mg_repoint drops the rows that collide on the primary key: {r}")
for k in ("tab", "col", "inj"):
    check(r.get(k) == "ValueError", f"mg_repoint refuses a name outside the schema ({k}): {r.get(k)} {r.get('_out', '')}")
check(sorted(x[0] for x in dbx("SELECT target FROM p2755_ref ORDER BY id")) == [12, 99, 99], "the refused calls moved nothing")
check(sorted((x[0], x[1]) for x in dbx("SELECT target, tag FROM p2755_pk")) == [(20, "x"), (20, "y")],
      "p2755_pk: (20,x) kept once, (20,y) moved in")

# --- 4. _write_back
r = in_app("""
from kalmido.core.writes import _write_back
sc = [("p2755_w", "id=?", [1], False), ("p2755_wm", "w_id=?", [1], True)]
snap = {"p2755_w": [{"id": 1, "title": "old", "body": "old body", "evil\\" = 1; --": "x"}],
        "p2755_wm": [{"w_id": 1, "pos": 1, "txt": "old 1"}, {"w_id": 1, "pos": 2, "txt": "old 2", "nocol": 5}]}
_write_back(c, sc, snap, 1)
c.commit()
out = {}
try:
    _write_back(c, [("p2755_gone", "id=?", [1], True)], {"p2755_gone": [{"id": 1, "title": "x"}]}, 1)
    out["gone"] = "none"
except Exception as e:
    out["gone"] = type(e).__name__
c.rollback()
print(json.dumps(out))
""")
check(r.get("gone") == "ValueError", f"_write_back refuses a table that is not in the schema: {r}")
check([tuple(x) for x in dbx("SELECT title, body FROM p2755_w WHERE id=1")] == [("old", "old body")],
      "_write_back writes the main row back (a key that is no column is left out)")
check([tuple(x) for x in dbx("SELECT pos, txt FROM p2755_wm WHERE w_id=1 ORDER BY pos")] == [(1, "old 1"), (2, "old 2")],
      "_write_back replaces the many rows")

# --- 5. obj_org_set: the allowlist of its table name (2.924.0, #5069: the member table and key column went)
r = in_app("from kalmido.accounts.orgs import obj_org_set\n"
           + refused("obj_org_set(c, 'users', 1, None, 'cal')") + "\nprint(json.dumps({'r': r}))")
check(r.get("r") == "ValueError", f"obj_org_set refuses a table outside ev_cals / books: {r}")

dbx("DROP TABLE IF EXISTS p2755_ref, p2755_pk, p2755_w, p2755_wm")
sys.exit(done("p2755_d_qi"))
