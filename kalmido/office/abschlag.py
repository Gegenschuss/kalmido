"""2.120.0 A (#2087): progress and final invoices, cash discount (Skonto).

Both are plain invoices (kind invoice, the invoice number series) with office_docs.inv_type '' | 'progress' | 'final':
- progress ("Abschlagsrechnung"): from a quotation (source_doc_id) an amount or a percentage of its net, split onto the
  quotation's tax rates in proportion (one position per rate, "Progress invoice no. n on quotation X"); e-invoice type 326.
- final ("Schlussrechnung"): the quotation's full positions, then one negative position (kind discount) per earlier
  progress invoice and tax rate (finalised, not cancelled; office_docs.abs_refs = their ids). The deduction as negative
  lines keeps the tax per rate right in the e-invoice (BT-113 prepaid would deduct gross without tax); type 380.
  Finalising checks that the progress invoices are still the same (one cancelled or a new one = draft it anew).
- Skonto: office_docs.skonto_pct / skonto_days per invoice (default from the office settings, empty = none). The PDF
  prints the line under the payment terms, the e-invoice carries the XRechnung line #SKONTO#TAGE=n#PROZENT=p.pp# in BT-20.
  Payments dated within the period that reach gross - discount (with credit notes) make the invoice paid.
Without inv_type / skonto (old documents) nothing changes."""
import json
from datetime import date, timedelta
from decimal import Decimal

from flask import jsonify

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..core.errors import BadInput
from .calc import TAX_KEYS, dec, dstr, fmt_money, inv_calc, money

ABS_TYPES = ("", "progress", "final")
ABS_TYPE_CODE = {"progress": "326", "final": "380"}  # UNTDID 1001: 326 partial invoice (XRechnung + EN 16931 accept it)
# 2.149.0 A (#2520): the documents' words through tr() in the document's language (placeholders {name} filled by _t)
ABS_TITLE = {"progress": N_("Progress invoice|document"), "final": N_("Final invoice|document")}
ABS_TXT = {
    "progress": N_("Progress payment no. {n} on quotation {num}|document"),
    "share": N_("Share at {pct} % VAT|document"),
    "share_of": N_("{p} % of the quotation's net|document"),
    "heading": N_("Less progress invoices already issued|document"),
    "deduct": N_("Less progress invoice no. {num} of {date}|document"),
    "deduct_detail": N_("Net {net}, VAT {pct} % {tax}, gross {gross}{paid}|document"),
    "paid": N_(" (paid)|document"),
    "open": N_(" (open)|document"),
    "rest": N_("Amount remaining|document"),
    "skonto": N_("When paid by {date} {pct} % cash discount (= {amt}), payable {pay}.|document"),
}


def _j(s, default):
    try:
        v = json.loads(s) if s else default
    except ValueError:
        return default
    return v if isinstance(v, type(default)) else default


def _col(r, k, default=None):
    return r[k] if r is not None and k in r.keys() and r[k] is not None else default


def _t(key, lang, **kw):
    from .doclang import doc_lg
    s = tr(ABS_TXT[key], lg=doc_lg(lang))
    for k, v in kw.items():
        s = s.replace("{" + k + "}", str(v))
    return s


def _pct_text(v, lang):
    q = dec(v).quantize(Decimal("0.01"))
    s = format(q.normalize(), "f") if q == q.to_integral() else format(q, "f")
    return s.replace(".", ",") if lang == "de" else s


# ---------------------------------------------------------------- skonto
def abs_skonto(r):
    """(pct Decimal, days int) of an invoice row, or None without cash discount."""
    if r is None or r["kind"] != "invoice":
        return None
    pct, days = dec(_col(r, "skonto_pct") or 0), _col(r, "skonto_days")
    if pct <= 0 or days is None or int(days) <= 0:
        return None
    return pct, int(days)


