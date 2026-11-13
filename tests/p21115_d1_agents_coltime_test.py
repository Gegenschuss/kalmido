#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1115.0 (#5951) part D1: the time columns of the agents and the machinery (agent_*, agents, bg_jobs, notifications,
newsletters, feeds, scans, kalmido_migrations, ...) onto TIMESTAMPTZ (core/coltime.py CT_D1). Own container (start.sh).
Invented names only.
   freelancer-matrix: n/a (no route of its own; the areas' suites cover their routes)
 - a new database: every CT_D1 column is TIMESTAMPTZ; agents.status_key_at stays TEXT (coltype-ok: the agent's own text,
   echoed as it sent it)
 - an older database (the columns as TEXT again, inside a rolled back transaction): kalmido_migrations.applied_at with
   DEFAULT '' turns, its rows keep their moment, '' = NULL, the column becomes nullable; mail_in_seen.seen_at (NOT NULL, no
   created_at) takes the start's time for ''; the start's own bookkeeping (mig_flags_sync / mig_apply) writes into the turned
   column afterwards
 - the reading watchdog (life/karakeep.py _wd_reading) sorts kk_conns by synced_at on TIMESTAMPTZ (was COALESCE(x, ''):
   an error on TIMESTAMPTZ), never synced first
usage: p21115_d1_agents_coltime_test.py <datadir>"""
import json
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import CT, FAILS, OKS, B, H, DATA, check, until  # noqa: E402

if not os.environ.get("P21115D1_NOSTART"):
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


# ---- a new database
ty, _e = py("""
from kalmido.core.coltime import CT_D1
have = {(t, col): typ for t, col, typ in c.execute("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema()").fetchall()}
print(json.dumps({"n": len(CT_D1), "kinds": sorted(set(CT_D1.values())), "other": sorted(f"{t}.{col}={have.get((t, col))}" for (t, col) in CT_D1 if have.get((t, col)) != 'timestamp with time zone'), "key_at": have.get(('agents', 'status_key_at'))}))
""")
check(ty.get("n") == 40 and ty.get("kinds") == ["ts"] and ty.get("other") == [], f"a new database: the 40 D1 columns are TIMESTAMPTZ ({ty})")
check(ty.get("key_at") == "text", f"agents.status_key_at stays TEXT (the agent's own text, coltype-ok) ({ty.get('key_at')})")

# ---- an older database: the columns as TEXT again (rolled back), then the start's turn
old, err = py("""
import kalmido.core.coltype as ct
import kalmido.core.db as d
c.execute("ALTER TABLE kalmido_migrations ALTER COLUMN applied_at TYPE TEXT USING to_char(applied_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\\"T\\"HH24:MI:SS\\"+00:00\\"'), ALTER COLUMN applied_at SET DEFAULT '', ALTER COLUMN applied_at SET NOT NULL")
c.execute("ALTER TABLE mail_in_seen ALTER COLUMN seen_at TYPE TEXT USING CAST(seen_at AS text)")
c.execute("INSERT INTO kalmido_migrations(id, applied_at, note) VALUES ('zz5951.a', '2026-03-02T12:00:00+02:00', 'applied'), ('zz5951.b', '', 'present'), ('zz5951.c', 'yesterday', 'present')")
c.execute("INSERT INTO mail_in_seen(box, mid, seen_at) VALUES ('zz5951', 'm1', '2026-03-04T08:00:00+00:00'), ('zz5951', 'm2', '')")
out = {"turn": {k: v for k, v in ct._ct_more(c, '2026-11-13T08:00:00+00:00').items() if k in ('kalmido_migrations.applied_at', 'mail_in_seen.seen_at')}}
out["cols"] = {f"{r[0]}.{r[1]}": [r[2], r[3], r[4]] for r in c.execute("SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema=current_schema() AND (table_name, column_name) IN (('kalmido_migrations', 'applied_at'), ('mail_in_seen', 'seen_at'))").fetchall()}
out["migs"] = [list(r) for r in c.execute("SELECT id, applied_at FROM kalmido_migrations WHERE id LIKE 'zz5951%' ORDER BY id").fetchall()]
out["seen"] = [list(r) for r in c.execute("SELECT mid, seen_at FROM mail_in_seen WHERE box='zz5951' ORDER BY mid").fetchall()]
out["typed"] = c.execute("SELECT COUNT(*) FROM kalmido_migrations WHERE id='type:kalmido_migrations.applied_at' AND applied_at IS NOT NULL").fetchone()[0]
c.execute("INSERT INTO settings(key, value) VALUES ('migr_zz5951', '1') ON CONFLICT (key) DO UPDATE SET value='1'")
d.mig_flags_sync(c)
d.mig_apply(c)
out["flag"] = c.execute("SELECT applied_at FROM kalmido_migrations WHERE id='flag:migr_zz5951'").fetchone()[0]
out["again"] = sorted(set(v for k, v in ct._ct_more(c, '2026-11-13T09:00:00+00:00').items() if k in ('kalmido_migrations.applied_at', 'mail_in_seen.seen_at')))
c.rollback()
print(json.dumps(out))
""")
check(old.get("turn") == {"kalmido_migrations.applied_at": "done", "mail_in_seen.seen_at": "done"}, f"older database: both columns turn {old}")
cols = old.get("cols") or {}
check(cols.get("kalmido_migrations.applied_at") == ["timestamp with time zone", "YES", None],
      f"kalmido_migrations.applied_at: TIMESTAMPTZ, nullable, the DEFAULT '' gone {cols}")
check(cols.get("mail_in_seen.seen_at") == ["timestamp with time zone", "NO", None], f"mail_in_seen.seen_at stays NOT NULL {cols}")
# 2.1115.0 (#5951): review (M3) - a text that is no time stays "set": the start's time (kalmido_migrations has no created_at)
check(old.get("migs") == [["zz5951.a", "2026-03-02T10:00:00+00:00"], ["zz5951.b", None], ["zz5951.c", "2026-11-13T08:00:00+00:00"]],
      f"the recorded steps keep their moment, '' = NULL, a text that is no time = the start's time {old.get('migs')}")
check(old.get("seen") == [["m1", "2026-03-04T08:00:00+00:00"], ["m2", "2026-11-13T08:00:00+00:00"]],
      f"mail_in_seen: '' in a NOT NULL column without created_at = the start's time {old.get('seen')}")
check(old.get("typed") == 1, f"the turn is recorded in the turned table itself ({old.get('typed')})")
check(bool(old.get("flag")) and old["flag"].endswith("+00:00"), f"the start's bookkeeping writes into the turned column ({old.get('flag')})")
check(set(old.get("again") or ["?"]) == {"present"}, f"a second turn changes nothing ({old.get('again')})")
check("kalmido_migrations.applied_at: 1 value(s) are no point in time" in err, f"the log names the misfit ({err[-400:]})")

# ---- the reading watchdog sorts kk_conns on TIMESTAMPTZ (2.1115.0, #5951: was ORDER BY COALESCE(synced_at, ''))
kk, err = py("""
from kalmido.life import karakeep as kk
uid = c.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
c.execute("DELETE FROM kk_conns WHERE user_id=?", (uid,))
c.execute("INSERT INTO kk_conns(user_id, url, created_at) VALUES(?, ?, ?)", (uid, "https://bookmarks.example.com", "2026-11-01T08:00:00+00:00"))
ok = True
try:
    kk._wd_reading(c, set(), {}, {}, None)
except Exception as e:
    ok = type(e).__name__ + ": " + str(e)[:200]
first = c.execute("SELECT synced_at FROM kk_conns ORDER BY synced_at NULLS FIRST LIMIT 1").fetchone()[0]
c.rollback()
print(json.dumps({"ok": ok, "first": first}))
""")
check(kk.get("ok") is True, f"the reading watchdog runs on TIMESTAMPTZ synced_at ({kk})")
check("first" in kk and kk["first"] is None, f"never synced first ({kk.get('first')})")

print(f"p21115_d1_agents_coltime: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
