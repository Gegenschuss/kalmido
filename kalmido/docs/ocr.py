"""2.48.0 (#1111): the text of a document and its preview image -- only local tools in the container, no network.

PDF with a text layer: the existing reader of attachments (tasks/attachtext.py: pypdf in a limited child process).
Scanned PDF / image: text recognition (OCR) with Tesseract (German + English): pdftoppm rasters page by page (300 dpi),
tesseract reads each page. Every tool runs as a short-lived child process with a memory / CPU / file-size limit and a
time limit PER PAGE, at most OCR_PAGES pages, at most OCR_PARALLEL documents at a time (semaphore). A missing Tesseract
(an older image) gives {"error": "no_ocr"} -- never an exception. Preview: the first page (pdftoppm) or the image
(Pillow in a limited child process), a small JPEG."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading


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


def ocr_langs(app_lang=None, have=None):
    """(the -l value, [missing Tesseract languages of the wanted ones]) for a person whose app language is app_lang: that
    language first, then the base languages; only installed ones are taken, a missing one is reported, never an error."""
    have = ocr_installed() if have is None else have
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


def ocr_bytes(data, kind, lang=None):
    """{"text", "pages", "pages_read", "truncated"} or {"error": "no_ocr" | "busy" | "too_complex" | "unreadable"}.
    kind = "pdf" | "image"; lang = the person's app language (2.122.0, #2101: read with its Tesseract language as well). Blocks while another document is being recognised (the caller is a background worker)."""
    if not ocr_available():
        return {"error": "no_ocr"}
    if not _SEM.acquire(timeout=OCR_PAGE_S * 2):
        return {"error": "busy"}
    langs = ocr_langs(lang)[0]
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
try:  # 2.146.0 B (#2454): HEIC / HEIF photos (pi-heif, read only); an image without it: no preview of them
    import pi_heif
    pi_heif.register_heif_opener()
except Exception:
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


def thumb_bytes(data, kind):
    """A small JPEG of the first page / the image, or None (no tools, damaged file, timeout)."""
    try:
        if kind == "pdf":
            if not shutil.which("pdftoppm"):
                return None
            with tempfile.TemporaryDirectory(prefix="kthb-") as tmp:
                src = os.path.join(tmp, "in.pdf")
                with open(src, "wb") as f:
                    f.write(data)
                base = os.path.join(tmp, "t")
                r = _run(["pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-scale-to", str(THUMB_W), "-jpeg", "-jpegopt",
                          "quality=72", src, base], 30, fsize=16 << 20)
                if r.returncode != 0 or not os.path.exists(base + ".jpg"):
                    return None
                with open(base + ".jpg", "rb") as f:
                    return f.read()
        if kind == "image":
            p = subprocess.run([sys.executable, "-I", "-c", THUMB_WORKER, str(THUMB_W)], input=data, capture_output=True,
                               timeout=30, close_fds=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
            return p.stdout if p.returncode == 0 and p.stdout[:2] == b"\xff\xd8" else None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


# 2.146.0 B (#2454): a HEIC / HEIF photo -> a JPEG for the text recognition (Tesseract reads no HEIF). Exit 3 = pi-heif is
# missing in this image (the server says so, never a 500), any other failure = unreadable
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
except Exception:
    pass
lib = ctypes.CDLL(ctypes.util.find_library("zbar") or "libzbar.so.0")
P = ctypes.c_void_p
for fn, res, args in (("zbar_image_scanner_create", P, []), ("zbar_image_scanner_set_config", ctypes.c_int, [P, ctypes.c_int, ctypes.c_int, ctypes.c_int]),
                      ("zbar_image_create", P, []), ("zbar_image_set_format", None, [P, ctypes.c_ulong]),
                      ("zbar_image_set_size", None, [P, ctypes.c_uint, ctypes.c_uint]),
                      ("zbar_image_set_data", None, [P, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]),
                      ("zbar_scan_image", ctypes.c_int, [P, P]), ("zbar_image_first_symbol", P, [P]),
                      ("zbar_symbol_next", P, [P]), ("zbar_symbol_get_data", ctypes.c_char_p, [P]),
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
        out.append((lib.zbar_symbol_get_data(sym) or b"").decode("utf-8", "replace")[:200])
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


def qr_codes(data, kind):
    """The texts of the QR / bar codes on the first page of a PDF or on an image ([] without zbar or on any trouble)."""
    if kind not in ("pdf", "image") or not qr_available():
        return []
    try:
        img = data
        if kind == "pdf":
            if not shutil.which("pdftoppm"):
                return []
            with tempfile.TemporaryDirectory(prefix="kqr-") as tmp:
                src = os.path.join(tmp, "in.pdf")
                with open(src, "wb") as f:
                    f.write(data)
                base = os.path.join(tmp, "p")
                r = _run(["pdftoppm", "-r", "200", "-gray", "-f", "1", "-l", "1", "-singlefile", "-png", src, base], 30, fsize=128 << 20)
                if r.returncode != 0 or not os.path.exists(base + ".png"):
                    return []
                with open(base + ".png", "rb") as f:
                    img = f.read()
        p = subprocess.run([sys.executable, "-I", "-c", QR_WORKER], input=img, capture_output=True, timeout=30, close_fds=True,
                           env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        out = json.loads(p.stdout or b"[]") if p.returncode == 0 else []
        return [str(x) for x in out][:20] if isinstance(out, list) else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def doc_text(name, mime, data, owner=None, lang=None):
    """{"text", "method": "text" | "pdf" | "ocr", "pages"?, "error"?} -- the text of one document's bytes."""
    from ..tasks.attachtext import file_kind, pdf_text, _decode  # noqa: PLC0415 -- the app's PDF text reader
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
    if kind not in ("pdf", "image"):
        return {"text": "", "method": "none", "kind": kind}
    if kind == "image":
        from ..files.photometa import pm_kind
        if pm_kind(data[:64]) == "heif":  # 2.146.0 B (#2454): an iPhone photo -> JPEG first
            data, e = heif_jpeg(data)
            if e:
                return {"error": e, "kind": kind}
    o = ocr_bytes(data, kind, lang)
    if o.get("error"):
        return {"error": o["error"], "kind": kind}
    return {"text": o["text"], "method": "ocr", "pages": o.get("pages"), "kind": kind}


if __name__ == "__main__":  # a manual check: python -m kalmido.docs.ocr FILE
    with open(sys.argv[1], "rb") as fh:
        b = fh.read()
    print(json.dumps(ocr_bytes(b, "pdf" if b[:4] == b"%PDF" else "image"), ensure_ascii=False)[:2000])
