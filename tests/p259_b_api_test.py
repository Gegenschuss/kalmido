#!/usr/bin/env python3
"""2.59.0 API tests (part B): #1375 related tasks, stage 1.
 - the optional embedding service in its stub mode (embed/server.py EMBED_STUB=1: deterministic vectors from word hashes, no
   model) inside the test container; KALMIDO_EMBED_URL points at it
 - service not running yet: enabled, pending, empty lists, never a 500; then the first start computes every vector (throttled
   batches), a changed title gets a new text_hash, a trashed task loses its vector, an encrypted organisation's vectors are
   sealed (kenc1:), a private list's vectors stay plain
 - the boundary: a person / an agent never gets an id of a task they cannot see (related, similar, search semantic=1, API v1,
   the related field of agent events); an agent only its shared lists, a token limited to selected lists only those
 - the instance switch off: enabled false everywhere; the service gone again: answers from the cache, no 500
 - rough timing (PERF lines)
tenant-matrix: org, related
usage: p259_b_api_test.py <datadir>"""
import json
import os
import subprocess
import sys
import time

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
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


def tok(t):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + t})
    return s


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def agent(name, scopes, org=None):
    r = A.post(B + "/api/admin/agents", json={"username": name, "display_name": name.title(), "scopes": scopes})
    assert r.status_code == 201, r.text
    aid, t = r.json()["id"], r.json().get("token") or ""
    dbx("DELETE FROM org_members WHERE user_id=? AND org_id IS DISTINCT FROM ?", (aid, org), write=True)
    if org:
        dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'member') ON CONFLICT DO NOTHING", (org, aid), write=True)
    dbx("UPDATE agents SET org_id=? WHERE user_id=?", (org, aid), write=True)
    return aid, tok(t)


def stub(on):
    """Start / stop the stub service inside the app container (port 8090)."""
    if on:
        subprocess.run(["docker", "cp", os.path.join(N, "..", "embed", "server.py"), f"{CT}:/tmp/embed_stub.py"], check=True)
        subprocess.run(["docker", "exec", "-d", "-e", "EMBED_STUB=1", CT, "python", "/tmp/embed_stub.py"], check=True)
        for _ in range(40):
            p = subprocess.run(["docker", "exec", CT, "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=2)"],
                               capture_output=True)
            if p.returncode == 0:
                return
            time.sleep(0.25)
        raise SystemExit("the stub service did not start")
    subprocess.run(["docker", "exec", CT, "python", "-c", "import os, signal\nfor p in os.listdir('/proc'):\n if p.isdigit():\n  try:\n   "
                    "cl = open(f'/proc/{p}/cmdline', 'rb').read()\n  except OSError:\n   continue\n  if b'embed_stub' in cl:\n   os.kill(int(p), signal.SIGTERM)"],
                   check=False)


def task(s, title, lid, notes=""):
    r = s.post(B + "/api/tasks", json={"title": title, "list_id": lid, "notes": notes})
    assert r.ok, r.text
    return r.json()["id"]


def wait_for(pred, what, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return time.time() - t0
        time.sleep(0.5)
    check(False, what + " (timeout)")
    return None


def vec_ids():
    return {r[0] for r in dbx("SELECT task_id FROM task_vectors")}


def ids_of(j):
    return {x["id"] for x in (j.get("items") or [])}


KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
EXTRA = (os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_SECRET_KEY=" + KEY
         + " -e KALMIDO_EMBED_URL=http://127.0.0.1:8090 -e KALMIDO_EMBED_IDLE=0.5 -e KALMIDO_EMBED_BUSY=0.2 -e KALMIDO_EMBED_DOWN=1 -e KALMIDO_EMBED_CLEAN=3"
         + " -e KALMIDO_RELATED_MIN=0.6 -e KALMIDO_RELATED_DUP=0.95 -e KALMIDO_RELATED_SEARCH=0.5")
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=dict(os.environ, EXTRA=EXTRA), check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE = ids["bob"], ids["carol"], ids["dave"]
ALPHA = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB}).json()["id"]
BETA = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
AG, AGS = agent("relbot", ["read", "tasks:write", "comments"], org=ALPHA)
A.post(B + "/api/auth/logout")
A, Bo, Ca, Da = sess("alice"), sess("bob"), sess("carol"), sess("dave")
for s in (A, Bo, Ca, Da):
    s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})

