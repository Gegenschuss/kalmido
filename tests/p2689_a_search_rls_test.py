#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.689.0 (#5116): the task search under row-level security (tasks carry org_id since 2.662.0, #4602).

ILIKE is not leakproof: under a policy Postgres may not use it as an index condition, so the trigram indexes tasks_trgm_* no
longer help in a person's context and a search that starts from "every task whose title matches" reads the whole table
(every organisation's rows, filtered by the policy one by one). The search now starts from the visible lists (index
tasks_list) and tests the text only on their tasks.
 1. seed: Alpha (alice) with a list of 2 000 tasks, Beta (carol) with 30 000 tasks; a few with the word "needle" in title /
    notes / link on both sides, a deleted one, a private one in alice's inbox
 2. the search finds exactly alice's matches (title, notes, link, private inbox), never Beta's and not the deleted one;
    a word with % and _ is taken literally
 3. the plans in alice's context (app role, row-level security): the shape before (one id set per field) and the search's
    own shape now - printed with their times for the record; the new one reads no task through a sequential scan
usage: p2689_a_search_rls_test.py <datadir>"""
import os
import re
import sys

import kt
from kt import B, DATA, check, dbx, sess
import dbx as dbxm

APP_ROLE = "kalmido_app"
NFOREIGN, NOWN = 30000, 2000


def as_app(stmts, role=None, orgs=None, uid=None):
    """Statements as the app's role with the given context -> (stdout lines, error text) - like p2662_a_rls_test.py."""
    dbc, dbn = dbxm._target(DATA)
    pre = [f"SET ROLE {APP_ROLE};"]
    for k, v in (("app.role", role), ("app.org_ids", orgs), ("app.user_id", uid)):
        if v is not None:
            pre.append(f"SET {k} = '{v}';")
    try:
        return dbxm._psql(dbc, dbn, "\n".join(pre + stmts) + "\n", timeout=120).strip().split("\n"), None
    except dbxm.DbError as e:
        return None, str(e)


kt.fresh()
A = kt.setup()
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
A.post(B + "/api/admin/orgs", json={"name": "Kalmido"})
r = A.post(B + "/api/users", json={"orgs": [1], "username": "carol", "display_name": "Carol", "password": "password123",
                                   "email": "carol@example.com"})
assert r.ok, r.text
CAROL = r.json()["id"]
kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, keep=True)
A, Ca = sess("alice"), sess("carol")
for s in (A, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ALPHA = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL})
assert r.status_code == 201, r.text
BETA = r.json()["id"]
check(A.delete(B + f"/api/orgs/{ALPHA}/members/{CAROL}").ok, "setup: carol leaves Alpha")

# ---- 1. seed
LA = A.post(B + "/api/lists", json={"name": "Alpha list", "org_id": ALPHA}).json()["id"]
LB = Ca.post(B + "/api/lists", json={"name": "Beta list", "org_id": BETA}).json()["id"]
INBOX = dbx("SELECT id FROM lists WHERE owner_id=1 AND is_inbox")[0][0]
for lid, n in ((LB, NFOREIGN), (LA, NOWN)):
    dbx(f"INSERT INTO tasks(list_id,title,content,created_at,updated_at) SELECT {lid}, 'filler task ' || g, "
        f"'some longer notes about task ' || g, '2026-01-01', '2026-01-01' FROM generate_series(1, {n}) g")
mine = {}
for k, body in (("title", {"title": "Alpha needle in the title"}), ("notes", {"title": "Alpha notes", "content": "a needle inside"}),
                ("url", {"title": "Alpha link", "url": "https://example.com/needle"}),
                ("lit", {"title": "Alpha 50%_needle literal"})):
    r = A.post(B + "/api/tasks", json={"list_id": LA, **body})
    assert r.ok, r.text
    mine[k] = r.json()["id"]
mine["inbox"] = A.post(B + "/api/tasks", json={"list_id": INBOX, "title": "private needle"}).json()["id"]
GONE = A.post(B + "/api/tasks", json={"list_id": LA, "title": "deleted needle"}).json()["id"]
check(A.delete(B + f"/api/tasks/{GONE}").ok, "setup: one needle task deleted")
FOREIGN = [Ca.post(B + "/api/tasks", json={"list_id": LB, "title": f"Beta needle {i}"}).json()["id"] for i in range(3)]
# 2.1123 (#5951): lists / list_members analysed too - with no statistics the planner guesses their rows from the row width,
# and the narrower time columns (TIMESTAMPTZ instead of TEXT) made it guess more visible lists than there are and pick a
# sequential scan of tasks; a real database has its statistics (autovacuum), the test now as well
dbx("ANALYZE tasks, lists, list_members")
orgs = {x[0]: x[1] for x in dbx("SELECT list_id, MIN(org_id) FROM tasks WHERE list_id IN (?,?) GROUP BY list_id", (LA, LB))}
check(orgs.get(LA) == ALPHA and orgs.get(LB) == BETA, f"setup: the seeded rows carry their list's organisation ({orgs})")


