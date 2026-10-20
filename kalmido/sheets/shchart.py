"""2.124.0 A (#2115): the simple chart of a table -- bars or a line from its columns, drawn by the client (static/js/sheetchart.js).

The setting lives in sheets.chart (JSON, '' = no chart): {type: bar | line, x: the column of the labels (null = the row
numbers), y: [1..SHC_SERIES_MAX columns with the numbers]}. Everyone who reads the table sees it (GET /api/sheets/<id> answers
it as "chart"); only who may write the table changes it, like every other change of the table (rev + the area counter, so the
others redraw). The values are never stored: the client draws the evaluated cells it already has, so a chart shows exactly
what the viewer may see. Column ids only (no text of the person): moving the table between spaces (shmove.py) keeps it as is;
a column that is deleted later simply drops out of the drawing.
"""
import json

from flask import jsonify

from ..core.access import need_feat
from ..core.config import app
from ..core.db import body, db
from ..core.i18n import tr
from ..accounts.session import me
from ..personal.timetrack import BadInput
from .core import sh_need, sh_reload, sh_touch

SHC_TYPES = ("bar", "line")
SHC_SERIES_MAX = 6


def shc_load(sheet_row):
    """The chart setting of a sheet row, or None (no chart / a broken value)."""
    try:
        raw = sheet_row["chart"] if "chart" in sheet_row.keys() else ""
        d = json.loads(raw) if raw else None
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict) or d.get("type") not in SHC_TYPES or not isinstance(d.get("y"), list):
        return None
    return {"type": d["type"], "x": d.get("x") if isinstance(d.get("x"), int) else None,
            "y": [y for y in d["y"] if isinstance(y, int)][:SHC_SERIES_MAX]}


def shc_clean(c, sid, v):
    """A chart setting from a request -> the stored dict, or None (no chart). Columns must be live columns of this sheet."""
    if v is None:
        return None
    if not isinstance(v, dict) or v.get("type") not in SHC_TYPES:
        raise BadInput(tr("Invalid value: {0}", "chart"))
    cols = {r[0] for r in c.execute("SELECT id FROM sheet_columns WHERE sheet_id=? AND deleted_at IS NULL", (sid,))}

    def col(x):
        if isinstance(x, bool) or not isinstance(x, int) or x not in cols:
            raise BadInput(tr("Invalid value: {0}", "column"))
        return x

    x = v.get("x")
    x = None if x is None else col(x)
    ys = v.get("y")
    if not isinstance(ys, list) or not ys or len(ys) > SHC_SERIES_MAX:
        raise BadInput(tr("Choose one to {0} columns with numbers", SHC_SERIES_MAX))
    out = []
    for y in ys:
        y = col(y)
        if y not in out and y != x:
            out.append(y)
    if not out:
        raise BadInput(tr("Choose one to {0} columns with numbers", SHC_SERIES_MAX))
    return {"type": v["type"], "x": x, "y": out}


@app.put("/api/sheets/<int:sid>/chart")
def sheets_chart_put(sid):
    """{chart: {type: bar|line, x: column id|null, y: [column ids]} | null} -- the table's chart (null = none). Write right."""
    need_feat("sheets")
    c = db()
    sh_need(c, sid, write=True)
    ch = shc_clean(c, sid, body().get("chart"))
    c.execute("UPDATE sheets SET chart=? WHERE id=?", (json.dumps(ch) if ch else "", sid))
    sh_touch(c, sid, me())
    c.commit()
    return jsonify(ok=True, rev=sh_reload(c, sid)["rev"], chart=ch)