LA = Bo.post(B + "/api/lists", json={"name": "Office work", "org_id": ALPHA}).json()["id"]
LA2 = Bo.post(B + "/api/lists", json={"name": "Office plans", "org_id": ALPHA}).json()["id"]  # not shared with the agent
LB = Ca.post(B + "/api/lists", json={"name": "Office work", "org_id": BETA}).json()["id"]
LP = Bo.post(B + "/api/lists", json={"name": "Office home"}).json()["id"]  # bob's private list
check(Bo.put(B + f"/api/lists/{LA}/members", json={"user_id": AG, "role": "edit"}).ok, "setup: LA shared with the agent")

T1 = task(Bo, "Invoice template for clients", LA)
T2 = task(Bo, "Invoice template for customers", LA)
T3 = task(Bo, "Invoice template for clients", LA)  # an exact duplicate of T1
T4 = task(Bo, "Buy milk and bread", LA)
T5 = task(Bo, "Invoice template for clients", LA2)
TB = task(Ca, "Invoice template for clients", LB)
TB2 = task(Ca, "Invoice template for customers", LB)
TP = task(Bo, "Invoice template for clients at home", LP)
ALPHA_IDS, BETA_IDS = {T1, T2, T3, T4, T5}, {TB, TB2}
ALL = ALPHA_IDS | BETA_IDS | {TP}

# ================================================================== the service is not running yet
r = Bo.get(B + "/api/related/config")
check(r.ok and r.json()["enabled"] is True, "config: enabled with KALMIDO_EMBED_URL + the switch on (default) " + r.text[:120])
r = Bo.get(B + f"/api/tasks/{T1}/related")
check(r.ok and r.json() == {"enabled": True, "pending": True, "items": []}, "service down: related = pending, empty, no error " + r.text[:200])
r = Bo.post(B + "/api/tasks/similar", json={"title": "Invoice template for clients", "list_id": LA})
check(r.ok and r.json()["enabled"] is True and not (ids_of(r.json()) & BETA_IDS), "service down: similar answers (no 500), nothing of Beta " + r.text[:200])
r = Bo.get(B + "/api/tasks", params={"scope": "search", "q": "Invoice", "semantic": "1"})
check(r.ok and not ({t["id"] for t in r.json()["tasks"]} & BETA_IDS), "service down: search semantic=1 answers " + r.text[:120])
check(not vec_ids(), "service down: no vectors")
st = A.get(B + "/api/admin/related").json()
check(st["configured"] is True and st["on"] is True and st["reachable"] is False and st["open"] >= len(ALL), f"admin status: not reachable, open {st}")
check(Bo.get(B + "/api/admin/related").status_code == 403, "admin status: admins only")

# ================================================================== first start: everything is computed
stub(True)
dt = wait_for(lambda: ALL <= vec_ids(), "first start computes every vector")
if dt is not None:
    print(f"PERF p259_b first start: {len(ALL)} tasks in {dt:.1f} s", flush=True)
st = A.get(B + "/api/admin/related").json()
check(st["reachable"] is True and st["model"] == "stub" and st["dim"] == 384 and st["done"] >= len(ALL), f"admin status: reachable, model, counts {st}")
rows = {r[0]: r for r in dbx("SELECT task_id, org_id, list_id, model, dim, vec, text_hash FROM task_vectors")}
LORG = {r[0]: r[1] for r in dbx("SELECT t.id, l.org_id FROM tasks t JOIN lists l ON l.id=t.list_id")}
check(all(rows[t][1] == ALPHA and rows[t][2] in (LA, LA2) for t in ALPHA_IDS) and rows[TB][1] == BETA and rows[TP][1] == LORG[TP],
      f"org_id / list_id of the vectors follow the task's list (private: {rows[TP][1]} / {LORG[TP]})")
