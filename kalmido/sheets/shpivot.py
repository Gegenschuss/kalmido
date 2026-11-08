"""2.671.0 (#3463 b): the pivot sheet of a table -- a further sheet (sheets/shbook.py) with a setting instead of cells.

sheets.pivot holds {source, rows, cols, values, filter, updated_at} (JSON, sheet and column ids only; '' = an ordinary sheet):
  source   the id of another (ordinary, live) sheet of the same table
  rows     0-3 column ids of the source: one result row per combination of their values
  cols     null or one column id: its values become the result's columns
  values   1-6 {col, agg}: agg sum | count | avg of that column per cell (col null + count = the number of rows)
  filter   0-5 {col, values: [shown texts]}: only source rows whose cell shows one of them

The result is never stored: every read computes it from the source sheet, evaluated for the viewer (the same evaluator as the
source's own view, so Kalmido values are the viewer's), with the formula functions SUM / AVERAGE (formula.py ShEval.fn), so a
pivot and =SUMME() over the same cells give the same numbers. A change of the source counts the whole table's rev up
(shb_touch) and bumps the area, so an open pivot reloads by the usual live way. Rights: the table's (sh_need on the table; a
pivot sheet itself takes no write: core.py sh_need -> 409), the setting is saved under the sheet's lock with the version check
of the core (conflict.py ccf_check, expect_updated_at). Export: .xlsx and CSV write the computed values.
"""
import csv
import io as _io
import json
import math

from flask import jsonify

from ..core.config import app
from ..core.access import Denied
from ..core.conflict import ccf_check, take_version
from ..core.db import body, db, iso_ms, now_utc
from ..core.errors import BadInput
from ..core.i18n import dec_comma, lang, tr
from ..core.pg import write_lock
from ..accounts.session import me
from .core import ShBook, ShEvaluator, sh_currency, sh_touch
from ..personal.timetrack import _csv_cell
from .formula import ShErr, ShEval, sh_col_letter, sh_fmt, sh_json_value
from .shbook import _need_book, _need_tab, shb_bid, shb_label, shb_rows
from .shhist import shh_meta_note

SHP_ROW_FIELDS = 3
SHP_VALUES = 6
SHP_FILTERS = 5
SHP_FILTER_VALUES = 200
SHP_SPEC_MAX = 20_000    # review R2 F2: the whole setting as JSON (it is saved with every change in the history, old and new)
SHP_ROWS_MAX = 2000      # result rows; more -> truncated
SHP_COLS_MAX = 50        # values of the column field; more -> truncated
SHP_AGGS = ("sum", "count", "avg")
SHP_NUM_KINDS = ("number", "currency", "percent")


def shp_is(r):
    """Is sheet row r a pivot sheet?"""
    try:
        return bool(r["pivot"])
    except (KeyError, IndexError, TypeError):
        return False


