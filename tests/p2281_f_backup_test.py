#!/usr/bin/env python3
"""2.281.0 D (#3118): a backup keeps no transaction open while pg_dump and the ZIP run. The test container cuts idle
transactions after 1.5 s (KALMIDO_TEST_BK_IDLE_TX_MS) and delays the ZIP step by 4 s (KALMIDO_TEST_BK_ZIP_DELAY): without
the rollback before the dump the bookkeeping fails ("io"), with it the backup counts as done and bk_last_ok is set.
freelancer-matrix: backup (instance-wide admin function, no organisation involved)
usage: p2281_f_backup_test.py <datadir>"""
import os
import subprocess
import sys
import time

from kt import FAILS, OKS, check, sess

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")

env = dict(os.environ, KALMIDO_ADMIN_ALERTS="1",
           EXTRA=" ".join(["-e KALMIDO_BACKUP_TICK=1", "-e KALMIDO_BACKUPS=1", "-e KALMIDO_TEST_BK_IDLE_TX_MS=1500",
                           "-e KALMIDO_TEST_BK_ZIP_DELAY=4"]))
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, f"back up now accepted ({r.status_code})")
j = {}
t0 = time.time()
while time.time() - t0 < 60:  # until the run has ended with a result
    j = A.get(B + "/api/admin/backups").json()
    if not j["running"] and (j["items"] or j["last_error"]):
        break
    time.sleep(0.3)
check(not j.get("last_error"), f"no error recorded: {j.get('last_error')}")
check(bool(j.get("last_ok")) and len(j.get("items", [])) == 1, "bk_last_ok set and the backup is listed")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
