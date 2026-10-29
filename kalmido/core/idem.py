"""2.270.0 C (#3022): idempotency keys of write requests (header Idempotency-Key).

The offline queue (static/js/core.js) and the service worker (static/sw.js) send the queue entry's key `k` with every
replay, agents may send their own key per call (API v1). The first request with a key claims it: a row in idem_keys in
the SAME transaction as the request's effect (effect and key are committed together; a request that fails and does not
commit leaves no row). A 2xx answer is stored with the row. A repeat of the key (same person, method and path) gets the
stored answer back (header Idempotent-Replayed: true) and changes nothing -- the service worker that was stopped before it
could drop the entry, the tab that sends it again, an agent's retry after a lost answer.

Never swallows an effect: only a stored 2xx answer is replayed. A row without an answer (the first request still running:
waited for a moment; or it committed and then failed) lets the repeat run as before and the new 2xx answer is stored.
Without the header nothing changes. Keys older than IDEM_DAYS (14, 2.380 H #3387) go when the same person claims a new key.
"""
import json
import re
import time
from datetime import timedelta

from flask import Response, g, request

from .config import app
from .db import connect, db, iso, now_utc

IDEM_HEADER = "Idempotency-Key"
IDEM_DAYS = 14  # 2.380 H (#3387): as long as the offline queue lives (a change sent after days is no false conflict)
IDEM_MAX_BODY = 256 * 1024  # bytes of a stored answer; a larger one is replayed as {"ok": true}
IDEM_WAIT = 3.0  # s: a repeat that arrives while the first request is still running waits this long for its answer
_IDEM_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
_IDEM_METHODS = ("POST", "PATCH", "PUT", "DELETE")


def _idem_key():
    if request.method not in _IDEM_METHODS or not request.path.startswith("/api/"):
        return None
    k = (request.headers.get(IDEM_HEADER) or "").strip()
    u = getattr(g, "user", None)
    return k if k and _IDEM_KEY.match(k) and u is not None else None


def _idem_replay(r):
    body = r["body"]
    resp = Response(body if body is not None else json.dumps({"ok": True}), int(r["status"]), mimetype="application/json")
    if int(r["status"]) == 204:
        resp = Response(status=204)
    resp.headers["Idempotent-Replayed"] = "true"
    return resp


@app.before_request
def idem_claim():
    k = _idem_key()
    if not k:
        return None
    c, uid, ts = db(), g.user["id"], now_utc()
    c.execute("DELETE FROM idem_keys WHERE user_id=? AND created_at<?", (uid, iso(ts - timedelta(days=IDEM_DAYS))))
    # a second request with the same key waits here until the first one commits or rolls back (the row's lock)
    if c.execute("INSERT INTO idem_keys(user_id, k, method, path, created_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING RETURNING k",
                 (uid, k, request.method, request.path, iso(ts))).fetchone():
        g.idem_k = k
        return None
    end = time.monotonic() + IDEM_WAIT
    while True:
        r = c.execute("SELECT method, path, status, body FROM idem_keys WHERE user_id=? AND k=?", (uid, k)).fetchone()
        if r is None or (r["method"], r["path"]) != (request.method, request.path):
            return None  # gone meanwhile / the key of another call: runs as without a key
        if r["status"] is not None:
            return _idem_replay(r)
        if time.monotonic() > end:
            g.idem_k = k  # committed without an answer (failed after its commit): runs again, its answer is stored
            return None
        time.sleep(0.1)


@app.after_request
def idem_store(resp):
    """Stores a 2xx answer with the key -- on a connection of its own, and only when the claim row is committed (the request's
    effect then is too). The request's own transaction is never committed here: a claim it did not commit is locked by it
    (skipped) and goes with its rollback."""
    k = g.pop("idem_k", None)
    if not k or getattr(g, "user", None) is None:
        return resp
    ok, body = 200 <= resp.status_code < 300, None
    if ok and not resp.direct_passthrough and not resp.is_streamed and "json" in (resp.content_type or ""):
        data = resp.get_data()
        body = data.decode("utf-8", "replace") if len(data) <= IDEM_MAX_BODY else None
    c = None
    try:
        c = connect()
        if c.execute("SELECT 1 FROM idem_keys WHERE user_id=? AND k=? AND status IS NULL FOR UPDATE SKIP LOCKED", (g.user["id"], k)).fetchone():
            if ok:
                c.execute("UPDATE idem_keys SET status=?, body=? WHERE user_id=? AND k=?", (resp.status_code, body, g.user["id"], k))
            else:  # committed and then failed: the key is free again
                c.execute("DELETE FROM idem_keys WHERE user_id=? AND k=?", (g.user["id"], k))
        c.commit()
    except Exception as e:  # noqa: BLE001  (the answer goes out anyway; a repeat then runs as without a key)
        print(f"idempotency key not stored: {e!r}", flush=True)
    finally:
        if c is not None:
            c.close()
    return resp
