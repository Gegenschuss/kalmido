#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.585.0 A (#4836, #4841): the background encryption pass next to a deletion that hands a list on, and the start's triggers.
Own container with a server key (the start pass waits, KALMIDO_ORGCRYPT_DELAY=600); a helper process inside the container runs
the passes with a fixed order of events (no timing):
 - #4836 rows: the pass read the lists, then a deletion handed paula's budget project to bob and resealed its rows for bob
   (committed) -> the pass leaves them sealed for bob (it read paula's space before; was: back to paula's key, which the
   deletion drops; CI v2.573.0 p2146_d_api "booking and receipt resealed for alice's account")
 - #4836 rows: a list that a running transaction changes is left alone (no wait, nothing changed); then the pass does it
 - #4836 files: a deletion resealed the project's receipt for bob and holds the spaces lock until its COMMIT -> the pass
   waits for it and leaves the file sealed for bob (was: sealed again for paula, read before the COMMIT)
 - #4841: tools/check_migrations.py flags a fragment trigger whose WHEN Postgres prints otherwise (IN (...), a text without
   its type), the fragments as they are pass
usage: p2585_a_api_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(os.path.dirname(N), "tools"))
from kt import FAILS, OKS, check, sess  # noqa: E402
from kt import docker_logs_on_first_fail  # noqa: E402
import check_migrations as cm  # noqa: E402

docker_logs_on_first_fail()
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()


def in_ct(code):
    """Python inside the app container; the last stdout line is JSON."""
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- #4841: the lint (no server)
OLD = ("CREATE OR REPLACE TRIGGER t1 AFTER INSERT ON fs_nodes FOR EACH ROW WHEN (NEW.kind = 'ref' AND NEW.ref_kind IN ('a', 'b')) "
       "EXECUTE FUNCTION f1()")
NEW = ("CREATE OR REPLACE TRIGGER t1 AFTER INSERT ON fs_nodes FOR EACH ROW WHEN (NEW.kind = 'ref'::text AND "
       "(NEW.ref_kind = ANY (ARRAY['a'::text, 'b'::text]))) EXECUTE FUNCTION f1('x', 'y')")
check(cm.trigger_when_finding(cm.sql_bare(OLD)) and "IN (" in cm.trigger_when_finding(cm.sql_bare(OLD)), "#4841: WHEN with IN (...) is a finding")
check(cm.trigger_when_finding(cm.sql_bare(OLD.replace(" AND NEW.ref_kind IN ('a', 'b')", ""))), "#4841: an untyped text in WHEN is a finding")
check(cm.trigger_when_finding(cm.sql_bare(NEW)) is None, "#4841: WHEN as Postgres prints it is none (the function's arguments are no WHEN)")
check(cm.content_findings("x.py", {"SCHEMA": (OLD + ";", 3)}, "") != [], "#4841: a fragment with such a trigger has a finding")
check(cm.findings() == [], f"#4841: the fragments as they are pass {cm.findings()[:3]}")

