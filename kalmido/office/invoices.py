"""Office & finance, stage 2 (2.38.0, #1021, F1): invoices, credit notes and reminders (kinds invoice / credit / reminder of
office_docs), payments (office_payments), sending by e-mail and the DATEV document inbox.

States: invoice / credit  draft -> issued (= finalised, ledger.ofx_finalize) -> sent -> paid; derived in the answers
(never stored): partial (part paid), overdue (due date passed, still open). cancelled is stored on an invoice only when a
credit note over its full amount is finalised (cancels_id) -- never by editing; back to draft does not exist.
reminder: draft -> issued -> sent. Numbers come with finalising (OFX_NUMBER_AT_FINALIZE), one scheme per kind
(settings invoice_scheme / credit_scheme / reminder_scheme), a manual number only in the draft and only above the series'
last value. Amounts: the calculator (calc.inv_calc) is Decimal throughout; totals of these kinds are decimal strings.
Every route: office_gate (no agents, no kids) + office_org; foreign documents are 404. No agent reaches any of this."""
import json
import os
import re
import smtplib
from datetime import date, timedelta
from decimal import Decimal

from flask import g, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, iso, local_now, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .calc import INV_VAT_NOTES, dec, dstr, fmt_money, inv_calc, inv_open, money
from .packs import office_pack_for
from .model import office_feature, office_gate, office_need_feature, office_org, office_role, office_settings, pb_cl_sql
from .ledger import ofx_company, ofx_locked, ofx_log, ofx_need_editable

INV_KINDS = ("invoice", "credit", "reminder")
INV_STATUSES = {"invoice": ("draft", "issued", "sent", "paid", "cancelled"), "credit": ("draft", "issued", "sent", "paid"),
                "reminder": ("draft", "issued", "sent"), "delivery": ("draft", "issued", "sent")}  # 2.120.0 D (#2089): + delivery
PAY_METHODS = ("transfer", "cash", "card", "other")
REMINDER_LEVELS = (1, 2, 3)
STATE_TXT = {"issued": N_("Finalised"), "paid": N_("Paid"), "partial": N_("Partly paid"), "overdue": N_("Overdue"), "cancelled": N_("Cancelled")}
TITLE_FALLBACK = {"invoice": {"de": "Rechnung", "en": "Invoice"}, "credit": {"de": "Gutschrift", "en": "Credit note"},
                  "reminder_1": {"de": "Zahlungserinnerung", "en": "Payment reminder"}, "reminder_2": {"de": "Mahnung", "en": "Reminder"},
                  "reminder_3": {"de": "Letzte Mahnung", "en": "Final reminder"},
                  "delivery": {"de": "Lieferschein", "en": "Delivery note"}, "delivery_service": {"de": "Leistungsnachweis", "en": "Proof of service"},  # 2.120.0 D (#2089)
                  "offer": {"de": "Angebot", "en": "Quotation"}}  # 2.113.2 (#2253): a finalised quotation is mailed too


def _j(s, default):
    try:
        v = json.loads(s) if s else default
    except ValueError:
        return default
    return v if isinstance(v, type(default)) else default


def _col(r, k, default=None):
    return r[k] if r is not None and k in r.keys() and r[k] is not None else default


def _ctx(admin=False):
    c = db()
    uid = office_gate(c)
    return c, uid, office_org(c, uid, admin=admin)


# ---------------------------------------------------------------- schemes and numbers
def inv_scheme(s, kind):
    """The number scheme of a kind from the settings (office_settings fills the pack's defaults)."""
    return s.get(kind + "_scheme") or s.get("offer_scheme")


def inv_manual_seq(scheme, num):
    """The counter value a manual number carries under the scheme, None when it does not follow the scheme."""
    from .model import SCHEME_RE
    parts, pos, pat = [], 0, ""
    for m in SCHEME_RE.finditer(scheme):
        pat += re.escape(scheme[pos:m.start()])
        pat += r"(\d+)" if m.group(1).startswith("seq") else r".+?"
        pos = m.end()
    pat += re.escape(scheme[pos:])
    m = re.fullmatch(pat, num)
    if not m or not m.groups():
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


INV_SKIP_REASON_MIN = 5  # 2.39.1 (#1210 N2): characters of the reason a skipped number needs


def inv_manual_number(c, oid, r, s, num, reason=""):
    """2.38.0: a manual number of an invoice / credit note must follow the scheme and lie above the series' last value
    (no back-dating); the counter then continues from it. 2.39.1 (#1210 N2): more than one above the counter (a gap in
    the series) only with a reason (kept in the office log). The caller holds the number lock. BadInput otherwise."""
    from .model import office_scheme_period
    scheme = inv_scheme(s, r["kind"])
    seq = inv_manual_seq(scheme, num)
    if seq is None:
        raise BadInput(tr("The number must follow the scheme {0}", scheme))
    d = date.fromisoformat(r["date"]) if r["date"] else local_now().date()
    period = office_scheme_period(scheme, d)
    row = c.execute("SELECT last FROM office_numbers WHERE org_id=? AND kind=? AND period=?", (oid, r["kind"], period)).fetchone()
    last = row["last"] if row else 0
    if seq < last or (seq == last and num != (r["number"] or "")):  # 2.38.0 review: re-setting its own number is fine
        raise BadInput(tr("The number must be above the last one of the series ({0})", last))
    if seq > last + 1 and len((reason or "").strip()) < INV_SKIP_REASON_MIN:
        raise BadInput(tr("The number skips {0} numbers of the series; give a reason (GoBD)", seq - last - 1))
    c.execute("INSERT INTO office_numbers(org_id, kind, period, last) VALUES(?,?,?,?) ON CONFLICT(org_id, kind, period) DO UPDATE SET last=excluded.last",
              (oid, r["kind"], period, seq))


# ---------------------------------------------------------------- payments and the derived state
def inv_paid_map(c, oid, doc_ids=None):
    """{doc_id: {"paid": Decimal, "credits": Decimal}} of the organisation (all documents or the given ones):
    the payments recorded and the gross of the finalised credit notes against each invoice."""
    out = {}
    ids = [int(x) for x in doc_ids] if doc_ids is not None else None
    if ids is not None and not ids:
        return out
    q = " AND doc_id IN (" + ",".join("?" * len(ids)) + ")" if ids is not None else ""
    for row in c.execute(f"SELECT doc_id, SUM(amount) AS s FROM office_payments WHERE org_id=?{q} GROUP BY doc_id", [oid] + (ids or [])):
        out.setdefault(row["doc_id"], {"paid": Decimal(0), "credits": Decimal(0)})["paid"] = money(dec(row["s"]))
    q = " AND cancels_id IN (" + ",".join("?" * len(ids)) + ")" if ids is not None else ""
    for row in c.execute("SELECT cancels_id, totals FROM office_docs WHERE org_id=? AND kind='credit' AND locked_at IS NOT NULL AND cancels_id IS NOT NULL" + q,
                         [oid] + (ids or [])):
        t = _j(row["totals"], {})
        out.setdefault(row["cancels_id"], {"paid": Decimal(0), "credits": Decimal(0)})["credits"] += money(dec(t.get("gross") or 0))
    return out


def inv_state(r, pm, today=None):
    """The derived state of a row: the stored status, or partial / overdue for an open invoice."""
    st = r["status"]
    if r["kind"] not in ("invoice", "credit") or st in ("draft", "paid", "cancelled"):
        return st
    t = _j(r["totals"], {})
    p = pm.get(r["id"]) or {"paid": Decimal(0), "credits": Decimal(0)}
    gross = money(dec(t.get("gross") or 0))
    covered = p["paid"] + p["credits"]
    if gross > 0 and covered >= gross:
        return "paid"
    if r["kind"] == "invoice":
        if p["paid"] > 0:
            return "partial"
        due = _col(r, "due_date") or ""
        if due and due < (today or local_now().date().isoformat()):
            return "overdue"
    return st


def inv_money_fields(r, pm):
    """paid / open / credits of a row as decimal strings (for the list and the document)."""
    t = _j(r["totals"], {})
    p = pm.get(r["id"]) or {"paid": Decimal(0), "credits": Decimal(0)}
    paid, open_ = inv_open(t.get("gross") or 0, p["paid"], p["credits"])
    if r["status"] == "cancelled" or (r["status"] == "paid" and _col(r, "skonto_pct")):  # 2.120.0 A (#2087): paid with cash discount
        open_ = "0.00"
    return {"paid": paid, "credits": dstr(p["credits"]), "open": open_}


def inv_refresh_paid(c, oid, did):
    """After a payment or a credit note: an open invoice covered in full becomes paid (paid_at); one no longer covered
    goes back to sent / issued."""
    r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
    if not r or r["kind"] not in ("invoice", "credit") or not ofx_locked(r) or r["status"] == "cancelled":
        return
    pm = inv_paid_map(c, oid, [did])
    t = _j(r["totals"], {})
    gross = money(dec(t.get("gross") or 0))
    p = pm.get(did) or {"paid": Decimal(0), "credits": Decimal(0)}
    ts = iso(now_utc())
    from .abschlag import abs_skonto_covered  # 2.120.0 A (#2087): paid in time less the cash discount = paid
    if gross > 0 and (p["paid"] + p["credits"] >= gross or abs_skonto_covered(c, oid, r, p["credits"])):
        if r["status"] != "paid":
            c.execute("UPDATE office_docs SET status='paid', paid_at=?, updated_at=? WHERE id=? AND org_id=?", (ts, ts, did, oid))
            from ..integrations.webhooks import who_note
            who_note("invoice.paid", "invoice", did)  # 2.115.0 A (#2061): the payments reached the total
    elif r["status"] == "paid":
        c.execute("UPDATE office_docs SET status=?, paid_at=NULL, updated_at=? WHERE id=? AND org_id=?",
                  ("sent" if r["sent_at"] else "issued", ts, did, oid))


