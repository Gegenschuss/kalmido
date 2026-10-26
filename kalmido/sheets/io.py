"""2.89.0 C (#1916): tables to and from files.

Export (reading the sheet is enough; values evaluated for the person exporting, so a file never holds a value they could not see):
  - CSV: the values (no formulas), a header row with the column titles, UTF-8 with BOM, ";" and the decimal comma in the
    decimal-comma languages (like /api/time/export.csv); text that a spreadsheet would run as a formula gets a "'" (_csv_cell).
  - .xlsx: values AND formulas where Excel has the same thing (addresses, ranges, column ranges, SUM / AVERAGE / MIN / MAX /
    COUNT / IF / ROUND / TODAY / DAYS, 2.124.0 A (#2109): SUMIF / COUNTIF / VLOOKUP / XLOOKUP and the text / date functions of
    sheets/shfuncs.py, + - * / & % comparisons); a formula with a Kalmido variable (projekt.x.y ...) or one
    Excel cannot express is written as its value with a note (comment) showing the Kalmido formula. Column kinds become number
    formats, select columns a drop-down list (data validation) and a fill colour per option (conditional formatting, the cell
    or the whole row by color_mode), cell names Excel names. Written by hand (zipfile, no library), checked against the
    OOXML schema order so Excel, LibreOffice and Numbers open it.
Import (a new sheet in a space the person may write, optionally attached to a list; the module "sheets" on):
  - CSV (separator ; , or tab detected) and .xlsx (the first sheet): a header row becomes the column titles, the column kind is
    guessed from the values / number formats, an .xlsx drop-down list becomes a select column (its colours from the
    conditional formatting when there are any), simple formulas are taken over (German names), the rest as their value --
    the answer counts what was taken over as a value. Size budget and entity guard like the legacy import (fi_xlsx_read).
"""
import csv
import io
import re
import zipfile
import zlib
from datetime import date, timedelta
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as _sax_escape

from flask import Response, jsonify, request

from ..core.config import app
from ..core.access import need_feat
from ..core.db import db
from ..core.i18n import dec_comma, lang, tr
from ..accounts.session import me
from ..office.legacyimport import _col_index, _local, _rels
from ..personal.timetrack import _csv_cell
from ..core.serializers import csv_uncell  # 2.273.0 D (#3051)
from ..core.errors import BadInput
from .shkinds import shk_export, shk_guess  # 2.124.0 B (#2110)
from .core import (SH_COLS_MAX, SH_ROWS_MAX, ShBook, _write_cells, sh_brief, sh_create, sh_currency, sh_eval, sh_need, sh_options,
                   sh_reload, sh_to_display, sh_to_internal, sh_touch)
from .formula import (SH_CURRENCY_SYMBOLS, ShErr, sh_col_letter, sh_fmt_date, sh_name_ok, sh_parse_date, sh_parse_number,
                      sh_fn_key, sh_tokens)
from .shfuncs import SHF_DE, SHF_EXCEL, shf_vlookup3

SHX_FILE_MAX = 10 * 1024 * 1024        # an uploaded file
SHX_UNZIPPED_MAX = 60 * 1024 * 1024    # the parts of an .xlsx read in all (zip bomb guard)
SHX_CELLS_MAX = 50_000                 # non-empty cells of an import
_SHX_EMPTY = {"v": "", "f": None, "fmt": None}  # 2.148.1 D (#2485): read only, shared by every empty place of a read grid
SHX_CHUNK = 4000                       # cells per write (the core takes at most SH_CELLS_MAX at once)
SHX_EXCEL_FN = {"sum": "SUM", "avg": "AVERAGE", "min": "MIN", "max": "MAX", "count": "COUNT", "if": "IF", "round": "ROUND",
                "today": "TODAY", "days": "_xlfn.DAYS"}
SHX_KALMIDO_FN = {"SUM": "SUMME", "AVERAGE": "MITTELWERT", "MIN": "MIN", "MAX": "MAX", "COUNT": "ANZAHL", "IF": "WENN",
                  "ROUND": "RUNDEN", "TODAY": "HEUTE", "DAYS": "TAGE",
                  "SUMME": "SUMME", "MITTELWERT": "MITTELWERT", "ANZAHL": "ANZAHL", "WENN": "WENN", "RUNDEN": "RUNDEN",
                  "HEUTE": "HEUTE", "TAGE": "TAGE"}
SHX_XL_ERR = {"div0": "#DIV/0!", "ref": "#REF!", "cycle": "#VALUE!", "type": "#VALUE!", "syntax": "#NAME?", "na": "#N/A"}
SHX_EXCEL_FN.update(SHF_EXCEL)  # 2.124.0 A (#2109): SUMIF, VLOOKUP, text and date functions both ways
SHX_KALMIDO_FN.update({re.sub(r"^_xlfn\.", "", x): SHF_DE[k] for k, x in SHF_EXCEL.items()})
SHX_KALMIDO_FN.update({"CONCATENATE": "VERKETTEN", **{x: x for x in SHF_DE.values()}})
_NS = "http://schemas.openxmlformats.org"
_MAIN = f"{_NS}/spreadsheetml/2006/main"
_EPOCH = date(1899, 12, 30)
_XL_DATE_FMTS = {14, 15, 16, 17, 22, 27, 30, 36, 50, 57}  # built-in date formats (22 = date + time)
_XL_PCT_FMTS = {9, 10}


# ---------------------------------------------------------------- export: helpers
def shx_file_name(title, ext):
    """A safe download name from the sheet's title."""
    s = re.sub(r"[^\w\- .]+", "", title or "", flags=re.U).strip()[:80] or tr("Table")
    return f"{s}.{ext}"


def _disposition(name):
    from urllib.parse import quote
    ascii_name = re.sub(r"[^A-Za-z0-9_\- .]", "_", name)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def _pyval(r):
    """The Python value of an evaluated cell (None when empty or an error)."""
    if not r or r.get("error"):
        return None
    v, t = r.get("value"), r.get("vtype")
    if t == "date":
        return sh_parse_date(str(v))
    if t == "number":
        return float(v)
    if t == "bool":
        return bool(v)
    return v


def _grid(c, sheet):
    """(book, results, {(row index, col index): cell}) of the sheet, evaluated for the current person."""
    book = ShBook(c, sheet)
    res = sh_eval(c, sheet, book, me())
    at = {}
    for x in book.cells.values():
        if book.live(x):
            at[(book.row_idx[x["row_id"]], book.col_idx[x["col_id"]])] = x
    return book, res, at


