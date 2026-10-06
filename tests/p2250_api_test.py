#!/usr/bin/env python3
"""2.25.0 API tests.
 - #931 a list created inside a folder that is shared with people is shared with them on EVERY path: the list dialog,
   a project of a built-in type, a family list, an import (Trello, lists mode: the board is the folder); the one-time
   repair at start (migr_folder931) shares lists that came into a shared folder after it was shared and missed it, but
   never a list someone was taken off on purpose (created before the share)
 - UX-03 the user setting "sidebar" ({order, hidden}: validated, stored normalized, '' = default)
 - UX-26 accounts added by an admin start with a lean sidebar (Tomorrow / Next 7 days / Now doable hidden), the admin
   who set up the server does not
 - UX-25 the purpose "team" switches on what its name promises only (no habits, focus timer, matrix, statistics)
Restarts its container (start.sh). usage: p2250_api_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FX = os.path.join(N, "fixtures", "import")
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


def dbx(sql, args=(), write=False):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def member(lid, uid):
    return bool(dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (lid, uid)))


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.patch(B + "/api/settings", json={"lang": "en"})
ids = {}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB = ids["bob"]

# ================================================================== #931 lists in a shared folder
old = A.post(B + "/api/lists", json={"name": "Old", "folder": "Clients"}).json()["id"]
r = A.put(B + "/api/folders/people", json={"folder": "Clients", "user_id": BOB, "role": "edit"})
check(r.ok and member(old, BOB), "#931: sharing the folder shares the list in it " + r.text[:120])
check(A.delete(B + f"/api/lists/{old}/members/{BOB}").ok and not member(old, BOB), "#931: bob taken off 'Old' on purpose")
time.sleep(1.1)  # created_at of the next lists is later than the folder share (second precision)
d = A.post(B + "/api/lists", json={"name": "Dialog", "folder": "Clients"}).json()["id"]
check(member(d, BOB), "#931: the list dialog: shared with the folder's people")
r = A.post(B + "/api/lists", json={"name": "App", "folder": "Clients", "ptype": "software"})
check(r.ok and member(r.json()["id"], BOB), "#931: a project of a built-in type in the folder: shared " + r.text[:120])
r = A.post(B + "/api/lists", json={"name": "Groceries", "folder": "Clients", "family": "shopping"})
check(r.ok and member(r.json()["id"], BOB), "#931: a family list in the folder: shared " + r.text[:120])
brd = json.load(open(os.path.join(FX, "trello-board.json")))
brd["name"] = "Clients"
r = A.post(B + "/api/import/trello", files={"file": ("b.json", json.dumps(brd).encode())}, data={"mode": "lists"})
imp = [x[0] for x in dbx("SELECT id FROM lists WHERE owner_id=1 AND folder='Clients' AND name NOT IN ('Old','Dialog','App','Groceries')")]
check(r.ok and imp and all(member(x, BOB) for x in imp), f"#931: an import into the folder (Trello, lists mode): shared {len(imp)} " + r.text[:120])
check(not member(old, BOB), "#931: 'Old' stays without bob")

# the one-time repair: a list that missed the share (written as an older version did) gets it, 'Old' does not
ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 5))
dbx("INSERT INTO lists(name,folder,sort,view,created_at,owner_id) VALUES('Missed','Clients',99,'list',?,1)", (ts,), write=True)
miss = dbx("SELECT id FROM lists WHERE name='Missed'")[0][0]
dbx("DELETE FROM settings WHERE key='migr_folder931'", write=True)
check(not member(miss, BOB), "repair: before the start the list misses bob")
subprocess.run(["docker", "restart", CT], check=True, stdout=subprocess.DEVNULL)
for _ in range(60):
    try:
        if requests.get(B + "/api/health", timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(0.5)
check(member(miss, BOB), "repair (migr_folder931): the missed list is shared now")
check(not member(old, BOB), "repair: a list taken off on purpose stays off")
check(dbx("SELECT value FROM settings WHERE key='migr_folder931'") == [("1",)], "repair: runs once")
A = sess("alice")

# ================================================================== UX-03 / UX-26 the sidebar setting
st = A.get(B + "/api/state").json()["settings"]
check(st.get("sidebar", "") == "", "UX-26: the admin who set up the server: full sidebar")
C = sess("carol")
sc = json.loads(C.get(B + "/api/state").json()["settings"]["sidebar"] or "{}")
check(set(sc.get("hidden", [])) == {"e:tomorrow", "e:week", "e:doable"}, "UX-26: an added account starts lean " + json.dumps(sc))
r = A.patch(B + "/api/settings", json={"sidebar": json.dumps({"order": ["lists", "focus", "lists"], "hidden": ["g:views", "e:week"]})})
check(r.ok and json.loads(A.get(B + "/api/state").json()["settings"]["sidebar"]) == {"order": ["lists", "focus"], "hidden": ["g:views", "e:week"]},
      "UX-03: sidebar stored normalized")
for bad in ({"order": ["nope"]}, {"hidden": ["x:views"]}, {"order": [], "hidden": [], "x": 1}, ["focus"]):
    check(A.patch(B + "/api/settings", json={"sidebar": json.dumps(bad)}).status_code == 400, "UX-03: invalid sidebar refused " + json.dumps(bad))
check(A.patch(B + "/api/settings", json={"sidebar": ""}).ok and A.get(B + "/api/state").json()["settings"]["sidebar"] == "", "UX-03: '' = default")

# ================================================================== UX-25 the purpose "team"
fs = A.post(B + "/api/me/purpose", json={"purpose": "team", "examples": False}).json()["features"].split(",")
check({"collab", "time", "kanban", "timeline", "deps", "fields", "progress"} <= set(fs) and not {"habits", "pomo", "matrix", "stats"} & set(fs),
      "UX-25: team = what the name promises " + str(fs))

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
