#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.360.0 part A (#2496, after-audit #1461, hardening): sign-in, backup / restore, registration, portal, core. Invented names only.
 (1) a restore keeps the API tokens and app passwords revoked after the backup revoked; one still valid stays valid
 (2) the step-up: restore and backup download, the account export (also a person without an organisation) and an
     organisation's export ask for the password (download: POST -> one-time ticket, GET with it); a switch that opens the
     server (public links on, two-factor policy off, a registration mode) asks for it, closing it does not
 (3) a reset link and the admin setting a password revoke the person's own API tokens; an agent's token stays
 (4) a registration without e-mail confirmation joins no organisation through its e-mail domain
 (5) the portal: a report joins "all my reports" only once the link in a mail to its address was opened (the bare status
     link or a wrong check value do not confirm it)
 (6) the log path of public pages hides their token
 (7) PUT /api/v1/admin/announcement needs admin-read (account alone 403)
usage: p2360_0_a_auth_test.py <datadir>   (P2360A_NOSTART=1: against a running instance on KALMIDO_TEST_PORT)
freelancer-matrix: own"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, FAILS, OKS, check, sess, su_get, until  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
PW = kt.PASSWORD

# the organisation export needs the server key (like p2184_a)
kt.fresh(env={"KALMIDO_SECRET_KEY": base64.b64encode(os.urandom(32)).decode(), "KALMIDO_ORGCRYPT_DELAY": "0"}, prefix="P2360A")
A = kt.setup()
DB = dbxm.connect(DATA)
ME = A.get(B + "/api/me").json()["id"]


