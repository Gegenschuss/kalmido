#!/usr/bin/env python3
"""2.273.0 part A (#3050, #3051 points 12 + 13): nothing of a backup or a restore goes missing unseen. Invented names only.
 - a file that vanishes while the backup is written (after the database dump) is named: manifest / list / check carry
   missing_files with its path; a file that is only briefly away is taken on the second try (not named)
 - a restore that stops after the preparation keeps the rows of a table the backup does not have (before: that table was
   dropped in an own transaction ahead of pg_restore - a stop in between left it empty); a restore that goes through
   still removes it (init_db creates it again, empty)
 - the restore's answer names the waiting background jobs it could not bring back (with their number) and the devices
   with unsent changes
 - a restore whose way back fails too says so with the name of the safety backup (before: "nothing was changed")
 - a person without an organisation: her task file is the one that vanishes / is named
Starts its OWN container (start.sh) (P2273AB_NOSTART=1 = the server already runs).
usage: p2273_a_backup_test.py <datadir>"""
# freelancer-matrix: own
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, CT, check, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402


def py(code, *args):
    """A few lines of Python inside the container (the server's modules); -> the last JSON line it printed."""
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code, *args], capture_output=True, text=True, timeout=600)
    for line in reversed((r.stdout or "").strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    print("container python:", r.returncode, (r.stdout or "")[-800:], (r.stderr or "")[-1500:], flush=True)
    return {}


def items():
    return A.get(B + "/api/admin/backups").json().get("items") or []


SQL = """
import json, sys
from kalmido.core import pg as _pg
from kalmido.core.config import DATABASE_URL
out = []
for q in json.loads(sys.argv[1]):  # one connection (one transaction) per statement
    c = _pg.connect_direct(DATABASE_URL)
    try:
        with _pg.system_ctx(c):
            cur = c.execute(q)
            out.append([list(r) for r in cur.fetchall()] if q.lstrip().upper().startswith("SELECT") else None)
        c.commit()
    except Exception as e:
        c.rollback()
        out.append({"error": type(e).__name__})
    finally:
        c.close()
print(json.dumps({"out": out}, default=str))
"""


def sql(*qs):
    return py(SQL, json.dumps(list(qs))).get("out") or [None] * len(qs)


kt.fresh(prefix="P2273AB")
A = kt.setup()
FID, Fr = freelancer(B, A)
L = Fr.post(B + "/api/lists", json={"name": "Sicherung Projekt"}).json()["id"]
T = Fr.post(B + "/api/tasks", json={"title": "Mit Dateien", "list_id": L}).json()["id"]
for nm in ("gone.txt", "brief.txt"):
    r = Fr.post(B + f"/api/tasks/{T}/attachments", files={"file": (nm, f"file {nm}\n".encode(), "text/plain")})
    check(r.ok, f"freelancer: attachment {nm} {r.status_code}")
paths = dict(kt.dbx("SELECT name, path FROM attachments WHERE task_id=?", (T,)))
check(set(paths) == {"gone.txt", "brief.txt"}, f"the two files are stored {paths}")

# ================================================================== #3050 a file vanishes while the backup is written
MK = """
import json, os, sys
from kalmido.admin import backup as bk
from kalmido.core.config import ATT_DIR
gone, brief = os.path.join(ATT_DIR, sys.argv[1]), os.path.join(ATT_DIR, sys.argv[2])
real, seen = bk._sha256_file, set()
def fake(p):
    if p == gone:  # deleted after the dump (like a trash run or a move)
        os.remove(p)
        raise FileNotFoundError(p)
    if p == brief and p not in seen:  # only away for a moment (replaced in place)
        seen.add(p)
        raise FileNotFoundError(p)
    return real(p)
bk._sha256_file = fake
import contextlib, io
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    name = bk.bk_create("manual")
print(json.dumps({"name": name, "log": buf.getvalue()}))
"""
mk = py(MK, paths["gone.txt"], paths["brief.txt"])
BK1 = mk.get("name")
# 2.273.0 F1 (#3050): the server log names how many and the folders, never the file names / paths
check("1 file(s) vanished" in (mk.get("log") or "") and paths["gone.txt"].rsplit("/", 1)[-1] not in (mk.get("log") or ""),
      f"#3050: the log has the count, not the vanished file's name {mk.get('log')!r}")
check(bool(BK1), "a backup was written although a file vanished")
it = next((x for x in items() if x["name"] == BK1), {})
check(it.get("missing_files") == 1, f"#3050: the backup list names the vanished file {it.get('missing_files')!r}")
r = A.post(B + f"/api/admin/backups/{BK1}/verify", json={})
v = r.json() if r.ok else {}
check(r.ok and v.get("missing_files") == 1 and v.get("missing_paths") == ["attachments/" + paths["gone.txt"]],
      f"#3050: the check names it with its path {r.status_code} {v.get('missing_files')} {v.get('missing_paths')}")
check(v.get("attachment_files", 0) >= 1 and "attachments/" + paths["brief.txt"] not in (v.get("missing_paths") or []),
      f"#3050: the file that was only briefly away is in the backup (second try) {v.get('attachment_files')}")

# ================================================================== #3050 a table the backup does not have keeps its rows when the restore stops
q = sql("CREATE TABLE IF NOT EXISTS zz_p2273 (id BIGINT PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE CASCADE, note TEXT)",
        f"INSERT INTO zz_p2273 VALUES (1, {FID}, 'keep me')", "SELECT count(*) FROM zz_p2273")
check(q[2] == [[1]], f"a table after the backup with a row and a foreign key {q}")
STOP = """
import json, os, sys, tempfile
from kalmido.admin import backup as bk
work = tempfile.mkdtemp(prefix=".p2273-", dir=bk.BK_DIR)
man, dbp = bk.bk_prepare(os.path.join(bk.BK_DIR, sys.argv[1]), "", work)
def stop(args, err_code="io", timeout=None):  # the process stops where pg_restore would start
    raise bk.BackupError("restore", "stopped")
bk._pg_run = stop
try:
    bk._pg_restore(dbp)
    print(json.dumps({"stopped": False}))
except bk.BackupError as e:
    print(json.dumps({"stopped": e.code}))
"""
j = py(STOP, BK1)
check(j.get("stopped") == "restore", f"the restore stopped before pg_restore {j}")
q = sql("SELECT count(*) FROM zz_p2273", "SELECT note FROM zz_p2273")
check(q[0] == [[1]] and q[1] == [["keep me"]], f"#3050: the table the backup does not have keeps its row {q}")

# ================================================================== #3051 p. 12 + 13: the restore names what it cannot bring back
sql("INSERT INTO bg_jobs(kind, payload, state, run_after, created_at) VALUES ('p2273_test', '', 'wait', '2099-01-01T00:00:00Z', '2026-10-24T10:00:00Z')")
r = A.post(B + "/api/admin/backups/restore", json={"name": BK1, "confirm": "RESTORE"})
j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
check(r.ok, f"the restore went through {r.status_code} {r.text[:200]}")
notes = " | ".join(j.get("notes") or [])
check("1 waiting background jobs were not restored" in notes, f"#3051: the waiting background job is named with its number: {notes[:300]}")
check("unsent changes" in notes, f"#3051: the devices with unsent changes are named: {notes[:300]}")
A = kt.sess("alice")  # the restore ended every session
q = sql("SELECT count(*) FROM zz_p2273")
check(isinstance(q[0], dict), f"#3050: a restore that went through still removes the table the backup does not have {q}")
check(kt.dbx("SELECT count(*) FROM bg_jobs WHERE kind='p2273_test'")[0][0] == 0, "the queue is not in the backup (#2220)")

# ================================================================== #3050 the way back fails too
BACK = """
import json, os, sys
from kalmido.admin import backup as bk
def boom(dump):
    raise bk.BackupError("restore", "broken")
bk._pg_restore = boom  # the restore and the way back both fail
try:
    bk.bk_restore(os.path.join(bk.BK_DIR, sys.argv[1]), "", "alice", "session")
    print(json.dumps({"code": None}))
except bk.BackupError as e:
    print(json.dumps({"code": e.code, "text": e.text("en"), "args": [str(a) for a in e.args_]}))
"""
j = py(BACK, BK1)
safety = (j.get("args") or [""])[0]
check(j.get("code") == "rollback" and safety.startswith("kalmido-backup-") and "-safety" in safety and safety in j.get("text", ""),
      f"#3050: a failed way back says so with the safety backup's name {j}")
check("nothing was changed" not in j.get("text", ""), f"#3050: ... and never 'nothing was changed' {j.get('text')}")
check(any(x["name"] == safety for x in items()), f"the named safety backup exists {safety}")
check(Fr.get(B + f"/api/tasks/{T}").ok or kt.sess("frida").get(B + f"/api/tasks/{T}").ok, "the server still answers after the failed restore")

sys.exit(kt.done("p2273_a_backup"))
