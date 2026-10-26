#!/usr/bin/env python3
"""2.306.0 D1 (#2875): hardening of the core / accounts (audit D), own container (start.sh, a server key; later restarted
with KEEP=1 as a hosted instance). Invented accounts only (example.com). One case per rule:
 - the background queue: a payload is sealed with a key from the server key (v2), a row of the old form (v1, the sign-in
   key of the database) still opens, another server key opens no v2 row
 - rate limits over several processes: a limit of an hour (and sign-in failures) counts the hits of every process; the
   per-minute load limits stay per process; the stored keys are hashes
 - an organisation's trip is not reachable by its id with a personal API token (a private one is, also for a person
   without an organisation)
 - hosted: the last admin leaving makes the operator no admin (409), the instance admin's dialog can still swap the admin
   in one step; self-hosted the operator takes over as before
 - hosted: the instance admin invites an existing account into an organisation (it joins by accepting); self-hosted directly
 - the sign-on's admin domains change only with the account password (a draft's apply too); non-admins 403 as before
 - review (Fix-1): while an admin rule is set, the provider, client, groups claim and auto-create change only with the
   password too; hosted, the last admin stays at the user dialog, admins_remove and the old admins set; invited + admin
   keeps the admin role; the operator does not invite itself; the rate keys are keyed with the server key and a flood on
   one key stops adding rows
 - the connection's context after a raw ROLLBACK TO SAVEPOINT is the stored one again
 - a reference node's free name avoids only the names the person sees in the folder (an admin / the owner: all)
freelancer-matrix: core_hardening
usage: p2306_d1_core_hardening_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time

import requests

import kt
from kt import B, CT, check, sess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer, login  # noqa: E402

KEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (32 bytes, base64)
KEY2 = "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8="


def dbw(q, a=()):
    """A write in the suite's database (committed)."""
    c = kt._dbx.connect(os.path.join(kt.DATA, "tasks.db"))
    try:
        r = c.execute(q, a).fetchall() if "RETURNING" in q else None
        if r is None:
            c.execute(q, a)
        c.commit()
        return r
    finally:
        c.close()


def py(code, env=None):
    """Runs code in a second process of the container (no loops, role web); the last line of its output = JSON."""
    extra = []
    for k, v in {"TASKS_WATCHDOG": "0", "KALMIDO_ROLE": "web", **(env or {})}.items():
        extra += ["-e", f"{k}={v}"]
    for _try in range(3):  # the import may meet the running server's start-up DDL (deadlock): try again
        r = subprocess.run(["docker", "exec", "-w", "/app", *extra, CT, "python", "-c", "import app\n" + code],
                           capture_output=True, text=True)
        if "DeadlockDetected" not in r.stdout + r.stderr:
            break
        time.sleep(2)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print((r.stdout + r.stderr)[-2000:], flush=True)
        return {}


kt.fresh(env={"KALMIDO_SECRET_KEY": KEY})
A = kt.sess(None)
assert A.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "gus", "mia", "hugo", "ivy", "gus2"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com", "orgs": [{"id": ORG, "role": "member"}] if u == "bob" else []})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
FID, Fr = freelancer(B, A)
for s in (A, sess("bob")):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "comments,collab,travel,files"}).ok

# ================================================================ 1. the queue's payload: the server key
q = py(f"""
import base64, json, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from kalmido.accounts.bgjobs import _seal, _unseal
from kalmido.accounts.login import auth_key
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
c = connect()
s = _seal(c, "mail:pwreset", ["bob@example.com", "https://kalmido.example/#reset=abc"])
back = _unseal(c, "mail:pwreset", s)
with system_ctx(c):
    k = auth_key(c)
n = os.urandom(12)  # a row the version before queued (the sign-in key of the database)
old = "v1." + base64.urlsafe_b64encode(n + AESGCM(k).encrypt(n, json.dumps(["x@example.com"]).encode(), b"kalmido-bgjob:mail:pwreset")).decode()
try:
    oldback = _unseal(c, "mail:pwreset", old)
except Exception as e:
    oldback = repr(e)
try:  # the v2 row opened with the sign-in key alone (what a copy of the database holds) must fail
    raw = base64.urlsafe_b64decode(s[3:])
    AESGCM(k).decrypt(raw[:12], raw[12:], b"kalmido-bgjob:mail:pwreset")
    dbonly = True
except Exception:
    dbonly = False
print(json.dumps({{"v2": s.startswith("v2."), "plain": "abc" in s, "back": back, "old": oldback, "dbonly": dbonly, "s": s}}))
""")
check(q.get("v2") is True and q.get("plain") is False, f"the queue's payload is sealed in the form v2 (the server key) {str(q)[:200]}")
check(q.get("back") == ["bob@example.com", "https://kalmido.example/#reset=abc"], "a v2 payload opens again")
check(q.get("old") == ["x@example.com"], f"a row of the old form (v1) still opens after the update {q.get('old')}")
check(q.get("dbonly") is False, "the database's own sign-in key does not open a v2 payload")
q2 = py(f"""
import json
from kalmido.accounts.bgjobs import _unseal
from kalmido.core.db import connect
try:
    _unseal(connect(), "mail:pwreset", {json.dumps(q.get("s", "v2.x"))})
    ok = True
except Exception:
    ok = False
print(json.dumps({{"opened": ok}}))
""", env={"KALMIDO_SECRET_KEY": KEY2})
check(q2.get("opened") is False, "another server key opens no v2 payload")

