"""2.125.0 C (#2122): Excel (.xlsx) export of the time report and of the workload view.
GET /api/time/export.xlsx   same filters, columns, visibility (#1523) and rounding as /api/time/export.csv
GET /api/workload/export.xlsx   the people x weeks view of /api/workload (planned / capacity), only what the person sees
Numbers are numbers, times are date-time cells, a sum row closes the sheet. A small writer of its own: the sheet writer
(sheets/io.py) is bound to a sheet of the app."""
import io
import re
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape
from flask import g, request, Response

from ..core.config import app
from ..core.i18n import lang, tr
from ..core.db import db, err, local_now
from ..core.access import Denied, need_feat
from ..core.serializers import csv_cell
from ..accounts.session import me
from ..sheets.formula import sh_col_letter
from ..sheets.io import _EPOCH, _MAIN, _NS, _q, _xl_num
from .timetrack import n43_admin_lists, need_time, time_report

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# cell styles: 0 default, 1 bold, 2 date + time, 3 number 0.00, 4 bold number 0.00, 5 date
TX_TEXT, TX_BOLD, TX_DT, TX_NUM, TX_BNUM, TX_DATE = 0, 1, 2, 3, 4, 5


def tx_cell(r, c, v, s=0):
    """One cell: None = empty, numbers as numbers, text as an inline string (a formula-looking text gets the CSV guard)."""
    ref = f"{sh_col_letter(c)}{r}"
    sa = f' s="{s}"' if s else ""
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f'<c r="{ref}"{sa}><v>{_xl_num(float(v))}</v></c>'
    if isinstance(v, datetime):
        d = v - datetime(1899, 12, 30)
        return f'<c r="{ref}"{sa}><v>{_xl_num(d.days + d.seconds / 86400)}</v></c>'
    if isinstance(v, date):
        return f'<c r="{ref}"{sa}><v>{(v - _EPOCH).days}</v></c>'
    return f'<c r="{ref}"{sa} t="inlineStr"><is><t xml:space="preserve">{escape(csv_cell(str(v)))}</t></is></c>'


def tx_book(sheet_name, rows, widths):
    """rows = [[(value, style), ...], ...]; row 1 is the header. Returns the .xlsx bytes."""
    xml_rows = []
    for ri, row in enumerate(rows, 1):
        cells = "".join(tx_cell(ri, ci, v, s) for ci, (v, s) in enumerate(row))
        xml_rows.append(f'<row r="{ri}">{cells}</row>')
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    ws = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{_MAIN}">'
          '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
          f'<cols>{cols}</cols><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    rel = f"{_NS}/officeDocument/2006/relationships"
    name = _q(re.sub(r"[\[\]*?:/\\]", " ", sheet_name)[:31] or "Sheet1")
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="{_MAIN}">'
              '<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd\\ hh:mm"/></numFmts>'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
              '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="6"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
              '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
              '<xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
              '<xf numFmtId="2" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>'
              '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    parts = {
        "[Content_Types].xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{_NS}/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_NS}/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{_MAIN}" xmlns:r="{rel}">'
            f'<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_NS}/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{rel}/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": styles,
        "xl/worksheets/sheet1.xml": ws,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return buf.getvalue()


