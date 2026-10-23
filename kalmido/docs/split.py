"""2.154.0 A (#1111): a stack scan (one PDF of several letters) split into documents by its archive number codes.

The recognition run (store.process) reads the QR / bar codes of every page of a PDF with two pages or more (sp_detect, at
most SP_PAGES pages): a page with a NEW archive number (prefix + digits, docs/extract.find_asn) starts a document, pages
without a code belong to the one before (back / following pages), a separator sheet (a QR code with SP_SEP) starts one
too and is dropped itself. Pages before the first code become a document without an archive number (with a hint). A page
counts as blank when almost no ink is on it (dark pixels inside the margins below SP_INK) AND the text recognition finds
hardly any text on it; without text recognition only nearly white pages (SP_INK_SURE) -- in doubt a page stays.

With two codes or more (or a separator sheet between pages) the document is marked "Stack - split?" (doc_meta.split_scan
state "open", To review). Nothing is split without a person: GET .../split gives the pages and the proposed cuts, the
preview moves / removes / sets cuts and drops blank pages, POST .../split makes the documents (pypdf in a limited child
process like tasks/attachtext.py) in the stack's folder, with its shares, through the same recognition (ingest); the
stack goes to the trash. POST .../unsplit is the undo (the new documents into the trash, the stack back with its archive
number). Agents never reach these routes; the workspace boundary stays (the folder of the stack, never another one).

doc_meta.split_scan: JSON (no content of the document, only numbers): {v, n (pages), pages: [{asn, sep, ink, blank}],
state: open | none | single | long | done, parts? (ids after a split), asn? (the stack's own number before it), from?
(a part: the stack's id), no_asn? (a part: the pages before the first code)}."""
import base64
import json
import os
import re
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import threading

from flask import Response, g, jsonify, request

from ..core.config import app
from ..core.db import body, bump, db, err, iso, now_utc
from ..core.i18n import tr
from ..core.access import Denied
from ..accounts.session import me
from ..files.store import fs_log_add, fs_read, need_node
from . import store as S
from . import ocr as O

SP_PAGES = O._env_int("KALMIDO_SPLIT_PAGES", 100, 2, 500)  # pages of a stack at most
SP_SEP = "KALMIDO-SPLIT"     # the text of the separator sheet's QR code
SP_DPI = 200                 # like the archive number of the first page (ocr.qr_codes)
SP_INK = 0.004               # share of dark pixels below which a page may be blank (text recognition decides)
SP_INK_SURE = 0.0008         # ... and without text recognition: only this little
SP_TEXT = 12                 # visible characters at most on a blank page
SP_THUMB_W = 180
SP_THUMBS = 12               # previews per request
_THUMB_SEM = threading.BoundedSemaphore(2)  # 2.154.0 E (#1111): preview renders at the same time at most


def _now():
    return iso(now_utc())


def _no_agent():
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403)


