#!/usr/bin/env python3
"""2.116.0 API tests (part B: #2065 full-text search on the server), own container (start.sh).
 - GET /api/search: ranked hits over tasks (title before notes) and their comments (the task with the comment's snippet),
   custom fields as weaker hits; case, accents and ä / ae do not matter, words match their beginnings (typing), completed
   tasks are found (status), the trash never; one hit per task; the snippet is plain text with marks; limit + cursor; 400
 - the index: the GIN expression indexes exist; a note of 190 000 characters is saved (the index reads a capped part)
 - visibility: another person's private list, another organisation, a participant only their own tasks (not the comment of
   a task not assigned to them), a shared list yes, a list with the lock (e2e) never (the browser searches it)
 - GET /api/v1/search?fulltext=1: the same hits as tasks with match {where, snippet}; an agent token only the lists shared
   with it; a person without an organisation (freelancer-matrix: tasks) finds the own and nothing of others
usage: p2116_b_api_test.py <datadir>      (a fresh container; P2116B_NOSTART=1 = the server already runs)"""
import os
import dbx as dbxm
import subprocess
import sys
import time

import requests

from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def restart():
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL,
                   env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces"))


if not os.environ.get("P2116B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "fields"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [1], "username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    uid[u] = r.json()["id"]
BOB, CAROL, DAVE = uid["bob"], uid["carol"], uid["dave"]
restart()
A, Bo, Ca, Da = sess("alice"), sess("bob"), sess("carol"), sess("dave")
for s in (Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en"})
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
BETA = r.json().get("id") if r.ok else None
dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG, CAROL), write=True)
check(BETA is not None, "setup: organisation Beta for carol " + r.text[:100])

r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "claude", "display_name": "Claude"})
CL, CLH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
check(A.patch(B + f"/api/admin/agents/{CL}", json={"org_id": ORG}).ok, "setup: a team agent of the organisation")
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (ORG, CL), write=True)

W = A.post(B + "/api/lists", json={"name": "Work", "org_id": ORG}).json()["id"]
for who in (CL, BOB):
    check(A.put(B + f"/api/lists/{W}/members", json={"user_id": who, "role": "edit"}).ok, f"setup: {who} in the list")
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": DAVE, "role": "participant"}).ok, "setup: dave a participant")
PRIV = A.post(B + "/api/lists", json={"name": "Private", "org_id": ORG}).json()["id"]
LE = A.post(B + "/api/lists", json={"name": "Locked", "org_id": ORG}).json()["id"]


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    check(r.status_code in (200, 201), "setup: task " + r.text[:100])
    return r.json().get("id")


def comment(s, tid, body):
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": body})
    check(r.status_code in (200, 201), "setup: comment " + r.text[:100])
    return r.json().get("id")


def find(s, q, **kw):
    r = s.get(B + "/api/search", params={"q": q, **kw})
    return r.json().get("hits", []) if r.ok else r.status_code


def ids(hits):
    return [h["task"]["id"] for h in hits] if isinstance(hits, list) else hits


# ---- the index
names = {r[0] for r in dbx("SELECT indexname FROM pg_indexes WHERE indexname IN ('fts_tasks', 'fts_comments')")}
check(names == {"fts_tasks", "fts_comments"}, f"the two GIN indexes exist: {names}")

# ---- ranking: title before notes, the comment hit with its snippet
T_TITLE = task(A, W, "Projektplan Kickoff")
T_NOTE = task(A, W, "Meeting notes", content="We still need the **projektplan** for the client")
T_CMT = task(A, W, "Budget review")
C1 = comment(A, T_CMT, "Please attach the projektplan before Friday")
h = find(A, "projektplan")
check(ids(h)[:3] == [T_TITLE, T_NOTE, T_CMT], f"title, then notes, then comment: {ids(h)} vs {[T_TITLE, T_NOTE, T_CMT]}")
by = {x["task"]["id"]: x for x in h} if isinstance(h, list) else {}
check(by.get(T_TITLE, {}).get("where") == "title" and by.get(T_NOTE, {}).get("where") == "notes"
      and by.get(T_CMT, {}).get("where") == "comment" and by.get(T_CMT, {}).get("comment_id") == C1,
      "where = title / notes / comment (+ comment_id) " + str([(x["task"]["id"], x["where"]) for x in h])[:200])
