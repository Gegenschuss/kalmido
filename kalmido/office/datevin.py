"""2.120.0 C (#2090): the input side of the DATEV booking batch (office/datev.py): receipts and travel expenses.

Same batch as the invoices (one batch may mix revenue and expenses; Belegfeld 1 stays unique: "B<id>" per receipt,
"R<trip>-<item>" per travel receipt, "V<trip>" per per diem). Switch "in_on" in the settings (default on), the download
dialog can leave it out (?in=0).
 - a receipt with an amount (office/books.py bk_receipts, by its document date): one line, expense account from its category
   (own assignment in the settings, else a default per chart found by keywords, else "other expenses") against the collective
   creditor (or the bank account), the input tax key of its rate (19 % -> 9, 7 % -> 8; none for 0 %, an unknown rate or a
   small business). A receipt carries one rate (rc_receipts.vat_pct), so one line per receipt.
 - a travel receipt (office/travel.py): one line on the travel account of its category (fares, hotel, other), no input tax
   key (travel receipts carry no rate); the per diem of a trip (all participants, office/vma.py) one line on the per diem
   account without input tax, dated on the trip's last day. Personal office = the owner's travel accounts
   ("Reisekosten Unternehmer"), an organisation = the employees' ones.
 - hints (dv_hints, shown by the check before the download): receipts without an amount (not exported), without a category
   (booked on the "other expenses" account), without a rate (booked without input tax).
More kinds of receipts later: one more function in DV_SOURCES (c, oid, d_from, d_to, st, s) -> (rows, hints)."""
import re
from decimal import Decimal

from flask import jsonify

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.errors import BadInput
from .calc import dec, money
from ..core.db import db  # 2.149.0 G (#2517): pulled up from functions

# keyword (casefolded, part of the category) -> (SKR03, SKR04); the first match wins
DV_CAT_DEFAULTS = (
    (("software", "lizenz", "licen", "abo", "subscription", "hosting", "cloud", "saas"), ("4964", "6837")),
    (("büro", "buero", "office", "schreibwaren", "stationery"), ("4930", "6815")),
    (("porto", "post", "versand", "shipping"), ("4910", "6800")),
    (("telefon", "internet", "mobil", "handy", "phone"), ("4920", "6805")),
    (("miete", "rent", "raum"), ("4210", "6310")),
    (("werbung", "marketing", "anzeige", "advert"), ("4600", "6600")),
    (("fortbildung", "weiterbildung", "seminar", "training", "kurs", "course"), ("4945", "6821")),
    (("literatur", "buch", "bücher", "zeitschrift", "book", "magazin"), ("4940", "6820")),
    (("versicherung", "insurance"), ("4360", "6400")),
    (("beitrag", "mitglied", "membership", "verband"), ("4380", "6420")),
    (("bewirtung", "restaurant", "hospitality", "entertainment"), ("4650", "6640")),
    (("kfz", "tank", "benzin", "diesel", "fuel", "auto", "car"), ("4530", "6530")),
    (("reise", "travel", "hotel", "bahn", "train", "flug", "flight"), ("4660", "6650")),
    (("werkzeug", "kleingerät", "gerät", "hardware", "equipment", "tool"), ("4985", "6845")),
    (("fremdleistung", "subunternehmer", "freelancer", "subcontract"), ("3100", "5900")),
    (("steuerberat", "buchführung", "rechtsanwalt", "beratung", "legal", "tax advi", "accounting"), ("4950", "6825")),
    (("bank", "gebühr", "fee", "kontoführung"), ("4970", "6855")),
)
DV_OTHER = {"SKR03": "4900", "SKR04": "6300"}  # sonstige betriebliche Aufwendungen
DV_CREDITOR = "70000"  # the collective creditor (both charts; ledger length + 1)
DV_TRAVEL_KEYS = ("fares", "hotel", "vma", "other")
# the travel accounts per chart: an organisation (employees) / a personal office (the owner)
DV_TRAVEL = {
    "SKR03": {"emp": {"fares": "4663", "hotel": "4666", "vma": "4664", "other": "4660"},
              "own": {"fares": "4673", "hotel": "4676", "vma": "4674", "other": "4676"}},
    "SKR04": {"emp": {"fares": "6663", "hotel": "6660", "vma": "6664", "other": "6650"},
              "own": {"fares": "6673", "hotel": "6680", "vma": "6674", "other": "6680"}},
}
DV_RK_KEY = {"car": "fares", "train": "fares", "flight": "fares", "rental_car": "fares", "taxi": "fares", "parking": "fares",
             "hotel": "hotel", "meals": "other", "other": "other"}
