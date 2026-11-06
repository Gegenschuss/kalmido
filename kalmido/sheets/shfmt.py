"""2.578.0 (#3462 part C): the format of a table's cells and its colour rules.

Cell format (sheet_cells.fmt, JSON, '' = none) comes on top of the column's kind (the kind stays the column's, #3462 "Bleibt"):
{bold, italic, color, fill, align, wrap, merge}. color / fill are keys of the app's palette (SHFM_PALETTE: the accent, a light
accent and three cool greys; no free colour, the client draws them from the theme), align left | center | right, wrap true =
the text breaks into lines, merge [rows, columns] on the top left cell of a merged block (the cells it covers keep their input,
they are only hidden). Written through the cells' own write (sheets/core.py _write_cells): an entry with fmt (the whole format,
null / {} = none) or fmt_patch (only the keys given, null removes one), optionally prev_fmt (the format the writer read: a cell
formatted otherwise by now is not changed but reported in conflicts, like prev of the inputs). An agent's format change is in
its batch (sheet_changes kind 'fmt', taken back with the call); the app's Undo writes the former format back.

Colour rules (sheets.fmt_rules, JSON list, '' = none): [{id, cols: [column ids], rows: [first row id, last row id] | null (=
the whole columns), op, a, b, color, fill}] with op gt | lt | eq | between | contains | empty | overdue (a date before today).
The client colours the cells it shows (the values it already has, so a rule never reveals anything); PUT /api/sheets/<id>/rules
replaces the list (write right, expect_rev -> 409 with the current rules), in the sheet's history ("Rules").

xlsx: the export writes fonts / fills / alignment per cell format, mergeCells and the rules as conditionalFormatting with their
own dxf; the import reads the same back (colours to the nearest palette key; theme colours are left out).
"""
import json
import re
import secrets

from flask import jsonify

from ..core.access import need_feat
from ..core.config import app
from ..core.conflict import Conflict, need_version
from ..core.db import body, db, insert_id
from ..core.errors import BadInput, UnknownFields
from ..core.i18n import tr
from ..core.pg import write_lock
from ..accounts.session import me
from ..api.common import v1_json, v1_view
from .core import sh_change, sh_need, sh_reload, sh_touch
from .formula import sh_col_letter
from .shhist import shh_meta

SHFM_PALETTE = ("a", "a2", "g1", "g2", "g3")  # accent, light accent, dark / middle / light grey (static/js/sheetfmt.js SHFM_PAL)
# their fixed shades in a file (Excel has no theme of ours): text colours and fills
SHFM_XL_INK = {"a": "187381", "a2": "4FB3C1", "g1": "3A3D42", "g2": "6B6F78", "g3": "9497A0"}
SHFM_XL_FILL = {"a": "BFE3E8", "a2": "E2F2F4", "g1": "D3D5D9", "g2": "E5E6E9", "g3": "F2F3F5"}
SHFM_ALIGN = ("left", "center", "right")
SHFM_MERGE_MAX = (500, 50)
SHFM_OPS = ("gt", "lt", "eq", "between", "contains", "empty", "overdue")
SHFM_RULES_MAX = 50
SHFM_ARG_MAX = 200
SHFM_KEYS = ("bold", "italic", "color", "fill", "align", "wrap", "merge")


# ---------------------------------------------------------------- the format of a cell
def shfm_load(raw):
    """The stored format of a cell -> dict, or None (none / a broken value)."""
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return d if isinstance(d, dict) and d else None


def _bool(v, what):
    if v in (None, False, 0):
        return False
    if v in (True, 1):
        return True
    raise BadInput(tr("Invalid value: {0}", what))


