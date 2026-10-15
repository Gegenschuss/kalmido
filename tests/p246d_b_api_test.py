#!/usr/bin/env python3
"""2.46.4 part B API tests (#1751), own container (start.sh): the list switch "Tap does not open details" (lists.tap_done).
- new shopping and packing lists start with it on, a meal plan and a plain list with it off; a packing list from a template too
- PATCH tap_done: owner and list admins (0 / 1 / true / false), a member with edit rights gets 403, wrong values 400
- once on for the shopping / packing lists that exist when the column is created (the column dropped by hand, a restart);
  switched off afterwards it stays off over the next restart
usage: p246d_b_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def lists(s):
    return {x["id"]: x for x in s.get(B + "/api/state").json()["lists"]}


def start(keep=False):
    env = dict(os.environ, **({"KEEP": "1"} if keep else {}))
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)


# ---------------------------------------------------------------- setup
start()
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "comments,collab,family"})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
check(r.ok, "bob created " + r.text[:160])
BOB = r.json().get("id")

# ---------------------------------------------------------------- defaults
ids = {}
for fam in ("shopping", "packing", "meals", ""):
    r = A.post(B + "/api/lists", json={"name": "L-" + (fam or "plain"), **({"family": fam} if fam else {})})
    check(r.ok, f"list {fam or 'plain'} created " + r.text[:160])
    ids[fam or "plain"] = r.json()["id"]
    check(r.json().get("tap_done") == (1 if fam in ("shopping", "packing") else 0), f"#1751: tap_done of a new {fam or 'plain'} list: {r.json().get('tap_done')}")
st = lists(A)
check(st[ids["shopping"]].get("tap_done") == 1 and st[ids["plain"]].get("tap_done") == 0, "#1751: the state carries tap_done")
r = A.post(B + "/api/family/packing", json={"template": "pool"})
check(r.ok and lists(A)[r.json().get("list_id")].get("tap_done") == 1, "#1751: a packing list from a template has it on " + r.text[:120])

# ---------------------------------------------------------------- PATCH
P = ids["plain"]
for v, want in ((1, 1), (False, 0), (True, 1), ("0", 0), ("1", 1)):
    r = A.patch(B + f"/api/lists/{P}", json={"tap_done": v})
    check(r.ok and lists(A)[P].get("tap_done") == want, f"#1751: PATCH tap_done={v!r} -> {want}: {r.status_code} {r.text[:120]}")
for v in (2, "x", 1.0, None, [1]):
    r = A.patch(B + f"/api/lists/{P}", json={"tap_done": v})
    check(r.status_code == 400, f"#1751: PATCH tap_done={v!r} refused: {r.status_code}")
check(lists(A)[P].get("tap_done") == 1, "#1751: a refused value changes nothing")
if BOB:
    A.put(B + f"/api/lists/{P}/members", json={"user_id": BOB, "role": "edit"})
    Bo = sess("bob")
    r = Bo.patch(B + f"/api/lists/{P}", json={"tap_done": 0})
    check(r.status_code == 403 and lists(A)[P].get("tap_done") == 1, f"#1751: a member with edit rights may not change it: {r.status_code}")
    check(lists(Bo)[P].get("tap_done") == 1, "#1751: the member sees the switch of the list")
    A.put(B + f"/api/lists/{P}/members", json={"user_id": BOB, "role": "admin"})
    r = Bo.patch(B + f"/api/lists/{P}", json={"tap_done": 0})
    check(r.ok and lists(A)[P].get("tap_done") == 0, f"#1751: a list admin may: {r.status_code} {r.text[:120]}")
r = A.patch(B + f"/api/lists/{ids['meals']}", json={"tap_done": 1, "name": "Meals"})
check(r.ok and lists(A)[ids["meals"]].get("tap_done") == 1 and lists(A)[ids["meals"]]["name"] == "Meals", "#1751: together with other fields")

# ---------------------------------------------------------------- once on for existing shopping / packing lists
try:  # start.sh names "<db container> <database>" in <datadir>/.kalmido-db
    DBC, DBN = open(os.path.join(DATA, ".kalmido-db")).read().split()[:2]
except (OSError, ValueError):
    DBC, DBN = "", ""


def sql(q):
    if not DBC:
        return None
    r = subprocess.run(["docker", "exec", DBC, "psql", "-U", "kalmido", "-d", DBN, "-Atc", q], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


OLD = A.post(B + "/api/lists", json={"name": "Old groceries"}).json()["id"]
if sql(f"ALTER TABLE lists DROP COLUMN tap_done; UPDATE lists SET family='shopping' WHERE id={OLD}") is not None:
    start(keep=True)
    A = sess("alice")
    st = lists(A)
    check(st[OLD].get("tap_done") == 1 and st[ids["shopping"]].get("tap_done") == 1 and st[ids["packing"]].get("tap_done") == 1,
          "#1751: the column's creation switches it on for the shopping and packing lists that exist")
    check(st[ids["plain"]].get("tap_done") == 0 and st[ids["meals"]].get("tap_done") == 0, "#1751: other lists stay off")
    check(A.patch(B + f"/api/lists/{OLD}", json={"tap_done": 0}).ok, "#1751: switched off")
    start(keep=True)
    A = sess("alice")
    check(lists(A)[OLD].get("tap_done") == 0, "#1751: switched off stays off over a restart (the migration runs once)")
else:  # no access to the database container here: the migration is checked in the schema text
    src = open(os.path.join(N, "..", "kalmido", "core", "schema.py"), encoding="utf-8").read()
    check("UPDATE lists SET tap_done=1 WHERE family IN ('shopping', 'packing')" in src, "#1751: the once-migration in the schema")

print(f"p246d_b_api_test: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
