"""2.43.0 (#1328): formula fields -- a small calculator over the number fields of a list, computed on the server.

Syntax: + - * /, brackets, numbers (decimal point), field names ({Field name} or a single word) and round(x, n) as the only
function. Stored with field ids ({#12}), shown with the current names, so renaming a field keeps every formula working.
Never eval: a tokenizer and a recursive descent parser build a tiny tree that is evaluated per task. Division by zero
gives an empty value; empty fields count as 0 (or make the result empty, the field's setting "empty": "blank")."""
import json
import math
import re

from ..core.i18n import tr
from ..core.errors import BadInput

FX_REF_TYPES = ("number", "formula", "checkbox")   # what a formula may read
FX_MAX_LEN = 500
_WORD = re.compile(r"[^\W\d]\w*")
_NUM = re.compile(r"\d+(\.\d+)?|\.\d+")


class FxError(BadInput):
    pass


def _err(msg, pos):
    return FxError(tr("Formula: {0} (at character {1})", msg, pos + 1))


def fx_tokens(s):
    """[(kind, value, pos)]: kind num | ref (name or #id) | op | ( | ) | , | fn."""
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "+-*/":
            out.append(("op", ch, i))
            i += 1
            continue
        if ch in "(),":
            out.append((ch, ch, i))
            i += 1
            continue
        if ch == "{":
            j = s.find("}", i + 1)
            if j < 0:
                raise _err(tr("a “}” is missing"), i)
            name = s[i + 1:j].strip()
            if not name:
                raise _err(tr("a field name is missing"), i)
            out.append(("ref", name, i))
            i = j + 1
            continue
        m = _NUM.match(s, i)
        if m:
            if not math.isfinite(float(m.group())):  # review S1: "999...9" is inf
                raise _err(tr("Invalid value: {0}", m.group()[:20]), i)
            out.append(("num", float(m.group()), i))
            i = m.end()
            continue
        m = _WORD.match(s, i)
        if m:
            w = m.group()
            out.append(("fn" if w.lower() == "round" else "ref", w, i))
            i = m.end()
            continue
        raise _err(tr("“{0}” is not allowed", ch), i)
    return out


class _Parser:
    """Recursive descent: expr = term (+|- term)*, term = factor (*|/ factor)*, factor = -factor | num | ref |
    round(expr[, num]) | (expr). Nodes: ("n", x) ("r", key) ("neg", a) ("+"/"-"/"*"/"/", a, b) ("round", a, digits)."""

    def __init__(self, toks, resolve, end):
        self.t, self.i, self.resolve, self.end = toks, 0, resolve, end

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None, self.end)

    def take(self, kind, what):
        k, v, p = self.peek()
        if k != kind:
            raise _err(tr("{0} expected", what), p)
        self.i += 1
        return v

    def parse(self):
        if not self.t:
            raise _err(tr("the formula is empty"), 0)
        node = self.expr()
        k, v, p = self.peek()
        if k is not None:
            raise _err(tr("“{0}” is not expected here", v if k != "num" else fmt_fx(v)), p)
        return node

    def expr(self):
        a = self.term()
        while self.peek()[0] == "op" and self.peek()[1] in "+-":
            op = self.t[self.i][1]
            self.i += 1
            a = (op, a, self.term())
        return a

    def term(self):
        a = self.factor()
        while self.peek()[0] == "op" and self.peek()[1] in "*/":
            op = self.t[self.i][1]
            self.i += 1
            a = (op, a, self.factor())
        return a

    def factor(self):
        k, v, p = self.peek()
        if k == "op" and v in "+-":
            self.i += 1
            f = self.factor()
            return ("neg", f) if v == "-" else f
        if k == "num":
            self.i += 1
            return ("n", v)
        if k == "ref":
            self.i += 1
            return ("r", self.resolve(v, p))
        if k == "fn":
            self.i += 1
            self.take("(", "“(”")
            a = self.expr()
            digits = 0
            if self.peek()[0] == ",":
                self.i += 1
                k2, v2, p2 = self.peek()
                if k2 != "num" or v2 != int(v2) or v2 > 6:
                    raise _err(tr("round(value, digits): digits 0 to 6"), p2)
                self.i += 1
                digits = int(v2)
            self.take(")", "“)”")
            return ("round", a, digits)
        if k == "(":
            self.i += 1
            a = self.expr()
            self.take(")", "“)”")
            return a
        if k is None:
            raise _err(tr("the formula ends too early"), p)
        raise _err(tr("“{0}” is not expected here", v), p)


