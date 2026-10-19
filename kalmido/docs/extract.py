"""2.48.0 (#1111): date, due date and amount of a document from its text -- without any agent or language model.

Pure Python (standard library only, loaded by the unit test without the app). The document date is the first plausible
date (not before 1990, not more than a year in the future). The due date comes from words like "fällig", "zahlbar
bis", "due", "payable by" followed by a date, or "Zahlungsziel 14 Tage" / "within 30 days" (counted from the document
date). The amount comes from a line with a total word ("Gesamtbetrag", "Rechnungsbetrag", "zu zahlen", "Summe",
"Total", ...); without such a line, the largest amount with a currency. IBANs, phone numbers and postal codes are not
amounts (an amount needs two decimals or a currency) and never dates (a date needs separators)."""
import re
import unicodedata
from datetime import date, timedelta

MONTHS = {
    # German
    "januar": 1, "jan": 1, "jänner": 1, "jaenner": 1, "februar": 2, "feb": 2, "märz": 3, "maerz": 3, "marz": 3, "mär": 3,
    "mrz": 3, "april": 4, "apr": 4, "mai": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9, "oktober": 10, "okt": 10, "november": 11, "nov": 11, "dezember": 12, "dez": 12,
    # English
    "january": 1, "february": 2, "march": 3, "mar": 3, "may": 5, "june": 6, "july": 7, "october": 10, "oct": 10,
    "december": 12, "dec": 12,
}
_MON = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))
_B = r"(?<![\w.,/-])"   # no digit / letter / separator right before a date
_E = r"(?![\w/-]|[.,]\d)"  # ... and none right after it (a sentence dot is fine)

DATE_RES = [
    # 15.10.2026, 15.10.26, 15/10/2026, 15-10-2026 (day first, the European order)
    ("dmy", re.compile(_B + r"(\d{1,2})([./-])(\d{1,2})\2(\d{4}|\d{2})" + _E)),
    # 2026-10-15, 2026/10/15
    ("ymd", re.compile(_B + r"(\d{4})([-/.])(\d{1,2})\2(\d{1,2})" + _E)),
    # 15. Oktober 2026, 15 October 2026, 15. Okt. 2026, 15th of October 2026
    ("dMy", re.compile(_B + r"(\d{1,2})(?:\.|st|nd|rd|th)?\s*(?:of\s+)?(" + _MON + r")\.?,?\s+(\d{4})" + _E, re.I)),
    # October 15, 2026, Oct 15th 2026
    ("Mdy", re.compile(r"(?<![\w])(" + _MON + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})" + _E, re.I)),
]
DUE_WORDS = re.compile(r"(f(?:ä|ae|a)llig(?:\s*(?:am|bis|zum))?|zahlbar\s+(?:bis|zum|am)(?:\s+(?:zum|sp(?:ä|ae)testens))?|"
                       r"zahlungsfrist(?:\s+bis)?|bitte\s+(?:(?:begleichen|zahlen|(?:ü|ue)berweisen)\s+sie\s+)?bis(?:\s+zum)?|"
                       r"due(?:\s+(?:date|on|by))?|payable\s+(?:by|on|until)|payment\s+due|pay\s+by)\s*[:\-]?\s*", re.I)
TERM_RE = re.compile(r"(?:zahlungsziel|zahlbar|payment\s+terms?|net|netto|due|payable|innerhalb|within)\D{0,40}?(\d{1,3})\s*"
                     r"(?:tage|tagen|days|tg\.?)", re.I)