def _used_rows(book, at, res):
    """The number of rows up to the last one with content (empty rows at the end are left out)."""
    last = -1
    for (ri, _ci), x in at.items():
        if (x["raw"] or "") != "" or x["frozen"]:
            last = max(last, ri)
    return last + 1


# ---------------------------------------------------------------- export: CSV
def shx_csv(c, sheet):
    """The CSV text (with BOM) of the sheet's values."""
    book, res, at = _grid(c, sheet)
    lg = lang()
    de = dec_comma(lg)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";" if de else ",", lineterminator="\r\n")
    w.writerow([_csv_cell(col["title"] or sh_col_letter(i)) for i, col in enumerate(book.cols)])

    def num(x):
        s = f"{x:.10f}".rstrip("0").rstrip(".") if x != int(x) or abs(x) >= 1e15 else str(int(x))
        return s.replace(".", ",") if de else s

    for ri in range(_used_rows(book, at, res)):
        row = []
        for ci, col in enumerate(book.cols):
            x = at.get((ri, ci))
            r = res.get(x["id"]) if x else None
            v = shk_export(col, r, _pyval(r), lg, csv=True)  # 2.124.0 B (#2110): a checkbox as WAHR / FALSCH
            if v is None:
                row.append("")
            elif isinstance(v, bool):
                row.append(_csv_cell(r.get("display") or ""))
            elif isinstance(v, float):
                if col["kind"] == "percent":
                    row.append(num(round(v * 100, 6)) + "%")
                elif col["kind"] == "currency":
                    row.append(num(round(v, 2)))
                else:
                    row.append(num(v))
            elif isinstance(v, date):
                row.append(sh_fmt_date(v, lg))
            else:
                row.append(_csv_cell(str(v)))
        w.writerow(row)
    return "﻿" + buf.getvalue()


# ---------------------------------------------------------------- export: .xlsx
def _xl_num(v):
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(float(v))


def _xl_ref(book, x, hdr=1):
    return sh_col_letter(book.col_idx[x["col_id"]]) + str(book.row_idx[x["row_id"]] + 1 + hdr)


def shx_xl_formula(book, raw, self_cell, last_row):
    f = _shx_xl_formula(book, raw, self_cell, last_row)
    if f and "!" in f and getattr(book, "shb_xl", None):  # 2.124.0 E (#2116): 'Sheet 2'!A2:'Sheet 2'!B5 -> 'Sheet 2'!A2:B5
        from .shbook import shb_pairs
        f = shb_pairs(f)
    return f


def _shx_xl_formula(book, raw, self_cell, last_row):
    """The Excel form of a stored formula (ids), or None when Excel has no equivalent (Kalmido variables, hier.*, a column
    range that contains the cell itself, a deleted reference). last_row = the sheet's last row in the file (1-based)."""
    try:
        toks = sh_tokens(raw[1:])
    except ShErr:
        return None
    out, v3 = [], shf_vlookup3(toks)  # 2.124.0 A (#2109): VLOOKUP with three arguments is approximate in Excel
    for i, (kind, val, _a, _b) in enumerate(toks):
        if i in v3:
            out.append(",FALSE")
        if kind == "num":
            out.append(_xl_num(val))
        elif kind == "str":
            out.append('"' + val.replace('"', '""') + '"')
        elif kind in ("op", "cmp", "(", ")", ":", "%"):
            out.append(val)
        elif kind == "sep":
            out.append(",")
        elif kind == "fn":
            key = sh_fn_key(val)  # 2.124.0 A (#2109): + shfuncs
            if key not in SHX_EXCEL_FN:
                return None
            out.append(SHX_EXCEL_FN[key])
        elif kind == "ident":
            low = val.lower()
            if low in ("wahr", "true"):
                out.append("TRUE")
            elif low in ("falsch", "false"):
                out.append("FALSE")
            else:
                return None  # hier.<field> or a name that is no id any more
        elif kind == "idref":
            typ, xid, _field = val
            if typ == "c":
                x = book.cells.get(xid)
                if not book.live(x):
                    return None
                out.append(_xl_ref(book, x))
            elif typ == "col":
                if xid not in book.col_idx or (self_cell is not None and self_cell["col_id"] == xid) or last_row < 2:
                    return None
                L = sh_col_letter(book.col_idx[xid])
                out.append(f"{L}2:{L}{last_row}")
            elif typ == "x":  # 2.124.0 E (#2116): a cell of another sheet of the table (only when all sheets are written)
                from .shbook import shb_xl_ref
                ref = shb_xl_ref(book, xid)
                if ref is None:
                    return None
                out.append(ref)
            else:
                return None  # a Kalmido variable: the value goes into the file, the formula into a note
        else:
            return None
    return "".join(out)


def _sheet_name(title):
    s = re.sub(r"[\[\]:*?/\\]", " ", title or "").strip().strip("'")[:31].strip()
    return s or "Sheet1"


_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]")


def escape(s, entities=None):
    """XML text: characters XML 1.0 cannot carry are dropped (a pasted \\x01 would make the file unreadable). 2.89.0 (#1916): review 6"""
    return _sax_escape(_XML_BAD.sub("", s), entities or {})


def _q(s):
    """An attribute value in double quotes."""
    return escape(s, {'"': "&quot;"})


def _currency_fmt(cur):
    sym = SH_CURRENCY_SYMBOLS.get((cur or "EUR").upper(), (cur or "EUR").upper())
    if sym in ("$", "£"):
        return f'"{sym}"#,##0.00'
    return f'#,##0.00\\ "{sym}"'


def _xl_name_ok(name):
    """Excel's own rules for a defined name on top of Kalmido's (no R1C1-like names, no single r / c)."""
    return bool(name) and not re.fullmatch(r"[rRcC]|[rR]\d*[cC]\d*|[rR]\d+|[cC]\d+", name) and len(name) <= 255


