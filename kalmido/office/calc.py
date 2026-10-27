"""2.36.1 (#1021): the quotation calculator of Office & Finance -- a pure function without database or request context.

office_calc(doc, items, pack) -> dict reproduces the rules of the spreadsheet template the module replaces:
 - a position is qty x rate; rates are kept in the organisation's currency (EUR) and converted into the document's
   currency with doc["fx_rate"] when the document is in USD (2.354.0 A (#2831): the exact rate, the position is
   money(qty x rate x fx); was the converted rate rounded to 2 places first, like the template)
   2.189.0 (#2475): "the organisation's currency" is doc["home"] (the office's home currency, missing = EUR); every other
   currency of homecur.HC_CODES is converted with its rate (units per one unit of the home currency)
 - "Producing": the sum of the quantities of the positions flagged producing, divided by doc["prod_quotient"], rounded to
   half days the way the template does (ROUND(x / 5, 1) * 5), times doc["producing_rate"]; only when > 0.
   2.113.1 (#2251): doc["producing_mode"] "amount" = the option "share by amount" an industry pack offers: the amount of
   the flagged positions (net, qty x rate, before discount, without raw data) / doc["producing_rate"] x doc["prod_quotient"]
   (a factor then), rounded to half days, times the rate; amount and rate in the document's currency; title from
   doc["share_label"] {de, en}. None = the calculation by quantities above (every older document keeps it)
 - 2.113.1 (#2252): two surcharges after the positions, before discount / raw data, standard tax, each on when its
   percentage is set: handling costs = doc["handling_pct"] % of the positions flagged in_handling; markup =
   doc["markup_pct"] % of the positions flagged in_markup (+ the handling costs with doc["markup_stacked"]); titles from
   doc["handling_label"] / doc["markup_label"] ({de, en} or the document's own text)
 - raw data: the sum of the totals of the positions flagged raw_fee times doc["raw_factor"]; raw_mode "optional" shows
   the line without counting it (net_incl_raw next to net), "included" counts it (net_excl_raw next to net), "none" omits it
 - discount: doc["discount_pct"] on the positions flagged discountable, one negative line
 - tax per position through the country pack (standard / reduced / exempt); vat_mode "novat" = no tax at all
Money is Decimal, rounded half up to 2 places at every step the template rounds; the result holds floats (JSON).
"""
import os
import re
import json
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
try:  # 2.263.0 (#2976): the one reader of typed numbers; calc.py loaded on its own (tests/office_calc_test.py) reads a comma as decimal
    from ..core.numtext import num_text, user_dec
except ImportError:
    num_text = user_dec = None

try:
    from ..core.i18n import LANGS, N_, tr
except ImportError:  # 2.185.0 C (#2520): loaded as a single file (tests/office_calc_test.py, no package): the same translation files
    def _calc_langs():
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "static", "i18n")
        out = {"en": {}}
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as fh:
                    out[fn[:-5]] = json.load(fh) if fn.endswith(".json") else {}
            except (OSError, ValueError):
                pass
        return out
    LANGS = _calc_langs()

    def N_(s):
        return s

    def tr(key, *a, lg=None):
        v = LANGS.get(lg or "en", {}).get(key)
        s = v if isinstance(v, str) else key[:key.find("|")] if key.find("|") > 0 else key
        return s.format(*a) if a else s

Q2 = Decimal("0.01")
TAX_KEYS = ("standard", "reduced", "exempt")
RAW_MODES = ("optional", "included", "none")

