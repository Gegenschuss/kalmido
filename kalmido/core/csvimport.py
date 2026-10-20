"""2.140.0 B (#2134): the one reader of bank statements -- the household budget (life/budget.py) and the office's bank
reconciliation (office/bank.py) both read their files here; nothing is stored here and nothing goes from one to the other.

  CSV    csv_table (encoding left to the client: UTF-8, windows-1252 fallback; the delimiter and the header row found here:
         bank exports start with a few lines about the account), csv_guess (which column holds what, the decimal separator,
         the date format; a known bank layout of CSV_PRESETS first), csv_mapping (a client's mapping checked against the
         columns), csv_row (one row with a mapping -> day, amount, kind, text, counterpart or a readable error)
  CAMT   camt_is / camt_rows: CAMT.052 / .053 XML (no DOCTYPE / ENTITY, so no entity expansion and no external references)
  dups   csv_dup_take: "two equal rows of one file need two existing ones" -- each caller keeps its own keyed fingerprint
         (budget: per list with the space key, office: per office area), so equal bookings never meet across areas
Limits: CSV_MAX bytes, CSV_ROWS rows; texts are cut and stripped of control characters. A CSV export of what came in goes
through csv_cell (no formulas in spreadsheet programs)."""
import csv
import hashlib
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .i18n import tr

CSV_MAX, CSV_ROWS = 2 * 1024 * 1024, 3000
CSV_AMOUNT_MAX = Decimal("10000000")
CSV_TEXT_MAX = 200
CAMT_AMOUNT_MAX = Decimal("100000000")
DATE_FORMATS = {"DD.MM.YYYY": r"(\d{1,2})\.(\d{1,2})\.(\d{4})", "YYYY-MM-DD": r"(\d{4})-(\d{1,2})-(\d{1,2})",
                "DD.MM.YY": r"(\d{1,2})\.(\d{1,2})\.(\d{2})", "MM/DD/YYYY": r"(\d{1,2})/(\d{1,2})/(\d{4})"}
MAP_KEYS = ("date", "amount", "amount_in", "amount_out", "title", "counterpart")
IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{8,30}$")
GUESS = {
    "date": ("buchungstag", "buchungsdatum", "datum", "date", "booking date", "transaction date", "valuta", "wertstellung", "value date"),
    "amount": ("betrag", "amount", "umsatz", "betrag (eur)", "betrag in eur", "value"),
    "amount_in": ("haben", "gutschrift", "credit", "eingang", "einnahme"),
    "amount_out": ("soll", "lastschrift", "debit", "ausgang", "ausgabe"),
    "title": ("verwendungszweck", "buchungstext", "beschreibung", "description", "purpose", "memo", "reference", "text", "details"),
    "counterpart": ("beguenstigter/zahlungspflichtiger", "begünstigter/zahlungspflichtiger", "zahlungsempfänger", "zahlungsempfaenger",
                    "empfänger", "empfaenger", "auftraggeber", "name", "payee", "counterparty", "gegenseite", "partner"),
}
# Known export layouts (header names as the banks write them, compared like csv_norm). A preset is taken only when EVERY
# column it names is in the header, so another file never matches by accident; it only pre-fills the choice (the person
# checks it like the guess). Without a match the plain guess above decides as before.
CSV_PRESETS = (
    {"id": "sparkasse", "name": "Sparkasse (CSV-CAMT)", "decimal": ",", "date_format": "DD.MM.YY",
     "cols": {"date": "buchungstag", "amount": "betrag", "title": "verwendungszweck", "counterpart": "beguenstigter/zahlungspflichtiger"},
     "also": ("auftragskonto", "valutadatum", "glaeubiger id")},
    {"id": "ing", "name": "ING", "decimal": ",", "date_format": "DD.MM.YYYY",
     "cols": {"date": "buchung", "amount": "betrag", "title": "verwendungszweck", "counterpart": "auftraggeber/empfänger"},
     "also": ("buchungstext", "saldo")},
    {"id": "dkb", "name": "DKB", "decimal": ",", "date_format": "DD.MM.YY",
     "cols": {"date": "buchungsdatum", "amount": "betrag (€)", "title": "verwendungszweck", "counterpart": "zahlungsempfänger*in"},
     "also": ("wertstellung", "zahlungspflichtige*r", "umsatztyp")},
    {"id": "comdirect", "name": "comdirect", "decimal": ",", "date_format": "DD.MM.YYYY",
     "cols": {"date": "buchungstag", "amount": "umsatz in eur", "title": "buchungstext"},
     "also": ("wertstellung (valuta)", "vorgang")},
)