# ================================================================ 2. rate limits counted for every process
HIT = """
import json
from kalmido.api.common import hit_limit
print(json.dumps([hit_limit("p2306:{k}", {n}, {w}) for _ in range({times})]))
"""
a = py(HIT.format(k="hour", n=3, w=3600, times=2))
b = py(HIT.format(k="hour", n=3, w=3600, times=2))
check(a == [False, False] and b == [False, True], f"an hourly limit counts the hits of every process (3 of 3 then refused) {a} {b}")
a = py(HIT.format(k="min", n=1, w=60, times=1))
b = py(HIT.format(k="min", n=1, w=60, times=1))
check(a == [False] and b == [False], f"a per-minute load limit stays per process {a} {b}")
FAIL = """
import json
from kalmido.accounts.session import _rate_blocked, _rate_fail
keys = [("p2306f:u:dora@203.0.113.9", 5)]
out = [_rate_fail(keys) for _ in range({times})]
print(json.dumps({{"tripped": out, "blocked": _rate_blocked(keys)}}))
"""
a = py(FAIL.format(times=3))
b = py(FAIL.format(times=2))
c3 = py("""
import json
from kalmido.accounts.session import _rate_blocked
print(json.dumps(_rate_blocked([("p2306f:u:dora@203.0.113.9", 5)])))
""")
check(a.get("blocked") is False and b.get("tripped") == [[], ["p2306f:u:dora@203.0.113.9"]] and b.get("blocked") is True and c3 is True,
      f"sign-in failures of two processes add up (5th trips the limit, a third process is blocked too) {a} {b} {c3}")
check(not kt.dbx("SELECT 1 FROM rate_hits WHERE k LIKE '%p2306%' OR k LIKE '%dora%'") and kt.dbx("SELECT COUNT(*) FROM rate_hits")[0][0] >= 8,
      "the shared counter stores hashes of the keys only")
HK = """
import hashlib, json
from kalmido.core.db import connect
from kalmido.core.ratedb import _h
k = "p2306f:u:dora@203.0.113.9"
c = connect()
n = c.execute("SELECT COUNT(*) FROM rate_hits WHERE k=?", (_h(k),)).fetchone()[0]
print(json.dumps({"h": _h(k), "plain": hashlib.sha256(("kalmido-rate:" + k).encode()).hexdigest()[:32], "rows": n}))
"""
a, b = py(HK), py(HK, env={"KALMIDO_SECRET_KEY": KEY2})
check(a.get("rows") == 5 and a.get("h") != a.get("plain") and b.get("h") not in (a.get("h"), None),
      f"2.306.0 Fix-1 (#2875 review): the stored keys are keyed with the server key (not a plain hash) {a} {b}")
q = py("""
import json
from kalmido.accounts.session import _rate_fail
from kalmido.core.db import connect
from kalmido.core.ratedb import _h
keys = [("p2306cap:u:erin@203.0.113.7", 2)]
out = [_rate_fail(keys) for _ in range(7)]
c = connect()
n = c.execute("SELECT COUNT(*) FROM rate_hits WHERE k=?", (_h(keys[0][0]),)).fetchone()[0]
ix = c.execute("SELECT COUNT(*) FROM pg_indexes WHERE indexname='rate_hits_at'").fetchone()[0]
print(json.dumps({"out": out, "rows": n, "ix": ix}))
""")
check(q.get("rows") == 4 and q.get("out", [None] * 2)[1] == ["p2306cap:u:erin@203.0.113.7"] and q.get("ix") == 1,
      f"2.306.0 Fix-1 (#2875 review): a flood on one key stops adding rows at twice the limit (it still trips once), the clean-up has its index {q}")