def abs_skonto_numbers(r, gross):
    """{pct, days, deadline, amount, payable} (Decimal / ISO date) of an invoice with cash discount, else None."""
    sk = abs_skonto(r)
    if sk is None or not r["date"]:
        return None
    pct, days = sk
    gross = money(dec(gross))
    amt = money(gross * pct / 100)
    return {"pct": pct, "days": days, "deadline": (date.fromisoformat(r["date"]) + timedelta(days=days)).isoformat(), "amount": amt, "payable": gross - amt}


def abs_skonto_covered(c, oid, r, credits):
    """True when the payments dated within the cash discount period plus the credit notes reach gross - discount."""
    sk = abs_skonto_numbers(r, _j(r["totals"], {}).get("gross") or 0)
    if sk is None:
        return False
    row = c.execute("SELECT SUM(amount) AS s FROM office_payments WHERE org_id=? AND doc_id=? AND date<>'' AND date<=?",
                    (oid, r["id"], sk["deadline"])).fetchone()
    paid = money(dec(row["s"] if row and row["s"] is not None else 0))
    return paid > 0 and paid + credits >= sk["payable"]


def abs_skonto_bt20(r):
    """The XRechnung cash discount line of BT-20 (with its closing line break) or ''."""
    sk = abs_skonto(r)
    if sk is None:
        return ""
    return f"#SKONTO#TAGE={sk[1]}#PROZENT={sk[0].quantize(Decimal('0.01'))}#\n"


def abs_new_row(s, row, kind):
    """The office settings' cash discount on a new invoice draft (row of invoices.inv_new_row)."""
    if kind != "invoice":
        return
    pct, days = dec(s.get("skonto_pct") or 0), int(s.get("skonto_days") or 0)
    if pct > 0 and days > 0:
        row["skonto_pct"], row["skonto_days"] = float(pct), days


def abs_clean(b, cur, f):
    """The head fields of this module from body b (docs.clean_doc) -- invoices only, others ignore them."""
    if cur["kind"] != "invoice":
        return
    from .docs import _num
    if "skonto_pct" in b:
        v = _num(b.get("skonto_pct"), "skonto_pct", 0, 99.99)
        f["skonto_pct"] = None if not v else round(float(v), 2)
    if "skonto_days" in b:
        v = _num(b.get("skonto_days"), "skonto_days", 0, 365)
        f["skonto_days"] = None if not v else int(v)
    if "inv_type" in b:
        v = b.get("inv_type") or ""
        if v not in ABS_TYPES:
            raise BadInput(tr("Invalid value: {0}", "inv_type"))
        f["inv_type"] = v


def abs_settings_clean(k, v, out):
    """office settings skonto_pct / skonto_days (model.office_settings_clean); True when k is one of them."""
    from .model import _num
    if k == "skonto_pct":
        out[k] = round(_num(v, k, 0, 99.99), 2) if v not in (None, "") else 0
    elif k == "skonto_days":
        out[k] = int(_num(v, k, 0, 365)) if v not in (None, "") else 0
    else:
        return False
    return True


# ---------------------------------------------------------------- progress / final invoices
def _bases(lines):
    """{tax key: net Decimal} of calculator lines (positions and discounts)."""
    out = {}
    for ln in lines or []:
        if ln.get("kind") in ("item", "discount") and ln.get("tax") in TAX_KEYS:
            out[ln["tax"]] = out.get(ln["tax"], Decimal(0)) + dec(ln.get("net") or ln.get("total") or 0)
    return out


def _eur_bases(items, pack):
    """{tax key: net in EUR} of position rows (rates are stored in EUR)."""
    return _bases(inv_calc({"currency": "EUR", "vat_mode": "vat"}, items, pack)["lines"])


def abs_progress_of(c, oid, offer_id, locked_only=False):
    """The progress invoices of quotation offer_id (not cancelled), oldest first."""
    q = " AND locked_at IS NOT NULL" if locked_only else ""
    # 2.144.10 B (#2576): only invoices of the quotation's own kind count (a real chain never counts trial ones, a trial chain in itself)
    return c.execute("SELECT * FROM office_docs WHERE org_id=? AND kind='invoice' AND inv_type='progress' AND source_doc_id=? AND status<>'cancelled'"
                     + q + " AND trial=(SELECT COALESCE(MAX(o.trial), 0) FROM office_docs o WHERE o.id=? AND o.org_id=?) ORDER BY date, id",
                     (oid, offer_id, offer_id, oid)).fetchall()


