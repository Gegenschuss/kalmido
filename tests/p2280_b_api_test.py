#!/usr/bin/env python3
"""2.280.0 API tests, part B (#3116): the helpers per list in the start state and the time report ask the database once for
all lists, with the same answers. Own container (start.sh). Invented people and texts only.
freelancer-matrix: lists, time
 - the new bulk helpers give exactly what the old per-list helpers give (in the app, same database context): repositories
   (own, folder, switched off, none), notification limits (list / folder / default), group shares + names, list roles
 - GET /api/state: notif_cap, repos, groups and the role of an organisation list for a read-only member are as expected;
   the statements no longer grow per foreign list (2 vs 30 shared lists without a repository)
 - GET /api/time/report: the same sums and list names; the statements do not grow with the number of visible lists
 - a person without an organisation: a shared list with its limit and repository, their own time report
 - PERF lines (information): the statement counts
usage: p2280_b_api_test.py <datadir>   (P2280B_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import json
import os
import re
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

from kt import FAILS, OKS, check, B, H, DATA  # noqa: E402
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FEATURES = "cal,collab,comments,events,fields,progress,time"
TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')
DAY = "2026-10-05"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    return out[-1] if out else "ERR " + r.stderr[-600:]


if not (os.environ.get("P2280B_NOSTART") or os.environ.get("KMT_NOSTART")):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha"})
assert r.status_code in (200, 201), r.text
ORG = r.json()["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "vera", "carol"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
dbx("UPDATE org_members SET role='readonly' WHERE org_id=? AND user_id=?", (ORG, uid["carol"]), write=True)
Bo, Ve, Ca = login(B, "bob"), login(B, "vera"), login(B, "carol")
for s in (A, Bo, Ve, Ca):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok
FID, Fr = freelancer(B, A, features=FEATURES)  # freelancer-matrix: lists, time
uid["frida"] = FID


def mklist(s, name, **kw):
    r = s.post(B + "/api/lists", json={"name": name, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def share(lid, who, role="edit"):
    check(Bo.put(B + f"/api/lists/{lid}/members", json={"user_id": uid[who], "role": role}).ok, f"setup: {who} {role} in {lid}")


def state_lists(s):
    r = s.get(B + "/api/state")
    assert r.ok, r.text
    return r, {x["id"]: x for x in r.json()["lists"]}


def git_conn(lid, repo, folder=None):
    """A repository row straight into the database (never polled: next_at far away; the API would ask the provider)."""
    cid = dbx("INSERT INTO git_conns(list_id, provider, base_url, owner, repo, next_at, created_by, created_at) "
              "VALUES(?, 'gitea', 'http://127.0.0.1:9', 'acme', ?, 9e12, ?, '2026-10-01T00:00:00Z') RETURNING id",
              (lid, repo, uid["bob"]), write=True)[0][0]
    if folder:
        dbx("INSERT INTO git_folders(conn_id, owner_id, folder, created_at) VALUES(?, ?, ?, '2026-10-01T00:00:00Z')",
            (cid, uid["bob"], folder), write=True)
    return cid


def report(s):
    r = s.get(B + "/api/time/report", params={"from": DAY, "to": DAY, "scope": "mine"})
    assert r.ok, r.text
    return r, r.json()


# ================================================================ setup: bob's lists shared with vera (and frida)
OWN = mklist(Bo, "Own repo", kind="project")       # a repository of its own
FP = mklist(Bo, "Folder project", kind="project")  # uses the folder's repository
OFF = mklist(Bo, "Folder off", kind="project")     # in the folder, switched off
PLAIN = mklist(Bo, "Plain")                        # no repository
GRP = mklist(Bo, "Group list")                     # shared with a group
OL = mklist(Bo, "Org list", org_id=ORG)            # an organisation list, carol read-only in the organisation
for lid in (OWN, FP, OFF, PLAIN, GRP):
    share(lid, "vera")
share(OL, "carol")
FL = mklist(Fr, "Frida's project", kind="project")  # freelancer-matrix: lists (her own repository, no organisation)
for lid in (FP, OFF):
    check(Bo.patch(B + f"/api/lists/{lid}", json={"folder": "Studio/Cuts"}).ok, f"setup: list {lid} into bob's folder")
dbx("UPDATE lists SET git_folder_off=1 WHERE id=?", (OFF,), write=True)
C_OWN = git_conn(OWN, "own")
C_F = git_conn(FP, "folder", folder="Studio")
C_FR = git_conn(FL, "frida")
r = Bo.put(B + "/api/folders/notify-template", json={"folder": "Studio", "tpl": "work"})
check(r.ok, "setup: bob limits his folder Studio to 'work' " + r.text[:120])
r = Bo.put(B + f"/api/lists/{PLAIN}/notify-template", json={"tpl": "custom", "custom": {"comment": 1}, "user_id": uid["vera"]})
check(r.ok, "setup: bob's own choice for vera in Plain " + r.text[:160])
r = A.post(B + "/api/admin/groups", json={"name": "Editors", "members": [uid["bob"], uid["vera"]]})
check(r.ok, "setup: group " + r.text[:120])
GID = r.json()["id"]
r = Bo.put(B + f"/api/lists/{GRP}/groups/{GID}", json={"role": "view"})
check(r.ok, "setup: Group list shared with the group " + r.text[:200])

# ================================================================ the bulk helpers = the per-list helpers (in the app)
vlists = sorted(state_lists(Ve)[1])
CODE = """
from flask import g
from kalmido.core.config import app as kapp
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx, st_ids
from kalmido.integrations.git import git_conns_of_list, git_repos_of_lists
from kalmido.integrations.gitfolder import gf_conns_of_lists
from kalmido.notify import caps
from kalmido.lists.groups import grp_shares_of_list, grp_shares_of_lists, grp_name
from kalmido.core.access import list_roles, _list_role
ids, uid = IDS, UID
res = {}
c = connect()
with kapp.test_request_context('/api/state'):
    with system_ctx(c):
        old = {l: [r['id'] for r in git_conns_of_list(c, l)] for l in ids}
        res['git_old'] = {str(k): v for k, v in old.items() if v}
        res['git_new'] = {str(k): [r['id'] for r in v] for k, v in gf_conns_of_lists(c, ids).items()}
        old = {l: caps._tpl_for(c, l, uid) for l in ids}
        caps.tpl_prefetch(c, ids, uid)
        res['tpl_same'] = old == {l: g._notif_tpl[(l, uid)] for l in ids}
        res['tpl'] = {str(k): (v or {}).get('tpl') for k, v in old.items()}
        rows = c.execute('SELECT id, owner_id, folder, is_inbox FROM lists WHERE id = ANY(CAST(? AS BIGINT[]))', (st_ids(ids),)).fetchall()
        sh, nm = grp_shares_of_lists(c, rows)
        old = {l: sorted(grp_shares_of_list(c, l)) for l in ids}
        res['grp_same'] = {k: v for k, v in old.items() if v} == {k: sorted(v) for k, v in sh.items()} and \\
            all(nm.get(x[0]) == grp_name(c, x[0]) for v in sh.values() for x in v)
        res['grp'] = {str(k): [list(x) for x in v] for k, v in sh.items()}
        old = {l: _list_role(c, l, uid) for l in ids}
        res['roles_same'] = list_roles(c, uid, ids) == old
        res['roles'] = {str(k): v for k, v in old.items()}
        res['repos'] = {str(k): [d['full_name'] for d in v] for k, v in git_repos_of_lists(c, ids).items()}
