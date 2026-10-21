"""2.43.0 (#1328): formula fields -- a small calculator over the number fields of a list, computed on the server.

Field names ({Field name} or a single word) are stored with field ids ({#12}), shown with the current names, so renaming a field
keeps every formula working. Empty fields count as 0 (or make the result empty, the field's setting "empty": "blank").
2.156.0 B (#2070): the formula engine of tables (sheets/formula.py: tokenizer, parser, evaluation) does the work, so lists get
comparisons (= <> < > <= >=), WENN/IF, SUMME/SUM, RUNDEN/ROUND, MIN, MAX, MITTELWERT/AVERAGE and ANZAHL/COUNT with German and
English names, ";" or "," between arguments, like in tables. Every other part of the typed formula is stored as typed. A mistake
in the formula is refused when it is saved (with the position); a calculation that fails for one task (division by 0, a value
that is no number) gives a short error value "#div0" / "#type" -- or an empty result while none of the fields it reads has a
value yet. Never eval."""
import json
import math

from ..core.i18n import tr
from ..personal.timetrack import BadInput
from ..sheets.formula import SH_BOOLS, ShErr, ShEval, _Parser as _ShParser, sh_fn_key, sh_parse, sh_tokens

FX_REF_TYPES = ("number", "formula", "checkbox", "currency", "rating")  # what a formula may read; 2.156.0 B (#2069): + currency, rating
FX_MAX_LEN = 500
FX_FUNCS = ("sum", "avg", "min", "max", "count", "if", "round")  # 2.156.0 B (#2070): the functions of tables a list formula may use
FX_ERRORS = ("div0", "type")  # 2.156.0 B (#2070): error values of a result ("#div0"), shown as a short text by the client


class FxError(BadInput):
    pass


def _err(msg, pos):
    return FxError(tr("Formula: {0} (at character {1})", msg, pos + 1))


def _mask(s):
    """2.156.0 B (#2070): the formula with every {…} turned into a reference the tables' tokenizer reads: {#12} -> {c:12},
    {Name} -> {x:<n>} (n = index into names). Returns (masked text, names, map of each masked character to the typed one)."""
    out, pm, names, i, n, quote = [], [], [], 0, len(s), False
    while i < n:
        ch = s[i]
        if ch == '"':
            quote = not quote
        if ch == "{" and not quote:
            j = s.find("}", i + 1)
            if j < 0:
                raise _err(tr("a “}” is missing"), i)
            name = s[i + 1:j].strip()
            if not name:
                raise _err(tr("a field name is missing"), i)
            if name.startswith("#") and name[1:].isdigit() and len(name) < 19:
                rep = "{c:%d}" % int(name[1:])
            else:
                rep = "{x:%d}" % len(names)
                names.append(name)
            out.append(rep)
            pm.extend([i] * len(rep))
            i = j + 1
            continue
        out.append(ch)
        pm.append(i)
        i += 1
    return "".join(out), names, pm


def _is_ref(tok):
    k, v = tok[0], tok[1]
    return k in ("idref", "a1", "xref") or (k == "ident" and str(v).lower() not in SH_BOOLS)


def _ref_key(tok, masked, names):
    """The name of a reference token ("#12" for a stored id), None when it is no field reference."""
    k, v, a, b = tok
    if k == "idref":
        if v[2]:
            return None
        if v[0] == "c":
            return "#%d" % v[1]
        return names[v[1]] if v[0] == "x" and v[1] < len(names) else None
    if k in ("ident", "a1"):
        return masked[a:b]
    return None


def _parse(text, lookup):
    """(tree, tokens, masked) of a formula; lookup(name, position) -> field id (raises BadInput). Raises FxError with the
    position: a sign that is not allowed, an unknown function, brackets, the end."""
    masked, names, pm = _mask(text)

    def pos(k):
        return pm[k] if 0 <= k < len(pm) else len(text)
    try:
        toks = sh_tokens(masked)
    except ShErr as e:
        d = '"' if e.detail == "quote" else (e.detail or "")[:12]
        k = masked.find(d) if d else -1
        raise _err(tr("“{0}” is not allowed", d), pos(k) if k >= 0 else 0) from None
    for k, v, a, _b in toks:
        if k == "fn" and sh_fn_key(v) not in FX_FUNCS:
            raise _err(tr("unknown function “{0}”", v), pos(a))
        if k in (":", "xref"):
            raise _err(tr("“{0}” is not allowed", masked[a:_b][:12]), pos(a))

    def res(tok):
        key = _ref_key(tok, masked, names)
        if key is None:
            raise _err(tr("“{0}” is not allowed", masked[tok[2]:tok[3]][:12]), pos(tok[2]))
        return ("cell", lookup(key, pos(tok[2])))
    if not toks:
        raise _err(tr("the formula is empty"), 0)
    try:
        tree = sh_parse(masked, res)
    except ShErr as e:
        if e.kind != "syntax" or e.detail == "deep":
            raise BadInput(tr("Invalid value: {0}", "formula")) from None
        p = _ShParser(toks, res)  # again, to know where it stopped
        try:
            p.parse()
        except ShErr:
            pass
        if e.detail == ")":
            raise _err(tr("{0} expected", "“)”"), pos(toks[p.i][2] if p.i < len(toks) else len(masked))) from None
        if p.i >= len(toks):
            raise _err(tr("the formula ends too early"), len(text)) from None
        t = toks[p.i]
        raise _err(tr("“{0}” is not expected here", masked[t[2]:t[3]][:20]), pos(t[2])) from None
    except RecursionError:  # review S1: "-(-(-(..." nested deeper than Python's stack -> 400, not 500
        raise BadInput(tr("Invalid value: {0}", "formula")) from None
    for k, v, a, _b in toks:  # 2.43.0 (#1328): round(value, digits) with digits 0 to 6 when typed as a number
        if k == "fn" and sh_fn_key(v) == "round":
            _fx_round_digits(tree, pos(a))
            break
    return tree, toks, masked, names


