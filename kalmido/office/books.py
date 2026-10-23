"""2.90.0 A (#1921): bookkeeping light -- income/expense statement (EUeR), VAT return figures, tax reserve, receipt photo.

Self-employed people do the running bookkeeping in the office without a second tool. Deliberately NOT: sending to ELSTER,
payroll, tax advice -- every view carries the note "No tax advice; figures without guarantee." Admins of the office area
only (a personal office: its owner); agents and kids 403 (office_gate), office areas of others never (the area comes from
office_org, ids of other areas 404).

Sources (nothing is booked twice):
 - income = payments on invoices (office_payments, cash principle), the net part of each payment split by the document's
   tax lines; refunds paid on credit notes count negative; a foreign currency through the document's rate
 - expenses = receipts (documents of the office's documents space with a row in rc_receipts and an amount; the VAT rate
   from rc_receipts.vat_pct, unknown counts as 0 % input tax) on their payment day (paid_at, set by the bank
   reconciliation) or else their document date, and travel receipts (no input tax). Fixed costs and purchases are plans
   (and would double the receipts): not counted.
 - VAT return figures: "ist" (VAT on payment received, the payments of the period) or "soll" (VAT on invoicing: finalised
   invoices by their date, credit notes negative -- the same documents as the DATEV export); input tax from receipts by
   their document date."""
import csv
import io
import re
from datetime import date
from decimal import ROUND_DOWN, Decimal

from flask import Response, g, has_request_context, jsonify, request

from ..core.config import app
from ..core.db import db, local_now
from ..core.access import Denied
from ..core.i18n import N_, tr, lang
from ..core.errors import BadInput
from .calc import dec, dstr, money
from .model import ofx_name1, office_feature, office_gate, office_need_feature, office_org, office_settings, pb_owner

BK_NOTE = N_("No tax advice; figures without guarantee.")
BK_VAT = ("19", "7", "0")
PERIOD_RE = re.compile(r"^(m(0[1-9]|1[0-2])|q[1-4]|y)$")  # 2.122.0 D (#2315): y = the whole year
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BK_LIST_MAX = 500  # rows behind the VAT return figures / of the receipts list


from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


def _j(s):
    import json
    try:
        v = json.loads(s) if s else {}
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _year(v):
    y = str(v or "")
    if not y:
        return local_now().year
    if not (y.isdigit() and len(y) == 4 and 2000 <= int(y) <= local_now().year + 1):
        raise BadInput(tr("Invalid value: {0}", "year"))
    return int(y)


def bk_ws(c, oid):
    """The documents space of office area oid: 'u<owner>' for a personal office, 'o<oid>' for an organisation."""
    from ..docs.store import doc_ws
    owner = pb_owner(c, oid)
    return doc_ws(None, owner) if owner else doc_ws(oid, None)


def _home(s):
    return (s.get("currency") or "EUR").upper()


def bk_to_home(amount, cur, s):
    """A receipt amount in its currency -> the office currency (EUR <-> USD through the office rate fx_usd = USD per EUR;
    another or no currency counts as the office currency)."""
    home = _home(s)
    cur = {"€": "EUR", "$": "USD"}.get((cur or "").strip(), (cur or "").strip().upper()) or home
    if cur == home or cur not in ("EUR", "USD"):
        return amount
    fx = dec(s.get("fx_usd"), "1.09")
    fx = fx if fx > 0 else Decimal(1)
    return amount / fx if home == "EUR" else amount * fx


def _split(gross, pct):
    """(net, vat) of a gross amount at pct percent (None / "0" = no VAT)."""
    p = dec(pct or 0)
    if p <= 0:
        return money(gross), Decimal("0.00")
    net = money(gross * 100 / (100 + p))
    return net, money(gross) - net


def _uid_filter(uid):
    if uid is None and has_request_context() and getattr(g, "user", None) is not None:
        return g.user["id"]
    return uid


