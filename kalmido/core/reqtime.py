"""2.149.0 B (#2504): measuring instead of guessing. Every request gets its duration, the number of database statements and
their time (core/pg.py counts per thread) as a Server-Timing header (`app;dur=12.3, db;dur=4.1;desc="n=9"`, visible in the
browser's network tab). A request slower than KALMIDO_SLOW_REQUEST_MS (default 500) leaves one log line without user data:
method, route pattern (no ids, no query string), duration, statements, database time. The last REQ_RING requests feed
p50 / p95 / max in GET /api/admin/health (admin/worker.py).

Registered before every other module with request hooks (kalmido/__init__.py ORDER): its before_request runs first and its
after_request last (Flask calls those in reverse order), so the numbers cover the whole request incl. sign-in and gzip.
Not in the ring and never logged as slow: static files, /api/health and long polls that wait on purpose (?wait=)."""
import os
import threading
import time
from collections import deque

from flask import g, request

from ..core.config import app
from ..core.pg import rt_begin, rt_end

try:
    REQ_SLOW_MS = max(0, int(os.environ.get("KALMIDO_SLOW_REQUEST_MS", "") or 500))
except ValueError:
    REQ_SLOW_MS = 500
REQ_RING = 1000
_RING = deque(maxlen=REQ_RING)  # (ms, statements, db ms); append / list() are atomic, the lock only guards a consistent copy
_RLOCK = threading.Lock()


@app.before_request
def rt_in():
    g.rt_t0 = time.perf_counter()
    rt_begin()


def _skip_ring(path):
    return path.startswith("/static/") or path == "/api/health" or (request.args.get("wait") or "0") not in ("", "0")


@app.after_request
def rt_out(resp):
    t0 = g.pop("rt_t0", None)
    st = rt_end()
    if t0 is None:
        return resp
    ms = (time.perf_counter() - t0) * 1000
    n, dbs = st if st else (0, 0.0)
    dbms = dbs * 1000
    if getattr(g, "user", None):  # 2.149.0 review: only for signed-in people (counts would differ on login / reset paths)
        resp.headers["Server-Timing"] = f'app;dur={ms:.1f}, db;dur={dbms:.1f};desc="n={n}"'
    if not _skip_ring(request.path):
        with _RLOCK:
            _RING.append((ms, n, dbms))
        if REQ_SLOW_MS and ms > REQ_SLOW_MS:
            rule = request.url_rule.rule if request.url_rule is not None else "(no route)"
            print(f"slow request: {request.method} {rule} {ms:.0f} ms, {n} statements, db {dbms:.0f} ms", flush=True)
    return resp


@app.teardown_request
def rt_clear(_):
    rt_end()  # an exception without a response: never count into the next request on this thread


def _pct(vals, p):
    return round(vals[min(len(vals) - 1, int(round(p / 100 * (len(vals) - 1))))], 1) if vals else None


def rt_stats():
    """p50 / p95 / max of the last REQ_RING requests (duration, statements, database time). Numbers only."""
    with _RLOCK:
        rows = list(_RING)
    ms, n, dbms = (sorted(r[i] for r in rows) for i in range(3))
    return {"n": len(rows), "slow_ms": REQ_SLOW_MS, "slow": sum(1 for v in ms if REQ_SLOW_MS and v > REQ_SLOW_MS),
            "ms": {"p50": _pct(ms, 50), "p95": _pct(ms, 95), "max": _pct(ms, 100)},
            "statements": {"p50": _pct(n, 50), "p95": _pct(n, 95), "max": _pct(n, 100)},
            "db_ms": {"p50": _pct(dbms, 50), "p95": _pct(dbms, 95), "max": _pct(dbms, 100)}}