def shfm_clean(v):
    """A format from a request -> its stored text ('' = none). Unknown keys or values are refused."""
    if v in (None, "", {}):
        return ""
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", "fmt"))
    bad = sorted(k for k in v if k not in SHFM_KEYS)
    if bad:
        raise BadInput(tr("Invalid value: {0}", "fmt." + str(bad[0])[:30]))
    out = {}
    for k in ("bold", "italic", "wrap"):
        if _bool(v.get(k), "fmt." + k):
            out[k] = True
    for k in ("color", "fill"):
        x = v.get(k)
        if x in (None, ""):
            continue
        if x not in SHFM_PALETTE:
            raise BadInput(tr("Invalid value: {0}", "fmt." + k))
        out[k] = x
    al = v.get("align")
    if al not in (None, ""):
        if al not in SHFM_ALIGN:
            raise BadInput(tr("Invalid value: {0}", "fmt.align"))
        out["align"] = al
    m = v.get("merge")
    if m not in (None, [], [1, 1]):
        if (not isinstance(m, list) or len(m) != 2 or any(isinstance(n, bool) or not isinstance(n, int) for n in m)
                or not (1 <= m[0] <= SHFM_MERGE_MAX[0] and 1 <= m[1] <= SHFM_MERGE_MAX[1])):
            raise BadInput(tr("Invalid value: {0}", "fmt.merge"))
        out["merge"] = [m[0], m[1]]
    return json.dumps(out, sort_keys=True, separators=(",", ":")) if out else ""


def shfm_wanted(d, old):
    """The new stored format of a cell entry {fmt | fmt_patch} -> text, or None when the entry says nothing about the format."""
    if "fmt" in d:
        return shfm_clean(d["fmt"])
    if "fmt_patch" in d:
        p = d["fmt_patch"]
        if not isinstance(p, dict):
            raise BadInput(tr("Invalid value: {0}", "fmt_patch"))
        cur = dict(shfm_load(old) or {})
        for k, v in p.items():
            if v is None:
                cur.pop(k, None)
            else:
                cur[k] = v
        return shfm_clean(cur)
    return None


def _same(a, b):
    return (shfm_load(a) or {}) == (shfm_load(b) or {})


def shfm_write(c, sheet_row, book, d, rid, cid, uid, ts, agent_id, batch, conflicts):
    """The format part of one cell entry (sheets/core.py _write_cells) -> the cell id when its format changed, else None.
    prev_fmt given and the cell formatted otherwise by now: nothing changes, the cell goes to conflicts."""
    x = book.at.get((rid, cid))
    old = (x.get("fmt") or "") if x else ""
    new = shfm_wanted(d, old)
    if new is None:
        return None
    if "prev_fmt" in d:
        try:
            prev = shfm_clean(d["prev_fmt"])
        except BadInput:
            prev = None
        if prev is None or not (_same(prev, old) or _same(new, old)):
            if conflicts is not None:
                conflicts.append({"row_id": rid, "col_id": cid, "cell_id": x["id"] if x else None, "what": "fmt",
                                  "server": shfm_load(old), "mine": shfm_load(new)})
            return None
    if new == old:
        return None
    if x:
        c.execute("UPDATE sheet_cells SET fmt=? WHERE id=?", (new, x["id"]))
        x["fmt"] = new
        xid = x["id"]
    else:
        xid = insert_id(c, "INSERT INTO sheet_cells(sheet_id,row_id,col_id,raw,fmt,updated_by,updated_at) VALUES(?,?,?,'',?,?,?)",
                        (sheet_row["id"], rid, cid, new, uid, ts))
        book._add(dict(c.execute("SELECT * FROM sheet_cells WHERE id=?", (xid,)).fetchone()))
    sh_change(c, sheet_row["id"], batch, agent_id, "fmt", cell_id=xid, row_id=rid, col_id=cid, old=old, new=new)
    n = getattr(book, "_shf_hist", 0)
    if n < 50 and not getattr(book, "shh_off", False):  # the history keeps the first 50 cells of one call
        book._shf_hist = n + 1
        shh_meta(c, sheet_row["id"], "format", shfm_text(old), shfm_text(new), uid, cell={"id": xid, "row_id": rid, "col_id": cid})
    return xid


def shfm_undo(c, ch, uid):
    """Takes back one 'fmt' change of an agent's call (sheets/core.py sh_undo_batch) -> True when it was put back (False:
    formatted otherwise since, the newer format stays)."""
    x = c.execute("SELECT fmt FROM sheet_cells WHERE id=?", (ch["cell_id"],)).fetchone()
    if not x or not _same(x["fmt"], ch["new_raw"] or ""):
        return False
    c.execute("UPDATE sheet_cells SET fmt=? WHERE id=?", (ch["old_raw"] or "", ch["cell_id"]))
    return True


