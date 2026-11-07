#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.622.0 part B (#3891): the state that broke with several web processes lives in the database / goes over pg_notify.
"A second process" = `docker exec ... python` in the test container: its own Python process on the same database, like a second
web process of KALMIDO_WEB_PROCS. Invented names only.
 - sign-in ticket (2FA): made by the server, read by the second process; made by the second process, the server finishes the
   sign-in with it (bob and frida, a person without an organisation); used once; the wrong tries count in the database and
   the ticket dies after PEND_TRIES; an expired row is no ticket; key only as an HMAC, content sealed
 - OIDC state: stored in one process, taken in another, once; expired = gone
 - pg_notify (KALMIDO_PGBUS=1): an agent's long-poll in the server wakes at once for an event the second process commits;
   the instance switch collab_all changed by the second process reaches the server
usage: p2622_b_procstate_test.py <datadir>      (a fresh container; P2622B_NOSTART=1 = the server already runs)"""
import base64
import hashlib
import hmac
import os
import re
import struct
import subprocess
import sys
import threading
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, H, check, dbx, sess  # noqa: E402

kt.fresh({"KALMIDO_PGBUS": "1"}, prefix="P2622B")
A = kt.setup()
uid = {}
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": kt.PASSWORD, "email": "bob@example.com"})
assert r.ok, r.text
uid["bob"] = r.json()["id"]
FID, Fr = freelancer(B, A)
uid["frida"] = FID


def box(code):
    """Python in a second process of the container (the same database)."""
    out = subprocess.run(["docker", "exec", CT, "python", "-c", "import app\nfrom kalmido.core.db import connect, db\n"
                          "from kalmido.core.config import app as fa\nc = connect()\n" + code + "\nc.commit()\nc.close()"],
                         capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


def totp(secret, step):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    o = mac[-1] & 15
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def enrol(s):
    r = s.post(B + "/api/me/2fa/totp", json={"password": kt.PASSWORD})
    assert r.ok, r.text
    sec = r.json()["secret"].replace(" ", "")
    st = int(time.time() // 30)
    r = s.post(B + "/api/me/2fa/totp/confirm", json={"code": totp(sec, st)})
    check(r.ok, f"setup: TOTP enrolment (its secret waits in the database between the two steps) {r.text[:160]}")
    return sec, st


def login(user):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": kt.PASSWORD})
    return s, r


check(dbx("SELECT COUNT(*) FROM information_schema.tables WHERE table_name='eph_state'")[0][0] == 1, "#3891: table eph_state exists")

# ================================================================== 2FA ticket across processes
Bo = sess("bob")
SEC, ST = enrol(Bo)
SECF, STF = enrol(Fr)
dbx("DELETE FROM rate_hits")

s1, r = login("bob")
tok = s1.cookies.get("kalmido_2fa") or ""
check(r.ok and r.json().get("twofa") and tok, f"#3891: password step: ticket cookie {r.text[:160]}")
rows = dbx("SELECT k, v FROM eph_state WHERE ns='pend' AND uid=?", (uid["bob"],))
check(len(rows) == 1 and tok not in rows[0][0] and tok not in rows[0][1] and hashlib.sha256(tok.encode()).hexdigest() not in rows[0][0]
      and '"2fa"' not in rows[0][1] and rows[0][1].startswith("v1."), f"#3891: the ticket row: key only as an HMAC, content sealed {rows!r:.200}")
out = box("from kalmido.accounts import login as L\nfrom kalmido.accounts.session import _token_hash\n"
          f"with fa.test_request_context('/'):\n    p = L._pend_load('t:' + _token_hash({tok!r}))\n    print('seen', p and p['kind'], p and p['uid'])")
check(f"seen 2fa {uid['bob']}" in out, "#3891: the ticket of the server is read by a second process " + out[-300:])

# the second process makes the ticket, the server finishes the sign-in (bob, then frida without an organisation)
for who, sec, st in (("bob", SEC, ST), ("frida", SECF, STF)):
    out = box("from kalmido.accounts import login as L\n"
              f"with fa.test_request_context('/', environ_base={{'REMOTE_ADDR': '198.51.100.20'}}):\n"
              f"    print('TOK', L.pend_new('2fa', {uid[who]}, remember=True))")
    m = re.search(r"TOK (\S+)", out)
    check(m, f"#3891: a second process makes {who}'s ticket " + out[-300:])
    s2 = requests.Session()
    s2.headers.update(H)
    s2.cookies.set("kalmido_2fa", m.group(1) if m else "x")
    r = s2.post(B + "/api/auth/2fa", json={"code": totp(sec, st + 1)})
    me = s2.get(B + "/api/me")
    check(r.ok and me.ok and me.json().get("id") == uid[who], f"#3891: the server finishes {who}'s sign-in with that ticket {r.status_code} {r.text[:160]}")
    r = s2.post(B + "/api/auth/2fa", json={"code": totp(sec, st + 1)})
    check(r.status_code == 401 and r.json().get("expired"), f"#3891: the ticket is used once ({who}) {r.status_code} {r.text[:120]}")

# wrong tries: counted in the row (every process sees them), the ticket dies after PEND_TRIES
dbx("DELETE FROM rate_hits")
s3, r = login("bob")
codes = []
for i in range(2):
    codes.append(s3.post(B + "/api/auth/2fa", json={"code": "000000"}).status_code)
n = dbx("SELECT n FROM eph_state WHERE ns='pend' AND uid=? ORDER BY at DESC LIMIT 1", (uid["bob"],))
check(codes == [401, 401] and n and n[0][0] == 2, f"#3891: two wrong codes, the row counts 2 {codes} {n}")
for i in range(3):
    r = s3.post(B + "/api/auth/2fa", json={"code": "000000"})
r = s3.post(B + "/api/auth/2fa", json={"code": "000000"})
check(r.status_code == 401 and r.json().get("expired"), f"#3891: after PEND_TRIES wrong codes the ticket is gone {r.text[:160]}")

# an expired row is no ticket
dbx("DELETE FROM rate_hits")
s4, r = login("bob")
dbx("UPDATE eph_state SET exp = 1 WHERE ns='pend' AND uid=?", (uid["bob"],))
r = s4.post(B + "/api/auth/2fa", json={"code": "000000"})
check(r.status_code == 401 and r.json().get("expired"), f"#3891: an expired ticket counts as gone {r.text[:160]}")

# ================================================================== OIDC state across processes
put = ("from kalmido.accounts import oidc as O\nfrom kalmido.accounts.login import seal\nfrom kalmido.accounts.session import _token_hash\n"
       "from kalmido.core.ephem import eph_put\nimport json, time\n"
       "with fa.test_request_context('/'):\n"
       "    st = {'bind': 'b', 'nonce': 'nonce-p2622', 'verifier': 'v', 'exp': time.time() + 600, 'remember': True}\n"
       "    print('put', eph_put(O.EPH_OIDC, 'state-p2622', seal(db(), 'oidc:' + _token_hash('state-p2622'), json.dumps(st)), 600))")
take = ("from kalmido.accounts import oidc as O\n"
        "with fa.test_request_context('/'):\n    a = O._oidc_state_take('state-p2622')\n    b = O._oidc_state_take('state-p2622')\n"
        "    print('take', a and a['nonce'], b)")
out = box(put)
check("put True" in out, "#3891: OIDC state stored by one process " + out[-200:])
check(not dbx("SELECT 1 FROM eph_state WHERE ns='oidc' AND (k LIKE '%state-p2622%' OR v LIKE '%nonce-p2622%')"),
      "#3891: OIDC state: key as an HMAC, nonce sealed")
out = box(take)
check("take nonce-p2622 None" in out, "#3891: another process takes the OIDC state, once " + out[-300:])
box(put)
dbx("UPDATE eph_state SET exp = 1 WHERE ns='oidc'")
out = box(take)
check("take None None" in out, "#3891: an expired OIDC state is gone " + out[-300:])

# ================================================================== pg_notify: agents' long-poll, instance switch
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "robo2622", "display_name": "Robo"})
assert r.ok, r.text
AID, ATOK = r.json()["id"], r.json()["token"]
ag = requests.Session()
ag.headers.update({"Authorization": "Bearer " + ATOK, **H})
cur = ag.get(B + "/api/v1/agent/events", params={"since": "latest"}).json()["cursor"]
res = {}


def poll():
    t = time.time()
    rr = ag.get(B + "/api/v1/agent/events", params={"since": cur, "wait": 20})
    res["r"] = (rr, time.time() - t)


th = threading.Thread(target=poll)
th.start()
# the long-poll waits in the server: a busy thread besides the health request itself
check(kt.until(lambda: A.get(B + "/api/admin/health").json()["threads"]["busy"] >= 2, timeout=10), "setup: the agent's long-poll waits")
out = box("from kalmido.agents.core import agent_emit\n"
          f"print('seq', agent_emit(c, {AID}, 'nudge', {{'text': 'p2622'}}, actor=None))")
th.join(25)
rr, dt = res.get("r", (None, 99))
check("seq " in out and rr is not None and rr.ok and rr.json()["data"] and dt < 8,
      f"#3891: the long-poll in the server wakes for an event of the second process ({dt:.1f}s of 20) {out[-200:]}")

check(A.get(B + "/api/about").json().get("collab_all") is True, "setup: collaboration on")
out = box("from kalmido.core.db import gset\nfrom kalmido.core.pgbus import bus_send\n"
          "gset(c, 'collab_all', '0')\nprint('sent', bus_send('flags', c=c))")
check("sent True" in out, "#3891: the second process sends the switch " + out[-200:])
check(kt.until(lambda: A.get(B + "/api/about").json().get("collab_all") is False, timeout=10),
      "#3891: the server reads the instance switch again (pg_notify)")
sys.exit(kt.done("p2622_b_procstate"))
