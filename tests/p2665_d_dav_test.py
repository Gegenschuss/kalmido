#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.665.0 D (#4196): the change state (getctag / sync-token) of a DAV collection comes from its own rows (count, last change,
a digest of the rows in SQL) instead of rendering every object, and the cache of rendered collections hangs on that key
per person and collection instead of the instance-wide change counter. Invented names only.
 - measurement: objects rendered (test header X-Kalmido-Test-Dav-Rendered) and statements (Server-Timing) of a PROPFIND
   Depth 1 on the calendar home with 20 lists x 10 tasks, warm, after a change in ONE list, with only getctag
 - the ctag of a task list changes on: a new task, a changed title, a task in the trash, trash + new task right after,
   moving a task (both lists), the own tag of a task, renaming / recolouring the list, the role of a member (view -> edit);
   a removed member no longer has the list
 - a change in ANOTHER list leaves the ctag and the cache of this list alone (nothing rendered); bob's ctag of a shared list
   stays when alice changes her own (per person) tags, and bob never sees alice's tag
 - sync-collection with the old token reports the changed task and the task in the trash
 - event calendar: a new event changes its ctag, a task change does not; address book: a new contact and a new photo change it
 - a person without an organisation (freelancer-matrix: pim): her list's ctag follows a new task
usage: p2665_d_dav_test.py <datadir>      (a fresh container; P2665D_NOSTART=1 = the server already runs)"""
import os
import re
import sys
import xml.etree.ElementTree as ET

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402
from kt import B, check, sess  # noqa: E402

kt.fresh(env={"KALMIDO_CALDAV_HTTP": "1", "KALMIDO_TEST_TIMING_ALL": "1"}, prefix="P2665D")
kt.docker_logs_on_first_fail()
D_, CS_ = "{DAV:}", "{http://calendarserver.org/ns/}"
PF_CTAG = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:cs="http://calendarserver.org/ns/">'
           '<d:prop><d:displayname/><cs:getctag/></d:prop></d:propfind>')
PF_BOTH = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:cs="http://calendarserver.org/ns/">'
           '<d:prop><d:displayname/><cs:getctag/><d:sync-token/></d:prop></d:propfind>')


class Dav:
    def __init__(self, s, user):
        r = s.post(B + "/api/me/app-passwords", json={"name": "Phone"})
        assert r.ok, r.text
        self.user, self.pw = user, r.json()["password"]

    def req(self, m, path, data=None, **hd):
        h = {"X-Forwarded-Proto": "https", **hd}
        return requests.request(m, B + path, auth=(self.user, self.pw), data=(data or "").encode("utf-8"), headers=h,
                                allow_redirects=False)

    def home(self, body=PF_CTAG, path=None):
        """{collection href: (ctag, sync-token)} of a PROPFIND Depth 1 on the calendar home + the response."""
        r = self.req("PROPFIND", path or f"/dav/calendars/{self.user}/", body, Depth="1",
                     **{"Content-Type": "application/xml"})
        assert r.status_code == 207, (r.status_code, r.text[:300])
        out = {}
        for resp in ET.fromstring(r.content).findall(D_ + "response"):
            href = resp.find(D_ + "href").text
            ct = resp.find(f".//{CS_}getctag")
            st = resp.find(f".//{D_}sync-token")
            if ct is not None and ct.text:
                out[href] = (ct.text, st.text if st is not None else None)
        return out, r

    def ctag(self, coll, kind="calendars"):
        got, _ = self.home(PF_CTAG, f"/dav/{kind}/{self.user}/")
        return got.get(f"/dav/{kind}/{self.user}/{coll}/", (None,))[0]


def rendered(r):
    return int(r.headers.get("X-Kalmido-Test-Dav-Rendered", "-1"))


def statements(r):
    m = re.search(r'n=(\d+)', r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


assert requests.post(B + "/api/auth/setup", headers=kt.H, json={"username": "alice", "display_name": "Alice",
                                                                  "password": kt.PASSWORD}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,events,contacts"})
ME = A.get(B + "/api/state").json()["me"]
ORG = ME["workspaces"][0]["id"]
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "bob", "display_name": "Bob", "password": kt.PASSWORD,
                                   "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
Bs = sess("bob")
Bs.patch(B + "/api/settings", json={"lang": "en", "features": "cal,comments,events,contacts"})

LISTS, SEED = [], {}
for i in range(20):
    r = A.post(B + "/api/lists", json={"name": f"Garden {i:02d}"})
    assert r.ok, r.text
    lid = r.json()["id"]
    LISTS.append(lid)
    for k in range(10):
        r = A.post(B + "/api/tasks", json={"title": f"Seed {i}-{k}", "list_id": lid})
        assert r.ok, r.text
        SEED.setdefault(lid, []).append(r.json()["id"])
L1, L2 = LISTS[0], LISTS[1]
al = Dav(A, "alice")
H1, H2 = f"/dav/calendars/alice/{L1}/", f"/dav/calendars/alice/{L2}/"

# ================================================================== measurement (numbers into the job result)
_, r0 = al.home(PF_BOTH)
_, r1 = al.home(PF_BOTH)
assert A.patch(B + f"/api/tasks/{SEED[L2][0]}", json={"title": "Seed changed"}).ok
_, r2 = al.home(PF_CTAG)
assert A.patch(B + f"/api/tasks/{SEED[L2][1]}", json={"title": "Seed changed too"}).ok
_, r3 = al.home(PF_BOTH)
# PERF lines are kept in the run log (tests/run_all.sh)
for what, r in (("kalt, getctag+sync-token", r0), ("warm, getctag+sync-token", r1),
                ("nach Aenderung in einer Liste, nur getctag", r2), ("nach Aenderung in einer Liste, getctag+sync-token", r3)):
    print(f"PERF p2665_d PROPFIND Depth 1 Home, 20 Listen x 10 Aufgaben, {what}: gerendert={rendered(r)} "
          f"Statements={statements(r)} Server-Timing={r.headers.get('Server-Timing', '-')}", flush=True)
check(rendered(r1) == 0, f"a second PROPFIND renders nothing ({rendered(r1)})")
check(rendered(r2) == 0, f"PROPFIND with only getctag renders no object, also after a change ({rendered(r2)})")
check(0 <= rendered(r3) <= 10, f"a change in ONE list renders at most that list, not all 200 tasks ({rendered(r3)})")


# ================================================================== the ctag of a task list
def task(title, lid=L1):
    r = A.post(B + "/api/tasks", json={"title": title, "list_id": lid})
    assert r.ok, r.text
    return r.json()["id"]


def both():
    got, r = al.home(PF_CTAG)
    return got.get(H1, (None,))[0], got.get(H2, (None,))[0], r


c1, c2, _ = both()
check(c1 and c2 and c1 != c2, "two lists have their own ctag")
T = task("Water the roses")
n1, n2, _ = both()
check(n1 != c1, "a new task changes the ctag of its list")
check(n2 == c2, "a new task leaves the ctag of another list alone")
c1 = n1
A.patch(B + f"/api/tasks/{T}", json={"title": "Water the tulips"})
n1, n2, _ = both()
check(n1 != c1 and n2 == c2, "a changed title changes the ctag of its list only")
c1 = n1
A.delete(B + f"/api/tasks/{T}")
n1, _, _ = both()
check(n1 != c1, "a task in the trash changes the ctag")
c1 = n1
T2 = task("Prune the hedge")
A.delete(B + f"/api/tasks/{T2}")
T3 = task("Prune the hedge")
n1, _, _ = both()
check(n1 != c1, "trash + a new task right after (same count) change the ctag")
c1 = n1
r = A.patch(B + f"/api/tasks/{T3}", json={"list_id": L2})
check(r.ok, f"move a task: {r.status_code} {r.text[:200]}")
n1, n2, _ = both()
check(n1 != c1 and n2 != c2, "moving a task changes the ctag of both lists")
c1, c2 = n1, n2
A.patch(B + f"/api/tasks/{T3}", json={"tags": ["rosebed"]})
n1, n2, _ = both()
check(n2 != c2 and n1 == c1, "the own tag of a task changes the ctag of its list")
c2 = n2
A.patch(B + f"/api/lists/{L1}", json={"name": "Garden renamed"})
n1, _, _ = both()
check(n1 != c1, "renaming the list changes its ctag")
c1 = n1
A.patch(B + f"/api/lists/{L1}", json={"color": "#e11d48"})
n1, _, _ = both()
check(n1 != c1, "a new colour changes the ctag")
c1 = n1
# review L1: texts of a collection are rendered in the person's language: a change of language gives a new ctag
A.patch(B + "/api/settings", json={"lang": "de"})
n1, _, _ = both()
A.patch(B + "/api/settings", json={"lang": "en"})
check(n1 != c1, "a change of the person's language changes the ctag")
n1, _, _ = both()
check(n1 == c1, "... and back to the old language gives the old ctag")

# other lists / instance changes: no new ctag, nothing rendered for L1
al.home(PF_BOTH)
task("Elsewhere", LISTS[5])
Bs.post(B + "/api/lists", json={"name": "Bob private"})
n1, _, r = both()
check(n1 == c1, "a change in another list / by another person leaves the ctag alone")
got, r = al.home(PF_BOTH, H1)
check(rendered(r) == 0, f"... and the cached collection of the list (nothing rendered: {rendered(r)})")

# rights: bob as a member of L1
A.put(B + f"/api/lists/{L1}/members", json={"user_id": BOB, "role": "view"})
bo = Dav(Bs, "bob")
b1 = bo.ctag(L1)
check(b1 is not None, "bob sees the shared list as a calendar")
A.patch(B + f"/api/tasks/{task('Rake leaves')}", json={"tags": ["alicesecret"]})
b2 = bo.ctag(L1)
r = bo.req("REPORT", f"/dav/calendars/bob/{L1}/", '<?xml version="1.0"?><c:calendar-query xmlns:d="DAV:" '
           'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data/></d:prop></c:calendar-query>',
           Depth="1", **{"Content-Type": "application/xml"})
check("Rake leaves" in r.text and "alicesecret" not in r.text, "bob gets the new task but never alice's own tag")
check(b2 != b1, "a new task changes bob's ctag too")
MOW = task("Mow")
b2 = bo.ctag(L1)
A.patch(B + f"/api/tasks/{MOW}", json={"tags": ["alicesecret"]})
check(bo.ctag(L1) == b2, "alice's own tag leaves bob's ctag alone")
A.put(B + f"/api/lists/{L1}/members", json={"user_id": BOB, "role": "edit"})
b3 = bo.ctag(L1)
check(b3 is not None and b3 != b2, "a new role of the member changes his ctag")
A.delete(B + f"/api/lists/{L1}/members/{BOB}")
check(bo.ctag(L1) is None, "a removed member no longer has the list")

# sync-collection: the old token reports what changed
got, _ = al.home(PF_BOTH)
tok = got[H2][1]
T4 = task("Feed the fish", L2)
A.delete(B + f"/api/tasks/{T3}")
r = al.req("REPORT", H2, f'<?xml version="1.0"?><d:sync-collection xmlns:d="DAV:"><d:sync-token>{tok}</d:sync-token>'
           '<d:sync-level>1</d:sync-level><d:prop><d:getetag/></d:prop></d:sync-collection>',
           **{"Content-Type": "application/xml"})
check(r.status_code == 207 and f"kalmido-{T4}-" in r.text and f"kalmido-{T3}-" in r.text and "404 Not Found" in r.text,
      f"sync-collection after a change: the new task and the one in the trash ({r.status_code} {r.text[:300]})")

# ================================================================== events
cal = A.post(B + "/api/evcals", json={"name": "Garden events", "org_id": ORG}).json()["id"]
ek = f"e{cal}"
e1 = al.ctag(ek)
check(e1 is not None, "the event calendar has a ctag")
task("Not an event")
check(al.ctag(ek) == e1, "a task change leaves the event calendar's ctag alone")
r = A.post(B + "/api/events", json={"cal_id": cal, "title": "Harvest", "start": "2026-11-20T10:00", "end": "2026-11-20T11:00"})
check(r.status_code == 201, f"an event: {r.status_code}")
check(al.ctag(ek) not in (None, e1), "a new event changes the ctag of its calendar")

# ================================================================== contacts
bk = A.post(B + "/api/books", json={"name": "Garden people"}).json()["id"]
a1 = al.ctag(f"b{bk}", "addressbooks")
check(a1 is not None, "the address book has a ctag")
r = A.post(B + "/api/contacts", json={"book_id": bk, "fn": "Gil Gardener"})
check(r.ok, f"a contact: {r.status_code}")
CID = r.json().get("id")
a2 = al.ctag(f"b{bk}", "addressbooks")
check(a2 not in (None, a1), "a new contact changes the address book's ctag")
PNG1 = "data:image/png;base64," + "A" * 40 + "QUJD"
PNG2 = "data:image/png;base64," + "B" * 40 + "QUJD"  # same length, other bytes
A.patch(B + f"/api/contacts/{CID}", json={"photo": PNG1})
a3 = al.ctag(f"b{bk}", "addressbooks")
check(a3 != a2, "a contact photo changes the ctag")
A.patch(B + f"/api/contacts/{CID}", json={"photo": PNG2})
check(al.ctag(f"b{bk}", "addressbooks") != a3, "another photo of the same size changes the ctag")

# ================================================================== a person without an organisation
FID, Fr = freelancer(B, A, "frida", features="cal,comments,events,contacts")
FL = Fr.post(B + "/api/lists", json={"name": "Frida plants"}).json()["id"]
fr = Dav(Fr, "frida")
f1 = fr.ctag(FL)
check(f1 is not None, "freelancer: her list is a calendar with a ctag")
Fr.post(B + "/api/tasks", json={"title": "Repot the fern", "list_id": FL})
check(fr.ctag(FL) not in (None, f1), "freelancer: a new task changes her ctag")

sys.exit(kt.done("p2665_d_dav"))
