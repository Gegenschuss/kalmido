#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.466.0 (#3314) API: the areas' introductions and accounts that exist already.
 - the start once marks areas with content as opened (tours_seen): the introduction shows only for areas never used
 - an account without content stays empty; a second start changes nothing (once)
 - KALMIDO_ONBOARDING=0: a new account has them off (tours_more 0), tours_seen takes only a list of ids
freelancer-matrix: onboarding (alice has no organisation)
usage: p2466_tour_seed_test.py <datadir>"""
import os
import subprocess
import sys

import requests

import dbx
import kt
from kt import B, check, sess

kt.fresh()
kt.setup("alice")
A = sess("alice")
s = A.get(B + "/api/state").json()["settings"]
check(s["tours_more"] == "0" and s["tours_seen"] == "", "KALMIDO_ONBOARDING=0: introductions off, nothing seen")
check(A.patch(B + "/api/settings", json={"tours_seen": "cal,office"}).ok, "tours_seen: a list of ids")
check(A.patch(B + "/api/settings", json={"tours_seen": "cal;<x>"}).status_code == 400, "tours_seen: nothing else")
check(A.patch(B + "/api/settings", json={"tours_seen": "a," * 200}).status_code == 400, "tours_seen: not endless")
A.patch(B + "/api/settings", json={"tours_seen": ""})

uid = A.get(B + "/api/state").json()["me"]["id"]


def write(sql, args=()):
    c = dbx.connect(os.path.join(kt.DATA, "tasks.db"))
    c.execute(sql, args)
    c.commit()
    c.close()


write("INSERT INTO journal(user_id, day, text, updated_at) VALUES(?, '2026-01-01', 'x', '2026-01-01T00:00:00Z')", (uid,))
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")


def restart():
    subprocess.run(["docker", "restart", CT], capture_output=True)
    def up():
        try:
            return requests.get(B + "/api/health", timeout=2).ok
        except requests.RequestException:
            return False
    check(kt.until(up, timeout=60), "the container is back")


def seen():
    return A.get(B + "/api/state").json()["settings"]["tours_seen"]


write("DELETE FROM user_settings WHERE key='tours_seen'")
write("DELETE FROM settings WHERE key='migr_tours2466'")
restart()
check(seen() == "review", "the area with content counts as opened: " + seen())
A.patch(B + "/api/settings", json={"tours_seen": "review,cal"})
restart()
check(seen() == "review,cal", "once: a second start changes nothing: " + seen())

sys.exit(kt.done("p2466_tour_seed"))
