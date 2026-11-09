"""2.781.0 (#5390): is a document a scan? Decides whether the document view shows the archive number field and "Next free
number" for a document without a number (docview.js; "Assign archive number" stays in every document's actions menu).

Not the missing text layer decides (a scanner writes its OCR into the PDF), but:
  - it came through a scan inbox / the folder watcher (doc_meta.source "scan", docs/scankeys.py),
  - a picture (JPEG / PNG / HEIC / WebP ...) is a scan,
  - a PDF whose every page (up to SCAN_PAGES) is in its core one picture filling the page: the pictures drawn cover at least
    SCAN_COVER of the page and no visible text is drawn on top of them -- text only as an invisible OCR layer (text render
    mode 3) or hidden below the picture. A digital PDF (an invoice, a mail's PDF) draws visible vector text and is none.
    The phone scan (files/bulk.py abm_pdf) writes such a PDF, so it is caught here too,
  - an e-invoice (XML / ZUGFeRD) never is.
The result is kept once per recognition run in doc_meta.auto["_scan"] (1 / 0; docs/store.py process), documents from
before get it from the catch-up (docs/thumbfill.py p5390_scan_fill). The PDF is read by pypdf in its own limited child
process like the text layer (tasks/attachtext.py: time / memory limit, no new processes, no file writes)."""
import json
import os
import subprocess
import sys

from ..tasks.attachtext import PDF_MEM, PDF_SECONDS, _SEM

SCAN_PAGES = 20      # pages looked at; a longer PDF counts by its first pages
SCAN_COVER = 0.75    # share of the page the pictures cover at least
SCAN_OPS = 200_000   # content operators looked at in all (a page full of vector paths is no scan anyway)
SCAN_WAIT = 60       # seconds the background run waits for a free PDF slot, then "unknown" (asked again later)

WORKER = r"""
import io, json, resource, sys
def lim(k, v):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
MEM, CPU, PAGES, OPS = (int(x) for x in sys.argv[1:5])
COVER = float(sys.argv[5])
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
from pypdf.generic import ContentStream
def out(**kw):
    print(json.dumps(kw))
    sys.exit(0)
try:
    r = PdfReader(io.BytesIO(data))
    if r.is_encrypted:
        try:
            ok = r.decrypt("")
        except Exception:
            ok = 0
        if not ok:
            out(error="encrypted")
    n = len(r.pages)
except SystemExit:
    raise
except Exception:
    out(error="unreadable")
BUDGET = [OPS]
def mul(m, n):
    return (m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3], m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
            m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5])
def chars(s):
    if isinstance(s, (bytes, bytearray)):
        return len(bytes(s).strip())
    if isinstance(s, str):
        return len(s.strip())
    if isinstance(s, list):
        return sum(chars(x) for x in s)
    return 0
def obj(x):
    try:
        return x.get_object()
    except Exception:
        return x
def walk(stream, res, ctm, box, ev, depth):
    # the events of one content stream: ("img", covered area) / ("txt", visible characters)
    res = obj(res) or {}
    xo = obj(res.get("/XObject")) if hasattr(res, "get") else None
    xo = xo or {}
    try:
        ops = (stream if isinstance(stream, ContentStream) else ContentStream(stream, r)).operations
    except Exception:
        return
    stack, tr = [], 0
    for operands, op in ops:
        BUDGET[0] -= 1
        if BUDGET[0] < 0:
            raise OverflowError
        if op == b"q":
            stack.append((ctm, tr))
        elif op == b"Q":
            if stack:
                ctm, tr = stack.pop()
        elif op == b"cm" and len(operands) == 6:
            try:
                ctm = mul(tuple(float(x) for x in operands), ctm)
            except (TypeError, ValueError):
                pass
        elif op == b"Tr" and operands:
            try:
                tr = int(operands[0])
            except (TypeError, ValueError):
                pass
        elif op in (b"Tj", b"TJ", b"'", b'"'):
            k = chars(operands[-1]) if operands else 0
            if k and tr != 3:
                ev.append(("txt", k))
        elif op == b"INLINE IMAGE":
            ev.append(("img", area(ctm, box)))
        elif op == b"Do" and operands:
            x = obj(xo.get(operands[0])) if hasattr(xo, "get") else None
            if x is None or not hasattr(x, "get"):
                continue
            st = x.get("/Subtype")
            if st == "/Image":
                ev.append(("img", area(ctm, box)))
            elif st == "/Form" and depth < 4:
                fm = x.get("/Matrix")
                try:
                    m2 = mul(tuple(float(v) for v in fm), ctm) if fm and len(fm) == 6 else ctm
                except (TypeError, ValueError):
                    m2 = ctm
                walk(x, x.get("/Resources") or res, m2, box, ev, depth + 1)
def area(ctm, box):
    a, b, c, d, e, f = ctm
    xs = [e, a + e, c + e, a + c + e]
    ys = [f, b + f, d + f, b + d + f]
    w = min(max(xs), box[2]) - max(min(xs), box[0])
    h = min(max(ys), box[3]) - max(min(ys), box[1])
    return max(0.0, w) * max(0.0, h)
looked = 0
try:
    for i in range(min(n, PAGES)):
        p = r.pages[i]
        try:
            bx = p.cropbox
            box = (float(min(bx.left, bx.right)), float(min(bx.bottom, bx.top)), float(max(bx.left, bx.right)), float(max(bx.bottom, bx.top)))
        except Exception:
            out(scan=False, pages=n, looked=looked)
        full = (box[2] - box[0]) * (box[3] - box[1])
        c = p.get_contents()
        ev = []
        if c is not None and full > 0:
            walk(c, p.get("/Resources"), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), box, ev, 0)
        cov, covered, seen = 0.0, False, 0
        for kind, v in ev:
            if kind == "img":
                cov += v
                covered = covered or cov >= COVER * full
            elif covered:
                seen += v
        looked += 1
        if not covered or seen:
            out(scan=False, pages=n, looked=looked)
except OverflowError:
    out(scan=False, pages=n, looked=looked)
except SystemExit:
    raise
except Exception:
    out(error="unreadable")
out(scan=looked > 0, pages=n, looked=looked)
"""


def pdf_is_scan(data):
    """True / False for a PDF's bytes, None when it could not be told (busy, too slow, broken, encrypted) -- then nothing
    is kept and a later run asks again."""
    if not _SEM.acquire(timeout=SCAN_WAIT):
        return None
    try:
        p = subprocess.run([sys.executable, "-I", "-c", WORKER, str(PDF_MEM), str(PDF_SECONDS), str(SCAN_PAGES), str(SCAN_OPS), str(SCAN_COVER)],
                           input=data, capture_output=True, timeout=PDF_SECONDS, close_fds=True,
                           env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"})
        res = json.loads(p.stdout.decode("utf-8", "replace") or "null") if p.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        res = None
    finally:
        _SEM.release()
    if not isinstance(res, dict) or "scan" not in res:
        return None
    return bool(res["scan"])


def scan_of(name, mime, data, kind, source="", einvoice=False):
    """1 = a scan, 0 = none, None = not to be told now (see the module text)."""
    if einvoice:
        return 0
    if source == "scan":
        return 1
    if kind == "image":
        low = (mime or "").lower()
        return 0 if "svg" in low or (name or "").lower().endswith(".svg") else 1
    if kind == "pdf":
        s = pdf_is_scan(data)
        return None if s is None else int(s)
    return 0


def scan_flag(auto):
    """doc_meta.auto["_scan"] as True / False (False while it is not known yet)."""
    return bool(isinstance(auto, dict) and auto.get("_scan"))