# ---------------------------------------------------------------- finalising (called by ledger.ofx_finalize)
def inv_missing(c, oid, r, s, pack, items):
    """The required fields of an invoice that are still missing (names in the signed-in person's language)."""
    miss = []
    rec = _j(r["recipient"], {})
    cl = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (r["client_id"],)).fetchone() if r["client_id"] else None
    if not (rec.get("name") or "").strip():
        miss.append(tr("recipient name"))
    addr_ok = cl is not None and all((cl[k] if k in cl.keys() else "") for k in ("street", "zip", "city"))
    # 2.97.0 B (#1951): with a client only its fields count (its name + attn. line are no address)
    if not addr_ok and (cl is not None or len([x for x in (rec.get("lines") or []) if x.strip()]) < 2):
        miss.append(tr("recipient address (street, postcode and city)"))
    if not r["date"]:
        miss.append(tr("date"))
    if r["kind"] == "reminder":
        if not _j(_col(r, "ref_doc_ids") or "[]", []):
            miss.append(tr("invoices to remind of"))
        return miss
    if r["kind"] == "delivery":  # 2.120.0 D (#2089): no tax, bank or period needed: recipient, date and one position
        if not any(it.get("kind") == "service" for it in items):
            miss.append(tr("at least one position"))
        return miss
    if not (_col(r, "service_from") or _col(r, "service_to")):
        miss.append(tr("period of service"))
    if not any(it.get("kind") == "service" for it in items):
        miss.append(tr("at least one position"))
    co = ofx_company(c, oid)
    free = s.get("company") or {}
    if not (co.get("name") or free.get("name")):
        miss.append(tr("company name"))
    if not ((co.get("street") and co.get("zip") and co.get("city")) or free.get("lines")):
        miss.append(tr("company address"))
    if not (co.get("tax_number") or co.get("vat_id")):
        miss.append(tr("tax number or VAT ID"))
    if not co.get("iban"):
        miss.append(tr("IBAN"))
    from .countries import fk_country_code  # 2.40.0 (#1372): an unknown country code stops here, never silently DE
    if co.get("country") and fk_country_code(co["country"]) is None:
        miss.append(tr("valid country of the company (ISO code, now {0})", co["country"]))
    elif not co.get("country") and (pack or {}).get("neutral"):  # 2.147.0 (#2461): the base pack assumes no country (the e-invoice needs one)
        miss.append(tr("country of the company"))
    if cl is not None and "country" in cl.keys() and cl["country"] and fk_country_code(cl["country"]) is None:
        miss.append(tr("valid country of the client (ISO code, now {0})", cl["country"]))
    if r["kind"] == "invoice" and not (_col(r, "due_date") or _col(r, "payment_days")) and not s.get("payment_days"):
        miss.append(tr("due date or payment days"))
    if r["vat_mode"] == "novat" and (_col(r, "vat_note") or "") not in INV_VAT_NOTES:
        miss.append(tr("VAT note (reverse charge / not taxable / small business)"))
    return miss


def inv_before_finalize(c, oid, r, s, pack):
    """400 with the list of missing fields; sets the due date of an invoice from its payment days when it has none."""
    from .docs import doc_items
    items = doc_items(c, r["id"], oid)
    miss = inv_missing(c, oid, r, s, pack, items)
    if miss:
        raise BadInput(tr("Missing before finalising: {0}", ", ".join(miss)))
    if r["kind"] in ("invoice", "credit"):
        inv_check_date(c, oid, r, s)
    from .abschlag import abs_before_finalize
    abs_before_finalize(c, oid, r)  # 2.120.0 A (#2087): a final invoice deducts the current progress invoices
    if r["kind"] == "invoice" and not _col(r, "due_date"):
        days = _col(r, "payment_days")
        if days is None:
            days = int(s.get("payment_days") or 14)
        d = date.fromisoformat(r["date"]) + timedelta(days=int(days))
        c.execute("UPDATE office_docs SET due_date=?, payment_days=? WHERE id=? AND org_id=?", (d.isoformat(), int(days), r["id"], oid))


def inv_check_date(c, oid, r, s):
    """2.38.0 review (GoBD, chronological series): the date of an invoice / credit note being finalised lies neither in
    the future nor before the date of the last finalised document of the same series (organisation, kind, counter
    period); the due date never lies before the date. BadInput otherwise."""
    from .model import office_scheme_period
    d = r["date"]
    if d > local_now().date().isoformat():
        raise BadInput(tr("The date must not lie in the future"))
    due = _col(r, "due_date")
    if due and due < d:
        raise BadInput(tr("The due date must not lie before the date"))
    scheme = inv_scheme(s, r["kind"])
    period = office_scheme_period(scheme, date.fromisoformat(d))
    for row in c.execute("SELECT date FROM office_docs WHERE org_id=? AND kind=? AND locked_at IS NOT NULL AND id<>? AND date>? ORDER BY date DESC",
                         (oid, r["kind"], r["id"], d)):
        try:
            if office_scheme_period(scheme, date.fromisoformat(row["date"])) == period:
                raise BadInput(tr("The date must not lie before the last finalised document of this series ({0})", row["date"]))
        except ValueError:
            continue


def inv_after_finalize(c, oid, uid, r):
    """Status issued; a credit note settles its invoice (cancelled when it covers the full gross, else the open amount
    shrinks); then the optional store hook of the PDF / XML writer (F2)."""
    ts = iso(now_utc())
    c.execute("UPDATE office_docs SET status='issued', updated_at=? WHERE id=? AND org_id=? AND status='draft'", (ts, r["id"], oid))
    if r["kind"] == "credit" and _col(r, "cancels_id"):
        write_lock(c, f"office_credits_{int(r['cancels_id'])}")  # 2.39.0 (#1209 audit M1): parallel credit notes see each other
        inv_ = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=? AND kind='invoice'", (r["cancels_id"], oid)).fetchone()
        if inv_ is not None:
            ti, tc = _j(inv_["totals"], {}), _j(r["totals"], {})
            credited = sum((money(dec(_j(x["totals"], {}).get("gross") or 0)) for x in c.execute(
                "SELECT totals FROM office_docs WHERE org_id=? AND kind='credit' AND cancels_id=? AND locked_at IS NOT NULL AND id<>?",
                (oid, inv_["id"], r["id"]))), Decimal(0))
            if credited + money(dec(tc.get("gross") or 0)) > money(dec(ti.get("gross") or 0)):  # 2.38.0 review: credits never exceed the invoice
                raise Denied(409, tr("The credit notes would exceed the amount of the invoice"))
            if money(dec(tc.get("gross") or 0)) >= money(dec(ti.get("gross") or 0)) and inv_["status"] != "cancelled":
                c.execute("UPDATE office_docs SET status='cancelled', updated_at=? WHERE id=? AND org_id=?", (ts, inv_["id"], oid))
                ofx_log(c, oid, "status", doc_id=inv_["id"], detail={"before": {"status": inv_["status"]}, "after": {"status": "cancelled"}, "credit_id": r["id"]})
            else:
                inv_refresh_paid(c, oid, inv_["id"])
    hook = _f2("epdf_store")
    if hook is not None:
        hook(c, oid, r["id"])


def _f2(name):
    """A function of F2's PDF / e-invoice modules when it exists (the modules are built in parallel)."""
    for mod in ("pdfweb", "pdf", "einvoice"):
        try:
            m = __import__("kalmido.office." + mod, fromlist=[name])
        except ImportError:
            continue
        fn = getattr(m, name, None)
        if callable(fn):
            return fn
    return None


# ---------------------------------------------------------------- making documents
def _lines_eur(c, oid, r):
    """The automatic lines of a quotation (producing, raw data, discount) in EUR: the calculator run in EUR."""
    from .docs import _calc_doc, doc_items
    from .calc import office_calc
    s = office_settings(c, oid)
    pack = office_pack_for(s)
    d = _calc_doc(r)
    d["currency"] = "EUR"
    return office_calc(d, doc_items(c, r["id"], oid), pack)["lines"]