# ---------------------------------------------------------------- receipts (contract with part B)
def bk_receipts(c, oid, frm, to, uid=None, by="paid"):
    """The receipts of office area oid in [frm, to] (ISO days, both included) ->
    [{node_id, date, amount (Decimal gross, office currency), vat_pct, net, vat, category, title, paid_at, doc_date}].
    A receipt = a document of the office's documents space with a row in rc_receipts and an amount, not in the trash.
    by="paid": the day = paid_at, else the document date (cash principle, the EUeR); by="doc": the document date, else
    paid_at (input tax). uid: only documents this person sees (default: the signed-in person; 0 = all, for jobs)."""
    from ..docs.store import doc_open
    from ..files.store import fs_chain, fs_deleted, fs_role
    ws = bk_ws(c, oid)
    s = office_settings(c, oid)
    uid = _uid_filter(uid)
    day = "COALESCE(NULLIF(r.paid_at, ''), d.doc_date)" if by == "paid" else "COALESCE(NULLIF(d.doc_date, ''), NULLIF(r.paid_at, ''))"
    rows = c.execute(f"SELECT r.node_id, r.vat_pct, r.paid_at, r.category, d.doc_date, d.amount, d.currency, d.ws, n.name, "
                     f"{day} AS day FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id JOIN fs_nodes n ON n.id=r.node_id "
                     f"WHERE d.ws=? AND n.kind='file' AND n.deleted_at IS NULL AND {day}>=? AND {day}<=? ORDER BY {day}, r.node_id",
                     (ws, frm, to)).fetchall()
    out = []
    for r in rows:
        raw = doc_open(c, r["ws"], "doc_meta.amount", r["amount"]) or ""
        if not raw:
            continue
        a = dec(raw, "0")
        if a == 0:
            continue
        if fs_deleted(fs_chain(c, r["node_id"])):
            continue  # a folder above it is in the trash
        if uid and not fs_role(c, r["node_id"], uid):
            continue
        gross = money(bk_to_home(a, r["currency"], s))
        vat_pct = r["vat_pct"] if r["vat_pct"] in BK_VAT else None
        net, vat = _split(gross, vat_pct)
        out.append({"node_id": r["node_id"], "date": r["day"], "amount": gross, "vat_pct": vat_pct, "net": net, "vat": vat,
                    "category": r["category"] or "", "title": r["name"] or "", "paid_at": r["paid_at"], "doc_date": r["doc_date"]})
    return out


def bk_receipt_set_paid(c, oid, node_id, day):
    """Set (ISO day) or remove (None) the payment day of a receipt of office area oid; returns the previous value.
    404 when the document is no receipt of this area (or in the trash); BadInput on a wrong day."""
    if day not in (None, "") and not (isinstance(day, str) and DAY_RE.match(day)):
        raise BadInput(tr("Invalid value: {0}", "paid_at"))
    if day:
        try:
            date.fromisoformat(day)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "paid_at"))
    r = c.execute("SELECT r.paid_at FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id JOIN fs_nodes n ON n.id=r.node_id "
                  "WHERE r.node_id=? AND d.ws=? AND n.deleted_at IS NULL", (node_id, bk_ws(c, oid))).fetchone()
    if not r:
        raise Denied(404)
    from .periodlock import period_need_open
    period_need_open(c, oid, r["paid_at"], day)  # 2.148.0 A (#2471): a payment day in a locked month stays
    c.execute("UPDATE rc_receipts SET paid_at=? WHERE node_id=?", (day or None, node_id))
    return r["paid_at"]


# ---------------------------------------------------------------- income: the parts of a document
def _fx(r, home):
    """The rate of document row r to the office currency (amount / rate = office currency), as the cash flow."""
    if (r["currency"] or home) == home:
        return Decimal(1)
    fx = dec(r["fx_rate"], "1.09" if r["currency"] == "USD" else "1")
    return fx if fx > 0 else Decimal(1)


