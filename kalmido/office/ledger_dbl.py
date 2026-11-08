"""2.666.0 (#3461): double-entry bookkeeping and the balance sheet for organisations that must draw one up (GmbH, UG).

The choice per office area (a person without an organisation: the personal office): profit determination "euer" (the
income / expense statement, the default -- nothing changes) or "balance" (double entry, balance sheet and profit and loss
account by the German Commercial Code, size "small" or "micro"). A name with GmbH / UG / AG or a register number HRB suggests
the balance sheet (taxcheck.TC_CORP_RE). Stored in the office settings as profit_method {"method", "size"} (set only by the
route here, the general settings route ignores it). The chart of accounts is the one of the DATEV export (SKR03 / SKR04,
office/datev.py), its accounts too: one place for both.

The journal of a year is worked out on every look from what is there -- nothing is entered twice, no copy of the documents:
 - invoices / credit notes (finalised, by their date: accrual): debtor against the revenue account of the tax case and the VAT
   account; a cash discount taken on the day of the payment; payments: bank / cash against the debtor (office/datev.py dx_rows)
 - receipts by their document date: expense account of the category (+ input tax by the rate) against the creditor
   (office/datevin.py; a receipt paid by card against the card account); travel expenses, card fees and private card positions,
   the bank booking of a card total -- the same lines as the DATEV export, split into net and VAT here
 - the payment of a receipt: creditor against the bank (its bank line), the cash box (its cash entry) or, with only a payment
   day, the bank
 - bank lines without a match and ignored ones: the clearing account (to be cleared by an adjusting entry); private ones on the
   private accounts; a cash withdrawal through the money in transit account, as the cash book's money in without an invoice
 - cash entries out without a receipt: the expense account of their category (+ input tax) against the cash box
 - depreciation (office/assets.py ast_afa_year): depreciation against the fixed asset account; the device's receipt is
   capitalised (net on the asset account instead of an expense), a device without a receipt is capitalised against the
   clearing account in the year of its purchase
Stored (office_ledger_entries, migrations.d/3461_a.py) are only the entries made by hand ("manual": accruals, provisions,
corrections) and the opening entries ("open": by hand for the first year, else written by the closing of the year before;
without them the opening balances of the DATEV import, office/datevimp.py). The year-end closing checks that the balance sheet
balances, writes the opening entries of the next year (the balances carried forward, the result onto the profit / loss
carried forward), marks the year closed ("close") and locks every month up to its December (office/periodlock.py pl_lock).
Every booking has debit = credit; the trial balance, the profit and loss account and the balance sheet follow from the
balances of the accounts. Not part of it: filing (E-Bilanz XBRL / ERiC), group accounts, notes and management report.
Rights: those of the income statement (office_ctx_admin: the office's admins, a personal office its owner); agents never
(office_gate) -- the income statement has no agent path either. Home currency EUR only (as the DATEV export)."""
import csv
import io
import re
from datetime import date
from decimal import Decimal

from flask import Response, jsonify, request

from ..core.config import app
from ..core.conflict import ccf_check
from ..core.db import body, bump, iso, local_now, now_utc
from ..core.errors import BadInput, DeniedKey
from ..core.access import Denied
from ..core.i18n import N_, csv_dialect, tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import insert_id, write_lock
from ..core.serializers import csv_cell
from .calc import dec, dstr, money
from .assets import ast_afa_year, ast_values
from .bankacc import bka_datev
from .books import _year, bk_receipts, bk_ws
from .cardnorc import cc_dv_nodes
from .catacct import ca_accounts
from .datev import DX_CASES, _acct, dx_need_eur, dx_rows, dx_settings
from .datevin import DV_BU_IN, dv_card_account, dv_card_private, dv_cat_account, dv_counter, dv_rows, dv_supplier_accounts
from .euerbasis import _bank_rows, _cash_rows
from .ledger import ofx_company, ofx_log
from .model import office_ctx_admin as _ctx, office_rows, office_settings, office_settings_lock, office_settings_save
from .periodlock import period_need_open, pl_lock
from .taxcheck import TC_CORP_RE

LD_METHODS = ("euer", "balance")
LD_SIZES = ("small", "micro")
LD_KINDS = ("manual", "open")
LD_DEFAULT = {"method": "euer", "size": "small"}
LD_TEXT_MAX = 200
LD_NOTE = N_("No tax advice; figures without guarantee. The balance sheet is worked out from the documents of the office; check it with your tax advisor.")
LD_NOT_BALANCE = N_("Switch the profit determination to the balance sheet first.")
LD_CLOSED = N_("The year {0} is closed.")
LD_UNBALANCED = N_("The balance sheet does not balance (difference {0}): the year cannot be closed.")
LD_NOT_OVER = N_("Only a finished year can be closed.")
LD_ALREADY = N_("The year {0} is closed already.")
LD_SAME = N_("Debit and credit account must differ.")
# 2.666.0 (#3461 review): the closing never writes a second set of opening entries, never into a closed year, never on an
# opening that does not balance; after a closing the next year's opening is the closing's (corrections: adjusting entries)
LD_NEXT_OPEN = N_("The year {0} has opening entries already: delete them before closing {1}.")
LD_OPEN_UNBAL = N_("The opening entries do not balance (difference {0}): the year cannot be closed.")
LD_OPEN_WRITTEN = N_("The opening entries of {0} come from the closing of {1}: book a correction as an adjusting entry.")

# the accounts the journal needs beyond those of the DATEV export, per chart (4 digits, stretched to the ledger length)
LD_ACCOUNTS = {
    "SKR03": {"vat19": "1776", "vat7": "1771", "in19": "1576", "in7": "1571", "asset": "0490", "afa": "4830", "clearing": "1590",
              "transit": "1360", "private_in": "1890", "capital": "0800", "carry": "0860", "opening": "9000"},
    "SKR04": {"vat19": "3806", "vat7": "3801", "in19": "1406", "in7": "1401", "asset": "0690", "afa": "6220", "clearing": "1370",
              "transit": "1460", "private_in": "2180", "capital": "2900", "carry": "2970", "opening": "9000"},
}
LD_ACC_LABELS = {
    "vat19": N_("VAT 19 %"), "vat7": N_("VAT 7 %"), "in19": N_("Input tax 19 %"), "in7": N_("Input tax 7 %"),
    "asset": N_("Other operating and office equipment"), "afa": N_("Depreciation of fixed assets"),
    "clearing": N_("Clearing account (items to clear)"), "transit": N_("Money in transit"), "private_in": N_("Private deposits"),
    "capital": N_("Subscribed capital"), "carry": N_("Profit / loss carried forward"), "opening": N_("Opening balance account"),
    "debtor": N_("Trade receivables"), "creditor": N_("Trade payables"), "bank": N_("Bank"), "cash": N_("Cash"),
    "card": N_("Credit card"), "private": N_("Private withdrawals"),
}
LD_CASE_LABELS = {"standard": N_("Revenue 19 % VAT"), "reduced": N_("Revenue 7 % VAT"), "exempt": N_("Tax-free revenue"),
                  "reverse": N_("Revenue reverse charge (EU)"), "abroad": N_("Revenue not taxable in Germany"), "small": N_("Revenue (small business)"),
                  "skonto_standard": N_("Cash discounts granted 19 % VAT"), "skonto_reduced": N_("Cash discounts granted 7 % VAT"),
                  "skonto_other": N_("Cash discounts granted"), "reverse_dom": N_("Revenue reverse charge (section 13b)"),
                  "eu_goods": N_("Tax-free deliveries within the EU"), "export": N_("Tax-free exports")}
