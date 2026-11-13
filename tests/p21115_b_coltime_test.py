#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1115.0 (#5951) part B: the time columns of office / receipts / books / time / documents onto TIMESTAMPTZ / DATE.
Own container (start.sh). Invented names only.
   freelancer-matrix: n/a (no route of its own; the areas' suites cover their routes)
 - a partial index whose condition compares the column with '' (doc_meta redo_at / learn_at had `WHERE x <> ''`) does not stop
   the turn of an existing database: core/coltype.py _ct_more drops it and creates it anew as `WHERE x IS NOT NULL`
   (scratch table, rolled back); without that Postgres refuses the TYPE (no operator timestamptz <> text) and the column stays TEXT
 - a new database: the two doc_meta indexes carry IS NOT NULL, the part B columns have their types
 - the import of old backups (admin/acctimport.py _coerce): a DATE column takes a day (of a point in time its day), '' and
   text that is no day stay out; a TIMESTAMPTZ column leaves '' out
usage: p21115_b_coltime_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import CT, FAILS, OKS, B, H, DATA, check, until  # noqa: E402

if not os.environ.get("P21115B_NOSTART"):
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


# ---- a new database: part B's columns and the doc_meta queue indexes
nd, _e = py("""
from kalmido.core.coltime import CT_B
have = {(t, col): typ for t, col, typ in c.execute("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema()").fetchall()}
want = {'ts': 'timestamp with time zone', 'date': 'date'}
idx = {n: d for n, d in c.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname=current_schema() AND indexname IN ('doc_meta_redo', 'ix4872_doc_meta_learn')").fetchall()}
print(json.dumps({"n": len(CT_B), "bad": sorted(f"{t}.{col}={have.get((t, col))}" for (t, col), k in CT_B.items() if have.get((t, col)) != want[k]), "idx": idx}))
""")
check(nd.get("n", 0) >= 50 and nd.get("bad") == [], f"a new database: every CT_B column has its type ({nd})")
idx = nd.get("idx") or {}
check(sorted(idx) == ["doc_meta_redo", "ix4872_doc_meta_learn"] and all("IS NOT NULL" in d and "''" not in d for d in idx.values()),
      f"a new database: the doc_meta queue indexes read IS NOT NULL {idx}")

# ---- the turn of an existing database with a partial index "WHERE x <> ''" (scratch table, rolled back)
mig, err = py("""
import kalmido.core.coltype as ct
c.execute("CREATE TABLE zz5951b (id BIGINT PRIMARY KEY, created_at TIMESTAMPTZ, r_at TEXT NOT NULL DEFAULT '', w_at TEXT)")
c.execute("CREATE INDEX zz5951b_r ON zz5951b(r_at) WHERE r_at <> ''")
c.execute("CREATE INDEX zz5951b_w ON zz5951b(id) WHERE w_at = '' AND id > 0")
c.execute("INSERT INTO zz5951b VALUES (1, '2026-03-01T10:00:00Z', '2026-03-02T12:00:00Z', ''), (2, '2026-03-01T10:00:00Z', '', '2026-03-03T08:00:00Z')")
ct.CT_MORE = {('zz5951b', 'r_at'): 'ts', ('zz5951b', 'w_at'): 'ts'}
ct.CT_MORE_TABLES = {'zz5951b'}
ct.CT_MORE_NAMES = {'r_at', 'w_at', 'created_at'}
out = {'first': ct._ct_more(c, '2026-11-13T08:00:00+00:00')}
out['types'] = {r[0]: r[1] for r in c.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='zz5951b'").fetchall()}
out['idx'] = {n: d for n, d in c.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname=current_schema() AND tablename='zz5951b'").fetchall()}
out['rows'] = [list(r) for r in c.execute("SELECT id, r_at, w_at FROM zz5951b ORDER BY id").fetchall()]
c.rollback()
print(json.dumps(out))
""")
check((mig.get("first") or {}) == {"zz5951b.r_at": "done", "zz5951b.w_at": "done"}, f"turn with a partial index on '': both columns turn {mig} {err[-400:]}")
check((mig.get("types") or {}).get("r_at") == "timestamp with time zone" and (mig.get("types") or {}).get("w_at") == "timestamp with time zone",
      f"turn with a partial index: the types {mig.get('types')}")
mi = mig.get("idx") or {}
check("IS NOT NULL" in (mi.get("zz5951b_r") or "") and "IS NULL" in (mi.get("zz5951b_w") or "") and "''" not in json.dumps(mi)
      and "id > 0" in (mi.get("zz5951b_w") or ""),
      f"turn with a partial index: the indexes come back, `<> ''` as IS NOT NULL, `= ''` as IS NULL, the rest kept {mi}")
check(mig.get("rows") == [[1, "2026-03-02T12:00:00+00:00", None], [2, None, "2026-03-03T08:00:00+00:00"]], f"turn: the values {mig.get('rows')}")

# ---- the import of an old backup: _coerce per type
co, _e = py("""
from kalmido.admin.acctimport import _coerce, _BAD
vals = ['2026-03-04', '2026-03-04T10:00:00+00:00', '', 'soon', None]
print(json.dumps({t: [None if (r := _coerce(v, t)) is None else ('BAD' if r is _BAD else r) for v in vals] for t in ('date', 'timestamp with time zone')}))
""")
check(co.get("date") == ["2026-03-04", "2026-03-04", "BAD", "BAD", None], f"import: a DATE column takes the day, '' / no day stay out {co}")
check(co.get("timestamp with time zone") == ["2026-03-04", "2026-03-04T10:00:00+00:00", "BAD", "BAD", None],
      f"import: a TIMESTAMPTZ column leaves '' out {co}")

print(f"p21115_b_coltime: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
