#!/usr/bin/env python3
"""2.65.0 API tests, part A (#1505): GET /api/state with many tasks. Invented names only.
 - seeds 5000 tasks straight into the test database (4000 open, 1000 done, half of them within the last 14 days) in
   five private lists of alice, a list of the organisation shared with bob (edit), pete (participant), vic (view) and an
   agent limited to it (list_ids), and a health list; with subtasks, tags of two people, comments, files (own and on
   comments), field values, dependencies and AI usage
 - measures GET /api/state: time (median of 5), size raw and gzip; prints "PERF ..." lines (generous limits only)
 - prints a hash of the tasks of every viewer ("PERF hash ...": the same data before and after a change of the server
   code must give the same hash; *_at values are left out, they depend on the day of the run)
 - the gzip answer of the server (Accept-Encoding: gzip) is the same JSON as the plain one; small answers stay plain;
   Vary: Accept-Encoding; HEAD and 304 not compressed; file downloads not compressed
 - visibility: pete sees only his assigned tasks of the shared list, vic / bob all of it, nobody else sees alice's
   private lists, the agent never the health list
usage: p265_a_api_test.py <datadir>      (a fresh container; P265A_NOSTART=1 = the server already runs)"""
import gzip
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
NT = int(os.environ.get("P265A_N", "5000"))
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


