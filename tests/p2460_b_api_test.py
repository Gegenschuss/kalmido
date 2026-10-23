#!/usr/bin/env python3
"""2.46.0 API tests, part B (#1603): who sees an organisation list -- "Only invited people" (the default) or "Everyone in
the organisation" (lists.org_visibility 'org'). Invented names only. Mode workspaces (organisations + private space):
 - default: a member of the organisation who is not invited does not see the list
 - 'org': every member sees it read-only (role view, org_reader), may not change it or add tasks; org_edit: role edit
 - join (POST /api/lists/<id>/join) = a member with the role edit, undo = leaving (back to reader); explicit roles stay
 - a person outside the organisation and the organisation's agent see nothing (web, v1 by id, search)
 - removed from the organisation = no access at once
 - private lists, Home & life and family lists refuse 'org'; a list that becomes private is reset
 - only the owner / list admins change it; v1 shows and changes org_visibility / org_edit
 - readers: search finds the tasks, the calendar feed and CalDAV only the joined lists, no News (bell "all" included)
usage: p2460_b_api_test.py <datadir>      (a fresh container; the suite restarts it in mode workspaces)"""
import os
import subprocess
import sys

import requests
from freelancer_fixture import org_join  # 2.148.1 (#2480): an invited member accepts

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
MARK = "Qv8Orgwide"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def lst(s, lid):
    """The list as the state shows it to s (None = not visible)."""
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)


def task_ids(s):
    return {t["id"] for t in s.get(B + "/api/state").json()["tasks"]}


