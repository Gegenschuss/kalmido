"""2.589.0 (#3458): the tax check before filing the Anlage EUeR and the annual VAT return -- a traffic light per point.

Nothing is computed twice and nothing is filed or booked: the figures come from books.bk_euer (the year and the year before),
books.bk_ustva (the advance returns of the rhythm of the tax dates) and taxforms.tf_ust (the annual VAT return of #3456, fed
with the same advance returns). The check only compares and names what the tax office tends to look at.

Every point: {punkt (key), group, ampel green | yellow | red, title, text, link, amount (the deviation, text with two
decimals, or None), details: [texts]}. Red is a hint as well and never blocks anything; the quotas are hints only (never red).
link: "#office/..." (a place of the app) or "setgo:biz-<part>" (a part of Settings > Company & office).
Rights: the same as the tax forms (office_ctx_admin + the function books.vat_return); the bank points only for a person who
may see the bank (ofr_allows "bank"), else they are left out. No tax advice; figures without guarantee."""
import re
from decimal import Decimal

from flask import jsonify, request

from ..core.config import app
from ..core.db import local_now
from ..core.i18n import N_, lang, tr, trn
from ..docs.rcheck import rck_taxno_ok
from .assets import AST_GWG, ast_afa_year
from .books import BK_NOTE, _ctx, _year, bk_euer, bk_receipts, bk_ustva
from .calc import calc_lang, dec, dstr, money
from .ledger import ofx_company
from .model import office_need_feature, office_settings
from .pdf import pdf_money
from .rights import ofr_allows
from .taxforms import TF_EUER, TF_FEATURE, tf_periods, tf_ust

# ---------------------------------------------------------------- thresholds (no tax advice; figures without guarantee)
# a jump to the year before counts when BOTH hold: at least TC_JUMP_PCT percent AND at least TC_JUMP_EUR (home currency)
TC_JUMP_PCT = Decimal(30)
TC_JUMP_EUR = Decimal(2500)
TC_JUMP_SHOW = 6  # lines named in the details
# rounding of the forms: bases in whole euros per field and period (81 / 86 / 35) -> up to 3 euros per period
TC_TOL_PERIOD = Decimal(3)
# quotas (share of the net income), hints only: the tax office compares with the averages of the trade
TC_QUOTA_COST = Decimal(90)   # expenses above 90 % of the income
TC_QUOTA_MEALS = Decimal(3)   # entertainment above 3 % of the income
TC_QUOTA_CAR = Decimal(20)    # vehicle costs above 20 % of the income
# low-value assets (section 6 (2) EStG): written off at once up to 800 EUR net since 2018 (410 EUR before); assets.AST_GWG
TC_GWG = ((2018, AST_GWG), (0, Decimal(410)))
# gifts to business friends (section 4 (5) no. 1 EStG): deductible up to 50 EUR net per person and year since 2024 (35 EUR before)
TC_GIFT = ((2024, Decimal(50)), (0, Decimal(35)))
# study / home office (section 4 (5) no. 6b / 6c EStG): a flat 1,260 EUR per year since 2023 (study without the centre of the work)
TC_ROOM = ((2023, Decimal(1260)), (0, Decimal(1250)))
# small business (section 19 UStG): the year before at most 25,000 EUR and the current year at most 100,000 EUR since 2025;
# before 2025: 22,000 EUR the year before (since 2020) and 50,000 EUR expected for the current year
TC_SMALL = ((2025, Decimal(25000), Decimal(100000)), (2020, Decimal(22000), Decimal(50000)), (0, Decimal(17500), Decimal(50000)))
# entertainment of business friends is only 70 % deductible (section 4 (5) no. 2 EStG); books.ofc_meals_euer does the split
# words of receipt categories (casefolded, free text: a hint, never a proof)
TC_MEALS_RE = re.compile(r"bewirt|restaurant|geschäftsessen|entertain|meal")
TC_GIFT_RE = re.compile(r"geschenk|präsent|gift|cadeau|regalo")
TC_CAR_RE = re.compile(r"kfz|auto|fahrzeug|pkw|tank|benzin|diesel|sprit|kraftstoff|werkstatt|car\b|fuel|vehicle")
TC_ROOM_RE = re.compile(r"arbeitszimmer|home.?office|homeoffice")
TC_EQUIP_RE = re.compile(r"computer|laptop|notebook|rechner|hardware|technik|kamera|camera|objektiv|möbel|gerät|equipment|"
                         r"ausstattung|tablet|handy|smartphone|monitor|drucker|maschine")