# a limited child process reads the codes and the ink of page images: 2.209.0 C (#2589) one at a time, a path per line on
# stdin, its result as one JSON line (the caller renders the next page only then and deletes this one after reading it)
SCAN_WORKER = r"""
import ctypes, ctypes.util, json, os, resource, sys
for k, v in ((resource.RLIMIT_AS, 768 << 20), (resource.RLIMIT_CPU, 240), (resource.RLIMIT_FSIZE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
from PIL import Image
Image.MAX_IMAGE_PIXELS = 80_000_000
lib = ctypes.CDLL(ctypes.util.find_library("zbar") or "libzbar.so.0") if ctypes.util.find_library("zbar") else None
P = ctypes.c_void_p
if lib:
    for fn, res, args in (("zbar_image_scanner_create", P, []), ("zbar_image_scanner_set_config", ctypes.c_int, [P, ctypes.c_int, ctypes.c_int, ctypes.c_int]),
                          ("zbar_image_create", P, []), ("zbar_image_set_format", None, [P, ctypes.c_ulong]),
                          ("zbar_image_set_size", None, [P, ctypes.c_uint, ctypes.c_uint]),
                          ("zbar_image_set_data", None, [P, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]),
                          ("zbar_scan_image", ctypes.c_int, [P, P]), ("zbar_image_first_symbol", P, [P]),
                          ("zbar_symbol_next", P, [P]), ("zbar_symbol_get_data", ctypes.c_char_p, [P]),
                          ("zbar_image_destroy", None, [P]), ("zbar_image_scanner_destroy", None, [P])):
        f = getattr(lib, fn)
        f.restype, f.argtypes = res, args
def codes(im):
    if not lib:
        return []
    data = im.tobytes()
    sc = lib.zbar_image_scanner_create()
    lib.zbar_image_scanner_set_config(sc, 0, 0, 1)
    img = lib.zbar_image_create()
    lib.zbar_image_set_format(img, ord("Y") | ord("8") << 8 | ord("0") << 16 | ord("0") << 24)
    lib.zbar_image_set_size(img, im.width, im.height)
    buf = ctypes.create_string_buffer(data, len(data))
    lib.zbar_image_set_data(img, ctypes.cast(buf, ctypes.c_void_p), len(data), None)
    out = []
    if lib.zbar_scan_image(sc, img) > 0:
        sym = lib.zbar_image_first_symbol(img)
        while sym and len(out) < 20:
            out.append((lib.zbar_symbol_get_data(sym) or b"").decode("utf-8", "replace")[:200])
            sym = lib.zbar_symbol_next(sym)
    lib.zbar_image_destroy(img)
    lib.zbar_image_scanner_destroy(sc)
    return out
def page(p):
    try:
        im = Image.open(p).convert("L")
    except Exception:
        return {"codes": [], "ink": 1.0}
    if im.width * im.height > 12_000_000:
        im.thumbnail((3000, 4200))
    w, h = im.size
    mx, my = int(w * 0.06), int(h * 0.06)
    hist = im.crop((mx, my, w - mx, h - my)).histogram()
    total = sum(hist) or 1
    return {"codes": codes(im), "ink": round(sum(hist[:128]) / total, 5)}
while True:
    line = sys.stdin.readline()
    if not line:
        break
    sys.stdout.write(json.dumps(page(line.strip())) + "\n")
    sys.stdout.flush()
"""
SP_WORKER_S = 60             # s one page may take in the reader above

# pypdf in a limited child process: the stack's bytes on stdin, the parts (1-based page numbers) as argv; out: per part
# 8 bytes length + the PDF
CUT_WORKER = r"""
import io, json, resource, struct, sys
for k, v in ((resource.RLIMIT_AS, 1024 << 20), (resource.RLIMIT_CPU, 120), (resource.RLIMIT_FSIZE, 0), (resource.RLIMIT_CORE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
import logging, warnings
logging.disable(logging.CRITICAL)
warnings.simplefilter("ignore")
from pypdf import PdfReader, PdfWriter
parts = json.loads(sys.argv[1])
src = sys.stdin.buffer.read()
r = PdfReader(io.BytesIO(src))
if r.is_encrypted and not r.decrypt(""):
    sys.exit(3)
out = sys.stdout.buffer
budget = 4 * len(src) + (32 << 20)  # 2.154.0 E (#1111): the parts together never grow far past the stack
for pages in parts:
    w = PdfWriter()
    for p in pages:
        w.add_page(r.pages[p - 1])
    b = io.BytesIO()
    w.write(b)
    budget -= len(b.getvalue())
    if budget < 0:
        sys.exit(4)
    out.write(struct.pack(">Q", len(b.getvalue())) + b.getvalue())
"""


def _pdf_of(c, nid, m, node):
    """The bytes of a PDF document or None (another kind)."""
    from ..tasks.attachtext import file_kind
    data = fs_read(c, nid)
    return data if file_kind(node["name"], node["mime"], data[:2048]) == "pdf" else None


