"""2.124.0 A (#2109): the newer formula functions of tables -- conditional sum / count, lookups, text and date functions.

SUMMEWENN/SUMIF, ZÄHLENWENN/COUNTIF, SVERWEIS/VLOOKUP, XVERWEIS/XLOOKUP, LINKS/LEFT, RECHTS/RIGHT, TEIL/MID, LÄNGE/LEN,
VERKETTEN/CONCAT(ENATE), GLÄTTEN/TRIM, GROSS/UPPER, KLEIN/LOWER, DATUM/DATE, JAHR/YEAR, MONAT/MONTH, TAG/DAY, EDATUM/EDATE.
The parser (sheets/formula.py) asks sh_fn_key for a name it does not know itself and ShEval.fn hands these keys to shf_call;
the classic nine stay in formula.py untouched. The new names are no reserved words: a column or cell called "Datum" or "Tag"
keeps working (a function is only a name right before "(").

Criteria (SUMIF / COUNTIF) like spreadsheets: a number, a date, text (case does not matter, * and ? as wildcards, ~ escapes),
or text with a comparison in front (">5", "<>x", "<=2026-01-01", "=" = empty, "<>" = not empty). Lookups are exact by default
(VLOOKUP's fourth argument WAHR/TRUE = the largest value <= the searched one, the first column sorted), "not found" = the
error kind "na". Ranges are read cell by cell from what exists (never every position of a huge rectangle); the cells visited
per evaluation of a sheet are capped (SHF_WORK_BUDGET), an exact lookup builds its index once per evaluation, so 5,000 rows
each with a VLOOKUP over 5,000 rows stay cheap and a sheet cannot become a time bomb.
"""
import calendar
import re
from datetime import date, timedelta

from ..core.i18n import N_
from .formula import SH_BOOLS, SH_RAW_MAX, ShErr, _date, _num, _text, _truthy, sh_parse_date, sh_parse_number

# name (lower case) -> key; German and English names like the classic functions
SHF_NAMES = {"summewenn": "sumif", "sumif": "sumif", "zählenwenn": "countif", "zaehlenwenn": "countif", "countif": "countif",
             "sverweis": "vlookup", "vlookup": "vlookup", "xverweis": "xlookup", "xlookup": "xlookup",
             "links": "left", "left": "left", "rechts": "right", "right": "right", "teil": "mid", "mid": "mid",
             "länge": "len", "laenge": "len", "len": "len", "verketten": "concat", "concat": "concat", "concatenate": "concat",
             "textkette": "concat", "glätten": "trim", "glaetten": "trim", "trim": "trim", "gross": "upper", "groß": "upper",
             "upper": "upper", "klein": "lower", "lower": "lower", "datum": "date", "date": "date", "jahr": "year", "year": "year",
             "monat": "month", "month": "month", "tag": "day", "day": "day", "edatum": "edate", "edate": "edate"}
# what the completion offers, with a short help (German names like the classic ones)
SHF_HELP = {"SUMMEWENN": N_("SUMIF(range; criterion; [sum range]): sum of the values whose cell meets the criterion"),
            "ZÄHLENWENN": N_("COUNTIF(range; criterion): number of cells that meet the criterion, e.g. \">5\" or \"open\""),
            "SVERWEIS": N_("VLOOKUP(value; range; column; [approximate]): a value from the row whose first cell matches"),
            "XVERWEIS": N_("XLOOKUP(value; search range; result range; [if not found])"),
            "LINKS": N_("LEFT(text; [count]): the first characters"), "RECHTS": N_("RIGHT(text; [count]): the last characters"),
            "TEIL": N_("MID(text; start; count): characters from the middle"), "LÄNGE": N_("LEN(text): number of characters"),
            "VERKETTEN": N_("CONCAT(text; ...): joins texts"), "GLÄTTEN": N_("TRIM(text): removes extra spaces"),
            "GROSS": N_("UPPER(text): capital letters"), "KLEIN": N_("LOWER(text): small letters"),
            "DATUM": N_("DATE(year; month; day)"), "JAHR": N_("YEAR(date)"), "MONAT": N_("MONTH(date)"),
            "TAG": N_("DAY(date): the day of the month"), "EDATUM": N_("EDATE(date; months): the date some months later")}
