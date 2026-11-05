#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.565.0 A (#4703): calendar writes one after the other. Invented names only, own test calendars.
 - two single dates of one series moved / left out from the same starting state: both changes stay (the list of changed
   dates is read under the event's lock, not from a copy read before); with the version of before the second one gets 409
 - many single dates of one series changed at the same moment (threads): none is lost
 - a phone (CalDAV PUT with If-Match) and the app (PATCH with expect) writing the same state at the same moment: never both
   pass (one 204 / 200, the other 412 / 409), the one that passed is what is stored
 - a CalDAV DELETE with an old ETag after an app change: 412, the event stays
 - the same for a person without an organisation (freelancer-matrix: events)
usage: p2565_a_lock_test.py <datadir>      (P2565A_NOSTART=1 / KMT_NOSTART=1: it runs already)"""
import os
import sys
import threading

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

kt.fresh(prefix="P2565A")
kt.docker_logs_on_first_fail()
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "cal,events,contacts"})
FID, Fr = freelancer(B, A, "frida")


def clone(s):
    """A second device of the same person (its own connection, the same login)."""
    x = requests.Session()
    x.headers.update(s.headers)
    x.cookies.update(s.cookies)
    return x


def at_once(fns):
    """Runs fns at the same moment (one thread each, a barrier) -> their results in order."""
    out, bar = [None] * len(fns), threading.Barrier(len(fns))

    def run(i, f):
        bar.wait()
        try:
            out[i] = f()
        except Exception as e:  # noqa: BLE001  (a broken request counts as a failed check, not a crash)
            out[i] = e
    ts = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(fns)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    return out


class Dav:
    def __init__(self, s, user):
        r = s.post(B + "/api/me/app-passwords", json={"name": "Phone"})
        assert r.ok, r.text
        self.user, self.pw = user, r.json()["password"]

    def req(self, m, path, data=None, **hd):
        h = {"X-Forwarded-Proto": "https", **hd}
        return requests.request(m, B + path, auth=(self.user, self.pw), data=data.encode("utf-8") if isinstance(data, str) else data,
                                headers=h, allow_redirects=False)


def series(s, cal, title, day="2026-12-01"):
    r = s.post(B + "/api/events", json={"cal_id": cal, "title": title, "start": f"{day}T09:00", "end": f"{day}T10:00", "rrule": "FREQ=DAILY;COUNT=30"})
    assert r.status_code == 201, r.text
    return r.json()


def occ(day):
    return f"{day}T09:00"


def checks(s, who, user):
    cal = s.post(B + "/api/evcals", json={"name": f"Locks {who}"}).json()["id"]
    s2 = clone(s)
    # ---- two dates of one series, one after the other, from the same starting state (no version sent: an old client)
    e = series(s, cal, "Standup")
    r1 = s.patch(B + f"/api/events/{e['id']}?occ={occ('2026-12-02')}", json={"start": "2026-12-02T11:00", "end": "2026-12-02T12:00"})
    r2 = s2.delete(B + f"/api/events/{e['id']}?occ={occ('2026-12-03')}")
    g = s.get(B + f"/api/events/{e['id']}").json()
    check(r1.ok and r2.ok and [o["rid"] for o in g["overrides"]] == [occ("2026-12-02")] and g["exdates"] == [occ("2026-12-03")],
          f"{who}: a moved date and a left-out date of the same series both stay {g.get('overrides')} {g.get('exdates')} ({r1.status_code} {r2.status_code})")
    # ---- with the version both read: the second one is refused (409), the first one stays
    e = series(s, cal, "Review")
    r1 = s.patch(B + f"/api/events/{e['id']}?occ={occ('2026-12-04')}", json={"title": "Review A", "expect": e["updated_at"]})
    r2 = s2.patch(B + f"/api/events/{e['id']}?occ={occ('2026-12-05')}", json={"title": "Review B", "expect": e["updated_at"]})
    g = s.get(B + f"/api/events/{e['id']}").json()
    check(r1.ok and r2.status_code == 409 and [o.get("title") for o in g["overrides"]] == ["Review A"],
          f"{who}: the second date with the old version gets 409, the first change stays ({r1.status_code} {r2.status_code} {g.get('overrides')})")
    # the client takes the version of the 409 answer (or reloads it) and moves its date again: both stay
    at = (r2.json().get("event") or {}).get("updated_at") or s2.get(B + f"/api/events/{e['id']}").json()["updated_at"]
    r3 = s2.patch(B + f"/api/events/{e['id']}?occ={occ('2026-12-05')}", json={"title": "Review B", "expect": at})
    g = s.get(B + f"/api/events/{e['id']}").json()
    check(r3.ok and sorted(o.get("title") for o in g["overrides"]) == ["Review A", "Review B"], f"{who}: saved again with the new version: both dates changed {g.get('overrides')}")
    # ---- many dates at the same moment (threads, no version): every change stays
    e = series(s, cal, "Daily")
    days = [f"2026-12-{d:02d}" for d in range(6, 18)]

    def mv(d, i):
        x = clone(s)
        if i % 3 == 2:
            return x.delete(B + f"/api/events/{e['id']}?occ={occ(d)}").status_code
        return x.patch(B + f"/api/events/{e['id']}?occ={occ(d)}", json={"title": f"Daily {d}"}).status_code
    res = at_once([lambda d=d, i=i: mv(d, i) for i, d in enumerate(days)])
    g = s.get(B + f"/api/events/{e['id']}").json()
    want_ov = sorted(occ(d) for i, d in enumerate(days) if i % 3 != 2)
    want_ex = sorted(occ(d) for i, d in enumerate(days) if i % 3 == 2)
    check(all(x in (200, 204) for x in res) and sorted(o["rid"] for o in g["overrides"]) == want_ov and sorted(g["exdates"]) == want_ex,
          f"{who}: {len(days)} dates changed at once, none lost: {res} overrides {len(g['overrides'])}/{len(want_ov)} exdates {len(g['exdates'])}/{len(want_ex)}")
    # ---- the phone and the app at the same moment, both from the same state
    dav = Dav(s, user)
    lost = []
    for i in range(6):
        e = s.post(B + "/api/events", json={"cal_id": cal, "title": f"Call {i}", "start": "2026-12-20T15:00", "end": "2026-12-20T16:00"}).json()
        href = kt.dbx("SELECT href FROM events WHERE id=?", (e["id"],))[0][0]
        path = f"/dav/calendars/{user}/e{cal}/{href}"
        gr = dav.req("GET", path)
        etag, text = gr.headers.get("ETag", ""), gr.text
        phone = text.replace(f"SUMMARY:Call {i}", f"SUMMARY:Call {i} phone")
        rs = at_once([lambda: dav.req("PUT", path, phone, **{"Content-Type": "text/calendar; charset=utf-8", "If-Match": etag}).status_code,
                      lambda: clone(s).patch(B + f"/api/events/{e['id']}", json={"title": f"Call {i} app", "expect": e["updated_at"]}).status_code])
        title = s.get(B + f"/api/events/{e['id']}").json()["title"]
        ok_p, ok_a = rs[0] in (200, 204), rs[1] == 200
        if (ok_p and ok_a) or (not ok_p and not ok_a) or (ok_p and title != f"Call {i} phone") or (ok_a and title != f"Call {i} app") \
                or (not ok_p and rs[0] != 412) or (not ok_a and rs[1] != 409):
            lost.append((i, rs, title))
    check(not lost, f"{who}: phone and app at the same moment: exactly one passes, the other gets 412 / 409 {lost}")
    # ---- a DELETE from the phone with the ETag of before an app change: 412, the event stays
    e = s.post(B + "/api/events", json={"cal_id": cal, "title": "Keep me", "start": "2026-12-21T15:00", "end": "2026-12-21T16:00"}).json()
    href = kt.dbx("SELECT href FROM events WHERE id=?", (e["id"],))[0][0]
    path = f"/dav/calendars/{user}/e{cal}/{href}"
    etag = dav.req("GET", path).headers.get("ETag", "")
    s.patch(B + f"/api/events/{e['id']}", json={"title": "Keep me, changed"})
    r = dav.req("DELETE", path, **{"If-Match": etag})
    check(r.status_code == 412 and s.get(B + f"/api/events/{e['id']}").ok, f"{who}: a DELETE with the old ETag gets 412, the event stays ({r.status_code})")


checks(A, "alice", "alice")
checks(Fr, "frida (no organisation)", "frida")
sys.exit(kt.done("p2565_a_lock"))
