#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.924.0 part A (#5069, stage 7a of the shared core): the team chat's old member table tchat_members is retired, the core
alone decides (rebuilt on main after package 2.661 did not reach the train). Own container (mode workspaces). Invented names only.
tenant-matrix: team
freelancer-matrix: team
 - the start check: a database that still has tchat_members with a row whose person has no share on the room's node (the
   forward copy already ran) keeps the table, the log names the number, the row opens nothing (no fallback reader)
 - the forward copy (once) at the next start: a row without a share gets one, a room without a node gets one (owner: its
   maker), also a private channel of a person without an organisation; then the table is dropped (log line), every later
   start is a no-op
 - the import of an organisation archive: an older archive's chat/members.json becomes shares of the room's node (made at
   once with the importing person's share); a newer archive's node of the channel (store) points at the new room at once and
   keeps its shares -- one node per room
 - the organisation export: a closed channel the exporting admin is in only through a group comes along (ox_csq reads the core)
 - #5053 on the core alone: a token of bob limited to lists finds no message of a channel he is in through the forward copy;
   his token without a limit and the app find it
usage: p2924_a_kern_teamchat_test.py <datadir>"""
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
import kt  # noqa: E402
import requests  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, DATA, FAILS, OKS, check, sess, until  # noqa: E402,F401

FEAT = "cal,comments,collab,files"
V = B + "/api/v1"
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
OLD_DDL = ("CREATE TABLE IF NOT EXISTS tchat_members (room_id BIGINT NOT NULL REFERENCES tchat_rooms(id) ON DELETE CASCADE, "
           "user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, added_by BIGINT, created_at TEXT NOT NULL, "
           "PRIMARY KEY (room_id, user_id))")  # the table as 2.113 - 2.923 made it

kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2924A")


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


def no(r, what):
    check(r.status_code in (403, 404), f"{what}: refused ({r.status_code} {r.text[:120]})")


def share(rid, who, key="user_id"):
    x = sql(f"SELECT s.role FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind='tchat_room' "
            f"AND n.ref_id=? AND s.{key}=?", (rid, who))
    return x[0][0] if x else None


def nodes(rid):
    return sql("SELECT id, owner_id, org_id FROM fs_nodes WHERE kind='ref' AND ref_kind='tchat_room' AND ref_id=?", (rid,))


def old_table():
    return sql("SELECT to_regclass('tchat_members')")[0][0] is not None


def reads(s, rid):
    return s.get(B + f"/api/team/rooms/{rid}/messages").ok


def channel(s, name, oid, members=(), open_=False):
    r = s.post(B + "/api/team/channels", json={"name": name, "org_id": oid, "members": list(members), **({"open": True} if open_ else {})})
    check(r.status_code in (200, 201), f"setup: channel {name} {r.text[:160]}")
    return r.json().get("id")


def logs():
    r = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
    return r.stdout + r.stderr


def restart():
    """The next start of the server (core/db.py init_db runs collab/tcxcore.py tcx_core_copy once, then tcx_core_retire)."""
    subprocess.run(["docker", "restart", CT], capture_output=True)
    check(until(lambda: _health(), timeout=90), "the server is up again after the restart")


def _health():
    try:
        return requests.get(B + "/api/health", timeout=3).ok
    except requests.RequestException:
        return False


def in_app(code, *args):
    """Python inside the test container (the app's modules, its database) -> the JSON of its last output line."""
    r = subprocess.run(["docker", "exec", "-i", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", code, *map(str, args)],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (r.stdout + r.stderr)[-600:]}


A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ALICE = A.get(B + "/api/me").json()["id"]
uid, S = {}, {}
for u in ("bob", "mia"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
    S[u] = sess(u)
    S[u].patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
Bo, Mi = S["bob"], S["mia"]
BOB, MIA = uid["bob"], uid["mia"]
r = A.post(B + "/api/admin/orgs", json={"name": "Kappa"})
assert r.status_code in (200, 201), r.text
K = r.json()["id"]
sql("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT (org_id,user_id) DO UPDATE SET role='admin'", (K, ALICE), write=True)
for who in (BOB, MIA):
    mail = sql("SELECT email FROM users WHERE id=?", (who,))[0][0]
    check(A.put(B + f"/api/orgs/{K}/members", json={"email": mail, "role": "member"}).ok, f"setup: {who} is a member of Kappa")
A.patch(B + "/api/settings", json={"workspace": f"org:{K}"})
FE, Fe = freelancer(B, A, "fred", features=FEAT)

# ================================================================== the start check
check(not old_table(), "a new database has no tchat_members")
C = channel(A, "Closed", K)
check(share(C, BOB) is None and not reads(Bo, C), "setup: bob is not in the closed channel")
sql(OLD_DDL, write=True)
sql("INSERT INTO tchat_members(room_id,user_id,added_by,created_at) VALUES(?,?,?,'2026-11-01T10:00:00Z')", (C, BOB, ALICE), write=True)
sql("INSERT INTO settings(key,value) VALUES('migr_tcx5069','1') ON CONFLICT(key) DO UPDATE SET value='1'", write=True)  # the copy ran
restart()
Bo, A = sess("bob"), sess("alice")
check(old_table(), "start check: an old row without a share -> the table stays (nothing dropped)")
check("team chat, stage 7a (#5069): 1 old row(s) of tchat_members have no share in the shared core" in logs(),
      "start check: the log names the row left")
check(share(C, BOB) is None, "start check: nothing copied after the copy ran")
no(Bo.get(B + f"/api/team/rooms/{C}/messages"), "start check: the old row opens nothing (the core alone decides)")
check(C not in {x.get("id") for x in Bo.get(B + "/api/team/channels").json().get("channels") or []}, "start check: bob does not list it")

# ================================================================== the forward copy, then the drop
# a channel of the organisation and a private channel of a person without one that have no node (an old database)
sql("INSERT INTO tchat_rooms(kind,name,org_id,is_open,created_by,created_at) VALUES('channel','Raw',?,false,?,'2026-11-01T09:00:00Z')",
    (K, ALICE), write=True)
R2 = sql("SELECT id FROM tchat_rooms WHERE name='Raw' AND org_id=?", (K,))[0][0]
R3 = channel(Fe, "Fred alone", None)
sql("DELETE FROM fs_nodes WHERE kind='ref' AND ref_kind='tchat_room' AND ref_id=?", (R3,), write=True)
check(not nodes(R2) and not nodes(R3), "setup: two rooms without a node")
for rid, who in ((R2, ALICE), (R2, BOB), (R3, FE)):
    sql("INSERT INTO tchat_members(room_id,user_id,added_by,created_at) VALUES(?,?,?,'2026-11-01T10:00:00Z')", (rid, who, ALICE), write=True)
sql("DELETE FROM settings WHERE key='migr_tcx5069'", write=True)
restart()
Bo, A, Fe = sess("bob"), sess("alice"), sess("fred")
check(not old_table(), "copy: every row has its share -> tchat_members is dropped")
check("team chat, stage 7a (#5069): every old row has its share in the shared core -- tchat_members dropped" in logs(), "copy: the log says so")
check(sql("SELECT value FROM settings WHERE key='migr_tcx5069'") == [("1",)], "copy: ran once (flag)")
# 2.924.0 (#5069, Fable review F1): the DROP raises the database's back limit to this image's minor - an older image refuses
# to start (core/db.py appver_check "format") instead of creating tchat_members empty again and taking every member's share
fl = dict(sql("SELECT key, value FROM kalmido_meta WHERE key IN ('back_floor','back_floor_how')"))
mine = in_app("import json; from kalmido.core.config import APP_VERSION; print(json.dumps(APP_VERSION))")
check(isinstance(mine, str) and fl.get("back_floor") == ".".join(mine.split(".")[:2] + ["0"]) and "#5069" in (fl.get("back_floor_how") or ""),
      f"drop: back_floor is the minor of this image {fl} {mine}")
v = in_app("import json, sys; from kalmido.core.db import appver_check; from kalmido.core.config import APP_VERSION as m; "
           "x = m.split('.'); prev = f'{x[0]}.{int(x[1]) - 1}.0'; "
           "print(json.dumps(appver_check(m, prev, mine=prev, floor=sys.argv[1])))", fl.get("back_floor"))
check(v == "format", f"drop: the previous minor (the one step back) now refuses to start on this database: {v}")
check(share(C, BOB) == "edit" and reads(Bo, C), "copy: bob's old row of the closed channel became his share, he reads it")
n2 = nodes(R2)
check(len(n2) == 1 and n2[0][1] == ALICE and n2[0][2] == K, f"copy: the room without a node got one (owner its maker, the organisation) {n2}")
check(share(R2, ALICE) == "edit" and share(R2, BOB) == "edit" and reads(Bo, R2), "copy: both rows of it are shares, bob reads it")
check(share(R2, MIA) is None and not reads(Mi, R2), "copy: nobody else (a closed channel)")
n3 = nodes(R3)
check(len(n3) == 1 and n3[0][1] == FE and n3[0][2] is None and share(R3, FE) == "edit" and reads(Fe, R3),
      f"freelancer: the private channel got its node in his own space and his share {n3}")
restart()
check(not old_table() and len(nodes(R2)) == 1, "a later start: nothing to do (no table, no second node)")

# ================================================================== the import of an organisation archive
IMP = r"""
import json, sys
from kalmido.core.config import app
from kalmido.core import pg as _pg
from kalmido.core.config import DATABASE_URL
from kalmido.admin import oi_team
org, alice, bob = map(int, sys.argv[1:4])

class Run:
    def __init__(self):
        self.map, self.created, self.stats, self.oi_store = {}, {"oi": []}, {}, {"docs": [], "pages": [], "names": None, "refs": []}
    def m(self, kind, v):
        return self.map.get((kind, str(v)))
    def put(self, kind, v, new):
        self.map[(kind, str(v))] = new
    def count(self, k, n=1):
        self.stats[k] = self.stats.get(k, 0) + n

class Ctx:
    uid = alice

out = {}
with app.app_context():
    c = _pg.connect_direct(DATABASE_URL)
    with _pg.system_ctx(c):
        def room(name):
            return c.execute("INSERT INTO tchat_rooms(kind,name,org_id,is_open,created_by,created_at) VALUES('channel',?,?,false,?,'2026-11-08T09:00:00Z') "
                             "RETURNING id", (name, org, alice)).fetchone()[0]
        # an archive before 2.924: chat/channels.json + chat/members.json, no node of the channel in the store
        run = Run()
        old = room("Imported old")
        run.put("tchat_rooms", 901, old)
        oi_team._room_after(c, run, {"kind": "channel", "id": 901}, old, Ctx())
        d = oi_team._room_member(c, run, {"room_id": 901, "user_id": 77}, {"user_id": bob, "node_id": 0}, Ctx())
        out["old"] = {"room": old, "ret": d, "created": run.created["oi"]}
        # an archive of 2.924: the channel's node came with the store (ref_id NULL, waiting in _CORE_LATE) with bob's share
        run = Run()
        n = c.execute("INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,ref_kind,ref_id,created_by,created_at,updated_at) "
                      "VALUES(NULL,'ref','Imported new',?,?,'tchat_room',NULL,?,'2026-11-08T09:00:00Z','2026-11-08T09:00:00Z') RETURNING id",
                      (alice, org, alice)).fetchone()[0]
        c.execute("INSERT INTO fs_shares(node_id,user_id,role,created_by,created_at) VALUES(?,?,'edit',?,'2026-11-08T09:00:00Z')", (n, bob, alice))
        run.put("fs_nodes", 501, n)
        run.oi_store["refs"].append((501, "tchat_room", 902))
        new = room("Imported new")
        run.put("tchat_rooms", 902, new)
        oi_team._room_after(c, run, {"kind": "channel", "id": 902}, new, Ctx())
        out["new"] = {"room": new, "node": n, "created": run.created["oi"]}
    c.commit()
print(json.dumps(out))
"""
res = in_app(IMP, K, ALICE, BOB)
check("old" in res and "new" in res, f"import: the importer's steps ran {res}")
OLD, NEW = (res.get("old") or {}).get("room"), (res.get("new") or {}).get("room")
on = nodes(OLD) if OLD else []
check(len(on) == 1 and share(OLD, ALICE) == "edit", f"import (old archive): the room's node is made at once with the importer's share {on}")
check(share(OLD, BOB) == "edit" and reads(Bo, OLD), "import (old archive): the member of chat/members.json is a share of the node, bob reads it")
check(res.get("old", {}).get("ret") is False and on and ["fs_nodes", on[0][0], K] in res["old"]["created"],
      "import (old archive): no row of the old table, the node made is recorded for the undo")
nn = nodes(NEW) if NEW else []
check(len(nn) == 1 and nn[0][0] == res["new"]["node"], f"import (new archive): the store's node points at the new room at once, one node {nn}")
check(share(NEW, BOB) == "edit" and share(NEW, ALICE) == "edit" and reads(Bo, NEW), "import (new archive): its shares count, the importer joins")
check(res["new"]["created"] == [], "import (new archive): the archive's node is recorded by the store already (nothing twice)")

# ================================================================== the organisation export: a channel through a group
r = A.post(B + "/api/admin/groups", json={"name": "Leads", "members": [ALICE]})
check(r.ok, "export: a group with alice " + r.text[:160])
G = r.json().get("id")
GC = channel(Bo, "Bob closed", K)
check(share(GC, ALICE) is None, "export: bob's closed channel, alice has no personal share")
# bob may not share with a group he is not in (F1 of #4719): the group's share as the core holds it
sql("INSERT INTO fs_shares(node_id,group_id,role,created_by,created_at) SELECT id, ?, 'edit', ?, '2026-11-08T09:00:00Z' FROM fs_nodes "
    "WHERE kind='ref' AND ref_kind='tchat_room' AND ref_id=?", (G, BOB, GC), write=True)
check(share(GC, G, "group_id") == "edit" and reads(A, GC), "export: alice reads the channel through the group")
CSQ = r"""
import json, sys
from kalmido.core.config import app
from kalmido.core import pg as _pg
from kalmido.core.config import DATABASE_URL
from kalmido.admin.orgexport import ox_csq
org, alice, bob = map(int, sys.argv[1:4])
with app.app_context():
    c = _pg.connect_direct(DATABASE_URL)
    with _pg.system_ctx(c):
        out = {"alice": [r[0] for r in c.execute(ox_csq(alice), (org,))], "none": [r[0] for r in c.execute(ox_csq(None), (org,))]}
print(json.dumps(out))
"""
res = in_app(CSQ, K, ALICE, BOB)
check(GC in (res.get("alice") or []), f"export: the closed channel the admin reads through a group comes along {res}")
check("none" in res and GC not in res["none"], "export: (control) without the admin's membership it stays out")

# ================================================================== #5053 on the core alone: the list limit of a token
LW = A.post(B + "/api/lists", json={"name": "Work", "org_id": K}).json()["id"]
r = A.post(B + f"/api/team/rooms/{R2}/messages", json={"body": "kolibri in the copied channel"})
check(r.status_code in (200, 201), f"token: a message in the channel bob reaches through the forward copy {r.text[:160]}")
M = (r.json() or {}).get("id") if r.ok else None


def tok(lists=None):
    j = {"name": f"t{lists}", "scopes": ["read", "comments"], "expires_days": None, **({"list_ids": lists} if lists is not None else {})}
    x = Bo.post(B + "/api/me/tokens", json=j)
    check(x.ok and x.json().get("token"), f"setup: bob's token {x.text[:160]}")
    return {"Authorization": "Bearer " + ((x.json().get("token") if x.ok else None) or "x")}


def vfind(h):
    x = requests.get(V + "/search", headers=h, params={"scope": "messages", "q": "kolibri"})
    return [x2.get("id") for x2 in x.json().get("data") or []] if x.ok else x.status_code


check(A.put(B + f"/api/lists/{LW}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: bob in the list Work")
got = Bo.get(B + "/api/search?kind=messages", params={"q": "kolibri"})
check(got.ok and M in [x.get("id") for x in got.json().get("hits") or []], "token: the app finds the channel's message")
got = vfind(tok())
check(isinstance(got, list) and M in got, f"token: bob's token without a limit finds it {got}")
got = vfind(tok([LW]))
check(isinstance(got, list) and M not in got, f"token: bob's token limited to lists finds no message of the channel {got}")

sys.exit(kt.done("p2924_a_kern_teamchat"))
