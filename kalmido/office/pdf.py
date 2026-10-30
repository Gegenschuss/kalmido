"""2.36.1 (#1021, part D): the PDF of an office document (quotation), written without any PDF library.

Input is the print model of office.docs (odoc_render): a plain dict with the document's texts, lines and totals in the
document's language (DE / EN; 2.185.0 C: every app language) -- see office_pdf() below for the keys. Output: the bytes of a PDF/A-3b (PDF 1.7) file with real A4
pages (DIN 5008 form B: address in the window area, sender line above it, key data on the right, fold marks), the
embedded TrueType fonts Liberation Sans Regular / Bold (fonts/, SIL OFL 1.1) in WinAnsiEncoding (umlauts, sharp s,
euro sign), the company's logo as an image (PNG / JPEG / WebP through Pillow -> RGB + FlateDecode) and the company
colour as the only accent (rules, title, category headings). Text wraps with the width tables read from the TTF files.
2.38.0 (#1021 P5): the file is PDF/A-3b -- PDF 1.7, XMP metadata (pdfaid part 3 / B, consistent with the Info
dictionary), an sRGB OutputIntent with the embedded ICC profile (fonts/sRGB2014.icc), a file identifier in the
trailer, all fonts embedded, no encryption, no actions; an invoice / credit note may carry its e-invoice XML as the
embedded file factur-x.xml (AFRelationship Alternative, ZUGFeRD / Factur-X EN 16931 with the fx: XMP schema). Page breaks: following pages carry a
small head (logo, title, number) and repeat the table head; "Page x of y" (only from two pages on) is written in the footer after all pages are laid out;
a category heading never stays alone at the end of a page, text blocks and the rights block are not torn, the totals
never stand alone on a page (the last position comes along); no carry-over lines.

Nothing here reads the database: office.web / office.docs render the model and call office_pdf(model)."""
import contextvars
import datetime
import functools
import hashlib
import io
import json
import logging
import os
import re
import struct
import unicodedata
import zlib

try:
    from ..core.i18n import LANGS, N_, tr
except ImportError:  # 2.185.0 C (#2520): loaded as a single file (tests/office_pdf_test.py, no package): the same translation files
    def _pdf_langs():
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "static", "i18n")
        out = {"en": {}}
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as fh:
                    out[fn[:-5]] = json.load(fh) if fn.endswith(".json") else {}
            except (OSError, ValueError):
                pass
        return out
    LANGS = _pdf_langs()

    def N_(s):
        return s

    def tr(key, *a, lg=None):
        v = LANGS.get(lg or "en", {}).get(key)
        s = v if isinstance(v, str) else key[:key.find("|")] if key.find("|") > 0 else key
        return s.format(*a) if a else s

log = logging.getLogger(__name__)

# ---- geometry (points; 1 mm = 2.8346 pt) ---------------------------------------------------------------------------
MM = 72 / 25.4
A4_W, A4_H = 595.28, 841.89
PDF_L = 25 * MM          # left margin (DIN 5008)
PDF_R = 20 * MM          # right margin
PDF_CW = A4_W - PDF_L - PDF_R
PDF_TOP = 10 * MM        # letterhead starts here
PDF_ADDR_TOP = 45 * MM   # form B: the address field (sender line + recipient) begins 45 mm from the top
PDF_ADDR_H = 45 * MM     # ... and is 45 mm high; the body begins below it
PDF_ADDR_W = 85 * MM
PDF_INFO_X = 125 * MM    # 2.390.0 A (#3350): the info block begins 125 mm from the sheet edge (DIN 5008 form B)
PDF_FOOT_H = 20 * MM     # footer (four columns + page line) reserved at the bottom of every page
PDF_BODY_BOTTOM = A4_H - 12 * MM - PDF_FOOT_H
PDF_SUM_GAP = 18 * MM      # 2.294.0 (#3154): wished gap table -> totals when the closing still fits on the page; 2.380.0 A (#3415): was 11 mm
PDF_SUM_GAP_MIN = 8 * MM   # ... reduced step by step down to this before the page breaks; 2.380.0 A (#3415): was 4 mm
PDF_SUM_AFTER = 3 * MM     # ... and a little air below the totals (given up first as well)
# 2.406.0 (#3491): look A of the quotation PDF (chosen 27.10.2026), only while a quotation is laid out (PDF_LOOK_A);
# 2.434.0 A (#3603): also invoices, credit notes and reminders (PDF_LOOK_A_KINDS), delivery notes keep the old look
PDF_LOOK_A_KINDS = ("offer", "invoice", "credit", "reminder")
PDF_FS_DELTA = -2.0       # every text of the quotation 2 pt smaller ...
PDF_FS_MIN = 6.0          # ... but never below 6 pt (footer, small captions)
PDF_SUM_FILL = 1.0        # share of the free room of the last main page put ABOVE the totals (1 = totals + closing sit at the bottom)
PDF_LOOK_A = contextvars.ContextVar("pdf_look_a", default=False)  # per request: parallel PDFs never see each other's look
PDF_MARK_GREY = "0.85 0.86 0.88"  # 2.294.0 (#3155): the draft watermark (was 0.88 0.89 0.91, fill only)
PDF_NEXT_TOP = 30 * MM   # body top on following pages (below the small head)
P3Q_MAX = 34 * MM        # 2.296.0 E (#3170): the widest quantity column (wider quantities: the unit on a second line)
PDF_LOGO_MAX_W = 45 * MM  # 2.114.5 (#2300): smaller logo (was 60 x 22 mm)
PDF_LOGO_MAX_H = 22 * MM  # 2.357.0 B (#3179): a tall logo gets up to 22 mm (was 16: an upright logo printed 5 mm narrow)
PDF_LOGO_DPI = 200       # 2.357.0 B (#3179): a small logo is never scaled up beyond this (drawn at its own size, not blurred)
# 2.406.0 (#3501): the logo frame per size chosen in the office settings (medium = the frame above); the logo fits inside
PDF_LOGO_SIZES = {"s": (30 * MM, 14 * MM), "m": (PDF_LOGO_MAX_W, PDF_LOGO_MAX_H), "l": (60 * MM, 30 * MM)}
PDF_LOGO_MAX_PX = 1600   # the upload route scales to this width; the writer accepts anything Pillow reads
BP = None                # 2.120.0 E (#2091): the own letterhead in effect -- set only in the run of bp_layout
PDF_MARKS = (105 * MM, 148.5 * MM, 210 * MM)  # 2.357.0 A (#3156): fold and punch marks of the paper size (DIN 5008 form B)
PAPER = "a4"             # 2.357.0 A (#3156): the paper size of this run -- "letter" only in a copy of pdf_paper_ns

# ---- colours ("#rrggbb"); the accent comes from the company settings ----------------------------------------------
C_INK, C_INK2, C_RULE, C_RULE2, C_WHITE = "#16191f", "#4b515c", "#c9ced6", "#e7e9ee", "#ffffff"

# ---- labels in the document language; the pack's labels (model["labels"]) override these -------------------------
# 2.185.0 C (#2520): English keys through tr() in the document's language (was a de / en table; the words stay the same)
PDF_LABELS = {"title": N_("Quotation|pdf"), "number": N_("Quotation No.|pdf"), "date": N_("Date|pdf"), "valid_until": N_("Valid until|pdf"),
              "client": N_("Client|pdf"), "ref": N_("Your reference|pdf"), "project": N_("Project|pdf"), "pos": N_("No.|pdf"),
              "service": N_("Service|pdf"), "qty": N_("Qty|pdf"), "rate": N_("Unit price|pdf"), "vat": N_("VAT|pdf"), "total": N_("Total|pdf"),
              "net": N_("Net total|pdf"), "vat_plus": N_("plus {0} % VAT|pdf"), "gross": N_("Total incl. VAT|pdf"),
              "incl_raw": N_("Net total with option raw data|pdf"),  # 2.114.4 A (#2275)
              "excl_raw": N_("Total excluding raw data|pdf"), "net_suffix": N_("net|pdf"), "optional": N_("Optional|pdf"),
              "rights": N_("Transfer of rights|pdf"),
              "rights_see": N_("Transfer of rights see appendix|pdf"),  # 2.114.1 C (#2258)
              "accept_see": N_("Order confirmation by signature on page {0}|pdf"),  # 2.114.5 (#2300)
              "accept": N_("Order confirmation|pdf"), "place_date": N_("Place, date|pdf"), "sign": N_("Signature, stamp of the client|pdf"),
              "accept_text": N_("We hereby place the order on the terms of this quotation.|pdf"),  # 2.357.0 C (#3182)
              "page": N_("Page {0} of {1}|pdf"), "contact": N_("Contact|pdf"), "register": N_("Registration|pdf"), "bank": N_("Bank|pdf"),
              "discount": N_("Discount|pdf"), "producing": N_("Producing|pdf")}
PDF_COMMA = ("de", "fr", "es", "it", "nl")  # 2.185.0 C (#2520): decimal comma (English: the point)


def pdf_lang(v):
    """2.185.0 C (#2520): the language of a print model: en / de as before, any other app language, else German."""
    s = str(v or "de").strip().lower()
    return "en" if s.startswith("en") else s if s in LANGS else "de"


# ---- the embedded fonts (2.38.0, #1021 P5): Liberation Sans from fonts/, metrics read from the TTF tables ---------
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_FILES = {False: "LiberationSans-Regular.ttf", True: "LiberationSans-Bold.ttf"}
ICC_FILE = os.path.join(FONT_DIR, "sRGB2014.icc")
# WinAnsiEncoding differs from cp1252 in the unassigned codes (bullet) and 0xA0 / 0xAD (space / hyphen)
_WINANSI = {c: (bytes([c]).decode("cp1252", errors="replace") if c not in (0x7F, 0x81, 0x8D, 0x8F, 0x90, 0x9D) else "•") for c in range(32, 256)}
_WINANSI[0xA0], _WINANSI[0xAD] = " ", "-"


class _TTF:
    """A TrueType font file: the tables needed for a simple PDF font (head, hhea, hmtx, cmap format 4, OS/2, post, name).
    widths: advance widths of the WinAnsi codes 32..255 in 1/1000 em (a code without a glyph gets the .notdef width and
    is listed in missing)."""

    def __init__(self, path):
        with open(path, "rb") as fh:
            self.data = d = fh.read()
        n = struct.unpack(">H", d[4:6])[0]
        self.tables = {}
        for k in range(n):
            tag, _cs, off, ln = struct.unpack(">4sIII", d[12 + 16 * k:28 + 16 * k])
            self.tables[tag.decode("latin-1")] = (off, ln)
        head = self._t("head")
        self.upem = struct.unpack(">H", head[18:20])[0] or 1000
        self.bbox = [self._em(x) for x in struct.unpack(">hhhh", head[36:44])]
        hhea = self._t("hhea")
        self.ascent, self.descent = self._em(struct.unpack(">h", hhea[4:6])[0]), self._em(struct.unpack(">h", hhea[6:8])[0])
        n_hm = struct.unpack(">H", hhea[34:36])[0]
        hmtx = self._t("hmtx")
        self.adv = [struct.unpack(">H", hmtx[4 * i:4 * i + 2])[0] for i in range(n_hm)]
        self.cmap = self._cmap4()
        os2 = self._t("OS/2")
        self.cap_height = self._em(struct.unpack(">h", os2[88:90])[0]) if len(os2) >= 90 and struct.unpack(">H", os2[0:2])[0] >= 2 else self.ascent * 0.72
        self.weight = struct.unpack(">H", os2[4:6])[0] if len(os2) >= 6 else 400
        post = self._t("post")
        self.italic_angle = struct.unpack(">i", post[4:8])[0] / 65536.0 if len(post) >= 8 else 0.0
        self.fixed_pitch = bool(struct.unpack(">I", post[12:16])[0]) if len(post) >= 16 else False
        self.ps_name = self._ps_name() or os.path.splitext(os.path.basename(path))[0]
        self.missing = set()
        w = []
        for code in range(32, 256):
            gid = self.cmap.get(ord(_WINANSI[code]), 0)
            if not gid:
                self.missing.add(code)
            w.append(self._em(self.adv[gid] if gid < len(self.adv) else self.adv[-1]))
        self.widths = tuple(w)

    def _t(self, tag):
        off, ln = self.tables.get(tag, (0, 0))
        return self.data[off:off + ln]

    def _em(self, v):
        return v * 1000.0 / self.upem

    def _cmap4(self):
        """unicode -> glyph id from the (3,1) or (0,x) format 4 subtable."""
        c = self._t("cmap")
        n = struct.unpack(">H", c[2:4])[0]
        best = None
        for k in range(n):
            pid, eid, off = struct.unpack(">HHI", c[4 + 8 * k:12 + 8 * k])
            if struct.unpack(">H", c[off:off + 2])[0] != 4:
                continue
            if (pid, eid) == (3, 1):
                best = off
                break
            if pid == 0 and best is None:
                best = off
        out = {}
        if best is None:
            return out
        seg2 = struct.unpack(">H", c[best + 6:best + 8])[0]
        segs = seg2 // 2
        ends = struct.unpack(f">{segs}H", c[best + 14:best + 14 + seg2])
        p = best + 16 + seg2
        starts = struct.unpack(f">{segs}H", c[p:p + seg2])
        p += seg2
        deltas = struct.unpack(f">{segs}h", c[p:p + seg2])
        p += seg2
        ro_at = p
        ros = struct.unpack(f">{segs}H", c[p:p + seg2])
        for i in range(segs):
            for ch in range(starts[i], min(ends[i], 0xFFFE) + 1):
                if ros[i] == 0:
                    gid = (ch + deltas[i]) & 0xFFFF
                else:
                    q = ro_at + 2 * i + ros[i] + 2 * (ch - starts[i])
                    gid = struct.unpack(">H", c[q:q + 2])[0]
                    if gid:
                        gid = (gid + deltas[i]) & 0xFFFF
                if gid:
                    out[ch] = gid
        return out

    def _ps_name(self):
        nm = self._t("name")
        if len(nm) < 6:
            return ""
        cnt, so = struct.unpack(">HH", nm[2:6])
        for k in range(cnt):
            pid, eid, _lid, nid, ln, off = struct.unpack(">HHHHHH", nm[6 + 12 * k:18 + 12 * k])
            if nid == 6:
                raw = nm[so + off:so + off + ln]
                try:
                    return (raw.decode("utf-16-be") if pid in (0, 3) else raw.decode("latin-1")).strip()
                except UnicodeDecodeError:
                    continue
        return ""


_FONTS = {}


def pdf_font(bold=False):
    """The parsed font (cached per process); a missing file raises OSError at the first use."""
    f = _FONTS.get(bool(bold))
    if f is None:
        f = _FONTS[bool(bold)] = _TTF(os.path.join(FONT_DIR, FONT_FILES[bool(bold)]))
        if f.missing:
            log.warning("office pdf: font %s lacks %d WinAnsi glyphs", f.ps_name, len(f.missing))
    return f


# characters outside WinAnsi that appear in office texts, mapped to something the fonts have
_FALLBACK = str.maketrans({"→": "->", "←": "<-", "≤": "<=", "≥": ">=", "−": "-", " ": " ",
                           " ": " ", " ": " ", " ": " ", "‑": "-", "′": "'", "″": '"',
                           "✓": "x", "✔": "x", "☐": "[ ]", "☑": "[x]", "\t": " "})


# 2.296.0 D (#3171): letters without a decomposition that read as their base letter
_TRANSLIT = {"ł": "l", "Ł": "L", "ı": "i", "İ": "I", "ẞ": "SS", "đ": "d", "Đ": "D", "ħ": "h", "Ħ": "H", "ŧ": "t", "Ŧ": "T", "ſ": "s"}


def _clean_char(ch):
    if ch in _TRANSLIT:
        return _TRANSLIT[ch]
    try:
        ch.encode("cp1252")
        return ch
    except UnicodeEncodeError:
        pass
    base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
    try:
        base.encode("cp1252")
        return base or ch
    except UnicodeEncodeError:
        return ch


@functools.lru_cache(maxsize=8192)
def _pdf_text(s):
    # NFC (a decomposed "u" + diaeresis becomes one WinAnsi letter), invisible format characters (soft hyphen, ZWSP,
    # ZWJ, BOM ...) and control characters out, letters WinAnsi lacks as their base letter
    s = unicodedata.normalize("NFC", s)
    s = "".join(c for c in s if c == "\n" or unicodedata.category(c) not in ("Cf", "Cc", "Cs"))
    return s if s.isascii() else "".join(_clean_char(c) for c in s)


def pdf_encode(s):
    """str -> WinAnsi bytes (cp1252; unknown characters become '?'; a code the font has no glyph for as well).
    2.296.0 D (#3171): NFC, invisible characters dropped, Latin letters outside WinAnsi transliterated (the width
    and the drawing both come through here, so they see the same text)."""
    s = _pdf_text(str(s or "").translate(_FALLBACK))
    b = s.encode("cp1252", errors="replace")
    miss = pdf_font(False).missing | pdf_font(True).missing
    if miss and any(ch in miss for ch in b):
        b = bytes(63 if ch in miss else ch for ch in b)
    return b


def pdf_fs(size):
    """2.406.0 (#3491): the printed font size of a nominal size: in look A (a quotation) PDF_FS_DELTA smaller, at least
    PDF_FS_MIN (the 120 pt draft mark is not text); every other document as it is."""
    if not PDF_LOOK_A.get():
        return size
    return size if size >= 60 else max(PDF_FS_MIN, min(size, size + PDF_FS_DELTA))


