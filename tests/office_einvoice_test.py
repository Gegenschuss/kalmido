#!/usr/bin/env python3
"""2.38.0 (#1021 P5): the e-invoice XML (kalmido/office/einvoice.py) and the PDF/A-3 files of invoices, no server, no container.
 - the parity invoice (invented company and client, the figures of the template's invoice 663): CII EN 16931 XML with
   the exact sums 34422.90 / 6540.35 / 40963.25 as decimal strings, type 380, seller / buyer / payment / period / due
   date; the module's own check (ein_check) finds nothing
 - the PDF/A-3 with the XML embedded: PDF 1.7, XMP with pdfaid part 3, the fx: schema, OutputIntent, EmbeddedFile +
   /AF, both fonts as FontFile2; pypdf reads the attachment back byte for byte
 - credit note: type 381, positive amounts, the cancelled invoice in BT-25
 - XRechnung: the profile id, BT-10 buyer reference, seller contact, electronic addresses; without a buyer reference
   the builder refuses with a reason
 - USD: BT-5 USD, BT-6 EUR, BT-111 tax in EUR (2.189.0 #2475: BT-6 / BT-111 = the home currency, e.g. GBP; CHF in a EUR office); reverse charge: category AE with reason, tax 0; a discount line as a
   negative quantity with a positive price
 - ein_check sees a broken sum and a missing mandatory term
 - writes the files to tests/.data/einvoice/ for the validators (tools/einvoice_validate.sh: veraPDF + KoSIT in CI)
usage: office_einvoice_test.py            (KALMIDO_SRC = the source tree, default ../ next to tests/)"""
import importlib.util
import io
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
OUT = os.path.join(N, ".data", "einvoice")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SRC, "kalmido", "office", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ein = load("einvoice")
pdf = load("pdf")
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    print("pypdf is needed (tests/requirements.txt)")
    sys.exit(2)


# ---------------------------------------------------------------- fixture: the parity invoice (invented names)
def money_de(s):
    v = float(s)
    t = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 else "") + t + " €"


SENDER = {"name": "Studio Nordlicht GmbH", "street": "Hafenstraße 12", "zip": "20457", "city": "Hamburg", "country": "DE",
          "email": "post@beispiel-studio.example", "phone": "+49 40 000000", "tax_number": "12/345/67890", "vat_id": "DE123456789",
          "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank", "register_court": "Amtsgericht Hamburg",
          "register_no": "HRB 00000", "managing_directors": "Jana Muster"}
RECIPIENT = {"name": "Beispielkunde AG", "lines": ["Beispielkunde AG", "Marktstraße 5", "50667 Köln"], "street": "Marktstraße 5", "zip": "50667",
             "city": "Köln", "country": "DE", "vat_id": "DE987654321", "customer_no": "K-0042", "buyer_reference": "04011000-12345-03",
             "email_invoice": "rechnung@beispielkunde.example"}


def item(pos, title, rate, qty=1, net=None, unit="flat"):
    net = net if net is not None else f"{qty * float(rate):.2f}"
    return {"kind": "item", "pos": pos, "title": title, "qty": qty, "qty_text": str(qty), "unit": unit, "unit_text": "pauschal", "rate": float(rate),
            "rate_text": money_de(rate), "tax": "standard", "tax_pct": 19, "total": float(net), "total_text": money_de(net), "net": net, "tax_amount": f"{float(net) * 0.19:.2f}"}


