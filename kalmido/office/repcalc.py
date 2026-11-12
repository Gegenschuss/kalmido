"""2.1041.0 (#5812): repricing a quotation (Nachkalkulieren) -- the pure part, without database or request context.

The prices themselves change, no discount or markup line appears: the unit prices (rate, stored in the office's home
currency) of the chosen positions are multiplied by one factor and rounded (cent / whole euro / 5 euro). Three ways to
get the factor (orp_solve):
 - "pct": by x % (factor 1 + x / 100)
 - "net" / "gross": a target sum of the document (its currency), found through the real calculation: ev(items, rate)
   is the caller's office_calc / tp_doc_totals with the scaled prices put in, so discount, markup, handling costs, raw
   data, producing and positions that count in no sum (#5814 opt) all count the way the document counts them
 - "margin": the surplus (net minus external costs, office_calc margin / costs) on x % of the net
The search is a bisection over the factor on the ROUNDED prices (the result is a step function of the factor), so it
ends at the closest sum a single factor reaches. rest = the largest scaled position (by amount) takes what is left, in
cents of its unit price; with a quantity > 1 the smallest possible deviation stays and is reported.
Not scaled: headings, text lines, part lines of the title page and positions of unit "percent" (their rate is a
percentage). The producing day rate is scaled with the same factor and rounding when asked (scale_prod).
Loaded as a single file by tests/office_calc_test.py (no package): only calc.py is imported, with a fallback."""
from decimal import Decimal, ROUND_HALF_UP

try:
    from .calc import dec, money
except ImportError:  # loaded on its own (tests)
    from calc import dec, money  # type: ignore

ORP_MODES = ("pct", "net", "gross", "margin")
ORP_ROUND = {"cent": Decimal("0.01"), "euro": Decimal(1), "five": Decimal(5)}
ORP_ITER = 64  # bisection steps (2^-64 of the range: far below a cent)
ORP_MAX_FACTOR = Decimal(1000)
_Q4 = Decimal("0.0001")


def orp_scalable(it):
    """A position whose unit price is a price (not a heading / text / part line, not a percentage)."""
    return (it.get("kind") or "service") == "service" and (it.get("unit") or "day") != "percent"