def inv_items_from_offer(c, oid, r, parts_mode=None, parts_title=None):
    """The positions of an invoice from quotation r: every quotation line becomes a plain position with its amount (the
    producing / raw data / discount automation of the quotation is condensed into positions; an uncounted raw data option
    is left out). Rates stay in EUR; the invoice converts them with its own rate."""
    from .docs import doc_items
    from .parts import tp_inv_items  # 2.47.0 (#1215): a quotation with parts -> title page / summary / full (office/parts.py)
    out = tp_inv_items(c, oid, r, parts_mode, parts_title)
    if out is not None:
        return out
    items = doc_items(c, r["id"], oid)
    lines = _lines_eur(c, oid, r)
    pct = {ln.get("id"): ln for ln in lines if ln.get("kind") == "item" and ln.get("pct") is not None}
    out = []
    for it in items:
        row = {k: it.get(k) for k in ("kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "intext", "cost")}
        row.update(raw_fee=0, producing=0, discountable=1)
        if it.get("unit") == "percent" and it.get("id") in pct:  # 2.47.0 (#1649): a percent position becomes its amount
            row.update(qty=1, unit="flat", rate=pct[it["id"]]["total"])
        out.append(row)
    for ln in lines:
        if ln["kind"] == "producing":  # 2.113.1 (#2251): without its calculation (internal)
            out.append({"kind": "service", "service_id": None, "title": ln["title"], "detail": "", "qty": ln["qty"], "unit": "day",
                        "rate": ln["rate"], "tax": "standard", "intext": "intern", "cost": 0, "raw_fee": 0, "producing": 0, "discountable": 1})
        elif ln["kind"] == "raw" and not ln.get("optional") or ln["kind"] == "surcharge":  # 2.113.1 (#2252): + surcharge
            out.append({"kind": "service", "service_id": None, "title": ln["title"], "detail": "" if ln["kind"] == "surcharge" else ln.get("detail") or "", "qty": 1, "unit": "flat",
                        "rate": ln["total"], "tax": "standard", "intext": "intern", "cost": 0, "raw_fee": 0, "producing": 0, "discountable": 1})
        elif ln["kind"] == "discount":
            out.append({"kind": "discount", "service_id": None, "title": ln["title"], "detail": ln.get("detail") or "", "qty": 1, "unit": "flat",
                        "rate": abs(dec(ln["total"])), "tax": "standard", "intext": "intern", "cost": 0, "raw_fee": 0, "producing": 0, "discountable": 1})
    return out


def _insert_doc(c, oid, uid, row):
    ts = iso(now_utc())
    row.update(org_id=oid, number="", status="draft", totals="{}", created_by=uid, created_at=ts, updated_at=ts, sent_at=None)
    did = insert_id(c, f"INSERT INTO office_docs({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    from ..integrations.webhooks import who_note
    who_note("invoice.created", "invoice", did)  # 2.115.0 A (#2061)
    return did


def _put_rows(c, oid, did, rows):
    for i, row in enumerate(rows):
        row = dict(row)
        row.update(doc_id=did, org_id=oid, sort=i)
        row["qty"] = float(dec(row.get("qty"), "1"))
        row["rate"] = float(dec(row.get("rate"), "0"))
        row["cost"] = float(dec(row.get("cost"), "0"))
        from ..core.orgcrypt import oc_item_store
        row = oc_item_store(c, oid, row)  # 2.42.0 (#828): the purchase price encrypted at rest
        c.execute(f"INSERT INTO office_doc_items({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def inv_default_texts(c, oid, s, kind, lang, level=1):
    """intro / closing of an invoice, credit note or reminder: the organisation's text (settings), else the pack's.
    2.40.0 (#1368): credit notes have their own closing (credit_closing), reminders an intro / closing per level 1-3."""
    pack = office_pack_for(s) or {}
    texts = pack.get("texts") or {}
    sal = (texts.get("salutation") or {}).get(lang) or ""
    sfx = f"_{level}" if kind == "reminder" and level in (2, 3) else ""
    intro = (texts.get(kind + "_intro" + sfx) or texts.get(kind + "_intro") or {}).get(lang) or ""
    if sal and intro:
        intro = sal + "\n" + intro
    if kind == "reminder":
        closing = s.get("reminder_text_" + lang) or (texts.get("reminder_closing" + sfx) or texts.get("reminder_closing") or {}).get(lang) or ""
    elif kind == "credit":
        closing = (texts.get("credit_closing") or {}).get(lang) or ""
    else:
        closing = s.get("invoice_closing_" + lang) or (texts.get("invoice_closing") or {}).get(lang) or ""
    return intro, closing


def inv_new_row(c, oid, s, kind, lang, src=None):
    """The head of a new invoice-kind draft (from quotation / invoice src or empty)."""
    today = local_now().date()
    intro, closing = inv_default_texts(c, oid, s, kind, lang)
    row = {"kind": kind, "lang": lang, "currency": (s.get("currency") or "EUR").upper(), "fx_rate": s.get("fx_usd") or 1.09, "vat_mode": "vat",
           "client_id": None, "recipient": json.dumps({"name": "", "lines": []}), "project_title": "", "project_ref": "", "date": today.isoformat(),
           "valid_until": "", "contract_id": None, "raw_mode": "none", "raw_factor": 0, "prod_quotient": 3, "producing_rate": 0, "discount_pct": 0,
           "intro": intro, "closing": closing, "rights": json.dumps({"time": {"id": None, "text": ""}, "territory": {"id": None, "text": ""},
                                                                   "media": {"id": None, "text": ""}, "exceptions": "", "exclusive": 0, "note": ""}),
           "fields": "[]", "service_from": None, "service_to": None, "order_ref": "", "due_date": None,
           "payment_days": int(s.get("payment_days") or 14) if kind == "invoice" else None, "vat_note": "", "einvoice_format": s.get("einvoice_format") or "zugferd"}
    if src is not None:
        for k in ("lang", "currency", "fx_rate", "vat_mode", "client_id", "recipient", "project_title", "project_ref", "contract_id", "rights", "fields",
                  "service_from", "service_to", "vat_note", "contact_id"):  # 2.40.0 (#1380): + the contact person
            if k in src.keys() and src[k] is not None:
                row[k] = src[k]
        row["order_ref"] = _col(src, "order_ref") or src["project_ref"] or ""
        if src["lang"] != lang:
            row["intro"], row["closing"] = inv_default_texts(c, oid, s, kind, src["lang"])
        if src["client_id"]:
            cl = c.execute(f"SELECT buyer_reference, payment_terms_days FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (src["client_id"],)).fetchone()
            if cl is not None:
                if cl["payment_terms_days"] and kind == "invoice":
                    row["payment_days"] = int(cl["payment_terms_days"])
                if cl["buyer_reference"] and kind in ("invoice", "credit"):  # 2.40.0 (#1368): credit notes too
                    row["einvoice_format"] = "xrechnung"
    # 2.47.3 (#1360): section 19 UStG -- no VAT, the exemption note (E); a credit note keeps the tax of the invoice it
    # corrects (review S3: a credit for a 19 % invoice from before the switch must balance it)
    if s.get("small_business") and kind != "reminder" and not (kind == "credit" and src is not None):
        row["vat_mode"], row["vat_note"] = "novat", "small"
    from .abschlag import abs_new_row
    abs_new_row(s, row, kind)  # 2.120.0 A (#2087): the default cash discount
    return row


def inv_apply_client(c, oid, row, b):
    """A new draft with a client: its payment terms and (buyer reference = XRechnung) its e-invoice format, unless given."""
    if not row.get("client_id") or row.get("kind") not in ("invoice", "credit"):  # 2.40.0 (#1368): credit: the format only
        return
    cl = c.execute(f"SELECT buyer_reference, payment_terms_days FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (row["client_id"],)).fetchone()
    if cl is None:
        return
    if cl["payment_terms_days"] and "payment_days" not in b and row.get("kind") == "invoice":
        row["payment_days"] = int(cl["payment_terms_days"])
    if cl["buyer_reference"] and "einvoice_format" not in b:
        row["einvoice_format"] = "xrechnung"


def inv_from_offer(c, oid, uid, offer, parts_mode=None, parts_title=None):
    s = office_settings(c, oid)
    row = inv_new_row(c, oid, s, "invoice", offer["lang"], offer)
    row["source_doc_id"] = offer["id"]
    did = _insert_doc(c, oid, uid, row)
    _put_rows(c, oid, did, inv_items_from_offer(c, oid, offer, parts_mode, parts_title))
    return did


def inv_credit_of(c, oid, uid, inv_):
    """A credit note draft over the whole invoice (positions copied; the person shortens it for a partial credit)."""
    from .docs import doc_items
    s = office_settings(c, oid)
    row = inv_new_row(c, oid, s, "credit", inv_["lang"], inv_)
    if _col(inv_, "einvoice_format"):  # 2.40.0 (#1368): the credit note keeps the invoice's e-invoice format (XRechnung)
        row["einvoice_format"] = inv_["einvoice_format"]
    row["cancels_id"] = inv_["id"]
    row["source_doc_id"] = inv_["id"]
    did = _insert_doc(c, oid, uid, row)
    rows = []
    for it in doc_items(c, inv_["id"], oid):
        r_ = {k: it.get(k) for k in ("kind", "service_id", "title", "detail", "qty", "unit", "rate", "tax", "intext", "cost")}
        r_.update(raw_fee=0, producing=0, discountable=1)
        rows.append(r_)
    _put_rows(c, oid, did, rows)
    return did


def inv_from_time(c, oid, uid, b):
    """{client_id, from, to, project_id?}: an invoice draft from the finished time entries of the client's lists in the
    period, one position per list (project) with the hours; rate = the client's hourly rate when set, else 0 (to fill in)."""
    from .docs import _date, _recipient_from_client, cdn_home
    cid = b.get("client_id")
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "client_id"))
    cl = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (cid,)).fetchone()
    if cl is None:
        raise Denied(404)
    d_from, d_to = _date(b.get("from"), "from"), _date(b.get("to"), "to")
    if not d_from or not d_to or d_to < d_from:
        raise BadInput(tr("Invalid value: {0}", "from/to"))
    pid = b.get("project_id")
    # the WHERE part first (a fragment: pg_prepare only checks the complete statement below)
    from ..core.access import vis_sql
    # 2.86.0 (N16): only the lists the person making the invoice sees (their hours, names); 2.126.0 A (#1967): the
    # personal office's lists are the owner's private ones (org_id NULL)
    sql = ("FROM time_entries e JOIN lists l ON l.id=e.list_id "
           f"WHERE l.client_id=? AND {pb_cl_sql(c, oid, 'l.org_id', 'l.owner_id')} AND l.id IN {vis_sql()} AND e.\"end\" IS NOT NULL AND e.start>=? AND e.start<?")
    args = [cid, uid, uid, d_from + "T00:00:00", (date.fromisoformat(d_to) + timedelta(days=1)).isoformat() + "T00:00:00"]
    if pid not in (None, "", 0):
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "project_id"))
        sql += " AND e.list_id=?"
        args.append(pid)
    groups = c.execute(f"SELECT e.list_id, l.name AS lname, SUM(e.seconds) AS secs {sql} GROUP BY e.list_id, l.name ORDER BY l.name", args).fetchall()
    s = office_settings(c, oid)
    row = inv_new_row(c, oid, s, "invoice", s.get("lang") or "de")
    row.update(client_id=cid, recipient=json.dumps({k: v for k, v in _recipient_from_client(dict(cl), None, cdn_home(c, oid)).items() if k != "missing"}, ensure_ascii=False), service_from=d_from, service_to=d_to,
               project_title=cl["name"])
    if "payment_terms_days" in cl.keys() and cl["payment_terms_days"]:
        row["payment_days"] = int(cl["payment_terms_days"])
    did = _insert_doc(c, oid, uid, row)
    rate = cl["rate"] if "rate" in cl.keys() and cl["rate"] else 0
    rows = []
    for gr in groups:
        hours = (dec(gr["secs"] or 0) / 3600).quantize(Decimal("0.01"))
        if hours <= 0:
            continue
        rows.append({"kind": "service", "service_id": None, "title": gr["lname"] or tr("Hours"), "detail": "", "qty": hours, "unit": "hour", "rate": rate,
                     "tax": "standard", "intext": "intern", "cost": 0, "raw_fee": 0, "producing": 0, "discountable": 1})
    _put_rows(c, oid, did, rows)
    return did, len(rows)


def inv_reminder_rows(c, oid, ids):
    """The invoices a reminder lists (snapshot rows for totals.lines): open, finalised invoices of the organisation."""
    pm = inv_paid_map(c, oid, ids)
    rows = []
    for did in ids:
        r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=? AND kind='invoice'", (did, oid)).fetchone()
        if r is None:
            raise Denied(404)
        if not ofx_locked(r) or r["status"] in ("cancelled", "paid"):
            raise BadInput(tr("Only open, finalised invoices can be reminded of ({0})", r["number"] or did))
        mf = inv_money_fields(r, pm)
        rows.append({"kind": "ref", "id": r["id"], "number": r["number"], "date": r["date"], "due_date": _col(r, "due_date") or "", "gross": _j(r["totals"], {}).get("gross"),
                     "open": mf["open"], "currency": r["currency"]})
    return rows


def inv_reminder_totals(c, oid, r, pack=None):
    """The totals of a reminder: the open amounts of its invoices (snapshot in ref_doc_ids / totals.lines once finalised) plus the fee."""
    lang = "en" if r["lang"] == "en" else "de"
    cur = r["currency"]
    ids = _j(_col(r, "ref_doc_ids") or "[]", [])
    if ofx_locked(r):
        lines = [ln for ln in _j(r["totals"], {}).get("lines", []) if ln.get("kind") == "ref"]
    else:
        lines = inv_reminder_rows(c, oid, ids) if ids else []
    total = sum((money(dec(ln["open"])) for ln in lines), Decimal(0))
    fee = money(dec(_col(r, "reminder_fee") or 0))
    gross = total + fee
    for ln in lines:
        ln["open_text"] = fmt_money(ln["open"], lang, cur)
    return {"lang": lang, "currency": cur, "fx_rate": None, "fx_note": "", "vat_mode": "novat", "raw_mode": "none", "lines": lines,
            "net": dstr(total), "net_text": fmt_money(total, lang, cur), "fee": dstr(fee), "fee_text": fmt_money(fee, lang, cur), "tax_lines": [],
            "tax": "0.00", "tax_total": "0.00", "gross": dstr(gross), "gross_text": fmt_money(gross, lang, cur), "costs": "0.00", "margin": "0.00",
            "vat_note": "", "labels": {"net": "", "gross": "", "discount": ""}, "level": int(_col(r, "reminder_level") or 1),
            "deadline_days": int(_col(r, "reminder_deadline_days") or 0), "raw_amount": "0.00", "producing_days": 0, "discount": "0.00"}


def inv_check_reminder(c, oid, ids, rows):
    """2.38.0 review: a reminder lists issued / sent invoices with an open amount, all of the same client and currency."""
    keys = set()
    for did, ln in zip(ids, rows):
        r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
        if r["status"] not in ("issued", "sent") or money(dec(ln["open"])) <= 0:
            raise BadInput(tr("Only open, finalised invoices can be reminded of ({0})", r["number"] or did))
        who = r["client_id"] if r["client_id"] else (_j(r["recipient"], {}).get("name") or "").strip().lower()
        keys.add((who, r["currency"]))
    if len(keys) > 1:
        raise BadInput(tr("A reminder covers invoices of one client in one currency only"))


def inv_make_reminder(c, oid, uid, b):
    ids = b.get("doc_ids")
    if not isinstance(ids, list) or not ids or len(ids) > 50:
        raise BadInput(tr("Invalid value: {0}", "doc_ids"))
    try:
        ids = [int(x) for x in ids]
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "doc_ids"))
    s = office_settings(c, oid)
    rows = inv_reminder_rows(c, oid, ids)
    first = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (ids[0], oid)).fetchone()
    write_lock(c, f"office_dunning_{int(oid)}")  # 2.147.1 (#2054, review): the same lock as the suggestion run (no second draft at once)
    inv_check_reminder(c, oid, ids, rows)
    level = b.get("level", 1)
    if level not in REMINDER_LEVELS:
        raise BadInput(tr("Invalid value: {0}", "level"))
    fee = dec(b.get("fee") if b.get("fee") not in (None, "") else (s.get("reminder_fee") or 0))
    if fee < 0 or fee > 1000000:
        raise BadInput(tr("Invalid value: {0}", "fee"))
    try:
        days = int(b.get("deadline_days") if b.get("deadline_days") not in (None, "") else (s.get("reminder_deadline_days") or 10))
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "deadline_days"))
    if days < 0 or days > 365:
        raise BadInput(tr("Invalid value: {0}", "deadline_days"))
    row = inv_new_row(c, oid, s, "reminder", first["lang"], first)
    row["intro"], row["closing"] = inv_default_texts(c, oid, s, "reminder", row["lang"], int(level))  # 2.40.0 (#1368): text per level
    row.update(ref_doc_ids=json.dumps(ids), reminder_level=int(level), reminder_fee=float(fee), reminder_deadline_days=days, currency=first["currency"],
               service_from=None, service_to=None, order_ref="", payment_days=None, project_title=first["project_title"])
    did = _insert_doc(c, oid, uid, row)
    return did