sn = by.get(T_CMT, {}).get("snippet") or {}
check(sn.get("text", "").startswith("Please attach") and sn.get("marks") and
      sn["text"][sn["marks"][0][0]:sn["marks"][0][1]].lower() == "projektplan", "the comment's snippet with the mark " + str(sn))
sn = by.get(T_NOTE, {}).get("snippet") or {}
check("**" not in sn.get("text", "") and "<" not in sn.get("text", "x<"), "the notes' snippet is plain text (Markdown out) " + str(sn))
check(len(ids(h)) == len(set(ids(h))), "one hit per task")
check(set(by.get(T_TITLE, {}).get("task", {})) >= {"id", "title", "list_id", "status"}, "the task in brief: id, title, list_id, status")

# ---- umlauts, ß, accents, prefix, several words
T_UML = task(A, W, "Ärger mit der Straße im Café")
for q in ("ärger", "arger", "AERGER", "ärg", "strasse", "STRASSE", "cafe", "ärger straße"):
    check(T_UML in ids(find(A, q)), f"umlaut / prefix variant {q!r} finds the task")
check(T_UML not in ids(find(A, "ärger drucker")), "every word must match (AND)")
check(T_TITLE in ids(find(A, "proj")), "a word's beginning (typing) finds it")
check(T_TITLE not in ids(find(A, "plan")), "the middle of a word is no hit (word beginnings, as the message search)")

# ---- completed yes (status), trash no, custom field (weaker)
T_DONE = task(A, W, "Pelikan old task")
check(A.post(B + f"/api/tasks/{T_DONE}/complete").ok, "setup: completed")
h = find(A, "pelikan")
check(ids(h) == [T_DONE] and h[0]["task"]["status"] != 0, "a completed task is found and marked (status) " + str(h)[:200])
T_DEL = task(A, W, "Flamingo in the trash")
comment(A, T_DEL, "flamingo comment")
check(A.delete(B + f"/api/tasks/{T_DEL}").ok, "setup: to the trash")
check(find(A, "flamingo") == [], "the trash is never found (title nor comment)")
T_CD = task(A, W, "Another one")
CD = comment(A, T_CD, "Kakadu talk")
check(A.delete(B + f"/api/comments/{CD}").status_code in (200, 204), "setup: comment deleted")
check(find(A, "kakadu") == [], "a deleted comment is no hit")

# ---- long notes: saved without an error (the index reads a capped part)
big = " ".join(f"w{i}x" for i in range(25000))
r = A.post(B + "/api/tasks", json={"title": "Big note", "list_id": W, "content": big[:190000]})
check(r.status_code in (200, 201), "a note of 190 000 characters is saved " + r.text[:120])
check(r.json().get("id") in ids(find(A, "w12x")), "a word early in the long note is found")

# ---- visibility
TP = task(A, PRIV, "Kolibri private")
TS = task(A, W, "Shared task")
comment(A, TS, "Kolibri shared")
TD = task(A, W, "Dave's task", assignee_id=DAVE)
comment(A, TD, "Kolibri for dave")
LB = Ca.post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json().get("id")
TB = task(Ca, LB, "Kolibri beta")
TL = task(A, LE, "Kolibri locked")
comment(A, TL, "Kolibri locked comment")
dbx("UPDATE lists SET e2e='test' WHERE id=?", (LE,), write=True)  # the lock: the server holds ciphertexts only
check(set(ids(find(A, "kolibri"))) == {TP, TS, TD}, f"alice: own private + shared, not Beta, not the locked list: {ids(find(A, 'kolibri'))}")
check(set(ids(find(Bo, "kolibri"))) == {TS, TD}, f"bob (member): the shared list only, not alice's private list: {ids(find(Bo, 'kolibri'))}")
check(ids(find(Da, "kolibri")) == [TD], f"dave (participant): only his own task, not the comment of another task: {ids(find(Da, 'kolibri'))}")
check(ids(find(Ca, "kolibri")) == [TB], f"carol (other organisation): only her own: {ids(find(Ca, 'kolibri'))}")
check(T_TITLE not in ids(find(Ca, "projektplan")), "the other organisation finds nothing of this one")
check(TL not in ids(find(A, "locked")), "a locked list never (browser-only search)")

