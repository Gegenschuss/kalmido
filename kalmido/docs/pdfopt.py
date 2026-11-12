"""2.892.0 (#4873, includes #4806): "Optimise PDF" -- a scanned PDF made small and searchable, the tools part (no routes, no
database: docs/pdfoptq.py runs it in the documents queue and stores the result as a NEW VERSION of the file).

Every page is rendered (pdftoppm) and measured in a limited child process (Pillow): its ink (dark pixels inside the margins,
like the stack split, docs/split.py), its share of coloured pixels and its share of middle greys (a photo / a grey area).
The level decides what a page becomes:
  auto  -- a page of text -> 1 bit black and white (300 dpi, CCITT G4); a page with noticeable colour -> colour JPEG
           (200 dpi); a photo-like page without colour -> grey JPEG (200 dpi). In doubt the richer kind.
  bw    -- every page black and white;  gray -- every page a grey JPEG.
Each page image then goes through Tesseract with the output "pdf": the page image with an invisible text layer on top
(#4806: the archive version with a text layer, the preview of pdf.js can mark and copy its words). pypdf joins the pages
in a limited child process. Blank pages (the switch "Remove blank pages", on in auto by default) are found like the
stack split: ink below SP_INK AND the text recognition reads at most SP_TEXT characters; in doubt a page stays, and never
every page goes.

Limits as the text recognition (docs/ocr.py): every tool a short-lived child process with memory / CPU / file-size limits
(ocr._run, the workers set their own), a time limit per page, at most PO_PAGES pages and PO_MAX bytes, one heavy step at a
time (ocr._SEM, taken per page: review F2). No shell strings: every tool gets its arguments as a list. Loaded as a single file in tests (the sibling
ocr.py then too)."""
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time

try:
    from . import ocr as OCR
