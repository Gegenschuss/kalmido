"""2.444.0 (#3447): reading a credit card statement (PDF) -- one reader per provider's layout, no model, no outside service.

ccr_read(provider, data) -> {day, last4, total (Decimal or None), lines: [{day, booked, merchant, amount (Decimal, + = charged),
orig_amount, orig_currency, kind}], error}. Nothing is stored here and nothing counts before a person confirms the positions
(office/cards.py); a statement that cannot be read gets no lines and the person types them in.

The Mastercard reader works line by line on the text layer, as the German issuers print it: receipt day, booking day
(optional), text, amount with its sign ("12,34-", "-12,34", "12,34 S" / "H", or none). Lines without a day of their own
belong to the position above: the foreign amount ("USD 12,00", "12,00 USD") and the foreign fee ("Auslandseinsatzentgelt
0,19"), which becomes its own position. Which sign means "charged" differs per issuer: S / H are taken as printed, otherwise
the direction that fits the printed total (no total: the larger side). Balances, carried amounts and the payment of the last
statement are no positions. Fees, interest and the foreign fee are kind "fee"; money back is kind "credit"."""
import io
import re
from datetime import date
from decimal import Decimal

from .calc import dec, money

CCR_PAGES_MAX = 60
CCR_LINES_MAX = 2000
CCR_TEXT_MAX = 200
_NUM = r"\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2}"
_DAY = r"\d{2}\.\d{2}\.(?:\d{4}|\d{2})?"
LINE_RE = re.compile(rf"^(?P<d1>{_DAY})\s+(?:(?P<d2>{_DAY})\s+)?(?P<text>\S.*?)\s+(?P<pre>[+-]\s?)?(?:EUR\s+)?(?P<amt>{_NUM})(?:\s*EUR)?(?:\s*(?P<post>[+-]|S|H))?$")
TAIL_RE = re.compile(rf"^(?P<text>\S.*?)\s+(?P<pre>[+-]\s?)?(?:EUR\s+)?(?P<amt>{_NUM})(?:\s*EUR)?(?:\s*(?P<post>[+-]|S|H))?$")
FX_RE = re.compile(rf"\b(?:(?P<c1>[A-Z]{{3}})\s+(?P<a1>{_NUM})|(?P<a2>{_NUM})\s+(?P<c2>[A-Z]{{3}}))\b")
RATE_RE = re.compile(r"\b(?:Kurs|Umrechnungskurs|Wechselkurs)\b.*$", re.I)
SKIP_RE = re.compile(r"^(?:(?:neuer|alter|letzter|bisheriger|vorheriger)\s+)?(?:saldo|kontostand|übertrag|uebertrag|zwischensumme|summe|gesamt|"
                     r"zahlung|ihre zahlung|zahlungseingang|lastschrift|einzug|abbuchung|ausgleich|abrechnung|rechnungsbetrag|abrechnungsbetrag|verfügungsrahmen|kreditrahmen)\b", re.I)
FEE_RE = re.compile(r"auslandseinsatz|auslandsentgelt|fremdw(?:ä|ae)hrung\w*\s*(?:entgelt|geb)|fremdw(?:ä|ae)hrungs(?:entgelt|geb)|jahres(?:entgelt|geb|preis)|"
                    r"karten(?:preis|entgelt|geb)|sollzins|\bzinsen\b|bargeld\w*\s*(?:entgelt|geb)|bargeld(?:entgelt|geb)|\bentgelt\b|geb(?:ü|ue)hr", re.I)
TOTAL_RE = re.compile(rf"(?:neuer saldo|neuer kontostand|rechnungsbetrag|abrechnungsbetrag|gesamtbetrag|einzugsbetrag|lastschriftbetrag|"
                      rf"zu zahlender betrag|wird .{{0,40}}eingezogen|wird .{{0,40}}belastet)\D{{0,40}}(?P<amt>{_NUM})", re.I)
# the amount in front: "wird am 15.11. mit 1.234,56 EUR eingezogen"
TOTAL2_RE = re.compile(rf"(?P<amt>{_NUM})\s*(?:EUR|€)?\s+(?:\S+\s+){{0,6}}(?:eingezogen|belastet)\b", re.I)
HEAD_DAY_RE = re.compile(r"(?:abrechnungsdatum|abrechnung vom|abrechnung per|rechnungsdatum|datum der abrechnung|kartenabrechnung vom|abrechnung)\D{0,20}(\d{2}\.\d{2}\.\d{4})", re.I)
LAST4_RE = re.compile(r"(?:\d{4}|[xX*•]{4})[ -]?(?:\d{2}[xX*•]{2}|[xX*•]{4})[ -]?[xX*•]{4}[ -]?(\d{4})\b")
LAST4_WORD_RE = re.compile(r"karten-?\s?(?:nummer|nr\.?)\D{0,30}(\d{4})\b", re.I)


def _real(y, m, d):
    """'YYYY-MM-DD' of a day that exists, else None (31.02. is no day)."""
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _num(v):
    return dec(v.replace(".", "").replace(",", "."), "0")


def _iso(v):
    """'31.10.2026' -> '2026-10-31' (None when it is no day)."""
    d, m, y = v.split(".")
    return _real(y, m, d) if len(y) == 4 else None