def py(code, *args):
    """A few lines of Python inside the container (the server's modules); -> the last JSON line it printed."""
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code, *args], capture_output=True, text=True, timeout=600)
    for line in reversed((r.stdout or "").strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    print("container python:", r.returncode, (r.stdout or "")[-800:], (r.stderr or "")[-1500:], flush=True)
    return {}


def token(s, name, scopes=("read",)):
    r = s.post(B + "/api/me/tokens", json={"name": name, "scopes": list(scopes)})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def live(tok):
    return requests.get(V + "/me", headers={"Authorization": "Bearer " + tok}).status_code == 200


def user(name):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": PW, "email": f"{name}@example.com"})
    assert r.ok, r.text
    return r.json()["id"]


# ================================================================== (1) a restore keeps what was revoked since the backup
KEEP, GONE = token(A, "keep"), token(A, "revoked later")
ap = A.post(B + "/api/me/app-passwords", json={"name": "old phone"}).json()
check(live(KEEP) and live(GONE) and ap.get("id"), "setup: two tokens and an app password")
BK = py("from kalmido.admin import backup as bk\nimport json\nprint(json.dumps({'name': bk.bk_create('manual')}))").get("name")
check(bool(BK), f"setup: a backup {BK}")
gid, GH = DB.execute("SELECT id, token_hash FROM api_tokens WHERE name='revoked later'").fetchone()
check(A.delete(B + f"/api/me/tokens/{gid}").ok and A.delete(B + f"/api/me/app-passwords/{ap['id']}").ok and not live(GONE),
      "after the backup: the token and the app password are revoked")
NEW = token(A, "made after the backup")  # 2.360.0 R (#2496, review): in the safety backup, not in BK
check(bool(DB.execute("SELECT 1 FROM revoked_creds WHERE hash=?", (GH,)).fetchone()), "(1) the revoked token is noted (revoked_creds)")

# ================================================================== (2) step-up: restore
r = A.post(B + "/api/admin/backups/restore", json={"name": BK, "confirm": "RESTORE"})
check(r.status_code == 403 and r.json().get("need") == "password", f"(2) restore without the password: 403 need=password {r.status_code} {r.text[:160]}")
r = A.post(B + "/api/admin/backups/restore", json={"name": BK, "confirm": "RESTORE", "password": "wrong-pass-1"})
check(r.status_code == 403, f"(2) restore with a wrong password: 403 {r.status_code}")
r = A.post(B + "/api/admin/backups/restore", json={"name": BK, "confirm": "RESTORE", "password": PW})
check(r.ok, f"(2) restore with the password {r.status_code} {r.text[:200]}")
A = sess("alice")  # the restore ended every session
check(live(KEEP), "(1) a token valid before and after the backup stays valid")
check(not live(GONE), "(1) a token revoked after the backup stays revoked (before: the restore brought it back)")
check(not DB.execute("SELECT 1 FROM app_passwords WHERE id=?", (ap["id"],)).fetchone(), "(1) an app password revoked after the backup stays revoked")
# 2.360.0 R (#2496, review): restoring the safety backup undoes the restore: the token made after BK comes back (before:
# it was not valid at that moment and went, like every token of a backup restored onto a freshly installed server)
SAF = r.json().get("safety")
check(not live(NEW) and bool(SAF), f"(1) a token made after the backup is not in it; safety backup {SAF}")
r = A.post(B + "/api/admin/backups/restore", json={"name": SAF, "confirm": "RESTORE", "password": PW})
check(r.ok, f"(1) restoring the safety backup {r.status_code} {r.text[:200]}")
A = sess("alice")
check(live(NEW) and live(KEEP), "(1) restoring the safety backup keeps every token it holds (none was revoked)")
check(not live(GONE), "(1) the revoked token stays revoked after the second restore too")

# ================================================================== (2) step-up: backup download
r = A.get(B + f"/api/admin/backups/{BK}/download")
check(r.status_code == 403 and r.json().get("need") == "password", f"(2) backup download without the step-up: 403 {r.status_code}")
check(A.get(B + f"/api/admin/backups/{BK}/download", params={"t": "x" * 40}).status_code == 403, "(2) a made-up ticket 403")
r = su_get(A, B + f"/api/admin/backups/{BK}/download")
check(r.ok and len(r.content) > 100, f"(2) backup download with the ticket {r.status_code}")

# ================================================================== (2) step-up: account export (a person without an organisation)
FID, Fr = freelancer(B, A)
check(Fr.post(B + "/api/account/export").status_code == 202, "freelancer: the account export starts")
until(lambda: Fr.get(B + "/api/account/export").json().get("state") != "running", 120)
r = Fr.get(B + "/api/account/export/file")
check(r.status_code == 403 and r.json().get("need") == "password", f"(2) freelancer: the account export without the step-up 403 {r.status_code}")
r = su_get(Fr, B + "/api/account/export/file")
check(r.ok and r.content[:2] == b"PK", f"(2) freelancer: the account export with the ticket {r.status_code}")
check(Fr.get(B + "/api/account/export/file", params={"t": "x" * 40}).status_code == 403, "(2) a made-up ticket 403")

# ================================================================== (2) step-up: an organisation's export
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha Test", "admin_id": ME}).json()["id"]
check(A.post(B + f"/api/orgs/{ORG}/export").status_code == 202, "the organisation export starts")
until(lambda: A.get(B + f"/api/orgs/{ORG}/export").json().get("state") != "running", 120)
r = A.get(B + f"/api/orgs/{ORG}/export/file")
check(r.status_code == 403 and r.json().get("need"), f"(2) the organisation export without the step-up 403 {r.status_code}")
r = su_get(A, B + f"/api/orgs/{ORG}/export/file")
check(r.ok and r.content[:8] == b"KALMIDO-", f"(2) the organisation export with the ticket {r.status_code}")

# ================================================================== (2) step-up: the switches that open the server
S = B + "/api/admin/settings"
check(A.patch(S, json={"public_links": False}).ok, "(2) public links off: no password")
r = A.patch(S, json={"public_links": True})
check(r.status_code == 403 and r.json().get("password_needed") is True, f"(2) public links on: asks for the password {r.status_code}")
check(A.patch(S, json={"public_links": True, "password": PW}).ok and A.get(B + "/api/about").json().get("public_links") is True,
      "(2) public links on with the password")
check(A.patch(S, json={"public_links": True}).ok, "(2) public links already on: no question")
check(A.patch(S, json={"twofa_required": True}).ok, "(2) two-factor policy on: no password")
r = A.patch(S, json={"twofa_required": False})
check(r.status_code == 403 and r.json().get("password_needed") is True, "(2) two-factor policy off: asks for the password")
check(A.patch(S, json={"twofa_required": False, "password": "wrong-pass-1"}).status_code == 403, "(2) ... not with a wrong one")
check(A.patch(S, json={"twofa_required": False, "password": PW}).ok and A.get(B + "/api/about").json().get("twofa_required") is False,
      "(2) two-factor policy off with the password")
r = A.patch(S, json={"signup_mode": "approval"})
check(r.status_code == 403 and r.json().get("password_needed") is True, "(2) opening the registration asks for the password")
# 2.360.0 R (#2496, review 9): the default mode ("off", also when never stored) asks for nothing
check(A.patch(S, json={"signup_mode": "off"}).ok,
      "(2) choosing the default registration mode (off) asks for no password")
check(Fr.patch(S, json={"public_links": True, "password": PW}).status_code == 403, "(2) freelancer (no instance admin): the switches 403 as before")

# ================================================================== (3) a reset revokes the own API tokens, an agent's stays
BOB = user("bob")
Bo = sess("bob")
BT = token(Bo, "bob script")
AG = user("helperbot")
DB.execute("UPDATE users SET kind='agent' WHERE id=?", (AG,))
AGT = "agent" + "x" * 30
DB.execute("INSERT INTO api_tokens(user_id,name,token_hash,prefix,scopes,created_at) VALUES(?,?,?,?,?,?)",
           (AG, "agent token", hashlib.sha256(AGT.encode()).hexdigest(), "agent", "read", "2026-01-01T00:00:00+00:00"))
check(live(BT), "setup: bob's token works")
r = A.patch(B + f"/api/users/{BOB}", json={"password": "password789"})
check(r.ok and not live(BT), f"(3) the admin sets a password: bob's own token is revoked {r.status_code}")
check(DB.execute("SELECT COUNT(*) FROM api_tokens WHERE user_id=?", (AG,)).fetchone()[0] == 1, "(3) the agent's token stays")
Bo = sess("bob", "password789")
BT = token(Bo, "bob script 2")
TOK = "r2360a" + "x" * 30
DB.execute("INSERT INTO user_invites(user_id,token_hash,kind,created_at,expires_at) VALUES(?,?,?,?,?)",
           (BOB, hashlib.sha256(TOK.encode()).hexdigest(), "reset", "2026-01-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00"))
r = sess().post(B + "/api/auth/invite/accept", json={"token": TOK, "password": "password321"})
check(r.ok and not live(BT), f"(3) a reset link: bob's own token is revoked {r.status_code} {r.text[:120]}")
check(DB.execute("SELECT COUNT(*) FROM api_tokens WHERE user_id=?", (AG,)).fetchone()[0] == 1, "(3) the agent's token still stays")
FT = token(Fr, "frida script")
check(A.patch(B + f"/api/users/{FID}", json={"password": "password654"}).ok and not live(FT), "(3) freelancer: the same")

# ================================================================== (4) registration without e-mail: no organisation by its domain
DB.execute("UPDATE orgs SET domains='alpha-test.example' WHERE id=?", (ORG,))
A.patch(S, json={"signup_mode": "approval", "password": PW})
R = sess()
r = R.post(B + "/api/auth/signup", json={"name": "Mallory", "email": "mallory@alpha-test.example", "password": "mallory-secret-1"})
row = DB.execute("SELECT id FROM users WHERE email='mallory@alpha-test.example'").fetchone()
if r.ok and r.json().get("mail") is False:
    check(row and not DB.execute("SELECT 1 FROM org_members WHERE user_id=?", (row[0],)).fetchone(),
          "(4) without e-mail: the unconfirmed address joins no organisation by its domain (before: it did)")
else:  # a container with e-mail: the address is confirmed by the link before anything (the old way, unchanged)
    check(r.ok, f"(4) registration answered {r.status_code} {r.text[:120]}")
    print("(4) this container sends e-mail: the case without e-mail is covered by p2460_a", flush=True)

# ================================================================== (5) portal: only a confirmed address lists a report
L = A.post(B + "/api/lists", json={"name": "Support Alpha"}).json()["id"]
T1 = A.post(B + "/api/tasks", json={"list_id": L, "title": "Typed in by someone else"}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"list_id": L, "title": "Sent by the owner of the address"}).json()["id"]
PT = """
import json, sys, app
from kalmido.core.pg import system_ctx
from kalmido.team.portal import pt_create, pt_mail_url
c = app.connect()
out = {}
with system_ctx(c):
    l = c.execute('SELECT id, org_id, owner_id FROM lists WHERE id=?', (int(sys.argv[1]),)).fetchone()
    for t in sys.argv[2:]:
        pid, tok = pt_create(c, int(t), l, None, 'Someone', 'victim@example.com')
        p = c.execute('SELECT * FROM portal_tickets WHERE id=?', (pid,)).fetchone()
        out[t] = {'tok': tok, 'mail': pt_mail_url(c, p, tok).split('/p/', 1)[1]}
c.commit()
print(json.dumps(out))
"""
tk = py(PT, str(L), str(T1), str(T2))
t1, t2 = tk.get(str(T1)) or {}, tk.get(str(T2)) or {}


