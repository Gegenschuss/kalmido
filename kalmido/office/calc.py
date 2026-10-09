"""2.36.1 (#1021): the quotation calculator of Office & Finance -- a pure function without database or request context.

office_calc(doc, items, pack) -> dict reproduces the rules of the spreadsheet template the module replaces:
 - a position is qty x rate; rates are kept in the organisation's currency (EUR) and converted into the document's
   currency with doc["fx_rate"] when the document is in USD (converted rate rounded to 2 places first, like the template)
 - "Producing": the sum of the quantities of the positions flagged producing, divided by doc["prod_quotient"], rounded to
   half days the way the template does (ROUND(x / 5, 1) * 5), times doc["producing_rate"]; only when > 0
 - raw data: the sum of the totals of the positions flagged raw_fee times doc["raw_factor"]; raw_mode "optional" shows
   the line without counting it (net_incl_raw next to net), "included" counts it (net_excl_raw next to net), "none" omits it
 - discount: doc["discount_pct"] on the positions flagged discountable, one negative line
 - tax per position through the country pack (standard / reduced / exempt); vat_mode "novat" = no tax at all
Money is Decimal, rounded half up to 2 places at every step the template rounds; the result holds floats (JSON).
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

Q2 = Decimal("0.01")
TAX_KEYS = ("standard", "reduced", "exempt")
RAW_MODES = ("optional", "included", "none")

# the words of the document itself (its language, not the signed-in person's): the country pack may override them
# (pack["labels"][lang][key]); these are the defaults so the calculator works without a pack
LABELS = {
    "de": {
        "producing": "Producing", "producing_detail": "{days} Tage = {qty} Produktionstage / {quot}, auf halbe Tage gerundet",
        "raw_optional": "Optional: Bereitstellung der Rohdaten", "raw_included": "Bereitstellung der Rohdaten",
        "raw_detail": "{pct} % der Positionen mit Rohdaten", "discount": "Rabatt", "discount_detail": "{pct} % auf die markierten Positionen",
        "net": "Summe Netto", "net_incl_raw": "inklusive Rohdaten", "net_excl_raw": "ohne Rohdaten", "gross": "Gesamt Brutto",
        "tax_standard": "MwSt. {pct} %", "tax_reduced": "MwSt. {pct} %", "tax_exempt": "steuerfrei",
        "vat_note": "Alle Preise zuzüglich 7 % bzw. 19 % MwSt.", "novat_note": "Nicht im Inland steuerbar / Reverse-Charge-Verfahren.",
        "fx_note": "Wechselkurs 1 €: {rate} $",
        "unit_day": "Tage", "unit_hour": "Std.", "unit_piece": "Stk.", "unit_minute": "Min.", "unit_flat": "pauschal",
    },
    "en": {
        "producing": "Producing", "producing_detail": "{days} days = {qty} production days / {quot}, rounded to half days",
        "raw_optional": "Optional: Delivery of raw data", "raw_included": "Delivery of raw data",
        "raw_detail": "{pct} % of the positions with raw data", "discount": "Discount", "discount_detail": "{pct} % on the marked positions",
        "net": "Net Total", "net_incl_raw": "including raw data", "net_excl_raw": "excluding raw data", "gross": "Gross Total",
        "tax_standard": "VAT {pct} %", "tax_reduced": "VAT {pct} %", "tax_exempt": "tax exempt",
        "vat_note": "All prices plus 7 % or 19 % VAT.", "novat_note": "Not taxable domestically / reverse charge.",
        "fx_note": "Exchange rate €1: ${rate}",
        "unit_day": "days", "unit_hour": "h", "unit_piece": "pcs", "unit_minute": "min", "unit_flat": "flat",
    },
}
DEFAULT_TAX = {"standard": 19, "reduced": 7, "exempt": 0}


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
    elif "," in s:
        s = s.replace(",", ".")
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
        lg = "en" if (lang or "de").lower().startswith("en") else "de"
        one = (((pack or {}).get("labels") or {}).get(lg) or {}).get("units_one")
        if isinstance(one, dict) and one.get(unit):
            return one[unit]
    return label(pack, lang, "unit_" + unit)


def label(pack, lang, key, **kw):
    """A word of the document in its language: pack["labels"][lang][key] (units: labels[lang]["units"][unit]), then
    pack["texts"][key][lang], then the built-in LABELS; {placeholders} filled from kw."""
    lg = "en" if (lang or "de").lower().startswith("en") else "de"
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
    if s is None:
        s = LABELS[lg].get(key) or LABELS["de"].get(key) or key
    if kw:
        try:
            s = s.format(**kw)
        except (KeyError, IndexError, ValueError):
            pass
    return s


def fmt_qty(d, lang="de"):
    """A quantity for a line: 3 -> "3", 4.5 -> "4,5" (de) / "4.5" (en)."""
    d = dec(d).normalize()
    s = str(int(d)) if d == d.to_integral() else format(d, "f")
    return s if (lang or "de").lower().startswith("en") else s.replace(".", ",")


def fmt_money(d, lang="de", currency="EUR"):
    """1234.5 -> "1.234,50 €" (de) / "€1,234.50" (en) / USD "1.234,50 $" / "$1,234.50"."""
    d = money(dec(d))
    neg = d < 0
    whole, frac = f"{abs(d):.2f}".split(".")
    en = (lang or "de").lower().startswith("en")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    sym = "$" if currency == "USD" else "€"
    if en:
        s = ",".join(groups) + "." + frac
        return ("-" if neg else "") + sym + s
    s = ".".join(groups) + "," + frac
    return ("-" if neg else "") + s + " " + sym


def office_calc(doc, items, pack=None):
    """doc: {lang, currency, fx_rate, vat_mode, raw_mode, raw_factor, prod_quotient, producing_rate, discount_pct};
    items: [{kind: service|text|heading, title, detail, qty, unit, rate, tax, raw_fee, producing, intext, cost, discountable}]
    in order. Returns {net, gross, tax_lines, net_incl_raw, net_excl_raw, raw_amount, raw_mode, producing_days,
    producing_qty, producing_total, discount, costs, margin, items_net, lines, vat_note, fx_rate, currency, lang}."""
    doc = doc or {}
    lang = "en" if str(doc.get("lang") or "de").lower().startswith("en") else "de"
    currency = "USD" if str(doc.get("currency") or "EUR").upper() == "USD" else "EUR"
    fx = dec(doc.get("fx_rate"), "1.09") if currency == "USD" else Decimal(1)
    if fx <= 0:
        fx = Decimal(1)
    novat = str(doc.get("vat_mode") or "vat") == "novat"
    raw_mode = doc.get("raw_mode") if doc.get("raw_mode") in RAW_MODES else "optional"
    raw_factor = dec(doc.get("raw_factor"), "0.25")
    quot = dec(doc.get("prod_quotient"), "3")
    prod_rate = dec(doc.get("producing_rate"), "600")
    disc_pct = dec(doc.get("discount_pct"), "0")
    rates = {k: (Decimal(0) if novat else pack_tax(pack, k)) for k in TAX_KEYS}

    def conv(rate):  # the rate in the document's currency
        r = dec(rate)
        return money(r * fx) if currency == "USD" else money(r)

    lines, pos = [], 0
    items_net = Decimal(0)
    raw_base = Decimal(0)
    prod_qty = Decimal(0)
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
        qty = dec(it.get("qty"), "1")
        rate = conv(it.get("rate"))
        total = money(qty * rate)
        tax = it.get("tax") if it.get("tax") in TAX_KEYS else "standard"
        pos += 1
        items_net += total
        base[tax] += total
        if _flag(it.get("raw_fee")):
            raw_base += total
        if _flag(it.get("producing")):
            prod_qty += qty
        if _flag(it.get("discountable", 1)):
            disc_base[tax] += total
        costs += money(dec(it.get("cost")) * qty * (fx if currency == "USD" else 1))
        unit = it.get("unit") or "day"
        lines.append({"kind": "item", "pos": pos, "id": it.get("id"), "service_id": it.get("service_id"), "title": it.get("title") or "",
                      "detail": it.get("detail") or "", "qty": _num(qty), "qty_text": fmt_qty(qty, lang), "unit": unit,
                      "unit_text": unit_text(pack, lang, unit, qty),
                      "rate": _num(rate), "tax": tax, "tax_pct": _num(rates[tax]), "total": _num(total),
                      "raw_fee": 1 if _flag(it.get("raw_fee")) else 0, "producing": 1 if _flag(it.get("producing")) else 0,
                      "intext": it.get("intext") or "intern", "discountable": 1 if _flag(it.get("discountable", 1)) else 0})

    # Producing
    days = half_days(prod_qty / quot) if quot > 0 and prod_qty > 0 else Decimal(0)
    prod_rate_doc = conv(prod_rate)
    prod_total = money(days * prod_rate_doc) if days > 0 else Decimal(0)
    if days > 0:
        base["standard"] += prod_total
        lines.append({"kind": "producing", "title": label(pack, lang, "producing"), "qty": _num(days), "qty_text": fmt_qty(days, lang),
                      "unit": "day", "unit_text": unit_text(pack, lang, "day", days), "rate": _num(prod_rate_doc), "tax": "standard",
                      "tax_pct": _num(rates["standard"]), "total": _num(prod_total),
                      "detail": label(pack, lang, "producing_detail", days=fmt_qty(days, lang), qty=fmt_qty(prod_qty, lang), quot=fmt_qty(quot, lang))})

    # raw data
    raw_amount = money(raw_base * raw_factor) if raw_mode != "none" else Decimal(0)
    if raw_mode != "none" and raw_base > 0:
        incl = raw_mode == "included"
        if incl:
            base["standard"] += raw_amount
        lines.append({"kind": "raw", "optional": not incl, "title": label(pack, lang, "raw_included" if incl else "raw_optional"),
                      "qty": 1 if incl else None, "qty_text": "1" if incl else "", "unit": "flat", "unit_text": "",
                      "rate": _num(raw_amount), "tax": "standard", "tax_pct": _num(rates["standard"]), "total": _num(raw_amount),
                      "detail": label(pack, lang, "raw_detail", pct=fmt_qty(raw_factor * 100, lang))})

    # discount
    discount = Decimal(0)
    if disc_pct > 0:
        for k in TAX_KEYS:
            d = money(disc_base[k] * disc_pct / 100)
            base[k] -= d
            discount += d
        if discount > 0:
            lines.append({"kind": "discount", "title": label(pack, lang, "discount"), "pct": _num(disc_pct), "total": _num(-discount),
                          "detail": label(pack, lang, "discount_detail", pct=fmt_qty(disc_pct, lang))})

    net = items_net + prod_total + (raw_amount if raw_mode == "included" else Decimal(0)) - discount
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
        "lang": lang, "currency": currency, "fx_rate": _num(fx) if currency == "USD" else None,
        "fx_note": label(pack, lang, "fx_note", rate=fmt_qty(fx, lang)) if currency == "USD" else "",
        "vat_mode": "novat" if novat else "vat", "raw_mode": raw_mode,
        "items_net": _num(items_net), "producing_qty": _num(prod_qty), "producing_days": _num(days), "producing_rate": _num(prod_rate_doc),
        "producing_total": _num(prod_total), "raw_base": _num(raw_base), "raw_factor": _num(raw_factor), "raw_amount": _num(raw_amount),
        "discount_pct": _num(disc_pct), "discount": _num(discount),
        "net": _num(net), "tax_lines": tax_lines, "tax_total": _num(tax_sum), "gross": _num(gross),
        "net_incl_raw": _num(net + raw_amount) if raw_mode == "optional" and raw_base > 0 else None,
        "net_excl_raw": _num(net - raw_amount) if raw_mode == "included" and raw_base > 0 else None,
        "costs": _num(costs), "margin": _num(net - costs),
        "vat_note": label(pack, lang, "novat_note" if novat else "vat_note"),
        "lines": lines,
        "labels": {k: label(pack, lang, k) for k in ("net", "net_incl_raw", "net_excl_raw", "gross", "producing", "discount")},
    }
    return out


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
