"""Office & finance (2.47.3, #1460): the DATEV booking batch (EXTF "Buchungsstapel", format 700, category 21) of the
finalised invoices, credit notes and payments of a period, for the tax advisor. Complements the DATEV document inbox
(invoices.py, #1362), changes nothing there.

The file: a header line (31 fields), the column names (125 fields of format version 13) and one booking line per tax rate of
a document (gross amount, debtor against the revenue account of that rate) and per payment (bank or cash against the
debtor). Semicolons, text fields in double quotes, decimal comma without thousands separators, document date DDMM,
Windows-1252, CRLF. The batch never spans two fiscal years (DATEV refuses such batches).

Settings (office_settings.data["datev_extf"], admin): advisor and client number, start month of the fiscal year, length of
the general ledger accounts, chart SKR03 / SKR04 (default accounts per tax case), own accounts / tax keys (BU) per case,
collective debtor, bank and cash account. A client's customer number becomes its debtor when it is a valid debtor
number (digits, ledger length + 1, first digit 1-6), else the collective debtor. Small business (section 19 UStG): the
documents without VAT and the note "small" (or the office's small business switch) go to the small business revenue
account without a tax key. No agent reaches any of this (office_gate)."""
import json
import re
from datetime import date, timedelta
from decimal import Decimal

from flask import g, jsonify, request, Response

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import db, local_now
from ..personal.timetrack import BadInput
from .calc import dec, money
from .model import office_gate, office_org, office_settings
from .ledger import ofx_log

# tax cases -> the default revenue accounts per chart (automatic accounts: DATEV adds the VAT itself, no tax key needed)
DX_CASES = ("standard", "reduced", "exempt", "reverse", "abroad", "small")
DX_CHARTS = {
    "SKR03": {"standard": "8400", "reduced": "8300", "exempt": "8100", "reverse": "8337", "abroad": "8338", "small": "8195",
              "debtor": "10000", "bank": "1200", "cash": "1000"},
    "SKR04": {"standard": "4400", "reduced": "4300", "exempt": "4100", "reverse": "4337", "abroad": "4338", "small": "4185",
              "debtor": "10000", "bank": "1800", "cash": "1600"},
}
DX_DEFAULTS = {"advisor_no": "", "client_no": "", "fy_start": 1, "acct_len": 4, "chart": "SKR03",
               "accounts": {}, "bu": {}, "debtor": "", "bank": "", "cash": ""}
DX_NEED_IDS = N_("Enter the advisor number and the client number of the DATEV export in the settings first")
DX_FY_SPAN = N_("The period must lie within one fiscal year (DATEV): {0} to {1}")

# the header line: 31 fields, the column line: 125 fields (DATEV format 700, booking batch format version 13)
DX_COLUMNS = (
    "Umsatz (ohne Soll/Haben-Kz)", "Soll/Haben-Kennzeichen", "WKZ Umsatz", "Kurs", "Basis-Umsatz", "WKZ Basis-Umsatz", "Konto",
    "Gegenkonto (ohne BU-Schlüssel)", "BU-Schlüssel", "Belegdatum", "Belegfeld 1", "Belegfeld 2", "Skonto", "Buchungstext",
    "Postensperre", "Diverse Adressnummer", "Geschäftspartnerbank", "Sachverhalt", "Zinssperre", "Beleglink",
    *[f"Beleginfo - {k} {i}" for i in range(1, 9) for k in ("Art", "Inhalt")],
    "KOST1 - Kostenstelle", "KOST2 - Kostenstelle", "Kost-Menge", "EU-Land u. UStID (Bestimmung)", "EU-Steuersatz (Bestimmung)",
    "Abw. Versteuerungsart", "Sachverhalt L+L", "Funktionsergänzung L+L", "BU 49 Hauptfunktionstyp", "BU 49 Hauptfunktionsnummer",
    "BU 49 Funktionsergänzung",
    *[f"Zusatzinformation - {k} {i}" for i in range(1, 21) for k in ("Art", "Inhalt")],
    "Stück", "Gewicht", "Zahlweise", "Forderungsart", "Veranlagungsjahr", "Zugeordnete Fälligkeit", "Skontotyp", "Auftragsnummer",
    "Buchungstyp", "USt-Schlüssel (Anzahlungen)", "EU-Mitgliedstaat (Anzahlungen)", "Sachverhalt L+L (Anzahlungen)",
    "EU-Steuersatz (Anzahlungen)", "Erlöskonto (Anzahlungen)", "Herkunft-Kz", "Buchungs GUID", "KOST-Datum", "SEPA-Mandatsreferenz",
    "Skontosperre", "Gesellschaftername", "Beteiligtennummer", "Identifikationsnummer", "Zeichnernummer", "Postensperre bis",
    "Bezeichnung SoBil-Sachverhalt", "Kennzeichen SoBil-Buchung", "Festschreibung", "Leistungsdatum", "Datum Zuord. Steuerperiode",
    "Fälligkeit", "Generalumkehr (GU)", "Steuersatz", "Land", "Abrechnungsreferenz", "BVV-Position", "EU-Mitgliedstaat u. UStID (Ursprung)",
    "EU-Steuersatz (Ursprung)", "Abw. Skontokonto")
