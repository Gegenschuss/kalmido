#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.369.2 (#3136): the start state (GET /api/state) of a big account, measured like Audit Q (24.10.2026, 50 people,
200 organisation lists, 20.600 tasks; baseline 20,5 MB / 2,8-3,9 s / 5.244 statements). Own container (start.sh).
Invented people and texts only.
freelancer-matrix: lists, tasks
 - an organisation member (bob) sees 200 organisation lists with 103 tasks each (filled by SQL); a person without an
   organisation (frida) has 50 own lists with 200 tasks each
 - PERF lines: bytes, gzip bytes, time (3 calls), statements (Server-Timing n=) of /api/state for both, without and with lz=1
 - without lz=1 (older clients, agents) the whole state as before
 - lz=1 (the start set): every task Today / Next 7 days / Pinned / Waiting / My tasks need is in it (with its parents and
   subtasks), the basket and the lists named in lzl whole; lz.pending = the other visible lists, lz.counts = their open
   top-level tasks and tags exactly as the whole state counts them; lzl=all = the whole state; a small account (below
   KALMIDO_STATE_LAZY_MIN) gets the whole state with lz=1 too
 - GET /api/state/lists?ids= (one list, several, all) = those lists' tasks exactly as in the whole state (same serialization);
   someone of another organisation gets nothing of them
 - GET /api/state/delta?lz=1 after a change in a list not loaded: lzc carries that list's new count
