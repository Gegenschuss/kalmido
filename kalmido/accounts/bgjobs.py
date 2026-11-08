"""2.193.0 D (#2220): the short background work a request starts (mails right after an action, "Back up now", the
organisation keys' passes after a move) as a queue in the database (table bg_jobs) instead of a thread of the request's
process. A request adds a row (bgj_add, rights checked by the caller before); the loop "bgjobs" (admin/worker.py WRK_LOOPS:
one process of the instance at a time) takes it. In the roles all / worker the add wakes the loop of the same process at
once (no delay against the thread before); in the role web the worker takes it on its next round (BGJ_IDLE s). Each
row runs in a thread of its own (at most BGJ_SLOTS at once), so a long backup never holds the mails behind it. 2.370.2 (#2779):
the work goes through the maintenance gate, a restore waits for it and it waits for a restore (bgj_fn gate=False: a kind that
would hold a restore off for hours and never writes to the tables it reads).

2.370.3 (#2760): the exports and imports a person starts (account export, organisation export, account import with its check
and key step, knowledge import, contacts import) are rows too: bgj_fn(kind, long=True) gives them slots of their own
(BGJ_LONG_SLOTS per process), so a long import never holds the mails off. Whether one runs is the row (bgj_busy: waiting or
running, in every process), not a thread of the process that answers; the progress a browser asks for is the row's progress
(bgj_progress / bgj_state) or the state file the run writes. bgj_add(lock=, guard=) checks "one at a time" / "at most n on
the server" and adds the row in one step. When the process is told to stop (SIGTERM, bgj_on_term), its running rows wait
again at once (rows of a kind with one run only are failed at once: the browser says "interrupted" instead of waiting
BGJ_LOST s), so a restart takes them up right away.

A row is taken with SELECT ... FOR UPDATE SKIP LOCKED (two takers never get the same row). While it runs, its beat_at is
renewed every BGJ_BEAT s: a row whose process is gone (no beat for BGJ_LOST s) is waiting again (at most BGJ_TRIES runs, then
failed). The payload is sealed with the server key (it may hold a mail with a sign-in link; 2.306.0 D1 (#2875): a key from
KALMIDO_SECRET_KEY, which never lives in the database, so a copy of the database alone never opens it) and emptied when the row is
done; done rows go after BGJ_KEEP_DONE_H hours, failed ones after BGJ_KEEP_FAILED_D days. A kind is a function registered
with @bgj_fn(kind) that gets the payload's arguments; it runs in the same context as the thread before (own connections,
no request). Without the database (bgj_add fails) the work runs in a thread as before.
"""
import base64
import json
import os
import signal
import threading
import time
from datetime import datetime, timedelta, timezone

from ..core.config import app, SECRET_KEY
from ..core.db import connect, iso
from ..core.env import env_int  # 2.370.3 (#2760)
from ..core.db import db_log_err  # 2.239.0 B (#2888): no values of database errors in the log
from ..core.pg import system_ctx
from ..core.pgbus import bus_on, bus_send  # 2.622.0 (#3891)
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .login import auth_key
from .session import GATE, bg_here

BGJ_IDLE = 3            # s between two rounds without work (the role web: how late the worker sees a new row)
BGJ_BEAT = 30           # s between two beats of a running row
BGJ_LOST = 150          # s without a beat: the process that ran it is gone
BGJ_TRIES = 3           # runs of one row at most (a lost run counts)
BGJ_HOUSE_S = 30        # s between two housekeeping passes (lost rows back, old rows away)
BGJ_KEEP_DONE_H = 24
BGJ_KEEP_FAILED_D = 7
BGJ_SLOTS = 4           # rows running at once per process
BGJ_STOP_WAIT_S = env_int("KALMIDO_BG_STOP_WAIT_S", 8, lo=0, hi=60)  # 2.370.3 (#2760, review 1): a stop waits this long for running rows (< Docker's 10 s)
BGJ_PROGRESS_KEEP_H = 1  # 2.370.3 (review 7): the progress of an ended row (counts, names of bad cards) is emptied after this
BGJ_LONG_SLOTS = env_int("KALMIDO_BG_LONG_SLOTS", 4, lo=1)  # 2.370.3 (#2760): exports / imports at once per process
BGJ_FNS = {}            # kind -> function(*args)
BGJ_TRIES_OF = {}       # kind -> runs at most (review 2.193.0: a mail is not sent a second time after a lost run)
_Q = {"thread": None, "house": 0.0}
_SLOTS = {"busy": 0, "long": 0}
_LOCK = threading.Lock()
_WAKE = threading.Event()
_TOKEN = f"{os.getpid()}-{os.urandom(3).hex()}"  # the process in started_by (numbers only, for a look in the table)