def shfm_text(raw):
    """How a format reads in the history: its parts in words."""
    f = shfm_load(raw) or {}
    out = []
    for k, label in (("bold", "Bold"), ("italic", "Italic"), ("wrap", "Wrap text")):
        if f.get(k):
            out.append(tr(label))
    if f.get("color"):
        out.append(tr("Text colour") + " " + f["color"])
    if f.get("fill"):
        out.append(tr("Fill") + " " + f["fill"])
    if f.get("align"):
        out.append({"left": tr("Align left"), "center": tr("Align centre"), "right": tr("Align right")}[f["align"]])
    if f.get("merge"):
        out.append(tr("Merged") + f" {f['merge'][0]}×{f['merge'][1]}")
    return ", ".join(out)


# ---------------------------------------------------------------- colour rules
def shfm_rules_load(sheet_row):
    """The colour rules of a sheet row ([] = none / broken)."""
    try:
        raw = sheet_row["fmt_rules"] if "fmt_rules" in sheet_row.keys() else ""
        v = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [r for r in v if isinstance(r, dict)] if isinstance(v, list) else []


def _arg(v, what):
    if v is None or v == "":
        return ""
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        raise BadInput(tr("Invalid value: {0}", what))
    s = str(v).strip()
    if len(s) > SHFM_ARG_MAX:
        raise BadInput(tr("Invalid value: {0}", what))
    return s


def shfm_rules_clean(c, sid, v, kept=()):
    """The rules of a request -> the stored list. Columns / rows must be live ones of this sheet. kept = the ids of the rules
    stored before: such a rule whose column / row went to the trash since loses that column (a row: the rule) instead of
    refusing the whole list (the app sends the rules back as it read them)."""
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > SHFM_RULES_MAX:
        raise BadInput(tr("At most {0} rules", SHFM_RULES_MAX))
    cols = {r[0] for r in c.execute("SELECT id FROM sheet_columns WHERE sheet_id=? AND deleted_at IS NULL", (sid,))}
    rows = {r[0] for r in c.execute("SELECT id FROM sheet_rows WHERE sheet_id=? AND deleted_at IS NULL", (sid,))}
    out = []
    for r in v:
        if not isinstance(r, dict):
            raise BadInput(tr("Invalid value: {0}", "rules"))
        op = r.get("op")
        if op not in SHFM_OPS:
            raise BadInput(tr("Invalid value: {0}", "op"))
        cs, rs, old = r.get("cols"), r.get("rows"), r.get("id") in kept
        if old and isinstance(cs, list):
            cs = [x for x in cs if not isinstance(x, bool) and x in cols]
            if not cs or (isinstance(rs, list) and any(x not in rows for x in rs)):
                continue  # its columns / its rows are gone
        if not isinstance(cs, list) or not cs or len(cs) > 200 or any(isinstance(x, bool) or x not in cols for x in cs):
            raise BadInput(tr("Invalid value: {0}", "cols"))
        if rs is not None and (not isinstance(rs, list) or len(rs) != 2 or any(isinstance(x, bool) or x not in rows for x in rs)):
            raise BadInput(tr("Invalid value: {0}", "rows"))
        a, b = _arg(r.get("a"), "a"), _arg(r.get("b"), "b")
        if op in ("gt", "lt", "eq", "contains") and a == "":
            raise BadInput(tr("Enter a value for the rule"))
        if op == "between" and (a == "" or b == ""):
            raise BadInput(tr("Enter both values for the rule"))
        color, fill = r.get("color") or "", r.get("fill") or ""
        if (color and color not in SHFM_PALETTE) or (fill and fill not in SHFM_PALETTE) or not (color or fill):
            raise BadInput(tr("Choose a text colour or a fill for the rule"))
        rid = r.get("id") if isinstance(r.get("id"), str) and re.fullmatch(r"[a-z0-9]{1,16}", r.get("id") or "") else secrets.token_hex(4)
        x = {"id": rid, "cols": list(dict.fromkeys(cs)), "rows": list(rs) if rs else None, "op": op, "color": color, "fill": fill}
        if op in ("gt", "lt", "eq", "contains", "between"):
            x["a"] = a
        if op == "between":
            x["b"] = b
        out.append(x)
    return out