def shx_xlsx(c, sheet, xl_names=None):
    """The .xlsx bytes of the sheet (one visible sheet; a hidden sheet "_lists" only when a drop-down list is too long to
    be written inline). 2.124.0 E (#2116): xl_names = {sheet id: name in the file} of the table's sheets (sheets/shbook.py
    shb_xlsx puts the files of all sheets together; formulas into another sheet keep their reference then)."""
    book, res, at = _grid(c, sheet)
    book.shb_xl = xl_names
    ncols = len(book.cols)
    nrows = _used_rows(book, at, res)
    last_row = nrows + 1                       # the header is row 1
    cur = sh_currency(c, sheet)
    # styles: 0 default, 1 header, 2 currency, 3 percent, 4 date
    style_of = {"currency": 2, "percent": 3, "date": 4}
    cells_xml, notes = [], []
    # the header
    hdr = "".join(f'<c r="{sh_col_letter(i)}1" s="1" t="inlineStr"><is><t xml:space="preserve">{escape(col["title"] or "")}</t></is></c>'
                  for i, col in enumerate(book.cols) if col["title"])
    cells_xml.append(f'<row r="1">{hdr}</row>')
    for ri in range(nrows):
        parts = []
        for ci, col in enumerate(book.cols):
            x = at.get((ri, ci))
            if not x:
                continue
            ref = f"{sh_col_letter(ci)}{ri + 2}"
            r = res.get(x["id"]) or {}
            raw = x["raw"] or ""
            v = shk_export(col, r, _pyval(r), None)  # 2.124.0 B (#2110): a checkbox as a truth value
            s = style_of.get(col["kind"])
            if isinstance(v, date):
                s = 4
            sa = f' s="{s}"' if s else ""
            f = None
            if raw.startswith("=") and not x["frozen"]:
                f = shx_xl_formula(book, raw, x, last_row)
                if f is None:
                    shown = sh_to_display(c, sheet, raw, book)
                    note = shown if not r.get("error") else f"{shown}\n{r.get('error_text') or ''}"
                    notes.append((ref, ri + 1, ci, "Kalmido: " + note))
            fx = f"<f>{escape(f)}</f>" if f else ""
            if f and r.get("error"):
                parts.append(f'<c r="{ref}"{sa} t="e">{fx}<v>{SHX_XL_ERR.get(r["error"], "#VALUE!")}</v></c>')
            elif v is None:
                if fx:
                    parts.append(f'<c r="{ref}"{sa} t="str">{fx}<v></v></c>')
                continue
            elif isinstance(v, bool):
                parts.append(f'<c r="{ref}"{sa} t="b">{fx}<v>{1 if v else 0}</v></c>')
            elif isinstance(v, float):
                parts.append(f'<c r="{ref}"{sa}>{fx}<v>{_xl_num(v)}</v></c>')
            elif isinstance(v, date):
                parts.append(f'<c r="{ref}"{sa}>{fx}<v>{(v - _EPOCH).days}</v></c>')
            elif fx:
                parts.append(f'<c r="{ref}"{sa} t="str">{fx}<v>{escape(str(v))}</v></c>')
            else:
                parts.append(f'<c r="{ref}"{sa} t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>')
        if parts:
            cells_xml.append(f'<row r="{ri + 2}">{"".join(parts)}</row>')
    # drop-down lists + colours
    dv_end = max(last_row, 2) + 100           # rows added later in Excel get the list too
    dxfs, cfs, dvs, lists_sheet = [], [], [], []
    prio = 1
    for ci, col in enumerate(book.cols):
        if col["kind"] != "select":
            continue
        opts = [o for o in sh_options(col["options"]) if o.get("label")]
        if not opts:
            continue
        L = sh_col_letter(ci)
        sq = f"{L}2:{L}{dv_end}"
        labels = [o["label"] for o in opts]
        inline = ",".join(labels)
        if len(inline) <= 250 and not any("," in x or '"' in x for x in labels):
            f1 = '"' + inline + '"'
        else:
            k = len(lists_sheet)
            lists_sheet.append(labels)
            LL = sh_col_letter(k)
            f1 = f"'_lists'!${LL}$1:${LL}${len(labels)}"
        dvs.append(f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="{sq}"><formula1>{escape(f1)}</formula1></dataValidation>')
        rules = []
        for o in opts:
            if not o.get("color"):
                continue
            dxfs.append(f'<dxf><fill><patternFill patternType="solid"><bgColor rgb="FF{o["color"][1:].upper()}"/></patternFill></fill></dxf>')
            lit = '"' + o["label"].replace('"', '""') + '"'
            if col["color_mode"] == "row":
                rules.append(f'<cfRule type="expression" dxfId="{len(dxfs) - 1}" priority="{prio}"><formula>{escape(f"${L}2={lit}")}</formula></cfRule>')
            else:
                rules.append(f'<cfRule type="cellIs" dxfId="{len(dxfs) - 1}" priority="{prio}" operator="equal"><formula>{escape(lit)}</formula></cfRule>')
            prio += 1
        if rules:
            rng = f"A2:{sh_col_letter(max(ncols - 1, 0))}{dv_end}" if col["color_mode"] == "row" else sq
            cfs.append(f'<conditionalFormatting sqref="{rng}">{"".join(rules)}</conditionalFormatting>')
    # columns + view
    cols_xml = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{round(max(4.0, (col["width"] or 110) / 7.0), 2)}" customWidth="1"/>'
                       for i, col in enumerate(book.cols))
    dim = f"A1:{sh_col_letter(max(ncols - 1, 0))}{max(last_row, 1)}"
    ws = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{_MAIN}" '
          f'xmlns:r="{_NS}/officeDocument/2006/relationships"><dimension ref="{dim}"/>',
          '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
          '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>',
          f"<cols>{cols_xml}</cols>" if cols_xml else "", f'<sheetData>{"".join(cells_xml)}</sheetData>', "".join(cfs),
          f'<dataValidations count="{len(dvs)}">{"".join(dvs)}</dataValidations>' if dvs else "",
          '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>',
          '<legacyDrawing r:id="rId2"/>' if notes else "", "</worksheet>"]
    sname = _sheet_name(sheet["title"])
    qname = "'" + sname.replace("'", "''") + "'"
    names = []
    for x in book.cells.values():
        if x.get("name") and book.live(x) and _xl_name_ok(x["name"]):
            col_l = sh_col_letter(book.col_idx[x["col_id"]])
            names.append(f'<definedName name="{_q(x["name"])}">{escape(qname)}!${col_l}${book.row_idx[x["row_id"]] + 2}</definedName>')
    sheets = [f'<sheet name="{_q(sname)}" sheetId="1" r:id="rId1"/>']
    if lists_sheet:
        sheets.append('<sheet name="_lists" sheetId="2" state="hidden" r:id="rId3"/>')
    wb = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{_MAIN}" xmlns:r="{_NS}/officeDocument/2006/relationships">'
          f'<bookViews><workbookView/></bookViews><sheets>{"".join(sheets)}</sheets>'
          + (f'<definedNames>{"".join(sorted(names))}</definedNames>' if names else "")
          + '<calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>')
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="{_MAIN}">'
              f'<numFmts count="1"><numFmt numFmtId="164" formatCode="{_q(_currency_fmt(cur))}"/></numFmts>'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
              '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
              '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
              '<xf numFmtId="10" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
              '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
              f'<dxfs count="{len(dxfs)}">{"".join(dxfs)}</dxfs></styleSheet>')
    ct = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{_NS}/package/2006/content-types">',
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>',
          '<Default Extension="vml" ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/>' if notes else "",
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
          '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          if lists_sheet else "",
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
          '<Override PartName="/xl/comments1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/>'
          if notes else "", "</Types>"]
    rel = f"{_NS}/officeDocument/2006/relationships"
    wrels = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_NS}/package/2006/relationships">',
             f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>',
             f'<Relationship Id="rId2" Type="{rel}/styles" Target="styles.xml"/>',
             f'<Relationship Id="rId3" Type="{rel}/worksheet" Target="worksheets/sheet2.xml"/>' if lists_sheet else "", "</Relationships>"]
    parts = {
        "[Content_Types].xml": "".join(ct),
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_NS}/package/2006/relationships">'
                       f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": wb,
        "xl/_rels/workbook.xml.rels": "".join(wrels),
        "xl/styles.xml": styles,
        "xl/worksheets/sheet1.xml": "".join(ws),
    }
    if lists_sheet:
        n = max(len(x) for x in lists_sheet)
        rows = "".join(f'<row r="{i + 1}">' + "".join(f'<c r="{sh_col_letter(k)}{i + 1}" t="inlineStr"><is><t xml:space="preserve">{escape(lab[i])}</t></is></c>'
                                                      for k, lab in enumerate(lists_sheet) if i < len(lab)) + "</row>" for i in range(n))
        parts["xl/worksheets/sheet2.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{_MAIN}">'
                                             f'<sheetData>{rows}</sheetData></worksheet>')
    if notes:
        parts["xl/worksheets/_rels/sheet1.xml.rels"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_NS}/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/comments" Target="../comments1.xml"/>'
            f'<Relationship Id="rId2" Type="{rel}/vmlDrawing" Target="../drawings/vmlDrawing1.vml"/></Relationships>')
        parts["xl/comments1.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><comments xmlns="{_MAIN}"><authors><author>Kalmido</author></authors>'
            "<commentList>" + "".join(f'<comment ref="{ref}" authorId="0"><text><t xml:space="preserve">{escape(t)}</t></text></comment>'
                                      for ref, _r, _c, t in notes) + "</commentList></comments>")
        parts["xl/drawings/vmlDrawing1.vml"] = _vml(notes)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return buf.getvalue()


