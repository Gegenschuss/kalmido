#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.505.0 (#4302): the restore dialog's preview of what would be deleted again, the choice to keep it, and the off-site backups in
the clean-up of the list. Invented names only, addresses @example.com.
 preview: per kind, with the time span; what went before the backup or was made after it does not count; recent rows apart; admins only
 default: deleted again, the choice is in the log
 keep_purged: everything stays, leaves the list (a later restore with the default keeps it), the choice is in the log, a note in the result
 off-site: an older backup on the target holds the list back; a target without a readable list: nothing goes
usage: p2505_restore_purged_test.py <datadir>
freelancer-matrix: admin (the restore is the instance's; the entries are those of a person without an organisation)"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
PW = kt.PASSWORD
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2505R")
A = kt.setup()
NOW = datetime.now(timezone.utc)


def ago(days):
    return (NOW - timedelta(days=days)).isoformat(timespec="seconds")


def sql(q, args=(), write=False):
    c = dbxm.connect(DATA)
    try:
        r = c.execute(q, args)
        rows = None if write else r.fetchall()
        c.commit()
        return rows
    finally:
        c.close()


def py(code):
    """Lines inside the container -> its output."""
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", "import app, json\nfrom kalmido.core.db import connect\nfrom kalmido.core.pg import system_ctx\n"
                        "c = connect()\nwith system_ctx(c):\n" + "\n".join("    " + x for x in code.strip().split("\n")) + "\n    c.commit()\nc.close()"],
                       capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def log():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def restore(name, **kw):
    r = A.post(B + "/api/admin/backups/restore", json={"name": name, "confirm": "RESTORE", "password": PW, **kw})
    check(r.ok, f"restore {kw} {r.status_code} {r.text[:200]}")
    return r.json() if r.ok else {}


FR, Fr = freelancer(B, A, "frieda")  # a person without an organisation: their entries as everybody's
L = Fr.post(B + "/api/lists", json={"name": "Old project"}).json()["id"]
T_OLD, T_REC, T_BEFORE = (Fr.post(B + "/api/tasks", json={"title": t, "list_id": L}).json()["id"] for t in ("Old task", "Recent task", "Gone before the backup"))
sql("UPDATE tasks SET created_at=? WHERE id IN (?,?,?)", (ago(100), T_OLD, T_REC, T_BEFORE), write=True)
sql("DELETE FROM tasks WHERE id=?", (T_BEFORE,), write=True)
BK = json.loads([x for x in py("from kalmido.admin import backup as bk\nprint(json.dumps({'name': bk.bk_create('manual')}))").splitlines() if x.startswith("{")][-1])["name"]
T_AFTER = Fr.post(B + "/api/tasks", json={"title": "Made after the backup", "list_id": L}).json()["id"]
sql("UPDATE tasks SET created_at=? WHERE id=?", (ago(30), T_AFTER), write=True)
for t in (T_OLD, T_REC, T_AFTER):
    sql("DELETE FROM tasks WHERE id=?", (t,), write=True)
OLD = ago(40)
for t, at in ((T_BEFORE, ago(90)), (T_OLD, OLD), (T_AFTER, ago(20)), (T_REC, ago(1))):
    sql("UPDATE purged_rows SET at=? WHERE tbl='tasks' AND ref_id=?", (at, t), write=True)

# ------ the preview, as for a backup written 60 days ago (the times above stand around that day)
p = A.get(B + "/api/admin/backups/purged-preview", params={"since": ago(60)}).json()
check(p.get("kinds") == {"tasks": 1} and p.get("total") == 1, f"preview: what went before the backup or was made after it does not count {p}")
check(p.get("first") == OLD and p.get("last") == OLD, f"preview: the time span {p}")
check(p.get("recent") == 1 and p.get("recent_days") == 7, f"preview: what went in the last days apart {p}")
check(A.get(B + "/api/admin/backups/purged-preview").json().get("total") == 3, "preview: an archive without a date: every row older than the last days")
check(Fr.get(B + "/api/admin/backups/purged-preview").status_code in (401, 403, 404), "preview: admins only")

# ------ the default: deleted again, the choice in the log
ag = restore(BK).get("deleted_again") or {}
A = sess("alice")
check(ag.get("entries") == 1 and ag.get("entries_recent") == 1 and not ag.get("entries_kept"), f"default: the numbers of the result {ag}")
check(not sql("SELECT 1 FROM tasks WHERE id=?", (T_OLD,)), "default: an entry deleted earlier is gone again")
check("(choice: delete again)" in log(), "default: the choice is in the log")

# ------ the choice: everything stays and leaves the list
j = restore(BK, keep_purged=True)
A = sess("alice")
ag = j.get("deleted_again") or {}
check(ag.get("entries") == 0 and ag.get("entries_kept") == 2, f"keep: the numbers of the result {ag}")
check(bool(sql("SELECT 1 FROM tasks WHERE id=?", (T_OLD,))), "keep: the entry deleted earlier is back")
check(not sql("SELECT 1 FROM purged_rows WHERE tbl='tasks' AND ref_id IN (?,?)", (T_OLD, T_REC)), "keep: what came back left the list")
check("2 kept (choice: keep everything)" in log(), "keep: the choice is in the log")
check(any("trash" in n for n in j.get("notes") or []), f"keep: the note about the trash period {j.get('notes')}")
restore(BK)
A = sess("alice")
check(bool(sql("SELECT 1 FROM tasks WHERE id=?", (T_OLD,))), "keep: a later restore with the default leaves it alone")

# ------ only true chooses: another value is the default
made = sql("SELECT created_at FROM tasks WHERE id=?", (T_OLD,))[0][0]
sql("INSERT INTO purged_rows(tbl, ref_id, made, at) VALUES('tasks',?,?,?)", (T_OLD, made, OLD), write=True)
restore(BK, keep_purged="yes")
A = sess("alice")
check(not sql("SELECT 1 FROM tasks WHERE id=?", (T_OLD,)), "keep_purged other than true: deleted again")

# ------ the off-site backups in the clean-up of the list
CUT = "from kalmido.admin.dataretention import lgc_journal_cut\nfrom kalmido.core.db import now_utc\nprint('cut', lgc_journal_cut(now_utc(), c))"


def setting(key, value):
    sql("DELETE FROM settings WHERE key=?", (key,), write=True)
    if value is not None:
        sql("INSERT INTO settings(key, value) VALUES(?,?)", (key, value), write=True)


setting("bko_remote", json.dumps(["kalmido-backup-20200102-033000-auto.zip.enc"]))
out = py(CUT)
check("cut 2020-01-02" in out, "off-site: an older backup on the target holds the list back " + out[-200:])
setting("bko_remote", "not json")
check("cut None" in py(CUT), "off-site: an unreadable list: nothing goes")
setting("bko_remote", None)
setting("bko_conf", json.dumps({"on": True, "type": "s3"}))
check("cut None" in py(CUT), "off-site: a target switched on without a list: nothing goes")
setting("bko_conf", None)
out = py(CUT)
check("cut None" not in out and "cut 2020" not in out, "no off-site target: the local rule " + out[-200:])
print(f"p2505_restore_purged: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