def tx_response(data, name):
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return Response(data, mimetype=XLSX_MIME, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def tx_time_rows(c, uid, rep):
    """The rows of the time sheet: the rows and columns of the CSV (2.125.0 R (#2122): the same rows, timesheet.py tz_rows), but
    numbers / date-times as such, plus a sum row."""
    from .timesheet import tz_rows
    B = TX_BOLD
    rows = [[(tr(h), B) for h in ("List", "Task", "User", "Start|time", "End|time", "Duration (h)", "Duration (h:mm)", "Rounded (h)")]
            + [(tr("Amount ({0})", rep["currency"]), B), (tr("Note"), B)]]
    tot_s = tot_r = 0
    tot_a, any_a = 0.0, False
    for x in tz_rows(c, uid, rep):
        s0 = x["start"].replace(tzinfo=None, second=0, microsecond=0)
        en = x["end"].replace(tzinfo=None, second=0, microsecond=0) if x["end"] else None
        sec, rs, amt = x["seconds"], x["rounded"], x["amount"]
        tot_s, tot_r = tot_s + sec, tot_r + rs
        if amt is not None:
            tot_a, any_a = tot_a + amt, True
        rows.append([(x["list"], 0), (x["title"], 0), (x["user"], 0), (s0, TX_DT), (en if en else tr("running"), TX_DT),
                     (round(sec / 3600, 2), TX_NUM), (f"{sec // 3600}:{sec % 3600 // 60:02d}", 0), (round(rs / 3600, 2), TX_NUM),
                     (round(amt, 2) if amt is not None else None, TX_NUM), (x["note"], 0)])
    rows.append([(tr("Total"), B), ("", 0), ("", 0), ("", 0), ("", 0), (round(tot_s / 3600, 2), TX_BNUM),
                 (f"{tot_s // 3600}:{tot_s % 3600 // 60:02d}", B), (round(tot_r / 3600, 2), TX_BNUM), (round(tot_a, 2) if any_a else None, TX_BNUM)])
    return rows


@app.get("/api/time/export.xlsx")
def time_xlsx():
    """Same filters and visibility as /api/time/export.csv (time_report decides who sees which entry)."""
    need_time()
    c = db()
    uid = me()
    rep = time_report(c, uid, dict(request.args), own=n43_admin_lists(c, uid))
    name = f"{tr('timesheet|file')}-{rep['from'] or 'all'}-{rep['to'] or local_now().date().isoformat()}.xlsx"
    return tx_response(tx_book(tr("Timesheet"), tx_time_rows(c, uid, rep), [22, 30, 18, 17, 17, 12, 12, 12, 12, 40]), name)


def tx_workload_rows(d):
    """People x weeks: planned hours and capacity hours per week, tasks without a date, a sum row."""
    B = TX_BOLD
    head = [(tr("Person"), B)]
    for w in d["weeks"]:
        head += [(f"{tr('Planned (h)')} {w['start']}", B), (f"{tr('Capacity (h)')} {w['start']}", B)]
    head += [(f"{tr('No date')} (h)", B)]
    rows = [head]
    tp = [0.0] * len(d["weeks"])
    tc = [0.0] * len(d["weeks"])
    tn = 0.0
    for p in d["people"]:
        row = [(p["display_name"], 0)]
        for i, w in enumerate(p["weeks"]):
            ph, ch = round(w["minutes"] / 60, 2), round(w.get("capacity_h", p["capacity_h"]), 2)
            tp[i], tc[i] = tp[i] + ph, tc[i] + ch
            row += [(ph, TX_NUM), (ch, TX_NUM)]
        nh = round(p["nodate"]["minutes"] / 60, 2)
        tn += nh
        rows.append(row + [(nh, TX_NUM)])
    rows.append([(tr("Total"), B)] + [(round(x, 2), TX_BNUM) for pair in zip(tp, tc) for x in pair] + [(round(tn, 2), TX_BNUM)])
    return rows


@app.get("/api/workload/export.xlsx")
def workload_xlsx():
    """?start= &weeks= &org= like /api/workload (same rules: module on, no agents / kids, only people and tasks the person sees)."""
    from ..team.workload import workload
    c = db()
    if (g.user["kind"] or "user") != "agent":
        need_feat("workload")
    if g.user["kid"]:
        raise Denied(403)
    a = request.args
    try:
        org = int(a["org"]) if a.get("org") else None
        weeks = int(a.get("weeks") or 4)
    except ValueError:
        return err(tr("Invalid data"))
    d = workload(c, me(), a.get("start"), weeks, org)
    rows = tx_workload_rows(d)
    name = f"{tr('Workload')}-{d['weeks'][0]['start']}.xlsx"
    return tx_response(tx_book(tr("Workload"), rows, [24] + [14] * (len(rows[0]) - 1)), name)
