"""2.603.0 (#4921): the comparison of the income/expense statement (EUeR) with the year before -- display only.

The year and the year before both come from books.bk_euer (called twice, never changed here) and the VAT liability from
books.bk_ustva over the whole year (field 83). Has the year before no figures of its own in Kalmido (income or expenses;
the depreciation of devices alone does not count, it runs on in every year), the comparison falls back to the DATEV booking
archive (office/bookarch.py ba_euer_year, only while the DATEV function is on): its sums are marked "source DATEV archive"
and are never added to Kalmido figures, booked, taken over or counted into the EUeR / VAT return of any year. The VAT
return itself gets no comparison. The tax check (office/taxcheck.py tc_jumps) compares the same two bk_euer results for its
hints; this view shows every line with the deviation.

GET /api/office/books/euer/compare?year=YYYY -> {year, prev_year, currency, small_business, source kalmido | archive | none,
rows [{key, group income | expense | total, label, now, prev, diff, pct}], vat {now, prev, diff, pct} | None,
archive {chart, accounts [...]} | None, notes}. Amounts as text with two decimals (net; a small business: gross), pct an
integer or None (no figure the year before). Rights as the EUeR (office admin; agents 403)."""
from decimal import Decimal

from flask import jsonify, request

from ..core.config import app
from ..core.i18n import N_, tr
from .bookarch import ba_euer_year
from .books import BK_NOTE, _ctx, _year, bk_euer, bk_ustva
from .datev import dx_settings
from .calc import dec, dstr, money
from .model import office_feature, office_settings

EC_SRC_ARCHIVE = N_("Source: DATEV archive")
EC_NOTE = N_("Comparison for display only: nothing is booked, imported or counted into this year.")
EC_NOTE_ARCHIVE = N_("The year before comes from the DATEV booking archive (sums of the profit and loss accounts and the VAT accounts); it is not added to figures in Kalmido.")


def _ec_own(e):
    """True when a bk_euer result holds figures of its own (depreciation alone runs on from older purchases: not counted)."""
    return bool(e["income"]) or any(not r["key"].startswith("a:") for r in e["expenses"])


def _ec_vat(c, oid, year, s):
    """The VAT liability of a Kalmido year (field 83 of the whole year), or None (small business / VAT return figures off)."""
    if s.get("small_business") or not office_feature(c, oid, "books.vat_return", s):
        return None
    return dec(bk_ustva(c, oid, year, "y").get("kz", {}).get("83") or 0)


def _ec_row(key, group, label, now, prev):
    d = None if prev is None else now - prev  # no figure the year before: no deviation either
    pct = int(round(d * 100 / abs(prev))) if prev else None
    m = lambda v: None if v is None else dstr(money(v))  # noqa: E731
    return {"key": key, "group": group, "label": label, "now": m(now), "prev": m(prev), "diff": m(d), "pct": pct}


def bk_euer_compare(c, oid, year):
    """The EUeR of year next to the year before (see the module text)."""
    s = office_settings(c, oid)
    e = bk_euer(c, oid, year)
    p = bk_euer(c, oid, year - 1)
    small = e["small_business"]
    f = "gross" if small else "net"
    rows, arch, src = [], None, "kalmido"
    if _ec_own(p):
        prev = {("i:" + r["key"]): (r["label"], dec(r[f])) for r in p["income"]}
        prev.update({("e:" + r["key"]): (r["label"], dec(r[f])) for r in p["expenses"]})
        for grp, lines in (("income", e["income"]), ("expense", e["expenses"])):
            pre = "i:" if grp == "income" else "e:"
            for r in lines:
                rows.append(_ec_row(pre + r["key"], grp, r["label"], dec(r[f]), prev.pop(pre + r["key"], (None, Decimal(0)))[1]))
            for k, (lb, v) in prev.items():  # lines only the year before had
                if k.startswith(pre):
                    rows.append(_ec_row(k, grp, lb, Decimal(0), v))
        p_inc, p_exp, p_profit = dec(p["income_total"][f]), dec(p["expense_total"][f]), dec(p["profit"])
        p_vat = _ec_vat(c, oid, year - 1, s)
    else:
        a = None
        if office_feature(c, oid, "books.datev", s):
            dx = dx_settings(s)
            a = ba_euer_year(c, oid, year - 1, dx.get("chart") or "SKR03", int(dx.get("acct_len") or 4))
        if a:
            src = "archive"
            p_inc, p_exp = dec(a["income"][f]), dec(a["expense"][f])
            p_profit = p_inc - p_exp
            p_vat = None if small else dec(a["vat_due"])
            arch = {"chart": a["chart"], "accounts": a["accounts"], "label": tr(EC_SRC_ARCHIVE)}
        else:
            src, p_inc, p_exp, p_profit, p_vat = "none", None, None, None, None
    rows += [_ec_row("income_total", "total", tr("Income"), dec(e["income_total"][f]), p_inc),
             _ec_row("expense_total", "total", tr("Expenses"), dec(e["expense_total"][f]), p_exp),
             _ec_row("profit", "total", tr("Profit"), dec(e["profit"]), p_profit)]
    vat = None
    n_vat = _ec_vat(c, oid, year, s)
    if n_vat is not None:
        v = _ec_row("vat_due", "vat", tr("VAT liability"), n_vat, p_vat)
        vat = {k: v[k] for k in ("label", "now", "prev", "diff", "pct")}
    notes = [tr(EC_NOTE)] + ([tr(EC_NOTE_ARCHIVE)] if src == "archive" else []) + [tr(BK_NOTE)]
    return {"year": year, "prev_year": year - 1, "currency": e["currency"], "small_business": small, "source": src,
            "rows": rows, "vat": vat, "archive": arch, "notes": notes}


@app.get("/api/office/books/euer/compare")
def bk_euer_compare_get():
    """?year=YYYY (default: this one) -> bk_euer_compare."""
    c, uid, oid = _ctx()
    return jsonify(bk_euer_compare(c, oid, _year(request.args.get("year"))))