def fixture(kind="invoice", lang="de", currency="EUR", fmt="zugferd", vat_note_key="", paid="0.00"):
    de = lang == "de"
    lines = [{"kind": "heading", "title": "FILMHERSTELLUNG OHNE ANKAUF VON ROH- UND PROJEKTDATEN"},
             item(1, "Filmherstellung", "32840.40"),
             {"kind": "heading", "title": "Zusatzkosten:"},
             item(2, "Sprachfassung EN", "1215.00"), item(3, "Cube-Integration in UI", "262.50"), item(4, "Webhosting (3 Monate)", "105.00")]
    net, tax, gross = "34422.90", "6540.35", "40963.25"
    if vat_note_key:
        tax, gross = "0.00", net
        for ln in lines:
            if ln["kind"] == "item":
                ln["tax_pct"] = 0
                ln["tax_amount"] = "0.00"
    tot = {"net": net, "net_text": money_de(net), "tax_lines": [] if vat_note_key else [{"pct": "19", "base": net, "amount": tax, "label": "19 % MwSt.", "base_text": money_de(net), "amount_text": money_de(tax)}],
           "tax": tax, "tax_text": money_de(tax), "gross": gross, "gross_text": money_de(gross), "show_tax_lines": True,
           "rows": [["Zwischensumme:", money_de(net)]] + ([] if vat_note_key else [["19% MwSt.:", money_de(tax)]]) + [["Rechnungsbetrag:", money_de(gross)]],
           "currency": currency, "fx_rate": "1.09" if currency == "USD" else None, "fx_note": "", "paid": paid, "open": f"{float(gross) - float(paid):.2f}",
           "vat_note": "", "vat_note_key": vat_note_key}
    if currency == "USD":
        tot["tax_eur"] = f"{float(tax) / 1.09:.2f}"
        tot["gross_eur"] = f"{float(gross) / 1.09:.2f}"
        tot["fx_line"] = f"Steuerbetrag entspricht {money_de(tot['tax_eur'])}, Kurs 1 EUR = 1,09 USD"
    number = {"invoice": "RE-2026-663", "credit": "GS-2026-001"}[kind]
    m = {"kind": kind, "lang": lang, "currency": currency, "locked": True, "status": "issued", "number": number, "date": "2026-05-08",
         "date_text": "08.05.2026", "title": {"invoice": "Rechnung" if de else "Invoice", "credit": "Gutschrift" if de else "Credit note"}[kind],
         "project_title": "Interaktiver Film (5 Module + Intro), Hauptfilm 1:30-2:00 min, Sprachadaption EN", "project_ref": "PO-2026-0001",
         "order_ref": "PO-2026-0001", "service_from": "2026-04-01", "service_to": "2026-05-31", "service_period_text": "April-Mai 2026",
         "due_date": "2026-05-22", "due_date_text": "22.05.2026", "payment_days": 14, "vat_mode": "novat" if vat_note_key else "vat",
         "vat_note_key": vat_note_key, "vat_note_text": "", "einvoice_format": fmt,
         "company": {"name": SENDER["name"], "lines": ["Hafenstraße 12", "20457 Hamburg"], "contact_lines": ["Tel. +49 40 000000", "E-Mail post@beispiel-studio.example"],
                     "register_lines": ["Registergericht: Amtsgericht Hamburg HRB 00000", "Geschäftsführung: Jana Muster"],
                     "bank_lines": ["Beispielbank", "IBAN DE02 1203 0000 0000 2020 51", "BIC BYLADEM1001", "USt-IdNr. DE123456789"],
                     "sender_line": "Studio Nordlicht GmbH · Hafenstraße 12 · 20457 Hamburg", "logo_path": None, "color": "#2f5d8a"},
         "sender_fields": dict(SENDER), "recipient": dict(RECIPIENT),
         "meta": [["Rechnung Nr.:", number], ["Ref./PO-Nr.:", "PO-2026-0001"], ["Datum:", "08.05.2026"], ["Leistungszeitraum:", "April-Mai 2026"], ["Fällig am:", "22.05.2026"]],
         "intro": "Sehr geehrte Damen und Herren,\nfür das oben genannte Projekt erlauben wir uns Ihnen folgende Leistungen in Rechnung zu stellen:",
         "lines": lines, "totals": tot,
         "cancels": {"id": 663, "number": "RE-2026-663", "date": "2026-05-08", "date_text": "08.05.2026"} if kind == "credit" else None,
         "payment": {"iban": SENDER["iban"], "bic": SENDER["bic"], "bank_name": "Beispielbank", "text": "Zahlbar bis 22.05.2026 ohne Abzug."},
         "rights": {"title": "Rechteübertragung", "rows": [["Zeitliche Auswertung", "unbegrenzt"], ["Räumliche Auswertung", "weltweit"],
                                                           ["Mediale Auswertung", "intern, web, unpaid media, public screening"]],
                    "exceptions": "", "exclusive": 0, "note": "Im Übrigen bleibt es bei den Regelungen unter §3 des RV."},
         "closing": "Der Gesamtbetrag wird mit Erhalt dieser Rechnung zur Zahlung fällig. Es gelten unsere allgemeinen Geschäftsbedingungen.",
         "signature": "Mit freundlichen Grüßen", "signature_name": "Jana Muster", "valid_note": "", "fields": [],
         "labels": {"invoice_no": "Rechnung Nr.", "pos": "Pos.", "title": "Leistung", "qty": "x", "unit_price": "Preis", "vat": "%", "total": "Gesamt",
                    "net_total": "Zwischensumme:", "gross_total": "Rechnungsbetrag:", "rights": "Rechteübertragung", "page_of": "Seite {x} von {y}"},
         "formats": {"date": "dd.mm.yyyy", "decimal": ",", "thousands": ".", "currency_pos": "after"}, "internal": None}
    return m