BGJ_NO_GATE = set()  # 2.370.2 (#2779): kinds of bgj_fn(gate=False)
BGJ_LONG = set()     # 2.370.3 (#2760): kinds of bgj_fn(long=True)
_CUR = threading.local()  # 2.370.3 (#2760): the row the current thread runs (bgj_current)


def _now():
    """The real clock (not the test clock of now_utc): the queue's times are about processes, a moved clock in a test
    would make a running row look lost (or a new one wait for days)."""
    return datetime.now(timezone.utc)


def bgj_fn(kind, tries=BGJ_TRIES, gate=True, long=False):
    """Registers the function of a kind (decorator); it gets the arguments bgj_add was given. tries: runs at most (1 for
    work that must not happen twice, e.g. a mail: a lost run is then failed, not repeated). gate: see the top. long: an
    export / import (2.370.3, #2760): its own slots, never in the way of the short rows."""
    def deco(fn):
        BGJ_FNS[kind] = fn
        BGJ_TRIES_OF[kind] = tries
        if not gate:
            BGJ_NO_GATE.add(kind)
        if long:
            BGJ_LONG.add(kind)
        return fn
    return deco


def _enc(v):
    """JSON-safe: bytes (an attachment) as {"$b": base64}, tuples as lists."""
    if isinstance(v, (bytes, bytearray)):
        return {"$b": base64.b64encode(bytes(v)).decode()}
    if isinstance(v, (list, tuple)):
        return [_enc(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _enc(x) for k, x in v.items()}
    return v


def _dec(v):
    if isinstance(v, dict):
        if set(v) == {"$b"}:
            return base64.b64decode(v["$b"])
        return {k: _dec(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_dec(x) for x in v]
    return v


_BGJ_KEY = {}


def _srv_key():
    """2.306.0 D1 (#2875): the queue's key from the server key (KALMIDO_SECRET_KEY / its file, never in the database or a
    backup), HKDF like the other sealed values; None without a server key."""
    if SECRET_KEY and "k" not in _BGJ_KEY:
        _BGJ_KEY["k"] = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"kalmido-bgjob", info=b"bg_jobs payload v2").derive(SECRET_KEY)
    return _BGJ_KEY.get("k")


def _db_key(c):
    with system_ctx(c):  # the sign-in key (settings), never handed out
        return auth_key(c)


def _seal(c, kind, args):
    """AES-GCM, the kind bound as associated data. v2: the server key (2.306.0 D1, #2875); v1 (the sign-in key, kept in the
    database) only on a server without KALMIDO_SECRET_KEY, as before."""
    k = _srv_key()
    tag, key = ("v2.", k) if k else ("v1.", _db_key(c))
    n = os.urandom(12)
    return tag + base64.urlsafe_b64encode(n + AESGCM(key).encrypt(n, json.dumps(_enc(list(args))).encode(), b"kalmido-bgjob:" + kind.encode())).decode()


def _unseal(c, kind, s):
    """Both forms: rows a v1 server queued before the update still run after it."""
    if s.startswith("v2."):
        key = _srv_key()
        if not key:
            raise ValueError("no server key")
    else:
        key = _db_key(c)
    raw = base64.urlsafe_b64decode(s[3:])
    return _dec(json.loads(AESGCM(key).decrypt(raw[:12], raw[12:], b"kalmido-bgjob:" + kind.encode())))


def bgj_add(kind, *args, org_id=None, user_id=None, delay=0.0, once=False, lock=None, guard=None, progress=None):
    """Queues kind(*args) (own connection, committed at once; delay = not before so many seconds, e.g. after the request's
    commit). once: nothing new while a row of this kind (and org_id / user_id) waits. Returns the row id (None: ran in a thread / not needed).
    2.370.3 (#2760): lock = a name: the check and the add as one step for every process (a transaction lock on it); guard(c) runs
    under it before the add and may raise (e.g. Denied 409 "already running"): that goes to the caller, nothing is added and
    nothing runs. progress: the row's first progress (dict, bgj_state)."""
    if kind not in BGJ_FNS:
        raise KeyError(kind)
    c = None
    refused = []
    try:
        c = connect()
        with system_ctx(c):  # the queue's own rows: the caller checked the rights, the row hands nothing to a person
            if lock:
                bgj_lock(c, lock)
            if guard is not None:
                try:
                    guard(c)
                except Exception as e:  # noqa: BLE001 -- the caller's answer (409 / 429), never the thread fallback below
                    refused.append(e)
                    raise
            if once:  # review 2.193.0: check + add as one step (two clicks at once give one row)
                c.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("bgjobs:" + kind,)).fetchone()
            # 2.280.0 (#3114): once per kind AND org / person (a waiting index job of space A must not swallow space B's)
            if once and c.execute("""SELECT 1 FROM bg_jobs WHERE kind=? AND state='wait' AND org_id IS NOT DISTINCT FROM ?
                                     AND user_id IS NOT DISTINCT FROM ? LIMIT 1""", (kind, org_id, user_id)).fetchone():
                c.commit()
                return None
            now = _now()
            rid = c.execute("""INSERT INTO bg_jobs(kind, org_id, user_id, payload, state, attempts, run_after, created_at)
                               VALUES(?,?,?,?,'wait',0,?,?) RETURNING id""",
                            (kind, org_id, user_id, _seal(c, kind, args), iso(now + timedelta(seconds=delay)), iso(now))).fetchone()[0]
            if progress is not None:  # 2.370.3 (#2760)
                c.execute("UPDATE bg_jobs SET progress=? WHERE id=?", (json.dumps(progress), rid))
        c.commit()
    except Exception as e:  # noqa: BLE001 -- no database: the work runs as before (a thread of this process)
        if c is not None:
            try:
                c.rollback()
            except Exception:  # noqa: BLE001 -- rollback after an error: the connection may be gone
                pass
        if refused:
            raise refused[0]  # (the connection is closed below)
        print("bgjobs: queue unavailable, running", kind, "here:", type(e).__name__, flush=True)

        def late():
            time.sleep(delay)
            if kind in BGJ_NO_GATE:
                return BGJ_FNS[kind](*args)
            with GATE.work():  # 2.370.3 (#2760): the fallback goes through the maintenance gate like a row (gated_thread before)
                return BGJ_FNS[kind](*args)
        threading.Thread(target=late, daemon=True, name="bgjobs-direct").start()
        return None
    finally:
        if c is not None:
            c.close()
    bgj_kick()
    return rid