check(all(str(rows[t][5]).startswith("kenc1:") for t in ALPHA_IDS | BETA_IDS), "an encrypted organisation's vectors are sealed (kenc1:)")
# a list without an organisation keeps its vector plain (like every field orgcrypt leaves alone without an organisation)
dbx("UPDATE lists SET org_id=NULL WHERE id=?", (LP,), write=True)
wait_for(lambda: (dbx("SELECT org_id, vec FROM task_vectors WHERE task_id=?", (TP,)) or [(0, "kenc1:")])[0][0] is None, "a list moved out of the workspace: its vectors follow")
r = dbx("SELECT vec FROM task_vectors WHERE task_id=?", (TP,))
check(r and not str(r[0][0]).startswith("kenc1:") and len(r[0][0]) > 100, "a vector without an organisation is plain base64 (float16)")
check(all(rows[t][3] == "stub" and rows[t][4] == 384 for t in ALL), "model + dim stored")

# ================================================================== related: only what the asker sees
t0 = time.time()
r = Bo.get(B + f"/api/tasks/{T1}/related")
print(f"PERF p259_b related: {(time.time() - t0) * 1000:.0f} ms", flush=True)
j = r.json()
got = ids_of(j)
check(r.ok and j["enabled"] and not j["pending"] and T3 in got and T2 in got, f"related of T1 has the duplicate and the close one {j}")
check(not (got & BETA_IDS) and T1 not in got and T4 not in got, f"related: never Beta, never itself, not the unrelated one {got}")
check(any(x["id"] == T3 and x["dup"] for x in j["items"]) and not any(x["id"] == T2 and x["dup"] for x in j["items"]),
      "dup only above the duplicate threshold")
check(all(set(x) == {"id", "title", "list_id", "done", "score", "dup", "ref"} for x in j["items"]), "item fields as agreed")
check(len(j["items"]) <= 5, "at most 5")
r = Ca.get(B + f"/api/tasks/{TB}/related")
check(r.ok and TB2 in ids_of(r.json()) and not (ids_of(r.json()) & (ALPHA_IDS | {TP})), f"carol (Beta): only Beta {r.text[:200]}")
check(Ca.get(B + f"/api/tasks/{T1}/related").status_code == 404, "carol: another organisation's task = 404")
check(Da.get(B + f"/api/tasks/{TP}/related").status_code == 404, "dave: bob's private task = 404")
# a reference (#id) counts even without a close vector
TR = task(Bo, "Follow-up", LA, notes=f"see #{T4} and #{TB}")
wait_for(lambda: TR in vec_ids(), "the new task gets its vector")
got = ids_of(Bo.get(B + f"/api/tasks/{TR}/related").json())
jr = Bo.get(B + f"/api/tasks/{TR}/related").json()
check(T4 in got and TB not in got and any(x["id"] == T4 and x["ref"] and not x["dup"] for x in jr["items"]), f"an explicit #reference is related (ref), a foreign one never {got}")
j = Bo.get(B + f"/api/tasks/{T4}/related").json()
check(TR in ids_of(j) and not any(x["id"] == TR and x["dup"] for x in j["items"]), f"... also the other way round (a task naming T4), never as a duplicate {j}")
check(TR not in ids_of(Ca.get(B + f"/api/tasks/{TB}/related").json()), "a task of another organisation naming TB stays hidden from carol")

# ================================================================== similar while adding
r = Bo.post(B + "/api/tasks/similar", json={"title": "Invoice template for clients", "list_id": LA})
got = ids_of(r.json())
check(r.ok and {T1, T3} <= got and not (got & BETA_IDS), f"similar: the visible matches, never Beta {got}")
r = Bo.post(B + "/api/tasks/similar", json={"title": "Invoice template for clients", "list_id": LB})
check(r.ok and not (ids_of(r.json()) & BETA_IDS), "similar with a foreign list_id: no context from it, no Beta ids")
r = Bo.post(B + "/api/tasks/similar", json={"title": "Invoice template for clients", "list_id": LA, "exclude": T1})
check(T1 not in ids_of(r.json()), "similar: exclude leaves the task out")
check(Bo.post(B + "/api/tasks/similar", json={"title": "ab"}).json()["items"] == [], "similar: too short = nothing")
check(Bo.post(B + "/api/tasks/similar", json={"title": "x", "list_id": "a"}).status_code == 400, "similar: bad list_id = 400")

