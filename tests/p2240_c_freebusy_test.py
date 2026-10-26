#!/usr/bin/env python3
"""2.240.0 C (#2868): free / busy of a colleague only from the organisations both share. Invented names only. Own container
(start.sh, mode workspaces).
 - xavier is in Alpha and Beta: a member of Alpha sees only his Alpha calendar and his Alpha absences, never Beta's or his
   private calendar; a member of Beta the other way round
 - setting freebusy_share: org (default) / all (private + other organisations too) / off (left out, like a stranger); bad = 400
 - asking about oneself still sees every source; a freelancer (no organisation) gets her own bar as before
 - the answer is counted per person: 429 after EFB_RATE answers a minute
freelancer-matrix: pim
usage: p2240_c_freebusy_test.py <datadir>"""
import os
import subprocess
import sys
from datetime import timedelta

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, org_join  # noqa: E402
import testclock  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FEAT = "cal,comments,collab,events,contacts,workload"
TZ = "Europe/Berlin"
EFB_RATE = 120  # kalmido/events/freebusy.py


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def fb(s, day, users):
    return s.get(B + "/api/events/freebusy", params={"day": day, "users": ",".join(str(u) for u in users), "tz": TZ})


def slots(s, day, uid, users=None):
    r = fb(s, day, users or [uid])
    assert r.ok, r.text
    for p in r.json()["people"]:
        if p["user_id"] == uid:
            return [(x["start"], x["end"], x["kind"]) for x in p["slots"]]
    return None


if not os.environ.get("P2240C_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("anna", "berta", "xavier"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
ANNA, BERTA, XAV = ids["anna"], ids["berta"], ids["xavier"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ANNA})
assert r.status_code == 201, r.text
OA = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": BERTA})
assert r.status_code == 201, r.text
OB = r.json()["id"]
An, Be = sess("anna"), sess("berta")
check(An.put(B + f"/api/orgs/{OA}/members", json={"email": "xavier@example.com"}).ok and org_join(B, "xavier", OA), "setup: xavier joins Alpha")
check(Be.put(B + f"/api/orgs/{OB}/members", json={"email": "xavier@example.com"}).ok and org_join(B, "xavier", OB), "setup: xavier joins Beta")
dbx("DELETE FROM org_members WHERE (org_id=? AND user_id NOT IN (?,?)) OR (org_id=? AND user_id NOT IN (?,?))", (OA, ANNA, XAV, OB, BERTA, XAV), write=True)
FID, Fr = freelancer(B, A, "fiona")
An, Be, Xa = sess("anna"), sess("berta"), sess("xavier")
for s in (An, Be, Xa):
    assert s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"}).ok

D = testclock.today() + timedelta(days=21)
while D.weekday() >= 5:
    D += timedelta(days=1)
DS, D2, D3 = D.isoformat(), (D + timedelta(days=1)).isoformat(), (D + timedelta(days=2)).isoformat()


def cal(s, name, org):
    r = s.post(B + "/api/evcals", json={"name": name, "org_id": org})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def ev(s, calid, a, b):
    r = s.post(B + "/api/events", json={"cal_id": calid, "title": "Termin", "start": a, "end": b, "tz": TZ})
    assert r.status_code == 201, r.text
    return r.json()["id"]


ev(Xa, cal(Xa, "Privat", None), f"{DS}T08:00", f"{DS}T09:00")
ev(Xa, cal(Xa, "Alpha-Kalender", OA), f"{DS}T10:00", f"{DS}T11:00")
ev(Xa, cal(Xa, "Beta-Kalender", OB), f"{DS}T12:00", f"{DS}T13:00")
for org, day in ((OA, D2), (OB, D3)):
    dbx("INSERT INTO hub_absences(org_id, user_id, kind, start_date, end_date, status, created_at) VALUES(?,?,?,?,?,?,?)",
        (org, XAV, "vacation", day, day, "approved", "2026-10-01T00:00:00Z"), write=True)
PRIV, ALPHA, BETA, AWAY = ("08:00", "09:00", "busy"), ("10:00", "11:00", "busy"), ("12:00", "13:00", "busy"), [("00:00", "24:00", "away")]

# ---- default: only the shared organisation
check(Xa.get(B + "/api/state").json()["settings"].get("freebusy_share") == "org", "default freebusy_share: org")
got = slots(An, DS, XAV, [ANNA, XAV])
check(got == [ALPHA], f"anna (Alpha) sees only xavier's Alpha calendar, not Beta, not private ({got})")
check(slots(An, D2, XAV) == AWAY and slots(An, D3, XAV) == [], "anna sees his Alpha absence, not the one of Beta")
got = slots(Be, DS, XAV)
check(got == [BETA], f"berta (Beta) sees only the Beta calendar ({got})")
check(slots(Be, D3, XAV) == AWAY and slots(Be, D2, XAV) == [], "berta sees his Beta absence, not the one of Alpha")
check(slots(Xa, DS, XAV) == [PRIV, ALPHA, BETA] and slots(Xa, D2, XAV) == AWAY and slots(Xa, D3, XAV) == AWAY,
      "xavier himself sees every source")

# ---- all / off / bad value
check(Xa.patch(B + "/api/settings", json={"freebusy_share": "bogus"}).status_code == 400, "an unknown value: 400")
check(Xa.patch(B + "/api/settings", json={"freebusy_share": "all"}).ok, "xavier shares all")
got = slots(An, DS, XAV)
check(got == [PRIV, ALPHA, BETA] and slots(An, D3, XAV) == AWAY, f"all: anna sees private + Beta too ({got})")
check(Xa.patch(B + "/api/settings", json={"freebusy_share": "off"}).ok, "xavier shares nothing")
r = fb(An, DS, [ANNA, XAV])
check(r.ok and [p["user_id"] for p in r.json()["people"]] == [ANNA], "off: xavier is left out like a stranger " + r.text[:200])
check(slots(Xa, DS, XAV) == [PRIV, ALPHA, BETA], "off: xavier still sees his own bar")
Xa.patch(B + "/api/settings", json={"freebusy_share": "org"})
check(slots(An, DS, XAV) == [ALPHA], "back to org")

# ---- freelancer: her own bar as before (private calendar)
ev(Fr, cal(Fr, "Fiona", None), f"{DS}T09:00", f"{DS}T09:30")
r = fb(Fr, DS, [FID, XAV, ANNA])
check(r.ok and [p["user_id"] for p in r.json()["people"]] == [FID], "the freelancer: only herself " + r.text[:200])
check(slots(Fr, DS, FID) == [("09:00", "09:30", "busy")], "the freelancer: her private calendar counts")

# ---- per-person limit (berta; the freelancer and anna are not affected)
codes = [fb(Be, DS, [BERTA]).status_code for _ in range(EFB_RATE + 2)]
first = codes.index(429) if 429 in codes else -1
check(first >= EFB_RATE - 10 and set(codes[:first]) == {200}, f"429 after about {EFB_RATE} answers a minute (first at {first})")
check(fb(An, DS, [ANNA]).ok, "another person is not limited by it")

print(f"p2240_c_freebusy: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