def shp_load(r):
    """The stored setting of pivot sheet r (a dict; {} when none or unreadable)."""
    try:
        v = json.loads(r["pivot"] or "{}")
    except (KeyError, IndexError, TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def _id(v, what):
    if isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 2 ** 62:
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def shp_clean(c, first, b, self_id=None):
    """The setting of body b checked against table `first` -> the dict to store (without updated_at); BadInput when wrong."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "pivot"))
    src = _id(b.get("source"), "source")
    tab = next((x for x in shb_rows(c, first["id"]) if x["id"] == src), None)
    if tab is None or src == self_id or shp_is(tab):
        raise BadInput(tr("Select an ordinary sheet of this table as the source"))
    live = {r[0] for r in c.execute("SELECT id FROM sheet_columns WHERE sheet_id=? AND deleted_at IS NULL", (src,)).fetchall()}

    def col(v, what, none=False):
        if v is None and none:
            return None
        if _id(v, what) not in live:
            raise BadInput(tr("There is no such column in the source sheet"))
        return v

    rows = b.get("rows") if b.get("rows") is not None else []
    if not isinstance(rows, list) or len(rows) > SHP_ROW_FIELDS:
        raise BadInput(tr("Invalid value: {0}", "rows"))
    rows = list(dict.fromkeys(col(x, "rows") for x in rows))
    cols = col(b.get("cols"), "cols", none=True)
    if cols is not None and cols in rows:
        raise BadInput(tr("A column cannot be a row and a column field at once"))
    vals = b.get("values")
    if not isinstance(vals, list) or not 1 <= len(vals) <= SHP_VALUES:
        raise BadInput(tr("Invalid value: {0}", "values"))
    out_v = []
    for v in vals:
        if not isinstance(v, dict) or v.get("agg") not in SHP_AGGS:
            raise BadInput(tr("Invalid value: {0}", "values"))
        cid = col(v.get("col"), "values", none=v.get("agg") == "count")
        out_v.append({"col": cid, "agg": v["agg"]})
    flt = b.get("filter") if b.get("filter") is not None else []
    if not isinstance(flt, list) or len(flt) > SHP_FILTERS:
        raise BadInput(tr("Invalid value: {0}", "filter"))
    out_f = []
    for f in flt:
        if not isinstance(f, dict) or not isinstance(f.get("values"), list) or len(f["values"]) > SHP_FILTER_VALUES \
                or not all(isinstance(x, str) and len(x) <= 500 for x in f["values"]):
            raise BadInput(tr("Invalid value: {0}", "filter"))
        out_f.append({"col": col(f.get("col"), "filter"), "values": list(dict.fromkeys(f["values"]))})
    out = {"source": src, "rows": rows, "cols": cols, "values": out_v, "filter": out_f}
    if len(json.dumps(out)) > SHP_SPEC_MAX:  # review R2 F2: no bloating of the table and its history through the filter values
        raise BadInput(tr("Invalid value: {0}", "filter"))
    return out


def shp_dump(spec):
    return json.dumps(dict(spec, updated_at=iso_ms(now_utc())), separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------- computing
class _Env:
    """The env of formula.py ShEval for one aggregate: the column node gives the group's values."""

    def __init__(self, vals, lg):
        self.vals, self.lg = vals, lg

    def col(self, _cid):
        return self.vals


def shp_agg(agg, vals, lg="de"):
    """sum / avg as SUMME / MITTELWERT of the formulas over the values (numbers count, text / empty / truth values not);
    count = the non-empty cells (as a spreadsheet's pivot counts). None when there is nothing to average."""
    if agg == "count":
        return float(sum(1 for v in vals if v is not None and v != ""))
    try:
        return ShEval(_Env(vals, lg)).fn(agg, [("col", 0)])
    except ShErr:
        return None


def _skey(v, label):
    """The order of group keys: numbers, dates, texts (case-insensitive), the empty one last."""
    if label == "":
        return (9, 0, "")
    if isinstance(v, float) and not isinstance(v, bool):
        return (0, v, "")
    if hasattr(v, "toordinal"):
        return (1, v.toordinal(), "")
    return (2, 0, label.casefold())


def _cell(v, d):
    return {"v": v, "d": d}


def shp_compute(c, r, uid=None):
    """The result of pivot sheet r for viewer uid: {header, rows, total, keys, truncated, error, source}."""
    uid = uid or me()
    spec = shp_load(r)
    lg = lang()
    out = {"header": [], "rows": [], "total": None, "keys": 0, "truncated": False, "error": None, "source": None}
    src = next((x for x in shb_rows(c, shb_bid(r)) if x["id"] == spec.get("source")), None)
    if src is None or shp_is(src):
        out["error"] = tr("The source sheet is gone: select another one")
        return out
    out["source"] = {"id": src["id"], "name": shb_label(src)}
    book = ShBook(c, src)
    res = ShEvaluator(c, book, uid).run()
    cur = sh_currency(c, src)
    titles = {x["id"]: (x["title"] or "") for x in book.cols}
    kinds = {x["id"]: x["kind"] for x in book.cols}
    rows_f = [x for x in spec.get("rows") or [] if x in book.col_idx]
    col_f = spec.get("cols") if spec.get("cols") in book.col_idx else None
    vals_f = [v for v in spec.get("values") or [] if v.get("agg") in SHP_AGGS and (v.get("col") in book.col_idx
                                                                                    or (v.get("col") is None and v.get("agg") == "count"))]
    if not vals_f:
        vals_f = [{"col": None, "agg": "count"}]
    flt = [(f["col"], set(f.get("values") or [])) for f in spec.get("filter") or [] if f.get("col") in book.col_idx]
    out["keys"] = len(rows_f)

    def at(row, cid):
        x = book.at.get((row["id"], cid))
        rr = res.get(x["id"]) if x else None
        if not rr:
            return None, ""
        if rr.get("error"):
            return None, tr("Error")
        return rr.get("_v"), rr.get("display") or ""

    data = []  # (row keys [(v, label)], column key (v, label), {value index: value})
    for row in book.rows:
        if not any((x["raw"] or "") != "" or x["frozen"] for x in (book.at.get((row["id"], cc["id"])) for cc in book.cols) if x):
            continue  # an empty row is no record
        if any(at(row, cid)[1] not in want for cid, want in flt):
            continue
        rk = tuple(at(row, cid) for cid in rows_f)
        ck = at(row, col_f) if col_f else None
        vs = [at(row, v["col"])[0] if v["col"] is not None else True for v in vals_f]
        data.append((rk, ck, vs))

    rkeys = {}
    for rk, _ck, _vs in data:
        rkeys.setdefault(tuple(lab for _v, lab in rk), rk)
    rorder = sorted(rkeys, key=lambda k: tuple(_skey(v, lab) for v, lab in rkeys[k]))
    ckeys = {}
    if col_f:
        for _rk, ck, _vs in data:
            ckeys.setdefault(ck[1], ck)
    corder = sorted(ckeys, key=lambda k: _skey(*ckeys[k]))
    if len(corder) > SHP_COLS_MAX:
        corder, out["truncated"] = corder[:SHP_COLS_MAX], True
    if len(rorder) > SHP_ROWS_MAX:
        rorder, out["truncated"] = rorder[:SHP_ROWS_MAX], True

    def vlabel(v):
        t = titles.get(v["col"], "") if v["col"] is not None else ""
        if v["agg"] == "count":
            return tr("Count of {0}", t) if v["col"] is not None else tr("Count")
        return tr("Sum of {0}", t) if v["agg"] == "sum" else tr("Average of {0}", t)

    def fmt(v, x):
        if x is None:
            return _cell(None, "")
        kind = kinds.get(v["col"]) if v["agg"] != "count" else "number"
        kind = kind if kind in SHP_NUM_KINDS else "number"
        return _cell(sh_json_value(x) if math.isfinite(x) else None, sh_fmt(x, kind, lg, cur))

    vl = [vlabel(v) for v in vals_f]
    empty = tr("(empty)")
    head = [titles.get(cid, "") or tr("Column") for cid in rows_f]
    for ck in corder:
        for i in range(len(vals_f)):
            name = ck or empty
            head.append(name if len(vals_f) == 1 else f"{name} · {vl[i]}")
    for i in range(len(vals_f)):
        head.append(tr("Total") if len(vals_f) == 1 and corder else (f"{tr('Total')} · {vl[i]}" if corder else vl[i]))
    out["header"] = head
    by = {}
    for rk, ck, vs in data:
        key = tuple(lab for _v, lab in rk)
        by.setdefault(key, []).append((ck[1] if ck else None, vs))

    def agg_cells(items):
        cells = []
        for ck in corder:
            sel = [vs for k, vs in items if k == ck]  # no source row for this cell: empty (not 0), as a spreadsheet's pivot
            cells.extend(fmt(v, shp_agg(v["agg"], [vs[i] for vs in sel], lg) if sel else None) for i, v in enumerate(vals_f))
        cells.extend(fmt(v, shp_agg(v["agg"], [vs[i] for _k, vs in items], lg)) for i, v in enumerate(vals_f))
        return cells
    for key in rorder:
        rk = rkeys[key]
        out["rows"].append([_cell(sh_json_value(v) if isinstance(v, float) else lab, lab or empty) for v, lab in rk]
                           + agg_cells(by.get(key, [])))
    allitems = [(ck[1] if ck else None, vs) for _rk, ck, vs in data]
    out["total"] = [_cell(tr("Total"), tr("Total"))] + [_cell(None, "") for _ in rows_f[1:]] + agg_cells(allitems) if rows_f \
        else agg_cells(allitems)
    if not rows_f:  # no row field: the one result row is the total itself
        out["rows"], out["total"] = [out["total"]], None
    return out


def shp_dict(c, r, uid=None):
    """sh_dict's part of a pivot sheet: {kind: "pivot", pivot: {setting, result}} (shb_dict adds it)."""
    spec = shp_load(r)
    return {"source": spec.get("source"), "rows": spec.get("rows") or [], "cols": spec.get("cols"),
            "values": spec.get("values") or [], "filter": spec.get("filter") or [], "updated_at": spec.get("updated_at"),
            "result": shp_compute(c, r, uid)}


# ---------------------------------------------------------------- export
def shp_table(c, r, uid=None):
    """(header row, data rows, total row or None) of pivot sheet r as cells {v, d}."""
    res = shp_compute(c, r, uid)
    return [_cell(h, h) for h in res["header"]], res["rows"], res["total"]


def shp_csv(c, r):
    """The CSV text (with BOM) of the computed table (the shown texts)."""
    head, rows, total = shp_table(c, r)
    buf = _io.StringIO()
    w = csv.writer(buf, delimiter=";" if dec_comma(lang()) else ",", lineterminator="\r\n")
    for line in [head, *rows, *([total] if total else [])]:
        w.writerow([_csv_cell(x["d"] or "") for x in line])
    return "﻿" + buf.getvalue()


def shp_xlsx_sheet(c, r, reg):
    """The worksheet XML of pivot sheet r for an .xlsx of its table (sheets/shbook.py shb_xlsx): the computed values (numbers
    as numbers, the header and the total row bold), no formulas."""
    from .io import _MAIN, _xl_num, escape
    head, rows, total = shp_table(c, r)
    lines = [(head, 1), *((x, 0) for x in rows), *([(total, 1)] if total else [])]
    xml = []
    for ri, (line, st) in enumerate(lines, 1):
        parts = []
        for ci, x in enumerate(line):
            ref = f"{sh_col_letter(ci)}{ri}"
            s = reg.style(st, None)
            sa = f' s="{s}"' if s else ""
            v = x["v"]
            if isinstance(v, (int, float)) and not isinstance(v, bool) and ri > 1:
                parts.append(f'<c r="{ref}"{sa}><v>{_xl_num(float(v))}</v></c>')
            elif x["d"]:
                parts.append(f'<c r="{ref}"{sa} t="inlineStr"><is><t xml:space="preserve">{escape(str(x["d"]))}</t></is></c>')
        xml.append(f'<row r="{ri}">{"".join(parts)}</row>')
    width = max((len(x) for x, _s in lines), default=1)
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{_MAIN}">'
            f'<dimension ref="A1:{sh_col_letter(max(width - 1, 0))}{max(len(lines), 1)}"/>'
            f'<sheetFormatPr defaultRowHeight="15"/><sheetData>{"".join(xml)}</sheetData>'
            '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>')


