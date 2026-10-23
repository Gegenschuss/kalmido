#!/usr/bin/env python3
"""2.172.1 API tests (part A): read later stays with people (#2689), feeds of active organisations, one read-later project
per organisation (#2690). Own container (start.sh) with the fake feed server and the webhook stub inside. Guarded here:
 - an API token (also with the scope "private") and an agent see neither the private read-later project nor the
   organisation's one: /api/v1/lists, /api/v1/tasks, /api/v1/life (no "reading"), a change through the REST API 404; an
   agent's old share of a read-later project shows nothing
 - a read-later project is never shared with an agent (by hand 409), its new entries reach no webhook (personal or the
   organisation's), a task of a normal project still does
 - an organisation's bookmarks stay when the account that added them is deleted (the private ones go with it)
 - the background fetches an organisation's feeds only while the organisation is active and a member with the role admin /
   member / read-only reads feeds (a guest alone: no)
 - two members saving to the organisation's read later at once for the first time make ONE project
 - a person without an organisation: the same (freelancer-matrix: reading)
tenant-matrix: reading, webhook, token"""
import json
import os
import subprocess
import sys
import threading
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FS, STUB = "http://127.0.0.1:8098", "http://127.0.0.1:8097"
FAILS, OKS = [], [0]


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def dbx(q, a=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def sess(u):
    s = requests.Session()
    s.headers.update(H)
    assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok, u
    return s


def jlog(name):
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, name), encoding="utf-8") if x.strip()]
    except OSError:
        return []


def got(path, pred, timeout=15):
    """task.created payloads the stub received on path with pred(task), waiting up to timeout seconds for the first."""
    def f():
        out = []
        for r in jlog("wh.log"):
            if r["path"] == path and r["headers"].get("X-Kalmido-Event") == "task.created":
                p = json.loads(r["body"])
                if pred(p["data"].get("task") or {}):
                    out.append(p)
        return out
    t0 = time.time()
    while time.time() - t0 < timeout:
        if f():
            return f()
        time.sleep(0.3)
    return f()


def feed(title, slug):
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title><link>https://example.com/{slug}</link>'
            f'<item><title>{title} 1</title><link>https://example.com/{slug}/1</link><guid>{slug}-1</guid></item></channel></rss>')


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098"
           " -e KALMIDO_WEBHOOK_ALLOW_HOSTS=127.0.0.1:8097 -e KALMIDO_WEBHOOK_TICK=1")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
os.makedirs(os.path.join(DATA, "feeds"), exist_ok=True)
for name in ("alpha", "beta", "gamma"):
    with open(os.path.join(DATA, "feeds", name + ".xml"), "w", encoding="utf-8") as f:
        f.write(feed(name.title() + " Blog", name))
for x in ("fake_feeds.py", "stub_webhook.py"):
    subprocess.run(["cp", os.path.join(N, x), DATA])
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/" + x])
time.sleep(1)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
for u, orgs in (("bob", [{"id": ORG, "role": "member"}]), ("carl", [{"id": ORG, "role": "member"}]),
                ("dora", [{"id": ORG, "role": "admin"}]), ("frank", []), ("gail", [])):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
OB = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]}).json().get("id")
OG = A.post(B + "/api/admin/orgs", json={"name": "Gamma", "admin_id": uid["gail"]}).json().get("id")
r = A.post(B + "/api/users", json={"orgs": [{"id": OB, "role": "guest"}], "username": "gus", "display_name": "Gus",
                                   "password": "password123", "email": "gus@example.com"})
assert r.ok, r.text
Bo, Ca, Fr, Ga, Gu = sess("bob"), sess("carl"), sess("frank"), sess("gail"), sess("gus")
for s in (A, Bo, Ca, Fr, Ga, Gu):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATURES}).ok

# ================================================================ #2690: the organisation's read-later project, made once
res = []


def save(s, n):
    res.append(s.post(B + "/api/reading", json={"url": f"https://example.com/first/{n}", "space": SP}))