def sp_scan(data, pages, prefix):
    """[{asn, sep, ink, blank}] of the first min(pages, SP_PAGES) pages of PDF bytes; None when it cannot be read (no
    tools, busy, damaged). 2.209.0 C (#2589): page by page -- render one, read it, delete its image -- so at most one page
    image lies in the temp folder."""
    if not shutil.which("pdftoppm"):
        return None
    n = min(int(pages or 0), SP_PAGES)
    if n < 2:
        return None
    if not O._SEM.acquire(timeout=O.OCR_PAGE_S * 2):  # one heavy reader at a time (like the text recognition)
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="kspl-") as tmp:
            src = os.path.join(tmp, "in.pdf")
            with open(src, "wb") as f:
                f.write(data)
            try:
                w = subprocess.Popen([sys.executable, "-I", "-c", SCAN_WORKER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, bufsize=0, close_fds=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
            except OSError:
                return None
            try:
                return _sp_pages(w, tmp, src, n, prefix)
            finally:
                try:
                    w.stdin.close()
                except OSError:
                    pass
                w.kill()
                w.wait()
    finally:
        O._SEM.release()


def _sp_pages(w, tmp, src, n, prefix):
    """The page loop of sp_scan with the reader process w; None when the reader fails or stalls."""
    ocr = O.ocr_available()
    out, fails = [], 0
    for i in range(1, n + 1):
        png = os.path.join(tmp, f"p-{i}.png")
        try:
            O._run(["pdftoppm", "-r", str(SP_DPI), "-gray", "-f", str(i), "-l", str(i), "-singlefile", "-png", src, png[:-4]],
                   O.OCR_PAGE_S, fsize=32 << 20)
        except subprocess.TimeoutExpired:
            fails += 1  # 2.154.0 E (#1111): a stack of slow pages does not hold the reader for minutes
            if fails >= 2:
                return None
        try:
            w.stdin.write((png + "\n").encode())
            if not select.select([w.stdout], [], [], SP_WORKER_S)[0]:
                return None
            x = json.loads(w.stdout.readline() or b"null")
        except (OSError, ValueError):
            return None
        if not isinstance(x, dict):
            return None
        codes = [str(t) for t in (x.get("codes") or [])][:20]
        ink = float(x.get("ink") or 0)
        sep = any(t.strip().upper() == SP_SEP for t in codes)
        asn = None if sep else S.EX.find_asn(prefix, codes)
        blank = False
        if not sep and asn is None and ink < SP_INK:
            if ocr:
                try:
                    txt = O._tess(png, O.OCR_PAGE_S)
                    blank = len(re.sub(r"\s+", "", txt)) <= SP_TEXT
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    blank = False
            else:
                blank = ink < SP_INK_SURE
        out.append({"asn": asn, "sep": sep, "ink": round(ink, 5), "blank": blank})
        try:
            os.unlink(png)
        except FileNotFoundError:
            pass
    return out


def sp_plan(pages):
    """The proposed cuts of scanned pages: (starts [0-based page indices that begin a document], drop [separator pages],
    stack = two documents or more found by codes / separator sheets)."""
    starts, drop, cur, pending, codes = [], [], None, False, 0
    for i, p in enumerate(pages):
        if p.get("sep"):
            drop.append(i)
            pending = True
            continue
        if p.get("asn") is not None and p["asn"] != cur:
            starts.append(i)
            cur, codes = p["asn"], codes + 1
        elif pending or not starts:
            starts.append(i)
            cur = None
        pending = False
    return starts, drop, codes >= 2 or (bool(drop) and len(starts) >= 2)


def _get(m):
    try:
        v = json.loads(m["split_scan"] or "{}")
    except (KeyError, IndexError, TypeError, ValueError):
        v = {}
    return v if isinstance(v, dict) else {}


def _put(c, nid, v):
    c.execute("UPDATE doc_meta SET split_scan=? WHERE node_id=?", (json.dumps(v, separators=(",", ":")), nid))


def sp_detect(c, nid, data, res):
    """Called by the recognition run (store.process) with the document's bytes: scan a PDF of two pages or more, mark a
    stack (To review). A decision already made (state none / done) stays; a part keeps where it came from (the pages
    before the first code stay in To review for their hint)."""
    m = S.meta_row(c, nid)
    if not m:
        return
    cur = _get(m)
    if cur.get("no_asn") and not m["asn"]:
        c.execute("UPDATE doc_meta SET review=1 WHERE node_id=?", (nid,))
    if res.get("kind") != "pdf" or int(res.get("pages") or 0) < 2:
        return
    if cur.get("state") in ("none", "done"):
        return
    keep = {k: cur[k] for k in ("from", "no_asn") if k in cur}
    n = int(res.get("pages") or 0)
    if n > SP_PAGES:
        _put(c, nid, {**keep, "v": 1, "n": n, "state": "long"})
        return
    pages = sp_scan(data, n, S.cfg_get(c, m["ws"])["asn_prefix"])
    if pages is None:
        return
    stack = sp_plan(pages)[2]
    _put(c, nid, {**keep, "v": 1, "n": n, "pages": pages, "state": "open" if stack else "single", "at": _now()})
    if stack:
        c.execute("UPDATE doc_meta SET review=1 WHERE node_id=?", (nid,))


def sp_scan_queued(c):
    """2.209.0 C (#2589): the queue (docs/ingest.py, while no document waits) reads the pages of one document the split
    preview asked for (state "scan"); it goes back to its state before with the scan, or with "unread" when it cannot be
    read (the preview says so once). Returns 1 when it took one."""
    r = c.execute("SELECT node_id FROM doc_meta WHERE split_scan ILIKE '%\"state\":\"scan\"%' LIMIT 1").fetchone()
    if not r:
        return 0
    nid = r[0]
    m = S.meta_row(c, nid)
    v = _get(m)
    keep = {k: x for k, x in v.items() if k not in ("state", "was", "at")}
    was = {"state": v["was"]} if v.get("was") else {}
    pages = None
    try:
        node = c.execute("SELECT name, mime, deleted_at FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        data = _pdf_of(c, nid, m, node) if node and not node["deleted_at"] and (m["pages"] or 0) >= 2 else None
        pages = sp_scan(data, m["pages"], S.cfg_get(c, m["ws"])["asn_prefix"]) if data is not None else None
    except Exception as e:  # noqa: BLE001 -- a broken file must not keep the queue on it
        print("docs: split scan", nid, type(e).__name__, e, flush=True)
    if pages is None:
        _put(c, nid, {**keep, **was, "unread": 1})
    else:
        st = "done" if v.get("was") == "done" else "open" if sp_plan(pages)[2] else "single"
        _put(c, nid, {**keep, "v": 1, "n": m["pages"], "pages": pages, "state": st, "at": _now()})
    return 1


def sp_view(m):
    """What a document's JSON carries: {stack} while it waits for a decision, {from, no_asn} on a part; None else."""
    v = _get(m)
    out = {}
    if v.get("state") == "open":
        out["stack"] = True
    if v.get("from"):
        out["from"] = v["from"]
        if v.get("no_asn"):
            out["no_asn"] = True
    return out or None


# ---- routes (people only) ------------------------------------------------------------------------------------------------
def _stack(c, nid, write=False):
    n = need_node(c, nid, write=write)
    m = S.meta_row(c, nid)
    if not m or n["kind"] != "file":
        raise Denied(404)
    return m, n


@app.get("/api/docs/<int:nid>/split")
def docs_split_get(nid):
    """The pages of a PDF document with the proposed cuts: {pages: n, scan: [{asn, sep, blank}], starts, drop, stack,
    prefix}. A document never scanned (older than 2.154): 2.209.0 C (#2589) 202 {scanning, pages} -- the queue reads its
    pages (sp_scan_queued), the preview asks again."""
    _no_agent()
    c = db()
    m, n = _stack(c, nid, write=True)
    if m["state"] in ("wait", "run"):
        return err(tr("The document is still being recognised"), 409)
    v = _get(m)
    pages = v.get("pages")
    if not isinstance(pages, list):  # 2.154.0 E (#1111): a split stack keeps its scan (no new read)
        if (m["pages"] or 0) > SP_PAGES:
            return err(tr("A stack has at most {0} pages", SP_PAGES), 413)
        if v.get("unread"):  # the queue could not read it: say so once, the next look asks again
            _put(c, nid, {k: x for k, x in v.items() if k != "unread"})
            c.commit()
            return err(tr("The pages cannot be read right now, try again later"), 503)
        if (m["pages"] or 0) < 2 or _pdf_of(c, nid, m, n) is None:
            return err(tr("Only a PDF with two pages or more can be split"), 409)
        if v.get("state") != "scan":
            _put(c, nid, {**v, "state": "scan", "was": v.get("state") or "", "at": _now()})
            c.commit()
            from .ingest import docs_kick
            docs_kick()
        return jsonify(scanning=True, pages=m["pages"]), 202
    starts, drop, stack = sp_plan(pages)
    return jsonify(pages=len(pages), scan=[{"asn": p.get("asn"), "sep": bool(p.get("sep")), "blank": bool(p.get("blank"))} for p in pages],
                   starts=starts, drop=drop, stack=stack, prefix=S.cfg_get(c, m["ws"])["asn_prefix"])


@app.get("/api/docs/<int:nid>/split/thumbs")
def docs_split_thumbs(nid):
    """?from=1 (1-based): small JPEG previews of SP_THUMBS pages from there -> {thumbs: [{page, src (data URI) | null}]}."""
    _no_agent()
    c = db()
    m, n = _stack(c, nid)
    try:
        first = max(1, int(request.args.get("from") or 1))
    except ValueError:
        return err(tr("Invalid value: {0}", "from"))
    last = min(int(m["pages"] or 0), SP_PAGES, first + SP_THUMBS - 1)
    if first > last or not shutil.which("pdftoppm"):
        return jsonify(thumbs=[])
    data = _pdf_of(c, nid, m, n)
    if data is None:
        return jsonify(thumbs=[])
    if not _THUMB_SEM.acquire(timeout=20):
        return err(tr("The pages cannot be read right now, try again later"), 503)
    try:
        out = _thumbs(data, first, last)
    finally:
        _THUMB_SEM.release()
    resp = jsonify(thumbs=out)
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


def _thumbs(data, first, last):
    out = []
    with tempfile.TemporaryDirectory(prefix="ksth-") as tmp:
        src = os.path.join(tmp, "in.pdf")
        with open(src, "wb") as f:
            f.write(data)
        for i in range(first, last + 1):
            base = os.path.join(tmp, f"t{i}")
            src_uri = None
            try:
                r = O._run(["pdftoppm", "-f", str(i), "-l", str(i), "-singlefile", "-scale-to", str(SP_THUMB_W), "-jpeg", "-jpegopt",
                            "quality=70", src, base], 30, fsize=8 << 20)
                if r.returncode == 0 and os.path.exists(base + ".jpg"):
                    with open(base + ".jpg", "rb") as f:
                        src_uri = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
            except (OSError, subprocess.SubprocessError):
                src_uri = None
            out.append({"page": i, "src": src_uri})
    return out


def _parts_clean(raw, n):
    """[[page, ...], ...] (1-based, ascending, each page once, at least two parts) or a ValueError."""
    if not isinstance(raw, list) or not 2 <= len(raw) <= n:
        raise ValueError("parts")
    seen, last, out = set(), 0, []
    for part in raw:
        if not isinstance(part, list) or not part:
            raise ValueError("parts")
        ps = []
        for p in part:
            if not isinstance(p, int) or isinstance(p, bool) or not 1 <= p <= n or p in seen or p <= last:
                raise ValueError("parts")
            seen.add(p)
            last = p
            ps.append(p)
        out.append(ps)
    return out


def _cut(data, parts):
    p = subprocess.run([sys.executable, "-I", "-c", CUT_WORKER, json.dumps(parts)], input=data, capture_output=True,
                       timeout=180, close_fds=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    if p.returncode != 0:
        raise ValueError("encrypted" if p.returncode == 3 else "unreadable")  # 4 = output budget exceeded
    out, b, i = [], p.stdout, 0
    while i + 8 <= len(b):
        ln = struct.unpack(">Q", b[i:i + 8])[0]
        out.append(b[i + 8:i + 8 + ln])
        i += 8 + ln
    if len(out) != len(parts):
        raise ValueError("unreadable")
    return out


@app.post("/api/docs/<int:nid>/split")
def docs_split(nid):
    """{parts: [[1, 2], [3], ...]} (1-based pages; pages left out are dropped: blank pages, separator sheets) -> the new
    documents in the stack's folder (with its shares), the stack into the trash. 201 {ids, stack_id}."""
    from ..admin.hosting import QuotaExceeded
    from .ingest import docs_ingest, docs_kick
    _no_agent()
    c = db()
    uid = me()
    from ..core.pg import write_lock
    write_lock(c, f"docs_split_{int(nid)}")  # 2.154.0 E (#1111): a double click splits once (the second one sees state done)
    m, n = _stack(c, nid, write=True)
    if m["state"] in ("wait", "run"):
        return err(tr("The document is still being recognised"), 409)
    v = _get(m)
    if v.get("state") == "done":
        return err(tr("This stack was already split"), 409)
    total = int(m["pages"] or 0)
    if total > SP_PAGES:
        return err(tr("A stack has at most {0} pages", SP_PAGES), 413)
    try:
        parts = _parts_clean(body().get("parts"), total)
    except ValueError:
        return err(tr("Invalid value: {0}", "parts"))
    data = _pdf_of(c, nid, m, n)
    if data is None:
        return err(tr("Only a PDF with two pages or more can be split"), 409)
    try:
        pdfs = _cut(data, parts)
    except (ValueError, OSError, subprocess.SubprocessError) as e:
        return err(tr(S.ERRORS.get(str(e), S.ERRORS["unreadable"])), 422)
    scan = v.get("pages") if isinstance(v.get("pages"), list) else []
    asn_of = lambda ps: next((scan[p - 1].get("asn") for p in ps if p - 1 < len(scan) and scan[p - 1].get("asn") is not None), None)  # noqa: E731
    own_asn = m["asn"]
    stem = re.sub(r"\.pdf$", "", n["name"], flags=re.I)[:110] or "document"
    ids, have_code = [], False
    try:
        with c.savepoint():
            c.execute("UPDATE doc_meta SET asn=NULL WHERE node_id=?", (nid,))  # the stack's number goes to its part (2.154.0 E: undone on a failure)
            for i, (ps, pdf) in enumerate(zip(parts, pdfs), 1):
                a = asn_of(ps)
                pid = docs_ingest(c, uid, n["org_id"], f"{stem} ({i}).pdf", pdf, "application/pdf", m["source"], parent_id=n["parent_id"])
                fs_log_add(c, pid, "upload", "split")
                extra = {"from": nid}
                if a is not None and not S.asn_taken(c, m["ws"], a, pid):
                    c.execute("UPDATE doc_meta SET asn=?, auto=? WHERE node_id=?", (a, json.dumps({"asn": "code"}), pid))
                    have_code = True
                elif not have_code:
                    extra["no_asn"] = True  # the pages before the first code
                    c.execute("UPDATE doc_meta SET review=1 WHERE node_id=?", (pid,))
                _put(c, pid, extra)
                c.execute("INSERT INTO fs_shares(node_id, user_id, group_id, agent_id, role, expires_at, created_by, created_at) "
                          "SELECT ?, user_id, group_id, agent_id, role, expires_at, created_by, created_at FROM fs_shares WHERE node_id=?", (pid, nid))
                ids.append(pid)
    except QuotaExceeded:
        c.rollback()
        return err(tr("Your storage is full"), 413)
    except ValueError as e:
        c.rollback()
        return err(str(e))
    except Denied as e:  # 2.154.0 E (#1111): e.g. no write right in the stack's folder
        c.rollback()
        return err(e.msg or tr("No permission (view only)"), 403)
    c.execute("UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE id=?", (_now(), uid, nid))
    fs_log_add(c, nid, "trash", "split")
    _put(c, nid, {**v, "state": "done", "parts": ids, "asn": own_asn})
    c.execute("UPDATE doc_meta SET review=0 WHERE node_id=?", (nid,))
    bump(c)
    c.commit()
    docs_kick()
    return jsonify(ids=ids, stack_id=nid), 201


@app.post("/api/docs/<int:nid>/unsplit")
def docs_unsplit(nid):
    """The undo of a split: its documents into the trash, the stack back (with its archive number when it is still free)."""
    _no_agent()
    c = db()
    uid = me()
    n = need_node(c, nid, write=True, trash=True)
    m = S.meta_row(c, nid)
    v = _get(m) if m else {}
    if not m or v.get("state") != "done":
        return err(tr("This stack was not split"), 409)
    if n["role"] != "owner" and n["deleted_by"] != uid:
        raise Denied(403)
    ts = _now()
    for pid in [int(x) for x in v.get("parts") or [] if isinstance(x, int)]:
        pm = S.meta_row(c, pid)
        if not pm or _get(pm).get("from") != nid:
            continue
        try:
            need_node(c, pid, write=True, trash=True)
        except Denied:
            continue
        c.execute("UPDATE doc_meta SET asn=NULL WHERE node_id=?", (pid,))
        c.execute("UPDATE fs_nodes SET deleted_at=?, deleted_by=? WHERE id=? AND deleted_at IS NULL", (ts, uid, pid))
        fs_log_add(c, pid, "trash", "unsplit")
    from ..files.store import _free_name
    nm = _free_name(c, n["parent_id"], n["owner_id"], n["org_id"], n["name"], skip=nid)
    c.execute("UPDATE fs_nodes SET deleted_at=NULL, deleted_by=NULL, name=? WHERE id=?", (nm, nid))
    fs_log_add(c, nid, "restore", "unsplit")
    a = v.get("asn")
    if isinstance(a, int) and not S.asn_taken(c, m["ws"], a, nid):
        c.execute("UPDATE doc_meta SET asn=? WHERE node_id=?", (a, nid))
    rest = {k: x for k, x in v.items() if k not in ("parts", "asn")}
    _put(c, nid, {**rest, "state": "open"})
    c.execute("UPDATE doc_meta SET review=1 WHERE node_id=?", (nid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/docs/<int:nid>/split/dismiss")
def docs_split_dismiss(nid):
    """{undo?: true} -- "No stack": the mark goes (undo: it comes back)."""
    _no_agent()
    c = db()
    m, _n = _stack(c, nid, write=True)
    v = _get(m)
    if v.get("state") == "done":
        return err(tr("This stack was already split"), 409)
    _put(c, nid, {**v, "state": "open" if body().get("undo") is True else "none"})
    from ..receipts.suggest import rc_review
    rc_review(c, nid)
    if body().get("undo") is True:
        c.execute("UPDATE doc_meta SET review=1 WHERE node_id=?", (nid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.get("/api/docs/split-sheet.pdf")
def docs_split_sheet():
    """The separator sheet to print: a QR code with SP_SEP and a short text (A4, vectors only)."""
    _no_agent()
    me()
    from ..office.pdf import _Page, pdf_write, A4_W
    import segno
    p = _Page()
    rows = [[bool(x) for x in row] for row in segno.make(SP_SEP, error="m", micro=False).matrix]
    size, nmod = 170.0, len(rows) or 1
    mod, x0, y0 = size / nmod, (A4_W - size) / 2, 150.0
    for i, row in enumerate(rows):
        j = 0
        while j < nmod:
            if not row[j]:
                j += 1
                continue
            k = j
            while k < nmod and row[k]:
                k += 1
            p.rect(x0 + j * mod, y0 + i * mod, (k - j) * mod + 0.02, mod + 0.02, "#000000")
            j = k
    p.text(0, 90, tr("Separator sheet"), 22, True, "#111111", align="c", width=A4_W)
    p.text(0, y0 + size + 30, tr("Put this sheet between two documents of a stack scan."), 11, False, "#333333", align="c", width=A4_W)
    p.text(0, y0 + size + 48, tr("Kalmido starts a new document after it; the sheet itself is left out."), 11, False, "#333333", align="c", width=A4_W)
    pdf = pdf_write([p], {}, title=tr("Separator sheet"))
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": 'inline; filename="separator-sheet.pdf"',
                                                              "Cache-Control": "private, max-age=3600"})