if not os.environ.get("P2460B_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = ids["bob"], ids["carol"], ids["dave"], ids["erin"]
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
for s in (A, Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
for u in ("carol", "erin"):
    check((Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com"}).ok and org_join(B, u, ORG)), f"setup: {u} joins the organisation")
dbx("DELETE FROM org_members WHERE org_id=? AND user_id NOT IN (?,?,?)", (ORG, BOB, CAROL, ERIN), write=True)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments", "structure"], "username": "alphabot", "display_name": "Alpha bot"})
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
dbx("UPDATE agents SET org_id=? WHERE user_id=?", (ORG, AG), write=True)
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG, AG), write=True)
Bo.post(B + "/api/auth/logout")
Bo = sess("bob")
A.post(B + "/api/auth/logout")
A = sess("alice")
for s in (Ca, Er):
    s.post(B + "/api/auth/logout")
Ca, Er = sess("carol"), sess("erin")

# ---- bob's organisation list with a task and a comment
r = Bo.post(B + "/api/lists", json={"name": f"{MARK} list", "org_id": ORG})
assert r.ok, r.text
L = r.json()["id"]
check(list(dbx("SELECT org_id, org_visibility, org_edit FROM lists WHERE id=?", (L,))[0]) == [ORG, "", 0],
      "new organisation list: only invited people (default)")
T = Bo.post(B + "/api/tasks", json={"title": f"{MARK} task", "list_id": L, "due": "2026-10-20"}).json()["id"]
check(lst(Ca, L) is None and T not in task_ids(Ca), "default: an organisation member who is not invited sees nothing")
check(Ca.get(B + f"/api/tasks/{T}").status_code in (403, 404), "default: the task by id: refused")

# ---- only the owner / list admins switch it; private and family lists refuse it
check(Ca.patch(B + f"/api/lists/{L}", json={"org_visibility": "org"}).status_code in (403, 404), "a stranger cannot switch it")
check(Bo.patch(B + f"/api/lists/{L}", json={"org_visibility": "everyone"}).status_code == 400, "an unknown value: 400")
P = Bo.post(B + "/api/lists", json={"name": "Private list", "org_id": None}).json()["id"]
check(dbx("SELECT org_id FROM lists WHERE id=?", (P,))[0][0] is None, "setup: a private list")
check(Bo.patch(B + f"/api/lists/{P}", json={"org_visibility": "org"}).status_code == 409, "a private list refuses 'org'")
r = Bo.post(B + "/api/lists", json={"name": "Shopping", "org_id": ORG, "family": "shopping"})
FAM = r.json()["id"]
check(Bo.patch(B + f"/api/lists/{FAM}", json={"org_visibility": "org"}).status_code == 409, "a family list refuses 'org'")
check(Bo.patch(B + f"/api/lists/{L}", json={"org_visibility": "org"}).ok, "the owner opens the list to the organisation")

# ---- readers
d = lst(Ca, L)
check(d is not None and d["role"] == "view" and d.get("org_reader") is True, f"'org': a member sees it as reader ({d and d.get('role')})")
check(T in task_ids(Ca), "'org': the reader sees its tasks")
check(Ca.patch(B + f"/api/tasks/{T}", json={"title": "changed"}).status_code in (403, 404), "reader: cannot change a task")
check(Ca.post(B + "/api/tasks", json={"title": "new", "list_id": L}).status_code in (403, 404), "reader: cannot add a task")
check(Ca.patch(B + f"/api/lists/{L}", json={"org_visibility": ""}).status_code == 403, "reader: cannot change the visibility")
check(Ca.patch(B + f"/api/lists/{L}", json={"name": "renamed"}).status_code == 403, "reader: cannot rename the list")
r = Ca.get(B + f"/api/tasks?scope=search&q={MARK}")
check(r.ok and MARK in r.text, "reader: search finds the task")
check(lst(Da, L) is None and T not in task_ids(Da) and Da.get(B + f"/api/tasks/{T}").status_code in (403, 404),
      "a person outside the organisation sees nothing")
r = Da.get(B + f"/api/tasks?scope=search&q={MARK}")
check(MARK not in r.text, "outside: search finds nothing")
r = requests.get(V + "/lists", headers=AGH)
check(r.ok and all(x["id"] != L for x in r.json().get("items", r.json() if isinstance(r.json(), list) else [])), "the organisation's agent: not in its lists")
check(requests.get(V + f"/lists/{L}", headers=AGH).status_code in (403, 404), "the organisation's agent: the list by id refused")
check(requests.get(V + f"/tasks/{T}", headers=AGH).status_code in (403, 404), "the organisation's agent: the task by id refused")
r = requests.get(V + f"/search?q={MARK}", headers=AGH)
check(MARK not in r.text, "the organisation's agent: search finds nothing")

# ---- an agent opening its own organisation list waits for approval
r = requests.post(V + "/lists", headers=AGH, json={"name": "Bot list"})
check(r.status_code == 201, f"setup: the agent's own list ({r.status_code} {r.text[:120]})")
AL = r.json().get("id")
dbx("UPDATE lists SET org_id=? WHERE id=?", (ORG, AL), write=True)
r = requests.patch(V + f"/lists/{AL}", headers=AGH, json={"org_visibility": "org"})
check(r.status_code == 202 and dbx("SELECT org_visibility FROM lists WHERE id=?", (AL,))[0][0] == "",
      f"an agent opening a list: waits for approval ({r.status_code})")
check(Ca.patch(B + f"/api/lists/{AL}", json={"org_visibility": "org"}).status_code in (403, 404), "a stranger cannot open the agent's list")

# ---- v1 for a person: the fields, reading, changing
tok = Ca.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()
CAH = {"Authorization": "Bearer " + (tok.get("token") or "")}
r = requests.get(V + f"/lists/{L}", headers=CAH)
check(r.ok and r.json().get("org_visibility") == "org" and r.json().get("org_reader") is True and r.json().get("role") == "view",
      f"v1: the reader gets the list with org_visibility / org_reader ({r.status_code} {r.text[:200]})")
check(requests.patch(V + f"/tasks/{T}", headers=CAH, json={"title": "x"}).status_code in (403, 404), "v1: the reader cannot change a task")
r = requests.get(V + f"/search?q={MARK}", headers=CAH)
check(r.ok and MARK in r.text, "v1: search finds the task for the reader")
tokb = Bo.post(B + "/api/me/tokens", json={"name": "t", "scopes": ["read", "write"]}).json()
BOH = {"Authorization": "Bearer " + (tokb.get("token") or "")}
r = requests.patch(V + f"/lists/{L}", headers=BOH, json={"org_edit": True})
check(r.ok and r.json().get("org_edit") is True, f"v1: the owner switches org_edit ({r.status_code} {r.text[:200]})")
check(requests.patch(V + f"/lists/{L}", headers=BOH, json={"org_edit": "yes"}).status_code == 400, "v1: org_edit must be a boolean")

# ---- org_edit: readers may edit without joining
d = lst(Er, L)
check(d is not None and d["role"] == "edit" and d.get("org_reader") is True, "org_edit: role edit for the not invited")
check(Er.patch(B + f"/api/tasks/{T}", json={"title": f"{MARK} task 2"}).ok, "org_edit: changes a task")
requests.patch(V + f"/lists/{L}", headers=BOH, json={"org_edit": False})
check(Er.patch(B + f"/api/tasks/{T}", json={"title": f"{MARK} task 3"}).status_code in (403, 404), "org_edit off: read-only again")

# ---- explicitly invited people keep their role
check(Bo.put(B + f"/api/lists/{L}/members", json={"user_id": ERIN, "role": "admin"}).ok, "setup: erin invited as list admin")
d = lst(Er, L)
check(d["role"] == "admin" and not d.get("org_reader"), "an invited person keeps their own role")
check(Er.patch(B + f"/api/lists/{L}", json={"org_edit": True}).ok and Er.patch(B + f"/api/lists/{L}", json={"org_edit": False}).ok,
      "a list admin may change the setting")

# ---- no News / bell for readers
check(Ca.put(B + f"/api/lists/{L}/bell", json={"mode": "all"}).ok, "setup: the reader rings the bell 'all'")
Bo.post(B + f"/api/tasks/{T}/comments", json={"body": f"{MARK} comment one"})
Bo.post(B + "/api/tasks", json={"title": f"{MARK} second", "list_id": L})
r = Ca.get(B + "/api/news")
check(r.ok and MARK not in r.text and f'"list_id": {L}' not in r.text.replace('"list_id":', '"list_id": '), f"reader: no News about the list ({r.text[:200]})")

# ---- calendars follow the joined lists
FEED = Ca.post(B + "/api/ical", json={"action": "rotate"}).json()["url"].replace("https://kalmido.example", "")  # 2.138.0 (#1907): the feed link is only in the answer of create / rotate
feed = requests.get(B + FEED)
check(feed.ok and MARK not in feed.text, "reader: not in the calendar feed")
pw = Ca.post(B + "/api/me/app-passwords", json={"name": "phone"}).json()
dav = requests.Session()
dav.auth = ("carol", pw.get("password") or pw.get("token") or "")
r = dav.request("PROPFIND", B + "/dav/calendars/carol/", headers={"Depth": "1"})
check(r.status_code == 207 and MARK not in r.text, f"reader: no CalDAV calendar ({r.status_code})")

# ---- join (one step back = leave)
r = Ca.post(B + f"/api/lists/{L}/join")
check(r.ok and r.json().get("role") == "edit", f"join: a member with the role edit ({r.status_code} {r.text[:120]})")
d = lst(Ca, L)
check(d["role"] == "edit" and not d.get("org_reader"), "joined: no longer a reader")
check(Ca.post(B + f"/api/lists/{L}/join").status_code == 409, "join twice: 409")
check(Ca.patch(B + f"/api/tasks/{T}", json={"title": f"{MARK} task 4"}).ok, "joined: changes a task")
feed = requests.get(B + FEED)
check(MARK in feed.text, "joined: in the calendar feed")
r = dav.request("PROPFIND", B + "/dav/calendars/carol/", headers={"Depth": "1"})
check(MARK in r.text, "joined: a CalDAV calendar")
Bo.post(B + f"/api/tasks/{T}/comments", json={"body": f"{MARK} comment two"})
check(MARK in Ca.get(B + "/api/news").text, "joined + bell 'all': News about the list")
check(Ca.delete(B + f"/api/lists/{L}/members/{CAROL}").ok, "undo of join: leave")
d = lst(Ca, L)
check(d is not None and d["role"] == "view" and d.get("org_reader") is True, "after leaving: reader again")
check(Da.post(B + f"/api/lists/{L}/join").status_code in (403, 404), "outside the organisation: cannot join")
check(requests.post(V + f"/lists/{L}/join", headers=AGH).status_code in (403, 404), "the organisation's agent: cannot join")
r = requests.post(V + f"/lists/{L}/join", headers=CAH)
check(r.ok, f"v1: a person joins ({r.status_code} {r.text[:120]})")
Ca.delete(B + f"/api/lists/{L}/members/{CAROL}")

# ---- back to "only invited people"
check(Bo.patch(B + f"/api/lists/{L}", json={"org_visibility": ""}).ok, "back to only invited people")
check(lst(Ca, L) is None and T not in task_ids(Ca), "only invited: the reader loses it")
check(lst(Er, L) is not None, "only invited: the invited list admin keeps it")
Bo.patch(B + f"/api/lists/{L}", json={"org_visibility": "org"})
check(lst(Ca, L) is not None, "setup: open again")

# ---- removed from the organisation = no access at once
check(Bo.delete(B + f"/api/orgs/{ORG}/members/{CAROL}").ok, "setup: carol leaves the organisation")
check(lst(Ca, L) is None and T not in task_ids(Ca) and Ca.get(B + f"/api/tasks/{T}").status_code in (403, 404),
      "removed from the organisation: no access")
check(requests.get(V + f"/lists/{L}", headers=CAH).status_code in (403, 404), "removed: v1 refused")

# ---- a list that becomes private is reset
L2 = Bo.post(B + "/api/lists", json={"name": "Second", "org_id": ORG}).json()["id"]
Bo.patch(B + f"/api/lists/{L2}", json={"org_visibility": "org", "org_edit": 1})
check(list(dbx("SELECT org_visibility, org_edit FROM lists WHERE id=?", (L2,))[0]) == ["org", 1], "setup: second list open, org_edit")
r = Bo.patch(B + f"/api/lists/{L2}", json={"life": "home"})
check(r.ok and list(dbx("SELECT org_visibility, org_edit FROM lists WHERE id=?", (L2,))[0]) == ["", 0],
      f"Home & life: back to only invited ({r.status_code})")
check(lst(Er, L2) is None, "Home & life: the organisation does not see it")
L3 = Bo.post(B + "/api/lists", json={"name": "Third", "org_id": ORG}).json()["id"]
Bo.patch(B + f"/api/lists/{L3}", json={"org_visibility": "org"})
r = Bo.patch(B + f"/api/lists/{L3}", json={"org_id": None})
check(r.ok and dbx("SELECT org_visibility FROM lists WHERE id=?", (L3,))[0][0] == "", f"moved to the private space: reset ({r.status_code} {r.text[:120]})")
# 2.46.0 (#1603, review): a list that moves to another organisation is shared again only with its members
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": BOB})
check(r.status_code == 201, f"setup: a second organisation ({r.text[:120]})")
ORG2 = r.json()["id"]
L4 = Bo.post(B + "/api/lists", json={"name": "Fourth", "org_id": ORG}).json()["id"]
Bo.patch(B + f"/api/lists/{L4}", json={"org_visibility": "org", "org_edit": 1})
r = Bo.patch(B + f"/api/lists/{L4}", json={"org_id": ORG2})
check(r.ok and list(dbx("SELECT org_id, org_visibility, org_edit FROM lists WHERE id=?", (L4,))[0]) == [ORG2, "", 0],
      f"moved to another organisation: reset ({r.status_code} {r.text[:120]})")
dbx("UPDATE lists SET org_visibility='org' WHERE id=?", (L2,), write=True)  # a stale value never opens a private list
check(lst(Er, L2) is None and Er.get(B + f"/api/lists/{L2}/members").status_code in (403, 404, 405), "a stale value on a Home & life list opens nothing")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