# the revenue cases with VAT in the gross amount (DATEV automatic accounts) -> the VAT account
LD_CASE_VAT = {"standard": ("19", "vat19"), "reduced": ("7", "vat7"), "skonto_standard": ("19", "vat19"), "skonto_reduced": ("7", "vat7")}

# ---------------------------------------------------------------- balance sheet and profit and loss lines (HGB)
# (key, label, side, micro key); side a = assets, p = equity and liabilities. micro = the letter the micro size shows
LD_BS = (
    ("A.I", N_("Intangible assets"), "a"), ("A.II", N_("Tangible assets"), "a"), ("A.III", N_("Financial assets"), "a"),
    ("B.I", N_("Inventories"), "a"), ("B.II.1", N_("Trade receivables"), "a"), ("B.II.4", N_("Other assets"), "a"),
    ("B.III", N_("Securities"), "a"), ("B.IV", N_("Cash in hand and bank balances"), "a"), ("C", N_("Prepaid expenses"), "a"),
    ("P.A.I", N_("Subscribed capital"), "p"), ("P.A.II", N_("Capital reserve"), "p"), ("P.A.III", N_("Revenue reserves"), "p"),
    ("P.A.IV", N_("Profit / loss carried forward"), "p"), ("P.A.V", N_("Net income / net loss for the year"), "p"),
    ("P.A.P", N_("Private accounts"), "p"),
    ("P.B", N_("Provisions"), "p"), ("P.C.2", N_("Liabilities to banks"), "p"), ("P.C.4", N_("Trade payables"), "p"),
    ("P.C.8", N_("Other liabilities"), "p"), ("P.D", N_("Deferred income"), "p"),
)
LD_BS_GROUPS = (("A", N_("Fixed assets"), "a"), ("B", N_("Current assets"), "a"), ("C", N_("Prepaid expenses"), "a"),
                ("P.A", N_("Equity"), "p"), ("P.B", N_("Provisions"), "p"), ("P.C", N_("Liabilities"), "p"), ("P.D", N_("Deferred income"), "p"))
# profit and loss account (total cost method, section 275 (2) HGB); kind i = income, e = expense; micro = section 275 (5)
LD_PL = (
    ("1", N_("Revenue"), "i", "m1"), ("4", N_("Other operating income"), "i", "m2"), ("5", N_("Cost of materials"), "e", "m3"),
    ("6", N_("Personnel expenses"), "e", "m4"), ("7", N_("Depreciation"), "e", "m5"), ("8", N_("Other operating expenses"), "e", "m6"),
    ("11", N_("Other interest and similar income"), "i", "m2"), ("13", N_("Interest and similar expenses"), "e", "m6"),
    ("14", N_("Taxes on income"), "e", "m7"), ("16", N_("Other taxes"), "e", "m7"),
)
LD_PL_MICRO = (("m1", N_("Revenue"), "i"), ("m2", N_("Other income"), "i"), ("m3", N_("Cost of materials"), "e"),
               ("m4", N_("Personnel expenses"), "e"), ("m5", N_("Depreciation"), "e"), ("m6", N_("Other expenses"), "e"),
               ("m7", N_("Taxes"), "e"))

# account ranges (first four digits of a general ledger account) -> balance sheet line ("bs:<key>"), profit and loss line
# ("pl:<key>"), "tax" (VAT / input tax, netted), "liquid" (cash / bank, a negative bank balance is a liability), "net" (clearing
# accounts: the sign decides), "open" (the opening balance account); the first range that holds the number wins
LD_RANGES = {
    "SKR03": (
        (0, 99, "bs:A.I"), (100, 499, "bs:A.II"), (500, 599, "bs:A.III"), (600, 699, "bs:P.C.2"), (700, 799, "bs:P.C.8"),
        (800, 839, "bs:P.A.I"), (840, 845, "bs:P.A.II"), (846, 859, "bs:P.A.III"), (860, 869, "bs:P.A.IV"), (870, 929, "bs:P.A.III"),
        (930, 979, "bs:P.B"), (980, 989, "bs:C"), (990, 999, "bs:P.D"),
        (1000, 1299, "liquid"), (1300, 1399, "net"), (1400, 1499, "bs:B.II.1"), (1570, 1589, "tax"), (1590, 1599, "net"),
        (1500, 1599, "bs:B.II.4"), (1600, 1699, "bs:P.C.4"), (1770, 1799, "tax"), (1700, 1769, "bs:P.C.8"), (1800, 1999, "bs:P.A.P"),
        (2100, 2149, "pl:13"), (2200, 2289, "pl:14"), (2290, 2399, "pl:8"), (2600, 2699, "pl:11"), (2000, 2999, "pl:4"),
        (3000, 4099, "pl:5"), (4100, 4199, "pl:6"), (4340, 4349, "pl:16"), (4800, 4899, "pl:7"), (4200, 4999, "pl:8"),
        (7000, 7999, "bs:B.I"), (8000, 8799, "pl:1"), (8800, 8999, "pl:4"), (9000, 9999, "open")),
    "SKR04": (
        (0, 199, "bs:A.I"), (200, 799, "bs:A.II"), (800, 999, "bs:A.III"),
        (1000, 1199, "bs:B.I"), (1200, 1299, "bs:B.II.1"), (1400, 1449, "tax"), (1360, 1379, "net"), (1450, 1499, "net"),
        (1300, 1499, "bs:B.II.4"), (1500, 1599, "bs:B.III"), (1600, 1899, "liquid"), (1900, 1999, "bs:C"),
        (2000, 2899, "bs:P.A.P"), (2900, 2919, "bs:P.A.I"), (2920, 2929, "bs:P.A.II"), (2930, 2969, "bs:P.A.III"), (2970, 2999, "bs:P.A.IV"),
        (3000, 3099, "bs:P.B"), (3100, 3299, "bs:P.C.2"), (3300, 3399, "bs:P.C.4"), (3800, 3899, "tax"), (3400, 3899, "bs:P.C.8"),
        (3900, 3999, "bs:P.D"),
        (4000, 4799, "pl:1"), (4800, 4999, "pl:4"), (5000, 5999, "pl:5"), (6000, 6199, "pl:6"), (6200, 6299, "pl:7"), (6300, 6999, "pl:8"),
        (7100, 7199, "pl:11"), (7300, 7399, "pl:13"), (7600, 7649, "pl:14"), (7650, 7699, "pl:16"), (7000, 7599, "pl:4"), (7700, 7999, "pl:8"),
        (9000, 9999, "open")),
}
ACCT_RE = re.compile(r"^\d{1,9}$")


