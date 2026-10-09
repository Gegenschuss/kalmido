"""2.36.1 (#1021, part D): the PDF of an office document (quotation), written without any PDF library.

Input is the print model of office.docs (odoc_render): a plain dict with the document's texts, lines and totals in the
document's language (DE / EN) -- see office_pdf() below for the keys. Output: the bytes of a PDF 1.4 file with real A4
pages (DIN 5008 form B: address in the window area, sender line above it, key data on the right, fold marks), the
base-14 fonts Helvetica / Helvetica-Bold in WinAnsiEncoding (umlauts, sharp s, euro sign), the company's logo as an
image (PNG / JPEG / WebP through Pillow -> RGB + FlateDecode) and the company colour as the only accent (rules, title,
category headings). Text wraps with the AFM width tables of the two fonts (below). Page breaks: following pages carry a
small head (logo, title, number) and repeat the table head; "Page x of y" is written after all pages are laid out;
a category heading never stays alone at the end of a page, text blocks and the rights block are not torn, the totals
never stand alone on a page (the last position comes along); no carry-over lines.

Nothing here reads the database: office.web / office.docs render the model and call office_pdf(model)."""
import datetime
import io
import re
import zlib

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
PDF_FOOT_H = 20 * MM     # footer (four columns + page line) reserved at the bottom of every page
PDF_BODY_BOTTOM = A4_H - 12 * MM - PDF_FOOT_H
PDF_NEXT_TOP = 30 * MM   # body top on following pages (below the small head)
PDF_LOGO_MAX_W = 60 * MM
PDF_LOGO_MAX_H = 22 * MM
PDF_LOGO_MAX_PX = 1600   # the upload route scales to this width; the writer accepts anything Pillow reads

# ---- colours ("#rrggbb"); the accent comes from the company settings ----------------------------------------------
C_INK, C_INK2, C_RULE, C_RULE2, C_WHITE = "#16191f", "#4b515c", "#c9ced6", "#e7e9ee", "#ffffff"

# ---- labels in the document language; the pack's labels (model["labels"]) override these -------------------------
PDF_LABELS = {
    "de": {"title": "Kostenvoranschlag", "number": "Angebot Nr.", "date": "Datum", "valid_until": "Gültig bis",
           "client": "Kunde", "ref": "Ihre Referenz", "project": "Projekt", "pos": "Pos.", "service": "Leistung",
           "qty": "Menge", "rate": "Einzelpreis", "vat": "MwSt.", "total": "Gesamt", "net": "Summe netto",
           "vat_plus": "zzgl. {0} % MwSt.", "gross": "Gesamt brutto", "incl_raw": "Gesamt inklusive Rohdaten",
           "excl_raw": "Summe ohne Rohdaten", "net_suffix": "netto", "optional": "Optional", "rights": "Rechteübertragung",
           "accept": "Auftragserteilung", "place_date": "Ort, Datum", "sign": "Unterschrift, Stempel Auftraggeber",
           "page": "Seite {0} von {1}", "contact": "Kontakt", "register": "Register", "bank": "Bank",
           "discount": "Rabatt", "producing": "Producing"},
    "en": {"title": "Quotation", "number": "Quotation No.", "date": "Date", "valid_until": "Valid until",
           "client": "Client", "ref": "Your reference", "project": "Project", "pos": "No.", "service": "Service",
           "qty": "Qty", "rate": "Unit price", "vat": "VAT", "total": "Total", "net": "Net total",
           "vat_plus": "plus {0} % VAT", "gross": "Total incl. VAT", "incl_raw": "Total including raw data",
           "excl_raw": "Total excluding raw data", "net_suffix": "net", "optional": "Optional", "rights": "Transfer of rights",
           "accept": "Order confirmation", "place_date": "Place, date", "sign": "Signature, stamp of the client",
           "page": "Page {0} of {1}", "contact": "Contact", "register": "Registration", "bank": "Bank",
           "discount": "Discount", "producing": "Producing"},
}

