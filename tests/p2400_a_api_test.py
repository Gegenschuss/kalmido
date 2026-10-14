#!/usr/bin/env python3
"""2.40.0 API tests (agent A): #1432 "Load more" instead of loading everything.
 - GET /api/agents/jobs?limit=&before=: the first page brings every running / waiting job plus the newest ended ones, the
   following pages (cursor next = change time + id) neither repeat nor skip a job with the same change time; every page
   holds only jobs the person may see (job_visible); state=open has no next; ?id= still returns one job; without limit /
   before the answer is the old one (no next)
 - GET /api/tasks?scope=done|trash&limit=100&before=: pages of 100 without doubles / gaps (equal completion / deletion
   times), the first trash page counts the whole trash (deletable / kept); DELETE /api/trash empties all of it
 - GET /api/news?limit=&before=: pages of read items, every unread item on the first page; unread / unread_me, filter=me
   and "mark all as read" cover the whole feed
tenant-matrix: org
usage: p2400_a_api_test.py <datadir>"""
import os
import dbx as dbxm
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args)
        r = r.fetchall() if not write else None
        if write:
            c.commit()
        return r
    finally:
        c.close()


def pages(s, url, first, more, key):
    """Follows next; returns ([ids per page], [answers])."""
    out, ans, nxt = [], [], None
    for _ in range(60):
        r = s.get(B + url, params={"limit": more if nxt else first, **({"before": nxt} if nxt else {})})
        assert r.ok, r.text
        j = r.json()
        ans.append(j)
        out.append([x["id"] for x in j[key]])
        nxt = j.get("next")
        if not nxt:
            break
    return out, ans


subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"}).json()["id"]
Bo = sess("bob")
Bo.patch(B + "/api/settings", json={"lang": "en"})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
CL = r.json()["id"]

# ================================================================== jobs
# 3 open jobs of Bob with OLD change times, 80 ended jobs in four equal change times; the even ones are Bob's, the odd ones Alice's
for i in range(3):
    dbx("INSERT INTO agent_jobs (agent_id, user_id, title, state, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (CL, BOB, f"Open job {i}", "running" if i else "waiting", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"), write=True)
