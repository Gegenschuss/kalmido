"""2.146.0 A (#2451): incoming e-invoices -- XRechnung / EN 16931 as UBL (Invoice, CreditNote) or UN/CEFACT CII
(CrossIndustryInvoice, also the older ZUGFeRD 1 CrossIndustryDocument), on their own (.xml) or embedded in a PDF
(ZUGFeRD / Factur-X: PDF/A-3 attachment factur-x.xml, zugferd-invoice.xml, ZUGFeRD-invoice.xml, xrechnung.xml).

ei_is(data)                    -> True when the bytes look like an e-invoice XML (root element and namespace; cheap)
ei_parse(data)                 -> dict of the invoice (see _empty) or raises EinvoiceError (not readable / not an e-invoice)
ei_from_pdf(data, owner)       -> the embedded XML of a PDF (bytes) or None; pypdf in its own limited process like
                                  tasks/attachtext.py pdf_text (a hostile PDF only kills that process)
ei_of_file(name, mime, data)   -> the parsed invoice of a document's file or None (the recognition run, docs/store.py)
ei_details(inv)                -> the receipt suggestion keys of receipts/extracted.py (supplier, vat_id, ..., gross)
ei_text(inv)                   -> readable text of the invoice (the document's text and search index)
ei_html(inv)                   -> the readable view (HTML, every value escaped, no script)
ei_amount(inv)                 -> 2.153.0 (#2055): the document amount (a credit note negative)
ei_receipt(c, node, ws, inv, vat) -> 2.153.0 (#2055): in an office's documents space a receipt (not an own invoice; once)

Safety: at most XML_MAX bytes; a DOCTYPE or an ENTITY is refused before parsing (like core/csvimport.py camt_rows: no
entity expansion, no external references, no new dependency); the parse runs as a pull parser that stops beyond
DEPTH_MAX levels or ELEMENTS_MAX elements; amounts are Decimal (never float) and at most AMOUNT_MAX; texts are cleaned
of control characters and cut to TEXT_MAX; at most LINES_MAX invoice lines are kept."""
import base64
import html
import json
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from xml.etree import ElementTree as ET

try:
    from ..core.i18n import N_, tr
except ImportError:  # loaded as a single file (tests, no package)
    def tr(key, *a, lg=None):
        return key.format(*a) if a else key

    def N_(s):
        return s

XML_MAX = 5 * 1024 * 1024        # bytes of one e-invoice XML (alone or embedded)
DEPTH_MAX = 40                   # element levels (an EN 16931 invoice needs about 8)
ELEMENTS_MAX = 50_000            # elements of one document
LINES_MAX = 500                  # invoice lines kept for the readable view
TEXT_MAX = 300                   # characters of one text value
NOTE_MAX = 2000                  # characters of the notes
AMOUNT_MAX = Decimal("10000000000")
PDF_NAMES = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml")  # compared in lower case (also ZUGFeRD-invoice.xml)
Q2 = Decimal("0.01")
UBL_NS = ("urn:oasis:names:specification:ubl:schema:xsd:Invoice-2", "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2")
CII_NS = ("urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100", "urn:ferd:CrossIndustryDocument:invoice:1p0")
CREDIT_TYPES = {"381", "396", "532"}  # UNTDID 1001: credit note (factored), forwarder's credit note
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
_NUM = re.compile(r"^\s*([+-]?\d{1,15}(?:\.\d{1,8})?)\s*$")
_ROOT = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?(Invoice|CreditNote|CrossIndustryInvoice|CrossIndustryDocument)[\s>/]")


class EinvoiceError(ValueError):
    pass