def _vml(notes):
    """The legacy drawing Excel needs to show notes (comments)."""
    shapes = []
    for i, (_ref, r, ci, _t) in enumerate(notes):
        shapes.append(
            f'<v:shape id="_x0000_s{1025 + i}" type="#_x0000_t202" style="position:absolute;margin-left:59.25pt;margin-top:1.5pt;'
            'width:144pt;height:59.25pt;z-index:1;visibility:hidden" fillcolor="#ffffe1" o:insetmode="auto">'
            '<v:fill color2="#ffffe1"/><v:shadow on="t" color="black" obscured="t"/><v:path o:connecttype="none"/>'
            '<v:textbox style="mso-direction-alt:auto"><div style="text-align:left"></div></v:textbox>'
            f'<x:ClientData ObjectType="Note"><x:MoveWithCells/><x:SizeWithCells/>'
            f'<x:Anchor>{ci + 1}, 15, {r}, 2, {ci + 3}, 15, {r + 4}, 4</x:Anchor><x:AutoFill>False</x:AutoFill>'
            f'<x:Row>{r}</x:Row><x:Column>{ci}</x:Column></x:ClientData></v:shape>')
    return ('<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" '
            'xmlns:x="urn:schemas-microsoft-com:office:excel"><o:shapelayout v:ext="edit"><o:idmap v:ext="edit" data="1"/></o:shapelayout>'
            '<v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202" path="m,l,21600r21600,l21600,xe">'
            '<v:stroke joinstyle="miter"/><v:path gradientshapeok="t" o:connecttype="rect"/></v:shapetype>' + "".join(shapes) + "</xml>")


# ---------------------------------------------------------------- import: reading
class ShxGrid:
    """What an import reads from a file: rows of cells {v: text value, f: Excel formula | None, fmt: 'date'|'percent'|'currency'|
    None}, select columns {col index: [labels]}, option colours {col index: {label: color}}, row colouring {col index},
    cell names {name: (row, col)} (0-based, header included)."""

    def __init__(self):
        self.rows, self.lists, self.colors, self.row_mode, self.names = [], {}, {}, set(), {}


def _shx_too_many():
    """2.89.0 (#1916): review 5, counted while reading (the header row may come on top)."""
    return BadInput(tr("Too many filled cells (at most {0})", SHX_CELLS_MAX))


def shx_read_csv(raw):
    """A CSV file (UTF-8 with or without BOM, else Windows-1252) -> ShxGrid."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    text = text.replace("\x00", "")
    head = text[:4096]
    first = head.split("\n", 1)[0]
    delim = max((";", ",", "\t"), key=lambda d: first.count(d))
    if not any(first.count(d) for d in (";", ",", "\t")):
        delim = ";"
    g = ShxGrid()
    full = 0
    try:
        for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=delim)):
            if i > SH_ROWS_MAX + 1:
                raise BadInput(tr("Too many rows (at most {0})", SH_ROWS_MAX))
            full += sum(1 for x in row[:SH_COLS_MAX + 1] if x != "")
            if full > SHX_CELLS_MAX + SH_COLS_MAX:
                raise _shx_too_many()
            g.rows.append([{"v": csv_uncell(x), "f": None, "fmt": None} for x in row[:SH_COLS_MAX + 1]])  # 2.273.0 D (#3051)
    except csv.Error:
        raise BadInput(tr("This file could not be read")) from None
    return g


def _num_fmts(z, names, budget):
    """{style index: 'date' | 'percent' | 'currency' | None} of the workbook's cell formats."""
    if "xl/styles.xml" not in names:
        return {}, []
    st = _budget_xml(z, "xl/styles.xml", budget)
    custom = {}
    dxf_fill = []
    for el in st:
        tag = _local(el.tag)
        if tag == "numFmts":
            for nf in el:
                try:
                    custom[int(nf.get("numFmtId"))] = nf.get("formatCode") or ""
                except (TypeError, ValueError):
                    pass
        elif tag == "dxfs":
            for dx in el:
                col = None
                for x in dx.iter():
                    if _local(x.tag) in ("bgColor", "fgColor") and x.get("rgb"):
                        col = x.get("rgb")
                        break
                dxf_fill.append(("#" + col[-6:].lower()) if col and re.fullmatch(r"[0-9A-Fa-f]{6,8}", col) else None)
    out = {}
    for el in st:
        if _local(el.tag) != "cellXfs":
            continue
        for i, xf in enumerate(el):
            try:
                nid = int(xf.get("numFmtId") or 0)
            except ValueError:
                nid = 0
            code = custom.get(nid, "")
            plain = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", code)  # without quoted text, escapes and [colour] / [$€-407]
            if nid in _XL_DATE_FMTS or (code and re.search(r"[dy]", plain, re.I) and not re.search(r"[h]", plain, re.I)):
                out[i] = "date"
            elif nid in _XL_PCT_FMTS or "%" in plain:
                out[i] = "percent"
            elif nid in (5, 6, 7, 8, 42, 44) or re.search(r"[€$£]|\[\$|CHF|EUR|USD", code):
                out[i] = "currency"
    return out, dxf_fill