DX_COL = {n: i for i, n in enumerate(DX_COLUMNS)}
DX_HEADER_FIELDS = 31
BELEG_RE = re.compile(r"[^A-Za-z0-9$&%*+\-/]")  # the characters DATEV allows in Belegfeld 1


def _q(s):
    """A text field: in double quotes, inner quotes doubled, no line breaks or semicolon trouble."""
    return '"' + re.sub(r"[\x00-\x1f\x7f]+", " ", str(s or "")).replace('"', '""') + '"'  # 2.47.3 (review K1): every control character


def _amt(d):
    return format(money(abs(dec(d))), "f").replace(".", ",")


# ---------------------------------------------------------------- settings
def dx_settings(s):
    """The DATEV export settings out of the office settings dict (defaults filled)."""
    out = json.loads(json.dumps(DX_DEFAULTS))
    v = s.get("datev_extf") if isinstance(s, dict) else None
    if isinstance(v, dict):
        for k in DX_DEFAULTS:
            if k in v and v[k] is not None:
                out[k] = v[k]
    return out


def _digits(v, name, lo, hi, empty_ok=True):
    v = str(v if v is not None else "").strip()
    if not v and empty_ok:
        return ""
    if not re.fullmatch(r"\d{%d,%d}" % (lo, hi), v):
        raise BadInput(tr("Invalid value: {0}", name))
    return v


def dx_settings_clean(v, cur):
    """Validates the partial "datev_extf" body against the current settings -> the new dict."""
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", "datev_extf"))
    out = dx_settings({"datev_extf": cur})
    if "advisor_no" in v:
        out["advisor_no"] = _digits(v["advisor_no"], "advisor_no", 4, 7)  # Beraternummer 1001-9999999
        if out["advisor_no"] and int(out["advisor_no"]) < 1001:
            raise BadInput(tr("Invalid value: {0}", "advisor_no"))
    if "client_no" in v:
        out["client_no"] = _digits(v["client_no"], "client_no", 1, 5)  # Mandantennummer 1-99999
        if out["client_no"] and int(out["client_no"]) < 1:
            raise BadInput(tr("Invalid value: {0}", "client_no"))
    if "fy_start" in v:
        try:
            m = int(v["fy_start"])
        except (TypeError, ValueError):
            m = 0
        if not 1 <= m <= 12:
            raise BadInput(tr("Invalid value: {0}", "fy_start"))
        out["fy_start"] = m
    if "acct_len" in v:
        try:
            n = int(v["acct_len"])
        except (TypeError, ValueError):
            n = 0
        if not 4 <= n <= 8:
            raise BadInput(tr("Invalid value: {0}", "acct_len"))
        out["acct_len"] = n
    if "chart" in v:
        if v["chart"] not in DX_CHARTS:
            raise BadInput(tr("Invalid value: {0}", "chart"))
        out["chart"] = v["chart"]
    n = int(out["acct_len"])
    if "accounts" in v:
        a = v["accounts"] if isinstance(v["accounts"], dict) else {}
        out["accounts"] = {k: _digits(a.get(k), k, 1, n) for k in DX_CASES if str(a.get(k) or "").strip()}
    if "bu" in v:
        b = v["bu"] if isinstance(v["bu"], dict) else {}
        out["bu"] = {k: _digits(b.get(k), "BU " + k, 1, 4) for k in DX_CASES if str(b.get(k) or "").strip()}
    for k, mx in (("debtor", n + 1), ("bank", n), ("cash", n)):
        if k in v:
            out[k] = _digits(v[k], k, 1, mx)
    return out


