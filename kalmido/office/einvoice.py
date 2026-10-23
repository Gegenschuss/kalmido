"""2.38.0 (#1021 P5): the e-invoice XML of a finalised invoice / credit note -- UN/CEFACT Cross Industry Invoice (CII D16B)
in the EN 16931 profile (ZUGFeRD 2.x / Factur-X "EN 16931") or the XRechnung 3.0 customisation (CIUS of the German public
sector), built from the print model of office.docs (odoc_render), which for a finalised document is its snapshot only.

ein_build(model, fmt)      -> bytes: the XML from a print model (pure, no database; tests use it with a fixture)
ein_xml(c, oid, did, fmt)  -> bytes: the XML of document did of organisation oid (locked invoice / credit note)
ein_check(xml_bytes)       -> [findings]: the module's own plausibility check without a validator (mandatory BTs, sums)

Amounts are Decimal strings all the way (never float): the totals of the print model carry two-place strings, the line
totals are read as text. Tax categories: S (standard / reduced rate), AE (reverse charge), G (export outside the EU),
E (exempt, small business) by the document's vat_note. A foreign currency (USD) gets BT-5 USD, BT-6 EUR and BT-111 (the
tax in EUR) from totals.tax_eur. A credit note is type 381 with positive amounts and the invoice it cancels in BT-25.
The KoSIT validator (Schematron EN 16931 + XRechnung) and veraPDF run in CI on the files tests/office_einvoice_test.py
writes (tools/einvoice_validate.sh)."""
# Adding a format (#1961): see CONTRIBUTING.md, "Contributing national e-invoice formats".
# A new format is an entry in EIN_FORMATS and EIN_PROFILE, its own branch in ein_build, the key in pdfweb.epdf_format,
# example invoices in tests/office_einvoice_test.py and an official validator run in CI (tools/einvoice_validate.sh).
# It needs a source of the specification (link + version) and a maintainer; formats that submit invoices to an authority
# are agreed in an issue first. No plugins or scripts run on the server: formats ship with Kalmido.
import json
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from xml.etree import ElementTree as ET

try:
    from ..core.i18n import LANGS, N_, tr
    from ..core.errors import BadInput
except ImportError:  # loaded as a single file (tests/office_einvoice_test.py, no package)
    def _ein_langs():  # 2.185.0 C (#2520): the same translation files (the document's words in its language)
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "static", "i18n")
        out = {"en": {}}
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as fh:
                    out[fn[:-5]] = json.load(fh) if fn.endswith(".json") else {}
            except (OSError, ValueError):
                pass
        return out
    LANGS = _ein_langs()

    def N_(s):
        return s

    def tr(key, *a, lg=None):
        v = LANGS.get(lg or "en", {}).get(key)
        s = v if isinstance(v, str) else key[:key.find("|")] if key.find("|") > 0 else key
        return s.format(*a) if a else s

    class BadInput(Exception):
        pass

EIN_FORMATS = ("zugferd", "xrechnung")
EIN_PROFILE = {"zugferd": "urn:cen.eu:en16931:2017",
               "xrechnung": "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"}
EIN_PROCESS = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"  # BT-23
NS = {"rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
      "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
      "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
      "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100"}
Q2 = Decimal("0.01")
UNIT_CODES = {"day": "DAY", "hour": "HUR", "minute": "MIN", "piece": "C62", "flat": "C62", "": "C62"}
COUNTRY_WORDS = {"deutschland": "DE", "germany": "DE", "österreich": "AT", "austria": "AT", "schweiz": "CH", "switzerland": "CH",
                 "frankreich": "FR", "france": "FR", "niederlande": "NL", "netherlands": "NL", "italien": "IT", "italy": "IT",
                 "spanien": "ES", "spain": "ES", "belgien": "BE", "belgium": "BE", "luxemburg": "LU", "luxembourg": "LU",
                 "polen": "PL", "poland": "PL", "dänemark": "DK", "denmark": "DK", "vereinigtes königreich": "GB", "united kingdom": "GB"}
# tax category by the document's VAT note (vat_mode novat); S for taxed documents
VAT_CATEGORY = {"reverse": ("AE", "VATEX-EU-AE"), "abroad": ("G", "VATEX-EU-G"), "small": ("E", "")}
# 2.185.0 C (#2520): English keys through tr() in the document's language (was a de / en table; the words stay the same)
EXEMPT_TEXT = {"reverse": N_("Reverse charge: VAT liability of the recipient.|einvoice"),
               "abroad": N_("Not taxable domestically (export / service outside the EU).|einvoice"),
               "small": N_("No VAT charged under section 19 of the German VAT Act (small business).|einvoice")}
EIN_WORDS = {"project": N_("Project: {0}|einvoice"), "transfer": N_("Credit transfer|einvoice"),
             "refund": N_("The amount will be refunded or offset.|einvoice"), "now": N_("Payable on receipt.|einvoice")}


def ein_lang(v):
    """2.185.0 C (#2520): the language of the texts in the XML (notes, payment terms; codes stay as they are): en / de as
    before, any other app language, else German."""
    s = str(v or "de").strip().lower()
    return "en" if s.startswith("en") else s if s in LANGS else "de"


def _exempt(m, lang):
    return tr(EXEMPT_TEXT.get(m.get("vat_note_key") or "small", EXEMPT_TEXT["small"]), lg=lang)


