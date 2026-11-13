#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1095.0 (#5306) API tests: the old time columns created_at / updated_at / deleted_at as TIMESTAMPTZ (core/coltype.py).
Own container (start.sh). Invented names only.
   freelancer-matrix: lists
 - every column of core/coltype.py CT_TIME is timestamp with time zone in a new database
 - the answers keep their form: a project's updated_at is canonical ISO text (UTC, +00:00); the version check takes it
   (an old one = 409); the same for a person without an organisation
 - the migration on old values (in the container, rolled back): the three columns of tasks and ev_cals.updated_at turned back
   to TEXT with Z / no zone / '' / a value that is no time; ct_migrate turns them: the same moment, a time without a zone is
   UTC, '' in updated_at = the row's created_at, '' in deleted_at = NULL, a value that is no time = the start's time (the log
   names column and id); DEFAULT '' becomes CURRENT_TIMESTAMP; a second run changes nothing
 - the SQL that read them as text (regression): kern_version_seed of an old calendar (updated_at '' compared before), the purged
   list notes made in the canonical form, ct_day / ct_iso give the same for TEXT and TIMESTAMPTZ
usage: p21095_a_coltime_test.py <datadir>"""
import json
import os
import re
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import CT, FAILS, OKS, B, H, DATA, check, dbx, sess, until  # noqa: E402

CANON = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,6})?\+00:00$"  # a write answers with the time it wrote (iso_ms: milliseconds)

if not os.environ.get("P21095A_NOSTART"):
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
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})


def py(code):
    """Runs code in the container (the owner's direct connection c, as init_db has it, under system_ctx) -> (the JSON it prints
    on its last line, stderr)."""
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
from kalmido.core.coltype import CT_TIME
have = {(t, col): typ for t, col, typ in c.execute("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema()").fetchall()}
want = [(t, col) for col, ts in CT_TIME.items() for t in ts]
print(json.dumps({"n": len(want), "there": sum(1 for k in want if k in have), "other": sorted(f"{t}.{col}={have[(t, col)]}" for t, col in want if (t, col) in have and have[(t, col)] != 'timestamp with time zone')[:10]}))
""")
check(ty.get("n", 0) > 400 and ty.get("there", 0) > 350 and ty.get("other") == [],
      f"a new database: every created_at / updated_at / deleted_at of CT_TIME is TIMESTAMPTZ {ty}")


# ---- the answers keep their form, the version check works (an organisation's admin and a person without one)
def versions(s, who):
    r = s.post(B + "/api/lists", json={"name": f"{who} garden"})
    check(r.status_code in (200, 201), f"{who}: a project ({r.status_code} {r.text[:160]})")
    lid = r.json()["id"]
    r = s.patch(B + f"/api/lists/{lid}", json={"color": "#224466"})
    v0 = r.json().get("updated_at") if r.ok else None
    check(bool(v0) and re.match(CANON, v0), f"{who}: updated_at is canonical ISO text ({v0})")
    r = s.patch(B + f"/api/lists/{lid}", json={"color": "#224488", "expect_updated_at": v0})
    check(r.ok and r.json().get("updated_at") not in (None, ""), f"{who}: with the version read = changed ({r.status_code} {r.text[:160]})")
    r = s.patch(B + f"/api/lists/{lid}", json={"name": "Not this", "expect_updated_at": "2020-01-01T00:00:00+00:00"})
    check(r.status_code == 409, f"{who}: an old version = 409 ({r.status_code} {r.text[:160]})")
    made = dbx("SELECT created_at FROM lists WHERE id=?", (lid,))[0][0]
    check(re.match(CANON, made or ""), f"{who}: created_at reads as an ISO time ({made})")
    r = s.post(B + "/api/tasks", json={"title": f"{who} plant", "list_id": lid})
    check(r.status_code in (200, 201), f"{who}: a task ({r.status_code} {r.text[:160]})")
    tid = r.json()["id"]
    tm = dbx("SELECT created_at, updated_at, deleted_at FROM tasks WHERE id=?", (tid,))[0]
    check(re.match(CANON, tm[0] or "") and re.match(CANON, tm[1] or "") and tm[2] is None, f"{who}: a task's times {list(tm)}")
    return lid, tid


LA, TA = versions(A, "alice")
FRIDA, F = freelancer(B, A)
LF, TF = versions(F, "frida")
TX = A.post(B + "/api/tasks", json={"title": "third", "list_id": LA}).json()["id"]  # review 2.1095 (F11): the row with a bad value

