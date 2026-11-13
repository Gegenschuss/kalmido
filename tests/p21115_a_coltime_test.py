#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1115.0 (#5951) API tests: the other old time columns (*_at / *_on / *_until) onto TIMESTAMPTZ / DATE (core/coltime.py
CT_MORE, turned by core/coltype.py _ct_more at the start). Own container (start.sh). Invented names only.
   freelancer-matrix: n/a (no route of its own; the areas' suites cover their routes)
 - every column of CT_MORE has its type in a new database (TIMESTAMPTZ for "ts", DATE for "date")
 - the turn on old values (a scratch table in the container, rolled back): ISO text with / without a zone = that moment (no
   zone = UTC), '' = NULL in a nullable column and in a NOT NULL DEFAULT '' column (which becomes nullable, its default goes),
   a NOT NULL column without default takes the row's created_at; a value that is no time is set all the same and takes the
   row's created_at (a day column its day) in every column, never NULL (review #5951); a day column = DATE (a whole point in
   time keeps its day); the log names column and id; a second run changes nothing
 - an ALTER that fails (a view on the column): the column stays TEXT, but its DEFAULT '' and NOT NULL go and '' becomes NULL,
   so an INSERT with None works (review #5951, M4); a CT_CLOSED "all" mark keeps its ''
 - a DATE reads back as 'YYYY-MM-DD' text (core/pg.py _DateLoader), a TIMESTAMPTZ as canonical ISO text
usage: p21115_a_coltime_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import CT, FAILS, OKS, B, H, DATA, check, until  # noqa: E402

if not os.environ.get("P21115A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)


def _up():
    try:
        return s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"})
    except requests.ConnectionError:
        return None


r = until(_up, 30)  # the server is up once setup answers (a real state, not a fixed time)
assert r is not None and r.ok, r and r.text


def py(code):
    """Runs code in the container (the owner's direct connection c under system_ctx) -> (the JSON of its last line, stderr)."""
    src = ("import app, json, sys\nfrom kalmido.core.config import DATABASE_URL\nfrom kalmido.core.db import connect_direct\n"
           "from kalmido.core.pg import system_ctx\nc = connect_direct(DATABASE_URL)\n"
           "with system_ctx(c):\n" + "".join("    " + x + "\n" for x in code.strip().splitlines()) + "c.close()\n")
    out = subprocess.run(["docker", "exec", CT, "python", "-c", src], capture_output=True, text=True)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1]), out.stderr
    except (ValueError, IndexError):
        return {"_error": out.stdout[-400:] + out.stderr[-800:]}, out.stderr


# ---- the column types of a new database
ty, _e = py("""
from kalmido.core.coltime import CT_MORE
have = {(t, col): typ for t, col, typ in c.execute("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema()").fetchall()}
want = {'ts': 'timestamp with time zone', 'date': 'date'}
print(json.dumps({"n": len(CT_MORE), "missing": sorted(f"{t}.{col}" for (t, col) in CT_MORE if (t, col) not in have)[:10], "other": sorted(f"{t}.{col}={have[(t, col)]}" for (t, col), k in CT_MORE.items() if (t, col) in have and have[(t, col)] != want[k])[:10]}))
""")
check(ty.get("missing") == [] and ty.get("other") == [], f"a new database: every CT_MORE column has its type ({ty})")

# ---- the turn on old values (a scratch table, rolled back)
mig, err = py("""
import kalmido.core.coltype as ct
c.execute("CREATE TABLE zz5951 (id BIGINT PRIMARY KEY, created_at TIMESTAMPTZ, a_at TEXT, b_at TEXT NOT NULL DEFAULT '', c_at TEXT NOT NULL, d_on TEXT, e_until TEXT NOT NULL DEFAULT '')")
c.execute("INSERT INTO zz5951 VALUES (1, '2026-03-01T10:00:00Z', '2026-03-02T12:00:00+02:00', '', '2026-03-03 08:00:00', '2026-03-04', '2026-03-05T23:30:00Z')")
c.execute("INSERT INTO zz5951 VALUES (2, '2026-03-01T10:00:00Z', '', '2026-03-06T07:00:00', '', '', 'soon')")
c.execute("INSERT INTO zz5951 VALUES (3, '2026-03-01T10:00:00Z', 'last tuesday', '2026-03-06T07:00:00.250Z', 'never', NULL, '')")
ct.CT_MORE = {('zz5951', 'a_at'): 'ts', ('zz5951', 'b_at'): 'ts', ('zz5951', 'c_at'): 'ts', ('zz5951', 'd_on'): 'date', ('zz5951', 'e_until'): 'date'}
ct.CT_MORE_TABLES = {'zz5951'}
ct.CT_MORE_NAMES = {'a_at', 'b_at', 'c_at', 'd_on', 'e_until', 'created_at'}
out = {'first': ct._ct_more(c, '2026-11-13T08:00:00+00:00')}
cols = c.execute("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='zz5951' ORDER BY column_name").fetchall()
out['cols'] = {r[0]: [r[1], r[2], r[3]] for r in cols}
out['rows'] = [list(r) for r in c.execute("SELECT id, a_at, b_at, c_at, d_on, e_until FROM zz5951 ORDER BY id").fetchall()]
out['second'] = sorted(set(ct._ct_more(c, '2026-11-13T09:00:00+00:00').values()))
out['day'] = c.execute("SELECT DATE '2026-07-08'").fetchone()[0]
c.rollback()
print(json.dumps(out))
""")
first = mig.get("first") or {}
check(first and set(first.values()) == {"done"}, f"turn: every column turns {mig}")
cols = mig.get("cols") or {}
check([cols.get(k, [None])[0] for k in ("a_at", "b_at", "c_at", "d_on", "e_until")]
      == ["timestamp with time zone"] * 3 + ["date"] * 2, f"turn: the types {cols}")
