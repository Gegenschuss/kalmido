"""2.622.0 (#3891): short-lived state in the database, so every web process of an instance sees it (later KALMIDO_WEB_PROCS,
KALMIDO_REPLICAS, the roles of 2.102). It replaces the dictionaries in the process memory that broke when step one of a flow
landed in one process and step two in another: sign-in steps (accounts/login.py), OIDC states (accounts/oidc.py), download
tickets, undo tokens, typing / presence markers and short counters.

One table, eph_state (migrations.d/3891_a.py): ns = the kind, k = the key -- stored only as an HMAC of the server key, so a copy
of the database gives no ticket back --, v = the value (callers seal what holds a secret), uid / grp / ip = what a lookup or a cap
goes by (ip as an HMAC too), n = a counter, exp = end (Unix time). An expired row counts as gone at once (every query asks
exp > now) and is deleted by the next pass (at most once a minute per process).

Taking a value once is atomic (DELETE ... RETURNING): two processes never both get it. Every call runs on a short connection of
its own with its own commit (system context: no workspace data, only the instance's own state), so a caller's rollback after a
wrong code never takes the counted try back. A failing database answers "nothing there" (None / 0 / []), never a value."""
import hashlib
import hmac
import secrets
import time

from .db import connect
from .pg import system_ctx
from . import config

EPH_HOUSE_S = 60  # expired rows are deleted at most this often per process
_HOUSE = {"at": 0.0}
_EKEY = {}


def _ekey():
    if config.SECRET_KEY and "k" not in _EKEY:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        _EKEY["k"] = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"kalmido-eph", info=b"eph_state key v1").derive(config.SECRET_KEY)
    return _EKEY.get("k")


def eph_hash(ns, key):
    """The stored form of a key (HMAC with the server key; without one a plain hash, like core/ratedb.py)."""
    s = f"{ns}\x00{key}".encode()
    k = _ekey()
    if k:
        return hmac.new(k, s, hashlib.sha256).hexdigest()[:40]
    return hashlib.sha256(b"kalmido-eph:" + s).hexdigest()[:40]


def _run(fn, fail=None):
    c = None
    try:
        c = connect()
        with system_ctx(c):  # the instance's own short-lived state, no content of a workspace
            now = time.time()
            out = fn(c, now)
            if now - _HOUSE["at"] > EPH_HOUSE_S:
                _HOUSE["at"] = now
                c.execute("DELETE FROM eph_state WHERE exp < ?", (now,))
        c.commit()
        return out
    except Exception as e:  # noqa: BLE001 -- the database is away: nothing there (a sign-in step asks to start again)
        print("ephem:", type(e).__name__, flush=True)
        if c is not None:
            try:
                c.rollback()
            except Exception:  # noqa: BLE001
                pass
        return fail
    finally:
        if c is not None:
            c.close()


def _cap(c, ns, col, val, keep, now):
    """Makes room for one more row of ns with col = val: its oldest give way, so at most `keep` stay with the new one."""
    where, args = ("", ()) if col is None else (f" AND {col}=?", (val,))
    c.execute(f"""DELETE FROM eph_state WHERE ns=? AND k IN (SELECT k FROM eph_state WHERE ns=?{where} AND exp > ?
                  ORDER BY exp DESC OFFSET ?)""", (ns, ns, *args, now, max(0, keep - 1)))


def eph_put(ns, key, value, ttl, uid=None, grp="", ip="", caps=None):
    """Stores value (text) under key for ttl seconds (a row with the same key is replaced, its counter starts at 0).
    caps {"ip": n, "uid": n, "grp": n, "all": n}: before the row goes in, the oldest rows of ns with the same ip / uid / grp
    (or of ns at all) give way so that at most n stay -- many entries of one address never push out those of others.
    True = stored."""
    ih = eph_hash("ip", ip) if ip else ""

    def fn(c, now):
        c.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("eph:" + ns,)).fetchone()  # caps count rows: one writer per kind
        c.execute("DELETE FROM eph_state WHERE ns=? AND exp < ?", (ns, now))
        for dim, n in (caps or {}).items():
            col, val = {"ip": ("ip", ih), "uid": ("uid", uid), "grp": ("grp", grp), "all": (None, None)}[dim]
            if col is None or val not in (None, ""):
                _cap(c, ns, col, val, n, now)
        c.execute("""INSERT INTO eph_state(ns, k, v, uid, grp, ip, n, at, exp) VALUES(?,?,?,?,?,?,0,?,?)
                     ON CONFLICT(ns, k) DO UPDATE SET v=excluded.v, uid=excluded.uid, grp=excluded.grp, ip=excluded.ip, n=0,
                     at=excluded.at, exp=excluded.exp""", (ns, eph_hash(ns, key), value or "", uid, grp or "", ih, now, now + ttl))
        return True
    return bool(_run(fn, False))