DV_BU_IN = {"19": "9", "7": "8"}  # Vorsteuer keys
DV_DEFAULTS = {"in_on": 1, "creditor": "", "in_counter": "creditor", "in_other": "", "cat_accounts": {}, "travel": {}, "bu_in": {}}
DV_CAT_MAX = 200
DV_NO_AMOUNT = N_("{0} receipts without an amount are not exported")
DV_NO_AMOUNT_1 = N_("1 receipt without an amount is not exported")
DV_NO_CAT = N_("{0} receipts without a category booked on the account {1}")
DV_NO_CAT_1 = N_("1 receipt without a category booked on the account {0}")
DV_NO_VAT = N_("{0} receipts without a VAT rate booked without input tax")
DV_NO_VAT_1 = N_("1 receipt without a VAT rate booked without input tax")
# 2.120.0 (#2090): travel receipts marked "in DATEV" (with a DATEV number) are booked there already -- not twice
DV_IN_DATEV = N_("{0} travel receipts already in DATEV are not exported again")
DV_IN_DATEV_1 = N_("1 travel receipt already in DATEV is not exported again")
# 2.146.0 B (#2452): a possible duplicate (docs/dups.py) stays out unless the export asks for it (?dups=1)
DV_DUP = N_("{0} possibly duplicate receipts are not exported")
DV_DUP_1 = N_("1 possibly duplicate receipt is not exported")
DV_DUP_IN = N_("{0} possibly duplicate receipts are exported")
DV_DUP_IN_1 = N_("1 possibly duplicate receipt is exported")


def _len(st, n, plus=0):
    return n.ljust(int(st["acct_len"]) + plus, "0")


def _chart(st):
    return st["chart"] if st["chart"] in DV_TRAVEL else "SKR03"


def dv_cat_default(st, cat):
    """The default expense account of a receipt category (keywords), stretched to the ledger length."""
    k = (cat or "").casefold()
    col = 0 if _chart(st) == "SKR03" else 1
    if k:
        for words, accts in DV_CAT_DEFAULTS:
            if any(w in k for w in words):
                return _len(st, accts[col])
    return dv_other(st)


def dv_other(st):
    return st.get("in_other") or _len(st, DV_OTHER[_chart(st)])


def dv_cat_account(st, cat):
    own = (st.get("cat_accounts") or {}).get((cat or "").strip().casefold()) if cat else ""
    return own or dv_cat_default(st, cat)


def dv_travel_default(st, key, own):
    return _len(st, DV_TRAVEL[_chart(st)]["own" if own else "emp"][key])


def dv_travel_account(st, key, own):
    return (st.get("travel") or {}).get(key) or dv_travel_default(st, key, own)


def dv_counter(st):
    """The counter account of the input side: the collective creditor or the bank account."""
    if st.get("in_counter") == "bank":
        from .datev import _acct
        return st["bank"] or _acct(st, "bank")
    return st.get("creditor") or _len(st, DV_CREDITOR, 1)


# ---------------------------------------------------------------- settings
def dv_settings(v, out):
    """Fills the input side defaults into the DATEV settings dict out (from the stored dict v)."""
    for k, d in DV_DEFAULTS.items():
        val = v.get(k) if isinstance(v, dict) else None
        out[k] = val if val is not None else (dict(d) if isinstance(d, dict) else d)
    return out


def dv_settings_clean(v, out):
    """The input side keys of a partial "datev_extf" body -> into out (validated)."""
    from .datev import _digits
    n = int(out["acct_len"])
    if "in_on" in v:
        out["in_on"] = 1 if v["in_on"] in (1, True, "1") else 0
    if "in_counter" in v:
        if v["in_counter"] not in ("creditor", "bank"):
            raise BadInput(tr("Invalid value: {0}", "in_counter"))
        out["in_counter"] = v["in_counter"]
    if "creditor" in v:
        out["creditor"] = _digits(v["creditor"], "creditor", 1, n + 1)
    if "in_other" in v:
        out["in_other"] = _digits(v["in_other"], "in_other", 1, n)
    if "cat_accounts" in v:
        a = v["cat_accounts"]
        if not isinstance(a, dict) or len(a) > DV_CAT_MAX:
            raise BadInput(tr("Invalid value: {0}", "cat_accounts"))
        clean = {}
        for k, x in a.items():
            name = re.sub(r"[\x00-\x1f\x7f]", "", str(k or "")).strip().casefold()[:60]
            if name and str(x or "").strip():
                clean[name] = _digits(x, name, 1, n)
        out["cat_accounts"] = clean
    if "travel" in v:
        t = v["travel"] if isinstance(v["travel"], dict) else {}
        out["travel"] = {k: _digits(t.get(k), k, 1, n) for k in DV_TRAVEL_KEYS if str(t.get(k) or "").strip()}
    if "bu_in" in v:
        b = v["bu_in"] if isinstance(v["bu_in"], dict) else {}
        out["bu_in"] = {k: _digits(b.get(k), "BU " + k, 1, 4) for k in DV_BU_IN if str(b.get(k) or "").strip()}
    return out


