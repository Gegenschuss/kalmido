#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.663.0 B (#4191): sealed files are no longer held whole in memory without a limit.
Own container with a server key. A helper process inside the container calls core/orgcrypt.py directly (the budget is per
process, so its counters are checked there); the routes are checked over HTTP. Invented names only.
freelancer-matrix: files
 - step 1, RAM budget: a sealed file from 10 MB on counts twice its size while it is opened whole; over the budget a request
   waits briefly and then answers 503 + Retry-After (was: no limit, every parallel download held its plain text); the room
   is handed back when the answer is closed; a small file is not counted; a background job (no request) goes on after its
   wait; a single file larger than the whole budget still opens when nothing else is held
usage: p2663_b_seal_test.py <datadir>"""
import base64
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check  # noqa: E402
from kt import docker_logs_on_first_fail  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

docker_logs_on_first_fail()
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
KEY = base64.b64encode(os.urandom(32)).decode()


def in_ct(code):
    """Python inside the app container; the last stdout line is JSON."""
    r = subprocess.run(["docker", "exec", CT, "python3", "-c", code], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "600", "KALMIDO_SECRET_KEY": KEY})
A = kt.setup()
ALICE = kt.me_id(A)
A.patch(B + "/api/settings", json={"lang": "en", "features": "collab,files,comments", "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
FID, Fr = freelancer(B, A)

BASE = f"""import io, json, os, threading, time
from kalmido.core.db import connect
from kalmido.core.config import app
from kalmido.core import orgcrypt as oc
c = connect()
ORG = {ORG}
KEY = oc.oc_key(c, ORG)
c.commit()
MB = 1024 * 1024
def sealed_v1(name, n):  # a sealed file of the older format (one piece), plain bytes of a known pattern
    p = "/tmp/p2663b-" + name
    data = bytes(i % 251 for i in range(n))
    with open(p, "wb") as f:
        f.write(oc.oc_seal_raw(KEY, ORG, data))
    return p, data
"""

# ---------------------------------------------------------------- step 1: the RAM budget (one process, its own counters)
r = in_ct(BASE + """out = {}
oc.SEAL_RAM_BUDGET, oc.SEAL_RAM_WAIT, oc.SEAL_RAM_BG_WAIT = 30 * MB, 0.3, 0.3
big, data = sealed_v1("big", 12 * MB)
small, sdata = sealed_v1("small", 2 * MB)
held = oc.oc_ram_take(os.path.getsize(big))  # another download holds 2 x 12 MB
out["held"] = oc.oc_ram_held() // MB
with app.test_request_context("/x"):
    try:
        oc.oc_send_file(c, big, mimetype="application/octet-stream")
        out["busy"] = None
    except oc.SealBusy as e:
        rv = app.make_response(app.handle_user_exception(e))
        out["busy"] = [rv.status_code, rv.headers.get("Retry-After"), oc.oc_ram_held() // MB]
    rv = oc.oc_send_file(c, small, mimetype="application/octet-stream")  # under 10 MB: never counted
    out["small"] = [rv.status_code, b"".join(rv.response) == sdata, oc.oc_ram_held() // MB]
    rv.close()
t0 = time.monotonic()
bg = oc.oc_read_file(c, big)  # a background job: waits, then goes on
out["bg"] = [bg == data, oc.oc_ram_held() // MB]
oc.oc_ram_give(held)
with app.test_request_context("/x"):
    rv = oc.oc_send_file(c, big, mimetype="application/octet-stream")
    out["sent"] = [rv.status_code, oc.oc_ram_held() // MB]
    out["body"] = b"".join(rv.response) == data
    rv.close()
    rv.close()  # closing twice hands back once
    out["after"] = oc.oc_ram_held()
oc.SEAL_RAM_BUDGET = 5 * MB  # smaller than the one file: still opens when nothing else is held
with app.test_request_context("/x"):
    rv = oc.oc_send_file(c, big, mimetype="application/octet-stream")
    out["alone"] = [rv.status_code, oc.oc_ram_held() > 0]
    rv.close()
out["end"] = oc.oc_ram_held()
print(json.dumps(out))""")
check(r["held"] >= 24, f"step 1: the other download is counted twice its size {r}")
check(r["busy"] and r["busy"][0] == 503 and r["busy"][1] == "10" and r["busy"][2] == r["held"],
      f"step 1: over the budget a request answers 503 + Retry-After and holds nothing (was: no limit) {r}")
check(r["small"] == [200, True, r["held"]], f"step 1: a file under 10 MB is not counted {r}")
check(r["bg"] == [True, r["held"]], f"step 1: a background job goes on after its wait and hands the room back {r}")
check(r["sent"][0] == 200 and r["sent"][1] >= 24 and r["body"], f"step 1: with room the download is counted while it is sent {r}")
check(r["after"] == 0, f"step 1: closing the answer hands the room back (once) {r}")
check(r["alone"] == [200, True] and r["end"] == 0, f"step 1: a file larger than the budget opens when nothing else is held {r}")

sys.exit(kt.done("p2663_b_seal"))
