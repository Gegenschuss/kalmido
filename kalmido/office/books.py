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
   reconciliation) or else their document date, and travel receipts (no input tax); 2.534.0 (#4333): the approved
   entertainment receipts (office/meals.py) on their day, 70 % of the net amount (a small business: of the gross amount)
   as an expense, their input tax in full (field 66). Fixed costs and purchases are plans
   (and would double the receipts): not counted.
 - VAT return figures: "ist" (VAT on payment received, the payments of the period) or "soll" (VAT on invoicing: finalised
   invoices by their date, credit notes negative -- the same documents as the DATEV export); input tax from receipts by
   their document date."""
import csv
import io
import re
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

from flask import Response, g, has_request_context, jsonify, request

from ..core.config import app
from ..core.db import db, local_now
from ..core.access import Denied, live_sql
from ..core.i18n import N_, csv_dialect, tr, trn, lang
from ..core.errors import BadInput
from .abschlag import abs_skonto_rows  # 2.355.0 C (#2840)
from .calc import calc_lang, dec, dstr, money
from .countries import fk_reverse_case, fk_third_country  # 2.355.0 C (#2844); 2.502.0 (#4081)
from .einvoice_in import ei_amount, ei_details, ei_rc_offer  # 2.237.0 C (#2865)
from .homecur import hc_code, hc_doc_fx, hc_home, hc_office_rate
from .ledger import ofx_company  # 2.355.0 C (#2844)
from .model import ofx_name1, office_feature, office_gate, office_need_feature, office_org, office_settings, pb_owner
from .pdf import pdf_money, pdf_paper_ns  # 2.357.0 A (#3156): the office's paper size; 2.534.0 (#4333): pdf_money

BK_NOTE = N_("No tax advice; figures without guarantee.")
BK_VAT = ("19", "7", "0")
PERIOD_RE = re.compile(r"^(m(0[1-9]|1[0-2])|q[1-4]|y)$")  # 2.122.0 D (#2315): y = the whole year
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# document groups of a document without VAT by its note (2.355.0 C #2844: + eu_goods = field 41, export = field 43)
BK_NOVAT_GROUPS = ("small", "reverse", "abroad", "eu_goods", "export")
# 2.545.0 (#4387): the reverse charge marks of a receipt (rc_receipts.rc13b, section 13b UStG): eu = a service of a business in
# another EU state (section 13b (1), UStVA 46 / 47), other = section 13b (2) no. 1, 2, 4-12 (84 / 85); input tax of both: 67
BK_RC13B = ("eu", "other")
BK_LIST_MAX = 500  # rows behind the VAT return figures / of the receipts list
# 2.355.0 C (#2841): the day a payment counts on: a reversal line (p, its payment o joined) on the day of its payment
BK_PAY_DAY = "COALESCE(NULLIF(o.date, ''), p.date)"


from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy
from ..files.store import fs_roles_many  # 2.369.5 (#2517): pulled up from functions; 2.546.0 (#4186): the rights in one go
from .periodlock import period_need_open  # 2.369.5 (#2517): pulled up from functions
from .travel import rk_cat_label, rk_trips  # 2.369.5 (#2517): pulled up from functions
from .meals import BW_SHARE, ofc_bw_booked  # 2.534.0 (#4333): the approved entertainment receipts (layers budget: module level)
from ..core.serializers import csv_cell  # 2.369.5 (#2517): pulled up from functions
from .ledger import ofx_log  # 2.369.5 (#2517): pulled up from functions
from .years import ofc_years, ofc_years_join, ofc_years_sql  # 2.593.0 (#4891): the years with data
from .euerbasis import EB_NORC_LABEL, eb_basis_of, eb_flows, eb_income_payment_ids, eb_map, eb_segments  # noqa: E402 - 2.603.0 (#4927): the basis of the EUeR per year
# 2.755.0 (#5241): eb_map -- an office that never chose "bank and cash" has no edge between two bases


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
    return hc_home(s)  # 2.189.0 B (#2475): the home currency, no longer the currency of new documents


def bk_home_rate(cur, s):
    """2.189.0 B (#2475): (currency code, office rate) of a receipt currency: the home currency -> rate 1; a currency of
    homecur.HC_CODES -> the office rate (hc_office_rate), None when the office has none; unknown or empty -> home."""
    home = hc_home(s)
    cur = hc_code(cur) or home
    return cur, hc_office_rate(s, cur)


def bk_to_home(amount, cur, s):
    """A receipt amount in its currency -> the home currency (2.189.0 B (#2475): every currency of homecur.HC_CODES through
    the office rate, units per one unit of the home currency; no office rate or another currency counts as the home
    currency, as before)."""
    rate = bk_home_rate(cur, s)[1]
    return amount / rate if rate and rate > 0 else amount


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
def bk_receipts(c, oid, frm, to, uid=None, by="paid", gaps=None, paid=None, with_undated=True, zero=False, skip=()):
    """The receipts of office area oid in [frm, to] (ISO days, both included) ->
    [{node_id, date, amount (Decimal gross, office currency), vat_pct, net, vat, category, title, paid_at, doc_date, checked_at,
    checked_by (2.420.0 C, #3448: a person's tick, the user id)}].
    A receipt = a document of the office's documents space with a row in rc_receipts and an amount, not in the trash.
    by="paid": the day = paid_at, else the document date (cash principle, the EUeR); by="doc": the document date, else
    paid_at (input tax). uid: only documents this person sees (default: the signed-in person; 0 = all, for jobs).
    2.356.0 (#3097): gaps = a dict the exports fill with what they leave out: "no_amount" / "no_date" ([titles] of receipts
    this person sees: no amount in the period, no date at all) and "hidden" (count of receipts in folders uid cannot open).
    2.603.0 (#4927): paid = {node id: {day, amount, src, ref}} of the strict basis (office/euerbasis.py eb_flows): only these
    receipts, on the day of their bank / card / cash line and with its amount as the gross (frm / to: the caller's flows);
    each row then carries "src" / "ref" (the line).
    2.610.0 (#4932 review N2 / N3): with_undated=False leaves the receipts without any date out of gaps (a later segment of
    bk_receipts_basis: they were named once already); zero=True keeps the receipts without an amount as rows of amount 0
    (instead of gaps "no_amount": the open receipts of a strict year name them too).
    2.755.0 (#5241): skip = node ids left out before anything is counted (bk_receipts_edge: they count in a strict year)."""
    from ..docs.store import doc_opener  # 2.546.0 (#4186)
    ws = bk_ws(c, oid)
    s = office_settings(c, oid)
    uid = _uid_filter(uid)
    # 2.1115.0 (#5951): rc_receipts.paid_at is a DATE (doc_meta.doc_date text): its day as text, for both types
    day = "COALESCE(NULLIF(CAST(r.paid_at AS text), ''), d.doc_date)" if by == "paid" else "COALESCE(NULLIF(d.doc_date, ''), NULLIF(CAST(r.paid_at AS text), ''))"
    if paid is not None:  # 2.603.0 (#4927): the receipts of the strict basis, whatever their own days say
        ids = sorted(paid)[:20000] or [0]
        rows = c.execute(f"SELECT r.node_id, r.vat_pct, r.rc13b, r.paid_at, r.checked_at, r.checked_by, r.category, d.doc_date, d.amount, d.currency, d.ws, n.name, "
                         f"{day} AS day FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id JOIN fs_nodes n ON n.id=r.node_id "
                         f"WHERE d.ws=? AND n.kind='file' AND n.deleted_at IS NULL AND r.node_id IN ({','.join('?' * len(ids))})",
                         (ws, *ids)).fetchall()
        rows = sorted(rows, key=lambda r: (paid[r["node_id"]]["day"], r["node_id"]))
    else:
        rows = c.execute(f"SELECT r.node_id, r.vat_pct, r.rc13b, r.paid_at, r.checked_at, r.checked_by, r.category, d.doc_date, d.amount, d.currency, d.ws, n.name, "
                         f"{day} AS day FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id JOIN fs_nodes n ON n.id=r.node_id "
                         f"WHERE d.ws=? AND n.kind='file' AND n.deleted_at IS NULL AND {day}>=? AND {day}<=? ORDER BY {day}, r.node_id",
                         (ws, frm, to)).fetchall()
    if skip:
        rows = [r for r in rows if r["node_id"] not in skip]  # 2.755.0 (#5241)
    out, amts, opener = [], {}, {}
    for r in rows:  # 2.546.0 (#4186): the amounts first (key read once), then trash and rights of the rest in one go (fs_roles_many)
        if r["ws"] not in opener:
            opener[r["ws"]] = doc_opener(c, r["ws"], "doc_meta.amount")
        raw = opener[r["ws"]](r["amount"]) or ""
        amts[r["node_id"]] = dec(raw, "0") if raw else dec(0)
    keep0 = gaps is not None or zero
    acc = fs_roles_many(c, [i for i, a in amts.items() if a != 0 or keep0 or (paid is not None and paid[i].get("amount"))], uid)
    for r in rows:
        a = amts[r["node_id"]]
        pl = paid.get(r["node_id"]) if paid is not None else None
        if pl is not None and pl.get("amount"):
            a = pl["amount"]  # 2.603.0 (#4927): the line's amount (home currency) is the gross
        if a == 0 and not keep0:
            continue
        if acc[r["node_id"]][0]:
            continue  # a folder above it is in the trash
        if uid and not acc[r["node_id"]][1]:
            if gaps is not None and a != 0:
                gaps["hidden"] = gaps.get("hidden", 0) + 1
            continue
        if a == 0 and not zero:
            gaps.setdefault("no_amount", []).append(r["name"] or "")
            continue
        cur, rate = bk_home_rate(r["currency"], s)
        if pl is not None and pl.get("amount"):
            cur, rate = hc_home(s), 1  # 2.603.0 (#4927): the bank / card / cash line is in the home currency already
        gross = money(a / rate if rate else a)
        vat_pct = r["vat_pct"] if r["vat_pct"] in BK_VAT else None
        rc13b = r["rc13b"] if r["rc13b"] in BK_RC13B else ""
        rc13b_pct = None
        if rc13b:  # 2.545.0 (#4387): the bill shows no VAT (the amount is net, no input tax paid to the supplier); the office
            rc13b_pct = "7" if vat_pct == "7" else "19"  # owes it at its own rate: 7 when chosen, else 19 (bk_ustva 47 / 85 = 67)
            vat_pct = "0"
        net, vat = _split(gross, vat_pct)
        out.append({"node_id": r["node_id"], "date": pl["day"] if pl is not None else r["day"], "amount": gross, "vat_pct": vat_pct, "net": net, "vat": vat,
                    "rc13b": rc13b, "rc13b_pct": rc13b_pct,
                    "category": r["category"] or "", "title": r["name"] or "", "paid_at": r["paid_at"], "doc_date": r["doc_date"],
                    "unrated": cur if rate is None else None,  # 2.189.0 B (#2475): a foreign receipt without office rate
                    "checked_at": r["checked_at"], "checked_by": r["checked_by"] if r["checked_at"] else None,  # 2.420.0 C (#3448)
                    **({"src": pl["src"], "ref": pl["ref"]} if pl is not None else {})})  # 2.603.0 (#4927)
    if gaps is not None and with_undated:  # 2.356.0 (#3097): receipts without any date belong to no period -- every export names them
        undated = c.execute("SELECT r.node_id, n.name FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id JOIN fs_nodes n ON n.id=r.node_id "
                           "WHERE d.ws=? AND n.kind='file' AND n.deleted_at IS NULL AND COALESCE(NULLIF(CAST(r.paid_at AS text), ''), NULLIF(d.doc_date, '')) IS NULL "
                           "ORDER BY r.node_id LIMIT 1000", (ws,)).fetchall()  # review N4: bounded (named, not all of them)
        acc = fs_roles_many(c, [r["node_id"] for r in undated], uid)  # 2.546.0 (#4186)
        for r in undated:
            if acc[r["node_id"]][0]:
                continue
            if uid and not acc[r["node_id"]][1]:
                gaps["hidden"] = gaps.get("hidden", 0) + 1
                continue
            gaps.setdefault("no_date", []).append(r["name"] or "")
    return out


def bk_paid_all(c, oid):
    """2.743.0 (#4937): {receipt node id: its bank / card / cash line {day, amount, src, ref}} over all days (eb_flows paid)."""
    return eb_flows(c, oid, "0001-01-01", "9999-12-31")["paid"]


def bk_receipts_basis(c, oid, frm, to, by="doc", uid=None, gaps=None, open_=None, prep=None):
    """2.603.0 (#4927): the receipts of [frm, to] by the basis of each year (office/euerbasis.py): "receipts" = bk_receipts(by);
    "bank and cash" = only those with a bank / card / cash line, on its day with its amount (the DATEV export).
    2.610.0 (#4932, the neutral export and the DATEV hints): gaps as bk_receipts (the receipts without a date named once);
    open_ (a list) gets the receipts of a strict year without a bank / card / cash line (by day `by`) -- they do not count and
    the exports name them instead of leaving them out silently (review M2: "without a line" means no line on any day, so a
    receipt of 28.03. paid on 02.04. is not open in March; review N3: receipts without an amount as well, amount 0); prep(a, b, flows) runs before the receipts of a strict
    segment are read (the neutral export takes the entertainment receipts off their lines there, as books.bk_euer)."""
    s = office_settings(c, oid)
    segs = eb_segments(s, frm, to)
    if "bank" not in eb_map(s).values():  # 2.755.0 (#5241): was "no strict year in [frm, to]" -- a receipts year next to a strict one has an edge
        return bk_receipts(c, oid, frm, to, uid=uid, by=by, gaps=gaps)
    out, lines = [], None
    # 2.764.0 (#5314, review 2.755 M1): the bank / card / cash lines are read once and only for the years of [frm, to] and
    # their neighbours (was every day of every year: eb_flows decrypts each bank line) -- a receipt and its line meet at an
    # edge of the bases within a year; a line further away than the next / previous year no longer moves a receipt.
    near = (f"{int(frm[:4]) - 1:04d}-01-01", f"{int(to[:4]) + 1:04d}-12-31")
    for i, (a, b, strict) in enumerate(segs):
        one = i == 0  # review N2: the receipts without any date belong to no period -- named (and counted as hidden) once
        if strict:
            flows = eb_flows(c, oid, a, b)
            if open_ is not None:
                if lines is None:  # review M2: the lines of every day (2.764.0 #5314: of the near years), read once
                    lines = eb_flows(c, oid, *near)["paid"]
                open_ += [rc for rc in bk_receipts(c, oid, a, b, uid=uid, by=by, zero=True) if rc["node_id"] not in lines]
            if prep is not None:
                prep(a, b, flows)
            out += bk_receipts(c, oid, a, b, uid=uid, paid=flows["paid"], gaps=gaps, with_undated=one)
        else:
            if lines is None:  # 2.755.0 (#5241): the bank / card / cash lines, read once (2.764.0 #5314: of the near years)
                lines = eb_flows(c, oid, *near)["paid"]
            out += bk_receipts_edge(c, oid, s, a, b, by, lines, uid=uid, gaps=gaps, with_undated=one)
    if gaps is not None and not gaps.get("no_amount"):
        gaps.pop("no_amount", None)
    return out


def bk_receipts_edge(c, oid, s, a, b, by, lines, uid=None, gaps=None, with_undated=True):
    """2.755.0 (#5241): the receipts of [a, b] (a segment of a receipts year) by bk_receipts(by), at the edge to a strict year
    so that every receipt counts exactly once over the years. lines = {node id: {day, amount, src, ref}} of the bank / card /
    cash lines of every day (eb_flows). Where the two bases meet, the day of the line decides:
     - a receipt whose line lies in a strict year counts there (on the line's day), never here as well;
     - a receipt whose own day (by `by`) lies in a strict year but whose line lies in [a, b] counts here, on the line's day and
       with its amount (the strict year left it open: no line in that year).
    Receipts without a line and the years away from an edge count as before."""
    strict = lambda day: bool(day) and eb_basis_of(s, int(day[:4])) == "bank"  # noqa: E731
    gone = {n for n, x in lines.items() if strict(x["day"])}
    rows = bk_receipts(c, oid, a, b, uid=uid, by=by, gaps=gaps, with_undated=with_undated, skip=gone)
    cand = sorted(n for n, x in lines.items() if a <= x["day"] <= b)[:20000]  # 2.764.0 (#5314): bounded as bk_receipts(paid)
    if not cand:
        return rows
    day = "COALESCE(NULLIF(CAST(r.paid_at AS text), ''), d.doc_date)" if by == "paid" else "COALESCE(NULLIF(d.doc_date, ''), NULLIF(CAST(r.paid_at AS text), ''))"
    own = {r["node_id"]: r["day"] for r in c.execute(f"SELECT r.node_id, {day} AS day FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id "
                                                      f"WHERE d.ws=? AND r.node_id IN ({','.join('?' * len(cand))})", (bk_ws(c, oid), *cand)).fetchall()}
    moved = {n: lines[n] for n in cand if strict(own.get(n))}
    if not moved:
        return rows
    extra = bk_receipts(c, oid, a, b, uid=uid, paid=moved, gaps=gaps, with_undated=False)
    return sorted(rows + extra, key=lambda rc: (rc["date"] or "", rc["node_id"]))


def bk_gaps_text(gaps, missing=()):
    """2.356.0 (#3097): the text of missing.txt in an export ZIP -- the files that could not be read (missing: [(where, name)])
    and the receipts left out (gaps of bk_receipts); "" when nothing is missing."""
    out = []
    if missing:
        out.append(tr("Files that could not be read (damaged or missing) - the list names them, the ZIP does not hold them:"))
        out += [f"- {w}: {n}" for w, n in missing]
    if gaps.get("no_date"):
        out.append(tr("Receipts without a date (not in the export, complete them under Office > Receipts):"))
        out += [f"- {n}" for n in gaps["no_date"]]
    if gaps.get("no_amount"):
        out.append(tr("Receipts without an amount (not in the export, complete them under Office > Receipts):"))
        out += [f"- {n}" for n in gaps["no_amount"]]
    if gaps.get("hidden"):
        out.append(trn("{0} receipt lies in a folder you cannot open and is not in this export; the GoBD export holds it.", "{0} receipts lie in folders you cannot open and are not in this export; the GoBD export holds them.", gaps["hidden"]))
    return "\r\n".join(out) + ("\r\n" if out else "")


BK_OFFER_MAX = 100  # 2.237.0 C (#2865): e-invoices waiting to be taken over as receipts, newest first


def bk_einv_offers(c, oid, uid=None):
    """2.237.0 C (#2865): the e-invoices in the documents space of office area oid that are no receipt yet (an incoming one
    becomes a receipt only once a person takes it over, office/einvoice_in.py ei_take) -> [{node_id, title, date, amount,
    supplier, vat_pct}]; not those a person took out of the receipts (_eirc) or the office issued itself (ei_rc_offer)."""
    from ..docs.store import doc_open, meta_json, meta_row
    uid = _uid_filter(uid)
    rows = c.execute("SELECT d.node_id FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE d.ws=? AND d.method='e-invoice' "
                     "AND n.kind='file' AND n.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM rc_receipts r WHERE r.node_id=d.node_id) "
                     "ORDER BY d.node_id DESC LIMIT ?", (bk_ws(c, oid), BK_OFFER_MAX * 2)).fetchall()
    out, acc = [], fs_roles_many(c, [r["node_id"] for r in rows], uid)  # 2.546.0 (#4186): trash + rights in one go
    for r in rows:
        if acc[r["node_id"]][0] or (uid and not acc[r["node_id"]][1]):
            continue
        m = meta_row(c, r["node_id"])
        inv = ei_rc_offer(c, m) if m else None
        if inv is None or meta_json(c, m, "extracted", {}).get("_eirc"):
            continue
        n = c.execute("SELECT name FROM fs_nodes WHERE id=?", (r["node_id"],)).fetchone()
        out.append({"node_id": r["node_id"], "title": n["name"] if n else "", "date": m["doc_date"] or inv.get("date") or "",
                    "amount": str(ei_amount(inv) or doc_open(c, m["ws"], "doc_meta.amount", m["amount"]) or ""),
                    "currency": inv.get("currency") or m["currency"] or "",
                    "supplier": (inv.get("seller") or {}).get("name") or "", "vat_pct": ei_details(inv).get("vat_pct")})
        if len(out) >= BK_OFFER_MAX:
            break
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
    period_need_open(c, oid, r["paid_at"], day)  # 2.148.0 A (#2471): a payment day in a locked month stays
    if r["paid_at"] and not day:
        from ..receipts.suggest import olk_rc_keep
        olk_rc_keep(c, node_id)  # 2.186.0 B (#2600): removing the payment day (also a bank match taken back) keeps the lock
    c.execute("UPDATE rc_receipts SET paid_at=? WHERE node_id=?", (day or None, node_id))
    return r["paid_at"]


# ---------------------------------------------------------------- income: the parts of a document
def _fx(r, home):
    """The rate of document row r to the home currency (amount / rate = home currency), as the cash flow."""
    return hc_doc_fx(r, home)  # 2.189.0 B (#2475): every foreign currency


def bk_doc_parts(r):
    """[(group, share of the gross, pct)] of an invoice / credit note: a document without VAT by its note (small = small
    business, reverse = reverse charge to a business in the EU, abroad = not taxable domestically, else exempt); with VAT
    its tax lines (group "vat19" / "vat7" / "vat<pct>", 0 % = exempt), shares by each line's gross."""
    if (r["vat_mode"] or "vat") == "novat":
        note = (r["vat_note"] if "vat_note" in r.keys() else "") or ""
        return [(note if note in BK_NOVAT_GROUPS else "exempt", Decimal(1), Decimal(0))]
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
            "abroad": tr("Tax-free revenue / reverse charge"), "exempt": tr("Tax-free revenue / reverse charge"),
            "fee": tr("Reminder fees received (not taxable)"),  # 2.545.0 (#4387)
            "bank": tr("Money received without invoice")}[key]  # 2.603.0 (#4927): the strict basis


def bk_reverse_key(c, oid, r, memo):
    """2.355.0 C (#2844): the tax case of reverse charge document r: "reverse_dom" for a client in the office's own country
    (section 13b UStG, field 60), "reverse" for another EU state (field 21); 2.502.0 (#4081): "abroad" for a third country,
    finalised before the refusal in inv_missing (field 45). The client's country of the snapshot, else the live client."""
    if "home" not in memo:
        memo["home"] = ofx_company(c, oid).get("country") or "DE"
    cc = _j(r["recipient_snapshot"] if "recipient_snapshot" in r.keys() else "").get("country") or ""
    if not cc and r["client_id"]:
        cl = c.execute("SELECT country FROM clients WHERE id=?", (r["client_id"],)).fetchone()
        cc = (cl["country"] if cl else "") or ""
    if fk_reverse_case(cc, memo["home"]) == "domestic":
        return "reverse_dom"
    return "abroad" if fk_third_country(cc, memo["home"]) else "reverse"


def bk_pay_docs(c, oid, frm, to):
    """2.525.0 (#4187): the invoices / credit notes (no trial ones) with a payment in [frm, to] by the filter of bk_payments;
    was every document of every year."""
    return c.execute(f"SELECT * FROM office_docs WHERE org_id=? AND kind IN ('invoice', 'credit') AND trial=0 AND {live_sql()} AND id IN "
                     "(SELECT p.doc_id FROM office_payments p LEFT JOIN office_payments o ON o.id=p.reverses_id AND o.org_id=p.org_id "
                     f"WHERE p.org_id=? AND {BK_PAY_DAY}>=? AND {BK_PAY_DAY}<=?)", (oid, oid, frm, to)).fetchall()


def bk_payments(c, oid, frm, to, home):
    """[(payment row, document row)] of invoices / credit notes paid in [frm, to] (ISO days, both included)."""
    # 2.144.10 B (#2576): trial documents never reach the books
    docs = {r["id"]: r for r in bk_pay_docs(c, oid, frm, to)}
    out = []
    # 2.355.0 C (#2841): a reversal line counts on the day of the payment it takes back (was the day of the correction)
    for p in c.execute(f"SELECT p.id, p.doc_id, {BK_PAY_DAY} AS date, p.amount FROM office_payments p LEFT JOIN office_payments o "
                       f"ON o.id=p.reverses_id AND o.org_id=p.org_id WHERE p.org_id=? AND {BK_PAY_DAY}>=? AND {BK_PAY_DAY}<=? "
                       "ORDER BY 3, p.id", (oid, frm, to)):
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


OFC_MEAL_TWICE = N_("Entertainment receipts count from Office > Entertainment receipts. A restaurant bill that also lies under Receipts counts twice: keep it in one place only.")


def ofc_meals_home(c, oid, frm, to, s):
    """2.534.0 (#4333): the approved meals of [frm, to] (meals.ofc_bw_booked) in the office currency: [{id, date, title,
    gross, vat, net, deductible, not_deductible (Decimal), unrated}] -- net and the 70 / 30 split include the tip (bw_calc).
    A currency without an office rate counts 1:1 (unrated = its code), as the receipts do."""
    out = []
    for m in ofc_bw_booked(c, oid, frm, to):
        cur, rate = bk_home_rate(m["currency"], s)
        f = lambda v: money(dec(v) / rate) if rate else money(dec(v))  # noqa: E731
        k = m["calc"]
        net, ded = f(k["net"]), f(k["deductible"])
        out.append({"id": m["id"], "date": m["date"], "title": m["title"], "gross": f(k["gross"]), "vat": f(k["vat"]), "net": net,
                    "deductible": ded, "not_deductible": net - ded, "unrated": cur if rate is None else None,
                    "pay": m.get("pay"),  # 2.603.0 (#4927): (kind, id) of its bank / cash / card line or None
                    "rates": [(dec(x["rate"]), f(x["net"]), f(x["vat"])) for x in k.get("lines") or []],  # 2.616.0 (#4563): per line
                    "tip": f(k.get("tip") or 0)})
    return out


def ofc_meals_euer(meals, small):
    """2.534.0 (#4333), bk_euer: (expense line values [net, vat, gross], summary {count, gross, vat, deductible, not_deductible}).
    70 % of the net amount is an expense, its input tax counts in full (section 4 (5) no. 2 EStG, section 15 UStG); a small
    business deducts no input tax: 70 % of the gross amount (meals.BW_SHARE)."""
    z = Decimal(0)
    gross = sum((m["gross"] for m in meals), z)
    if small:
        ded = sum((money(m["gross"] * BW_SHARE) for m in meals), z)
        vat, nd = z, gross - ded
    else:
        ded = sum((m["deductible"] for m in meals), z)
        vat, nd = sum((m["vat"] for m in meals), z), sum((m["not_deductible"] for m in meals), z)
    return [ded, vat, ded + vat], {"count": len(meals), "gross": dstr(money(gross)), "vat": dstr(money(vat)),
                                   "deductible": dstr(money(ded)), "not_deductible": dstr(money(nd))}


def bk_fees_paid(c, oid, frm, to, home):
    """2.545.0 (#4387): the paid fees of finalised reminders in [frm, to] (ISO days): [{doc_id, number, date, amount (Decimal,
    home currency)}]. The day = reminder_fee_paid_at (set when a person marks the fee paid), before 2.545 the reminder's date.
    A reminder fee is damages, not a sale: no VAT, not in the VAT return (the tax advisor checks, #1153)."""
    day = "COALESCE(NULLIF(CAST(reminder_fee_paid_at AS text), ''), date)"  # 2.1115.0 (#5951): DATE
    out = []
    for r in c.execute(f"SELECT id, number, currency, fx_rate, reminder_fee, {day} AS day FROM office_docs WHERE org_id=? AND kind='reminder' "
                       f"AND locked_at IS NOT NULL AND {live_sql()} AND trial=0 AND reminder_fee > 0 AND reminder_fee_state='paid' AND {day}>=? AND {day}<=? "
                       f"ORDER BY {day}, id", (oid, frm, to)).fetchall():
        out.append({"doc_id": r["id"], "number": r["number"], "date": r["day"], "amount": money(dec(r["reminder_fee"]) / _fx(r, home))})
    return out


# ---------------------------------------------------------------- EUeR
def bk_euer(c, oid, year):
    """The income / expense statement of a year (see the module text); amounts as text with two decimals."""
    s = office_settings(c, oid)
    home = _home(s)
    small = bool(s.get("small_business"))
    y0, y1 = f"{year}-01-01", f"{year}-12-31"
    inc = {}
    # 2.603.0 (#4927): the basis "bank" (strict): only what flowed through the bank, the cash book or a card (office/euerbasis.py)
    strict = eb_basis_of(s, year) == "bank"
    flows = eb_flows(c, oid, y0, y1) if strict else None
    inc_ids = eb_income_payment_ids(c, oid) if strict else None
    pay_outside = 0
    # 2.534.0 (#4333): the approved entertainment receipts (office/meals.py); 2.603.0 (#4927): strict = through their line only
    meals = bk_meals_strict(c, oid, flows, y0, y1, s) if strict else bk_meals_receipts(c, oid, y0, y1, s)  # 2.764.0 (#5313): + the edge
    for p, r in bk_payments(c, oid, y0, y1, home):
        if strict and p["id"] not in inc_ids:
            pay_outside += 1  # (6) a payment typed by hand without its bank / cash booking does not count
            continue
        for k, gross, net, vat in _pay_parts(p, r, home):
            k = "exempt" if k in ("reverse", "abroad", "eu_goods", "export") else k  # 2.355.0 C (#2844): + goods
            x = inc.setdefault(k, [Decimal(0)] * 3)
            x[0], x[1], x[2] = x[0] + net, x[1] + vat, x[2] + gross
    for f in bk_fees_paid(c, oid, y0, y1, home):  # 2.545.0 (#4387): paid reminder fees, without VAT
        x = inc.setdefault("fee", [Decimal(0)] * 3)
        x[0], x[2] = x[0] + f["amount"], x[2] + f["amount"]
    for t in (flows["income_open"] if strict else []):  # 2.603.0 (#4927): money received that no invoice matched (warning)
        x = inc.setdefault("bank", [Decimal(0)] * 3)
        x[0], x[2] = x[0] + t["amount"], x[2] + t["amount"]
    exp, missing, unrated = {}, 0, set()
    # 2.92.0 (#1931): equipment with a purchase price is depreciated (office/assets.py ast_afa_year): the year's depreciation
    # is an expense of its own, the device's receipt counts only with its input tax (else the purchase would count twice).
    # A small business keeps the receipt as it is (its depreciation basis would be the gross price, assets.py works net)
    afa = {"rows": [], "receipt_ids": set(), "no_receipt": []}
    if not small:
        from .assets import ast_afa_year
        afa = ast_afa_year(c, oid, year)
    # 2.755.0 (#5241): a receipts year at the edge to a strict one: the day of the line decides (bk_receipts_edge), as the VAT figures
    for rc in (bk_receipts(c, oid, y0, y1, paid=flows["paid"]) if strict else bk_receipts_basis(c, oid, y0, y1, by="paid")):
        k = "c:" + rc["category"].casefold() if rc["category"] else "c:"
        x = exp.setdefault(k, {"label": rc["category"] or tr("Other"), "v": [Decimal(0)] * 3, "count": 0})
        if rc["node_id"] in afa["receipt_ids"]:
            x["v"] = [x["v"][0], x["v"][1] + rc["vat"], x["v"][2] + rc["vat"]]
        else:
            x["v"] = [x["v"][0] + rc["net"], x["v"][1] + rc["vat"], x["v"][2] + rc["amount"]]
        x["count"] += 1
        if rc["vat_pct"] is None:
            missing += 1
        if rc["unrated"]:
            unrated.add(rc["unrated"])
    for a_ in afa["rows"]:
        x = exp.setdefault("a:", {"label": tr("Depreciation"), "v": [Decimal(0)] * 3, "count": 0})
        x["v"] = [x["v"][0] + a_["amount"], x["v"][1], x["v"][2] + a_["amount"]]
        x["count"] += 1
    for x in (flows["norc"] if strict else []):  # 2.603.0 (#4927): (2) bank / cash / card lines without a receipt: gross, no input tax
        k = exp.setdefault("b:", {"label": tr("Bookings without receipt"), "v": [Decimal(0)] * 3, "count": 0}) if x["missing"] else \
            exp.setdefault("n:", {"label": tr("Bookings that need no receipt"), "v": [Decimal(0)] * 3, "count": 0})
        k["v"] = [k["v"][0] + x["amount"], k["v"][1], k["v"][2] + x["amount"]]
        k["count"] += 1
    # 2.536.0 (#4334): card fees and interest without a receipt, as the DATEV export books them (office/cardnorc.py; no input tax)
    from .cardnorc import cc_norc_lines
    for x in cc_norc_lines(c, oid, y0, y1):
        k = exp.setdefault("k:", {"label": tr("Card fees without receipt"), "v": [Decimal(0)] * 3, "count": 0})
        k["v"] = [k["v"][0] + x["amount"], k["v"][1], k["v"][2] + x["amount"]]
        k["count"] += 1
    for t in bk_trips_near(c, oid, y0, y1):  # 2.764.0 (#5313): was rk_trips(year) -- an item of a trip of the next / last year
        for it in t["items"]:
            day = it["date"] or t["date_from"] or ""
            if not (y0 <= day <= y1):
                continue
            a = dec(it["amount_home"] or 0)
            x = exp.setdefault("t:" + (it["category"] or "other"), {"label": tr("Travel expenses") + ": " + rk_cat_label(it["category"] or "other"),
                                                                    "v": [Decimal(0)] * 3, "count": 0})
            # 2.545.0 (#4387): a travel receipt with a VAT rate counts net + its input tax (a small business: gross, no input tax)
            net, vat = _split(a, None if small else it.get("vat_pct"))
            x["v"] = [x["v"][0] + net, x["v"][1] + vat, x["v"][2] + a]
            x["count"] += 1
    # 2.93.0 B (#1928): the mileage allowance of the logbook (business drives with a private car; no input tax)
    from .logbook import lb_allowance_year
    km = lb_allowance_year(c, oid, year)
    if km["count"]:
        exp["km"] = {"label": tr("Mileage allowance"), "v": [km["amount"], Decimal(0), km["amount"]], "count": km["count"]}
    # 2.534.0 (#4333): the approved entertainment receipts (office/meals.py): 70 % as an expense, the input tax in full
    meal_sum, meal_notes = None, []
    if meals:
        v, meal_sum = ofc_meals_euer(meals, small)
        exp["m:"] = {"label": tr("Entertainment (70 % deductible)"), "v": v, "count": len(meals)}
        unrated |= {m["unrated"] for m in meals if m["unrated"]}
        meal_notes = [tr("Entertainment: {0} (30 %) are not deductible and are not in the expenses.",
                         pdf_money(meal_sum["not_deductible"], calc_lang(lang()), home)),
                      tr(OFC_MEAL_STRICT if strict else OFC_MEAL_TWICE)]
        meal_sum["notes"] = meal_notes
    m2 = lambda v: dstr(money(v))  # noqa: E731
    order = lambda k: (0, -int(dec(k[3:]))) if k.startswith("vat") else ({"exempt": 1, "fee": 3}.get(k, 2), 0)  # noqa: E731
    income = [{"key": k, "label": _income_label(k), "net": m2(v[0]), "vat": m2(v[1]), "gross": m2(v[2])}
              for k, v in sorted(inc.items(), key=lambda kv: order(kv[0]))]
    expenses = [{"key": k, "label": x["label"], "net": m2(x["v"][0]), "vat": m2(x["v"][1]), "gross": m2(x["v"][2]), "count": x["count"]}
                for k, x in sorted(exp.items(), key=lambda kv: (kv[0] == "km", kv[0][:2] == "t:", kv[0] == "m:", kv[0] in ("b:", "n:"), kv[0] == "c:", kv[1]["label"].casefold()))]
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
            "notes": [tr(BK_NOTE), tr(BK_STRICT_NOTE) if strict else tr("Income = payments received (cash principle); expenses = receipts and travel expenses.")]
            + ([tr("Mileage allowance from the logbook (business drives with a private car).")] if km["count"] else [])
            # 2.189.0 B (#2475): receipts in a foreign currency without an office rate count 1:1 in the home currency
            + [tr("Receipts in {0} without an exchange rate in the office settings count as {1}.", x, home) for x in sorted(unrated)]
            + meal_notes,  # 2.534.0 (#4333)
            "unrated": sorted(unrated), "meals": meal_sum,
            "afa_no_receipt": afa["no_receipt"],  # 2.536.0 (#4335): depreciated devices without a linked receipt (the client warns)
            "basis": "bank" if strict else "receipts", "warnings": bk_strict_warnings(c, oid, y0, y1, flows, pay_outside) if strict else None}


BK_STRICT_NOTE = N_("Basis: bank and cash (strict). Income = payments received through the bank or the cash book; expenses = the bookings of the bank, the cash book and the credit cards with their receipts. Depreciation, travel expenses and the mileage allowance count as before.")
OFC_MEAL_STRICT = N_("Entertainment receipts count only through their bank, cash or card booking (their proof), never as an expense of their own.")
BK_WARN_MAX = 200


BK_MEAL_WINDOW = 62  # days: a meal may be paid up to two months before / after its date (the line's day counts)


def bk_meals_strict(c, oid, flows, frm, to, s):
    """2.603.0 (#4927) point 5, the strict basis: the approved meals that hang on a bank / cash / card line of the flows of
    [frm, to] (office_meals.pay_kind / pay_id, office/mealpay.py), on the line's day. That line leaves the flows (its receipt
    or "without receipt"): the meal gives its 70 / 30 split instead, no second expense. A meal without a line does not count.
    Changes flows in place -> the meals that count (ofc_meals_home rows)."""
    lines = {(x["src"], x["ref"]): ("paid", nid) for nid, x in flows["paid"].items()}
    lines.update({(x["src"], x["ref"]): ("norc", i) for i, x in enumerate(flows["norc"])})
    d0 = (date.fromisoformat(frm) - timedelta(days=BK_MEAL_WINDOW)).isoformat()
    d1 = (date.fromisoformat(to) + timedelta(days=BK_MEAL_WINDOW)).isoformat()
    out, nodes, norc = [], set(), set()
    for m in ofc_meals_home(c, oid, d0, d1, s):
        w = lines.get(tuple(m["pay"])) if m.get("pay") else None
        if w is None or (w[0] == "norc" and w[1] in norc) or (w[0] == "paid" and w[1] in nodes):
            continue
        day = flows["paid"][w[1]]["day"] if w[0] == "paid" else flows["norc"][w[1]]["day"]
        out.append(dict(m, date=day))
        (nodes if w[0] == "paid" else norc).add(w[1])
    for nid in nodes:
        flows["paid"].pop(nid, None)
    flows["norc"][:] = [x for i, x in enumerate(flows["norc"]) if i not in norc]
    return out


def bk_trips_near(c, oid, frm, to):
    """2.764.0 (#5313): the trips whose items may lie in [frm, to] -- those of the years of [frm, to] and their neighbours, each
    once: an item keeps its own day (a ticket bought in December for a trip in January), so a trip of the next year may
    have an item of this one (rk_trips(year) alone left it out of both years)."""
    out = {}
    for y in range(int(frm[:4]) - 1, int(to[:4]) + 2):
        for t in rk_trips(c, oid, year=str(y)):
            out.setdefault(t["id"], t)
    return list(out.values())


def bk_meals_receipts(c, oid, a, b, s):
    """2.764.0 (#5313): the approved meals of [a, b] (a segment of a receipts year) as ofc_meals_home, at the edge to a strict year
    so that every meal counts exactly once over the years -- the rule of the receipts (bk_receipts_edge, #5241) for the meals:
     - a meal whose line (office_meals.pay_kind / pay_id) lies in a strict year counts there (bk_meals_strict, on the line's day),
       never here as well -- as long as that year takes it (its date within BK_MEAL_WINDOW days of that year);
     - a meal whose own date lies in a strict year but whose line lies in [a, b] counts here, on the line's day (the strict year
       does not count a meal without a line in it).
    The lines are read for the years of [a, b] and their neighbours only (as bk_receipts_basis, #5314)."""
    if "bank" not in eb_map(s).values():
        return ofc_meals_home(c, oid, a, b, s)
    strict = lambda day: bool(day) and eb_basis_of(s, int(day[:4])) == "bank"  # noqa: E731
    n0, n1 = f"{int(a[:4]) - 1:04d}-01-01", f"{int(b[:4]) + 1:04d}-12-31"
    fl = eb_flows(c, oid, n0, n1)
    days = {(x["src"], x["ref"]): x["day"] for x in fl["paid"].values()}
    days.update({(x["src"], x["ref"]): x["day"] for x in fl["norc"]})
    w = timedelta(days=BK_MEAL_WINDOW)

    def taken(day, line):  # the strict year of the line takes the meal (bk_meals_strict reads meals this close to its year)
        y = int(line[:4])
        return (date(y, 1, 1) - w).isoformat() <= day <= (date(y, 12, 31) + w).isoformat()

    out = []
    for m in ofc_meals_home(c, oid, n0, n1, s):
        line = days.get(tuple(m["pay"])) if m.get("pay") else None
        if a <= m["date"] <= b:
            if not (line and strict(line) and taken(m["date"], line)):
                out.append(m)
        elif line and a <= line <= b and strict(m["date"]):
            out.append(dict(m, date=line))
    return sorted(out, key=lambda m: (m["date"], m["id"]))


def bk_strict_warnings(c, oid, frm, to, flows, pay_outside):
    """2.603.0 (#4927): what the strict basis warns about -> {missing_receipt: [{day, amount, src, ref, text}] (bookings
    without a receipt, point 2), missing_count, income_open: [...] (money received without an invoice), card_diff: [...]
    (a card total that differs from its statement, point 3), open_receipts (receipts of the period without a bank, cash or card
    line: they do not count, point 1), payments_outside (invoice payments without a bank / cash booking, point 6)}."""
    mis = [x for x in flows["norc"] if x["missing"]]
    paid = bk_paid_all(c, oid)  # 2.743.0 (#4937): a line on any day (a receipt of 28.12. paid in January is not open)
    opened = sum(1 for rc in bk_receipts(c, oid, frm, to) if rc["node_id"] not in paid)
    row = lambda x: {"day": x["day"], "amount": dstr(money(x["amount"])), "src": x.get("src", "bank"), "ref": x["ref"], "text": x.get("text") or ""}  # noqa: E731
    return {"missing_receipt": [row(x) for x in mis[:BK_WARN_MAX]], "missing_count": len(mis), "label": tr(EB_NORC_LABEL),
            "income_open": [row(x) for x in flows["income_open"][:BK_WARN_MAX]],
            "card_diff": [{"ref": x["ref"], "day": x["day"], "booking": dstr(x["booking"]), "statement": dstr(x["statement"])} for x in flows["card_diff"]],
            "open_receipts": opened, "payments_outside": pay_outside}


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
    with reverse charge (vat_note "reverse", section 18b UStG); 60 = reverse charge to a client at home (section 13b (5));
    41 = goods to businesses in the EU (vat_note "eu_goods", section 6a); 43 = exports of goods (vat_note "export",
    section 6); 45 = other sales not taxable domestically (vat_note "abroad", e.g. services to a third country); 48 = other
    tax-free sales (no note / 0 % lines, section 4 no. 8-28, also listed as exempt_other); 66 = input tax from receipts with
    a VAT rate; 83 = the advance payment (VAT minus input tax; negative = a refund). Bases in whole euros (cut off), taxes in
    cents computed from the bases as ELSTER does. 2.355.0 C (#2841, #2844): + 41 / 43 / 48 / 60; a cash discount taken
    lowers the bases of the accrual basis ("soll") in the period of its payment (#2840)."""
    s = office_settings(c, oid)
    home = _home(s)
    frm, to = bk_period(year, period)
    basis = s.get("vat_basis") if s.get("vat_basis") in ("ist", "soll") else "ist"
    strict = eb_basis_of(s, year) == "bank"  # 2.603.0 (#4927): the strict basis of the EUeR also for the VAT figures
    head = {"year": year, "period": period, "from": frm, "to": to, "basis": basis, "currency": home, "note": tr(BK_NOTE),
            "euer_basis": "bank" if strict else "receipts"}
    if s.get("small_business"):
        return dict(head, small_business=True)
    flows = eb_flows(c, oid, frm, to) if strict else None
    inc_ids = eb_income_payment_ids(c, oid) if strict and basis == "ist" else None
    meals = bk_meals_strict(c, oid, flows, frm, to, s) if strict else bk_meals_receipts(c, oid, frm, to, s)  # 2.603.0 (#4927): before the receipts; 2.764.0 (#5313): + the edge
    sums, items = {}, []

    memo = {}

    def add(k, net, vat, r=None):
        if k == "reverse" and r is not None:
            k = bk_reverse_key(c, oid, r, memo)  # 2.355.0 C (#2844): section 13b at home = field 60, not 21; 2.502.0 (#4081): a third country = 45
        x = sums.setdefault(k, [Decimal(0), Decimal(0)])
        x[0], x[1] = x[0] + net, x[1] + vat

    if basis == "ist":
        for p, r in bk_payments(c, oid, frm, to, home):
            if inc_ids is not None and p["id"] not in inc_ids:
                continue  # 2.603.0 (#4927): (6) only payments of a bank / cash booking
            gross_all = Decimal(0)
            for k, gross, net, vat in _pay_parts(p, r, home):
                add(k, net, vat, r)
                gross_all += gross
            items.append({"kind": r["kind"], "doc_id": r["id"], "number": r["number"], "date": p["date"], "gross": dstr(money(gross_all)),
                          "source": "payment"})
    else:
        for r in c.execute(f"SELECT * FROM office_docs WHERE org_id=? AND kind IN ('invoice','credit') AND locked_at IS NOT NULL AND {live_sql()} "
                           "AND trial=0 AND number != '' AND date>=? AND date<=? ORDER BY date, number", (oid, frm, to)).fetchall():
            t = _j(r["totals"])
            fx, sign = _fx(r, home), (-1 if r["kind"] == "credit" else 1)
            gross = dec(t.get("gross") or 0) / fx * sign
            for k, share, pct in bk_doc_parts(r):
                part = gross * share
                net = part * 100 / (100 + pct) if pct > 0 else part
                add(k, net, part - net, r)
            items.append({"kind": r["kind"], "doc_id": r["id"], "number": r["number"], "date": r["date"], "gross": dstr(money(gross)),
                          "source": "document"})
        # 2.355.0 C (#2840): a cash discount taken reduces the base (section 17 UStG) per tax rate, in the period of its payment
        for r, sk in abs_skonto_rows(c, oid, frm, to):
            minus = -sk["amount"] / _fx(r, home)
            for k, share, pct in bk_doc_parts(r):
                part = minus * share
                net = part * 100 / (100 + pct) if pct > 0 else part
                add(k, net, part - net, r)
            items.append({"kind": "skonto", "doc_id": r["id"], "number": r["number"], "date": sk["day"], "gross": dstr(money(minus)),
                          "source": "skonto"})
    kz66, missing = Decimal(0), 0
    r13 = {"eu": [Decimal(0), Decimal(0)], "other": [Decimal(0), Decimal(0)]}  # 2.545.0 (#4387): [base, tax] of 46 / 47, 84 / 85
    # 2.603.0 (#4927): the strict basis: the input tax of the receipts with a bank / card / cash line, on the line's day
    # 2.755.0 (#5241): a receipts year: by the document date as before, but at the edge to a strict year the day of the bank / card /
    # cash line decides (bk_receipts_edge) -- every receipt gives its input tax exactly once over the years, as the exports count it
    for rc in (bk_receipts(c, oid, frm, to, paid=flows["paid"]) if strict else bk_receipts_basis(c, oid, frm, to, by="doc")):
        if rc["rc13b"]:
            x = r13[rc["rc13b"]]
            x[0], x[1] = x[0] + rc["net"], x[1] + money(rc["net"] * dec(rc["rc13b_pct"]) / 100)
        kz66 += rc["vat"]
        missing += rc["vat_pct"] is None
        items.append({"kind": "receipt", "node_id": rc["node_id"], "title": rc["title"], "date": rc["date"], "gross": dstr(rc["amount"]),
                      "vat": dstr(rc["vat"]), "vat_pct": rc["vat_pct"], "rc13b": rc["rc13b"] or None})
    # 2.545.0 (#4387): the input tax of travel receipts with a VAT rate (by the receipt's day, else the trip's start)
    for t in bk_trips_near(c, oid, frm, to):  # 2.764.0 (#5313): was rk_trips(year) -- an item of a trip of the next / last year
        for it in t["items"]:
            day = it["date"] or t["date_from"] or ""
            if not (frm <= day <= to) or not it.get("vat_pct"):
                continue
            gross = money(dec(it["amount_home"] or 0))
            vat = _split(gross, it["vat_pct"])[1]
            kz66 += vat
            items.append({"kind": "travel", "trip_id": t["id"], "title": it.get("text") or rk_cat_label(it["category"] or "other"), "date": day,
                          "gross": dstr(gross), "vat": dstr(vat), "vat_pct": it["vat_pct"]})
    # 2.534.0 (#4333): the input tax of the approved entertainment receipts counts in full (by the day of the meal)
    for m in meals:
        kz66 += m["vat"]
        items.append({"kind": "meal", "meal_id": m["id"], "title": m["title"], "date": m["date"], "gross": dstr(m["gross"]),
                      "vat": dstr(m["vat"]), "vat_pct": None})
    b = lambda k: sums.get(k, [Decimal(0)] * 2)[0]  # noqa: E731
    kz81, kz86 = _euro_floor(b("vat19")), _euro_floor(b("vat7"))
    others = [k for k in sums if k.startswith("vat") and k not in ("vat19", "vat7")]
    kz35 = _euro_floor(sum((b(k) for k in others), Decimal(0)))
    kz36 = money(sum((sums[k][1] for k in others), Decimal(0)))  # mixed rates: the tax itself, not computed from the base
    t19, t7 = money(kz81 * 19 / 100), money(kz86 * 7 / 100)
    kz66 = money(kz66)
    # 2.545.0 (#4387): section 13b as the recipient (BMF, Vordruckmuster USt 1 A 2026 of 29.12.2025): 46 / 84 = the base
    # (whole euros), 47 / 85 = the tax owed (cents, summed per receipt at its rate), 67 = the same tax as input tax (section 15
    # (1) no. 4 UStG) -- adds up to 0 in 83 for an office with full input tax deduction; the tax advisor checks (#1153)
    kz47, kz85 = money(r13["eu"][1]), money(r13["other"][1])
    kz67 = kz47 + kz85
    kz83 = t19 + t7 + kz36 + kz47 + kz85 - kz66 - kz67
    e = lambda v: str(int(v))  # noqa: E731 -- bases: whole euros
    # 2.355.0 C (#2841, #2844): + 41 goods to EU businesses, 43 exports (tax-free with input tax), 48 other tax-free sales
    # (section 4 no. 8-28 UStG, without input tax), 60 reverse charge at home (section 13b) -- the tax advisor checks (#1153)
    kz = {"81": e(kz81), "86": e(kz86), "35": e(kz35), "36": dstr(kz36), "21": e(_euro_floor(b("reverse"))),
          "41": e(_euro_floor(b("eu_goods"))), "43": e(_euro_floor(b("export"))), "45": e(_euro_floor(b("abroad"))),
          "48": e(_euro_floor(b("exempt"))), "60": e(_euro_floor(b("reverse_dom"))), "66": dstr(kz66), "83": dstr(kz83),
          "46": e(_euro_floor(r13["eu"][0])), "47": dstr(kz47), "84": e(_euro_floor(r13["other"][0])), "85": dstr(kz85), "67": dstr(kz67)}
    return dict(head, small_business=False, kz=kz, tax={"19": dstr(t19), "7": dstr(t7)},
                exempt_other=dstr(money(b("exempt"))), missing_vat=missing, items=items[:BK_LIST_MAX], items_more=len(items) > BK_LIST_MAX)


# ---------------------------------------------------------------- routes
def _rc_public(rc):
    return {"node_id": rc["node_id"], "title": rc["title"], "date": rc["date"], "amount": dstr(rc["amount"]), "vat_pct": rc["vat_pct"],
            "net": dstr(rc["net"]), "vat": dstr(rc["vat"]), "category": rc["category"], "paid_at": rc["paid_at"],
            "rc13b": rc["rc13b"] or None}  # 2.545.0 (#4387)


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
    gaps = {}  # 2.356.0 (#3097): receipts of the year the exports leave out (no date / no amount)
    y_from, y_to = f"{year}-01-01", f"{year}-12-31"
    y_rcs = bk_receipts(c, oid, y_from, y_to, gaps=gaps)
    # 2.546.0 (#4186): the month inside the year = the year's receipts of its days (same order, same rights); was a second run
    m_rcs = [x for x in y_rcs if m_from <= x["date"] <= m_to] if y_from <= m_from and m_to <= y_to else bk_receipts(c, oid, m_from, m_to)
    month = [_rc_public(x) for x in m_rcs][-BK_LIST_MAX:]
    missing = [_rc_public(x) for x in y_rcs if x["vat_pct"] is None][:BK_LIST_MAX]
    from ..docs.dups import dup_seen
    dups = dup_seen(c, {x["node_id"] for x in month + missing}, uid)  # 2.185.0 A (#2583): marked in the list, still counted
    for x in month + missing:
        x["dup"] = x["node_id"] in dups
    from .catacct import ca_accounts
    cats = rc_categories(c, ws)
    einv = bk_einv_offers(c, oid, uid)  # 2.237.0 C (#2865): e-invoices to take over as receipts
    return jsonify(upload_ws="private" if ws[0] == "u" else f"org:{oid}", categories=cats, currency=_home(s),
                   # 2.121.0 (#2093): SKR03 / SKR04 account per category (None: no DATEV input side; 2.147.0 (#2460): or DATEV off)
                   accounts=ca_accounts(c, oid, cats) if office_feature(c, oid, "books.datev", s) else None,
                   small_business=bool(s.get("small_business")), month=mo, receipts=month, year=year, einvoices=einv,
                   missing=[] if s.get("small_business") else missing, note=tr(BK_NOTE),
                   incomplete=len(gaps.get("no_date") or ()) + len(gaps.get("no_amount") or ()),
                   years=bk_years(c, oid),  # 2.593.0 (#4891): the year pickers of the books and the VAT return
                   ledger=(s.get("profit_method") or {}).get("method") or "euer")  # 2.666.0 (#3461): "balance" = the balance sheet page (office/ledger_dbl.py)


def bk_years(c, oid, uid=None):
    """2.593.0 (#4891): {min, max} of the years with data of the books: the receipts the person sees (bk_receipts' trash and
    rights; the paid day and the document date both count, the income statement takes one, the VAT return the other), the
    issued invoices / credit notes (no trial ones) and their payments; None: nothing yet. Only the oldest and the newest
    year's receipts are checked for rights, year by year until one is visible (no full run over every receipt)."""
    uid = _uid_filter(uid)
    by = {}
    for r in c.execute("SELECT r.node_id, r.paid_at, d.doc_date FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id "
                       "JOIN fs_nodes n ON n.id=r.node_id WHERE d.ws=? AND n.kind='file' AND n.deleted_at IS NULL",
                       (bk_ws(c, oid),)).fetchall():
        for v in (r["paid_at"], r["doc_date"]):
            y = ofc_years([v])
            if y:
                by.setdefault(y["min"], set()).add(r["node_id"])

    def seen(y):
        acc = fs_roles_many(c, list(by[y]), uid)
        return any(not a[0] and (not uid or a[1]) for a in acc.values())
    ys = sorted(by)
    lo = next((y for y in ys if seen(y)), None)
    hi = next((y for y in reversed(ys) if seen(y)), None) if lo is not None else None
    rcs = {"min": lo, "max": hi} if lo is not None else None
    docs = ofc_years_sql(c, f"SELECT MIN(date), MAX(date) FROM office_docs WHERE org_id=? AND kind IN ('invoice', 'credit') AND {live_sql()} "
                            "AND locked_at IS NOT NULL AND trial=0 AND number != '' AND date>='1900'", (oid,))
    pays = ofc_years_sql(c, f"SELECT MIN({BK_PAY_DAY}), MAX({BK_PAY_DAY}) FROM office_payments p LEFT JOIN office_payments o "
                            f"ON o.id=p.reverses_id AND o.org_id=p.org_id WHERE p.org_id=? AND {BK_PAY_DAY}>='1900'", (oid,))
    return ofc_years_join(rcs, docs, pays)


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
    return csv_cell(v)


@app.get("/api/office/books/euer.csv")
def bk_euer_csv():
    """?year=YYYY -> the EUeR as CSV (separator and decimal sign of the language, 2.368.2 #2984): group, net, VAT, gross."""
    c, uid, oid = _ctx()
    d = bk_euer(c, oid, _year(request.args.get("year")))
    buf = io.StringIO()
    sep, num = csv_dialect()
    w = csv.writer(buf, delimiter=sep, lineterminator="\r\n")
    w.writerow([tr("Group"), tr("Net"), tr("VAT"), tr("Gross")])
    for title, rows, tot in ((tr("Income"), d["income"], d["income_total"]), (tr("Expenses"), d["expenses"], d["expense_total"])):
        w.writerow([bk_csv_cell(title), "", "", ""])
        for r in rows:
            w.writerow([bk_csv_cell(r["label"]), num(r["net"]), num(r["vat"]), num(r["gross"])])
        w.writerow([bk_csv_cell(tr("Total")), num(tot["net"]), num(tot["vat"]), num(tot["gross"])])
    w.writerow([bk_csv_cell(tr("Profit")), num(d["profit"]), "", ""])
    w.writerow([bk_csv_cell(tr(BK_NOTE)), "", "", ""])
    ofx_log(c, oid, "export", target="books", detail={"what": "euer.csv", "year": d["year"]})
    c.commit()
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{tr("euer|file name")}-{d["year"]}.csv"', "Cache-Control": "no-store"})


def bk_euer_pdf_bytes(c, oid, d, lang):
    """A plain A4 PDF of the EUeR: company and year, the two tables with sums, the profit and the note."""
    from .pdf import A4_H, A4_W, C_INK2, C_RULE, _Page, pdf_money, pdf_write
    s = office_settings(c, oid)
    ppr = pdf_paper_ns(s.get("paper"))  # 2.357.0 A (#3156): the office's paper size
    A4_H, A4_W, _Page = ppr.A4_H, ppr.A4_W, ppr._Page
    company = ofx_name1(ofx_company(c, oid).get("name") or (s.get("company") or {}).get("name"))  # 2.99.0 D (#2188): one line
    cur = d["currency"]
    lg = calc_lang(lang)  # 2.449.0 (#3766): every app language (was de, else en)
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
    c, uid, oid = _ctx()
    d = bk_euer(c, oid, _year(request.args.get("year")))
    data = bk_euer_pdf_bytes(c, oid, d, lang())
    ofx_log(c, oid, "export", target="books", detail={"what": "euer.pdf", "year": d["year"]})
    c.commit()
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{tr("euer|file name")}-{d["year"]}.pdf"', "Cache-Control": "no-store"})
