#!/usr/bin/env python3
"""2.83.0 API tests, part A (#1725): organisation-wide lists ("Everyone in the organisation") -- a member who has not
joined can be assigned where everyone in the organisation may edit (org_edit) and sees the tasks assigned to them in the
calendar feed and in CalDAV (a read-only calendar with only those tasks); the other tasks of the list stay out until
joining. Invented names only. Mode workspaces:
 - assignable only with org_edit (read-only list, another organisation, the agent: refused); org_edit off = unassigned
 - the state carries the assigned task (the app shows it in Today / All, p283_a_ui.js)
 - iCal feed: the assigned task, not the others; CalDAV: the list as a read-only calendar with only the assigned task
   (GET of another task 404, DELETE / PUT 403)
 - a person of another organisation and the organisation's agent see nothing
 - removed from the organisation: gone at once
usage: p283_a_api_test.py <datadir>      (a fresh container; the suite restarts it in mode workspaces)"""
import os
import re
import subprocess
import sys

import requests
from freelancer_fixture import org_join  # 2.148.1 (#2480): an invited member accepts

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
MARK = "Zx7Assigned"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def feed(s):
    # 2.138.0 (#1907): the feed link is only in the answer of create / rotate
    return requests.get(B + s.post(B + "/api/ical", json={"action": "rotate"}).json()["url"].replace("https://kalmido.example", "")).text


def dav_of(s, user):
    pw = s.post(B + "/api/me/app-passwords", json={"name": "phone"}).json()
    d = requests.Session()
    d.auth = (user, pw.get("password") or pw.get("token") or "")
    return d


