"""2.193.0 D (#2220): the short background work a request starts (mails right after an action, "Back up now", the
organisation keys' passes after a move) as a queue in the database (table bg_jobs) instead of a thread of the request's
process. A request adds a row (bgj_add, rights checked by the caller before); the loop "bgjobs" (admin/worker.py WRK_LOOPS:
one process of the instance at a time) takes it. In the roles all / worker the add wakes the loop of the same process at
once (no delay against the thread before); in the role web the worker takes it on its next round (BGJ_IDLE s). Each
row runs in a thread of its own (at most BGJ_SLOTS at once, outside the maintenance gate as the threads before), so a long
backup never holds the mails behind it.

A row is taken with SELECT ... FOR UPDATE SKIP LOCKED (two takers never get the same row). While it runs, its beat_at is
renewed every BGJ_BEAT s: a row whose process is gone (no beat for BGJ_LOST s) is waiting again (at most BGJ_TRIES runs, then
failed). The payload is sealed with the server key (it may hold a mail with a sign-in link) and emptied when the row is
done; done rows go after BGJ_KEEP_DONE_H hours, failed ones after BGJ_KEEP_FAILED_D days. A kind is a function registered
with @bgj_fn(kind) that gets the payload's arguments; it runs in the same context as the thread before (own connections,
no request). Without the database (bgj_add fails) the work runs in a thread as before.
"""
import base64
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from ..core.config import app
from ..core.db import connect, iso
from ..core.pg import system_ctx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

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
BGJ_FNS = {}            # kind -> function(*args)
BGJ_TRIES_OF = {}       # kind -> runs at most (review 2.193.0: a mail is not sent a second time after a lost run)
_Q = {"thread": None, "house": 0.0}
_SLOTS = {"busy": 0}
_LOCK = threading.Lock()
_WAKE = threading.Event()
_TOKEN = f"{os.getpid()}-{os.urandom(3).hex()}"  # the process in started_by (numbers only, for a look in the table)


def _now():
    """The real clock (not the test clock of now_utc): the queue's times are about processes, a moved clock in a test
    would make a running row look lost (or a new one wait for days)."""
    return datetime.now(timezone.utc)


def bgj_fn(kind, tries=BGJ_TRIES):
    """Registers the function of a kind (decorator); it gets the arguments bgj_add was given. tries: runs at most (1 for
    work that must not happen twice, e.g. a mail: a lost run is then failed, not repeated)."""
    def deco(fn):
        BGJ_FNS[kind] = fn
        BGJ_TRIES_OF[kind] = tries
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


def _seal(c, kind, args):
    """AES-GCM with the server's sign-in key (login.seal's, without its length limit: a mail with HTML is longer), the kind
    bound as associated data."""
    with system_ctx(c):  # the server key (settings), never handed out
        key = auth_key(c)
    n = os.urandom(12)
    return "v1." + base64.urlsafe_b64encode(n + AESGCM(key).encrypt(n, json.dumps(_enc(list(args))).encode(), b"kalmido-bgjob:" + kind.encode())).decode()


def _unseal(c, kind, s):
    with system_ctx(c):  # the server key (settings), never handed out
        key = auth_key(c)
    raw = base64.urlsafe_b64decode(s[3:])
    return _dec(json.loads(AESGCM(key).decrypt(raw[:12], raw[12:], b"kalmido-bgjob:" + kind.encode())))


def bgj_add(kind, *args, org_id=None, user_id=None, delay=0.0, once=False):
    """Queues kind(*args) (own connection, committed at once; delay = not before so many seconds, e.g. after the request's
    commit). once: nothing new while a row of this kind waits. Returns the row id (None: ran in a thread / not needed)."""
    if kind not in BGJ_FNS:
        raise KeyError(kind)
    c = None
    try:
        c = connect()
        with system_ctx(c):  # the queue's own rows: the caller checked the rights, the row hands nothing to a person
            if once:  # review 2.193.0: check + add as one step (two clicks at once give one row)
                c.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("bgjobs:" + kind,)).fetchone()
            if once and c.execute("SELECT 1 FROM bg_jobs WHERE kind=? AND state='wait' LIMIT 1", (kind,)).fetchone():
                c.commit()
                return None
            now = _now()
            rid = c.execute("""INSERT INTO bg_jobs(kind, org_id, user_id, payload, state, attempts, run_after, created_at)
                               VALUES(?,?,?,?,'wait',0,?,?) RETURNING id""",
                            (kind, org_id, user_id, _seal(c, kind, args), iso(now + timedelta(seconds=delay)), iso(now))).fetchone()[0]
        c.commit()
    except Exception as e:  # noqa: BLE001 -- no database: the work runs as before (a thread of this process)
        print("bgjobs: queue unavailable, running", kind, "here:", type(e).__name__, flush=True)
        if c is not None:
            try:
                c.rollback()
            except Exception:  # noqa: BLE001
                pass

        def late():
            time.sleep(delay)
            BGJ_FNS[kind](*args)
        threading.Thread(target=late, daemon=True, name="bgjobs-direct").start()
        return None
    finally:
        if c is not None:
            c.close()
    bgj_kick()
    return rid