def bgj_kick():
    """Wakes the loop (starts it when it does not run yet); nothing in the role web (the worker takes the row).
    2.622.0 (#3891): and tells the other processes (core/pgbus.py): the one that runs the queue now takes the row at once
    instead of after its rest (BGJ_IDLE)."""
    bus_send("bgjobs")
    if not bg_here():
        return
    with _LOCK:
        if _Q["thread"] is None or not _Q["thread"].is_alive():
            _Q["thread"] = threading.Thread(target=_loop, daemon=True, name="bgjobs")
            _Q["thread"].start()
    _WAKE.set()


def _bgj_heard(_d):
    if _Q["thread"] is not None:  # 2.622.0 (#3891): another process added a row
        _WAKE.set()


bus_on("bgjobs", _bgj_heard)


@app.before_request
def _bgj_start():
    if _Q["thread"] is None and bg_here():  # rows left from before a restart run without a new add
        bgj_kick()


def _loop():
    while True:
        n = 0
        _WAKE.clear()  # job/2398: before taking, not after the wait - a kick between wait() and clear() was lost (up to BGJ_IDLE late)
        try:
            if _kinds_free():
                with GATE.bg():  # only the taking: each row goes through the gate itself (_run)
                    n = bgj_run_once()
        except Exception as e:  # noqa: BLE001 -- the loop never dies
            print("bgjobs: loop", db_log_err(e), flush=True)
            time.sleep(BGJ_IDLE)
        if not n:
            _WAKE.wait(BGJ_IDLE)


