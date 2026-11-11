#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.602.0 part D API test (#4507, #4508): fewer server queries, the same answers. Invented names only.
 - #4507: GET /api/state asks the participant lists of the viewer (plists) once, not once per caller; in a GET the request
   cache follows a membership change (acx_drop) at once, a caller cannot change the cached list, a write request and code
   outside a request read the database every time; for a person without an organisation (frida) as well
 - #4508: GET /api/v1/tags reads the list tags of all visible lists in one query, the list part equals the per-list route
   in the order of visible_lists; the approval hint of an agent's batch (h6e_batch_detail) gives the same text as the old
   one-query-per-list way; completing a repeating task copies its tags (user + tag) to the completed copy (bob and frida)
freelancer-matrix: lists, tags
usage: p2602_d_queries_test.py <datadir>      (a fresh container; P2602D_NOSTART=1 = the server already runs)"""
import json
import os
import subprocess
import sys
import uuid

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, CT, FAILS, OKS, check, sess  # noqa: E402

kt.fresh(prefix="P2602D")
A = kt.setup()
uid = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": kt.PASSWORD, "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
FID, Fr = freelancer(B, A)
uid["frida"] = FID
TODAY = kt.today()


def mklist(s, name):
    r = s.post(B + "/api/lists", json={"name": name})
    assert r.ok, r.text
    return r.json()["id"]


def share(s, lid, who, role):
    r = s.put(B + f"/api/lists/{lid}/members", json={"user_id": uid[who], "role": role})
    check(r.ok, f"setup: {who} {role} in {lid} {r.text[:160]}")


def ltag(s, lid, name):
    r = s.post(B + f"/api/lists/{lid}/tags", json={"name": name})
    check(r.status_code == 201, f"setup: list tag {name} in {lid} {r.text[:160]}")


def tok(s):
    r = s.post(B + "/api/me/tokens", json={"name": "t-" + uuid.uuid4().hex[:8], "scopes": ["read", "write"]})
    assert r.ok, r.text
    return r.json()["token"]


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    try:
        return json.loads(out[-1])
    except (IndexError, ValueError):
        check(False, f"in-app probe ran: {(r.stdout + r.stderr)[-800:]}")
        return {}


# ================================================================ setup
P = [mklist(Bo, f"Shoot {i}") for i in range(1, 6)]  # bob's lists
for lid in P[:3]:
    share(Bo, lid, "carol", "participant")
share(Bo, P[3], "carol", "edit")
F1, F2 = mklist(Fr, "Frida one"), mklist(Fr, "Frida two")  # freelancer-matrix: lists
share(Fr, F1, "carol", "participant")
share(Bo, P[0], "frida", "participant")  # frida (no organisation) as a participant
share(Bo, P[4], "frida", "participant")
for lid, names in ((P[0], ("zeta", "Alpha", "mid")), (P[1], ("beta",)), (P[3], ("Gamma", "delta")), (F1, ("f-b", "F-a")),
                   (F2, ("solo",))):
    for n in names:
        ltag(Bo if lid in P else Fr, lid, n)

PROBE_STATE = """
from kalmido.core import pg
import re
seen = []
orig = pg.Conn._pgx
def rec(self, sql, args=None):
    seen.append(sql if isinstance(sql, str) else str(sql))
    return orig(self, sql, args)
pg.Conn._pgx = rec
from kalmido.core.config import app as kapp
cl = kapp.test_client()
hh = {'X-Requested-With': 'kalmido'}
cl.post('/api/auth/login', json={'username': 'WHO', 'password': 'password123'}, headers=hh)
cl.get('/api/state', headers=hh)
seen.clear()
r = cl.get('/api/state', headers=hh)
pat = re.compile(r"FROM list_members WHERE user_id=\\S+ AND role='participant'")
print(json.dumps({'status': r.status_code, 'plists': sum(1 for x in seen if pat.search(x)),
                  'lists': sorted(x['id'] for x in r.get_json()['lists'])}))