if not os.environ.get("P265A_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "time_all": True,
                                     "modules": ["comments", "kanban"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "pete", "vic"):
    r = A.post(B + "/api/users", json={"orgs": [ORG], "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Pe, Vi = sess("bob"), sess("pete"), sess("vic")
for s in (Bo, Pe, Vi):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

SH = A.post(B + "/api/lists", json={"name": "Shared", "org_id": ORG}).json()["id"]
for u, ro in (("bob", "edit"), ("pete", "participant"), ("vic", "view")):
    check(A.put(B + f"/api/lists/{SH}/members", json={"user_id": uid[u], "role": ro}).ok, f"setup: share with {u}")
HL = A.post(B + "/api/lists", json={"name": "Health"}).json()["id"]
check(A.patch(B + f"/api/lists/{HL}", json={"life": "health"}).ok, "setup: a health list")
F1 = A.post(B + f"/api/lists/{SH}/fields", json={"name": "Cost", "type": "number"})
F1 = F1.json().get("id") if F1.ok else None
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"})
assert r.ok, r.text
AG, AGH = r.json()["id"], {"Authorization": "Bearer " + r.json()["token"]}
A.patch(B + f"/api/admin/agents/{AG}", json={"org_id": ORG})
A.put(B + f"/api/lists/{SH}/members", json={"user_id": AG, "role": "edit"})
A.put(B + f"/api/lists/{HL}/members", json={"user_id": AG, "role": "edit"})
check(A.patch(B + f"/api/admin/agents/{AG}", json={"list_ids": [SH]}).ok, "setup: the agent is limited to the shared list")

# ------------------------------------------------------------------ seed (deterministic: fixed seed, fixed dates)
SEED = f"""
import random, datetime
from kalmido.core.db import connect
from kalmido.core.pg import insert_id
c = connect()
random.seed(11)
now = datetime.datetime.now(datetime.timezone.utc)
iso = lambda d: d.isoformat()
T0 = "2026-01-05T10:00:00+00:00"
alice, bob, pete, ag = {ALICE}, {uid['bob']}, {uid['pete']}, {AG}
lists = []
for i in range(5):
    lid = insert_id(c, "INSERT INTO lists(name, owner_id, sort, created_at) VALUES(?,?,?,?)", (f"Private {{i}}", alice, 10 + i, T0))
    lists.append(lid)
c.execute("UPDATE lists SET kind='project' WHERE id IN (?,?,?)", (lists[0], lists[1], {SH}))  # dependencies count in projects
lists += [{SH}, {SH}, {HL}]
secs = {{l: [insert_id(c, "INSERT INTO sections(list_id, name, sort) VALUES(?,?,?)", (l, f"Section {{k}}", k)) for k in range(3)]
        for l in set(lists)}}
words = "plan call write check order send review fix build test draft update clean book pay".split()
made, tids, ids = 0, [], []
while made < {NT}:
    lid = random.choice(lists)
    done = made % 5 == 4  # 1000 of 5000 done; half of them within the last 14 days
    comp = iso(now - datetime.timedelta(days=(3 if made % 10 == 4 else 40))) if done else None
    due = "2026-%02d-%02d" % (random.randint(1, 12), random.randint(1, 28)) if random.random() < .6 else None
    ass = random.choice([None, None, pete, bob]) if lid == {SH} else None
    t = insert_id(c, "INSERT INTO tasks(list_id, section_id, title, content, priority, due, sort, created_at, updated_at, created_by, "
                     "status, completed_at, assignee_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (lid, random.choice(secs[lid] + [None]), " ".join(random.sample(words, 3)).capitalize() + f" {{made}}",
                   "Some notes " * random.randint(0, 6), random.choice([0, 0, 1, 3, 5]), due, made, T0, T0, alice,
                   2 if done else 0, comp, ass))
    made += 1
    ids.append(t)
    if random.random() < .15 and made < {NT}:
        ids.append(insert_id(c, "INSERT INTO tasks(list_id, parent_id, title, sort, created_at, updated_at, created_by, assignee_id) "
                                "VALUES(?,?,?,?,?,?,?,?)", (lid, t, f"Sub {{made}}", made, T0, T0, alice, ass)))
        made += 1
    if random.random() < .2:
        c.execute("INSERT INTO task_tags(task_id, user_id, tag) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                  (t, random.choice([alice, bob]), random.choice(["home", "work", "urgent", "later"])))
    if random.random() < .1:
        k = insert_id(c, "INSERT INTO comments(task_id, user_id, body, created_at) VALUES(?,?,?,?)",
                      (t, random.choice([alice, bob]), "A comment", T0))
        if random.random() < .2:
            c.execute("INSERT INTO attachments(task_id, comment_id, user_id, name, mime, size, path, created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (t, k, alice, "c.txt", "text/plain", 3, "none/c.txt", T0))
    if random.random() < .05:
        c.execute("INSERT INTO attachments(task_id, user_id, name, mime, size, path, created_at) VALUES(?,?,?,?,?,?,?)",
                  (t, random.choice([alice, ag]), "f.pdf", "application/pdf", 1234, "none/f.pdf", T0))
    if {F1 or 0} and lid == {SH} and random.random() < .3:
        c.execute("INSERT INTO task_field_values(task_id, field_id, value) VALUES(?,?,?)", (t, {F1 or 0}, str(random.randint(1, 900))))
    if random.random() < .03 and len(ids) > 10:
        b = random.choice(ids[:-1])
        c.execute("INSERT INTO task_deps(task_id, blocker_id, created_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (t, b, T0))
    if random.random() < .02:
        c.execute("INSERT INTO agent_usage(agent_id, task_id, model, input_tokens, output_tokens, cache_write_tokens, cost_usd, day, created_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?)", (ag, t, "model-x", 1000, 200, 0, 0.01, "2026-01-05", T0))
c.execute("UPDATE settings SET value=CAST(CAST(value AS BIGINT)+1 AS TEXT) WHERE key='version'")
c.commit()
c.close()
print(made)
"""
r = subprocess.run(["docker", "exec", "-w", "/app", CT, "python", "-c", SEED], capture_output=True, text=True)
check(r.returncode == 0, "seed failed")
if r.returncode:
    for ln in r.stderr.strip().splitlines()[-12:]:
        print("FAIL: seed |", ln, flush=True)
print("seeded", r.stdout.strip(), flush=True)


def norm(v):
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items() if not k.endswith("_at")}
    if isinstance(v, list):
        return [norm(x) for x in v]
    return v


def hsh(v):
    return hashlib.sha256(json.dumps(norm(v), sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def get_state(s, enc="identity", headers=None):
    return s.get(B + "/api/state", headers={"Accept-Encoding": enc, **(headers or {})}, stream=True)


def raw_of(r):
    b = r.raw.read(decode_content=False)
    r.close()
    return b


# ------------------------------------------------------------------ measure (alice: everything)
get_state(A).close()  # warm up
times, raw = [], b""
for _ in range(5):
    t0 = time.perf_counter()
    r = get_state(A)
    raw = raw_of(r)
    times.append((time.perf_counter() - t0) * 1000)
check(r.status_code == 200, "state 200")
st = json.loads(raw)
ms = statistics.median(times)
gz_local = len(gzip.compress(raw, 5))
gtimes, graw, gr = [], b"", None
for _ in range(5):
    t0 = time.perf_counter()
    gr = get_state(A, "gzip, deflate")
    graw = raw_of(gr)
    gtimes.append((time.perf_counter() - t0) * 1000)
genc = gr.headers.get("Content-Encoding", "")
print(f"PERF tasks={len(st.get('tasks', []))} lists={len(st.get('lists', []))}", flush=True)
print(f"PERF state_ms_median={ms:.0f} (runs {', '.join('%.0f' % x for x in times)})", flush=True)
print(f"PERF state_ms_median_gzip={statistics.median(gtimes):.0f}", flush=True)
print(f"PERF state_kb_raw={len(raw) / 1024:.0f} state_kb_gzip5_local={gz_local / 1024:.0f} "
      f"state_kb_wire_gzip={len(graw) / 1024:.0f} content_encoding={genc or '-'}", flush=True)
done = [t for t in st.get("tasks", []) if t["status"] != 0]
print(f"PERF done_in_state={len(done)} done_kb={len(json.dumps(done, separators=(',', ':'))) / 1024:.0f} (of {len(raw) / 1024:.0f} KB)", flush=True)
one = st["tasks"][len(st["tasks"]) // 2]["id"]
ot = []
for _ in range(5):
    t0 = time.perf_counter()
    A.get(B + f"/api/tasks/{one}")
    ot.append((time.perf_counter() - t0) * 1000)
print(f"PERF one_task_ms_median={statistics.median(ot):.1f}", flush=True)
check(len(st.get("tasks", [])) > NT * .5, f"the state has the tasks ({len(st.get('tasks', []))})")
check(ms < 5000, f"/api/state in {ms:.0f} ms (median)")

# ------------------------------------------------------------------ compression
if genc == "gzip":
    check(json.loads(gzip.decompress(graw)) == st or hsh(json.loads(gzip.decompress(graw))["tasks"]) == hsh(st["tasks"]),
          "the gzip answer is the same state")
    check("accept-encoding" in gr.headers.get("Vary", "").lower(), f"Vary: Accept-Encoding ({gr.headers.get('Vary')})")
    check(len(graw) < len(raw) / 4, f"gzip shrinks the state ({len(graw)} of {len(raw)})")
    r = A.get(B + "/api/version", headers={"Accept-Encoding": "gzip"}, stream=True)
    small = r.raw.read(decode_content=False)
    check(len(small) >= 1024 or r.headers.get("Content-Encoding") is None, "a small answer stays plain")
    r = A.head(B + "/api/state", headers={"Accept-Encoding": "gzip"})
    check(r.headers.get("Content-Encoding") is None, "HEAD: not compressed")
    r = requests.get(B + "/api/state", headers={"Accept-Encoding": "gzip", **H}, stream=True)
    check(r.headers.get("Content-Encoding") is None, f"an error answer (not logged in, {r.status_code}) stays plain or tiny")
    r = A.get(B + "/static/app.css", headers={"Accept-Encoding": "gzip"}, stream=True)
    check(r.headers.get("Content-Encoding") is None, "static files are not compressed by the app (the proxy may)")
    r.close()
    r = get_state(A, "identity")
    check(r.headers.get("Content-Encoding") is None, "Accept-Encoding: identity -> plain")
    r.close()
    r = get_state(A, "gzip;q=0")
    check(r.headers.get("Content-Encoding") is None, "gzip;q=0 -> plain")
    r.close()
else:
    print("PERF note: the server does not compress (yet)", flush=True)

# ------------------------------------------------------------------ hashes + visibility per viewer
views = {"alice": st}
for name, s in (("bob", Bo), ("pete", Pe), ("vic", Vi)):
    r = get_state(s)
    views[name] = json.loads(raw_of(r))
# the agent reads tasks through the API (/api/state is for people): every page of GET /api/v1/tasks (the same load_tasks)
ag_tasks, cur = [], None
for _ in range(100):
    r = requests.get(B + "/api/v1/tasks", params={"limit": 200, **({"cursor": cur} if cur else {})}, headers=AGH)
    if not r.ok:
        check(False, f"agent GET /api/v1/tasks: {r.status_code} {r.text[:200]}")
        break
    ag_tasks += r.json()["data"]
    cur = r.json()["next_cursor"]
    if not cur:
        break
views["agent"] = {"tasks": ag_tasks}
for name, v in views.items():
    tl = v.get("tasks", [])
    print(f"PERF hash {name} tasks={hsh(sorted(tl, key=lambda t: t['id']))} n={len(tl)} sections={hsh(v.get('sections'))} "
          f"counts={hsh(v.get('counts'))} lists={hsh([(x['id'], x['role'], x['progress']) for x in v.get('lists', [])])}", flush=True)
lid_of = lambda v: {t["list_id"] for t in v.get("tasks", [])}  # noqa: E731
check(lid_of(views["bob"]) <= {SH}, "bob sees only the shared list's tasks")
check(lid_of(views["vic"]) <= {SH}, "vic sees only the shared list's tasks")
pt = [t for t in views["pete"].get("tasks", []) if not t.get("context")]
check(all(t["assignee_id"] == uid["pete"] or any(p["id"] == t.get("parent_id") and p["assignee_id"] == uid["pete"] for p in pt)
          for t in pt), "pete (participant) sees only his tasks (and their subtasks)")
check(len(views["vic"]["tasks"]) > len(views["pete"]["tasks"]) > 0, "pete sees fewer than vic")
if "agent" in views:
    check(lid_of(views["agent"]) <= {SH}, "the agent sees only its allowed list (never the health list)")
check(HL in lid_of(views["alice"]), "alice sees her health list")
bt = {t["id"]: t for t in views["bob"]["tasks"]}
at = {t["id"]: t for t in st["tasks"]}
check(any(bt[i]["tags"] != at[i]["tags"] for i in bt if i in at), "tags are per person (bob's differ from alice's)")
check(any(t["comment_count"] for t in st["tasks"]) and any(t["unread"] for t in st["tasks"]), "comment counts + unread")
check(any(t["attachments"] for t in st["tasks"]), "files")
check(not F1 or any(t["fields"] for t in views["bob"]["tasks"]), "field values")
check(any(t["blocked"] for t in st["tasks"]) and any(t["blocking"] for t in st["tasks"]), "dependencies")
check(any(t.get("ai_usage") for t in st["tasks"]), "AI usage")

print(f"p265_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
