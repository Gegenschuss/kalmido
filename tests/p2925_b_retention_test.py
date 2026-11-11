#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.925.0 part B: the clean-up of the activity table. Invented data only.
 - (#5055) the daily clean-up of the activity table reads the history rows to spare for the customer portal ONCE per run
   (a temp table) and every batch DELETE only looks them up there - no batch groups the whole portal history again. The
   oldest edit of the description of a portal ticket still stays, the other old rows go; the temp table is gone after.
usage: p2925_b_retention_test.py <datadir>"""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, dbx  # noqa: E402
import dbx as dbxm  # noqa: E402

kt.fresh()
A = kt.setup()


def write(q, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"))
    c.execute(q, args)
    c.commit()
    c.close()


def box(code, env=()):
    """Python inside the app container (the watchdog calls lgc_tick directly)."""
    cmd = ["docker", "exec"]
    for e in env:
        cmd += ["-e", e]
    out = subprocess.run(cmd + [CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.commit()\nc.close()"],
                         capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


# ============================================================== #5055: the portal rows to spare, read once per run
L = A.post(B + "/api/lists", json={"name": "Portal 5055"}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"title": "Ticket 5055", "list_id": L}).json()["id"]
write("INSERT INTO portal_tickets(task_id, list_id, token, token_hash, created_at) VALUES(?,?,?,?,?)", (T1, L, "x", "p2925b-" + str(T1), ago(600)))
for i, kind in enumerate(("content", "title", "content", "title", "title", "title")):
    write("INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)", (T1, 1, kind, '{"p5055": %d}' % i, ago(500 - i)))
first = dbx("SELECT min(id) FROM activity WHERE task_id=? AND kind='content'", (T1,))[0][0]
SPY = ("import kalmido.admin.dataretention as d\nd.LGC_BATCH = 2\nstm = []\n_ex = c.execute\n"
       "def spy(q, args=None):\n    stm.append(q)\n    return _ex(q, args)\n"
       "c.execute = spy\n")
out = box(SPY + "d.lgc_tick(c, True)\n"
          "dels = [q for q in stm if q.startswith('DELETE FROM activity ')]\n"
          "print('deletes', len(dels), 'grouped', sum('GROUP BY' in q for q in dels), 'keep', sum('lgc_portal_keep_ids' in q for q in dels))\n"
          "print('made', sum(q.startswith('CREATE TEMP TABLE') and 'lgc_portal_keep_ids' in q for q in stm))\n"
          "print('left', c.execute(\"SELECT to_regclass('pg_temp.lgc_portal_keep_ids')\").fetchone()[0])",
          ("KALMIDO_PURGE_LOGS=1",))
left = dbx("SELECT id, kind FROM activity WHERE task_id=? AND created_at<?", (T1, ago(400)))
check([r[0] for r in left] == [first], f"(#5055) only the oldest edit of the description of the portal ticket stays {left} " + out[-300:])
line = next((x for x in out.splitlines() if x.startswith("deletes ")), "deletes 0 grouped 9 keep 0").split()
# without #5055 every batch DELETE carried the grouping over the whole portal history (id NOT IN (SELECT min(a.id) ... GROUP BY))
check(int(line[1]) >= 3 and line[3] == "0" and line[5] == line[1],
      f"(#5055) {line[1]} batches of activity, none groups the portal history again, each looks the kept ids up " + out[-300:])
check("made 1" in out, "(#5055) the ids to spare are read once per run " + out[-300:])
check("left None" in out, "(#5055) the temp table is gone after the run (the connection goes back to the pool) " + out[-300:])

sys.exit(kt.done("p2925_b_retention"))
