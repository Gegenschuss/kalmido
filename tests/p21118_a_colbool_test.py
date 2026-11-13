#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1118.0 (#5952) API tests: the old yes / no columns (BIGINT / INTEGER 0/1) onto BOOLEAN (core/colbool.py CB_BOOL, turned by
cb_migrate at the start), read back as 0 / 1 (core/pg.py). Own container (start.sh). Invented names only.
   freelancer-matrix: n/a (no route of its own; the areas' suites cover their routes)
 - every column of CB_BOOL is BOOLEAN in a new database, with its default (false / true)
 - the turn on old values (a scratch table in the container, rolled back): 0 = false, 1 = true, another number = true and the
   log names it; the default stays (0 -> false, 1 -> true); a partial index `WHERE en = 1` is made anew as `WHERE en`; a second
   run changes nothing
 - reading: a CB_BOOL column comes back as the number 0 / 1 (Python and the JSON of the answers), a BOOLEAN of another table
   and a computed one as True / False; a `?` parameter 0 / 1 / True / False writes the column
 - the list state trigger (migrations.d/5537_a.py) works on the BOOLEAN lists.archived both ways
usage: p21118_a_colbool_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import CT, FAILS, OKS, B, H, DATA, check, until  # noqa: E402

if not os.environ.get("P21118A_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
A = requests.Session()
A.headers.update(H)


def _up():
    try:
        return A.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"})
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
from kalmido.core.colbool import CB_BOOL
have = {(t, col): (typ, d) for t, col, typ, d in c.execute("SELECT table_name, column_name, data_type, column_default FROM information_schema.columns WHERE table_schema=current_schema()").fetchall()}
pairs = [(t, col) for t, cs in CB_BOOL.items() for col in cs]
print(json.dumps({"n": len(pairs), "missing": sorted(f"{t}.{col}" for t, col in pairs if (t, col) not in have)[:10],
                  "other": sorted(f"{t}.{col}={have[(t, col)][0]}" for t, col in pairs if (t, col) in have and have[(t, col)][0] != 'boolean')[:10],
                  "dflt": {f"{t}.{col}": have[(t, col)][1] for t, col in (('lists', 'archived'), ('webhooks', 'enabled')) if (t, col) in have}}))
""")
check(ty.get("n") == 53 and ty.get("missing") == [] and ty.get("other") == [], f"a new database: every CB_BOOL column is BOOLEAN ({ty})")
check(ty.get("dflt") == {"lists.archived": "false", "webhooks.enabled": "true"}, f"a new database: the defaults false / true {ty.get('dflt')}")

# ---- the turn on old values (a scratch table, rolled back)
mig, err = py("""
import kalmido.core.colbool as cb
c.execute("CREATE TABLE zz5952 (id BIGINT PRIMARY KEY, org_id BIGINT, en BIGINT NOT NULL DEFAULT 1, ar INTEGER NOT NULL DEFAULT 0, other BIGINT NOT NULL DEFAULT 0)")
c.execute("CREATE INDEX zz5952_on ON zz5952(org_id) WHERE en = 1")
c.execute("CREATE UNIQUE INDEX zz5952_one ON zz5952(org_id) WHERE ar = 0 AND other = 0")
c.execute("INSERT INTO zz5952 VALUES (1, 1, 1, 0, 0), (2, 2, 0, 1, 1), (3, 3, 2, 0, 0)")
cb.CB_BOOL = {'zz5952': ('en', 'ar')}
cb.CB_NAMES = {'en', 'ar'}
out = {'first': cb._cb_run(c, '2026-11-13T08:00:00+00:00')}
cols = c.execute("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='zz5952' ORDER BY column_name").fetchall()
out['cols'] = {r[0]: [r[1], r[2], r[3]] for r in cols}
out['rows'] = [[r[0], r[1], r[2]] for r in c.execute("SELECT id, en::text, ar::text FROM zz5952 ORDER BY id").fetchall()]
out['idx'] = {r[0]: r[1].split(' WHERE ', 1)[1] for r in c.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='zz5952' AND indexdef LIKE '%WHERE%'").fetchall()}
c.execute("INSERT INTO zz5952(id, org_id) VALUES (4, 4)")
out['new'] = [r[0] for r in c.execute("SELECT en::text || '/' || ar::text FROM zz5952 WHERE id=4").fetchall()]
out['second'] = sorted(set(cb._cb_run(c, '2026-11-13T09:00:00+00:00').values()))
c.rollback()
print(json.dumps(out))
""")
first = mig.get("first") or {}
check(first == {"zz5952.en": "done", "zz5952.ar": "done"}, f"turn: both columns turn {mig}")
cols = mig.get("cols") or {}
check(cols.get("en") == ["boolean", "NO", "true"] and cols.get("ar") == ["boolean", "NO", "false"] and (cols.get("other") or [""])[0] == "bigint",
      f"turn: BOOLEAN NOT NULL, the default kept as true / false, a column not in the list untouched {cols}")
check(mig.get("rows") == [[1, "true", "false"], [2, "false", "true"], [3, "true", "false"]], f"turn: 0 = false, 1 = true, 2 = true {mig.get('rows')}")
idx = mig.get("idx") or {}
check(idx.get("zz5952_on") == "en" and idx.get("zz5952_one") == "((NOT ar) AND (other = 0))",
      f"turn: the partial indexes made anew with the condition in the new type {idx}")
check(mig.get("new") == ["true/false"], f"turn: a new row takes the defaults {mig.get('new')}")
check("5952: zz5952.en: 1 value(s) are neither 0 nor 1" in err, f"turn: the log names the column with a value 2 {err[-600:]}")
check(mig.get("second") == ["present"], f"turn: a second run changes nothing {mig.get('second')}")

# ---- reading 0 / 1, writing with parameters
rd, _e = py("""
uid = c.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
r = c.execute("SELECT is_admin, disabled, u.disabled AS d2 FROM users u WHERE id=?", (uid,)).fetchone()
out = {'admin': [r[0], type(r[0]).__name__], 'disabled': [r[1], type(r[1]).__name__], 'alias': type(r[2]).__name__}
out['expr'] = [type(x).__name__ for x in c.execute("SELECT is_admin OR false, EXISTS (SELECT 1), NOT disabled FROM users WHERE id=?", (uid,)).fetchone()]
c.execute("CREATE TEMP TABLE zz5952b (archived BOOLEAN NOT NULL DEFAULT true)")
c.execute("INSERT INTO zz5952b DEFAULT VALUES")
out['other'] = type(c.execute("SELECT archived FROM zz5952b").fetchone()[0]).__name__
lid = c.execute("SELECT id FROM lists WHERE owner_id=? AND is_inbox", (uid,)).fetchone()[0]
c.execute("UPDATE lists SET archived=? WHERE id=?", (True, lid))
a1 = c.execute("SELECT archived, state FROM lists WHERE id=?", (lid,)).fetchone()
c.execute("UPDATE lists SET archived=? WHERE id=?", (0, lid))
a2 = c.execute("SELECT archived, state FROM lists WHERE id=?", (lid,)).fetchone()
c.execute("UPDATE lists SET state='archived' WHERE id=?", (lid,))
a3 = c.execute("SELECT archived, state FROM lists WHERE id=?", (lid,)).fetchone()
c.execute("UPDATE lists SET state='live' WHERE id=?", (lid,))
a4 = c.execute("SELECT archived, state FROM lists WHERE id=?", (lid,)).fetchone()
out['lists'] = [list(a1), list(a2), list(a3), list(a4)]
c.rollback()
print(json.dumps(out))
""")
check(rd.get("admin") == [1, "int"] and rd.get("disabled") == [0, "int"] and rd.get("alias") == "int",
      f"read: users.is_admin / disabled come back as the numbers 1 / 0, also under an alias {rd}")
check(rd.get("expr") == ["bool", "bool", "bool"] and rd.get("other") == "bool",
      f"read: a computed boolean and a BOOLEAN outside the list stay True / False {rd.get('expr')} {rd.get('other')}")
check(rd.get("lists") == [[1, "archived"], [0, "live"], [1, "archived"], [0, "live"]],
      f"write: a parameter True / 0 sets archived, the state trigger follows; state written = archived follows {rd.get('lists')}")

st = A.get(B + "/api/state").json()
inbox = [x for x in st.get("lists", []) if x.get("is_inbox")]
check(len(inbox) == 1 and inbox[0]["is_inbox"] == 1 and inbox[0]["is_inbox"] is not True,
      f"answer: /api/state gives is_inbox as the number 1, not true {[{k: x.get(k) for k in ('id', 'is_inbox')} for x in inbox]}")
L = A.post(B + "/api/lists", json={"name": "Garden"}).json()["id"]
got = [x for x in A.get(B + "/api/state").json().get("lists", []) if x.get("id") == L]
check(got and got[0].get("is_inbox") == 0 and got[0].get("is_inbox") is not False, f"answer: a new project has is_inbox 0 {got[:1]}")

print(f"p21118_a_colbool: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