except ImportError:  # loaded as a single file (tests): the sibling ocr.py as a single file too
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("kalmido_ocr_single", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr.py"))
    OCR = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(OCR)

PO_PAGES = OCR._env_int("KALMIDO_PDFOPT_PAGES", 60, 1, 500)          # pages of one PDF at most
PO_MAX = OCR._env_int("KALMIDO_PDFOPT_MB", 100, 1, 2048) << 20       # bytes of one PDF at most
PO_DOC_S = OCR._env_int("KALMIDO_PDFOPT_DOC_S", 1800, 60, 7200)      # wall clock of one run in all
PO_MODES = ("auto", "bw", "gray")
PO_KINDS = ("bw", "gray", "color")
PO_DPI_BW = 300            # a black and white page keeps the scan's resolution (sharp letters, G4 is small anyway)
PO_DPI_JPG = 200           # grey / colour pages
PO_DPI_SCAN = 200          # the measuring render (= docs/split.py SP_DPI: the same ink values as the stack split)
PO_JPG_Q = 55
PO_COLOR = 0.01            # share of clearly coloured pixels from which a page keeps its colour
PO_MID = 0.15              # share of middle greys from which a page without colour becomes grey (photo, grey areas)
SP_INK = 0.004             # = docs/split.py SP_INK: below this a page may be blank (the text recognition decides)
SP_TEXT = 12               # = docs/split.py SP_TEXT: visible characters at most on a blank page
PO_WORKER_S = 90           # s one page may take in the page worker


def po_kind(mode, ink, color, mid):
    """The kind a page becomes: mode = auto | bw | gray, the page's measures (shares 0..1)."""
    if mode == "bw":
        return "bw"
    if mode == "gray":
        return "gray"
    if float(color or 0) >= PO_COLOR:
        return "color"
    if float(mid or 0) >= PO_MID:
        return "gray"
    return "bw"


def po_blank(ink, text):
    """A page is blank: almost no ink AND the text recognition read (nearly) nothing. text None = not read: never blank."""
    if text is None:
        return False
    return float(ink) < SP_INK and len(re.sub(r"\s+", "", text)) <= SP_TEXT


def po_drop(pages, blank):
    """The 1-based numbers of the pages that go: the blank ones when the switch is on, never every page (in doubt it stays)."""
    if not blank:
        return []
    out = [i + 1 for i, p in enumerate(pages) if p.get("b")]
    return [] if len(out) >= len(pages) else out


def po_otsu(hist):
    """The threshold (0..255) that parts a grey histogram into two classes best (Otsu), held between 90 and 210 so a pale
    scan does not turn black and a dark one white."""
    total = sum(hist) or 1
    s_all = sum(i * h for i, h in enumerate(hist))
    w0 = s0 = 0
    best, t = -1.0, 160
    for i in range(256):
        w0 += hist[i]
        if not w0:
            continue
        w1 = total - w0
        if not w1:
            break
        s0 += i * hist[i]
        m0, m1 = s0 / w0, (s_all - s0) / w1
        v = w0 * w1 * (m0 - m1) ** 2
        if v > best:
            best, t = v, i
    return max(90, min(210, t))


def po_smaller(before, after):
    """Only a file that came out smaller becomes a new version (decided 06.11.2026: not smaller -> the file stays)."""
    return 0 < int(after or 0) < int(before or 0)


def po_size(n):
    """1536 -> "1.5 KB" (the server's text of the result; the client formats with its own locale)."""
    n = int(n or 0)
    for u, f in (("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= f:
            return f"{n / f:.1f} {u}"
    return f"{n} B"


# the page worker: a limited child process, one JSON request per line on stdin, one JSON answer per line on stdout
#   {"op": "ana", "p": png}                                   -> {"ink", "color", "mid"}
#   {"op": "out", "p": png, "k": bw|gray|color, "din": 300, "o": base} -> {"f": file, "dpi": n} (the page image to read)
PAGE_WORKER = r"""
import json, resource, sys
CPU = int(sys.argv[1]) if len(sys.argv) > 1 else 600  # review F10: CPU seconds grow with the pages (po_cpu)
for k, v in ((resource.RLIMIT_AS, 1536 << 20), (resource.RLIMIT_CPU, CPU), (resource.RLIMIT_FSIZE, 256 << 20), (resource.RLIMIT_CORE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
from PIL import Image
Image.MAX_IMAGE_PIXELS = 120_000_000
def otsu(hist):
    total = sum(hist) or 1
    s_all = sum(i * h for i, h in enumerate(hist))
    w0 = s0 = 0
    best, t = -1.0, 160
    for i in range(256):
        w0 += hist[i]
        if not w0:
            continue
        w1 = total - w0
        if not w1:
            break
        s0 += i * hist[i]
        m0, m1 = s0 / w0, (s_all - s0) / w1
        v = w0 * w1 * (m0 - m1) ** 2
        if v > best:
            best, t = v, i
    return max(90, min(210, t))
def ana(p):
    im = Image.open(p)
    im.load()
    w, h = im.size
    mx, my = int(w * 0.06), int(h * 0.06)
    inner = im.crop((mx, my, w - mx, h - my))
    g = inner.convert("L")
    hist = g.histogram()
    total = sum(hist) or 1
    ink = sum(hist[:128]) / total
    mid = sum(hist[60:200]) / total
    color = 0.0
    if inner.mode not in ("L", "1", "LA"):
        small = inner.convert("RGB")
        small.thumbnail((700, 700))
        hh, s, v = small.convert("HSV").split()
        sm = s.point(lambda x: 255 if x > 80 else 0)
        vm = v.point(lambda x: 255 if x > 60 else 0)
        from PIL import ImageChops
        both = ImageChops.multiply(sm, vm).histogram()
        color = both[255] / (sum(both) or 1)
    return {"ink": round(ink, 5), "color": round(color, 5), "mid": round(mid, 5)}
def out(p, kind, din, base):
    im = Image.open(p)
    im.load()
    if kind == "bw":
        g = im.convert("L")
        t = otsu(g.histogram())
        bw = g.point(lambda x: 255 if x > t else 0).convert("1", dither=Image.Dither.NONE)
        f = base + ".tif"
        bw.save(f, "TIFF", compression="group4", dpi=(din, din))
        return {"f": f, "dpi": din}
    dout = min(din, %(JPG)d)
    im = im.convert("RGB" if kind == "color" else "L")
    if dout < din:
        im = im.resize((max(1, round(im.width * dout / din)), max(1, round(im.height * dout / din))), Image.Resampling.LANCZOS)
    f = base + ".jpg"
    im.save(f, "JPEG", quality=%(Q)d, optimize=True, dpi=(dout, dout))
    return {"f": f, "dpi": dout}
while True:
    line = sys.stdin.readline()
    if not line:
        break
    try:
        q = json.loads(line)
        r = ana(q["p"]) if q["op"] == "ana" else out(q["p"], q["k"], int(q["din"]), q["o"])
    except Exception as e:
        r = {"error": type(e).__name__}
    sys.stdout.write(json.dumps(r) + "\n")
    sys.stdout.flush()
""" % {"JPG": PO_DPI_JPG, "Q": PO_JPG_Q}

# pypdf joins the page PDFs (paths as JSON in argv) in a limited child process; out: the PDF on stdout
JOIN_WORKER = r"""
import io, json, resource, sys
for k, v in ((resource.RLIMIT_AS, 1536 << 20), (resource.RLIMIT_CPU, 300), (resource.RLIMIT_FSIZE, 0), (resource.RLIMIT_CORE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
import logging, warnings
logging.disable(logging.CRITICAL)
warnings.simplefilter("ignore")
from pypdf import PdfReader, PdfWriter
w = PdfWriter()
for p in json.loads(sys.argv[1]):
    for page in PdfReader(p).pages:
        w.add_page(page)
w.add_metadata({"/Producer": "Kalmido"})
b = io.BytesIO()
w.write(b)
sys.stdout.buffer.write(b.getvalue())
"""


class PoError(Exception):
    """A run that cannot go on: its key (no_ocr, busy, unreadable, too_many_pages, too_big, too_complex, failed)."""


def po_available():
    return OCR.ocr_available() and bool(shutil.which("pdftoppm"))


def po_cpu(n):
    """CPU seconds of the page worker for n pages (review F10): a measure and an output per page, never above a run's time."""
    return max(60, min(PO_DOC_S, 60 + 40 * int(n or 1)))


class _Slot:
    """Review F2: one heavy step (a page, the join) holds the tools' slot (ocr._SEM), not the whole document: a long PDF
    no longer keeps the text recognition of new documents waiting. No slot within OCR_PAGE_S * 2: PoError("busy") (the queue
    puts the run back and starts it again later)."""

    def __enter__(self):
        if not OCR._SEM.acquire(timeout=OCR.OCR_PAGE_S * 2):
            raise PoError("busy")
        return self

    def __exit__(self, *exc):
        OCR._SEM.release()


PO_TMP = ("kpdo-", "kpdi-")


def po_tmp_clean(age=None):
    """Review F9: temp folders of runs cut off (a killed process) older than age s (default a run's time + 10 min) go."""
    age = PO_DOC_S + 600 if age is None else age
    base, n = tempfile.gettempdir(), 0
    try:
        names = os.listdir(base)
    except OSError:
        return 0
    for f in names:
        p = os.path.join(base, f)
        try:
            if f.startswith(PO_TMP) and os.path.isdir(p) and not os.path.islink(p) and time.time() - os.path.getmtime(p) > age:
                shutil.rmtree(p, ignore_errors=True)
                n += 1
        except OSError:
            pass
    return n


class _Pages:
    """The rendering + page worker of one PDF in a temp folder (one page image at a time lies there)."""

    def __init__(self, data, n=1, tmp=None, budget=None):
        """tmp (2.1073.0, #5570): the folder of a stepwise run (po_begin wrote its in.pdf); it stays after the step, only
        the worker ends. budget: the seconds of the run left (a run's time is counted over its steps)."""
        self.keep = tmp is not None
        self.tmp = tmp if self.keep else tempfile.mkdtemp(prefix="kpdo-")
        self.w = None
        self.n = n
        self.end = time.monotonic() + (PO_DOC_S if budget is None else max(0.0, float(budget)))
        self.src = os.path.join(self.tmp, "in.pdf")
        if self.keep:
            if not os.path.isfile(self.src):
                raise PoError("failed")
            return
        try:
            with open(self.src, "wb") as f:
                f.write(data)
        except BaseException:  # review F9: a full disk leaves no folder behind
            shutil.rmtree(self.tmp, ignore_errors=True)
            raise

    def __enter__(self):
        try:
            self.w = subprocess.Popen([sys.executable, "-I", "-c", PAGE_WORKER, str(po_cpu(self.n))], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0, close_fds=True,
                                      env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        except BaseException:  # review F9: __exit__ does not run when __enter__ fails
            if not self.keep:
                shutil.rmtree(self.tmp, ignore_errors=True)
            raise
        return self

    def __exit__(self, *exc):
        if self.w:
            try:
                self.w.stdin.close()
            except OSError:
                pass
            self.w.kill()
            self.w.wait()
        if not self.keep:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def clock(self):
        if time.monotonic() > self.end:
            raise PoError("too_complex")

    def ask(self, q):
        try:
            self.w.stdin.write((json.dumps(q) + "\n").encode())
            if not select.select([self.w.stdout], [], [], PO_WORKER_S)[0]:
                raise PoError("too_complex")
            line = self.w.stdout.readline()
            if not line:  # review F10: the worker died (its memory / CPU limit), not a broken file
                raise PoError("too_complex")
            r = json.loads(line)
        except (OSError, ValueError):
            raise PoError("failed") from None
        if not isinstance(r, dict) or r.get("error"):
            raise PoError("unreadable")
        return r

    def render(self, i, dpi, gray):
        """Page i (1-based) as a PNG file at dpi (grey or colour)."""
        self.clock()
        base = os.path.join(self.tmp, f"r{i}")
        args = ["pdftoppm", "-r", str(int(dpi))] + (["-gray"] if gray else []) + ["-f", str(i), "-l", str(i), "-singlefile", "-png", self.src, base]
        try:
            r = OCR._run(args, OCR.OCR_PAGE_S, fsize=256 << 20)
        except subprocess.TimeoutExpired:
            raise PoError("too_complex") from None
        if r.returncode != 0 or not os.path.exists(base + ".png"):
            raise PoError("unreadable")
        return base + ".png"


def _rm(*ps):
    for p in ps:
        try:
            os.unlink(p)
        except (OSError, TypeError):
            pass


def po_pages(data):
    """The number of pages of PDF bytes, None when they cannot be read."""
    with tempfile.TemporaryDirectory(prefix="kpdi-") as tmp:
        src = os.path.join(tmp, "in.pdf")
        with open(src, "wb") as f:
            f.write(data)
        return OCR._pdf_pages(src)


def _check(data):
    if not po_available():
        raise PoError("no_ocr")
    if len(data) > PO_MAX:
        raise PoError("too_big")
    n = po_pages(data)
    if not n:
        raise PoError("unreadable")
    if n > PO_PAGES:
        raise PoError("too_many_pages")
    return n


def _ana_page(pg, i, langs):
    """The measure of page i (1-based): {k, b, ink, c, m} (one heavy step: the slot)."""
    with _Slot():
        png = pg.render(i, PO_DPI_SCAN, False)
        try:
            a = pg.ask({"op": "ana", "p": png})
            text = None
            if float(a["ink"]) < SP_INK:  # only an almost empty page is read (the stack split's rule)
                try:
                    text = OCR._tess(png, OCR.OCR_PAGE_S, langs)
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    text = None
        finally:
            _rm(png)
    return {"k": po_kind("auto", a["ink"], a["color"], a["mid"]), "b": 1 if po_blank(a["ink"], text) else 0,
            "ink": a["ink"], "c": a["color"], "m": a["mid"]}


def _analyse(pg, n, langs):
    return [_ana_page(pg, i, langs) for i in range(1, n + 1)]


def po_analyse(data, langs=None):
    """[{k: the kind in auto, b: 1 = blank, ink, c, m}] per page of PDF bytes (raises PoError)."""
    n = _check(data)
    with _Pages(data, n) as pg:
        return _analyse(pg, n, langs or OCR.OCR_LANGS)


def _page_pdf(pg, i, k, langs):
    """Page i as kind k through Tesseract with the output "pdf" (the page image, an invisible text layer): the file."""
    png = pg.render(i, PO_DPI_BW, k != "color")
    img = None
    try:
        r = pg.ask({"op": "out", "p": png, "k": k, "din": PO_DPI_BW, "o": os.path.join(pg.tmp, f"o{i}")})
        img = r["f"]
        base = os.path.join(pg.tmp, f"t{i:04d}")
        pg.clock()
        try:
            t = OCR._run(["tesseract", img, base, "-l", langs, "--dpi", str(int(r["dpi"])), "--psm", "3", "pdf"],
                         OCR.OCR_PAGE_S, fsize=128 << 20)
        except subprocess.TimeoutExpired:
            raise PoError("too_complex") from None
        if t.returncode != 0 or not os.path.exists(base + ".pdf"):
            raise PoError("unreadable")
        return base + ".pdf"
    finally:
        _rm(png, img)


def po_page_kind(mode, p):
    """The kind page p (its measure) becomes in mode (auto: the kind measured, in doubt colour)."""
    if mode != "auto":
        return po_kind(mode, p.get("ink"), p.get("c"), p.get("m"))
    return p.get("k") if p.get("k") in PO_KINDS else "color"


def _join(pg, parts):
    """The page PDFs joined (pypdf in a limited child process): the PDF's bytes."""
    if not parts:
        raise PoError("unreadable")
    pg.clock()
    with _Slot():
        try:
            j = subprocess.run([sys.executable, "-I", "-c", JOIN_WORKER, json.dumps(parts)], capture_output=True,
                               timeout=300, close_fds=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        except subprocess.TimeoutExpired:
            raise PoError("too_complex") from None
    if j.returncode != 0 or j.stdout[:4] != b"%PDF":
        raise PoError("failed")
    return j.stdout


def po_optimise(data, mode="auto", blank=True, langs=None, pages=None):
    """{"pdf": bytes, "pages": analysis, "drop": [1-based], "kinds": {bw, gray, color}} -- the optimised PDF with a text layer.
    pages = an analysis of exactly these bytes made before (po_analyse: the list a person saw), else it is made here.
    In one go (a manual check, the tests); the queue goes page by page (po_begin / po_step_*, #5570)."""
    if mode not in PO_MODES:
        raise PoError("failed")
    n = _check(data)
    langs = langs or OCR.OCR_LANGS
    with _Pages(data, n) as pg:
        if not (isinstance(pages, list) and len(pages) == n):
            pages = _analyse(pg, n, langs)
        drop = po_drop(pages, blank)
        kinds, parts = {k: 0 for k in PO_KINDS}, []
        for i in range(1, n + 1):
            if i in drop:
                continue
            k = po_page_kind(mode, pages[i - 1])
            kinds[k] += 1
            with _Slot():  # review F2: the slot per page
                parts.append(_page_pdf(pg, i, k, langs))
        return {"pdf": _join(pg, parts), "pages": pages, "drop": drop, "kinds": kinds}


# ---- 2.1073.0 (#5570): the run page by page, one queue step per page ------------------------------------------------
# A run of many pages held the documents queue (and its GATE.bg) for up to PO_DOC_S: no recognition of new scans, a restore
# refused. Now the queue (docs/pdfoptq.py) makes one page per step: the run's folder (po_dir) keeps the PDF and the page
# PDFs made so far between the steps, the state in doc_meta.pdf_opt notes how far it got; between two steps the queue
# recognises waiting documents and leaves GATE. The run's time (PO_DOC_S) is counted over its steps (budget).
PO_DIR_RE = re.compile(r"^[0-9]+-[0-9a-f]{8,32}$")


def po_dir(key):
    """The folder of one stepwise run: key = "<node id>-<the run's word>" (nothing else is accepted)."""
    if not PO_DIR_RE.match(str(key or "")):
        raise PoError("failed")
    return os.path.join(tempfile.gettempdir(), PO_TMP[0] + "r" + str(key))


def po_begin(data, tmp):
    """A run's first step: the checks (PoError) and the PDF into its folder tmp (a new one). -> the number of pages."""
    n = _check(data)
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, mode=0o700)
    try:
        with open(os.path.join(tmp, "in.pdf"), "wb") as f:
            f.write(data)
    except BaseException:  # review F9: a full disk leaves no folder behind
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return n


def po_end(tmp):
    """The run's folder goes (done, failed, put back)."""
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


def po_step_ana(tmp, n, i, langs=None, budget=None):
    """One step: the measure of page i of the run in tmp (po_analyse's entry of that page)."""
    with _Pages(None, n, tmp=tmp, budget=budget) as pg:
        return _ana_page(pg, i, langs or OCR.OCR_LANGS)


def po_step_page(tmp, n, i, k, langs=None, budget=None):
    """One step: page i as kind k with its text layer, kept in tmp for the join."""
    with _Pages(None, n, tmp=tmp, budget=budget) as pg:
        with _Slot():
            _page_pdf(pg, i, k, langs or OCR.OCR_LANGS)


def po_step_join(tmp, n, keep, budget=None):
    """The last step: the pages kept (1-based numbers, each made by po_step_page) joined -> the PDF's bytes."""
    parts = [os.path.join(tmp, f"t{i:04d}.pdf") for i in keep]
    if any(not os.path.isfile(p) for p in parts):
        raise PoError("failed")
    with _Pages(None, n, tmp=tmp, budget=budget) as pg:
        return _join(pg, parts)


if __name__ == "__main__":  # a manual check: python -m kalmido.docs.pdfopt FILE [auto|bw|gray]
    with open(sys.argv[1], "rb") as fh:
        b = fh.read()
    res = po_optimise(b, sys.argv[2] if len(sys.argv) > 2 else "auto")
    print(json.dumps({"before": len(b), "after": len(res["pdf"]), "drop": res["drop"], "kinds": res["kinds"]}))