# the words of the document itself (its language, not the signed-in person's): the country pack may override them
# (pack["labels"][lang][key]); these are the defaults so the calculator works without a pack
# 2.185.0 C (#2520): English keys through tr() in the document's language (was a de / en table; the words stay the same)
LABELS = {
    "producing": N_("Producing|calc"), "producing_detail": N_("{days} {day_word} = {qty} {prod_word} / {quot}, rounded to half days|calc"),  # 2.114.4 A (#2276): singular for 1
    "raw_optional": N_("Optional: Delivery of raw data|calc"), "raw_included": N_("Delivery of raw data|calc"),
    "share_detail": N_("{amount} / {rate} x {factor} = {days} days, rounded to half days|calc"),  # 2.113.1 (#2251)
    "handling": N_("Handling costs|calc"), "markup": N_("Markup|calc"), "surcharge_detail": N_("{pct} % on the marked positions|calc"),  # 2.113.1 (#2252)
    "surcharge_detail_stacked": N_("{pct} % on the marked positions and the handling costs|calc"),
    "raw_detail": N_("{pct} % of the positions with raw data|calc"), "discount": N_("Discount|calc"),
    "discount_detail": N_("{pct} % on the marked positions|calc"),
    "net": N_("Net Total|calc"), "net_incl_raw": N_("Net total with option raw data|calc"), "net_excl_raw": N_("excluding raw data|calc"),  # 2.114.4 A (#2275)
    "gross": N_("Gross Total|calc"),
    "tax_standard": N_("VAT {pct} %|calc"), "tax_reduced": N_("VAT {pct} %|calc"), "tax_exempt": N_("tax exempt|calc"),
    "vat_note": N_("All prices plus 7 % or 19 % VAT.|calc"), "novat_note": N_("Not taxable domestically / reverse charge.|calc"),
    "fx_note": N_("Exchange rate €1: ${rate}|calc"),
    "fx_note_any": N_("Exchange rate 1 {home} = {rate} {cur}|calc"),  # 2.189.0 (#2475): other pairs than EUR / USD
    "unit_day": N_("days|calc"), "unit_hour": N_("h|calc"), "unit_piece": N_("pcs|calc"), "unit_minute": N_("min|calc"), "unit_flat": N_("flat|calc"),
}
CALC_PROD_WORD = (N_("production day|calc"), N_("production days|calc"))  # 2.185.0 C (#2520)
CALC_OR = {"de": " bzw. ", "en": " or ", "fr": " ou ", "nl": " of ", "es": " o ", "it": " o "}  # 2.185.0 C (#2520): "7 % bzw. 19 %"


def calc_lang(v):
    """2.185.0 C (#2520): a document's language: en / de as before, any other app language (nl, fr, es, it), else German."""
    s = str(v or "de").strip().lower()
    return "en" if s.startswith("en") else s if s in LANGS else "de"


DEFAULT_TAX = {"standard": 19, "reduced": 7, "exempt": 0}
# 2.189.0 (#2475): currency signs like homecur.HC_SYMBOLS (this module stays free of package imports)
CALC_SIGNS = {"EUR": "€", "USD": "$", "GBP": "£"}
# 2.296.0 B (#3175): the number format of a document by its language: (thousands, decimal, sign before the amount);
# fr groups with a no-break space ("1 234,50 €"), nl writes "€ 1.234,50"; any other language like de
CALC_LOCALE = {"de": (".", ",", False), "en": (",", ".", True), "fr": ("\u00a0", ",", False), "es": (".", ",", False),
               "it": (".", ",", False), "nl": (".", ",", True)}


def calc_code(v, home="EUR"):
    """A currency code ("€" / "$" / "£" / "gbp" -> "GBP"); anything that is no three-letter code = home."""
    v = str(v or "").strip()
    v = {"€": "EUR", "$": "USD", "£": "GBP"}.get(v, v.upper())
    return v if len(v) == 3 and v.isalpha() and v.isascii() else home


def dec(v, default="0"):
    """A Decimal from a number or a text with comma or point ("1.234,56" / "1,234.56" / "4.5" / "4,5"); None / '' = default."""
    if v is None or v == "":
        v = default
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        return Decimal(int(v))
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip().replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:  # 2.263.0 (#2976): a comma alone in the user's language ("1,500" in English = 1500; stored values have none)
        s = (num_text(s, user_dec()) or "x") if num_text else s.replace(",", ".")
    elif s.count(".") > 1:  # 2.355.0 A (#2847): "1.234.567" = groups (was no Decimal -> silently the default); "1.2.3" no number
        s = (num_text(s) or "x") if num_text else s
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal(default)


def money(d):
    return d.quantize(Q2, rounding=ROUND_HALF_UP)


def half_days(x):
    """The template's ROUND(x / 5, 1) * 5: multiples of 0.5, half up (4.667 -> 4.5, 4.75 -> 5.0, 0.2 -> 0, 0.25 -> 0.5)."""
    return ((dec(x) / 5).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) * 5).normalize() + Decimal(0)


def pack_tax(pack, key):
    """The percentage of a tax key from the pack (tax: {standard: 19} or {standard: {pct: 19}}), the DE defaults otherwise."""
    t = (pack or {}).get("tax") or {}
    v = t.get(key)
    if isinstance(v, dict):
        v = v.get("pct", v.get("rate"))
    if v is None:
        v = DEFAULT_TAX.get(key, 0)
    return dec(v)


ALIAS = {"net": "net_total", "net_incl_raw": "incl_raw", "net_excl_raw": "excl_raw", "gross": "gross_total", "novat_note": "vat_note_novat"}