ts = [threading.Thread(target=save, args=(s, n)) for n, s in enumerate((Bo, Ca, A))]
for t in ts:
    t.start()
for t in ts:
    t.join()
check(all(x.status_code == 201 for x in res), "three members save at once " + str([x.status_code for x in res]))
check(len({x.json()["list_id"] for x in res}) == 1, "... into ONE project " + str([x.json().get("list_id") for x in res]))
OL = res[0].json()["list_id"]
n_lists = dbx("SELECT COUNT(*) FROM lists WHERE org_id=? AND name='Read later'", (ORG,))[0][0]
check(n_lists == 1, f"no second (discarded) project was made ({n_lists})")
check(dbx("SELECT list_id FROM reading_orgs WHERE org_id=?", (ORG,))[0][0] == OL, "remembered for the organisation")
r = A.post(B + "/api/reading", json={"url": "https://example.com/private/1", "title": "Mine"})
check(r.status_code == 201 and r.json()["space"] == "private", "a private read-later entry")
PL, PT = r.json()["list_id"], r.json()["task_id"]
OTK = res[0].json()["task_id"]
NL = A.post(B + "/api/lists", json={"name": "Normal", "org_id": None}).json()["id"]

# ================================================================ #2689: API tokens and agents see no read later
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
assert r.ok, r.text
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
AGID = r.json().get("user_id") or r.json().get("id")
r = A.post(B + "/api/me/tokens", json={"name": "t1", "scopes": ["read", "write", "private"]})
assert r.ok, r.text
PTH = {"Authorization": "Bearer " + r.json()["token"], **H}
# an agent's old share of the private read-later project (made before 2.172.1)
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,'edit','edit',0,'2026-10-01T00:00:00Z')", (PL, AGID))
r = requests.get(B + "/api/v1/lists", headers=PTH)
ids = [x["id"] for x in (r.json().get("data") or [])] if r.ok else []
check(r.ok and PL not in ids and OL not in ids and NL in ids, f"API token lists: no read later, the normal project (PL {PL in ids}, OL {OL in ids})")
for lid, what in ((PL, "private"), (OL, "organisation")):
    r = requests.get(B + "/api/v1/tasks", headers=PTH, params={"list_id": lid})
    check(r.status_code in (403, 404) or not (r.json().get("data") or []), f"API token: no tasks of the {what} read later ({r.status_code})")
    r = requests.patch(B + f"/api/v1/lists/{lid}", headers=PTH, json={"name": "x"})
    check(r.status_code == 404, f"API token: the {what} read later cannot be changed ({r.status_code})")
r = requests.get(B + "/api/v1/tasks", headers=PTH)
tids = [x["id"] for x in (r.json().get("data") or [])] if r.ok else []
check(r.ok and PT not in tids and OTK not in tids, "API token: all tasks without read-later entries")
r = requests.get(B + "/api/v1/life", headers=PTH)
check(r.ok and "reading" not in r.json(), "API token: /api/v1/life without reading " + r.text[:200])
check(requests.get(B + f"/api/v1/tasks/{PT}", headers=PTH).status_code == 404, "API token: a read-later entry 404")
r = requests.get(B + "/api/v1/lists", headers=AGH)
check(r.ok and PL not in [x["id"] for x in (r.json().get("data") or [])], "agent with an old share: the read-later project is not there " + r.text[:200])
check(requests.get(B + f"/api/v1/tasks/{PT}", headers=AGH).status_code in (403, 404), "agent with an old share: no entry")
check(dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (PL, AGID)), "the old share is kept (nothing deleted)")
dbx("DELETE FROM list_members WHERE list_id=? AND user_id=?", (PL, AGID))
# never shared with an agent
r = A.put(B + f"/api/lists/{PL}/members", json={"user_id": AGID, "role": "edit"})
check(r.status_code == 409 and "Read later" in r.text, f"private read later: not shared with an agent ({r.status_code} {r.text[:120]})")
r = A.put(B + f"/api/lists/{OL}/members", json={"user_id": AGID, "role": "edit"})
check(r.status_code in (403, 404, 409), f"the organisation's read later: not shared with an agent ({r.status_code})")
r = A.post(B + f"/api/agents/{AGID}/share-all")
check(r.ok and not dbx("SELECT 1 FROM list_members WHERE list_id IN (?, ?) AND user_id=?", (PL, OL, AGID)),
      "share all with the agent: read later left out " + r.text[:200])
