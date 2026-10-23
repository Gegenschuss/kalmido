#!/usr/bin/env python3
"""2.190.0 API tests, part B: server key fingerprint (#2592), recovery key only when stored, private approvals in the
encryption passes, live texts of encrypted organisations, team chat files of a deleted organisation (#2496 #2561).
freelancer-matrix: office
 - #2592: a new database stores the fingerprint of its server key (kalmido_meta secret_fp, an HMAC, never the key); the same
   key starts again; another key in the key file refuses the start with a clear FATAL and the file stays where it is; the
   old key starts it again; a database without a fingerprint gets it on the next start when its organisation keys open with
   the key, refuses another key, KALMIDO_SECRET_KEY_CHANGED=1 accepts a changed key and stores its fingerprint; after a
   restore the fingerprint is set again for the current key
 - #2496: a recovery key whose row a starting rotation took over meanwhile is not handed out
 - #2561: an approval of a private project (org_id NULL) of a person without an organisation is encrypted, counted and
   decrypted by the passes of the personal office (not by another organisation's); live texts of an encrypted
   organisation never go to an embedding service on another server; the team chat files of an organisation are found for
   its final deletion
usage: p2190_b_crypto_test.py <datadir>"""
import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
SEC = DATA.rstrip("/") + "-secret2190b"  # next to the data dir, never inside it
KEYF = os.path.join(SEC, "kalmido.key")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FILE_ARGS = ("-e KALMIDO_SECRET_FILE=/secret/kalmido.key", f"-v {SEC}:/secret", "-e KALMIDO_ORGCRYPT_DELAY=0")
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall() if not write else None
        if write:
            c.execute(sql, args)
            c.commit()
        return r
    finally:
        c.close()


def fp_stored():
    r = dbx("SELECT value FROM kalmido_meta WHERE key='secret_fp'")
    return r[0][0] if r else None


def fp_of(key_b64):
    return hmac.new(base64.b64decode(key_b64.strip()), b"kalmido-server-key-fingerprint-v1", hashlib.sha256).hexdigest()[:32]