# a corporation draws up a balance sheet, no EUeR (section 4 (3) EStG is for those without bookkeeping duty)
TC_CORP_RE = re.compile(r"\b(gmbh|ug|ag|se|kgaa|eg)\b|haftungsbeschränkt|\bltd\b|\binc\b", re.I)

TC_GROUPS = (("match", N_("Comparison")), ("jumps", N_("Year before")), ("quota", N_("Quotas")), ("fields", N_("Checked fields")),
             ("receipts", N_("Receipts")), ("formal", N_("Formalities")))
TC_NOTE = N_("Red and yellow are hints: nothing is blocked and nothing is sent to ELSTER.")


def _by_year(table, year):
    return next(x for x in table if year >= x[0])


def _money_txt(v, cur):
    return pdf_money(money(v), calc_lang(lang()), cur)


def _pt(group, key, ampel, title, text, link, amount=None, details=()):
    return {"group": group, "punkt": key, "ampel": ampel, "title": tr(title), "text": text, "link": link,
            "amount": dstr(money(amount)) if amount is not None else None, "details": list(details)}


def _taxable(d):
    """(net, VAT) of the taxable income of a bk_euer: the groups vat<rate> with a rate above 0."""
    net = vat = Decimal(0)
    for r in d["income"]:
        if r["key"].startswith("vat") and dec(r["key"][3:] or 0) > 0:
            net, vat = net + dec(r["net"]), vat + dec(r["vat"])
    return net, vat


def _va_sums(vas):
    """(bases, tax) summed over advance returns (bk_ustva dicts): 81 + 86 + 35 and the tax of 19 % + 7 % + 36."""
    base = tax = Decimal(0)
    for v in vas:
        z = v["kz"]
        base += dec(z["81"]) + dec(z["86"]) + dec(z["35"])
        tax += dec(v["tax"]["19"]) + dec(v["tax"]["7"]) + dec(z["36"])
    return base, tax


def _amount_of(small):
    return (lambda r: dec(r["gross"])) if small else (lambda r: dec(r["net"]))