def _day(v, head):
    """A day of a position ('31.10.', '31.10.26', '31.10.2026') -> ISO; without a year the one of the statement: a month
    after the statement's month lies in the year before (December on the January statement)."""
    if not v:
        return None
    d, m, y = v.split(".")
    if len(y) == 4:
        return _real(y, m, d)
    if len(y) == 2:
        return _real(f"20{y}", m, d)
    if not head or not 1 <= int(m) <= 12:
        return None
    return _real(int(head[:4]) - (1 if m > head[5:7] else 0), m, d)


def _signed(m):
    """(raw value, by_letter): the amount of a line with its printed sign; by_letter = S / H say the direction themselves."""
    v = _num(m["amt"])
    post, pre = m["post"], (m["pre"] or "").strip()
    if post in ("S", "H"):
        return (v if post == "S" else -v), True
    return (-v if "-" in (post or "", pre) else v), False


def _fx(text):
    """(text without the foreign amount and the rate, foreign amount or None, its currency)."""
    text = RATE_RE.sub("", text).strip()
    m = None
    for x in FX_RE.finditer(text):
        if (x["c1"] or x["c2"]) != "EUR":
            m = x
    if m is None:
        return text, None, None
    return (text[:m.start()] + text[m.end():]).strip(" ,;·-"), _num(m["a1"] or m["a2"]), m["c1"] or m["c2"]


def ccr_mastercard(text):
    """The text of a Mastercard statement -> see the module's text (error None here; no lines = not readable)."""
    rows = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
    head = next((d for d in (_iso(m.group(1)) for x in rows for m in [HEAD_DAY_RE.search(x)] if m) if d), None)
    total = None
    last4 = None
    lines, cur, letters = [], None, False
    for x in rows:
        if not x:
            continue
        m = TOTAL_RE.search(x) or TOTAL2_RE.search(x)
        if m:
            total = _num(m["amt"])  # the last one printed is the end of the statement
        if last4 is None:
            m = LAST4_RE.search(x) or LAST4_WORD_RE.search(x)
            last4 = m.group(1) if m else None
        m = LINE_RE.match(x)
        if m:
            label = m["text"]
            if SKIP_RE.match(label):
                cur = None
                continue
            day = _day(m["d1"], head)
            if day is None:
                continue
            raw, by = _signed(m)
            letters = letters or by
            merchant, oa, oc = _fx(label)
            cur = {"day": day, "booked": _day(m["d2"], head) if m["d2"] else None, "merchant": merchant[:CCR_TEXT_MAX] or label[:CCR_TEXT_MAX], "raw": raw,
                   "orig_amount": oa, "orig_currency": oc, "fee": bool(FEE_RE.search(label))}
            lines.append(cur)
            if len(lines) >= CCR_LINES_MAX:
                break
            continue
        if cur is None or SKIP_RE.match(x):
            continue
        m = TAIL_RE.match(x)
        if m and FEE_RE.search(m["text"]):  # the foreign fee under its position: a position of its own
            raw, by = _signed(m)
            letters = letters or by
            lines.append({"day": cur["day"], "booked": cur["booked"], "merchant": m["text"][:CCR_TEXT_MAX], "raw": raw, "orig_amount": None, "orig_currency": None, "fee": True})
            continue
        if cur["orig_amount"] is None:
            _t, oa, oc = _fx(x)
            if oa is not None:
                cur["orig_amount"], cur["orig_currency"] = oa, oc
    s = Decimal(1)
    if not letters and lines:
        raw = sum((r["raw"] for r in lines), Decimal(0))
        if total is not None and abs(-raw - total) < abs(raw - total):
            s = Decimal(-1)
        elif total is None and raw < 0:
            s = Decimal(-1)
    out = []
    for r in lines:
        a = money(r["raw"] * s)
        out.append({"day": r["day"], "booked": r["booked"], "merchant": r["merchant"], "amount": a,
                    "orig_amount": money(r["orig_amount"]) if r["orig_amount"] is not None else None, "orig_currency": r["orig_currency"],
                    "kind": "fee" if r["fee"] else "credit" if a < 0 else "purchase"})
    return {"day": head or max((r["day"] for r in out), default=None), "last4": last4, "total": money(total) if total is not None else None,
            "lines": out, "error": None}


CCR_READERS = {"mastercard": ccr_mastercard}  # one more provider: one more layout


def ccr_text(data):
    """The text layer of a PDF ('' when it has none or cannot be opened: a scan, a password)."""
    from pypdf import PdfReader
    try:
        rd = PdfReader(io.BytesIO(data))
        if rd.is_encrypted:
            return ""
        return "\n".join((p.extract_text(extraction_mode="layout") or p.extract_text() or "") for p in rd.pages[:CCR_PAGES_MAX])
    except Exception:  # noqa: BLE001 -- a broken file is "not readable", never a 500
        return ""


def ccr_read(provider, data):
    reader = CCR_READERS.get(provider)
    text = ccr_text(data) if reader else ""
    if not text.strip():
        return {"day": None, "last4": None, "total": None, "lines": [], "error": "unreadable"}
    r = reader(text)
    if not r["lines"]:
        r["error"] = "unreadable"
    return r