def bk_doc_parts(r):
    """[(group, share of the gross, pct)] of an invoice / credit note: a document without VAT by its note (small = small
    business, reverse = reverse charge to a business in the EU, abroad = not taxable domestically, else exempt); with VAT
    its tax lines (group "vat19" / "vat7" / "vat<pct>", 0 % = exempt), shares by each line's gross."""
    if (r["vat_mode"] or "vat") == "novat":
        note = (r["vat_note"] if "vat_note" in r.keys() else "") or ""
        return [(note if note in ("small", "reverse", "abroad") else "exempt", Decimal(1), Decimal(0))]
    lines = []
    for tl in _j(r["totals"]).get("tax_lines") or []:
        lg = dec(tl.get("base") or 0) + dec(tl.get("amount") or 0)
        pct = dec(tl.get("pct") or 0).normalize()
        lines.append(("vat" + format(pct, "f") if pct > 0 else "exempt", lg, pct))
    tot = sum((x[1] for x in lines), Decimal(0))
    if not lines or tot == 0:
        return [("exempt", Decimal(1), Decimal(0))]
    return [(k, lg / tot, pct) for k, lg, pct in lines]


def _income_label(key):
    if key.startswith("vat"):
        return tr("Revenue {0} % VAT", key[3:])
    return {"small": tr("Revenue (small business)"), "reverse": tr("Tax-free revenue / reverse charge"),
            "abroad": tr("Tax-free revenue / reverse charge"), "exempt": tr("Tax-free revenue / reverse charge")}[key]


def bk_payments(c, oid, frm, to, home):
    """[(payment row, document row)] of invoices / credit notes paid in [frm, to] (ISO days, both included)."""
    # 2.144.10 B (#2576): trial documents never reach the books
    docs = {r["id"]: r for r in c.execute("SELECT * FROM office_docs WHERE org_id=? AND kind IN ('invoice', 'credit') AND trial=0",
                                          (oid,))}
    out = []
    for p in c.execute("SELECT id, doc_id, date, amount FROM office_payments WHERE org_id=? AND date>=? AND date<=? ORDER BY date, id",
                       (oid, frm, to)):
        r = docs.get(p["doc_id"])
        if r is not None and p["date"]:
            out.append((p, r))
    return out


def _pay_parts(p, r, home):
    """[(group, gross, net, vat)] of one payment in the office currency (a refund on a credit note negative)."""
    a = dec(p["amount"]) / _fx(r, home)
    if r["kind"] == "credit":
        a = -a
    out = []
    for k, share, pct in bk_doc_parts(r):
        part = a * share
        net = part * 100 / (100 + pct) if pct > 0 else part
        out.append((k, part, net, part - net))
    return out


