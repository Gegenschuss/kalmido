#!/usr/bin/env python3
"""2.306.0 G (#2946): weekly backups are kept for at most 104 weeks (52 with the retention switch).
freelancer-matrix: admin (backup settings belong to the instance admin, a person without an organisation is its own admin)
 - without the switch: a stored 300 reads as 104, PATCH 300 -> 104, PATCH 600 -> 400, keep_weekly_max always 104
 - bk_prune keeps at most 104 weekly backups when 300 is stored
 - with the switch (second container): the cap stays 52
usage: p2306_g_backup_cap_test.py <datadir>      (KMT_NOSTART=1 / P2306G_NOSTART=1: a running server)"""
import os
import subprocess
import sys

import kt
from kt import B, CT, check, done, fresh, sess, setup


def in_app(code):
    """Python inside the server container (app loaded, c = a connection in the system context) -> stdout + stderr."""
    body = "\n".join("    " + x for x in code.split("\n"))
    out = subprocess.run(["docker", "exec", CT, "python", "-c",
                          "import app\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\nc = connect()\n"
                          "with system_ctx(c):\n" + body + "\nc.commit()\nc.close()"], capture_output=True, text=True)
    return out.stdout + out.stderr


def run_cases(A, cap, tag):
    j = A.get(B + "/api/admin/backups").json()
    check(j.get("keep_weekly_max") == cap, f"{tag}: keep_weekly_max is always set ({j.get('keep_weekly_max')})")
    in_app("from kalmido.core.db import gset\ngset(c, 'bk_keep_weekly', '300')")
    check(A.get(B + "/api/admin/backups").json()["keep_weekly"] == cap, f"{tag}: a stored 300 reads as {cap}")
    r = A.patch(B + "/api/admin/backups", json={"keep_weekly": 300})
    check(r.ok and A.get(B + "/api/admin/backups").json()["keep_weekly"] == cap, f"{tag}: PATCH 300 is cut to {cap} {r.status_code}")
    check(A.patch(B + "/api/admin/backups", json={"keep_weekly": 600}).status_code == 400, f"{tag}: PATCH 600 is refused")
    check(A.patch(B + "/api/admin/backups", json={"keep_weekly": 10}).ok, f"{tag}: a small value is saved")


fresh({}, prefix="P2306G")
A = setup()
run_cases(A, 104, "no switch")

# bk_prune: 130 weekly backups (one per week, older than 24 h), 300 stored
in_app("""import os
from datetime import timedelta
from kalmido.admin import backup as bk
from kalmido.core.db import gset, local_now
os.makedirs(bk.BK_DIR, exist_ok=True)
now = local_now()
for w in range(2, 132):
    t = (now - timedelta(weeks=w)).replace(hour=3, minute=30, second=0)
    open(os.path.join(bk.BK_DIR, f"kalmido-backup-{t.strftime('%Y%m%d-%H%M%S')}-auto.zip"), "wb").write(b"x")
gset(c, 'bk_keep_daily', '1')
gset(c, 'bk_keep_weekly', '300')""")
out = in_app("""from kalmido.admin import backup as bk
gone = bk.bk_prune(c)
left = [x for x in bk.bk_list() if x['kind'] != 'safety']
print('gone', len(gone), 'left', len(left))""")
check("left 105" in out or "left 104" in out, "bk_prune: at most 104 weeks stay with 300 stored " + out[-200:])
check("gone 25" in out or "gone 26" in out, "bk_prune: the older weeks are deleted " + out[-200:])

# with the switch
fresh({"KALMIDO_PURGE_BACKUPS": "1"}, prefix="P2306G")
A = setup()
run_cases(A, 52, "switch on")

sys.exit(done("p2306_g_backup_cap"))