# import / export (sheets/io.py): key -> the German name Kalmido writes, key -> the name in an .xlsx file
SHF_DE = {"sumif": "SUMMEWENN", "countif": "ZÄHLENWENN", "vlookup": "SVERWEIS", "xlookup": "XVERWEIS", "left": "LINKS",
          "right": "RECHTS", "mid": "TEIL", "len": "LÄNGE", "concat": "VERKETTEN", "trim": "GLÄTTEN", "upper": "GROSS",
          "lower": "KLEIN", "date": "DATUM", "year": "JAHR", "month": "MONAT", "day": "TAG", "edate": "EDATUM"}
SHF_EXCEL = {"sumif": "SUMIF", "countif": "COUNTIF", "vlookup": "VLOOKUP", "xlookup": "_xlfn.XLOOKUP", "left": "LEFT",
             "right": "RIGHT", "mid": "MID", "len": "LEN", "concat": "_xlfn.CONCAT", "trim": "TRIM", "upper": "UPPER",
             "lower": "LOWER", "date": "DATE", "year": "YEAR", "month": "MONTH", "day": "DAY", "edate": "EDATE"}
SHF_WORK_BUDGET = 3_000_000  # cells one evaluation of a whole sheet may visit in these functions -> "type" / "big"
_OPS = {"=": lambda a, b: a == b, "<>": lambda a, b: a != b, "<": lambda a, b: a < b, ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b}
_CRIT_OP = re.compile(r"(<=|>=|<>|<|>|=)?(.*)\Z", re.S)


# ---------------------------------------------------------------- ranges as grids
class _Grid:
    """A range as rows x columns: ids {(r, c): key} of the cells that exist, get(key) -> value (raises ShErr)."""

    def __init__(self, nrows, ncols, ids, get):
        self.nrows, self.ncols, self.ids, self.get = nrows, ncols, ids, get

    def val(self, pos):
        k = self.ids.get(pos)
        return None if k is None else self.get(k)


def _book_of(sv):
    """The sheet evaluator behind a ShEval (sheets/core.py _Env.ev) or None (a bare evaluation without a sheet)."""
    ev = getattr(sv.env, "ev", None)
    return ev if ev is not None and hasattr(ev, "book") else None


def shf_spend(sv, n):
    """n cells visited: over the budget of this evaluation = an error instead of minutes of work."""
    ev = _book_of(sv) or sv.env
    left = getattr(ev, "shf_work", SHF_WORK_BUDGET) - n
    ev.shf_work = left
    if left < 0:
        raise ShErr("type", "big")


def shf_grid(sv, node):
    """The grid of a range / column / cell argument; anything else is a type error (SUMIF(5; ...))."""
    if node is not None and node[0] in ("xrange", "xcell"):  # 2.124.0 E (#2116): a range of another sheet of the table
        from .shbook import shb_grid
        return shb_grid(sv, node)
    if node is None or node[0] not in ("range", "col", "cell"):
        raise ShErr("type")
    ev = _book_of(sv)
    if ev is None:  # no sheet behind it: the values as one column
        v = sv.ev(node)
        vals = v if isinstance(v, list) else [v]
        shf_spend(sv, len(vals))
        return _Grid(len(vals), 1, {(i, 0): i for i in range(len(vals))}, lambda i: vals[i])
    cache = ev.__dict__.setdefault("shf_grids", {})
    g = cache.get(node)
    if g is None:
        book = ev.book
        if node[0] == "col":
            if node[1] not in book.col_idx:
                raise ShErr("ref")
            ids = {(book.row_idx[x["row_id"]], 0): x["id"] for x in book.col_cells(node[1])}
            g = (len(book.rows), 1, ids)
        else:
            a, b = (node[1], node[1]) if node[0] == "cell" else (node[1], node[2])
            xa, xb = book.cells.get(a), book.cells.get(b)
            if not book.live(xa) or not book.live(xb):
                raise ShErr("ref")
            r1, r2 = sorted((book.row_idx[xa["row_id"]], book.row_idx[xb["row_id"]]))
            c1, c2 = sorted((book.col_idx[xa["col_id"]], book.col_idx[xb["col_id"]]))
            ids = {(book.row_idx[x["row_id"]] - r1, book.col_idx[x["col_id"]] - c1): x["id"] for x in book.rect(r1, r2, c1, c2)}
            g = (r2 - r1 + 1, c2 - c1 + 1, ids)
        shf_spend(sv, len(g[2]) + 1)
        cache[node] = g
    me = sv.env.cell_row["id"]  # a column reference leaves out the formula's own cell (like SUMME(column))
    return _Grid(g[0], g[1], g[2], lambda cid: None if cid == me else ev.value_of(cid))