def _shift_formula(f, dr, dc):
    """A shared formula's text moved by dr rows / dc columns (relative references only)."""
    def mv(m):
        cabs, col, rabs, row = m.group(1), m.group(2), m.group(3), m.group(4)
        if not cabs:
            col = sh_col_letter(_col_index(col.upper()) + dc)
        if not rabs:
            row = str(int(row) + dr)
        return f"{cabs}{col}{rabs}{row}"
    parts = re.split(r'("(?:[^"]|"")*")', f)
    return "".join(p if p.startswith('"') else re.sub(r"(?<![\w.])(\$?)([A-Za-z]{1,3})(\$?)(\d{1,7})(?![\w(])", mv, p) for p in parts)


def shx_read_xlsx(raw):
    """The first sheet of an .xlsx -> ShxGrid (values, formulas, number formats, drop-down lists, their colours, names)."""
    if not raw.startswith(b"PK"):
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)"))
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = set(z.namelist())
    except (zipfile.BadZipFile, ValueError):
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)")) from None
    if "xl/workbook.xml" not in names or len(names) > 2000:
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)"))
    budget = [0]
    try:
        return _read_xlsx(z, names, budget)
    except BadInput:
        raise
    except (ET.ParseError, KeyError, ValueError, IndexError, zipfile.BadZipFile, zlib.error, EOFError, RuntimeError):
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)")) from None


def shx_read_xlsx_all(raw, most):
    """2.124.0 E (#2116): every visible sheet of an .xlsx (at most `most`) -> [ShxGrid] with .sheet_name; the cell limit counts
    for all sheets together."""
    first = shx_read_xlsx(raw)
    if first.n_sheets < 2 or most < 2:
        return [first]
    z = zipfile.ZipFile(io.BytesIO(raw))
    names, budget, ctx = set(z.namelist()), [0], {}
    try:
        out = [first] + [_read_xlsx(z, names, budget, k, ctx) for k in range(1, min(first.n_sheets, most))]
    except BadInput:
        raise
    except (ET.ParseError, KeyError, ValueError, IndexError, zipfile.BadZipFile, zlib.error, EOFError, RuntimeError):
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)")) from None
    if sum(1 for g in out for r in g.rows for x in r if (x.get("v") or "") != "" or x.get("f")) > SHX_CELLS_MAX:
        raise _shx_too_many()
    return out


def _budget_xml(z, name, budget):
    if z.getinfo(name).file_size + budget[0] > SHX_UNZIPPED_MAX:
        raise BadInput(tr("The file is too large"))
    budget[0] += z.getinfo(name).file_size
    data = z.read(name)
    if b"<!DOCTYPE" in data[:4096].upper() or b"<!ENTITY" in data.upper() \
            or data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:4]:  # no entity tricks; 2.148.1 G (#2496): single-byte encodings only
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)"))
    return ET.fromstring(data)


