"""2.36.1 (#1021, part D): the PDF of an office document (quotation), written without any PDF library.

Input is the print model of office.docs (odoc_render): a plain dict with the document's texts, lines and totals in the
document's language (DE / EN) -- see office_pdf() below for the keys. Output: the bytes of a PDF/A-3b (PDF 1.7) file with real A4
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
import datetime
import hashlib
import io
import logging
import os
import re
import struct
import zlib

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
           "vat_plus": "zzgl. {0} % MwSt.", "gross": "Gesamt brutto", "incl_raw": "Summe netto mit Option Rohdaten",  # 2.114.4 A (#2275)
           "excl_raw": "Summe ohne Rohdaten", "net_suffix": "netto", "optional": "Optional", "rights": "Rechteübertragung",
           "rights_see": "Rechteübertragung siehe Anhang",  # 2.114.1 C (#2258)
           "accept": "Auftragserteilung", "place_date": "Ort, Datum", "sign": "Unterschrift, Stempel Auftraggeber",
           "page": "Seite {0} von {1}", "contact": "Kontakt", "register": "Register", "bank": "Bank",
           "discount": "Rabatt", "producing": "Producing"},
    "en": {"title": "Quotation", "number": "Quotation No.", "date": "Date", "valid_until": "Valid until",
           "client": "Client", "ref": "Your reference", "project": "Project", "pos": "No.", "service": "Service",
           "qty": "Qty", "rate": "Unit price", "vat": "VAT", "total": "Total", "net": "Net total",
           "vat_plus": "plus {0} % VAT", "gross": "Total incl. VAT", "incl_raw": "Net total with option raw data",
           "excl_raw": "Total excluding raw data", "net_suffix": "net", "optional": "Optional", "rights": "Transfer of rights",
           "rights_see": "Transfer of rights see appendix",  # 2.114.1 C (#2258)
           "accept": "Order confirmation", "place_date": "Place, date", "sign": "Signature, stamp of the client",
           "page": "Page {0} of {1}", "contact": "Contact", "register": "Registration", "bank": "Bank",
           "discount": "Discount", "producing": "Producing"},
}

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


def pdf_encode(s):
    """str -> WinAnsi bytes (cp1252; unknown characters become '?'; a code the font has no glyph for as well)."""
    s = str(s or "").translate(_FALLBACK)
    b = s.encode("cp1252", errors="replace")
    miss = pdf_font(False).missing | pdf_font(True).missing
    if miss and any(ch in miss for ch in b):
        b = bytes(63 if ch in miss else ch for ch in b)
    return b


def pdf_text_width(s, size, bold=False, spacing=0.0):
    """Width of s in points at the given size (plus the character spacing, like the Tc operator)."""
    b = pdf_encode(s)
    tab = pdf_font(bold).widths
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

    def mark(self, word):
        """A light diagonal word across the page (drafts), drawn first so the content stays on top."""
        size = 120
        w = pdf_text_width(word, size, True)
        self.ops.insert(0, f"BT 0.88 0.89 0.91 rg /F2 {size} Tf 0.7071 0.7071 -0.7071 0.7071 {(A4_W - w * 0.7071) / 2 + 40:.2f} "
                           f"{(A4_H - w * 0.7071) / 2 - 60:.2f} Tm <{pdf_encode(word).hex()}> Tj ET")

    def image(self, name, x, y, w, h):
        self.images.add(name)
        self.ops.append(f"q {w:.2f} 0 0 {h:.2f} {x:.2f} {A4_H - y - h:.2f} cm /{name} Do Q")


def qac_sig_block_h(rows):
    """2.99.0 C (#2195): the height of the signature box of qac_sig_block for rows."""
    return 16 + 14 + len(rows) * 12 + 18


def qac_sig_block(p, y, rows, head, foot, accent):
    """2.99.0 C (#2195): the box of a simple electronic signature at y (the signed document of office.doctpl, the
    quotation accepted online): head in the accent colour, rows [(label, value)], a closing line."""
    p.rect(PDF_L, y, PDF_CW, qac_sig_block_h(rows), C_RULE, stroke=True, lw=0.6)
    p.text(PDF_L + 10, y + 9, head.upper(), 7.4, True, accent, spacing=0.8)
    yy = y + 26
    for a, b in rows:
        p.text(PDF_L + 10, yy, a, 8.4, False, C_INK2)
        p.text(PDF_L + 120, yy, b, 8 if len(b) > 40 else 8.6, True, C_INK)
        yy += 12
    p.text(PDF_L + 10, yy + 2, foot, 7.6, False, C_INK2)


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


def pdf_write(pages, images, title="", author="", xml=None, meta=None):
    """Serialises pages ([_Page]) and images ({name: (w, h, data)}) into PDF/A-3b bytes (PDF 1.7: embedded TrueType fonts,
    XMP + Info, sRGB OutputIntent, trailer ID). xml: bytes of the e-invoice to embed as factur-x.xml (AFRelationship
    Alternative, fx: XMP schema). meta: {"when": aware datetime, "producer", "creator", "xml_name", "xml_profile", "doc_type"}."""
    meta = meta or {}
    objs = []  # list of bytes bodies; object number = index + 1

    def add(body):
        objs.append(body)
        return len(objs)

    def pstr(s):
        return b"(" + pdf_encode(s).replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"

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
    pages_id = len(objs) + 1 + 2 * len(pages)  # the Pages object comes after all page + content objects
    page_ids = []
    for p in pages:
        content = zlib.compress("\n".join(p.ops).encode("latin-1"), 6)
        cid = add(f"<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n".encode() + content + b"\nendstream")
        xo = " ".join(f"/{n} {img_ids[n]} 0 R" for n in sorted(p.images) if n in img_ids)
        pid = add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {A4_W:.2f} {A4_H:.2f}] "
                  f"/Resources << /Font << /F1 {font_ids[False]} 0 R /F2 {font_ids[True]} 0 R >> /XObject << {xo} >> "
                  f"/ProcSet [/PDF /Text /ImageC] >> /Contents {cid} 0 R >>".encode())
        page_ids.append(pid)
    assert len(objs) + 1 == pages_id
    add(f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in page_ids)}] /Count {len(page_ids)} >>".encode())

    # -- PDF/A: output intent (sRGB), XMP, the embedded e-invoice
    when = meta.get("when") or datetime.datetime.now(datetime.timezone.utc).astimezone()
    d_pdf, d_xmp = _pdf_date(when)
    producer = str(meta.get("producer") or "Kalmido")
    creator = str(meta.get("creator") or "Kalmido")
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
    info = add(b"<< /Producer " + pstr(producer) + b" /Creator " + pstr(creator) + b" /Title " + pstr(title) + b" /Author " + pstr(author) +
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


def pdf_footer_cols(co):
    """2.114.4 A (#2271): the footer columns of a printed company (name + address, contact, register, bank; empty
    ones left out) -> [[(line, keep)]]; keep = the line never breaks (address, phone / email, IBAN / BIC / tax number)."""
    co = co or {}
    # 2.99.0 D (#2188): the up to three name lines one under the other; with a long first column (review L3) one line
    nl = [str(x).strip() for x in (co.get("name_lines") or str(co.get("name") or "").split("\n")) if str(x).strip()][:3] or [""]
    head = list(dict.fromkeys(nl + [str(x) for x in (co.get("lines") or [])]))
    if len(nl) > 1 and len(head) > 6:
        head = list(dict.fromkeys([" ".join(nl)] + [str(x) for x in (co.get("lines") or [])]))
    cols = [[(ln, j > 0) for j, ln in enumerate(head)], [(pdf_phone_in(x), True) for x in (co.get("contact_lines") or [])],
            [(str(x), False) for x in (co.get("register_lines") or [])], [(str(x), True) for x in (co.get("bank_lines") or [])]]
    return [c for c in cols if any(ln.strip() for ln, _ in c)]


def bwa_half(ln, fs, bold=False):
    """2.114.4 A (#2271): the narrowest width at which ln takes at most two lines (the wider half of the best split)."""
    ws = ln.split(" ")
    return min([max(pdf_text_width(" ".join(ws[:q]), fs, bold), pdf_text_width(" ".join(ws[q:]), fs, bold)) for q in range(1, len(ws))]
               or [pdf_text_width(ln, fs, bold)])


def bwa_wrap(ln, keep, fs, width, bold=False):
    """2.114.4 A (#2271): a footer line within width: whole when it fits (an unbreakable line always tries so), a
    "Label: value" line breaks after the label first, everything else wraps by words."""
    if pdf_text_width(ln, fs, bold) <= width:
        return [ln]
    if not keep and ": " in ln:
        a, b = ln.split(": ", 1)
        if pdf_text_width(a + ":", fs, bold) <= width and pdf_text_width(b, fs, bold) <= width:
            return [a + ":", b]
    return pdf_wrap(ln, fs, width, bold=bold)


def pdf_draw_footer(p, cols, right=""):
    """2.114.4 A (#2271): the footer of a page: a rule, the columns of pdf_footer_cols and the text bottom right
    (number / page). Widths follow the content: every column gets at least its longest unbreakable line (an IBAN, "E-Mail
    x"), the rest goes to the columns that still wrap; when even that does not fit, the font shrinks a little."""
    top = A4_H - 12 * MM - PDF_FOOT_H
    p.line(PDF_L, top, PDF_L + PDF_CW, top, 0.5, C_RULE)
    if cols:
        free = PDF_CW - 8 * (len(cols) - 1)
        bold = lambda i, j: i == 0 and j == 0  # noqa: E731
        # no break at all when a slightly smaller font allows it, else the narrowest font that keeps every unbreakable line
        for fs, whole in ((6.9, 1), (6.6, 1), (6.3, 1), (6.9, 0), (6.6, 0), (6.3, 0), (6.0, 0)):
            nat = [max(pdf_text_width(ln, fs, bold(i, j)) for j, (ln, _k) in enumerate(c)) + 3 for i, c in enumerate(cols)]
            low = [max(pdf_text_width(ln, fs, bold(i, j)) if k else bwa_half(ln, fs, bold(i, j)) for j, (ln, k) in enumerate(c)) + 3
                   for i, c in enumerate(cols)]
            if whole and sum(nat) > free:
                continue
            if sum(nat) <= free:
                cws = [w + (free - sum(nat)) / len(cols) for w in nat]
            elif sum(low) <= free:
                want = [a - b for a, b in zip(nat, low)]
                cws = [b + (free - sum(low)) * w / sum(want) for b, w in zip(low, want)]
            else:
                cws = [free * b / sum(low) for b in low]
            shown = [[(w, j == 0) for j, (ln, k) in enumerate(c)
                      for w in bwa_wrap(ln, k, fs, cws[i] - 2, bold(i, j))]
                     for i, c in enumerate(cols)]
            if sum(low) <= free and max(len(x) for x in shown) <= 6:
                break
        x = PDF_L
        for i, c in enumerate(shown):
            if i:
                x += cws[i - 1] + 8
            yy = top + 5
            for ln, first in c[:6]:
                p.text(x, yy, ln, fs, bold=(i == 0 and first), color=C_INK if (i == 0 and first) else C_INK2)
                yy += fs * 1.39
    if right:
        p.text(PDF_L + PDF_CW, A4_H - 9 * MM, right, 6.8, False, C_INK2, align="r")


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
        w, h = logo[0], logo[1]
        sc = min(max_w / w, max_h / h)
        return w * sc, h * sc

    # -- letterhead (page 1) and the small head (following pages)
    def draw_letterhead(p):
        if logo:
            w, h = logo_box(PDF_LOGO_MAX_W, PDF_LOGO_MAX_H)
            p.image("Logo", A4_W - PDF_R - w, PDF_TOP + 2 * MM, w, h)
        else:
            nl = co_lines or [""]  # 2.99.0 D (#2188): up to three name lines, one under the other
            for i, ln in enumerate(nl):
                p.text(PDF_L + PDF_CW, PDF_TOP + 4 * MM + i * 18, ln, 15, True, C_INK, align="r", spacing=1.2)
            p.rect(A4_W - PDF_R - 12 * MM, PDF_TOP + 4 * MM + 24 + (len(nl) - 1) * 18, 12 * MM, 2.2, accent)
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

    # -- footer (every page), four columns; empty ones are left out (2.114.4 A (#2271): shared with the document templates)
    cols = pdf_footer_cols(co)

    def draw_footer(p, n, total):
        # 2.114.4 A (#2282): the page count only from two pages on, the number stays
        pdf_draw_footer(p, cols, " · ".join(x for x in (number, L["page"].format(n, total) if total >= 2 else "") if x))

    # -- blocks: (height, draw(page, y), keep_next, keep_prev, table)
    blocks = []

    def block(h, fn, keep_next=False, keep_prev=False, table=False, brk=False):  # 2.47.0 (#1215): brk = starts a new page
        blocks.append({"h": h, "draw": fn, "keep_next": keep_next, "keep_prev": keep_prev, "table": table, "brk": brk})

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
        if m.get("client") and str(m["client"]).strip() and not str(rc.get("name") or "").strip():  # 2.114.4 A (#2277): only without a recipient name
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
    if rc.get("street") and not any(str(rc["street"]).strip() in ln for ln in addr_lines):  # 2.38.0: billing fields without free lines
        addr_lines += [str(x) for x in (rc["street"], " ".join(str(y) for y in (rc.get("zip"), rc.get("city")) if y)) if str(x).strip()]
        if rc.get("country") and str(rc["country"]).strip().upper() != str((m.get("sender_fields") or {}).get("country") or "DE").upper():
            addr_lines.append(str(rc["country"]))

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

    def draw_title(p, y):
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

    def table_rows(lines):  # 2.47.0 (#1215): the rows of the title page and of every printed part
        nonlocal have_table, last_item_idx
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
                detail = str(ln.get("detail") or "") if k != "producing" else ""  # 2.114.4 A (#2276): the formula only in the app
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
                pos_s = str(ln.get("pos") or "") if k in ("item", "producing") else ""  # 2.114.4 A (#2276): producing numbered too
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
        block(20, draw_rem_head, keep_next=True)
        for rr in rem["rows"]:
            if not isinstance(rr, dict):
                continue
            cells = [str(rr.get("number") or ""), str(rr.get("date_text") or ""), str(rr.get("due_text") or ""), str(rr.get("open_text") or money(rr.get("open") or 0))]

            def draw_rem_row(p, y, cells=cells):
                for j, (x, v) in enumerate(zip(xs, cells)):
                    p.text(x + 3, y + 4, v, body, align="l" if j == 0 else "r", width=(c_r1 if j == 0 else c_r4) - 6)
                p.line(PDF_L, y + 8 + lh - 0.5, PDF_L + PDF_CW, y + 8 + lh - 0.5, 0.5, C_RULE2)
            block(8 + lh, draw_rem_row)
        last_item_idx = len(blocks) - 1
    if not have_table:
        thead_h = 0

    # -- totals block (right column) + VAT note (left column); never alone on a page
    tot = m.get("totals") or {}
    raw_opt = next((x for x in lines if x.get("kind") == "raw" and x.get("optional")), None)
    raw_inc = next((x for x in lines if x.get("kind") == "raw" and not x.get("optional")), None)
    show_tax = tot.get("show_tax_lines")
    if isinstance(tot.get("rows"), list) and tot["rows"]:  # the print model brings the rows ready-made (first = net total)
        given = [r for r in tot["rows"] if isinstance(r, (list, tuple)) and len(r) >= 2]
        # 2.38.0: an invoice's rows already end with the tax lines and the grand total (show_tax_lines true) -> last row bold
        rows = [(str(r[0]), str(r[1]), i == 0 or ((bool(show_tax) or (m.get("kind") or "offer") != "offer") and len(given) > 1 and i == len(given) - 1))
                for i, r in enumerate(given)]
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
    notes = [str(x) for x in (tot.get("vat_note"), m.get("vat_note_text"), tot.get("fx_line") or m.get("fx_note"), m.get("valid_note"))
             if x and str(x).strip()]
    notes = list(dict.fromkeys(notes))
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

    # -- 2.38.0 (#1021): payment information of an invoice (due text + bank line) right below the totals
    pay = m.get("payment") if isinstance(m.get("payment"), dict) else None
    if pay and (pay.get("text") or pay.get("iban")):
        iban = str(pay.get("iban") or "").replace(" ", "")
        bank = " · ".join(x for x in (str(pay.get("bank_name") or ""), ("IBAN " + " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))) if iban else "",
                                     ("BIC " + str(pay["bic"])) if pay.get("bic") else "") if x)
        pt_lines = pdf_wrap(str(pay.get("text") or ""), body, PDF_CW) if pay.get("text") else []
        pb_lines = pdf_wrap(bank, 8.4, PDF_CW) if bank else []
        pay_h = 6 + len(pt_lines) * lh + (len(pb_lines) * 8.4 * 1.42 + 2 if pb_lines else 0)

        def draw_pay(p, y, pt_lines=pt_lines, pb_lines=pb_lines):
            yy = y + 4
            for t_ in pt_lines:
                p.text(PDF_L, yy, t_, body)
                yy += lh
            for t_ in pb_lines:
                p.text(PDF_L, yy, t_, 8.4, False, C_INK2)
                yy += 8.4 * 1.42
        block(pay_h, draw_pay, keep_prev=True)

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

    # -- rights block (not torn); 2.114.1 C (#2258): printed as an appendix on its own last page, see below
    bfc_rights, bfc_seen = [], []
    rights = m.get("rights") or {}
    r_rows = [(str(r[0]), str(r[1])) for r in (rights.get("rows") or []) if isinstance(r, (list, tuple)) and len(r) >= 2 and str(r[1]).strip()]
    if str(rights.get("exceptions") or "").strip():
        r_rows.append((str(ml.get("rights_exceptions") or ("Ausnahmen" if lang == "de" else "Exceptions")), str(rights["exceptions"])))
    if rights.get("exclusive"):
        r_rows.append((str(ml.get("rights_exclusive") or ("Exklusiv" if lang == "de" else "Exclusive")), "ja" if lang == "de" else "yes"))
    if r_rows or rights.get("note"):
        lab_w = 112
        r_lines = [(a, pdf_wrap(b, 9, PDF_CW - lab_w - 12)) for a, b in r_rows]
        rn_lines = pdf_wrap(str(rights.get("note") or ""), 8, PDF_CW) if rights.get("note") else []  # 2.114.1 C (#2258): small note
        r_h = 14 + sum(max(1, len(b)) * 9 * 1.6 + 10 for _, b in r_lines) + (len(rn_lines) * 8 * 1.42 + 14 if rn_lines else 0)

        def draw_rights(p, y):  # 2.114.1 C (#2258): the title is the appendix heading, rows with more air
            yy = y + 14
            for a, b in r_lines:
                p.text(PDF_L, yy, a, 9, False, C_INK2)
                for j, s in enumerate(b):
                    p.text(PDF_L + lab_w, yy + j * 9 * 1.6, s, 9)
                yy += max(1, len(b)) * 9 * 1.6 + 10
            if rn_lines:
                yy += 12
                for s in rn_lines:
                    p.text(PDF_L, yy, s, 8, False, C_INK2)
                    yy += 8 * 1.42
        bfc_rights.append((r_h, draw_rights))

    def bfc_see_ref():  # 2.114.1 C (#2258): one short line above the signature pointing to the rights appendix
        if bfc_rights and not bfc_seen:
            bfc_seen.append(1)
            block(lh + 8, lambda p, y, t=str(ml.get("rights_see") or L["rights_see"]): p.text(PDF_L, y + 10, t, 8.6, False, C_INK2), keep_next=True)

    # -- closing text, signature, order confirmation
    if m.get("closing"):
        ct = str(m["closing"])
        n = len(pdf_wrap(ct, body, PDF_CW))
        block(n * lh + 14, lambda p, y, t=ct: p.para(PDF_L, y + 12, t, body, PDF_CW), keep_next=bool(m.get("signature")))
    if m.get("signature") or (m.get("kind") or "offer") == "offer":
        bfc_see_ref()
    if m.get("signature"):
        sg = str(m["signature"])
        sl = [sg, ""] + [str(x) for x in (m.get("signature_name"), co.get("name")) if x]
        block(len(sl) * lh + 14, lambda p, y, sl=sl: [p.text(PDF_L, y + 10 + i * lh, s, body, bold=(i == 2)) for i, s in enumerate(sl)])
    acc = m.get("accepted") if isinstance(m.get("accepted"), dict) else None
    if (m.get("kind") or "offer") == "offer" and acc:  # 2.99.0 C (#2195): accepted online -> the signature box instead of the empty lines
        acc_rows = [(str(x[0]), str(x[1])) for x in acc.get("rows") or [] if isinstance(x, (list, tuple)) and len(x) >= 2]
        block(8 + qac_sig_block_h(acc_rows), lambda p, y: qac_sig_block(p, y + 8, acc_rows, str(acc.get("head") or ""), str(acc.get("foot") or ""), accent))
    elif (m.get("kind") or "offer") == "offer" and m.get("accept_on", 1):  # 2.114.4 B (#2270): the block can be switched off
        half = (PDF_CW - 28) / 2

        def draw_accept(p, y):
            p.text(PDF_L, y + 16, L["accept"].upper(), 7.4, True, C_INK2, spacing=0.8)
            yl = y + 16 + 40
            p.line(PDF_L, yl, PDF_L + half, yl, 0.6, C_INK)
            p.text(PDF_L, yl + 3, L["place_date"], 7.6, False, C_INK2)
            p.line(PDF_L + half + 28, yl, PDF_L + PDF_CW, yl, 0.6, C_INK)
            p.text(PDF_L + half + 28, yl + 3, L["sign"], 7.6, False, C_INK2)
        block(16 + 40 + 16, draw_accept)
    bfc_see_ref()  # no signature, no order confirmation: the line ends the main pages

    # -- 2.47.0 (#1215): every printed part of a quotation on its own page(s): part title + number, its rows, its sums
    for part in m.get("parts") or []:
        if not isinstance(part, dict):
            continue
        ptitle = str(part.get("title") or "")
        psub = " · ".join(x for x in (f"{L['number']} {number}" if number else "", str(m.get("project_title") or "")) if x)

        def draw_part_head(p, y, ptitle=ptitle, psub=psub):
            p.text(PDF_L, y + 6, ptitle.upper(), 14, True, C_INK, spacing=0.8)
            p.line(PDF_L, y + 6 + 20, PDF_L + 14 * MM, y + 6 + 20, 1.6, accent)
            if psub:
                p.text(PDF_L + PDF_CW, y + 8, psub, 8.6, False, C_INK2, align="r")
        block(34, draw_part_head, keep_next=True, brk=True)
        for hr in part.get("head") or []:
            if isinstance(hr, (list, tuple)) and len(hr) >= 2:
                block(lh, lambda p, y, a=str(hr[0]), b=str(hr[1]): (p.text(PDF_L, y, a, 9, False, C_INK2), p.text(PDF_L + 112, y, b, 9)), keep_next=True)
        table_rows([x for x in (part.get("lines") or []) if isinstance(x, dict)])
        prow = [(str(r[0]), str(r[1])) for r in ((part.get("totals") or {}).get("rows") or []) if isinstance(r, (list, tuple)) and len(r) >= 2]
        if prow:
            def draw_part_sum(p, y, prow=prow):
                yy = y + 8
                for j, (lab, val) in enumerate(prow):
                    if j == 0:
                        p.line(PDF_L + PDF_CW - 190, yy, PDF_L + PDF_CW, yy, 1.1, C_INK)
                        yy += 5
                    p.text(PDF_L + PDF_CW - 190, yy, lab, 10.4 if j == 0 else 9, j == 0)
                    p.text(PDF_L + PDF_CW - 190, yy, val, 10.4 if j == 0 else 8.8, j == 0, align="r", width=190)
                    yy += (10.4 if j == 0 else 9) * 1.5
            block(14 + sum((10.4 if j == 0 else 9) * 1.5 for j in range(len(prow))) + 5, draw_part_sum, keep_prev=True)

    # -- 2.114.1 C (#2258): the rights block as an appendix on its own last page, after the parts
    if bfc_rights:
        rtitle = str(rights.get("title") or L["rights"])
        rsub = " · ".join(x for x in (f"{L['number']} {number}" if number else "", str(m.get("project_title") or "")) if x)

        def bfc_draw_rights_head(p, y, rtitle=rtitle, rsub=rsub):
            p.text(PDF_L, y + 6, rtitle.upper(), 14, True, C_INK, spacing=0.8)
            p.line(PDF_L, y + 6 + 20, PDF_L + 14 * MM, y + 6 + 20, 1.6, accent)
            if rsub:
                p.text(PDF_L + PDF_CW, y + 8, rsub, 8.6, False, C_INK2, align="r")
        block(34 + 12, bfc_draw_rights_head, keep_next=True, brk=True)
        block(*bfc_rights[0])

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
        if b.get("brk") and not first_on_page:  # 2.47.0 (#1215): a part starts on a new page
            page = _Page()
            draw_small_head(page)
            pages.append(page)
            y = PDF_NEXT_TOP
            first_on_page = True
            continue
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
    # 2.114.4 A (#2273): no "Page 1 of n" next to the title any more, the footer has it
    if str(m.get("draft_mark") or "").strip():
        for p in pages:
            p.mark(str(m["draft_mark"]).strip())
    return pdf_write(pages, images, title=f"{title} {number}".strip(), author=co.get("name") or "", xml=xml, meta=meta)