# ---------------------------------------------------------------- the lines
def _eur(amount, s):
    """An amount in the office currency -> EUR (the batch is in EUR; a USD office through its rate fx_usd = USD per EUR)."""
    if (s.get("currency") or "EUR").upper() != "USD":
        return money(amount)
    fx = dec(s.get("fx_usd"), "1.09")
    return money(amount / (fx if fx > 0 else Decimal(1)))


def _line(amount, konto, gegen, bu, day, beleg, text):
    from .datev import BELEG_RE, _amt, _ddmm
    return {"Umsatz (ohne Soll/Haben-Kz)": _amt(amount), "Soll/Haben-Kennzeichen": "S" if amount > 0 else "H", "WKZ Umsatz": "EUR",
            "Konto": konto, "Gegenkonto (ohne BU-Schlüssel)": gegen, "BU-Schlüssel": bu, "Belegdatum": _ddmm(day),
            "Belegfeld 1": BELEG_RE.sub("-", beleg)[:36], "Buchungstext": (text or "").strip()[:60], "Festschreibung": "0",
            "_date": day, "_kind": "in"}


def _no_amount(c, oid, d_from, d_to):
    """The receipts of the period without an amount (by document date, else payment day, else the day they became a
    receipt) that the signed-in person sees -- they cannot be booked."""
    from ..docs.store import doc_open
    from ..files.store import fs_chain, fs_deleted, fs_role
    from .books import _uid_filter, bk_ws
    ws = bk_ws(c, oid)
    uid = _uid_filter(None)
    day = "COALESCE(NULLIF(d.doc_date, ''), NULLIF(r.paid_at, ''), substr(r.set_at, 1, 10))"
    n = 0
    for r in c.execute(f"SELECT r.node_id, d.amount, d.ws FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id "
                       f"JOIN fs_nodes n ON n.id=r.node_id WHERE d.ws=? AND n.kind='file' AND n.deleted_at IS NULL "
                       f"AND {day}>=? AND {day}<=?", (ws, d_from, d_to)).fetchall():
        raw = doc_open(c, r["ws"], "doc_meta.amount", r["amount"]) or ""
        if raw and dec(raw, "0") != 0:
            continue
        if fs_deleted(fs_chain(c, r["node_id"])) or (uid and not fs_role(c, r["node_id"], uid)):
            continue
        n += 1
    return n


def dv_receipt_rows(c, oid, d_from, d_to, st, s):
    from .books import bk_receipts
    small = bool(s.get("small_business"))
    gegen = dv_counter(st)
    bu_in = {**DV_BU_IN, **(st.get("bu_in") or {})}
    rows, no_cat, no_vat = [], 0, 0
    from flask import has_request_context, request
    from ..docs.dups import dup_open
    rcs = bk_receipts(c, oid, d_from, d_to, by="doc")
    dups = dup_open(c, [rc["node_id"] for rc in rcs])
    with_dups = has_request_context() and request.args.get("dups") == "1"
    dup_ids = []
    for rc in rcs:
        amount = _eur(rc["amount"], s)
        if amount == 0:
            continue
        if rc["node_id"] in dups:
            dup_ids.append(rc["node_id"])
            if not with_dups:
                continue
        no_cat += not rc["category"]
        no_vat += rc["vat_pct"] is None and not small
        bu = "" if small else bu_in.get(rc["vat_pct"] or "", "")
        rows.append(_line(amount, dv_cat_account(st, rc["category"]), gegen, bu, rc["date"], f"B{rc['node_id']}",
                          (rc["category"] + " " + rc["title"]) if rc["category"] else rc["title"]))
    hints = []
    na = _no_amount(c, oid, d_from, d_to)
    if na:
        hints.append({"key": "no_amount", "count": na, "text": tr(DV_NO_AMOUNT_1) if na == 1 else tr(DV_NO_AMOUNT, na)})
    if no_cat:
        o = dv_other(st)
        hints.append({"key": "no_category", "count": no_cat, "text": tr(DV_NO_CAT_1, o) if no_cat == 1 else tr(DV_NO_CAT, no_cat, o)})
    if no_vat:
        hints.append({"key": "no_vat", "count": no_vat, "text": tr(DV_NO_VAT_1) if no_vat == 1 else tr(DV_NO_VAT, no_vat)})
    if dup_ids:
        n = len(dup_ids)
        txt = (tr(DV_DUP_IN_1) if n == 1 else tr(DV_DUP_IN, n)) if with_dups else (tr(DV_DUP_1) if n == 1 else tr(DV_DUP, n))
        hints.append({"key": "dups", "count": n, "ids": dup_ids[:50], "text": txt})
    return rows, hints


