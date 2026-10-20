"""2.102.0 D (#1994): the server's capacity in numbers. Waitress threads per env (KALMIDO_THREADS, core/pg.py WEB_THREADS), the
pool follows them; a start-up warning when KALMIDO_REPLICAS x the pool would exceed Postgres' max_connections; and
GET /api/admin/health for the instance's admins: pool counters, busy threads, version, role -- numbers only, no user data.

2.102.0 D (#1997): process roles. KALMIDO_ROLE=all (default: web + background loops, as before), web (requests only, no
loop runs here) or worker (`python app.py worker`: the loops only, no web server). Every background loop -- the start-up
ones (watchdog, calendars, backups, webhooks, mail, git, ntfy inbox, update check) and the queues started on demand (file
text, documents, Paperless, embeddings) -- runs in ONE process of the instance at a time: before each round it holds a
session-level pg_try_advisory_lock of its own (one connection per process keeps them), also in the role "all", so two
replicas never push, mail or back up twice. The queues work from their tables, so a web process needs no signal of its own:
the worker picks new rows up on its next round.
"""
import json
import os
import threading
import time

from flask import g, jsonify

from ..core.config import app, APP_VERSION, DATABASE_URL
from ..core.db import connect, db, gset, gsetting, iso, now_utc
from ..core.pg import POOL_MAX, WEB_THREADS, connect_direct, pool_stats
from ..accounts.session import _BG_TURN, GATE
from ..accounts.users import need_admin

try:
    WRK_REPLICAS = max(1, int(os.environ.get("KALMIDO_REPLICAS", "") or 1))
except ValueError:
    WRK_REPLICAS = 1
WRK_CONN_EXTRA = 6  # direct connections outside the pool per process (start-up, loop locks, backup, CLI)
WRK_CONN_RESERVE = 5  # left for an operator's psql / pg_dump
_BUSY = {"n": 0, "peak": 0, "served": 0, "since": time.time()}
_BLK = threading.Lock()
WRK_ROLE = (os.environ.get("KALMIDO_ROLE", "") or "all").strip().lower()
if WRK_ROLE not in ("all", "web", "worker"):
    print(f"warning: KALMIDO_ROLE={WRK_ROLE!r} is not all / web / worker; using all", flush=True)
    WRK_ROLE = "all"
WRK_LOCKS_ON = os.environ.get("KALMIDO_LOOP_LOCKS", "1") != "0"  # 0 = every process runs its loops (the behaviour before 2.102)
WRK_LOCK_CLASS = 21020  # first key of the two-key advisory locks (a key space of its own next to write_lock's one-key locks)
WRK_RETRY_S = 15  # a loop another process runs: asks again after this
WRK_PING_S = 15  # the lock connection is checked at most this often
WRK_HB_S = max(5, int(os.environ.get("KALMIDO_WORKER_HEARTBEAT", "") or 30))
# the threads (by name) that take a loop lock: startup.py's loops + the queues their modules start on demand
WRK_LAZY = ("filetext", "docs", "paperless", "paperless-zipcheck", "embed")
WRK_LOOPS = {"watchdog", "update-check", "calendars", "backup", "webhooks", "mail-in", "git", "ntfy-inbox", "ntfy-inbox-users", *WRK_LAZY}
_HELD = set()
_STATE = {}  # loop name -> "running" (this process holds its lock) / "waiting" (another process runs it) / "web"
_LCONN = {"c": None, "checked": 0.0}
_LLK = threading.Lock()


def wrk_hold(name):
    """True when this process holds the loop's lock (takes it when free). A lost lock connection drops every lock of the
    process with it (Postgres releases them): they are taken again, or another process has them by then."""
    if not WRK_LOCKS_ON:
        return True
    with _LLK:
        c = _LCONN["c"]
        try:
            now = time.time()
            if c is not None and now - _LCONN["checked"] > WRK_PING_S:
                c.execute("SELECT 1").fetchone()
                c.commit()
                _LCONN["checked"] = now
            if name in _HELD:
                return True
            if c is None:
                c = _LCONN["c"] = connect_direct(DATABASE_URL)
                _LCONN["checked"] = now
            ok = c.execute("SELECT pg_try_advisory_lock(?, hashtext(?))", (WRK_LOCK_CLASS, "loop:" + name)).fetchone()[0]
            c.commit()  # session-level: the lock outlives the transaction (no idle transaction for the 5-minute limit)
            if ok:
                _HELD.add(name)
            return bool(ok)
        except Exception as e:  # noqa: BLE001 - the database is away: no loop runs until it is back
            if _HELD:
                print("background loops: lost the lock connection", type(e).__name__, "- taking them again", flush=True)
            _HELD.clear()
            for k, v in list(_STATE.items()):
                if v == "running":
                    _STATE[k] = "waiting"
            if c is not None:
                try:
                    c.close()
                except Exception:  # noqa: BLE001
                    pass
            _LCONN["c"] = None
            return False


def wrk_release(name):
    """Gives the loop's lock back (its thread ended)."""
    _STATE[name] = "stopped"
    if not WRK_LOCKS_ON:
        return
    with _LLK:
        if name not in _HELD or _LCONN["c"] is None:
            return
        _HELD.discard(name)
        try:
            _LCONN["c"].execute("SELECT pg_advisory_unlock(?, hashtext(?))", (WRK_LOCK_CLASS, "loop:" + name)).fetchone()
            _LCONN["c"].commit()
        except Exception as e:  # noqa: BLE001 - a lost connection released it already
            print("background loops: unlock", name, type(e).__name__, flush=True)