TOTAL_WORDS = [  # strongest first
    ("gesamtbetrag", 6), ("rechnungsbetrag", 6), ("zu zahlen", 6), ("zahlbetrag", 6), ("endbetrag", 6), ("amount due", 6),
    ("total due", 6), ("balance due", 6), ("grand total", 6), ("bruttobetrag", 5), ("gesamtsumme", 5), ("total amount", 5),
    ("gesamt", 4), ("brutto", 4), ("summe", 3), ("total", 3), ("betrag", 2), ("amount", 2),
]
NOT_TOTAL = re.compile(r"\b(netto|zwischensumme|subtotal|sub-total|mwst|ust|vat|steuer|tax|rabatt|discount|skonto)\b", re.I)
CUR = r"(?:€|eur|euro|\$|usd|chf|£|gbp)"
CUR_CODE = {"€": "EUR", "eur": "EUR", "euro": "EUR", "$": "USD", "usd": "USD", "chf": "CHF", "£": "GBP", "gbp": "GBP"}
_NUM = r"(\d{1,3}(?:[.,'  ]\d{3})+(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)"
AMOUNT_RE = re.compile(r"(?<![\w.,])(?:(" + CUR + r")\s*)?" + r"(-?)" + _NUM + r"(?![\d])(?:\s*(" + CUR + r")(?![a-z]))?", re.I)
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,3})?\b")
PHONE_RE = re.compile(r"(?:tel|telefon|phone|fon|fax|mobil|handy)\.?\s*[:.]?\s*[+\d][\d\s/().-]{5,}", re.I)
TEXT_CAP = 60_000  # characters looked at (the date and the total sit on the first pages)
MAX_AMOUNT = 100_000_000


def _fold(s):
    return unicodedata.normalize("NFC", s or "")


def _year(y):
    y = int(y)
    return y + (2000 if y < 70 else 1900) if y < 100 else y