# ---------------------------------------------------------------- settings
def ld_cfg_of(s):
    """{method, size} of the office settings s."""
    v = s.get("profit_method") if isinstance(s.get("profit_method"), dict) else {}
    return {"method": v.get("method") if v.get("method") in LD_METHODS else LD_DEFAULT["method"],
            "size": v.get("size") if v.get("size") in LD_SIZES else LD_DEFAULT["size"]}


def ld_method(c, oid):
    """"euer" | "balance" of office area oid (the books' page shows the balance sheet only for "balance")."""
    return ld_cfg_of(office_settings(c, oid))["method"]


def ld_suggest(c, oid):
    """"balance" for a corporation (the name says GmbH / UG / AG ... or the register number is an HRB), else "euer" --
    the same test as the tax check (office/taxcheck.py)."""
    co = ofx_company(c, oid)
    name = " ".join((co.get("name") or "", co.get("register_no") or ""))
    return "balance" if TC_CORP_RE.search(name) or (co.get("register_no") or "").strip().upper().startswith("HRB") else "euer"


def ld_public(c, oid):
    s = office_settings(c, oid)
    st = dx_settings(s)
    return {**ld_cfg_of(s), "chart": st["chart"] if st["chart"] in LD_ACCOUNTS else "SKR03", "suggest": ld_suggest(c, oid),
            "methods": list(LD_METHODS), "sizes": list(LD_SIZES), "closed": ld_closed_years(c, oid)}


def ld_set(c, oid, b):
    """Change method / size (partial body); the caller commits. -> the new settings."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    office_settings_lock(c, oid)
    s = office_settings(c, oid)
    cur = ld_cfg_of(s)
    new = dict(cur)
    if "method" in b:
        if b["method"] not in LD_METHODS:
            raise BadInput(tr("Invalid value: {0}", "method"))
        new["method"] = b["method"]
    if "size" in b:
        if b["size"] not in LD_SIZES:
            raise BadInput(tr("Invalid value: {0}", "size"))
        new["size"] = b["size"]
    if new != cur:
        s["profit_method"] = new
        office_settings_save(c, oid, s)
        ofx_log(c, oid, "update", target="settings", detail={"before": {"profit_method": cur}, "after": {"profit_method": new}})
    return new


# ---------------------------------------------------------------- accounts
def _chart(st):
    return st["chart"] if st["chart"] in LD_ACCOUNTS else "SKR03"


def ld_acct(st, key):
    """An account of LD_ACCOUNTS stretched to the ledger length."""
    return LD_ACCOUNTS[_chart(st)][key].ljust(int(st["acct_len"]), "0")


def ld_class(st, acct):
    """The class of account acct (see LD_RANGES): "debtor" / "creditor" for personal accounts (ledger length + 1, first digit
    1-6 / 7-9), else the class of its range ("pl:8" / "net" for numbers outside every range: the sign decides)."""
    n = int(st["acct_len"])
    a = str(acct or "")
    if len(a) == n + 1:
        return "bs:B.II.1" if a[:1] in "123456" else "bs:P.C.4"
    head = int((a + "0000")[:4]) if len(a) >= n else int(a.rjust(4, "0")[:4])
    for lo, hi, k in LD_RANGES[_chart(st)]:
        if lo <= head <= hi:
            return k
    return "net"


def _ld_ctx(c, oid, s=None):
    """The settings of the journal: the DATEV settings with the bank account of the default account (office/bankacc.py), the
    input side on (the balance sheet needs every receipt, whatever the export does)."""
    s = s if s is not None else office_settings(c, oid)
    st = bka_datev(c, oid, dx_settings(s))
    st["in_on"] = 1
    return s, st


# ---------------------------------------------------------------- the journal
def _amt(v):
    """A DATEV line amount ("1234,56") -> Decimal."""
    return dec(str(v or "0").replace(".", "").replace(",", "."))


class _J:
    """The postings of a year: (day, doc, text, debit, credit, amount, src); a negative amount swaps the sides."""

    def __init__(self, st):
        self.st, self.rows, self.labels = st, [], {}

    def add(self, day, doc, text, debit, credit, amount, src, kind="", ref=None):
        a = money(dec(amount))
        if a == 0 or not debit or not credit or debit == credit:
            return
        if a < 0:
            debit, credit, a = credit, debit, -a
        self.rows.append({"day": day or "", "doc": doc or "", "text": (text or "")[:LD_TEXT_MAX], "debit": debit, "credit": credit,
                          "amount": a, "src": src, "kind": kind or src, **({"ref": ref} if ref is not None else {})})

    def label(self, acct, text):
        if acct and text and acct not in self.labels:
            self.labels[acct] = text


def _vat_split(gross, pct):
    """(net, vat) of a gross amount at pct (text "19" / "7"): the VAT as DATEV's automatic accounts work it out."""
    p = dec(pct)
    vat = money(gross * p / (100 + p))
    return gross - vat, vat


def _receipt_side(c, oid, j, st, s, y0, y1):
    """The receipts, travel expenses and card lines of the DATEV input side, split into net and input tax; the receipts of
    depreciated devices onto the fixed asset account. -> (node ids of the receipts paid by card, hints)."""
    small = bool(s.get("small_business"))
    bu_rate = {v: k for k, v in {**DV_BU_IN, **(st.get("bu_in") or {})}.items() if v}  # tax key -> "19" / "7"
    afa_ids = set() if small else ast_afa_year(c, oid, int(y0[:4]))["receipt_ids"]
    asset = ld_acct(st, "asset")
    card_nodes = set(cc_dv_nodes(c, oid))
    names = _cat_names(c, oid)
    rows, hints = dv_rows(c, oid, y0, y1, st, s)
    for r in rows:
        gross = _amt(r["Umsatz (ohne Soll/Haben-Kz)"])
        konto, gegen = r["Konto"], r["Gegenkonto (ohne BU-Schlüssel)"]
        if r.get("Soll/Haben-Kennzeichen") == "H":
            gross = -gross
        node = r.get("_node")
        doc = r.get("Belegfeld 1") or ""
        if node and doc.startswith("B") and node in afa_ids:
            konto = asset  # 2.666.0 (#3461): a depreciated device is capitalised, its depreciation is the expense
            j.label(asset, tr(LD_ACC_LABELS["asset"]))
        else:
            j.label(konto, names.get(konto) or (tr("Travel expenses") if doc[:1] in ("R", "V") else ""))
        pct = "" if small else bu_rate.get(r.get("BU-Schlüssel") or "", "")
        if pct in ("19", "7"):
            net, vat = _vat_split(gross, pct)
            j.add(r["_date"], doc, r.get("Buchungstext"), konto, gegen, net, "receipt" if doc.startswith("B") else "in")
            j.add(r["_date"], doc, r.get("Buchungstext"), ld_acct(st, "in" + pct), gegen, vat, "receipt" if doc.startswith("B") else "in", kind="vat")
        else:
            j.add(r["_date"], doc, r.get("Buchungstext"), konto, gegen, gross, "receipt" if doc.startswith("B") else "in")
    return card_nodes, hints


