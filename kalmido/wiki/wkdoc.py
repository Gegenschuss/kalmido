"""2.1151.0 D (#5524): one knowledge page as a PDF or a Word file (.docx), for texts that go out (decision of 10.11.2026: no
word processor of its own, the Markdown page is the source).

GET /api/wiki/pages/<id>/export?format=pdf|docx[&style=] -- whoever reads the page (wiki_need: the space's role or a share of
its folders) gets the file. The reading style (wkstyle.WIKI_STYLES; the browser sends the one it shows, else the space's
default) sets the look: Clear, Book (wide margins, more line spacing, a serif in Word), Compact (dense) or Notepad (ruled
lines). A page of a space with the lock is refused like the space's export (wke_guard 409 wiki_e2e): the browser makes
its file there (static/js/wkdoc.js). No library: the PDF is drawn with the office's own writer (office/pdf.py: _Page,
pdf_write, fonts, pictures), the .docx is a ZIP of WordprocessingML written by hand.

What is understood of the Markdown: headings, paragraphs, bold / italic / struck / code, links (web and mail addresses are
links, the others text), [[page]] links as their text, lists (also nested and with ticks), quotes, code blocks, rules,
tables and pictures: a picture of the page itself (/api/wiki/files/<id>, not SVG, not found infected) is embedded, any
other one (another page's, a web address -- the server fetches nothing) is written as its text."""
import io
import os
import re
import zipfile
from xml.sax.saxutils import escape as _xesc

from flask import request, send_file

from ..core.config import app, ATT_DIR
from ..core.i18n import tr
from ..core.errors import BadInput
from ..accounts.session import me
from ..core.db import db, now_utc
from ..core.orgcrypt import oc_read_file
from .pages import wiki_need
from .wikie2e import wke_guard
from .wkhist import wkh_body
from .wkstyle import WIKI_STYLES, wst_get

WKD_FORMATS = ("pdf", "docx")
WKD_IMG_MAX = 40                 # pictures embedded per file (more: as their text)
WKD_IMG_BYTES = 40 * 1024 * 1024  # ... and their stored bytes in all
WKD_URL_OK = re.compile(r"(?i)^(https?://|mailto:)[^\s<>\"]+$")
WKD_FILE_RE = re.compile(r"^/api/wiki/files/(\d{1,15})(?:/|$)")