def bgj_house(c, force=False):
    """Lost rows (no beat for BGJ_LOST s) wait again or fail after BGJ_TRIES runs; old rows go. Returns the counts."""
    if not force and time.monotonic() - _Q["house"] < BGJ_HOUSE_S:
        return None
    _Q["house"] = time.monotonic()
    now = _now()
    lost = iso(now - timedelta(seconds=BGJ_LOST))
    with system_ctx(c):  # the queue's housekeeping over every workspace's rows (states and times only)
        again = failed = 0
        for r in c.execute("SELECT id, kind, attempts FROM bg_jobs WHERE state='run' AND beat_at < ? FOR UPDATE SKIP LOCKED",
                           (lost,)).fetchall():
            if r["attempts"] < BGJ_TRIES_OF.get(r["kind"], BGJ_TRIES):
                again += c.execute("UPDATE bg_jobs SET state='wait', started_by='' WHERE id=?", (r["id"],)).rowcount
            else:
                failed += c.execute("UPDATE bg_jobs SET state='failed', error='lost', payload='', finished_at=? WHERE id=?",
                                    (iso(now), r["id"])).rowcount
        c.execute("UPDATE bg_jobs SET progress='' WHERE state IN ('done', 'failed') AND progress != '' AND finished_at < ?",
                  (iso(now - timedelta(hours=BGJ_PROGRESS_KEEP_H)),))  # 2.370.3 (review 7)
        gone = c.execute("DELETE FROM bg_jobs WHERE (state='done' AND finished_at < ?) OR (state='failed' AND finished_at < ?)",
                         (iso(now - timedelta(hours=BGJ_KEEP_DONE_H)), iso(now - timedelta(days=BGJ_KEEP_FAILED_D)))).rowcount
    c.commit()
    if again or failed:
        print(f"bgjobs: {again} lost run(s) waiting again, {failed} failed", flush=True)
    return {"again": again, "failed": failed, "gone": gone}


def _kinds_free():
    """2.370.3 (#2760): the kinds this process may take now: the short ones while a short slot is free, the long ones
    (exports / imports) while a long slot is free."""
    if _Q.get("stopping"):
        return []
    with _LOCK:
        short, long_ = _SLOTS["busy"] < BGJ_SLOTS, _SLOTS["long"] < BGJ_LONG_SLOTS
    return sorted(k for k in BGJ_FNS if (long_ if k in BGJ_LONG else short))


def bgj_claim(c, kinds=None):
    """Takes the oldest due row (state run, attempts + 1) without committing: (id, kind, payload, attempts) or None. Two
    takers at once get two different rows (SKIP LOCKED). Only kinds this process knows (a row of another version waits).
    kinds: only these (2.370.3, #2760: those with a free slot)."""
    now = iso(_now())
    kinds = sorted(BGJ_FNS) if kinds is None else kinds
    if not kinds:
        return None
    with system_ctx(c):  # the queue's rows of every workspace; the work itself runs in the context its kind had before
        return c.execute("""UPDATE bg_jobs SET state='run', attempts=attempts+1, started_at=?, beat_at=?, started_by=?
                            WHERE id=(SELECT id FROM bg_jobs WHERE state='wait' AND run_after <= ?
                                      AND kind IN (""" + ",".join("?" * len(kinds)) + """) ORDER BY id LIMIT 1
                                      FOR UPDATE SKIP LOCKED)
                            RETURNING id, kind, payload, attempts""", (now, now, _TOKEN, now, *kinds)).fetchone()


