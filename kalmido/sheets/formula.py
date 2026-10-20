"""2.89.0 (#1916): the formula engine of tables ("Excel in simple") -- tokenizer, parser, evaluation, value formats.

An input starting with "=" is a formula: + - * /, brackets, comparisons (= <> < > <= >=, for IF), text in "..." joined with &,
19% = 0.19, arguments split by ";" (German Excel) or "," (accepted too). Functions (German names, English aliases): SUMME/SUM,
MITTELWERT/AVERAGE, MIN, MAX, ANZAHL/COUNT, WENN/IF, RUNDEN/ROUND, HEUTE/TODAY, TAGE/DAYS. A date plus a number is a date.
2.124.0 A (#2109): more in sheets/shfuncs.py (SUMMEWENN, ZÄHLENWENN, SVERWEIS, XVERWEIS, text and date functions).
References: A1, A1:B5, a cell's own name, a column's name (= every cell of the column but the formula's own), Kalmido variables
projekt.<name>.<field>, liste.<name>.<field>, kunde.<name>.<field>, hier.<field> (sheets/vars.py).

Stored with ids, never names: {c:991} a cell (by address or name), {col:5} a column, {p:12}.field / {l:7}.field / {k:3}.field a
project / list / client. Everything else of the input stays as typed, so renaming or sorting changes no formula. The display
form swaps the ids for the current names / addresses (sheets/core.py sh_to_display). Never eval: a tokenizer and a recursive
descent parser build a small tree, evaluated per cell with a cycle check; errors are kinds (ShErr), translated by the caller.
"""
import json
import math
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

SH_RAW_MAX = 10_000
SH_ERR_KINDS = ("deleted", "denied", "cycle", "syntax", "div0", "ref", "type", "na")  # 2.124.0 A (#2109): + na = not found
SH_FUNCS = {"summe": "sum", "sum": "sum", "mittelwert": "avg", "average": "avg", "min": "min", "max": "max",
            "anzahl": "count", "count": "count", "wenn": "if", "if": "if", "runden": "round", "round": "round",
            "heute": "today", "today": "today", "tage": "days", "days": "days"}
SH_FUNC_NAMES = ("SUMME", "MITTELWERT", "MIN", "MAX", "ANZAHL", "WENN", "RUNDEN", "HEUTE", "TAGE")  # what the completion offers
SH_BOOLS = {"wahr": True, "true": True, "falsch": False, "false": False}
SH_VAR_PREFIX = {"projekt": "p", "liste": "l", "kunde": "k"}
SH_RESERVED = set(SH_FUNCS) | set(SH_BOOLS) | set(SH_VAR_PREFIX) | {"hier", "aufgabe"}  # 2.89.0 (#1916, D): + aufgabe.<id>.<field>
SH_TEXT_BUDGET = 2_000_000  # 2.89.0 (#1916): review 1, characters "&" may build in one evaluation of a whole sheet
SH_MAX_DEPTH = 200  # 2.89.0 (#1916): review 4, the depth of a formula's tree (=1+1+...+1 nests to the left) -> syntax "deep"
SH_MAX_NEST = 64  # brackets / functions / signs inside each other (Excel allows 64) -> syntax "deep"

_A1 = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d{1,6})(?![\w.$])")
_IDREF = re.compile(r"\{(c|col|p|l|k|t|x):(\d{1,18})\}((?:\.\w+)?)")  # 2.124.0 E (#2116): + x = a cell of another sheet of the table
# 2.124.0 E (#2116): Blatt2!A1, 'Mein Blatt'!A1:B5 (a sheet of the same table, as in .xlsx)
_XREF = re.compile(r"(?:'((?:[^']|''){1,100})'|([^\W\d][\w.]{0,99}))!\$?([A-Za-z]{1,3})\$?(\d{1,6})(?::\$?([A-Za-z]{1,3})\$?(\d{1,6}))?(?![\w.$(])")
_IDENT = re.compile(r"[^\W\d]\w*(?:\.\w+)*")
_NUM = re.compile(r"\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?|[.,]\d+")
_DATE_DE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_DATE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


