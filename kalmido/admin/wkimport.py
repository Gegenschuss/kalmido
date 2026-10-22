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

from ..core.config import app
from ..core.db import body, connect, db, err, iso, now_utc
from ..core.access import Denied
from ..core.errors import BadInput
from ..core.i18n import lang
from ..core.serializers import unlink_files
from ..accounts.session import me
from ..wiki import wikiatt
from ..wiki.pages import wiki_space
from ..wiki.wikiatt import WKA_FILE_MAX, tr
from ..wiki.wikie2e import wke_guard
from .orgexport import EXPORT_DIR
from .acctexport import UMZ_BLOCK, UmzReader, UmzWriter, umz_key, umz_person, umz_space_ok, umz_user_conn, umz_write_state
from .acctimport import UMZ_CHUNK, _env_mb, _slot, umz_disk_size
from .hosting import quota_guard

WKI_DIR = os.path.join(EXPORT_DIR, "wiki-import")
WKI_MAX_MB = _env_mb("KALMIDO_WIKI_IMPORT_MAX_MB", 4096)
WKI_MAX_FILES = _env_mb("KALMIDO_WIKI_IMPORT_MAX_FILES", 10000)
WKI_KEEP_H = 24  # an upload / result nobody looks at any more is removed after this
WKI_TICK_S = 0.5  # the progress is written at most this often
_WKI = {}  # user id -> running import thread
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


def _busy(uid):
    t = _WKI.get(int(uid))
    return bool(t and t.is_alive())


def _need(uid, iid):
    st = _st(uid, iid)
    if not st:
        raise Denied(404)  # another person's upload is not even there for me (own folder per person)
    return st


def _view(uid, iid, st):
    out = {"id": iid, "state": st.get("state"), "size": st.get("size"), "received": st.get("received"), "name": st.get("name", ""),
           "space": st.get("space") or "private"}
    if st.get("state") == "running" and not _busy(uid):
        out["state"] = "failed"
        out["error"] = tr("The import was interrupted. Please start it again.")
    for k in ("progress", "result", "error"):
        if st.get(k) is not None and k not in out:
            out[k] = st[k]
    return out


def _limits():
    return {"chunk": UMZ_CHUNK, "max_mb": WKI_MAX_MB, "file_mb": WKA_FILE_MAX // (1024 * 1024)}


def wki_cleanup():
    """Watchdog part (acctexport.umz_cleanup): uploads and results older than WKI_KEEP_H hours (not while one runs)."""
    n = 0
    if not os.path.isdir(WKI_DIR):
        return n
    for d in os.listdir(WKI_DIR):
        p = os.path.join(WKI_DIR, d)
        if not d.isdigit() or not os.path.isdir(p) or _busy(int(d)):
            continue
        for iid in os.listdir(p):
            q = os.path.join(p, iid)
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
    """The thread after the last piece: the space is checked again, the ZIP read from the sealed upload and imported."""
    c = connect()
    saved = []
    try:
        umz_user_conn(c, uid)
        wikiatt.WKA_LANG.lg = lang(c, uid)
        st = _st(uid, iid) or {}
        oid = wiki_space(c, uid, st.get("space"), write=True)  # the rights may have changed while the upload ran
        wke_guard(c, oid, uid, kind="import")
        path = os.path.join(_dir(uid, iid), "upload.bin")
        key = umz_key(uid, "wikiupload") if st.get("sealed") else None
        stop = os.path.join(_dir(uid, iid), "stop")
        last = [0.0]
        prog = {"done": 0, "total": 0}

        def tick(n=1):
            prog["done"] += n
            if os.path.exists(stop):
                raise WkiStop()
            if time.monotonic() - last[0] >= WKI_TICK_S:
                last[0] = time.monotonic()
                _set(uid, iid, progress=dict(prog))
        try:
            z = zipfile.ZipFile(io.BufferedReader(UmzReader(path, key, st["size"]), UMZ_BLOCK))
            infos = [i for i in z.infolist() if not i.is_dir()]
        except (zipfile.BadZipFile, ValueError, OSError):
            raise BadInput(tr("This is not a ZIP file"))
        prog["total"] = len(infos)
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
        msg = str(e) if isinstance(e, BadInput) else getattr(e, "msg", None)
        _set(uid, iid, state="failed", error=msg if isinstance(msg, str) and msg else tr("The import failed."))
    except Exception as e:  # noqa: BLE001
        c.rollback()
        unlink_files(saved)
        print(f"wiki import of user {uid} failed: {type(e).__name__}", flush=True)
        _set(uid, iid, state="failed", error=tr("The import failed."))
    finally:
        c.close()
        try:
            os.remove(os.path.join(_dir(uid, iid), "upload.bin"))  # the ZIP is not kept after the run
        except OSError:
            pass
        with _WKI_LOCK:
            _WKI.pop(int(uid), None)


def _thread(uid, iid):
    with _WKI_LOCK:
        if _busy(uid):
            raise Denied(409, tr("An import is already running"))
        lc = _slot()  # the import slots of the server (shared with the account import)
        if lc is None:
            raise Denied(429, tr("Too many imports are running on this server right now. Please try again in a few minutes."))

        def run():
            try:
                wki_run(uid, iid)
            finally:
                lc.close()
        t = threading.Thread(target=run, daemon=True)
        _WKI[int(uid)] = t
        t.start()


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
        _set(uid, iid, state="running", progress={"done": 0, "total": 0})
        try:
            _thread(uid, iid)
        except Denied:
            _set(uid, iid, state="upload", received=off)
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
    st = _need(uid, iid)
    if st.get("state") == "running" and _busy(uid):
        with open(os.path.join(_dir(uid, iid), "stop"), "w"):
            pass
        return jsonify(ok=True, state="stopping"), 202
    shutil.rmtree(_dir(uid, iid), ignore_errors=True)
    return jsonify(ok=True)
