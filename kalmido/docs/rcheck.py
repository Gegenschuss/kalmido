"""2.299.0 D (#3193): the fixed check of a receipt -- required details (section 14 (4) UStG; small amounts up to 250 EUR
section 33 UStDV), the arithmetic (net + VAT = gross per rate and in total, the rate times the net), the allowed rates
(0 / 7 / 19 in Germany; another one = a foreign rate?), the format of a VAT id per EU country (DE with its check digit)
and of a German tax number, the details of an entertainment receipt. Without any agent or language model.

Pure Python (standard library + docs/extract.py, loaded by the unit test without the app). rck_check(fields, text) ->
[{code, level: "hint" | "warn", text, msg, args}]: text is the English sentence, msg / args the source the server
translates (tr(msg, *args)). Nothing here blocks anything: the results are hints a person reads. What the recognition
could only not read (an address, the kind of service) is "Please check: ... not found" (hint), never "Missing";
"Missing" only when the text has not even the label of the detail. fields as docs/extract.py ex_details (supplier,
vat_id, tax_no, invoice_no, vat_pct, vat_rates [{pct, net, vat}], net, vat, gross, currency) + date, amount, sender
(the document's own values) and the flags meal (an entertainment receipt) and einvoice (fields of a structured
e-invoice: no checks of the text)."""
import re

try:
    from . import extract as EX
except ImportError:  # loaded on its own (the unit test)
    import importlib.util
    import os
    _sp = importlib.util.spec_from_file_location("kalmido_rcheck_extract", os.path.join(os.path.dirname(os.path.abspath(__file__)), "extract.py"))
    EX = importlib.util.module_from_spec(_sp)
    _sp.loader.exec_module(EX)

RCK_SMALL = 25000                 # cents: a small amount invoice (section 33 UStDV) up to 250 EUR gross
RCK_RATES = ("0", "7", "19")      # the German VAT rates
RCK_RATE_CENT = 1                 # rate * net may differ from the VAT by one cent (rounding per rate)
RCK_SUM_CENT = 2                  # net + VAT may differ from the gross by two cents (as ex_details)

# the VAT ids of the EU (+ XI Northern Ireland, CHE Switzerland), spaces / dots / dashes removed
RCK_VATID = {
    "AT": r"ATU\d{8}", "BE": r"BE[01]\d{9}", "BG": r"BG\d{9,10}", "CY": r"CY\d{8}[A-Z]", "CZ": r"CZ\d{8,10}", "DE": r"DE\d{9}",
    "DK": r"DK\d{8}", "EE": r"EE\d{9}", "EL": r"EL\d{9}", "ES": r"ES[A-Z0-9]\d{7}[A-Z0-9]", "FI": r"FI\d{8}",
    "FR": r"FR[A-HJ-NP-Z0-9]{2}\d{9}", "HR": r"HR\d{11}", "HU": r"HU\d{8}", "IE": r"IE\d[A-Z0-9+*]\d{5}[A-W][A-I]?",
    "IT": r"IT\d{11}", "LT": r"LT(?:\d{9}|\d{12})", "LU": r"LU\d{8}", "LV": r"LV\d{11}", "MT": r"MT\d{8}",
    "NL": r"NL\d{9}B\d{2}", "PL": r"PL\d{10}", "PT": r"PT\d{9}", "RO": r"RO\d{2,10}", "SE": r"SE\d{10}01", "SI": r"SI\d{8}",
    "SK": r"SK\d{10}", "XI": r"XI(?:\d{9}|\d{12}|GD\d{3}|HA\d{3})", "CHE": r"CHE\d{9}(?:MWST|TVA|IVA)?",
}
RCK_TAXNO_RE = re.compile(r"\d{2,3}/\d{3,4}/\d{4,5}|\d{10,11}|\d{13}")
RCK_TAXNO_LABEL = re.compile(r"steuer\s*-?\s*(?:nummer|nr)|st\.?\s*-?\s*nr", re.I)
RCK_RC = re.compile(r"reverse\s+charge|steuerschuldnerschaft\s+des\s+leistungsempf|§\s*13b", re.I)
RCK_MEAL_OK = (re.compile(r"anlass|occasion", re.I), re.compile(r"teilnehm|bewirtete\s+person|participant|guests?", re.I))
RCK_NOT_SERVICE = re.compile(r"(?<![a-zäöü])(?:summe|gesamt|total|netto|brutto|mwst|mehrwertsteuer|umsatzsteuer|steuer|betrag|zahlung|"
                             r"zahlbar|karte|girocard|mastercard|r(?:ü|ue)ckgeld|gegeben|konto|datum|rechnung|invoice|zwischensumme|"
                             r"subtotal|rabatt|skonto|discount|transaktion|kasse|"
                             r"(?:ust|vat|tax|bar|card|ec|visa|change|iban|bic|date|tse|bon)(?![a-zäöü]))", re.I)
