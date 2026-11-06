"""2.578.0 (#3462): the everyday formula functions of tables that were still missing next to sheets/shfuncs.py.

SUMMEWENNS/SUMIFS, ZÄHLENWENNS/COUNTIFS, MITTELWERTWENN/AVERAGEIF, INDEX, VERGLEICH/MATCH, WENNFEHLER/IFERROR, UND/AND,
ODER/OR, NICHT/NOT, ABS, AUFRUNDEN/ROUNDUP, ABRUNDEN/ROUNDDOWN, NETTOARBEITSTAGE/NETWORKDAYS, ARBEITSTAG/WORKDAY,
WOCHENTAG/WEEKDAY, KALENDERWOCHE/WEEKNUM, ISOKALENDERWOCHE/ISOWEEKNUM, TEXT, ANZAHL2/COUNTA, JETZT/NOW.
The names live in the tables of sheets/shfuncs.py (SHF_NAMES, SHF_HELP, SHF_DE, SHF_EXCEL), so parsing, the display in the
viewer's language, the completion and the .xlsx mapping take them like the older ones; shf_call hands the keys here.

Two defaults differ from Excel on purpose, like SVERWEIS (exact lookups): VERGLEICH/MATCH without its third argument looks for
the exact value (Excel: 1 = sorted, approximate) and KALENDERWOCHE/WEEKNUM without its second argument counts ISO weeks (the
week numbers of German calendars; Excel: 1 = weeks from Sunday with 1 January in week 1). Import and export add the argument
(shf_arg_fill), so a formula keeps its meaning in both directions.
The values know no time of day: JETZT/NOW is the date and time as text ("06.11.2026 14:05"); TEXT reads it back.
"""
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal

from ..core.db import local_now
from .formula import ShErr, _date, _lg, _num, _text, _truthy, sh_parse_date, sh_parse_number
from .shfuncs import _Grid, _args, _int, _lookup_approx, _lookup_exact, _matches, _safe, _SKIP, _as, shf_crit, shf_grid, shf_spend

SHF2_WORKDAYS_MAX = 100_000  # ARBEITSTAG: work days one call may step (about 380 years)
_KEEP = ("cycle",)  # WENNFEHLER never hides a cycle: the cells of a cycle stay marked as such
_DT = re.compile(r"\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?\s*\Z")
_DT_ISO = re.compile(r"\s*(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?\s*\Z")
_MONTHS = {"de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"),
           "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
           "fr": ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"),
           "es": ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"),
           "it": ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"),
           "nl": ("januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december")}