def start(keep=True, env=None):
    """start.sh with the key file; True when the server answered. The fingerprint check is on (start.sh turns it off)."""
    e = dict(os.environ, EXTRA=" ".join(FILE_ARGS), KALMIDO_SECRET_KEY_CHANGED="", KALMIDO_NO_SECRET_KEY="")
    e.pop("KEEP", None)
    if keep:
        e["KEEP"] = "1"
    e.update(env or {})
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    return r.returncode == 0


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def py(code):
    """A few lines of Python inside the container (the server's modules, its server key) -> the last JSON line."""
    r = subprocess.run(["docker", "exec", "-i", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", code], capture_output=True, text=True,
                       timeout=300)
    out = r.stdout.strip()
    try:
        return json.loads(out.splitlines()[-1])
    except (ValueError, IndexError):
        return {"err": (out[-300:] + " " + r.stderr[-600:]).strip()}


def put_key(k):
    with open(KEYF, "w") as f:
        f.write(k)
    os.chmod(KEYF, 0o600)


# ---- set-up: a new server with a key file ---------------------------------------------------------------------------------
shutil.rmtree(SEC, ignore_errors=True)
os.makedirs(SEC)
subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
assert start(keep=False), logs()[-2000:]
KEY = open(KEYF).read()
KEY2 = base64.b64encode(os.urandom(32)).decode() + "\n"
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
FRIDA, F = freelancer(B, A)

# ---- #2592: the fingerprint ---------------------------------------------------------------------------------------------
FP = fp_stored()
check(FP == fp_of(KEY) and KEY.strip() not in (FP or "") and len(FP or "") == 32,
      f"a new database stores the fingerprint of its key, not the key ({FP!r})")
j = py("import app, json\nfrom kalmido.core import orgcrypt as oc\nfrom kalmido.core.pg import system_ctx\nc = app.connect()\n"
       f"with system_ctx(c):\n    oc.oc_key(c, {ORG})\n    c.commit()\n"
       f"    print(json.dumps({{'n': c.execute('SELECT COUNT(*) FROM org_keys WHERE org_id=?', ({ORG},)).fetchone()[0]}}))")
check(j.get("n") == 1, f"the organisation has a key row {j}")
check(start(), "the same key: starts again")
put_key(KEY2)
ok = start()
lg = logs()
check(not ok and "FATAL: the server key (the key file /secret/kalmido.key) is not the one this database was used with" in lg,
      f"another key in the key file: start refused ({ok}, {lg[-400:]!r})")
check(os.path.exists(KEYF) and open(KEYF).read() == KEY2 and fp_stored() == FP, "... the key file stays, the fingerprint too")
put_key(KEY)
check(start(), "the old key back: starts")

# a database from before (no fingerprint yet)
dbx("DELETE FROM kalmido_meta WHERE key='secret_fp'", write=True)
check(start() and fp_stored() == FP, "no fingerprint yet, the organisation key opens: starts and stores it")
dbx("DELETE FROM kalmido_meta WHERE key='secret_fp'", write=True)
put_key(KEY2)
ok = start()
lg = logs()
check(not ok and "does not open the organisation or account keys of this database" in lg and fp_stored() is None,
      f"no fingerprint yet, another key: start refused, nothing stored ({ok}, {lg[-400:]!r})")
check(start(env={"KALMIDO_SECRET_KEY_CHANGED": "1"}) and fp_stored() == fp_of(KEY2),
      "KALMIDO_SECRET_KEY_CHANGED=1: the changed key starts, its fingerprint is stored")
put_key(KEY)
check(not start(), "then the earlier key: refused (the fingerprint is the new one now)")
check(start(env={"KALMIDO_SECRET_KEY_CHANGED": "1"}) and fp_stored() == FP and "KALMIDO_SECRET_KEY_CHANGED=1: the new server key is accepted" in logs(),
      "KALMIDO_SECRET_KEY_CHANGED=1 again: back to the earlier key, with a warning")
check(start(), "and a normal start after it")
check("is still set" not in logs(), "... without the switch: no reminder")
# 2.190.0 R (#2592): the switch left on = a reminder on every start, also when the key matches
check(start(env={"KALMIDO_SECRET_KEY_CHANGED": "1"}) and "KALMIDO_SECRET_KEY_CHANGED=1 is still set" in logs(),
      "KALMIDO_SECRET_KEY_CHANGED=1 left on, same key: starts with a warning")

# after a restore: the fingerprint of the backup is replaced by the current key's (its keys open with it)
j = py("import app, json\nfrom kalmido.core.config import DATABASE_URL\nfrom kalmido.core.pg import connect_direct\n"
       "from kalmido.core.db import skfp_check\nc = connect_direct(DATABASE_URL)\n"
       "c.execute(\"UPDATE kalmido_meta SET value=? WHERE key='secret_fp'\", ('f' * 32,))\nskfp_check(c, restore=True)\n"
       "v = c.execute(\"SELECT value FROM kalmido_meta WHERE key='secret_fp'\").fetchone()\nc.rollback()\nc.close()\n"
       "print(json.dumps({'fp': v[0] if v else None}))")
check(j.get("fp") == FP, f"after a restore the fingerprint is set for the current key {j}")

# ---- #2496: a recovery key is only handed out once stored ---------------------------------------------------------------
j = py(f"""import app, json
from kalmido.core import orgcrypt as oc
from kalmido.core.pg import system_ctx
c = app.connect()
COLS = ("recovery_wrapped", "recovery_secret", "recovery_shown_at", "wrapped_rot", "rot_started_at", "rotated_at")
out = {{}}
with system_ctx(c):
    sec, made = oc.rck_secret(c, {ORG}, new=True)
    out["plain"] = [sec is not None, made]
    c.rollback()
    real = oc.rck_row
    oc.rck_row = lambda c_, o: dict({{k: real(c_, o)[k] for k in COLS}}, wrapped_rot=None)  # read before the rotation began
    c.execute("UPDATE org_keys SET wrapped_rot=wrapped WHERE org_id=?", ({ORG},))
    sec, made = oc.rck_secret(c, {ORG}, new=True)
    oc.rck_row = real
    out["race"] = [sec is not None, made]
    c.rollback()
print(json.dumps(out))""")
check(j.get("plain") == [True, True], f"a new recovery key is made and stored {j}")
check(j.get("race") == [False, False], f"a rotation that began meanwhile: no recovery key handed out {j}")

# ---- #2561: approvals of a private project in the personal office's passes -------------------------------------------------
r = F.post(B + "/api/lists", json={"name": "Private Project"})
check(r.ok, f"the person without an organisation makes a private project {r.status_code}")
LID = r.json().get("id") if r.ok else 0
check(F.get(B + "/api/state").ok, "the person without an organisation reads the app (office on)")
j = py(f"""import app, json
from kalmido.admin import orgcrypt_cli as cl
from kalmido.core import orgcrypt as oc
from kalmido.core.pg import system_ctx
from kalmido.office.model import pb_personal
from kalmido.office.signoff import sig_dec
c = app.connect()
poid = pb_personal(c, {FRIDA})
with system_ctx(c):
    sid = c.execute("INSERT INTO office_signoffs(org_id, kind, list_id, title, token_hash, token, signer_name, signer_email, created_at) "
                    "VALUES(NULL, 'acceptance', ?, 'Approval', ?, '', 'Erika Example', 'erika@example.com', '2026-10-23T10:00:00+00:00') RETURNING id",
                    ({LID}, 'p2190b-' + str(poid))).fetchone()[0]
    c.commit()
    before_org = cl.fields_count(c, {ORG})
    n = cl.fields_pass(c, poid, True, oc.oc_key(c, poid))
    row = c.execute("SELECT * FROM office_signoffs WHERE id=?", (sid,)).fetchone()
    cnt = cl.fields_count(c, poid)
    plain = sig_dec(c, row)["signer_name"]
    after_org = cl.fields_count(c, {ORG})
    m = cl.fields_pass(c, poid, False, oc.oc_key(c, poid))
    back = c.execute("SELECT signer_name FROM office_signoffs WHERE id=?", (sid,)).fetchone()[0]
    c.execute("DELETE FROM office_signoffs WHERE id=?", (sid,))
    c.commit()
print(json.dumps({{"n": n, "sealed": str(row["signer_name"]).startswith(oc.PREFIX), "enc": cnt["enc"], "plain": plain, "m": m,
                  "back": back, "org_same": before_org == after_org}}))""")
check(j.get("n", 0) >= 2 and j.get("sealed") and j.get("enc", 0) >= 2,
      f"the private approval is encrypted and counted by the personal office's pass {j}")
check(j.get("plain") == "Erika Example" and j.get("m", 0) >= 2 and j.get("back") == "Erika Example",
      f"... opens for the app and the decrypting pass brings it back {j}")
check(j.get("org_same"), f"... another organisation's count does not see it {j}")

# ---- #2561: live texts of an encrypted organisation stay off a service on another server -----------------------------------
j = py(f"""import app, json
from kalmido.tasks import related as rl
from kalmido.core.pg import system_ctx
c = app.connect()
rl.oc_active = lambda c_: True
out = {{}}
with system_ctx(c):
    rl.EMB_KIND = "https"
    out["https"] = [rl.rt9_live_ok(c, {ALICE}, {ORG}), rl.rt9_live_ok(c, {ALICE}, None), rl.rt9_live_ok(c, {ALICE}), rl.rt9_live_ok(c, {FRIDA})]
    rl.EMB_KIND = "internal"
    out["internal"] = [rl.rt9_live_ok(c, {ALICE}, {ORG}), rl.rt9_live_ok(c, {ALICE})]
print(json.dumps(out))""")
check(j.get("https") == [False, True, False, True], f"another server: no live text of the organisation, private ones go {j}")
check(j.get("internal") == [True, True], f"a service on this server: everything as before {j}")

# ---- #2561: team chat files of an organisation for its final deletion -------------------------------------------------------
j = py(f"""import app, json
from kalmido.accounts.orgretain import odl_tchat_files
from kalmido.core.pg import system_ctx
c = app.connect()
with system_ctx(c):
    rid = c.execute("INSERT INTO tchat_rooms(kind, created_at) VALUES('group', '2026-10-23T10:00:00+00:00') RETURNING id").fetchone()[0]
    mid = c.execute("INSERT INTO tchat_msgs(room_id, user_id, body, created_at) VALUES(?, ?, '', '2026-10-23T10:00:00+00:00') RETURNING id",
                    (rid, {ALICE})).fetchone()[0]
    for oid, p in (({ORG}, 'tchat/p2190b/org.bin'), (None, 'tchat/p2190b/own.bin')):
        c.execute("INSERT INTO tchat_files(message_id, room_id, org_id, user_id, name, mime, size, path, created_at) "
                  "VALUES(?,?,?,?,'a.bin','application/octet-stream',1,?,'2026-10-23T10:00:00+00:00')", (mid, rid, oid, {ALICE}, p))
    got = odl_tchat_files(c, {ORG})
    c.rollback()
print(json.dumps({{"got": got}}))""")
check(j.get("got") == ["tchat/p2190b/org.bin"], f"the organisation's team chat files are found for its deletion {j}")

shutil.rmtree(SEC, ignore_errors=True)
print(f"p2190_b_crypto: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