usage: p3136_state_size_test.py <datadir>   (P3136_NOSTART=1 / KMT_NOSTART=1: the container runs already)"""
import gzip
import json
import os
import re
import sys
import time

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

TIMING = re.compile(r'db;dur=([\d.]+);desc="n=(\d+)"')
# budget (#3136, decision 28.10.2026): above 2 MB or 1 s the start state has to be split
BUDGET_BYTES = int(os.environ.get("P3136_BUDGET_BYTES", "2000000"))  # 0 = only measure; 2.575.0 (#3966): 2 MB set (td=1, 1,94 MB on 06.11.2026)


def measure(s, who, n=3):
    out = []
    for _ in range(n):
        t = time.monotonic()
        r = s.get(B + "/api/state")
        dt = time.monotonic() - t
        m = TIMING.search(r.headers.get("Server-Timing", ""))
        out.append((r, dt, float(m.group(1)) if m else -1, int(m.group(2)) if m else -1))
    r = out[-1][0]
    raw = len(r.content)
    gz = len(gzip.compress(r.content, 6))
    times = ", ".join(f"{x[1]:.2f}" for x in out)
    print(f"PERF {who} /api/state: {raw / 1e6:.2f} MB, gzip {gz / 1e6:.2f} MB, {times} s, db {out[-1][2]:.0f} ms, "
          f"{out[-1][3]} statements, {len(r.json().get('tasks', []))} tasks", flush=True)
    return r, raw, min(x[1] for x in out)


if not kt.nostart("P3136"):
    kt.fresh()
A = kt.setup()
oid = A.post(B + "/api/admin/orgs", json={"name": "Messung GmbH"}).json()["id"]
uid = {}
for u in ("bob", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [oid], "username": u, "display_name": u.title(), "password": kt.PASSWORD,
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
Bo = sess("bob")
for s in (A, Bo):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "workspace": f"org:{oid}"}).ok
aid = A.get(B + "/api/state").json()["me"]["id"]

# 200 organisation lists of alice, everyone in the organisation sees them
lids = []
for i in range(200):
    r = A.post(B + "/api/lists", json={"name": f"Projekt {i + 1:03d}", "kind": "project", "org_id": oid,
                                       "folder": f"Bereich {i % 8 + 1}"})
    assert r.ok, r.text
    lids.append(r.json()["id"])
kt.dbx(f"UPDATE lists SET org_visibility='org', org_edit=1 WHERE id IN ({','.join(map(str, lids))})")
WORDS = "ARRAY['Angebot','Kunde','Termin','Entwurf','Rechnung','Abstimmung','Freigabe','Bericht','Planung','Pruefung']"


def fill(list_ids, per, users, tag_uid):
    ids = ",".join(map(str, list_ids))
    us = ",".join(map(str, users))
    kt.dbx(f"INSERT INTO sections (list_id, name, sort) SELECT l, n, k FROM unnest(ARRAY[{ids}]) l, "
           "unnest(ARRAY['Offen','In Arbeit','Fertig']) WITH ORDINALITY AS x(n, k)")
    # 2.1112.2 (#5184): created_at / updated_at are TIMESTAMPTZ since #5306 - a point in time (whole seconds, as the app
    # writes them), not to_char text; 2.1154.0 (#5184, CI red p3136_state_size): completed_at is TIMESTAMPTZ as well now
    # (schema.py tasks) - the to_char text crashed the seed again
    # like Audit Q's generator: 60 % with a note (0-60 words), 45 % due (-60..90 days), 20 % done (half of them within
    # the 14 days the start state keeps), priorities 0/0/0/1/3/5, a section each
    kt.dbx(f"""INSERT INTO tasks (list_id, section_id, title, content, priority, status, due, due_time, reminders, sort,
               created_at, updated_at, completed_at, created_by, assignee_id)
        SELECT l, (SELECT id FROM sections s WHERE s.list_id=l ORDER BY id OFFSET (j % 3) LIMIT 1),
          (SELECT string_agg(({WORDS})[1 + (j * 7 + w * 3 + l) % 10], ' ') FROM generate_series(1, 2 + (j % 6)) w) || ' #' || j,
          CASE WHEN (j * 13 + l) % 10 < 6 THEN (SELECT COALESCE(string_agg(({WORDS})[1 + (j + w * 11) % 10], ' '), '')
                                                FROM generate_series(1, (j * 17 + l) % 61) w) ELSE '' END,
          (ARRAY[0,0,0,1,3,5])[1 + (j + l) % 6], CASE WHEN (j * 7 + l) % 5 = 0 THEN 2 ELSE 0 END,
          CASE WHEN (j * 3 + l) % 20 < 9 THEN to_char(current_date + ((j * 37 + l) % 151) - 60, 'YYYY-MM-DD') END,
          CASE WHEN (j * 3 + l) % 20 < 3 THEN lpad((7 + j % 12)::text, 2, '0') || ':00' END,
          CASE WHEN (j * 3 + l) % 20 < 4 THEN '0,15' ELSE '' END, j,
          date_trunc('second', now() - interval '40 days'), date_trunc('second', now() - interval '20 days'),
          CASE WHEN (j * 7 + l) % 5 = 0 THEN date_trunc('second', now() - ((j % 28) || ' days')::interval) END,
          (ARRAY[{us}])[1 + j % {len(users)}], CASE WHEN j % 4 = 0 THEN (ARRAY[{us}])[1 + (j / 4) % {len(users)}] END
        FROM unnest(ARRAY[{ids}]) l, generate_series(1, {per}) j""")
    # 2.955.0 (#5276): personal tags are rows of the core (obj_tags scope user, obj_tag_links)
    kt.dbx(f"""INSERT INTO obj_tags (scope_kind, scope_id, name) SELECT 'user', '{int(tag_uid)}', x FROM unnest(ARRAY['kunde','intern','dringend']) x
        ON CONFLICT DO NOTHING""")
    kt.dbx(f"""INSERT INTO obj_tag_links (tag_id, kind, obj_id) SELECT ot.id, 'task', t.id FROM tasks t
        JOIN obj_tags ot ON ot.scope_kind='user' AND ot.scope_id='{int(tag_uid)}' AND ot.name=(ARRAY['kunde','intern','dringend'])[1 + t.id % 3]
        WHERE t.list_id IN ({ids}) AND t.id % 5 < 2 ON CONFLICT DO NOTHING""")


fill(lids, 103, [aid, uid["bob"], uid["dave"]], uid["bob"])
kt.dbx(f"UPDATE tasks SET pinned=true WHERE list_id={lids[5]} AND id % 50 = 0")
kt.dbx(f"UPDATE tasks SET waiting_at='2026-01-01T10:00:00' WHERE list_id={lids[6]} AND id % 40 = 0")
# subtasks (an undated subtask of a task due soon must come along, a due subtask brings its parent)
kt.dbx(f"""UPDATE tasks t SET parent_id=p.id FROM tasks p WHERE t.list_id={lids[7]} AND p.list_id={lids[7]} AND p.id = t.id - 1
           AND t.id % 7 = 0""")
n_open = kt.dbx(f"SELECT COUNT(*) FROM tasks WHERE status=0 AND list_id IN ({','.join(map(str, lids))})")[0][0]
check(n_open > 16000, f"setup: {n_open} open organisation tasks")

r, raw, best = measure(Bo, "bob (organisation, 200 lists, 20.600 tasks)")
check(r.ok, "bob: /api/state answers")
st = r.json()
check(len(st.get("lists", [])) >= 200, "bob: all 200 organisation lists in the start state")
# 2.724.0 (#5184): the row-level security column org_id of #4602 (08.11.2026) came along on every task, +75 KB in bob's start set
check(not any("org_id" in t for t in st["tasks"]), "bob: no task carries the internal org_id")

full = {t["id"]: t for t in st["tasks"]}
check("lz" not in st and len(full) == len(st["tasks"]) > 16000, "without lz=1: the whole state as before")
d8 = kt.dbx("SELECT to_char(current_date + 7, 'YYYY-MM-DD')")[0][0]


def tdfill(j):
    """2.575.0 (#3966): as the client's tdFill (liveparts.js): the keys left out at their default back from the answer's tdef.
    2.1117.0 (#6023): + the zone +00:00 back on the points in time named in tutc (td=2)."""
    for t in j.get("tasks", []):
        for k, v in (j.get("tdef") or {}).items():
            if k not in t and not (k == "content" and "content_n" in t):
                t[k] = type(v)() if isinstance(v, (list, dict)) else v
        for k in j.get("tutc") or ():
            if isinstance(t.get(k), str) and t[k] and not re.search(r"(Z|[+-]\d\d:\d\d)$", t[k]):
                t[k] += "+00:00"
    return j


def lzcheck(s, who, full, me_id, lz_lists=()):
    # 2.575.0 (#3966): measured as the client asks (td=1: without the defaults, filled back here as the client does)
    # 2.1117.0 (#6023): the client asks td=2 (+ the points in time without their zone, tutc)
    r = s.get(B + "/api/state?td=2&lz=1&lzl=" + ",".join(map(str, lz_lists)))
    j = r.json()
    raw = len(r.content)
    check(isinstance(j.get("tdef"), dict) and any(len(t) < len(j["tdef"]) for t in j["tasks"]), f"{who}: td=2 leaves the defaults out (+ tdef)")
    check(j.get("tutc") and not any(str(t.get("updated_at") or "").endswith("+00:00") for t in j["tasks"]),
          f"{who}: td=2 sends the points in time without their zone (+ tutc)")
    old = s.get(B + "/api/state?lz=1&lzl=" + ",".join(map(str, lz_lists))).json()  # an older client (lz=1, no td): every key
    check("tdef" not in old and {t["id"]: t for t in old["tasks"]} == {t["id"]: t for t in tdfill(j)["tasks"]},
          f"{who}: lz=1 without td = every key, the same tasks as td=2 filled back")
    m = TIMING.search(r.headers.get("Server-Timing", ""))
    print(f"PERF {who} /api/state?lz=1: {raw / 1e6:.2f} MB, gzip {len(gzip.compress(r.content, 6)) / 1e6:.2f} MB, "
          f"{r.elapsed.total_seconds():.2f} s, {m.group(2) if m else '?'} statements, {len(j.get('tasks', []))} tasks, "
          f"{len(j.get('lz', {}).get('pending', []))} lists pending", flush=True)
    check(r.ok and "lz" in j, f"{who}: lz=1 answers the start set")
    got = {t["id"]: t for t in j["tasks"]}
    pend = set(j["lz"]["pending"])
    vis = {l["id"] for l in j["lists"]}
    check(pend <= vis and not pend & set(lz_lists), f"{who}: pending = visible lists not asked for")
    inbox = [l["id"] for l in j["lists"] if l.get("is_inbox") and l.get("owner_id") == me_id]
    check(not set(inbox) & pend, f"{who}: the basket is never pending")
    # what the views of the start set show
    need = [t for t in full.values() if t["status"] == 0 and ((t.get("due") and t["due"] <= d8) or t.get("assignee_id") == me_id
                                                              or t.get("pinned") or t.get("waiting_at"))]
    check(all(t["id"] in got for t in need), f"{who}: every task Today / Next 7 days / pinned / waiting / mine needs is there "
                                              f"({sum(1 for t in need if t['id'] not in got)} missing of {len(need)})")
    par = [t for t in got.values() if t.get("parent_id") and t["parent_id"] in full]
    check(all(t["parent_id"] in got for t in par), f"{who}: parents of the start set come along")
    kids = [t for t in full.values() if t.get("parent_id") in got]
    check(all(t["id"] in got for t in kids), f"{who}: subtasks of the start set come along")
    for lid in [*lz_lists, *inbox]:
        a = {i for i, t in full.items() if t["list_id"] == lid}
        check(a <= set(got), f"{who}: list {lid} named in lzl comes whole ({len(a)} tasks)")
    check(all(got[i] == full[i] for i in got), f"{who}: the start set's tasks are serialized as in the whole state")
    # the counts of the pending lists = the whole state's open top-level tasks + tags
    bad = []
    for lid in pend:
        roots = [t for t in full.values() if t["list_id"] == lid and t["status"] == 0 and not t.get("parent_id") and not t.get("context")]
        tags = {}
        for t in roots:
            for g in set(t.get("tags") or []) | set(t.get("ltags") or []):
                tags[g] = tags.get(g, 0) + 1
        x = j["lz"]["counts"].get(str(lid))
        if not x or x["n"] != len(roots) or x["tags"] != tags:
            bad.append((lid, x and x["n"], len(roots)))
    check(not bad, f"{who}: lz.counts = the whole state's counts of the pending lists {bad[:3]}")
    return j, raw


lzj, lzraw = lzcheck(Bo, "bob", full, uid["bob"], lids[:2])
check(lzraw < raw / 2, f"bob: the start set is less than half the whole state ({lzraw} of {raw})")
check(len(lzj["lz"]["pending"]) == 198, "bob: 198 of the 200 organisation lists pending")
rr = Bo.get(B + "/api/state?lz=1&lzl=all")
check("lz" not in rr.json() and len(rr.json()["tasks"]) == len(full), "lzl=all: the whole state")

# GET /api/state/lists: one list, several, all = as in the whole state
for ids in ([lids[10]], [lids[11], lids[12], lids[7]]):
    rr = Bo.get(B + "/api/state/lists?td=2&ids=" + ",".join(map(str, ids)))  # 2.575.0 (#3966): as the client asks; 2.1117.0 (#6023): td=2
    got = {t["id"]: t for t in tdfill(rr.json())["tasks"]}
    want = {i for i, t in full.items() if t["list_id"] in ids}
    check(rr.ok and want <= set(got) and all(got[i] == full[i] for i in got), f"/api/state/lists?ids={ids}: those lists as in the whole state")
rr = Bo.get(B + "/api/state/lists?ids=all")
check(rr.ok and {t["id"] for t in rr.json()["tasks"]} == set(full), "/api/state/lists?ids=all: every task of the whole state")
check(rr.json().get("v", 0) >= st["v"], "/api/state/lists: carries the version")
check(isinstance(rr.json().get("evlinks"), dict) and isinstance(rr.json().get("tcontacts"), dict), "/api/state/lists: + the tasks' events / contacts")

# someone of another organisation: nothing of these lists
oid2 = A.post(B + "/api/admin/orgs", json={"name": "Andere GmbH"}).json()["id"]
assert A.post(B + "/api/users", json={"orgs": [oid2], "username": "carl", "display_name": "Carl", "password": kt.PASSWORD,
                                      "email": "carl@example.com"}).ok
Ca = sess("carl")
rr = Ca.get(B + "/api/state/lists?ids=" + ",".join(map(str, lids[:20])))
check(rr.ok and rr.json()["tasks"] == [], "another organisation: /api/state/lists gives nothing of the lists")
rr = Ca.get(B + "/api/state/lists?ids=all")
check(rr.ok and not any(t["list_id"] in set(lids) for t in rr.json()["tasks"]), "another organisation: ids=all gives nothing of them")
rr = Ca.get(B + "/api/state?lz=1&lzl=" + ",".join(map(str, lids[:5])))
check(rr.ok and not any(t["list_id"] in set(lids) for t in rr.json()["tasks"]), "another organisation: lzl names no foreign list")

# the delta of a change in a pending list carries its new count
L = lzj["lz"]["pending"][0]
before = lzj["lz"]["counts"][str(L)]["n"]
tid = next(t["id"] for t in full.values() if t["list_id"] == L and t["status"] == 0 and not t.get("parent_id"))
v = Bo.get(B + "/api/version").json()["v"]
assert A.post(B + f"/api/tasks/{tid}/complete", json={}).ok
d = kt.until(lambda: (lambda x: x if x.get("tasks") or x.get("full") else None)(Bo.get(B + f"/api/state/delta?since={v}&lean=1&lz=1").json()), 10)
check(d and d.get("full") is False and d.get("lzc", {}).get(str(L), {}).get("n") == before - 1,
      f"delta lz=1: lzc of the touched list ({(d or {}).get('lzc', {}).get(str(L))}, before {before})")
d2 = Bo.get(B + f"/api/state/delta?since={v}&lean=1").json()
check("lzc" not in d2, "delta without lz=1: no lzc (older clients)")

# a person without an organisation: 50 own lists with 200 tasks each
fid, F = freelancer(B, A, "frida")
flids = []
for i in range(50):
    rr = F.post(B + "/api/lists", json={"name": f"Eigenes {i + 1:02d}", "kind": "project"})
    assert rr.ok, rr.text
    flids.append(rr.json()["id"])
fill(flids, 200, [fid], fid)
rf, rawf, bestf = measure(F, "frida (no organisation, 50 lists, 10.000 tasks)")
check(rf.ok and len(rf.json().get("lists", [])) >= 50, "frida: /api/state answers with her lists")
ffull = {t["id"]: t for t in rf.json()["tasks"]}
fj, frawlz = lzcheck(F, "frida", ffull, fid, flids[:1])
check(frawlz < rawf / 2, f"frida: the start set is less than half the whole state ({frawlz} of {rawf})")
rr = F.get(B + f"/api/state/lists?ids={flids[3]}")
check(rr.ok and {t["id"] for t in rr.json()["tasks"]} == {i for i, t in ffull.items() if t["list_id"] == flids[3]},
      "frida: /api/state/lists of her own list")
# a small account gets the whole state with lz=1 too (dave: no tasks of his own, but he sees the organisation's lists ->
# a fresh person without lists instead)
gid, G = freelancer(B, A, "gina")
assert G.post(B + "/api/lists", json={"name": "Klein", "kind": "project"}).ok
check("lz" not in G.get(B + "/api/state?lz=1&lzl=").json(), "a small account: lz=1 answers the whole state")
# 2.724.0 (#5184): which task keys fill the start set (bytes as sent, the largest first) - the first look when the budget is red
kb, tdef = {}, lzj.get("tdef") or {}
for t in lzj["tasks"]:  # filled back by tdfill: a key at its tdef default did not go over the wire
    for k, v in t.items():
        if k in tdef and type(v) is type(tdef[k]) and v == tdef[k]:
            continue
        if k in (lzj.get("tutc") or ()) and isinstance(v, str) and v.endswith("+00:00"):
            v = v[:-6]  # 2.1117.0 (#6023): went over the wire without its zone
        kb[k] = kb.get(k, 0) + len(json.dumps({k: v}, separators=(",", ":"))) - 1
print("PERF bob start set by task key:", ", ".join(f"{k} {n / 1e3:.0f} KB" for k, n in sorted(kb.items(), key=lambda x: -x[1])[:12]), flush=True)
if BUDGET_BYTES:
    check(lzraw <= BUDGET_BYTES, f"bob: start set within {BUDGET_BYTES} bytes ({lzraw})")
sys.exit(kt.done("p3136_state_size"))