class ShErr(Exception):
    """An error of a cell: kind is one of SH_ERR_KINDS, detail a short hint (syntax: what and where)."""

    def __init__(self, kind, detail=""):
        super().__init__(kind)
        self.kind, self.detail = kind, detail


# ---------------------------------------------------------------- tokens
def sh_tokens(s):
    """[(kind, value, start, end)] of a formula without its "=": kind num | str | op | cmp | ( | ) | sep | : | % | a1 | idref |
    ident | fn (an identifier right before "("). A "," between digits is a decimal comma when the formula uses ";" as separator
    or the number is not inside a function's brackets."""
    out, i, n, semi, stack = [], 0, len(s), ";" in s, []
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            j, buf = i + 1, []
            while True:
                if j >= n:
                    raise ShErr("syntax", "quote")
                if s[j] == '"':
                    if j + 1 < n and s[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(s[j])
                j += 1
            out.append(("str", "".join(buf), i, j + 1))
            i = j + 1
            continue
        if ch in "+-*/&":
            out.append(("op", ch, i, i + 1))
            i += 1
            continue
        if ch in "<>=":
            two = s[i:i + 2]
            if two in ("<=", ">=", "<>"):
                out.append(("cmp", two, i, i + 2))
                i += 2
            else:
                out.append(("cmp", ch, i, i + 1))
                i += 1
            continue
        if ch == "(":
            stack.append("f" if out and out[-1][0] == "fn" else "p")
            out.append(("(", ch, i, i + 1))
            i += 1
            continue
        if ch == ")":
            if stack:
                stack.pop()
            out.append((")", ch, i, i + 1))
            i += 1
            continue
        if ch in ";,":
            out.append(("sep", ch, i, i + 1))
            i += 1
            continue
        if ch in ":%":
            out.append((ch, ch, i, i + 1))
            i += 1
            continue
        if ch == "{":
            m = _IDREF.match(s, i)
            if not m:
                raise ShErr("syntax", s[i:i + 12])
            out.append(("idref", (m.group(1), int(m.group(2)), m.group(3)[1:].lower()), i, m.end()))
            i = m.end()
            continue
        if ch.isdigit() or (ch in ".," and i + 1 < n and s[i + 1].isdigit()):
            m = _NUM.match(s, i)
            txt = m.group()
            if "," in txt and not (semi or not stack or stack[-1] == "p"):
                m2 = re.match(r"\d+", s[i:])  # "1,5" inside SUM(1,5) = two arguments
                txt = m2.group() if m2 else txt
            try:
                v = float(txt.replace(",", "."))
            except ValueError:
                raise ShErr("syntax", txt) from None
            if not math.isfinite(v):
                raise ShErr("syntax", txt[:20])
            out.append(("num", v, i, i + len(txt)))
            i += len(txt)
            continue
        if ch == "'" or ch.isalpha() or ch == "_":  # 2.124.0 E (#2116): a reference into another sheet
            m = _XREF.match(s, i)
            if m:
                name = m.group(1).replace("''", "'") if m.group(1) is not None else m.group(2)
                end = (m.group(5).upper(), int(m.group(6))) if m.group(5) else None
                out.append(("xref", (name, (m.group(3).upper(), int(m.group(4))), end), i, m.end()))
                i = m.end()
                continue
        if ch == "$" or ch.isalpha() or ch == "_":
            m = _A1.match(s, i)
            if m and not (i + len(m.group()) < n and s[i + len(m.group())] == "("):
                out.append(("a1", (m.group(1).upper(), int(m.group(2))), i, m.end()))
                i = m.end()
                continue
            m = _IDENT.match(s, i)
            if not m:
                raise ShErr("syntax", ch)
            j = m.end()
            k = j
            while k < n and s[k].isspace():
                k += 1
            out.append(("fn" if k < n and s[k] == "(" else "ident", m.group(), i, j))
            i = j
            continue
        raise ShErr("syntax", ch)
    return out


# ---------------------------------------------------------------- parser
class _Parser:
    """expr = cmp; cmp = concat [(=|<>|<|>|<=|>=) concat]; concat = add (& add)*; add = mul ((+|-) mul)*;
    mul = unary ((*|/) unary)*; unary = (+|-) unary | post; post = prim %*; prim = num | str | ref [: ref] | fn(args) | (expr).
    Nodes: ("n", x) ("s", t) ("b", v) ("neg", a) ("pct", a) (op, a, b) ("cmp", op, a, b) ("fn", key, [args]) and the reference
    nodes the resolver returns: ("cell", id) ("range", id1, id2) ("col", id) ("var", type, id, field) ("here", field)."""

    def __init__(self, toks, resolve):
        self.t, self.i, self.resolve, self.nest = toks, 0, resolve, 0

    def deeper(self):
        self.nest += 1
        if self.nest > SH_MAX_NEST:
            raise ShErr("syntax", "deep")

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None, 0, 0)

    def parse(self):
        if not self.t:
            raise ShErr("syntax", "empty")
        node = self.cmp()
        if self.peek()[0] is not None:
            raise ShErr("syntax", str(self.peek()[1]))
        return node

    def cmp(self):
        self.deeper()
        a = self.concat()
        if self.peek()[0] == "cmp":
            op = self.peek()[1]
            self.i += 1
            a = ("cmp", op, a, self.concat())
        self.nest -= 1
        return a

    def concat(self):
        a = self.add()
        while self.peek()[:2] == ("op", "&"):
            self.i += 1
            a = ("&", a, self.add())
        return a

    def add(self):
        a = self.mul()
        while self.peek()[0] == "op" and self.peek()[1] in "+-":
            op = self.peek()[1]
            self.i += 1
            a = (op, a, self.mul())
        return a

    def mul(self):
        a = self.unary()
        while self.peek()[0] == "op" and self.peek()[1] in "*/":
            op = self.peek()[1]
            self.i += 1
            a = (op, a, self.unary())
        return a

    def unary(self):
        k, v = self.peek()[:2]
        if k == "op" and v in "+-":
            self.i += 1
            self.deeper()
            a = self.unary()
            self.nest -= 1
            return ("neg", a) if v == "-" else a
        a = self.prim()
        while self.peek()[0] == "%":
            self.i += 1
            a = ("pct", a)
        return a

    def ref(self):
        tok = self.peek()
        self.i += 1
        node = self.resolve(tok)
        if self.peek()[0] == ":":
            self.i += 1
            tok2 = self.peek()
            if tok2[0] not in ("a1", "idref", "ident"):
                raise ShErr("syntax", ":")
            self.i += 1
            node2 = self.resolve(tok2)
            if node[0] == "xcell" and node2[0] == "xcell":  # 2.124.0 E (#2116): {x:..}:{x:..} (stored form)
                return ("xrange", node[1], node2[1])
            if node[0] != "cell" or node2[0] != "cell":
                raise ShErr("syntax", ":")
            return ("range", node[1], node2[1])
        return node

    def prim(self):
        k, v = self.peek()[:2]
        if k == "num":
            self.i += 1
            return ("n", v)
        if k == "str":
            self.i += 1
            return ("s", v)
        if k in ("a1", "idref", "xref"):  # 2.124.0 E (#2116): + xref
            return self.ref()
        if k == "ident":
            if v.lower() in SH_BOOLS:
                self.i += 1
                return ("b", SH_BOOLS[v.lower()])
            return self.ref()
        if k == "fn":
            key = sh_fn_key(v)  # 2.124.0 A (#2109): + the functions of sheets/shfuncs.py
            if not key:
                raise ShErr("syntax", v)
            self.i += 2  # name + "("
            args = []
            if self.peek()[0] != ")":
                while True:
                    if self.peek()[0] in ("sep", ")"):
                        args.append(None)  # an empty argument (WENN(a;;b))
                    else:
                        args.append(self.cmp())
                    if self.peek()[0] == "sep":
                        self.i += 1
                        continue
                    break
            if self.peek()[0] != ")":
                raise ShErr("syntax", ")")
            self.i += 1
            return ("fn", key, args)
        if k == "(":
            self.i += 1
            a = self.cmp()
            if self.peek()[0] != ")":
                raise ShErr("syntax", ")")
            self.i += 1
            return a
        raise ShErr("syntax", "end" if k is None else str(v))


