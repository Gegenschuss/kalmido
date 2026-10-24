#!/usr/bin/env python3
"""2.269.0 B (#3014): office settings and the account's settings lose no change when two saves come at the same time.
 - two parallel PUT /api/office/settings (two sessions, different keys) both stay, several rounds (the office_settings lock)
 - PATCH /api/settings set_delta: one entry of a list setting added / removed (agents_hidden, features, folders,
   trial_hint_seen); two parallel adds of the same account both stay; a whole value still replaces as before; a wrong
   key / entry is a 400 and nothing changes
 - a folder rename running next to a set_delta add keeps both (the account's settings lock)
 - a person without an organisation (freelancer-matrix: office): the same in the personal office
usage: p2269_b_settings_test.py <datadir>      (KMT_NOSTART=1 / P2269B_NOSTART=1: a running server)"""
import json
import sys
import threading

from freelancer_fixture import freelancer, login
from kt import B, check, done, fresh, sess, setup

fresh(prefix="P2269B")
A = setup()
ALICE = A.get(B + "/api/state").json()["me"]["id"]
FEAT = "cal,comments,collab,office,clients,agents"
A.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
A.patch(B + "/api/settings", json={"workspace": f"org:{ORG}"})
S = "/api/office/settings"
ROUNDS = 8


def parallel(*calls):
    """runs the calls at the same moment (a barrier), -> their results in order"""
    bar, out = threading.Barrier(len(calls)), [None] * len(calls)

    def run(i, fn):
        bar.wait()
        out[i] = fn()
    ts = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    return out


def office_rounds(s1, s2, who):
    s1.get(B + S)  # the office area exists before the race
    lost = 0
    for i in range(ROUNDS):
        col, days = f"#{(i * 37) % 256:02x}4a{(i * 11) % 256:02x}", 10 + i
        r1, r2 = parallel(lambda: s1.put(B + S, json={"color": col}), lambda: s2.put(B + S, json={"payment_days": days}))
        check(r1.status_code == 200 and r2.status_code == 200, f"{who}: round {i}: both saves 200 ({r1.status_code}, {r2.status_code} {r2.text[:120]})")
        st = s1.get(B + S).json()["settings"]
        if st.get("color") != col or st.get("payment_days") != days:
            lost += 1
    check(lost == 0, f"{who}: two parallel saves with different keys keep both changes ({lost} of {ROUNDS} rounds lost one)")


def settings(s):
    return s.get(B + "/api/state").json()["settings"]


def delta_suite(s1, s2, who):
    # one entry of a comma list
    check(s1.patch(B + "/api/settings", json={"agents_hidden": "3"}).ok, f"{who}: a whole value still replaces")
    check(settings(s1)["agents_hidden"] == "3", f"{who}: whole value stored")
    r = s1.patch(B + "/api/settings", json={"set_delta": {"agents_hidden": {"add": [5, "7"]}}})
    check(r.ok and settings(s1)["agents_hidden"] == "3,5,7", f"{who}: set_delta add keeps the others ({r.status_code} {settings(s1)['agents_hidden']})")
    r = s1.patch(B + "/api/settings", json={"set_delta": {"agents_hidden": {"remove": [3]}}})
    check(r.ok and settings(s1)["agents_hidden"] == "5,7", f"{who}: set_delta remove takes only that entry")
    # wrong key / entry: 400, nothing changed
    r = s1.patch(B + "/api/settings", json={"set_delta": {"lang": {"add": ["de"]}}})
    check(r.status_code == 400, f"{who}: set_delta of a key that is no list: 400 ({r.status_code})")
    r = s1.patch(B + "/api/settings", json={"set_delta": {"agents_hidden": {"add": ["x1"]}}})
    check(r.status_code == 400 and settings(s1)["agents_hidden"] == "5,7", f"{who}: a wrong entry: 400, nothing changed ({r.status_code})")
    r = s1.patch(B + "/api/settings", json={"set_delta": {"agents_hidden": {"put": [1]}}})
    check(r.status_code == 400, f"{who}: an unknown operation: 400")
    # features (the module switch) and trial_hint_seen (a json list)
    f0 = settings(s1)["features"].split(",")
    r = s1.patch(B + "/api/settings", json={"set_delta": {"features": {"remove": ["cal"]}}})
    check(r.ok and settings(s1)["features"].split(",") == [x for x in f0 if x != "cal"], f"{who}: a module off by set_delta, the others stay")
    s1.patch(B + "/api/settings", json={"set_delta": {"features": {"add": ["cal"]}}})
    check("cal" in settings(s1)["features"].split(","), f"{who}: a module on again by set_delta")
    r = s1.patch(B + "/api/settings", json={"set_delta": {"trial_hint_seen": {"add": ["4:offer"]}}})
    check(r.ok and json.loads(settings(s1)["trial_hint_seen"]) == ["4:offer"], f"{who}: trial_hint_seen add ({r.status_code} {r.text[:120]})")
    # two devices add a folder each at the same moment: both stay
    lost = 0
    for i in range(ROUNDS):
        a, b = f"Race A{i}", f"Race B{i}"
        r1, r2 = parallel(lambda: s1.patch(B + "/api/settings", json={"set_delta": {"folders": {"add": [a]}}}),
                          lambda: s2.patch(B + "/api/settings", json={"set_delta": {"folders": {"add": [b]}}}))
        fs = json.loads(settings(s1)["folders"] or "[]")
        if not (r1.ok and r2.ok and a in fs and b in fs):
            lost += 1
    check(lost == 0, f"{who}: two parallel folder adds keep both ({lost} of {ROUNDS} rounds lost one)")
    fs = json.loads(settings(s1)["folders"] or "[]")
    check(fs[:2] == ["Race A0", "Race B0"] or fs[:2] == ["Race B0", "Race A0"], f"{who}: the order of the earlier folders stays ({fs[:3]})")
    # a folder rename next to a folder add
    lost = 0
    for i in range(ROUNDS):
        new, add = f"Moved {i}", f"Race C{i}"
        r1, r2 = parallel(lambda: s1.post(B + "/api/folders/rename", json={"old": f"Race A{i}", "new": new}),
                          lambda: s2.patch(B + "/api/settings", json={"set_delta": {"folders": {"add": [add]}}}))
        fs = json.loads(settings(s1)["folders"] or "[]")
        if not (r1.ok and r2.ok and new in fs and add in fs and f"Race A{i}" not in fs):
            lost += 1
    check(lost == 0, f"{who}: a folder rename and a parallel folder add both stay ({lost} of {ROUNDS} rounds lost one)")
    # the notification matrix as a partial change (the web app's switch)
    r = s1.patch(B + "/api/settings", json={"notify": {"assign": {"push": 0}}})
    check(r.ok and json.loads(settings(s1)["notify"] or "{}").get("assign", {}).get("push") == 0, f"{who}: one switch of the matrix ({r.status_code} {r.text[:100]})")


# ---------------------------------------------------------------- an organisation's office
office_rounds(A, sess("alice"), "org admin")
delta_suite(A, sess("alice"), "org admin")

# ---------------------------------------------------------------- a person without an organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
check(Fr.get(B + S).json().get("role") == "admin", "freelancer: admin of the personal office")
office_rounds(Fr, login(B, "frida"), "freelancer")
delta_suite(Fr, login(B, "frida"), "freelancer")
check(A.get(B + S).json()["settings"].get("payment_days") == 10 + ROUNDS - 1, "freelancer: the organisation's office untouched")

sys.exit(done("p2269_b_settings"))