c.close()
print(json.dumps(res))
"""


def compare(who, ids):
    out = in_app(CODE.replace("IDS", json.dumps(ids)).replace("UID", str(uid[who])))
    try:
        return json.loads(out)
    except ValueError:
        check(False, f"in-app comparison for {who} ran: {out[:600]}")
        return {}


eq = compare("vera", vlists)
if eq:
    check(eq["git_new"] == eq["git_old"] and eq["git_new"] == {str(OWN): [C_OWN], str(FP): [C_F]},
          f"#3116 repositories in bulk = per list (own, folder, switched off, none) {eq['git_new']} / {eq['git_old']}")
    check(eq["tpl_same"] and eq["tpl"][str(PLAIN)] == "custom" and eq["tpl"][str(FP)] == "work" and eq["tpl"][str(OWN)],
          f"#3116 notification limits in bulk = per list (member / folder / default) {eq['tpl']}")
    check(eq["grp_same"] and eq["grp"] == {str(GRP): [[GID, "view", "list"]]}, f"#3116 group shares in bulk = per list {eq['grp']}")
    check(eq["roles_same"] and eq["roles"][str(OWN)] == "edit", f"#3116 list_roles = list_role one by one {eq['roles']}")
    check(eq["repos"] == {str(OWN): ["acme/own"], str(FP): ["acme/folder"]}, f"#3116 git_repos_of_lists {eq['repos']}")
eqc = compare("carol", [OL])
if eqc:
    check(eqc["roles_same"] and eqc["roles"] == {str(OL): "view"}, f"#3116 list_roles: read-only in the organisation -> view {eqc['roles']}")

# ================================================================ /api/state: the same answers
_, L = state_lists(Ve)
check(L[OWN]["repos"] and L[OWN]["repos"][0]["full_name"] == "acme/own" and L[OWN]["repos"][0]["folder"] is None,
      f"#3116 state: the list's own repository {L[OWN]['repos']}")
check([x["full_name"] for x in L[FP]["repos"]] == ["acme/folder"] and L[FP]["repos"][0]["folder"] == "",
      f"#3116 state: the folder's repository (folder name private for vera) {L[FP]['repos']}")
check(L[OFF]["repos"] == [] and L[PLAIN]["repos"] == [], "#3116 state: switched off / no repository: none")
check(L[PLAIN]["notif_cap"] and L[PLAIN]["notif_cap"]["tpl"] == "custom" and L[PLAIN]["notif_cap"]["allowed"] == ["comment"]
      and L[PLAIN]["notif_cap"]["by"] == "Bob", f"#3116 state: bob's own choice for vera {L[PLAIN]['notif_cap']}")
check(L[FP]["notif_cap"] and L[FP]["notif_cap"]["tpl"] == "work", f"#3116 state: the folder's limit {L[FP]['notif_cap']}")
DEF = eq.get("tpl", {}).get(str(OWN))  # the instance default (read unless KALMIDO_NOTIF_TEMPLATE says otherwise)
check((L[OWN]["notif_cap"] or {"tpl": "all"})["tpl"] == DEF, f"#3116 state: the default limit {L[OWN]['notif_cap']} / {DEF}")
check([(x["group_id"], x["name"], x["role"], x["via"]) for x in L[GRP]["groups"]] == [(GID, "Editors", "view", "list")],
      f"#3116 state: the group share with its name {L[GRP]['groups']}")
check(all(L[x]["groups"] == [] for x in (OWN, PLAIN)), "#3116 state: lists without group share: none")
inbox = next(x for x in L.values() if x["is_inbox"])
check(inbox["notif_cap"] is None and inbox["repos"] == [], "#3116 state: vera's own inbox: not limited, no repository")
_, LC = state_lists(Ca)
check(LC[OL]["role"] == "view", f"#3116 state: an organisation list for a read-only member: view {LC[OL]['role']}")
_, LF = state_lists(Fr)
check([x["full_name"] for x in LF[FL]["repos"]] == ["acme/frida"] and LF[FL]["notif_cap"] is None and LF[FL]["role"] == "owner",
      f"#3116 without an organisation: her own list with its repository, not limited (freelancer-matrix: lists) {LF[FL]['repos']}")
eqf = compare("frida", sorted(LF))
if eqf:
    check(eqf["git_new"] == eqf["git_old"] == {str(FL): [C_FR]} and eqf["tpl_same"] and eqf["roles_same"],
          f"#3116 without an organisation: bulk helpers = per list {eqf.get('git_new')}")
_, LB = state_lists(Bo)
check(LB[PLAIN]["notif_cap"] is None and LB[OWN]["role"] == "owner", "#3116 state: the owner is never limited")

# ================================================================ time report: same sums, names
dbx("UPDATE lists SET time_tracking=1 WHERE id IN (?, ?, ?, ?)", (OWN, PLAIN, inbox["id"], FL), write=True)  # the list setting
for lid, minutes in ((OWN, 30), (PLAIN, 45), (inbox["id"], 15)):
    r = Ve.post(B + "/api/time/entries", json={"list_id": lid, "start": DAY + "T09:00", "minutes": minutes, "note": "invented"})
    check(r.ok, f"setup: vera's time in {lid} " + r.text[:120])
_, rep = report(Ve)
got = {x["id"]: (x["name"], x["seconds"]) for x in rep["lists"]}
check(got == {OWN: ("Own repo", 1800), PLAIN: ("Plain", 2700), inbox["id"]: (inbox["name"], 900)} and rep["total"]["seconds"] == 5400,
      f"#3116 time report: the same sums per list with their names {got} {rep['total']}")
check(next(x for x in rep["lists"] if x["id"] == inbox["id"])["is_inbox"] is True, "#3116 time report: the inbox is marked")
check(Fr.post(B + "/api/time/entries", json={"list_id": FL, "start": DAY + "T10:00", "minutes": 20}).ok, "setup: frida's time")
_, repf = report(Fr)
check([(x["id"], x["name"], x["seconds"]) for x in repf["lists"]] == [(FL, "Frida's project", 1200)],
      f"#3116 without an organisation: the own time report (freelancer-matrix: time) {repf['lists']}")

# ================================================================ statements: 2 vs 30 foreign lists (no repository)
# /api/state as a whole still grows per list through the team chat rooms (2.281 #3110); the statements of the helpers of this
# part are counted in the app (git_conns / git_folders / list_notif / folder_notif / group_shares / groups / org_members).
PROBE = """
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
cl.post('/api/auth/login', json={'username': 'vera', 'password': 'password123'}, headers=hh)
cl.get('/api/state', headers=hh)
seen.clear()
r = cl.get('/api/state', headers=hh)
pat = re.compile(r'\\b(git_conns|git_folders|list_notif|folder_notif)\\b|FROM group_shares WHERE|FROM groups WHERE|FROM org_members WHERE user_id')
print(json.dumps({'status': r.status_code, 'all': len(seen), 'helpers': sum(1 for x in seen if pat.search(x))}))
"""


def probe():
    out = in_app(PROBE)
    try:
        return json.loads(out)
    except ValueError:
        check(False, f"statement probe ran: {out[:600]}")
        return {"all": -1, "helpers": -1}


SV = login(B, "vera")  # a fresh session (nothing cached in the client)
state_lists(SV)
ns_a = nstmt(state_lists(SV)[0])
nr_a = nstmt(report(SV)[0])
pa = probe()
for i in range(28):
    lid = mklist(Bo, f"Shot {i}", kind="project" if i % 2 else "")
    share(lid, "vera")
    if i % 3 == 0:
        check(Bo.patch(B + f"/api/lists/{lid}", json={"folder": "Studio/Day %d" % (i % 4)}).ok, f"setup: list {lid} in a folder")
r, L30 = state_lists(SV)
r, L30 = state_lists(SV)
ns_b = nstmt(r)
r, rep30 = report(SV)
nr_b = nstmt(r)
pb = probe()
check(rep30["total"]["seconds"] == 5400, "#3116 time report with 30 more lists: the same sum")
check(sum(1 for x in L30.values() if x["notif_cap"] and x["notif_cap"]["tpl"] == "work") >= 10,
      "#3116 state: the folder limit reaches the lists in its subfolders")

print(f"PERF #3116 /api/state: {len(L)} lists {ns_a} statements, {len(L30)} lists {ns_b} statements", flush=True)
print(f"PERF #3116 /api/time/report: {len(L)} lists {nr_a} statements, {len(L30)} lists {nr_b} statements", flush=True)
check(0 < nr_b <= nr_a + 3, f"#3116 time report: statements do not grow per visible list ({nr_a} -> {nr_b})")
print(f"PERF #3116 /api/state helpers (repositories, limits, groups, memberships): {pa['helpers']} -> {pb['helpers']} statements", flush=True)
check(0 < pb["helpers"] <= pa["helpers"] + 1, f"#3116 state: the helpers' statements do not grow per foreign list ({pa} -> {pb}; before: 4-6 each)")

print(f"\np2280_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
