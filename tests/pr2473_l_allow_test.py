#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.473.0 (#3569, rest of review #3389): after a fallback to an older version changed the old list cal_allow_hosts, the next
start copies it into every purpose again, so a host removed there does not stay allowed. Nothing else overwrites the lists
per purpose: not a plain restart, not the old field changed in this version, not the first start with no mark yet.
usage: pr2473_l_allow_test.py <datadir>"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kt  # noqa: E402
from kt import B, check, dbx, sess  # noqa: E402

A = kt.setup()


def by():
    return A.get(B + "/api/about").json()["allow_hosts_by_purpose"]


def mark():
    r = dbx("SELECT value FROM settings WHERE key='allow_hosts_copied_from'")
    return r[0][0] if r else None


def restart():
    global A
    kt.fresh(keep=True)
    A = sess("alice")


check(mark() == "", f"a fresh server notes the empty old list as copied: {mark()!r}")
r = A.patch(B + "/api/admin/settings", json={"cal_allow_hosts": "10.1.1.1:8443"})
check(r.ok and mark() == "10.1.1.1:8443", f"the old field changed here moves the mark along: {mark()!r}")
assert A.patch(B + "/api/admin/settings", json={"allow_hosts_by_purpose": {"calendar": "10.2.2.2:8443"}}).ok
restart()
check(by()["calendar"] == "10.2.2.2:8443" and by()["git"] == "10.1.1.1:8443", f"a plain restart keeps the lists per purpose: {by()}")

# the older version only changes the old list, the mark stays behind
dbx("UPDATE settings SET value='10.3.3.3:8443' WHERE key='cal_allow_hosts'")
restart()
check(set(by().values()) == {"10.3.3.3:8443"}, f"changed after a fallback: copied into every purpose again: {by()}")
check(mark() == "10.3.3.3:8443", f"the mark follows: {mark()!r}")
assert A.patch(B + "/api/admin/settings", json={"allow_hosts_by_purpose": {"calendar": "10.4.4.4:8443"}}).ok
restart()
check(by()["calendar"] == "10.4.4.4:8443", f"copied once only: {by()}")

# a server of an older version: copied long ago, no mark yet -- a list kept per purpose must survive the update
dbx("DELETE FROM settings WHERE key='allow_hosts_copied_from'")
restart()
check(by()["calendar"] == "10.4.4.4:8443", f"the first start with this version overwrites nothing: {by()}")
check(mark() == "10.3.3.3:8443", f"and notes the old list: {mark()!r}")

sys.exit(kt.done("pr2473_l_allow"))
