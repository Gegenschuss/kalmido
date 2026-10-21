#!/usr/bin/env python3
"""2.146.0 API tests, part A (#2451): receiving e-invoices -- XRechnung as UBL and as CII, ZUGFeRD / Factur-X (the XML
embedded in a PDF). Invented companies and figures only; every file is written here (XML as text, the PDF by hand).
freelancer-matrix: files  tenant-matrix: document
 - unit (pure Python, office/einvoice_in.py): UBL invoice, CII with 19 % and 7 %, a UBL credit note, the older ZUGFeRD 1
   names; a DOCTYPE / an ENTITY refused (also in UTF-16), broken XML, too deep, too many elements, too large, an amount
   beyond the limit dropped, any other XML is no e-invoice; the readable view escapes every value and has no script
 - a person without an organisation (private documents, org encryption on): an XRechnung UBL .xml uploaded -> recognised
   as e-invoice: date, due date, amount, currency and sender from the XML (the seller), the receipt suggestion carries
   number, net, VAT and the rate; the readable view (HTML, CSP sandbox, escaped); the stored values sealed; a CII with two
   rates; a ZUGFeRD PDF whose text says another sum: the XML wins, the PDF stays a PDF (its preview); an XML with a
   DOCTYPE and an ordinary XML stay ordinary documents (no e-invoice); "Recognise again" keeps it an e-invoice
 - mail: an .xml e-invoice attached to a mail to the forwarding address becomes a document, an ordinary .xml does not
 - rights: another person 404 on the document and its readable view
usage: p2146_a_api_test.py <datadir>   (P2146A_NOSTART=1 / KMT_NOSTART=1: the container runs already;
KALMIDO_SRC=<dir with kalmido/> for the unit part)"""
import email.message
import importlib.util
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

SRC = os.environ.get("KALMIDO_SRC") or os.path.join(N, "..")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]
MAILENV = ["-e", "KALMIDO_MAIL_ADDRESS=tasks@example.test", "-e", "KALMIDO_IMAP_HOST=127.0.0.1", "-e", "KALMIDO_IMAP_PORT=1143",
           "-e", "KALMIDO_IMAP_SSL=0", "-e", "KALMIDO_IMAP_USER=kalmido", "-e", "KALMIDO_IMAP_PASSWORD=secret", "-e", "KALMIDO_IMAP_INTERVAL=600",
           "-e", "KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=", "-e", "KALMIDO_ORGCRYPT_DELAY=0", "-e", "KALMIDO_DOCS_SCAN_S=2"]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


# ---- the invented e-invoices ----------------------------------------------------------------------------------------------
UBL = """<?xml version="1.0" encoding="UTF-8"?>
<ubl:Invoice xmlns:ubl="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>
  <cbc:ID>UBL-2026-0042</cbc:ID>
  <cbc:IssueDate>2026-10-05</cbc:IssueDate>
  <cbc:DueDate>2026-10-19</cbc:DueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:Note>Thank you for your order</cbc:Note>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>Beispiel Druckerei</cbc:Name></cac:PartyName>
    <cac:PostalAddress><cbc:StreetName>Druckweg 1</cbc:StreetName><cbc:CityName>Musterstadt</cbc:CityName>
      <cbc:PostalZone>12345</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>DE123456789</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Beispiel Druckerei GmbH</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Frida Freelance</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingCustomerParty>
  <cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode>
    <cac:PayeeFinancialAccount><cbc:ID>DE02 1203 0000 0000 2020 51</cbc:ID></cac:PayeeFinancialAccount></cac:PaymentMeans>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">38.00</cbc:TaxAmount>
    <cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">200.00</cbc:TaxableAmount><cbc:TaxAmount currencyID="EUR">38.00</cbc:TaxAmount>
      <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID="EUR">200.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">200.00</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount currencyID="EUR">238.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">238.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="C62">100</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">200.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Flyer A5 &lt;script&gt;alert(1)&lt;/script&gt;</cbc:Name>
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">2.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
</ubl:Invoice>
"""