for i in range(80):
    dbx("INSERT INTO agent_jobs (agent_id, user_id, title, state, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (CL, BOB if i % 2 == 0 else ALICE, f"Ended job {i}", "done", "2026-02-01T00:00:00Z", f"2026-02-0{2 + i % 4}T08:00:00Z"), write=True)
rows = dbx("SELECT id, state, user_id, updated_at FROM agent_jobs ORDER BY updated_at DESC, id DESC")
OPEN_B = {x[0] for x in rows if x[1] in ("running", "waiting")}
ENDED_B = [x[0] for x in rows if x[1] == "done" and x[2] == BOB]
check(len(OPEN_B) == 3 and len(ENDED_B) == 40, "setup: 3 open, 40 ended jobs of Bob")

old = Bo.get(B + "/api/agents/jobs").json()
check("next" not in old and len(old["jobs"]) == 43, "#1432: without limit the old answer (all 43 visible jobs, no next) " + str(len(old["jobs"])))
pg, ans = pages(Bo, "/api/agents/jobs", 20, 7, "jobs")
first = pg[0]
check(set(first[:3]) == OPEN_B and len(first) == 23, "#1432: the first page: the 3 open jobs on top + 20 ended " + str(first[:5]))
flat = [i for p in pg for i in p]
check(len(flat) == len(set(flat)), "#1432: no job twice across the pages")
check([i for i in flat if i not in OPEN_B] == ENDED_B, "#1432: the ended jobs complete and in order (equal change times: no gap)")
check(all(len(p) <= 7 for p in pg[1:]) and len(pg) == 4, "#1432: later pages hold at most limit jobs " + str([len(p) for p in pg]))
check(all(j["user_id"] == BOB for a in ans for j in a["jobs"]), "#1432: every page only Bob's jobs (job_visible per page)")
check(ans[-1]["next"] is None, "#1432: the last page has next = null")
pa, _ = pages(A, "/api/agents/jobs", 20, 50, "jobs")
fa = [i for p in pa for i in p]
check(len(fa) == len(set(fa)) and {x[0] for x in rows if x[2] == ALICE} <= set(fa), "#1432: Alice pages through her own jobs too")
r = Bo.get(B + "/api/agents/jobs", params={"limit": 5, "state": "open"}).json()
check({j["id"] for j in r["jobs"]} == OPEN_B and r["next"] is None, "#1432: state=open: every open job, no next")
check(Bo.get(B + "/api/agents/jobs", params={"limit": 5, "before": "nonsense"}).status_code == 400, "#1432: a broken cursor 400")
r = Bo.get(B + "/api/agents/jobs", params={"limit": 5, "before": ans[0]["next"]}).json()
check(not (set(j["id"] for j in r["jobs"]) & OPEN_B), "#1432: a page with before has no open jobs (they came with the first)")
check([j["id"] for j in Bo.get(B + "/api/agents/jobs", params={"id": ENDED_B[-1]}).json()["jobs"]] == [ENDED_B[-1]], "#1432: ?id= one job")
alice_job = next(x[0] for x in rows if x[2] == ALICE)
check(Bo.get(B + "/api/agents/jobs", params={"id": alice_job}).json()["jobs"] == [], "#1432: ?id= of a job not mine: empty")

# ================================================================== completed / trash
INBOX = dbx("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1", (BOB,))[0][0]
SHL = A.post(B + "/api/lists", json={"name": "Shared desk", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{SHL}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: Bob edits Alice's list")
ids = [Bo.post(B + "/api/tasks", json={"title": f"Errand {i}", "list_id": INBOX}).json()["id"] for i in range(250)]
shared = [Bo.post(B + "/api/tasks", json={"title": f"Desk {i}", "list_id": SHL}).json()["id"] for i in range(3)]
done, trash = ids[:130], ids[130:]
for k, t in enumerate(done):
    dbx("UPDATE tasks SET status=1, completed_at=? WHERE id=?", (f"2026-03-0{1 + k % 3}T10:00:00Z" if k else None, t), write=True)
for t in trash + shared:
    dbx("UPDATE tasks SET deleted_at=? WHERE id=?", ("2026-03-05T10:00:00Z", t), write=True)
pd, ad = pages(Bo, "/api/tasks?scope=done", 100, 100, "tasks")
full = [t["id"] for t in Bo.get(B + "/api/tasks", params={"scope": "done", "limit": 2000}).json()["tasks"]]
check([len(p) for p in pd] == [100, 30], "#1432: completed in pages of 100 " + str([len(p) for p in pd]))
check([i for p in pd for i in p] == full and set(full) == set(done), "#1432: completed: no doubles / gaps, also with no completion time")
pt, at = pages(Bo, "/api/tasks?scope=trash", 100, 100, "tasks")
check([len(p) for p in pt] == [100, 23] and len({i for p in pt for i in p}) == 123, "#1432: trash in pages of 100 (equal deletion times) " + str([len(p) for p in pt]))
check(at[0].get("deletable") == 120 and at[0].get("kept") == 3, "#1432: the first trash page counts the whole trash " + str({k: at[0].get(k) for k in ("deletable", "kept")}))
check(Bo.get(B + "/api/tasks", params={"scope": "done", "limit": 50, "before": "x|y"}).status_code == 400, "#1432: a broken cursor 400")
r = Bo.delete(B + "/api/trash").json()
check(r.get("deleted") == 120 and r.get("kept") == 3, "#1432: Empty deletes the whole trash, not only the loaded page " + str(r))
check(len(Bo.get(B + "/api/tasks", params={"scope": "trash", "limit": 100}).json()["tasks"]) == 3, "#1432: only the kept ones stay")

# ================================================================== news
Bo.patch(B + "/api/settings", json={"features": "comments,collab"})
for i in range(140):  # every 7th unread; assignments (for me) and status changes of the inbox
    dbx("INSERT INTO notifications (user_id, kind, task_id, actor_id, created_at, read_at) VALUES (?,?,?,?,?,?)",
        (BOB, "assign" if i % 2 else "complete", done[1 + i % 50], ALICE, "2026-04-01T10:00:00Z", None if i % 7 == 0 else "2026-04-02T10:00:00Z"), write=True)
fulln = Bo.get(B + "/api/news").json()
U = fulln["unread"]
check(len(fulln["items"]) > 100 and U >= 15, f"setup: a long feed ({len(fulln['items'])} items, {U} unread)")
pn, an = pages(Bo, "/api/news", 50, 50, "items")
flat = [i for p in pn for i in p]
check(len(flat) == len(set(flat)) and set(flat) == {x["id"] for x in fulln["items"]}, "#1432: news pages: no doubles / gaps")
check(sum(1 for x in an[0]["items"] if x["read"]) == 50 and sum(1 for x in an[0]["items"] if not x["read"]) == sum(1 for x in fulln["items"] if not x["read"]),
      "#1432: the first page: 50 read + every unread item")
check(all(x["read"] for a in an[1:] for x in a["items"]), "#1432: later pages only read items")
check(all(a["unread"] == U and a["unread_me"] == fulln["unread_me"] for a in an), "#1432: unread / unread_me count the whole feed on every page")
two = Bo.get(B + "/api/news", params={"limit": 100}).json()
check({x["id"] for x in two["items"]} == set(pn[0] + pn[1]) and two["next"] == an[1]["next"], "#1432: limit = all loaded brings back exactly what was shown")
fm = {x["id"] for x in Bo.get(B + "/api/news", params={"filter": "me"}).json()["items"]}
pm, _ = pages(Bo, "/api/news?filter=me", 20, 20, "items")
check({i for p in pm for i in p} == fm and len(pm) > 1, "#1432: filter=me pages through the whole filtered feed")
r = Bo.post(B + "/api/news/read", json={"all": True}).json()
check(r.get("unread") == 0 and len(r.get("marked") or []) >= U, "#1432: mark all as read covers the whole feed " + str(r.get("unread")))
check(dbx("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL", (BOB,))[0][0] == 0, "#1432: ... also the rows never loaded")

print(f"{OKS[0]} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