def claimed(t):
    return DB.execute("SELECT claimed FROM portal_tickets WHERE task_id=?", (t,)).fetchone()[0]


P = requests.Session()
check(t1 and P.get(B + f"/p/{t1['tok']}").status_code == 200 and claimed(T1) == 0, "(5) the bare status link (thank-you page) confirms nothing")
check(P.get(B + f"/p/{t1['tok']}", params={"m": "0" * 32}).status_code == 200 and claimed(T1) == 0, "(5) a wrong check value confirms nothing")
check(t2 and "?m=" in t2["mail"] and P.get(B + "/p/" + t2["mail"]).status_code == 200 and claimed(T2) == 1,
      "(5) the link from the mail to the address confirms it")
MY = """
import json, sys, app
from kalmido.core.pg import system_ctx
from kalmido.team.portal import pt_email_hash, pt_my_tickets
c = app.connect()
with system_ctx(c):
    l = c.execute('SELECT org_id, owner_id FROM lists WHERE id=?', (int(sys.argv[1]),)).fetchone()
    rows = pt_my_tickets(c, pt_email_hash(c, 'victim@example.com'), l['org_id'], None if l['org_id'] else l['owner_id'])
print(json.dumps({'tasks': [r['task_id'] for r in rows]}))
"""
mine = py(MY, str(L)).get("tasks")
check(mine == [T2], f"(5) all my reports: only the confirmed one (before: the one typed in by someone else too) {mine}")

