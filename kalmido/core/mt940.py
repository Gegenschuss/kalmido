"""2.299.0 A (#3190): SWIFT MT940 / MT942 statements (the German bank dialects: Sparkasse, Volksbank, Deutsche Bank,
Commerzbank ...) -> the same booking rows as core/csvimport.camt_rows, plus the balances of the statement. Pure functions
(no app, no request): the text is parsed in memory only, nothing is executed or fetched.

  mt_is(text)                    a MT940 / MT942 statement (also inside a {1:..}{4:..-} envelope)
  mt_parse(text, text_max)       -> (rows, balances)
    rows      [{day, amount (signed Decimal), currency, counterpart, purpose, iban, ref, error, pending, status, svc_ref, e2e}]
    balances  [{account, day, amount (signed Decimal), kind open|close}] (:60F: / :60M: and :62F: / :62M: / :64:)

Fields read: :20: (starts a statement), :25: (IBAN, or BLZ/account), :34F: (MT942 currency), :60F/M:, :61: (value date YYMMDD,
optional booking date MMDD with the year change, C / D / RC / RD, amount with comma, key, reference, //bank reference),
:86: (structured with sub-fields ?00 ... ?63 and a freely chosen separator, SEPA tags EREF+ KREF+ MREF+ SVWZ+ ABWA+ IBAN+
in the purpose, or free text), :62F/M:, :64:. Several statements in one file ("-" or an envelope between them); MT942
bookings are pending (shown, never imported, like CAMT.052). A bulk booking is one booking with its purpose."""
import re
from datetime import date
from decimal import Decimal

from .csvimport import CAMT_AMOUNT_MAX, IBAN_RE, REF_NONE, _bad, _money, csv_clean
from .i18n import tr

MT_TAG_RE = re.compile(r"^:(\d\d[A-Z]?):(.*)$")
MT_DETECT_RE = re.compile(r"^:(20|25|28C|60[FM]|61|62[FM]):", re.M)
MT_61_RE = re.compile(r"^(\d{6})(\d{4})?(RC|RD|C|D)([A-Z])?(\d+(?:,\d*)?)([A-Z])?([A-Z0-9]{3})?(.*)$", re.S)
MT_BAL_RE = re.compile(r"^([CD])(\d{6})([A-Z]{3})(\d+(?:,\d*)?)$")
MT_SEPA_RE = re.compile(r"(EREF|KREF|MREF|CRED|DEBT|COAM|OAMT|SVWZ|ABWA|ABWE|IBAN|BIC|PURP|BREF|ISSR|CSID)\+")
MT_ACCT_MAX = 60
MT_BAL_RANK = {"60F": 0, "60M": 1, "62F": 0, "62M": 1, "64": 2}


def mt_is(text):
    return len(MT_DETECT_RE.findall(_lines_text((text or "")[:20000]))) >= 2


