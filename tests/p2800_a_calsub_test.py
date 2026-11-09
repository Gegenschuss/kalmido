#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.800.0 API test, part A (#5466): removing a calendar subscription can be taken back. Own container (start.sh).
 - DELETE /api/calendars/<id> answers with an undo token; POST /api/calendars/restore {undo} puts the subscription back with
   its id (the Today / planning switches keep pointing at it), name, colour, shown flag, its sealed link and login, as a
   pending one that is fetched again
 - the token works once, only for its own account (another person's try finds nothing and leaves it), a bad one is refused
 - checked as a person without an organisation (tests/freelancer_fixture.py)
freelancer-matrix: pim
usage: p2800_a_calsub_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import check, dbx, done, me_id, sess  # shared helpers (tests/kt.py)
from freelancer_fixture import freelancer

subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,events"})
FID, Fr = freelancer(B, A)


def add_sub(uid, name):
    """A subscription as the settings make one (link and password sealed for the person), without fetching it."""
    code = f"""from kalmido.core.db import connect
from kalmido.calendars.subscriptions import cal_seal
c = connect()
c.execute("INSERT INTO cal_subs(user_id,kind,name,color,visible,interval,url,url_hint,username,password,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
          ({uid}, 'caldav', {name!r}, '#f5b041', 0, 60, cal_seal(c, {uid}, 'https://cal.example.org/dav/u/club/'), 'https://cal.example.org/...', 'club',
           cal_seal(c, {uid}, 'secret-word'), 'ok', '2026-01-01T00:00:00Z'))
print(c.execute('SELECT MAX(id) FROM cal_subs').fetchone()[0])
c.commit(); c.close()"""
    return int(subprocess.run(["docker", "exec", CT, "python", "-c", code], check=True, capture_output=True, text=True).stdout.strip())


def row(sid):
    r = dbx("SELECT user_id, kind, name, color, visible, interval, url, url_hint, username, password FROM cal_subs WHERE id=?", (sid,))
    return tuple(r[0]) if r else None


SID = add_sub(FID, "Club fixtures")
before = row(SID)
check(before and before[0] == FID, f"the freelancer's subscription ({before})")
Fr.patch(B + "/api/settings", json={"today_cals_hidden": [f"s:{SID}"]})

# ---- removed: the answer carries the token, the subscription is gone
r = Fr.delete(B + f"/api/calendars/{SID}")
j = r.json() if r.ok else {}
tok = j.get("undo")
check(r.ok and isinstance(tok, str) and len(tok) >= 16 and not any(s["id"] == SID for s in j.get("subs", [])),
      f"removed, with an undo token ({r.status_code} {r.text[:200]})")
check(row(SID) is None, "the row is gone")

# ---- another person cannot use it, and does not use it up
r = A.post(B + "/api/calendars/restore", json={"undo": tok})
check(r.status_code == 409 and row(SID) is None, f"another person's try: refused, nothing back ({r.status_code})")
for bad in (None, "", 5, "x" * 65, "0" * 32):
    r = Fr.post(B + "/api/calendars/restore", json={"undo": bad})
    check(r.status_code == 409, f"a bad token is refused: {bad!r} ({r.status_code})")

# ---- the person takes it back: the same id, name, colour, shown flag, sealed link and login
r = Fr.post(B + "/api/calendars/restore", json={"undo": tok})
j = r.json() if r.ok else {}
check(r.ok and j.get("restored") == SID, f"back with its id ({r.status_code} {r.text[:200]})")
sub = next((s for s in j.get("subs", []) if s["id"] == SID), {})
check(sub.get("name") == "Club fixtures" and sub.get("color") == "#f5b041" and sub.get("visible") is False and sub.get("interval") == 60
      and sub.get("username") == "club" and sub.get("password_saved") is True, f"name, colour, hidden, interval, login as before ({sub})")
check(row(SID) == before, "the stored row (sealed link and password included) is the same")
check(Fr.get(B + "/api/state").json()["settings"]["today_cals_hidden"] == f'["s:{SID}"]', "the Today switch still points at it")

# ---- once only
r = Fr.post(B + "/api/calendars/restore", json={"undo": tok})
check(r.status_code == 409 and len([s for s in Fr.get(B + "/api/calendars").json()["subs"] if s["id"] == SID]) == 1,
      f"the token works once ({r.status_code})")

# ---- another person's subscription cannot be removed through this route
SA = add_sub(me_id(A), "Alice's feed")
r = Fr.delete(B + f"/api/calendars/{SA}")
check(r.status_code == 404 and row(SA) is not None, f"another person's subscription: 404, kept ({r.status_code})")

sys.exit(done("p2800_a_calsub_test"))