def unit_text(pack, lang, unit, qty):
    """The unit word for a quantity: singular from labels[lang]["units_one"] for exactly 1 ("1 Tag"), else the plural label."""
    if unit not in ("day", "hour", "piece", "minute", "flat"):
        return unit
    if qty == 1:
        lg = calc_lang(lang)
        one = (((pack or {}).get("labels") or {}).get(lg) or {}).get("units_one")
        if isinstance(one, dict) and one.get(unit):
            return one[unit]
    return label(pack, lang, "unit_" + unit)


def label(pack, lang, key, **kw):
    """A word of the document in its language: pack["labels"][lang][key] (units: labels[lang]["units"][unit]), then
    pack["texts"][key][lang], then the built-in LABELS; {placeholders} filled from kw. 2.185.0 C (#2520): any app language; a
    word only a pack knows comes in English where the pack has none in that language."""
    lg = calc_lang(lang)
    pack = pack or {}
    pl = pack.get("labels") or {}
    pl = pl.get(lg) if isinstance(pl.get(lg), dict) else {}
    s = None
    for k in (key, ALIAS.get(key)):
        if k is None:
            continue
        if k.startswith("unit_") and isinstance(pl.get("units"), dict):
            s = pl["units"].get(k[5:])
        if s is None:
            s = pl.get(k)
        if s is None:
            pt = (pack.get("texts") or {}).get(k)
            s = pt.get(lg) if isinstance(pt, dict) else None
        if s is None and k == "vat_note_novat":
            pt = (pack.get("tax") or {}).get("exempt_note")
            s = pt.get(lg) if isinstance(pt, dict) else None
        if isinstance(s, str):
            break
        s = None
    if s is None and key not in LABELS and lg not in ("de", "en"):
        return label(pack, "en", key, **kw)
    if s is None:
        s = tr(LABELS[key], lg=lg) if key in LABELS else key
    if kw:
        try:
            s = re.sub(r"\{(\w+)\}", lambda m: str(kw[m.group(1)]) if m.group(1) in kw else m.group(0), s)  # 2.148.1 E (#2496): plain placeholders only
        except (KeyError, IndexError, ValueError):
            pass
    return s


def fmt_qty(d, lang="de"):
    """A quantity for a line: 3 -> "3", 4.5 -> "4,5" (de) / "4.5" (en)."""
    d = dec(d).normalize()
    s = str(int(d)) if d == d.to_integral() else format(d, "f")
    return s if (lang or "de").lower().startswith("en") else s.replace(".", ",")


def fmt_money(d, lang="de", currency="EUR", places=2):
    """1234.5 -> "1.234,50 €" (de) / "€1,234.50" (en) / USD "1.234,50 $" / "$1,234.50"; 2.296.0 B (#3175): by CALC_LOCALE
    ("1 234,50 €" fr, "€ 1.234,50" nl). 2.354.0 A (#2831): places 3 / 4 for a unit price (fmt_rate)."""
    d = money(dec(d)) if places == 2 else dec(d).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    neg = d < 0
    whole, frac = f"{abs(d):.{places}f}".split(".")
    lg = str(lang or "de").lower()
    tho, dp, before = CALC_LOCALE.get("en" if lg.startswith("en") else lg.split("-")[0], CALC_LOCALE["de"])
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    cur = calc_code(currency)
    sym = CALC_SIGNS.get(cur, cur)  # 2.189.0 (#2475): €, $, £, else the code ("CHF 1,234.50")
    s = tho.join(groups) + dp + frac
    if before:
        return ("-" if neg else "") + sym + ("" if len(sym) == 1 and dp == "." else " ") + s
    return ("-" if neg else "") + s + " " + sym


def rate_places(d):
    """2.354.0 A (#2831): the places a unit price is shown with: 2, or 3 / 4 when it has them (0.125 -> 3)."""
    d = dec(d).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return 2 if d == money(d) else max(2, min(4, -d.normalize().as_tuple().exponent))


def fmt_rate(d, lang="de", currency="EUR"):
    """2.354.0 A (#2831): a unit price as money text with up to 4 places ("0,125 €"); 2 places as fmt_money otherwise."""
    return fmt_money(d, lang, currency, rate_places(d))