def fmt_fx(x):
    s = ("%.6f" % x).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def fx_refs(node, acc=None):
    acc = set() if acc is None else acc
    if node[0] == "r":
        acc.add(node[1])
    elif node[0] in ("neg", "round"):
        fx_refs(node[1], acc)
    elif node[0] in "+-*/":
        fx_refs(node[1], acc)
        fx_refs(node[2], acc)
    return acc


_CACHE = {}


def fx_tree(expr):
    """Tree of a stored formula ({#id} refs); None when it cannot be read (a deleted field...)."""
    if expr in _CACHE:
        return _CACHE[expr]

    def res(v, p):
        if not v.startswith("#") or not v[1:].isdigit():
            raise _err(tr("unknown field “{0}”", v), p)
        return int(v[1:])
    try:
        t = _Parser(fx_tokens(expr), res, len(expr)).parse()
    except (BadInput, RecursionError):  # 2.43.0 (#1328): review S1, deep nesting
        t = None
    if len(_CACHE) > 2000:
        _CACHE.clear()
    _CACHE[expr] = t
    return t


def fx_compile(text, fields, self_id=None):
    """The formula as typed (names) -> (stored expr with {#id}, refs). fields = rows of the list's fields. Raises BadInput
    with the position or the field name: unknown name, a field that is not a number, the formula itself."""
    text = str(text or "").strip()
    if len(text) > FX_MAX_LEN:
        raise BadInput(tr("Formula: at most {0} characters", FX_MAX_LEN))
    by_name = {}
    for f in fields:
        by_name.setdefault(f["name"].strip().casefold(), f)

    def res(v, p):
        f = None
        if v.startswith("#") and v[1:].isdigit():
            f = next((x for x in fields if x["id"] == int(v[1:])), None)
        f = f or by_name.get(v.strip().casefold())
        if not f:
            raise _err(tr("unknown field “{0}”", v), p)
        if self_id is not None and f["id"] == self_id:
            raise BadInput(tr("Formula: the field cannot use itself"))
        if f["type"] not in FX_REF_TYPES:
            raise BadInput(tr("Formula: “{0}” is not a number field", f["name"]))
        return f["id"]
    try:
        tree = _Parser(fx_tokens(text), res, len(text)).parse()
        return fx_render(tree), fx_refs(tree)
    except RecursionError:  # review S1: "-(-(-(..." nested deeper than Python's stack -> 400, not 500
        raise BadInput(tr("Invalid value: {0}", "formula")) from None


_PREC = {"+": 1, "-": 1, "*": 2, "/": 2}


def fx_render(node, names=None, prec=0):
    """The tree as text: {#id} (names None) or {Name}."""
    k = node[0]
    if k == "n":
        return fmt_fx(node[1])
    if k == "r":
        if names is None:
            return "{#%d}" % node[1]
        nm = names.get(node[1])
        return "{%s}" % nm if nm is not None else "{?}"
    if k == "neg":
        return "-" + fx_render(node[1], names, 3)
    if k == "round":
        return "round(%s%s)" % (fx_render(node[1], names), ", %d" % node[2] if node[2] else "")
    p = _PREC[k]
    s = "%s %s %s" % (fx_render(node[1], names, p), k, fx_render(node[2], names, p + (1 if k in "-/" else 0)))
    return "(" + s + ")" if p < prec else s


def fx_display(expr, fields):
    """Stored formula -> text with the current field names (shown in the field's dialog)."""
    t = fx_tree(expr or "")
    if t is None:
        return ""
    return fx_render(t, {f["id"]: f["name"] for f in fields})