def _pack(c, oid):
    from .model import office_settings
    from .packs import office_pack_for
    s = office_settings(c, oid)
    return s, office_pack_for(s)


def abs_offer_info(c, oid, offer):
    """{net, progress: [...], billed, remaining} of a quotation (net in EUR, as the invoices' rates)."""
    from .docs import doc_items
    from .invoices import inv_items_from_offer, inv_money_fields, inv_paid_map
    s, pack = _pack(c, oid)
    net = sum(_eur_bases(inv_items_from_offer(c, oid, offer), pack).values(), Decimal(0))
    rows = abs_progress_of(c, oid, offer["id"])
    pm = inv_paid_map(c, oid, [x["id"] for x in rows])
    out, billed = [], Decimal(0)
    for x in rows:
        pn = sum(_eur_bases(doc_items(c, x["id"], oid), pack).values(), Decimal(0))
        billed += pn
        t = _j(x["totals"], {})
        out.append({"id": x["id"], "number": x["number"], "date": x["date"], "status": x["status"], "locked": bool(x["locked_at"]),
                    "net_eur": dstr(pn), "gross": t.get("gross") or "0.00", "gross_text": fmt_money(t.get("gross") or 0, x["lang"], x["currency"]),
                    **inv_money_fields(x, pm)})
        out[-1]["open_text"] = fmt_money(out[-1]["open"], x["lang"], x["currency"])  # 2.123.0 (#2351): German number format
    return {"net": dstr(net), "net_text": fmt_money(net, offer["lang"], "EUR"), "progress": out, "billed": dstr(billed),
            "remaining": dstr(net - billed), "remaining_text": fmt_money(net - billed, offer["lang"], "EUR")}


def abs_final_done(c, oid, offer_id, but=None):
    """2.120.0 (review M3): a finalised, not cancelled final invoice of quotation offer_id exists (other than id but) --
    then no second final invoice and no further progress invoice."""
    r = c.execute("SELECT id FROM office_docs WHERE org_id=? AND kind='invoice' AND inv_type='final' AND source_doc_id=? AND id<>? "
                  "AND locked_at IS NOT NULL AND locked_at<>'' AND status NOT IN ('draft', 'cancelled') "
                  "AND trial=(SELECT COALESCE(MAX(o.trial), 0) FROM office_docs o WHERE o.id=? AND o.org_id=?) LIMIT 1",  # 2.144.10 B (#2576)
                  (oid, offer_id, but or 0, offer_id, oid)).fetchone()
    if r:
        raise BadInput(tr("The quotation already has a final invoice"))


