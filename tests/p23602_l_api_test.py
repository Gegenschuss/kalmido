#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.360.2 part L (#2561): limits and leftovers of the security audit. Invented names only.
freelancer-matrix: personal
 (1) a key rotation locks writes on every process: a row in settings gives 503 (JSON, header X-Kalmido-Maint) for writes
     of people with and without an organisation, reads and signing in stay open, a lock that ran out or was cleared frees
     the server; rotate_org sets the lock before the key switch and clears it after an error; running writers are waited for
 (2) an organisation's webhook never carries the name of a file filed with a hub mail
 (3) the readable filed mails are a subquery with the same answers as hbm_node_ok, mail by mail
 (4) the watchdog queues the Karakeep sync instead of running it
 (5) a table has a byte cap (cell writes and sheet copies)
 (6) a booking page out of its mails: one News item per day for the owner
 (7) signature pictures and imported letterheads wait for the scanner
usage: p23602_l_api_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm
from freelancer_fixture import freelancer
from kt import FAILS, OKS, check, sess

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
NOW = "2026-10-01T00:00:00Z"


def dbw(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        cur = c.execute(sql, args)
        rows = cur.fetchall() if "RETURNING" in sql.upper() or sql.lstrip().upper().startswith("SELECT") else []
        c.commit()
        return rows
    finally:
        c.close()


def in_app(code):
    """Lines of Python inside the container; prints the JSON of `out`."""
    head = "import json\nimport app\nfrom kalmido.core.config import app as flask_app\nfrom kalmido.core.db import connect\nc = connect()\n"
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", head + code + "\nprint('OUT' + json.dumps(out))"],
                       capture_output=True, text=True, timeout=200)
    for line in r.stdout.splitlines():
        if line.startswith("OUT"):
            return json.loads(line[3:])
    raise AssertionError(r.stdout[-800:] + r.stderr[-1500:])


def wait_for(fn, t=15.0):
    end = time.monotonic() + t
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return fn()


def news(s, kind):
    r = s.get(B + "/api/news")
    return [x for x in r.json().get("items", []) if x["kind"] == kind] if r.ok else []


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
               env=dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_SHEET_MB_MAX=1"))
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordlicht", "lang": "en", "collab_all": True, "time_all": True, "modules": ["cal", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ALICE, ORG = (lambda m: (m["id"], m["workspaces"][0]["id"]))(A.get(B + "/api/state").json()["me"])
BOB = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"}).json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en"})
FID, Fr = freelancer(B, A)

# ================================================================== (1) the rotation's write lock
SET = "INSERT INTO settings(key,value) VALUES('rot_write_lock',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value"


def write(s):
    return s.post(B + "/api/lists", json={"name": "Lock probe"})


dbw(SET, (str(time.time() + 300),))
r = wait_for(lambda: (lambda x: x if x.status_code == 503 else None)(write(A)))
check(r is not None and r.json().get("maint") is True, "(1) a write is refused with 503 while the lock holds")
check(r is not None and r.headers.get("X-Kalmido-Maint") == "1" and r.headers.get("Retry-After"), "(1) the header keeps the client's change in its queue")
check(write(Fr).status_code == 503, "(1) the same for a person without an organisation")
check(A.get(B + "/api/state").status_code == 200, "(1) reading stays open")
check(requests.post(B + "/api/auth/login", headers=H, json={"username": "bob", "password": "password123"}).ok, "(1) signing in stays open")
dbw(SET, (str(time.time() - 5),))
check(wait_for(lambda: write(A).ok), "(1) a lock that ran out frees the server (a dead rotation)")
dbw(SET, (str(time.time() + 300),))
wait_for(lambda: write(A).status_code == 503)
dbw(SET, ("",))
check(wait_for(lambda: write(Fr).ok), "(1) a cleared lock frees the server")

