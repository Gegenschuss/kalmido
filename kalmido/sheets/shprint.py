"""2.578.0 (#3462): the print view of a table as a PDF -- portrait or landscape, fitted to the page width, the header row on
every page, page numbers, the whole sheet or a choice of rows / columns.

POST /api/sheets/<id>/print.pdf {orient: portrait | landscape, fit: bool, head: bool, numbers: bool, rows: [row ids] | null,
cols: [column ids] | null} -> application/pdf. The client sends the rows it shows (its filters are its own) or the selected
rectangle; null = every row / column of the sheet. The values are the evaluated cells of the person who asks (sh_eval), so the
PDF never holds a value they could not see. Written with the office PDF writer (office/pdf.py: _Page, pdf_write, the
embedded fonts), no PDF library and nothing in the browser. Without "fit" the columns that do not fit run onto further
pages (down first, then across, like spreadsheets), each with the row numbers again; with "fit" the font gets smaller
until every column fits (at least SHP_FS_MIN, longer texts end with "…"). Read right only (the export routes' rule).
2.589.0 (#4825): a cell's own format goes along -- bold, italic (the regular font slanted), alignment and fill (the palette's
fill colours of sheets/shfmt.py SHFM_XL_FILL, as in the .xlsx export); colour rules and merged blocks stay screen only.
"""
import re

from flask import Response

from ..core.config import app
from ..core.db import body, db, local_now
from ..core.errors import BadInput
from ..core.i18n import lang, tr
from ..accounts.session import me
from ..office.pdf import A4_H, A4_W, C_INK2, C_RULE, C_RULE2, _Page, pdf_text_width, pdf_write
from .core import ShBook, sh_eval, sh_need
from .formula import sh_col_letter
from .io import _disposition, shx_file_name
from .shfmt import SHFM_XL_FILL, shfm_load  # 2.589.0 (#4825)

SHP_FS = 8.0  # the font size of the cells (points)
SHP_FS_MIN = 3.5  # "fit": never smaller
SHP_MARGIN = 36.0  # page margins (half an inch)
SHP_COL_MAX = 220.0  # a column is never wider than this (at SHP_FS)
SHP_PAGES_MAX = 400  # more pages = 400 (choose fewer rows / columns)
SHP_NUM_KINDS = ("number", "currency", "percent")
SHP_SLANT = 0.21  # 2.589.0 (#4825): italic = the font slanted ~12 degrees (the embedded fonts have no italic face)
SHP_ALIGN = {"left": "l", "center": "c", "right": "r"}


class _Wide(_Page):
    """A landscape A4 page (pdf_write takes the MediaBox from W / H)."""
    W, H = A4_H, A4_W


def _ids(v, have, what):
    if v is None:
        return None
    if not isinstance(v, list) or len(v) > 100_000 or any(isinstance(x, bool) or not isinstance(x, int) for x in v):
        raise BadInput(tr("Invalid value: {0}", what))
    keep = [x for x in v if x in have]
    if not keep:
        raise BadInput(tr("Nothing to print"))
    return keep


def _cut(s, size, width, bold=False):
    """s shortened with "…" to width at size."""
    if pdf_text_width(s, size, bold) <= width:
        return s
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if pdf_text_width(s[:mid] + "…", size, bold) <= width:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo] + "…" if lo else ""


def _shp_text(pg, x, y, s, size, bold, italic, align, width):
    """2.589.0 (#4825): one cell's text; italic slants the line through its text matrix (office/pdf.py _Page.text draws with Td
    from the origin, the same place as an absolute Tm)."""
    pg.text(x, y, s, size, bold=bold, align=align, width=width)
    if italic and pg.ops:
        pg.ops[-1] = re.sub(r"(-?[\d.]+) (-?[\d.]+) Td ", lambda m: f"1 0 {SHP_SLANT} 1 {m.group(1)} {m.group(2)} Tm ", pg.ops[-1], count=1)


