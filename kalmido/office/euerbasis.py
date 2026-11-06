"""2.603.0 (#4927): the basis of the income / expense statement (EUeR) of an office, chosen per whole year.

"receipts" (the default, the behaviour up to 2.602): the receipts count on their payment day, else their document date,
approved entertainment receipts are an expense of their own, invoice payments count however they were recorded.
"bank" (bank and cash, strict cash principle): only what flowed through the bank account, the cash book or a credit card counts:
 (1) a receipt without a bank, cash or card line is "open" and does not count;
 (2) a bank line (money out) without a receipt counts, with the warning "receipt missing"; marked "needs no receipt" it counts
     without the warning; the gross amount is the amount of the line, the VAT rate the receipt's;
 (3) credit card: the monthly total on the bank account moves money to the card (match kind card, no expense); the positions
     of the statement are the expenses, each with its receipt (open = "receipt missing"), fees and private ones per position;
     a total that differs from the statement is a warning;
 (4) a cash withdrawal (bank match kind "cash") moves money from the bank into the cash box, no expense; the expenses are the
     entries of the cash book (money out, with their receipt, else "receipt missing");
 (5) an entertainment receipt is the proof of its bank / cash / card line (office_meals.pay_kind / pay_id) and gives that
     line its 70 / 30 split -- no second expense; a meal without a line does not count;
 (6) income only through the bank (and the cash book): invoice payments of a bank booking (office_bank_tx.payment_id /
     office_payments.bank_tx_id), of a cash entry or of an online payout matched with a bank booking; money received that no
     invoice matched counts with a warning;
 (7) a bank line marked private (withdrawal / deposit) or ignored does not count.
Depreciation (AfA) and the 10-day rule stay exceptions as in "receipts".
Stored in the office settings as euer_basis {"YYYY": "bank" | "receipts"} (set only by the route here, the general settings
route ignores it); a year without an entry takes the latest earlier year with one, else "receipts". A year with a locked month
(GoBD, office/periodlock.py) keeps its basis: the change is refused (409) -- the months already booked but open follow the new
basis, there is no switch in the middle of a year."""
from flask import jsonify

from ..core.access import Denied
from ..core.config import app
from ..core.db import body, bump, local_now
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_dec_fields
from .calc import dec, money
from .ledger import ofx_log
from .model import office_ctx_admin as _ctx, office_settings, office_settings_lock, office_settings_save
from .periodlock import pl_through

EB_BASES = ("receipts", "bank")
EB_DEFAULT = "receipts"
EB_LOCKED = N_("{0} has a locked month: the basis of the income statement stays as it is for the whole year.")
EB_NORC_LABEL = N_("Receipt missing")


def eb_map(s):
    """{year (int): basis} of the office settings s (only valid entries)."""
    v = s.get("euer_basis") if isinstance(s.get("euer_basis"), dict) else {}
    return {int(k): x for k, x in v.items() if str(k).isdigit() and len(str(k)) == 4 and x in EB_BASES}


def eb_basis_of(s, year):
    """The basis of a year: its own entry, else the latest earlier year with one, else EB_DEFAULT."""
    m = eb_map(s)
    ys = [y for y in m if y <= int(year)]
    return m[max(ys)] if ys else EB_DEFAULT


def eb_basis(c, oid, year):
    return eb_basis_of(office_settings(c, oid), year)


def eb_strict(c, oid, year):
    """True when the year of office area oid counts by bank and cash (strict)."""
    return eb_basis(c, oid, year) == "bank"


def eb_set(c, oid, year, basis):
    """Set the basis of year (and the later years without an own entry). 409 when the year has a locked month and the basis
    would change. The caller commits. -> the settings after the change."""
    if basis not in EB_BASES:
        raise BadInput(tr("Invalid value: {0}", "basis"))
    year = int(year)
    office_settings_lock(c, oid)
    s = office_settings(c, oid)
    if eb_basis_of(s, year) == basis and year in eb_map(s):
        return s
    t = pl_through(c, oid)
    if eb_basis_of(s, year) != basis and t and t >= f"{year}-01":
        raise Denied(409, tr(EB_LOCKED, str(year)))
    s["euer_basis"] = dict({str(k): v for k, v in eb_map(s).items()}, **{str(year): basis})
    office_settings_save(c, oid, s)
    ofx_log(c, oid, "update", target="settings", detail={"euer_basis": year, "basis": basis})
    return s


