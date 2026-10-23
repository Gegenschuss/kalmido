#!/usr/bin/env python3
"""2.152.0 API tests, part B (#2165: trash periods; #2172: backups), own container (start.sh). Invented people and
addresses only (example.com).
 - #2165: in every area one object goes into the trash and is dated back past the period (files with the stored file,
   wiki page (its own run wiki_trash_tick), hub mail with its word index, table + a deleted row / column of a live table, pipeline deal, invoice series,
   team chat tombstone, emptied comment); the run with the switch off deletes nothing and reports the numbers per area
   (GET /api/admin/retention); with KALMIDO_RETENTION_PURGE=1 they are gone (the stored file from the disk too, the hub
   mail's folder in the file store's trash); what was deleted today stays; the file store's trash view says the period
 - #2172: keep_weekly at most 52 only with the switch (2.186.0 #2602: without it the value stays); a safety backup older than 30 days goes
   only with the switch (counted without); list header pictures (attachments/listheads) are in the archive;
   KALMIDO_BACKUP_ENCRYPT_REQUIRED=1 without a passphrase writes no backup; the journal of deleted accounts: an account
   deleted after a backup is deleted again after restoring that backup (one that owns lists is disabled), the journal
   itself survives the restore
Selbstständige: the trash objects of the private space belong to a person without an organisation (frida). The backups are
the instance admin's alone (no organisation, no freelancer side): n/a.
usage: p2103_b_api_test.py <datadir>      (P2103B_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import io
import os
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import dbx as dbxm
import requests
from freelancer_fixture import FEATURES, freelancer
import testclock  # noqa: E402  (2.192.0 A, #2512: the group's test time, run_all.sh `now`)

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
BK = os.path.join(DATA, "backups")
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, args)
        if write:
            c.commit()
            return None
        return r.fetchall()
    finally:
        c.close()


def one(q, args=()):
    rows = sql(q, args)
    return rows[0][0] if rows else None


def app_log():
    out = subprocess.run(["docker", "logs", "--tail", "400", CT], capture_output=True, text=True)
    text = out.stdout + out.stderr
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


def in_app(code, env=()):
    """Python inside the app container (the watchdog's runs called directly)."""
    cmd = ["docker", "exec"] + [x for k in env for x in ("-e", k)] + [CT, "python", "-c",
                                                                        "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.close()"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    return out.stdout + out.stderr


def retention(kind):
    r = A.get(B + "/api/admin/retention")
    return (r.json().get("kinds") or {}).get(kind) if r.ok else None


def backup_now():
    """"Back up now" runs in the background: wait until the new one is listed. -> its name or None."""
    n = len(A.get(B + "/api/admin/backups").json()["items"])
    r = A.post(B + "/api/admin/backups")
    check(r.status_code == 202, "back up now " + r.text[:160])
    t0 = time.time()
    while time.time() - t0 < 60:
        j = A.get(B + "/api/admin/backups").json()
        if not j["running"] and (len(j["items"]) > n or j["last_error"]):
            break
        time.sleep(0.3)
    items = [x for x in j["items"] if x["kind"] == "manual"]
    return items[0]["name"] if items and len(j["items"]) > n else None


def ago(days):
    return (testclock.now().astimezone(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


if os.environ.get("P2103B_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Studio", "admin_id": ALICE}).json()["id"]
FID, Fr = freelancer(B, A, features=FEATURES + ",sheets")
OLD = ago(31)

# ================================================================== #2165 the trash periods
# file store: an old file in the trash (with its stored file) and one deleted today
for nm in ("old-contract.txt", "fresh-draft.txt"):
    r = Fr.post(B + "/api/files/upload", data={"space": "private"}, files={"file": (nm, b"invented text\n" * 40, "text/plain")})
    check(r.status_code == 201, f"setup: upload {nm} " + r.text[:160])
F_OLD = one("SELECT id FROM fs_nodes WHERE owner_id=? AND name='old-contract.txt'", (FID,))
F_NEW = one("SELECT id FROM fs_nodes WHERE owner_id=? AND name='fresh-draft.txt'", (FID,))
P_OLD = os.path.join(DATA, "attachments", one("SELECT path FROM fs_versions WHERE node_id=?", (F_OLD,)) or "-")
check(os.path.isfile(P_OLD), "setup: the stored file is on the disk")
for nid in (F_OLD, F_NEW):
    check(Fr.delete(B + f"/api/files/nodes/{nid}").ok, f"setup: file {nid} into the trash")
sql("UPDATE fs_nodes SET deleted_at=? WHERE id=?", (OLD, F_OLD), write=True)
j = Fr.get(B + "/api/files", params={"space": "trash"}).json()
check(j.get("trash_days") == 30 and {F_OLD, F_NEW} <= {x["id"] for x in j["items"]}, f"the trash view says the period: {j.get('trash_days')}")

# wiki: an old page and a fresh one
for path in ("Old note", "Fresh note"):
    r = Fr.post(B + "/api/wiki/pages", json={"space": "private", "path": path, "body": "Invented text"})
    check(r.ok, f"setup: wiki page {path} " + r.text[:160])
W_OLD = one("SELECT id FROM wiki_pages WHERE owner_id=? AND path='Old note'", (FID,))
W_NEW = one("SELECT id FROM wiki_pages WHERE owner_id=? AND path='Fresh note'", (FID,))
for pid in (W_OLD, W_NEW):
    check(Fr.delete(B + f"/api/wiki/pages/{pid}").ok, f"setup: wiki page {pid} into the trash")
sql("UPDATE wiki_pages SET deleted_at=? WHERE id=?", (OLD, W_OLD), write=True)

# tables: an old deleted table; a live table with an old deleted row and column
r = Fr.post(B + "/api/sheets", json={"title": "Old table", "space": "private"})
check(r.status_code == 201, "setup: table " + r.text[:160])
S_OLD = r.json()["id"]
S_LIVE = Fr.post(B + "/api/sheets", json={"title": "Live table", "space": "private"}).json()["id"]
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def sheet_file(sid, rid, name):
    """A file column on the sheet and a file into the row's cell -> (sheet_files id, stored path on the disk)."""
    cid = Fr.post(B + f"/api/sheets/{sid}/columns", json={"title": "Doc", "kind": "file"}).json()["column"]["id"]
    r = Fr.post(B + f"/api/sheets/{sid}/files", data={"row_id": str(rid), "col_id": str(cid)}, files={"file": (name, PDF, "application/pdf")})
    check(r.status_code == 201, f"setup: file {name} into a table cell " + r.text[:160])
    fid = r.json().get("file", {}).get("id") if r.ok else 0
    return fid, os.path.join(DATA, "attachments", one("SELECT path FROM sheet_files WHERE id=?", (fid,)) or "-")


# 2.152.0 (#2165, review C-M1): a further sheet of the old table holds a file (with a text row): all of it goes with the table
r = Fr.post(B + f"/api/sheets/{S_OLD}/tabs", json={})
check(r.status_code == 201, "setup: a second sheet of the old table " + r.text[:160])
S_TAB = r.json()["tab"]["id"] if r.ok else 0
TF, TF_PATH = sheet_file(S_TAB, one("SELECT id FROM sheet_rows WHERE sheet_id=? ORDER BY pos LIMIT 1", (S_TAB,)), "tab-receipt.pdf")
check(os.path.isfile(TF_PATH), "setup: the further sheet's file is on the disk")
sql("INSERT INTO file_text(kind, ref_id, ws, state, created_at, updated_at) VALUES('sheet',?,?,'found',?,?)", (TF, f"u{FID}", OLD, OLD), write=True)
check(Fr.delete(B + f"/api/sheets/{S_OLD}").ok, "setup: the old table into the trash")
ROW = one("SELECT id FROM sheet_rows WHERE sheet_id=? ORDER BY pos LIMIT 1", (S_LIVE,))
COL = one("SELECT id FROM sheet_columns WHERE sheet_id=? ORDER BY pos LIMIT 1", (S_LIVE,))
# 2.152.0 (#2165, review C-M2): the deleted row holds a file; a second row keeps its own
RF, _ = sheet_file(S_LIVE, ROW, "row-receipt.pdf")
r = Fr.post(B + f"/api/sheets/{S_LIVE}/files", files={"file": ("kept.pdf", PDF, "application/pdf")},
            data={"row_id": str(one("SELECT id FROM sheet_rows WHERE sheet_id=? ORDER BY pos LIMIT 1 OFFSET 1", (S_LIVE,))),
                  "col_id": str(one("SELECT col_id FROM sheet_cells WHERE raw=?", (f"file:{RF}",)))})
check(r.status_code == 201, "setup: a file in a second, live row " + r.text[:160])
KF = r.json().get("file", {}).get("id") if r.ok else 0
check(Fr.delete(B + f"/api/sheets/{S_LIVE}/rows/{ROW}").ok and Fr.delete(B + f"/api/sheets/{S_LIVE}/columns/{COL}").ok,
      "setup: a row and a column of the live table into the trash")
sql("UPDATE sheets SET deleted_at=? WHERE id=?", (OLD, S_OLD), write=True)
sql("UPDATE sheet_rows SET deleted_at=? WHERE id=?", (OLD, ROW), write=True)
sql("UPDATE sheet_columns SET deleted_at=? WHERE id=?", (OLD, COL), write=True)

# hub mail: its folder in the file store (with a file), the word index (rows written straight: the mail import needs a mailbox)
r = Fr.post(B + "/api/files/folders", json={"name": "Mail from a client", "space": "private"})
check(r.status_code in (200, 201), "setup: the mail's folder " + r.text[:160])
HF = one("SELECT id FROM fs_nodes WHERE owner_id=? AND name='Mail from a client'", (FID,))
Fr.post(B + "/api/files/upload", data={"parent_id": str(HF)}, files={"file": ("mail.eml", b"Subject: invented\n\nhello\n", "message/rfc822")})
sql("INSERT INTO hub_mails(org_id, owner_id, ws, message_id, subject, created_at, folder_id, deleted_at) VALUES(NULL,?,?,?,?,?,?,?)",
    (FID, f"u{FID}", "old-1@example.com", "Invented", OLD, HF, OLD), write=True)
HM = one("SELECT id FROM hub_mails WHERE message_id='old-1@example.com'")
sql("INSERT INTO hub_words(mail_id, h) VALUES(?, 'abc123')", (HM,), write=True)
sql("INSERT INTO hub_mails(org_id, owner_id, ws, message_id, created_at, deleted_at) VALUES(NULL,?,?,?,?,?)",
    (FID, f"u{FID}", "fresh-1@example.com", ago(0), ago(0)), write=True)

# office (the organisation of alice): a deal and an invoice series in the bin
sql("INSERT INTO office_deals(org_id, title, created_at, updated_at, deleted_at) VALUES(?,?,?,?,?)", (ORG, "Old deal", OLD, OLD, OLD), write=True)
sql("INSERT INTO office_deals(org_id, title, created_at, updated_at, deleted_at) VALUES(?,?,?,?,?)", (ORG, "Live deal", OLD, OLD, None), write=True)
sql("INSERT INTO office_inv_series(org_id, title, created_at, updated_at, deleted_at) VALUES(?,?,?,?,?)", (ORG, "Old series", OLD, OLD, OLD), write=True)

# team chat: a tombstone of a deleted message (body already empty), a live message
sql("INSERT INTO tchat_rooms(kind, a, b, created_at) VALUES('dm',?,?,?)", (min(ALICE, FID), max(ALICE, FID), OLD), write=True)
ROOM = one("SELECT id FROM tchat_rooms WHERE kind='dm' AND a=? AND b=?", (min(ALICE, FID), max(ALICE, FID)))
sql("INSERT INTO tchat_msgs(room_id, user_id, body, created_at, deleted_at) VALUES(?,?,?,?,?)", (ROOM, FID, "", OLD, OLD), write=True)
sql("INSERT INTO tchat_msgs(room_id, user_id, body, created_at) VALUES(?,?,?,?)", (ROOM, FID, "Hello", OLD), write=True)
# 2.152.0 (#2165, review C-H2): an old tombstone that opened a thread with a live reply stays (the reply needs it)
sql("INSERT INTO tchat_msgs(room_id, user_id, body, created_at, deleted_at) VALUES(?,?,?,?,?)", (ROOM, FID, "", OLD, OLD), write=True)
TROOT = one("SELECT MAX(id) FROM tchat_msgs WHERE room_id=?", (ROOM,))
sql("INSERT INTO tchat_msgs(room_id, user_id, body, created_at, thread_of) VALUES(?,?,?,?,?)", (ROOM, ALICE, "A reply", OLD, TROOT), write=True)

# comments: an emptied row of a deleted comment
T = Fr.post(B + "/api/tasks", json={"title": "Invented task"}).json()["id"]
check(Fr.post(B + f"/api/tasks/{T}/comments", json={"body": "First thought"}).ok, "setup: a comment")
CM = one("SELECT id FROM comments WHERE task_id=?", (T,))
check(Fr.delete(B + f"/api/comments/{CM}").ok, "setup: the comment deleted (emptied row)")
sql("UPDATE comments SET deleted_at=? WHERE id=?", (OLD, CM), write=True)

# 2.152.0 (#2165): no "wiki" here -- main's own run wiki/pages.py wiki_trash_tick deletes the pages with their files (below)
WANT = {"files": 1, "sheets": 1, "sheet_rows": 1, "sheet_columns": 1, "hub_mails": 1, "deals": 1, "series": 1,
        "chat_tombstones": 1, "comments": 1}

# ---- the switch off: nothing goes, the numbers are reported
out = in_app("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))")
check("counts" in out, "dry run ran " + out[-600:])
st = retention("trash")
last = (st or {}).get("last") or {}
check(st and not st["on"] and st["days"] == 30 and last.get("purged") is False, f"retention: trash off, 30 days, dry run: {st}")
check(all((last.get("counts") or {}).get(k) == v for k, v in WANT.items()), f"dry run counts per area: {last.get('counts')}")
check(one("SELECT COUNT(*) FROM fs_nodes WHERE id=?", (F_OLD,)) == 1 and os.path.isfile(P_OLD), "dry run: the old file and its stored file stay")
check(one("SELECT COUNT(*) FROM wiki_pages WHERE id=?", (W_OLD,)) == 1 and one("SELECT COUNT(*) FROM sheets WHERE id=?", (S_OLD,)) == 1
      and one("SELECT COUNT(*) FROM hub_mails WHERE id=?", (HM,)) == 1 and one("SELECT COUNT(*) FROM comments WHERE id=?", (CM,)) == 1,
      "dry run: page, table, mail and comment row stay")

# ---- the switch on: gone, the fresh ones stay
out = in_app("from kalmido.files.trashpurge import tp_tick\nprint('counts', tp_tick(c, True))", env=("KALMIDO_RETENTION_PURGE=1",))
if "Traceback" in out:
    print(out[-3000:])
last = (retention("trash") or {}).get("last") or {}
check(last.get("purged") is True and all((last.get("counts") or {}).get(k) == v for k, v in WANT.items()), f"purge counts: {last}")
check(not sql("SELECT 1 FROM fs_nodes WHERE id=?", (F_OLD,)) and not sql("SELECT 1 FROM fs_versions WHERE node_id=?", (F_OLD,)),
      "files: the old node and its versions are gone")
check(not os.path.exists(P_OLD), "files: the stored file is gone from the disk")
check(sql("SELECT deleted_at IS NOT NULL FROM fs_nodes WHERE id=?", (F_NEW,)) == [(1,)], "files: deleted today stays in the trash")
check(sql("SELECT 1 FROM wiki_pages WHERE id=?", (W_OLD,)), "wiki: the trash run leaves the pages to their own run")
out = in_app("from kalmido.wiki.pages import wiki_trash_tick\nprint('wiki', wiki_trash_tick(c, True))")
check("'pages': 1" in out, "wiki: its own run deletes the old page " + out[-300:])
check(not sql("SELECT 1 FROM wiki_pages WHERE id=?", (W_OLD,)) and sql("SELECT 1 FROM wiki_pages WHERE id=?", (W_NEW,)), "wiki: old gone, fresh stays")
check(not sql("SELECT 1 FROM sheets WHERE id=?", (S_OLD,)) and not sql("SELECT 1 FROM sheet_cells WHERE sheet_id=?", (S_OLD,)), "tables: the old table and its cells gone")
check(not sql("SELECT 1 FROM sheet_rows WHERE id=?", (ROW,)) and not sql("SELECT 1 FROM sheet_columns WHERE id=?", (COL,))
      and sql("SELECT 1 FROM sheets WHERE id=? AND deleted_at IS NULL", (S_LIVE,)), "tables: the deleted row / column gone, the live table stays")
r = Fr.get(B + f"/api/sheets/{S_LIVE}")
check(r.ok, "tables: the live table still opens " + r.text[:120])
check(not os.path.exists(TF_PATH) and not sql("SELECT 1 FROM sheet_files WHERE id=?", (TF,))
      and not sql("SELECT 1 FROM file_text WHERE kind='sheet' AND ref_id=?", (TF,))
      and not sql("SELECT 1 FROM upload_scan WHERE kind='sheet' AND ref_id=?", (TF,)), "tables: the further sheet's file, text and scan rows gone with the table")
check(sql("SELECT deleted_at IS NOT NULL FROM sheet_files WHERE id=?", (RF,)) == [(1,)], "tables: the purged row's file is in the files' trash")
check(sql("SELECT deleted_at IS NULL FROM sheet_files WHERE id=?", (KF,)) == [(1,)], "tables: the live row's file stays")
check(not sql("SELECT 1 FROM hub_mails WHERE id=?", (HM,)) and not sql("SELECT 1 FROM hub_words WHERE mail_id=?", (HM,)), "hub mail: row and word index gone")
check(sql("SELECT deleted_at IS NOT NULL FROM fs_nodes WHERE id=?", (HF,)) == [(1,)], "hub mail: its folder is in the file store's trash now")
check(sql("SELECT 1 FROM hub_mails WHERE message_id='fresh-1@example.com'"), "hub mail: deleted today stays")
check(sql("SELECT title FROM office_deals WHERE org_id=?", (ORG,)) == [("Live deal",)], "pipeline: the old deal gone, the live one stays")
check(not sql("SELECT 1 FROM office_inv_series WHERE org_id=?", (ORG,)), "invoice series: gone")
# 2.152.0 (#2165, review C-H2): the room holds a thread now (its tombstone and reply are checked below)
check(sql("SELECT body FROM tchat_msgs WHERE room_id=? AND id<>? AND thread_of IS NULL", (ROOM, TROOT)) == [("Hello",)],
      "team chat: the tombstone gone, the live message stays")
check(sql("SELECT deleted_at IS NOT NULL FROM tchat_msgs WHERE id=?", (TROOT,)) == [(1,)]
      and sql("SELECT body FROM tchat_msgs WHERE thread_of=?", (TROOT,)) == [("A reply",)], "team chat: a thread's tombstone stays with its live reply")
check(not sql("SELECT 1 FROM comments WHERE id=?", (CM,)) and sql("SELECT 1 FROM tasks WHERE id=?", (T,)), "comments: the emptied row gone, the task stays")

# ================================================================== #2172 backups
# 2.186.0 (#2602): the cap of 52 weeks holds only with the switch KALMIDO_PURGE_BACKUPS (p2186_c_retention covers it);
# this server runs without it: the stored value stays
r = A.patch(B + "/api/admin/backups", json={"keep_weekly": 100})
j = A.get(B + "/api/admin/backups").json()
check(r.ok and j["keep_weekly"] == 100 and j.get("keep_weekly_max") is None, f"keep_weekly 100 stays without the switch: {r.status_code} {j.get('keep_weekly')}")
sql("UPDATE settings SET value='300' WHERE key='bk_keep_weekly'", write=True)
check(A.get(B + "/api/admin/backups").json()["keep_weekly"] == 300, "a stored older value (300 weeks) stays without the switch")
check(A.patch(B + "/api/admin/backups", json={"keep_weekly": 600}).status_code == 400, "above the old limit: still refused")
check(j.get("encrypt_required") is False and not j["encrypt"], "encryption: not required by default (self-hosted)")

# list header picture in the archive
LID = A.post(B + "/api/lists", json={"name": "Header list"}).json()["id"]
HD = os.path.join(DATA, "attachments", "listheads")
os.makedirs(HD, exist_ok=True)
HEAD = f"l{LID}-a1b2c3.jpg"
with open(os.path.join(HD, HEAD), "wb") as f:
    f.write(b"\xff\xd8\xff invented picture")
# 2.152.0 (#2172, review C-H3): table file cells, team chat files and bookmark pictures go into the archive too
MORE = ("attachments/sheets/9001/a1b2c3-cell.pdf", "attachments/tchat/9002/a1b2c3-chat.png", "attachments/bookmarks/9003-a1b2c3.jpg")
for m in MORE:
    os.makedirs(os.path.dirname(os.path.join(DATA, m)), exist_ok=True)
    with open(os.path.join(DATA, m), "wb") as f:
        f.write(b"invented bytes")
GOOD = backup_now()
with zipfile.ZipFile(os.path.join(BK, GOOD)) as z:
    names = set(z.namelist())
check(f"attachments/listheads/{HEAD}" in names, f"listheads in the archive ({len(names)} members)")
check(all(m in names for m in MORE), f"table / team chat / bookmark files in the archive: {[m for m in MORE if m not in names]}")

# encryption required, no passphrase: no backup
n0 = len(os.listdir(BK))
out = in_app("from kalmido.admin.backup import BackupError, bk_create\ntry:\n    bk_create('manual', c)\nexcept BackupError as e:\n    print('code', e.code)",
             env=("KALMIDO_BACKUP_ENCRYPT_REQUIRED=1",))
check("code encrypt_required" in out and len(os.listdir(BK)) == n0, "KALMIDO_BACKUP_ENCRYPT_REQUIRED=1 without a passphrase: refused, no file " + out[-300:])

# safety backups older than 30 days
TZ = ZoneInfo("Europe/Berlin")  # the container's zone (start.sh): backup names are local time
fake = []
for d in (45, 40, 2):
    t = (testclock.now() - timedelta(days=d)).replace(hour=12, minute=0, second=0)
    fake.append(f"kalmido-backup-{t.strftime('%Y%m%d-%H%M%S')}-safety.zip")
    with open(os.path.join(BK, fake[-1]), "wb") as f:
        f.write(open(os.path.join(BK, GOOD), "rb").read())
out = in_app("from kalmido.admin.backup import bk_prune\nprint('gone', bk_prune(c))\nc.commit()")
st = retention("backups")
check(all(os.path.exists(os.path.join(BK, n)) for n in fake), "switch off: the old safety backups stay " + out[-300:])
check(st and (st.get("last") or {}).get("counts") == {"safety": 2} and st["last"]["purged"] is False, f"switch off: 2 counted: {st}")
out = in_app("from kalmido.admin.backup import bk_prune\nprint('gone', bk_prune(c))\nc.commit()", env=("KALMIDO_RETENTION_PURGE=1",))
check(not os.path.exists(os.path.join(BK, fake[0])) and not os.path.exists(os.path.join(BK, fake[1])) and os.path.exists(os.path.join(BK, fake[2])),
      "switch on: the two older than 30 days are gone, the young one stays " + out[-300:])
check(os.path.exists(os.path.join(BK, GOOD)), "the normal backup of today stays")
os.remove(os.path.join(BK, fake[2]))

# the journal of deleted accounts + restore
for u in ("gina", "hugo"):
    assert A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"}).ok
GINA = one("SELECT id FROM users WHERE username='gina'")
HUGO = one("SELECT id FROM users WHERE username='hugo'")
Hu = sess("hugo")
HL = Hu.post(B + "/api/lists", json={"name": "Hugo's project"}).json()["id"]
# 2.152.0 review F7: an account deleted in the last 7 days is only disabled by a restore; gina is an old account deleted
# 10 days ago (created_at and the journal row moved back), ida one deleted today
OLD30 = (testclock.now().astimezone(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
sql("UPDATE users SET created_at=? WHERE id=?", (OLD30, GINA), write=True)
assert A.post(B + "/api/users", json={"username": "ida", "display_name": "Ida", "password": "password123", "email": "ida@example.com"}).ok
IDA = one("SELECT id FROM users WHERE username='ida'")
WITH = backup_now()
check(WITH and WITH != GOOD, f"the backup with gina and hugo: {WITH}")
check(A.delete(B + f"/api/users/{GINA}").ok, "gina deleted")
r = A.delete(B + f"/api/users/{HUGO}", params={"lists": "delete", "confirm": "hugo"})
check(r.ok, "hugo deleted with his list " + r.text[:160])
check(A.delete(B + f"/api/users/{IDA}").ok, "ida deleted")
sql("UPDATE deleted_accounts SET at=? WHERE user_id=?", ((testclock.now().astimezone(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds"), GINA), write=True)
jr = sql("SELECT user_id, email_hash, username_hash FROM deleted_accounts WHERE user_id IN (?, ?) ORDER BY id", (GINA, HUGO))
check([x[0] for x in jr] == [GINA, HUGO] and all(len(x[1]) == 64 and len(x[2]) == 64 for x in jr), f"journal: two rows of hashes {jr}")
check(not sql("SELECT 1 FROM deleted_accounts WHERE email_hash LIKE '%example%' OR username_hash IN ('gina', 'hugo')"), "journal: no plain text")
r = A.post(B + "/api/admin/backups/restore", json={"name": WITH, "confirm": "RESTORE"})
if not r.ok:
    app_log()
j = r.json() if r.ok else {}
# 2.186.0 (#2602): the recently deleted (ida) and the owners of projects (hugo) are counted apart as well
check(r.ok and j.get("deleted_again") == {"deleted": 1, "disabled": 2, "owners": 1, "recent": 1}, f"restored: gina deleted again, hugo + ida disabled: {r.text[:300]}")
check(sql("SELECT disabled FROM users WHERE id=?", (IDA,)) == [(1,)], "review F7: ida (deleted today) is back disabled, not deleted again")
check(not sql("SELECT 1 FROM users WHERE id=?", (GINA,)), "gina is gone again")
check(sql("SELECT disabled FROM users WHERE id=?", (HUGO,)) == [(1,)] and sql("SELECT 1 FROM lists WHERE id=?", (HL,)),
      "hugo (owns a list) is back disabled, his list waits for the admin")
check([x[0] for x in sql("SELECT user_id FROM deleted_accounts ORDER BY id")] == [GINA, HUGO, IDA], "the journal survived the restore")
check(requests.post(B + "/api/auth/login", headers=H, json={"username": "gina", "password": "password123"}).status_code in (401, 403),
      "gina cannot log in")

print(f"p2103_b_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
