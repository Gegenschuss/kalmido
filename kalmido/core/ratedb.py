"""2.306.0 D1 (#2875): the rate limits that guard rare, sensitive actions (sign-in failures, invitations, set-up code, the
hourly / daily budgets: windows of RATE_SHARED_MIN_S and more) are counted in the database, so n web processes of one
instance (KALMIDO_REPLICAS, the roles of 2.102) share one count instead of n. The short per-minute load limits stay in each
process's memory (a write per request would cost more than they save). Keys are stored as a hash only; rows go after a day.
A failed count never locks anybody out: the callers keep their own count in memory and use it alone then.
2.312.0 C (#3265): the addresses an account signed in from (accounts/session.py h6a_uall_exempt) are shared the same way
(rate_known: hashes, gone after KNOWN_DAYS)."""
import hashlib
import hmac
import time

from .db import connect
from .pg import system_ctx

RATE_SHARED_MIN_S = 600   # a limit over at least this many seconds is counted for every process
RATE_KEEP_S = 86400 + 60  # the longest window of a shared limit (a day) and a little
_HOUSE = {"at": 0.0}
_HKEY = {}


def _hkey():
    """2.306.0 Fix-1 (#2875 review): the keys' hash key from the server key (HKDF like the queue's, accounts/bgjobs.py), so a
    copy of the database alone does not give the addresses and names back; without a server key a plain hash as before."""
    from . import config
    if config.SECRET_KEY and "k" not in _HKEY:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        _HKEY["k"] = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"kalmido-rate", info=b"rate_hits key v1").derive(config.SECRET_KEY)
    return _HKEY.get("k")


def _h(k):
    key = _hkey()
    if key:
        return hmac.new(key, k.encode(), hashlib.sha256).hexdigest()[:32]
    return hashlib.sha256(("kalmido-rate:" + k).encode()).hexdigest()[:32]


def _house(c, now):
    if now - _HOUSE["at"] > 60:
        _HOUSE["at"] = now
        c.execute("DELETE FROM rate_hits WHERE at < ?", (now - RATE_KEEP_S,))


def _run(fn):
    c = None
    try:
        c = connect()
        with system_ctx(c):  # the instance's own counters (hashes and times), no content of a workspace
            out = fn(c, time.time())
        c.commit()
        return out
    except Exception as e:  # noqa: BLE001 -- no count = only the process's own count (never locked out by an error)
        print("ratedb:", type(e).__name__, flush=True)
        if c is not None:
            try:
                c.rollback()
            except Exception:  # noqa: BLE001
                pass
        return None
    finally:
        if c is not None:
            c.close()


def _lock(c, hs):
    for h in sorted(set(hs)):  # one order for every process (no deadlock between two keys)
        c.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("rate:" + h,)).fetchone()


def _count(c, h, since):
    return int(c.execute("SELECT COUNT(*) FROM rate_hits WHERE k=? AND at > ?", (h, since)).fetchone()[0])


def rate_hit(key, limit, window):
    """hit_limit over every process: True = refuse (limit hits in the window; the refused one is not counted), False = counted,
    None = the count failed."""
    def fn(c, now):
        h = _h(key)
        _lock(c, [h])
        if _count(c, h, now - window) >= limit:
            return True
        c.execute("INSERT INTO rate_hits(k, at) VALUES(?,?)", (h, now))
        _house(c, now)
        return False
    return _run(fn)


def rate_counts(keys, window, add=False, cap=None):
    """{key: hits in the window} over every process (add: one hit per key first, e.g. a failed sign-in); None = failed.
    2.306.0 Fix-1 (#2875 review): cap {key: n}: a key with n hits in the window gets no further rows (a flood on one key
    neither grows the table nor makes its count slower; the limit is long reached)."""
    def fn(c, now):
        hs = {k: _h(k) for k in keys}
        if add:
            _lock(c, hs.values())
            for k, h in hs.items():
                if cap and k in cap and _count(c, h, now - window) >= cap[k]:
                    continue
                c.execute("INSERT INTO rate_hits(k, at) VALUES(?,?)", (h, now))
            _house(c, now)
        return {k: _count(c, h, now - window) for k, h in hs.items()}
    return _run(fn) if keys else {}


def rate_clear(key):
    """A successful sign-in forgets the failures of this pair for every process."""
    return _run(lambda c, now: c.execute("DELETE FROM rate_hits WHERE k=?", (_h(key),)).rowcount)


RATE_KNOWN_MAX = 20  # 2.312.0 C (#3265): addresses kept per account (as the process memory keeps)
_HOUSE_KNOWN = {"at": 0.0}


def _hk(key, addr):
    return _h("known:" + key), _h("known:" + key + "@" + addr)


def rate_known_add(key, addr, days):
    """2.312.0 C (#3265): remembers a successful sign-in of key ("<pre>uall:<name>") from addr for every process (the newest
    RATE_KNOWN_MAX addresses per key, none older than days)."""
    def fn(c, now):
        u, a = _hk(key, addr)
        c.execute("INSERT INTO rate_known(u, a, at) VALUES(?,?,?) ON CONFLICT(u, a) DO UPDATE SET at=excluded.at", (u, a, now))
        c.execute("DELETE FROM rate_known WHERE u=? AND a NOT IN (SELECT a FROM rate_known WHERE u=? ORDER BY at DESC LIMIT ?)",
                  (u, u, RATE_KNOWN_MAX))
        if now - _HOUSE_KNOWN["at"] > 3600:
            _HOUSE_KNOWN["at"] = now
            c.execute("DELETE FROM rate_known WHERE at < ?", (now - days * 86400,))
        return True
    return _run(fn)


def rate_known_at(key, addr):
    """2.312.0 C (#3265): the Unix time of the last successful sign-in of key from addr in any process (0 = none, None = the
    look-up failed)."""
    def fn(c, now):
        u, a = _hk(key, addr)
        r = c.execute("SELECT at FROM rate_known WHERE u=? AND a=?", (u, a)).fetchone()
        return float(r[0]) if r else 0.0
    return _run(fn)