def shfm_rules_remap(rules, cmap, rmap):
    """The rules of a copied sheet (sheets/shbook.py _copy): column / row ids mapped onto the copies, rules left without a
    column dropped."""
    out = []
    for r in rules:
        cs = [cmap[x] for x in r.get("cols") or [] if x in cmap]
        if not cs:
            continue
        rs = r.get("rows")
        rs = [rmap[x] for x in rs] if rs and all(x in rmap for x in rs) else None
        out.append({**r, "cols": cs, "rows": rs})
    return out


def _rules_put(c, sid, b, uid):
    write_lock(c, "sheet:" + str(sid))  # the sheet's lock like its cells
    r = sh_reload(c, sid)
    er = b.get("expect_rev")
    if er is not None and (isinstance(er, bool) or not isinstance(er, int)):
        raise BadInput(tr("Invalid value: {0}", "expect_rev"))
    if er is not None and er != r["rev"]:
        raise Conflict("rules", shfm_rules_load(r))
    rules = shfm_rules_clean(c, sid, b.get("rules"), {x.get("id") for x in shfm_rules_load(r)})
    was = r["fmt_rules"] or ""
    new = json.dumps(rules, separators=(",", ":")) if rules else ""
    c.execute("UPDATE sheets SET fmt_rules=? WHERE id=?", (new, sid))
    shh_meta(c, sid, "rules", str(len(shfm_rules_load(r))) if was else "", str(len(rules)) if rules else "", uid)
    sh_touch(c, sid, uid)
    return rules


@app.put("/api/sheets/<int:sid>/rules")
def sheets_rules_put(sid):
    """{rules: [...], expect_rev?} -- the sheet's colour rules (the whole list; [] = none). Write right; expect_rev differs ->
    409 {error, rules: the current ones}."""
    need_feat("sheets")
    c = db()
    sh_need(c, sid, write=True)
    rules = _rules_put(c, sid, body(), me())
    c.commit()
    return jsonify(ok=True, rev=sh_reload(c, sid)["rev"], rules=rules)


@app.put("/api/v1/sheets/<int:sid>/rules")
@v1_view
def v1_sheet_rules(sid):
    """2.578.0 (#3462 C): the same for agents (scope sheets:write); expect_rev is required for an agent account."""
    b = v1_json()
    extra = sorted(k for k in b if k not in ("rules", "expect_rev"))
    if extra:
        raise UnknownFields(extra)
    c = db()
    sh_need(c, sid, write=True)
    need_version(b, "expect_rev", header=False)
    rules = _rules_put(c, sid, b, me())
    c.commit()
    return jsonify(rules=rules, rev=sh_reload(c, sid)["rev"])


