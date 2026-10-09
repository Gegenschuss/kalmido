"""2.34.0 (#368): the text of an attachment for agents ("read attachment") and for the briefing field (#260).

PDFs: the text layer, read by pypdf in its own short-lived Python process (python -I -c WORKER): the file comes on stdin,
the process runs with a time limit, a memory limit (RLIMIT_AS), no new processes and no file writes, and reads at most
PDF_PAGES pages / TEXT_CAP characters -- a malicious or broken file can only kill that process. Scanned PDFs without a
text layer get no_text_layer (no OCR). Text files: their text. Images: a pointer to the file (the MCP tool returns it as
an image). The result is cached per file content (sha256) below the data folder (textcache/, not part of backups)."""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from flask import jsonify, request

from ..core.config import app, ATT_DIR, DB
from ..core.i18n import N_, tr
from ..core.db import db, err
from ..core.access import Denied, need_task
from ..tasks.attachments import file_ext, need_attachment, TEXT_MIME
from ..tasks.validation import as_int
from ..accounts.session import me
from ..api.v1 import hit_limit, v1_args, v1_err, v1_view

TEXT_FILE_MB = 20          # larger files are refused (413)
TEXT_CAP = 200_000         # characters at most (the rest: truncated: true)
PDF_PAGES = 1000           # pages at most


def _env_int(name, default, lo, hi):
    try:
        return min(hi, max(lo, int(os.environ.get(name, "") or default)))
    except ValueError:
        return default


# 2.34.0 review (M3): the limits can be set per instance (small hosts: KALMIDO_PDF_PARALLEL=1, less memory)
PDF_SECONDS = _env_int("KALMIDO_PDF_TIMEOUT_S", 20, 2, 300)                 # wall clock for one PDF
PDF_MEM = _env_int("KALMIDO_PDF_MEM_MB", 512, 128, 8192) * 1024 * 1024      # address space of the worker
PDF_PARALLEL = _env_int("KALMIDO_PDF_PARALLEL", 2, 1, 16)                   # PDFs read at the same time
PDF_WAIT = 2               # seconds a request waits for a free slot, then 503 + Retry-After (review H1)
PDF_RATE = 10              # POST /api/pdf-text per account in 10 minutes (review H1)
CACHE_DIR = os.environ.get("TASKS_TEXT_CACHE", os.path.join(os.path.dirname(DB), "textcache"))
CACHE_KEEP = 400           # cached results kept (oldest go first)
CACHE_DAYS = 30            # ... and none older than this (the text of a deleted file does not stay for long)
CACHE_VER = "1"            # bump when the extraction changes
NO_TEXT_MIN = 16           # fewer visible characters in the whole PDF = no text layer
_SEM = threading.BoundedSemaphore(PDF_PARALLEL)
_RUNNING = set()           # accounts with a PDF being read right now (at most one each, review H1)
_RUN_LOCK = threading.Lock()
TEXT_EXT = {"txt", "text", "md", "markdown", "csv", "tsv", "json", "xml", "yml", "yaml", "html", "htm", "css", "js", "mjs",
            "log", "ini", "toml", "py", "sh", "sql", "ics", "vcf", "eml", "rst", "tex"} | set(TEXT_MIME)

WORKER = r"""
import io, json, resource, sys
def lim(k, v):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
MEM, CPU, PAGES, CAP = (int(x) for x in sys.argv[1:5])
lim(resource.RLIMIT_AS, MEM)
lim(resource.RLIMIT_CPU, CPU)
lim(resource.RLIMIT_FSIZE, 0)
lim(resource.RLIMIT_CORE, 0)
if hasattr(resource, "RLIMIT_NPROC"):
    lim(resource.RLIMIT_NPROC, 0)
data = sys.stdin.buffer.read()
import logging, warnings
logging.disable(logging.CRITICAL)
warnings.simplefilter("ignore")
from pypdf import PdfReader
try:
    r = PdfReader(io.BytesIO(data))
    if r.is_encrypted:
        try:
            ok = r.decrypt("")
        except Exception:
            ok = 0
        if not ok:
            print(json.dumps({"error": "encrypted"}))
            sys.exit(0)
    n = len(r.pages)
except Exception:
    print(json.dumps({"error": "unreadable"}))
    sys.exit(0)
out, total, cut = [], 0, n > PAGES
for i in range(min(n, PAGES)):
    try:
        t = r.pages[i].extract_text() or ""
    except Exception:
        t = ""
    out.append(t.strip())
    total += len(t) + 2
    if total > CAP:
        cut = True
        break
text = "\n\n".join(out)
print(json.dumps({"pages": n, "pages_read": len(out), "text": text[:CAP], "truncated": cut or len(text) > CAP}))
"""