# ---- AFM widths of Helvetica and Helvetica-Bold for WinAnsiEncoding (codes 32..255, 1/1000 em) -------------------
_W_HELV = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,  # 32
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,  # 48
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,  # 64
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,  # 80
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,  # 96
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584, 350,  # 112
    556, 350, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350,  # 128
    350, 222, 222, 333, 333, 350, 556, 1000, 333, 1000, 500, 333, 944, 350, 500, 667,  # 144
    278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333,  # 160
    400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611,  # 176
    667, 667, 667, 667, 667, 667, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,  # 192
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,  # 208
    556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556, 278, 278, 278, 278,  # 224
    556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556, 500, 556, 500,  # 240
)
_W_BOLD = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,  # 32
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,  # 48
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,  # 64
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,  # 80
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,  # 96
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 350,  # 112
    556, 350, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350,  # 128
    350, 278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 350, 500, 667,  # 144
    278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333,  # 160
    400, 584, 333, 333, 333, 611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611,  # 176
    722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,  # 192
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,  # 208
    556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278,  # 224
    611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556, 611, 556,  # 240
)
# characters outside WinAnsi that appear in office texts, mapped to something the fonts have
_FALLBACK = str.maketrans({"→": "->", "←": "<-", "≤": "<=", "≥": ">=", "−": "-", " ": " ",
                           " ": " ", " ": " ", " ": " ", "‑": "-", "′": "'", "″": '"',
                           "✓": "x", "✔": "x", "☐": "[ ]", "☑": "[x]", "\t": " "})


def pdf_encode(s):
    """str -> WinAnsi bytes (cp1252; unknown characters become '?')."""
    s = str(s or "").translate(_FALLBACK)
    return s.encode("cp1252", errors="replace")


def pdf_text_width(s, size, bold=False, spacing=0.0):
    """Width of s in points at the given size (plus the character spacing, like the Tc operator)."""
    b = pdf_encode(s)
    tab = _W_BOLD if bold else _W_HELV
    w = 0
    for ch in b:
        w += tab[ch - 32] if 32 <= ch < 256 else 556
    return w * size / 1000.0 + spacing * len(b)


def pdf_wrap(text, size, width, bold=False):
    """Breaks text into lines that fit width (explicit line breaks kept, long words cut by characters)."""
    out = []
    for para in str(text or "").replace("\r", "").split("\n"):
        words = para.split(" ")
        line = ""
        for w in words:
            cand = (line + " " + w) if line else w
            if pdf_text_width(cand, size, bold) <= width or not line and not w:
                line = cand
                continue
            if line:
                out.append(line)
                line = ""
            if pdf_text_width(w, size, bold) > width and len(w) > 1:  # a word longer than the line: cut by summed widths, one pass
                part, pw = "", 0.0
                for ch in w:
                    cw = pdf_text_width(ch, size, bold)
                    if part and pw + cw > width:
                        out.append(part)
                        part, pw = "", 0.0
                    part += ch
                    pw += cw
                w = part
            line = w
        out.append(line)
    return out


def _rgb(hexcol):
    h = (hexcol or "").strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = "2f5d8a"
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _f(x):
    return f"{x:.2f}".rstrip("0").rstrip(".") if x != int(x) else str(int(x))


class _Page:
    """Collects the content stream of one page (coordinates: x from the left, y from the TOP, in points)."""

    def __init__(self):
        self.ops = []
        self.images = set()

    def text(self, x, y, s, size, bold=False, color=C_INK, align="l", spacing=0.0, width=None):
        """Draws one line; y is the top of the line box (the baseline sits 0.78 * size below it)."""
        s = str(s or "")
        if not s:
            return
        w = pdf_text_width(s, size, bold, spacing)
        if align == "r":
            x = x + (width or 0) - w if width else x - w
        elif align == "c":
            x = x + ((width or 0) - w) / 2
        r, g, b = _rgb(color)
        self.ops.append(f"BT {r:.3f} {g:.3f} {b:.3f} rg /{'F2' if bold else 'F1'} {size:.2f} Tf {spacing:.2f} Tc "
                        f"{x:.2f} {A4_H - y - size * 0.78:.2f} Td <{pdf_encode(s).hex()}> Tj ET")

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
        self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {w:.2f} w {d}{x1:.2f} {A4_H - y1:.2f} m {x2:.2f} {A4_H - y2:.2f} l S")

    def rect(self, x, y, w, h, color, stroke=False, lw=0.5, dash=None):
        r, g, b = _rgb(color)
        if stroke:
            d = f"[{dash[0]} {dash[1]}] 0 d " if dash else "[] 0 d "
            self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {lw:.2f} w {d}{x:.2f} {A4_H - y - h:.2f} {w:.2f} {h:.2f} re S")
        else:
            self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {A4_H - y - h:.2f} {w:.2f} {h:.2f} re f")

    def image(self, name, x, y, w, h):
        self.images.add(name)
        self.ops.append(f"q {w:.2f} 0 0 {h:.2f} {x:.2f} {A4_H - y - h:.2f} cm /{name} Do Q")


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


