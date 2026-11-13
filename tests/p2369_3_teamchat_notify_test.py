#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.369.3 API tests (#3199): the team chat pushes read what they need of every person of a room in a fixed number of
statements, and an open channel's check reads a person's organisations once. Own container (start.sh). Invented people only.
freelancer-matrix: team
 - #3199 tchat_notify decides the same as before: bell "all" = push, default bell = none, an @mention = push (also when muted),
   muted = none, a disabled account / module "collab" off / no device or topic / a leftover member row outside the
   organisation = none (each case in one transaction that is rolled back, the pushes read from g.pushes)
 - #3199 statements of tchat_notify: 8 people in the room cost what 2 cost (default bell, no mention; before: five to eight
   statements per person)
 - #3199 tcx_room_ok over 1 vs. 11 open channels of the person's organisation (not joined): the same statements with the
   shared per-person dict (before: the organisations and the person check again per channel); /api/team/channels lists them
 - a person without an organisation: the channel of the own list shared with another freelancer pushes with the bell "all"
usage: p2369_3_teamchat_notify_test.py <datadir>   (KMT_NOSTART=1: the container runs already)"""
import json
import os
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
FEATURES = "cal,collab,comments"
NOSTART = os.environ.get("P23693_NOSTART") or os.environ.get("KMT_NOSTART")


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    return out[-1] if out else "ERR " + r.stderr[-800:]


def in_app_json(code, what):
    res = in_app(code)
    try:
        return json.loads(res)
    except ValueError:
        check(False, f"{what}: the script ran inside the app: {res[:600]}")
        return None


if not NOSTART:
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A = login(B, "alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta"})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES})


def person(name, org, role="member"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": org, "role": role}], "username": name, "display_name": name.title(),
                                       "password": "password123", "email": f"{name}@example.com"})
    assert r.ok, r.text
    uid[name] = r.json()["id"]
    s = login(B, name)
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok
    return s


PPL = ("bob", "gina", "rita", "dave", "erik", "fred", "hans")
S = {n: person(n, ORG) for n in PPL}
person("carl", BETA)


def team(s):
    r = s.get(B + "/api/team")
    assert r.ok, r.text
    return {x["id"]: x for x in r.json()["rooms"]}


def room_of_list(s, lid):
    return next((x for x in team(s).values() if x.get("list_id") == lid), None)


def post(s, rid, text):
    r = s.post(B + f"/api/team/rooms/{rid}/messages", json={"body": text})
    return r.json().get("id") if r.status_code == 201 else None


LA = A.post(B + "/api/lists", json={"name": "Shoot plan", "org_id": ORG}).json()["id"]
for n in PPL:
    check(A.put(B + f"/api/lists/{LA}/members", json={"user_id": uid[n], "role": "edit"}).ok, f"setup: {n} in the list")
dbx("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,?,?)", (LA, uid["carl"], "edit", "2026-11-02T08:00:00"))
RA = (room_of_list(A, LA) or {}).get("id")
check(bool(RA), "setup: the channel of the shared list")
LB = A.post(B + "/api/lists", json={"name": "Edit plan", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{LB}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob in the small list")
RB = (room_of_list(A, LB) or {}).get("id")
MA = post(A, RA, "Call sheet is up")
MB = post(A, RB, "Cut is up")
check(bool(MA and MB), "setup: alice writes in both channels")

# one transaction per case (rolled back): the settings of the case, then tchat_notify; the pushes come from g.pushes
HEAD = r"""
from kalmido.core.config import app as fa
from kalmido.core.db import connect
from flask import g
from kalmido.collab import teamchat as T
class W:
    def __init__(s, c): s.c, s.n = c, 0
    def execute(s, *a, **k):
        s.n += 1
        return s.c.execute(*a, **k)
    def __getattr__(s, k): return getattr(s.c, k)