def pdf_text_width(s, size, bold=False, spacing=0.0):
    """Width of s in points at the given size (plus the character spacing, like the Tc operator)."""
    size = pdf_fs(size)
    b = pdf_encode(s)
    tab = pdf_font(bold).widths
    w = 0
    for ch in b:
        w += tab[ch - 32] if 32 <= ch < 256 else 556
    return w * size / 1000.0 + spacing * len(b)


def pdf_wrap(text, size, width, bold=False, spacing=0.0):
    """Breaks text into lines that fit width (explicit line breaks kept, long words cut by characters).
    2.357.0 B (#3180): spacing = the character spacing of a spaced line (counts into every width, one pass: was a second
    pass in pb_wrap that left single words alone); a word cut between two letters gets a hyphen."""
    def tw(s_):
        return pdf_text_width(s_, size, bold, spacing)
    hw = tw("-")
    out = []
    for para in str(text or "").replace("\r", "").split("\n"):
        words = para.split(" ")
        line = ""
        for w in words:
            cand = (line + " " + w) if line else w
            if tw(cand) <= width or not line and not w:
                line = cand
                continue
            if line:
                out.append(line)
                line = ""
            if tw(w) > width and len(w) > 1:  # a word longer than the line: cut by summed widths, one pass
                part, pw = "", 0.0
                for ch in w:
                    cw = tw(ch)
                    if part and pw + cw > width:
                        carry = ""
                        if part[-1].isalpha() and ch.isalpha():  # 2.357.0 B (#3180): room for the hyphen
                            while len(part) > 2 and pw + hw > width:
                                carry = part[-1] + carry
                                pw -= tw(part[-1])
                                part = part[:-1]
                            if pw + hw <= width and part[-1].isalpha() and (carry or ch)[0].isalpha():
                                part += "-"
                        out.append(part)
                        part, pw = carry, tw(carry) if carry else 0.0
                    part += ch
                    pw += cw
                w = part
            line = w
        out.append(line)
    return out


def pb_wrap(text, size, width, bold=False, spacing=0.0):
    """2.138.0 A (#2240): pdf_wrap for a spaced heading line (the character spacing counts into the width).
    2.357.0 B (#3180): one pass in pdf_wrap (kept as a name for the callers)."""
    return pdf_wrap(text, size, width, bold, spacing)


