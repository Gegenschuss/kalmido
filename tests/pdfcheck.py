"""2.296.0 A (#3178): a layout check for the office PDFs Kalmido writes itself (kalmido/office/pdf.py and the writers on top of
it: quotations / invoices, documents from templates, letters, entertainment receipts). Reads the PDF bytes with pypdf only
(tests/requirements.txt), no server.

  layout(data) -> one dict per page: {"w", "h", "texts": [{"x", "y", "size", "w", "s", "bold"}], "rules": [(x1, y1, x2, y2)],
                  "foot": y of the footer rule or None}; y always from the TOP of the page (like the writer), in points;
                  "y" of a text = the top of its line box (baseline - 0.78 * size), "w" its width from the font's /Widths
  problems(data, top=5 mm, right=20 mm, bottom=5 mm, left=0, overlap=True, foot=True, body_size=7.2) -> [str]:
     every text inside [left, page width - right] and [top, page height - bottom]; with foot: no text crosses the footer
     rule and no text above body_size (a body line) stands below it; with overlap: no two text boxes overlap
  footer_lines(data) -> per page the text lines below the footer rule (top to bottom, one string per line)

The footer rule is the lowest horizontal rule of at least 100 mm in the lowest 70 mm of a page. A letterhead page that hides
our footer has none (then only the page frame is checked). The writer's own conventions are the parsing basis: text as
"BT r g b rg /Fn size Tf c Tc x y Td <hex> Tj ET", rules as "... x1 y1 m x2 y2 l S", a page shift as "q 1 0 0 1 dx dy cm"
(bp_finish); the diagonal watermark (Tm) is no text line and is left out."""
import io
import re

MM = 72 / 25.4
_TXT = re.compile(rb"BT [\d.]+ [\d.]+ [\d.]+ rg /(F\d+) ([\d.]+) Tf (-?[\d.]+) Tc (-?[\d.]+) (-?[\d.]+) Td <([0-9a-fA-F]*)> Tj ET")
_RULE = re.compile(rb"(-?[\d.]+) (-?[\d.]+) m (-?[\d.]+) (-?[\d.]+) l S")
_SHIFT = re.compile(rb"^q 1 0 0 1 (-?[\d.]+) (-?[\d.]+) cm$", re.M)


def _widths(page):
    out = {}
    fonts = ((page.get("/Resources") or {}).get("/Font") or {})
    for name, ref in fonts.items():
        f = ref.get_object()
        first = int(f.get("/FirstChar", 32))
        ws = [float(w) for w in (f.get("/Widths") or [])]
        out[name.lstrip("/")] = (first, ws, "Bold" in str(f.get("/BaseFont", "")))
    return out


def layout(data):
    from pypdf import PdfReader
    rd = PdfReader(io.BytesIO(data))
    pages = []
    for page in rd.pages:
        box = page.mediabox
        pw, ph = float(box.width), float(box.height)
        raw = page.get_contents().get_data() if page.get_contents() is not None else b""
        m = _SHIFT.search(raw)
        dx, dy = (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)
        fw = _widths(page)
        texts = []
        for t in _TXT.finditer(raw):
            font, size, tc, x, y = t.group(1).decode(), float(t.group(2)), float(t.group(3)), float(t.group(4)), float(t.group(5))
            b = bytes.fromhex(t.group(6).decode())
            first, ws, bold = fw.get(font, (32, [], False))
            w = sum(ws[ch - first] if 0 <= ch - first < len(ws) else 556 for ch in b) * size / 1000.0 + tc * len(b)
            texts.append({"x": x + dx, "y": ph - (y + dy) - size * 0.78, "size": size, "w": w, "s": b.decode("cp1252", "replace"), "bold": bold})
        rules = [(float(a) + dx, ph - float(b_) - dy, float(c) + dx, ph - float(d) - dy) for a, b_, c, d in _RULE.findall(raw)]
        foot = [r for r in rules if abs(r[1] - r[3]) < 0.01 and abs(r[2] - r[0]) >= 100 * MM and r[1] > ph - 70 * MM]
        pages.append({"w": pw, "h": ph, "texts": texts, "rules": rules, "foot": max(r[1] for r in foot) if foot else None})
    return pages


def problems(data, top=5 * MM, right=20 * MM, bottom=5 * MM, left=0.0, overlap=True, foot=True, body_size=7.2, tol=0.6):
    """See the module doc; [] = the layout is clean. Every problem names the page (1-based) and the text."""
    out = []
    for n, p in enumerate(layout(data), 1):
        ts = p["texts"]
        for t in ts:
            q = f"p{n}: {t['s'][:40]!r}"
            if t["x"] < left - tol or t["x"] + t["w"] > p["w"] - right + tol:
                out.append(f"{q} outside the side margins (x {t['x']:.1f}..{t['x'] + t['w']:.1f}, page {p['w']:.1f}, right margin {right:.1f})")
            if t["y"] < top - tol or t["y"] + t["size"] > p["h"] - bottom + tol:
                out.append(f"{q} outside the page height (y {t['y']:.1f}..{t['y'] + t['size']:.1f}, page {p['h']:.1f})")
            fy = p["foot"]
            if foot and fy is not None:
                if t["y"] < fy - tol and t["y"] + t["size"] * 0.95 > fy + tol:
                    out.append(f"{q} crosses the footer rule (y {t['y']:.1f}, rule {fy:.1f})")
                elif t["y"] >= fy - tol and t["size"] > body_size:
                    out.append(f"{q} body text below the footer rule (y {t['y']:.1f}, rule {fy:.1f}, {t['size']} pt)")
        if overlap:
            for i, a in enumerate(ts):
                for b in ts[i + 1:]:
                    ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
                    oy = min(a["y"] + a["size"] * 0.95, b["y"] + b["size"] * 0.95) - max(a["y"], b["y"])
                    if ox > tol and oy > tol:
                        out.append(f"p{n}: {a['s'][:30]!r} overlaps {b['s'][:30]!r} ({ox:.1f} x {oy:.1f} pt)")
    return out


def footer_lines(data):
    """Per page the footer's text lines below the rule, top to bottom (texts on one line joined by a space, left to right)."""
    res = []
    for p in layout(data):
        if p["foot"] is None:
            res.append([])
            continue
        rows = {}
        for t in sorted((t for t in p["texts"] if t["y"] >= p["foot"] - 0.6), key=lambda t: (round(t["y"], 1), t["x"])):
            rows.setdefault(round(t["y"], 1), []).append(t["s"])
        res.append([" ".join(v) for _k, v in sorted(rows.items())])
    return res