def shfm_spec(paths, schemas, op, ok, errs, pid):
    """OpenAPI of the format and the rules (called from sheets/v1.py sheets_spec)."""
    fmt = {"type": ["object", "null"], "description": "2.578.0: the cell's format on top of its column's kind: {bold, italic, wrap: "
           "true, color / fill: a | a2 | g1 | g2 | g3 (the app's accent, light accent, dark / middle / light grey), align: left | "
           "center | right, merge: [rows, columns] (on the top left cell of a merged block)}; null = none"}
    schemas["SheetCell"]["properties"]["fmt"] = fmt
    cell = paths["/sheets/{id}/cells"]["put"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["cells"]["items"]
    cell["properties"].update({
        "fmt": {**fmt, "description": "2.578.0: the whole new format (null = none); without raw only the format changes"},
        "fmt_patch": {"type": "object", "description": "2.578.0: only these format keys (null removes one), e.g. {\"bold\": true}"},
        "prev_fmt": {"type": ["object", "null"], "description": "2.578.0: the format you read; formatted otherwise by now = not "
                                                               "changed, reported in conflicts (what: fmt)"}})
    rule = {"type": "object", "required": ["cols", "op"], "properties": {
        "id": {"type": "string"}, "cols": {"type": "array", "items": {"type": "integer"}, "description": "column ids"},
        "rows": {"type": ["array", "null"], "items": {"type": "integer"}, "description": "[first row id, last row id]; null = whole columns"},
        "op": {"type": "string", "enum": list(SHFM_OPS), "description": "overdue = a date before today"},
        "a": {"type": "string"}, "b": {"type": "string", "description": "between: the upper value"},
        "color": {"type": "string", "enum": list(SHFM_PALETTE)}, "fill": {"type": "string", "enum": list(SHFM_PALETTE)}}}
    schemas["SheetRule"] = rule
    schemas["Sheet"]["properties"]["rules"] = {"type": "array", "items": {"$ref": "#/components/schemas/SheetRule"},
                                               "description": "2.578.0: the colour rules of the table"}
    paths["/sheets/{id}/rules"] = {"put": op(
        "Set the colour rules of a table (2.578.0)", "Tables",
        ok({"type": "object", "properties": {"rules": {"type": "array", "items": {"$ref": "#/components/schemas/SheetRule"}}, "rev": {"type": "integer"}}})
        | errs("400", "403", "404", "409"), [pid("id", "Table id")],
        body={"type": "object", "required": ["rules"], "properties": {"rules": {"type": "array", "maxItems": SHFM_RULES_MAX, "items": rule},
                                                                     "expect_rev": {"type": "integer", "description": "the rev you read (required for agents)"}}},
        scope="sheets:write", desc="Replaces the whole list ([] = none). Colours come from the app's palette only.")}


# ---------------------------------------------------------------- xlsx: export
class ShfmXl:
    """The cell formats of an .xlsx being written: fonts, fills and cell formats (xf) after the five fixed ones of
    sheets/io.py shx_xlsx (0 default, 1 header, 2 currency, 3 percent, 4 date). One registry for all sheets of a table
    (sheets/shbook.py shb_xlsx takes the styles of the last sheet)."""
    BASE_NUM = {0: 0, 1: 0, 2: 164, 3: 10, 4: 14}

    def __init__(self):
        self.fonts = ['<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>',
                      '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font>']
        self.fills = ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>']
        self.xfs = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>',
                    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>',
                    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>',
                    '<xf numFmtId="10" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>',
                    '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>']
        self._font, self._fill, self._xf = {}, {}, {}

    def _idx(self, cache, lst, key, xml):
        if key not in cache:
            lst.append(xml)
            cache[key] = len(lst) - 1
        return cache[key]

    def style(self, base, f):
        """The xf index of a cell with base style `base` (0-4) and format f (dict | None)."""
        if not f or not any(f.get(k) for k in ("bold", "italic", "color", "fill", "align", "wrap")):
            return base
        fk = (bool(f.get("bold")), bool(f.get("italic")), f.get("color") or "")
        font = 0
        if any(fk):
            font = self._idx(self._font, self.fonts, fk, "<font>" + ("<b/>" if fk[0] else "") + ("<i/>" if fk[1] else "")
                             + '<sz val="11"/>' + (f'<color rgb="FF{SHFM_XL_INK[fk[2]]}"/>' if fk[2] else "")
                             + '<name val="Calibri"/><family val="2"/></font>')
        fill = 0
        if f.get("fill"):
            fill = self._idx(self._fill, self.fills, f["fill"], f'<fill><patternFill patternType="solid"><fgColor rgb="FF{SHFM_XL_FILL[f["fill"]]}"/>'
                                                                  '<bgColor indexed="64"/></patternFill></fill>')
        al = (f.get("align") or "", bool(f.get("wrap")))
        num = self.BASE_NUM.get(base, 0)
        key = (num, font, fill, al)
        if key not in self._xf:
            a = ""
            if any(al):
                a = "<alignment" + (f' horizontal="{al[0]}"' if al[0] else "") + (' wrapText="1"' if al[1] else "") + "/>"
            self.xfs.append(f'<xf numFmtId="{num}" fontId="{font}" fillId="{fill}" borderId="0" xfId="0"'
                            + (' applyNumberFormat="1"' if num else "") + (' applyFont="1"' if font else "")
                            + (' applyFill="1"' if fill else "") + (' applyAlignment="1"' if a else "")
                            + (f">{a}</xf>" if a else "/>"))
            self._xf[key] = len(self.xfs) - 1
        return self._xf[key]

    def xml(self):
        """fonts, fills, borders, cellStyleXfs and cellXfs of styles.xml (in the order OOXML wants them)."""
        return (f'<fonts count="{len(self.fonts)}">{"".join(self.fonts)}</fonts>'
                f'<fills count="{len(self.fills)}">{"".join(self.fills)}</fills>'
                '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                f'<cellXfs count="{len(self.xfs)}">{"".join(self.xfs)}</cellXfs>')


def shfm_xl_merges(book, at, nrows):
    """<mergeCells> of a sheet being written (data rows start at row 2), '' when there are none."""
    out = []
    ncols = len(book.cols)
    for (ri, ci), x in at.items():
        m = (shfm_load(x.get("fmt")) or {}).get("merge")
        if not m or ri >= nrows:
            continue
        h, w = min(m[0], nrows - ri), min(m[1], ncols - ci)
        if h * w > 1:
            out.append(f'<mergeCell ref="{sh_col_letter(ci)}{ri + 2}:{sh_col_letter(ci + w - 1)}{ri + h + 1}"/>')
    return f'<mergeCells count="{len(out)}">{"".join(sorted(out))}</mergeCells>' if out else ""


def _xl_lit(v):
    s = str(v)
    if re.fullmatch(r"-?\d+(?:[.,]\d+)?", s):
        return s.replace(",", ".")
    return '"' + s.replace('"', '""') + '"'


def shfm_xl_rules(sheet_row, book, dv_end, dxfs, prio):
    """The colour rules as <conditionalFormatting> parts -> (xml, next priority); their dxf go onto dxfs."""
    from xml.sax.saxutils import escape
    out = []
    for r in shfm_rules_load(sheet_row):
        cis = sorted(book.col_idx[x] for x in r.get("cols") or [] if x in book.col_idx)
        if not cis:
            continue
        rs = r.get("rows")
        if rs and all(x in book.row_idx for x in rs):
            r0, r1 = sorted(book.row_idx[x] + 2 for x in rs)
        else:
            r0, r1 = 2, dv_end
        sq = " ".join(f"{sh_col_letter(ci)}{r0}:{sh_col_letter(ci)}{r1}" for ci in cis)
        tl = f"{sh_col_letter(cis[0])}{r0}"
        dx = "<dxf>" + (f'<font><color rgb="FF{SHFM_XL_INK[r["color"]]}"/></font>' if r.get("color") else "") + (
            f'<fill><patternFill patternType="solid"><bgColor rgb="FF{SHFM_XL_FILL[r["fill"]]}"/></patternFill></fill>' if r.get("fill") else "") + "</dxf>"
        dxfs.append(dx)
        di, op = len(dxfs) - 1, r["op"]
        a = r.get("a", "")
        if op in ("gt", "lt", "eq"):
            o = {"gt": "greaterThan", "lt": "lessThan", "eq": "equal"}[op]
            rule = f'<cfRule type="cellIs" dxfId="{di}" priority="{prio}" operator="{o}"><formula>{escape(_xl_lit(a))}</formula></cfRule>'
        elif op == "between":
            rule = (f'<cfRule type="cellIs" dxfId="{di}" priority="{prio}" operator="between"><formula>{escape(_xl_lit(a))}</formula>'
                    f'<formula>{escape(_xl_lit(r.get("b", "")))}</formula></cfRule>')
        elif op == "contains":
            lit = '"' + a.replace('"', '""') + '"'
            rule = (f'<cfRule type="containsText" dxfId="{di}" priority="{prio}" operator="containsText" text="{escape(a, {chr(34): "&quot;"})}">'
                    f'<formula>{escape(f"NOT(ISERROR(SEARCH({lit},{tl})))")}</formula></cfRule>')
        elif op == "empty":
            rule = f'<cfRule type="containsBlanks" dxfId="{di}" priority="{prio}"><formula>{escape(f"LEN(TRIM({tl}))=0")}</formula></cfRule>'
        else:  # overdue
            rule = f'<cfRule type="expression" dxfId="{di}" priority="{prio}"><formula>{escape(f"AND(ISNUMBER({tl}),{tl}<TODAY())")}</formula></cfRule>'
        out.append(f'<conditionalFormatting sqref="{sq}">{rule}</conditionalFormatting>')
        prio += 1
    return "".join(out), prio


# ---------------------------------------------------------------- xlsx: import
def _hex(el):
    """#rrggbb of a colour element with rgb (theme / indexed colours: None)."""
    if el is None:
        return None
    v = el.get("rgb") or ""
    return v[-6:].upper() if re.fullmatch(r"[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8}", v) else None


def _near(hx, table, plain):
    """The palette key nearest to colour hx; None when the colour is nearer to the plain one (black text / white fill)."""
    if not hx:
        return None
    rgb = tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))

    def dist(h):
        return sum((a - b) ** 2 for a, b in zip(rgb, (int(h[i:i + 2], 16) for i in (0, 2, 4))))
    best = min(table, key=lambda k: dist(table[k]))
    return None if dist(plain) <= dist(table[best]) else best


