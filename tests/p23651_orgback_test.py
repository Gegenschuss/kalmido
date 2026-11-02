#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.365.1 (#3395): leaving an organisation (or being removed) takes along what the person brought in from their private
space, not only projects: tables, files and folders, knowledge pages, video reviews, polls and bookmarks. Invented names only,
addresses @example.com. tenant-matrix: org
 - brought in (move-space private -> organisation): back in the private space, the organisation no longer has it
 - made in the organisation / in the trash / another member's file in a brought folder: stays
 - consequences as a move: shares end, the attachment to a project of the organisation lets go, a project that went back
   keeps its table, further sheets follow, a file stays readable, a name taken gets " (2)", links between the pages follow
 - GET leave-info: back_counts / back_text next to stays, what cannot go by itself = kept (a space with the lock, the same link)
 - the removed person's News counts everything, the organisation's log has one row per area, the admins are told
 - a way out clears the mark (out and in by an admin of the same organisation: not brought in by the admin's move out)
 - the old data: the mark comes from the last move in space_moves, one-time at the start
 - a person without an organisation (freelancer-matrix: orgadmin): no preview of another organisation (404)
usage: p23651_orgback_test.py <datadir>      (P23651_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402

TIMES = [{"start": "2031-03-10T10:00"}, {"start": "2031-03-11T14:30"}]
FEAT = FEATURES + ",sheets,wiki,office,clients"

if os.environ.get("P23651_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "time_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = (ids[u] for u in ("bob", "carol", "dave", "erin"))


def sql(q, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        cur = c.execute(q, args)
        out = cur.fetchall() if not write else None
        if write:
            c.commit()
        return out
    finally:
        c.close()


def user(u, oid):
    s = sess(u)
    r = s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "workspace": f"org:{oid}", "features": FEAT})
    assert r.ok, r.text
    return s


r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
SP = f"org:{ORG}"
Bo = user("bob", ORG)
for u in ("carol", "dave", "erin"):
    check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}@example.com"}).ok and org_join(B, u, ORG), f"setup: {u} joins")
Ca, Da, Er = user("carol", ORG), user("dave", ORG), user("erin", ORG)


def org_of(table, i):
    return sql(f"SELECT org_id FROM {table} WHERE id=?", (i,))[0][0]


def brought(table, i):
    return sql(f"SELECT brought_by FROM {table} WHERE id=?", (i,))[0][0]


def in_sheet(s, title, space="private"):
    r = s.post(B + "/api/sheets", json={"title": title, "space": space})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def sheet_in(s, sid):
    r = s.post(B + f"/api/sheets/{sid}/move-space", json={"to": SP})
    check(r.ok, f"setup: table {sid} into Alpha ({r.text[:160]})")


def upload(s, name, data, **form):
    r = s.post(B + "/api/files/upload", files={"file": (name, data)}, data=form)
    assert r.status_code in (200, 201), r.text
    return r.json()["items"][0]["id"]


def files_in(s, ids_):
    r = s.post(B + "/api/files/move-space", json={"ids": ids_, "to": SP})
    check(r.ok, f"setup: files into Alpha ({r.text[:160]})")


def page(s, path, text, space="private"):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def pages_in(s, pids):
    r = s.post(B + "/api/wiki/move-space", json={"pages": pids, "space": "private", "to": SP, "dest": ""})
    check(r.ok, f"setup: pages into Alpha ({r.text[:160]})")


def poll(s, title, space=None):
    r = s.post(B + "/api/polls", json={"title": title, "duration": 60, "tz": "Europe/Berlin", "options": TIMES, **({"space": space} if space else {})})
    assert r.status_code in (200, 201), r.text
    j = r.json()
    return (j.get("poll") or j)["id"]


def mark(s, url, title, space=None):
    r = s.post(B + "/api/bookmarks", json={"url": url, "title": title, **({"space": space} if space else {})})
    assert r.status_code in (200, 201), r.text
    return r.json()["bookmark"]["id"]


def video(s, lid, title):
    r = s.post(B + "/api/videos", json={"list_id": lid, "url": "https://example.com/film.webm", "title": title})
    assert r.status_code in (200, 201), r.text
    j = r.json()
    return (j.get("review") or j)["id"]


def alist(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org})
    assert r.ok, r.text
    return r.json()["id"]


# ================================================================ carol brings things in, then leaves
OWNL = alist(Ca, "Carols own")
check(Ca.patch(B + f"/api/lists/{OWNL}", json={"org_id": ORG}).ok, "setup: carol's project into Alpha")
PRIVL = alist(Ca, "Carols private")
ORGL = alist(Bo, "Alpha project", ORG)