# ---- reading the XML ------------------------------------------------------------------------------------------------------
def _decode(data):
    """Text of the XML bytes (BOM, the declared encoding, else UTF-8 with a cp1252 fallback)."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    m = re.match(rb"\s*<\?xml[^>]*encoding\s*=\s*[\"']([A-Za-z0-9._-]{1,40})[\"']", data[:200])
    for enc in ([m.group(1).decode("ascii")] if m else []) + ["utf-8", "cp1252"]:
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("latin-1")


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _ns(tag):
    return tag[1:].split("}", 1)[0] if isinstance(tag, str) and tag.startswith("{") else ""


def _tree(data):
    """The root element of an e-invoice XML (bytes) with the limits of the module docstring."""
    if not isinstance(data, (bytes, bytearray)):
        raise EinvoiceError(tr("The file is not an e-invoice"))
    if len(data) > XML_MAX:
        raise EinvoiceError(tr("The e-invoice is larger than {0} MB and is not read", XML_MAX // (1024 * 1024)))
    if not data.strip():
        raise EinvoiceError(tr("The file is not an e-invoice"))
    text = _decode(bytes(data))
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.I):
        raise EinvoiceError(tr("The file contains a DOCTYPE or an ENTITY and is not read"))
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text.lstrip("﻿"))
    p = ET.XMLPullParser(events=("start", "end"))
    depth = count = 0
    root = None
    try:
        raw = text.encode("utf-8")
        for i in range(0, len(raw), 65536):
            p.feed(raw[i:i + 65536])
            for ev, el in p.read_events():
                if ev == "start":
                    depth += 1
                    count += 1
                    if root is None:
                        root = el
                    if depth > DEPTH_MAX or count > ELEMENTS_MAX:
                        raise EinvoiceError(tr("The e-invoice is too large or too deeply nested and is not read"))
                else:
                    depth -= 1
        p.close()
    except ET.ParseError:
        raise EinvoiceError(tr("The e-invoice cannot be read (broken XML)")) from None
    if root is None:
        raise EinvoiceError(tr("The file is not an e-invoice"))
    return root


def _kid(el, *path):
    """The first descendant along path (local names, any namespace); None when one step is missing."""
    for name in path:
        if el is None:
            return None
        el = next((k for k in el if _local(k.tag) == name), None)
    return el


def _alt(el, *names):
    """The first child with one of the local names (an Element without children is falsy: never chain with "or")."""
    for name in names:
        k = _kid(el, name)
        if k is not None:
            return k
    return None


def _kids(el, name):
    return [k for k in el if _local(k.tag) == name] if el is not None else []


def _clean(s, n=TEXT_MAX):
    s = _CTRL.sub("", " ".join(str(s or "").split()))
    return s[:n]


def _txt(el, *path, n=TEXT_MAX):
    e = _kid(el, *path) if path else el
    return _clean(e.text if e is not None else "", n)


def _amt(el, *path):
    """Decimal of an amount element (None when missing, unreadable or beyond AMOUNT_MAX)."""
    e = _kid(el, *path) if path else el
    m = _NUM.match((e.text or "") if e is not None else "")
    if not m:
        return None
    try:
        v = Decimal(m.group(1))
    except InvalidOperation:
        return None
    return v if v.is_finite() and abs(v) <= AMOUNT_MAX else None


def _money(v):
    return format(v.quantize(Q2, rounding=ROUND_HALF_UP), "f") if v is not None else None


def _pct(v):
    if v is None:
        return None
    return format(v.quantize(Q2).normalize(), "f")


def _qty(v):
    return format(v.normalize(), "f") if v is not None else None


def _day(s):
    """ISO day of 2026-10-20, 20261020 (CII format 102) or 2026-10-20T..; None otherwise."""
    s = str(s or "").strip()
    m = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})(?:[T ].*)?", s[:40])
    if not m or not ("01" <= m.group(2) <= "12" and "01" <= m.group(3) <= "31"):
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _empty(fmt):
    return {"format": fmt, "kind": "invoice", "number": None, "date": None, "due": None, "currency": None,
            "seller": {}, "buyer": {}, "iban": None, "bic": None, "payment_ref": None, "terms": None,
            "net": None, "vat": None, "gross": None, "payable": None, "vat_rates": [], "lines": [], "note": None}


def _party_clean(p):
    return {k: v for k, v in p.items() if v}


def ei_is(data):
    """Cheap test of the first bytes: the root element of an e-invoice (UBL Invoice / CreditNote, CII)."""
    if not isinstance(data, (bytes, bytearray)):
        return False
    head = bytes(data[:4096])
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            head = head.decode("utf-16", "ignore").encode("utf-8")
        except (UnicodeError, ValueError):
            return False
    head = re.sub(rb"<\?[^>]*\?>|<!--.*?-->", b"", head, flags=re.S)
    m = _ROOT.search(head)
    if not m or head[:m.start()].strip(b" \t\r\n\xef\xbb\xbf"):
        return False
    return any(ns.encode() in head for ns in UBL_NS + CII_NS)


def ei_parse(data):
    """The invoice of an e-invoice XML (bytes); raises EinvoiceError."""
    root = _tree(data)
    name, ns = _local(root.tag), _ns(root.tag)
    if name in ("Invoice", "CreditNote") and ns in UBL_NS:
        inv = _ubl(root, name)
    elif name in ("CrossIndustryInvoice", "CrossIndustryDocument") and ns in CII_NS:
        inv = _cii(root)
    else:
        raise EinvoiceError(tr("The file is not an e-invoice"))
    if not (inv["number"] or inv["gross"] or inv["seller"].get("name")):
        raise EinvoiceError(tr("The e-invoice contains neither a number nor an amount"))
    return inv


# ---- UBL (OASIS UBL 2.1, XRechnung UBL syntax) ----------------------------------------------------------------------------
def _ubl_party(p):
    if p is None:
        return {}
    party = _kid(p, "Party")
    if party is None:
        return {}
    vat = tax = ""
    for ts in _kids(party, "PartyTaxScheme"):
        cid, scheme = _txt(ts, "CompanyID", n=40), _txt(ts, "TaxScheme", "ID", n=10).upper()
        if scheme == "VAT" and not vat:
            vat = cid
        elif cid and not tax:
            tax = cid
    a = _kid(party, "PostalAddress")
    addr = [_txt(a, "StreetName"), _txt(a, "AdditionalStreetName"),
            " ".join(x for x in (_txt(a, "PostalZone", n=20), _txt(a, "CityName")) if x), _txt(a, "Country", "IdentificationCode", n=3)]
    return _party_clean({"name": _txt(party, "PartyLegalEntity", "RegistrationName") or _txt(party, "PartyName", "Name"),
                         "vat_id": vat.replace(" ", ""), "tax_no": tax, "address": [x for x in addr if x],
                         "email": _txt(party, "Contact", "ElectronicMail", n=120) or _txt(party, "EndpointID", n=120)})


def _ubl(root, name):
    inv = _empty("ubl")
    inv["kind"] = "credit_note" if name == "CreditNote" else "invoice"
    inv["number"] = _txt(root, "ID", n=80) or None
    inv["date"] = _day(_txt(root, "IssueDate", n=40))
    pm = _kid(root, "PaymentMeans")
    inv["due"] = _day(_txt(root, "DueDate", n=40)) or _day(_txt(pm, "PaymentDueDate", n=40))
    inv["currency"] = _txt(root, "DocumentCurrencyCode", n=3).upper() or None
    inv["seller"] = _ubl_party(_kid(root, "AccountingSupplierParty"))
    inv["buyer"] = _ubl_party(_kid(root, "AccountingCustomerParty"))
    for pm in _kids(root, "PaymentMeans"):
        acc = _kid(pm, "PayeeFinancialAccount")
        if acc is not None and not inv["iban"]:
            inv["iban"] = _txt(acc, "ID", n=40).replace(" ", "") or None
            inv["bic"] = _txt(acc, "FinancialInstitutionBranch", "ID", n=20) or None
        inv["payment_ref"] = inv["payment_ref"] or _txt(pm, "PaymentID", n=140) or None
    inv["terms"] = _txt(root, "PaymentTerms", "Note") or None
    tot = _kid(root, "LegalMonetaryTotal")
    net, gross, payable = _amt(tot, "TaxExclusiveAmount"), _amt(tot, "TaxInclusiveAmount"), _amt(tot, "PayableAmount")
    vat, rates = None, []
    for tt in _kids(root, "TaxTotal"):
        ta = _kid(tt, "TaxAmount")
        if ta is not None and (ta.get("currencyID") or inv["currency"] or "").upper() not in ((inv["currency"] or "").upper(), ""):
            continue  # BT-111: the tax in the accounting currency
        vat = _amt(ta) if vat is None else vat
        for sub in _kids(tt, "TaxSubtotal"):
            rates.append({"pct": _pct(_amt(sub, "TaxCategory", "Percent")) or "0", "net": _money(_amt(sub, "TaxableAmount")),
                          "vat": _money(_amt(sub, "TaxAmount")), "category": _txt(sub, "TaxCategory", "ID", n=4) or None})
    inv.update(net=_money(net), vat=_money(vat), gross=_money(gross), payable=_money(payable), vat_rates=rates[:20])
    lines = _kids(root, "CreditNoteLine" if name == "CreditNote" else "InvoiceLine")
    for ln in lines[:LINES_MAX]:
        q = _kid(ln, "CreditedQuantity" if name == "CreditNote" else "InvoicedQuantity")
        inv["lines"].append({"name": _txt(ln, "Item", "Name") or _txt(ln, "Item", "Description"),
                             "qty": _qty(_amt(q)), "unit": _clean(q.get("unitCode") if q is not None else "", 6),
                             "price": _money(_amt(ln, "Price", "PriceAmount")), "net": _money(_amt(ln, "LineExtensionAmount")),
                             "pct": _pct(_amt(ln, "Item", "ClassifiedTaxCategory", "Percent"))})
    inv["lines_more"] = max(0, len(lines) - LINES_MAX)
    inv["note"] = _clean(" ".join(_txt(n, n=NOTE_MAX) for n in _kids(root, "Note")), NOTE_MAX) or None
    return inv


# ---- CII (UN/CEFACT D16B, ZUGFeRD 2 / Factur-X / XRechnung CII; ZUGFeRD 1 by its older element names) ---------------------
def _cii_party(p):
    if p is None:
        return {}
    vat = tax = ""
    for reg in _kids(p, "SpecifiedTaxRegistration"):
        e = _kid(reg, "ID")
        scheme = (e.get("schemeID") or "").upper() if e is not None else ""
        if scheme == "VA" and not vat:
            vat = _txt(e, n=40)
        elif scheme == "FC" and not tax:
            tax = _txt(e, n=40)
    a = _kid(p, "PostalTradeAddress")
    addr = [_txt(a, "LineOne"), _txt(a, "LineTwo"), " ".join(x for x in (_txt(a, "PostcodeCode", n=20), _txt(a, "CityName")) if x),
            _txt(a, "CountryID", n=3)]
    return _party_clean({"name": _txt(p, "Name"), "vat_id": vat.replace(" ", ""), "tax_no": tax, "address": [x for x in addr if x],
                         "email": _txt(p, "URIUniversalCommunication", "URIID", n=120)
                         or _txt(p, "DefinedTradeContact", "EmailURIUniversalCommunication", "URIID", n=120)})


def _cii(root):
    inv = _empty("cii")
    doc = _alt(root, "ExchangedDocument", "HeaderExchangedDocument")
    tx = _alt(root, "SupplyChainTradeTransaction", "SpecifiedSupplyChainTradeTransaction")
    if doc is None or tx is None:
        raise EinvoiceError(tr("The file is not an e-invoice"))
    inv["number"] = _txt(doc, "ID", n=80) or None
    inv["kind"] = "credit_note" if _txt(doc, "TypeCode", n=4) in CREDIT_TYPES else "invoice"
    inv["date"] = _day(_txt(doc, "IssueDateTime", "DateTimeString", n=40))
    inv["note"] = _clean(" ".join(_txt(n, "Content", n=NOTE_MAX) for n in _kids(doc, "IncludedNote")), NOTE_MAX) or None
    ag = _alt(tx, "ApplicableHeaderTradeAgreement", "ApplicableSupplyChainTradeAgreement")
    st = _alt(tx, "ApplicableHeaderTradeSettlement", "ApplicableSupplyChainTradeSettlement")
    inv["seller"] = _cii_party(_kid(ag, "SellerTradeParty"))
    inv["buyer"] = _cii_party(_kid(ag, "BuyerTradeParty"))
    if st is not None:
        inv["currency"] = _txt(st, "InvoiceCurrencyCode", n=3).upper() or None
        inv["payment_ref"] = _txt(st, "PaymentReference", n=140) or None
        for pm in _kids(st, "SpecifiedTradeSettlementPaymentMeans"):
            acc = _kid(pm, "PayeePartyCreditorFinancialAccount")
            if acc is not None and not inv["iban"]:
                inv["iban"] = _txt(acc, "IBANID", n=40).replace(" ", "") or None
                inv["bic"] = _txt(pm, "PayeeSpecifiedCreditorFinancialInstitution", "BICID", n=20) or None
        for t in _kids(st, "SpecifiedTradePaymentTerms"):
            inv["due"] = inv["due"] or _day(_txt(t, "DueDateDateTime", "DateTimeString", n=40))
            inv["terms"] = inv["terms"] or _txt(t, "Description") or None
        for t in _kids(st, "ApplicableTradeTax"):
            inv["vat_rates"].append({"pct": _pct(_amt(_alt(t, "RateApplicablePercent", "ApplicablePercent"))) or "0",
                                     "net": _money(_amt(t, "BasisAmount")), "vat": _money(_amt(t, "CalculatedAmount")),
                                     "category": _txt(t, "CategoryCode", n=4) or None})
        inv["vat_rates"] = inv["vat_rates"][:20]
        ms = _alt(st, "SpecifiedTradeSettlementHeaderMonetarySummation", "SpecifiedTradeSettlementMonetarySummation")
        if ms is not None:
            vat = None
            for ta in _kids(ms, "TaxTotalAmount"):
                if (ta.get("currencyID") or "").upper() in ("", (inv["currency"] or "").upper()):
                    vat = _amt(ta)
                    break
            inv.update(net=_money(_amt(ms, "TaxBasisTotalAmount")), vat=_money(vat), gross=_money(_amt(ms, "GrandTotalAmount")),
                       payable=_money(_amt(ms, "DuePayableAmount")))
    lines = _kids(tx, "IncludedSupplyChainTradeLineItem")
    for ln in lines[:LINES_MAX]:
        q = _kid(_alt(ln, "SpecifiedLineTradeDelivery", "SpecifiedSupplyChainTradeDelivery"), "BilledQuantity")
        lst = _alt(ln, "SpecifiedLineTradeSettlement", "SpecifiedSupplyChainTradeSettlement")
        lag = _alt(ln, "SpecifiedLineTradeAgreement", "SpecifiedSupplyChainTradeAgreement")
        inv["lines"].append({"name": _txt(ln, "SpecifiedTradeProduct", "Name"), "qty": _qty(_amt(q)),
                             "unit": _clean(q.get("unitCode") if q is not None else "", 6),
                             "price": _money(_amt(lag, "NetPriceProductTradePrice", "ChargeAmount")),
                             "net": _money(_amt(lst, "SpecifiedTradeSettlementLineMonetarySummation", "LineTotalAmount")),
                             "pct": _pct(_amt(lst, "ApplicableTradeTax", "RateApplicablePercent"))})
    inv["lines_more"] = max(0, len(lines) - LINES_MAX)
    return inv


# ---- the XML inside a PDF (ZUGFeRD / Factur-X) ----------------------------------------------------------------------------
PDF_WORKER = r"""
import base64, io, json, resource, sys
def lim(k, v):
    try:
        resource.setrlimit(k, (v, v))
    except (ValueError, OSError):
        pass