def _cat_names(c, oid):
    """{expense account: the receipt categories booked on it, joined} (office/catacct.py)."""
    from ..receipts.suggest import rc_categories
    a = ca_accounts(c, oid, rc_categories(c, bk_ws(c, oid))) or {}
    out = {}
    for name, x in (a.get("categories") or {}).items():
        out.setdefault(x["account"], []).append(name)
    return {k: ", ".join(sorted(v, key=str.casefold))[:80] for k, v in out.items()}


def _doc_side(c, oid, j, st, s, y0, y1):
    """Invoices, credit notes, cash discounts and invoice payments of the DATEV export, revenue split into net and VAT."""
    small = bool(s.get("small_business"))
    case_of = {}
    for k in DX_CASES:
        case_of.setdefault(_acct(st, k), k)
    s2 = {**s, "euer_basis": {}}  # every payment counts in the balance sheet, whatever the basis of the income statement
    for r in dx_rows(c, oid, y0, y1, s2, inside=False):
        a = _amt(r["Umsatz (ohne Soll/Haben-Kz)"])
        konto, gegen = r["Konto"], r["Gegenkonto (ohne BU-Schlüssel)"]
        if r.get("Soll/Haben-Kennzeichen") == "H":
            a = -a
        kind = r.get("_kind") or ""
        doc = r.get("Belegfeld 1") or ""
        if kind == "payment":
            j.add(r["_date"], doc, r.get("Buchungstext"), konto, gegen, a, "payment")
            continue
        case = case_of.get(gegen)
        if case:
            j.label(gegen, tr(LD_CASE_LABELS[case]))
        vat = None if small else LD_CASE_VAT.get(case)
        if vat:
            net, tax = _vat_split(a, vat[0])
            j.add(r["_date"], doc, r.get("Buchungstext"), konto, gegen, net, "skonto" if kind == "skonto" else "invoice")
            j.add(r["_date"], doc, r.get("Buchungstext"), konto, ld_acct(st, vat[1]), tax, "skonto" if kind == "skonto" else "invoice", kind="vat")
        else:
            j.add(r["_date"], doc, r.get("Buchungstext"), konto, gegen, a, "skonto" if kind == "skonto" else "invoice")


def _creditors(c, oid, st, nodes, card_nodes):
    """{receipt node id: its creditor account} of the receipts among nodes that the input side books against a creditor (the
    collective one or a supplier of the DATEV import) -- none while the counter account is the bank, none for card receipts."""
    if st.get("in_counter") == "bank":
        return {}
    nodes = [n for n in nodes if n and n not in card_nodes]
    own = dv_supplier_accounts(c, oid, st, nodes)
    return {n: own.get(n) or dv_counter(st) for n in nodes}


def _money_side(c, oid, j, st, s, y0, y1, card_nodes):
    """The bank lines and cash entries that the DATEV export leaves to the tax advisor, and the payments of the receipts
    (whatever year their receipt was booked in)."""
    bank = st["bank"] or _acct(st, "bank")
    cash = st["cash"] or _acct(st, "cash")
    clearing, transit = ld_acct(st, "clearing"), ld_acct(st, "transit")
    banks, cashes = _bank_rows(c, oid, y0, y1), _cash_rows(c, oid, y0, y1)
    cred = _creditors(c, oid, st, {t["match_id"] for t in banks if t["match_kind"] == "receipt"} | {e["node_id"] for e in cashes if e["node_id"]},
                      card_nodes)
    paid = set()
    for t in banks:
        a, k = t["amount"], t["match_kind"]
        txt = t.get("counterpart") or t.get("purpose") or ""
        doc = f"BK{t['id']}"
        if not a or k in ("invoice", "card", "payout"):
            continue  # the payment of the invoice / the card total / the payout of the online payments: the DATEV lines book them
        if k == "receipt":
            if t["match_id"] in cred:
                j.add(t["day"], doc, txt, cred[t["match_id"]], bank, -a, "bank")
                paid.add(t["match_id"])
            continue
        if k == "private":
            j.add(t["day"], doc, txt, bank, ld_acct(st, "private_in") if a > 0 else dv_card_private(st), a, "bank")
        elif k == "cash":
            j.add(t["day"], doc, txt, bank, transit, a, "bank")  # money out of the bank into the cash box (or back)
        elif k == "noreceipt" and a < 0:
            j.add(t["day"], doc, txt, dv_cat_account(st, "bank"), bank, -a, "bank")
        else:
            j.add(t["day"], doc, txt, bank, clearing, a, "bank")  # not matched / ignored: to clear by an adjusting entry
    for e in cashes:
        a = money(dec(e["amount"], "0"))
        if not a or e["invoice_id"]:
            continue  # a cash payment of an invoice: its payment is booked (cash against the debtor)
        doc = f"KA{e['id']}"
        txt = oc_dec_fields(c, oid, "office_cash_entries", {"text": e["text"]})["text"] or ""
        if e["dir"] == "in":
            j.add(e["day"], doc, txt, cash, transit, a, "cash")
        elif e["node_id"]:
            if e["node_id"] in cred and e["node_id"] not in paid:
                j.add(e["day"], doc, txt, cred[e["node_id"]], cash, a, "cash")
                paid.add(e["node_id"])
        else:
            konto = dv_cat_account(st, e["category"] or "")
            j.label(konto, e["category"] or "")
            pct = "" if s.get("small_business") else (e["vat_pct"] if e["vat_pct"] in ("19", "7") else "")
            if pct:
                net, vat = _vat_split(a, pct)
                j.add(e["day"], doc, txt, konto, cash, net, "cash")
                j.add(e["day"], doc, txt, ld_acct(st, "in" + pct), cash, vat, "cash", kind="vat")
            else:
                j.add(e["day"], doc, txt, konto, cash, a, "cash")
    # a receipt with only a payment day (set by hand, no bank / cash line): paid from the bank on that day
    if st.get("in_counter") != "bank":
        rcs = [rc for rc in bk_receipts(c, oid, y0, y1, by="paid") if rc["paid_at"] and y0 <= rc["paid_at"] <= y1
               and rc["node_id"] not in paid and rc["node_id"] not in card_nodes and not _flowed(c, oid, rc["node_id"])]
        cr = _creditors(c, oid, st, [rc["node_id"] for rc in rcs], card_nodes)
        for rc in rcs:
            j.add(rc["paid_at"], f"B{rc['node_id']}", rc["title"], cr[rc["node_id"]], bank, rc["amount"], "receipt_paid")
    return paid