T1 = in_sheet(Ca, "Brought table")          # a plain table with a share
sheet_in(Ca, T1)
check(brought("sheets", T1) == CAROL, "the mark: a table moved private -> organisation notes who brought it")
r = Ca.post(B + f"/api/sheets/{T1}/tabs", json={"name": "Second"})
T1B = (r.json().get("tab") or {}).get("id")
check(bool(T1B), f"setup: a further sheet ({r.status_code} {r.text[:120]})")
check(Ca.post(B + f"/api/sheets/{T1}/shares", json={"user_id": DAVE, "role": "read"}).ok, "setup: table shared with dave")
T2 = in_sheet(Ca, "Bound to the project that goes back", SP)  # made in Alpha: stays
T3 = in_sheet(Ca, "Bound brought table")    # brought in, then attached to a project of Alpha and one that goes back
sheet_in(Ca, T3)
check(Ca.patch(B + f"/api/sheets/{T3}", json={"list_id": OWNL}).ok, "setup: T3 attached to carol's project")
T4 = in_sheet(Ca, "Brought, attached to Alpha")
sheet_in(Ca, T4)
sql("UPDATE sheets SET list_id=? WHERE id=?", (ORGL, T4), write=True)
T5 = in_sheet(Ca, "Thrown away")
sheet_in(Ca, T5)
check(Ca.delete(B + f"/api/sheets/{T5}").ok, "setup: a brought table in the trash")

DOC = upload(Ca, "brief.txt", b"carols words")
FOLD = Ca.post(B + "/api/files/folders", json={"name": "Brought folder", "space": "private"}).json()["id"]
INNER = upload(Ca, "inner.txt", b"inside the folder", parent_id=FOLD)
files_in(Ca, [DOC, FOLD])
check(brought("fs_nodes", DOC) == CAROL and brought("fs_nodes", INNER) == CAROL, "the mark: every moved node")
THEIRS = upload(Bo, "bobs.txt", b"bob added this", parent_id=FOLD)  # another member's file in the brought folder
check(brought("fs_nodes", THEIRS) is None, "a file added in the organisation has no mark")
MADE = upload(Ca, "made.txt", b"made in alpha", space=SP)
check(upload(Ca, "brief.txt", b"a second one, same name"), "setup: the same file name again, private")

P1 = page(Ca, "Home", "see [[Second]]")
P2 = page(Ca, "Second", "text two")
pages_in(Ca, [P1, P2])
check(brought("wiki_pages", P1) == CAROL, "the mark: a page")
page(Ca, "Second", "private page of the same name")  # the name is taken when P2 comes back
PM = page(Ca, "Made here", "stays", SP)

Q1 = poll(Ca, "Team lunch")
r = Ca.post(B + f"/api/polls/{Q1}/move-space", json={"to": SP})
check(r.ok and brought("sched_polls", Q1) == CAROL, f"the mark: a poll ({r.text[:160]})")
QM = poll(Ca, "Made in Alpha", SP)

M1 = mark(Ca, "https://example.com/one", "One")
M2 = mark(Ca, "https://example.com/two", "Two")
r = Ca.post(B + "/api/bookmarks/move-space", json={"ids": [M1, M2], "to": SP})
check(r.ok and brought("bookmarks", M1) == CAROL, f"the mark: bookmarks ({r.text[:160]})")
mark(Ca, "https://example.com/two", "Two again")  # the same link is saved privately now: M2 stays

MADEL = alist(Ca, "Made in Alpha", ORG)  # goes to bob with the leaving
V1 = video(Ca, PRIVL, "Rough cut")
r = Ca.post(B + f"/api/videos/{V1}/move-space", json={"to": SP, "place": MADEL})
check(r.ok and brought("video_reviews", V1) == CAROL, f"the mark: a video review ({r.text[:160]})")
V2 = video(Ca, PRIVL, "Second cut")
r = Ca.post(B + f"/api/videos/{V2}/move-space", json={"to": SP, "place": OWNL})
check(r.ok, f"setup: review at carol's project ({r.text[:160]})")