# ---- 2. the search's answer
def search(s, q):
    r = s.get(B + "/api/tasks", params={"scope": "search", "q": q, "limit": 200})
    assert r.ok, r.text[:300]
    return {t["id"] for t in r.json()["tasks"]}


got = search(A, "needle")
want = {mine[k] for k in ("title", "notes", "url", "lit", "inbox")}
check(got == want, f"alice finds her needles in title, notes, link and her private inbox ({sorted(got)} vs {sorted(want)})")
check(not (got & set(FOREIGN)) and GONE not in got, "... never Beta's, not the deleted one")
check(search(A, "50%_needle") == {mine["lit"]}, "% and _ are no wildcards")  # 2.981.0 (#5278): words of the shared index, punctuation ignored
check(search(A, "NEEDLE IN THE") == {mine["title"]}, "the search ignores case")
check(search(Ca, "needle") == set(FOREIGN), "carol finds only Beta's needles")
check(len(search(A, "filler task 19")) > 0, "a word of the seeded tasks in the visible list is found")

# ---- 3. the plans in alice's context
VIS = "(SELECT id FROM lists WHERE owner_id=1 UNION SELECT list_id FROM list_members WHERE user_id=1)"
Q = "'%needle%'"
SNIP = ("snippets IS NOT NULL AND EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(snippets)='array' "
        "THEN snippets ELSE '[]'::jsonb END) j WHERE (j->>'code') ILIKE {q} OR (j->>'path') ILIKE {q})").format(q=Q)
BEFORE = (f"SELECT id FROM tasks WHERE list_id IN {VIS} AND deleted_at IS NULL AND id IN (SELECT id FROM tasks WHERE title ILIKE {Q} "
          f"UNION SELECT id FROM tasks WHERE content ILIKE {Q} UNION SELECT id FROM tasks WHERE url ILIKE {Q} "
          f"UNION SELECT id FROM tasks WHERE {SNIP} UNION SELECT unnest(CAST('{{}}' AS BIGINT[]))) "
          "ORDER BY status, updated_at DESC LIMIT 200")
NOW = (f"SELECT id FROM tasks WHERE list_id IN {VIS} AND deleted_at IS NULL AND (title ILIKE {Q} OR content ILIKE {Q} "
       f"OR url ILIKE {Q} OR ({SNIP}) OR id = ANY(CAST('{{}}' AS BIGINT[]))) ORDER BY status, updated_at DESC LIMIT 200")


def plan(sql, ctx):
    out, e = as_app([f"EXPLAIN (ANALYZE, COSTS OFF) {sql};"], **ctx)
    check(e is None, f"EXPLAIN runs ({(e or '')[:200]})")
    return [x for x in (out or []) if x.strip() and x.strip() not in ("SET", "QUERY PLAN") and not set(x.strip()) <= {"-"}]


def ms(lines):
    m = [float(x) for ln in lines for x in re.findall(r"Execution Time: ([0-9.]+) ms", ln)]
    return m[-1] if m else -1.0


CTX = {"role": "user", "orgs": str(ALPHA), "uid": 1}
pb, pn = plan(BEFORE, CTX), plan(NOW, CTX)
print(f"info: #5116 plan before ({ms(pb):.1f} ms, {NFOREIGN + NOWN} tasks, row-level security):\n  " + "\n  ".join(pb))
print(f"info: #5116 plan now ({ms(pn):.1f} ms):\n  " + "\n  ".join(pn))
ps = plan(BEFORE, {"role": "system"})
print(f"info: #5116 plan before as system ({ms(ps):.1f} ms; the policy is still there, ILIKE still not an index condition):\n  "
      + "\n  ".join(ps))
check(not any("Seq Scan on tasks" in x for x in pn), "the search's plan reads no task through a sequential scan")
check(any("tasks_list" in x or "tasks_done" in x for x in pn), "... it starts from the visible lists' index")
# the app's own statement has the new shape (the plans above are of a copy; the API checks of 2. run the app's)
SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kalmido", "core", "state.py"), encoding="utf-8").read()
body = SRC[SRC.index("def search_tasks("):]
body = body[:body.index("\n@app.")]
# 2.981.0 (#5278): the text through the shared search index obj_search (no ILIKE on tasks any more), still on the visible lists
check("SELECT id FROM tasks WHERE title ILIKE" not in body and "title ILIKE ?" not in body and 'osr_ids_sql("task"' in body
      and "vis_search_lids(c, uid)" in body, "search_tasks tests the text on the visible lists' tasks through obj_search")

sys.exit(kt.done("p2689_a_search_rls"))
