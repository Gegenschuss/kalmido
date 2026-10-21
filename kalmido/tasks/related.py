"""2.59.0 B (#1375): related tasks, stage 1 -- local text vectors of every task, "Related tasks" in a task, the duplicate hint
while adding, "also similar meaning" in the search, the related tasks in agent events, API v1 / MCP related_tasks.

Kalmido calls no language model. The optional service kalmido-embed (embed/ in the repository, docker compose --profile
embed, KALMIDO_EMBED_URL) turns a text into numbers (a vector) with a small embedding model on the own CPU; nothing leaves
the server. Without the service, or with the instance switch "Related tasks" off (Administration > Server), everything works
as before and the new parts are hidden (enabled: false, empty lists, never an error).

- task_vectors: one row per task (task_id, org_id + list_id like the task's list, model, dim, vec, text_hash, updated_at).
  vec = float16 values, base64; in an organisation with encryption at rest (core/orgcrypt.py) sealed with the organisation's
  key (ctx "task_vectors.vec"), private lists (org_id NULL) plain -- like every other organisation field (orgcrypt never
  encrypts without an organisation). Vectors are derived data: not in the organisation export, recomputed when missing.
- The worker (one thread per process; one batch at a time per database through an advisory lock) embeds the tasks whose
  vector is missing, of another model, older than the task or of another list / organisation. Text = "folder > list >
  parent" + title + description. Trash and health lists: no vectors (a trashed task's vector is dropped); 2.64.1 (#1817): lists
  with the lock neither (the server holds only ciphertexts; the vectors of a list that gets the lock are dropped).
- Finding (rt9_related): cosine over the vectors of the tasks the asker may SEE (the candidates come from the same
  visibility filter as the search: vis_sql + tvis, agents only what is shared with them), mixed with the text similarity of
  the titles (pg_trgm) and explicit references (#123). Pure Python (math.sumprod), the vectors of an organisation cached
  in memory (checked against count + newest updated_at on every use).
"""
import base64
import hashlib
import hmac
import json
import math
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.request
from datetime import timedelta
from operator import mul

from flask import g, jsonify, request

from ..core.config import app, SECRET_KEY
from ..core.db import body, connect, db, err, gset, gsetting, iso_ms, now_utc
from ..core.i18n import tr
from ..core.pg import system_ctx
from ..core.access import Denied, need_task, tvis, vis_sql, acx_lists_sql
from ..api.common import v1_args, v1_view
from ..core.env import env_bool
from ..core.orgcrypt import oc_active, oc_dec, oc_enc, OrgCryptError, PREFIX  # 2.149.0 G (#2517): pulled up from functions
from ..core.serializers import load_tasks  # 2.149.0 G (#2517): pulled up from functions

# ---- the one place for the model-dependent values (part M's measurement; environment overrides for other models) ----------
EMBED_URL = (os.environ.get("KALMIDO_EMBED_URL") or "").strip().rstrip("/")
# 2.59.0 part M (measurement on the dev lists, 16.10.2026): multilingual-e5-small int8, cosine thresholds of that model
EMB_DUP = float(os.environ.get("KALMIDO_RELATED_DUP") or 0.96)     # cosine from which two tasks are "probably duplicates"
EMB_REL = float(os.environ.get("KALMIDO_RELATED_MIN") or 0.90)     # lowest cosine of a related task
EMB_SEARCH = float(os.environ.get("KALMIDO_RELATED_SEARCH") or 0.82)  # lowest cosine of a "similar meaning" search hit (query vs task)
EMB_MIX = os.environ.get("KALMIDO_RELATED_MIX") or "nsum"  # the order of the related tasks, t = trigram similarity of the titles:
#   nsum: (1 - EMB_W_TXT) * clip((cosine - EMB_NORM) / (1 - EMB_NORM), 0, 1) + EMB_W_TXT * t   (M: e5 cosines sit above ~0.84)
#   add: min(1, cosine + EMB_W_TXT * t) | max: max(cosine, 0.5 + t / 2) | sum: (1 - EMB_W_TXT) * cosine + EMB_W_TXT * t
EMB_NORM = float(os.environ.get("KALMIDO_RELATED_NORM") or 0.84)
EMB_W_TXT = 0.25
EMB_REFS = 5            # tasks named by #number (either direction) are shown apart from the similar ones ("ref"), at most this many
EMB_TRGM_MIN = 0.45     # titles at least this similar (pg_trgm) are candidates even without a close vector
EMB_TOP = 30            # vector candidates before mixing
EMB_K = 5               # related tasks shown
EMB_TEXT_MAX = 2000     # characters of a task's text sent to the service (the model reads ~512 tokens anyway)
EMB_BATCH = 32          # tasks per worker batch (the service takes at most 64 texts)
EMB_IDLE = float(os.environ.get("KALMIDO_EMBED_IDLE") or 15)      # seconds between looks when nothing is waiting
EMB_BUSY = float(os.environ.get("KALMIDO_EMBED_BUSY") or 2)       # pause between batches of a backlog (first start: throttled)
EMB_DOWN = float(os.environ.get("KALMIDO_EMBED_DOWN") or 60)  # pause after the service failed
EMB_CLEAN = float(os.environ.get("KALMIDO_EMBED_CLEAN") or 60)  # seconds between two cleanups (emb_cleanup) of a process
EMB_QUERY_TIMEOUT = 1.5  # a live query (hint while adding, search) waits at most this long for the service
EMB_RATE = (6, 10.0)     # live queries per account: at most 6 per 10 s (more: an empty answer without asking the service)
EMB_CTX = "task_vectors.vec"
EMB_BADKEY = 600.0       # seconds an organisation whose key cannot be opened is left out of the batches (per process)
RT9_SETTING = "related_on"  # instance switch (Administration > Server), default on: effective only with KALMIDO_EMBED_URL