def _bad(msg):
    from ..personal.timetrack import BadInput  # noqa: PLC0415 -- the app's 400 (a domain class; core imports it here only)
    return BadInput(msg)


def csv_norm(s):
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return re.sub(r"\s+", " ", s).strip()


def csv_clean(v, n=CSV_TEXT_MAX):
    """A text of a statement: no control characters, one space between words, at most n characters."""
    v = re.sub(r"[\x00-\x1f\x7f]", " ", v if isinstance(v, str) else "")
    return re.sub(r"\s+", " ", v).strip()[:n]


def csv_cell(s):
    """Free text for a CSV cell of an export (no formulas, core/serializers.csv_cell)."""
    from .serializers import csv_cell as _cell  # noqa: PLC0415 -- serializers reads the session (accounts)
    return _cell(s)


def csv_dup_take(counts, key):
    """True (and one existing match used up) when counts still holds key: two equal rows of one file need two existing
    bookings to count as duplicates."""
    if counts.get(key):
        counts[key] -= 1
        return True
    return False


# ---------------------------------------------------------------- CSV
def csv_decode(text, max_bytes=CSV_MAX):
    if not isinstance(text, str):
        raise _bad(tr("Invalid value: {0}", "text"))
    if len(text.encode("utf-8", "ignore")) > max_bytes:
        raise _bad(tr("The file is too large (at most {0} MB)", max_bytes // (1024 * 1024)))
    return text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")


def csv_delim(lines):
    best, n = ";", -1
    for d in (";", ",", "\t", "|"):
        counts = [ln.count(d) for ln in lines[:30] if ln.strip()]
        if not counts:
            continue
        top = max(set(counts), key=counts.count)
        score = top * counts.count(top) if top else 0
        if score > n:
            best, n = d, score
    return best


def csv_table(text, max_rows=CSV_ROWS):
    """CSV text -> (delimiter, header, rows): the header is the first row with the most common column count (bank
    exports start with a few lines about the account)."""
    text = csv_decode(text)
    lines = text.split("\n")
    d = csv_delim(lines)
    try:
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=d) if any(x.strip() for x in r)]
    except csv.Error:
        raise _bad(tr("The file cannot be read as CSV")) from None
    if not rows:
        raise _bad(tr("The file is empty"))
    if len(rows) > max_rows + 50:
        raise _bad(tr("At most {0} rows per import", max_rows))
    lens = [len(r) for r in rows]
    common = max(set(lens), key=lens.count)
    hi = next(i for i, r in enumerate(rows) if len(r) == common)
    header = [x.strip()[:80] for x in rows[hi]]
    body = [[x.strip() for x in r] for r in rows[hi + 1:]]
    return d, header, body


def csv_amount(s, dec):
    """'1.234,56' / '-12,30' / '12,30-' / '12.30' / '(12.30)' -> signed Decimal or None."""
    s = (s or "").strip().replace(" ", "").replace(" ", "")
    s = re.sub(r"(?i)(eur|€|\$|usd|chf|£)", "", s)
    if not s:
        return None
    neg = False
    if s.endswith("-"):
        neg, s = True, s[:-1]
    elif s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.startswith("-"):
        neg, s = not neg, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if dec == ",":
        s = s.replace(".", "").replace("'", "").replace(",", ".")
    else:
        s = s.replace(",", "").replace("'", "")
    if not re.fullmatch(r"\d{1,9}(\.\d{1,4})?", s):
        return None
    v = Decimal(s).quantize(Decimal("0.01"))
    return -v if neg else v


def csv_day(s, fmt):
    m = re.fullmatch(DATE_FORMATS[fmt], (s or "").strip())
    if not m:
        return None
    a, b_, y = m.groups()
    if fmt == "YYYY-MM-DD":
        y, a, b_ = a, b_, y
        dd, mm = int(b_), int(a)
    elif fmt == "MM/DD/YYYY":
        dd, mm = int(b_), int(a)
    else:
        dd, mm = int(a), int(b_)
    yy = int(y) + (2000 if len(y) == 2 else 0)
    try:
        return date(yy, mm, dd).isoformat()
    except ValueError:
        return None


def csv_preset(header):
    """The first preset of CSV_PRESETS whose columns are all in header -> (preset, {field: column}) or (None, None)."""
    low = [csv_norm(h) for h in header]
    for p in CSV_PRESETS:
        names = list(p["cols"].values()) + list(p["also"])
        if all(n in low for n in names):
            return p, {k: low.index(n) for k, n in p["cols"].items()}
    return None, None