j = in_app("""
import time
from kalmido.admin import orgcrypt_cli as cl
from kalmido.core import orgcrypt as oc
from kalmido.core.db import gsetting
cl.ROT_SETTLE = 0
seen = {}
def boom(c2, oid):
    seen["held"] = float(gsetting(c2, oc.ROT_LOCK_KEY) or 0) > time.time()
    raise oc.OrgCryptError("boom")
oc.rck_rot_begin = boom
try:
    cl.rotate_org(c, 1)
except oc.OrgCryptError:
    seen["raised"] = True
c.rollback()
seen["after"] = gsetting(c, oc.ROT_LOCK_KEY)
c.commit()
# review: the lock lasts for the switch only, the long run works without it
def nolock(*a):
    seen["during"] = gsetting(c, oc.ROT_LOCK_KEY)
    c.commit()
    raise oc.OrgCryptError("boom")
oc.rck_rot_begin, cl.rot_fields = (lambda c2, oid: (b"", b"", None)), nolock
try:
    cl.rotate_org(c, 1)
except oc.OrgCryptError:
    c.rollback()
# review: a failed wait for the writers leaves no lock behind
cl.ROT_SETTLE, keep = 1.0, cl._rot_older_xacts
def fail(*a):
    raise RuntimeError("boom")
cl._rot_older_xacts, cl.oc.ROT_LOCK_TTL, ttl = fail, 0, cl.oc.ROT_LOCK_TTL
try:
    cl.rot_lock_on(c)
except RuntimeError:
    c.rollback()
cl._rot_older_xacts, cl.oc.ROT_LOCK_TTL = keep, ttl
seen["failed"] = gsetting(c, oc.ROT_LOCK_KEY)
c.commit()
# a transaction older than the lock is waited for, within the limit
c2 = connect()
c2.execute("SELECT 1 FROM users LIMIT 1").fetchall()
cl.ROT_SETTLE = 1.0
t = time.monotonic()
cl.rot_lock_off(c, cl.rot_lock_on(c))
seen["waited"] = time.monotonic() - t
c2.commit()
seen["after2"] = gsetting(c, oc.ROT_LOCK_KEY)
c.commit()
out = seen
""")
check(j.get("held") and j.get("raised"), f"(1) rotate_org holds the lock at the key switch {j}")
check(j.get("after") == "" and j.get("after2") == "", f"(1) the lock is cleared after an error, too {j}")
check(j.get("during") == "", f"(1) review: the run after the switch holds no lock {j}")
check(j.get("failed") == "", f"(1) review: a failed wait clears the lock {j}")
check(j.get("waited", 0) >= 3.0, f"(1) the wait covers the gate's cache and an older transaction {j}")

# ================================================================== (2) + (3) filed mails
check(wait_for(lambda: write(A).ok), "(1) free again after the run")
LO = A.post(B + "/api/lists", json={"name": "Team mail", "org_id": ORG}).json()["id"]
assert A.put(B + f"/api/lists/{LO}/members", json={"user_id": BOB, "role": "edit"}).ok
LOTHER = A.post(B + "/api/lists", json={"name": "Closed", "org_id": ORG, "org_visibility": "private"}).json()["id"]
LP = A.post(B + "/api/lists", json={"name": "Mine"}).json()["id"]
CLI = A.post(B + "/api/clients", json={"name": "Invented Customer", "org_id": ORG})
CID = CLI.json()["id"] if CLI.ok else None


def mail(owner, org, lid=None, cid=None):
    ws = f"o{org}" if org else f"u{owner}"
    mid = dbw("INSERT INTO hub_mails(owner_id, org_id, list_id, client_id, ws, message_id, subject, created_at) VALUES(?,?,?,?,?,?,'Invented',?) RETURNING id",
              (owner, org, lid, cid, ws, f"<p23602-{time.monotonic_ns()}@example.test>", NOW))[0][0]
    nid = dbw("INSERT INTO fs_nodes(kind, name, owner_id, org_id, created_at, updated_at, hub_mail_id) VALUES('file',?,?,?,?,?,?) RETURNING id",
              (f"Secret subject {mid}.eml", owner, org, NOW, NOW, mid))[0][0]
    dbw("UPDATE hub_mails SET eml_id=? WHERE id=?", (nid, mid))
    return mid, nid


M_ORG, N_ORG = mail(ALICE, ORG, LO)
M_CLOSED, _ = mail(ALICE, ORG, LOTHER)
M_OWN, _ = mail(ALICE, ORG)
M_PRIV, N_PRIV = mail(ALICE, None, LP)
M_FR, _ = mail(FID, None)
M_WRONG, _ = mail(ALICE, None, LO)  # the list's organisation differs from the mail's: never readable
MAILS = [M_ORG, M_CLOSED, M_OWN, M_PRIV, M_FR, M_WRONG]
if CID:
    MAILS.append(mail(ALICE, ORG, None, CID)[0])