def tc_match(e, vas, mode, ust, cur):
    """The comparison of the EUeR income with the advance returns and with the annual VAT return."""
    out = []
    if e["small_business"]:
        out.append(_pt("match", "ustva", "green", N_("Advance VAT returns"), tr("Small business: no VAT returns to compare."), "#office/books/ustva"))
        return out
    net, vat = _taxable(e)
    soll = ust.get("basis") == "soll"
    why = tr("VAT on invoicing: invoices paid in another year than their date cause such a difference; please be able to explain it.") if soll else \
        tr("The figures were computed from the same payments; a difference means the data changed after the returns. Please compare with what you filed.")
    if mode in ("month", "quarter"):
        base, tax = _va_sums(vas)
        tol = TC_TOL_PERIOD * len(vas)
        diff, dvat = net - base, vat - tax
        if abs(diff) > tol or abs(dvat) > tol:
            out.append(_pt("match", "ustva", "red", N_("Advance VAT returns"),
                           tr("Taxable income of the income/expense statement {0}, sum of the advance returns {1}: difference {2}.",
                              _money_txt(net, cur), _money_txt(base, cur), _money_txt(diff, cur)) + " " + why, "#office/books/ustva", diff,
                           [tr("VAT: income/expense statement {0}, advance returns {1}", _money_txt(vat, cur), _money_txt(tax, cur))]))
        else:
            out.append(_pt("match", "ustva", "green", N_("Advance VAT returns"),
                           trn("The income/expense statement matches the {0} advance return of the year.",
                               "The income/expense statement matches the {0} advance returns of the year.", len(vas)), "#office/books/ustva"))
    elif mode == "year":
        out.append(_pt("match", "ustva", "green", N_("Advance VAT returns"), tr("Rhythm of the tax dates: yearly, no advance returns."), "setgo:biz-tax"))
    else:
        out.append(_pt("match", "ustva", "yellow", N_("Advance VAT returns"),
                       tr("No rhythm is set under tax dates: the advance returns cannot be compared."), "setgo:biz-tax"))
    if not ust.get("known"):
        out.append(_pt("match", "ust_year", "yellow", N_("Annual VAT return"), ust["notes"][0], "#office/books/taxforms/ust"))
        return out
    rows = {r["key"]: r for r in ust["rows"]}
    ybase = sum((dec(rows[k]["base"]) for k in ("b19", "b7", "bx") if k in rows), Decimal(0))
    ytax = dec(rows["sum_tax"]["amount"]) if "sum_tax" in rows else Decimal(0)
    diff, dvat = net - ybase, vat - ytax
    if abs(diff) > TC_TOL_PERIOD or abs(dvat) > TC_TOL_PERIOD:
        out.append(_pt("match", "ust_year", "red", N_("Annual VAT return"),
                       tr("Taxable income of the income/expense statement {0}, annual VAT return {1}: difference {2}.",
                          _money_txt(net, cur), _money_txt(ybase, cur), _money_txt(diff, cur)) + " " + why, "#office/books/taxforms/ust", diff,
                       [tr("VAT: income/expense statement {0}, annual VAT return {1}", _money_txt(vat, cur), _money_txt(ytax, cur))]))
    else:
        out.append(_pt("match", "ust_year", "green", N_("Annual VAT return"), tr("The income/expense statement matches the annual VAT return."),
                       "#office/books/taxforms/ust"))
    return out


def tc_jumps(e, p, cur):
    """Lines with a big change to the year before (TC_JUMP_PCT and TC_JUMP_EUR): yellow, "please be able to explain"."""
    small = e["small_business"]
    amt = _amount_of(small)
    if not (p["income"] or p["expenses"]):
        return [_pt("jumps", "jumps", "green", N_("Changes to the year before"), tr("No figures of the year before to compare."), "#office/books/taxforms/euer")]
    lines = [("i:" + r["key"], r["label"], amt(r)) for r in e["income"]] + [("e:" + r["key"], r["label"], amt(r)) for r in e["expenses"]]
    prev = {("i:" + r["key"]): amt(r) for r in p["income"]}
    prev.update({("e:" + r["key"]): amt(r) for r in p["expenses"]})
    names = {k: lb for k, lb, _v in lines}
    names.update({("i:" + r["key"]): r["label"] for r in p["income"]})
    names.update({("e:" + r["key"]): r["label"] for r in p["expenses"]})
    now = {k: v for k, _lb, v in lines}
    now["profit"], prev["profit"] = dec(e["profit"]), dec(p["profit"])
    names["profit"] = tr("Profit")
    hits = []
    for k in list(names):
        a, b = now.get(k, Decimal(0)), prev.get(k, Decimal(0))
        d = a - b
        if abs(d) < TC_JUMP_EUR:
            continue
        if b and abs(d) * 100 / abs(b) < TC_JUMP_PCT:
            continue
        pct = f"{int(round(d * 100 / abs(b))):+d} %" if b else tr("new|compared with the year before")
        hits.append((abs(d), tr("{0}: {1} → {2} ({3})", names[k], _money_txt(b, cur), _money_txt(a, cur), pct)))
    if not hits:
        return [_pt("jumps", "jumps", "green", N_("Changes to the year before"), tr("No line changed much compared with the year before."), "#office/books/taxforms/euer")]
    hits.sort(key=lambda x: -x[0])
    return [_pt("jumps", "jumps", "yellow", N_("Changes to the year before"),
                trn("{0} line changed a lot compared with the year before: please be able to explain it.",
                    "{0} lines changed a lot compared with the year before: please be able to explain them.", len(hits)),
                "#office/books/taxforms/euer", details=[h[1] for h in hits[:TC_JUMP_SHOW]])]


