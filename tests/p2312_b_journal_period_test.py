#!/usr/bin/env python3
"""2.312.0 B (#3264): the journal of deleted accounts (deleted_accounts) has a period: the daily log clean-up (kind "logs")
removes a row once no backup can hold the account any more -- older than the longest backup period (104 weeks) and older
than every backup still in the backup folder. Invented accounts only (example.com).
freelancer-matrix: admin (the journal is the instance's; a person without an organisation is noted like everyone else)
 - without the switch: the old row is only counted (dry run), nothing goes
 - with KALMIDO_PURGE_LOGS=1: the old row goes, the young one stays
 - a backup older than a row keeps that row; once the backup is gone the row goes
usage: p2312_b_journal_period_test.py <datadir>      (KMT_NOSTART=1 / P2312B_NOSTART=1: a running server)"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import dbx as dbxm
import kt
from freelancer_fixture import freelancer
from kt import B, CT, check, dbx, done, fresh, setup


def write(q, args=()):
    c = dbxm.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        c.execute(q, args)
        c.commit()
    finally:
        c.close()


def in_app(code, env=()):
    """Python inside the server container (app loaded, c = a connection in the system context) -> stdout + stderr."""
    body = "\n".join("    " + x for x in code.split("\n"))
    cmd = ["docker", "exec"]
    for e in env:
        cmd += ["-e", e]
    out = subprocess.run(cmd + [CT, "python", "-c",
                                "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nc = connect()\n"
                                "with system_ctx(c):\n" + body + "\nc.commit()\nc.close()"], capture_output=True, text=True)
    return out.stdout + out.stderr


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def rows():
    return sorted(r[0] for r in dbx("SELECT user_id FROM deleted_accounts"))


TICK = "from kalmido.admin.dataretention import lgc_tick\nprint('rows', lgc_tick(c, True))"
PURGE = ("KALMIDO_PURGE_LOGS=1",)

fresh({}, prefix="P2312B")
A = setup()
OLD, _ = freelancer(B, A, "olga")     # deleted long ago (row moved back past 104 weeks)
YOUNG, _ = freelancer(B, A, "yara")   # deleted 10 days ago
for uid in (OLD, YOUNG):
    check(A.delete(B + f"/api/users/{uid}").ok, f"account {uid} deleted")
check(rows() == sorted([OLD, YOUNG]), f"(setup) both deletions are in the journal {rows()}")
write("UPDATE deleted_accounts SET at=? WHERE user_id=?", (ago(800), OLD))
write("UPDATE deleted_accounts SET at=? WHERE user_id=?", (ago(10), YOUNG))

# dry run: counted, nothing deleted
out = in_app(TICK)
check(rows() == sorted([OLD, YOUNG]), f"no switch: the journal stays complete {rows()} " + out[-200:])
last = (A.get(B + "/api/admin/retention").json().get("kinds") or {}).get("logs", {}).get("last") or {}
check(last.get("purged") is False and (last.get("counts") or {}).get("deleted_accounts") == 1,
      f"no switch: the old row is counted as a dry run {json.dumps(last)[:200]}")

# a backup older than the old row keeps it (it may still hold that account)
mk = in_app("""import os
from datetime import timedelta
from kalmido.admin import backup as bk
from kalmido.core.db import local_now
os.makedirs(bk.BK_DIR, exist_ok=True)
t = (local_now() - timedelta(days=900)).replace(microsecond=0)
p = os.path.join(bk.BK_DIR, f"kalmido-backup-{t.strftime('%Y%m%d-%H%M%S')}-manual.zip")
open(p, "wb").write(b"x")
print('made', p)""")
check("made" in mk, "(setup) an old backup file " + mk[-200:])
out = in_app(TICK, PURGE)
check(rows() == sorted([OLD, YOUNG]), f"with switch: a backup older than the row keeps it {rows()} " + out[-200:])

# the old backup gone: the old row goes, the young one stays
in_app("""import glob, os
from kalmido.admin import backup as bk
for p in glob.glob(os.path.join(bk.BK_DIR, 'kalmido-backup-*-manual.zip')):
    os.remove(p)""")
out = in_app(TICK, PURGE)
check(rows() == [YOUNG], f"with switch: the row older than 104 weeks goes, the young one stays {rows()} " + out[-200:])
last = (A.get(B + "/api/admin/retention").json().get("kinds") or {}).get("logs", {}).get("last") or {}
check(last.get("purged") is True, f"with switch: reported as deleted {json.dumps(last)[:200]}")
check(not dbx("SELECT 1 FROM deleted_accounts WHERE at<?", (ago(728),)), "nothing older than 104 weeks is left")

# 2.312.0 (#3264, review): a set backup folder that is missing (a mount away) counts as unreadable: no cut, nothing goes
out = in_app("from kalmido.admin.dataretention import lgc_journal_cut\nfrom kalmido.core.db import now_utc\nprint('cut', lgc_journal_cut(now_utc()))",
             ("KALMIDO_BACKUP_DIR=/tmp/p2312b-missing-backup-dir",))
check("cut None" in out, "a missing set backup folder: no cut " + out[-200:])

sys.exit(done("p2312_b_journal_period"))