# ---------------------------------------------------------------- the print model (invoice kinds), on top of docs.odoc_render
def inv_level(r):
    """The level argument of inv_title for row r: a reminder's level; 2.120.0 D (#2089) a delivery note: 2 = "proof of service"."""
    if r["kind"] == "delivery":
        return 2 if _col(r, "delivery_title") == "service" else 1
    return int(_col(r, "reminder_level") or 1)


def inv_title(L, lang, kind, level=1):
    key = kind if kind != "reminder" else f"reminder_{level if level in REMINDER_LEVELS else 1}"
    if kind == "delivery" and level == 2:  # 2.120.0 D (#2089): level 2 = "Leistungsnachweis" (delivery_title 'service')
        key = "delivery_service"
    return L.get(key) or TITLE_FALLBACK[key][lang]


def inv_render(c, oid, r, m, t, pack, L, lang, fmt_date):
    """Adds the keys of invoices / credit notes / reminders to print model m (see iface: title per kind, order_ref, due
    date, tax lines per rate, EUR tax line for USD, the credit note's invoice, the reminder's table, the payment info)."""
    texts = pack.get("texts") or {}
    cur = r["currency"]
    kind = r["kind"]
    level = inv_level(r)
    m["title"] = inv_title(L, lang, kind, level)
    m["order_ref"] = _col(r, "order_ref") or ""
    m["due_date"] = _col(r, "due_date") or ""
    m["due_date_text"] = fmt_date(m["due_date"], pack)
    m["payment_days"] = _col(r, "payment_days")
    m["einvoice_format"] = _col(r, "einvoice_format") or ""
    m["vat_note_key"] = _col(r, "vat_note") or ""
    m["vat_note_text"] = ((texts.get("vat_note_" + m["vat_note_key"]) or {}).get(lang) or "") if m["vat_note_key"] else ""
    sf, st = m.get("service_from") or "", m.get("service_to") or ""
    m["service_period_text"] = (fmt_date(sf, pack) if sf == st or not st else (fmt_date(st, pack) if not sf else f"{fmt_date(sf, pack)} – {fmt_date(st, pack)}")) if (sf or st) else ""
    snd = _j(r["sender"], {}) if ofx_locked(r) else {}
    fields = snd.get("fields") if snd else ofx_company(c, oid)
    m["sender_fields"] = {k: (fields or {}).get(k) or "" for k in ("name", "street", "address_extra", "zip", "city", "country", "email", "phone", "tax_number", "vat_id",
                                                                   "iban", "bic", "bank_name", "register_court", "register_no", "managing_directors")}  # 2.99.0 D (#2188): + address_extra (BT-36)
    rec = _j(r["recipient_snapshot"], {}) if ofx_locked(r) and r["recipient_snapshot"] else {}
    if not rec and r["client_id"]:
        cl = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (r["client_id"],)).fetchone()
        if cl is not None:
            rec = {k: (cl[k] if k in cl.keys() else "") for k in ("street", "zip", "city", "country", "vat_id", "customer_no", "buyer_reference", "email_invoice")}
            rec["extra"] = cl["address_extra"] if "address_extra" in cl.keys() else ""  # 2.97.0 B (#1951): the extra address line
            rec["email_invoice"] = rec["email_invoice"] or cl["email"] or ""  # 2.99.0 D (#2188): BT-49 falls back to the client's e-mail
    for k in ("street", "extra", "zip", "city", "country", "vat_id", "customer_no", "buyer_reference", "email_invoice"):
        m["recipient"][k] = rec.get(k) or ""
    # 2.40.0 (#1380): the buyer's contact person (e-invoice BT-56) -- the snapshot's, else the chosen / default one
    if ofx_locked(r) and r["recipient_snapshot"]:
        m["recipient"]["contact"] = rec.get("contact") or None
    else:
        from .docs import fk_doc_contact
        k = fk_doc_contact(c, r["client_id"], _col(r, "contact_id"))
        m["recipient"]["contact"] = {"name": k["name"], "email": k["email"], "phone": k["phone"]} if k else None
    num_label = L.get(kind + "_no") or (L.get("invoice_no", "Rechnung Nr.") if kind == "invoice" else m["title"] + (" No." if lang == "en" else " Nr."))
    meta = [[num_label, r["number"] or ("Draft" if lang == "en" else "Entwurf")]]
    cancels = None
    if kind == "credit" and _col(r, "cancels_id"):
        ci = c.execute("SELECT id, number, date FROM office_docs WHERE id=? AND org_id=?", (r["cancels_id"], oid)).fetchone()
        if ci is not None:
            cancels = {"id": ci["id"], "number": ci["number"], "date_text": fmt_date(ci["date"], pack)}
            meta.append([L.get("to_invoice", "zu Rechnung Nr." if lang == "de" else "Credit note for invoice no."), f"{ci['number']} ({cancels['date_text']})"])
    m["cancels"] = cancels
    if m["order_ref"]:
        meta.append([L.get("ref", "Ref./PO-Nr."), m["order_ref"]])
    if r["project_title"]:
        meta.append([L.get("project", "Projekttitel"), r["project_title"]])
    if m["recipient"].get("customer_no"):
        meta.append([L.get("customer_no", "Kunden-Nr." if lang == "de" else "Customer no."), m["recipient"]["customer_no"]])
    meta.append([L.get("date", "Datum"), m["date_text"]])
    if m["service_period_text"]:
        meta.append([L.get("service_period", "Leistungszeitraum" if lang == "de" else "Service period"), m["service_period_text"]])
    if kind == "invoice" and m["due_date"]:
        meta.append([L.get("due", "Fällig am" if lang == "de" else "Due on"), m["due_date_text"]])
    if cur == "USD" and t.get("fx_rate"):
        meta.append([L.get("fx", "Wechselkurs 1 €" if lang == "de" else "Exchange rate €1"), t.get("fx_note") or ""])
    m["meta"] = meta
    tot = m["totals"]
    tot["show_tax_lines"] = kind != "reminder"
    for k in ("net", "tax", "gross", "currency", "fx_rate", "fx_note", "tax_eur", "gross_eur", "tax_eur_text", "gross_eur_text"):
        if k in t:
            tot[k] = t[k]
    tot["tax_lines"] = t.get("tax_lines") or []
    tot["tax_total"] = t.get("tax") or "0.00"
    tot["net_text"] = fmt_money(t.get("net") or 0, lang, cur)
    tot["tax_text"] = fmt_money(t.get("tax") or 0, lang, cur)
    tot["gross_text"] = fmt_money(t.get("gross") or 0, lang, cur)
    pm = inv_paid_map(c, oid, [r["id"]])
    mf = inv_money_fields(r, pm)
    tot["paid"], tot["open"] = mf["paid"], mf["open"]
    tot["open_text"] = fmt_money(mf["open"], lang, cur)
    tot["vat_note"] = m["vat_note_text"] if r["vat_mode"] == "novat" else ""
    tot["fx_line"] = ""
    if cur == "USD" and t.get("tax_eur") is not None:
        tot["fx_line"] = ((texts.get("fx_tax_note") or {}).get(lang) or ("Steuerbetrag entspricht {tax} EUR, Kurs 1 EUR = {rate} USD" if lang == "de" else
                                                                       "Tax amount equals EUR {tax}, rate EUR 1 = USD {rate}")).replace(
            "{tax}", fmt_money(t["tax_eur"], lang, "EUR").replace(" €", "").replace("€", "")).replace("{rate}", str(t.get("fx_rate") or "").replace(".", "," if lang == "de" else "."))
    if kind == "reminder":
        rows = [[L.get("open_total", "Offener Betrag" if lang == "de" else "Amount outstanding"), tot["net_text"]]]
        if dec(t.get("fee") or 0) > 0:
            rows.append([L.get("reminder_fee", "Mahngebühr" if lang == "de" else "Reminder fee"), t.get("fee_text") or ""])
        rows.append([L.get("reminder_total", "Gesamtbetrag" if lang == "de" else "Total amount due"), tot["gross_text"]])  # 2.40.0 (#1368)
        deadline = ""
        if r["date"] and _col(r, "reminder_deadline_days"):
            deadline = fmt_date((date.fromisoformat(r["date"]) + timedelta(days=int(r["reminder_deadline_days"]))).isoformat(), pack)
        m["reminder"] = {"level": level, "title": m["title"], "fee": t.get("fee") or "0.00", "fee_text": t.get("fee_text") or "", "deadline_days": int(_col(r, "reminder_deadline_days") or 0),
                         "deadline_text": deadline,
                         "columns": [L.get("col_invoice", "Rechnung" if lang == "de" else "Invoice"), L.get("date", "Datum"), L.get("col_due", "Fällig" if lang == "de" else "Due"),
                                     L.get("amount", "Betrag" if lang == "de" else "Amount")],
                         "rows": [{"id": ln.get("id"), "number": ln.get("number"), "date_text": fmt_date(ln.get("date"), pack), "due_text": fmt_date(ln.get("due_date"), pack),
                                   "open": ln.get("open"), "open_text": ln.get("open_text") or fmt_money(ln.get("open") or 0, lang, cur)} for ln in t.get("lines") or []],
                         "total_open": t.get("net"), "total_open_text": tot["net_text"]}
        m["lines"] = []
        m["rights"] = {"title": "", "rows": [], "exceptions": "", "exclusive": 0, "note": ""}
        # the closing may carry {days} / {date} (pack text or the organisation's own): the deadline of this reminder
        m["closing"] = (m.get("closing") or "").replace("{days}", str(int(_col(r, "reminder_deadline_days") or 0))).replace("{date}", deadline)
    else:
        rows = [[L.get("subtotal", "Zwischensumme" if lang == "de" else "Subtotal"), tot["net_text"]]]
        for tl in tot["tax_lines"]:
            rows.append([tl.get("label") or "", tl.get("amount_text") or fmt_money(tl.get("amount") or 0, lang, cur)])
        rows.append([L.get("credit_total" if kind == "credit" else "invoice_total", ("Gutschriftsbetrag" if kind == "credit" else "Rechnungsbetrag") if lang == "de" else "Total"), tot["gross_text"]])
        if kind == "invoice" and dec(mf["paid"]) > 0:
            rows.append([L.get("paid", "Bereits bezahlt" if lang == "de" else "Already paid"), fmt_money(mf["paid"], lang, cur)])
            rows.append([L.get("open", "Offener Betrag" if lang == "de" else "Amount outstanding"), tot["open_text"]])
        m["reminder"] = None
    tot["rows"] = rows
    if kind == "delivery":  # 2.120.0 D (#2089): no prices, no totals, no tax, no payment info; the receipt box is drawn by pdf.py
        tot["rows"], tot["tax_lines"], tot["vat_note"], tot["fx_line"] = [], [], "", ""
        m["noprice"], m["vat_note_text"], m["signature"] = True, "", ""
        m["rights"] = {"title": "", "rows": [], "exceptions": "", "exclusive": 0, "note": ""}
        m["receipt_label"] = L.get("delivery_receipt") or (("Received / accepted" if lang == "en" else "Erhalten / abgenommen"))
        m["lines"] = [ln for ln in m["lines"] if ln.get("kind") in ("item", "heading", "text")]
    sfd = m["sender_fields"]
    ptext = ""
    if kind == "invoice":
        ptext = ((texts.get("payment_note") or {}).get(lang) or ("Zahlbar bis {date} ohne Abzug." if lang == "de" else "Payable by {date} without deduction.")).replace("{date}", m["due_date_text"]) if m["due_date"] else ""
    m["payment"] = {"iban": sfd["iban"], "bic": sfd["bic"], "bank_name": sfd["bank_name"], "text": ptext} if kind not in ("credit", "delivery") else None
    from .girocode import gcq_model
    gcq_model(r, m, None if ofx_locked(r) else office_settings(c, oid), snd)  # 2.147.1 B (#2054): the GiroCode (EPC QR text)
    m["valid_note"] = ""
    m["valid_until"] = ""
    m["valid_until_text"] = ""
    from .abschlag import abs_render
    abs_render(r, m, L, lang)  # 2.120.0 A (#2087): progress / final title, cash discount line
    return m


