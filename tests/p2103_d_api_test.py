#!/usr/bin/env python3
"""2.103.0 API tests, part D (#2170 #2171 #2173 #2175), own container (fresh server). Invented accounts only (example.com).
tenant-matrix: agent
freelancer-matrix: agents
 - #2170 newsletter: an unsubscription survives deleting the contact and a re-import ("yes" on the same address stays
   "unsub"); an older unsub without a list entry is remembered when the contact is deleted; consent events land in the
   consent log (hash only)
 - #2171 logs: an old activity row goes only with the switch (the dry run counts it, GET /api/admin/retention); an expired
   session goes without the switch
 - #2173 files: a failing unlink is counted and queued; an old orphan file goes only with the switch, a young one and a
   referenced one stay; version 21 of a file replaces version 1 (switch); the undo of an account import takes the
   attachment files along; a subtask in a foreign list stays alive there, detached, when its parent is deleted for good
   (2.103.0 review F2: whoever deletes the parent must not remove work of a list they do not own)
 - #2175 agent chat: own message / whole history deleted for good with the files; another person's conversation 404
usage: p2103_d_api_test.py <datadir>      (P2103D_NOSTART=1: a running server on KALMIDO_TEST_PORT)
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
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


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
    """Runs python code inside the app container (the watchdog runs call the functions directly)."""
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


if os.environ.get("P2103D_NOSTART") != "1":
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
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
GID, Gr = freelancer(B, A, "gina")
ALICE = A.get(B + "/api/state").json()["me"]["id"]


def retention(kind):
    return (A.get(B + "/api/admin/retention").json().get("kinds") or {}).get(kind, {}).get("last") or {}


# ================================================================== #2170 the suppression list
r = Fr.post(B + "/api/books", json={"name": "Clients", "org_id": None})
BK = r.json()["id"]


def contact(fn, email):
    r = Fr.post(B + "/api/contacts", json={"book_id": BK, "fn": fn, "emails": [{"value": email}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def status(cid):
    return Fr.get(B + f"/api/contacts/{cid}").json()["newsletter"]["status"]


C1 = contact("Anna Alpha", "anna.nl@example.com")
r = Fr.put(B + "/api/newsletter/consent", json={"ids": [C1], "status": "yes", "source": "Sign-up form"})
check(r.ok and r.json()["changed"] == [C1], f"#2170: consent given {r.text[:150]}")
log = sql("SELECT event, source FROM nl_consent_log WHERE email_hash=?", (hsh("anna.nl@example.com"),))
check(log == [("consent", "Sign-up form")], f"#2170: the consent is logged by hash {log}")
check("anna.nl" not in json.dumps(sql("SELECT * FROM nl_consent_log")), "#2170: no address in the log")
box(f"from kalmido.newsletter.sync import nwl_set_status\nnwl_set_status(c, {C1}, 'unsub', 'service')")  # the service reports it
check(status(C1) == "unsub", "#2170: unsubscribed")
check(sql("SELECT kind FROM nl_suppress WHERE email_hash=?", (hsh("anna.nl@example.com"),)) == [("unsub",)], "#2170: the hash is on the suppression list")
check(Fr.delete(B + f"/api/contacts/{C1}").ok, "#2170: the contact is deleted")
check(sql("SELECT COUNT(*) FROM nl_suppress WHERE email_hash=?", (hsh("anna.nl@example.com"),))[0][0] == 1, "#2170: the suppression stays after the delete")
C1b = contact("Anna again", "Anna.NL@Example.com")  # re-import, other spelling
r = Fr.put(B + "/api/newsletter/consent", json={"ids": [C1b], "status": "yes", "source": "Import 2026"})
check(r.ok and r.json()["kept"] == 1 and r.json()["changed"] == [], f"#2170: yes on a suppressed address is refused {r.text[:150]}")
check(status(C1b) == "unsub", "#2170: ... the new contact is unsub")
# an unsub from before the list existed: remembered when the contact is deleted
C2 = contact("Ben Beta", "ben.nl@example.com")
sql("UPDATE contacts SET nl_status='bounce' WHERE id=?", (C2,), write=True)
check(sql("SELECT COUNT(*) FROM nl_suppress WHERE email_hash=?", (hsh("ben.nl@example.com"),))[0][0] == 0, "#2170: (setup) no entry yet")
Fr.delete(B + f"/api/contacts/{C2}")
check(sql("SELECT kind FROM nl_suppress WHERE email_hash=?", (hsh("ben.nl@example.com"),)) == [("bounce",)], "#2170: an older bounce is remembered on delete")
check(sql("SELECT ws FROM nl_suppress WHERE email_hash=?", (hsh("ben.nl@example.com"),)) == [(f"u{FID}",)], "#2170: per workspace (the person's own)")
# merge: the merged-away unsub contact leaves its entry
C3 = contact("Cleo One", "cleo.nl@example.com")
C4 = contact("Cleo Two", "cleo.nl@example.com")
sql("UPDATE contacts SET nl_status='unsub' WHERE id=?", (C4,), write=True)
r = Fr.post(B + "/api/contacts/merge", json={"target": C3, "ids": [C3, C4]})
check(r.ok or r.status_code == 400, f"(merge answers {r.status_code})")
if r.ok:
    check(sql("SELECT COUNT(*) FROM nl_suppress WHERE email_hash=?", (hsh("cleo.nl@example.com"),))[0][0] == 1, "#2170: a merge keeps the unsubscription")
other = Gr.get(B + f"/api/contacts/{C1b}")
check(other.status_code in (403, 404), "#2170: another person does not see the contact")

# ================================================================== #2171 logs and credentials
T0 = Fr.post(B + "/api/tasks", json={"title": "Log task"}).json()["id"]
sql("INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)", (T0, FID, "title", "{}", ago(500)), write=True)
sql("INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)", (T0, FID, "title", "{}", ago(1)), write=True)
sql("INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES(?,?,?,?)", ("dead" * 16, FID, ago(40), ago(10)), write=True)
n_old = sql("SELECT COUNT(*) FROM activity WHERE task_id=? AND created_at<?", (T0, ago(400)))[0][0]
check(n_old == 1, "#2171: (setup) one old activity row")
out = box("from kalmido.admin.dataretention import lgc_tick\nprint('rows', lgc_tick(c, True))")
check("rows" in out, "#2171: the run works " + out[-300:])
check(sql("SELECT COUNT(*) FROM activity WHERE task_id=? AND created_at<?", (T0, ago(400)))[0][0] == 1, "#2171: switch off: the old row stays")
check(sql("SELECT COUNT(*) FROM sessions WHERE token_hash=?", ("dead" * 16,))[0][0] == 0, "#2171: an expired session goes without the switch")
last = retention("logs")
check(last.get("purged") is False and (last.get("counts") or {}).get("activity", 0) >= 1, f"#2171: the dry run counts it {last}")
out = box("from kalmido.admin.dataretention import lgc_tick\nprint('rows', lgc_tick(c, True))", ("KALMIDO_PURGE_LOGS=1",))
check(sql("SELECT COUNT(*) FROM activity WHERE task_id=? AND created_at<?", (T0, ago(400)))[0][0] == 0, "#2171: switch on: the old row is gone " + out[-200:])
check(sql("SELECT COUNT(*) FROM activity WHERE task_id=? AND created_at>?", (T0, ago(5)))[0][0] >= 1, "#2171: ... the young row stays")
check(retention("logs").get("purged") is True, "#2171: the report says purged")

# ================================================================== #2173 files
TF = Fr.post(B + "/api/tasks", json={"title": "With file"}).json()["id"]
r = Fr.post(B + f"/api/tasks/{TF}/attachments", files={"file": ("keep.txt", b"keep\n" * 20, "text/plain")})
check(r.ok, f"#2173: (setup) attachment {r.status_code}")
rel_keep = sql("SELECT path FROM attachments WHERE task_id=?", (TF,))[0][0]
d_rel = os.path.dirname(rel_keep)
mk = ("import os, time\nfrom kalmido.core.config import ATT_DIR\nd = os.path.join(ATT_DIR, %r)\nos.makedirs(d, exist_ok=True)\n"
      "p = os.path.join(d, %%r)\nopen(p, 'wb').write(b'x')\nt = time.time() - %%d\nos.utime(p, (t, t))\n") % d_rel
box(mk % ("orphan-old.bin", 3 * 86400))
box(mk % ("orphan-young.bin", 0))
box("import os, time\nfrom kalmido.core.config import ATT_DIR\np = os.path.join(ATT_DIR, %r)\nt = time.time() - 5 * 86400\nos.utime(p, (t, t))" % rel_keep)
P = lambda name: os.path.join(DATA, "attachments", d_rel, name)
check(os.path.exists(P("orphan-old.bin")) and os.path.exists(P("orphan-young.bin")), "#2173: (setup) the orphan files exist")
box("from kalmido.admin.dataretention import orf_tick\nprint(orf_tick(c, True))")
check(os.path.exists(P("orphan-old.bin")), "#2173: switch off: the old orphan stays")
last = retention("files")
check(last.get("purged") is False and (last.get("counts") or {}).get("orphans", 0) >= 1, f"#2173: the dry run counts it {last}")
box("from kalmido.admin.dataretention import orf_tick\nprint(orf_tick(c, True))", ("KALMIDO_PURGE_FILES=1",))
check(not os.path.exists(P("orphan-old.bin")), "#2173: switch on: the old orphan is gone")
check(os.path.exists(P("orphan-young.bin")), "#2173: ... a young one stays")
check(os.path.exists(os.path.join(DATA, "attachments", rel_keep)), "#2173: ... a referenced old file stays")

# a failing unlink is counted and queued (a directory where the file should be: remove() fails with an OSError)
out = box("import os\nfrom kalmido.core.config import ATT_DIR\nfrom kalmido.core.serializers import unlink_files\n"
          "os.makedirs(os.path.join(ATT_DIR, 'zz-stuck', 'f.bin'), exist_ok=True)\nunlink_files(['zz-stuck/f.bin', 'zz-gone/none.bin'])\n"
          "from kalmido.core.db import gsetting\nprint('queue', gsetting(c, 'unlink_retry'))")
check("zz-stuck/f.bin" in out and "zz-gone" not in out, "#2173: the failing path is queued, a missing file is no failure " + out[-300:])
out = box("from kalmido.admin.dataretention import orf_tick\norf_tick(c, True)\nfrom kalmido.core.db import gsetting\nprint('queue', gsetting(c, 'unlink_retry'))")
check("zz-stuck/f.bin" in out, "#2173: the sweep tries again and keeps what still fails " + out[-200:])
box("import os, shutil\nfrom kalmido.core.config import ATT_DIR\nshutil.rmtree(os.path.join(ATT_DIR, 'zz-stuck'), ignore_errors=True)\nfrom kalmido.admin.dataretention import orf_tick\norf_tick(c, True)")
out = box("from kalmido.core.db import gsetting\nprint('queue', gsetting(c, 'unlink_retry'))")
check("zz-stuck" not in out, "#2173: ... and drops it when the file is gone")

# versions: 21 versions of a file -> 20 (switch on)
up = Fr.post(B + "/api/files/upload", files={"file": ("v.txt", b"v1")})
check(up.ok, f"#2173: (setup) a file {up.status_code} {up.text[:100]}")
NID = (up.json().get("items") or [{}])[0].get("id") if up.ok else None
nv = 1
for i in range(2, 22):
    r = Fr.post(B + "/api/files/upload", files={"file": ("v.txt", f"v{i}".encode())}) if NID else None
    if r is None or not r.ok:
        break
    nv += 1
cnt = sql("SELECT COUNT(*) FROM fs_versions WHERE node_id=?", (NID,))[0][0] if NID else 0
check(nv == 21 and cnt == 21, f"#2173: switch off at upload: all {nv} uploads stay as versions ({cnt})")
if NID and cnt >= 20:
    if cnt == 21:
        box("from kalmido.admin.dataretention import orf_prune_versions\nprint(orf_prune_versions(c, %d, False))" % NID)
        check(sql("SELECT COUNT(*) FROM fs_versions WHERE node_id=?", (NID,))[0][0] == 21, "#2173: switch off: the 21st version stays (counted only)")
    box("from kalmido.admin.dataretention import orf_prune_versions\nprint(orf_prune_versions(c, %d, True))" % NID)
    vs = [x[0] for x in sql("SELECT no FROM fs_versions WHERE node_id=? ORDER BY no", (NID,))]
    check(len(vs) == 20 and vs[-1] == max(vs) and 1 not in vs, f"#2173: version 21 replaces version 1 {vs[:3]}..{vs[-1:]}")

# the undo of an account import takes the attachment files along
L2 = Fr.post(B + "/api/lists", json={"name": "Imported", "org_id": None}).json()["id"]
TI = Fr.post(B + "/api/tasks", json={"title": "Imported task", "list_id": L2}).json()["id"]
Fr.post(B + f"/api/tasks/{TI}/attachments", files={"file": ("imp.txt", b"imp\n" * 10, "text/plain")})
rel_imp = sql("SELECT path FROM attachments WHERE task_id=?", (TI,))[0][0]
sql("UPDATE tasks SET tt_id='kalmido:1:1' WHERE id=?", (TI,), write=True)
sql("INSERT INTO imports(user_id, source, file_name, created, report, created_at) VALUES(?,?,?,?,?,?)",
    (FID, "Kalmido", "export.zip", json.dumps({"lists": [L2], "tasks": [TI]}), "{}", ago(0)), write=True)
iid = sql("SELECT MAX(id) FROM imports WHERE user_id=?", (FID,))[0][0]
check(os.path.exists(os.path.join(DATA, "attachments", rel_imp)), "#2173: (setup) the imported attachment exists")
r = Fr.post(B + f"/api/imports/{iid}/undo")
check(r.ok, f"#2173: undo of the import {r.status_code} {r.text[:150]}")
check(not os.path.exists(os.path.join(DATA, "attachments", rel_imp)), "#2173: ... its attachment file is gone from the disk")

# 2.103.0 review F2: a subtask in a foreign list stays in its list (detached, not in the trash) when the parent is deleted for good
TP = Fr.post(B + "/api/tasks", json={"title": "Parent"}).json()["id"]
TS = A.post(B + "/api/tasks", json={"title": "Foreign subtask"}).json()["id"]
sql("UPDATE tasks SET parent_id=? WHERE id=?", (TP, TS), write=True)
r = Fr.delete(B + f"/api/tasks/{TP}?hard=1")
check(r.ok, f"#2173: the parent is deleted for good {r.status_code}")
row = sql("SELECT parent_id, deleted_at FROM tasks WHERE id=?", (TS,))
check(row and row[0][0] is None and row[0][1] is None, f"#2173 review F2: the foreign subtask stays in its list, detached {row}")
r = A.post(B + f"/api/tasks/{TS}/restore")
check(r.ok and sql("SELECT deleted_at FROM tasks WHERE id=?", (TS,))[0][0] is None, "#2173: its owner restores it")

# ================================================================== #2175 the agent chat
assert A.put(B + "/api/admin/agent-policy", json={"user_agents": True, "max_per_user": 2}).ok
ag = Fr.post(B + "/api/my/agents", json={"username": "fridabot2", "display_name": "Frida's bot", "scopes": ["read", "tasks:write", "comments"]}).json()
assert "id" in ag, ("my/agents answered", ag)
AID, AGH = ag["id"], {"Authorization": "Bearer " + ag["token"], **H}
m1 = Fr.post(B + f"/api/agents/{AID}/chat", json={"body": "First question"}).json()["id"]
r = Fr.post(B + f"/api/agents/{AID}/chat", data={"body": "With a picture"}, files={"file": ("pic.txt", b"picture\n" * 5, "text/plain")})
m2 = r.json()["id"]
rr = requests.post(B + f"/api/v1/agent/chats/{FID}", headers=AGH, json={"body": "The answer"})
check(rr.status_code in (200, 201), f"#2175: (setup) the agent answers {rr.status_code} {rr.text[:100]}")
rel_chat = sql("SELECT path FROM chat_files WHERE message_id=?", (m2,))[0][0]
check(os.path.exists(os.path.join(DATA, "attachments", rel_chat)), "#2175: (setup) the chat file exists")
other = Gr.delete(B + f"/api/agents/{AID}/chat/{m1}")
check(other.status_code in (403, 404), f"#2175: another person: {other.status_code}")
check(Gr.delete(B + f"/api/agents/{AID}/chat").status_code in (403, 404), "#2175: another person cannot delete the history")
check(sql("SELECT COUNT(*) FROM agent_chat WHERE agent_id=?", (AID,))[0][0] == 3, "#2175: ... nothing was deleted")
check(A.delete(B + f"/api/agents/{AID}/chat/{m1}").status_code in (403, 404), "#2175: not even the admin deletes into someone's conversation")
r = Fr.delete(B + f"/api/agents/{AID}/chat/{m2}")
check(r.ok, f"#2175: my message with its file {r.status_code} {r.text[:100]}")
check(not sql("SELECT 1 FROM agent_chat WHERE id=?", (m2,)) and not sql("SELECT 1 FROM chat_files WHERE message_id=?", (m2,)), "#2175: row and file row gone")
check(not os.path.exists(os.path.join(DATA, "attachments", rel_chat)), "#2175: the file left the disk")
check(Fr.delete(B + f"/api/agents/{AID}/chat/{m2}").status_code == 404, "#2175: the same again: 404")
r = Fr.delete(B + f"/api/agents/{AID}/chat")
check(r.ok and r.json().get("deleted") == 2, f"#2175: the whole history (my first message + the answer) {r.text[:100]}")
check(sql("SELECT COUNT(*) FROM agent_chat WHERE agent_id=? AND user_id=?", (AID, FID))[0][0] == 0, "#2175: the conversation is empty")
check(Fr.get(B + f"/api/agents/{AID}/chat").json().get("messages") == [], "#2175: the chat reads empty")
check(requests.delete(B + f"/api/agents/{AID}/chat", headers=H).status_code in (401, 403), "#2175: nobody signed in")

print(f"p2103_d_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