def _cat_sum(e, rx, small):
    amt = _amount_of(small)
    return sum((amt(r) for r in e["expenses"] if r["key"].startswith("c:") and rx.search(r["key"][2:])), Decimal(0))


def tc_quota(e, cur):
    """Quotas of the trade: hints only (yellow at most)."""
    small = e["small_business"]
    inc = dec(e["income_total"]["gross" if small else "net"])
    if inc <= 0:
        return [_pt("quota", "quota", "green", N_("Quotas"), tr("No income in the year: no quotas."), "#office/books")]
    exp = dec(e["expense_total"]["gross" if small else "net"])
    meals = sum((_amount_of(small)(r) for r in e["expenses"] if r["key"] == "m:"), Decimal(0)) + _cat_sum(e, TC_MEALS_RE, small)
    car = _cat_sum(e, TC_CAR_RE, small)
    q = lambda v: money(v * 100 / inc)  # noqa: E731
    det, hot = [], False
    for label, v, lim in ((tr("Expenses"), exp, TC_QUOTA_COST), (tr("Entertainment"), meals, TC_QUOTA_MEALS), (tr("Vehicle costs"), car, TC_QUOTA_CAR)):
        over = q(v) > lim
        hot |= over
        det.append(tr("{0}: {1} % of the income (usual up to {2} %)", label, dstr(q(v)), str(int(lim))))
    if hot:
        return [_pt("quota", "quota", "yellow", N_("Quotas"), tr("A share is above the usual: only a hint, the tax office may ask."), "#office/books", details=det)]
    return [_pt("quota", "quota", "green", N_("Quotas"), tr("The shares are in the usual range (only a hint)."), "#office/books", details=det)]