r = sess(None).post(B + "/api/auth/login", json={"username": "alice", "password": "password123"})
check(r.ok, "a normal sign-in works with the shared counter " + r.text[:120])

# ================================================================ 3. an organisation's trip by its id: not for a token
r = A.post(B + "/api/life/trips", json={"name": "Trade fair", "from": "2030-05-01", "to": "2030-05-03", "packing": "", "space": f"org:{ORG}"})
check(r.status_code == 201, "an organisation's trip " + r.text[:160])
OT = r.json().get("list_id")
r = A.post(B + "/api/life/trips", json={"name": "Holiday", "from": "2030-06-01", "to": "2030-06-03", "packing": ""})
PT = r.json().get("list_id")
tok = A.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "private"]}).json()["token"]
TH = {"Authorization": "Bearer " + tok}
check(OT in [x["list_id"] for x in A.get(B + "/api/life", params={"space": f"org:{ORG}"}).json().get("travel", {}).get("trips", [])],
      "the app still shows the organisation's trip")
check(requests.get(B + f"/api/v1/lists/{OT}", headers=TH).status_code == 404,
      "a personal token gets 404 for an organisation's trip by its id")
check(requests.get(B + f"/api/v1/lists/{PT}", headers=TH).status_code == 200, "a private trip is reachable with the token")
OTT = A.post(B + "/api/tasks", json={"title": "Book the stand", "list_id": OT}).json().get("id")
check(OTT and requests.get(B + f"/api/v1/tasks/{OTT}", headers=TH).status_code == 404, "a personal token gets 404 for a task of an organisation's trip")
for path in ("overview", "milestones", "links"):
    check(requests.get(B + f"/api/v1/lists/{OT}/{path}", headers=TH).status_code == 404, f"a personal token gets 404 for /lists/<trip>/{path}")
PTT = A.post(B + "/api/tasks", json={"title": "Pack", "list_id": PT}).json().get("id")
check(PTT and requests.get(B + f"/api/v1/tasks/{PTT}", headers=TH).status_code == 200, "a task of the private trip is reachable with the token")
r = Fr.post(B + "/api/life/trips", json={"name": "Solo", "from": "2030-07-01", "to": "2030-07-02", "packing": ""})
FT = r.json().get("list_id")
ftok = Fr.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write", "private"]}).json().get("token", "")
check(r.status_code == 201 and requests.get(B + f"/api/v1/lists/{FT}", headers={"Authorization": "Bearer " + ftok}).status_code == 200,
      "freelancer: the own trip is reachable with the own token")

# ================================================================ 6. sign-on admin domains: with the password
r = A.put(B + "/api/admin/oidc", json={"admin_domains": "corp.example"})
check(r.status_code == 403 and r.json().get("password_needed") is True, "admin domains without the password: asked for it")
check(A.put(B + "/api/admin/oidc", json={"admin_domains": "corp.example", "password": "nope-nope"}).status_code == 403, "a wrong password: 403")
r = A.put(B + "/api/admin/oidc", json={"admin_domains": "corp.example", "password": "password123"})
check(r.ok and r.json().get("admin_domains") == "corp.example", "with the password: stored " + r.text[:160])
check(A.put(B + "/api/admin/oidc", json={"label": "Company login"}).ok, "another field needs no password (as before)")
check(Fr.put(B + "/api/admin/oidc", json={"admin_domains": "x.example", "password": "password123"}).status_code == 403,
      "freelancer (no instance admin): 403 as before")