def fx_check_cycles(fields, fid, refs):
    """A formula field fid using refs must not reach itself through other formula fields."""
    deps = {}
    for f in fields:
        if f["type"] == "formula" and f["id"] != fid:
            t = fx_tree(json.loads(f["options"] or "{}").get("expr") or "")
            deps[f["id"]] = fx_refs(t) if t else set()
    deps[fid] = set(refs)
    names = {f["id"]: f["name"] for f in fields}
    seen, stack = set(), list(refs)
    while stack:
        x = stack.pop()
        if x == fid:
            raise BadInput(tr("Formula: circular reference via “{0}”", names.get(next(iter(refs & deps.keys()), fid), "?")))
        if x in seen:
            continue
        seen.add(x)
        stack.extend(deps.get(x, ()))


def _eval(node, get):
    k = node[0]
    if k == "n":
        return node[1]
    if k == "r":
        return get(node[1])
    if k == "neg":
        a = _eval(node[1], get)
        return None if a is None else -a
    if k == "round":
        a = _eval(node[1], get)
        return None if a is None else round(a, node[2])
    a, b = _eval(node[1], get), _eval(node[2], get)
    if a is None or b is None:
        return None
    if k == "+":
        return a + b
    if k == "-":
        return a - b
    if k == "*":
        return a * b
    if b == 0:
        return None
    return a / b


def fx_values(fields, vals):
    """{field id (int): stored text} of one task -> {formula field id: text or None}. fields = rows of the task's list."""
    fx = {f["id"]: f for f in fields if f["type"] == "formula"}
    if not fx:
        return {}
    typ = {f["id"]: f["type"] for f in fields}
    out, busy = {}, set()

    def calc(fid):
        if fid in out:
            return out[fid]
        if fid in busy:  # a cycle left in old data: empty
            return None
        busy.add(fid)
        o = json.loads(fx[fid]["options"] or "{}")
        t = fx_tree(o.get("expr") or "")
        blank = o.get("empty") == "blank"
        miss = []

        def get(r):
            if typ.get(r) == "formula":
                v = calc(r)
                x = None if v is None else float(v)
            elif typ.get(r) == "checkbox":
                x = 1.0 if vals.get(r) == "1" else 0.0
            elif typ.get(r) == "number":
                try:
                    x = float(vals[r]) if vals.get(r) not in (None, "") else None
                except ValueError:
                    x = None
            else:  # deleted / changed field: no result
                miss.append(r)
                return None
            if x is None:
                if blank:
                    miss.append(r)
                    return None
                return 0.0
            return x
        r = None
        if t is not None:
            try:
                r = _eval(t, get)
            except (OverflowError, ValueError):
                r = None
        if miss or r is None or not math.isfinite(r) or abs(r) >= 1e15:
            r = None
        out[fid] = None if r is None else fmt_fx(r)
        busy.discard(fid)
        return out[fid]
    for fid in fx:
        calc(fid)
    return out


def fx_fill(c, fvs, lids):
    """Adds the computed formula values to {task id: {"field id": text}} (task -> its list id in lids). One query for the
    formula lists; tasks of lists without formula fields stay as they are."""
    if not lids:
        return fvs
    want = sorted(set(lids.values()))
    rows = c.execute(f"SELECT * FROM list_fields WHERE list_id IN ({','.join('?' * len(want))}) ORDER BY sort, id", want).fetchall()
    per = {}
    for r in rows:
        per.setdefault(r["list_id"], []).append(r)
    per = {k: v for k, v in per.items() if any(f["type"] == "formula" for f in v)}
    if not per:
        return fvs
    for tid, lid in lids.items():
        fs = per.get(lid)
        if not fs:
            continue
        have = fvs.get(tid) or {}
        vals = {int(k): v for k, v in have.items()}
        res = fx_values(fs, vals)
        cur = dict(have)
        for fid, v in res.items():
            if v is None:
                cur.pop(str(fid), None)
            else:
                cur[str(fid)] = v
        if cur or tid in fvs:
            fvs[tid] = cur
    return fvs