def orp_round(v, rnd, places4=False):
    """A unit price rounded by rnd (cent / euro / five); a price smaller than the step stays a cent amount (a 0.50 rate is not
    rounded to nothing); places4 = the price had more than 2 places (0.125): 4 places kept with "cent"."""
    v = dec(v)
    step = ORP_ROUND.get(rnd, ORP_ROUND["cent"])
    if step > ORP_ROUND["cent"] and abs(v) >= step:
        return ((v / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step).quantize(ORP_ROUND["cent"])
    return v.quantize(_Q4 if places4 else ORP_ROUND["cent"], rounding=ROUND_HALF_UP)


def _places4(v):
    v = dec(v)
    return v != money(v)


def orp_scale(items, sel, f, rnd):
    """items with the rates of the positions at the indexes sel x f, rounded (new dicts; the others as they are)."""
    out = []
    for i, it in enumerate(items):
        if i in sel:
            r = dec(it.get("rate"))
            it = {**it, "rate": orp_round(r * f, rnd, _places4(r))}
        out.append(it)
    return out


def orp_metric(t, mode):
    """The figure a target compares with: net / gross of the totals, margin = surplus in % of the net (None: no net)."""
    if mode == "gross":
        return dec(t.get("gross"))
    if mode == "margin":
        net = dec(t.get("net"))
        return None if net == 0 else (net - dec(t.get("costs"))) / net * 100
    return dec(t.get("net"))


def orp_figures(t):
    """{net, gross, costs, margin, margin_pct} of totals t as Decimal (margin_pct None without a net)."""
    net, costs = dec(t.get("net")), dec(t.get("costs"))
    return {"net": net, "gross": dec(t.get("gross")), "costs": costs, "margin": net - costs,
            "margin_pct": None if net == 0 else ((net - costs) / net * 100).quantize(ORP_ROUND["cent"], rounding=ROUND_HALF_UP)}


def orp_rest_index(items, sel):
    """The largest scaled position by amount |qty x rate| (not one that counts in no sum, #5814 opt), None if none."""
    best, bv = None, Decimal(0)
    for i in sorted(sel):
        it = items[i]
        if it.get("opt"):
            continue
        v = abs(dec(it.get("qty"), "1") * dec(it.get("rate")))
        if v > bv:
            best, bv = i, v
    return best


def orp_solve(ev, items, sel, prod_rate, mode, value, rnd="cent", rest=False, scale_prod=False):
    """ev(items, prod_rate) -> totals (office_calc shape). sel: the indexes of the positions to scale (scalable ones only).
    -> {factor, items (new), prod_rate (new), before, after (totals), reachable, reason?, deviation (target minus reached,
    Decimal; None for "pct")}. reason: "nothing" (no price to change), "negative" (prices would have to go below zero),
    "too_high" (more than ORP_MAX_FACTOR), "margin_net" (no net to take a margin of)."""
    sel = {i for i in sel if 0 <= i < len(items) and orp_scalable(items[i])}
    value = dec(value)
    prod_rate = dec(prod_rate)
    before = ev(items, prod_rate)

    def build(f):
        return orp_scale(items, sel, f, rnd), orp_round(prod_rate * f, rnd) if scale_prod else prod_rate

    def res(f, its, pr, reachable=True, reason=None, after=None):
        out = {"factor": f, "items": its, "prod_rate": pr, "before": before, "after": after if after is not None else ev(its, pr),
               "reachable": reachable, "deviation": None}
        if reason:
            out["reason"] = reason
        if mode != "pct" and reachable:
            m = orp_metric(out["after"], mode)
            out["deviation"] = None if m is None else value - m
        return out

    if not any(dec(items[i].get("rate")) != 0 for i in sel) and not (scale_prod and prod_rate):
        return res(Decimal(1), items, prod_rate, False, "nothing", before)
    if mode == "pct":
        f = 1 + value / 100
        if f <= 0:
            return res(Decimal(1), items, prod_rate, False, "negative", before)
        its, pr = build(f)
        return res(f, its, pr)

    memo = {}

    def g(f):
        if f not in memo:
            its, pr = build(f)
            t = ev(its, pr)
            memo[f] = (orp_metric(t, mode), its, pr, t)
        return memo[f]

    if mode == "margin" and g(Decimal(1))[0] is None:
        return res(Decimal(1), items, prod_rate, False, "margin_net", before)
    m0 = g(Decimal(0))[0]
    if m0 is not None and m0 > value:
        return res(Decimal(1), items, prod_rate, False, "negative", before)
    lo, hi = Decimal(0), Decimal(1)
    while (g(hi)[0] is None or g(hi)[0] < value) and hi <= ORP_MAX_FACTOR:
        lo, hi = hi, hi * 2
    if hi > ORP_MAX_FACTOR:
        return res(Decimal(1), items, prod_rate, False, "too_high", before)
    for _ in range(ORP_ITER):
        if g(hi)[0] == value:
            break
        mid = (lo + hi) / 2
        m = g(mid)[0]
        if m is None or m < value:
            lo = mid
        else:
            hi = mid
    cands = [x for x in (hi, lo) if x > 0 and g(x)[0] is not None]
    if not cands:
        return res(Decimal(1), items, prod_rate, False, "negative", before)
    f = min(cands, key=lambda x: abs(value - g(x)[0]))  # hi first: on a tie the higher sum (the target not undercut)
    _m, its, pr, t = g(f)
    if rest and _m != value:
        its, t = orp_rest(ev, its, pr, sel, mode, value)
    return res(f, its, pr, after=t)


def _orp_near(ev, its, pr, k, mode, value):
    """Position k's unit price moved by whole cents so that the figure comes closest to value (a local search around the
    step the slope suggests); a price never changes its sign. -> (|deviation| or None, items, totals)."""
    t0 = ev(its, pr)
    m0 = orp_metric(t0, mode)
    r0 = dec(its[k].get("rate"))
    cent = ORP_ROUND["cent"]

    def at(d):
        x = list(its)
        x[k] = {**its[k], "rate": money(r0) + d * cent}
        t = ev(x, pr)
        return orp_metric(t, mode), x, t

    best = (None if m0 is None else abs(value - m0), its, t0)
    m1 = at(100)[0]
    if m0 is None or m1 is None or m1 == m0:
        return best
    k0 = int(((value - m0) / (m1 - m0) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    for d in sorted(set(range(k0 - 3, k0 + 4)), key=lambda x: abs(x - k0)):
        nr = money(r0) + d * cent
        if (r0 > 0 and nr < 0) or (r0 < 0 and nr > 0):
            continue
        m, x, t = at(d)
        if m is not None and abs(value - m) < best[0]:
            best = (abs(value - m), x, t)
    return best


def orp_rest(ev, its, pr, sel, mode, value):
    """The rest on the largest scaled position (_orp_near). Its steps may skip the target: a quantity > 1 moves the sum by
    qty cents, a discount takes a share of every cent off, the tax of one rate is rounded on its sum (gross). Then one of
    the next largest scaled positions (another tax rate first for gross) moves by a few cents as well and the rest position
    is searched again. -> (items, totals)."""
    k = orp_rest_index(its, sel)
    if k is None:
        return its, ev(its, pr)
    dv, x, t = _orp_near(ev, its, pr, k, mode, value)
    if not dv:
        return x, t
    tk = its[k].get("tax") or "standard"
    others = sorted((i for i in sel if i != k and not its[i].get("opt") and dec(its[i].get("rate"))),
                    key=lambda i: (mode == "gross" and (its[i].get("tax") or "standard") == tk, -abs(dec(its[i].get("qty"), "1") * dec(its[i].get("rate")))))
    cent = ORP_ROUND["cent"]
    for k2 in others[:3]:
        r2 = money(dec(x[k2].get("rate")))
        for j in (1, -1, 2, -2, 3, -3):
            n2 = r2 + j * cent
            if (r2 > 0 and n2 < 0) or (r2 < 0 and n2 > 0):
                continue
            y = list(x)
            y[k2] = {**y[k2], "rate": n2}
            d2, y, t2 = _orp_near(ev, y, pr, k, mode, value)
            if d2 is not None and d2 < dv:
                dv, x, t = d2, y, t2
            if not dv:
                return x, t
    return x, t