def _safe(grid, pos):
    """A value of a range that is only searched / compared: an error cell there simply does not match."""
    try:
        return grid.val(pos)
    except ShErr:
        return _SKIP


_SKIP = object()


# ---------------------------------------------------------------- criteria
def _wild(t):
    """A pattern with * ? (~ escapes) -> a matcher on casefolded text (.fullmatch), or None without wildcards.
    2.124.0 review: a linear glob match instead of a regex (".*a.*a.*b" backtracked for minutes on a long cell)."""
    if "*" not in t and "?" not in t:
        return None
    pat, i = [], 0
    while i < len(t):
        ch = t[i]
        if ch == "~" and i + 1 < len(t) and t[i + 1] in "*?~":
            pat.append(t[i + 1])
            i += 2
            continue
        pat.append(_STAR if ch == "*" else _ONE if ch == "?" else ch)
        i += 1
    return _Glob(pat)


_STAR, _ONE = object(), object()


class _Glob:
    """* = any run, ? = one character, everything else literal; O(len(text) * len(pattern)) at worst."""

    def __init__(self, pat):
        self.pat = pat

    def fullmatch(self, text):
        p, n, pi, ti, star, mark = self.pat, len(text), 0, 0, -1, 0
        while ti < n:
            if pi < len(p) and p[pi] is not _STAR and (p[pi] is _ONE or p[pi] == text[ti]):
                pi += 1
                ti += 1
            elif pi < len(p) and p[pi] is _STAR:
                star, mark = pi, ti
                pi += 1
            elif star >= 0:
                pi, mark = star + 1, mark + 1
                ti = mark
            else:
                return False
        while pi < len(p) and p[pi] is _STAR:
            pi += 1
        return pi == len(p)


def shf_crit(v):
    """A criterion -> (op, kind, operand): kind n (number) | d (date) | b (WAHR/FALSCH) | s (text, casefolded) | w (wildcard
    pattern) | e (empty)."""
    if isinstance(v, bool):
        return "=", "b", v
    if isinstance(v, float):
        return "=", "n", v
    if isinstance(v, date):
        return "=", "d", v
    if v is None:
        return "=", "e", None
    m = _CRIT_OP.match(str(v))
    op, rest = m.group(1) or "=", m.group(2)
    if rest == "":
        return op, "e", None
    x = sh_parse_number(rest)
    if x is not None:
        return op, "n", x
    d = sh_parse_date(rest)
    if d is not None:
        return op, "d", d
    low = rest.casefold()
    if low in SH_BOOLS:
        return op, "b", SH_BOOLS[low]
    if op in ("=", "<>"):
        w = _wild(low)
        if w is not None:
            return op, "w", w
    return op, "s", low.replace("~*", "*").replace("~?", "?").replace("~~", "~")


def _as(x, kind):
    """A cell value in the criterion's kind, or None when it is of another kind."""
    if x is None or x == "":
        return None
    if kind == "n":
        if isinstance(x, float):
            return x
        return sh_parse_number(x) if isinstance(x, str) else None
    if kind == "d":
        if isinstance(x, date):
            return x
        return sh_parse_date(x) if isinstance(x, str) else None
    if kind == "b":
        if isinstance(x, float) and x in (0.0, 1.0):
            return x == 1.0  # 2.138.4 B (#2371): a checkbox tick is 1 / 0 in formulas, so WAHR / FALSCH hit it
        return x if isinstance(x, bool) else None
    return x.casefold() if isinstance(x, str) else None