"""

# ================================================================ #4507: /api/state asks plists once
for who, want in (("carol", sorted(P[:4] + [F1])), ("frida", None)):
    st = in_app(PROBE_STATE.replace("WHO", who))
    if st:
        print(f"PERF #4507 /api/state {who}: plists statements {st['plists']}", flush=True)
        check(st["status"] == 200 and st["plists"] == 1, f"#4507 {who}: /api/state reads the participant lists once ({st})")
        if want:
            check(set(want) <= set(st["lists"]), f"#4507 {who}: the same lists in the state {st['lists']}")
        else:
            check({P[0], P[4], F1, F2} <= set(st["lists"]), f"#4507 frida: her lists and the shared ones {st['lists']}")

# ================================================================ #4507: the cache follows membership changes
PROBE_CACHE = """
from flask import g
from kalmido.core.config import app as kapp
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.core.access import plists, acx_drop
U, L = UID, LID
res = {}
c = connect()
with system_ctx(c):
    with kapp.test_request_context('/api/state', method='GET'):
        p0 = plists(c, U)
        res['p0'] = p0
        p0.append(-1)
        res['untouched'] = plists(c, U) == res['p0'][:-1] and -1 not in plists(c, U)
        c.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,'participant','participant',99,'2026-11-06T00:00:00Z')", (L, U))
        res['cached'] = plists(c, U)
        acx_drop()
        res['added'] = plists(c, U)
        c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (L, U))
        acx_drop()
        res['removed'] = plists(c, U)
    with kapp.test_request_context('/api/tasks', method='POST'):
        a = plists(c, U)
        c.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,'participant','participant',99,'2026-11-06T00:00:00Z')", (L, U))
        res['post'] = [a, plists(c, U)]
        c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (L, U))
    a = plists(c, U)
    c.execute("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,'participant','participant',99,'2026-11-06T00:00:00Z')", (L, U))
    res['outside'] = [a, plists(c, U)]
c.rollback()
c.close()
print(json.dumps(res))
"""
for who, base, extra in (("carol", sorted(P[:3] + [F1]), P[4]), ("frida", sorted([P[0], P[4]]), P[1])):
    ca = in_app(PROBE_CACHE.replace("UID", str(uid[who])).replace("LID", str(extra)))
    if ca:
        new = sorted(base + [extra])
        check(ca["p0"][:-1] == base and ca["untouched"], f"#4507 {who}: plists as before, a caller cannot change the cached answer {ca}")
        check(ca["cached"] == base, f"#4507 {who}: in one GET the second call comes from the cache {ca['cached']}")
        check(ca["added"] == new and ca["removed"] == base, f"#4507 {who}: after acx_drop() the new membership counts (added / removed) {ca}")
        check(ca["post"] == [base, new], f"#4507 {who}: a write request reads the database every time {ca['post']}")
        check(ca["outside"] == [base, new], f"#4507 {who}: outside a request no cache {ca['outside']}")

# ================================================================ #4508: /api/v1/tags in one query, same answer
PROBE_TAGS = """
import re
from kalmido.core import pg
import kalmido.api.v1 as v1
seen, order = [], []
orig = pg.Conn._pgx
def rec(self, sql, args=None):
    seen.append(sql if isinstance(sql, str) else str(sql))
    return orig(self, sql, args)
pg.Conn._pgx = rec
vl = v1.visible_lists
def vl_rec(c, uid, *a, **k):
    out = vl(c, uid, *a, **k)
    order[:] = [d['id'] for d in out]
    return out
v1.visible_lists = vl_rec
from kalmido.core.config import app as kapp
cl = kapp.test_client()
h = {'Authorization': 'Bearer TOKEN'}
seen.clear()
r = cl.get('/api/v1/tags', headers=h)
# v1_tags' own query: before one 'list_id=' per list, now one '= ANY'; visible_lists' tag rows (list_id IN (...)) are not counted
# 2.947.0 (#5275): the project tags of the core (collab/reactions.py ltags_of_lists: one statement for all lists, the one of
# visible_lists -- v1_tags takes its tags from there, no statement of its own)
hit = [x for x in seen if re.search(r'FROM obj_tags ot WHERE ot.scope_kind=.list. AND ot.scope_id = ANY', x)]
n = len(hit)
per = {}
for lid in order:
    per[lid] = cl.get('/api/v1/lists/%d/tags' % lid, headers=h).get_json()['data']
print(json.dumps({'status': r.status_code, 'data': r.get_json()['data'], 'order': order, 'per': per, 'n': n, 'hit': hit}))
"""
for who, s, want in (("bob", Bo, [P[0], P[1], P[3]]), ("frida", Fr, [P[0], F1, F2]), ("carol", Ca, [P[0], P[1], P[3], F1])):
    tg = in_app(PROBE_TAGS.replace("TOKEN", tok(s)))
    if tg:
        got = [x for x in tg["data"] if x["kind"] == "list"]
        old = [{**x, "kind": "list"} for lid in tg["order"] for x in tg["per"][str(lid)]]
        print(f"PERF #4508 /api/v1/tags {who}: {len(tg['order'])} lists, {tg['n']} list tag statements", flush=True)
        check(tg["status"] == 200 and got == old and got, f"#4508 {who}: list tags = the per-list route in visible_lists' order {got} / {old}")
        check({x["list_id"] for x in got} >= set(want), f"#4508 {who}: the tags of every visible list {sorted({x['list_id'] for x in got})}")
        check(tg["n"] == 1, f"#4508 {who}: one query for the list tags of {len(tg['order'])} lists ({tg['hit']})")

# ================================================================ #4508: the approval hint of a batch
PROBE_HINT = """
import re
from flask import g
from kalmido.core import pg
from kalmido.core.config import app as kapp
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.core.access import list_role
from kalmido.core.i18n import tr
from kalmido.api.scopes import h6e_batch_detail
seen = []
orig = pg.Conn._pgx
def rec(self, sql, args=None):
    seen.append(sql if isinstance(sql, str) else str(sql))
    return orig(self, sql, args)