def shfm_xl_styles(st, local):
    """The cell formats of a read styles.xml (ElementTree root) -> ({xf index: format dict}, [(color, fill) per dxf])."""
    fonts, fills, xfs, dxfs = [], [], [], []
    for el in st:
        tag = local(el.tag)
        if tag == "fonts":
            for fo in el:
                d = {}
                for x in fo:
                    t = local(x.tag)
                    if t == "b" and x.get("val") not in ("0", "false"):
                        d["bold"] = True
                    elif t == "i" and x.get("val") not in ("0", "false"):
                        d["italic"] = True
                    elif t == "color":
                        k = _near(_hex(x), SHFM_XL_INK, "000000")
                        if k:
                            d["color"] = k
                fonts.append(d)
        elif tag == "fills":
            for fi in el:
                k = None
                for x in fi.iter():
                    if local(x.tag) == "patternFill" and x.get("patternType") != "solid":
                        break
                    if local(x.tag) == "fgColor":
                        k = _near(_hex(x), SHFM_XL_FILL, "FFFFFF")
                        break
                fills.append(k)
        elif tag == "dxfs":
            for dx in el:
                ink = fill = None
                for x in dx.iter():
                    t = local(x.tag)
                    if t == "color" and ink is None:
                        ink = _near(_hex(x), SHFM_XL_INK, "000000")
                    elif t in ("bgColor", "fgColor") and fill is None:
                        fill = _near(_hex(x), SHFM_XL_FILL, "FFFFFF")
                dxfs.append((ink, fill))
    for el in st:
        if local(el.tag) != "cellXfs":
            continue
        for i, xf in enumerate(el):
            d = {}
            try:
                fo = int(xf.get("fontId") or 0)
                fi = int(xf.get("fillId") or 0)
            except ValueError:
                fo = fi = 0
            if 0 <= fo < len(fonts):
                d.update(fonts[fo])
            if 0 <= fi < len(fills) and fills[fi]:
                d["fill"] = fills[fi]
            for x in xf:
                if local(x.tag) == "alignment":
                    if x.get("horizontal") in SHFM_ALIGN:
                        d["align"] = x.get("horizontal")
                    if x.get("wrapText") in ("1", "true"):
                        d["wrap"] = True
            if d:
                xfs.append((i, d))
    return dict(xfs), dxfs