def eb_public(c, oid, year=None):
    """{year, basis, years: {YYYY: basis} of the stored entries, locked (the year has a locked month)}."""
    s = office_settings(c, oid)
    year = int(year or local_now().year)
    t = pl_through(c, oid)
    return {"year": year, "basis": eb_basis_of(s, year), "years": {str(k): v for k, v in sorted(eb_map(s).items())},
            "locked": bool(t and t >= f"{year}-01"), "bases": list(EB_BASES)}


@app.get("/api/office/books/basis")
def eb_get():
    """Office admin. ?year=YYYY -> eb_public."""
    from flask import request
    from .books import _year
    c, uid, oid = _ctx()
    return jsonify(eb_public(c, oid, _year(request.args.get("year"))))


@app.put("/api/office/books/basis")
def eb_put():
    """Office admin. {year, basis: receipts | bank} -> eb_public (409 for a year with a locked month)."""
    from .books import _year
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    year = _year(b.get("year"))
    eb_set(c, oid, year, b.get("basis"))
    bump(c)
    c.commit()
    return jsonify(eb_public(c, oid, year))


# ---------------------------------------------------------------- the lines of the bank, the cash book and the cards
def _bank_rows(c, oid, frm, to):
    out = []
    for r in c.execute("SELECT * FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND day>=? AND day<=? ORDER BY day, id",
                       (oid, frm, to)).fetchall():
        d = oc_dec_fields(c, oid, "office_bank_tx", r)
        d["amount"] = money(dec(d["amount"], "0"))
        out.append(d)
    return out


def _cash_rows(c, oid, frm, to):
    """The live cash entries of [frm, to]: not cancelled and no cancellation themselves."""
    return c.execute("SELECT e.* FROM office_cash_entries e WHERE e.org_id=? AND e.day>=? AND e.day<=? AND e.storno_of IS NULL "
                     "AND NOT EXISTS (SELECT 1 FROM office_cash_entries x WHERE x.storno_of=e.id) ORDER BY e.day, e.id",
                     (oid, frm, to)).fetchall()


def _card_rows(c, oid, frm, to):
    from .cardnorc import _lines
    return _lines(c, oid, frm, to)