PLAIN = dbw("INSERT INTO fs_nodes(kind, name, owner_id, org_id, created_at, updated_at) VALUES('file','plain.txt',?,?,?,?) RETURNING id", (ALICE, ORG, NOW, NOW))[0][0]
j = in_app(f"""
from flask import g
from kalmido.integrations.webhooks import who_obj
from kalmido.hub.hubmail import hbm_node_ok, hbm_node_mail_ids
from kalmido.files.store import _mail_hidden
from kalmido.core.pg import system_ctx
out = {{}}
with system_ctx(c):
    out["org_mail"] = who_obj(c, "file", {N_ORG}, "file.created")
    out["plain"] = bool(who_obj(c, "file", {PLAIN}, "file.created"))
    out["private_mail"] = bool(who_obj(c, "file", {N_PRIV}, "file.created"))
    for uid in ({ALICE}, {BOB}, {FID}):
        with flask_app.test_request_context("/"):
            out[f"sql{{uid}}"] = sorted(x for x in hbm_node_mail_ids(c, uid) if x in {MAILS})
            out[f"one{{uid}}"] = sorted(m for m in {MAILS} if hbm_node_ok(c, uid, m))
            out[f"clause{{uid}}"] = _mail_hidden(c, uid)
""")
check(j["org_mail"] is None, "(2) an organisation's filed mail sends no file event with its subject")
check(j["plain"], "(2) an ordinary file still sends its event")
check(j["private_mail"], "(2) a private filed mail stays with its owner's own webhook")
for uid, who in ((ALICE, "owner"), (BOB, "member"), (FID, "person without an organisation")):
    check(j[f"sql{uid}"] == j[f"one{uid}"], f"(3) the subquery answers like hbm_node_ok for the {who}: {j[f'sql{uid}']} / {j[f'one{uid}']}")
    check("SELECT m.id FROM hub_mails m" in j[f"clause{uid}"], f"(3) a subquery, no id list, for the {who}")
check(M_ORG in j[f"sql{BOB}"] and M_OWN not in j[f"sql{BOB}"], "(3) the member reads the list's mail, not someone's own one")
check(M_WRONG not in j[f"sql{ALICE}"], "(3) a list of another organisation than the mail's gives no right")
check(j[f"sql{FID}"] == [M_FR], "(3) a person without an organisation reads her own filed mail only")

# ================================================================== (4) Karakeep
dbw("INSERT INTO kk_conns(user_id, url, token, created_at) VALUES(?, 'http://127.0.0.1:9', 'x', ?)", (FID, NOW))
j = in_app(f"""
import kalmido.life.karakeep as kk
from kalmido.core.pg import system_ctx
called = []
kk.kk_sync = lambda *a: called.append(a)
kk._wd_reading(c, {{{FID}}}, {{{FID}: {{"features": "reading"}}}}, None, None)
c.commit()
with system_ctx(c):
    n = c.execute("SELECT COUNT(*) FROM bg_jobs WHERE kind='life:karakeep' AND user_id=?", ({FID},)).fetchone()[0]
    kk._wd_reading(c, {{{FID}}}, {{{FID}: {{"features": "reading"}}}}, None, None)
    n2 = c.execute("SELECT COUNT(*) FROM bg_jobs WHERE kind='life:karakeep' AND user_id=?", ({FID},)).fetchone()[0]
c.commit()
out = {{"called": len(called), "n": n, "n2": n2}}
""")
check(j["called"] == 0 and j["n"] >= 1, f"(4) the watchdog queues the sync {j}")
check(j["n2"] == j["n"], f"(4) one waiting job per person {j}")

