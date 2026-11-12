#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.369.6 API tests (#3139 one GET = one transaction: the RLS context is set once, not per helper).
Invented people and texts only.
freelancer-matrix: lists, tasks
 - the second GET /api/state of an organisation member and of a person without an organisation: few set_config calls
   (audit Q 28.10.2026: 22) and no commit in the middle of the request (counted in the app, PERF lines with the callers)
 - the answer stays the same: the second state equals the first (lists, tasks, me)
 - the connection layer: the statement right after a system_ctx() block reads as the person again (also after a savepoint
   inside it, an error rolled back to a savepoint, a commit); two blocks in a row switch once; set_ctx applies with the
   next statement
usage: p2369_6_api_test.py <datadir>"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, CT, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

FEATURES = "cal,collab,comments,events,fields,progress,time"


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    return out[-1] if out else "ERR " + r.stderr[-900:]


A = kt.setup()
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
uid = {}
for u in ("bob", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Da = sess("bob"), sess("dave")
for s in (A, Bo, Da):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok
FID, Fr = freelancer(B, A, features=FEATURES)  # freelancer-matrix: lists, tasks


def mk(s, name, **kw):
    r = s.post(B + "/api/lists", json={"name": name, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def task(s, title, lid, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.ok, r.text
    return r.json()["id"]


for i in range(4):
    lid = mk(A, f"Board {i}", org_id=ORG)
    assert A.put(B + f"/api/lists/{lid}/members", json={"user_id": uid["bob"], "role": "edit"}).ok
    for j in range(3):
        task(A, f"Card {i}.{j}", lid)
own = mk(Bo, "Bob private")
task(Bo, "Bob's own", own)
for i in range(2):
    lid = mk(Fr, f"Project {i}")
    for j in range(3):
        task(Fr, f"Step {i}.{j}", lid)

PROBE = """
import traceback
from collections import Counter
from kalmido.core import pg
ev = []
o_pgx, o_commit, o_rb = pg.Conn._pgx, pg.Conn.commit, pg.Conn.rollback
def who():
    out = [f"{f.filename.split('/kalmido/')[-1]}:{f.lineno} {f.name}" for f in reversed(traceback.extract_stack()[:-2])
           if not f.filename.endswith(('core/pg.py', 'contextlib.py')) and '/kalmido/' in f.filename]
    return ' < '.join(out[:3]) or '?'
def pgx(self, sql, args=None):
    q = ' '.join(str(sql).split())
    k = 'S' if q.startswith("SELECT set_config('app.user_id'") else 'Q'
    ev.append([id(self), k, (args[2] if k == 'S' else q[:70]), who() if k == 'S' else ''])
    return o_pgx(self, sql, args)
def commit(self):
    ev.append([id(self), 'C', '', who() if self._pg.info.transaction_status != 0 else 'idle'])
    return o_commit(self)
def rollback(self):
    ev.append([id(self), 'R', '', who()])
    return o_rb(self)
pg.Conn._pgx, pg.Conn.commit, pg.Conn.rollback = pgx, commit, rollback
from kalmido.core.config import app as kapp
cl = kapp.test_client()
hh = {'X-Requested-With': 'kalmido'}
cl.post('/api/auth/login', json={'username': USER, 'password': 'password123'}, headers=hh)
r1 = cl.get('/api/state', headers=hh)
ev.clear()
r2 = cl.get('/api/state', headers=hh)
a, b = r1.get_json(), r2.get_json()
same = all(a.get(k) == b.get(k) for k in ('lists', 'tasks', 'me'))
conns = {e[0] for e in ev}
sets = [e for e in ev if e[1] == 'S']
commits = [e for e in ev if e[1] == 'C' and e[3] != 'idle']
seq = [f"{e[2]}@{e[3]}" for e in sets]
print(json.dumps({'seq': seq, 'status': r2.status_code, 'same': same, 'n': len(ev), 'conns': len(conns), 'set': len(sets),
                  'commit': len(commits), 'set_by': Counter(f"{e[2]} {e[3]}" for e in sets).most_common(12),
                  'commit_by': Counter(e[3] for e in commits).most_common(12)}))
"""


def probe(user):
    out = in_app(f"USER = {user!r}\n" + PROBE)
    try:
        return json.loads(out)
    except ValueError:
        check(False, f"#3139 the statement probe ran for {user}: {out[:900]}")
        return {}


for user, label in (("bob", "organisation member"), ("frida", "without an organisation (freelancer-matrix: lists)")):
    p = probe(user)
    if not p:
        continue
    print(f"PERF #3139 second /api/state as {user}: {p['n']} events, {p['conns']} connections, {p['set']} set_config, "
          f"{p['commit']} commits", flush=True)
    print(f"PERF #3139 set_config in order: {p['seq']}", flush=True)
    print(f"PERF #3139 commits by: {p['commit_by']}", flush=True)
    check(p["status"] == 200 and p["same"], f"#3139 {label}: the second state answers the same as the first")
    check(0 < p["set"] <= 4, f"#3139 {label}: at most 4 set_config in the second /api/state (audit Q 28.10.2026: 22) - {p['set']}")
    check(p["commit"] <= 1, f"#3139 {label}: the GET runs in one transaction (commits in the middle: {p['commit_by']})")

# ================================================================ the connection layer: the context before every statement
LAYER = """
from kalmido.core import pg
from kalmido.core.config import DATABASE_URL
n = [0]
o_apply = pg.Conn._apply_ctx
def apply(self):
    n[0] += 1
    return o_apply(self)
pg.Conn._apply_ctx = apply
role = lambda c: c.execute("SELECT current_setting('app.role', true), current_setting('app.user_id', true)").fetchone()
out = {}
c = pg.connect_direct(DATABASE_URL)
c.set_ctx(7, (), "user")
out['start'] = list(role(c))
with pg.system_ctx(c):
    out['inside'] = list(role(c))
out['after'] = list(role(c))  # the very next statement after the block reads as the person again
n[0] = 0
with pg.system_ctx(c):
    c.execute("SELECT 1")
with pg.system_ctx(c):
    c.execute("SELECT 1")
out['two_blocks'] = n[0]  # two blocks in a row: one switch to system, none back in between
out['after2'] = list(role(c))
with pg.system_ctx(c):
    with c.savepoint():
        c.execute("SELECT 1")
out['after_sp'] = list(role(c))
c.execute("SAVEPOINT x")
try:
    with pg.system_ctx(c):
        c.execute("SELECT 1/0")
except Exception:
    pass
c.execute("ROLLBACK TO SAVEPOINT x")  # aborted inside the block: the rollback runs, the person's context follows
out['after_err'] = list(role(c))
c.commit()
out['after_commit'] = list(role(c))
c.set_ctx(9, (), "agent")
out['set_ctx'] = list(role(c))
c.rollback()
c.close()
print(json.dumps(out))
"""
L = in_app(LAYER)
try:
    L = json.loads(L)
except ValueError:
    check(False, f"#3139 the layer probe ran: {L[:900]}")
    L = {}
if L:
    U = ["user", "7"]
    check(L["start"] == U and L["inside"] == ["system", ""], f"#3139 the block reads as system {L}")
    check(L["after"] == U, f"#3139 the first statement after a system block reads as the person again {L['after']}")
    check(L["two_blocks"] == 1 and L["after2"] == U, f"#3139 two system blocks in a row: one switch, then the person {L}")
    check(L["after_sp"] == U, f"#3139 a savepoint inside the block: the person after it {L['after_sp']}")
    check(L["after_err"] == U, f"#3139 an error inside the block, rolled back to a savepoint: the person {L['after_err']}")
    check(L["after_commit"] == U, f"#3139 after a commit the next transaction opens as the person {L['after_commit']}")
    check(L["set_ctx"] == ["agent", "9"], f"#3139 a new context inside a transaction applies with the next statement {L['set_ctx']}")

# 2.997.0 (#5137, review): /api/state probes fs_shares in the person's context (lists/groups.py grp_shares_any,
# lists/lffolder.py lf_people_rows, core/state.py) and skips the system read when the probe finds nothing - that holds only
# while fs_shares has no row-level policy; one there (e.g. an org_id column picked up by rls.apply) would hide other
# workspaces' folder shares silently. Then move the probes into system_ctx() again.
fs_rls = kt.dbx("SELECT relrowsecurity FROM pg_class WHERE relname='fs_shares' AND relnamespace='public'::regnamespace")
check(fs_rls == [(False,)] or (fs_rls and not fs_rls[0][0]), f"#5137 fs_shares has no row-level security (the probes rely on it) {fs_rls}")

sys.exit(kt.done("p2369_6_api"))