MEM, CPU, CAP = (int(x) for x in sys.argv[1:4])
NAMES = json.loads(sys.argv[4])
lim(resource.RLIMIT_AS, MEM)
lim(resource.RLIMIT_CPU, CPU)
lim(resource.RLIMIT_FSIZE, 0)
lim(resource.RLIMIT_CORE, 0)
if hasattr(resource, "RLIMIT_NPROC"):
    lim(resource.RLIMIT_NPROC, 0)
data = sys.stdin.buffer.read()
import logging, warnings
logging.disable(logging.CRITICAL)
warnings.simplefilter("ignore")
from pypdf import PdfReader
out = None
try:
    r = PdfReader(io.BytesIO(data))
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:
            pass
    att = r.attachments
    names = list(att.keys())[:50]
    pick = [n for want in NAMES for n in names if str(n).lower() == want]
    if not pick:
        xs = [n for n in names if str(n).lower().endswith(".xml")]
        pick = xs[:1] if len(xs) == 1 else []
    if pick:
        blobs = att[pick[0]]
        b = blobs[0] if blobs else b""
        if 0 < len(b) <= CAP:
            out = {"name": str(pick[0])[:100], "xml": base64.b64encode(b).decode("ascii")}
except Exception:
    out = None
print(json.dumps(out))
"""


def ei_from_pdf(data, owner=None):
    """The e-invoice XML embedded in a PDF (bytes) or None. Only PDFs that carry an embedded file are opened."""
    if not data or not bytes(data[:1024]).lstrip().startswith(b"%PDF") or b"/EmbeddedFile" not in data:
        return None
    from ..tasks.attachtext import PDF_MEM, PDF_SECONDS, PDF_WAIT, _SEM
    if not _SEM.acquire(timeout=PDF_WAIT * 5):
        return None
    try:
        p = subprocess.run([sys.executable, "-I", "-c", PDF_WORKER, str(PDF_MEM), str(PDF_SECONDS), str(XML_MAX), json.dumps(PDF_NAMES)],
                           input=bytes(data), capture_output=True, timeout=PDF_SECONDS, close_fds=True,
                           env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        out = json.loads(p.stdout.decode("utf-8", "replace") or "null") if p.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError, ValueError):
        out = None
    finally:
        _SEM.release()
    if not isinstance(out, dict) or not isinstance(out.get("xml"), str):
        return None
    try:
        xml = base64.b64decode(out["xml"], validate=True)
    except ValueError:
        return None
    return xml if len(xml) <= XML_MAX else None


def ei_of_file(name, mime, data, owner=None):
    """The parsed e-invoice of a document's file (an e-invoice XML, or a PDF with one embedded) or None. A broken or refused
    XML is no e-invoice here (the file stays an ordinary document); its reason is logged without content."""
    head = bytes(data[:1024]) if data else b""
    src = None
    if head.lstrip().startswith(b"%PDF"):
        xml = ei_from_pdf(data, owner)
        src = "pdf" if xml else None
    else:
        xml = data if ei_is(data) else None
        src = "xml" if xml else None
    if not xml:
        return None
    try:
        inv = ei_parse(xml)
    except EinvoiceError as e:
        print("docs: e-invoice not read:", type(e).__name__, flush=True)
        return None
    inv["source"] = src
    return inv


# ---- what the documents / receipts take over -------------------------------------------------------------------------------
def ei_details(inv):
    """The keys of receipts/extracted.py RX_KEYS from an invoice; vat_pct = the rate with the largest base (19 / 7 / 0)."""
    rates = [{"pct": r["pct"], "net": r["net"], "vat": r["vat"]} for r in inv.get("vat_rates") or []]
    pct = None
    if rates:
        def base(r):
            try:
                return Decimal(r["net"] or "0")
            except InvalidOperation:
                return Decimal(0)
        top = max(rates, key=base)["pct"]
        pct = top if top in ("19", "7", "0") else None
    s = inv.get("seller") or {}
    return {"supplier": s.get("name") or None, "vat_id": s.get("vat_id") or None, "tax_no": s.get("tax_no") or None,
            "invoice_no": inv.get("number"), "vat_pct": pct, "vat_rates": rates, "net": inv.get("net"), "vat": inv.get("vat"),
            "gross": inv.get("gross") or inv.get("payable"), "currency": inv.get("currency")}


def ei_compact(inv):
    """What the document keeps of the invoice for its readable view (doc_meta.extracted, sealed): the dict, JSON-safe."""
    keep = ("format", "kind", "number", "date", "due", "currency", "seller", "buyer", "iban", "bic", "payment_ref", "terms",
            "net", "vat", "gross", "payable", "vat_rates", "lines", "lines_more", "note", "source")
    return {k: inv.get(k) for k in keep if inv.get(k) not in (None, "", [], {})}


# ---- 2.153.0 (#2055): an incoming e-invoice in an office's documents space becomes a receipt ---------------------------------
def ei_amount(inv):
    """The document amount of an invoice (gross, else the amount due); a credit note negative (it lowers the expenses)."""
    a = inv.get("gross") or inv.get("payable")
    if not a or inv.get("kind") != "credit_note":
        return a
    try:
        v = Decimal(str(a))
    except InvalidOperation:
        return a
    return format(-v if v > 0 else v, "f")


def _ei_office(c, ws):
    """The office area whose documents space ws is (office/books.py bk_ws), or None when no office is set up there."""
    if ws and ws[0] == "o" and ws[1:].isdigit():
        oid = int(ws[1:])
        used = c.execute("SELECT 1 FROM office_settings WHERE org_id=? UNION ALL SELECT 1 FROM office_company WHERE org_id=? "
                         "UNION ALL SELECT 1 FROM office_docs WHERE org_id=? LIMIT 1", (oid, oid, oid)).fetchone()
        return oid if used else None
    if not ws or ws[0] != "u" or not ws[1:].isdigit():
        return None
    from .model import office_on, pb_personal
    uid = int(ws[1:])
    return pb_personal(c, uid, create=False) if office_on(c, uid) else None


def _ei_norm(s):
    return re.sub(r"[^0-9a-z]+", "", str(s or "").lower())


def ei_own(c, oid, inv):
    """True when inv was issued by office area oid itself (seller VAT id / tax number / name = the own company)."""
    from .ledger import ofx_company
    co, s = ofx_company(c, oid), inv.get("seller") or {}
    vat = re.sub(r"\s+", "", co.get("vat_id") or "").upper()
    if vat and vat == re.sub(r"\s+", "", s.get("vat_id") or "").upper():
        return True
    tax = re.sub(r"\D+", "", co.get("tax_number") or "")
    if len(tax) >= 6 and tax == re.sub(r"\D+", "", s.get("tax_no") or ""):
        return True
    return bool(_ei_norm(co.get("name")) and _ei_norm(co.get("name")) == _ei_norm(s.get("name")))


def ei_receipt(c, node, ws, inv, vat_pct):
    """docs/store.py process, the first time a document is read as an e-invoice: in the documents space of an office it
    becomes a receipt (rc_receipts, VAT rate of the invoice) unless it is one already or the office issued it itself.
    Never raises (an ordinary document stays)."""
    try:
        with c.savepoint():
            oid = _ei_office(c, ws)
            if not oid or ei_own(c, oid, inv) or c.execute("SELECT 1 FROM rc_receipts WHERE node_id=?", (node["id"],)).fetchone():
                return
            from ..receipts.suggest import rc_set
            rc_set(c, node, ws, None, "", None, vat=vat_pct, keep=True)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING e-invoice receipt of document {node['id']}: {type(e).__name__}", flush=True)


KIND_LABEL = {"invoice": N_("Invoice"), "credit_note": N_("Credit note")}


def ei_text(inv):
    """A readable plain text of the invoice (document text, search index)."""
    s, b = inv.get("seller") or {}, inv.get("buyer") or {}
    rows = [f"{tr(KIND_LABEL.get(inv.get('kind'), 'Invoice'))} {inv.get('number') or ''}".strip(),
            s.get("name"), *(s.get("address") or []), s.get("vat_id"),
            f"{tr('Date')}: {inv['date']}" if inv.get("date") else None,
            f"{tr('Due')}: {inv['due']}" if inv.get("due") else None,
            f"{tr('Recipient')}: {b['name']}" if b.get("name") else None]
    for ln in inv.get("lines") or []:
        rows.append(" ".join(x for x in (ln.get("qty") or "", ln.get("unit") or "", ln.get("name") or "", ln.get("net") or "") if x))
    rows += [f"{tr('Net')}: {inv['net']} {inv.get('currency') or ''}".strip() if inv.get("net") else None,
             f"{tr('VAT')}: {inv['vat']}" if inv.get("vat") else None,
             f"{tr('Gross')}: {inv['gross']} {inv.get('currency') or ''}".strip() if inv.get("gross") else None,
             f"IBAN {inv['iban']}" if inv.get("iban") else None, inv.get("note")]
    return "\n".join(r for r in rows if r)


def _fmt_money(v, cur=""):
    return f"{v} {cur}".strip() if v else ""


def ei_html(inv, title=""):
    """The readable view of an e-invoice: a plain page to read and print (every value escaped, no script, no images)."""
    e = lambda v: html.escape(str(v if v is not None else ""), quote=True)  # noqa: E731
    cur = inv.get("currency") or ""
    s, b = inv.get("seller") or {}, inv.get("buyer") or {}

    def party(label, p):
        if not p:
            return ""
        lines = [p.get("name"), *(p.get("address") or []), f"{tr('VAT ID')}: {p['vat_id']}" if p.get("vat_id") else None,
                 f"{tr('Tax number')}: {p['tax_no']}" if p.get("tax_no") else None, p.get("email")]
        return f"<div class=\"p\"><h2>{e(tr(label))}</h2>" + "".join(f"<div>{e(x)}</div>" for x in lines if x) + "</div>"

    head = [(tr("Invoice number"), inv.get("number")), (tr("Date"), inv.get("date")), (tr("Due"), inv.get("due")),
            (tr("Currency"), cur), ("IBAN", inv.get("iban")), ("BIC", inv.get("bic")), (tr("Payment reference"), inv.get("payment_ref")),
            (tr("Payment terms"), inv.get("terms"))]
    rows = "".join(f"<tr><td>{e(ln.get('name'))}</td><td class=\"n\">{e(ln.get('qty'))} {e(ln.get('unit'))}</td>"
                   f"<td class=\"n\">{e(ln.get('price'))}</td><td class=\"n\">{e(ln.get('pct') and ln['pct'] + ' %')}</td>"
                   f"<td class=\"n\">{e(ln.get('net'))}</td></tr>" for ln in inv.get("lines") or [])
    more = f"<p class=\"m\">{e(tr('{0} more lines are not shown', inv['lines_more']))}</p>" if inv.get("lines_more") else ""
    vat = "".join(f"<tr><td>{e(tr('VAT'))} {e(r.get('pct'))} %</td><td class=\"n\">{e(_fmt_money(r.get('net'), cur))}</td>"
                  f"<td class=\"n\">{e(_fmt_money(r.get('vat'), cur))}</td></tr>" for r in inv.get("vat_rates") or [])
    fmt = "XRechnung / EN 16931 (UBL)" if inv.get("format") == "ubl" else "XRechnung / ZUGFeRD / Factur-X (CII)"
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title or tr(KIND_LABEL.get(inv.get('kind'), 'Invoice')))}</title><style>
body{{font:0.95rem/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;color:#1d1b22;max-width:52rem;margin:1.5rem auto;padding:0 1rem}}
h1{{font-size:1.4rem;margin:0 0 .25rem}}h2{{font-size:.8rem;text-transform:uppercase;letter-spacing:.04em;color:#6b6475;margin:0 0 .3rem}}
.m{{color:#6b6475;font-size:.85rem}}.ps{{display:flex;flex-wrap:wrap;gap:2rem;margin:1.25rem 0}}.p{{min-width:14rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}td,th{{padding:.35rem .5rem;border-bottom:1px solid #e4e0ea;text-align:left;vertical-align:top}}
th{{font-size:.8rem;color:#6b6475;font-weight:600}}.n{{text-align:right;white-space:nowrap}}.kv td:first-child{{color:#6b6475;width:12rem}}
.tot td{{border:0}}.tot tr:last-child td{{font-weight:700;border-top:2px solid #6d4aff}}
@media print{{body{{margin:0;max-width:none}}}}
</style></head><body>
<h1>{e(tr(KIND_LABEL.get(inv.get('kind'), 'Invoice')))} {e(inv.get('number'))}</h1>
<p class="m">{e(tr('E-invoice'))}: {e(fmt)}{' · ' + e(tr('embedded in the PDF')) if inv.get('source') == 'pdf' else ''}</p>
<div class="ps">{party(N_('Seller'), s)}{party(N_('Recipient'), b)}</div>
<table class="kv">{''.join(f'<tr><td>{e(k)}</td><td>{e(v)}</td></tr>' for k, v in head if v)}</table>
{f'<table><tr><th>{e(tr("Description"))}</th><th class="n">{e(tr("Quantity"))}</th><th class="n">{e(tr("Price"))}</th><th class="n">{e(tr("VAT"))}</th><th class="n">{e(tr("Net"))}</th></tr>{rows}</table>' if rows else ''}{more}
<table class="tot">{vat}
<tr><td>{e(tr('Net'))}</td><td></td><td class="n">{e(_fmt_money(inv.get('net'), cur))}</td></tr>
<tr><td>{e(tr('VAT'))}</td><td></td><td class="n">{e(_fmt_money(inv.get('vat'), cur))}</td></tr>
<tr><td>{e(tr('Gross'))}</td><td></td><td class="n">{e(_fmt_money(inv.get('gross') or inv.get('payable'), cur))}</td></tr></table>
{f'<p>{e(inv["note"])}</p>' if inv.get('note') else ''}
<p class="m">{e(tr('Print or save as PDF with the print function of your browser.'))}</p>
</body></html>"""