def _lines_text(text):
    """Envelope {1:..}{4: dropped, line ends unified, the "@@" some banks use as a line separator turned into one."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("@@", "\n")
    return t


def _day(yymmdd):
    try:
        return date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6]))
    except ValueError:
        return None


def _booking_day(value, mmdd):
    """The booking day (MMDD, no year) in the year closest to the value day: a booking of 30.12. with the value day
    02.01. belongs to the year before, a booking of 02.01. with the value day 30.12. to the year after."""
    if not mmdd:
        return value
    best = None
    for y in (value.year - 1, value.year, value.year + 1):
        try:
            d = date(y, int(mmdd[:2]), int(mmdd[2:4]))
        except ValueError:
            continue
        if best is None or abs((d - value).days) < abs((best - value).days):
            best = d
    return best


def _num(s):
    try:
        a = Decimal(s.replace(",", "."))
    except (ArithmeticError, ValueError):
        return None
    return a if a.is_finite() and 0 <= a <= CAMT_AMOUNT_MAX else None


def _fields(text):
    """-> [(tag, value)] in file order; "-" / an envelope line ends a statement (tag "-"). Continuation lines are
    joined with a newline."""
    out = []
    for raw in _lines_text(text).split("\n"):
        line = raw.rstrip()
        if line.startswith("{") and ("{4:" in line or line.startswith("{1:")):
            out.append(("-", ""))
            line = line.split("{4:", 1)[1] if "{4:" in line else ""
        if line.strip() in ("-", "-}", "}"):
            out.append(("-", ""))
            continue
        if line.endswith("-}"):
            line = line[:-2]
        m = MT_TAG_RE.match(line)
        if m:
            out.append((m.group(1), m.group(2)))
        elif out and line.strip() and out[-1][0] != "-":
            out[-1] = (out[-1][0], out[-1][1] + "\n" + line)
    return out


def _account(v):
    v = re.sub(r"\s+", "", v.split("\n")[0]).upper()
    iban = v.split("/")[0] if IBAN_RE.match(v.split("/")[0]) else ""
    return (iban or v)[:MT_ACCT_MAX]


def _bal(v):
    m = MT_BAL_RE.match(v.split("\n")[0].strip())
    if not m:
        return None
    a, day = _num(m.group(4)), _day(m.group(2))
    if a is None or day is None:
        return None
    return {"day": day.isoformat(), "amount": _money(a if m.group(1) == "C" else -a), "currency": m.group(3)}


def _sub_text(parts, codes):
    return "".join(parts.get(k, "") for k in codes)


def _structured(t):
    """The :86: text -> ({"00": .., "20": ..}, sep) when it is structured (GVC + separator + 2-digit sub-field codes), else
    (None, None). The separator is any non-word character (? in nearly every bank; others in some Deutsche Bank files)."""
    m = re.match(r"^\s*\d{3}([^\w\s])(\d{2})", t) or re.match(r"^\s*(\?)(\d{2})", t)
    if not m:
        return None, None
    sep = m.group(1)
    parts = {}
    for piece in t.split(sep)[1:]:
        if len(piece) >= 2 and piece[:2].isdigit():
            parts[piece[:2]] = parts.get(piece[:2], "") + piece[2:]
    return parts, sep


def _sepa(text):
    """EREF+ ... SVWZ+ ... -> {"EREF": .., "SVWZ": ..} (a value runs to the next tag); {} without tags."""
    ms = list(MT_SEPA_RE.finditer(text))
    out = {}
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        out.setdefault(m.group(1), text[m.end():end].strip())
    return out


def _ref(v):
    v = csv_clean(v, 120)
    return v if v and v.upper() not in REF_NONE and not re.fullmatch(r"0+", v) else None


def _info(v, text_max):
    """The :86: text -> {counterpart, iban, purpose, e2e}."""
    flat = v.replace("\n", "")
    parts, sep = _structured(flat)
    out = {"counterpart": "", "iban": None, "purpose": "", "e2e": None, "text": ""}
    if parts is not None:
        body = _sub_text(parts, [f"{i}" for i in range(20, 30)] + ["60", "61", "62", "63"])
        out["text"] = csv_clean(parts.get("00", ""), 60)
        out["counterpart"] = csv_clean(" ".join(x for x in (parts.get("32", "").strip(), parts.get("33", "").strip()) if x), 200)
        iban = re.sub(r"\s+", "", parts.get("31", "")).upper()
        out["iban"] = iban if IBAN_RE.match(iban) else None
    else:
        body = v.replace("\n", " ")
    tags = _sepa(body)
    if tags:
        out["purpose"] = csv_clean(tags.get("SVWZ") or "", text_max)
        out["e2e"] = _ref(tags.get("EREF", ""))
        if not out["purpose"]:  # no SVWZ+: whatever is not a tag value (e.g. KREF / MREF alone) is no purpose; free text before the first tag is
            out["purpose"] = csv_clean(body[:MT_SEPA_RE.search(body).start()], text_max)
        if not out["counterpart"]:
            out["counterpart"] = csv_clean(tags.get("ABWA") or tags.get("ABWE") or "", 200)
        if not out["iban"]:
            iban = re.sub(r"\s+", "", tags.get("IBAN", "")).upper()
            out["iban"] = iban if IBAN_RE.match(iban) else None
    else:
        out["purpose"] = csv_clean(body, text_max)
    return out


def _entry(v, cur, pending, text_max):
    """One :61: line (+ its supplementary line) -> a row without the :86: part."""
    first, _nl, extra = v.partition("\n")
    row = {"day": None, "amount": None, "currency": cur, "counterpart": "", "purpose": "", "iban": None, "ref": None, "error": None,
           "pending": pending, "status": "PDNG" if pending else "BOOK", "svc_ref": None, "e2e": None}
    m = MT_61_RE.match(first.strip())
    if not m:
        row["error"] = tr("The date cannot be read")
        return row
    value = _day(m.group(1))
    if value is not None:
        row["day"] = _booking_day(value, m.group(2)).isoformat()
    else:
        row["error"] = tr("The date cannot be read")
    a = _num(m.group(5))
    if a is not None and a != 0 and _money(a) != 0:
        credit = m.group(3) in ("C", "RD")  # RC / RD: reversals -- the money goes the other way
        row["amount"] = _money(a if credit else -a)
    if row["error"] is None and row["amount"] is None:
        row["error"] = tr("The amount cannot be read")
    cust, _s, bank = m.group(8).partition("//")
    row["e2e"] = _ref(cust)
    row["svc_ref"] = _ref(bank)
    row["ref"] = row["svc_ref"] or row["e2e"]
    row["_extra"] = csv_clean(extra, text_max)
    return row


def mt_parse(text, text_max=300):
    rows, bals = [], []
    acct, cur, pending, opens, closes = "", "", False, [], []
    last = None

    def flush():
        nonlocal opens, closes
        for kind, items in (("open", opens), ("close", closes)):
            best = {}
            for rank, b in items:
                k = b["day"]
                if k not in best or rank < best[k][0]:
                    best[k] = (rank, b)
            bals.extend({"account": acct, "day": b["day"], "amount": b["amount"], "kind": kind, "currency": b["currency"]}
                        for _r, b in sorted(best.values(), key=lambda x: x[1]["day"]))
        opens, closes = [], []

    for tag, val in _fields(text):
        if tag in ("20", "-"):
            flush()
            acct, cur, pending, last = "", "", False, None
        elif tag == "25":
            acct = _account(val)
        elif tag in ("34F", "34"):  # MT942: the floor limit's currency; a report with it is an intraday one
            pending = True
            cur = cur or val.strip()[:3].upper()
        elif tag in ("60F", "60M", "62F", "62M", "64"):
            b = _bal(val)
            if b:
                cur = cur or b["currency"]
                if tag.startswith("60"):
                    opens.append((MT_BAL_RANK[tag], b))
                else:
                    closes.append((MT_BAL_RANK[tag], b))
            last = None
        elif tag == "61":
            last = _entry(val, cur, pending, text_max)
            rows.append(last)
        elif tag == "86" and last is not None:
            i = _info(val, text_max)
            last["counterpart"], last["iban"] = i["counterpart"], i["iban"]
            last["purpose"] = i["purpose"] or i["text"]
            last["e2e"] = i["e2e"] or last["e2e"]
            last["ref"] = last["svc_ref"] or last["e2e"]
            last = None
    flush()
    for r in rows:
        extra = r.pop("_extra", "")
        r["purpose"] = r["purpose"] or extra
    if not rows:
        raise _bad(tr("The file contains no bookings"))
    return rows, bals
