"""2.112.1 A (#2058): actions on several nodes of the file store at once, the ZIP download and the phone scan.

POST /api/files/trash {ids}      several rows into the trash (a folder with everything in it), all or nothing
POST /api/files/restore {ids}    the undo of it: every id back out of the trash, all or nothing
GET  /api/files/zip?ids=1,2,3    the chosen files and folders as one ZIP (only what the person may see)
POST /api/files/scan             photographed pages (multipart "page", in order) -> ONE PDF, stored like an upload

The rights are the ones of the single routes (files/web.py): write on every node to trash / restore it, a node at the top
of a space only by its owner. The ZIP takes what the person can see (files/store.py fs_visible_ids), nothing from the trash,
no links (their original has its own rights), no file the virus scanner locked or has not checked yet (scan.py sc_guard).
fs_zip_build is the shared core (external folder links use it with their own check).
"""
import io
import os
import re
import tempfile
import threading
import warnings
import zipfile

from flask import jsonify, request, send_file

from ..core.config import app, MAX_FILE_MB
from ..core.db import bump, db, body, err, local_now
from ..core.i18n import tr
from ..core.access import Denied
from ..accounts.session import me
from .store import DEPTH_MAX, fs_chain, fs_log_add, fs_put, fs_read, fs_role, fs_visible_ids, need_node, safe_fs_name, _free_name, _now
from .fsref import fs_ref_need_move, fs_ref_trashed, fs_trash_prepare, fs_trash_restored  # 2.199.0 A (#2742); 2.238.0 A (#2863)
from .fsroots import fs_area_before, fs_area_root_need_free  # 2.199.0 F (#2742, review G1); 2.200.0 (#2747)
from .fslock import fl_is_locked, fsl_denied, fsl_map  # 2.353.0 A (#2758); F: + scan

ABM_IDS_MAX = 500  # ids per request
ABM_ZIP_MAX_MB = int(os.environ.get("KALMIDO_FILES_ZIP_MAX_MB", "1024"))
ABM_ZIP_MAX_FILES = int(os.environ.get("KALMIDO_FILES_ZIP_MAX_FILES", "5000"))
ABM_SCAN_PAGES = 30  # pages per scan
ABM_SCAN_MAX_MB = 60  # the pages of one scan together (the phone scales them before sending)
# 2.112.1 (#2058, review): at most two ZIPs / scans are built at once per server process (temp disk, CPU, memory)
ABM_BUSY = threading.BoundedSemaphore(2)
ABM_SCAN_EDGE = 2000  # the long edge of a page in the PDF (pixels)
ABM_SCAN_DPI = 180  # 2000 px at 180 dpi ~ the long edge of an A4 page
# already packed: stored as they are (packing again costs time and wins nothing)
ABM_PACKED = {"zip", "gz", "tgz", "bz2", "xz", "7z", "rar", "zst", "jpg", "jpeg", "png", "gif", "webp", "avif", "heic", "heif",
              "mp3", "m4a", "aac", "ogg", "opus", "mp4", "m4v", "mov", "mkv", "webm", "avi", "pdf", "docx", "xlsx", "pptx",
              "odt", "ods", "odp", "epub", "jar", "apk"}


def abm_ids(v):
    """The node ids of a request ({ids: [..]} or "1,2,3"): ints, unique, in order; 400 when empty or too many."""
    if isinstance(v, str):
        v = [x for x in v.split(",") if x.strip()]
    if not isinstance(v, list) or not v:
        raise Denied(400, tr("Invalid value: {0}", "ids"))
    out = []
    try:
        for x in v:
            i = int(x)
            if i > 0 and i not in out:
                out.append(i)
    except (TypeError, ValueError):
        raise Denied(400, tr("Invalid value: {0}", "ids")) from None
    if not out or len(out) > ABM_IDS_MAX:
        raise Denied(400, tr("Invalid value: {0}", "ids"))
    return out


def abm_outermost(c, ids):
    """ids without the ones lying inside another chosen folder (that folder takes them along)."""
    s = set(ids)
    return [i for i in ids if not any(r["id"] in s for r in fs_chain(c, i)[1:])]