# ---------------------------------------------------------------- the route
@app.put("/api/sheets/<int:sid>/tabs/<int:tid>/pivot")
def sheets_tab_pivot_put(sid, tid):
    """{source, rows, cols, values, filter, expect_updated_at?} -- the setting of pivot sheet tid (the updated_at of the setting
    read: changed since -> 409 with "pivot" = the current one). The answer: {pivot: setting + result, rev}."""
    c = db()
    first, uid = _need_book(c, sid, write=True)
    _need_tab(c, first, tid)
    write_lock(c, "sheet:" + str(tid))
    r = _need_tab(c, first, tid)
    if not shp_is(r):
        raise Denied(409, tr("This sheet is no pivot sheet"))
    b = take_version(body())
    old = shp_load(r)
    ccf_check(b, old.get("updated_at"), "pivot", lambda: shp_dict(c, r, uid))
    spec = shp_clean(c, first, b, self_id=tid)
    new = shp_dump(spec)
    c.execute("UPDATE sheets SET pivot=? WHERE id=?", (new, tid))
    shh_meta_note(c, tid, "pivot", r["pivot"], new, uid)
    sh_touch(c, tid, uid)
    c.commit()
    r = c.execute("SELECT * FROM sheets WHERE id=?", (tid,)).fetchone()
    return jsonify(pivot=shp_dict(c, r, uid), rev=r["rev"])
