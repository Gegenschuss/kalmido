#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.391.0 A (#3360): the MCP client (class Kalmido in mcp/kalmido_mcp.py) against a fake HTTP server, no container:
 - a 429 without Retry-After (a quota) is not retried
 - 429 with Retry-After: 1 -> exactly 2 requests, both with the same Idempotency-Key, then the answer
 - 503 is retried too; 400 / 404 are not; the third failure is raised (at most 3 requests)
 - a Retry-After beyond the 60 s budget is raised at once (no waiting)
 - the long poll (/agent/events) is never retried
 - every write (POST / PATCH / PUT / DELETE outside /agent/) carries an Idempotency-Key, a different one per call; reads and
   /agent/ writes carry none
 - RateLimit-Remaining 0 + RateLimit-Reset: the next call waits for the reset first
usage: python3 tests/mcp_retry_test.py"""
import importlib.util
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kt import FAILS, OKS, check

N = os.path.dirname(os.path.abspath(__file__))
sp = importlib.util.spec_from_file_location("kalmido_mcp", os.path.join(N, "..", "mcp", "kalmido_mcp.py"))
mcp = importlib.util.module_from_spec(sp)
sp.loader.exec_module(mcp)

REQS = []
PLAN = {}  # path -> list of (status, headers) answers, used in order; the last one repeats


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _go(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        path = self.path.split("?")[0]
        REQS.append((self.command, path, self.headers.get("Idempotency-Key")))
        plan = PLAN.get(path) or [(200, {})]
        st, hd = plan.pop(0) if len(plan) > 1 else plan[0]
        body = json.dumps({"ok": True} if st < 400 else {"error": {"code": "x", "message": f"fail {st}"}}).encode()
        self.send_response(st)
        for k, v in hd.items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _go


srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
api = mcp.Kalmido(f"http://127.0.0.1:{srv.server_address[1]}", "abk_" + "t" * 40, timeout=10)
SLEPT = []
mcp._sleep = lambda s: SLEPT.append(s)  # no real waiting except in the first case, which uses the real sleep


def run(method, path, **kw):
    REQS.clear()
    SLEPT.clear()
    try:
        return api.call(method, path, **kw), None
    except mcp.ApiError as e:
        return None, e


# 1. the brief's case: 429 + Retry-After 1 -> exactly 2 requests with the same key (real sleep: ~1 s)
mcp._sleep = time.sleep
PLAN["/api/v1/tasks/1"] = [(429, {"Retry-After": "1"}), (200, {})]
t0 = time.time()
r, e = run("PATCH", "/tasks/1", body={"title": "x"})
check(e is None and r == {"ok": True} and len(REQS) == 2 and REQS[0][2] and REQS[0][2] == REQS[1][2], f"429 + Retry-After 1: 2 requests, same key {REQS}")
check(0.9 <= time.time() - t0 < 5, f"it waited the Retry-After ({time.time() - t0:.1f} s)")
mcp._sleep = lambda s: SLEPT.append(s)

# 2. 503 is retried, with the table's wait when no Retry-After comes
PLAN["/api/v1/tasks/2/comments"] = [(503, {}), (200, {})]
r, e = run("POST", "/tasks/2/comments", body={"body": "x"})
check(e is None and len(REQS) == 2 and SLEPT == [mcp.RETRY_429_S[0]] and REQS[0][2] == REQS[1][2], f"503 without Retry-After: waits {SLEPT}, same key")

PLAN["/api/v1/tasks/7/comments"] = [(429, {})]
r, e = run("POST", "/tasks/7/comments", body={"body": "x"})
check(e and e.status == 429 and len(REQS) == 1 and not SLEPT, "429 without Retry-After (a quota): not retried")

# 3. 400 / 404 are not retried; a third failure is raised (3 requests at most)
PLAN["/api/v1/tasks/3"] = [(404, {})]
r, e = run("GET", "/tasks/3")
check(e and e.status == 404 and len(REQS) == 1 and not SLEPT, "404: one request")
PLAN["/api/v1/tasks/4"] = [(429, {"Retry-After": "2"})]
r, e = run("DELETE", "/tasks/4")
check(e and e.status == 429 and len(REQS) == 3 and SLEPT == [2.0, 2.0] and len({q[2] for q in REQS}) == 1, f"three 429: 3 requests, then the error {REQS} {SLEPT}")

# 4. a wait beyond the 60 s budget is not waited for
PLAN["/api/v1/tasks/5/waiting"] = [(429, {"Retry-After": "120"})]
r, e = run("PUT", "/tasks/5/waiting", body={"note": "x"})
check(e and e.status == 429 and len(REQS) == 1 and not SLEPT, "Retry-After 120: raised at once")
PLAN["/api/v1/tasks/6/waiting"] = [(429, {"Retry-After": "40"})]
r, e = run("PUT", "/tasks/6/waiting", body={"note": "x"})
check(e and len(REQS) == 2 and SLEPT == [40.0], f"40 s + 40 s would pass 60 s: one wait, then the error {REQS} {SLEPT}")

# 5. the long poll is never retried
PLAN["/api/v1/agent/events"] = [(429, {"Retry-After": "1"})]
r, e = run("GET", "/agent/events", query={"wait": 5})
check(e and e.status == 429 and len(REQS) == 1 and not SLEPT, "wait_for_events: no retry")

# 6. Idempotency-Key: writes (not /agent/), a new one per call
PLAN.clear()
keys = []
for m, p in (("POST", "/tasks"), ("PATCH", "/tasks/1"), ("PUT", "/tasks/1/waiting"), ("DELETE", "/tasks/1")):
    run(m, p, body={"a": 1})
    keys.append(REQS[0][2])
check(all(keys) and len(set(keys)) == 4, f"every write has its own Idempotency-Key {keys}")
run("GET", "/tasks")
check(REQS[0][2] is None, "a read has no key")
run("POST", "/agent/jobs", body={"title": "x"})
check(REQS[0][2] is None, "a write on the /agent/ channel has no key")

# 7. RateLimit-Remaining 0: the next call waits for the reset
PLAN["/api/v1/me"] = [(200, {"RateLimit-Remaining": "0", "RateLimit-Reset": "7"})]
run("GET", "/me")
check(not SLEPT, "the call that used the last place does not wait")
PLAN["/api/v1/tasks"] = [(200, {"RateLimit-Remaining": "5", "RateLimit-Reset": "7"})]
run("GET", "/tasks")
check(len(SLEPT) == 1 and 5 <= SLEPT[0] <= 7, f"the next call waits for the reset {SLEPT}")
run("GET", "/tasks")
check(not SLEPT, "and then no more")

srv.shutdown()
print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
raise SystemExit(1 if FAILS else 0)