def _flowed(c, oid, nid):
    """A receipt paid through a bank line or a cash entry (of any year): its payment is that line's."""
    return c.execute("SELECT 1 FROM office_bank_tx WHERE org_id=? AND match_kind='receipt' AND match_id=? AND deleted_at IS NULL "
                     "UNION ALL SELECT 1 FROM office_cash_entries WHERE org_id=? AND node_id=? LIMIT 1", (oid, nid, oid, nid)).fetchone() is not None


def _afa_side(c, oid, j, st, s, year):
    """The depreciation of the year; a device without a receipt is capitalised against the clearing account in its year."""
    if s.get("small_business"):
        return
    asset, afa = ld_acct(st, "asset"), ld_acct(st, "afa")
    j.label(afa, tr(LD_ACC_LABELS["afa"]))
    for a in ast_afa_year(c, oid, year)["rows"]:
        j.add(f"{year}-12-31", f"AfA{a['equipment_id']}", a["name"], afa, asset, a["amount"], "afa")
    for r in office_rows(c, oid, "equipment"):
        pd = str(r.get("purchase_date") or "")
        if r.get("receipt_node_id") or not pd.startswith(str(year)):
            continue
        v = ast_values(r, date(year, 12, 31))
        if v["method"] and r.get("purchase_net"):
            j.add(pd, f"AN{r['id']}", r.get("name"), asset, ld_acct(st, "clearing"), dec(r["purchase_net"]), "asset")


def ld_entries(c, oid, year, kinds=("manual", "open")):
    """The stored entries of year (decrypted dicts), oldest first."""
    q = ",".join("?" * len(kinds))
    return [oc_dec_fields(c, oid, "office_ledger_entries", r) for r in
            c.execute(f"SELECT * FROM office_ledger_entries WHERE org_id=? AND year=? AND kind IN ({q}) ORDER BY day, id",
                      (oid, year, *kinds)).fetchall()]


def ld_closed_years(c, oid):
    return sorted(int(r[0]) for r in c.execute("SELECT year FROM office_ledger_entries WHERE org_id=? AND kind='close'", (oid,)))


def _opening(c, oid, j, st, year):
    """The opening entries of year: the stored ones, else the opening balances of the DATEV import of that year."""
    rows = ld_entries(c, oid, year, ("open",))
    if rows:
        for e in rows:
            j.add(e["day"], f"EB{e['id']}", e["text"], e["debit"], e["credit"], dec(e["amount"]), "open", ref=e["id"])
        return "entries"
    ob = c.execute("SELECT account, label, amount, side FROM office_opening_balances WHERE org_id=? AND year=? ORDER BY account",
                   (oid, year)).fetchall()
    op = ld_acct(st, "opening")
    for r in ob:
        a = money(dec(r["amount"]))
        j.label(r["account"], r["label"])
        if r["side"] == "H":
            j.add(f"{year}-01-01", "EB", r["label"], op, r["account"], a, "open")
        else:
            j.add(f"{year}-01-01", "EB", r["label"], r["account"], op, a, "open")
    return "datev" if ob else None


def ld_journal(c, oid, year):
    """{rows: the postings of year (oldest first), labels: {account: name}, hints: [...], opening: "entries" | "datev" | None}."""
    s, st = _ld_ctx(c, oid)
    dx_need_eur(s)
    y0, y1 = f"{year}-01-01", f"{year}-12-31"
    j = _J(st)
    opening = _opening(c, oid, j, st, year)
    _doc_side(c, oid, j, st, s, y0, y1)
    card_nodes, hints = _receipt_side(c, oid, j, st, s, y0, y1)
    _money_side(c, oid, j, st, s, y0, y1, card_nodes)
    _afa_side(c, oid, j, st, s, year)
    for e in ld_entries(c, oid, year, ("manual",)):
        j.add(e["day"], f"UB{e['id']}", e["text"], e["debit"], e["credit"], dec(e["amount"]), "manual", ref=e["id"])
    j.rows.sort(key=lambda r: (r["src"] != "open", r["day"], r["doc"]))
    if opening is None and year - 1 not in ld_closed_years(c, oid) and _had_data(c, oid, year - 1):
        hints = [{"key": "no_opening", "text": tr("The year {0} is not closed: enter the opening balances of {1} as opening entries.", year - 1, year)}] + hints
    if int(st.get("fy_start") or 1) != 1:
        hints.append({"key": "fiscal_year", "text": tr("The balance sheet runs by calendar year; the fiscal year of the DATEV settings starts in another month.")})
    return {"rows": j.rows, "labels": j.labels, "hints": hints, "opening": opening, "st": st}


def _had_data(c, oid, year):
    r = c.execute("SELECT 1 FROM office_docs WHERE org_id=? AND date>=? AND date<=? AND trial=0 LIMIT 1",
                  (oid, f"{year}-01-01", f"{year}-12-31")).fetchone()
    return r is not None


# ---------------------------------------------------------------- the reports
def ld_label(st, labels, acct):
    """The name of an account: the journal's (category, case, import), else the one of the accounts the ledger knows."""
    if labels.get(acct):
        return labels[acct]
    for k in LD_ACCOUNTS[_chart(st)]:
        if ld_acct(st, k) == acct:
            return tr(LD_ACC_LABELS[k])
    named = {"bank": st["bank"] or _acct(st, "bank"), "cash": st["cash"] or _acct(st, "cash"), "card": dv_card_account(st),
             "private": dv_card_private(st), "creditor": dv_counter(st)}
    for k, a in named.items():
        if a == acct:
            return tr(LD_ACC_LABELS[k])
    cls = ld_class(st, acct)
    if cls == "bs:B.II.1":
        return tr(LD_ACC_LABELS["debtor"])
    if cls == "bs:P.C.4":
        return tr(LD_ACC_LABELS["creditor"])
    return ""


