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


def extract(text, today=None, guess=True):
    """{'date': 'YYYY-MM-DD' | None, 'due': .. | None, 'amount': '12.34' | None, 'currency': 'EUR' | None}. guess False (a
    document that is no invoice / receipt): the due date and amount only from a 'to pay until' line (pay_line)."""
    d = doc_date(text or "", today)
    if guess:
        due = due_date(text or "", d, today)
        a = doc_amount(text or "") or {}
    else:
        due, a = pay_line(text or "", today)
        a = a or {}
    if due and d and due < d:
        due = None
    return {"date": d.isoformat() if d else None, "due": due.isoformat() if due else None,
            "amount": a.get("amount"), "currency": a.get("currency")}


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