def tc_fields(c, oid, e, rcs, ykz, year, cur):
    """The fields the tax office looks at: entertainment 70 %, gifts, private use of a car, study, low-value assets, reverse charge."""
    small = e["small_business"]
    out = []
    # entertainment
    plain = [r for r in rcs if r["category"] and TC_MEALS_RE.search(r["category"].casefold())]
    if plain:
        out.append(_pt("fields", "meals", "yellow", N_("Entertainment 70 %"),
                       trn("{0} receipt in an entertainment category counts in full: only 70 % is deductible. Please enter it as an entertainment receipt.",
                           "{0} receipts in an entertainment category count in full: only 70 % is deductible. Please enter them as entertainment receipts.", len(plain)),
                       "#office/meals", details=[r["title"] for r in plain[:TC_JUMP_SHOW]]))
    elif e.get("meals"):
        out.append(_pt("fields", "meals", "green", N_("Entertainment 70 %"), tr("Entertainment receipts count with 70 %."), "#office/meals"))
    else:
        out.append(_pt("fields", "meals", "green", N_("Entertainment 70 %"), tr("No entertainment in the year."), "#office/meals"))
    # gifts above the limit (per receipt: Kalmido does not know the persons)
    glim = _by_year(TC_GIFT, year)[1]
    gifts = [r for r in rcs if r["category"] and TC_GIFT_RE.search(r["category"].casefold()) and (r["amount"] if small else r["net"]) > glim]
    if gifts:
        out.append(_pt("fields", "gifts", "yellow", N_("Gifts"),
                       trn("{0} gift receipt is above {1} per person: above the limit the gift is not deductible at all.",
                           "{0} gift receipts are above {1} per person: above the limit a gift is not deductible at all.", len(gifts), _money_txt(glim, cur)),
                       "#office/books/receipts", details=[r["title"] for r in gifts[:TC_JUMP_SHOW]]))
    else:
        out.append(_pt("fields", "gifts", "green", N_("Gifts"), tr("No gift receipt above {0}.", _money_txt(glim, cur)), "#office/books/receipts"))
    # vehicle: the private use is not booked in Kalmido
    car = _cat_sum(e, TC_CAR_RE, small)
    if car > 0:
        out.append(_pt("fields", "car", "yellow", N_("Private use of a car"),
                       tr("Vehicle costs {0}: the private use (1 % rule or logbook) is not booked in Kalmido. Please add it with the tax advisor.", _money_txt(car, cur)),
                       "#office/books"))
    else:
        out.append(_pt("fields", "car", "green", N_("Private use of a car"), tr("No vehicle costs in the year."), "#office/books"))
    # study / home office
    rlim = _by_year(TC_ROOM, year)[1]
    room = _cat_sum(e, TC_ROOM_RE, small)
    if room > rlim:
        out.append(_pt("fields", "room", "yellow", N_("Study / home office"),
                       tr("Study / home office {0}: the flat rate is {1} per year; more only with the centre of the work there.", _money_txt(room, cur), _money_txt(rlim, cur)),
                       "#office/books/receipts", room - rlim))
    else:
        out.append(_pt("fields", "room", "green", N_("Study / home office"),
                       tr("Study / home office {0} (flat rate up to {1}).", _money_txt(room, cur), _money_txt(rlim, cur)) if room else tr("No study costs in the year."),
                       "#office/books/receipts"))
    # low-value assets: a device receipt above the limit should be depreciated (office/assets.py)
    gwg = _by_year(TC_GWG, year)[1]
    linked = ast_afa_year(c, oid, year)["receipt_ids"]
    big = [r for r in rcs if r["category"] and TC_EQUIP_RE.search(r["category"].casefold()) and r["node_id"] not in linked
           and (r["amount"] if small else r["net"]) > gwg]
    if big:
        out.append(_pt("fields", "gwg", "yellow", N_("Depreciation and low-value assets"),
                       trn("{0} receipt for a device is above {1} net and counts in full: please enter the device under equipment so it is depreciated.",
                           "{0} receipts for devices are above {1} net and count in full: please enter the devices under equipment so they are depreciated.",
                           len(big), _money_txt(gwg, cur)), "#office/equipment", details=[r["title"] for r in big[:TC_JUMP_SHOW]]))
    else:
        out.append(_pt("fields", "gwg", "green", N_("Depreciation and low-value assets"), tr("No device receipt above {0} outside of the depreciation.", _money_txt(gwg, cur)),
                       "#office/equipment"))
    # reverse charge
    if not small:
        z = ykz or {}
        det = []
        if int(z.get("46") or 0) or int(z.get("84") or 0):
            det.append(tr("Receipts with reverse charge (section 13b): please enter them in the section 13b part of the annual return."))
        if int(z.get("21") or 0) or int(z.get("41") or 0):
            det.append(tr("Services / goods to businesses in the EU: the recapitulative statement (ZM) is due as well."))
        if det:
            out.append(_pt("fields", "reverse", "yellow", N_("Reverse charge"), " ".join(det), "#office/books/taxforms/ust"))
        else:
            out.append(_pt("fields", "reverse", "green", N_("Reverse charge"), tr("No reverse charge in the year."), "#office/books/taxforms/ust"))
    return out


def tc_bank(c, oid, year):
    """(open money in, open money out, bookings of the year) of the bank matching in year; None without a bank import."""
    from .bank import _tx_dec
    rows = c.execute("SELECT * FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND day>=? AND day<=?",
                     (oid, f"{year}-01-01", f"{year}-12-31")).fetchall()
    if not rows:
        return None
    o_in = o_out = 0
    for r in rows:
        if r["match_kind"]:
            continue
        t = _tx_dec(c, oid, r)
        if t["amount"] > 0:
            o_in += 1
        elif t["amount"] < 0:
            o_out += 1
    return o_in, o_out, len(rows)