RCK_WORD = re.compile(r"[A-Za-zÄÖÜäöüß]{3,}")



def N_(s):
    """Marks a translation key for tools/i18n_check.py (the app's core.i18n.N_; this file loads without the app)."""
    return s


# code -> (level, English sentence); the server translates the sentence (static/i18n)
RCK_MSG = {
    "supplier": ("hint", N_("Please check: name of the supplier not found")),
    "address": ("hint", N_("Please check: address of the supplier not found")),
    "taxid": ("warn", N_("Missing: tax number or VAT ID of the supplier")),
    "taxid_read": ("hint", N_("Please check: tax number or VAT ID not found")),
    "date": ("warn", N_("Missing: invoice date")),
    "date_read": ("hint", N_("Please check: invoice date not found")),
    "number": ("warn", N_("Missing: invoice number")),
    "number_read": ("hint", N_("Please check: invoice number not found")),
    "service": ("hint", N_("Please check: quantity and kind of the service not found")),
    "rate": ("warn", N_("Missing: VAT rate and VAT amount (or a note on the tax exemption)")),
    "rate_small": ("warn", N_("Missing: VAT rate (or a note on the tax exemption)")),
    "rate_read": ("hint", N_("Please check: VAT rate not found")),
    "net": ("hint", N_("Please check: net amount for {0} % not found")),
    "vat": ("hint", N_("Please check: VAT amount for {0} % not found")),
    "zero_note": ("hint", N_("Please check: 0 % VAT without a note on the exemption (reverse charge, small business, tax free)")),
    "reverse": ("hint", N_("Reverse charge (section 13b UStG): you declare the VAT on this receipt yourself")),
    "rate_foreign": ("hint", N_("Please check: VAT rate {0} % - a foreign rate?")),
    "calc_rate": ("warn", N_("Please check: {0} % of {1} gives {2}, the receipt says {3}")),
    "calc_sum": ("warn", N_("Please check: net {0} + VAT {1} gives {2}, the receipt says {3}")),
    "calc_nets": ("warn", N_("Please check: the net amounts per rate give {0}, the receipt says {1}")),
    "vatid_fmt": ("warn", N_("Please check: the VAT ID {0} does not have the format of {1}")),
    "vatid_digit": ("warn", N_("Please check: the check digit of the VAT ID {0} does not fit")),
    "taxno_fmt": ("hint", N_("Please check: the tax number {0} does not look like a German tax number")),
    "recipient": ("hint", N_("Please check: name and address of the recipient (required above 250 EUR)")),
    "meal": ("hint", N_("Entertainment: note the occasion, the participants and a tip (Office > Entertainment)")),
}


def _c(v):
    """'12.34' / 12.34 / '12,34' -> cents (int) or None."""
    if v in (None, "", [], {}):
        return None
    try:
        return int(round(float(str(v).replace(",", ".")) * 100))
    except (TypeError, ValueError):
        return None


def _m(cents):
    return f"{'-' if cents < 0 else ''}{abs(cents) // 100}.{abs(cents) % 100:02d}"