def cii(number="CII-2026-118", grand="378.40", seller="Muster Bau GmbH", vat_id="DE987654321"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext><ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:cen.eu:en16931:2017</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter></rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument><ram:ID>{number}</ram:ID><ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">20261006</udt:DateTimeString></ram:IssueDateTime>
    <ram:IncludedNote><ram:Content>Werkvertrag</ram:Content></ram:IncludedNote></rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct><ram:Name>Arbeitszeit</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>75.00</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="HUR">4</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement><ram:ApplicableTradeTax><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>19</ram:RateApplicablePercent></ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>300.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation></ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct><ram:Name>Fachbuch</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>20.00</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">1</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement><ram:ApplicableTradeTax><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>7</ram:RateApplicablePercent></ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>20.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation></ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty><ram:Name>{seller}</ram:Name>
        <ram:PostalTradeAddress><ram:PostcodeCode>54321</ram:PostcodeCode><ram:LineOne>Werkstraße 12</ram:LineOne><ram:CityName>Beispielort</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{vat_id}</ram:ID></ram:SpecifiedTaxRegistration></ram:SellerTradeParty>
      <ram:BuyerTradeParty><ram:Name>Frida Freelance</ram:Name></ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery/>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:PaymentReference>{number}</ram:PaymentReference>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans><ram:TypeCode>58</ram:TypeCode>
        <ram:PayeePartyCreditorFinancialAccount><ram:IBANID>DE89370400440532013000</ram:IBANID></ram:PayeePartyCreditorFinancialAccount></ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:ApplicableTradeTax><ram:CalculatedAmount>57.00</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode><ram:BasisAmount>300.00</ram:BasisAmount>
        <ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>19.00</ram:RateApplicablePercent></ram:ApplicableTradeTax>
      <ram:ApplicableTradeTax><ram:CalculatedAmount>1.40</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode><ram:BasisAmount>20.00</ram:BasisAmount>
        <ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>7.00</ram:RateApplicablePercent></ram:ApplicableTradeTax>
      <ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime><udt:DateTimeString format="102">20261020</udt:DateTimeString></ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>320.00</ram:LineTotalAmount><ram:TaxBasisTotalAmount>320.00</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">58.40</ram:TaxTotalAmount><ram:GrandTotalAmount>{grand}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>{grand}</ram:DuePayableAmount></ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""


CREDIT = UBL.replace("ubl:Invoice", "ubl:CreditNote").replace("xsd:Invoice-2", "xsd:CreditNote-2").replace("UBL-2026-0042", "GS-7") \
    .replace("<cbc:DueDate>2026-10-19</cbc:DueDate>", "").replace("cac:InvoiceLine", "cac:CreditNoteLine").replace("cbc:InvoicedQuantity", "cbc:CreditedQuantity")
ZF1 = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryDocument xmlns:rsm="urn:ferd:CrossIndustryDocument:invoice:1p0"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:12"
  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:15">
  <rsm:HeaderExchangedDocument><ram:ID>ZF1-9</ram:ID><ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">20250102</udt:DateTimeString></ram:IssueDateTime></rsm:HeaderExchangedDocument>
  <rsm:SpecifiedSupplyChainTradeTransaction>
    <ram:ApplicableSupplyChainTradeAgreement><ram:SellerTradeParty><ram:Name>Alt Händler KG</ram:Name></ram:SellerTradeParty></ram:ApplicableSupplyChainTradeAgreement>
    <ram:ApplicableSupplyChainTradeSettlement><ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementMonetarySummation><ram:TaxBasisTotalAmount>10.00</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">1.90</ram:TaxTotalAmount><ram:GrandTotalAmount>11.90</ram:GrandTotalAmount></ram:SpecifiedTradeSettlementMonetarySummation>
    </ram:ApplicableSupplyChainTradeSettlement></rsm:SpecifiedSupplyChainTradeTransaction>
</rsm:CrossIndustryDocument>
"""
DOCTYPE = UBL.replace('<?xml version="1.0" encoding="UTF-8"?>', '<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">]>')
OTHER = """<?xml version="1.0"?><config><item name="a">1</item></config>"""


def esc(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def zugferd_pdf(lines, xml, name="factur-x.xml"):
    """A one-page PDF with a text layer and an embedded e-invoice (EmbeddedFiles + AF, written by hand, no library)."""
    stream = ("BT /F1 12 Tf 60 740 Td 16 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET").encode("latin-1")
    xb = xml.encode("utf-8")
    nm = f"({name})".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles << /Names [" + nm + b" 6 0 R] >> >> /AF [6 0 R] >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Filespec /F " + nm + b" /UF " + nm + b" /AFRelationship /Alternative /EF << /F 7 0 R /UF 7 0 R >> >>",
            b"<< /Type /EmbeddedFile /Subtype /text#2Fxml /Length %d >>\nstream\n" % len(xb) + xb + b"\nendstream"]
    out, offs = b"%PDF-1.7\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


# ---- unit: the reader -----------------------------------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location("p2146a_einv", os.path.join(SRC, "kalmido", "office", "einvoice_in.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

u = E.ei_parse(UBL.encode())
check(u["format"] == "ubl" and u["kind"] == "invoice" and u["number"] == "UBL-2026-0042", f"UBL: format, kind, number {u['number']}")
check((u["date"], u["due"], u["currency"]) == ("2026-10-05", "2026-10-19", "EUR"), f"UBL: dates + currency {u['date']} {u['due']}")
check(u["seller"].get("name") == "Beispiel Druckerei GmbH" and u["seller"].get("vat_id") == "DE123456789", f"UBL: seller {u['seller']}")
check(u["buyer"].get("name") == "Frida Freelance", "UBL: buyer")
check((u["net"], u["vat"], u["gross"], u["iban"]) == ("200.00", "38.00", "238.00", "DE02120300000000202051"), f"UBL: sums + IBAN {u['net']} {u['vat']} {u['gross']} {u['iban']}")
check(u["vat_rates"] and u["vat_rates"][0]["pct"] == "19" and u["vat_rates"][0]["net"] == "200.00", f"UBL: the rate {u['vat_rates']}")
check(len(u["lines"]) == 1 and u["lines"][0]["qty"] == "100" and u["lines"][0]["price"] == "2.00", f"UBL: the line {u['lines']}")
d = E.ei_details(u)
check(d["supplier"] == "Beispiel Druckerei GmbH" and d["invoice_no"] == "UBL-2026-0042" and d["vat_pct"] == "19" and d["gross"] == "238.00",
      f"UBL: the receipt suggestion {d}")
c2 = E.ei_parse(cii().encode())
check(c2["format"] == "cii" and c2["number"] == "CII-2026-118" and c2["date"] == "2026-10-06" and c2["due"] == "2026-10-20", f"CII: number + dates {c2['date']} {c2['due']}")
check((c2["net"], c2["vat"], c2["gross"]) == ("320.00", "58.40", "378.40") and c2["iban"] == "DE89370400440532013000", "CII: sums + IBAN")
check(sorted((r["pct"], r["net"], r["vat"]) for r in c2["vat_rates"]) == [("19", "300.00", "57.00"), ("7", "20.00", "1.40")], f"CII: two rates {c2['vat_rates']}")
check(E.ei_details(c2)["vat_pct"] == "19" and c2["seller"].get("vat_id") == "DE987654321", "CII: the larger base decides the rate, VAT id")
check([ln["name"] for ln in c2["lines"]] == ["Arbeitszeit", "Fachbuch"] and c2["lines"][0]["unit"] == "HUR", "CII: the lines")
cn = E.ei_parse(CREDIT.encode())
check(cn["kind"] == "credit_note" and cn["number"] == "GS-7" and len(cn["lines"]) == 1 and cn["due"] is None, f"UBL credit note {cn['kind']} {cn['due']}")
z1 = E.ei_parse(ZF1.encode())
check(z1["number"] == "ZF1-9" and z1["gross"] == "11.90" and z1["seller"].get("name") == "Alt Händler KG", f"ZUGFeRD 1 names {z1['gross']}")
check(E.ei_is(UBL.encode()) and E.ei_is(cii().encode()) and E.ei_is(ZF1.encode()), "ei_is: the e-invoices")
check(not E.ei_is(OTHER.encode()) and not E.ei_is(b"%PDF-1.4") and not E.ei_is(b"hello <Invoice"), "ei_is: other files are no e-invoice")


def refused(data, word):
    try:
        E.ei_parse(data)
    except E.EinvoiceError as e:
        return word.lower() in str(e).lower()
    return False


check(refused(DOCTYPE.encode(), "DOCTYPE"), "a DOCTYPE is refused before parsing")
check(refused(UBL.replace("<cbc:Note>", "<!ENTITY x 'y'><cbc:Note>").encode(), "ENTITY"), "an ENTITY is refused")
check(refused(DOCTYPE.replace('<?xml version="1.0"?>', "").encode("utf-16"), "DOCTYPE"), "a DOCTYPE in UTF-16 is refused too")
check(refused(UBL[:600].encode(), "broken"), "broken XML: a clear message")
deep = UBL.replace("<cbc:Note>Thank you for your order</cbc:Note>", "<x>" * 60 + "</x>" * 60)
check(refused(deep.encode(), "nested"), "too deeply nested: refused")
many = UBL.replace("<cbc:Note>Thank you for your order</cbc:Note>", "<x/>" * (E.ELEMENTS_MAX + 10))
check(refused(many.encode(), "large"), "too many elements: refused")
check(refused(b" " * (E.XML_MAX + 1), "MB"), "too large: refused before parsing")
check(refused(OTHER.encode(), "not an e-invoice"), "any other XML: not an e-invoice")
big = E.ei_parse(cii(grand="99999999999999.00").encode())
check(big["gross"] is None and big["net"] == "320.00", "an amount beyond the limit is dropped")
page = E.ei_html(u, "x")
check("<script>" not in page and "&lt;script&gt;" in page and "Beispiel Druckerei GmbH" in page and "238.00" in page, "the readable view escapes, shows seller + gross")
check("<script" not in page.lower().replace("&lt;script", ""), "the readable view has no script")
check("UBL-2026-0042" in E.ei_text(u) and "238.00" in E.ei_text(u), "the readable text (search index)")


# ---- the server -------------------------------------------------------------------------------------------------------------
def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def until(fn, secs=60):
    t = time.time()
    while time.time() - t < secs:
        x = fn()
        if x:
            return x
        time.sleep(0.5)
    return fn()


def upload(s, name, data, mime):
    r = s.post(B + "/api/docs", data={"ws": "private"}, files=[("files", (name, data, mime))])
    assert r.ok, r.text
    return r.json()["ids"][0]


def done(s, nid, secs=90):
    return until(lambda: (lambda r: r.json() if r.ok and r.json()["state"] in ("done", "failed") else None)(s.get(B + f"/api/docs/{nid}")), secs)


if not (os.environ.get("P2146A_NOSTART") or os.environ.get("KMT_NOSTART")):
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(os.path.join(DATA, "mail", "in"), exist_ok=True)
    subprocess.run(["cp", os.path.join(N, "stub_mail.py"), DATA])
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA],
                       env=dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + " ".join(MAILENV)), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_mail.py"])
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
assert A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol Other", "password": "password123", "email": "carol@example.com"}).ok
Ca = login(B, "carol")
Ca.patch(B + "/api/settings", json={"lang": "en", "features": "docs,files,office", "tour": "done"})
FID, Fr = freelancer(B, A)  # freelancer-matrix: files (the own private documents and receipts)

# ---- XRechnung UBL as .xml
n1 = upload(Fr, "rechnung.xml", UBL.encode(), "application/xml")
d1 = done(Fr, n1)
check(d1 and d1["state"] == "done" and d1["method"] == "e-invoice", f"UBL .xml: recognised as e-invoice ({d1 and (d1['state'], d1['method'], d1['error'])})")
if d1:
    check((d1["date"], d1["due"], d1["amount"], d1["currency"]) == ("2026-10-05", "2026-10-19", "238.00", "EUR"),
          f"UBL: date, due, amount, currency from the XML {(d1['date'], d1['due'], d1['amount'], d1['currency'])}")
    check((d1.get("sender") or {}).get("name") == "Beispiel Druckerei GmbH", f"UBL: the seller is the sender {d1.get('sender')}")
    check(d1["auto"].get("amount") == "e-invoice" and d1["auto"].get("sender") == "e-invoice", f"UBL: the origin e-invoice is noted {d1['auto']}")
    check((d1.get("einvoice") or {}).get("format") == "ubl" and d1["einvoice"]["source"] == "xml", f"UBL: the document says e-invoice {d1.get('einvoice')}")
    x = d1.get("extracted") or {}
    check(x.get("invoice_no") == "UBL-2026-0042" and x.get("net") == "200.00" and x.get("vat") == "38.00" and x.get("vat_pct") == "19",
          f"UBL: the receipt suggestion from the XML {x}")
    check(x.get("new") == ["vat_pct"], f"UBL: only the VAT rate is left to take over {x.get('new')}")
    check("UBL-2026-0042" in (d1.get("text") or "") and "<cbc:" not in (d1.get("text") or ""), "UBL: the text is the readable invoice, not the XML")
    check(not d1["thumb"], "UBL: no preview image of an XML")
r = Fr.get(B + f"/api/docs/{n1}/einvoice")
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("text/html"), f"the readable view {r.status_code}")
check("sandbox" in r.headers.get("Content-Security-Policy", "") and "script-src" not in r.headers.get("Content-Security-Policy", ""), "the readable view: CSP sandbox, no script")
check("&lt;script&gt;" in r.text and "<script>" not in r.text and "238.00" in r.text and "DE02120300000000202051" in r.text, "the readable view: escaped, sums, IBAN")
raw = dbx("SELECT extracted FROM doc_meta WHERE node_id=?", (n1,))[0][0]
check(raw.startswith("kenc1:") and "Druckerei" not in raw, f"the e-invoice values are stored sealed ({raw[:10]})")
check(Ca.get(B + f"/api/docs/{n1}").status_code == 404 and Ca.get(B + f"/api/docs/{n1}/einvoice").status_code == 404, "another person: 404 (document + view)")
check(A.get(B + f"/api/docs/{n1}/einvoice").status_code == 404, "the instance admin: 404 on a private document")
# Recognise again: still an e-invoice
r = Fr.post(B + f"/api/docs/{n1}/redo")
if r.status_code != 404:
    d1b = until(lambda: (lambda j: j if j["state"] == "done" and j.get("einvoice") else None)(Fr.get(B + f"/api/docs/{n1}").json()), 60)
    check(bool(d1b) and d1b["amount"] == "238.00", "recognised again: still the e-invoice")

# ---- XRechnung CII with two rates (an existing sender with another legal-form spelling is found)
n2 = upload(Fr, "xrechnung-cii.xml", cii().encode(), "text/xml")
d2 = done(Fr, n2)
check(d2 and d2["method"] == "e-invoice" and d2["amount"] == "378.40" and d2["due"] == "2026-10-20", f"CII: amount + due {d2 and (d2['amount'], d2['due'])}")
if d2:
    x = d2.get("extracted") or {}
    check(sorted((v["pct"], v["vat"]) for v in x.get("vat_rates") or []) == [("19", "57.00"), ("7", "1.40")], f"CII: both rates {x.get('vat_rates')}")
    check((d2.get("sender") or {}).get("name") == "Muster Bau GmbH", "CII: the seller is the sender")
n2b = upload(Fr, "zweite.xml", cii(number="CII-2026-119", seller="Muster Bau").encode(), "application/xml")
d2b = done(Fr, n2b)
check(d2b and (d2b.get("sender") or {}).get("id") == (d2.get("sender") or {}).get("id"), "a second invoice of the same company: the same sender")

# ---- ZUGFeRD / Factur-X: the PDF's text says another sum, the XML wins
pdf = zugferd_pdf(["Rechnung CII-2026-200", "Datum 01.10.2026", "Summe 9,99 EUR"], cii(number="CII-2026-200", grand="378.40"))
n3 = upload(Fr, "zugferd.pdf", pdf, "application/pdf")
d3 = done(Fr, n3)
check(d3 and d3["method"] == "e-invoice" and d3["amount"] == "378.40" and d3["date"] == "2026-10-06", f"ZUGFeRD PDF: the XML's values {d3 and (d3['method'], d3['amount'], d3['date'])}")
check(d3 and (d3.get("einvoice") or {}).get("source") == "pdf" and "Summe" in (d3.get("text") or ""), "ZUGFeRD PDF: source pdf, the text layer stays the text")
check(Fr.get(B + f"/api/docs/{n3}/einvoice").status_code == 200, "ZUGFeRD PDF: the readable view too")
pdf2 = zugferd_pdf(["Rechnung", "Summe 9,99 EUR"], cii(number="ZF-NAME", grand="10.00"), name="ZUGFeRD-invoice.xml")
d3b = done(Fr, upload(Fr, "zf2.pdf", pdf2, "application/pdf"))
check(d3b and d3b["method"] == "e-invoice" and d3b["amount"] == "10.00", "ZUGFeRD-invoice.xml (ZUGFeRD 2.0 name) is read too")
d3c = done(Fr, upload(Fr, "plain.pdf", zugferd_pdf(["Brief"], OTHER, name="data.xml"), "application/pdf"))
check(d3c and d3c["method"] != "e-invoice" and not d3c.get("einvoice"), "a PDF with another XML attached: an ordinary PDF")

# ---- refused / other XML: ordinary documents
d4 = done(Fr, upload(Fr, "doctype.xml", DOCTYPE.encode(), "application/xml"))
check(d4 and d4["method"] != "e-invoice" and not d4.get("einvoice") and d4["auto"].get("amount") != "e-invoice", f"an XML with a DOCTYPE: no e-invoice ({d4 and d4['method']})")
d5 = done(Fr, upload(Fr, "config.xml", OTHER.encode(), "application/xml"))
check(d5 and d5["state"] == "done" and not d5.get("einvoice"), "an ordinary XML: an ordinary document")
check(Fr.get(B + f"/api/docs/{d5['id'] if d5 else 0}/einvoice").status_code == 404, "an ordinary XML: no readable view (404)")

# ---- mail: the forwarding address takes an e-invoice .xml, not any other XML
r = Fr.post(B + "/api/docs/mail", json={"ws": "private"})
check(r.ok and "+d" in r.json().get("address", ""), f"the freelancer's forwarding address ({r.text[:100]})")
if r.ok:
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "rechnung@example.com", r.json()["address"], "Ihre Rechnung", "<p2146a-1@example.com>"
    m.set_content("Anbei die XRechnung")
    m.add_attachment(cii(number="MAIL-1").encode(), maintype="application", subtype="xml", filename="xrechnung.xml")
    m.add_attachment(OTHER.encode(), maintype="application", subtype="xml", filename="config.xml")
    open(os.path.join(DATA, "mail", "in", "1.eml"), "wb").write(bytes(m))
    A.post(B + "/api/admin/mail/poll")
    got = until(lambda: dbx("SELECT node_id, ext_id FROM doc_meta WHERE source='mail'"), 40)
    check(len(got) == 1 and got[0][1].endswith(":0"), f"the mail's e-invoice became a document, the other XML not ({got})")
    if got:
        dm = done(Fr, got[0][0])
        check(dm and dm["method"] == "e-invoice" and dm["amount"] == "378.40", f"the mailed e-invoice is read {dm and (dm['method'], dm['amount'])}")

print(f"p2146_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