def sh_parse(text, resolve):
    """The tree of a formula (text without "="); resolve(token) -> reference node (raises ShErr)."""
    tree = _Parser(sh_tokens(text), resolve).parse()
    stack = [(tree, 1)]  # review 4: a deep tree would overflow the evaluation's stack; checked without recursion
    while stack:
        n, d = stack.pop()
        if d > SH_MAX_DEPTH:
            raise ShErr("syntax", "deep")
        if isinstance(n, tuple):
            stack.extend((a, d + 1) for a in n[1:] if isinstance(a, tuple))
            for a in n[1:]:
                if isinstance(a, list):
                    stack.extend((x, d + 1) for x in a if isinstance(x, tuple))
    return tree


# ---------------------------------------------------------------- plain values
def sh_parse_number(s):
    """1,5 / 1.5 / 1.234,50 / 1,234.50 / 12 € / 19% -> float, or None. A trailing % divides by 100."""
    t = (s or "").strip().replace(" ", "").replace(" ", "").replace(" ", "")
    pct = t.endswith("%")
    t = t.rstrip("%")
    for sym in ("€", "$", "£", "EUR", "USD", "CHF", "GBP"):
        t = t.replace(sym, "")
    if not re.fullmatch(r"[+-]?(\d[\d.,']*|[.,]\d+)", t or "x"):
        return None
    t = t.replace("'", "")
    if "." in t and "," in t:
        dec_ch = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("." if dec_ch == "," else ",", "").replace(",", ".")
    elif t.count(",") > 1:
        t = t.replace(",", "")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    else:
        t = t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    if not math.isfinite(v):
        return None
    return v / 100 if pct else v