def calc_cur(doc):
    """2.189.0 (#2475): (home, currency, fx, foreign) of a calculator doc: doc["home"] (missing = EUR as before), the
    document's currency (unknown = home), its rate (1 in the home currency; USD in a EUR office without one: 1.09)."""
    home = calc_code(doc.get("home"))
    cur = calc_code(doc.get("currency"), home)
    if cur == home:
        return home, cur, Decimal(1), False
    fx = dec(doc.get("fx_rate"), "1.09" if (home, cur) == ("EUR", "USD") else "1")  # like homecur.hc_doc_fx
    return home, cur, fx if fx > 0 else Decimal(1), True


def calc_fx_note(pack, lang, home, cur, fx):
    """2.189.0 (#2475): the rate line of a document in a foreign currency; EUR / USD keep the words of before."""
    if (home, cur) == ("EUR", "USD"):
        return label(pack, lang, "fx_note", rate=fmt_qty(fx, lang))
    return label(pack, lang, "fx_note_any", home=home, cur=cur, rate=fmt_qty(fx, lang))


def office_calc(doc, items, pack=None):
    """doc: {lang, currency, fx_rate, vat_mode, raw_mode, raw_factor, prod_quotient, producing_rate, discount_pct};
    items: [{kind: service|text|heading, title, detail, qty, unit, rate, tax, raw_fee, producing, intext, cost, discountable}]
    in order. Returns {net, gross, tax_lines, net_incl_raw, net_excl_raw, raw_amount, raw_mode, producing_days,
    producing_qty, producing_total, discount, costs, margin, items_net, lines, vat_note, fx_rate, currency, lang}."""
    doc = doc or {}
    lang = calc_lang(doc.get("lang"))  # 2.185.0 C (#2520)
    home, currency, fx, foreign = calc_cur(doc)  # 2.189.0 (#2475)
    novat = str(doc.get("vat_mode") or "vat") == "novat"
    raw_mode = doc.get("raw_mode") if doc.get("raw_mode") in RAW_MODES else "optional"
    raw_factor = dec(doc.get("raw_factor"), "0.25")
    quot = dec(doc.get("prod_quotient"), "3")
    prod_rate = dec(doc.get("producing_rate"), "600")
    disc_pct = dec(doc.get("discount_pct"), "0")
    # 2.47.0 (#1645): producing switched on per document; None (rows of 2.46 and older, callers without it) = as before:
    # the flagged positions alone decide
    prod_on = doc.get("producing_on")
    prod_on = True if prod_on is None else _flag(prod_on)
    share = doc.get("producing_mode") == "amount"  # 2.113.1 (#2251): share by amount (prod_quotient = the factor)
    hu_pct, mk_pct = dec(doc.get("handling_pct"), "0"), dec(doc.get("markup_pct"), "0")  # 2.113.1 (#2252)
    rates = {k: (Decimal(0) if novat else pack_tax(pack, k)) for k in TAX_KEYS}

    def conv(rate):  # the rate in the document's currency; 2.354.0 A (#2831): unrounded (was money(): 1000 x 0.125 = 130)
        r = dec(rate)
        return r * fx if foreign else r

    # 2.47.0 (#1649): a position of unit "percent" (e.g. the artists' social insurance) is its rate in percent of the
    # positions marked extern of the same sheet; its quantity does not count
    ext_base = Decimal(0)
    for it in items or []:
        if (it.get("kind") or "service") == "service" and it.get("unit") != "percent" and it.get("intext") == "extern":
            ext_base += money(dec(it.get("qty"), "1") * conv(it.get("rate")))

    lines, pos = [], 0
    items_net = Decimal(0)
    raw_base = Decimal(0)
    prod_qty = Decimal(0)
    prod_amt = Decimal(0)  # 2.113.1 (#2251): the amount of the flagged positions (share by amount)
    hu_base, mk_base = Decimal(0), Decimal(0)  # 2.113.1 (#2252)
    costs = Decimal(0)
    base = {k: Decimal(0) for k in TAX_KEYS}  # taxable amounts per key
    disc_base = {k: Decimal(0) for k in TAX_KEYS}
    for it in items or []:
        kind = it.get("kind") or "service"
        if kind == "heading":
            lines.append({"kind": "heading", "title": it.get("title") or ""})
            continue
        if kind == "text":
            lines.append({"kind": "text", "text": it.get("detail") or it.get("text") or it.get("title") or ""})
            continue
        unit = it.get("unit") or "day"
        pct = None
        if unit == "percent":  # 2.47.0 (#1649): shown as "5 %" x the extern sum
            pct = dec(it.get("rate"))
            qty, rate = Decimal(1), ext_base
            total = money(ext_base * pct / 100)
        else:
            qty = dec(it.get("qty"), "1")
            rate = conv(it.get("rate"))
            total = money(qty * rate)
        tax = it.get("tax") if it.get("tax") in TAX_KEYS else "standard"
        pos += 1
        items_net += total
        base[tax] += total
        if _flag(it.get("raw_fee")):
            raw_base += total
        if _flag(it.get("producing")) and pct is None:
            prod_qty += qty
        if _flag(it.get("producing")):
            prod_amt += total
        if _flag(it.get("in_handling")):
            hu_base += total
        if _flag(it.get("in_markup")):
            mk_base += total
        if _flag(it.get("discountable", 1)):
            disc_base[tax] += total
        costs += money(dec(it.get("cost")) * qty * (fx if foreign else 1))
        lines.append({"kind": "item", "pos": pos, "id": it.get("id"), "service_id": it.get("service_id"), "title": it.get("title") or "",
                      "detail": it.get("detail") or "", "qty": _num(qty), "qty_text": fmt_qty(qty, lang) if pct is None else fmt_qty(pct, lang) + " %",
                      "unit": unit, "unit_text": unit_text(pack, lang, unit, qty) if pct is None else "",
                      **({"pct": _num(pct), "base": _num(ext_base)} if pct is not None else {}),
                      "rate": _num(rate), "tax": tax, "tax_pct": _num(rates[tax]), "total": _num(total),
                      "raw_fee": 1 if _flag(it.get("raw_fee")) else 0, "producing": 1 if _flag(it.get("producing")) else 0,
                      "in_handling": 1 if _flag(it.get("in_handling")) else 0, "in_markup": 1 if _flag(it.get("in_markup")) else 0,
                      "intext": it.get("intext") or "intern", "discountable": 1 if _flag(it.get("discountable", 1)) else 0})

    # Producing
    prod_rate_doc = money(conv(prod_rate))  # 2.354.0 A (#2831): the day rate stays a money amount, as before
    if share:  # 2.113.1 (#2251): amount and rate both in the document's currency
        days = half_days(prod_amt / prod_rate_doc * quot) if prod_on and quot > 0 and prod_rate_doc > 0 and prod_amt > 0 else Decimal(0)
    else:
        days = half_days(prod_qty / quot) if prod_on and quot > 0 and prod_qty > 0 else Decimal(0)
    prod_total = money(days * prod_rate_doc) if days > 0 else Decimal(0)
    if days > 0:
        base["standard"] += prod_total
        if share:
            title = prd_label(doc.get("share_label"), lang) or label(pack, lang, "producing")
            detail = label(pack, lang, "share_detail", amount=fmt_money(prod_amt, lang, currency), rate=fmt_money(prod_rate_doc, lang, currency),
                           factor=fmt_qty(quot, lang), days=fmt_qty(days, lang))
        else:
            title = label(pack, lang, "producing")
            detail = label(pack, lang, "producing_detail", days=fmt_qty(days, lang), qty=fmt_qty(prod_qty, lang), quot=fmt_qty(quot, lang),
                           day_word=unit_text(pack, lang, "day", days),
                           prod_word=tr(CALC_PROD_WORD[0 if prod_qty == 1 else 1], lg=lang))  # 2.114.4 A (#2276): "1 Tag"; 2.185.0 C: tr()
        lines.append({"kind": "producing", "pos": pos + 1, "title": title, "qty": _num(days), "qty_text": fmt_qty(days, lang),
                      "unit": "day", "unit_text": unit_text(pack, lang, "day", days), "rate": _num(prod_rate_doc), "tax": "standard",
                      "tax_pct": _num(rates["standard"]), "total": _num(prod_total), "detail": detail})

    # 2.113.1 (#2252): handling costs, then the markup (stacked: also on the handling costs); the discount takes in neither
    hu_total = money(hu_base * hu_pct / 100) if hu_pct > 0 else Decimal(0)
    stacked = _flag(doc.get("markup_stacked"))
    mk_total = money((mk_base + (hu_total if stacked else 0)) * mk_pct / 100) if mk_pct > 0 else Decimal(0)
    for slot, amt, pct_, det in (("handling", hu_total, hu_pct, "surcharge_detail"),
                                 ("markup", mk_total, mk_pct, "surcharge_detail_stacked" if stacked and hu_total > 0 else "surcharge_detail")):
        if amt <= 0:
            continue
        base["standard"] += amt
        lines.append({"kind": "surcharge", "slot": slot, "pos": pos + 1 + sum(1 for x in lines if x["kind"] in ("producing", "surcharge")),
                      "title": prd_label(doc.get(slot + "_label"), lang) or label(pack, lang, slot),
                      "qty": 1, "qty_text": "1", "unit": "flat", "unit_text": unit_text(pack, lang, "flat", 1), "pct": _num(pct_), "rate": _num(amt),  # 2.296.0 B (#3173): was "" (printed "1 flat")
                      "tax": "standard", "tax_pct": _num(rates["standard"]), "total": _num(amt),
                      "detail": label(pack, lang, det, pct=fmt_qty(pct_, lang))})

    # raw data
    raw_amount = money(raw_base * raw_factor) if raw_mode != "none" else Decimal(0)
    if raw_mode != "none" and raw_base > 0:
        incl = raw_mode == "included"
        if incl:
            base["standard"] += raw_amount
        lines.append({"kind": "raw", "optional": not incl, "title": label(pack, lang, "raw_included" if incl else "raw_optional"),
                      "qty": 1 if incl else None, "qty_text": "1" if incl else "", "unit": "flat", "unit_text": unit_text(pack, lang, "flat", 1) if incl else "",  # 2.296.0 B (#3173)
                      "rate": _num(raw_amount), "tax": "standard", "tax_pct": _num(rates["standard"]), "total": _num(raw_amount),
                      "detail": label(pack, lang, "raw_detail", pct=fmt_qty(raw_factor * 100, lang))})

    # discount
    discount = Decimal(0)
    disc_by = {}  # 2.354.0 A (#2835): the discount per tax key (an invoice from the quotation takes one position per key)
    if disc_pct > 0:
        for k in TAX_KEYS:
            d = money(disc_base[k] * disc_pct / 100)
            base[k] -= d
            discount += d
            if d:
                disc_by[k] = _num(d)
        if discount > 0:
            lines.append({"kind": "discount", "title": label(pack, lang, "discount"), "pct": _num(disc_pct), "total": _num(-discount),
                          "detail": label(pack, lang, "discount_detail", pct=fmt_qty(disc_pct, lang)), "by_tax": disc_by})

    net = items_net + prod_total + hu_total + mk_total + (raw_amount if raw_mode == "included" else Decimal(0)) - discount
    tax_lines, tax_sum = [], Decimal(0)
    if not novat:
        for k in TAX_KEYS:
            if base[k] == 0:
                continue
            amt = money(base[k] * rates[k] / 100)
            tax_sum += amt
            tax_lines.append({"rate_key": k, "pct": _num(rates[k]), "base": _num(base[k]), "amount": _num(amt),
                              "label": label(pack, lang, "tax_" + k, pct=fmt_qty(rates[k], lang))})
    gross = net + tax_sum
    out = {
        "lang": lang, "currency": currency, "fx_rate": _num(fx) if foreign else None, "home": home,
        "fx_note": calc_fx_note(pack, lang, home, currency, fx) if foreign else "",
        "vat_mode": "novat" if novat else "vat", "raw_mode": raw_mode, "producing_on": 1 if prod_on else 0,
        "items_net": _num(items_net), "producing_qty": _num(prod_qty), "producing_days": _num(days), "producing_rate": _num(prod_rate_doc),
        "producing_total": _num(prod_total), "producing_mode": "amount" if share else None, "producing_amount": _num(prod_amt),
        "handling_pct": _num(hu_pct), "handling_base": _num(hu_base), "handling_total": _num(hu_total),
        "markup_pct": _num(mk_pct), "markup_base": _num(mk_base), "markup_total": _num(mk_total), "raw_base": _num(raw_base), "raw_factor": _num(raw_factor), "raw_amount": _num(raw_amount),
        "discount_pct": _num(disc_pct), "discount": _num(discount),
        "net": _num(net), "tax_lines": tax_lines, "tax_total": _num(tax_sum), "gross": _num(gross),
        "net_incl_raw": _num(net + raw_amount) if raw_mode == "optional" and raw_base > 0 else None,
        "net_excl_raw": _num(net - raw_amount) if raw_mode == "included" and raw_base > 0 else None,
        "costs": _num(costs), "margin": _num(net - costs),
        "vat_note": label(pack, lang, ("vat_note_small" if str(doc.get("vat_note") or "") == "small" else "novat_note") if novat else "vat_note"),  # 2.47.3 (#1360)
        # 2.114.4 A (#2274): only the rates that occur in the document ("7 % bzw. 19 %" -> "19 %")
        "lines": lines,
        "labels": {k: label(pack, lang, k) for k in ("net", "net_incl_raw", "net_excl_raw", "gross", "producing", "discount")},
    }
    if not novat:
        out["vat_note"] = bwa_vat_note(out["vat_note"], [rates[k] for k in TAX_KEYS if base[k] != 0 and rates[k] > 0], lang)
    return out