# ---------------------------------------------------------------- sending
def inv_files(c, oid, did):
    """[(name, bytes, mime)] to attach: F2's epdf_doc_files (PDF/A-3 + XML) when it exists, else the plain PDF."""
    fn = _f2("epdf_doc_files")
    if fn is not None:
        files = fn(c, oid, did)
        if files:
            return files
    from .docs import odoc_render
    from .pdf import office_pdf
    m = odoc_render(c, did, oid)
    m.pop("internal", None)
    from .docs import doc_row
    from .pdfweb import epdf_draft, epdf_is_draft
    if epdf_is_draft(doc_row(c, oid, did)):
        epdf_draft(m)  # 2.138.2 A (#2393): a draft goes out marked
    number = re.sub(r"[^A-Za-z0-9._-]+", "-", str(m.get("number") or "")).strip("-") or f"doc-{did}"
    return [(f"{m['kind']}-{number}.pdf", office_pdf(m), "application/pdf")]


def _mail_text(r, lang, s):
    co = _j(r["sender"], {}).get("company") or {}
    name = co.get("name") or (s.get("company") or {}).get("name") or ""
    if lang == "en":
        return f"Dear Sir or Madam,\n\nplease find attached the document {r['number']}.\n\nKind regards\n{name}"
    return f"Sehr geehrte Damen und Herren,\n\nanbei erhalten Sie das Dokument {r['number']}.\n\nMit freundlichen Grüßen\n{name}"


