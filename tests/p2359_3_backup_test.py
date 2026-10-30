#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.359.3: the backup checks of package 2.359.3, each against a real server.
 - #2945: pg_dump older than the database server: "Back up now" stops with its own code, Admin > Server (about) and an admin
   alert name it; with a matching pg_dump everything is clear again. KALMIDO_TEST_PG_DUMP_VERSION plays the older tool.
 - #2893: a backup whose organisation / account keys do not open with this server's key is refused before anything changes
   (verify warns); KALMIDO_SECRET_KEY_CHANGED=1 lets it through with a warning; a backup without such keys but with another
   fingerprint only warns.
 - #2510: an existing install without a server key keeps starting and the admins get an alert; KALMIDO_NO_SECRET_KEY=1 = none.
freelancer-matrix: backup (instance-wide admin function, no organisation involved)
usage: p2359_3_backup_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time

import dbx as dbxm
from kt import FAILS, OKS, check, sess, su_get

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
BASE = ["-e KALMIDO_BACKUP_TICK=1", "-e KALMIDO_BACKUPS=1"]


def start(extra=(), **env):
    e = dict(os.environ, KALMIDO_ADMIN_ALERTS="1", EXTRA=" ".join(BASE + list(extra)), **env)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    return r.returncode == 0


def until_done(s):
    j, t0 = {}, time.time()
    while time.time() - t0 < 60:  # until the run has ended with a result
        j = s.get(B + "/api/admin/backups").json()
        if not j["running"]:
            return j
        time.sleep(0.2)
    return j


def wait_alert(s, word, wait=75):
    t0 = time.time()
    while time.time() - t0 < wait:
        if word in str(s.get(B + "/api/admin/alerts").json().get("items")):
            return True
        time.sleep(0.5)
    return False


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-300:]


# ---- #2945
assert start(), "first start"
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
check(A.get(B + "/api/about").json().get("backup_tools_problem") == "", "#2945: the real pg_dump fits the server, no message")
res = in_app("from kalmido.admin.backup import bk_tools_majors\nfrom kalmido.core.db import connect\nc = connect()\nprint(json.dumps(bk_tools_majors(c)))\nc.close()")
check(res == "[17, 17]", f"#2945: the versions of the real pg_dump and the server are read: {res}")
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, f"#2945: back up now accepted ({r.status_code})")
j = until_done(A)
check(not j.get("last_error") and len(j.get("items", [])) == 1, f"#2945: the real tools write a backup: {j.get('last_error')}")

assert start(["-e KALMIDO_TEST_PG_DUMP_VERSION=16.4"], KEEP="1"), "start with the older tool"
A = sess("alice")
ab = A.get(B + "/api/about").json()
check(str(ab.get("backup_tools_problem", "")).startswith("16|"), f"#2945: Admin > Server names the older pg_dump from the start on: {ab.get('backup_tools_problem')}")
check(sess().get(B + "/api/about").json().get("backup_tools_problem") is None, "#2945: only admins see it")
check(wait_alert(A, "pg_dump 16"), "#2945: an admin alert names it at the start")
before = len(A.get(B + "/api/admin/backups").json()["items"])
A.post(B + "/api/admin/backups")
j = until_done(A)
check("pg_dump 16" in (j.get("last_error") or "") and len(j["items"]) == before, f"#2945: the backup stops with the clear message, nothing written: {j.get('last_error')}")

assert start(KEEP="1"), "start with the real tool again"
A = sess("alice")
check(A.get(B + "/api/about").json().get("backup_tools_problem") == "", "#2945: the next start with a fitting tool clears the message")



# ---- #2893
K1, K2 = (base64.b64encode(os.urandom(32)).decode() for _ in range(2))


def key_start(key, changed="", keep=False):
    return start([f"-e KALMIDO_SECRET_KEY={key}"], KALMIDO_SECRET_KEY_CHANGED=changed, KALMIDO_NO_SECRET_KEY="", **({"KEEP": "1"} if keep else {}))


def first_admin():
    assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
    s = sess("alice")
    s.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
    return s