def tc_receipts(c, uid, oid, e, rcs, year):
    """Bookings without a receipt, receipts without a booking, open bank bookings of the year."""
    out = []
    bank = tc_bank(c, oid, year) if ofr_allows(c, uid, oid, "bank", "view") else None
    no_rc = e.get("afa_no_receipt") or []
    det = [tr("Depreciated device without a receipt: {0}", x["name"]) for x in no_rc[:TC_JUMP_SHOW]]
    n = len(no_rc) + (bank[1] if bank else 0)
    if bank and bank[1]:
        det.insert(0, trn("{0} payment from the account without a receipt", "{0} payments from the account without a receipt", bank[1]))
    if n:
        out.append(_pt("receipts", "no_receipt", "yellow", N_("Bookings without a receipt"),
                       trn("{0} booking of the year has no receipt.", "{0} bookings of the year have no receipt.", n),
                       "#office/bank" if bank and bank[1] else "#office/equipment", details=det))
    else:
        out.append(_pt("receipts", "no_receipt", "green", N_("Bookings without a receipt"), tr("Every booking has a receipt."), "#office/bank"))
    if bank is None:
        out.append(_pt("receipts", "no_booking", "green", N_("Receipts without a booking"),
                       tr("No bank statement of the year imported: receipts cannot be compared with the account."), "#office/bank"))
    else:
        unpaid = [r for r in rcs if not r["paid_at"]]
        if unpaid:
            out.append(_pt("receipts", "no_booking", "yellow", N_("Receipts without a booking"),
                           trn("{0} receipt of the year is not matched with a bank booking.", "{0} receipts of the year are not matched with a bank booking.", len(unpaid)),
                           "#office/bank", details=[r["title"] for r in unpaid[:TC_JUMP_SHOW]]))
        else:
            out.append(_pt("receipts", "no_booking", "green", N_("Receipts without a booking"), tr("Every receipt is matched with a bank booking."), "#office/bank"))
        if bank[0]:
            out.append(_pt("receipts", "bank_open", "yellow", N_("Open bank bookings"),
                           trn("{0} payment received in the year is not matched: income may be missing.", "{0} payments received in the year are not matched: income may be missing.", bank[0]),
                           "#office/bank"))
        else:
            out.append(_pt("receipts", "bank_open", "green", N_("Open bank bookings"), tr("Every payment received is matched."), "#office/bank"))
    return out