def dv_travel_rows(c, oid, d_from, d_to, st, s):
    from .model import pb_owner
    from .travel import rk_cat_label, rk_trips
    own = bool(pb_owner(c, oid))
    gegen = dv_counter(st)
    rows, seen, in_datev = [], set(), 0
    for y in sorted({d_from[:4], d_to[:4]}):
        for t in rk_trips(c, oid, year=y):
            if t["id"] in seen:
                continue
            seen.add(t["id"])
            dest = t.get("dest") or ""
            for it in t["items"]:
                day = it["date"] or t["date_from"] or ""
                if not (d_from <= day <= d_to):
                    continue
                amount = _eur(dec(it["amount_home"] or 0), s)
                if amount == 0:
                    continue
                if it.get("datev"):
                    in_datev += 1
                    continue
                k = DV_RK_KEY.get(it["category"] or "other", "other")
                rows.append(_line(amount, dv_travel_account(st, k, own), gegen, "", day, f"R{t['id']}-{it['id']}",
                                  tr("Travel expenses") + ": " + rk_cat_label(it["category"] or "other") + " " + dest))
            vt = (t.get("vma") or {}).get("total")
            day = t["date_to"] or t["date_from"] or ""
            if vt and d_from <= day <= d_to:
                amount = _eur(dec(vt), s)
                if amount != 0:
                    rows.append(_line(amount, dv_travel_account(st, "vma", own), gegen, "", day, f"V{t['id']}",
                                      tr("Per diem") + " " + dest))
    hints = [{"key": "in_datev", "count": in_datev, "text": tr(DV_IN_DATEV_1) if in_datev == 1 else tr(DV_IN_DATEV, in_datev)}] if in_datev else []
    return rows, hints


# the sources of the input side, in this order; 2.119.0 (hospitality receipts) and later kinds add one function here
DV_SOURCES = [dv_receipt_rows, dv_travel_rows]


def dv_rows(c, oid, d_from, d_to, st, s):
    """(booking lines, hints) of the input side of the period (empty when switched off)."""
    rows, hints = [], []
    if not st.get("in_on"):
        return rows, hints
    for f in DV_SOURCES:
        r, h = f(c, oid, d_from, d_to, st, s)
        rows += r
        hints += h
    return rows, hints


def dv_accounts(c, oid, st):
    """For the settings page: the receipt categories of the office with their default and own account, the travel
    accounts, the counter accounts' defaults."""
    from ..receipts.suggest import rc_categories
    from .books import bk_ws
    from .model import pb_owner
    own = bool(pb_owner(c, oid))
    cats = rc_categories(c, bk_ws(c, oid))
    mine = st.get("cat_accounts") or {}
    known = {x.casefold() for x in cats}
    cats += sorted(k for k in mine if k not in known)  # an assignment of a category no receipt uses any more stays editable
    return {"categories": [{"name": x, "default": dv_cat_default(st, x), "account": mine.get(x.casefold(), "")} for x in cats],
            "travel": [{"key": k, "default": dv_travel_default(st, k, own), "account": (st.get("travel") or {}).get(k, "")} for k in DV_TRAVEL_KEYS],
            "other": _len(st, DV_OTHER[_chart(st)]), "creditor": _len(st, DV_CREDITOR, 1), "bu_in": DV_BU_IN}


@app.get("/api/office/datev/accounts")
def dv_accounts_get():
    """Org admin (a personal office: its owner): the accounts of the input side for the DATEV settings (see dv_accounts)."""
    from .datev import dx_settings
    from .model import office_gate, office_need_feature, office_org, office_settings
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=True)
    s = office_settings(c, oid)
    office_need_feature(c, oid, "books.datev", s)  # 2.147.0 (#2459, #2460)
    return jsonify(dv_accounts(c, oid, dx_settings(s)))