# ---------------------------------------------------------------- EUeR
def bk_euer(c, oid, year):
    """The income / expense statement of a year (see the module text); amounts as text with two decimals."""
    from .travel import rk_cat_label, rk_trips
    s = office_settings(c, oid)
    home = _home(s)
    small = bool(s.get("small_business"))
    y0, y1 = f"{year}-01-01", f"{year}-12-31"
    inc = {}
    for p, r in bk_payments(c, oid, y0, y1, home):
        for k, gross, net, vat in _pay_parts(p, r, home):
            k = "exempt" if k in ("reverse", "abroad") else k
            x = inc.setdefault(k, [Decimal(0)] * 3)
            x[0], x[1], x[2] = x[0] + net, x[1] + vat, x[2] + gross
    exp, missing = {}, 0
    # 2.92.0 (#1931): equipment with a purchase price is depreciated (office/assets.py ast_afa_year): the year's depreciation
    # is an expense of its own, the device's receipt counts only with its input tax (else the purchase would count twice).
    # A small business keeps the receipt as it is (its depreciation basis would be the gross price, assets.py works net)
    afa = {"rows": [], "receipt_ids": set()}
    if not small:
        from .assets import ast_afa_year
        afa = ast_afa_year(c, oid, year)
    for rc in bk_receipts(c, oid, y0, y1):
        k = "c:" + rc["category"].casefold() if rc["category"] else "c:"
        x = exp.setdefault(k, {"label": rc["category"] or tr("Other"), "v": [Decimal(0)] * 3, "count": 0})
        if rc["node_id"] in afa["receipt_ids"]:
            x["v"] = [x["v"][0], x["v"][1] + rc["vat"], x["v"][2] + rc["vat"]]
        else:
            x["v"] = [x["v"][0] + rc["net"], x["v"][1] + rc["vat"], x["v"][2] + rc["amount"]]
        x["count"] += 1
        if rc["vat_pct"] is None:
            missing += 1
    for a_ in afa["rows"]:
        x = exp.setdefault("a:", {"label": tr("Depreciation"), "v": [Decimal(0)] * 3, "count": 0})
        x["v"] = [x["v"][0] + a_["amount"], x["v"][1], x["v"][2] + a_["amount"]]
        x["count"] += 1
    for t in rk_trips(c, oid, year=str(year)):
        for it in t["items"]:
            day = it["date"] or t["date_from"] or ""
            if not (y0 <= day <= y1):
                continue
            a = dec(it["amount_home"] or 0)
            x = exp.setdefault("t:" + (it["category"] or "other"), {"label": tr("Travel expenses") + ": " + rk_cat_label(it["category"] or "other"),
                                                                    "v": [Decimal(0)] * 3, "count": 0})
            x["v"] = [x["v"][0] + a, x["v"][1], x["v"][2] + a]  # travel receipts carry no input tax here
            x["count"] += 1
    # 2.93.0 B (#1928): the mileage allowance of the logbook (business drives with a private car; no input tax)
    from .logbook import lb_allowance_year
    km = lb_allowance_year(c, oid, year)
    if km["count"]:
        exp["km"] = {"label": tr("Mileage allowance"), "v": [km["amount"], Decimal(0), km["amount"]], "count": km["count"]}
    m2 = lambda v: dstr(money(v))  # noqa: E731
    order = lambda k: (0, -int(dec(k[3:]))) if k.startswith("vat") else (1 if k == "exempt" else 2, 0)  # noqa: E731
    income = [{"key": k, "label": _income_label(k), "net": m2(v[0]), "vat": m2(v[1]), "gross": m2(v[2])}
              for k, v in sorted(inc.items(), key=lambda kv: order(kv[0]))]
    expenses = [{"key": k, "label": x["label"], "net": m2(x["v"][0]), "vat": m2(x["v"][1]), "gross": m2(x["v"][2]), "count": x["count"]}
                for k, x in sorted(exp.items(), key=lambda kv: (kv[0] == "km", kv[0][:2] == "t:", kv[0] == "c:", kv[1]["label"].casefold()))]
    from .catacct import ca_euer
    expenses = ca_euer(c, oid, expenses)  # 2.121.0 (#2093): the account of each receipt category line
    tot = lambda rows, f: sum((dec(r[f]) for r in rows), Decimal(0))  # noqa: E731
    i_net, i_gross = tot(income, "net"), tot(income, "gross")
    e_net, e_gross = tot(expenses, "net"), tot(expenses, "gross")
    # a small business deducts no input tax: its expenses count gross (its income has no VAT: net = gross)
    profit = (i_gross - e_gross) if small else (i_net - e_net)
    pct = int(s.get("tax_reserve_pct") or 0)
    return {"year": year, "currency": home, "small_business": small, "income": income, "expenses": expenses,
            "income_total": {"net": m2(i_net), "vat": m2(tot(income, "vat")), "gross": m2(i_gross)},
            "expense_total": {"net": m2(e_net), "vat": m2(tot(expenses, "vat")), "gross": m2(e_gross)},
            "profit": m2(profit), "missing_vat": 0 if small else missing, "tax_reserve_pct": pct,
            "tax_reserve": m2(profit * pct / 100) if pct and profit > 0 else "0.00",
            "notes": [tr(BK_NOTE), tr("Income = payments received (cash principle); expenses = receipts and travel expenses.")]
            + ([tr("Mileage allowance from the logbook (business drives with a private car).")] if km["count"] else [])}


# ---------------------------------------------------------------- VAT return figures
def bk_period(year, period):
    """(first day, last day) of a period m01..m12 | q1..q4 | y."""
    if not PERIOD_RE.match(period or ""):
        raise BadInput(tr("Invalid value: {0}", "period"))
    if period == "y":
        m0, m1 = 1, 12
    elif period[0] == "m":
        m0 = m1 = int(period[1:])
    else:
        m0 = (int(period[1]) - 1) * 3 + 1
        m1 = m0 + 2
    last = (date(year + (m1 == 12), m1 % 12 + 1, 1) - date.resolution).isoformat()
    return f"{year}-{m0:02d}-01", last