def _d(v, default="0"):
    try:
        return Decimal(str(v if v not in (None, "") else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _m(v):
    """Money text with two places (half up)."""
    return format(_d(v).quantize(Q2, rounding=ROUND_HALF_UP), "f")


def _qty(v):
    q = _d(v, "1")
    s = format(q.normalize(), "f")
    return s if "." in s or "E" not in s else format(q, "f")


def _pct(v):
    p = _d(v).normalize()
    return format(p, "f") if p == p.to_integral() else _m(p)


def _date8(s):
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(s or "")[:10])
    return "".join(m.groups()) if m else ""


def _country(v, fallback="DE"):
    """2.40.0 (#1372): a code from the ISO list (UK -> GB, EL -> GR); an unknown code is stopped before finalising
    (invoices.inv_missing), a free word is looked up, empty = the fallback."""
    try:
        from .countries import fk_country_code
    except ImportError:  # loaded on its own (tests/office_einvoice_test.py): only the two corrections
        def fk_country_code(x):
            return {"UK": "GB", "EL": "GR"}.get(x.upper(), x.upper())
    s = str(v or "").strip()
    if re.fullmatch(r"[A-Za-z]{2}", s):
        return fk_country_code(s) or fallback  # 2.40.0 (review): an unknown pair of letters is no country
    return COUNTRY_WORDS.get(s.lower(), fallback)


def _e(parent, tag, text=None, **attrs):
    ns, _, name = tag.partition(":")
    el = ET.SubElement(parent, f"{{{NS[ns]}}}{name}", {k: v for k, v in attrs.items() if v not in (None, "")})
    if text is not None:
        el.text = str(text)
    return el


def _date_el(parent, tag, iso, prefix="udt"):
    d8 = _date8(iso)
    if d8:
        _e(_e(parent, tag), f"{prefix}:DateTimeString", d8, format="102")


_ZIP_RE = re.compile(r"^(?:([A-Z]{1,2})\s*-\s*)?(\d{4,5})\s+(\S.*)$")


def fd_split_address(lines):
    """2.40.0 (#1368): free address lines -> street / line2 / line3 / zip / city. The LAST line with a postcode pattern
    ("12345 Town", "1010 Wien", "CH-8000 Zürich") is zip + city, the line before it the street (LineOne), the lines before
    that LineTwo / LineThree. No postcode line found (e.g. UK): the last line is the city, the one before the street."""
    lines = [str(x).strip() for x in (lines or []) if str(x).strip()]
    out = {}
    if not lines:
        return out
    idx = next((i for i in range(len(lines) - 1, -1, -1) if _ZIP_RE.match(lines[i])), None)
    if idx is None:
        idx, zip_, city = len(lines) - 1, "", lines[-1]
    else:
        mm = _ZIP_RE.match(lines[idx])
        zip_, city = mm.group(2), mm.group(3).strip()
        pre = {"D": "DE", "A": "AT", "F": "FR", "B": "BE", "I": "IT", "L": "LU"}.get(mm.group(1) or "", mm.group(1) or "")
        tail = lines[idx + 1:]  # a country line after "zip city" ("Deutschland", "AT")
        cc = _country(tail[-1], "") if tail else ""
        if cc or pre:
            out["country"] = cc or pre
    before = lines[:idx]
    out["zip"], out["city"] = zip_, city
    if before:
        out["street"] = before[-1]
        extra = before[:-1]
        if extra:
            out["line2"] = extra[0]
        if len(extra) > 1:
            out["line3"] = ", ".join(extra[1:])
    return out


def _party(parent, tag, name, fields, lang, home, contact=False, email=None, legal_id=None, person=None):
    """A trade party (seller / buyer) in the schema order: Name, legal organisation, contact, address, URI, tax ids."""
    f = fields or {}
    p = _e(parent, tag)
    _e(p, "ram:Name", name or "")
    if legal_id:
        _e(_e(p, "ram:SpecifiedLegalOrganization"), "ram:ID", legal_id)
    if contact and (f.get("phone") or f.get("email")):  # BG-6 (XRechnung BR-DE-2: the seller contact is mandatory)
        ct = _e(p, "ram:DefinedTradeContact")
        _e(ct, "ram:PersonName", f.get("managing_directors") or name or "")
        if f.get("phone"):
            _e(_e(ct, "ram:TelephoneUniversalCommunication"), "ram:CompleteNumber", f["phone"])
        if f.get("email"):
            _e(_e(ct, "ram:EmailURIUniversalCommunication"), "ram:URIID", f["email"])
    elif person and person.get("name"):  # 2.40.0 (#1380): the buyer's contact person (BG-9, BT-56/57/58) of the document
        ct = _e(p, "ram:DefinedTradeContact")
        _e(ct, "ram:PersonName", person["name"])
        if person.get("phone"):
            _e(_e(ct, "ram:TelephoneUniversalCommunication"), "ram:CompleteNumber", person["phone"])
        if person.get("email"):
            _e(_e(ct, "ram:EmailURIUniversalCommunication"), "ram:URIID", person["email"])
    a = _e(p, "ram:PostalTradeAddress")
    _e(a, "ram:PostcodeCode", f.get("zip") or "")
    _e(a, "ram:LineOne", f.get("street") or "")
    for k, tg in (("line2", "ram:LineTwo"), ("line3", "ram:LineThree")):  # 2.40.0 (#1368): extra free address lines
        if f.get(k):
            _e(a, tg, f[k])
    _e(a, "ram:CityName", f.get("city") or "")
    _e(a, "ram:CountryID", _country(f.get("country"), home))
    if email:
        _e(_e(p, "ram:URIUniversalCommunication"), "ram:URIID", email, schemeID="EM")
    if f.get("tax_number") and tag.startswith("ram:Seller"):
        _e(_e(p, "ram:SpecifiedTaxRegistration"), "ram:ID", f["tax_number"], schemeID="FC")
    if f.get("vat_id"):
        _e(_e(p, "ram:SpecifiedTaxRegistration"), "ram:ID", f["vat_id"], schemeID="VA")
    return p


def ein_build(model, fmt="zugferd"):
    """The CII XML (bytes, UTF-8) from the print model of an invoice / credit note (see the module text for the keys used:
    kind, number, date, lang, currency, order_ref, service_from/to, due_date, sender_fields, recipient, lines, totals,
    cancels, payment, vat_mode, vat_note_key). fmt: zugferd (EN 16931 profile) or xrechnung (BT-10 buyer reference
    mandatory -> BadInput with the reason)."""
    m = model or {}
    fmt = fmt if fmt in EIN_FORMATS else "zugferd"
    lang = ein_lang(m.get("lang"))  # 2.185.0 C (#2520)
    kind = m.get("kind") or "invoice"
    sf = m.get("sender_fields") or {}
    rc = m.get("recipient") or {}
    tot = m.get("totals") or {}
    pay = m.get("payment") or {}
    cur = str(m.get("currency") or "EUR").upper()
    home = _country(sf.get("country"), "DE")
    novat = (m.get("vat_mode") == "novat") or bool(m.get("vat_note_key"))
    cat, excode = VAT_CATEGORY.get(m.get("vat_note_key") or "", ("E", "")) if novat else ("S", "")
    buyer_ref = str(rc.get("buyer_reference") or "").strip()
    if fmt == "xrechnung" and not buyer_ref:
        raise BadInput(tr("XRechnung needs a buyer reference (billing details of the client)."))

    for p, u in NS.items():
        ET.register_namespace(p, u)
    root = ET.Element(f"{{{NS['rsm']}}}CrossIndustryInvoice")
    ctx = _e(root, "rsm:ExchangedDocumentContext")
    _e(_e(ctx, "ram:BusinessProcessSpecifiedDocumentContextParameter"), "ram:ID", EIN_PROCESS)
    _e(_e(ctx, "ram:GuidelineSpecifiedDocumentContextParameter"), "ram:ID", EIN_PROFILE[fmt])
    doc = _e(root, "rsm:ExchangedDocument")
    _e(doc, "ram:ID", m.get("number") or "")
    _e(doc, "ram:TypeCode", "381" if kind == "credit" else (m.get("type_code") or "380"))  # 2.120.0 A (#2087): 326 progress invoice
    _date_el(doc, "ram:IssueDateTime", m.get("date"))
    notes = [str(x) for x in (m.get("vat_note_text") or (tot.get("vat_note") if novat else ""), m.get("project_title") and
             tr(EIN_WORDS["project"], str(m["project_title"]), lg=lang)) if x and str(x).strip()]
    if novat and not m.get("vat_note_text"):
        notes.insert(0, _exempt(m, lang))
    for n in notes[:4]:
        _e(_e(doc, "ram:IncludedNote"), "ram:Content", n)

    tx = _e(root, "rsm:SupplyChainTradeTransaction")
    line_sum = Decimal("0")
    by_rate = {}
    n = 0
    for ln in m.get("lines") or []:
        if not isinstance(ln, dict) or ln.get("kind") not in ("item", "discount", "producing", "surcharge", "raw"):  # 2.113.1 (#2252): + surcharge
            continue
        if ln.get("kind") == "raw" and ln.get("optional"):
            continue
        n += 1
        net = _d(ln.get("net") if ln.get("net") not in (None, "") else ln.get("total")).quantize(Q2, rounding=ROUND_HALF_UP)
        pct = _d(ln.get("tax_pct")) if cat == "S" else Decimal("0")
        qty = _d(ln.get("qty"), "1") if ln.get("qty") not in (None, "") else Decimal("1")
        rate = _d(ln.get("rate")) if ln.get("rate") not in (None, "") else net
        if qty == 0:
            qty, rate = Decimal("1"), net
        if rate < 0:  # BR-27: the net price is never negative; a discount line is a negative quantity
            rate, qty = -rate, -qty
        elif net < 0 and qty > 0:  # 2.38.0 review: inv_calc's discount position (rate and qty positive, net negative)
            qty = -qty
        li = _e(tx, "ram:IncludedSupplyChainTradeLineItem")
        _e(_e(li, "ram:AssociatedDocumentLineDocument"), "ram:LineID", str(ln.get("pos") or n))
        pr = _e(li, "ram:SpecifiedTradeProduct")
        _e(pr, "ram:Name", str(ln.get("title") or "")[:200] or ("Position " + str(n)))
        if ln.get("detail"):
            _e(pr, "ram:Description", str(ln["detail"])[:1000])
        _e(_e(_e(li, "ram:SpecifiedLineTradeAgreement"), "ram:NetPriceProductTradePrice"), "ram:ChargeAmount", _m(rate) if rate == rate.quantize(Q2) else format(rate.quantize(Decimal("0.0001")), "f"))
        _e(_e(li, "ram:SpecifiedLineTradeDelivery"), "ram:BilledQuantity", _qty(qty), unitCode=UNIT_CODES.get(str(ln.get("unit") or ""), "C62"))
        st = _e(li, "ram:SpecifiedLineTradeSettlement")
        t = _e(st, "ram:ApplicableTradeTax")
        _e(t, "ram:TypeCode", "VAT")
        _e(t, "ram:CategoryCode", cat)
        _e(t, "ram:RateApplicablePercent", _pct(pct))
        _e(_e(st, "ram:SpecifiedTradeSettlementLineMonetarySummation"), "ram:LineTotalAmount", _m(net))
        line_sum += net
        by_rate[pct] = by_rate.get(pct, Decimal("0")) + net

    ag = _e(tx, "ram:ApplicableHeaderTradeAgreement")
    if buyer_ref:
        _e(ag, "ram:BuyerReference", buyer_ref)
    _party(ag, "ram:SellerTradeParty", " ".join(str(sf.get("name") or (m.get("company") or {}).get("name") or "").split()), {**sf, "line2": sf.get("address_extra") or ""}, lang, home, contact=True,  # 2.99.0 D (#2188): BT-27 on one line, BT-36
           email=sf.get("email"), legal_id=sf.get("register_no"))
    rfields = {"street": rc.get("street"), "zip": rc.get("zip"), "city": rc.get("city"), "country": rc.get("country"), "vat_id": rc.get("vat_id")}
    if rc.get("extra"):  # 2.97.0 B (#1951): the client's extra address line (BT-51)
        rfields["line2"] = rc["extra"]
    if not rfields["street"] and not rfields["city"]:  # only free address lines (2.40.0 #1368: see fd_split_address)
        lines = [str(x) for x in (rc.get("lines") or []) if str(x).strip() and str(x).strip() not in (str(rc.get("name") or "").strip(), str(rc.get("name_extra") or "").strip())]
        sp = fd_split_address(lines)
        if rfields.get("country"):
            sp.pop("country", None)
        rfields.update(sp)
    bname = " - ".join(x for x in (str(rc.get("name") or "").strip(), str(rc.get("name_extra") or "").strip()) if x)  # 2.99.0 D (#2188): BT-44 + the name addition
    _party(ag, "ram:BuyerTradeParty", bname, rfields, lang, home, email=rc.get("email_invoice"),
           person=rc.get("contact") if isinstance(rc.get("contact"), dict) else None)
    if m.get("order_ref"):
        _e(_e(ag, "ram:BuyerOrderReferencedDocument"), "ram:IssuerAssignedID", m["order_ref"])
    _e(tx, "ram:ApplicableHeaderTradeDelivery")  # BG-13: the period of service stands in BillingSpecifiedPeriod below
    se = _e(tx, "ram:ApplicableHeaderTradeSettlement")
    if cur != "EUR":
        _e(se, "ram:TaxCurrencyCode", "EUR")
    _e(se, "ram:InvoiceCurrencyCode", cur)
    pm = _e(se, "ram:SpecifiedTradeSettlementPaymentMeans")
    iban = str(pay.get("iban") or sf.get("iban") or "").replace(" ", "")
    bic = str(pay.get("bic") or sf.get("bic") or "").replace(" ", "")
    _e(pm, "ram:TypeCode", "58" if iban else "30")
    _e(pm, "ram:Information", "SEPA" if iban else tr(EIN_WORDS["transfer"], lg=lang))
    if iban:
        acc = _e(pm, "ram:PayeePartyCreditorFinancialAccount")
        _e(acc, "ram:IBANID", iban)
        if sf.get("bank_name"):
            _e(acc, "ram:AccountName", sf["bank_name"][:70])
        if bic:
            _e(_e(pm, "ram:PayeeSpecifiedCreditorFinancialInstitution"), "ram:BICID", bic)
    tax_sum = Decimal("0")
    tax_lines = [tl for tl in (tot.get("tax_lines") or []) if isinstance(tl, dict)]
    rates = sorted(by_rate) if by_rate else [Decimal("0")]
    for pct in rates:
        base = by_rate.get(pct, Decimal("0"))
        given = next((tl for tl in tax_lines if _d(tl.get("pct")) == pct), None)
        amount = _d(given.get("amount")).quantize(Q2, rounding=ROUND_HALF_UP) if given else (base * pct / 100).quantize(Q2, rounding=ROUND_HALF_UP)
        if cat != "S":
            amount = Decimal("0")
        t = _e(se, "ram:ApplicableTradeTax")
        _e(t, "ram:CalculatedAmount", _m(amount))
        _e(t, "ram:TypeCode", "VAT")
        if cat != "S":
            _e(t, "ram:ExemptionReason", _exempt(m, lang))
        _e(t, "ram:BasisAmount", _m(base))
        _e(t, "ram:CategoryCode", cat)
        if excode:
            _e(t, "ram:ExemptionReasonCode", excode)
        _e(t, "ram:RateApplicablePercent", _pct(pct))
        tax_sum += amount
    if m.get("service_from") or m.get("service_to"):
        bp = _e(se, "ram:BillingSpecifiedPeriod")
        _date_el(bp, "ram:StartDateTime", m.get("service_from") or m.get("service_to"))
        _date_el(bp, "ram:EndDateTime", m.get("service_to") or m.get("service_from"))
    pt = _e(se, "ram:SpecifiedTradePaymentTerms")
    if pay.get("skonto_bt20"):  # 2.120.0 A (#2087): the XRechnung cash discount line (BT-20), the printed text before it
        first = str(pay.get("text") or "").split("\n")[0][:400]
        _e(pt, "ram:Description", (first + "\n" if first else "") + pay["skonto_bt20"])
    elif pay.get("text"):
        _e(pt, "ram:Description", str(pay["text"])[:500])
    if m.get("due_date"):
        _date_el(pt, "ram:DueDateDateTime", m.get("due_date"))
    elif kind == "credit":  # 2.40.0 (#1368): a credit note is not "payable on receipt"; BR-CO-25 still wants terms
        _e(pt, "ram:Description", tr(EIN_WORDS["refund"], lg=lang))
    elif not pay.get("text"):
        _e(pt, "ram:Description", tr(EIN_WORDS["now"], lg=lang))
    gross = tot.get("gross") if tot.get("gross") not in (None, "") else line_sum + tax_sum
    gross = _d(gross).quantize(Q2, rounding=ROUND_HALF_UP)
    paid = _d(tot.get("paid")).quantize(Q2, rounding=ROUND_HALF_UP) if kind == "invoice" else Decimal("0")
    ms = _e(se, "ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    _e(ms, "ram:LineTotalAmount", _m(line_sum))
    _e(ms, "ram:TaxBasisTotalAmount", _m(line_sum))
    _e(ms, "ram:TaxTotalAmount", _m(tax_sum), currencyID=cur)
    if cur != "EUR":
        _e(ms, "ram:TaxTotalAmount", _m(tot.get("tax_eur") if tot.get("tax_eur") not in (None, "") else tax_sum), currencyID="EUR")
    _e(ms, "ram:GrandTotalAmount", _m(gross))
    _e(ms, "ram:TotalPrepaidAmount", _m(paid))
    _e(ms, "ram:DuePayableAmount", _m(gross - paid))
    cz = m.get("cancels") or {}
    if kind == "credit" and cz.get("number"):
        ir = _e(se, "ram:InvoiceReferencedDocument")
        _e(ir, "ram:IssuerAssignedID", cz["number"])
        if cz.get("date"):
            _date_el(ir, "ram:FormattedIssueDateTime", cz["date"], prefix="qdt")
    ET.indent(root, space=" ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")


def ein_xml(c, oid, did, fmt=None):
    """The XML of the finalised invoice / credit note did of organisation oid (bytes). fmt: the document's einvoice_format
    when empty. 409 (BadInput) for drafts and other kinds."""
    from .docs import odoc_render
    model = odoc_render(c, did, oid)
    if not model.get("locked") or model.get("kind") not in ("invoice", "credit"):
        raise BadInput(tr("The e-invoice XML exists for finalised invoices and credit notes only."))
    return ein_build(model, fmt or model.get("einvoice_format") or "zugferd")


# ---------------------------------------------------------------- the own check (no validator)
def _find(el, path):
    return el.find(path, NS)


def _text(el, path):
    x = _find(el, path) if el is not None else None
    return (x.text or "").strip() if x is not None else ""


def ein_check(xml_bytes):
    """Plausibility findings of an e-invoice XML (list of strings, empty = fine): mandatory business terms present, the
    sums agree (BR-CO-10/13/15/16, BR-CO-17 tax per rate = base x rate rounded half up), lines present, dates well-formed.
    Not a replacement for the Schematron validator (CI), but enough for tests without Java."""
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        return [f"not well-formed: {e}"]
    doc = _find(root, "rsm:ExchangedDocument")
    tx = _find(root, "rsm:SupplyChainTradeTransaction")
    if doc is None or tx is None:
        return ["missing ExchangedDocument / SupplyChainTradeTransaction"]
    req = {"BT-1 number": (doc, "ram:ID"), "BT-3 type": (doc, "ram:TypeCode"), "BT-2 date": (doc, "ram:IssueDateTime/udt:DateTimeString"),
           "BT-24 profile": (root, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID"),
           "BT-27 seller name": (tx, "ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:Name"),
           "BT-40 seller country": (tx, "ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:PostalTradeAddress/ram:CountryID"),
           "BT-44 buyer name": (tx, "ram:ApplicableHeaderTradeAgreement/ram:BuyerTradeParty/ram:Name"),
           "BT-55 buyer country": (tx, "ram:ApplicableHeaderTradeAgreement/ram:BuyerTradeParty/ram:PostalTradeAddress/ram:CountryID"),
           "BT-5 currency": (tx, "ram:ApplicableHeaderTradeSettlement/ram:InvoiceCurrencyCode"),
           "BT-106 line total": (tx, "ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:LineTotalAmount"),
           "BT-109 tax basis": (tx, "ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxBasisTotalAmount"),
           "BT-112 grand total": (tx, "ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:GrandTotalAmount"),
           "BT-115 due": (tx, "ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:DuePayableAmount")}
    for name, (el, path) in req.items():
        if not _text(el, path):
            out.append(f"{name} missing")
    if _text(doc, "ram:TypeCode") not in ("380", "381", "326"):  # 2.120.0 A (#2087): 326 progress invoice
        out.append("BT-3 type must be 380, 381 or 326")
    for d in root.iterfind(".//udt:DateTimeString", NS):
        if not re.fullmatch(r"\d{8}", d.text or "") or d.get("format") != "102":
            out.append(f"date not YYYYMMDD / format 102: {d.text}")
    profile = _text(root, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID")
    seller = _find(tx, "ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty")
    if seller is not None and not seller.findall("ram:SpecifiedTaxRegistration/ram:ID", NS) and not _text(seller, "ram:SpecifiedLegalOrganization/ram:ID"):
        out.append("BT-31/BT-32/BT-30 seller tax or registration id missing")
    if "xrechnung" in profile:
        if not _text(tx, "ram:ApplicableHeaderTradeAgreement/ram:BuyerReference"):
            out.append("BT-10 buyer reference missing (XRechnung)")
        if seller is not None and not (_text(seller, "ram:DefinedTradeContact/ram:PersonName") and
                                       _text(seller, "ram:DefinedTradeContact/ram:TelephoneUniversalCommunication/ram:CompleteNumber") and
                                       _text(seller, "ram:DefinedTradeContact/ram:EmailURIUniversalCommunication/ram:URIID")):
            out.append("BT-41/42/43 seller contact with phone and e-mail missing (XRechnung)")
        if not _text(tx, "ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:URIUniversalCommunication/ram:URIID"):
            out.append("BT-34 seller electronic address missing (XRechnung)")
        if not _text(tx, "ram:ApplicableHeaderTradeAgreement/ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID"):
            out.append("BT-49 buyer electronic address missing (XRechnung)")
    lines = tx.findall("ram:IncludedSupplyChainTradeLineItem", NS)
    if not lines:
        out.append("BG-25 no invoice lines")
    line_sum = Decimal("0")
    by_cat = {}
    for li in lines:
        amt = _text(li, "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount")
        if not re.fullmatch(r"-?\d+\.\d{2}", amt):
            out.append(f"BT-131 line amount not two places: {amt!r}")
            continue
        if _d(_text(li, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount")) < 0:
            out.append("BT-146 net price negative")
        if not _text(li, "ram:SpecifiedTradeProduct/ram:Name"):
            out.append("BT-153 item name missing")
        line_sum += _d(amt)
        key = (_text(li, "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode"),
               _d(_text(li, "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent")))
        by_cat[key] = by_cat.get(key, Decimal("0")) + _d(amt)
    se = _find(tx, "ram:ApplicableHeaderTradeSettlement")
    ms = _find(se, "ram:SpecifiedTradeSettlementHeaderMonetarySummation") if se is not None else None
    if ms is None:
        return out + ["BG-22 totals missing"]
    bt106, bt109, bt112, bt113, bt115 = (_d(_text(ms, p)) for p in ("ram:LineTotalAmount", "ram:TaxBasisTotalAmount", "ram:GrandTotalAmount",
                                                                    "ram:TotalPrepaidAmount", "ram:DuePayableAmount"))
    allow = _d(_text(ms, "ram:AllowanceTotalAmount"))
    charge = _d(_text(ms, "ram:ChargeTotalAmount"))
    cur = _text(se, "ram:InvoiceCurrencyCode")
    taxcur = _text(se, "ram:TaxCurrencyCode")
    tts = ms.findall("ram:TaxTotalAmount", NS)
    bt110 = next((_d(t.text) for t in tts if t.get("currencyID") == cur), None)
    if bt110 is None:
        out.append("BT-110 tax total in the invoice currency missing")
        bt110 = Decimal("0")
    if taxcur and not any(t.get("currencyID") == taxcur for t in tts):
        out.append("BT-111 tax total in the tax currency missing")
    if line_sum != bt106:
        out.append(f"BR-CO-10: sum of lines {line_sum} != BT-106 {bt106}")
    if bt106 - allow + charge != bt109:
        out.append(f"BR-CO-13: BT-109 {bt109} != BT-106 - allowances + charges {bt106 - allow + charge}")
    if bt109 + bt110 != bt112:
        out.append(f"BR-CO-15: BT-112 {bt112} != BT-109 + BT-110 {bt109 + bt110}")
    if bt112 - bt113 != bt115:
        out.append(f"BR-CO-16: BT-115 {bt115} != BT-112 - BT-113 {bt112 - bt113}")
    tax_sum = Decimal("0")
    seen = set()
    for t in se.findall("ram:ApplicableTradeTax", NS):
        cat = _text(t, "ram:CategoryCode")
        pct = _d(_text(t, "ram:RateApplicablePercent"))
        base = _d(_text(t, "ram:BasisAmount"))
        amount = _d(_text(t, "ram:CalculatedAmount"))
        seen.add((cat, pct))
        want = (base * pct / 100).quantize(Q2, rounding=ROUND_HALF_UP)
        if amount != want:
            out.append(f"BR-CO-17: tax {amount} for {cat} {pct} % != {want}")
        if by_cat.get((cat, pct), Decimal("0")) != base:
            out.append(f"BR-S-08: basis {base} for {cat} {pct} % != sum of its lines {by_cat.get((cat, pct), Decimal('0'))}")
        if cat != "S" and not (_text(t, "ram:ExemptionReason") or _text(t, "ram:ExemptionReasonCode")):
            out.append(f"BR-{cat}-10: exemption reason missing")
        tax_sum += amount
    if set(by_cat) - seen:
        out.append(f"tax breakdown lacks {sorted(set(by_cat) - seen)}")
    if tax_sum != bt110:
        out.append(f"BR-CO-14: BT-110 {bt110} != sum of the tax breakdown {tax_sum}")
    if bt115 > 0 and not (_text(se, "ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString") or _text(se, "ram:SpecifiedTradePaymentTerms/ram:Description")):
        out.append("BR-CO-25: due date or payment terms missing")
    if not se.findall("ram:SpecifiedTradeSettlementPaymentMeans", NS):
        out.append("BG-16 payment means missing")
    return out


# ---------------------------------------------------------------- 2.154.0 B (#1960): UBL 2.1 (Peppol BIS Billing 3.0)
# The same print model as OASIS UBL 2.1 Invoice / CreditNote: Peppol BIS Billing 3.0 (the Peppol network), the XRechnung
# 3.0 UBL syntax (German public buyers, also through Peppol) or plain EN 16931. The CII above stays as it is; ein_ubl_build
# repeats its rules (tax category by vat_note, discount lines as a negative quantity, BT-111 for a foreign currency).
# EndpointID (BT-34 / BT-49): the Peppol ids "<scheme>:<id>" when given, else the e-mail (scheme EM).
UBL_PROFILES = {"peppol": "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0",
                "xrechnung": "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0",
                "en16931": "urn:cen.eu:en16931:2017"}
UBL_NS = {"inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
          "cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
          "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
          "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"}


def _u(parent, tag, text=None, **attrs):
    """A UBL element (cac:/cbc:); an empty text is not written (PEPPOL-EN16931-R008: no empty elements)."""
    ns, _, name = tag.partition(":")
    el = ET.SubElement(parent, f"{{{UBL_NS[ns]}}}{name}", {k: v for k, v in attrs.items() if v not in (None, "")})
    if text is not None:
        el.text = str(text)
    return el


def _ut(parent, tag, text, **attrs):
    """_u only when text is not empty."""
    if text is None or not str(text).strip():
        return None
    return _u(parent, tag, str(text).strip(), **attrs)


def _udate(iso):
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})", str(iso or "")[:10])
    return m.group(1) if m else ""


def ein_ubl_endpoint(pid):
    """'<scheme>:<id>' -> (scheme, id) or None."""
    m = re.fullmatch(r"\s*(\d{4}|EM):(\S{1,200})\s*", str(pid or ""))
    return (m.group(1), m.group(2)) if m else None


def _ubl_lines(m, cat):
    """[(line dict, net, pct, qty, price)] like ein_build's loop; price and quantity agree with the net amount
    (PEPPOL-EN16931-R120: net = quantity x price, rounded to cents) -- else the price gets four places, else qty 1."""
    out = []
    n = 0
    for ln in m.get("lines") or []:
        if not isinstance(ln, dict) or ln.get("kind") not in ("item", "discount", "producing", "surcharge", "raw"):
            continue
        if ln.get("kind") == "raw" and ln.get("optional"):
            continue
        n += 1
        net = _d(ln.get("net") if ln.get("net") not in (None, "") else ln.get("total")).quantize(Q2, rounding=ROUND_HALF_UP)
        pct = _d(ln.get("tax_pct")) if cat == "S" else Decimal("0")
        qty = _d(ln.get("qty"), "1") if ln.get("qty") not in (None, "") else Decimal("1")
        rate = _d(ln.get("rate")) if ln.get("rate") not in (None, "") else net
        if qty == 0:
            qty, rate = Decimal("1"), net
        if rate < 0:
            rate, qty = -rate, -qty
        elif net < 0 and qty > 0:
            qty = -qty
        if (qty * rate).quantize(Q2, rounding=ROUND_HALF_UP) != net:
            p4 = (net / qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if qty else net
            if p4 >= 0 and (qty * p4).quantize(Q2, rounding=ROUND_HALF_UP) == net:
                rate = p4
            else:
                qty, rate = (Decimal("-1"), -net) if net < 0 else (Decimal("1"), net)
        out.append((ln, n, net, pct, qty, rate))
    return out


def _ubl_party(parent, tag, name, f, home, endpoint=None, email=None, contact=None, legal_id=None, seller=False):
    """AccountingSupplierParty / AccountingCustomerParty in the UBL order: EndpointID, PostalAddress, PartyTaxScheme,
    PartyLegalEntity, Contact."""
    p = _u(_u(parent, tag), "cac:Party")
    ep = ein_ubl_endpoint(endpoint)
    if ep:
        _u(p, "cbc:EndpointID", ep[1], schemeID=ep[0])
    elif email:
        _u(p, "cbc:EndpointID", email, schemeID="EM")
    a = _u(p, "cac:PostalAddress")
    _ut(a, "cbc:StreetName", f.get("street"))
    _ut(a, "cbc:AdditionalStreetName", f.get("line2"))
    _ut(a, "cbc:CityName", f.get("city"))
    _ut(a, "cbc:PostalZone", f.get("zip"))
    if f.get("line3"):
        _ut(_u(a, "cac:AddressLine"), "cbc:Line", f["line3"])
    _u(_u(a, "cac:Country"), "cbc:IdentificationCode", _country(f.get("country"), home))
    if f.get("vat_id"):
        ts = _u(p, "cac:PartyTaxScheme")
        _u(ts, "cbc:CompanyID", f["vat_id"])
        _u(_u(ts, "cac:TaxScheme"), "cbc:ID", "VAT")
    if seller and f.get("tax_number"):  # BT-32: the seller's tax number (scheme FC, not VAT)
        ts = _u(p, "cac:PartyTaxScheme")
        _u(ts, "cbc:CompanyID", f["tax_number"])
        _u(_u(ts, "cac:TaxScheme"), "cbc:ID", "FC")
    le = _u(p, "cac:PartyLegalEntity")
    _u(le, "cbc:RegistrationName", name or "-")
    _ut(le, "cbc:CompanyID", legal_id)
    if contact and (contact.get("name") or contact.get("phone") or contact.get("email")):
        ct = _u(p, "cac:Contact")
        _ut(ct, "cbc:Name", contact.get("name"))
        _ut(ct, "cbc:Telephone", contact.get("phone"))
        _ut(ct, "cbc:ElectronicMail", contact.get("email"))
    return p


def ein_ubl_build(model, profile="peppol", sender_id="", receiver_id=""):
    """The UBL 2.1 XML (bytes, UTF-8) of an invoice / credit note print model. profile: peppol (Peppol BIS Billing 3.0),
    xrechnung (XRechnung 3.0 UBL: BT-10 mandatory -> BadInput) or en16931. sender_id / receiver_id: Peppol ids
    "<scheme>:<id>" (BT-34 / BT-49); empty = the e-mail addresses (scheme EM)."""
    m = model or {}
    profile = profile if profile in UBL_PROFILES else "peppol"
    lang = ein_lang(m.get("lang"))  # 2.185.0 C (#2520)
    kind = m.get("kind") or "invoice"
    credit = kind == "credit"
    sf = m.get("sender_fields") or {}
    rc = m.get("recipient") or {}
    tot = m.get("totals") or {}
    pay = m.get("payment") or {}
    cur = str(m.get("currency") or "EUR").upper()
    home = _country(sf.get("country"), "DE")
    novat = (m.get("vat_mode") == "novat") or bool(m.get("vat_note_key"))
    cat, excode = VAT_CATEGORY.get(m.get("vat_note_key") or "", ("E", "")) if novat else ("S", "")
    extext = _exempt(m, lang) if cat != "S" else ""
    buyer_ref = str(rc.get("buyer_reference") or "").strip()
    if profile == "xrechnung" and not buyer_ref:
        raise BadInput(tr("XRechnung needs a buyer reference (billing details of the client)."))
    if profile == "peppol" and not buyer_ref and not m.get("order_ref"):
        buyer_ref = str(rc.get("customer_no") or "").strip()  # PEPPOL-EN16931-R003: BT-10 or BT-13; the customer number stands in

    for p, u in (("cac", UBL_NS["cac"]), ("cbc", UBL_NS["cbc"])):
        ET.register_namespace(p, u)
    ET.register_namespace("", UBL_NS["cn" if credit else "inv"])
    root = ET.Element(f"{{{UBL_NS['cn' if credit else 'inv']}}}{'CreditNote' if credit else 'Invoice'}")
    _u(root, "cbc:CustomizationID", UBL_PROFILES[profile])
    _u(root, "cbc:ProfileID", EIN_PROCESS)
    _u(root, "cbc:ID", m.get("number") or "")
    _u(root, "cbc:IssueDate", _udate(m.get("date")))
    if not credit and _udate(m.get("due_date")):
        _u(root, "cbc:DueDate", _udate(m.get("due_date")))
    _u(root, "cbc:CreditNoteTypeCode" if credit else "cbc:InvoiceTypeCode", "381" if credit else (m.get("type_code") or "380"))
    notes = [str(x) for x in (m.get("vat_note_text") or (tot.get("vat_note") if novat else ""), m.get("project_title") and
             tr(EIN_WORDS["project"], str(m["project_title"]), lg=lang)) if x and str(x).strip()]
    if novat and not m.get("vat_note_text"):
        notes.insert(0, extext)
    if notes:  # PEPPOL-EN16931-R002: one note on document level
        _u(root, "cbc:Note", "\n".join(notes[:4]))
    _u(root, "cbc:DocumentCurrencyCode", cur)
    if cur != "EUR":
        _u(root, "cbc:TaxCurrencyCode", "EUR")
    if buyer_ref:
        _u(root, "cbc:BuyerReference", buyer_ref)
    if m.get("service_from") or m.get("service_to"):
        ip = _u(root, "cac:InvoicePeriod")
        _u(ip, "cbc:StartDate", _udate(m.get("service_from") or m.get("service_to")))
        _u(ip, "cbc:EndDate", _udate(m.get("service_to") or m.get("service_from")))
    if m.get("order_ref"):
        _u(_u(root, "cac:OrderReference"), "cbc:ID", m["order_ref"])
    cz = m.get("cancels") or {}
    if credit and cz.get("number"):  # BT-25 / BT-26: the invoice this credit note cancels
        dr = _u(_u(root, "cac:BillingReference"), "cac:InvoiceDocumentReference")
        _u(dr, "cbc:ID", cz["number"])
        _ut(dr, "cbc:IssueDate", _udate(cz.get("date")))

    sname = " ".join(str(sf.get("name") or (m.get("company") or {}).get("name") or "").split())
    _ubl_party(root, "cac:AccountingSupplierParty", sname, {**sf, "line2": sf.get("address_extra") or ""}, home, endpoint=sender_id,
               email=sf.get("email"), legal_id=sf.get("register_no"), seller=True,
               contact={"name": sf.get("managing_directors") or sname, "phone": sf.get("phone"), "email": sf.get("email")}
               if (sf.get("phone") or sf.get("email")) else None)
    rfields = {"street": rc.get("street"), "zip": rc.get("zip"), "city": rc.get("city"), "country": rc.get("country"), "vat_id": rc.get("vat_id")}
    if rc.get("extra"):
        rfields["line2"] = rc["extra"]
    if not rfields["street"] and not rfields["city"]:
        lines = [str(x) for x in (rc.get("lines") or []) if str(x).strip() and str(x).strip() not in (str(rc.get("name") or "").strip(), str(rc.get("name_extra") or "").strip())]
        sp = fd_split_address(lines)
        if rfields.get("country"):
            sp.pop("country", None)
        rfields.update(sp)
    bname = " - ".join(x for x in (str(rc.get("name") or "").strip(), str(rc.get("name_extra") or "").strip()) if x)
    person = rc.get("contact") if isinstance(rc.get("contact"), dict) else None
    _ubl_party(root, "cac:AccountingCustomerParty", bname, rfields, home, endpoint=receiver_id, email=rc.get("email_invoice"), contact=person)

    iban = str(pay.get("iban") or sf.get("iban") or "").replace(" ", "")
    bic = str(pay.get("bic") or sf.get("bic") or "").replace(" ", "")
    pm = _u(root, "cac:PaymentMeans")
    _u(pm, "cbc:PaymentMeansCode", "58" if iban else "30")
    if credit and _udate(m.get("due_date")):
        _u(pm, "cbc:PaymentDueDate", _udate(m.get("due_date")))
    if iban:
        acc = _u(pm, "cac:PayeeFinancialAccount")
        _u(acc, "cbc:ID", iban)
        _ut(acc, "cbc:Name", str(sf.get("bank_name") or "")[:70])
        if bic:
            _u(_u(acc, "cac:FinancialInstitutionBranch"), "cbc:ID", bic)
    if pay.get("skonto_bt20"):
        first = str(pay.get("text") or "").split("\n")[0][:400]
        terms = (first + "\n" if first else "") + pay["skonto_bt20"]
    elif pay.get("text"):
        terms = str(pay["text"])[:500]
    elif credit:
        terms = tr(EIN_WORDS["refund"], lg=lang)
    elif not m.get("due_date"):
        terms = tr(EIN_WORDS["now"], lg=lang)
    else:
        terms = ""
    if terms:
        _u(_u(root, "cac:PaymentTerms"), "cbc:Note", terms)

    lines = _ubl_lines(m, cat)
    line_sum = sum((x[2] for x in lines), Decimal("0"))
    by_rate = {}
    for x in lines:
        by_rate[x[3]] = by_rate.get(x[3], Decimal("0")) + x[2]
    tax_lines = [tl for tl in (tot.get("tax_lines") or []) if isinstance(tl, dict)]
    tt = _u(root, "cac:TaxTotal")
    ta = _u(tt, "cbc:TaxAmount", "0.00", currencyID=cur)
    tax_sum = Decimal("0")
    for pct in (sorted(by_rate) if by_rate else [Decimal("0")]):
        base = by_rate.get(pct, Decimal("0"))
        given = next((tl for tl in tax_lines if _d(tl.get("pct")) == pct), None)
        amount = _d(given.get("amount")).quantize(Q2, rounding=ROUND_HALF_UP) if given else (base * pct / 100).quantize(Q2, rounding=ROUND_HALF_UP)
        if cat != "S":
            amount = Decimal("0")
        st = _u(tt, "cac:TaxSubtotal")
        _u(st, "cbc:TaxableAmount", _m(base), currencyID=cur)
        _u(st, "cbc:TaxAmount", _m(amount), currencyID=cur)
        tc = _u(st, "cac:TaxCategory")
        _u(tc, "cbc:ID", cat)
        _u(tc, "cbc:Percent", _pct(pct))
        if cat != "S":
            _ut(tc, "cbc:TaxExemptionReasonCode", excode)
            _u(tc, "cbc:TaxExemptionReason", extext)
        _u(_u(tc, "cac:TaxScheme"), "cbc:ID", "VAT")
        tax_sum += amount
    ta.text = _m(tax_sum)
    if cur != "EUR":  # BT-111: the tax in EUR, its own TaxTotal without subtotals
        _u(_u(root, "cac:TaxTotal"), "cbc:TaxAmount", _m(tot.get("tax_eur") if tot.get("tax_eur") not in (None, "") else tax_sum), currencyID="EUR")
    gross = tot.get("gross") if tot.get("gross") not in (None, "") else line_sum + tax_sum
    gross = _d(gross).quantize(Q2, rounding=ROUND_HALF_UP)
    paid = _d(tot.get("paid")).quantize(Q2, rounding=ROUND_HALF_UP) if kind == "invoice" else Decimal("0")
    mt = _u(root, "cac:LegalMonetaryTotal")
    _u(mt, "cbc:LineExtensionAmount", _m(line_sum), currencyID=cur)
    _u(mt, "cbc:TaxExclusiveAmount", _m(line_sum), currencyID=cur)
    _u(mt, "cbc:TaxInclusiveAmount", _m(gross), currencyID=cur)
    if paid:
        _u(mt, "cbc:PrepaidAmount", _m(paid), currencyID=cur)
    _u(mt, "cbc:PayableAmount", _m(gross - paid), currencyID=cur)

    for ln, n, net, pct, qty, rate in lines:
        li = _u(root, "cac:CreditNoteLine" if credit else "cac:InvoiceLine")
        _u(li, "cbc:ID", str(ln.get("pos") or n))
        _u(li, "cbc:CreditedQuantity" if credit else "cbc:InvoicedQuantity", _qty(qty), unitCode=UNIT_CODES.get(str(ln.get("unit") or ""), "C62"))
        _u(li, "cbc:LineExtensionAmount", _m(net), currencyID=cur)
        it = _u(li, "cac:Item")
        _ut(it, "cbc:Description", str(ln.get("detail") or "")[:1000])
        _u(it, "cbc:Name", str(ln.get("title") or "")[:200] or ("Position " + str(n)))
        tc = _u(it, "cac:ClassifiedTaxCategory")
        _u(tc, "cbc:ID", cat)
        _u(tc, "cbc:Percent", _pct(pct))
        _u(_u(tc, "cac:TaxScheme"), "cbc:ID", "VAT")
        _u(_u(li, "cac:Price"), "cbc:PriceAmount", _m(rate) if rate == rate.quantize(Q2) else format(rate.quantize(Decimal("0.0001")), "f"), currencyID=cur)
    ET.indent(root, space=" ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")


def ein_ubl_check(xml_bytes):
    """The Peppol points the EN 16931 Schematron does not cover (list of strings, empty = fine): CustomizationID /
    ProfileID of Peppol BIS 3.0, both electronic addresses with a scheme, BT-10 or BT-13, one note, one tax total with
    subtotals, every amount with a currency, no empty element."""
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        return [f"not well-formed: {e}"]
    q = {"cac": UBL_NS["cac"], "cbc": UBL_NS["cbc"]}

    def tx(path):
        x = root.find(path, q)
        return (x.text or "").strip() if x is not None else ""
    if not tx("cbc:CustomizationID").startswith("urn:cen.eu:en16931:2017"):
        out.append("BT-24 CustomizationID")
    if tx("cbc:ProfileID") != EIN_PROCESS:
        out.append("BT-23 ProfileID (PEPPOL-EN16931-R001)")
    for who, path in (("BT-34 seller", "cac:AccountingSupplierParty/cac:Party/cbc:EndpointID"), ("BT-49 buyer", "cac:AccountingCustomerParty/cac:Party/cbc:EndpointID")):
        el = root.find(path, q)
        if el is None or not (el.text or "").strip() or not el.get("schemeID"):
            out.append(f"{who} electronic address with scheme missing (PEPPOL-EN16931-R020 / R010)")
    if not tx("cbc:BuyerReference") and not tx("cac:OrderReference/cbc:ID"):
        out.append("BT-10 buyer reference or BT-13 order reference missing (PEPPOL-EN16931-R003)")
    if len(root.findall("cbc:Note", q)) > 1:
        out.append("more than one note (PEPPOL-EN16931-R002)")
    if len([t for t in root.findall("cac:TaxTotal", q) if t.find("cac:TaxSubtotal", q) is not None]) != 1:
        out.append("exactly one tax total with subtotals (PEPPOL-EN16931-R053)")
    for el in root.iter():
        if len(el) == 0 and not (el.text or "").strip():
            out.append(f"empty element {el.tag.split('}')[-1]} (PEPPOL-EN16931-R008)")
        if el.tag.endswith("Amount") and el.tag.startswith("{" + UBL_NS["cbc"]) and not el.get("currencyID"):
            out.append(f"amount without currency: {el.tag.split('}')[-1]}")
    for ln in root.findall("cac:InvoiceLine", q) + root.findall("cac:CreditNoteLine", q):
        qe = ln.find("cbc:InvoicedQuantity", q)
        qe = qe if qe is not None else ln.find("cbc:CreditedQuantity", q)
        net, price = _d(ln.findtext("cbc:LineExtensionAmount", "", q)), _d(ln.findtext("cac:Price/cbc:PriceAmount", "", q))
        if qe is not None and (_d(qe.text) * price).quantize(Q2, rounding=ROUND_HALF_UP) != net:
            out.append(f"line {ln.findtext('cbc:ID', '', q)}: net != quantity x price (PEPPOL-EN16931-R120)")
    return out