def _pct(v):
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return str(int(f)) if f == int(f) else str(f)


def rck_de_vatid_ok(v):
    """The check digit of a German VAT id (DE + 9 digits; ISO 7064 MOD 11,10 as the Federal Central Tax Office uses it)."""
    d = re.sub(r"\D", "", v or "")
    if len(d) != 9:
        return False
    p = 10
    for ch in d[:8]:
        s = (int(ch) + p) % 10 or 10
        p = (2 * s) % 11
    chk = 11 - p
    return (0 if chk == 10 else chk) == int(d[8])


def rck_vatid(v):
    """(code, args) of a VAT id that does not fit its country's format (None: fits, or a prefix this list does not know)."""
    v = re.sub(r"[\s.\-]", "", str(v or "")).upper()
    cc = "CHE" if v.startswith("CHE") else v[:2]
    pat = RCK_VATID.get(cc)
    if not pat:
        return None
    if not re.fullmatch(pat, v):
        return "vatid_fmt", [v, cc]
    if cc == "DE" and not rck_de_vatid_ok(v[2:]):
        return "vatid_digit", [v]
    return None


def rck_taxno_ok(v):
    """A German tax number: 10 / 11 digits of a state ("12/345/67890", "123/456/78901") or the 13 digits of the federal
    format; separators other than "/" and spaces are not part of it."""
    return bool(RCK_TAXNO_RE.fullmatch(re.sub(r"\s", "", str(v or ""))))


def _raw(text):
    """The figures of the text before ex_details throws away what does not add up: (net, vat, gross, rates, zero)."""
    v = EX.ex_vat(text)
    rates = v["rates"]
    vat = sum(_c(r["vat"]) or 0 for r in rates) if rates and all(r["vat"] for r in rates) else v["vat_sum"]
    a = EX.doc_amount(text) or {}
    return EX.ex_net(text), vat, _c(a.get("amount")), rates, v["zero"]


def _service(lines):
    """A line naming a service / an article: a word (not a total, VAT or payment word) and an amount or a quantity."""
    for ln in lines:
        if not ln or RCK_NOT_SERVICE.search(ln):
            continue
        if RCK_WORD.search(EX.RX_PCT.sub(" ", ln)) and (EX.find_amounts(ln) or re.search(r"\d+\s*(?:x|stk|st\.|stück|pcs|h|std)\b", ln, re.I)):
            return True
    return False