@app.post("/api/files/trash")
def files_bulk_trash():
    """{ids}: every node into the trash like DELETE /api/files/nodes/<id> -- each one checked first, then all at once."""
    c = db()
    uid = me()
    ids = abm_ids(body().get("ids"))
    for i in ids:
        n = need_node(c, i, write=True)
        if n["parent_id"] is None and n["role"] != "owner":
            raise Denied(403)
        fs_area_root_need_free(c, i)  # 2.199.0 F (#2742, review G1)
        fs_area_before(c, uid, n)  # 2.200.0 (#2747, review): a closed area's rule may refuse, like DELETE /api/files/nodes/<id>
    from ..office.periodlock import pl_tree_need_open
    for i in ids:
        pl_tree_need_open(c, i)  # 2.148.0 A (#2471) like DELETE /api/files/nodes/<id> (CI of 2.223.1)
    ids = abm_outermost(c, ids)
    kept, refs = [], []
    for i in ids:  # 2.199.0 A (#2742): what may not go into the trash moves one level up first (a protected node refuses)
        k, r = fs_trash_prepare(c, uid, c.execute("SELECT * FROM fs_nodes WHERE id=?", (i,)).fetchone())
        kept += k
        refs += r
    ts = _now()
    for i in ids:
        c.execute("UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE id=?", (ts, uid, i))
        fs_log_add(c, i, "trash")
    for r in refs:
        fs_ref_trashed(c, uid, r, False)
    bump(c)
    c.commit()
    return jsonify(ok=True, ids=ids, kept=kept)


@app.post("/api/files/restore")
def files_bulk_restore():
    """{ids}: every node back out of the trash like POST /api/files/nodes/<id>/restore (a taken name gets " (2)")."""
    c = db()
    uid = me()
    ids = abm_ids(body().get("ids"))
    rows = []
    for i in ids:
        n = need_node(c, i, write=True, trash=True)
        if n["deleted_at"] and n["role"] != "owner" and n["deleted_by"] != uid:
            raise Denied(403)
        if n["deleted_at"]:
            fs_ref_need_move(c, uid, n, restore=True)  # 2.238.0 A (#2863) like POST /api/files/nodes/<id>/restore
        rows.append(n)
    from ..office.periodlock import pl_tree_need_open
    for n in rows:
        if n["deleted_at"]:
            pl_tree_need_open(c, n["id"])  # 2.237.0 B (#2864) like POST /api/files/nodes/<id>/restore: all or nothing
    for n in rows:
        if not n["deleted_at"]:
            continue
        nm = _free_name(c, n["parent_id"], n["owner_id"], n["org_id"], n["name"], skip=n["id"])
        c.execute("UPDATE fs_nodes SET deleted_at=NULL, deleted_by=NULL, name=? WHERE id=?", (nm, n["id"]))
        fs_log_add(c, n["id"], "restore")
        fs_trash_restored(c, uid, n)  # 2.199.0 A (#2742)
    bump(c)
    c.commit()
    return jsonify(ok=True, ids=[n["id"] for n in rows])


# ---- the ZIP
def abm_zip_name(name):
    """A safe name of one path part: no separators, no "..", no control characters, never empty."""
    s = re.sub(r"[\x00-\x1f\x7f/\\:]", "_", str(name or "")).strip().lstrip(".").strip()
    return s[:180] or "file"


def abm_unique(name, taken, folder=False):
    """name, or "name (2).ext" ... when the folder of the ZIP has it already (case-insensitive); notes the result in taken."""
    nm = name
    if not folder and "." in name.strip("."):
        stem, dot, ext = name.rpartition(".")
    else:
        stem, dot, ext = name, "", ""
    i = 2
    while nm.lower() in taken:
        nm = f"{stem} ({i}){dot}{ext}"
        i += 1
    taken.add(nm.lower())
    return nm


def abm_too_big(files, size, max_files=None, max_mb=None):
    """The refusal text when a ZIP would hold too much, else None (the limits of ABM_ZIP_MAX_FILES / ABM_ZIP_MAX_MB or lower ones)."""
    mf, mm = min(max_files or ABM_ZIP_MAX_FILES, ABM_ZIP_MAX_FILES), min(max_mb or ABM_ZIP_MAX_MB, ABM_ZIP_MAX_MB)
    if files > mf or size > mm * 1024 * 1024:
        return tr("Too much for one ZIP: at most {0} files and {1} MB. Please choose fewer.", mf, mm)
    return None


def abm_readable(c, n):
    """May this file's current version go out at all (not locked by the virus scanner, not waiting for it)?"""
    from .scan import sc_guard
    try:
        sc_guard(c, "fs", n["id"], n["cur_version"])
    except Denied:
        return False
    return True


