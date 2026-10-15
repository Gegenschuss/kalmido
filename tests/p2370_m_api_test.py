#!/usr/bin/env python3
"""2.37.0 (#1150): the move from SQLite (2.36) to Postgres -- `python app.py migrate-sqlite [--check] [--source PATH]` and the
automatic move on the first start. Own test containers (start.sh, KEEP=1 with a prepared data dir); the SQLite databases come
from mk_sqlite_fixture.py (schema of 2.36.2, invented data).
 (a) empty Postgres + no tasks.db: a new install, nothing moved
 (e) --check: reports the corrections and the private agents, writes nothing (database, files); a decimal comma: exit 3
 (b) a big SQLite database (20,000 tasks, 50,000 comments / activities, every table): moved on start, counts and checksums
     equal (report), tasks.db renamed, copy in backups/, kalmido_meta.sqlite_migrated; sign-in, /api/state, the message
     search and the office amounts work; the time it took is printed (MIGRATION ... s)
 (g) K2-3: a private agent in an organisation's list is in the report and in the boundary check (list_agent_private)
 (d) a second start ignores the renamed file; the moved file put back is ignored (known hash); another tasks.db next to a
     database with data: exit 3
 (c) broken values: text in number columns, invalid / empty JSON, an orphan row -> corrected and listed in the report;
     a decimal comma in an amount -> exit 3, Postgres empty, tasks.db unchanged
 (f) an old backup zip (format 1, tasks.db inside) through the admin restore: moved over, its data and files there
usage: p2370_m_api_test.py <datadir>"""
import glob
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from decimal import Decimal

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
DBF = os.path.join(DATA, "tasks.db")
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def state():
    st = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", CT], capture_output=True, text=True).stdout.split()
    return (st[0] == "true", int(st[1])) if st else (False, None)