def tc_formal(c, oid, e, p, year, gaps, cur):
    """Tax number, period, legal form / small business, missing details."""
    out = []
    co = ofx_company(c, oid)
    tn = (co.get("tax_number") or "").strip()
    if not tn:
        out.append(_pt("formal", "tax_number", "red", N_("Tax number"), tr("The tax number is missing in the company details."), "setgo:biz-company"))
    elif not rck_taxno_ok(tn):
        out.append(_pt("formal", "tax_number", "yellow", N_("Tax number"), tr("The tax number {0} does not look like a German tax number.", tn), "setgo:biz-company"))
    else:
        out.append(_pt("formal", "tax_number", "green", N_("Tax number"), tr("Tax number {0}", tn), "setgo:biz-company"))
    today = local_now().date()
    if year >= today.year:
        out.append(_pt("formal", "period", "yellow", N_("Period"), tr("The year {0} is not over yet: the figures can still change.", year), "#office/books/taxforms/euer"))
    elif year not in TF_EUER:
        out.append(_pt("formal", "period", "yellow", N_("Period"), tr("There is no line assignment for {0} in Kalmido yet.", year), "#office/books/taxforms/euer"))
    else:
        out.append(_pt("formal", "period", "green", N_("Period"), tr("Calendar year {0}", year),
                       "#office/books/taxforms/euer"))
    name = " ".join((co.get("name") or "", co.get("register_no") or ""))
    if TC_CORP_RE.search(name) or (co.get("register_no") or "").strip().upper().startswith("HRB"):
        out.append(_pt("formal", "legal_form", "red", N_("Legal form"),
                       tr("A corporation (e.g. GmbH, UG) draws up a balance sheet, no income/expense statement."), "setgo:biz-company"))
    elif e["small_business"]:
        _y0, lim_prev, lim_now = _by_year(TC_SMALL, year)
        now, prev = dec(e["income_total"]["gross"]), dec(p["income_total"]["gross"])
        if now > lim_now:
            out.append(_pt("formal", "legal_form", "red", N_("Small business"),
                           tr("Small business: income {0} is above {1} in the year itself.", _money_txt(now, cur), _money_txt(lim_now, cur)), "setgo:biz-tax", now - lim_now))
        elif prev > lim_prev:
            out.append(_pt("formal", "legal_form", "yellow", N_("Small business"),
                           tr("Small business: income of the year before {0} is above {1}.", _money_txt(prev, cur), _money_txt(lim_prev, cur)), "setgo:biz-tax", prev - lim_prev))
        else:
            out.append(_pt("formal", "legal_form", "green", N_("Small business"), tr("Small business: income within the limits ({0} / {1}).",
                                                                                        _money_txt(lim_prev, cur), _money_txt(lim_now, cur)), "setgo:biz-tax"))
    else:
        out.append(_pt("formal", "legal_form", "green", N_("Legal form"), tr("Sole proprietor or partnership: the income/expense statement fits."), "setgo:biz-company"))
    det = []
    if e.get("missing_vat"):
        det.append(trn("{0} receipt without VAT rate", "{0} receipts without VAT rate", e["missing_vat"]))
    if gaps.get("no_amount"):
        det.append(trn("{0} receipt without an amount", "{0} receipts without an amount", len(gaps["no_amount"])))
    if gaps.get("no_date"):
        det.append(trn("{0} receipt without a date", "{0} receipts without a date", len(gaps["no_date"])))
    if e.get("unrated"):
        det.append(tr("Receipts in {0} without an exchange rate", ", ".join(e["unrated"])))
    miss = [tr(x) for k, x in (("name", N_("Name")), ("street", N_("Street")), ("zip", N_("Postcode")), ("city", N_("City"))) if not (co.get(k) or "").strip()]
    if miss:
        det.append(tr("Company details missing: {0}", ", ".join(miss)))
    if det:
        out.append(_pt("formal", "details", "yellow", N_("Missing details"), tr("Some details are missing."), "#office/books/receipts", details=det))
    else:
        out.append(_pt("formal", "details", "green", N_("Missing details"), tr("No details are missing."), "#office/books/receipts"))
    return out


def tc_check(c, uid, oid, year):
    """The whole check of a year -> {year, currency, small_business, points, counts {green, yellow, red}, groups, notes}."""
    s = office_settings(c, oid)
    e = bk_euer(c, oid, year)
    p = bk_euer(c, oid, year - 1)
    cur = e["currency"]
    mode, vas = tf_periods(c, oid, year, s)
    yd = bk_ustva(c, oid, year, "y")  # once: the annual return (tf_ust) and the reverse charge fields (46 / 84 have no lines there)
    ust = tf_ust(c, oid, year, vas=vas, yd=yd)
    gaps = {}
    rcs = bk_receipts(c, oid, f"{year}-01-01", f"{year}-12-31", gaps=gaps)
    pts = (tc_match(e, vas, mode, ust, cur) + tc_jumps(e, p, cur) + tc_quota(e, cur) + tc_fields(c, oid, e, rcs, yd.get("kz"), year, cur)
           + tc_receipts(c, uid, oid, e, rcs, year) + tc_formal(c, oid, e, p, year, gaps, cur))
    counts = {k: sum(1 for x in pts if x["ampel"] == k) for k in ("green", "yellow", "red")}
    return {"year": year, "currency": cur, "small_business": e["small_business"], "points": pts, "counts": counts,
            "groups": [[k, tr(n)] for k, n in TC_GROUPS], "notes": [tr(BK_NOTE), tr(TC_NOTE)]}


@app.get("/api/office/books/taxcheck")
def tc_get():
    """?year=YYYY (default: the year before) -> tc_check. Office admin, the function books.vat_return (as the tax forms)."""
    c, uid, oid = _ctx()
    office_need_feature(c, oid, TF_FEATURE)
    y = request.args.get("year") or str(local_now().year - 1)
    return jsonify(tc_check(c, uid, oid, _year(y)))