def backup_bytes(s):
    assert s.post(B + "/api/admin/backups").status_code == 202
    j = until_done(s)
    assert j["items"], j
    name = j["items"][0]["name"]
    return name, su_get(s, B + f"/api/admin/backups/{name}/download").content


def upload(s, data):
    r = s.post(B + "/api/admin/backups/upload", data=data, headers={"Content-Type": "application/octet-stream"})
    assert r.ok, r.text
    return r.json()["upload"]


def restore(s, **b):
    return s.post(B + "/api/admin/backups/restore", json={"password": "password123", "confirm": "RESTORE", **b})


def verify(s, name):
    return s.post(B + f"/api/admin/backups/{name}/verify", json={})


def wipe_keys():
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        c.execute("DELETE FROM org_keys")
        c.execute("DELETE FROM user_keys")
        c.commit()
    finally:
        c.close()


assert key_start(K1), "the server with the first key"
A = first_admin()
me = A.get(B + "/api/state").json()["me"]["id"]
org = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": me}).json()["id"]
res = in_app(f"from kalmido.core import orgcrypt as oc\nfrom kalmido.core.pg import system_ctx\nc = app.connect()\nwith system_ctx(c):\n    oc.oc_key(c, {org})\n    c.commit()\nprint('ok')")
check(res == "ok", f"#2893: the organisation has a key {res}")
name, sealed = backup_bytes(A)
r = verify(A, name)
check(r.ok and r.json().get("key_warning") == "", f"#2893: verify with the same key: no warning {r.text[:200]}")
r = restore(A, name=name)
check(r.ok and r.json().get("key_warning") == "", f"#2893: restore with the same key: no warning {r.text[:200]}")

assert key_start(K2), "a fresh server with another key"
A = first_admin()
before = len(A.get(B + "/api/admin/backups").json()["items"])
A.post(B + "/api/lists", json={"name": "Stays here"})
up = upload(A, sealed)
r = verify(A, up)
check(r.ok and "another server key" in r.json().get("key_warning", ""), f"#2893: verify warns about the other key: {r.text[:200]}")
r = restore(A, upload=up)
check(r.status_code == 400 and r.json().get("code") == "server_key" and "Nothing was changed" in r.json().get("error", ""), f"#2893: another key: refused {r.status_code} {r.text[:200]}")
st = A.get(B + "/api/state")
check(st.ok and any(x["name"] == "Stays here" for x in st.json()["lists"]), "#2893: nothing changed: the session and the data of this server are there")
check(len(A.get(B + "/api/admin/backups").json()["items"]) == before, "#2893: refused before the safety backup")

assert key_start(K2, changed="1", keep=True), "the switch for a key changed on purpose"
A = sess("alice")
r = restore(A, upload=upload(A, sealed))
check(r.ok and "another server key" in r.json().get("key_warning", ""), f"#2893: KALMIDO_SECRET_KEY_CHANGED=1: restored, with a warning: {r.text[:200]}")

assert key_start(K1), "a server without sealed keys"
A = first_admin()
wipe_keys()
name, plain = backup_bytes(A)
r = verify(A, name)
check(r.ok and r.json().get("key_warning") == "", f"#2893: no sealed keys, same fingerprint: no warning {r.text[:200]}")
assert key_start(K2), "a fresh server with another key again"
A = first_admin()
r = restore(A, upload=upload(A, plain))
check(r.ok and "may come from another server key" in r.json().get("key_warning", ""), f"#2893: no sealed keys, another fingerprint: restored with a warning: {r.text[:200]}")


# ---- #2510
assert start(), "without a key, decided on purpose"
A = first_admin()
assert start(KEEP="1"), "again"
A = sess("alice")
check(not wait_alert(A, "no access token can be stored", 35), "#2510: KALMIDO_NO_SECRET_KEY=1: no alert")
assert start(KEEP="1", KALMIDO_NO_SECRET_KEY=""), "an existing install without a key still starts"
A = sess("alice")
check(wait_alert(A, "no access token can be stored"), "#2510: an existing install without a key: the admins get an alert")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
