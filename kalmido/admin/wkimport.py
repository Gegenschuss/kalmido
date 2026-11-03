"""2.177.0 (#2685): the ZIP import of knowledge pages for large archives -- uploaded in pieces, unpacked in the background.

Flow (Knowledge > Space menu > Import ZIP, people only; the old single POST /api/wiki/import stays for small ZIPs and agents):
    POST   /api/wiki/import/upload              {size, name, space, replace} -> {id, chunk, max_mb, file_mb}: a new upload
                                                (space rights, a locked space (browser import), size, quota and disk space
                                                checked first)
    PUT    /api/wiki/import/upload/<id>?offset=n the next piece (raw body, `chunk` bytes, the last one shorter); sealed at rest
                                                like the account import's upload (0600, own folder of the person); after the
                                                last piece the import runs in the background
    GET    /api/wiki/import/upload/<id>         state: upload (+ received) | running (+ progress {done, total}) | done
                                                (+ result as POST /api/wiki/import answers) | stopped | failed (+ error)
    GET    /api/wiki/import/upload              my current upload / import (the app picks it up again after a reload)
    DELETE /api/wiki/import/upload/<id>         cancel: the upload goes at once; a running import stops (nothing of it
                                                stays) -- after the end: the result was seen, the folder goes
The import itself is wikiatt._wka_import (the same checks, link rewriting and report as the single POST) with the limits of
this route: KALMIDO_WIKI_IMPORT_MAX_MB (default 4096) for the ZIP and for everything unpacked from it, at most
KALMIDO_WIKI_IMPORT_MAX_FILES entries (default 10000), KALMIDO_WIKI_FILE_MAX_MB per PDF / picture (wiki/wikiatt.py WKA_FILE_MAX).
In the admin package (layer integrations): it uses the upload of the account import (sealed pieces, import slots)."""
import io
import json
import os
import re
import secrets
import shutil
import threading
import time
import zipfile

from flask import jsonify, request

from ..core.config import app, ATT_DIR
from ..core.db import body, connect, db, err, iso, now_utc
from ..core.access import Denied
from ..core.errors import BadInput, BadKey
from ..core.i18n import BG_LANG, N_, lang, tr_stored
from ..core.pg import system_ctx
from ..core.serializers import unlink_files
from ..accounts.session import me
from ..wiki import wikiatt
from ..wiki.pages import wiki_space
from ..wiki.wikiatt import WKA_FILE_MAX, tr
from ..wiki.wikie2e import wke_guard
from .orgexport import EXPORT_DIR
from .acctexport import UMZ_BLOCK, UmzReader, UmzWriter, umz_key, umz_person, umz_space_ok, umz_user_conn, umz_write_state
from .acctimport import UMZ_CHUNK, _env_mb, umz_disk_size, umz_settle, umz_slots_guard  # 2.370.3 (#2760): + the queue's slots
from ..accounts.bgjobs import bgj_add, bgj_busy, bgj_drop, bgj_fn, bgj_lock
from .hosting import quota_guard

WKI_DIR = os.path.join(EXPORT_DIR, "wiki-import")
WKI_MAX_MB = _env_mb("KALMIDO_WIKI_IMPORT_MAX_MB", 4096)
WKI_MAX_FILES = _env_mb("KALMIDO_WIKI_IMPORT_MAX_FILES", 10000)
WKI_KEEP_H = 24  # an upload / result nobody looks at any more is removed after this
WKI_TICK_S = 0.5  # the progress is written at most this often
_WKI = {}  # user id -> running import thread (of this process; 2.370.3 (#2760): the queue row tells it for every process)
_WKI_LOCK = threading.Lock()
_PIECE_LOCK = threading.Lock()  # one piece at a time: two requests at the same offset must not both append


class WkiStop(Exception):
    pass


def _base(uid):
    return os.path.join(WKI_DIR, str(int(uid)))


def _dir(uid, iid):
    if not re.fullmatch(r"[0-9a-f]{24}", str(iid or "")):
        raise Denied(404)
    return os.path.join(_base(uid), iid)


