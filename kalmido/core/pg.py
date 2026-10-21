"""2.37.0 (#1150): the Postgres driver layer. The only module that imports psycopg; everything else talks to the database through
connect() / db() (core/db.py) and gets a Conn back that behaves like the sqlite3 connection the code was written for:

- `?` placeholders (translated to psycopg's `%t` outside string literals / identifiers / comments; a `%` is doubled),
- rows that answer to an index, a column name (case-insensitive, like the SQLite driver's rows), .keys() and dict(row),
- execute() returns the cursor (fetchone / fetchall / iteration / rowcount), commit() / rollback() / close(),
- parameters typed like SQLite's loose typing: ints / bools go as untyped literals (Postgres infers the column's type, so
  `text_col = 5` and `bigint_col = '5'` both work; True / False are stored as 1 / 0), NUMERIC comes back as int / float
  (exact storage, the office calculator works in Decimal on str(value)), jsonb comes back as its JSON text.

There is no lastrowid on the cursor: an INSERT that needs its id says so with insert_id() (RETURNING id).
Request context (#1142 / RLS): set_ctx() stores (user_id, org_ids, role); it is applied with SET LOCAL semantics
(set_config(..., true)) at the start of every transaction, so it survives commit() and never leaks into the next request that
borrows the same pooled connection. Background threads, init_db and the CLI get role "system".
Inside a request the context hook (core/access.py) derives it per transaction from g.user ("user" / "agent", or "anon" without
an account); system_ctx(c) is the one deliberate way to read across organisations (row-level security, core/rls.py).
"""
import contextlib
import functools
import itertools
import os
import re
import threading
import time

import psycopg
from psycopg import adapt, errors as pgerrors  # noqa: F401  (pgerrors: specific SQLSTATE classes for callers)
from psycopg.pq import TransactionStatus
from psycopg.types.string import TextLoader
from psycopg_pool import ConnectionPool, PoolTimeout

Error = psycopg.Error
DatabaseError = psycopg.DatabaseError
DataError = psycopg.DataError
IntegrityError = psycopg.IntegrityError
OperationalError = psycopg.OperationalError
ProgrammingError = psycopg.ProgrammingError
UniqueViolation = pgerrors.UniqueViolation


_IS_NULL = re.compile(r"\s+IS\s+(NOT\s+)?NULL\b", re.I)


# --- placeholders ------------------------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=4096)
def translate(sql):
    """`?` -> `%t` outside quotes / comments, every `%` -> `%%` (psycopg reads % everywhere, also inside literals)."""
    out, i, n = [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):  # string literal / quoted identifier ('' and "" escape themselves)
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i:j + 1].replace("%", "%%"))
            i = j + 1
        elif ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(sql[i:j].replace("%", "%%"))
            i = j
        elif ch == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(sql[i:j].replace("%", "%%"))
            i = j
        elif ch == "$" and (m := _dollar_tag(sql, i)):  # $tag$ ... $tag$ (function bodies)
            j = sql.find(m, i + len(m))
            j = n if j < 0 else j + len(m)
            out.append(sql[i:j].replace("%", "%%"))
            i = j
        elif ch == "?":
            # `? IS NULL` alone gives Postgres no type for the parameter: compare its text form
            out.append("%t::text" if _IS_NULL.match(sql, i + 1) else "%t")
            i += 1
        elif ch == "%":
            out.append("%%")
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _dollar_tag(sql, i):
    j = i + 1
    while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
        j += 1
    if j < len(sql) and sql[j] == "$" and not sql[i + 1:j][:1].isdigit():
        return sql[i:j + 1]
    return None


# --- rows --------------------------------------------------------------------------------------------------------------
class Row(tuple):
    """A row like the SQLite driver's: r[0], r["col"] (case-insensitive), r.keys(), dict(r)."""
    __slots__ = ()
    _keys = ()
    _idx = {}

    def __getitem__(self, k):
        if isinstance(k, str):
            try:
                return tuple.__getitem__(self, self._idx[k])
            except KeyError:
                try:
                    return tuple.__getitem__(self, self._idx[k.lower()])
                except KeyError:
                    raise IndexError(f"No item with that key: {k}") from None
        return tuple.__getitem__(self, k)

    def keys(self):
        return list(self._keys)

    def get(self, k, default=None):  # convenience (sqlite3.Row has none; harmless)
        try:
            return self[k]
        except IndexError:
            return default


@functools.lru_cache(maxsize=2048)
def _row_class(names):
    idx = {}
    for i, k in enumerate(names):
        idx.setdefault(k, i)
        idx.setdefault(k.lower(), i)
    return type("Row", (Row,), {"__slots__": (), "_keys": names, "_idx": idx})