# ---- Markdown -> blocks ---------------------------------------------------------------------------------------------
# a run = (text, style, href): style a frozenset of "b" / "i" / "s" / "c" (code); href '' or a web / mail address
_INLINE = re.compile(
    r"(?P<esc>\\[\\`*_{}\[\]()#+\-.!|~>])"
    r"|(?P<code>`+)(?P<codet>.+?)(?P=code)"
    r"|!\[(?P<ialt>[^\]\n]*)\]\((?P<isrc>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"|\[\[(?P<wl>[^\]|\n]+)(?:\|(?P<wlt>[^\]\n]+))?\]\]"
    r"|\[(?P<lt>[^\]\n]+)\]\((?P<lh>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"|<(?P<auto>(?:https?://|mailto:)[^>\s]+)>"
    r"|(?P<bare>https?://[^\s<>()\[\]]+[^\s<>()\[\].,;:!?'\"])"
    r"|(?P<br><br\s*/?>)"
    r"|\*\*(?=\S)(?P<b1>.+?)(?<=\S)\*\*"
    r"|(?<!\w)__(?=\S)(?P<b2>.+?)(?<=\S)__(?!\w)"
    r"|~~(?=\S)(?P<st>.+?)(?<=\S)~~"
    r"|\*(?=[^\s*])(?P<i1>.+?)(?<=[^\s*])\*"
    r"|(?<!\w)_(?=[^\s_])(?P<i2>.+?)(?<=[^\s_])_(?!\w)")


def wkd_inline(s, style=frozenset(), href=""):
    """The runs of one line / paragraph of Markdown."""
    out, pos = [], 0
    s = str(s or "")
    for m in _INLINE.finditer(s):
        if m.start() > pos:
            out.append((s[pos:m.start()], style, href))
        pos = m.end()
        g = m.groupdict()
        if g["esc"]:
            out.append((g["esc"][1], style, href))
        elif g["code"]:
            out.append((g["codet"].strip() if g["codet"].strip() else g["codet"], style | {"c"}, href))
        elif g["isrc"] is not None:
            out.append((g["ialt"] or g["isrc"].rsplit("/", 1)[-1], style | {"i"}, g["isrc"] if WKD_URL_OK.match(g["isrc"]) else href))
        elif g["wl"]:
            t = (g["wlt"] or g["wl"]).strip()
            out.append((t if not t.startswith("_attachments/") else t.rsplit("/", 1)[-1], style, href))
        elif g["lt"]:
            h = g["lh"] if WKD_URL_OK.match(g["lh"]) else href
            out.extend(wkd_inline(g["lt"], style, h))
        elif g["auto"] or g["bare"]:
            u = g["auto"] or g["bare"]
            out.append((u[7:] if u.lower().startswith("mailto:") else u, style, u))
        elif g["br"]:
            out.append(("\n", style, href))
        elif g["b1"] is not None or g["b2"] is not None:
            out.extend(wkd_inline(g["b1"] if g["b1"] is not None else g["b2"], style | {"b"}, href))
        elif g["st"] is not None:
            out.extend(wkd_inline(g["st"], style | {"s"}, href))
        else:
            out.extend(wkd_inline(g["i1"] if g["i1"] is not None else g["i2"], style | {"i"}, href))
    if pos < len(s):
        out.append((s[pos:], style, href))
    return [r for r in out if r[0]]


def wkd_plain(runs):
    return "".join(r[0] for r in runs)


_LI = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
_HR = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
_HEAD = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^ {0,3}(```+|~~~+)\s*([\w+-]*)")
_TSEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
_IMG_LINE = re.compile(r"^\s*!\[([^\]\n]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)\s*$")


def _cells(line):
    t = line.strip()
    if t.startswith("|"):
        t = t[1:]
    if t.endswith("|") and not t.endswith("\\|"):
        t = t[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", t)]


def wkd_blocks(text):
    """Markdown -> [block]: ("h", level, runs) | ("p", runs) | ("li", ordered, depth, number, tick (None / bool), runs) |
    ("quote", runs) | ("code", text) | ("hr",) | ("table", [[runs]], head row?) | ("img", src, alt)."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    m = re.match(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|\Z)", text, re.S)  # the page's attributes (wiki_frontmatter) stay out
    if m:
        text = text[m.end():]
    lines, out, para, i = text.split("\n"), [], [], 0

    def flush():
        if para:
            out.append(("p", wkd_inline(" ".join(x.strip() for x in para))))
            para.clear()
    while i < len(lines):
        ln = lines[i]
        f = _FENCE.match(ln)
        if f:
            flush()
            mark, body = f.group(1), []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(mark[:3]):
                body.append(lines[i])
                i += 1
            out.append(("code", "\n".join(body)))
            i += 1
            continue
        if not ln.strip():
            flush()
            i += 1
            continue
        h = _HEAD.match(ln)
        if h:
            flush()
            out.append(("h", len(h.group(1)), wkd_inline(h.group(2))))
            i += 1
            continue
        if _HR.match(ln) and not (para and set(ln.strip()) == {"-"}):
            flush()
            out.append(("hr",))
            i += 1
            continue
        if para and set(ln.strip()) <= {"=", "-"} and len(ln.strip()) >= 2:  # a Setext heading
            out.append(("h", 1 if ln.strip()[0] == "=" else 2, wkd_inline(" ".join(x.strip() for x in para))))
            para.clear()
            i += 1
            continue
        if "|" in ln and i + 1 < len(lines) and _TSEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            flush()
            rows = [_cells(ln)]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            n = max(len(r) for r in rows)
            out.append(("table", [[wkd_inline(c) for c in r + [""] * (n - len(r))] for r in rows], True))
            continue
        if ln.lstrip().startswith(">"):
            flush()
            q = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                q.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            for part in re.split(r"\n\s*\n", "\n".join(q)):
                if part.strip():
                    out.append(("quote", wkd_inline(" ".join(x.strip().lstrip(">").strip() for x in part.split("\n")))))
            continue
        li = _LI.match(ln)
        if li:
            flush()
            ind = len(li.group(1).replace("\t", "    "))
            txt = li.group(3)
            i += 1
            while i < len(lines) and lines[i].strip() and not _LI.match(lines[i]) and lines[i].startswith((" ", "\t")) \
                    and not _FENCE.match(lines[i]):
                txt += " " + lines[i].strip()
                i += 1
            t = _TASK.match(txt)
            num = li.group(2)
            out.append(("li", num[0].isdigit(), min(3, ind // 2), int(num[:-1]) if num[0].isdigit() else 0,
                        (t.group(1) != " ") if t else None, wkd_inline(t.group(2) if t else txt)))
            continue
        im = _IMG_LINE.match(ln)
        if im:
            flush()
            out.append(("img", im.group(2), im.group(1)))
            i += 1
            continue
        para.append(ln)
        i += 1
    flush()
    return out


# ---- the page's pictures ---------------------------------------------------------------------------------------------
def wkd_images(c, page, blocks):
    """{src: (stored bytes, mime)} of the block pictures that are files of this very page, readable, not SVG, not found
    infected; at most WKD_IMG_MAX / WKD_IMG_BYTES. Anything else stays text."""
    from ..files.upsafe import up_marks
    out, total = {}, 0
    for b in blocks:
        if b[0] != "img" or b[1] in out or len(out) >= WKD_IMG_MAX:
            continue
        m = WKD_FILE_RE.match(b[1])
        if not m:
            continue
        f = c.execute("SELECT * FROM wiki_files WHERE id=? AND page_id=? AND deleted_at IS NULL", (int(m.group(1)), page["id"])).fetchone()
        if not f or not str(f["mime"] or "").startswith("image/") or "svg" in str(f["mime"]):
            continue
        if (up_marks(c, "wiki", [f["id"]]).get(f["id"]) or {}).get("scan") == "infected":  # as wka_get (sc_guard): never opened
            continue
        if total + int(f["size"] or 0) > WKD_IMG_BYTES:
            continue
        try:
            raw = oc_read_file(c, os.path.join(ATT_DIR, f["path"]))
        except Exception:  # noqa: BLE001  (a missing / unreadable file: the picture stays text)
            continue
        total += len(raw)
        out[b[1]] = (raw, f["mime"])
    return out


# ---- the look per reading style --------------------------------------------------------------------------------------
MM = 72 / 25.4
WKD_LOOK = {  # size (pt), line height factor, side margin (mm), gap after a paragraph (factor of the size), Word font
    "": {"fs": 10.5, "lh": 1.45, "side": 22, "gap": 0.6, "font": "Arial"},
    "book": {"fs": 11.0, "lh": 1.65, "side": 32, "gap": 0.75, "font": "Georgia"},
    "compact": {"fs": 9.0, "lh": 1.3, "side": 16, "gap": 0.35, "font": "Arial"},
    "notepad": {"fs": 10.5, "lh": 1.6, "side": 24, "gap": 0.6, "font": "Arial"},
}
WKD_HEAD = (1.9, 1.5, 1.28, 1.14, 1.05, 1.0)  # heading sizes as factors of the text size
C_LINK = "#1d4ed8"
C_CODEBG = "#f1f3f6"
SHD = '<w:shd w:val="clear" w:color="auto" w:fill="F1F3F6"/>'
EXT = ' TargetMode="External"'


def wkd_look(style):
    return WKD_LOOK.get(style or "", WKD_LOOK[""])


# ---- PDF -------------------------------------------------------------------------------------------------------------
def wkd_pdf(title, blocks, images, style=""):
    """The PDF bytes (office/pdf.py writes them: A4, embedded fonts, PDF/A-3b)."""
    from ..office.pdf import A4_H, A4_W, C_INK, C_INK2, C_RULE, C_RULE2, _Page, _rgb, pdf_encode, pdf_image_object, pdf_text_width, pdf_write
    lk = wkd_look(style)
    fs, L = lk["fs"], lk["side"] * MM
    W = A4_W - 2 * L
    TOP, BOT = 22 * MM, A4_H - 20 * MM
    pages, imgs, img_names = [], {}, {}
    st = {"p": None, "y": TOP}

    def new_page():
        p = _Page()
        pages.append(p)
        st["p"], st["y"] = p, TOP
        return p

    def room(h):
        if st["y"] + h > BOT and st["y"] > TOP + 1:
            new_page()

    def draw(p, x, y, s, size, sty, color):
        b = "b" in sty
        if "c" in sty:
            p.rect(x - 0.8, y - 0.6, pdf_text_width(s, size, b) + 1.6, size * 1.2, C_CODEBG)
        r, g, bl = _rgb(color)
        skew = " 1 0 0.21 1" if "i" in sty else " 1 0 0 1"
        p.ops.append(f"BT {r:.3f} {g:.3f} {bl:.3f} rg /{'F2' if b else 'F1'} {size:.2f} Tf{skew} {x:.2f} {p.H - y - size * 0.78:.2f} Tm "
                     f"<{pdf_encode(s).hex()}> Tj ET")
        w = pdf_text_width(s, size, b)
        if "s" in sty:
            p.line(x, y + size * 0.5, x + w, y + size * 0.5, 0.6, color)
        return w

    def lines_of(runs, size, width):
        """runs -> lines of [(text, style, href)] that fit width (words kept whole, an overlong one cut)."""
        toks = []
        for t, sty, href in runs:
            for k, part in enumerate(t.split("\n")):
                if k:
                    toks.append(("\n", sty, href))
                toks.extend((w, sty, href) for w in re.split(r"(\s+)", part) if w)
        out, cur, cw = [], [], 0.0
        for t, sty, href in toks:
            if t == "\n":
                out.append(cur)
                cur, cw = [], 0.0
                continue
            sp = t.isspace()
            if sp:
                t = " "
                if not cur:
                    continue
            w = pdf_text_width(t, size, "b" in sty)
            if cw + w > width and not sp and cur:
                while cur and cur[-1][0] == " ":
                    cw -= pdf_text_width(" ", size, "b" in cur[-1][1])
                    cur.pop()
                out.append(cur)
                cur, cw = [], 0.0
            while w > width and len(t) > 1:  # a word longer than the line: cut by characters
                k = len(t)
                while k > 1 and pdf_text_width(t[:k], size, "b" in sty) > width - cw:
                    k -= 1
                out.append(cur + [(t[:k], sty, href)])
                cur, cw, t = [], 0.0, t[k:]
                w = pdf_text_width(t, size, "b" in sty)
            cur.append((t, sty, href))
            cw += w
        if cur:
            out.append(cur)
        merged = []  # neighbours of the same look drawn as one piece
        for ln in out:
            m = []
            for t, sty, href in ln:
                if m and m[-1][1] == sty and m[-1][2] == href:
                    m[-1] = (m[-1][0] + t, sty, href)
                else:
                    m.append((t, sty, href))
            merged.append(m)
        return merged or [[]]

    def flow(runs, x, width, size, color=C_INK, lh=None, bold=False):
        """Draws runs from st['y'] on (breaking pages); returns nothing, st['y'] below the last line."""
        lh = lh or size * lk["lh"]
        for ln in lines_of([(t, s | ({"b"} if bold else set()), h) for t, s, h in runs], size, width):
            room(lh)
            p, xx = st["p"], x
            for t, sty, href in ln:
                w = draw(p, xx, st["y"] + (lh - size * 1.2) / 2, t, size, sty, C_LINK if href else color)
                if href and t.strip():
                    p.line(xx, st["y"] + (lh + size) / 2, xx + w, st["y"] + (lh + size) / 2, 0.4, C_LINK)
                    try:
                        p.uri(xx, st["y"], w, lh, href)
                    except ValueError:
                        pass
                xx += w
            st["y"] += lh

    new_page()
    first = blocks[0] if blocks else None
    if not (first and first[0] == "h" and wkd_plain(first[2]).strip().lower() == title.strip().lower()):
        flow([(title, frozenset({"b"}), "")], L, W, fs * WKD_HEAD[0], lh=fs * WKD_HEAD[0] * 1.3)
        st["y"] += fs * 0.8
    gap = fs * lk["gap"]
    for b in blocks:
        k = b[0]
        if k == "h":
            size = fs * WKD_HEAD[b[1] - 1]
            st["y"] += size * 0.5 if st["y"] > TOP + 1 else 0
            room(size * 1.3 + fs * lk["lh"] * 2)  # a heading never stays alone at the bottom
            flow(b[2], L, W, size, bold=True, lh=size * 1.3)
            if b[1] <= 2:
                st["y"] += 2
                st["p"].line(L, st["y"], L + W, st["y"], 0.5, C_RULE2)
            st["y"] += gap * 0.7
        elif k == "p":
            flow(b[1], L, W, fs)
            st["y"] += gap
        elif k == "li":
            ordered, depth, num, tick, runs = b[1:]
            ind = L + depth * 6 * MM
            mark = (f"{num}." if ordered else "•") if tick is None else ("[x]" if tick else "[ ]")
            room(fs * lk["lh"])
            draw(st["p"], ind, st["y"] + (fs * lk["lh"] - fs * 1.2) / 2, mark, fs, frozenset(), C_INK2)
            flow(runs, ind + 6 * MM, W - (ind - L) - 6 * MM, fs)
            st["y"] += gap * 0.3
        elif k == "quote":
            y0, p0 = st["y"], st["p"]
            flow(b[1], L + 5 * MM, W - 5 * MM, fs, color=C_INK2)
            if st["p"] is p0:
                p0.rect(L + 1, y0, 2, st["y"] - y0, C_RULE)
            st["y"] += gap
        elif k == "code":
            size = fs * 0.88
            lh = size * 1.35
            for ln in (b[1].split("\n") or [""]):
                for part in lines_of([(ln.replace("\t", "    ") or " ", frozenset(), "")], size, W - 6 * MM):
                    room(lh)
                    st["p"].rect(L, st["y"], W, lh, C_CODEBG)
                    t = "".join(x[0] for x in part)
                    if t.strip():
                        draw(st["p"], L + 3 * MM, st["y"] + (lh - size * 1.2) / 2, t, size, frozenset(), C_INK)
                    st["y"] += lh
            st["y"] += gap
        elif k == "hr":
            room(fs)
            st["p"].line(L, st["y"] + fs / 2, L + W, st["y"] + fs / 2, 0.6, C_RULE)
            st["y"] += fs + gap
        elif k == "table":
            rows, n = b[1], max(len(r) for r in b[1])
            size, pad = fs * 0.92, 2.5
            nat = [max(min(pdf_text_width(wkd_plain(r[j]), size, True), W * 0.6) for r in rows) + 2 * pad for j in range(n)]
            floor = W / n / 3
            nat = [max(floor, x) for x in nat]
            cw = [x * W / sum(nat) for x in nat] if sum(nat) > W else nat
            lh = size * 1.35
            for ri, r in enumerate(rows):
                cells = [lines_of([(t, s | ({"b"} if ri == 0 else set()), h) for t, s, h in r[j]], size, cw[j] - 2 * pad) for j in range(n)]
                h = max(len(x) for x in cells) * lh + 2 * pad
                room(h)
                p, x = st["p"], L
                if ri == 0:
                    p.rect(L, st["y"], sum(cw), h, C_CODEBG)
                for j in range(n):
                    yy = st["y"] + pad
                    for ln in cells[j]:
                        xx = x + pad
                        for t, sty, href in ln:
                            xx += draw(p, xx, yy + (lh - size * 1.2) / 2, t, size, sty, C_LINK if href else C_INK)
                        yy += lh
                    p.rect(x, st["y"], cw[j], h, C_RULE, stroke=True, lw=0.5)
                    x += cw[j]
                st["y"] += h
            st["y"] += gap
        elif k == "img":
            hit = images.get(b[1])
            obj = None
            if hit:
                if b[1] not in img_names:
                    o = pdf_image_object(hit[0])
                    if o:
                        img_names[b[1]] = f"W{len(img_names) + 1}"
                        imgs[img_names[b[1]]] = o
                obj = imgs.get(img_names.get(b[1], ""))
            if not obj:
                flow([(b[2] or b[1].rsplit("/", 1)[-1], frozenset({"i"}), b[1] if WKD_URL_OK.match(b[1]) else "")], L, W, fs, color=C_INK2)
                st["y"] += gap
                continue
            pw, ph = obj[0], obj[1]
            w = min(W, pw * 72 / 150)
            h = ph * w / pw
            if h > (BOT - TOP) * 0.8:
                h = (BOT - TOP) * 0.8
                w = pw * h / ph
            room(h)
            st["p"].image(img_names[b[1]], L, st["y"], w, h)
            st["y"] += h + gap
    if style == "notepad":  # ruled paper behind the text, a margin line
        for p in pages:
            pitch = fs * lk["lh"]
            ops, y = [], TOP + pitch
            while y < BOT:
                r, g, bl = _rgb("#dbe4ef")
                ops.append(f"{r:.3f} {g:.3f} {bl:.3f} RG 0.4 w [] 0 d {L:.2f} {p.H - y:.2f} m {L + W:.2f} {p.H - y:.2f} l S")
                y += pitch
            r, g, bl = _rgb("#efb8b8")
            ops.append(f"{r:.3f} {g:.3f} {bl:.3f} RG 0.6 w [] 0 d {L - 4 * MM:.2f} {p.H - TOP + 6:.2f} m {L - 4 * MM:.2f} {p.H - BOT:.2f} l S")
            p.ops[:0] = ops
    if len(pages) > 1:
        for n, p in enumerate(pages, 1):
            s = tr("Page {0} of {1}|pdf", n, len(pages))
            p.text(L, A4_H - 12 * MM, s, 8, color=C_INK2, align="c", width=W)
    return pdf_write(pages, imgs, title=title, author="")


# ---- .docx -----------------------------------------------------------------------------------------------------------
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _x(s):
    return _xesc(_XML_BAD.sub("", str(s)), {'"': "&quot;"})


W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')


def wkd_docx(title, blocks, images, style=""):
    """The .docx bytes: document.xml with styles (Title, Heading1-6, Quote, Code, Hyperlink), numbering for the lists
    (each numbered list starts at its own first number), hyperlinks and the page's pictures (as PNG)."""
    lk = wkd_look(style)
    rels, media, nums = [], {}, []  # (id, type, target, external?); name -> png bytes; numbered lists -> start number

    def rel(typ, target, ext=False):
        rid = f"rId{len(rels) + 10}"
        rels.append((rid, typ, target, ext))
        return rid

    def run(t, sty):
        pr = "".join(x for k, x in (("b", "<w:b/>"), ("i", "<w:i/>"), ("s", "<w:strike/>")) if k in sty)
        if "c" in sty:
            pr = '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>' + pr + '<w:shd w:val="clear" w:color="auto" w:fill="F1F3F6"/>'
        parts = t.split("\n")
        body = "<w:br/>".join(f'<w:t xml:space="preserve">{_x(p)}</w:t>' for p in parts)
        return f"<w:r>{'<w:rPr>' + pr + '</w:rPr>' if pr else ''}{body}</w:r>"

    def runs_xml(runs, extra=frozenset()):
        out = []
        for t, sty, href in runs:
            sty = sty | extra
            if href:
                rid = rel("hyperlink", href, True)
                pr = "".join(x for k, x in (("b", "<w:b/>"), ("i", "<w:i/>")) if k in sty)
                out.append(f'<w:hyperlink r:id="{rid}"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/>{pr}</w:rPr>'
                           f'<w:t xml:space="preserve">{_x(t)}</w:t></w:r></w:hyperlink>')
            else:
                out.append(run(t, sty))
        return "".join(out)

    def para(inner, pstyle=None, ppr=""):
        st = f'<w:pStyle w:val="{pstyle}"/>' if pstyle else ""
        return f"<w:p>{'<w:pPr>' + st + ppr + '</w:pPr>' if st or ppr else ''}{inner}</w:p>"

    def picture(src):
        hit = images.get(src)
        if not hit:
            return None
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(hit[0]))
            if im.width * im.height > 30_000_000:
                return None
            im.load()
            if im.mode not in ("RGB", "RGBA", "L", "LA"):
                im = im.convert("RGBA")
            buf = io.BytesIO()
            im.save(buf, "PNG")
        except Exception:  # noqa: BLE001  (not a picture after all)
            return None
        name = f"image{len(media) + 1}.png"
        media[name] = buf.getvalue()
        rid = rel("image", f"media/{name}")
        maxw = (210 - 2 * lk["side"]) * 36000  # EMU
        w = min(maxw, im.width * 914400 // 150)
        h = im.height * w // max(1, im.width)
        n = len(media)
        return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{w}" cy="{h}"/>'
                f'<wp:docPr id="{n}" name="Picture {n}"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{n}" name="{_x(name)}"/><pic:cNvPicPr/></pic:nvPicPr>'
                f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
                f'</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')

    body, prev = [], None
    first = blocks[0] if blocks else None
    if not (first and first[0] == "h" and wkd_plain(first[2]).strip().lower() == title.strip().lower()):
        body.append(para(run(title, frozenset()), "Title"))
    for b in blocks:
        k = b[0]
        if k == "h":
            body.append(para(runs_xml(b[2]), f"Heading{b[1]}"))
        elif k == "p":
            body.append(para(runs_xml(b[1])))
        elif k == "li":
            ordered, depth, num, tick, runs = b[1:]
            if ordered and not (prev and prev[0] == "li" and prev[1] and prev[2] <= depth):
                nums.append(num or 1)
            nid = 1 if not ordered else 1 + len(nums)
            mark = [("☒ " if tick else "☐ ", frozenset(), "")] if tick is not None else []
            body.append(para(runs_xml(mark + list(runs)), "ListParagraph", f'<w:numPr><w:ilvl w:val="{depth}"/><w:numId w:val="{nid}"/></w:numPr>'))
        elif k == "quote":
            body.append(para(runs_xml(b[1]), "Quote"))
        elif k == "code":
            body.append(para(run(b[1], frozenset()), "Code"))
        elif k == "hr":
            body.append(para("", None, '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="C9CED6"/></w:pBdr>'))
        elif k == "table":
            rows, n = b[1], max(len(r) for r in b[1])
            tw = int((210 - 2 * lk["side"]) * 56.7)
            grid = "".join(f'<w:gridCol w:w="{tw // n}"/>' for _ in range(n))
            trs = []
            for ri, r in enumerate(rows):
                tcs = "".join(f'<w:tc><w:tcPr><w:tcW w:w="{tw // n}" w:type="dxa"/>'
                              f'{SHD if ri == 0 else ""}</w:tcPr>'
                              f'{para(runs_xml(r[j], frozenset({"b"}) if ri == 0 else frozenset()))}</w:tc>' for j in range(n))
                trs.append(f"<w:tr>{'<w:trPr><w:tblHeader/></w:trPr>' if ri == 0 else ''}{tcs}</w:tr>")
            bd = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="C9CED6"/>' for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
            body.append(f'<w:tbl><w:tblPr><w:tblW w:w="{tw}" w:type="dxa"/><w:tblBorders>{bd}</w:tblBorders></w:tblPr>'
                        f'<w:tblGrid>{grid}</w:tblGrid>{"".join(trs)}</w:tbl>')
            body.append(para(""))
        elif k == "img":
            pic = picture(b[1])
            body.append(para(pic) if pic else para(runs_xml([(b[2] or b[1].rsplit("/", 1)[-1], frozenset({"i"}), b[1] if WKD_URL_OK.match(b[1]) else "")])))
        prev = b
    side = int(lk["side"] * 56.7)
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {W_NS}><w:body>{"".join(body)}'
           f'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1247" w:right="{side}" w:bottom="1134" w:left="{side}" '
           f'w:header="709" w:footer="709" w:gutter="0"/></w:sectPr></w:body></w:document>')
    hs = int(lk["fs"] * 2)
    ln = int(240 * lk["lh"] / 1.15)
    after = int(lk["fs"] * lk["gap"] * 20)
    font = lk["font"]
    head = "".join(f'<w:style w:type="paragraph" w:styleId="Heading{n}"><w:name w:val="heading {n}"/><w:basedOn w:val="Normal"/>'
                   f'<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="{int(hs * WKD_HEAD[n - 1] * 6)}" w:after="{after}"/>'
                   f'<w:outlineLvl w:val="{n - 1}"/></w:pPr><w:rPr><w:b/><w:sz w:val="{int(hs * WKD_HEAD[n - 1])}"/></w:rPr></w:style>' for n in range(1, 7))
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:styles {W_NS}><w:docDefaults><w:rPrDefault><w:rPr>'
              f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}" w:eastAsia="{font}"/><w:sz w:val="{hs}"/><w:szCs w:val="{hs}"/>'
              f'<w:lang w:val="de-DE"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="{after}" w:line="{ln}" w:lineRule="auto"/>'
              f'</w:pPr></w:pPrDefault></w:docDefaults>'
              f'<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
              f'<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>'
              f'<w:qFormat/><w:pPr><w:spacing w:after="{after * 2}"/></w:pPr><w:rPr><w:b/><w:sz w:val="{int(hs * WKD_HEAD[0])}"/></w:rPr></w:style>{head}'
              f'<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr>'
              f'<w:pBdr><w:left w:val="single" w:sz="12" w:space="8" w:color="C9CED6"/></w:pBdr><w:ind w:left="340"/></w:pPr>'
              f'<w:rPr><w:color w:val="4B515C"/></w:rPr></w:style>'
              f'<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:pPr>'
              f'<w:shd w:val="clear" w:color="auto" w:fill="F1F3F6"/><w:spacing w:line="240" w:lineRule="auto"/></w:pPr>'
              f'<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/><w:sz w:val="{max(14, hs - 2)}"/></w:rPr></w:style>'
              f'<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>'
              f'<w:qFormat/><w:pPr><w:spacing w:after="{after // 3}"/><w:contextualSpacing/></w:pPr></w:style>'
              f'<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr><w:color w:val="1D4ED8"/>'
              f'<w:u w:val="single"/></w:rPr></w:style></w:styles>')

    def lvls(fmt):
        return "".join(f'<w:lvl w:ilvl="{n}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/>'
                       f'<w:lvlText w:val="{chr(0x2022) if fmt == "bullet" else "%" + str(n + 1) + "."}"/><w:lvlJc w:val="left"/>'
                       f'<w:pPr><w:ind w:left="{360 * (n + 1) + 0}" w:hanging="360"/></w:pPr></w:lvl>' for n in range(4))
    numbering = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:numbering {W_NS}>'
                 f'<w:abstractNum w:abstractNumId="0">{lvls("bullet")}</w:abstractNum>'
                 f'<w:abstractNum w:abstractNumId="1">{lvls("decimal")}</w:abstractNum>'
                 f'<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
                 + "".join(f'<w:num w:numId="{k + 2}"><w:abstractNumId w:val="1"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="{s}"/>'
                           f'</w:lvlOverride></w:num>' for k, s in enumerate(nums)) + "</w:numbering>")
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rId1" Type="{R}/styles" Target="styles.xml"/>'
                f'<Relationship Id="rId2" Type="{R}/numbering" Target="numbering.xml"/>'
                + "".join(f'<Relationship Id="{rid}" Type="{R}/{typ}" Target="{_x(t)}"{EXT if ext else ""}/>'
                          for rid, typ, t, ext in rels) + "</Relationships>")
    now = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{_x(title)}</dc:title><dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
             '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
             '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
    pkg_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rId1" Type="{R}/officeDocument" Target="word/document.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
                'Target="docProps/core.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", pkg_rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/numbering.xml", numbering)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        for n, data in media.items():
            z.writestr(f"word/media/{n}", data, compress_type=zipfile.ZIP_STORED)
    return buf.getvalue()


def wkd_file_name(path, ext):
    """The page's own name (the last part of its path) as a file name: no path signs, at most 80 characters."""
    base = str(path or "").rsplit("/", 1)[-1]
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", base).strip(" .") or "page"
    return base[:80] + "." + ext


@app.get("/api/wiki/pages/<int:pid>/export")
def wiki_page_export(pid):
    """?format=pdf|docx [&style=''|book|compact|notepad: the reading style the browser shows; missing = the space's default]
    -- the page as a file to download. Whoever reads the page (wiki_need); a page of a space with the lock: 409 wiki_e2e (the
    browser makes it, static/js/wkdoc.js)."""
    fmt = (request.args.get("format") or "pdf").lower()
    if fmt not in WKD_FORMATS:
        raise BadInput(tr("Invalid value: {0}", "format"))
    c, uid = db(), me()
    r = wiki_need(c, pid)
    wke_guard(c, r["org_id"], r["owner_id"] or uid, kind="export")
    style = request.args.get("style")
    if style is None:
        style = wst_get(c, r["org_id"], r["owner_id"] or uid)
    if style not in WIKI_STYLES:
        raise BadInput(tr("Invalid value: {0}", "style"))
    blocks = wkd_blocks(wkh_body(c, r))
    title = str(r["path"]).rsplit("/", 1)[-1]
    images = wkd_images(c, r, blocks)
    if fmt == "pdf":
        data, mime = wkd_pdf(title, blocks, images, style), "application/pdf"
    else:
        data, mime = wkd_docx(title, blocks, images, style), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    resp = send_file(io.BytesIO(data), mimetype=mime, as_attachment=True, download_name=wkd_file_name(r["path"], fmt))
    resp.headers["Cache-Control"] = "no-store"
    return resp