def _read_xlsx(z, names, budget, which=0, ctx=None):
    """The visible sheet number `which` (2.124.0 E #2116: ctx = the parts every sheet shares, read once for all of them)."""
    ctx = {} if ctx is None else ctx
    if "wb" not in ctx:
        strings = []
        if "xl/sharedStrings.xml" in names:
            for si in _budget_xml(z, "xl/sharedStrings.xml", budget):
                if _local(si.tag) == "si":
                    strings.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t" and not _in_rph(si, t)))
        fmts, dxf_fill = _num_fmts(z, names, budget)
        wb = _budget_xml(z, "xl/workbook.xml", budget)
        wrels = _rels(z, "xl/workbook.xml", [0])
        sheets = []  # (name, path, hidden)
        for sh in wb.iter():
            if _local(sh.tag) == "sheet":
                rid = next((v for k, v in sh.attrib.items() if _local(k) == "id"), None)
                if wrels.get(rid) in names:
                    sheets.append(((sh.get("name") or ""), wrels[rid], sh.get("state") in ("hidden", "veryHidden")))
        ctx.update(strings=strings, fmts=fmts, dxf_fill=dxf_fill, wb=wb, sheets=sheets)
    strings, fmts, dxf_fill, wb, sheets = ctx["strings"], ctx["fmts"], ctx["dxf_fill"], ctx["wb"], ctx["sheets"]
    visible = [s for s in sheets if not s[2]] or sheets
    if not visible or which >= len(visible):
        raise BadInput(tr("This is not a spreadsheet file (.xlsx)"))
    sname, path, _h = visible[which]
    g = ShxGrid()
    g.sheet_name, g.n_sheets = sname, len(visible)  # 2.124.0 E (#2116)
    cells, shared, full = {}, {}, 0
    root = _budget_xml(z, path, budget)
    dvs, cfs = [], []
    for el in root:
        tag = _local(el.tag)
        if tag == "dataValidations":
            dvs = [x for x in el if _local(x.tag) == "dataValidation"]
        elif tag == "conditionalFormatting":
            cfs.append(el)
    for row in root.iter(f"{{{_MAIN}}}row"):
        r = int(row.get("r") or (max((k[0] for k in cells), default=0) + 1))
        if r > SH_ROWS_MAX + 1:
            raise BadInput(tr("Too many rows (at most {0})", SH_ROWS_MAX))
        for k, cel in enumerate(x for x in row if _local(x.tag) == "c"):
            ref = cel.get("r")
            ci = _col_index(ref) if ref else k
            if ci >= SH_COLS_MAX:
                continue
            t, v, f = cel.get("t"), None, None
            for ch in cel:
                tag = _local(ch.tag)
                if tag == "v":
                    v = ch.text or ""
                elif tag == "is":
                    v = "".join(x.text or "" for x in ch.iter() if _local(x.tag) == "t")
                elif tag == "f":
                    if ch.get("t") == "shared":
                        si = ch.get("si")
                        if ch.text:
                            shared[si] = (ch.text, r, ci)
                            f = ch.text
                        elif si in shared:
                            base, r0, c0 = shared[si]
                            f = _shift_formula(base, r - r0, ci - c0)
                    elif ch.get("t") != "array" and ch.text:
                        f = ch.text
                    elif ch.text:
                        f = "\x00array"  # an array formula: its value only
            if t == "s" and v is not None:
                try:
                    v = strings[int(v)]
                except (ValueError, IndexError):
                    v = ""
            elif t == "b" and v is not None:
                v = "WAHR" if v == "1" else "FALSCH"
            elif t == "e":
                v = ""
            elif t in (None, "n") and v and re.fullmatch(r"-?\d+\.0+", v):
                v = v.split(".")[0]
            try:
                fmt = fmts.get(int(cel.get("s") or 0))
            except ValueError:
                fmt = None
            if v is None and f is None:
                continue
            if fmt == "date" and t in (None, "n") and v and re.fullmatch(r"-?\d+(\.\d+)?", v):
                try:
                    v = (_EPOCH + timedelta(days=int(float(v)))).isoformat()
                except (OverflowError, ValueError):
                    pass
            if v or f:
                full += 1
                if full > SHX_CELLS_MAX + SH_COLS_MAX:
                    raise _shx_too_many()
            cells[(r, ci)] = {"v": v or "", "f": f, "fmt": fmt, "num": t in (None, "n") and bool(v)}
    if cells:
        # 2.148.1 D (#2485): no full grid of empty cells: each row only up to its last cell, empty places share one entry
        h = max(k[0] for k in cells)
        last = {}
        for (r, ci) in cells:
            last[r] = max(last.get(r, -1), ci)
        g.rows = [[cells.get((r, ci)) or _SHX_EMPTY for ci in range(last.get(r, -1) + 1)] for r in range(1, h + 1)]
    # drop-down lists of whole columns
    for dv in dvs:
        if dv.get("type") != "list":
            continue
        f1 = next((x.text or "" for x in dv if _local(x.tag) == "formula1"), "")
        labels = _dv_labels(z, names, budget, sheets, f1)
        if not labels:
            continue
        for rg in (dv.get("sqref") or "").split():
            m = re.fullmatch(r"\$?([A-Z]{1,3})\$?\d+(?::\$?([A-Z]{1,3})\$?\d+)?", rg)
            if m:
                for ci in range(_col_index(m.group(1)), _col_index(m.group(2) or m.group(1)) + 1):
                    if ci < SH_COLS_MAX:
                        g.lists.setdefault(ci, labels[:100])
    # their colours: cellIs equal "x" (the cell) or the expression $C2="x" (the row)
    for cf in cfs:
        sq = (cf.get("sqref") or "").split()
        for rule in cf:
            if _local(rule.tag) != "cfRule":
                continue
            try:
                color = dxf_fill[int(rule.get("dxfId"))]
            except (TypeError, ValueError, IndexError):
                color = None
            fx = next((x.text or "" for x in rule if _local(x.tag) == "formula"), "")
            if not color:
                continue
            if rule.get("type") == "cellIs" and rule.get("operator") == "equal":
                m = re.fullmatch(r'"((?:[^"]|"")*)"', fx.strip())
                if m and sq:
                    m2 = re.match(r"\$?([A-Z]{1,3})", sq[0])
                    if m2:
                        g.colors.setdefault(_col_index(m2.group(1)), {})[m.group(1).replace('""', '"')] = color
            elif rule.get("type") == "expression":
                m = re.fullmatch(r'\$([A-Z]{1,3})\$?\d+\s*=\s*"((?:[^"]|"")*)"', fx.strip())
                if m:
                    ci = _col_index(m.group(1))
                    g.colors.setdefault(ci, {})[m.group(2).replace('""', '"')] = color
                    g.row_mode.add(ci)
    # names of single cells of this sheet
    for dn in wb.iter(f"{{{_MAIN}}}definedName"):
        nm, val = dn.get("name") or "", (dn.text or "").strip()
        if dn.get("localSheetId") not in (None, str(sheets.index(visible[which]))) or nm.startswith("_xlnm"):
            continue
        m = re.fullmatch(r"(?:'((?:[^']|'')+)'|([^'!]+))!\$?([A-Z]{1,3})\$?(\d+)", val)
        if m and (m.group(1) or m.group(2) or "").replace("''", "'") == sname:
            g.names[nm] = (int(m.group(4)) - 1, _col_index(m.group(3)))
    return g


def _in_rph(si, t):
    for rph in si:
        if _local(rph.tag) == "rPh" and any(x is t for x in rph.iter()):
            return True
    return False


def _dv_labels(z, names, budget, sheets, f1):
    """The labels of a list validation: inline "a,b,c" or a range of a sheet of the file."""
    f1 = (f1 or "").strip()
    if f1.startswith('"') and f1.endswith('"'):
        return [x.strip() for x in f1[1:-1].replace('""', '"').split(",") if x.strip()][:100]
    m = re.fullmatch(r"(?:'((?:[^']|'')+)'|([^'!]+))!\$?([A-Z]{1,3})\$?(\d+):\$?([A-Z]{1,3})\$?(\d+)", f1)
    if not m:
        return []
    want = (m.group(1) or m.group(2) or "").replace("''", "'")
    path = next((p for n, p, _h in sheets if n == want), None)
    if not path:
        return []
    c1, r1, c2, r2 = _col_index(m.group(3)), int(m.group(4)), _col_index(m.group(5)), int(m.group(6))
    if r2 - r1 > 200 or c2 - c1 > 0:
        return []
    strings = []
    if "xl/sharedStrings.xml" in names:
        for si in _budget_xml(z, "xl/sharedStrings.xml", budget):
            if _local(si.tag) == "si":
                strings.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
    out = {}
    for row in _budget_xml(z, path, budget).iter(f"{{{_MAIN}}}row"):
        r = int(row.get("r") or 0)
        if not r1 <= r <= r2:
            continue
        for cel in row:
            if _local(cel.tag) != "c" or _col_index(cel.get("r") or "A") != c1:
                continue
            v = None
            for ch in cel:
                if _local(ch.tag) == "v":
                    v = ch.text or ""
                elif _local(ch.tag) == "is":
                    v = "".join(x.text or "" for x in ch.iter() if _local(x.tag) == "t")
            if cel.get("t") == "s" and v is not None:
                try:
                    v = strings[int(v)]
                except (ValueError, IndexError):
                    v = None
            if v:
                out[r] = v.strip()
    return [out[k] for k in sorted(out)][:100]