j = Ca.get(B + f"/api/orgs/{ORG}/leave-info").json()
bc = j.get("back_counts") or {}
check(bc.get("tables") == 3, f"leave-info: three tables go back ({bc})")
check(bc.get("files") == 2 and bc.get("folders") == 1, f"leave-info: two files, one folder ({bc})")
check(bc.get("wiki_pages") == 2 and bc.get("polls") == 1 and bc.get("bookmarks") == 1 and bc.get("videos") == 2, f"leave-info: pages, poll, bookmark, reviews ({bc})")
check("table" in (j.get("back_text") or "") and "folder" in j["back_text"], f"leave-info: the words ({j.get('back_text')})")
st = j.get("stays") or {}
check(st.get("tables") == 1, f"leave-info: the table made in Alpha stays, the brought ones do not count there ({st})")
check(st.get("files") == 1 and st.get("wiki_pages") == 1 and st.get("polls") == 1, f"leave-info: made in Alpha stays per area ({st})")
check(st.get("bookmarks") == 1, f"leave-info: the bookmark that cannot go stays ({st})")
check(j.get("kept") == 1, f"leave-info: one thing stays although brought in ({j.get('kept')})")
check(j.get("back") == ["Carols own"], f"leave-info: the projects by name as before ({j.get('back')})")
check(Bo.get(B + f"/api/orgs/{ORG}/leave-info", params={"uid": CAROL}).json().get("back_counts") == bc, "leave-info: the admin sees the same numbers")
check(Da.get(B + f"/api/orgs/{ORG}/leave-info", params={"uid": CAROL}).status_code == 403, "leave-info: another member may not look (403)")
# freelancer-matrix: orgadmin
FID, Fr = freelancer(B, A)
check(Fr.get(B + f"/api/orgs/{ORG}/leave-info").status_code == 404, "freelancer: no leave preview of somebody else's organisation (404)")

r = Ca.delete(B + f"/api/orgs/{ORG}/members/{CAROL}")
check(r.ok, f"carol leaves ({r.text[:160]})")
check(r.json().get("back") == 1 + 3 + 2 + 2 + 2 + 1 + 1, f"the answer counts everything that came back: project + 3 tables + 2 file tops + 2 pages + 2 reviews + poll + bookmark ({r.json()})")
for t, i, what in (("sheets", T1, "table"), ("sheets", T1B, "further sheet"), ("sheets", T3, "attached table"), ("sheets", T4, "table of an Alpha project"),
                   ("fs_nodes", DOC, "file"), ("fs_nodes", FOLD, "folder"), ("fs_nodes", INNER, "file in the folder"), ("wiki_pages", P1, "page"), ("wiki_pages", P2, "page 2"),
                   ("sched_polls", Q1, "poll"), ("bookmarks", M1, "bookmark"), ("video_reviews", V1, "review"), ("video_reviews", V2, "review at the project")):
    check(org_of(t, i) is None, f"{what} {i} is private again")
    check(brought(t, i) is None, f"{what} {i}: the mark is cleared")
for t, i, what in (("sheets", T2, "table made in Alpha"), ("sheets", T5, "table in the trash"), ("fs_nodes", THEIRS, "bob's file in the folder"), ("fs_nodes", MADE, "file made in Alpha"),
                   ("wiki_pages", PM, "page made in Alpha"), ("sched_polls", QM, "poll made in Alpha"), ("bookmarks", M2, "the bookmark saved twice")):
    check(org_of(t, i) == ORG, f"{what} stays in Alpha")
# the owner of the private things
check(sql("SELECT owner_id, list_id FROM sheets WHERE id=?", (T1,))[0] == (CAROL, None), "the table is carol's")
check(sql("SELECT owner_id FROM sheets WHERE id=?", (T1B,))[0][0] == CAROL, "the further sheet followed")
check(Da.get(B + f"/api/sheets/{T1}").status_code in (403, 404), "dave's share ended")
check(not sql("SELECT 1 FROM sheet_shares WHERE sheet_id=? AND revoked_at IS NULL", (T1,)), "no live share left")
check(sql("SELECT list_id FROM sheets WHERE id=?", (T3,))[0][0] == OWNL, "a project that went back keeps its table")
check(sql("SELECT list_id FROM sheets WHERE id=?", (T4,))[0][0] is None, "a project of Alpha lets go of the table")
Ca.patch(B + "/api/settings", json={"workspace": "private"})
check(Ca.get(B + f"/api/sheets/{T1}").ok, "carol opens her table")
rows = sql("SELECT name, parent_id, owner_id FROM fs_nodes WHERE id=?", (DOC,))[0]
check(rows[0] != "brief.txt" and rows[0].startswith("brief") and rows[1] is None and rows[2] == CAROL, f"a file name taken in the private space gets a suffix ({rows})")
d = Ca.get(B + f"/api/files/nodes/{INNER}/content")
check(d.ok and d.content == b"inside the folder", f"the file opens with the account key ({d.status_code})")
check(sql("SELECT parent_id FROM fs_nodes WHERE id=?", (THEIRS,))[0][0] is None, "bob's file moved to the top of Alpha")
d = Bo.get(B + f"/api/files/nodes/{THEIRS}/content")
check(d.ok and d.content == b"bob added this", "bob still opens it")
pp = sql("SELECT path, owner_id FROM wiki_pages WHERE id=?", (P2,))[0]
check(pp == ("Second (2)", CAROL), f"a page path taken gets (2) ({pp})")
g = Ca.get(B + f"/api/wiki/pages/{P1}")
check(g.ok and "[[Second (2)]]" in g.json().get("body", ""), f"the link follows the new path ({g.text[:200]})")
check(sql("SELECT list_id, client_id, task_id FROM video_reviews WHERE id=?", (V2,))[0] == (OWNL, None, None), "a review at a project that went back stays there")
inbox = sql("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1 AND org_id IS NULL", (CAROL,))[0][0]
check(sql("SELECT list_id FROM video_reviews WHERE id=?", (V1,))[0][0] == inbox, "a review of an Alpha project lands in the inbox")
acts = [json.loads(d) if isinstance(d, str) else d for (d,) in sql("SELECT detail FROM org_list_log WHERE org_id=? AND action='moveout'", (ORG,))]
kinds = sorted(a["kind"] for a in acts)
check(kinds == sorted(["list", "sheet", "file", "wiki", "video", "poll", "bookmark"]) and all(a.get("back") for a in acts), f"the log: one row per area ({kinds})")
mo = {x["data"].get("kind") for x in Bo.get(B + "/api/news").json()["items"] if x["kind"] == "orglist" and x["data"].get("action") == "moveout"}
check({"sheet", "file", "wiki"} <= mo, f"bob (admin) is told ({mo})")
check(sql("SELECT COUNT(*) FROM space_moves WHERE kind='sheet' AND obj_id=? AND to_org IS NULL", (T1,))[0][0] == 1, "the history of the table has the move")