def _acct(st, key):
    """An account of the settings or the chart's default, the defaults stretched to the ledger length (8400 -> 84000)."""
    own = (st["accounts"].get(key) if key in DX_CASES else st.get(key)) or ""
    if own:
        return own
    dflt = DX_CHARTS.get(st["chart"], DX_CHARTS["SKR03"])[key]
    n = int(st["acct_len"]) + (1 if key == "debtor" else 0)
    return dflt.ljust(n, "0")


def dx_fiscal_year(d, start_month):
    """(first day, last day) of the fiscal year that contains date d."""
    y = d.year if d.month >= start_month else d.year - 1
    first = date(y, start_month, 1)
    nxt = date(y + 1, start_month, 1)
    return first, nxt - timedelta(days=1)


def dx_debtor(st, customer_no):
    """The client's debtor account: its customer number when that is a valid debtor number, else the collective debtor."""
    n = int(st["acct_len"]) + 1
    cn = str(customer_no or "").strip()
    if re.fullmatch(r"[1-6]\d{%d}" % (n - 1), cn):
        return cn
    return st["debtor"] or _acct(st, "debtor")


# ---------------------------------------------------------------- the batch
def _ddmm(iso_date):
    return iso_date[8:10] + iso_date[5:7] if iso_date and len(iso_date) >= 10 else ""


def _ddmmyyyy(iso_date):
    return iso_date[8:10] + iso_date[5:7] + iso_date[0:4] if iso_date and len(iso_date) >= 10 else ""


def _j(s):
    try:
        v = json.loads(s) if s else {}
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _fx(r, t):
    """The document's rate (USD per 1 EUR) or 1 for EUR documents."""
    if (r["currency"] or "EUR").upper() != "USD":
        return Decimal(1)
    f = dec(t.get("fx_rate") or r["fx_rate"] or 0)
    return f if f > 0 else Decimal(1)


def _case(r, s):
    """The tax case of a document without VAT (vat_note), else None (the tax lines decide)."""
    if (r["vat_mode"] or "vat") != "novat":
        return None
    note = (r["vat_note"] if "vat_note" in r.keys() else "") or ""
    if note in ("reverse", "abroad", "small"):
        return note
    return "exempt"  # 2.47.3 (review S2): the document's own note decides, never today's switch (documents already exported keep their account)


