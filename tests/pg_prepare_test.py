"""pg_prepare_test.py -- 2.37.0 (#1150): every SQL statement written in the server code is PREPAREd against the real schema in
the test container's database (planned, type-checked, never run). Finds what the static guard pg_dialect cannot see because it
only looks at patterns: GROUP BY rules, comparisons of text with numbers, functions and operators that do not exist for the
types, ambiguous columns, ORDER BY with DISTINCT, unknown tables or columns.

- plain string literals that start with SELECT / INSERT / UPDATE / DELETE / WITH: every error fails, except a syntax error
  (a fragment that the code completes later, e.g. `sql = "SELECT ... WHERE"` + conditions) - those are counted only;
- f-strings: the {expressions} are replaced by stand-ins (IN ({x}) -> IN (?), a table name -> tasks, LIMIT {n} -> 1, else
  TRUE); only the errors that mean "Postgres is stricter than SQLite" fail (grouping, datatype mismatch, undefined function /
  operator, ambiguous column, invalid column reference), unknown columns / tables there come from the stand-ins.
Known exceptions are listed in EXCEPT with the reason.
Runs inside the test container (start.sh, a running app = the schema exists):  python3 tests/pg_prepare_test.py [datadir]
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, ".data")
CONTAINER = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")

CODE = r'''
import ast, os, re, sys
import psycopg
from kalmido.core.pg import translate
from kalmido.core.config import DATABASE_URL

ROOT = "/app/kalmido"
KW = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|WITH)\b", re.I)
FMT = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")  # a str.format() template: not SQL as it stands
STRICT = {"42803", "42804", "42883", "42702", "42P10", "42725", "42P18"}  # what Postgres refuses and SQLite took
# (file, a piece of the statement) -> why it may fail here
EXCEPT = {
    ("core/access.py", "SELECT id FROM dn"): "the tail of a recursive query whose WITH part is built in front of it",
    ("admin/migrate.py", "FROM sqlite_master"): "2.37 migrate-sqlite: runs against the old SQLite file, not Postgres",
    ("files/scan.py", "s.ver="): "2.61.0: ver={cur} is a number expression; the stand-in TRUE makes it bigint = boolean",
    ("files/scan.py", "AND ver="): "2.61.0: ver={cur} is a number expression; the stand-in TRUE makes it bigint = boolean",
    ("tasks/ftsearch.py", "ts_rank(TRUE, q)"): "2.139.1 (#2065): {TASK_VEC} / {CMT_VEC} is a tsvector expression; the stand-in TRUE makes it ts_rank(boolean, tsquery)",
    ("tasks/ftsearch.py", "SELECT id, TRUE FROM"): "2.281.0 C (#3113): {TASK_VEC} / {CMT_VEC} fill the tsvector column vec; the stand-in TRUE makes it boolean",
    ("admin/orgcrypt_cli.py", "AND TRUE LIKE ?"): "2.138.0 (#1972): {col} is a text column name; the stand-in TRUE makes it boolean LIKE text",
}

def excepted(rel, sql):
    return next((why for (f, piece), why in EXCEPT.items() if f == rel and piece in sql), None)

def fstr(n):
    out = []
    for v in n.values:
        out.append(v.value if isinstance(v, ast.Constant) else "\x00")
    s = "".join(out)
    s = re.sub(r"(IN\s*\()\x00", r"\1?", s, flags=re.I)
    s = re.sub(r"\b(table|FROM|UPDATE|INTO|JOIN)\s+\x00", r"\1 tasks", s, flags=re.I)
    s = re.sub(r"\b(LIMIT|OFFSET)\s+\x00", r"\1 1", s, flags=re.I)
    s = re.sub(r"\b(ORDER\s+BY)\s+\x00", r"\1 1", s, flags=re.I)
    return s.replace("\x00", "TRUE")

def numbered(sql):
    i = [0]
    def rep(m):
        i[0] += 1
        return f"${i[0]}"
    return re.sub(r"%t", rep, translate(sql)).replace("%%", "%")

conn = psycopg.connect(DATABASE_URL, autocommit=True)
fails, n_plain, n_f, n_frag, n_exc = [], 0, 0, 0, 0
k = 0
for dp, _, fns in os.walk(ROOT):
    for fn in sorted(fns):
        if not fn.endswith(".py"):
            continue
        p = os.path.join(dp, fn)
        rel = os.path.relpath(p, ROOT)
        tree = ast.parse(open(p, encoding="utf-8").read())
        inner = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in inner:
                s, is_f = n.value, False
            elif isinstance(n, ast.JoinedStr):
                s, is_f = fstr(n), True
            else:
                continue
            if not KW.match(s) or (not is_f and FMT.search(s)):
                continue
            k += 1
            if is_f:
                n_f += 1
            else:
                n_plain += 1
            try:
                with conn.transaction():
                    conn.execute(f"PREPARE pgp{k} AS {numbered(s)}", prepare=False)
                    conn.execute(f"DEALLOCATE pgp{k}", prepare=False)
            except psycopg.Error as e:
                state = e.sqlstate or ""
                msg = str(e).splitlines()[0] if str(e) else type(e).__name__
                if state == "42601" and not is_f:
                    n_frag += 1
                    continue
                if is_f and state not in STRICT:
                    continue
                why = excepted(rel, s)
                if why:
                    n_exc += 1
                    continue
                fails.append(f"{rel}:{n.lineno}: [{state}] {msg}")
for f in fails:
    print("FAIL " + f)
print(f"pg_prepare: {n_plain} plain statements ({n_frag} fragments not checkable), {n_f} f-strings, {n_exc} known exceptions, "
      f"{len(fails)} failed")
check_min = n_plain > 300 and n_f > 100
if not check_min:
    print(f"FAIL too few statements found ({n_plain} / {n_f}): is the server code at {ROOT}?")
raise SystemExit(1 if fails or not check_min else 0)
'''

p = subprocess.run(["docker", "exec", "-i", "-w", "/app", CONTAINER, "python", "-"], input=CODE, capture_output=True, text=True,
                   timeout=300)
print(p.stdout + p.stderr)
sys.exit(p.returncode)