def t(xml, path):
    from xml.etree import ElementTree as ET
    root = ET.fromstring(xml)
    x = root.find(path, ein.NS)
    return (x.text or "").strip() if x is not None else None


os.makedirs(OUT, exist_ok=True)
for fn in os.listdir(OUT):
    os.remove(os.path.join(OUT, fn))

# ---------------------------------------------------------------- 1. the parity invoice as ZUGFeRD EN 16931
m = fixture()
xml = ein.ein_build(m, "zugferd")
check(xml.startswith(b'<?xml version="1.0" encoding="UTF-8"?>') and b"CrossIndustryInvoice" in xml, "a CII XML document")
check(t(xml, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID") == "urn:cen.eu:en16931:2017", "profile EN 16931")
check(t(xml, "rsm:ExchangedDocument/ram:ID") == "RE-2026-663" and t(xml, "rsm:ExchangedDocument/ram:TypeCode") == "380", "number and type 380")
check(t(xml, "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString") == "20260508", "issue date YYYYMMDD")
S = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"
MS = S + "ram:SpecifiedTradeSettlementHeaderMonetarySummation/"
check(t(xml, MS + "ram:LineTotalAmount") == "34422.90" and t(xml, MS + "ram:TaxBasisTotalAmount") == "34422.90", "BT-106 / BT-109 = 34422.90 (exact string)")
check(t(xml, MS + "ram:TaxTotalAmount") == "6540.35" and t(xml, MS + "ram:GrandTotalAmount") == "40963.25" and t(xml, MS + "ram:DuePayableAmount") == "40963.25",
      "BT-110 6540.35, BT-112 / BT-115 40963.25")
check(t(xml, S + "ram:ApplicableTradeTax/ram:CalculatedAmount") == "6540.35" and t(xml, S + "ram:ApplicableTradeTax/ram:BasisAmount") == "34422.90"
      and t(xml, S + "ram:ApplicableTradeTax/ram:CategoryCode") == "S" and t(xml, S + "ram:ApplicableTradeTax/ram:RateApplicablePercent") == "19", "tax breakdown S 19 %")
A = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/"
check(t(xml, A + "ram:SellerTradeParty/ram:Name") == "Studio Nordlicht GmbH" and t(xml, A + "ram:SellerTradeParty/ram:PostalTradeAddress/ram:CountryID") == "DE"
      and t(xml, A + "ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID") in ("12/345/67890", "DE123456789"), "seller with address and tax ids")
check(t(xml, A + "ram:BuyerTradeParty/ram:Name") == "Beispielkunde AG" and t(xml, A + "ram:BuyerTradeParty/ram:PostalTradeAddress/ram:CityName") == "Köln"
      and t(xml, A + "ram:BuyerTradeParty/ram:PostalTradeAddress/ram:PostcodeCode") == "50667", "buyer with address")
check(t(xml, A + "ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID") == "PO-2026-0001", "BT-13 order reference")
check(t(xml, S + "ram:BillingSpecifiedPeriod/ram:StartDateTime/udt:DateTimeString") == "20260401" and t(xml, S + "ram:BillingSpecifiedPeriod/ram:EndDateTime/udt:DateTimeString") == "20260531", "BT-73 / BT-74 period")
check(t(xml, S + "ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString") == "20260522", "BT-9 due date")
check(t(xml, S + "ram:SpecifiedTradeSettlementPaymentMeans/ram:TypeCode") == "58" and t(xml, S + "ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeePartyCreditorFinancialAccount/ram:IBANID") == "DE02120300000000202051",
      "SEPA credit transfer with IBAN")
check(t(xml, S + "ram:InvoiceCurrencyCode") == "EUR" and t(xml, S + "ram:TaxCurrencyCode") is None, "EUR: no tax currency")
check(xml.count(b"<ram:IncludedSupplyChainTradeLineItem>") == 4 and b"<ram:LineTotalAmount>32840.40</ram:LineTotalAmount>" in xml, "four lines, the heading is no line")
check(b"34422.9<" not in xml and b"6540.351" not in xml, "no float formatting anywhere")
find = ein.ein_check(xml)
check(find == [], f"ein_check finds nothing: {find}")
with open(os.path.join(OUT, "invoice-RE-2026-663.xml"), "wb") as fh:
    fh.write(xml)

# ---------------------------------------------------------------- 2. the PDF/A-3 with the XML embedded
data = pdf.office_pdf(m, xml=xml, meta={"xml_profile": "EN 16931"})
with open(os.path.join(OUT, "invoice-RE-2026-663.pdf"), "wb") as fh:
    fh.write(data)
check(data.startswith(b"%PDF-1.7"), "PDF 1.7")
check(b"<pdfaid:part>3</pdfaid:part>" in data and b"<pdfaid:conformance>B</pdfaid:conformance>" in data, "XMP pdfaid 3 / B")
check(b"<fx:DocumentFileName>factur-x.xml</fx:DocumentFileName>" in data and b"<fx:ConformanceLevel>EN 16931</fx:ConformanceLevel>" in data
      and b"urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#" in data and b"pdfaSchema:prefix>fx<" in data, "fx: schema with its extension description")
check(b"/S /GTS_PDFA1" in data and b"/EmbeddedFile" in data and b"/AFRelationship /Alternative" in data and b"/AF [" in data, "OutputIntent, EmbeddedFile, AF")
check(data.count(b"/FontFile2") == 2, "both fonts embedded")
r = PdfReader(io.BytesIO(data))
att = r.attachments
got = att.get("factur-x.xml")
got = got[0] if isinstance(got, list) else got
check(got == xml, "pypdf reads factur-x.xml back byte for byte")
txt = "\n".join(p.extract_text() or "" for p in r.pages)
check("RE-2026-663" in txt and "Beispielkunde AG" in txt and "40.963,25" in txt and "Filmherstellung" in txt, "the printed invoice carries number, client, total")
check("Interaktiver Film" in txt and "Zahlbar bis 22.05.2026" in txt and "IBAN DE02 1203 0000 0000 2020 51" in txt, "project title, payment text and bank line printed")
check(txt.count("40.963,25") == 1 and txt.count("6.540,35") == 1, "the totals rows of the model are printed once (no doubled tax line)")

# ---------------------------------------------------------------- 3. credit note
mc = fixture("credit")
xc = ein.ein_build(mc, "zugferd")
check(t(xc, "rsm:ExchangedDocument/ram:TypeCode") == "381" and t(xc, MS + "ram:GrandTotalAmount") == "40963.25", "credit note: 381 with positive amounts")
check(t(xc, S + "ram:InvoiceReferencedDocument/ram:IssuerAssignedID") == "RE-2026-663" and t(xc, S + "ram:InvoiceReferencedDocument/ram:FormattedIssueDateTime/qdt:DateTimeString") == "20260508",
      "BT-25 the cancelled invoice")
check(ein.ein_check(xc) == [], f"credit note check: {ein.ein_check(xc)}")
with open(os.path.join(OUT, "credit-GS-2026-001.xml"), "wb") as fh:
    fh.write(xc)
with open(os.path.join(OUT, "credit-GS-2026-001.pdf"), "wb") as fh:
    fh.write(pdf.office_pdf(mc, xml=xc))

# ---------------------------------------------------------------- 4. XRechnung
mx = fixture(fmt="xrechnung")
xx = ein.ein_build(mx, "xrechnung")
check(t(xx, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID") == "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0", "XRechnung 3.0 profile")
check(t(xx, "rsm:ExchangedDocumentContext/ram:BusinessProcessSpecifiedDocumentContextParameter/ram:ID") == "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0", "BT-23 process")
check(t(xx, A + "ram:BuyerReference") == "04011000-12345-03", "BT-10 buyer reference")
check(t(xx, A + "ram:SellerTradeParty/ram:DefinedTradeContact/ram:TelephoneUniversalCommunication/ram:CompleteNumber") == "+49 40 000000"
      and t(xx, A + "ram:SellerTradeParty/ram:DefinedTradeContact/ram:EmailURIUniversalCommunication/ram:URIID") == "post@beispiel-studio.example", "seller contact (BR-DE-2)")
check(t(xx, A + "ram:SellerTradeParty/ram:URIUniversalCommunication/ram:URIID") == "post@beispiel-studio.example"
      and t(xx, A + "ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID") == "rechnung@beispielkunde.example", "BT-34 / BT-49 electronic addresses (EM)")
check(ein.ein_check(xx) == [], f"XRechnung check: {ein.ein_check(xx)}")
with open(os.path.join(OUT, "xrechnung-RE-2026-663.xml"), "wb") as fh:
    fh.write(xx)
mnr = fixture(fmt="xrechnung")
mnr["recipient"]["buyer_reference"] = ""
try:
    ein.ein_build(mnr, "xrechnung")
    check(False, "XRechnung without a buyer reference is refused")
except ein.BadInput as e:
    check("buyer reference" in str(e), f"XRechnung without a buyer reference: {e}")
xnr = ein.ein_build(mnr, "zugferd")
check(ein.ein_check(xnr) == [], "ZUGFeRD without a buyer reference is fine")

# ---------------------------------------------------------------- 5. USD, reverse charge, discount line, part payment
mu = fixture(currency="USD")
xu = ein.ein_build(mu, "zugferd")
check(t(xu, S + "ram:InvoiceCurrencyCode") == "USD" and t(xu, S + "ram:TaxCurrencyCode") == "EUR", "BT-5 USD, BT-6 EUR")
check(b'<ram:TaxTotalAmount currencyID="USD">6540.35</ram:TaxTotalAmount>' in xu and b'<ram:TaxTotalAmount currencyID="EUR">6000.32</ram:TaxTotalAmount>' in xu, "BT-110 in USD and BT-111 in EUR")
check(ein.ein_check(xu) == [], f"USD check: {ein.ein_check(xu)}")
with open(os.path.join(OUT, "invoice-usd-RE-2026-663.xml"), "wb") as fh:
    fh.write(xu)
# 2.189.0 (#2475): the tax currency (BT-6, BT-111) is the office's home currency (totals.home, missing = EUR as above)
mg = fixture(currency="USD")
mg["totals"].update({"home": "GBP", "fx_rate": "1.25", "tax_eur": "5232.28", "gross_eur": "32770.60"})
xg = ein.ein_build(mg, "zugferd")
check(t(xg, S + "ram:InvoiceCurrencyCode") == "USD" and t(xg, S + "ram:TaxCurrencyCode") == "GBP", "2.189.0 (#2475): home GBP: BT-5 USD, BT-6 GBP")
check(b'<ram:TaxTotalAmount currencyID="USD">6540.35</ram:TaxTotalAmount>' in xg and b'<ram:TaxTotalAmount currencyID="GBP">5232.28</ram:TaxTotalAmount>' in xg
      and b'currencyID="EUR"' not in xg, "2.189.0 (#2475): BT-110 in USD, BT-111 in GBP, no EUR")
check(ein.ein_check(xg) == [], f"2.189.0 (#2475): home GBP check: {ein.ein_check(xg)}")
with open(os.path.join(OUT, "invoice-gbp-home-usd-RE-2026-663.xml"), "wb") as fh:
    fh.write(xg)
mh = fixture(currency="GBP")
mh["totals"]["home"] = "GBP"
xh = ein.ein_build(mh, "zugferd")
check(t(xh, S + "ram:InvoiceCurrencyCode") == "GBP" and t(xh, S + "ram:TaxCurrencyCode") is None and xh.count(b"<ram:TaxTotalAmount") == 1,
      "2.189.0 (#2475): an invoice in the home currency GBP has no BT-6 / BT-111")
check(ein.ein_check(xh) == [], f"2.189.0 (#2475): GBP in GBP check: {ein.ein_check(xh)}")
with open(os.path.join(OUT, "invoice-gbp-RE-2026-663.xml"), "wb") as fh:
    fh.write(xh)
mc = fixture(currency="CHF")
mc["totals"].update({"fx_rate": "0.95", "tax_eur": "6884.58", "gross_eur": "43119.21"})
xch = ein.ein_build(mc, "zugferd")
check(t(xch, S + "ram:InvoiceCurrencyCode") == "CHF" and t(xch, S + "ram:TaxCurrencyCode") == "EUR"
      and b'<ram:TaxTotalAmount currencyID="EUR">6884.58</ram:TaxTotalAmount>' in xch, "2.189.0 (#2475): EUR office, invoice in CHF: BT-6 EUR, BT-111 in EUR")
check(ein.ein_check(xch) == [], f"2.189.0 (#2475): CHF check: {ein.ein_check(xch)}")
with open(os.path.join(OUT, "invoice-chf-RE-2026-663.xml"), "wb") as fh:
    fh.write(xch)
mr = fixture(vat_note_key="reverse")
xr = ein.ein_build(mr, "zugferd")
check(t(xr, S + "ram:ApplicableTradeTax/ram:CategoryCode") == "AE" and t(xr, S + "ram:ApplicableTradeTax/ram:CalculatedAmount") == "0.00"
      and t(xr, S + "ram:ApplicableTradeTax/ram:ExemptionReasonCode") == "VATEX-EU-AE" and "Reverse" in (t(xr, S + "ram:ApplicableTradeTax/ram:ExemptionReason") or ""),
      "reverse charge: AE, tax 0, reason")
check(t(xr, MS + "ram:GrandTotalAmount") == "34422.90" and ein.ein_check(xr) == [], f"reverse charge totals + check: {ein.ein_check(xr)}")
with open(os.path.join(OUT, "invoice-reverse-RE-2026-663.xml"), "wb") as fh:
    fh.write(xr)
md = fixture()
md["lines"].append({"kind": "discount", "pos": 5, "title": "Rabatt", "qty": 1, "rate": -422.90, "tax_pct": 19, "total": -422.90, "net": "-422.90"})
md["totals"].update({"net": "34000.00", "tax_lines": [{"pct": "19", "base": "34000.00", "amount": "6460.00"}], "tax": "6460.00", "gross": "40460.00", "open": "40460.00"})
xd = ein.ein_build(md, "zugferd")
check(b"<ram:ChargeAmount>422.90</ram:ChargeAmount>" in xd and b'<ram:BilledQuantity unitCode="C62">-1</ram:BilledQuantity>' in xd and b"<ram:LineTotalAmount>-422.90</ram:LineTotalAmount>" in xd,
      "discount line: positive price, negative quantity (BR-27)")
check(t(xd, MS + "ram:LineTotalAmount") == "34000.00" and t(xd, MS + "ram:GrandTotalAmount") == "40460.00" and ein.ein_check(xd) == [], f"discount totals + check: {ein.ein_check(xd)}")
# 2.38.0 review: the discount position as the invoice calculator delivers it (qty and rate positive, net negative)
mq = fixture()
mq["lines"].append({"kind": "discount", "pos": 5, "title": "Rabatt", "qty": "1", "rate": "422.90", "tax_pct": 19, "total": "-422.90", "net": "-422.90"})
mq["totals"].update({"net": "34000.00", "tax_lines": [{"pct": "19", "base": "34000.00", "amount": "6460.00"}], "tax": "6460.00", "gross": "40460.00", "open": "40460.00"})
xq = ein.ein_build(mq, "zugferd")
check(b"<ram:ChargeAmount>422.90</ram:ChargeAmount>" in xq and b'<ram:BilledQuantity unitCode="C62">-1</ram:BilledQuantity>' in xq and b"<ram:LineTotalAmount>-422.90</ram:LineTotalAmount>" in xq
      and ein.ein_check(xq) == [], f"calculator discount line: quantity -1, price positive, line total negative: {ein.ein_check(xq)}")
mp = fixture(paid="10000.00")
xp = ein.ein_build(mp, "zugferd")
check(t(xp, MS + "ram:TotalPrepaidAmount") == "10000.00" and t(xp, MS + "ram:DuePayableAmount") == "30963.25" and ein.ein_check(xp) == [], "part payment: BT-113 / BT-115")

# ---------------------------------------------------------------- 6. ein_check sees broken files
broken = xml.replace(b"<ram:GrandTotalAmount>40963.25</ram:GrandTotalAmount>", b"<ram:GrandTotalAmount>40963.26</ram:GrandTotalAmount>")
f = ein.ein_check(broken)
check(any("BR-CO-15" in x for x in f) and any("BR-CO-16" in x for x in f), f"a wrong grand total is found: {f}")
f2 = ein.ein_check(xml.replace(b"<ram:CalculatedAmount>6540.35</ram:CalculatedAmount>", b"<ram:CalculatedAmount>6540.36</ram:CalculatedAmount>"))
check(any("BR-CO-17" in x for x in f2), f"a wrong tax amount is found: {f2}")
f3 = ein.ein_check(re.sub(rb"<ram:SellerTradeParty>\s*<ram:Name>[^<]*</ram:Name>", b"<ram:SellerTradeParty><ram:Name></ram:Name>", xml))
check(any("BT-27" in x for x in f3), f"a missing seller name is found: {f3}")
check(ein.ein_check(b"<nope") and ein.ein_check(b"<a/>"), "junk gives findings, no exception")
print("files for the validators:", sorted(os.listdir(OUT)))
print(f"office_einvoice: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