A.put(B + "/api/admin/oidc/draft", json={"admin_domains": "corp.example, other.example"})
gate = py("""
import json
from kalmido.core.db import connect, gset
c = connect()
from kalmido.accounts.oidc import _oidc_draft, _oidc_draft_hash
gset(c, "oidc_draft_ok", _oidc_draft_hash(_oidc_draft(c)))  # the check of the draft (no provider in the test)
c.commit()
print(json.dumps(True))
""")
r = A.post(B + "/api/admin/oidc/draft/apply", json={})
check(gate is True and r.status_code == 403 and r.json().get("password_needed") is True, "apply of new admin domains asks for the password " + r.text[:160])
r = A.post(B + "/api/admin/oidc/draft/apply", json={"password": "password123"})
check(r.ok and r.json().get("admin_domains") == "corp.example, other.example", "apply with the password " + r.text[:160])
# 2.306.0 Fix-1 (#2875 review): while an admin rule is set, everything that decides who becomes an admin asks for the password
for k, v in (("issuer", "https://idp.example"), ("client_id", "kalmido-x"), ("groups_claim", "roles"), ("admin_group", "kalmido-admins")):
    r = A.put(B + "/api/admin/oidc", json={k: v})
    check(r.status_code == 403 and r.json().get("password_needed") is True, f"admin rule set: a new {k} asks for the password " + r.text[:120])
r = A.put(B + "/api/admin/oidc", json={"issuer": "https://idp.example", "client_id": "kalmido-x", "password": "password123"})
check(r.ok and r.json().get("issuer") == "https://idp.example", "a new provider with the password " + r.text[:160])
r = A.patch(B + "/api/admin/settings", json={"oidc_autocreate": True})
check(r.status_code == 403 and r.json().get("password_needed") is True, "admin rule set: auto-create asks for the password " + r.text[:120])
check(A.patch(B + "/api/admin/settings", json={"oidc_autocreate": True, "password": "password123"}).ok
      and A.patch(B + "/api/admin/settings", json={"oidc_autocreate": False}).ok, "auto-create on with the password, off without")
check(Fr.patch(B + "/api/admin/settings", json={"oidc_autocreate": True, "password": "password123"}).status_code == 403,
      "freelancer (no instance admin): the switch 403 as before")
assert A.put(B + "/api/admin/oidc", json={"admin_domains": "", "password": "password123"}).ok
check(A.put(B + "/api/admin/oidc", json={"issuer": "https://idp2.example"}).ok and A.patch(B + "/api/admin/settings", json={"oidc_autocreate": True}).ok
      and A.patch(B + "/api/admin/settings", json={"oidc_autocreate": False}).ok, "without an admin rule: provider and auto-create need no password (as before)")
assert A.put(B + "/api/admin/oidc", json={"issuer": "", "client_id": ""}).ok

# ================================================================ 7. the context after a raw ROLLBACK TO SAVEPOINT
q = py("""
import json
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
c = connect()
c._ctx = (1, (), "user")
c.execute("SELECT 1")
c._apply_ctx()
c.execute("SAVEPOINT p2306")
with system_ctx(c):  # the context changes after the savepoint ...
    c.execute("ROLLBACK TO SAVEPOINT p2306")  # ... and the rollback undoes its set_config
    inside = c.execute("SELECT current_setting('app.role')").fetchone()[0]
    want = c._ctx[2]
c.rollback()
print(json.dumps({"inside": inside, "want": want}))
""")
check(q.get("inside") and q.get("inside") == q.get("want"), f"after a raw ROLLBACK TO SAVEPOINT the database has the stored context {q}")

# ================================================================ 8. a reference node's free name: visible names only
FREE = """
import json
from kalmido.core.config import app as fa
from kalmido.core.db import connect
from kalmido.files.fsref import _ref_free_name
from kalmido.files.store import _free_name
c = connect()
with fa.app_context():  # no request: the connection keeps the system context
    print(json.dumps({{"ref": _ref_free_name(c, {uid}, {pid}, {owner}, {org}, "{name}"), "all": _free_name(c, {pid}, {owner}, {org}, "{name}")}}))
"""
now = "2030-01-01T00:00:00+00:00"
FOLD = dbw("INSERT INTO fs_nodes(parent_id, kind, name, owner_id, org_id, org_access, created_at, updated_at) VALUES(NULL, 'folder', 'Shared', ?, ?, 'edit', ?, ?) RETURNING id",
           (1, ORG, now, now))[0][0]
# a reference node the folder does not open (the test kind "probe": its object's name starts with "hide"), and a plain file
SRC = dbw("INSERT INTO fs_nodes(parent_id, kind, name, owner_id, org_id, created_at, updated_at) VALUES(NULL, 'file', 'hide-src', 1, ?, ?, ?) RETURNING id",
          (ORG, now, now))[0][0]
dbw("INSERT INTO fs_nodes(parent_id, kind, name, owner_id, org_id, ref_kind, ref_id, created_at, updated_at) VALUES(?, 'ref', 'Plan', 1, ?, 'probe', ?, ?, ?)",
    (FOLD, ORG, SRC, now, now))
