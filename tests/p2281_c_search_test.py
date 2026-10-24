#!/usr/bin/env python3
"""2.281.0 C (#3113) full-text search with stored vectors, own container (start.sh). freelancer-matrix: tasks
 - the side tables task_fts / cmt_fts with their GIN indexes exist, the expression indexes of 2.116 are gone
 - the same hits, order and place (title / notes / comment / field) as the ranking of 2.116 (computed here in SQL the old way)
 - visibility: the owner, a list guest, another organisation, a person without an organisation
 - the vectors follow: a new title / note / comment, a renamed title (the old word no longer), a deleted comment, a task gone
   for good (the row goes with it); a row missing in the side table is filled at the next start
 - custom fields (text, select, multiselect) are found as before
 - statements of /api/search do not grow with the number of lists (3 vs. 30 lists with hits and a field each)
usage: p2281_c_search_test.py <datadir>      (a fresh container; P2281C_NOSTART=1 = the server already runs)"""
import os
import re
import subprocess
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402
from kt import check, done, B, H, DATA  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
TIMING = re.compile(r'db;dur=[\d.]+;desc="n=(\d+)"')
# the ranking expression of 2.116 (tasks/ftsearch.py TASK_VEC / TITLE_VEC), to compare the stored vectors with
CAP = 100000


def _vec(col, w=None):
    v = f"to_tsvector('simple'::regconfig, kalmido_fold(left(COALESCE({col}, ''), {CAP})))"
    return f"setweight({v}, '{w}')" if w else v


OLD_TASK_VEC = f"{_vec('title', 'A')} || {_vec('content', 'B')}"
OLD_TITLE_VEC = _vec("title")


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall() if not write else c.execute(sql, args)
        if write:
            c.commit()
            return None
        return r
    finally:
        c.close()


def restart():
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=dict(os.environ, KEEP="1"))


def nstmt(r):
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    return int(m.group(1)) if m else -1


if not os.environ.get("P2281C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "fields"]})
ME = A.get(B + "/api/state").json()["me"]
ALICE, ORG = ME["id"], ME["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["carl"]})
check(r.ok, "setup: organisation Beta for carl " + r.text[:100])
dbx("DELETE FROM org_members WHERE org_id=? AND user_id=?", (ORG, uid["carl"]), write=True)
FID, Fr = freelancer(B, A)
Bo, Ca = login(B, "bob"), login(B, "carl")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})


def lst(s, name, **kw):
    r = s.post(B + "/api/lists", json={"name": name, **kw})
    assert r.ok, r.text
    return r.json()["id"]


def task(s, lid, title, **kw):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, **kw})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def comment(s, tid, body):
    r = s.post(B + f"/api/tasks/{tid}/comments", json={"body": body})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def search(s, q, **kw):
    r = s.get(B + "/api/search", params={"q": q, "limit": 50, **kw})
    return r


def hits(s, q):
    r = search(s, q)
    return [(h["task"]["id"], h["where"]) for h in r.json()["hits"]] if r.ok else r.status_code


# ---- the side tables
t = {r[0] for r in dbx("SELECT tablename FROM pg_tables WHERE tablename IN ('task_fts', 'cmt_fts')")}
check(t == {"task_fts", "cmt_fts"}, f"the side tables exist: {t}")
ix = {r[0] for r in dbx("SELECT indexname FROM pg_indexes WHERE indexname IN ('fts_tasks', 'fts_comments', "
                        "'ix2281_task_fts_vec', 'ix2281_cmt_fts_vec')")}
check(ix == {"ix2281_task_fts_vec", "ix2281_cmt_fts_vec"}, f"the GIN indexes of the side tables, not the expression ones: {ix}")