# ================================================================== (6) the log path hides public tokens
LP = """
import json
from kalmido.core.db import log_path
print(json.dumps({p: log_path(p) for p in ['/s/abcdef123/file/3', '/s/f/abcdef/zip', '/f/abcdef', '/u/abcdef', '/p/abcdef/stop',
      '/ical/abcdef.ics', '/ical/ev/abcdef.ics', '/portal/login/abcdef', '/api/hooks/in/abcdef', '/api/tasks/7']}))
"""
lp = py(LP)
check(lp and all("abcdef" not in v for v in lp.values() if v != "/api/tasks/7") and lp.get("/api/tasks/7") == "/api/tasks/7"
      and lp.get("/p/abcdef/stop") == "/p/***/stop", f"(6) tokens of public paths are masked, other paths stay {lp}")

# ================================================================== (7) the announcement through API v1 needs admin-read
A = sess("alice")
TA = {"Authorization": "Bearer " + token(A, "banner", ("read", "account"))}
r = requests.put(V + "/admin/announcement", headers=TA, json={"text": "Phishing text"})
check(r.status_code == 403 and not A.get(B + "/api/state").json().get("announce"), f"(7) an admin's token with account only: 403 {r.status_code}")
TA2 = {"Authorization": "Bearer " + token(A, "banner2", ("read", "account", "admin-read"))}
r = requests.put(V + "/admin/announcement", headers=TA2, json={"text": "Maintenance tonight"})
check(r.ok, f"(7) with admin-read + account: set {r.status_code}")
requests.put(V + "/admin/announcement", headers=TA2, json={"text": ""})

DB.close()
print(f"p2360_0_a_auth: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