def shfm_xl_read_rules(cfs, dxfs, local, col_index):
    """The colour rules of a read worksheet (its conditionalFormatting elements) Kalmido understands -> [{cols, r0, r1, op, a,
    b, color, fill}] (0-based column indexes, file rows). Option colours of drop-down lists are read by sheets/io.py."""
    out = []
    for cf in cfs:
        sq = (cf.get("sqref") or "").split()
        spans = []
        for rg in sq:
            m = re.fullmatch(r"\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?", rg)
            if m:
                spans.append((col_index(m.group(1)), int(m.group(2)), col_index(m.group(3) or m.group(1)), int(m.group(4) or m.group(2))))
        if not spans:
            continue
        cols = sorted({ci for c0, _r0, c1, _r1 in spans for ci in range(c0, min(c1, c0 + 200) + 1)})
        r0, r1 = min(s[1] for s in spans), max(s[3] for s in spans)
        for rule in cf:
            if local(rule.tag) != "cfRule":
                continue
            try:
                ink, fill = dxfs[int(rule.get("dxfId"))]
            except (TypeError, ValueError, IndexError):
                continue
            if not (ink or fill):
                continue
            fx = [x.text or "" for x in rule if local(x.tag) == "formula"]
            t, o = rule.get("type"), rule.get("operator")

            def lit(s):
                s = (s or "").strip()
                m = re.fullmatch(r'"((?:[^"]|"")*)"', s)
                return m.group(1).replace('""', '"') if m else (s if re.fullmatch(r"-?\d+(?:\.\d+)?", s) else None)
            x = None
            if t == "cellIs" and o in ("greaterThan", "lessThan", "equal") and fx and lit(fx[0]) is not None:
                x = {"op": {"greaterThan": "gt", "lessThan": "lt", "equal": "eq"}[o], "a": lit(fx[0])}
            elif t == "cellIs" and o == "between" and len(fx) > 1 and lit(fx[0]) is not None and lit(fx[1]) is not None:
                x = {"op": "between", "a": lit(fx[0]), "b": lit(fx[1])}
            elif t == "containsText" and rule.get("text"):
                x = {"op": "contains", "a": rule.get("text")}
            elif t == "containsBlanks":
                x = {"op": "empty"}
            elif t == "expression" and fx and re.fullmatch(r"AND\(ISNUMBER\(\$?[A-Z]{1,3}\$?\d+\),\$?[A-Z]{1,3}\$?\d+<TODAY\(\)\)", fx[0].replace(" ", "")):
                x = {"op": "overdue"}
            if x:
                out.append({**x, "cols": cols, "r0": r0, "r1": r1, "color": ink or "", "fill": fill or "", "eq_lit": t == "cellIs" and o == "equal"})
    return out[:SHFM_RULES_MAX]