def _finish(rid, state, error="", run=None):
    """run = the row's attempts when taken: a late finish of a run the housekeeping gave up never touches the next run."""
    c = connect()
    try:
        with system_ctx(c):  # the queue's own row
            c.execute("UPDATE bg_jobs SET state=?, error=?, payload='', finished_at=? WHERE id=?" + (" AND attempts=? AND state='run'" if run else ""),
                      (state, error[:200], iso(_now()), rid, *((run,) if run else ())))
        c.commit()
    finally:
        c.close()


def _beat(rid, stop, run):
    while not stop.wait(BGJ_BEAT):
        try:
            with GATE.work():  # 2.370.2 (#2779)
                c = connect()
                try:
                    with system_ctx(c):  # the queue's own row
                        c.execute("UPDATE bg_jobs SET beat_at=? WHERE id=? AND state='run' AND attempts=?", (iso(_now()), rid, run))
                    c.commit()
                finally:
                    c.close()
        except Exception as e:  # noqa: BLE001 -- a missed beat only risks a second run after BGJ_LOST
            print("bgjobs: beat", type(e).__name__, flush=True)


def _row_ours(rid, run):
    """2.370.2 (#2779): this run of the row still exists (a restore in between emptied the queue, #3051 p. 12)."""
    c = connect()
    try:
        with system_ctx(c):  # the queue's own row
            return bool(c.execute("SELECT 1 FROM bg_jobs WHERE id=? AND state='run' AND attempts=?", (rid, run)).fetchone())
    finally:
        c.close()


def _run(rid, kind, args, run):
    """One row in a thread of its own, through the maintenance gate (2.370.2, #2779): a restore never runs next to it."""
    if kind in BGJ_NO_GATE:
        return _run_row(rid, kind, args, run)
    with GATE.work():
        _run_row(rid, kind, args, run, True)


def _run_row(rid, kind, args, run, gated=False):
    """The work of a row (a long backup never holds the mails behind it); the row's state afterwards. gated = it came through
    the gate: what a restore took away meanwhile never runs."""
    stop = threading.Event()
    threading.Thread(target=_beat, args=(rid, stop, run), daemon=True, name="bgjobs-beat").start()
    state, error = "done", ""
    _CUR.rid = rid
    try:
        fn = BGJ_FNS.get(kind)
        if fn is None:  # a kind of another version
            state, error = "failed", "unknown kind"
        elif not gated or _row_ours(rid, run):
            fn(*args)
    except Exception as e:  # noqa: BLE001 -- the kinds log their own errors as before
        print("bgjobs:", kind, "failed:", db_log_err(e), flush=True)
        state, error = "failed", type(e).__name__
    finally:
        _CUR.rid = None
        stop.set()
        try:
            _finish(rid, state, error, run)
        except Exception as e:  # noqa: BLE001 -- no database: the housekeeping finds the row without a beat later
            print("bgjobs: finish", rid, type(e).__name__, flush=True)
        with _LOCK:
            _SLOTS[_slot_of(kind)] -= 1
        _WAKE.set()


def _slot_of(kind):
    return "long" if kind in BGJ_LONG else "busy"