def _euro_floor(v):
    """A tax base as the form wants it: whole euros, cents cut off."""
    return money(v).quantize(Decimal(1), rounding=ROUND_DOWN)  # cents first: 999.99999... of a split payment is 1000


def bk_ustva(c, oid, year, period):
    """The figures of the German VAT return (UStVA) of a period to type into ELSTER. Field numbers (Kennzahlen):
    81 = base of the sales at 19 %, 86 = at 7 %, 35 / 36 = base / tax at other rates; 21 = services to businesses in the EU
    with reverse charge (vat_note "reverse", section 18b UStG -- Kalmido documents are services; deliveries of goods to the
    EU would be field 41, which Kalmido cannot tell apart, so 41 stays empty); 45 = other sales not taxable domestically
    (vat_note "abroad", e.g. services to a third country); 66 = input tax from receipts with a VAT rate; 83 = the advance
    payment (VAT minus input tax; negative = a refund). Bases in whole euros (cut off), taxes in cents computed from the
    bases as ELSTER does. Other tax-free sales (no note) are listed apart, without a field (to check)."""
    s = office_settings(c, oid)
    home = _home(s)
    frm, to = bk_period(year, period)
    basis = s.get("vat_basis") if s.get("vat_basis") in ("ist", "soll") else "ist"
    head = {"year": year, "period": period, "from": frm, "to": to, "basis": basis, "currency": home, "note": tr(BK_NOTE)}
    if s.get("small_business"):
        return dict(head, small_business=True)
    sums, items = {}, []

    def add(k, net, vat):
        x = sums.setdefault(k, [Decimal(0), Decimal(0)])
        x[0], x[1] = x[0] + net, x[1] + vat

    if basis == "ist":
        for p, r in bk_payments(c, oid, frm, to, home):
            gross_all = Decimal(0)
            for k, gross, net, vat in _pay_parts(p, r, home):
                add(k, net, vat)
                gross_all += gross
            items.append({"kind": r["kind"], "doc_id": r["id"], "number": r["number"], "date": p["date"], "gross": dstr(money(gross_all)),
                          "source": "payment"})
    else:
        for r in c.execute("SELECT * FROM office_docs WHERE org_id=? AND kind IN ('invoice','credit') AND locked_at IS NOT NULL "
                           "AND trial=0 AND number != '' AND date>=? AND date<=? ORDER BY date, number", (oid, frm, to)).fetchall():
            t = _j(r["totals"])
            fx, sign = _fx(r, home), (-1 if r["kind"] == "credit" else 1)
            gross = dec(t.get("gross") or 0) / fx * sign
            for k, share, pct in bk_doc_parts(r):
                part = gross * share
                net = part * 100 / (100 + pct) if pct > 0 else part
                add(k, net, part - net)
            items.append({"kind": r["kind"], "doc_id": r["id"], "number": r["number"], "date": r["date"], "gross": dstr(money(gross)),
                          "source": "document"})
    kz66, missing = Decimal(0), 0
    for rc in bk_receipts(c, oid, frm, to, by="doc"):
        kz66 += rc["vat"]
        missing += rc["vat_pct"] is None
        items.append({"kind": "receipt", "node_id": rc["node_id"], "title": rc["title"], "date": rc["date"], "gross": dstr(rc["amount"]),
                      "vat": dstr(rc["vat"]), "vat_pct": rc["vat_pct"]})
    b = lambda k: sums.get(k, [Decimal(0)] * 2)[0]  # noqa: E731
    kz81, kz86 = _euro_floor(b("vat19")), _euro_floor(b("vat7"))
    others = [k for k in sums if k.startswith("vat") and k not in ("vat19", "vat7")]
    kz35 = _euro_floor(sum((b(k) for k in others), Decimal(0)))
    kz36 = money(sum((sums[k][1] for k in others), Decimal(0)))  # mixed rates: the tax itself, not computed from the base
    t19, t7 = money(kz81 * 19 / 100), money(kz86 * 7 / 100)
    kz66 = money(kz66)
    kz83 = t19 + t7 + kz36 - kz66
    e = lambda v: str(int(v))  # noqa: E731 -- bases: whole euros
    kz = {"81": e(kz81), "86": e(kz86), "35": e(kz35), "36": dstr(kz36), "21": e(_euro_floor(b("reverse"))),
          "41": "0", "45": e(_euro_floor(b("abroad"))), "66": dstr(kz66), "83": dstr(kz83)}
    return dict(head, small_business=False, kz=kz, tax={"19": dstr(t19), "7": dstr(t7)},
                exempt_other=dstr(money(b("exempt"))), missing_vat=missing, items=items[:BK_LIST_MAX], items_more=len(items) > BK_LIST_MAX)