def abm_plan(c, roots, can_read):
    """[(path in the ZIP, node row or None for a folder)] of roots and everything below them that can_read lets through:
    no trash, no links / pages, no locked files; the folder structure kept, names made unique per folder."""
    out, seen, top = [], set(), set()

    def walk(n, prefix, taken, lvl):
        if n["id"] in seen or n["deleted_at"] or n["kind"] not in ("file", "folder") or not can_read(c, n):
            return
        seen.add(n["id"])
        if n["kind"] == "file":
            if n["cur_version"] and abm_readable(c, n):
                out.append((prefix + abm_unique(abm_zip_name(n["name"]), taken), n))
            return
        path = prefix + abm_unique(abm_zip_name(n["name"]), taken, folder=True) + "/"
        out.append((path, None))
        if lvl >= DEPTH_MAX:
            return
        sub = set()
        for k in c.execute("SELECT * FROM fs_nodes WHERE parent_id=? AND deleted_at IS NULL ORDER BY kind DESC, lower(name), id", (n["id"],)).fetchall():
            walk(k, path, sub, lvl + 1)

    for r in roots:
        walk(r, "", top, 1)
    return out


def abm_zip_plan(c, roots, can_read, max_files=None, max_mb=None):
    """(plan, files): abm_plan with the limits checked -- Denied(409) when nothing can go into the ZIP, Denied(413) when
    the limits are passed."""
    plan = abm_plan(c, roots, can_read)
    if not plan:
        raise Denied(409, tr("Nothing here can be downloaded"))
    files = [n for _, n in plan if n is not None]
    msg = abm_too_big(len(files), sum(int(n["size"] or 0) for n in files), max_files, max_mb)
    if msg:
        raise Denied(413, msg)
    return plan, files


