#!/usr/bin/env python3
"""2.38.0 API tests, part U2: locked tasks in a batch (#1132), the message search with only special characters (#1169) and
the server points of #1155; own container (start.sh).
 - a batch patch / patch_each over a locked and a free task changes the free one and answers the locked one in skipped
   (its values stay); errors still name the lock
 - the message search: a query of only %, _, spaces or punctuation answers 200 with no hits (before: 400); an empty query
   stays 400; a real word still finds its message (ae = ae)
 - office_doc_log: read entries (open, render, pdf) older than 90 days go after a start (watchdog), newer reads and every
   other entry (writes, exports) stay
 - fx2_mask_ip: IPv4 without the last octet, IPv6 only the first 48 bits, anything else unchanged
usage: p2380_u2_api_test.py <datadir>"""
import os
import dbx as dbxm
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")  # organisations for the office log
subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ALICE = A.get(B + "/api/state").json()["me"]["id"]

# ================================================================== #1132: locked tasks in a batch are skipped
T1 = A.post(B + "/api/tasks", json={"title": "Locked one", "priority": 0}).json()["id"]
T2 = A.post(B + "/api/tasks", json={"title": "Free one", "priority": 0}).json()["id"]
check(A.patch(B + f"/api/tasks/{T1}", json={"locked": 1}).ok, "setup: lock T1")
r = A.post(B + "/api/tasks/batch", json={"ids": [T1, T2], "action": "patch", "data": {"priority": 3}})
j = r.json()
prio = {t["id"]: t["priority"] for t in A.get(B + "/api/state").json()["tasks"] if t["id"] in (T1, T2)}
check(r.ok and j["count"] == 1 and j["skipped"] == [T1] and prio == {T1: 0, T2: 3}, f"#1132 patch: the free task changes, the locked one is skipped {j} {prio}")
r = A.post(B + "/api/tasks/batch", json={"ids": [T1, T2], "action": "patch_each", "data": {"items": {str(T1): {"priority": 1}, str(T2): {"priority": 1}}}})
j = r.json()
prio = {t["id"]: t["priority"] for t in A.get(B + "/api/state").json()["tasks"] if t["id"] in (T1, T2)}
check(r.ok and j["count"] == 1 and j["skipped"] == [T1] and prio == {T1: 0, T2: 1} and j["errors"], f"#1132 patch_each: same, errors name the lock {j} {prio}")
r = A.post(B + "/api/tasks/batch", json={"ids": [T2], "action": "patch", "data": {"priority": 5}})
check(r.ok and r.json()["skipped"] == [] and r.json()["count"] == 1, "#1132: nothing locked -> skipped empty")

# ================================================================== #1169: only special characters = no hits
c = A.post(B + f"/api/tasks/{T2}/comments", json={"body": "So viel Ärger mit dem 100% Rabatt"})
check(c.ok, "setup: a comment " + c.text[:100])
for q in ("%", "%%%", "_", "__", "% _ !?", "  %  ", "%_%", "..."):
    r = A.get(B + "/api/search/messages", params={"q": q})
    check(r.status_code == 200 and r.json()["hits"] == [] and r.json()["total"] == 0, f"#1169: {q!r} -> 200, no hits ({r.status_code} {r.text[:80]})")
check(A.get(B + "/api/search/messages", params={"q": ""}).status_code == 400, "#1169: an empty query stays 400")
r = A.get(B + "/api/search/messages", params={"q": "aerger"})
check(r.ok and len(r.json()["hits"]) == 1, "the search still finds words (aerger -> Ärger) " + r.text[:120])
r = A.get(B + "/api/search/messages", params={"q": "100%"})
check(r.ok and len(r.json()["hits"]) == 1, "a word with % next to it still finds it " + r.text[:120])

# ================================================================== #1155: fx2_mask_ip
p = subprocess.run(["docker", "exec", "-w", "/app", CT, "python", "-c",
                    "from kalmido.notify.alerts import fx2_mask_ip as m; print('|'.join(str(m(x)) for x in "
                    "['203.0.113.77', '2001:db8:1:2:3:4:5:6', '::ffff:198.51.100.9', '?', '']))"], capture_output=True, text=True)
check(p.stdout.strip() == "203.0.113.x|2001:db8:1::/48|198.51.100.x|?|", "#1155 fx2_mask_ip " + repr(p.stdout + p.stderr[-300:]))

# ================================================================== #1155: old reads in the office log go, writes stay
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE})
check(r.ok, "setup: organisation " + r.text[:120])
ORG = r.json()["id"]
now = datetime.now(timezone.utc)
ago = lambda d: (now - timedelta(days=d)).isoformat(timespec="seconds")  # noqa: E731
rows = [("open", 200), ("pdf", 100), ("render", 91), ("open", 10), ("pdf", 89), ("finalize", 400), ("create", 200),
        ("export", 200), ("update", 120)]
for act, d in rows:
    dbx("INSERT INTO office_doc_log(org_id, doc_id, user_id, at, action, target, detail) VALUES(?,?,?,?,?,?,?)",
        (ORG, None, ALICE, ago(d), act, "doc", '{"u2": 1}'))
mark = lambda: sorted((x[0], x[1][:10]) for x in dbx("SELECT action, at FROM office_doc_log WHERE detail LIKE ?", ('%"u2"%',)))  # noqa: E731
check(len(mark()) == len(rows), "setup: 9 log rows")
subprocess.run(["docker", "restart", CT], capture_output=True)
for _ in range(60):
    try:
        if requests.get(B + "/api/health", timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(0.5)
want = sorted((a, ago(d)[:10]) for a, d in rows if not (a in ("open", "pdf", "render") and d > 90))
for _ in range(30):
    if mark() == want:
        break
    time.sleep(0.5)
got = mark()
check(got == want, f"#1155: reads older than 90 days gone, newer reads + writes + exports kept {got}")
check(not [x for x in got if x[0] in ("open", "pdf", "render") and x[1] < ago(90)[:10]], "#1155: no old read left")

print(f"p2380_u2_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