check(cols.get("b_at", [0, 0])[1:] == ["YES", None] and cols.get("e_until", [0, 0])[1:] == ["YES", None],
      f"turn: a NOT NULL DEFAULT '' column becomes nullable, its default goes {cols}")
check(cols.get("c_at", [0, 0])[1] == "NO", f"turn: a NOT NULL column without default stays NOT NULL {cols.get('c_at')}")
rows = mig.get("rows") or []
check(rows[:1] == [[1, "2026-03-02T10:00:00+00:00", None, "2026-03-03T08:00:00+00:00", "2026-03-04", "2026-03-05"]],
      f"turn: a zone kept as the moment, no zone = UTC, '' = NULL, a day = DATE, a point in time keeps its day {rows[:1]}")
# 2.1115.0 (#5951): review - a text that is no day / no time stays set (the row's created_at), never NULL (was NULL)
check(rows[1:2] == [[2, None, "2026-03-06T07:00:00+00:00", "2026-03-01T10:00:00+00:00", None, "2026-03-01"]],
      f"turn: '' in a NOT NULL column without default = the row's created_at, a text that is no day = its day {rows[1:2]}")
# 2.1115.0 (#5951): review - 'last tuesday' in a nullable column = created_at (was NULL)
check(rows[2:3] == [[3, "2026-03-01T10:00:00+00:00", "2026-03-06T07:00:00.25+00:00", "2026-03-01T10:00:00+00:00", None, None]]
      or rows[2:3] == [[3, "2026-03-01T10:00:00+00:00", "2026-03-06T07:00:00.250000+00:00", "2026-03-01T10:00:00+00:00", None, None]]
      # 2.1115.0 (#5951): since #5986 (main) ts_canon keeps milliseconds as written (.250)
      or rows[2:3] == [[3, "2026-03-01T10:00:00+00:00", "2026-03-06T07:00:00.250+00:00", "2026-03-01T10:00:00+00:00", None, None]],
      f"turn: a value that is no time = created_at in every column, milliseconds kept {rows[2:3]}")
check("5951: zz5951.a_at: 1 value(s) are no point in time" in err and "5951: zz5951.e_until: 1 value(s) are no day" in err,
      f"turn: the log names the columns {err[-600:]}")
check(set(mig.get("second") or ["?"]) <= {"present", "missing"}, f"turn: a second run changes nothing {mig.get('second')}")
check(mig.get("day") == "2026-07-08", f"a DATE reads back as 'YYYY-MM-DD' text {mig.get('day')!r}")

# ---- review (#5951, M4): the ALTER fails (a view on the column), the column stays TEXT but takes None (rolled back)
kept, err = py("""
import kalmido.core.coltype as ct
c.execute("CREATE TABLE zz5951k (id BIGINT PRIMARY KEY, created_at TIMESTAMPTZ, f_at TEXT NOT NULL DEFAULT '', g_at TEXT, h_at TEXT NOT NULL DEFAULT '')")
c.execute("INSERT INTO zz5951k VALUES (1, '2026-03-01T10:00:00Z', '', '', ''), (2, '2026-03-01T10:00:00Z', '2026-03-02T10:00:00Z', 'x', '2026-03-02T10:00:00Z')")
c.execute("CREATE VIEW zz5951kv AS SELECT f_at, g_at, h_at FROM zz5951k")
ct.CT_MORE = {('zz5951k', 'f_at'): 'ts', ('zz5951k', 'g_at'): 'ts', ('zz5951k', 'h_at'): 'ts'}
ct.CT_MORE_TABLES = {'zz5951k'}
ct.CT_MORE_NAMES = {'f_at', 'g_at', 'h_at', 'created_at'}
ct.CT_CLOSED = {('zz5951k', 'h_at'): 'all'}
out = {'first': ct._ct_more(c, '2026-11-13T08:00:00+00:00')}
out['cols'] = {r[0]: [r[1], r[2], r[3]] for r in c.execute("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='zz5951k' AND column_name LIKE '%_at' AND column_name <> 'created_at'").fetchall()}
out['rows'] = [list(r) for r in c.execute("SELECT id, f_at, g_at, h_at FROM zz5951k ORDER BY id").fetchall()]
try:
    with c.savepoint():
        c.execute("INSERT INTO zz5951k(id, created_at, f_at, g_at, h_at) VALUES (3, now(), NULL, NULL, NULL)")
    out['insert'] = 'ok'
except Exception as e:
    out['insert'] = type(e).__name__
out['isnull'] = c.execute("SELECT COUNT(*) FROM zz5951k WHERE f_at IS NULL").fetchone()[0]
c.rollback()
print(json.dumps(out))
""")
check(kept.get("first") == {"zz5951k.f_at": "kept", "zz5951k.g_at": "kept", "zz5951k.h_at": "kept"},
      f"kept: a view on the columns fails the ALTER, they stay TEXT {kept}")
kc = kept.get("cols") or {}
check(kc.get("f_at") == ["text", "YES", None] and kc.get("h_at") == ["text", "YES", None] and kc.get("g_at") == ["text", "YES", None],
      f"kept: DEFAULT '' and NOT NULL go even so {kc}")
check(kept.get("rows") == [[1, None, None, ""], [2, "2026-03-02T10:00:00Z", "x", "2026-03-02T10:00:00Z"]],
      f"kept: '' becomes NULL (not in an 'all' mark), other values stay {kept.get('rows')}")
check(kept.get("insert") == "ok" and kept.get("isnull") == 2, f"kept: an INSERT with None works, IS NULL finds the empty ones {kept}")
check("5951: zz5951k.f_at stays TEXT" in err, f"kept: the log says why {err[-400:]}")

print(f"p21115_a_coltime: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