def _cache_path(key):
    return os.path.join(CACHE_DIR, f"{key}.json")


def _cache_get(key):
    try:
        with open(_cache_path(key), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _cache_put(key, val):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = _cache_path(key) + f".{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(val, f, ensure_ascii=False)
        os.replace(tmp, _cache_path(key))
        full = sorted((os.path.join(CACHE_DIR, n) for n in os.listdir(CACHE_DIR) if n.endswith(".json")), key=os.path.getmtime)
        old = time.time() - CACHE_DAYS * 86400
        for i, p in enumerate(full):
            if i < len(full) - CACHE_KEEP or os.path.getmtime(p) < old:
                try:
                    os.remove(p)
                except OSError:
                    pass
    except OSError as e:
        print(f"WARNING text cache: {e}", flush=True)


def pdf_text(data, owner=None):
    """The text layer of a PDF (bytes) -> {pages, pages_read, text, truncated, no_text_layer} or {error: encrypted |
    unreadable | too_complex | busy}. Runs pypdf in a limited child process; cached per content. owner (account id):
    at most one PDF of that account is read at a time; no request waits longer than PDF_WAIT seconds for a slot."""
    key = hashlib.sha256(data).hexdigest() + "-" + CACHE_VER
    hit = _cache_get(key)
    if hit is not None:
        return hit
    if owner is not None:
        with _RUN_LOCK:
            if owner in _RUNNING:
                return {"error": "busy"}
            _RUNNING.add(owner)
    try:
        if not _SEM.acquire(timeout=PDF_WAIT):
            return {"error": "busy"}
        clean = False  # only a result the worker delivered itself is cached (review M2: no timeouts / fork errors)
        try:
            t0 = time.monotonic()
            try:
                p = subprocess.run([sys.executable, "-I", "-c", WORKER, str(PDF_MEM), str(PDF_SECONDS), str(PDF_PAGES), str(TEXT_CAP)],
                                   input=data, capture_output=True, timeout=PDF_SECONDS, close_fds=True,
                                   env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"})
                out = json.loads(p.stdout.decode("utf-8", "replace") or "null") if p.returncode == 0 else None
                clean = isinstance(out, dict)
            except subprocess.TimeoutExpired:
                out = {"error": "too_complex"}
            except (OSError, ValueError):
                out = None
            if not isinstance(out, dict):
                out = {"error": "too_complex" if time.monotonic() - t0 >= PDF_SECONDS - 1 else "unreadable"}
        finally:
            _SEM.release()
    finally:
        if owner is not None:
            with _RUN_LOCK:
                _RUNNING.discard(owner)
    if "error" not in out:
        out["no_text_layer"] = len("".join((out.get("text") or "").split())) < NO_TEXT_MIN
    if clean:
        _cache_put(key, out)
    return out


def _decode(data):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1")


def file_kind(name, mime, head):
    mime = (mime or "").lower()
    if head.startswith(b"%PDF") or (mime == "application/pdf" and b"%PDF" in head[:1024]):
        return "pdf"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("text/") or mime in ("application/json", "application/xml", "application/yaml") or file_ext(name or "") in TEXT_EXT:
        return "text" if b"\x00" not in head[:4096] else "other"
    return "other"


ERR_MSG = {
    "encrypted": N_("The PDF is password-protected and cannot be read."),
    "unreadable": N_("The PDF is damaged or not a PDF and cannot be read."),
    "too_complex": N_("The PDF took too long or too much memory to read."),
    "busy": N_("Several PDFs are being read right now, try again in a moment."),
}


def text_of_bytes(name, mime, data, max_chars=TEXT_CAP, owner=None):
    """{kind, text, chars, truncated, pages?, no_text_layer?, error?, message?} for one file's bytes (the caller checked
    rights and size). Shared by the agent API and the briefing field."""
    kind = file_kind(name, mime, data[:2048])
    out = {"kind": kind, "text": None, "chars": 0, "truncated": False, "message": None}
    if kind == "pdf":
        r = pdf_text(data, owner)
        if r.get("error"):
            out.update(error=r["error"], message=tr(ERR_MSG[r["error"]]))
            return out
        text = r.get("text") or ""
        out.update(pages=r.get("pages"), pages_read=r.get("pages_read"), no_text_layer=bool(r.get("no_text_layer")),
                   truncated=bool(r.get("truncated")))
        if out["no_text_layer"]:
            out.update(text="", message=tr("Scanned PDF without a text layer: it cannot be read without text recognition (OCR)."))
            return out
    elif kind == "text":
        text = _decode(data)
    elif kind == "image":
        out["message"] = tr("An image: download it from url (MCP: get_attachment shows it as an image).")
        return out
    else:
        out["message"] = tr("No text can be read from this kind of file.")
        return out
    if len(text) > max_chars:
        text, out["truncated"] = text[:max_chars], True
    out.update(text=text, chars=len(text))
    return out


@app.get("/api/v1/attachments/<int:aid>/text")
@v1_view
def v1_attachment_text_get(aid):
    """2.34.0 (#368): the text of a task / comment attachment (PDF text layer, text files); images point to the file.
    Same rights as GET /attachments/{id} (agents: only lists shared with them), else 404."""
    a = v1_args(("max_chars",))
    max_chars = as_int(a.get("max_chars", TEXT_CAP), "max_chars", 1, TEXT_CAP)
    c = db()
    att = need_attachment(c, aid, False)
    need_task(c, att["task_id"], write=False, full=True)
    if c.execute("SELECT deleted_at FROM tasks WHERE id=?", (att["task_id"],)).fetchone()[0]:
        raise Denied(404)
    base = {"id": att["id"], "task_id": att["task_id"], "comment_id": att["comment_id"], "name": att["name"], "mime": att["mime"],
            "size": att["size"], "url": f"/api/v1/attachments/{att['id']}"}
    if (att["size"] or 0) > TEXT_FILE_MB * 1024 * 1024:
        return v1_err(413, tr("{0}: larger than {1} MB", att["name"], TEXT_FILE_MB), name="too_large")
    full = os.path.join(ATT_DIR, att["path"])
    try:
        with open(full, "rb") as f:
            data = f.read(TEXT_FILE_MB * 1024 * 1024 + 1)
    except OSError:
        return v1_err(404, tr("File damaged or missing"))
    r = text_of_bytes(att["name"], att["mime"], data, max_chars, owner=me())
    if r.get("error") == "busy":
        return v1_err(503, r["message"], headers={"Retry-After": "10"}, name="busy")
    return jsonify({**base, **r})


@app.post("/api/pdf-text")
def pdf_text_upload():
    """2.34.0 (#368 / #260): the briefing field reads a PDF: the text layer of the uploaded file (nothing is stored).
    At most PDF_RATE files per account in 10 minutes (429) and one at a time (503 + Retry-After)."""
    f = request.files.get("file")
    if not f:
        return err(tr("File missing"))
    if hit_limit(f"pdftext:{me()}", PDF_RATE, 600):
        return err(tr("Too many requests, please slow down"), 429)
    data = f.read(TEXT_FILE_MB * 1024 * 1024 + 1)
    if len(data) > TEXT_FILE_MB * 1024 * 1024:
        return err(tr("{0}: larger than {1} MB", f.filename or "PDF", TEXT_FILE_MB), 413)
    if not data.startswith(b"%PDF") and b"%PDF" not in data[:1024]:
        return err(tr("Only PDF files"))
    r = text_of_bytes(f.filename or "", "application/pdf", data, 50_000, owner=me())
    if r.get("error") == "busy":
        resp, code = err(r["message"], 503)
        resp.headers["Retry-After"] = "10"
        return resp, code
    if r.get("error"):
        return err(r["message"], 422)
    return jsonify(text=r["text"], pages=r.get("pages"), truncated=r["truncated"], no_text_layer=r.get("no_text_layer", False),
                   message=r["message"])