# ---- data: a shared list (bob a member), a private one, carl's and the freelancer's own
W = lst(A, "Work", org_id=ORG)
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob in Work")
P = lst(A, "Private", org_id=ORG)
CW = lst(Ca, "Carls")
FW = lst(Fr, "Frida")
T = {}
T["t1"] = task(A, W, "Zebra plan")
T["t2"] = task(A, W, "Zebra zebra zebra and more zebra")
T["n1"] = task(A, W, "Meeting", content="the zebra crossing near the office")
T["n2"] = task(A, P, "Groceries", content="zebra zebra stripes, zebra again")
T["c1"] = task(A, W, "Budget")
C1 = comment(A, T["c1"], "Bring the zebra numbers")
T["c2"] = task(A, W, "Hiring")
comment(A, T["c2"], "zebra")
comment(A, T["c2"], "zebra zebra twice")
T["both"] = task(A, W, "Zebra crossing", content="zebra notes as well")
T["carl"] = task(Ca, CW, "Zebra of carl")
T["frida"] = task(Fr, FW, "Zebra of frida", content="Ärger with the zebra")
FC = comment(Fr, T["frida"], "zebra comment of frida")


def old_order(lids):
    """title / notes hits of 2.116 for the lists lids, best first: [(id, where)]."""
    rows = dbx(f"""SELECT id, ts_rank({OLD_TASK_VEC}, q) AS r, ({OLD_TITLE_VEC} @@ q) AS it
                   FROM tasks, to_tsquery('simple'::regconfig, ?) q
                   WHERE ({OLD_TASK_VEC}) @@ q AND deleted_at IS NULL AND list_id = ANY(CAST(? AS BIGINT[]))
                   ORDER BY r DESC, id DESC""", ("'zebra':*", "{" + ",".join(map(str, lids)) + "}"))
    ti = [(r[0], "title") for r in rows if r[2]]
    no = [(r[0], "notes") for r in rows if not r[2]]
    return ti + no


h = hits(A, "zebra")
check(isinstance(h, list), f"search answers {h}")
h = h if isinstance(h, list) else []
tn = [x for x in h if x[1] in ("title", "notes")]
check(tn == old_order([W, P]), f"title / notes hits in the order of 2.116: {tn} vs {old_order([W, P])}")
cm = [x for x in h if x[1] == "comment"]
check({x[0] for x in cm} == {T["c1"], T["c2"]} and len(cm) == 2, f"one comment hit per task: {cm}")
check(h.index((T["c2"], "comment")) < h.index((T["c1"], "comment")), f"the better comment first: {cm}")
check(T["both"] in [x[0] for x in h if x[1] == "title"], "a task with the word in title and notes is a title hit")
check(T["carl"] not in [x[0] for x in h] and T["frida"] not in [x[0] for x in h], "other organisation / freelancer never")
j = search(A, "zebra").json()["hits"]
c1h = next((x for x in j if x["task"]["id"] == T["c1"]), {})
check(c1h.get("comment_id") == C1 and "zebra" in c1h.get("snippet", {}).get("text", "").lower(), f"comment id + snippet: {c1h}")

hb = hits(Bo, "zebra")
check(isinstance(hb, list) and [x for x in hb if x[1] in ("title", "notes")] == old_order([W]),
      f"list guest: the shared list only, same order: {hb}")
check(isinstance(hb, list) and T["n2"] not in [x[0] for x in hb], "list guest: not the private list")
hc = hits(Ca, "zebra")
check(hc == [(T["carl"], "title")], f"another organisation: only the own task {hc}")
hf = hits(Fr, "zebra")
check(isinstance(hf, list) and [x[0] for x in hf] == [T["frida"]], f"freelancer: the own task only {hf}")
check(hits(Fr, "arger") == [(T["frida"], "notes")], "freelancer: folded umlauts (Ärger / arger) in the notes")
check(hits(Fr, "frida") == [(T["frida"], "title")], "freelancer: the title")