# ---- the migration on old values (rolled back)
mig, err = py("""
from kalmido.core.coltype import ct_migrate
for col in ('created_at', 'updated_at', 'deleted_at'):
    c.execute(f"ALTER TABLE tasks ALTER COLUMN {col} TYPE TEXT USING to_char({col} AT TIME ZONE 'UTC', 'YYYY-MM-DD\\"T\\"HH24:MI:SS\\"+00:00\\"')")
c.execute("ALTER TABLE ev_cals ALTER COLUMN updated_at DROP DEFAULT, ALTER COLUMN updated_at TYPE TEXT USING updated_at::text, ALTER COLUMN updated_at SET DEFAULT ''")
out = {'old': [c.execute("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='tasks' AND column_name=?", (x,)).fetchone()[0] for x in ('created_at', 'updated_at')]}
c.execute("UPDATE tasks SET created_at='2026-03-01T10:00:00Z', updated_at='', deleted_at='' WHERE id=?", (%(ta)d,))
c.execute("UPDATE tasks SET created_at='2026-03-01 11:30:00', updated_at='2026-03-02T12:00:00+02:00', deleted_at=NULL WHERE id=?", (%(tf)d,))
c.execute("UPDATE tasks SET created_at='last tuesday' WHERE id=?", (%(tx)d,))
out['bad_id'] = %(tx)d
out['first'] = ct_migrate(c, '2026-11-13T08:00:00+00:00')
out['types'] = [c.execute("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? AND column_name=?", x).fetchone()[0] for x in (('tasks', 'created_at'), ('tasks', 'updated_at'), ('tasks', 'deleted_at'), ('ev_cals', 'updated_at'))]
out['a'] = list(c.execute("SELECT created_at, updated_at, deleted_at FROM tasks WHERE id=?", (%(ta)d,)).fetchone())
out['f'] = list(c.execute("SELECT created_at, updated_at, deleted_at FROM tasks WHERE id=?", (%(tf)d,)).fetchone())
out['bad'] = c.execute("SELECT created_at FROM tasks WHERE id=?", (out['bad_id'],)).fetchone()[0]
out['dflt'] = c.execute("SELECT column_default FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='ev_cals' AND column_name='updated_at'").fetchone()[0]
out['second'] = sorted(set(ct_migrate(c, '2026-11-13T09:00:00+00:00').values()))
c.rollback()
print(json.dumps(out))
""" % {"ta": TA, "tf": TF, "tx": TX})
first = mig.get("first") or {}
check(mig.get("old") == ["text", "text"], f"migration: the old state is TEXT {mig}")
check(first.get("tasks.created_at") == "done" and first.get("tasks.updated_at") == "done" and first.get("tasks.deleted_at") == "done"
      and first.get("ev_cals.updated_at") == "done", f"migration: the columns turn {dict((k, v) for k, v in first.items() if v != 'present')}")
check(mig.get("types") == ["timestamp with time zone"] * 4, f"migration: TIMESTAMPTZ after the turn {mig.get('types')}")
check(mig.get("a") == ["2026-03-01T10:00:00+00:00", "2026-03-01T10:00:00+00:00", None],
      f"migration: Z kept, updated_at '' = created_at, deleted_at '' = NULL {mig.get('a')}")
check(mig.get("f") == ["2026-03-01T11:30:00+00:00", "2026-03-02T10:00:00+00:00", None],
      f"migration: no zone = UTC, +02:00 = the same moment in UTC {mig.get('f')}")
check(mig.get("bad") == "2026-11-13T08:00:00+00:00", f"migration: a value that is no time = the start's time {mig.get('bad')}")
check("5306: tasks.created_at: 1 value(s) are no point in time" in err and str(mig.get("bad_id")) in err,
      f"migration: the log names the column and the id {err[-600:]}")
check("CURRENT_TIMESTAMP" in str(mig.get("dflt") or "").upper(), f"migration: DEFAULT '' becomes CURRENT_TIMESTAMP {mig.get('dflt')}")
check(set(mig.get("second") or ["?"]) <= {"present", "missing"}, f"migration: a second run changes nothing {mig.get('second')}")

# ---- the SQL that read the columns as text
reg, err = py("""
from kalmido.core.conflict import kern_version_seed
from kalmido.core.coltype import ct_day, ct_iso
out = {'before': c.execute("SELECT updated_at FROM lists WHERE id=?", (%(la)d,)).fetchone()[0]}
try:
    out['seed'] = kern_version_seed(c, 'lists', %(la)d)['updated_at']
except Exception as e:
    out['seed'] = type(e).__name__ + ': ' + str(e)[:120]
c.rollback()
ts, tx, te = "'2026-05-06T23:30:00+00:00'::timestamptz", "'2026-05-06T23:30:00+00:00'::text", "''::text"
out['day'] = list(c.execute("SELECT " + ct_day(ts) + ", " + ct_day(tx)).fetchone())
out['iso'] = list(c.execute("SELECT " + ct_iso(ts) + ", " + ct_iso("'2026-05-06T23:30:00Z'::text") + ", " + ct_iso(te) + ", "
                            + ct_iso("'2026-05-06T23:30:00.123+00:00'::timestamptz")).fetchone())
print(json.dumps(out))
""" % {"la": LA})
check(reg.get("seed") and reg.get("seed") == reg.get("before"), f"kern_version_seed on a TIMESTAMPTZ project (compared '' before) {reg} {err[-300:]}")
check(reg.get("day") == ["2026-05-06", "2026-05-06"], f"ct_day: the same day for TEXT and TIMESTAMPTZ {reg.get('day')}")
check(reg.get("iso") == ["2026-05-06T23:30:00+00:00", "2026-05-06T23:30:00+00:00", None, "2026-05-06T23:30:00.123+00:00"],
      f"ct_iso: the form of ts_canon (2.1112.2 #5986: shortest exact form, ms / us only when there are any), '' = NULL {reg.get('iso')}")

made = dbx("SELECT created_at FROM tasks WHERE id=?", (TF,))[0][0]
check(F.delete(B + f"/api/tasks/{TF}").ok, "frida: her task into the trash")
py(f"c.execute('DELETE FROM tasks WHERE id={int(TF)}')\nc.commit()\nprint('{{}}')")
pr = dbx("SELECT made FROM purged_rows WHERE tbl='tasks' AND ref_id=?", (TF,))
check(pr and pr[0][0] == made, f"purged_rows.made in the canonical form of created_at ({pr} / {made})")

print(f"p21095_a_coltime: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