# ================================================================ removed by an admin: News, locks, the way out clears the mark
T6 = in_sheet(Da, "Daves table")
sheet_in(Da, T6)
D1 = upload(Da, "dave.txt", b"daves words")
files_in(Da, [D1])
DP = page(Da, "Daves page", "text")
pages_in(Da, [DP])
# an admin takes the table out and it comes back through someone else: no mark left of dave
T7 = in_sheet(Da, "Moved out again")
sheet_in(Da, T7)
check(Bo.post(B + f"/api/sheets/{T7}/move-space", json={"to": "private"}).ok, "setup: bob takes a table out")
check(brought("sheets", T7) is None, "a way out clears the mark")
sql("INSERT INTO wiki_spaces(org_id, e2e) VALUES(?, 'on') ON CONFLICT (COALESCE(org_id, 0), COALESCE(owner_id, 0)) DO UPDATE SET e2e='on'", (ORG,), write=True)
j = Bo.get(B + f"/api/orgs/{ORG}/leave-info", params={"uid": DAVE}).json()
check((j.get("back_counts") or {}).get("wiki_pages") is None and j.get("kept") == 1, f"a space with the lock: the page stays, kept ({j.get('back_counts')}, {j.get('kept')})")
check((j.get("stays") or {}).get("wiki_pages") == 1, f"the page counts where it stays ({j.get('stays')})")
r = Bo.delete(B + f"/api/orgs/{ORG}/members/{DAVE}")
check(r.ok and r.json().get("back") == 2, f"bob removes dave: table and file back, the locked page stays ({r.text[:160]})")
sql("UPDATE wiki_spaces SET e2e=NULL WHERE org_id=?", (ORG,), write=True)
check(org_of("wiki_pages", DP) == ORG, "the page of the locked space stays in Alpha")
check(org_of("sheets", T6) is None and org_of("fs_nodes", D1) is None, "dave's table and file are private")
d = Da.get(B + f"/api/files/nodes/{D1}/content")
check(d.ok and d.content == b"daves words", "removed by an admin: the file opens with dave's key")
un = [x for x in Da.get(B + "/api/news").json()["items"] if x["kind"] == "unshare"]
check(un and un[0]["data"].get("back") == 2, f"dave's News counts it ({[x['data'] for x in un]})")

# ================================================================ the old data: from the last move, once
T8 = in_sheet(Er, "Old table")
sheet_in(Er, T8)
Q8 = poll(Er, "Old poll")
check(Er.post(B + f"/api/polls/{Q8}/move-space", json={"to": SP}).ok, "setup: poll in")
T9 = in_sheet(Er, "Made in Alpha, out, in by an admin", SP)
sql("UPDATE sheets SET brought_by=NULL WHERE id=?", (T8,), write=True)
sql("UPDATE sched_polls SET brought_by=NULL WHERE id=?", (Q8,), write=True)
sql("DELETE FROM settings WHERE key='migr_brought2365'", write=True)
subprocess.run(["docker", "restart", CT], capture_output=True)
for _ in range(120):
    try:
        if requests.get(B + "/api/health", timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(0.5)
check(brought("sheets", T8) == ERIN and brought("sched_polls", Q8) == ERIN, "the old data: the mark comes from the last move")
check(brought("sheets", T9) is None, "the old data: no move, no mark (never a guess from who made it)")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