# ---- the vectors follow the rows
check(A.patch(B + f"/api/tasks/{T['t1']}", json={"title": "Giraffe plan"}).ok, "setup: rename")
check(hits(A, "giraffe") == [(T["t1"], "title")], "a renamed title is found by its new word")
check(T["t1"] not in [x[0] for x in hits(A, "zebra")], "... and no longer by the old one")
check(A.patch(B + f"/api/tasks/{T['t1']}", json={"content": "okapi in the notes"}).ok, "setup: notes")
check(hits(A, "okapi") == [(T["t1"], "notes")], "changed notes are found")
CD = comment(A, T["t1"], "lemur talk")
check(hits(A, "lemur") == [(T["t1"], "comment")], "a new comment is found")
check(A.delete(B + f"/api/comments/{CD}").status_code in (200, 204), "setup: comment deleted")
check(hits(A, "lemur") == [], "a deleted comment is no hit")
GONE = task(A, W, "Wombat temporary")
comment(A, GONE, "wombat comment")
dbx("DELETE FROM tasks WHERE id=?", (GONE,), write=True)
check(dbx("SELECT count(*) FROM task_fts WHERE task_id=?", (GONE,))[0][0] == 0, "a task gone for good: its vector goes with it")
check(hits(A, "wombat") == [], "... and is no hit")

# ---- custom fields as before (text, select, multiselect; the weaker place "field")
F1 = A.post(B + f"/api/lists/{W}/fields", json={"name": "Ref", "type": "text"}).json()
F2 = A.post(B + f"/api/lists/{W}/fields", json={"name": "Kind", "type": "select",
                                                   "options": {"options": [{"name": "Quokka"}, {"name": "Other"}]}}).json()
F3 = A.post(B + f"/api/lists/{W}/fields", json={"name": "Tags", "type": "multiselect",
                                                   "options": {"options": [{"name": "Red"}, {"name": "Narwhal"}]}}).json()
check(all("id" in f for f in (F1, F2, F3)), f"setup: fields {F1} {F2} {F3}")
TF1, TF2, TF3 = task(A, W, "Field one"), task(A, W, "Field two"), task(A, W, "Field three")
o2 = {o["name"]: o["id"] for o in F2["options"]["options"]}
o3 = {o["name"]: o["id"] for o in F3["options"]["options"]}
check(A.patch(B + f"/api/tasks/{TF1}", json={"fields": {str(F1["id"]): "INV-quokka-7"}}).ok, "setup: text value")
check(A.patch(B + f"/api/tasks/{TF2}", json={"fields": {str(F2["id"]): o2["Quokka"]}}).ok, "setup: select value")
check(A.patch(B + f"/api/tasks/{TF3}", json={"fields": {str(F3["id"]): f"{o3['Red']},{o3['Narwhal']}"}}).ok, "setup: multiselect")
check(sorted(hits(A, "quokka")) == sorted([(TF1, "field"), (TF2, "field")]), f"text + select field values: {hits(A, 'quokka')}")
check(hits(A, "narwhal") == [(TF3, "field")], f"a multiselect option: {hits(A, 'narwhal')}")
check(hits(Ca, "quokka") == [], "fields of another organisation's list: never")
r = A.get(B + "/api/tasks", params={"scope": "search", "q": "quokka"})
check(r.ok and {x["id"] for x in r.json()["tasks"]} >= {TF1, TF2}, "the simple search finds the field values too")

# ---- a row missing in the side table is filled at the next start
dbx("DELETE FROM task_fts WHERE task_id=?", (T["n1"],), write=True)
dbx("DELETE FROM cmt_fts WHERE comment_id=?", (C1,), write=True)
restart()
A = login(B, "alice")
h2 = hits(A, "zebra")
check(isinstance(h2, list) and (T["n1"], "notes") in h2 and (T["c1"], "comment") in h2, f"filled again at the start: {h2}")

# ---- statements do not grow with the lists (before: list_role per list, one query per field)


def many(n, tag):
    for i in range(n):
        lid = lst(A, f"{tag} {i}", org_id=ORG)
        A.post(B + f"/api/lists/{lid}/fields", json={"name": "Code", "type": "text"})
        task(A, lid, f"Pangolin {tag} {i}", content="pangolin notes")


many(3, "few")
n3 = nstmt(search(A, "pangolin"))
check(len(hits(A, "pangolin")) == 3, "3 lists: 3 hits")
many(27, "more")
r30 = search(A, "pangolin")
n30 = nstmt(r30)
check(r30.ok and len(r30.json()["hits"]) == 30, "30 lists: 30 hits")
check(0 < n3 and n30 <= n3 + 5, f"statements of /api/search do not grow per list: {n3} (3 lists) vs. {n30} (30 lists)")

sys.exit(done("p2281_c_search"))