def shp_pdf(c, sheet, opts):
    """The PDF bytes of sheet for the current person with opts (see the module doc)."""
    book = ShBook(c, sheet)
    res = sh_eval(c, sheet, book, me())
    rows = _ids(opts.get("rows"), book.row_idx, "rows")
    cols = _ids(opts.get("cols"), book.col_idx, "cols")
    rset, cset = set(rows or ()), set(cols or ())
    rows = [r for r in book.rows if rows is None or r["id"] in rset]
    cols = [col for col in book.cols if cols is None or col["id"] in cset]
    if not rows or not cols:
        raise BadInput(tr("Nothing to print"))
    land, fit = opts.get("orient") == "landscape", bool(opts.get("fit", True))
    head, numbers = bool(opts.get("head", True)), bool(opts.get("numbers", True))
    P = _Wide if land else _Page
    pw, ph = P.W, P.H
    uw = pw - 2 * SHP_MARGIN
    at = {(x["row_id"], x["col_id"]): x for x in book.cells.values() if book.live(x)}

    def text(rid, col):
        x = at.get((rid, col["id"]))
        r = res.get(x["id"]) if x else None
        if not r:
            return ""
        if r.get("error"):
            return r.get("error_text") or "#"
        return str(r.get("display") or "").replace("\n", " ")

    grid = [[text(r["id"], col) for col in cols] for r in rows]

    def fmt(rid, col):  # 2.589.0 (#4825): the cell's own format (bold, italic, align, fill) or None
        x = at.get((rid, col["id"]))
        return shfm_load(x["fmt"]) if x and "fmt" in x.keys() else None

    fmts = [[fmt(r["id"], col) for col in cols] for r in rows]
    titles = [col["title"] or sh_col_letter(book.col_idx[col["id"]]) for col in cols]
    nums = [str(book.row_idx[r["id"]] + 1) for r in rows]
    right = [col["kind"] in SHP_NUM_KINDS for col in cols]
    for ci, col in enumerate(cols):  # a text column whose values are numbers (formulas) is right-aligned as well
        if not right[ci]:
            vals = [res.get(at[(r["id"], col["id"])]["id"], {}).get("vtype") for r in rows if (r["id"], col["id"]) in at]
            vals = [v for v in vals if v not in (None, "empty")]
            right[ci] = bool(vals) and all(v == "number" for v in vals)
    pad = 4.0

    def natural(size):
        ws = []
        for ci in range(len(cols)):
            w = pdf_text_width(titles[ci], size, True)
            for ri, row in enumerate(grid):
                if row[ci]:
                    w = max(w, pdf_text_width(row[ci], size, bool((fmts[ri][ci] or {}).get("bold"))))
                    if w >= SHP_COL_MAX * size / SHP_FS:
                        break
            ws.append(min(SHP_COL_MAX * size / SHP_FS, max(18.0 * size / SHP_FS, w)) + 2 * pad)
        nw = max(pdf_text_width(n, size) for n in nums + ["0"]) + 2 * pad
        return ws, nw

    fs = SHP_FS
    ws, nw = natural(fs)
    if fit and nw + sum(ws) > uw:
        fs = max(SHP_FS_MIN, SHP_FS * uw / (nw + sum(ws)))
        ws, nw = natural(fs)
        if nw + sum(ws) > uw:  # at the smallest size: the columns share the width in proportion
            k = (uw - nw) / sum(ws)
            ws = [w * k for w in ws]
    # the columns of each page across (without "fit" as many as fit; a column wider than the page gets the page)
    chunks, cur, used = [], [], nw
    for ci, w in enumerate(ws):
        if cur and used + w > uw + 0.01:
            chunks.append(cur)
            cur, used = [], nw
        w = min(w, uw - nw)
        ws[ci] = w
        cur.append(ci)
        used += w
    chunks.append(cur)
    lh = fs * 1.6
    foot = 18.0 if numbers else 0.0
    top = SHP_MARGIN
    title = sheet["title"] or tr("Untitled table")
    when = local_now().strftime("%d.%m.%Y %H:%M") if lang().split("-")[0] != "en" else local_now().strftime("%Y-%m-%d %H:%M")
    pages = []

    def new_page(first):
        pg = P()
        pages.append(pg)
        if len(pages) > SHP_PAGES_MAX:
            raise BadInput(tr("Too many pages: select fewer rows or columns"))
        y = top
        if first:
            pg.text(SHP_MARGIN, y, title, 12, bold=True)
            y += 17
            pg.text(SHP_MARGIN, y, when, 7, color=C_INK2)
            y += 14
        return pg, y

    def head_row(pg, y, chunk):
        pg.rect(SHP_MARGIN, y, nw + sum(ws[ci] for ci in chunk), lh, C_RULE2)
        x = SHP_MARGIN + nw
        for ci in chunk:
            s = _cut(titles[ci], fs, ws[ci] - 2 * pad, True)
            pg.text(x + pad, y + (lh - fs) / 2, s, fs, bold=True, align="r" if right[ci] else "l", width=ws[ci] - 2 * pad)
            x += ws[ci]
        pg.line(SHP_MARGIN, y + lh, x, y + lh, color=C_RULE)
        return y + lh

    for k, chunk in enumerate(chunks):
        pg, y = new_page(k == 0)
        y = head_row(pg, y, chunk)
        x1 = SHP_MARGIN + nw + sum(ws[ci] for ci in chunk)
        for ri, row in enumerate(grid):
            if y + lh > ph - SHP_MARGIN - foot:
                pg, y = new_page(False)
                if head:
                    y = head_row(pg, y, chunk)
            pg.text(SHP_MARGIN + pad, y + (lh - fs) / 2, nums[ri], fs, color=C_INK2, align="r", width=nw - 2 * pad)
            x = SHP_MARGIN + nw
            for ci in chunk:
                f = fmts[ri][ci] or {}
                if f.get("fill") in SHFM_XL_FILL:  # 2.589.0 (#4825): under the text and the row's rule
                    pg.rect(x, y, ws[ci], lh, "#" + SHFM_XL_FILL[f["fill"]])
                if row[ci]:
                    b = bool(f.get("bold"))
                    s = _cut(row[ci], fs, ws[ci] - 2 * pad, b)
                    al = SHP_ALIGN.get(f.get("align")) or ("r" if right[ci] else "l")
                    _shp_text(pg, x + pad, y + (lh - fs) / 2, s, fs, b, bool(f.get("italic")), al, ws[ci] - 2 * pad)
                x += ws[ci]
            y += lh
            pg.line(SHP_MARGIN, y, x1, y, w=0.3, color=C_RULE)
    if numbers:
        n = len(pages)
        for i, pg in enumerate(pages, 1):
            pg.text(SHP_MARGIN, ph - SHP_MARGIN - 9, tr("Page {0} of {1}", i, n), 7, color=C_INK2, align="r", width=pw - 2 * SHP_MARGIN)
    return pdf_write(pages, {}, title=title)


@app.post("/api/sheets/<int:sid>/print.pdf")
def shp_print(sid):
    """{orient, fit, head, numbers, rows, cols} -> the PDF of the sheet's print view (read right; see the module doc)."""
    c = db()
    r = sh_need(c, sid)
    b = body()
    if not isinstance(b, dict) or b.get("orient", "portrait") not in ("portrait", "landscape"):
        raise BadInput(tr("Invalid value: {0}", "orient"))
    data = shp_pdf(c, r, b)
    c.commit()  # sheet_lastvals of the viewer, like the exports
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": _disposition(shx_file_name(r["title"], "pdf")), "Cache-Control": "no-store"})