def inv_clean_subject(v, limit=200):
    """2.38.0 review: a mail subject on one line (CR / LF become a space), at most limit characters."""
    v = v if isinstance(v, str) else ""
    return re.sub(r"\s*[\r\n]+\s*", " ", v).strip()[:limit].strip()


def _mail(to, subject, text, **kw):
    """mail_send with a readable 409 when the mail server refuses; the details only go to the server log."""
    from ..integrations.mail import mail_send
    try:
        return mail_send(to, subject, text, **kw)  # 2.153.0 (#2029): the message sent (a letter keeps its Message-ID)
    except (smtplib.SMTPException, OSError) as e:
        app.logger.warning("office mail failed: %s", type(e).__name__)  # 2.39.0 (#1209 audit N6): no addresses in the log
        raise Denied(409, tr("Mail server refused the message"))


def inv_datev_ready(c, oid, r, s):
    """409 when the DATEV copy cannot go out (no SMTP, no inbox address, not finalised)."""
    from ..integrations.mail import MAIL_OUT_ON
    office_need_feature(c, oid, "books.datev", s)  # 2.147.0 (#2459, #2460)
    if not MAIL_OUT_ON:
        raise Denied(409, tr("Sending e-mail is not set up on this server (KALMIDO_SMTP_HOST)"))
    if not s.get("datev_email"):
        raise Denied(409, tr("No DATEV inbox address in the settings"))
    if not ofx_locked(r):
        raise Denied(409, tr("Finalise the document first"))


def inv_send(c, oid, uid, r, b):
    """Mails the finalised document r to b["to"] (cc, subject, text optional) with its PDF (+ XML) and records it (status
    sent, log). Returns (files, datev): datev = the DATEV copy is due (b["datev"] true, or the setting datev_auto while
    the document has not gone to DATEV yet); the caller commits the customer mail first and sends that copy afterwards
    (2.38.0 review: a DATEV failure never undoes or repeats the customer mail). Its prerequisites are checked before
    anything goes out. 409 without SMTP."""
    from ..integrations.mail import MAIL_OUT_ON
    if not MAIL_OUT_ON:
        raise Denied(409, tr("Sending e-mail is not set up on this server (KALMIDO_SMTP_HOST)"))
    if not ofx_locked(r):
        raise Denied(409, tr("Finalise the document first"))
    to = (b.get("to") or "").strip() if isinstance(b.get("to"), str) else ""
    cc = (b.get("cc") or "").strip() if isinstance(b.get("cc"), str) else ""
    mail_re = r"[^@\s,]+@[^@\s,]+\.[^@\s,]+"
    if not re.fullmatch(mail_re, to) or (cc and not re.fullmatch(mail_re, cc)):
        raise BadInput(tr("Invalid value: {0}", "to"))
    s = office_settings(c, oid)
    explicit = b.get("datev") in (1, True, "1", "true")
    if explicit:  # 2.147.0 (#2460): DATEV switched off -> no copy, also not the automatic one
        office_need_feature(c, oid, "books.datev", s)
    datev = r["kind"] in ("invoice", "credit") and (explicit or (b.get("datev") is None and s.get("datev_auto") and not _col(r, "datev_sent_at")
                                                                 and office_feature(c, oid, "books.datev", s)))
    if datev:
        inv_datev_ready(c, oid, r, s)
    lang = "en" if r["lang"] == "en" else "de"
    pack = office_pack_for(s) or {}
    title = inv_title((pack.get("labels") or {}).get(lang) or {}, lang, r["kind"], inv_level(r))
    subject = inv_clean_subject(b.get("subject")) or f"{title} {r['number']}"
    text = (b.get("text") or "").strip() if isinstance(b.get("text"), str) else ""
    own = bool(text) and text[:5000] != _mail_text(r, lang, s).strip()
    if own:
        inv_own_text_quota(c, oid, uid)
    h6c_send_budget(c, oid, uid, [to] + ([cc] if cc else []))  # 2.86.0 (N27)
    text = text[:5000] or _mail_text(r, lang, s)
    files = inv_files(c, oid, r["id"])
    sheet = []
    if r["kind"] == "invoice" and b.get("timesheet") in (1, True, "1", "true"):  # 2.120.0 D (#2089): the timesheet as a second attachment
        from .delivery import ls_sheet_file
        sheet = [ls_sheet_file(c, oid, uid, r)]
    from .terms import agb_mail_files
    mail_files, terms = agb_mail_files(c, oid, r, b, files + sheet)  # 2.113.2 (#2253): the terms PDF on request (quotations: by default; never to DATEV)
    u = g.user
    from .ledger import ofx_company
    rt = ofx_company(c, oid).get("email") or ""  # 2.39.0 (#1209 audit N4): the client's answer goes to the company, not the server
    rt = rt if re.fullmatch(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+", rt) else None
    _mail(to, subject, text, attachments=mail_files, cc=cc or None, from_name=(u["display_name"] if u is not None and "display_name" in u.keys() else None),
          reply_to=rt)
    if r["kind"] == "offer" and r["status"] == "draft":  # 2.113.2 (#2253): a mailed quotation is sent (purchase, pipeline as in the app)
        from .docs import odoc_set_status
        odoc_set_status(c, oid, r["id"], "sent", uid, r)
    ts = iso(now_utc())
    c.execute("UPDATE office_docs SET status=CASE WHEN status IN ('issued') THEN 'sent' ELSE status END, sent_at=COALESCE(sent_at, ?), updated_at=? "
              "WHERE id=? AND org_id=?", (ts, ts, r["id"], oid))
    from ..integrations.webhooks import who_note
    who_note("invoice.sent", "invoice", r["id"])  # 2.115.0 A (#2061): mailed
    ofx_log(c, oid, "send", doc_id=r["id"], detail={"to": to, "cc": cc, "files": [f[0] for f in mail_files], **({"own_text": 1} if own else {}),
                                                      **({"terms": terms} if terms else {})})  # 2.113.2 (#2253)
    return files, datev


INV_OWN_TEXT_DAY = 50  # 2.39.1 (#1210 N7): mails with an own text per organisation and day before members get 429


def inv_own_text_quota(c, oid, uid):
    """2.39.1 (#1210 N7): a member's mail with an own text: 429 once the organisation sent INV_OWN_TEXT_DAY of them since
    midnight UTC (admins' own texts count, they are not limited; the standard text and system mails never count)."""
    if office_role(c, uid, oid) == "admin":
        return
    write_lock(c, f"office_mail_{int(oid)}")
    since = now_utc().strftime("%Y-%m-%dT00:00:00")
    n = c.execute("SELECT COUNT(*) FROM office_doc_log WHERE org_id=? AND action='send' AND at>=? AND detail LIKE ?",  # pg-ok: own JSON, exact case
                  (oid, since, '%"own_text": 1%')).fetchone()[0]
    if n >= INV_OWN_TEXT_DAY:
        raise Denied(429, tr("Your organisation sent {0} mails with an own text today; members can send more tomorrow or with the standard text", INV_OWN_TEXT_DAY))


# 2.86.0 (N27): the day's budget of document mails (any text), generous so month-end billing never hits it
# (review: adjustable per environment; a broken value keeps the default)


def h6r_env_int(name, default):
    """A positive whole number from the environment variable name, else default (unset / not a number)."""
    try:
        return max(1, int(os.environ.get(name) or default))
    except ValueError:
        return default


H6C_SEND_DAY_ORG = h6r_env_int("KALMIDO_OFFICE_MAILS_DAY_ORG", 300)         # per organisation and day (UTC)
H6C_SEND_DAY_PERSON = h6r_env_int("KALMIDO_OFFICE_MAILS_DAY_PERSON", 150)   # per person and day
H6C_SEND_DAY_RCPT = h6r_env_int("KALMIDO_OFFICE_MAILS_DAY_ADDRESS", 20)     # per organisation, receiving address and day


def h6c_send_budget(c, oid, uid, rcpts):
    """2.86.0 (N27): 429 once the organisation / the person sent their day's document mails or one address got its share;
    counts the log's "send" entries since midnight UTC (user_id is plain, the detail may be encrypted) and per address a
    mail_counts row (key o:<org>:<address>, cleared like the other mail limits). The DATEV copy never counts."""
    write_lock(c, f"office_mail_{int(oid)}")
    since = now_utc().strftime("%Y-%m-%dT00:00:00")
    n_org, n_me = c.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE user_id=?) FROM office_doc_log WHERE org_id=? AND action='send' AND at>=?",
                            (uid, oid, since)).fetchone()
    if n_org >= H6C_SEND_DAY_ORG or n_me >= H6C_SEND_DAY_PERSON:
        raise Denied(429, tr("The day's limit of document mails is reached ({0}); please try again tomorrow",
                             H6C_SEND_DAY_PERSON if n_me >= H6C_SEND_DAY_PERSON else H6C_SEND_DAY_ORG))
    day = since[:10]
    keys = [f"o:{int(oid)}:{x.strip().lower()}"[:300] for x in rcpts if x]
    for k in keys:
        r = c.execute("SELECT n FROM mail_counts WHERE k=? AND day=?", (k, day)).fetchone()
        if r and r[0] >= H6C_SEND_DAY_RCPT:
            raise Denied(429, tr("This address already got {0} mails from your organisation today; please try again tomorrow", H6C_SEND_DAY_RCPT))
    for k in keys:
        c.execute("""INSERT INTO mail_counts(k,day,n) VALUES(?,?,1) ON CONFLICT(k) DO UPDATE SET
                     n=CASE WHEN mail_counts.day=excluded.day THEN mail_counts.n+1 ELSE 1 END, day=excluded.day""", (k, day))