pg.Conn._pgx = rec
def old(c, approver, lg, lids, data):
    parts = []
    if data:
        parts.append(tr("Fields", lg=lg) + ": " + ", ".join(sorted(data))[:120])
    cnt = {}
    for x in lids:
        cnt[x] = cnt.get(x, 0) + 1
    names, hidden = [], 0
    for lid, n in sorted(cnt.items(), key=lambda kv: -kv[1]):
        r = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()
        if r and approver and list_role(c, lid, approver) and len(names) < 4:
            names.append(f"{r[0][:40]} ({n})")
        else:
            hidden += 1
    if hidden:
        names.append(tr("+{0} more", hidden, lg=lg))
    parts.append(tr("Projects", lg=lg) + ": " + ", ".join(names))
    return " · ".join(parts)
res = []
c = connect()
with system_ctx(c):
    for ap, lids, data in CASES:
        with kapp.test_request_context('/api/v1/tasks/batch', method='POST'):
            g.user = dict(c.execute('SELECT * FROM users WHERE id=1').fetchone())
            o = old(c, ap, 'en', lids, data)
        with kapp.test_request_context('/api/v1/tasks/batch', method='POST'):
            g.user = dict(c.execute('SELECT * FROM users WHERE id=1').fetchone())
            seen.clear()
            nw = h6e_batch_detail(c, ap, 'en', lids, data)
            res.append([o, nw, sum(1 for x in seen if re.search(r'SELECT (id, )?name FROM lists WHERE', x))])
c.close()
print(json.dumps(res))
"""
L6 = [P[0]] * 6 + [P[1]] * 5 + [P[2]] * 4 + [P[3]] * 3 + [P[4]] * 2 + [F1]  # 6 lists, 4 names at most, frida's list hidden
cases = [(uid["bob"], L6, {"due": 1, "title": 1}), (uid["bob"], [P[1], P[0], P[1]], {}), (uid["frida"], [F1, F1, P[0], P[2]], {"status": 1}),
         (uid["carol"], [P[3], P[0]], {}), (None, [P[0], P[1]], {"due": 1})]
hint = in_app(PROBE_HINT.replace("CASES", "json.loads(%r)" % json.dumps(cases)))
for (ap, lids, _), (o, nw, n) in zip(cases, hint or []):
    check(o == nw, f"#4508 approval hint for {ap} over {len(set(lids))} lists: same text ('{nw}' / '{o}')")
    check(n == (1 if lids else 0), f"#4508 approval hint for {ap}: the list rows in one query, not one per list ({n})")
if hint:
    check("Shoot 1 (6)" in hint[0][1] and "+2 more" in hint[0][1], f"#4508 bob: four names, the rest counted {hint[0][1]}")
    check("Frida one (2)" in hint[2][1] and "+1 more" in hint[2][1], f"#4508 frida: her list named, bob's one she does not see counted {hint[2][1]}")

# ================================================================ #4508: repeating copies the tags
for who, s, lid in (("bob", Bo, P[0]), ("frida", Fr, F2)):
    title = f"Clean the lens {who}"
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, "due": TODAY.isoformat(), "repeat": "FREQ=DAILY",
                                       "tags": ["kit", "Weekly", "zz"]})
    check(r.ok, f"setup: repeating task of {who} {r.text[:160]}")
    tid = r.json()["id"]
    r = s.post(B + "/api/tasks/batch", json={"ids": [tid], "action": "complete", "data": {}})
    check(r.ok, f"{who}: complete the repeating task {r.text[:160]}")
    cp = kt.dbx("SELECT id FROM tasks WHERE title=? AND status=2 AND id<>?", (title, tid))
    check(len(cp) == 1, f"#4508 {who}: one completed copy ({len(cp)})")
    if cp:
        tags = lambda t: sorted((r[0], r[1]) for r in kt.dbx("SELECT user_id, tag FROM (SELECT k.obj_id AS task_id, CAST(ot.scope_id AS BIGINT) AS user_id, ot.name AS tag FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id AND ot.scope_kind='user' WHERE k.kind='task') task_tags WHERE task_id=?", (t,)))  # noqa: E731
        orig = tags(tid)
        check(len(orig) == 3 and tags(cp[0][0]) == orig and {u for u, _ in orig} == {uid[who]},
              f"#4508 {who}: the copy carries the same tags (user + tag) {tags(cp[0][0])} / {orig}")

print(f"\np2602_d_queries: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