U = %(uid)s
SENDER = %(sender)d
def case(rid, mid, setup, mentions=()):
    c = connect()
    try:
        for sql, args in setup:
            c.execute(sql, args)
        with fa.test_request_context('/api/x'):
            g.user, g.pushes = c.execute("SELECT * FROM users WHERE id=?", (SENDER,)).fetchone(), []
            r = c.execute("SELECT * FROM tchat_rooms WHERE id=?", (rid,)).fetchone()
            m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
            w = W(c)
            T.tchat_notify(w, r, m, [U[x] for x in mentions])
            return sorted(p[0] for p in g.pushes), w.n
    finally:
        c.rollback()
        c.close()
topic = lambda n: ("INSERT INTO user_settings(user_id,key,value) VALUES(?,'ntfy_topic',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value", (U[n], "t-" + n))
# 2.981.0 (#5287): the project bell is a row of the core's obj_follow (kind list, the project's workspace)
bell = lambda n, lid, mode="all": ("INSERT INTO obj_follow(user_id,kind,ref_id,org_id,mode,custom) VALUES(?,'list',?,(SELECT org_id FROM lists WHERE id=?),?,'{}') "
                                   "ON CONFLICT (user_id,kind,ref_id) WHERE mode <> 'watch' DO UPDATE SET mode=excluded.mode", (U[n], lid, lid, mode))
# 2.981.0 (#5286): muting a room is a row of the core's obj_follow (kind tchat, mode mute; tchat_reads is gone)
mute = lambda n, rid: ("INSERT INTO obj_follow(user_id,kind,ref_id,mode) VALUES(?,'tchat',?,'mute') ON CONFLICT DO NOTHING", (U[n], rid))
"""
NOTIFY = r"""
RA, RB, LA, LB, MA, MB = %(ids)s
nott = lambda n: ("DELETE FROM user_settings WHERE user_id=? AND key='ntfy_topic'", (U[n],))
base = [topic(n) for n in ("bob", "gina", "rita", "dave", "erik", "fred", "carl")] + [nott("hans")]  # hans: no topic, no device
base += [bell(n, LA) for n in ("bob", "dave", "erik", "fred", "hans", "carl")]  # gina, rita: the default bell
base += [mute("dave", RA), ("UPDATE users SET disabled=true WHERE id=?", (U["erik"],)),
         ("INSERT INTO user_settings(user_id,key,value) VALUES(?,'features','cal,comments') ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value", (U["fred"],))]
out = {}
out["all"] = case(RA, MA, base)[0]
out["mention"] = case(RA, MA, base, ("rita", "dave", "erik", "hans"))[0]
# statements: default bell, no mention, everyone reachable -- 8 people (+ carl's leftover row) vs. 2
quiet = [topic(n) for n in ("bob", "gina", "rita", "dave", "erik", "fred", "hans")]
out["n8"] = case(RA, MA, quiet)[1]
out["n2"] = case(RB, MB, quiet)[1]
out["n8_all"] = case(RA, MA, quiet + [bell(n, LA) for n in ("bob", "gina", "rita", "dave", "erik", "fred", "hans")])
print(json.dumps(out))
""" % {"ids": json.dumps([RA, RB, LA, LB, MA, MB])}


def head(sender):
    return HEAD % {"uid": json.dumps(uid), "sender": sender}


res = in_app_json(head(uid["alice"]) + NOTIFY, "#3199 tchat_notify")
if res:
    check(res["all"] == [uid["bob"]],
          f"#3199 bell 'all': only bob gets a push (gina/rita default bell, dave muted, erik disabled, fred without the module, "
          f"hans without a device, carl outside the organisation) {res['all']}")
    check(res["mention"] == sorted([uid["bob"], uid["rita"], uid["dave"]]),
          f"#3199 @mentions: rita (default bell) and dave (muted) get it, erik (disabled) and hans (no device) not; bob by the bell "
          f"{res['mention']}")
    check(0 < res["n8"] <= res["n2"] + 2, f"#3199 tchat_notify: 8 people cost what 2 cost ({res['n2']} -> {res['n8']} statements)")
    check(res["n8_all"][0] == sorted(uid[n] for n in ("bob", "gina", "rita", "dave", "erik", "fred", "hans")),
          f"#3199 everyone with the bell 'all' and a topic gets the push {res['n8_all'][0]}")
    print(f"PERF #3199 tchat_notify statements: 2 people {res['n2']}, 8 people {res['n8']}, 8 people all pushed {res['n8_all'][1]}",
          flush=True)

# ================================================================ #3199: tcx_room_ok reads a person's organisations once
CH = []
for i in range(11):
    r = A.post(B + "/api/team/channels", json={"name": f"Open {i}", "org_id": ORG, "members": [uid["gina"]], "open": True})
    check(r.status_code in (200, 201), f"setup: open channel {i} {r.text[:200]}")
    CH.append(r.json().get("id"))
ROOMOK = r"""
from kalmido.core.db import connect
from kalmido.collab.teamchan import tcx_room_ok
class W:
    def __init__(s, c): s.c, s.n = c, 0
    def execute(s, *a, **k):
        s.n += 1
        return s.c.execute(*a, **k)
    def __getattr__(s, k): return getattr(s.c, k)