def dx_rows(c, oid, d_from, d_to, s=None):
    """The booking lines (dicts of DX_COLUMNS names) of the period [d_from, d_to] (ISO dates)."""
    s = s if s is not None else office_settings(c, oid)
    st = dx_settings(s)
    out = []
    docs = c.execute("SELECT d.*, cl.customer_no AS dx_customer_no, cl.name AS dx_client_name FROM office_docs d "
                     "LEFT JOIN clients cl ON cl.id=d.client_id WHERE d.org_id=? AND d.kind IN ('invoice','credit') "
                     "AND d.locked_at IS NOT NULL AND d.number != '' AND d.date>=? AND d.date<=? ORDER BY d.date, d.number",
                     (oid, d_from, d_to)).fetchall()
    for r in docs:
        t = _j(r["totals"])
        fx = _fx(r, t)
        debtor = dx_debtor(st, r["dx_customer_no"])
        name = (_j(r["recipient"]).get("name") or r["dx_client_name"] or "").strip()
        text = (r["number"] + " " + name).strip()[:60]
        perf = _ddmmyyyy(r["service_to"] or r["date"] or "") if "service_to" in r.keys() else ""
        case = _case(r, s)
        parts = []  # (case, gross amount in the document's currency)
        if case:
            parts.append((case, dec(t.get("gross") or 0)))
        else:
            for tl in t.get("tax_lines") or []:
                parts.append((tl.get("rate_key") or "standard", dec(tl.get("base") or 0) + dec(tl.get("amount") or 0)))
            if not parts:  # a document without positions or tax lines: the gross on the standard account
                parts.append(("standard", dec(t.get("gross") or 0)))
        # 2.47.3 (review S1): in USD every line is rounded on its own -> the rounding difference to the document's gross in
        # EUR goes onto the last line, so the debtor balances with the payment
        conv = [(k, money(a / fx)) for k, a in parts]
        if fx != 1 and conv:
            diff = money(dec(t.get("gross") or 0) / fx) - sum((a for _, a in conv), Decimal(0))
            if diff and abs(diff) <= Decimal("0.05"):
                conv[-1] = (conv[-1][0], conv[-1][1] + diff)
        for k, amount in conv:
            if amount == 0:
                continue
            sign = "S" if (amount > 0) == (r["kind"] == "invoice") else "H"
            out.append({"Umsatz (ohne Soll/Haben-Kz)": _amt(amount), "Soll/Haben-Kennzeichen": sign, "WKZ Umsatz": "EUR",
                        "Konto": debtor, "Gegenkonto (ohne BU-Schlüssel)": _acct(st, k if k in DX_CASES else "standard"),
                        "BU-Schlüssel": st["bu"].get(k, "") if k not in ("small",) else "",
                        "Belegdatum": _ddmm(r["date"]), "Belegfeld 1": BELEG_RE.sub("-", r["number"])[:36],
                        "Buchungstext": text, "Leistungsdatum": perf, "Festschreibung": "0",
                        "_date": r["date"], "_kind": r["kind"]})
    pays = c.execute("SELECT p.date AS p_date, p.amount AS p_amount, p.method AS p_method, d.*, cl.customer_no AS dx_customer_no, "
                     "cl.name AS dx_client_name FROM office_payments p JOIN office_docs d ON d.id=p.doc_id "
                     "LEFT JOIN clients cl ON cl.id=d.client_id WHERE p.org_id=? AND d.org_id=? AND p.date>=? AND p.date<=? "
                     "ORDER BY p.date, p.id", (oid, oid, d_from, d_to)).fetchall()
    for r in pays:
        t = _j(r["totals"])
        amount = money(dec(r["p_amount"] or 0) / _fx(r, t))
        if amount == 0:
            continue
        sign = "S" if (amount > 0) == (r["kind"] != "credit") else "H"  # a payment on a credit note = money paid back
        name = (_j(r["recipient"]).get("name") or r["dx_client_name"] or "").strip()
        out.append({"Umsatz (ohne Soll/Haben-Kz)": _amt(amount), "Soll/Haben-Kennzeichen": sign, "WKZ Umsatz": "EUR",
                    "Konto": (st["cash"] or _acct(st, "cash")) if r["p_method"] == "cash" else (st["bank"] or _acct(st, "bank")),
                    "Gegenkonto (ohne BU-Schlüssel)": dx_debtor(st, r["dx_customer_no"]), "BU-Schlüssel": "",
                    "Belegdatum": _ddmm(r["p_date"]), "Belegfeld 1": BELEG_RE.sub("-", r["number"] or "")[:36],
                    "Buchungstext": ("Zahlung " + (r["number"] or "") + " " + name).strip()[:60], "Festschreibung": "0",
                    "_date": r["p_date"], "_kind": "payment"})
    out.sort(key=lambda x: x["_date"] or "")
    return out