def shfm_import_apply(c, sheet, book, grid, hdr, width, uid):
    """The formats, merges and rules of a read file into the new sheet (sheets/io.py shx_import, after its cells)."""
    nrows = len(book.rows)
    want = {}
    for ri, r in enumerate(grid.rows[hdr:]):
        if ri >= nrows:
            break
        for ci in range(min(width, len(r))):
            f = r[ci].get("sty") if isinstance(r[ci], dict) else None
            if f:
                want[(ri, ci)] = dict(f)
    for (r0, c0, r1, c1) in getattr(grid, "merges", []):
        ri, ci = r0 - 1 - hdr, c0
        if ri < 0 or ri >= nrows or ci >= width:
            continue
        h, w = min(r1 - r0 + 1, SHFM_MERGE_MAX[0], nrows - ri), min(c1 - c0 + 1, SHFM_MERGE_MAX[1], width - ci)
        if h * w > 1:
            want.setdefault((ri, ci), {})["merge"] = [h, w]
    for (ri, ci), f in want.items():
        try:
            raw = shfm_clean(f)
        except BadInput:
            continue
        if not raw:
            continue
        x = book.ensure(book.rows[ri]["id"], book.cols[ci]["id"], uid)
        c.execute("UPDATE sheet_cells SET fmt=? WHERE id=?", (raw, x["id"]))
        x["fmt"] = raw
    rules = []
    for r in getattr(grid, "fmt_rules", []):
        cols = [book.cols[ci]["id"] for ci in r["cols"] if ci < width]
        if not cols or (r.get("eq_lit") and all(ci in grid.lists for ci in r["cols"])):
            continue  # an option colour of a drop-down list (sheets/io.py reads it as the option's colour)
        a, b = r["r0"] - 1 - hdr, r["r1"] - 1 - hdr
        rows = None
        if a > 0 or b < nrows - 1:
            a, b = max(a, 0), min(b, nrows - 1)
            if a > b:
                continue
            rows = [book.rows[a]["id"], book.rows[b]["id"]]
        rules.append({"cols": cols, "rows": rows, "op": r["op"], "a": r.get("a", ""), "b": r.get("b", ""),
                      "color": r["color"], "fill": r["fill"]})
    if rules:
        try:
            clean = shfm_rules_clean(c, sheet["id"], rules)
        except BadInput:
            clean = []
        if clean:
            c.execute("UPDATE sheets SET fmt_rules=? WHERE id=?", (json.dumps(clean, separators=(",", ":")), sheet["id"]))
