"""2.263.0 (#2976): ONE reader for numbers typed by people - the same rules as parseNum in static/js/core.js.

"1.234,50" / "1,234.50": the last sign is the decimal one; with a known decimal sign (the writer's language) it must be
that one, else the input is no number (wrong order is never cut silently). A sign used once is a thousands separator only
when it is not the decimal sign, 1-3 digits stand before it (not a lone 0) and exactly three after it ("1.500" in German,
"1,500" in English); else it is the decimal sign ("12,5" in English = 12.5). frac=True (rate, factor with up to four
decimals): a sign used once is always the decimal one. dec=None (neutral, stored texts of unknown writers): a sign used once
is the decimal one, as the readers did before.
"""
import re

try:
    from .i18n import lang
except ImportError:  # loaded on its own (tests/p2263_formats_api_test.py)
    lang = None

_WS = re.compile(r"[\s  ']")
_SHAPE = re.compile(r"[+-]?(\d[\d.,]*|[.,]\d+)")


def dec_char(lg):
    """The decimal sign of an app language: a point in English, a comma in every other one (de, fr, es, it, nl)."""
    return "." if (lg or "en").split("-")[0].lower() == "en" else ","


def user_dec():
    """The decimal sign of the current user's language (request or watchdog: i18n.lang)."""
    return dec_char(lang() if lang else "en")


def num_text(s, dec=None, frac=False):
    """A typed number -> its plain text "-1234.5" (point, no groups) or None when it is no number."""
    t = _WS.sub("", str(s if s is not None else "").strip())
    if not _SHAPE.fullmatch(t or "x"):
        return None
    sign = t[0] if t[0] in "+-" else ""
    t = t.lstrip("+-")
    d = dec
    if d is None:  # neutral: the later of two signs, a sign used once, else (used several times) the other one
        if "." in t and "," in t:
            d = "," if t.rfind(",") > t.rfind(".") else "."
        else:
            one = "," if "," in t else "."
            d = one if t.count(one) <= 1 else ("." if one == "," else ",")
    g = "." if d == "," else ","
    groups = re.compile(r"\d{1,3}(" + re.escape(g) + r"\d{3})+")
    nd, ng = t.count(d), t.count(g)
    if nd > 1:
        return None
    if nd and ng:
        a, b = t.split(d)
        if not groups.fullmatch(a) or g in b:
            return None
        t = a.replace(g, "") + "." + b
    elif nd:
        t = t.replace(d, ".")
    elif ng > 1:
        if not groups.fullmatch(t):
            return None
        t = t.replace(g, "")
    elif ng:
        t = t.replace(g, "") if dec is not None and not frac and groups.fullmatch(t) and not re.match(r"0\D", t) else t.replace(g, ".")
    if t.startswith("."):
        t = "0" + t
    if t.endswith("."):
        t = t[:-1]
    return sign.replace("+", "") + t


def parse_num(s, dec=None, frac=False):
    """A typed number -> float or None (see num_text); numbers (not bool) pass as they are."""
    if isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = num_text(s, dec, frac)
    try:
        return float(t) if t is not None else None
    except ValueError:
        return None


def server_num(s, frac=False):
    """A number the server gets as text -> float or None. A point alone is always the decimal sign: the app sends plain
    texts ("1234.5", the stored values of fields, rules, templates, undo), so they never change with the language. A comma
    alone is read in the current user's language ("1,500" in English = 1500, "1,5" in German = 1.5), both signs by their
    position ("1.234,50" / "1,234.50")."""
    if isinstance(s, (bool, int, float)) or s is None:
        return parse_num(s)
    t = str(s)
    if "," not in t:
        return parse_num(t, ".", True)
    return parse_num(t, None if "." in t else user_dec(), frac)


def user_num(s, frac=False):
    """server_num that raises ValueError when it is no number."""
    x = server_num(s, frac)
    if x is None:
        raise ValueError(s)
    return x