def rck_check(fields, text=None, today=None):
    """The hints of a receipt (see the module): [{code, level, text, msg, args}], warnings first. today is not used yet
    (the contract of the parts; a later rule on old dates may need it)."""
    f = fields if isinstance(fields, dict) else {}
    out = []

    def add(code, *args):
        if any(x["code"] == code for x in out):
            return
        level, msg = RCK_MSG[code]
        a = [str(x) for x in args]
        out.append({"code": code, "level": level, "text": msg.format(*a) if a else msg, "msg": msg, "args": a})

    einv = bool(f.get("einvoice"))
    text = None if einv else (text or None)
    lines = [ln for ln in EX.ex_lines(text)] if text else []
    raw_net = raw_vat = raw_gross = None
    raw_rates, zero = [], False
    if text:
        raw_net, raw_vat, raw_gross, raw_rates, zero = _raw(text)
    gross = _c(f.get("gross"))
    if gross is None:
        gross = _c(f.get("amount"))
    if gross is None:
        gross = raw_gross
    cur = str(f.get("currency") or "EUR").upper()
    small = gross is not None and 0 < abs(gross) <= RCK_SMALL and cur in ("EUR", "€")
    rates = [r for r in (f.get("vat_rates") or []) if isinstance(r, dict) and _pct(r.get("pct")) is not None] or raw_rates
    pct = _pct(f.get("vat_pct")) if f.get("vat_pct") not in (None, "") else None

    # ---- the arithmetic: per rate (rate * net = VAT, one cent), in total (net + VAT = gross, two cents)
    calc = False
    for r in rates:
        p, n, t = _pct(r.get("pct")), _c(r.get("net")), _c(r.get("vat"))
        if n is not None and t is not None and p is not None:
            want = int(round(n * float(p) / 100 + 1e-9))
            if abs(want - t) > RCK_RATE_CENT:
                add("calc_rate", p, _m(n), _m(want), _m(t))
                calc = True
    net, vat = _c(f.get("net")), _c(f.get("vat"))
    if net is None or vat is None:  # ex_details drops figures that do not add up: the text's own ones show why
        net, vat = (raw_net, raw_vat) if raw_net is not None and raw_vat is not None else (net, vat)
    if net is not None and vat is not None and gross is not None and abs(net + vat - gross) > RCK_SUM_CENT:
        add("calc_sum", _m(net), _m(vat), _m(net + vat), _m(gross))
        calc = True
    nets = [_c(r.get("net")) for r in rates]
    if len(rates) > 1 and all(x is not None for x in nets) and net is not None and abs(sum(nets) - net) > RCK_SUM_CENT:
        add("calc_nets", _m(sum(nets)), _m(net))
        calc = True

    # ---- the rates: allowed in Germany, a 0 % with its reason, reverse charge
    for p in sorted({_pct(r.get("pct")) for r in rates} | ({pct} if pct else set()), key=lambda x: -float(x)):
        if p not in RCK_RATES:
            add("rate_foreign", p)
    if text and RCK_RC.search(EX._fold(text)):
        add("reverse")
    elif text and (pct == "0" or any(_pct(r.get("pct")) == "0" for r in rates)) and not zero:
        add("zero_note")
    if not rates and not pct and not zero and not (text and RCK_RC.search(text)):
        if text and not any(EX.RX_VAT_WORD.search(EX.RX_VAT_ID_LABEL.sub(" ", ln)) or EX.RX_PCT.search(ln) for ln in lines):
            add("rate_small" if small else "rate")
        else:
            add("rate_read")
    elif not small and not calc and not zero:
        one = len(rates) <= 1
        for r in rates:
            p = _pct(r.get("pct"))
            if p == "0":
                continue
            if _c(r.get("net")) is None and not (one and net is not None):
                add("net", p)
            if _c(r.get("vat")) is None and not (one and vat is not None):
                add("vat", p)

    # ---- the required details (section 14 (4) UStG; small amounts: name + address, date, service, gross, rate)
    if not einv:
        if not (f.get("supplier") or f.get("sender")):
            add("supplier")
        if text and not any(EX.RX_ZIP.search(ln) or EX.RX_STREET.search(ln) for ln in lines):
            add("address")
        if not (f.get("date") or (text and EX.find_dates(text))):
            add("date" if text else "date_read")
        if text and not _service(lines):
            add("service")
    if not small and not einv:
        if not (f.get("vat_id") or f.get("tax_no")):
            add("taxid" if text and not (EX.RX_VAT_ID_LABEL.search(text) or RCK_TAXNO_LABEL.search(text)) else "taxid_read")
        if not f.get("invoice_no"):
            add("number" if text and not EX.RX_INV_NO.search(text) else "number_read")
        if text and cur in ("EUR", "€") and gross is not None and gross > RCK_SMALL and not (any(EX.RX_TO.match(ln) for ln in lines) or sum(1 for ln in lines if EX.RX_ZIP.search(ln)) > 1):
            add("recipient")
    if f.get("vat_id"):
        bad = rck_vatid(f["vat_id"])
        if bad:
            add(bad[0], *bad[1])
    if f.get("tax_no") and not rck_taxno_ok(f["tax_no"]):
        add("taxno_fmt", f["tax_no"])

    # ---- an entertainment receipt: occasion and participants (the office's own receipt, office/meals.py, asks for them)
    if f.get("meal") and not (text and all(r.search(text) for r in RCK_MEAL_OK)):
        add("meal")
    return sorted(out, key=lambda x: x["level"] != "warn")