def bwa_vat_note(note, pcts, lang="de"):
    """2.114.4 A (#2274): the VAT note naming only the rates of the document: a list of rates in the note ("7 % bzw.
    19 %", "7 % or 19 %", also an own text of the pack) becomes the rates that occur; no rate or a note without a
    list stays as it is."""
    pcts = sorted(set(Decimal(str(p)) for p in pcts))
    if not pcts:
        return note
    rx = r"\d+(?:[.,]\d+)?\s?%(?:\s*(?:,|/|bzw\.|oder|und|or|and|ou|et|of|en|o|y|e)\s*\d+(?:[.,]\d+)?\s?%)+"  # 2.185.0 C: + fr / nl / es / it
    m = re.search(rx, str(note or ""))
    if not m:
        return note
    join = CALC_OR.get(calc_lang(lang), " / ")
    for w in (" bzw. ", " oder ", " und ", " or ", " and ", " ou ", " et ", " of ", " en ", " o ", " y ", " e ", " / ", ", "):
        if w in m.group(0):
            join = w
            break
    sp = " %" if " %" in m.group(0) else "%"
    return note[:m.start()] + join.join(fmt_qty(p, lang) + sp for p in pcts) + note[m.end():]


# 2.113.1 (#2251): how producing / handling costs / markup were computed is internal: customer documents
# (print model, PDF, approval page, e-invoice, an invoice made from the quotation) show their title and amount only
PRD_INTERNAL_DETAIL = ("producing", "surcharge")