def _row_factory(cursor):
    desc = cursor.description
    if desc is None:
        return tuple
    cls = _row_class(tuple(d.name for d in desc))
    return cls


# --- adapters: SQLite-like loose typing --------------------------------------------------------------------------------
class _IntUnknown(adapt.Dumper):
    oid = 0  # untyped literal: Postgres infers the type from the context (text or bigint column, LIMIT, arithmetic)

    def dump(self, obj):
        return str(int(obj)).encode()


class _NumLoader(adapt.Loader):
    """NUMERIC (SUM of bigint, office amounts) -> int when whole, else float (what SQLite returned)."""

    def load(self, data):
        s = bytes(data).decode()
        if "." not in s and "e" not in s.lower() and s not in ("NaN", "Infinity", "-Infinity"):
            return int(s)
        f = float(s)
        return f


def _adapters():
    am = adapt.AdaptersMap(psycopg.adapters)
    am.register_dumper(bool, _IntUnknown)
    am.register_dumper(int, _IntUnknown)
    am.register_loader("numeric", _NumLoader)
    am.register_loader("jsonb", TextLoader)
    am.register_loader("json", TextLoader)
    return am


ADAPTERS = _adapters()


# --- connection wrapper ------------------------------------------------------------------------------------------------
SYSTEM = (None, (), "system")
LOOKUP = object()  # context hook answer: "read the memberships first" (see Conn._resolve_ctx)
_CTX_HOOK = [None]
# 2.149.0 B (#2504): per thread [statements, seconds in the database] of the running request (core/reqtime.py); None = not counted
# (background threads, start-up, CLI). Thread-local, so no lock: a request runs on one waitress thread.
_RT = threading.local()


def rt_begin():
    _RT.s = [0, 0.0]


def rt_end():
    """The counters of this thread's request ([n, seconds] or None); counting stops."""
    st = getattr(_RT, "s", None)
    _RT.s = None
    return st


def rt_peek():
    return getattr(_RT, "s", None)


def set_ctx_hook(fn):
    """2.37.0 (#1150, W-2): register the function that derives the context of a transaction from the request
    (core/access.py acx_conn_hook). fn(None) -> context tuple | None | LOOKUP; fn(conn) -> context tuple (may query conn)."""
    _CTX_HOOK[0] = fn


@contextlib.contextmanager
def system_ctx(c):
    """2.37.0 (#1150): run the block with app.role = 'system' (row-level security lets it see and write every
    organisation's rows), then restore the previous context -- also after an exception. Greppable on purpose: use it only
    where the app deliberately works across organisations (resolving a public token, counting for the admin overview,
    creating an organisation, accepting an invitation) and never to hand content of foreign organisations to a person."""
    # 2.149.0 C (#2508): set_config only when the context really changes. Inside a running transaction c._ctx is what
    # the database holds, so a nested block (or one entered while "system" already) applies nothing, and an idle
    # connection opens its transaction with "system" directly; a request context the hook would have chosen first is
    # resolved by the next statement after the block, as before.
    same = c._ctx == SYSTEM and c._pg.info.transaction_status == TransactionStatus.INTRANS
    if not c._sys:
        c._sys_prev = c._ctx
    c._sys += 1
    c._ctx = SYSTEM
    if not same:
        c._apply_ctx()
    try:
        yield c
    finally:
        c._sys -= 1
        if not c._sys:
            c._ctx, c._sys_prev = c._sys_prev, None
            if not c.closed and not c._pg.closed and c._pg.info.transaction_status == TransactionStatus.INTRANS \
                    and c._ctx != SYSTEM:
                c._apply_ctx()  # same transaction goes on: back to the caller's context (aborted / ended: next _begin)