def pdf_write(pages, images, title="", author=""):
    """Serialises pages ([_Page]) and images ({name: (w, h, data)}) into PDF 1.4 bytes."""
    objs = []  # list of bytes bodies; object number = index + 1

    def add(body):
        objs.append(body)
        return len(objs)

    font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    img_ids = {}
    for name, (w, h, data) in images.items():
        img_ids[name] = add(f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB "
                            f"/BitsPerComponent 8 /Filter /FlateDecode /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream")
    pages_id = len(objs) + 1 + 2 * len(pages)  # the Pages object comes after all page + content objects
    page_ids = []
    for p in pages:
        content = zlib.compress("\n".join(p.ops).encode("latin-1"), 6)
        cid = add(f"<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n".encode() + content + b"\nendstream")
        xo = " ".join(f"/{n} {img_ids[n]} 0 R" for n in sorted(p.images) if n in img_ids)
        pid = add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {A4_W:.2f} {A4_H:.2f}] "
                  f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> /XObject << {xo} >> >> "
                  f"/Contents {cid} 0 R >>".encode())
        page_ids.append(pid)
    assert len(objs) + 1 == pages_id
    add(f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in page_ids)}] /Count {len(page_ids)} >>".encode())
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    def pstr(s):
        return b"(" + pdf_encode(s).replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"
    info = add(b"<< /Producer (Kalmido) /Creator (Kalmido) /Title " + pstr(title) + b" /Author " + pstr(author) +
               b" /CreationDate (D:" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S").encode() + b"Z) >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for o in offsets:
        out.write(f"{o:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


# ---- number and date formats in the document language -------------------------------------------------------------
def pdf_money(v, lang, currency, fmt=None):
    """1234.5 -> "1.234,50 €" (de) / "1,234.50 €" (en); USD is written as "USD"; fmt = the pack's formats (optional)."""
    fmt = fmt or {}
    dec = fmt.get("decimal") or ("," if lang == "de" else ".")
    tho = fmt.get("thousands") or ("." if lang == "de" else ",")
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    neg = v < 0
    s = f"{abs(v):,.2f}".replace(",", "\x00").replace(".", dec).replace("\x00", tho)
    sym = fmt.get("currency_symbol") or {"EUR": "€", "USD": "USD", "GBP": "£", "CHF": "CHF"}.get(currency or "EUR", currency or "")
    s = f"{sym} {s}" if (fmt.get("currency_pos") == "before") else f"{s} {sym}"
    return ("-" if neg else "") + s


def pdf_num(v, lang, fmt=None):
    """A quantity: 3 -> "3", 4.5 -> "4,5" (de) / "4.5" (en)."""
    fmt = fmt or {}
    dec = fmt.get("decimal") or ("," if lang == "de" else ".")
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return str(v)
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", dec)


def pdf_date(s, lang, fmt=None):
    """ISO date -> "09.10.2026" (de) / "9 October 2026" (en); anything else is returned as it is."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(s or "")[:10])
    if not m:
        return str(s or "")
    y, mo, d = m.groups()
    if lang == "de":
        return f"{d}.{mo}.{y}"
    months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
    return f"{int(d)} {months[int(mo) - 1]} {y}"


# ---- the document ------------------------------------------------------------------------------------------------------
def office_pdf(model, logo_bytes=None):
    """The quotation PDF (bytes) from the print model of office.docs:
    {kind, lang, currency, number, date, valid_until, title, project_title, project_ref, client (name, optional),
     company {name, lines[], contact_lines[], register_lines[], bank_lines[], logo_path, color}, recipient {name, lines[]},
     intro, lines [{kind: heading|item|text|producing|raw|discount, ...}], totals {net, tax_lines[{pct, base, amount}],
     gross, net_incl_raw, net_excl_raw, vat_note}, rights {title, rows[[label, text]], note}, closing, signature,
     fields [{name, value}], labels {...}, formats {...}}.
    logo_bytes: the logo file (else company.logo_path is read)."""
    m = model or {}
    lang = "en" if str(m.get("lang") or "de").lower().startswith("en") else "de"
    L = dict(PDF_LABELS[lang])
    ml = m.get("labels") or {}
    for mine, theirs in (("number", "offer_no"), ("service", "title"), ("rate", "unit_price"), ("net", "net_total"),
                         ("gross", "gross_total"), ("accept", "order"), ("page", "page_of")):
        if isinstance(ml.get(theirs), str) and ml[theirs]:
            L[mine] = ml[theirs].replace("{x}", "{0}").replace("{y}", "{1}")
    L.update({k: v for k, v in ml.items() if k in L and isinstance(v, str) and v and k not in ("title", "page")})
    fmt = m.get("formats") or {}
    cur = m.get("currency") or "EUR"
    co = m.get("company") or {}
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
        w, h = logo[0], logo[1]
        sc = min(max_w / w, max_h / h)
        return w * sc, h * sc

    # -- letterhead (page 1) and the small head (following pages)
    def draw_letterhead(p):
        if logo:
            w, h = logo_box(PDF_LOGO_MAX_W, PDF_LOGO_MAX_H)
            p.image("Logo", A4_W - PDF_R - w, PDF_TOP + 2 * MM, w, h)
        else:
            p.text(PDF_L + PDF_CW, PDF_TOP + 4 * MM, co.get("name") or "", 15, True, C_INK, align="r", spacing=1.2)
            p.rect(A4_W - PDF_R - 12 * MM, PDF_TOP + 4 * MM + 24, 12 * MM, 2.2, accent)
        for y in (105 * MM, 148.5 * MM, 210 * MM):  # fold and punch marks (DIN 5008 form B)
            p.line(5 * MM, y, 9 * MM, y, 0.4, C_RULE)

    def draw_small_head(p):
        y = 12 * MM
        if logo:
            w, h = logo_box(32 * MM, 11 * MM)
            p.image("Logo", A4_W - PDF_R - w, y, w, h)
        else:
            p.text(PDF_L + PDF_CW, y, co.get("name") or "", 9, True, C_INK, align="r", spacing=0.6)
        p.text(PDF_L, y + 2, f"{title} {number}".strip() + (" · " + rc["name"] if rc.get("name") else ""), 8, False, C_INK2)
        p.line(PDF_L, 24.5 * MM, PDF_L + PDF_CW, 24.5 * MM, 0.5, accent)

    # -- footer (every page), four columns; empty ones are left out
    cols = [list(dict.fromkeys([co.get("name") or ""] + [str(x) for x in (co.get("lines") or [])])), list(co.get("contact_lines") or []),
            list(co.get("register_lines") or []), list(co.get("bank_lines") or [])]
    cols = [c for c in cols if any(str(x).strip() for x in c)]

    def draw_footer(p, n, total):
        top = A4_H - 12 * MM - PDF_FOOT_H
        p.line(PDF_L, top, PDF_L + PDF_CW, top, 0.5, C_RULE)
        if cols:
            # widths follow the longest line of each column (an IBAN stays on one line), never below 60 % of a fair share
            free = PDF_CW - 8 * (len(cols) - 1)
            nat = [max(pdf_text_width(str(ln), 6.9, bold=(i == 0 and j == 0)) for j, ln in enumerate(c)) + 3 for i, c in enumerate(cols)]
            if sum(nat) <= free:
                cws = [w + (free - sum(nat)) / len(cols) for w in nat]
            else:
                floor = 0.6 * free / len(cols)
                want = [max(0.0, w - floor) for w in nat]
                extra = free - floor * len(cols)
                cws = [floor + (extra * w / sum(want) if sum(want) else extra / len(cols)) for w in want]
            x = PDF_L
            for i, c in enumerate(cols):
                if i:
                    x += cws[i - 1] + 8
                cw = cws[i]
                yy = top + 5
                shown = [(w, j == 0) for j, ln in enumerate(c) for w in pdf_wrap(str(ln), 6.9, cw - 2, bold=(i == 0 and j == 0))][:6]
                for ln, first in shown:
                    p.text(x, yy, ln, 6.9, bold=(i == 0 and first), color=C_INK if (i == 0 and first) else C_INK2)
                    yy += 9.6
        p.text(PDF_L + PDF_CW, A4_H - 9 * MM, (number + " · " if number else "") + L["page"].format(n, total), 6.8, False, C_INK2, align="r")

    # -- blocks: (height, draw(page, y), keep_next, keep_prev, table)
    blocks = []

    def block(h, fn, keep_next=False, keep_prev=False, table=False):
        blocks.append({"h": h, "draw": fn, "keep_next": keep_next, "keep_prev": keep_prev, "table": table})

    body = 9.6
    lh = body * 1.42

    # -- page 1 head: address field left, key data right
    info = [(str(r[0]), str(r[1])) for r in (m.get("meta") or []) if isinstance(r, (list, tuple)) and len(r) >= 2 and str(r[1]).strip()]
    if not info:
        if number:
            info.append((L["number"], number))
        if m.get("date"):
            info.append((L["date"], m.get("date_text") or pdf_date(m["date"], lang, fmt)))
        if m.get("valid_until"):
            info.append((L["valid_until"], m.get("valid_until_text") or pdf_date(m["valid_until"], lang, fmt)))
        if m.get("client") and str(m["client"]).strip() and str(m["client"]).strip() != str(rc.get("name") or "").strip():
            info.append((L["client"], str(m["client"])))
        if m.get("project_ref"):
            info.append((L["ref"], str(m["project_ref"])))
    for f in m.get("fields") or []:
        if isinstance(f, dict) and str(f.get("name") or "").strip():
            info.append((str(f["name"]), str(f.get("value") or "")))
    info_x = PDF_L + PDF_ADDR_W + 8 * MM
    info_w = PDF_CW - PDF_ADDR_W - 8 * MM
    info_lh = 8.6 * 1.45
    addr_lines = [str(x) for x in (rc.get("lines") or []) if str(x).strip()]
    if rc.get("name") and (not addr_lines or addr_lines[0].strip() != str(rc["name"]).strip()):
        addr_lines.insert(0, str(rc["name"]))

    def draw_head(p, y):
        sender = str(co.get("sender_line") or "") or " · ".join(dict.fromkeys(str(x) for x in [co.get("name") or ""] + list(co.get("lines") or []) if str(x).strip()))
        sender_w = pdf_text_width(sender, 7)
        while sender_w > PDF_ADDR_W and " · " in sender:  # too long: drop trailing parts
            sender = sender.rsplit(" · ", 1)[0]
            sender_w = pdf_text_width(sender, 7)
        p.text(PDF_L, y, sender, 7, False, C_INK2)
        p.line(PDF_L, y + 11, PDF_L + PDF_ADDR_W, y + 11, 0.5, C_RULE2)
        yy = y + 16
        for ln in addr_lines[:8]:
            p.text(PDF_L, yy, ln, body)
            yy += lh
        yy = y + 2
        for k, v in info:
            p.text(info_x, yy, k, 8.6, False, C_INK2)
            vw = info_w - pdf_text_width(k, 8.6) - 10
            vl = pdf_wrap(v, 8.6, max(vw, 40))
            for vv in vl:
                p.text(info_x, yy, vv, 8.6, True, C_INK, align="r", width=info_w)
                yy += info_lh
    head_h = max(PDF_ADDR_H, 2 + sum(max(1, len(pdf_wrap(v, 8.6, max(info_w - pdf_text_width(k, 8.6) - 10, 40)))) for k, v in info) * info_lh + 4)
    block(head_h, draw_head)

    # -- title line, project title, intro
    title_at = {}

    def draw_title(p, y):
        title_at["page"], title_at["y"] = p, y
        p.text(PDF_L, y + 6, title.upper(), 16, True, C_INK, spacing=1.0)
        p.line(PDF_L, y + 6 + 22, PDF_L + 14 * MM, y + 6 + 22, 1.6, accent)
    block(34, draw_title, keep_next=True)
    if m.get("project_title"):
        pt = str(m["project_title"])
        n = len(pdf_wrap(pt, 10.4, PDF_CW, True))
        block(n * 10.4 * 1.42 + 8, lambda p, y, t=pt: p.para(PDF_L, y + 2, t, 10.4, PDF_CW, True), keep_next=True)
    if m.get("intro"):
        it = str(m["intro"])
        n = len(pdf_wrap(it, body, PDF_CW))
        block(n * lh + 8, lambda p, y, t=it: p.para(PDF_L, y, t, body, PDF_CW), keep_next=True)

    # -- the table: columns Pos. | Service | Qty | Unit price | VAT | Total
    c_pos, c_qty, c_rate, c_vat, c_tot = 22, 64, 70, 36, 76
    c_title = PDF_CW - c_pos - c_qty - c_rate - c_vat - c_tot
    x_pos = PDF_L
    x_title = x_pos + c_pos
    x_qty = x_title + c_title
    x_rate = x_qty + c_qty
    x_vat = x_rate + c_rate
    x_tot = x_vat + c_vat
    thead_h = 20

    def draw_thead(p, y):
        yy = y + 4
        p.text(x_pos + 3, yy, L["pos"].upper(), 7.4, True, C_INK2, spacing=0.6)
        p.text(x_title + 3, yy, L["service"].upper(), 7.4, True, C_INK2, spacing=0.6)
        p.text(x_qty, yy, L["qty"].upper(), 7.4, True, C_INK2, align="r", width=c_qty - 3, spacing=0.6)
        p.text(x_rate, yy, L["rate"].upper(), 7.4, True, C_INK2, align="r", width=c_rate - 3, spacing=0.6)
        p.text(x_vat, yy, L["vat"].upper(), 7.4, True, C_INK2, align="c", width=c_vat, spacing=0.6)
        p.text(x_tot, yy, L["total"].upper(), 7.4, True, C_INK2, align="r", width=c_tot - 3, spacing=0.6)
        p.line(PDF_L, y + thead_h - 1, PDF_L + PDF_CW, y + thead_h - 1, 1.1, C_INK)

    lines = [x for x in (m.get("lines") or []) if isinstance(x, dict)]
    have_table = False
    last_item_idx = None
    for i, ln in enumerate(lines):
        k = ln.get("kind") or "item"
        if k == "heading":
            t = str(ln.get("title") or "")
            block(22, lambda p, y, t=t: p.text(x_title + 3, y + 11, t.upper(), 8, True, accent, spacing=0.8), keep_next=True, table=True)
            have_table = True
        elif k == "text":
            tw = c_title + c_qty + c_rate + c_vat + c_tot - 6
            wrapped = pdf_wrap(str(ln.get("text") or ""), body, tw)
            for part in (wrapped[q:q + 40] for q in range(0, max(1, len(wrapped)), 40)):  # a very long block may break (40 lines each)
                block(len(part) * lh + 10, lambda p, y, part=part: [p.text(x_title + 3, y + 4 + q * lh, s_, body) for q, s_ in enumerate(part)],
                      table=True)
        elif k in ("item", "producing", "raw", "discount"):
            if k == "raw" and ln.get("optional"):
                continue  # the option is printed below the totals
            t = str(ln.get("title") or (L["producing"] if k == "producing" else L["discount"] if k == "discount" else ""))
            if k == "discount" and ln.get("pct") not in (None, "", 0):
                t = f"{t} {pdf_num(ln['pct'], lang, fmt)} %"
            detail = str(ln.get("detail") or "")
            qty = ln.get("qty")
            unit = str(ln.get("unit") or "")
            unit = str(ln.get("unit_text") or ln.get("unit") or "")
            if "qty_text" in ln:
                qty_s = (str(ln.get("qty_text") or "") + (" " + unit if unit and ln.get("qty_text") else "")).strip()
            else:
                qty_s = (pdf_num(qty, lang, fmt) + (" " + unit if unit else "")) if qty not in (None, "") else ""
            rate_s = str(ln.get("rate_text") or "") if "rate_text" in ln else (money(ln["rate"]) if ln.get("rate") not in (None, "") else "")
            vat_s = (pdf_num(ln["tax_pct"], lang, fmt) + " %") if ln.get("tax_pct") not in (None, "") else ""
            tot_s = str(ln.get("total_text") or "") if ln.get("total_text") else money(ln.get("total") or 0)
            pos_s = str(ln.get("pos") or "") if k == "item" else ""
            t_lines = pdf_wrap(t, body, c_title - 6)
            d_lines = pdf_wrap(detail, 8.4, c_title + c_qty + c_rate + c_vat + c_tot - 6) if detail else []
            h = 8 + len(t_lines) * lh + (len(d_lines) * 8.4 * 1.42 + 2 if d_lines else 0)

            def draw_row(p, y, t_lines=t_lines, d_lines=d_lines, pos_s=pos_s, qty_s=qty_s, rate_s=rate_s, vat_s=vat_s, tot_s=tot_s, h=h):
                yy = y + 4
                p.text(x_pos + 3, yy + 1, pos_s, 8, False, C_INK2)
                for j, s in enumerate(t_lines):
                    p.text(x_title + 3, yy + j * lh, s, body)
                p.text(x_qty, yy, qty_s, 8.8, align="r", width=c_qty - 3)
                p.text(x_rate, yy, rate_s, 8.8, align="r", width=c_rate - 3)
                p.text(x_vat, yy + 1, vat_s, 8, False, C_INK2, align="c", width=c_vat)
                p.text(x_tot, yy, tot_s, 8.8, align="r", width=c_tot - 3)
                dy = yy + len(t_lines) * lh
                for s in d_lines:
                    p.text(x_title + 3, dy, s, 8.4, False, C_INK2)
                    dy += 8.4 * 1.42
                p.line(PDF_L, y + h - 0.5, PDF_L + PDF_CW, y + h - 0.5, 0.5, C_RULE2)
            block(h, draw_row, table=True)
            have_table = True
            last_item_idx = len(blocks) - 1
    if not have_table:
        thead_h = 0

    # -- totals block (right column) + VAT note (left column); never alone on a page
    tot = m.get("totals") or {}
    raw_opt = next((x for x in lines if x.get("kind") == "raw" and x.get("optional")), None)
    raw_inc = next((x for x in lines if x.get("kind") == "raw" and not x.get("optional")), None)
    show_tax = tot.get("show_tax_lines")
    if isinstance(tot.get("rows"), list) and tot["rows"]:  # the print model brings the rows ready-made (first = net total)
        rows = [(str(r[0]), str(r[1]), i == 0) for i, r in enumerate(tot["rows"]) if isinstance(r, (list, tuple)) and len(r) >= 2]
        if show_tax is None:
            show_tax = bool(tot.get("tax_lines"))
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
    notes = [str(x) for x in (tot.get("vat_note"), m.get("fx_note"), m.get("valid_note")) if x and str(x).strip()]
    note = "\n".join(notes)
    tot_w = 190
    left_w = PDF_CW - tot_w - 20
    note_lines = pdf_wrap(note, 8.4, left_w) if note else []
    tot_h = 10 + sum(9 * 1.5 + (6 if g else 0) for _, _, g in rows)
    sum_h = max(tot_h, len(note_lines) * 8.4 * 1.42 + 10)

    def draw_sum(p, y):
        yy = y + 8
        for lab, val, grand in rows:
            if grand:
                p.line(PDF_L + PDF_CW - tot_w, yy, PDF_L + PDF_CW, yy, 1.1, C_INK)
                yy += 5
                p.text(PDF_L + PDF_CW - tot_w, yy, lab, 10.4, True)
                p.text(PDF_L + PDF_CW - tot_w, yy, val, 10.4, True, align="r", width=tot_w)
                yy += 10.4 * 1.5
            else:
                p.text(PDF_L + PDF_CW - tot_w, yy, lab, 9)
                p.text(PDF_L + PDF_CW - tot_w, yy, val, 8.8, align="r", width=tot_w)
                yy += 9 * 1.5
        ny = y + 8
        for s in note_lines:
            p.text(PDF_L, ny, s, 8.4, False, C_INK2)
            ny += 8.4 * 1.42
    block(sum_h, draw_sum, keep_prev=last_item_idx is not None)

    # -- the raw data option (own dashed box below the totals)
    if raw_opt:
        rt = str(raw_opt.get("title") or "")
        rtot = money(raw_opt.get("total") or 0)
        rtot = str(raw_opt.get("total_text") or "") or rtot
        right = rtot + " " + L["net_suffix"]
        if tot.get("net_incl_raw") not in (None, "") and not any(r[0] == (ml.get("incl_raw") or L["incl_raw"]) for r in rows):
            right += " · " + L["incl_raw"] + " " + (tot.get("net_incl_raw_text") or money(tot["net_incl_raw"]))
        rw = pdf_text_width(right, 9)
        rt_lines = pdf_wrap(rt, 9, PDF_CW - rw - 40)
        rd_lines = pdf_wrap(str(raw_opt.get("detail") or ""), 8.4, PDF_CW - 24) if raw_opt.get("detail") else []
        opt_h = 12 + 8 + max(1, len(rt_lines)) * 9 * 1.42 + (len(rd_lines) * 8.4 * 1.42 + 2 if rd_lines else 0) + 8

        def draw_opt(p, y, rt_lines=rt_lines, rd_lines=rd_lines, right=right, opt_h=opt_h):
            p.rect(PDF_L, y + 10, PDF_CW, opt_h - 12, C_RULE, stroke=True, lw=0.6, dash=(2, 2))
            yy = y + 18
            for j, s in enumerate(rt_lines):
                p.text(PDF_L + 10, yy + j * 9 * 1.42, s, 9, bold=(j == 0))
            p.text(PDF_L + PDF_CW - 10, yy, right, 9, align="r")
            yy += len(rt_lines) * 9 * 1.42 + 2
            for s in rd_lines:
                p.text(PDF_L + 10, yy, s, 8.4, False, C_INK2)
                yy += 8.4 * 1.42
        block(opt_h, draw_opt)

    # -- rights block (not torn)
    rights = m.get("rights") or {}
    r_rows = [(str(r[0]), str(r[1])) for r in (rights.get("rows") or []) if isinstance(r, (list, tuple)) and len(r) >= 2 and str(r[1]).strip()]
    if str(rights.get("exceptions") or "").strip():
        r_rows.append((str(ml.get("rights_exceptions") or ("Ausnahmen" if lang == "de" else "Exceptions")), str(rights["exceptions"])))
    if rights.get("exclusive"):
        r_rows.append((str(ml.get("rights_exclusive") or ("Exklusiv" if lang == "de" else "Exclusive")), "ja" if lang == "de" else "yes"))
    if r_rows or rights.get("note"):
        lab_w = 112
        r_lines = [(a, pdf_wrap(b, 9, PDF_CW - lab_w - 12)) for a, b in r_rows]
        rn_lines = pdf_wrap(str(rights.get("note") or ""), 8.4, PDF_CW) if rights.get("note") else []
        r_h = 14 + 12 + sum(max(1, len(b)) * 9 * 1.45 + 2 for _, b in r_lines) + (len(rn_lines) * 8.4 * 1.42 + 6 if rn_lines else 0)

        def draw_rights(p, y):
            p.text(PDF_L, y + 14, str(rights.get("title") or L["rights"]).upper(), 7.4, True, C_INK2, spacing=0.8)
            yy = y + 26
            for a, b in r_lines:
                p.text(PDF_L, yy, a, 9, False, C_INK2)
                for j, s in enumerate(b):
                    p.text(PDF_L + lab_w, yy + j * 9 * 1.45, s, 9)
                yy += max(1, len(b)) * 9 * 1.45 + 2
            if rn_lines:
                yy += 4
                for s in rn_lines:
                    p.text(PDF_L, yy, s, 8.4, False, C_INK2)
                    yy += 8.4 * 1.42
        block(r_h, draw_rights)

    # -- closing text, signature, order confirmation
    if m.get("closing"):
        ct = str(m["closing"])
        n = len(pdf_wrap(ct, body, PDF_CW))
        block(n * lh + 14, lambda p, y, t=ct: p.para(PDF_L, y + 12, t, body, PDF_CW), keep_next=bool(m.get("signature")))
    if m.get("signature"):
        sg = str(m["signature"])
        sl = [sg, ""] + [str(x) for x in (m.get("signature_name"), co.get("name")) if x]
        block(len(sl) * lh + 14, lambda p, y, sl=sl: [p.text(PDF_L, y + 10 + i * lh, s, body, bold=(i == 2)) for i, s in enumerate(sl)])
    if (m.get("kind") or "offer") == "offer":
        half = (PDF_CW - 28) / 2

        def draw_accept(p, y):
            p.text(PDF_L, y + 16, L["accept"].upper(), 7.4, True, C_INK2, spacing=0.8)
            yl = y + 16 + 40
            p.line(PDF_L, yl, PDF_L + half, yl, 0.6, C_INK)
            p.text(PDF_L, yl + 3, L["place_date"], 7.6, False, C_INK2)
            p.line(PDF_L + half + 28, yl, PDF_L + PDF_CW, yl, 0.6, C_INK)
            p.text(PDF_L + half + 28, yl + 3, L["sign"], 7.6, False, C_INK2)
        block(16 + 40 + 16, draw_accept)

    # -- lay the blocks out on pages
    pages = []
    page = _Page()
    draw_letterhead(page)
    pages.append(page)
    y = PDF_ADDR_TOP
    first_on_page = True
    i = 0
    n_blocks = len(blocks)
    while i < n_blocks:
        b = blocks[i]
        # the group that must stay together with b: keep_next chains forward, keep_prev of the follower
        j = i
        while j + 1 < n_blocks and (blocks[j]["keep_next"] or blocks[j + 1]["keep_prev"]):
            j += 1
        group_h = sum(blocks[k]["h"] for k in range(i, j + 1))
        need = group_h + (thead_h if b["table"] and (first_on_page or not blocks[i - 1]["table"]) else 0)
        if y + need > PDF_BODY_BOTTOM and not first_on_page:
            # does b alone fit together with everything that must precede the break? no: new page
            page = _Page()
            draw_small_head(page)
            pages.append(page)
            y = PDF_NEXT_TOP
            first_on_page = True
            continue
        if b["table"] and (first_on_page or not blocks[i - 1]["table"]):
            draw_thead(page, y)
            y += thead_h
        b["draw"](page, y)
        y += b["h"]
        first_on_page = False
        i += 1
    total = len(pages)
    for n, p in enumerate(pages, 1):
        draw_footer(p, n, total)
    if title_at:  # "Page 1 of n" next to the title, known only now
        title_at["page"].text(PDF_L + PDF_CW, title_at["y"] + 12, L["page"].format(1, total), 8.6, False, C_INK2, align="r")
    return pdf_write(pages, images, title=f"{title} {number}".strip(), author=co.get("name") or "")