c = connect()
rows = c.execute("SELECT * FROM tchat_rooms WHERE id = ANY(%%s) ORDER BY id" %% "CAST(? AS BIGINT[])", (%(ch)s,)).fetchall()
out = {}
for k, rr in (("n1", rows[:1]), ("n11", rows)):
    w, who = W(c), {}
    ok = [tcx_room_ok(w, x, %(bob)d, set(), who) for x in rr]
    out[k], out[k + "_ok"] = w.n, all(ok)
w, who = W(c), {}
out["agent_ok"] = any(tcx_room_ok(w, x, %(carl)d, set(), who) for x in rows)
c.rollback()
c.close()
print(json.dumps(out))
""" % {"ch": json.dumps(CH), "bob": uid["bob"], "carl": uid["carl"]}
res = in_app_json(ROOMOK, "#3199 tcx_room_ok")
if res:
    check(res["n1_ok"] and res["n11_ok"], f"#3199 bob may read every open channel of his organisation {res}")
    check(not res["agent_ok"], f"#3199 carl (other organisation) may read none of them {res}")
    check(0 < res["n11"] <= res["n1"], f"#3199 tcx_room_ok: 11 open channels cost what one costs ({res['n1']} -> {res['n11']})")
    print(f"PERF #3199 tcx_room_ok statements: 1 channel {res['n1']}, 11 channels {res['n11']}", flush=True)
r = S["bob"].get(B + "/api/team/channels")
got = {x["id"] for x in r.json().get("channels", [])} if r.ok else set()
check(set(CH) <= got, f"#3199 /api/team/channels: bob sees the 11 open channels (not joined) {len(got)}")

# ================================================================ a person without an organisation (freelancer-matrix: team)
FID, Fr = freelancer(B, A)
FIO, Fi = freelancer(B, A, "fiona")
for s in (Fr, Fi):
    s.patch(B + "/api/settings", json={"features": FEATURES})
dbx("INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES(?,?,?,?)", ("Freelance pool", "", "2026-11-02T08:00:00", uid["alice"]))
GID = dbx("SELECT id FROM groups WHERE name=?", ("Freelance pool",))[0][0]
for x in (FID, FIO):
    dbx("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (GID, x, "2026-11-02T08:00:00"))
FL = Fr.post(B + "/api/lists", json={"name": "Own studio"}).json()["id"]
check(Fr.put(B + f"/api/lists/{FL}/members", json={"user_id": FIO, "role": "edit"}).ok, "freelancer: the own list shared")
fx = room_of_list(Fr, FL)
check(fx is not None, "freelancer: the channel of the own list")
if fx:
    fm = post(Fr, fx["id"], "Draft is ready")
    uid["fiona"], uid["frida"] = FIO, FID
    got = in_app_json(head(FID) + "print(json.dumps(case(%d, %d, [topic('fiona'), bell('fiona', %d)])[0]))" % (fx["id"], fm, FL),
                      "freelancer: tchat_notify")
    check(got == [FIO], f"freelancer: fiona (bell 'all', a topic) gets the push of frida's message {got}")

print(f"\np2369_3_teamchat_notify: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