# 2.59.0 (#1375): review - live queries per account are limited (6 per 10 s): the 7th answers empty, never a 500
time.sleep(10.5)  # carol's earlier queries are out of the window
res = [Ca.post(B + "/api/tasks/similar", json={"title": "Invoice template for clients", "list_id": LB}) for _ in range(7)]
check(all(r.ok and r.json()["enabled"] is True for r in res), "rate limit: every answer ok + enabled " + str([r.status_code for r in res]))
check(all(TB in ids_of(r.json()) for r in res[:6]) and res[6].json()["items"] == [], f"rate limit: 6 answered, the 7th empty {[len(r.json()['items']) for r in res]}")
check(T1 in ids_of(Bo.post(B + "/api/tasks/similar", json={"title": "Invoice template for clients", "list_id": LA}).json()),
      "rate limit: per account (bob still gets his hints)")

# ================================================================== search semantic=1
r = Bo.get(B + "/api/tasks", params={"scope": "search", "q": "clients invoice template", "semantic": "1"})
ts = r.json()["tasks"]
check(r.ok and not ({t["id"] for t in ts} & BETA_IDS), "search semantic=1: never Beta")
check(any(t.get("similar") for t in ts) or {T1, T3} <= {t["id"] for t in ts}, f"search semantic=1: hits {[t['id'] for t in ts]}")
r = Bo.get(B + "/api/tasks", params={"scope": "search", "q": "customers invoice", "semantic": "1"})
check({t["id"] for t in r.json()["tasks"] if t.get("similar")} <= (ALPHA_IDS | {TP, TR}), "search semantic=1: similar hits are visible ones")

# ================================================================== API v1 / agents
r = AGS.get(V + f"/tasks/{T1}/related")
got = ids_of(r.json())
check(r.ok and T3 in got and not (got & (BETA_IDS | {T5, TP})), f"agent v1: only the shared list LA {r.text[:200]}")
check(AGS.get(V + f"/tasks/{TB}/related").status_code == 404, "agent v1: a task of another organisation = 404")
check(AGS.get(V + f"/tasks/{T5}/related").status_code == 404, "agent v1: an unshared list's task = 404")
r = AGS.get(V + "/search", params={"q": "invoice template", "semantic": "1"})
check(r.ok and {t["id"] for t in r.json()["data"]} <= {T1, T2, T3, T4, TR}, f"agent v1 search semantic=1: only LA {r.text[:200]}")
check(AGS.get(V + "/search", params={"q": "x", "semantic": "2"}).status_code == 400, "v1 search: semantic must be 0 / 1")
spec = AGS.get(V + "/openapi.json").json()
op = spec["paths"].get("/tasks/{id}/related", {}).get("get", {})
check(op.get("x-kalmido-scope") == "read" and "RelatedTask" in spec["components"]["schemas"], "OpenAPI: /tasks/{id}/related with its scope")
check(any(p["name"] == "semantic" for p in spec["paths"]["/search"]["get"]["parameters"]), "OpenAPI: search has semantic")
# a token limited to selected lists: only those
r = Bo.post(B + "/api/me/tokens", json={"name": "limited", "scopes": ["read"], "list_ids": [LA2]})
if r.ok and r.json().get("token"):
    LT = tok(r.json()["token"])
    got = ids_of(LT.get(V + f"/tasks/{T5}/related").json())
    check(not (got & ({T1, T2, T3, T4, TP} | BETA_IDS)), f"a token limited to LA2 sees no other list's tasks {got}")
else:
    check(False, "setup: a token limited to one list " + r.text[:200])

# the related field of an agent event: assign T1 to the agent
r = Bo.patch(B + f"/api/tasks/{T1}", json={"assignee_id": AG})
check(r.ok, "assign T1 to the agent " + r.text[:120])
ev = [json.loads(x[0])["data"] for x in dbx("SELECT payload FROM agent_events WHERE agent_id=? ORDER BY id", (AG,))]
ev = [e for e in ev if (e.get("task") or {}).get("id") == T1]
rel = (ev[-1]["task"].get("related") if ev else None)
check(rel is not None and T3 in {x["id"] for x in rel} and not ({x["id"] for x in rel} & (BETA_IDS | {T5, TP})),
      f"agent event: related tasks of LA only {rel}")