class Conn:
    """What the app calls a database connection (one per request / background task)."""

    def __init__(self, pg, release=None):
        self._pg = pg
        self._release = release
        self._ctx = SYSTEM
        self._sys, self._sys_prev, self._resolving = 0, None, False  # system_ctx() nesting / the context hook running
        self._auto = release is not None  # pooled connections follow the request (hook); direct ones (init_db, CLI) keep theirs
        self._sp = itertools.count(1)
        self.closed = False

    # context (#1142 / RLS): who is asking
    def set_ctx(self, user_id=None, org_ids=(), role="user"):
        ctx = (user_id, tuple(org_ids or ()), role)
        if self._sys:  # inside system_ctx(): takes effect when the block ends
            self._sys_prev = ctx
            return
        self._ctx = ctx
        if self._pg.info.transaction_status != TransactionStatus.IDLE:
            self._apply_ctx()

    @property
    def ctx(self):
        return self._ctx

    def _apply_ctx(self):
        uid, orgs, role = self._ctx
        self._pgx("SELECT set_config('app.user_id', %s, true), set_config('app.org_ids', %s, true), "
                  "set_config('app.role', %s, true)",
                  ("" if uid is None else str(uid), ",".join(str(int(o)) for o in orgs), role))

    def _pgx(self, sql, args=None):
        """2.149.0 B (#2504): one statement on the driver; inside a request (rt_begin) it is counted with its time."""
        st = getattr(_RT, "s", None)
        if st is None:
            return self._pg.execute(sql, args)
        t0 = time.perf_counter()
        try:
            return self._pg.execute(sql, args)
        finally:
            st[0] += 1
            st[1] += time.perf_counter() - t0

    def _begin(self):
        idle = self._pg.info.transaction_status == TransactionStatus.IDLE
        if self._auto and _CTX_HOOK[0] is not None and not self._sys and not self._resolving and self._resolve_ctx(idle):
            return
        if idle:
            self._apply_ctx()  # opens the transaction; SET LOCAL lives until commit / rollback

    def _resolve_ctx(self, idle):
        """2.37.0 (#1150, W-2): before every statement the context hook (core/access.py acx_conn_hook) says who is asking,
        so a route that sets g.user late (DAV, public links, forms, hooks, API tokens) can never read with a stale or the
        system context; a change is applied at once (also in the middle of a transaction). The hook answers a context,
        None (no request: keep the stored one) or LOOKUP (the memberships must be read first: that read runs as "system",
        then the real context replaces it). True when the context was applied here."""
        hook = _CTX_HOOK[0]
        ctx = hook(None)
        if ctx is None:
            return False
        if ctx is LOOKUP:
            self._resolving = True
            try:
                self._ctx = SYSTEM
                self._apply_ctx()
                ctx = hook(self)
            finally:
                self._resolving = False
            idle = True  # applied below in any case
        ctx = (ctx[0], tuple(ctx[1] or ()), ctx[2])
        if not idle and ctx == self._ctx:
            return False
        self._ctx = ctx
        self._apply_ctx()
        return True

    def execute(self, sql, args=None):
        self._begin()
        if args is None or (not args and "?" not in sql):
            return self._pgx(sql.replace("%", "%%") if args is not None else _raw(sql), None if args is None else ())
        if isinstance(args, dict):
            raise ProgrammingError("named parameters are not supported; use ?")
        return self._pgx(translate(sql), tuple(args))

    def executemany(self, sql, seq):
        self._begin()
        cur = self._pg.cursor()
        st, t0 = getattr(_RT, "s", None), time.perf_counter()  # 2.149.0 B (#2504): counted as one statement
        try:
            cur.executemany(translate(sql), [tuple(a) for a in seq])
        finally:
            if st is not None:
                st[0] += 1
                st[1] += time.perf_counter() - t0
        return cur

    def executescript(self, sql):
        self._begin()
        return self._pgx(_raw(sql))

    def commit(self):
        self._pg.commit()

    def rollback(self):
        self._pg.rollback()

    def heal(self):
        """After a caught database error: roll back when the transaction is aborted (Postgres refuses every further
        statement until then); a healthy transaction is left alone. True when it rolled back."""
        if self._pg.info.transaction_status == TransactionStatus.INERROR:
            self._pg.rollback()
            return True
        return False

    @property
    def in_transaction(self):
        return self._pg.info.transaction_status != TransactionStatus.IDLE

    def cursor(self):
        return _CursorShim(self)

    @contextlib.contextmanager
    def savepoint(self):
        """Statements that may fail (a duplicate key, ...) and are handled by the caller: Postgres aborts the whole
        transaction on an error unless it ran inside a savepoint."""
        self._begin()
        name = f"sp{next(self._sp)}"
        self._pgx(f"SAVEPOINT {name}")
        try:
            yield self
        except BaseException:
            self._pgx(f"ROLLBACK TO SAVEPOINT {name}")
            self._apply_ctx()  # 2.37.0 (#1150): a context set inside the savepoint was rolled back with it
            raise
        else:
            self._pgx(f"RELEASE SAVEPOINT {name}")

    def __enter__(self):  # like sqlite3: `with c:` commits on success, rolls back on an error (does not close)
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            self.commit()
        else:
            self.rollback()
        return False

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if not self._pg.closed and self._pg.info.transaction_status != TransactionStatus.IDLE:
                self._pg.rollback()  # like sqlite3.close(): what was not committed is gone
        except Exception:
            pass
        if self._release:
            self._release(self._pg)
        else:
            self._pg.close()

    def __del__(self):  # a forgotten close() must not keep a pooled connection forever
        with contextlib.suppress(Exception):
            if not self.closed:
                self.close()


