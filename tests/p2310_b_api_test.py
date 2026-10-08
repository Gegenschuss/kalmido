#!/usr/bin/env python3
"""2.31.0 API tests (agent B: the task panel), own container (start.sh).
 - #344 the desktop split of the task panel: detail_split (the properties' share above the comments area in %, 20-85, default
   60) and detail_cm_fold (the comments area folded, 0 / 1) are settings per user: defaults in GET /api/state, PATCH
   /api/settings stores them, wrong values are refused with 400 and nothing is stored, another user keeps his own
usage: p2310_b_api_test.py <datadir>"""
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


def sett(s):
    return s.get(B + "/api/state").json()["settings"]


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"})
assert r.ok, r.text
Bo = sess("bob")

st = sett(A)
check(st.get("detail_split") == "60" and st.get("detail_cm_fold") == "0", "#344: defaults 60 % / not folded " + str([st.get("detail_split"), st.get("detail_cm_fold")]))
r = A.patch(B + "/api/settings", json={"detail_split": 72, "detail_cm_fold": True})
st = sett(A)
check(r.ok and st["detail_split"] == "72" and st["detail_cm_fold"] == "1", "#344: stored (number, true -> 1) " + str([r.status_code, st["detail_split"], st["detail_cm_fold"]]))
r = A.patch(B + "/api/settings", json={"detail_split": "45.5", "detail_cm_fold": "0"})
st = sett(A)
check(r.ok and float(st["detail_split"]) == 45.5 and st["detail_cm_fold"] == "0", "#344: a string with decimals, unfolded " + str([r.status_code, st["detail_split"]]))
for bad in ({"detail_split": 10}, {"detail_split": 95}, {"detail_split": "abc"}, {"detail_split": [50]}, {"detail_cm_fold": "maybe"}, {"detail_split": "NaN"}):
    r = A.patch(B + "/api/settings", json=bad)
    check(r.status_code == 400, "#344: refused " + str(bad) + " " + str(r.status_code))
st = sett(A)
check(float(st["detail_split"]) == 45.5 and st["detail_cm_fold"] == "0", "#344: nothing stored after the refusals " + str([st["detail_split"], st["detail_cm_fold"]]))
r = A.patch(B + "/api/settings", json={"detail_split": "", "detail_cm_fold": "1"})
st = sett(A)
check(r.ok and float(st["detail_split"]) == 45.5 and st["detail_cm_fold"] == "1", "#344: an empty split leaves it unchanged " + str([r.status_code, st["detail_split"]]))
sb = sett(Bo)
check(sb["detail_split"] == "60" and sb["detail_cm_fold"] == "0", "#344: per user: Bob keeps the defaults " + str([sb["detail_split"], sb["detail_cm_fold"]]))

print(f"p2310_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