# 2.172.1 review: a project shared with the agent that becomes "Read later" loses the agent; an agent member hears nothing
SL = A.post(B + "/api/lists", json={"name": "Shared", "org_id": None}).json()["id"]
check(A.put(B + f"/api/lists/{SL}/members", json={"user_id": AGID, "role": "edit"}).ok, "a normal project shared with the agent")
check(A.patch(B + f"/api/lists/{SL}", json={"life": "reading"}).ok, "... becomes read later")
check(not dbx("SELECT 1 FROM list_members WHERE list_id=? AND user_id=?", (SL, AGID)), "... and the agent is no member any more")
dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,'edit','edit',0,'2026-10-01T00:00:00Z')", (SL, AGID))
n_ev = dbx("SELECT COUNT(*) FROM agent_events WHERE agent_id=?", (AGID,))[0][0]
check(A.post(B + "/api/tasks", json={"title": "Read me", "list_id": SL}).ok, "a new entry in the read-later project")
time.sleep(1)
evs = [r[0] for r in dbx("SELECT payload FROM agent_events WHERE agent_id=? ORDER BY id", (AGID,))[n_ev:]]
check(not any(f'"list_id": {SL}' in x or f'"list_id":{SL}' in x or "Read me" in x for x in evs), "an agent member gets no event of read later " + str(evs)[:200])
dbx("DELETE FROM list_members WHERE list_id=? AND user_id=?", (SL, AGID))
# the person in the app as before
check(A.get(B + "/api/reading").json()["list_id"] == PL, "the app: the private read later as before")
check(any(x["id"] == OL for x in Bo.get(B + "/api/state").json()["lists"]), "the app: a member sees the organisation's project")

# ================================================================ #2689: webhooks
r = A.post(B + "/api/me/webhooks", json={"name": "mine", "url": STUB + "/alice", "events": ["task.created"]})
check(r.status_code == 201, "alice's own webhook " + r.text[:200])
r = A.post(B + f"/api/orgs/{ORG}/webhooks", json={"name": "Alpha", "url": STUB + "/org", "events": ["task.created"]})
check(r.status_code == 201, "the organisation's webhook " + r.text[:200])
OPL = A.post(B + "/api/lists", json={"name": "Org board", "org_id": ORG}).json()["id"]
A.post(B + "/api/reading", json={"url": "https://example.com/private/2", "title": "Private later"})
Bo.post(B + "/api/reading", json={"url": "https://example.com/org/2", "title": "Org later", "space": SP})
A.post(B + "/api/tasks", json={"list_id": NL, "title": "Normal task"})
A.post(B + "/api/tasks", json={"list_id": OPL, "title": "Org task"})
check(bool(got("/alice", lambda t: t.get("title") == "Normal task")), "a normal task reaches the own webhook")
check(bool(got("/org", lambda t: t.get("title") == "Org task")), "an organisation's task reaches its webhook")
time.sleep(3)
check(not got("/alice", lambda t: t.get("title") in ("Private later", "Org later"), 0), "read later never at the own webhook")
check(not got("/org", lambda t: t.get("title") in ("Private later", "Org later"), 0), "read later never at the organisation's webhook")

# ================================================================ #2689: an organisation's bookmarks stay
T0 = "2026-10-01T00:00:00Z"
for oid, url in ((ORG, "https://example.com/org-bm"), (None, "https://example.com/dora-bm")):
    dbx("INSERT INTO bookmarks(user_id,org_id,url,url_key,title,preview,created_at,updated_at) VALUES(?,?,?,?,?,'done',?,?)",
        (uid["dora"], oid, url, url, "BM", T0, T0))