check(rel is not None and all(set(x) == {"id", "title", "score"} for x in rel), "agent event: id, title, score")

# ================================================================== changes: title, trash
old = dbx("SELECT text_hash FROM task_vectors WHERE task_id=?", (T4,))[0][0]
Bo.patch(B + f"/api/tasks/{T4}", json={"title": "Invoice template for clients and milk"})
wait_for(lambda: (dbx("SELECT text_hash FROM task_vectors WHERE task_id=?", (T4,)) or [[old]])[0][0] != old, "a changed title gets a new text_hash")
check(Bo.delete(B + f"/api/tasks/{T2}").ok, "trash T2")
wait_for(lambda: T2 not in vec_ids(), "a trashed task loses its vector")
check(T2 not in ids_of(Bo.get(B + f"/api/tasks/{T1}/related").json()), "a trashed task is not related any more")

# ================================================================== the switch off / on
r = A.put(B + "/api/admin/related", json={"on": False})
check(r.ok and r.json()["on"] is False, "admin: switch off")
check(Bo.get(B + "/api/related/config").json()["enabled"] is False, "switched off: config enabled false")
check(Bo.get(B + f"/api/tasks/{T1}/related").json() == {"enabled": False, "pending": False, "items": []}, "switched off: related empty")
check(Bo.post(B + "/api/tasks/similar", json={"title": "Invoice template"}).json() == {"enabled": False, "items": []}, "switched off: similar empty")
check(AGS.get(V + f"/tasks/{T1}/related").json()["enabled"] is False, "switched off: v1 related enabled false")
check(Bo.patch(B + "/api/settings", json={"lang": "en"}).ok and Bo.put(B + "/api/admin/related", json={"on": True}).status_code == 403, "switch: admins only")
check(A.put(B + "/api/admin/related", json={"on": True}).json()["on"] is True, "admin: switch on again")

# ================================================================== the service gone again: the cache answers, no 500
stub(False)
time.sleep(1)
r = Bo.get(B + f"/api/tasks/{T1}/related")
check(r.ok and T3 in ids_of(r.json()), "service gone: related from the stored vectors " + r.text[:120])
t0 = time.time()
r = Bo.post(B + "/api/tasks/similar", json={"title": "Invoice template for clients", "list_id": LA})
check(r.ok and time.time() - t0 < 5, f"service gone: similar answers quickly ({time.time() - t0:.1f} s)")
r = Bo.get(B + "/api/tasks", params={"scope": "search", "q": "Invoice", "semantic": "1"})
check(r.ok, "service gone: search semantic=1 answers")
logs = subprocess.run(["docker", "logs", CT], capture_output=True, text=True).stdout
check(logs.count("embed: the service is not reachable") <= 3, "one log line per outage, no flood")
check("Traceback" not in logs, "no traceback in the server log")

# ================================================================== 2.59.0 (#1375): review - full visibility only
# a participant sees the parent of an assigned subtask as context (title only): its related tasks = 404 like its notes
LQ = A.post(B + "/api/lists", json={"name": "Desk"}).json()["id"]
r = A.put(B + f"/api/lists/{LQ}/members", json={"user_id": DAVE, "role": "participant"})
check(r.ok, "setup: alice's list shared with dave (participant) " + r.text[:120])
TQ = task(A, "Invoice parent with secret notes", LQ, notes="secret parent notes")
r = A.post(B + "/api/tasks", json={"title": "Invoice step for dave", "parent_id": TQ, "assignee_id": DAVE})
check(r.ok, "setup: a subtask assigned to dave " + r.text[:120])
TQa = r.json()["id"] if r.ok else 0
check(Da.get(B + f"/api/tasks/{TQa}/related").status_code == 200, "participant: related of the own subtask")
check(Da.get(B + f"/api/tasks/{TQ}/related").status_code == 404, "participant: related of the context parent = 404")

# ================================================================== deleting the task deletes the vector (cascade)
dbx("DELETE FROM tasks WHERE id=?", (T3,), write=True)
check(T3 not in vec_ids(), "deleting a task deletes its vector (ON DELETE CASCADE)")

print(f"p259_b_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
