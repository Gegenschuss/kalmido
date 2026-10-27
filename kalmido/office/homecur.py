"""2.189.0 (#2475): the office's own home currency (ISO 4217) instead of only EUR / USD.

The home currency of an office area is the currency of its price list, its books, cash flow, key figures, travel expenses,
bank and exports; a document in another currency is converted with its rate (fx_rate = units of the document currency per
one unit of the home currency, like the 2.147 USD rate). A country pack fixes it (DE: always EUR, nothing changes for German
offices); a pack with "currency_editable" (the neutral base pack XX) lets the admin choose -- only as long as the office has
no bookings yet (final invoices / credit notes, payments, receipts, travel receipts, bank or cash book entries, opening
balances). No rate service: rates are entered by hand (office rates per currency, per document) as before.

Settings keys (office_settings.data, the previous version ignores the new ones):
 - home_currency: the chosen home currency (only read for an editable pack; missing = the office's currency as in 2.147)
 - currency: the currency of new documents (home or a foreign one), fx_usd: USD per EUR (kept for EUR offices, 2.147),
   fx_rates: {code: rate per one unit of the home currency} for the other foreign currencies."""
from decimal import Decimal

from ..core.i18n import N_

# ISO 4217 currencies with two decimal places (amounts are rounded to cents everywhere); EUR and USD first
HC_CODES = ("EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "BGN", "TRY", "CAD", "AUD", "NZD",
            "CNY", "HKD", "SGD", "INR", "ZAR", "BRL", "MXN", "ILS", "AED", "THB")
HC_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}
HC_LOCKED = N_("The home currency can no longer be changed: this office already has bookings (invoices, payments, receipts).")


def hc_code(v):
    """A currency code ("€" / "$" / "£" / "gbp") -> "GBP"; unknown -> ""."""
    v = {"€": "EUR", "$": "USD", "£": "GBP"}.get(str(v or "").strip(), str(v or "").strip().upper())
    return v if v in HC_CODES else ""


def hc_symbol(cur):
    """The short sign of a currency for screens and calculations (€, $, £, else the code)."""
    return HC_SYMBOLS.get(cur, cur or "")


def hc_pack_editable(pack):
    return bool((pack or {}).get("currency_editable"))


def hc_home_of(stored, pack):
    """The home currency from the stored settings dict and the country pack: a fixed pack -> its currency (DE: EUR); an
    editable one -> the chosen home_currency, else the office's currency as before (2.147: EUR or USD)."""
    fixed = hc_code((pack or {}).get("currency")) or "EUR"
    if not hc_pack_editable(pack):
        return fixed
    return hc_code(stored.get("home_currency")) or hc_code(stored.get("currency")) or fixed


def hc_home(s):
    """The home currency of a resolved settings dict (office_settings)."""
    return hc_code(s.get("home_currency")) or "EUR"


def hc_office_rate(s, cur):
    """The office's rate of currency cur (units of cur per one unit of the home currency) as Decimal, or None when there is
    none. EUR offices keep their USD rate in fx_usd (2.147); a USD office reads it the other way round for EUR."""
    from .calc import dec
    home = hc_home(s)
    cur = hc_code(cur) or home
    if cur == home:
        return Decimal(1)
    r = dec((s.get("fx_rates") or {}).get(cur), "0")
    if r > 0:
        return r
    fx = dec(s.get("fx_usd"), "0")
    if fx > 0 and home == "EUR" and cur == "USD":
        return fx
    if fx > 0 and home == "USD" and cur == "EUR":
        return Decimal(1) / fx
    return None


def hc_doc_fx(r, home):
    """The rate of a document / receipt row r (currency, fx_rate) to the home currency: 1 in the home currency, else its
    fx_rate (missing: 1.09 for USD in a EUR office like before, else 1). amount_home = amount / rate."""
    from .calc import dec
    cur = hc_code(r["currency"]) or home
    if cur == home:
        return Decimal(1)
    fx = dec(r["fx_rate"], "1.09" if cur == "USD" and home == "EUR" else "1")
    return fx if fx > 0 else Decimal(1)


def hc_rate_missing(r, home):
    """2.355.0 C (#2844): True when document row r is in a foreign currency without a rate of its own: a new document and an
    emptied rate field take the office's rate, else 1 (no made-up rate) -- and 1 between two different currencies is no
    rate (none of HC_CODES is pegged 1:1), its EUR tax would be wrong. USD in a EUR office keeps its 1.09 as before."""
    from .calc import dec
    cur = hc_code(r["currency"]) or home
    return cur != home and dec(r["fx_rate"], "0") in (Decimal(0), Decimal(1))


def hc_bookings(c, oid):
    """True when office area oid already has bookings (then the home currency stays as it is)."""
    for sql in ("SELECT 1 FROM office_docs WHERE org_id=? AND kind IN ('invoice', 'credit') AND status<>'draft' AND trial=0 LIMIT 1",
                "SELECT 1 FROM office_payments WHERE org_id=? LIMIT 1",
                "SELECT 1 FROM office_trip_items WHERE org_id=? LIMIT 1",
                "SELECT 1 FROM office_bank_tx WHERE org_id=? LIMIT 1",
                "SELECT 1 FROM office_cash_entries WHERE org_id=? LIMIT 1",
                "SELECT 1 FROM office_opening_balances WHERE org_id=? LIMIT 1",
                # review: assets with a purchase price (depreciation), purchases, the cash flow's start and actual values
                "SELECT 1 FROM office_equipment WHERE org_id=? AND purchase_net<>'' LIMIT 1",
                "SELECT 1 FROM office_purchases WHERE org_id=? LIMIT 1",
                "SELECT 1 FROM office_cf_start WHERE org_id=? LIMIT 1",
                "SELECT 1 FROM office_cf_actual WHERE org_id=? LIMIT 1",
                "SELECT 1 FROM office_bank_balances WHERE org_id=? LIMIT 1"):
        if c.execute(sql, (oid,)).fetchone():
            return True
    from .books import bk_ws
    return bool(c.execute("SELECT 1 FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id WHERE d.ws=? LIMIT 1",
                          (bk_ws(c, oid),)).fetchone())