def _plain_guess(header, body):
    low = [csv_norm(h) for h in header]
    g_ = {}
    for k, names in GUESS.items():
        g_[k] = None
        for n in names:
            hit = next((i for i, h in enumerate(low) if h == n and i not in g_.values()), None)
            if hit is None:
                hit = next((i for i, h in enumerate(low) if n in h and i not in g_.values()), None)
            if hit is not None:
                g_[k] = hit
                break
    if g_["amount"] is not None:
        g_["amount_in"] = g_["amount_out"] = None
    sample = [r for r in body[:50]]
    cols = [g_[k] for k in ("amount", "amount_in", "amount_out") if g_[k] is not None]
    vals = [r[i] for r in sample for i in cols if i < len(r) and r[i]]
    commas = sum(1 for v in vals if re.search(r",\d{1,2}-?$", v))
    dots = sum(1 for v in vals if re.search(r"\.\d{1,2}-?$", v))
    g_["decimal"] = "." if dots > commas else ","
    fmt = "DD.MM.YYYY"
    if g_["date"] is not None:
        ds = [r[g_["date"]] for r in sample if g_["date"] < len(r) and r[g_["date"]]]
        for f in DATE_FORMATS:
            if ds and sum(1 for x in ds if csv_day(x, f)) >= max(1, len(ds) * 0.8):
                fmt = f
                break
    g_["date_format"] = fmt
    return g_


def csv_guess(header, body):
    """{date, amount, amount_in, amount_out, title, counterpart, decimal, date_format, preset, preset_name}: a known layout
    (csv_preset; its date format only when the sample reads with it) or the plain guess (preset None)."""
    g_ = _plain_guess(header, body)
    p, cols = csv_preset(header)
    g_["preset"] = g_["preset_name"] = None
    if p:
        for k in MAP_KEYS:
            g_[k] = cols.get(k)
        g_["decimal"] = p["decimal"]
        ds = [r[cols["date"]] for r in body[:50] if cols["date"] < len(r) and r[cols["date"]]]
        for f in (p["date_format"], *DATE_FORMATS):
            if not ds or sum(1 for x in ds if csv_day(x, f)) >= max(1, len(ds) * 0.8):
                g_["date_format"] = f
                break
        g_["preset"], g_["preset_name"] = p["id"], p["name"]
    return g_


def csv_hkey(header):
    """The fingerprint of a header (a remembered mapping per layout)."""
    return hashlib.sha256("\x1f".join(csv_norm(h) for h in header).encode()).hexdigest()[:24]


def csv_mapping(m, ncols):
    """A client's mapping, checked against the number of columns."""
    if not isinstance(m, dict):
        raise _bad(tr("Invalid value: {0}", "mapping"))
    out = {}
    for k in MAP_KEYS:
        v = m.get(k)
        if v is None:
            out[k] = None
            continue
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < ncols:
            raise _bad(tr("Invalid value: {0}", k))
        out[k] = v
    if out["date"] is None or (out["amount"] is None and out["amount_in"] is None and out["amount_out"] is None):
        raise _bad(tr("Please choose the columns for the date and the amount"))
    if out["title"] is None and out["counterpart"] is None:
        raise _bad(tr("Please choose the column for the text"))
    out["decimal"] = m.get("decimal") if m.get("decimal") in (",", ".") else ","
    out["date_format"] = m.get("date_format") if m.get("date_format") in DATE_FORMATS else "DD.MM.YYYY"
    return out


def csv_row(r, m, title_max=CSV_TEXT_MAX, cp_max=CSV_TEXT_MAX, amount_max=CSV_AMOUNT_MAX):
    """One CSV row with mapping m -> {day, amount (positive float), kind out | in, title, counterpart, error}."""
    def col(k):
        i = m.get(k)
        return r[i] if i is not None and i < len(r) else ""
    out = {"day": None, "amount": None, "kind": "out", "title": "", "counterpart": col("counterpart")[:cp_max], "error": None}
    out["day"] = csv_day(col("date"), m["date_format"])
    amt = None
    if m.get("amount") is not None:
        amt = csv_amount(col("amount"), m["decimal"])
    else:
        a_in = csv_amount(col("amount_in"), m["decimal"]) if m.get("amount_in") is not None else None
        a_out = csv_amount(col("amount_out"), m["decimal"]) if m.get("amount_out") is not None else None
        if a_in:
            amt = abs(a_in)
        elif a_out:
            amt = -abs(a_out)
    title = (col("title") or col("counterpart")).strip()
    out["title"] = re.sub(r"\s+", " ", title)[:title_max]
    if out["day"] is None:
        out["error"] = tr("The date cannot be read")
    elif amt is None or amt == 0 or abs(amt) > amount_max:
        out["error"] = tr("The amount cannot be read")
    elif not out["title"]:
        out["error"] = tr("The row has no text")
    if amt is not None and amt != 0:
        out["amount"], out["kind"] = float(abs(amt).quantize(Decimal("0.01"))), "out" if amt < 0 else "in"
    return out