def fs_zip_build(c, roots, can_read, on_file=None, max_files=None, max_mb=None):
    """The ZIP of roots (node rows: files and folders) in a temporary file -> (path of the file, name for the download).
    can_read(c, node row) -> bool decides for every node (a folder it refuses is left out with everything below it).
    Refuses with Denied(413) before writing anything when the limits are passed (no half ZIP). on_file(c, node row) is
    called for every file written (the access history). The caller sends the file and removes it (abm_send_zip / abm_drop).
    Denied(429) while two ZIPs are being built already."""
    plan, _files = abm_zip_plan(c, roots, can_read, max_files, max_mb)
    if not ABM_BUSY.acquire(blocking=False):
        raise Denied(429, tr("Too many requests"))
    if len(roots) == 1 and roots[0]["kind"] == "folder":
        name = abm_zip_name(roots[0]["name"]) + ".zip"
    else:
        name = f"Kalmido-Dateien-{local_now().strftime('%Y-%m-%d')}.zip"
    fd, path = tempfile.mkstemp(prefix="kalmido-zip-", suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as f, zipfile.ZipFile(f, "w", allowZip64=True) as z:
            for p, n in plan:
                if n is None:
                    z.writestr(zipfile.ZipInfo(p), b"")
                    continue
                try:
                    data = fs_read(c, n["id"])
                except (OSError, Denied):  # a damaged / missing stored file: left out, the rest still comes
                    continue
                ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
                packed = ext in ABM_PACKED or (n["mime"] or "").startswith(("image/", "video/", "audio/"))
                z.writestr(p, data, compress_type=zipfile.ZIP_STORED if packed else zipfile.ZIP_DEFLATED)
                if on_file:
                    on_file(c, n)
    except BaseException:
        os.unlink(path)
        raise
    finally:
        ABM_BUSY.release()
    return path, name


def abm_drop(path):
    """Removes a built ZIP that is not sent (an error between building and sending)."""
    try:
        os.unlink(path)
    except OSError:
        pass


def abm_send_zip(path, name):
    """The ZIP as a download; the temporary file is gone once the answer is sent (opened, then unlinked)."""
    f = open(path, "rb")  # noqa: SIM115 -- closed by the response
    os.unlink(path)
    resp = send_file(f, mimetype="application/zip", as_attachment=True, download_name=name, max_age=0)
    resp.headers["Cache-Control"] = "private, no-cache"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.get("/api/files/zip")
def files_zip():
    """?ids=1,2,3: the chosen files and folders (with what is in them) as one ZIP; a single folder -> "<folder>.zip".
    &check=1: only the check before the download ({files, size} or the refusal), nothing is read or written."""
    c = db()
    ids = abm_ids(request.args.get("ids") or "")
    roots = [need_node(c, i) for i in abm_outermost(c, ids)]  # links are left out (abm_plan)
    vis = fs_visible_ids(c)
    vis -= set(fsl_map(c, list(vis)))  # 2.353.0 A (#2758): ciphertexts of a locked folder stay out (the browser opens them one by one)
    if request.args.get("check") == "1":
        _plan, files = abm_zip_plan(c, roots, lambda c2, n: n["id"] in vis)
        return jsonify(files=len(files), size=sum(int(n["size"] or 0) for n in files))
    path, name = fs_zip_build(c, roots, lambda c2, n: n["id"] in vis, on_file=lambda c2, n: fs_log_add(c2, n["id"], "download"))
    try:
        c.commit()
        return abm_send_zip(path, name)
    except BaseException:
        abm_drop(path)
        raise


# ---- the phone scan: pages -> one PDF
def abm_pdf(pages, rots, bw):
    """The bytes of a PDF with one page per image (bytes): EXIF orientation applied, turned by rots[i] degrees (clockwise),
    the long edge at most ABM_SCAN_EDGE, grey + auto contrast when bw. Pillow's guard against decompression bombs stays on
    (its warning is an error here). No EXIF / location goes into the PDF (the pages are drawn again)."""
    from PIL import Image, ImageOps
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        for i, data in enumerate(pages):
            try:
                im = Image.open(io.BytesIO(data))
                im.load()
            except (Image.DecompressionBombWarning, Image.DecompressionBombError):
                raise ValueError(tr("Page {0}: the picture is too large", i + 1)) from None
            except Exception:  # noqa: BLE001 -- not a picture Pillow can read
                raise ValueError(tr("Page {0}: not a picture", i + 1)) from None
            im = ImageOps.exif_transpose(im)
            rot = rots[i] if i < len(rots) else 0
            if rot:
                im = im.rotate(-rot, expand=True)
            im.thumbnail((ABM_SCAN_EDGE, ABM_SCAN_EDGE))
            if bw:
                im = ImageOps.autocontrast(im.convert("L"), cutoff=1)
            else:
                im = im.convert("RGB")
            out.append(Image.frombytes(im.mode, im.size, im.tobytes()))  # pixels only: no metadata comes along
    buf = io.BytesIO()
    out[0].save(buf, "PDF", save_all=True, append_images=out[1:], resolution=ABM_SCAN_DPI, quality=80)
    return buf.getvalue()


@app.post("/api/files/scan")
def files_scan():
    """multipart: page (repeatable, in order), rot (repeatable, 0 / 90 / 180 / 270 per page), name, bw (1 / 0), parent_id
    or space (like the upload). Stores ONE PDF like an upload (rights, quota, virus scan, text recognition).
    out=pdf: nothing is stored, the answer is the PDF (the documents file it through their own upload, docs/web.py)."""
    from .upsafe import h6d_read
    from .web import _parent_arg, _items
    c = db()
    pages = request.files.getlist("page")
    if not pages:
        return err(tr("File missing"))
    if len(pages) > ABM_SCAN_PAGES:
        return err(tr("At most {0} pages per scan", ABM_SCAN_PAGES))
    rots = []
    for v in request.form.getlist("rot"):
        try:
            r = int(v) % 360
        except (TypeError, ValueError):
            r = 0
        rots.append(r if r in (0, 90, 180, 270) else 0)
    out_pdf = request.form.get("out") == "pdf"
    pid, oid = _parent_arg(c, request.form) if not out_pdf else (None, None)
    uid = me()
    if pid:  # 2.353.0 F (#2758, review M6): a locked folder takes no plain scan -- refused before the pages are read (rights first: 404)
        if fl_is_locked(c, pid) and fs_role(c, pid, uid):
            raise fsl_denied("fs_locked")
    name = str(request.form.get("name") or "").strip()[:150] or f"Scan {local_now().strftime('%Y-%m-%d %H-%M')}"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    datas = []
    for f in pages:
        d = h6d_read(f)
        if len(d) > MAX_FILE_MB * 1024 * 1024:
            return err(tr("{0}: larger than {1} MB", f.filename or "?", MAX_FILE_MB))
        datas.append(d)
    if sum(len(d) for d in datas) > ABM_SCAN_MAX_MB * 1024 * 1024:  # 2.112.1 (#2058, review): memory of one scan
        return err(tr("{0}: larger than {1} MB", tr("Scan"), ABM_SCAN_MAX_MB))
    if not ABM_BUSY.acquire(blocking=False):
        return err(tr("Too many requests"), 429)
    try:
        try:
            pdf = abm_pdf(datas, rots, request.form.get("bw", "1") != "0")
        finally:
            ABM_BUSY.release()
        if out_pdf:
            resp = send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=True, download_name=safe_fs_name(name), max_age=0)
            resp.headers["Cache-Control"] = "private, no-store"
            return resp
        nid = fs_put(c, uid, pid, name, pdf, "application/pdf", org_id=oid)
    except ValueError as e:
        c.rollback()
        return err(str(e))
    fs_log_add(c, nid, "upload")
    from ..docs.recog import rc_after_add, rc_kick
    added = rc_after_add(c, nid, uid)  # 2.353.0 D (#2759): a scan into a recognising folder = a document
    bump(c)
    c.commit()
    rc_kick(added)
    rows = [c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()]
    return jsonify(items=_items(c, rows)), 201