def bgj_run_once():
    """One round: housekeeping (every BGJ_HOUSE_S s), then the due rows while a slot is free (each in its own thread).
    Returns how many rows were taken."""
    n = 0
    c = connect()
    try:
        bgj_house(c)
        while True:
            kinds = _kinds_free()
            if not kinds:
                break
            r = bgj_claim(c, kinds)
            c.commit()
            if not r:
                break
            rid, kind = r["id"], r["kind"]
            try:
                args = _unseal(c, kind, r["payload"])
                c.commit()
            except Exception as e:  # noqa: BLE001 -- another server key: the row cannot be read here
                c.rollback()
                _finish(rid, "failed", "payload: " + type(e).__name__)
                continue
            with _LOCK:
                _SLOTS[_slot_of(kind)] += 1
            try:
                threading.Thread(target=_run, args=(rid, kind, args, r["attempts"]), daemon=True, name="bgjobs-run").start()
            except Exception as e:  # noqa: BLE001 -- review 2.193.0: no thread = the slot is free again, the row waits
                with _LOCK:
                    _SLOTS[_slot_of(kind)] -= 1
                print("bgjobs: no thread for", kind, type(e).__name__, flush=True)
                with system_ctx(c):  # the queue's own row
                    c.execute("UPDATE bg_jobs SET state='wait', attempts=attempts-1, started_by='' WHERE id=?", (rid,))
                c.commit()
                break
            n += 1
    finally:
        c.close()
    return n


def bgj_counts(c):
    """GET /api/admin/health: the rows per state (numbers only)."""
    with system_ctx(c):  # counts of the queue over every workspace, no content
        rows = c.execute("SELECT state, COUNT(*) AS n FROM bg_jobs GROUP BY state").fetchall()
    out = {"wait": 0, "run": 0, "done": 0, "failed": 0}
    out.update({r["state"]: int(r["n"]) for r in rows})
    return out


def bgj_pending(c, kind):
    """A row of this kind waits or runs (e.g. "Back up now" while the worker has not started it yet)."""
    with system_ctx(c):  # a state of the queue, no content
        return bool(c.execute("SELECT 1 FROM bg_jobs WHERE kind=? AND state IN ('wait', 'run') LIMIT 1", (kind,)).fetchone())



# ---------------------------------------------------------------- 2.370.3 (#2760): state from the row, stop of the process
def _kinds_sql(kinds):
    kinds = (kinds,) if isinstance(kinds, str) else tuple(kinds)
    return "kind IN (" + ",".join("?" * len(kinds)) + ")", kinds


def bgj_lock(c, lock):
    """The lock bgj_add(lock=) takes, on c until its transaction ends (e.g. a cancel that must not fall between the check
    and the add of a row)."""
    with system_ctx(c):  # a lock only, no rows
        c.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("bgjobs-lock:" + lock,)).fetchone()


def bgj_busy(kinds, user_id=None, org_id=None, c=None):
    """A row of these kinds (for this person / organisation, None = any) waits or runs, in any process of the instance.
    Own connection unless c is given (states only, no content)."""
    return bgj_active(kinds, user_id=user_id, org_id=org_id, c=c) > 0


def bgj_active(kinds, user_id=None, org_id=None, c=None):
    """How many rows of these kinds wait or run (e.g. "at most n imports on the server")."""
    own = c is None
    c = c or connect()
    try:
        w, a = _kinds_sql(kinds)
        if user_id is not None:
            w, a = w + " AND user_id=?", (*a, int(user_id))
        if org_id is not None:
            w, a = w + " AND org_id=?", (*a, int(org_id))
        with system_ctx(c):  # a state of the queue, no content
            n = c.execute(f"SELECT COUNT(*) FROM bg_jobs WHERE state IN ('wait', 'run') AND {w}", a).fetchone()[0]
        if own:
            c.rollback()
        return int(n or 0)
    finally:
        if own:
            c.close()


def bgj_drop(kinds, user_id=None, org_id=None, c=None):
    """2.370.3 (#2760, review 6): removes the WAITING rows of these kinds for this person / organisation (a cancel before a
    worker took it, e.g. no worker running); a running row stays. Returns how many went."""
    own = c is None
    c = c or connect()
    try:
        w, a = _kinds_sql(kinds)
        if user_id is not None:
            w, a = w + " AND user_id=?", (*a, int(user_id))
        if org_id is not None:
            w, a = w + " AND org_id=?", (*a, int(org_id))
        with system_ctx(c):  # the queue's own rows of the caller (checked by the route)
            n = c.execute(f"DELETE FROM bg_jobs WHERE state='wait' AND {w}", a).rowcount
        if own:
            c.commit()
        return n
    finally:
        if own:
            c.close()