# ---------------------------------------------------------------- import: into a sheet
def shx_kalmido_formula(f, hdr, names_at, xsheets=None):
    """An Excel formula -> the Kalmido input (German names, ";", addresses moved up by the header row), or None when it has
    something Kalmido cannot take (other sheets, whole columns, unknown functions, names that are no cell of this sheet).
    2.124.0 E (#2116): xsheets = {Excel sheet name: (Kalmido sheet name, its header rows)} -- other sheets of the file."""
    if not f or f.startswith("\x00"):
        return None
    try:
        toks = sh_tokens(f)
    except ShErr:
        return None
    out, v3 = [], shf_vlookup3(toks)
    for i, (kind, val, a, b) in enumerate(toks):
        if i in v3:  # 2.124.0 A (#2109): Excel's VLOOKUP without the fourth argument looks up approximately
            out.append(";WAHR")
        if kind == "num":
            out.append(_xl_num(val))
        elif kind == "str":
            out.append('"' + val.replace('"', '""') + '"')
        elif kind in ("op", "cmp", "(", ")", ":", "%"):
            out.append(val)
        elif kind == "sep":
            out.append(";")
        elif kind == "a1":
            letters, num = val
            if num - hdr < 1:
                return None
            out.append(f"{letters}{num - hdr}")
        elif kind == "fn":
            name = re.sub(r"^_xl(fn|ws)\.", "", val, flags=re.I).upper()
            if name not in SHX_KALMIDO_FN:
                return None
            out.append(SHX_KALMIDO_FN[name])
        elif kind == "xref" and xsheets and val[0] in xsheets:  # 2.124.0 E (#2116): Sheet2!A1, 'My sheet'!A1:B5
            from .shbook import shb_quote
            to, h = xsheets[val[0]]
            if val[1][1] - h < 1 or (val[2] and val[2][1] - h < 1):
                return None
            out.append(shb_quote(to) + "!" + f"{val[1][0]}{val[1][1] - h}" + (f":{val[2][0]}{val[2][1] - h}" if val[2] else ""))
        elif kind == "ident":
            up = val.upper()
            if up in ("TRUE", "WAHR"):
                out.append("WAHR")
            elif up in ("FALSE", "FALSCH"):
                out.append("FALSCH")
            elif val in names_at:
                out.append(val)  # a cell name: the import gives the cell this name
            else:
                return None
        else:
            return None
    return "=" + "".join(out)


def _guess_kind(vals, fmts):
    """The column kind of an import column from its non-empty values (text) and their number formats."""
    vals = [v for v in vals if v != ""]
    if not vals:
        return "text"
    if shk_guess(vals):  # 2.124.0 B (#2110): truth values only
        return "checkbox"
    if any(f == "date" for f in fmts) and all(sh_parse_date(v) for v in vals):
        return "date"
    if all(sh_parse_date(v) for v in vals):
        return "date"
    pct = [f for f in fmts if f == "percent"]
    if pct and len(pct) * 2 >= len(vals) and all(sh_parse_number(v) is not None for v in vals):
        return "percent"
    if all(sh_parse_number(v) is not None for v in vals) and not any(re.match(r"\s*0\d", v) for v in vals):  # 01234: a code
        if any(f == "currency" for f in fmts) or any(re.search(r"[€$£]", v) for v in vals):
            return "currency"
        if all(v.strip().endswith("%") for v in vals):
            return "percent"
        return "number"
    return "text"


def _is_header(row, nxt):
    """Is the first row a header (titles): text only (no numbers / dates / formulas) and something below it."""
    vals = [x for x in row if (x.get("v") or "").strip()]
    if not vals or nxt is None:
        return False
    return all(x.get("f") is None and not x.get("num") and sh_parse_number(x["v"]) is None and not sh_parse_date(x["v"])
               for x in vals)