def shf_hit(x, cr):
    """Does value x meet criterion cr (shf_crit)?"""
    op, kind, val = cr
    if kind == "e":
        empty = x is None or x == ""
        return empty if op == "=" else (not empty if op == "<>" else False)
    xv = _as(x, "s" if kind == "w" else kind)
    if xv is None:
        return op == "<>"
    if kind == "w":
        r = bool(val.fullmatch(xv))
        return r if op == "=" else not r
    try:
        return _OPS[op](xv, val)
    except TypeError:
        return op == "<>"


def _keys(x):
    """The equality keys of a value (a text that reads as a number / date matches those too)."""
    if isinstance(x, bool):
        return (("b", x),)
    if isinstance(x, float):
        return (("n", x),)
    if isinstance(x, date):
        return (("d", x),)
    if isinstance(x, str) and x != "":
        out = [("s", x.casefold())]
        n = sh_parse_number(x)
        if n is not None:
            out.append(("n", n))
        d = sh_parse_date(x)
        if d is not None:
            out.append(("d", d))
        return tuple(out)
    return ()


def _index(sv, node, grid, col=None):
    """{key: [positions in order]} of a grid (or one column of it), built once per evaluation."""
    ev = _book_of(sv)
    cache = ev.__dict__.setdefault("shf_index", {}) if ev is not None else {}
    idx = cache.get((node, col))
    if idx is None:
        idx, whole = {}, True
        poss = sorted(p for p in grid.ids if col is None or p[1] == col)
        shf_spend(sv, len(poss))
        for p in poss:
            k = grid.ids[p]
            try:
                x = grid.get(k) if ev is None or getattr(grid, "shb", False) else ev.value_of(k)  # the own cell is filtered by the caller; 2.124.0 E (#2116): a grid of another sheet reads there
            except ShErr as e:
                whole = whole and e.kind != "cycle"  # not evaluated yet (the own cell): this index is for this cell only
                continue
            for key in _keys(x):
                idx.setdefault(key, []).append(p)
        if ev is not None and whole:
            cache[(node, col)] = idx
    return idx


def _matches(sv, node, grid, cr):
    """The positions of a grid whose value meets cr (in order). Equality uses the index; empties count as positions."""
    op, kind, val = cr
    me = sv.env.cell_row["id"] if _book_of(sv) is not None else None
    if op == "=" and kind in ("n", "d", "s"):  # 2.138.4 B (#2371): WAHR / FALSCH compare one by one (_as: a tick 1 / 0 hits them), the index stays as the lookups use it
        return [p for p in _index(sv, node, grid).get((kind, val), ()) if grid.ids[p] != me]
    if shf_hit(None, cr):  # empty cells match too: every position
        shf_spend(sv, grid.nrows * grid.ncols)
        out = []
        for r in range(grid.nrows):
            for c in range(grid.ncols):
                x = _safe(grid, (r, c))
                if x is not _SKIP and shf_hit(x, cr):
                    out.append((r, c))
        return out
    shf_spend(sv, len(grid.ids))
    out = []
    for p in sorted(grid.ids):
        x = _safe(grid, p)
        if x is not _SKIP and x is not None and shf_hit(x, cr):
            out.append(p)
    return out


def shf_vlookup3(toks):
    """The indexes of the ")" that close a VLOOKUP / SVERWEIS with exactly three arguments: there Excel looks up approximately
    and Kalmido exactly, so import and export add the fourth argument (WAHR / FALSE) to keep the meaning."""
    out, stack = set(), []
    for i, t in enumerate(toks):
        if t[0] == "(":
            fn = toks[i - 1][1] if i and toks[i - 1][0] == "fn" else ""
            stack.append([re.sub(r"^_xl(fn|ws)\.", "", fn, flags=re.I).lower() in ("vlookup", "sverweis"), 0])
        elif t[0] == "sep" and stack:
            stack[-1][1] += 1
        elif t[0] == ")" and stack:
            is_v, n = stack.pop()
            if is_v and n == 2:
                out.add(i)
    return out