def bgj_current():
    """The id of the row the current thread runs (None outside a queue row, e.g. the thread fallback without a database)."""
    return getattr(_CUR, "rid", None)


def bgj_progress(rid, d):
    """The progress of a running row (a small dict: counts, state, a message key - no content), for bgj_state."""
    if not rid:
        return
    c = connect()
    try:
        with system_ctx(c):  # the queue's own row
            c.execute("UPDATE bg_jobs SET progress=? WHERE id=?", (json.dumps(d), int(rid)))
        c.commit()
    finally:
        c.close()


def bgj_state(kind, user_id, pick):
    """The newest row of this kind and person whose progress pick(progress) accepts -> (row state, progress) or None. A
    row that ended without its run writing the end (lost, stopped) shows as it was: the caller tells "interrupted"."""
    c = connect()
    try:
        with system_ctx(c):  # the queue's own rows of this person (the caller is that person)
            rows = c.execute("SELECT state, progress FROM bg_jobs WHERE kind=? AND user_id=? AND progress != '' ORDER BY id DESC LIMIT 50",
                             (kind, int(user_id))).fetchall()
        c.rollback()
    finally:
        c.close()
    for r in rows:
        try:
            p = json.loads(r["progress"])
        except ValueError:
            continue
        if isinstance(p, dict) and pick(p):
            return r["state"], p
    return None


def bgj_release():
    """The process stops: its running rows wait again at once (no BGJ_LOST s until the next process takes them); a row
    of a kind with its runs used up (one run only: a mail, an import) is failed at once. Returns (again, failed)."""
    again = failed = 0
    c = connect()
    try:
        with system_ctx(c):  # the queue's own rows of this process
            for r in c.execute("SELECT id, kind, attempts FROM bg_jobs WHERE state='run' AND started_by=?", (_TOKEN,)).fetchall():
                if r["attempts"] < BGJ_TRIES_OF.get(r["kind"], BGJ_TRIES):
                    again += c.execute("UPDATE bg_jobs SET state='wait', started_by='' WHERE id=? AND state='run'", (r["id"],)).rowcount
                else:
                    failed += c.execute("UPDATE bg_jobs SET state='failed', error='stopped', payload='', finished_at=? WHERE id=? AND state='run'",
                                        (iso(_now()), r["id"])).rowcount
        c.commit()
    finally:
        c.close()
    if again or failed:
        print(f"bgjobs: stopping, {again} running row(s) waiting again, {failed} failed", flush=True)
    return again, failed


def bgj_on_term():
    """Installs the stop handler (main thread only: app.py before the web server, the worker's main): on SIGTERM the
    running rows are released (bgj_release), then the process ends as it did before (the signal's former handling)."""
    prev = signal.getsignal(signal.SIGTERM)

    def stop(signum, frame):
        _Q["stopping"] = True  # no new row is taken from here on (_kinds_free)
        end = time.monotonic() + BGJ_STOP_WAIT_S  # review 1: the running rows get the time Docker gives before its SIGKILL
        while (_SLOTS["busy"] or _SLOTS["long"]) and time.monotonic() < end:
            time.sleep(0.1)
        try:
            bgj_release()
        except Exception as e:  # noqa: BLE001 -- no database: the housekeeping finds the rows after BGJ_LOST s
            print("bgjobs: release", type(e).__name__, flush=True)
        if callable(prev):
            return prev(signum, frame)
        if prev == signal.SIG_IGN:
            return None
        # the process ends now: a released row must not be taken again by this process (as PID 1 of a container the default
        # handling would ignore the signal and leave it running until the SIGKILL)
        os._exit(128 + signal.SIGTERM)
        return None
    try:
        signal.signal(signal.SIGTERM, stop)
    except ValueError:  # not the main thread
        pass
