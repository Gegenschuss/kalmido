"""2.48.0 (#1111): the text of a document and its preview image -- only local tools in the container, no network.

PDF with a text layer: the existing reader of attachments (tasks/attachtext.py: pypdf in a limited child process).
Scanned PDF / image: text recognition (OCR) with Tesseract (German + English): pdftoppm rasters page by page (300 dpi),
tesseract reads each page. Every tool runs as a short-lived child process with a memory / CPU / file-size limit and a
time limit PER PAGE, at most OCR_PAGES pages, at most OCR_PARALLEL documents at a time (semaphore). A missing Tesseract
(an older image) gives {"error": "no_ocr"} -- never an exception. Preview: the first page (pdftoppm) or the image
(Pillow in a limited child process), a small JPEG."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
try:  # 2.369.5 (#2517): pulled up from functions; #3506: guarded, ocr.py is also loaded as a single file (tests, ocr_langs)
    from ..tasks.attachtext import file_kind, pdf_text, _decode
    from ..files.photometa import pm_kind
    from ..files.officeprev import dpv_model  # 2.635.0 (#4807): the text / preview image of Office files
except ImportError:  # loaded as a single file (tests, no package): only the pure helpers are used there
    file_kind = pdf_text = _decode = pm_kind = dpv_model = None


def _env_int(name, default, lo, hi):
    try:
        return min(hi, max(lo, int(os.environ.get(name, "") or default)))
    except ValueError:
        return default


OCR_PAGE_S = _env_int("KALMIDO_OCR_PAGE_S", 60, 5, 600)          # wall clock per page (raster + recognition)
OCR_PAGES = _env_int("KALMIDO_OCR_PAGES", 30, 1, 500)            # pages recognised at most
OCR_PARALLEL = _env_int("KALMIDO_OCR_PARALLEL", 1, 1, 8)         # documents recognised at the same time
OCR_MEM = _env_int("KALMIDO_OCR_MEM_MB", 1024, 256, 8192) << 20  # address space of a tool
OCR_DPI = 300
OCR_LANGS = os.environ.get("KALMIDO_OCR_LANGS", "deu+eng")
TEXT_CAP = 200_000
THUMB_W = 320
OFFICE_KINDS = ("docx", "xlsx", "odt", "ods")  # 2.635.0 (#4807): read through files/officeprev.py
THUMB_WL = 800  # 2.583.0 (#4812): the sharper preview of big cards (docs/store.py thumb_store, doc_meta.thumb_l)
_SEM = threading.BoundedSemaphore(OCR_PARALLEL)
_AVAIL = {}


# the limits are set by a tiny exec wrapper (preexec_fn is not safe in a threaded server)
LIMIT_EXEC = r"""
import os, resource, sys
mem, cpu, fsize = (int(x) for x in sys.argv[1:4])
for k, v in ((resource.RLIMIT_AS, mem), (resource.RLIMIT_CPU, cpu), (resource.RLIMIT_FSIZE, fsize), (resource.RLIMIT_CORE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
os.execvp(sys.argv[4], sys.argv[4:])
"""


def _env():
    # one thread per tool (OpenMP in tesseract), no proxy / network settings inherited
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "OMP_THREAD_LIMIT": "1", "HOME": "/tmp"}


def _run(args, timeout, fsize=64 << 20, data=None):
    return subprocess.run([sys.executable, "-I", "-c", LIMIT_EXEC, str(OCR_MEM), str(OCR_PAGE_S), str(fsize)] + list(args),
                          input=data, capture_output=True, timeout=timeout, close_fds=True, env=_env())


def ocr_available():
    """True when tesseract (with the configured languages) and pdftoppm are installed."""
    if "ok" not in _AVAIL:
        ok = bool(shutil.which("tesseract") and shutil.which("pdftoppm"))
        if ok:
            try:
                p = _run(["tesseract", "--list-langs"], 10)
                have = set((p.stdout + p.stderr).decode("utf-8", "replace").split())
                ok = all(lang in have for lang in OCR_LANGS.split("+"))
            except (OSError, subprocess.SubprocessError):
                ok = False
        _AVAIL["ok"] = ok
    return _AVAIL["ok"]


# 2.122.0 (#2101): the app language of the person adds its Tesseract language to the configured base (deu+eng)
OCR_LANG_OF = {"de": "deu", "en": "eng", "fr": "fra", "it": "ita", "es": "spa", "nl": "nld"}


def ocr_installed():
    """The Tesseract languages installed in this image (cached); empty when it cannot be asked."""
    if "have" not in _AVAIL:
        have = set()
        try:
            p = _run(["tesseract", "--list-langs"], 10)
            have = set((p.stdout + p.stderr).decode("utf-8", "replace").split())
        except (OSError, subprocess.SubprocessError):
            pass
        _AVAIL["have"] = have
    return _AVAIL["have"]


# 2.635.0 (#4807 b): the languages an area may choose for its documents: the installed ones (not the script / orientation
# models), within KALMIDO_OCR_LANGS when the server sets it (its upper bound); deu+eng stays the default of every area
OCR_NOT_LANGS = {"osd", "equ", "snum"}
OCR_LANG_MAX = 4           # languages of one area at most (every one makes the recognition slower)
OCR_CAP = os.environ.get("KALMIDO_OCR_LANGS", "").strip()
OCR_NAMES = {"deu": "Deutsch", "eng": "English", "fra": "Français", "ita": "Italiano", "spa": "Español", "nld": "Nederlands",
             "por": "Português", "pol": "Polski", "ces": "Čeština", "dan": "Dansk", "swe": "Svenska", "nor": "Norsk", "fin": "Suomi",
             "tur": "Türkçe", "rus": "Русский", "ukr": "Українська", "ell": "Ελληνικά", "hun": "Magyar", "ron": "Română",
             "hrv": "Hrvatski", "slk": "Slovenčina", "slv": "Slovenščina", "deu_latf": "Deutsch (Fraktur)", "frk": "Fraktur"}


def ocr_choices(have=None):
    """2.635.0 (#4807 b): the Tesseract languages an area may choose (sorted codes)."""
    have = ocr_installed() if have is None else have
    # the answer of --list-langs starts with a line of words ("List of available languages in ..."): only language codes
    out = {x for x in have if x not in OCR_NOT_LANGS and re.fullmatch(r"[a-z]{3}(_[a-z]{3,4})?", x)}
    if OCR_CAP:
        out &= set(OCR_CAP.split("+"))
    return sorted(out)


def ocr_langs(app_lang=None, have=None, base=None):
    """(the -l value, [missing Tesseract languages of the wanted ones]) for a person whose app language is app_lang: that
    language first, then the base languages; only installed ones are taken, a missing one is reported, never an error.
    2.635.0 (#4807 b): base = the languages the area chose (docs/store.py cfg_get ocr_langs): exactly those, no app language."""
    have = ocr_installed() if have is None else have
    if base:
        use = [x for x in base if x in have and (not OCR_CAP or x in OCR_CAP.split("+"))]
        return "+".join(use) or OCR_LANGS, [x for x in base if x not in have]
    want = []
    own = OCR_LANG_OF.get(str(app_lang or "").lower().split("-")[0].split("_")[0])
    for code in ([own] if own else []) + OCR_LANGS.split("+"):
        if code and code not in want:
            want.append(code)
    use = [x for x in want if x in have]
    return "+".join(use) or OCR_LANGS, [x for x in want if x not in have]


def _pdf_pages(path):
    try:
        p = _run(["pdfinfo", path], 20)
        for ln in p.stdout.decode("utf-8", "replace").splitlines():
            if ln.startswith("Pages:"):
                return int(ln.split()[1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return None


def _tess(img, timeout, langs=OCR_LANGS):
    p = _run(["tesseract", img, "stdout", "-l", langs, "--psm", "3"], timeout)
    if p.returncode != 0:
        raise RuntimeError("tesseract")
    return p.stdout.decode("utf-8", "replace")


def ocr_bytes(data, kind, lang=None, base=None):
    """{"text", "pages", "pages_read", "truncated"} or {"error": "no_ocr" | "busy" | "too_complex" | "unreadable"}.
    kind = "pdf" | "image"; lang = the person's app language (2.122.0, #2101: read with its Tesseract language as well). Blocks while another document is being recognised (the caller is a background worker)."""
    if not ocr_available():
        return {"error": "no_ocr"}
    if not _SEM.acquire(timeout=OCR_PAGE_S * 2):
        return {"error": "busy"}
    langs = ocr_langs(lang, base=base)[0]  # 2.635.0 (#4807 b): base = the area's chosen languages
    try:
        with tempfile.TemporaryDirectory(prefix="kocr-") as tmp:
            src = os.path.join(tmp, "in.pdf" if kind == "pdf" else "in.img")
            with open(src, "wb") as f:
                f.write(data)
            if kind != "pdf":
                try:
                    text = _tess(src, OCR_PAGE_S, langs)
                except subprocess.TimeoutExpired:
                    return {"error": "too_complex"}
                except (OSError, RuntimeError):
                    return {"error": "unreadable"}
                return {"text": text[:TEXT_CAP].strip(), "pages": 1, "pages_read": 1, "truncated": len(text) > TEXT_CAP}
            n = _pdf_pages(src)
            if not n:
                return {"error": "unreadable"}
            out, total, timeouts = [], 0, 0
            for i in range(1, min(n, OCR_PAGES) + 1):
                base = os.path.join(tmp, f"p{i}")
                try:
                    r = _run(["pdftoppm", "-r", str(OCR_DPI), "-gray", "-f", str(i), "-l", str(i), "-singlefile", "-png", src, base],
                             OCR_PAGE_S, fsize=256 << 20)
                    if r.returncode != 0 or not os.path.exists(base + ".png"):
                        out.append("")
                        continue
                    out.append(_tess(base + ".png", OCR_PAGE_S, langs).strip())
                except subprocess.TimeoutExpired:
                    timeouts += 1
                    out.append("")
                    if timeouts >= 2:
                        break
                except (OSError, RuntimeError):
                    out.append("")
                finally:
                    try:
                        os.remove(base + ".png")
                    except OSError:
                        pass
                total += len(out[-1])
                if total > TEXT_CAP:
                    break
            text = "\n\n".join(out)
            if not text.strip() and timeouts:
                return {"error": "too_complex"}
            return {"text": text[:TEXT_CAP], "pages": n, "pages_read": len(out),
                    "truncated": n > len(out) or len(text) > TEXT_CAP}
    finally:
        _SEM.release()


THUMB_WORKER = r"""
import io, resource, sys
for k, v in ((resource.RLIMIT_AS, 768 << 20), (resource.RLIMIT_CPU, 20), (resource.RLIMIT_FSIZE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
from PIL import Image, ImageOps
Image.MAX_IMAGE_PIXELS = 80_000_000
try:  # 2.146.0 B (#2454): HEIC / HEIF photos; #4168: pi-heif left the image (its libheif / libde265 have known holes), so no preview of them for now
    import pi_heif
    pi_heif.register_heif_opener()
except Exception:  # noqa: BLE001 -- HEIC support is optional: without it HEIC files simply get no preview
    pass
W = int(sys.argv[1])
im = Image.open(io.BytesIO(sys.stdin.buffer.read()))
im.draft("RGB", (W * 2, W * 3))
im = ImageOps.exif_transpose(im).convert("RGB")
im.thumbnail((W, W * 2))
b = io.BytesIO()
im.save(b, "JPEG", quality=72, optimize=True)
sys.stdout.buffer.write(b.getvalue())
"""


# 2.635.0 (#4807): the preview image of a Word / Excel / OpenDocument file: the beginning of its preview model's text
# (files/officeprev.py, never the file itself) drawn as a page -- headings bold, a sheet's rows as lines
OFFICE_THUMB_WORKER = r"""
import io, resource, sys
for k, v in ((resource.RLIMIT_AS, 512 << 20), (resource.RLIMIT_CPU, 10), (resource.RLIMIT_FSIZE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
from PIL import Image, ImageDraw, ImageFont
W = int(sys.argv[1])
H = int(W * 1.414)
text = sys.stdin.buffer.read().decode("utf-8", "replace")
im = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(im)
def font(n):
    try:
        return ImageFont.load_default(size=n)
    except Exception:
        return ImageFont.load_default()
f, fb = font(10), font(13)
M, y = 16, 16
for raw in text.splitlines()[:300]:
    line = raw.replace("\t", " ").rstrip()
    head = line.lstrip().startswith("#")
    if head:
        line = line.lstrip().lstrip("#").strip()
    if not line.strip():
        y += 5
        continue
    ft = fb if head else f
    while line and y < H - 16:
        n = len(line)
        while n > 1 and d.textlength(line[:n], font=ft) > W - 2 * M:
            n -= 1
        d.text((M, y), line[:n], fill=(30, 30, 30) if head else (70, 70, 70), font=ft)
        line = line[n:]
        y += 18 if head else 13
    if y >= H - 16:
        break
b = io.BytesIO()
im.save(b, "JPEG", quality=72, optimize=True)
sys.stdout.buffer.write(b.getvalue())
"""


def office_thumb(data, kind):
    """2.635.0 (#4807): a small JPEG page of a Word / Excel / OpenDocument file from its preview model's text, or None."""
    r = dpv_model(data, kind)  # cached per content: the recognition read it a moment ago
    text = (r.get("text") or "").strip() if not r.get("error") else ""
    if not text:
        return None
    p = subprocess.run([sys.executable, "-I", "-c", OFFICE_THUMB_WORKER, str(THUMB_W)], input=text[:6000].encode("utf-8"),
                       capture_output=True, timeout=30, close_fds=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    return p.stdout if p.returncode == 0 and p.stdout[:2] == b"\xff\xd8" else None


def thumb_bytes(data, kind, w=THUMB_W):
    """A small JPEG of the first page / the image, or None (no tools, damaged file, timeout). 2.635.0 (#4807): + Office files.
    2.583.0 (#4812): w = THUMB_WL makes the sharper one of big cards: a page then w pixels wide (the small one fits the page
    into w x w); Office files always get the small one."""
    try:
        if kind in OFFICE_KINDS:
            return office_thumb(data, kind)
        if kind == "pdf":
            if not shutil.which("pdftoppm"):
                return None
            with tempfile.TemporaryDirectory(prefix="kthb-") as tmp:
                src = os.path.join(tmp, "in.pdf")
                with open(src, "wb") as f:
                    f.write(data)
                base = os.path.join(tmp, "t")
                scale = ["-scale-to", str(THUMB_W)] if w == THUMB_W else ["-scale-to-x", str(int(w)), "-scale-to-y", "-1"]
                r = _run(["pdftoppm", "-f", "1", "-l", "1", "-singlefile", *scale, "-jpeg", "-jpegopt",
                          "quality=72", src, base], 30, fsize=16 << 20 if w == THUMB_W else 4 << 20)
                # 2.583.0 (#4812 review): the 800 one has no height cap (a very tall page): over 4 MB it fails, the 320 one stays
                if r.returncode != 0 or not os.path.exists(base + ".jpg"):
                    return None
                with open(base + ".jpg", "rb") as f:
                    return f.read()
        if kind == "image":
            p = subprocess.run([sys.executable, "-I", "-c", THUMB_WORKER, str(int(w))], input=data, capture_output=True,
                               timeout=30, close_fds=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
            return p.stdout if p.returncode == 0 and p.stdout[:2] == b"\xff\xd8" else None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


# 2.146.0 B (#2454): a HEIC / HEIF photo -> a JPEG for the text recognition (Tesseract reads no HEIF). Exit 3 = pi-heif is
# missing in this image (the server says so, never a 500), any other failure = unreadable. #4168: it is missing in the
# official image for now: pi-heif is discontinued, its last release bundles libheif / libde265 with known holes
HEIF_WORKER = r"""
import io, resource, sys
for k, v in ((resource.RLIMIT_AS, 1024 << 20), (resource.RLIMIT_CPU, 30), (resource.RLIMIT_FSIZE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
from PIL import Image, ImageOps
Image.MAX_IMAGE_PIXELS = 80_000_000
have = True
try:
    import pi_heif
    pi_heif.register_heif_opener()
except ImportError:
    have = False
try:
    im = Image.open(io.BytesIO(sys.stdin.buffer.read()))
    im = ImageOps.exif_transpose(im).convert("RGB")
except Exception:
    sys.exit(2 if have else 3)
b = io.BytesIO()
im.save(b, "JPEG", quality=90)
sys.stdout.buffer.write(b.getvalue())
"""


def heif_jpeg(data):
    """(JPEG bytes, None) of a HEIC / HEIF photo, else (None, "no_heif" | "unreadable")."""
    try:
        p = subprocess.run([sys.executable, "-I", "-c", HEIF_WORKER], input=data, capture_output=True, timeout=OCR_PAGE_S,
                           close_fds=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    except (OSError, subprocess.SubprocessError):
        return None, "unreadable"
    if p.returncode == 0 and p.stdout[:2] == b"\xff\xd8":
        return p.stdout, None
    return None, "no_heif" if p.returncode == 3 else "unreadable"


QR_WORKER = r"""
import ctypes, ctypes.util, io, json, resource, sys
for k, v in ((resource.RLIMIT_AS, 768 << 20), (resource.RLIMIT_CPU, 20), (resource.RLIMIT_FSIZE, 0)):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
from PIL import Image
Image.MAX_IMAGE_PIXELS = 80_000_000
try:  # 2.146.0 B (#2454): HEIC / HEIF photos
    import pi_heif
    pi_heif.register_heif_opener()
except Exception:  # noqa: BLE001 -- HEIC support is optional: without it HEIC files are simply not scanned
    pass
lib = ctypes.CDLL(ctypes.util.find_library("zbar") or "libzbar.so.0")
P = ctypes.c_void_p
for fn, res, args in (("zbar_image_scanner_create", P, []), ("zbar_image_scanner_set_config", ctypes.c_int, [P, ctypes.c_int, ctypes.c_int, ctypes.c_int]),
                      ("zbar_image_create", P, []), ("zbar_image_set_format", None, [P, ctypes.c_ulong]),
                      ("zbar_image_set_size", None, [P, ctypes.c_uint, ctypes.c_uint]),
                      ("zbar_image_set_data", None, [P, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]),
                      ("zbar_scan_image", ctypes.c_int, [P, P]), ("zbar_image_first_symbol", P, [P]),
                      ("zbar_symbol_next", P, [P]), ("zbar_symbol_get_data", ctypes.c_char_p, [P]), ("zbar_symbol_get_type", ctypes.c_int, [P]),
                      ("zbar_image_destroy", None, [P]), ("zbar_image_scanner_destroy", None, [P])):
    f = getattr(lib, fn)
    f.restype, f.argtypes = res, args
im = Image.open(io.BytesIO(sys.stdin.buffer.read()))
im.draft("L", (2600, 3600))
im = im.convert("L")
if im.width * im.height > 12_000_000:
    im.thumbnail((3000, 4200))
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
        t = (lib.zbar_symbol_get_data(sym) or b"").decode("utf-8", "replace")[:200]
        # 2.591.0 (#4863, review): digits only count from a QR code (ZBAR_QRCODE = 64) -- an EAN / UPC / Code 128 number of a
        # product or a parcel is no archive number sticker
        if lib.zbar_symbol_get_type(sym) == 64 or not t.strip().isdigit():
            out.append(t)
        sym = lib.zbar_symbol_next(sym)
lib.zbar_image_destroy(img)
lib.zbar_image_scanner_destroy(sc)
print(json.dumps(out))
"""
_QR = {}


def qr_available():
    """True when the zbar library is installed (the QR codes of archive numbers)."""
    if "ok" not in _QR:
        import ctypes.util
        _QR["ok"] = bool(ctypes.util.find_library("zbar"))
    return _QR["ok"]


QR_PAGES = _env_int("KALMIDO_SPLIT_PAGES", 100, 2, 500)  # 2.591.0 B (#4863): pages read for codes at most (= docs/split.py SP_PAGES)
QR_DPI = (200, 300)        # 2.591.0 B (#4863): a second try finer when the first found no code at all (a small sticker)
QR_DPI_PAGES = 10          # ... over this many pages at most (the finer pass costs about twice the time per page)
QR_DOC_S = 120             # 2.591.0 (#4863, review): wall-clock budget of the codes of ONE uploaded document (the queue is serial)


def _qr_read(img):
    """The texts of the QR / bar codes zbar finds on one image (bytes), [] on any trouble."""
    p = subprocess.run([sys.executable, "-I", "-c", QR_WORKER], input=img, capture_output=True, timeout=30, close_fds=True,
                       env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    out = json.loads(p.stdout or b"[]") if p.returncode == 0 else []
    return [str(x) for x in out][:20] if isinstance(out, list) else []


def _qr_page(src, tmp, i, dpi):
    """Page i (1-based) of the PDF file src as a gray PNG (bytes) at dpi, None when it cannot be rendered."""
    base = os.path.join(tmp, f"p{i}-{dpi}")
    r = _run(["pdftoppm", "-r", str(dpi), "-gray", "-f", str(i), "-l", str(i), "-singlefile", "-png", src, base], 30, fsize=128 << 20)
    if r.returncode != 0 or not os.path.exists(base + ".png"):
        return None
    with open(base + ".png", "rb") as f:
        img = f.read()
    os.unlink(base + ".png")
    return img


def qr_pages(n, page, read, want=None, budget=None, clock=time.monotonic):
    """2.591.0 B (#4863): the codes of pages 1..n of a document in page order: page(i, dpi) -> image bytes | None, read(image)
    -> [texts]. First at QR_DPI[0]; when no page had any code, once more at QR_DPI[1] over the first QR_DPI_PAGES pages.
    want(codes so far) -> True stops early (the archive number is found). At most 20 texts. budget: seconds in all, then
    what was found so far (2.591.0 review: a long scan without any code must not hold the document queue for an hour)."""
    n = max(1, min(int(n or 1), QR_PAGES))
    end = None if budget is None else clock() + budget
    for k, dpi in enumerate(QR_DPI):
        out = []
        for i in range(1, (n if k == 0 else min(n, QR_DPI_PAGES)) + 1):
            if end is not None and clock() > end:
                return out[:20]
            img = page(i, dpi)
            if img is None:
                continue
            out += read(img)
            if out and want is not None and want(out):
                return out[:20]
            if len(out) >= 20:
                return out[:20]
        if out:
            return out[:20]
    return []


def qr_codes(data, kind, pages=1, want=None, budget=None):
    """The texts of the QR / bar codes of a PDF (its first pages, 2.591.0 B #4863: up to pages / QR_PAGES, a finer second try
    when none is found, qr_pages) or of an image ([] without zbar or on any trouble)."""
    if kind not in ("pdf", "image") or not qr_available():
        return []
    try:
        if kind == "image":
            return _qr_read(data)
        if not shutil.which("pdftoppm"):
            return []
        with tempfile.TemporaryDirectory(prefix="kqr-") as tmp:
            src = os.path.join(tmp, "in.pdf")
            with open(src, "wb") as f:
                f.write(data)
            return qr_pages(pages, lambda i, dpi: _qr_page(src, tmp, i, dpi), _qr_read, want, budget)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def doc_text(name, mime, data, owner=None, lang=None, langs=None):
    """{"text", "method": "text" | "pdf" | "ocr" | "office" (2.635.0, #4807) | "none", "pages"?, "error"?} -- the text of one document's bytes."""
    kind = file_kind(name, mime, data[:2048])
    if kind == "text":
        return {"text": _decode(data)[:TEXT_CAP], "method": "text", "kind": kind}
    if kind == "pdf":
        r = pdf_text(data)
        if r.get("error") == "busy":
            return {"error": "busy", "kind": kind}
        if not r.get("error") and not r.get("no_text_layer"):
            return {"text": r.get("text") or "", "method": "pdf", "pages": r.get("pages"), "kind": kind}
        if r.get("error") == "encrypted":
            return {"error": "encrypted", "kind": kind}
    if kind in OFFICE_KINDS:  # 2.635.0 (#4807): Word / Excel / OpenDocument: the text of the preview model (limited worker)
        r = dpv_model(data, kind, owner)
        if r.get("error"):
            e = r["error"]
            return {"error": e if e in ("busy", "too_complex", "encrypted") else "unreadable", "kind": kind}
        return {"text": (r.get("text") or "")[:TEXT_CAP], "method": "office", "kind": kind}
    if kind not in ("pdf", "image"):
        return {"text": "", "method": "none", "kind": kind}
    if kind == "image":
        if pm_kind(data[:64]) == "heif":  # 2.146.0 B (#2454): an iPhone photo -> JPEG first
            data, e = heif_jpeg(data)
            if e:
                return {"error": e, "kind": kind}
    o = ocr_bytes(data, kind, lang, langs)
    if o.get("error"):
        return {"error": o["error"], "kind": kind}
    return {"text": o["text"], "method": "ocr", "pages": o.get("pages"), "kind": kind}


if __name__ == "__main__":  # a manual check: python -m kalmido.docs.ocr FILE
    with open(sys.argv[1], "rb") as fh:
        b = fh.read()
    print(json.dumps(ocr_bytes(b, "pdf" if b[:4] == b"%PDF" else "image"), ensure_ascii=False)[:2000])