# ---------------------------------------------------------------- routes
def _rc_public(rc):
    return {"node_id": rc["node_id"], "title": rc["title"], "date": rc["date"], "amount": dstr(rc["amount"]), "vat_pct": rc["vat_pct"],
            "net": dstr(rc["net"]), "vat": dstr(rc["vat"]), "category": rc["category"], "paid_at": rc["paid_at"]}


@app.get("/api/office/books")
def bk_get():
    """?month=YYYY-MM (default: this one)&year=YYYY -> {upload_ws (the documents space for POST /api/docs: private | org:<id>),
    categories, currency, small_business, receipts (of the month), missing (receipts of the year without a VAT rate), note}."""
    from ..receipts.suggest import rc_categories
    c, uid, oid = _ctx()
    year = _year(request.args.get("year"))
    mo = request.args.get("month") or local_now().date().isoformat()[:7]
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mo):
        raise BadInput(tr("Invalid value: {0}", "month"))
    s = office_settings(c, oid)
    ws = bk_ws(c, oid)
    m_from, m_to = bk_period(int(mo[:4]), "m" + mo[5:])
    month = [_rc_public(x) for x in bk_receipts(c, oid, m_from, m_to)][-BK_LIST_MAX:]
    missing = [_rc_public(x) for x in bk_receipts(c, oid, f"{year}-01-01", f"{year}-12-31") if x["vat_pct"] is None][:BK_LIST_MAX]
    from ..docs.dups import dup_seen
    dups = dup_seen(c, {x["node_id"] for x in month + missing}, uid)  # 2.185.0 A (#2583): marked in the list, still counted
    for x in month + missing:
        x["dup"] = x["node_id"] in dups
    from .catacct import ca_accounts
    cats = rc_categories(c, ws)
    return jsonify(upload_ws="private" if ws[0] == "u" else f"org:{oid}", categories=cats, currency=_home(s),
                   # 2.121.0 (#2093): SKR03 / SKR04 account per category (None: no DATEV input side; 2.147.0 (#2460): or DATEV off)
                   accounts=ca_accounts(c, oid, cats) if office_feature(c, oid, "books.datev", s) else None,
                   small_business=bool(s.get("small_business")), month=mo, receipts=month, year=year,
                   missing=[] if s.get("small_business") else missing, note=tr(BK_NOTE))


@app.get("/api/office/books/euer")
def bk_euer_get():
    """?year=YYYY (default: this one) -> bk_euer."""
    c, uid, oid = _ctx()
    return jsonify(bk_euer(c, oid, _year(request.args.get("year"))))


@app.get("/api/office/books/ustva")
def bk_ustva_get():
    """?year=YYYY&period=m01..m12|q1..q4|y -> bk_ustva."""
    c, uid, oid = _ctx()
    office_need_feature(c, oid, "books.vat_return")  # 2.147.0 (#2459, #2460)
    return jsonify(bk_ustva(c, oid, _year(request.args.get("year")), request.args.get("period") or ""))


def bk_csv_cell(v):
    """A text cell safe against formula injection in spreadsheets (as the time export)."""
    from ..core.serializers import csv_cell  # 2.122.4 B (#2317): one shared helper
    return csv_cell(v)


def _de(v):
    return str(v).replace(".", ",")


