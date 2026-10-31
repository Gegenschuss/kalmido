#!/usr/bin/env python3
"""2.186.0 API tests, part C (#2602: the clean-up runs sharpened), own container (start.sh with KALMIDO_PURGE_BACKUPS=1).
Invented accounts only (example.com); the person without an organisation (freelancer fixture) does every step.
 - orphan sweep: stored paths checked in batches (more than one batch at once), a sweep under way resumes after the folder
   it finished, the last finish survives a restart (no new sweep at once)
 - backups: with the switch the weekly backups are capped at 52 (without it: p2103_b_api)
 - newsletter: deleting an address book keeps its unsubscriptions; the private suppression rows go with the account
 - agent chat: KALMIDO_CHAT_KEEP_DAYS is applied by the daily run (dry run without the switch)
 - logs: the 400-day clean-up keeps the history row the customer portal's "your text" check reads (same answer before
   and after), other old rows go
usage: p2186_c_retention_test.py <datadir>      (P2186C_NOSTART=1: a running server on KALMIDO_TEST_PORT)
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


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


def box(code, env=()):
    """Runs python code inside the app container (each call = a fresh process, like a restart for the run state)."""
    cmd = ["docker", "exec"]
    for e in env:
        cmd += ["-e", e]
    out = subprocess.run(cmd + [CT, "python", "-c", "import app\nfrom kalmido.core.db import connect\nc = connect()\n" + code + "\nc.commit()\nc.close()"],
                         capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def hsh(mail):
    return hashlib.sha256(mail.strip().lower().encode()).hexdigest()


if os.environ.get("P2186C_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_PURGE_BACKUPS=1")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = requests.Session()
A.headers.update(H)
assert A.post(B + "/api/auth/login", json={"username": "alice", "password": "password123"}).ok
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
FID, Fr = freelancer(B, A)


def retention(kind):
    return (A.get(B + "/api/admin/retention").json().get("kinds") or {}).get(kind, {}).get("last") or {}


# ================================================================== orphan sweep
TF = Fr.post(B + "/api/tasks", json={"title": "With file"}).json()["id"]
r = Fr.post(B + f"/api/tasks/{TF}/attachments", files={"file": ("keep.txt", b"keep\n" * 20, "text/plain")})
check(r.ok, f"orphans: (setup) attachment {r.status_code}")
rel_keep = sql("SELECT path FROM attachments WHERE task_id=?", (TF,))[0][0]
# batches: 1200 unknown paths and the stored one -> only the stored one is known
out = box("from kalmido.admin.dataretention import orf_known_set, orf_path_columns, ORF_BATCH\nfrom kalmido.core.pg import system_ctx\n"
          "with system_ctx(c):\n    cols = orf_path_columns(c)\n"
          f"    got = orf_known_set(c, cols, ['900001/none-%d.bin' % i for i in range(1200)] + [{rel_keep!r}])\n"
          "print('known', sorted(got), ORF_BATCH)")
check(f"known [{rel_keep!r}] 500" in out, "orphans: the batched check finds the stored path among 1201 " + out[-300:])
mk = ("import os, time\nfrom kalmido.core.config import ATT_DIR\nd = os.path.join(ATT_DIR, %r)\nos.makedirs(d, exist_ok=True)\n"
      "p = os.path.join(d, 'orphan.bin')\nopen(p, 'wb').write(b'x')\nt = time.time() - 3 * 86400\nos.utime(p, (t, t))\n")
box(mk % "900001")
box(mk % "900002")
P = lambda sub: os.path.join(DATA, "attachments", sub, "orphan.bin")
check(os.path.exists(P("900001")) and os.path.exists(P("900002")), "orphans: (setup) two old orphan files")
# a sweep under way that finished folder 900001: the resumed sweep starts after it
box("from kalmido.core.db import gset\nimport json\ngset(c, 'orphan_sweep_pos', json.dumps({'sub': '900001', 'orphans': 4}))")
box("from kalmido.admin.dataretention import orf_tick\nprint(orf_tick(c, True))", ("KALMIDO_PURGE_FILES=1",))
check(os.path.exists(P("900001")), "orphans: the folder finished before the restart is not walked again")
check(not os.path.exists(P("900002")), "orphans: the next folder is swept (switch on)")
check(os.path.exists(os.path.join(DATA, "attachments", rel_keep)), "orphans: the stored file stays")
last = retention("files")
check((last.get("counts") or {}).get("orphans") == 5, f"orphans: the count goes on from the saved progress (4 + 1) {last}")
st = sql("SELECT key, value FROM settings WHERE key IN ('orphan_sweep_pos', 'orphan_sweep_at')")
st = dict(st)
check(not st.get("orphan_sweep_pos") and int(st.get("orphan_sweep_at") or 0) > time.time() - 600, f"orphans: progress cleared, finish saved {st}")
# a restart (fresh process, run state 0): no new sweep within the week
out = box("from kalmido.admin.dataretention import orf_tick\nprint('ran', orf_tick(c))", ("KALMIDO_PURGE_FILES=1",))
check("ran 0" in out and os.path.exists(P("900001")), "orphans: after a restart no new sweep before the week is over " + out[-200:])
box("import os, shutil\nfrom kalmido.core.config import ATT_DIR\nfor s in ('900001', '900002'):\n    shutil.rmtree(os.path.join(ATT_DIR, s), ignore_errors=True)")

# ================================================================== backups (switch on in this container)
r = A.patch(B + "/api/admin/backups", json={"keep_weekly": 100})
j = A.get(B + "/api/admin/backups").json()
check(r.ok and j["keep_weekly"] == 52 and j.get("keep_weekly_max") == 52, f"backups: with the switch 100 -> 52 {r.status_code} {j.get('keep_weekly')}")
sql("UPDATE settings SET value='300' WHERE key='bk_keep_weekly'", write=True)
check(A.get(B + "/api/admin/backups").json()["keep_weekly"] == 52, "backups: a stored older value reads as 52 with the switch")  # 2.306.0 G (#2946): switch on keeps 52

# ================================================================== newsletter suppression list
BK = Fr.post(B + "/api/books", json={"name": "Clients", "org_id": None}).json()["id"]
r = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": "Una Unsub", "emails": [{"value": "una.nl@example.com"}]})
check(r.status_code == 201, f"newsletter: (setup) contact {r.status_code}")
CU = r.json()["id"]
sql("UPDATE contacts SET nl_status='unsub' WHERE id=?", (CU,), write=True)  # an older unsub without a list entry
check(not sql("SELECT 1 FROM nl_suppress WHERE email_hash=?", (hsh("una.nl@example.com"),)), "newsletter: (setup) no entry yet")
r = Fr.delete(B + f"/api/books/{BK}")
check(r.ok, f"newsletter: the address book is deleted {r.status_code} {r.text[:120]}")
check(sql("SELECT ws, kind FROM nl_suppress WHERE email_hash=?", (hsh("una.nl@example.com"),)) == [(f"u{FID}", "unsub")],
      "newsletter: the unsubscription outlives the address book")
HID, Hr = freelancer(B, A, "hugo")
sql("INSERT INTO nl_suppress(ws, org_id, email_hash, kind, at) VALUES(?,?,?,?,?)", (f"u{HID}", None, hsh("x.nl@example.com"), "unsub", ago(1)), write=True)
r = A.delete(B + f"/api/users/{HID}")
check(r.ok, f"newsletter: (setup) the account is deleted {r.status_code} {r.text[:150]}")
if r.ok:
    check(not sql("SELECT 1 FROM nl_suppress WHERE ws=?", (f"u{HID}",)), "newsletter: the private suppression rows go with the account")
check(sql("SELECT COUNT(*) FROM nl_suppress WHERE ws=?", (f"u{FID}",))[0][0] == 1, "newsletter: another person's rows stay")

# ================================================================== agent chat day limit
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2}).ok
ag = Fr.post(B + "/api/my/agents", json={"username": "fridabot3", "display_name": "Frida's bot", "scopes": ["read"]}).json()
assert "id" in ag, ("my/agents answered", ag)
AID = ag["id"]
young = Fr.post(B + f"/api/agents/{AID}/chat", json={"body": "A new question"}).json()["id"]
sql("INSERT INTO agent_chat(agent_id, user_id, sender, body, created_at) VALUES(?,?,?,?,?)",
    (AID, FID, "user", "An old question", (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="milliseconds")), write=True)
old_n = lambda: sql("SELECT COUNT(*) FROM agent_chat WHERE agent_id=? AND body='An old question'", (AID,))[0][0]
check(old_n() == 1, "chat: (setup) one old message")
out = box("from kalmido.admin.dataretention import ckd_tick\nprint('found', ckd_tick(c, True))", ("KALMIDO_CHAT_KEEP_DAYS=30",))
check("found 1" in out and old_n() == 1, "chat: switch off: counted, the old message stays " + out[-200:])
last = retention("chat")
check(last.get("purged") is False and (last.get("counts") or {}).get("messages") == 1, f"chat: the dry run is reported {last}")
out = box("from kalmido.admin.dataretention import ckd_tick\nprint('found', ckd_tick(c, True))", ("KALMIDO_CHAT_KEEP_DAYS=30", "KALMIDO_PURGE_CHAT=1"))
check(old_n() == 0, "chat: switch on: the old message is gone without a new one arriving " + out[-200:])
check(sql("SELECT COUNT(*) FROM agent_chat WHERE id=?", (young,))[0][0] == 1, "chat: ... the young one stays")
out = box("from kalmido.admin.dataretention import ckd_tick\nprint('found', ckd_tick(c, True))", ("KALMIDO_PURGE_CHAT=1",))
check("found 0" in out, "chat: no day limit set: the run does nothing " + out[-200:])

# ================================================================== logs vs the portal's "your text" check
TP = Fr.post(B + "/api/tasks", json={"title": "Portal report", "content": "My text\n\n— Sent with the form Support"}).json()
TO = Fr.post(B + "/api/tasks", json={"title": "Plain task"}).json()["id"]
sql("INSERT INTO portal_tickets(task_id, list_id, owner_id, token, token_hash, created_at) VALUES(?,?,?,?,?,?)",
    (TP["id"], TP["list_id"], FID, "tok-2186c", "hash-2186c", ago(500)), write=True)
for tid, kind in ((TP["id"], "content"), (TP["id"], "content"), (TP["id"], "title"), (TO, "content")):
    sql("INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)", (tid, FID, kind, "{}", ago(500)), write=True)
first = sql("SELECT MIN(id) FROM activity WHERE task_id=? AND kind='content' AND created_at<?", (TP["id"], ago(400)))[0][0]
orig = ("from kalmido.team.portal import pt_original\nfrom kalmido.core.pg import system_ctx\nwith system_ctx(c):\n"
        "    p = c.execute('SELECT p.*, t.content FROM portal_tickets p JOIN tasks t ON t.id=p.task_id WHERE p.task_id=?', (%d,)).fetchone()\n"
        "    print('orig', repr(pt_original(c, p)))" % TP["id"])
before = box(orig)
check("orig ''" in before, "portal: (setup) an edited description: the page shows the title only " + before[-200:])
out = box("from kalmido.admin.dataretention import lgc_tick\nprint('rows', lgc_tick(c, True))", ("KALMIDO_PURGE_LOGS=1",))
left = sql("SELECT id, kind FROM activity WHERE task_id=? AND created_at<?", (TP["id"], ago(400)))
check(left == [(first, "content")], f"portal: the oldest edit row of the ticket stays, the others go {left} " + out[-200:])
check(not sql("SELECT 1 FROM activity WHERE task_id=? AND created_at<?", (TO, ago(400))), "logs: an old edit row of a task without a ticket goes")
# only the answer line: the process also logs its start time (migrations: start total ... ms), different on every run
answer = lambda s: [ln for ln in s.splitlines() if ln.startswith("orig ")]  # noqa: E731
after = box(orig)
check(answer(after) == answer(before), f"portal: the answer of the check is the same after the clean-up {answer(before)} / {answer(after)}")

print(f"p2186_c_retention: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