def sh_parse_date(s):
    t = (s or "").strip()
    m = _DATE_DE.fullmatch(t)
    try:
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        m = _DATE_ISO.fullmatch(t[:10]) if len(t) in (10, 19, 20, 24, 25) else None
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return None


def sh_plain_value(raw, kind, options=None):
    """The value of a typed (non-formula) input in a column of that kind: float | str | date | None (empty)."""
    t = (raw or "").strip()
    if not t:
        return None
    if kind == "select":
        o = next((x for x in options or [] if x.get("id") == t), None)
        return o.get("label", "") if o else None
    if kind in ("number", "currency"):
        v = sh_parse_number(t)
        return t if v is None else v
    if kind == "percent":
        v = sh_parse_number(t.rstrip("%"))
        return t if v is None else v / 100
    if kind == "date":
        d = sh_parse_date(t)
        return t if d is None else d
    v = sh_parse_number(t)  # text: a number or a date still counts as one in formulas
    if v is not None and not t.endswith("%") and re.fullmatch(r"[+-]?[\d.,' ]+", t):
        return v
    d = sh_parse_date(t)
    return d if d is not None else raw


# ---------------------------------------------------------------- formats
def _lg(lg):
    return (lg or "de").split("-")[0].lower()


def sh_fmt_number(x, lg, decimals=None):
    """1234.5 -> "1.234,5" (de, es, it, nl) / "1,234.5" (en) / "1 234,5" (fr); decimals None = up to 4, trimmed."""
    if abs(x) >= 1e15:
        s = f"{x:.6g}"
        return s if _lg(lg) == "en" else s.replace(".", ",")
    if decimals is None:
        s = f"{x:,.4f}".rstrip("0").rstrip(".")
    else:
        s = f"{x:,.{decimals}f}"
    if s in ("-0", "-0.00", "-0.0"):
        s = s[1:]
    lang = _lg(lg)
    if lang == "en":
        return s
    th = " " if lang == "fr" else "."
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", th)