# ================================================================== (5) the byte cap of a table (the test server: 1 MB)
SH = Fr.post(B + "/api/sheets", json={"title": "Budget", "space": "private"}).json()["id"]
assert Fr.put(B + f"/api/sheets/{SH}/cells", json={"cells": [{"cell": "A1", "raw": "x"}]}).ok
TAB = Fr.post(B + f"/api/sheets/{SH}/tabs", json={"name": "Copy before", "copy_of": SH})
check(TAB.ok, f"(5) a small copy works: {TAB.status_code} {TAB.text[:200]}")
dbw("UPDATE sheet_cells SET raw=repeat('x', 1100000) WHERE sheet_id=?", (SH,))
r = Fr.put(B + f"/api/sheets/{SH}/cells", json={"cells": [{"cell": "A2", "raw": "more"}]})
check(r.status_code == 400 and "1 MB" in r.text, f"(5) a table over its size takes no new cell: {r.status_code} {r.text[:200]}")
r = Fr.post(B + f"/api/sheets/{SH}/tabs", json={"name": "Copy after", "copy_of": SH})
check(r.status_code == 400 and "1 MB" in r.text, f"(5) nor a copy of a sheet: {r.status_code} {r.text[:200]}")
r = Fr.put(B + f"/api/sheets/{SH}/cells", json={"cells": [{"cell": "A1", "raw": ""}]})
check(r.ok, f"(5) emptying a cell stays possible: {r.status_code} {r.text[:200]}")
check(Fr.put(B + f"/api/sheets/{SH}/cells", json={"cells": [{"cell": "A2", "raw": "fine"}]}).ok, "(5) below the cap writing works")

# ================================================================== (6) the booking page's quota
j = in_app(f"""
from kalmido.calendars import apptbook as ab
from kalmido.core.db import now_utc
from kalmido.core.pg import system_ctx
day = now_utc().strftime("%Y-%m-%d")
out = {{}}
with system_ctx(c):
    c.execute("INSERT INTO mail_counts(k,day,n) VALUES(?,?,?) ON CONFLICT(k) DO UPDATE SET day=excluded.day, n=excluded.n", (f"apb:{FID}", day, ab.APB_MAIL_DAY))
    out["first"] = ab.apb_mail_quota(c, {FID})
    out["second"] = ab.apb_mail_quota(c, {FID})
c.commit()
""")
check(j["first"] is False and j["second"] is False, "(6) the quota refuses")
items = news(Fr, "apblimit")
check(len(items) == 1, f"(6) one News item a day for the owner: {len(items)}")
check(items and (items[0].get("data") or {}).get("limit"), "(6) it names the limit, no customer")
check(not news(A, "apblimit"), "(6) nobody else gets it")

# ================================================================== (7) scanner leftovers
j = in_app("""
import base64, types
from kalmido.core.errors import BadInput
from kalmido.files import scan
from kalmido.files.upsafe import UploadRefused
import kalmido.files.upsafe as up
from kalmido.admin import orgimport as oi, oi_office, acctimport
from kalmido.office import letters
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
out = {}
for st in ("unchecked", "off", "clean"):
    scan.sc_scan = lambda n, d, st=st: st
    try:
        letters.lt_image_in("data:image/png;base64," + base64.b64encode(PNG).decode())
        out[st] = "ok"
    except BadInput as e:
        out[st] = str(e)
# the letterhead of an organisation import asks for the strict check, a plain file does not
got = []
ctx = types.SimpleNamespace(space=1, run=types.SimpleNamespace(), file=lambda *a, **k: got.append(k.get("strict")) or None)
oi_office._oi_put(ctx, "a.pdf", "b.pdf", strict=True)
oi_office._oi_put(ctx, "a.pdf", "c.pdf")
out["put"] = got
warn = []
run = types.SimpleNamespace(written=[], warning=lambda *a: warn.append(a), stopped=None)
ctx = types.SimpleNamespace(c=c, run=run, uid=1, zf=None, files={})
acctimport._file_bytes = lambda *a: b"%PDF-1.4 invented"
up.up_check = lambda c, n, raw, *a: (raw, "application/pdf", {"scan": "unchecked"})
oi.quota_guard = None
import kalmido.admin.hosting as ho
ho.quota_guard = lambda *a: None
out["strict"] = oi.oi_file(ctx, "x.pdf", None, "x.pdf", space=1, base="/tmp", strict=True, seal=False)
out["warned"] = len(warn)
""")
check(j["unchecked"] != "ok", f"(7) a signature waits while the scanner cannot check it: {j['unchecked']}")
check(j["off"] == "ok" and j["clean"] == "ok", "(7) scanner off or clean: as before")
check(j["put"] == [True, False], "(7) _oi_put hands the strict check on")
check(j["strict"] is None and j["warned"] == 1, "(7) an imported letterhead is left out with a warning")

print(f"p23602_l: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