@app.get("/api/office/books/euer.csv")
def bk_euer_csv():
    """?year=YYYY -> the EUeR as CSV (semicolon, decimal comma: German spreadsheets): group;net;VAT;gross."""
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    d = bk_euer(c, oid, _year(request.args.get("year")))
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow([tr("Group"), tr("Net"), tr("VAT"), tr("Gross")])
    for title, rows, tot in ((tr("Income"), d["income"], d["income_total"]), (tr("Expenses"), d["expenses"], d["expense_total"])):
        w.writerow([bk_csv_cell(title), "", "", ""])
        for r in rows:
            w.writerow([bk_csv_cell(r["label"]), _de(r["net"]), _de(r["vat"]), _de(r["gross"])])
        w.writerow([bk_csv_cell(tr("Total")), _de(tot["net"]), _de(tot["vat"]), _de(tot["gross"])])
    w.writerow([bk_csv_cell(tr("Profit")), _de(d["profit"]), "", ""])
    w.writerow([bk_csv_cell(tr(BK_NOTE)), "", "", ""])
    ofx_log(c, oid, "export", target="books", detail={"what": "euer.csv", "year": d["year"]})
    c.commit()
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="euer-{d["year"]}.csv"', "Cache-Control": "no-store"})


def bk_euer_pdf_bytes(c, oid, d, lang):
    """A plain A4 PDF of the EUeR: company and year, the two tables with sums, the profit and the note."""
    from .ledger import ofx_company
    from .pdf import A4_H, A4_W, C_INK2, C_RULE, _Page, pdf_money, pdf_write
    s = office_settings(c, oid)
    company = ofx_name1(ofx_company(c, oid).get("name") or (s.get("company") or {}).get("name"))  # 2.99.0 D (#2188): one line
    cur = d["currency"]
    lg = "de" if lang == "de" else "en"
    m = lambda v: pdf_money(v, lg, cur)  # noqa: E731
    x0, x1 = 56, A4_W - 56
    cols = [x1 - 230, x1 - 140, x1 - 50]  # right edges of net / VAT / gross minus their width
    pages, pg = [], None
    y = 0

    def page():
        nonlocal pg, y
        pg = _Page()
        pages.append(pg)
        y = 56

    def need(h):
        if pg is None or y + h > A4_H - 56:
            page()

    page()
    if company:
        pg.text(x0, y, company, 10, color=C_INK2)
        y += 18
    pg.text(x0, y, tr("Income/expense statement {0}", d["year"]), 16, bold=True)
    y += 30

    def table(title, rows, tot):
        nonlocal y
        need(60)
        pg.text(x0, y, title, 11, bold=True)
        for i, h in enumerate((tr("Net"), tr("VAT"), tr("Gross"))):
            pg.text(cols[i], y, h, 9, color=C_INK2, align="r", width=80)
        y += 16
        pg.line(x0, y, x1, y, color=C_RULE)
        y += 5
        for r in rows or [{"label": tr("None"), "net": "0", "vat": "0", "gross": "0"}]:
            need(16)
            pg.text(x0, y, str(r["label"])[:70], 9)
            for i, f in enumerate(("net", "vat", "gross")):
                pg.text(cols[i], y, m(r[f]), 9, align="r", width=80)
            y += 14
        pg.line(x0, y, x1, y, color=C_RULE)
        y += 5
        pg.text(x0, y, tr("Total"), 9, bold=True)
        for i, f in enumerate(("net", "vat", "gross")):
            pg.text(cols[i], y, m(tot[f]), 9, bold=True, align="r", width=80)
        y += 28

    table(tr("Income"), d["income"], d["income_total"])
    table(tr("Expenses"), d["expenses"], d["expense_total"])
    need(60)
    pg.text(x0, y, tr("Profit"), 12, bold=True)
    pg.text(cols[2], y, m(d["profit"]), 12, bold=True, align="r", width=80)
    y += 26
    for n in d["notes"]:
        need(30)
        y += pg.para(x0, y, n, 8, x1 - x0, color=C_INK2) + 4
    return pdf_write(pages, {}, title=tr("Income/expense statement {0}", d["year"]), author=company)


@app.get("/api/office/books/euer.pdf")
def bk_euer_pdf():
    """?year=YYYY -> the EUeR as PDF."""
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    d = bk_euer(c, oid, _year(request.args.get("year")))
    data = bk_euer_pdf_bytes(c, oid, d, lang())
    ofx_log(c, oid, "export", target="books", detail={"what": "euer.pdf", "year": d["year"]})
    c.commit()
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="euer-{d["year"]}.pdf"', "Cache-Control": "no-store"})