SH_CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}


def sh_fmt_currency(x, lg, currency="EUR"):
    sym = SH_CURRENCY_SYMBOLS.get((currency or "EUR").upper(), (currency or "EUR").upper())
    s = sh_fmt_number(abs(x), lg, 2)
    neg = "-" if x < 0 and round(abs(x), 2) else ""
    if _lg(lg) == "en":
        return f"{neg}{sym}{s}"
    return f"{neg}{s} {sym}"


def sh_fmt_date(d, lg):
    lang = _lg(lg)
    if lang == "en":
        return d.isoformat()
    if lang in ("fr", "es", "it"):
        return d.strftime("%d/%m/%Y")
    if lang == "nl":
        return d.strftime("%d-%m-%Y")
    return d.strftime("%d.%m.%Y")


def sh_fmt(v, kind, lg, currency="EUR", yes="Yes", no="No"):
    """The display text of a value in a column of that kind (text / select: numbers and dates in the plain format)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return yes if v else no
    if isinstance(v, date):
        return sh_fmt_date(v, lg)
    if isinstance(v, float):
        if kind == "currency":
            return sh_fmt_currency(v, lg, currency)
        if kind == "percent":
            return sh_fmt_number(round(v * 100, 2), lg) + ("%" if _lg(lg) == "en" else " %")
        return sh_fmt_number(v, lg)
    return str(v)


def sh_vtype(v):
    if v is None:
        return "empty"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, float):
        return "number"
    if isinstance(v, date):
        return "date"
    return "text"


def sh_json_value(v):
    """A value as JSON (a date as ISO text)."""
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v == int(v) and abs(v) < 2 ** 53:
        return int(v)
    return v


def sh_freeze_dump(v, display):
    return json.dumps({"t": sh_vtype(v), "v": sh_json_value(v), "d": display}, ensure_ascii=False)


def sh_freeze_load(s):
    """(value, display at freezing) of a frozen copy."""
    try:
        d = json.loads(s or "{}")
    except ValueError:
        return None, ""
    t, v = d.get("t"), d.get("v")
    if t == "number" and isinstance(v, (int, float)) and not isinstance(v, bool):
        v = float(v)
    elif t == "date":
        v = sh_parse_date(str(v)) if v else None
    elif t == "bool":
        v = bool(v)
    elif t == "text":
        v = str(v)
    else:
        v = None
    return v, str(d.get("d") or "")


# ---------------------------------------------------------------- evaluation
def _num(v):
    """A value as a number for arithmetic: empty = 0, WAHR = 1, numeric text counts; other text = type error."""
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, float):
        return v
    if isinstance(v, date):
        return float(v.toordinal())
    x = sh_parse_number(str(v))
    if x is None:
        raise ShErr("type")
    return x


def _date(v):
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        d = sh_parse_date(v)
        if d:
            return d
    raise ShErr("type")


def _fin(x):
    if not math.isfinite(x):
        raise ShErr("type")
    return x


def _text(v, lg):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "WAHR" if v and _lg(lg) == "de" else "TRUE" if v else "FALSCH" if _lg(lg) == "de" else "FALSE"
    if isinstance(v, float):
        s = (str(int(v)) if v == int(v) and abs(v) < 1e15 else repr(round(v, 10)))
        return s if _lg(lg) == "en" else s.replace(".", ",")
    if isinstance(v, date):
        return sh_fmt_date(v, lg)
    return str(v)


def _truthy(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, float):
        return v != 0
    if isinstance(v, date):
        return True
    t = str(v).strip().lower()
    if t in SH_BOOLS:
        return SH_BOOLS[t]
    x = sh_parse_number(t)
    if x is None:
        raise ShErr("type")
    return x != 0


def _cmp(op, a, b):
    if a is None and b is None:
        a = b = 0.0
    elif a is None:
        a = "" if isinstance(b, str) else (False if isinstance(b, bool) else 0.0 if not isinstance(b, date) else None)
    elif b is None:
        b = "" if isinstance(a, str) else (False if isinstance(a, bool) else 0.0 if not isinstance(a, date) else None)
    if isinstance(a, date) or isinstance(b, date):
        try:
            a, b = _date(a) if a is not None else date.min, _date(b) if b is not None else date.min
        except ShErr:
            return op == "<>"
    elif isinstance(a, str) and isinstance(b, str):
        a, b = a.casefold(), b.casefold()
    elif isinstance(a, str) or isinstance(b, str):
        xa = sh_parse_number(a) if isinstance(a, str) else _num(a)
        xb = sh_parse_number(b) if isinstance(b, str) else _num(b)
        if xa is None or xb is None:
            return op == "<>"
        a, b = xa, xb
    else:
        a, b = _num(a), _num(b)
    return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]


def _round(x, n):
    q = Decimal(1).scaleb(-n) if n >= 0 else Decimal(10) ** (-n)
    r = Decimal(repr(x)).quantize(q, rounding=ROUND_HALF_UP) if n >= 0 else (Decimal(repr(x)) / q).quantize(Decimal(1), rounding=ROUND_HALF_UP) * q
    return float(r)


class ShEval:
    """Evaluates one node tree. env: cell(id) -> value (raises ShErr), rng(id1, id2) -> [values], col(id) -> [values],
    var(type, id, field) -> value, here(field) -> value, today() -> date, lg = the viewer's language."""

    def __init__(self, env):
        self.env = env

    def run(self, node):
        v = self.ev(node)
        if isinstance(v, list):
            raise ShErr("type")  # a bare range / column is not a value
        if isinstance(v, float):
            _fin(v)
        return v

    def ev(self, n):
        k = n[0]
        if k in ("n", "s", "b"):
            return n[1]
        if k == "cell":
            return self.env.cell(n[1])
        if k == "range":
            return self.env.rng(n[1], n[2])
        if k == "col":
            return self.env.col(n[1])
        if k == "var":
            return self.env.var(n[1], n[2], n[3])
        if k == "here":
            return self.env.here(n[1])
        if k in ("xcell", "xrange"):  # 2.124.0 E (#2116): a cell / range of another sheet of the table
            fn = getattr(self.env, k, None)
            if fn is None:
                raise ShErr("ref")
            return fn(*n[1:])
        if k == "neg":
            return -_num(self.scalar(n[1]))
        if k == "pct":
            return _num(self.scalar(n[1])) / 100
        if k == "&":
            lg = self.env.lg
            a, b = _text(self.scalar(n[1]), lg), _text(self.scalar(n[2]), lg)
            if len(a) + len(b) > SH_RAW_MAX:  # review 1: A2=A1&A1, A3=A2&A2 ... would double without end
                raise ShErr("type", "long")
            spend = getattr(self.env, "spend", None)
            if spend:
                spend(len(a) + len(b))
            return a + b
        if k == "cmp":
            return _cmp(n[1], self.scalar(n[2]), self.scalar(n[3]))
        if k in "+-*/":
            a, b = self.scalar(n[1]), self.scalar(n[2])
            if k == "+":
                if isinstance(a, date) and not isinstance(b, date):
                    return a + timedelta(days=int(_num(b)))
                if isinstance(b, date) and not isinstance(a, date):
                    return b + timedelta(days=int(_num(a)))
                if isinstance(a, date) and isinstance(b, date):
                    raise ShErr("type")
                return _fin(_num(a) + _num(b))
            if k == "-":
                if isinstance(a, date) and isinstance(b, date):
                    return float((a - b).days)
                if isinstance(a, date):
                    return a - timedelta(days=int(_num(b)))
                if isinstance(b, date):
                    raise ShErr("type")
                return _fin(_num(a) - _num(b))
            if isinstance(a, date) or isinstance(b, date):
                raise ShErr("type")
            if k == "*":
                return _fin(_num(a) * _num(b))
            d = _num(b)
            if d == 0:
                raise ShErr("div0")
            return _fin(_num(a) / d)
        if k == "fn":
            return self.fn(n[1], n[2])
        raise ShErr("syntax")

    def scalar(self, n):
        if n is None:
            return None
        v = self.ev(n)
        if isinstance(v, list):
            raise ShErr("type")
        return v

    def flat(self, args):
        """The numbers of the arguments: ranges / columns give their numbers (text and empty cells are left out), a direct
        argument must be a number (numeric text counts)."""
        out = []
        for a in args:
            if a is None:
                continue
            v = self.ev(a)
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, float):
                        out.append(x)
                    elif isinstance(x, bool):
                        continue
            elif v is not None:
                out.append(_num(v) if not isinstance(v, date) else float(v.toordinal()))
        return out

    def fn(self, key, args):
        if key == "sum":
            return _fin(math.fsum(self.flat(args)))
        if key == "avg":
            xs = self.flat(args)
            if not xs:
                raise ShErr("div0")
            return _fin(math.fsum(xs) / len(xs))
        if key in ("min", "max"):
            xs = self.flat(args)
            return (min if key == "min" else max)(xs) if xs else 0.0
        if key == "count":
            return float(len(self.flat_count(args)))
        if key == "if":
            if not args or len(args) > 3:
                raise ShErr("syntax", "WENN")
            cond = _truthy(self.scalar(args[0]))
            if cond:
                return self.scalar(args[1]) if len(args) > 1 else True
            return self.scalar(args[2]) if len(args) > 2 else False
        if key == "round":
            if not args or len(args) > 2:
                raise ShErr("syntax", "RUNDEN")
            x = _num(self.scalar(args[0]))
            d = int(_num(self.scalar(args[1]))) if len(args) > 1 and args[1] is not None else 0
            if not -10 <= d <= 10:
                raise ShErr("type")
            return _round(x, d)
        if key == "today":
            if any(a is not None for a in args):
                raise ShErr("syntax", "HEUTE")
            return self.env.today()
        if key == "days":
            if len(args) != 2:
                raise ShErr("syntax", "TAGE")
            return float((_date(self.scalar(args[0])) - _date(self.scalar(args[1]))).days)
        from .shfuncs import shf_call  # 2.124.0 A (#2109): SUMMEWENN, SVERWEIS, text and date functions
        return shf_call(self, key, args)

    def flat_count(self, args):
        out = []
        for a in args:
            if a is None:
                continue
            v = self.ev(a)
            for x in (v if isinstance(v, list) else [v]):
                if isinstance(x, (float, date)) and not isinstance(x, bool):
                    out.append(x)
                elif isinstance(x, str) and not isinstance(v, list) and sh_parse_number(x) is not None:
                    out.append(x)
        return out


def sh_fn_key(name):
    """2.124.0 A (#2109): the key of a function name (any case): the classic ones above, then those of sheets/shfuncs.py."""
    low = (name or "").lower()
    key = SH_FUNCS.get(low)
    if key is None:
        from .shfuncs import SHF_NAMES
        key = SHF_NAMES.get(low)
    return key


def sh_today():
    from ..core.db import local_now
    return local_now().date()


def sh_col_letter(i):
    """0 -> A, 25 -> Z, 26 -> AA."""
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def sh_col_index(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def sh_slug(name):
    """The name of a project / list / client / column in a formula: lower case, Umlauts stay, spaces and other signs -> "_"."""
    s = re.sub(r"[^\w]+", "_", (name or "").strip().lower(), flags=re.U).strip("_")
    return re.sub(r"_+", "_", s)[:60]


def sh_name_ok(name):
    """A cell name: a letter first, then letters / digits / _, at most 40, never an address, function or reserved word."""
    return bool(re.fullmatch(r"[^\W\d]\w{0,39}", name or "")) and not _A1.fullmatch(name) and name.lower() not in SH_RESERVED


def sh_is_iso_dt(s):
    try:
        datetime.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False