# ---- paging, input
for i in range(3):
    task(A, W, f"Seriennummer {i}")
r = A.get(B + "/api/search", params={"q": "seriennummer", "limit": 2}).json()
check(len(r.get("hits", [])) == 2 and r.get("next"), "limit 2 + next " + str(r)[:120])
r2 = A.get(B + "/api/search", params={"q": "seriennummer", "limit": 2, "cursor": r.get("next")}).json()
check(len(r2.get("hits", [])) == 1 and r2.get("next") is None and not set(ids(r2["hits"])) & set(ids(r["hits"])), "the second page " + str(r2)[:120])
for bad in ({"q": ""}, {"q": "x" * 201}, {"q": "ab", "limit": 0}, {"q": "ab", "limit": 51}, {"q": "ab", "cursor": "zz"}):
    check(A.get(B + "/api/search", params=bad).status_code == 400, "400: " + str(bad)[:40])
check(find(A, "%%% ___") == [], "only punctuation: no hits, no error")
check(Da.get(B + "/api/search", params={"q": "ab"}).ok and requests.get(B + "/api/search", params={"q": "ab"}, headers=H).status_code in (401, 403),
      "signed in only")
t0 = time.time()
find(A, "projektplan")
check(time.time() - t0 < 2.0, f"a query answers quickly ({time.time() - t0:.2f} s)")

# ---- API v1: fulltext=1, an agent only the shared lists
r = requests.get(V + "/search", params={"q": "kolibri", "fulltext": "1"}, headers=CLH)
d = r.json().get("data", []) if r.ok else []
check(r.ok and {x["id"] for x in d} == {TS, TD}, f"agent: only the shared list's tasks {r.status_code} {[x.get('id') for x in d]}")
check(all(x.get("match", {}).get("where") == "comment" for x in d), "v1: match.where = comment")
r = requests.get(V + "/search", params={"q": "projektplan", "fulltext": "1", "limit": 500}, headers=CLH)
check(r.ok and [x["id"] for x in r.json()["data"]][:3] == [T_TITLE, T_NOTE, T_CMT], "v1: the same order (a big limit becomes 50) " + r.text[:150])
check(requests.get(V + "/search", params={"q": "kolibri", "fulltext": "x"}, headers=CLH).status_code == 400, "v1: fulltext 0 / 1 only")
check(requests.get(V + "/search", params={"q": "kolibri"}, headers=CLH).ok, "v1: the old search stays")
spec = requests.get(V + "/openapi.json").json()
check(any(p.get("name") == "fulltext" for p in spec["paths"]["/search"]["get"].get("parameters", [])), "OpenAPI: the fulltext parameter")

# ---- a person without an organisation (freelancer-matrix: tasks)
FID, Fr = freelancer(B, A)
FL = Fr.post(B + "/api/lists", json={"name": "My clients"}).json()["id"]
FT = task(Fr, FL, "Angebot Kolibri GmbH")
FT2 = task(Fr, FL, "Follow up")
FC = comment(Fr, FT2, "Rechnung an Kolibri senden")
h = find(Fr, "kolibri")
check(set(ids(h)) == {FT, FT2} and ids(h)[0] == FT, f"freelancer: own title hit first, then the comment hit {ids(h)}")
check(any(x.get("comment_id") == FC for x in h if isinstance(x, dict)), "freelancer: the comment hit names its comment")
check(not set(ids(find(A, "angebot"))) & {FT}, "alice (instance admin) never finds the freelancer's private task")
check(find(Fr, "projektplan") == [], "the freelancer finds nothing of the organisation")

print(f"p2116_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