def dx_check(st, d_from, d_to):
    """Raises BadInput when the batch cannot be made (numbers missing, period spans two fiscal years)."""
    if not st["advisor_no"] or not st["client_no"]:
        raise BadInput(tr(DX_NEED_IDS))
    a, b = dx_fiscal_year(date.fromisoformat(d_from), int(st["fy_start"]))
    if date.fromisoformat(d_to) > b:
        raise BadInput(tr(DX_FY_SPAN, a.strftime("%d.%m.%Y"), b.strftime("%d.%m.%Y")))


def dx_extf(c, oid, d_from, d_to, by="", s=None, now=None):
    """The batch file as bytes (Windows-1252) + the number of booking lines."""
    s = s if s is not None else office_settings(c, oid)
    st = dx_settings(s)
    dx_check(st, d_from, d_to)
    rows = dx_rows(c, oid, d_from, d_to, s)
    now = now or local_now()
    fy = dx_fiscal_year(date.fromisoformat(d_from), int(st["fy_start"]))[0]
    head = ['"EXTF"', "700", "21", '"Buchungsstapel"', "13", now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}", "",
            '"RE"', _q(by[:25]), '""', st["advisor_no"], st["client_no"], fy.strftime("%Y%m%d"), str(int(st["acct_len"])),
            d_from.replace("-", ""), d_to.replace("-", ""), _q("Kalmido " + d_from.replace("-", "") + "-" + d_to.replace("-", "")), '""', "1", "0", "0", '"EUR"',
            "", '""', "", "", '"' + st["chart"][3:] + '"', "", "", "", '""']
    assert len(head) == DX_HEADER_FIELDS
    lines = [";".join(head), ";".join(DX_COLUMNS)]
    numeric = {"Umsatz (ohne Soll/Haben-Kz)", "Konto", "Gegenkonto (ohne BU-Schlüssel)", "Belegdatum", "Festschreibung", "Leistungsdatum"}
    for r in rows:
        vals = []
        for n in DX_COLUMNS:
            v = r.get(n, "")
            vals.append(str(v) if n in numeric else (_q(v) if v != "" else ""))
        lines.append(";".join(vals))
    data = ("\r\n".join(lines) + "\r\n").encode("cp1252", errors="replace")
    return data, len(rows)


def _prev_month():
    first = local_now().date().replace(day=1)
    last = first - timedelta(days=1)
    return last.replace(day=1).isoformat(), last.isoformat()


def _period():
    pf, pt = _prev_month()
    d_from = (request.args.get("from") or pf).strip()
    d_to = (request.args.get("to") or pt).strip()
    try:
        a, b = date.fromisoformat(d_from), date.fromisoformat(d_to)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "from / to"))
    if b < a:
        raise BadInput(tr("The end lies before the start"))
    return a.isoformat(), b.isoformat()


@app.get("/api/office/datev/extf")
def dx_extf_get():
    """Org admin: ?from=YYYY-MM-DD&to=YYYY-MM-DD (default: the previous month) -> the EXTF booking batch as a CSV download;
    ?check=1 -> {count, from, to, file} only (the client checks before the download and shows errors as text)."""
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=True)
    d_from, d_to = _period()
    u = g.user
    by = (u["display_name"] if "display_name" in u.keys() else "") or u["username"]
    data, n = dx_extf(c, oid, d_from, d_to, by=by)
    fname = f"EXTF_Buchungsstapel_{d_from.replace('-', '')}_{d_to.replace('-', '')}.csv"
    if request.args.get("check"):
        return jsonify(count=n, **{"from": d_from, "to": d_to}, file=fname)
    ofx_log(c, oid, "export", target="datev", detail={"from": d_from, "to": d_to, "count": n})
    c.commit()
    return Response(data, mimetype="text/csv; charset=windows-1252", headers={"Content-Disposition": f"attachment; filename=\"{fname}\""})