class _CursorShim:
    """c.cursor().execute(...) as in sqlite3 (rare)."""

    def __init__(self, conn):
        self._conn, self._cur = conn, None

    def execute(self, sql, args=None):
        self._cur = self._conn.execute(sql, args)
        return self

    def __getattr__(self, k):
        return getattr(self._cur, k)

    def __iter__(self):
        return iter(self._cur)


def _raw(sql):
    return sql  # no parameters: psycopg sends the text as is (several statements allowed)


# --- pool --------------------------------------------------------------------------------------------------------------
_POOL = {"p": None}
_LOCK = threading.Lock()


def _configure(pg):
    pg.adapters  # noqa: B018
    pg.row_factory = _row_factory
    _rls_enter(pg)


def _rls_enter(pg):
    """2.37.0 (#1150): a login role that is a superuser or has BYPASSRLS ignores row-level security -- the app's pooled
    connections then work as the role kalmido_app (core/rls.py). Once per new connection; start-up keeps the login role."""
    from .rls import APP_ROLE, enter_sql
    try:
        if pg.execute(enter_sql()).fetchone()[0]:
            pg.execute(f"SET ROLE {APP_ROLE}")
    finally:
        pg.commit()


def pool_refresh():
    """2.37.0 (#1150): after init_db created the app role: replace connections the pool opened before (they would keep the
    login role)."""
    p = _POOL["p"]
    if p is not None:
        p.drain()


# 2.37.0 (#1150): 16 waitress threads x up to 3 connections each (a request may borrow a second one, e.g. for a push) plus the
# background threads. Postgres' max_connections must stay above this (its default 100 does). KALMIDO_DB_POOL_MAX overrides it.
# 2.102.0 D (#1994): the threads come from KALMIDO_THREADS (default 16, as before) and the pool follows them: 3 per thread + 8 for
# the background threads (16 -> 56, unchanged); KALMIDO_DB_POOL_MAX (or KALMIDO_POOL_MAX) still sets it explicitly.
try:
    WEB_THREADS = min(256, max(2, int(os.environ.get("KALMIDO_THREADS", "") or 16)))
except ValueError:
    print("warning: KALMIDO_THREADS is not a number; using 16", flush=True)
    WEB_THREADS = 16
POOL_MIN = 4
POOL_MAX = max(POOL_MIN, int(os.environ.get("KALMIDO_DB_POOL_MAX", "") or os.environ.get("KALMIDO_POOL_MAX", "") or WEB_THREADS * 3 + 8))
POOL_WAIT_S = 30
_POOL_TO = {"n": 0, "last": 0.0}  # 2.102.0 D (#1994): pool waits that ran out (the health check shows them, the log warns)
# Every session: no statement runs longer than 30 s, no transaction idles longer than 5 min (a hung network call inside a
# transaction would otherwise hold its snapshot and locks). init_db and the backup lift the statement limit for themselves.
# 2.37.0 (review K2-4): KALMIDO_DB_STATEMENT_TIMEOUT overrides the 30 s (seconds; 0 = no limit) for big instances.
try:
    STATEMENT_TIMEOUT_S = max(0, int(float(os.environ.get("KALMIDO_DB_STATEMENT_TIMEOUT", "") or 30)))
except ValueError:
    print("warning: KALMIDO_DB_STATEMENT_TIMEOUT is not a number of seconds; using 30", flush=True)
    STATEMENT_TIMEOUT_S = 30
SESSION_OPTIONS = (f"-c statement_timeout={STATEMENT_TIMEOUT_S * 1000} -c idle_in_transaction_session_timeout=300000 "
                   "-c jit=off")  # 2.37: JIT costs 15-20 ms per /api/state for <3 ms queries (EXPLAIN)


def _new_conn_kwargs():
    return {"autocommit": False, "prepare_threshold": None, "options": SESSION_OPTIONS}


def pool(url):
    with _LOCK:
        p = _POOL["p"]
        if p is None:
            # check: a cheap test of every borrowed connection, so a database restart costs no failed requests
            p = ConnectionPool(url, min_size=POOL_MIN, max_size=POOL_MAX, timeout=POOL_WAIT_S, open=False, configure=_configure,
                               kwargs={**_new_conn_kwargs(), "context": _ctx_for_adapters()},
                               check=_check_borrowed,
                               reset=lambda pg: pg.rollback() if pg.info.transaction_status != TransactionStatus.IDLE else None)
            p.open(wait=False)
            _POOL["p"] = p
        return p


