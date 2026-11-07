"""2.622.0 (#3891): signals between the processes of one instance over Postgres' LISTEN / NOTIFY (no new service, no new
dependency). What a process keeps in memory and another process changes -- a setting it caches, an event a waiting agent
should hear, work for the process that runs a queue -- is told to the others with bus_send(name, data); every process that
registered bus_on(name, fn) calls fn(data) in its listener thread.

Only when there are other processes (KALMIDO_REPLICAS > 1 or the roles web / worker of 2.102; KALMIDO_PGBUS=1 / 0 forces
it on / off): a single process does its own step itself and sends nothing, as before.
The sender always does its own step locally first; a process never handles its own signal again. bus_send(..., c=conn) puts the
signal into that connection's transaction: Postgres delivers it with the commit (a rollback sends nothing), so the others never
hear of a row they cannot read yet. A lost listener connection is opened again; since signals of that gap are lost, every
handler is called once with data None ("something may have changed": caches drop what they hold, waiters look again).
Payloads stay small (Postgres allows 8000 bytes): ids and names, never content or secrets."""
import json
import os
import secrets
import threading
import time

from . import config
from .db import connect
from .pg import connect_listen

BUS_CHANNEL = "kalmido_bus"
BUS_MAX = 7000          # bytes of one payload (Postgres: below 8000)
BUS_WAIT_S = 30         # the listener checks its connection at least this often
BUS_RETRY_S = 5         # after a lost connection
BUS_ME = f"{os.getpid()}.{secrets.token_hex(4)}"  # this process (a pid alone may come back in another container)
_HANDLERS = {}          # name -> [fn(data)]
_BUS = {"thread": None, "up": False, "heard": 0, "sent": 0}
_BLK = threading.Lock()


def _env_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def bus_active():
    """True when this instance may run more than one process (then the signals are needed)."""
    f = os.environ.get("KALMIDO_PGBUS", "").strip().lower()
    if f in ("1", "on", "true", "yes"):
        return True
    if f in ("0", "off", "false", "no"):
        return False
    role = (os.environ.get("KALMIDO_ROLE", "") or "all").strip().lower()
    return role in ("web", "worker") or _env_int("KALMIDO_REPLICAS", 1) > 1


def bus_on(name, fn):
    """fn(data) runs in every OTHER process when one of them sends `name` (and with None after a lost connection)."""
    with _BLK:
        _HANDLERS.setdefault(name, []).append(fn)
    bus_start()


def bus_start():
    if not bus_active() or not config.DATABASE_URL:
        return
    with _BLK:
        t = _BUS["thread"]
        if t is not None and t.is_alive():
            return
        _BUS["thread"] = threading.Thread(target=_listen, daemon=True, name="pgbus")
        _BUS["thread"].start()


def bus_send(name, data=None, c=None):
    """Tells the other processes; c: inside that connection's transaction (goes with its commit). Nothing without other
    processes. Never raises: a lost signal costs a cache its freshness or a waiter its wake-up (both have a time limit)."""
    if not bus_active():
        return False
    body = json.dumps({"n": name, "d": data, "f": BUS_ME}, ensure_ascii=False, separators=(",", ":"))
    if len(body.encode()) > BUS_MAX:
        body = json.dumps({"n": name, "d": None, "f": BUS_ME})  # too long: "something changed" (handlers treat None like a gap)
    try:
        if c is not None:
            c.execute("SELECT pg_notify(?, ?)", (BUS_CHANNEL, body)).fetchone()
        else:
            c2 = connect()
            try:
                c2.execute("SELECT pg_notify(?, ?)", (BUS_CHANNEL, body)).fetchone()
                c2.commit()
            finally:
                c2.close()
        _BUS["sent"] += 1
        return True
    except Exception as e:  # noqa: BLE001
        print("pgbus: send failed", type(e).__name__, flush=True)
        return False


def _call(name, data):
    for fn in list(_HANDLERS.get(name, ())):
        try:
            fn(data)
        except Exception as e:  # noqa: BLE001 -- one handler's error never stops the listener
            print("pgbus: handler", name, type(e).__name__, flush=True)


def bus_dispatch(payload):
    """Handles one received payload (the listener; tests call it directly). Own signals and unknown names are skipped."""
    try:
        m = json.loads(payload)
    except (TypeError, ValueError):
        return False
    if not isinstance(m, dict) or m.get("f") == BUS_ME or not isinstance(m.get("n"), str):
        return False
    _BUS["heard"] += 1
    _call(m["n"], m.get("d"))
    return True


def _listen():
    gap = False
    while True:
        pg = None
        try:
            pg = connect_listen(config.DATABASE_URL)
            pg.execute(f"LISTEN {BUS_CHANNEL}")
            _BUS["up"] = True
            if gap:  # signals of the gap are lost: every handler looks again
                for name in list(_HANDLERS):
                    _call(name, None)
            gap = True
            while True:
                for n in pg.notifies(timeout=BUS_WAIT_S):
                    bus_dispatch(n.payload)
                pg.execute("SELECT 1")  # a dead connection fails here, not silently in notifies()
        except Exception as e:  # noqa: BLE001
            if _BUS["up"]:
                print("pgbus: listener connection lost", type(e).__name__, "- connecting again", flush=True)
            _BUS["up"] = False
            try:
                if pg is not None:
                    pg.close()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(BUS_RETRY_S)


def bus_stats():
    """For the health view: on / listening / heard / sent."""
    return {"on": bus_active(), "listening": bool(_BUS["up"]), "heard": _BUS["heard"], "sent": _BUS["sent"]}