def wait_up(timeout=900):
    """True once /api/health answers; False when the container stopped (exit code in state())."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get(B + "/api/health", timeout=2).ok:
                return True
        except requests.RequestException:
            pass
        if not state()[0]:
            return False
        time.sleep(0.5)
    return False


def fixture(path, *args):
    r = subprocess.run([sys.executable, os.path.join(N, "mk_sqlite_fixture.py"), path, *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def fresh_dir():
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA, exist_ok=True)


def start():
    """start.sh with KEEP=1 on the prepared data dir (its database starts empty); start.sh itself waits 30 s only."""
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, KEEP="1"), capture_output=True, text=True)


def psql(sql):
    with open(os.path.join(DATA, ".kalmido-db"), encoding="utf-8") as f:
        dbc, dbn = f.read().split()
    r = subprocess.run(["docker", "exec", dbc, "psql", "-U", "kalmido", "-d", dbn, "-v", "ON_ERROR_STOP=1", "-Atqc", sql],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "ERR " + r.stderr.strip()


def tables():
    return int(psql("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'") or 0)


def sess(user="alice", pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    return s if r.ok and r.json().get("ok") else None


def report():
    ps = sorted(glob.glob(os.path.join(DATA, "backups", "migration-report-*.json")), key=os.path.getmtime)
    return json.load(open(ps[-1], encoding="utf-8")) if ps else {}


def cli(*args):
    r = subprocess.run(["docker", "exec", CT, "python", "app.py", "migrate-sqlite", *args], capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    i = r.stdout.find("\n{")  # 2.45.0 (#1515): start warnings go to stderr, the report is the end of stdout
    try:
        rep = json.loads(r.stdout[i + 1:]) if i >= 0 else {}
    except ValueError:
        rep = {}
    return r.returncode, out, rep


# ================================================================== (a) empty Postgres, no tasks.db: a new install
fresh_dir()
start()
check(wait_up(60), "(a) a new install starts")
check("migrate-sqlite:" not in logs() and not glob.glob(os.path.join(DATA, "backups", "migration-report-*")), "(a) nothing moved, no report")
check(psql("SELECT COUNT(*) FROM kalmido_meta WHERE key='sqlite_migrated'") == "0", "(a) no sqlite_migrated")
r = requests.post(B + "/api/auth/setup", headers=H, json={"username": "admin", "display_name": "Admin", "password": "password123"})
check(r.ok, "(a) the setup page creates the first admin " + r.text[:100])

# ================================================================== (e) --check writes nothing
info = fixture(os.path.join(DATA, "old.db"), "--tasks", "400", "--comments", "300", "--activity", "300", "--broken", "text,json,orphan", "--k23")
h0, n0 = sha(os.path.join(DATA, "old.db")), tables()
bk0 = sorted(os.listdir(os.path.join(DATA, "backups"))) if os.path.isdir(os.path.join(DATA, "backups")) else []
users0 = psql("SELECT COUNT(*) FROM users")
code, out, rep = cli("--check", "--source", "/data/old.db")
check(code == 0 and rep.get("status") == "check", f"(e) --check: exit 0, a report ({code}) {out[-400:]}")
what = {(x["table"], x["column"], x["what"]) for x in rep.get("corrections", [])}
check(("activity", "data", "invalid JSON -> {}") in what and ("agent_chat", "choices", "invalid JSON -> NULL") in what
      and ("tasks", "priority", "empty text -> default") in what and ("tasks", "snippets", "empty JSON -> NULL") in what,
      "(e) --check lists the corrections " + str(sorted(what))[:400])
check(rep.get("private_agents_in_organisation_lists", {}).get("rows") == [[info["shared_list"], info["users"]["pbot"]]],
      "(e) --check names the private agent in the organisation's list (K2-3) " + str(rep.get("private_agents_in_organisation_lists")))
check(sha(os.path.join(DATA, "old.db")) == h0 and tables() == n0 and psql("SELECT COUNT(*) FROM users") == users0,
      "(e) --check: the file and the database unchanged")
check((sorted(os.listdir(os.path.join(DATA, "backups"))) if os.path.isdir(os.path.join(DATA, "backups")) else []) == bk0,
      "(e) --check: no file written (no copy, no report)")
fixture(os.path.join(DATA, "comma.db"), "--tasks", "200", "--comments", "100", "--activity", "100", "--broken", "comma")
code, out, rep = cli("--check", "--source", "/data/comma.db")
check(code == 3 and "decimal comma" in out and "office_doc_items.rate" in out, f"(e) --check: a decimal comma -> exit 3 with table and row ({code}) {out[-300:]}")
code, out, _ = cli("--source", "/data/old.db")
check(code == 3 and "not empty" in out, f"(e) a move into a database with data is refused ({code})")

# ================================================================== (b) + (g) the big database, moved on start
fresh_dir()
big = fixture(DBF, "--k23")
hb, want = sha(DBF), big["tables"]
t0 = time.time()
start()
ok = wait_up(900)
secs = time.time() - t0
check(ok, "(b) the big database: the app starts after the move " + logs()[-1500:])
lg = logs()
rows = sum(want.values())
mt = next((ln for ln in lg.splitlines() if ln.startswith("migrate-sqlite: done:")), "")
print(f"MIGRATION big: {rows} rows in {len(want)} tables, start to healthy {secs:.1f} s; {mt}", flush=True)
rep = report()
check(rep.get("status") == "ok" and len(rep.get("tables", {})) == len(want), f"(b) report: ok, every table ({len(rep.get('tables', {}))}/{len(want)})")
diff = {t: (want[t], x.get("source"), x.get("written")) for t, x in rep.get("tables", {}).items() if x.get("source") != want.get(t)}
check(not diff, "(b) report: source rows = rows of the SQLite file " + str(diff)[:300])
left = {t: x for t, x in rep.get("tables", {}).items() if x.get("written") != x.get("source")}
check(set(left) == {"list_tags", "task_list_tags"} and left["list_tags"]["source"] - left["list_tags"]["written"] == 1,
      "(b) only the merged list tag (and the double tag of a task) differ " + str(left)[:300])
check(psql("SELECT COUNT(*) FROM tasks") == str(want["tasks"] + want["list_milestones"]), "(b) tasks (+ the milestones of 2.17, now tasks)")
for t in ("comments", "attachments", "office_doc_items", "agent_chat", "list_members", "time_entries"):
    # 2.41.0 (#1471): the lists holding time entries get time tracking on (migr_time241), so the focus sessions of the generic rows
    # that the watchdog ends right after the start become time entries there (pomo_id set): count the moved rows only
    w = " WHERE pomo_id IS NULL" if t == "time_entries" else ""
    check(psql(f"SELECT COUNT(*) FROM {t}{w}") == str(want[t]), f"(b) {t}: {want[t]} rows in Postgres ({psql(f'SELECT COUNT(*) FROM {t}{w}')}, all {psql(f'SELECT COUNT(*) FROM {t}')})")
for t in ("activity", "notifications"):  # (the app writes / tidies these right after the start: the report's count)
    check(rep.get("tables", {}).get(t, {}).get("written") == want[t], f"(b) {t}: {want[t]} rows copied")
check(want["tasks"] >= 20000 and want["comments"] >= 50000 and want["activity"] >= 50000, "(b) the fixture is big")
check(not os.path.exists(DBF) and [sha(p) for p in glob.glob(DBF + ".migrated-*")] == [hb], "(b) tasks.db renamed, unchanged")
check(len(glob.glob(os.path.join(DATA, "backups", "pre-postgres-*.db"))) == 1, "(b) a copy of the source in backups/")
meta = json.loads(psql("SELECT value FROM kalmido_meta WHERE key='sqlite_migrated'") or "{}")
check(meta.get("sha256") == hb, "(b) kalmido_meta.sqlite_migrated knows the file " + str(meta)[:200])
check(psql("SELECT is_identity FROM information_schema.columns WHERE table_name='list_members' AND column_name='id'") == "YES"
      and psql("SELECT COUNT(DISTINCT id) FROM list_members") == str(want["list_members"]), "(b) list_members.id assigned")
nid = psql("SELECT MAX(id) FROM tasks")
A = sess()
check(A is not None, "(b) alice signs in with her old password")
if A:
    r = A.get(B + "/api/state")
    check(r.ok and len(r.json().get("tasks", [])) > 1000, f"(b) /api/state ({r.status_code}, {len(r.json().get('tasks', [])) if r.ok else 0} tasks)")
    r = A.get(B + "/api/search/messages", params={"q": "aerger"})
    check(r.ok and len(r.json().get("hits", [])) > 10, "(b) the message search finds old comments (Ärger as aerger) " + r.text[:120])
    lid = big["shared_list"]
    r = A.post(B + "/api/tasks", json={"title": "after the move", "list_id": lid})
    check(r.ok and r.json()["id"] > int(nid), f"(b) a new task gets an id after the old ones ({r.json().get('id') if r.ok else r.text[:100]} > {nid})")
check(psql("SELECT rate::text FROM office_doc_items WHERE id=1") == "1234.5678" and psql("SELECT qty::text FROM office_doc_items WHERE id=2") == "1.5000",
      "(b) office amounts exact (NUMERIC) " + psql("SELECT rate::text, qty::text FROM office_doc_items WHERE id IN (1,2)"))
check(psql("SELECT SUM(rate*qty)::numeric(14,4)::text FROM office_doc_items") == str(40 * sum((Decimal("1234.5678") + j) * (Decimal("0.5") + j) for j in range(5)).quantize(Decimal("0.0001"))),
      "(b) office totals " + psql("SELECT SUM(rate*qty) FROM office_doc_items"))
check(psql("SELECT COUNT(*) FROM tasks WHERE snippets IS NOT NULL") == "0", "(b) tasks.snippets '' -> NULL")
check(psql("SELECT COUNT(*) FROM list_tags WHERE list_id=%d AND lower(name)='ärger'" % big["shared_list"]) == "1"
      and psql("SELECT COUNT(*) FROM task_list_tags WHERE tag_id=%d" % big["tags"][0]) == "2", "(b) Ärger/ärger merged, both tasks keep the tag")
# (g) K2-3
k23 = rep.get("private_agents_in_organisation_lists", {})
check(k23.get("rows") == [[big["shared_list"], big["users"]["pbot"]]] and "workspace" in k23.get("hint", ""), "(g) the report names the private agent " + str(k23))
check("K2-3" in lg, "(g) and the log")
if A:
    bd = A.get(B + "/api/admin/orgs").json().get("boundary", {})
    check(bd.get("kinds", {}).get("list_agent_private") == 1 and "list_agent" not in bd.get("kinds", {}),
          "(g) the boundary check counts it as its own kind " + str(bd.get("kinds")))

# ================================================================== (d) the second start
subprocess.run(["docker", "restart", CT], capture_output=True)
check(wait_up(120), "(d) second start")
check(logs().count("migrate-sqlite: moving") == 1 and sess() is not None, "(d) nothing moved again, data there")
mig = glob.glob(DBF + ".migrated-*")[0]
subprocess.run(["cp", mig, DBF])
subprocess.run(["docker", "restart", CT], capture_output=True)
check(wait_up(120) and "moved into Postgres before; ignored" in logs(), "(d) the moved file put back: ignored")
import sqlite3  # noqa: E402
con = sqlite3.connect(DBF)
con.execute("UPDATE tasks SET title='changed' WHERE id=1")
con.commit()
con.close()
subprocess.run(["docker", "restart", CT], capture_output=True)
check(not wait_up(60) and state()[1] == 3 and "two versions" in logs(), f"(d) another tasks.db next to a database with data: exit 3 ({state()})")
os.remove(DBF)

# ================================================================== (c) broken values
fresh_dir()
small = fixture(DBF, "--tasks", "300", "--comments", "300", "--activity", "300", "--broken", "text,json,orphan")
start()
check(wait_up(300), "(c) broken values: moved, starts " + logs()[-800:])
rep = report()
what = {(x["table"], x["column"], x["what"]): x["count"] for x in rep.get("corrections", [])}
check(what.get(("activity", "data", "invalid JSON -> {}")) == 1 and what.get(("notifications", "data", "empty JSON -> {}")) == 1
      and what.get(("agent_chat", "choices", "invalid JSON -> NULL")) == 1, "(c) JSON corrected and counted " + str(what)[:300])
check(what.get(("tasks", "priority", "empty text -> default")) == 1 and what.get(("tasks", "duration", "empty text -> NULL")) == 1
      and what.get(("tasks", "pinned", "true/false -> 1/0")) == 1, "(c) text in number columns corrected")
check(psql("SELECT priority FROM tasks WHERE id=3") == "0" and psql("SELECT duration IS NULL FROM tasks WHERE id=4") == "t"
      and psql("SELECT pinned FROM tasks WHERE id=6") == "1", "(c) the corrected values in Postgres")
check(psql("SELECT data::text FROM activity WHERE id=1") == "{}" and psql("SELECT COALESCE(choices::text,'null') FROM agent_chat WHERE id=10") == "null",
      "(c) JSON values in Postgres")
check(rep.get("left_out", {}).get("comments") and psql("SELECT COUNT(*) FROM comments") == str(small["tables"]["comments"] - 1),
      "(c) the orphan comment left out and listed " + str(rep.get("left_out")))

# ================================================================== (f) an old backup zip through the admin restore
leg = os.path.join(DATA, "leg.db")
lgi = fixture(leg, "--tasks", "150", "--comments", "100", "--activity", "100")
con = sqlite3.connect(leg)
con.execute("UPDATE tasks SET title='Aus dem alten Backup' WHERE id=1")
con.commit()
con.close()
data, att = open(leg, "rb").read(), b"old file"
os.remove(leg)
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    files = []
    for n, d in (("tasks.db", data), ("attachments/1/a.txt", att)):
        z.writestr(n, d)
        files.append([n, len(d), hashlib.sha256(d).hexdigest()])
    z.writestr("manifest.json", json.dumps({"format": "kalmido-backup", "format_version": 1, "app_version": "2.36.2", "schema_version": 2,
                                            "created_at": "2026-01-01T00:00:00+00:00", "kind": "manual", "counts": {}, "files": files}))
A = sess()
up = A.post(B + "/api/admin/backups/upload", data=buf.getvalue(), headers={"Content-Type": "application/octet-stream"}) if A else None
check(up is not None and up.ok and up.json().get("legacy") is True, "(f) old archive uploaded, marked legacy " + (up.text[:200] if up is not None else ""))
if up is not None and up.ok:
    r = A.post(B + "/api/admin/backups/restore", json={"confirm": "RESTORE", "upload": up.json()["upload"]})
    check(r.ok and r.json().get("ok"), "(f) the restore of the old archive runs the move " + r.text[:300])
    A2 = sess()
    st = A2.get(B + "/api/state").json() if A2 else {}
    check(any(t["id"] == 1 and t["title"] == "Aus dem alten Backup" for t in st.get("tasks", [])), "(f) the data of the old backup is there")
    check(open(os.path.join(DATA, "attachments", "1", "a.txt"), "rb").read() == att, "(f) its files are there")
    meta = json.loads(psql("SELECT value FROM kalmido_meta WHERE key='sqlite_migrated'") or "{}")
    check(meta.get("restore") is True and meta.get("sha256") == hashlib.sha256(data).hexdigest(), "(f) recorded as a move from a restore")
    check(psql("SELECT COUNT(*) FROM tasks") == str(150 + lgi["tables"]["list_milestones"]), "(f) only the backup's tasks " + psql("SELECT COUNT(*) FROM tasks"))

# ================================================================== (c) a decimal comma: stop, nothing written
fresh_dir()
fixture(DBF, "--tasks", "200", "--comments", "100", "--activity", "100", "--broken", "comma")
hc = sha(DBF)
start()
check(not wait_up(120) and state()[1] == 3, f"(c) decimal comma: the container stops with exit code 3 ({state()})")
lg = logs()
check("decimal comma" in lg and "office_doc_items.rate" in lg and "row id=3" in lg, "(c) the log names table, column and row " + lg[-400:])
check(tables() == 0, f"(c) Postgres stays empty ({tables()} tables)")
check(os.path.exists(DBF) and sha(DBF) == hc and not glob.glob(DBF + ".migrated-*"), "(c) tasks.db unchanged, not renamed")
check(report().get("status") == "failed", "(c) a report of the failed move")
# review W3-1: a failed move leaves no copy of the source and one report file, also after restarts
check(not glob.glob(os.path.join(DATA, "backups", "pre-postgres-*.db")), "(c) no copy of the source after a failed move")
check(glob.glob(os.path.join(DATA, "backups", "migration-report-*.json")) == [os.path.join(DATA, "backups", "migration-report-failed.json")],
      "(c) one report file for failed moves")

subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
print(f"p2370_m_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
