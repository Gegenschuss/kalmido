#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.644.0 (#4192): the daily clean-up of old logs (admin/dataretention.py lgc_tick) deletes in batches of LGC_BATCH rows,
each committed on its own, until none is left (here 2, so five old rows take three batches); the young rows stay. The log
tables without a time index get one (core/migrations.d/4192_a.py). A table that fails no longer leaves only a log line: the
instance admins get an alert of the kind "storage", and the other tables are still cleaned up. Invented data only.
usage: p2644_d_loeschen_test.py <datadir>"""
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


def old_rows(task):
    return dbx("SELECT COUNT(*) FROM activity WHERE task_id=? AND created_at<?", (task, ago(400)))[0][0]


# the indexes on the time columns that had none
have = {r[0] for r in dbx("SELECT indexname FROM pg_indexes WHERE indexname LIKE 'ix4192_%'")}
check(have == {"ix4192_list_activity_created", "ix4192_fs_log_at", "ix4192_org_list_log_created", "ix4192_sheet_changes_created"},
      f"the log tables have their time index: {sorted(have)}")

# ---- batches: five old rows with batches of two -> three DELETEs, each committed; the young row stays
T1 = A.post(B + "/api/tasks", json={"title": "Old history"}).json()["id"]
for _ in range(5):
    write("INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)", (T1, 1, "title", "{}", ago(500)))
write("INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)", (T1, 1, "title", '{"p2644": 1}', ago(1)))
check(old_rows(T1) == 5, "setup: five old rows")
RUN = ("import kalmido.admin.dataretention as d\nd.LGC_BATCH = 2\nsizes = []\n_del = d.lgc_del_batches\n"
       "def spy(c, table, where, args):\n    n = _del(c, table, where, args)\n    sizes.append((table, n, c.commits))\n    return n\n"
       "d.lgc_del_batches = spy\n")
out = box(RUN + "c0 = c.commits\nd.lgc_tick(c, True)\nprint('commits', c.commits - c0)\nprint('sizes', sizes)", ("KALMIDO_PURGE_LOGS=1",))
check(old_rows(T1) == 0, "the old rows are all gone " + out[-300:])
check(dbx("SELECT COUNT(*) FROM activity WHERE task_id=? AND data=?", (T1, '{"p2644": 1}'))[0][0] == 1, "the young row stays")
line = next((x for x in out.splitlines() if x.startswith("commits ")), "commits 0")
# without #4192 one DELETE inside one transaction: no batches, a single commit at the end
check(int(line.split()[1]) >= 4, f"three batches of the activity table each committed, plus the start and the end ({out[-300:]})")
check("('activity', 5," in out, "lgc_del_batches deleted the five rows of the activity table " + out[-300:])

# ---- the switch off: nothing goes, only counted
for _ in range(3):
    write("INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)", (T1, 1, "title", "{}", ago(500)))
out = box(RUN + "d.lgc_tick(c, True)")
check(old_rows(T1) == 3, "switch off: the old rows stay (dry run) " + out[-200:])

# ---- a failing table: the admins get an alert, the other tables are still cleaned up
out = box(RUN + "d.LGC_LOGS = ((\"p2644_no_such_log\", \"created_at\", \"\", None),) + d.LGC_LOGS\nd.lgc_tick(c, True)\n"
          "from kalmido.notify.alerts import _AA\nprint('queued', [(q[0], q[1], q[3]) for q in _AA['q']])",
          ("KALMIDO_PURGE_LOGS=1",))
# without #4192 only a log line: nothing in the queue the watchdog sends to the admins (notify/alerts.py aa_tick)
q = next((x for x in out.splitlines() if x.startswith("queued ")), "")
check("('storage', 'retention:p2644_no_such_log', ['p2644_no_such_log'," in q, "the failure is queued as an admin alert of the kind storage " + out[-300:])
check(old_rows(T1) == 0, "the next tables are cleaned up after the failure " + out[-200:])

sys.exit(kt.done("p2644_d_loeschen"))