def shx_import(c, uid, grid, space, title, list_id=None, into=None):
    """A new sheet from a read file -> (sheet id, report). Formulas that Kalmido cannot take are kept as their value.
    2.124.0 E (#2116): into = the first sheet of a table: a further sheet of it named title; a formula into another sheet of
    the file is kept as its value and noted in grid.xlater (sheets/shbook.py shb_import sets it once all sheets are there)."""
    rows = grid.rows
    while rows and not any((x.get("v") or "") != "" or x.get("f") for x in rows[-1]):
        rows.pop()
    width = max((max((i + 1 for i, x in enumerate(r) if (x.get("v") or "") != "" or x.get("f")), default=0) for r in rows), default=0)
    width = max(width, max((ci + 1 for ci in grid.lists), default=0))
    if width > SH_COLS_MAX:
        raise BadInput(tr("Too many columns (at most {0})", SH_COLS_MAX))
    first_empty = bool(rows) and len(rows) > 1 and not any((x.get("v") or "").strip() or x.get("f") for x in rows[0])
    hdr = 1 if rows and (first_empty or _is_header(rows[0], rows[1] if len(rows) > 1 else None)) else 0  # an empty first row = untitled
    data = rows[hdr:]
    if len(data) > SH_ROWS_MAX:
        raise BadInput(tr("Too many rows (at most {0})", SH_ROWS_MAX))
    if sum(1 for r in data for x in r if (x.get("v") or "") != "" or x.get("f")) > SHX_CELLS_MAX:
        raise BadInput(tr("The file is too large"))
    titles = [(rows[0][ci].get("v") or "").strip()[:80] if hdr and ci < len(rows[0]) else "" for ci in range(width)]
    columns = []
    for ci in range(width):
        vals = [(r[ci].get("v") or "") if ci < len(r) else "" for r in data]  # a formula's cached value counts too
        fmts = [r[ci].get("fmt") for r in data if ci < len(r)]
        if ci in grid.lists:
            colors = grid.colors.get(ci, {})
            opts = [{"label": lab, "color": colors.get(lab, "")} for lab in grid.lists[ci]]
            columns.append({"title": titles[ci], "kind": "select", "options": opts,
                            "color_mode": "row" if ci in grid.row_mode else "cell"})
        else:
            columns.append({"title": titles[ci], "kind": _guess_kind(vals, fmts)})
    report = {"rows": len(data), "columns": width, "formulas": 0, "as_value": 0, "options_added": 0, "names": 0}
    grid.hdr = hdr  # 2.124.0 E (#2116)
    if into is not None:
        from .shbook import shb_create
        sid = shb_create(c, into, uid, title, columns=columns or None, rows=max(len(data), 1))
    else:
        sid = sh_create(c, uid, space, title, list_id, columns=columns or None, rows=max(len(data), 1))
    sheet = sh_reload(c, sid)
    book = ShBook(c, sheet)
    book.shh_off = True  # 2.124.0 B (#2112): a new table from a file has no history of its own
    plain, later = [], []
    names_at = {nm: (r - hdr, ci) for nm, (r, ci) in grid.names.items() if r - hdr >= 0 and ci < width}
    for ri, r in enumerate(data):
        rid = book.rows[ri]["id"]
        for ci in range(min(width, len(r))):
            x = r[ci]
            v, f = x.get("v") or "", x.get("f")
            col = book.cols[ci]
            if f:
                kf = shx_kalmido_formula(f, hdr, names_at)
                if kf:
                    later.append((rid, col["id"], kf, v))
                    continue
                report["as_value"] += 1
                if "!" in f and hasattr(grid, "xlater"):  # 2.124.0 E (#2116): maybe another sheet of the file
                    grid.xlater.append((rid, col["id"], f, v, names_at))
            if v == "":
                continue
            if v.startswith("="):
                v = "'" + v  # text, never a formula from a value
            if col["kind"] == "percent":
                n = sh_parse_number(v.rstrip("%").strip())
                if n is not None and not v.strip().endswith("%") and x.get("num"):
                    v = _xl_num(n * 100)  # Excel keeps 19 % as 0.19
            elif col["kind"] == "select" and v not in grid.lists.get(ci, []):
                report["options_added"] += 1
            plain.append({"row_id": rid, "col_id": col["id"], "raw": v})
    for i in range(0, len(plain), SHX_CHUNK):
        _write_cells(c, sheet, plain[i:i + SHX_CHUNK], uid, None, None, book)
    # names first (formulas may use them), then each formula on its own: one Kalmido cannot read is kept as its value
    for nm, (ri, ci) in names_at.items():
        if not sh_name_ok(nm) or ri >= len(book.rows) or nm.lower() in book.names() or nm.lower() in book.slug_col:
            continue
        x = book.ensure(book.rows[ri]["id"], book.cols[ci]["id"], uid)
        c.execute("UPDATE sheet_cells SET name=? WHERE id=?", (nm, x["id"]))
        x["name"] = nm
        report["names"] += 1
    ok = []
    for rid, col_id, kf, v in later:
        try:
            with c.savepoint():
                sh_to_internal(c, sheet, kf, uid, book)
            ok.append({"row_id": rid, "col_id": col_id, "raw": kf})
            report["formulas"] += 1
        except BadInput:
            report["as_value"] += 1
            if v != "":
                ok.append({"row_id": rid, "col_id": col_id, "raw": ("'" + v) if v.startswith("=") else v})
    book = ShBook(c, sheet)
    book.shh_off = True  # 2.124.0 B (#2112)
    for i in range(0, len(ok), SHX_CHUNK):
        _write_cells(c, sheet, ok[i:i + SHX_CHUNK], uid, None, None, book)
    sh_touch(c, sid, uid)
    return sid, report


def shx_report_text(rep):
    """The import's result in words (translated)."""
    out = [tr("{0} rows and {1} columns imported", rep["rows"], rep["columns"])]
    if rep.get("sheets", 1) > 1:  # 2.124.0 E (#2116)
        out.append(tr("{0} sheets imported", rep["sheets"]))
    if rep.get("sheets_total", 0) > rep.get("sheets", 1):
        out.append(tr("{0} sheets left out (at most {1} per table)", rep["sheets_total"] - rep["sheets"], rep["sheets"]))
    if rep["formulas"]:
        out.append(tr("{0} formulas taken over", rep["formulas"]))
    if rep["as_value"]:
        out.append(tr("{0} formulas taken over as a value", rep["as_value"]))
    if rep["options_added"]:
        out.append(tr("{0} values added as new choices", rep["options_added"]))
    return out


# ---------------------------------------------------------------- routes
@app.get("/api/sheets/<int:sid>/export.csv")
def shx_export_csv(sid):
    """The values as CSV (formulas as their result, evaluated for you)."""
    c = db()
    r = sh_need(c, sid)
    data = shx_csv(c, r)
    c.commit()  # sheet_lastvals of the viewer
    return Response(data, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": _disposition(shx_file_name(r["title"], "csv")), "Cache-Control": "no-store"})


@app.get("/api/sheets/<int:sid>/export.xlsx")
def shx_export_xlsx(sid):
    """Values, formulas Excel understands, formats, drop-down lists and colours as .xlsx."""
    c = db()
    r = sh_need(c, sid)
    from .shbook import shb_xlsx
    data, title = shb_xlsx(c, r)  # 2.124.0 E (#2116): every sheet of the table
    c.commit()
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": _disposition(shx_file_name(title, "xlsx")), "Cache-Control": "no-store"})


@app.post("/api/sheets/import")
def shx_import_post():
    """multipart: file (.csv / .xlsx), space (private | org:N), list_id?, title? -> {sheet, report, messages} (201)."""
    need_feat("sheets")
    c = db()
    uid = me()
    f = request.files.get("file")
    if not f:
        raise BadInput(tr("No file"))
    raw = f.read(SHX_FILE_MAX + 1)
    if len(raw) > SHX_FILE_MAX:
        raise BadInput(tr("The file is too large (at most {0} MB)", SHX_FILE_MAX // (1024 * 1024)))
    name = f.filename or ""
    lid = request.form.get("list_id")
    try:
        lid = int(lid) if lid not in (None, "", "null") else None
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "list_id")) from None
    if raw.startswith(b"PK") or name.lower().endswith(".xlsx"):
        from .shbook import SHB_TABS_MAX
        grid = shx_read_xlsx_all(raw, SHB_TABS_MAX)  # 2.124.0 E (#2116): every sheet of the file
    elif name.lower().endswith((".csv", ".txt", ".tsv")) or not name:
        grid = shx_read_csv(raw)
    else:
        raise BadInput(tr("Only .csv and .xlsx files can be imported"))
    title = (request.form.get("title") or re.sub(r"\.(csv|xlsx|txt|tsv)$", "", name, flags=re.I) or "").strip()
    from .shbook import shb_import
    sid, rep = shb_import(c, uid, grid, request.form.get("space") or "private", title, lid)  # 2.124.0 E (#2116)
    c.commit()
    r = sh_reload(c, sid)
    return jsonify(sheet=sh_brief(c, [r], uid)[0], report=rep, messages=shx_report_text(rep)), 201