def _rgb(hexcol):
    h = (hexcol or "").strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = "2f5d8a"
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def pdf_text_color(hexcol, min_contrast=4.5):
    """2.296.0 D (#3172): the colour for TEXT in the company colour: the colour itself when it reads on white (WCAG contrast
    >= min_contrast), else the same hue darkened until it does (rules and fills keep the pure colour)."""
    col = hexcol if isinstance(hexcol, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", hexcol.strip()) else "#2f5d8a"
    rgb = [int(col[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]

    def contrast(c):
        lin = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 1.05 / (0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] + 0.05)
    if contrast(rgb) >= min_contrast:
        return col
    k = 1.0
    while contrast([v * k for v in rgb]) < min_contrast and k > 0.02:
        k -= 0.02
    return "#" + "".join(f"{round(v * k * 255):02x}" for v in rgb)


def pdf_to_8bit(im):
    """2.296.0 D (#3172): a 16 / 32 bit grey picture (I;16, I) on 8 bit L by scaling the value range (65535 -> 255), not by
    clipping (convert("RGB") would cut everything above 255 to white). Other modes come back as they are."""
    from PIL import Image
    if im.mode.startswith("I;16"):
        raw = im.tobytes()
        hi = raw[0::2] if im.mode == "I;16B" else raw[1::2]  # I;16 / I;16L / I;16N on little-endian: the high byte is the 2nd
        if im.mode == "I;16N":
            import sys
            hi = raw[0::2] if sys.byteorder == "big" else raw[1::2]
        return Image.frombytes("L", im.size, hi)
    if im.mode in ("I", "F"):
        lo, top = im.getextrema()
        scale = 1.0 if (lo >= 0 and top <= 255) else (1 / 256.0 if top <= 65535 else 255.0 / max(top, 1))
        return im.point(lambda i: i * scale).convert("L")
    return im


def _f(x):
    return f"{x:.2f}".rstrip("0").rstrip(".") if x != int(x) else str(int(x))


class _Page:
    """Collects the content stream of one page (coordinates: x from the left, y from the TOP, in points)."""
    W, H = A4_W, A4_H  # 2.357.0 A (#3156): the page size (pdf_paper_ns: a US-Letter subclass); pdf_write takes the MediaBox from it

    def __init__(self):
        self.ops = []
        self.images = set()

    def text(self, x, y, s, size, bold=False, color=C_INK, align="l", spacing=0.0, width=None):
        """Draws one line; y is the top of the line box (the baseline sits 0.78 * size below it)."""
        s = str(s or "")
        if not s:
            return
        w = pdf_text_width(s, size, bold, spacing)
        size = pdf_fs(size)  # 2.406.0 (#3491)
        if align == "r":
            x = x + (width or 0) - w if width else x - w
        elif align == "c":
            x = x + ((width or 0) - w) / 2
        elif align == "cr":  # 2.434.0 A (#3603): centred, but a wider line ends at the box's right edge (the GiroCode label)
            x = x + min(((width or 0) - w) / 2, (width or 0) - w)
        r, g, b = _rgb(color)
        self.ops.append(f"BT {r:.3f} {g:.3f} {b:.3f} rg /{'F2' if bold else 'F1'} {size:.2f} Tf {spacing:.2f} Tc "
                        f"{x:.2f} {self.H - y - size * 0.78:.2f} Td <{pdf_encode(s).hex()}> Tj ET")

    def para(self, x, y, text, size, width, bold=False, color=C_INK, lh=None, align="l"):
        """A wrapped paragraph; returns the height used."""
        lh = lh or size * 1.42
        lines = pdf_wrap(text, size, width, bold)
        for i, ln in enumerate(lines):
            self.text(x, y + i * lh, ln, size, bold, color, align=align, width=width)
        return len(lines) * lh

    def line(self, x1, y1, x2, y2, w=0.5, color=C_RULE, dash=None):
        r, g, b = _rgb(color)
        d = f"[{dash[0]} {dash[1]}] 0 d " if dash else "[] 0 d "
        self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {w:.2f} w {d}{x1:.2f} {self.H - y1:.2f} m {x2:.2f} {self.H - y2:.2f} l S")

    def rect(self, x, y, w, h, color, stroke=False, lw=0.5, dash=None):
        r, g, b = _rgb(color)
        if stroke:
            d = f"[{dash[0]} {dash[1]}] 0 d " if dash else "[] 0 d "
            self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {lw:.2f} w {d}{x:.2f} {self.H - y - h:.2f} {w:.2f} {h:.2f} re S")
        else:
            self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {self.H - y - h:.2f} {w:.2f} {h:.2f} re f")

    def mark(self, word):
        """A diagonal word across the page (drafts), drawn first so the content stays on top. 2.294.0 (#3155): bolder (outlined
        too) and a little darker, the same in every office PDF, the content stays readable."""
        size = 120
        w = pdf_text_width(word, size, True)
        self.ops.insert(0, f"q {PDF_MARK_GREY} rg {PDF_MARK_GREY} RG 2 w BT /F2 {size} Tf 2 Tr 0.7071 0.7071 -0.7071 0.7071 "
                           f"{(self.W - w * 0.7071) / 2 + 40:.2f} {(self.H - w * 0.7071) / 2 - 60:.2f} Tm <{pdf_encode(word).hex()}> Tj ET Q")

    def image(self, name, x, y, w, h):
        self.images.add(name)
        self.ops.append(f"q {w:.2f} 0 0 {h:.2f} {x:.2f} {self.H - y - h:.2f} cm /{name} Do Q")


def qac_sig_block_h(rows):
    """2.99.0 C (#2195): the height of the signature box of qac_sig_block for rows."""
    return 16 + 14 + len(rows) * 12 + 18


def qac_sig_block(p, y, rows, head, foot, accent):
    """2.99.0 C (#2195): the box of a simple electronic signature at y (the signed document of office.doctpl, the
    quotation accepted online): head in the accent colour, rows [(label, value)], a closing line."""
    p.rect(PDF_L, y, PDF_CW, qac_sig_block_h(rows), C_RULE, stroke=True, lw=0.6)
    p.text(PDF_L + 10, y + 9, head.upper(), 7.4, True, pdf_text_color(accent), spacing=0.8)  # 2.296.0 D (#3172)
    yy = y + 26
    for a, b in rows:
        p.text(PDF_L + 10, yy, a, 8.4, False, C_INK2)
        p.text(PDF_L + 120, yy, b, 8 if len(b) > 40 else 8.6, True, C_INK)
        yy += 12
    p.text(PDF_L + 10, yy + 2, foot, 7.6, False, C_INK2)


def pdf_logo_frame(co):
    """2.406.0 (#3501): the logo frame of a company model (logo_size s / m / l, logo_pos l / r) -> (max_w, max_h, left).
    Without a choice: medium, right (the look before). Large ends 42 mm from the top, above the address field (45 mm)."""
    co = co or {}
    w, h = PDF_LOGO_SIZES.get(str(co.get("logo_size") or "m"), PDF_LOGO_SIZES["m"])
    return w, h, co.get("logo_pos") == "l"


def pdf_logo_fit(logo, max_w, max_h):
    """2.357.0 B (#3179): the printed size (pt) of a logo (pdf_image_object) in a box of max_w x max_h: fitted, but never
    larger than PDF_LOGO_DPI (a 100 px logo stays small and sharp instead of blown up to the box)."""
    w, h = logo[0], logo[1]
    sc = min(max_w / w, max_h / h, 72.0 / PDF_LOGO_DPI)
    return w * sc, h * sc


def pdf_to_srgb(im):
    """2.357.0 B (#3179): a picture with an embedded colour profile (Adobe RGB, a CMYK JPEG) converted to sRGB (the
    OutputIntent of the PDF); without ImageCms or on any error the picture comes back as it was."""
    icc = im.info.get("icc_profile")
    if not icc or im.mode not in ("RGB", "RGBA", "CMYK"):
        return im
    try:
        from PIL import ImageCms
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        return ImageCms.profileToProfile(im, src, ImageCms.createProfile("sRGB"), outputMode="RGBA" if im.mode == "RGBA" else "RGB")
    except Exception:  # noqa: BLE001  (no ImageCms / littlecms, a broken profile)
        return im


def pdf_image_object(raw):
    """Logo bytes (PNG / JPEG / WebP / GIF / BMP) -> (width px, height px, stream dict entries, stream data) for an
    image XObject: RGB 8 bit, transparency composed on white, FlateDecode. None when Pillow cannot read it."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        im = Image.open(io.BytesIO(raw))
        if im.width * im.height > 30_000_000:
            return None
        im.load()
        im = pdf_to_8bit(im)  # 2.296.0 D (#3172): 16 bit grey scaled, not clipped to white
        im = pdf_to_srgb(im)  # 2.357.0 B (#3179): Adobe RGB / CMYK with a profile -> sRGB
        if im.mode in ("RGBA", "LA", "P", "PA"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        else:
            im = im.convert("RGB")
        if im.width > PDF_LOGO_MAX_PX:
            im = im.resize((PDF_LOGO_MAX_PX, max(1, round(im.height * PDF_LOGO_MAX_PX / im.width))), Image.Resampling.LANCZOS)
        data = zlib.compress(im.tobytes(), 6)
        return im.width, im.height, data
    except Exception:  # noqa: BLE001  (not a picture, truncated, bomb)
        return None


def _xml_esc(s):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _pdf_date(dt):
    """datetime (aware) -> (PDF string D:YYYYMMDDHHmmSS+01'00', XMP ISO 8601 with offset)."""
    off = dt.utcoffset() or datetime.timedelta(0)
    sign = "-" if off.total_seconds() < 0 else "+"
    mins = abs(int(off.total_seconds())) // 60
    return (dt.strftime("D:%Y%m%d%H%M%S") + f"{sign}{mins // 60:02d}'{mins % 60:02d}'",
            dt.strftime("%Y-%m-%dT%H:%M:%S") + f"{sign}{mins // 60:02d}:{mins % 60:02d}")


def epdf_xmp(title, author, producer, creator, created, modified, xml_name=None, xml_profile="EN 16931", doc_type="INVOICE"):
    """The XMP packet of a PDF/A-3b file (bytes, UTF-8, no filter); with xml_name the Factur-X / ZUGFeRD extension schema."""
    fx = ""
    if xml_name:
        fx = f"""
  <rdf:Description rdf:about="" xmlns:pdfaExtension="http://www.aiim.org/pdfa/ns/extension/" xmlns:pdfaSchema="http://www.aiim.org/pdfa/ns/schema#" xmlns:pdfaProperty="http://www.aiim.org/pdfa/ns/property#">
   <pdfaExtension:schemas>
    <rdf:Bag>
     <rdf:li rdf:parseType="Resource">
      <pdfaSchema:schema>Factur-X PDFA Extension Schema</pdfaSchema:schema>
      <pdfaSchema:namespaceURI>urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#</pdfaSchema:namespaceURI>
      <pdfaSchema:prefix>fx</pdfaSchema:prefix>
      <pdfaSchema:property>
       <rdf:Seq>
        <rdf:li rdf:parseType="Resource">
         <pdfaProperty:name>DocumentFileName</pdfaProperty:name>
         <pdfaProperty:valueType>Text</pdfaProperty:valueType>
         <pdfaProperty:category>external</pdfaProperty:category>
         <pdfaProperty:description>name of the embedded XML invoice file</pdfaProperty:description>
        </rdf:li>
        <rdf:li rdf:parseType="Resource">
         <pdfaProperty:name>DocumentType</pdfaProperty:name>
         <pdfaProperty:valueType>Text</pdfaProperty:valueType>
         <pdfaProperty:category>external</pdfaProperty:category>
         <pdfaProperty:description>INVOICE</pdfaProperty:description>
        </rdf:li>
        <rdf:li rdf:parseType="Resource">
         <pdfaProperty:name>Version</pdfaProperty:name>
         <pdfaProperty:valueType>Text</pdfaProperty:valueType>
         <pdfaProperty:category>external</pdfaProperty:category>
         <pdfaProperty:description>The actual version of the Factur-X XML schema</pdfaProperty:description>
        </rdf:li>
        <rdf:li rdf:parseType="Resource">
         <pdfaProperty:name>ConformanceLevel</pdfaProperty:name>
         <pdfaProperty:valueType>Text</pdfaProperty:valueType>
         <pdfaProperty:category>external</pdfaProperty:category>
         <pdfaProperty:description>The conformance level of the embedded Factur-X data</pdfaProperty:description>
        </rdf:li>
       </rdf:Seq>
      </pdfaSchema:property>
     </rdf:li>
    </rdf:Bag>
   </pdfaExtension:schemas>
  </rdf:Description>
  <rdf:Description rdf:about="" xmlns:fx="urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#">
   <fx:DocumentType>{_xml_esc(doc_type)}</fx:DocumentType>
   <fx:DocumentFileName>{_xml_esc(xml_name)}</fx:DocumentFileName>
   <fx:Version>1.0</fx:Version>
   <fx:ConformanceLevel>{_xml_esc(xml_profile)}</fx:ConformanceLevel>
  </rdf:Description>"""
    xmp = f"""<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/">
   <pdfaid:part>3</pdfaid:part>
   <pdfaid:conformance>B</pdfaid:conformance>
  </rdf:Description>
  <rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{_xml_esc(title)}</rdf:li></rdf:Alt></dc:title>
   <dc:creator><rdf:Seq><rdf:li>{_xml_esc(author)}</rdf:li></rdf:Seq></dc:creator>
  </rdf:Description>
  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/">
   <xmp:CreatorTool>{_xml_esc(creator)}</xmp:CreatorTool>
   <xmp:CreateDate>{created}</xmp:CreateDate>
   <xmp:ModifyDate>{modified}</xmp:ModifyDate>
  </rdf:Description>
  <rdf:Description rdf:about="" xmlns:pdf="http://ns.adobe.com/pdf/1.3/">
   <pdf:Producer>{_xml_esc(producer)}</pdf:Producer>
  </rdf:Description>{fx}
 </rdf:RDF>
</x:xmpmeta>
""" + " " * 2000 + "\n<?xpacket end=\"w\"?>"
    return xmp.encode("utf-8")


def _meta_text(s):
    """2.296.0 D (#3171): a metadata string (Info dictionary and XMP alike): NFC, no control / invisible characters, one line."""
    s = unicodedata.normalize("NFC", str(s or "")).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return "".join(c for c in s if unicodedata.category(c) not in ("Cf", "Cc", "Cs")).strip()


def pdf_write(pages, images, title="", author="", xml=None, meta=None):
    """Serialises pages ([_Page]) and images ({name: (w, h, data)}) into PDF/A-3b bytes (PDF 1.7: embedded TrueType fonts,
    XMP + Info, sRGB OutputIntent, trailer ID). xml: bytes of the e-invoice to embed as factur-x.xml (AFRelationship
    Alternative, fx: XMP schema). meta: {"when": aware datetime, "producer", "creator", "xml_name", "xml_profile", "doc_type"}."""
    meta = meta or {}
    title, author = _meta_text(title), _meta_text(author)  # 2.296.0 D (#3171): Info and XMP carry the same text
    objs = []  # list of bytes bodies; object number = index + 1

    def add(body):
        objs.append(body)
        return len(objs)

    def pstr(s):
        return b"(" + pdf_encode(s).replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"

    def tstr(s):
        # 2.296.0 D (#3171): a PDF text string (Info dictionary): plain ASCII as it is, else UTF-16BE with BOM (not cp1252)
        s = _meta_text(s)
        if s.isascii():
            return b"(" + s.encode("ascii").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"
        return b"<FEFF" + s.encode("utf-16-be", errors="replace").hex().upper().encode() + b">"

    def stream(dict_entries, data, compress=True):
        if compress:
            data = zlib.compress(data, 6)
            dict_entries = dict_entries + " /Filter /FlateDecode"
        return add(f"<< {dict_entries} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream")

    # -- fonts: a simple TrueType font per face with its descriptor and the whole font program
    font_ids = {}
    for bold in (False, True):
        f = pdf_font(bold)
        ff = stream(f"/Length1 {len(f.data)}", f.data)
        flags = 32 | (1 if f.fixed_pitch else 0) | (1 << 18 if bold else 0)
        fd = add(f"<< /Type /FontDescriptor /FontName /{f.ps_name} /Flags {flags} /FontBBox [{' '.join(f'{v:.0f}' for v in f.bbox)}] "
                 f"/ItalicAngle {f.italic_angle:.0f} /Ascent {f.ascent:.0f} /Descent {f.descent:.0f} /CapHeight {f.cap_height:.0f} "
                 f"/StemV {140 if bold else 80} /FontFile2 {ff} 0 R >>".encode())
        font_ids[bold] = add(f"<< /Type /Font /Subtype /TrueType /BaseFont /{f.ps_name} /FirstChar 32 /LastChar 255 "
                             f"/Widths [{' '.join(f'{w:.2f}'.rstrip('0').rstrip('.') for w in f.widths)}] /Encoding /WinAnsiEncoding "
                             f"/FontDescriptor {fd} 0 R >>".encode())
    img_ids = {}
    for name, (w, h, data) in images.items():
        img_ids[name] = add(f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB "
                            f"/BitsPerComponent 8 /Filter /FlateDecode /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream")
    form_ids = {}  # 2.120.0 E (#2091): the letterhead pages (page.forms {name: emit(objs) -> object number}), each written once
    for p in pages:
        for n, emit in sorted((getattr(p, "forms", None) or {}).items()):
            if n not in form_ids:
                form_ids[n] = emit(objs)
    pages_id = len(objs) + 1 + 2 * len(pages)  # the Pages object comes after all page + content objects
    page_ids = []
    for p in pages:
        content = zlib.compress("\n".join(p.ops).encode("latin-1"), 6)
        cid = add(f"<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n".encode() + content + b"\nendstream")
        xo = " ".join([f"/{n} {img_ids[n]} 0 R" for n in sorted(p.images) if n in img_ids] + [f"/{n} {form_ids[n]} 0 R" for n in sorted(getattr(p, "forms", None) or {})])
        pid = add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {p.W:.2f} {p.H:.2f}] "
                  f"/Resources << /Font << /F1 {font_ids[False]} 0 R /F2 {font_ids[True]} 0 R >> /XObject << {xo} >> "
                  f"/ProcSet [/PDF /Text /ImageC] >> /Contents {cid} 0 R >>".encode())
        page_ids.append(pid)
    assert len(objs) + 1 == pages_id
    add(f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in page_ids)}] /Count {len(page_ids)} >>".encode())

    # -- PDF/A: output intent (sRGB), XMP, the embedded e-invoice
    when = meta.get("when") or datetime.datetime.now(datetime.timezone.utc).astimezone()
    d_pdf, d_xmp = _pdf_date(when)
    try:
        from ..core.config import APP_VERSION  # 2.117.0 C (#2262): "Kalmido v<version>" in all PDFs
    except ImportError:  # 2.117.1: the module loaded on its own (office_pdf_test) -> the VERSION file next to the app
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VERSION"), encoding="utf-8") as f:
                APP_VERSION = f.read().strip()
        except OSError:
            APP_VERSION = "?"
    producer = str(meta.get("producer") or f"Kalmido v{APP_VERSION}")
    creator = str(meta.get("creator") or f"Kalmido v{APP_VERSION}")
    try:
        with open(ICC_FILE, "rb") as fh:
            icc = fh.read()
    except OSError:
        icc = b""
        log.warning("office pdf: ICC profile %s missing, no OutputIntent", ICC_FILE)
    extra = ""
    if icc:
        icc_id = stream("/N 3 /Alternate /DeviceRGB", icc)
        oi = add(f"<< /Type /OutputIntent /S /GTS_PDFA1 /OutputConditionIdentifier (sRGB) /Info (sRGB2014) "
                 f"/RegistryName (http://www.color.org) /DestOutputProfile {icc_id} 0 R >>".encode())
        extra += f" /OutputIntents [{oi} 0 R]"
    xml_name = None
    if xml:
        xml_name = str(meta.get("xml_name") or "factur-x.xml")
        ef = stream(f"/Type /EmbeddedFile /Subtype /application#2Fxml /Params << /ModDate ({d_pdf}) /Size {len(xml)} >>", xml)
        fs = add(b"<< /Type /Filespec /F " + pstr(xml_name) + b" /UF " + pstr(xml_name) + b" /Desc (Factur-X / ZUGFeRD invoice) "
                 b"/AFRelationship /Alternative /EF << /F " + f"{ef} 0 R /UF {ef} 0 R".encode() + b" >> >>")
        extra += f" /Names << /EmbeddedFiles << /Names [" + " ".join([pstr(xml_name).decode("latin-1"), f"{fs} 0 R"]) + "] >> >> " + f"/AF [{fs} 0 R]"
    xmp = epdf_xmp(title, author, producer, creator, d_xmp, d_xmp, xml_name=xml_name,
                   xml_profile=meta.get("xml_profile") or "EN 16931", doc_type=meta.get("doc_type") or "INVOICE")
    md = stream("/Type /Metadata /Subtype /XML", xmp, compress=False)
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R /Metadata {md} 0 R /MarkInfo << /Marked false >>{extra} >>".encode())
    info = add(b"<< /Producer " + tstr(producer) + b" /Creator " + tstr(creator) + b" /Title " + tstr(title) + b" /Author " + tstr(author) +
               b" /CreationDate (" + d_pdf.encode() + b") /ModDate (" + d_pdf.encode() + b") >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for o in offsets:
        out.write(f"{o:010d} 00000 n \n".encode())
    fid = hashlib.md5(out.getvalue() + d_pdf.encode(), usedforsecurity=False).hexdigest()  # file identifier only
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R /ID [<{fid}> <{fid}>] >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


# ---- number and date formats in the document language -------------------------------------------------------------
def pdf_money(v, lang, currency, fmt=None, places=2):
    """1234.5 -> "1.234,50 €" (de) / "€1,234.50" (en); fmt = the pack's formats (optional).
    2.185.0 C (#2520): without fmt nl / fr / es / it write the decimal comma like de. 2.296.0 B (#3175): the one format of
    calc.fmt_money (language table, "$" like the model's texts); the pack's formats only for German documents.
    2.354.0 A (#2831): places 3 / 4 for a unit price (pdf_rate_places)."""
    fmt = fmt or {}
    if str(lang or "de").split("-")[0] != "de" or not fmt:
        return _pdf_fmt_money(v, lang, currency or "EUR", places)
    comma = str(lang or "").split("-")[0] in PDF_COMMA
    dec = fmt.get("decimal") or ("," if comma else ".")
    tho = fmt.get("thousands") or ("." if comma else ",")
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    neg = v < 0
    s = f"{abs(v):,.{places}f}".replace(",", "\x00").replace(".", dec).replace("\x00", tho)
    sym = fmt.get("currency_symbol") or {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}.get(currency or "EUR", currency or "")
    s = f"{sym} {s}" if (fmt.get("currency_pos") == "before") else f"{s} {sym}"
    return ("-" if neg else "") + s


def pdf_rate_places(v):
    """2.354.0 A (#2831): the places of a unit price on paper: 2, or 3 / 4 when it has them (0.125 -> 3)."""
    try:
        s = f"{float(v or 0):.4f}".rstrip("0")
    except (TypeError, ValueError):
        return 2
    return max(2, min(4, len(s.split(".")[1]) if "." in s else 0))


def _pdf_fmt_money(v, lang, currency, places=2):
    """2.296.0 B (#3175): calc.fmt_money (the package's, or calc.py next to this file when loaded on its own)."""
    global _PDF_CALC
    if _PDF_CALC is None:  # loaded on its own (tests): calc.py next to this file
        import importlib.util
        sp = importlib.util.spec_from_file_location("office_calc_for_pdf", os.path.join(os.path.dirname(os.path.abspath(__file__)), "calc.py"))
        _c = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(_c)
        _PDF_CALC = _c
    try:
        return _PDF_CALC.fmt_money(v if v not in (None, "") else 0, lang, currency, places)
    except (TypeError, ValueError, ArithmeticError):
        return _PDF_CALC.fmt_money(0, lang, currency)


try:
    from . import calc as _PDF_CALC
except ImportError:
    _PDF_CALC = None


def pdf_num(v, lang, fmt=None):
    """A quantity: 3 -> "3", 4.5 -> "4,5" (de, 2.185.0 C: nl / fr / es / it too) / "4.5" (en)."""
    fmt = fmt or {}
    dec = fmt.get("decimal") or ("," if str(lang or "").split("-")[0] in PDF_COMMA else ".")
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return str(v)
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", dec)


def pdf_date(s, lang, fmt=None):
    """ISO date -> "09.10.2026" (de) / "9 October 2026" (en); anything else is returned as it is. 2.185.0 C (#2520): other
    languages "9 octobre 2026" with the month names of their translation file."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(s or "")[:10])
    if not m:
        return str(s or "")
    y, mo, d = m.groups()
    if lang == "de":
        return f"{d}.{mo}.{y}"
    mons = LANGS.get(str(lang or ""), {}).get("_months") if lang != "en" else None
    if isinstance(mons, list) and len(mons) == 12:
        if lang == "es":  # 2.357.0 D (#3183): "9 de octubre de 2026"
            return f"{int(d)} de {mons[int(mo) - 1]} de {y}"
        return f"{int(d)} {mons[int(mo) - 1]} {y}"
    months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
    return f"{int(d)} {months[int(mo) - 1]} {y}"


# ---- the document ------------------------------------------------------------------------------------------------------
PDF_CC2 = ("20", "27", "30", "31", "32", "33", "34", "36", "39", "40", "41", "43", "44", "45", "46", "47", "48", "49", "51", "52", "53",
           "54", "55", "56", "57", "58", "60", "61", "62", "63", "64", "65", "66", "81", "82", "84", "86", "90", "91", "92", "93", "94", "95", "98")
PDF_DE_AREA2 = ("30", "40", "69", "89")
PDF_DE_AREA3 = ("228", "234", "335", "340", "345", "355", "365", "375", "385", "395")


def pdf_phone(s):
    """2.114.4 A (#2272): a phone number grouped for print ("+4922178966436" -> "+49 221 78966436"); only display, the
    stored value stays. A number the user already spaced stays as it is. German area codes by a simple rule (Berlin,
    Hamburg, Frankfurt, Munich 2 digits; "xx1" and a few big cities 3; mobile 15x 4, 16x / 17x 3; else 4), other
    countries only split off the country code."""
    t = str(s or "").strip()
    if not t or " " in t or not re.fullmatch(r"(\+|00)?[0-9/()\-]{6,}", t):
        return t
    d = re.sub(r"\D", "", t)
    if t.startswith("+") or t.startswith("00"):
        d = d[2:] if t.startswith("00") else d
        cc = d[:1] if d[:1] in ("1", "7") else d[:2] if d[:2] in PDF_CC2 else d[:3]
        nat, pre = d[len(cc):], "+" + cc + " "
        if cc != "49":
            return pre + nat
    elif d.startswith("0") and not d.startswith("00"):
        nat, pre = d[1:], "0"
    else:
        return t
    nat = nat.lstrip("0")
    if nat[:3] in ("800", "180", "900"):  # service numbers 0800 / 0180 / 0900 (review)
        n = 3
    elif nat[:2] in PDF_DE_AREA2:
        n = 2
    elif nat[:2] in ("15",):
        n = 4
    elif nat[:2] in ("16", "17") or nat[2:3] == "1" or nat[:3] in PDF_DE_AREA3:
        n = 3
    else:
        n = 4
    if len(nat) <= n + 2:
        return t
    return pre + nat[:n] + " " + nat[n:]


def pdf_phone_in(ln):
    """2.114.4 A (#2272): ln with every unspaced phone number in it grouped (a footer line "Tel. +4922178966436")."""
    return re.sub(r"(?<![\w@.])(?:\+|00|0)[0-9][0-9/()\-]{5,}(?![\w@])", lambda mt: pdf_phone(mt.group(0)), str(ln))


class _FooterCols(list):
    n_name = 1
    raw = None


def pdf_footer_cols(co):
    """2.114.4 A (#2271): the footer columns of a printed company (name + address, contact, register, bank; empty
    ones left out) -> [[(line, keep)]]; keep = the line never breaks (address, phone / email, IBAN / BIC / tax number)."""
    co = co or {}
    # 2.99.0 D (#2188): the up to three name lines one under the other; with a long first column (review L3) one line
    nl = [str(x).strip() for x in (co.get("name_lines") or str(co.get("name") or "").split("\n")) if str(x).strip()][:3] or [""]
    head = list(dict.fromkeys(nl + [str(x) for x in (co.get("lines") or [])]))
    if len(nl) > 1 and len(head) > 6:
        head = list(dict.fromkeys([" ".join(nl)] + [str(x) for x in (co.get("lines") or [])]))
        nl = [" ".join(nl)]
    cols = [[(ln, j > 0) for j, ln in enumerate(head)], [(pdf_phone_in(x), True) for x in (co.get("contact_lines") or [])],
            [(str(x), False) for x in (co.get("register_lines") or [])], [(str(x), True) for x in (co.get("bank_lines") or [])]]
    out = _FooterCols(p3f_three(c, len(nl) if i == 0 else 0) for i, c in enumerate(cols) if any(ln.strip() for ln, _ in c))
    out.n_name = len(nl)  # 2.138.2 B (#2397): how many leading lines of column 1 are the (bold) name
    # 2.296.0 A (#3164): the columns before the three-line joining, for p3f_fit to move a long entry below the columns
    out.raw = [(c, len(nl) if i == 0 else 0) for i, c in enumerate(cols) if any(ln.strip() for ln, _ in c)]
    return out


def p3f_three(col, n_name=0):
    """2.114.5 (#2300): a footer column of at most three lines: the address lines below the n_name name lines join with
    ", ", elsewhere the two neighbours with the shortest joined text join with " · " (bank name / IBAN / BIC / tax number)."""
    if n_name:
        if len(col) > n_name + 1:
            col = col[:n_name] + [(", ".join(ln for ln, _ in col[n_name:]), True)]
        return col
    col = [(ln, k) for ln, k in col if str(ln).strip()]
    while len(col) > 3:  # the two shortest lines join (bank name + BIC), at the place of the first
        a, b = sorted(sorted(range(len(col)), key=lambda q: len(col[q][0]))[:2])
        col[a] = (col[a][0] + " · " + col[b][0], col[a][1] and col[b][1])
        del col[b]
    return col


_P3W = {}


def p3f_w(s, fs, bold=False):
    """2.296.0 A (#3164): pdf_text_width remembered for the footer fitting (it tries many layouts)."""
    k = (s, fs, bool(bold), PDF_LOOK_A.get())  # 2.406.0 (#3491): look A prints smaller, its widths apart
    w = _P3W.get(k)
    if w is None:
        if len(_P3W) > 20000:
            _P3W.clear()
        w = _P3W[k] = pdf_text_width(s, fs, bold)
    return w


def bwa_half(ln, fs, bold=False):
    """2.114.4 A (#2271): the narrowest width at which ln takes at most two lines (the wider half of the best split)."""
    ws = ln.split(" ")
    return min([max(p3f_w(" ".join(ws[:q]), fs, bold), p3f_w(" ".join(ws[q:]), fs, bold)) for q in range(1, len(ws))]
               or [p3f_w(ln, fs, bold)])


def bwa_wrap(ln, keep, fs, width, bold=False):
    """2.114.4 A (#2271): a footer line within width: whole when it fits (an unbreakable line always tries so), a
    "Label: value" line breaks after the label first, everything else wraps by words. 2.296.0 A (#3164): an unbreakable
    line only between its joined entries."""
    if p3f_w(ln, fs, bold) <= width:
        return [ln]
    if not keep and ": " in ln:
        a, b = ln.split(": ", 1)
        if p3f_w(a + ":", fs, bold) <= width and p3f_w(b, fs, bold) <= width:
            return [a + ":", b]
    if keep:  # 2.296.0 A (#3164): an unbreakable line breaks only between its joined entries (" · ", ", "), never inside one
        sp = re.split(r"( · |, )", ln)
        out, cur = [], sp[0]
        for sep, t in zip(sp[1::2], sp[2::2]):
            if p3f_w(cur + sep + t, fs, bold) <= width:
                cur += sep + t
            else:
                out.append(cur + sep.rstrip(" ·"))  # "a," / "a" (the dot is left out)
                cur = t
        out.append(cur)
        # an entry wider than the column (p3f_fit moves it below the columns first) wraps as before
        return [x for o in out for x in (pdf_wrap(o, fs, width, bold=bold) if p3f_w(o, fs, bold) > width else [o])]
    return pdf_wrap(ln, fs, width, bold=bold)


def p3f_atoms(ln, keep):
    """2.296.0 A (#3164): the parts of a footer line that never break: an unbreakable line's joined entries, else words."""
    return [x for x in (re.split(r" · |, ", str(ln)) if keep else str(ln).split(" ")) if x] or [str(ln)]


class _FootFit(tuple):
    full = ()  # 2.296.0 A (#3164): the wrapped full-width lines below the columns


P3F_MIN_FS = 6.5  # 2.296.0 A (#3164): the smallest footer font (was 6.0)


def p3f_fit(cols, width=None):
    """2.114.4 A (#2271): the footer's font size, column widths and wrapped lines -> (fs, cws, shown). Widths follow the
    content: every column gets at least its longest unbreakable line (an IBAN, "E-Mail x"), the rest goes to the columns
    that still wrap; when even that does not fit, the font shrinks a little. 2.114.5 (#2300): aims at three lines.
    2.296.0 A (#3164): nothing is ever cut: a long entry (shareholders, a line over three lines) or an unbreakable line
    that finds no room in its column moves to a full-width line below the columns (.full of the result); width = the
    footer width (default PDF_CW, a letter on a letterhead passes its own)."""
    width = PDF_CW if width is None else width
    nn = max(1, getattr(cols, "n_name", 1))
    # the entries before the three-line joining (pdf_footer_cols.raw); t = name lines of the column, None = no joining
    raw = [(list(c), t) for c, t in getattr(cols, "raw", None) or [(c, None) for c in cols or []]]
    bold = lambda i, j: i == 0 and j < nn  # noqa: E731

    memo = {}

    def lay(raw):  # -> columns, fit, column lines, cut lines (a part wider than its column), long lines (three and more / wide)
        key = repr(raw)
        if key not in memo:
            memo[key] = lay1(raw)
        return memo[key]

    def lay1(raw):
        cur = [c if t is None else p3f_three(list(c), t) for c, t in raw]
        fs, cws, shown, _ok = p3f_core(cur, nn, width - 8 * (max(1, len(cur)) - 1))
        cut = [ln for i, c in enumerate(cur) for j, (ln, k) in enumerate(c)
               if not bold(i, j) and max(p3f_w(w, fs, bold(i, j)) for w in p3f_atoms(ln, k)) > cws[i] - 2]
        long = [ln for i, c in enumerate(cur) for j, (ln, k) in enumerate(c) if not bold(i, j) and not k and
                (len(bwa_wrap(ln, k, fs, cws[i] - 2, bold(i, j))) >= 3 or (cws[i] < p3f_w(ln, fs) and p3f_w(ln, fs) > width * 0.4))]
        return cur, (fs, cws, shown), max([len(x) for x in shown] or [0]), cut, long

    def without(raw, i, q):
        out = [(list(c), t) for c, t in raw]
        out[i][0].pop(q)
        return [x for x in out if any(str(r).strip() for r, _k in x[0])]

    full, nf = [], 0  # the moved entries, their line count at full width
    for n in range(13):
        cur, fit, h, cut, long = lay(raw)
        fs = fit[0]
        if n == 12 or (not cut and not long and h <= 3):  # the last round only lays out; three lines, nothing cut: done
            break
        opts = []  # (cut lines after the move, footer lines after it, -width, column, entry, the entry is in a long line)
        for i, (c, t) in enumerate(raw):
            for q, (r, _k) in enumerate(c):
                if q < (t if t is not None else nn if i == 0 else 0) or not str(r).strip():
                    continue
                _c2, _f2, h2, cut2, _l2 = lay(without(raw, i, q))
                opts.append((len(cut2), h2 + nf + len(pdf_wrap(str(r), fs, width - 2)), -p3f_w(str(r), fs), i, q,
                             any(str(r) in x for x in long)))
        if cut:  # a part would be cut inside (an IBAN, an e-mail address): the move that leaves the fewest cuts
            pick = min(opts, default=None)
        else:
            pick = min([o for o in opts if not o[0]], default=None)
            if pick and pick[1] >= h + nf:  # no lower footer: a long entry (shareholders) moves when the footer does not grow
                pick = min([o for o in opts if not o[0] and o[5] and o[1] <= h + nf], default=None) or (pick if h > 6 else None)
        if pick is None:
            break
        ln = str(raw[pick[3]][0][pick[4]][0])
        full.append(ln)
        nf += len(pdf_wrap(ln, fs, width - 2))
        raw = without(raw, pick[3], pick[4])
    out = _FootFit(fit)
    out.full = [x for ln in full for x in pdf_wrap(ln, fs, width - 2)]
    return out


def p3f_core(cols, nn, free):
    """p3f_fit for fixed columns -> (fs, cws, shown, ok); ok = every unbreakable line keeps its line (no width cut)."""
    fs, cws, shown = 6.9, [], []
    ok6 = None
    if cols:
        bold = lambda i, j: i == 0 and j < nn  # noqa: E731  2.138.2 B (#2397): every name line is bold
        # no break at all when a slightly smaller font allows it, else the narrowest font that keeps every unbreakable line
        # 2.296.0 A (#3164): never below 6.5 pt; whole = -1: an unbreakable line may break between its entries (one line more)
        for fs, whole in ((6.9, 1), (6.6, 1), (P3F_MIN_FS, 1), (6.9, 0), (6.6, 0), (P3F_MIN_FS, 0), (P3F_MIN_FS, -1)):
            nat = [max(p3f_w(ln, fs, bold(i, j)) for j, (ln, _k) in enumerate(c)) + 3 for i, c in enumerate(cols)]
            low = [max(p3f_w(ln, fs, bold(i, j)) if k and whole >= 0 else
                       max(p3f_w(x, fs, bold(i, j)) for x in p3f_atoms(ln, k)) if k else bwa_half(ln, fs, bold(i, j))
                       for j, (ln, k) in enumerate(c)) + 3 for i, c in enumerate(cols)]
            if whole > 0 and sum(nat) > free:
                continue
            if sum(nat) <= free:
                cws = [w + (free - sum(nat)) / len(cols) for w in nat]
            elif sum(low) <= free:
                want = [a - b for a, b in zip(nat, low)]
                cws = [b + (free - sum(low)) * w / sum(want) for b, w in zip(low, want)]
            else:
                cws = [free * b / sum(low) for b in low]
            lay = lambda i, w: [(x, j < nn) for j, (ln, k) in enumerate(cols[i]) for x in bwa_wrap(ln, k, fs, w - 2, bold(i, j))]  # noqa: E731
            shown = [lay(i, w) for i, w in enumerate(cws)]
            # 2.114.5 (#2300): a column over three lines takes width from the others as long as they keep their line count
            for _ in range(60):
                need = max(range(len(cols)), key=lambda i: len(shown[i]))
                if len(shown[need]) <= 3 or sum(low) > free:
                    break
                give = [i for i in range(len(cols)) if i != need and cws[i] - 4 >= low[i] and len(lay(i, cws[i] - 4)) == len(shown[i])]
                if not give:
                    break
                for i in give:
                    cws[i] -= 4
                    cws[need] += 4
                shown = [lay(i, w) for i, w in enumerate(cws)]
            if sum(low) <= free and max(len(x) for x in shown) <= 3:
                return fs, cws, shown, True
            if ok6 is None and sum(low) <= free:
                ok6 = (fs, cws, shown, True)  # three lines not reachable: the first layout that keeps every unbreakable line
        return ok6 or (fs, cws, shown, False)
    return fs, cws, shown, True


def p3f_lines(fit):
    """2.296.0 A (#3164): the number of footer text lines (tallest column + the full-width lines below)."""
    return max([len(x) for x in fit[2]] or [0]) + len(getattr(fit, "full", ()) or ())


def p3f_foot_h(fit):
    """2.114.5 (#2300): the height the footer needs (rule to the page bottom margin): three lines take less than the old
    fixed 20 mm, so the body gets the rest. 2.296.0 A (#3164): from the real line count, no cap (nothing is cut)."""
    return max(12 * MM, p3f_lines(fit) * fit[0] * 1.39 + 5)


def pdf_body_bottom(foot_h):
    """2.296.0 A (#3164): where the body ends above a footer of height foot_h (p3f_foot_h)."""
    return A4_H - 12 * MM - foot_h


def pdf_draw_footer(p, cols, right="", fit=None, foot_h=None, x0=None, width=None):
    """2.114.4 A (#2271): the footer of a page: a rule, the columns of pdf_footer_cols (laid out by p3f_fit) and the text
    bottom right (number / page). 2.114.5 (#2300): foot_h = the reserved height (office_pdf passes p3f_foot_h).
    2.296.0 A (#3164): every line is drawn (no cut), the full-width lines below the columns; x0 / width = a letterhead's
    margins (default PDF_L / PDF_CW). Shared by the office PDFs, the templates, the letters and the meal receipts."""
    x0 = PDF_L if x0 is None else x0
    width = PDF_CW if width is None else width
    fit = fit or (p3f_fit(cols, width) if cols else None)
    top = pdf_body_bottom(foot_h if foot_h is not None else p3f_foot_h(fit) if fit else PDF_FOOT_H)
    p.line(x0, top, x0 + width, top, 0.5, C_RULE)
    if cols:
        fs, cws, shown = fit
        x, yy = x0, top + 5
        for i, c in enumerate(shown):
            if i:
                x += cws[i - 1] + 8
            yy = top + 5
            for ln, first in c:  # 2.138.2 B (#2397): first = a name line (p3f_fit marks them)
                p.text(x, yy, ln, fs, bold=(i == 0 and first), color=C_INK if (i == 0 and first) else C_INK2)
                yy += fs * 1.39
        yy = top + 5 + max([len(c) for c in shown] or [0]) * fs * 1.39
        for ln in getattr(fit, "full", ()) or ():
            p.text(x0, yy, ln, fs, color=C_INK2)
            yy += fs * 1.39
    if right:
        p.text(x0 + width, A4_H - 9 * MM, right, 6.8, False, C_INK2, align="r")


def pdf_sender_line(sender, name="", name1="", width=PDF_ADDR_W, size=7):
    """2.296.0 E (#3170): the sender line above the address field fitted to width; the address has priority over the company
    name: a long name gives way first (its first line name1; then only street and town; then the name shortened with "…"),
    trailing parts only after that."""
    s = str(sender or "")
    if pdf_text_width(s, size) <= width:
        return s
    nm = str(name or "")
    if nm and s.startswith(nm + " · "):
        rest = s[len(nm):]
        short = str(name1 or "").strip() or nm
        if pdf_text_width(short + rest, size) <= width:
            return short + rest
        parts = rest.split(" · ")[1:]
        if len(parts) > 2 and pdf_text_width(short + " · " + parts[0] + " · " + parts[-1], size) <= width:
            return short + " · " + parts[0] + " · " + parts[-1]  # the street and the town before the lines between them
        while len(short) > 8 and pdf_text_width(short.rstrip() + "…" + rest, size) > width:
            short = short[:-1]
        if pdf_text_width(short.rstrip() + "…" + rest, size) <= width:
            return short.rstrip() + "…" + rest
    while pdf_text_width(s, size) > width and " · " in s:  # still too long: drop trailing parts
        s = s.rsplit(" · ", 1)[0]
    if pdf_text_width(s, size) > width:  # one part alone too long: shortened
        while len(s) > 1 and pdf_text_width(s + "…", size) > width:
            s = s[:-1]
        s = s.rstrip() + "…"
    return s


def office_pdf(model, logo_bytes=None, xml=None, meta=None):
    """The document PDF (bytes, PDF/A-3b) from the print model of office.docs:
    {kind, lang, currency, number, date, valid_until, title, project_title, project_ref, client (name, optional),
     company {name, lines[], contact_lines[], register_lines[], bank_lines[], logo_path, color}, recipient {name, lines[]},
     intro, lines [{kind: heading|item|text|producing|raw|discount, ...}], totals {net, tax_lines[{pct, base, amount}],
     gross, net_incl_raw, net_excl_raw, vat_note}, rights {title, rows[[label, text]], note}, closing, signature,
     fields [{name, value}], labels {...}, formats {...}}.
    logo_bytes: the logo file (else company.logo_path is read). xml / meta (2.38.0): the e-invoice XML to embed and the
    writer's metadata, see pdf_write. model["draft_mark"]: a word printed as a light diagonal mark on every page (drafts)."""
    m = model or {}
    if pdf_paper(m.get("paper")) != PAPER:  # 2.357.0 A (#3156): US-Letter: the same layout with the sizes of the paper
        return pdf_paper_ns(m.get("paper")).office_pdf(model, logo_bytes, xml, meta)
    if BP is None and isinstance(m.get("letterhead"), dict):  # 2.120.0 E (#2091): own letterhead: the same layout with its margins
        return bp_layout(m["letterhead"], model, logo_bytes, xml, meta)
    if (m.get("kind") or "offer") in PDF_LOOK_A_KINDS and not PDF_LOOK_A.get():  # 2.406.0 (#3491): a quotation in look A; 2.434.0 A (#3603): + invoices
        tok = PDF_LOOK_A.set(True)
        try:
            return office_pdf(model, logo_bytes, xml, meta)
        finally:
            PDF_LOOK_A.reset(tok)
    look_a = PDF_LOOK_A.get()
    lang = pdf_lang(m.get("lang"))  # 2.185.0 C (#2520): every app language
    L = {k: tr(v, lg=lang) for k, v in PDF_LABELS.items()}
    ml = m.get("labels") or {}
    for mine, theirs in (("number", "offer_no"), ("service", "title"), ("rate", "unit_price"), ("net", "net_total"),
                         ("gross", "gross_total"), ("accept", "order"), ("page", "page_of")):
        if isinstance(ml.get(theirs), str) and ml[theirs]:
            L[mine] = ml[theirs].replace("{x}", "{0}").replace("{y}", "{1}")
    L.update({k: v for k, v in ml.items() if k in L and isinstance(v, str) and v and k not in ("title", "page")})
    fmt = m.get("formats") or {}
    cur = m.get("currency") or "EUR"
    co = m.get("company") or {}
    # 2.99.0 D (#2188): the company name's lines (up to three) for the letterhead and the footer; "name" is the one-line form
    co_lines = [str(x).strip() for x in (co.get("name_lines") or str(co.get("name") or "").split("\n")) if str(x).strip()][:3]
    rc = m.get("recipient") or {}
    accent = co.get("color") or "#2f5d8a"
    number = str(m.get("number") or "")
    title = str(m.get("title") or L["title"])
    money = lambda v: pdf_money(v, lang, cur, fmt)  # noqa: E731
    images = {}
    logo = None
    if logo_bytes is None and co.get("logo_path"):
        try:
            with open(co["logo_path"], "rb") as fh:
                logo_bytes = fh.read(16 * 1024 * 1024)
        except OSError:
            logo_bytes = None
    if logo_bytes:
        logo = pdf_image_object(logo_bytes)
        if logo:
            images["Logo"] = logo

    def logo_box(max_w, max_h):
        return pdf_logo_fit(logo, max_w, max_h)  # 2.357.0 B (#3179): at most PDF_LOGO_DPI

    # -- letterhead (page 1) and the small head (following pages)
    def draw_letterhead(p):
        if BP and BP["hide_head"]:  # 2.120.0 E (#2091): logo, name and fold marks come with the letterhead
            return
        if logo:
            fw, fh, left = pdf_logo_frame(co)  # 2.406.0 (#3501): size and side from the office settings
            w, h = logo_box(fw, fh)
            p.image("Logo", PDF_L if left else A4_W - PDF_R - w, PDF_TOP + 2 * MM, w, h)
        else:
            nl = co_lines or [""]  # 2.99.0 D (#2188): up to three name lines, one under the other
            for i, ln in enumerate(nl):
                p.text(PDF_L + PDF_CW, PDF_TOP + 4 * MM + i * 18, ln, 15, True, C_INK, align="r", spacing=1.2)
            p.rect(A4_W - PDF_R - 12 * MM, PDF_TOP + 4 * MM + 24 + (len(nl) - 1) * 18, 12 * MM, 2.2, accent)
        for y in PDF_MARKS:  # fold and punch marks (DIN 5008 form B; 2.357.0 A (#3156): of the paper size)
            p.line(5 * MM, y, 9 * MM, y, 0.4, C_RULE)

    def draw_small_head(p):
        y = 12 * MM if not BP else max(4 * MM, PDF_NEXT_TOP - 18 * MM)  # 2.120.0 E (#2091): above the body of the letterhead
        rw = 0  # 2.217.0 B (#2800): the width taken by the logo / company name on the right
        if BP and BP["hide_head"]:
            pass
        elif logo:
            w, h = logo_box(32 * MM, 11 * MM)
            p.image("Logo", A4_W - PDF_R - w, y, w, h)
            rw = w
        else:
            p.text(PDF_L + PDF_CW, y, co.get("name") or "", 9, True, C_INK, align="r", spacing=0.6)
            rw = pdf_text_width(co.get("name") or "", 9, True, 0.6)
        # 2.217.0 B (#2800): title · recipient wraps left of the logo / name (at most two lines, the rest cut with "…")
        sw = PDF_CW - rw - (6 * MM if rw else 0)
        sl = pdf_wrap(f"{title} {number}".strip() + (" · " + rc["name"] if rc.get("name") else ""), 8, sw)
        if len(sl) > 2:
            t2 = sl[1]
            while t2 and pdf_text_width(t2 + "…", 8) > sw:
                t2 = t2[:-1]
            sl = [sl[0], t2.rstrip() + "…"]
        for i, ln in enumerate(sl):
            p.text(PDF_L, y + 2 + i * 10, ln, 8, False, C_INK2)
        ry = 24.5 * MM if not BP else y + 12.5 * MM
        p.line(PDF_L, ry, PDF_L + PDF_CW, ry, 0.5, accent)

    # -- footer (every page), four columns; empty ones are left out (2.114.4 A (#2271): shared with the document templates)
    cols = pdf_footer_cols(co)
    p3f = p3f_fit(cols)  # 2.114.5 (#2300): laid out once; a three-line footer leaves the body more room
    foot_h = p3f_foot_h(p3f)
    body_bottom = A4_H - 12 * MM - foot_h

    def draw_footer(p, n, total):
        # 2.114.4 A (#2282): the page count only from two pages on, the number stays
        right = " · ".join(x for x in (number, L["page"].format(n, total) if total >= 2 else "") if x)
        if BP and BP["hide_footer"]:  # 2.120.0 E (#2091): the letterhead has its own footer; number + page under the body
            return p.text(PDF_L + PDF_CW, BP["bottom"][n > 1] + 3 * MM, right, 6.8, False, C_INK2, align="r")
        pdf_draw_footer(p, cols, right, p3f, foot_h)

    # -- blocks: (height, draw(page, y), keep_next, keep_prev, table)
    blocks = []

    # 2.138.0 E (#2238): tail = part of the closing (totals .. order confirmation) that stays with the block before it as long as the
    # whole closing fits on one page; sq = points of its top gap that may be given up so that a group still fits on the page
    # 2.294.0 (#3154): air = (top, bottom, min_top) extra points around a block (totals, intro) that the layout gives up first --
    # down to min_top before the old gaps (sq), below it only so that the page count never grows
    # 2.434.0 A (#3603): foot = the block (with what follows it up to the next page break) sits at the bottom of its page
    def block(h, fn, keep_next=False, keep_prev=False, table=False, brk=False, tail=False, sq=0, air=None, air_kind="", pk=False, foot=False):  # 2.47.0 (#1215): brk = starts a new page
        at, ab, am = air or (0.0, 0.0, 0.0)
        blocks.append({"h": h + at + ab, "draw": fn, "keep_next": keep_next, "keep_prev": keep_prev, "table": table, "brk": brk, "tail": tail, "sq": sq,
                       "sq_used": 0.0, "air": at + ab, "air_top": at, "air_min": am, "air_cut": 0.0, "air_kind": air_kind, "pk": pk, "foot": foot})

    # 2.296.0 E (#3166): a paragraph as one block per line, so that one longer than the room of a page breaks between its lines
    # instead of running over the footer; its first two and last two lines stay together (no single line at a page end / start),
    # soft: the whole paragraph stays together as long as it fits on an empty page. step = line height (a number or one per row);
    # top / bottom = the paragraph's gaps; draw1(page, y, row, q) draws row q at y (the top of its line)
    def para_blocks(rows, step, top, bottom, draw1, keep_next=False, soft=True, sq=0, air=None, air_kind="", **kw):
        n = len(rows)
        for q, r in enumerate(rows):
            st = step[q] if isinstance(step, (list, tuple)) else step
            off = top if q == 0 else 0
            block(off + st + (bottom if q == n - 1 else 0), lambda p, y, r=r, q=q, off=off: draw1(p, y + off, r, q),
                  keep_next=keep_next if q == n - 1 else q in (0, n - 2), pk=soft and q < n - 1, sq=sq if q == 0 else 0,
                  air=air if q == n - 1 else None, air_kind=air_kind if q == n - 1 else "", **kw)

    body = 9.6
    lh = pdf_fs(body) * 1.42  # 2.406.0 (#3491): the line height of the printed size

    # -- page 1 head: address field left, key data right
    info = [(str(r[0]), str(r[1])) for r in (m.get("meta") or []) if isinstance(r, (list, tuple)) and len(r) >= 2 and str(r[1]).strip()]
    if not info:
        if number:
            info.append((L["number"], number))
        if m.get("date"):
            info.append((L["date"], m.get("date_text") or pdf_date(m["date"], lang, fmt)))
        if m.get("valid_until"):
            info.append((L["valid_until"], m.get("valid_until_text") or pdf_date(m["valid_until"], lang, fmt)))
        if m.get("client") and str(m["client"]).strip() and not str(rc.get("name") or "").strip():  # 2.114.4 A (#2277): only without a recipient name
            info.append((L["client"], str(m["client"])))
        if m.get("project_ref"):
            info.append((L["ref"], str(m["project_ref"])))
    # 2.144.9 (#2575): the number's label of this document (the head row that carries the number: "Rechnung Nr." on an
    # invoice) for the part pages and the rights appendix -- not the quotation's label; own fields do not count
    num_l = next((k for k, v in info if number and v == number), L["number"])
    for f in m.get("fields") or []:
        if isinstance(f, dict) and str(f.get("name") or "").strip():
            info.append((str(f["name"]), str(f.get("value") or "")))
    info_x = PDF_INFO_X  # 2.390.0 A (#3350): 125 mm from the sheet edge (was 118 mm); runs to the right margin
    info_w = PDF_L + PDF_CW - PDF_INFO_X
    info_lh = pdf_fs(8.6) * 1.45  # 2.406.0 (#3491)
    addr_lines = [str(x) for x in (rc.get("lines") or []) if str(x).strip()]
    if rc.get("name") and (not addr_lines or addr_lines[0].strip() != str(rc["name"]).strip()):
        addr_lines.insert(0, str(rc["name"]))
    if rc.get("street") and not any(str(rc["street"]).strip() in ln for ln in addr_lines):  # 2.38.0: billing fields without free lines
        addr_lines += [str(x) for x in (rc["street"], " ".join(str(y) for y in (rc.get("zip"), rc.get("city")) if y)) if str(x).strip()]
        if rc.get("country") and str(rc["country"]).strip().upper() != str((m.get("sender_fields") or {}).get("country") or "DE").upper():
            addr_lines.append(str(rc["country"]))
    # 2.217.0 B (#2800): every address line (a long recipient name above all) wraps within the address field instead of
    # running into the key data on the right; the head grows with the wrapped lines (nothing is cut)
    addr_lines = [w for ln in addr_lines for w in pdf_wrap(ln, body, PDF_ADDR_W)]  # 2.296.0 E (#3170): every line (was cut after 8)

    def draw_head(p, y):
        sender = str(co.get("sender_line") or "") or " · ".join(dict.fromkeys(str(x) for x in [co.get("name") or ""] + list(co.get("lines") or []) if str(x).strip()))
        sender = pdf_sender_line(sender, co.get("name"), co_lines[0] if len(co_lines) > 1 else "")  # 2.296.0 E (#3170): the address first
        p.text(PDF_L, y, sender, 7, False, C_INK2)
        p.line(PDF_L, y + 11, PDF_L + PDF_ADDR_W, y + 11, 0.5, C_RULE2)
        yy = y + 16
        for ln in addr_lines:
            p.text(PDF_L, yy, ln, body)
            yy += lh
        yy = y + 2
        for kl, vl, below in info_rows:
            for j, kk in enumerate(kl):
                p.text(info_x, yy + j * info_lh, kk, 8.6, False, C_INK2)
            if below:
                yy += len(kl) * info_lh
            for j, vv in enumerate(vl):
                p.text(info_x, yy + j * info_lh, vv, 8.6, True, C_INK, align="r", width=info_w)
            yy += (len(vl) if below else max(len(kl), len(vl))) * info_lh

    # 2.296.0 E (#3170): a long label wraps (at most ~half the width), the value below it when too little room is left beside it
    # (was: the label never wrapped and ran under the value / over the margin)
    info_rows = []
    for k, v in info:
        kl = pdf_wrap(k, 8.6, info_w * 0.55) if pdf_text_width(k, 8.6) > info_w * 0.55 else [k]
        vw = info_w - max(pdf_text_width(x, 8.6) for x in kl) - 10
        # 2.357.0 B (#3180): also a value that would need more than two lines beside its label goes below it (a long order
        # reference was four right-aligned lines); wrapped bold as it is drawn (was measured regular)
        below = (vw < 60 or len(pdf_wrap(v, 8.6, max(vw, 40), True)) > 2) and pdf_text_width(v, 8.6, True) > vw
        info_rows.append((kl, pdf_wrap(v, 8.6, info_w if below else max(vw, 40), True), below))
    head_h = max(PDF_ADDR_H, 16 + len(addr_lines) * lh + 4,
                 2 + sum(len(kl) + len(vl) if below else max(1, len(kl), len(vl)) for kl, vl, below in info_rows) * info_lh + 4)
    block(head_h, draw_head)

    # -- title line, project title, intro

    # 2.138.0 A (#2240): a long title wraps over the full width (the page count sits in the footer); the accent line under its last line
    t_lines = pb_wrap(title.upper(), 16, PDF_CW, True, 1.0)

    def draw_title(p, y):
        for j, s in enumerate(t_lines):
            p.text(PDF_L, y + 6 + j * t_step, s, 16, True, C_INK, spacing=1.0)
        ly = y + 6 + (len(t_lines) - 1) * t_step + (19 if look_a else 22)
        p.line(PDF_L, ly, PDF_L + 14 * MM, ly, 1.6, accent)
    t_step = 18 if look_a else 20  # 2.406.0 (#3491): look A a little tighter
    block((30 if look_a else 34) + (len(t_lines) - 1) * t_step, draw_title, keep_next=True)
    if m.get("project_title"):
        pt = str(m["project_title"])
        n = len(pdf_wrap(pt, 10.4, PDF_CW, True))
        block(n * 10.4 * 1.42 + 8, lambda p, y, t=pt: p.para(PDF_L, y + 2, t, 10.4, PDF_CW, True), keep_next=True)
    if m.get("intro"):
        it = str(m["intro"])
        # 2.294.0 (#3154): the same air between the intro and the table as before the totals (today lh + 8 + 4 - body = ~5.7 mm
        # from the last line to the table head; never less than that, the wish only while it costs no page)
        # 2.296.0 E (#3166): line by line (a long intro breaks; the title keeps its first two lines, page 1 never stays empty)
        para_blocks(pdf_wrap(it, body, PDF_CW), lh, 0, 8, lambda p, y, s_, q: p.text(PDF_L, y, s_, body), keep_next=True, soft=False,
                    air=(0.0, max(0.0, PDF_SUM_GAP - (lh + 12 - body)), 0.0), air_kind="intro")

    # -- the table: columns Pos. | Service | Qty | Unit price | VAT | Total
    c_pos, c_qty, c_rate, c_vat, c_tot = 22, 64, 70, 56, 76  # 2.380.0 A (#3415): c_vat was 36 (the price and VAT columns almost touched)
    np_ = bool(m.get("noprice"))  # 2.120.0 D (#2089): delivery note / timesheet: no price, VAT or total columns
    if np_:
        c_pos, c_rate, c_vat, c_tot = int(m.get("pos_w") or 22), 0, 0, 0

    def qty_two(ln):  # 2.296.0 E (#3170): (number, unit) of a row's quantity
        unit = str(ln.get("unit_text") or ln.get("unit") or "")
        if "unit_text" in ln and not ln.get("unit_text") and str(ln.get("unit") or "") in ("flat", "day", "hour", "piece", "minute"):
            unit = str((ml.get("units") or {}).get(ln["unit"]) or "") if isinstance(ml.get("units"), dict) else ""  # 2.296.0 B (#3173): never the key "flat"
        if "qty_text" in ln:
            q = str(ln.get("qty_text") or "")
            return (q, unit if q else "")
        return (pdf_num(ln["qty"], lang, fmt), unit) if ln.get("qty") not in (None, "") else ("", "")
    # 2.296.0 E (#3170): the quantity column as wide as its widest entry (up to P3Q_MAX; wider ones put the unit on a second line),
    # the position column as wide as its widest entry (a timesheet's dates); was a fixed width the text ran over
    p3q_rows = [x for x in list(m.get("lines") or []) + [y for pt in (m.get("parts") or []) if isinstance(pt, dict) for y in (pt.get("lines") or [])]
                if isinstance(x, dict) and (x.get("kind") or "item") in ("item", "producing", "surcharge", "raw", "discount")]
    p3q_w = [pdf_text_width(" ".join(x for x in qty_two(x) if x).strip(), 8.8) for x in p3q_rows]
    c_qty = max(c_qty, min(P3Q_MAX, max(p3q_w or [0]) + 6))
    c_pos = max(c_pos, max([pdf_text_width(str(x.get("pos") or ""), 8) + 6 for x in p3q_rows] or [0]))
    # 2.114.5 (#2300): a quotation whose positions (parts too) all carry the same rate prints no VAT column
    p3v = {pdf_num(x.get("tax_pct"), "en") for x in list(m.get("lines") or []) + [y for pt in (m.get("parts") or []) if isinstance(pt, dict) for y in (pt.get("lines") or [])]
           if isinstance(x, dict) and (x.get("kind") or "item") in ("item", "producing", "raw", "discount") and x.get("tax_pct") not in (None, "")}
    # 2.357.0 B (#3181): every document (was quotations only): one rate, also 0 % of section 19 / reverse charge, sits in the totals
    # (review N4: the rates compared as numbers, so "19" and "19.0" are one)
    if len(p3v) <= 1:
        c_vat = 0
    c_title = PDF_CW - c_pos - c_qty - c_rate - c_vat - c_tot
    x_pos = PDF_L
    x_title = x_pos + c_pos
    x_qty = x_title + c_title
    x_rate = x_qty + c_qty
    x_vat = x_rate + c_rate
    x_tot = x_vat + c_vat
    thead_h = 17 if look_a else 20  # 2.406.0 (#3491)

    def draw_thead(p, y):
        yy = y + 4
        p.text(x_pos + 3, yy, L["pos"].upper(), 7.4, True, C_INK2, spacing=0.6)
        p.text(x_title + 3, yy, L["service"].upper(), 7.4, True, C_INK2, spacing=0.6)
        p.text(x_qty, yy, L["qty"].upper(), 7.4, True, C_INK2, align="r", width=c_qty - 3, spacing=0.6)
        if not np_:  # 2.120.0 D (#2089): no price columns on a delivery note
            p.text(x_rate, yy, L["rate"].upper(), 7.4, True, C_INK2, align="r", width=c_rate - 3, spacing=0.6)
            if c_vat:
                p.text(x_vat, yy, L["vat"].upper(), 7.4, True, C_INK2, align="c", width=c_vat, spacing=0.6)
            p.text(x_tot, yy, L["total"].upper(), 7.4, True, C_INK2, align="r", width=c_tot - 3, spacing=0.6)
        p.line(PDF_L, y + thead_h - 1, PDF_L + PDF_CW, y + thead_h - 1, 1.1, C_INK)

    lines = [x for x in (m.get("lines") or []) if isinstance(x, dict)]
    # 2.296.0 E (#3166): the room of a following page below a table head; a row / payment text higher than that is split by lines
    p3s_cap = ((BP["bottom"][1] if BP["hide_footer"] else min(BP["bottom"][1], body_bottom)) if BP else body_bottom) - PDF_NEXT_TOP - thead_h - 8
    have_table = False
    last_item_idx = None

    def table_rows(lines):  # 2.47.0 (#1215): the rows of the title page and of every printed part
        nonlocal have_table, last_item_idx
        for i, ln in enumerate(lines):
            k = ln.get("kind") or "item"
            if k == "heading":
                t = str(ln.get("title") or "")
                hl = pb_wrap(t.upper(), 8, c_title + c_qty + c_rate + c_vat + c_tot - 6, True, 0.8)  # 2.296.0 E (#3170): a long heading wraps
                block(22 + (len(hl) - 1) * 11, lambda p, y, hl=hl: [p.text(x_title + 3, y + 11 + j * 11, t_, 8, True, pdf_text_color(accent), spacing=0.8)
                                                               for j, t_ in enumerate(hl)], keep_next=True, table=True)  # 2.296.0 D (#3172): readable text colour
                have_table = True
            elif k == "text":
                tw = c_title + c_qty + c_rate + c_vat + c_tot - 6
                wrapped = pdf_wrap(str(ln.get("text") or ""), body, tw)
                # 2.296.0 E (#3166): line by line (was 40 lines a block: too long for a letterhead with wide margins)
                para_blocks(wrapped, lh, 4, 6, lambda p, y, s_, q: p.text(x_title + 3, y, s_, body), table=True)
            elif k in ("item", "producing", "surcharge", "raw", "discount"):  # 2.113.1 (#2252): + surcharge
                if k == "raw" and ln.get("optional"):
                    continue  # the option is printed below the totals
                t = str(ln.get("title") or (L["producing"] if k == "producing" else L["discount"] if k == "discount" else ""))
                if k == "discount" and ln.get("pct") not in (None, "", 0):
                    t = f"{t} {pdf_num(ln['pct'], lang, fmt)} %"
                detail = str(ln.get("detail") or "") if k != "producing" else ""  # 2.114.4 A (#2276): the formula only in the app
                qty_s = " ".join(x for x in qty_two(ln) if x).strip()
                # 2.296.0 E (#3170): too wide for the column: number and unit on two lines (each wrapped to the column)
                q_lines = [qty_s] if pdf_text_width(qty_s, 8.8) <= c_qty - 6 else [w for x in qty_two(ln) if x for w in pdf_wrap(x, 8.8, c_qty - 6)]
                rate_s = str(ln.get("rate_text") or "") if "rate_text" in ln else (pdf_money(ln["rate"], lang, cur, fmt, pdf_rate_places(ln["rate"])) if ln.get("rate") not in (None, "") else "")  # 2.354.0 A (#2831)
                vat_s = (pdf_num(ln["tax_pct"], lang, fmt) + " %") if ln.get("tax_pct") not in (None, "") and c_vat else ""
                tot_s = str(ln.get("total_text") or "") if ln.get("total_text") else money(ln.get("total") or 0)
                if np_:
                    rate_s = vat_s = tot_s = ""
                pos_s = str(ln.get("pos") or "") if k in ("item", "producing", "surcharge") else ""  # 2.114.4 A (#2276): producing numbered too; surcharges like it
                t_lines = pdf_wrap(t, body, c_title - 6)
                d_lines = pdf_wrap(detail, 8.4, c_title + c_qty + c_rate + c_vat + c_tot - 6) if detail else []
                h = 8 + max(len(t_lines), len(q_lines)) * lh + (len(d_lines) * 8.4 * 1.42 + 2 if d_lines else 0)

                def draw_row(p, y, t_lines=t_lines, d_lines=d_lines, pos_s=pos_s, q_lines=q_lines, rate_s=rate_s, vat_s=vat_s, tot_s=tot_s, h=h):
                    yy = y + 4
                    p.text(x_pos + 3, yy + 1, pos_s, 8, False, C_INK2)
                    for j, s in enumerate(t_lines):
                        p.text(x_title + 3, yy + j * lh, s, body)
                    for j, s in enumerate(q_lines):
                        p.text(x_qty, yy + j * lh, s, 8.8, align="r", width=c_qty - 3)
                    p.text(x_rate, yy, rate_s, 8.8, align="r", width=c_rate - 3)
                    p.text(x_vat, yy + 1, vat_s, 8, False, C_INK2, align="c", width=c_vat)
                    p.text(x_tot, yy, tot_s, 8.8, align="r", width=c_tot - 3)
                    dy = yy + max(len(t_lines), len(q_lines)) * lh
                    for s in d_lines:
                        p.text(x_title + 3, dy, s, 8.4, False, C_INK2)
                        dy += 8.4 * 1.42
                    p.line(PDF_L, y + h - 0.5, PDF_L + PDF_CW, y + h - 0.5, 0.5, C_RULE2)
                if h > p3s_cap:  # 2.296.0 E (#3166): a row higher than a page: its title and detail lines one by one (the amounts on the first)
                    rr = [(s_, body, C_INK) for s_ in t_lines] + [("", body, C_INK)] * (len(q_lines) - len(t_lines)) + [(s_, 8.4, C_INK2) for s_ in d_lines]
                    rs = [lh] * max(len(t_lines), len(q_lines)) + [8.4 * 1.42] * len(d_lines)
                    rb = 4 + (2 if d_lines else 0)

                    def draw_row(p, y, r, q, n=len(rr), rs=rs, rb=rb, pos_s=pos_s, q_lines=q_lines, rate_s=rate_s, vat_s=vat_s, tot_s=tot_s):
                        if q == 0:
                            p.text(x_pos + 3, y + 1, pos_s, 8, False, C_INK2)
                            for j, s_ in enumerate(q_lines):
                                p.text(x_qty, y + j * lh, s_, 8.8, align="r", width=c_qty - 3)
                            p.text(x_rate, y, rate_s, 8.8, align="r", width=c_rate - 3)
                            p.text(x_vat, y + 1, vat_s, 8, False, C_INK2, align="c", width=c_vat)
                            p.text(x_tot, y, tot_s, 8.8, align="r", width=c_tot - 3)
                        p.text(x_title + 3, y, r[0], r[1], False, r[2])
                        if q == n - 1:
                            p.line(PDF_L, y + rs[q] + rb - 0.5, PDF_L + PDF_CW, y + rs[q] + rb - 0.5, 0.5, C_RULE2)
                    para_blocks(rr, rs, 4, rb, draw_row, table=True)
                else:
                    block(h, draw_row, table=True)
                have_table = True
                last_item_idx = len(blocks) - 1
    table_rows(lines)
    # 2.38.0 (#1021): a payment reminder lists the open invoices (number, date, due, open amount) instead of positions
    rem = m.get("reminder") if isinstance(m.get("reminder"), dict) else None
    if rem and isinstance(rem.get("rows"), list) and rem["rows"]:
        rcols = [str(x) for x in (rem.get("columns") or [])][:4]
        while len(rcols) < 4:
            rcols.append("")
        c_r4 = 86
        c_r1 = PDF_CW - 3 * c_r4
        xs = [PDF_L, PDF_L + c_r1, PDF_L + c_r1 + c_r4, PDF_L + c_r1 + 2 * c_r4]

        def draw_rem_head(p, y):
            for j, (x, lab) in enumerate(zip(xs, rcols)):
                p.text(x + 3, y + 4, lab.upper(), 7.4, True, C_INK2, align="l" if j == 0 else "r", width=(c_r1 if j == 0 else c_r4) - 6, spacing=0.6)
            p.line(PDF_L, y + 19, PDF_L + PDF_CW, y + 19, 1.1, C_INK)
        # 2.296.0 D (#3174): the head of the open invoices is the table head of the page layout (it comes back on every following
        # page like the position table's); only when no position table is drawn (a reminder has none)
        rem_table = not have_table
        if rem_table:
            draw_thead, have_table = draw_rem_head, True
            thead_h = 20
        else:
            block(20, draw_rem_head, keep_next=True)
        for rr in rem["rows"]:
            if not isinstance(rr, dict):
                continue
            cells = [str(rr.get("number") or ""), str(rr.get("date_text") or ""), str(rr.get("due_text") or ""), str(rr.get("open_text") or money(rr.get("open") or 0))]

            def draw_rem_row(p, y, cells=cells):
                for j, (x, v) in enumerate(zip(xs, cells)):
                    p.text(x + 3, y + 4, v, body, align="l" if j == 0 else "r", width=(c_r1 if j == 0 else c_r4) - 6)
                p.line(PDF_L, y + 8 + lh - 0.5, PDF_L + PDF_CW, y + 8 + lh - 0.5, 0.5, C_RULE2)
            block(8 + lh, draw_rem_row, table=rem_table)
        last_item_idx = len(blocks) - 1
    if not have_table:
        thead_h = 0

    # -- totals block (right column) + VAT note (left column); never alone on a page
    tot = m.get("totals") or {}
    sum_at = []  # 2.406.0 (#3491)
    raw_opt = next((x for x in lines if x.get("kind") == "raw" and x.get("optional")), None)
    raw_inc = next((x for x in lines if x.get("kind") == "raw" and not x.get("optional")), None)
    show_tax = tot.get("show_tax_lines")
    p3o = {}
    if isinstance(tot.get("rows"), list) and tot["rows"]:  # the print model brings the rows ready-made (first = net total)
        given = [r for r in tot["rows"] if isinstance(r, (list, tuple)) and len(r) >= 2]
        # 2.38.0: an invoice's rows already end with the tax lines and the grand total (show_tax_lines true) -> last row bold
        rows = [(str(r[0]), str(r[1]), i == 0 or ((bool(show_tax) or (m.get("kind") or "offer") != "offer") and len(given) > 1 and i == len(given) - 1)
                 or ("b" if len(r) > 2 and isinstance(r[2], dict) and r[2].get("b") else False))
                for i, r in enumerate(given)]
        # 2.408.0 (#3520): a row may bring {"b": 1} (bold, like a sum) and {"detail": text} (small below, like the option's detail)
        p3o = {str(r[0]): str(r[2]["detail"]) for r in given if len(r) > 2 and isinstance(r[2], dict) and r[2].get("detail")}
        show_tax = False
    else:
        rows = [(L["net"], tot.get("net_text") or money(tot.get("net") or 0), True)]
        if raw_inc and tot.get("net_excl_raw") not in (None, ""):
            rows.append((L["excl_raw"], tot.get("net_excl_raw_text") or money(tot["net_excl_raw"]), False))
        if show_tax is None:
            show_tax = bool(tot.get("tax_lines"))
    if show_tax:
        for tl in tot.get("tax_lines") or []:
            if not isinstance(tl, dict):
                continue
            lab = tl.get("label") or L["vat_plus"].format(pdf_num(tl.get("pct"), lang, fmt))
            rows.append((str(lab), money(tl.get("amount") or 0), False))
        if tot.get("gross") not in (None, ""):
            rows.append((L["gross"], money(tot.get("gross")), True))
    # 2.114.5 (#2300): the option as three rows of the totals (net, + option, net with option) instead of the dashed box
    if raw_opt:
        inc_l = str(ml.get("incl_raw") or L["incl_raw"])
        inc_t = str(tot.get("net_incl_raw_text") or (money(tot["net_incl_raw"]) if tot.get("net_incl_raw") not in (None, "") else ""))
        rows = [r for r in rows if not (inc_t and (r[0] == inc_l or r[1] == inc_t))]
        ot = str(raw_opt.get("title") or "").strip()
        o_l = "+ " + (ot if ot.lower().startswith(L["optional"].lower()) else L["optional"] + (": " + ot if ot else ""))
        rows[1:1] = [(o_l, str(raw_opt.get("total_text") or "") or money(raw_opt.get("total") or 0), False)] + ([(inc_l, inc_t, "b")] if inc_t else [])
        if raw_opt.get("detail"):
            p3o[o_l] = str(raw_opt["detail"])
    # 2.114.5 (#2300): no "valid until" sentence below the table when the head names the date
    notes = [str(x) for x in (tot.get("vat_note"), m.get("vat_note_text"), tot.get("exempt_note"), tot.get("fx_line") or m.get("fx_note"),  # 2.296.0 B (#3169): + exempt_note
                              m.get("valid_note") if not m.get("valid_until") else None) if x and str(x).strip()]
    notes = list(dict.fromkeys(notes))
    note = "\n".join(notes)
    tot_w = 230 if raw_opt or m.get("abs_prepaid") else 190  # 2.114.5 (#2300): room for the option's name; 2.408.0 (#3520): the progress invoices
    left_w = PDF_CW - tot_w - 20
    note_lines = pdf_wrap(note, 8.4, left_w) if note else []
    # 2.114.5 (#2300): a long label (the option's name) wraps beside its amount, the option's detail small below it
    p3w = {lab: (pdf_wrap(lab, 9, tot_w - pdf_text_width(val, 8.8) - 10), pdf_wrap(p3o[lab], 7.8, tot_w - 10) if lab in p3o else [])
           for lab, val, g in rows if g is not True}
    tot_h = 10 + sum(pdf_fs(10.4) * 1.5 + 5 + 1 if g is True else len(p3w[lab][0]) * pdf_fs(9) * 1.5 + len(p3w[lab][1]) * pdf_fs(7.8) * 1.4 for lab, _, g in rows)
    sum_h = max(tot_h, len(note_lines) * pdf_fs(8.4) * 1.42 + 10)

    def draw_sum(p, y):
        yy = y + 8
        for lab, val, grand in rows:
            if grand is True:
                p.line(PDF_L + PDF_CW - tot_w, yy, PDF_L + PDF_CW, yy, 1.1, C_INK)
                yy += 5
                p.text(PDF_L + PDF_CW - tot_w, yy, lab, 10.4, True)
                p.text(PDF_L + PDF_CW - tot_w, yy, val, 10.4, True, align="r", width=tot_w)
                yy += pdf_fs(10.4) * 1.5
            else:
                p.text(PDF_L + PDF_CW - tot_w, yy, val, 8.8, bool(grand), align="r", width=tot_w)
                for s_ in p3w[lab][0]:
                    p.text(PDF_L + PDF_CW - tot_w, yy, s_, 9, bool(grand))
                    yy += pdf_fs(9) * 1.5
                for s_ in p3w[lab][1]:
                    p.text(PDF_L + PDF_CW - tot_w, yy - 2, s_, 7.8, False, C_INK2)
                    yy += pdf_fs(7.8) * 1.4
        ny = y + 8
        for s in note_lines:
            p.text(PDF_L, ny, s, 8.4, False, C_INK2)
            ny += pdf_fs(8.4) * 1.42
    if not (np_ and not (isinstance(tot.get("rows"), list) and tot["rows"])):  # 2.120.0 D (#2089): a delivery note has no totals
        # 2.294.0 (#3154): air between table and totals (wish ~11 mm, at least ~4 mm visible; 8 pt are in draw_sum) and a little below
        sum_air = (PDF_SUM_GAP - 8, PDF_SUM_AFTER, PDF_SUM_GAP_MIN - 8) if last_item_idx is not None else None
        if look_a:
            sum_at.append(len(blocks))  # 2.406.0 (#3491): the totals block, see PDF_SUM_FILL in lay()
        block(sum_h, draw_sum, keep_prev=last_item_idx is not None, sq=4, air=sum_air, air_kind="sum")

    # -- 2.38.0 (#1021): payment information of an invoice (due text + bank line) right below the totals; 2.434.0 A (#3603): only
    # the due text stays there (full width), the bank line and the GiroCode form a block of their own at the end, above the footer
    pay = m.get("payment") if isinstance(m.get("payment"), dict) else None
    pay_end = []  # (height, draw) of the bank line + GiroCode, placed after the closing (see below)
    if pay and (pay.get("text") or pay.get("iban")):
        iban = str(pay.get("iban") or "").replace(" ", "")
        bank = " · ".join(x for x in (str(pay.get("bank_name") or ""), ("IBAN " + " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))) if iban else "",
                                     ("BIC " + str(pay["bic"])) if pay.get("bic") else "") if x)
        gcq = str(pay.get("girocode") or "")  # 2.147.1 B (#2054): the GiroCode right of the bank line (office/girocode.py)
        if gcq:  # imported only then: this module also runs on its own (no package; tests/office_einvoice_test.py)
            from .girocode import GCQ_SIZE, gcq_block_h, gcq_draw
        pt_lines = pdf_wrap(str(pay.get("text") or ""), body, PDF_CW) if pay.get("text") else []
        pb_lines = pdf_wrap(bank, 8.4, PDF_CW - GCQ_SIZE - 14 if gcq else PDF_CW) if bank else []
        pb_lh = pdf_fs(8.4) * 1.42
        if pt_lines:
            pay_h = 6 + len(pt_lines) * lh

            def draw_pay(p, y, pt_lines=pt_lines):
                yy = y + 4
                for t_ in pt_lines:
                    p.text(PDF_L, yy, t_, body)
                    yy += lh
            if pay_h > p3s_cap:  # 2.296.0 E (#3166): a payment text higher than a page line by line
                para_blocks([(t_, body, C_INK) for t_ in pt_lines], lh, 4, 2, lambda p, y, r, q: p.text(PDF_L, y, r[0], r[1], False, r[2]), tail=True)
                blocks[-len(pt_lines)]["keep_prev"] = True
            else:
                block(pay_h, draw_pay, keep_prev=True, tail=True)
        if pb_lines or gcq:
            def draw_bank(p, y, pb_lines=pb_lines):
                if gcq:
                    gcq_draw(p, PDF_L + PDF_CW - GCQ_SIZE, y + 10, gcq, lang, C_INK, C_INK2)
                yy = y + 10
                for t_ in pb_lines:
                    p.text(PDF_L, yy, t_, 8.4, False, C_INK2)
                    yy += pb_lh
            pay_end.append((10 + max(len(pb_lines) * pb_lh + 2, gcq_block_h() if gcq else 0), draw_bank))

    # -- rights block (not torn); 2.114.1 C (#2258): printed as an appendix on its own last page, see below
    bfc_rights, bfc_seen = [], []
    rights = m.get("rights") or {}
    r_rows = [(str(r[0]), str(r[1])) for r in (rights.get("rows") or []) if isinstance(r, (list, tuple)) and len(r) >= 2 and str(r[1]).strip()]
    # 2.122.4 B (#2261): exceptions / exclusive are already in rights.rows (docs.py print model), not appended again
    if r_rows or rights.get("note"):
        lab_w = 112
        r_lines = [(a, pdf_wrap(b, 10, PDF_CW - lab_w - 12)) for a, b in r_rows]  # 2.138.2 B (#2388): rows 10 pt, label = value size
        rn_lines = pdf_wrap(str(rights.get("note") or ""), 8.5, PDF_CW) if rights.get("note") else []  # 2.114.1 C (#2258): small note

        def draw_rights():  # 2.114.1 C (#2258): the title is the appendix heading, rows with more air
            # 2.296.0 E (#3166): every row line by line (was one block for all rows: ran over the footer and the page edge); the
            # appendix heading keeps only the first row's first lines
            for j, (a, b) in enumerate(r_lines):
                para_blocks(b, 10 * 1.6, 14 if j == 0 else 0, 10, lambda p, y, s_, q, a=a: (p.text(PDF_L, y, a, 10, False, C_INK2) if q == 0 else None,
                                                                                           p.text(PDF_L + lab_w, y, s_, 10)))
            if rn_lines:
                para_blocks(rn_lines, 8.5 * 1.42, 12 + (0 if r_lines else 14), 2, lambda p, y, s_, q: p.text(PDF_L, y, s_, 8.5, False, C_INK2))
        bfc_rights.append(draw_rights)

    acc = m.get("accepted") if isinstance(m.get("accepted"), dict) else None
    # 2.114.4 B (#2270): the order confirmation can be switched off; 2.114.5 (#2300): with an appendix (rights) or printed
    # parts it moves to the very end, page 1 only names the page it is on (p3a_ref, filled in after the layout)
    p3a_on = (m.get("kind") or "offer") == "offer" and not acc and bool(m.get("accept_on", 1))
    p3a_end = p3a_on and bool(bfc_rights or any(isinstance(x, dict) for x in (m.get("parts") or [])))
    p3a_ref, p3a_at = [], []
    rh_ref, rh_acc = [], []  # 2.357.0 C (#3182): the blocks of the reference lines / the order confirmation behind the appendix

    def bfc_see_ref():  # 2.114.1 C (#2258): one short line above the signature pointing to the rights appendix
        if bfc_seen:
            return
        bfc_seen.append(1)
        ref = [str(ml.get("rights_see") or L["rights_see"])] if bfc_rights else []
        if p3a_end:  # 2.114.5 (#2300): + "Order confirmation by signature on page n"
            ref.append(str(ml.get("accept_see") or L["accept_see"]))
        if ref:
            def draw_ref(p, y, ref=ref):
                for q, t in enumerate(ref):
                    if "{0}" in t:
                        p3a_ref.append((p, len(p.ops), y + 8 + q * 8.6 * 1.45, t))  # filled in at this place of the stream
                    else:
                        p.text(PDF_L, y + 8 + q * 8.6 * 1.45, t, 8.6, False, C_INK2)
            rh_ref.append(len(blocks))  # 2.357.0 C (#3182): left out when the appendix stays on the page
            block(len(ref) * 8.6 * 1.45 + 8, draw_ref, keep_next=True, tail=True)


    # 2.406.0 (#3491): the closing of a quotation in look A, two columns; other documents keep the old closing
    q3_ref = ([str(ml.get("rights_see") or L["rights_see"])] if bfc_rights else []) + ([str(ml.get("accept_see") or L["accept_see"])] if p3a_end else [])
    q3_ct = str(m.get("closing") or "")
    q3_sg = str(m.get("signature") or "")
    q3_names = [str(x) for x in [m.get("signature_name")] + (co_lines if len(co_lines) > 1 else [co.get("name")]) if x]
    q3_tl = str(m.get("terms_line") or "")

    def q3_line(p, x, y, t, size, color=C_INK2, align="l", width=None):  # a reference line; "{0}" = the page, filled in after the layout
        if "{0}" in t:
            p3a_ref.append((p, len(p.ops), y, t, x, size, align, width))
        else:
            p.text(x, y, t, size, False, color, align=align, width=width)
    q3_on = look_a and not m.get("signature_image")
    q3_alt = []  # (block index, height, draw) of the closing without the reference lines

    if q3_on:
        bfc_seen.append(1)
        q3_lw = PDF_CW * 0.58  # left: thanks, references, terms; right from 64 %: greeting and company
        q3_rx = PDF_L + PDF_CW * 0.64
        q3_rw = PDF_CW - (q3_rx - PDF_L)
        q3_cl = pdf_wrap(q3_ct, body, q3_lw) if q3_ct else []
        q3_slh = pdf_fs(8.6) * 1.45
        q3_sgl = pdf_wrap(q3_sg, body, q3_rw) if q3_sg else []
        q3_nl = [(t, i == 0) for i, n in enumerate(q3_names) for t in pdf_wrap(n, body, q3_rw, i == 0)]

        def q3_small(refs):  # the small grey lines, each wrapped ("{0}" lines are short and filled in after the layout)
            return [ln for t in refs + ([q3_tl] if q3_tl else []) for ln in ([t] if "{0}" in t else pdf_wrap(t, 8.6, q3_lw))]

        def q3_block(refs):
            sm = q3_small(refs)
            left = len(q3_cl) * lh + ((4 if q3_cl else 0) + len(sm) * q3_slh if sm else 0)
            right = (len(q3_sgl) * lh + 4 if q3_sgl else 0) + len(q3_nl) * lh

            def draw_q3(p, y):
                p.line(PDF_L, y + 4, PDF_L + PDF_CW, y + 4, 0.5, C_RULE2)
                yy = y + 12
                for t in q3_cl:
                    p.text(PDF_L, yy, t, body)
                    yy += lh
                yy += 4 if q3_cl else 0
                for t in sm:  # small and grey, one under the other
                    q3_line(p, PDF_L, yy, t, 8.6)
                    yy += q3_slh
                yy = y + 12
                for t in q3_sgl:
                    p.text(q3_rx, yy, t, body)
                    yy += lh
                yy += 4 if q3_sgl else 0
                for t, bold in q3_nl:
                    p.text(q3_rx, yy, t, body, bold=bold)
                    yy += lh
            return 14 + max(left, right) + 10, draw_q3
        # the reference lines ("rights see appendix", "order confirmation on page n") fall away when the appendix comes onto
        # this page (rh_at below): the block without them is swapped in there
        q3_alt.append((len(blocks),) + q3_block([]))
        block(*q3_block(q3_ref), keep_prev=True, tail=True)
    else:
        # -- closing text, signature, order confirmation; 2.114.5 (#2300): the greeting set closer
        if m.get("closing"):
            ct = str(m["closing"])
            # 2.296.0 E (#3166): line by line; as part of the closing (tail) it still stays whole while the closing fits a page
            para_blocks(pdf_wrap(ct, body, PDF_CW), lh, 8, 2, lambda p, y, s_, q: p.text(PDF_L, y, s_, body), keep_next=bool(m.get("signature")),
                        tail=True, sq=4)
        if m.get("signature") or (m.get("kind") or "offer") == "offer":
            bfc_see_ref()
        if m.get("signature"):
            sg = str(m["signature"])
            # 2.296.0 E (#3170): every line of a company name of several lines one under the other (was printed as one line)
            sl = [sg] + [str(x) for x in [m.get("signature_name")] + (co_lines if len(co_lines) > 1 else [co.get("name")]) if x]
            # 2.357.0 C (#3158): the own signature picture (model["signature_image"], base64; set by office.letters lt_doc_sig only for
            # the person who finalised the document) between the greeting and the name; 2.357.0 C (#3182): a quotation without one
            # keeps 2.5 lines of air for a signature by hand (was 0.6)
            sig = None
            if m.get("signature_image"):
                import base64
                try:
                    sig = pdf_image_object(base64.b64decode(str(m["signature_image"])))
                except ValueError:
                    sig = None
            sg_w = sg_h = 0.0
            if sig:
                images["Sig"] = sig
                sg_h = 16 * MM
                sg_w = min(60 * MM, sig[0] * sg_h / sig[1])
                sg_h = sg_w * sig[1] / sig[0]
                sg_gap = sg_h + 8
            else:
                sg_gap = 2.5 * lh if (m.get("kind") or "offer") == "offer" else 0.6 * lh

            def draw_sig(p, y, sl=sl, sg_gap=sg_gap, sig=sig, sg_w=sg_w, sg_h=sg_h):
                for i, s in enumerate(sl):
                    p.text(PDF_L, y + 8 + i * lh + (sg_gap if i else 0), s, body, bold=(i == 1))
                if sig:
                    p.image("Sig", PDF_L, y + 8 + lh + 2, sg_w, sg_h)
            block((len(sl) - 1) * lh + sg_gap + lh + 10, draw_sig, tail=True, sq=4)
        if m.get("terms_line"):  # 2.113.2 (#2253): "our terms apply (as of ...), see attachment"
            tl = str(m["terms_line"])
            block(len(pdf_wrap(tl, body, PDF_CW)) * lh + 10, lambda p, y, t=tl: p.para(PDF_L, y + 10, t, body, PDF_CW))
    if (m.get("kind") or "offer") == "offer" and acc:  # 2.99.0 C (#2195): accepted online -> the signature box instead of the empty lines
        acc_rows = [(str(x[0]), str(x[1])) for x in acc.get("rows") or [] if isinstance(x, (list, tuple)) and len(x) >= 2]
        block(8 + qac_sig_block_h(acc_rows), lambda p, y: qac_sig_block(p, y + 8, acc_rows, str(acc.get("head") or ""), str(acc.get("foot") or ""), accent), tail=True, sq=4)
    half = (PDF_CW - 28) / 2
    acc_txt = str(L.get("accept_text") or "") if (m.get("kind") or "offer") == "offer" else ""  # 2.357.0 C (#3182): not on a delivery note
    acc_dy = 14 if acc_txt else 0

    def draw_accept(p, y, gap=0):
        # 2.138.2 B (#2388): after the rights appendix (gap > 0) a section of its own: air above, heading and captions one step larger
        p3a_at.append(p)
        p.text(PDF_L, y + gap + 16, str(m.get("receipt_label") or L["accept"]).upper(), 10 if gap else 7.4, True, C_INK if gap else C_INK2, spacing=0.8)  # 2.120.0 D (#2089): + receipt label
        if acc_txt:  # 2.357.0 C (#3182): what the signature means, above the lines of a quotation
            p.text(PDF_L, y + gap + 16 + (16 if gap else 12), acc_txt, 8.6, False, C_INK)
        yl = y + gap + 16 + 40 + acc_dy + (6 if gap else 0)
        p.line(PDF_L, yl, PDF_L + half, yl, 0.6, C_INK)
        p.text(PDF_L, yl + 3, L["place_date"], 8.6 if gap else 7.6, False, C_INK2)
        p.line(PDF_L + half + 28, yl, PDF_L + PDF_CW, yl, 0.6, C_INK)
        p.text(PDF_L + half + 28, yl + 3, L["sign"], 8.6 if gap else 7.6, False, C_INK2)
    if (p3a_on and not p3a_end) or (m.get("kind") == "delivery" and np_):  # 2.120.0 D (#2089): the receipt box of a delivery note
        block(16 + 40 + acc_dy + 16, draw_accept, tail=True, sq=8)
    bfc_see_ref()  # no signature, no order confirmation: the line ends the main pages
    for h_, fn_ in pay_end:  # 2.434.0 A (#3603): bank line + GiroCode at the end of the main pages, right above the footer
        block(h_, fn_, tail=True, foot=True, keep_prev=True)  # 2.434.0 (#3603) review: never alone on an otherwise empty page

    # -- 2.47.0 (#1215): every printed part of a quotation on its own page(s): part title + number, its rows, its sums
    for part in m.get("parts") or []:
        if not isinstance(part, dict):
            continue
        ptitle = str(part.get("title") or "")
        psub = " · ".join(x for x in (f"{num_l} {number}" if number else "", str(m.get("project_title") or "")) if x)

        # 2.138.0 A (#2240): number + project as a small line above the title (was right beside it, a long title ran over it);
        # the title wraps over the full width, the accent line under its last line
        pt_lines = pb_wrap(ptitle, 14, PDF_CW, True, 0.8)  # 2.144.9 (#2575): as typed, the same spelling as on the title page
        ps_lines = pdf_wrap(psub, 8.6, PDF_CW) if psub else []
        pt_top = 4 + 12 * len(ps_lines) if ps_lines else 6
        pt_line = pt_top + (len(pt_lines) - 1) * 17.5 + 20

        def draw_part_head(p, y, pt_lines=pt_lines, ps_lines=ps_lines, pt_top=pt_top, pt_line=pt_line):
            for j, s in enumerate(ps_lines):
                p.text(PDF_L, y + 2 + j * 12, s, 8.6, False, C_INK2)
            for j, s in enumerate(pt_lines):
                p.text(PDF_L, y + pt_top + j * 17.5, s, 14, True, C_INK, spacing=0.8)
            p.line(PDF_L, y + pt_line, PDF_L + 14 * MM, y + pt_line, 1.6, accent)
        block(pt_line + 8, draw_part_head, keep_next=True, brk=True)
        for hr in part.get("head") or []:
            if isinstance(hr, (list, tuple)) and len(hr) >= 2:
                block(lh, lambda p, y, a=str(hr[0]), b=str(hr[1]): (p.text(PDF_L, y, a, 9, False, C_INK2), p.text(PDF_L + 112, y, b, 9)), keep_next=True)
        table_rows([x for x in (part.get("lines") or []) if isinstance(x, dict)])
        prow = [(str(r[0]), str(r[1])) for r in ((part.get("totals") or {}).get("rows") or []) if isinstance(r, (list, tuple)) and len(r) >= 2]
        # 2.144.9 (#2575): the part's optional raw data as a row of its own before "net total with option", as on the title page
        p_opt = next((x for x in (part.get("lines") or []) if isinstance(x, dict) and x.get("kind") == "raw" and x.get("optional")), None)
        pw_ = 190
        if prow and p_opt:
            ot = str(p_opt.get("title") or "").strip()
            prow[1:1] = [("+ " + (ot if ot.lower().startswith(L["optional"].lower()) else L["optional"] + (": " + ot if ot else "")),
                          str(p_opt.get("total_text") or "") or money(p_opt.get("total") or 0))]
            pw_ = 230
        if prow:
            def draw_part_sum(p, y, prow=prow, pw_=pw_):
                yy = y + 8
                for j, (lab, val) in enumerate(prow):
                    if j == 0:
                        p.line(PDF_L + PDF_CW - pw_, yy, PDF_L + PDF_CW, yy, 1.1, C_INK)
                        yy += 5
                    p.text(PDF_L + PDF_CW - pw_, yy, lab, 10.4 if j == 0 else 9, j == 0)
                    p.text(PDF_L + PDF_CW - pw_, yy, val, 10.4 if j == 0 else 8.8, j == 0, align="r", width=pw_)
                    yy += (10.4 if j == 0 else 9) * 1.5
            block(14 + sum((10.4 if j == 0 else 9) * 1.5 for j in range(len(prow))) + 5, draw_part_sum, keep_prev=True)

    # -- 2.114.1 C (#2258): the rights block as an appendix on its own last page, after the parts; 2.357.0 C (#3182): on the
    # last page itself when it fits there completely (with the order confirmation behind it), see rh_at below
    rh_at = []
    if bfc_rights:
        rtitle = str(rights.get("title") or L["rights"])
        rsub = " · ".join(x for x in (f"{num_l} {number}" if number else "", str(m.get("project_title") or "")) if x)

        # 2.296.0 E (#3170): a long number / project line wraps right of the heading, below the accent line when no room is left
        rs_w = PDF_CW - pdf_text_width(rtitle.upper(), 14, True, 0.8) - 6 * MM
        rs_low = bool(rsub) and rs_w < 100 and pdf_text_width(rsub, 8) > rs_w
        rs_lines = pdf_wrap(rsub, 8, PDF_CW if rs_low else max(rs_w, 100)) if rsub else []

        def bfc_draw_rights_head(p, y, rtitle=rtitle, rs_lines=rs_lines, rs_low=rs_low):
            p.text(PDF_L, y + 6, rtitle.upper(), 14, True, C_INK, spacing=0.8)
            p.line(PDF_L, y + 6 + 20, PDF_L + 14 * MM, y + 6 + 20, 1.6, accent)
            for j, s_ in enumerate(rs_lines):  # 2.138.2 B (#2388): not larger than the body text
                p.text(PDF_L + PDF_CW, y + (34 if rs_low else 8) + j * 10, s_, 8, False, C_INK2, align="r")
        rh_at.append(len(blocks))
        block(34 + 12 + max(0, len(rs_lines) * 10 + 6 if rs_low else (len(rs_lines) - 2) * 10), bfc_draw_rights_head, keep_next=True, brk=True)
        bfc_rights[0]()
    if p3a_end:  # 2.114.5 (#2300): the order confirmation behind the rights appendix (or the last part)
        agap = 32 if bfc_rights else 0  # 2.138.2 B (#2388)
        rh_acc.append(len(blocks))
        block(agap + 16 + 40 + acc_dy + 16 + (6 + 6 if agap else 0), lambda p, y, g=agap: draw_accept(p, y, g))

    # -- lay the blocks out on pages
    n_blocks = len(blocks)

    def group_end(i, soft):
        j = i
        # 2.296.0 E (#3166): never across a block that starts a new page (an appendix / part head); pk = the lines of a paragraph
        while j + 1 < n_blocks and not blocks[j + 1]["brk"] and (blocks[j]["keep_next"] or blocks[j + 1]["keep_prev"]
                                                                  or (soft and (blocks[j + 1]["tail"] or blocks[j]["pk"]))):
            j += 1
        return j

    def need(i, j, fresh):  # height of blocks i..j incl. the table heads they bring (2.138.0 E #2238: also inside the group)
        h = 0.0
        for k in range(i, j + 1):
            h += blocks[k]["h"] - blocks[k]["sq_used"] - blocks[k]["air_cut"]
            if blocks[k]["table"] and ((fresh and k == i) or (k > 0 and not blocks[k - 1]["table"])):
                h += thead_h
        return h

    def room_sq(i, j):
        return sum(blocks[k]["sq"] - blocks[k]["sq_used"] for k in range(i, j + 1))

    def room_air(i, j, floor=False):  # 2.294.0 (#3154): air still to give (floor: only down to its minimum)
        return sum(max(0.0, blocks[k]["air"] - blocks[k]["air_cut"] - (blocks[k]["air_min"] if floor else 0)) for k in range(i, j + 1))

    def cut_air(i, j, over, floor):
        for k in range(i, j + 1):
            t = min(over, max(0.0, blocks[k]["air"] - blocks[k]["air_cut"] - (blocks[k]["air_min"] if floor else 0)))
            blocks[k]["air_cut"] += t
            over -= t
        return over

    def page_bottom(later):  # 2.120.0 E (#2091): the body ends above the letterhead's footer
        return (BP["bottom"][later] if BP["hide_footer"] else min(BP["bottom"][later], body_bottom)) if BP else body_bottom

    def lay(dry, scale):  # 2.294.0 (#3154): dry = only count the pages (the air must never add one); scale = share of the air per kind
        nonlocal page
        for b in blocks:
            b["sq_used"] = 0.0
            b["air_cut"] = b["air"] * (1.0 - scale.get(b["air_kind"], 0.0))
        n_pages = 1
        if not dry:
            page = _Page()
            draw_letterhead(page)
            pages.append(page)
        y = PDF_ADDR_TOP
        first_on_page = True
        i = 0
        while i < n_blocks:
            b = blocks[i]
            if b.get("brk") and not first_on_page:  # 2.47.0 (#1215): a part starts on a new page
                n_pages += 1
                if not dry:
                    page = _Page()
                    draw_small_head(page)
                    pages.append(page)
                y = PDF_NEXT_TOP
                first_on_page = True
                continue
            bot = page_bottom(n_pages > 1)
            # the group that must stay together with b: keep_next chains forward, keep_prev of the follower; 2.138.0 E (#2238): plus the
            # rest of the closing (tail) as long as that group fits on an empty page (else the closing may break between its blocks)
            j = group_end(i, True)
            if j > i and need(i, j, True) - room_sq(i, j) - room_air(i, j) > page_bottom(True) - PDF_NEXT_TOP:
                j = group_end(i, False)
                cut_air(i, j, float("inf"), True)  # 2.294.0 (#3154): the closing breaks anyway -> only the minimum air
                if j > i and need(i, j, True) - room_sq(i, j) - room_air(i, j) > page_bottom(True) - PDF_NEXT_TOP:
                    j = i  # 2.296.0 E (#3166): a group that fits no page is not held together (it would only leave a page empty)
            nd = need(i, j, first_on_page)
            sqa = room_sq(i, j)
            aira = room_air(i, j)
            # 2.380.0 A (#3415): the totals' gap never goes below its minimum: if the closing is still too long with the air at its
            # minimum (no top gap given up either), it breaks (the totals with the last position on the next page)
            hold = any(blocks[k]["air_kind"] == "sum" for k in range(i, j + 1))
            if hold:
                aira = room_air(i, j, True)
                sqa = sum(blocks[k]["sq"] - blocks[k]["sq_used"] for k in range(i, j + 1) if not blocks[k]["air"])
            if y + nd > bot + 0.01 and sqa + aira > 0 and y + nd - sqa - aira <= bot + 0.01:
                # 2.294.0 (#3154): first the air around the totals down to its minimum, then (2.138.0 E #2238) the group a little
                # tighter (top gaps only, same font sizes), the air below its minimum last -- instead of breaking the page
                over = cut_air(i, j, y + nd - bot, True)
                for with_air in (False, True):  # the top gaps of the blocks with air (the totals' own) only with the air below its minimum
                    ks = [k for k in range(i, j + 1) if bool(blocks[k]["air"]) == with_air]
                    if with_air and hold:
                        break
                    if with_air and over > 0:
                        over = cut_air(i, j, over, False)
                    sqk = sum(blocks[k]["sq"] - blocks[k]["sq_used"] for k in ks)
                    if over > 0 and sqk > 0:
                        cut = min(1.0, over / sqk)
                        for k in ks:
                            blocks[k]["sq_used"] += (blocks[k]["sq"] - blocks[k]["sq_used"]) * cut
                        over -= sqk * cut
                nd = need(i, j, first_on_page)
            if y + nd > bot + 0.01 and not first_on_page:
                # does b alone fit together with everything that must precede the break? no: new page
                n_pages += 1
                if not dry:
                    page = _Page()
                    draw_small_head(page)
                    pages.append(page)
                y = PDF_NEXT_TOP
                first_on_page = True
                continue
            if y + nd > bot + 0.01:
                cut_air(i, j, float("inf"), False)  # 2.294.0 (#3154): overfull anyway -> no air on top of it
            if sum_at and i == sum_at[0] and PDF_SUM_FILL > 0:
                # 2.406.0 (#3491): totals + closing (up to the next page break / appendix) at the bottom of this page when all of it fits here
                je = i
                while je + 1 < n_blocks and not blocks[je + 1]["brk"]:
                    je += 1
                free = bot - y - need(i, je, False)
                if free > 0:
                    y += free * PDF_SUM_FILL
            if b["foot"]:  # 2.434.0 A (#3603): down to the bottom of the page together with what follows up to the next page break
                je = i
                while je + 1 < n_blocks and not blocks[je + 1]["brk"]:
                    je += 1
                y = max(y, bot - need(i, je, first_on_page))
            if b["table"] and (first_on_page or not blocks[i - 1]["table"]):
                if not dry:
                    draw_thead(page, y)
                y += thead_h
            if not dry:
                # 2.294.0 (#3154): the air below the block is given up first, the top air keeps its minimum longest
                b["draw"](page, y - b["sq_used"] + max(0.0, b["air_top"] - max(0.0, b["air_cut"] - (b["air"] - b["air_top"]))))
            y += b["h"] - b["sq_used"] - b["air_cut"]
            first_on_page = False
            i += 1
        # 2.294.0 (#3154): tight = some air went below its minimum (or the totals gave up their own top gap)
        return n_pages, any(b["air"] and (b["air_cut"] > b["air"] - b["air_min"] + 0.01 or b["sq_used"] > 0.01) for b in blocks)

    pages = []
    page = None
    # 2.380.0 A (#3415) + 2.357.0 C (#3182), rescue #1592: the totals' air held at its minimum gap (the least #3415 allows); the
    # appendix decision and the last fallback count with it instead of with no air at all
    air_min = {"sum": max(0.0, PDF_SUM_GAP_MIN - 8) / max(1.0, PDF_SUM_GAP - 8 + PDF_SUM_AFTER)}
    if rh_at:  # 2.357.0 C (#3182): the appendix without its page break when that saves a page and it stays whole on one page;
        # then without the reference lines ("see appendix", "order confirmation on page n") and with the compact order confirmation
        keep = [(i, dict(blocks[i])) for i in rh_ref + rh_acc]
        for i in rh_ref:
            blocks[i].update(h=0.0, draw=lambda p, y: None)
        for i, h, fn in q3_alt:  # 2.406.0 (#3491): look A: the closing without its reference lines
            keep.append((i, dict(blocks[i])))
            blocks[i].update(h=h, draw=fn)
        for i in rh_acc:
            blocks[i].update(h=16 + 40 + acc_dy + 16, draw=lambda p, y: draw_accept(p, y))
        blocks[rh_at[0]]["brk"] = False
        app_hs = [b["h"] for b in blocks[rh_at[0]:]]
        for b in blocks[rh_at[0]:]:
            b["h"] = 0.0
        n_main = lay(True, air_min)[0]  # the pages without the appendix
        for b, h in zip(blocks[rh_at[0]:], app_hs):
            b["h"] = h
        if lay(True, air_min)[0] > n_main:  # it does not fit completely on the last page: as before on a page of its own
            blocks[rh_at[0]]["brk"] = True
            for i, b in keep:
                blocks[i].update(b)
    # 2.294.0 (#3154): the full air unless that costs a page or presses the totals below their minimum gap; then less intro air
    # step by step, the totals' air last (it already shrinks on its own page before a break) -- never more pages than without air
    tries = [{"intro": 1.0, "sum": 1.0}, {"intro": 2 / 3, "sum": 1.0}, {"intro": 1 / 3, "sum": 1.0}, {"sum": 1.0}, {}]
    if any(b["air"] for b in blocks):
        base = lay(True, {})[0]
        res = [(t, lay(True, t)) for t in tries]
        # 2.380.0 A (#3415): the totals' air never goes below its minimum (a break instead); the first try without an extra page,
        # else the one with the fewest pages (the full air, then less intro air); the totals at their minimum gap last, as the
        # appendix decision above counts with it (else the order confirmation slides onto a page of its own, p2406_lead_pdf)
        ns = [(t, lay(True, t)[0]) for t in tries[:4] + [air_min]]
        tries = [next((t for t, n in ns if n <= base), None) or min(ns, key=lambda x: x[1])[0]]
    lay(False, tries[0])
    total = len(pages)
    for n, p in enumerate(pages, 1):
        draw_footer(p, n, total)
    for p, at, yy, t, *ex in reversed(p3a_ref):  # 2.114.5 (#2300): the page the order confirmation landed on
        tmp = _Page()
        rx, rs, ra, rw = ex or (PDF_L, 8.6, "l", None)  # 2.406.0 (#3491): x, size, align, width of the line
        tmp.text(rx, yy, t.format(next((n for n, q in enumerate(pages, 1) if p3a_at and q is p3a_at[0]), total)), rs, False, C_INK2, align=ra, width=rw)
        p.ops[at:at] = tmp.ops
    # 2.114.4 A (#2273): no "Page 1 of n" next to the title any more, the footer has it
    if str(m.get("draft_mark") or "").strip():
        for p in pages:
            p.mark(str(m["draft_mark"]).strip())
    if BP:
        bp_finish(pages, BP)  # 2.120.0 E (#2091): the letterhead behind every page
    return pdf_write(pages, images, title=f"{title} {number}".strip(), author=co.get("name") or "", xml=xml, meta=meta)


def bp_geometry(lh):
    """2.184.0 C (#2581): the margins of letterhead lh (see bp_layout) as layout values in points: {l, cw, addr_top, next_top,
    bp (the BP dict of bp_finish / the page code)}; shared by office_pdf (bp_layout) and the letters (office.letters)."""
    mm = lambda key, dflt: [min(150.0, max(0.0, float(v))) * MM for v in (list(lh.get(key) or []) + dflt)[:4]]  # noqa: E731
    t1, r1, b1, l1 = mm("m1", [45, 20, 32, 25])
    t2, r2, b2, l2 = mm("m2", [30, 20, 32, 25])
    cw = max(60 * MM, min(A4_W - l1 - r1, A4_W - l2 - r2))
    bottom = [A4_H - b1, A4_H - b2]
    if not lh.get("hide_footer"):  # the own footer stays where it is: the body ends above it
        bottom = [min(y, PDF_BODY_BOTTOM) for y in bottom]
    bottom = [max(y, t + 40 * MM) for y, t in zip(bottom, (t1 + PDF_ADDR_H, t2))]  # never a page without room
    return {"l": l1, "cw": cw, "addr_top": t1, "next_top": t2,
            "bp": {"hide_head": bool(lh.get("hide_head")), "hide_footer": bool(lh.get("hide_footer")), "bottom": bottom,
                   "dx": l2 - l1, "pages": int(lh.get("pages") or 0), "emit": lh.get("emit")}}


def bp_layout(lh, model, logo_bytes=None, xml=None, meta=None):
    """2.120.0 E (#2091): office_pdf with an own letterhead (office.letterhead bp_model): lh = {"m1": [top, right, bottom,
    left] mm of page 1 (top = where the address field begins), "m2": the same for the following pages, "hide_head",
    "hide_footer": 0/1, "pages": 1 or 2 letterhead pages, "emit": fn(objs, i) -> object number of letterhead page i as a
    form XObject}. The layout code stays as it is: it runs once more with its margin constants taken from lh (a copy of
    this module's globals for this call only, so parallel requests never see each other's margins). The text width is
    the narrower one of the two pages; following pages are moved by the difference of the left margins."""
    import types
    geo = bp_geometry(lh)
    l1, cw, t1, t2, bp = geo["l"], geo["cw"], geo["addr_top"], geo["next_top"], geo["bp"]
    g = dict(globals())
    g.update(PDF_L=l1, PDF_R=A4_W - l1 - cw, PDF_CW=cw, PDF_ADDR_TOP=t1, PDF_NEXT_TOP=t2, BP=bp)
    for k, v in list(g.items()):
        if isinstance(v, types.FunctionType) and v.__module__ == __name__:
            g[k] = types.FunctionType(v.__code__, g, v.__name__, v.__defaults__, v.__closure__)
    return g["office_pdf"](model, logo_bytes, xml, meta)


def bp_finish(pages, bp):
    """2.120.0 E (#2091): following pages moved by the left margin difference, the letterhead page (1 for page 1, 2 for
    the rest; one letterhead page for all) drawn first as a form XObject so the document stays on top."""
    for n, p in enumerate(pages):
        if n and bp["dx"]:
            p.ops.insert(0, f"q 1 0 0 1 {bp['dx']:.2f} 0 cm")
            p.ops.append("Q")
        if bp["pages"] and bp["emit"]:
            i = min(1 if n else 0, bp["pages"] - 1)
            name = f"BP{i + 1}"
            p.ops.insert(0, f"q /{name} Do Q")
            p.forms = {name: (lambda objs, i=i: bp["emit"](objs, i))}


# ---- 2.357.0 A (#3156): the paper size per company (office settings "paper": "a4" | "letter") ------------------------
IN = 72.0
PAPER_SIZES = {"a4": (A4_W, A4_H), "letter": (8.5 * IN, 11 * IN)}


def pdf_paper(v):
    """2.357.0 A (#3156): the paper size of a setting / print model: "letter" (US-Letter 8.5 x 11 in), anything else A4."""
    return "letter" if str(v or "").strip().lower().replace("-", "_") in ("letter", "us_letter", "usletter") else "a4"


def pdf_paper_ns(paper):
    """2.357.0 A (#3156): this module for paper size `paper`: A4 = the module itself; US-Letter = a copy of its globals with
    the page size, margins (1 in left / right), the address field for a #10 window envelope (recipient from about 2.1 in) and
    fold marks on the thirds (no punch mark), every function bound to that copy -- the same pattern as bp_layout (which runs
    inside it for a letterhead), so the layout code stays as it is and parallel requests never see each other's sizes.
    Callers use it like the module: P = pdf_paper_ns(s.get("paper")); P._Page(), P.A4_W, P.pdf_write(...)."""
    import sys
    import types
    if pdf_paper(paper) == PAPER:
        mod = sys.modules.get(__name__)  # (a file loaded on its own by a test may not be in sys.modules)
        return mod if mod is not None and globals() is vars(mod) else types.SimpleNamespace(**globals())
    w, h = PAPER_SIZES[pdf_paper(paper)]
    g = dict(globals())
    if pdf_paper(paper) == "letter":
        g.update(A4_W=w, A4_H=h, PDF_L=1 * IN, PDF_R=1 * IN, PDF_CW=w - 2 * IN, PDF_ADDR_TOP=2 * IN,
                 PDF_BODY_BOTTOM=h - 12 * MM - PDF_FOOT_H, PDF_MARKS=(h / 3, 2 * h / 3), PAPER="letter")
    else:  # back to A4 from a letter copy
        g.update(A4_W=w, A4_H=h, PDF_L=25 * MM, PDF_R=20 * MM, PDF_CW=w - 45 * MM, PDF_ADDR_TOP=45 * MM,
                 PDF_BODY_BOTTOM=h - 12 * MM - PDF_FOOT_H, PDF_MARKS=(105 * MM, 148.5 * MM, 210 * MM), PAPER="a4")
    g["_Page"] = type("_Page", (_Page,), {"W": w, "H": h, "__module__": __name__})
    for k, v in list(g.items()):
        if isinstance(v, types.FunctionType) and v.__module__ == __name__:
            g[k] = types.FunctionType(v.__code__, g, v.__name__, v.__defaults__, v.__closure__)
    return types.SimpleNamespace(**g)


def pdf_paper_bind(fn, paper):
    """2.357.0 A (#3156): fn, a function of a module that imported names from this one at its top (mealpdf), bound to a copy
    of that module's globals in which those names come from pdf_paper_ns(paper) (its other functions bound to the copy
    too); A4: fn itself. The caller checks the imported PAPER first: `if paper != PAPER: return pdf_paper_bind(f, paper)(...)`."""
    import types
    if pdf_paper(paper) == PAPER:
        return fn
    ns = pdf_paper_ns(paper)
    src, mine = fn.__globals__, globals()
    g = dict(src)
    for k, v in src.items():
        if k in mine and mine[k] is v and hasattr(ns, k):
            g[k] = getattr(ns, k)
    for k, v in list(g.items()):
        if isinstance(v, types.FunctionType) and v.__module__ == fn.__module__:
            g[k] = types.FunctionType(v.__code__, g, v.__name__, v.__defaults__, v.__closure__)
    return g[fn.__name__]