def inv_datev(c, oid, r, s=None, files=None):
    """Mails PDF + XML of a finalised invoice / credit note to the DATEV document inbox (settings datev_email)."""
    s = s or office_settings(c, oid)
    inv_datev_ready(c, oid, r, s)
    files = files or inv_files(c, oid, r["id"])
    _mail(s["datev_email"], f"{r['kind']} {r['number']}", f"{r['kind']} {r['number']} ({r['date']})", attachments=files)
    ts = iso(now_utc())
    c.execute("UPDATE office_docs SET datev_sent_at=?, updated_at=? WHERE id=? AND org_id=?", (ts, ts, r["id"], oid))
    ofx_log(c, oid, "datev", doc_id=r["id"], detail={"to": s["datev_email"], "files": [f[0] for f in files]})


# ---------------------------------------------------------------- routes
def _answer(c, oid, uid, did, code=200):
    from .docs import doc_public, doc_row
    return jsonify(doc_public(c, oid, doc_row(c, oid, did), office_role(c, uid, oid) == "admin")), code


@app.post("/api/office/docs/<int:did>/invoice")
def inv_from_offer_post(did):
    """An invoice draft from quotation did (every quotation line becomes a position; rights, framework contract, recipient,
    project, language, currency, rate and PO number are taken over; source_doc_id). 201 the invoice."""
    from .docs import doc_row, recalc
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    if r["kind"] != "offer":
        raise Denied(409, tr("Only a quotation can be turned into an invoice"))
    b = body()  # 2.47.0 (#1215): {parts_mode?: full|title|summary, parts_title?} for a quotation with parts
    b = b if isinstance(b, dict) else {}
    typ = b.get("inv_type") or ""  # 2.120.0 A (#2087): progress {amount | pct} / final invoice
    if typ == "progress":
        from .abschlag import abs_progress
        nid = abs_progress(c, oid, uid, r, b.get("amount"), b.get("pct"))
    elif typ == "final":
        from .abschlag import abs_final
        nid = abs_final(c, oid, uid, r, b.get("parts_mode") or None, b.get("parts_title") if isinstance(b.get("parts_title"), str) else None)
    elif typ:
        raise BadInput(tr("Invalid value: {0}", "inv_type"))
    else:
        nid = inv_from_offer(c, oid, uid, r, b.get("parts_mode") or None, b.get("parts_title") if isinstance(b.get("parts_title"), str) else None)
    recalc(c, oid, nid)
    ofx_log(c, oid, "create", doc_id=nid, detail={"kind": "invoice", "from_id": did, "from_number": r["number"], **({"inv_type": typ} if typ else {})})
    bump(c)
    c.commit()
    return _answer(c, oid, uid, nid, 201)


@app.post("/api/office/docs/<int:did>/credit")
def inv_credit_post(did):
    """A credit note draft to the finalised invoice did (positions copied, cancels_id). 201 the credit note."""
    from .docs import doc_row, recalc
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    if r["kind"] != "invoice" or not ofx_locked(r):
        raise Denied(409, tr("A credit note needs a finalised invoice"))
    if r["status"] == "cancelled":
        raise Denied(409, tr("This invoice is already cancelled"))
    nid = inv_credit_of(c, oid, uid, r)
    recalc(c, oid, nid)
    ofx_log(c, oid, "create", doc_id=nid, detail={"kind": "credit", "cancels_id": did, "from_number": r["number"]})
    bump(c)
    c.commit()
    return _answer(c, oid, uid, nid, 201)


@app.post("/api/office/docs/from-time")
def inv_from_time_post():
    """{client_id, from, to, project_id?} -> 201 an invoice draft from the client's time entries (one position per list)."""
    from .docs import recalc
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    nid, n = inv_from_time(c, oid, uid, b)
    recalc(c, oid, nid)
    ofx_log(c, oid, "create", doc_id=nid, detail={"kind": "invoice", "from": "time", "positions": n})
    bump(c)
    c.commit()
    return _answer(c, oid, uid, nid, 201)


@app.post("/api/office/docs/reminder")
def inv_reminder_post():
    """{doc_ids: [...], level: 1|2|3, fee?, deadline_days?} -> 201 a reminder draft over those open invoices."""
    from .docs import recalc
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    nid = inv_make_reminder(c, oid, uid, b)
    recalc(c, oid, nid)
    ofx_log(c, oid, "create", doc_id=nid, detail={"kind": "reminder", "doc_ids": b.get("doc_ids")})
    bump(c)
    c.commit()
    return _answer(c, oid, uid, nid, 201)


def _payment_public(c, r):
    d = dict(r)
    d["amount"] = dstr(d.get("amount") or 0)
    u = c.execute("SELECT display_name, username FROM users WHERE id=?", (r["created_by"],)).fetchone() if r["created_by"] else None
    d["created_by_name"] = (u["display_name"] or u["username"]) if u else ""
    return d


def inv_payments(c, oid, did):
    return [_payment_public(c, r) for r in c.execute("SELECT * FROM office_payments WHERE org_id=? AND doc_id=? ORDER BY date, id", (oid, did))]


@app.get("/api/office/docs/<int:did>/payments")
def inv_payments_get(did):
    from .docs import doc_row
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    pm = inv_paid_map(c, oid, [did])
    return jsonify(payments=inv_payments(c, oid, did), **inv_money_fields(r, pm))


@app.post("/api/office/docs/<int:did>/payments")
def inv_payment_post(did):
    """{date, amount, method?: transfer|cash|card|other, note?} on a finalised invoice; covers the gross -> paid. 201 the document."""
    from .docs import doc_row
    c, uid, oid = _ctx()
    doc_row(c, oid, did)
    if office_role(c, uid, oid) != "admin":  # 2.39.1 (#1210 N3, decided 12.10.): only the organisation's admins book payments
        raise Denied(403, tr("Only an admin of this organisation can record payments"))
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    inv_pay_add(c, oid, uid, did, b)
    bump(c)
    c.commit()
    return _answer(c, oid, uid, did, 201)