check(A.delete(B + f"/api/users/{uid['dora']}").ok, "the account that added the bookmarks deleted")
row = dbx("SELECT user_id FROM bookmarks WHERE url='https://example.com/org-bm'")
check(row and row[0][0] != uid["dora"], f"the organisation's bookmark stays with the organisation {row}")
check(not dbx("SELECT 1 FROM bookmarks WHERE url='https://example.com/dora-bm'"), "the private bookmark went with the account")

# ================================================================ #2690: feeds only of active organisations with readers
assert A.post(B + "/api/feeds", json={"url": FS + "/alpha.xml", "space": SP}).status_code == 201
assert Fr.post(B + "/api/feeds", json={"url": FS + "/beta.xml", "space": f"org:{OB}"}).status_code == 201
assert Ga.post(B + "/api/feeds", json={"url": FS + "/gamma.xml", "space": f"org:{OG}"}).status_code == 201
Fr.patch(B + "/api/settings", json={"features": "comments"})  # Beta: only the guest Gus reads feeds
dbx("UPDATE orgs SET retired_at=? WHERE id=?", (T0, OG))      # Gamma: retired (its admin still reads feeds)
time.sleep(1)
n0 = len(jlog("feeds.log"))
dbx("UPDATE rss_feeds SET last_fetch=NULL WHERE url IN (?, ?, ?)", (FS + "/alpha.xml", FS + "/beta.xml", FS + "/gamma.xml"))
t0 = time.time()
while time.time() - t0 < 90 and not any(e["p"] == "/alpha.xml" for e in jlog("feeds.log")[n0:]):
    time.sleep(1)
seen = {e["p"] for e in jlog("feeds.log")[n0:]}
check("/alpha.xml" in seen, "the background fetches the feed of an active organisation")
check("/beta.xml" not in seen, "... not the one of an organisation where only a guest reads feeds")
check("/gamma.xml" not in seen, "... not the one of a retired organisation")

# ================================================================ a person without an organisation (freelancer-matrix: reading)
FID, Fl = freelancer(B, A)
r = Fl.post(B + "/api/reading", json={"url": "https://example.com/frida/1", "title": "Frida later", "space": "private"})
check(r.status_code == 201, "freelancer: read later " + r.text[:200])
FL = r.json()["list_id"]
FNL = Fl.post(B + "/api/lists", json={"name": "Frida normal"}).json()["id"]
r = Fl.post(B + "/api/me/tokens", json={"name": "ft", "scopes": ["read", "write", "private"]})
FTH = {"Authorization": "Bearer " + r.json()["token"], **H}
r = requests.get(B + "/api/v1/lists", headers=FTH)
ids = [x["id"] for x in (r.json().get("data") or [])] if r.ok else []
check(r.ok and FL not in ids and FNL in ids, "freelancer's token: no read later, the normal project")
check("reading" not in requests.get(B + "/api/v1/life", headers=FTH).json(), "freelancer's token: /api/v1/life without reading")
r = Fl.post(B + "/api/me/webhooks", json={"name": "f", "url": STUB + "/frida", "events": ["task.created"]})
check(r.status_code == 201, "freelancer: own webhook")
Fl.post(B + "/api/reading", json={"url": "https://example.com/frida/2", "title": "Frida later 2", "space": "private"})
Fl.post(B + "/api/tasks", json={"list_id": FNL, "title": "Frida task"})
check(bool(got("/frida", lambda t: t.get("title") == "Frida task")), "freelancer: a normal task reaches the webhook")
time.sleep(2)
check(not got("/frida", lambda t: t.get("title") == "Frida later 2", 0), "freelancer: read later never at the webhook")
check(Fl.get(B + "/api/reading?space=private").json()["list_id"] == FL, "freelancer: read later in the app as before")

print(f"p21721_a_reading_guard: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