def _fx_round_digits(node, at):
    if isinstance(node, tuple):
        if node[0] == "fn" and node[1] == "round" and len(node[2]) > 1 and node[2][1] and node[2][1][0] == "n":
            d = node[2][1][1]
            if d != int(d) or not 0 <= d <= 6:
                raise _err(tr("round(value, digits): digits 0 to 6"), at)
        for a in node[1:]:
            for x in (a if isinstance(a, list) else [a]):
                _fx_round_digits(x, at)


def fmt_fx(x):
    s = ("%.6f" % x).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def fx_refs(node, acc=None):
    """The field ids a tree reads."""
    acc = set() if acc is None else acc
    if isinstance(node, tuple):
        if node[0] == "cell":
            acc.add(node[1])
            return acc
        for a in node[1:]:
            for x in (a if isinstance(a, list) else [a]):
                fx_refs(x, acc)
    return acc


_CACHE = {}


def _stored_lookup(v, p):
    if not v.startswith("#") or not v[1:].isdigit():
        raise _err(tr("unknown field “{0}”", v), p)
    return int(v[1:])


def fx_tree(expr):
    """Tree of a stored formula ({#id} refs); None when it cannot be read (a deleted field...)."""
    if expr in _CACHE:
        return _CACHE[expr]
    try:
        t = _parse(expr, _stored_lookup)[0]
    except (BadInput, RecursionError):  # 2.43.0 (#1328): review S1, deep nesting
        t = None
    if len(_CACHE) > 2000:
        _CACHE.clear()
    _CACHE[expr] = t
    return t


def _rebuild(toks, masked, names, ref_text):
    """The formula text with every field reference replaced by ref_text(key); everything else as typed."""
    out, last = [], 0
    for tok in toks:
        if not _is_ref(tok):
            continue
        key = _ref_key(tok, masked, names)
        out.append(masked[last:tok[2]])
        out.append(ref_text(key))
        last = tok[3]
    out.append(masked[last:])
    return "".join(out).strip()


def fx_compile(text, fields, self_id=None):
    """The formula as typed (names) -> (stored expr with {#id}, refs). fields = rows of the list's fields. Raises BadInput
    with the position or the field name: unknown name, a field that is not a number, the formula itself."""
    text = str(text or "").strip()
    if len(text) > FX_MAX_LEN:
        raise BadInput(tr("Formula: at most {0} characters", FX_MAX_LEN))
    by_name = {}
    for f in fields:
        by_name.setdefault(f["name"].strip().casefold(), f)

    def find(v, p):
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
    tree, toks, masked, names = _parse(text, find)
    return _rebuild(toks, masked, names, lambda k: "{#%d}" % find(k, 0)), fx_refs(tree)


def fx_display(expr, fields):
    """Stored formula -> text with the current field names (shown in the field's dialog)."""
    if fx_tree(expr or "") is None:
        return ""
    nm = {f["id"]: f["name"] for f in fields}
    masked, names, _ = _mask(expr)
    toks = sh_tokens(masked)

    def name(k):
        n = nm.get(int(k[1:])) if k and k.startswith("#") and k[1:].isdigit() else None
        return "{%s}" % n if n is not None else "{?}"
    return _rebuild(toks, masked, names, name)


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


class _FxEnv:
    """2.156.0 B (#2070): what the tables' evaluation asks for: only cells (= fields of the task); no ranges, columns, variables."""
    lg = "en"

    def __init__(self, get):
        self.cell = get

    def _none(self, *a):
        raise ShErr("ref")
    rng = col = var = here = today = _none


def fx_values(fields, vals):
    """{field id (int): stored text} of one task -> {formula field id: text or None}. fields = rows of the task's list.
    2.156.0 B (#2070): a failed calculation gives "#div0" / "#type" (None while no field it reads has a value)."""
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
        miss, seen = [], []

        def get(r):
            if typ.get(r) == "formula":
                v = calc(r)
                if v is not None and v.startswith("#"):
                    seen.append(r)
                    raise ShErr(v[1:] if v[1:] in FX_ERRORS else "type")
                x = None if v is None else float(v)
            elif typ.get(r) == "checkbox":  # unticked = 0, never empty
                if vals.get(r) != "1":
                    return 0.0
                x = 1.0
            elif typ.get(r) in ("number", "currency", "rating"):
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
            seen.append(r)
            return x
        r, bad = None, None
        if t is not None:
            try:
                r = ShEval(_FxEnv(get)).run(t)
            except ShErr as e:
                bad = e.kind if e.kind in FX_ERRORS else "type"
            except (RecursionError, ValueError, ArithmeticError):  # review: + decimal.InvalidOperation (ROUND of a huge value)
                bad = "type"
        if isinstance(r, bool):
            r = 1.0 if r else 0.0
        if r is not None and not bad and (not isinstance(r, float) or not math.isfinite(r) or abs(r) >= 1e15):
            bad = "type"  # a text or date as the result, or too big
        if miss or t is None:
            res = None
        elif bad:
            res = "#" + bad if seen else None
        else:
            res = None if r is None else fmt_fx(r)
        out[fid] = res
        busy.discard(fid)
        return res
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