# ---------------------------------------------------------------- the functions
def _args(name, args, lo, hi):
    if not lo <= len(args) <= hi or any(a is None for a in args[:lo]):
        raise ShErr("syntax", name)


def _int(v):
    x = _num(v)
    if abs(x) > 1e9:
        raise ShErr("type")
    return int(x)


def _sumif(sv, args):
    _args("SUMMEWENN", args, 2, 3)
    g = shf_grid(sv, args[0])
    cr = shf_crit(sv.scalar(args[1]))
    s = shf_grid(sv, args[2]) if len(args) > 2 and args[2] is not None else g
    total = 0.0
    for p in _matches(sv, args[0], g, cr):
        if p[0] >= s.nrows or p[1] >= s.ncols:  # Excel takes the sum range in the criteria range's shape; outside = nothing
            continue
        x = s.val(p)
        if isinstance(x, float):
            total += x
    return total


def _countif(sv, args):
    _args("ZÄHLENWENN", args, 2, 2)
    g = shf_grid(sv, args[0])
    return float(len(_matches(sv, args[0], g, shf_crit(sv.scalar(args[1])))))


def _lookup_exact(sv, node, grid, col, v):
    """The first row (position) of column col whose value equals v (text: case does not matter, * ? wildcards)."""
    if isinstance(v, str) and _wild(v.casefold()) is not None:
        cr = ("=", "w", _wild(v.casefold()))
        shf_spend(sv, grid.nrows)
        for p in sorted(p for p in grid.ids if p[1] == col):
            x = _safe(grid, p)
            if x is not _SKIP and shf_hit(x, cr):
                return p
        return None
    me = sv.env.cell_row["id"] if _book_of(sv) is not None else None
    keys = _keys(v)
    if isinstance(v, str):
        keys = keys[:1]  # a text looks for that text (a number 5 is found by 5, not by "5")
    idx = _index(sv, node, grid, col)
    best = None
    for key in keys:
        for p in idx.get(key, ()):
            if grid.ids[p] != me:
                best = p if best is None or p < best else best
                break
    return best


def _lookup_approx(sv, grid, col, v):
    """The row with the largest value <= v (same kind: number, date or text), for a sorted first column."""
    shf_spend(sv, grid.nrows)
    kind = "n" if isinstance(v, (float, bool)) else "d" if isinstance(v, date) else "s"
    want = _as(float(v) if isinstance(v, bool) else v, kind)
    if want is None:
        return None
    best, best_v = None, None
    for p in sorted(p for p in grid.ids if p[1] == col):
        x = _safe(grid, p)
        if x is _SKIP or isinstance(x, bool):
            continue
        xv = _as(x, kind)
        if xv is None or xv > want:
            continue
        if best_v is None or xv >= best_v:
            best, best_v = p, xv
    return best


def _vlookup(sv, args):
    _args("SVERWEIS", args, 3, 4)
    v = sv.scalar(args[0])
    g = shf_grid(sv, args[1])
    ci = _int(sv.scalar(args[2]))
    if ci < 1:
        raise ShErr("type")
    if ci > g.ncols:
        raise ShErr("ref")
    approx = False
    if len(args) > 3 and args[3] is not None:
        approx = _truthy(sv.scalar(args[3]))
    if v is None or v == "":
        raise ShErr("na")
    p = _lookup_approx(sv, g, 0, v) if approx else _lookup_exact(sv, args[1], g, 0, v)
    if p is None:
        raise ShErr("na")
    return g.val((p[0], ci - 1))


def _xlookup(sv, args):
    _args("XVERWEIS", args, 3, 4)
    v = sv.scalar(args[0])
    g = shf_grid(sv, args[1])
    res = shf_grid(sv, args[2])
    if g.ncols == 1:  # a column: rows match rows
        if res.ncols != 1 or res.nrows != g.nrows:
            raise ShErr("type")
        col, flip = 0, False
    elif g.nrows == 1:  # a row: columns match columns (searched as a column of the swapped grid)
        if res.nrows != 1 or res.ncols != g.ncols:
            raise ShErr("type")
        g = _Grid(g.ncols, 1, {(c, 0): k for (_r, c), k in g.ids.items()}, g.get)
        col, flip = 0, True
    else:
        raise ShErr("type")
    p = None if v is None or v == "" else _lookup_exact(sv, ("flip",) + tuple(args[1]) if flip else args[1], g, col, v)
    if p is None:
        if len(args) > 3 and args[3] is not None:
            return sv.scalar(args[3])
        raise ShErr("na")
    return res.val((0, p[0]) if flip else (p[0], 0))