# ---------------------------------------------------------------- CAMT.052 / .053
def camt_is(text):
    head = (text or "")[:4000]
    return "<Document" in head and "camt.05" in head


def camt_local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def camt_kids(el, name):
    return [x for x in el if camt_local(x.tag) == name]


def camt_kid(el, *path):
    for name in path:
        if el is None:
            return None
        el = next((x for x in el if camt_local(x.tag) == name), None)
    return el


def camt_txt(el, *path):
    el = camt_kid(el, *path)
    return (el.text or "").strip() if el is not None and el.text else ""


def _camt_day(el):
    if el is None:
        return None
    v = camt_txt(el, "Dt") or camt_txt(el, "DtTm")[:10]
    try:
        return date.fromisoformat(v[:10]).isoformat() if v else None
    except ValueError:
        return None


def _money(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def camt_rows(text, text_max=300):
    """CAMT.052 / .053 XML -> [{day, amount (signed Decimal), currency, counterpart, purpose, iban, ref, error}]. Documents
    with a DOCTYPE or an ENTITY are refused before parsing (no entity expansion, no external references)."""
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.I):
        raise _bad(tr("The file contains a DOCTYPE or an ENTITY and is not read"))
    try:
        # the client sends text (UTF-8, cp1252 fallback): a declared encoding (ISO-8859-1 ...) would make expat decode twice
        root = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text.lstrip("﻿")).encode("utf-8"))
    except (ET.ParseError, ValueError):
        raise _bad(tr("The file cannot be read as CAMT")) from None
    out = []
    for ntry in root.iter():
        if camt_local(ntry.tag) != "Ntry":
            continue
        amt_el = camt_kid(ntry, "Amt")
        row = {"day": _camt_day(camt_kid(ntry, "BookgDt")) or _camt_day(camt_kid(ntry, "ValDt")), "amount": None,
               "currency": ((amt_el.get("Ccy") if amt_el is not None else "") or "").upper()[:3], "counterpart": "", "purpose": "",
               "iban": None, "ref": csv_clean(camt_txt(ntry, "AcctSvcrRef"), 120) or None, "error": None}
        credit = camt_txt(ntry, "CdtDbtInd") == "CRDT"
        try:
            a = Decimal((amt_el.text or "").strip()) if amt_el is not None else None
        except (ArithmeticError, ValueError):
            a = None
        if a is not None and a.is_finite() and 0 < a <= CAMT_AMOUNT_MAX and _money(a) != 0:  # 0.004 -> 0.00 = unreadable
            row["amount"] = _money(a if credit else -a)
        tx = camt_kid(ntry, "NtryDtls", "TxDtls")
        if tx is not None:
            purpose = [(x.text or "").strip() for x in camt_kids(camt_kid(tx, "RmtInf") if camt_kid(tx, "RmtInf") is not None else tx, "Ustrd")]
            row["purpose"] = csv_clean(" ".join(p for p in purpose if p), text_max)
            pts = camt_kid(tx, "RltdPties")
            if pts is not None:
                side, acct = ("Dbtr", "DbtrAcct") if credit else ("Cdtr", "CdtrAcct")
                p = camt_kid(pts, side)
                if p is not None:
                    row["counterpart"] = csv_clean(camt_txt(p, "Nm") or camt_txt(p, "Pty", "Nm"), 200)
                iban = camt_txt(pts, acct, "Id", "IBAN").replace(" ", "").upper()
                row["iban"] = iban if IBAN_RE.match(iban) else None
            if not row["ref"]:
                row["ref"] = csv_clean(camt_txt(tx, "Refs", "AcctSvcrRef") or camt_txt(tx, "Refs", "EndToEndId"), 120) or None
            if row["ref"] == "NOTPROVIDED":
                row["ref"] = None
        if not row["purpose"]:
            row["purpose"] = csv_clean(camt_txt(ntry, "AddtlNtryInf"), text_max)
        if row["day"] is None:
            row["error"] = tr("The date cannot be read")
        elif row["amount"] is None:
            row["error"] = tr("The amount cannot be read")
        out.append(row)
    if not out:
        raise _bad(tr("The file contains no bookings"))
    return out