def abs_progress(c, oid, uid, offer, amount=None, pct=None):
    """A progress invoice draft from quotation offer: amount (net, in the document's currency) or pct of the quotation's
    net, split onto its tax rates in proportion. -> new id."""
    from .invoices import _insert_doc, _put_rows, inv_items_from_offer, inv_new_row
    abs_final_done(c, oid, offer["id"])
    s, pack = _pack(c, oid)
    bases = {k: v for k, v in _eur_bases(inv_items_from_offer(c, oid, offer), pack).items() if v != 0}
    net = sum(bases.values(), Decimal(0))
    if net <= 0:
        raise BadInput(tr("The quotation has no net amount to bill"))
    info = abs_offer_info(c, oid, offer)
    lang = offer["lang"]
    if pct not in (None, ""):
        p = dec(pct, "NaN")
        if p.is_nan() or p <= 0 or p > 100:
            raise BadInput(tr("Invalid value: {0}", "pct"))
        total = money(net * p / 100)
        detail = _t("share_of", lang, p=_pct_text(p, lang))
    else:
        a = dec(amount, "NaN") if amount not in (None, "") else Decimal("NaN")
        if a.is_nan() or a <= 0:
            raise BadInput(tr("Invalid value: {0}", "amount"))
        fx = dec(offer["fx_rate"], "1") if str(offer["currency"]).upper() == "USD" else Decimal(1)
        total = (a / fx).quantize(Decimal("0.0001")) if fx not in (0, 1) else money(a)  # rates are stored in EUR
        detail = ""
    if total > dec(info["remaining"]):
        raise BadInput(tr("The progress invoices would exceed the quotation's net ({0} left)", info["remaining_text"]))
    n = len(info["progress"]) + 1
    keys = sorted(bases, key=lambda k: TAX_KEYS.index(k))
    rows, left = [], total
    for i, k in enumerate(keys):
        part = left if i == len(keys) - 1 else money(total * bases[k] / net)
        left -= part
        d = detail
        if len(keys) > 1:
            d = (detail + " · " if detail else "") + _t("share", lang, pct=_pct_text(pack_rate(pack, k), lang))
        rows.append({"kind": "service", "service_id": None, "title": _t("progress", lang, n=n, num=offer["number"] or "-"), "detail": d,
                     "qty": 1, "unit": "flat", "rate": part, "tax": k, "intext": "intern", "cost": 0, "raw_fee": 0, "producing": 0, "discountable": 0})
    row = inv_new_row(c, oid, s, "invoice", lang, offer)
    row.update(source_doc_id=offer["id"], inv_type="progress")
    did = _insert_doc(c, oid, uid, row)
    _put_rows(c, oid, did, rows)
    return did


def pack_rate(pack, key):
    from .calc import pack_tax
    return pack_tax(pack, key)


def abs_deductions(c, oid, offer, lang, cur):
    """(ids, position rows) deducting the finalised progress invoices of quotation offer, one per invoice and tax rate."""
    from .docs import doc_items
    from .invoices import inv_money_fields, inv_paid_map
    s, pack = _pack(c, oid)
    rows = abs_progress_of(c, oid, offer["id"], locked_only=True)
    pm = inv_paid_map(c, oid, [x["id"] for x in rows])
    ids, out = [], []
    for x in rows:
        ids.append(x["id"])
        t = _j(x["totals"], {})
        taxes = {tl.get("rate_key"): tl for tl in t.get("tax_lines") or []}
        nets = {}
        for ln in t.get("lines") or []:
            if ln.get("kind") in ("item", "discount") and ln.get("tax") in TAX_KEYS:
                nets.setdefault(ln["tax"], Decimal(0))
                nets[ln["tax"]] += dec(ln.get("net") or ln.get("total") or 0)
        eur = _eur_bases(doc_items(c, x["id"], oid), pack)
        mf = inv_money_fields(x, pm)
        paid = _t("paid", lang) if dec(mf["open"]) <= 0 else _t("open", lang)
        dt = x["date"] or ""
        dtext = f"{dt[8:10]}.{dt[5:7]}.{dt[0:4]}" if lang == "de" and len(dt) == 10 else dt
        for k in sorted(eur, key=lambda k: TAX_KEYS.index(k)):
            if eur[k] == 0:
                continue
            net = nets.get(k, eur[k])
            tax = dec((taxes.get(k) or {}).get("amount") or 0)
            pct = (taxes.get(k) or {}).get("pct") or (dstr(pack_rate(pack, k)) if x["vat_mode"] != "novat" else "0")
            out.append({"kind": "discount", "service_id": None, "title": _t("deduct", lang, num=x["number"], date=dtext),
                        "detail": _t("deduct_detail", lang, net=fmt_money(net, lang, cur), pct=_pct_text(pct, lang), tax=fmt_money(tax, lang, cur),
                                     gross=fmt_money(net + tax, lang, cur), paid=paid),
                        "qty": 1, "unit": "flat", "rate": abs(eur[k]), "tax": k, "intext": "intern", "cost": 0, "raw_fee": 0, "producing": 0, "discountable": 0})
    return ids, out