def _cap(t):
    if len(t) > SH_RAW_MAX:
        raise ShErr("type", "long")
    return t


def _str_arg(sv, a):
    return _text(sv.scalar(a), sv.env.lg)


def _left_right(sv, args, key):
    _args("LINKS" if key == "left" else "RECHTS", args, 1, 2)
    t = _str_arg(sv, args[0])
    n = _int(sv.scalar(args[1])) if len(args) > 1 and args[1] is not None else 1
    if n < 0:
        raise ShErr("type")
    return t[:n] if key == "left" else (t[-n:] if n else "")


def _mid(sv, args):
    _args("TEIL", args, 3, 3)
    t = _str_arg(sv, args[0])
    start, n = _int(sv.scalar(args[1])), _int(sv.scalar(args[2]))
    if start < 1 or n < 0:
        raise ShErr("type")
    return t[start - 1:start - 1 + n]


def _concat(sv, args):
    parts, size = [], 0
    for a in args:
        if a is None:
            continue
        v = sv.ev(a)
        for x in (v if isinstance(v, list) else [v]):
            t = _text(x, sv.env.lg)
            size += len(t)
            if size > SH_RAW_MAX:
                raise ShErr("type", "long")
            parts.append(t)
    spend = getattr(sv.env, "spend", None)
    if spend:
        spend(size)
    return "".join(parts)


def _mkdate(y, m, d):
    """DATE like spreadsheets: years 0..1899 count from 1900, months and days may run over (DATUM(2026;13;1) = 1.1.2027)."""
    if 0 <= y < 1900:
        y += 1900
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    if not 1 <= y <= 9999:
        raise ShErr("type")
    try:
        out = date(y, m, 1) + timedelta(days=d - 1)
    except OverflowError:
        raise ShErr("type") from None
    return out


def _edate(d, months):
    m0 = d.year * 12 + d.month - 1 + months
    y, m = divmod(m0, 12)
    if not 1 <= y <= 9999:
        raise ShErr("type")
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def shf_call(sv, key, args):
    """The value of function key (one of SHF_NAMES' values) with its argument trees, for ShEval sv."""
    if key == "sumif":
        return _sumif(sv, args)
    if key == "countif":
        return _countif(sv, args)
    if key == "vlookup":
        return _vlookup(sv, args)
    if key == "xlookup":
        return _xlookup(sv, args)
    if key in ("left", "right"):
        return _left_right(sv, args, key)
    if key == "mid":
        return _mid(sv, args)
    if key == "concat":
        if not args:
            raise ShErr("syntax", "VERKETTEN")
        return _concat(sv, args)
    if key in ("len", "trim", "upper", "lower"):
        _args({"len": "LÄNGE", "trim": "GLÄTTEN", "upper": "GROSS", "lower": "KLEIN"}[key], args, 1, 1)
        t = _str_arg(sv, args[0])
        if key == "len":
            return float(len(t))
        if key == "trim":
            return re.sub(r" +", " ", t.strip(" "))
        return _cap(t.upper() if key == "upper" else t.lower())
    if key == "date":
        _args("DATUM", args, 3, 3)
        return _mkdate(*(_int(sv.scalar(a)) for a in args))
    if key in ("year", "month", "day"):
        _args({"year": "JAHR", "month": "MONAT", "day": "TAG"}[key], args, 1, 1)
        d = _date(sv.scalar(args[0]))
        return float(d.year if key == "year" else d.month if key == "month" else d.day)
    if key == "edate":
        _args("EDATUM", args, 2, 2)
        return _edate(_date(sv.scalar(args[0])), _int(sv.scalar(args[1])))
    raise ShErr("syntax", key)