def ld_reports(c, oid, year, jr=None):
    """{susa, pl, bs, checks} of year from the journal (ld_journal)."""
    jr = jr or ld_journal(c, oid, year)
    st, labels = jr["st"], jr["labels"]
    size = ld_cfg_of(office_settings(c, oid))["size"]
    acc = {}
    for r in jr["rows"]:
        for a, side in ((r["debit"], 0), (r["credit"], 1)):
            x = acc.setdefault(a, [Decimal(0)] * 4)  # opening debit, opening credit, debit, credit
            x[(0 if r["src"] == "open" else 2) + side] += r["amount"]
    susa, tot = [], [Decimal(0)] * 4
    for a in sorted(acc, key=lambda x: (len(x), x)):
        v = acc[a]
        tot = [t + x for t, x in zip(tot, v)]
        susa.append({"account": a, "label": ld_label(st, labels, a), "class": ld_class(st, a), "open": dstr(v[0] - v[1]),
                     "debit": dstr(v[0] + v[2]), "credit": dstr(v[1] + v[3]), "balance": dstr(v[0] + v[2] - v[1] - v[3])})
    # the profit and loss account
    pl = {k: Decimal(0) for k, *_ in LD_PL}
    pl_accts = {k: [] for k, *_ in LD_PL}
    bs = {k: Decimal(0) for k, *_ in LD_BS}
    bs_accts = {k: [] for k, *_ in LD_BS}
    for row in susa:
        a, cls, bal = row["account"], row["class"], dec(row["balance"])  # bal = debit - credit
        if bal == 0:
            continue
        if cls.startswith("pl:"):
            k = cls[3:]
            kind = next(x[2] for x in LD_PL if x[0] == k)
            pl[k] += -bal if kind == "i" else bal
            pl_accts[k].append(a)
            continue
        if cls.startswith("bs:"):
            k = cls[3:]
        elif cls == "liquid":
            k = "B.IV" if bal > 0 else "P.C.2"
        elif cls in ("tax", "net", "open"):
            k = "B.II.4" if bal > 0 else "P.C.8"
        else:
            k = "B.II.4" if bal > 0 else "P.C.8"
        side = next(x[2] for x in LD_BS if x[0] == k)
        bs[k] += bal if side == "a" else -bal
        bs_accts[k].append(a)
    # the tax accounts are netted (VAT payable against input tax): one line, on the side its sum says
    tax = sum((dec(r["balance"]) for r in susa if r["class"] == "tax"), Decimal(0))
    for k in ("B.II.4", "P.C.8"):
        for a in [x for x in bs_accts[k] if ld_class(st, x) == "tax"]:
            bal = dec(next(r["balance"] for r in susa if r["account"] == a))
            bs[k] -= bal if k == "B.II.4" else -bal
            bs_accts[k].remove(a)
    if tax:
        k = "B.II.4" if tax > 0 else "P.C.8"
        bs[k] += abs(tax)
        bs_accts[k] += [r["account"] for r in susa if r["class"] == "tax" and dec(r["balance"])]
    result = sum((v if next(x[2] for x in LD_PL if x[0] == k) == "i" else -v for k, v in pl.items()), Decimal(0))
    bs["P.A.V"] = result
    pl_lines = [{"key": k, "label": tr(lb), "kind": kind, "amount": dstr(pl[k]), "accounts": pl_accts[k]} for k, lb, kind, _m in LD_PL]
    if size == "micro":
        m = {k: Decimal(0) for k, *_ in LD_PL_MICRO}
        ma = {k: [] for k, *_ in LD_PL_MICRO}
        for k, _lb, kind, mk in LD_PL:
            m[mk] += pl[k] if kind == next(x[2] for x in LD_PL_MICRO if x[0] == mk) else -pl[k]
            ma[mk] += pl_accts[k]
        pl_lines = [{"key": k, "label": tr(lb), "kind": kind, "amount": dstr(m[k]), "accounts": ma[k]} for k, lb, kind in LD_PL_MICRO]
    bs_lines = []
    for g, glb, side in LD_BS_GROUPS:
        items = [(k, lb) for k, lb, sd in LD_BS if (k == g or k.startswith(g + ".")) and sd == side]
        gsum = sum((bs[k] for k, _ in items), Decimal(0))
        bs_lines.append({"key": g, "label": tr(glb), "side": side, "level": 0, "amount": dstr(gsum)})
        if size == "small":
            for k, lb in items:
                if bs[k] or k == "P.A.V":
                    bs_lines.append({"key": k, "label": tr(lb), "side": side, "level": 1, "amount": dstr(bs[k]), "accounts": bs_accts[k]})
    assets = sum((bs[k] for k, _l, sd in LD_BS if sd == "a"), Decimal(0))
    liab = sum((bs[k] for k, _l, sd in LD_BS if sd == "p"), Decimal(0))
    op = acc.get(ld_acct(st, "opening"), [Decimal(0)] * 4)  # 2.666.0 (#3461 review): the opening balance account: 0 when the opening entries balance
    checks = {"debit": dstr(tot[0] + tot[2]), "credit": dstr(tot[1] + tot[3]), "balanced": tot[0] + tot[2] == tot[1] + tot[3],
              "assets": dstr(assets), "liabilities": dstr(liab), "difference": dstr(assets - liab), "result": dstr(result),
              "opening": dstr(op[0] + op[2] - op[1] - op[3])}
    return {"year": year, "size": size, "susa": susa, "pl": pl_lines, "result": dstr(result), "bs": bs_lines, "checks": checks,
            "hints": jr["hints"], "opening": jr["opening"]}


# ---------------------------------------------------------------- entries by hand
def _acct_clean(st, v, name):
    a = str(v or "").strip()
    n = int(st["acct_len"])
    if not ACCT_RE.match(a) or not (n <= len(a) <= n + 1):
        raise BadInput(tr("Invalid value: {0}", name))
    return a