def _st(uid, iid):
    try:
        with open(os.path.join(_dir(uid, iid), "state.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _set(uid, iid, **kw):
    st = _st(uid, iid) or {}
    st.update(kw)
    umz_write_state(_dir(uid, iid), st)
    return st


def _wki_json(path, v):
    with os.fdopen(os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(v, f)
    os.replace(path + ".tmp", path)


def _busy(uid, c=None):
    """2.370.3 (#2760): my import waits or runs: its queue row (any process), or a thread of this process (the queue's
    fallback without a database)."""
    t = _WKI.get(int(uid))
    if t and t.is_alive():
        return True
    try:
        return bgj_busy("wki:import", user_id=int(uid), c=c)
    except Exception:  # noqa: BLE001 -- no database: only this process' thread counts
        return False


def _need(uid, iid):
    st = _st(uid, iid)
    if not st:
        raise Denied(404)  # another person's upload is not even there for me (own folder per person)
    return st


def _view(uid, iid, st):
    lost = False
    if st.get("state") == "running" and not _busy(uid):
        st = _st(uid, iid) or st  # 2.307.1 (CI): the thread may have written its last state and ended after st was read
        lost = st.get("state") == "running" and not _busy(uid)  # #3506: as acctimport._view, only after that fresh read
    out = {"id": iid, "state": st.get("state"), "size": st.get("size"), "received": st.get("received"), "name": st.get("name", ""),
           "space": st.get("space") or "private"}
    if lost:
        out["state"] = "failed"
        out["error"] = tr("The import was interrupted. Please start it again.")
    for k in ("progress", "result", "error"):
        if st.get(k) is not None and k not in out:
            out[k] = st[k]
    if "error" in out:
        out["error"] = tr_stored(out["error"])
    if "result" in out:
        out["result"] = wikiatt.wka_report(out["result"])  # 2.498.0 (#3858): the skipped reasons, for who asks
    return out


def _limits():
    return {"chunk": UMZ_CHUNK, "max_mb": WKI_MAX_MB, "file_mb": WKA_FILE_MAX // (1024 * 1024)}


def _orphans(q):
    """Review M2: a run that died with the server (its rows were rolled back): the files it had stored already go."""
    try:
        with open(os.path.join(q, "saved.json"), encoding="utf-8") as f:
            rels = json.load(f)
    except (OSError, ValueError):
        return
    rels = [r for r in rels if isinstance(r, str) and r.startswith("wiki/") and ".." not in r][:WKI_MAX_FILES]
    if rels:  # a file whose row exists (the run committed just before the server stopped) stays
        c = connect()
        try:
            with system_ctx(c):
                kept = {r["path"] for r in c.execute(f"SELECT path FROM wiki_files WHERE path IN ({','.join('?' * len(rels))})", rels).fetchall()}
            c.rollback()
        finally:
            c.close()
        unlink_files([r for r in rels if r not in kept])
    os.remove(os.path.join(q, "saved.json"))


def wki_cleanup():
    """Watchdog part (acctexport.umz_cleanup): uploads and results older than WKI_KEEP_H hours (not while one runs); the
    stored files of a run the server lost (state running without its thread)."""
    n = 0
    if not os.path.isdir(WKI_DIR):
        return n
    for d in os.listdir(WKI_DIR):
        p = os.path.join(WKI_DIR, d)
        if not d.isdigit() or not os.path.isdir(p) or _busy(int(d)):
            continue
        for iid in os.listdir(p):
            q = os.path.join(p, iid)
            if os.path.exists(os.path.join(q, "saved.json")):
                _orphans(q)
            try:
                old = time.time() - os.path.getmtime(os.path.join(q, "state.json")) > WKI_KEEP_H * 3600
            except OSError:
                old = time.time() - os.path.getmtime(q) > WKI_KEEP_H * 3600
            if old:
                shutil.rmtree(q, ignore_errors=True)
                n += 1
        if not os.listdir(p):
            shutil.rmtree(p, ignore_errors=True)
    return n


# ---------------------------------------------------------------- the background run
def wki_run(uid, iid):
    """The thread after the last piece: the space is checked again, the ZIP read from the sealed upload and imported. One
    transaction as the single POST (review L9: pages replaced with ?replace stay locked for other writers until the end)."""
    c = connect()
    saved = []
    try:
        umz_user_conn(c, uid)
        wikiatt.WKA_LANG.lg = BG_LANG.lg = lang(c, uid)  # 2.498.0 (#3858): a thread of its own, a skipped file builds its text without a connection
        st = _st(uid, iid) or {}
        oid = wiki_space(c, uid, st.get("space"), write=True)  # the rights may have changed while the upload ran
        wke_guard(c, oid, uid, kind="import")
        path = os.path.join(_dir(uid, iid), "upload.bin")
        key = umz_key(uid, "wikiupload") if st.get("sealed") else None
        stop = os.path.join(_dir(uid, iid), "stop")
        last = [0.0, 0]
        prog = {"done": 0, "total": 0}

        def tick(n=1):
            prog["done"] += n
            if os.path.exists(stop):
                raise WkiStop()
            if saved and len(saved) != last[1]:  # review M2: what is stored so far (the watchdog removes it after a crash)
                last[1] = len(saved)
                _wki_json(os.path.join(_dir(uid, iid), "saved.json"), saved)
            if time.monotonic() - last[0] >= WKI_TICK_S:
                last[0] = time.monotonic()
                _set(uid, iid, progress=dict(prog))
        try:
            z = zipfile.ZipFile(io.BufferedReader(UmzReader(path, key, st["size"]), UMZ_BLOCK))
            infos = [i for i in z.infolist() if not i.is_dir()]
        except (zipfile.BadZipFile, ValueError, OSError):
            raise BadKey(N_("This is not a ZIP file"))
        prog["total"] = len(infos)
        if not umz_space_ok(ATT_DIR, min(WKI_MAX_MB * 1024 * 1024, sum(i.file_size for i in infos))):  # review M1: unpacked
            raise BadKey(N_("There is not enough space on the server for the import. Please ask the server admin."))
        _set(uid, iid, progress=dict(prog))
        with z:
            res = wikiatt._wka_import(c, uid, oid, bool(st.get("replace")), z, infos, saved, total=WKI_MAX_MB * 1024 * 1024,
                                      max_files=WKI_MAX_FILES, tick=tick)
        _set(uid, iid, state="done", progress={"done": prog["total"], "total": prog["total"]}, result=res)
    except WkiStop:
        c.rollback()
        unlink_files(saved)
        _set(uid, iid, state="stopped")
    except (BadInput, Denied) as e:
        c.rollback()
        unlink_files(saved)
        # 2.454.0 (#3808): key + values, translated for who asks (wki_state)
        msg = getattr(e, "stored", None) or (str(e) if isinstance(e, BadInput) else getattr(e, "msg", None))
        _set(uid, iid, state="failed", error=msg or [N_("The import failed.")])
    except Exception as e:  # noqa: BLE001
        c.rollback()
        unlink_files(saved)
        print(f"wiki import of user {uid} failed: {type(e).__name__}", flush=True)
        _set(uid, iid, state="failed", error=[N_("The import failed.")])  # 2.448.0 (#3765): key, translated for who asks
    finally:
        c.close()
        for fn in ("upload.bin", "saved.json"):  # the ZIP is not kept after the run; the stored files are in rows or gone
            try:
                os.remove(os.path.join(_dir(uid, iid), fn))
            except OSError:
                pass
        if os.environ.get("KALMIDO_TEST") == "1" and os.environ.get("KALMIDO_TEST_UMZ_END_DELAY"):  # tests only (#3280)
            time.sleep(float(os.environ["KALMIDO_TEST_UMZ_END_DELAY"]))
        with _WKI_LOCK:
            _WKI.pop(int(uid), None)


def _settle(uid):
    """2.363.0 (#3280): the worker publishes "done" and then still tidies up and frees its slot: the person's next step
    right after it waits for that end instead of answering "already running" (as acctimport._thread, #3261). 2.370.3
    (#2760): the end of its queue row."""
    umz_settle(_busy, uid)


@bgj_fn("wki:import", tries=1, long=True)  # 2.370.3 (#2760): one transaction; a lost run says "interrupted", never runs twice
def wki_import_row(uid, iid):
    with _WKI_LOCK:
        _WKI[int(uid)] = threading.current_thread()
    wki_run(uid, iid)


def _thread(uid, iid):
    """2.370.3 (#2760): the import as a queue row (the worker runs it); the import slots of the server are shared with the
    account import (acctimport.umz_slots_guard). The state "running" is written under the queue lock, with the row (review L6)."""
    _settle(uid)

    def guard(qc):
        umz_slots_guard(uid, _busy, qc)
        _set(uid, iid, state="running", progress={"done": 0, "total": 0})
    bgj_add("wki:import", uid, iid, user_id=uid, lock="umz:import", guard=guard)


# ---------------------------------------------------------------- routes
@app.post("/api/wiki/import/upload")
def wki_new():
    """{size, name, space, replace}: a new upload. 413 above KALMIDO_WIKI_IMPORT_MAX_MB, 413 quota_exceeded, 507 without
    disk space, 409 wiki_e2e for a locked space (the browser imports there)."""
    umz_person()
    uid = me()
    b = body()
    size = b.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 22:
        return err(tr("Invalid value: {0}", "size"))
    c = db()
    oid = wiki_space(c, uid, b.get("space"), write=True)
    wke_guard(c, oid, uid, kind="import")
    if size > WKI_MAX_MB * 1024 * 1024:
        return err(tr("The file is too large (at most {0} MB)", WKI_MAX_MB), 413)
    quota_guard(c, uid, size)  # the files in it count against the storage (checked again per file in the run)
    if not umz_space_ok(WKI_DIR, size * 2):
        return err(tr("There is not enough space on the server for the import. Please ask the server admin."), 507)
    _settle(uid)
    if _busy(uid):
        return err(tr("An import is already running"), 409)
    if os.path.isdir(_base(uid)):  # one upload per person: an older one (or an old result) goes
        shutil.rmtree(_base(uid), ignore_errors=True)
    iid = secrets.token_hex(12)
    os.makedirs(_dir(uid, iid), mode=0o700, exist_ok=True)
    key = umz_key(uid, "wikiupload")
    with os.fdopen(os.open(os.path.join(_dir(uid, iid), "upload.bin"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        UmzWriter(f, key).finish()
    name = b.get("name") if isinstance(b.get("name"), str) else ""
    umz_write_state(_dir(uid, iid), {"state": "upload", "size": size, "received": 0, "sealed": bool(key), "name": name[:200],
                                     "space": f"org:{oid}" if oid else "private", "replace": b.get("replace") is True,
                                     "created_at": iso(now_utc())})
    c.rollback()
    return jsonify(id=iid, **_limits())


@app.put("/api/wiki/import/upload/<iid>")
def wki_piece(iid):
    """The next piece of the upload (raw body) at ?offset= (= the bytes received so far)."""
    umz_person()
    uid = me()
    st = _need(uid, iid)
    if st.get("state") != "upload":
        return err(tr("This upload is complete already"), 409)
    try:
        off = int(request.args.get("offset", ""))
    except ValueError:
        return err(tr("Invalid value: {0}", "offset"))
    if off != st["received"]:
        return jsonify(error=tr("Invalid value: {0}", "offset"), received=st["received"]), 409
    n = request.content_length or 0
    last = off + n == st["size"]
    if n <= 0 or n > UMZ_CHUNK or off + n > st["size"] or (not last and n % UMZ_BLOCK):
        return err(tr("Invalid value: {0}", "chunk"))
    data = request.get_data(cache=False)
    if len(data) != n:
        return err(tr("Invalid value: {0}", "chunk"))
    path = os.path.join(_dir(uid, iid), "upload.bin")
    key = umz_key(uid, "wikiupload") if st.get("sealed") else None
    with _PIECE_LOCK:
        if (_st(uid, iid) or {}).get("received") != off:  # another request at the same offset was faster
            return jsonify(error=tr("Invalid value: {0}", "offset"), received=(_st(uid, iid) or {}).get("received")), 409
        with open(path, "ab") as f:
            f.truncate(umz_disk_size(off, bool(key)))  # a piece that broke off half-written: its bytes go (acctimport review N4)
            w = UmzWriter.resume(f, path, key, off)
            w.write(data)
            w.finish()
        _set(uid, iid, received=off + n)
    if last:
        try:
            _thread(uid, iid)
        except Denied:
            _set(uid, iid, received=off)  # the last piece is sent again (429: the client waits and retries)
            raise
    return jsonify(_view(uid, iid, _st(uid, iid)))


@app.get("/api/wiki/import/upload/<iid>")
def wki_state(iid):
    umz_person()
    uid = me()
    return jsonify(_view(uid, iid, _need(uid, iid)))


@app.get("/api/wiki/import/upload")
def wki_current():
    """My current upload / import (the newest), if any, and the limits of the route."""
    umz_person()
    uid = me()
    best = None
    if os.path.isdir(_base(uid)):
        for iid in os.listdir(_base(uid)):
            st = _st(uid, iid) if re.fullmatch(r"[0-9a-f]{24}", iid) else None
            if st and (best is None or st.get("created_at", "") > best[1].get("created_at", "")):
                best = (iid, st)
    return jsonify(current=_view(uid, *best) if best else None, **_limits())


@app.delete("/api/wiki/import/upload/<iid>")
def wki_cancel(iid):
    """Cancels the upload (removed at once) or a running import (it stops at the next file, nothing of it stays: 202);
    after the end the result was seen and the folder goes."""
    umz_person()
    uid = me()
    _need(uid, iid)
    c = db()
    bgj_lock(c, "umz:import")  # review L6: not between "running" and the queue row (2.370.3, #2760: the queue's lock)
    try:
        bgj_drop("wki:import", user_id=uid, c=c)  # 2.370.3 (review 6): a row still waiting for the worker goes
        running = (_st(uid, iid) or {}).get("state") == "running" and _busy(uid, c)
        if running:
            with open(os.path.join(_dir(uid, iid), "stop"), "w"):
                pass
        else:
            try:
                os.replace(_dir(uid, iid), _dir(uid, iid) + ".gone")  # out of the way before the lock ends (review 5)
            except OSError:  # gone already (another cancel)
                pass
    finally:
        c.commit()  # review 5: the lock ends here, the clean-up below holds no import start up
    if running:
        return jsonify(ok=True, state="stopping"), 202
    gone = _dir(uid, iid) + ".gone"
    if os.path.exists(os.path.join(gone, "saved.json")):
        _orphans(gone)
    shutil.rmtree(gone, ignore_errors=True)
    return jsonify(ok=True)