def _ctx_for_adapters():
    return _AdaptCtx()


class _AdaptCtx:
    adapters = ADAPTERS
    connection = None


def _check_borrowed(pg):
    """The pool's test of a borrowed connection. 2.102.1: a broken one usually means the server dropped them all (a database
    restart): then every idle connection is tested at once (pool.check: the broken ones go, new ones are opened), else the
    borrow would walk the dead ones one by one with the pool's growing pause between them (1 + 2 + 4 + 8 + 16 s, past the
    30 s wait with six dead connections)."""
    try:
        ConnectionPool.check_connection(pg)
    except Exception:
        p = _POOL["p"]
        if p is not None:
            try:
                p.check()
            except Exception:  # noqa: BLE001 - the borrow goes on with its own retry
                pass
        raise


def connect_pooled(url):
    p = pool(url)
    try:
        pg = p.getconn()
    except PoolTimeout:
        pool_timeout_warn(p)
        raise
    pg.row_factory = _row_factory
    return Conn(pg, release=p.putconn)


def pool_timeout_warn(p):
    """2.102.0 D (#1994): a request waited POOL_WAIT_S for a connection in vain -- no longer silent: a log line with the pool's
    counters (at most one a minute; the health check counts every one)."""
    _POOL_TO["n"] += 1
    now = time.time()
    if now - _POOL_TO["last"] < 60:
        return
    _POOL_TO["last"] = now
    try:
        st = p.get_stats()
    except Exception:  # noqa: BLE001
        st = {}
    print(f"WARNING database pool exhausted: waited {POOL_WAIT_S} s for a connection ({_POOL_TO['n']} times so far); "
          f"size {st.get('pool_size')}/{POOL_MAX}, available {st.get('pool_available')}, waiting {st.get('requests_waiting')}, "
          f"threads {WEB_THREADS}. Raise KALMIDO_DB_POOL_MAX / KALMIDO_THREADS or look for slow requests.", flush=True)


def pool_stats():
    """2.102.0 D (#1994): the pool's counters (numbers only) for /api/admin/health."""
    p = _POOL["p"]
    st = dict(p.get_stats()) if p is not None else {}
    return {"min": POOL_MIN, "max": POOL_MAX, "timeouts": _POOL_TO["n"],
            **{k: v for k, v in st.items() if isinstance(v, (int, float))}}


def connect_direct(url, timeout=10):
    """A connection outside the pool (start-up checks, the CLI, tests of the layer)."""
    pg = psycopg.connect(url, connect_timeout=timeout, context=_AdaptCtx(), **_new_conn_kwargs())
    pg.row_factory = _row_factory
    return Conn(pg)


def wait_ready(url, seconds=60):
    """At start the database container may still be starting: try for a while."""
    t0, last = time.time(), None
    while time.time() - t0 < seconds:
        try:
            c = connect_direct(url, timeout=5)
            c.execute("SELECT 1").fetchone()
            c.close()
            return True
        except psycopg.OperationalError as e:
            last = e
            time.sleep(1)
    raise last or OperationalError("database not reachable")


# --- dialect helpers ---------------------------------------------------------------------------------------------------
def insert_id(c, sql, args=()):
    """INSERT ... RETURNING id: the new row's id (what the cursor's lastrowid was in SQLite)."""
    r = c.execute(sql.rstrip().rstrip(";") + " RETURNING id", args).fetchone()
    return r[0] if r else None


def write_lock(c, name="kalmido"):
    """Serializes a check-then-write section across connections until the transaction ends (SQLite: an immediate write transaction)."""
    c.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (name,))


def table_columns(c, table):
    return {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() "
                                    "AND table_name=?", (table,))}


def table_exists(c, table):
    return c.execute("SELECT to_regclass(?)", (table,)).fetchone()[0] is not None


def like_escape(s):
    """A user's text as a literal part of an ILIKE pattern (with ESCAPE '\\')."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def conninfo_dict(url):
    """DATABASE_URL as libpq keywords (host, port, dbname, user, password, ...): admin/backup.py hands them to pg_dump /
    pg_restore through the environment."""
    return psycopg.conninfo.conninfo_to_dict(url)


def st_ids(ids):
    """2.65.0 (#1505): a set of ids as ONE parameter for `col = ANY(CAST(? AS BIGINT[]))`: the array literal as text (one value
    to send instead of thousands of placeholders or one dumped number each)."""
    return "{" + ",".join(str(int(i)) for i in ids) + "}"