dbw("INSERT INTO fs_nodes(parent_id, kind, name, owner_id, org_id, created_at, updated_at) VALUES(?, 'file', 'Notes', 1, ?, ?, ?)", (FOLD, ORG, now, now))
PROBE = {"KALMIDO_TEST_FSREF": "1"}
q = py(FREE.format(uid=uid["bob"], pid=FOLD, owner=1, org=ORG, name="Plan"), env=PROBE)
check(q.get("ref") == "Plan" and q.get("all") == "Plan (2)", f"a member: a hidden node's name is not avoided (no hint at it) {q}")
q = py(FREE.format(uid=uid["bob"], pid=FOLD, owner=1, org=ORG, name="Notes"), env=PROBE)
check(q.get("ref") == "Notes (2)", f"a member: a name the member sees is avoided as before {q}")
q = py(FREE.format(uid=1, pid=FOLD, owner=1, org=ORG, name="Notes"), env=PROBE)
check(q.get("ref") == "Notes (2)", f"the admin: the names in the folder are avoided as before {q}")
FF = dbw("INSERT INTO fs_nodes(parent_id, kind, name, owner_id, org_id, created_at, updated_at) VALUES(NULL, 'folder', 'Mine', ?, NULL, ?, ?) RETURNING id", (FID, now, now))[0][0]
dbw("INSERT INTO fs_nodes(parent_id, kind, name, owner_id, org_id, created_at, updated_at) VALUES(?, 'file', 'Plan', ?, NULL, ?, ?)", (FF, FID, now, now))
q = py(FREE.format(uid=FID, pid=FF, owner=FID, org="None", name="Plan"), env=PROBE)
check(q.get("ref") == "Plan (2)", f"freelancer: the own name in the own folder is avoided {q}")

# ================================================================ 4 + 5 self-hosted first (unchanged)
r = A.post(B + "/api/admin/orgs", json={"name": "Delta", "admin_id": uid["gus2"]})
DO = r.json().get("id") or r.json().get("org", {}).get("id")
r = sess("gus2").delete(B + f"/api/orgs/{DO}/members/{uid['gus2']}")
check(r.ok and kt.dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=1", (DO,)) == [("admin",)],
      "self-hosted: the last admin leaves, the operator takes the organisation over (as before) " + r.text[:120])
r = A.put(B + f"/api/orgs/{ORG}/members", json={"email": "ivy@example.com"})
check(r.ok and kt.dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (ORG, uid["ivy"])),
      "self-hosted: the instance admin adds an existing account directly (as before) " + r.text[:120])
r = A.patch(B + f"/api/admin/orgs/{DO}", json={"members_add": [uid["mia"]], "admins_add": [uid["mia"]]})
check(r.ok and kt.dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (DO, uid["mia"])) == [("admin",)],
      "self-hosted: added + admin in one step is an admin at once (as before) " + r.text[:120])
r = A.patch(B + f"/api/admin/orgs/{DO}", json={"admins_remove": [1, uid["mia"]]})
check(r.ok and not kt.dbx("SELECT 1 FROM org_members WHERE org_id=? AND role='admin'", (DO,)),
      "self-hosted: the instance admin may still demote every admin (as before) " + r.text[:120])

# ================================================================ hosted (KEEP=1)
kt.fresh(env={"KALMIDO_SECRET_KEY": KEY, "KALMIDO_HOSTED": "1"}, keep=True)
A = sess("alice")
r = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": uid["gus"]})
GO = r.json().get("id") or r.json().get("org", {}).get("id")
check(r.status_code in (200, 201) and GO, "hosted: an organisation of a customer " + r.text[:160])
G = sess("gus")
r = G.delete(B + f"/api/orgs/{GO}/members/{uid['gus']}")
check(r.status_code == 409 and not kt.dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=1", (GO,)),
      "hosted: the last admin cannot leave, the operator does not become its admin " + r.text[:160])
dbw("INSERT INTO org_members(org_id, user_id, role) VALUES(?,?,'member')", (GO, uid["mia"]))
r = A.patch(B + f"/api/admin/orgs/{GO}", json={"members_remove": [uid["gus"]]})
check(r.status_code == 409 and kt.dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (GO, uid["gus"])) == [("admin",)],
      "hosted: the instance admin's dialog cannot take the last admin out either (nothing changed) " + r.text[:160])