_DAYS = {"de": ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"),
         "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
         "fr": ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"),
         "es": ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"),
         "it": ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"),
         "nl": ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")}


# ---------------------------------------------------------------- import / export: the arguments Excel reads otherwise
_FILL = {"vlookup": 3, "match": 2, "weeknum": 1}  # key -> the argument count whose meaning differs from Excel
_FILL_TO = {"xl": {"vlookup": ",FALSE", "match": ",0", "weeknum": ",21"},  # Kalmido -> Excel
            "kalmido": {"vlookup": ";WAHR", "match": ";1", "weeknum": ";1"}}  # Excel -> Kalmido


def shf_arg_fill(toks, way):
    """{index of the closing ")": text to put before it} for the functions whose short form means something else in Excel
    (SVERWEIS with 3, VERGLEICH with 2, KALENDERWOCHE with 1 argument); way "xl" (export) or "kalmido" (import)."""
    from .formula import sh_fn_key
    out, stack = {}, []
    for i, t in enumerate(toks):
        if t[0] == "(":
            fn = toks[i - 1][1] if i and toks[i - 1][0] == "fn" else ""
            key = sh_fn_key(re.sub(r"^_xl(fn|ws)\.", "", fn, flags=re.I)) if fn else None
            stack.append([key if key in _FILL else None, 0, i])
        elif t[0] == "sep" and stack:
            stack[-1][1] += 1
        elif t[0] == ")" and stack:
            key, n, at = stack.pop()
            if key and n + (0 if toks[at + 1][0] == ")" else 1) == _FILL[key]:
                out[i] = _FILL_TO[way][key]
    return out


# ---------------------------------------------------------------- conditions over several ranges
def _pairs(sv, args, name):
    """(range node, grid, criterion) per pair; every range must have the shape of the first."""
    out, shape = [], None
    for k in range(0, len(args), 2):
        if args[k] is None or k + 1 >= len(args):
            raise ShErr("syntax", name)
        g = shf_grid(sv, args[k])
        if shape is None:
            shape = (g.nrows, g.ncols)
        elif (g.nrows, g.ncols) != shape:
            raise ShErr("type")
        out.append((args[k], g, shf_crit(sv.scalar(args[k + 1]))))
    return out, shape


def _hits(sv, pairs):
    """The positions that meet every criterion, in order."""
    pos = None
    for node, g, cr in pairs:
        ps = set(_matches(sv, node, g, cr))
        pos = ps if pos is None else pos & ps
        if not pos:
            return []
    return sorted(pos or ())


def _sumifs(sv, args):
    if len(args) < 3 or len(args) % 2 == 0 or args[0] is None:
        raise ShErr("syntax", "SUMMEWENNS")
    s = shf_grid(sv, args[0])
    pairs, shape = _pairs(sv, args[1:], "SUMMEWENNS")
    if (s.nrows, s.ncols) != shape:
        raise ShErr("type")
    return sum((x for x in (s.val(p) for p in _hits(sv, pairs)) if isinstance(x, float) and not isinstance(x, bool)), 0.0)


def _countifs(sv, args):
    if len(args) < 2 or len(args) % 2:
        raise ShErr("syntax", "ZÄHLENWENNS")
    pairs, _shape = _pairs(sv, args, "ZÄHLENWENNS")
    return float(len(_hits(sv, pairs)))


def _averageif(sv, args):
    _args("MITTELWERTWENN", args, 2, 3)
    g = shf_grid(sv, args[0])
    cr = shf_crit(sv.scalar(args[1]))
    a = shf_grid(sv, args[2]) if len(args) > 2 and args[2] is not None else g
    xs = []
    for p in _matches(sv, args[0], g, cr):
        if p[0] < a.nrows and p[1] < a.ncols:
            x = a.val(p)
            if isinstance(x, float) and not isinstance(x, bool):
                xs.append(x)
    if not xs:
        raise ShErr("div0")
    return sum(xs) / len(xs)


# ---------------------------------------------------------------- INDEX, MATCH
def _index(sv, args):
    _args("INDEX", args, 2, 3)
    g = shf_grid(sv, args[0])
    r = _int(sv.scalar(args[1]))
    c = _int(sv.scalar(args[2])) if len(args) > 2 and args[2] is not None else None
    if c is None:
        if g.nrows == 1 and g.ncols > 1:  # INDEX(A1:E1; 3): along a row
            r, c = 1, r
        else:
            c = 1
    if r < 1 or c < 1:
        raise ShErr("type")  # 0 = a whole row / column: no single value
    if r > g.nrows or c > g.ncols:
        raise ShErr("ref")
    return g.val((r - 1, c - 1))


def _lookup_ge(sv, grid, col, v):
    """The row with the smallest value >= v (MATCH type -1, a column sorted from large to small)."""
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
        if xv is None or xv < want:
            continue
        if best_v is None or xv <= best_v:
            best, best_v = p, xv
    return best


def _match(sv, args):
    _args("VERGLEICH", args, 2, 3)
    v = sv.scalar(args[0])
    g = shf_grid(sv, args[1])
    typ = _int(sv.scalar(args[2])) if len(args) > 2 and args[2] is not None else 0
    if typ not in (-1, 0, 1):
        raise ShErr("type")
    node = args[1]
    if g.ncols != 1:
        if g.nrows != 1:
            raise ShErr("type")  # a rectangle: MATCH searches one row or one column
        g = _Grid(g.ncols, 1, {(c, 0): k for (_r, c), k in g.ids.items()}, g.get)
        node = ("flip",) + tuple(node)
    if v is None or v == "":
        raise ShErr("na")
    p = (_lookup_exact(sv, node, g, 0, v) if typ == 0 else _lookup_approx(sv, g, 0, v) if typ == 1 else _lookup_ge(sv, g, 0, v))
    if p is None:
        raise ShErr("na")
    return float(p[0] + 1)


# ---------------------------------------------------------------- logic
def _iferror(sv, args):
    _args("WENNFEHLER", args, 2, 2)
    try:
        return sv.scalar(args[0])
    except ShErr as e:
        if e.kind in _KEEP or e.detail == "big":  # a cycle or the work budget of the sheet: not a value to replace
            raise
        return sv.scalar(args[1])


def _bools(sv, args):
    """The truth values of the arguments: a range gives its numbers and WAHR / FALSCH (text and empty cells are left out)."""
    out = []
    for a in args:
        if a is None:
            continue
        v = sv.ev(a)
        if isinstance(v, list):
            out.extend(_truthy(x) for x in v if isinstance(x, (bool, float)))
        else:
            out.append(_truthy(v))
    if not out:
        raise ShErr("type")
    return out


# ---------------------------------------------------------------- numbers
_ROUNDING = {"roundup": ROUND_UP, "rounddown": ROUND_DOWN}


def _round_dir(sv, args, key):
    _args("AUFRUNDEN" if key == "roundup" else "ABRUNDEN", args, 1, 2)
    x = _num(sv.scalar(args[0]))
    d = _int(sv.scalar(args[1])) if len(args) > 1 and args[1] is not None else 0
    if not -10 <= d <= 10:
        raise ShErr("type")
    mode = _ROUNDING[key]  # away from zero / towards zero, like spreadsheets
    q = Decimal(1).scaleb(-d)
    return float((Decimal(repr(x)) / q).quantize(Decimal(1), rounding=mode) * q)


# ---------------------------------------------------------------- work days and weeks
def _holidays(sv, node):
    """The dates of the holidays argument (a range, a cell or one date); empty cells are left out."""
    if node is None:
        return frozenset()
    v = sv.ev(node)
    out = set()
    for x in (v if isinstance(v, list) else [v]):
        if x is None or x == "":
            continue
        out.add(_date(x))
    shf_spend(sv, len(out) + 1)
    return frozenset(out)


def _weekdays(a, b):
    """Mondays to Fridays from a to b, both included (a <= b)."""
    weeks, rest = divmod((b - a).days + 1, 7)
    n, wd = weeks * 5, a.weekday()
    return n + sum(1 for i in range(rest) if (wd + i) % 7 < 5)


def _networkdays(sv, args):
    _args("NETTOARBEITSTAGE", args, 2, 3)
    a, b = _date(sv.scalar(args[0])), _date(sv.scalar(args[1]))
    hol = _holidays(sv, args[2] if len(args) > 2 else None)
    sign = 1
    if a > b:
        a, b, sign = b, a, -1
    n = _weekdays(a, b) - sum(1 for h in hol if a <= h <= b and h.weekday() < 5)
    return float(sign * n)


def _workday(sv, args):
    _args("ARBEITSTAG", args, 2, 3)
    d = _date(sv.scalar(args[0]))
    n = _int(sv.scalar(args[1]))
    if abs(n) > SHF2_WORKDAYS_MAX:
        raise ShErr("type")
    hol = _holidays(sv, args[2] if len(args) > 2 else None)
    step = 1 if n > 0 else -1
    shf_spend(sv, abs(n) * 7 // 5 + 1)
    try:
        while n:
            d += timedelta(days=step)
            if d.weekday() < 5 and d not in hol:
                n -= step
    except OverflowError:
        raise ShErr("type") from None
    return d


def _weekday(sv, args):
    _args("WOCHENTAG", args, 1, 2)
    wd = _date(sv.scalar(args[0])).weekday()  # Monday = 0
    t = _int(sv.scalar(args[1])) if len(args) > 1 and args[1] is not None else 1
    if t == 1:
        return float((wd + 1) % 7 + 1)  # Sunday = 1 .. Saturday = 7
    if t == 2:
        return float(wd + 1)  # Monday = 1 .. Sunday = 7
    if t == 3:
        return float(wd)  # Monday = 0 .. Sunday = 6
    if 11 <= t <= 17:
        return float((wd - (t - 11)) % 7 + 1)  # 11 = Monday first .. 17 = Sunday first
    raise ShErr("type")


_WEEK_START = {1: 6, 17: 6, 2: 0, 11: 0, 12: 1, 13: 2, 14: 3, 15: 4, 16: 5}  # type -> the weekday a week starts with


def _weeknum(sv, args):
    _args("KALENDERWOCHE", args, 1, 2)
    d = _date(sv.scalar(args[0]))
    t = _int(sv.scalar(args[1])) if len(args) > 1 and args[1] is not None else 21
    if t == 21:
        return float(d.isocalendar()[1])
    if t not in _WEEK_START:
        raise ShErr("type")
    jan1 = date(d.year, 1, 1)
    return float(((d - jan1).days + (jan1.weekday() - _WEEK_START[t]) % 7) // 7 + 1)


# ---------------------------------------------------------------- TEXT, NOW
def _now_text(lg):
    t = local_now()
    lang = _lg(lg)
    if lang == "en":
        return t.strftime("%Y-%m-%d %H:%M")
    return t.strftime("%d/%m/%Y %H:%M" if lang in ("fr", "es", "it") else "%d-%m-%Y %H:%M" if lang == "nl" else "%d.%m.%Y %H:%M")


def _as_datetime(v):
    """A date / a date with time ("06.11.2026 14:05", ISO) -> datetime, else None."""
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if not isinstance(v, str):
        return None
    m = _DT_ISO.match(v)
    if m:
        y, mo, d, h, mi, s = m.groups()
    else:
        m = _DT.match(v)
        if not m:
            d0 = sh_parse_date(v.strip())
            return datetime(d0.year, d0.month, d0.day) if d0 else None
        d, mo, y, h, mi, s = m.groups()
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    except ValueError:
        return None


_DATE_TOK = re.compile(r"JJJJ|YYYY|JJ|YY|MMMM|MMM|MM|M|TTTT|DDDD|TTT|DDD|TT|DD|T|D|hh|h|ss|s|AM/PM", re.I)


def _fmt_date(dt, f, lg):
    lang = _lg(lg) if _lg(lg) in _MONTHS else "en"
    toks = []  # (kind, text): literal text or a token
    i, n = 0, len(f)
    while i < n:
        ch = f[i]
        if ch == '"':
            j = f.find('"', i + 1)
            j = n if j < 0 else j
            toks.append(("lit", f[i + 1:j]))
            i = j + 1
            continue
        if ch == "\\" and i + 1 < n:
            toks.append(("lit", f[i + 1]))
            i += 2
            continue
        m = _DATE_TOK.match(f, i)
        if m:
            toks.append(("tok", m.group()))
            i = m.end()
            continue
        toks.append(("lit", ch))
        i += 1
    out = []
    for k, (kind, t) in enumerate(toks):
        if kind == "lit":
            out.append(t)
            continue
        u = t.upper()
        if u[0] == "M" and len(u) <= 2:  # minutes right after hours or right before seconds
            prev = next((x[1].upper() for x in reversed(toks[:k]) if x[0] == "tok"), "")
            nxt = next((x[1].upper() for x in toks[k + 1:] if x[0] == "tok"), "")
            if prev.startswith("H") or nxt.startswith("S"):
                out.append(f"{dt.minute:02d}" if len(u) == 2 else str(dt.minute))
                continue
        if u in ("JJJJ", "YYYY"):
            out.append(f"{dt.year:04d}")
        elif u in ("JJ", "YY"):
            out.append(f"{dt.year % 100:02d}")
        elif u == "MMMM":
            out.append(_MONTHS[lang][dt.month - 1])
        elif u == "MMM":
            out.append(_MONTHS[lang][dt.month - 1][:3])
        elif u == "MM":
            out.append(f"{dt.month:02d}")
        elif u == "M":
            out.append(str(dt.month))
        elif u in ("TTTT", "DDDD"):
            out.append(_DAYS[lang][dt.weekday()])
        elif u in ("TTT", "DDD"):
            out.append(_DAYS[lang][dt.weekday()][:2 if lang == "de" else 3])
        elif u in ("TT", "DD"):
            out.append(f"{dt.day:02d}")
        elif u in ("T", "D"):
            out.append(str(dt.day))
        elif u == "HH":
            out.append(f"{dt.hour:02d}")
        elif u == "H":
            out.append(str(dt.hour))
        elif u == "SS":
            out.append(f"{dt.second:02d}")
        elif u == "S":
            out.append(str(dt.second))
        elif u == "AM/PM":
            out.append("AM" if dt.hour < 12 else "PM")
    return "".join(out)


def _is_date_fmt(f):
    plain = re.sub(r'"[^"]*"|\\.', "", f)
    return bool(re.search(r"[JjYyTtDdHhSs]|M", plain)) and not re.search(r"[0#]", plain)


def _seps(lg):
    lang = _lg(lg)
    return (".", ",") if lang == "en" else (",", " " if lang == "fr" else ".")


def _fmt_number(x, f, lg):
    """A number in an Excel number format: 0 / # places, a decimal sign (the last of . and , ; one alone is thousands when
    three places follow and a # stands before it), thousands, %, text around it ("0,00 €", "#.##0", "0%")."""
    secs = re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*\Z)', f)
    if len(secs) > 1 and x < 0:
        f, x = secs[1], -x
    elif len(secs) > 2 and x == 0:
        f = secs[2]
    else:
        f = secs[0]
    lit = re.sub(r'"([^"]*)"', lambda m: "\x01" * len(m.group(1)), f)  # quoted text never counts as a place
    m = re.search(r"[0#?][0#?.,\s]*[0#?]|[0#?]", lit)
    if not m:
        return re.sub(r'"([^"]*)"', r"\1", f)
    core = m.group()
    pre = re.sub(r'"([^"]*)"', r"\1", f[:m.start()]).replace("\\", "")
    post = re.sub(r'"([^"]*)"', r"\1", f[m.end():]).replace("\\", "")
    if "%" in pre + post:
        x *= 100
    dots = [i for i, ch in enumerate(core) if ch in ".,"]
    dec_at = None
    if dots:
        last = dots[-1]
        if len({core[i] for i in dots}) > 1:
            dec_at = last
        else:
            after = core[last + 1:]
            alone_thousands = len(after) == 3 and "#" in core[:last]
            dec_at = None if alone_thousands or len(dots) > 1 else last
    intpart = core if dec_at is None else core[:dec_at]
    decs = 0 if dec_at is None else sum(1 for ch in core[dec_at + 1:] if ch in "0#?")
    group = any(ch in ".," for ch in intpart) or bool(re.search(r"[0#]\s[0#]", intpart))
    q = Decimal(1).scaleb(-decs)
    neg = x < 0
    s = format(abs(Decimal(repr(x))).quantize(q, rounding=ROUND_HALF_UP), "f")
    whole, _, frac = s.partition(".")
    need = intpart.count("0")
    whole = whole.lstrip("0").rjust(max(need, 0), "0") if whole != "0" or need else ""
    if group and len(whole) > 3:
        th = _seps(lg)[1]
        whole = "{:,}".format(int(whole)).replace(",", th)
    if decs:
        opt = sum(1 for ch in core[dec_at + 1:] if ch == "#")  # # places after the sign drop trailing zeros
        frac = frac[:decs]
        while opt and frac.endswith("0"):
            frac, opt = frac[:-1], opt - 1
    body = whole + ((_seps(lg)[0] + frac) if decs and frac else "")
    if neg and len(secs) == 1 and any(ch in "123456789" for ch in body):
        pre = "-" + pre
    return pre + body + post


def _text_fn(sv, args):
    _args("TEXT", args, 2, 2)
    v = sv.scalar(args[0])
    f = _text(sv.scalar(args[1]), sv.env.lg)
    if len(f) > 200:
        raise ShErr("type")
    lg = sv.env.lg
    if f == "@" or f == "":
        return _text(v, lg)
    if _is_date_fmt(f):
        dt = _as_datetime(v)
        if dt is None:
            if isinstance(v, str) and sh_parse_number(v) is None:
                return v
            raise ShErr("type")
        return _fmt_date(dt, f, lg)
    if isinstance(v, bool):
        return _text(v, lg)
    if isinstance(v, date):
        x = float(v.toordinal())
    elif isinstance(v, str):
        x = sh_parse_number(v)
        if x is None:
            return v  # text in a number format stays as it is (like spreadsheets)
    else:
        x = _num(v)
    return _fmt_number(x, f, lg)


def _counta(sv, args):
    n = 0
    for a in args:
        if a is None:
            continue
        v = sv.ev(a)
        if isinstance(v, list):
            n += sum(1 for x in v if x is not None and x != "")
        else:
            n += 1
    return float(n)


# ---------------------------------------------------------------- dispatch
def shf2_call(sv, key, args):
    """The value of function key (one of the 2.578.0 keys of SHF_NAMES); another key is a syntax error."""
    if key == "sumifs":
        return _sumifs(sv, args)
    if key == "countifs":
        return _countifs(sv, args)
    if key == "averageif":
        return _averageif(sv, args)
    if key == "index":
        return _index(sv, args)
    if key == "match":
        return _match(sv, args)
    if key == "iferror":
        return _iferror(sv, args)
    if key in ("and", "or"):
        if not args:
            raise ShErr("syntax", "UND" if key == "and" else "ODER")
        xs = _bools(sv, args)
        return all(xs) if key == "and" else any(xs)
    if key == "not":
        _args("NICHT", args, 1, 1)
        return not _truthy(sv.scalar(args[0]))
    if key == "abs":
        _args("ABS", args, 1, 1)
        return abs(_num(sv.scalar(args[0])))
    if key in ("roundup", "rounddown"):
        return _round_dir(sv, args, key)
    if key == "networkdays":
        return _networkdays(sv, args)
    if key == "workday":
        return _workday(sv, args)
    if key == "weekday":
        return _weekday(sv, args)
    if key == "weeknum":
        return _weeknum(sv, args)
    if key == "isoweeknum":
        _args("ISOKALENDERWOCHE", args, 1, 1)
        return float(_date(sv.scalar(args[0])).isocalendar()[1])
    if key == "text":
        return _text_fn(sv, args)
    if key == "counta":
        if not args:
            raise ShErr("syntax", "ANZAHL2")
        return _counta(sv, args)
    if key == "now":
        if any(a is not None for a in args):
            raise ShErr("syntax", "JETZT")
        return _now_text(sv.env.lg)
    raise ShErr("syntax", key)