def _mk(y, m, d):
    try:
        return date(_year(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def find_dates(text):
    """[(pos, end, date)] of every date in text, in reading order (duplicates of a span removed)."""
    text = _fold(text)[:TEXT_CAP]
    out = []
    for kind, rx in DATE_RES:
        for m in rx.finditer(text):
            g = m.groups()
            if kind == "dmy":
                d = _mk(g[3], g[2], g[0])
                if d is None and g[1] == "/":   # 10/15/2026: the US order when the day-first reading is no date
                    d = _mk(g[3], g[0], g[2])
            elif kind == "ymd":
                d = _mk(g[0], g[2], g[3])
            elif kind == "dMy":
                d = _mk(g[2], MONTHS.get(g[1].lower().rstrip(".")), g[0])
            else:
                d = _mk(g[2], MONTHS.get(g[0].lower().rstrip(".")), g[1])
            if d is not None:
                out.append((m.start(), m.end(), d))
    out.sort()
    keep, last = [], -1
    for s, e, d in out:
        if s >= last:
            keep.append((s, e, d))
            last = e
    return keep


def plausible(d, today=None):
    today = today or date.today()
    return date(1990, 1, 1) <= d <= today + timedelta(days=366)


def doc_date(text, today=None):
    """The document date: the first plausible date that is not a due date (None when there is none)."""
    dues = {s for s, _ in _due_spans(text)}
    for s, _e, d in find_dates(text):
        if plausible(d, today) and s not in dues:
            return d
    for _s, _e, d in find_dates(text):
        if plausible(d, today):
            return d
    return None


def _due_spans(text):
    """[(date start, date)] of dates right after a due word."""
    text = _fold(text)[:TEXT_CAP]
    dates = find_dates(text)
    out = []
    for m in DUE_WORDS.finditer(text):
        for s, _e, d in dates:
            if m.end() <= s <= m.end() + 12:
                out.append((s, d))
                break
    return out


def due_date(text, doc=None, today=None):
    """The due date: a date after a due word, else the document date plus a payment term in days (None without one)."""
    for _s, d in _due_spans(text):
        if plausible(d, today):
            return d
    text = _fold(text)[:TEXT_CAP]
    base = doc or doc_date(text, today)
    m = TERM_RE.search(text)
    if base and m and 0 < int(m.group(1)) <= 180:
        return base + timedelta(days=int(m.group(1)))
    return None


def parse_number(s):
    """'1.234,56' / '1,234.56' / '1 234,56' / '12,5' -> Decimal-like text '1234.56' (None when it is no amount)."""
    s = s.replace(" ", " ").replace("'", " ").strip()
    if not s:
        return None
    last = max(s.rfind(","), s.rfind("."))
    if last >= 0 and len(s) - last - 1 == 2:      # two decimals after the last separator
        whole, frac = s[:last], s[last + 1:]
    else:
        whole, frac = s, "00"
    whole = re.sub(r"[ .,]", "", whole)
    if not whole.isdigit() or not frac.isdigit():
        return None
    v = int(whole) * 100 + int(frac)
    if v <= 0 or v > MAX_AMOUNT * 100:
        return None
    return f"{v // 100}.{v % 100:02d}"


def _clean(text):
    text = IBAN_RE.sub(" ", text)
    return PHONE_RE.sub(" ", text)


def find_amounts(line):
    """[(value text, currency or None, has decimals)] on one line."""
    out = []
    for m in AMOUNT_RE.finditer(line):
        cur = (m.group(1) or m.group(4) or "").lower()
        num = m.group(3)
        has_dec = bool(re.search(r"[.,]\d{2}$", num))
        if not has_dec and not cur:
            continue                     # a bare whole number: a postal code, an id, a count
        if m.group(2):
            continue                     # negative: a credit or a discount line
        v = parse_number(num)
        if v:
            out.append((v, CUR_CODE.get(cur), has_dec))
    return out


def doc_amount(text):
    """{'amount': '1234.56', 'currency': 'EUR' | None} or None."""
    text = _clean(_fold(text)[:TEXT_CAP])
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    best = None  # (weight, line index, value, currency)
    for i, ln in enumerate(lines):
        low = ln.lower()
        w = next((wt for word, wt in TOTAL_WORDS if re.search(r"(?<![a-zäöü])" + re.escape(word) + r"(?![a-zäöü])", low)), 0)
        if not w or (NOT_TOTAL.search(low) and w < 5):
            continue
        am = find_amounts(ln)
        if not am and i + 1 < len(lines) and len(ln) < 40:
            am = find_amounts(lines[i + 1])  # the amount on the next line (table layouts)
        if not am:
            continue
        v, cur, _ = am[-1]
        cand = (w, i, v, cur)
        if best is None or cand[0] > best[0] or (cand[0] == best[0] and cand[1] > best[1]):
            best = cand
    if best:
        return {"amount": best[2], "currency": best[3] or _doc_currency(text)}
    return None      # 2.98.0 D (#2178): no total line, no guess (the largest amount with a currency is gone)


def _doc_currency(text):
    m = re.search(CUR, text, re.I)
    return CUR_CODE.get(m.group(0).lower()) if m else None


PAY_RE = re.compile(r"(?:nach|zu)\s*zu?zahl\w*|nachzahlung|zahlbetrag", re.I)
PAY_BY = re.compile(r"\b(?:bis(?:\s+zum)?|sp(?:ä|ae)testens(?:\s+(?:bis|am|zum))?|am|zum)\s*", re.I)


def pay_line(text, today=None):
    """2.98.0 D (#2178): (due date | None, amount | None) of a line like 'Nachzahlung 123,45 EUR zu zahlen bis 15.11.2026' (a tax
    notice that is no invoice); both come from that one line (the amount may sit on the next line)."""
    lines = [ln.strip() for ln in _clean(_fold(text)[:TEXT_CAP]).splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        m = PAY_RE.search(ln)
        if not m or NOT_TOTAL.search(ln.lower()):
            continue
        due = None
        for s, _e, d in find_dates(ln):
            if s > m.start() and plausible(d, today) and PAY_BY.search(ln[:s]):
                due = d
                break
        if not due:
            continue
        bare = ln
        for s0, e0, _d in reversed(find_dates(ln)):      # a date is no amount ("03.11" would read as 3.11)
            bare = bare[:s0] + " " * (e0 - s0) + bare[e0:]
        am = find_amounts(bare) or (find_amounts(lines[i + 1]) if i + 1 < len(lines) and len(ln) < 60 else [])
        v, cur = (am[-1][0], am[-1][1]) if am else (None, None)
        return due, ({"amount": v, "currency": cur or _doc_currency(ln)} if v else None)
    return None, None


def extract(text, today=None, guess=True, details=False):
    """{'date': 'YYYY-MM-DD' | None, 'due': .. | None, 'amount': '12.34' | None, 'currency': 'EUR' | None}. guess False (a
    document that is no invoice / receipt): the due date and amount only from a 'to pay until' line (pay_line). 2.121.0 A
    (#2092): details=True adds 'details' = ex_details (supplier, VAT, net / gross, invoice number; only with guess)."""
    d = doc_date(text or "", today)
    if guess:
        due = due_date(text or "", d, today)
        a = doc_amount(text or "") or {}
    else:
        due, a = pay_line(text or "", today)
        a = a or {}
    if due and d and due < d:
        due = None
    out = {"date": d.isoformat() if d else None, "due": due.isoformat() if due else None,
           "amount": a.get("amount"), "currency": a.get("currency")}
    if details:
        out["details"] = ex_details(text) if guess else None
    return out


def find_asn(prefix, texts):
    """The archive serial number in codes / texts: prefix + digits ("ASN00042", "ASN 42", "asn-42") -> 42, the first one
    found (texts in their order: the QR codes first, then the recognised text). None without one."""
    prefix = (prefix or "ASN").strip()
    if not prefix:
        return None
    rx = re.compile(r"(?<![A-Za-z0-9])" + re.escape(prefix) + r"[\s:#-]?0*(\d{1,9})(?!\d)", re.I)
    for t in texts:
        m = rx.search((t or "")[:TEXT_CAP])
        if m and int(m.group(1)) > 0:
            return int(m.group(1))
    return None


# ---- 2.121.0 A (#2092): supplier, VAT, net / VAT / gross and the invoice number of a receipt (a suggestion the person
# confirms; nothing of it is set on its own). Rules only, German and English.
RX_FORM = re.compile(r"(?<![\w&])(?:gGmbH|GmbH(?:\s*&\s*Co\.?\s*KG(?:aA)?)?|mbH|UG(?:\s*\(haftungsbeschr(?:ä|ae)nkt\))?|AG|KGaA|KG|OHG|GbR|"
                     r"e\.\s?K(?:fm|fr)?\.|e\.\s?V\.|PartG(?:\s*mbB)?|SE|Ltd\.?|Limited|Inc\.?|LLC|LLP|Corp\.?|B\.V\.|S\.A\.|S\.A\.S\.|"
                     r"S\.?r\.?l\.?|ApS|AB|Oy)(?![\w])")
RX_NOT_NAME = re.compile(r"amtsgericht|registergericht|handelsregister|\bHR[AB]\b|gesch(?:ä|ae)ftsf(?:ü|ue)hr|vorstand|"
                         r"aufsichtsrat|sitz der|registered|director|\bbank\b|\biban\b|\bbic\b|swift|\bust\b|\bvat\b|steuer|\btax\b|@|www\.|https?:|"
                         r"\bseite\b|\bpage\b|telefon|\btel\b|fax|e-?mail", re.I)
RX_TO = re.compile(r"^\s*(?:an|to|bill(?:ed)?\s+to|invoice\s+to|sold\s+to|ship\s+to|deliver(?:y|ed)?\s+to|rechnung\s+an|"
                   r"rechnungs(?:empf(?:ä|ae)nger|anschrift|adresse)|empf(?:ä|ae)nger|lieferanschrift|lieferadresse|kunde|customer|"
                   r"recipient|buyer|käufer|kaeufer)\b\s*:?", re.I)
RX_ZIP = re.compile(r"(?<!\d)(?:D-|A-|CH-)?\d{4,5}\s+[A-ZÄÖÜ][a-zäöüß]")
RX_STREET = re.compile(r"(?:stra(?:ß|ss)e|str\.|weg|allee|platz|gasse|ring|damm|ufer|chaussee|park|markt|street|st\.|road|rd\.|avenue|ave\.)"
                       r"\s*\d", re.I)
RX_DOC_WORD = re.compile(r"^(?:rechnung|invoice|quittung|receipt|beleg|kassenbon|bon|gutschrift|credit\s+note|angebot|"
                         r"lieferschein|seite|page|datum|date|kopie|copy|original|duplikat)\b", re.I)
RX_VAT_ID = re.compile(r"(?<![A-Z0-9])(DE\s?\d{3}\s?\d{3}\s?\d{3}|ATU\s?\d{8}|(?:BE|NL|FR|IT|ES|LU|DK|PL|CZ|SE|FI|IE|PT|SK|SI|HU|"
                       r"RO|BG|HR|LT|LV|EE|GR|EL|CY|MT|CHE)[-\s]?[0-9A-Z][0-9A-Z.\s]{6,13}[0-9A-Z])(?![A-Z0-9])")
RX_VAT_ID_LABEL = re.compile(r"ust\.?\s*-?\s*id(?:ent)?\.?\s*-?\s*(?:nr|nummer)?|umsatzsteuer-?\s*id|vat\s*(?:id|reg|no|number)|"
                             r"\buid\b|tva|btw|\bp\.?\s?iva", re.I)
RX_TAX_NO = re.compile(r"(?:steuer\s*-?\s*(?:nummer|nr\.?)|st\.?\s*-?\s*nr\.?)\s*[:.]?\s*(\d{2,3}/\d{3,4}/\d{4,5}|\d{10,13})", re.I)
RX_THEIR = re.compile(r"\b(?:ihre|your|kunden?|customer|buyer|empf(?:ä|ae)nger|leistungsempf(?:ä|ae)nger|recipient)\b", re.I)
RX_INV_NO = re.compile(r"(?<![a-zäöü])(?:rechnungs?\s*-?\s*(?:nummer|nr\.?|no\.?)|rg\.?\s*-?\s*nr\.?|re\.?\s*-?\s*nr\.?|"
                       r"rechnung\s+(?:nr\.?|no\.?|nummer|#)|beleg\s*-?\s*(?:nummer|nr\.?)|quittungs?\s*-?\s*(?:nummer|nr\.?|no\.?)|"
                       r"quittung\s+(?:nr\.?|no\.?|#)|bon\s*-?\s*(?:nummer|nr\.?)|invoice\s*(?:no\.?|number|nr\.?|#|id)|"
                       r"receipt\s*(?:no\.?|number|#)|bill\s*(?:no\.?|number|#))\s*[:#.]?\s*", re.I)
RX_INV_VAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/._]{0,30}")
RX_PCT = re.compile(r"(?<![\d,.])(\d{1,2})(?:[.,]0{1,2})?\s*%")
RX_VAT_WORD = re.compile(r"(?<![a-zäöü])(?:mwst|mehrwertsteuer|ust|umsatzsteuer|vat|tax|steuer|tva|btw)(?![a-zäöü])", re.I)
RX_NET_WORD = re.compile(r"(?<![a-zäöü])(?:netto(?:betrag|summe|wert)?|summe\s+netto|gesamt\s+netto|zwischensumme|warenwert|"
                         r"subtotal|sub-total|net\s+amount|net\s+total|total\s+net|amount\s+net|total\s+excl\.?|net)(?![a-zäöü])", re.I)
RX_ZERO = re.compile(r"§\s*19\s*(?:abs\.?\s*1\s*)?ustg|kleinunternehmer|steuerfrei|umsatzsteuerfrei|reverse\s+charge|"
                     r"steuerschuldnerschaft\s+des\s+leistungsempf|innergemeinschaftlich|intra-community|§\s*13b\s*ustg|"
                     r"tax\s+exempt|vat\s+exempt|exempt\s+from\s+vat|ohne\s+(?:mwst|umsatzsteuer|ust)|"
                     r"(?<![\d,.])0\s*%\s*(?:mwst|ust|vat)", re.I)
RX_VAT_SUM = re.compile(r"(?:summe|gesamt|total)\s+(?:mwst|ust|vat|tax|steuer)|(?:mwst|ust|vat|tax)[\s.-]*(?:betrag|gesamt|summe|total)", re.I)


def _cents(v):
    return int(round(float(v) * 100)) if v else None


def _mon(c):
    return f"{c // 100}.{c % 100:02d}" if c is not None and c > 0 else None


def ex_lines(text):
    """The cleaned lines (blank lines kept: they bound the address blocks)."""
    return [ln.strip() for ln in _fold(text or "")[:TEXT_CAP].splitlines()]


def _rx_blocked(lines):
    """Indexes of the lines in the recipient's address block ("An", "Rechnung an", "Bill to" ... up to a blank line, at
    most 6 lines) -- the supplier is never the recipient."""
    out = set()
    for i, ln in enumerate(lines):
        if not RX_TO.match(ln):
            continue
        rest = RX_TO.sub("", ln, count=1).strip()
        if rest:
            out.add(i)
        for j in range(i + 1, min(i + 7, len(lines))):
            if not lines[j]:
                if j > i + 1:
                    break
                continue
            out.add(j)
    return out


def _rx_name(part):
    part = re.sub(r"\s+", " ", part).strip(" ,;:-·|•")
    if not (2 < len(part) <= 80) or RX_NOT_NAME.search(part) or RX_ZIP.search(part) or RX_STREET.search(part):
        return None
    if sum(ch.isdigit() for ch in part) > len(part) // 3 or not re.search(r"[A-Za-zÄÖÜäöüß]{2}", part):
        return None
    return part


def ex_supplier(text):
    """The supplier's company name: a line (or the first part of a return-address line "Muster GmbH · Weg 1 · 12345 Ort")
    with a legal form, looked for in the head (first 20 lines), then in the foot; without one the first sensible line
    before the first address line. Never a line of the recipient's address block. None when nothing fits."""
    lines = ex_lines(text)
    blocked = _rx_blocked(lines)
    head = [(i, ln) for i, ln in enumerate(lines[:20]) if ln and i not in blocked]
    foot = [(i, ln) for i, ln in enumerate(lines) if ln and i >= 20 and i not in blocked][-25:]
    for part_of in (head, foot):
        for _i, ln in part_of:
            for part in re.split(r"\s+[·|•–—/]\s+|\s{3,}|\s+-\s+|,\s+(?=\S)", ln):
                m = RX_FORM.search(part)
                if m:
                    name = _rx_name(part[:m.end()])
                    if name:
                        return name
    cands = []
    for _i, ln in head[:8]:
        if RX_ZIP.search(ln) or RX_STREET.search(ln):
            return cands[0] if cands else None  # the first address: the name stands before it
        if RX_DOC_WORD.search(ln) or RX_TO.match(ln) or find_dates(ln) or find_amounts(ln):
            continue
        name = _rx_name(re.split(r"\s+[·|•–—]\s+", ln)[0])
        if name:
            cands.append(name)
    return None


def ex_vat_id(text):
    """The supplier's VAT id ("DE123456789", "ATU12345678", ...): a labelled one not marked as the customer's ("Ihre
    USt-IdNr."), else the first one. Spaces removed."""
    lines = ex_lines(text)
    blocked = _rx_blocked(lines)
    first = None
    for i, ln in enumerate(lines):
        for m in RX_VAT_ID.finditer(ln):
            v = re.sub(r"[\s.-]", "", m.group(1))
            if len(v) < 9 or not re.search(r"\d{6}", v):
                continue
            pre = ln[:m.start()]
            if i in blocked or RX_THEIR.search(pre[-40:]):
                continue
            if RX_VAT_ID_LABEL.search(pre[-40:]):
                return v
            first = first or v
    return first


def ex_tax_no(text):
    for ln in ex_lines(text):
        m = RX_TAX_NO.search(ln)
        if m and not RX_THEIR.search(ln[:m.start()][-40:]):
            return m.group(1)
    return None


def ex_invoice_no(text):
    """The invoice / receipt number after its label ("Rechnungsnummer", "Rg.-Nr.", "Invoice No.", "Quittung Nr.", the value
    on the same line or alone on the next one); never a date, an IBAN, a customer / order number (other labels)."""
    lines = [ln for ln in ex_lines(text) if ln]
    for i, ln in enumerate(lines):
        for m in RX_INV_NO.finditer(ln):
            rest = ln[m.end():]
            if not re.search(r"\d", rest) and i + 1 < len(lines):
                rest = lines[i + 1]     # a table head ("Rechnungsnummer   Datum"): the value starts the next line
            v = RX_INV_VAL.match(rest.strip())
            if not v:
                continue
            val = v.group(0).rstrip(".-/_")
            if not re.search(r"\d", val) or len(val) < 2 or IBAN_RE.fullmatch(val):
                continue
            if any(s == 0 and e >= len(val) for s, e, _d in find_dates(val)):
                continue                # a date, not a number ("Rechnungsdatum" is no label; this guards "Nr.: 01.10.2026")
            if re.fullmatch(r"(?:kunden|kd|auftrags?|bestell|order|customer)\w*", val, re.I):
                continue
            return val[:40]
    return None


def _rx_amounts(ln):
    """The amounts of a line without its percent figures ("19,00 %" is no amount)."""
    bare = RX_PCT.sub(lambda m: " " * len(m.group(0)), ln)
    for s0, e0, _d in reversed(find_dates(bare)):
        bare = bare[:s0] + " " * (e0 - s0) + bare[e0:]
    return [_cents(v) for v, _cur, dec in find_amounts(bare) if dec or _cur]


def ex_vat(text):
    """{'rates': [{'pct': '19', 'net': '100.00' | None, 'vat': '19.00'}], 'zero': bool, 'vat_sum': cents | None} -- the VAT
    lines with a rate ("zzgl. 19 % MwSt 19,00", "enthaltene MwSt 7 %: 1,40", "19% 100,00 19,00 119,00"); 'zero': the
    document says it charges no VAT (§ 19 UStG, reverse charge, intra-community, tax exempt)."""
    lines = [ln for ln in ex_lines(_clean(text or "")) if ln]
    rates = {}
    vat_sum = None
    for i, ln in enumerate(lines):
        low = ln.lower()
        if not RX_VAT_WORD.search(low) and not (RX_PCT.search(ln) and re.search(r"(?<![a-zäöü])(?:mwst|ust|vat|tax)", " ".join(lines[max(0, i - 3):i]).lower())):
            continue
        pcts = [int(p) for p in RX_PCT.findall(ln)]
        ams = _rx_amounts(ln)
        if not ams and i + 1 < len(lines) and len(ln) < 50:
            ams = _rx_amounts(lines[i + 1])
        if not pcts:
            if RX_VAT_SUM.search(low) and ams:
                vat_sum = ams[-1]
            continue
        p = pcts[0]
        if len(pcts) > 1 or not (0 < p < 30) or not ams:
            continue
        net = vat = None
        for a in ams:                   # a net / VAT pair: vat = net * p / 100 (one cent each way)
            for b in ams:
                if a != b and abs(round(a * p / 100) - b) <= 2:
                    net, vat = a, b
                    break
            if vat:
                break
        if vat is None:
            vat = ams[-1]
            base = next((a for a in ams if a != vat and abs(round(a * p / (100 + p)) - vat) <= 2), None)  # "7 % von 21,40: 1,40"
            if base:
                net = base - vat
        if net is not None and vat > net:
            continue
        r = rates.setdefault(p, {"net": None, "vat": None})
        if r["vat"] is None:
            r.update(net=net, vat=vat)
    return {"rates": [{"pct": str(p), "net": _mon(r["net"]), "vat": _mon(r["vat"])} for p, r in sorted(rates.items(), reverse=True)],
            "zero": bool(RX_ZERO.search(_fold(text or "")[:TEXT_CAP])), "vat_sum": vat_sum}


def ex_net(text):
    """The net total from a "Netto" / "Zwischensumme" / "Subtotal" line (the last such line: a total after the items), cents."""
    lines = [ln for ln in ex_lines(_clean(text or "")) if ln]
    out = None
    for i, ln in enumerate(lines):
        m = RX_NET_WORD.search(ln)
        if not m or (RX_PCT.search(ln) and RX_VAT_WORD.search(ln[:m.start()])):
            continue
        ams = _rx_amounts(ln[m.end():]) or (_rx_amounts(lines[i + 1]) if i + 1 < len(lines) and len(ln) < 40 else [])
        if ams:
            out = ams[0] if RX_VAT_WORD.search(ln[m.end():]) else ams[-1]
    return out


def ex_details(text):
    """2.121.0 A (#2092): {'supplier', 'vat_id', 'tax_no', 'invoice_no', 'vat_pct' ('19' | '7' | '0' | None: the rate with the
    largest base), 'vat_rates' [{pct, net, vat}], 'net', 'vat', 'gross' ('12.34' | None), 'currency'} of an invoice or a
    receipt. Net + VAT must give the gross (the total of doc_amount) within two cents; when they do not, only what is
    sure stays (the gross, the rate). Every key is there (None when not found)."""
    text = text or ""
    a = doc_amount(text) or {}
    gross = _cents(a.get("amount"))
    v = ex_vat(text)
    rates = v["rates"]
    net = ex_net(text)
    vat = sum(_cents(r["vat"]) for r in rates) if rates else v["vat_sum"]
    if rates and len(rates) > 1 and all(r["net"] for r in rates) and net is None:
        net = sum(_cents(r["net"]) for r in rates)
    if len(rates) == 1 and rates[0]["net"] and net is None:
        net = _cents(rates[0]["net"])
    if gross is not None and vat is not None and net is None and vat < gross:
        net = gross - vat               # a receipt with "enthaltene MwSt": the net is what is left
    if gross is None and net is not None and vat is not None:
        gross = net + vat
    if net is not None and vat is not None and gross is not None and abs(net + vat - gross) > 2:
        net = vat = None                # does not add up: only the sure gross
        rates = [{"pct": r["pct"], "net": None, "vat": None} for r in rates]
    if net is not None and vat is None and gross is not None and not rates:
        net = None                      # a net without any VAT figure proves nothing
    pct = None
    if rates:
        def base(r):
            n, t = _cents(r["net"]), _cents(r["vat"])
            return n if n is not None else (t * 100 // int(r["pct"]) if t else 0)
        top = max(rates, key=base)["pct"]
        pct = top if top in ("19", "7") else None
    elif v["zero"]:
        pct = "0"
        if gross is not None:
            net, vat = gross, None
    return {"supplier": ex_supplier(text), "vat_id": ex_vat_id(text), "tax_no": ex_tax_no(text), "invoice_no": ex_invoice_no(text),
            "vat_pct": pct, "vat_rates": rates, "net": _mon(net), "vat": _mon(vat) if vat else ("0.00" if pct == "0" and gross else None),
            "gross": _mon(gross), "currency": a.get("currency")}