def bgj_kick():
    """Wakes the loop (starts it when it does not run yet); nothing in the role web (the worker takes the row)."""
    if not bg_here():
        return
    with _LOCK:
        if _Q["thread"] is None or not _Q["thread"].is_alive():
            _Q["thread"] = threading.Thread(target=_loop, daemon=True, name="bgjobs")
            _Q["thread"].start()
    _WAKE.set()


@app.before_request
def _bgj_start():
    if _Q["thread"] is None and bg_here():  # rows left from before a restart run without a new add
        bgj_kick()


def _loop():
    while True:
        n = 0
        try:
            if _SLOTS["busy"] < BGJ_SLOTS:
                with GATE.bg():  # only the taking: the work itself runs outside the gate, as the threads before
                    n = bgj_run_once()
        except Exception as e:  # noqa: BLE001 -- the loop never dies
            print("bgjobs: loop", type(e).__name__, e, flush=True)
            time.sleep(BGJ_IDLE)
        if not n:
            _WAKE.wait(BGJ_IDLE)
            _WAKE.clear()


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
        gone = c.execute("DELETE FROM bg_jobs WHERE (state='done' AND finished_at < ?) OR (state='failed' AND finished_at < ?)",
                         (iso(now - timedelta(hours=BGJ_KEEP_DONE_H)), iso(now - timedelta(days=BGJ_KEEP_FAILED_D)))).rowcount
    c.commit()
    if again or failed:
        print(f"bgjobs: {again} lost run(s) waiting again, {failed} failed", flush=True)
    return {"again": again, "failed": failed, "gone": gone}


def bgj_claim(c):
    """Takes the oldest due row (state run, attempts + 1) without committing: (id, kind, payload, attempts) or None. Two
    takers at once get two different rows (SKIP LOCKED). Only kinds this process knows (a row of another version waits)."""
    now = iso(_now())
    kinds = sorted(BGJ_FNS)
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
            c = connect()
            try:
                with system_ctx(c):  # the queue's own row
                    c.execute("UPDATE bg_jobs SET beat_at=? WHERE id=? AND state='run' AND attempts=?", (iso(_now()), rid, run))
                c.commit()
            finally:
                c.close()
        except Exception as e:  # noqa: BLE001 -- a missed beat only risks a second run after BGJ_LOST
            print("bgjobs: beat", type(e).__name__, flush=True)


def _run(rid, kind, args, run):
    """One row in a thread of its own (a long backup never holds the mails behind it); the row's state afterwards."""
    stop = threading.Event()
    threading.Thread(target=_beat, args=(rid, stop, run), daemon=True, name="bgjobs-beat").start()
    state, error = "done", ""
    try:
        fn = BGJ_FNS.get(kind)
        if fn is None:  # a kind of another version
            state, error = "failed", "unknown kind"
        else:
            fn(*args)
    except Exception as e:  # noqa: BLE001 -- the kinds log their own errors as before
        print("bgjobs:", kind, "failed:", type(e).__name__, e, flush=True)
        state, error = "failed", type(e).__name__
    finally:
        stop.set()
        try:
            _finish(rid, state, error, run)
        except Exception as e:  # noqa: BLE001 -- no database: the housekeeping finds the row without a beat later
            print("bgjobs: finish", rid, type(e).__name__, flush=True)
        with _LOCK:
            _SLOTS["busy"] -= 1
        _WAKE.set()


def bgj_run_once():
    """One round: housekeeping (every BGJ_HOUSE_S s), then the due rows while a slot is free (each in its own thread).
    Returns how many rows were taken."""
    n = 0
    c = connect()
    try:
        bgj_house(c)
        while _SLOTS["busy"] < BGJ_SLOTS:
            r = bgj_claim(c)
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
                _SLOTS["busy"] += 1
            try:
                threading.Thread(target=_run, args=(rid, kind, args, r["attempts"]), daemon=True, name="bgjobs-run").start()
            except Exception as e:  # noqa: BLE001 -- review 2.193.0: no thread = the slot is free again, the row waits
                with _LOCK:
                    _SLOTS["busy"] -= 1
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