def eph_get(ns, key):
    """{"v", "n", "uid", "grp", "exp"} of a live row, else None."""
    def fn(c, now):
        r = c.execute("SELECT v, n, uid, grp, exp FROM eph_state WHERE ns=? AND k=? AND exp > ?", (ns, eph_hash(ns, key), now)).fetchone()
        return {"v": r[0], "n": int(r[1]), "uid": r[2], "grp": r[3], "exp": float(r[4])} if r else None
    return _run(fn)


def eph_set(ns, key, value):
    """New value of a live row (its end stays). True = there was one."""
    return bool(_run(lambda c, now: c.execute("UPDATE eph_state SET v=? WHERE ns=? AND k=? AND exp > ?",
                                              (value or "", ns, eph_hash(ns, key), now)).rowcount, 0))


def eph_take(ns, key, uid=None):
    """The value of a live row, deleted in the same step (at most one caller of all processes gets it), else None. uid given:
    only a row of that account (another account's request leaves the row alone)."""
    def fn(c, now):
        extra, args = ("", ()) if uid is None else (" AND uid=?", (uid,))
        r = c.execute(f"DELETE FROM eph_state WHERE ns=? AND k=? AND exp > ?{extra} RETURNING v",
                      (ns, eph_hash(ns, key), now, *args)).fetchone()
        return r[0] if r else None
    return _run(fn)


def eph_drop(ns, key):
    _run(lambda c, now: c.execute("DELETE FROM eph_state WHERE ns=? AND k=?", (ns, eph_hash(ns, key))).rowcount, 0)


def eph_count_up(ns, key):
    """Counter of a live row plus one: the new count (None = no live row). Atomic: two wrong codes at once count two."""
    def fn(c, now):
        r = c.execute("UPDATE eph_state SET n=n+1 WHERE ns=? AND k=? AND exp > ? RETURNING n", (ns, eph_hash(ns, key), now)).fetchone()
        return int(r[0]) if r else None
    return _run(fn)


def eph_group(ns, grp):
    """[{"uid", "v", "exp"}] of the live rows of a group (typing in one task, presence in one table), oldest first."""
    def fn(c, now):
        return [{"uid": r[0], "v": r[1], "exp": float(r[2])} for r in
                c.execute("SELECT uid, v, exp FROM eph_state WHERE ns=? AND grp=? AND exp > ? ORDER BY at, k", (ns, str(grp), now))]
    return _run(fn, [])


def eph_add(ns, grp, n, ttl, key=None):
    """A counter over a sliding window: one row of n for grp that lives ttl seconds; the answer is the sum of the live rows of
    grp with this one (None = the count failed). key: the row's own name (default: unique per call)."""
    def fn(c, now):
        c.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("eph:" + ns + ":" + str(grp),)).fetchone()
        k = key if key is not None else f"{grp}:{secrets.token_hex(12)}"
        c.execute("""INSERT INTO eph_state(ns, k, grp, n, at, exp) VALUES(?,?,?,?,?,?)
                     ON CONFLICT(ns, k) DO UPDATE SET n=eph_state.n+excluded.n, exp=excluded.exp""",
                  (ns, eph_hash(ns, k), str(grp), int(n), now, now + ttl))
        return int(c.execute("SELECT COALESCE(SUM(n), 0) FROM eph_state WHERE ns=? AND grp=? AND exp > ?", (ns, str(grp), now)).fetchone()[0])
    return _run(fn)


def eph_total(ns, grp):
    """The sum of the live rows of grp (eph_add without adding); 0 when the count fails."""
    return _run(lambda c, now: int(c.execute("SELECT COALESCE(SUM(n), 0) FROM eph_state WHERE ns=? AND grp=? AND exp > ?",
                                             (ns, str(grp), now)).fetchone()[0]), 0)


def eph_clear(ns=None):
    """Every row of a kind, or every row at all (the restore of a backup: no ticket of before survives it)."""
    if ns is None:
        _run(lambda c, now: c.execute("DELETE FROM eph_state").rowcount, 0)
    else:
        _run(lambda c, now: c.execute("DELETE FROM eph_state WHERE ns=?", (ns,)).rowcount, 0)
