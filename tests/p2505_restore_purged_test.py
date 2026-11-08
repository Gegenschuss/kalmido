#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.505.0 (#4302): the restore dialog's preview of what would be deleted again, the choice to keep it, and the off-site backups in
the clean-up of the list. Invented names only, addresses @example.com.
 preview: per kind, with the time span; what went before the backup or was made after it does not count; recent rows apart; admins only
 default: deleted again, the choice is in the log
 keep_purged: everything stays, leaves the list (a later restore with the default keeps it), the choice is in the log, a note in the result
 off-site: an older backup on the target holds the list back; a target without a readable list: nothing goes
 2.538.0 (#4367): a removed / replaced target's backups stay "formerly off-site" and hold the list back too; on without an
   upload = upload_pending (the backup page's hint); the keep note says accounts excepted
 2.538.0 (#4367, review F7): with an unreadable formerly-off-site list, removing / replacing a target that holds backups is
   refused (409), its names stay
 2.662.0 (#4587): a formerly off-site name expires after the longest set retention + 30 days: no longer counted for the
   journal, dropped by the daily clean-up, the backup page names how many still count and until when
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
T_SUB = Fr.post(B + "/api/tasks", json={"title": "Subtask, goes with its parent", "list_id": L, "parent_id": T_OLD}).json()["id"]
sql("UPDATE tasks SET created_at=? WHERE id IN (?,?,?,?)", (ago(100), T_OLD, T_REC, T_BEFORE, T_SUB), write=True)
sql("DELETE FROM tasks WHERE id=?", (T_BEFORE,), write=True)
BK = json.loads([x for x in py("from kalmido.admin import backup as bk\nprint(json.dumps({'name': bk.bk_create('manual')}))").splitlines() if x.startswith("{")][-1])["name"]
T_AFTER = Fr.post(B + "/api/tasks", json={"title": "Made after the backup", "list_id": L}).json()["id"]
sql("UPDATE tasks SET created_at=? WHERE id=?", (ago(30), T_AFTER), write=True)
for t in (T_OLD, T_REC, T_AFTER):
    sql("DELETE FROM tasks WHERE id=?", (t,), write=True)
OLD = ago(40)
for t, at in ((T_BEFORE, ago(90)), (T_OLD, OLD), (T_SUB, OLD), (T_AFTER, ago(20)), (T_REC, ago(1))):
    sql("UPDATE purged_rows SET at=? WHERE tbl='tasks' AND ref_id=?", (at, t), write=True)

# ------ the preview, as for a backup written 60 days ago (the times above stand around that day)
p = A.get(B + "/api/admin/backups/purged-preview", params={"since": ago(60)}).json()
check(p.get("kinds") == {"tasks": 2} and p.get("total") == 2, f"preview: what went before the backup or was made after it does not count {p}")
check(p.get("first") == OLD and p.get("last") == OLD, f"preview: the time span {p}")
check(p.get("recent") == 1 and p.get("recent_days") == 7, f"preview: what went in the last days apart {p}")
check(A.get(B + "/api/admin/backups/purged-preview").json().get("total") == 4, "preview: an archive without a date: every row older than the last days")
check(Fr.get(B + "/api/admin/backups/purged-preview").status_code in (401, 403, 404), "preview: admins only")

# ------ the default: deleted again, the choice in the log
ag = restore(BK).get("deleted_again") or {}
A = sess("alice")
check(ag.get("entries") == 2 and ag.get("entries_recent") == 1 and not ag.get("entries_kept"), f"default: the same number as the preview, what went along counts {ag}")
check(not sql("SELECT 1 FROM tasks WHERE id=?", (T_OLD,)), "default: an entry deleted earlier is gone again")
check("(choice: delete again)" in log(), "default: the choice is in the log")

# ------ the choice: everything stays and leaves the list
j = restore(BK, keep_purged=True)
A = sess("alice")
ag = j.get("deleted_again") or {}
check(ag.get("entries") == 0 and ag.get("entries_kept") == 3, f"keep: the numbers of the result {ag}")
check(bool(sql("SELECT 1 FROM tasks WHERE id=?", (T_OLD,))), "keep: the entry deleted earlier is back")
check(not sql("SELECT 1 FROM purged_rows WHERE tbl='tasks' AND ref_id IN (?,?)", (T_OLD, T_REC)), "keep: what came back left the list")
check("3 kept (choice: keep everything)" in log(), "keep: the choice is in the log")
check(any("trash" in n for n in j.get("notes") or []), f"keep: the note about the trash period {j.get('notes')}")
# 2.538.0 (#4367): the accounts are no part of the choice (they are deleted again): the note says so
check(any("accounts excepted" in n for n in j.get("notes") or []), f"keep: the note says accounts excepted {j.get('notes')}")
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
# 2.552.0 (#4596, review): on a hosted instance the saved target is never used (403 / no upload) - it no longer holds the list back
check("cut None" not in py("import kalmido.admin.hosting as hz\nhz.HOSTED = True\n" + CUT),
      "off-site: hosted, a target switched on without a list does not stop the clean-up for good")
setting("bko_conf", None)
check("cut None" not in py(CUT) and "cut 2020" not in py(CUT), "no off-site target ever: the local rule")
# 2.538.0 (#4367): removing the target keeps its backups' names as "formerly off-site" (they still lie there and can be
# restored): the journal is not cut past them (was: the local rule at once, 2.505.0 review)
OFF = B + "/api/admin/backups/offsite"


# 2.662.0 (#4587): formerly off-site names expire after the longest set retention + 30 days (was: never) -- the checks below set
# the longest one (365 days + 104 weeks = 1093 days) and use backups 800 / 760 days old instead of 2020 (older than the
# journal's 104 weeks, so they move the cut, and not expired yet)
def bkname(days):
    return "kalmido-backup-" + (NOW - timedelta(days=days)).strftime("%Y%m%d") + "-033000-auto.zip.enc"


def bkday(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%d")


setting("bk_keep_daily", "365")
setting("bk_keep_weekly", "104")
DAV = {"url": "https://dav.example.com/backups", "user": "kbk", "password": "dav-secret-1"}
check(A.patch(OFF, json={"type": "webdav", "webdav": DAV, "password": PW}).ok, "off-site: a target set up")
check(A.get(OFF).json().get("upload_pending") is False, "off-site: off = no hint about a missing upload")
setting("bko_conf", json.dumps({**json.loads(sql("SELECT value FROM settings WHERE key='bko_conf'")[0][0]), "on": True}))
check(A.get(OFF).json().get("upload_pending") is True, "off-site: on without an upload = the backup page's hint")
setting("bko_remote", json.dumps([bkname(800)]))  # 2.662.0 (#4587): a date that has not expired (was 2020-01-02)
check(A.get(OFF).json().get("upload_pending") is False, "off-site: after an upload no hint")
r = A.patch(OFF, json={"remove": True})
check(r.ok, f"off-site: remove the target {r.status_code} {r.text[:160]}")
out = py(CUT)
check(f"cut {bkday(800)}" in out, "off-site removed: its backups still hold the journal back " + out[-200:])
check(bkname(800) in (sql("SELECT value FROM settings WHERE key='bko_former'") or [[""]])[0][0],
      "off-site removed: the names kept as formerly off-site")
# another address of the target: the backups at the old one stay formerly off-site as well
setting("bko_former", None)
check(A.patch(OFF, json={"type": "webdav", "webdav": DAV, "password": PW}).ok, "off-site: a target again")
setting("bko_remote", json.dumps([bkname(760)]))  # 2.662.0 (#4587): was 2020-03-04
check(A.patch(OFF, json={"webdav": {**DAV, "url": "https://dav2.example.com/backups"}, "password": PW}).ok, "off-site: another address")
check(not sql("SELECT value FROM settings WHERE key='bko_remote' AND value<>''"), "another address: the list of the new target starts empty")
check(f"cut {bkday(760)}" in py(CUT), "another address: the old target's backups hold the journal back")
check(A.patch(OFF, json={"keep": 5}).ok and f"cut {bkday(760)}" in py(CUT), "the count kept is no other target")
setting("bko_former", "not json")
check("cut None" in py(CUT), "an unreadable formerly-off-site list: nothing goes")
# 2.538.0 (#4367, review F7): an unreadable formerly-off-site list: removing / replacing the target is refused, the names of
# its backups stay (was: bko_remote emptied, the names lost)
setting("bko_remote", json.dumps(["kalmido-backup-20200506-033000-auto.zip.enc"]))
conf = sql("SELECT value FROM settings WHERE key='bko_conf'")[0][0]
for what, body in (("remove", {"remove": True}), ("another address", {"webdav": {**DAV, "url": "https://dav3.example.com/backups"}, "password": PW})):
    r = A.patch(OFF, json=body)
    check(r.status_code == 409 and "bko_former" in r.text, f"unreadable formerly-off-site list: {what} refused {r.status_code} {r.text[:160]}")
    check("20200506" in sql("SELECT value FROM settings WHERE key='bko_remote'")[0][0], f"{what}: the target keeps its backups' names")
    check(sql("SELECT value FROM settings WHERE key='bko_former'")[0][0] == "not json", f"{what}: the unreadable list stays as it was")
    check(sql("SELECT value FROM settings WHERE key='bko_conf'")[0][0] == conf, f"{what}: the target stays as it was")
setting("bko_remote", None)
r = A.patch(OFF, json={"remove": True})
check(r.ok, f"unreadable formerly-off-site list, no backups on the target: removing goes {r.status_code} {r.text[:160]}")
setting("bko_former", None)

# 2.662.0 (#4587): a formerly off-site name expires once it is older than the longest set retention (keep_daily days +
# keep_weekly weeks, or the off-site keep) plus 30 days: it no longer holds the journal, the daily clean-up drops it, and the
# backup page says how many still count and until when. Time through set dates, no waiting.
setting("bk_keep_daily", "300")
setting("bk_keep_weekly", "70")  # 300 + 490 = 790 days, + 30 = 820: 800 days old still counts, 830 days old has expired
setting("bko_former", json.dumps([bkname(830), bkname(800), "not-a-backup-name"]))
out = py(CUT)
check(f"cut {bkday(800)}" in out and f"cut {bkday(830)}" not in out, "#4587: the expired name no longer holds the journal back " + out[-200:])
f = A.get(OFF).json().get("former") or {}
check(f.get("count") == 1 and str(f.get("until", ""))[:10] == (NOW + timedelta(days=20)).strftime("%Y-%m-%d"),
      f"#4587: the backup page: one former backup still counts, until its date + 820 days {f}")
setting("bko_former", json.dumps([bkname(830), bkname(800)]))  # the plain list of before 2.662 is read as it is
TICK = "import os\nos.environ['KALMIDO_PURGE_LOGS'] = '1'\nfrom kalmido.admin.dataretention import lgc_tick\nlgc_tick(c, force=True)\nprint('tick ok')"
out = py(TICK)
check("tick ok" in out, "#4587: the daily clean-up runs " + out[-300:])
check(json.loads(sql("SELECT value FROM settings WHERE key='bko_former'")[0][0]) == [bkname(800)],
      "#4587: the daily clean-up drops the expired name, the other stays")
setting("bk_keep_weekly", "50")  # 300 + 350 + 30 = 680 days: 800 days old has expired too
check(f"cut {bkday(800)}" not in py(CUT), "#4587: a shorter retention lets the name expire")
check(not A.get(OFF).json().get("former"), "#4587: nothing left to wait for = no note on the backup page")
py(TICK)
check(not (sql("SELECT value FROM settings WHERE key='bko_former'") or [[""]])[0][0], "#4587: the last expired name dropped, the list empty")
check(A.patch(OFF, json={"type": "webdav", "webdav": DAV, "password": PW}).ok and A.patch(OFF, json={"remove": True}).ok,
      "#4587: an empty list after the expiry: removing a target still works")
print(f"p2505_restore_purged: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