def ld_entry_clean(c, oid, b, cur=None):
    """A body {day, debit, credit, amount, text, kind: manual | open} -> the clean values (BadInput on a wrong one)."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    _s, st = _ld_ctx(c, oid)
    cur = cur or {}
    day = str(b.get("day", cur.get("day")) or "").strip()
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "day"))
    kind = b.get("kind", cur.get("kind") or "manual")
    if kind not in LD_KINDS:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    debit = _acct_clean(st, b.get("debit", cur.get("debit")), "debit")
    credit = _acct_clean(st, b.get("credit", cur.get("credit")), "credit")
    if debit == credit:
        raise BadInput(tr(LD_SAME))
    a = dec(b.get("amount", cur.get("amount")), "0")
    if a <= 0 or a >= Decimal("1e11"):
        raise BadInput(tr("Invalid value: {0}", "amount"))
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(b.get("text", cur.get("text")) or "")).strip()[:LD_TEXT_MAX]
    return {"year": d.year, "day": d.isoformat(), "kind": kind, "debit": debit, "credit": credit, "amount": dstr(a), "text": text}


def _need_balance(c, oid):
    if ld_method(c, oid) != "balance":
        raise DeniedKey(409, LD_NOT_BALANCE)


def _need_open_year(c, oid, *years):
    closed = set(ld_closed_years(c, oid))
    for y in years:
        if y in closed:
            raise DeniedKey(409, LD_CLOSED, str(y))


def _need_open_free(c, oid, kind, year):
    """2.666.0 (#3461 review): no opening entry by hand for a year whose year before is closed: that closing wrote them."""
    if kind == "open" and year - 1 in ld_closed_years(c, oid):
        raise DeniedKey(409, LD_OPEN_WRITTEN, str(year), str(year - 1))


def _entry_row(c, oid, eid):
    r = c.execute("SELECT * FROM office_ledger_entries WHERE id=? AND org_id=? AND kind IN ('manual', 'open')", (eid, oid)).fetchone()
    if r is None:
        raise Denied(404)
    return oc_dec_fields(c, oid, "office_ledger_entries", r)


def ld_public_entry(e):
    return {k: e[k] for k in ("id", "year", "kind", "day", "debit", "credit", "amount", "text", "ref", "created_at", "updated_at")}


def ld_entry_add(c, oid, uid, b):
    _need_balance(c, oid)
    write_lock(c, f"office_ledger_{int(oid)}")
    v = ld_entry_clean(c, oid, b)
    _need_open_year(c, oid, v["year"])
    _need_open_free(c, oid, v["kind"], v["year"])
    period_need_open(c, oid, v["day"])
    at = iso(now_utc())
    enc = oc_enc_fields(c, oid, "office_ledger_entries", {"text": v["text"]})
    eid = insert_id(c, "INSERT INTO office_ledger_entries(org_id, year, kind, day, debit, credit, amount, text, ref, created_at, created_by, "
                       "updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (oid, v["year"], v["kind"], v["day"], v["debit"], v["credit"], v["amount"], enc["text"], "", at, uid, at, uid))
    ofx_log(c, oid, "create", target="ledger", detail={"id": eid, **{k: v[k] for k in ("day", "kind", "debit", "credit", "amount")}})
    return _entry_row(c, oid, eid)


def ld_entry_put(c, oid, uid, eid, b):
    _need_balance(c, oid)
    write_lock(c, f"office_ledger_{int(oid)}")
    cur = _entry_row(c, oid, eid)
    ccf_check(b, cur["updated_at"], "entry", lambda: ld_public_entry(cur))
    if cur["ref"]:
        raise DeniedKey(409, LD_CLOSED, str(cur["year"]))  # written by a closing: stays as it is
    v = ld_entry_clean(c, oid, b, cur)
    _need_open_year(c, oid, cur["year"], v["year"])
    _need_open_free(c, oid, v["kind"], v["year"])
    period_need_open(c, oid, cur["day"], v["day"])
    enc = oc_enc_fields(c, oid, "office_ledger_entries", {"text": v["text"]})
    c.execute("UPDATE office_ledger_entries SET year=?, kind=?, day=?, debit=?, credit=?, amount=?, text=?, updated_at=?, updated_by=? "
              "WHERE id=? AND org_id=?", (v["year"], v["kind"], v["day"], v["debit"], v["credit"], v["amount"], enc["text"], iso(now_utc()), uid, eid, oid))
    ofx_log(c, oid, "update", target="ledger", detail={"id": eid, "before": {k: cur[k] for k in ("day", "kind", "debit", "credit", "amount")},
                                                       "after": {k: v[k] for k in ("day", "kind", "debit", "credit", "amount")}})
    return _entry_row(c, oid, eid)


def ld_entry_delete(c, oid, eid, b=None):
    _need_balance(c, oid)
    write_lock(c, f"office_ledger_{int(oid)}")
    cur = _entry_row(c, oid, eid)
    ccf_check(b or {}, cur["updated_at"], "entry", lambda: ld_public_entry(cur))
    if cur["ref"]:
        raise DeniedKey(409, LD_CLOSED, str(cur["year"]))
    _need_open_year(c, oid, cur["year"])
    period_need_open(c, oid, cur["day"])
    c.execute("DELETE FROM office_ledger_entries WHERE id=? AND org_id=?", (eid, oid))
    ofx_log(c, oid, "delete", target="ledger", detail={"id": eid, **{k: cur[k] for k in ("day", "kind", "debit", "credit", "amount")}})


# ---------------------------------------------------------------- the year-end closing
def ld_close(c, oid, uid, year):
    """Close year: the balance sheet must balance; writes the opening entries of year + 1 (every balance sheet account with
    its balance against the opening balance account, the result onto the profit / loss carried forward), the mark "close"
    and locks every month up to December of year (GoBD). -> {year, result, opening: count, locked: months}."""
    _need_balance(c, oid)
    if year >= local_now().year:
        raise DeniedKey(409, LD_NOT_OVER)
    write_lock(c, f"office_ledger_{int(oid)}")
    closed = ld_closed_years(c, oid)
    if year in closed:
        raise DeniedKey(409, LD_ALREADY, str(year))
    if year + 1 in closed:  # 2.666.0 (#3461 review): never into a closed year
        raise DeniedKey(409, LD_CLOSED, str(year + 1))
    if ld_entries(c, oid, year + 1, ("open",)):  # 2.666.0 (#3461 review): never a second set of opening entries
        raise DeniedKey(409, LD_NEXT_OPEN, str(year + 1), str(year))
    rep = ld_reports(c, oid, year)
    ch = rep["checks"]
    if not ch["balanced"] or dec(ch["difference"]) != 0:
        raise DeniedKey(409, LD_UNBALANCED, ch["difference"])
    if dec(ch["opening"]) != 0:  # 2.666.0 (#3461 review): an opening that does not balance would ride along as a balance of 9000
        raise DeniedKey(409, LD_OPEN_UNBAL, ch["opening"])
    _s, st = _ld_ctx(c, oid)
    op, carry = ld_acct(st, "opening"), ld_acct(st, "carry")
    at, day, n = iso(now_utc()), f"{year + 1}-01-01", 0
    text = tr("Opening balance {0}", year + 1)

    def put(debit, credit, amount, txt):
        enc = oc_enc_fields(c, oid, "office_ledger_entries", {"text": txt})
        c.execute("INSERT INTO office_ledger_entries(org_id, year, kind, day, debit, credit, amount, text, ref, created_at, created_by, "
                  "updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (oid, year + 1, "open", day, debit, credit, dstr(amount), enc["text"], f"close:{year}", at, uid, at, uid))
    for r in rep["susa"]:
        bal = dec(r["balance"])
        if bal == 0 or r["class"].startswith("pl:") or r["account"] == op:
            continue
        if bal > 0:
            put(r["account"], op, bal, text)
        else:
            put(op, r["account"], -bal, text)
        n += 1
    res = dec(rep["result"])
    if res > 0:
        put(op, carry, res, tr("Result {0} carried forward", year))
    elif res < 0:
        put(carry, op, -res, tr("Result {0} carried forward", year))
    n += bool(res)
    c.execute("INSERT INTO office_ledger_entries(org_id, year, kind, day, debit, credit, amount, text, ref, created_at, created_by, updated_at, "
              "updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (oid, year, "close", f"{year}-12-31", "", "", rep["result"], "", "", at, uid, at, uid))
    months = pl_lock(c, oid, uid, f"{year}-12")
    ofx_log(c, oid, "close", target="ledger", detail={"year": year, "result": rep["result"], "opening": n, "assets": ch["assets"]})
    return {"year": year, "result": rep["result"], "opening": n, "locked": len(months)}


# ---------------------------------------------------------------- routes
def _year_arg(v=None):
    return _year(v if v is not None else request.args.get("year"))


@app.get("/api/office/books/ledger/settings")
def ld_settings_get():
    """Office admin -> {method, size, chart, suggest, methods, sizes, closed}."""
    c, uid, oid = _ctx()
    return jsonify(ld_public(c, oid))


@app.put("/api/office/books/ledger/settings")
def ld_settings_put():
    """Office admin. {method: euer | balance, size: small | micro} (partial) -> ld_public."""
    c, uid, oid = _ctx()
    ld_set(c, oid, body())
    bump(c)
    c.commit()
    return jsonify(ld_public(c, oid))


@app.get("/api/office/books/ledger")
def ld_get():
    """Office admin. ?year=YYYY -> {settings, closed (the year), susa, pl, result, bs, checks, hints, opening, entries (stored
    entries of the year), note}; ?journal=1 adds the postings."""
    c, uid, oid = _ctx()
    year = _year_arg()
    jr = ld_journal(c, oid, year)
    rep = ld_reports(c, oid, year, jr)
    out = {**rep, "settings": ld_public(c, oid), "closed": year in ld_closed_years(c, oid), "note": tr(LD_NOTE),
           "entries": [ld_public_entry(e) for e in ld_entries(c, oid, year)]}
    if request.args.get("journal"):
        out["journal"] = [{**r, "amount": dstr(r["amount"])} for r in jr["rows"]]
    return jsonify(out)


LD_CSV = {"susa": N_("trial-balance|file name"), "pl": N_("profit-and-loss|file name"), "bs": N_("balance-sheet|file name"),
          "journal": N_("journal|file name")}


@app.get("/api/office/books/ledger/<what>.csv")
def ld_csv(what):
    """Office admin. ?year=YYYY -> the trial balance (susa), the profit and loss account (pl), the balance sheet (bs) or the
    journal as CSV (separator and decimal sign of the language)."""
    if what not in LD_CSV:
        raise Denied(404)
    c, uid, oid = _ctx()
    year = _year_arg()
    jr = ld_journal(c, oid, year)
    rep = ld_reports(c, oid, year, jr)
    buf = io.StringIO()
    sep, num = csv_dialect()
    w = csv.writer(buf, delimiter=sep, lineterminator="\r\n")
    if what == "susa":
        w.writerow([tr("Account"), tr("Name"), tr("Opening balance"), tr("Debit"), tr("Credit"), tr("Balance")])
        for r in rep["susa"]:
            w.writerow([r["account"], csv_cell(r["label"]), num(r["open"]), num(r["debit"]), num(r["credit"]), num(r["balance"])])
        w.writerow(["", csv_cell(tr("Total")), "", num(rep["checks"]["debit"]), num(rep["checks"]["credit"]), ""])
    elif what == "pl":
        w.writerow([tr("Line"), tr("Amount")])
        for r in rep["pl"]:
            w.writerow([csv_cell(r["label"]), num(r["amount"] if r["kind"] == "i" else dstr(-dec(r["amount"])))])
        w.writerow([csv_cell(tr("Net income / net loss for the year")), num(rep["result"])])
    elif what == "bs":
        w.writerow([tr("Side"), tr("Line"), tr("Amount")])
        for r in rep["bs"]:
            w.writerow([tr("Assets") if r["side"] == "a" else tr("Equity and liabilities"), csv_cell(("  " if r["level"] else "") + r["label"]), num(r["amount"])])
        w.writerow([tr("Assets"), csv_cell(tr("Total")), num(rep["checks"]["assets"])])
        w.writerow([tr("Equity and liabilities"), csv_cell(tr("Total")), num(rep["checks"]["liabilities"])])
    else:
        w.writerow([tr("Date"), tr("Document"), tr("Text"), tr("Debit"), tr("Credit"), tr("Amount")])
        for r in jr["rows"]:
            w.writerow([r["day"], csv_cell(r["doc"]), csv_cell(r["text"]), r["debit"], r["credit"], num(dstr(r["amount"]))])
    w.writerow([csv_cell(tr(LD_NOTE))])
    ofx_log(c, oid, "export", target="books", detail={"what": f"ledger-{what}.csv", "year": year})
    c.commit()
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{tr(LD_CSV[what])}-{year}.csv"', "Cache-Control": "no-store"})


@app.post("/api/office/books/ledger/entries")
def ld_entries_post():
    """Office admin. {day, debit, credit, amount, text, kind: manual | open} -> 201 the entry (409 while the profit determination
    is the income statement, the year is closed or the month locked)."""
    c, uid, oid = _ctx()
    e = ld_entry_add(c, oid, uid, body())
    bump(c)
    c.commit()
    return jsonify(ld_public_entry(e)), 201


@app.put("/api/office/books/ledger/entries/<int:eid>")
def ld_entry_put_route(eid):
    """Office admin. A partial body + expect_updated_at (409 with the current entry when it moved on)."""
    c, uid, oid = _ctx()
    e = ld_entry_put(c, oid, uid, eid, body() or {})
    bump(c)
    c.commit()
    return jsonify(ld_public_entry(e))


@app.delete("/api/office/books/ledger/entries/<int:eid>")
def ld_entry_delete_route(eid):
    c, uid, oid = _ctx()
    ld_entry_delete(c, oid, eid, {"expect_updated_at": request.args.get("expect_updated_at")} if request.args.get("expect_updated_at") else None)
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/office/books/ledger/close")
def ld_close_post():
    """Office admin. {year} -> ld_close (409: not over, closed already, not balanced, the opening entries do not balance, the next
    year closed or with opening entries already, the income statement chosen)."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    out = ld_close(c, oid, uid, _year_arg(str(b.get("year") or "")))
    bump(c)
    c.commit()
    return jsonify(out)