def wrk_turn():
    """GATE.bg() calls this first: in a loop thread it waits until this process may run the loop's round."""
    name = threading.current_thread().name
    if name not in WRK_LOOPS:
        return
    if WRK_ROLE == "web":  # a queue a request started here: the worker runs it, this thread stays asleep
        _STATE[name] = "web"
        while True:
            time.sleep(3600)
    while not wrk_hold(name):  # (held: a set lookup, the connection checked at most every WRK_PING_S)
        if _STATE.get(name) != "waiting":
            _STATE[name] = "waiting"
        time.sleep(WRK_RETRY_S)
    _STATE[name] = "running"


_BG_TURN["f"] = wrk_turn


def wrk_start(name, fn, *args):
    """startup.py: a background loop in a thread of that name; its first round waits for the loop's lock."""
    WRK_LOOPS.add(name)
    _STATE[name] = "waiting"

    def run():
        try:
            wrk_turn()
            fn(*args)
        finally:  # 2.102.0 review F8: a loop that died gives its lock back, another process may take the loop over
            wrk_release(name)
    threading.Thread(target=run, daemon=True, name=name).start()


def wrk_loops():
    return dict(sorted(_STATE.copy().items()))


def _wrk_heartbeat():
    """The worker writes what it runs every WRK_HB_S seconds (setting wrk_heartbeat); the web's health check shows it."""
    while True:
        try:
            with GATE.bg():
                c = connect()
                try:
                    gset(c, "wrk_heartbeat", json.dumps({"at": iso(now_utc()), "version": APP_VERSION, "loops": wrk_loops()}))
                    c.commit()
                finally:
                    c.close()
        except Exception as e:  # noqa: BLE001
            print("worker heartbeat:", type(e).__name__, e, flush=True)
        time.sleep(WRK_HB_S)


def wrk_main():
    """`python app.py worker` (KALMIDO_ROLE=worker): startup.py has started the loops; this starts the queues a web process
    would start on its first request, the heartbeat, and keeps the process alive (no web server)."""
    from ..files.textscan import ts_kick
    from ..docs.ingest import docs_kick
    from ..paperless.ngx import pl_kick
    from ..tasks.related import emb_kick
    for kick in (ts_kick, docs_kick, pl_kick, emb_kick):
        try:
            kick()
        except Exception as e:  # noqa: BLE001
            print("worker: could not start", kick.__name__, type(e).__name__, e, flush=True)
    threading.Thread(target=_wrk_heartbeat, daemon=True, name="worker-heartbeat").start()
    print(f"Kalmido {APP_VERSION} worker: background loops only (no web server); loops:", ", ".join(sorted(_STATE)), flush=True)
    stop = threading.Event()
    while not stop.wait(3600):
        pass


@app.before_request
def wrk_req_in():
    g.wrk_busy = True
    with _BLK:
        _BUSY["n"] += 1
        _BUSY["peak"] = max(_BUSY["peak"], _BUSY["n"])
    return None


@app.teardown_request
def wrk_req_out(_):
    if g.pop("wrk_busy", False):
        with _BLK:
            _BUSY["n"] -= 1
            _BUSY["served"] += 1


def wrk_conn_budget(c):
    """Postgres' max_connections against what the replicas may open (pool + direct connections each)."""
    mx = int(c.execute("SHOW max_connections").fetchone()[0])
    su = int(c.execute("SHOW superuser_reserved_connections").fetchone()[0])
    need = WRK_REPLICAS * (POOL_MAX + WRK_CONN_EXTRA)
    room = mx - su - WRK_CONN_RESERVE
    return {"max_connections": mx, "reserved": su + WRK_CONN_RESERVE, "replicas": WRK_REPLICAS, "need": need, "ok": need <= room}


def wrk_conn_check():
    """At the start: warn in the log when the replicas could open more connections than Postgres allows."""
    c = connect()
    try:
        b = wrk_conn_budget(c)
        if not b["ok"]:
            print(f"WARNING database connections: {b['replicas']} replica(s) x (pool {POOL_MAX} + {WRK_CONN_EXTRA}) = {b['need']} "
                  f"but Postgres allows {b['max_connections']} ({b['reserved']} reserved). Raise max_connections or lower "
                  "KALMIDO_DB_POOL_MAX / KALMIDO_THREADS (see SELF-HOSTING).", flush=True)
    except Exception as e:  # noqa: BLE001 - a check never stops the start
        print("connection budget check skipped:", type(e).__name__, e, flush=True)
    finally:
        c.close()


def wrk_health(c):
    with _BLK:
        busy = dict(_BUSY)
    hb = None
    try:
        hb = json.loads(gsetting(c, "wrk_heartbeat") or "null")
    except ValueError:
        pass
    if isinstance(hb, dict) and hb.get("at"):
        try:
            from ..core.db import parse_iso
            hb["age_s"] = int((now_utc() - parse_iso(hb["at"])).total_seconds())
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "version": APP_VERSION, "role": WRK_ROLE, "loop_locks": WRK_LOCKS_ON, "loops": wrk_loops(),
            "worker": hb if isinstance(hb, dict) else None,
            "threads": {"configured": WEB_THREADS, "busy": busy["n"], "peak": busy["peak"], "served": busy["served"],
                        "since_s": int(time.time() - busy["since"])},
            "pool": pool_stats(), "connections": wrk_conn_budget(c)}


@app.get("/api/admin/health")
def admin_health():
    """Admins of the server: capacity numbers (pool, threads, connections, role, background loops). No user data."""
    need_admin()
    return jsonify(wrk_health(db()))