if not os.environ.get("P283A_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, ERIN = ids["bob"], ids["carol"], ids["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ERIN}).json()["id"]
Bo = sess("bob")
check((Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG)), "setup: carol joins Alpha")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "alphabot", "display_name": "Alpha bot"})
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
dbx("UPDATE agents SET org_id=? WHERE user_id=?", (ORG, AG), write=True)
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG, AG), write=True)
Bo, Ca, Er = sess("bob"), sess("carol"), sess("erin")
for s in (Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

# ---- bob's organisation-wide list: one task assigned to carol (not joined), one not
L = Bo.post(B + "/api/lists", json={"name": f"{MARK} list", "org_id": ORG}).json()["id"]
check(Bo.patch(B + f"/api/lists/{L}", json={"org_visibility": "org"}).ok, "setup: everyone in the organisation")
T1 = Bo.post(B + "/api/tasks", json={"title": f"{MARK} mine", "list_id": L, "due": "2026-10-20"}).json()["id"]
T2 = Bo.post(B + "/api/tasks", json={"title": f"{MARK} other", "list_id": L, "due": "2026-10-21"}).json()["id"]
# assigning a member who has not joined: refused in a read-only list, allowed where everyone in the organisation may edit
r = Bo.patch(B + f"/api/tasks/{T1}", json={"assignee_id": CAROL})
check(r.status_code in (400, 403, 409, 422), f"#1725: a reader of a read-only list is not assignable: {r.status_code}")
check(Bo.patch(B + f"/api/lists/{L}", json={"org_edit": True}).ok, "setup: everyone in the organisation may edit")
r = Bo.patch(B + f"/api/tasks/{T1}", json={"assignee_id": CAROL})
check(r.ok, f"#1725: with org_edit the member who has not joined is assignable: {r.status_code} {r.text[:160]}")
r = Bo.patch(B + f"/api/tasks/{T2}", json={"assignee_id": ERIN})
check(r.status_code in (400, 403, 409, 422), f"#1725: a person of another organisation is not assignable: {r.status_code}")
r = Bo.patch(B + f"/api/tasks/{T2}", json={"assignee_id": AG})
check(r.status_code in (400, 403, 409, 422), f"#1725: the organisation's agent (never a reader) is not assignable: {r.status_code}")
check(not any(m["user_id"] == CAROL for m in (next(x for x in Bo.get(B + "/api/state").json()["lists"] if x["id"] == L).get("members") or [])),
      "#1725: carol is still not a member of the list")
st = Ca.get(B + "/api/state").json()
lr = next((x for x in st["lists"] if x["id"] == L), None)
check(lr is not None and lr.get("org_reader") is True, "carol reads the list without joining")
check(any(t["id"] == T1 and t.get("assignee_id") == CAROL for t in st["tasks"]), "#1725: the state carries the assigned task")

# ---- calendar feed
f = feed(Ca)
check(f"{MARK} mine" in f, "#1725: the assigned task is in carol's calendar feed")
check(f"{MARK} other" not in f, "#1725: the other task of the list is not in the feed")

# ---- CalDAV: a read-only calendar with only the assigned task
dav = dav_of(Ca, "carol")
r = dav.request("PROPFIND", B + "/dav/calendars/carol/", headers={"Depth": "1"})
check(r.status_code == 207 and f"/calendars/carol/{L}/" in r.text, f"#1725: CalDAV lists the list as a calendar ({r.status_code})")
r = dav.request("PROPFIND", B + f"/dav/calendars/carol/{L}/", headers={"Depth": "1"})
hrefs = re.findall(r"<D:href>([^<]+\.ics)</D:href>", r.text)
check(r.status_code == 207 and len(hrefs) == 1 and f"kalmido-{T1}-" in hrefs[0], f"#1725: CalDAV shows only the assigned task: {hrefs}")
r0 = dav.request("PROPFIND", B + f"/dav/calendars/carol/{L}/", headers={"Depth": "0", "Content-Type": "application/xml"},
                 data='<?xml version="1.0"?><D:propfind xmlns:D="DAV:"><D:prop><D:current-user-privilege-set/></D:prop></D:propfind>')
check(r0.status_code == 207 and "current-user-privilege-set" in r0.text and "<D:read/>" in r0.text and "<D:write/>" not in r0.text and "<D:write-content/>" not in r0.text,
      f"#1725: the calendar is read-only ({r0.text[:300]})")
if hrefs:
    h1 = hrefs[0]
    g1 = dav.get(B + h1)
    check(g1.ok and f"{MARK} mine" in g1.text, f"#1725: GET of the assigned task ({g1.status_code})")
    h2 = h1.replace(f"kalmido-{T1}-", f"kalmido-{T2}-")
    check(dav.get(B + h2).status_code == 404, "#1725: GET of another task of the list: 404")
    check(dav.delete(B + h1).status_code == 403, "#1725: DELETE refused (read-only)")
    r = dav.put(B + h1, data=g1.text.replace(f"{MARK} mine", f"{MARK} renamed"), headers={"Content-Type": "text/calendar"})
    check(r.status_code == 403, f"#1725: PUT refused (read-only): {r.status_code}")
    check(dbx("SELECT deleted_at, title FROM tasks WHERE id=?", (T1,))[0][0] is None, "#1725: the task is still there")

# ---- other organisation and the agent see nothing
check(MARK not in feed(Er), "#1725: a person of another organisation: nothing in the feed")
check(not any(t["id"] in (T1, T2) for t in Er.get(B + "/api/state").json()["tasks"]), "#1725: another organisation: nothing in the state")
r = requests.get(B + f"/api/v1/tasks/{T1}", headers=AGH)
check(r.status_code in (403, 404), f"#1725: the organisation's agent does not get the task ({r.status_code})")
dav_e = dav_of(Er, "erin")
r = dav_e.request("PROPFIND", B + f"/dav/calendars/erin/{L}/", headers={"Depth": "1"})
check(r.status_code == 404, f"#1725: another organisation: no CalDAV calendar ({r.status_code})")

# ---- no longer open for editing: the assignment goes (like leaving the list)
check(Bo.patch(B + f"/api/lists/{L}", json={"org_edit": False}).ok, "setup: members of the organisation may only read")
check(dbx("SELECT assignee_id FROM tasks WHERE id=?", (T1,))[0][0] is None, "#1725: org_edit off -> the reader's assignment goes")
check(f"{MARK} mine" not in feed(Ca), "#1725: and the task leaves carol's feed")
check(Bo.patch(B + f"/api/lists/{L}", json={"org_edit": True}).ok and Bo.patch(B + f"/api/tasks/{T1}", json={"assignee_id": CAROL}).ok,
      "setup: open again, carol assigned again")
check(f"{MARK} mine" in feed(Ca), "#1725: back in the feed")

# ---- removed from the organisation: gone
check(Bo.delete(B + f"/api/orgs/{ORG}/members/{CAROL}").ok, "setup: carol leaves Alpha")
check(dbx("SELECT assignee_id FROM tasks WHERE id=?", (T1,))[0][0] is None, "#1725: leaving the organisation removes the assignment")
dbx("UPDATE tasks SET assignee_id=? WHERE id=?", (CAROL, T1), write=True)  # even if an assignment were left behind
Ca = sess("carol")
check(MARK not in feed(Ca), "#1725: after leaving the organisation: nothing in the feed")
r = dav.request("PROPFIND", B + f"/dav/calendars/carol/{L}/", headers={"Depth": "1"})
check(r.status_code == 404, f"#1725: after leaving: no CalDAV calendar ({r.status_code})")
check(not any(t["id"] in (T1, T2) for t in Ca.get(B + "/api/state").json()["tasks"]), "#1725: after leaving: nothing in the state")

print(f"p283_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