def inv_pay_add(c, oid, uid, did, b):
    """2.90.0 B (#1921): records payment b {date, amount, method?, note?} on invoice did of area oid (the caller checked the
    admin role) and refreshes its state; returns the payment's id. Also used by the bank reconciliation (office/bank.py)."""
    from .docs import _date, doc_row
    write_lock(c, f"office_pay_{did}")  # 2.38.0 review: check and write of one invoice's payments in one go
    r = doc_row(c, oid, did)
    if r["kind"] != "invoice" or not ofx_locked(r) or r["status"] in ("cancelled", "paid"):
        raise Denied(409, tr("Payments go on finalised, open invoices only"))
    amt = dec(b.get("amount"), "NaN") if b.get("amount") not in (None, "") else Decimal("NaN")
    if amt.is_nan() or amt <= 0 or amt > Decimal("100000000"):
        raise BadInput(tr("Invalid value: {0}", "amount"))
    d = _date(b.get("date"), "date") or local_now().date().isoformat()
    if d > local_now().date().isoformat():
        raise BadInput(tr("The date must not lie in the future"))
    if money(amt) > dec(inv_money_fields(r, inv_paid_map(c, oid, [did]))["open"]):
        raise Denied(409, tr("The payment exceeds the open amount"))
    method = b.get("method") or "transfer"
    if method not in PAY_METHODS:
        raise BadInput(tr("Invalid value: {0}", "method"))
    note = (b.get("note") or "").strip()[:500] if isinstance(b.get("note"), str) else ""
    pid = insert_id(c, "INSERT INTO office_payments(org_id, doc_id, date, amount, method, note, created_by, created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (oid, did, d, float(money(amt)), method, note, uid, iso(now_utc())))
    inv_refresh_paid(c, oid, did)
    ofx_log(c, oid, "payment", doc_id=did, detail={"id": pid, "date": d, "amount": dstr(amt), "method": method})
    return pid


@app.delete("/api/office/docs/<int:did>/payments/<int:pid>")
def inv_payment_delete(did, pid):
    """The organisation's admin removes a payment (a wrong entry); the state follows."""
    from .docs import doc_row
    c, uid, oid = _ctx()
    doc_row(c, oid, did)
    if office_role(c, uid, oid) != "admin":
        raise Denied(403, tr("Only an admin of this organisation can do this"))
    inv_pay_del(c, oid, did, pid)
    bump(c)
    c.commit()
    return _answer(c, oid, uid, did)


def inv_pay_del(c, oid, did, pid):
    """2.90.0 B (#1921): removes payment pid of invoice did (404 when not there) and refreshes the state; also used by the
    bank reconciliation's undo."""
    write_lock(c, f"office_pay_{did}")
    p = c.execute("SELECT * FROM office_payments WHERE id=? AND doc_id=? AND org_id=?", (pid, did, oid)).fetchone()
    if p is None:
        raise Denied(404)
    c.execute("DELETE FROM office_payments WHERE id=? AND org_id=?", (pid, oid))
    inv_refresh_paid(c, oid, did)
    ofx_log(c, oid, "payment_delete", doc_id=did, detail={"id": pid, "date": p["date"], "amount": dstr(p["amount"])})
    # a bank booking matched by this payment is open again
    c.execute("UPDATE office_bank_tx SET match_kind=NULL, match_id=NULL, payment_id=NULL, matched_by=NULL, matched_at=NULL "
              "WHERE org_id=? AND payment_id=?", (oid, pid))


@app.post("/api/office/docs/<int:did>/send")
def inv_send_post(did):
    """{to, cc?, subject?, text?, datev?: bool} mails the finalised document with its files; status sent."""
    from .docs import doc_row
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    files, datev = inv_send(c, oid, uid, r, b)
    bump(c)
    c.commit()  # 2.38.0 review: the customer mail is recorded before the DATEV copy is tried
    if datev:
        try:
            inv_datev(c, oid, doc_row(c, oid, did), files=files)
        except Denied as e:
            c.rollback()
            raise Denied(409, tr("Sent to the recipient; the copy to the DATEV inbox failed: {0}", e.text()))
        bump(c)
        c.commit()
    resp, code = _answer(c, oid, uid, did)
    return resp, code


@app.post("/api/office/docs/<int:did>/datev")
def inv_datev_post(did):
    """Mails PDF + XML of the finalised invoice / credit note to the DATEV inbox only."""
    from .docs import doc_row
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    if r["kind"] not in ("invoice", "credit"):
        raise Denied(409, tr("Only invoices and credit notes go to the DATEV inbox"))
    inv_datev(c, oid, r)
    bump(c)
    c.commit()
    return _answer(c, oid, uid, did)


@app.get("/api/office/mail-status")
def inv_mail_status():
    """{smtp: bool, datev_email: str} so the send dialog can say when mail is not set up."""
    from ..integrations.mail import MAIL_OUT_ON
    c, uid, oid = _ctx()
    s = office_settings(c, oid)
    if not office_feature(c, oid, "books.datev", s):  # 2.147.0 (#2460): the send dialog shows no DATEV choice
        return jsonify(smtp=bool(MAIL_OUT_ON), datev_email="", datev_auto=0, datev_on=False)
    return jsonify(smtp=bool(MAIL_OUT_ON), datev_email=s.get("datev_email") or "", datev_auto=int(s.get("datev_auto") or 0), datev_on=True)


# ---------------------------------------------------------------- 2.40.0 (#1368 points 8 + 9): reminder fee as an open item, settled reminders
FEE_STATES = ("", "waived", "paid")


def fd_reminder_extra(c, oid, rows):
    """Adds to brief / full reminder dicts: settled (all its invoices paid or cancelled; derived, never stored; state
    "done"), fee_state and fee_open (the fee of a finalised reminder that is neither paid nor waived: it stays open after
    the invoice is paid). Invoice dicts get fee_open / fee_reminders from the reminders that name them."""
    rems = [d for d in rows if d.get("kind") == "reminder"]
    invs = [d for d in rows if d.get("kind") == "invoice"]
    if rems:
        ids = [d["id"] for d in rems]
        meta = {x["id"]: x for x in c.execute(
            "SELECT id, ref_doc_ids, reminder_fee, reminder_fee_state, locked_at, currency, lang FROM office_docs WHERE org_id=? AND id IN ("
            + ",".join("?" * len(ids)) + ")", [oid] + ids)}
        refs = sorted({int(i) for x in meta.values() for i in _j(x["ref_doc_ids"] or "[]", []) if str(i).isdigit()})
        pm = inv_paid_map(c, oid, refs) if refs else {}
        st = {x["id"]: inv_state(x, pm) for x in c.execute(
            "SELECT * FROM office_docs WHERE org_id=? AND id IN (" + ",".join("?" * len(refs)) + ")", [oid] + refs)} if refs else {}
        for d in rems:
            x = meta.get(d["id"])
            if x is None:
                continue
            rid = [int(i) for i in _j(x["ref_doc_ids"] or "[]", []) if str(i).isdigit()]
            fee = money(dec(x["reminder_fee"] or 0))
            d["settled"] = bool(x["locked_at"]) and bool(rid) and all(st.get(i) in ("paid", "cancelled") for i in rid)
            d["fee_state"] = x["reminder_fee_state"] or ""
            d["fee"] = dstr(fee)
            d["fee_open"] = dstr(fee) if x["locked_at"] and fee > 0 and not d["fee_state"] else "0.00"
            d["fee_open_text"] = fmt_money(d["fee_open"], x["lang"], x["currency"])
            if d["settled"]:
                d["state"] = "done"
                d["status_text"] = tr("Settled")
    if invs:
        open_fees = {}
        for x in c.execute("SELECT id, number, ref_doc_ids, reminder_fee FROM office_docs WHERE org_id=? AND kind='reminder' AND locked_at IS NOT NULL "
                           "AND reminder_fee > 0 AND COALESCE(reminder_fee_state, '') = ''", (oid,)):
            for i in _j(x["ref_doc_ids"] or "[]", []):
                open_fees.setdefault(str(i), []).append({"id": x["id"], "number": x["number"], "fee": dstr(money(dec(x["reminder_fee"])))})
        for d in invs:
            fl = open_fees.get(str(d["id"])) or []
            if fl:
                d["fee_reminders"] = fl
                tot = sum((dec(f["fee"]) for f in fl), Decimal(0))
                d["fee_open"] = dstr(tot)
                d["fee_open_text"] = fmt_money(tot, d.get("lang") or "de", d.get("currency") or "EUR")
    return rows


@app.post("/api/office/docs/<int:did>/fee")
def fd_fee_post(did):
    """{state: "waived" | "paid" | ""} the organisation's admin waives the fee of a finalised reminder, marks it paid or
    opens it again. The reminder document stays unchanged (GoBD); the change is logged."""
    from .docs import doc_row
    c, uid, oid = _ctx()
    doc_row(c, oid, did)
    if office_role(c, uid, oid) != "admin":
        raise Denied(403, tr("Only an admin of this organisation can do this"))
    r = doc_row(c, oid, did)
    if r["kind"] != "reminder" or not ofx_locked(r) or money(dec(_col(r, "reminder_fee") or 0)) <= 0:
        raise Denied(409, tr("Only the fee of a finalised reminder can be waived or marked as paid"))
    b = body()
    st = b.get("state") if isinstance(b, dict) else None
    if st not in FEE_STATES:
        raise BadInput(tr("Invalid value: {0}", "state"))
    before = _col(r, "reminder_fee_state") or ""
    if st != before:
        c.execute("UPDATE office_docs SET reminder_fee_state=? WHERE id=? AND org_id=?", (st, did, oid))
        ofx_log(c, oid, "reminder_fee", doc_id=did, detail={"before": before, "after": st, "fee": dstr(money(dec(r["reminder_fee"])))})
        bump(c)
    c.commit()
    return _answer(c, oid, uid, did)