# ---------------------------------------------------------------- setup: a server key, paula's budget project with a receipt
env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=600 -e KALMIDO_SECRET_KEY={KEY}")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
for _ in range(120):
    try:
        if requests.get(B + "/api/health", timeout=2).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(0.25)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u, n in (("bob", "Bob Member"), ("paula", "Paula Example")):
    r = A.post(B + "/api/users", json={"orgs": [], "username": u, "display_name": n, "password": "password123"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Pa = sess("paula")
Pa.patch(B + "/api/settings", json={"lang": "en", "features": "comments,collab,budget"})
PL = Pa.post(B + "/api/budget/lists", json={}).json().get("list_id")
e = Pa.post(B + f"/api/budget/{PL}/entries", json={"day": "2026-09-04", "amount": 12, "kind": "out", "title": "Brushes"}).json()
check(Pa.post(B + f"/api/budget/entries/{e['id']}/files", files=[("file", ("receipt.txt", b"kept", "text/plain"))]).ok, "setup: paula's project receipt")

HEAD = f"""import json, os, threading, time
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.core.config import ATT_DIR
from kalmido.core import orgcrypt as oc
from kalmido.life import budget as bud
from kalmido.admin import orgcrypt_cli as cli
PL, PID, BOB = {PL}, {ids["paula"]}, {ids["bob"]}
c, c2 = connect(), connect()
def rpath(k):
    with system_ctx(k):
        return os.path.join(ATT_DIR, k.execute("SELECT path FROM budget_files WHERE list_id=?", (PL,)).fetchone()[0])
def state(k):
    with system_ctx(k):
        rows = k.execute("SELECT * FROM budget_entries WHERE list_id=?", (PL,)).fetchall()
    path = rpath(k)
    k.commit()
    return {{"sids": [int(r["sid"] or 0) for r in rows], "titles": [bud.bud_dec(k, "budget_entries", r)["title"] for r in rows],
            "file": oc.oc_file_org(cli._head(path) or b""), "path": path}}
def hand_on(k, to):  # what a deletion does in its transaction: the list to its new owner, its rows and files sealed for them
    getattr(cli, "oc_spaces_lock", lambda x: None)(k)  # (without it: the code before 2.585, the counter-check of this suite)
    with system_ctx(k):
        k.execute("UPDATE lists SET owner_id=? WHERE id=?", (to, PL))
    bud.bud_settle(k, list_ids=[PL], force_from=-PID, commit=False)
    cli.files_decrypt(k, [rpath(k)], only_org=-PID, reseal=lambda x: -to)  # no commit: the deletion's transaction goes on
"""
s = in_ct(HEAD + "print(json.dumps(state(c)))")
check(s["sids"] == [-ids["paula"]] and s["file"] == -ids["paula"] and s["titles"] == ["Brushes"], f"setup: sealed for paula's account {s}")

# ---------------------------------------------------------------- #4836: rows, the pass read the lists before the hand-on
r = in_ct(HEAD + """
calls = [0]
def stop():  # bud_settle asks once per list, after it read the lists: the hand-on commits right then
    calls[0] += 1
    if calls[0] == 1:
        hand_on(c2, BOB)
        c2.commit()
    return False
n = bud.bud_settle(c, list_ids=[PL], stop=stop)
print(json.dumps({"n": n, "calls": calls[0], **state(c)}))""")
check(r["calls"] == 1 and r["sids"] == [-ids["bob"]] and r["titles"] == ["Brushes"],
      f"#4836: the pass leaves the rows sealed for bob (it read paula's space before the hand-on) {r}")
check(r["file"] == -ids["bob"], f"setup: the hand-on sealed the receipt for bob {r}")

# ---------------------------------------------------------------- #4836: a list in a running transaction is left to it
r = in_ct(HEAD + """
with system_ctx(c2):
    c2.execute("UPDATE lists SET owner_id=? WHERE id=?", (PID, PL))  # back to paula, not committed yet
t0 = time.monotonic()
n = bud.bud_settle(c, list_ids=[PL])
waited = time.monotonic() - t0
mid = state(c)
c2.commit()
n2 = bud.bud_settle(c, list_ids=[PL])
print(json.dumps({"n": n, "waited": waited, "mid": mid["sids"], "n2": n2, **state(c)}))""")
check(r["n"] == 0 and r["mid"] == [-ids["bob"]] and r["waited"] < 5, f"#4836: a list that a transaction changes: left alone, no wait {r}")
check(r["n2"] >= 1 and r["sids"] == [-ids["paula"]] and r["titles"] == ["Brushes"], f"#4836: after its commit the pass reseals it {r}")

# ---------------------------------------------------------------- #4836: files, the pass waits for the deletion's COMMIT
r = in_ct(HEAD + """
cli.files_settle(c, list_ids=[PL])  # the receipt for paula again, like the rows (owner paula now)
before = state(c)["file"]
hand_on(c2, BOB)  # the receipt for bob on the disk, the owner bob only at the COMMIT
out = {}
def run():
    k = connect()
    out["r"] = cli.files_settle(k, list_ids=[PL])
    k.close()
th = threading.Thread(target=run)
th.start()
blocked = False
for _ in range(400):  # until the pass waits for the lock (or is done: without the lock it does not wait)
    with system_ctx(c):
        blocked = bool(c.execute("SELECT 1 FROM pg_locks WHERE locktype='advisory' AND NOT granted").fetchone())
    c.commit()
    if blocked or not th.is_alive():
        break
    time.sleep(0.05)
c2.commit()
th.join(60)
print(json.dumps({"before": before, "blocked": blocked, "out": out.get("r"), **state(c)}))""")
check(r["before"] == -ids["paula"], f"setup: the receipt sealed for paula again {r}")
check(r["blocked"], f"#4836: the pass waits for the deletion's COMMIT {r}")
check(r["file"] == -ids["bob"] and (r["out"] or {}).get("resealed") == 0, f"#4836: and leaves the receipt sealed for bob {r}")
check(r["sids"] == [-ids["bob"]], f"#4836: the rows sealed for bob too {r}")

print(f"p2585_a: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