def eb_flows(c, oid, frm, to):
    """The money flows of [frm, to] as the strict basis counts them ->
    {paid: {receipt node id: {day, amount (Decimal, money out, home currency), src: bank|card|cash, ref: line id}},
     norc: [{day, amount, src, ref, text, missing (bool)}] (money out without receipt: missing = the warning; needs-no-receipt not),
     income_open: [{day, amount, ref, text}] (money in on the bank no invoice matched),
     card_diff: [{ref, day, booking, statement}] (the bank total of a card statement differs from the statement)}.
    Private, ignored, card totals, payouts and cash withdrawals are no expense."""
    out = {"paid": {}, "norc": [], "income_open": [], "card_diff": []}
    from .bankvend import bv_key, bv_noreceipt_keys
    nr = bv_noreceipt_keys(c, oid)
    for t in _bank_rows(c, oid, frm, to):
        a, k = t["amount"], t["match_kind"]
        if not a:
            continue
        txt = t.get("counterpart") or t.get("purpose") or ""
        if k == "receipt" and t["match_id"] and a < 0:
            out["paid"].setdefault(t["match_id"], {"day": t["day"], "amount": -a, "src": "bank", "ref": t["id"]})
        elif k is None and a < 0:
            out["norc"].append({"day": t["day"], "amount": -a, "src": "bank", "ref": t["id"], "text": txt,
                                "missing": not (nr and bv_key(t) in nr)})
        elif k == "noreceipt" and a < 0:
            out["norc"].append({"day": t["day"], "amount": -a, "src": "bank", "ref": t["id"], "text": txt, "missing": False})
        elif k is None and a > 0:
            out["income_open"].append({"day": t["day"], "amount": a, "ref": t["id"], "text": txt})
        elif k == "card" and t["match_id"]:
            s = c.execute("SELECT total FROM office_cc_statements WHERE id=? AND org_id=?", (t["match_id"], oid)).fetchone()
            if s is not None:
                tot = money(dec(oc_dec_fields(c, oid, "office_cc_statements", {"total": s["total"]})["total"], "0"))
                if tot != -a:
                    out["card_diff"].append({"ref": t["id"], "day": t["day"], "booking": -a, "statement": tot})
    for x in _card_rows(c, oid, frm, to):
        if not x["amount"] or x["state"] == "private":
            continue
        if x["state"] == "matched" and x["node_id"]:
            if x["amount"] > 0:
                out["paid"].setdefault(x["node_id"], {"day": x["day"], "amount": x["amount"], "src": "card", "ref": x["id"]})
        elif x["state"] == "open" and x["amount"] > 0:
            out["norc"].append({"day": x["day"], "amount": x["amount"], "src": "card", "ref": x["id"], "text": x.get("merchant") or "",
                                "missing": True})
        # noreceipt positions (fees, interest): books.bk_euer counts them as before (cardnorc.cc_norc_lines)
    for e in _cash_rows(c, oid, frm, to):
        a = money(dec(e["amount"], "0"))
        if e["dir"] != "out" or not a:
            continue
        if e["node_id"]:
            out["paid"].setdefault(e["node_id"], {"day": e["day"], "amount": a, "src": "cash", "ref": e["id"]})
        else:
            txt = oc_dec_fields(c, oid, "office_cash_entries", {"text": e["text"]})["text"] or ""
            out["norc"].append({"day": e["day"], "amount": a, "src": "cash", "ref": e["id"], "text": txt, "missing": True,
                                "vat_pct": e["vat_pct"] if e["vat_pct"] in ("19", "7", "0") else None, "category": e["category"] or ""})
    return out


def eb_segments(s, frm, to):
    """[(first day, last day, strict)] of [frm, to] (ISO days, both included) cut at the year ends -- for readers over several
    years (the cash flow)."""
    out, y = [], int(frm[:4])
    while f"{y}-01-01" <= to:
        a, b = max(frm, f"{y}-01-01"), min(to, f"{y}-12-31")
        if a <= b:
            out.append((a, b, eb_basis_of(s, y) == "bank"))
        y += 1
    return out


def eb_income_payment_ids(c, oid):
    """The office_payments ids that came in through the bank or the cash book (point 6): the payment of a bank booking matched
    with an invoice (and the parts of a split), the payment of a cash entry, the payments of the online payment provider; the
    day filter is the caller's (books.bk_payments)."""
    ids = set()
    for r in c.execute("SELECT id, payment_id, match_kind, match_id FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL",
                       (oid,)).fetchall():
        if r["match_kind"] == "invoice" and r["payment_id"]:
            ids.add(r["payment_id"])
    ids |= {r[0] for r in c.execute("SELECT p.id FROM office_payments p JOIN office_bank_tx b ON b.id=p.bank_tx_id AND b.org_id=p.org_id "
                                    "WHERE p.org_id=? AND b.deleted_at IS NULL AND b.match_kind='invoice'", (oid,))}
    ids |= {r[0] for r in c.execute("SELECT payment_id FROM office_cash_entries WHERE org_id=? AND payment_id IS NOT NULL", (oid,))}
    # the payments of the online payment provider (office/payonline.py): the provider's account counts like a bank account
    # (a payout names no payments, its bank booking is match kind payout and no income of its own)
    ids |= {r[0] for r in c.execute("SELECT payment_id FROM office_pay_sessions WHERE org_id=? AND payment_id IS NOT NULL", (oid,))}
    # a reversal line (reverses_id) follows the payment it takes back
    ids |= {r[0] for r in c.execute("SELECT id, reverses_id FROM office_payments WHERE org_id=? AND reverses_id IS NOT NULL", (oid,))
            if r[1] in ids}
    return ids