r = A.patch(B + f"/api/admin/orgs/{GO}", json={"members_remove": [uid["gus"]], "admins_add": [uid["mia"]]})
check(r.ok and kt.dbx("SELECT user_id, role FROM org_members WHERE org_id=? ORDER BY user_id", (GO,)) == [(uid["mia"], "admin")],
      "hosted: swapping the admin in one step works, the operator stays out " + r.text[:160])
r = A.put(B + f"/api/orgs/{ORG}/members", json={"email": "hugo@example.com"})
check(r.ok and kt.dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (ORG, uid["hugo"])) and not kt.dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (ORG, uid["hugo"])),
      "hosted: the instance admin only invites an existing account " + r.text[:160])
check(login(B, "hugo").post(B + f"/api/orgs/{ORG}/join").ok and kt.dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (ORG, uid["hugo"])),
      "hosted: the person accepts and is a member")
r = A.patch(B + f"/api/users/{FID}", json={"orgs": [GO]})
check(r.ok and not kt.dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (GO, FID))
      and kt.dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=?", (GO, FID)),
      "hosted: the user dialog invites the freelancer instead of adding them " + r.text[:160])
check(Fr.get(B + "/api/state").json()["me"].get("workspaces") == [], "freelancer: still without an organisation until accepted")

# ---- 2.306.0 Fix-1 (#2875 review): hosted, the organisation keeps an admin of its own at every place the operator edits
def role(o, u):
    return kt.dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (o, u))


r = A.patch(B + f"/api/users/{uid['mia']}", json={"orgs": []})
check(r.status_code == 409 and role(GO, uid["mia"]) == [("admin",)] and not role(GO, 1),
      "hosted: the user dialog cannot take the last admin out, the operator does not take over " + r.text[:120])
r = A.patch(B + f"/api/admin/orgs/{GO}", json={"admins_remove": [uid["mia"]]})
check(r.status_code == 409 and role(GO, uid["mia"]) == [("admin",)], "hosted: the last admin is not demoted " + r.text[:120])
r = A.patch(B + f"/api/admin/orgs/{GO}", json={"admins": []})
check(r.status_code == 409 and role(GO, uid["mia"]) == [("admin",)], "hosted: the old admins set cannot empty it either " + r.text[:120])
dbw("INSERT INTO org_members(org_id, user_id, role) VALUES(?,?,'member')", (GO, uid["ivy"]))
r = A.patch(B + f"/api/admin/orgs/{GO}", json={"admins_add": [uid["ivy"]], "admins_remove": [uid["mia"]]})
check(r.ok and role(GO, uid["ivy"]) == [("admin",)] and role(GO, uid["mia"]) == [("member",)], "hosted: swapping the admin role works " + r.text[:120])
r = A.patch(B + f"/api/users/{uid['mia']}", json={"orgs": [DO]})  # Delta (no admin since the self-hosted part) stays as it is
check(r.ok and not role(GO, uid["mia"]) and not role(GO, 1), "hosted: a member is taken out by the user dialog, the operator stays out " + r.text[:120])
r = A.patch(B + f"/api/admin/orgs/{GO}", json={"members_add": [uid["bob"]], "admins_add": [uid["bob"]]})
check(r.ok and kt.dbx("SELECT role FROM org_joins WHERE org_id=? AND user_id=?", (GO, uid["bob"])) == [("admin",)],
      "hosted: invited + admin in one step: the invitation carries the admin role " + r.text[:120])
check(login(B, "bob").post(B + f"/api/orgs/{GO}/join").ok and role(GO, uid["bob"]) == [("admin",)], "hosted: accepted, the person is an admin")
r = A.patch(B + f"/api/admin/orgs/{GO}", json={"members_add": [1]})
check(r.status_code == 409 and not kt.dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=1", (GO,)) and not role(GO, 1),
      "hosted: the operator does not invite itself into a customer's organisation " + r.text[:120])
r = A.patch(B + "/api/users/1", json={"orgs": [ORG, GO]})
check(r.status_code == 409 and not kt.dbx("SELECT 1 FROM org_joins WHERE org_id=? AND user_id=1", (GO,)) and role(ORG, 1) == [("admin",)],
      "hosted: not through the user dialog either (nothing changed) " + r.text[:120])
check(Fr.patch(B + f"/api/admin/orgs/{GO}", json={"members_add": [FID]}).status_code == 403, "freelancer (no instance admin): 403 as before")

sys.exit(kt.done("p2306_d1_core_hardening"))