def abs_final(c, oid, uid, offer, parts_mode=None, parts_title=None):
    """A final invoice draft from quotation offer: its full positions, then the deduction of every finalised progress
    invoice (one negative position per invoice and tax rate). -> new id."""
    from .invoices import _insert_doc, _put_rows, inv_items_from_offer, inv_new_row
    abs_final_done(c, oid, offer["id"])
    s, pack = _pack(c, oid)
    row = inv_new_row(c, oid, s, "invoice", offer["lang"], offer)
    ids, ded = abs_deductions(c, oid, offer, offer["lang"], row["currency"])
    items = inv_items_from_offer(c, oid, offer, parts_mode, parts_title)
    if ded:
        items = items + [{"kind": "heading", "title": _t("heading", offer["lang"]), "detail": "", "qty": 1, "unit": "flat", "rate": 0, "tax": "standard",
                          "intext": "intern", "cost": 0, "raw_fee": 0, "producing": 0, "discountable": 0, "service_id": None}] + ded
    row.update(source_doc_id=offer["id"], inv_type="final", abs_refs=json.dumps(ids))
    did = _insert_doc(c, oid, uid, row)
    _put_rows(c, oid, did, items)
    return did


def abs_before_finalize(c, oid, r):
    """A final invoice: the finalised, not cancelled progress invoices of its quotation are still those it deducts."""
    if r["kind"] != "invoice" or _col(r, "inv_type") not in ("final", "progress") or not _col(r, "source_doc_id"):
        return
    abs_final_done(c, oid, r["source_doc_id"], but=r["id"])  # 2.120.0 (review M3): two drafts, a double click, an agent
    if _col(r, "inv_type") != "final":
        return
    now = sorted(x["id"] for x in abs_progress_of(c, oid, r["source_doc_id"], locked_only=True))
    if now != sorted(int(x) for x in _j(_col(r, "abs_refs") or "[]", [])):
        raise BadInput(tr("The progress invoices of the quotation changed since this final invoice was drafted; create the final invoice again"))


def abs_render(r, m, L, lang):
    """The print model of invoices.inv_render: the title of a progress / final invoice, its type code, the remaining
    amount of a final invoice and the cash discount line under the payment terms."""
    typ = _col(r, "inv_type") or ""
    m["inv_type"] = typ if r["kind"] == "invoice" else ""
    m["type_code"] = ABS_TYPE_CODE.get(m["inv_type"]) or ""
    if m["inv_type"]:
        m["title"] = L.get(typ + "_invoice") or tr(ABS_TITLE[typ], lg=lang)
    tot = m.get("totals") or {}
    if m["inv_type"] == "final" and isinstance(tot.get("rows"), list):
        lab = L.get("invoice_total", tr("Total|invoice", lg=lang))
        tot["rows"] = [[_t("rest", lang), x[1]] if x and x[0] == lab else x for x in tot["rows"]]
    m["skonto"] = None
    sk = abs_skonto_numbers(r, tot.get("gross") or 0) if r["kind"] == "invoice" else None
    if sk is not None and isinstance(m.get("payment"), dict):
        cur = r["currency"]
        dl = sk["deadline"]
        dtext = f"{dl[8:10]}.{dl[5:7]}.{dl[0:4]}" if lang == "de" else dl
        line = _t("skonto", lang, date=dtext, pct=_pct_text(sk["pct"], lang), amt=fmt_money(sk["amount"], lang, cur), pay=fmt_money(sk["payable"], lang, cur))
        m["payment"]["text"] = (m["payment"].get("text") + "\n" if m["payment"].get("text") else "") + line
        m["payment"]["skonto_bt20"] = abs_skonto_bt20(r)
        m["skonto"] = {"pct": dstr(sk["pct"]), "days": sk["days"], "deadline": dl, "amount": dstr(sk["amount"]), "payable": dstr(sk["payable"]), "text": line}


# ---------------------------------------------------------------- routes
@app.get("/api/office/docs/<int:did>/progress")
def abs_progress_get(did):
    """The progress invoices of quotation did with the quotation's net and what is left to bill (the "invoice from
    quotation" dialog)."""
    from .docs import doc_row
    from .invoices import _ctx
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    if r["kind"] != "offer":
        raise Denied(409, tr("Only a quotation can be turned into an invoice"))
    return jsonify(abs_offer_info(c, oid, r))
