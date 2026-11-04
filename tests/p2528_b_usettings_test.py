#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.528.0 part B (#4305, A11): the list settings of a person in user_settings are changed under the account's settings
lock (write_lock "usettings-<id>", the one PATCH /api/settings and the folder routes take), read-change-write in one lock.
A second writer inside the app holds that lock, reads the value, waits until the request really waits for the lock (a
waiting advisory lock in pg_locks, no fixed time), then writes its own change and lets go. A person without an
organisation (freelancer-matrix: lists):
 - PUT /api/lists/<id>/favorite: the star added meanwhile (fav_lists) and the new one both stay
 - POST /api/lists/<id>/fields switches "Custom fields" on for the owner: the module added meanwhile (features) stays
 - POST /api/admin/setup (the admin's own modules) waits for the lock too
usage: p2528_b_usettings_test.py <datadir>"""
import json
import os
import subprocess
import sys
import threading

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

HOLD = """
import json, time
import app
from kalmido.core.db import connect, usettings, uset
c = connect()
c.execute("SELECT pg_advisory_lock(hashtext(?))", (NAME,))
seen = usettings(c, UID).get(KEY) or ""
c.commit()
print("LOCKED", flush=True)
end, waiter = time.monotonic() + 20, False
while time.monotonic() < end and not waiter:  # until the request waits for the lock (a state, not a fixed time)
    waiter = c.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted").fetchone()[0] > 0
    c.commit()
    if not waiter:
        time.sleep(0.05)
uset(c, UID, KEY, ",".join([x for x in seen.split(",") if x] + [ADD]))
c.commit()
c.execute("SELECT pg_advisory_unlock(hashtext(?))", (NAME,))
c.commit()
print("OUT" + json.dumps({"waiter": waiter, "seen": seen}), flush=True)
"""


def race(uid, key, add, request):
    """A second writer of user_settings[key] (adds `add`) holds the lock while request() runs -> (its result, the answer)."""
    head = f"NAME, UID, KEY, ADD = {json.dumps(f'usettings-{uid}')}, {int(uid)}, {json.dumps(key)}, {json.dumps(add)}\n"
    p = subprocess.Popen(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", kt.CT, "python", "-c", head + HOLD],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    first = p.stdout.readline()
    assert first.startswith("LOCKED"), first + p.stderr.read()[-1500:]
    res = {}
    t = threading.Thread(target=lambda: res.update(r=request()))
    t.start()
    out, err = p.communicate(timeout=60)
    t.join(60)
    line = [x for x in out.splitlines() if x.startswith("OUT")]
    assert line, out[-800:] + err[-1500:]
    return json.loads(line[0][3:]), res.get("r")


def uget(uid, key):
    r = kt.dbx("SELECT value FROM user_settings WHERE user_id=? AND key=?", (uid, key))
    return r[0][0] if r else ""


kt.fresh(prefix="P2528BU")
A = kt.setup()
FID, Fr = freelancer(B, A, features="cal,time")
L1 = Fr.post(B + "/api/lists", json={"name": "Garden"}).json()["id"]
L2 = Fr.post(B + "/api/lists", json={"name": "Kitchen"}).json()["id"]
L3 = Fr.post(B + "/api/lists", json={"name": "Garage"}).json()["id"]
check(Fr.put(B + f"/api/lists/{L1}/favorite", json={"on": True}).ok, "a first star")

# favourites: the other writer stars L2 meanwhile (as a second tab's PATCH /api/settings would), the request stars L3
h, r = race(FID, "fav_lists", str(L2), lambda: Fr.put(B + f"/api/lists/{L3}/favorite", json={"on": True}))
check(h["waiter"], "favorite: the request waits for the settings lock")
check(r is not None and r.ok, f"favorite: answered {getattr(r, 'status_code', None)}")
fav = [int(x) for x in uget(FID, "fav_lists").split(",") if x]
check(set(fav) == {L1, L2, L3}, f"favorite: the star set meanwhile and the new one both stay {fav}")

# custom fields switch the module on for the owner: the module added meanwhile stays
h, r = race(FID, "features", "habits", lambda: Fr.post(B + f"/api/lists/{L1}/fields", json={"name": "Size", "type": "text"}))
check(h["waiter"], "fields: the request waits for the settings lock")
check(r is not None and r.ok, f"fields: field created {getattr(r, 'status_code', None)} {getattr(r, 'text', '')[:160]}")
fs = uget(FID, "features").split(",")
check("fields" in fs and "habits" in fs and "time" in fs, f"fields: both modules stay {fs}")

# the first-run setup's own settings of the admin: under the same lock
AID = A.get(B + "/api/state").json()["me"]["id"]
h, r = race(AID, "fav_lists", "", lambda: A.post(B + "/api/admin/setup", json={"lang": "en", "modules": ["cal"]}))
check(h["waiter"], "admin setup: waits for the settings lock")
check(r is not None and r.ok, f"admin setup: answered {getattr(r, 'status_code', None)}")
sys.exit(kt.done("p2528_b_usettings"))
