#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.638.0 B: writes one after the other. Invented names only, own test calendars.
 - #4780: the answer to an invitation (app POST /api/events/<id>/rsvp, CalDAV PUT / DELETE of an invitation) takes the
   event's lock 'event-<id>' like every other write of the event: while another connection holds it, the answer waits and
   is not stored; after that COMMIT it goes through. Without the lock the answer passes at once (red).
 - the same for a person without an organisation (freelancer-matrix: events)
usage: p2638_b_locks_test.py <datadir>      (P2638B_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import os
import re
import subprocess
import sys
import threading

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, DATA, check, dbx, until  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(prefix="P2638B")
kt.docker_logs_on_first_fail()
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "cal,events,contacts"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bo = kt.sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "cal,events,contacts"})
FID, Fr = freelancer(B, A, "frida")
DBC, DBN = open(os.path.join(DATA, ".kalmido-db")).read().split()


class Dav:
    def __init__(self, s, user):
        r = s.post(B + "/api/me/app-passwords", json={"name": "Phone"})
        assert r.ok, r.text
        self.user, self.pw = user, r.json()["password"]

    def req(self, m, path, data=None, **hd):
        return requests.request(m, B + path, auth=(self.user, self.pw), data=data.encode("utf-8") if isinstance(data, str) else data,
                                headers={"X-Forwarded-Proto": "https", **hd}, allow_redirects=False)


def lock_rows(eid):
    """[granted, ...] of the advisory locks on 'event-<eid>' (write_lock: pg_advisory_xact_lock(hashtext(name)))."""
    return [bool(x[0]) for x in dbx("SELECT granted FROM pg_locks WHERE locktype='advisory' AND objsubid=1 "
                                    "AND objid::text::bigint = (hashtext(?)::bigint & 4294967295)", (f"event-{eid}",))]


class Holder:
    """Another connection holding the event's lock (an open transaction in psql) until release()."""
    def __init__(self, eid):
        self.eid = eid
        self.p = subprocess.Popen(["docker", "exec", "-i", DBC, "psql", "-U", "kalmido", "-d", DBN, "-X", "-q"], stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        self.p.stdin.write(f"BEGIN;\nSELECT pg_advisory_xact_lock(hashtext('event-{int(eid)}'));\n")
        self.p.stdin.flush()
        self.ok = bool(until(lambda: True in lock_rows(eid), 20))

    def release(self):
        self.p.stdin.write("COMMIT;\n\\q\n")
        self.p.stdin.close()
        self.p.wait(30)


def partstat(eid, uid):
    x = dbx("SELECT partstat FROM event_attendees WHERE event_id=? AND user_id=?", (eid, uid))
    return x[0][0] if x else None


def waits(who, eid, uid, call, want):
    """call() (one request) while another connection holds the event's lock: it must wait (a not granted lock on
    'event-<eid>'), store nothing meanwhile, and go through after the COMMIT."""
    before = partstat(eid, uid)
    h = Holder(eid)
    check(h.ok, f"{who}: the other connection holds the event's lock")
    out = {}
    t = threading.Thread(target=lambda: out.update(r=call()))
    t.start()
    blocked = until(lambda: False in lock_rows(eid) or not t.is_alive(), 20) and t.is_alive()
    mid = partstat(eid, uid)
    h.release()
    t.join(60)
    r = out.get("r")
    check(blocked, f"{who}: the answer waits for the event's lock (#4780)")
    check(mid == before, f"{who}: nothing stored while the lock is held ({before} -> {mid})")
    check(r is not None and r.status_code in (200, 204) and partstat(eid, uid) == want,
          f"{who}: after the COMMIT the answer is stored ({r is not None and r.status_code} {partstat(eid, uid)})")


# ---- #4780: the app's answer (bob, invited to alice's event)
TEAM = A.post(B + "/api/evcals", json={"name": "Team locks", "org_id": ORG}).json()["id"]
r = A.post(B + "/api/events", json={"cal_id": TEAM, "title": "Planning", "start": "2026-12-03T10:00", "end": "2026-12-03T11:00",
                                    "attendees": [{"user_id": BOB}]})
assert r.status_code == 201, r.text
E1 = r.json()["id"]
waits("app", E1, BOB, lambda: Bo.post(B + f"/api/events/{E1}/rsvp", json={"partstat": "accepted"}), "accepted")

# ---- #4780: CalDAV: the phone answers (PUT with PARTSTAT) and removes the invitation (DELETE = declined)
bob = Dav(Bo, "bob")
r = bob.req("PROPFIND", "/dav/calendars/bob/inv/", '<?xml version="1.0"?><D:propfind xmlns:D="DAV:"><D:prop><D:getetag/></D:prop></D:propfind>',
            Depth="1", **{"Content-Type": "application/xml"})
items = [x for x in re.findall(r"<D:href>([^<]+)</D:href>", r.text) if x.endswith(".ics")]
check(r.status_code == 207 and len(items) == 1, f"bob's invitations on the phone ({r.status_code} {items})")
H1 = items[0] if items else "/dav/calendars/bob/inv/none.ics"
g = bob.req("GET", H1)
lines = []
for line in g.text.replace("\r\n ", "").split("\r\n"):
    if line.startswith("ATTENDEE") and f"urn:kalmido:user:{BOB}" in line:
        line = re.sub(r"PARTSTAT=[A-Z-]+", "PARTSTAT=TENTATIVE", line)
    lines.append(line)
waits("CalDAV PUT", E1, BOB, lambda: bob.req("PUT", H1, "\r\n".join(lines), **{"Content-Type": "text/calendar; charset=utf-8"}), "tentative")
waits("CalDAV DELETE", E1, BOB, lambda: bob.req("DELETE", H1), "declined")

# ---- a person without an organisation: her answer to her own event (freelancer-matrix: events)
r = Fr.post(B + "/api/events", json={"title": "Studio", "start": "2026-12-04T10:00", "end": "2026-12-04T11:00", "attendees": [{"user_id": FID}]})
check(r.status_code == 201, f"frida: an event with herself invited ({r.status_code} {r.text[:200]})")
E2 = (r.json() or {}).get("id") if r.ok else None
if E2:
    waits("frida", E2, FID, lambda: Fr.post(B + f"/api/events/{E2}/rsvp", json={"partstat": "tentative"}), "tentative")

sys.exit(kt.done("p2638_b_locks"))