def prd_label(v, lang):
    """2.113.1 (#2251): a line title {de, en} (dict or JSON text, as stored on the document) in the document's language
    (2.185.0 C: any other language takes the English title)."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return v.strip()[:80]
    if not isinstance(v, dict):
        return ""
    lg = "de" if calc_lang(lang) == "de" else "en"
    t = v.get(lg) or v.get("de") or v.get("en") or ""
    return t.strip()[:80] if isinstance(t, str) else ""


def _flag(v):
    return v not in (None, 0, "0", "", False, "false", "off")


def _num(d):
    """A Decimal as a JSON number: integers as int, else a float with 2 (money) or up to 4 places."""
    if d is None:
        return None
    d = dec(d)
    if d == d.to_integral():
        return int(d)
    return float(d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize())


# ---------------------------------------------------------------- 2.38.0 (#1021, F1): invoices, credit notes, reminders
INV_ITEM_KINDS = ("service", "text", "heading", "discount")
INV_VAT_NOTES = ("reverse", "abroad", "small", "eu_goods", "export")  # 2.355.0 C (#2844): + goods to the EU (K) / a third country (G)


def dstr(d):
    """A Decimal as money text with exactly 2 places ("34422.90"); the exact figures of invoices travel as such strings."""
    return format(money(dec(d)), "f")


def inv_calc(doc, items, pack=None):
    """The invoice calculator (invoices and credit notes): no producing / raw data / discount automation -- a document is
    exactly its positions; a discount is a position of kind "discount" (its amount is taken off, same tax class).
    Every position is money(qty x rate) (rate converted into USD first, like quotations); the document's net is the sum of
    the positions; the tax per rate is computed on the rounded sum of that rate (EN 16931), half up to 2 places.
    All amounts of the result are decimal strings with 2 places ("net": "34422.90"); the lines keep the numbers the editor
    shows (qty / rate / total). USD: tax_eur / gross_eur = the tax and the total in EUR by doc["fx_rate"] (VAT law)."""
    doc = doc or {}
    lang = calc_lang(doc.get("lang"))  # 2.185.0 C (#2520)
    home, currency, fx, foreign = calc_cur(doc)  # 2.189.0 (#2475)
    novat = str(doc.get("vat_mode") or "vat") == "novat"
    rates = {k: (Decimal(0) if novat else pack_tax(pack, k)) for k in TAX_KEYS}

    def conv(rate):  # 2.354.0 A (#2831): unrounded, the position is money(qty x rate x fx) (was money(rate) first)
        r = dec(rate)
        return r * fx if foreign else r

    lines, pos = [], 0
    net = Decimal(0)
    costs = Decimal(0)
    base = {k: Decimal(0) for k in TAX_KEYS}
    ext_base = Decimal(0)  # 2.47.0 (#1649): the base of positions of unit "percent", like office_calc
    for it in items or []:
        if (it.get("kind") or "service") == "service" and it.get("unit") != "percent" and it.get("intext") == "extern":
            ext_base += money(dec(it.get("qty"), "1") * conv(it.get("rate")))
    for it in items or []:
        kind = it.get("kind") or "service"
        if kind == "heading":
            lines.append({"kind": "heading", "title": it.get("title") or ""})
            continue
        if kind == "text":
            lines.append({"kind": "text", "text": it.get("detail") or it.get("text") or it.get("title") or ""})
            continue
        pct = dec(it.get("rate")) if kind == "service" and it.get("unit") == "percent" else None
        qty = dec(it.get("qty"), "1") if pct is None else Decimal(1)
        total = money(qty * conv(it.get("rate"))) if pct is None else money(ext_base * pct / 100)
        rate = conv(it.get("rate")) if pct is None else total  # an invoice line stays qty x rate (EN 16931)
        if kind == "discount":
            total = -abs(total)
        tax = it.get("tax") if it.get("tax") in TAX_KEYS else "standard"
        pos += 1
        net += total
        base[tax] += total
        if kind != "discount":
            costs += money(dec(it.get("cost")) * qty * (fx if foreign else 1))
        unit = it.get("unit") or "day"
        lines.append({"kind": "discount" if kind == "discount" else "item", "pos": pos, "id": it.get("id"), "service_id": it.get("service_id"),
                      "title": it.get("title") or (label(pack, lang, "discount") if kind == "discount" else ""), "detail": it.get("detail") or "",
                      "qty": _num(qty), "qty_text": fmt_qty(qty, lang) if pct is None else fmt_qty(pct, lang) + " %", "unit": unit,
                      "unit_text": unit_text(pack, lang, unit, qty) if pct is None else "",
                      **({"pct": _num(pct), "base": _num(ext_base)} if pct is not None else {}),
                      "rate": _num(rate), "rate_text": fmt_rate(rate, lang, currency) if pct is None else fmt_money(rate, lang, currency), "tax": tax, "tax_pct": _num(rates[tax]),
                      "total": _num(total), "total_text": fmt_money(total, lang, currency), "net": dstr(total), "intext": it.get("intext") or "intern"})
    tax_lines, tax_sum = [], Decimal(0)
    if not novat:
        for k in TAX_KEYS:
            if base[k] == 0:
                continue
            amt = money(base[k] * rates[k] / 100)
            tax_sum += amt
            tax_lines.append({"rate_key": k, "pct": format(rates[k].normalize(), "f"), "base": dstr(base[k]), "amount": dstr(amt),
                              "base_text": fmt_money(base[k], lang, currency), "amount_text": fmt_money(amt, lang, currency),
                              "label": label(pack, lang, "tax_" + k, pct=fmt_qty(rates[k], lang))})
    gross = net + tax_sum
    out = {
        "lang": lang, "currency": currency, "fx_rate": format(fx.normalize(), "f") if foreign else None, "home": home,
        "fx_note": calc_fx_note(pack, lang, home, currency, fx) if foreign else "",
        "vat_mode": "novat" if novat else "vat", "raw_mode": "none",
        "net": dstr(net), "net_text": fmt_money(net, lang, currency), "tax_lines": tax_lines, "tax": dstr(tax_sum), "tax_total": dstr(tax_sum),
        "tax_text": fmt_money(tax_sum, lang, currency), "gross": dstr(gross), "gross_text": fmt_money(gross, lang, currency),
        "costs": dstr(costs), "margin": dstr(net - costs), "items_net": dstr(net), "discount": "0.00", "raw_amount": "0.00", "producing_days": 0,
        "vat_note": label(pack, lang, "novat_note") if novat else "",
        "lines": lines,
        "labels": {k: label(pack, lang, k) for k in ("net", "gross", "discount")},
    }
    if foreign:  # the tax (and the total) in the home currency as well, by the document's rate (2.189.0: keys keep "_eur")
        out["tax_eur"] = dstr(tax_sum / fx)
        out["gross_eur"] = dstr(gross / fx)
        out["tax_eur_text"] = fmt_money(tax_sum / fx, lang, home)
        out["gross_eur_text"] = fmt_money(gross / fx, lang, home)
    return out


def inv_open(gross, paid, credits="0"):
    """(paid, open) as strings: open = gross - paid - credits, never below zero."""
    o = money(dec(gross)) - money(dec(paid)) - money(dec(credits))
    return dstr(paid), dstr(o if o > 0 else Decimal(0))