_REF = re.compile(r"(?<![\w&])#(\d{1,9})\b")


class EmbedDown(Exception):
    """The service is not set, not reachable or answered wrongly."""


class EmbedBusy(EmbedDown):
    """The service is busy (503: its one model run did not come free in time) -- a short pause, not an outage."""


# ---- the service ----------------------------------------------------------------------------------------------------------
def emb_call(texts, kind="passage", timeout=30):
    """[[float], ...] (L2-normalised) for texts, and the service's model name. EmbedDown on any failure."""
    if not EMBED_URL:
        raise EmbedDown("off")
    req = urllib.request.Request(EMBED_URL + "/embed", data=json.dumps({"texts": texts, "kind": kind}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 -- the admin's own service address (environment)
            j = json.loads(r.read(16 * 1024 * 1024))
        vecs, model = j["vectors"], str(j.get("model") or "")[:200]
        if not isinstance(vecs, list) or len(vecs) != len(texts) or not model:
            raise ValueError("answer")
        return [[float(x) for x in v] for v in vecs], model
    except urllib.error.HTTPError as e:
        raise (EmbedBusy if e.code == 503 else EmbedDown)(type(e).__name__) from None
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as e:
        raise EmbedDown(type(e).__name__) from None


def emb_health(timeout=2):
    """{"ok", "model", "dim"} of the service, or None."""
    if not EMBED_URL:
        return None
    try:
        with urllib.request.urlopen(EMBED_URL + "/health", timeout=timeout) as r:  # noqa: S310 -- the admin's own service address
            j = json.loads(r.read(65536))
        return {"ok": bool(j.get("ok")), "model": str(j.get("model") or "")[:200], "dim": int(j.get("dim") or 0)}
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return None


def rt9_on(c):
    """Related tasks are on: the service is configured and the instance switch is on."""
    if not EMBED_URL:
        return False
    with system_ctx(c):  # instance setting (no content)
        r = c.execute("SELECT value FROM settings WHERE key=?", (RT9_SETTING,)).fetchone()
    return (r[0] if r else "1") != "0"


# ---- vectors: packing, sealing ----------------------------------------------------------------------------------------------
def emb_pack(v):
    return base64.b64encode(struct.pack(f"<{len(v)}e", *v)).decode()


def emb_unpack(s, dim):
    from array import array
    raw = base64.b64decode(s)
    if len(raw) != 2 * dim:
        raise ValueError("dim")
    return array("f", struct.unpack(f"<{dim}e", raw))


def emb_store_val(c, org_id, v):
    """The stored text of vector v: base64 of float16; sealed with the organisation's key when its data is encrypted."""
    return oc_enc(c, org_id, EMB_CTX, emb_pack(v)) if org_id else emb_pack(v)


def emb_load_val(c, org_id, s, dim):
    return emb_unpack(oc_dec(c, org_id, EMB_CTX, s) if org_id else s, dim)


def emb_text(r):
    """The text of a task for its vector: a short context (folder > list > parent) + title + description."""
    pre = " > ".join(x for x in ((r["folder"] or "").strip(), (r["lname"] or "").strip(), (r["ptitle"] or "").strip()) if x)
    t = (r["title"] or "").strip()
    n = (r["content"] or "").strip()
    return ((pre + ": " if pre else "") + t + ("\n" + n if n else ""))[:EMB_TEXT_MAX]


_HKEY = {}


def emb_hash(c, text):
    """HMAC-SHA-256 of a task's text with a key derived from the server key (KALMIDO_SECRET_KEY; without it the instance's
    sign-in secret) -- not a plain hash (no word-list oracle), not the organisation's key (a key change recomputes nothing)."""
    k = _HKEY.get("k")
    if k is None:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        base = SECRET_KEY
        if not base:
            with system_ctx(c):  # instance key material, never handed out
                base = bytes.fromhex(gsetting(c, "auth_secret") or "")
        k = _HKEY["k"] = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                              info=b"kalmido-related-text-hash-v1").derive(base or b"kalmido-related-without-server-key")
    return hmac.new(k, text.encode(), hashlib.sha256).hexdigest()[:32]


def _sumprod(a, b):
    try:
        return math.sumprod(a, b)
    except AttributeError:  # Python < 3.12
        return sum(map(mul, a, b))


# ---- the worker -----------------------------------------------------------------------------------------------------------
_W = {"thread": None, "down": False, "model": "", "last": 0.0, "done": 0, "clean": -EMB_CLEAN}
_WLOCK = threading.Lock()
_WAKE = threading.Event()
_BADORG = {}  # org id -> monotonic time until which its tasks are left out (its key could not be opened)

# the tasks whose vector must be (re)computed: missing, other model, older than the task, other list / organisation, or plain
# in an organisation whose data is encrypted (after "Encrypt organisation data" was switched on)
_STALE_SQL = """SELECT t.id, t.title, t.content, t.list_id, t.updated_at, l.org_id, l.name AS lname, l.folder, p.title AS ptitle,
       v.task_id AS vid, v.text_hash, v.model AS vmodel, v.vec, v.org_id AS vorg
  FROM tasks t JOIN lists l ON l.id=t.list_id LEFT JOIN tasks p ON p.id=t.parent_id LEFT JOIN task_vectors v ON v.task_id=t.id
 WHERE t.deleted_at IS NULL AND COALESCE(l.life, '')!='health' AND l.e2e IS NULL{skip}
   AND (v.task_id IS NULL OR v.model!=? OR v.updated_at < t.updated_at OR v.list_id IS DISTINCT FROM t.list_id
        OR v.org_id IS DISTINCT FROM l.org_id{enc})
 ORDER BY (v.task_id IS NULL) DESC, t.updated_at DESC LIMIT ?"""


def emb_kick():
    """Start the worker (once per process) and wake it."""
    if not EMBED_URL or not env_bool("TASKS_WATCHDOG", True):
        return
    with _WLOCK:
        if _W["thread"] is None or not _W["thread"].is_alive():
            _W["thread"] = threading.Thread(target=emb_loop, daemon=True, name="embed")
            _W["thread"].start()
    _WAKE.set()


@app.before_request
def _emb_start():
    if _W["thread"] is None and EMBED_URL:
        emb_kick()


def emb_loop():
    from ..accounts.session import GATE
    time.sleep(3)
    while True:
        wait = EMB_IDLE
        try:
            with GATE.bg():
                n = emb_run_once()
            if n:
                wait = EMB_BUSY
        except EmbedBusy:
            wait = EMB_BUSY * 5  # live queries keep the service busy: try again soon, no log line
        except EmbedDown as e:
            if not _W["down"]:  # one line per outage, not one per batch
                print("embed: the service is not reachable (", str(e), "), related tasks wait", flush=True)
            _W["down"] = True
            wait = EMB_DOWN
        except Exception as e:  # noqa: BLE001 -- the worker never dies
            print("embed: worker", type(e).__name__, e, flush=True)
            wait = EMB_DOWN
        _WAKE.wait(wait)
        _WAKE.clear()


def emb_run_once(c=None):
    """One batch: compute the stale vectors (at most EMB_BATCH). Returns how many tasks were looked at (0 = nothing to do /
    switched off / another process holds the batch). EmbedDown when the service fails."""
    own = c is None
    c = c or connect()
    try:
        # the cleanup also runs while switched off / the service is down (nothing stale stays readable in another
        # workspace), but at most once a minute and only in the process that holds the lock
        if time.monotonic() - _W["clean"] >= EMB_CLEAN:
            with system_ctx(c):  # the batch lock (no content)
                got = c.execute("SELECT pg_try_advisory_xact_lock(hashtext('kalmido-embed'))").fetchone()[0]
            if got:
                emb_cleanup(c)
                _W["clean"] = time.monotonic()
            c.commit()
        if not rt9_on(c):
            return 0
        # the worker sees every organisation's tasks: server-side computation of derived data, nothing handed to a person
        with system_ctx(c):
            got = c.execute("SELECT pg_try_advisory_xact_lock(hashtext('kalmido-embed'))").fetchone()[0]
            n = _emb_batch(c) if got else 0
        c.commit()
        if not got:
            return 0
        if _W["down"]:
            print("embed: the service answers again", flush=True)
        _W["down"] = False
        return n
    except BaseException:
        c.rollback()
        raise
    finally:
        if own:
            c.close()


def emb_cleanup(c):
    """Drop the vectors of trashed tasks, of health lists and of tasks whose list is now in another workspace / that moved
    to another list (computed again, sealed with the right key): a vector never stays readable outside its task's workspace."""
    with system_ctx(c):  # housekeeping of derived data over every organisation, nothing handed to a person
        c.execute("DELETE FROM task_vectors v USING tasks t, lists l WHERE t.id=v.task_id AND l.id=t.list_id "
                  "AND (t.deleted_at IS NOT NULL OR COALESCE(l.life, '')='health' OR l.e2e IS NOT NULL OR v.org_id IS DISTINCT FROM l.org_id "
                  "OR v.list_id IS DISTINCT FROM t.list_id)")


def _emb_model(c):
    """The service's model name (asked once per process, again after an outage)."""
    if not _W["model"] or _W["down"]:
        h = emb_health(5)
        if not h or not h["ok"] or not h["model"]:
            raise EmbedDown("health")
        _W["model"] = h["model"]
    return _W["model"]


def _emb_batch(c):
    model = _emb_model(c)
    enc = " OR (l.org_id IS NOT NULL AND v.vec NOT LIKE ?)" if oc_active(c) else ""  # pg-ok: kenc1: prefix is case-exact
    now = time.monotonic()
    for k in [k for k, until in _BADORG.items() if until <= now]:
        del _BADORG[k]
    bad = sorted(_BADORG)
    skip = f" AND (l.org_id IS NULL OR l.org_id NOT IN ({','.join('?' * len(bad))}))" if bad else ""
    rows = c.execute(_STALE_SQL.format(enc=enc, skip=skip), (*bad, model, *((PREFIX + "%",) if enc else ()), EMB_BATCH)).fetchall()
    if not rows:
        return 0
    stamp = iso_ms(now_utc() - timedelta(seconds=2))  # a change in the same second as this batch is looked at again
    todo = []
    for r in rows:
        text = emb_text(r)
        h = emb_hash(c, text)
        same = r["vid"] is not None and r["text_hash"] == h and r["vmodel"] == model
        if same and r["vorg"] != r["org_id"]:
            same = False  # another workspace: sealed with another key (or plain) -- computed again, never carried over
        if same and enc and r["org_id"] and not str(r["vec"]).startswith(PREFIX):
            same = False  # plain in an encrypted organisation: computed again (sealed)
        if same:
            c.execute("UPDATE task_vectors SET updated_at=?, list_id=?, org_id=? WHERE task_id=?", (stamp, r["list_id"], r["org_id"], r["id"]))
        else:
            todo.append((r, text, h))
    if todo:
        t0 = time.monotonic()
        vecs, got = emb_call([x[1] for x in todo], "passage")
        if got != model:  # the service was replaced meanwhile: start over with the new model's name
            _W["model"] = got
            return len(rows)
        for (r, _text, h), v in zip(todo, vecs):
            try:
                val = emb_store_val(c, r["org_id"], v)
            except OrgCryptError:
                # the organisation's key cannot be opened: no vector (the related tasks just stay empty there); left out
                # of the batches for EMB_BADKEY instead of being sent to the service again every batch
                if r["org_id"] not in _BADORG:
                    print("embed: organisation", r["org_id"], "key cannot be opened, its tasks wait", flush=True)
                _BADORG[r["org_id"]] = time.monotonic() + EMB_BADKEY
                continue
            c.execute("INSERT INTO task_vectors(task_id, org_id, list_id, model, dim, vec, text_hash, updated_at) VALUES(?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(task_id) DO UPDATE SET org_id=excluded.org_id, list_id=excluded.list_id, model=excluded.model, "
                      "dim=excluded.dim, vec=excluded.vec, text_hash=excluded.text_hash, updated_at=excluded.updated_at",
                      (r["id"], r["org_id"], r["list_id"], model, len(v), val, h, stamp))
        _W["done"] += len(todo)
        _W["last"] = time.monotonic() - t0
    return len(rows)


def emb_drop_org(c, org_id, sealed=None):
    """Called by the encryption passes (admin/orgcrypt_cli.py): drop the vectors of an organisation (sealed=True: only the
    sealed ones, False: only the plain ones, None: all) -- the worker computes them again in the right form."""
    with system_ctx(c):  # orgcrypt pass: server-side bulk work on derived data
        q = "DELETE FROM task_vectors WHERE org_id=?"
        if sealed is not None:
            q += " AND vec " + ("" if sealed else "NOT ") + "LIKE 'kenc1:%'"
        c.execute(q, (int(org_id),))
    rt9_forget(org_id)


def emb_drop_sealed(c):
    """decrypt-all (the way back): no sealed vector stays behind."""
    with system_ctx(c):  # orgcrypt pass: server-side bulk work on derived data
        c.execute("DELETE FROM task_vectors WHERE vec LIKE 'kenc1:%'")  # pg-ok: kenc1: prefix is case-exact
    rt9_forget()


# ---- the cache: the decoded vectors per organisation -----------------------------------------------------------------------
_CACHE = {}  # org id (None = private lists) -> {"sig": (count, newest, model), "model": the worker's model, "vecs": {task id: array},
#              "at": last use (monotonic)}
_CLOCK = threading.Lock()
EMB_CACHE_IDLE = 600.0  # an organisation's vectors nobody used for this long leave the memory


def rt9_forget(org_id=False):
    with _CLOCK:
        if org_id is False:
            _CACHE.clear()
        else:
            _CACHE.pop(org_id, None)


def _org_vectors(c, org_id, ids=()):
    """{task id: vector} of one organisation (None: the private lists), decoded once and kept while nothing changed.
    Only ever used after the caller's visibility filter decided which ids may be compared. 2.82.0 (#1880): the private
    lists of all people are no shared bucket in the cache: for org_id None only the given ids are read, nothing is kept."""
    if org_id is None:
        return fr2a_private_vectors(c, ids)
    cond = "org_id=?" if org_id is not None else "org_id IS NULL"
    args = (org_id,) if org_id is not None else ()
    model = _W["model"]
    # the vectors of the whole organisation are read once for the cache (derived numbers, never handed out: only the ids and
    # titles of tasks the asker may see leave this module)
    with system_ctx(c):
        sig = tuple(c.execute(f"SELECT COUNT(*), MAX(updated_at), MAX(model) FROM task_vectors WHERE {cond}", args).fetchone())
        now = time.monotonic()
        with _CLOCK:
            for k in [k for k, e in _CACHE.items() if now - e["at"] > EMB_CACHE_IDLE]:
                del _CACHE[k]
            hit = _CACHE.get(org_id)
            if hit:
                hit["at"] = now
        if hit and hit["sig"] == sig and hit["model"] == model:
            return hit["vecs"]
        vecs = {}
        for r in c.execute(f"SELECT task_id, dim, vec, model FROM task_vectors WHERE {cond}", args):
            if model and r["model"] != model:
                continue
            try:
                vecs[r["task_id"]] = emb_load_val(c, org_id, r["vec"], r["dim"])
            except (OrgCryptError, ValueError, struct.error):
                continue
    with _CLOCK:
        _CACHE[org_id] = {"sig": sig, "model": model, "vecs": vecs, "at": time.monotonic()}
    return vecs


def fr2a_private_vectors(c, ids):
    """2.82.0 (#1880): {task id: vector} of the given tasks of private lists (no cache: a person's own vectors only)."""
    ids, model, vecs = sorted({int(x) for x in ids}), _W["model"], {}
    with system_ctx(c):  # derived numbers of tasks the caller already filtered by visibility
        for i in range(0, len(ids), 1000):
            part = ids[i:i + 1000]
            for r in c.execute(f"SELECT task_id, dim, vec, model FROM task_vectors WHERE org_id IS NULL AND task_id IN ({','.join('?' * len(part))})",
                               part):
                if model and r["model"] != model:
                    continue
                try:
                    vecs[r["task_id"]] = emb_load_val(c, None, r["vec"], r["dim"])
                except (OrgCryptError, ValueError, struct.error):
                    continue
    return vecs


def _own_vector(c, tid):
    with system_ctx(c):  # the asked task's own vector (the caller checked that the task is visible)
        r = c.execute("SELECT org_id FROM task_vectors WHERE task_id=?", (tid,)).fetchone()
    if not r:
        return None
    return _org_vectors(c, r["org_id"], (tid,)).get(tid)


def _visible(c, uid, exclude=()):
    """{task id: org id} of every task uid may see (the search's filter: lists in scope, participants only their own tasks --
    not the context parents --, no trash)."""
    rows = c.execute(f"SELECT t.id, l.org_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.list_id IN {vis_sql()} "
                     f"AND t.deleted_at IS NULL AND {tvis(c, uid, 't.', write=True)}", (uid, uid)).fetchall()
    ex = set(exclude)
    return {r[0]: r[1] for r in rows if r[0] not in ex}


def _visible_agent(c, aid, exclude=()):
    """{task id: org id} an agent sees outside a request of its own (events): its lists (the list scope without the
    request's token filter), never a health list, only its selected lists (agents.list_ids), only its workspace."""
    from ..agents.core import agent_row
    from ..agents.safety import ids_parse
    a = agent_row(c, aid)
    if not a:
        return {}
    rows = c.execute(f"SELECT t.id, l.org_id, l.id AS lid FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.list_id IN "
                     f"{acx_lists_sql(req=False)} AND t.deleted_at IS NULL AND COALESCE(l.life, '') NOT IN ('health', 'budget') AND l.e2e IS NULL "
                     f"AND {tvis(c, aid, 't.', write=True)}", (aid, aid)).fetchall()
    only = set(ids_parse(a["list_ids"])) if a["list_ids"] else None
    ex = set(exclude)
    return {r[0]: r[1] for r in rows if r[0] not in ex and (only is None or r[2] in only)
            and (r[1] is None or r[1] == a["org_id"] or not a["org_id"])}


def _score_vec(c, qv, vis, top=EMB_TOP):
    """[(cosine, task id)] of the visible tasks closest to qv (best first)."""
    by_org = {}
    for tid, oid in vis.items():
        by_org.setdefault(oid, []).append(tid)
    out = []
    for oid, ids in by_org.items():
        vecs = _org_vectors(c, oid, ids)
        for tid in ids:
            v = vecs.get(tid)
            if v is not None and len(v) == len(qv):
                out.append((_sumprod(qv, v), tid))
    out.sort(reverse=True)
    return out[:top]


def _cos_of(c, qv, tid, oid):
    v = _org_vectors(c, oid, (tid,)).get(tid) if qv is not None else None
    return _sumprod(qv, v) if v is not None and len(v) == len(qv) else None


def _rank(cos, trg):
    """The order of a candidate: cosine (None = no vector) mixed with the trigram similarity of the titles (0 = none)."""
    if cos is None:
        return EMB_W_TXT * trg
    if EMB_MIX == "nsum":
        return (1 - EMB_W_TXT) * min(1.0, max(0.0, (cos - EMB_NORM) / (1 - EMB_NORM))) + EMB_W_TXT * trg
    if EMB_MIX == "max":
        return max(cos, 0.5 + trg / 2)
    if EMB_MIX == "sum":
        return (1 - EMB_W_TXT) * cos + EMB_W_TXT * trg
    return min(1.0, cos + EMB_W_TXT * trg)


def _mix(c, qv, title, text, cos, vis, k, own=None):
    """Related = cosine >= EMB_REL (or an almost equal title without a vector), ordered by _rank, without the task's own
    parent / subtasks; "probably a duplicate" = cosine >= EMB_DUP. Plus, apart, the tasks named by #number in either
    direction (own = the asked task's id). All only among vis. -> [(score, id, dup, ref)]."""
    cs = {tid: s for s, tid in cos}
    trg = {}
    t = (title or "").strip()[:300]
    ids = sorted(vis)
    if t:
        for i in range(0, len(ids), 5000):
            part = ids[i:i + 5000]
            for r in c.execute(f"SELECT id, similarity(title, ?) FROM tasks WHERE id IN ({','.join('?' * len(part))}) "
                               "AND similarity(title, ?) >= ?", (t, *part, t, EMB_TRGM_MIN)):
                trg[r[0]] = float(r[1])
                if r[0] not in cs:
                    cs[r[0]] = _cos_of(c, qv, r[0], vis[r[0]])
    near = set()
    if own:  # the parent and the subtasks are shown by the task itself
        near = {r[0] for r in c.execute("SELECT id FROM tasks WHERE parent_id=? OR id=(SELECT parent_id FROM tasks WHERE id=?)", (own, own))}
    sim = []
    for tid, cv in cs.items():
        if tid == own or tid in near:
            continue
        g = trg.get(tid, 0.0)
        if (cv is not None and cv >= EMB_REL) or (cv is None and g >= 0.9):
            sim.append((round(_rank(cv, g), 4), tid, cv is not None and cv >= EMB_DUP, False))
    sim.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    sim = sim[:k]
    refs = {int(x) for x in _REF.findall(text or "")} & set(vis)
    if own:  # the tasks that name this one (#own) in their title or description
        pat = f"%#{int(own)}%"
        for i in range(0, len(ids), 5000):
            part = ids[i:i + 5000]
            for r in c.execute(f"SELECT id, title, content FROM tasks WHERE id IN ({','.join('?' * len(part))}) "
                               "AND (title LIKE ? OR content LIKE ?)", (*part, pat, pat)):  # pg-ok: #<number> has no case
                if int(own) in {int(x) for x in _REF.findall((r[1] or "") + "\n" + (r[2] or ""))}:
                    refs.add(r[0])
    shown = {x[1] for x in sim}
    extra = sorted(refs - shown - {own})[:EMB_REFS]
    return sim + [(round(_rank(cs.get(x), trg.get(x, 0.0)), 4), x, False, True) for x in extra]


def _items(c, scored):
    if not scored:
        return []
    ids = [x[1] for x in scored]
    rows = {r["id"]: r for r in c.execute(f"SELECT id, title, list_id, status FROM tasks WHERE id IN ({','.join('?' * len(ids))})", ids)}
    return [{"id": tid, "title": rows[tid]["title"], "list_id": rows[tid]["list_id"], "done": rows[tid]["status"] != 0,
             "score": s, "dup": bool(d), "ref": bool(rf)} for s, tid, d, rf in scored if tid in rows]


def rt9_related(c, uid, tid, k=EMB_K):
    """{"enabled", "pending", "items"} -- the tasks related to tid among those uid may see. The caller checked that uid sees
    tid. pending: tid has no vector yet (the worker computes it)."""
    if not rt9_on(c):
        return {"enabled": False, "pending": False, "items": []}
    qv = _own_vector(c, tid)
    if qv is None:
        return {"enabled": True, "pending": True, "items": []}
    t = c.execute("SELECT title, content FROM tasks WHERE id=?", (tid,)).fetchone()
    vis = _visible(c, uid, exclude=(tid,))
    scored = _mix(c, qv, t["title"], (t["title"] or "") + "\n" + (t["content"] or ""), _score_vec(c, qv, vis), vis, k, own=tid)
    return {"enabled": True, "pending": False, "items": _items(c, scored)}


def rt9_event(c, tid, aid, k=EMB_K):
    """The related tasks of an agent event ([{"id", "title", "score"}] the agent may see), or None: switched off, or the
    task has no vector yet (the field is left out then). From the cache only, never a call to the service."""
    try:
        if not rt9_on(c):
            return None
        qv = _own_vector(c, tid)
        if qv is None:
            return None
        vis = _visible_agent(c, aid, exclude=(tid,))
        near = {r[0] for r in c.execute("SELECT id FROM tasks WHERE parent_id=? OR id=(SELECT parent_id FROM tasks WHERE id=?)", (tid, tid))}
        scored = [(round(s, 4), x, s >= EMB_DUP, False) for s, x in _score_vec(c, qv, vis, k + len(near)) if s >= EMB_REL and x not in near][:k]
        return [{"id": i["id"], "title": i["title"], "score": i["score"]} for i in _items(c, scored)]
    except Exception as e:  # noqa: BLE001 -- an event never fails because of its extra field
        print("embed: event", type(e).__name__, e, flush=True)
        return None


_QSEM = threading.BoundedSemaphore(2)  # live queries at once per process: the worker's batches never starve
_RATE = {}  # user id -> [times of the live queries in the last EMB_RATE[1] seconds]
_RLOCK = threading.Lock()


def rt9_rate_ok(uid):
    """False when uid asked more than EMB_RATE live queries lately (per process; the answer is then empty, no service call)."""
    n, win = EMB_RATE
    now = time.monotonic()
    with _RLOCK:
        if len(_RATE) > 1000:  # forget the quiet accounts
            for k in [k for k, v in _RATE.items() if not v or now - v[-1] > win]:
                del _RATE[k]
        q = [t for t in _RATE.get(uid, ()) if now - t < win]
        ok = len(q) < n
        if ok:
            q.append(now)
        _RATE[uid] = q
    return ok


def rt9_query(c, text, kind):
    """The vector of a live text (hint while adding, search), or None (off, slow, down, two queries already running):
    never waits longer than EMB_QUERY_TIMEOUT."""
    if not _QSEM.acquire(blocking=False):
        return None
    try:
        vecs, model = emb_call([text[:EMB_TEXT_MAX]], kind, timeout=EMB_QUERY_TIMEOUT)
    except EmbedDown:
        return None
    finally:
        _QSEM.release()
    if _W["model"] and model != _W["model"]:
        return None  # the stored vectors are of another model (the worker switches over)
    _W["model"] = model
    from array import array
    return array("f", vecs[0])


def rt9_similar(c, uid, title, notes="", list_id=None, exclude=None, k=EMB_K):
    """{"enabled", "items"}: visible tasks similar to a task being added (title + description, the list as context)."""
    if not rt9_on(c):
        return {"enabled": False, "items": []}
    title = (title or "").strip()[:500]
    if len(title) < 3 or not rt9_rate_ok(uid):
        return {"enabled": True, "items": []}
    pre = ""
    if list_id:
        r = c.execute(f"SELECT name, folder FROM lists WHERE id=? AND id IN {vis_sql()}", (list_id, uid, uid)).fetchone()
        if r:
            pre = " > ".join(x for x in ((r["folder"] or "").strip(), (r["name"] or "").strip()) if x)
    notes = (notes or "")[:EMB_TEXT_MAX]
    vis = _visible(c, uid, exclude=(exclude,) if exclude else ())
    qv = rt9_query(c, (pre + ": " if pre else "") + title + ("\n" + notes if notes else ""), "passage")
    cos = _score_vec(c, qv, vis) if qv is not None else []
    return {"enabled": True, "items": _items(c, _mix(c, qv, title, title + "\n" + notes, cos, vis, k))}


def rt9_semantic(c, uid, q, have, limit=20):
    """Task ids of a "similar meaning" search: visible tasks whose vector is close to the query, without the ids in have."""
    if not rt9_on(c) or not q.strip() or not rt9_rate_ok(uid):
        return []
    qv = rt9_query(c, q.strip()[:500], "query")
    if qv is None:
        return []
    vis = _visible(c, uid, exclude=have)
    return [tid for s, tid in _score_vec(c, qv, vis, limit) if s >= EMB_SEARCH]


def rt9_search_extend(c, uid, q, rows, limit):
    """2.59.0 B (#1375): the search with semantic=1 -- the text hits, then the visible tasks of similar meaning (flag "similar")."""
    ids = rt9_semantic(c, uid, q, {r["id"] for r in rows}, max(0, min(20, limit - len(rows))))
    if not ids:
        return rows
    order = {tid: i for i, tid in enumerate(ids)}
    extra = load_tasks(c, f"id IN ({','.join('?' * len(ids))}) AND deleted_at IS NULL AND list_id IN {vis_sql()} AND {tvis(c, uid, write=True)}",
                       (*ids, uid, uid))
    for t in extra:
        t["similar"] = True
    return rows + sorted(extra, key=lambda t: order.get(t["id"], 0))


# ---- routes -----------------------------------------------------------------------------------------------------------------
@app.get("/api/related/config")
def rt9_config():
    """Whether the app shows the related tasks (the client hides everything otherwise)."""
    c = db()
    return jsonify(enabled=rt9_on(c), dup=EMB_DUP)


@app.get("/api/tasks/<int:tid>/related")
def rt9_route_related(tid):
    c = db()
    need_task(c, tid, write=False, full=True)  # a participant's context parent (title only) = 404: its cosines echo its notes
    return jsonify(rt9_related(c, g.user["id"], tid))


@app.post("/api/tasks/similar")
def rt9_route_similar():
    """{title, notes?, list_id?, exclude?} -> {enabled, items}: the hint while adding a task (nothing is stored)."""
    c, b = db(), body()
    try:
        lid = int(b.get("list_id")) if b.get("list_id") not in (None, "") else None
        ex = int(b.get("exclude")) if b.get("exclude") not in (None, "") else None
    except (TypeError, ValueError):
        return err(tr("Invalid value: {0}", "list_id"))
    from ..collab.liste2e import le2e_mode
    if lid and le2e_mode(c, lid):  # 2.64.1 (#1817): a list with the lock gets no hints (its titles stay in the browser)
        return jsonify(enabled=True, items=[])
    return jsonify(rt9_similar(c, g.user["id"], str(b.get("title") or ""), str(b.get("notes") or ""), lid, ex))


@app.get("/api/admin/related")
def rt9_admin_get():
    from ..accounts.users import need_admin
    need_admin()
    c = db()
    on = True
    with system_ctx(c):  # instance status for the admin: counts only, no content
        r = c.execute("SELECT value FROM settings WHERE key=?", (RT9_SETTING,)).fetchone()
        on = (r[0] if r else "1") != "0"
        done = c.execute("SELECT COUNT(*) FROM task_vectors").fetchone()[0]
        total = c.execute("SELECT COUNT(*) FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.deleted_at IS NULL "
                          "AND COALESCE(l.life, '')!='health' AND l.e2e IS NULL").fetchone()[0]
    h = emb_health(2) if EMBED_URL else None
    return jsonify(configured=bool(EMBED_URL), on=on, reachable=bool(h and h["ok"]), model=(h or {}).get("model") or None,
                   dim=(h or {}).get("dim") or None, done=done, open=max(0, total - done))


@app.put("/api/admin/related")
def rt9_admin_put():
    from ..accounts.users import need_admin
    need_admin()
    c, b = db(), body()
    on = b.get("on") in (1, True, "1", "true")
    with system_ctx(c):  # instance setting
        gset(c, RT9_SETTING, "1" if on else "0")
    c.commit()
    if on:
        emb_kick()
    return rt9_admin_get()


# ---- API v1 -----------------------------------------------------------------------------------------------------------------
@app.get("/api/v1/tasks/<int:tid>/related")
@v1_view
def rt9_v1_related(tid):
    """The related tasks of a task (read): only tasks the token's user may see."""
    v1_args(())
    c = db()
    need_task(c, tid, write=False, full=True)  # a participant's context parent (title only) = 404: its cosines echo its notes
    return jsonify(rt9_related(c, g.user["id"], tid))


def rt9_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI: related tasks + the search's semantic parameter (called from openapi_spec)."""
    schemas["RelatedTask"] = {"type": "object", "description": "2.59.0 (#1375): a task related to another one (same meaning by local "
                              "text vectors, similar title or an explicit #reference); only tasks the caller may see", "properties": {
        "id": {"type": "integer"}, "title": {"type": "string"}, "list_id": {"type": "integer"}, "done": {"type": "boolean"},
        "score": {"type": "number", "description": "0..1, higher = closer"},
        "dup": {"type": "boolean", "description": "probably a duplicate (score above the server's duplicate threshold)"}}}
    paths["/tasks/{id}/related"] = {"get": op(
        "Related tasks of a task (2.59.0)", "Tasks",
        ok({"type": "object", "properties": {
            "enabled": {"type": "boolean", "description": "false: the server runs without the embedding service or switched it off"},
            "pending": {"type": "boolean", "description": "true: the task's vector is not computed yet (try again in a minute)"},
            "items": {"type": "array", "items": ref("RelatedTask"), "description": "at most 5, best first"}}}) | errs("404"),
        [pid("id", "Task id")],
        desc="Up to five tasks close in meaning to this one, among the tasks you may see. Computed on the server by a local "
             "embedding model (no language model, nothing leaves the server). Read-only.")}
    s = paths.get("/search", {}).get("get")
    if s is not None:
        s.setdefault("parameters", []).append(q("semantic", "2.59.0 (#1375): 1 = after the text hits also tasks of similar meaning "
                                                "(flag similar: true; tasks only, needs the embedding service)", {"type": "string", "enum": ["0", "1"]}))

