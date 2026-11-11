"""2.905.0 (#5393): the size of a document's first page, as the document view lays it out (static/js/docview.js dcv_phSize).
The view's first picture (the small preview) takes this size before the file is loaded, so nothing moves when the full
document replaces it -- only the content changes.

  - a PDF: [w, h, widest] in points as pdf.js shows them at scale 1 (the crop box clipped to the media box, turned by the
    inherited /Rotate); widest = the widest of the first 30 pages (pdf.js reads those up front, "Width" fits the widest).
    Read by pypdf in its own limited child process like the text layer and the scan mark (tasks/attachtext.py: one of its
    slots, time / memory limit, no new processes, no file writes) -- never in the app process.
  - a picture: [w, h] in pixels from its header only (Pillow opens JPEG / PNG / GIF / BMP lazily and decodes nothing; a
    JPEG's EXIF orientation 5-8 turns it like the browser does; a WebP from its RIFF header, never through Pillow).
  - anything else: None.

Kept once per recognition run in doc_meta.auto["_pg"] (docs/store.py process), documents from before get it from the
catch-up (docs/thumbfill.py p5393_page_fill); docs/web.py doc_json hands it out as "page"."""
import io
import json
import os
import subprocess
import sys

from ..tasks.attachtext import PDF_MEM, PDF_SECONDS, _SEM

PG_MAX = 100000          # a size beyond it (points / pixels) is no page the view lays out: none kept
PG_PDF = 100 << 20       # bytes of a PDF whose size is read at most
PG_IMG = 50 << 20        # bytes of a picture whose size is read at most (the catch-up never reads bigger ones whole)
PG_WAIT = 2              # seconds the recognition run waits for a free PDF slot (the size is a nicety; the catch-up asks again)
PG_PAGES = 30            # pages whose width counts for "widest" (as docview.js reads them up front)
PG_FORMATS = ["JPEG", "PNG", "GIF", "BMP"]  # only these through Pillow, their header gives the size; no TIFF (its IFD tags may
# each point at the whole file and Pillow reads every one of them in the app process)

WORKER = r"""
import io, json, resource, sys
def lim(k, v):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
MEM, CPU, PAGES = (int(x) for x in sys.argv[1:4])
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
r = PdfReader(io.BytesIO(data))
if r.is_encrypted and not r.decrypt(""):
    sys.exit(3)
def size(p):
    c, m = p.cropbox, p.mediabox
    x0, x1 = max(min(c.left, c.right), min(m.left, m.right)), min(max(c.left, c.right), max(m.left, m.right))
    y0, y1 = max(min(c.bottom, c.top), min(m.bottom, m.top)), min(max(c.bottom, c.top), max(m.bottom, m.top))
    w, h = float(x1) - float(x0), float(y1) - float(y0)
    return (h, w) if int(p.rotation or 0) % 180 else (w, h)
w, h = size(r.pages[0])
mw = w
for i in range(1, min(len(r.pages), PAGES)):
    try:
        mw = max(mw, size(r.pages[i])[0])
    except Exception:
        break
print(json.dumps([round(w, 2), round(h, 2), round(mw, 2)]))
"""


class PgBusy(Exception):
    """No free PDF slot now (pg_of strict=True): the catch-up stops its portion and asks the same document again."""


def pg_ok(pg):
    """[w, h] or [w, h, widest] of positive numbers below PG_MAX, else None (doc_json hands out only such a value)."""
    return pg if isinstance(pg, list) and len(pg) in (2, 3) and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                                  and 0 < x < PG_MAX for x in pg) else None


def _pdf_size(data, wait, strict):
    if not _SEM.acquire(timeout=wait):
        if strict:
            raise PgBusy()
        return None
    try:
        p = subprocess.run([sys.executable, "-I", "-c", WORKER, str(PDF_MEM), str(PDF_SECONDS), str(PG_PAGES)],
                           input=data, capture_output=True, timeout=PDF_SECONDS, close_fds=True,
                           env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"})
        res = json.loads(p.stdout.decode("utf-8", "replace") or "null") if p.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        res = None
    finally:
        _SEM.release()
    return pg_ok(res)


def _webp_size(b):
    """A WebP's canvas from its RIFF header (VP8X / VP8 / VP8L, a few bytes), never through Pillow (its animation decoder
    reserves the whole canvas). None when it is no WebP header this knows."""
    if len(b) < 30 or b[:4] != b"RIFF" or b[8:12] != b"WEBP":
        return None
    ch = b[12:16]
    if ch == b"VP8X":
        return [1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")]
    if ch == b"VP8 " and b[23:26] == b"\x9d\x01\x2a":
        return [int.from_bytes(b[26:28], "little") & 0x3FFF, int.from_bytes(b[28:30], "little") & 0x3FFF]
    if ch == b"VP8L" and b[20] == 0x2F:
        x = int.from_bytes(b[21:25], "little")
        return [1 + (x & 0x3FFF), 1 + ((x >> 14) & 0x3FFF)]
    return None


def _img_size(data):
    if data[:4] == b"RIFF":
        return pg_ok(_webp_size(data[:64]))
    try:
        from PIL import Image  # lazy like files/photometa.py: Pillow only when a picture is measured
        with Image.open(io.BytesIO(data), formats=PG_FORMATS) as im:  # reads the header only, decodes nothing
            w, h = im.size
            try:
                # only a JPEG's EXIF (one APP1 segment, at most 64 KB): Pillow decodes a whole PNG for getexif() without an
                # eXIf chunk, and a PNG's eXIf chunk may be as long as the file
                if im.format == "JPEG" and im.getexif().get(0x0112) in (5, 6, 7, 8):
                    w, h = h, w
            except Exception:  # noqa: BLE001 -- a broken EXIF block: the size as stored
                pass
        return pg_ok([int(w), int(h)])
    except Exception:  # noqa: BLE001 -- not one of PG_FORMATS (HEIC, SVG), a decompression bomb, a broken file
        return None


def pg_of(data, kind, wait=PG_WAIT, strict=False):
    """The first page's size of a document's bytes (see the module text), None when it cannot be told now (busy, too slow,
    encrypted, broken, too big, another kind). strict=True: no free PDF slot -> PgBusy instead of None."""
    if not data:
        return None
    if kind == "pdf":
        return _pdf_size(data, wait, strict) if len(data) <= PG_PDF else None
    if kind == "image":
        return _img_size(data) if len(data) <= PG_IMG else None
    return None
